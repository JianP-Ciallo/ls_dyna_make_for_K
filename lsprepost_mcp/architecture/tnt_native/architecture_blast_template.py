"""Register and load a portable, sealed view of the retained native K package."""
from copy import deepcopy
import json
import math
from pathlib import Path
import shutil

import numpy as np

from .architecture_blast_contracts import fingerprint
from .architecture_scene_surfaces import read_nodes, read_solids
from .support import file_sha256

MASTER = 'building-blast-reference.k'
INDEX = 'blast-template.json'
SCHEMA = 'architecture.blast-template@1'


def native_blocks(text):
    """Keep fixed-width columns: stripping native records corrupts installation cards."""
    blocks=[];key=None;rows=[]
    for line in text.splitlines():
        if line.lstrip().startswith('*'):
            if key is not None:blocks.append((key,rows))
            key=line.strip().upper();rows=[]
        elif key is not None and line.strip() and not line.lstrip().startswith('$'):
            rows.append(line)
    if key is not None:blocks.append((key,rows))
    return blocks


def fields(row,width=10):
    return [v.strip() for v in row.split(',')] if ',' in row else [row[i:i+width].strip() for i in range(0,len(row),width)]


def part_records(path):
    result={}
    for key,rows in native_blocks(Path(path).read_text(encoding='utf8')):
        if key not in ('*PART','*PART_TITLE'):continue
        title=rows[0].strip();values=fields(rows[1],10 if ',' in rows[1] else 8)
        if title in result:raise ValueError('duplicate Part title: '+title)
        result[title]=list(map(int,values[:4]))
    if len({r[0] for r in result.values()})!=len(result):raise ValueError('duplicate Part ID')
    return result


def installation_index(path,components):
    blocks=native_blocks(Path(path).read_text(encoding='utf8'))
    owners={}
    for cid,c in components.items():
        for nid in c['node_ids']:owners.setdefault(nid,[]).append(cid)
    result=dict(interpolations=[],sets={},rigid_bodies=[],joints=[],
                auxiliary_nodes={str(n):list(p) for n,p in read_nodes(path).items()})
    supported={'*NODE','*NODE+','*CONSTRAINED_INTERPOLATION','*SET_NODE_LIST',
               '*CONSTRAINED_NODAL_RIGID_BODY','*CONSTRAINED_JOINT_REVOLUTE'}
    for i,(key,rows) in enumerate(blocks):
        if key not in supported:raise ValueError('unsupported installation card: '+key)
        if key=='*CONSTRAINED_INTERPOLATION':
            head=fields(rows[0]);nid=int(head[1]);source=owners.get(nid,[])
            if len(source)!=1:raise ValueError('ambiguous installation source node')
            weights=[]
            for row in rows[1:]:
                f=fields(row);weights.append([int(f[0]),float(f[2])])
            result['interpolations'].append(dict(block=i,id=int(head[0]),source_node_id=nid,
                source_component_id=source[0],weights=weights))
        elif key=='*SET_NODE_LIST':
            sid=int(fields(rows[0])[0]);members=[int(v) for row in rows[1:] for v in fields(row) if v and int(v)>0]
            if str(sid) in result['sets']:raise ValueError('duplicate installation node set')
            result['sets'][str(sid)]=dict(block=i,members=members)
        elif key=='*CONSTRAINED_NODAL_RIGID_BODY':
            f=fields(rows[0]);result['rigid_bodies'].append(dict(block=i,id=int(f[0]),set_id=int(f[2])))
        elif key=='*CONSTRAINED_JOINT_REVOLUTE':
            result['joints'].append(dict(block=i,node_ids=list(map(int,fields(rows[0])[:4]))))
    for body in result['rigid_bodies']:
        members=result['sets'].get(str(body['set_id']),{}).get('members',[])
        if not members:raise ValueError('missing rigid body node set')
        body['component_ids']=sorted({cid for n in members for cid in owners.get(n,[])})
    for joint in result['joints']:
        candidates={cid for body in result['rigid_bodies']
                    if set(joint['node_ids']).intersection(result['sets'][str(body['set_id'])]['members'])
                    for cid in body['component_ids'] if components[cid]['role']=='door'}
        if len(candidates)!=1:raise ValueError('ambiguous revolute door membership')
        joint['source_component_id']=candidates.pop()
    return result


def _bounds(nodes):
    points=np.array(list(nodes.values()),float)
    if not len(points) or not np.all(np.isfinite(points)):raise ValueError('finite geometry required')
    return [*points.min(axis=0),*points.max(axis=0)]


def _geometry(root):
    return dict(building_nodes=read_nodes(root/'solids-solver.k'),
                building_elements=read_solids(root/'solids-solver.k'),
                ground_nodes=read_nodes(root/'ground-solver.k'),
                ground_elements=read_solids(root/'ground-solver.k'))


def verify_native_envelope(component,points,all_cells,part_ids,pid):
    """Validate envelope differences caused by native Boolean ownership.

    The reference mesh rounds stair coordinates to seven decimal places. A lost
    rectangular strip must be completely occupied by other actual building parts;
    a semantic envelope alone is never sufficient evidence of a filled strip.
    """
    tol=5.1e-8
    expected=np.asarray(component['bounds_m'],float);lo=points.min(0);hi=points.max(0)
    actual=np.r_[lo,hi]
    if np.allclose(actual,expected,atol=tol,rtol=0):return {}
    error='component geometry mismatch: '+component['id']
    if np.any(lo<expected[:3]-tol) or np.any(hi>expected[3:]+tol):raise ValueError(error)
    vertices=np.asarray(component['vertices_m'],float)
    if not np.all((abs(vertices-expected[:3])<tol)|(abs(vertices-expected[3:])<tol)):
        raise ValueError(error+' (nonrectangular envelope)')
    cell_lo=all_cells.min(1);cell_hi=all_cells.max(1)
    lower=expected[:3].copy();upper=expected[3:].copy();covered=0.
    for axis in range(3):
        for side in (0,1):
            a=lower.copy();b=upper.copy()
            if side==0:b[axis]=lo[axis]
            else:a[axis]=hi[axis]
            if b[axis]-a[axis]<=tol:continue
            volume=float(np.prod(b-a));remainder=[(a,b)]
            mask=(part_ids!=pid)&np.all(cell_hi>a+tol,axis=1)&np.all(cell_lo<b-tol,axis=1)
            for cell,cl,ch in zip(all_cells[mask],cell_lo[mask],cell_hi[mask]):
                if not np.all((abs(cell-cl)<tol)|(abs(cell-ch)<tol)):
                    raise ValueError(error+' (nonrectangular native trim owner)')
                remaining=[]
                for low,high in remainder:
                    cutlo=np.maximum(low,cl);cuthi=np.minimum(high,ch)
                    if np.any(cuthi<=cutlo):remaining.append((low,high));continue
                    corelo=low.copy();corehi=high.copy()
                    for k in range(3):
                        if cutlo[k]>corelo[k]:
                            end=corehi.copy();end[k]=cutlo[k];remaining.append((corelo.copy(),end));corelo[k]=cutlo[k]
                        if cuthi[k]<corehi[k]:
                            start=corelo.copy();start[k]=cuthi[k];remaining.append((start,corehi.copy()));corehi[k]=cuthi[k]
                remainder=remaining
                if len(remainder)>200000:raise ValueError(error+' (coverage budget exceeded)')
                if not remainder:break
            uncovered=sum(float(np.prod(high-low)) for low,high in remainder)
            if uncovered>max(1e-10,volume*1e-6):raise ValueError(error+' (uncovered native trim)')
            covered+=volume
        lower[axis]=lo[axis];upper[axis]=hi[axis]
    return dict(semantic_bounds_m=expected.tolist(),native_bounds_m=actual.tolist(),covered_trim_volume_m3=covered)


def verify_door_pose(component,opening,points):
    angle=component['door_state']['angle_deg'];axis=opening['axis'];normal=1-axis
    direction=1 if component['id'].endswith('.leaf0') else -1
    swing=opening.get('swing_sign',-1 if '.east.' in component['id'] else 1)
    desired=np.zeros(2);desired[axis]=direction*math.cos(math.radians(angle));desired[normal]=swing*math.sin(math.radians(angle))
    vertices=np.asarray(component['vertices_m'],float);tangent=vertices[1,:2]-vertices[0,:2]
    if not np.allclose(tangent/np.linalg.norm(tangent),desired,rtol=0,atol=1e-7):
        raise ValueError('door pose disagrees with semantic state: '+component['id'])
    from .solid_geometry import face_planes
    for anchor,normal in face_planes(vertices.tolist()):
        distances=(points-anchor)@normal
        if abs(distances.max())>1e-7:
            raise ValueError('door pose disagrees with actual mesh: '+component['id'])


def _build_index(source,canonical,expected):
    if MASTER not in expected or len(expected)!=16:raise ValueError('the complete 16-file template is required')
    for name,sha in expected.items():
        if Path(name).name!=name or not name.endswith('.k'):raise ValueError('invalid template file name')
        if file_sha256(source/name)!=sha:raise ValueError('source SHA256 mismatch: '+name)
    master=native_blocks((source/MASTER).read_text(encoding='utf8'))
    included=[row.strip() for key,rows in master if key=='*INCLUDE' for row in rows]
    if len(included)!=15 or set(included)!=set(expected)-{MASTER}:raise ValueError('template include graph mismatch')
    model=json.loads(canonical.read_text(encoding='utf8'));g=_geometry(source)
    all_cells=np.array([[g['building_nodes'][int(n)] for n in e[2:]] for e in g['building_elements']])
    props=part_records(source/'solid-properties.k');components={}
    by_pid={}
    for e in g['building_elements']:by_pid.setdefault(int(e[1]),[]).append(e)
    for row in model['components']:
        if row.get('mesh_owner')!='building' or row.get('export_policy')!='physical':continue
        cid=row['component_id']
        if cid in components or cid not in props:raise ValueError('missing or ambiguous component: '+cid)
        pid=props[cid][0];els=np.array(by_pid.get(pid,[]),dtype=np.int32)
        if not len(els):raise ValueError('component has no actual Hex8: '+cid)
        nids=sorted(set(map(int,els[:,2:].ravel())))
        xyz={n:g['building_nodes'][n] for n in nids}
        reconciliation=verify_native_envelope(row,np.asarray(list(xyz.values())),all_cells,g['building_elements'][:,1],pid)
        if row['role']=='door':
            opening=next(o for o in model['openings'] if o['id']==row['host_opening_id'])
            verify_door_pose(row,opening,np.asarray(list(xyz.values())))
        points=np.array([[xyz[int(n)] for n in e[2:]] for e in els])
        det=np.einsum('ij,ij->i',np.cross(points[:,1]-points[:,0],points[:,3]-points[:,0]),points[:,4]-points[:,0])
        if np.any(det<=0):raise ValueError('nonpositive Hex8: '+cid)
        components[cid]=dict(deepcopy(row),part_id=pid,node_ids=nids,element_ids=list(map(int,els[:,0])),
                            native_bounds_m=_bounds(xyz),native_reconciliation=reconciliation)
    if set(props)!=set(components) or set(by_pid)!={r['part_id'] for r in components.values()}:
        raise ValueError('unmapped actual building Part')
    index=installation_index(source/'installation.k',components)
    air_nodes=read_nodes(source/'air-tnt-grid.k');air_els=read_solids(source/'air-tnt-grid.k')
    air_bounds=_bounds(air_nodes);building_bounds=_bounds(g['building_nodes']);ground_bounds=_bounds(g['ground_nodes'])
    grade=ground_bounds[5];air_parts=part_records(source/'air-tnt-mm.k');ground_parts=part_records(source/'ground-solver.k')
    def air_role(prefix):
        matches=[r for name,r in air_parts.items() if name.startswith(prefix)]
        if len(matches)!=1:raise ValueError('ambiguous fluid Part '+prefix)
        return matches[0]
    a,t,v=air_role('AIR'),air_role('TNT'),air_role('VACUUM')
    if len(ground_parts)!=1:raise ValueError('one fixed concrete ground Part required')
    ground=next(iter(ground_parts.values()))
    mm=native_blocks((source/'air-tnt-mm.k').read_text(encoding='utf8'))
    density=float(next(rows for key,rows in mm if key=='*MAT_HIGH_EXPLOSIVE_BURN')[0].split(',')[1])
    initial=next(rows for key,rows in native_blocks((source/'scene-initial.k').read_text(encoding='utf8')) if key=='*INITIAL_DETONATION')
    firing=list(map(float,fields(initial[0])))
    openings={r['id']:deepcopy(r) for r in model['openings']}
    leaves={cid:dict(opening_id=c['host_opening_id'],elevator=c.get('connection_profile')=='elevator_door_frame')
            for cid,c in components.items() if c['role']=='door'}
    for row in openings.values():row['elevator']=any(v['elevator'] and v['opening_id']==row['id'] for v in leaves.values())
    rooms={r['id']:dict(deepcopy(r),eligible=r.get('kind') not in ('balcony','stair','stairs','stairwell','elevator','shaft')) for r in model['rooms']}
    margins=dict(zip(('xmin','xmax','ymin','ymax','top'),
                    (building_bounds[0]-air_bounds[0],air_bounds[3]-building_bounds[3],
                     building_bounds[1]-air_bounds[1],air_bounds[4]-building_bounds[4],air_bounds[5]-building_bounds[5])))
    if min(margins.values())<=0:raise ValueError('air must enclose the building')
    metadata=dict(tnt_density_kg_m3=density,default_location_xy_m=firing[1:3],
                  default_mesh=dict(margins_m=margins,background_cell_m=.75,charge_cell_m=.0125,
                                    room_cell_m=.75,opening_cell_m=.75),rooms=rooms,openings=openings,door_leaves=leaves)
    ids=dict(air_part_id=a[0],section_id=a[1],air_material_id=a[2],air_eos_id=a[3],
             tnt_part_id=t[0],tnt_material_id=t[2],tnt_eos_id=t[3],void_part_id=v[0],vacuum_material_id=v[2],
             ground_part_id=ground[0],node_start=min(air_nodes),element_start=int(air_els[:,0].min()),
             master_part_set_id=9600101,fill_part_set_id=9600102,coupled_mmg_set_id=9600103)
    for key,rows in native_blocks((source/'ground-fsi-mm.k').read_text(encoding='utf8')):
        if key=='*SET_PART_LIST_TITLE':ids['master_part_set_id']=int(fields(rows[1])[0])
        elif key=='*SET_MULTI-MATERIAL_GROUP_LIST_TITLE':ids['coupled_mmg_set_id']=int(fields(rows[1])[0])
    geometry_metadata=dict(building_bounds_m=building_bounds,ground_bounds_m=ground_bounds,
                           air_bounds_m=air_bounds,grade_m=grade,
                           buffer_z=sorted({p[2] for p in air_nodes.values() if p[2]<grade}))
    payload=dict(schema_version=SCHEMA,files=dict(expected),canonical_sha256=file_sha256(canonical),
                 rooms=rooms,openings=openings,components=components,metadata=metadata,native_ids=ids,
                 geometry_metadata=geometry_metadata,installation_index=index)
    return payload


def register_blast_template(destination: Path,source: Path,canonical: Path,*,expected_sha256: dict[str,str]) -> dict:
    destination,source,canonical=Path(destination),Path(source),Path(canonical)
    if destination.exists():raise FileExistsError('preserve existing template')
    payload=_build_index(source,canonical,expected_sha256)
    sealed=dict(template_id='three-storey-reference',template_fingerprint=fingerprint(payload),payload=payload)
    destination.mkdir(parents=True,exist_ok=False)
    for name in expected_sha256:shutil.copyfile(source/name,destination/name)
    (destination/INDEX).write_text(json.dumps(sealed,ensure_ascii=False,sort_keys=True,allow_nan=False),encoding='utf8')
    # Catch source changes while the registration copy was in progress.
    for name,sha in expected_sha256.items():
        if file_sha256(source/name)!=sha or file_sha256(destination/name)!=sha:raise ValueError('source changed during registration')
    return dict(template_id=sealed['template_id'],template_fingerprint=sealed['template_fingerprint'],
                component_count=len(payload['components']),source_k_files=len(expected_sha256))


def load_blast_template(directory: Path) -> dict:
    root=Path(directory).resolve();sealed=json.loads((root/INDEX).read_text(encoding='utf8'))
    payload=sealed['payload']
    if payload['schema_version']!=SCHEMA or fingerprint(payload)!=sealed['template_fingerprint']:
        raise ValueError('template semantic index checksum mismatch')
    result=deepcopy(payload);result.update(root=root,template_id=sealed['template_id'],template_fingerprint=sealed['template_fingerprint'])
    result['metadata'].update(template_id=sealed['template_id'],template_fingerprint=sealed['template_fingerprint'])
    verify_blast_template(result)
    result['geometry']=dict(_geometry(root),**payload['geometry_metadata'])
    return result


def verify_blast_template(template: dict) -> None:
    root=template['root']
    sealed=json.loads((root/INDEX).read_text(encoding='utf8'))
    if fingerprint(sealed['payload'])!=template['template_fingerprint']:
        raise ValueError('template semantic index changed')
    for name,sha in template['files'].items():
        if Path(name).name!=name or file_sha256(root/name)!=sha:raise ValueError('template file checksum mismatch: '+name)
