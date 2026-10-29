"""Bounded powder fixtures; no full-building or native analysis."""
from pathlib import Path
import json
import subprocess
from node_runtime import node_executable

ROOT = Path(__file__).resolve().parents[1]
def case(name):
    result = subprocess.run([str(node_executable()), str(ROOT / 'web/tests' / name)], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)

def test_powder_trigger_lifecycle_budget_and_rewind():
    assert case('powder.runtime.cjs')['status'] == 'passed'

def test_three_body_powder_releases_hosts_and_keeps_steel_response():
    assert case('powder-integration.runtime.cjs')['status'] == 'passed'

def test_retired_powder_support_never_reenters_sleeping_contact():
    assert case('powder-retirement.runtime.cjs')['status'] == 'passed'

def test_powder_history_requires_matching_emissions_and_mass():
    assert case('powder-history.runtime.cjs')['status'] == 'passed'

def test_powder_assets_have_compatibility_routes(tmp_path):
    from lsprepost_mcp.web.fixed_building_workspace import FixedBuildingWorkspace
    workspace = FixedBuildingWorkspace(tmp_path)
    try:
        for name in ('blast_powder.js', 'blast_powder_view.js'):
            response = workspace.static_response('/static/' + name)
            assert response and response[0] == 200, name
    finally:
        workspace.close()
