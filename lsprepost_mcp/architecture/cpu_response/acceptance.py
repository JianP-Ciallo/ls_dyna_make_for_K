"""Read-only convergence assessment; missing/failed measurements never pass."""
from copy import deepcopy
import math
import statistics
from .contracts import fingerprint


def assess_convergence(rows):
    checks={};changes={}
    checks['three_completed_full_window_cases']=len(rows)==3 and all(
        r['status']=='completed' and math.isclose(r['duration_s'],.15,abs_tol=1e-12)
        and math.isclose(r['last_time_s'],.15,abs_tol=1e-12) and 0<r['wall_s']<=30 for r in rows)
    if len(rows)!=3:return dict(passed=False,checks=checks,changes=changes)
    checks['same_physical_case']=len({r['physical_identity'] for r in rows})==1
    checks['same_verified_adapter']=all(r.get('adapter_identity') for r in rows) and len({r.get('adapter_identity') for r in rows})==1
    checks['native_steel_verification']=all(
        r.get('steel_response_method')=='native_fiber' or
        (r.get('steel_response_method')=='elastic_section_recovery_native_checked' and (r.get('native_steel_checks') or 0)>0)
        for r in rows)
    checks['complete_dynamic_basis']=all(
        r.get('integration_method')=='native_Newmark' or
        (r.get('integration_method')=='native_FE_full_basis_Newmark' and r.get('all_dynamic_modes_retained') is True
         and isinstance(r.get('dynamic_modes'),int) and r['dynamic_modes']>0
         and r['dynamic_modes']==r.get('expected_dynamic_modes')
         and isinstance(r.get('condensation_residual'),(int,float)) and 0<=r['condensation_residual']<=1e-10)
        for r in rows)
    checks['explicit_16_32_and_32_halved_dt']=([r['n'] for r in rows]==[16,32,32]
        and all(math.isclose(r['dt_s'],dt,abs_tol=1e-12) for r,dt in zip(rows,[.0001,.0001,.00005])))
    checks['nonzero_energy_conservation']=all(math.isfinite(r['energy_drift']) and 0<=r['energy_drift']<=.005 for r in rows)
    for name,a,b in [('space',rows[0],rows[1]),('time',rows[1],rows[2])]:
        changes[name]={}
        for field in ('displacement_m','steel_abs_pa','period_s'):
            valid=all(isinstance(r[field],(int,float)) and math.isfinite(r[field]) and r[field]>0 for r in (a,b))
            error=abs(b[field]/a[field]-1) if valid else None
            changes[name][field]=error;checks[name+'_'+field]=valid and error<=.02
        for field in ('displacement_time_s','steel_time_s'):
            valid=a[field]>0 and b[field]>0
            delta=abs(b[field]-a[field]);changes[name][field]=delta
            checks[name+'_'+field]=valid and (delta/a[field]<=.02 or delta<=max(a['dt_s'],b['dt_s'])+1e-12)
    return dict(passed=all(checks.values()),checks=checks,changes=changes)


def result_measurement(case,result,process):
    physical=deepcopy(case);physical.pop('mesh');physical['analysis'].pop('dt_s')
    axis=0 if case['geometry']['kind']=='column' else 2
    rows=[r for r in result['curves'] if r['time_s']>.011]
    crossings=[]
    for a,b in zip(rows,rows[1:]):
        u,v=a['monitor_displacement_m'][axis],b['monitor_displacement_m'][axis]
        if u<0<=v:crossings.append(a['time_s']-u*(b['time_s']-a['time_s'])/(v-u))
    period=statistics.median(b-a for a,b in zip(crossings,crossings[1:])) if len(crossings)>=2 else None
    energies=[r['energy_j'] for r in rows]
    drift=(max(energies)-min(energies))/statistics.mean(energies) if energies and min(energies)>0 else float('inf')
    peak=result['peaks'];location=next(s for s in result['mesh']['steel_samples'] if s['id']==peak['steel_sample_id'])
    provenance=result['provenance'];numerics=provenance['numerics'];n=case['mesh']['n']
    expected_modes=(n//2)**2 if numerics.get('quarter_panel') else (n-1)**2
    return dict(status=process['status'],n=n,dt_s=case['analysis']['dt_s'],duration_s=case['analysis']['duration_s'],
                last_time_s=result['curves'][-1]['time_s'],wall_s=process['wall_s'],physical_identity=fingerprint(physical),
                displacement_m=peak['displacement_m'],steel_abs_pa=peak['steel_abs_pa'],
                displacement_time_s=peak['displacement_time_s'],steel_time_s=peak['steel_time_s'],
                period_s=period,energy_drift=drift,steel_peak_location=location,
                native_steel_checks=result['diagnostics'].get('native_steel_checks'),
                dynamic_modes=result['diagnostics'].get('dynamic_modes'),input_fingerprint=result['input_fingerprint'],
                adapter_identity=provenance.get('adapter_identity'),steel_response_method=provenance.get('steel_response_method'),
                integration_method=provenance.get('integration_method'),expected_dynamic_modes=expected_modes,
                all_dynamic_modes_retained=result['diagnostics'].get('all_dynamic_modes_retained'),
                condensation_residual=result['diagnostics'].get('condensation_residual'))
