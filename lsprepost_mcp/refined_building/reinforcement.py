"""Parametric reinforcement generation for reinforced-concrete members."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

from .artifacts import BeamElement, MeshFragment, Node, PartBinding
from .meshing import merge_fragments
from .spatial import AxisAlignedBox


REINFORCEMENT_ROLES = frozenset(
    {
        "column_longitudinal",
        "column_stirrup",
        "beam_longitudinal",
        "beam_stirrup",
        "slab_rebar",
        "wall_rebar",
        "foundation_rebar",
    }
)

_MAX_REINFORCEMENT_POSITIONS = 1_000_000


def selected_reinforcement_roles(parameters: Mapping[str, object]) -> frozenset[str]:
    mode = parameters.get("generation_mode", "full_reinforced")
    if mode == "concrete_only":
        return frozenset()
    if mode == "full_reinforced":
        return REINFORCEMENT_ROLES
    if mode != "custom":
        raise ValueError(f"unsupported RC generation_mode: {mode!r}")
    selected = parameters.get("include_reinforcement_roles", [])
    if not isinstance(selected, list) or any(not isinstance(role, str) for role in selected):
        raise ValueError("include_reinforcement_roles must be a list of role ids")
    unknown = set(selected) - REINFORCEMENT_ROLES
    if unknown:
        raise ValueError(f"unknown reinforcement roles: {sorted(unknown)}")
    return frozenset(selected)


def generate_reinforcement(
    members: Iterable[tuple[str, AxisAlignedBox]],
    parameters: Mapping[str, object],
    included_roles: frozenset[str],
    excluded_boxes: Iterable[AxisAlignedBox] = (),
) -> MeshFragment | None:
    """Regenerate reinforcement from current member dimensions."""

    target_length = _optional_positive_parameter(parameters, "rebar_target_length_m")
    cover = _positive_parameter(parameters, "cover_m", 0.04)
    diameter = _positive_parameter(parameters, "bar_diameter_m", 0.016)
    spacing = _positive_parameter(parameters, "rebar_spacing_m", 0.3)
    if not included_roles:
        return None
    fragments: list[MeshFragment] = []
    for member_role, box in members:
        applicable = _roles_for_member(member_role) & included_roles
        if not applicable:
            continue
        dimensions = (
            box.max_x - box.min_x,
            box.max_y - box.min_y,
            box.max_z - box.min_z,
        )
        transverse = sorted(dimensions)[:2]
        if 2.0 * cover + diameter >= min(transverse):
            raise ValueError(
                f"cover/bar combination does not fit member {member_role!r}: "
                f"cover={cover}, diameter={diameter}"
            )
        if "column_longitudinal" in applicable:
            fragments.extend(
                _column_longitudinal(box, cover, "column_longitudinal")
            )
        if "column_stirrup" in applicable:
            fragments.extend(
                _column_stirrups(
                    box, cover, spacing, "column_stirrup"
                )
            )
        if "beam_longitudinal" in applicable:
            fragments.extend(
                _beam_longitudinal(box, cover, "beam_longitudinal")
            )
        if "beam_stirrup" in applicable:
            fragments.extend(
                _beam_stirrups(box, cover, spacing, "beam_stirrup")
            )
        if "slab_rebar" in applicable:
            fragments.extend(
                _horizontal_grid(box, cover, spacing, "slab_rebar")
            )
        if "foundation_rebar" in applicable:
            fragments.extend(
                _horizontal_grid(box, cover, spacing, "foundation_rebar")
            )
        if "wall_rebar" in applicable:
            fragments.extend(
                _wall_grid(box, cover, spacing, "wall_rebar")
            )
    if not fragments:
        return None
    merged = merge_fragments(fragments)
    exclusions = tuple(excluded_boxes)
    if not exclusions:
        return _subdivide_beams(merged, target_length) if target_length else merged
    nodes = {node.node_id: node for node in merged.nodes}
    kept_beams = tuple(
        beam
        for beam in merged.beams
        if not any(
            _segment_crosses_box_interior(
                nodes[beam.node_ids[0]].coordinates,
                nodes[beam.node_ids[1]].coordinates,
                box,
            )
            for box in exclusions
        )
    )
    if not kept_beams:
        return None
    used_node_ids = sorted(
        {node_id for beam in kept_beams for node_id in beam.node_ids}
    )
    node_id_map = {
        old_node_id: new_node_id
        for new_node_id, old_node_id in enumerate(used_node_ids, start=1)
    }
    kept_nodes = tuple(
        Node(node_id_map[old_node_id], *nodes[old_node_id].coordinates)
        for old_node_id in used_node_ids
    )
    remapped_beams = tuple(
        BeamElement(
            beam.element_id,
            tuple(node_id_map[node_id] for node_id in beam.node_ids),
            beam.part_role,
        )
        for beam in kept_beams
    )
    kept_roles = {beam.part_role for beam in kept_beams}
    filtered = MeshFragment(
        nodes=kept_nodes,
        beams=remapped_beams,
        part_bindings=tuple(
            binding for binding in merged.part_bindings if binding.part_role in kept_roles
        ),
    )
    return _subdivide_beams(filtered, target_length) if target_length else filtered


def estimate_reinforcement_size(
    members: Iterable[tuple[str, AxisAlignedBox]],
    parameters: Mapping[str, object],
    included_roles: frozenset[str],
) -> tuple[int, int]:
    """Return a proved upper bound for generated Beam and Node counts."""

    target = _optional_positive_parameter(parameters, "rebar_target_length_m")
    cover = _positive_parameter(parameters, "cover_m", 0.04)
    diameter = _positive_parameter(parameters, "bar_diameter_m", 0.016)
    spacing = _positive_parameter(parameters, "rebar_spacing_m", 0.3)
    beam_count = 0
    polyline_count = 0

    def add_lines(count: int, length: float) -> None:
        nonlocal beam_count, polyline_count
        beam_count += count * _segment_count(length, target)
        polyline_count += count

    def add_rectangle(first: float, second: float, count: int) -> None:
        nonlocal beam_count, polyline_count
        beam_count += count * (
            2 * _segment_count(first, target) + 2 * _segment_count(second, target)
        )
        polyline_count += count

    for member_role, box in members:
        applicable = _roles_for_member(member_role) & included_roles
        if not applicable:
            continue
        dx = box.max_x - box.min_x
        dy = box.max_y - box.min_y
        dz = box.max_z - box.min_z
        transverse = sorted((dx, dy, dz))[:2]
        if 2.0 * cover + diameter >= min(transverse):
            raise ValueError(
                f"cover/bar combination does not fit member {member_role!r}: "
                f"cover={cover}, diameter={diameter}"
            )
        usable_x = dx - 2.0 * cover
        usable_y = dy - 2.0 * cover
        usable_z = dz - 2.0 * cover
        if "column_longitudinal" in applicable:
            add_lines(4, usable_z)
        if "column_stirrup" in applicable:
            add_rectangle(usable_x, usable_y, _position_count(usable_z, spacing))
        if "beam_longitudinal" in applicable:
            length = usable_x if dx >= dy else usable_y
            add_lines(4, length)
        if "beam_stirrup" in applicable:
            along_x = dx >= dy
            count = _position_count(usable_x if along_x else usable_y, spacing)
            add_rectangle(usable_y if along_x else usable_x, usable_z, count)
        if "slab_rebar" in applicable or "foundation_rebar" in applicable:
            add_lines(_position_count(usable_y, spacing), usable_x)
            add_lines(_position_count(usable_x, spacing), usable_y)
        if "wall_rebar" in applicable:
            if dx <= dy:
                add_lines(_position_count(usable_y, spacing), usable_z)
                add_lines(_position_count(usable_z, spacing), usable_y)
            else:
                add_lines(_position_count(usable_x, spacing), usable_z)
                add_lines(_position_count(usable_z, spacing), usable_x)
    return beam_count, beam_count + polyline_count


def _segment_crosses_box_interior(
    start: Sequence[float],
    end: Sequence[float],
    box: AxisAlignedBox,
    tolerance: float = 1e-12,
) -> bool:
    """Return whether a finite segment has positive length inside a box interior."""

    if len(start) != 3 or len(end) != 3:
        raise ValueError("segment endpoints must contain exactly three coordinates")
    bounds = box.as_tuple()
    enter = 0.0
    leave = 1.0
    for axis in range(3):
        lower = bounds[axis] + tolerance
        upper = bounds[axis + 3] - tolerance
        if lower >= upper:
            return False
        start_value = float(start[axis])
        delta = float(end[axis]) - start_value
        if abs(delta) <= tolerance:
            if not lower < start_value < upper:
                return False
            continue
        first, second = sorted(
            ((lower - start_value) / delta, (upper - start_value) / delta)
        )
        enter = max(enter, first)
        leave = min(leave, second)
        if enter >= leave:
            return False
    return enter < leave


def _subdivide_beams(fragment: MeshFragment, target_length: float) -> MeshFragment:
    nodes = list(fragment.nodes)
    nodes_by_id = {node.node_id: node for node in nodes}
    beams: list[BeamElement] = []
    for source in fragment.beams:
        start_id, end_id = source.node_ids
        start = nodes_by_id[start_id].coordinates
        end = nodes_by_id[end_id].coordinates
        segment_count = max(1, math.ceil(math.dist(start, end) / target_length))
        if segment_count > _MAX_REINFORCEMENT_POSITIONS:
            raise ValueError(
                "reinforcement subdivision exceeds internal hard cap "
                f"{_MAX_REINFORCEMENT_POSITIONS}"
            )
        previous_id = start_id
        for segment_index in range(1, segment_count):
            node_id = len(nodes) + 1
            coordinate = tuple(
                start[axis]
                + (end[axis] - start[axis]) * segment_index / segment_count
                for axis in range(3)
            )
            node = Node(node_id, *coordinate)
            nodes.append(node)
            nodes_by_id[node_id] = node
            beams.append(
                BeamElement(len(beams) + 1, (previous_id, node_id), source.part_role)
            )
            previous_id = node_id
        beams.append(
            BeamElement(len(beams) + 1, (previous_id, end_id), source.part_role)
        )
    return MeshFragment(
        nodes=tuple(nodes),
        beams=tuple(beams),
        part_bindings=fragment.part_bindings,
    )


def _roles_for_member(member_role: str) -> frozenset[str]:
    if member_role == "rc_column":
        return frozenset({"column_longitudinal", "column_stirrup"})
    if member_role.startswith("rc_beam"):
        return frozenset({"beam_longitudinal", "beam_stirrup"})
    if member_role == "rc_slab":
        return frozenset({"slab_rebar"})
    if member_role == "rc_foundation":
        return frozenset({"foundation_rebar"})
    if member_role == "hybrid_foundation":
        return frozenset({"foundation_rebar"})
    if member_role == "hybrid_slab":
        return frozenset({"slab_rebar"})
    if member_role in {"rc_box_floor", "rc_box_roof"}:
        return frozenset({"slab_rebar"})
    if member_role == "rc_shear_wall" or member_role == "rc_box_wall":
        return frozenset({"wall_rebar"})
    return frozenset()


def _column_longitudinal(
    box: AxisAlignedBox,
    cover: float,
    role: str,
) -> list[MeshFragment]:
    xs = (box.min_x + cover, box.max_x - cover)
    ys = (box.min_y + cover, box.max_y - cover)
    return [
        _polyline(
            ((x, y, box.min_z + cover), (x, y, box.max_z - cover)),
            role,
        )
        for x in xs
        for y in ys
    ]


def _column_stirrups(
    box: AxisAlignedBox,
    cover: float,
    spacing: float,
    role: str,
) -> list[MeshFragment]:
    return [
        _closed_rectangle_xy(
            box.min_x + cover,
            box.min_y + cover,
            box.max_x - cover,
            box.max_y - cover,
            position,
            role,
        )
        for position in _positions(box.min_z + cover, box.max_z - cover, spacing)
    ]


def _beam_longitudinal(
    box: AxisAlignedBox,
    cover: float,
    role: str,
) -> list[MeshFragment]:
    along_x = (box.max_x - box.min_x) >= (box.max_y - box.min_y)
    zs = (box.min_z + cover, box.max_z - cover)
    if along_x:
        ys = (box.min_y + cover, box.max_y - cover)
        return [
            _polyline(
                ((box.min_x + cover, y, z), (box.max_x - cover, y, z)),
                role,
            )
            for y in ys
            for z in zs
        ]
    xs = (box.min_x + cover, box.max_x - cover)
    return [
        _polyline(
            ((x, box.min_y + cover, z), (x, box.max_y - cover, z)),
            role,
        )
        for x in xs
        for z in zs
    ]


def _beam_stirrups(
    box: AxisAlignedBox,
    cover: float,
    spacing: float,
    role: str,
) -> list[MeshFragment]:
    along_x = (box.max_x - box.min_x) >= (box.max_y - box.min_y)
    if along_x:
        return [
            _closed_rectangle_yz(
                box.min_y + cover,
                box.min_z + cover,
                box.max_y - cover,
                box.max_z - cover,
                position,
                role,
            )
            for position in _positions(box.min_x + cover, box.max_x - cover, spacing)
        ]
    return [
        _closed_rectangle_xz(
            box.min_x + cover,
            box.min_z + cover,
            box.max_x - cover,
            box.max_z - cover,
            position,
            role,
        )
        for position in _positions(box.min_y + cover, box.max_y - cover, spacing)
    ]


def _horizontal_grid(
    box: AxisAlignedBox,
    cover: float,
    spacing: float,
    role: str,
) -> list[MeshFragment]:
    z = (box.min_z + box.max_z) / 2.0
    fragments = [
        _polyline(
            ((box.min_x + cover, y, z), (box.max_x - cover, y, z)),
            role,
        )
        for y in _positions(box.min_y + cover, box.max_y - cover, spacing)
    ]
    fragments.extend(
        _polyline(
            ((x, box.min_y + cover, z), (x, box.max_y - cover, z)),
            role,
        )
        for x in _positions(box.min_x + cover, box.max_x - cover, spacing)
    )
    return fragments


def _wall_grid(
    box: AxisAlignedBox,
    cover: float,
    spacing: float,
    role: str,
) -> list[MeshFragment]:
    if (box.max_x - box.min_x) <= (box.max_y - box.min_y):
        x = (box.min_x + box.max_x) / 2.0
        fragments = [
            _polyline(
                ((x, y, box.min_z + cover), (x, y, box.max_z - cover)),
                role,
            )
            for y in _positions(box.min_y + cover, box.max_y - cover, spacing)
        ]
        fragments.extend(
            _polyline(
                ((x, box.min_y + cover, z), (x, box.max_y - cover, z)),
                role,
            )
            for z in _positions(box.min_z + cover, box.max_z - cover, spacing)
        )
        return fragments
    y = (box.min_y + box.max_y) / 2.0
    fragments = [
        _polyline(
            ((x, y, box.min_z + cover), (x, y, box.max_z - cover)),
            role,
        )
        for x in _positions(box.min_x + cover, box.max_x - cover, spacing)
    ]
    fragments.extend(
        _polyline(
            ((box.min_x + cover, y, z), (box.max_x - cover, y, z)),
            role,
        )
        for z in _positions(box.min_z + cover, box.max_z - cover, spacing)
    )
    return fragments


def _positions(start: float, end: float, target_spacing: float) -> tuple[float, ...]:
    if end <= start:
        raise ValueError("reinforcement direction has zero usable length")
    segments = max(1, math.ceil((end - start) / target_spacing))
    if segments + 1 > _MAX_REINFORCEMENT_POSITIONS:
        raise ValueError(
            "reinforcement positions exceed internal hard cap "
            f"{_MAX_REINFORCEMENT_POSITIONS}"
        )
    spacing = (end - start) / segments
    return tuple(start + spacing * index for index in range(segments)) + (end,)


def _position_count(length: float, target_spacing: float) -> int:
    if length <= 0.0:
        raise ValueError("reinforcement direction has zero usable length")
    return max(1, math.ceil(length / target_spacing)) + 1


def _segment_count(length: float, target_length: float | None) -> int:
    return 1 if target_length is None else max(1, math.ceil(length / target_length))


def _polyline(
    points: Sequence[tuple[float, float, float]],
    role: str,
) -> MeshFragment:
    nodes = tuple(Node(index + 1, *point) for index, point in enumerate(points))
    beams = tuple(BeamElement(index + 1, (index + 1, index + 2), role) for index in range(len(points) - 1))
    return MeshFragment(
        nodes=nodes,
        beams=beams,
        part_bindings=(PartBinding(role, "reinforcing_steel", f"{role}_beam_section"),),
    )


def _closed_rectangle_xy(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    z: float,
    role: str,
) -> MeshFragment:
    return _polyline(
        ((min_x, min_y, z), (max_x, min_y, z), (max_x, max_y, z), (min_x, max_y, z), (min_x, min_y, z)),
        role,
    )


def _closed_rectangle_yz(
    min_y: float,
    min_z: float,
    max_y: float,
    max_z: float,
    x: float,
    role: str,
) -> MeshFragment:
    return _polyline(
        ((x, min_y, min_z), (x, max_y, min_z), (x, max_y, max_z), (x, min_y, max_z), (x, min_y, min_z)),
        role,
    )


def _closed_rectangle_xz(
    min_x: float,
    min_z: float,
    max_x: float,
    max_z: float,
    y: float,
    role: str,
) -> MeshFragment:
    return _polyline(
        ((min_x, y, min_z), (max_x, y, min_z), (max_x, y, max_z), (min_x, y, max_z), (min_x, y, min_z)),
        role,
    )


def _positive_parameter(parameters: Mapping[str, object], key: str, default: float) -> float:
    raw = parameters.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{key} must be a positive finite number")
    result = float(raw)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{key} must be a positive finite number")
    return result


def _optional_positive_parameter(
    parameters: Mapping[str, object], key: str
) -> float | None:
    if key not in parameters:
        return None
    return _positive_parameter(parameters, key, 0.0)
