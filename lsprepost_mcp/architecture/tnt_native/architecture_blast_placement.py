"""Resolve floor-relative sources against actual convex cells before allocating ALE."""
import math
import numpy as np

from .architecture_blast_contracts import resolve_blast_cylinder
from .architecture_scene_surfaces import HEX_FACES
from .architecture_volume_fractions import clip_convex_faces

TOL=1e-9


def _cross2(a,b):return a[0]*b[1]-a[1]*b[0]


def _hull(points):
    points=sorted(set(map(tuple,points)))
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    halves=[]
    for sequence in (points,list(reversed(points))):
        half=[]
        for p in sequence:
            while len(half)>=2 and cross(half[-2],half[-1],p)<=0:half.pop()
            half.append(p)
        halves.append(half[:-1])
    return np.asarray(halves[0]+halves[1])


def cylinder_intersects_hex(points,center,radius,z_interval):
    points=np.asarray(points,float);lo=points.min(0);hi=points.max(0)
    lo[2]=max(lo[2],z_interval[0]);hi[2]=min(hi[2],z_interval[1])
    if hi[2]-lo[2]<=TOL:return False
    faces=clip_convex_faces([points[f] for f in HEX_FACES],lo,hi)
    if not faces:return False
    poly=_hull(np.concatenate(faces)[:,:2]);p=np.asarray(center[:2]);distance=math.inf;inside=True
    for a,b in zip(poly,np.roll(poly,-1,axis=0)):
        edge=b-a
        if _cross2(edge,p-a)<-TOL:inside=False
        t=np.clip(np.dot(p-a,edge)/np.dot(edge,edge),0,1)
        distance=min(distance,float(np.linalg.norm(p-(a+t*edge))))
    return inside or distance<radius-TOL


def resolve_blast_placement(template:dict,derived:dict,config:dict)->dict:
    cylinder=resolve_blast_cylinder(config['cylinder'],template['metadata']['tnt_density_kg_m3'])
    x,y=config['location']['xy_m'];g=derived['geometry'];room=None
    reference=g['grade_m']
    if config['scenario']=='indoor':
        room=template['rooms'][config['location']['room_id']];b=room['bounds_m']
        if not b[0]-TOL<=x<=b[3]+TOL or not b[1]-TOL<=y<=b[4]+TOL:raise ValueError('source is outside selected room')
        floors=[]
        for c in derived['components'].values():
            if c['role'] not in ('slab','floor','foundation','landing'):continue
            if c.get('level') not in (room['level'],None):continue
            for e in g['building_elements'][g['building_elements'][:,1]==c['part_id']]:
                points=np.array([g['building_nodes'][int(n)] for n in e[2:]])
                for f in HEX_FACES:
                    face=points[f];z=face[0,2]
                    if np.ptp(face[:,2])>TOL or z>b[2]+.3 or z<b[2]-.3:continue
                    n=np.cross(face[1]-face[0],face[2]-face[0])
                    if n[2]<=0:continue
                    poly=_hull(face[:,:2]);q=np.array([x,y])
                    if all(_cross2(v-u,q-u)>=-TOL for u,v in zip(poly,np.roll(poly,-1,axis=0))):floors.append(z)
        if not floors:raise ValueError('no actual supporting floor at selected room position')
        reference=max(floors)
    bottom=reference+config['location']['bottom_clearance_m'];height=cylinder['height_m'];r=cylinder['diameter_m']/2
    center=[x,y,bottom+height/2];bounds=[x-r,y-r,bottom,x+r,y+r,bottom+height]
    for cid,c in derived['components'].items():
        b=c['native_bounds_m']
        if any(min(b[i+3],bounds[i+3])-max(b[i],bounds[i])<=TOL for i in range(3)):continue
        for e in g['building_elements'][g['building_elements'][:,1]==c['part_id']]:
            if cylinder_intersects_hex([g['building_nodes'][int(n)] for n in e[2:]],center,r,[bottom,bottom+height]):
                raise ValueError('cylinder collision: '+cid)
    if room:
        b=room['bounds_m']
        if any(bounds[i]<b[i]-TOL or bounds[i+3]>b[i+3]+TOL for i in range(3)):
            raise ValueError('full cylinder must remain in selected room')
    return dict(center_m=center,bounds_m=bounds,diameter_m=2*r,height_m=height,
                reference_floor_z_m=float(reference),analytical_volume_m3=cylinder['volume_m3'],mass_kg=cylinder['mass_kg'])


def _axis(lo,hi,background,regions):
    cuts=sorted({lo,hi,*[max(lo,min(hi,v)) for a,b,h in regions for v in (a,b)]})
    out=[]
    for a,b in zip(cuts,cuts[1:]):
        spacing=min([background]+[h for l,u,h in regions if l<(a+b)/2<u])
        count=math.ceil((b-a)/spacing-1e-10)
        if count>200000 or len(out)+count>200001:raise ValueError('axis budget exceeded')
        out.extend(a+(b-a)*i/count for i in range(count))
    out.append(hi)
    return [float(v) for i,v in enumerate(out) if i==0 or v-out[i-1]>1e-10]


def plan_blast_grid(template:dict,derived:dict,config:dict,placement:dict)->dict:
    g=derived['geometry'];b=g['building_bounds_m'];ground=g['ground_bounds_m'];mesh=config['mesh'];m=mesh['margins_m'];grade=g['grade_m']
    bounds=[b[0]-m['xmin'],b[1]-m['ymin'],grade,b[3]+m['xmax'],b[4]+m['ymax'],b[5]+m['top']]
    if any(bounds[i]<ground[i]-TOL or bounds[i+3]>ground[i+3]+TOL for i in (0,1)):
        raise ValueError('horizontal air extent exceeds fixed concrete ground coverage')
    charge=placement['bounds_m'];h=mesh['charge_cell_m']
    if any(charge[i]-h<=bounds[i]+TOL or charge[i+3]+h>=bounds[i+3]-TOL for i in range(3)):
        # A zero-clearance charge may touch the grade; the below-grade buffer remains vacuum.
        if not (abs(charge[2]-grade)<TOL and all(bounds[i]<charge[i]-h<charge[i+3]+h<bounds[i+3] for i in (0,1)) and charge[5]+h<bounds[5]):
            raise ValueError('charge and refinement padding must be enclosed by air')
    regions=[[(max(bounds[i],charge[i]-h),min(bounds[i+3],charge[i+3]+h),h)] for i in range(3)]
    if config['scenario']=='indoor':
        room=template['rooms'][config['location']['room_id']];rb=room['bounds_m']
        for i in range(3):regions[i].append((rb[i],rb[i+3],mesh['room_cell_m']))
        for o in template['openings'].values():
            if o['kind'] not in ('window','door'):continue
            ob=o['bounds_m']
            if o['level']==room['level'] and all(min(ob[i+3],rb[i+3])-max(ob[i],rb[i])>=-.2 for i in range(3)):
                for i in range(3):regions[i].append((ob[i]-.1,ob[i+3]+.1,mesh['opening_cell_m']))
    axes=[_axis(bounds[i],bounds[i+3],mesh['background_cell_m'],regions[i]) for i in range(3)]
    axes[2]=g['buffer_z']+axes[2]
    count=math.prod(len(a)-1 for a in axes);nodes=math.prod(len(a) for a in axes)
    if count>200000 or nodes>250000:raise ValueError(f'ALE budget exceeded: {count} cells, {nodes} nodes')
    plan=dict(template['native_ids'],**placement,axes=axes,grade_m=grade,node_count=nodes,element_count=count,
              building_bounds_m=b,local_target_cell_m=h,volume_fill_ntrace=3,
              effective_resolution=dict(target=mesh,minimum_axis_spacing_m=min(min(np.diff(a)) for a in axes)))
    if max(plan['node_start']+nodes-1,plan['element_start']+count-1)>99999999:raise ValueError('native ID budget exceeded')
    if max(derived['geometry']['building_nodes'])>=plan['node_start'] or max(derived['geometry']['ground_nodes'])>=plan['node_start']:
        raise ValueError('retained and fluid node ID ranges collide')
    return plan
