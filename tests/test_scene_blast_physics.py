"""Small arithmetic/constitutive fixtures only; never solve a building."""
import math

import numpy as np
import pytest

from lsprepost_mcp.architecture.scene_blast.loads import parameters, pulse
from lsprepost_mcp.architecture.scene_blast.mechanics import cohesive, steel_return, rotation, spring_wrench, ground_impulse


def test_surface_burst_reference_and_scaling():
    p = parameters(10000., 500.)
    assert p['incident_pa'] == pytest.approx(5054.9639655, rel=1e-8)
    assert p['reflected_pa'] == pytest.approx(10244.621193, rel=1e-8)
    assert p['arrival_s'] == pytest.approx(1.2761650109, rel=1e-8)
    q = parameters(80000., 1000.)
    assert q['incident_pa'] == pytest.approx(p['incident_pa'])
    assert q['incident_impulse_pa_s'] == pytest.approx(2*p['incident_impulse_pa_s'])
    for mass, distance in [(0, 10), (1, .1), (1, 50), (math.nan, 10)]:
        with pytest.raises(ValueError): parameters(mass, distance)


def test_triangular_pressure_preserves_peak_arrival_and_impulse():
    p = parameters(10., 10.)
    duration = 2*p['reflected_impulse_pa_s']/p['reflected_pa']
    t = np.linspace(p['arrival_s'], p['arrival_s']+duration, 10001)
    y = pulse(t, p['arrival_s'], p['reflected_pa'], p['reflected_impulse_pa_s'])
    assert y[0] == p['reflected_pa']
    assert np.trapezoid(y, t) == pytest.approx(p['reflected_impulse_pa_s'], rel=1e-6)
    assert pulse(p['arrival_s']-1e-5, p['arrival_s'], p['reflected_pa'], p['reflected_impulse_pa_s']) == 0


def test_tensile_fracture_energy_size_objectivity_and_unloading():
    # Entire area under traction-opening curve is Gf. Size changes strain, not crack energy.
    for length in [.1, .25, .5]:
        E, ft, gf = 30e9, 2.5e6, 100.
        onset = ft*length/E
        final = 2*gf/ft
        x = np.linspace(0, final, 20001)
        traction, history, damage = cohesive(x, np.zeros_like(x), E/length, ft, gf)
        assert np.trapezoid(traction, x) == pytest.approx(gf, rel=1e-4)
        assert traction.max() == pytest.approx(ft, rel=.002)
        k = np.array([.5*final]);old = k.copy()
        _, hist, dam = cohesive(np.array([.1*onset]), k, E/length, ft, gf)
        expected=max(0.,1-ft*(final-old[0])/(final-onset)/(E/length*old[0]))
        assert hist[0] == old[0] and dam[0] == pytest.approx(expected)
        compressed, _, _ = cohesive(np.array([-onset]), k, E/length, ft, gf)
        assert compressed[0] == pytest.approx(-ft)  # crack closure recovers compression


def test_steel_has_plastic_unloading_separate_from_concrete():
    stress, plastic, failed = steel_return(np.array([.01]), np.zeros(1), np.zeros(1, bool), 200e9, 400e6, .05)
    assert stress[0] == pytest.approx(400e6)
    assert plastic[0] > 0 and not failed[0]
    stress2, _, _ = steel_return(plastic, plastic, failed, 200e9, 400e6, .05)
    assert abs(stress2[0]) < 1e-6
    assert steel_return(np.array([.06]), plastic, failed, 200e9, 400e6, .05)[2][0]


def test_finite_rigid_rotation_zero_gap_and_equal_opposite_wrench():
    centers = np.array([[0., 0, 0], [1., 0, 0]])
    anchor = np.array([.5, .2, .1])
    R = rotation(np.array([.7, -.8, 1.1]))
    x = centers@R.T + [7, 2, 3]
    f, torque = spring_wrench(x, np.stack([R, R]), np.array([[0, 1]]),
        (anchor-centers[0])[None], (anchor-centers[1])[None], np.array([[1., 0, 0]]), np.array([[1e6, 4e5]]))
    assert np.linalg.norm(f) < 1e-8 and np.linalg.norm(torque) < 1e-8
    x[1, 0] += .001
    f, torque = spring_wrench(x, np.stack([R, R]), np.array([[0, 1]]),
        (anchor-centers[0])[None], (anchor-centers[1])[None], np.array([[1., 0, 0]]), np.array([[1e6, 4e5]]))
    assert np.linalg.norm(f.sum(axis=0)) < 1e-9
    assert np.linalg.norm((np.cross(x, f)+torque).sum(axis=0)) < 1e-8


def test_fixed_plane_impact_and_no_impulse_while_separating():
    v = np.array([0., 0., -3.]);m = 10.
    j = ground_impulse(v, np.zeros(3), np.zeros(3), m, np.eye(3), restitution=.1)
    assert j[2] == pytest.approx(33.)
    after = v+j/m
    assert after[2] == pytest.approx(.3)
    assert np.dot(after, after) <= np.dot(v,v)
    assert np.all(ground_impulse(after, np.zeros(3), np.zeros(3), m, np.eye(3)) == 0)


def test_gravity_is_balanced_in_actual_nonlinear_law_and_holds():
    from lsprepost_mcp.architecture.scene_blast.sources import shell_model
    from lsprepost_mcp.architecture.scene_blast.solver import MacroSystem
    m=shell_model('wall',[(1,0,0,0),(2,1,0,0),(3,1,0,1),(4,0,0,1)],[(1,1,1,2,3,4)],.2)
    s=MacroSystem(m,{'damping_ratio':0})
    assert s.equilibrate()<1e-5
    initial=s.x.copy()
    for _ in range(100):s.step(s.dt_stable*.5);s.plane_contact()
    assert np.max(np.abs(s.x-initial))<1e-8
    assert s.damage.max()<1e-8


def test_detached_body_keeps_mass_and_falls_under_gravity():
    from lsprepost_mcp.architecture.scene_blast.sources import shell_model
    from lsprepost_mcp.architecture.scene_blast.solver import MacroSystem
    m=shell_model('fall',[(1,0,0,2),(2,1,0,2),(3,1,0,3),(4,0,0,3)],[(1,1,1,2,3,4)],.2)
    m['springs']=[]
    s=MacroSystem(m,{'damping_ratio':0});mass=s.mass.sum();z=s.x[0,2];dt=.0001
    for _ in range(100):s.step(dt)
    assert s.mass.sum()==mass
    assert s.x[0,2]-z==pytest.approx(-.5*9.80665*.01**2,rel=.011)
    assert s.v[0,2]==pytest.approx(-9.80665*.01)


def test_interface_elastic_stiffness_has_correct_axial_bending_and_no_mechanism():
    from lsprepost_mcp.architecture.scene_blast.sources import add_interface,corners
    from lsprepost_mcp.architecture.scene_blast.solver import MacroSystem
    model={'bodies':[dict(id='beam',center_m=[.5,0,1],vertices_m=corners([0,-.1,.9],[1,.1,1.1]).tolist(),mass_kg=10,inertia_kg_m2=np.eye(3).tolist(),fixed=False)],'springs':[]}
    add_interface(model,0,-1,[0,0,1],[-1.,0,0],[0,1.,0],.2,.2,.5,steel_ratio=0)
    s=MacroSystem(model);K=s.K[:6,:6].toarray();E=MATERIAL_E=30e9;area=.04
    assert K[0,0]==pytest.approx(E*area/.5)
    assert K[3,3]>0
    assert np.linalg.eigvalsh(K).min()>0
    # Rotation about y, with translation removing shear at interface center.
    q=np.array([0,0,-.5,0,1,0])
    expected=E*(.2*.2**3/12)/.5
    assert q@K@q==pytest.approx(expected)


def test_finite_relative_rotation_wrench_is_the_energy_gradient():
    from lsprepost_mcp.architecture.scene_blast.mechanics import gaps
    x=np.array([[0.,0,0],[1.01,.02,.03]]);R=np.array([rotation(np.array([.3,-.2,.1])),rotation(np.array([-.1,.2,-.2]))]);pairs=np.array([[0,1]])
    ra=np.array([[.5,.2,.1]]);rb=np.array([[-.5,.2,.1]]);n=np.array([[1.,0,0]]);k=np.array([[1e6,4e5]])
    f,torque=spring_wrench(x,R,pairs,ra,rb,n,k)
    def energy(rot):
        g,normal,*_=gaps(x,rot,pairs,ra,rb,n);dn=np.sum(g*normal,axis=1)
        return float((.5*k[:,0]*dn**2+.5*k[:,1]*(np.sum(g*g,axis=1)-dn**2)).sum())
    eps=1e-7
    for body in [0,1]:
        for axis in range(3):
            d=np.eye(3)[axis]*eps;plus=R.copy();minus=R.copy();plus[body]=rotation(d)@R[body];minus[body]=rotation(-d)@R[body]
            derivative=(energy(plus)-energy(minus))/(2*eps)
            assert torque[body,axis]==pytest.approx(-derivative,rel=1e-6,abs=1e-3)


def test_compressive_plastic_unloading_cannot_bypass_tension_damage():
    from lsprepost_mcp.architecture.scene_blast.sources import shell_model
    from lsprepost_mcp.architecture.scene_blast.solver import MacroSystem
    m=shell_model('wall',[(1,0,0,0),(2,1,0,0),(3,1,0,1),(4,0,0,1)],[(1,1,1,2,3,4)],.2);s=MacroSystem(m)
    s.x[0,2]-=.002;s.forces()
    assert np.any(s.compression_plastic<0)
    s.x[0,2]+=.0019;s.forces()
    assert np.max(s.stress[~s.steel])<=s.mat['ft_pa']*(1+1e-8)


def test_step_average_catches_pulse_entirely_between_time_samples():
    from lsprepost_mcp.architecture.scene_blast.loads import pulse_average
    arrival=.0002;peak=1e5;impulse=10.
    assert pulse_average(0.,.001,arrival,peak,impulse)==pytest.approx(impulse/.001)


def test_micro_wall_end_to_end_keeps_input_identity_and_real_peaks():
    from lsprepost_mcp.architecture.scene_blast.sources import shell_model
    from lsprepost_mcp.architecture.scene_blast.contracts import normalize_input,snapshot
    from lsprepost_mcp.architecture.scene_blast.solver import solve
    m=shell_model('micro-wall',[(1,0,0,0),(2,1,0,0),(3,1,0,1),(4,0,0,1)],[(1,1,1,2,3,4)],.2)
    m.update(source={'kind':'micro_fixture'},assumptions=['test fixture; not a real building'])
    config=normalize_input({'source':{'kind':'commercial_supermarket'},'tnt':{'position_m':[0,-5,0],'mass_kg':.01},'analysis':{'duration_s':.05}})
    frozen=snapshot(config,m);r=solve(frozen)
    assert r['status']=='completed' and len(r['frames'])>2
    assert r['input_fingerprint']==frozen['input_fingerprint']
    assert r['metrics']['gravity_relative_residual']<1e-5
    assert 0<max(r['peaks']['displacement_mm'])<1
    assert r['metrics']['completed_steps']==r['metrics']['planned_steps']
    assert r['metrics']['mass_kg']==pytest.approx(480)
