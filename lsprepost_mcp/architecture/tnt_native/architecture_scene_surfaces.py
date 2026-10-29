"""Bounded surface extraction from retained positive Hex8 connectivity."""
from pathlib import Path

import numpy as np


HEX_FACES = np.array(((0,3,2,1),(4,5,6,7),(0,1,5,4),
                      (1,2,6,5),(2,3,7,6),(3,0,4,7)))


def read_solids(path, maximum=500000):
    rows=[];keyword=''
    with Path(path).open(encoding='utf8') as stream:
        for line in stream:
            line=line.rstrip('\r\n')
            if not line.strip() or line.lstrip().startswith('$'): continue
            if line.startswith('*'): keyword=line.strip().upper();continue
            if keyword!='*ELEMENT_SOLID': continue
            values=line.split(',') if ',' in line else [line[i:i+8] for i in range(0,80,8)]
            row=list(map(int,values[:10]))
            if len(row)!=10 or len(set(row[2:]))!=8: raise ValueError('positive Hex8 required')
            rows.append(row)
            if len(rows)>maximum: raise ValueError('surface element budget exceeded')
    if not rows: raise ValueError('solid elements required')
    return np.array(rows,dtype=np.int32)


def read_nodes(path, wanted=None):
    nodes={};keyword=''
    with Path(path).open(encoding='utf8') as stream:
        for line in stream:
            line=line.rstrip('\r\n')
            if not line.strip() or line.lstrip().startswith('$'): continue
            if line.startswith('*'): keyword=line.strip().upper();continue
            if keyword not in ('*NODE','*NODE+'): continue
            if ',' in line: values=line.split(',')
            else:
                width=20 if keyword.endswith('+') else 16
                first=20 if keyword.endswith('+') else 8
                values=[line[:first]]+[line[first+i*width:first+(i+1)*width] for i in range(3)]
            nid=int(values[0])
            if wanted is None or nid in wanted:
                nodes[nid]=tuple(map(float,values[1:4]))
    if wanted is not None and set(nodes)!=set(wanted): raise ValueError('missing requested nodes')
    return nodes


def exterior_faces(elements):
    """Cancel shared faces across Parts, keeping outward element winding."""
    connectivity=np.asarray(elements)[:,2:10]
    faces=connectivity[:,HEX_FACES].reshape(-1,4)
    keys=np.sort(faces,axis=1)
    _,indices,counts=np.unique(keys,axis=0,return_index=True,return_counts=True)
    if np.any(counts>2): raise ValueError('nonmanifold solid face')
    return faces[np.sort(indices[counts==1])]


def convex_occupied_pieces(xyz,elements,grade=0):
    """Merge only exact adjoining orthogonal cells; keep sloping cells convex.

    The R12 concave surface fill misses volume in the bounded ring probe.
    Independent convex containers avoid that behavior without changing solids.
    """
    boxes=[];sloping=[];corner_ids={}
    original_volume=0
    for element in elements:
        ns=list(map(int,element[2:]));points=np.array([xyz[n] for n in ns])
        if points[:,2].max()<=grade+1e-12: continue
        rounded=np.round(points,9);lo=rounded.min(axis=0);hi=rounded.max(axis=0)
        orthogonal=np.all((abs(rounded-lo)<1e-12)|(abs(rounded-hi)<1e-12))
        if orthogonal:
            boxes.append(tuple(lo)+tuple(hi));original_volume+=float(np.prod(hi-lo))
            for nid,p in zip(ns,rounded): corner_ids.setdefault(tuple(p),nid)
        else:
            faces=[]
            for indices in HEX_FACES:
                p=points[indices];normal=np.cross(p[1]-p[0],p[2]-p[0])
                scale=np.linalg.norm(normal)
                if scale<1e-15 or abs(normal@(p[3]-p[0]))>scale*1e-8:
                    raise ValueError('occupied sloping Hex has a degenerate or nonplanar face')
                if np.max((points-p[0])@normal)>scale*1e-8:
                    raise ValueError('occupied sloping Hex is not convex')
                faces.append(tuple(ns[int(i)] for i in indices))
            sloping.append(faces)
    # A merge consumes precisely adjacent boxes with identical transverse bounds.
    # Repeated axis passes also handle a grid with different neighboring widths.
    previous=-1
    while previous!=len(boxes):
        previous=len(boxes)
        for axis in range(3):
            other=[a for a in range(6) if a not in (axis,axis+3)]
            boxes.sort(key=lambda b:tuple(b[a] for a in other)+(b[axis],b[axis+3]))
            merged=[]
            for box in boxes:
                if (merged and all(merged[-1][a]==box[a] for a in other)
                        and merged[-1][axis+3]==box[axis]):
                    value=list(merged[-1]);value[axis+3]=box[axis+3];merged[-1]=tuple(value)
                else: merged.append(box)
            boxes=merged
    merged_volume=sum(np.prod(np.array(b[3:])-b[:3]) for b in boxes)
    if not np.isclose(merged_volume,original_volume,rtol=1e-10,atol=1e-9):
        raise ValueError('occupied box merge changed solid volume')
    pieces=[]
    for x,y,z,X,Y,Z in boxes:
        corners=((x,y,z),(X,y,z),(X,Y,z),(x,Y,z),(x,y,Z),(X,y,Z),(X,Y,Z),(x,Y,Z))
        try: ns=[corner_ids[p] for p in corners]
        except KeyError as exc: raise ValueError('merged box corner absent from real source') from exc
        pieces.append([tuple(ns[int(i)] for i in face) for face in HEX_FACES])
    if len(pieces)+len(sloping)>100000: raise ValueError('occupied container budget exceeded')
    return pieces+sloping


def _rect(xyz,face):
    points=np.array([xyz[int(n)] for n in face]);lo=points.min(axis=0);hi=points.max(axis=0)
    axes=np.flatnonzero(hi-lo<1e-9)
    if len(axes)!=1: raise ValueError('contact requires axis-aligned quad faces')
    axis=int(axes[0]);uv=[i for i in range(3) if i!=axis]
    normal=np.cross(points[1]-points[0],points[2]-points[0])[axis]
    return axis,round(float(lo[axis]),9),int(np.sign(normal)),lo[uv],hi[uv]


def coincident_contact(foundation,foundation_faces,ground,ground_faces):
    """Only complete coincident, oppositely facing patches become tied contact."""
    planes={}
    for face in ground_faces:
        a,p,s,lo,hi=_rect(ground,face)
        planes.setdefault((a,p,s),[]).append((face,lo,hi))
    nodes=set();segments={}
    for face in foundation_faces:
        a,p,s,lo,hi=_rect(foundation,face)
        candidates=planes.get((a,p,-s),[])
        if not candidates: continue
        lows=np.array([r[1] for r in candidates]);highs=np.array([r[2] for r in candidates])
        widths=np.maximum(0,np.minimum(hi,highs)-np.maximum(lo,lows))
        areas=widths.prod(axis=1);intersect=np.flatnonzero(areas>1e-15)
        if not len(intersect): continue
        if abs(float(areas.sum())-float(np.prod(hi-lo)))>1e-8:
            raise ValueError('partial foundation contact is not an ideal coincident bond')
        nodes.update(map(int,face))
        for i in intersect:
            f=candidates[int(i)][0]
            segments[tuple(sorted(map(int,f)))]=tuple(map(int,f))
    if not nodes or not segments: raise ValueError('no actual coincident foundation contact')
    return sorted(nodes),list(segments.values())


def outer_fluid_faces(plan):
    xs,ys,zs=plan['axes'];nx,ny,nz=len(xs)-1,len(ys)-1,len(zs)-1
    def n(i,j,k): return plan['node_start']+k*(nx+1)*(ny+1)+j*(nx+1)+i
    sides=[]
    for k in range(nz):
        for j in range(ny):
            sides.extend(((n(0,j,k),n(0,j+1,k),n(0,j+1,k+1),n(0,j,k+1)),
                          (n(nx,j,k),n(nx,j,k+1),n(nx,j+1,k+1),n(nx,j+1,k))))
        for i in range(nx):
            sides.extend(((n(i,0,k),n(i,0,k+1),n(i+1,0,k+1),n(i+1,0,k)),
                          (n(i,ny,k),n(i+1,ny,k),n(i+1,ny,k+1),n(i,ny,k+1))))
    top=[(n(i,j,nz),n(i,j+1,nz),n(i+1,j+1,nz),n(i+1,j,nz))
         for j in range(ny) for i in range(nx)]
    bottom=[(n(i,j,0),n(i+1,j,0),n(i+1,j+1,0),n(i,j+1,0))
            for j in range(ny) for i in range(nx)]
    return sides,top,bottom
