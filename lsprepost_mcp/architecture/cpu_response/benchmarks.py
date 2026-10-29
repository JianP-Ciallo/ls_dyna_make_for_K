"""Versioned numerical fixtures, not measured properties of the user's building."""
from copy import deepcopy
from .contracts import fingerprint

IDS = ('rc-column-v1', 'rc-panel-v1')


def make_benchmark(case_id: str, refinement: str = 'base') -> dict:
    if case_id not in IDS:
        raise ValueError('unknown benchmark')
    column = case_id == IDS[0]
    case = dict(
        source=dict(kind='benchmark', id=case_id, revision=1),
        geometry=(dict(kind='column', length_m=3.0, width_m=0.3, depth_m=0.3)
                  if column else dict(kind='panel', a_m=2.0, b_m=2.0, thickness_m=0.15)),
        reinforcement=(dict(diameter_m=0.016, cover_m=0.04, count=4)
                       if column else dict(diameter_m=0.01, cover_m=0.025, spacing_m=0.2)),
        materials=dict(concrete_e_pa=30e9, concrete_nu=0.2, steel_e_pa=200e9,
                       concrete_density=2500.0, steel_density=7850.0, profile='elastic_reference'),
        mesh=(dict(n=4, fibers=10, integration_points=3) if column else dict(n=4)),
        loads=dict(curve_si=[[0,0],[0.001,10000],[0.01,0],[0.15,0]],
                   static_pressure_pa=10000.0, direction=([1,0,0] if column else [0,0,-1])),
        analysis=dict(kind='dynamic', dt_s=0.0001, duration_s=0.15, damping=0.0),
        budget=dict(wall_s=30.0, max_steps=10000, frames=500, samples=5000),
        assumptions=['numerical_reference_not_building_calibration', 'elastic_small_displacement',
                     'perfect_bond', 'lumped_translation_mass_no_rotary_inertia',
                     'no_shear_failure_spall_slip_fracture_or_collapse'],
    )
    case['source']['fingerprint'] = fingerprint(case)
    if refinement not in ('base','medium','fine','ultra'):
        raise ValueError('unknown refinement')
    case['mesh']['n'] *= {'base':1,'medium':2,'fine':4,'ultra':8}[refinement]
    return deepcopy(case)
