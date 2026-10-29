"""Tiny retained-mesh tests; no mesh generator or native solver."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import time
import zipfile

import numpy as np
import pytest


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def make_template(root):
    root.mkdir()
    points = [(0,0,0),(1,0,0),(1,1,0),(0,1,0),(0,0,1),(1,0,1),(1,1,1),(0,1,1)]
    def cube(start, pid, dz):
        return '*NODE\n'+''.join(f'{start+i},{x},{y},{z+dz}\n' for i,(x,y,z) in enumerate(points))+'*ELEMENT_SOLID\n'+f'{pid},{pid},'+','.join(str(start+i) for i in range(8))+'\n'
    files = {
        'solids-solver.k': cube(1, 1, 0),
        'ground-solver.k': '*PART\nground\n11,1,1,0\n'+cube(101, 11, -1),
        'materials-solver.k': '*MAT_ELASTIC\n1,2400,30000000000,0.2\n',
        'solid-properties.k': '*SECTION_SOLID\n1,2\n*PART\nwall\n1,1,1,0\n',
        'reinforcement.k': '$ no reinforcement in fixture\n',
        'installation.k': '$ no installed fixture components\n',
    }
    for name,text in files.items(): (root/name).write_bytes(text.encode('utf8'))
    payload = dict(schema_version='architecture.blast-template@1',
        files={k: hashlib.sha256(v.encode()).hexdigest() for k,v in files.items()},
        components={'wall': dict(part_id=1,role='wall',level=0,native_bounds_m=[0,0,0,1,1,1])},
        geometry_metadata=dict(building_bounds_m=[0,0,0,1,1,1],ground_bounds_m=[0,0,-1,1,1,0],air_bounds_m=[-1,-1,0,2,2,2],grade_m=0))
    (root/'blast-template.json').write_text(json.dumps(dict(template_id='fixture',template_fingerprint=digest(payload),payload=payload)), encoding='utf8')
    return root


def service_class():
    name = 'lsprepost_mcp.architecture.pressure_service'
    assert importlib.util.find_spec(name), 'structural pressure service is missing'
    return importlib.import_module(name).PressureService


@pytest.fixture
def service(tmp_path):
    svc = service_class()(make_template(tmp_path/'template'),tmp_path/'data')
    yield svc
    svc.close()


def reviewed_config(service):
    c = copy.deepcopy(service.schema()['default_config'])
    c.update(name='Fixture pressure',target=dict(component_id='wall',face='west'),
        curve_ms_kpa=[[0,0],[10,2],[20,0]],
        source=dict(reference='Synthetic test fixture, not an engineering load',reviewer='Test only',reviewed=True),
        monitors=[dict(id='m1',kind='structure_node',position_m=[0,0,0])])
    return c


def await_export(service, job):
    for _ in range(100):
        result=service.export_status(job['job_id'])
        if result['status'] in ('exported','failed','interrupted'): return result
        time.sleep(.02)
    pytest.fail('small export did not finish')


def test_reviewed_curve_exports_real_portable_structural_package(service):
    record=service.save(reviewed_config(service))
    preview=service.preview(record['scene_id'],1)
    assert preview['segment_count']==1 and preview['area_m2']==1
    assert preview['curve_si']==[[0,0],[.01,2000],[.02,0]]
    assert preview['monitors'][0]['node_id']==1
    job=await_export(service,service.start_export(record['scene_id'],1,preview['scene_fingerprint']))
    assert job['status']=='exported',job
    data=service.download(job['job_id'])
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert 'structural-pressure.k' in z.namelist()
        entry=z.read('structural-pressure.k').decode()
        for included in ('materials-solver.k','solids-solver.k','ground-solver.k','pressure-load.k','supports.k','controls.k'):
            assert included in entry and included in z.namelist()
        loads=z.read('pressure-load.k').decode()
        assert '*LOAD_SEGMENT_SET' in loads and '0.01,2000' in loads
        supports=z.read('supports.k').decode().replace('\r','')
        assert '*BOUNDARY_SPC_SET' in supports
        assert '9899003\n1,2,3,4\n' in supports
        assert '9899004\n101,102,103,104\n' in supports
        assert '*DATABASE_HISTORY_NODE' in z.read('controls.k').decode()
        assert not any(b'*INITIAL_DETONATION' in z.read(n) or b'*ALE_' in z.read(n) for n in z.namelist())
        manifest=json.loads(z.read('manifest.json'))
        assert manifest['solver_started'] is False and manifest['engineering_validated'] is False
        for name,sha in manifest['files'].items(): assert hashlib.sha256(z.read(name)).hexdigest()==sha
    # Outward west normal gives inward compressive loading.
    segments=preview['segments'];p=np.asarray(preview['segment_points_m'][0])
    assert len(segments)==1 and np.cross(p[1]-p[0],p[2]-p[0])[0]<0


@pytest.mark.parametrize('field,value',[
    ('curve_ms_kpa',[[0,0],[0,2],[20,0]]),
    ('curve_ms_kpa',[[0,0],[10,float('nan')],[20,0]]),
    ('curve_ms_kpa',[[0,0],[10,2],[20,2]]),
    ('target',dict(component_id='missing',face='west')),
    ('controls',dict(termination_ms=10,plot_ms=1,history_ms=.1)),
])
def test_invalid_inputs_cannot_preview(service,field,value):
    c=reviewed_config(service);c[field]=value
    with pytest.raises(ValueError):
        r=service.save(c);service.preview(r['scene_id'],1)


def test_unreviewed_draft_can_save_but_not_export(service):
    c=reviewed_config(service);c['source']['reviewed']=False
    r=service.save(c);p=service.preview(r['scene_id'],1)
    assert p['exportable'] is False
    with pytest.raises(ValueError,match='review'):service.start_export(r['scene_id'],1,p['scene_fingerprint'])


def test_revision_conflict_and_stale_preview(service):
    c=reviewed_config(service);r=service.save(c);p=service.preview(r['scene_id'],1)
    service.save(c,scene_id=r['scene_id'],revision=1)
    with pytest.raises(ValueError):service.save(c,scene_id=r['scene_id'],revision=1)
    with pytest.raises(ValueError):service.start_export(r['scene_id'],1,p['scene_fingerprint'])
    assert service.list_scenes()[0]['revision']==2
    assert service.load(r['scene_id'])['config']==c


def test_changed_structure_and_injected_keywords_are_rejected(service):
    (service.template.root/'materials-solver.k').write_text('*INITIAL_DETONATION\n',encoding='utf8')
    with pytest.raises(ValueError,match='checksum'):service.preview(service.save(reviewed_config(service))['scene_id'],1)


def test_no_unknown_fields_or_client_paths(service):
    c=reviewed_config(service);c['output_path']='../../escape'
    with pytest.raises(ValueError):service.save(c)
    with pytest.raises(ValueError):service.load('../template')


def test_actual_ground_and_stress_sampling_excludes_auxiliary_nodes(service):
    c=reviewed_config(service)
    c['monitors']=[dict(id='ground',kind='ground_node',position_m=[0,0,-1]),
                   dict(id='stress',kind='solid_stress',position_m=[.5,.5,.5])]
    r=service.save(c);p=service.preview(r['scene_id'],1)
    assert p['monitors'][0]['node_id']==101
    assert p['monitors'][1]['element_id']==1 and p['monitors'][1]['distance_m']==0


@pytest.mark.parametrize('monitors',[
    [dict(id='far',kind='structure_node',position_m=[99,99,99])],
    [dict(id='dup',kind='structure_node',position_m=[0,0,0])]*2,
])
def test_invalid_monitor_requests_rejected(service,monitors):
    c=reviewed_config(service);c['monitors']=monitors
    with pytest.raises(ValueError):r=service.save(c);service.preview(r['scene_id'],1)


def test_export_requires_preview_and_download_checks_integrity(service):
    r=service.save(reviewed_config(service))
    with pytest.raises(ValueError):service.start_export(r['scene_id'],1,'0'*64)
    p=service.preview(r['scene_id'],1)
    j=await_export(service,service.start_export(r['scene_id'],1,p['scene_fingerprint']))
    (service.outputs/j['job_id']/'structural-pressure.zip').write_bytes(b'changed')
    with pytest.raises(ValueError,match='checksum'):service.download(j['job_id'])


def test_nested_include_with_matching_checksum_cannot_export(service):
    path=service.template.root/'installation.k';path.write_bytes(b'*INCLUDE\n../../outside.k\n')
    sealed=json.loads((service.template.root/'blast-template.json').read_text(encoding='utf8'))
    sealed['payload']['files']['installation.k']=hashlib.sha256(path.read_bytes()).hexdigest()
    sealed['template_fingerprint']=digest(sealed['payload'])
    (service.template.root/'blast-template.json').write_text(json.dumps(sealed),encoding='utf8')
    replacement=service_class()(service.template.root,service.root/'replacement')
    try:
        r=replacement.save(reviewed_config(replacement));p=replacement.preview(r['scene_id'],1)
        j=await_export(replacement,replacement.start_export(r['scene_id'],1,p['scene_fingerprint']))
        assert j['status']=='failed' and 'unsupported card' in j['error']
        with pytest.raises(ValueError):replacement.download(j['job_id'])
    finally:replacement.close()


def test_shared_node_union_does_not_load_another_parts_roof(tmp_path):
    root=make_template(tmp_path/'template')
    nid=lambda x,y,z:1+x+4*y+12*z
    rows=['*NODE']+[f'{nid(x,y,z)},{x},{y},{z}' for z in range(2) for y in range(3) for x in range(4)]
    rows.append('*ELEMENT_SOLID')
    eid=0
    for y in range(2):
        for x in range(3):
            eid+=1;pid=2 if (x,y)==(1,1) else 1
            corners=[nid(x,y,0),nid(x+1,y,0),nid(x+1,y+1,0),nid(x,y+1,0),
                     nid(x,y,1),nid(x+1,y,1),nid(x+1,y+1,1),nid(x,y+1,1)]
            rows.append(','.join(map(str,[eid,pid,*corners])))
    (root/'solids-solver.k').write_bytes(('\n'.join(rows)+'\n').encode())
    sealed=json.loads((root/'blast-template.json').read_text(encoding='utf8'))
    payload=sealed['payload']
    payload['components']['wall']['native_bounds_m']=[0,0,0,3,2,1]
    payload['components']['other']=dict(part_id=2,role='wall',level=0,native_bounds_m=[1,1,0,2,2,1])
    payload['geometry_metadata']['building_bounds_m']=[0,0,0,3,2,1]
    payload['files']['solids-solver.k']=hashlib.sha256((root/'solids-solver.k').read_bytes()).hexdigest()
    sealed['template_fingerprint']=digest(payload)
    (root/'blast-template.json').write_text(json.dumps(sealed),encoding='utf8')
    service=service_class()(root,tmp_path/'data')
    try:
        c=reviewed_config(service);c['target']['face']='roof'
        r=service.save(c);p=service.preview(r['scene_id'],1)
        assert p['segment_count']==5 and p['area_m2']==5
        foreign={nid(1,1,1),nid(2,1,1),nid(2,2,1),nid(1,2,1)}
        assert all(set(face)!=foreign for face in p['segments'])
    finally:service.close()


@pytest.mark.parametrize('keyword',['*CONTROL_ALE','*CONSTRAINED_LAGRANGE_IN_SOLID','*LOAD_SEGMENT_SET','*MAT_NULL'])
def test_structural_inputs_reject_fluid_coupling_and_extra_loads(tmp_path,keyword):
    from lsprepost_mcp.architecture.pressure_model import validate_structural_file
    path=tmp_path/'injected.k';path.write_text(keyword+'\n1,1,1\n',encoding='utf8')
    with pytest.raises(ValueError,match='unsupported card'):validate_structural_file(path)


def test_structural_material_cards_allow_blank_leading_fields(tmp_path):
    from lsprepost_mcp.architecture.pressure_model import validate_structural_file
    path=tmp_path/'material.k'
    path.write_text('*MAT_CONCRETE_DAMAGE_REL3_TITLE+\nConcrete reference\n9002,2400,0.2\n,-30000000,,,,,\n,,,,,,,\n',encoding='utf8')
    validate_structural_file(path)
