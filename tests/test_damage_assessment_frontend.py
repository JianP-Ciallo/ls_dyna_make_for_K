"""Behavioral contracts for the real workbench assessment controller."""
from pathlib import Path
import subprocess

import pytest
from node_runtime import node_executable

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("case", [
    "open", "unavailable", "no-project", "dirty", "stale", "latest",
    "success", "blocked", "no-source", "unregistered", "bad-snapshot",
    "restore", "corrupt-cache", "latest-bad-snapshot", "bad-artifact",
])
def test_damage_panel_uses_controlled_identity_and_honest_result_states(case: str) -> None:
    result = subprocess.run(
        [str(node_executable()), str(ROOT / "web/tests/damage-assessment-panel.runtime.cjs"), case],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
