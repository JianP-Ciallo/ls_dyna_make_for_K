"""Isolated integration fixture: REAL previews, SYNTHETIC tasks, NO native solver."""
import argparse
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from lsprepost_mcp.web.app import WebAppServer,WebAppHandler,ApiError,json_ok
from lsprepost_mcp.web.fixed_building_workspace import FixedBuildingWorkspace
from lsprepost_mcp.architecture.scene_blast.service import SceneBlastService,write_json


def synthetic(snapshot,directory,cancel):
    # A visible fixture label prevents these frames being mistaken for physics evidence.
    time.sleep(.6);model=snapshot['model'];count=len(model['bodies']);frames=[]
    write_json(directory/'gravity.json',dict(schema_version='scene-blast-gravity@1',status='converged',
        input_fingerprint=snapshot['input_fingerprint'],model_fingerprint=snapshot['model_fingerprint'],method=snapshot['method'],
        accepted_load_factor=1.,blast_applied=False,wall_s=.1,
        reason='SYNTHETIC BROWSER FIXTURE ONLY — 不是自重求解证据',
        last_stability=dict(status='positive_definite',matrix_dofs=6,blocks=[dict(method='synthetic_fixture_only')]),
        final=dict(scaled_relative_residual=0.,force_residual_n=0.,moment_residual_nm=0.,
            connections=dict(cracked_concrete=0,compression_plastic=0,shear_plastic=0,steel_plastic=0))))
    for i,t in enumerate([0.,.05,.1]):
        frames.append(dict(time_s=t,translation_m=[[i*.0005,0.,0.] for _ in range(count)],rotation_xyzw=[[0.,0.,0.,1.] for _ in range(count)],displacement_mm=[i*.5]*count,damage=[i*.2]*count,steel_mpa=[i*20.]*count,pressure_kpa=[i*5.]*count))
    return dict(schema_version='scene-blast-result@1',status='completed',input_fingerprint=snapshot['input_fingerprint'],model_fingerprint=snapshot['model_fingerprint'],method=snapshot['method'],source=model['source'],config=snapshot['config'],frames=frames,curves=[],peaks=dict(displacement_mm=[1.]*count,steel_mpa=[40.]*count,damage=[.4]*count),events=[dict(time_s=.05,kind='cracking',body_id=model['bodies'][0]['id'])],metrics=dict(wall_s=.6,dt_s=.0001,planned_steps=1000,completed_steps=1000,gravity_relative_residual=0.,mass_kg=model['mass_ledger']['total_kg']),limitations=['SYNTHETIC BROWSER FIXTURE ONLY — 这些帧不是建筑求解结果'])


class Handler(WebAppHandler):
    def handle_api(self,method,path,query):
        if path=='/api/test-scene-blast' and method=='GET':return json_ok(dict(isolated_no_compute=True))
        if method=='POST' and not path.startswith('/api/cpu-blast/'):
            raise ApiError(403,'fixture_forbids_computation','This fixture never allows any real computation or project mutation')
        return super().handle_api(method,path,query)


class Server(WebAppServer):
    def __init__(self,port,data):
        self.fixed_building=FixedBuildingWorkspace(data)
        self.fixed_building.cpu.runner=lambda *a,**k:(_ for _ in ()).throw(AssertionError('native worker forbidden'))
        self.fixed_building._scene_cpu=SceneBlastService(Path(data)/'scene_cpu',runner=synthetic)
        ThreadingHTTPServer.__init__(self,('127.0.0.1',port),Handler)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8900);p.add_argument('--data',type=Path,required=True);args=p.parse_args()
    server=Server(args.port,args.data)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
