"""Allocation-free element-family preflight for detailed building assets."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from .backends.rc import _build_member_boxes
from .contracts import normalize_building_definition
from .meshing import count_axis_aligned_union_nodes
from .nonstructural import estimate_nonstructural_size
from .reinforcement import estimate_reinforcement_size, selected_reinforcement_roles
from .spatial import AxisAlignedBox, SpatialTopology, compile_spatial_topology
from .systems import normalize_structural_system_profile


def estimate_template_families(
    definitions: Sequence[Mapping[str, object]],
    *,
    solid_count: int,
    solid_estimation_kind: str,
) -> dict[str, dict[str, object]]:
    """Return exact or proved-upper-bound family sizes before FE allocation."""

    beams = 0
    shells = 0
    nodes = 0
    exact_beams = True
    exact_nodes = True
    for definition in definitions:
        structural = _estimate_structural(definition)
        panel_shells, panel_nodes = estimate_nonstructural_size(definition)
        beams += structural["beams"]
        shells += structural["shells"] + panel_shells
        nodes += structural["nodes"] + panel_nodes
        exact_beams = exact_beams and structural["beams_exact"]
        exact_nodes = exact_nodes and structural["nodes_exact"]
    total = solid_count + beams + shells
    solid_kind = "exact" if solid_estimation_kind == "exact" else "proved_upper_bound"
    total_kind = (
        "exact"
        if solid_kind == "exact" and exact_beams
        else "proved_upper_bound"
    )
    return {
        "solid_elements": _row(solid_count, solid_kind),
        "beam_elements": _row(beams, "exact" if exact_beams else "proved_upper_bound"),
        "shell_elements": _row(shells, "proved_upper_bound"),
        "node_count": _row(nodes, "exact" if exact_nodes else "proved_upper_bound"),
        "total_elements": _row(total, total_kind),
    }


def _row(count: int, kind: str) -> dict[str, object]:
    return {"estimated_count": int(count), "estimation_kind": kind}


def _estimate_structural(definition: Mapping[str, object]) -> dict[str, object]:
    normalized = normalize_building_definition(definition)
    topology = compile_spatial_topology(normalized)
    raw_profile = normalized["structural_system"]
    assert isinstance(raw_profile, dict)
    profile = normalize_structural_system_profile(raw_profile)
    parameters = profile["parameters"]
    assert isinstance(parameters, dict)
    system_id = str(profile["type"])
    if "task4_subway_solid_members" in parameters:
        return _estimate_task4_subway(parameters, topology)
    if system_id in {"rc_frame", "rc_frame_shear_wall"}:
        members = _build_member_boxes(
            normalized,
            topology,
            system_id,
            column_width=float(parameters.get("column_width_m", 0.3)),
            column_depth=float(parameters.get("column_depth_m", 0.3)),
            beam_width=float(parameters.get("beam_width_m", 0.3)),
            beam_depth=float(parameters.get("beam_depth_m", 0.4)),
            slab_thickness=float(parameters.get("slab_thickness_m", 0.2)),
            foundation_thickness=float(parameters.get("foundation_thickness_m", 0.2)),
        )
        exclusions = tuple(box for _, box in topology.opening_regions)
        mesh_size = float(parameters.get("mesh_size_m", 0.5))
        solid_nodes = count_axis_aligned_union_nodes(
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
        roles = selected_reinforcement_roles(parameters)
        beam_count, rebar_nodes = estimate_reinforcement_size(members, parameters, roles)
        return {
            "beams": beam_count,
            "shells": 0,
            "nodes": solid_nodes + rebar_nodes,
            "beams_exact": not roles,
            "nodes_exact": not roles,
        }
    if system_id == "steel_concrete_hybrid":
        envelope = topology.envelope
        levels = normalized["levels"]
        assert isinstance(levels, list)
        slab = float(parameters.get("slab_thickness_m", 0.2))
        foundation = float(parameters.get("foundation_thickness_m", 0.2))
        concrete_members: list[tuple[str, AxisAlignedBox]] = [
            (
                "hybrid_foundation",
                AxisAlignedBox(
                    envelope.min_x,
                    envelope.min_y,
                    envelope.min_z,
                    envelope.max_x,
                    envelope.max_y,
                    envelope.min_z + foundation,
                ),
            )
        ]
        for level in levels:
            assert isinstance(level, dict)
            top = float(level["elevation_m"]) + float(level["height_m"])
            concrete_members.append(
                (
                    "hybrid_slab",
                    AxisAlignedBox(
                        envelope.min_x,
                        envelope.min_y,
                        top - slab,
                        envelope.max_x,
                        envelope.max_y,
                        top,
                    ),
                )
            )
        exclusions = tuple(box for _, box in topology.opening_regions)
        concrete_nodes = count_axis_aligned_union_nodes(
            concrete_members,
            float(parameters.get("mesh_size_m", 0.5)),
            exclusions,
            {"hybrid_foundation": 0, "hybrid_slab": 1},
        )
        steel_beams, steel_shells, steel_nodes, steel_exact = _estimate_steel(
            normalized, parameters
        )
        rebar_parameters, roles = _hybrid_rebar(parameters)
        rebar_beams, rebar_nodes = (
            estimate_reinforcement_size(concrete_members, rebar_parameters, roles)
            if rebar_parameters is not None
            else (0, 0)
        )
        return {
            "beams": steel_beams + rebar_beams,
            "shells": steel_shells,
            "nodes": concrete_nodes + steel_nodes + rebar_nodes,
            "beams_exact": not roles and steel_exact,
            "nodes_exact": not roles and steel_exact,
        }
    if system_id == "rc_box":
        envelope = topology.envelope
        floor = float(parameters.get("floor_thickness_m", parameters.get("box_thickness_m", 0.2)))
        wall = float(parameters.get("wall_thickness_m", parameters.get("box_thickness_m", 0.2)))
        roof = float(parameters.get("roof_thickness_m", parameters.get("box_thickness_m", 0.2)))
        members = _rc_box_members(envelope, floor, wall, roof)
        exclusions = tuple(box for _, box in topology.opening_regions)
        solid_nodes = count_axis_aligned_union_nodes(
            members,
            float(parameters.get("mesh_size_m", 0.5)),
            exclusions,
            {"rc_box_floor": 0, "rc_box_wall": 1, "rc_box_roof": 2},
        )
        roles = selected_reinforcement_roles(parameters)
        beam_count, rebar_nodes = estimate_reinforcement_size(members, parameters, roles)
        return {
            "beams": beam_count,
            "shells": 0,
            "nodes": solid_nodes + rebar_nodes,
            "beams_exact": not roles,
            "nodes_exact": not roles,
        }
    raise ValueError(f"unsupported detailed structural system {system_id!r}")


def _estimate_steel(
    normalized: Mapping[str, object], parameters: Mapping[str, object]
) -> tuple[int, int, int, bool]:
    axes = normalized["grid_axes"]
    levels = normalized["levels"]
    assert isinstance(axes, dict) and isinstance(levels, list)
    xs = tuple(float(value) for value in axes["x_m"])  # type: ignore[arg-type]
    ys = tuple(float(value) for value in axes["y_m"])  # type: ignore[arg-type]
    z_values: list[float] = []
    for level in levels:
        assert isinstance(level, dict)
        base = float(level["elevation_m"])
        top = base + float(level["height_m"])
        if base not in z_values:
            z_values.append(base)
        if top not in z_values:
            z_values.append(top)
    z_values.sort()
    target_raw = parameters.get("member_target_length_m")
    target = float(target_raw) if target_raw is not None else None
    beams = 0
    extra_nodes = 0

    def add(length: float, count: int) -> None:
        nonlocal beams, extra_nodes
        segments = 1 if target is None else max(1, math.ceil(length / target))
        beams += count * segments
        extra_nodes += count * (segments - 1)

    for lower, upper in zip(z_values, z_values[1:]):
        add(upper - lower, len(xs) * len(ys))
    for left, right in zip(xs, xs[1:]):
        add(right - left, (len(z_values) - 1) * len(ys))
    for lower, upper in zip(ys, ys[1:]):
        add(upper - lower, (len(z_values) - 1) * len(xs))
    shells = max(0, len(xs) - 1) * max(0, len(ys) - 1)
    nodes = len(xs) * len(ys) * len(z_values) + extra_nodes
    opening_profile = parameters.get("opening_frame_profile")
    exact = opening_profile is None
    if isinstance(opening_profile, Mapping):
        openings = normalized["openings"]
        assert isinstance(openings, list)
        opening_id = opening_profile.get("opening_id")
        opening = next(
            row
            for row in openings
            if isinstance(row, dict) and row.get("id") == opening_id
        )
        bounds = opening["bounds_m"]
        assert isinstance(bounds, list)
        depth = float(opening_profile["section_depth_m"])
        header_z = float(bounds[5]) + depth / 2.0
        width = float(opening_profile["section_width_m"])
        left_jamb = float(bounds[0]) - width / 2.0
        right_jamb = float(bounds[3]) + width / 2.0
        header_breaks = sorted(
            {left_jamb, right_jamb} | {x for x in xs if left_jamb < x < right_jamb}
        )
        added_lengths = (
            header_z - z_values[0],
            z_values[-1] - header_z,
            header_z - z_values[0],
            z_values[-1] - header_z,
            *(right - left for left, right in zip(header_breaks, header_breaks[1:])),
        )
        for length in added_lengths:
            segments = 1 if target is None else max(1, math.ceil(length / target))
            beams += segments
            nodes += segments + 1
    return beams, shells, nodes, exact


def _hybrid_rebar(
    parameters: Mapping[str, object],
) -> tuple[dict[str, object] | None, frozenset[str]]:
    raw = parameters.get("concrete_reinforcement")
    if not isinstance(raw, Mapping):
        return None, frozenset()
    mode = raw.get("mode")
    allowed = frozenset({"foundation_rebar", "slab_rebar"})
    if mode == "full_reinforced":
        roles = allowed
    elif mode == "concrete_only":
        roles = frozenset()
    elif mode == "custom":
        selected = raw.get("include_roles", [])
        roles = frozenset(str(role) for role in selected) if isinstance(selected, list) else frozenset()
    else:
        roles = frozenset()
    translated = {
        key: raw[key]
        for key in ("cover_m", "bar_diameter_m", "rebar_spacing_m", "rebar_target_length_m")
        if key in raw
    }
    return translated, roles


def _estimate_task4_subway(parameters: Mapping[str, object], topology: object) -> dict[str, object]:
    if not isinstance(topology, SpatialTopology):
        raise TypeError("Task 4 subway topology is invalid")
    raw_members = parameters["task4_subway_solid_members"]
    assert isinstance(raw_members, list)
    members = tuple(
        (str(row["part_role"]), AxisAlignedBox.from_bounds(row["bounds_m"]))
        for row in raw_members
        if isinstance(row, dict)
    )
    target = float(parameters["task4_subway_solid_target_m"])
    exclusions = tuple(box for _, box in topology.opening_regions)
    base = tuple((role, box) for role, box in members if role.startswith("rc_"))
    circulation = tuple((role, box) for role, box in members if not role.startswith("rc_"))
    priorities = {
        "rc_box_floor": 0,
        "rc_box_wall": 1,
        "rc_box_roof": 2,
        "rc_frame_column": 3,
        "rc_frame_roof_beam": 3,
        "pavilion_rc_plinth": 3,
        "lower_landing_8": 4,
        "upper_landing": 4,
        "fixed_stair_A": 5,
    }
    raw_interfaces = parameters["task4_pavilion_plinth_interface_coordinates_m"]
    assert isinstance(raw_interfaces, list)
    interfaces = tuple(
        tuple(float(value) for value in point)
        for point in raw_interfaces
        if isinstance(point, list)
    )
    solid_nodes = count_axis_aligned_union_nodes(
        base,
        target,
        (*exclusions, *(box for _, box in circulation)),
        priorities,
    ) + count_axis_aligned_union_nodes(
        circulation,
        target,
        exclusions,
        priorities,
        interfaces,  # type: ignore[arg-type]
    )
    roles = selected_reinforcement_roles(parameters)
    rebar_beams, rebar_nodes = estimate_reinforcement_size(base, parameters, roles)
    if "slab_rebar" in roles:
        for selected_roles in ({"fixed_stair_A"}, {"upper_landing", "lower_landing_8"}, {"pavilion_rc_plinth"}):
            boxes = tuple(box for role, box in members if role in selected_roles)
            if selected_roles == {"fixed_stair_A"}:
                stair_beams, stair_nodes = _estimate_stair_rebar(boxes, parameters)
            else:
                stair_beams, stair_nodes = estimate_reinforcement_size(
                    (("rc_slab", box) for box in boxes),
                    parameters,
                    frozenset({"slab_rebar"}),
                )
            rebar_beams += stair_beams
            rebar_nodes += stair_nodes
    components = parameters.get("task4_subway_components", [])
    assert isinstance(components, list)
    component_beams = sum(row.get("kind") == "beam" for row in components if isinstance(row, dict))
    component_shells = sum(row.get("kind") == "shell" for row in components if isinstance(row, dict))
    component_nodes = sum(
        len(row.get("points_m", [])) for row in components if isinstance(row, dict)
    )
    return {
        "beams": rebar_beams + component_beams,
        "shells": component_shells,
        "nodes": solid_nodes + rebar_nodes + component_nodes,
        "beams_exact": not roles,
        "nodes_exact": False,
    }


def _estimate_stair_rebar(
    boxes: Sequence[AxisAlignedBox], parameters: Mapping[str, object]
) -> tuple[int, int]:
    cover = float(parameters["cover_m"])
    longitudinal = float(parameters["fixed_stair_longitudinal_spacing_m"])
    distribution = float(parameters["fixed_stair_distribution_spacing_m"])
    density = float(parameters["fixed_stair_local_densification_factor"])
    beams = 0
    lines = 0
    for index, box in enumerate(boxes):
        x = box.max_x - box.min_x - 2.0 * cover
        y = box.max_y - box.min_y - 2.0 * cover
        longitudinal_lines = max(1, math.ceil(y / longitudinal)) + 1
        distribution_lines = max(1, math.ceil(x / distribution)) + 1
        local_lines = (
            max(1, math.ceil(x / (distribution / density))) + 1
            if index in {0, len(boxes) - 1}
            else 0
        )
        beams += longitudinal_lines + distribution_lines + local_lines
        lines += longitudinal_lines + distribution_lines + local_lines
    return beams, beams + lines


def _rc_box_members(
    envelope: AxisAlignedBox, floor: float, wall: float, roof: float
) -> tuple[tuple[str, AxisAlignedBox], ...]:
    return (
        ("rc_box_floor", AxisAlignedBox(envelope.min_x, envelope.min_y, envelope.min_z, envelope.max_x, envelope.max_y, envelope.min_z + floor)),
        ("rc_box_roof", AxisAlignedBox(envelope.min_x, envelope.min_y, envelope.max_z - roof, envelope.max_x, envelope.max_y, envelope.max_z)),
        ("rc_box_wall", AxisAlignedBox(envelope.min_x, envelope.min_y, envelope.min_z + floor, envelope.min_x + wall, envelope.max_y, envelope.max_z - roof)),
        ("rc_box_wall", AxisAlignedBox(envelope.max_x - wall, envelope.min_y, envelope.min_z + floor, envelope.max_x, envelope.max_y, envelope.max_z - roof)),
        ("rc_box_wall", AxisAlignedBox(envelope.min_x + wall, envelope.min_y, envelope.min_z + floor, envelope.max_x - wall, envelope.min_y + wall, envelope.max_z - roof)),
        ("rc_box_wall", AxisAlignedBox(envelope.min_x + wall, envelope.max_y - wall, envelope.min_z + floor, envelope.max_x - wall, envelope.max_y, envelope.max_z - roof)),
    )
