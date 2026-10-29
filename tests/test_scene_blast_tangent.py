"""Tiny constitutive/connection checks; never generate or solve a building."""
import numpy as np
import pytest

from lsprepost_mcp.architecture.scene_blast.gravity import capture
from lsprepost_mcp.architecture.scene_blast.mechanics import rotation
from lsprepost_mcp.architecture.scene_blast.solver import MacroSystem
from test_scene_blast_gravity import hanging_block


@pytest.mark.parametrize('committed', [False, True])
def test_tangent_uses_loading_branch_instead_of_averaging_across_cracking(committed):
    model=hanging_block()
    for spring in model['springs']:spring['length_m']=.7
    s=MacroSystem(model)
    onset=2e6/(30e9/.7)
    # Recorded failed spring was just 1.87 nm past this exact onset.
    opening=onset+1.87e-9
    s.x[0,2]-=opening
    if committed:s.forces()
    saved=capture(s)
    K=s.current_stiffness()
    # Independent derivative of the piecewise section law on further loading.
    expected=.04*(.995*(-2e6/(.0002-onset))+.005*200e9/.7)
    assert K[2,2]==pytest.approx(expected,rel=2e-7)
    assert K[2,2]<0  # This local branch really softens, even though steel is elastic.
    for key,value in saved.items():assert np.array_equal(getattr(s,key),value),key


def test_tangent_on_damaged_unloading_branch_is_secant_not_loading_average():
    s=MacroSystem(hanging_block())
    s.x[0,2]-=50e-6;s.forces()
    s.x[0,2]+=.2e-9  # Strict unloading, smaller than the old finite-difference step.
    expected=.04*(.995*(1-s.damage[0])*30e9/.05+.005*200e9/.05)
    assert s.current_stiffness()[2,2]==pytest.approx(expected,rel=2e-7)


@pytest.mark.parametrize('kind,displacement,axis,continuation',[
    ('concrete',[0,0,.0001],2,1.),
    ('steel',[0,0,-.0002],2,-1.),
    ('concrete',[.0001,0,0],0,1.),
])
def test_committed_plastic_corner_uses_continuing_loading_derivative(kind,displacement,axis,continuation):
    model=hanging_block()
    model['springs']=[p for p in model['springs'] if p['kind']==kind]
    s=MacroSystem(model);s.x[0]+=displacement;s.forces()
    initial_force=s.forces(commit=False)[0][0,axis]
    K=s.current_stiffness()
    s.x[0,axis]+=continuation*1e-9
    actual=s.forces(commit=False)[0][0,axis]
    expected=-(actual-initial_force)/(continuation*1e-9)
    assert abs(expected)<1.
    assert K[axis,axis]==pytest.approx(expected,abs=1.)


@pytest.mark.parametrize('kind,displacement,axis,continuation',[
    ('concrete',[0,0,.0001],2,1.),
    ('steel',[0,0,-.0002],2,-1.),
    ('concrete',[.0001,0,0],0,1.),
])
def test_plastic_connection_recovers_elastic_tangent_on_strict_unloading(kind,displacement,axis,continuation):
    model=hanging_block();model['springs']=[p for p in model['springs'] if p['kind']==kind]
    s=MacroSystem(model);s.x[0]+=displacement;s.forces()
    s.x[0,axis]-=continuation*1e-9
    expected=np.sum(s.area*(s.kn if axis==2 else s.ks))
    assert s.current_stiffness()[axis,axis]==pytest.approx(expected,rel=1e-10)


def test_fully_fractured_concrete_has_no_fictitious_zero_slip_shear_stiffness():
    model=hanging_block();model['springs']=[p for p in model['springs'] if p['kind']=='concrete']
    s=MacroSystem(model);s.x[0,2]-=.0003;s.forces()
    assert np.all(s.damage==1)
    assert s.current_stiffness().toarray()==pytest.approx(np.zeros((12,12)),abs=1e-8)


@pytest.mark.parametrize('displacement', [
    [2e-6,-3e-6,-1e-6], [4e-5,-3e-5,-4e-5], [2e-4,1e-4,-8e-5],
    [5e-5,2e-5,8e-5], [3e-4,-1e-4,-3e-4],
])
def test_finite_rotation_tangent_matches_independent_force_difference(displacement):
    s=MacroSystem(hanging_block())
    common=rotation(np.array([.3,-.2,.4]))
    s.x=s.x@common.T;s.R[:]=common
    s.x[0]+=common@np.array(displacement)
    s.R[0]=rotation(common@np.array([1e-4,-2e-4,1e-4]))@s.R[0]
    x,R=s.x.copy(),s.R.copy();saved=capture(s)
    rng=np.random.default_rng(73);direction=rng.normal(size=(2,6));direction[1]=0
    eps=2e-10
    K=s.current_stiffness()
    s.x=x+eps*direction[:,:3];s.R=rotation(eps*direction[:,3:])@R
    fp,tp=s.forces(commit=False)
    s.x=x-eps*direction[:,:3];s.R=rotation(-eps*direction[:,3:])@R
    fm,tm=s.forces(commit=False)
    derivative=np.c_[fp-fm,tp-tm].ravel()/(2*eps)
    assert K@direction.ravel()==pytest.approx(-derivative,rel=1e-4,abs=5.)
    for key,value in saved.items():
        if key not in ('x','R'):assert np.array_equal(getattr(s,key),value),key
