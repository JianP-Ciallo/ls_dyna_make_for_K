from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).parents[1] / "scripts" / "generate_phase18_solver_blast_models.py"
IMPORT_SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "validate_phase18_solver_blast_imports.py"
)
SOLVE_SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "run_phase18_solver_blast_validation.py"
)
SUPPORTED_IDS = (
    "commercial_supermarket_detailed_building",
    "residential_community_detailed_building",
    "subway_entrance_detailed_building",
)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=SCRIPT.parents[1],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_cli_dry_run_lists_exact_three_models(tmp_path: Path) -> None:
    result = _run("--output-root", str(tmp_path / "models"), "--dry-run")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [row["resource_id"] for row in payload["models"]] == list(
        SUPPORTED_IDS
    )
    assert all(row["charge_mass_kg"] == 2.0 for row in payload["models"])
    assert all(
        row["charge_position_m"] == [-2.0, 1.5, 4.0]
        for row in payload["models"]
    )
    assert all(row["termination_time_s"] == 5.0e-5 for row in payload["models"])
    assert payload["solver_config"]["schema_version"] == "phase18.solver_blast.config@4"
    assert payload["solver_config"]["air_cell_size_m"] == 0.225
    assert payload["solver_config"]["near_field_cell_size_m"] == 0.15
    assert payload["solver_config"]["ground_cell_size_m"] == 0.25
    assert payload["solver_config"]["air_margins_m"] == [3.0, 3.0, 3.0, 3.0, 3.0]
    assert payload["solver_config"]["coupling_buffer_layers"] == 2
    assert payload["solver_config"]["material_profile"] == "verification_reference"
    assert payload["physical_size_target_mib"] == [45.0, 70.0]
    assert payload["dry_run"] is True
    assert not (tmp_path / "models").exists()


def test_cli_accepts_layered_air_contract_controls(tmp_path: Path) -> None:
    result = _run(
        "--output-root",
        str(tmp_path / "models"),
        "--air-margins",
        "2",
        "4",
        "3",
        "5",
        "6",
        "--near-field-cell-size-m",
        "0.1",
        "--coupling-buffer-layers",
        "5",
        "--material-profile",
        "project_calibrated",
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)["solver_config"]
    assert config["air_margins_m"] == [2.0, 4.0, 3.0, 5.0, 6.0]
    assert config["near_field_cell_size_m"] == 0.1
    assert config["coupling_buffer_layers"] == 5
    assert config["material_profile"] == "project_calibrated"


def test_cli_rejects_ambiguous_legacy_air_margin_flag(tmp_path: Path) -> None:
    result = _run(
        "--output-root",
        str(tmp_path / "models"),
        "--air-margin",
        "3",
        "3",
        "3",
        "--dry-run",
    )

    assert result.returncode != 0
    assert "unrecognized arguments" in result.stderr


def test_cli_refuses_nonempty_output_before_compilation(tmp_path: Path) -> None:
    output = tmp_path / "models"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("do not overwrite", encoding="utf-8")

    result = _run("--output-root", str(output))

    assert result.returncode != 0
    assert "output root must be empty" in result.stderr
    assert marker.read_text(encoding="utf-8") == "do not overwrite"


def test_cli_does_not_accept_an_arbitrary_solver_path(tmp_path: Path) -> None:
    result = _run(
        "--output-root",
        str(tmp_path / "models"),
        "--solver-exe",
        str(tmp_path / "untrusted.exe"),
        "--dry-run",
    )

    assert result.returncode != 0
    assert "unrecognized arguments" in result.stderr


def test_import_cli_dry_run_lists_exact_models_without_launching(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(IMPORT_SCRIPT),
            "--output-root",
            str(tmp_path / "models"),
            "--dry-run",
        ],
        cwd=SCRIPT.parents[1],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "dry_run": True,
        "folders": [
            "01_commercial_supermarket",
            "02_residential_community",
            "03_subway_entrance",
        ],
        "output_root": str((tmp_path / "models").resolve()),
    }


def test_solver_cli_dry_run_is_serial_and_does_not_accept_solver_path(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SOLVE_SCRIPT),
            "--output-root",
            str(tmp_path / "models"),
            "--dry-run",
        ],
        cwd=SCRIPT.parents[1],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["folders"] == [
        "01_commercial_supermarket",
        "02_residential_community",
        "03_subway_entrance",
    ]
    assert payload["parallel_jobs"] == 1
    assert payload["acceptance_mode"] == "configured_short_solve_no_error"
    assert payload["preflight"] == "mcheck=y"
    assert payload["termination_time_source"] == "model.solver_config.termination_time_s"
    assert "termination_time_s" not in payload

    rejected = subprocess.run(
        [
            sys.executable,
            str(SOLVE_SCRIPT),
            "--output-root",
            str(tmp_path / "models"),
            "--solver-exe",
            str(tmp_path / "untrusted.exe"),
            "--dry-run",
        ],
        cwd=SCRIPT.parents[1],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert rejected.returncode != 0
    assert "unrecognized arguments" in rejected.stderr


def test_solver_validation_runs_mcheck_before_short_solve(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spec = importlib.util.spec_from_file_location(
        "phase18_solver_validation_script",
        SOLVE_SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    root = tmp_path / "models"
    folder = "01_commercial_supermarket"
    model_dir = root / folder
    model_dir.mkdir(parents=True)
    (model_dir / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")
    (model_dir / "model.json").write_text(
        json.dumps({"solver_config": {"termination_time_s": 5.0e-5}}),
        encoding="utf-8",
    )
    (model_dir / "validation.json").write_text(
        json.dumps({"ok": True, "findings": []}),
        encoding="utf-8",
    )
    solver = tmp_path / "lsdyna.exe"
    solver.write_bytes(b"solver")
    events: list[str] = []
    smoke = {
        "ok": True,
        "status": "completed",
        "returncode": 0,
        "smoke_id": "smoke_1",
        "smoke_dir": str(model_dir / "solver_smokes" / "smoke_1"),
    }
    run_dir = model_dir / "solver_runs" / "run_1"

    monkeypatch.setattr(module, "configured_lsdyna_exe", lambda: solver)
    monkeypatch.setattr(
        module,
        "doctor_named_exe",
        lambda *_args: SimpleNamespace(ok=True),
    )

    def fake_mcheck(*_args, **_kwargs):
        events.append("mcheck")
        return smoke

    def fake_solve(*_args, **_kwargs):
        events.append("solve")
        run_dir.mkdir(parents=True)
        return {"run_dir": str(run_dir), "run_id": "run_1"}

    def fake_evaluate(*_args, **_kwargs):
        events.append("evaluate")
        return object()

    def fake_report(
        selected_folder,
        mcheck,
        run,
        _report,
        requested_termination_time_s,
    ):
        assert selected_folder == folder
        assert mcheck is smoke
        assert run["run_id"] == "run_1"
        assert requested_termination_time_s == 5.0e-5
        return {
            "folder": folder,
            "ok": True,
            "run_id": "run_1",
            "runner_duration_s": 1.0,
            "report": {"findings": []},
        }

    monkeypatch.setattr(module, "execute_lsdyna_initialization_smoke", fake_mcheck)
    monkeypatch.setattr(module, "execute_lsdyna_run", fake_solve)
    monkeypatch.setattr(module, "evaluate_solver_blast_run", fake_evaluate)
    monkeypatch.setattr(module, "_report_record", fake_report)

    module.run_models(root, (folder,))

    assert events == ["mcheck", "solve", "evaluate"]
