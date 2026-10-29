from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import statistics
import uuid
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any

from .city_impact import METRIC_DEFINITIONS, build_city_impact_assessment
from .city_layout_contract import (
    city_editor_state_fingerprint,
    city_layout_fingerprint,
)
from .config import JSONDict
from .io import read_json
from .locks import ProjectLock
from .paths import safe_project_name


CASE_MATRIX_SCHEMA_VERSION = "phase16b.case_matrix.v1"
BATCH_AUTHORIZATION_SCHEMA_VERSION = "phase16b.batch_authorization.v1"
RESULT_REPOSITORY_SCHEMA_VERSION = "phase16b.result_repository.v1"
CASE_RESULT_SCHEMA_VERSION = "phase16b.case_result.v1"
COMPARISON_SCHEMA_VERSION = "phase16b.object_comparison.v1"
UNCERTAINTY_SCHEMA_VERSION = "phase16b.uncertainty_analysis.v1"
REFINEMENT_PLAN_SCHEMA_VERSION = "phase16b.refinement_plan.v1"
SURROGATE_MODEL_SCHEMA_VERSION = "phase16b.surrogate_model.v1"
SURROGATE_PREDICTION_SCHEMA_VERSION = "phase16b.surrogate_prediction.v1"
PROTECTION_RANKING_SCHEMA_VERSION = "phase16b.protection_ranking.v1"
MAX_MATRIX_CASES = 64
MAX_VALUES_PER_PARAMETER = 16
MIN_SURROGATE_SAMPLES = 6
MAX_PROTECTION_OPTIONS = 16
MAX_PROTECTION_OBJECTIVES = 16
_REFINEMENT_FACTORS = {0.5, 0.67, 0.75}
_SURROGATE_NEIGHBOR_COUNTS = {1, 2, 3}
_SURROGATE_ERROR_THRESHOLDS = {0.15, 0.25, 0.35, 0.5}
_PROTECTION_MEASURE_TYPES = {
    "increase_standoff",
    "blast_barrier",
    "entrance_reorientation",
    "vehicle_evacuation",
    "combined",
    "other_validated",
}
_RISK_PRIORITY = {
    "low": 0.1,
    "attention": 0.35,
    "high": 0.7,
    "severe": 1.0,
}

_CONTROLLED_PARAMETERS: dict[str, JSONDict] = {
    "tnt_mass_kg": {"minimum": 10.0, "maximum": 1000.0},
    "tnt_diameter_m": {"minimum": 0.3, "maximum": 1.5},
    "blast_center_x_m": {"domain_axis": 0},
    "blast_center_y_m": {"domain_axis": 1},
    "blast_center_z_m": {"domain_axis": 2},
    "near_mesh_size_m": {"enum": [0.05, 0.075, 0.1, 0.15, 0.2]},
    "end_time_s": {"minimum": 0.005, "maximum": 0.1},
}


def create_controlled_case_matrix(
    reference_project: Path,
    study_id: str,
    dimensions: JSONDict,
) -> JSONDict:
    project, model, resolved_spec = _reference_city_project(reference_project)
    safe_study_id = safe_project_name(study_id)
    metadata = model.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("reference city metadata is missing")
    reference_layout_fingerprint = city_layout_fingerprint(
        resolved_spec,
        metadata,
    )
    layout_contract_enforced = (
        metadata.get("layout_fingerprint") == reference_layout_fingerprint
    )
    normalized_dimensions = _normalize_dimensions(dimensions, resolved_spec)
    parameter_names = sorted(normalized_dimensions)
    combinations = list(
        itertools.product(*(normalized_dimensions[name] for name in parameter_names))
    )
    if len(combinations) > MAX_MATRIX_CASES:
        raise ValueError(
            f"controlled case matrix exceeds the maximum of {MAX_MATRIX_CASES} cases"
        )

    cases: list[JSONDict] = []
    for values in combinations:
        parameters = dict(zip(parameter_names, values, strict=True))
        _resolved_controls(resolved_spec, parameters)
        case_digest = _digest(
            {
                "reference_model_sha256": _sha256(project / "model.k"),
                "reference_layout_fingerprint": reference_layout_fingerprint,
                "parameters": parameters,
            }
        )
        case_id = f"case_{case_digest[:12]}"
        cases.append(
            {
                "case_id": case_id,
                "parameters": parameters,
                "target_project_name": _target_project_name(
                    project.name,
                    safe_study_id,
                    case_digest[:8],
                ),
                "status": "prepared",
                "solver_authorized": False,
                "solver_execution_started": False,
            }
        )
    cases.sort(key=lambda item: item["case_id"])

    matrix_core = {
        "schema_version": CASE_MATRIX_SCHEMA_VERSION,
        "study_id": safe_study_id,
        "reference_project_name": project.name,
        "reference_model_sha256": _sha256(project / "model.k"),
        "reference_layout_fingerprint": reference_layout_fingerprint,
        "layout_contract_enforced": layout_contract_enforced,
        "semantic_schema_version": _semantic_schema_version(model),
        "dimensions": normalized_dimensions,
        "cases": cases,
    }
    matrix_id = f"matrix_{_digest(matrix_core)[:16]}"
    approval_text = f"AUTHORIZE PHASE16B {safe_study_id} {matrix_id}"
    manifest = {
        **matrix_core,
        "ok": True,
        "operation": "create_controlled_case_matrix",
        "matrix_id": matrix_id,
        "status": "prepared",
        "case_count": len(cases),
        "requires_explicit_solver_authorization": True,
        "solver_execution_started": False,
        "authorization": {
            "status": "required",
            "approval_text": approval_text,
            "notice": (
                "Recording authorization does not start LS-Run or LS-DYNA. "
                "Solver execution remains a separate user-approved action."
            ),
        },
        "created_at": _utc_now(),
    }
    manifest_path = _study_dir(project, safe_study_id) / "case_matrix.json"
    with ProjectLock(project.name, namespace="phase16b_study"):
        if manifest_path.is_file():
            previous = read_json(manifest_path)
            has_downstream_records = any(
                path.exists()
                for path in (
                    manifest_path.parent / "batch_authorization.json",
                    manifest_path.parent / "result_index.json",
                )
            )
            if (
                has_downstream_records
                and previous.get("matrix_id") != matrix_id
            ):
                raise ValueError(
                    "the study already has authorization or results; use a new study_id "
                    "instead of redefining its matrix"
                )
        _atomic_write_json(manifest_path, manifest)
    manifest["relative_manifest_path"] = _relative(project, manifest_path)
    return manifest


def authorize_case_batch(
    reference_project: Path,
    study_id: str,
    case_ids: list[str],
    approval_text: str,
) -> JSONDict:
    project = reference_project.resolve()
    safe_study_id = safe_project_name(study_id)
    path = _study_dir(project, safe_study_id) / "batch_authorization.json"
    with ProjectLock(project.name, namespace="phase16b_study"):
        matrix = _load_matrix(project, safe_study_id)
        known_ids = [item["case_id"] for item in matrix["cases"]]
        selected = _validated_case_ids(case_ids, known_ids)
        expected = matrix["authorization"]["approval_text"]
        if approval_text != expected:
            raise ValueError(
                "approval_text does not match the exact Phase 16B batch authorization phrase"
            )
        record = {
            "ok": True,
            "operation": "authorize_case_batch",
            "schema_version": BATCH_AUTHORIZATION_SCHEMA_VERSION,
            "study_id": safe_study_id,
            "matrix_id": matrix["matrix_id"],
            "reference_project_name": project.name,
            "reference_model_sha256": matrix["reference_model_sha256"],
            "reference_layout_fingerprint": matrix.get(
                "reference_layout_fingerprint"
            ),
            "authorized_case_ids": selected,
            "authorized_case_count": len(selected),
            "approval_text_sha256": hashlib.sha256(approval_text.encode("utf-8")).hexdigest(),
            "status": "authorized_not_started",
            "solver_execution_started": False,
            "notice": (
                "This record authorizes only the listed batch. It does not launch "
                "LS-Run or LS-DYNA."
            ),
            "authorized_at": _utc_now(),
        }
        _atomic_write_json(path, record)
    record["relative_authorization_path"] = _relative(project, path)
    return record


def register_case_result(
    reference_project: Path,
    study_id: str,
    case_id: str,
    result_project: Path,
    *,
    replace: bool = False,
) -> JSONDict:
    reference = reference_project.resolve()
    safe_study_id = safe_project_name(study_id)
    matrix = _load_matrix(reference, safe_study_id)
    case = _matrix_case(matrix, case_id)
    result_path, model, resolved_spec = _reference_city_project(result_project)
    assessment = build_city_impact_assessment(result_path)
    if not assessment.get("ready_for_risk"):
        raise ValueError(
            "result project did not pass the Phase 16A quality gate and cannot "
            "enter the Phase 16B comparable repository"
        )
    mismatches = _case_parameter_mismatches(case["parameters"], resolved_spec)
    if mismatches:
        raise ValueError(
            "result project does not match the controlled case parameters: "
            + "; ".join(mismatches)
        )

    result_metadata = model.get("metadata", {})
    if not isinstance(result_metadata, dict):
        raise ValueError("result city metadata is missing")
    expected_layout = matrix.get("reference_layout_fingerprint")
    if not isinstance(expected_layout, str):
        raise ValueError("layout_fingerprint_missing")
    actual_layout = city_layout_fingerprint(resolved_spec, result_metadata)
    layout_contract_enforced = matrix.get("layout_contract_enforced") is True
    if layout_contract_enforced and actual_layout != expected_layout:
        raise ValueError("layout_fingerprint_mismatch")
    repository_layout = actual_layout if layout_contract_enforced else expected_layout
    editor_state = city_editor_state_fingerprint(
        resolved_spec,
        result_metadata,
    )
    fingerprints = _result_fingerprints(model, resolved_spec, assessment)
    if not layout_contract_enforced:
        fingerprints["layout_fingerprint"] = repository_layout
        fingerprints["compatibility_fingerprint"] = _digest(fingerprints)
    objects = _repository_objects(assessment)
    record = {
        "ok": True,
        "operation": "register_case_result",
        "schema_version": CASE_RESULT_SCHEMA_VERSION,
        "study_id": safe_study_id,
        "matrix_id": matrix["matrix_id"],
        "case_id": case_id,
        "parameters": case["parameters"],
        "observed_controls": _observed_controls(resolved_spec),
        "result_project_name": result_path.name,
        "result_project_dir": str(result_path),
        "model_sha256": assessment["model_sha256"],
        "layout_fingerprint": repository_layout,
        "editor_state_fingerprint": editor_state,
        "assessment_schema_version": assessment["schema_version"],
        "quality_status": assessment["status"],
        "ready_for_risk": True,
        "fingerprints": fingerprints,
        "objects": objects,
        "registered_at": _utc_now(),
    }
    results_dir = _study_dir(reference, safe_study_id) / "results"
    record_path = results_dir / f"{case_id}.json"
    index_path = _study_dir(reference, safe_study_id) / "result_index.json"
    with ProjectLock(reference.name, namespace="phase16b_study"):
        current_matrix = _load_matrix(reference, safe_study_id)
        if current_matrix["matrix_id"] != matrix["matrix_id"]:
            raise ValueError("Phase 16B case matrix changed while registering a result")
        current_case = _matrix_case(current_matrix, case_id)
        if current_case["parameters"] != case["parameters"]:
            raise ValueError("Phase 16B case parameters changed while registering a result")
        if record_path.exists() and not replace:
            raise FileExistsError(
                f"Phase 16B result already registered for {case_id}; use replace=True"
            )
        index = _load_or_create_index(index_path, matrix)
        _atomic_write_json(record_path, record)
        index["results"][case_id] = {
            "case_id": case_id,
            "relative_path": _relative(reference, record_path),
            "result_project_name": result_path.name,
            "model_sha256": assessment["model_sha256"],
            "layout_fingerprint": repository_layout,
            "editor_state_fingerprint": editor_state,
            "fingerprints": fingerprints,
            "registered_at": record["registered_at"],
        }
        index["result_count"] = len(index["results"])
        index["updated_at"] = _utc_now()
        _atomic_write_json(index_path, index)
    record["relative_result_path"] = _relative(reference, record_path)
    record["relative_index_path"] = _relative(reference, index_path)
    return record


def compare_case_results(
    reference_project: Path,
    study_id: str,
    object_id: str,
    *,
    case_ids: list[str] | None = None,
    allow_mixed_mesh: bool = False,
) -> JSONDict:
    reference = reference_project.resolve()
    safe_study_id = safe_project_name(study_id)
    matrix = _load_matrix(reference, safe_study_id)
    index_path = _study_dir(reference, safe_study_id) / "result_index.json"
    if not index_path.is_file():
        raise FileNotFoundError("Phase 16B result repository is empty")
    index = _load_result_index(index_path, matrix)
    registered_ids = sorted(index.get("results", {}))
    selected_ids = (
        _validated_case_ids(case_ids, registered_ids)
        if case_ids is not None
        else registered_ids
    )
    if not selected_ids:
        raise ValueError("at least one registered case result is required")

    records = [
        read_json(
            _repository_record_path(
                reference,
                index["results"][case_id]["relative_path"],
            )
        )
        for case_id in selected_ids
    ]
    rows: list[JSONDict] = []
    for record in records:
        objects = record.get("objects", {})
        if object_id not in objects:
            raise ValueError(
                f"semantic object {object_id!r} is missing from case {record['case_id']}"
            )
        rows.append(
            {
                "case_id": record["case_id"],
                "parameters": record["parameters"],
                "result_project_name": record["result_project_name"],
                "model_sha256": record["model_sha256"],
                "fingerprints": record["fingerprints"],
                "risk": objects[object_id]["risk"],
                "metrics": objects[object_id]["metrics"],
            }
        )

    blocking = _comparison_blockers(rows, allow_mixed_mesh)
    comparable = not blocking
    metrics = _metric_summary(rows) if comparable else {}
    mesh_fingerprints = {
        row["fingerprints"]["mesh_fingerprint"] for row in rows
    }
    return {
        "ok": True,
        "operation": "compare_case_results",
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "study_id": safe_study_id,
        "matrix_id": matrix["matrix_id"],
        "object_id": object_id,
        "case_count": len(rows),
        "case_ids": selected_ids,
        "comparable": comparable,
        "blocking_differences": blocking,
        "mixed_mesh": len(mesh_fingerprints) > 1,
        "mixed_mesh_explicitly_allowed": bool(allow_mixed_mesh),
        "metrics": metrics,
        "rows": rows,
        "notice": (
            "Cross-mesh comparison is explicit and remains labeled; it is not "
            "equivalent to a same-discretization comparison."
            if len(mesh_fingerprints) > 1 and allow_mixed_mesh
            else ""
        ),
    }


def analyze_case_uncertainty(
    reference_project: Path,
    study_id: str,
    object_id: str,
    metric_id: str,
    *,
    case_ids: list[str] | None = None,
    confidence_level: float = 0.95,
) -> JSONDict:
    if metric_id not in METRIC_DEFINITIONS:
        raise ValueError(f"unsupported city impact metric: {metric_id}")
    if confidence_level not in {0.90, 0.95, 0.99}:
        raise ValueError("confidence_level must be one of 0.90, 0.95, or 0.99")

    reference = reference_project.resolve()
    safe_study_id = safe_project_name(study_id)
    matrix = _load_matrix(reference, safe_study_id)
    index_path = _study_dir(reference, safe_study_id) / "result_index.json"
    if not index_path.is_file():
        raise FileNotFoundError("Phase 16B result repository is empty")
    index = _load_result_index(index_path, matrix)
    registered_ids = sorted(index.get("results", {}))
    selected_ids = (
        _validated_case_ids(case_ids, registered_ids)
        if case_ids is not None
        else registered_ids
    )
    if not selected_ids:
        raise ValueError("at least one registered case result is required")

    records = [
        read_json(
            _repository_record_path(
                reference,
                index["results"][case_id]["relative_path"],
            )
        )
        for case_id in selected_ids
    ]
    rows: list[JSONDict] = []
    missing_metric_case_ids: list[str] = []
    for record in records:
        objects = record.get("objects", {})
        if object_id not in objects:
            raise ValueError(
                f"semantic object {object_id!r} is missing from case {record['case_id']}"
            )
        metric = objects[object_id].get("metrics", {}).get(metric_id)
        if not isinstance(metric, dict):
            missing_metric_case_ids.append(record["case_id"])
            continue
        rows.append(
            {
                "case_id": record["case_id"],
                "parameters": record["parameters"],
                "result_project_name": record["result_project_name"],
                "model_sha256": record["model_sha256"],
                "fingerprints": record["fingerprints"],
                "value": float(metric["value"]),
                "unit": str(metric["unit"]),
            }
        )

    blocking_reasons: list[str] = []
    if missing_metric_case_ids:
        blocking_reasons.append("missing_metric_values")
    if len(rows) < 3:
        blocking_reasons.append("minimum_sample_count")
    compatibility_differences = _analysis_compatibility_differences(rows)
    if compatibility_differences:
        blocking_reasons.append("incompatible_result_contracts")
    units = {row["unit"] for row in rows}
    if len(units) > 1:
        blocking_reasons.append("incompatible_metric_units")

    values = [row["value"] for row in rows]
    response = _response_statistics(
        values,
        units,
        confidence_level,
        metric_id,
    )
    sensitivity = (
        _parameter_sensitivity(rows)
        if len(rows) >= 3 and len(units) == 1
        else []
    )
    fidelity = _fidelity_difference(rows)
    coverage = _sample_coverage(
        matrix,
        registered_ids,
        rows,
        selected_ids,
    )
    ready = not blocking_reasons
    if ready:
        status = "ready"
    elif "missing_metric_values" in blocking_reasons:
        status = "incomplete_metric_coverage"
    elif "minimum_sample_count" in blocking_reasons:
        status = "insufficient_samples"
    else:
        status = "incompatible_results"

    analysis = {
        "ok": True,
        "operation": "analyze_case_uncertainty",
        "schema_version": UNCERTAINTY_SCHEMA_VERSION,
        "study_id": safe_study_id,
        "matrix_id": matrix["matrix_id"],
        "object_id": object_id,
        "metric_id": metric_id,
        "confidence_level": confidence_level,
        "status": status,
        "ready": ready,
        "blocking_reasons": blocking_reasons,
        "compatibility_differences": compatibility_differences,
        "missing_metric_case_ids": missing_metric_case_ids,
        "sample_coverage": coverage,
        "response": response,
        "parameter_sensitivity": sensitivity,
        "fidelity_difference": fidelity,
        "uncertainty_components": {
            "input": {
                "status": (
                    "sampled"
                    if any(
                        item["uncertainty_source"] == "input"
                        for item in sensitivity
                    )
                    else "not_sampled"
                ),
                "method": "observed controlled-matrix variation",
            },
            "model_resolution": {
                "status": (
                    "paired"
                    if fidelity["paired_group_count"] > 0
                    else "not_paired"
                ),
                "method": "same-controls coarse/fine mesh difference",
            },
            "material": {
                "status": "not_sampled",
                "notice": (
                    "The current controlled matrix has no material-uncertainty "
                    "dimension; no material uncertainty claim is made."
                ),
            },
        },
        "method_notice": (
            "Sensitivity is a screening correlation, not causal attribution. "
            "Confidence intervals describe only the registered sample set and "
            "must not be extrapolated beyond its parameter coverage."
        ),
        "created_at": _utc_now(),
    }
    analysis_path = (
        _study_dir(reference, safe_study_id)
        / "analyses"
        / f"{safe_project_name(object_id)}_{safe_project_name(metric_id)}.json"
    )
    with ProjectLock(reference.name, namespace="phase16b_study"):
        current_matrix = _load_matrix(reference, safe_study_id)
        if current_matrix["matrix_id"] != matrix["matrix_id"]:
            raise ValueError("Phase 16B case matrix changed during uncertainty analysis")
        _atomic_write_json(analysis_path, analysis)
    analysis["relative_analysis_path"] = _relative(reference, analysis_path)
    return analysis


def plan_local_refinement(
    reference_project: Path,
    study_id: str,
    object_id: str,
    metric_id: str,
    *,
    case_ids: list[str] | None = None,
    confidence_level: float = 0.95,
    refinement_factor: float = 0.5,
    padding_cells: int = 4,
) -> JSONDict:
    if isinstance(refinement_factor, bool) or not isinstance(
        refinement_factor,
        (int, float),
    ):
        raise ValueError("refinement_factor must be a controlled number")
    factor = float(refinement_factor)
    if factor not in _REFINEMENT_FACTORS:
        raise ValueError("refinement_factor must be one of 0.5, 0.67, or 0.75")
    if (
        isinstance(padding_cells, bool)
        or not isinstance(padding_cells, int)
        or not 2 <= padding_cells <= 12
    ):
        raise ValueError("padding_cells must be an integer from 2 to 12")

    reference, _model, resolved_spec = _reference_city_project(reference_project)
    safe_study_id = safe_project_name(study_id)
    analysis = analyze_case_uncertainty(
        reference,
        safe_study_id,
        object_id,
        metric_id,
        case_ids=case_ids,
        confidence_level=confidence_level,
    )
    matrix = _load_matrix(reference, safe_study_id)
    index = _load_result_index(
        _study_dir(reference, safe_study_id) / "result_index.json",
        matrix,
    )
    registered_ids = sorted(index["results"])
    selected_ids = (
        _validated_case_ids(case_ids, registered_ids)
        if case_ids is not None
        else registered_ids
    )
    records = [
        read_json(
            _repository_record_path(
                reference,
                index["results"][case_id]["relative_path"],
            )
        )
        for case_id in selected_ids
    ]

    blocking_reasons: list[str] = []
    if not analysis["ready"]:
        blocking_reasons.append("uncertainty_analysis_not_ready")
    fidelity = analysis["fidelity_difference"]
    if fidelity["paired_group_count"] < 1:
        blocking_reasons.append("paired_fidelity_evidence_missing")

    object_rows: list[JSONDict] = []
    for record in records:
        item = record.get("objects", {}).get(object_id)
        if isinstance(item, dict):
            object_rows.append(item)
    bounds_rows = [
        _validated_spatial_bounds(item.get("bounds_m"))
        for item in object_rows
        if item.get("bounds_m") is not None
    ]
    if len(bounds_rows) != len(object_rows) or not bounds_rows:
        blocking_reasons.append("semantic_object_bounds_missing")
    elif len({_digest(item) for item in bounds_rows}) != 1:
        blocking_reasons.append("semantic_object_bounds_inconsistent")

    risk_levels = [
        str(item.get("risk", {}).get("level", "unavailable"))
        for item in object_rows
    ]
    if not risk_levels or any(level not in _RISK_PRIORITY for level in risk_levels):
        blocking_reasons.append("object_risk_unavailable")
    highest_risk = (
        max(risk_levels, key=lambda level: _RISK_PRIORITY[level])
        if risk_levels and all(level in _RISK_PRIORITY for level in risk_levels)
        else "unavailable"
    )

    controls = [
        _record_observed_controls(record)
        for record in records
    ]
    mesh_values = sorted(
        {
            float(item["near_mesh_size_m"])
            for item in controls
            if "near_mesh_size_m" in item
        }
    )
    if not mesh_values:
        blocking_reasons.append("observed_mesh_size_missing")
    if any(
        parameter not in item
        for item in controls
        for parameter in (
            "blast_center_x_m",
            "blast_center_y_m",
            "blast_center_z_m",
            "tnt_diameter_m",
            "tnt_length_m",
        )
    ):
        blocking_reasons.append("observed_blast_geometry_missing")

    blocking_reasons = list(dict.fromkeys(blocking_reasons))
    plan_core: JSONDict = {
        "ok": True,
        "operation": "plan_local_refinement",
        "schema_version": REFINEMENT_PLAN_SCHEMA_VERSION,
        "study_id": safe_study_id,
        "matrix_id": matrix["matrix_id"],
        "object_id": object_id,
        "metric_id": metric_id,
        "case_ids": selected_ids,
        "confidence_level": confidence_level,
        "refinement_factor": factor,
        "padding_cells": padding_cells,
        "analysis_path": analysis["relative_analysis_path"],
        "ready": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "solver_execution_started": False,
        "implementation_status": "planning_only",
    }
    if blocking_reasons:
        plan = {
            **plan_core,
            "status": "blocked",
            "object": {
                "object_id": object_id,
                "risk_level": highest_risk,
            },
            "decision": {
                "refinement_needed": None,
                "drivers": [],
                "notice": "No spatial refinement claim is made while planning gates fail.",
            },
            "mesh": {},
            "regions": [],
            "expected_benefit": {
                "guaranteed": False,
                "verification_required": True,
            },
        }
        return _write_refinement_plan(reference, matrix, plan)

    finest_mesh = min(mesh_values)
    target_mesh = max(0.025, finest_mesh * factor)
    response = analysis["response"]
    response_mean = abs(float(response["mean"]))
    response_range_ratio = (
        float(response["range"]) / response_mean
        if response_mean > 0.0
        else math.inf
    )
    mean_relative_difference = fidelity["mean_relative_difference_to_fine"]
    fidelity_score = min(
        1.0,
        float(mean_relative_difference or 0.0) / 0.2,
    )
    uncertainty_score = min(1.0, response_range_ratio / 0.5)
    risk_score = _RISK_PRIORITY[highest_risk]
    priority_score = (
        0.4 * risk_score
        + 0.35 * fidelity_score
        + 0.25 * uncertainty_score
    )
    drivers: list[str] = []
    if highest_risk in {"high", "severe"}:
        drivers.append("high_or_severe_object_risk")
    if float(mean_relative_difference or 0.0) >= 0.05:
        drivers.append("paired_model_difference")
    if response_range_ratio >= 0.2:
        drivers.append("wide_observed_response_range")
    refinement_needed = bool(drivers)

    object_bounds = bounds_rows[0]
    domain_bounds = _validated_spatial_bounds(
        {
            "min": resolved_spec["domain"]["min_m"],
            "max": resolved_spec["domain"]["max_m"],
        }
    )
    padding_distance = target_mesh * padding_cells
    regions = (
        _refinement_regions(
            controls,
            object_bounds,
            domain_bounds,
            padding_distance,
            target_mesh,
        )
        if refinement_needed
        else []
    )
    acceptance_relative_difference = min(
        0.1,
        0.5 * float(mean_relative_difference or 0.1),
    )
    plan = {
        **plan_core,
        "status": "planned" if refinement_needed else "not_required",
        "object": {
            "object_id": object_id,
            "category": object_rows[0]["category"],
            "part_ids": object_rows[0]["part_ids"],
            "bounds_m": object_bounds,
            "risk_level": highest_risk,
            "observed_risk_levels": sorted(set(risk_levels)),
        },
        "decision": {
            "refinement_needed": refinement_needed,
            "priority_score": priority_score,
            "priority_level": (
                "high"
                if priority_score >= 0.7
                else "medium"
                if priority_score >= 0.4
                else "low"
            ),
            "drivers": drivers,
            "components": {
                "risk": risk_score,
                "paired_fidelity": fidelity_score,
                "response_variation": uncertainty_score,
            },
            "notice": (
                "The score prioritizes follow-up analysis; it is not a structural "
                "failure probability."
            ),
        },
        "mesh": {
            "observed_sizes_m": mesh_values,
            "finest_observed_size_m": finest_mesh,
            "target_size_m": target_mesh if refinement_needed else finest_mesh,
            "refinement_ratio": (
                finest_mesh / target_mesh if refinement_needed else 1.0
            ),
            "local_3d_cell_cost_multiplier": (
                (finest_mesh / target_mesh) ** 3
                if refinement_needed
                else 1.0
            ),
            "backend_status": "requires_local_mesh_generation_backend",
        },
        "regions": regions,
        "expected_benefit": {
            "guaranteed": False,
            "verification_required": True,
            "metric_id": metric_id,
            "unit": response["unit"],
            "current_mean_absolute_paired_difference": fidelity[
                "mean_absolute_difference"
            ],
            "current_mean_relative_paired_difference": mean_relative_difference,
            "acceptance_target_relative_difference_at_most": (
                acceptance_relative_difference
            ),
            "current_observed_response_range_ratio": response_range_ratio,
            "notice": (
                "The acceptance target is a validation goal, not a promised "
                "reduction. A newly generated high-fidelity result must be registered "
                "and compared before benefit is claimed."
            ),
        },
        "created_at": _utc_now(),
    }
    return _write_refinement_plan(reference, matrix, plan)


def train_surrogate_model(
    reference_project: Path,
    study_id: str,
    object_id: str,
    metric_id: str,
    *,
    case_ids: list[str] | None = None,
    confidence_level: float = 0.95,
    neighbor_count: int = 1,
    max_normalized_rmse: float = 0.25,
) -> JSONDict:
    if (
        isinstance(neighbor_count, bool)
        or not isinstance(neighbor_count, int)
        or neighbor_count not in _SURROGATE_NEIGHBOR_COUNTS
    ):
        raise ValueError("neighbor_count must be one of 1, 2, or 3")
    if isinstance(max_normalized_rmse, bool) or not isinstance(
        max_normalized_rmse,
        (int, float),
    ):
        raise ValueError("max_normalized_rmse must be a controlled number")
    error_threshold = float(max_normalized_rmse)
    if error_threshold not in _SURROGATE_ERROR_THRESHOLDS:
        raise ValueError(
            "max_normalized_rmse must be one of 0.15, 0.25, 0.35, or 0.5"
        )

    reference, _model, _resolved_spec = _reference_city_project(reference_project)
    safe_study_id = safe_project_name(study_id)
    analysis = analyze_case_uncertainty(
        reference,
        safe_study_id,
        object_id,
        metric_id,
        case_ids=case_ids,
        confidence_level=confidence_level,
    )
    matrix = _load_matrix(reference, safe_study_id)
    index = _load_result_index(
        _study_dir(reference, safe_study_id) / "result_index.json",
        matrix,
    )
    registered_ids = sorted(index["results"])
    selected_ids = (
        _validated_case_ids(case_ids, registered_ids)
        if case_ids is not None
        else registered_ids
    )
    records = [
        read_json(
            _repository_record_path(
                reference,
                index["results"][case_id]["relative_path"],
            )
        )
        for case_id in selected_ids
    ]
    samples: list[JSONDict] = []
    for record in records:
        item = record.get("objects", {}).get(object_id)
        metric = (
            item.get("metrics", {}).get(metric_id)
            if isinstance(item, dict)
            else None
        )
        if not isinstance(metric, dict):
            continue
        samples.append(
            {
                "case_id": record["case_id"],
                "parameters": dict(record["parameters"]),
                "value": float(metric["value"]),
                "unit": str(metric["unit"]),
                "model_sha256": record["model_sha256"],
            }
        )
    feature_ids = _surrogate_feature_ids(samples)
    features = _surrogate_features(samples, feature_ids)
    blocking_reasons: list[str] = []
    if not analysis["ready"]:
        blocking_reasons.append("uncertainty_analysis_not_ready")
    if len(samples) < MIN_SURROGATE_SAMPLES:
        blocking_reasons.append("minimum_surrogate_sample_count")
    if not feature_ids:
        blocking_reasons.append("no_varying_numeric_parameters")
    if neighbor_count >= len(samples):
        blocking_reasons.append("neighbor_count_exceeds_training_support")
    units = {sample["unit"] for sample in samples}
    if len(units) != 1:
        blocking_reasons.append("incompatible_metric_units")
    blocking_reasons = list(dict.fromkeys(blocking_reasons))

    model_core: JSONDict = {
        "ok": True,
        "operation": "train_surrogate_model",
        "schema_version": SURROGATE_MODEL_SCHEMA_VERSION,
        "study_id": safe_study_id,
        "matrix_id": matrix["matrix_id"],
        "reference_model_sha256": matrix["reference_model_sha256"],
        "object_id": object_id,
        "metric_id": metric_id,
        "unit": next(iter(units)) if len(units) == 1 else "incompatible",
        "analysis_path": analysis["relative_analysis_path"],
        "algorithm": {
            "name": "normalized_inverse_distance_knn",
            "neighbor_count": neighbor_count,
            "distance": "euclidean",
            "weight": "inverse_squared_distance",
        },
        "sample_count": len(samples),
        "minimum_sample_count": MIN_SURROGATE_SAMPLES,
        "case_ids": selected_ids,
        "features": features,
        "quality_gate": {
            "max_normalized_rmse": error_threshold,
            "profile": "controlled_phase16b_surrogate_gate",
        },
        "solver_execution_started": False,
        "material_uncertainty_status": "not_sampled",
        "blocking_reasons": blocking_reasons,
    }
    if blocking_reasons:
        model = {
            **model_core,
            "status": "blocked",
            "ready": False,
            "accepted_for_prediction": False,
            "training_samples": samples,
            "cross_validation": {
                "status": "not_run",
                "method": "leave_one_out",
            },
            "applicability_domain": {},
            "notice": (
                "No surrogate prediction is permitted while training gates fail."
            ),
            "created_at": _utc_now(),
        }
        return _write_surrogate_model(reference, matrix, model)

    normalized_samples = _normalize_surrogate_samples(samples, features)
    cross_validation = _leave_one_out_validation(
        normalized_samples,
        neighbor_count,
    )
    response_values = [float(sample["value"]) for sample in normalized_samples]
    response_range = max(response_values) - min(response_values)
    rmse = float(cross_validation["rmse"])
    normalized_rmse = (
        rmse / response_range
        if response_range > 0.0
        else 0.0
        if rmse == 0.0
        else math.inf
    )
    cross_validation["response_range"] = response_range
    cross_validation["normalized_rmse"] = normalized_rmse
    accepted = normalized_rmse <= error_threshold
    quality_blockers = (
        [] if accepted else ["cross_validation_error_too_high"]
    )
    coverage_radius = _training_coverage_radius(normalized_samples)
    model = {
        **model_core,
        "status": "accepted" if accepted else "rejected_quality",
        "ready": accepted,
        "accepted_for_prediction": accepted,
        "blocking_reasons": quality_blockers,
        "training_samples": normalized_samples,
        "cross_validation": cross_validation,
        "applicability_domain": {
            "type": "bounded_sampled_parameter_space",
            "parameter_ranges": {
                feature["parameter_id"]: {
                    "minimum": feature["minimum"],
                    "maximum": feature["maximum"],
                }
                for feature in features
            },
            "maximum_normalized_distance_to_sample": coverage_radius,
            "outside_range_policy": "refuse",
            "sparse_region_policy": "refuse",
        },
        "notice": (
            "This is a local interpolation surrogate for screened use. It is not "
            "a replacement for LS-DYNA and must not be extrapolated."
        ),
        "created_at": _utc_now(),
    }
    return _write_surrogate_model(reference, matrix, model)


def predict_surrogate_response(
    reference_project: Path,
    study_id: str,
    object_id: str,
    metric_id: str,
    parameters: JSONDict,
) -> JSONDict:
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")
    reference, _model, _resolved_spec = _reference_city_project(reference_project)
    safe_study_id = safe_project_name(study_id)
    matrix = _load_matrix(reference, safe_study_id)
    model_path = _surrogate_model_path(
        reference,
        safe_study_id,
        object_id,
        metric_id,
    )
    if not model_path.is_file():
        raise FileNotFoundError("Phase 16B surrogate model has not been trained")
    model = read_json(model_path)
    _validate_surrogate_model(model, matrix, object_id, metric_id)
    prediction_core: JSONDict = {
        "ok": True,
        "operation": "predict_surrogate_response",
        "schema_version": SURROGATE_PREDICTION_SCHEMA_VERSION,
        "study_id": safe_study_id,
        "matrix_id": matrix["matrix_id"],
        "surrogate_model_id": model["model_id"],
        "object_id": object_id,
        "metric_id": metric_id,
        "parameters": parameters,
        "ready": False,
        "solver_execution_started": False,
    }
    if not model.get("accepted_for_prediction"):
        return _write_surrogate_prediction(
            reference,
            {
                **prediction_core,
                "status": "model_not_accepted",
                "refusal_reasons": {
                    "model": "surrogate model did not pass its quality gate"
                },
            },
        )

    stale_reasons = _surrogate_staleness_reasons(reference, matrix, model)
    if stale_reasons:
        return _write_surrogate_prediction(
            reference,
            {
                **prediction_core,
                "status": "stale_model",
                "refusal_reasons": {
                    "repository": "; ".join(stale_reasons)
                },
            },
        )

    feature_ids = [item["parameter_id"] for item in model["features"]]
    unknown = sorted(set(parameters) - set(feature_ids))
    missing = sorted(set(feature_ids) - set(parameters))
    if unknown or missing:
        details = {}
        if unknown:
            details["unknown_parameters"] = ", ".join(unknown)
        if missing:
            details["missing_parameters"] = ", ".join(missing)
        return _write_surrogate_prediction(
            reference,
            {
                **prediction_core,
                "status": "invalid_parameter_contract",
                "refusal_reasons": details,
            },
        )

    normalized_query: JSONDict = {}
    outside: JSONDict = {}
    for feature in model["features"]:
        parameter_id = feature["parameter_id"]
        raw = parameters[parameter_id]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            outside[parameter_id] = "value must be a finite number"
            continue
        value = float(raw)
        minimum = float(feature["minimum"])
        maximum = float(feature["maximum"])
        if not math.isfinite(value):
            outside[parameter_id] = "value must be a finite number"
        elif value < minimum or value > maximum:
            outside[parameter_id] = (
                f"value {value} is outside [{minimum}, {maximum}]"
            )
        else:
            normalized_query[parameter_id] = (
                (value - minimum) / (maximum - minimum)
            )
    if outside:
        return _write_surrogate_prediction(
            reference,
            {
                **prediction_core,
                "status": "outside_applicability_domain",
                "refusal_reasons": outside,
            },
        )

    neighbors = _surrogate_neighbors(
        normalized_query,
        model["training_samples"],
    )
    nearest_distance = float(neighbors[0]["distance"])
    coverage_radius = float(
        model["applicability_domain"][
            "maximum_normalized_distance_to_sample"
        ]
    )
    if nearest_distance > coverage_radius + 1.0e-12:
        return _write_surrogate_prediction(
            reference,
            {
                **prediction_core,
                "status": "sparse_applicability_region",
                "refusal_reasons": {
                    "sample_coverage_radius": (
                        f"nearest normalized distance {nearest_distance:.6g} "
                        f"exceeds {coverage_radius:.6g}"
                    )
                },
                "nearest_normalized_distance": nearest_distance,
            },
        )

    neighbor_count = int(model["algorithm"]["neighbor_count"])
    estimate, used_neighbors = _knn_estimate(neighbors, neighbor_count)
    error = float(model["cross_validation"]["maximum_absolute_error"])
    prediction = {
        **prediction_core,
        "status": "estimated",
        "ready": True,
        "normalized_parameters": normalized_query,
        "nearest_normalized_distance": nearest_distance,
        "neighbors": used_neighbors,
        "estimate": {
            "value": estimate,
            "unit": model["unit"],
            "deterministic": False,
            "prediction_interval": {
                "lower": estimate - error,
                "upper": estimate + error,
                "half_width": error,
                "empirical": True,
                "basis": "maximum leave-one-out absolute error",
            },
        },
        "applicability": {
            "inside_parameter_ranges": True,
            "inside_sample_coverage_radius": True,
        },
        "notice": (
            "Estimated by a cross-validated local surrogate. Run and register a "
            "real solver case before using this value as verified evidence."
        ),
        "created_at": _utc_now(),
    }
    return _write_surrogate_prediction(reference, prediction)


def rank_protection_options(
    reference_project: Path,
    study_id: str,
    baseline_case_id: str,
    objectives: list[JSONDict],
    options: list[JSONDict],
    *,
    effectiveness_weight: float = 0.7,
    cost_weight: float = 0.3,
    budget_limit: float | None = None,
    metric_limits: list[JSONDict] | None = None,
    minimum_benefit_fraction: float = 0.0,
    allow_mixed_mesh: bool = False,
    allow_semantic_variants: bool = False,
) -> JSONDict:
    reference = reference_project.resolve()
    safe_study_id = safe_project_name(study_id)
    matrix = _load_matrix(reference, safe_study_id)
    index_path = _study_dir(reference, safe_study_id) / "result_index.json"
    if not index_path.is_file():
        raise FileNotFoundError("Phase 16B result repository is empty")
    index = _load_result_index(index_path, matrix)
    registered_ids = sorted(index.get("results", {}))

    normalized_objectives = _normalize_protection_objectives(objectives)
    normalized_options, cost_unit = _normalize_protection_options(
        options,
        registered_ids,
        baseline_case_id,
    )
    selected_case_ids = [baseline_case_id] + [
        item["case_id"] for item in normalized_options
    ]
    _validated_case_ids(selected_case_ids, registered_ids)
    weights = _protection_weights(effectiveness_weight, cost_weight)
    budget = (
        None
        if budget_limit is None
        else _finite_number(budget_limit, "budget_limit", minimum=0.0)
    )
    minimum_benefit = _finite_number(
        minimum_benefit_fraction,
        "minimum_benefit_fraction",
        minimum=-1.0,
        maximum=1.0,
    )
    normalized_limits = _normalize_metric_limits(
        metric_limits or [],
        normalized_objectives,
    )

    records = {
        case_id: read_json(
            _repository_record_path(
                reference,
                index["results"][case_id]["relative_path"],
            )
        )
        for case_id in selected_case_ids
    }
    blocking_differences = _protection_compatibility_blockers(
        records,
        normalized_objectives,
        allow_mixed_mesh=allow_mixed_mesh,
        allow_semantic_variants=allow_semantic_variants,
    )
    evidence = [
        {
            "case_id": case_id,
            "result_project_name": records[case_id]["result_project_name"],
            "model_sha256": records[case_id]["model_sha256"],
            "fingerprints": records[case_id]["fingerprints"],
        }
        for case_id in selected_case_ids
    ]
    ranking_core: JSONDict = {
        "schema_version": PROTECTION_RANKING_SCHEMA_VERSION,
        "study_id": safe_study_id,
        "matrix_id": matrix["matrix_id"],
        "baseline_case_id": baseline_case_id,
        "objectives": normalized_objectives,
        "options": normalized_options,
        "weights": weights,
        "cost_unit": cost_unit,
        "constraints": {
            "budget_limit": budget,
            "metric_limits": normalized_limits,
            "minimum_benefit_fraction": minimum_benefit,
        },
        "compatibility_policy": {
            "allow_mixed_mesh": bool(allow_mixed_mesh),
            "allow_semantic_variants": bool(allow_semantic_variants),
        },
        "result_evidence": evidence,
    }
    if blocking_differences:
        result = {
            **ranking_core,
            "ok": True,
            "operation": "rank_protection_options",
            "status": "blocked_incompatible_results",
            "blocking_differences": blocking_differences,
            "ranked_options": [],
            "recommendation": None,
            "solver_execution_started": False,
            "notice": (
                "Protection alternatives were not ranked because their registered "
                "results are not comparable under the selected compatibility policy."
            ),
            "created_at": _utc_now(),
        }
        return _write_protection_ranking(reference, matrix, result)

    baseline_record = records[baseline_case_id]
    baseline_metrics = {
        _objective_key(item): _registered_metric(
            baseline_record,
            item["object_id"],
            item["metric_id"],
        )
        for item in normalized_objectives
    }
    maximum_cost = max(
        float(item["incremental_cost"]["value"])
        for item in normalized_options
    )
    ranked: list[JSONDict] = []
    for option in normalized_options:
        record = records[option["case_id"]]
        objective_results: list[JSONDict] = []
        aggregate_benefit = 0.0
        for objective in normalized_objectives:
            key = _objective_key(objective)
            baseline_metric = baseline_metrics[key]
            candidate_metric = _registered_metric(
                record,
                objective["object_id"],
                objective["metric_id"],
            )
            if candidate_metric["unit"] != baseline_metric["unit"]:
                raise ValueError(
                    f"metric unit mismatch for {key}: "
                    f"{baseline_metric['unit']} vs {candidate_metric['unit']}"
                )
            absolute_benefit = (
                float(baseline_metric["value"])
                - float(candidate_metric["value"])
            )
            benefit_fraction = _benefit_fraction(
                float(baseline_metric["value"]),
                float(candidate_metric["value"]),
            )
            weighted_benefit = (
                float(objective["normalized_weight"]) * benefit_fraction
            )
            aggregate_benefit += weighted_benefit
            objective_results.append(
                {
                    "object_id": objective["object_id"],
                    "metric_id": objective["metric_id"],
                    "unit": baseline_metric["unit"],
                    "baseline_value": float(baseline_metric["value"]),
                    "candidate_value": float(candidate_metric["value"]),
                    "absolute_benefit": absolute_benefit,
                    "benefit_fraction": benefit_fraction,
                    "normalized_weight": objective["normalized_weight"],
                    "weighted_benefit": weighted_benefit,
                }
            )

        cost_value = float(option["incremental_cost"]["value"])
        normalized_cost = (
            cost_value / maximum_cost if maximum_cost > 0.0 else 0.0
        )
        violations: list[str] = []
        if budget is not None and cost_value > budget:
            violations.append("budget_limit")
        if aggregate_benefit < minimum_benefit:
            violations.append("minimum_benefit_fraction")
        for limit in normalized_limits:
            objective_result = next(
                (
                    item
                    for item in objective_results
                    if item["object_id"] == limit["object_id"]
                    and item["metric_id"] == limit["metric_id"]
                ),
                None,
            )
            if (
                objective_result is not None
                and float(objective_result["candidate_value"])
                > float(limit["maximum_value"])
            ):
                violations.append("metric_limit:" + _objective_key(limit))
        decision_score = (
            float(weights["effectiveness"]) * aggregate_benefit
            - float(weights["cost"]) * normalized_cost
        )
        ranked.append(
            {
                **option,
                "objective_results": objective_results,
                "absolute_benefit": (
                    objective_results[0]["absolute_benefit"]
                    if len(objective_results) == 1
                    else None
                ),
                "benefit_fraction": aggregate_benefit,
                "normalized_cost": normalized_cost,
                "decision_score": decision_score,
                "constraint_violations": sorted(set(violations)),
                "feasible": not violations,
                "pareto_efficient": False,
                "rank": None,
            }
        )

    _mark_pareto_options(ranked)
    feasible = [item for item in ranked if item["feasible"]]
    feasible.sort(
        key=lambda item: (
            -float(item["decision_score"]),
            -float(item["benefit_fraction"]),
            float(item["incremental_cost"]["value"]),
            item["option_id"],
        )
    )
    for rank, item in enumerate(feasible, start=1):
        item["rank"] = rank
    infeasible = sorted(
        (item for item in ranked if not item["feasible"]),
        key=lambda item: (
            len(item["constraint_violations"]),
            -float(item["decision_score"]),
            item["option_id"],
        ),
    )
    ranked_options = feasible + infeasible
    recommendation = (
        {
            "option_id": feasible[0]["option_id"],
            "label": feasible[0]["label"],
            "case_id": feasible[0]["case_id"],
            "measure_type": feasible[0]["measure_type"],
            "feasible": True,
            "decision_score": feasible[0]["decision_score"],
            "benefit_fraction": feasible[0]["benefit_fraction"],
            "absolute_benefit": feasible[0]["absolute_benefit"],
            "objective_results": feasible[0]["objective_results"],
            "incremental_cost": feasible[0]["incremental_cost"],
            "physical_basis": feasible[0]["physical_basis"],
            "constraints": feasible[0]["constraints"],
        }
        if feasible
        else None
    )
    result = {
        **ranking_core,
        "ok": True,
        "operation": "rank_protection_options",
        "status": "ranked" if feasible else "no_feasible_option",
        "blocking_differences": [],
        "baseline": {
            "case_id": baseline_case_id,
            "metrics": baseline_metrics,
        },
        "ranked_options": ranked_options,
        "recommendation": recommendation,
        "solver_execution_started": False,
        "scoring_formula": (
            "decision_score = effectiveness_weight * weighted_benefit_fraction "
            "- cost_weight * normalized_incremental_cost"
        ),
        "notice": (
            "This is a transparent comparison of registered simulation results, "
            "not an automatic engineering approval. Physical-basis text and cost "
            "values are user-supplied and remain visible in the audit artifact."
        ),
        "created_at": _utc_now(),
    }
    return _write_protection_ranking(reference, matrix, result)


def _normalize_protection_objectives(
    objectives: list[JSONDict],
) -> list[JSONDict]:
    if not isinstance(objectives, list) or not objectives:
        raise ValueError("objectives must be a non-empty array")
    if len(objectives) > MAX_PROTECTION_OBJECTIVES:
        raise ValueError(
            f"objectives exceeds the maximum of {MAX_PROTECTION_OBJECTIVES}"
        )
    normalized: list[JSONDict] = []
    seen: set[str] = set()
    for index, item in enumerate(objectives):
        if not isinstance(item, dict):
            raise ValueError(f"objectives[{index}] must be an object")
        unknown = sorted(set(item) - {"object_id", "metric_id", "weight"})
        if unknown:
            raise ValueError(
                f"objectives[{index}] contains unknown field(s): "
                + ", ".join(unknown)
            )
        object_id = item.get("object_id")
        metric_id = item.get("metric_id")
        if not isinstance(object_id, str) or not object_id.strip():
            raise ValueError(f"objectives[{index}].object_id must be a string")
        if metric_id not in METRIC_DEFINITIONS:
            raise ValueError(
                f"objectives[{index}].metric_id is not a supported city metric"
            )
        weight = _finite_number(
            item.get("weight"),
            f"objectives[{index}].weight",
            minimum=0.0,
            strictly_greater_than_minimum=True,
        )
        key = f"{object_id.strip()}::{metric_id}"
        if key in seen:
            raise ValueError(f"duplicate protection objective: {key}")
        seen.add(key)
        normalized.append(
            {
                "object_id": object_id.strip(),
                "metric_id": metric_id,
                "weight": weight,
            }
        )
    weight_sum = sum(float(item["weight"]) for item in normalized)
    for item in normalized:
        item["normalized_weight"] = float(item["weight"]) / weight_sum
    return normalized


def _normalize_protection_options(
    options: list[JSONDict],
    registered_case_ids: list[str],
    baseline_case_id: str,
) -> tuple[list[JSONDict], str]:
    if not isinstance(options, list) or not options:
        raise ValueError("options must be a non-empty array")
    if len(options) > MAX_PROTECTION_OPTIONS:
        raise ValueError(
            f"options exceeds the maximum of {MAX_PROTECTION_OPTIONS}"
        )
    normalized: list[JSONDict] = []
    option_ids: set[str] = set()
    case_ids: set[str] = set()
    cost_units: set[str] = set()
    allowed = {
        "option_id",
        "label",
        "case_id",
        "measure_type",
        "incremental_cost",
        "physical_basis",
        "constraints",
    }
    for index, item in enumerate(options):
        if not isinstance(item, dict):
            raise ValueError(f"options[{index}] must be an object")
        unknown = sorted(set(item) - allowed)
        if unknown:
            raise ValueError(
                f"options[{index}] contains unknown field(s): "
                + ", ".join(unknown)
            )
        option_id = item.get("option_id")
        if not isinstance(option_id, str) or not option_id.strip():
            raise ValueError(f"options[{index}].option_id must be a string")
        option_id = option_id.strip()
        if safe_project_name(option_id) != option_id:
            raise ValueError(
                f"options[{index}].option_id must use a safe project-style name"
            )
        if option_id in option_ids:
            raise ValueError(f"duplicate protection option_id: {option_id}")
        option_ids.add(option_id)
        label = item.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"options[{index}].label must be a string")
        case_id = item.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"options[{index}].case_id must be a string")
        if case_id == baseline_case_id:
            raise ValueError("a protection option cannot reuse the baseline case")
        if case_id in case_ids:
            raise ValueError(f"duplicate protection option case_id: {case_id}")
        case_ids.add(case_id)
        _validated_case_ids([case_id], registered_case_ids)
        measure_type = item.get("measure_type")
        if measure_type not in _PROTECTION_MEASURE_TYPES:
            raise ValueError(
                f"options[{index}].measure_type must be one of "
                + ", ".join(sorted(_PROTECTION_MEASURE_TYPES))
            )
        cost = item.get("incremental_cost")
        if not isinstance(cost, dict):
            raise ValueError(
                f"options[{index}].incremental_cost must be an object"
            )
        if sorted(cost) != ["unit", "value"]:
            raise ValueError(
                f"options[{index}].incremental_cost requires value and unit only"
            )
        cost_value = _finite_number(
            cost.get("value"),
            f"options[{index}].incremental_cost.value",
            minimum=0.0,
        )
        cost_unit = cost.get("unit")
        if not isinstance(cost_unit, str) or not cost_unit.strip():
            raise ValueError(
                f"options[{index}].incremental_cost.unit must be a string"
            )
        cost_unit = cost_unit.strip()
        cost_units.add(cost_unit)
        physical_basis = item.get("physical_basis")
        if not isinstance(physical_basis, str) or not physical_basis.strip():
            raise ValueError(
                f"options[{index}].physical_basis must be a non-empty string"
            )
        constraints = item.get("constraints", [])
        if (
            not isinstance(constraints, list)
            or len(constraints) > 16
            or any(
                not isinstance(value, str) or not value.strip()
                for value in constraints
            )
        ):
            raise ValueError(
                f"options[{index}].constraints must contain up to 16 strings"
            )
        normalized.append(
            {
                "option_id": option_id,
                "label": label.strip(),
                "case_id": case_id,
                "measure_type": measure_type,
                "incremental_cost": {
                    "value": cost_value,
                    "unit": cost_unit,
                },
                "physical_basis": physical_basis.strip(),
                "constraints": [value.strip() for value in constraints],
            }
        )
    if len(cost_units) != 1:
        raise ValueError("all protection option costs must use the same unit")
    return normalized, next(iter(cost_units))


def _protection_weights(
    effectiveness_weight: Any,
    cost_weight: Any,
) -> JSONDict:
    effectiveness = _finite_number(
        effectiveness_weight,
        "effectiveness_weight",
        minimum=0.0,
        maximum=1.0,
    )
    cost = _finite_number(
        cost_weight,
        "cost_weight",
        minimum=0.0,
        maximum=1.0,
    )
    if not math.isclose(effectiveness + cost, 1.0, abs_tol=1.0e-9):
        raise ValueError("effectiveness_weight and cost_weight must sum to 1")
    return {"effectiveness": effectiveness, "cost": cost}


def _normalize_metric_limits(
    metric_limits: list[JSONDict],
    objectives: list[JSONDict],
) -> list[JSONDict]:
    if not isinstance(metric_limits, list) or len(metric_limits) > 16:
        raise ValueError("metric_limits must contain up to 16 objects")
    objective_keys = {_objective_key(item) for item in objectives}
    normalized = []
    seen: set[str] = set()
    for index, item in enumerate(metric_limits):
        if not isinstance(item, dict):
            raise ValueError(f"metric_limits[{index}] must be an object")
        if sorted(item) != ["maximum_value", "metric_id", "object_id"]:
            raise ValueError(
                f"metric_limits[{index}] requires object_id, metric_id, and "
                "maximum_value only"
            )
        key = _objective_key(item)
        if key not in objective_keys:
            raise ValueError(
                f"metric limit {key} does not match a ranking objective"
            )
        if key in seen:
            raise ValueError(f"duplicate metric limit: {key}")
        seen.add(key)
        normalized.append(
            {
                "object_id": item["object_id"],
                "metric_id": item["metric_id"],
                "maximum_value": _finite_number(
                    item["maximum_value"],
                    f"metric_limits[{index}].maximum_value",
                ),
            }
        )
    return normalized


def _protection_compatibility_blockers(
    records: dict[str, JSONDict],
    objectives: list[JSONDict],
    *,
    allow_mixed_mesh: bool,
    allow_semantic_variants: bool,
) -> list[str]:
    blockers = []
    fingerprints = [item["fingerprints"] for item in records.values()]
    for field in (
        "layout_fingerprint",
        "material_fingerprint",
        "generator_fingerprint",
    ):
        if len({item[field] for item in fingerprints}) > 1:
            blockers.append(field)
    if (
        not allow_mixed_mesh
        and len({item["mesh_fingerprint"] for item in fingerprints}) > 1
    ):
        blockers.append("mesh_fingerprint")
    semantic_mixed = (
        len({item["semantic_fingerprint"] for item in fingerprints}) > 1
    )
    if semantic_mixed and not allow_semantic_variants:
        blockers.append("semantic_fingerprint")
    for objective in objectives:
        key = _objective_key(objective)
        categories = set()
        units = set()
        for record in records.values():
            objects = record.get("objects", {})
            item = objects.get(objective["object_id"])
            if not isinstance(item, dict):
                blockers.append(f"missing_object:{key}")
                continue
            categories.add(item.get("category"))
            metric = item.get("metrics", {}).get(objective["metric_id"])
            if not isinstance(metric, dict):
                blockers.append(f"missing_metric:{key}")
                continue
            units.add(metric.get("unit"))
        if len(categories) > 1:
            blockers.append(f"object_category:{key}")
        if len(units) > 1:
            blockers.append(f"metric_unit:{key}")
    return sorted(set(blockers))


def _registered_metric(
    record: JSONDict,
    object_id: str,
    metric_id: str,
) -> JSONDict:
    item = record.get("objects", {}).get(object_id)
    if not isinstance(item, dict):
        raise ValueError(
            f"semantic object {object_id!r} is missing from case "
            f"{record.get('case_id')}"
        )
    metric = item.get("metrics", {}).get(metric_id)
    if not isinstance(metric, dict):
        raise ValueError(
            f"metric {metric_id!r} for object {object_id!r} is missing from "
            f"case {record.get('case_id')}"
        )
    value = _finite_number(
        metric.get("value"),
        f"{record.get('case_id')}:{object_id}:{metric_id}",
    )
    unit = metric.get("unit")
    if not isinstance(unit, str) or not unit:
        raise ValueError(
            f"metric unit for {object_id!r}/{metric_id!r} is invalid"
        )
    return {"value": value, "unit": unit}


def _benefit_fraction(baseline: float, candidate: float) -> float:
    if baseline != 0.0:
        return (baseline - candidate) / abs(baseline)
    if candidate == 0.0:
        return 0.0
    return -1.0


def _mark_pareto_options(options: list[JSONDict]) -> None:
    feasible = [item for item in options if item["feasible"]]
    for item in feasible:
        cost = float(item["incremental_cost"]["value"])
        benefit = float(item["benefit_fraction"])
        dominated = any(
            other is not item
            and float(other["incremental_cost"]["value"]) <= cost
            and float(other["benefit_fraction"]) >= benefit
            and (
                float(other["incremental_cost"]["value"]) < cost
                or float(other["benefit_fraction"]) > benefit
            )
            for other in feasible
        )
        item["pareto_efficient"] = not dominated


def _write_protection_ranking(
    reference: Path,
    matrix: JSONDict,
    result: JSONDict,
) -> JSONDict:
    persisted = dict(result)
    persisted["ranking_id"] = f"protection_{_digest(persisted)[:16]}"
    path = (
        _study_dir(reference, str(result["study_id"]))
        / "protection_rankings"
        / f"{persisted['ranking_id']}.json"
    )
    with ProjectLock(reference.name, namespace="phase16b_study"):
        current_matrix = _load_matrix(reference, str(result["study_id"]))
        if current_matrix["matrix_id"] != matrix["matrix_id"]:
            raise ValueError(
                "Phase 16B case matrix changed while ranking protection options"
            )
        index_path = (
            _study_dir(reference, str(result["study_id"]))
            / "result_index.json"
        )
        current_index = _load_result_index(index_path, current_matrix)
        for evidence in result["result_evidence"]:
            current = current_index["results"].get(evidence["case_id"])
            if (
                not isinstance(current, dict)
                or current.get("model_sha256") != evidence["model_sha256"]
            ):
                raise ValueError(
                    "Phase 16B registered result changed while ranking "
                    "protection options"
                )
        _atomic_write_json(path, persisted)
    persisted["relative_ranking_path"] = _relative(reference, path)
    return persisted


def _finite_number(
    raw: Any,
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    strictly_greater_than_minimum: bool = False,
) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None:
        invalid = (
            value <= minimum
            if strictly_greater_than_minimum
            else value < minimum
        )
        if invalid:
            operator = "greater than" if strictly_greater_than_minimum else "at least"
            raise ValueError(f"{name} must be {operator} {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return value


def _objective_key(item: JSONDict) -> str:
    return f"{item.get('object_id')}::{item.get('metric_id')}"


def _analysis_compatibility_differences(rows: list[JSONDict]) -> list[str]:
    fields = (
        "layout_fingerprint",
        "semantic_fingerprint",
        "material_fingerprint",
        "generator_fingerprint",
    )
    return [
        field
        for field in fields
        if len({row["fingerprints"][field] for row in rows}) > 1
    ]


def _response_statistics(
    values: list[float],
    units: set[str],
    confidence_level: float,
    metric_id: str,
) -> JSONDict:
    if not values:
        return {
            "status": "unavailable",
            "sample_count": 0,
            "unit": METRIC_DEFINITIONS[metric_id]["unit"],
        }
    sample_count = len(values)
    average = statistics.fmean(values)
    sample_std = statistics.stdev(values) if sample_count >= 2 else 0.0
    standard_error = sample_std / math.sqrt(sample_count) if sample_count else 0.0
    z_value = NormalDist().inv_cdf(0.5 + 0.5 * confidence_level)
    margin = z_value * standard_error
    alpha = 1.0 - confidence_level
    ordered = sorted(values)
    return {
        "status": "available",
        "sample_count": sample_count,
        "unit": next(iter(units)) if len(units) == 1 else "incompatible",
        "minimum": min(values),
        "maximum": max(values),
        "range": max(values) - min(values),
        "mean": average,
        "sample_standard_deviation": sample_std,
        "standard_error": standard_error,
        "mean_confidence_interval": {
            "confidence_level": confidence_level,
            "method": "normal_approximation",
            "lower": average - margin,
            "upper": average + margin,
        },
        "central_observed_interval": {
            "confidence_level": confidence_level,
            "method": "linear_empirical_quantile",
            "lower": _quantile(ordered, 0.5 * alpha),
            "upper": _quantile(ordered, 1.0 - 0.5 * alpha),
        },
    }


def _parameter_sensitivity(rows: list[JSONDict]) -> list[JSONDict]:
    common_parameters = set(rows[0]["parameters"])
    for row in rows[1:]:
        common_parameters.intersection_update(row["parameters"])
    response_values = [float(row["value"]) for row in rows]
    candidates: list[JSONDict] = []
    for parameter_id in sorted(common_parameters):
        raw_values = [row["parameters"][parameter_id] for row in rows]
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in raw_values
        ):
            continue
        values = [float(value) for value in raw_values]
        unique_values = sorted(set(values))
        if len(unique_values) < 2:
            continue
        pearson = _pearson(values, response_values)
        slope = _linear_slope(values, response_values)
        candidates.append(
            {
                "parameter_id": parameter_id,
                "uncertainty_source": (
                    "model_resolution"
                    if parameter_id == "near_mesh_size_m"
                    else "input"
                ),
                "sample_count": len(values),
                "unique_value_count": len(unique_values),
                "minimum": min(values),
                "maximum": max(values),
                "pearson_r": pearson,
                "absolute_pearson_r": abs(pearson),
                "linear_slope": slope,
                "screening_score": pearson * pearson,
            }
        )
    total_score = sum(item["screening_score"] for item in candidates)
    for item in candidates:
        item["screening_contribution"] = (
            item["screening_score"] / total_score if total_score > 0.0 else 0.0
        )
        item["notice"] = "Correlation-based screening; not a causal contribution."
    candidates.sort(
        key=lambda item: (
            -float(item["screening_contribution"]),
            str(item["parameter_id"]),
        )
    )
    return candidates


def _fidelity_difference(rows: list[JSONDict]) -> JSONDict:
    groups: dict[str, list[JSONDict]] = {}
    for row in rows:
        parameters = row["parameters"]
        mesh_value = parameters.get("near_mesh_size_m")
        if isinstance(mesh_value, bool) or not isinstance(mesh_value, (int, float)):
            continue
        pairing_controls = {
            key: value
            for key, value in parameters.items()
            if key != "near_mesh_size_m"
        }
        groups.setdefault(_digest(pairing_controls), []).append(row)

    pairs: list[JSONDict] = []
    for grouped_rows in groups.values():
        meshes = {
            float(row["parameters"]["near_mesh_size_m"])
            for row in grouped_rows
        }
        if len(meshes) < 2:
            continue
        fine = min(
            grouped_rows,
            key=lambda row: float(row["parameters"]["near_mesh_size_m"]),
        )
        coarse = max(
            grouped_rows,
            key=lambda row: float(row["parameters"]["near_mesh_size_m"]),
        )
        signed = float(fine["value"]) - float(coarse["value"])
        absolute = abs(signed)
        fine_value = float(fine["value"])
        pairs.append(
            {
                "pairing_parameters": {
                    key: value
                    for key, value in fine["parameters"].items()
                    if key != "near_mesh_size_m"
                },
                "fine_case_id": fine["case_id"],
                "fine_mesh_size_m": float(
                    fine["parameters"]["near_mesh_size_m"]
                ),
                "fine_value": fine_value,
                "coarse_case_id": coarse["case_id"],
                "coarse_mesh_size_m": float(
                    coarse["parameters"]["near_mesh_size_m"]
                ),
                "coarse_value": float(coarse["value"]),
                "fine_minus_coarse": signed,
                "absolute_difference": absolute,
                "relative_difference_to_fine": (
                    absolute / abs(fine_value) if fine_value != 0.0 else None
                ),
            }
        )
    absolute_differences = [item["absolute_difference"] for item in pairs]
    relative_differences = [
        item["relative_difference_to_fine"]
        for item in pairs
        if item["relative_difference_to_fine"] is not None
    ]
    return {
        "status": "available" if pairs else "no_paired_mesh_levels",
        "paired_group_count": len(pairs),
        "pairs": pairs,
        "mean_absolute_difference": (
            statistics.fmean(absolute_differences)
            if absolute_differences
            else None
        ),
        "maximum_absolute_difference": (
            max(absolute_differences) if absolute_differences else None
        ),
        "mean_relative_difference_to_fine": (
            statistics.fmean(relative_differences)
            if relative_differences
            else None
        ),
        "notice": (
            "Pairs differ only by near_mesh_size_m within the controlled matrix."
        ),
    }


def _sample_coverage(
    matrix: JSONDict,
    registered_ids: list[str],
    rows: list[JSONDict],
    selected_ids: list[str],
) -> JSONDict:
    matrix_case_count = int(matrix["case_count"])
    analyzed_case_ids = [row["case_id"] for row in rows]
    parameters: JSONDict = {}
    for parameter_id, planned_values in matrix["dimensions"].items():
        registered_values = sorted(
            {
                float(row["parameters"][parameter_id])
                for row in rows
                if parameter_id in row["parameters"]
            }
        )
        parameters[parameter_id] = {
            "planned_values": planned_values,
            "planned_unique_count": len(planned_values),
            "analyzed_values": registered_values,
            "analyzed_unique_count": len(registered_values),
            "minimum": min(registered_values) if registered_values else None,
            "maximum": max(registered_values) if registered_values else None,
        }
    return {
        "matrix_case_count": matrix_case_count,
        "registered_case_count": len(registered_ids),
        "selected_case_count": len(selected_ids),
        "analyzed_case_count": len(rows),
        "registered_fraction": (
            len(registered_ids) / matrix_case_count if matrix_case_count else 0.0
        ),
        "analyzed_fraction": (
            len(rows) / matrix_case_count if matrix_case_count else 0.0
        ),
        "analyzed_case_ids": analyzed_case_ids,
        "parameters": parameters,
    }


def _pearson(x_values: list[float], y_values: list[float]) -> float:
    mean_x = statistics.fmean(x_values)
    mean_y = statistics.fmean(y_values)
    centered_x = [value - mean_x for value in x_values]
    centered_y = [value - mean_y for value in y_values]
    numerator = sum(x * y for x, y in zip(centered_x, centered_y, strict=True))
    denominator = math.sqrt(
        sum(value * value for value in centered_x)
        * sum(value * value for value in centered_y)
    )
    return numerator / denominator if denominator > 0.0 else 0.0


def _linear_slope(x_values: list[float], y_values: list[float]) -> float:
    mean_x = statistics.fmean(x_values)
    mean_y = statistics.fmean(y_values)
    denominator = sum((value - mean_x) ** 2 for value in x_values)
    if denominator == 0.0:
        return 0.0
    return sum(
        (x - mean_x) * (y - mean_y)
        for x, y in zip(x_values, y_values, strict=True)
    ) / denominator


def _quantile(ordered: list[float], probability: float) -> float:
    if not ordered:
        raise ValueError("quantile requires at least one value")
    if len(ordered) == 1:
        return ordered[0]
    position = min(1.0, max(0.0, probability)) * (len(ordered) - 1)
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    fraction = position - lower_index
    return (
        ordered[lower_index] * (1.0 - fraction)
        + ordered[upper_index] * fraction
    )


def _record_observed_controls(record: JSONDict) -> JSONDict:
    observed = record.get("observed_controls")
    if isinstance(observed, dict):
        return observed
    parameters = record.get("parameters")
    return parameters if isinstance(parameters, dict) else {}


def _validated_spatial_bounds(raw: object) -> JSONDict:
    if not isinstance(raw, dict):
        raise ValueError("spatial bounds must be an object")
    lower = raw.get("min")
    upper = raw.get("max")
    if not isinstance(lower, list) or not isinstance(upper, list):
        raise ValueError("spatial bounds require min/max arrays")
    if len(lower) != 3 or len(upper) != 3:
        raise ValueError("spatial bounds must contain three axes")
    normalized_lower: list[float] = []
    normalized_upper: list[float] = []
    for axis, (raw_lower, raw_upper) in enumerate(
        zip(lower, upper, strict=True)
    ):
        if (
            isinstance(raw_lower, bool)
            or isinstance(raw_upper, bool)
            or not isinstance(raw_lower, (int, float))
            or not isinstance(raw_upper, (int, float))
        ):
            raise ValueError(f"spatial bounds axis {axis} must be numeric")
        low = float(raw_lower)
        high = float(raw_upper)
        if not math.isfinite(low) or not math.isfinite(high) or low > high:
            raise ValueError(f"spatial bounds axis {axis} is invalid")
        normalized_lower.append(low)
        normalized_upper.append(high)
    return {"min": normalized_lower, "max": normalized_upper}


def _refinement_regions(
    controls: list[JSONDict],
    object_bounds: JSONDict,
    domain_bounds: JSONDict,
    padding_distance: float,
    target_mesh: float,
) -> list[JSONDict]:
    source_bounds = {
        "min": [math.inf, math.inf, math.inf],
        "max": [-math.inf, -math.inf, -math.inf],
    }
    for item in controls:
        center = [
            float(item["blast_center_x_m"]),
            float(item["blast_center_y_m"]),
            float(item["blast_center_z_m"]),
        ]
        radial = 0.5 * float(item["tnt_diameter_m"])
        half_length = 0.5 * float(item["tnt_length_m"])
        half_extents = [radial, radial, half_length]
        for axis in range(3):
            source_bounds["min"][axis] = min(
                source_bounds["min"][axis],
                center[axis] - half_extents[axis],
            )
            source_bounds["max"][axis] = max(
                source_bounds["max"][axis],
                center[axis] + half_extents[axis],
            )
    source_region = _expand_clip_bounds(
        source_bounds,
        padding_distance,
        domain_bounds,
    )
    target_region = _expand_clip_bounds(
        object_bounds,
        padding_distance,
        domain_bounds,
    )
    corridor_base = {
        "min": [
            min(source_bounds["min"][axis], object_bounds["min"][axis])
            for axis in range(3)
        ],
        "max": [
            max(source_bounds["max"][axis], object_bounds["max"][axis])
            for axis in range(3)
        ],
    }
    corridor_padding = max(padding_distance, 4.0 * target_mesh)
    corridor_region = _expand_clip_bounds(
        corridor_base,
        corridor_padding,
        domain_bounds,
    )
    return [
        {
            "region_id": "blast_source_region",
            "region_type": "blast_source",
            "geometry": "axis_aligned_bounds",
            "bounds_m": source_region["bounds_m"],
            "clipped_to_domain": source_region["clipped_to_domain"],
            "target_mesh_size_m": target_mesh,
            "purpose": "Resolve TNT initialization and the early pressure front.",
        },
        {
            "region_id": "propagation_corridor_region",
            "region_type": "propagation_corridor",
            "geometry": "axis_aligned_corridor_envelope",
            "bounds_m": corridor_region["bounds_m"],
            "clipped_to_domain": corridor_region["clipped_to_domain"],
            "target_mesh_size_m": target_mesh,
            "purpose": "Reduce numerical diffusion between the sampled blast envelope and target.",
        },
        {
            "region_id": "target_object_region",
            "region_type": "target_object",
            "geometry": "axis_aligned_bounds",
            "bounds_m": target_region["bounds_m"],
            "clipped_to_domain": target_region["clipped_to_domain"],
            "target_mesh_size_m": target_mesh,
            "purpose": "Resolve local loading and response around the semantic object.",
        },
    ]


def _expand_clip_bounds(
    bounds: JSONDict,
    padding: float,
    domain: JSONDict,
) -> JSONDict:
    expanded = {
        "min": [float(value) - padding for value in bounds["min"]],
        "max": [float(value) + padding for value in bounds["max"]],
    }
    clipped = {
        "min": [
            max(expanded["min"][axis], domain["min"][axis])
            for axis in range(3)
        ],
        "max": [
            min(expanded["max"][axis], domain["max"][axis])
            for axis in range(3)
        ],
    }
    return {
        "bounds_m": clipped,
        "clipped_to_domain": clipped != expanded,
    }


def _write_refinement_plan(
    reference: Path,
    matrix: JSONDict,
    plan: JSONDict,
) -> JSONDict:
    persisted = dict(plan)
    persisted.setdefault("created_at", _utc_now())
    persisted["plan_id"] = f"refinement_{_digest(persisted)[:16]}"
    plan_path = (
        _study_dir(reference, str(plan["study_id"]))
        / "refinement_plans"
        / (
            f"{safe_project_name(str(plan['object_id']))}_"
            f"{safe_project_name(str(plan['metric_id']))}.json"
        )
    )
    with ProjectLock(reference.name, namespace="phase16b_study"):
        current_matrix = _load_matrix(reference, str(plan["study_id"]))
        if current_matrix["matrix_id"] != matrix["matrix_id"]:
            raise ValueError("Phase 16B case matrix changed during refinement planning")
        _atomic_write_json(plan_path, persisted)
    persisted["relative_plan_path"] = _relative(reference, plan_path)
    return persisted


def _surrogate_feature_ids(samples: list[JSONDict]) -> list[str]:
    if not samples:
        return []
    common = set(samples[0]["parameters"])
    for sample in samples[1:]:
        common.intersection_update(sample["parameters"])
    feature_ids = []
    for parameter_id in sorted(common):
        values = [sample["parameters"][parameter_id] for sample in samples]
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in values
        ):
            continue
        if len({float(value) for value in values}) >= 2:
            feature_ids.append(parameter_id)
    return feature_ids


def _surrogate_features(
    samples: list[JSONDict],
    feature_ids: list[str],
) -> list[JSONDict]:
    rows = []
    for parameter_id in feature_ids:
        values = sorted(
            {float(sample["parameters"][parameter_id]) for sample in samples}
        )
        rows.append(
            {
                "parameter_id": parameter_id,
                "uncertainty_source": (
                    "model_resolution"
                    if parameter_id == "near_mesh_size_m"
                    else "input"
                ),
                "minimum": values[0],
                "maximum": values[-1],
                "sampled_values": values,
                "sampled_unique_count": len(values),
            }
        )
    return rows


def _normalize_surrogate_samples(
    samples: list[JSONDict],
    features: list[JSONDict],
) -> list[JSONDict]:
    normalized = []
    for sample in samples:
        normalized_parameters = {}
        selected_parameters = {}
        for feature in features:
            parameter_id = feature["parameter_id"]
            value = float(sample["parameters"][parameter_id])
            minimum = float(feature["minimum"])
            maximum = float(feature["maximum"])
            selected_parameters[parameter_id] = value
            normalized_parameters[parameter_id] = (
                (value - minimum) / (maximum - minimum)
            )
        normalized.append(
            {
                "case_id": sample["case_id"],
                "parameters": selected_parameters,
                "normalized_parameters": normalized_parameters,
                "value": float(sample["value"]),
                "unit": sample["unit"],
                "model_sha256": sample["model_sha256"],
            }
        )
    normalized.sort(key=lambda item: item["case_id"])
    return normalized


def _leave_one_out_validation(
    samples: list[JSONDict],
    neighbor_count: int,
) -> JSONDict:
    residual_rows = []
    for held_out in samples:
        training = [
            sample
            for sample in samples
            if sample["case_id"] != held_out["case_id"]
        ]
        neighbors = _surrogate_neighbors(
            held_out["normalized_parameters"],
            training,
        )
        estimate, used = _knn_estimate(neighbors, neighbor_count)
        actual = float(held_out["value"])
        residual = estimate - actual
        residual_rows.append(
            {
                "case_id": held_out["case_id"],
                "actual": actual,
                "predicted": estimate,
                "residual": residual,
                "absolute_error": abs(residual),
                "neighbor_case_ids": [
                    item["case_id"] for item in used
                ],
            }
        )
    absolute_errors = [row["absolute_error"] for row in residual_rows]
    squared_errors = [row["residual"] ** 2 for row in residual_rows]
    percentage_errors = [
        row["absolute_error"] / abs(row["actual"])
        for row in residual_rows
        if row["actual"] != 0.0
    ]
    return {
        "status": "completed",
        "method": "leave_one_out",
        "sample_count": len(samples),
        "mean_absolute_error": statistics.fmean(absolute_errors),
        "rmse": math.sqrt(statistics.fmean(squared_errors)),
        "maximum_absolute_error": max(absolute_errors),
        "mean_absolute_percentage_error": (
            statistics.fmean(percentage_errors)
            if percentage_errors
            else None
        ),
        "residuals": residual_rows,
    }


def _training_coverage_radius(samples: list[JSONDict]) -> float:
    nearest_distances = []
    for sample in samples:
        others = [
            item
            for item in samples
            if item["case_id"] != sample["case_id"]
        ]
        neighbors = _surrogate_neighbors(
            sample["normalized_parameters"],
            others,
        )
        nearest_distances.append(float(neighbors[0]["distance"]))
    return max(nearest_distances)


def _surrogate_neighbors(
    query: JSONDict,
    samples: list[JSONDict],
) -> list[JSONDict]:
    rows = []
    for sample in samples:
        normalized = sample["normalized_parameters"]
        distance = math.sqrt(
            sum(
                (
                    float(query[parameter_id])
                    - float(normalized[parameter_id])
                )
                ** 2
                for parameter_id in query
            )
        )
        rows.append(
            {
                "case_id": sample["case_id"],
                "distance": distance,
                "value": float(sample["value"]),
                "parameters": sample["parameters"],
            }
        )
    rows.sort(key=lambda item: (item["distance"], item["case_id"]))
    return rows


def _knn_estimate(
    neighbors: list[JSONDict],
    neighbor_count: int,
) -> tuple[float, list[JSONDict]]:
    if not neighbors:
        raise ValueError("surrogate prediction requires at least one neighbor")
    exact = [item for item in neighbors if float(item["distance"]) == 0.0]
    if exact:
        return (
            statistics.fmean(float(item["value"]) for item in exact),
            exact,
        )
    used = neighbors[: min(neighbor_count, len(neighbors))]
    weighted = [
        (1.0 / (float(item["distance"]) ** 2), float(item["value"]))
        for item in used
    ]
    weight_sum = sum(weight for weight, _value in weighted)
    estimate = sum(weight * value for weight, value in weighted) / weight_sum
    return estimate, used


def _write_surrogate_model(
    reference: Path,
    matrix: JSONDict,
    model: JSONDict,
) -> JSONDict:
    persisted = dict(model)
    persisted["model_id"] = f"surrogate_{_digest(persisted)[:16]}"
    model_path = _surrogate_model_path(
        reference,
        str(model["study_id"]),
        str(model["object_id"]),
        str(model["metric_id"]),
    )
    with ProjectLock(reference.name, namespace="phase16b_study"):
        current_matrix = _load_matrix(reference, str(model["study_id"]))
        if current_matrix["matrix_id"] != matrix["matrix_id"]:
            raise ValueError("Phase 16B case matrix changed during surrogate training")
        _atomic_write_json(model_path, persisted)
    persisted["relative_model_path"] = _relative(reference, model_path)
    return persisted


def _surrogate_model_path(
    reference: Path,
    study_id: str,
    object_id: str,
    metric_id: str,
) -> Path:
    return (
        _study_dir(reference, safe_project_name(study_id))
        / "surrogates"
        / (
            f"{safe_project_name(object_id)}_"
            f"{safe_project_name(metric_id)}.json"
        )
    )


def _validate_surrogate_model(
    model: JSONDict,
    matrix: JSONDict,
    object_id: str,
    metric_id: str,
) -> None:
    if model.get("schema_version") != SURROGATE_MODEL_SCHEMA_VERSION:
        raise ValueError("unsupported Phase 16B surrogate model schema")
    if model.get("matrix_id") != matrix["matrix_id"]:
        raise ValueError("Phase 16B surrogate model belongs to another matrix")
    if model.get("reference_model_sha256") != matrix["reference_model_sha256"]:
        raise ValueError("Phase 16B surrogate model is stale for the reference model")
    if model.get("object_id") != object_id or model.get("metric_id") != metric_id:
        raise ValueError("Phase 16B surrogate model target does not match the request")
    expected_id = f"surrogate_{_digest({
        key: value
        for key, value in model.items()
        if key != 'model_id'
    })[:16]}"
    if model.get("model_id") != expected_id:
        raise ValueError("Phase 16B surrogate model integrity check failed")


def _surrogate_staleness_reasons(
    reference: Path,
    matrix: JSONDict,
    model: JSONDict,
) -> list[str]:
    index_path = (
        _study_dir(reference, str(model["study_id"]))
        / "result_index.json"
    )
    if not index_path.is_file():
        return ["result repository is missing"]
    index = _load_result_index(index_path, matrix)
    reasons = []
    for sample in model.get("training_samples", []):
        case_id = sample.get("case_id")
        entry = index["results"].get(case_id)
        if not isinstance(entry, dict):
            reasons.append(f"training case {case_id} is no longer registered")
        elif entry.get("model_sha256") != sample.get("model_sha256"):
            reasons.append(f"training case {case_id} changed after training")
    return reasons


def _write_surrogate_prediction(
    reference: Path,
    prediction: JSONDict,
) -> JSONDict:
    persisted = dict(prediction)
    persisted.setdefault("created_at", _utc_now())
    persisted["prediction_id"] = f"prediction_{_digest(persisted)[:16]}"
    prediction_path = (
        _study_dir(reference, str(prediction["study_id"]))
        / "surrogate_predictions"
        / (
            f"{safe_project_name(str(prediction['object_id']))}_"
            f"{safe_project_name(str(prediction['metric_id']))}_"
            f"{persisted['prediction_id']}.json"
        )
    )
    with ProjectLock(reference.name, namespace="phase16b_study"):
        _atomic_write_json(prediction_path, persisted)
    persisted["relative_prediction_path"] = _relative(
        reference,
        prediction_path,
    )
    return persisted


def _normalize_dimensions(dimensions: JSONDict, resolved_spec: JSONDict) -> JSONDict:
    if not isinstance(dimensions, dict) or not dimensions:
        raise ValueError("dimensions must be a non-empty object")
    unknown = sorted(set(dimensions) - set(_CONTROLLED_PARAMETERS))
    if unknown:
        raise ValueError(
            "unsupported controlled parameter(s): " + ", ".join(unknown)
        )
    normalized: JSONDict = {}
    for parameter_id, raw_values in dimensions.items():
        if not isinstance(raw_values, list) or not raw_values:
            raise ValueError(f"{parameter_id} must be a non-empty array")
        if len(raw_values) > MAX_VALUES_PER_PARAMETER:
            raise ValueError(
                f"{parameter_id} exceeds {MAX_VALUES_PER_PARAMETER} controlled values"
            )
        values = [
            _controlled_number(parameter_id, raw, resolved_spec)
            for raw in raw_values
        ]
        normalized[parameter_id] = sorted(set(values))
    case_count = math.prod(len(values) for values in normalized.values())
    if case_count > MAX_MATRIX_CASES:
        raise ValueError(
            f"controlled case matrix exceeds the maximum of {MAX_MATRIX_CASES} cases"
        )
    return dict(sorted(normalized.items()))


def _controlled_number(
    parameter_id: str,
    raw: Any,
    resolved_spec: JSONDict,
) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{parameter_id} values must be finite numbers")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"{parameter_id} values must be finite numbers")
    rule = _CONTROLLED_PARAMETERS[parameter_id]
    if "enum" in rule and value not in rule["enum"]:
        raise ValueError(
            f"{parameter_id} must be one of {rule['enum']}"
        )
    minimum = rule.get("minimum")
    maximum = rule.get("maximum")
    if minimum is not None and value < float(minimum):
        raise ValueError(f"{parameter_id} must be at least {minimum}")
    if maximum is not None and value > float(maximum):
        raise ValueError(f"{parameter_id} must be at most {maximum}")
    if "domain_axis" in rule:
        axis = int(rule["domain_axis"])
        domain = resolved_spec.get("domain", {})
        lower = float(domain["min_m"][axis])
        upper = float(domain["max_m"][axis])
        if value < lower or value > upper:
            raise ValueError(
                f"{parameter_id} must stay inside the ALE domain [{lower}, {upper}]"
            )
    return value


def _resolved_controls(base_spec: JSONDict, parameters: JSONDict) -> JSONDict:
    explosive = base_spec["explosive"]
    density = float(explosive["density_kg_per_m3"])
    mass = float(parameters.get("tnt_mass_kg", explosive["mass_kg"]))
    diameter = float(parameters.get("tnt_diameter_m", explosive["diameter_m"]))
    radius = 0.5 * diameter
    length = mass / (density * math.pi * radius * radius)
    base_center = [float(value) for value in explosive["base_center_m"]]
    # Preserve the reference charge base when mass changes unless the matrix
    # explicitly controls the blast-center elevation.
    default_center_z = base_center[2] + 0.5 * length
    center = [
        float(parameters.get("blast_center_x_m", base_center[0])),
        float(parameters.get("blast_center_y_m", base_center[1])),
        float(parameters.get("blast_center_z_m", default_center_z)),
    ]
    domain_min = [float(value) for value in base_spec["domain"]["min_m"]]
    domain_max = [float(value) for value in base_spec["domain"]["max_m"]]
    if center[0] - radius < domain_min[0] or center[0] + radius > domain_max[0]:
        raise ValueError("TNT cylinder exceeds the ALE domain in x")
    if center[1] - radius < domain_min[1] or center[1] + radius > domain_max[1]:
        raise ValueError("TNT cylinder exceeds the ALE domain in y")
    if center[2] - 0.5 * length < domain_min[2] or center[2] + 0.5 * length > domain_max[2]:
        raise ValueError("TNT cylinder exceeds the ALE domain in z")
    return {
        "tnt_mass_kg": mass,
        "tnt_diameter_m": diameter,
        "tnt_length_m": length,
        "blast_center_m": center,
        "near_mesh_size_m": float(
            parameters.get(
                "near_mesh_size_m",
                base_spec["mesh"]["near_size_m"],
            )
        ),
        "end_time_s": float(
            parameters.get("end_time_s", base_spec["analysis"]["end_time_s"])
        ),
    }


def _case_parameter_mismatches(
    expected: JSONDict,
    resolved_spec: JSONDict,
) -> list[str]:
    actual = _observed_controls(resolved_spec)
    mismatches = []
    for parameter_id, expected_value in expected.items():
        actual_value = actual[parameter_id]
        if not math.isclose(
            float(actual_value),
            float(expected_value),
            rel_tol=1e-9,
            abs_tol=1e-12,
        ):
            mismatches.append(
                f"{parameter_id}: expected {expected_value}, got {actual_value}"
            )
    return mismatches


def _observed_controls(resolved_spec: JSONDict) -> JSONDict:
    explosive = resolved_spec["explosive"]
    base_center = [float(value) for value in explosive["base_center_m"]]
    center_z = base_center[2] + 0.5 * float(explosive["length_m"])
    return {
        "tnt_mass_kg": float(explosive["mass_kg"]),
        "tnt_diameter_m": float(explosive["diameter_m"]),
        "tnt_length_m": float(explosive["length_m"]),
        "blast_center_x_m": base_center[0],
        "blast_center_y_m": base_center[1],
        "blast_center_z_m": center_z,
        "near_mesh_size_m": float(resolved_spec["mesh"]["near_size_m"]),
        "end_time_s": float(resolved_spec["analysis"]["end_time_s"]),
    }


def _repository_objects(assessment: JSONDict) -> JSONDict:
    objects: JSONDict = {}
    for item in assessment["objects"]:
        metrics: JSONDict = {}
        for metric_id, metric in item.get("metrics", {}).items():
            if not isinstance(metric, dict) or not metric.get("available"):
                continue
            metrics[metric_id] = {
                "value": float(metric["value"]),
                "unit": str(metric["unit"]),
            }
        objects[item["object_id"]] = {
            "category": item["category"],
            "part_ids": item["part_ids"],
            **(
                {"bounds_m": item["bounds_m"]}
                if isinstance(item.get("bounds_m"), dict)
                else {}
            ),
            "risk": item["risk"],
            "metrics": metrics,
        }
    return objects


def _result_fingerprints(
    model: JSONDict,
    resolved_spec: JSONDict,
    assessment: JSONDict,
) -> JSONDict:
    metadata = model.get("metadata", {})
    semantic_contract = {
        "schema_version": metadata.get("city_semantic_schema_version"),
        "objects": sorted(
            [
            {
                "object_id": item["object_id"],
                "category": item["category"],
                "part_ids": item["part_ids"],
                "bounds_m": item.get("bounds_m"),
            }
            for item in assessment["objects"]
            ],
            key=lambda item: item["object_id"],
        ),
    }
    explosive = resolved_spec.get("explosive", {})
    material_contract = {
        "structure": resolved_spec.get("material"),
        "explosive": {
            "material": explosive.get("material"),
            "density_kg_per_m3": explosive.get("density_kg_per_m3"),
        },
    }
    generator_contract = {
        "model_schema_version": model.get("schema_version"),
        "validation_profile": metadata.get("validation_profile"),
        "validation_capabilities": sorted(
            metadata.get("validation_capabilities", [])
        ),
    }
    fingerprints = {
        "semantic_fingerprint": _digest(semantic_contract),
        "material_fingerprint": _digest(material_contract),
        "mesh_fingerprint": (
            metadata.get("ale_domain", {}).get("mesh_fingerprint")
            if isinstance(metadata.get("ale_domain"), dict)
            else None
        )
        or _digest(resolved_spec.get("mesh", {})),
        "layout_fingerprint": city_layout_fingerprint(
            resolved_spec,
            metadata,
        ),
        "editor_state_fingerprint": city_editor_state_fingerprint(
            resolved_spec,
            metadata,
        ),
        "generator_fingerprint": _digest(generator_contract),
    }
    fingerprints["compatibility_fingerprint"] = _digest(fingerprints)
    return fingerprints


def _comparison_blockers(
    rows: list[JSONDict],
    allow_mixed_mesh: bool,
) -> list[str]:
    fields = [
        "layout_fingerprint",
        "semantic_fingerprint",
        "material_fingerprint",
        "generator_fingerprint",
    ]
    if not allow_mixed_mesh:
        fields.append("mesh_fingerprint")
    blockers = [
        field
        for field in fields
        if len({row["fingerprints"][field] for row in rows}) > 1
    ]
    for metric_id in METRIC_DEFINITIONS:
        units = {
            row["metrics"][metric_id]["unit"]
            for row in rows
            if metric_id in row["metrics"]
        }
        if len(units) > 1:
            blockers.append(f"metric_unit:{metric_id}")
    return blockers


def _metric_summary(rows: list[JSONDict]) -> JSONDict:
    summary: JSONDict = {}
    for metric_id in METRIC_DEFINITIONS:
        values = [
            float(row["metrics"][metric_id]["value"])
            for row in rows
            if metric_id in row["metrics"]
        ]
        if not values:
            continue
        unit = next(
            row["metrics"][metric_id]["unit"]
            for row in rows
            if metric_id in row["metrics"]
        )
        minimum = min(values)
        maximum = max(values)
        summary[metric_id] = {
            "unit": unit,
            "sample_count": len(values),
            "minimum": minimum,
            "maximum": maximum,
            "range": maximum - minimum,
            "mean": sum(values) / len(values),
        }
    return summary


def _reference_city_project(
    project_path: Path,
) -> tuple[Path, JSONDict, JSONDict]:
    project = project_path.resolve()
    model_path = project / "model.json"
    keyword_path = project / "model.k"
    if not model_path.is_file() or not keyword_path.is_file():
        raise FileNotFoundError(
            "Phase 16B requires a city project with model.json and model.k"
        )
    model = read_json(model_path)
    metadata = model.get("metadata", {})
    spec = model.get("spec", {})
    model_type = (
        metadata.get("model_type")
        if isinstance(metadata, dict)
        else None
    ) or (spec.get("model_type") if isinstance(spec, dict) else None)
    if model_type != "city_street_blast_scene":
        raise ValueError("Phase 16B only supports city_street_blast_scene projects")
    resolved_spec = (
        metadata.get("resolved_spec")
        if isinstance(metadata, dict)
        else None
    )
    if not isinstance(resolved_spec, dict):
        resolved_spec = spec
    if not isinstance(resolved_spec, dict):
        raise ValueError("city project does not contain a resolved specification")
    _resolved_controls(resolved_spec, {})
    return project, model, resolved_spec


def _semantic_schema_version(model: JSONDict) -> str:
    metadata = model.get("metadata", {})
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get("city_semantic_schema_version", ""))


def _study_dir(project: Path, study_id: str) -> Path:
    return project / "artifacts" / "phase16b" / safe_project_name(study_id)


def _load_matrix(project: Path, study_id: str) -> JSONDict:
    path = _study_dir(project, study_id) / "case_matrix.json"
    if not path.is_file():
        raise FileNotFoundError(f"Phase 16B case matrix not found: {path}")
    matrix = read_json(path)
    if matrix.get("schema_version") != CASE_MATRIX_SCHEMA_VERSION:
        raise ValueError("unsupported Phase 16B case matrix schema")
    if matrix.get("reference_model_sha256") != _sha256(project / "model.k"):
        raise ValueError("Phase 16B case matrix is stale for the current reference model")
    return matrix


def _matrix_case(matrix: JSONDict, case_id: str) -> JSONDict:
    for item in matrix["cases"]:
        if item["case_id"] == case_id:
            return item
    raise ValueError(f"unknown case_id: {case_id}")


def _validated_case_ids(
    case_ids: list[str],
    known_ids: list[str],
) -> list[str]:
    if not isinstance(case_ids, list) or not case_ids:
        raise ValueError("case_ids must be a non-empty array")
    if any(not isinstance(case_id, str) or not case_id for case_id in case_ids):
        raise ValueError("case_ids must contain non-empty strings")
    selected = list(dict.fromkeys(case_ids))
    unknown = sorted(set(selected) - set(known_ids))
    if unknown:
        raise ValueError("unknown case_id(s): " + ", ".join(unknown))
    return selected


def _load_or_create_index(path: Path, matrix: JSONDict) -> JSONDict:
    if path.is_file():
        index = read_json(path)
        if index.get("schema_version") != RESULT_REPOSITORY_SCHEMA_VERSION:
            raise ValueError("unsupported Phase 16B result repository schema")
        if index.get("matrix_id") != matrix["matrix_id"]:
            raise ValueError("Phase 16B result repository belongs to another matrix")
        return index
    return {
        "schema_version": RESULT_REPOSITORY_SCHEMA_VERSION,
        "study_id": matrix["study_id"],
        "matrix_id": matrix["matrix_id"],
        "reference_project_name": matrix["reference_project_name"],
        "reference_model_sha256": matrix["reference_model_sha256"],
        "results": {},
        "result_count": 0,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }


def _load_result_index(path: Path, matrix: JSONDict) -> JSONDict:
    index = read_json(path)
    if index.get("schema_version") != RESULT_REPOSITORY_SCHEMA_VERSION:
        raise ValueError("unsupported Phase 16B result repository schema")
    if index.get("matrix_id") != matrix["matrix_id"]:
        raise ValueError("Phase 16B result repository belongs to another matrix")
    if index.get("reference_model_sha256") != matrix["reference_model_sha256"]:
        raise ValueError("Phase 16B result repository is stale for the reference model")
    if not isinstance(index.get("results"), dict):
        raise ValueError("Phase 16B result repository index is malformed")
    return index


def _target_project_name(base: str, study_id: str, suffix: str) -> str:
    raw = f"{base}_{study_id}_{suffix}"
    if len(raw) > 96:
        raw = f"{base[:48]}_{study_id[:30]}_{suffix}"
    return safe_project_name(raw)


def _repository_record_path(reference: Path, relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("Phase 16B result index contains an invalid record path")
    candidate = (reference / relative_path).resolve()
    root = reference.resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError("Phase 16B result record path escaped the reference project")
    return candidate


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write_json(path: Path, data: JSONDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _relative(project: Path, path: Path) -> str:
    return str(path.relative_to(project)).replace("\\", "/")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
