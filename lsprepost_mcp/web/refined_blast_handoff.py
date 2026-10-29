"""Narrow, path-only external handoffs for refined-blast action snapshots.

The refined-blast HTTP adapter never receives executables or launch options from
the browser.  This module owns the configured-executable and process-launch
boundary so its callers can pass only server-materialized snapshot paths.
"""

from __future__ import annotations

from pathlib import Path

from lsprepost_mcp.config import JSONDict, configured_lspp_exe
from lsprepost_mcp.lsdyna_runner import execute_lsdyna_run
from lsprepost_mcp.lspp.launcher import doctor_lsprepost_exe, launch_lsprepost_command
from lsprepost_mcp.web.config_api import configured_lsdyna_exe, doctor_named_exe


def configured_action_doctor(action: str) -> bool:
    """Return whether the configured executable for one approved action is usable."""

    if action == "open_lsprepost":
        executable, _source, configured = configured_lspp_exe()
        return configured and doctor_lsprepost_exe(executable).ok
    if action == "launch_lsdyna":
        solver = configured_lsdyna_exe()
        return solver is not None and doctor_named_exe(
            solver, ("lsdyna", "ls-dyna", "mppdyna"), require_name=False
        ).ok
    return False


def open_lsprepost_snapshot(model: Path) -> JSONDict:
    """Open exactly one trusted ``main.k`` snapshot with configured LS-PrePost."""

    model = Path(model).resolve()
    if model.name != "main.k" or not model.is_file():
        raise ValueError("LS-PrePost handoff requires a materialized main.k snapshot")
    executable, _source, configured = configured_lspp_exe()
    if not configured or not doctor_lsprepost_exe(executable).ok:
        raise ValueError("LS-PrePost is not configured")
    record = launch_lsprepost_command(
        model.parent,
        [str(executable), f"k={model}"],
        "keyword_preview",
        allow_multiple=False,
        extra_record={"refined_blast_snapshot": str(model)},
    )
    return {"started": record.get("status") == "started", "record": record}


def launch_lsdyna_snapshot(snapshot: Path, model: Path) -> JSONDict:
    """Solve one trusted snapshot using server-owned conservative defaults only."""

    snapshot = Path(snapshot).resolve()
    model = Path(model).resolve()
    if model != snapshot / "main.k" or not model.is_file() or not (snapshot / "model.k").is_file():
        raise ValueError("LS-DYNA handoff requires a closed main.k/model.k snapshot")
    solver = configured_lsdyna_exe()
    if solver is None or not doctor_named_exe(
        solver, ("lsdyna", "ls-dyna", "mppdyna"), require_name=False
    ).ok:
        raise ValueError("LS-DYNA is not configured")
    record = execute_lsdyna_run(
        snapshot,
        solver,
        ncpu=1,
        memory="20m",
        timeout_s=600.0,
        static_validation={
            "refined_blast_snapshot": str(model),
            "solver_ready": False,
            "requires_project_review": True,
        },
        input_closure={
            path.relative_to(snapshot).as_posix(): path
            for path in snapshot.rglob("*")
            if path.is_file()
        },
    )
    return {
        "started": record.get("status") not in {"launch_failed", "starting"},
        "record": record,
    }
