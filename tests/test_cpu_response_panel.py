"""Real layered shell: independent thin-plate reference, mass and rebar strain."""
import importlib
import math
import pytest


def module():
    try:
        return importlib.import_module('lsprepost_mcp.architecture.cpu_response.panel')
    except ModuleNotFoundError:
        pytest.fail('layered reinforced panel builder is missing')


def test_panel_static_reference_and_signed_layer_stress():
    panel=module()
    import openseespy.opensees as ops
    from lsprepost_mcp.architecture.cpu_response.benchmarks import make_benchmark
    case=make_benchmark('rc-panel-v1','medium')
    model=panel.build_panel(ops,case);panel.run_static(ops,model,10000)
    sample=panel.read_panel_sample(ops,model,1)
    import json
    from pathlib import Path
    ref=json.loads((Path(__file__).parent/'fixtures/cpu_response/panel-layer-reference.json').read_text())
    w=ref['center_w_m']
    assert ref['navier_truncation_m']/w<1e-6
    assert model['laminate_d_nm']==pytest.approx(ref['d_nm'],rel=1e-12)
    steel=[v for v in model['layers'] if v['kind']=='steel']
    assert [v['axis'] for v in steel]==['X','Y','Y','X']
    assert [v['z'] for v in steel]==pytest.approx([-0.045,-0.035,0.035,0.045],abs=1e-12)
    assert [v['t'] for v in steel]==pytest.approx([ref['steel_t_m']]*4)
    assert ref['b_n']==pytest.approx([0]*4,abs=1e-8)
    coupling=[0.0]*4
    for layer in model['layers']:
        q=([30e9/0.96,30e9/0.96,0.2*30e9/0.96,30e9/2.4] if layer['kind']=='concrete'
           else [200e9,0,0,0] if layer['axis']=='X' else [0,200e9,0,0])
        for i in range(4):coupling[i]+=q[i]*layer['t']*layer['z']
    assert coupling==pytest.approx(ref['b_n'],abs=1e-7)
    assert abs(sample['displacements_m'][model['monitor_node']][2])==pytest.approx(w,rel=0.05)
    assert sample['support_reaction'][2]==pytest.approx(40000,abs=1e-5)
    steel_area_per_width=4*math.pi*0.01**2/(4*0.2)
    expected_mass=(2500*(0.15-steel_area_per_width)+7850*steel_area_per_width)*4
    assert model['mass_kg']==pytest.approx(expected_mass,rel=1e-12)
    assert sum(model['node_masses_kg'])==pytest.approx(expected_mass,rel=1e-12)
    assert len(sample['steel_stress_pa'])==len(model['steel_samples'])
    assert min(sample['steel_stress_pa'])<0<max(sample['steel_stress_pa'])
    for stress,strain in zip(sample['steel_stress_pa'],sample['steel_strain']):
        assert stress==pytest.approx(200e9*strain,abs=1)
    ops.wipe()


@pytest.mark.parametrize('kx,ky',[(1e-4,2e-4),(2e-4,1e-4)])
def test_prescribed_curvature_checks_layer_depth_axis_and_sign(kx,ky):
    import openseespy.opensees as ops
    from lsprepost_mcp.architecture.cpu_response.benchmarks import make_benchmark
    from lsprepost_mcp.architecture.cpu_response.column import configure_static
    panel=module();model=panel.build_panel(ops,make_benchmark('rc-panel-v1'))
    # Remove reference boundary SPs and impose a Kirchhoff quadratic patch.
    for node in range(1,len(model['nodes'])+1):
        for dof in range(1,7):ops.remove('sp',node,dof)
    ops.timeSeries('Linear',1);ops.pattern('Plain',1,1)
    for node,(x,y,z) in enumerate(model['nodes'],1):
        for dof,value in [(3,-(kx*x*x+ky*y*y)/2),(4,-ky*y),(5,kx*x),(6,0)]:ops.sp(node,dof,value)
        if x in (0,2) or y in (0,2):ops.sp(node,1,0);ops.sp(node,2,0)
    configure_static(ops);assert ops.analyze(1)==0
    sample=panel.read_panel_sample(ops,model,1)
    for loc,strain,stress in zip(model['steel_samples'],sample['steel_strain'],sample['steel_stress_pa']):
        expected=loc['position_m'][2]*(kx if loc['axis']=='X' else ky)
        assert strain==pytest.approx(expected,abs=1e-10)
        assert stress==pytest.approx(200e9*expected,abs=20)
    ops.wipe()


def test_unreinforced_plate_frequency_and_navier_deflection():
    panel=module()
    import openseespy.opensees as ops
    from lsprepost_mcp.architecture.cpu_response.benchmarks import make_benchmark
    case=make_benchmark('rc-panel-v1','medium')
    model=panel.build_panel(ops,case,reinforced=False)
    eig=ops.eigen(6)
    d=30e9*0.15**3/(12*(1-0.2**2));ma=2500*0.15
    ref=math.pi**2*math.sqrt(d/ma)*(1/4+1/4)
    bending=[]
    for mode,value in enumerate(eig,1):
        xyz=[sum(ops.nodeEigenvector(i+1,mode)[d]**2 for i in range(len(model['nodes']))) for d in range(3)]
        if xyz[2]>100*(xyz[0]+xyz[1]):bending.append(math.sqrt(value))
    assert bending and min(bending)==pytest.approx(ref,rel=0.05)
    panel.run_static(ops,model,10000)
    sample=panel.read_panel_sample(ops,model,1)
    expected=0.00406235*10000*2**4/d
    assert abs(sample['displacements_m'][model['monitor_node']][2])==pytest.approx(expected,rel=0.05)
    ops.wipe()
