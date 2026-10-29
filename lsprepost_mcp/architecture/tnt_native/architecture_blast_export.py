"""Fixed-template scenario preparation, portable export and semantic readback."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import numpy as np

from ...ale import render_control_ale
from .architecture_blast_contracts import normalize_blast_config,fingerprint
from .architecture_blast_template import verify_blast_template,load_blast_template,MASTER,INDEX
from .architecture_blast_openings import derive_blast_openings
from .architecture_blast_placement import resolve_blast_placement,plan_blast_grid
from .architecture_blast_monitors import resolve_blast_monitors
from .support import render_mm_grid
from .architecture_scene_surfaces import exterior_faces,convex_occupied_pieces,coincident_contact,outer_fluid_faces
from .support import render_scene,allocate_ids
from .architecture_volume_fractions import scene_fractions
from .support import file_sha256

WRITER_VERSION='architecture.fixed-blast-writer@1'
COUPLING_NQUAD=2
MANIFEST='blast-scene-manifest.json'
FIXED_FILES=('materials-solver.k','reinforcement.k','ground-solver.k','air-tnt-mm.k')


def _prepare(template,config,nquad,version):
    verify_blast_template(template)
    config=normalize_blast_config(config,template['metadata'])
    derived=derive_blast_openings(template,config['opening_states'])
    placement=resolve_blast_placement(template,derived,config)
    plan=plan_blast_grid(template,derived,config,placement)
    identity=dict(config=config,template_fingerprint=template['template_fingerprint'],plan=plan,
                  change_set=derived['change_set'],coupling_nquad=nquad,writer_version=version)
    return dict(identity,derived=derived,placement=placement,scene_fingerprint=fingerprint(identity))


def prepare_blast_scene(template:dict,config:dict)->dict:
    return _prepare(template,config,COUPLING_NQUAD,WRITER_VERSION)


def quantize_fractions(fractions,volumes):
    vf=np.asarray(fractions,float);volumes=np.asarray(volumes,float)
    if vf.shape!=(len(volumes),3) or not np.all(np.isfinite(vf)) or np.any(vf<0) or np.any(vf>1) or not np.allclose(vf.sum(1),1,rtol=0,atol=1e-12):
        raise ValueError('invalid phase fractions')
    if not np.all(np.isfinite(volumes)) or np.any(volumes<=0):raise ValueError('invalid cell volumes')
    raw=np.rint(vf*100000000).astype(np.int64);written=raw.copy()
    written[:,2]=np.minimum(100000000-written[:,1],written[:,2]);written[:,0]=100000000-written[:,1]-written[:,2]
    total=float(volumes.sum());error=(written/1e8-vf).T@volumes
    rounding=np.finfo(float).eps*max(total,1)*32
    bounds=np.array([2e-8,.5e-8,1.5e-8])*total+rounding
    if np.any(np.abs(error)>bounds):raise ValueError('quantized phase volume exceeds its rounding bound')
    return written,dict(phase_volume_error_m3=dict(zip(('air','tnt','vacuum'),map(float,error))),
        phase_volume_error_bound_m3=dict(zip(('air','tnt','vacuum'),map(float,bounds))),
        closure_corrected_cells=int(np.count_nonzero(np.any(raw!=written,axis=1))),
        written_phase_volumes_m3=dict(zip(('air','tnt','vacuum'),map(float,(written/1e8).T@volumes))))


def render_blast_scene(template,prepared):
    """Production writer shared with small fixtures; never invokes a solver."""
    d=prepared['derived'];g=d['geometry'];plan=prepared['plan'];c=prepared['config']
    elements=g['building_elements'];xyz=g['building_nodes'];ground=g['ground_elements'];gxyz=g['ground_nodes']
    pieces=convex_occupied_pieces(xyz,elements,grade=plan['grade_m'])
    vf,vol_summary=scene_fractions(plan,xyz,pieces)
    sizes=[np.diff(a) for a in plan['axes']];volumes=(sizes[2][:,None,None]*sizes[1][None,:,None]*sizes[0][None,None,:]).ravel()
    written,quantization=quantize_fractions(vf,volumes)
    monitors=resolve_blast_monitors(template,d,plan,written/1e8,c['monitors'])
    foundations={r['part_id'] for r in d['components'].values() if r['role']=='foundation'}
    fe=elements[np.isin(elements[:,1],list(foundations))];fn=set(map(int,fe[:,2:].ravel()))
    contact_nodes,contact_faces=coincident_contact({n:xyz[n] for n in fn},exterior_faces(fe),gxyz,exterior_faces(ground))
    bounds=g['ground_bounds_m'];bottom=sorted(n for n,p in gxyz.items() if abs(p[2]-bounds[2])<1e-9)
    bx=sorted(n for n,p in gxyz.items() if n not in bottom and min(abs(p[0]-bounds[0]),abs(p[0]-bounds[3]))<1e-9)
    by=sorted(n for n,p in gxyz.items() if n not in bottom and min(abs(p[1]-bounds[1]),abs(p[1]-bounds[4]))<1e-9)
    ids=allocate_ids([template['root']/name for name in template['files'] if name!=MASTER])
    sides,top,base=outer_fluid_faces(plan);parts=sorted(map(int,np.unique(elements[:,1])))
    hnodes=sorted({r['node_id'] for r in monitors if 'node_id' in r});hels=sorted({r['element_id'] for r in monitors if 'element_id' in r})
    # Empty output sets are invalid native references. Keep one real reference node/solid
    # when no user history request of that type exists, and identify these separately.
    if not hnodes:hnodes=[min(xyz)]
    if not hels:hels=[int(elements[0,0])]
    options=dict(c['controls'],timestep_scale=.67)
    files=render_scene(plan,ids,options,parts,exterior_faces(elements),sides,top,base,bottom,bx,by,
                       contact_nodes,contact_faces,hnodes,hels,initial_fractions=vf,
                       detonation_time_s=c['detonation_time_s'],coupling_nquad=prepared['coupling_nquad'])
    # MM gas properties are fixed template bytes. Only ALE controls/coupling are rebuilt.
    nquad=prepared['coupling_nquad']
    fsi=['*SET_PART_LIST_TITLE','ground_fsi_mm_air_tnt_vacuum_mesh',str(plan['master_part_set_id']),
         f"{plan['air_part_id']},{plan['tnt_part_id']},{plan['void_part_id']}",
         '*SET_MULTI-MATERIAL_GROUP_LIST_TITLE','ground_fsi_real_fluids_excluding_vacuum',str(plan['coupled_mmg_set_id']),'1,2',
         *render_control_ale(),'*CONSTRAINED_LAGRANGE_IN_SOLID',
         f"{plan['ground_part_id']},{plan['master_part_set_id']},1,0,{nquad},5,2,{-plan['coupled_mmg_set_id']}",
         '0,1e20,0.1,0,0.5,0,0,0','0,0,0,0,0,0,0,0']
    files.update(d['native_replacements']);files['ground-fsi-mm.k']='\n'.join(fsi)+'\n';files['air-tnt-grid.k']=render_mm_grid(plan)
    # Keep the reference include graph: replacements use the same portable names.
    summary=dict(coupled_building_part_ids=parts,coupling_nquad=nquad,monitor_bindings=monitors,
                 history_node_ids=hnodes,history_solid_ids=hels,volume_initialization=vol_summary,quantization=quantization,
                 foundation_tied_node_count=len(contact_nodes),ground_contact_face_count=len(contact_faces),
                 air_element_count=plan['element_count'],air_node_count=plan['node_count'])
    return files,summary


def _json(path,value):path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False),encoding='utf8')


def export_blast_scene(destination:Path,template:dict,prepared:dict)->dict:
    destination=Path(destination)
    if destination.exists():raise FileExistsError('preserve previous scenario output')
    expected=prepare_blast_scene(template,prepared['config'])
    if expected['scene_fingerprint']!=prepared['scene_fingerprint']:raise ValueError('stale prepared scene')
    destination.mkdir(parents=True,exist_ok=False)
    (destination/'stage.log').write_text('rendering scenario\n',encoding='utf8')
    try:
        files,summary=render_blast_scene(template,expected)
        for name in template['files']:shutil.copyfile(template['root']/name,destination/name)
        for name,text in files.items():(destination/name).write_text(text,encoding='utf8')
        shutil.copytree(template['root'],destination/'template',ignore=shutil.ignore_patterns('*.tmp'))
        _json(destination/'scene-config.json',expected['config']);_json(destination/'change-map.json',expected['change_set'])
        result=dict(schema_version='architecture.blast-scene@1',status='exported',main_k=MASTER,
                    template_fingerprint=template['template_fingerprint'],scene_fingerprint=expected['scene_fingerprint'],
                    writer_version=expected['writer_version'],coupling_nquad=expected['coupling_nquad'],
                    full_duration_verified=False,engineering_validated=False,whole_building_solved=False,summary=summary,
                    k_sha256={name:file_sha256(destination/name) for name in template['files']})
        _json(destination/'pending-manifest.json',result)
        _audit_blast_scene(destination,result)
        verify_blast_template(template)
        (destination/'pending-manifest.json').replace(destination/MANIFEST)
        (destination/'stage.log').write_text('semantic audit passed; exported; no solver started\n',encoding='utf8')
        return result
    except Exception as exc:
        (destination/'stage.log').write_text('failed: '+repr(exc)+'\n',encoding='utf8')
        # A manifest only publishes a bundle after every semantic check passes.
        for name in ('pending-manifest.json',MANIFEST):
            if (destination/name).exists():(destination/name).replace(destination/'failed-manifest.json')
        raise


def audit_blast_scene(directory:Path)->dict:
    root=Path(directory);r=json.loads((root/MANIFEST).read_text(encoding='utf8'))
    return _audit_blast_scene(root,r)


def _audit_blast_scene(root,r):
    if r.get('schema_version')!='architecture.blast-scene@1' or r.get('status')!='exported':raise ValueError('invalid scene manifest')
    if any(r.get(k) is not False for k in ('full_duration_verified','engineering_validated','whole_building_solved')):
        raise ValueError('unverified numerical claim')
    if r.get('writer_version')!='architecture.fixed-blast-writer@1' or r.get('coupling_nquad') not in (2,8):raise ValueError('unknown writer or quadrature')
    t=load_blast_template(root/'template');c=json.loads((root/'scene-config.json').read_text(encoding='utf8'))
    p=_prepare(t,c,r['coupling_nquad'],r['writer_version'])
    if p['scene_fingerprint']!=r['scene_fingerprint'] or t['template_fingerprint']!=r['template_fingerprint']:
        raise ValueError('scene semantic fingerprint mismatch')
    if json.loads((root/'change-map.json').read_text(encoding='utf8'))!=p['change_set']:raise ValueError('change map mismatch')
    files,summary=render_blast_scene(t,p)
    if summary!=r['summary'] or set(r['k_sha256'])!=set(t['files']):raise ValueError('scene semantic summary mismatch')
    for name in t['files']:
        if name in files:
            if (root/name).read_text(encoding='utf8')!=files[name]:raise ValueError('native semantic content mismatch: '+name)
        elif (root/name).read_bytes()!=(t['root']/name).read_bytes():raise ValueError('retained template bytes changed: '+name)
        if file_sha256(root/name)!=r['k_sha256'][name]:raise ValueError('native checksum mismatch: '+name)
    return dict(status='passed',scene_fingerprint=p['scene_fingerprint'],summary=summary)
