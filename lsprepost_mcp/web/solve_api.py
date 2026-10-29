from __future__ import annotations

import os
import uuid
from pathlib import Path

from lsprepost_mcp.config import JSONDict
from lsprepost_mcp.blast_analysis import compare_blast_run_records, summarize_blast_run
from lsprepost_mcp.io import write_json
from lsprepost_mcp.locks import ProjectLock
from lsprepost_mcp.lsrun_handoff import (
    launch_lsrun_handoff,
    prepare_lsrun_handoff,
    recover_lsrun_result,
)
from lsprepost_mcp.lsdyna_runner import execute_lsdyna_run, latest_lsdyna_run, parse_run_options
from lsprepost_mcp.paths import find_project_dir
from lsprepost_mcp.phase14_acceptance import evaluate_phase14_mesh_convergence
from lsprepost_mcp.project_store import validate_project_files
from lsprepost_mcp.web.config_api import configured_lsdyna_exe, configured_lsrun_exe, doctor_named_exe
from lsprepost_mcp.web.http_utils import ApiError


def open_lsrun_payload(payload: JSONDict) -> JSONDict:
    project_name = payload_project_name(payload)
    project = find_project_dir(project_name)
    model = project / "model.k"
    if not model.is_file():
        raise ApiError(400, "missing_model", "current project does not contain model.k")

    lsrun = configured_lsrun_exe()
    if lsrun is None:
        raise ApiError(400, "lsrun_not_configured", "LS-Run executable is not configured")
    doctor = doctor_named_exe(lsrun, ("lsrun",), require_name=True)
    if not doctor.ok:
        raise ApiError(400, "invalid_lsrun_path", "LS-Run path must be an existing lsrun*.exe file")

    lsdyna = configured_lsdyna_exe()
    validation = validate_project_files(project)
    readiness = validation.get("readiness", {})
    if not bool(readiness.get("ok_for_solver_draft")):
        blockers = validation.get("errors", []) or readiness.get(
            "solver_warning_blockers",
            [],
        )
        raise ApiError(
            400,
            "project_not_solver_ready",
            f"project did not pass the solver draft gate: {blockers}",
        )
    try:
        handoff = prepare_lsrun_handoff(
            project,
            lsrun,
            lsdyna,
            ncpu=payload.get("ncpu", 4),
            memory=payload.get("memory", "20m"),
        )
        return launch_lsrun_handoff(project, handoff)
    except TimeoutError as exc:
        raise ApiError(
            409,
            "lsrun_handoff_locked",
            "this project is locked by another operation",
        ) from exc
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise ApiError(400, "invalid_lsrun_handoff", str(exc)) from exc


def recover_lsrun_payload(payload: JSONDict) -> JSONDict:
    project_name = payload_project_name(payload)
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ApiError(400, "invalid_run_id", "run_id must be a non-empty string")
    project = find_project_dir(project_name)
    if not project.is_dir():
        raise ApiError(404, "project_not_found", f"project not found: {project_name}")
    try:
        return recover_lsrun_result(project, run_id)
    except TimeoutError as exc:
        raise ApiError(
            409,
            "lsrun_handoff_locked",
            "this project is locked by another operation",
        ) from exc
    except FileNotFoundError as exc:
        raise ApiError(404, "lsrun_handoff_not_found", str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "invalid_lsrun_handoff", str(exc)) from exc


def run_lsdyna_payload(payload: JSONDict) -> JSONDict:
    options = parse_run_options(payload)
    project_name = str(options["project_name"])
    project = find_project_dir(project_name)
    if not project.is_dir():
        raise ApiError(404, "project_not_found", f"project not found: {project_name}")

    solver = configured_lsdyna_exe()
    if solver is None:
        raise ApiError(400, "lsdyna_not_configured", "LS-DYNA solver executable is not configured")
    doctor = doctor_named_exe(solver, ("lsdyna", "ls-dyna", "mppdyna"), require_name=False)
    if not doctor.ok:
        raise ApiError(400, "invalid_lsdyna_path", "LS-DYNA solver path must be an existing .exe file")

    try:
        with ProjectLock(project_name):
            with ProjectLock(project_name, namespace="solver_runtime", timeout_s=1.0):
                validation = validate_project_files(project)
                readiness = validation.get("readiness", {})
                if not bool(readiness.get("ok_for_solver_draft")):
                    blockers = validation.get("errors", []) or readiness.get("solver_warning_blockers", [])
                    raise ApiError(
                        400,
                        "project_not_solver_ready",
                        f"project did not pass the solver draft gate: {blockers}",
                    )
                return execute_lsdyna_run(
                    project,
                    solver,
                    ncpu=int(options["ncpu"]),
                    memory=str(options["memory"]),
                    timeout_s=float(options["timeout_s"]),
                    static_validation={
                        "ok": validation.get("ok"),
                        "readiness": readiness,
                        "errors": validation.get("errors", []),
                        "warnings": validation.get("warnings", []),
                    },
                )
    except TimeoutError as exc:
        raise ApiError(409, "solver_already_running", "this project is locked by another operation or solver run") from exc


def latest_lsdyna_payload(project_name: str) -> JSONDict:
    if not isinstance(project_name, str) or not project_name.strip():
        raise ApiError(400, "invalid_project_name", "project_name must be a non-empty string")
    project = find_project_dir(project_name.strip())
    if not project.is_dir():
        raise ApiError(404, "project_not_found", f"project not found: {project_name.strip()}")
    record = latest_lsdyna_run(project)
    record["phase13_metrics"] = summarize_blast_run(record)
    return record


def compare_lsdyna_payload(payload: JSONDict) -> JSONDict:
    names = payload.get("project_names")
    if not isinstance(names, list) or not 2 <= len(names) <= 8:
        raise ApiError(400, "invalid_project_names", "project_names must contain between 2 and 8 projects")
    normalized: list[str] = []
    for value in names:
        if not isinstance(value, str) or not value.strip():
            raise ApiError(400, "invalid_project_names", "each project name must be a non-empty string")
        name = value.strip()
        if name in normalized:
            raise ApiError(400, "duplicate_project", f"duplicate project name: {name}")
        normalized.append(name)

    projects: list[Path] = []
    records: list[JSONDict] = []
    for name in normalized:
        project = find_project_dir(name)
        if not project.is_dir():
            raise ApiError(404, "project_not_found", f"project not found: {name}")
        record = latest_lsdyna_run(project)
        if not record.get("run_id"):
            raise ApiError(400, "run_not_available", f"project has no LS-DYNA run record: {name}")
        projects.append(project)
        records.append(record)

    comparison = compare_blast_run_records(records)
    if len(projects) >= 3:
        convergence = evaluate_phase14_mesh_convergence(projects)
        if _check_ok(convergence, "all_phase14_plate_scenes"):
            comparison["mmale_mesh_convergence"] = convergence
            finest = _finest_convergence_project(projects, convergence)
            if finest is not None:
                _persist_mesh_convergence(finest, convergence)
    return comparison


def build_command_preview(model: Path, lsdyna: Path | None) -> str:
    solver = str(lsdyna) if lsdyna else "<LS_DYNA_SOLVER_EXE>"
    return f'"{solver}" i="{model}" ncpu=4 memory=20m'


def payload_project_name(payload: JSONDict) -> str:
    raw = payload.get("project_name")
    if not isinstance(raw, str) or not raw.strip():
        raise ApiError(400, "invalid_project_name", "project_name must be a non-empty string")
    return raw.strip()


def _check_ok(report: JSONDict, check_id: str) -> bool:
    checks = report.get("checks")
    if not isinstance(checks, list):
        return False
    return any(
        isinstance(check, dict)
        and check.get("id") == check_id
        and check.get("ok") is True
        for check in checks
    )


def _finest_convergence_project(
    projects: list[Path],
    report: JSONDict,
) -> Path | None:
    evidence = report.get("projects")
    if not isinstance(evidence, list):
        return None
    candidates = [
        item
        for item in evidence
        if isinstance(item, dict)
        and isinstance(item.get("project_name"), str)
        and isinstance(item.get("mesh_size_m"), (int, float))
        and not isinstance(item.get("mesh_size_m"), bool)
    ]
    if not candidates:
        return None
    finest_name = str(
        min(candidates, key=lambda item: float(item["mesh_size_m"]))[
            "project_name"
        ]
    )
    return next((project for project in projects if project.name == finest_name), None)


def _persist_mesh_convergence(project: Path, report: JSONDict) -> None:
    target = project / "artifacts" / "mmale_mesh_convergence.json"
    with ProjectLock(project.name, namespace="mmale_convergence"):
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{target.name}.tmp_{uuid.uuid4().hex}")
        try:
            write_json(temp, report)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
