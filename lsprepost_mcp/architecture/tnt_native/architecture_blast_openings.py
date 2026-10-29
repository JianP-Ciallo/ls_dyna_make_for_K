"""Derive only declared door/glass edits from the retained physical mesh."""
from copy import deepcopy
import math
import numpy as np

from .solid_geometry import interiors_overlap
from .architecture_blast_template import native_blocks, fields
from .support import _coordinate_token


def _text(blocks):
    return ''.join(key+'\n'+'\n'.join(rows)+'\n' for key,rows in blocks)


def _native_geometry(nodes,elements):
    return '*NODE+\n'+''.join(str(n)+','+','.join(_coordinate_token(format(v,'.17g')) for v in p)+'\n' for n,p in nodes.items())+\
        '*ELEMENT_SOLID\n'+''.join(','.join(map(str,e))+'\n' for e in elements)


def _check_installation(index,components,nodes):
    xyz={**nodes,**{int(n):p for n,p in index['auxiliary_nodes'].items()}}
    assigned=set()
    for body in index['rigid_bodies']:
        members=index['sets'][str(body['set_id'])]['members']
        if assigned.intersection(members):raise ValueError('conflicting rigid node membership')
        if any(n not in xyz for n in members):raise ValueError('dangling rigid node reference')
        assigned.update(members)
    for row in index['interpolations']:
        if row['source_node_id'] not in xyz or any(n not in xyz for n,w in row['weights']):
            raise ValueError('dangling interpolation reference')
        weights=row['weights']
        if abs(sum(w for n,w in weights)-1)>1e-8:raise ValueError('interpolation weights do not close')
        p=np.sum([np.asarray(xyz[n])*w for n,w in weights],axis=0)
        if not np.allclose(p,xyz[row['source_node_id']],atol=1e-7,rtol=0):raise ValueError('interpolation geometry does not close')
    for row in index['joints']:
        a,b,c,d=[np.asarray(xyz[n]) for n in row['node_ids']]
        if not np.allclose(a,b,atol=1e-9,rtol=0) or not np.allclose(c,d,atol=1e-9,rtol=0):
            raise ValueError('hinge joint axes do not coincide')
        if np.linalg.norm(c-a)<1e-6:raise ValueError('degenerate hinge axis')
        leaf=components[row['source_component_id']]
        axis=np.asarray(leaf['hinge_points_m'][0])
        if not np.allclose(a[:2],axis[:2],atol=1e-9,rtol=0):raise ValueError('hinge differs from original axis')


def derive_blast_openings(template:dict,opening_states:dict[str,str])->dict:
    components=deepcopy(template['components']);g=dict(template['geometry'])
    nodes=dict(g['building_nodes']);elements=g['building_elements'].copy()
    index=deepcopy(template['installation_index']);removed=set();moved=set();rotated=[]
    for cid,state in opening_states.items():
        if cid in template['metadata']['door_leaves']:
            c=components[cid];elevator=template['metadata']['door_leaves'][cid]['elevator']
            if state not in ('keep','closed','open_90'):raise ValueError('invalid door state')
            if elevator:
                if state=='open_90':raise ValueError('elevator doors remain closed')
                continue
            if state=='keep':continue
            angle=0. if state=='closed' else 90.
            if angle==c['door_state']['angle_deg']:continue
            opening=template['openings'][c['host_opening_id']];axis=opening['axis'];normal=1-axis
            direction=1 if cid.endswith('.leaf0') else -1
            swing=opening.get('swing_sign',-1 if '.east.' in cid else 1)
            target=np.zeros(2);target[axis]=direction*math.cos(math.radians(angle));target[normal]=swing*math.sin(math.radians(angle))
            v=np.asarray(c['vertices_m'][1])-c['vertices_m'][0]
            delta=math.atan2(target[1],target[0])-math.atan2(v[1],v[0]);co,si=math.cos(delta),math.sin(delta)
            matrix=np.array([[co,-si],[si,co]]);pivot=np.asarray(c['hinge_points_m'][0][:2])
            def rotate(p):
                q=list(p);q[:2]=(matrix@(np.asarray(p[:2])-pivot)+pivot).tolist();return q
            owned=set(c['node_ids'])
            if any(owned.intersection(r['node_ids']) for other,r in components.items() if other!=cid):
                raise ValueError('door leaf shares movable nodes with another component')
            for n in owned:nodes[n]=rotate(nodes[n])
            c['vertices_m']=[rotate(p) for p in c['vertices_m']]
            pts=np.array([nodes[n] for n in c['node_ids']]);c['bounds_m']=c['native_bounds_m']=[*pts.min(0).tolist(),*pts.max(0).tolist()]
            c['door_state']=dict(angle_deg=angle,latched=False);moved.update(owned);rotated.append(cid)
        elif cid in template['openings'] and template['openings'][cid]['kind']=='window':
            if state not in ('keep_glass','clear_opening'):raise ValueError('invalid window state')
            if state=='clear_opening':removed.update(c for c,r in components.items() if r['role']=='glass' and r.get('host_opening_id')==cid)
        else:raise ValueError('unknown opening or leaf: '+cid)
    # Collision uses actual cells, including other derived leaves, with a cheap AABB prefilter.
    for cid in rotated:
        pid=components[cid]['part_id'];leafcells=elements[elements[:,1]==pid]
        others=elements[elements[:,1]!=pid];otherpoints=np.array([[nodes[int(n)] for n in e[2:]] for e in others])
        lows=otherpoints.min(1);highs=otherpoints.max(1)
        for e in leafcells:
            points=np.array([nodes[int(n)] for n in e[2:]]);lo=points.min(0);hi=points.max(0)
            candidates=otherpoints[np.all(highs>lo+1e-9,axis=1)&np.all(lows<hi-1e-9,axis=1)]
            if any(interiors_overlap(points.tolist(),p.tolist(),tolerance=1e-9) for p in candidates):
                raise ValueError('door collision: '+cid)
    replacements={};removed_pids={components[c]['part_id'] for c in removed}
    if removed:
        elements=elements[~np.isin(elements[:,1],list(removed_pids))]
        retained=set(map(int,elements[:,2:].ravel()));nodes={n:p for n,p in nodes.items() if n in retained}
        blocks=native_blocks((template['root']/'installation.k').read_text(encoding='utf8'));drop=set()
        for row in index['interpolations']:
            if row['source_component_id'] in removed:drop.add(row['block'])
            elif any(n not in nodes for n,w in row['weights']):raise ValueError('retained interpolation depends on removed glass')
        for body in index['rigid_bodies']:
            if set(body['component_ids']).intersection(removed):
                if set(body['component_ids'])-removed:raise ValueError('glass rigid body includes another component')
                drop.update((body['block'],index['sets'][str(body['set_id'])]['block']))
        index['interpolations']=[r for r in index['interpolations'] if r['block'] not in drop]
        index['rigid_bodies']=[r for r in index['rigid_bodies'] if r['block'] not in drop]
        index['sets']={k:v for k,v in index['sets'].items() if v['block'] not in drop}
        if any(r['source_component_id'] in removed for r in index['joints']):raise ValueError('unexpected glass revolute reference')
        replacements['installation.k']=_text([r for i,r in enumerate(blocks) if i not in drop])
        remap={old:new for new,old in enumerate(i for i in range(len(blocks)) if i not in drop)}
        for record in [*index['interpolations'],*index['rigid_bodies'],*index['joints'],*index['sets'].values()]:
            record['block']=remap[record['block']]
        props=native_blocks((template['root']/'solid-properties.k').read_text(encoding='utf8'))
        replacements['solid-properties.k']=_text([(k,r) for k,r in props if not (k in ('*PART','*PART_TITLE') and r[0].strip() in removed)])
        # The classification file only owns typed part sets; no numeric text replacement.
        groups=[]
        for key,rows in native_blocks((template['root']/'part-groups-air.k').read_text(encoding='utf8')):
            if key!='*SET_PART_LIST_TITLE':raise ValueError('unsupported group reference card: '+key)
            ids=[int(v) for r in rows[2:] for v in fields(r,8) if v and int(v)>0]
            ids=[n for n in ids if n not in removed_pids]
            if ids:groups.append((key,rows[:2]+[','.join(map(str,ids[i:i+8])) for i in range(0,len(ids),8)]))
        if groups:replacements['part-groups-air.k']=_text(groups)
        elif (template['root']/'part-groups-air.k').read_text().lstrip().startswith('*'):
            replacements['part-groups-air.k']='$ all classification sets removed\n'
        for cid in removed:components.pop(cid)
    g.update(building_nodes=nodes,building_elements=elements)
    _check_installation(index,components,nodes)
    if moved or removed:replacements['solids-solver.k']=_native_geometry(nodes,elements)
    return dict(geometry=g,components=components,installation_index=index,native_replacements=replacements,
                change_set=dict(moved_node_ids=sorted(moved),rotated_component_ids=sorted(rotated),
                                removed_component_ids=sorted(removed),removed_part_ids=sorted(removed_pids),
                                removed_node_ids=sorted(set(template['geometry']['building_nodes'])-set(nodes)),
                                changed_k_files=sorted(replacements)))
