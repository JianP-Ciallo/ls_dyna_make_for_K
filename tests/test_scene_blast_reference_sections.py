"""Reference section algebra and tiny two-sided interfaces only."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from lsprepost_mcp.architecture.scene_blast.contracts import MATERIAL


def reference_pair():
    r=json.loads((Path(__file__).resolve().parents[1]/'resources/scene_blast/three-storey-reference.json').read_text(encoding='utf8'))
    return deepcopy(r['panel_sections'][10]),deepcopy(r['panel_sections'][12])


def test_reference_fibers_preserve_directional_area_centroid_and_bending_coupling():
    from lsprepost_mcp.architecture.scene_blast.reference_sections import panel_fibers
    left,_=reference_pair();f=panel_fibers(left,width=.2,length=.075,axis='X')
    steel=f['steel'];area=f['area_m2'];z=f['positions_m'][:,1]
    assert area[steel].sum()==pytest.approx(.0004037532446492825)
    expected_z=sum(p['t']*p['z'] for p in left['layers'] if p['kind']=='steel' and p['axis']=='X')/sum(
        p['t'] for p in left['layers'] if p['kind']=='steel' and p['axis']=='X')
    assert np.sum(area[steel]*z[steel])/area[steel].sum()==pytest.approx(expected_z)
    # The two sides retain separate layer positions, not invented averaged bars.
    assert set(np.round(z[steel],8))=={-.042,.0060003}
    E=np.where(steel,200e9,30e9)
    K=np.einsum('n,ni,nj->ij',E*area/.075,f['basis'],f['basis'])
    assert abs(K[0,2])>1e6 and np.all(np.linalg.eigvalsh(K)>0)
    mirrored=deepcopy(left)
    for p in mirrored['layers']:p['z']=-p['z']
    other=panel_fibers(mirrored,width=.2,length=.075,axis='X')
    Q=np.diag([1,1,-1])
    other_K=np.einsum('n,ni,nj->ij',np.where(other['steel'],200e9,30e9)*other['area_m2']/.075,other['basis'],other['basis'])
    assert other_K==pytest.approx(Q@K@Q,rel=1e-12,abs=1e-4)


def test_two_sided_elastic_connection_matches_independent_internal_node_elimination():
    from lsprepost_mcp.architecture.scene_blast.reference_sections import panel_fibers,elastic_matrix,series_elastic
    a,b=reference_pair()
    left=panel_fibers(a,width=.2,length=.075,axis='X')
    right=panel_fibers(b,width=.2,length=.625,axis='X')
    A,B=elastic_matrix(left),elastic_matrix(right)
    # Independently assembled two-element chain with one internal section node.
    # The left end is fixed, q is the right end and u is the unknown joint.
    full=np.block([[A+B,-B],[-B,B]])
    load=np.r_[np.zeros(3),[100.,2.,-3.]]
    solution=np.linalg.solve(full,load)
    condensed=series_elastic(left,right)
    assert condensed@solution[3:]==pytest.approx(load[3:],rel=1e-10,abs=1e-7)
    assert np.all(np.linalg.eigvalsh(condensed)>0)
    assert A@solution[:3]==pytest.approx(B@(solution[3:]-solution[:3]),abs=1e-7)
    assert abs(condensed[0,2])>1e4  # membrane-bending coupling must survive condensation


def test_reference_section_does_not_count_orthogonal_steel_as_axial_steel():
    from lsprepost_mcp.architecture.scene_blast.reference_sections import panel_fibers
    a,_=reference_pair()
    x=panel_fibers(a,width=.2,length=.075,axis='X')
    y=panel_fibers(a,width=.2,length=.075,axis='Y')
    assert x['area_m2'][x['steel']].sum()!=y['area_m2'][y['steel']].sum()
    assert set(np.round(y['positions_m'][y['steel'],1],8))=={-.0259999,-.0099998}
    assert x['assumption']=='ideal_monolithic_section_fully_anchored_rebar'


def test_reference_fiber_trial_is_pure_and_recovers_existing_uniaxial_law():
    from lsprepost_mcp.architecture.scene_blast.reference_sections import panel_fibers,new_state,section_trial
    a,_=reference_pair();f=panel_fibers(a,width=.2,length=.075,axis='X')
    state=new_state(f);saved=deepcopy(state)
    q=np.array([30e-6,0,0])
    N,K,trial=section_trial(f,q,state)
    # Independent cohesive envelope and elastic bars at this uniform extension.
    k=30e9/.075;onset=2e6/k
    sigma=2e6*(.0002-q[0])/(.0002-onset)
    expected=f['area_m2'][~f['steel']].sum()*sigma+f['area_m2'][f['steel']].sum()*200e9*q[0]/.075
    assert N[0]==pytest.approx(expected,rel=1e-12)
    assert np.any(trial['damage']>0)
    for key in state:assert np.array_equal(state[key],saved[key])
    assert MATERIAL['steel_fy_pa']==400e6


def test_serial_nonlinear_sections_balance_force_and_match_condensed_derivative():
    from lsprepost_mcp.architecture.scene_blast.reference_sections import panel_fibers,SerialSection
    a,_=reference_pair()
    left=panel_fibers(a,width=.2,length=.025,axis='X')
    right=panel_fibers(a,width=.2,length=.025,axis='X')
    joint=SerialSection(left,right);state=joint.initial_state();saved=deepcopy(state)
    q=np.array([40e-6,0,0])
    force,K,trial=joint.trial(q,state)
    assert trial['relative_internal_residual']<1e-8
    assert trial['assumption']=='ideal_monolithic_section_fully_anchored_rebar'
    assert np.any(trial['left']['damage']>0)
    assert trial['left_force']==pytest.approx(trial['right_force'],abs=1e-4)
    assert trial['left_gap']+trial['right_gap']==pytest.approx(q,abs=1e-14)
    for i in range(3):
        delta=np.eye(3)[i]*1e-9
        actual=(joint.trial(q+delta,state)[0]-joint.trial(q-delta,state)[0])/(2e-9)
        assert K[:,i]==pytest.approx(actual,rel=2e-5,abs=5.)
    for side in ('left','right'):
        for key in saved[side]:assert np.array_equal(state[side][key],saved[side][key])


def test_serial_rejects_internal_softening_instability_without_committing_history():
    from lsprepost_mcp.architecture.scene_blast.reference_sections import panel_fibers,SerialSection,SectionFailure
    a,_=reference_pair();a['layers']=[p for p in a['layers'] if p['kind']=='concrete']
    joint=SerialSection(panel_fibers(a,width=.2,length=.025,axis='X'),panel_fibers(a,width=.2,length=.025,axis='X'))
    state=joint.initial_state()
    with pytest.raises(SectionFailure):joint.trial(np.array([60e-6,0,0]),state)
    assert np.max(state['left']['history'])==0 and np.max(state['right']['history'])==0
