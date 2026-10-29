from __future__ import annotations

from .config import JSONDict
from .materials import load_materials, validate_material_resource
from .phase18_resource_review import load_phase18_review_manifest, validate_phase18_review_manifest
from .structural_resources import (
    get_structural_resource,
    list_structural_resources,
    load_structural_resources,
    validate_structural_catalog_closure,
)


def tool_list_structural_resources(_: JSONDict) -> JSONDict:
    resources = list_structural_resources()
    return {"resources": resources, "count": len(resources)}


def tool_get_structural_resource(args: JSONDict) -> JSONDict:
    return {"resource": get_structural_resource(str(args.get("resource_id", "")))}


def tool_validate_phase18_resource_review(_: JSONDict) -> JSONDict:
    manifest = load_phase18_review_manifest()
    records = manifest.get("resources")
    if not isinstance(records, list):
        raise ValueError("Phase 18 review manifest resources must be a list")
    material_ids = {
        str(record["id"])
        for record in records
        if isinstance(record, dict) and record.get("resource_kind") == "material"
    }
    structural_ids = {
        str(record["id"])
        for record in records
        if isinstance(record, dict) and record.get("resource_kind") == "structural"
    }
    available_materials = load_materials()
    available_structural = load_structural_resources()
    materials = {resource_id: available_materials[resource_id] for resource_id in sorted(material_ids)}
    structural = {resource_id: available_structural[resource_id] for resource_id in sorted(structural_ids)}
    for resource in materials.values():
        validate_material_resource(resource)
    closure = validate_structural_catalog_closure(list(structural.values()), materials)
    report = validate_phase18_review_manifest(manifest, {**materials, **structural})
    return {
        **report,
        "material_count": len(materials),
        "structural_count": len(structural),
        "section_count": closure["section_count"],
        "curve_point_count": closure["curve_point_count"],
        "part_count": closure["part_count"],
        "set_count": closure["set_count"],
        "coupling_count": closure["coupling_count"],
        "requires_project_review": True,
    }
