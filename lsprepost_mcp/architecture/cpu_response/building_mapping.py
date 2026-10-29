"""Separate regularized column/slab reference, with explicit source differences.

No native solver calls. Infill/accessories contribute mass and prescribed load,
not bearing stiffness. Row-lumped eccentric point masses retain total physical
mass, first moments and inertia; every mass slave has one independent master.
"""
from collections import defaultdict,deque
from itertools import product
import math
import numpy as np
from .contracts import fingerprint
from .gravity_mapping import shape_gravity,gravity_dependencies,POLICY


def box_moments(boxes):
    b=np.asarray(boxes,dtype=float).reshape(-1,6);d=b[:,3:]-b[:,:3];v=np.prod(d,axis=1);c=(b[:,:3]+b[:,3:])/2
    second=c[:,:,None]*c[:,None,:]+np.eye(3)[None,:,:]*d[:,None,:]**2/12
    return v,v[:,None]*c,v[:,None,None]*second


def subtract_boxes(boxes,cut):
    b=np.asarray(boxes,dtype=float).reshape(-1,6);cut=np.asarray(cut)
    lo=np.maximum(b[:,:3],cut[:3]);hi=np.minimum(b[:,3:],cut[3:]);hit=np.all(hi-lo>1e-10,axis=1)
    if not hit.any():return b
    result=[b[~hit]];work=b[hit].copy();lo=lo[hit];hi=hi[hit]
    for d in range(3):
        left=work.copy();left[:,d+3]=lo[:,d]
        right=work.copy();right[:,d]=hi[:,d]
        result.extend([left[left[:,d+3]-left[:,d]>1e-10],right[right[:,d+3]-right[:,d]>1e-10]])
        work[:,d]=lo[:,d];work[:,d+3]=hi[:,d]
    return np.concatenate(result)


def moment_points(mass,center,second):
    center=np.asarray(center);cov=np.asarray(second)-np.outer(center,center);cov=(cov+cov.T)/2
    values,vectors=np.linalg.eigh(cov)
    if values.min()<-1e-8:raise ValueError('mass covariance not positive')
    offsets=vectors*np.sqrt(3*np.maximum(values,0))
    points=np.array([center+sign*offsets[:,i] for i in range(3) for sign in (-1,1)])
    return points,np.full(6,mass/6)


def box_points(boxes,density):
    b=np.asarray(boxes).reshape(-1,6);center=(b[:,:3]+b[:,3:])/2;half=(b[:,3:]-b[:,:3])/2
    gp=np.array(list(product((-1/math.sqrt(3),1/math.sqrt(3)),repeat=3)))
    return (center[:,None,:]+half[:,None,:]*gp).reshape(-1,3),np.repeat(np.prod(half*2,axis=1)*density/8,8)


def panel_layers(c,steel_e,concrete_e=30e9,nu=.2):
    b=c['native_bounds_m'];h=b[5]-b[2];mid=(b[5]+b[2])/2;area=(b[3]-b[0])*(b[4]-b[1]);r=c['rebar'].get('slab_rebar')
    if not r or r['oblique_segments']:raise ValueError('original orthogonal plate rebar required')
    grouped=defaultdict(float)
    for line in r['lines']:
        if line['axis'] not in (0,1):raise ValueError('plate rebar direction unsupported')
        grouped[(line['axis'],round(line['coordinates_m'][-1]-mid,8))]+=line['length_m']
    if len(grouped)!=4 or any(sum(k[0]==d for k in grouped)!=2 for d in (0,1)):raise ValueError('four native plate rebar layers required')
    steel=[]
    for (axis,z),length in sorted(grouped.items(),key=lambda kv:kv[0][1]):
        levels=sorted(k[1] for k in grouped if k[0]==axis)
        steel.append(dict(kind='steel',axis='X' if axis==0 else 'Y',z=z,t=math.pi*r['diameter_m']**2/4*length/area,
                          side='bottom' if z==levels[0] else 'top'))
    layers=[];cursor=-h/2
    for s in steel:
        lower=s['z']-s['t']/2
        if lower<cursor-1e-10:raise ValueError('overlapping/outside native plate layers')
        if lower>cursor:
            n=max(1,math.ceil((lower-cursor)/(h/20)))
            for i in range(n):layers.append(dict(kind='concrete',z=cursor+(i+.5)*(lower-cursor)/n,t=(lower-cursor)/n))
        layers.append(s);cursor=s['z']+s['t']/2
    if cursor>h/2:raise ValueError('plate layer outside thickness')
    n=max(1,math.ceil((h/2-cursor)/(h/20)))
    for i in range(n):layers.append(dict(kind='concrete',z=cursor+(i+.5)*(h/2-cursor)/n,t=(h/2-cursor)/n))
    q0=np.array([[1,nu,0],[nu,1,0],[0,0,(1-nu)/2]])*concrete_e/(1-nu*nu);bm=np.zeros((3,3))
    for s in layers:
        q=q0 if s['kind']=='concrete' else np.diag([steel_e if s['axis']=='X' else 0,steel_e if s['axis']=='Y' else 0,0])
        bm+=q*s['t']*s['z']
    return dict(layers=layers,thickness_m=h,steel_e_pa=steel_e,concrete_e_pa=concrete_e,concrete_nu=nu,
                original_rebar_volume_m3=r['volume_m3'],smeared_rebar_volume_m3=area*sum(s['t'] for s in steel),b_norm_n=float(np.linalg.norm(bm)))


def prepare_reference(audit,sealed,*,target_component_id,mesh_size_m=2.5,column_segments=4):
    if not audit.get('native_files_verified') or audit['files']!=sealed['payload']['files'] or audit['template_fingerprint']!=sealed['template_fingerprint'] or fingerprint(sealed['payload'])!=sealed['template_fingerprint']:
        raise ValueError('native/semantic identity mismatch')
    if not .5<=mesh_size_m<=3 or column_segments not in (2,4,8):raise ValueError('reference mesh budget')
    cs=audit['components'];semantic=sealed['payload']['components']
    column_ids=sorted(k for k,c in semantic.items() if c['role']=='column')
    if any(k not in cs for k in column_ids):raise ValueError('missing native column')
    grade=sealed['payload']['geometry_metadata'].get('grade_m',0.)
    top=max(cs[k]['native_bounds_m'][5] for k in column_ids)
    plate_ids=sorted(k for k,c in cs.items() if c['role'] in ('slab','roof') and c['material']=='concrete' and c['native_bounds_m'][5]<=top+1e-8)
    steel_material=audit['materials'].get(9001,audit['materials'].get('9001'))
    es=steel_material['elastic_e_pa'];rho_s=steel_material['density'];rho_c=2400.;ec=30e9
    floors=sorted({round(cs[k]['native_bounds_m'][5],8) for k in plate_ids})
    if len(floors)<2 or abs(floors[0]-grade)>1e-8:raise ValueError('supported floor/base layout required')
    byfloor={f:[k for k in plate_ids if abs(cs[k]['native_bounds_m'][5]-f)<1e-7] for f in floors}
    col_boxes=[];colxy=[];column_sections=[];section_keys={};column_section_map={}
    for k in column_ids:
        s=semantic[k];verts=np.array(s['vertices_m']);lo=verts.min(axis=0);hi=verts.max(axis=0);lo[2]=max(lo[2],grade)
        if len({tuple(p) for p in verts})!=8 or not np.all(hi>lo):raise ValueError('regular design column prism required')
        b,h=round(float(hi[0]-lo[0]),8),round(float(hi[1]-lo[1]),8);x,y=(hi[:2]+lo[:2])/2;colxy.append((round(x,8),round(y,8)));col_boxes.append([*lo,*hi])
        r=cs[k]['rebar'].get('column_longitudinal')
        if not r or r['oblique_segments'] or len(r['lines'])!=4 or any(v['axis']!=2 for v in r['lines']):raise ValueError('four original column longitudinal bars required')
        positions=sorted((round(v['coordinates_m'][0]-x,8),round(v['coordinates_m'][1]-y,8)) for v in r['lines'])
        cover=round(min(min(b/2-abs(p[0]),h/2-abs(p[1])) for p in positions)-r['diameter_m']/2,8)
        if cover<=0:raise ValueError('original column steel outside restored design section')
        profile=dict(geometry=dict(length_m=3.,width_m=float(b),depth_m=float(h)),reinforcement=dict(diameter_m=r['diameter_m'],cover_m=float(cover),count=4),
                     original_bar_positions_m=[list(p) for p in positions],
                     materials=dict(concrete_e_pa=ec,steel_e_pa=es,concrete_nu=.2,concrete_density=rho_c,steel_density=rho_s),mesh=dict(n=column_segments,fibers=10))
        key=fingerprint(profile)
        if key not in section_keys:section_keys[key]=len(column_sections);column_sections.append(profile)
        column_section_map[k]=section_keys[key]
    # Every storey must have the same continuous column axes. No invented beams.
    stacks=defaultdict(set)
    for k,xy in zip(column_ids,colxy):stacks[semantic[k]['level']].add(xy)
    if len(stacks)!=len(floors)-1 or any(s!=next(iter(stacks.values())) for s in stacks.values()):raise ValueError('incomplete column stack')
    nodes=[];node_ids={};elements=[];fixed=set();panels=[];part_section={};floor_elements=defaultdict(list)
    def node(xyz):
        key=tuple(round(float(v),8) for v in xyz)
        if key not in node_ids:node_ids[key]=len(nodes);nodes.append(list(key))
        return node_ids[key]
    for f in floors:
        ids=byfloor[f];rects=[cs[k]['native_bounds_m'] for k in ids]
        cuts=[]
        for d in (0,1):
            seeds=sorted({round(b[d],8) for b in rects}|{round(b[d+3],8) for b in rects}|{xy[d] for xy in colxy})
            values=[]
            for a,b in zip(seeds,seeds[1:]):values.extend(np.linspace(a,b,max(1,math.ceil((b-a)/mesh_size_m))+1).tolist())
            cuts.append(sorted({round(v,8) for v in values}))
        for k,b in zip(ids,rects):
            c=cs[k]
            if c['non_box_cells'] or not math.isclose(c['solid_volume_m3'],c['box_volume_m3'],rel_tol=1e-7):raise ValueError('native plate is not a verified rectangular prism: '+k)
            sec=panel_layers(c,es,ec);si=len(panels);panels.append(sec);part_section[k]=si
            xs=[v for v in cuts[0] if b[0]-1e-7<=v<=b[3]+1e-7];ys=[v for v in cuts[1] if b[1]-1e-7<=v<=b[4]+1e-7];z=(b[2]+b[5])/2
            for y0,y1 in zip(ys,ys[1:]):
                for x0,x1 in zip(xs,xs[1:]):
                    ns=[node([x,y,z]) for x,y in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))]
                    e=dict(kind='panel',nodes=ns,section=si,component_id=k);floor_elements[f].append(len(elements));elements.append(e)
                    if abs(f-grade)<1e-7:fixed.update(ns)
    column_routes=[]
    for k,box,xy in zip(column_ids,col_boxes,colxy):
        level=semantic[k]['level'];low=grade if level==0 else (floors[level]-(cs[byfloor[floors[level]][0]]['native_bounds_m'][5]-cs[byfloor[floors[level]][0]]['native_bounds_m'][2])/2)
        upper=floors[level+1];z=upper-panels[part_section[byfloor[upper][0]]]['thickness_m']/2
        a=node([*xy,low]);bkey=tuple([*xy,round(z,8)])
        if bkey not in node_ids:raise ValueError('column top does not meet a native plate footprint')
        b=node_ids[bkey]
        if level==0:fixed.add(a)
        tags=[a]+[node([*xy,v]) for v in np.linspace(low,z,column_segments+1)[1:-1]]+[b]
        for u,v in zip(tags,tags[1:]):elements.append(dict(kind='column',nodes=[u,v],section=column_section_map[k],component_id=k))
        column_routes.append((k,box,tags))
    nn=len(nodes);coords=np.array(nodes);m0=np.zeros(nn);m1=np.zeros((nn,3));m2=np.zeros((nn,3,3));nodal=np.zeros((nn,6))
    expected=np.zeros(13);changes=[];max_offset=0.;remaining_by_component={};source_ledger={};gravity=np.zeros((nn,6))
    # Precompute each floor's four-node rectangles, preserving holes and separate wings.
    floor_maps={}
    for f,indices in floor_elements.items():
        ns=np.array([elements[i]['nodes'] for i in indices]);p=coords[ns]
        floor_maps[f]=(ns,p[:,0,:2],p[:,2,:2])
    def floor_weights(points,f):
        tags,lo,hi=floor_maps[f];n=len(points);best=np.full(n,np.inf);chosen=np.zeros(n,dtype=int)
        # Each coarse rectangle is tried in a vectorized pass; nearest boundary
        # attachments for nonstructural parts retain their eccentricity explicitly.
        for i,(a,b) in enumerate(zip(lo,hi)):
            q=np.maximum(a,np.minimum(b,points[:,:2]));d=np.sum((q-points[:,:2])**2,axis=1);take=d<best-1e-14;best[take]=d[take];chosen[take]=i
        u=np.maximum(0,np.minimum(1,(points[:,:2]-lo[chosen])/(hi[chosen]-lo[chosen])))
        w=np.column_stack(((1-u[:,0])*(1-u[:,1]),u[:,0]*(1-u[:,1]),u[:,0]*u[:,1],(1-u[:,0])*u[:,1]))
        return tags[chosen],w
    def routes(points,column=None,floor=None):
        if floor is not None:return floor_weights(points,floor)
        if column is not None:
            tags=np.array(column);levels=coords[tags,2];i=np.maximum(0,np.minimum(len(tags)-2,np.searchsorted(levels,points[:,2],side='right')-1))
            t=np.maximum(0,np.minimum(1,(points[:,2]-levels[i])/(levels[i+1]-levels[i])))
            return np.column_stack((tags[i],tags[i+1])),np.column_stack((1-t,t))
        lower=np.maximum(0,np.minimum(len(floors)-2,np.searchsorted(floors,points[:,2],side='right')-1))
        t=np.maximum(0,np.minimum(1,(points[:,2]-np.array(floors)[lower])/(np.array(floors)[lower+1]-np.array(floors)[lower])))
        tags=np.zeros((len(points),8),dtype=int);weights=np.zeros((len(points),8))
        for j,f in enumerate(floors):
            for side in (0,1):
                mask=lower+side==j
                if mask.any():
                    ids,w=floor_weights(points[mask],f);tags[mask,side*4:side*4+4]=ids;weights[mask,side*4:side*4+4]=w*(t[mask,None] if side else 1-t[mask,None])
        return tags,weights
    def add_mass(points,masses,column=None,floor=None,source=None):
        nonlocal max_offset
        if not len(points):return
        expected[0]+=masses.sum();expected[1:4]+=np.sum(masses[:,None]*points,axis=0)
        expected[4:]+=np.einsum('p,pi,pj->ij',masses,points,points).ravel()
        tags,w=routes(points,column,floor);mass=masses[:,None]*w;flat=tags.ravel();weight=mass.ravel();p=np.repeat(points,tags.shape[1],axis=0)
        gravity[:]+=shape_gravity(coords,points,masses,tags,w,2 if column is not None else 4)
        route='own_column_chain_weights' if column is not None else 'own_floor_shape_weights' if floor is not None else 'adjacent_floor_shape_weights'
        record=source_ledger.setdefault(source,dict(mass_kg=0.,first_moment_kg_m=[0.,0.,0.],second_moment_kg_m2=np.zeros((3,3)).tolist(),route=route,master_mass_kg={}))
        record['mass_kg']+=float(masses.sum())
        record['first_moment_kg_m']=(np.asarray(record['first_moment_kg_m'])+np.sum(masses[:,None]*points,axis=0)).tolist()
        record['second_moment_kg_m2']=(np.asarray(record['second_moment_kg_m2'])+np.einsum('p,pi,pj->ij',masses,points,points)).tolist()
        if record['route']!=route:record['route']='mixed_explicit_source_routes'
        master_mass=np.bincount(flat,weights=weight,minlength=nn)
        for master in np.flatnonzero(master_mass>0):
            amount=float(master_mass[master])
            if amount>0:record['master_mass_kg'][str(master)]=record['master_mass_kg'].get(str(master),0.)+amount
        np.add.at(m0,flat,weight);np.add.at(m1,flat,weight[:,None]*p)
        np.add.at(m2,flat,weight[:,None,None]*p[:,:,None]*p[:,None,:])
        positive=weight>0
        if positive.any():max_offset=max(max_offset,float(np.max(np.linalg.norm(p[positive]-coords[flat[positive]],axis=1))))
    column_chain={k:tags for k,box,tags in column_routes}
    for k,c in cs.items():
        own_floor=round(c['native_bounds_m'][5],8) if k in part_section else None
        boxes=np.array(c['cell_bounds_m']).reshape(-1,6);b=np.array(c['native_bounds_m']);hits=[cut for cut in col_boxes if np.all(np.minimum(b[3:],cut[3:])-np.maximum(b[:3],cut[:3])>1e-10)]
        if c['non_box_cells']:
            if hits:raise ValueError('oblique native component intersects restored column: '+k)
            points,mass=moment_points(c['solid_volume_m3']*c['host_density_kg_m3'],c['solid_centroid_m'],c['solid_second_m2']);add_mass(points,mass,source=k)
            remaining_by_component[k]=None
        else:
            before=float(np.prod(boxes[:,3:]-boxes[:,:3],axis=1).sum())
            for cut in hits:boxes=subtract_boxes(boxes,cut)
            after=float(np.prod(boxes[:,3:]-boxes[:,:3],axis=1).sum())
            if before-after>1e-10:changes.append(dict(component_id=k,removed_volume_m3=before-after,old_density_kg_m3=c['host_density_kg_m3']))
            remaining_by_component[k]=boxes
            if len(boxes):add_mass(*box_points(boxes,c['host_density_kg_m3']),floor=own_floor,source=k)
        for r in c['rebar'].values():
            delta=r['volume_m3']*(rho_s-c['host_density_kg_m3']);add_mass(*moment_points(delta,r['centroid_m'],r['second_m2']),column=column_chain.get(k),floor=own_floor,source=k)
    for k,box,tags in column_routes:add_mass(*box_points([box],rho_c),column=tags,source=k)
    for group_id,group in audit['assembly_rebar'].items():
        host=cs[group['members'][0]]['host_density_kg_m3']
        for r in group['rebar'].values():add_mass(*moment_points(r['volume_m3']*(rho_s-host),r['centroid_m'],r['second_m2']),source='assembly:'+str(group_id))
    # Uniform pressure on the verified native component's south exterior plane.
    target=cs[target_component_id];boxes=remaining_by_component[target_component_id]
    if boxes is None or target['role'] not in ('wall','partition','shaft'):raise ValueError('first trial requires an axis-aligned infill south face')
    plane=target['native_bounds_m'][1];faces=boxes[np.abs(boxes[:,1]-plane)<1e-8];gauss=(-1/math.sqrt(3),1/math.sqrt(3));force=np.zeros(3);moment=np.zeros(3);area=0.
    level=target['level']
    if type(level) is not int or not 0<=level<len(floors)-1:raise ValueError('wall support storey required')
    support_floors=[floors[level],floors[level+1]]
    support_z=[support_floors[0],cs[byfloor[support_floors[1]][0]]['native_bounds_m'][2]]
    if target['native_bounds_m'][2]<support_z[0]-1e-8 or target['native_bounds_m'][5]>support_z[1]+1e-8:raise ValueError('wall extends beyond clear support span')
    edge_loads=np.zeros((2,nn,6))
    for face in faces:
        for gx,gz in product(gauss,repeat=2):
            point=np.array([[(face[0]+face[3])/2+gx*(face[3]-face[0])/2,plane,(face[2]+face[5])/2+gz*(face[5]-face[2])/2]])
            df=np.array([0.,(face[3]-face[0])*(face[5]-face[2])/4,0.]);t=(point[0,2]-support_z[0])/(support_z[1]-support_z[0])
            for side,f in enumerate(support_floors):
                ids,w=floor_weights(point,f);projected=np.sum(coords[ids[0],:2]*w[0,:,None],axis=0)
                for tag,weight in zip(ids[0],w[0]*(t if side else 1-t)):
                    # First resolve simply supported strip reactions, THEN use
                    # only support-plane -> shell-middle-surface eccentricity.
                    offset=np.r_[point[0,:2]-projected,support_z[side]-coords[tag,2]]
                    edge_loads[side,tag,:3]+=weight*df;edge_loads[side,tag,3:]+=weight*np.cross(offset,df)
            force+=df;moment+=np.cross(point[0],df);area+=df[1]
    nodal=edge_loads.sum(axis=0)
    if not area>0:raise ValueError('empty reference pressure face')
    mass_points=[]
    for i,m in enumerate(m0):
        if m<=0:continue
        points,masses=moment_points(m,m1[i]/m,m2[i]/m)
        for p,v in zip(points,masses):mass_points.append(dict(master=i,position_m=p.tolist(),mass_kg=float(v)))
    point_mass=np.array([p['mass_kg'] for p in mass_points]);point_x=np.array([p['position_m'] for p in mass_points]);actual=np.r_[point_mass.sum(),(point_mass[:,None]*point_x).sum(axis=0),np.einsum('p,pi,pj->ij',point_mass,point_x,point_x).ravel()]
    errors=[float(np.linalg.norm(actual[s]-expected[s])/max(1,np.linalg.norm(expected[s]))) for s in (slice(0,1),slice(1,4),slice(4,13))]
    graph=defaultdict(set)
    for e in elements:
        for n in e['nodes']:graph[n].update(e['nodes'])
    seen=set(fixed);queue=deque(fixed)
    while queue:
        for n in graph[queue.popleft()]-seen:seen.add(n);queue.append(n)
    checks=dict(connected_to_fixed_base=len(seen)==len(nodes),column_stacks_complete=True,mass_moments_conserved=max(errors)<1e-9,
                pressure_resultant_conserved=bool(np.allclose(nodal[:,:3].sum(axis=0),force,rtol=1e-10,atol=1e-8)),
                pressure_moment_conserved=bool(np.allclose((np.cross(coords,nodal[:,:3])+nodal[:,3:]).sum(axis=0),moment,rtol=1e-10,atol=1e-8)))
    checks['ready_for_trial']=all(checks.values())
    if not checks['ready_for_trial']:raise ValueError('reference connectivity/mass/load gate failed: '+str(checks))
    identity=fingerprint(dict(template=sealed['template_fingerprint'],policy='restore_design_column_priority@1',mesh_size_m=mesh_size_m,column_segments=column_segments))
    case=dict(schema_version='cpu-response.building-case@1',source=dict(kind='regularized_building_reference',id=sealed['template_id'],revision=1,fingerprint=identity),
        template_fingerprint=sealed['template_fingerprint'],native_files=audit['files'],nodes=nodes,elements=elements,fixed_nodes=sorted(fixed),mass_points=mass_points,
        column_sections=column_sections,panel_sections=panels,nodal_load_per_pa=nodal.tolist(),checks=checks,
        mass_ledger=dict(total_kg=float(expected[0]),first_moment_kg_m=expected[1:4].tolist(),second_moment_kg_m2=expected[4:].reshape(3,3).tolist(),
            mass_relative_error=errors[0],first_moment_relative_error=errors[1],second_moment_relative_error=errors[2],
            source_ledger=source_ledger,fixed_mass_kg=sum(p['mass_kg'] for p in mass_points if p['master'] in fixed),restored_column_volume_m3=float(box_moments(col_boxes)[0].sum()),
            removed_source_volume_m3=sum(c['removed_volume_m3'] for c in changes),source_changes=changes,max_mass_eccentricity_m=max_offset),
        loads=dict(target_component_id=target_component_id,face='south',area_m2=area,resultant_per_pa=force.tolist(),moment_per_pa_nm=moment.tolist(),
                   curve_si=[[0,0],[.001,10000],[.01,0],[.15,0]],scope='prescribed_single_component_surface_not_air_blast',
                   support_edges=[dict(floor_z=f,support_z=support_z[i],force_per_pa=edge_loads[i,:,:3].sum(axis=0).tolist(),
                       couples_per_pa_nm=edge_loads[i,:,3:].sum(axis=0).tolist()) for i,f in enumerate(support_floors)]),
        analysis=dict(duration_s=.15,dt_s=.0001,damping=0),budget=dict(wall_s=180,max_steps=10000,frames=30,samples=5000),
        assumptions=['separate_regularized_reference_original_K_unchanged','restored_design_columns_take_volume_from_original_owners',
            'flexible_shell_no_global_rigid_floor','monolithic_column_axes_meet_shell_midsurfaces_joint_zone_idealization',
            'infill_and_accessories_mass_and_load_only_no_stiffness','overrun_and_stairs_are_attached_mass_not_bearing_elements',
            'positive_eccentric_row_lumped_mass_retains_rigid_body_inertia','elastic_Ec_30GPa_reference_native_Es_and_rebar_positions',
            'native_asymmetric_plate_rebar_membrane_bending_coupling_retained','fixed_ground_floor_and_column_bases_no_soil_or_gravity',
            'trial_mesh_not_converged_whole_building_accuracy'])
    case['loads']['gravity_mapping']=dict(policy=POLICY,gravity_m_s2=9.80665,nodal_wrenches_n_nm=gravity.tolist(),dependencies=gravity_dependencies(case),
        scope='static_gravity_only_legacy_dynamic_eccentric_mass_requires_separate_validation')
    expected_force=np.array([0.,0.,-9.80665*expected[0]])
    expected_moment=np.cross(expected[1:4],np.array([0.,0.,-9.80665]))
    case['checks']['gravity_virtual_work_resultants_conserved']=bool(
        np.allclose(gravity[:,:3].sum(0),expected_force,rtol=1e-10,atol=1e-7) and
        np.allclose((np.cross(coords,gravity[:,:3])+gravity[:,3:]).sum(0),expected_moment,rtol=1e-10,atol=1e-7))
    if not case['checks']['gravity_virtual_work_resultants_conserved']:raise ValueError('重力合力或力矩不守恒')
    return case
