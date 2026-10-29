"""Local simplified mechanics only; no native or full-building engineering jobs."""
from pathlib import Path
import json,subprocess
from node_runtime import node_executable
ROOT=Path(__file__).resolve().parents[1]
def run_case(name):
    result=subprocess.run([str(node_executable()),str(ROOT/'web/tests'/name)],cwd=ROOT,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return json.loads(result.stdout)
def test_local_steel_has_own_geometry_inertia_and_physical_broken_tips():
    assert run_case('local-rebar.runtime.cjs')['status']=='passed'
def test_loaded_regions_refine_conservatively_and_accumulate_compression_damage():
    assert run_case('crush-refinement.runtime.cjs')['status']=='passed'
def test_refined_micro_response_uses_local_steel_and_pressure_damage():
    assert run_case('refined-response.runtime.cjs')['status']=='passed'
def test_spatial_contact_grid_preserves_sweeps_slopes_and_supports():
    assert run_case('contact-grid.runtime.cjs')['status']=='passed'
def test_refinement_modules_have_compatibility_static_routes(tmp_path):
    from lsprepost_mcp.web.fixed_building_workspace import FixedBuildingWorkspace
    workspace=FixedBuildingWorkspace(tmp_path)
    try:
        for name in ('blast_local_rebar.js','blast_local_rebar_view.js','blast_damage_fields.js'):
            response=workspace.static_response('/static/'+name)
            assert response and response[0]==200,name
    finally:
        workspace.close()
