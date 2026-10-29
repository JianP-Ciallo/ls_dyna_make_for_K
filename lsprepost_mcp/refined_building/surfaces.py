"""Fluid-exposed surface catalog for later independent blast scenarios."""

from __future__ import annotations

import math
from collections import Counter

from .artifacts import BuildingArtifact, Node
from .contracts import JSONDict
from .spatial import AxisAlignedBox, SpatialTopology


_HEX_FACES = (
    (0, 1, 2, 3),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (1, 2, 6, 5),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
)
_TOLERANCE = 1.0e-9


def build_fluid_exposed_surface_catalog(
    artifact: BuildingArtifact,
    topology: SpatialTopology,
) -> JSONDict:
    """Classify unique Solid boundary faces and structural Shell surfaces."""

    node_by_id = {node.node_id: node for node in artifact.mesh.nodes}
    candidates: list[tuple[tuple[tuple[float, float, float], ...], dict[str, object]]] = []
    for solid in artifact.mesh.solids:
        for local_index, local_face in enumerate(_HEX_FACES):
            nodes = tuple(node_by_id[solid.node_ids[index]] for index in local_face)
            key = tuple(sorted(_coordinate_key(node) for node in nodes))
            centroid = tuple(sum(node.coordinates[axis] for node in nodes) / 4.0 for axis in range(3))
            candidates.append(
                (
                    key,
                    {
                        "face_id": f"solid:{solid.element_id}:face:{local_index}",
                        "element_id": solid.element_id,
                        "node_ids": list(node.node_id for node in nodes),
                        "part_role": solid.part_role,
                        "centroid_m": list(centroid),
                        "normal": list(_normal(nodes)),
                    },
                )
            )
    counts = Counter(key for key, _ in candidates)
    solid_boundary_faces = [row for key, row in candidates if counts[key] == 1]
    coincidence_index = _build_solid_face_candidate_index(
        solid_boundary_faces,
        node_by_id,
    )
    boundary_faces = list(solid_boundary_faces)
    for shell in artifact.mesh.shells:
        nodes = tuple(node_by_id[node_id] for node_id in shell.node_ids)
        shell_key = tuple(sorted(_coordinate_key(node) for node in nodes))
        coincidence_candidates = _solid_face_candidates_for_shell(
            nodes,
            solid_boundary_faces,
            coincidence_index,
        )
        if shell_key in counts or _shell_coincident_with_solid_boundary(
            nodes, coincidence_candidates, node_by_id
        ):
            continue
        centroid = tuple(
            sum(node.coordinates[axis] for node in nodes) / len(nodes)
            for axis in range(3)
        )
        boundary_faces.append(
            {
                "face_id": f"shell:{shell.element_id}",
                "element_id": shell.element_id,
                "node_ids": list(shell.node_ids),
                "part_role": shell.part_role,
                "centroid_m": list(centroid),
                "normal": list(_normal(nodes)),
            }
        )

    exterior: list[dict[str, object]] = []
    interior: list[dict[str, object]] = []
    ground: list[dict[str, object]] = []
    remaining: list[dict[str, object]] = []
    for row in boundary_faces:
        node_ids = row["node_ids"]
        assert isinstance(node_ids, list)
        nodes = tuple(node_by_id[int(node_id)] for node_id in node_ids)
        if _face_on_plane(nodes, 2, topology.envelope.min_z):
            ground.append(row)
        elif _face_on_envelope(nodes, topology.envelope):
            exterior.append(row)
        elif any(_face_on_box_boundary(nodes, box) for _, box in topology.void_regions):
            interior.append(row)
        else:
            remaining.append(row)

    opening_boundaries: list[dict[str, object]] = [
        {
            "face_id": f"opening:{opening_id}",
            "opening_id": opening_id,
            "bounds_m": list(box.as_tuple()),
            "centroid_m": [
                (box.min_x + box.max_x) / 2.0,
                (box.min_y + box.max_y) / 2.0,
                (box.min_z + box.max_z) / 2.0,
            ],
        }
        for opening_id, box in topology.opening_regions
    ]
    for rows in (exterior, interior, ground, remaining, opening_boundaries):
        rows.sort(key=lambda row: str(row["face_id"]))
    user_selectable = sorted(
        (*exterior, *interior, *ground, *remaining, *opening_boundaries),
        key=lambda row: str(row["face_id"]),
    )
    return {
        "schema_version": "1.0.0",
        "exterior_surfaces": exterior,
        "interior_cavity_surfaces": interior,
        "opening_boundaries": opening_boundaries,
        "ground_contact_surfaces": ground,
        "unclassified_boundary_surfaces": remaining,
        "user_selectable_surfaces": user_selectable,
    }


def _coordinate_key(node: Node) -> tuple[float, float, float]:
    return tuple(round(value, 12) for value in node.coordinates)  # type: ignore[return-value]


def _normal(nodes: tuple[Node, Node, Node, Node]) -> tuple[float, float, float]:
    first = tuple(nodes[1].coordinates[index] - nodes[0].coordinates[index] for index in range(3))
    second = tuple(nodes[2].coordinates[index] - nodes[0].coordinates[index] for index in range(3))
    cross = (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )
    magnitude = math.sqrt(sum(value * value for value in cross))
    if magnitude <= _TOLERANCE:
        raise ValueError("degenerate structural face")
    return tuple(value / magnitude for value in cross)  # type: ignore[return-value]


def _face_on_plane(nodes: tuple[Node, ...], axis: int, coordinate: float) -> bool:
    return all(abs(node.coordinates[axis] - coordinate) <= _TOLERANCE for node in nodes)


def _face_on_envelope(nodes: tuple[Node, ...], envelope: AxisAlignedBox) -> bool:
    planes = (
        (0, envelope.min_x),
        (0, envelope.max_x),
        (1, envelope.min_y),
        (1, envelope.max_y),
        (2, envelope.min_z),
        (2, envelope.max_z),
    )
    return any(_face_on_plane(nodes, axis, coordinate) for axis, coordinate in planes)


def _face_on_box_boundary(nodes: tuple[Node, ...], box: AxisAlignedBox) -> bool:
    centroid = tuple(sum(node.coordinates[axis] for node in nodes) / len(nodes) for axis in range(3))
    limits = (
        (0, box.min_x, (box.min_y, box.max_y), (box.min_z, box.max_z)),
        (0, box.max_x, (box.min_y, box.max_y), (box.min_z, box.max_z)),
        (1, box.min_y, (box.min_x, box.max_x), (box.min_z, box.max_z)),
        (1, box.max_y, (box.min_x, box.max_x), (box.min_z, box.max_z)),
        (2, box.min_z, (box.min_x, box.max_x), (box.min_y, box.max_y)),
        (2, box.max_z, (box.min_x, box.max_x), (box.min_y, box.max_y)),
    )
    for axis, coordinate, first_range, second_range in limits:
        remaining = [index for index in range(3) if index != axis]
        if (
            _face_on_plane(nodes, axis, coordinate)
            and first_range[0] - _TOLERANCE <= centroid[remaining[0]] <= first_range[1] + _TOLERANCE
            and second_range[0] - _TOLERANCE <= centroid[remaining[1]] <= second_range[1] + _TOLERANCE
        ):
            return True
    return False


def _shell_coincident_with_solid_boundary(
    shell_nodes: tuple[Node, ...],
    solid_faces: list[dict[str, object]],
    node_by_id: dict[int, Node],
) -> bool:
    fixed_axis = next(
        (
            axis
            for axis in range(3)
            if _face_on_plane(shell_nodes, axis, shell_nodes[0].coordinates[axis])
        ),
        None,
    )
    if fixed_axis is None:
        return False
    coordinate = shell_nodes[0].coordinates[fixed_axis]
    projected_axes = tuple(axis for axis in range(3) if axis != fixed_axis)
    shell_rectangle = tuple(
        value
        for axis in projected_axes
        for value in (
            min(node.coordinates[axis] for node in shell_nodes),
            max(node.coordinates[axis] for node in shell_nodes),
        )
    )
    shell_min_first, shell_max_first, shell_min_second, shell_max_second = shell_rectangle
    if not _projected_nodes_form_rectangle(
        shell_nodes, projected_axes, shell_rectangle
    ):
        return False
    clipped_rectangles: list[tuple[float, float, float, float]] = []
    for row in solid_faces:
        raw_node_ids = row["node_ids"]
        assert isinstance(raw_node_ids, list)
        face_nodes = tuple(node_by_id[int(node_id)] for node_id in raw_node_ids)
        if not _face_on_plane(face_nodes, fixed_axis, coordinate):
            continue
        face_min_first = min(node.coordinates[projected_axes[0]] for node in face_nodes)
        face_max_first = max(node.coordinates[projected_axes[0]] for node in face_nodes)
        face_min_second = min(node.coordinates[projected_axes[1]] for node in face_nodes)
        face_max_second = max(node.coordinates[projected_axes[1]] for node in face_nodes)
        face_rectangle = (
            face_min_first,
            face_max_first,
            face_min_second,
            face_max_second,
        )
        if not _projected_nodes_form_rectangle(
            face_nodes, projected_axes, face_rectangle
        ):
            continue
        clipped = (
            max(shell_min_first, face_min_first),
            min(shell_max_first, face_max_first),
            max(shell_min_second, face_min_second),
            min(shell_max_second, face_max_second),
        )
        if (
            clipped[1] - clipped[0] > 0.0
            and clipped[3] - clipped[2] > 0.0
        ):
            clipped_rectangles.append(clipped)
    if not clipped_rectangles:
        return False

    first_boundaries = sorted(
        {
            shell_min_first,
            shell_max_first,
            *(value for rectangle in clipped_rectangles for value in rectangle[:2]),
        }
    )
    second_boundaries = sorted(
        {
            shell_min_second,
            shell_max_second,
            *(value for rectangle in clipped_rectangles for value in rectangle[2:]),
        }
    )
    covered_area = 0.0
    for first_start, first_end in zip(first_boundaries, first_boundaries[1:]):
        for second_start, second_end in zip(second_boundaries, second_boundaries[1:]):
            centroid = (
                (first_start + first_end) / 2.0,
                (second_start + second_end) / 2.0,
            )
            if any(
                rectangle[0] <= centroid[0] <= rectangle[1]
                and rectangle[2] <= centroid[1] <= rectangle[3]
                for rectangle in clipped_rectangles
            ):
                covered_area += (first_end - first_start) * (second_end - second_start)
    shell_area = (shell_max_first - shell_min_first) * (
        shell_max_second - shell_min_second
    )
    return abs(covered_area - shell_area) <= _TOLERANCE


def _build_solid_face_candidate_index(
    solid_faces: list[dict[str, object]],
    node_by_id: dict[int, Node],
) -> tuple[
    dict[
        tuple[int, float],
        tuple[tuple[int, dict[str, object], tuple[float, float, float, float]], ...],
    ],
    tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]],
    tuple[tuple[int, dict[str, object]], ...],
]:
    by_plane: dict[
        tuple[int, float],
        list[tuple[int, dict[str, object], tuple[float, float, float, float]]],
    ] = {}
    plane_coordinates: list[set[float]] = [set(), set(), set()]
    fallback: list[tuple[int, dict[str, object]]] = []
    for index, row in enumerate(solid_faces):
        raw_node_ids = row["node_ids"]
        assert isinstance(raw_node_ids, list)
        nodes = tuple(node_by_id[int(node_id)] for node_id in raw_node_ids)
        fixed_axes = tuple(
            axis
            for axis in range(3)
            if _face_on_plane(nodes, axis, nodes[0].coordinates[axis])
        )
        if len(fixed_axes) != 1:
            fallback.append((index, row))
            continue
        fixed_axis = fixed_axes[0]
        projected_axes = tuple(axis for axis in range(3) if axis != fixed_axis)
        rectangle = (
            min(node.coordinates[projected_axes[0]] for node in nodes),
            max(node.coordinates[projected_axes[0]] for node in nodes),
            min(node.coordinates[projected_axes[1]] for node in nodes),
            max(node.coordinates[projected_axes[1]] for node in nodes),
        )
        if not _projected_nodes_form_rectangle(nodes, projected_axes, rectangle):
            fallback.append((index, row))
            continue
        coordinate = nodes[0].coordinates[fixed_axis]
        plane_coordinates[fixed_axis].add(coordinate)
        by_plane.setdefault((fixed_axis, coordinate), []).append(
            (index, row, rectangle)
        )
    return (
        {key: tuple(value) for key, value in by_plane.items()},
        tuple(tuple(sorted(values)) for values in plane_coordinates),  # type: ignore[return-value]
        tuple(fallback),
    )


def _solid_face_candidates_for_shell(
    shell_nodes: tuple[Node, ...],
    solid_faces: list[dict[str, object]],
    index: tuple[
        dict[
            tuple[int, float],
            tuple[
                tuple[int, dict[str, object], tuple[float, float, float, float]],
                ...,
            ],
        ],
        tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]],
        tuple[tuple[int, dict[str, object]], ...],
    ],
) -> list[dict[str, object]]:
    fixed_axis = next(
        (
            axis
            for axis in range(3)
            if _face_on_plane(shell_nodes, axis, shell_nodes[0].coordinates[axis])
        ),
        None,
    )
    if fixed_axis is None:
        return solid_faces
    coordinate = shell_nodes[0].coordinates[fixed_axis]
    projected_axes = tuple(axis for axis in range(3) if axis != fixed_axis)
    shell_rectangle = (
        min(node.coordinates[projected_axes[0]] for node in shell_nodes),
        max(node.coordinates[projected_axes[0]] for node in shell_nodes),
        min(node.coordinates[projected_axes[1]] for node in shell_nodes),
        max(node.coordinates[projected_axes[1]] for node in shell_nodes),
    )
    if not _projected_nodes_form_rectangle(
        shell_nodes,
        projected_axes,
        shell_rectangle,
    ):
        return solid_faces

    by_plane, plane_coordinates, fallback = index
    close_planes = tuple(
        value
        for value in plane_coordinates[fixed_axis]
        if abs(value - coordinate) <= _TOLERANCE
    )
    if close_planes and close_planes != (coordinate,):
        return solid_faces

    selected: list[tuple[int, dict[str, object]]] = list(fallback)
    for face_index, row, rectangle in by_plane.get((fixed_axis, coordinate), ()):
        if (
            min(shell_rectangle[1], rectangle[1])
            - max(shell_rectangle[0], rectangle[0])
            > 0.0
            and min(shell_rectangle[3], rectangle[3])
            - max(shell_rectangle[2], rectangle[2])
            > 0.0
        ):
            selected.append((face_index, row))
    selected.sort(key=lambda item: item[0])
    return [row for _, row in selected]


def _projected_nodes_form_rectangle(
    nodes: tuple[Node, ...],
    projected_axes: tuple[int, int],
    rectangle: tuple[float, float, float, float],
) -> bool:
    if len(nodes) != 4:
        return False
    min_first, max_first, min_second, max_second = rectangle
    projected_coordinates = tuple(
        (node.coordinates[projected_axes[0]], node.coordinates[projected_axes[1]])
        for node in nodes
    )
    rectangle_corners = (
        (min_first, min_second),
        (max_first, min_second),
        (max_first, max_second),
        (min_first, max_second),
    )
    return all(
        any(
            abs(projected[0] - corner[0]) <= _TOLERANCE
            and abs(projected[1] - corner[1]) <= _TOLERANCE
            for projected in projected_coordinates
        )
        for corner in rectangle_corners
    )
