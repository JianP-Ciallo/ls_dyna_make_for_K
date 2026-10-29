"""Independent CPU page/JSON entry stays available without a full FE template."""
import json
from lsprepost_mcp.web.fixed_building_workspace import FixedBuildingWorkspace


def test_cpu_page_is_separate_and_readonly_capability_does_not_unpack_building(tmp_path,monkeypatch):
    workspace=FixedBuildingWorkspace(tmp_path/'data',resource_archive=tmp_path/'missing.zip')
    def forbidden():raise AssertionError('CPU benchmark GET tried to unpack the whole building')
    monkeypatch.setattr(workspace,'service',forbidden)
    try:
        response=workspace.static_response('/fixed-building-pressure/response')
        assert response is not None and response[0]==200
        assert 'text/html' in response[1]['Content-Type']
        code,headers,raw=workspace.request('GET','/api/architecture/pressure/cpu-response/benchmarks')
        assert code==200
        assert len(json.loads(raw)['benchmarks'])==2
        assert not (tmp_path/'data'/'templates').exists()
    finally:workspace.close()


def test_cpu_assets_are_explicitly_whitelisted(tmp_path):
    workspace=FixedBuildingWorkspace(tmp_path)
    try:
        for name in ('fixed_building_response.css','fixed_building_response.js','fixed_building_response_view.js','fixed_building_response_charts.js'):
            response=workspace.static_response('/static/'+name)
            assert response is not None and response[0]==200
        assert workspace.static_response('/static/../../cpu_response/worker.py') is None
    finally:workspace.close()
