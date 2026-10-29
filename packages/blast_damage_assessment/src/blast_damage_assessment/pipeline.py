"""Single deterministic orchestration path for standalone assessments."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

import numpy as np

from .adapters.contracts import AdapterProbe, EntityKind, GeometryIndex, ResultAdapter
from .adapters.lsdyna.adapter import LsdynaResultAdapter
from .aggregation import AggregateAssessment, aggregate_assessment
from .building.evaluator import (
    BuildingEvaluation,
    ComponentEvaluation,
    ComponentEvaluationInput,
    evaluate_building,
    evaluate_component,
)
from .building.connectivity import build_element_adjacency, largest_connected_region
from .building.metrics import BuildingAccumulator, relative_deformation
from .canonical import canonical_json_bytes, sha256_json
from .contracts import (
    ArtifactReference,
    AssessmentRequest,
    AssessmentResult,
    FileReference,
    GateState,
    Issue,
    Severity,
)
from .errors import AssessmentError, ContractError
from .evidence import EvidenceGraph, validate_evidence_graph
from .gates import (
    BuildingGateFacts,
    CommonGateFacts,
    GateDecision,
    GroundGateFacts,
    combine_gate_states,
    evaluate_building_gate,
    evaluate_ground_gate,
)
from .ground.evaluator import GroundEvaluation, GroundEvaluationInput, evaluate_ground
from .ground.surface import extract_initial_surface
from .output_store import AtomicAssessmentOutput
from .reporting import render_building_csv, render_ground_csv, render_html_report
from .rules import RulePack, check_rule_applicability, load_rule_pack, snapshot_rule_pack
from .schema import parse_request
from .semantics import ModelSemantics, load_semantics
from .source_evidence import EvidenceFile, SourceEvidence, inspect_source


SNAPSHOT_SCHEMA = "blast_damage.assessment_snapshot@1"
RESULT_SCHEMA = "blast_damage.assessment_result@1"
RULE_SNAPSHOT_SCHEMA = "blast_damage.rule_snapshot@1"
_KEPT_FIELDS = {
    "node_displacement_m",
    "node_velocity_m_per_s",
    "solid_stress_pa",
    "solid_effective_plastic_strain",
    "solid_history_variables",
    "solid_is_alive",
    "shell_stress_pa",
    "shell_effective_plastic_strain",
    "shell_history_variables",
    "shell_strain",
    "shell_is_alive",
    "beam_axial_force_n",
    "beam_shear_force_n",
    "beam_is_alive",
}
_FULL_HISTORY_FIELDS = {
    "node_displacement_m",
    "node_velocity_m_per_s",
}
_FINAL_STATE_FIELDS = {
    "solid_is_alive",
    "shell_is_alive",
    "beam_is_alive",
}


def _reduce_axes(values: np.ndarray, *, absolute: bool = False) -> np.ndarray:
    data = np.abs(values) if absolute else values
    axes = tuple(range(2, data.ndim))
    return np.max(data, axis=axes) if axes else data


def _response_field_arrays(
    field_name: str,
    values: np.ndarray,
) -> Mapping[str, np.ndarray]:
    if values.ndim < 2:
        raise AssessmentError(f"adapter field {field_name} must include state and entity axes")
    if field_name.endswith("_stress_pa"):
        if values.ndim < 3 or values.shape[-1] != 6:
            raise AssessmentError(
                f"adapter field {field_name} must end with six stress components"
            )
        state_count, entity_count = values.shape[:2]
        tensors = values.reshape(state_count, entity_count, -1, 6)
        xx, yy, zz, xy, yz, zx = np.moveaxis(tensors, -1, 0)
        von_mises = np.sqrt(
            0.5 * ((xx - yy) ** 2 + (yy - zz) ** 2 + (zz - xx) ** 2)
            + 3.0 * (xy**2 + yz**2 + zx**2)
        )
        matrices = np.empty((*tensors.shape[:-1], 3, 3), dtype=float)
        matrices[..., 0, 0] = xx
        matrices[..., 1, 1] = yy
        matrices[..., 2, 2] = zz
        matrices[..., 0, 1] = matrices[..., 1, 0] = xy
        matrices[..., 1, 2] = matrices[..., 2, 1] = yz
        matrices[..., 2, 0] = matrices[..., 0, 2] = zx
        maximum_principal = np.linalg.eigvalsh(matrices)[..., -1]
        prefix = field_name.removesuffix("_stress_pa")
        return MappingProxyType(
            {
                f"{prefix}_von_mises_stress_pa": np.max(von_mises, axis=2),
                f"{prefix}_maximum_principal_stress_pa": np.max(
                    maximum_principal, axis=2
                ),
            }
        )
    if field_name.endswith("_history_variables"):
        history_zero = values if values.ndim == 2 else values[..., 0]
        prefix = field_name.removesuffix("_history_variables")
        return MappingProxyType(
            {f"{prefix}_history_variable_0": _reduce_axes(history_zero)}
        )
    return MappingProxyType(
        {field_name: _reduce_axes(values, absolute=True)}
    )



@dataclass(frozen=True)
class _CollectedField:
    values: np.ndarray
    entity_ids: np.ndarray
    standard_unit: str
    conversion_id: str
    source_field_name: str

    def __post_init__(self) -> None:
        self.values.setflags(write=False)
        self.entity_ids.setflags(write=False)


@dataclass(frozen=True)
class _BlockedSubject:
    gate: GateState = GateState.BLOCKED
    severity: None = None
    governing_rule_hits: tuple[str, ...] = ()


def _available(probe: AdapterProbe, name: str) -> bool:
    value = probe.fields.get(name)
    return bool(value is not None and value.available)


def _collect_fields(
    adapter: ResultAdapter,
    result_dir: Path,
    state_count: int,
    chunk_size: int,
) -> tuple[np.ndarray, Mapping[str, _CollectedField]]:
    if state_count <= 0:
        raise AssessmentError("adapter reported no result states")
    times = np.full(state_count, np.nan, dtype=float)
    buffers: dict[str, np.ndarray] = {}
    filled: dict[str, np.ndarray] = {}
    finals: dict[str, np.ndarray] = {}
    final_filled: dict[str, np.ndarray] = {}
    peaks: dict[str, np.ndarray] = {}
    peak_filled: dict[str, np.ndarray] = {}
    metadata: dict[str, tuple[np.ndarray, str, str, str]] = {}
    for chunk in adapter.iter_state_chunks(result_dir, chunk_size):
        chunk_times = np.asarray(chunk.times, dtype=float)
        for field_name, field in chunk.fields.items():
            if field_name not in _KEPT_FIELDS:
                continue
            indexes = np.asarray(field.time_indices, dtype=np.int64)
            values = np.asarray(field.standard_values)
            if indexes.ndim != 1 or indexes.size != chunk_times.size or values.shape[0] != indexes.size:
                raise AssessmentError(f"adapter field {field_name} has inconsistent state dimensions")
            if indexes.size and (np.min(indexes) < 0 or np.max(indexes) >= state_count):
                raise AssessmentError(f"adapter field {field_name} has out-of-range state indexes")
            entity_ids = np.asarray(field.entity_ids, dtype=np.int64)
            if values.ndim < 2 or values.shape[1] != entity_ids.size:
                raise AssessmentError(f"adapter field {field_name} has inconsistent entity dimensions")
            if field_name in _FULL_HISTORY_FIELDS:
                if field_name not in buffers:
                    buffers[field_name] = np.empty(
                        (state_count, *values.shape[1:]), dtype=values.dtype
                    )
                    filled[field_name] = np.zeros(state_count, dtype=bool)
                    metadata[field_name] = (
                        entity_ids.copy(),
                        field.standard_unit,
                        field.conversion_id,
                        field.source_field_name,
                    )
                elif buffers[field_name].shape[1:] != values.shape[1:]:
                    raise AssessmentError(f"adapter field {field_name} changes shape between chunks")
                elif not np.array_equal(metadata[field_name][0], entity_ids):
                    raise AssessmentError(f"adapter field {field_name} changes entity identity")
                if np.any(filled[field_name][indexes]):
                    raise AssessmentError(f"adapter field {field_name} repeats a state")
                buffers[field_name][indexes] = values
                filled[field_name][indexes] = True
            elif field_name in _FINAL_STATE_FIELDS:
                if field_name not in finals:
                    finals[field_name] = np.empty(values.shape[1:], dtype=values.dtype)
                    final_filled[field_name] = np.zeros(state_count, dtype=bool)
                    metadata[field_name] = (
                        entity_ids.copy(),
                        field.standard_unit,
                        field.conversion_id,
                        field.source_field_name,
                    )
                elif finals[field_name].shape != values.shape[1:]:
                    raise AssessmentError(f"adapter field {field_name} changes shape between chunks")
                elif not np.array_equal(metadata[field_name][0], entity_ids):
                    raise AssessmentError(f"adapter field {field_name} changes entity identity")
                if np.any(final_filled[field_name][indexes]):
                    raise AssessmentError(f"adapter field {field_name} repeats a state")
                final_filled[field_name][indexes] = True
                final_positions = np.flatnonzero(indexes == state_count - 1)
                if final_positions.size:
                    finals[field_name][...] = values[int(final_positions[0])]
            else:
                for derived_name, state_values in _response_field_arrays(
                    field_name, values
                ).items():
                    if state_values.shape != (indexes.size, entity_ids.size):
                        raise AssessmentError(
                            f"derived field {derived_name} has inconsistent dimensions"
                        )
                    if derived_name not in peaks:
                        peaks[derived_name] = np.full(
                            entity_ids.size, -np.inf, dtype=float
                        )
                        peak_filled[derived_name] = np.zeros(state_count, dtype=bool)
                        metadata[derived_name] = (
                            entity_ids.copy(),
                            field.standard_unit,
                            field.conversion_id,
                            field.source_field_name,
                        )
                    elif not np.array_equal(metadata[derived_name][0], entity_ids):
                        raise AssessmentError(
                            f"adapter field {field_name} changes entity identity"
                        )
                    if np.any(peak_filled[derived_name][indexes]):
                        raise AssessmentError(f"adapter field {field_name} repeats a state")
                    peaks[derived_name] = np.maximum(
                        peaks[derived_name],
                        np.max(np.asarray(state_values, dtype=float), axis=0),
                    )
                    peak_filled[derived_name][indexes] = True
            existing = times[indexes]
            if np.any(np.isfinite(existing) & ~np.isclose(existing, chunk_times, rtol=1e-10, atol=1e-12)):
                raise AssessmentError("adapter state times disagree between fields")
            times[indexes] = chunk_times
    if not np.all(np.isfinite(times)):
        raise AssessmentError("adapter did not provide a complete finite time vector")
    if np.any(np.diff(times) < 0.0):
        raise AssessmentError("adapter state times decrease")
    result: dict[str, _CollectedField] = {}
    for name, values in buffers.items():
        if not np.all(filled[name]):
            raise AssessmentError(f"adapter field {name} is incomplete")
        entity_ids, unit, conversion, source_name = metadata[name]
        result[name] = _CollectedField(
            values,
            entity_ids.copy(),
            unit,
            conversion,
            source_name,
        )
    for name, values in finals.items():
        if not np.all(final_filled[name]):
            raise AssessmentError(f"adapter field {name} is incomplete")
        entity_ids, unit, conversion, source_name = metadata[name]
        result[name] = _CollectedField(
            values, entity_ids.copy(), unit, conversion, source_name
        )
    for name, values in peaks.items():
        if not np.all(peak_filled[name]):
            raise AssessmentError(f"adapter field {name} is incomplete")
        entity_ids, unit, conversion, source_name = metadata[name]
        result[name] = _CollectedField(
            values, entity_ids.copy(), unit, conversion, source_name
        )
    times.setflags(write=False)
    return times, MappingProxyType(result)


def _common_facts(probe: AdapterProbe, semantics: ModelSemantics, final_time: float | None) -> CommonGateFacts:
    target = probe.solver_quality.termination_time or probe.solver_quality.problem_time
    preliminary = (
        not semantics.engineering_validated
        or any(not capability.engineering_validated for capability in semantics.materials.values())
    )
    return CommonGateFacts(
        termination=probe.solver_quality.termination,
        final_time=final_time,
        target_time=target,
        units_known=semantics.unit_system == "SI_m_s_kg_N_Pa",
        evidence_unchanged=True,
        request_schema_supported=True,
        legacy_inference=semantics.legacy or bool(semantics.inferences),
        preliminary_materials=preliminary,
    )


def _gate_decisions(
    probe: AdapterProbe,
    semantics: ModelSemantics,
) -> tuple[GateDecision, GateDecision]:
    final_time = probe.solver_quality.final_state_time
    common = _common_facts(probe, semantics, final_time)
    geometry_part_ids: set[int] = set()
    if probe.geometry is not None:
        geometry_part_ids = {
            int(part_id)
            for values in probe.geometry.part_ids.values()
            for part_id in np.asarray(values, dtype=np.int64)
        }
    building_identity = (
        probe.geometry is not None
        and bool(semantics.components)
        and not semantics.building_blockers
        and all(
            bool(set(component.part_ids) & geometry_part_ids)
            for component in semantics.components
        )
    )
    ground_identity = (
        probe.geometry is not None
        and semantics.ground is not None
        and not semantics.ground_blockers
        and bool(set(semantics.ground.part_ids) & geometry_part_ids)
    )
    building = evaluate_building_gate(
        BuildingGateFacts(
            common,
            identity_available=building_identity,
            deformation_available=_available(probe, "node_displacement"),
            stress_available=_available(probe, "solid_stress") or _available(probe, "shell_stress"),
            strain_available=_available(probe, "solid_effective_plastic_strain") or _available(probe, "shell_strain"),
            importance_explicit=semantics.importance_explicit,
        )
    )
    ground_capability = None
    if semantics.ground is not None:
        ground_capability = next(
            (semantics.materials.get(material_id) for material_id in semantics.ground.material_ids if material_id in semantics.materials),
            None,
        )
    material_available = bool(
        ground_capability is not None
        and set(ground_capability.supported_metrics)
        & {"scaled_damage_measure", "effective_plastic_strain", "plastic_damage"}
    )
    ground = evaluate_ground_gate(
        GroundGateFacts(
            common,
            identity_available=ground_identity,
            deformation_available=_available(probe, "node_displacement"),
            velocity_available=_available(probe, "node_velocity"),
            material_damage_available=material_available,
        )
    )
    return building, ground


def _require_pipeline_rule_contract(building: RulePack, ground: RulePack) -> None:
    if building.subject != "building" or ground.subject != "ground":
        raise ContractError("rule-pack subject does not match its assessment request slot")
    required = (
        (building, ("building_relative_deformation_ratio",)),
        (
            ground,
            (
                "ground_depth_to_median_surface_cell",
                "ground_connected_area_in_surface_cells",
            ),
        ),
    )
    for pack, rule_ids in required:
        available = {str(rule["id"]) for rule in pack.rules}
        missing = [rule_id for rule_id in rule_ids if rule_id not in available]
        if missing:
            raise ContractError(
                f"rule pack {pack.pack_id} does not provide required rule {missing[0]}"
            )


def _rule_subject(
    semantics: ModelSemantics,
    probe: AdapterProbe,
    subject: str,
) -> Mapping[str, object]:
    if subject == "building":
        material_ids = sorted(
            {
                material_id
                for component in semantics.components
                for material_id in component.material_ids
            }
        )
        return {
            "unit_system": semantics.unit_system,
            "material_ids": material_ids,
            "node_kinematics_available": _available(probe, "node_displacement"),
            "component_geometry_available": probe.geometry is not None and bool(semantics.components),
            "stress_available": _available(probe, "solid_stress") or _available(probe, "shell_stress"),
            "declared_material_strength_available": any(
                semantics.materials[material_id].yield_stress_pa is not None
                for material_id in material_ids
            ),
        }
    ground = semantics.ground
    return {
        "unit_system": semantics.unit_system,
        "material_ids": [] if ground is None else list(ground.material_ids),
        "geometry_assumptions": (
            {} if ground is None else {"surface_axis": ground.surface_axis}
        ),
        "ground_surface_identity": ground is not None and probe.geometry is not None,
        "surface_identity": ground is not None and probe.geometry is not None,
        "node_kinematics_available": _available(probe, "node_displacement"),
        "median_surface_cell_available": ground is not None and probe.geometry is not None,
        "connected_region_available": ground is not None and probe.geometry is not None,
    }


def _apply_rule_applicability(
    gate: GateDecision,
    semantics: ModelSemantics,
    probe: AdapterProbe,
    pack: RulePack,
) -> GateDecision:
    if not pack.formal_eligible:
        return gate
    result = check_rule_applicability(pack, _rule_subject(semantics, probe, pack.subject))
    if semantics.formal_eligible and result.applicable:
        return gate
    subject = pack.subject
    return gate.degrade(
        GateState.PROVISIONAL,
        Issue(
            f"{subject}.rule_applicability",
            "Formal rule-pack bindings or applicability predicates do not match the assessed subject",
            {
                "subject_id": subject,
                "gate_state": "provisional",
                "source_evidence_ids": ("semantic_manifest", "rule_snapshot"),
                "affected_metrics": (f"{subject}_severity",),
                "remediation": "Declare and review every rule binding and applicability predicate for this subject.",
                "missing": result.missing,
                "mismatches": result.mismatches,
                "semantic_formal_eligible": semantics.formal_eligible,
            },
        ),
    )


def _component_response_metrics(
    semantics: ModelSemantics,
    component,
    geometry: GeometryIndex,
    fields: Mapping[str, _CollectedField],
    kind: EntityKind,
    mask: np.ndarray,
    rules: RulePack,
) -> tuple[Mapping[str, float], np.ndarray | None]:
    expected_ids = np.asarray(geometry.element_ids[kind], dtype=np.int64)

    def selected(name: str) -> np.ndarray | None:
        field = fields.get(name)
        if field is None:
            return None
        if not np.array_equal(field.entity_ids, expected_ids):
            raise AssessmentError(f"building response field {name} has mismatched element IDs")
        values = np.asarray(field.values, dtype=float)
        if values.shape != expected_ids.shape:
            raise AssessmentError(f"building response field {name} is not a per-entity peak")
        return values[mask]

    response: dict[str, float] = {}
    prefix = kind.value
    von_mises = selected(f"{prefix}_von_mises_stress_pa")
    principal = selected(f"{prefix}_maximum_principal_stress_pa")
    if von_mises is not None:
        response[f"{prefix}_peak_von_mises_stress_pa"] = float(np.max(von_mises))
    if principal is not None:
        response[f"{prefix}_peak_maximum_principal_stress_pa"] = float(np.max(principal))

    capabilities = [
        semantics.materials[material_id]
        for material_id in component.material_ids
    ]
    strengths = [
        capability.yield_stress_pa
        for capability in capabilities
        if capability.yield_stress_pa is not None
    ]
    corroborating = None
    if von_mises is not None and len(strengths) == 1:
        utilization = von_mises / float(strengths[0])
        response[f"{prefix}_peak_stress_to_declared_yield_ratio"] = float(
            np.max(utilization)
        )
        try:
            stress_rule = rules.rule("building_stress_to_declared_yield_ratio")
        except KeyError:
            stress_rule = None
        if stress_rule is not None:
            threshold = float(stress_rule["bands"][0])
            corroborating = np.where(utilization >= threshold, utilization, 0.0)

    history = selected(f"{prefix}_history_variable_0")
    damage_capabilities = [
        capability
        for capability in capabilities
        if capability.history_meanings.get(0) == "scaled_damage_measure"
    ]
    if history is not None and len(damage_capabilities) == 1:
        response[f"{prefix}_scaled_damage_measure"] = float(np.max(history))

    effective_plastic_strain = selected(
        f"{prefix}_effective_plastic_strain"
    )
    plastic_capabilities = [
        capability
        for capability in capabilities
        if "effective_plastic_strain" in capability.supported_metrics
    ]
    if effective_plastic_strain is not None and len(plastic_capabilities) == 1:
        response[f"{prefix}_effective_plastic_strain"] = float(
            np.max(effective_plastic_strain)
        )

    if kind is EntityKind.SHELL:
        strain = selected("shell_strain")
        if strain is not None:
            response["shell_peak_strain"] = float(np.max(strain))
    if kind is EntityKind.BEAM:
        for field_name, metric_name in (
            ("beam_axial_force_n", "beam_peak_axial_force_n"),
            ("beam_shear_force_n", "beam_peak_shear_force_n"),
        ):
            values = selected(field_name)
            if values is not None:
                response[metric_name] = float(np.max(values))
    return MappingProxyType(response), corroborating




def _element_alive(fields: Mapping[str, _CollectedField], kind: EntityKind, mask: np.ndarray) -> np.ndarray | None:
    name = f"{kind.value}_is_alive"
    field = fields.get(name)
    if field is None:
        return None
    values = np.asarray(field.values)
    if values.ndim > 1:
        values = np.all(values.astype(bool), axis=tuple(range(1, values.ndim)))
    if values.shape != mask.shape:
        raise AssessmentError(f"building alive field {name} has mismatched element IDs")
    return np.asarray(values[mask], dtype=bool)


def _merge_component_evaluations(values: list[ComponentEvaluation]) -> ComponentEvaluation:
    if len(values) == 1:
        return values[0]
    governing = max(
        values,
        key=lambda item: (int(item.severity), item.governing_relative_deformation, item.connected_deleted_count),
    )
    total_weight = sum(max(1, item.connected_affected_count) for item in values)
    affected = sum(item.affected_fraction * max(1, item.connected_affected_count) for item in values) / total_weight
    response_metrics: dict[str, float] = {}
    for item in values:
        for name, metric_value in item.response_metrics.items():
            response_metrics[name] = max(response_metrics.get(name, float("-inf")), metric_value)
    return replace(
        governing,
        component_id=values[0].component_id,
        gate=combine_gate_states(*(item.gate for item in values)),
        severity=max(item.severity for item in values),
        p99_relative_deformation=max(item.p99_relative_deformation for item in values),
        governing_relative_deformation=max(item.governing_relative_deformation for item in values),
        affected_fraction=affected,
        connected_affected_count=sum(item.connected_affected_count for item in values),
        connected_deleted_count=sum(item.connected_deleted_count for item in values),
        anomalies=tuple(issue for item in values for issue in item.anomalies),
        rule_hits=tuple(sorted({hit for item in values for hit in item.rule_hits})),
        response_metrics=response_metrics,
        rule_evidence=tuple(evidence for item in values for evidence in item.rule_evidence),
    )


def _evaluate_building_subject(
    semantics: ModelSemantics,
    geometry: GeometryIndex,
    times: np.ndarray,
    fields: Mapping[str, _CollectedField],
    rules: RulePack,
    gate: GateDecision,
) -> BuildingEvaluation | _BlockedSubject:
    if gate.state is GateState.BLOCKED:
        return _BlockedSubject()
    displacement = fields.get("node_displacement_m")
    if displacement is None:
        return _BlockedSubject()
    state_values = np.asarray(displacement.values, dtype=float)
    components: list[ComponentEvaluation] = []
    for component in semantics.components:
        per_kind: list[ComponentEvaluation] = []
        for kind in (EntityKind.SOLID, EntityKind.SHELL, EntityKind.BEAM):
            part_ids = np.asarray(geometry.part_ids.get(kind, ()), dtype=np.int64)
            mask = np.isin(part_ids, np.asarray(component.part_ids, dtype=np.int64))
            if not np.any(mask):
                continue
            connectivity = np.asarray(geometry.connectivity[kind], dtype=np.int64)[mask]
            entity_ids = np.asarray(geometry.element_ids[kind], dtype=np.int64)[mask]
            node_indexes = np.unique(connectivity.ravel())
            local_lookup = {int(value): index for index, value in enumerate(node_indexes)}
            local_connectivity = np.asarray(
                [[local_lookup[int(value)] for value in row] for row in connectivity], dtype=np.int64
            )
            accumulator = BuildingAccumulator(entity_ids)
            adjacency = build_element_adjacency(local_connectivity, kind.value)
            threshold = float(rules.rule("building_relative_deformation_ratio")["bands"][0])
            previous_affected: np.ndarray | None = None
            persistent_mask = np.zeros(entity_ids.size, dtype=bool)
            persistent_values = np.zeros(entity_ids.size, dtype=float)
            persistent_key: tuple[int, float, int] = (0, 0.0, 0)
            inferred = False
            for state_index, time in enumerate(times):
                relative = relative_deformation(
                    geometry.initial_coordinates[node_indexes],
                    state_values[state_index, node_indexes],
                )
                inferred = inferred or relative.reference_motion_inferred
                element_values = np.max(relative.ratios[local_connectivity], axis=1)
                accumulator.update(state_index, float(time), element_values)
                affected = element_values >= threshold
                if previous_affected is not None:
                    candidate_mask = affected & previous_affected
                    candidate_region = largest_connected_region(
                        candidate_mask, adjacency, entity_ids
                    )
                    candidate_peak = max(
                        (
                            float(element_values[index])
                            for index in candidate_region.indexes
                        ),
                        default=0.0,
                    )
                    candidate_key = (
                        candidate_region.size,
                        candidate_peak,
                        -state_index,
                    )
                    if candidate_key > persistent_key:
                        persistent_key = candidate_key
                        persistent_mask[:] = False
                        persistent_mask[list(candidate_region.indexes)] = True
                        persistent_values = element_values.copy()
                previous_affected = affected
            summary = accumulator.summary(affected_threshold=threshold)
            alive = _element_alive(fields, kind, mask)
            final_alive = alive
            deleted_ids = entity_ids if final_alive is None else entity_ids[~final_alive]
            response_metrics, corroborating_material_metric = (
                _component_response_metrics(
                    semantics,
                    component,
                    geometry,
                    fields,
                    kind,
                    mask,
                    rules,
                )
            )
            per_kind.append(
                evaluate_component(
                    ComponentEvaluationInput(
                        component,
                        entity_ids,
                        summary.peak_by_entity,
                        connectivity,
                        kind.value,
                        support_semantics_explicit=False,
                        load_path_semantics_explicit=not semantics.legacy,
                        material_metric=corroborating_material_metric,
                        response_metrics=response_metrics,
                        alive=final_alive,
                        reference_motion_inferred=inferred,
                        connected_affected=persistent_mask,
                        connected_metric=persistent_values,
                        deformation_entity_id=summary.extreme_entity_id,
                        deformation_state_index=summary.extreme_time_index,
                        deformation_time=summary.extreme_time,
                        deletion_entity_id=(
                            None if deleted_ids.size == 0 else int(np.min(deleted_ids))
                        ),
                        deletion_state_index=int(times.size - 1),
                        deletion_time=float(times[-1]),
                    ),
                    rules,
                )
            )
        if per_kind:
            components.append(_merge_component_evaluations(per_kind))
    if len(components) != len(semantics.components):
        return _BlockedSubject()
    result = evaluate_building(tuple(components))
    return replace(result, gate=combine_gate_states(result.gate, gate.state))


def _surface_state_values(surface, values: np.ndarray, vertical: int) -> np.ndarray:
    return np.asarray(
        [
            [float(np.mean(values[state, list(cell.node_indexes), vertical])) for cell in surface.cells]
            for state in range(values.shape[0])
        ],
        dtype=float,
    )


def _surface_speed_values(surface, values: np.ndarray) -> np.ndarray:
    magnitudes = np.linalg.norm(values, axis=-1)
    return np.asarray(
        [
            [float(np.mean(magnitudes[state, list(cell.node_indexes)])) for cell in surface.cells]
            for state in range(values.shape[0])
        ],
        dtype=float,
    )


def _evaluate_ground_subject(
    semantics: ModelSemantics,
    geometry: GeometryIndex,
    times: np.ndarray,
    fields: Mapping[str, _CollectedField],
    rules: RulePack,
    gate: GateDecision,
) -> GroundEvaluation | _BlockedSubject:
    if gate.state is GateState.BLOCKED or semantics.ground is None:
        return _BlockedSubject()
    displacement = fields.get("node_displacement_m")
    if displacement is None:
        return _BlockedSubject()
    try:
        surface = extract_initial_surface(
            geometry.initial_coordinates,
            np.asarray(geometry.connectivity[EntityKind.SOLID], dtype=np.int64),
            np.asarray(geometry.part_ids[EntityKind.SOLID], dtype=np.int64),
            semantics.ground.part_ids,
            semantics.blast_center_m,
            vertical_axis=semantics.vertical_axis,
            surface_direction=semantics.ground.surface_direction,
            inferred=semantics.legacy,
        )
    except ContractError:
        return _BlockedSubject()
    vertical = {"x": 0, "y": 1, "z": 2}[semantics.vertical_axis]
    shape_values = _surface_state_values(surface, np.asarray(displacement.values, dtype=float), vertical)
    velocity = fields.get("node_velocity_m_per_s")
    speed_values = None if velocity is None else _surface_speed_values(surface, np.asarray(velocity.values, dtype=float))
    capability = next(
        (semantics.materials[material_id] for material_id in semantics.ground.material_ids if material_id in semantics.materials),
        None,
    )
    if capability is None:
        return _BlockedSubject()
    source_indexes = [cell.source_element_index for cell in surface.cells]
    if any(index is None for index in source_indexes):
        raise AssessmentError("ground surface cells lost their source element identity")
    material_metric = None
    material_metric_name = None
    material_candidates = (
        ("scaled_damage_measure", "solid_history_variable_0"),
        ("effective_plastic_strain", "solid_effective_plastic_strain"),
    )
    for meaning, field_name in material_candidates:
        field = fields.get(field_name)
        if meaning not in capability.supported_metrics or field is None:
            continue
        expected_ids = np.asarray(geometry.element_ids[EntityKind.SOLID], dtype=np.int64)
        if not np.array_equal(field.entity_ids, expected_ids):
            raise AssessmentError(f"ground material field {field_name} has mismatched element IDs")
        material_metric = np.asarray(field.values, dtype=float)[source_indexes]
        material_metric_name = meaning
        break
    alive_field = fields.get("solid_is_alive")
    ground_alive = None
    if alive_field is not None:
        alive_values = np.asarray(alive_field.values)
        if alive_values.ndim > 1:
            alive_values = np.all(alive_values.astype(bool), axis=tuple(range(1, alive_values.ndim)))
        expected_ids = np.asarray(geometry.element_ids[EntityKind.SOLID], dtype=np.int64)
        if alive_values.shape != expected_ids.shape or not np.array_equal(alive_field.entity_ids, expected_ids):
            raise AssessmentError("ground alive field has mismatched element IDs")
        ground_alive = np.asarray(alive_values[source_indexes], dtype=bool)

    result = evaluate_ground(
        GroundEvaluationInput(
            surface,
            times,
            shape_values,
            speed_values,
            capability,
            material_metric=material_metric,
            material_metric_name=material_metric_name,
            alive=ground_alive,
        ),
        rules,
    )
    return replace(result, gate=combine_gate_states(result.gate, gate.state))


def _issue_record(issue: Issue) -> dict[str, object]:
    return {"code": issue.code, "message": issue.message, "details": dict(issue.details)}


def _component_record(component: ComponentEvaluation) -> dict[str, object]:
    return {
        "component_id": component.component_id,
        "zone_id": component.zone_id,
        "importance_class": component.importance_class,
        "primary_load_path": component.primary_load_path,
        "gate": component.gate.value,
        "severity": int(component.severity),
        "p99_relative_deformation": component.p99_relative_deformation,
        "governing_relative_deformation": component.governing_relative_deformation,
        "affected_fraction": component.affected_fraction,
        "connected_affected_count": component.connected_affected_count,
        "connected_deleted_count": component.connected_deleted_count,
        "response_metrics": dict(sorted(component.response_metrics.items())),
        "rule_hits": list(component.rule_hits),
        "anomalies": [_issue_record(issue) for issue in component.anomalies],
    }


def _region_record(region) -> dict[str, object]:
    return {
        "maximum_depth": region.maximum_depth,
        "maximum_height": region.maximum_height,
        "plan_area": region.plan_area,
        "equivalent_diameter": region.equivalent_diameter,
        "signed_prism_volume": region.signed_prism_volume,
        "affected_cell_count": region.affected_cell_count,
        "radial_rings": [
            {
                "ring_index": item.ring_index,
                "inner_radius": item.inner_radius,
                "outer_radius": item.outer_radius,
                "cell_count": item.cell_count,
                "mean_signed_displacement": item.mean_signed_displacement,
            }
            for item in region.radial_rings
        ],
    }


def _shape_record(shape) -> dict[str, object]:
    return {
        "crater": _region_record(shape.crater),
        "uplift": _region_record(shape.uplift),
        "settlement": _region_record(shape.settlement),
    }


def _subject_records(
    building: BuildingEvaluation | _BlockedSubject,
    ground: GroundEvaluation | _BlockedSubject,
    building_gate: GateDecision,
    ground_gate: GateDecision,
) -> tuple[dict[str, object], dict[str, object]]:
    if isinstance(building, BuildingEvaluation):
        building_record: dict[str, object] = {
            "gate": building.gate.value,
            "severity": int(building.severity),
            "class_severities": {key: int(value) for key, value in building.class_severities.items()},
            "zone_severities": {key: int(value) for key, value in building.zone_severities.items()},
            "components": [_component_record(item) for item in building.components],
            "issues": [_issue_record(issue) for issue in building_gate.issues],
        }
    else:
        building_record = {
            "gate": "blocked",
            "severity": None,
            "class_severities": {},
            "zone_severities": {},
            "components": [],
            "issues": [_issue_record(issue) for issue in building_gate.issues],
        }
    if isinstance(ground, GroundEvaluation):
        ground_record: dict[str, object] = {
            "gate": ground.gate.value,
            "severity": int(ground.severity),
            "peak": _shape_record(ground.peak),
            "final": _shape_record(ground.final),
            "material_metrics": dict(sorted(ground.material_metrics.items())),
            "stability": {
                "stable": ground.stability.stable,
                "shape_term": ground.stability.shape_term,
                "failed_criteria": list(ground.stability.failed_criteria),
                "tail_state_count": ground.stability.tail_state_count,
            },
            "subratings": {
                name: {
                    "available": item.available,
                    "severity": None if item.severity is None else int(item.severity),
                    "reason": item.reason,
                    "rule_hits": list(item.rule_hits),
                    "metric_name": item.metric_name,
                    "actual_value": item.actual_value,
                    "limit_value": item.limit_value,
                    "operator": item.operator,
                }
                for name, item in ground.subratings.items()
            },
            "issues": [_issue_record(issue) for issue in ground_gate.issues],
        }
    else:
        ground_record = {
            "gate": "blocked",
            "severity": None,
            "peak": None,
            "final": None,
            "material_metrics": {},
            "stability": None,
            "subratings": {},
            "issues": [_issue_record(issue) for issue in ground_gate.issues],
        }
    return building_record, ground_record


def _source_id(item: EvidenceFile, index: int) -> str:
    return f"source:{index}:{hashlib.sha256(item.relative_path.encode('utf-8')).hexdigest()[:12]}"


def _build_evidence_graph(
    source: SourceEvidence,
    times: np.ndarray | None,
    fields: Mapping[str, _CollectedField],
    building: BuildingEvaluation | _BlockedSubject,
    ground: GroundEvaluation | _BlockedSubject,
    aggregate: AggregateAssessment,
) -> EvidenceGraph:
    graph = EvidenceGraph()
    d3plot_source: str | None = None
    for index, item in enumerate(source.files):
        node_id = _source_id(item, index)
        graph.add_source(node_id, path=item.relative_path, sha256=item.sha256)
        if item.relative_path == "d3plot":
            d3plot_source = node_id
    field_ids: dict[str, str] = {}
    if d3plot_source is not None:
        for name, field in sorted(fields.items()):
            field_ids[name] = f"field:{name}"
            graph.add_field(field_ids[name], source_id=d3plot_source, field_name=field.source_field_name)
    field_id = field_ids.get("node_displacement_m")

    local_ids: dict[str, list[tuple[str, Severity]]] = {"building": [], "ground": []}
    if field_id is not None and times is not None and isinstance(building, BuildingEvaluation):
        for index, component in enumerate(building.components):
            governing = tuple(
                item
                for item in component.rule_evidence
                if item.severity == component.severity
            )
            if not governing:
                raise AssessmentError(
                    f"component {component.component_id} has no evidence for its reported severity"
                )
            hit_ids: list[str] = []
            for evidence_index, item in enumerate(governing):
                evidence_field_id = field_ids.get(item.field_name)
                if evidence_field_id is None:
                    raise AssessmentError(
                        f"evidence field is unavailable for building rule {item.rule_id}"
                    )
                observation_id = f"observation:building:{index}:{evidence_index}"
                graph.add_observation(
                    observation_id,
                    field_id=evidence_field_id,
                    entity_type="component_element",
                    entity_id=item.entity_id,
                    state_index=item.state_index,
                    time=item.time,
                )
                metric_id = f"metric:building:{index}:{evidence_index}"
                unit = (
                    "element"
                    if item.metric_name == "connected_deleted_element_count"
                    else "1"
                )
                graph.add_metric(
                    metric_id,
                    observation_ids=(observation_id,),
                    metric_name=item.metric_name,
                    raw_value=item.actual_value,
                    raw_unit=unit,
                    standard_value=item.actual_value,
                    standard_unit=unit,
                    conversion_id=(
                        "metric.relative_deformation@1"
                        if item.metric_name == "building_relative_deformation_ratio"
                        else "units.identity@1"
                    ),
                )
                hit_id = f"rule-hit:building:{index}:{evidence_index}"
                graph.add_rule_hit(
                    hit_id,
                    metric_id=metric_id,
                    rule_id=item.rule_id,
                    actual_value=item.actual_value,
                    limit_value=item.limit_value,
                    operator=item.operator,
                    severity=item.severity,
                )
                hit_ids.append(hit_id)
            local_id = f"local:building:{index}"
            graph.add_local_severity(
                local_id,
                rule_hit_ids=hit_ids,
                subject_id=f"building:{component.component_id}",
                severity=component.severity,
            )
            local_ids["building"].append((local_id, component.severity))
    if field_id is not None and times is not None and isinstance(ground, GroundEvaluation):
        for index, (name, rating) in enumerate(sorted(ground.subratings.items())):
            if not rating.available or rating.severity is None or rating.actual_value is None or rating.limit_value is None:
                continue
            rating_field_id = field_ids.get("solid_is_alive") if name == "numerical_erosion" else field_id
            if rating_field_id is None:
                raise AssessmentError(f"evidence field is unavailable for ground subrating {name}")

            observations = []
            for state_index, time in enumerate(times):
                observation_id = f"observation:ground:{index}:{state_index}"
                graph.add_observation(
                    observation_id,
                    field_id=rating_field_id,
                    entity_type="ground_surface",
                    entity_id=name,
                    state_index=state_index,
                    time=float(time),
                )
                observations.append(observation_id)
            metric_id = f"metric:ground:{index}"
            unit = "surface_cell" if "connected" in str(rating.metric_name) else "1"
            graph.add_metric(
                metric_id,
                observation_ids=observations,
                metric_name=str(rating.metric_name),
                raw_value=rating.actual_value,
                raw_unit=unit,
                standard_value=rating.actual_value,
                standard_unit=unit,
                conversion_id="units.identity@1",
            )
            hit_id = f"rule-hit:ground:{index}"
            graph.add_rule_hit(
                hit_id,
                metric_id=metric_id,
                rule_id=str(rating.metric_name),
                actual_value=rating.actual_value,
                limit_value=rating.limit_value,
                operator=rating.operator or ">=",
                severity=rating.severity,
            )
            local_id = f"local:ground:{index}"
            graph.add_local_severity(
                local_id,
                rule_hit_ids=(hit_id,),
                subject_id=f"ground:{name}",
                severity=rating.severity,
            )
            local_ids["ground"].append((local_id, rating.severity))
    if aggregate.severity is not None:
        governing_locals = [
            node_id
            for subject in aggregate.governing_subjects
            for node_id, severity in local_ids[subject]
            if severity == aggregate.severity
        ]
        if governing_locals:
            graph.add_aggregate_severity(
                "aggregate:overall",
                local_severity_ids=governing_locals,
                severity=aggregate.severity,
            )
    validate_evidence_graph(graph)
    return graph


def _artifact_reference(name: str, data: bytes, media_type: str, schema: str | None = None) -> ArtifactReference:
    return ArtifactReference(
        Path(name),
        hashlib.sha256(data).hexdigest(),
        media_type,
        len(data),
        schema,
    )


def _reference_record(reference: ArtifactReference) -> dict[str, object]:
    return {
        "path": reference.path.as_posix(),
        "sha256": reference.sha256,
        "media_type": reference.media_type,
        "size_bytes": reference.size_bytes,
        "schema_version": reference.schema_version,
    }


def _portable_manifest_path(source: SourceEvidence) -> str:
    try:
        relative = source.manifest_path.relative_to(source.result_dir)
    except ValueError:
        return f"source/semantic_manifest_parent/{source.manifest_path.name}"
    return f"source/result_dir/{relative.as_posix()}"


def _normalized_request_record(request: AssessmentRequest, source: SourceEvidence) -> dict[str, object]:
    """Persist a reproducible request snapshot without host-specific absolute paths."""

    return {
        "schema_version": request.schema_version,
        "project_id": request.project_id,
        "case_id": request.case_id,
        "result_dir": "source/result_dir",
        "semantic_manifest": {
            "path": _portable_manifest_path(source),
            "sha256": request.semantic_manifest.sha256,
            "schema_version": request.semantic_manifest.schema_version,
        },
        "building_rule_pack": request.building_rule_pack,
        "ground_rule_pack": request.ground_rule_pack,
        "output_dir": f"output/{source.output_dir.name}",
        "state_chunk_size": request.state_chunk_size,
        "input_files": [
            {
                "relative_path": item.relative_path,
                "role": item.role,
                "root_role": item.root_role,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256,
            }
            for item in source.files
        ],
    }


def _dedupe_issues(issues: Iterable[Issue]) -> tuple[Issue, ...]:
    result: list[Issue] = []
    seen: set[tuple[str, str]] = set()
    for issue in issues:
        key = (issue.code, issue.message)
        if key not in seen:
            seen.add(key)
            result.append(issue)
    return tuple(result)


def run_pipeline(raw_request: object, *, adapter: ResultAdapter | None = None) -> AssessmentResult:
    request = parse_request(raw_request)  # type: ignore[arg-type]
    source = inspect_source(request)
    building_rules = load_rule_pack(request.building_rule_pack)
    ground_rules = load_rule_pack(request.ground_rule_pack)
    _require_pipeline_rule_contract(building_rules, ground_rules)
    manifest_reference = FileReference(
        source.manifest_path,
        request.semantic_manifest.sha256,
        request.semantic_manifest.schema_version,
    )
    semantics = load_semantics(manifest_reference)
    active_adapter = adapter or LsdynaResultAdapter()
    try:
        probe = active_adapter.probe(source.result_dir)
    except Exception as exc:
        raise AssessmentError(f"result adapter probe failed: {exc}") from exc
    building_gate, ground_gate = _gate_decisions(probe, semantics)
    times: np.ndarray | None = None
    fields: Mapping[str, _CollectedField] = MappingProxyType({})
    needs_time_backfill = (
        probe.solver_quality.final_state_time is None
        and probe.state_count > 0
        and _available(probe, "node_displacement")
    )
    if probe.geometry is not None and (
        building_gate.state is not GateState.BLOCKED or ground_gate.state is not GateState.BLOCKED or needs_time_backfill
    ):
        try:
            times, fields = _collect_fields(
                active_adapter,
                source.result_dir,
                probe.state_count,
                request.state_chunk_size,
            )
        except Exception as exc:
            raise AssessmentError(f"result adapter state read failed: {exc}") from exc
        if probe.solver_quality.final_state_time is None:
            quality = replace(probe.solver_quality, final_state_time=float(times[-1]))
            effective_probe = replace(probe, solver_quality=quality)
            building_gate, ground_gate = _gate_decisions(effective_probe, semantics)
            probe = effective_probe

    building_gate = _apply_rule_applicability(building_gate, semantics, probe, building_rules)
    ground_gate = _apply_rule_applicability(ground_gate, semantics, probe, ground_rules)
    geometry = probe.geometry
    building: BuildingEvaluation | _BlockedSubject = _BlockedSubject()
    ground: GroundEvaluation | _BlockedSubject = _BlockedSubject()
    if geometry is not None and times is not None:
        building = _evaluate_building_subject(semantics, geometry, times, fields, building_rules, building_gate)
        ground = _evaluate_ground_subject(semantics, geometry, times, fields, ground_rules, ground_gate)
    if isinstance(building, _BlockedSubject) and building_gate.state is not GateState.BLOCKED:
        building_gate = building_gate.degrade(
            GateState.BLOCKED,
            Issue(
                "building.geometry_missing",
                "One or more declared building components have no assessable result geometry",
                {
                    "subject_id": "building",
                    "gate_state": "blocked",
                    "source_evidence_ids": ("semantic_manifest", "d3plot"),
                    "affected_metrics": ("building_severity",),
                    "remediation": "Align declared component Part IDs with the solver result geometry.",
                },
            ),
        )
    if isinstance(ground, _BlockedSubject) and ground_gate.state is not GateState.BLOCKED:
        ground_gate = ground_gate.degrade(
            GateState.BLOCKED,
            Issue(
                "ground.surface_invalid",
                "The declared ground surface could not be evaluated from result geometry",
                {
                    "subject_id": "ground",
                    "gate_state": "blocked",
                    "source_evidence_ids": ("semantic_manifest", "d3plot"),
                    "affected_metrics": ("ground_severity",),
                    "remediation": "Verify the ground Part, solid topology, vertical axis, and blast projection.",
                },
            ),
        )

    aggregate = aggregate_assessment(building, ground)
    building_record, ground_record = _subject_records(building, ground, building_gate, ground_gate)
    building_snapshot = snapshot_rule_pack(building_rules)
    ground_snapshot = snapshot_rule_pack(ground_rules)
    identity = {
        "request_schema": request.schema_version,
        "project_id": request.project_id,
        "case_id": request.case_id,
        "semantic_manifest_sha256": request.semantic_manifest.sha256,
        "input_hashes": [item.sha256 for item in source.files],
        "adapter_id": probe.adapter_id,
        "adapter_version": probe.adapter_version,
        "building_rule_sha256": building_snapshot.sha256,
        "ground_rule_sha256": ground_snapshot.sha256,
    }
    assessment_id = sha256_json(identity)[:24]
    all_gate_issues = building_gate.issues + ground_gate.issues
    blockers = _dedupe_issues(
        (*semantics.building_blockers, *semantics.ground_blockers, *(issue for issue in all_gate_issues if issue.details.get("gate_state") == "blocked"))
    )
    warnings = _dedupe_issues((*probe.solver_quality.issues, *semantics.warnings))
    review_issues = _dedupe_issues(
        issue for issue in all_gate_issues if issue.details.get("gate_state") == "provisional"
    )
    limitations = [issue.message for issue in review_issues]
    for pack in (building_rules, ground_rules):
        if not pack.formal_eligible:
            limitations.append(f"规则包 {pack.pack_id} 为研究参考，不具备正式工程定级资格")
    missing_fields = sorted(name for name, value in probe.fields.items() if not value.available)
    inference_records = [f"{item.field}: {item.reason}" for item in semantics.inferences]
    review_items = [issue.message for issue in review_issues]
    if semantics.requires_project_review:
        review_items.append("模型语义或材料参数需要项目级人工复核")
    snapshot_base: dict[str, object] = {
        "schema_version": SNAPSHOT_SCHEMA,
        "assessment_id": assessment_id,
        "identity": identity,
        "sources": [
            {
                "relative_path": item.relative_path,
                "role": item.role,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256,
            }
            for item in source.files
        ],
        "adapter": {
            "id": probe.adapter_id,
            "version": probe.adapter_version,
            "state_count": probe.state_count,
            "fields": {name: value.available for name, value in sorted(probe.fields.items())},
            "geometry": None if probe.geometry is None else {
                "node_count": int(probe.geometry.node_ids.size),
                "part_ids": [
                    int(value)
                    for value in np.unique(
                        np.concatenate(
                            [
                                np.asarray(values, dtype=np.int64)
                                for values in probe.geometry.part_ids.values()
                            ]
                        )
                    )
                ],
                "part_count": int(
                    np.unique(
                        np.concatenate(
                            [
                                np.asarray(values, dtype=np.int64)
                                for values in probe.geometry.part_ids.values()
                            ]
                        )
                    ).size
                ),
                "element_count": int(sum(values.size for values in probe.geometry.element_ids.values())),
                "element_count_by_kind": {
                    kind.value: int(probe.geometry.element_ids.get(kind, np.array([], dtype=np.int64)).size)
                    for kind in (EntityKind.SOLID, EntityKind.SHELL, EntityKind.BEAM)
                },
            },
            "solver_quality": {
                "termination": probe.solver_quality.termination,
                "problem_time": probe.solver_quality.problem_time,
                "termination_time": probe.solver_quality.termination_time,
                "final_state_time": probe.solver_quality.final_state_time,
                "max_hourglass_ratio": probe.solver_quality.max_hourglass_ratio,
            },
        },
        "overall": {
            "gate": aggregate.gate.value,
            "severity": None if aggregate.severity is None else int(aggregate.severity),
            "partial_assessment": aggregate.partial_assessment,
            "governing_subjects": list(aggregate.governing_subjects),
            "governing_rule_hits": list(aggregate.governing_rule_hits),
        },
        "building": building_record,
        "ground": ground_record,
        "limitations": limitations,
        "missing_fields": missing_fields,
        "inferences": inference_records,
        "review_items": review_items,
    }
    fingerprint = sha256_json(snapshot_base)
    snapshot = {**snapshot_base, "assessment_fingerprint": fingerprint}
    evidence_graph = _build_evidence_graph(
        source, times, fields, building, ground, aggregate
    )
    rule_record = {
        "schema_version": RULE_SNAPSHOT_SCHEMA,
        "rule_packs": [
            {
                "subject": subject,
                "pack_id": item.pack_id,
                "sha256": item.sha256,
                "payload": item.payload,
            }
            for subject, item in (("building", building_snapshot), ("ground", ground_snapshot))
        ],
    }
    request_bytes = canonical_json_bytes(_normalized_request_record(request, source))
    snapshot_bytes = canonical_json_bytes(snapshot)
    evidence_bytes = canonical_json_bytes(evidence_graph.to_dict())
    rule_bytes = canonical_json_bytes(rule_record)
    html_bytes = render_html_report(snapshot).encode("utf-8")
    building_csv = render_building_csv(snapshot)
    ground_csv = render_ground_csv(snapshot)
    payloads = {
        "assessment_request.json": (request_bytes, "application/json", request.schema_version),
        "assessment_snapshot.json": (snapshot_bytes, "application/json", SNAPSHOT_SCHEMA),
        "evidence_index.json": (evidence_bytes, "application/json", EvidenceGraph.schema_version),
        "rule_snapshot.json": (rule_bytes, "application/json", RULE_SNAPSHOT_SCHEMA),
        "damage_report.html": (html_bytes, "text/html; charset=utf-8", None),
        "building_components.csv": (building_csv, "text/csv; charset=utf-8", None),
        "ground_regions.csv": (ground_csv, "text/csv; charset=utf-8", None),
    }
    references = {
        name: _artifact_reference(name, data, media_type, schema)
        for name, (data, media_type, schema) in payloads.items()
    }
    envelope = {
        "schema_version": RESULT_SCHEMA,
        "assessment_id": assessment_id,
        "execution_status": "completed",
        "gate": aggregate.gate.value,
        "severity": None if aggregate.severity is None else int(aggregate.severity),
        "assessment_fingerprint": fingerprint,
        "state_chunk_size": request.state_chunk_size,
        "artifacts": {name: _reference_record(reference) for name, reference in sorted(references.items())},
        "warnings": [_issue_record(issue) for issue in warnings],
        "blockers": [_issue_record(issue) for issue in blockers],
        "review_items": [_issue_record(issue) for issue in review_issues],
    }
    result_bytes = canonical_json_bytes(envelope)
    references["assessment_result.json"] = _artifact_reference(
        "assessment_result.json", result_bytes, "application/json", RESULT_SCHEMA
    )
    with AtomicAssessmentOutput(source.output_dir, source) as output:
        for name, (data, _, _) in payloads.items():
            output.write_bytes(name, data)
        output.write_bytes("assessment_result.json", result_bytes)
        output.commit()
    return AssessmentResult(
        RESULT_SCHEMA,
        assessment_id,
        "completed",
        aggregate.gate,
        None if aggregate.severity is None else int(aggregate.severity),
        fingerprint,
        references,
        warnings,
        blockers,
        review_issues,
        request.state_chunk_size,
    )
