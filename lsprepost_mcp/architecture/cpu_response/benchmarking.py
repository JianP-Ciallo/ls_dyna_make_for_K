"""Measured cold/warm runs; never substitutes timing targets for measurements."""
from pathlib import Path
import statistics
import time
from .results import json_write,write_artifacts

BenchmarkReport=dict


def summarize_runs(runs: list[dict],expected_warm: int=3) -> dict:
    warm=[r for r in runs[1:] if r['status']=='completed']
    walls=[r['case_wall_s'] for r in warm]
    return dict(status='completed' if len(warm)==expected_warm else 'partial',
                completed_runs=sum(r['status']=='completed' for r in runs),expected_runs=expected_warm+1,
                warm_wall_median_s=statistics.median(walls) if walls else None,
                warm_wall_range_s=[min(walls),max(walls)] if walls else None,
                warm_solve_median_s=statistics.median(r['timings']['solve_s'] for r in warm) if warm else None)


def measure_case(case: dict,repeats: int,control=None,output_dir: Path | None=None) -> dict:
    from .backend_opensees import solve_case,RunControl
    if repeats not in (0,3):raise ValueError('reference benchmark uses one cold and three warm runs')
    root=Path(output_dir) if output_dir else None
    runs=[];started=time.monotonic()
    control=control or RunControl(deadline=started+180)
    for index in range(repeats+1):
        control.check();tick=time.perf_counter()
        if root:json_write(root/'phase.json',dict(phase_id=index))
        run_control=RunControl(deadline=min(control.deadline,time.monotonic()+case['budget']['wall_s']))
        result=solve_case(case,run_control)
        writing=time.perf_counter()
        if root:write_artifacts(result,root/f'run-{index}')
        record=dict(status='completed',kind='cold' if index==0 else 'warm',case_wall_s=time.perf_counter()-tick,
                    artifact_write_s=time.perf_counter()-writing,timings=result['diagnostics']['timings'],
                    peaks=result['peaks'],accepted_steps=result['diagnostics']['accepted_steps'],
                    input_fingerprint=result['input_fingerprint'])
        runs.append(record)
        report=dict(schema_version='cpu-response.benchmark@1',source=case['source'],runs=runs,
                    summary=summarize_runs(runs,repeats),case=case,provenance=result['provenance'],
                    worker_reused=True,each_run_rebuilds_model=True,elapsed_s=time.monotonic()-started,
                    browser_render_ms=None,browser_status='not_measured')
        if root:json_write(root/'report.json',report)
    if root:
        summary=report['summary']
        timing=(f"预热后总耗时中位数 {summary['warm_wall_median_s']:.4f} s；内核推进中位数 {summary['warm_solve_median_s']:.4f} s。"
                if summary['warm_wall_median_s'] is not None else f"首次耗时 {runs[0]['case_wall_s']:.4f} s；预热实验未运行。")
        (root/'report.md').write_text(
            '# CPU 小算例实测报告\n\n'+f"算例：{case['source']['id']}；范围：弹性参考模型。\n\n"
            +f"完成：{summary['completed_runs']}/{summary['expected_runs']}；{timing}\n\n"
            +'每次清空并重建模型；首次含内核导入，父进程启动耗时另记录。钢筋为截面纤维或配筋层轴向应力。浏览器渲染另测；不代表真实爆炸或三层建筑性能。\n',encoding='utf8')
    return report
