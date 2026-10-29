from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import unquote

from lsprepost_mcp.config import JSONDict


@dataclass
class ApiError(Exception):
    status: int
    code: str
    message: str


def encode_json(payload: JSONDict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def json_ok(result: JSONDict, status: int = 200) -> tuple[int, dict[str, str], bytes]:
    return status, {"Content-Type": "application/json; charset=utf-8"}, encode_json({"ok": True, "result": result})


def json_error(status: int, code: str, message: str) -> tuple[int, dict[str, str], bytes]:
    return status, {"Content-Type": "application/json; charset=utf-8"}, encode_json(
        {"ok": False, "error": {"code": code, "message": message}}
    )


def parse_json_body(body: bytes) -> JSONDict:
    try:
        payload: Any = json.loads(body.decode("utf-8"), parse_constant=reject_json_constant)
    except Exception as exc:
        raise ApiError(400, "invalid_json", f"request body is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ApiError(400, "invalid_request", "request body must be a JSON object")
    return payload


def reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant is not allowed: {value}")


def safe_relative_path(raw: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ApiError(400, "invalid_path", "relative_path is required")
    decoded = unquote(raw).replace("\\", "/")
    normalized = Path(decoded)
    if decoded.startswith("/") or PureWindowsPath(decoded).drive or normalized.is_absolute() or ".." in normalized.parts:
        raise ApiError(400, "invalid_path", "relative_path must stay inside the project")
    return normalized
