"""Read-only failed-state transfer audit and a TWO-SHELL boundary micro-test.

No whole assembly, self-weight solve, TNT load or invented boundary averaging.
Native material history is fresh: macro cohesive histories have no exact FE
material counterpart and must not be relabelled as transferred native damage.
"""
from copy import deepcopy
import math
import time
import numpy as np
from .contracts import fingerprint
from .native_reference import build_nonlinear_reference,configure_static,read_fields,check_small_tangent


def recorded_node_pose(reference,saved,state,element,node):
    i=saved['metadata']['body_source_indices'].index(element);body=saved['model']['bodies'][i]
    x0=np.asarray(body['center_m']);p=np.asarray(reference['nodes'][node]);data=saved['states'][state]['state']
    R=np.asarray(data['R'][i]);translation=np.asarray(data['x'][i])+R@(p-x0)-p
    angle=math.acos(np.clip((np.trace(R)-1)/2,-1,1))
    vector=np.array([R[2,1]-R[1,2],R[0,2]-R[2,0],R[1,0]-R[0,1]])*(.5 if angle<1e-8 else angle/(2*math.sin(angle)))
    return np.r_[translation,vector]


def audit_boundary_compatibility(reference,saved):
    elements=saved['metadata']['boundary_source_indices'];nodes=sorted({n for i in elements for n in reference['elements'][i]['nodes']});states={}
    for state in saved['states']:
        conflicts=[]
        for n in nodes:
            owners=[i for i in elements if n in reference['elements'][i]['nodes']]
            traces=np.array([recorded_node_pose(reference,saved,state,i,n) for i in owners]);difference=traces-traces[0]
            du=float(np.linalg.norm(difference[:,:3],axis=1).max());dr=float(np.linalg.norm(difference[:,3:],axis=1).max())
            if du>1e-8 or dr>1e-8:conflicts.append(dict(reference_node=n,source_elements=owners,translation_mismatch_m=du,rotation_mismatch_rad=dr,traces=traces.tolist()))
        states[state]=dict(conflicting_nodes=conflicts)
    return dict(scope='13_ELEMENT_BOUNDARY_TRACE_COMPATIBILITY_ONLY',boundary_node_count=len(nodes),states=states,
        direct_transfer_compatible=not any(v['conflicting_nodes'] for v in states.values()),
        policy='reject_incompatible_shared_node_traces_no_averaging_no_arbitrary_zero_fixity',
        limitation='different mechanical DOFs and histories: no exact macro-to-FE checkpoint transfer')


def two_panel_patch(reference,saved,state):
    selected=[197,208];case=deepcopy(reference);elements=[deepcopy(reference['elements'][i]) for i in selected]
    nodes=sorted({n for e in elements for n in e['nodes']});mapping={n:i for i,n in enumerate(nodes)}
    shared=set(elements[0]['nodes'])&set(elements[1]['nodes']);traces={}
    for original,e in zip(selected,elements):
        for n in set(e['nodes'])-shared:traces[mapping[n]]=recorded_node_pose(reference,saved,state,original,n).tolist()
        e['nodes']=[mapping[n] for n in e['nodes']]
    masses=[dict(p,master=mapping[p['master']]) for p in reference['mass_points'] if p['master'] in mapping]
    case.update(nodes=[reference['nodes'][n] for n in nodes],elements=elements,fixed_nodes=sorted(traces),mass_points=masses,
        nodal_load_per_pa=np.zeros((len(nodes),6)).tolist())
    case['mass_ledger']=dict(total_kg=sum(p['mass_kg'] for p in masses))
    case['source']=dict(case['source'],id='original-failed-junction-two-shells',fingerprint=fingerprint(dict(elements=elements,nodes=case['nodes'],state=state)))
    return dict(case=case,traces=traces,reference_elements=selected,reference_nodes=nodes,parent_state=state,
        parent_load_factor=saved['states'][state]['load_factor'],
        limitations=['two_shells_only_original_recorded_outer_boundaries_shared_edge_free',
            'fresh_native_material_history_not_a_replay_of_macro_damage',
            'no_gravity_or_TNT_applied_in_this_boundary_test',
            'subset_reference_nodal_masses_include_cut_away_sources_not_used_in_this_static_test',
            'not_a_13_element_cutout_or_whole_building_capacity_acceptance'])


def solve_recorded_boundary(ops,patch):
    start=time.monotonic();model=build_nonlinear_reference(ops,patch['case'])
    ops.timeSeries('Linear',98002);ops.pattern('Plain',98002,98002)
    for n,v in patch['traces'].items():
        for d,value in enumerate(v,1):ops.remove('sp',n+1,d);ops.sp(n+1,d,value)
    configure_static(ops,.1,1e-7)
    for _ in range(10):
        if time.monotonic()-start>5:raise TimeoutError('two-shell micro-test deadline')
        if ops.analyze(1)!=0:raise RuntimeError('two-shell recorded-boundary test failed')
    fields=read_fields(ops,model);internal=np.zeros((len(model['nodes']),6))
    for i,e in enumerate(model['case']['elements'],1):np.add.at(internal,e['nodes'],np.array(ops.eleForce(i)).reshape(-1,6))
    boundary=list(patch['traces']);free=[n for n in range(len(internal)) if n not in boundary]
    force_scale=max(1.,float(np.linalg.norm(internal[boundary,:3])))
    ell=model['node_residual_length_m'][free]
    residual=math.sqrt(float(np.sum(internal[free,:3]**2)+np.sum((internal[free,3:]/ell[:,None])**2)))/force_scale
    K=np.array(ops.printA('-ret')).reshape(ops.systemSize(),ops.systemSize());stability=check_small_tangent(K,lambda:None)
    error=max(float(np.max(np.abs(np.array(ops.nodeDisp(n+1))-v))) for n,v in patch['traces'].items())
    if residual>1e-5 or stability['status']!='positive_definite' or error>1e-10:raise RuntimeError('two-shell independent acceptance failed')
    return dict(status='completed',scope='TWO_ORIGINAL_SHELLS_RECORDED_BOUNDARY_ONLY',reference_elements=patch['reference_elements'],
        parent_state=patch['parent_state'],parent_load_factor=patch['parent_load_factor'],max_boundary_error=error,
        actual_relative_residual=residual,stability=stability,fields=fields,wall_s=time.monotonic()-start,
        full_gravity_acceptance=False,blast_applied=False,limitations=patch['limitations'],assumptions=model['assumptions'])
