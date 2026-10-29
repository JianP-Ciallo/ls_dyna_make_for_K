"""Only five short JS demos and small analytical contact/continuity fixtures."""
import json
from pathlib import Path
import subprocess
from node_runtime import node_executable

ROOT = Path(__file__).resolve().parents[1]


def test_scene_damage_supports_and_contact():
    run = subprocess.run([str(node_executable()), str(ROOT / 'web/tests/scene-physics.runtime.cjs')],
                         cwd=ROOT, capture_output=True, text=True, timeout=55)
    assert run.returncode == 0, run.stdout + run.stderr
    result = json.loads(run.stdout)
    assert result['status'] == 'passed' and len(result['scenes']) == 5
    assert all(row['cracks'] > 0 and row['detached'] > 0 for row in result['scenes'])
