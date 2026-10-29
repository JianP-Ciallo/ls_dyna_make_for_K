"""Bounded streamed MM-ALE grid with active air, TNT, and grade buffer."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from typing import Iterator

from ..artifacts import Node, SolidElement
from ..spatial import AxisAlignedBox
from .air_topology import (
    ALE_CELL_INDEX_ITEMSIZE_BYTES,
    AirCellPlan,
    AirRegionModel,
    build_air_cell_plan,
    build_air_region,
    classify_ale_cell,
)
from .charge import ChargeModel
from .contracts import SolverBlastConfig
from .ground import GroundModel
from .physical_building import PhysicalBuildingModel


_MAX_AXIS_COORDINATES = 100_000
_MAX_ALE_NODES = 8_000_000
_MAX_ALE_ELEMENTS = 6_000_000
_MAX_ALE_CELL_PLAN_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class AleDomainEstimate:
    part_role: str
    buffer_part_role: str
    tnt_part_role: str
    visible: bool
    bounds: AxisAlignedBox
    active_air_bounds: AxisAlignedBox
    coupling_buffer_bounds: AxisAlignedBox
    air_region: AirRegionModel
    cell_plan: AirCellPlan
    tnt_bounds_m: tuple[float, float, float, float, float, float]
    x_coordinates: tuple[float, ...]
    y_coordinates: tuple[float, ...]
    z_coordinates: tuple[float, ...]
    node_id_start: int
    element_id_start: int
    node_count: int
    element_count: int
    air_element_count: int
    active_air_element_count: int
    buffer_element_count: int
    tnt_element_count: int
    tnt_subdivisions_per_axis: int
    realized_tnt_volume_m3: float
    realized_tnt_mass_kg: float
    boundary_face_counts: tuple[tuple[str, int], ...]
    target_cell_size_m: float
    charge_refinement_cell_size_m: float
    minimum_charge_diameter_cells: float
    fingerprint: str


def estimate_ale_domain(
    building: PhysicalBuildingModel,
    ground: GroundModel,
    charge: ChargeModel,
    config: SolverBlastConfig,
) -> AleDomainEstimate:
    building_box = AxisAlignedBox.from_bounds(building.bounds_m)
    charge_box = AxisAlignedBox.from_bounds(charge.bounds_m)
    top_margin = config.air_margins_m[4]
    grade = ground.grade_elevation_m
    buffer_bottom = grade - config.coupling_buffer_layers * config.air_cell_size_m
    ground_box = AxisAlignedBox.from_bounds(ground.bounds_m)
    bounds = AxisAlignedBox(
        ground_box.min_x,
        ground_box.min_y,
        buffer_bottom,
        ground_box.max_x,
        ground_box.max_y,
        max(building_box.max_z, grade) + top_margin,
    )
    active_air_bounds = AxisAlignedBox(
        bounds.min_x,
        bounds.min_y,
        grade,
        bounds.max_x,
        bounds.max_y,
        bounds.max_z,
    )
    coupling_buffer_bounds = AxisAlignedBox(
        bounds.min_x,
        bounds.min_y,
        buffer_bottom,
        bounds.max_x,
        bounds.max_y,
        grade,
    )
    air_region = build_air_region(building, coupling_buffer_bounds)

    if charge_box.min_z < grade - 1.0e-12:
        raise ValueError(
            "below-grade TNT requires a dedicated internal ALE block"
        )
    refinement = min(
        config.air_cell_size_m,
        config.near_field_cell_size_m,
        charge.side_length_m / 3.0,
    )
    if any(value < refinement - 1.0e-12 for value in config.air_margins_m):
        raise ValueError(
            "air_margins_m must leave at least one local TNT refinement cell "
            "between the charge surface and the far boundary"
        )
    if not bounds.contains_box(charge_box):
        raise ValueError("TNT charge must lie inside the fixed ALE domain")
    clearances = (
        charge_box.min_x - bounds.min_x,
        bounds.max_x - charge_box.max_x,
        charge_box.min_y - bounds.min_y,
        bounds.max_y - charge_box.max_y,
        charge_box.min_z - bounds.min_z,
        bounds.max_z - charge_box.max_z,
    )
    if any(clearance < refinement - 1.0e-12 for clearance in clearances):
        raise ValueError(
            "TNT charge must leave at least one local refinement cell "
            "of clearance from every ALE outer boundary"
        )

    tnt_subdivisions = max(3, math.ceil(charge.side_length_m / refinement))
    connected_region_bounds = (
        *air_region.connected_internal_bounds_m,
        *air_region.connected_opening_bounds_m,
    )
    internal_axis_breaks = tuple(
        tuple(
            coordinate
            for row in connected_region_bounds
            for coordinate in (row[axis], row[axis + 3])
        )
        for axis in range(3)
    )
    required_breaks = (
        internal_axis_breaks[0],
        internal_axis_breaks[1],
        (*internal_axis_breaks[2], grade),
    )
    axis_specs = (
        (
            bounds.min_x, bounds.max_x, charge.position_m[0],
            required_breaks[0], None,
        ),
        (
            bounds.min_y, bounds.max_y, charge.position_m[1],
            required_breaks[1], None,
        ),
        (
            bounds.min_z, bounds.max_z, charge.position_m[2],
            required_breaks[2], grade,
        ),
    )
    upper_counts: list[int] = []
    for low, high, _, breaks, _anchor in axis_specs:
        count = (
            math.ceil((high - low) / config.air_cell_size_m)
            + 1
            + tnt_subdivisions
            + 1
            + len(breaks)
        )
        if count > _MAX_AXIS_COORDINATES:
            raise ValueError(
                f"ALE axis coordinate budget exceeded: estimated {count}, "
                f"limit {_MAX_AXIS_COORDINATES}"
            )
        upper_counts.append(count)
    node_upper = math.prod(upper_counts)
    element_upper = math.prod(max(1, value - 1) for value in upper_counts)
    if element_upper > _MAX_ALE_ELEMENTS:
        raise ValueError(
            "ALE element budget exceeded: "
            f"estimated {element_upper}, limit {_MAX_ALE_ELEMENTS}"
        )
    cell_plan_peak_upper = element_upper * (
        2 + ALE_CELL_INDEX_ITEMSIZE_BYTES
    )
    if cell_plan_peak_upper > _MAX_ALE_CELL_PLAN_BYTES:
        raise ValueError(
            "ALE cell-plan memory budget exceeded: "
            f"estimated {cell_plan_peak_upper} bytes, "
            f"limit {_MAX_ALE_CELL_PLAN_BYTES}"
        )
    if node_upper > _MAX_ALE_NODES:
        raise ValueError(
            f"ALE node budget exceeded: estimated {node_upper}, limit {_MAX_ALE_NODES}"
        )

    axes = tuple(
        _axis_coordinates(
            low,
            high,
            config.air_cell_size_m,
            center,
            charge.side_length_m,
            tnt_subdivisions,
            breaks,
            anchor,
        )
        for low, high, center, breaks, anchor in axis_specs
    )
    x_coordinates, y_coordinates, z_coordinates = axes
    below_grade_interval_count = sum(
        1
        for _left, right in zip(z_coordinates, z_coordinates[1:])
        if right <= grade + 1.0e-12
    )
    if below_grade_interval_count != config.coupling_buffer_layers:
        raise ValueError(
            "connected underground topology would split the strict 1-5 layer "
            "coupling buffer; a dedicated internal ALE block is required"
        )
    cell_plan = build_air_cell_plan(
        x_coordinates, y_coordinates, z_coordinates, air_region, charge.bounds_m
    )
    node_count = len(x_coordinates) * len(y_coordinates) * len(z_coordinates)
    element_count = (
        (len(x_coordinates) - 1)
        * (len(y_coordinates) - 1)
        * (len(z_coordinates) - 1)
    )
    if node_count > _MAX_ALE_NODES or element_count > _MAX_ALE_ELEMENTS:
        raise ValueError("ALE exact budget exceeded after charge refinement")
    minimum_resolution = min(
        _span_cells(axis, center, charge.side_length_m)
        for axis, center in zip(axes, charge.position_m)
    )
    if minimum_resolution < 3.0 - 1.0e-9:
        raise ValueError("ALE charge refinement must resolve the TNT diameter by three cells")

    nx, ny, nz = (
        len(x_coordinates) - 1,
        len(y_coordinates) - 1,
        len(z_coordinates) - 1,
    )
    boundary_face_counts = (
        ("x_min", ny * nz),
        ("x_max", ny * nz),
        ("y_min", nx * nz),
        ("y_max", nx * nz),
        ("z_min", nx * ny),
        ("z_max", nx * ny),
    )
    realized_tnt_volume = charge.side_length_m**3
    realized_tnt_mass = realized_tnt_volume * charge.density_kg_per_m3
    provisional = AleDomainEstimate(
        part_role="ale_active_air_domain",
        buffer_part_role="ale_coupling_buffer",
        tnt_part_role=charge.material_role,
        visible=True,
        bounds=bounds,
        active_air_bounds=active_air_bounds,
        coupling_buffer_bounds=coupling_buffer_bounds,
        air_region=air_region,
        cell_plan=cell_plan,
        tnt_bounds_m=charge.bounds_m,
        x_coordinates=x_coordinates,
        y_coordinates=y_coordinates,
        z_coordinates=z_coordinates,
        node_id_start=40_000_001,
        element_id_start=50_000_001,
        node_count=node_count,
        element_count=element_count,
        air_element_count=0,
        active_air_element_count=0,
        buffer_element_count=0,
        tnt_element_count=0,
        tnt_subdivisions_per_axis=tnt_subdivisions,
        realized_tnt_volume_m3=realized_tnt_volume,
        realized_tnt_mass_kg=realized_tnt_mass,
        boundary_face_counts=boundary_face_counts,
        target_cell_size_m=config.air_cell_size_m,
        charge_refinement_cell_size_m=refinement,
        minimum_charge_diameter_cells=minimum_resolution,
        fingerprint="",
    )
    if cell_plan.active_air_cell_count <= 0:
        raise ValueError("ALE active-air partition must contain explicit Solid elements")
    if cell_plan.buffer_cell_count <= 0:
        raise ValueError("ALE coupling buffer must contain explicit Solid elements")
    if cell_plan.tnt_cell_count <= 0:
        raise ValueError("ALE TNT partition must contain explicit Solid elements")

    identity = {
        "schema_version": "phase18.solver_blast.ale_domain@4",
        "part_role": provisional.part_role,
        "buffer_part_role": provisional.buffer_part_role,
        "tnt_part_role": provisional.tnt_part_role,
        "bounds_m": list(bounds.as_tuple()),
        "active_air_bounds_m": list(active_air_bounds.as_tuple()),
        "coupling_buffer_bounds_m": list(coupling_buffer_bounds.as_tuple()),
        "air_region_fingerprint": air_region.fingerprint,
        "cell_plan_fingerprint": cell_plan.fingerprint,
        "axis_hashes": [
            hashlib.sha256(
                json.dumps(axis, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            for axis in axes
        ],
        "node_count": node_count,
        "element_count": element_count,
        "active_air_element_count": cell_plan.active_air_cell_count,
        "buffer_element_count": cell_plan.buffer_cell_count,
        "tnt_element_count": cell_plan.tnt_cell_count,
        "tnt_subdivisions_per_axis": tnt_subdivisions,
        "realized_tnt_volume_m3": realized_tnt_volume,
        "realized_tnt_mass_kg": realized_tnt_mass,
        "target_cell_size_m": config.air_cell_size_m,
        "charge_refinement_cell_size_m": refinement,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return replace(
        provisional,
        air_element_count=cell_plan.active_air_cell_count,
        active_air_element_count=cell_plan.active_air_cell_count,
        buffer_element_count=cell_plan.buffer_cell_count,
        tnt_element_count=cell_plan.tnt_cell_count,
        fingerprint=fingerprint,
    )


def iter_ale_nodes(domain: AleDomainEstimate) -> Iterator[Node]:
    node_id = domain.node_id_start
    for z in domain.z_coordinates:
        for y in domain.y_coordinates:
            for x in domain.x_coordinates:
                yield Node(node_id, x, y, z)
                node_id += 1


def iter_ale_elements(domain: AleDomainEstimate) -> Iterator[SolidElement]:
    nx = len(domain.x_coordinates) - 1
    ny = len(domain.y_coordinates) - 1

    def node_id(ix: int, iy: int, iz: int) -> int:
        return domain.node_id_start + iz * (ny + 1) * (nx + 1) + iy * (nx + 1) + ix

    role_by_kind = {
        "active_air": domain.part_role,
        "explicit_tnt": domain.tnt_part_role,
        "coupling_buffer": domain.buffer_part_role,
    }
    element_id = domain.element_id_start
    for iz in range(len(domain.z_coordinates) - 1):
        for iy in range(ny):
            for ix in range(nx):
                yield SolidElement(
                    element_id,
                    (
                        node_id(ix, iy, iz),
                        node_id(ix + 1, iy, iz),
                        node_id(ix + 1, iy + 1, iz),
                        node_id(ix, iy + 1, iz),
                        node_id(ix, iy, iz + 1),
                        node_id(ix + 1, iy, iz + 1),
                        node_id(ix + 1, iy + 1, iz + 1),
                        node_id(ix, iy + 1, iz + 1),
                    ),
                    role_by_kind[classify_ale_cell(domain, ix, iy, iz)],
                )
                element_id += 1


def _axis_coordinates(
    low: float,
    high: float,
    target_size_m: float,
    charge_center: float,
    charge_side_length: float,
    tnt_subdivisions: int,
    required_breaks: tuple[float, ...] = (),
    regular_anchor: float | None = None,
) -> tuple[float, ...]:
    values = _regular_axis_coordinates(low, high, target_size_m, regular_anchor)
    lower = charge_center - 0.5 * charge_side_length
    values.extend(
        lower + charge_side_length * index / tnt_subdivisions
        for index in range(tnt_subdivisions + 1)
    )
    values.extend(required_breaks)
    merged: list[float] = []
    for value in sorted(max(low, min(high, row)) for row in values):
        if merged and value - merged[-1] <= 1.0e-12:
            merged[-1] = value
        else:
            merged.append(value)
    return tuple(merged)


def _regular_axis_coordinates(
    low: float,
    high: float,
    target_size_m: float,
    anchor: float | None,
) -> list[float]:
    if anchor is not None and low < anchor < high:
        intervals = ((low, anchor), (anchor, high))
    else:
        intervals = ((low, high),)
    values: list[float] = []
    for start, stop in intervals:
        ratio = (stop - start) / target_size_m
        nearest = round(ratio)
        if math.isclose(
            ratio,
            nearest,
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        ):
            count = max(1, int(nearest))
        else:
            count = max(1, math.ceil(ratio))
        spacing = (stop - start) / count
        values.extend(start + spacing * index for index in range(count))
    values.append(high)
    return values


def _span_cells(
    axis: tuple[float, ...], center: float, side_length: float
) -> float:
    lower = center - 0.5 * side_length
    upper = center + 0.5 * side_length
    coordinates = tuple(value for value in axis if lower - 1.0e-12 <= value <= upper + 1.0e-12)
    if len(coordinates) < 4:
        return 0.0
    maximum_spacing = max(right - left for left, right in zip(coordinates, coordinates[1:]))
    resolution = side_length / maximum_spacing
    nearest_integer = round(resolution)
    if math.isclose(resolution, nearest_integer, rel_tol=1.0e-12, abs_tol=1.0e-12):
        return float(nearest_integer)
    return resolution


def _contained_cell_count(
    axis: tuple[float, ...], lower: float, upper: float
) -> int:
    return sum(
        1
        for left, right in zip(axis, axis[1:])
        if left >= lower - 1.0e-12 and right <= upper + 1.0e-12
    )
