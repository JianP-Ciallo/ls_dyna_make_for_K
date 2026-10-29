"""Pure helpers extracted from the retained exporter; no generation entry points."""

import io, math, re, hashlib

from pathlib import Path

import numpy as np

def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def _blocks(path):
    """Stream blocks; only the bounded environment files are parsed here."""
    key,rows=None,[]
    with path.open(encoding='utf8') as stream:
        for raw in stream:
            line=raw.strip()
            if not line or line.startswith('$'): continue
            if line.startswith('*'):
                if key: yield key,rows
                key,rows=line.upper(),[]
            elif key is None: raise ValueError('orphan environment record')
            else: rows.append(line)
    if key: yield key,rows

def _coordinate_token(token):
    if len(token) <= 20:
        return token
    value = float(token)
    if not math.isfinite(value):
        raise ValueError('nonfinite native coordinate')
    for candidate in [repr(value),*(format(value,f'.{p}g') for p in range(17,0,-1))]:
        candidate = re.sub(r'^(-?)0\.',r'\1.',candidate)
        if len(candidate) <= 20 and abs(float(candidate)-value) <= 1e-28:
            return candidate
    raise ValueError('native coordinate cannot fit long field within roundoff budget')

def _inside(point, box):
    return all(box[a] - 1e-12 < point[a] < box[a+3] + 1e-12 for a in range(3))

def _cells(axes, exclusions=()):
    xs, ys, zs = axes
    for iz in range(len(zs)-1):
        for iy in range(len(ys)-1):
            for ix in range(len(xs)-1):
                if exclusions:
                    center = ((xs[ix]+xs[ix+1])/2, (ys[iy]+ys[iy+1])/2, (zs[iz]+zs[iz+1])/2)
                    if any(_inside(center, b) for b in exclusions):
                        continue
                yield ix, iy, iz

def iter_grid(axes, exclusions=(), *, node_start=1, element_start=1):
    """Return streaming nodes and positive-orientation Hex8s; omit unused nodes."""
    nx, ny, _ = map(len, axes)
    def nid(ix, iy, iz):
        return node_start + iz*nx*ny + iy*nx + ix
    def corners(ix, iy, iz):
        return (nid(ix,iy,iz),nid(ix+1,iy,iz),nid(ix+1,iy+1,iz),nid(ix,iy+1,iz),
                nid(ix,iy,iz+1),nid(ix+1,iy,iz+1),nid(ix+1,iy+1,iz+1),nid(ix,iy+1,iz+1))
    kept = tuple(_cells(axes, exclusions)) if exclusions else None
    used = {n for cell in kept for n in corners(*cell)} if kept is not None else None
    def nodes():
        for iz, z in enumerate(axes[2]):
            for iy, y in enumerate(axes[1]):
                for ix, x in enumerate(axes[0]):
                    identifier = nid(ix,iy,iz)
                    if used is None or identifier in used:
                        yield identifier, (x,y,z)
    def elements():
        for index, cell in enumerate(kept if kept is not None else _cells(axes)):
            yield element_start + index, corners(*cell)
    return nodes(), elements()

def _core_cell(x0,x1,y0,y1,z0,z1,plan):
    x,y,_ = plan['center_m']
    radius = plan['diameter_m']/2
    distance = max(abs(x0-x),abs(x1-x))**2+max(abs(y0-y),abs(y1-y))**2
    return (distance<=radius**2+1e-14 and z0>=plan['bounds_m'][2]-1e-14
            and z1<=plan['bounds_m'][5]+1e-14)

def render_mm_grid(plan):
    stream = io.StringIO()
    stream.write('*NODE+\n')
    nodes,elements = iter_grid(plan['axes'],node_start=plan['node_start'],element_start=plan['element_start'])
    for nid,point in nodes:
        stream.write(str(nid)+','+','.join(_coordinate_token(format(v,'.17g')) for v in point)+'\n')
    stream.write('*ELEMENT_SOLID\n')
    xs,ys,zs = plan['axes']
    cells = ((x0,x1,y0,y1,z0,z1) for z0,z1 in zip(zs,zs[1:])
             for y0,y1 in zip(ys,ys[1:]) for x0,x1 in zip(xs,xs[1:]))
    for (eid,nids),cell in zip(elements,cells):
        if cell[5]<=plan['grade_m']:
            pid = plan['void_part_id']
        elif _core_cell(*cell,plan):
            pid = plan['tnt_part_id']
        else:
            pid = plan['air_part_id']
        stream.write(','.join(map(str,(eid,pid,*nids)))+'\n')
    return stream.getvalue()

SET_NAMES=('occupied','building_parts','air_sides','air_top','air_bottom',
           'ground_bottom','ground_x','ground_y','foundation_nodes','foundation_faces',
           'history_nodes','history_solids','contact')

def allocate_ids(paths):
    maximum=9600000
    for path in paths:
        for key,rows in _blocks(path):
            if not key.startswith(('*SET_','*CONTACT_')): continue
            if key.startswith('*CONTACT_') and not key.endswith('_ID'): continue
            index=int(key.endswith('_TITLE'))
            if len(rows)>index:
                token=rows[index].split(',')[0].split()[0]
                maximum=max(maximum,int(token))
    if maximum+len(SET_NAMES)>99999999: raise ValueError('scene set ID budget exceeded')
    return {name:maximum+i+1 for i,name in enumerate(SET_NAMES)}

def _set(kind,name,sid,rows):
    lines=['*SET_'+kind+'_TITLE',name,str(sid)]
    if kind=='SEGMENT':
        lines.extend(','.join(map(str,f))+',0,0,0,0' for f in rows)
    else:
        lines.extend(','.join(map(str,rows[i:i+8])) for i in range(0,len(rows),8))
    return lines

def render_scene(plan,ids,options,parts,occupied,sides,top,bottom,
                 ground_bottom,ground_x,ground_y,foundation_nodes,foundation_faces,
                 history_nodes,history_solids,*,initial_fractions,detonation_time_s=0.0,coupling_nquad=2):
    if not math.isfinite(detonation_time_s) or not 0<=detonation_time_s<options['termination_s']:
        raise ValueError('detonation time must precede termination')
    if type(coupling_nquad) is not int or coupling_nquad not in (2,8):raise ValueError('unsupported coupling quadrature')
    sets=[]
    for name,kind,rows in [('occupied','SEGMENT',occupied),('building_parts','PART_LIST',parts),
              ('air_sides','SEGMENT',sides),('air_top','SEGMENT',top),('air_bottom','SEGMENT',bottom),
              ('ground_bottom','NODE_LIST',ground_bottom),('ground_x','NODE_LIST',ground_x),
              ('ground_y','NODE_LIST',ground_y),('foundation_nodes','NODE_LIST',foundation_nodes),
              ('foundation_faces','SEGMENT',foundation_faces),('history_nodes','NODE_LIST',history_nodes),
              ('history_solids','SOLID_LIST',history_solids)]:
        sets.extend(_set(kind,name,ids[name],list(rows)))
    x,y,z=plan['center_m']
    n=lambda value:format(value,'.12g')
    fractions=np.asarray(initial_fractions)
    if (fractions.ndim!=2 or fractions.shape[1]!=3 or not np.all(np.isfinite(fractions))
        or np.any(fractions<0) or np.any(fractions>1) or not np.allclose(fractions.sum(axis=1),1,atol=1e-12)):
        raise ValueError('invalid explicit volume fractions')
    initial=['$ Explicit AIR/TNT/VAC fractions, one row per retained ALE cell.',
             '*INITIAL_VOLUME_FRACTION']
    # R12 uses 10-character VF fields. Decimal rounding also preserves the
    # three-phase sum exactly at the precision written into the native file.
    for i,row in enumerate(fractions):
        tnt_units=int(round(float(row[1])*100000000))
        void_units=min(100000000-tnt_units,int(round(float(row[2])*100000000)))
        air_units=100000000-tnt_units-void_units
        initial.append(str(plan.get('element_start',1)+i)+','+
                       ','.join(format(v/100000000,'.8f') for v in (air_units,tnt_units,void_units)))
    initial+=['*INITIAL_DETONATION',','.join(n(v) for v in (0,x,y,z,detonation_time_s))]
    boundaries=['$ Ground bottom fixed; distant side faces restrained in their normals.',
                '*BOUNDARY_SPC_SET',f"{ids['ground_bottom']},0,1,1,1,0,0,0",
                '*BOUNDARY_SPC_SET',f"{ids['ground_x']},0,1,0,0,0,0,0",
                '*BOUNDARY_SPC_SET',f"{ids['ground_y']},0,0,1,0,0,0,0",
                '*BOUNDARY_NON_REFLECTING',f"{ids['air_sides']},0,0",f"{ids['air_top']},0,0",
                '*ALE_ESSENTIAL_BOUNDARY',f"{ids['air_bottom']},2,2,0"]
    interfaces=['*CONSTRAINED_LAGRANGE_IN_SOLID',
                f"{ids['building_parts']},{plan['master_part_set_id']},0,0,{coupling_nquad},5,2,{-plan['coupled_mmg_set_id']}",
                '0,1e20,0.1,0,0.5,0,0,0','0,0,0,0,0,0,0,0',
                '$ Initially coincident foundation/ground ideal bond, penalty OFFSET, no projection.',
                '*CONTACT_TIED_NODES_TO_SURFACE_OFFSET_ID',
                f"{ids['contact']},foundation_ground_initial_bond",
                f"{ids['foundation_nodes']},{ids['foundation_faces']},4,0,0,0,0,0",
                '0,0,0,0,0,0,0,1e20','1,1,-1e-6,-1e-6,0,0,1,1']
    h=n(options['history_interval_s'])
    controls=['*CONTROL_TERMINATION',n(options['termination_s']),
              '*CONTROL_TIMESTEP',f"0,{n(options['timestep_scale'])},0,0,0,0,0,0",
              '*CONTROL_ENERGY','2,2,2,2',
              '*DATABASE_BINARY_D3PLOT',n(options['plot_interval_s']),
              '*DATABASE_GLSTAT','0.0001','*DATABASE_MATSUM','0.0001',
              '*DATABASE_NODOUT',h,'*DATABASE_ELOUT',h,'*DATABASE_RCFORC',h,'*DATABASE_SLEOUT',h,
              '*DATABASE_HISTORY_NODE_SET',str(ids['history_nodes']),
              '*DATABASE_HISTORY_SOLID_SET',str(ids['history_solids']),
              '*DATABASE_FSI',h,f"1,{plan['ground_part_id']},1",f"2,{ids['building_parts']},0"]
    return {name:'\n'.join(rows)+'\n' for name,rows in (
        ('scene-surfaces.k',sets),('scene-initial.k',initial),('scene-boundaries.k',boundaries),
        ('scene-interfaces.k',interfaces),('scene-controls.k',controls))}
