"""A small flexible panel and one short lightweight demonstration; no native solver."""
import json
from pathlib import Path
import subprocess
from node_runtime import node_executable

ROOT = Path(__file__).resolve().parents[1]


def test_flexible_panel_fracture_and_short_demo():
    result = subprocess.run([str(node_executable()), str(ROOT / 'web/tests/panel-fracture.runtime.cjs')],
                            cwd=ROOT, capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data['status'] == 'passed' and data['checks'] == 13
    assert data['nonplanarity'] > 1e-4 and data['strong']['detached'] > 0
