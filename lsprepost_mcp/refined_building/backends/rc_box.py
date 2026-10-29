"""Reinforced-concrete box backend for enclosed/underground buildings."""

from __future__ import annotations

import math
from collections.abc import Mapping

from ..artifacts import BuildingArtifact
from ..connections import make_connection
from ..contracts import normalize_building_definition
from ..meshing import merge_fragments, mesh_axis_aligned_union
from ..reinforcement import generate_reinforcement, selected_reinforcement_roles
from ..spatial import AxisAlignedBox, SpatialTopology
from ..systems import StructuralSystemDescriptor, normalize_structural_system_profile


def compile_rc_box(
    definition: Mapping[str, object],
    topology: SpatialTopology,
    descriptor: StructuralSystemDescriptor,
) -> BuildingArtifact:
    if descriptor.backend_key != "rc_box":
        raise ValueError(f"descriptor {descriptor.system_id!r} is not an RC-box backend")
    normalized = normalize_building_definition(definition)
    profile_raw = normalized["structural_system"]
    assert isinstance(profile_raw, dict)
    profile = normalize_structural_system_profile(profile_raw)
    if profile["type"] != descriptor.system_id:
        raise ValueError("definition structural system does not match descriptor")
    normalized["structural_system"] = profile
    parameters = profile["parameters"]
    assert isinstance(parameters, dict)
    thickness = _positive(parameters.get("box_thickness_m", 0.2), "box_thickness_m")
    floor_thickness = _positive(
        parameters.get("floor_thickness_m", thickness), "floor_thickness_m"
    )
    wall_thickness = _positive(
        parameters.get("wall_thickness_m", thickness), "wall_thickness_m"
    )
    roof_thickness = _positive(
        parameters.get("roof_thickness_m", thickness), "roof_thickness_m"
    )
    mesh_size = _positive(parameters.get("mesh_size_m", 0.5), "mesh_size_m")
    envelope = topology.envelope
    envelope_height = envelope.max_z - envelope.min_z
    if floor_thickness + roof_thickness >= envelope_height:
        raise ValueError(
            "floor_thickness_m + roof_thickness_m must be smaller than envelope height"
        )
    if 2.0 * wall_thickness >= min(
        envelope.max_x - envelope.min_x,
        envelope.max_y - envelope.min_y,
    ):
        raise ValueError("wall_thickness_m leaves no x/y internal void")
    members = (
        (
            "rc_box_floor",
            AxisAlignedBox(
                envelope.min_x,
                envelope.min_y,
                envelope.min_z,
                envelope.max_x,
                envelope.max_y,
                envelope.min_z + floor_thickness,
            ),
        ),
        (
            "rc_box_roof",
            AxisAlignedBox(
                envelope.min_x,
                envelope.min_y,
                envelope.max_z - roof_thickness,
                envelope.max_x,
                envelope.max_y,
                envelope.max_z,
            ),
        ),
        (
            "rc_box_wall",
            AxisAlignedBox(
                envelope.min_x,
                envelope.min_y,
                envelope.min_z + floor_thickness,
                envelope.min_x + wall_thickness,
                envelope.max_y,
                envelope.max_z - roof_thickness,
            ),
        ),
        (
            "rc_box_wall",
            AxisAlignedBox(
                envelope.max_x - wall_thickness,
                envelope.min_y,
                envelope.min_z + floor_thickness,
                envelope.max_x,
                envelope.max_y,
                envelope.max_z - roof_thickness,
            ),
        ),
        (
            "rc_box_wall",
            AxisAlignedBox(
                envelope.min_x + wall_thickness,
                envelope.min_y,
                envelope.min_z + floor_thickness,
                envelope.max_x - wall_thickness,
                envelope.min_y + wall_thickness,
                envelope.max_z - roof_thickness,
            ),
        ),
        (
            "rc_box_wall",
            AxisAlignedBox(
                envelope.min_x + wall_thickness,
                envelope.max_y - wall_thickness,
                envelope.min_z + floor_thickness,
                envelope.max_x - wall_thickness,
                envelope.max_y,
                envelope.max_z - roof_thickness,
            ),
        ),
    )
    exclusions = tuple(box for _, box in topology.opening_regions)
    concrete = mesh_axis_aligned_union(
        members,
        mesh_size,
        exclusions,
        {"rc_box_floor": 0, "rc_box_wall": 1, "rc_box_roof": 2},
    )
    roles = selected_reinforcement_roles(parameters)
    rebar = generate_reinforcement(members, parameters, roles, exclusions)
    if rebar is None:
        mesh = concrete
        connections = ()
    else:
        mesh = merge_fragments((concrete, rebar))
        connections = (
            make_connection(
                "rc_box_embedded_rebar",
                "embedded_rebar",
                source_element_ids=(row.element_id for row in mesh.beams),
                target_element_ids=(row.element_id for row in mesh.solids),
                metadata={"method": "constrained_lagrange_in_solid"},
            ),
        )
    asset_id = normalized["asset_id"]
    assert isinstance(asset_id, str)
    return BuildingArtifact(
        asset_id=asset_id,
        system_id=descriptor.system_id,
        mesh=mesh,
        connections=connections,
        normalized_input=normalized,
        topology_manifest=topology.to_manifest(),
        dependency_manifest=(
            {
                "module": "refined_building.backends.rc_box",
                "version": "1.0.0",
                "material_roles": ["concrete", "reinforcing_steel"] if rebar else ["concrete"],
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
