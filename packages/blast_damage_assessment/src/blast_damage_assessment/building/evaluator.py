"""Explainable component and building severity evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Mapping

import numpy as np

from ..contracts import GateState, Issue, Severity
from ..gates import combine_gate_states
from ..material_capabilities import MaterialCapability
from ..rules import RulePack
from ..semantics import ComponentSemantics
from .connectivity import build_element_adjacency, largest_connected_region


@dataclass(frozen=True)
class MetricObservation:
    available: bool
    values: np.ndarray | None
    reason: str | None
    physical_meaning: str

    def __post_init__(self) -> None:
        if self.values is not None:
            self.values.setflags(write=False)

@dataclass(frozen=True)
class RuleEvidence:
    rule_id: str
    metric_name: str
    actual_value: float
    limit_value: float
    operator: str
    severity: Severity
    field_name: str
    entity_id: int
    state_index: int
    time: float


@dataclass(frozen=True)
class ComponentEvaluationInput:
    component: ComponentSemantics
    entity_ids: np.ndarray
    relative_deformation: np.ndarray
    connectivity: np.ndarray
    entity_kind: str
    support_semantics_explicit: bool
    load_path_semantics_explicit: bool
    alive: np.ndarray | None = None
    material_metric: np.ndarray | None = None
    reference_motion_inferred: bool = False
    hazardous_debris: bool = False
    evacuation_blockage: bool = False
    widespread_failure: bool = False
    corroborated_primary_damage: bool = False
    connected_affected: np.ndarray | None = None
    connected_metric: np.ndarray | None = None
    response_metrics: Mapping[str, float] = field(default_factory=dict)
    deformation_entity_id: int | None = None
    deformation_state_index: int = 0
    deformation_time: float = 0.0
    deletion_entity_id: int | None = None
    deletion_state_index: int = 0
    deletion_time: float = 0.0


@dataclass(frozen=True)
class ComponentEvaluation:
    component_id: str
    zone_id: str | None
    importance_class: str
    primary_load_path: bool
    gate: GateState
    severity: Severity
    p99_relative_deformation: float
    affected_fraction: float
    connected_affected_count: int
    connected_deleted_count: int
    anomalies: tuple[Issue, ...]
    rule_hits: tuple[str, ...]
    hazardous_debris: bool = False
    evacuation_blockage: bool = False
    widespread_failure: bool = False
    corroborated_primary_damage: bool = False
    governing_relative_deformation: float = 0.0

    response_metrics: Mapping[str, float] = field(default_factory=dict)
    rule_evidence: tuple[RuleEvidence, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "response_metrics", MappingProxyType(dict(self.response_metrics)))

    def with_classification(
        self,
        importance_class: str,
        severity: Severity,
        *,
        hazardous_debris: bool = False,
    ) -> "ComponentEvaluation":
        return replace(
            self,
            component_id=f"{self.component_id}:{importance_class}",
            importance_class=importance_class,
            primary_load_path=importance_class == "primary",
            severity=severity,
            hazardous_debris=hazardous_debris,
        )


def _severity(value: float, bands: tuple[float, ...]) -> Severity:
    return Severity(min(4, int(np.searchsorted(np.asarray(bands), value, side="right"))))


def evaluate_material_metrics(
    capability: MaterialCapability,
    *,
    history: np.ndarray | None,
    effective_plastic_strain: np.ndarray | None,
) -> Mapping[str, MetricObservation]:
    metrics: dict[str, MetricObservation] = {}
    if "scaled_damage_measure" in capability.supported_metrics and history is not None:
        metrics["scaled_damage_measure"] = MetricObservation(
            True, np.array(history, dtype=float, copy=True), None, "scaled_damage_measure"
        )
    else:
        metrics["scaled_damage_measure"] = MetricObservation(
            False, None, "material does not expose K&C NOUT=2 scaled damage", "scaled_damage_measure"
        )
    if "effective_plastic_strain" in capability.supported_metrics and effective_plastic_strain is not None:
        metrics["effective_plastic_strain"] = MetricObservation(
            True,
            np.array(effective_plastic_strain, dtype=float, copy=True),
            None,
            "steel_effective_plastic_strain",
        )
    else:
        metrics["effective_plastic_strain"] = MetricObservation(
            False,
            None,
            "material capability or calibrated field is unavailable",
            "steel_effective_plastic_strain",
        )
    return MappingProxyType(metrics)


def evaluate_component(inputs: ComponentEvaluationInput, rule_pack: RulePack) -> ComponentEvaluation:
    entity_ids = np.asarray(inputs.entity_ids, dtype=np.int64)
    values = np.asarray(inputs.relative_deformation, dtype=float)
    if entity_ids.ndim != 1 or values.shape != entity_ids.shape or not np.all(np.isfinite(values)):
        raise ValueError("component entity IDs and relative deformation must be matching finite vectors")
    rule = rule_pack.rule("building_relative_deformation_ratio")
    bands = tuple(float(value) for value in rule["bands"])
    threshold = bands[0]
    p99 = float(np.quantile(values, 0.99, method="linear"))
    p99_severity = _severity(p99, bands)
    adjacency = build_element_adjacency(inputs.connectivity, inputs.entity_kind)
    affected = values >= threshold
    connected_affected = affected if inputs.connected_affected is None else np.asarray(
        inputs.connected_affected, dtype=bool
    )
    if connected_affected.shape != affected.shape:
        raise ValueError("connected affected state must match component entities")
    connected_metric = values if inputs.connected_metric is None else np.asarray(
        inputs.connected_metric, dtype=float
    )
    if connected_metric.shape != values.shape or not np.all(np.isfinite(connected_metric)):
        raise ValueError("connected metric must be a finite vector matching component entities")
    region = largest_connected_region(connected_affected, adjacency, entity_ids)
    minimum_connected = int(rule_pack.payload.get("parameters", {}).get("minimum_connected_elements", 4))  # type: ignore[union-attr]
    connected_count = region.size if region.size >= minimum_connected else 0
    connected_value = (
        max((float(connected_metric[index]) for index in region.indexes), default=0.0)
        if connected_count
        else 0.0
    )
    connected_severity = _severity(connected_value, bands) if connected_count else Severity.NO_OBVIOUS
    severity = max(p99_severity, connected_severity)
    anomalies: list[Issue] = []
    if np.any(affected) and connected_count == 0:
        anomalies.append(
            Issue(
                "building.isolated_spike",
                "Affected values lack the minimum connected support and do not govern severity",
                {"component_id": inputs.component.component_id, "count": int(np.count_nonzero(affected))},
            )
        )
    gate = GateState.FORMAL if rule_pack.formal_eligible else GateState.PROVISIONAL
    deleted_count = 0
    hits = ["building_relative_deformation_ratio"] if severity > Severity.NO_OBVIOUS else []
    deformation_actual = max(p99, connected_value)
    deformation_limit = bands[0] if severity is Severity.NO_OBVIOUS else bands[int(severity) - 1]
    deformation_entity = (
        int(inputs.deformation_entity_id)
        if inputs.deformation_entity_id is not None
        else int(np.min(entity_ids))
    )
    evidence = [
        RuleEvidence(
            "building_relative_deformation_ratio",
            "building_relative_deformation_ratio",
            deformation_actual,
            deformation_limit,
            "<" if severity is Severity.NO_OBVIOUS else ">=",
            Severity(severity),
            "node_displacement_m",
            deformation_entity,
            inputs.deformation_state_index,
            inputs.deformation_time,
        )
    ]
    if inputs.alive is not None:
        alive = np.asarray(inputs.alive, dtype=bool)
        if alive.shape != entity_ids.shape:
            raise ValueError("alive state must match component entities")
        deleted_region = largest_connected_region(~alive, adjacency, entity_ids)
        corroborated = (
            inputs.material_metric is not None and np.any(np.asarray(inputs.material_metric) > 0)
        ) or severity > Severity.NO_OBVIOUS
        if deleted_region.size and (deleted_region.size >= minimum_connected or corroborated):
            deleted_count = deleted_region.size
            deletion_severity = Severity.SEVERE
            severity = max(severity, deletion_severity)
            gate = combine_gate_states(gate, GateState.PROVISIONAL)
            hits.append("numerical_deletion_corroborated")
            deletion_entity = (
                int(inputs.deletion_entity_id)
                if inputs.deletion_entity_id is not None
                else int(min(deleted_region.entity_ids))
            )
            connected_deletion = deleted_region.size >= minimum_connected
            evidence.append(
                RuleEvidence(
                    (
                        "numerical_deletion_connected"
                        if connected_deletion
                        else "numerical_deletion_corroborated"
                    ),
                    "connected_deleted_element_count",
                    float(deleted_region.size),
                    float(minimum_connected if connected_deletion else 1),
                    ">=",
                    deletion_severity,
                    f"{inputs.entity_kind}_is_alive",
                    deletion_entity,
                    inputs.deletion_state_index,
                    inputs.deletion_time,
                )
            )
        elif np.any(~alive):
            anomalies.append(
                Issue(
                    "building.isolated_numerical_deletion",
                    "Isolated numerical deletion is retained as evidence but does not govern",
                    {"component_id": inputs.component.component_id},
                )
            )
    if inputs.reference_motion_inferred:
        gate = combine_gate_states(gate, GateState.PROVISIONAL)
    if (
        inputs.component.primary_load_path
        and severity is Severity.EXTREME
        and not (inputs.support_semantics_explicit and inputs.load_path_semantics_explicit)
    ):
        severity = Severity.SEVERE
        gate = combine_gate_states(gate, GateState.PROVISIONAL)
        evidence = [
            replace(
                item,
                severity=severity,
                limit_value=bands[int(severity) - 1],
                operator=">=",
            )
            if item.severity > severity else item
            for item in evidence
        ]
    return ComponentEvaluation(
        inputs.component.component_id,
        inputs.component.zone_id,
        inputs.component.importance_class,
        inputs.component.primary_load_path,
        gate,
        Severity(severity),
        p99,
        float(np.count_nonzero(affected) / entity_ids.size),
        connected_count,
        deleted_count,
        tuple(anomalies),
        tuple(hits),
        inputs.hazardous_debris,
        inputs.evacuation_blockage,
        inputs.widespread_failure,
        inputs.corroborated_primary_damage,
        max(p99, connected_value),
        inputs.response_metrics,
        tuple(evidence),
    )


@dataclass(frozen=True)
class BuildingEvaluation:
    gate: GateState
    severity: Severity
    class_severities: Mapping[str, Severity]
    zone_severities: Mapping[str, Severity]
    components: tuple[ComponentEvaluation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_severities", MappingProxyType(dict(self.class_severities)))
        object.__setattr__(self, "zone_severities", MappingProxyType(dict(self.zone_severities)))


def evaluate_building(components: tuple[ComponentEvaluation, ...]) -> BuildingEvaluation:
    if not components:
        raise ValueError("building evaluation requires components")
    classes = {name: Severity.NO_OBVIOUS for name in ("primary", "secondary", "nonstructural")}
    zones: dict[str, Severity] = {}
    for component in components:
        name = component.importance_class
        if name not in classes:
            name = "secondary"
        classes[name] = max(classes[name], component.severity)
        if component.zone_id is not None:
            zones[component.zone_id] = max(zones.get(component.zone_id, Severity.NO_OBVIOUS), component.severity)
    overall = classes["primary"]
    for component in components:
        if component.importance_class == "primary":
            continue
        if any(
            (
                component.hazardous_debris,
                component.evacuation_blockage,
                component.widespread_failure,
                component.corroborated_primary_damage,
            )
        ):
            overall = max(overall, component.severity)
    gate = combine_gate_states(*(component.gate for component in components))
    return BuildingEvaluation(gate, Severity(overall), classes, zones, components)
