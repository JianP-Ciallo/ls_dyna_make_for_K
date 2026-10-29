"""Small dynamic-fragment collision and stacking fixtures, no native solver."""
import json
from pathlib import Path
import subprocess
from node_runtime import node_executable

ROOT = Path(__file__).resolve().parents[1]


def test_debris_two_way_contact_friction_and_stacking():
    run = subprocess.run([str(node_executable()), str(ROOT / 'web/tests/debris-contact.runtime.cjs')],
                         cwd=ROOT, capture_output=True, text=True, timeout=25)
    assert run.returncode == 0, run.stdout + run.stderr
    result = json.loads(run.stdout)
    assert result['status'] == 'passed' and result['checks'] == 10
    assert result['pile']['settled'] >= 2 and result['fastContacts'] > 0
