"""Resolve requests to actual pure AIR cells or physical solid nodes/elements."""
import numpy as np


def resolve_blast_monitors(template,derived,plan,fractions,requests):
    g=derived['geometry'];result=[]
    for req in requests:
        position=np.asarray(req['position_m'],float);kind=req['kind'];r=dict(id=req['id'],kind=kind,requested_position_m=position.tolist())
        if kind=='air_pressure':
            axes=[np.asarray(a) for a in plan['axes']]
            if any(p<a[0] or p>=a[-1] for p,a in zip(position,axes)):raise ValueError('air monitor outside grid')
            i,j,k=[int(np.searchsorted(a,p,side='right'))-1 for p,a in zip(position,axes)]
            nx,ny=len(axes[0])-1,len(axes[1])-1;offset=(k*ny+j)*nx+i
            vf=np.asarray(fractions[offset])
            if not np.all(np.isfinite(vf)) or vf[0]<1-1e-8 or np.any(vf[1:]>1e-8) or np.any(vf<0):
                raise ValueError('air pressure monitor must be in a pure air cell')
            sample=[float((a[n]+a[n+1])/2) for a,n in zip(axes,(i,j,k))]
            r.update(element_id=plan['element_start']+offset,initial_fractions=dict(zip(('air','tnt','vacuum'),map(float,vf))),
                     output='elout: hydrostatic pressure; compression positive')
        else:
            if kind=='ground_node':xyz=g['ground_nodes'];elements=g['ground_elements']
            elif kind in ('structure_node','solid_stress'):xyz=g['building_nodes'];elements=g['building_elements']
            else:raise ValueError('unknown monitor kind')
            levels={room['level'] for room in template['rooms'].values() if all(room['bounds_m'][i]-1e-9<=position[i]<=room['bounds_m'][i+3]+1e-9 for i in range(3))}
            if levels and kind!='ground_node':
                pids={c['part_id'] for c in derived['components'].values() if c.get('level') in levels}
                elements=elements[np.isin(elements[:,1],list(pids))]
            if kind=='solid_stress':
                choices=[(int(e[0]),np.mean([xyz[int(n)] for n in e[2:]],axis=0)) for e in elements]
            else:choices=[(n,np.asarray(xyz[n])) for n in sorted(set(map(int,elements[:,2:].ravel())))]
            choices=[(n,p) for n,p in choices if abs(p[2]-position[2])<=1.55]
            if not choices:raise ValueError('no physical monitor candidate on requested floor')
            n,p=min(choices,key=lambda row:(float(np.linalg.norm(row[1]-position)),row[0]))
            if np.linalg.norm(p-position)>2:raise ValueError('no nearby physical monitor candidate on requested floor')
            sample=list(map(float,p));r['element_id' if kind=='solid_stress' else 'node_id']=n
        r.update(sample_position_m=sample,offset_m=(np.asarray(sample)-position).tolist());result.append(r)
    return result
