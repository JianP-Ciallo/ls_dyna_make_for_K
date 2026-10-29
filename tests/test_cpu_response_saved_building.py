"""Expose sealed earlier building trial evidence, without new computation."""
import json
import pytest
from lsprepost_mcp.architecture.cpu_response.service import CpuResponseService
from lsprepost_mcp.architecture.cpu_response.api import handle_cpu_response_request, PREFIX
from lsprepost_mcp.architecture.cpu_response.results import json_write, write_artifacts
from test_cpu_response_results import fixture_result


def archive(root):
    value=fixture_result();value['source']={'kind':'regularized_building_reference','id':'three-storey-structural-reference'}
    value['mesh']['kind']='building_reference'
    value['provenance']={'case':{'analysis':{'duration_s':.15,'dt_s':.0001},'loads':{'target_component_id':'wall','curve_si':[[0,0],[.001,10000],[.01,0]]}},'whole_building_convergence_verified':False}
    write_artifacts(value,root);json_write(root/'parent-process.json',{'status':'completed','wall_s':97.9})
    (root/'analysis').mkdir();(root/'analysis'/'report.md').write_text('saved trial report')
    return value


def test_building_archive_reads_saved_results_without_enabling_solver(tmp_path):
    root=tmp_path/'trial';archive(root)
    service=CpuResponseService(tmp_path/'jobs',building_trial_dir=root,runner=lambda *a,**k:pytest.fail('worker forbidden'))
    try:
        code,_,raw=handle_cpu_response_request(service,'GET',PREFIX+'building-trial');value=json.loads(raw)
        assert code==200 and value['status']=='saved_trial'
        assert value['solver_enabled'] is False and value['convergence_verified'] is False
        assert value['trial']['duration_ms']==150 and value['trial']['peak_pressure_kpa']==10
        assert value['trial']['wall_s']==97.9 and not (tmp_path/'jobs').exists()
        code,headers,raw=handle_cpu_response_request(service,'GET',PREFIX+'building-trial/artifacts/curves.csv')
        assert code==200 and 'text/csv' in headers['Content-Type'] and b'time_s' in raw
        for path in ['building-trial/artifacts/../../input.json','building-trial/artifacts/input.json']:
            assert handle_cpu_response_request(service,'GET',PREFIX+path)[0]==404
        assert handle_cpu_response_request(service,'POST',PREFIX+'building-trial',{})[0]==404
    finally:service.close()


def test_missing_or_corrupt_archive_is_visible_without_fabricated_values(tmp_path):
    root=tmp_path/'trial';service=CpuResponseService(tmp_path/'jobs',building_trial_dir=root)
    try:
        assert service.building_trial()['status']=='unavailable'
        archive(root);(root/'result.json').write_text('{}')
        value=service.building_trial()
        assert value['status']=='unavailable' and value['trial'] is None
        assert value['solver_enabled'] is False
        assert handle_cpu_response_request(service,'GET',PREFIX+'building-trial/artifacts/result.json')[0] in (400,409)
    finally:service.close()
