"""Steel-concrete hybrid backend for refined buildings."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping

from ..artifacts import BuildingArtifact, MeshFragment, PartBinding
from ..connections import make_connection
from ..contracts import normalize_building_definition
from ..meshing import merge_fragments, mesh_axis_aligned_union
from ..reinforcement import generate_reinforcement
from ..spatial import AxisAlignedBox, SpatialTopology
from ..systems import StructuralSystemDescriptor, get_structural_system, normalize_structural_system_profile
from .steel import compile_steel_frame


def compile_steel_concrete_hybrid(
    definition: Mapping[str, object],
    topology: SpatialTopology,
    descriptor: StructuralSystemDescriptor,
) -> BuildingArtifact:
    if descriptor.backend_key != "hybrid":
        raise ValueError(f"descriptor {descriptor.system_id!r} is not a hybrid backend")
    normalized = normalize_building_definition(definition)
    profile_raw = normalized["structural_system"]
    assert isinstance(profile_raw, dict)
    profile = normalize_structural_system_profile(profile_raw)
    if profile["type"] != descriptor.system_id:
        raise ValueError("definition structural system does not match descriptor")
    normalized["structural_system"] = profile
    parameters = profile["parameters"]
    assert isinstance(parameters, dict)
    mesh_size = _positive(parameters.get("mesh_size_m", 0.5), "mesh_size_m")
    slab_thickness = _positive(parameters.get("slab_thickness_m", 0.2), "slab_thickness_m")
    foundation_thickness = _positive(
        parameters.get("foundation_thickness_m", 0.2), "foundation_thickness_m"
    )

    envelope = topology.envelope
    if foundation_thickness > envelope.max_z - envelope.min_z:
        raise ValueError("foundation_thickness_m must not exceed envelope height")
    levels = normalized["levels"]
    assert isinstance(levels, list)
    if any(
        slab_thickness > float(level["height_m"])
        for level in levels
        if isinstance(level, dict)
    ):
        raise ValueError("slab_thickness_m must not exceed level height")

    steel_input = copy.deepcopy(normalized)
    steel_parameters = {}
    if "member_target_length_m" in parameters:
        steel_parameters["member_target_length_m"] = parameters["member_target_length_m"]
    if "opening_frame_profile" in parameters:
        steel_parameters["opening_frame_profile"] = copy.deepcopy(
            parameters["opening_frame_profile"]
        )
    steel_input["structural_system"] = {
        "type": "steel_frame",
        "parameters": steel_parameters,
    }
    steel = compile_steel_frame(steel_input, topology, get_structural_system("steel_frame"))
    concrete_members: list[tuple[str, AxisAlignedBox]] = []
    concrete_members.append(
        (
            "hybrid_foundation",
            AxisAlignedBox(
                envelope.min_x,
                envelope.min_y,
                envelope.min_z,
                envelope.max_x,
                envelope.max_y,
                envelope.min_z + foundation_thickness,
            ),
        )
    )
    for level in levels:
        assert isinstance(level, dict)
        top = float(level["elevation_m"]) + float(level["height_m"])
        concrete_members.append(
            (
                "hybrid_slab",
                AxisAlignedBox(
                    envelope.min_x,
                    envelope.min_y,
                    top - slab_thickness,
                    envelope.max_x,
                    envelope.max_y,
                    top,
                ),
            )
        )
    exclusions = tuple(excluded for _, excluded in topology.opening_regions)
    raw_concrete = mesh_axis_aligned_union(
        concrete_members,
        mesh_size,
        exclusions,
        {"hybrid_foundation": 0, "hybrid_slab": 1},
    )
    concrete = MeshFragment(
        nodes=raw_concrete.nodes,
        solids=raw_concrete.solids,
        part_bindings=tuple(
            PartBinding(binding.part_role, "concrete", binding.section_role)
            for binding in raw_concrete.part_bindings
        ),
    )
    rebar_parameters, rebar_roles = _concrete_reinforcement(parameters)
    rebar = (
        generate_reinforcement(
            concrete_members,
            rebar_parameters,
            rebar_roles,
            exclusions,
        )
        if rebar_parameters is not None
        else None
    )
    mesh = merge_fragments(
        (concrete, steel.mesh) if rebar is None else (concrete, steel.mesh, rebar)
    )
    steel_element_ids = tuple(
        row.element_id
        for row in mesh.beams
        if row.part_role.startswith("steel_")
    )
    connections = [
        make_connection(
            "hybrid_steel_joints",
            "steel_connection",
            source_element_ids=steel_element_ids,
            metadata={"joint_model": "user_selectable"},
        ),
        make_connection(
            "hybrid_composite_interface",
            "composite_interface",
            source_element_ids=steel_element_ids,
            target_element_ids=(row.element_id for row in mesh.solids),
            metadata={"interface_model": "user_selectable"},
        ),
    ]
    if rebar is not None:
        connections.append(
            make_connection(
                "hybrid_embedded_rebar",
                "embedded_rebar",
                source_element_ids=(
                    row.element_id
                    for row in mesh.beams
                    if row.part_role in {"foundation_rebar", "slab_rebar"}
                ),
                target_element_ids=(row.element_id for row in mesh.solids),
                metadata={"method": "constrained_lagrange_in_solid"},
            )
        )
    asset_id = normalized["asset_id"]
    assert isinstance(asset_id, str)
    return BuildingArtifact(
        asset_id=asset_id,
        system_id=descriptor.system_id,
        mesh=mesh,
        connections=tuple(connections),
        normalized_input=normalized,
        topology_manifest=topology.to_manifest(),
        dependency_manifest=(
            {
                "module": "refined_building.backends.hybrid",
                "version": "1.0.0",
                "material_roles": (
                    ["concrete", "structural_steel", "reinforcing_steel"]
                    if rebar is not None
                    else ["concrete", "structural_steel"]
                ),
            },
        ),
        requires_project_review=True,
    )


def _positive(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a positive finite number")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{key} must be a positive finite number")
    return result


def _concrete_reinforcement(
    parameters: Mapping[str, object],
) -> tuple[dict[str, object] | None, frozenset[str]]:
    if "concrete_reinforcement" not in parameters:
        return None, frozenset()
    raw = parameters["concrete_reinforcement"]
    if not isinstance(raw, Mapping):
        raise ValueError("concrete_reinforcement must be a mapping")
    mode = raw.get("mode")
    allowed_roles = frozenset({"foundation_rebar", "slab_rebar"})
    if mode == "full_reinforced":
        roles = allowed_roles
    elif mode == "concrete_only":
        roles = frozenset()
    elif mode == "custom":
        selected = raw.get("include_roles")
        if not isinstance(selected, list) or any(
            not isinstance(role, str) for role in selected
        ):
            raise ValueError("concrete_reinforcement.include_roles must be a list of role ids")
        unknown = set(selected) - allowed_roles
        if unknown:
            raise ValueError(
                f"unknown concrete reinforcement roles: {sorted(unknown)}"
            )
        roles = frozenset(selected)
    else:
        raise ValueError(f"unsupported concrete_reinforcement mode: {mode!r}")

    translated = {
        key: raw[key]
        for key in (
            "cover_m",
            "bar_diameter_m",
            "rebar_spacing_m",
            "rebar_target_length_m",
        )
        if key in raw
    }
    translated["generation_mode"] = "custom"
    translated["include_reinforcement_roles"] = sorted(roles)
    return translated, roles
