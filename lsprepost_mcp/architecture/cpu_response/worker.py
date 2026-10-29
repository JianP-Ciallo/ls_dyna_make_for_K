"""Server-owned argv and JSON only; no eval, user scripts or shell commands."""
import argparse
import json
from pathlib import Path
import time
from .contracts import normalize_case,fingerprint,adapter_identity
from .results import json_write,write_artifacts


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();source=Path(args.input);root=Path(args.output)
    if source.stat().st_size>1_000_000:raise ValueError('worker input size budget exceeded')
    request=json.loads(source.read_text(encoding='utf8'))
    if request.get('operation')=='solve_building_reference':
        from .building_solver import validate_reference
        case=validate_reference(request['case'])
    else:case=normalize_case(request['case'])
    if request['input_fingerprint']!=fingerprint(case):raise ValueError('worker snapshot identity mismatch')
    if request.get('adapter_identity',adapter_identity())!=adapter_identity():raise ValueError('worker adapter changed after submission')
    if 'runtime' in request:
        from .runtime import runtime_identity
        import sys
        if request['runtime'].get('runtime_identity')!=runtime_identity(sys.executable):raise ValueError('native runtime changed after submission')
    root.mkdir(parents=True,exist_ok=True)
    if request.get('operation')=='benchmark':
        from .benchmarking import measure_case
        from .backend_opensees import RunControl
        measure_case(case,request['repeats'],RunControl(deadline=time.monotonic()+request['wall_budget_s']),root)
    elif request.get('operation')=='solve':
        from .backend_opensees import solve_case
        result=solve_case(case);write_artifacts(result,root)
    elif request.get('operation')=='solve_building_reference':
        from .building_solver import solve_building_reference
        result=solve_building_reference(case);write_artifacts(result,root)
    else:raise ValueError('unknown worker operation')


if __name__=='__main__':main()
