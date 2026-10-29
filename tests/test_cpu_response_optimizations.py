"""Native equivalence, including current shell state and changing actual dt."""
import numpy as np
import pytest
from lsprepost_mcp.architecture.cpu_response.benchmarks import make_benchmark


def short_panel():
    case=make_benchmark('rc-panel-v1')
    case['analysis']['duration_s']=.015;case['loads']['curve_si'][-1][0]=.015
    return case


def test_bulk_recovery_matches_current_native_fibers_at_every_step():
    from lsprepost_mcp.architecture.cpu_response.elastic_sampling import read_panel_elastic_sample
    from lsprepost_mcp.architecture.cpu_response.panel import build_panel,read_panel_sample
    import openseespy.opensees as ops
    case=short_panel();model=build_panel(ops,case)
    curve=case['loads']['curve_si'];ops.timeSeries('Path',1,'-time',*[t for t,p in curve],'-values',*[p for t,p in curve]);ops.pattern('Plain',1,1)
    for i,f in enumerate(model['load_map']['nodal_vectors_per_pa'],1):ops.load(i,*f)
    ops.constraints('Transformation');ops.numberer('RCM');ops.system('UmfPack');ops.algorithm('Linear');ops.integrator('Newmark',.5,.25);ops.analysis('Transient')
    maximum=0
    for step in range(150):
        assert ops.analyze(1,.0001)==0
        # No caller refresh: optimized reader must synchronize to CURRENT nodes.
        fast=read_panel_elastic_sample(ops,model,ops.getTime())
        original=read_panel_sample(ops,model,ops.getTime())
        np.testing.assert_allclose(fast['steel_stress_pa'],original['steel_stress_pa'],rtol=1e-11,atol=.01)
        np.testing.assert_allclose(fast['steel_strain'],original['steel_strain'],rtol=1e-11,atol=1e-12)
        maximum=max(maximum,max(abs(v) for v in original['steel_stress_pa']))
    assert maximum>2e6
    ops.wipe()


def test_cached_tangent_resets_on_short_step_and_when_nominal_dt_resumes():
    from lsprepost_mcp.architecture.cpu_response.backend_opensees import solve_case
    case=short_panel();case['analysis']['dt_s']=.0003
    original=solve_case(case,reuse_tangent=False,panel_recovery=False)
    fast=solve_case(case,reuse_tangent=True,panel_recovery=True)
    assert fast['diagnostics']['tangent_rebuilds']==4
    assert original['diagnostics']['tangent_rebuilds']==original['diagnostics']['accepted_steps']
    assert fast['diagnostics']['native_steel_checks']>0
    for quantity in ('monitor_displacement_m','monitor_velocity_m_s','monitor_acceleration_m_s2','steel_max_pa','steel_min_pa','energy_j','time_s'):
        np.testing.assert_allclose([r[quantity] for r in fast['curves']],[r[quantity] for r in original['curves']],rtol=1e-8,atol=1e-9)
    assert fast['peaks']['steel_abs_pa']==pytest.approx(original['peaks']['steel_abs_pa'],rel=1e-9)


@pytest.mark.parametrize('n',[4,8])
def test_quarter_panel_reflection_matches_full_domain_history_fields_and_mass(n):
    from lsprepost_mcp.architecture.cpu_response.backend_opensees import solve_case
    case=short_panel();case['mesh']['n']=n;case['budget']['frames']=12
    full=solve_case(case,quarter_panel=False)
    reduced=solve_case(case,quarter_panel=True)
    assert reduced['diagnostics']['native_element_count']==n*n//4
    assert reduced['mesh']['symmetry']['fraction']==.25
    assert len(reduced['mesh']['nodes'])==(n+1)**2
    assert reduced['diagnostics']['mass_kg']==pytest.approx(full['diagnostics']['mass_kg'],rel=1e-12)
    assert sum(reduced['mesh']['node_masses_kg'])==pytest.approx(full['diagnostics']['mass_kg'],rel=1e-12)
    for quantity in ('monitor_displacement_m','steel_max_pa','steel_min_pa','energy_j','support_reaction','time_s'):
        np.testing.assert_allclose([r[quantity] for r in reduced['curves']],[r[quantity] for r in full['curves']],rtol=1e-8,atol=1e-7)
    # Peak ties can have different times by roundoff. Compare common actual frames.
    originals={round(f['time_s'],10):f for f in full['frames']}
    for frame in reduced['frames']:
        if round(frame['time_s'],10) not in originals:continue
        for field in ('displacements_m','rotations_rad','steel_stress_pa','steel_strain'):
            np.testing.assert_allclose(frame[field],originals[round(frame['time_s'],10)][field],rtol=1e-8,atol=1e-7)
    assert reduced['peaks']['steel_abs_pa']==pytest.approx(full['peaks']['steel_abs_pa'],rel=1e-9)


def test_replay_keeps_displacement_and_steel_peak_frames_within_budget():
    from lsprepost_mcp.architecture.cpu_response.backend_opensees import solve_case
    case=short_panel();case['budget']['frames']=8
    value=solve_case(case)
    assert len(value['frames'])<=8
    for key in ('displacement_time_s','steel_time_s'):
        assert any(abs(f['time_s']-value['peaks'][key])<1e-12 for f in value['frames'])


@pytest.mark.parametrize('n',[4,8])
def test_all_mode_native_matrix_system_matches_full_native_newmark(n):
    from lsprepost_mcp.architecture.cpu_response.backend_opensees import solve_case
    case=short_panel();case['mesh']['n']=n;case['analysis']['dt_s']=.0003;case['budget']['frames']=12
    original=solve_case(case,quarter_panel=False,linear_matrix=False,reuse_tangent=False,panel_recovery=False)
    fast=solve_case(case,quarter_panel=False,linear_matrix=True)
    assert fast['diagnostics']['dynamic_modes']==(n-1)**2
    assert fast['diagnostics']['all_dynamic_modes_retained']
    assert fast['diagnostics']['native_steel_checks']>0
    for quantity in ('monitor_displacement_m','monitor_velocity_m_s','monitor_acceleration_m_s2','steel_max_pa','steel_min_pa','energy_j','support_reaction','time_s'):
        np.testing.assert_allclose([r[quantity] for r in fast['curves']],[r[quantity] for r in original['curves']],rtol=1e-7,atol=1e-7)
    assert fast['peaks']['steel_abs_pa']==pytest.approx(original['peaks']['steel_abs_pa'],rel=1e-8)
    originals={round(f['time_s'],10):f for f in original['frames']}
    common=[f for f in fast['frames'] if round(f['time_s'],10) in originals]
    assert len(common)>=2
    for frame in common:
        for field in ('displacements_m','rotations_rad','steel_stress_pa','steel_strain'):
            np.testing.assert_allclose(frame[field],originals[round(frame['time_s'],10)][field],rtol=1e-7,atol=1e-7)
