from __future__ import annotations

import math

from .component_library import estimate_component_mesh
from .config import JSONDict
from .schema import ModelSpec


MAX_AXIS_CELLS = 500
MAX_RING_SEGMENTS = 720
MAX_NODES = 250_000
MAX_ELEMENTS = 200_000
MAX_KEYWORD_BYTES = 80 * 1024 * 1024


def preflight_model_spec(spec: ModelSpec) -> JSONDict:
    estimate = estimate_model_size(spec)
    problems: list[str] = []
    dimensions = estimate["dimensions"]
    limits = estimate["limits"]
    for key, value in dimensions.items():
        limit = MAX_RING_SEGMENTS if key == "nt" else MAX_AXIS_CELLS
        if int(value) > limit:
            problems.append(f"{key}={value} exceeds limit {limit}")
    if int(estimate["node_count"]) > int(limits["max_nodes"]):
        problems.append(f"node_count={estimate['node_count']} exceeds limit {limits['max_nodes']}")
    if int(estimate["element_count"]) > int(limits["max_elements"]):
        problems.append(f"element_count={estimate['element_count']} exceeds limit {limits['max_elements']}")
    if int(estimate["keyword_bytes"]) > MAX_KEYWORD_BYTES:
        problems.append(f"keyword_bytes={estimate['keyword_bytes']} exceeds limit {MAX_KEYWORD_BYTES}")
    if problems:
        raise ValueError(
            "mesh preflight exceeded safe generation limits: "
            + "; ".join(problems)
            + f"; suggested mesh.size_m >= {estimate['suggested_mesh_size_m']:.9g}"
        )
    return estimate


def estimate_model_size(spec: ModelSpec) -> JSONDict:
    mesh_size = float(spec.mesh["size_m"])
    geometry = spec.geometry
    model_type = spec.model_type

    if model_type == "shell_plate":
        nx = grid_count(float(geometry["length_m"]), mesh_size)
        ny = grid_count(float(geometry["width_m"]), mesh_size)
        nodes = (nx + 1) * (ny + 1)
        elements = nx * ny
        dimensions = {"nx": nx, "ny": ny}
        dimensionality = 2
    elif model_type in {"solid_block", "beam_bar"}:
        nx = grid_count(float(geometry["length_m"]), mesh_size)
        ny = grid_count(float(geometry["width_m"]), mesh_size)
        nz = grid_count(float(geometry["height_m"]), mesh_size)
        nodes = (nx + 1) * (ny + 1) * (nz + 1)
        elements = nx * ny * nz
        dimensions = {"nx": nx, "ny": ny, "nz": nz}
        dimensionality = 3
    elif model_type == "shell_box":
        nx = grid_count(float(geometry["length_m"]), mesh_size)
        ny = grid_count(float(geometry["width_m"]), mesh_size)
        nz = grid_count(float(geometry["height_m"]), mesh_size)
        nodes = 2 * ((nx + 1) * (ny + 1) + (nx + 1) * max(nz - 1, 0) + (ny + 1) * max(nz - 1, 0))
        elements = 2 * (nx * ny + nx * nz + ny * nz)
        dimensions = {"nx": nx, "ny": ny, "nz": nz}
        dimensionality = 2
    elif model_type == "cylinder_shell":
        nt = max(8, round(2 * math.pi * float(geometry["radius_m"]) / mesh_size))
        nz = grid_count(float(geometry["length_m"]), mesh_size)
        nodes = nt * (nz + 1)
        elements = nt * nz
        dimensions = {"nt": nt, "nz": nz}
        dimensionality = 2
    elif model_type == "cylinder_solid":
        nxy = max(4, 2 * grid_count(float(geometry["radius_m"]), mesh_size))
        nz = grid_count(float(geometry["length_m"]), mesh_size)
        nodes = (nxy + 1) * (nxy + 1) * (nz + 1)
        elements = nxy * nxy * nz
        dimensions = {"nxy": nxy, "nz": nz}
        dimensionality = 3
    elif model_type == "single_solid_element_test":
        nodes = 8
        elements = 1
        dimensions = {"nx": 1, "ny": 1, "nz": 1}
        dimensionality = 3
    elif model_type == "assembly_scene":
        nodes = 0
        elements = 0
        dimensionality = 3
        dimensions = {}
        for index, component in enumerate(spec.components):
            template = str(component["template"])
            component_mesh_size = float(component["mesh"]["size_m"])
            geometry = component["geometry"]
            component_nodes, component_elements, component_dimensions = estimate_component_mesh(
                template, geometry, component_mesh_size
            )
            nodes += component_nodes
            elements += component_elements
            for key, value in component_dimensions.items():
                dimensions[f"c{index}_{key}"] = value
    elif model_type == "ale_blast_scene":
        domain_min = geometry["domain_min_m"]
        domain_max = geometry["domain_max_m"]
        if geometry.get("scene_variant") == "open_concrete_tunnel":
            nx = grid_count(float(domain_max[0]) - float(domain_min[0]), mesh_size)
            ny = grid_count(float(domain_max[1]) - float(domain_min[1]), mesh_size)
            nz = grid_count(float(domain_max[2]) - float(domain_min[2]), mesh_size)
            plate_size = float(spec.mesh.get("plate_size_m", 0.05))
        else:
            nx = grid_count(float(domain_max[0]) - float(domain_min[0]), mesh_size)
            ny = grid_count(float(domain_max[1]) - float(domain_min[1]), mesh_size)
            nz = grid_count(float(domain_max[2]) - float(domain_min[2]), mesh_size)
            plate_size = mesh_size
        plate_nx = grid_count(float(geometry["plate_length_m"]), plate_size)
        plate_ny = grid_count(float(geometry["plate_width_m"]), plate_size)
        nodes = (nx + 1) * (ny + 1) * (nz + 1) + (plate_nx + 1) * (plate_ny + 1)
        elements = nx * ny * nz + plate_nx * plate_ny
        if geometry.get("scene_variant") == "open_concrete_tunnel":
            wall_size = float(spec.mesh.get("wall_size_m", mesh_size))
            wall_nx = grid_count(float(geometry["tunnel_length_m"]), wall_size)
            wall_ny = grid_count(float(geometry["tunnel_width_m"]), wall_size)
            wall_nz = grid_count(float(geometry["tunnel_height_m"]), wall_size)
            nodes += 2 * (wall_nx + 1) * (wall_ny + 1) + 2 * (wall_nx + 1) * (wall_nz + 1)
            elements += 2 * wall_nx * wall_ny + 2 * wall_nx * wall_nz
        dimensions = {
            "nx": nx,
            "ny": ny,
            "nz": nz,
            "plate_nx": plate_nx,
            "plate_ny": plate_ny,
        }
        dimensionality = 3
    else:
        raise ValueError(f"unsupported model_type for preflight: {model_type}")

    keyword_bytes = estimate_keyword_bytes(nodes, elements)
    suggested = suggested_mesh_size(mesh_size, dimensions, nodes, elements, keyword_bytes, dimensionality)
    tunnel_limits = model_type == "ale_blast_scene" and geometry.get("scene_variant") == "open_concrete_tunnel"
    return {
        "model_type": model_type,
        "mesh_size_m": mesh_size,
        "dimensions": dimensions,
        "node_count": nodes,
        "element_count": elements,
        "keyword_bytes": keyword_bytes,
        "suggested_mesh_size_m": suggested,
        "limits": {
            "max_axis_cells": MAX_AXIS_CELLS,
            "max_ring_segments": MAX_RING_SEGMENTS,
            "max_nodes": 400_000 if tunnel_limits else MAX_NODES,
            "max_elements": 350_000 if tunnel_limits else MAX_ELEMENTS,
            "max_keyword_bytes": MAX_KEYWORD_BYTES,
        },
    }


def grid_count(size: float, mesh_size: float) -> int:
    return max(1, round(size / mesh_size))


def piecewise_axis(
    low: float,
    high: float,
    base_size: float,
    regions: list[tuple[float, float, float]],
) -> list[float]:
    """Create a conforming axis using the smallest requested local cell size."""

    breaks = {float(low), float(high)}
    clipped: list[tuple[float, float, float]] = []
    for start, end, size in regions:
        left = max(float(low), min(float(high), float(start)))
        right = max(float(low), min(float(high), float(end)))
        if right <= left or size <= 0.0:
            continue
        clipped.append((left, right, float(size)))
        breaks.update({left, right})
    ordered = sorted(breaks)
    coordinates = [float(low)]
    for left, right in zip(ordered, ordered[1:]):
        midpoint = 0.5 * (left + right)
        sizes = [size for start, end, size in clipped if start <= midpoint <= end]
        count = grid_count(right - left, min(sizes) if sizes else float(base_size))
        step = (right - left) / count
        coordinates.extend(left + step * index for index in range(1, count + 1))
    return coordinates


def estimate_keyword_bytes(nodes: int, elements: int) -> int:
    return 8_192 + nodes * 80 + elements * 96


def suggested_mesh_size(
    mesh_size: float,
    dimensions: JSONDict,
    nodes: int,
    elements: int,
    keyword_bytes: int,
    dimensionality: int,
) -> float:
    scale = 1.0
    for key, value in dimensions.items():
        limit = MAX_RING_SEGMENTS if key == "nt" else MAX_AXIS_CELLS
        if int(value) > limit:
            scale = max(scale, int(value) / limit)
    if nodes > MAX_NODES:
        scale = max(scale, (nodes / MAX_NODES) ** (1.0 / max(dimensionality, 1)))
    if elements > MAX_ELEMENTS:
        scale = max(scale, (elements / MAX_ELEMENTS) ** (1.0 / max(dimensionality, 1)))
    if keyword_bytes > MAX_KEYWORD_BYTES:
        scale = max(scale, (keyword_bytes / MAX_KEYWORD_BYTES) ** (1.0 / max(dimensionality, 1)))
    return mesh_size * scale * 1.05
