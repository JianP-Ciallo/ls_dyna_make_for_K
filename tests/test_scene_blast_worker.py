"""One native NUMPY worker with ONE macro block; never a building/city case."""
import time

from lsprepost_mcp.architecture.scene_blast.contracts import normalize_input
from lsprepost_mcp.architecture.scene_blast.service import SceneBlastService,read_json
from lsprepost_mcp.architecture.scene_blast.sources import shell_model


def test_owned_worker_micro_block_roundtrip(tmp_path):
    def prepare(config):
        m=shell_model('one-micro-block',[(1,0,0,0),(2,1,0,0),(3,1,0,1),(4,0,0,1)],[(1,1,1,2,3,4)],.2)
        m.update(source=dict(config['source'],fixture='ONE_BLOCK_NOT_A_BUILDING'),assumptions=['one-block worker fixture only']);return m
    s=SceneBlastService(tmp_path,prepare=prepare)
    try:
        c=normalize_input({'source':{'kind':'commercial_supermarket'},'tnt':{'position_m':[0,-5,0],'mass_kg':.01},'analysis':{'duration_s':.05}});p=s.prepare(c)
        j=s.submit({'input':c,'model_fingerprint':p['model_fingerprint'],'request_id':'e'*32});deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            j=s.job(j['run_id'])
            if j['status'] not in {'queued','running'}:break
            time.sleep(.02)
        assert j['status']=='completed',j
        r=s.result(j['run_id']);assert r['metrics']['mass_kg']==480.
        assert r['peaks']['displacement_mm'][0]>0
        process=read_json(tmp_path/'runs'/j['run_id']/'process.json');assert process['returncode']==0
        assert process['wall_s']<15
    finally:s.close()
