"""History deletion is reversible metadata only; never launch a worker."""
import json
import pytest
from lsprepost_mcp.architecture.cpu_response.service import CpuResponseService, CpuConflict
from lsprepost_mcp.architecture.cpu_response.api import handle_cpu_response_request, PREFIX
from lsprepost_mcp.architecture.cpu_response.results import json_write, write_artifacts
from test_cpu_response_results import fixture_result


def seed(service, status='completed', rid='a'*32):
    root=service.root/'runs'/rid;root.mkdir(parents=True)
    source={'kind':'benchmark','id':'rc-column-v1'}
    record=dict(run_id=rid,client_request_id=rid,source=source,status=status,created_at='2026-10-22T12:00:00Z',input_fingerprint='b'*64)
    json_write(root/'job.json',record);(root/'input.json').write_text('original input')
    value=fixture_result();value['source']=source;write_artifacts(value,root)
    service.requests[rid]=rid
    return root


@pytest.mark.parametrize('status',['completed','failed','cancelled','interrupted'])
def test_delete_and_restore_preserve_all_saved_artifacts(tmp_path,status):
    service=CpuResponseService(tmp_path,runner=lambda *a,**k:pytest.fail('no worker allowed'))
    try:
        root=seed(service,status);original={p.name:p.read_bytes() for p in root.iterdir() if p.name!='job.json'}
        deleted=service.delete_run('a'*32)
        assert deleted['deleted_at']
        assert service.history('benchmark','rc-column-v1')==[]
        assert service.history('benchmark','rc-column-v1',deleted=True)[0]['status']==status
        assert service.delete_run('a'*32)['deleted_at']==deleted['deleted_at']
        with pytest.raises(CpuConflict):service.get_results('a'*32)
        assert not service.restore_run('a'*32).get('deleted_at')
        assert service.history('benchmark','rc-column-v1')[0]['status']==status
        assert {p.name:p.read_bytes() for p in root.iterdir() if p.name!='job.json'}==original
    finally:service.close()


@pytest.mark.parametrize('status',['queued','running'])
def test_delete_rejects_active_jobs_without_cancelling_them(tmp_path,status):
    service=CpuResponseService(tmp_path)
    try:
        seed(service,status)
        with pytest.raises(CpuConflict):service.delete_run('a'*32)
        assert service.get_run('a'*32)['status']==status
        assert not service.get_run('a'*32).get('deleted_at')
    finally:service.close()


def test_trash_is_persistent_and_closed_api_rejects_extra_fields(tmp_path):
    service=CpuResponseService(tmp_path)
    try:
        seed(service)
        code,_,_=handle_cpu_response_request(service,'POST',PREFIX+'runs/'+'a'*32+'/delete',{'all':True})
        assert code==400
        for action in ['delete','restore','delete']:
            code,_,body=handle_cpu_response_request(service,'POST',PREFIX+'runs/'+'a'*32+'/'+action,{})
            assert code==200,json.loads(body)
        code,_,body=handle_cpu_response_request(service,'GET',PREFIX+'sources/benchmark/rc-column-v1/deleted-runs')
        assert code==200 and len(json.loads(body)['runs'])==1
        code,_,_=handle_cpu_response_request(service,'GET',PREFIX+'runs/'+'a'*32+'/delete')
        assert code==404
    finally:service.close()
    service=CpuResponseService(tmp_path)
    try:
        assert service.history('benchmark','rc-column-v1')==[]
        assert len(service.history('benchmark','rc-column-v1',deleted=True))==1
        with pytest.raises(ValueError):service.delete_run('../outside')
    finally:service.close()
