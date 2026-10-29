"""Isolated browser fixture server: deletion/restoration allowed, computation forbidden."""
import argparse
import json
from pathlib import Path
import sys
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from lsprepost_mcp.web.app import WebAppServer, WebAppHandler, ApiError, json_ok
from lsprepost_mcp.web.fixed_building_workspace import FixedBuildingWorkspace
from lsprepost_mcp.architecture.cpu_response.results import json_write, write_artifacts


class Handler(WebAppHandler):
    def handle_api(self,method,path,query):
        if path=='/api/test-cpu-history' and method=='GET':return json_ok({'isolated_no_compute':True})
        if method=='POST' and not (path.endswith('/delete') or path.endswith('/restore')):
            raise ApiError(403,'fixture_forbids_computation','fixture never permits computation')
        return super().handle_api(method,path,query)


class FixtureServer(WebAppServer):
    def __init__(self,port,data):
        self.fixed_building=FixedBuildingWorkspace(data)
        service=self.fixed_building.cpu
        service.runner=lambda *a,**k: (_ for _ in ()).throw(AssertionError('worker forbidden'))
        value=json.loads((ROOT/'tests/fixtures/cpu_response/column-navigation-replay.json').read_text(encoding='utf8'))
        for ch,status in [('a','failed'),('b','completed'),('c','running')]:
            rid=ch*32;directory=service.root/'runs'/rid;directory.mkdir(parents=True,exist_ok=False)
            write_artifacts(value,directory);(directory/'input.json').write_text('browser fixture only')
            record=dict(run_id=rid,client_request_id=rid,status=status,source=value['source'],input_fingerprint=value['input_fingerprint'],created_at='2026-10-22T12:00:00Z',process={'wall_s':1})
            json_write(directory/'job.json',record);service.requests[rid]=rid
        ThreadingHTTPServer.__init__(self,('127.0.0.1',port),Handler)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8899);p.add_argument('--data',type=Path,required=True);a=p.parse_args()
    server=FixtureServer(a.port,a.data)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
