from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from pathlib import Path

from .config import DEFAULT_UNIT_SYSTEM, JSONDict, STRUCTURAL_RESOURCES_DIR
from .io import read_json
from .materials import validate_material_resource
from .phase18_reference_naming import MATERIAL_RESOURCE_ALIASES, STRUCTURAL_RESOURCE_ALIASES
from .phase18_resource_review import SOURCE_2K_SHA256, apply_effective_review
from .resource_aliases import build_alias_index, normalize_resource_identity, resolve_resource_id


def _structural_files(root: Path = STRUCTURAL_RESOURCES_DIR) -> list[Path]:
    roots = [root]
    if root == STRUCTURAL_RESOURCES_DIR:
        from .config import ROOT
        from .source_rebuild_resources import STRUCTURAL_RELATIVE
        roots.append(ROOT / STRUCTURAL_RELATIVE)
        from .impact_1788_resources import STRUCTURAL_RELATIVE as SECOND_STRUCTURAL_RELATIVE
        roots.append(ROOT / SECOND_STRUCTURAL_RELATIVE)
        from .b120_spg_sale_resources import STRUCTURAL_RELATIVE as THIRD_STRUCTURAL_RELATIVE
        roots.append(ROOT / THIRD_STRUCTURAL_RELATIVE)
    return sorted((path for directory in roots for path in directory.rglob("*.json")), key=lambda item: str(item).lower())


def load_structural_resources(root: Path = STRUCTURAL_RESOURCES_DIR) -> dict[str, JSONDict]:
    resources: dict[str, JSONDict] = {}
    for path in _structural_files(root):
        resource = read_json(path)
        raw_id = str(resource.get("id") or path.stem)
        normalized = normalize_resource_identity(resource, raw_id, STRUCTURAL_RESOURCE_ALIASES, "structural")
        resource_id = str(normalized["id"])
        if resource_id in resources:
            previous = resources[resource_id]["_path"]
            raise ValueError(f"duplicate structural resource id '{resource_id}' in '{previous}' and '{path}'")
        normalized["_path"] = str(path)
        resources[resource_id] = normalized
    build_alias_index(resources, "structural")
    return resources


def _public_resource(resource: Mapping[str, object]) -> JSONDict:
    if resource.get("resource_type") == "source_keyword_bundle":
        return {**{k: v for k, v in resource.items() if k != "_path"}, "effective_validation_status": "source_reference"}
    reviewed = apply_effective_review(resource, expected_resource_kind="structural")
    reviewed.pop("_path", None)
    return reviewed


def list_structural_resources() -> list[JSONDict]:
    rows = []
    for resource in load_structural_resources().values():
        public = _public_resource(resource)
        rows.append({
            "id": public["id"],
            "display_name": public.get("display_name", public["id"]),
            "resource_type": public.get("resource_type"),
            "unit_system": public.get("unit_system"),
            "validation_status": public.get("validation_status"),
            "effective_validation_status": public.get("effective_validation_status"),
            "requires_project_review": bool(public.get("requires_project_review", True)),
        })
    return rows


def get_structural_resource(resource_id: str) -> JSONDict:
    key = str(resource_id).strip()
    if not key:
        raise ValueError("resource_id is required")
    resources = load_structural_resources()
    _, resource = resolve_resource_id(key, resources, "structural")
    return _public_resource(resource)


def _validate_span(record: Mapping[str, object], context: str) -> None:
    try:
        start = int(record["source_line_start"])
        end = int(record["source_line_end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{context} requires integer source spans") from exc
    if start <= 0 or end < start:
        raise ValueError(f"{context} source span must be positive and ordered")


def _validate_common(resource: Mapping[str, object]) -> None:
    if resource.get("unit_system") != DEFAULT_UNIT_SYSTEM:
        raise ValueError(f"structural resource unit_system must be '{DEFAULT_UNIT_SYSTEM}'")
    if resource.get("validation_status") != "source_reference":
        raise ValueError("raw structural validation_status must be source_reference")
    if resource.get("requires_project_review") is not True:
        raise ValueError("structural requires_project_review must be true")
    provenance = resource.get("provenance")
    if not isinstance(provenance, Mapping) or provenance.get("source_sha256") != SOURCE_2K_SHA256:
        raise ValueError("structural resource source SHA-256 does not match the accepted 2.k source")


def _by_resource_id(resources: Sequence[Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for resource in resources:
        raw_id = str(resource.get("id", ""))
        normalized = normalize_resource_identity(resource, raw_id, STRUCTURAL_RESOURCE_ALIASES, "structural")
        resource_id = str(normalized["id"])
        if resource_id in result:
            raise ValueError(f"duplicate structural resource id '{resource_id}'")
        _validate_common(normalized)
        result[resource_id] = normalized
    return result


def validate_structural_catalog_closure(
    resources: Sequence[Mapping[str, object]],
    materials: Mapping[str, Mapping[str, object]],
) -> JSONDict:
    by_id = _by_resource_id(resources)
    materials_by_id: dict[str, Mapping[str, object]] = {}
    for material_key, material in materials.items():
        if not isinstance(material, Mapping):
            raise ValueError(f"material resource '{material_key}' must be an object")
        canonical_key = MATERIAL_RESOURCE_ALIASES.get(str(material_key), str(material_key))
        raw_material_id = str(material.get("id", "")).strip()
        canonical_material_id = MATERIAL_RESOURCE_ALIASES.get(raw_material_id, raw_material_id)
        if not canonical_material_id:
            raise ValueError(f"material resource '{material_key}' id is required")
        if canonical_key != canonical_material_id:
            raise ValueError(
                f"material resource '{material_key}' key/object identity mismatch: "
                f"object id is '{canonical_material_id}'"
            )
        if canonical_material_id in materials_by_id:
            raise ValueError(f"duplicate material resource id '{canonical_material_id}'")
        materials_by_id[canonical_material_id] = material
    required_ids = {
        STRUCTURAL_RESOURCE_ALIASES["2k_sections_used"],
        STRUCTURAL_RESOURCE_ALIASES["2k_curve1_kc_rate"],
        STRUCTURAL_RESOURCE_ALIASES["2k_part_role_map"],
        STRUCTURAL_RESOURCE_ALIASES["2k_sets_used"],
        STRUCTURAL_RESOURCE_ALIASES["2k_embedded_couplings"],
    }
    if set(by_id) != required_ids:
        raise ValueError("structural catalog IDs do not match the five reviewed resource families")

    section_items = by_id[STRUCTURAL_RESOURCE_ALIASES["2k_sections_used"]].get("items")
    if not isinstance(section_items, list) or len(section_items) != 6:
        raise ValueError("structural section catalog must contain six used sections")
    section_ids = set()
    for section in section_items:
        if not isinstance(section, Mapping):
            raise ValueError("structural section item must be an object")
        _validate_span(section, "section")
        secid = int(section["secid"])
        section_ids.add(secid)
        if "diameter_m" in section and (not math.isfinite(float(section["diameter_m"])) or float(section["diameter_m"]) <= 0):
            raise ValueError("beam section diameter_m must be finite and positive")
    if section_ids != {1, 2, 3, 4, 5, 6}:
        raise ValueError("structural section catalog contains audit-only or missing section IDs")

    curve = by_id[STRUCTURAL_RESOURCE_ALIASES["2k_curve1_kc_rate"]]
    _validate_span(curve, "curve")
    points = curve.get("points")
    if curve.get("curve_id") != 1 or not isinstance(points, list) or len(points) != 23:
        raise ValueError("K&C rate curve must preserve Curve 1 with 23 points")
    for point in points:
        if not isinstance(point, list) or len(point) != 2 or any(not math.isfinite(float(value)) for value in point):
            raise ValueError("K&C rate curve points must be finite pairs")

    part_items = by_id[STRUCTURAL_RESOURCE_ALIASES["2k_part_role_map"]].get("items")
    if not isinstance(part_items, list) or len(part_items) != 12:
        raise ValueError("part role map must contain 12 used Parts")
    part_ids = set()
    referenced_material_ids: set[str] = set()
    for part in part_items:
        if not isinstance(part, Mapping):
            raise ValueError("part role item must be an object")
        _validate_span(part, "part")
        pid = int(part["pid"])
        part_ids.add(pid)
        if int(part["secid"]) not in section_ids:
            raise ValueError(f"Part {pid} references an unpublished section")
        material_id = MATERIAL_RESOURCE_ALIASES.get(
            str(part.get("material_resource_id", "")),
            str(part.get("material_resource_id", "")),
        )
        if material_id not in materials_by_id:
            raise ValueError(f"Part {pid} references an unpublished material resource")
        referenced_material_ids.add(material_id)
    if len(part_ids) != 12:
        raise ValueError("part role map contains duplicate Part IDs")

    for material_id in sorted(referenced_material_ids):
        validate_material_resource(materials_by_id[material_id])

    concrete_id = MATERIAL_RESOURCE_ALIASES["2k_mid5_concrete_kc"]
    concrete = materials_by_id.get(concrete_id, {})
    dependencies = concrete.get("dependencies") if isinstance(concrete, Mapping) else None
    rate_curve = dependencies.get("rate_curve") if isinstance(dependencies, Mapping) else None
    if not isinstance(rate_curve, Mapping) or rate_curve.get("lcid") != 1 or rate_curve.get("point_count") != 23:
        raise ValueError("concrete material dependency does not close against Curve 1")

    set_items = by_id[STRUCTURAL_RESOURCE_ALIASES["2k_sets_used"]].get("items")
    if not isinstance(set_items, list) or len(set_items) != 7:
        raise ValueError("published Set catalog must contain seven definitions")
    published_set_ids = set()
    set_identities: set[tuple[str, int]] = set()
    for set_item in set_items:
        if not isinstance(set_item, Mapping):
            raise ValueError("Set item must be an object")
        _validate_span(set_item, "Set")
        set_type = str(set_item.get("set_type", ""))
        source_id = int(set_item["source_id"])
        set_identity = (set_type, source_id)
        if set_identity in set_identities:
            raise ValueError("duplicate Set identity")
        set_identities.add(set_identity)
        if set_type == "part" and source_id in {5, 7, 8}:
            raise ValueError("audit-only Part Set appears in the published catalog")
        published_set_ids.add(source_id)

    coupling_items = by_id[STRUCTURAL_RESOURCE_ALIASES["2k_embedded_couplings"]].get("items")
    if not isinstance(coupling_items, list) or len(coupling_items) != 5:
        raise ValueError("coupling catalog must contain five source relationships")
    coupling_indexes: set[int] = set()
    coupling_signatures: set[tuple[str, int, str, int, int, int]] = set()
    for coupling in coupling_items:
        if not isinstance(coupling, Mapping):
            raise ValueError("coupling item must be an object")
        _validate_span(coupling, "coupling")
        coupling_index = int(coupling["coupling_index"])
        slave_kind = str(coupling.get("slave_kind", ""))
        ssid = int(coupling["ssid"])
        master_kind = str(coupling.get("master_kind", ""))
        msid = int(coupling["msid"])
        sstyp = int(coupling["sstyp"])
        mstyp = int(coupling["mstyp"])
        for prefix, kind, endpoint in (("slave", slave_kind, ssid), ("master", master_kind, msid)):
            if kind == "part" and endpoint not in part_ids:
                raise ValueError(f"coupling {prefix} Part {endpoint} is not published")
            if kind == "set" and endpoint not in published_set_ids:
                raise ValueError(f"coupling {prefix} Set {endpoint} is not published")
            if kind not in {"part", "set"}:
                raise ValueError(f"coupling {prefix}_kind is invalid")
        if coupling_index in coupling_indexes:
            raise ValueError("duplicate coupling_index")
        coupling_indexes.add(coupling_index)
        coupling_signature = (slave_kind, ssid, master_kind, msid, sstyp, mstyp)
        if coupling_signature in coupling_signatures:
            raise ValueError("duplicate coupling relation")
        coupling_signatures.add(coupling_signature)

    return {
        "valid": True,
        "resource_count": len(by_id),
        "section_count": len(section_items),
        "curve_point_count": len(points),
        "part_count": len(part_items),
        "set_count": len(set_items),
        "coupling_count": len(coupling_items),
    }


def validate_structural_resource(resource_id: str) -> JSONDict:
    resource = get_structural_resource(resource_id)
    if resource.get("resource_type") == "source_keyword_bundle":
        from .source_rebuild_resources import validate_resource
        return validate_resource(resource)
    _validate_common(resource)
    return {
        "valid": True,
        "resource_id": resource_id,
        "resource_type": resource.get("resource_type"),
        "effective_validation_status": resource.get("effective_validation_status", "source_reference"),
        "requires_project_review": bool(resource.get("requires_project_review", True)),
    }
