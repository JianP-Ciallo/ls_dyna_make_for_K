"""Inspect a prepared reference; --run explicitly starts ONE owned trial worker.

The flag enforces intentional execution, not project heavy-test authorization.
Follow AGENTS.md and obtain the required current scope/time approval first.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lsprepost_mcp.architecture.cpu_response.building_solver import validate_reference
from lsprepost_mcp.architecture.cpu_response.contracts import fingerprint,adapter_identity
from lsprepost_mcp.architecture.cpu_response.results import json_write,load_result
from lsprepost_mcp.architecture.cpu_response.runtime import DEFAULT_PYTHON,run_process,runtime_identity


def main(argv=None,*,runner=run_process):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',type=Path,required=True)
    p.add_argument('--run',action='store_true');p.add_argument('--output-dir',type=Path);args=p.parse_args(argv)
    if args.case.stat().st_size>950_000:raise ValueError('prepared case exceeds worker input budget')
    case=validate_reference(json.loads(args.case.read_text(encoding='utf8')))
    identity=fingerprint(case)
    if not args.run:
        print(json.dumps(dict(status='prepared_only',input_fingerprint=identity,source=case['source'],
            nodes=len(case['nodes']),elements=len(case['elements']),mass_points=len(case['mass_points']),
            duration_s=case['analysis']['duration_s'],dt_s=case['analysis']['dt_s'],wall_budget_s=case['budget']['wall_s'],
            loads=case['loads'],checks=case['checks']),ensure_ascii=False));return 0
    if args.output_dir is None:p.error('--run requires a new --output-dir')
    runtime=json.loads((DEFAULT_PYTHON.parent/'capabilities.json').read_text(encoding='utf8'))
    if not runtime.get('verified') or not runtime.get('available') or runtime['runtime_identity']!=runtime_identity(DEFAULT_PYTHON):raise ValueError('native runtime must be verified again')
    dest=args.output_dir.resolve();dest.mkdir(parents=True,exist_ok=False)
    request=dict(operation='solve_building_reference',case=case,input_fingerprint=identity,adapter_identity=adapter_identity(),runtime=runtime)
    json_write(dest/'input.json',request)
    outcome=runner([str(DEFAULT_PYTHON),'-m','lsprepost_mcp.architecture.cpu_response.worker','--input',str(dest/'input.json'),'--output',str(dest)],
                   timeout_s=case['budget']['wall_s'],log_dir=dest)
    if outcome['status']=='completed':
        result=load_result(dest)
        if result['input_fingerprint']!=identity or result['source']!=case['source'] or result['provenance']['adapter_identity']!=request['adapter_identity']:
            outcome=dict(outcome,status='failed',reason='worker result identity mismatch')
    json_write(dest/'parent-process.json',outcome)
    print(json.dumps(outcome));return 0 if outcome['status']=='completed' else 1


if __name__=='__main__':raise SystemExit(main())
