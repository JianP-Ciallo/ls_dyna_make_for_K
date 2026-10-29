from __future__ import annotations

from .config import JSONDict

def grid_count(size: float, mesh_size: float) -> int:
    return max(1, round(size / mesh_size))


def node_id(ix: int, iy: int, nx: int) -> int:
    return iy * (nx + 1) + ix + 1


def format_id_lines(ids: list[int]) -> list[str]:
    return [",".join(str(value) for value in ids[start : start + 8]) for start in range(0, len(ids), 8)]


DOF_NUMBERS = {"x": 1, "y": 2, "z": 3}
SPC_DOF_MASK = {"x": 0, "y": 1, "z": 2, "rx": 3, "ry": 4, "rz": 5}
EDGE_AXES = {
    "x_min": (0, "min"),
    "x_max": (0, "max"),
    "y_min": (1, "min"),
    "y_max": (1, "max"),
    "z_min": (2, "min"),
    "z_max": (2, "max"),
}
Segment = tuple[int, int, int, int]


