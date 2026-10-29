"""Observe the actual 3D state hidden by the native PlateFiber adapter.

This gate detects an unresolved native condensation defect; it does NOT repair
the native scalar Newton loop or certify its finite-difference tangent.
"""
import numpy as np


def plane_stress_passed(report):
    value=report.get('max_abs_sigma33_pa',float('inf'))
    return isinstance(value,(int,float)) and report.get('status')=='passed' and report.get('tolerance_pa')==1e-8 and np.isfinite(value) and 0<=value<=1e-8


def plane_stress_diagnostics(ops,model):
    worst=None;peak=0.;count=0
    for tag,profile in model['panels']:
        for ip in range(1,5):
            for li,layer in enumerate(profile['layers'],1):
                if layer['kind']!='concrete':continue
                args=(tag,'material',ip,'fiber',li,'material',1)
                stress=np.asarray(ops.eleResponse(*args,'stress'))
                if stress.shape!=(6,) or not np.isfinite(stress).all():
                    raise ValueError(f'missing full concrete stress at e{tag}/ip{ip}/layer{li}')
                count+=1;value=abs(float(stress[2]))
                if worst is None or value>peak:
                    peak=value;worst=dict(element_tag=tag,component_id=model['case']['elements'][tag-1]['component_id'],ip=ip,layer=li,z_m=layer['z'],sigma33_pa=float(stress[2]),stress_3d_pa=stress.tolist())
    return dict(status='passed' if peak<=1e-8 else 'failed',max_abs_sigma33_pa=peak,tolerance_pa=1e-8,samples=count,worst=worst,
        tangent_scope='native_finite_difference_matrix_branch_consistency_not_certified_by_sigma33_gate')
