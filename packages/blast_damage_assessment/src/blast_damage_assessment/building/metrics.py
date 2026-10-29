"""Streaming robust metrics for building entities."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..errors import ContractError


@dataclass(frozen=True)
class MetricSummary:
    peak_max: float
    final_max: float
    residual_max: float
    p95: float
    p99: float
    affected_fraction: float
    extreme_entity_id: int
    extreme_time_index: int
    extreme_time: float
    peak_by_entity: np.ndarray
    final_by_entity: np.ndarray

    def __post_init__(self) -> None:
        self.peak_by_entity.setflags(write=False)
        self.final_by_entity.setflags(write=False)


class BuildingAccumulator:
    def __init__(self, entity_ids: np.ndarray):
        ids = np.asarray(entity_ids)
        if ids.ndim != 1 or ids.size == 0 or not np.issubdtype(ids.dtype, np.integer):
            raise ContractError("entity_ids must be a non-empty integer vector")
        if np.unique(ids).size != ids.size:
            raise ContractError("entity_ids must be unique")
        self.entity_ids = np.array(ids, dtype=np.int64, copy=True)
        self.entity_ids.setflags(write=False)
        self._peak = np.zeros(ids.size, dtype=float)
        self._final = np.zeros(ids.size, dtype=float)
        self._last_time_index: int | None = None
        self._extreme: tuple[float, int, int, float] | None = None

    def update(self, time_index: int, time: float, values: np.ndarray) -> None:
        data = np.asarray(values, dtype=float)
        if data.shape != self.entity_ids.shape or not np.all(np.isfinite(data)):
            raise ContractError("accumulator values must be a finite vector matching entity_ids")
        if isinstance(time_index, bool) or not isinstance(time_index, int) or time_index < 0:
            raise ContractError("time_index must be a non-negative integer")
        if not math.isfinite(time):
            raise ContractError("time must be finite")
        absolute = np.abs(data)
        self._peak = np.maximum(self._peak, absolute)
        if self._last_time_index is None or time_index >= self._last_time_index:
            self._final = absolute.copy()
            self._last_time_index = time_index
        local_peak = float(np.max(absolute))
        local_ids = self.entity_ids[absolute == local_peak]
        local_id = int(np.min(local_ids))
        candidate = (local_peak, time_index, local_id, float(time))
        if self._extreme is None:
            self._extreme = candidate
        else:
            old = self._extreme
            if candidate[0] > old[0] or (
                candidate[0] == old[0] and (candidate[1], candidate[2]) < (old[1], old[2])
            ):
                self._extreme = candidate

    def summary(self, *, affected_threshold: float = math.inf) -> MetricSummary:
        if self._extreme is None:
            raise ContractError("accumulator has no states")
        if isinstance(affected_threshold, bool) or not isinstance(affected_threshold, (int, float)):
            raise ContractError("affected_threshold must be numeric")
        affected = int(np.count_nonzero(self._peak >= affected_threshold))
        peak, time_index, entity_id, time = self._extreme
        return MetricSummary(
            peak,
            float(np.max(self._final)),
            float(np.max(self._final)),
            float(np.quantile(self._peak, 0.95, method="linear")),
            float(np.quantile(self._peak, 0.99, method="linear")),
            affected / self.entity_ids.size,
            entity_id,
            time_index,
            time,
            self._peak.copy(),
            self._final.copy(),
        )


@dataclass(frozen=True)
class RelativeDeformation:
    ratios: np.ndarray
    reference_motion: np.ndarray
    characteristic_length: float
    reference_motion_inferred: bool

    def __post_init__(self) -> None:
        self.ratios.setflags(write=False)
        self.reference_motion.setflags(write=False)


def relative_deformation(
    initial_coordinates: np.ndarray,
    displacement: np.ndarray,
    *,
    support_node_indexes: list[int] | np.ndarray | None = None,
) -> RelativeDeformation:
    coordinates = np.asarray(initial_coordinates, dtype=float)
    motion = np.asarray(displacement, dtype=float)
    if coordinates.ndim != 2 or coordinates.shape[1] != 3 or motion.shape != coordinates.shape:
        raise ContractError("coordinates and displacement must have matching (n, 3) shapes")
    if not np.all(np.isfinite(coordinates)) or not np.all(np.isfinite(motion)):
        raise ContractError("coordinates and displacement must be finite")
    extent = float(np.linalg.norm(np.ptp(coordinates, axis=0)))
    if extent <= 0:
        raise ContractError("component characteristic length must be positive")
    inferred = support_node_indexes is None
    if support_node_indexes is None:
        reference = np.median(motion, axis=0)
    else:
        indexes = np.asarray(support_node_indexes, dtype=np.int64)
        if indexes.ndim != 1 or indexes.size == 0 or np.min(indexes) < 0 or np.max(indexes) >= motion.shape[0]:
            raise ContractError("support node indexes are invalid")
        reference = np.median(motion[indexes], axis=0)
    ratios = np.linalg.norm(motion - reference, axis=1) / extent
    return RelativeDeformation(ratios, np.array(reference, copy=True), extent, inferred)


@dataclass(frozen=True)
class StressInvariants:
    von_mises: np.ndarray
    maximum_principal: np.ndarray

    def __post_init__(self) -> None:
        self.von_mises.setflags(write=False)
        self.maximum_principal.setflags(write=False)


def stress_invariants(stress: np.ndarray) -> StressInvariants:
    values = np.asarray(stress, dtype=float)
    if values.ndim != 2 or values.shape[1] != 6 or not np.all(np.isfinite(values)):
        raise ContractError("stress must be a finite (n, 6) tensor array")
    xx, yy, zz, xy, yz, zx = values.T
    von_mises = np.sqrt(
        0.5 * ((xx - yy) ** 2 + (yy - zz) ** 2 + (zz - xx) ** 2)
        + 3.0 * (xy**2 + yz**2 + zx**2)
    )
    tensors = np.empty((values.shape[0], 3, 3), dtype=float)
    tensors[:, 0, 0], tensors[:, 1, 1], tensors[:, 2, 2] = xx, yy, zz
    tensors[:, 0, 1] = tensors[:, 1, 0] = xy
    tensors[:, 1, 2] = tensors[:, 2, 1] = yz
    tensors[:, 2, 0] = tensors[:, 0, 2] = zx
    principal = np.linalg.eigvalsh(tensors)[:, -1]
    return StressInvariants(von_mises, principal)
