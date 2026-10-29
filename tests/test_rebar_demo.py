"""K-rule mapping and small demonstration mechanics; no native/gravity jobs."""
import json
from pathlib import Path
import subprocess
import importlib.util
from node_runtime import node_executable

ROOT=Path(__file__).resolve().parents[1]

def test_retained_k_catalog_is_reproducible_and_stair_layers_are_complete():
    spec=importlib.util.spec_from_file_location('extract_demo_rebar',ROOT/'scripts/build_demo_rebar_catalog.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    actual=module.extract(ROOT/'resources/fixed_building_pressure/three-storey-structural.zip')
    text=(ROOT/'lsprepost_mcp/web/static/blast_rebar_catalog.js').read_text(encoding='utf-8')
    expected=json.loads(text.split('export const K_REBAR_CATALOG=',1)[1].strip().removesuffix(';'))
    assert actual==expected
    assert len(actual['components'])==246
    for member in (c for c in actual['components'] if c['kind']=='stairs'):
        assert len(member['groups']['stair_longitudinal']['layers'])>=2
        layers=member['groups']['stair_transverse']['crossLayers']
        assert len(layers)==2 and all(layer['spacing'] and layer['spacing']>0 for layer in layers)

def run_node(name):
    run=subprocess.run([str(node_executable()),str(ROOT/'web/tests'/name)],cwd=ROOT,capture_output=True,text=True,timeout=30)
    assert run.returncode==0,run.stdout+run.stderr
    return json.loads(run.stdout)

def test_k_rebar_mapping_preserves_concrete_and_source_rules():
    assert run_node('rebar-layout.runtime.cjs')['status']=='passed'

def test_equivalent_steel_transfers_force_yields_and_breaks():
    assert run_node('rebar-bundles.runtime.cjs')['status']=='passed'

def test_steel_feedback_moves_concrete_and_respects_fixed_supports():
    assert run_node('rebar-coupling.runtime.cjs')['status']=='passed'

def test_reinforced_micro_demo_changes_response_and_keeps_old_method():
    assert run_node('rebar-integration.runtime.cjs')['status']=='passed'

def test_rebar_modules_are_available_from_compatibility_static_routes(tmp_path):
    from lsprepost_mcp.web.fixed_building_workspace import FixedBuildingWorkspace
    workspace=FixedBuildingWorkspace(tmp_path)
    try:
        for name in ('blast_rebar_catalog.js','blast_rebar_layout.js','blast_rebar_bundles.js','blast_rebar_coupling.js','blast_rebar_view.js'):
            result=workspace.static_response('/static/'+name)
            assert result is not None and result[0]==200,name
        assert workspace._scene_cpu is None
    finally:
        workspace.close()
