"""Physical, provenance-preserving source packets for mapping validation.

The caller must identify the bearing component BEFORE nodal aggregation. A packet
is assigned spatially within that component, never spread over all incident slab
and column blocks. Empty cells and point-mass inertia are reported, not padded.
This is not an automatic repair of the existing frozen scene input.
"""
import numpy as np


def map_source_packets(bodies,packets):
    candidates={}
    for i,b in enumerate(bodies):candidates.setdefault(b['component_id'],[]).append(i)
    n=len(bodies);mass=np.zeros(n);first=np.zeros((n,3));second=np.zeros((n,3,3))
    source_sets=[set() for _ in bodies];sources={};ledger_mass=0.;ledger_first=np.zeros(3);ledger_second=np.zeros((3,3))
    centers=[];axes=[];halves=[]
    for b in bodies:
        vertices=np.asarray(b['vertices_m'],dtype=float)
        edges=vertices[[1,3,4]]-vertices[0];lengths=np.linalg.norm(edges,axis=1)
        if np.any(lengths<=0):raise ValueError('质量映射需要非退化矩形单元')
        basis=edges/lengths[:,None]
        if not np.allclose(basis@basis.T,np.eye(3),atol=1e-9):raise ValueError('质量映射需要正交矩形单元')
        centers.append(vertices.mean(axis=0));axes.append(basis);halves.append(lengths/2)
    centers=np.asarray(centers);axes=np.asarray(axes);halves=np.asarray(halves)
    for packet in packets:
        source=packet['source_component'];bearing=packet['bearing_component']
        if bearing not in candidates:raise ValueError('质量来源没有明确的承重构件：'+str(bearing))
        m=float(packet['mass_kg']);p=np.asarray(packet['position_m'],dtype=float)
        if m<=0 or not np.isfinite(m) or p.shape!=(3,) or not np.isfinite(p).all():raise ValueError('质量包必须是有限正质量和三维位置')
        ids=np.asarray(candidates[bearing]);local=np.einsum('nij,nj->ni',axes[ids],p-centers[ids])
        distance=np.linalg.norm(np.maximum(np.abs(local)-halves[ids],0),axis=1);i=int(ids[int(distance.argmin())])
        # Candidate order is deterministic at an exact physical boundary. Packet
        # generation should use interior quadrature, not arbitrary nodal spreading.
        mass[i]+=m;first[i]+=m*p;second[i]+=m*np.outer(p,p);source_sets[i].add(source)
        record=sources.setdefault(source,dict(mass_kg=0.,bearing_components=set(),packet_count=0))
        record['mass_kg']+=m;record['bearing_components'].add(bearing);record['packet_count']+=1
        ledger_mass+=m;ledger_first+=m*p;ledger_second+=m*np.outer(p,p)
    mapped=[];empty=[]
    for i,b in enumerate(bodies):
        if mass[i]:
            center=first[i]/mass[i];cov=second[i]-mass[i]*np.outer(center,center)
            cov=(cov+cov.T)/2;inertia=np.trace(cov)*np.eye(3)-cov
            positive=bool(np.linalg.eigvalsh(inertia).min()>0)
        else:center=np.zeros(3);inertia=np.zeros((3,3));positive=False;empty.append(b['id'])
        mapped.append(dict(body_id=b['id'],mass_kg=float(mass[i]),center_m=center.tolist(),
            inertia_kg_m2=inertia.tolist(),inertia_positive=positive,source_components=sorted(source_sets[i])))
    for item in sources.values():item['bearing_components']=sorted(item['bearing_components'])
    return dict(bodies=mapped,unsupported_massless_bodies=empty,
        ledger=dict(mass_kg=ledger_mass,first_moment_kg_m=ledger_first.tolist(),
            second_moment_kg_m2=ledger_second.tolist(),source_components=sources),
        policy='physical_source_packet_with_explicit_bearing_component_before_nodal_aggregation')
