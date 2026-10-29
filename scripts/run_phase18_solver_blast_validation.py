from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lsprepost_mcp.lsdyna_runner import (
    execute_lsdyna_initialization_smoke,
    execute_lsdyna_run,
)
from lsprepost_mcp.refined_building.solver_blast import evaluate_solver_blast_run
from lsprepost_mcp.web.config_api import configured_lsdyna_exe, doctor_named_exe


FOLDERS = (
    "01_commercial_supermarket",
    "02_residential_community",
    "03_subway_entrance",
)
ACCEPTANCE_MODE = "configured_short_solve_no_error"
NCPU = 4
MEMORY = "2g"
TIMEOUT_S = 7200.0
MCHECK_TIMEOUT_S = 600.0


def _write_json_atomic(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _validated_model_dir(root: Path, folder: str) -> tuple[Path, float]:
    model_dir = root / folder
    if model_dir.is_symlink() or not model_dir.is_dir():
        raise ValueError(f"model directory must be a real directory: {folder}")
    model_dir = model_dir.resolve()
    if model_dir.parent != root:
        raise ValueError(f"model directory escaped output root: {folder}")
    for filename in ("model.k", "model.json", "validation.json"):
        path = model_dir / filename
        if path.is_symlink() or not path.is_file() or path.resolve().parent != model_dir:
            raise ValueError(f"required model file is invalid: {folder}/{filename}")
    model = json.loads((model_dir / "model.json").read_text(encoding="utf-8"))
    config = model.get("solver_config") if isinstance(model, dict) else None
    termination = config.get("termination_time_s") if isinstance(config, dict) else None
    if isinstance(termination, bool) or not isinstance(termination, (int, float)):
        raise ValueError(f"model has no numeric configured short-solve time: {folder}")
    configured_termination = float(termination)
    if not math.isfinite(configured_termination) or configured_termination <= 0.0:
        raise ValueError(f"model short-solve time must be positive and finite: {folder}")
    return model_dir, configured_termination


def _report_record(
    folder: str,
    mcheck: dict[str, Any],
    run: dict[str, Any],
    report: object,
    requested_termination_time_s: float,
) -> dict[str, object]:
    report_value = asdict(report)
    report_value["findings"] = [asdict(row) for row in report.findings]
    mcheck_ok = bool(
        mcheck.get("ok")
        and mcheck.get("status") == "completed"
        and mcheck.get("returncode") == 0
    )
    same_input = bool(
        mcheck.get("input_sha256")
        and mcheck.get("input_sha256") == run.get("input_sha256")
    )
    mcheck_solver = mcheck.get("solver")
    run_solver = run.get("solver")
    same_solver = bool(
        isinstance(mcheck_solver, dict)
        and isinstance(run_solver, dict)
        and mcheck_solver.get("sha256")
        and mcheck_solver.get("sha256") == run_solver.get("sha256")
    )
    run_ok = bool(
        mcheck_ok
        and same_input
        and same_solver
        and run.get("status") == "completed"
        and run.get("returncode") == 0
        and report.ok
    )
    return {
        "schema_version": "phase18.solver_blast.r12_acceptance@3",
        "acceptance_mode": ACCEPTANCE_MODE,
        "requested_termination_time_s": requested_termination_time_s,
        "folder": folder,
        "mcheck": {
            "ok": mcheck_ok,
            "status": mcheck.get("status"),
            "returncode": mcheck.get("returncode"),
            "smoke_id": mcheck.get("smoke_id"),
            "smoke_dir": mcheck.get("smoke_dir"),
            "duration_s": mcheck.get("duration_s"),
            "input_sha256": mcheck.get("input_sha256"),
            "solver": mcheck_solver,
            "resources": mcheck.get("resources"),
            "scope": mcheck.get("scope"),
            "same_input_as_short_solve": same_input,
            "same_solver_as_short_solve": same_solver,
        },
        "run_id": run.get("run_id"),
        "run_dir": run.get("run_dir"),
        "solver": run.get("solver"),
        "resources": run.get("resources"),
        "runner_status": run.get("status"),
        "runner_returncode": run.get("returncode"),
        "runner_duration_s": run.get("duration_s"),
        "report": report_value,
        "ok": run_ok,
        "engineering_validated": False,
        "solver_ready": False,
        "requires_project_review": True,
    }


def _update_summary(root: Path, row: dict[str, object]) -> dict[str, object]:
    path = root / "solver_blast_r12_summary.json"
    existing: dict[str, object] = {}
    if path.is_file() and not path.is_symlink():
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            existing = value
    rows_by_folder = {
        str(item.get("folder")): item
        for item in existing.get("models", [])
        if isinstance(item, dict) and isinstance(item.get("folder"), str)
    }
    rows_by_folder[str(row["folder"])] = row
    rows = [rows_by_folder[folder] for folder in FOLDERS if folder in rows_by_folder]
    summary: dict[str, object] = {
        "schema_version": "phase18.solver_blast.r12_acceptance_summary@3",
        "acceptance_mode": ACCEPTANCE_MODE,
        "output_root": str(root),
        "models": rows,
        "all_three_present": len(rows) == len(FOLDERS),
        "all_three_ok": len(rows) == len(FOLDERS) and all(bool(item.get("ok")) for item in rows),
        "engineering_validated": False,
        "solver_ready": False,
        "requires_project_review": True,
    }
    _write_json_atomic(path, summary)
    return summary


def run_models(output_root: Path, folders: tuple[str, ...]) -> dict[str, object]:
    root = Path(output_root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("output root must be an existing real directory")
    root = root.resolve()
    solver = configured_lsdyna_exe()
    if solver is None:
        raise FileNotFoundError("LS-DYNA is not configured")
    solver = solver.resolve()
    doctor = doctor_named_exe(solver, ("lsdyna",), True)
    if not doctor.ok:
        raise FileNotFoundError("configured LS-DYNA executable failed doctor checks")

    latest: dict[str, object] = {}
    for folder in folders:
        model_dir, requested_termination_time_s = _validated_model_dir(root, folder)
        static_validation = json.loads(
            (model_dir / "validation.json").read_text(encoding="utf-8")
        )
        print(
            json.dumps(
                {
                    "event": "starting",
                    "folder": folder,
                    "acceptance_mode": ACCEPTANCE_MODE,
                    "requested_termination_time_s": requested_termination_time_s,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        mcheck = execute_lsdyna_initialization_smoke(
            model_dir,
            solver,
            ncpu=NCPU,
            memory=MEMORY,
            timeout_s=MCHECK_TIMEOUT_S,
            static_validation=static_validation,
        )
        if not bool(
            mcheck.get("ok")
            and mcheck.get("status") == "completed"
            and mcheck.get("returncode") == 0
        ):
            failed_row = {
                "schema_version": "phase18.solver_blast.r12_acceptance@3",
                "acceptance_mode": ACCEPTANCE_MODE,
                "requested_termination_time_s": requested_termination_time_s,
                "folder": folder,
                "mcheck": mcheck,
                "ok": False,
                "engineering_validated": False,
                "solver_ready": False,
                "requires_project_review": True,
            }
            _update_summary(root, failed_row)
            raise RuntimeError(f"R12 mcheck failed for {folder}")
        run = execute_lsdyna_run(
            model_dir,
            solver,
            ncpu=NCPU,
            memory=MEMORY,
            timeout_s=TIMEOUT_S,
            static_validation=static_validation,
        )
        run_dir = Path(str(run["run_dir"])).resolve()
        if run_dir.parent != (model_dir / "solver_runs").resolve():
            raise ValueError("solver run escaped the model solver_runs directory")
        report = evaluate_solver_blast_run(model_dir, run_dir)
        row = _report_record(
            folder,
            mcheck,
            run,
            report,
            requested_termination_time_s,
        )
        _write_json_atomic(run_dir / "solver_blast_acceptance.json", row)
        latest = _update_summary(root, row)
        print(
            json.dumps(
                {
                    "event": "finished",
                    "folder": folder,
                    "ok": row["ok"],
                    "run_id": row["run_id"],
                    "duration_s": row["runner_duration_s"],
                    "findings": row["report"]["findings"],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        if not row["ok"]:
            raise RuntimeError(f"R12 validation failed for {folder}")
    return latest


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description=(
            "Run serial configured-duration R12 short solves for the three Phase 18 "
            "solver-blast models and fail on solver errors."
        )
    )
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--folder", choices=FOLDERS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    folders = (args.folder,) if args.folder else FOLDERS
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "folders": list(folders),
                    "output_root": str(args.output_root.resolve()),
                    "parallel_jobs": 1,
                    "acceptance_mode": ACCEPTANCE_MODE,
                    "preflight": "mcheck=y",
                    "termination_time_source": "model.solver_config.termination_time_s",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    summary = run_models(args.output_root, folders)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
