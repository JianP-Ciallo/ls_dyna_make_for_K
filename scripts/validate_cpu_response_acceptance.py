"""Read and verify saved small-case results; starts no solver or model generation."""
import argparse,json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lsprepost_mcp.architecture.cpu_response.acceptance import assess_convergence,result_measurement
from lsprepost_mcp.architecture.cpu_response.contracts import fingerprint,normalize_case
from lsprepost_mcp.architecture.cpu_response.results import json_write,load_result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);args=p.parse_args()
    dest=args.output_dir.resolve();dest.mkdir(parents=True,exist_ok=False);cases={}
    for kind in ('column','panel'):
        rows=[]
        for index in range(3):
            folder=args.root/kind/f'variant-{index}'
            snapshot=json.loads((folder/'input.json').read_text());case=normalize_case(snapshot['case'])
            if case['geometry']['kind']!=kind:raise ValueError('acceptance folder contains a different reference case')
            result=load_result(folder/'run-0');process=json.loads((folder/'parent-process.json').read_text())
            if result['input_fingerprint']!=fingerprint(case) or result['source']!=case['source']:raise ValueError('saved acceptance input/result mismatch')
            rows.append(result_measurement(case,result,process))
        cases[kind]=dict(assess_convergence(rows),measurements=rows)
    report=dict(schema_version='cpu-response.acceptance@1',scope='elastic_reference_cases_only',passed=all(v['passed'] for v in cases.values()),
                thresholds=dict(peak_relative_change=.02,period_relative_change=.02,energy_drift=.005,case_wall_s=30),cases=cases)
    json_write(dest/'acceptance.json',report)
    lines=['# CPU 弹性参考算例验收','',f"总状态：{'通过' if report['passed'] else '未通过'}；完整 150 ms 时窗，16→32 空间细化及 32 网格步长减半。",'',
           '| 算例 | 空间位移变化 | 空间钢筋峰值变化 | 步长钢筋峰值变化 | 最细算例耗时 |','| --- | --- | --- | --- | --- |']
    for name,value in cases.items():
        c=value['changes'];percent=lambda v:f'{v:.4%}' if isinstance(v,(int,float)) else '未测'
        lines.append(f"| {name} | {percent(c['space']['displacement_m'])} | {percent(c['space']['steel_abs_pa'])} | {percent(c['time']['steel_abs_pa'])} | {value['measurements'][-1]['wall_s']:.3f} s |")
    lines+=['','数据由保存结果及哈希核对后生成。通过仅针对这两个弹性参考模型，不代表实际建筑或真实爆炸精度。各门槛、峰时、周期、能量和采样位置见 acceptance.json。']
    (dest/'acceptance.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=report['passed'],cases={k:dict(passed=v['passed'],failed=[n for n,ok in v['checks'].items() if not ok]) for k,v in cases.items()})))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
