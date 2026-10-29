"""Solid balcony parapets must use the same progressive damage as other panels."""
import json
from pathlib import Path
import subprocess
from node_runtime import node_executable

ROOT = Path(__file__).resolve().parents[1]


def test_solid_parapet_damage_and_slender_handrail_exclusion():
    run = subprocess.run([str(node_executable()), str(ROOT / 'web/tests/rail-panel-damage.runtime.cjs')],
                         cwd=ROOT, capture_output=True, text=True, timeout=25)
    assert run.returncode == 0, run.stdout + run.stderr
    result = json.loads(run.stdout)
    assert result['status'] == 'passed' and result['checks'] == 8
    assert result['eligibleRails'] == 36 and result['activeRails'] > 0
