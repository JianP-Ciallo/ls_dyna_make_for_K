from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .config import JSONDict
from .blast_analysis import blast_configuration_summary
from .city_impact import _matsum_diagnostics
from .city_ground_crater_acceptance import evaluate_city_ground_crater
from .lspp.launcher import process_info, terminate_process_tree
from .phase14_acceptance import evaluate_phase14_wave_transfer
from .phase15_fsi import evaluate_phase15_wave_transfer
from .run_evidence import (
    seal_phase14_run_evidence,
    validate_phase14_run_evidence,
    validate_run_record_identity,
)
from .solver_results import (
    evaluate_solver_result,
    parse_blstfor,
    parse_city_object_responses,
    parse_d3hsp,
    parse_dbfsi,
    parse_nodout,
)


MAX_NCPU = 64
MAX_TIMEOUT_S = 7200.0
MEMORY_PATTERN = re.compile(r"^[1-9][0-9]{0,5}[mMgG]$")
OUTPUT_PREFIXES = (
    "d3plot",
    "blstfor",
    "fsifor",
    "dbfsi",
    "glstat",
    "matsum",
    "spcforc",
    "nodout",
    "elout",
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CITY_REQUIRED_EVIDENCE = (
    "d3hsp",
    "d3plot",
    "dbfsi",
    "matsum",
    "elout",
    "nodout",
)


def parse_run_options(payload: JSONDict) -> JSONDict:
    project_name = payload.get("project_name")
    if not isinstance(project_name, str) or not project_name.strip():
        raise ValueError("project_name must be a non-empty string")
    if project_name != project_name.strip():
        raise ValueError("project_name must not have leading or trailing whitespace")

    confirmation = payload.get("confirmation_project_name")
    if not isinstance(confirmation, str) or confirmation != project_name:
        raise ValueError("confirmation_project_name must exactly match project_name")

    ncpu = payload.get("ncpu", 4)
    if isinstance(ncpu, bool) or not isinstance(ncpu, int) or not 1 <= ncpu <= MAX_NCPU:
        raise ValueError(f"ncpu must be an integer between 1 and {MAX_NCPU}")

    memory = payload.get("memory", "20m")
    if not isinstance(memory, str) or not MEMORY_PATTERN.fullmatch(memory.strip()):
        raise ValueError("memory must use LS-DYNA syntax such as 20m or 2g")

    timeout_s = payload.get("timeout_s", 600)
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
        raise ValueError("timeout_s must be a finite number")
    timeout_value = float(timeout_s)
    if not math.isfinite(timeout_value) or not 1.0 <= timeout_value <= MAX_TIMEOUT_S:
        raise ValueError(f"timeout_s must be between 1 and {int(MAX_TIMEOUT_S)}")

    return {
        "project_name": project_name,
        "confirmation_project_name": confirmation,
        "ncpu": ncpu,
        "memory": memory.strip().lower(),
        "timeout_s": timeout_value,
    }


def execute_lsdyna_run(
    project: Path,
    solver_exe: Path,
    *,
    ncpu: int,
    memory: str,
    timeout_s: float,
    static_validation: JSONDict | None = None,
    input_closure: Mapping[str, Path] | None = None,
) -> JSONDict:
    project = project.resolve()
    solver_exe = solver_exe.resolve()
    model = project / "model.k"
    if not model.is_file():
        raise FileNotFoundError(f"model.k not found: {model}")
    if not solver_exe.is_file() or solver_exe.suffix.lower() != ".exe":
        raise ValueError("solver_exe must be an existing .exe file")

    run_id = _new_run_id()
    runs_dir = project / "solver_runs"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    snapshot = run_dir / "model.k"
    if input_closure is None:
        shutil.copy2(model, snapshot)
    else:
        for relative, source in input_closure.items():
            relative_path = PurePosixPath(relative)
            if (
                relative_path.is_absolute()
                or not relative_path.parts
                or any(part in {"", ".", ".."} or ":" in part or "\\" in part for part in relative_path.parts)
            ):
                raise ValueError("input_closure contains an unsafe relative path")
            source_path = Path(source).resolve()
            if not source_path.is_file() or not source_path.is_relative_to(project):
                raise ValueError("input_closure source is outside the project snapshot")
            target = run_dir.joinpath(*relative_path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
        if not snapshot.is_file():
            raise ValueError("input_closure must contain model.k")
    model_json_snapshot = run_dir / "model.json"
    source_model_json = project / "model.json"
    if source_model_json.is_file() and not model_json_snapshot.is_file():
        shutil.copy2(source_model_json, model_json_snapshot)

    mode = _result_mode(project)
    result_variant = _result_variant(project)
    command = [str(solver_exe), "i=model.k", f"ncpu={ncpu}", f"memory={memory}"]
    started_at = _utc_now()
    record: JSONDict = {
        "ok": False,
        "operation": "run_lsdyna",
        "status": "starting",
        "run_id": run_id,
        "project_name": project.name,
        "project_dir": str(project),
        "run_dir": str(run_dir),
        "input": str(snapshot),
        "input_sha256": _sha256(snapshot),
        "result_mode": mode,
        "result_variant": result_variant,
        "solver": {
            "path": str(solver_exe),
            "sha256": _sha256(solver_exe),
            "size_bytes": solver_exe.stat().st_size,
            "modified_at_utc": datetime.fromtimestamp(solver_exe.stat().st_mtime, timezone.utc).isoformat(),
        },
        "command": command,
        "resources": {"ncpu": ncpu, "memory": memory, "timeout_s": timeout_s},
        "started_at_utc": started_at,
        "static_validation": static_validation or {},
    }
    if model_json_snapshot.is_file():
        record["model_json_sha256"] = _sha256(model_json_snapshot)
    if mode == "blast":
        record["blast_configuration"] = _project_blast_configuration(project)
    _persist_record(runs_dir, run_dir, record)

    stdout_path = run_dir / "solver_stdout.txt"
    stderr_path = run_dir / "solver_stderr.txt"
    process = None
    timed_out = False
    termination_confirmed = False
    try:
        with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
            process = subprocess.Popen(
                command,
                cwd=str(run_dir),
                stdout=stdout_handle,
                stderr=stderr_handle,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            record.update({"status": "running", "pid": process.pid})
            _persist_record(runs_dir, run_dir, record)
            try:
                returncode = process.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                termination_confirmed = terminate_process_tree(process.pid)
                returncode = process.returncode
    except OSError as exc:
        record.update(
            {
                "status": "launch_failed",
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
        )
        return _finish_record(runs_dir, run_dir, record)

    record["returncode"] = returncode
    if timed_out:
        record.update(
            {
                "status": "timed_out",
                "termination_confirmed": termination_confirmed,
                "error": {
                    "type": "TimeoutExpired",
                    "message": f"LS-DYNA exceeded timeout_s={timeout_s}",
                },
            }
        )
    else:
        record["status"] = "completed" if returncode == 0 else "solver_failed"

    record["outputs"] = inspect_solver_outputs(run_dir)
    record["solver_evaluation"] = _evaluate_d3hsp(run_dir, mode, result_variant)
    wave_transfer_ok = True
    if result_variant == "phase15_axisymmetric_blast":
        acceptance = _phase15_wave_transfer_acceptance(project, run_dir)
        record["wave_transfer_acceptance"] = acceptance
        _write_json_atomic(run_dir / "wave_transfer_acceptance.json", acceptance)
        wave_transfer_ok = bool(acceptance.get("wave_transfer_verified"))
    elif result_variant == "city_street_blast":
        acceptance = _city_wave_transfer_acceptance(project, run_dir)
        record["wave_transfer_acceptance"] = acceptance
        _write_json_atomic(run_dir / "wave_transfer_acceptance.json", acceptance)
        evidence_integrity = _ensure_city_run_evidence(
            run_dir,
            record,
            allow_create=True,
        )
        wave_transfer_ok = bool(
            acceptance.get("wave_transfer_verified")
            and evidence_integrity.get("ok")
        )
    elif result_variant == "ale_blast":
        try:
            evidence_reference = seal_phase14_run_evidence(run_dir)
        except OSError as exc:
            evidence_reference = None
            evidence_integrity = {
                "ok": False,
                "reason": "evidence_manifest_write_failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
        else:
            record["evidence_manifest"] = evidence_reference
            record["evidence_manifest_sha256"] = evidence_reference["sha256"]
            evidence_integrity = validate_phase14_run_evidence(
                run_dir,
                evidence_reference,
            )
        record["evidence_integrity"] = evidence_integrity
        acceptance = evaluate_phase14_wave_transfer(
            project,
            run_dir,
            run_record=record,
        )
        record["wave_transfer_acceptance"] = acceptance
        _write_json_atomic(run_dir / "wave_transfer_acceptance.json", acceptance)
        wave_transfer_ok = (
            evidence_integrity.get("ok") is True
            and (
                bool(acceptance.get("wave_transfer_verified"))
                or (
                    acceptance.get("applicable") is False
                    and acceptance.get("status") == "not_applicable"
                )
            )
        )
    record["postprocessing"] = {
        "status": "requires_lsprepost_verification"
        if record["outputs"]["d3plot"]["ok"]
        else "d3plot_unavailable",
        "stress_cloud_recorded": False,
        "note": "A non-empty d3plot is necessary but LS-PrePost must still verify non-zero displacement and stress contours.",
    }
    required_outputs_ok = bool(record["outputs"]["d3plot"]["ok"])
    if mode == "blast":
        if result_variant == "phase15_axisymmetric_blast":
            required_outputs_ok = required_outputs_ok and bool(
                record["outputs"]["d3hsp"]["ok"] and record["outputs"]["elout"]["ok"]
            )
        elif result_variant == "city_street_blast":
            required_outputs_ok = required_outputs_ok and bool(
                record["outputs"]["d3hsp"]["ok"]
                and record["outputs"]["matsum"]["ok"]
                and record["outputs"]["elout"]["ok"]
                and record["outputs"]["nodout"]["ok"]
                and (
                    record["outputs"]["fsifor"]["ok"]
                    or record["outputs"]["dbfsi"]["ok"]
                )
            )
        elif result_variant == "ale_blast":
            required_outputs_ok = required_outputs_ok and bool(
                record["outputs"]["fsifor"]["ok"] or record["outputs"]["dbfsi"]["ok"]
            )
        else:
            required_outputs_ok = required_outputs_ok and bool(record["outputs"]["blstfor"]["ok"])
    evaluation = record["solver_evaluation"]
    normal_termination = bool(evaluation.get("parsed", {}).get("terminated_normally"))
    record["ok"] = bool(
        record["status"] == "completed"
        and returncode == 0
        and required_outputs_ok
        and normal_termination
        and evaluation.get("ok")
        and wave_transfer_ok
    )
    return _finish_record(runs_dir, run_dir, record)


def execute_lsdyna_initialization_smoke(
    project: Path,
    solver_exe: Path,
    *,
    ncpu: int = 4,
    memory: str = "1g",
    timeout_s: float = 120.0,
    static_validation: JSONDict | None = None,
) -> JSONDict:
    """Run a bounded LS-DYNA initialization check and persist auditable evidence."""
    project = project.resolve()
    solver_exe = solver_exe.resolve()
    model = project / "model.k"
    if not model.is_file():
        raise FileNotFoundError(f"model.k not found: {model}")
    if not solver_exe.is_file() or solver_exe.suffix.lower() != ".exe":
        raise ValueError("solver_exe must be an existing .exe file")
    if isinstance(ncpu, bool) or not isinstance(ncpu, int) or not 1 <= ncpu <= MAX_NCPU:
        raise ValueError(f"ncpu must be an integer between 1 and {MAX_NCPU}")
    if not isinstance(memory, str) or not MEMORY_PATTERN.fullmatch(memory.strip()):
        raise ValueError("memory must use LS-DYNA syntax such as 20m or 2g")
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
        raise ValueError("timeout_s must be a finite number")
    timeout_value = float(timeout_s)
    if not math.isfinite(timeout_value) or not 1.0 <= timeout_value <= MAX_TIMEOUT_S:
        raise ValueError(f"timeout_s must be between 1 and {int(MAX_TIMEOUT_S)}")

    smoke_id = _new_run_id().replace("run_", "smoke_", 1)
    smokes_dir = project / "solver_smokes"
    smoke_dir = smokes_dir / smoke_id
    smoke_dir.mkdir(parents=True, exist_ok=False)
    snapshot = smoke_dir / "model.k"
    shutil.copy2(model, snapshot)

    memory_value = memory.strip().lower()
    command = [
        str(solver_exe),
        "i=model.k",
        f"ncpu={ncpu}",
        f"memory={memory_value}",
        "mcheck=y",
    ]
    record: JSONDict = {
        "ok": False,
        "operation": "lsdyna_initialization_smoke",
        "status": "starting",
        "smoke_id": smoke_id,
        "project_name": project.name,
        "project_dir": str(project),
        "smoke_dir": str(smoke_dir),
        "input": str(snapshot),
        "input_sha256": _sha256(snapshot),
        "solver": {
            "path": str(solver_exe),
            "sha256": _sha256(solver_exe),
        },
        "command": command,
        "resources": {"ncpu": ncpu, "memory": memory_value, "timeout_s": timeout_value},
        "started_at_utc": _utc_now(),
        "static_validation": static_validation or {},
        "scope": "mcheck=y: initialization and bounded solver check (at most 10 cycles)",
    }
    _persist_smoke_record(smokes_dir, smoke_dir, record)

    stdout_path = smoke_dir / "solver_stdout.txt"
    stderr_path = smoke_dir / "solver_stderr.txt"
    timed_out = False
    termination_confirmed = False
    try:
        with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
            process = subprocess.Popen(
                command,
                cwd=str(smoke_dir),
                stdout=stdout_handle,
                stderr=stderr_handle,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            record.update({"status": "running", "pid": process.pid})
            _persist_smoke_record(smokes_dir, smoke_dir, record)
            try:
                returncode = process.wait(timeout=timeout_value)
            except subprocess.TimeoutExpired:
                timed_out = True
                termination_confirmed = terminate_process_tree(process.pid)
                returncode = process.returncode
    except OSError as exc:
        record.update(
            {
                "status": "launch_failed",
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
        )
        return _finish_smoke_record(smokes_dir, smoke_dir, record)

    record["returncode"] = returncode
    if timed_out:
        record.update(
            {
                "status": "timed_out",
                "termination_confirmed": termination_confirmed,
                "error": {
                    "type": "TimeoutExpired",
                    "message": f"LS-DYNA INIT exceeded timeout_s={timeout_value}",
                },
            }
        )
    else:
        record["status"] = "completed" if returncode == 0 else "solver_failed"

    evidence = _inspect_initialization_smoke(smoke_dir)
    record["evidence"] = evidence
    record["ok"] = bool(record["status"] == "completed" and returncode == 0 and evidence["ok"])
    return _finish_smoke_record(smokes_dir, smoke_dir, record)


def _inspect_initialization_smoke(smoke_dir: Path) -> JSONDict:
    sources: list[Path] = []
    for path in smoke_dir.iterdir():
        lower = path.name.lower()
        if path.is_file() and (lower.startswith("d3hsp") or lower.startswith("mes") or lower == "solver_stdout.txt"):
            sources.append(path)
    sources.sort(key=lambda item: item.name.lower())
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in sources)
    parsed = parse_d3hsp(text)
    cycles = [
        int(match.group(1))
        for match in re.finditer(
            r"(?im)^\s*(?:problem\s+)?cycle\s*(?:=|:)\s*([0-9]+)\b",
            text,
        )
    ]
    keyword_errors = [
        line.strip()
        for line in text.splitlines()
        if re.search(r"(?i)\*\*\*\s*error\s+[0-9]+", line)
    ][:20]
    maximum_cycle = max(cycles, default=0)
    solver_cycles_completed = maximum_cycle >= 1
    terminated_normally = bool(parsed.get("terminated_normally"))
    memory_check_completed = bool(
        re.search(
            r"(?i)memory\s+required\s+to\s+begin\s+solution",
            text,
        )
    )
    return {
        "ok": bool(
            sources
            and solver_cycles_completed
            and maximum_cycle <= 10
            and memory_check_completed
            and terminated_normally
            and not keyword_errors
        ),
        "sources": [str(path) for path in sources],
        "maximum_cycle": maximum_cycle,
        "solver_cycles_completed": solver_cycles_completed,
        "memory_check_completed": memory_check_completed,
        "terminated_normally": terminated_normally,
        "termination_marker": parsed.get("termination_marker"),
        "keyword_errors": keyword_errors,
    }


def inspect_solver_outputs(run_dir: Path) -> JSONDict:
    records: JSONDict = {}
    for prefix in OUTPUT_PREFIXES:
        matches = _nonempty_files_with_prefix(run_dir, prefix)
        records[prefix] = {
            "ok": bool(matches),
            "files": matches,
            "total_size_bytes": sum(int(item["size_bytes"]) for item in matches),
        }
    d3hsp = _nonempty_files_with_prefix(run_dir, "d3hsp")
    records["d3hsp"] = {
        "ok": bool(d3hsp),
        "files": d3hsp,
        "total_size_bytes": sum(int(item["size_bytes"]) for item in d3hsp),
    }
    return records


def latest_lsdyna_run(project: Path) -> JSONDict:
    project = project.resolve()
    runs_dir = project / "solver_runs"
    path = runs_dir / "latest.json"
    if not path.is_file():
        return {
            "ok": True,
            "operation": "lsdyna_status",
            "project_name": project.name,
            "status": "not_started",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("latest LS-DYNA run record is unreadable") from exc
    if not isinstance(data, dict):
        raise ValueError("latest LS-DYNA run record must be an object")
    run_record_identity = _latest_run_record_identity(runs_dir, data)
    if run_record_identity.get("ok") is not True:
        return {
            **data,
            "ok": False,
            "status": "invalid_evidence",
            "evidence_integrity": {
                "ok": False,
                "reason": run_record_identity.get(
                    "reason",
                    "run_record_identity_mismatch",
                ),
                "run_record_identity": run_record_identity,
            },
        }
    data["run_record_identity"] = run_record_identity
    if data.get("status") in {"starting", "running"}:
        if _recorded_solver_process_is_running(data):
            return data
        run_id = data.get("run_id")
        if not isinstance(run_id, str) or not re.fullmatch(r"run_[A-Za-z0-9_]+", run_id):
            raise ValueError("latest LS-DYNA run record has an invalid run_id")
        run_dir = (runs_dir / run_id).resolve()
        if run_dir.parent != runs_dir.resolve() or not run_dir.is_dir():
            raise ValueError("latest LS-DYNA run directory is unavailable")
        mode = str(data.get("result_mode") or _result_mode(project))
        result_variant = str(data.get("result_variant") or _result_variant(project))
        evaluation = _evaluate_d3hsp(run_dir, mode, result_variant)
        normal_termination = bool(
            evaluation.get("parsed", {}).get("terminated_normally")
        )
        recovered_at = _utc_now()
        data["recovery"] = {
            "status_was": data.get("status"),
            "reason": "recorded_solver_process_not_running",
            "recovered_at_utc": recovered_at,
            "returncode_source": (
                "d3hsp_normal_termination"
                if normal_termination
                else "unavailable"
            ),
        }
        data["finished_at_utc"] = recovered_at
        started_at = data.get("started_at_utc")
        if isinstance(started_at, str):
            data["duration_s"] = _duration_seconds(started_at, recovered_at)
        if normal_termination:
            data["status"] = "completed"
            data["returncode"] = 0
        else:
            data["status"] = "solver_failed"
            data["returncode"] = None
            data["error"] = {
                "type": "OrphanedSolverRun",
                "message": (
                    "recorded solver process exited without a recoverable "
                    "normal-termination marker"
                ),
            }
        _refresh_terminal_record(project, runs_dir, data)
    elif data.get("status") in {"completed", "solver_failed", "timed_out"}:
        _refresh_terminal_record(project, runs_dir, data)
    return data


def _latest_run_record_identity(
    runs_dir: Path,
    latest_record: JSONDict,
) -> JSONDict:
    run_id = latest_record.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(
        r"run_[A-Za-z0-9_]+",
        run_id,
    ):
        return {
            "ok": False,
            "reason": "run_record_identity_invalid",
            "mismatched_fields": ["run_id"],
        }
    run_dir = (runs_dir / run_id).resolve()
    if run_dir.parent != runs_dir.resolve() or not run_dir.is_dir():
        return {
            "ok": False,
            "reason": "run_record_unavailable",
            "mismatched_fields": [],
        }
    run_record, error = _read_run_record(run_dir / "run.json")
    if error is not None:
        return {
            "ok": False,
            "reason": "run_record_unreadable",
            "mismatched_fields": [],
            "error": error,
        }
    return validate_run_record_identity(latest_record, run_record)


def _recorded_solver_process_is_running(record: JSONDict) -> bool:
    pid = record.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    info = process_info(pid)
    if info is None:
        return False
    solver = record.get("solver")
    solver_path = solver.get("path") if isinstance(solver, dict) else None
    expected_name = Path(str(solver_path)).name.lower() if solver_path else ""
    image_name = str(info.get("image_name", "")).lower()
    if expected_name:
        return image_name == expected_name
    return True


def record_lsprepost_postprocessing(
    project: Path,
    run_id: str,
    image_path: Path,
    *,
    state_number: int,
    component_label: str,
    lspp_returncode: int,
    cfile_sha256: str,
    maximum_value_pa: float | None = None,
    state_time_s: float | None = None,
    peak_displacement_m: float | None = None,
    peak_displacement_state: int | None = None,
    peak_displacement_time_s: float | None = None,
) -> JSONDict:
    project = project.resolve()
    runs_dir = project / "solver_runs"
    if not re.fullmatch(r"run_[A-Za-z0-9_]+", run_id):
        raise ValueError("run_id is invalid")
    if isinstance(state_number, bool) or not isinstance(state_number, int) or state_number < 1:
        raise ValueError("state_number must be a positive integer")
    contour_flag = {
        "Effective Stress (v-m)": "stress_cloud_recorded",
        "Pressure": "pressure_cloud_recorded",
    }.get(component_label)
    if contour_flag is None:
        raise ValueError("component_label must identify a controlled stress or pressure result")
    if lspp_returncode != 0:
        raise ValueError("LS-PrePost verification requires returncode 0")
    if not re.fullmatch(r"[0-9a-f]{64}", cfile_sha256):
        raise ValueError("cfile_sha256 must be a lowercase SHA-256 digest")

    run_dir = (runs_dir / run_id).resolve()
    record_path = run_dir / "run.json"
    latest_path = runs_dir / "latest.json"
    if not record_path.is_file() or not latest_path.is_file():
        raise FileNotFoundError("LS-DYNA run record is unavailable")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    if not isinstance(record, dict) or record.get("run_id") != run_id:
        raise ValueError("LS-DYNA run record does not match run_id")
    if not isinstance(latest, dict) or latest.get("run_id") != run_id:
        raise ValueError("only the latest LS-DYNA run can be post-processed")

    image = image_path.resolve()
    artifacts = (project / "artifacts").resolve()
    if image.parent != artifacts or not image.is_file():
        raise ValueError("post-processing image must be a project artifact PNG")
    if image.suffix.lower() != ".png" or image.read_bytes()[:8] != PNG_SIGNATURE:
        raise ValueError("post-processing image must have a valid PNG signature")
    if maximum_value_pa is not None and (not math.isfinite(maximum_value_pa) or maximum_value_pa <= 0.0):
        raise ValueError("maximum_value_pa must be finite and positive")
    if state_time_s is not None and (not math.isfinite(state_time_s) or state_time_s < 0.0):
        raise ValueError("state_time_s must be finite and non-negative")
    if peak_displacement_m is not None and (
        not math.isfinite(peak_displacement_m) or peak_displacement_m < 0.0
    ):
        raise ValueError("peak_displacement_m must be finite and non-negative")
    if peak_displacement_state is not None and (
        isinstance(peak_displacement_state, bool)
        or not isinstance(peak_displacement_state, int)
        or peak_displacement_state < 1
    ):
        raise ValueError("peak_displacement_state must be a positive integer")
    if peak_displacement_time_s is not None and (
        not math.isfinite(peak_displacement_time_s) or peak_displacement_time_s < 0.0
    ):
        raise ValueError("peak_displacement_time_s must be finite and non-negative")

    existing_post = record.get("postprocessing")
    postprocessing = dict(existing_post) if isinstance(existing_post, dict) else {}
    postprocessing.update({
        "status": "verified",
        "component": component_label,
        "state_number": state_number,
        "maximum_value_pa": maximum_value_pa,
        "state_time_s": state_time_s,
        "peak_displacement_m": peak_displacement_m,
        "peak_displacement_state": peak_displacement_state,
        "peak_displacement_time_s": peak_displacement_time_s,
        "image_relative_path": str(image.relative_to(project)),
        "image_sha256": _sha256(image),
        "image_size_bytes": image.stat().st_size,
        "lspp_returncode": lspp_returncode,
        "cfile_sha256": cfile_sha256,
        "verified_at_utc": _utc_now(),
        "verification_basis": "LS-PrePost controlled cfile, PNG validation, and visual contour review",
    })
    postprocessing[contour_flag] = True
    postprocessing.pop("note", None)
    record["postprocessing"] = postprocessing
    _persist_record(runs_dir, run_dir, record)
    return record["postprocessing"]


def record_blast_pressure_history(project: Path, run_id: str, history_path: Path) -> JSONDict:
    """Extract positive-phase metrics from a controlled LS-PrePost history export."""
    project = project.resolve()
    runs_dir = project / "solver_runs"
    if not re.fullmatch(r"run_[A-Za-z0-9_]+", run_id):
        raise ValueError("run_id is invalid")

    run_dir = (runs_dir / run_id).resolve()
    record_path = run_dir / "run.json"
    latest_path = runs_dir / "latest.json"
    if not record_path.is_file() or not latest_path.is_file():
        raise FileNotFoundError("LS-DYNA run record is unavailable")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    if not isinstance(record, dict) or record.get("run_id") != run_id:
        raise ValueError("LS-DYNA run record does not match run_id")
    if not isinstance(latest, dict) or latest.get("run_id") != run_id:
        raise ValueError("only the latest LS-DYNA run can be post-processed")

    source = history_path.resolve()
    artifacts = (project / "artifacts").resolve()
    if source.parent != artifacts or not source.is_file():
        raise ValueError("pressure history must be a file in project artifacts")
    if source.suffix.lower() not in {".csv", ".txt", ".dat"} or source.stat().st_size <= 0:
        raise ValueError("pressure history must be a non-empty CSV, TXT, or DAT file")

    history = _read_two_column_history(source)
    positive_indices = [index for index, (_, pressure) in enumerate(history) if pressure > 0.0]
    if len(positive_indices) < 2:
        raise ValueError("pressure history must contain at least two positive-phase samples")
    peak_index = max(positive_indices, key=lambda index: history[index][1])
    start = peak_index
    while start > 0 and history[start - 1][1] > 0.0:
        start -= 1
    finish = peak_index
    while finish + 1 < len(history) and history[finish + 1][1] > 0.0:
        finish += 1
    if finish <= start:
        raise ValueError("pressure history has no measurable positive-phase duration")
    segment = history[start : finish + 1]
    impulse = sum(
        (right[0] - left[0]) * (left[1] + right[1]) * 0.5
        for left, right in zip(segment, segment[1:])
    )
    peak_time, peak_pressure = history[peak_index]
    metrics: JSONDict = {
        "peak_pressure_pa": peak_pressure,
        "peak_time_s": peak_time,
        "positive_duration_s": segment[-1][0] - segment[0][0],
        "positive_impulse_pa_s": impulse,
        "sample_count": len(history),
        "positive_sample_count": len(segment),
        "source_relative_path": str(source.relative_to(project)),
        "source_sha256": _sha256(source),
        "source_size_bytes": source.stat().st_size,
        "source_units": {"time": "s", "pressure": "Pa"},
        "extraction_method": "LS-PrePost exported pressure history",
        "extracted_at_utc": _utc_now(),
    }
    post = record.get("postprocessing")
    record["postprocessing"] = dict(post) if isinstance(post, dict) else {}
    record["postprocessing"]["blast_pressure"] = metrics
    _persist_record(runs_dir, run_dir, record)
    return metrics


def _read_two_column_history(path: Path) -> list[tuple[float, float]]:
    values: list[tuple[float, float]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(("#", "$")):
            continue
        columns = [item for item in re.split(r"[,;\s]+", line) if item]
        if len(columns) < 2:
            raise ValueError(f"pressure history line {line_number} must contain time and pressure")
        try:
            time_s = float(columns[0])
            pressure_pa = float(columns[1])
        except ValueError:
            if not values:
                continue
            raise ValueError(f"pressure history line {line_number} contains non-numeric data") from None
        if not math.isfinite(time_s) or not math.isfinite(pressure_pa):
            raise ValueError("pressure history values must be finite")
        if values and time_s <= values[-1][0]:
            raise ValueError("pressure history time must be strictly increasing")
        values.append((time_s, pressure_pa))
    if len(values) < 2:
        raise ValueError("pressure history must contain at least two numeric samples")
    return values


def _refresh_terminal_record(project: Path, runs_dir: Path, record: JSONDict) -> None:
    run_id = record.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"run_[A-Za-z0-9_]+", run_id):
        raise ValueError("latest LS-DYNA run record has an invalid run_id")
    run_dir = (runs_dir / run_id).resolve()
    if run_dir.parent != runs_dir.resolve() or not run_dir.is_dir():
        raise ValueError("latest LS-DYNA run directory is unavailable")

    result_variant = str(record.get("result_variant") or _result_variant(project))
    if result_variant == "ale_blast":
        identity = record.get("run_record_identity")
        if not isinstance(identity, dict):
            identity = {
                "ok": False,
                "reason": "run_record_identity_missing",
                "mismatched_fields": [],
            }
        evidence_integrity = validate_phase14_run_evidence(
            run_dir,
            record.get("evidence_manifest"),
        )
        evidence_integrity["run_record_identity"] = identity
        evidence_integrity["ok"] = bool(
            evidence_integrity.get("ok") and identity.get("ok")
        )
        if evidence_integrity["ok"] is not True:
            if identity.get("ok") is not True:
                evidence_integrity["reason"] = identity.get(
                    "reason",
                    "run_record_identity_mismatch",
                )
            record["evidence_integrity"] = evidence_integrity
            record["wave_transfer_acceptance"] = {
                "applicable": True,
                "status": "invalid_evidence",
                "wave_transfer_verified": False,
                "checks": [
                    {
                        "id": "sealed_run_evidence_valid",
                        "ok": False,
                        "actual": evidence_integrity,
                    }
                ],
                "metrics": {},
            }
            record["ok"] = False
            _persist_record(runs_dir, run_dir, record)
            return

    mode = record.get("result_mode")
    if mode not in {"impact", "blast"}:
        mode = _result_mode(project)
        record["result_mode"] = mode
    if mode == "blast":
        record["blast_configuration"] = _project_blast_configuration(project)
    outputs = inspect_solver_outputs(run_dir)
    record["result_variant"] = result_variant
    evaluation = _evaluate_d3hsp(run_dir, mode, result_variant)
    wave_transfer_ok = True
    if result_variant == "phase15_axisymmetric_blast":
        acceptance = _phase15_wave_transfer_acceptance(project, run_dir)
        record["wave_transfer_acceptance"] = acceptance
        _write_json_atomic(run_dir / "wave_transfer_acceptance.json", acceptance)
        wave_transfer_ok = bool(acceptance.get("wave_transfer_verified"))
    elif result_variant == "city_street_blast":
        acceptance = _city_wave_transfer_acceptance(project, run_dir)
        record["wave_transfer_acceptance"] = acceptance
        _write_json_atomic(run_dir / "wave_transfer_acceptance.json", acceptance)
        recovery = record.get("recovery")
        evidence_integrity = _ensure_city_run_evidence(
            run_dir,
            record,
            allow_create=(
                isinstance(recovery, dict)
                and recovery.get("returncode_source")
                == "d3hsp_normal_termination"
            ),
        )
        identity = record.get("run_record_identity")
        evidence_integrity["run_record_identity"] = identity
        evidence_integrity["ok"] = bool(
            evidence_integrity.get("ok")
            and isinstance(identity, dict)
            and identity.get("ok") is True
        )
        wave_transfer_ok = bool(
            acceptance.get("wave_transfer_verified")
            and evidence_integrity.get("ok")
        )
    elif result_variant == "ale_blast":
        acceptance = evaluate_phase14_wave_transfer(
            project,
            run_dir,
            run_record=record,
        )
        record["wave_transfer_acceptance"] = acceptance
        _write_json_atomic(run_dir / "wave_transfer_acceptance.json", acceptance)
        wave_transfer_ok = (
            bool(acceptance.get("wave_transfer_verified"))
            or (
                acceptance.get("applicable") is False
                and acceptance.get("status") == "not_applicable"
            )
        )
    required_outputs_ok = bool(outputs["d3plot"]["ok"])
    if mode == "blast":
        if result_variant == "phase15_axisymmetric_blast":
            required_outputs_ok = required_outputs_ok and bool(
                outputs["d3hsp"]["ok"] and outputs["elout"]["ok"]
            )
        elif result_variant == "city_street_blast":
            required_outputs_ok = required_outputs_ok and bool(
                outputs["d3hsp"]["ok"]
                and outputs["matsum"]["ok"]
                and outputs["elout"]["ok"]
                and outputs["nodout"]["ok"]
                and (outputs["fsifor"]["ok"] or outputs["dbfsi"]["ok"])
            )
        elif result_variant == "ale_blast":
            required_outputs_ok = required_outputs_ok and bool(
                outputs["fsifor"]["ok"] or outputs["dbfsi"]["ok"]
            )
        else:
            required_outputs_ok = required_outputs_ok and bool(outputs["blstfor"]["ok"])
    normal_termination = bool(evaluation.get("parsed", {}).get("terminated_normally"))

    record["project_dir"] = str(project)
    record["run_dir"] = str(run_dir)
    record["input"] = str(run_dir / "model.k")
    record["outputs"] = outputs
    record["solver_evaluation"] = evaluation
    record.setdefault(
        "postprocessing",
        {
            "status": (
                "requires_lsprepost_verification"
                if outputs["d3plot"]["ok"]
                else "d3plot_unavailable"
            ),
            "stress_cloud_recorded": False,
            "note": (
                "A non-empty d3plot is necessary but LS-PrePost must still verify "
                "non-zero displacement and stress contours."
            ),
        },
    )
    record["ok"] = bool(
        record.get("status") == "completed"
        and record.get("returncode") == 0
        and required_outputs_ok
        and normal_termination
        and evaluation.get("ok")
        and wave_transfer_ok
    )
    _persist_record(runs_dir, run_dir, record)


def _evaluate_d3hsp(run_dir: Path, mode: str, result_variant: str = "standard") -> JSONDict:
    candidates = [path for path in run_dir.iterdir() if path.is_file() and path.name.lower().startswith("d3hsp")]
    if not candidates:
        return {
            "ok": False,
            "mode": mode,
            "checks": [{"id": "d3hsp_present", "ok": False, "actual": None}],
            "parsed": {"terminated_normally": False, "termination_marker": "missing"},
        }
    source = candidates[0]
    text = source.read_text(encoding="utf-8", errors="replace")
    glstat_candidates = [
        path for path in run_dir.iterdir() if path.is_file() and path.name.lower().startswith("glstat")
    ]
    if glstat_candidates:
        text += "\n" + glstat_candidates[0].read_text(encoding="utf-8", errors="replace")
    expected_termination_time_s: float | None = None
    if mode == "initial_validation":
        model_json = run_dir / "model.json"
        try:
            model = json.loads(model_json.read_text(encoding="utf-8"))
            spec = model.get("spec") if isinstance(model, dict) else None
            raw_termination = (
                spec.get("termination_time_s") if isinstance(spec, dict) else None
            )
            if (
                isinstance(raw_termination, (int, float))
                and not isinstance(raw_termination, bool)
                and math.isfinite(float(raw_termination))
                and float(raw_termination) > 0.0
            ):
                expected_termination_time_s = float(raw_termination)
        except (OSError, json.JSONDecodeError):
            pass
    result = evaluate_solver_result(
        text,
        mode,
        expected_termination_time_s=expected_termination_time_s,
    )
    if result_variant in {
        "ale_blast",
        "phase15_axisymmetric_blast",
        "city_street_blast",
    }:
        for check in result.get("checks", []):
            if check.get("id") != "blast_total_energy_ratio":
                continue
            ratio = check.get("actual")
            ratio_ok = (
                isinstance(ratio, (int, float))
                and math.isfinite(float(ratio))
                and float(ratio) > 0.0
            )
            check.update(
                {
                    "id": "ale_reactive_energy_ratio_finite",
                    "ok": ratio_ok,
                    "limit": {"minimum_exclusive": 0.0},
                    "note": (
                        "High-explosive burn releases chemical energy that is not "
                        "represented by the initial mechanical-energy denominator. "
                        "Normal termination, finite energies, hourglass control, and "
                        "variant-specific pressure/transfer gates remain required."
                    ),
                }
            )
        result["ok"] = all(bool(check.get("ok")) for check in result.get("checks", []))
        result["metrics"]["reactive_total_initial_energy_ratio"] = result["metrics"].pop(
            "total_initial_ratio", None
        )
    result["source"] = {
        "path": str(source),
        "sha256": _sha256(source),
        "size_bytes": source.stat().st_size,
    }
    if mode == "blast" and result_variant not in {
        "ale_blast",
        "phase15_axisymmetric_blast",
        "city_street_blast",
    }:
        blstfor_candidates = [
            path for path in run_dir.iterdir() if path.is_file() and path.name.lower().startswith("blstfor")
        ]
        if not blstfor_candidates:
            result["blstfor"] = {"status": "unavailable", "reason": "blstfor file is missing"}
        else:
            blstfor_source = blstfor_candidates[0]
            try:
                blstfor = parse_blstfor(blstfor_source.read_bytes())
            except (OSError, TypeError, ValueError) as exc:
                result["blstfor"] = {
                    "status": "parse_failed",
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
            else:
                blstfor["status"] = "available" if blstfor.get("ok") else "unavailable"
                blstfor["source"] = {
                    "path": str(blstfor_source),
                    "sha256": _sha256(blstfor_source),
                    "size_bytes": blstfor_source.stat().st_size,
                }
                result["blstfor"] = blstfor
                if blstfor.get("ok"):
                    result["metrics"].update(
                        {
                            "sampled_peak_blast_pressure_pa": blstfor["sampled_peak_pressure_pa"],
                            "sampled_peak_blast_pressure_time_s": blstfor["sampled_peak_time_s"],
                            "positive_phase_duration_s": blstfor.get("positive_duration_s"),
                            "positive_phase_impulse_pa_s": blstfor.get("positive_impulse_pa_s"),
                            "positive_phase_quality": blstfor.get("positive_phase_quality"),
                            "positive_phase_sample_count": blstfor.get("positive_sample_count"),
                        }
                    )
    elif mode == "blast":
        result["blstfor"] = {
            "status": "not_applicable",
            "reason": "MM-ALE blast uses d3plot ALE pressure and dbfsi coupling output",
        }
        dbfsi_candidates = [
            path for path in run_dir.iterdir() if path.is_file() and path.name.lower().startswith("dbfsi")
        ]
        if not dbfsi_candidates:
            result["dbfsi"] = {"status": "unavailable", "reason": "dbfsi file is missing"}
        else:
            dbfsi_source = dbfsi_candidates[0]
            try:
                dbfsi = parse_dbfsi(dbfsi_source.read_text(encoding="utf-8", errors="replace"))
            except (OSError, TypeError, ValueError) as exc:
                result["dbfsi"] = {
                    "status": "parse_failed",
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
            else:
                dbfsi["status"] = "available"
                dbfsi["source"] = {
                    "path": str(dbfsi_source),
                    "sha256": _sha256(dbfsi_source),
                    "size_bytes": dbfsi_source.stat().st_size,
                }
                result["dbfsi"] = dbfsi
                result["metrics"].update(
                    {
                        "peak_coupled_surface_pressure_pa": dbfsi["peak_coupled_surface_pressure_pa"],
                        "peak_fsi_force_n": dbfsi["peak_resultant_force_n"],
                        "fsi_impulse_n_s": dbfsi["fsi_impulse_magnitude_n_s"],
                    }
                )
    nodout_candidates = [
        path for path in run_dir.iterdir() if path.is_file() and path.name.lower().startswith("nodout")
    ]
    if not nodout_candidates:
        result["nodout"] = {"status": "unavailable", "reason": "nodout file is missing"}
        return result
    nodout_source = nodout_candidates[0]
    try:
        nodout = parse_nodout(nodout_source.read_text(encoding="utf-8", errors="replace"))
    except (OSError, TypeError, ValueError) as exc:
        result["nodout"] = {
            "status": "parse_failed",
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
        return result
    nodout["status"] = "available" if nodout.get("ok") else "unavailable"
    nodout["source"] = {
        "path": str(nodout_source),
        "sha256": _sha256(nodout_source),
        "size_bytes": nodout_source.stat().st_size,
    }
    result["nodout"] = nodout
    if nodout.get("ok"):
        result["metrics"].update(
            {
                "peak_displacement_m": nodout["peak_displacement_m"],
                "peak_displacement_node_id": nodout["peak_node_id"],
                "peak_displacement_time_step": nodout["peak_time_step"],
                "peak_displacement_time_s": nodout["peak_time_s"],
            }
        )
    return result


def _result_mode(project: Path) -> str:
    model_path = project / "model.json"
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "impact"
    spec = model.get("spec", {}) if isinstance(model, dict) else {}
    if isinstance(spec, dict) and spec.get("model_type") in {
        "ale_blast_scene",
        "phase15_axisymmetric_blast",
        "city_street_blast_scene",
    }:
        return "blast"
    if isinstance(spec, dict) and spec.get("model_type") == "refined_building_initial_validation":
        return "initial_validation"
    loads = spec.get("loads", []) if isinstance(spec, dict) else []
    if any(isinstance(item, dict) and item.get("type") == "blast_enhanced" for item in loads):
        return "blast"
    return "impact"


def _result_variant(project: Path) -> str:
    model_path = project / "model.json"
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "standard"
    spec = model.get("spec", {}) if isinstance(model, dict) else {}
    if not isinstance(spec, dict):
        return "standard"
    if spec.get("model_type") == "ale_blast_scene":
        return "ale_blast"
    if spec.get("model_type") == "phase15_axisymmetric_blast":
        return "phase15_axisymmetric_blast"
    if spec.get("model_type") == "city_street_blast_scene":
        return "city_street_blast"
    return "standard"


def _city_wave_transfer_acceptance(
    project: Path,
    run_dir: Path,
) -> JSONDict:
    model_path = run_dir / "model.json"
    if not model_path.is_file():
        model_path = project / "model.json"
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "applicable": True,
            "wave_transfer_verified": False,
            "blocking_check_ids": ["city_model_metadata"],
            "checks": [
                {
                    "id": "city_model_metadata",
                    "ok": False,
                    "actual": f"{type(exc).__name__}: {exc}",
                }
            ],
            "responding_object_ids": [],
        }

    metadata = model.get("metadata") if isinstance(model, dict) else None
    if not isinstance(metadata, dict):
        metadata = {}
    spec = model.get("spec") if isinstance(model, dict) else None
    if not isinstance(spec, dict):
        spec = {}
    analysis = spec.get("analysis")
    if not isinstance(analysis, dict):
        analysis = {}
    history_interval_s = analysis.get("history_dt_s", 0.0)
    if not _finite_above(history_interval_s, 0.0):
        history_interval_s = 0.0
    fsi = metadata.get("fsi")
    if not isinstance(fsi, dict):
        fsi = {}
    semantic_objects = metadata.get("semantic_objects")
    if not isinstance(semantic_objects, list):
        semantic_objects = []
    response_objects = metadata.get("response_objects")
    if not isinstance(response_objects, list):
        response_objects = []

    dbfsi: JSONDict = {}
    dbfsi_error = ""
    dbfsi_path = run_dir / "dbfsi"
    try:
        dbfsi = parse_dbfsi(
            dbfsi_path.read_text(encoding="utf-8", errors="replace")
        )
    except (OSError, TypeError, ValueError) as exc:
        dbfsi_error = f"{type(exc).__name__}: {exc}"

    surfaces = dbfsi.get("surfaces")
    if not isinstance(surfaces, list):
        surfaces = []
    pressure = max(
        (
            float(item.get("peak_pressure_rise_pa", 0.0))
            for item in surfaces
            if isinstance(item, dict)
        ),
        default=None,
    )
    force = max(
        (
            float(item.get("peak_force_rise_n", 0.0))
            for item in surfaces
            if isinstance(item, dict)
        ),
        default=None,
    )
    impulse = max(
        (
            float(item.get("fsi_impulse_magnitude_n_s", 0.0))
            for item in surfaces
            if isinstance(item, dict)
        ),
        default=None,
    )
    response_targets = [
        item
        for item in semantic_objects
        if isinstance(item, dict)
        and item.get("supports_ale_fsi") is True
        and item.get("constraint_mode") in {"base_fixed", "tied_to_ground"}
    ]
    diagnostics = _matsum_diagnostics(
        run_dir / "matsum",
        response_targets,
    )
    target_ids = sorted(
        str(item.get("object_id", ""))
        for item in response_objects
        if isinstance(item, dict) and str(item.get("object_id", ""))
    )
    object_results: dict[str, JSONDict] = {}
    object_response_error = ""
    if response_objects:
        try:
            object_results = parse_city_object_responses(
                dbfsi_path.read_text(encoding="utf-8", errors="replace"),
                (run_dir / "elout").read_text(
                    encoding="utf-8",
                    errors="replace",
                ),
                (run_dir / "nodout").read_text(
                    encoding="utf-8",
                    errors="replace",
                ),
                response_objects,
            )
        except (OSError, KeyError, TypeError, ValueError) as exc:
            object_response_error = f"{type(exc).__name__}: {exc}"
    semantic_by_id = {
        str(item.get("object_id")): item
        for item in semantic_objects
        if isinstance(item, dict) and item.get("object_id")
    }
    object_acceptance: dict[str, JSONDict] = {}
    for object_id in target_ids:
        result = object_results.get(object_id, {})
        semantic = semantic_by_id.get(object_id, {})
        bounds = semantic.get("bounds_m")
        displacement_limit = 1.0
        if isinstance(bounds, dict):
            lower = bounds.get("min")
            upper = bounds.get("max")
            if (
                isinstance(lower, list)
                and isinstance(upper, list)
                and len(lower) == 3
                and len(upper) == 3
            ):
                diagonal = math.sqrt(
                    sum(
                        (float(high) - float(low)) ** 2
                        for low, high in zip(lower, upper, strict=True)
                    )
                )
                displacement_limit = max(0.05, 0.25 * diagonal)
        checks_by_name = {
            "fsi_surface": result.get("fsi_present") is True,
            "fsi_pressure": _finite_above(
                result.get("peak_fsi_pressure_rise_pa"),
                100.0,
            ),
            "fsi_duration": (
                int(result.get("fsi_positive_pressure_sample_count", 0)) >= 2
                and _finite_above(
                    result.get("fsi_positive_pressure_duration_s"),
                    0.0,
                )
            ),
            "structural_pressure": _finite_above(
                result.get("peak_structural_pressure_pa"),
                100.0,
            ),
            "principal_stress": _finite_above(
                result.get("peak_principal_stress_pa"),
                100.0,
            ),
            "displacement": (
                _finite_above(result.get("peak_displacement_m"), 1.0e-9)
                and float(result["peak_displacement_m"]) < displacement_limit
            ),
            "arrival_order": (
                _finite_number(result.get("fsi_arrival_time_s"))
                and _finite_number(result.get("structural_arrival_time_s"))
                and float(result["structural_arrival_time_s"])
                >= float(result["fsi_arrival_time_s"])
                - float(history_interval_s)
            ),
            "observation_window": (
                _finite_number(result.get("fsi_arrival_time_s"))
                and _finite_number(result.get("last_response_time_s"))
                and float(result["last_response_time_s"])
                - float(result["fsi_arrival_time_s"])
                >= 0.020
            ),
        }
        object_acceptance[object_id] = {
            "ok": all(checks_by_name.values()),
            "checks": checks_by_name,
            "metrics": result,
            "displacement_limit_m": displacement_limit,
        }
    responding_object_ids = sorted(
        object_id
        for object_id, result in object_acceptance.items()
        if result["ok"]
    )

    checks: list[JSONDict] = []

    def add(check_id: str, ok: bool, actual: object, limit: object) -> None:
        checks.append(
            {
                "id": check_id,
                "ok": bool(ok),
                "actual": actual,
                "limit": limit,
            }
        )

    slave_segment_count = fsi.get("slave_segment_count")
    fully_constrained_count = fsi.get(
        "fully_constrained_slave_segment_count"
    )
    add(
        "city_fsi_segments",
        isinstance(slave_segment_count, int)
        and slave_segment_count > 0
        and fully_constrained_count == 0,
        {
            "slave_segment_count": slave_segment_count,
            "fully_constrained_slave_segment_count": fully_constrained_count,
        },
        {
            "slave_segment_count_minimum": 1,
            "fully_constrained_slave_segment_count_maximum": 0,
        },
    )
    add(
        "city_fsi_pressure",
        isinstance(pressure, (int, float))
        and math.isfinite(float(pressure))
        and float(pressure) > 100.0,
        pressure if pressure is not None else dbfsi_error,
        {"minimum_exclusive_pa": 100.0},
    )
    add(
        "city_fsi_force",
        isinstance(force, (int, float))
        and math.isfinite(float(force))
        and float(force) > 10.0,
        force if force is not None else dbfsi_error,
        {"minimum_exclusive_n": 10.0},
    )
    add(
        "city_fsi_impulse",
        isinstance(impulse, (int, float))
        and math.isfinite(float(impulse))
        and float(impulse) > 1.0e-3,
        impulse if impulse is not None else dbfsi_error,
        {"minimum_exclusive_n_s": 1.0e-3},
    )
    add(
        "city_object_response_contract",
        bool(response_objects) and bool(target_ids),
        {
            "target_object_ids": target_ids,
            "response_object_count": len(response_objects),
        },
        {"minimum_response_object_count": 1},
    )
    add(
        "city_object_structural_response",
        bool(target_ids) and responding_object_ids == target_ids,
        {
            "target_object_ids": target_ids,
            "responding_object_ids": responding_object_ids,
            "objects": object_acceptance,
            "error": object_response_error or None,
        },
        {
            "minimum_fsi_pressure_rise_pa": 100.0,
            "minimum_structural_pressure_pa": 100.0,
            "minimum_principal_stress_pa": 100.0,
            "minimum_displacement_m": 1.0e-9,
            "minimum_positive_pressure_samples": 2,
        },
    )
    add(
        "city_object_arrival_order",
        bool(target_ids)
        and all(
            item["checks"]["arrival_order"]
            for item in object_acceptance.values()
        ),
        {
            object_id: {
                "fsi_arrival_time_s": item["metrics"].get(
                    "fsi_arrival_time_s"
                ),
                "structural_arrival_time_s": item["metrics"].get(
                    "structural_arrival_time_s"
                ),
            }
            for object_id, item in object_acceptance.items()
        },
        {"early_tolerance_s": history_interval_s},
    )
    add(
        "city_object_observation_window",
        bool(target_ids)
        and all(
            item["checks"]["observation_window"]
            for item in object_acceptance.values()
        ),
        {
            object_id: {
                "fsi_arrival_time_s": item["metrics"].get(
                    "fsi_arrival_time_s"
                ),
                "last_response_time_s": item["metrics"].get(
                    "last_response_time_s"
                ),
            }
            for object_id, item in object_acceptance.items()
        },
        {"minimum_post_arrival_window_s": 0.020},
    )
    add(
        "city_response_objects",
        bool(target_ids) and responding_object_ids == target_ids,
        {
            "target_object_ids": target_ids,
            "responding_object_ids": responding_object_ids,
            "diagnostics": diagnostics,
        },
        {
            "all_target_objects_must_respond": True,
            "matsum_is_diagnostic_only": True,
        },
    )
    ground_crater: JSONDict | None = None
    ground_metadata = metadata.get("ground_response")
    if (
        isinstance(ground_metadata, dict)
        and ground_metadata.get("mode") == "validation_crater"
    ):
        ground_crater = evaluate_city_ground_crater(run_dir, ground_metadata)
        crater_checks = ground_crater.get("checks")
        if isinstance(crater_checks, list):
            checks.extend(
                item for item in crater_checks if isinstance(item, dict)
            )
    blocking = [item["id"] for item in checks if not item["ok"]]
    return {
        "applicable": True,
        "wave_transfer_verified": not blocking,
        "blocking_check_ids": blocking,
        "checks": checks,
        "dbfsi": dbfsi,
        "responding_object_ids": responding_object_ids,
        "target_object_ids": target_ids,
        "response_diagnostics": diagnostics,
        "object_response": object_acceptance,
        "ground_crater": ground_crater,
    }


def _finite_above(value: object, minimum: float) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > minimum
    )


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _ensure_city_run_evidence(
    run_dir: Path,
    record: JSONDict,
    *,
    allow_create: bool,
) -> JSONDict:
    record["required_outputs"] = list(CITY_REQUIRED_EVIDENCE)
    reference = record.get("evidence_manifest")
    if not isinstance(reference, dict):
        if not allow_create:
            integrity = {
                "ok": False,
                "reason": "evidence_manifest_reference_missing",
            }
            record["evidence_integrity"] = integrity
            return integrity
        try:
            reference = seal_phase14_run_evidence(
                run_dir,
                required_output_prefixes=CITY_REQUIRED_EVIDENCE,
            )
        except (OSError, TypeError, ValueError) as exc:
            integrity: JSONDict = {
                "ok": False,
                "reason": "evidence_manifest_write_failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
            record["evidence_integrity"] = integrity
            return integrity
        record["evidence_manifest"] = reference
        record["evidence_manifest_sha256"] = reference["sha256"]
    integrity = validate_phase14_run_evidence(
        run_dir,
        reference,
        required_output_prefixes=CITY_REQUIRED_EVIDENCE,
    )
    record["evidence_integrity"] = integrity
    return integrity


def _phase15_wave_transfer_acceptance(project: Path, run_dir: Path) -> JSONDict:
    model_path = run_dir / "model.json"
    if not model_path.is_file():
        model_path = project / "model.json"
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
        metadata = model.get("metadata") if isinstance(model, dict) else None
        phase15 = metadata.get("phase15") if isinstance(metadata, dict) else None
        probes = phase15.get("probes") if isinstance(phase15, dict) else None
        coupling_mode = (
            phase15.get("coupling_mode", "immersed_clis")
            if isinstance(phase15, dict)
            else "immersed_clis"
        )
        concrete = probes.get("concrete") if isinstance(probes, dict) else None
        ale = probes.get("ale") if isinstance(probes, dict) else None
        output = phase15.get("output") if isinstance(phase15, dict) else None
        history_output_dt_s = (
            output.get("history_output_dt_s")
            if isinstance(output, dict)
            else None
        )
        if not isinstance(concrete, list):
            raise ValueError("Phase 15 concrete probe metadata is missing")
        element_ids = {
            int(probe["element_id"])
            for probe in concrete
            if isinstance(probe, dict)
            and isinstance(probe.get("element_id"), int)
            and not isinstance(probe.get("element_id"), bool)
            and int(probe["element_id"]) > 0
        }
        if not element_ids:
            raise ValueError("Phase 15 concrete probe element IDs are missing")
        return evaluate_phase15_wave_transfer(
            run_dir,
            element_ids,
            probe_metadata=concrete,
            ale_probe_metadata=ale if isinstance(ale, list) else None,
            history_output_dt_s=history_output_dt_s,
            coupling_mode=str(coupling_mode),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "wave_transfer_verified": False,
            "checks": [
                {
                    "id": "phase15_acceptance_inputs_valid",
                    "ok": False,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
            ],
        }


def _project_blast_configuration(project: Path) -> JSONDict:
    try:
        model = json.loads((project / "model.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    spec = model.get("spec") if isinstance(model, dict) else None
    if not isinstance(spec, dict):
        return {}
    if spec.get("model_type") == "ale_blast_scene":
        geometry = spec.get("geometry") if isinstance(spec.get("geometry"), dict) else {}
        mesh = spec.get("mesh") if isinstance(spec.get("mesh"), dict) else {}
        material = spec.get("material") if isinstance(spec.get("material"), dict) else {}
        analysis = spec.get("analysis_control") if isinstance(spec.get("analysis_control"), dict) else {}
        termination = analysis.get("termination") if isinstance(analysis.get("termination"), dict) else {}
        database = spec.get("database") if isinstance(spec.get("database"), dict) else {}
        return {
            "model_type": "ale_blast_scene",
            "unit_system": spec.get("unit_system", ""),
            "equivalent_mass_kg": [geometry.get("explosive_mass_kg")],
            "blast_positions_m": [geometry.get("explosive_center_m")],
            "blast_targets": ["target_plate.top_surface"],
            "mesh_sizes_m": [mesh.get("size_m")],
            "material_names": [material.get("name")],
            "ale_domain_min_m": geometry.get("domain_min_m"),
            "ale_domain_max_m": geometry.get("domain_max_m"),
            "end_time_s": termination.get("end_time_s"),
            "d3plot_dt_s": database.get("d3plot_dt_s"),
            "nodout_dt_s": database.get("nodout_dt_s"),
            "fsi_dt_s": database.get("fsi_dt_s"),
        }
    return blast_configuration_summary(spec)


def _nonempty_files_with_prefix(run_dir: Path, prefix: str) -> list[JSONDict]:
    matches: list[JSONDict] = []
    for path in sorted(run_dir.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or not path.name.lower().startswith(prefix.lower()):
            continue
        size = path.stat().st_size
        if size <= 0:
            continue
        matches.append({"name": path.name, "path": str(path), "size_bytes": size})
    return matches


def _finish_record(runs_dir: Path, run_dir: Path, record: JSONDict) -> JSONDict:
    record["finished_at_utc"] = _utc_now()
    record["duration_s"] = _duration_seconds(record["started_at_utc"], record["finished_at_utc"])
    _persist_record(runs_dir, run_dir, record)
    return record


def _finish_smoke_record(smokes_dir: Path, smoke_dir: Path, record: JSONDict) -> JSONDict:
    record["finished_at_utc"] = _utc_now()
    record["duration_s"] = _duration_seconds(record["started_at_utc"], record["finished_at_utc"])
    _persist_smoke_record(smokes_dir, smoke_dir, record)
    return record


def _persist_smoke_record(smokes_dir: Path, smoke_dir: Path, record: JSONDict) -> None:
    _write_json_atomic(smoke_dir / "smoke.json", record)
    _write_json_atomic(smokes_dir / "latest.json", record)


def _persist_record(runs_dir: Path, run_dir: Path, record: JSONDict) -> None:
    _write_json_atomic(run_dir / "run.json", record)
    _write_json_atomic(runs_dir / "latest.json", record)


def _read_run_record(path: Path) -> tuple[JSONDict, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    if not isinstance(value, dict):
        return {}, "run record must be a JSON object"
    return value, None


def _write_json_atomic(path: Path, data: JSONDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"run_{stamp}_{uuid.uuid4().hex[:8]}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_seconds(started_at: str, finished_at: str) -> float:
    start = datetime.fromisoformat(started_at)
    finish = datetime.fromisoformat(finished_at)
    return max(0.0, (finish - start).total_seconds())
