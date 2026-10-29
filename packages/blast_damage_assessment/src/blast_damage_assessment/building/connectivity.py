"""Deterministic face, edge, and endpoint connectivity."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from itertools import combinations

import numpy as np

from ..errors import ContractError


def _solid_faces(row: np.ndarray) -> tuple[tuple[int, ...], ...]:
    nodes = tuple(int(value) for value in row)
    if len(nodes) == 8:
        indexes = ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
    elif len(nodes) == 4:
        indexes = ((0, 1, 2), (0, 1, 3), (1, 2, 3), (0, 2, 3))
    else:
        raise ContractError("solid connectivity must contain 4 or 8 nodes")
    return tuple(tuple(sorted(nodes[index] for index in face)) for face in indexes)


def _shell_edges(row: np.ndarray) -> tuple[tuple[int, int], ...]:
    nodes = tuple(int(value) for value in row)
    if len(nodes) not in {3, 4}:
        raise ContractError("shell connectivity must contain 3 or 4 nodes")
    return tuple(tuple(sorted((nodes[index], nodes[(index + 1) % len(nodes)]))) for index in range(len(nodes)))


def build_element_adjacency(connectivity: np.ndarray, entity_kind: str) -> tuple[tuple[int, ...], ...]:
    rows = np.asarray(connectivity)
    if rows.ndim != 2:
        raise ContractError("element connectivity must be two-dimensional")
    tokens: dict[object, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        if entity_kind == "solid":
            entity_tokens = _solid_faces(row)
        elif entity_kind == "shell":
            entity_tokens = _shell_edges(row)
        elif entity_kind == "beam":
            if row.size < 2:
                raise ContractError("beam connectivity must contain two end nodes")
            entity_tokens = (int(row[0]), int(row[1]))
        else:
            raise ContractError(f"unsupported element kind: {entity_kind}")
        for token in entity_tokens:
            tokens[token].append(index)
    adjacent = [set() for _ in range(rows.shape[0])]
    for indexes in tokens.values():
        for left, right in combinations(indexes, 2):
            adjacent[left].add(right)
            adjacent[right].add(left)
    return tuple(tuple(sorted(neighbors)) for neighbors in adjacent)


@dataclass(frozen=True)
class ConnectedRegion:
    size: int
    indexes: tuple[int, ...]
    entity_ids: tuple[int, ...]


def largest_connected_region(
    affected: np.ndarray,
    adjacency: tuple[tuple[int, ...], ...],
    entity_ids: np.ndarray,
) -> ConnectedRegion:
    mask = np.asarray(affected, dtype=bool)
    ids = np.asarray(entity_ids, dtype=np.int64)
    if mask.ndim != 1 or ids.shape != mask.shape or len(adjacency) != mask.size:
        raise ContractError("affected mask, adjacency, and entity IDs must have matching sizes")
    visited: set[int] = set()
    candidates: list[ConnectedRegion] = []
    for start in range(mask.size):
        if not mask[start] or start in visited:
            continue
        queue = deque([start])
        visited.add(start)
        region: list[int] = []
        while queue:
            index = queue.popleft()
            region.append(index)
            for neighbor in adjacency[index]:
                if mask[neighbor] and neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        region_ids = tuple(sorted(int(ids[index]) for index in region))
        candidates.append(ConnectedRegion(len(region), tuple(sorted(region)), region_ids))
    if not candidates:
        return ConnectedRegion(0, (), ())
    return min(candidates, key=lambda item: (-item.size, item.entity_ids))
