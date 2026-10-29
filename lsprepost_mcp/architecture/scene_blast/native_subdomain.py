"""Consistent FE subdomain traces from the SAME equilibrated native parent.

No old macro displacement transfer, boundary averaging, added fixities, native
history recreation or second structural solve. Static subdomain loads are the
parent's exact nodal gravity (including attached sources), not volume fractions.
"""
import math
from collections import Counter
import numpy as np
from .contracts import fingerprint
from .native_reference import actual_balance,check_small_tangent,pdelta_geometric_moment
from .native_plane_stress import plane_stress_diagnostics,plane_stress_passed


def partition(case,indices):
    if not indices or any(type(i) is not int or not 0<=i<len(case['elements']) for i in indices) or len(set(indices))!=len(indices):
        raise ValueError('子域单元索引为空、重复或越界')
    selected=set(indices);incidence=[set() for _ in case['nodes']]
    for i,e in enumerate(case['elements']):
        for n in e['nodes']:incidence[n].add(i)
    nodes=sorted({n for i in indices for n in case['elements'][i]['nodes']})
    graph={i:set() for i in indices}
    for n in nodes:
        for i in incidence[n]&selected:graph[i].update(incidence[n]&selected)
    seen={indices[0]};pending=list(seen)
    while pending:
        for i in graph[pending.pop()]-seen:seen.add(i);pending.append(i)
    if seen!=selected:raise ValueError('子域单元没有相连的承载路径')
    fixed=set(case['fixed_nodes']);boundary=[n for n in nodes if incidence[n]-selected or n in fixed]
    interior=sorted(set(nodes)-set(boundary))
    if not boundary or not interior:raise ValueError('子域缺少实际父模型边界或内部自由节点')
    return dict(elements=sorted(indices),nodes=nodes,boundary_nodes=boundary,interior_nodes=interior,
        element_counts=dict(Counter(case['elements'][i]['kind'] for i in indices)),
        outside_incidence={str(n):sorted(incidence[n]-selected) for n in boundary})


def require_equilibrated_parent(report):
    values=[report.get(k,float('inf')) for k in ('actual_relative_residual','force_balance_relative_error','moment_balance_relative_error')]
    if report.get('status')!='completed' or report.get('accepted_load_factor')!=1. or not all(math.isfinite(v) and v<=1e-5 for v in values) or report.get('stability',{}).get('status')!='positive_definite':
        raise ValueError('父模型未通过100%自重及物理平衡验收，不能发布一致边界')
    if not plane_stress_passed(report.get('plane_stress',{})):raise ValueError('父模型缺少合格的厚度方向材料平衡证据')


def material_states(ops,model,indices):
    result={};columns={tag:items for tag,p,items in model['columns']}
    for i in indices:
        e=model['case']['elements'][i];tag=i+1;entry=dict(component_id=e['component_id'],kind=e['kind'],resisting_force=ops.eleForce(tag))
        if e['kind']=='panel':
            profile=model['case']['panel_sections'][e['section']];states=[]
            for ip in range(1,5):
                layers=[]
                for li,layer in enumerate(profile['layers'],1):
                    args=(tag,'material',ip,'fiber',li);s=ops.eleResponse(*args,'stress');strain=ops.eleResponse(*args,'strain')
                    if len(s)!=5 or len(strain)!=5:raise ValueError('父壳材料状态缺失')
                    item=dict(layer=li,kind=layer['kind'],z_m=layer['z'],stress_pa=s,strain=strain)
                    if layer['kind']=='concrete':
                        d=ops.eleResponse(*args,'material',1,'damage');plastic=ops.eleResponse(*args,'material',1,'equivalentPlasticStrain')
                        if len(d)!=2 or len(plastic)!=2:raise ValueError('父壳非线性历史响应缺失')
                        item.update(damage=d,equivalent_plastic_strain=plastic)
                    else:item['axis']=layer['axis']
                    layers.append(item)
                states.append(dict(ip=ip,layers=layers))
            entry['integration_points']=states
        else:
            states=[]
            for ip in range(1,len(columns[tag])+1):
                fibers=ops.eleResponse(tag,'section',ip,'fiberData')
                if not fibers or len(fibers)%5:raise ValueError('父柱原生纤维状态缺失')
                states.append(dict(ip=ip,fiber_y_z_area_stress_strain=fibers,
                    force=ops.eleResponse(tag,'section',ip,'force'),deformation=ops.eleResponse(tag,'section',ip,'deformation')))
            entry['integration_points']=states
        result[str(i)]=entry
    return result


def extract_and_verify(ops,model,parent,indices,*,check=lambda:None):
    require_equilibrated_parent(parent);check();case=model['case'];p=partition(case,indices)
    if parent.get('case_fingerprint')!=fingerprint(case):raise ValueError('父模型输入身份不一致')
    dofs=np.asarray([ops.nodeDisp(i+1) for i in range(len(case['nodes']))]);baseline=parent['last_accepted_fields']
    expected=np.c_[baseline['displacements_m'],baseline['rotations_rad']]
    if not np.isfinite(dofs).all() or not np.allclose(dofs,expected,rtol=0,atol=1e-12):raise ValueError('父模型位姿已改变，禁止使用过期边界')
    live=actual_balance(ops,model,1.)
    require_equilibrated_parent(dict(live,status='completed',accepted_load_factor=1.,stability=parent['stability'],plane_stress=plane_stress_diagnostics(ops,model)))
    all_internal=np.zeros_like(model['gravity']);local=np.zeros_like(all_internal);selected=set(indices)
    for i,e in enumerate(case['elements']):
        check();f=np.asarray(ops.eleForce(i+1)).reshape(-1,6);np.add.at(all_internal,e['nodes'],f)
        if i in selected:np.add.at(local,e['nodes'],f)
    outside=all_internal-local;inside=p['interior_nodes'];boundary=p['boundary_nodes'];nodes=p['nodes']
    gravity=model['gravity'];ell=model['node_residual_length_m']
    norm=lambda w,ids:math.sqrt(float(np.sum(w[ids,:3]**2)+np.sum((w[ids,3:]/ell[ids,None])**2)))
    residual=local-gravity;weight=max(1.,float(np.linalg.norm(gravity[inside,:3])))
    relative=norm(residual,inside)/weight
    reaction=np.zeros_like(local);reaction[boundary]=residual[boundary]
    parent_support=np.zeros_like(local);fixed=case['fixed_nodes'];parent_support[fixed]=all_internal[fixed]-gravity[fixed]
    cut_residual=reaction+outside-parent_support;cut_scale=max(1.,norm(outside,boundary),norm(gravity,boundary),norm(parent_support,boundary))
    interface=norm(cut_residual,boundary)/cut_scale
    external=gravity[nodes]+reaction[nodes];center=model['nodes'][nodes].mean(0)
    net=external[:,:3].sum(0);moment=(np.cross(model['nodes'][nodes]-center,external[:,:3])+external[:,3:]).sum(0)
    total=max(1.,float(np.linalg.norm(gravity[nodes,:3].sum(0))))
    radius=max(1.,float(np.ptp(model['nodes'][nodes],axis=0).max()))
    geometric=pdelta_geometric_moment(ops,model,indices);corrected=moment-geometric
    force_error=float(np.linalg.norm(net)/total);moment_error=float(np.linalg.norm(corrected)/(total*radius))
    # Interior nodes have no outside incident element. The corresponding parent
    # tangent principal block is therefore exactly the local Dirichlet tangent.
    # Native mass slaves contribute no stiffness in this static analysis.
    eq=np.asarray([ops.nodeDOFs(n+1) for n in inside],dtype=int).ravel()
    if np.any(eq<0) or len(set(eq))!=len(eq):raise ValueError('内部自由度不是独立父模型自由度')
    n=ops.systemSize();K=np.asarray(ops.printA('-ret')).reshape(n,n)
    stability=check_small_tangent(K[np.ix_(eq,eq)],check)
    states=material_states(ops,model,indices)
    plane=plane_stress_diagnostics(ops,model)
    if not plane_stress_passed(plane):raise ValueError('子域提取后原生材料厚度方向平衡不合格')
    result=dict(schema_version='scene-native-subdomain@1',status='completed',parent_case_fingerprint=fingerprint(case),**p,
        parent_source=case['source'],parent_load_factor=1.,boundary_owner='single_native_parent_node_no_averaging',
        boundary=[dict(parent_node=n,dofs=dofs[n].tolist(),dirichlet_reaction_n_nm=reaction[n].tolist(),
            outside_resisting_wrench_n_nm=outside[n].tolist(),parent_support_reaction_n_nm=parent_support[n].tolist()) for n in boundary],
        nodal_dofs=dofs[nodes].tolist(),nodal_gravity_n_nm=gravity[nodes].tolist(),
        actual_relative_residual=relative,interface_relative_residual=interface,
        force_balance_relative_error=force_error,moment_balance_relative_error=moment_error,
        net_force_n=net.tolist(),net_moment_nm=corrected.tolist(),raw_initial_net_moment_nm=moment.tolist(),
        pdelta_geometric_moment_nm=geometric.tolist(),stability=stability,plane_stress=plane,
        material_state_source='same_live_native_parent_domain_no_history_reinitialization',
        material_states=states,assumptions=model['assumptions'],blast_applied=False,
        scope='static_subdomain_equilibrium_in_full_parent_not_an_independent_dynamic_collapse_model',
        mass_scope='exact_parent_nodal_gravity_including_attached_mass_sources_no_new_mass_split')
    if max(relative,interface,force_error,moment_error)>1e-5 or stability['status']!='positive_definite':
        result['status']='failed';exc=ValueError('子域平衡/反力/力矩/物理切线验收失败');exc.diagnostics=result;raise exc
    return result
