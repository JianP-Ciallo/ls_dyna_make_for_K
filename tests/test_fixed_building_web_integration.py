"""Exercise the production HTTP boundary with a two-cube structural fixture."""
import http.client
import io
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import zipfile

import pytest

from lsprepost_mcp.web.app import create_server
from lsprepost_mcp.web.fixed_building_workspace import FixedBuildingWorkspace, PREFIX
from test_architecture_pressure import make_template, reviewed_config


@pytest.fixture
def web(tmp_path):
    server = create_server('127.0.0.1', 0)
    server.fixed_building.close()
    server.fixed_building = FixedBuildingWorkspace(
        tmp_path/'data', template_dir=make_template(tmp_path/'template'))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(method, path, payload=None, headers=None):
        body = None if payload is None else json.dumps(payload).encode()
        actual_headers = {'Content-Type': 'application/json'} if body is not None else {}
        actual_headers.update(headers or {})
        conn = http.client.HTTPConnection(*server.server_address, timeout=10)
        try:
            conn.request(method, path, body=body, headers=actual_headers)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    try:
        yield server, request
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_main_http_saves_previews_exports_and_downloads_a_tiny_k_package(web):
    server, request = web
    config = reviewed_config(server.fixed_building.service())
    status, _, body = request('POST', PREFIX+'scenes/save', {'config': config})
    assert status == 200, body
    record = json.loads(body)
    scene = PREFIX+'scenes/'+record['scene_id']
    assert json.loads(request('GET', scene)[2])['revision'] == 1
    status, _, body = request('POST', scene+'/preview', {'revision': 1})
    assert status == 200, body
    preview = json.loads(body)
    status, _, body = request('POST', scene+'/exports', {
        'revision': 1, 'scene_fingerprint': preview['scene_fingerprint']})
    assert status == 202, body
    job = PREFIX+'exports/'+json.loads(body)['job_id']
    for _ in range(100):
        status, _, body = request('GET', job)
        state = json.loads(body)
        if state['status'] in {'exported', 'failed', 'interrupted'}:
            break
        time.sleep(.02)
    assert status == 200 and state['status'] == 'exported', state
    status, headers, data = request('GET', job+'/download')
    assert status == 200 and headers['Content-Type'] == 'application/zip'
    assert 'attachment;' in headers['Content-Disposition']
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert 'structural-pressure.k' in archive.namelist()
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['solver_started'] is False
        assert '*LOAD_SEGMENT_SET' in archive.read('pressure-load.k').decode()


def test_main_http_keeps_namespaces_assets_and_request_guards_separate(web, monkeypatch):
    server, request = web
    # Legacy navigation must work even when the new structural resource is absent.
    def unavailable():
        raise FileNotFoundError('unavailable fixture resource')
    monkeypatch.setattr(server.fixed_building, 'service', unavailable)
    for path in ('/', '/refined-building-blast', '/app.js'):
        assert request('GET', path)[0] == 200
    html = request('GET', '/')[2].decode()
    assert 'id="openRefinedBlastWorkbench"' in html
    assert 'id="openFixedBuildingWorkspace"' in html
    assert request('GET', '/fixed-building-pressure')[0] == 200
    assert request('GET', '/structural-pressure')[0] == 200
    assert request('GET', PREFIX+'schema')[0] == 503
    monkeypatch.undo()
    status, headers, body = request('HEAD', PREFIX+'schema')
    assert status == 200 and body == b'' and int(headers['Content-Length']) > 0
    assert request('GET', PREFIX+'schema?unexpected=1')[0] == 400
    status, _, body = request('POST', PREFIX+'scenes/save', {},
                              {'Origin': 'http://example.invalid'})
    assert status == 403 and json.loads(body)['error']['message']
    assert request('POST', PREFIX+'scenes/save', {},
                   {'Content-Type': 'text/plain'})[0] == 415
    assert request('GET', '/api/scenes')[0] == 200
    assert request('GET', '/api/architecture/blast/schema')[0] == 404


def test_original_web_app_still_starts_and_serves_pages_without_numpy():
    # A fresh interpreter is necessary: fixture tests already imported NumPy.
    script = '''
import importlib.abc
import sys
class NoNumpy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'numpy' or fullname.startswith('numpy.'):
            raise ModuleNotFoundError('numpy disabled for startup-isolation test')
sys.meta_path.insert(0, NoNumpy())
from lsprepost_mcp.web.app import create_server
import http.client
import threading
server = create_server('127.0.0.1', 0)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
def request(path):
    conn = http.client.HTTPConnection(*server.server_address, timeout=10)
    try:
        conn.request('GET', path)
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()
try:
    for path in ('/', '/refined-building-blast', '/app.js',
                 '/fixed-building-pressure', '/structural-pressure'):
        assert request(path)[0] == 200, path
    status, body = request('/api/architecture/pressure/schema')
    assert status == 503 and b'numpy disabled' in body, (status, body)
    assert request('/api/scenes')[0] == 200
    assert 'numpy' not in sys.modules
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
'''
    result = subprocess.run([sys.executable, '-B', '-c', script],
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
