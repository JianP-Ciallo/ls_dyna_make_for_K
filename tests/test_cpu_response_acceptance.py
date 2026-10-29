"""Acceptance must fail on coarse peaks, incomplete windows and zero references."""
from copy import deepcopy


def measurements():
    base=dict(status='completed',n=16,dt_s=.0001,duration_s=.15,last_time_s=.15,wall_s=1,physical_identity='same',
              displacement_m=1.,steel_abs_pa=100.,displacement_time_s=.02,steel_time_s=.04,period_s=.01,energy_drift=.001,
              adapter_identity='same-adapter',steel_response_method='native_fiber',native_steel_checks=0,
              integration_method='native_Newmark',dynamic_modes=None,expected_dynamic_modes=None,
              all_dynamic_modes_retained=False,condensation_residual=None)
    fine=dict(base,n=32,displacement_m=1.01,steel_abs_pa=101.)
    half=dict(fine,dt_s=.00005,displacement_m=1.005,steel_abs_pa=100.5)
    return [base,fine,half]


def test_small_nonzero_changes_pass_with_explicit_spatial_and_temporal_metrics():
    from lsprepost_mcp.architecture.cpu_response.acceptance import assess_convergence
    value=assess_convergence(measurements())
    assert value['passed']
    assert abs(value['changes']['space']['steel_abs_pa']-.01)<1e-12


def test_steel_spatial_error_cannot_be_hidden_by_displacement_convergence():
    from lsprepost_mcp.architecture.cpu_response.acceptance import assess_convergence
    rows=measurements();rows[1]['steel_abs_pa']=104;rows[2]['steel_abs_pa']=104
    assert not assess_convergence(rows)['passed']


def test_recovery_and_full_basis_require_native_checks_and_complete_identity():
    from lsprepost_mcp.architecture.cpu_response.acceptance import assess_convergence
    rows=measurements()
    for r in rows:
        r.update(steel_response_method='elastic_section_recovery_native_checked',native_steel_checks=100,
                 integration_method='native_FE_full_basis_Newmark',dynamic_modes=64,expected_dynamic_modes=64,
                 all_dynamic_modes_retained=True,condensation_residual=1e-15)
    assert assess_convergence(rows)['passed']
    for key,value in [('adapter_identity','other'),('native_steel_checks',0),('dynamic_modes',63),
                      ('all_dynamic_modes_retained',False),('condensation_residual',.01)]:
        altered=deepcopy(rows);altered[1][key]=value
        assert not assess_convergence(altered)['passed'],key


def test_short_window_wrong_fine_dt_or_zero_signal_never_passes():
    from lsprepost_mcp.architecture.cpu_response.acceptance import assess_convergence
    for key,value in [('duration_s',.015),('last_time_s',.015),('steel_abs_pa',0),('wall_s',31),('physical_identity','different')]:
        rows=measurements();rows[2][key]=value
        assert not assess_convergence(rows)['passed'],key
    rows=measurements();rows[2]['dt_s']=.0001
    assert not assess_convergence(rows)['passed']
