"""Verified retained native data audit; reads inputs, never generates or solves.

Only axis-aligned, positive Hex8 cells are eligible for rectangular plate/column
mapping. Source bounds are diagnostics, never substituted for actual cells.
"""
from collections import defaultdict
import hashlib
from itertools import product
import json
import math
from pathlib import Path
import zipfile
import numpy as np
from .contracts import fingerprint

FILES=('materials-solver.k','solids-solver.k','solid-properties.k','reinforcement.k','installation.k','ground-solver.k')


def blocks(text):
    keyword=None;rows=[]
    for raw in text.splitlines():
        line=raw.rstrip()
        if not line.strip() or line.lstrip().startswith('$'):continue
        if line.startswith('*'):
            if keyword:yield keyword,rows
            keyword=line.upper();rows=[]
        else:rows.append(line)
    if keyword:yield keyword,rows


def values(line,width=8):
    return [v.strip() for v in line.split(',')] if ',' in line else [line[i:i+width].strip() for i in range(0,len(line),width)]


def parse_mesh(text,kind):
    nodes={};elements=[];parts={};sections={}
    for keyword,rows in blocks(text):
        if keyword in ('*NODE','*NODE+'):
            for line in rows:
                if ',' in line:v=values(line)
                else:
                    first,width=(20,20) if keyword.endswith('+') else (8,16)
                    v=[line[:first]]+[line[first+i*width:first+(i+1)*width] for i in range(3)]
                tag=int(v[0]);xyz=tuple(float(x) for x in v[1:4])
                if tag in nodes or len(xyz)!=3 or not all(math.isfinite(x) for x in xyz):raise ValueError('invalid/duplicate native node')
                nodes[tag]=xyz
        elif keyword=='*ELEMENT_'+kind:
            for line in rows:
                v=tuple(map(int,values(line)))
                if len(v)<(10 if kind=='SOLID' else 4):raise ValueError('native connectivity length')
                elements.append(v[:10] if kind=='SOLID' else v[:4])
        elif keyword=='*PART':
            v=values(rows[1]);parts[int(v[0])]=dict(title=rows[0],section=int(v[1]),material=int(v[2]))
        elif keyword=='*SECTION_BEAM':
            first,second=values(rows[0]),values(rows[1]);d=float(second[0])
            if int(first[3])!=2 or d<=0 or not math.isclose(d,float(second[1]),abs_tol=1e-12):raise ValueError('circular native rebar section required')
            sections[int(first[0])]=d
    if len(nodes)>1_000_000 or len(elements)>500_000:raise ValueError('native mesh audit budget')
    return nodes,elements,parts,sections


def parse_materials(text):
    result={}
    for keyword,rows in blocks(text):
        if keyword.startswith(('*MAT_ELASTIC','*MAT_PLASTIC_KINEMATIC','*MAT_CONCRETE_DAMAGE_REL3')):
            v=values(rows[1] if '_TITLE' in keyword else rows[0]);mid=int(v[0])
            result[mid]=dict(density=float(v[1]),model=keyword,
                             elastic_e_pa=None if 'CONCRETE_DAMAGE' in keyword else float(v[2]))
    return result


def stair_hosts(cid,components):
    return sorted(k for k,c in components.items() if k.startswith(cid+'.') and c['role'] in ('stair','landing') and c['material']=='concrete')


def measure_hexes(points):
    """2x2x2 native Hex8 integration: V, integral(x), integral(xx^T)."""
    p=np.asarray(points,dtype=float)
    signs=np.array([[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]])
    gps=np.array(list(product((-1/math.sqrt(3),1/math.sqrt(3)),repeat=3)))
    factors=1+gps[:,None,:]*signs[None,:,:]
    shape=np.prod(factors,axis=2)/8
    deriv=np.empty((8,8,3))
    for d in range(3):deriv[:,:,d]=signs[None,:,d]*np.prod(factors[:,:,[j for j in range(3) if j!=d]],axis=2)/8
    jac=np.einsum('eni,gnj->egij',p,deriv);det=np.linalg.det(jac)
    if not np.isfinite(det).all() or np.any(det<=0):raise ValueError('nonpositive native Hex8 Jacobian')
    x=np.einsum('gn,eni->egi',shape,p)
    return det.sum(axis=1),np.einsum('eg,egi->ei',det,x),np.einsum('eg,egi,egj->eij',det,x,x)


def audit_archive(archive):
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if len(names)!=len(set(names)) or set(names)!=set(FILES)|{'structural-template.json'}:raise ValueError('unexpected native archive members')
        if any(i.file_size>60_000_000 for i in z.infolist()) or sum(i.file_size for i in z.infolist())>200_000_000:raise ValueError('native archive budget')
        sealed=json.loads(z.read('structural-template.json'));payload=sealed['payload']
        if fingerprint(payload)!=sealed['template_fingerprint']:raise ValueError('semantic checksum mismatch')
        raw={}
        for name in FILES:
            data=z.read(name)
            if hashlib.sha256(data).hexdigest()!=payload['files'][name]:raise ValueError('native file checksum mismatch: '+name)
            if name not in ('installation.k','ground-solver.k'):raw[name]=data.decode('utf8')
    sn,se,_,_=parse_mesh(raw['solids-solver.k'],'SOLID')
    rn,re,rp,rs=parse_mesh(raw['reinforcement.k'],'BEAM')
    _,_,sp,_=parse_mesh(raw['solid-properties.k'],'SOLID')
    materials=parse_materials(raw['materials-solver.k'])
    bypart=defaultdict(list)
    for row in se:bypart[row[1]].append(row[2:])
    rebars=defaultdict(list)
    for row in re:rebars[row[1]].append(row[2:4])
    mapped=defaultdict(dict);unmapped=[]
    for pid,part in rp.items():
        if '.rebar.' not in part['title']:unmapped.append(pid);continue
        cid,role=part['title'].rsplit('.rebar.',1)
        if cid not in payload['components'] and not stair_hosts(cid,payload['components']):raise ValueError('rebar refers to missing semantic component/assembly')
        d=rs[part['section']];area=math.pi*d*d/4;length=0.;axis_lengths=[0.]*3;oblique=0;lines={};first=np.zeros(3);second=np.zeros((3,3))
        for tags in rebars[pid]:
            x,y=np.array(rn[tags[0]]),np.array(rn[tags[1]]);delta=y-x;size=float(np.linalg.norm(delta))
            if not size>0:raise ValueError('zero native rebar segment')
            center=(x+y)/2;unit=delta/size
            first+=size*center
            second+=size*(np.outer(center,center)+np.outer(delta,delta)/12+(np.eye(3)-np.outer(unit,unit))*d*d/16)
            length+=size;axis=int(np.argmax(np.abs(delta)))
            if np.count_nonzero(np.abs(delta)>1e-8)!=1:oblique+=1;continue
            axis_lengths[axis]+=size;other=[k for k in range(3) if k!=axis]
            key=(axis,*[round(float(x[k]),9) for k in other])
            line=lines.setdefault(key,dict(axis=axis,coordinates_m=[float(x[k]) for k in other],length_m=0.,min_m=float(min(x[axis],y[axis])),max_m=float(max(x[axis],y[axis]))))
            line['length_m']+=size;line['min_m']=min(line['min_m'],float(min(x[axis],y[axis])));line['max_m']=max(line['max_m'],float(max(x[axis],y[axis])))
        if role in mapped[cid]:raise ValueError('duplicate native rebar role')
        mapped[cid][role]=dict(part_id=pid,material_id=part['material'],diameter_m=d,length_m=length,
                               volume_m3=area*length,axis_lengths_m=axis_lengths,oblique_segments=oblique,lines=list(lines.values()),
                               centroid_m=(first/length).tolist(),second_m2=(second/length).tolist())
    components={};node_parts=defaultdict(set)
    for cid,c in payload['components'].items():
        pid=c['part_id'];cells=bypart[pid]
        if not cells:raise ValueError('native component missing solid cells: '+cid)
        volume=0.;bad=0;nodeids=set();cell_bounds=[];first=np.zeros(3);second=np.zeros((3,3));non_box_indices=[];non_box_points=[]
        for cell in cells:
            if len(set(cell))!=8:raise ValueError('native cell not Hex8')
            nodeids.update(cell);x=np.array([sn[n] for n in cell]);lo=x.min(axis=0);hi=x.max(axis=0)
            rounded={tuple(round(float(v),9) for v in row) for row in x}
            expected=set(product(*[(round(float(a),9),round(float(b),9)) for a,b in zip(lo,hi)]))
            cell_bounds.append([*lo.tolist(),*hi.tolist()])
            if rounded!=expected or np.any(hi<=lo):
                bad+=1;non_box_indices.append(len(cell_bounds)-1);non_box_points.append(x);continue
            v=float(np.prod(hi-lo));center=(lo+hi)/2
            volume+=v;first+=v*center;second+=v*(np.outer(center,center)+np.diag((hi-lo)**2/12))
        if non_box_points:
            vv,ff,ss=measure_hexes(non_box_points);volume+=float(vv.sum());first+=ff.sum(axis=0);second+=ss.sum(axis=0)
        for n in nodeids:node_parts[n].add(cid)
        bounds=np.array([sn[n] for n in nodeids]);lo=bounds.min(axis=0);hi=bounds.max(axis=0)
        groups=mapped.get(cid,{})
        steel=sum(v['volume_m3'] for v in groups.values());rho=materials[sp[pid]['material']]['density']
        steel_mass=sum(v['volume_m3']*materials[v['material_id']]['density'] for v in groups.values())
        # Original embedded steel replaces the same host volume. This component
        # ledger is provisional until cross-part anchorage/host clipping is checked.
        mass=rho*(volume-steel)+steel_mass
        components[cid]=dict(role=c['role'],material=c['material'],level=c.get('level'),part_id=pid,
            native_bounds_m=[*lo.tolist(),*hi.tolist()],solid_volume_m3=volume,steel_volume_m3=steel,
            host_density_kg_m3=rho,mass_kg=mass,mesh_node_count=len(nodeids),solid_cells=len(cells),
            non_box_cells=bad,non_box_indices=non_box_indices,box_volume_m3=float(np.prod(hi-lo)),rebar=groups,
            solid_centroid_m=(first/volume).tolist(),solid_second_m2=(second/volume).tolist(),
            material_id=sp[pid]['material'],cell_bounds_m=cell_bounds)
    assemblies={}
    for cid,groups in mapped.items():
        if cid in components:continue
        members=stair_hosts(cid,components)
        densities={components[k]['host_density_kg_m3'] for k in members}
        if len(densities)!=1:raise ValueError('assembly steel host has mixed densities')
        rho=densities.pop()
        correction=sum(v['volume_m3']*(materials[v['material_id']]['density']-rho) for v in groups.values())
        assemblies[cid]=dict(members=members,rebar=groups,mass_adjustment_kg=correction)
    shared=defaultdict(int)
    for ids in node_parts.values():
        ids=sorted(ids)
        for i,a in enumerate(ids):
            for b in ids[i+1:]:shared[(a,b)]+=1
    return dict(schema_version='cpu-response.native-audit@1',template_id=sealed['template_id'],
                template_fingerprint=sealed['template_fingerprint'],native_files_verified=True,files=payload['files'],
                components=components,materials=materials,shared_node_pairs=[dict(a=a,b=b,count=n) for (a,b),n in sorted(shared.items())],
                native_counts=dict(solid_nodes=len(sn),solid_elements=len(se),rebar_nodes=len(rn),rebar_elements=len(re)),
                assembly_rebar=assemblies,mass_total_kg=sum(c['mass_kg'] for c in components.values())+sum(a['mass_adjustment_kg'] for a in assemblies.values()),
                unmapped_rebar_parts=unmapped,ready_to_solve=False,
                limitations=['cross_part_steel_host_and_overlap_not_yet_verified','native_connections_not_assumed_from_bounds'])
