"""Deterministic low-level meshing utilities for Phase 18C."""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .artifacts import (
    BeamElement,
    MeshFragment,
    Node,
    PartBinding,
    ShellElement,
    SolidElement,
)
from .spatial import AxisAlignedBox


_MAX_AXIS_COORDINATE_CANDIDATES = 1_000_000
_MAX_AXIS_PLANE_INTERVALS = 10_000_000


def mesh_axis_aligned_block(
    bounds: AxisAlignedBox,
    target_size_m: float,
    part_role: str,
) -> MeshFragment:
    """Mesh an axis-aligned block with regular positive-orientation hex elements."""

    return mesh_axis_aligned_block_excluding(bounds, target_size_m, part_role, ())


def mesh_axis_aligned_block_excluding(
    bounds: AxisAlignedBox,
    target_size_m: float,
    part_role: str,
    excluded_boxes: Iterable[AxisAlignedBox],
) -> MeshFragment:
    """Mesh a block while conforming axes to and removing declared void boxes."""

    if isinstance(target_size_m, bool) or not isinstance(target_size_m, (int, float)):
        raise ValueError("target_size_m must be a positive finite number")
    target_size_m = float(target_size_m)
    if not math.isfinite(target_size_m) or target_size_m <= 0.0:
        raise ValueError("target_size_m must be a positive finite number")
    if not isinstance(part_role, str) or not part_role.strip():
        raise ValueError("part_role must be a non-empty string")
    part_role = part_role.strip()

    exclusions = tuple(box for box in excluded_boxes if bounds.intersects(box))
    x_values = _axis_coordinates_with_boundaries(
        bounds.min_x,
        bounds.max_x,
        target_size_m,
        (coordinate for box in exclusions for coordinate in (box.min_x, box.max_x)),
    )
    y_values = _axis_coordinates_with_boundaries(
        bounds.min_y,
        bounds.max_y,
        target_size_m,
        (coordinate for box in exclusions for coordinate in (box.min_y, box.max_y)),
    )
    z_values = _axis_coordinates_with_boundaries(
        bounds.min_z,
        bounds.max_z,
        target_size_m,
        (coordinate for box in exclusions for coordinate in (box.min_z, box.max_z)),
    )
    nx, ny, nz = len(x_values), len(y_values), len(z_values)

    def node_id(ix: int, iy: int, iz: int) -> int:
        return iz * nx * ny + iy * nx + ix + 1

    nodes = tuple(
        Node(node_id(ix, iy, iz), x, y, z)
        for iz, z in enumerate(z_values)
        for iy, y in enumerate(y_values)
        for ix, x in enumerate(x_values)
    )
    solids: list[SolidElement] = []
    element_id = 1
    for iz in range(nz - 1):
        for iy in range(ny - 1):
            for ix in range(nx - 1):
                centroid = (
                    (x_values[ix] + x_values[ix + 1]) / 2.0,
                    (y_values[iy] + y_values[iy + 1]) / 2.0,
                    (z_values[iz] + z_values[iz + 1]) / 2.0,
                )
                if any(box.contains_point(centroid) for box in exclusions):
                    continue
                connectivity = (
                    node_id(ix, iy, iz),
                    node_id(ix + 1, iy, iz),
                    node_id(ix + 1, iy + 1, iz),
                    node_id(ix, iy + 1, iz),
                    node_id(ix, iy, iz + 1),
                    node_id(ix + 1, iy, iz + 1),
                    node_id(ix + 1, iy + 1, iz + 1),
                    node_id(ix, iy + 1, iz + 1),
                )
                solids.append(SolidElement(element_id, connectivity, part_role))
                element_id += 1
    return MeshFragment(
        nodes=nodes,
        solids=tuple(solids),
        part_bindings=(
            PartBinding(part_role, f"{part_role}_material", f"{part_role}_solid_section"),
        ),
    )


def mesh_axis_aligned_union(
    members: Iterable[tuple[str, AxisAlignedBox]],
    target_size_m: float,
    excluded_boxes: Iterable[AxisAlignedBox] = (),
    role_priority: Mapping[str, int] | None = None,
    required_coordinates: Iterable[tuple[float, float, float]] = (),
) -> MeshFragment:
    """Mesh the geometric union of axis-aligned members with shared nodes.

    Every member boundary and relevant exclusion boundary is inserted into the
    global axes, so cell occupancy and role ownership are constant inside each
    emitted hexahedron.  Overlap volume is emitted once.
    """

    prepared = _prepare_axis_aligned_union(
        members,
        target_size_m,
        excluded_boxes,
        role_priority,
        required_coordinates,
    )
    x_values, y_values, z_values = prepared.axes

    coordinate_to_id: dict[tuple[float, float, float], int] = {}
    nodes: list[Node] = []
    solids: list[SolidElement] = []
    used_roles: set[str] = set()

    def allocate_node(coordinate: tuple[float, float, float]) -> int:
        existing = coordinate_to_id.get(coordinate)
        if existing is not None:
            return existing
        node_id = len(nodes) + 1
        coordinate_to_id[coordinate] = node_id
        nodes.append(Node(node_id, *coordinate))
        return node_id

    for iz in range(len(z_values) - 1):
        for iy in range(len(y_values) - 1):
            for ix in range(len(x_values) - 1):
                cell = (ix, iy, iz)
                owners = prepared.owners_by_cell.get(cell)
                if not owners or cell in prepared.excluded_cells:
                    continue
                role = max(
                    owners,
                    key=lambda candidate: (
                        prepared.priorities.get(candidate, 0),
                        candidate,
                    ),
                )
                corners = (
                    (x_values[ix], y_values[iy], z_values[iz]),
                    (x_values[ix + 1], y_values[iy], z_values[iz]),
                    (x_values[ix + 1], y_values[iy + 1], z_values[iz]),
                    (x_values[ix], y_values[iy + 1], z_values[iz]),
                    (x_values[ix], y_values[iy], z_values[iz + 1]),
                    (x_values[ix + 1], y_values[iy], z_values[iz + 1]),
                    (x_values[ix + 1], y_values[iy + 1], z_values[iz + 1]),
                    (x_values[ix], y_values[iy + 1], z_values[iz + 1]),
                )
                connectivity = tuple(allocate_node(coordinate) for coordinate in corners)
                solids.append(SolidElement(len(solids) + 1, connectivity, role))
                used_roles.add(role)

    if not solids:
        raise ValueError("union members produce no solid cells after exclusions")
    return MeshFragment(
        nodes=tuple(nodes),
        solids=tuple(solids),
        part_bindings=tuple(
            PartBinding(role, f"{role}_material", f"{role}_solid_section")
            for role in sorted(used_roles)
        ),
    )


def count_axis_aligned_union_cells(
    members: Iterable[tuple[str, AxisAlignedBox]],
    target_size_m: float,
    excluded_boxes: Iterable[AxisAlignedBox] = (),
    role_priority: Mapping[str, int] | None = None,
    required_coordinates: Iterable[tuple[float, float, float]] = (),
    *,
    max_cells: int | None = None,
) -> int:
    """Return the exact Solid count emitted by :func:`mesh_axis_aligned_union`.

    The counter intentionally shares axis construction, sparse occupancy, and
    exclusion preparation with the mesher.  It allocates no nodes or elements
    and therefore provides a fail-closed preflight without a Cartesian upper
    bound that could reject a sparse building unnecessarily.
    """

    if (
        max_cells is not None
        and (isinstance(max_cells, bool) or not isinstance(max_cells, int) or max_cells <= 0)
    ):
        raise ValueError("max_cells must be a positive integer")
    if isinstance(target_size_m, bool) or not isinstance(target_size_m, (int, float)):
        raise ValueError("target_size_m must be a positive finite number")
    target_size_m = float(target_size_m)
    if not math.isfinite(target_size_m) or target_size_m <= 0.0:
        raise ValueError("target_size_m must be a positive finite number")
    source = tuple(members)
    exclusions = tuple(excluded_boxes)
    if max_cells is not None and not exclusions:
        for _, box in source:
            bounds = box.as_tuple()
            member_cells = math.prod(
                max(1, math.ceil((bounds[axis + 3] - bounds[axis]) / target_size_m))
                for axis in range(3)
            )
            if member_cells > max_cells:
                return max_cells + 1
    geometry = _prepare_axis_aligned_union_geometry(
        source,
        target_size_m,
        exclusions,
        role_priority,
        required_coordinates,
    )
    if (len(geometry.axes[1]) - 1) * (len(geometry.axes[2]) - 1) > _MAX_AXIS_PLANE_INTERVALS:
        raise ValueError(
            "axis plane traversal exceeds internal hard cap "
            f"{_MAX_AXIS_PLANE_INTERVALS}"
        )
    centroids_by_axis = tuple(
        tuple((left + right) / 2.0 for left, right in zip(values, values[1:]))
        for values in geometry.axes
    )
    member_ranges = tuple(
        _box_cell_ranges(box, centroids_by_axis)
        for _, box in geometry.members
    )
    exclusion_ranges = tuple(
        _box_cell_ranges(box, centroids_by_axis)
        for box in geometry.exclusions
    )
    count = 0
    for iz in range(len(centroids_by_axis[2])):
        active_members = tuple(
            ranges for ranges in member_ranges if ranges[2].start <= iz < ranges[2].stop
        )
        if not active_members:
            continue
        active_exclusions = tuple(
            ranges
            for ranges in exclusion_ranges
            if ranges[2].start <= iz < ranges[2].stop
        )
        for iy in range(len(centroids_by_axis[1])):
            occupied = _merge_cell_intervals(
                (ranges[0].start, ranges[0].stop)
                for ranges in active_members
                if ranges[1].start <= iy < ranges[1].stop
            )
            if not occupied:
                continue
            excluded = _merge_cell_intervals(
                (ranges[0].start, ranges[0].stop)
                for ranges in active_exclusions
                if ranges[1].start <= iy < ranges[1].stop
            )
            count += _interval_difference_length(occupied, excluded)
            if max_cells is not None and count > max_cells:
                return max_cells + 1
    if count == 0:
        raise ValueError("union members produce no solid cells after exclusions")
    return count


def count_axis_aligned_union_nodes(
    members: Iterable[tuple[str, AxisAlignedBox]],
    target_size_m: float,
    excluded_boxes: Iterable[AxisAlignedBox] = (),
    role_priority: Mapping[str, int] | None = None,
    required_coordinates: Iterable[tuple[float, float, float]] = (),
    *,
    max_nodes: int | None = None,
) -> int:
    """Count the nodes used by the sparse union without allocating FE entities."""

    if (
        max_nodes is not None
        and (isinstance(max_nodes, bool) or not isinstance(max_nodes, int) or max_nodes <= 0)
    ):
        raise ValueError("max_nodes must be a positive integer")
    geometry = _prepare_axis_aligned_union_geometry(
        members,
        target_size_m,
        excluded_boxes,
        role_priority,
        required_coordinates,
    )
    if len(geometry.axes[1]) * len(geometry.axes[2]) > _MAX_AXIS_PLANE_INTERVALS:
        raise ValueError(
            "axis plane traversal exceeds internal hard cap "
            f"{_MAX_AXIS_PLANE_INTERVALS}"
        )
    centroids = tuple(
        tuple((left + right) / 2.0 for left, right in zip(values, values[1:]))
        for values in geometry.axes
    )
    member_ranges = tuple(
        _box_cell_ranges(box, centroids) for _, box in geometry.members
    )
    exclusion_ranges = tuple(
        _box_cell_ranges(box, centroids) for box in geometry.exclusions
    )
    count = 0
    for node_z in range(len(geometry.axes[2])):
        adjacent_z = tuple(
            index
            for index in (node_z - 1, node_z)
            if 0 <= index < len(centroids[2])
        )
        for node_y in range(len(geometry.axes[1])):
            adjacent_y = tuple(
                index
                for index in (node_y - 1, node_y)
                if 0 <= index < len(centroids[1])
            )
            node_intervals: list[tuple[int, int]] = []
            for cell_z in adjacent_z:
                for cell_y in adjacent_y:
                    occupied = _occupied_x_intervals(
                        member_ranges,
                        exclusion_ranges,
                        cell_y,
                        cell_z,
                    )
                    node_intervals.extend((start, stop + 1) for start, stop in occupied)
            count += sum(stop - start for start, stop in _merge_cell_intervals(node_intervals))
            if max_nodes is not None and count > max_nodes:
                return max_nodes + 1
    if count == 0:
        raise ValueError("union members produce no nodes after exclusions")
    return count


@dataclass(frozen=True, slots=True)
class _PreparedAxisAlignedUnion:
    axes: tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]
    owners_by_cell: Mapping[tuple[int, int, int], tuple[str, ...]]
    excluded_cells: frozenset[tuple[int, int, int]]
    priorities: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class _AxisAlignedUnionGeometry:
    axes: tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]
    members: tuple[tuple[str, AxisAlignedBox], ...]
    exclusions: tuple[AxisAlignedBox, ...]
    priorities: Mapping[str, int]


def _prepare_axis_aligned_union(
    members: Iterable[tuple[str, AxisAlignedBox]],
    target_size_m: float,
    excluded_boxes: Iterable[AxisAlignedBox] = (),
    role_priority: Mapping[str, int] | None = None,
    required_coordinates: Iterable[tuple[float, float, float]] = (),
) -> _PreparedAxisAlignedUnion:
    """Prepare the literal sparse union shared by counting and meshing."""

    geometry = _prepare_axis_aligned_union_geometry(
        members,
        target_size_m,
        excluded_boxes,
        role_priority,
        required_coordinates,
    )
    exact_axes = geometry.axes
    normalized = geometry.members
    exclusions = geometry.exclusions
    priorities = geometry.priorities

    centroids_by_axis = tuple(
        tuple((left + right) / 2.0 for left, right in zip(values, values[1:]))
        for values in exact_axes
    )
    owners_by_cell: dict[tuple[int, int, int], list[str]] = {}
    for role, box in normalized:
        ranges = _box_cell_ranges(box, centroids_by_axis)
        for ix in ranges[0]:
            for iy in ranges[1]:
                for iz in ranges[2]:
                    owners_by_cell.setdefault((ix, iy, iz), []).append(role)

    excluded_cells: set[tuple[int, int, int]] = set()
    for box in exclusions:
        ranges = _box_cell_ranges(box, centroids_by_axis)
        excluded_cells.update(
            (ix, iy, iz)
            for ix in ranges[0]
            for iy in ranges[1]
            for iz in ranges[2]
        )
    return _PreparedAxisAlignedUnion(
        axes=exact_axes,
        owners_by_cell={
            cell: tuple(owners) for cell, owners in owners_by_cell.items()
        },
        excluded_cells=frozenset(excluded_cells),
        priorities=priorities,
    )


def _prepare_axis_aligned_union_geometry(
    members: Iterable[tuple[str, AxisAlignedBox]],
    target_size_m: float,
    excluded_boxes: Iterable[AxisAlignedBox] = (),
    role_priority: Mapping[str, int] | None = None,
    required_coordinates: Iterable[tuple[float, float, float]] = (),
) -> _AxisAlignedUnionGeometry:
    """Validate a union and construct only its compressed coordinate axes."""

    if isinstance(target_size_m, bool) or not isinstance(target_size_m, (int, float)):
        raise ValueError("target_size_m must be a positive finite number")
    target_size_m = float(target_size_m)
    if not math.isfinite(target_size_m) or target_size_m <= 0.0:
        raise ValueError("target_size_m must be a positive finite number")

    source = tuple(members)
    if not source:
        raise ValueError("at least one union member is required")
    normalized: list[tuple[str, AxisAlignedBox]] = []
    for role, box in source:
        if not isinstance(role, str) or not role.strip():
            raise ValueError("union member role must be a non-empty string")
        if not isinstance(box, AxisAlignedBox):
            raise TypeError("union member bounds must be an AxisAlignedBox")
        normalized.append((role.strip(), box))

    priorities = dict(role_priority or {})
    required_rows: list[tuple[float, ...]] = []
    for point in required_coordinates:
        if len(required_rows) >= _MAX_AXIS_COORDINATE_CANDIDATES:
            raise ValueError(
                "required coordinate allocation exceeds internal hard cap "
                f"{_MAX_AXIS_COORDINATE_CANDIDATES}"
            )
        required_rows.append(tuple(float(value) for value in point))
    required = tuple(required_rows)
    if any(len(point) != 3 or not all(math.isfinite(value) for value in point) for point in required):
        raise ValueError("required_coordinates must contain finite x/y/z triples")
    exclusions = tuple(
        exclusion
        for exclusion in excluded_boxes
        if any(member_box.intersects(exclusion) for _, member_box in normalized)
    )
    overall = AxisAlignedBox(
        min(box.min_x for _, box in normalized),
        min(box.min_y for _, box in normalized),
        min(box.min_z for _, box in normalized),
        max(box.max_x for _, box in normalized),
        max(box.max_y for _, box in normalized),
        max(box.max_z for _, box in normalized),
    )

    candidate_count = len(required) * 3 + len(exclusions) * 6
    for _, box in normalized:
        bounds = box.as_tuple()
        candidate_count += sum(
            _axis_coordinate_count(bounds[axis], bounds[axis + 3], target_size_m)
            for axis in range(3)
        )
        if candidate_count > _MAX_AXIS_COORDINATE_CANDIDATES:
            raise ValueError(
                "axis coordinate allocation exceeds internal hard cap "
                f"{_MAX_AXIS_COORDINATE_CANDIDATES}"
            )

    axes: list[tuple[float, ...]] = []
    for axis, (overall_min, overall_max) in enumerate(
        (
            (overall.min_x, overall.max_x),
            (overall.min_y, overall.max_y),
            (overall.min_z, overall.max_z),
        )
    ):
        values: set[float] = set()
        for _, box in normalized:
            box_min = box.as_tuple()[axis]
            box_max = box.as_tuple()[axis + 3]
            values.update(_axis_coordinates(box_min, box_max, target_size_m))
        for exclusion in exclusions:
            exclusion_values = exclusion.as_tuple()
            values.add(max(overall_min, min(overall_max, exclusion_values[axis])))
            values.add(max(overall_min, min(overall_max, exclusion_values[axis + 3])))
        values.update(
            point[axis]
            for point in required
            if overall_min <= point[axis] <= overall_max
        )
        axes.append(_merge_close_coordinates(values))
    exact_axes = (axes[0], axes[1], axes[2])

    return _AxisAlignedUnionGeometry(
        axes=exact_axes,
        members=tuple(normalized),
        exclusions=exclusions,
        priorities=priorities,
    )


def merge_fragments(fragments: Iterable[MeshFragment]) -> MeshFragment:
    """Merge fragments in input order with deterministic collision-free remapping."""

    source = tuple(fragments)
    if not source:
        raise ValueError("at least one mesh fragment is required")
    nodes: list[Node] = []
    solids: list[SolidElement] = []
    shells: list[ShellElement] = []
    beams: list[BeamElement] = []
    binding_by_role: dict[str, PartBinding] = {}
    next_node_id = 1
    next_element_id = 1
    for fragment in source:
        node_map: dict[int, int] = {}
        for node in fragment.nodes:
            node_map[node.node_id] = next_node_id
            nodes.append(Node(next_node_id, node.x, node.y, node.z))
            next_node_id += 1
        ordered_elements = sorted(
            (*fragment.solids, *fragment.shells, *fragment.beams),
            key=lambda element: element.element_id,
        )
        for element in ordered_elements:
            remapped = tuple(node_map[node_id] for node_id in element.node_ids)
            if isinstance(element, SolidElement):
                solids.append(
                    SolidElement(next_element_id, remapped, element.part_role)  # type: ignore[arg-type]
                )
            elif isinstance(element, ShellElement):
                shells.append(
                    ShellElement(next_element_id, remapped, element.part_role)  # type: ignore[arg-type]
                )
            else:
                beams.append(
                    BeamElement(next_element_id, remapped, element.part_role)  # type: ignore[arg-type]
                )
            next_element_id += 1
        for binding in fragment.part_bindings:
            previous = binding_by_role.get(binding.part_role)
            if previous is not None and previous != binding:
                raise ValueError(f"conflicting part binding for role {binding.part_role!r}")
            binding_by_role[binding.part_role] = binding
    return MeshFragment(
        nodes=tuple(nodes),
        solids=tuple(solids),
        shells=tuple(shells),
        beams=tuple(beams),
        part_bindings=tuple(binding_by_role[key] for key in sorted(binding_by_role)),
    )


def merge_fragments_welded(fragments: Iterable[MeshFragment]) -> MeshFragment:
    """Merge fragments while welding nodes with identical coordinates.

    This is intentionally opt-in: ordinary package composition preserves the
    source fragments verbatim, while structural additions that meet an
    existing RC mesh need shared node ids to remain one connected component.
    """

    source = tuple(fragments)
    if not source:
        raise ValueError("at least one mesh fragment is required")
    nodes: list[Node] = []
    solids: list[SolidElement] = []
    shells: list[ShellElement] = []
    beams: list[BeamElement] = []
    binding_by_role: dict[str, PartBinding] = {}
    coordinate_to_id: dict[tuple[float, float, float], int] = {}
    next_element_id = 1
    for fragment in source:
        node_map: dict[int, int] = {}
        for node in fragment.nodes:
            coordinate = node.coordinates
            coordinate_key = tuple(round(value, 12) for value in coordinate)
            node_id = coordinate_to_id.get(coordinate_key)
            if node_id is None:
                node_id = len(nodes) + 1
                coordinate_to_id[coordinate_key] = node_id
                nodes.append(Node(node_id, *coordinate))
            node_map[node.node_id] = node_id
        for element in sorted(
            (*fragment.solids, *fragment.shells, *fragment.beams),
            key=lambda row: row.element_id,
        ):
            remapped = tuple(node_map[node_id] for node_id in element.node_ids)
            if isinstance(element, SolidElement):
                solids.append(SolidElement(next_element_id, remapped, element.part_role))  # type: ignore[arg-type]
            elif isinstance(element, ShellElement):
                shells.append(ShellElement(next_element_id, remapped, element.part_role))  # type: ignore[arg-type]
            else:
                beams.append(BeamElement(next_element_id, remapped, element.part_role))  # type: ignore[arg-type]
            next_element_id += 1
        for binding in fragment.part_bindings:
            previous = binding_by_role.get(binding.part_role)
            if previous is not None and previous != binding:
                raise ValueError(f"conflicting part binding for role {binding.part_role!r}")
            binding_by_role[binding.part_role] = binding
    return MeshFragment(
        nodes=tuple(nodes),
        solids=tuple(solids),
        shells=tuple(shells),
        beams=tuple(beams),
        part_bindings=tuple(binding_by_role[key] for key in sorted(binding_by_role)),
    )


def _axis_coordinates(start: float, end: float, target_size_m: float) -> tuple[float, ...]:
    segment_count = max(1, math.ceil((end - start) / target_size_m))
    if segment_count + 1 > _MAX_AXIS_COORDINATE_CANDIDATES:
        raise ValueError(
            "axis coordinate allocation exceeds internal hard cap "
            f"{_MAX_AXIS_COORDINATE_CANDIDATES}"
        )
    spacing = (end - start) / segment_count
    return tuple(start + spacing * index for index in range(segment_count)) + (end,)


def _axis_coordinate_count(start: float, end: float, target_size_m: float) -> int:
    return max(1, math.ceil((end - start) / target_size_m)) + 1


def _axis_coordinates_with_boundaries(
    start: float,
    end: float,
    target_size_m: float,
    boundaries: Iterable[float],
) -> tuple[float, ...]:
    values = set(_axis_coordinates(start, end, target_size_m))
    values.update(max(start, min(end, float(value))) for value in boundaries)
    return _merge_close_coordinates(values)


def _merge_close_coordinates(values: Iterable[float], tolerance: float = 1e-12) -> tuple[float, ...]:
    """Collapse round-off variants of the same geometric axis coordinate."""

    merged: list[float] = []
    for value in sorted(float(candidate) for candidate in values):
        if merged and value - merged[-1] <= tolerance:
            merged[-1] = value
        else:
            merged.append(value)
    return tuple(merged)


def _centroid_cell_range(
    centroids: tuple[float, ...], lower: float, upper: float
) -> range:
    """Return indices of sorted cell centroids inside inclusive bounds."""

    return range(
        bisect_left(centroids, lower),
        bisect_right(centroids, upper),
    )


def _box_cell_ranges(
    box: AxisAlignedBox,
    centroids_by_axis: tuple[tuple[float, ...], ...],
) -> tuple[range, range, range]:
    bounds = box.as_tuple()
    return tuple(
        _centroid_cell_range(
            centroids_by_axis[axis], bounds[axis], bounds[axis + 3]
        )
        for axis in range(3)
    )  # type: ignore[return-value]


def _merge_cell_intervals(
    intervals: Iterable[tuple[int, int]],
) -> tuple[tuple[int, int], ...]:
    merged: list[tuple[int, int]] = []
    for start, stop in sorted(intervals):
        if stop <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], stop))
        else:
            merged.append((start, stop))
    return tuple(merged)


def _interval_difference_length(
    occupied: tuple[tuple[int, int], ...],
    excluded: tuple[tuple[int, int], ...],
) -> int:
    total = sum(stop - start for start, stop in occupied)
    if not excluded:
        return total
    overlap = 0
    excluded_index = 0
    for occupied_start, occupied_stop in occupied:
        while (
            excluded_index < len(excluded)
            and excluded[excluded_index][1] <= occupied_start
        ):
            excluded_index += 1
        scan = excluded_index
        while scan < len(excluded) and excluded[scan][0] < occupied_stop:
            excluded_start, excluded_stop = excluded[scan]
            overlap += max(
                0,
                min(occupied_stop, excluded_stop)
                - max(occupied_start, excluded_start),
            )
            scan += 1
    return total - overlap


def _occupied_x_intervals(
    member_ranges: tuple[tuple[range, range, range], ...],
    exclusion_ranges: tuple[tuple[range, range, range], ...],
    cell_y: int,
    cell_z: int,
) -> tuple[tuple[int, int], ...]:
    occupied = _merge_cell_intervals(
        (ranges[0].start, ranges[0].stop)
        for ranges in member_ranges
        if ranges[1].start <= cell_y < ranges[1].stop
        and ranges[2].start <= cell_z < ranges[2].stop
    )
    if not occupied:
        return ()
    excluded = _merge_cell_intervals(
        (ranges[0].start, ranges[0].stop)
        for ranges in exclusion_ranges
        if ranges[1].start <= cell_y < ranges[1].stop
        and ranges[2].start <= cell_z < ranges[2].stop
    )
    if not excluded:
        return occupied
    result: list[tuple[int, int]] = []
    for start, stop in occupied:
        cursor = start
        for excluded_start, excluded_stop in excluded:
            if excluded_stop <= cursor:
                continue
            if excluded_start >= stop:
                break
            if excluded_start > cursor:
                result.append((cursor, min(stop, excluded_start)))
            cursor = max(cursor, excluded_stop)
            if cursor >= stop:
                break
        if cursor < stop:
            result.append((cursor, stop))
    return tuple(result)
