"""TNT UI service checks: metadata-only operations and immutable scene identity."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import zipfile
import time
import threading

import pytest


def service(tmp_path):
    module = importlib.import_module('lsprepost_mcp.architecture.tnt_service')
    return module.TntService(tmp_path / 'tnt')


def test_schema_save_and_preview_do_not_unpack_or_build_mesh(tmp_path):
    s = service(tmp_path)
    try:
        schema = s.schema()
        assert schema['analysis_type'] == 'tnt_air_fsi'
        assert len(schema['geometry']['components']) == 831
        c = deepcopy(schema['defaults'])
        saved = s.save(c)
        preview = s.preview(saved['scene_id'], saved['revision'])
        assert preview['mesh_generated'] is False
        assert preview['solver_started'] is False
        assert preview['exact_geometry_verified'] is False
        assert preview['placement']['mass_kg'] > 0
        assert preview['grid']['element_count'] > 0
        assert not list((tmp_path / 'tnt').rglob('*.k'))
        assert s.list_scenes()[0]['scene_id'] == saved['scene_id']
        assert s.load(saved['scene_id'])['config'] == c
    finally:
        s.close()


def test_revision_conflict_and_export_requires_explicit_scope_acceptance(tmp_path):
    s = service(tmp_path)
    try:
        r = s.save(s.schema()['defaults'])
        p = s.preview(r['scene_id'], 1)
        with pytest.raises(ValueError, match='确认|scope'):
            s.start_export(r['scene_id'], 1, p['scene_fingerprint'], scope_accepted=False)
        s.save(r['config'], scene_id=r['scene_id'], revision=1)
        with pytest.raises(ValueError, match='版本|revision'):
            s.preview(r['scene_id'], True)
        with pytest.raises(ValueError, match='版本|revision'):
            s.start_export(r['scene_id'], 1, p['scene_fingerprint'], scope_accepted=True)
        assert not list((tmp_path / 'tnt' / 'exports').iterdir())
    finally:
        s.close()


def test_outdoor_height_uses_grade_and_position_outside_air_is_rejected(tmp_path):
    s = service(tmp_path)
    try:
        schema = s.schema()
        c = deepcopy(schema['defaults'])
        r = s.save(c); p = s.preview(r['scene_id'], 1)
        assert p['placement']['bottom_elevation_m'] == pytest.approx(schema['geometry']['grade_m'] + .5)
        c['location']['xy_m'] = [10000., 10000.]
        r = s.save(c)
        with pytest.raises(ValueError, match='空气域'):
            s.preview(r['scene_id'], 1)
    finally:
        s.close()


def test_air_grid_budget_rejected_without_allocating_mesh(tmp_path):
    s = service(tmp_path)
    try:
        c = s.schema()['defaults']; c['mesh']['background_cell_m'] = 1e-10
        r = s.save(c)
        with pytest.raises(ValueError, match='预算|budget|grid'):
            s.preview(r['scene_id'], 1)
    finally:
        s.close()


def test_api_result_paths_cannot_escape_and_no_solve_route(tmp_path):
    from lsprepost_mcp.architecture.tnt_api import handle_tnt_request, PREFIX
    s = service(tmp_path)
    try:
        assert handle_tnt_request(s, 'GET', PREFIX+'schema')[0] == 200
        assert handle_tnt_request(s, 'POST', PREFIX+'solve', {})[0] == 404
        assert handle_tnt_request(s, 'GET', PREFIX+'exports/../../secret/download')[0] == 404
        assert handle_tnt_request(s, 'POST', PREFIX+'scenes/save', {'config':s.schema()['defaults'], 'path':'C:/secret'})[0] == 400
    finally:
        s.close()


def test_small_retained_template_exports_fsi_and_download_checks_hashes(tmp_path,monkeypatch):
    from lsprepost_mcp.architecture.tnt_service import TntService
    s = TntService(tmp_path/'tnt', archive=Path(__file__).parent/'fixtures/fixed_building_tnt/template.zip')
    try:
        c = s.schema()['defaults']
        c['location'].update(xy_m=[32.5,1.])
        c['mesh'].update(background_cell_m=32., charge_cell_m=.25, room_cell_m=32., opening_cell_m=32.)
        c['mesh']['margins_m']={k:1. for k in c['mesh']['margins_m']}
        c['monitors']=[dict(id='p1',kind='air_pressure',position_m=[32.5,1.,1.5])]
        r=s.save(c); p=s.preview(r['scene_id'],1)
        assert p['grid']['element_count']<5000
        job=s.start_export(r['scene_id'],1,p['scene_fingerprint'],scope_accepted=True)
        deadline=time.monotonic()+30
        while job['status'] in ('queued','running') and time.monotonic()<deadline:
            time.sleep(.02); job=s.export_status(job['job_id'])
        assert job['status']=='exported', job.get('error',job)
        from lsprepost_mcp.architecture.tnt_native import architecture_blast_export
        def no_rebuild(*args):pytest.fail('download must not repeat FE geometry or volume-fraction generation')
        monkeypatch.setattr(architecture_blast_export,'audit_blast_scene',no_rebuild)
        directory,_=s.export_directory(job['job_id'])
        (directory/'unrelated-secret.txt').write_text('not part of K package')
        raw=s.download(job['job_id'])
        import io
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            assert 'unrelated-secret.txt' not in z.namelist()
            assert '*CONSTRAINED_LAGRANGE_IN_SOLID' in z.read('scene-interfaces.k').decode()
            assert '*INITIAL_DETONATION' in z.read('scene-initial.k').decode()
            assert '*LOAD_SEGMENT_SET' not in z.read('scene-interfaces.k').decode()
        (directory/'scene-controls.k').write_text('$ changed')
        with pytest.raises(ValueError):s.download(job['job_id'])
    finally:s.close()


def test_active_export_cannot_be_reused_for_another_scene_or_revision(tmp_path,monkeypatch):
    s=service(tmp_path);entered=threading.Event();release=threading.Event()
    def held_export(*args):entered.set();assert release.wait(10)
    monkeypatch.setattr(s,'_export',held_export)
    try:
        first=s.save(s.schema()['defaults']);p=s.preview(first['scene_id'],1)
        j=s.start_export(first['scene_id'],1,p['scene_fingerprint'],scope_accepted=True);assert entered.wait(2)
        assert s.start_export(first['scene_id'],1,p['scene_fingerprint'],scope_accepted=True)['job_id']==j['job_id']
        second=s.save(first['config']);p2=s.preview(second['scene_id'],1)
        with pytest.raises(ValueError,match='正在执行'):
            s.start_export(second['scene_id'],1,p2['scene_fingerprint'],scope_accepted=True)
        r=s.save(first['config'],scene_id=first['scene_id'],revision=1);p3=s.preview(r['scene_id'],2)
        with pytest.raises(ValueError,match='正在执行'):
            s.start_export(r['scene_id'],2,p3['scene_fingerprint'],scope_accepted=True)
    finally:release.set();s.close()


def test_workspace_tnt_route_is_lazy_and_existing_pressure_service_stays_separate(tmp_path):
    from lsprepost_mcp.web.fixed_building_workspace import FixedBuildingWorkspace
    from test_architecture_pressure import make_template
    w=FixedBuildingWorkspace(tmp_path/'workspace',template_dir=make_template(tmp_path/'structure'))
    try:
        code,headers,body=w.request('GET','/api/architecture/tnt/schema')
        assert code==200 and json.loads(body)['analysis_type']=='tnt_air_fsi'
        assert w.request('GET','/api/architecture/pressure/schema')[0]==200
        assert b'tntEditor' in w.static_response('/structural-pressure')[2]
        assert b'curveFile' in w.static_response('/structural-pressure',legacy=True)[2]
        assert not list((tmp_path/'workspace'/'tnt').rglob('*.k'))
    finally:w.close()
