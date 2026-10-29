"""Default CPU navigation must use the lightweight demo without native preparation."""
from pathlib import Path

from lsprepost_mcp.web.fixed_building_workspace import FixedBuildingWorkspace

STATIC = Path(__file__).resolve().parents[1] / 'lsprepost_mcp/web/static'


def test_default_cpu_route_uses_integrated_demo_and_preserves_engineering_page(tmp_path):
    workspace = FixedBuildingWorkspace(tmp_path)
    try:
        for route in ('/cpu-blast', '/cpu-blast/'):
            code, _, raw = workspace.static_response(route)
            assert code == 200
            assert b'data-cpu-workbench' in raw
            assert b'/cpu_blast.js' in raw
            assert b'/scene_blast.js' not in raw
        code, _, old = workspace.static_response('/cpu-blast', legacy=True)
        assert code == 200 and b'/scene_blast.js' in old
        for name in ('cpu_blast.css', 'cpu_blast.js', 'blast_demo.js', 'blast_demo_cache.js', 'blast_original_scenes.js', 'blast_demo_presentation.js'):
            assert workspace.static_response('/static/' + name)[0] == 200
        assert workspace._scene_cpu is None
        assert not list(tmp_path.rglob('job.json'))
    finally:
        workspace.close()


def test_workbench_session_preserves_building_identity():
    import subprocess
    from node_runtime import node_executable
    script = """
const assert=require('node:assert/strict'),S=require('./lsprepost_mcp/web/static/workbench_session.js');
assert.equal(S.canonicalUrl('blast','/cpu-blast?building=city_street&source=city_street&run_id=old'),'/cpu-blast?building=city_street&source=city_street&run_id=old');
const values=new Map(),store=S.createStore({getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)});
for(const id of ['subway_entrance','city_street'])store.write('blast',{identity:'demo:'+id,url:'/cpu-blast?building='+id,revision:'demo@1',snapshot:{fields:[id]}});
assert.equal(store.read('blast','demo:subway_entrance').url,'/cpu-blast?building=subway_entrance');
assert.equal(store.read('blast','demo:city_street').snapshot.fields[0],'city_street');
"""
    result = subprocess.run([str(node_executable()), '-e', script], cwd=STATIC.parents[2], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
