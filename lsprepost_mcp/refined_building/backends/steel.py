"""Steel-frame backend for refined buildings."""

from __future__ import annotations

import math
from collections.abc import Mapping

from ..artifacts import (
    BeamElement,
    BuildingArtifact,
    MeshFragment,
    Node,
    PartBinding,
    ShellElement,
)
from ..connections import make_connection
from ..contracts import normalize_building_definition
from ..spatial import SpatialTopology
from ..systems import StructuralSystemDescriptor, normalize_structural_system_profile


def compile_steel_frame(
    definition: Mapping[str, object],
    topology: SpatialTopology,
    descriptor: StructuralSystemDescriptor,
) -> BuildingArtifact:
    if descriptor.backend_key != "steel":
        raise ValueError(f"descriptor {descriptor.system_id!r} is not a steel backend")
    normalized = normalize_building_definition(definition)
    profile_raw = normalized["structural_system"]
    assert isinstance(profile_raw, dict)
    profile = normalize_structural_system_profile(profile_raw)
    if profile["type"] != descriptor.system_id:
        raise ValueError("definition structural system does not match descriptor")
    normalized["structural_system"] = profile

    axes = normalized["grid_axes"]
    levels = normalized["levels"]
    assert isinstance(axes, dict) and isinstance(levels, list)
    xs = tuple(float(value) for value in axes["x_m"])  # type: ignore[arg-type]
    ys = tuple(float(value) for value in axes["y_m"])  # type: ignore[arg-type]
    parameters = profile["parameters"]
    assert isinstance(parameters, dict)
    member_target = (
        _positive(parameters["member_target_length_m"], "member_target_length_m")
        if "member_target_length_m" in parameters
        else None
    )
    opening_profile = _opening_frame_profile(normalized, parameters)
    if opening_profile is not None:
        return _compile_opening_aware_steel_frame(
            normalized,
            topology,
            descriptor,
            member_target,
            opening_profile,
        )

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

    nodes: list[Node] = []
    node_by_key: dict[tuple[float, float, float], int] = {}
    for z in z_values:
        for y in ys:
            for x in xs:
                node_id = len(nodes) + 1
                nodes.append(Node(node_id, x, y, z))
                node_by_key[(x, y, z)] = node_id

    beams: list[BeamElement] = []
    element_id = 1

    def append_member(start_id: int, end_id: int, role: str) -> None:
        nonlocal element_id
        if member_target is None:
            beams.append(BeamElement(element_id, (start_id, end_id), role))
            element_id += 1
            return
        start = nodes[start_id - 1].coordinates
        end = nodes[end_id - 1].coordinates
        segment_count = max(1, math.ceil(math.dist(start, end) / member_target))
        previous_id = start_id
        for segment_index in range(1, segment_count):
            node_id = len(nodes) + 1
            coordinate = tuple(
                start[axis]
                + (end[axis] - start[axis]) * segment_index / segment_count
                for axis in range(3)
            )
            nodes.append(Node(node_id, *coordinate))
            beams.append(BeamElement(element_id, (previous_id, node_id), role))
            element_id += 1
            previous_id = node_id
        beams.append(BeamElement(element_id, (previous_id, end_id), role))
        element_id += 1

    for lower, upper in zip(z_values, z_values[1:]):
        for y in ys:
            for x in xs:
                append_member(
                    node_by_key[(x, y, lower)],
                    node_by_key[(x, y, upper)],
                    "steel_column",
                )
    for z in z_values[1:]:
        for y in ys:
            for left, right in zip(xs, xs[1:]):
                append_member(
                    node_by_key[(left, y, z)],
                    node_by_key[(right, y, z)],
                    "steel_beam",
                )
        for x in xs:
            for lower, upper in zip(ys, ys[1:]):
                append_member(
                    node_by_key[(x, lower, z)],
                    node_by_key[(x, upper, z)],
                    "steel_beam",
                )

    shells: list[ShellElement] = []
    roof_z = z_values[-1]
    for lower_y, upper_y in zip(ys, ys[1:]):
        for left_x, right_x in zip(xs, xs[1:]):
            shells.append(
                ShellElement(
                    element_id,
                    (
                        node_by_key[(left_x, lower_y, roof_z)],
                        node_by_key[(right_x, lower_y, roof_z)],
                        node_by_key[(right_x, upper_y, roof_z)],
                        node_by_key[(left_x, upper_y, roof_z)],
                    ),
                    "steel_roof_deck",
                )
            )
            element_id += 1
    mesh = MeshFragment(
        nodes=tuple(nodes),
        beams=tuple(beams),
        shells=tuple(shells),
        part_bindings=(
            PartBinding("steel_column", "structural_steel", "steel_column_section"),
            PartBinding("steel_beam", "structural_steel", "steel_beam_section"),
            PartBinding("steel_roof_deck", "structural_steel", "steel_shell_section"),
        ),
    )
    connection = make_connection(
        "steel_frame_joints",
        "steel_connection",
        source_element_ids=(row.element_id for row in beams),
        metadata={"joint_model": "user_selectable"},
    )
    asset_id = normalized["asset_id"]
    assert isinstance(asset_id, str)
    return BuildingArtifact(
        asset_id=asset_id,
        system_id=descriptor.system_id,
        mesh=mesh,
        connections=(connection,),
        normalized_input=normalized,
        topology_manifest=topology.to_manifest(),
        dependency_manifest=(
            {
                "module": "refined_building.backends.steel",
                "version": "1.0.0",
                "material_roles": ["structural_steel"],
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


def _opening_frame_profile(
    normalized: Mapping[str, object], parameters: Mapping[str, object]
) -> dict[str, object] | None:
    raw = parameters.get("opening_frame_profile")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("opening_frame_profile must be a mapping")
    if raw.get("profile_id") != "commercial_front_entrance_v1":
        raise ValueError("unsupported opening_frame_profile.profile_id")
    opening_id = raw.get("opening_id")
    if not isinstance(opening_id, str) or not opening_id:
        raise ValueError("opening_frame_profile.opening_id is required")
    openings = normalized["openings"]
    assert isinstance(openings, list)
    opening = next(
        (
            row
            for row in openings
            if isinstance(row, dict) and row.get("id") == opening_id
        ),
        None,
    )
    if opening is None or not isinstance(opening.get("bounds_m"), list):
        raise ValueError("opening_frame_profile opening does not exist")
    return {
        "profile_id": "commercial_front_entrance_v1",
        "opening_id": opening_id,
        "bounds_m": tuple(float(value) for value in opening["bounds_m"]),
        "section_width_m": _positive(
            raw.get("section_width_m"), "opening_frame_profile.section_width_m"
        ),
        "section_depth_m": _positive(
            raw.get("section_depth_m"), "opening_frame_profile.section_depth_m"
        ),
    }


def _compile_opening_aware_steel_frame(
    normalized: dict[str, object],
    topology: SpatialTopology,
    descriptor: StructuralSystemDescriptor,
    member_target: float | None,
    profile: Mapping[str, object],
) -> BuildingArtifact:
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
    opening = profile["bounds_m"]
    assert isinstance(opening, tuple)
    section_width = float(profile["section_width_m"])
    section_depth = float(profile["section_depth_m"])
    front_y = opening[1]
    header_z = opening[5] + section_depth / 2.0
    if header_z >= z_values[-1]:
        raise ValueError("opening frame header leaves no upper steel load path")
    left_jamb_x = opening[0] - section_width / 2.0
    right_jamb_x = opening[3] + section_width / 2.0
    envelope = topology.envelope
    if left_jamb_x < envelope.min_x or right_jamb_x > envelope.max_x:
        raise ValueError("opening frame jambs are outside the building envelope")

    nodes: list[Node] = []
    node_by_key: dict[tuple[float, float, float], int] = {}
    beams: list[BeamElement] = []

    def node_id(point: tuple[float, float, float]) -> int:
        key = tuple(round(value, 12) for value in point)
        existing = node_by_key.get(key)
        if existing is not None:
            return existing
        result = len(nodes) + 1
        node_by_key[key] = result
        nodes.append(Node(result, *point))
        return result

    def append_member(
        start: tuple[float, float, float],
        end: tuple[float, float, float],
        role: str,
    ) -> None:
        segments = (
            1
            if member_target is None
            else max(1, math.ceil(math.dist(start, end) / member_target))
        )
        previous = node_id(start)
        for index in range(1, segments + 1):
            point = tuple(
                start[axis] + (end[axis] - start[axis]) * index / segments
                for axis in range(3)
            )
            current = node_id(point)  # type: ignore[arg-type]
            beams.append(BeamElement(len(beams) + 1, (previous, current), role))
            previous = current

    for lower, upper in zip(z_values, z_values[1:]):
        for y in ys:
            for x in xs:
                conflicts = (
                    abs(y - front_y) <= 1.0e-12
                    and x + section_width / 2.0 > opening[0] + 1.0e-12
                    and x - section_width / 2.0 < opening[3] - 1.0e-12
                    and lower < opening[5] - 1.0e-12
                )
                start_z = max(lower, header_z) if conflicts else lower
                if start_z < upper - 1.0e-12:
                    append_member((x, y, start_z), (x, y, upper), "steel_column")

    base_z = z_values[0]
    roof_z = z_values[-1]
    for jamb_x in (left_jamb_x, right_jamb_x):
        append_member(
            (jamb_x, front_y, base_z),
            (jamb_x, front_y, header_z),
            "steel_opening_jamb",
        )
        append_member(
            (jamb_x, front_y, header_z),
            (jamb_x, front_y, roof_z),
            "steel_opening_jamb",
        )

    header_breaks = tuple(
        sorted(
            {left_jamb_x, right_jamb_x}
            | {x for x in xs if left_jamb_x < x < right_jamb_x}
        )
    )
    for left, right in zip(header_breaks, header_breaks[1:]):
        append_member(
            (left, front_y, header_z),
            (right, front_y, header_z),
            "steel_opening_header",
        )

    for z in z_values[1:]:
        for y in ys:
            for left, right in zip(xs, xs[1:]):
                append_member((left, y, z), (right, y, z), "steel_beam")
        for x in xs:
            for lower, upper in zip(ys, ys[1:]):
                append_member((x, lower, z), (x, upper, z), "steel_beam")

    shells: list[ShellElement] = []
    for lower_y, upper_y in zip(ys, ys[1:]):
        for left_x, right_x in zip(xs, xs[1:]):
            shells.append(
                ShellElement(
                    len(beams) + len(shells) + 1,
                    (
                        node_id((left_x, lower_y, roof_z)),
                        node_id((right_x, lower_y, roof_z)),
                        node_id((right_x, upper_y, roof_z)),
                        node_id((left_x, upper_y, roof_z)),
                    ),
                    "steel_roof_deck",
                )
            )
    bindings = (
        PartBinding("steel_column", "structural_steel", "steel_column_section"),
        PartBinding("steel_beam", "structural_steel", "steel_beam_section"),
        PartBinding("steel_opening_jamb", "structural_steel", "steel_column_section"),
        PartBinding("steel_opening_header", "structural_steel", "steel_beam_section"),
        PartBinding("steel_roof_deck", "structural_steel", "steel_shell_section"),
    )
    mesh = MeshFragment(
        nodes=tuple(nodes),
        beams=tuple(beams),
        shells=tuple(shells),
        part_bindings=bindings,
    )
    connection = make_connection(
        "steel_frame_joints",
        "steel_connection",
        source_element_ids=(row.element_id for row in beams),
        metadata={
            "joint_model": "user_selectable",
            "opening_frame_profile": str(profile["profile_id"]),
        },
    )
    asset_id = normalized["asset_id"]
    assert isinstance(asset_id, str)
    return BuildingArtifact(
        asset_id=asset_id,
        system_id=descriptor.system_id,
        mesh=mesh,
        connections=(connection,),
        normalized_input=normalized,
        topology_manifest=topology.to_manifest(),
        dependency_manifest=(
            {
                "module": "refined_building.backends.steel",
                "version": "1.0.0",
                "material_roles": ["structural_steel"],
            },
        ),
        requires_project_review=True,
    )
