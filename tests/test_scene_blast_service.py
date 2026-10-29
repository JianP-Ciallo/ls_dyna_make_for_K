import json
from pathlib import Path
import time

import pytest

from lsprepost_mcp.architecture.scene_blast.contracts import normalize_input
from lsprepost_mcp.architecture.scene_blast.service import SceneBlastService


def tiny_prepare(config):
    from lsprepost_mcp.architecture.scene_blast.sources import shell_model
    m=shell_model('tiny',[(1,0,0,0),(2,1,0,0),(3,1,0,1),(4,0,0,1)],[(1,1,1,2,3,4)],.2)
    m.update(source=dict(config['source'],definition_fingerprint='fixture'),assumptions=['unit fixture only'])
    return m


def wait_job(service,rid):
    for _ in range(200):
        j=service.job(rid)
        if j['status'] not in {'queued','running'}:return j
        time.sleep(.005)
    raise AssertionError('synthetic worker did not finish')


def test_prepare_never_runs_worker_and_submission_is_frozen_idempotent(tmp_path):
    calls=[]
    def runner(snapshot,directory,cancel):
        calls.append(snapshot)
        return {'schema_version':'scene-blast-result@1','status':'completed','input_fingerprint':snapshot['input_fingerprint'],'model_fingerprint':snapshot['model_fingerprint'],'method':snapshot['method'],'frames':[{'time_s':0}], 'curves':[], 'peaks':{}}
    s=SceneBlastService(tmp_path,prepare=tiny_prepare,runner=runner)
    config=normalize_input({'source':{'kind':'commercial_supermarket'},'tnt':{'position_m':[2,-5,0],'mass_kg':1}})
    prepared=s.prepare(config)
    assert calls==[]
    payload={'input':config,'model_fingerprint':prepared['model_fingerprint'],'request_id':'a'*32}
    job=s.submit(payload);assert s.submit(payload)['run_id']==job['run_id']
    config['tnt']['mass_kg']=100
    assert wait_job(s,job['run_id'])['status']=='completed'
    assert len(calls)==1 and calls[0]['config']['tnt']['mass_kg']==1
    assert s.result(job['run_id'])['status']=='completed'
    s.delete(job['run_id']);assert not s.history()
    assert len(s.history(include_deleted=True))==1
    s.restore(job['run_id']);assert len(s.history())==1
    s.close()


def test_stale_models_indoor_bursts_and_changed_idempotency_are_rejected(tmp_path):
    s=SceneBlastService(tmp_path,prepare=tiny_prepare,runner=lambda *a:pytest.fail('worker should not launch'))
    config=normalize_input({'source':{'kind':'commercial_supermarket'},'tnt':{'position_m':[2,-5,0],'mass_kg':1}})
    p=s.prepare(config)
    with pytest.raises(ValueError,match='模型'):
        s.submit({'input':config,'model_fingerprint':'stale','request_id':'b'*32})
    config['tnt']['position_m']=[.5,0,0]
    with pytest.raises(ValueError,match='室外|内部'):
        s.submit({'input':config,'model_fingerprint':p['model_fingerprint'],'request_id':'c'*32})
    config['tnt']['position_m']=[1.06,0,0]
    with pytest.raises(ValueError,match='缩尺距离'):
        s.submit({'input':config,'model_fingerprint':p['model_fingerprint'],'request_id':'c'*32})
    s.close()


def test_result_tampering_and_active_deletion_fail(tmp_path):
    import threading
    started=threading.Event();release=threading.Event()
    def runner(snapshot,directory,cancel):
        started.set();release.wait(2)
        return {'schema_version':'scene-blast-result@1','status':'cancelled','input_fingerprint':snapshot['input_fingerprint'],'model_fingerprint':snapshot['model_fingerprint'],'method':snapshot['method'],'frames':[{'time_s':0}]}
    s=SceneBlastService(tmp_path,prepare=tiny_prepare,runner=runner)
    c=normalize_input({'source':{'kind':'commercial_supermarket'},'tnt':{'position_m':[2,-5,0],'mass_kg':1}});p=s.prepare(c)
    j=s.submit({'input':c,'model_fingerprint':p['model_fingerprint'],'request_id':'d'*32});started.wait(1)
    with pytest.raises(ValueError):s.delete(j['run_id'])
    s.cancel(j['run_id']);release.set();wait_job(s,j['run_id'])
    path=tmp_path/'runs'/j['run_id']/'result.json';path.write_text('{}')
    with pytest.raises(ValueError,match='校验'):s.result(j['run_id'])
    s.close()


def test_full_input_snapshot_is_sealed_and_timeouts_are_not_generic_failures(tmp_path):
    from lsprepost_mcp.architecture.scene_blast.service import ProcessStopped,read_json,write_json
    def runner(*args):raise ProcessStopped('timed_out','owned worker exceeded its budget')
    s=SceneBlastService(tmp_path,prepare=tiny_prepare,runner=runner)
    try:
        c=normalize_input({'source':{'kind':'commercial_supermarket'},'tnt':{'position_m':[2,-5,0],'mass_kg':1}});p=s.prepare(c)
        j=s.submit({'input':c,'model_fingerprint':p['model_fingerprint'],'request_id':'f'*32});assert wait_job(s,j['run_id'])['status']=='timed_out'
        path=tmp_path/'runs'/j['run_id']/'input.json';v=read_json(path);v['material']['e_pa']/=2;write_json(path,v)
        with pytest.raises(ValueError,match='校验'):s.input(j['run_id'])
    finally:s.close()


def test_atomic_json_write_retries_short_windows_reader_sharing_conflicts(tmp_path,monkeypatch):
    from lsprepost_mcp.architecture.scene_blast.service import write_json,read_json
    original=Path.replace;attempts=[]
    def sharing_conflict(path,target):
        if path.name.startswith('atomic.json'):
            attempts.append(1)
            if len(attempts)<3:raise PermissionError('short-lived Windows reader sharing conflict')
        return original(path,target)
    monkeypatch.setattr(Path,'replace',sharing_conflict)
    write_json(tmp_path/'atomic.json',{'sealed':True})
    assert read_json(tmp_path/'atomic.json')=={'sealed':True} and len(attempts)==3
