"""Native, provisional damage-assessment semantics for solver-complete decks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from lsprepost_mcp.config import JSONDict
from lsprepost_mcp.refined_building.solver_blast.materials import (
    CONCRETE_MATERIAL_ID,
    GLASS_MATERIAL_ID,
    NONSTRUCTURAL_MATERIAL_ID,
    SOIL_MATERIAL_ID,
    STEEL_MATERIAL_ID,
    ELASTIC_RC_MATERIAL_ID,
    material_id_for_role,
)


_SEMANTIC_SCHEMA = "blast_damage.model_semantics@1"
_CLASSIFICATION_SOURCE = "inferred_generator_mapping@1"
_NON_BUILDING_ROLES = frozenset(
    {
        "diagnostic_soil_ground",
        "ale_air_tnt_domain",
        "ale_air_domain",
        "ale_active_air_domain",
        "visible_mm_ale_air_domain",
        "ale_coupling_buffer",
        "tnt_high_explosive",
    }
)


@dataclass(frozen=True, slots=True)
class _ComponentRule:
    component_id: str
    role: str
    importance_class: str
    primary_load_path: bool


def _rule(
    component_id: str, role: str, primary: bool = True
) -> _ComponentRule:
    importance = "primary" if primary else "secondary"
    if role in {"partition", "barrier", "facade", "glazing"}:
        importance = "nonstructural"
    return _ComponentRule(component_id, role, importance, primary)


_COMPONENT_RULES = {
    "commercial_rc_column": _rule("commercial_columns", "column"),
    "commercial_column_longitudinal_rebar": _rule("commercial_columns", "column"),
    "commercial_column_stirrup": _rule("commercial_columns", "column"),
    "commercial_wall_horizontal_rebar": _rule("commercial_walls", "wall"),
    "commercial_wall_vertical_rebar": _rule("commercial_walls", "wall"),
    "hybrid_foundation": _rule("commercial_foundation", "foundation"),
    "foundation_rebar": _rule("foundation", "foundation"),
    "hybrid_slab": _rule("commercial_slab", "slab"),
    "slab_rebar": _rule("slab", "slab"),
    "steel_beam": _rule("commercial_beams", "beam"),
    "steel_roof_deck": _rule("commercial_roof", "roof", False),
    "nonstructural_partition": _rule("partitions", "partition", False),
    "nonstructural_balcony_barrier": _rule("balcony_barriers", "barrier", False),
    "opaque_facade": _rule("facade", "facade", False),
    "rc_column": _rule("residential_columns", "column"),
    "column_longitudinal": _rule("residential_columns", "column"),
    "column_stirrup": _rule("residential_columns", "column"),
    "rc_beam_x": _rule("residential_beams", "beam"),
    "rc_beam_y": _rule("residential_beams", "beam"),
    "beam_longitudinal": _rule("residential_beams", "beam"),
    "beam_stirrup": _rule("residential_beams", "beam"),
    "rc_shear_wall": _rule("residential_walls", "wall"),
    "wall_rebar": _rule("wall", "wall"),
    "rc_foundation": _rule("foundation", "foundation"),
    "rc_slab": _rule("slab", "slab"),
    "fixed_stair_A": _rule("fixed_stair", "stair"),
    "fixed_stair_rebar": _rule("fixed_stair", "stair"),
    "fixed_stair_distribution_rebar": _rule("fixed_stair", "stair"),
    "fixed_stair_local_rebar": _rule("fixed_stair", "stair"),
    "lower_landing_8": _rule("lower_landing", "landing"),
    "upper_landing": _rule("upper_landing", "landing"),
    "landing_rebar": _rule("landings", "landing"),
    "pavilion_frame": _rule("pavilion_frame", "frame"),
    "pavilion_glazing": _rule("pavilion_glazing", "glazing", False),
    "pavilion_opaque_solid_roof": _rule("pavilion_roof", "roof", False),
    "pavilion_rc_plinth": _rule("pavilion_plinth", "foundation"),
    "plinth_rebar": _rule("pavilion_plinth", "foundation"),
    "rc_box_floor": _rule("subway_box_floor", "floor"),
    "rc_box_roof": _rule("subway_box_roof", "roof"),
    "rc_box_wall": _rule("subway_box_wall", "wall"),
    "escalator_1_balustrade": _rule("escalator_1", "equipment", False),
    "escalator_1_handrails": _rule("escalator_1", "equipment", False),
    "escalator_1_step_band": _rule("escalator_1", "equipment", False),
    "escalator_1_truss_guides": _rule("escalator_1", "equipment", False),
    "escalator_2_balustrade": _rule("escalator_2", "equipment", False),
    "escalator_2_handrails": _rule("escalator_2", "equipment", False),
    "escalator_2_step_band": _rule("escalator_2", "equipment", False),
    "escalator_2_truss_guides": _rule("escalator_2", "equipment", False),
}


def build_assessment_semantics(detailed: object, compilation: object) -> JSONDict:
    """Build one closed native manifest from the exact compiled solver identities."""

    artifacts = tuple(getattr(detailed, "artifacts", ()))
    if len(artifacts) != 1:
        raise ValueError("assessment semantics require exactly one building artifact")
    building = getattr(compilation, "building", None)
    evidence = getattr(compilation, "evidence", None)
    validation = getattr(compilation, "validation", None)
    if building is None or evidence is None or validation is None:
        raise ValueError("assessment semantics require a complete solver compilation")

    part_rows = tuple(getattr(evidence, "part_ids", ()))
    part_by_role = {str(role): part_id for role, part_id in part_rows}
    if len(part_by_role) != len(part_rows) or any(
        isinstance(part_id, bool) or not isinstance(part_id, int) or part_id <= 0
        for part_id in part_by_role.values()
    ):
        raise ValueError("solver Part identities are invalid")
    ground_id = part_by_role.get("diagnostic_soil_ground")
    if not isinstance(ground_id, int):
        raise ValueError("assessment semantics require diagnostic soil ground identity")

    member_by_role = {
        str(member.role): member for member in tuple(getattr(building, "members", ()))
    }
    building_roles = set(part_by_role) - _NON_BUILDING_ROLES
    if building_roles != set(member_by_role):
        raise ValueError("assessment classification does not match physical building roles")
    unknown = sorted(building_roles - set(_COMPONENT_RULES))
    if unknown:
        raise ValueError(f"assessment classification is unavailable for Part role: {unknown[0]}")

    effective_rules = dict(_COMPONENT_RULES)
    if "hybrid_foundation" in building_roles and "foundation_rebar" in building_roles:
        effective_rules["foundation_rebar"] = _rule("commercial_foundation", "foundation")
    if "hybrid_slab" in building_roles and "slab_rebar" in building_roles:
        effective_rules["slab_rebar"] = _rule("commercial_slab", "slab")

    groups: dict[str, dict[str, object]] = {}
    bindings: list[JSONDict] = []
    for part_role in sorted(building_roles):
        rule = effective_rules[part_role]
        member = member_by_role[part_role]
        material_id = material_id_for_role(str(member.material_role))
        group = groups.setdefault(
            rule.component_id,
            {
                "id": rule.component_id,
                "role": rule.role,
                "part_ids": [],
                "material_ids": [],
                "importance_class": rule.importance_class,
                "primary_load_path": rule.primary_load_path,
            },
        )
        if (
            group["role"] != rule.role
            or group["importance_class"] != rule.importance_class
            or group["primary_load_path"] != rule.primary_load_path
        ):
            raise ValueError("assessment component classification table is inconsistent")
        group["part_ids"].append(part_by_role[part_role])  # type: ignore[union-attr]
        group["material_ids"].append(material_id)  # type: ignore[union-attr]
        bindings.append(
            {
                "part_role": part_role,
                "part_id": part_by_role[part_role],
                "component_id": rule.component_id,
                "material_id": material_id,
            }
        )

    components: list[JSONDict] = []
    for component_id in sorted(groups):
        row = groups[component_id]
        row["part_ids"] = sorted(set(row["part_ids"]))  # type: ignore[arg-type]
        row["material_ids"] = sorted(set(row["material_ids"]))  # type: ignore[arg-type]
        components.append(row)
    used_materials = {
        int(material_id)
        for component in components
        for material_id in component["material_ids"]  # type: ignore[union-attr]
    }
    used_materials.add(SOIL_MATERIAL_ID)

    position = list(getattr(validation, "charge_position_m", ()))
    if len(position) != 3:
        raise ValueError("assessment semantics require a three-axis blast center")
    fingerprints = {
        "building_artifact": str(getattr(artifacts[0], "fingerprint", "")),
        "detailed_building_package": str(getattr(detailed, "package_fingerprint", "")),
        "physical_building": str(getattr(building, "fingerprint", "")),
        "solver_building_mesh": str(getattr(evidence, "building_mesh_fingerprint", "")),
        "solver_scene": str(getattr(evidence, "scene_fingerprint", "")),
    }
    if any(len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value) for value in fingerprints.values()):
        raise ValueError("assessment generator fingerprint is invalid")

    return {
        "schema_version": _SEMANTIC_SCHEMA,
        "unit_system": "SI_m_s_kg_N_Pa",
        "axes": {"vertical": "z", "horizontal": ["x", "y"]},
        "blast_center_m": [float(value) for value in position],
        "engineering_validated": False,
        "requires_project_review": True,
        "building": {"zones": [], "components": components},
        "ground": {
            "part_ids": [ground_id],
            "material_ids": [SOIL_MATERIAL_ID],
            "surface": {"axis": "z", "direction": "max"},
        },
        "materials": [_material_capability(material_id) for material_id in sorted(used_materials)],
        "classification": {
            "source": _CLASSIFICATION_SOURCE,
            "part_role_bindings": bindings,
            "generator_fingerprints": fingerprints,
        },
    }


def _material_capability(material_id: int) -> JSONDict:
    if material_id == CONCRETE_MATERIAL_ID:
        return {
            "material_id": material_id,
            "model": "MAT_072R3",
            "nout": 2,
            "engineering_validated": False,
        }
    if material_id == STEEL_MATERIAL_ID:
        return {
            "material_id": material_id,
            "model": "steel_plasticity",
            "engineering_validated": False,
        }
    if material_id in {
        GLASS_MATERIAL_ID,
        NONSTRUCTURAL_MATERIAL_ID,
        SOIL_MATERIAL_ID,
        ELASTIC_RC_MATERIAL_ID,
    }:
        return {
            "material_id": material_id,
            "model": "elastic",
            "engineering_validated": False,
        }
    raise ValueError(f"assessment material capability is unavailable for ID {material_id}")


__all__ = ["build_assessment_semantics"]
