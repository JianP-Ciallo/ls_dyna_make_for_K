"""Seeded ground-region metrics and residual-state stability."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np

from ..contracts import Issue
from ..errors import ContractError
from .surface import SurfaceMesh


@dataclass(frozen=True)
class GroundRegion:
    cell_indexes: tuple[int, ...]


@dataclass(frozen=True)
class RegionDetection:
    crater: GroundRegion
    uplift: GroundRegion
    settlement: GroundRegion
    noise_threshold: float
    anomalies: tuple[Issue, ...]


@dataclass(frozen=True)
class RadialRing:
    ring_index: int
    inner_radius: float
    outer_radius: float
    cell_count: int
    mean_signed_displacement: float


@dataclass(frozen=True)
class RegionMetrics:
    maximum_depth: float
    maximum_height: float
    plan_area: float
    equivalent_diameter: float
    signed_prism_volume: float
    affected_cell_count: int
    radial_rings: tuple[RadialRing, ...]


def _components(mask: np.ndarray, adjacency: tuple[tuple[int, ...], ...]) -> list[tuple[int, ...]]:
    visited: set[int] = set()
    result: list[tuple[int, ...]] = []
    for start in range(mask.size):
        if not mask[start] or start in visited:
            continue
        queue = deque([start])
        visited.add(start)
        values: list[int] = []
        while queue:
            index = queue.popleft()
            values.append(index)
            for neighbor in adjacency[index]:
                if mask[neighbor] and neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        result.append(tuple(sorted(values)))
    return sorted(result, key=lambda item: (-len(item), item))


def _seeded(mask: np.ndarray, surface: SurfaceMesh) -> tuple[int, ...]:
    centers = np.asarray([cell.centroid for cell in surface.cells])
    blast = np.asarray(surface.blast_projection)
    distances = np.linalg.norm(centers - blast, axis=1)
    nearest_distance = float(np.min(distances))
    seeds = np.flatnonzero(mask & (distances <= nearest_distance + surface.median_cell_length + 1e-12))
    if seeds.size == 0:
        return ()
    reached = set(int(value) for value in seeds)
    queue = deque(sorted(reached))
    while queue:
        index = queue.popleft()
        for neighbor in surface.adjacency[index]:
            if mask[neighbor] and neighbor not in reached:
                reached.add(neighbor)
                queue.append(neighbor)
    return tuple(sorted(reached))


def detect_seeded_regions(surface: SurfaceMesh, vertical_displacement: np.ndarray) -> RegionDetection:
    values = np.asarray(vertical_displacement, dtype=float)
    if values.shape != (len(surface.cells),) or not np.all(np.isfinite(values)):
        raise ContractError("surface displacement must be a finite value per cell")
    absolute = np.abs(values)
    median_abs = float(np.median(absolute))
    mad = float(np.median(np.abs(absolute - median_abs)))
    threshold = max(1e-6 * surface.model_extent, median_abs + 5.0 * mad)
    negative = values < -threshold
    positive = values > threshold
    crater_indexes = _seeded(negative, surface)
    uplift_indexes = _seeded(positive, surface)
    outside_negative = negative.copy()
    if crater_indexes:
        outside_negative[list(crater_indexes)] = False
    settlement_components = _components(outside_negative, surface.adjacency)
    settlement_indexes = settlement_components[0] if settlement_components and len(settlement_components[0]) >= 2 else ()
    unexplained = set(np.flatnonzero(negative | positive)) - set(crater_indexes) - set(uplift_indexes) - set(settlement_indexes)
    anomalies = (
        (
            Issue(
                "ground.isolated_response",
                "Distant or isolated surface response was excluded from seeded regions",
                {"cell_indexes": tuple(sorted(int(value) for value in unexplained))},
            ),
        )
        if unexplained
        else ()
    )
    return RegionDetection(
        GroundRegion(crater_indexes),
        GroundRegion(uplift_indexes),
        GroundRegion(settlement_indexes),
        threshold,
        anomalies,
    )


def region_metrics(surface: SurfaceMesh, region: GroundRegion, values: np.ndarray) -> RegionMetrics:
    displacement = np.asarray(values, dtype=float)
    if not region.cell_indexes:
        return RegionMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0, ())
    indexes = np.asarray(region.cell_indexes, dtype=np.int64)
    selected = displacement[indexes]
    areas = np.asarray([surface.cells[index].plan_area for index in indexes], dtype=float)
    area = math.fsum(float(value) for value in areas)
    volume = math.fsum(float(value * weight) for value, weight in zip(selected, areas))
    centers = np.asarray([surface.cells[index].centroid for index in indexes])
    blast = np.asarray(surface.blast_projection)
    distances = np.linalg.norm(centers - blast, axis=1)
    ring_ids = np.floor(distances / surface.median_cell_length).astype(int)
    rings: list[RadialRing] = []
    for ring in sorted(set(int(value) for value in ring_ids)):
        mask = ring_ids == ring
        rings.append(
            RadialRing(
                ring,
                ring * surface.median_cell_length,
                (ring + 1) * surface.median_cell_length,
                int(np.count_nonzero(mask)),
                float(np.mean(selected[mask])),
            )
        )
    return RegionMetrics(
        max(0.0, float(-np.min(selected))),
        max(0.0, float(np.max(selected))),
        area,
        math.sqrt(4.0 * area / math.pi),
        volume,
        len(region.cell_indexes),
        tuple(rings),
    )


@dataclass(frozen=True)
class GroundStateRecord:
    time_index: int
    time: float
    crater_depth: float
    crater_volume: float
    crater_area: float
    p95_surface_speed: float | None
    crater_region: tuple[int, ...]


class GroundAccumulator:
    def __init__(self) -> None:
        self._states: list[GroundStateRecord] = []

    def update(self, record: GroundStateRecord) -> None:
        if self._states and record.time_index <= self._states[-1].time_index:
            raise ContractError("ground state indexes must increase")
        self._states.append(record)

    @property
    def states(self) -> tuple[GroundStateRecord, ...]:
        return tuple(self._states)


@dataclass(frozen=True)
class StabilityResult:
    stable: bool
    shape_term: str
    failed_criteria: tuple[str, ...]
    tail_state_count: int


def _jaccard(left: tuple[int, ...], right: tuple[int, ...]) -> float:
    a, b = set(left), set(right)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def evaluate_stability(
    states: tuple[GroundStateRecord, ...],
    *,
    median_cell_length: float,
    tail_fraction: float = 0.2,
    minimum_tail_states: int = 5,
    maximum_tail_speed_fraction_of_peak: float = 0.05,
    absolute_tail_speed_floor_m_per_s: float = 0.01,
    maximum_tail_geometry_relative_drift: float = 0.02,
    minimum_tail_region_jaccard: float = 0.95,
) -> StabilityResult:
    tail_count = max(minimum_tail_states, int(math.ceil(tail_fraction * len(states))))
    failed: list[str] = []
    if len(states) < tail_count:
        failed.append("too_few_states")
        return StabilityResult(False, "instantaneous_final_shape", tuple(failed), tail_count)
    tail = states[-tail_count:]
    speeds = [record.p95_surface_speed for record in states]
    if any(value is None for value in speeds):
        failed.append("velocity_unavailable")
    else:
        peak_speed = max(float(value) for value in speeds if value is not None)
        tail_speed = max(float(record.p95_surface_speed) for record in tail if record.p95_surface_speed is not None)
        limit = max(absolute_tail_speed_floor_m_per_s, maximum_tail_speed_fraction_of_peak * peak_speed)
        if tail_speed > limit:
            failed.append("tail_speed")
    depth_allowance = max(1e-5, 0.01 * median_cell_length)
    depths = [record.crater_depth for record in tail]
    if max(depths) - min(depths) > max(depth_allowance, maximum_tail_geometry_relative_drift * max(abs(depths[-1]), depth_allowance)):
        failed.append("depth_drift")
    for name, values in (
        ("volume_drift", [record.crater_volume for record in tail]),
        ("area_drift", [record.crater_area for record in tail]),
    ):
        scale = max(abs(values[-1]), 1e-12)
        if max(values) - min(values) > maximum_tail_geometry_relative_drift * scale:
            failed.append(name)
    if any(_jaccard(left.crater_region, right.crater_region) < minimum_tail_region_jaccard for left, right in zip(tail, tail[1:])):
        failed.append("region_jaccard")
    stable = not failed
    return StabilityResult(stable, "residual_shape" if stable else "instantaneous_final_shape", tuple(failed), tail_count)
