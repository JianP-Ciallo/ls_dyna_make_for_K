from __future__ import annotations

import json
import subprocess
from pathlib import Path

from node_runtime import node_executable


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "lsprepost_mcp" / "web" / "static" / "refined_blast_persistence.js"
RUNTIME = ROOT / "web" / "tests" / "refined-blast-persistence.runtime.cjs"


def run_case(case: str) -> dict[str, object]:
    result = subprocess.run(
        [str(node_executable()), str(RUNTIME), str(MODULE), case],
        cwd=str(ROOT), text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_latest_project_identity_is_validated_before_restore() -> None:
    assert run_case("project-id") == {"valid": "refined-blast-42", "rejected": None}


def test_uncreated_session_draft_round_trips_and_malformed_data_is_ignored() -> None:
    result = run_case("session-draft")
    assert result["restored"]["asset_id"] == "subway_entrance_detailed_building"
    assert result["restored"]["building"] == {"structural_system": "rc_box"}
    assert result["malformed"] is None


def test_new_scenario_clears_recovery_and_storage_failures_are_non_blocking() -> None:
    assert run_case("clear-and-unavailable") == {
        "project": None, "draft": None, "safe_project": None, "safe_draft": None,
    }
