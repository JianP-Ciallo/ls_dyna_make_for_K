"""Native small transient cases: actual field results, energy and time refinement."""
import importlib
import math
import pytest


def backend():
    try:return importlib.import_module('lsprepost_mcp.architecture.cpu_response.backend_opensees')
    except ModuleNotFoundError:pytest.fail('CPU time integration is missing')


def test_zero_load_is_zero_and_pressure_pulse_has_real_fiber_response():
    solver=backend()
    from lsprepost_mcp.architecture.cpu_response.benchmarks import make_benchmark
    case=make_benchmark('rc-column-v1');case['loads']['curve_si']=[[0,0],[0.15,0]]
    zero=solver.solve_case(case)
    assert zero['peaks']['displacement_m']==pytest.approx(0,abs=1e-10)
    assert zero['peaks']['steel_abs_pa']==pytest.approx(0,abs=1)
    result=solver.solve_case(make_benchmark('rc-column-v1'))
    assert result['peaks']['displacement_m']>1e-5
    assert result['peaks']['steel_abs_pa']>1e5
    assert len(result['frames'])<=500
    assert result['mesh']['steel_samples'][0]['bar_id']
    # A nonzero post-pulse state must conserve elastic mechanical energy.
    energy=[v['energy_j'] for v in result['curves'] if v['time_s']>0.011]
    assert min(energy)>0
    assert (max(energy)-min(energy))/max(energy)<0.005


def test_time_step_halving_preserves_dynamic_peak_and_internal_peak_survives_frame_thinning():
    solver=backend()
    from lsprepost_mcp.architecture.cpu_response.benchmarks import make_benchmark
    case=make_benchmark('rc-column-v1')
    original=solver.solve_case(case)
    case['analysis']['dt_s']/=2;case['budget']['frames']=12
    fine=solver.solve_case(case)
    assert fine['peaks']['displacement_m']==pytest.approx(original['peaks']['displacement_m'],rel=0.02)
    assert fine['peaks']['steel_abs_pa']==pytest.approx(original['peaks']['steel_abs_pa'],rel=0.02)
    assert len(fine['frames'])<=12
    assert fine['diagnostics']['accepted_steps']>=3000
    assert fine['peaks']['steel_sample_id'] in {s['id'] for s in fine['mesh']['steel_samples']}


def test_curve_budget_does_not_remove_raw_peaks_or_load_knots():
    from lsprepost_mcp.architecture.cpu_response.benchmarks import make_benchmark
    case=make_benchmark('rc-column-v1');full=backend().solve_case(case)
    case['budget']['samples']=40
    thin=backend().solve_case(case)
    assert len(thin['curves'])<=40
    assert thin['curves'][-1]['time_s']==pytest.approx(0.15)
    for knot in [0,0.001,0.01,0.15]:
        assert any(abs(r['time_s']-knot)<1e-12 for r in thin['curves'])
    assert thin['peaks']==full['peaks']


def test_cancel_or_expired_budget_never_returns_success():
    solver=backend()
    from lsprepost_mcp.architecture.cpu_response.benchmarks import make_benchmark
    import threading,time
    flag=threading.Event();flag.set()
    with pytest.raises(solver.CaseCancelled):solver.solve_case(make_benchmark('rc-column-v1'),solver.RunControl(cancel=flag))
    with pytest.raises(solver.BudgetExceeded):solver.solve_case(make_benchmark('rc-column-v1'),solver.RunControl(deadline=time.monotonic()-1))


def test_free_column_period_matches_absolute_first_mode_reference():
    from lsprepost_mcp.architecture.cpu_response.benchmarks import make_benchmark
    from test_cpu_response_references import column_reference
    case=make_benchmark('rc-column-v1','medium');value=backend().solve_case(case)
    curve=[r for r in value['curves'] if r['time_s']>0.01]
    crossings=[]
    for a,b in zip(curve,curve[1:]):
        u,v=a['monitor_displacement_m'][0],b['monitor_displacement_m'][0]
        if u<0<=v:crossings.append(a['time_s']-u*(b['time_s']-a['time_s'])/(v-u))
    assert len(crossings)>=2
    expected=2*math.pi/column_reference()['omega_rad_s']
    assert crossings[1]-crossings[0]==pytest.approx(expected,rel=0.02)


def test_elastic_panel_transient_matches_committed_newton_reference():
    import json
    from pathlib import Path
    from lsprepost_mcp.architecture.cpu_response.benchmarks import make_benchmark
    reference=json.loads((Path(__file__).parent/'fixtures/cpu_response/panel-transient-newton-reference.json').read_text())
    result=backend().solve_case(make_benchmark('rc-panel-v1'))
    assert result['input_fingerprint']==reference['input_fingerprint']
    assert result['peaks']['displacement_m']==pytest.approx(reference['displacement_m'],rel=1e-7)
    assert result['peaks']['steel_abs_pa']==pytest.approx(reference['steel_abs_pa'],rel=1e-7)
