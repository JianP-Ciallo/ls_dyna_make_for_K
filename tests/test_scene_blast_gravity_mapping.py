"""Local virtual-work regressions. Only tiny synthetic geometry is generated."""
from copy import deepcopy
import numpy as np
import pytest


def test_internal_slab_weight_does_no_work_on_independent_shell_rotations():
    import openseespy.opensees as ops
    from test_cpu_response_building_mapping import three_storey_fixture
    from lsprepost_mcp.architecture.cpu_response.building_mapping import prepare_reference
    from lsprepost_mcp.architecture.scene_blast.native_reference import build_nonlinear_reference
    a,s=three_storey_fixture();b=deepcopy(a)
    b['components']['floor1']['host_density_kg_m3']+=10.
    cases=[prepare_reference(x,s,target_component_id='wall',mesh_size_m=1.,column_segments=2) for x in (a,b)]
    try:
        loads=[build_nonlinear_reference(ops,c)['gravity'] for c in cases]
        delta=loads[1]-loads[0]
        # MITC shell w is independent of theta_x/y. In-plane slab weight
        # therefore contributes no work when only those rotations vary.
        np.testing.assert_allclose(delta[:,3:],0.,atol=1e-9)
        added_mass=cases[1]['mass_ledger']['total_kg']-cases[0]['mass_ledger']['total_kg']
        assert delta[:,2].sum()==pytest.approx(-9.80665*added_mass)
        assert np.linalg.norm(delta[:,:3])>1.
    finally:ops.wipe()


def test_outside_attachment_retains_real_eccentricity_and_virtual_work():
    from lsprepost_mcp.architecture.cpu_response.gravity_mapping import shape_gravity
    nodes=np.array([[0.,0,0],[2,0,0],[2,2,0],[0,2,0]])
    points=np.array([[.5,-.3,1.]])
    weights=np.array([[.75,.25,0,0]])
    force=np.array([0,0,-10*9.80665])
    q=shape_gravity(nodes,points,np.array([10.]),np.array([[0,1,2,3]]),weights,4)
    np.testing.assert_allclose(q[:,:3].sum(0),force)
    np.testing.assert_allclose((np.cross(nodes,q[:,:3])+q[:,3:]).sum(0),np.cross(points[0],force))
    # At the real boundary y=0, overhang -.3 m produces Mx; interpolation
    # between x=0 and x=2 must not add fictitious My couples.
    np.testing.assert_allclose(q[:,4],0.,atol=1e-12)
    assert q[:,3].sum()==pytest.approx(.3*10*9.80665)
    pose=np.arange(24,dtype=float).reshape(4,6)/100
    offset=points[0]-np.array([.5,0,0])
    displacement=sum(weights[0,i]*(pose[i,:3]+np.cross(pose[i,3:],offset)) for i in range(4))
    assert np.sum(q*pose)==pytest.approx(force@displacement)


def test_stale_gravity_table_rejected_after_mass_edit():
    from test_cpu_response_building_solver import micro_case
    from lsprepost_mcp.architecture.cpu_response.gravity_mapping import mapped_gravity
    c=micro_case();c['mass_points'][0]['mass_kg']+=1.
    with pytest.raises(ValueError,match='来源已变更'):mapped_gravity(c)


def test_adjacent_floors_keep_distinct_attachment_positions_and_column_offset():
    from lsprepost_mcp.architecture.cpu_response.gravity_mapping import shape_gravity
    lower=np.array([[0.,0,0],[2,0,0],[2,2,0],[0,2,0]])
    upper=lower+np.array([3.,0,3.]);nodes=np.vstack([lower,upper])
    point=np.array([[2.5,1.,1.5]]);weights=np.array([[0,.125,.125,0,.375,0,0,.375]])
    q=shape_gravity(nodes,point,np.array([10.]),np.arange(8)[None,:],weights,4)
    force=np.array([0,0,-98.0665]);pose=np.arange(48).reshape(8,6)/100
    du=np.zeros(3)
    for ids,attachment in [(range(4),[2.,1.,0]),(range(4,8),[3.,1.,3])]:
        for i in ids:du+=weights[0,i]*(pose[i,:3]+np.cross(pose[i,3:],point[0]-attachment))
    assert np.sum(q*pose)==pytest.approx(force@du)
    # The two floor groups have opposite real horizontal eccentricities.
    assert q[:4,4].sum()*q[4:,4].sum()<0
    column=shape_gravity(np.array([[0.,0,0],[0,0,3.]]),np.array([[.02,.01,1.]]),np.array([10.]),np.array([[0,1]]),np.array([[2/3,1/3]]),2)
    np.testing.assert_allclose(column[:,3:].sum(0),np.cross([.02,.01,0],force))


def test_native_success_does_not_accept_unbalanced_shell_thickness(tmp_path,monkeypatch):
    import openseespy.opensees as ops
    from test_scene_blast_native_reference import single_column_case
    import lsprepost_mcp.architecture.scene_blast.native_reference as n
    model=n.build_nonlinear_reference(ops,single_column_case())
    monkeypatch.setattr(n,'plane_stress_diagnostics',lambda *a:dict(status='failed' if ops.getTime()>0 else 'passed',max_abs_sigma33_pa=200000. if ops.getTime()>0 else 0.,tolerance_pa=1e-8,worst=dict(element_tag=1,ip=1,layer=26)),raising=False)
    try:
        with pytest.raises(n.NativeGravityFailure) as caught:n.equilibrate_gravity(ops,model,checkpoint_dir=tmp_path,wall_s=5.)
        d=caught.value.diagnostics
        assert d['reason_code']=='native_plane_stress_unbalanced'
        assert d['accepted_load_factor']==0. and d['restored_to_accepted_state']
        assert d['attempts'][0]['plane_stress']['worst']['layer']==26
    finally:ops.wipe()


def test_parent_without_material_equilibrium_evidence_cannot_publish_boundary():
    from lsprepost_mcp.architecture.scene_blast.native_subdomain import require_equilibrated_parent
    report=dict(status='completed',accepted_load_factor=1.,actual_relative_residual=0.,force_balance_relative_error=0.,moment_balance_relative_error=0.,stability=dict(status='positive_definite'))
    with pytest.raises(ValueError):require_equilibrated_parent(report)
    report['plane_stress']=dict(status='passed',max_abs_sigma33_pa=1e-4,tolerance_pa=1e-8)
    with pytest.raises(ValueError):require_equilibrated_parent(report)


def test_material_gate_runs_after_tangent_domain_updates(tmp_path,monkeypatch):
    import openseespy.opensees as ops
    from test_scene_blast_native_reference import single_column_case
    import lsprepost_mcp.architecture.scene_blast.native_reference as n
    m=n.build_nonlinear_reference(ops,single_column_case());real=n.physical_tangent;updated=[]
    def tangent(*args,**kwargs):
        result=real(*args,**kwargs);updated.append(True);return result
    def diagnostic(*args):
        bad=bool(updated) and ops.getTime()>0
        return dict(status='failed' if bad else 'passed',max_abs_sigma33_pa=1. if bad else 0.,tolerance_pa=1e-8)
    monkeypatch.setattr(n,'physical_tangent',tangent);monkeypatch.setattr(n,'plane_stress_diagnostics',diagnostic)
    try:
        with pytest.raises(n.NativeGravityFailure) as caught:n.equilibrate_gravity(ops,m,checkpoint_dir=tmp_path,wall_s=5.)
        assert caught.value.diagnostics['reason_code']=='native_plane_stress_unbalanced'
        assert caught.value.diagnostics['accepted_load_factor']==0.
    finally:ops.wipe()
