"""Explicit bounded static refinement evidence, separate from default pytest."""
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).parent))
from test_cpu_response_references import column_reference,plate_reference
from lsprepost_mcp.architecture.cpu_response.benchmarks import make_benchmark
from lsprepost_mcp.architecture.cpu_response.backend_opensees import solve_case,RunControl
from lsprepost_mcp.architecture.cpu_response.results import json_write,write_artifacts


def main():
    root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=False)
    references=dict(column=column_reference(),panel=plate_reference());rows=[]
    for kind in ('column','panel'):
        for n in (4,8,16):
            for fibers in ((10,20) if kind=='column' else (None,)):
                case=make_benchmark('rc-'+kind+'-v1');case['mesh']['n']=n
                if fibers:case['mesh']['fibers']=fibers
                case['analysis']['kind']='static'
                value=solve_case(case,RunControl(deadline=time.monotonic()+30))
                dest=root/(kind+'-'+str(n)+('-f'+str(fibers) if fibers else ''))
                write_artifacts(value,dest)
                actual=value['peaks']['displacement_m'];expected=references[kind]['tip_static_m' if kind=='column' else 'center_w_m']
                rows.append(dict(kind=kind,n=n,fibers=fibers,displacement_m=actual,reference_m=expected,
                                 relative_error=abs(actual/expected-1),steel_abs_pa=value['peaks']['steel_abs_pa']))
    json_write(root/'references.json',references)
    json_write(root/'static-convergence.json',dict(rows=rows,algorithm='independent continuous composite EI / orthotropic Navier 100 terms',units='SI'))
    assert max(r['relative_error'] for r in rows if r['n']==16 and r['kind']=='column')<0.02
    assert max(r['relative_error'] for r in rows if r['n']==16 and r['kind']=='panel')<0.05
    print(json.dumps(rows))


if __name__=='__main__':main()
