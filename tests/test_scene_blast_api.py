import json

from lsprepost_mcp.architecture.scene_blast.api import PREFIX,handle_request
from lsprepost_mcp.architecture.scene_blast.service import SceneBlastService
from lsprepost_mcp.web.fixed_building_workspace import FixedBuildingWorkspace


def test_get_routes_cannot_start_or_prepare_and_old_page_still_exists(tmp_path):
    s=SceneBlastService(tmp_path/'cpu',runner=lambda *a:(_ for _ in ()).throw(AssertionError('worker forbidden')))
    try:
        for route in ['prepare','runs/../../x','runs/'+'a'*32+'/cancel']:
            code,_,_=handle_request(s,'GET',PREFIX+route);assert code==404
        code,_,raw=handle_request(s,'GET',PREFIX+'catalog');assert code==200
        assert len(json.loads(raw)['sources'])==5 and not s.history()
    finally:s.close()
    w=FixedBuildingWorkspace(tmp_path/'workspace',resource_archive=tmp_path/'absent.zip')
    try:
        assert w.static_response('/cpu-blast')[0]==200
        assert w.static_response('/fixed-building-pressure/response')[0]==200
        assert w._scene_cpu is None  # Static navigation starts neither new worker nor model preparation.
    finally:w.close()
