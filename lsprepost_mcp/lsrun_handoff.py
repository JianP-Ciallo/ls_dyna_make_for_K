from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from .config import JSONDict
from .locks import ProjectLock
from .lsdyna_runner import (
    MAX_NCPU,
    MEMORY_PATTERN,
    _evaluate_d3hsp,
    _result_mode,
    _result_variant,
)
from .phase15_fsi import evaluate_phase15_wave_transfer
from .run_evidence import (
    seal_phase14_run_evidence,
    validate_phase14_run_evidence,
)


RUN_ID_PATTERN = re.compile(r"run_[A-Za-z0-9_]+")


def prepare_lsrun_handoff(
    project: Path,
    lsrun: Path,
    lsdyna: Path | None,
    *,
    ncpu: int,
    memory: str,
) -> JSONDict:
    project = Path(project).resolve()
    lsrun = Path(lsrun).resolve()
    lsdyna = Path(lsdyna).resolve() if lsdyna is not None else None
    if not project.is_dir():
        raise FileNotFoundError(f"project directory not found: {project}")
    if not lsrun.is_file() or lsrun.suffix.lower() != ".exe":
        raise ValueError("lsrun must be an existing .exe file")
    if lsdyna is not None and (
        not lsdyna.is_file() or lsdyna.suffix.lower() != ".exe"
    ):
        raise ValueError("lsdyna must be an existing .exe file")
    if isinstance(ncpu, bool) or not isinstance(ncpu, int) or not 1 <= ncpu <= MAX_NCPU:
        raise ValueError(f"ncpu must be an integer between 1 and {MAX_NCPU}")
    if not isinstance(memory, str) or not MEMORY_PATTERN.fullmatch(memory.strip()):
        raise ValueError("memory must use LS-DYNA syntax such as 512m or 2g")

    source_model = project / "model.k"
    source_metadata = project / "model.json"
    if not source_model.is_file():
        raise FileNotFoundError(f"model.k not found: {source_model}")
    if not source_metadata.is_file():
        raise FileNotFoundError(f"model.json not found: {source_metadata}")

    with ProjectLock(project.name):
        with ProjectLock(project.name, namespace="lsrun_handoff"):
            runs_dir = project / "solver_runs"
            runs_dir.mkdir(parents=True, exist_ok=True)
            resolved_runs = runs_dir.resolve()
            if resolved_runs.parent != project:
                raise ValueError("solver_runs must remain inside the project")
            run_id = _new_run_id()
            run_dir = resolved_runs / run_id
            run_dir.mkdir(exist_ok=False)
            if run_dir.resolve().parent != resolved_runs:
                raise ValueError("LS-Run handoff path escaped solver_runs")

            snapshot = run_dir / "model.k"
            metadata_snapshot = run_dir / "model.json"
            _copy_atomic(source_model, snapshot)
            _copy_atomic(source_metadata, metadata_snapshot)
            record: JSONDict = {
                "ok": False,
                "operation": "lsrun_handoff",
                "status": "handoff_prepared",
                "run_id": run_id,
                "project_name": project.name,
                "project_dir": str(project),
                "run_dir": str(run_dir),
                "input": str(snapshot),
                "input_sha256": _sha256(snapshot),
                "model_json_sha256": _sha256(metadata_snapshot),
                "lsrun_exe": str(lsrun),
                "lsdyna_exe": str(lsdyna) if lsdyna is not None else "",
                "options": {
                    "ncpu": ncpu,
                    "memory": memory.strip().lower(),
                },
                "command_preview": _command_preview(
                    snapshot,
                    lsdyna,
                    ncpu=ncpu,
                    memory=memory.strip().lower(),
                ),
                "prepared_at": _utc_now(),
            }
            _write_record(run_dir, resolved_runs, record)
            return record


def launch_lsrun_handoff(project: Path, handoff: JSONDict) -> JSONDict:
    project = Path(project).resolve()
    run_dir, record = _validated_handoff_record(project, handoff)
    lsrun = Path(str(record.get("lsrun_exe", ""))).resolve()
    snapshot = Path(str(record.get("input", ""))).resolve()
    if not lsrun.is_file() or lsrun.suffix.lower() != ".exe":
        raise ValueError("recorded LS-Run executable is unavailable")
    _verify_input_hashes(run_dir, record)

    proc = subprocess.Popen(
        [str(lsrun), str(snapshot)],
        cwd=str(run_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    record.update(
        {
            "status": "handoff_opened",
            "lsrun_pid": int(proc.pid),
            "handoff_opened_at": _utc_now(),
            "submission_state": "not_observed",
            "note": (
                "LS-Run was opened with the immutable input snapshot. "
                "Its PID does not prove that LS-DYNA was submitted."
            ),
        }
    )
    with ProjectLock(project.name, namespace="lsrun_handoff"):
        _write_record(run_dir, run_dir.parent, record)
    return record


def recover_lsrun_result(project: Path, run_id: str) -> JSONDict:
    project = Path(project).resolve()
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id is invalid")
    runs_dir = (project / "solver_runs").resolve()
    if runs_dir.parent != project or not runs_dir.is_dir():
        raise FileNotFoundError("project solver_runs directory not found")
    run_dir = (runs_dir / run_id).resolve()
    if run_dir.parent != runs_dir or not run_dir.is_dir():
        raise FileNotFoundError(f"LS-Run handoff not found: {run_id}")

    with ProjectLock(project.name, namespace="lsrun_handoff"):
        record_path = run_dir / "run.json"
        record = _read_json_object(record_path)
        mismatched_inputs = _input_hash_mismatches(run_dir, record)
        if mismatched_inputs:
            record.update(
                {
                    "ok": False,
                    "status": "invalid_evidence",
                    "mismatched_inputs": mismatched_inputs,
                    "recovered_at": _utc_now(),
                }
            )
            _write_record(run_dir, runs_dir, record)
            return record

        model = _read_json_object(run_dir / "model.json")
        required_outputs = _required_outputs(model)
        missing_outputs = [
            prefix
            for prefix in required_outputs
            if _first_nonempty_output(run_dir, prefix) is None
        ]
        if missing_outputs:
            record.update(
                {
                    "ok": False,
                    "status": "incomplete_outputs",
                    "missing_required_outputs": missing_outputs,
                    "required_outputs": list(required_outputs),
                    "recovered_at": _utc_now(),
                }
            )
            _write_record(run_dir, runs_dir, record)
            return record

        mode = _result_mode(run_dir)
        variant = _result_variant(run_dir)
        solver_evaluation = _evaluate_d3hsp(run_dir, mode, variant)
        wave_evaluation: JSONDict | None = None
        wave_ok = True
        if variant == "phase15_axisymmetric_blast":
            wave_evaluation = _evaluate_phase15_snapshot(run_dir, model)
            wave_ok = bool(wave_evaluation.get("wave_transfer_verified"))
        record.update(
            {
                "result_mode": mode,
                "result_variant": variant,
                "solver_evaluation": solver_evaluation,
                "wave_transfer_acceptance": wave_evaluation,
                "required_outputs": list(required_outputs),
                "recovered_at": _utc_now(),
            }
        )
        result_ok = bool(solver_evaluation.get("ok")) and wave_ok
        record["ok"] = result_ok
        record["status"] = "completed" if result_ok else "rejected"

        evidence = seal_phase14_run_evidence(
            run_dir,
            required_output_prefixes=required_outputs,
        )
        record["evidence_manifest"] = evidence
        record["evidence_manifest_sha256"] = evidence["sha256"]
        evidence_validation = validate_phase14_run_evidence(
            run_dir,
            evidence,
            required_output_prefixes=required_outputs,
        )
        record["evidence_validation"] = evidence_validation
        if not evidence_validation.get("ok"):
            record["ok"] = False
            record["status"] = "invalid_evidence"
        _write_record(run_dir, runs_dir, record)
        return record


def _evaluate_phase15_snapshot(run_dir: Path, model: JSONDict) -> JSONDict:
    metadata = model.get("metadata")
    phase15 = metadata.get("phase15") if isinstance(metadata, dict) else None
    probes = phase15.get("probes") if isinstance(phase15, dict) else None
    concrete = probes.get("concrete") if isinstance(probes, dict) else None
    ale = probes.get("ale") if isinstance(probes, dict) else None
    output = phase15.get("output") if isinstance(phase15, dict) else None
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
        history_output_dt_s=(
            output.get("history_output_dt_s")
            if isinstance(output, dict)
            else None
        ),
        coupling_mode=str(
            phase15.get("coupling_mode", "immersed_clis")
            if isinstance(phase15, dict)
            else "immersed_clis"
        ),
    )


def _required_outputs(model: JSONDict) -> tuple[str, ...]:
    spec = model.get("spec")
    if isinstance(spec, dict) and spec.get("model_type") == "phase15_axisymmetric_blast":
        metadata = model.get("metadata")
        phase15 = metadata.get("phase15") if isinstance(metadata, dict) else None
        mode = (
            phase15.get("coupling_mode", "immersed_clis")
            if isinstance(phase15, dict)
            else "immersed_clis"
        )
        common = ("d3hsp", "d3plot", "elout", "nodout")
        return (*common, "dbfsi") if mode == "immersed_clis" else common
    return ("d3hsp", "d3plot")


def _validated_handoff_record(
    project: Path,
    handoff: JSONDict,
) -> tuple[Path, JSONDict]:
    if not isinstance(handoff, dict):
        raise TypeError("handoff must be an object")
    run_id = handoff.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("handoff run_id is invalid")
    runs_dir = (project / "solver_runs").resolve()
    if runs_dir.parent != project:
        raise ValueError("solver_runs must remain inside the project")
    run_dir = (runs_dir / run_id).resolve()
    if run_dir.parent != runs_dir or not run_dir.is_dir():
        raise ValueError("handoff run directory is invalid")
    record = _read_json_object(run_dir / "run.json")
    if record.get("run_id") != run_id:
        raise ValueError("handoff run identity does not match run.json")
    for field in ("input_sha256", "model_json_sha256", "lsrun_exe"):
        if handoff.get(field) != record.get(field):
            raise ValueError(f"handoff field does not match run.json: {field}")
    return run_dir, record


def _verify_input_hashes(run_dir: Path, record: JSONDict) -> None:
    mismatches = _input_hash_mismatches(run_dir, record)
    if mismatches:
        raise ValueError(
            "LS-Run handoff input snapshot changed: " + ", ".join(mismatches)
        )


def _input_hash_mismatches(run_dir: Path, record: JSONDict) -> list[str]:
    mismatches: list[str] = []
    for name, field in (
        ("model.k", "input_sha256"),
        ("model.json", "model_json_sha256"),
    ):
        path = run_dir / name
        expected = record.get(field)
        if (
            not path.is_file()
            or not isinstance(expected, str)
            or _sha256(path) != expected
        ):
            mismatches.append(name)
    return mismatches


def _first_nonempty_output(run_dir: Path, prefix: str) -> Path | None:
    candidates = sorted(
        (
            path
            for path in run_dir.iterdir()
            if path.is_file()
            and path.name.lower().startswith(prefix)
            and path.stat().st_size > 0
        ),
        key=lambda path: path.name.lower(),
    )
    return candidates[0] if candidates else None


def _write_record(run_dir: Path, runs_dir: Path, record: JSONDict) -> None:
    _write_json_atomic(run_dir / "run.json", record)
    _write_json_atomic(runs_dir / "latest.json", record)


def _copy_atomic(source: Path, target: Path) -> None:
    temp = target.with_name(f".{target.name}.tmp_{uuid.uuid4().hex}")
    try:
        shutil.copy2(source, temp)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def _write_json_atomic(path: Path, payload: JSONDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp_{uuid.uuid4().hex}")
    try:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _read_json_object(path: Path) -> JSONDict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object expected: {path}")
    return value


def _command_preview(
    model: Path,
    lsdyna: Path | None,
    *,
    ncpu: int,
    memory: str,
) -> str:
    solver = str(lsdyna) if lsdyna is not None else "<LS_DYNA_SOLVER_EXE>"
    return f'"{solver}" i="{model}" ncpu={ncpu} memory={memory}'


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"run_{stamp}_{uuid.uuid4().hex[:8]}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
