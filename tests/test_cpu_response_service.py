"""Persistent immutable profiles/runs with a narrow injected worker boundary."""
import importlib
import json
import sys
import time
import pytest


def module():
    try:return importlib.import_module('lsprepost_mcp.architecture.cpu_response.service')
    except ModuleNotFoundError:pytest.fail('CPU response task service is missing')


def capability(tmp_path):
    from lsprepost_mcp.architecture.cpu_response.runtime import runtime_identity
    p=tmp_path/'capabilities.json'
    p.write_text(json.dumps(dict(available=True,verified=True,column_fiber_stress=True,panel_rebar_stress=True,
                                runtime={'executable':sys.executable},runtime_identity=runtime_identity(sys.executable))))
    return p


def fake_worker(command,**kwargs):
    from pathlib import Path
    from lsprepost_mcp.architecture.cpu_response.results import write_artifacts
    source=Path(command[command.index('--input')+1]);root=Path(command[command.index('--output')+1])
    value=json.loads(source.read_text());case=value['case']
    from test_cpu_response_results import fixture_result
    result=fixture_result();result['source']=case['source'];result['input_fingerprint']=value['input_fingerprint']
    result['provenance']['adapter_identity']=value.get('adapter_identity')
    write_artifacts(result,root)
    return dict(status='completed',returncode=0,wall_s=0.01)


def wait(service,run_id):
    for _ in range(150):
        run=service.get_run(run_id)
        if run['status'] not in ('queued','running'):return run
        time.sleep(0.01)
    future=service.jobs.futures[run_id]
    pytest.fail('task did not reach terminal state; worker exception: '+repr(future.exception() if future.done() else 'still active'))


def test_immutable_snapshot_and_idempotency_and_result_integrity(tmp_path):
    cls=module().CpuResponseService
    service=cls(tmp_path/'cpu',python_executable=sys.executable,capability_path=capability(tmp_path),runner=fake_worker)
    try:
        profile=service.create_profile({'benchmark_id':'rc-column-v1'})
        check=service.preflight(profile['source'],profile['profile_id'])
        run=service.start_run(profile['source'],profile['profile_id'],check['input_fingerprint'],'click-1')
        assert service.start_run(profile['source'],profile['profile_id'],check['input_fingerprint'],'click-1')['run_id']==run['run_id']
        assert wait(service,run['run_id'])['status']=='completed'
        assert service.get_results(run['run_id'])['source']==profile['source']
        other=service.create_profile({'benchmark_id':'rc-panel-v1'})
        with pytest.raises(ValueError):service.start_run(other['source'],other['profile_id'],other['input_fingerprint'],'click-1')
        snapshot=json.loads((tmp_path/'cpu'/'runs'/run['run_id']/'input.json').read_text())
        assert snapshot['case']['geometry']['length_m']==3
        (tmp_path/'cpu'/'runs'/run['run_id']/'result.json').write_text('{}')
        with pytest.raises(ValueError):service.get_results(run['run_id'])
    finally:service.close()


def test_preflight_rejects_stale_fingerprint_and_capability_reads_do_not_start_worker(tmp_path):
    def forbidden(*a,**kw):pytest.fail('GET capability started a worker')
    service=module().CpuResponseService(tmp_path/'cpu',python_executable=sys.executable,capability_path=capability(tmp_path),runner=forbidden)
    try:
        assert service.capabilities()['available']
        p=service.create_profile({'benchmark_id':'rc-column-v1'})
        with pytest.raises(ValueError):service.start_run(p['source'],p['profile_id'],'0'*64,'click-2')
        with pytest.raises(ValueError):service.get_run('../outside')
    finally:service.close()


def test_native_failure_or_cancel_never_publishes_completed(tmp_path):
    import threading
    entered=threading.Event()
    def blocked(command,**kwargs):
        entered.set();kwargs['cancel'].wait(2)
        return dict(status='cancelled',returncode=-1)
    service=module().CpuResponseService(tmp_path/'cpu',python_executable=sys.executable,capability_path=capability(tmp_path),runner=blocked)
    try:
        p=service.create_profile({'benchmark_id':'rc-panel-v1'})
        run=service.start_run(p['source'],p['profile_id'],p['input_fingerprint'],'cancel-1')
        assert entered.wait(2)
        service.cancel(run['run_id'])
        assert wait(service,run['run_id'])['status']=='cancelled'
        with pytest.raises(ValueError):service.get_results(run['run_id'])
    finally:service.close()


def test_changed_adapter_requires_a_new_profile_before_starting(tmp_path,monkeypatch):
    s=module().CpuResponseService(tmp_path/'cpu',python_executable=sys.executable,capability_path=capability(tmp_path),runner=fake_worker)
    try:
        profile=s.create_profile({'benchmark_id':'rc-column-v1'})
        monkeypatch.setattr(module(),'adapter_identity',lambda:'changed-adapter')
        with pytest.raises(ValueError):s.preflight(profile['source'],profile['profile_id'])
    finally:s.close()


def test_restarting_service_marks_unfinished_work_interrupted(tmp_path):
    from pathlib import Path
    p=tmp_path/'cpu'/'runs'/('a'*32);p.mkdir(parents=True)
    (p/'job.json').write_text(json.dumps(dict(run_id='a'*32,client_request_id='orphan',status='running')))
    s=module().CpuResponseService(tmp_path/'cpu',python_executable=sys.executable,capability_path=capability(tmp_path),runner=fake_worker)
    try:assert s.get_run('a'*32)['status']=='interrupted'
    finally:s.close()


def test_replaced_native_binary_invalidates_saved_capability_without_probe(tmp_path):
    exe=tmp_path/'python.exe';exe.write_bytes(b'first')
    from lsprepost_mcp.architecture.cpu_response.runtime import runtime_identity
    p=capability(tmp_path);value=json.loads(p.read_text());value['runtime']['executable']=str(exe)
    value['runtime_identity']=runtime_identity(exe);p.write_text(json.dumps(value))
    s=module().CpuResponseService(tmp_path/'cpu',python_executable=exe,capability_path=p,runner=fake_worker)
    try:
        assert s.capabilities()['verified']
        exe.write_bytes(b'replacement')
        assert not s.capabilities()['available']
    finally:s.close()
