"""Frozen proposals/read-only real input; no real model native assembly/solve."""
from copy import deepcopy
import json
from pathlib import Path
import numpy as np
import pytest

ROOT=Path(__file__).parents[1]
INDICES=[154,183,190,191,197,198,199,208,212,420,421,466,467]


def test_proposal_freezes_exact_gravity_only_scope_without_native_launch(monkeypatch):
    from lsprepost_mcp.architecture.scene_blast.native_prebalance import prepare_request,validate_request
    import sys
    monkeypatch.setitem(sys.modules,'openseespy.opensees',None)
    case=json.loads((ROOT/'resources/scene_blast/three-storey-reference.json').read_text(encoding='utf8'))
    request=prepare_request(case,INDICES,ROOT/'.venv/cpu-response/python.exe')
    validate_request(request)
    assert request['operation']=='gravity_prebalance_and_subdomain'
    assert request['budget']==dict(worker_wall_s=150.,parent_timeout_s=180.)
    assert request['target_elements']==INDICES
    assert 'tnt' not in request and request['case']['mass_points']==case['mass_points']
    assert request['preflight']['free_structural_dofs']==2976
    assert request['preflight']['subdomain']['boundary_nodes']==[187,195,230,231,238,240,248,249,257,528,571]
    assert request['preflight']['execution_status']=='not_run_requires_current_user_confirmation'
    for key,value in [('case_fingerprint','0'*64),('method_fingerprint','0'*64)]:
        bad=deepcopy(request);bad[key]=value
        with pytest.raises(ValueError):validate_request(bad)
    bad=deepcopy(request);bad['tnt']=dict(mass_kg=10)
    with pytest.raises(ValueError):validate_request(bad)


def test_sparse_solve_dense_tangent_extraction_preserves_native_state_and_time(tmp_path):
    import openseespy.opensees as ops
    from test_scene_blast_native_reference import single_column_case
    from lsprepost_mcp.architecture.scene_blast.native_reference import build_nonlinear_reference,install_gravity,configure_static,physical_tangent,read_fields
    m=build_nonlinear_reference(ops,single_column_case())
    try:
        install_gravity(ops,m,1.)
        configure_static(ops,.1,1e-6,system='UmfPack');assert ops.analyze(1)==0
        before=read_fields(ops,m);t=ops.getTime();K=physical_tangent(ops,m)
        after=read_fields(ops,m)
        assert K.shape==(6,6) and np.linalg.eigvalsh((K+K.T)/2).min()>0
        assert ops.getTime()==t
        for key in ('displacements_m','rotations_rad','steel_stress_pa','steel_strain','column_fiber_data'):
            assert np.asarray(after[key])==pytest.approx(np.asarray(before[key]),rel=1e-12,abs=1e-12)
    finally:ops.wipe()


def test_eccentric_gravity_column_uses_pdelta_moment_bookkeeping_not_false_imbalance():
    import openseespy.opensees as ops
    from test_scene_blast_native_reference import single_column_case
    from lsprepost_mcp.architecture.scene_blast.native_reference import build_nonlinear_reference,install_gravity,configure_static,actual_balance
    c=single_column_case();c['mass_points'][0]['position_m']=[.5,.2,1.]
    m=build_nonlinear_reference(ops,c)
    try:
        install_gravity(ops,m,1.);configure_static(ops,1.,1e-7)
        assert ops.analyze(1)==0
        r=actual_balance(ops,m,1.)
        assert r['raw_initial_moment_relative_error']>1e-5
        assert r['moment_balance_relative_error']<1e-8
        assert np.linalg.norm(r['pdelta_geometric_moment_nm'])>1e-2
    finally:ops.wipe()


def test_tangent_initialization_rejects_native_state_changes(monkeypatch):
    import openseespy.opensees as ops
    from test_scene_blast_native_reference import single_column_case
    import lsprepost_mcp.architecture.scene_blast.native_reference as n
    m=n.build_nonlinear_reference(ops,single_column_case());n.install_gravity(ops,m,1.)
    n.configure_static(ops,.1,1e-6,system='UmfPack');assert ops.analyze(1)==0
    initialize=ops.initialize
    def changed_initialize():
        initialize();ops.setNodeDisp(2,1,ops.nodeDisp(2,1)+1e-3,'-commit')
    monkeypatch.setattr(ops,'initialize',changed_initialize)
    try:
        with pytest.raises(ValueError,match='切线初始化改变'):n.physical_tangent(ops,m)
    finally:ops.wipe()


@pytest.mark.parametrize('kind',['column','panel'])
def test_duplicate_initialization_commits_preserve_nonlinear_material_future_path(kind):
    """Prescribed-strain material probes; these are not structural fixities."""
    import openseespy.opensees as ops
    from test_scene_blast_native_reference import single_column_case
    import lsprepost_mcp.architecture.scene_blast.native_reference as n
    def path(duplicate):
        c=single_column_case()
        if kind=='panel':
            c.update(nodes=[[0,0,0],[1,0,0],[1,1,0],[0,1,0]],elements=[dict(kind='panel',nodes=[0,1,2,3],section=0,component_id='probe')],
                fixed_nodes=[0,1,2,3],mass_points=[dict(master=0,mass_kg=1.,position_m=[0,0,0])],nodal_load_per_pa=np.zeros((4,6)).tolist())
            c['panel_sections']=[dict(concrete_e_pa=30e9,concrete_nu=.2,steel_e_pa=210e9,layers=[
                dict(kind='concrete',t=.049,z=-.0255),dict(kind='steel',axis='X',t=.002,z=0,side='middle'),dict(kind='concrete',t=.049,z=.0255)])]
            targets=[(2,1),(3,1)]
        else:c['fixed_nodes']=[0,1];targets=[(2,3)]
        m=n.build_nonlinear_reference(ops,c)
        # Keep the native system non-empty: a free, unloaded twist/drilling
        # rotation does not affect the prescribed constitutive strain path.
        ops.remove('sp',2,6)
        values=[0.,.00012,.00004,.003,0.,-.003,0.]
        ops.timeSeries('Path',2,'-dt',1.,'-values',*values);ops.pattern('Plain',2,2)
        for tag,dof in targets:ops.remove('sp',tag,dof);ops.sp(tag,dof,1.)
        snapshots=[]
        for _ in range(len(values)-1):
            n.configure_static(ops,1.,1e-8,system='UmfPack');assert ops.analyze(1)==0
            if duplicate:n.physical_tangent(ops,m)
            snapshots.append(n.read_fields(ops,m))
        ops.wipe();return snapshots
    control=path(False);observed=path(True)
    for a,b in zip(control,observed):
        for key in ('displacements_m','rotations_rad','steel_stress_pa','steel_strain','concrete_tensile_damage','concrete_compressive_damage','column_fiber_data'):
            assert np.asarray(b[key])==pytest.approx(np.asarray(a[key]),rel=1e-12,abs=1e-12)
    assert max(abs(v) for s in observed for v in s['steel_stress_pa'])>399e6
    if kind=='panel':assert max(v for s in observed for v in s['concrete_tensile_damage'])>.1


def test_prebalance_scope_never_rebuilds_entire_parent_after_rejected_trial(tmp_path,monkeypatch):
    import openseespy.opensees as ops
    from test_scene_blast_native_reference import single_column_case
    import lsprepost_mcp.architecture.scene_blast.native_reference as n
    m=n.build_nonlinear_reference(ops,single_column_case(),execution_scope='three_storey_prebalance')
    monkeypatch.setattr(n,'check_small_tangent',lambda *a,**k:dict(status='non_positive'))
    monkeypatch.setattr(n,'replay_accepted',lambda *a,**k:pytest.fail('must not rebuild/retry a whole parent'))
    try:
        with pytest.raises(n.NativeGravityFailure) as caught:n.equilibrate_gravity(ops,m,checkpoint_dir=tmp_path,wall_s=5)
        assert len(caught.value.diagnostics['attempts'])==1
        assert caught.value.diagnostics['automatic_restart'] is False
    finally:ops.wipe()


def test_micro_worker_completes_gravity_and_thirteen_element_acceptance_in_one_process(tmp_path):
    import sys
    from test_cpu_response_building_solver import micro_case
    from test_scene_blast_native_subdomain import micro_indices
    from lsprepost_mcp.architecture.scene_blast.native_prebalance import prepare_request
    from lsprepost_mcp.architecture.cpu_response.runtime import run_process
    case=micro_case();request=prepare_request(case,micro_indices(case),sys.executable)
    source=tmp_path/'request.json';source.write_text(json.dumps(request),encoding='utf8');output=tmp_path/'output'
    run=run_process([sys.executable,'-m','lsprepost_mcp.architecture.scene_blast.native_prebalance','--input',str(source),'--output',str(output)],timeout_s=15,log_dir=tmp_path/'logs')
    assert run['status']=='completed',(tmp_path/'logs/stderr.log').read_text(encoding='utf8')[-3000:]
    result=json.loads((output/'result.json').read_text(encoding='utf8'));sub=json.loads((output/'thirteen-element-result.json').read_text(encoding='utf8'))
    assert result['parent_load_factor']==1. and result['subdomain_status']=='completed'
    assert result['automatic_restarts']==0 and sub['actual_relative_residual']<=1e-5
    assert (output/'accepted-state.json').is_file() and (output/'trial-state.json').is_file()


def test_worker_records_pending_target_before_entering_native_call(tmp_path,monkeypatch):
    import sys
    import openseespy.opensees as ops
    from test_cpu_response_building_solver import micro_case
    from test_scene_blast_native_subdomain import micro_indices
    from lsprepost_mcp.architecture.scene_blast.native_prebalance import prepare_request,run_worker
    c=micro_case();request=prepare_request(c,micro_indices(c),sys.executable)
    monkeypatch.setattr(ops,'analyze',lambda *a:(_ for _ in ()).throw(SystemExit('simulated_native_abort')))
    with pytest.raises(SystemExit):run_worker(request,tmp_path)
    pending=json.loads((tmp_path/'pending-attempt.json').read_text(encoding='utf8'))
    accepted=json.loads((tmp_path/'accepted-state.json').read_text(encoding='utf8'))
    assert pending['target']==.1 and pending['accepted_load_factor']==0.
    assert accepted['accepted_load_factor']==0. and accepted['last_accepted_fields']


def test_cli_inspects_real_request_without_launch_or_output_files(tmp_path):
    import subprocess,sys
    from lsprepost_mcp.architecture.scene_blast.native_prebalance import prepare_request
    case=json.loads((ROOT/'resources/scene_blast/three-storey-reference.json').read_text(encoding='utf8'))
    request=prepare_request(case,INDICES,sys.executable)
    source=tmp_path/'request.json';source.write_text(json.dumps(request),encoding='utf8');output=tmp_path/'must-not-exist'
    result=subprocess.run([sys.executable,str(ROOT/'scripts/run_native_prebalance.py'),'--request',str(source),'--output',str(output)],capture_output=True,timeout=5,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert result.returncode==0,result.stderr.decode('utf8','replace')
    assert json.loads(result.stdout)['status']=='not_run' and not output.exists()
