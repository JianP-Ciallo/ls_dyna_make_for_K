"""Independent fixed-building workspace; no mesh generation or blast actions."""
import importlib
import json
import zipfile
import pytest
from test_architecture_pressure import make_template


def workspace_class():
    name='lsprepost_mcp.web.fixed_building_workspace'
    assert importlib.util.find_spec(name),'independent fixed-building workspace is missing'
    return importlib.import_module(name).FixedBuildingWorkspace


def test_readonly_preview_uses_same_template_without_loading_fe_geometry(tmp_path,monkeypatch):
    workspace=workspace_class()(tmp_path/'data',template_dir=make_template(tmp_path/'template'))
    try:
        service=workspace.service()
        monkeypatch.setattr(service.template,'geometry',lambda:pytest.fail('display metadata must not load FE geometry'))
        status,headers,body=workspace.request('GET','/api/architecture/pressure/preview-scene')
        scene=json.loads(body)
        assert status==200 and scene['components'][0]['id']=='wall'
        assert workspace.request('HEAD','/api/architecture/pressure/preview-scene')[0]==200
        assert scene['components'][0]['vertices_m'][6]==[1,1,1]
        assert scene['ground']['bounds_m']==[0,0,-1,1,1,0]
        assert scene['mesh_generated'] is False
        assert workspace.request('POST','/api/architecture/pressure/preview-scene',{})[0]==404
        schema=json.loads(workspace.request('GET','/api/architecture/pressure/schema')[2])
        assert scene['template_fingerprint']==schema['template_fingerprint']
    finally:workspace.close()


def test_packaged_structure_is_checked_and_cached_without_scenario_files(tmp_path):
    from test_architecture_pressure import digest
    template=make_template(tmp_path/'template')
    sealed=json.loads((template/'blast-template.json').read_text(encoding='utf8'))
    sealed['payload']['schema_version']='architecture.structural-template@1'
    sealed['template_fingerprint']=digest(sealed['payload'])
    archive=tmp_path/'structure.zip'
    with zipfile.ZipFile(archive,'w') as z:
        for name in sealed['payload']['files']:z.write(template/name,name)
        z.writestr('structural-template.json',json.dumps(sealed))
    cls=workspace_class();workspace=cls(tmp_path/'data',resource_archive=archive)
    try:
        assert workspace.request('GET','/api/architecture/pressure/schema')[0]==200
        assert workspace.service().template.root!=template
        assert {p.name for p in workspace.service().template.root.iterdir()}==set(sealed['payload']['files'])|{'structural-template.json'}
    finally:workspace.close()


def test_resource_archive_rejects_extra_entries_and_paths(tmp_path):
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('../escape','bad')
    workspace=workspace_class()(tmp_path/'data',resource_archive=archive)
    try:
        code,headers,body=workspace.request('GET','/api/architecture/pressure/schema')
        assert code==503 and not (tmp_path/'escape').exists()
    finally:workspace.close()


def test_closed_static_routes_do_not_expose_arbitrary_files(tmp_path):
    workspace=workspace_class()(tmp_path/'data',template_dir=make_template(tmp_path/'template'))
    try:
        assert workspace.static_response('/fixed-building-pressure')[0]==200
        assert workspace.static_response('/structural-pressure')[0]==200
        assert workspace.static_response('/static/pressure_model.py') is None
        assert workspace.static_response('/static/vendor/../structural_pressure.js') is None
    finally:workspace.close()


def test_invalid_resource_retries_do_not_accumulate_staging_directories(tmp_path):
    template=make_template(tmp_path/'template')
    sealed=json.loads((template/'blast-template.json').read_text(encoding='utf8'))
    archive=tmp_path/'bad-checksum.zip'
    with zipfile.ZipFile(archive,'w') as z:
        for name in sealed['payload']['files']:
            z.writestr(name,b'changed' if name=='materials-solver.k' else (template/name).read_bytes())
        z.writestr('structural-template.json',json.dumps(sealed))
    workspace=workspace_class()(tmp_path/'data',resource_archive=archive)
    try:
        for _ in range(2):assert workspace.request('GET','/api/architecture/pressure/schema')[0]==503
        assert list((tmp_path/'data'/'templates').glob('.stage-*'))==[]
    finally:workspace.close()
