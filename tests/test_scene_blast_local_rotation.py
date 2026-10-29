"""Two-body geometry fixtures only; NO actual building/gravity/blast solve."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest
from scipy.optimize import linprog

from lsprepost_mcp.architecture.scene_blast.mechanics import rotation
from lsprepost_mcp.architecture.scene_blast.solver import MacroSystem, overlap_pairs
from lsprepost_mcp.architecture.scene_blast.sources import add_interface, body_from_quad, corners

SAVED=json.loads((Path(__file__).parent/'fixtures/scene_blast/roof_joints_20261023.json').read_text(encoding='utf8'))


@pytest.mark.parametrize('index',range(4))
def test_saved_roof_joint_is_local_and_not_rejected_by_remote_roof_radius(index):
    fixture=SAVED['fixtures'][index];s=MacroSystem(deepcopy(fixture['model']))
    for i,p in enumerate(fixture['poses']):s.x[i]=p['center_m'];s.R[i]=p['rotation']
    s.damage[~s.steel]=fixture['diagnostic_max_damage']  # Preserves saved all-active predicate only.
    before={k:getattr(s,k).copy() for k in ('x','R','history','damage','plastic','stress')}
    assert overlap_pairs(s)==set()
    r=s.contact_diagnostics['records'][0];state=r['path'][0]['state']
    assert r['classification']=='connected_junction' and r['current_support']['contained']
    assert state['proxy_rotation_sweep_m']>state['budget_m']
    assert state['rotation_sweep_m']*1000==pytest.approx(fixture['oracle']['local_cell_rotation_sweep_mm'],rel=1e-8)
    assert state['normal_closure_m']*1000==pytest.approx(fixture['oracle']['actual_face_corner_closure_mm'],rel=1e-8)
    # These are the OLD unchanged allowances, independently recorded before repair.
    assert state['compression_limit_m']==pytest.approx(.0003885)
    assert state['shear_limit_m']==pytest.approx(.000528)
    assert state['opening_limit_m']==pytest.approx(.000976)
    assert state['budget_m']==pytest.approx(.0018925)
    for k,v in before.items():assert np.array_equal(v,getattr(s,k))


def roof_column(span=1.):
    column=dict(id='column',center_m=[0,0,.5],vertices_m=corners([-.15,-.15,0],[.15,.15,1]).tolist(),
        mass_kg=216.,inertia_kg_m2=np.diag([18.405,18.405,3.24]).tolist(),fixed=False,role='column')
    roof=body_from_quad('roof',[[-span/2,-.5,1],[span/2,-.5,1],[span/2,.5,1],[-span/2,.5,1]],.18)
    m=dict(bodies=[column,roof],springs=[])
    add_interface(m,0,1,[0,0,1],[0,0,1.],[1.,0,0],.3,.3,.5)
    return m


def test_same_joint_motion_is_independent_of_remote_roof_extent():
    local=[]
    for span in [1.,10.]:
        s=MacroSystem(roof_column(span));s.R[1]=rotation(np.array([0.,.0006,0.]))
        assert overlap_pairs(s)==set()
        local.append(s.contact_diagnostics['records'][0]['path'][0]['state'])
    assert local[0]['rotation_sweep_m']==pytest.approx(local[1]['rotation_sweep_m'])
    assert local[0]['normal_closure_m']==pytest.approx(.00009,rel=1e-6)
    assert local[1]['proxy_rotation_sweep_m']>local[1]['budget_m']
    assert local[0]['proxy_rotation_sweep_m']<local[0]['budget_m']


def test_full_face_corner_compression_cannot_hide_between_gauss_samples():
    s=MacroSystem(roof_column());s.R[1]=rotation(np.array([0.,.004,0.]))
    assert overlap_pairs(s)=={(0,1)}
    state=s.contact_diagnostics['records'][0]['path'][0]['state']
    # 0.15*sin(.004), versus only 0.15/sqrt(3)*sin(.004) at Gauss points.
    assert state['normal_closure_m']==pytest.approx(.00059999840000128,rel=1e-8)
    assert state['normal_closure_m']>state['compression_limit_m']


def test_remote_fold_collision_outside_local_cell_is_still_rejected():
    # Adversarial two-block GEOMETRY ONLY fixture. Large gauge compliance allows
    # local face motion, but a full remote fold must fail the actual overlap test.
    a=body_from_quad('a',[[-100,-.05,1],[0,-.05,1],[0,.05,1],[-100,.05,1]],.18)
    b=body_from_quad('b',[[0,-.05,1],[100,-.05,1],[100,.05,1],[0,.05,1]],.18)
    m=dict(bodies=[a,b],springs=[]);add_interface(m,0,1,[0,0,1],[1.,0,0],[0,1.,0],.1,.18,100.)
    s=MacroSystem(m);s.R[1]=rotation(np.array([0.,0.,np.pi]));p=np.array([0.,0.,1.])
    s.x[1]=p+s.R[1]@(s.x0[1]-p)
    assert overlap_pairs(s)=={(0,1)}
    r=s.contact_diagnostics['records'][0]
    assert r['reason_code']=='current_overlap_outside_junction'
    assert r['path'][0]['state']['compatible']  # Not silently hidden by a local metric.
    assert not r['current_support']['contained'] and r['current_support']['outside_point_m']


def test_local_classification_is_objective_under_common_rigid_motion():
    fixture=SAVED['fixtures'][0];s=MacroSystem(deepcopy(fixture['model']))
    for i,p in enumerate(fixture['poses']):s.x[i]=p['center_m'];s.R[i]=p['rotation']
    assert overlap_pairs(s)==set()
    before=s.contact_diagnostics['records'][0]['path'][0]['state']['rotation_sweep_m']
    Q=rotation(np.array([.3,-.2,.1]));t=np.array([2.,-4.,7.])
    s.x[:2]=s.x[:2]@Q.T+t;s.R[:2]=Q@s.R[:2]
    assert overlap_pairs(s)==set()
    assert s.contact_diagnostics['records'][0]['path'][0]['state']['rotation_sweep_m']==pytest.approx(before)


def test_corner_half_section_geometry_rejects_large_local_rotation():
    s=MacroSystem(roof_column());s.R[1]=rotation(np.array([1.,0.,0.]))
    assert overlap_pairs(s)=={(0,1)}
    assert s.contact_diagnostics['records'][0]['reason_code']=='joint_kinematics_exceeded'


@pytest.mark.parametrize('angle',[0.,.3,1.2])
def test_box_intersection_vertices_match_independent_three_variable_lp(angle):
    from lsprepost_mcp.architecture.scene_blast.contacts import intersection_vertices
    a=corners([-1,-1,-1],[1,1,1]);Q=rotation(np.array([angle,.15,-.2]))
    b=corners([-.6,-.8,-.5],[.6,.8,.5])@Q.T+[.6,.3,.2]
    points=intersection_vertices(a,b)
    assert len(points)>=4
    planes=[];rhs=[]
    for v in (a,b):
        edges=v[[1,3,4]]-v[0];lengths=np.linalg.norm(edges,axis=1);axes=edges/lengths[:,None]
        n=np.vstack([axes,-axes]);planes.extend(n);rhs.extend(np.r_[lengths/2,lengths/2]+n@v.mean(0))
    A=np.array(planes);B=np.array(rhs)
    assert np.max(points@A.T-B)<1e-8
    for direction in [[1,0,0],[0,1,0],[0,0,1],[-1,-1,.7],[1,.3,-.4]]:
        result=linprog(-np.array(direction),A_ub=A,b_ub=B,bounds=[(None,None)]*3,method='highs')
        assert result.success
        assert np.max(points@direction)==pytest.approx(-result.fun,abs=1e-8)


def test_intersection_parallel_separated_and_contained_boxes():
    from lsprepost_mcp.architecture.scene_blast.contacts import intersection_vertices
    a=corners([0,0,0],[1,1,1]);b=corners([.5,.25,.1],[2,2,.8])
    p=intersection_vertices(a,b)
    assert np.allclose(p.min(0),[.5,.25,.1]) and np.allclose(p.max(0),[1,1,.8])
    contained=corners([.2,.3,.4],[.6,.7,.8]);p=intersection_vertices(a,contained)
    assert np.allclose(p.min(0),[.2,.3,.4]) and np.allclose(p.max(0),[.6,.7,.8])
    assert len(intersection_vertices(a,b+[3,0,0]))==0
