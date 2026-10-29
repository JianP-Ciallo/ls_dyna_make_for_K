from __future__ import annotations

from pathlib import Path

from .config import JSONDict, MODEL_RESOURCE_EXPORTS_DIR
from .model_library import (
    export_model_resource,
    get_model_resource,
    list_model_resources,
    validate_model_resource,
)
from .paths import checked_child, safe_project_name


def _public_resource(resource: JSONDict) -> JSONDict:
    return {key: value for key, value in resource.items() if not key.startswith("_")}


def tool_list_model_resources(_: JSONDict) -> JSONDict:
    resources = list_model_resources()
    return {"resources": resources, "count": len(resources)}


def tool_get_model_resource(args: JSONDict) -> JSONDict:
    resource_id = str(args.get("resource_id", ""))
    return {"resource": _public_resource(get_model_resource(resource_id))}


def tool_validate_model_resource(args: JSONDict) -> JSONDict:
    return validate_model_resource(str(args.get("resource_id", "")))


def tool_export_model_resource(args: JSONDict) -> JSONDict:
    resource_id = str(args.get("resource_id", ""))
    export_name = safe_project_name(str(args.get("export_name") or resource_id))
    filename = str(args.get("filename", "component.k")).strip()
    if not filename or Path(filename).name != filename or not filename.lower().endswith(".k"):
        raise ValueError("filename must be a plain .k filename")
    export_dir = checked_child(MODEL_RESOURCE_EXPORTS_DIR, export_name)
    export_dir.mkdir(parents=True, exist_ok=True)
    target = export_dir / filename
    exported = export_model_resource(resource_id, target)
    validation = validate_model_resource(resource_id)
    return {
        "resource_id": resource_id,
        "export_dir": str(export_dir),
        "keyword_path": str(exported),
        **validation,
    }
