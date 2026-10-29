"""Reinforced-concrete frame and frame/shear-wall backend."""

from __future__ import annotations

import math
from collections.abc import Mapping

from ..artifacts import BuildingArtifact, ConnectionArtifact, MeshFragment
from ..contracts import JSONDict, normalize_building_definition
from ..meshing import merge_fragments, mesh_axis_aligned_union
from ..reinforcement import generate_reinforcement, selected_reinforcement_roles
from ..spatial import AxisAlignedBox, SpatialTopology, compile_spatial_topology
from ..systems import (
    StructuralSystemDescriptor,
    normalize_structural_system_profile,
)


def compile_rc_structure(
    definition: Mapping[str, object],
    topology: SpatialTopology,
    descriptor: StructuralSystemDescriptor,
) -> BuildingArtifact:
    """Compile an RC frame or frame/shear-wall from current dimensions."""

    if descriptor.backend_key != "rc":
        raise ValueError(f"descriptor {descriptor.system_id!r} is not an RC frame backend")
    normalized = normalize_building_definition(definition)
    profile_raw = normalized["structural_system"]
    assert isinstance(profile_raw, dict)
    profile = normalize_structural_system_profile(profile_raw)
    if profile["type"] != descriptor.system_id:
        raise ValueError("definition structural system does not match descriptor")
    normalized["structural_system"] = profile
    parameters = profile["parameters"]
    assert isinstance(parameters, dict)

    mesh_size = _positive_parameter(parameters, "mesh_size_m", 0.5)
    column_width = _positive_parameter(parameters, "column_width_m", 0.3)
    column_depth = _positive_parameter(parameters, "column_depth_m", 0.3)
    beam_width = _positive_parameter(parameters, "beam_width_m", 0.3)
    beam_depth = _positive_parameter(parameters, "beam_depth_m", 0.4)
    slab_thickness = _positive_parameter(parameters, "slab_thickness_m", 0.2)
    foundation_thickness = _positive_parameter(parameters, "foundation_thickness_m", 0.2)

    members = _build_member_boxes(
        normalized,
        topology,
        descriptor.system_id,
        column_width=column_width,
        column_depth=column_depth,
        beam_width=beam_width,
        beam_depth=beam_depth,
        slab_thickness=slab_thickness,
        foundation_thickness=foundation_thickness,
    )
    exclusions = tuple(box for _, box in topology.opening_regions)
    concrete_mesh = mesh_axis_aligned_union(
        members,
        mesh_size,
        exclusions,
        {
            "rc_foundation": 0,
            "rc_column": 1,
            "rc_shear_wall": 2,
            "rc_beam_x": 3,
            "rc_beam_y": 3,
            "rc_opening_jamb": 3,
            "rc_opening_header": 3,
            "rc_slab": 4,
        },
    )

    included_roles = selected_reinforcement_roles(parameters)
    rebar_mesh = generate_reinforcement(
        members, parameters, included_roles, exclusions
    )
    if rebar_mesh is None:
        mesh = concrete_mesh
        connections: tuple[ConnectionArtifact, ...] = ()
    else:
        mesh = merge_fragments((concrete_mesh, rebar_mesh))
        connections = (
            ConnectionArtifact(
                "embedded_rebar_1",
                "embedded_rebar",
                tuple(beam.element_id for beam in mesh.beams),
                tuple(solid.element_id for solid in mesh.solids),
                (("method", "constrained_lagrange_in_solid"),),
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
                "module": "refined_building.backends.rc",
                "version": "1.0.0",
                "material_roles": ["concrete", "reinforcing_steel"] if rebar_mesh else ["concrete"],
            },
        ),
        requires_project_review=True,
    )


def _build_member_boxes(
    normalized: JSONDict,
    topology: SpatialTopology,
    system_id: str,
    *,
    column_width: float,
    column_depth: float,
    beam_width: float,
    beam_depth: float,
    slab_thickness: float,
    foundation_thickness: float,
) -> list[tuple[str, AxisAlignedBox]]:
    envelope = topology.envelope
    axes = normalized["grid_axes"]
    levels = normalized["levels"]
    assert isinstance(axes, dict) and isinstance(levels, list)
    x_axes = tuple(float(value) for value in axes["x_m"])  # type: ignore[arg-type]
    y_axes = tuple(float(value) for value in axes["y_m"])  # type: ignore[arg-type]
    members: list[tuple[str, AxisAlignedBox]] = []

    lowest_elevation = min(
        float(level["elevation_m"]) for level in levels if isinstance(level, dict)
    )
    foundation_top = lowest_elevation + foundation_thickness
    if foundation_top >= envelope.max_z:
        raise ValueError("foundation_thickness_m must be smaller than envelope height")
    members.append(
        (
            "rc_foundation",
            AxisAlignedBox(
                envelope.min_x,
                envelope.min_y,
                lowest_elevation,
                envelope.max_x,
                envelope.max_y,
                foundation_top,
            ),
        )
    )

    for level in levels:
        assert isinstance(level, dict)
        level_base = float(level["elevation_m"])
        level_top = level_base + float(level["height_m"])
        beam_min_z = level_top - slab_thickness - beam_depth
        if beam_min_z < level_base:
            raise ValueError("beam_depth_m places beam below level base")
        column_min_z = (
            level_base + foundation_thickness
            if level_base == lowest_elevation
            else level_base
        )
        column_max_z = level_top - slab_thickness
        if column_max_z <= column_min_z:
            raise ValueError("level has no positive column height after floor/roof layers")
        for x in x_axes:
            for y in y_axes:
                box = _centered_xy_box(
                    x,
                    y,
                    column_width,
                    column_depth,
                    column_min_z,
                    column_max_z,
                    envelope,
                )
                members.append(("rc_column", box))

        beam_max_z = level_top - slab_thickness
        for y in y_axes:
            for left, right in zip(x_axes, x_axes[1:]):
                box = AxisAlignedBox(
                    left,
                    max(envelope.min_y, y - beam_width / 2.0),
                    beam_min_z,
                    right,
                    min(envelope.max_y, y + beam_width / 2.0),
                    beam_max_z,
                )
                members.append(("rc_beam_x", box))
        for x in x_axes:
            for lower, upper in zip(y_axes, y_axes[1:]):
                box = AxisAlignedBox(
                    max(envelope.min_x, x - beam_width / 2.0),
                    lower,
                    beam_min_z,
                    min(envelope.max_x, x + beam_width / 2.0),
                    upper,
                    beam_max_z,
                )
                members.append(("rc_beam_y", box))
        members.append(
            (
                "rc_slab",
                AxisAlignedBox(
                    envelope.min_x,
                    envelope.min_y,
                    level_top - slab_thickness,
                    envelope.max_x,
                    envelope.max_y,
                    level_top,
                ),
            )
        )

    profile = normalized["structural_system"]
    assert isinstance(profile, dict)
    parameters = profile["parameters"]
    assert isinstance(parameters, dict)
    opening_frame = _opening_frame_bounds(normalized, parameters)
    if opening_frame is not None:
        opening, section_width, section_depth = opening_frame
        removed_columns = [
            box
            for role, box in members
            if role == "rc_column" and _positive_volume_overlap(box, opening)
        ]
        if not removed_columns:
            raise ValueError("opening frame has no conflicting front column to replace")
        members = [
            (role, box)
            for role, box in members
            if role not in {"rc_column", "rc_beam_x", "rc_beam_y"}
            or not _positive_volume_overlap(box, opening)
        ]
        header_top = opening.max_z + section_depth
        for box in removed_columns:
            if header_top < box.max_z - 1.0e-12:
                members.append(
                    (
                        "rc_column",
                        AxisAlignedBox(
                            box.min_x,
                            box.min_y,
                            header_top,
                            box.max_x,
                            box.max_y,
                            box.max_z,
                        ),
                    )
                )
        column_min_z = min(box.min_z for box in removed_columns)
        column_max_z = max(box.max_z for box in removed_columns)
        front_depth = min(column_depth, envelope.max_y - opening.min_y)
        members.append(
            (
                "rc_opening_jamb",
                AxisAlignedBox(
                    opening.min_x - section_width,
                    opening.min_y,
                    column_min_z,
                    opening.min_x,
                    opening.min_y + front_depth,
                    column_max_z,
                ),
            )
        )
        members.append(
            (
                "rc_opening_jamb",
                AxisAlignedBox(
                    opening.max_x,
                    opening.min_y,
                    column_min_z,
                    opening.max_x + section_width,
                    opening.min_y + front_depth,
                    column_max_z,
                ),
            )
        )
        members.append(
            (
                "rc_opening_header",
                AxisAlignedBox(
                    opening.min_x - section_width,
                    opening.min_y,
                    opening.max_z,
                    opening.max_x + section_width,
                    opening.min_y + min(beam_width, envelope.max_y - opening.min_y),
                    header_top,
                ),
            )
        )

    if system_id == "rc_frame_shear_wall":
        wall_thickness = min(column_width, column_depth)
        wall_boxes = _declared_or_default_walls(normalized, topology, wall_thickness)
        members.extend(("rc_shear_wall", box) for box in wall_boxes)

    return members


def _opening_frame_bounds(
    normalized: JSONDict, parameters: Mapping[str, object]
) -> tuple[AxisAlignedBox, float, float] | None:
    raw = parameters.get("opening_frame_profile")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("opening_frame_profile must be a mapping")
    if raw.get("profile_id") != "commercial_front_entrance_v1":
        raise ValueError("unsupported opening_frame_profile.profile_id")
    opening_id = raw.get("opening_id")
    openings = normalized["openings"]
    assert isinstance(openings, list)
    opening_row = next(
        (
            row
            for row in openings
            if isinstance(row, dict) and row.get("id") == opening_id
        ),
        None,
    )
    if opening_row is None or not isinstance(opening_row.get("bounds_m"), list):
        raise ValueError("opening_frame_profile opening does not exist")
    section_width = _positive_parameter(
        raw, "section_width_m", 0.3
    )
    section_depth = _positive_parameter(
        raw, "section_depth_m", 0.4
    )
    opening = AxisAlignedBox.from_bounds(opening_row["bounds_m"])
    envelope = compile_spatial_topology(normalized).envelope
    if (
        opening.min_x - section_width < envelope.min_x
        or opening.max_x + section_width > envelope.max_x
        or opening.max_z + section_depth >= envelope.max_z
    ):
        raise ValueError("opening_frame_profile does not fit the building envelope")
    return opening, section_width, section_depth


def _positive_volume_overlap(left: AxisAlignedBox, right: AxisAlignedBox) -> bool:
    left_bounds = left.as_tuple()
    right_bounds = right.as_tuple()
    return all(
        min(left_bounds[axis + 3], right_bounds[axis + 3])
        - max(left_bounds[axis], right_bounds[axis])
        > 1.0e-12
        for axis in range(3)
    )


def _declared_or_default_walls(
    normalized: JSONDict, topology: SpatialTopology, thickness: float
) -> tuple[AxisAlignedBox, ...]:
    profile = normalized["structural_system"]
    assert isinstance(profile, dict)
    parameters = profile["parameters"]
    assert isinstance(parameters, dict)
    declared = parameters.get("wall_bounds_m")
    if declared is not None:
        if not isinstance(declared, list) or not declared:
            raise ValueError("wall_bounds_m must be a non-empty list")
        boxes = tuple(AxisAlignedBox.from_bounds(value) for value in declared)  # type: ignore[arg-type]
        if any(not topology.envelope.contains_box(box) for box in boxes):
            raise ValueError("wall_bounds_m entries must be inside envelope")
        return boxes
    envelope = topology.envelope
    return (
        AxisAlignedBox(
            envelope.min_x,
            envelope.min_y,
            envelope.min_z,
            envelope.min_x + thickness,
            envelope.max_y,
            envelope.max_z,
        ),
        AxisAlignedBox(
            envelope.max_x - thickness,
            envelope.min_y,
            envelope.min_z,
            envelope.max_x,
            envelope.max_y,
            envelope.max_z,
        ),
    )


def _centered_xy_box(
    x: float,
    y: float,
    width: float,
    depth: float,
    min_z: float,
    max_z: float,
    envelope: AxisAlignedBox,
) -> AxisAlignedBox:
    return AxisAlignedBox(
        max(envelope.min_x, x - width / 2.0),
        max(envelope.min_y, y - depth / 2.0),
        min_z,
        min(envelope.max_x, x + width / 2.0),
        min(envelope.max_y, y + depth / 2.0),
        max_z,
    )


def _positive_parameter(parameters: Mapping[str, object], key: str, default: float) -> float:
    raw = parameters.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{key} must be a positive finite number")
    result = float(raw)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{key} must be a positive finite number")
    return result
