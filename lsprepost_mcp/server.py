from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lsprepost_mcp.config import JSONDict
from lsprepost_mcp.project_store import cleanup_stale_project_artifacts
from lsprepost_mcp.tools import TOOLS, tool_list


def content_response(payload: JSONDict) -> JSONDict:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        ]
    }


def handle_request(message: JSONDict) -> JSONDict | None:
    msg_id = message.get("id")
    method = message.get("method")
    raw_params = message.get("params", {})
    if raw_params is None:
        params = {}
    elif isinstance(raw_params, dict):
        params = raw_params
    else:
        return invalid_params(msg_id, "params must be an object")

    try:
        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "lsprepost-mcp", "version": "0.2.0"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = tool_list()
        elif method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str) or not name:
                return invalid_params(msg_id, "tools/call name must be a non-empty string")
            args = params.get("arguments", {})
            if args is None:
                args = {}
            if not isinstance(args, dict):
                return invalid_params(msg_id, "tools/call arguments must be an object")
            if name not in TOOLS:
                raise ValueError(f"Unknown tool: {name}")
            validate_tool_arguments(name, args, TOOLS[name][1])
            result = content_response(TOOLS[name][2](args))
        elif method in {"notifications/initialized", "initialized"}:
            return None
        else:
            raise ValueError(f"Unsupported method: {method}")

        if msg_id is None:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}
    except Exception as exc:
        if msg_id is None:
            return None
        return error_response(msg_id, -32000, str(exc))


def error_response(msg_id: Any, code: int, message: str) -> JSONDict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def invalid_params(msg_id: Any, message: str) -> JSONDict | None:
    if msg_id is None:
        return None
    return error_response(msg_id, -32602, message)


def handle_message(message: Any) -> JSONDict | list[JSONDict] | None:
    if isinstance(message, list):
        responses = []
        for item in message:
            if not isinstance(item, dict):
                responses.append(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32600, "message": "Invalid batch item"},
                    }
                )
                continue
            response = handle_request(item)
            if response is not None:
                responses.append(response)
        return responses or None
    if isinstance(message, dict):
        return handle_request(message)
    return {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32600, "message": "Invalid JSON-RPC message"},
    }


def validate_tool_arguments(name: str, args: Any, schema: JSONDict) -> None:
    validate_json_schema(args, schema, name)


def validate_json_schema(value: Any, schema: JSONDict, path: str) -> None:
    expected = schema.get("type")
    if expected is not None and not json_type_matches(value, expected):
        raise ValueError(f"{path} must be {format_expected_type(expected)}")

    enum = schema.get("enum")
    if enum is not None and value not in enum:
        raise ValueError(f"{path} must be one of {', '.join(str(item) for item in enum)}")

    if schema.get("type") == "object" or isinstance(value, dict):
        if not isinstance(value, dict):
            return
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        missing = [key for key in required if key not in value]
        if missing:
            raise ValueError(f"{path} missing required field(s): {', '.join(missing)}")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value.keys()) - set(properties.keys()))
            if unknown:
                label = "argument(s)" if "." not in path and "[" not in path else "field(s)"
                raise ValueError(f"{path} received unsupported {label}: {', '.join(unknown)}")
        for key, item in value.items():
            if key in properties:
                validate_json_schema(item, properties[key], f"{path}.{key}")
            elif isinstance(schema.get("additionalProperties"), dict):
                validate_json_schema(item, schema["additionalProperties"], f"{path}.{key}")

    if schema.get("type") == "array" or isinstance(value, list):
        if not isinstance(value, list):
            return
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                validate_json_schema(item, item_schema, f"{path}[{index}]")


def json_type_matches(value: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return any(json_type_matches(value, item) for item in expected)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (
            (isinstance(value, int) or isinstance(value, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    if expected == "null":
        return value is None
    return True


def format_expected_type(expected: Any) -> str:
    if isinstance(expected, list):
        return " or ".join(str(item) for item in expected)
    return str(expected)


def reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant is not allowed: {value}")


def main() -> int:
    try:
        cleanup = cleanup_stale_project_artifacts()
        if cleanup.get("errors"):
            sys.stderr.write(f"Runtime cleanup warnings: {json.dumps(cleanup['errors'], ensure_ascii=False)}\n")
            sys.stderr.flush()
    except Exception as exc:
        sys.stderr.write(f"Runtime cleanup skipped: {exc}\n")
        sys.stderr.flush()
    for line in sys.stdin:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            message = json.loads(stripped, parse_constant=reject_json_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            sys.stderr.write(f"Invalid JSON-RPC message: {exc}\n")
            sys.stderr.flush()
            continue

        response = handle_message(message)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
