"""Explicit-first normalization of native and legacy Phase 18 model semantics."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .contracts import FileReference, Issue
from .errors import ContractError, UnsupportedSchemaError
from .material_capabilities import MaterialCapability, capability_for_material


_NATIVE_SCHEMA = "blast_damage.model_semantics@1"
_LEGACY_SCHEMA_RE = re.compile(r"^phase18\.solver_blast\.deck_manifest@([1-4])$")
_NON_BUILDING_ROLES = {
    "ale_air_tnt_domain",
    "ale_air_domain",
    "ale_active_air_domain",
    "ale_coupling_buffer",
    "visible_mm_ale_air_domain",
    "tnt_high_explosive",
}


@dataclass(frozen=True)
class SemanticInference:
    field: str
    value: object
    reason: str


@dataclass(frozen=True)
class ComponentSemantics:
    component_id: str
    role: str
    part_ids: tuple[int, ...]
    material_ids: tuple[int, ...]
    importance_class: str
    primary_load_path: bool
    zone_id: str | None = None


@dataclass(frozen=True)
class GroundSemantics:
    part_ids: tuple[int, ...]
    material_ids: tuple[int, ...]
    surface_axis: str
    surface_direction: str


@dataclass(frozen=True)
class ModelSemantics:
    schema_version: str
    source_schema_version: str
    unit_system: str
    vertical_axis: str
    horizontal_axes: tuple[str, str]
    blast_center_m: tuple[float, float, float]
    components: tuple[ComponentSemantics, ...]
    zone_ids: tuple[str, ...]
    ground: GroundSemantics | None
    materials: Mapping[int, MaterialCapability]
    engineering_validated: bool
    requires_project_review: bool
    legacy: bool
    formal_eligible: bool
    inferences: tuple[SemanticInference, ...] = ()
    warnings: tuple[Issue, ...] = ()
    building_blockers: tuple[Issue, ...] = ()
    ground_blockers: tuple[Issue, ...] = ()
    excluded_part_ids: tuple[int, ...] = ()
    classification_source: str = "explicit_manifest@1"
    importance_explicit: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "materials", MappingProxyType(dict(self.materials)))


@dataclass(frozen=True)
class _LegacyPartRule:
    component_id: str
    component_role: str
    importance_class: str
    primary_load_path: bool
    material_role: str


def _rule(component_id: str, role: str, material: str, primary: bool = True) -> _LegacyPartRule:
    importance = "primary" if primary else "secondary"
    if role in {"partition", "barrier", "facade", "glazing"}:
        importance = "nonstructural"
    return _LegacyPartRule(component_id, role, importance, primary, material)



_LEGACY_PART_RULES = {
    # Commercial building
    "commercial_rc_column": _rule("commercial_columns", "column", "concrete"),
    "commercial_column_longitudinal_rebar": _rule("commercial_columns", "column", "reinforcing_steel"),
    "commercial_column_stirrup": _rule("commercial_columns", "column", "reinforcing_steel"),
    "commercial_wall_horizontal_rebar": _rule("commercial_walls", "wall", "reinforcing_steel"),
    "commercial_wall_vertical_rebar": _rule("commercial_walls", "wall", "reinforcing_steel"),
    "hybrid_foundation": _rule("commercial_foundation", "foundation", "concrete"),
    "foundation_rebar": _rule("foundation", "foundation", "reinforcing_steel"),
    "hybrid_slab": _rule("commercial_slab", "slab", "concrete"),
    "slab_rebar": _rule("slab", "slab", "reinforcing_steel"),
    "steel_beam": _rule("commercial_beams", "beam", "structural_steel"),
    "steel_roof_deck": _rule("commercial_roof", "roof", "structural_steel", False),
    "nonstructural_partition": _rule("partitions", "partition", "nonstructural", False),
    "nonstructural_balcony_barrier": _rule("balcony_barriers", "barrier", "nonstructural", False),
    "opaque_facade": _rule("facade", "facade", "facade_masonry", False),
    # Residential building
    "rc_column": _rule("residential_columns", "column", "rc_column_material"),
    "column_longitudinal": _rule("residential_columns", "column", "reinforcing_steel"),
    "column_stirrup": _rule("residential_columns", "column", "reinforcing_steel"),
    "rc_beam_x": _rule("residential_beams", "beam", "rc_beam_x_material"),
    "rc_beam_y": _rule("residential_beams", "beam", "rc_beam_y_material"),
    "beam_longitudinal": _rule("residential_beams", "beam", "reinforcing_steel"),
    "beam_stirrup": _rule("residential_beams", "beam", "reinforcing_steel"),
    "rc_shear_wall": _rule("residential_walls", "wall", "rc_shear_wall_material"),
    "wall_rebar": _rule("wall", "wall", "reinforcing_steel"),
    "rc_foundation": _rule("foundation", "foundation", "rc_foundation_material"),
    "rc_slab": _rule("slab", "slab", "rc_slab_material"),
    # Subway entrance and equipment
    "fixed_stair_A": _rule("fixed_stair", "stair", "fixed_stair_A_material"),
    "fixed_stair_rebar": _rule("fixed_stair", "stair", "reinforcing_steel"),
    "fixed_stair_distribution_rebar": _rule("fixed_stair", "stair", "reinforcing_steel"),
    "fixed_stair_local_rebar": _rule("fixed_stair", "stair", "reinforcing_steel"),
    "lower_landing_8": _rule("lower_landing", "landing", "lower_landing_8_material"),
    "upper_landing": _rule("upper_landing", "landing", "upper_landing_material"),
    "landing_rebar": _rule("landings", "landing", "reinforcing_steel"),
    "pavilion_frame": _rule("pavilion_frame", "frame", "structural_steel"),
    "pavilion_glazing": _rule("pavilion_glazing", "glazing", "glazing", False),
    "pavilion_opaque_solid_roof": _rule("pavilion_roof", "roof", "metal_roof", False),
    "pavilion_rc_plinth": _rule("pavilion_plinth", "foundation", "pavilion_rc_plinth_material"),
    "plinth_rebar": _rule("pavilion_plinth", "foundation", "reinforcing_steel"),
    "rc_box_floor": _rule("subway_box_floor", "floor", "rc_box_floor_material"),
    "rc_box_roof": _rule("subway_box_roof", "roof", "rc_box_roof_material"),
    "rc_box_wall": _rule("subway_box_wall", "wall", "rc_box_wall_material"),
    "escalator_1_balustrade": _rule("escalator_1", "equipment", "escalator_balustrade", False),
    "escalator_1_handrails": _rule("escalator_1", "equipment", "escalator_handrail", False),
    "escalator_1_step_band": _rule("escalator_1", "equipment", "escalator_equipment", False),
    "escalator_1_truss_guides": _rule("escalator_1", "equipment", "escalator_equipment", False),
    "escalator_2_balustrade": _rule("escalator_2", "equipment", "escalator_balustrade", False),
    "escalator_2_handrails": _rule("escalator_2", "equipment", "escalator_handrail", False),
    "escalator_2_step_band": _rule("escalator_2", "equipment", "escalator_equipment", False),
    "escalator_2_truss_guides": _rule("escalator_2", "equipment", "escalator_equipment", False),
}


def _read(reference: FileReference) -> Mapping[str, object]:
    path = reference.path.resolve(strict=True)
    payload = path.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != reference.sha256:
        raise ContractError("semantic manifest hash mismatch")
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid semantic manifest JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError("semantic manifest root must be an object")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a non-empty string")
    return value


def _closed_fields(value: Mapping[str, object], allowed: set[str], name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ContractError(f"{name} contains unknown field: {unknown[0]}")


def _positive_ids(value: object, name: str) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise ContractError(f"{name} must be a non-empty array")
    result = tuple(value)
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in result):
        raise ContractError(f"{name} must contain positive integers")
    if len(set(result)) != len(result):
        raise ContractError(f"{name} contains duplicate IDs")
    return result


def _vector3(value: object, name: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ContractError(f"{name} must contain three numbers")
    if any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        or not math.isfinite(float(item))
        for item in value
    ):
        raise ContractError(f"{name} must contain three finite numbers")
    return tuple(float(item) for item in value)  # type: ignore[return-value]


def _load_native(raw: Mapping[str, object], schema: str) -> ModelSemantics:
    _closed_fields(
        raw,
        {
            "schema_version", "unit_system", "axes", "blast_center_m",
            "engineering_validated", "requires_project_review", "building",
            "ground", "materials", "classification",
        },
        "semantic manifest",
    )
    unit_system = _text(raw.get("unit_system"), "unit_system")
    axes = raw.get("axes")
    if not isinstance(axes, dict):
        raise ContractError("axes must be an object")
    _closed_fields(axes, {"vertical", "horizontal"}, "axes")
    vertical = _text(axes.get("vertical"), "axes.vertical")
    horizontal_raw = axes.get("horizontal")
    if not isinstance(horizontal_raw, list) or len(horizontal_raw) != 2:
        raise ContractError("axes.horizontal must contain two axes")
    horizontal = tuple(_text(item, "axes.horizontal") for item in horizontal_raw)
    if vertical not in {"x", "y", "z"} or set((vertical, *horizontal)) != {"x", "y", "z"}:
        raise ContractError("axes must be a permutation of x, y, and z")
    building = raw.get("building")
    if not isinstance(building, dict):
        raise ContractError("building must be an object")
    _closed_fields(building, {"zones", "components"}, "building")
    zones_raw = building.get("zones", [])
    if not isinstance(zones_raw, list):
        raise ContractError("building.zones must be an array")
    for zone in zones_raw:
        if not isinstance(zone, dict):
            raise ContractError("building zone must be an object")
        _closed_fields(zone, {"id"}, "building zone")
    zone_ids = tuple(_text(zone.get("id") if isinstance(zone, dict) else None, "zone.id") for zone in zones_raw)
    if len(set(zone_ids)) != len(zone_ids):
        raise ContractError("building zones contain duplicate IDs")
    components_raw = building.get("components")
    if not isinstance(components_raw, list) or not components_raw:
        raise ContractError("building.components must be a non-empty array")
    components: list[ComponentSemantics] = []
    seen_parts: set[int] = set()
    for item in components_raw:
        if not isinstance(item, dict):
            raise ContractError("building component must be an object")
        _closed_fields(
            item,
            {
                "id", "role", "part_ids", "material_ids", "importance_class",
                "primary_load_path", "zone_id",
            },
            "building component",
        )
        zone_id = item.get("zone_id")
        if zone_id is not None:
            zone_id = _text(zone_id, "component.zone_id")
            if zone_id not in zone_ids:
                raise ContractError(f"component references unknown zone: {zone_id}")
        part_ids = _positive_ids(item.get("part_ids"), "component.part_ids")
        if seen_parts.intersection(part_ids):
            raise ContractError("a Part ID is assigned to multiple components")
        seen_parts.update(part_ids)
        primary = item.get("primary_load_path")
        if not isinstance(primary, bool):
            raise ContractError("component.primary_load_path must be boolean")
        importance = _text(item.get("importance_class"), "component.importance_class")
        if importance not in {"primary", "secondary", "nonstructural"}:
            raise ContractError("component.importance_class is unsupported")
        components.append(
            ComponentSemantics(
                _text(item.get("id"), "component.id"),
                _text(item.get("role"), "component.role"),
                part_ids,
                _positive_ids(item.get("material_ids"), "component.material_ids"),
                importance,
                primary,
                zone_id,
            )
        )
    if len({component.component_id for component in components}) != len(components):
        raise ContractError("building components contain duplicate IDs")
    ground_raw = raw.get("ground")
    if not isinstance(ground_raw, dict) or not isinstance(ground_raw.get("surface"), dict):
        raise ContractError("ground surface identity is required")
    _closed_fields(ground_raw, {"part_ids", "material_ids", "surface"}, "ground")
    surface = ground_raw["surface"]
    _closed_fields(surface, {"axis", "direction"}, "ground.surface")
    surface_axis = _text(surface.get("axis"), "ground.surface.axis")
    if surface_axis != vertical:
        raise ContractError("ground surface axis must match the declared vertical axis")
    surface_direction = _text(surface.get("direction"), "ground.surface.direction")
    if surface_direction not in {"min", "max"}:
        raise ContractError("ground.surface.direction must be min or max")
    ground = GroundSemantics(
        _positive_ids(ground_raw.get("part_ids"), "ground.part_ids"),
        _positive_ids(ground_raw.get("material_ids"), "ground.material_ids"),
        surface_axis,
        surface_direction,
    )
    if seen_parts.intersection(ground.part_ids):
        raise ContractError("a Part ID cannot be both building and ground")
    materials_raw = raw.get("materials")
    if not isinstance(materials_raw, list) or not materials_raw:
        raise ContractError("materials must be a non-empty array")
    materials = {}
    for item in materials_raw:
        if not isinstance(item, dict):
            raise ContractError("material record must be an object")
        _closed_fields(
            item,
            {
                "material_id", "model", "engineering_validated", "nout",
                "yield_stress_pa", "calibration_id",
            },
            "material record",
        )
        capability = capability_for_material(item)
        if capability.material_id in materials:
            raise ContractError(f"duplicate material ID: {capability.material_id}")
        materials[capability.material_id] = capability
    used_materials = {
        material_id for component in components for material_id in component.material_ids
    } | set(ground.material_ids)
    missing_materials = sorted(used_materials - set(materials))
    if missing_materials:
        raise ContractError(f"semantic object references unknown material ID: {missing_materials[0]}")
    classification_source = "explicit_manifest@1"
    importance_explicit = True
    inferences: tuple[SemanticInference, ...] = ()
    classification = raw.get("classification")
    if classification is not None:
        if not isinstance(classification, dict):
            raise ContractError("classification must be an object")
        _closed_fields(
            classification,
            {"source", "part_role_bindings", "generator_fingerprints"},
            "classification",
        )
        classification_source = _text(
            classification.get("source"), "classification.source"
        )
        if classification_source not in {
            "explicit_source_asset@1",
            "inferred_generator_mapping@1",
        }:
            raise ContractError("classification.source is unsupported")
        bindings = classification.get("part_role_bindings")
        if not isinstance(bindings, list) or not bindings:
            raise ContractError("classification.part_role_bindings must be a non-empty array")
        component_by_id = {row.component_id: row for row in components}
        seen_binding_parts: set[int] = set()
        seen_binding_roles: set[str] = set()
        for binding in bindings:
            if not isinstance(binding, dict):
                raise ContractError("classification binding must be an object")
            _closed_fields(
                binding,
                {"part_role", "part_id", "component_id", "material_id"},
                "classification binding",
            )
            part_role = _text(binding.get("part_role"), "classification binding.part_role")
            component_id = _text(binding.get("component_id"), "classification binding.component_id")
            part_id = binding.get("part_id")
            material_id = binding.get("material_id")
            component = component_by_id.get(component_id)
            if (
                isinstance(part_id, bool)
                or not isinstance(part_id, int)
                or isinstance(material_id, bool)
                or not isinstance(material_id, int)
                or component is None
                or part_id not in component.part_ids
                or material_id not in component.material_ids
                or part_id in seen_binding_parts
                or part_role in seen_binding_roles
            ):
                raise ContractError("classification binding disagrees with building components")
            seen_binding_parts.add(part_id)
            seen_binding_roles.add(part_role)
        if seen_binding_parts != seen_parts:
            raise ContractError("classification bindings do not cover every building Part")
        fingerprints = classification.get("generator_fingerprints")
        if not isinstance(fingerprints, dict) or not fingerprints:
            raise ContractError("classification.generator_fingerprints must be a non-empty object")
        if any(
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            for name, digest in fingerprints.items()
        ):
            raise ContractError("classification generator fingerprint is invalid")
        if classification_source == "inferred_generator_mapping@1":
            importance_explicit = False
            inferences = (
                SemanticInference("building.components", dict(classification), classification_source),
            )
    engineering_validated = raw.get("engineering_validated")
    requires_review = raw.get("requires_project_review")
    if not isinstance(engineering_validated, bool) or not isinstance(requires_review, bool):
        raise ContractError("engineering validation flags must be boolean")
    formal = engineering_validated and not requires_review and all(item.engineering_validated for item in materials.values())
    return ModelSemantics(
        _NATIVE_SCHEMA,
        schema,
        unit_system,
        vertical,
        horizontal,  # type: ignore[arg-type]
        _vector3(raw.get("blast_center_m"), "blast_center_m"),
        tuple(components),
        zone_ids,
        ground,
        materials,
        engineering_validated,
        requires_review,
        False,
        formal,
        inferences=inferences,
        classification_source=classification_source,
        importance_explicit=importance_explicit,
    )


def _load_legacy(raw: Mapping[str, object], schema: str) -> ModelSemantics:
    unit_system = _text(raw.get("unit_system"), "unit_system")
    charge = raw.get("charge")
    if not isinstance(charge, dict):
        raise ContractError("legacy charge record is required")
    part_rows = raw.get("part_ids")
    if not isinstance(part_rows, list):
        raise ContractError("legacy part_ids must be an array")
    parts: list[tuple[str, int]] = []
    for row in part_rows:
        if not isinstance(row, list) or len(row) != 2:
            raise ContractError("legacy part_ids entries must be [role, id]")
        role, part_id = row
        role = _text(role, "part role")
        if isinstance(part_id, bool) or not isinstance(part_id, int) or part_id <= 0:
            raise ContractError("legacy Part ID must be a positive integer")
        parts.append((role, part_id))
    if len({part_id for _, part_id in parts}) != len(parts):
        raise ContractError("legacy part_ids contain duplicate IDs")
    materials_raw = raw.get("materials")
    material_rows = materials_raw.get("role_to_material_id", []) if isinstance(materials_raw, dict) else []
    role_materials = {
        str(row[0]): int(row[1])
        for row in material_rows
        if isinstance(row, list) and len(row) == 2 and isinstance(row[1], int) and not isinstance(row[1], bool)
    }
    grouped: dict[str, dict[str, object]] = {}
    excluded: list[int] = []
    warnings: list[Issue] = []
    building_blockers: list[Issue] = []
    primary_unknown = set(raw.get("primary_load_path_part_ids", [])) if isinstance(raw.get("primary_load_path_part_ids", []), list) else set()
    ground_ids = [part_id for role, part_id in parts if role == "diagnostic_soil_ground"]
    roles_present = {role for role, _ in parts}
    for role, part_id in parts:
        if role in _NON_BUILDING_ROLES or role == "diagnostic_soil_ground":
            continue
        rule = _LEGACY_PART_RULES.get(role)
        if rule is None:
            excluded.append(part_id)
            if part_id in primary_unknown:
                building_blockers.append(
                    Issue("semantics.unclassified_primary", "Unclassified Part is connected to the primary load path", {"part_id": part_id, "role": role})
                )
            else:
                warnings.append(
                    Issue("semantics.unclassified_noncritical", "Unclassified noncritical Part is visible but excluded", {"part_id": part_id, "role": role})
                )
            continue
        component_id = rule.component_id
        component_role = rule.component_role
        if role == "foundation_rebar" and "hybrid_foundation" in roles_present:
            component_id = "commercial_foundation"
        elif role == "slab_rebar":
            if "hybrid_slab" in roles_present:
                component_id = "commercial_slab"
            elif "rc_box_floor" in roles_present or "rc_box_roof" in roles_present:
                component_id = "subway_box_slabs"
                component_role = "slab"
        elif role == "wall_rebar":
            component_id = (
                "subway_box_wall" if "rc_box_wall" in roles_present else "residential_walls"
            )
        if role in {"rc_box_floor", "rc_box_roof"}:
            component_id = "subway_box_slabs"
            component_role = "slab"
        if role in {"lower_landing_8", "upper_landing", "landing_rebar"}:
            component_id = "subway_landings"
        item = grouped.setdefault(
            component_id,
            {
                "role": component_role,
                "importance": rule.importance_class,
                "primary": rule.primary_load_path,
                "parts": [],
                "materials": [],
            },
        )
        item["parts"].append(part_id)  # type: ignore[union-attr]
        material_id = role_materials.get(rule.material_role)
        if material_id is not None:
            item["materials"].append(material_id)  # type: ignore[union-attr]
    components = tuple(
        ComponentSemantics(
            component_id,
            str(item["role"]),
            tuple(sorted(set(item["parts"]))),  # type: ignore[arg-type]
            tuple(sorted(set(item["materials"]))),  # type: ignore[arg-type]
            str(item["importance"]),
            bool(item["primary"]),
        )
        for component_id, item in sorted(grouped.items())
    )
    ground_blockers: list[Issue] = []
    ground: GroundSemantics | None
    if len(ground_ids) != 1:
        ground = None
        ground_blockers.append(
            Issue("semantics.ground_identity", "Exactly one diagnostic_soil_ground Part is required", {"count": len(ground_ids)})
        )
    else:
        ground = GroundSemantics((ground_ids[0],), (7,), "z", "max")
    used_material_ids = {material_id for component in components for material_id in component.material_ids}
    if ground is not None:
        used_material_ids.update(ground.material_ids)
    capabilities: dict[int, MaterialCapability] = {}
    for material_id in sorted(used_material_ids):
        if material_id == 3:
            record = {"material_id": 3, "model": "MAT_072R3", "nout": 2, "engineering_validated": False}
        elif material_id == 4:
            record = {"material_id": 4, "model": "steel_plasticity", "engineering_validated": False}
        else:
            record = {"material_id": material_id, "model": "elastic", "engineering_validated": False}
        capabilities[material_id] = capability_for_material(record)
    inferences = (
        SemanticInference("axes", {"vertical": "z", "horizontal": ["x", "y"]}, "legacy Phase18 SI convention"),
        SemanticInference("components", "exact legacy role table", "native component semantics absent"),
        SemanticInference("ground.material_ids", [7] if ground else [], "Phase18 diagnostic soil material constant"),
    )
    return ModelSemantics(
        _NATIVE_SCHEMA,
        schema,
        unit_system,
        "z",
        ("x", "y"),
        _vector3(charge.get("position_m"), "charge.position_m"),
        components,
        (),
        ground,
        capabilities,
        bool(raw.get("engineering_validated", False)),
        bool(raw.get("requires_project_review", True)),
        True,
        False,
        inferences,
        tuple(warnings),
        tuple(building_blockers),
        tuple(ground_blockers),
        tuple(sorted(excluded)),
        classification_source="legacy_phase18_role_table@1",
        importance_explicit=False,
    )


def load_semantics(reference: FileReference) -> ModelSemantics:
    raw = _read(reference)
    schema = _text(raw.get("schema_version"), "schema_version")
    if schema == _NATIVE_SCHEMA:
        return _load_native(raw, schema)
    if _LEGACY_SCHEMA_RE.fullmatch(schema):
        return _load_legacy(raw, schema)
    raise UnsupportedSchemaError(f"unsupported semantic manifest schema: {schema}")
