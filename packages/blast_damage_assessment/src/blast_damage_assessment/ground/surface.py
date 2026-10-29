"""Initial diagnostic-ground surface extraction."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

import numpy as np

from ..contracts import GateState
from ..errors import ContractError


_HEX_FACES = ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
_AXIS = {"x": 0, "y": 1, "z": 2}


@dataclass(frozen=True)
class SurfaceCell:
    cell_id: int
    node_indexes: tuple[int, ...]
    centroid: tuple[float, float, float]
    plan_area: float
    source_element_index: int | None = None


@dataclass(frozen=True)
class SurfaceMesh:
    cells: tuple[SurfaceCell, ...]
    adjacency: tuple[tuple[int, ...], ...]
    median_cell_length: float
    model_extent: float
    blast_projection: tuple[float, float, float]
    inferred: bool
    gate: GateState


def _polygon_area(points: np.ndarray, vertical: int) -> float:
    horizontal = [index for index in range(3) if index != vertical]
    x = points[:, horizontal[0]]
    y = points[:, horizontal[1]]
    return abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))) * 0.5


def _normal_alignment(points: np.ndarray, vertical: int) -> float:
    normal = np.zeros(3, dtype=float)
    anchor = points[0]
    for index in range(1, points.shape[0] - 1):
        normal += np.cross(points[index] - anchor, points[index + 1] - anchor)
    magnitude = float(np.linalg.norm(normal))
    if magnitude <= 0.0:
        return 0.0
    return abs(float(normal[vertical])) / magnitude


def _point_in_polygon(point: np.ndarray, polygon: np.ndarray) -> bool:
    inside = False
    tolerance = 1e-12
    for index in range(polygon.shape[0]):
        first = polygon[index]
        second = polygon[(index + 1) % polygon.shape[0]]
        edge = second - first
        relative = point - first
        cross = edge[0] * relative[1] - edge[1] * relative[0]
        if abs(float(cross)) <= tolerance:
            dot = float(np.dot(relative, edge))
            if -tolerance <= dot <= float(np.dot(edge, edge)) + tolerance:
                return True
        if (first[1] > point[1]) != (second[1] > point[1]):
            intersection = first[0] + (
                (point[1] - first[1])
                * (second[0] - first[0])
                / (second[1] - first[1])
            )
            if point[0] < intersection:
                inside = not inside
    return inside


def extract_initial_surface(
    coordinates: np.ndarray,
    solid_connectivity: np.ndarray,
    solid_part_ids: np.ndarray,
    ground_part_ids: tuple[int, ...],
    blast_center: tuple[float, float, float],
    *,
    vertical_axis: str = "z",
    surface_direction: str = "max",
    inferred: bool = False,
) -> SurfaceMesh:
    points = np.asarray(coordinates, dtype=float)
    elements = np.asarray(solid_connectivity, dtype=np.int64)
    parts = np.asarray(solid_part_ids, dtype=np.int64)
    if vertical_axis not in _AXIS:
        raise ContractError("vertical axis must be x, y, or z")
    vertical = _AXIS[vertical_axis]
    if points.ndim != 2 or points.shape[1] != 3 or elements.ndim != 2 or elements.shape[1] != 8:
        raise ContractError("ground surface extraction requires points and 8-node solids")
    if surface_direction not in {"min", "max"}:
        raise ContractError("surface direction must be min or max")
    if elements.shape[0] != parts.size:
        raise ContractError("ground solid Part mapping size mismatch")
    selected = np.isin(parts, np.asarray(ground_part_ids, dtype=np.int64))
    if not np.any(selected):
        raise ContractError("declared ground Part has no solid elements")
    face_occurrences: dict[tuple[int, ...], list[tuple[tuple[int, ...], float, int]]] = defaultdict(list)
    for element_index in np.flatnonzero(selected):
        row = elements[element_index]
        if np.min(row) < 0 or np.max(row) >= points.shape[0]:
            raise ContractError("ground solid references an unknown node")
        element_center = float(np.mean(points[row, vertical]))
        for face_indexes in _HEX_FACES:
            face = tuple(int(row[index]) for index in face_indexes)
            center = float(np.mean(points[list(face), vertical]))
            face_occurrences[tuple(sorted(face))].append((face, center - element_center, int(element_index)))
    if any(len(entries) > 2 for entries in face_occurrences.values()):
        raise ContractError("ground boundary is nonmanifold")
    direction = 1.0 if surface_direction == "max" else -1.0
    upper_faces = [
        entries[0]
        for entries in face_occurrences.values()
        if len(entries) == 1
        and direction * entries[0][1] > 0
        and _normal_alignment(points[list(entries[0][0])], vertical) >= 0.9
    ]
    if not upper_faces:
        raise ContractError("ground upper surface could not be identified")
    cells: list[SurfaceCell] = []
    for cell_id, (face, _, element_index) in enumerate(sorted(upper_faces, key=lambda item: tuple(sorted(item[0])))):
        face_points = points[list(face)]
        area = _polygon_area(face_points, vertical)
        if area <= 0:
            raise ContractError("ground surface contains a zero-area face")
        cells.append(
            SurfaceCell(
                cell_id,
                face,
                tuple(float(value) for value in np.mean(face_points, axis=0)),
                area,
                element_index,
            )
        )
    edges: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, cell in enumerate(cells):
        nodes = cell.node_indexes
        for offset in range(len(nodes)):
            edges[tuple(sorted((nodes[offset], nodes[(offset + 1) % len(nodes)])))].append(index)
    adjacency = [set() for _ in cells]
    for indexes in edges.values():
        for left, right in combinations(indexes, 2):
            adjacency[left].add(right)
            adjacency[right].add(left)
    horizontal = [index for index in range(3) if index != vertical]
    surface_nodes = np.unique(np.asarray([node for cell in cells for node in cell.node_indexes]))
    center = np.asarray(blast_center, dtype=float)
    projected_center = center[horizontal]
    if not any(
        _point_in_polygon(
            projected_center,
            points[list(cell.node_indexes)][:, horizontal],
        )
        for cell in cells
    ):
        raise ContractError("blast-center projection falls outside the modeled ground")
    cell_centers = np.asarray([cell.centroid for cell in cells])
    nearest = int(np.argmin(np.linalg.norm(cell_centers[:, horizontal] - center[horizontal], axis=1)))
    projection = center.copy()
    projection[vertical] = cell_centers[nearest, vertical]
    median_length = float(np.median(np.sqrt([cell.plan_area for cell in cells])))
    extent = float(np.linalg.norm(np.ptp(points[elements[selected].ravel()], axis=0)))
    return SurfaceMesh(
        tuple(cells),
        tuple(tuple(sorted(item)) for item in adjacency),
        median_length,
        extent,
        tuple(float(value) for value in projection),
        inferred,
        GateState.PROVISIONAL if inferred else GateState.FORMAL,
    )
