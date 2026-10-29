from __future__ import annotations

from .config import JSONDict
from .materials import get_material, list_materials, validate_material_resource


def tool_list_materials(_: JSONDict) -> JSONDict:
    materials = list_materials()
    return {"materials": materials, "count": len(materials)}


def tool_get_material(args: JSONDict) -> JSONDict:
    material_id = str(args.get("material_id") or args.get("name") or "")
    return {"material": get_material(material_id)}


def tool_validate_material_resource(args: JSONDict) -> JSONDict:
    material_id = str(args.get("material_id", ""))
    material = get_material(material_id)
    report = validate_material_resource(material)
    return {
        **report,
        "effective_validation_status": material.get("effective_validation_status", "source_reference"),
        "requires_project_review": bool(material.get("requires_project_review", True)),
    }
