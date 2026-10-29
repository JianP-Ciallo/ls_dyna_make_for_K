"""Scene framing and demo configurations only; no long model computation."""
import json
from pathlib import Path
import subprocess
from node_runtime import node_executable

ROOT = Path(__file__).resolve().parents[1]


def test_scene_targets_framing_and_input_preservation():
    run = subprocess.run([str(node_executable()), str(ROOT / 'web/tests/scene-presentation.runtime.cjs')],
                         cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stdout + run.stderr
    result = json.loads(run.stdout)
    assert result['status'] == 'passed' and len(result['scenes']) == 5
