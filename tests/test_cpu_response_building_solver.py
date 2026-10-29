"""Native three-storey MICRO fixture only. No actual building solver is run."""
import math
import numpy as np
import pytest
from test_cpu_response_building_mapping import three_storey_fixture


def micro_case():
    from lsprepost_mcp.architecture.cpu_response.building_mapping import prepare_reference
    a,s=three_storey_fixture();c=prepare_reference(a,s,target_component_id='wall',mesh_size_m=1,column_segments=2)
    c['budget']['wall_s']=30;c['analysis']['duration_s']=.015;c['loads']['curve_si'][-1][0]=.015
    return c


def test_micro_three_storey_static_native_steel_force_moment_and_modes():
    import openseespy.opensees as ops
    from lsprepost_mcp.architecture.cpu_response.building_solver import build_reference,read_reference_sample
    from lsprepost_mcp.architecture.cpu_response.column import configure_static
    c=micro_case();model=build_reference(ops,c)
    try:
        masters={v[0] for v in model['mass_links']};slaves={v[1] for v in model['mass_links']}
        assert not masters&slaves
        ops.timeSeries('Linear',1);ops.pattern('Plain',1,1)
        for tag,f in enumerate(c['nodal_load_per_pa'],1):ops.load(tag,*[v*1000 for v in f])
        configure_static(ops);assert ops.analyze(1)==0
        sample=read_reference_sample(ops,model,1,native_check=True)
        reactions=np.array([ops.nodeReaction(i+1) for i in c['fixed_nodes']]);points=np.array(c['nodes'])[c['fixed_nodes']]
        np.testing.assert_allclose(reactions[:,:3].sum(axis=0),-1000*np.array(c['loads']['resultant_per_pa']),atol=1e-5)
        np.testing.assert_allclose((np.cross(points,reactions[:,:3])+reactions[:,3:]).sum(axis=0),-1000*np.array(c['loads']['moment_per_pa_nm']),atol=1e-5)
        assert max(map(abs,sample['steel_stress_pa']))>1000
        assert sample['native_layer_checks']>0
        eig=ops.eigen(6);assert len(eig)==6 and min(eig)>0
    finally:ops.wipe()


def test_micro_three_storey_transient_records_native_fields_and_full_mass(tmp_path):
    from lsprepost_mcp.architecture.cpu_response.building_solver import solve_building_reference
    from lsprepost_mcp.architecture.cpu_response.results import write_artifacts,load_result
    c=micro_case();c['analysis']['dt_s']=.0003
    r=solve_building_reference(c)
    assert r['curves'][-1]['time_s']==pytest.approx(.015)
    assert r['peaks']['displacement_m']>1e-7 and r['peaks']['steel_abs_pa']>1e3
    assert r['diagnostics']['native_layer_checks']>0
    assert r['diagnostics']['mass_kg']==pytest.approx(c['mass_ledger']['total_kg'])
    assert r['diagnostics']['quarter_domain'] is False
    assert r['diagnostics']['tangent_rebuilds']>=3
    for key in ('displacement_time_s','steel_time_s'):
        assert any(abs(f['time_s']-r['peaks'][key])<1e-12 for f in r['frames'])
    write_artifacts(r,tmp_path);assert load_result(tmp_path)['source']==c['source']


def test_micro_building_uses_real_worker_and_parent_watchdog(tmp_path):
    import json,sys
    from lsprepost_mcp.architecture.cpu_response.contracts import adapter_identity,fingerprint
    from lsprepost_mcp.architecture.cpu_response.runtime import run_process
    from lsprepost_mcp.architecture.cpu_response.results import json_write,load_result
    c=micro_case();c['analysis']['dt_s']=.0003
    source=tmp_path/'input.json';dest=tmp_path/'output'
    json_write(source,dict(operation='solve_building_reference',case=c,input_fingerprint=fingerprint(c),adapter_identity=adapter_identity()))
    outcome=run_process([sys.executable,'-m','lsprepost_mcp.architecture.cpu_response.worker','--input',str(source),'--output',str(dest)],timeout_s=10,log_dir=tmp_path/'logs')
    assert outcome['status']=='completed',(tmp_path/'logs'/'stderr.log').read_text()
    assert load_result(dest)['input_fingerprint']==fingerprint(c)


def test_asymmetric_column_keeps_original_steel_eccentricity_and_section_coupling():
    import openseespy.opensees as ops
    from lsprepost_mcp.architecture.cpu_response.building_solver import define_column
    from lsprepost_mcp.architecture.cpu_response.column import configure_static
    p=micro_case()['column_sections'][0];p['original_bar_positions_m'][0][0]=-.08
    area=math.pi*.016**2/4;ec=30e9;es=210e9;eps=1e-4;ea=ec*(.3**2-4*area)+es*4*area
    ops.wipe();ops.model('basic','-ndm',3,'-ndf',6)
    try:
        define_column(ops,p,1,1);ops.node(1,0,0,0);ops.node(2,0,0,1)
        ops.fix(1,1,1,1,1,1,1);ops.fix(2,1,1,0,1,1,1)
        ops.geomTransf('Linear',1,0,1,0);ops.beamIntegration('Lobatto',1,1,3);ops.element('dispBeamColumn',1,1,2,1,1)
        ops.timeSeries('Linear',1);ops.pattern('Plain',1,1);ops.load(2,0,0,ea*eps,0,0,0)
        configure_static(ops);assert ops.analyze(1)==0
        force=ops.eleResponse(1,'section',1,'force')
        assert abs(force[1])==pytest.approx((es-ec)*area*.014*eps,rel=1e-9)
        for y,z in p['original_bar_positions_m']:
            sigma,strain=ops.eleResponse(1,'section',1,'fiber',y,z,2,'stressStrain')
            assert sigma==pytest.approx(es*eps,rel=1e-9)
    finally:ops.wipe()
