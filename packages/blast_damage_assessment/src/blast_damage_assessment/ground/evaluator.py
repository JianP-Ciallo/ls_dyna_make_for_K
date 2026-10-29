"""Independent geometric and material subratings for ground response."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

import numpy as np

from ..contracts import GateState, Severity
from ..gates import combine_gate_states
from ..material_capabilities import MaterialCapability
from ..rules import RulePack
from .metrics import (
    GroundAccumulator,
    GroundStateRecord,
    RegionMetrics,
    StabilityResult,
    detect_seeded_regions,
    evaluate_stability,
    region_metrics,
)
from .surface import SurfaceMesh


@dataclass(frozen=True)
class GroundEvaluationInput:
    surface: SurfaceMesh
    times: np.ndarray
    vertical_displacement: np.ndarray
    surface_speed: np.ndarray | None
    material_capability: MaterialCapability
    material_metric: np.ndarray | None = None
    material_metric_name: str | None = None
    alive: np.ndarray | None = None


@dataclass(frozen=True)
class GroundShape:
    crater: RegionMetrics
    uplift: RegionMetrics
    settlement: RegionMetrics


@dataclass(frozen=True)
class GroundSubrating:
    available: bool
    severity: Severity | None
    reason: str | None
    rule_hits: tuple[str, ...]
    metric_name: str | None = None
    actual_value: float | None = None
    limit_value: float | None = None
    operator: str | None = None


@dataclass(frozen=True)
class GroundEvaluation:
    gate: GateState
    severity: Severity
    peak: GroundShape
    final: GroundShape
    stability: StabilityResult
    subratings: Mapping[str, GroundSubrating]
    material_metrics: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "subratings", MappingProxyType(dict(self.subratings)))
        object.__setattr__(self, "material_metrics", MappingProxyType(dict(self.material_metrics)))


def _severity(value: float, bands: tuple[float, ...]) -> Severity:
    return Severity(min(4, int(np.searchsorted(np.asarray(bands), value, side="right"))))


def _band_evidence(value: float, bands: tuple[float, ...], rule_id: str) -> tuple[Severity, str, float, float, str]:
    severity = _severity(value, bands)
    limit = bands[0] if severity is Severity.NO_OBVIOUS else bands[int(severity) - 1]
    return severity, rule_id, value, limit, "<" if severity is Severity.NO_OBVIOUS else ">="


def _region_rating(
    metrics: RegionMetrics, surface: SurfaceMesh, rule_pack: RulePack
) -> tuple[Severity, str, float, float, str]:
    depth_bands = tuple(float(value) for value in rule_pack.rule("ground_depth_to_median_surface_cell")["bands"])
    area_bands = tuple(float(value) for value in rule_pack.rule("ground_connected_area_in_surface_cells")["bands"])
    amplitude = max(metrics.maximum_depth, metrics.maximum_height) / surface.median_cell_length
    candidates = (
        _band_evidence(amplitude, depth_bands, "ground_depth_to_median_surface_cell"),
        _band_evidence(float(metrics.affected_cell_count), area_bands, "ground_connected_area_in_surface_cells"),
    )
    return max(candidates, key=lambda item: int(item[0]))


def evaluate_ground(inputs: GroundEvaluationInput, rule_pack: RulePack) -> GroundEvaluation:
    times = np.asarray(inputs.times, dtype=float)
    displacement = np.asarray(inputs.vertical_displacement, dtype=float)
    cell_count = len(inputs.surface.cells)
    if times.ndim != 1 or displacement.shape != (times.size, cell_count) or times.size == 0:
        raise ValueError("ground times and displacement must have shapes (states,) and (states, cells)")
    if not np.all(np.isfinite(times)) or not np.all(np.isfinite(displacement)):
        raise ValueError("ground state data must be finite")
    speed = None if inputs.surface_speed is None else np.asarray(inputs.surface_speed, dtype=float)
    if speed is not None and (speed.shape != displacement.shape or not np.all(np.isfinite(speed))):
        raise ValueError("ground speed must match displacement and be finite")
    shapes: list[GroundShape] = []
    accumulator = GroundAccumulator()
    for state_index, (time, values) in enumerate(zip(times, displacement)):
        detection = detect_seeded_regions(inputs.surface, values)
        shape = GroundShape(
            region_metrics(inputs.surface, detection.crater, values),
            region_metrics(inputs.surface, detection.uplift, values),
            region_metrics(inputs.surface, detection.settlement, values),
        )
        shapes.append(shape)
        p95_speed = None if speed is None else float(np.quantile(np.abs(speed[state_index]), 0.95, method="linear"))
        accumulator.update(
            GroundStateRecord(
                state_index,
                float(time),
                shape.crater.maximum_depth,
                shape.crater.signed_prism_volume,
                shape.crater.plan_area,
                p95_speed,
                detection.crater.cell_indexes,
            )
        )
    stability_parameters = rule_pack.payload.get("parameters", {})
    stability = evaluate_stability(
        accumulator.states,
        median_cell_length=inputs.surface.median_cell_length,
        tail_fraction=float(stability_parameters.get("tail_fraction", 0.2)),  # type: ignore[union-attr]
        minimum_tail_states=int(stability_parameters.get("minimum_tail_states", 5)),  # type: ignore[union-attr]
        maximum_tail_speed_fraction_of_peak=float(stability_parameters.get("maximum_tail_speed_fraction_of_peak", 0.05)),  # type: ignore[union-attr]
        absolute_tail_speed_floor_m_per_s=float(stability_parameters.get("absolute_tail_speed_floor_m_per_s", 0.01)),  # type: ignore[union-attr]
        maximum_tail_geometry_relative_drift=float(stability_parameters.get("maximum_tail_geometry_relative_drift", 0.02)),  # type: ignore[union-attr]
        minimum_tail_region_jaccard=float(stability_parameters.get("minimum_tail_region_jaccard", 0.95)),  # type: ignore[union-attr]
    )
    peak = GroundShape(
        max((shape.crater for shape in shapes), key=lambda item: (item.maximum_depth, item.plan_area)),
        max((shape.uplift for shape in shapes), key=lambda item: (item.maximum_height, item.plan_area)),
        max((shape.settlement for shape in shapes), key=lambda item: (item.maximum_depth, item.plan_area)),
    )
    final = shapes[-1]
    subratings: dict[str, GroundSubrating] = {}
    for name, metrics in (("crater", peak.crater), ("uplift", peak.uplift), ("outside_settlement", peak.settlement)):
        rating = _region_rating(metrics, inputs.surface, rule_pack)
        subratings[name] = GroundSubrating(
            True,
            rating[0],
            None,
            ("ground_depth_to_median_surface_cell", "ground_connected_area_in_surface_cells"),
            rating[1],
            rating[2],
            rating[3],
            rating[4],
        )
    material_metrics: dict[str, float] = {}
    material_name = inputs.material_metric_name
    if inputs.material_metric is None or material_name is None:
        subratings["material_damage"] = GroundSubrating(
            False, None, "material response field is unavailable", ()
        )
    else:
        material_values = np.asarray(inputs.material_metric, dtype=float)
        if material_values.shape != (cell_count,) or not np.all(np.isfinite(material_values)):
            raise ValueError("ground material metric must be a finite surface-cell vector")
        material_value = float(np.max(material_values))
        material_metrics[material_name] = material_value
        if material_name not in inputs.material_capability.supported_metrics:
            subratings["material_damage"] = GroundSubrating(
                False, None, "material capability does not support this response meaning", ()
            )
        else:
            material_rule_id = f"ground_{material_name}"
            material_rule = next(
                (
                    rule
                    for rule in rule_pack.rules
                    if rule["id"] == material_rule_id and "bands" in rule
                ),
                None,
            )
            if material_rule is None:
                subratings["material_damage"] = GroundSubrating(
                    False,
                    None,
                    "rule pack has no calibrated rule bound to this material metric",
                    (),
                )
            else:
                material_bands = tuple(float(value) for value in material_rule["bands"])
                rating = _band_evidence(material_value, material_bands, material_rule_id)
                subratings["material_damage"] = GroundSubrating(
                    True, rating[0], None, (material_rule_id,),
                    rating[1], rating[2], rating[3], rating[4],
                )
    if inputs.alive is None:
        subratings["numerical_erosion"] = GroundSubrating(False, None, "alive-state field is unavailable", ())
    else:
        alive = np.asarray(inputs.alive, dtype=bool)
        if alive.shape == (cell_count,):
            deleted = ~alive
        elif alive.shape == displacement.shape:
            deleted = ~alive[-1]
        else:
            raise ValueError("ground alive values must be final cells or match displacement states")
        from .metrics import _components

        regions = _components(deleted, inputs.surface.adjacency)
        connected = len(regions[0]) if regions else 0
        erosion_bands = tuple(
            float(value) for value in rule_pack.rule("ground_connected_area_in_surface_cells")["bands"]
        )
        rating = _band_evidence(float(connected), erosion_bands, "numerical_deletion")
        subratings["numerical_erosion"] = GroundSubrating(
            True, rating[0], None, ("numerical_deletion",),
            rating[1],
            rating[2],
            rating[3],
            rating[4],
        )
    severity = max(
        (item.severity for item in subratings.values() if item.available and item.severity is not None),
        default=Severity.NO_OBVIOUS,
    )
    gate = inputs.surface.gate
    if not rule_pack.formal_eligible or speed is None or not inputs.material_capability.engineering_validated:
        gate = combine_gate_states(gate, GateState.PROVISIONAL)
    return GroundEvaluation(gate, Severity(severity), peak, final, stability, subratings, material_metrics)
