"""Explicit small-case CPU benchmark. Does not select any building or heavy case."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lsprepost_mcp.architecture.cpu_response.benchmarks import make_benchmark
from lsprepost_mcp.architecture.cpu_response.contracts import fingerprint
from lsprepost_mcp.architecture.cpu_response.results import json_write
from lsprepost_mcp.architecture.cpu_response.runtime import DEFAULT_PYTHON,run_process


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=['column','panel'],required=True)
    parser.add_argument('--matrix',choices=['baseline','convergence','acceptance'],default='baseline')
    parser.add_argument('--wall-budget-s',type=float,default=180)
    parser.add_argument('--case-timeout-s',type=float,default=30)
    parser.add_argument('--duration-ms',type=int,choices=[15,150],default=150,
                        help='explicit analysis window; 15 ms isolates load/early peaks under the same watchdog')
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    if args.matrix=='acceptance' and args.duration_ms!=150:parser.error('acceptance always uses the full 150 ms window')
    if not 0<args.wall_budget_s<=180 or not 0<args.case_timeout_s<=30:parser.error('small-case budget exceeded')
    root=args.output_dir.resolve()
    if root.exists() and any(root.iterdir()):parser.error('use a new empty evidence directory')
    root.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();reports=[]
    variants=[('base',0.0001)] if args.matrix=='baseline' else [('base',0.0001),('medium',0.0001),('fine',0.0001),('medium',0.00005)]
    if args.matrix=='acceptance':variants=[('fine',0.0001),('ultra',0.0001),('ultra',0.00005)]
    for i,(refinement,dt) in enumerate(variants):
        left=args.wall_budget_s-(time.monotonic()-started)
        if left<=0:break
        dest=root if args.matrix=='baseline' else root/f'variant-{i}'
        dest.mkdir(exist_ok=True)
        case=make_benchmark('rc-column-v1' if args.case=='column' else 'rc-panel-v1',refinement)
        case['analysis']['dt_s']=dt;case['budget']['wall_s']=args.case_timeout_s
        case['analysis']['duration_s']=args.duration_ms/1000
        case['loads']['curve_si'][-1][0]=args.duration_ms/1000
        snapshot=dict(operation='benchmark',case=case,input_fingerprint=fingerprint(case),
                      repeats=3 if args.matrix=='baseline' else 0,wall_budget_s=left)
        json_write(dest/'input.json',snapshot)
        outcome=run_process([str(DEFAULT_PYTHON),'-m','lsprepost_mcp.architecture.cpu_response.worker',
                             '--input',str(dest/'input.json'),'--output',str(dest)],
                            timeout_s=left,case_timeout_s=args.case_timeout_s,phase_file=dest/'phase.json',log_dir=dest)
        json_write(dest/'parent-process.json',outcome);reports.append(dict(refinement=refinement,dt_s=dt,**outcome))
        print(json.dumps(reports[-1]),flush=True)
        if outcome['status']!='completed':break
    json_write(root/'matrix.json',dict(scope=args.matrix,duration_ms=args.duration_ms,variants=reports,elapsed_s=time.monotonic()-started))
    return 0 if len(reports)==len(variants) and all(r['status']=='completed' for r in reports) else 1


if __name__=='__main__':raise SystemExit(main())
