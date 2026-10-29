from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import JSONDict
from .run_evidence import (
    validate_phase14_run_evidence,
    validate_run_record_identity,
)
from .solver_results import (
    parse_d3hsp,
    parse_dbfsi,
    parse_fsi_interfaces,
    parse_nodout,
)


EXCLUDED_SCENE_VARIANT = "open_concrete_tunnel"
CONVERGENCE_METRICS = (
    "peak_coupled_surface_pressure_pa",
    "fsi_impulse_n_s",
    "peak_displacement_m",
)
MIN_PRESSURE_RISE_PA = 1.0
MIN_FORCE_RISE_N = 1.0e-6
MIN_IMPULSE_N_S = 1.0e-9
MIN_DISPLACEMENT_RISE_M = 1.0e-9
MIN_SIGNAL_TO_BASELINE_RATIO = 10.0


def evaluate_phase14_wave_transfer(
    project: Path,
    run_dir: Path,
    *,
    run_record: JSONDict | None = None,
) -> JSONDict:
    project = project.resolve()
    run_dir = run_dir.resolve()
    checks: list[JSONDict] = []
    result: JSONDict = {
        "applicable": False,
        "status": "invalid_evidence",
        "wave_transfer_verified": False,
        "checks": checks,
        "metrics": {},
    }

    if run_record is None:
        run_record, record_error = _read_json_object(run_dir / "run.json")
    else:
        record_error = None
    evidence_integrity = validate_phase14_run_evidence(
        run_dir,
        run_record.get("evidence_manifest") if isinstance(run_record, dict) else None,
    )
    recorded_input_sha256 = (
        run_record.get("input_sha256") if isinstance(run_record, dict) else None
    )
    recorded_model_sha256 = (
        run_record.get("model_json_sha256") if isinstance(run_record, dict) else None
    )
    evidence_integrity["record_error"] = record_error
    evidence_integrity["input_sha256_matches"] = bool(
        isinstance(recorded_input_sha256, str)
        and recorded_input_sha256 == _file_sha256(run_dir / "model.k")
    )
    evidence_integrity["model_json_sha256_matches"] = bool(
        isinstance(recorded_model_sha256, str)
        and recorded_model_sha256 == _file_sha256(run_dir / "model.json")
    )
    evidence_integrity["ok"] = bool(
        evidence_integrity.get("ok")
        and record_error is None
        and evidence_integrity["input_sha256_matches"]
        and evidence_integrity["model_json_sha256_matches"]
    )
    result["evidence_integrity"] = evidence_integrity
    _add_check(
        checks,
        "sealed_run_evidence_valid",
        evidence_integrity["ok"],
        actual=evidence_integrity,
        error=record_error,
    )
    if evidence_integrity["ok"] is not True:
        return result

    run_model_path = run_dir / "model.json"
    model_path = run_model_path
    model_source = "run_model_json"
    model, model_error = _read_json_object(model_path)
    if model_error is not None:
        _add_check(checks, "model_json_readable", False, error=model_error)
        return result
    _add_check(
        checks,
        "model_json_readable",
        True,
        actual={"path": str(model_path), "source": model_source},
    )

    spec = model.get("spec")
    metadata = model.get("metadata")
    if not isinstance(spec, dict) or not isinstance(metadata, dict):
        _add_check(
            checks,
            "model_structure_valid",
            False,
            actual={"spec": type(spec).__name__, "metadata": type(metadata).__name__},
        )
        return result
    _add_check(checks, "model_structure_valid", True, actual=True)

    target_part_id = _target_plate_part_id(metadata)
    deck_evidence, deck_error = _phase14_deck_evidence(
        run_dir / "model.k",
        target_part_id=target_part_id,
    )
    result["model_evidence"] = {
        "model_json_source": model_source,
        "model_json_path": str(model_path),
        "response_nodes_source": "run_model_k",
        "run_model_k_path": str(run_dir / "model.k"),
        "deck": deck_evidence,
    }
    _add_check(
        checks,
        "run_model_k_evidence_parsed",
        deck_error is None,
        actual=deck_evidence,
        error=deck_error,
    )

    _add_check(
        checks,
        "model_evidence_bound_to_run",
        True,
        actual={"model_json_source": model_source},
    )

    geometry = spec.get("geometry")
    geometry = geometry if isinstance(geometry, dict) else {}
    model_type = spec.get("model_type")
    scene_variant = geometry.get("scene_variant")
    is_phase14 = model_type == "ale_blast_scene"
    is_excluded = scene_variant == EXCLUDED_SCENE_VARIANT
    plate_signature_present = bool(
        _positive_integer(deck_evidence.get("coupling_count"))
        and _positive_integer(deck_evidence.get("shell_element_count"))
        and deck_evidence.get("response_node_ids")
    )
    result["applicable"] = is_phase14 and not (
        is_excluded and not plate_signature_present
    )
    _add_check(
        checks,
        "phase14_plate_scene",
        bool(result["applicable"]),
        actual={"model_type": model_type, "scene_variant": scene_variant},
    )
    if not result["applicable"]:
        result["status"] = "not_applicable" if is_phase14 and is_excluded else "invalid_evidence"
        return result

    coupling_count = deck_evidence.get("coupling_count")
    shell_count = deck_evidence.get("shell_element_count")
    response_node_ids = deck_evidence.get("response_node_ids")
    if not isinstance(response_node_ids, list):
        response_node_ids = []
    _add_check(
        checks,
        "metadata_coupling_present",
        _positive_integer(coupling_count),
        actual={"count": coupling_count, "source": "run_model_k"},
    )
    _add_check(
        checks,
        "metadata_shell_elements_present",
        _positive_integer(shell_count),
        actual={"count": shell_count, "source": "run_model_k"},
    )
    _add_check(
        checks,
        "metadata_response_nodes_present",
        bool(response_node_ids),
        actual={"count": len(response_node_ids), "source": "run_model_k"},
    )
    _add_check(
        checks,
        "single_target_coupling_card",
        coupling_count == 1
        and target_part_id is not None
        and deck_evidence.get("coupling_slave_part_ids") == [target_part_id],
        actual={
            "coupling_count": coupling_count,
            "target_part_id": target_part_id,
            "slave_part_ids": deck_evidence.get("coupling_slave_part_ids"),
        },
    )
    _add_check(
        checks,
        "response_nodes_belong_to_target_shell",
        deck_evidence.get("response_nodes_belong_to_target_shell") is True,
        actual={
            "target_part_id": target_part_id,
            "target_shell_node_count": deck_evidence.get("target_shell_node_count"),
            "invalid_response_node_ids": deck_evidence.get(
                "response_nodes_outside_target_shell"
            ),
        },
    )
    _add_check(
        checks,
        "response_nodes_are_translationally_free",
        deck_evidence.get("response_nodes_are_translationally_free") is True,
        actual={
            "constrained_response_node_ids": deck_evidence.get(
                "constrained_response_node_ids"
            )
        },
    )

    d3hsp_path = _first_output(run_dir, "d3hsp")
    d3hsp: JSONDict = {}
    fsi: JSONDict = {}
    if d3hsp_path is None:
        _add_check(checks, "d3hsp_parsed", False, actual=None, error="d3hsp is missing")
    else:
        try:
            d3hsp_text = d3hsp_path.read_text(encoding="utf-8", errors="replace")
            d3hsp = parse_d3hsp(d3hsp_text)
            fsi = parse_fsi_interfaces(d3hsp_text)
        except (OSError, TypeError, ValueError) as exc:
            _add_check(
                checks,
                "d3hsp_parsed",
                False,
                actual=None,
                error=f"{type(exc).__name__}: {exc}",
            )
        else:
            _add_check(checks, "d3hsp_parsed", True, actual=str(d3hsp_path))
    result["d3hsp"] = d3hsp
    result["fsi"] = fsi
    _add_check(
        checks,
        "d3hsp_terminated_normally",
        bool(d3hsp.get("terminated_normally")),
        actual=d3hsp.get("termination_marker"),
    )
    _add_check(
        checks,
        "fsi_interface_present",
        _positive_integer(fsi.get("interface_count")),
        actual=fsi.get("interface_count"),
    )
    fsi_interfaces = fsi.get("interfaces")
    fsi_interface_ids = (
        [
            item.get("interface_id")
            for item in fsi_interfaces
            if isinstance(item, dict)
        ]
        if isinstance(fsi_interfaces, list)
        else []
    )
    _add_check(
        checks,
        "single_target_fsi_interface",
        fsi.get("interface_count") == 1,
        actual={"interface_ids": fsi_interface_ids},
        limit={"exact": 1},
    )
    _add_check(
        checks,
        "fsi_slave_definition_valid",
        fsi.get("has_slave_definition") is True,
        actual={
            "mode": fsi.get("slave_definition_mode"),
            "slave_segment_count": fsi.get("total_slave_segment_count"),
            "slave_material_count": fsi.get("slave_material_count"),
        },
    )

    dbfsi, dbfsi_error = _parse_text_output(run_dir, "dbfsi", parse_dbfsi)
    result["dbfsi"] = dbfsi
    _add_check(
        checks,
        "dbfsi_parsed",
        dbfsi_error is None,
        actual=dbfsi.get("state_count"),
        error=dbfsi_error,
    )
    _add_check(
        checks,
        "dbfsi_states_sufficient",
        _integer_at_least(dbfsi.get("state_count"), 2),
        actual=dbfsi.get("state_count"),
        limit={"minimum": 2},
    )
    dbfsi_surface_ids = dbfsi.get("surface_ids")
    _add_check(
        checks,
        "single_dbfsi_surface",
        dbfsi.get("surface_count") == 1,
        actual={"surface_ids": dbfsi_surface_ids},
        limit={"exact": 1},
    )
    _add_check(
        checks,
        "dbfsi_surface_matches_fsi_interface",
        len(fsi_interface_ids) == 1
        and isinstance(dbfsi_surface_ids, list)
        and dbfsi_surface_ids == fsi_interface_ids,
        actual={
            "fsi_interface_ids": fsi_interface_ids,
            "dbfsi_surface_ids": dbfsi_surface_ids,
        },
    )

    pressure = dbfsi.get("peak_pressure_rise_pa")
    force = dbfsi.get("peak_force_rise_n")
    impulse = dbfsi.get("fsi_impulse_magnitude_n_s")
    _add_check(
        checks,
        "fsi_pressure_positive_finite",
        _positive_finite(pressure),
        actual=pressure,
    )
    _add_check(
        checks,
        "fsi_peak_force_positive_finite",
        _positive_finite(force),
        actual=force,
    )
    _add_check(
        checks,
        "fsi_impulse_positive_finite",
        _positive_finite(impulse),
        actual=impulse,
    )
    pressure_baseline = dbfsi.get("baseline_pressure_pa")
    force_baseline = dbfsi.get("baseline_resultant_force_n")
    pressure_snr = _signal_ratio(
        pressure,
        pressure_baseline,
        MIN_PRESSURE_RISE_PA / MIN_SIGNAL_TO_BASELINE_RATIO,
    )
    force_snr = _signal_ratio(
        force,
        force_baseline,
        MIN_FORCE_RISE_N / MIN_SIGNAL_TO_BASELINE_RATIO,
    )
    pressure_signal_significant = bool(
        _finite_at_least(pressure, MIN_PRESSURE_RISE_PA)
        and pressure_snr >= MIN_SIGNAL_TO_BASELINE_RATIO
        and _integer_at_least(dbfsi.get("positive_pressure_sample_count"), 2)
        and _positive_finite(dbfsi.get("positive_pressure_duration_s"))
    )
    _add_check(
        checks,
        "fsi_pressure_signal_significant",
        pressure_signal_significant,
        actual={
            "pressure_rise_pa": pressure,
            "baseline_pressure_pa": pressure_baseline,
            "signal_to_baseline_ratio": pressure_snr,
            "positive_sample_count": dbfsi.get("positive_pressure_sample_count"),
            "positive_duration_s": dbfsi.get("positive_pressure_duration_s"),
        },
        limit={
            "minimum_pressure_rise_pa": MIN_PRESSURE_RISE_PA,
            "minimum_signal_to_baseline_ratio": MIN_SIGNAL_TO_BASELINE_RATIO,
            "minimum_positive_samples": 2,
            "minimum_positive_duration_s_exclusive": 0.0,
        },
    )
    _add_check(
        checks,
        "fsi_force_signal_significant",
        _finite_at_least(force, MIN_FORCE_RISE_N)
        and force_snr >= MIN_SIGNAL_TO_BASELINE_RATIO
        and _finite_at_least(impulse, MIN_IMPULSE_N_S),
        actual={
            "force_rise_n": force,
            "baseline_force_n": force_baseline,
            "signal_to_baseline_ratio": force_snr,
            "impulse_n_s": impulse,
        },
        limit={
            "minimum_force_rise_n": MIN_FORCE_RISE_N,
            "minimum_impulse_n_s": MIN_IMPULSE_N_S,
            "minimum_signal_to_baseline_ratio": MIN_SIGNAL_TO_BASELINE_RATIO,
        },
    )

    nodout, nodout_error = _parse_text_output(run_dir, "nodout", parse_nodout)
    result["nodout"] = nodout
    _add_check(
        checks,
        "nodout_parsed",
        nodout_error is None and nodout.get("ok") is True,
        actual=nodout.get("state_count"),
        error=nodout_error,
    )
    _add_check(
        checks,
        "nodout_states_sufficient",
        _integer_at_least(nodout.get("state_count"), 2),
        actual=nodout.get("state_count"),
        limit={"minimum": 2},
    )

    displacement = nodout.get("effective_peak_displacement_m")
    displacement_time = nodout.get("peak_time_s")
    displacement_node_id = nodout.get("peak_node_id")
    pressure_time = dbfsi.get("peak_pressure_rise_time_s")
    _add_check(
        checks,
        "plate_response_node_matches_target",
        isinstance(displacement_node_id, int)
        and not isinstance(displacement_node_id, bool)
        and displacement_node_id in response_node_ids,
        actual={
            "peak_node_id": displacement_node_id,
            "target_response_node_count": len(response_node_ids),
        },
    )
    _add_check(
        checks,
        "plate_displacement_positive_finite",
        _positive_finite(displacement),
        actual=displacement,
    )
    displacement_baseline = nodout.get("initial_peak_displacement_m")
    displacement_snr = _signal_ratio(
        displacement,
        displacement_baseline,
        MIN_DISPLACEMENT_RISE_M / MIN_SIGNAL_TO_BASELINE_RATIO,
    )
    _add_check(
        checks,
        "plate_displacement_signal_significant",
        _finite_at_least(displacement, MIN_DISPLACEMENT_RISE_M)
        and displacement_snr >= MIN_SIGNAL_TO_BASELINE_RATIO
        and _positive_finite(nodout.get("displacement_signal_duration_s")),
        actual={
            "displacement_rise_m": displacement,
            "baseline_displacement_m": displacement_baseline,
            "signal_to_baseline_ratio": displacement_snr,
            "signal_duration_s": nodout.get("displacement_signal_duration_s"),
        },
        limit={
            "minimum_displacement_rise_m": MIN_DISPLACEMENT_RISE_M,
            "minimum_signal_to_baseline_ratio": MIN_SIGNAL_TO_BASELINE_RATIO,
            "minimum_duration_s_exclusive": 0.0,
        },
    )
    response_order_ok = (
        _nonnegative_finite(displacement_time)
        and _nonnegative_finite(pressure_time)
        and float(displacement_time) >= float(pressure_time)
    )
    _add_check(
        checks,
        "response_peak_not_before_pressure_peak",
        response_order_ok,
        actual={
            "pressure_peak_time_s": pressure_time,
            "displacement_peak_time_s": displacement_time,
        },
    )

    metrics = result["metrics"]
    metrics.update(
        {
            "peak_coupled_surface_pressure_pa": pressure,
            "peak_fsi_force_n": force,
            "fsi_impulse_n_s": impulse,
            "peak_pressure_time_s": pressure_time,
            "peak_displacement_m": displacement,
            "peak_displacement_time_s": displacement_time,
            "peak_displacement_node_id": displacement_node_id,
        }
    )
    verified = all(bool(check.get("ok")) for check in checks)
    result["wave_transfer_verified"] = verified
    result["status"] = "verified" if verified else "not_verified"
    return result


def evaluate_phase14_mesh_convergence(
    projects: list[Path],
    tolerance: float = 0.10,
) -> JSONDict:
    checks: list[JSONDict] = []
    result: JSONDict = {
        "status": "invalid_evidence",
        "convergence_verified": False,
        "tolerance": tolerance,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "projects": [],
        "metric_comparisons": {},
    }

    project_count_valid = isinstance(projects, list) and 3 <= len(projects) <= 8
    _add_check(
        checks,
        "project_count_valid",
        project_count_valid,
        actual=len(projects) if isinstance(projects, list) else None,
        limit={"minimum": 3, "maximum": 8},
    )
    if not isinstance(projects, list):
        return result

    resolved_projects = [
        project.resolve() for project in projects if isinstance(project, Path)
    ]
    path_types_valid = len(resolved_projects) == len(projects)
    _add_check(
        checks,
        "project_paths_valid",
        path_types_valid,
        actual=len(resolved_projects),
    )
    names = [project.name for project in resolved_projects]
    names_unique = len(names) == len(set(names))
    _add_check(
        checks,
        "project_names_unique",
        names_unique,
        actual=names,
    )
    tolerance_valid = _positive_finite(tolerance) and float(tolerance) <= 1.0
    _add_check(
        checks,
        "tolerance_valid",
        tolerance_valid,
        actual=tolerance,
        limit={"minimum_exclusive": 0.0, "maximum": 1.0},
    )

    evidence: list[JSONDict] = []
    for project in resolved_projects:
        item: JSONDict = {
            "project_name": project.name,
            "project_dir": str(project),
        }
        record, run_dir, run_error = _latest_terminal_run(project)
        item["run_error"] = run_error
        item["run_id"] = record.get("run_id")
        run_model_json = run_dir / "model.json" if run_dir is not None else None
        model_path = run_model_json or project / "solver_runs" / "missing-model.json"
        item["model_json_source"] = "run_model_json"
        model, model_error = _read_json_object(model_path)
        item["model_error"] = model_error
        spec = model.get("spec") if isinstance(model, dict) else None
        metadata = model.get("metadata") if isinstance(model, dict) else None
        if not isinstance(spec, dict):
            spec = {}
        if not isinstance(metadata, dict):
            metadata = {}
        geometry = spec.get("geometry")
        geometry = geometry if isinstance(geometry, dict) else {}
        item["is_phase14_plate"] = (
            spec.get("model_type") == "ale_blast_scene"
            and geometry.get("scene_variant") != EXCLUDED_SCENE_VARIANT
        )
        mesh = spec.get("mesh")
        mesh = mesh if isinstance(mesh, dict) else {}
        mesh_size = mesh.get("size_m")
        item["mesh_size_m"] = mesh_size
        blast_configuration = record.get("blast_configuration")
        recorded_mesh_sizes = (
            blast_configuration.get("mesh_sizes_m")
            if isinstance(blast_configuration, dict)
            else None
        )
        item["recorded_mesh_sizes_m"] = recorded_mesh_sizes
        item["mesh_size_bound_to_run"] = bool(
            _positive_finite(mesh_size)
            and isinstance(recorded_mesh_sizes, list)
            and len(recorded_mesh_sizes) == 1
            and _positive_finite(recorded_mesh_sizes[0])
            and math.isclose(
                float(mesh_size),
                float(recorded_mesh_sizes[0]),
                rel_tol=1.0e-12,
                abs_tol=1.0e-15,
            )
        )
        normalized_spec = _normalized_model_spec(spec)
        item["model_fingerprint_sha256"] = _json_sha256(normalized_spec)

        recorded_input_sha256 = record.get("input_sha256")
        snapshot_input_sha256 = (
            _file_sha256(run_dir / "model.k") if run_dir is not None else None
        )
        recorded_model_sha256 = record.get("model_json_sha256")
        snapshot_model_sha256 = (
            _file_sha256(run_model_json)
            if run_model_json is not None
            else None
        )
        declared_output_set_ids = _declared_output_set_ids(metadata)
        item["input_sha256"] = recorded_input_sha256
        item["snapshot_input_sha256"] = snapshot_input_sha256
        item["model_json_sha256"] = recorded_model_sha256
        item["snapshot_model_json_sha256"] = snapshot_model_sha256
        item["physical_control_sha256"] = (
            _keyword_control_sha256(
                run_dir / "model.k",
                declared_output_set_ids,
            )
            if run_dir is not None
            else None
        )
        evidence_integrity = (
            validate_phase14_run_evidence(
                run_dir,
                record.get("evidence_manifest"),
            )
            if run_dir is not None
            else {"ok": False, "reason": "run_directory_missing"}
        )
        item["evidence_integrity"] = evidence_integrity
        item["run_input_integrity_valid"] = (
            isinstance(recorded_input_sha256, str)
            and len(recorded_input_sha256) == 64
            and recorded_input_sha256 == snapshot_input_sha256
            and isinstance(recorded_model_sha256, str)
            and len(recorded_model_sha256) == 64
            and recorded_model_sha256 == snapshot_model_sha256
            and evidence_integrity.get("ok") is True
        )
        solver_evaluation = record.get("solver_evaluation")
        terminal_complete = (
            run_error is None
            and record.get("status") == "completed"
            and record.get("returncode") == 0
            and record.get("ok") is True
            and isinstance(solver_evaluation, dict)
            and solver_evaluation.get("ok") is True
            and run_dir is not None
            and bool(_nonempty_outputs(run_dir, "d3plot"))
        )
        item["terminal_run_complete"] = terminal_complete
        acceptance: JSONDict = {}
        if run_dir is not None and run_dir.is_dir():
            acceptance = evaluate_phase14_wave_transfer(
                project,
                run_dir,
                run_record=record,
            )
        item["wave_transfer_acceptance"] = acceptance
        item["wave_transfer_verified"] = bool(
            acceptance.get("wave_transfer_verified")
        )
        metrics = acceptance.get("metrics")
        item["metrics"] = metrics if isinstance(metrics, dict) else {}
        evidence.append(item)

    if all(_positive_finite(item.get("mesh_size_m")) for item in evidence):
        evidence.sort(key=lambda item: float(item["mesh_size_m"]), reverse=True)
    result["projects"] = evidence

    all_models_readable = bool(evidence) and all(
        item.get("model_error") is None for item in evidence
    )
    all_plate_scenes = bool(evidence) and all(
        item.get("is_phase14_plate") is True for item in evidence
    )
    mesh_sizes_positive = bool(evidence) and all(
        _positive_finite(item.get("mesh_size_m")) for item in evidence
    )
    mesh_sizes = [
        float(item["mesh_size_m"])
        for item in evidence
        if _positive_finite(item.get("mesh_size_m"))
    ]
    mesh_sizes_unique = (
        len(mesh_sizes) == len(evidence)
        and len(mesh_sizes) == len(set(mesh_sizes))
    )
    mesh_sizes_bound = bool(evidence) and all(
        item.get("mesh_size_bound_to_run") is True for item in evidence
    )
    refinement_ratios = (
        [
            float(coarser["mesh_size_m"]) / float(finer["mesh_size_m"])
            for coarser, finer in zip(evidence, evidence[1:])
        ]
        if mesh_sizes_positive and mesh_sizes_unique
        else []
    )
    refinement_ratios_meaningful = bool(refinement_ratios) and all(
        math.isfinite(value) and value >= 1.10
        for value in refinement_ratios
    )
    refinement_ratios_consistent = bool(refinement_ratios) and (
        max(refinement_ratios) / min(refinement_ratios) <= 1.20
    )
    fingerprints = [
        str(item.get("model_fingerprint_sha256", "")) for item in evidence
    ]
    specs_match = bool(fingerprints) and len(set(fingerprints)) == 1
    control_fingerprints = [
        item.get("physical_control_sha256") for item in evidence
    ]
    physical_controls_match = bool(control_fingerprints) and all(
        isinstance(value, str) for value in control_fingerprints
    ) and len(set(control_fingerprints)) == 1
    all_terminal = bool(evidence) and all(
        item.get("terminal_run_complete") is True for item in evidence
    )
    all_run_inputs_match = bool(evidence) and all(
        item.get("run_input_integrity_valid") is True for item in evidence
    )
    all_wave_verified = bool(evidence) and all(
        item.get("wave_transfer_verified") is True for item in evidence
    )
    all_metrics_positive = bool(evidence) and all(
        all(
            _positive_finite(item.get("metrics", {}).get(metric))
            for metric in CONVERGENCE_METRICS
        )
        for item in evidence
    )

    _add_check(
        checks,
        "all_models_readable",
        all_models_readable,
        actual=[item.get("model_error") for item in evidence],
    )
    _add_check(
        checks,
        "all_phase14_plate_scenes",
        all_plate_scenes,
        actual=[item.get("is_phase14_plate") for item in evidence],
    )
    _add_check(
        checks,
        "mesh_sizes_positive_finite",
        mesh_sizes_positive,
        actual=[item.get("mesh_size_m") for item in evidence],
    )
    _add_check(
        checks,
        "mesh_sizes_unique",
        mesh_sizes_unique,
        actual=mesh_sizes,
    )
    _add_check(
        checks,
        "mesh_sizes_bound_to_runs",
        mesh_sizes_bound,
        actual=[
            {
                "project_name": item["project_name"],
                "snapshot_mesh_size_m": item.get("mesh_size_m"),
                "recorded_mesh_sizes_m": item.get("recorded_mesh_sizes_m"),
            }
            for item in evidence
        ],
    )
    _add_check(
        checks,
        "refinement_ratios_meaningful",
        refinement_ratios_meaningful and refinement_ratios_consistent,
        actual=refinement_ratios,
        limit={
            "minimum": 1.10,
            "maximum_ratio_spread": 1.20,
        },
    )
    _add_check(
        checks,
        "model_specs_match_except_mesh",
        specs_match,
        actual=fingerprints,
    )
    _add_check(
        checks,
        "physical_controls_match_across_levels",
        physical_controls_match,
        actual=control_fingerprints,
    )
    _add_check(
        checks,
        "all_terminal_runs_accepted",
        all_terminal,
        actual=[item.get("terminal_run_complete") for item in evidence],
    )
    _add_check(
        checks,
        "all_run_evidence_integrity_valid",
        all_run_inputs_match,
        actual=[
            {
                "project_name": item["project_name"],
                "recorded": item.get("input_sha256"),
                "snapshot": item.get("snapshot_input_sha256"),
                "recorded_model_json": item.get("model_json_sha256"),
                "snapshot_model_json": item.get("snapshot_model_json_sha256"),
                "evidence_integrity": item.get("evidence_integrity"),
            }
            for item in evidence
        ],
    )
    _add_check(
        checks,
        "all_wave_transfer_verified",
        all_wave_verified,
        actual=[item.get("wave_transfer_verified") for item in evidence],
    )
    _add_check(
        checks,
        "all_metrics_positive_finite",
        all_metrics_positive,
        actual={
            item["project_name"]: item.get("metrics", {})
            for item in evidence
        },
    )

    evidence_valid = all(
        (
            project_count_valid,
            path_types_valid,
            names_unique,
            tolerance_valid,
            all_models_readable,
            all_plate_scenes,
            mesh_sizes_positive,
            mesh_sizes_unique,
            mesh_sizes_bound,
            refinement_ratios_meaningful,
            refinement_ratios_consistent,
            specs_match,
            physical_controls_match,
            all_terminal,
            all_run_inputs_match,
            all_wave_verified,
            all_metrics_positive,
        )
    )
    if not evidence_valid:
        return result

    result["model_fingerprint_sha256"] = fingerprints[0]
    comparisons: JSONDict = {}
    convergence_verified = True
    for metric in CONVERGENCE_METRICS:
        pairs: list[JSONDict] = []
        for coarser, finer in zip(evidence, evidence[1:]):
            coarser_value = float(coarser["metrics"][metric])
            finer_value = float(finer["metrics"][metric])
            pairs.append(
                {
                    "coarser_project_name": coarser["project_name"],
                    "finer_project_name": finer["project_name"],
                    "coarser_mesh_size_m": coarser["mesh_size_m"],
                    "finer_mesh_size_m": finer["mesh_size_m"],
                    "coarser_value": coarser_value,
                    "finer_value": finer_value,
                    "relative_difference": abs(finer_value - coarser_value)
                    / abs(finer_value),
                }
            )
        final_difference = float(pairs[-1]["relative_difference"])
        previous_difference = float(pairs[-2]["relative_difference"])
        within_tolerance = _less_or_close(final_difference, float(tolerance))
        error_nonincreasing = _less_or_close(
            final_difference,
            previous_difference,
        )
        gci = _three_grid_gci(
            mesh_sizes=[
                float(item["mesh_size_m"])
                for item in evidence[-3:]
            ],
            values=[
                float(item["metrics"][metric])
                for item in evidence[-3:]
            ],
        )
        monotonic = gci["monotonic"] is True
        observed_order = gci.get("observed_order")
        fine_grid_gci = gci.get("fine_grid_gci")
        gci_valid = (
            _positive_finite(observed_order)
            and _nonnegative_finite(fine_grid_gci)
            and _less_or_close(float(fine_grid_gci), float(tolerance))
        )
        metric_converged = bool(
            within_tolerance
            and error_nonincreasing
            and monotonic
            and gci_valid
        )
        convergence_verified = convergence_verified and metric_converged
        comparisons[metric] = {
            "values": [
                {
                    "project_name": item["project_name"],
                    "mesh_size_m": item["mesh_size_m"],
                    "value": item["metrics"][metric],
                }
                for item in evidence
            ],
            "pairs": pairs,
            "finest_pair_within_tolerance": within_tolerance,
            "final_error_nonincreasing": error_nonincreasing,
            "monotonic": monotonic,
            "observed_order": observed_order,
            "fine_grid_gci": fine_grid_gci,
            "richardson_extrapolated_value": gci.get(
                "richardson_extrapolated_value"
            ),
            "refinement_ratios": gci.get("refinement_ratios"),
            "method": "three-grid Richardson extrapolation with GCI safety factor 1.25",
            "converged": metric_converged,
        }

    result["metric_comparisons"] = comparisons
    result["convergence_verified"] = convergence_verified
    result["status"] = "converged" if convergence_verified else "not_converged"
    return result


def _three_grid_gci(
    *,
    mesh_sizes: list[float],
    values: list[float],
) -> JSONDict:
    if len(mesh_sizes) != 3 or len(values) != 3:
        return {"monotonic": False}
    coarse_h, medium_h, fine_h = mesh_sizes
    coarse_value, medium_value, fine_value = values
    r32 = coarse_h / medium_h
    r21 = medium_h / fine_h
    coarse_delta = coarse_value - medium_value
    fine_delta = medium_value - fine_value
    monotonic = coarse_delta * fine_delta > 0.0
    result: JSONDict = {
        "monotonic": monotonic,
        "refinement_ratios": {
            "coarse_to_medium": r32,
            "medium_to_fine": r21,
        },
    }
    if (
        not monotonic
        or fine_delta == 0.0
        or fine_value == 0.0
        or r32 <= 1.0
        or r21 <= 1.0
    ):
        return result
    representative_ratio = math.sqrt(r32 * r21)
    error_ratio = abs(coarse_delta / fine_delta)
    if error_ratio <= 1.0 or representative_ratio <= 1.0:
        return result
    observed_order = math.log(error_ratio) / math.log(representative_ratio)
    if not math.isfinite(observed_order) or observed_order <= 0.0:
        return result
    denominator = r21**observed_order - 1.0
    if not math.isfinite(denominator) or denominator <= 0.0:
        return result
    approximate_relative_error = abs((fine_value - medium_value) / fine_value)
    fine_grid_gci = 1.25 * approximate_relative_error / denominator
    extrapolated = fine_value + (fine_value - medium_value) / denominator
    result.update(
        {
            "observed_order": observed_order,
            "fine_grid_gci": fine_grid_gci,
            "richardson_extrapolated_value": extrapolated,
        }
    )
    return result


def _read_json_object(path: Path) -> tuple[JSONDict, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    if not isinstance(value, dict):
        return {}, "model.json must contain a JSON object"
    return value, None


def _phase14_deck_evidence(
    path: Path,
    *,
    target_part_id: int | None,
) -> tuple[JSONDict, str | None]:
    blocks = _keyword_blocks(path)
    if blocks is None:
        return {}, "run model.k is missing or is not valid UTF-8"

    coupling_count = 0
    shell_element_count = 0
    response_node_ids: list[int] = []
    coupling_slave_part_ids: list[int] = []
    shell_nodes_by_part: dict[int, set[int]] = {}
    node_sets: dict[int, set[int]] = {}
    translationally_fixed_set_ids: set[int] = set()
    for keyword_line, block_lines in blocks:
        card = keyword_line.split(",", 1)[0].split(None, 1)[0]
        values = [
            line.strip()
            for line in block_lines
            if line.strip() and not line.lstrip().startswith("$")
        ]
        if card == "*CONSTRAINED_LAGRANGE_IN_SOLID":
            coupling_count += 1
            if values:
                fields = _integer_fields(values[0])
                if fields:
                    coupling_slave_part_ids.append(fields[0])
        elif card.startswith("*ELEMENT_SHELL"):
            for line in values:
                fields = _integer_fields(line)
                if len(fields) < 6:
                    continue
                shell_element_count += 1
                shell_nodes_by_part.setdefault(fields[1], set()).update(fields[2:])
        elif card in {"*SET_NODE_LIST", "*SET_NODE_LIST_TITLE"}:
            set_id, members = _node_set(card, values)
            if set_id is not None:
                node_sets[set_id] = members
            if (
                card == "*SET_NODE_LIST_TITLE"
                and values
                and "free target plate response nodes" in values[0].lower()
            ):
                response_node_ids.extend(members)
        elif card == "*BOUNDARY_SPC_SET" and values:
            fields = _integer_fields(values[0])
            if len(fields) >= 5 and any(value != 0 for value in fields[2:5]):
                translationally_fixed_set_ids.add(fields[0])
    fixed_nodes: set[int] = set()
    for set_id in translationally_fixed_set_ids:
        fixed_nodes.update(node_sets.get(set_id, set()))
    response_nodes = set(response_node_ids)
    target_shell_nodes = (
        shell_nodes_by_part.get(target_part_id, set())
        if target_part_id is not None
        else set()
    )
    outside_target_shell = sorted(response_nodes - target_shell_nodes)
    constrained_response_nodes = sorted(response_nodes & fixed_nodes)
    result = {
        "coupling_count": coupling_count,
        "coupling_slave_part_ids": sorted(coupling_slave_part_ids),
        "shell_element_count": shell_element_count,
        "response_node_ids": sorted(response_nodes),
        "target_part_id": target_part_id,
        "target_shell_node_count": len(target_shell_nodes),
        "response_nodes_outside_target_shell": outside_target_shell,
        "constrained_response_node_ids": constrained_response_nodes,
        "response_nodes_belong_to_target_shell": bool(response_nodes)
        and not outside_target_shell,
        "response_nodes_are_translationally_free": bool(response_nodes)
        and not constrained_response_nodes,
    }
    return result, None


def _integer_fields(line: str) -> list[int]:
    fields = line.split(",") if "," in line else line.split()
    result: list[int] = []
    for field in fields:
        token = field.strip()
        if not token:
            continue
        if not re.fullmatch(r"[+-]?\d+", token):
            return []
        result.append(int(token))
    return result


def _node_set(card: str, values: list[str]) -> tuple[int | None, set[int]]:
    header_index = 1 if card.endswith("_TITLE") else 0
    if len(values) <= header_index:
        return None, set()
    header = _integer_fields(values[header_index])
    if not header or header[0] <= 0:
        return None, set()
    members: set[int] = set()
    for line in values[header_index + 1 :]:
        members.update(value for value in _integer_fields(line) if value > 0)
    return header[0], members


def _normalized_model_spec(spec: JSONDict) -> JSONDict:
    normalized = copy.deepcopy(spec)
    normalized.pop("project_name", None)
    mesh = normalized.get("mesh")
    if isinstance(mesh, dict):
        mesh.pop("size_m", None)
    return normalized


def _json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _declared_output_set_ids(metadata: JSONDict) -> set[int]:
    outputs = metadata.get("ale_quantitative_outputs")
    if not isinstance(outputs, dict):
        return set()
    set_id = outputs.get("pressure_probe_set_id")
    if isinstance(set_id, int) and not isinstance(set_id, bool) and set_id > 0:
        return {set_id}
    return set()


def _keyword_physics_sha256(
    path: Path,
    ignored_output_set_ids: set[int],
) -> str | None:
    blocks = _keyword_blocks(path)
    if blocks is None:
        return None

    normalized: list[str] = []
    for keyword_line, block_lines in blocks:
        card = keyword_line.split(",", 1)[0].split(None, 1)[0]
        if card.startswith("*DATABASE"):
            continue
        if card in {"*SET_SOLID_LIST", "*SET_SOLID_LIST_TITLE"}:
            set_id = _set_card_id(card, block_lines)
            if set_id in ignored_output_set_ids:
                continue
        normalized.append(keyword_line)
        for raw_line in block_lines:
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("$"):
                continue
            normalized.append(raw_line.rstrip())
    if not normalized:
        return None
    return hashlib.sha256("\n".join(normalized).encode("utf-8")).hexdigest()


def _keyword_control_sha256(
    path: Path,
    ignored_output_set_ids: set[int],
) -> str | None:
    blocks = _keyword_blocks(path)
    if blocks is None:
        return None

    normalized: list[str] = []
    mesh_set_cards = {
        "*SET_NODE_LIST",
        "*SET_NODE_LIST_TITLE",
        "*SET_SEGMENT",
        "*SET_SEGMENT_TITLE",
        "*SET_SOLID",
        "*SET_SOLID_TITLE",
        "*SET_SOLID_LIST",
        "*SET_SOLID_LIST_TITLE",
    }
    for keyword_line, block_lines in blocks:
        card = keyword_line.split(",", 1)[0].split(None, 1)[0]
        if (
            card == "*TITLE"
            or card.startswith("*DATABASE")
            or card == "*NODE"
            or card.startswith("*ELEMENT_")
        ):
            continue
        if card in {"*SET_SOLID_LIST", "*SET_SOLID_LIST_TITLE"}:
            set_id = _set_card_id(card, block_lines)
            if set_id in ignored_output_set_ids:
                continue
        normalized.append(keyword_line)
        data_lines = [
            line.rstrip()
            for line in block_lines
            if line.strip() and not line.lstrip().startswith("$")
        ]
        if card in mesh_set_cards:
            header_count = 2 if card.endswith("_TITLE") else 1
            normalized.extend(data_lines[:header_count])
        else:
            normalized.extend(data_lines)
    if not normalized:
        return None
    return hashlib.sha256("\n".join(normalized).encode("utf-8")).hexdigest()


def _keyword_solid_set_ids(path: Path) -> set[int] | None:
    blocks = _keyword_blocks(path)
    if blocks is None:
        return None
    result: set[int] = set()
    for keyword_line, block_lines in blocks:
        card = keyword_line.split(",", 1)[0].split(None, 1)[0]
        if card not in {"*SET_SOLID_LIST", "*SET_SOLID_LIST_TITLE"}:
            continue
        set_id = _set_card_id(card, block_lines)
        if set_id is not None:
            result.add(set_id)
    return result


def _keyword_blocks(path: Path) -> list[tuple[str, list[str]]] | None:
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError):
        return None

    blocks: list[tuple[str, list[str]]] = []
    keyword = ""
    data_lines: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("*"):
            if keyword:
                blocks.append((keyword, data_lines))
            keyword = stripped.upper()
            data_lines = []
        elif keyword:
            data_lines.append(raw_line)
    if keyword:
        blocks.append((keyword, data_lines))
    return blocks


def _set_card_id(card: str, lines: list[str]) -> int | None:
    values = [
        line.strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith("$")
    ]
    index = 1 if card.endswith("_TITLE") else 0
    if len(values) <= index:
        return None
    match = re.match(r"\s*(\d+)", values[index])
    return int(match.group(1)) if match else None


def _latest_terminal_run(
    project: Path,
) -> tuple[JSONDict, Path | None, str | None]:
    record, error = _read_json_object(project / "solver_runs" / "latest.json")
    if error is not None:
        return {}, None, error
    run_id = record.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"run_[A-Za-z0-9_]+", run_id):
        return record, None, "latest run_id is invalid"
    runs_dir = (project / "solver_runs").resolve()
    run_dir = (runs_dir / run_id).resolve()
    if run_dir.parent != runs_dir or not run_dir.is_dir():
        return record, None, "latest run directory is unavailable"
    run_record, run_record_error = _read_json_object(run_dir / "run.json")
    if run_record_error is not None:
        return record, run_dir, run_record_error
    identity = validate_run_record_identity(record, run_record)
    if identity.get("ok") is not True:
        return record, run_dir, "latest.json and run.json identities do not match"
    return record, run_dir, None


def _nonempty_outputs(run_dir: Path, prefix: str) -> list[Path]:
    return [
        path
        for path in run_dir.iterdir()
        if path.is_file()
        and path.name.lower().startswith(prefix)
        and path.stat().st_size > 0
    ]


def _target_plate_response_nodes(metadata: JSONDict) -> list[int]:
    components = metadata.get("components")
    if not isinstance(components, list):
        return []
    for component in components:
        if not isinstance(component, dict) or component.get("id") != "target_plate":
            continue
        nodes = component.get("response_node_ids")
        if not isinstance(nodes, list):
            return []
        return [
            int(node)
            for node in nodes
            if isinstance(node, int) and not isinstance(node, bool) and node > 0
        ]
    return []


def _target_plate_part_id(metadata: JSONDict) -> int | None:
    components = metadata.get("components")
    if not isinstance(components, list):
        return None
    for component in components:
        if not isinstance(component, dict) or component.get("id") != "target_plate":
            continue
        part_id = component.get("part_id")
        if isinstance(part_id, int) and not isinstance(part_id, bool) and part_id > 0:
            return part_id
    return None


def _first_output(run_dir: Path, prefix: str) -> Path | None:
    if not run_dir.is_dir():
        return None
    try:
        candidates = sorted(
            path
            for path in run_dir.iterdir()
            if path.is_file() and path.name.lower().startswith(prefix)
        )
    except OSError:
        return None
    return candidates[0] if candidates else None


def _parse_text_output(
    run_dir: Path,
    prefix: str,
    parser: Any,
) -> tuple[JSONDict, str | None]:
    source = _first_output(run_dir, prefix)
    if source is None:
        return {}, f"{prefix} is missing"
    try:
        parsed = parser(source.read_text(encoding="utf-8", errors="replace"))
    except (OSError, TypeError, ValueError) as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    if not isinstance(parsed, dict):
        return {}, f"{prefix} parser returned a non-object result"
    return parsed, None


def _add_check(
    checks: list[JSONDict],
    check_id: str,
    ok: bool,
    *,
    actual: Any = None,
    limit: Any = None,
    error: str | None = None,
) -> None:
    check: JSONDict = {"id": check_id, "ok": bool(ok), "actual": actual}
    if limit is not None:
        check["limit"] = limit
    if error is not None:
        check["error"] = error
    checks.append(check)


def _positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _integer_at_least(value: Any, minimum: int) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= minimum
    )


def _positive_finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0.0
    )


def _finite_at_least(value: Any, minimum: float) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= minimum
    )


def _signal_ratio(signal: Any, baseline: Any, floor: float) -> float:
    if not _nonnegative_finite(signal):
        return 0.0
    baseline_value = (
        abs(float(baseline))
        if _nonnegative_finite(baseline)
        else 0.0
    )
    return float(signal) / max(baseline_value, floor)


def _nonnegative_finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0.0
    )


def _less_or_close(left: float, right: float) -> bool:
    return left <= right or math.isclose(
        left,
        right,
        rel_tol=1.0e-12,
        abs_tol=1.0e-15,
    )
