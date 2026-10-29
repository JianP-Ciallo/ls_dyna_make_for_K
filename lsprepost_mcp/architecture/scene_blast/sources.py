"""Bounded CPU/display adapters. Never build an ALE mesh or invoke an FE solver."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import zipfile

try:import numpy as np
except ImportError:np=None  # Other workbenches/catalog remain available without this runtime.

from .contracts import KINDS, LIMITS, MATERIAL, fingerprint

ROOT=Path(__file__).resolve().parents[3]
LABELS=('商超','住宅小区','地铁入口','城市街道','我的三层建筑')
FACES=((0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7))


def catalog():
    return [dict(id=k,label=v,system='柱板承重，填充墙仅质量与传压' if k=='fixed_three_storey' else '既有粗壳几何的承重壳参考模型') for k,v in zip(KINDS,LABELS)]


def corners(lo,hi):
    x,y,z=lo;X,Y,Z=hi
    return np.array([[x,y,z],[X,y,z],[X,Y,z],[x,Y,z],[x,y,Z],[X,y,Z],[X,Y,Z],[x,Y,Z]])


def body_from_quad(cid,points,thickness):
    p=np.asarray(points,dtype=float);u=p[1]-p[0];v=p[3]-p[0]
    l=np.linalg.norm(u);w=np.linalg.norm(v);u/=l;v/=w;n=np.cross(u,v);n/=np.linalg.norm(n)
    if abs(u@v)>1e-6:raise ValueError('首版只支持正交粗壳单元')
    center=p.mean(axis=0);basis=np.stack([u,v,n],axis=1);dims=np.array([l,w,thickness])
    mass=l*w*thickness*MATERIAL['density_kg_m3'];principal=mass/12*(sum(dims**2)-dims**2)
    vertices=np.vstack([p-.5*thickness*n,p+.5*thickness*n])
    return dict(id=cid,component_id=cid.rsplit(':',1)[0],center_m=center.tolist(),mass_kg=mass,
                inertia_kg_m2=(basis@np.diag(principal)@basis.T).tolist(),vertices_m=vertices.tolist(),
                quad_m=p.tolist(),thickness_m=thickness,fixed=bool(np.max(np.abs(p[:,2]))<1e-7),role='shell')


def add_interface(model,a,b,point,normal,tangent,width,depth,length,steel_ratio=None,steel_points=None):
    """2x2 section quadrature retains both bending lever arms and torsion."""
    if min(width,depth,length)<=1e-9:return
    n=np.asarray(normal,dtype=float);n/=np.linalg.norm(n);t=np.asarray(tangent,dtype=float);t-=n*(t@n);t/=np.linalg.norm(t);v=np.cross(n,t)
    p=np.asarray(point,dtype=float);rho=MATERIAL['reference_steel_ratio'] if steel_ratio is None else steel_ratio
    for i in (-1,1):
        for j in (-1,1):
            q=p+t*i*width/(2*math.sqrt(3))+v*j*depth/(2*math.sqrt(3))
            model['springs'].append(dict(a=a,b=b,point_m=q.tolist(),normal=n.tolist(),area_m2=width*depth/4*(1-rho),length_m=length,kind='concrete'))
            if rho and steel_points is None:model['springs'].append(dict(a=a,b=b,point_m=q.tolist(),normal=n.tolist(),area_m2=width*depth/4*rho,length_m=length,kind='steel'))
    for q,area in steel_points or []:
        model['springs'].append(dict(a=a,b=b,point_m=list(q),normal=n.tolist(),area_m2=area,length_m=length,kind='steel'))


def connect_quad_edges(model, body_indices=None):
    lines={};bodies=model['bodies'];indices=body_indices if body_indices is not None else range(len(bodies))
    for idx in indices:
        b=bodies[idx];p=np.array(b['quad_m']);h=b['thickness_m']
        for start,end in zip(p,np.roll(p,-1,axis=0)):
            d=end-start;length=np.linalg.norm(d);direction=d/length
            first=next((v for v in direction if abs(v)>1e-8),1)
            if first<0:direction=-direction
            offset=start-direction*(start@direction)
            key=tuple(np.round(np.r_[direction,offset],7))
            interval=sorted([start@direction,end@direction])
            lines.setdefault(key,[]).append((idx,interval,h,direction,offset))
            if max(abs(start[2]),abs(end[2]))<1e-7 and not b['fixed']:
                point=(start+end)/2;n=np.array([0.,0.,-1.]);distance=abs((point-np.array(b['center_m']))@n)
                add_interface(model,idx,-1,point,n,direction,length,h,max(distance, h/2))
    seen=set()
    for row in lines.values():
        for k,(a,ia,ha,t,off) in enumerate(row):
            for b,ib,hb,_,_ in row[k+1:]:
                if a==b:continue
                lo=max(ia[0],ib[0]);hi=min(ia[1],ib[1])
                if hi-lo<1e-7:continue
                key=(min(a,b),max(a,b),tuple(np.round(off+t*(lo+hi)/2,7)))
                if key in seen:continue
                seen.add(key);delta=np.array(bodies[b]['center_m'])-bodies[a]['center_m'];delta-=t*(delta@t)
                length=float(np.linalg.norm(delta))
                if length<1e-7:raise ValueError('发现重复重叠壳，不能重复计入质量和刚度')
                add_interface(model,a,b,off+t*(lo+hi)/2,delta/length,t,hi-lo,min(ha,hb),length)


def finish(model):
    bodies=model['bodies'];n=len(bodies)
    if n>LIMITS['max_bodies'] or len(model['springs'])>LIMITS['max_springs']:raise ValueError('场景超过首版宏单元预算；未启动计算')
    adjacency=[set() for _ in bodies];supported={i for i,b in enumerate(bodies) if b['fixed']}
    for s in model['springs']:
        if s['b']<0:supported.add(s['a'])
        else:adjacency[s['a']].add(s['b']);adjacency[s['b']].add(s['a'])
    queue=list(supported)
    while queue:
        i=queue.pop()
        for j in adjacency[i]-supported:supported.add(j);queue.append(j)
    missing=[bodies[i]['id'] for i in range(n) if i not in supported]
    # Preview remains reviewable; submission must reject unsupported graphs.
    model['checks']=dict(supported=not missing,unsupported_bodies=missing[:20],mass_positive=all(b['mass_kg']>0 for b in bodies))
    model['budget']=dict(bodies=n,dofs=6*sum(not b['fixed'] for b in bodies),springs=len(model['springs']),limits=LIMITS)
    model['mass_ledger']=dict(total_kg=sum(b['mass_kg'] for b in bodies),fixed_kg=sum(b['mass_kg'] for b in bodies if b['fixed']))
    vertices=np.vstack([b['vertices_m'] for b in bodies]);model['bounds_m']=np.r_[vertices.min(axis=0),vertices.max(axis=0)].tolist()
    model['schema_version']='scene-blast-model@1'
    return model


def shell_model(cid,nodes,shells,thickness):
    lookup={n[0]:n[1:] for n in nodes};model=dict(bodies=[],springs=[],surfaces=[],display=[],envelopes=[],duplicate_skins_removed=0);seen=set()
    quads=[(str(row[0]),np.array([lookup[j] for j in row[2:6]],dtype=float)) for row in shells]
    quads,removed_area=union_coplanar_quads(quads)
    model['overlapping_skin_area_removed_m2']=removed_area
    for eid,p in quads:
        key=tuple(sorted(map(tuple,np.round(p,8))))
        if key in seen:model['duplicate_skins_removed']+=1;continue
        seen.add(key);b=body_from_quad(f'{cid}:{eid}',p,thickness);b['component_id']=cid;i=len(model['bodies']);model['bodies'].append(b)
        n=np.cross(p[1]-p[0],p[3]-p[0]);area=np.linalg.norm(n);n/=area
        # Ground skins and bottoms are not exposed to outdoor blast.
        if p.mean(axis=0)[2]>1e-6:model['surfaces'].append(dict(point_m=p.mean(axis=0).tolist(),normal=n.tolist(),area_m2=float(area),weights=[[i,1.]],component_id=cid))
    connect_quad_edges(model)
    model['display']=[dict(id=b['id'],component_id=b['component_id'],vertices_m=b['vertices_m'],body=i,role=b['role']) for i,b in enumerate(model['bodies'])]
    points=np.array([n[1:] for n in nodes]);model['envelopes']=[dict(min_m=points.min(axis=0).tolist(),max_m=points.max(axis=0).tolist())]
    return finish(model)


def union_coplanar_quads(quads):
    """Remove repeated/overlapping skins in the existing assembled-box geometry.

    Rectangle subtraction preserves the visible union, avoiding coincident tiles
    and double mass. It does not repair arbitrary intersecting/nonorthogonal solids.
    """
    planes={};result=[];original=0.;retained=0.
    for eid,p in quads:
        u=p[1]-p[0];v=p[3]-p[0];u/=np.linalg.norm(u);v/=np.linalg.norm(v);normal=np.cross(u,v)
        canonical=normal.copy()
        if next(x for x in canonical if abs(x)>1e-8)<0:canonical=-canonical
        key=tuple(np.round(np.r_[canonical,p[0]@canonical],7));planes.setdefault(key,[]).append((eid,p,u,v,normal))
    for rows in planes.values():
        _,base,u,v,n=rows[0];origin=base[0];kept=[]
        def rect(p):
            q=np.stack([(p-origin)@u,(p-origin)@v],axis=1);return [q[:,0].min(),q[:,1].min(),q[:,0].max(),q[:,1].max()]
        entries=sorted([(eid,rect(p),norm) for eid,p,_,_,norm in rows],key=lambda t:-(t[1][2]-t[1][0])*(t[1][3]-t[1][1]))
        for eid,r,norm in entries:
            original+=(r[2]-r[0])*(r[3]-r[1]);pieces=[r]
            for old in kept:
                following=[]
                for a in pieces:
                    x,y,X,Y=max(a[0],old[0]),max(a[1],old[1]),min(a[2],old[2]),min(a[3],old[3])
                    if X-x<1e-8 or Y-y<1e-8:following.append(a);continue
                    following.extend(q for q in ([a[0],a[1],x,a[3]],[X,a[1],a[2],a[3]],[x,a[1],X,y],[x,Y,X,a[3]]) if q[2]-q[0]>1e-8 and q[3]-q[1]>1e-8)
                pieces=following
                if not pieces:break
            for k,a in enumerate(pieces):
                q=np.array([origin+u*x+v*y for x,y in ((a[0],a[1]),(a[2],a[1]),(a[2],a[3]),(a[0],a[3]))])
                if norm@n<0:q=q[[0,3,2,1]]
                result.append((f'{eid}.{k}',q));kept.append(a);retained+=(a[2]-a[0])*(a[3]-a[1])
    return result,float(max(0.,original-retained))


def face_patches(quad,coordinates,max_size=2.5):
    """Partition a parent face on actual reference node lines before integrating.

    One midpoint per subface is a first-order spatial quadrature, not one force
    per architectural wall/roof. Adjacent macro tiles therefore get independent
    loads; additional uniform cuts bound the empirical pressure sampling length.
    """
    q=np.asarray(quad);origin=q[0];u=q[1]-q[0];v=q[3]-q[0]
    cuts=[]
    for direction in (u,v):
        axis=int(np.argmax(np.abs(direction)));values=(coordinates[axis]-origin[axis])/direction[axis]
        fractions=np.r_[np.linspace(0,1,max(1,math.ceil(np.linalg.norm(direction)/max_size))+1),values[(values>1e-8)&(values<1-1e-8)]]
        cuts.append(np.unique(np.round(fractions,9)))
    if len(cuts[0])*len(cuts[1])>3000:raise ValueError('单个表面受压积分预算超限')
    for a,b in zip(cuts[0],cuts[0][1:]):
        for c,d in zip(cuts[1],cuts[1][1:]):
            points=np.array([origin+x*u+y*v for x,y in ((a,c),(b,c),(b,d),(a,d))]);normal=np.cross(points[1]-points[0],points[3]-points[0]);area=np.linalg.norm(normal)
            if area>1e-12:yield points.mean(axis=0),normal/area,float(area)


def append_model(target,source):
    offset=len(target['bodies']);target['bodies'].extend(source['bodies'])
    target['springs'].extend([dict(s,a=s['a']+offset,b=s['b']+offset if s['b']>=0 else -1) for s in source['springs']])
    target['surfaces'].extend([dict(s,weights=[[i+offset,w] for i,w in s['weights']]) for s in source['surfaces']])
    target['display'].extend([dict(s,body=s['body']+offset) for s in source['display']]);target['envelopes'].extend(source['envelopes'])
    target.setdefault('geometry_corrections',[]).append(dict(instance_id=source['display'][0]['component_id'],overlapping_skin_area_removed_m2=source.get('overlapping_skin_area_removed_m2',0)))


def project_spec(name):
    from ...paths import find_project_dir,safe_project_name
    if safe_project_name(name)!=name:raise ValueError('项目名称必须使用项目列表中的完整标识')
    path=find_project_dir(name)/'model.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_size>4_000_000:raise ValueError('项目输入不可用或过大')
    data=json.loads(path.read_text(encoding='utf8'));return data['spec']


def prepare(config):
    if np is None:raise ValueError('CPU 场景准备需要 NumPy；其他工作台仍可使用')
    from ...component_library import default_component_geometry
    from ...dyna_assembly import apply_transform, build_component_geometry
    source=config['source'];kind=source['kind'];spec=project_spec(source['project_name']) if source['project_name'] else None
    if kind=='fixed_three_storey':return fixed_model(config)
    if kind=='city_street':
        from ...city_street_blast import default_city_street_blast_spec,_urban_component_specs
        spec=spec or default_city_street_blast_spec()
        if spec.get('model_type')!='city_street_blast_scene':raise ValueError('所选项目不是城市街道场景')
        all_components=_urban_component_specs(spec)
        components=[c for c in all_components if c['template'] in KINDS[:3]]
        unsupported=[c['id'] for c in all_components if c['template'] not in (*KINDS[:3],'shell_plate','parked_vehicle','traffic_light','parking_lot') and c.get('role')!='non_structural_visual_guide']
        if unsupported:raise ValueError('城市包含尚未适配的结构：'+', '.join(unsupported))
    elif spec:
        components=deepcopy(spec.get('components',[]))
        if not components or any(c.get('template')!=kind for c in components):raise ValueError('项目组件与所选模型来源不一致；首版不自动忽略其他构件')
    else:components=[dict(id=kind,template=kind,geometry=default_component_geometry(kind),transform={})]
    model=dict(bodies=[],springs=[],surfaces=[],display=[],envelopes=[],context=[])
    for c in components:
        c=deepcopy(c);g=c['geometry'];dims=[float(v) for k,v in g.items() if k.endswith('_m') and isinstance(v,(float,int))]
        if not dims or min(dims)<=0 or max(dims)>100 or g.get('tower_count',1)>6:raise ValueError('几何超出首版支持范围')
        c['mesh']={'size_m':config['analysis']['mesh_m']};c['structural_response_mode']='supported_shell_details'
        # Cap BEFORE invoking the bounded coarse builder; no native fine mesh.
        estimate=12*sum((math.ceil(v/c['mesh']['size_m'])+1)**2 for v in dims[:3])
        if estimate>30000:raise ValueError('几何准备预算超限')
        nodes,shells,solids,section=build_component_geometry(c,1)
        if solids:raise ValueError('首版来源适配只支持既有粗壳')
        nodes=apply_transform(nodes,c)
        append_model(model,shell_model(c['id'],nodes,shells,section['thickness_m']))
    if kind=='city_street':
        for c in all_components:
            if c['template'] in KINDS[:3]:continue
            # Explicit display-only context; these objects do not masquerade as solved bodies.
            model['context'].append(dict(id=c['id'],template=c['template'],geometry=c['geometry'],transform=c.get('transform',{}),response='visual_context_only'))
    model['source']=dict(source,definition_fingerprint=fingerprint(spec or components))
    model['assumptions']=['既有 supported_shell_details 粗壳几何；壳壁承担自重，非细化梁柱模型',
        '材料与缺失配筋采用可见的参考参数，未核验为实物参数','宏单元 6 自由度，分布连接近似；泊松效应及整栋精度待验证',
        '室外经验表面荷载，不含城市遮挡、绕射、多重反射；不是空气域压力云图',
        '道路、车辆、路灯仅作为场景参照，不参与本版建筑响应']
    return finish(model)


def fixed_model(config):
    """Use the already audited column/slab reference, not the original wall-overlap model."""
    resource=ROOT/'resources'/'scene_blast'/'three-storey-reference.json'
    manifest=json.loads(resource.with_suffix('.manifest.json').read_text(encoding='utf8'))
    if hashlib.sha256(resource.read_bytes()).hexdigest()!=manifest['sha256']:raise ValueError('三层规整参考校验失败')
    ref=json.loads(resource.read_text(encoding='utf8'))
    archive=ROOT/'resources'/'fixed_building_pressure'/'three-storey-structural.zip'
    with zipfile.ZipFile(archive) as z:sealed=json.loads(z.read('structural-template.json'))
    if ref['template_fingerprint']!=sealed['template_fingerprint']:raise ValueError('固定建筑来源版本不匹配')
    model=dict(bodies=[],springs=[],surfaces=[],display=[],envelopes=[],context=[])
    xyz=np.array(ref['nodes']);adj=[[] for _ in xyz];fixed=set(ref['fixed_nodes']);panels=[];columns=[]
    for idx,e in enumerate(ref['elements']):
        p=xyz[e['nodes']];cid=e['component_id']
        if e['kind']=='panel':
            section=ref['panel_sections'][e['section']];b=body_from_quad(f'{cid}:{idx}',p,section['thickness_m']);panels.append(idx)
        else:
            sec=ref['column_sections'][e['section']];g=sec['geometry'];center=p.mean(axis=0);lo=center-[g['width_m']/2,g['depth_m']/2,abs(p[1,2]-p[0,2])/2];hi=2*center-lo
            b=dict(id=f'{cid}:{idx}',component_id=cid,center_m=center.tolist(),mass_kg=1.,inertia_kg_m2=np.eye(3).tolist(),vertices_m=corners(lo,hi).tolist(),fixed=False,role='column');columns.append(idx)
        b['fixed']=all(n in fixed for n in e['nodes']);model['bodies'].append(b)
        for n in e['nodes']:adj[n].append(idx)
    connect_quad_edges(model,panels)
    # Actual column/slab joints share audited reference node IDs. No wall stiffness.
    for idx in columns:
        e=ref['elements'][idx];sec=ref['column_sections'][e['section']];g=sec['geometry'];area=g['width_m']*g['depth_m']
        bars=sec['original_bar_positions_m'];bar_area=math.pi*sec['reinforcement']['diameter_m']**2/4
        for node in e['nodes']:
            destinations=adj[node]
            if node in fixed:destinations=[*destinations,-1]
            for other in destinations:
                if other==idx or (other in columns and other<idx):continue
                point=xyz[node];n=np.array([0.,0.,1. if point[2]>=np.array(model['bodies'][idx]['center_m'])[2] else -1.])
                length=abs(point[2]-model['bodies'][idx]['center_m'][2])
                if other>=0:length+=abs(point[2]-model['bodies'][other]['center_m'][2])
                weights=1/max(1,sum(o not in columns and o>=0 for o in destinations)) if other>=0 and other not in columns else 1.
                steel=[(point+np.array([x,y,0]),bar_area*weights) for x,y in bars]
                before=len(model['springs']);add_interface(model,idx,other,point,n,[1.,0,0],g['width_m'],g['depth_m'],max(length,g['width_m']),len(bars)*bar_area/area,steel)
                for s in model['springs'][before:]:
                    if s['kind']=='concrete':s['area_m2']*=weights
    # Split each existing positive point mass over incident elements. This conserves
    # total mass, centroid AND inertia, including infill/steel overlap corrections.
    masses=[[] for _ in model['bodies']];fixed_bodies=[i for i,b in enumerate(model['bodies']) if b['fixed']]
    for point in ref['mass_points']:
        owners=adj[point['master']]
        if point['master'] in fixed:
            owners=[i for i in owners if model['bodies'][i]['fixed']] or [min(fixed_bodies,key=lambda i:np.linalg.norm(np.array(model['bodies'][i]['center_m'])-point['position_m']))]
        if not owners:raise ValueError('参考质量点没有结构承载映射')
        for owner in owners:masses[owner].append((point['mass_kg']/len(owners),np.array(point['position_m'])))
    for b,points in zip(model['bodies'],masses):
        m=sum(v for v,_ in points);center=sum(v*p for v,p in points)/m;I=np.zeros((3,3))
        for v,p in points:
            r=p-center;I+=v*((r@r)*np.eye(3)-np.outer(r,r))
        if np.linalg.eigvalsh(I).min()<=0:raise ValueError('三层参考转动惯量非正定')
        b.update(center_m=center.tolist(),mass_kg=m,inertia_kg_m2=I.tolist())
    centers=np.array([b['center_m'] for b in model['bodies']]);by_component={}
    for i,b in enumerate(model['bodies']):by_component.setdefault(b['component_id'],[]).append(i)
    floor_maps={}
    for i in panels:
        b=model['bodies'][i];p=np.array(b['quad_m']);top=round(float(p[:,2].mean()+b['thickness_m']/2),7)
        floor_maps.setdefault(top,[]).append(i)
    floors=sorted(floor_maps)
    rectangles={f:(np.array(floor_maps[f]),np.array([np.array(model['bodies'][i]['quad_m'])[:,:2].min(axis=0) for i in floor_maps[f]]),np.array([np.array(model['bodies'][i]['quad_m'])[:,:2].max(axis=0) for i in floor_maps[f]])) for f in floors}
    def floor_owner(point,f,attachment=False):
        tags,lo,hi=rectangles[f];offset=np.maximum(lo-point[:2],0)+np.minimum(hi-point[:2],0);distance=np.linalg.norm(offset,axis=1);k=int(distance.argmin())
        if distance[k]>.35 and not attachment:raise ValueError('外墙找不到局部楼板支承；拒绝跨空洞刚臂映射')
        return int(tags[k])
    def applications(point,c,own,display=False):
        if own:
            # Original slabs/columns have multiple macro tiles, never one owner for a whole floor.
            containing=[]
            for i in own:
                vertices=np.array(model['bodies'][i]['vertices_m']);lo=vertices.min(axis=0);hi=vertices.max(axis=0)
                distance=np.linalg.norm(np.maximum(lo-point,0)+np.minimum(hi-point,0));containing.append(distance)
            return [[own[int(np.argmin(containing))],1.]], [point.tolist()]
        level=c.get('level');level=level if type(level) is int else int(np.searchsorted(floors,point[2],side='right')-1)
        level=max(0,min(len(floors)-1,level));lower=floors[level]
        attachment=display or c['role']=='canopy' or level>=len(floors)-1
        a=floor_owner(point,lower,attachment)
        if level>=len(floors)-1:return [[a,1.]], [point.tolist()]  # Explicit attached rooftop mass/load.
        upper=floors[level+1];b=floor_owner(point,upper,attachment);upper_support=upper-model['bodies'][b]['thickness_m']
        if point[2]<lower or point[2]>upper_support:return [[a if point[2]<lower else b,1.]], [point.tolist()]
        t=(point[2]-lower)/(upper_support-lower)
        # Simply supported wall strip reactions at physical slab faces. Only the
        # face-to-midsurface eccentricity remains, not a storey-height rigid arm.
        return [[a,1-t],[b,t]], [[float(point[0]),float(point[1]),lower],[float(point[0]),float(point[1]),upper_support]]
    all_bounds=np.array([c['native_bounds_m'] for c in sealed['payload']['components'].values()]);coordinates=[np.unique(np.round(xyz[:,a],8)) for a in range(3)]
    indoor_bounds=np.array([r['bounds_m'] for r in sealed['payload']['rooms'].values()])
    for component_index,(cid,c) in enumerate(sealed['payload']['components'].items()):
        bounds=c['native_bounds_m'];vertices=c.get('vertices_m',corners(bounds[:3],bounds[3:]).tolist());p=np.mean(vertices,axis=0)
        own=by_component.get(cid,[])
        if own:
            for owner in own:model['display'].append(dict(id=model['bodies'][owner]['id'],component_id=cid,vertices_m=model['bodies'][owner]['vertices_m'],body=owner,role=c['role'],response='structural'))
        else:
            weights,_=applications(p,c,own,display=True);owner=max(weights,key=lambda v:v[1])[0]
            model['display'].append(dict(id=cid,component_id=cid,vertices_m=vertices,body=owner,role=c['role'],response='attached_mass_display'))
        # Load only envelope faces, preserving actual facade openings/accessories.
        if c['role'] in {'partition','shaft','stair','railing','landing','foundation'}:continue
        for face in FACES:
            for q,n,area in face_patches(np.array(vertices)[list(face)],coordinates):
                if q[2]<=0:continue
                # Interior room faces are not outdoor empirical-blast receivers.
                outside=q+n*1e-4
                if np.any(np.all(outside>=indoor_bounds[:,:3]-1e-7,axis=1)&np.all(outside<=indoor_bounds[:,3:]+1e-7,axis=1)):continue
                enclosed=np.all(outside>all_bounds[:,:3]+1e-6,axis=1)&np.all(outside<all_bounds[:,3:]-1e-6,axis=1);enclosed[component_index]=False
                if enclosed.any():continue
                weights,points=applications(q,c,own)
                model['surfaces'].append(dict(point_m=q.tolist(),normal=n.tolist(),area_m2=area,weights=weights,application_points_m=points,component_id=cid))
    building=sealed['payload']['geometry_metadata']['building_bounds_m']
    model['envelopes']=[dict(min_m=building[:3],max_m=building[3:])]
    model['source']=dict(config['source'],definition_fingerprint=ref['source']['fingerprint'],template_fingerprint=ref['template_fingerprint'])
    model['assumptions']=['几何、柱截面与正质量/惯量沿用已审计的规整参考；旧弹性内核假设不自动沿用',
        '节点采用截面整体连接、钢筋充分锚固的理想化假设；实际搭接/锚固构造未核实，不视为已验证的实物连续性',
        '本版增加重力与非线性宏连接；原弹性结果不复用为新响应',
        '固定三层采用已经审计的规整柱板参考；不修改原 K；填充墙仅作正质量与表面荷载传递',
        '附属外观采用最近承载构件刚体映射，不输出填充墙自身裂缝或逐根钢筋结果',
        '柱筋位置沿用参考；板筋首版采用等效参考率，非原不对称分层精细应力',
        '墙面压力经上下楼板面的简支条带反力传递，屋顶突出物按附属物刚接传力；不解算填充墙自身破坏',
        '宏连接材料/破坏参数尚未经真实整栋对照；不得作为工程倒塌预测']
    result=finish(model)
    result['mass_ledger']['audited_reference_kg']=ref['mass_ledger']['total_kg']
    result['mass_ledger']['relative_error']=abs(result['mass_ledger']['total_kg']/ref['mass_ledger']['total_kg']-1)
    result['mass_ledger']['audited_fixed_kg']=ref['mass_ledger']['fixed_mass_kg']
    result['mass_ledger']['fixed_relative_error']=abs(result['mass_ledger']['fixed_kg']/ref['mass_ledger']['fixed_mass_kg']-1)
    return result
