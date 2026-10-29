"""CPU HTTP adapter is closed and independent of the full structural template."""
import importlib
import json
import sys
import pytest
from test_cpu_response_service import capability,fake_worker


def test_cpu_routes_preserve_schema_and_distinct_artifact_mime(tmp_path):
    try:
        from lsprepost_mcp.architecture.cpu_response.service import CpuResponseService
        from lsprepost_mcp.architecture.cpu_response.api import handle_cpu_response_request,PREFIX
    except ModuleNotFoundError:pytest.fail('CPU HTTP adapter is missing')
    s=CpuResponseService(tmp_path/'data',python_executable=sys.executable,capability_path=capability(tmp_path),runner=fake_worker)
    try:
        code,headers,raw=handle_cpu_response_request(s,'GET',PREFIX+'benchmarks')
        assert code==200 and len(json.loads(raw)['benchmarks'])==2
        code,_,raw=handle_cpu_response_request(s,'POST',PREFIX+'profiles',{'benchmark_id':'rc-column-v1','python_path':'bad'})
        assert code==400
        code,_,_=handle_cpu_response_request(s,'GET',PREFIX+'runs/../../bad')
        assert code in (400,404)
        code,_,raw=handle_cpu_response_request(s,'HEAD',PREFIX+'capabilities')
        assert code==200 and raw==b''
    finally:s.close()
