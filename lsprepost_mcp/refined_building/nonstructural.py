"""Independent nonstructural component meshing for refined buildings."""

from __future__ import annotations

import math
from collections.abc import Mapping

from .artifacts import BuildingArtifact, MeshFragment, Node, PartBinding, ShellElement
from .contracts import normalize_building_definition
from .meshing import merge_fragments
from .spatial import AxisAlignedBox


_MAX_PANEL_AXIS_COORDINATES = 1_000_000


def compile_nonstructural(
    definition: Mapping[str, object], structural: BuildingArtifact
) -> MeshFragment:
    """Compile declared nonstructural panels without structural couplings."""

    normalized = normalize_building_definition(definition)
    if normalized["asset_id"] != structural.asset_id:
        raise ValueError("nonstructural definition does not match structural artifact")
    rows = normalized["nonstructural"]
    assert isinstance(rows, list)
    if not rows:
        raise ValueError("no nonstructural components are declared")
    envelope_data = normalized["envelope"]
    assert isinstance(envelope_data, dict)
    origin = envelope_data["origin_m"]
    size = envelope_data["size_m"]
    assert isinstance(origin, list) and isinstance(size, list)
    envelope = AxisAlignedBox(
        float(origin[0]),
        float(origin[1]),
        float(origin[2]),
        float(origin[0]) + float(size[0]),
        float(origin[1]) + float(size[1]),
        float(origin[2]) + float(size[2]),
    )
    fragments: list[MeshFragment] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"nonstructural[{index}] must be a mapping")
        component_id = row.get("id")
        kind = row.get("kind")
        material_role = row.get("material_role", "nonstructural_generic")
        if not isinstance(component_id, str) or not component_id.strip():
            raise ValueError(f"nonstructural[{index}].id must be non-empty")
        if component_id in seen_ids:
            raise ValueError(f"duplicate nonstructural id: {component_id!r}")
        seen_ids.add(component_id)
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError(f"nonstructural[{index}].kind must be non-empty")
        if not isinstance(material_role, str) or not material_role.strip():
            raise ValueError(f"nonstructural[{index}].material_role must be non-empty")
        bounds_raw = row.get("bounds_m")
        if not isinstance(bounds_raw, list):
            raise ValueError(f"nonstructural[{index}].bounds_m must be a six-value list")
        box = AxisAlignedBox.from_bounds(bounds_raw)
        if not envelope.contains_box(box):
            raise ValueError(f"nonstructural[{index}] must be inside envelope")
        mesh_size = None
        if "mesh_size_m" in row:
            mesh_size = _positive(row["mesh_size_m"], f"nonstructural[{index}].mesh_size_m")
        plane_at = row.get("plane_at", "mid")
        if not isinstance(plane_at, str) or plane_at not in {"min", "mid", "max"}:
            raise ValueError(
                f"nonstructural[{index}].plane_at must be one of: min, mid, max"
            )
        role = f"nonstructural_{kind.strip()}"
        fragments.append(
            _panel_fragment(
                box,
                role,
                material_role.strip(),
                mesh_size_m=mesh_size,
                plane_at=plane_at,
            )
        )
    return merge_fragments(fragments)


def estimate_nonstructural_size(definition: Mapping[str, object]) -> tuple[int, int]:
    """Return exact Shell and pre-merge Node counts without panel allocation."""

    normalized = normalize_building_definition(definition)
    rows = normalized["nonstructural"]
    assert isinstance(rows, list)
    shell_count = 0
    node_count = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"nonstructural[{index}] must be a mapping")
        bounds_raw = row.get("bounds_m")
        if not isinstance(bounds_raw, list):
            raise ValueError(f"nonstructural[{index}].bounds_m must be a six-value list")
        box = AxisAlignedBox.from_bounds(bounds_raw)
        dimensions = (
            box.max_x - box.min_x,
            box.max_y - box.min_y,
            box.max_z - box.min_z,
        )
        thin_axis = min(range(3), key=dimensions.__getitem__)
        in_plane = tuple(axis for axis in range(3) if axis != thin_axis)
        if "mesh_size_m" not in row:
            shell_count += 1
            node_count += 4
            continue
        target = _positive(row["mesh_size_m"], f"nonstructural[{index}].mesh_size_m")
        u_segments = max(1, math.ceil(dimensions[in_plane[0]] / target))
        v_segments = max(1, math.ceil(dimensions[in_plane[1]] / target))
        shell_count += u_segments * v_segments
        node_count += (u_segments + 1) * (v_segments + 1)
    return shell_count, node_count


def _panel_fragment(
    box: AxisAlignedBox,
    role: str,
    material_role: str,
    *,
    mesh_size_m: float | None = None,
    plane_at: str = "mid",
) -> MeshFragment:
    dimensions = (
        box.max_x - box.min_x,
        box.max_y - box.min_y,
        box.max_z - box.min_z,
    )
    thin_axis = min(range(3), key=dimensions.__getitem__)
    bounds = box.as_tuple()
    fixed = {
        "min": bounds[thin_axis],
        "mid": (bounds[thin_axis] + bounds[thin_axis + 3]) / 2.0,
        "max": bounds[thin_axis + 3],
    }[plane_at]
    if thin_axis == 0:
        x = fixed
        coordinates = (
            (x, box.min_y, box.min_z),
            (x, box.max_y, box.min_z),
            (x, box.max_y, box.max_z),
            (x, box.min_y, box.max_z),
        )
    elif thin_axis == 1:
        y = fixed
        coordinates = (
            (box.min_x, y, box.min_z),
            (box.max_x, y, box.min_z),
            (box.max_x, y, box.max_z),
            (box.min_x, y, box.max_z),
        )
    else:
        z = fixed
        coordinates = (
            (box.min_x, box.min_y, z),
            (box.max_x, box.min_y, z),
            (box.max_x, box.max_y, z),
            (box.min_x, box.max_y, z),
        )
    if mesh_size_m is None:
        nodes = tuple(Node(index + 1, *coordinates[index]) for index in range(4))
        return MeshFragment(
            nodes=nodes,
            shells=(ShellElement(1, (1, 2, 3, 4), role),),
            part_bindings=(PartBinding(role, material_role, f"{role}_shell_section"),),
        )

    in_plane_axes = tuple(axis for axis in range(3) if axis != thin_axis)
    u_axis, v_axis = in_plane_axes
    u_values = _axis_coordinates(
        bounds[u_axis], bounds[u_axis + 3], mesh_size_m
    )
    v_values = _axis_coordinates(
        bounds[v_axis], bounds[v_axis + 3], mesh_size_m
    )

    def coordinate(u: float, v: float) -> tuple[float, float, float]:
        values = [0.0, 0.0, 0.0]
        values[thin_axis] = fixed
        values[u_axis] = u
        values[v_axis] = v
        return (values[0], values[1], values[2])

    nodes = tuple(
        Node(iv * len(u_values) + iu + 1, *coordinate(u, v))
        for iv, v in enumerate(v_values)
        for iu, u in enumerate(u_values)
    )
    shells = tuple(
        ShellElement(
            iv * (len(u_values) - 1) + iu + 1,
            (
                iv * len(u_values) + iu + 1,
                iv * len(u_values) + iu + 2,
                (iv + 1) * len(u_values) + iu + 2,
                (iv + 1) * len(u_values) + iu + 1,
            ),
            role,
        )
        for iv in range(len(v_values) - 1)
        for iu in range(len(u_values) - 1)
    )
    return MeshFragment(
        nodes=nodes,
        shells=shells,
        part_bindings=(PartBinding(role, material_role, f"{role}_shell_section"),),
    )


def _positive(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a positive finite number")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{path} must be a positive finite number")
    return result


def _axis_coordinates(start: float, end: float, target: float) -> tuple[float, ...]:
    segment_count = max(1, math.ceil((end - start) / target))
    if segment_count + 1 > _MAX_PANEL_AXIS_COORDINATES:
        raise ValueError(
            "panel axis coordinate allocation exceeds internal hard cap "
            f"{_MAX_PANEL_AXIS_COORDINATES}"
        )
    spacing = (end - start) / segment_count
    return tuple(start + spacing * index for index in range(segment_count)) + (end,)
