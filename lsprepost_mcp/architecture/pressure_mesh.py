"""Small retained-Hex8 readers, independent of the refined blast package."""
from pathlib import Path
import numpy as np

HEX_FACES = np.array(((0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)))


def read_solids(path, maximum=500000):
    rows=[];keyword=''
    with Path(path).open(encoding='utf8') as stream:
        for line in stream:
            line=line.rstrip('\r\n')
            if not line.strip() or line.lstrip().startswith('$'):continue
            if line.startswith('*'):keyword=line.strip().upper();continue
            if keyword!='*ELEMENT_SOLID':continue
            values=line.split(',') if ',' in line else [line[i:i+8] for i in range(0,80,8)]
            row=list(map(int,values[:10]))
            if len(row)!=10 or len(set(row[2:]))!=8:raise ValueError('positive Hex8 required')
            rows.append(row)
            if len(rows)>maximum:raise ValueError('surface element budget exceeded')
    if not rows:raise ValueError('solid elements required')
    return np.array(rows,dtype=np.int32)


def read_nodes(path,wanted=None):
    nodes={};keyword=''
    with Path(path).open(encoding='utf8') as stream:
        for line in stream:
            line=line.rstrip('\r\n')
            if not line.strip() or line.lstrip().startswith('$'):continue
            if line.startswith('*'):keyword=line.strip().upper();continue
            if keyword not in ('*NODE','*NODE+'):continue
            if ',' in line:values=line.split(',')
            else:
                width=20 if keyword.endswith('+') else 16;first=20 if keyword.endswith('+') else 8
                values=[line[:first]]+[line[first+i*width:first+(i+1)*width] for i in range(3)]
            nid=int(values[0])
            if wanted is None or nid in wanted:nodes[nid]=tuple(map(float,values[1:4]))
    if wanted is not None and set(nodes)!=set(wanted):raise ValueError('missing requested nodes')
    return nodes


def exterior_faces(elements):
    connectivity=np.asarray(elements)[:,2:10]
    faces=connectivity[:,HEX_FACES].reshape(-1,4);keys=np.sort(faces,axis=1)
    _,indices,counts=np.unique(keys,axis=0,return_index=True,return_counts=True)
    if np.any(counts>2):raise ValueError('nonmanifold solid face')
    return faces[np.sort(indices[counts==1])]
