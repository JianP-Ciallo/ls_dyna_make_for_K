"""Bounded native material/column/slab tests; never solve the real building."""
import json
from pathlib import Path
import numpy as np
import pytest


def test_crack_band_law_retains_strength_and_total_fracture_energy():
    from lsprepost_mcp.architecture.scene_blast.native_materials import concrete_laws
    for h in (.2,.7,2.5):
        law=concrete_laws(30e9,h)
        assert max(law['Ts'])==2e6 and max(law['Cs'])==30e6
        assert np.trapezoid(law['Ts'],law['Te'])*h==pytest.approx(200.)
        assert law['Ts'][1]/law['Te'][1]==pytest.approx(30e9)
    with pytest.raises(ValueError,match='断裂能'):concrete_laws(30e9,4.)


def test_native_shell_has_real_crack_damage_and_steel_yield():
    import openseespy.opensees as ops
    from lsprepost_mcp.architecture.scene_blast.native_materials import define_panel
    # Symmetric 1m panel, imposed uniform membrane strain; no structural solve.
    p=dict(concrete_e_pa=30e9,concrete_nu=.2,steel_e_pa=210e9,
           layers=[dict(kind='concrete',t=.049,z=-.0255),dict(kind='steel',axis='X',t=.002,z=0,side='middle'),dict(kind='concrete',t=.049,z=.0255)])
    ops.wipe();ops.model('basic','-ndm',3,'-ndf',6)
    try:
        meta=define_panel(ops,p,100,1.)
        for i,xyz in enumerate(((0,0,0),(1,0,0),(1,1,0),(0,1,0)),1):ops.node(i,*xyz)
        ops.element('ShellMITC4',1,1,2,3,4,100)
        def sample(eps):
            for i in (2,3):ops.setNodeDisp(i,1,eps,'-commit')
            ops.reactions()
            base=(1,'material',1,'fiber')
            return np.array(ops.eleResponse(*base,1,'material',1,'damage')),np.array(ops.eleResponse(*base,2,'stress')),np.array(ops.eleResponse(*base,2,'strain'))
        d,s,e=sample(2e-5);assert max(d)<1e-8 and s[0]==pytest.approx(210e9*2e-5,rel=1e-7)
        d,s,e=sample(.00012);assert d[0]>.1
        d,s,e=sample(.003);assert abs(s[0])==pytest.approx(400e6,rel=1e-7)
        assert e[0]==pytest.approx(.003) and meta['steel_e_pa']==210e9
    finally:ops.wipe()


def test_mass_source_ledger_retains_ownership_before_nodal_aggregation():
    from test_cpu_response_building_mapping import three_storey_fixture
    from lsprepost_mcp.architecture.cpu_response.building_mapping import prepare_reference
    a,s=three_storey_fixture();c=prepare_reference(a,s,target_component_id='wall',mesh_size_m=1.,column_segments=2)
    ledger=c['mass_ledger']['source_ledger']
    assert sum(v['mass_kg'] for v in ledger.values())==pytest.approx(c['mass_ledger']['total_kg'])
    assert ledger['floor1']['route']=='own_floor_shape_weights'
    assert ledger['c0-0']['route']=='own_column_chain_weights'
    assert ledger['wall']['route']=='adjacent_floor_shape_weights'
    xyz=np.array(c['nodes'])
    assert all(abs(xyz[int(i),2]-3.01)<1e-8 for i in ledger['floor1']['master_mass_kg'])


def test_native_micro_reference_full_gravity_force_moment_and_current_tangent(tmp_path):
    import openseespy.opensees as ops
    from test_cpu_response_building_solver import micro_case
    from lsprepost_mcp.architecture.scene_blast.native_reference import build_nonlinear_reference,equilibrate_gravity,read_fields
    c=micro_case();model=build_nonlinear_reference(ops,c)
    try:
        outcome=equilibrate_gravity(ops,model,checkpoint_dir=tmp_path,wall_s=10)
        assert outcome['status']=='completed' and outcome['accepted_load_factor']==pytest.approx(1.)
        assert outcome['actual_relative_residual']<=1e-5
        assert outcome['force_relative_residual']<=1e-5 and outcome['moment_relative_residual']<=1e-5
        assert outcome['force_balance_relative_error']<1e-5 and outcome['moment_balance_relative_error']<1e-5
        assert outcome['stability']['status']=='positive_definite'
        assert outcome['gravity_applied'] and not outcome['blast_applied']
        assert outcome['assumptions']==model['assumptions']
        fields=read_fields(ops,model)
        assert len(fields['steel_stress_pa'])>0 and max(map(abs,fields['steel_stress_pa']))>1e4
        assert len(fields['concrete_tensile_damage'])>0
        (tmp_path/'gravity-outcome.json').write_text(json.dumps(outcome,indent=2),encoding='utf8')
    finally:ops.wipe()


def test_native_reference_refuses_whole_building_in_small_validation_entry():
    from lsprepost_mcp.architecture.scene_blast.native_reference import build_nonlinear_reference
    import openseespy.opensees as ops
    c=json.loads((Path(__file__).parents[1]/'resources/scene_blast/three-storey-reference.json').read_text(encoding='utf8'))
    with pytest.raises(ValueError,match='小例'):build_nonlinear_reference(ops,c)


def single_column_case():
    from test_cpu_response_building_solver import micro_case
    from copy import deepcopy
    c=deepcopy(micro_case());c.update(nodes=[[0,0,0],[0,0,1.]],elements=[dict(kind='column',nodes=[0,1],section=0,component_id='c')],
        fixed_nodes=[0],mass_points=[dict(master=1,position_m=[.02,.01,1.],mass_kg=500.)],nodal_load_per_pa=np.zeros((2,6)).tolist())
    c['mass_ledger']['total_kg']=500.
    # This analytical two-node fixture replaces the source slab geometry.
    # Its one rigid column mass has its own exact eccentric gravity wrench.
    c['loads'].pop('gravity_mapping',None)
    return c


def test_native_gravity_hold_has_no_spurious_drift(tmp_path):
    import openseespy.opensees as ops
    from lsprepost_mcp.architecture.scene_blast.native_reference import build_nonlinear_reference,equilibrate_gravity,hold_gravity
    m=build_nonlinear_reference(ops,single_column_case())
    try:
        equilibrate_gravity(ops,m,checkpoint_dir=tmp_path,wall_s=5)
        r=hold_gravity(ops,m,duration_s=.02,dt_s=.001,wall_s=5)
        assert r['max_displacement_drift_m']<1e-7 and not r['blast_applied']
        assert r['max_steel_stress_drift_pa']<1e3
        (tmp_path/'hold-outcome.json').write_text(json.dumps(r,indent=2),encoding='utf8')
    finally:ops.wipe()


def test_native_overload_fails_with_complete_fields_and_checked_rollback(tmp_path):
    import openseespy.opensees as ops
    from lsprepost_mcp.architecture.scene_blast.native_reference import build_nonlinear_reference,equilibrate_gravity,NativeGravityFailure,read_fields
    m=build_nonlinear_reference(ops,single_column_case())
    try:
        with pytest.raises(NativeGravityFailure) as caught:equilibrate_gravity(ops,m,checkpoint_dir=tmp_path,wall_s=5,load_scale=10000.)
        d=caught.value.diagnostics
        assert d['accepted_load_factor']<1. and d['restored_to_accepted_state']
        assert d['last_rejected_fields'] and d['last_accepted_fields']
        assert not d['blast_applied'] and all(np.isfinite(read_fields(ops,m)['steel_stress_pa']))
        assert all(max(a['rollback_relative_field_errors'].values())<=1e-10 for a in d['attempts'] if 'rollback_relative_field_errors' in a)
        (tmp_path/'overload-outcome.json').write_text(json.dumps(d,indent=2),encoding='utf8')
    finally:ops.wipe()


def test_native_disconnected_column_is_rejected_before_analysis():
    import openseespy.opensees as ops
    from lsprepost_mcp.architecture.scene_blast.native_reference import build_nonlinear_reference
    c=single_column_case();c['nodes'].append([2,0,1]);c['nodal_load_per_pa'].append([0]*6)
    with pytest.raises(ValueError,match='承载路径'):build_nonlinear_reference(ops,c)


def test_native_tangent_timeout_returns_diagnostics_and_restores_previous_state(tmp_path,monkeypatch):
    import openseespy.opensees as ops
    import lsprepost_mcp.architecture.scene_blast.native_reference as native
    m=native.build_nonlinear_reference(ops,single_column_case())
    try:
        monkeypatch.setattr(native,'check_small_tangent',lambda *a,**kw:(_ for _ in ()).throw(TimeoutError('injected_tangent_deadline')))
        with pytest.raises(native.NativeGravityFailure) as caught:native.equilibrate_gravity(ops,m,checkpoint_dir=tmp_path,wall_s=5)
        d=caught.value.diagnostics
        assert d['reason_code']=='deadline' and d['accepted_load_factor']==0.
        assert d['restored_to_accepted_state'] and d['last_accepted_fields']
        assert np.array(native.read_fields(ops,m)['displacements_m'])==pytest.approx(np.zeros((2,3)))
    finally:ops.wipe()


def test_native_later_restore_failure_cannot_reuse_earlier_success_flag(tmp_path,monkeypatch):
    import openseespy.opensees as ops
    import lsprepost_mcp.architecture.scene_blast.native_reference as native
    m=native.build_nonlinear_reference(ops,single_column_case());real_replay=native.replay_accepted;calls=[]
    def replay(*args,**kwargs):
        calls.append(1)
        if len(calls)==2:raise RuntimeError('injected_second_replay_failure')
        return real_replay(*args,**kwargs)
    monkeypatch.setattr(native,'replay_accepted',replay)
    monkeypatch.setattr(native,'check_small_tangent',lambda *a,**kw:dict(status='non_positive'))
    try:
        with pytest.raises(native.NativeGravityFailure) as caught:native.equilibrate_gravity(ops,m,checkpoint_dir=tmp_path,wall_s=5)
        d=caught.value.diagnostics
        assert d['reason_code']=='checkpoint_restore_failed' and not d['restored_to_accepted_state']
    finally:ops.wipe()


def test_native_exception_preserves_diagnostics_and_previous_domain(tmp_path,monkeypatch):
    import openseespy.opensees as ops
    import lsprepost_mcp.architecture.scene_blast.native_reference as native
    m=native.build_nonlinear_reference(ops,single_column_case())
    monkeypatch.setattr(ops,'analyze',lambda *a:(_ for _ in ()).throw(RuntimeError('injected_native_exception')))
    try:
        with pytest.raises(native.NativeGravityFailure) as caught:native.equilibrate_gravity(ops,m,checkpoint_dir=tmp_path,wall_s=5)
        d=caught.value.diagnostics
        assert d['reason_code']=='native_exception' and d['restored_to_accepted_state']
        assert 'injected_native_exception' in d['attempts'][-1]['error']
        assert (tmp_path/'native-gravity-failure.json').exists()
    finally:ops.wipe()


def test_nonfinite_native_field_cannot_be_accepted_before_field_validation(tmp_path,monkeypatch):
    import openseespy.opensees as ops
    import lsprepost_mcp.architecture.scene_blast.native_reference as native
    m=native.build_nonlinear_reference(ops,single_column_case());real=native.read_fields;count=[]
    def read(*args):
        count.append(1)
        if len(count)==3:raise RuntimeError('nonfinite_native_fiber')
        return real(*args)
    monkeypatch.setattr(native,'read_fields',read)
    try:
        with pytest.raises(native.NativeGravityFailure) as caught:native.equilibrate_gravity(ops,m,checkpoint_dir=tmp_path,wall_s=5)
        assert caught.value.diagnostics['accepted_load_factor']==0.
        assert caught.value.diagnostics['restored_to_accepted_state']
    finally:ops.wipe()


def test_native_keeps_gravity_constant_and_uses_local_moment_residual_scale():
    import openseespy.opensees as ops
    from lsprepost_mcp.architecture.scene_blast.native_reference import build_nonlinear_reference
    m=build_nonlinear_reference(ops,single_column_case())
    try:
        assert m['gravity'][1,2]==pytest.approx(-500*9.80665)
        assert np.array(m['node_residual_length_m'])==pytest.approx([.5,.5])
    finally:ops.wipe()


def test_saved_macro_cut_boundaries_are_not_silently_averaged_into_fe_nodes():
    from lsprepost_mcp.architecture.scene_blast.native_patch import audit_boundary_compatibility
    root=Path(__file__).parents[1];ref=json.loads((root/'resources/scene_blast/three-storey-reference.json').read_text(encoding='utf8'))
    saved=json.loads((root/'tests/fixtures/scene_blast/failure_junction_92df.json').read_text(encoding='utf8'))
    result=audit_boundary_compatibility(ref,saved)
    assert not result['direct_transfer_compatible']
    conflicts=result['states']['accepted']['conflicting_nodes']
    assert {v['reference_node'] for v in conflicts}=={238,248}
    assert max(v['translation_mismatch_m'] for v in conflicts)==pytest.approx(1.2054486401281775e-5)


@pytest.mark.parametrize('state',['accepted','rejected_trial'])
def test_original_failed_two_shells_keep_recorded_outer_boundary_and_native_layers(state,tmp_path):
    import openseespy.opensees as ops
    from lsprepost_mcp.architecture.scene_blast.native_patch import two_panel_patch,solve_recorded_boundary
    root=Path(__file__).parents[1];ref=json.loads((root/'resources/scene_blast/three-storey-reference.json').read_text(encoding='utf8'))
    saved=json.loads((root/'tests/fixtures/scene_blast/failure_junction_92df.json').read_text(encoding='utf8'))
    patch=two_panel_patch(ref,saved,state)
    try:
        result=solve_recorded_boundary(ops,patch)
        assert result['status']=='completed' and result['reference_elements']==[197,208]
        assert result['max_boundary_error']<1e-10 and result['actual_relative_residual']<=1e-5
        assert result['stability']['status']=='positive_definite'
        assert result['fields']['steel_stress_pa'] and max(map(abs,result['fields']['steel_stress_pa']))>1e5
        assert result['full_gravity_acceptance'] is False
        (tmp_path/f'failed-pair-{state}.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    finally:ops.wipe()

