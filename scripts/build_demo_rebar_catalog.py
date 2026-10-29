"""Read retained K reinforcement into small layout rules; never builds/solves a model."""
from collections import defaultdict
import argparse
import hashlib
import json
from pathlib import Path
from statistics import median
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def values(line):
    return line.split(',') if ',' in line else [line[i:i+8] for i in range(0,len(line),8)]

def blocks(text):
    key=None;rows=[]
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('$'):continue
        if line.startswith('*'):
            if key:yield key,rows
            key=line.strip();rows=[]
        else:rows.append(line.rstrip())
    if key:yield key,rows

def spacing(positions):
    p=sorted(set(round(v,8) for v in positions))
    gaps=[b-a for a,b in zip(p,p[1:]) if b-a>1e-5]
    return median(gaps) if gaps else None

def extract(archive):
    with zipfile.ZipFile(archive) as z:
        sealed=json.loads(z.read('structural-template.json'));metadata=sealed['payload'];raw=z.read('reinforcement.k');materials=z.read('materials-solver.k')
    sha=lambda b:hashlib.sha256(b).hexdigest()
    assert sha(raw)==metadata['files']['reinforcement.k']
    assert sha(materials)==metadata['files']['materials-solver.k']
    nodes={};elements=[];parts={};sections={}
    for key,rows in blocks(raw.decode('utf-8-sig')):
        if key in ('*NODE','*NODE+'):
            for row in rows:
                v=values(row);nodes[int(v[0])]=tuple(float(x) for x in v[1:4])
        elif key=='*ELEMENT_BEAM':
            elements.extend(tuple(int(x) for x in values(row)[:4]) for row in rows)
        elif key=='*PART':
            p=values(rows[1]);parts[int(p[0])]=(rows[0],int(p[1]),int(p[2]))
        elif key=='*SECTION_BEAM':sections[int(values(rows[0])[0])]=float(values(rows[1])[0])
    steel=None
    for key,rows in blocks(materials.decode('utf-8-sig')):
        if key.startswith('*MAT_PLASTIC_KINEMATIC'):
            p=values(rows[1] if '_TITLE' in key else rows[0])
            if int(p[0])==9001:
                steel=dict(id=9001,density=float(p[1]),elasticModulus=float(p[2]),yieldStress=float(p[4]),hardeningModulus=float(p[5]),failureStrain=float(values(rows[2])[2]))
    assert steel and steel['failureStrain']>0
    # Keep a physical straight line once, independently of the source mesh subdivision.
    lines=defaultdict(dict);oblique=defaultdict(list)
    for _,pid,a,b in elements:
        x,y=nodes[a],nodes[b];delta=[y[k]-x[k] for k in range(3)];axes=[k for k in range(3) if abs(delta[k])>1e-8]
        if len(axes)==1:
            axis=axes[0];key=(axis,*(round(x[k],8) for k in range(3) if k!=axis));lo,hi=sorted((x[axis],y[axis]));old=lines[pid].get(key)
            lines[pid][key]=(min(lo,old[0]),max(hi,old[1])) if old else (lo,hi)
        elif axes:oblique[pid].append((x,y))
    flight_slopes={}
    for pid,(name,_,_) in parts.items():
        if name.endswith('.rebar.stair_longitudinal'):
            slopes=[(b[2]-a[2])/(b[1]-a[1]) for a,b in oblique[pid] if abs(b[1]-a[1])>1e-7]
            if slopes:flight_slopes[name.rsplit('.rebar.',1)[0]]=median(slopes)
    bycomponent=defaultdict(dict)
    components=metadata['components']
    for pid,(name,sid,mid) in parts.items():
        if '.rebar.' not in name:continue
        cid,role=name.rsplit('.rebar.',1)
        if cid in components:host=components[cid];bounds=host['native_bounds_m'];kind=host['role'];floor=host['level']
        else:
            hosts=[c for k,c in components.items() if k.startswith(cid+'.') and c['role'] in ('stair','landing')]
            if not hosts:raise ValueError('Unknown reinforcement host '+cid)
            bounds=[min(c['native_bounds_m'][k] for c in hosts) for k in range(3)]+[max(c['native_bounds_m'][k+3] for c in hosts) for k in range(3)];kind='stairs';floor=hosts[0]['level']
        group=dict(part=pid,section=sid,material=mid,diameter=sections[sid])
        axial=[dict(axis=key[0],fixed=list(key[1:]),start=interval[0],end=interval[1]) for key,interval in lines[pid].items()]
        totals=[sum(line['end']-line['start'] for line in axial if line['axis']==k) for k in range(3)]
        if role=='column_longitudinal':
            group['positions']=[[line['fixed'][k]-(bounds[k]+bounds[k+3])/2 for k in (0,1)] for line in axial if line['axis']==2]
        elif role=='column_stirrup':
            allpts=[(key,interval) for key,interval in lines[pid].items()];zs=[key[2] for key,_ in allpts if key[0] in (0,1)]
            group['spacing']=spacing(zs);group['offsets']=[max(abs(v-(bounds[k]+bounds[k+3])/2) for key,interval in allpts for a,v in zip([j for j in range(3) if j!=key[0]],key[1:]) if a==k) for k in (0,1)]
        elif role.startswith('stair_'):
            segments=oblique[pid];slope=flight_slopes[cid];group['slope']=slope
            if role=='stair_longitudinal':
                group['positions']=sorted(set(round(p[0]-bounds[0],7) for pair in segments for p in pair));layers=defaultdict(set)
                for a,b in segments:
                    for p in (a,b):layers[round(p[2]-slope*(p[1]-bounds[1])-bounds[2],5)].add(round(p[0]-bounds[0],7))
                group['layers']=[dict(offset=intercept,positions=sorted(xs)) for intercept,xs in sorted(layers.items())]
            else:
                layers=defaultdict(list)
                for line in axial:
                    if line['axis']==0:
                        y,z=line['fixed'];layers[round(z-slope*(y-bounds[1]),5)].append((y,z))
                group['crossLayers']=[dict(spacing=spacing([p[0] for p in points]),offset=intercept-bounds[2],count=len(points)) for intercept,points in sorted(layers.items())]
            group['cover']=max(.01,min(sections[sid]*3,.05))
        else:
            thin=min(range(3),key=lambda k:totals[k]);group['normalAxis']=thin;layers=defaultdict(list)
            for line in axial:
                axis=line['axis']
                if axis==thin:continue
                other=[j for j in range(3) if j!=axis];fixed=dict(zip(other,line['fixed']));depth=round(fixed[thin]-bounds[thin],7);transverse=next(j for j in range(3) if j not in (axis,thin));layers[(axis,depth)].append((fixed[transverse],line))
            group['layers']=[]
            for (axis,depth),rows in sorted(layers.items()):
                transverse=next(j for j in range(3) if j not in (axis,thin));coords=sorted(set(round(x,7) for x,_ in rows));pitch=spacing(coords)
                group['layers'].append(dict(axis=axis,depth=depth,spacing=pitch,positions=len(coords),margin=min(coords)-bounds[transverse],endMargin=bounds[transverse+3]-max(coords),startCover=min(r['start'] for _,r in rows)-bounds[axis],endCover=bounds[axis+3]-max(r['end'] for _,r in rows)))
        bycomponent[cid].update(id=cid,kind=kind,floor=floor,bounds=bounds)
        bycomponent[cid].setdefault('groups',{})[role]=group
    result=dict(schema='retained-k-rebar-rules@1',source=dict(archiveSha256=sha(Path(archive).read_bytes()),reinforcementSha256=sha(raw),materialsSha256=sha(materials),templateFingerprint=sealed['template_fingerprint'],nodes=len(nodes),elements=len(elements)),steel=steel,buildingBounds=metadata['geometry_metadata']['building_bounds_m'],components=sorted(bycomponent.values(),key=lambda c:c['id']))
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,default=ROOT/'resources/fixed_building_pressure/three-storey-structural.zip');p.add_argument('--output',type=Path,default=ROOT/'lsprepost_mcp/web/static/blast_rebar_catalog.js');a=p.parse_args()
    result=extract(a.archive);payload=json.dumps(result,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    a.output.write_text('// Extracted from verified retained K files; generated by scripts/build_demo_rebar_catalog.py.\nexport const K_REBAR_CATALOG='+payload+';\n',encoding='utf-8')
    print(json.dumps(dict(status='extracted',components=len(result['components']),source=result['source'],bytes=a.output.stat().st_size)))

if __name__=='__main__':main()
