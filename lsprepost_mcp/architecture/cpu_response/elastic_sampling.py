"""Exact linear layer recovery from native ShellMITC4 GP section strains.

Only the verified 0/90 degree elastic reference reinforcement is eligible.
Native fiber reads remain the independent check for saved fields and new peaks.
"""
import math
import numpy as np
from .column import node_sample


def read_panel_elastic_sample(ops,model,time_s):
    # ShellMITC4 caches sections. reactions() in node_sample MUST precede strains
    # to refresh stresses to the current nodal state after a one-pass Linear step.
    sample=node_sample(ops,model,time_s)
    layers=[v for v in model['layers'] if v['kind']=='steel']
    if len(layers)!=4 or any(v['axis'] not in ('X','Y') for v in layers):
        raise ValueError('elastic recovery requires four verified orthogonal layers')
    values=np.asarray([ops.eleResponse(e,'strains') for e in range(1,len(model['elements'])+1)],dtype=float)
    if values.shape!=(len(model['elements']),32) or not np.isfinite(values).all():
        raise RuntimeError('missing or nonfinite native ShellMITC4 section strain')
    values=values.reshape(-1,4,8)
    axes=np.asarray([0 if v['axis']=='X' else 1 for v in layers])
    z=np.asarray([v['z'] for v in layers])
    strain=(values[:,:,axes]-z*values[:,:,axes+3]).ravel()
    sample.update(steel_strain=strain.tolist(),steel_stress_pa=(strain*model['steel_e_pa']).tolist())
    return sample


def check_native_steel(ops,model,sample,indices):
    count=0
    for i in indices:
        s=model['steel_samples'][i];args=(s['element'],'material',s['ip'],'fiber',s['layer'])
        sv=ops.eleResponse(*args,'stress');ev=ops.eleResponse(*args,'strain');k=0 if s['axis']=='X' else 1
        if (len(sv)!=5 or len(ev)!=5 or not math.isclose(sv[k],sample['steel_stress_pa'][i],rel_tol=1e-10,abs_tol=.01)
                or not math.isclose(ev[k],sample['steel_strain'][i],rel_tol=1e-10,abs_tol=1e-12)):
            raise RuntimeError(f"native steel mismatch at t={sample['time_s']}, element={s['element']}, ip={s['ip']}, layer={s['layer']}")
        count+=1
    return count
