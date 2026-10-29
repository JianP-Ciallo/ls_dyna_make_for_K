"""Performance evidence distinguishes missing runs from zeros and cold from warm."""
import importlib
import pytest


def module():
    try:return importlib.import_module('lsprepost_mcp.architecture.cpu_response.benchmarking')
    except ModuleNotFoundError:pytest.fail('CPU benchmark report is missing')


def test_warm_summary_excludes_cold_and_does_not_pad_missing_runs():
    value=module().summarize_runs([
        {'status':'completed','case_wall_s':99,'timings':{'solve_s':9}},
        {'status':'completed','case_wall_s':3,'timings':{'solve_s':0.3}},
        {'status':'completed','case_wall_s':1,'timings':{'solve_s':0.1}},
        {'status':'completed','case_wall_s':2,'timings':{'solve_s':0.2}},
    ],expected_warm=3)
    assert value['status']=='completed'
    assert value['warm_wall_median_s']==2
    assert value['warm_solve_median_s']==pytest.approx(0.2)
    partial=module().summarize_runs([{'status':'completed','case_wall_s':99,'timings':{'solve_s':9}}],expected_warm=3)
    assert partial['status']=='partial'
    assert partial['warm_wall_median_s'] is None


def test_cold_only_matrix_report_does_not_require_warm_measurements(tmp_path,monkeypatch):
    from lsprepost_mcp.architecture.cpu_response import backend_opensees
    from lsprepost_mcp.architecture.cpu_response.benchmarks import make_benchmark
    from test_cpu_response_results import fixture_result
    value=fixture_result();value['diagnostics']['timings']={'solve_s':0.01};value['diagnostics']['accepted_steps']=1
    monkeypatch.setattr(backend_opensees,'solve_case',lambda *args:value)
    report=module().measure_case(make_benchmark('rc-column-v1'),0,output_dir=tmp_path)
    assert report['summary']['status']=='completed'
    assert report['summary']['warm_wall_median_s'] is None
    assert '未运行' in (tmp_path/'report.md').read_text(encoding='utf8')
