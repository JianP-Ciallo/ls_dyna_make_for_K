"""Isolated gravity-only request/worker. Preparing or validating NEVER solves.

The agent must obtain current explicit user approval before launching the real
worker. This module does not expose a web endpoint or submit production tasks.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np
from .contracts import fingerprint
from .native_subdomain import partition
from .native_materials import concrete_laws
from ..cpu_response.building_solver import validate_reference
from ..cpu_response.runtime import runtime_identity
from ..cpu_response.results import json_write


def method_fingerprint():
    here=Path(__file__).resolve().parent
    paths=[here/name for name in ('native_materials.py','native_plane_stress.py','native_reference.py','native_subdomain.py','native_prebalance.py','contracts.py')]
    paths+=[here.parent/'cpu_response'/name for name in ('building_solver.py','building_mapping.py','gravity_mapping.py','runtime.py')]
    paths.append(here.parents[2]/'scripts/run_native_prebalance.py')
    return fingerprint({str(p.relative_to(here.parents[2])):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})


def preflight(case,indices):
    validate_reference(case);p=partition(case,indices)
    if len(indices)!=13:raise ValueError('本次仅允许约定的完整13单元子域')
    counts=[len(case[k]) for k in ('nodes','elements','mass_points')]
    if any(n>limit for n,limit in zip(counts,(640,600,4000))):raise ValueError('预平衡规模预算超限')
    n=6*(len(case['nodes'])-len(case['fixed_nodes']))
    if n>3072:raise ValueError('预平衡物理切线预算超限')
    xyz=np.asarray(case['nodes'])
    for e in case['elements']:
        points=xyz[e['nodes']]
        if e['kind']=='panel':
            area=np.linalg.norm(np.cross(points[1]-points[0],points[3]-points[0]))
            concrete_laws(case['panel_sections'][e['section']]['concrete_e_pa'],float(np.sqrt(area)))
        else:
            length=float(np.linalg.norm(points[1]-points[0]));elastic=case['column_sections'][e['section']]['materials']['concrete_e_pa']
            for w in (1/6,2/3,1/6):concrete_laws(elastic,length*w)
    return dict(execution_status='not_run_requires_current_user_confirmation',structural_nodes=counts[0],elements=counts[1],mass_points=counts[2],
        free_structural_dofs=n,dense_tangent_matrix_bytes=8*n*n,subdomain=p,
        scope='100_percent_self_weight_only_then_same_domain_13_element_static_acceptance',
        gravity_m_s2=9.80665,physical_residual_limit=1e-5,scaled_tangent_threshold=1e-9,TNT=False,
        automatic_retries=0,production_dispatch=False,maximum_load_attempts=128,minimum_load_increment=1/4096,
        internal_backtracking='only_after_native_revert_matches_accepted_state_no_model_restart')


def prepare_request(case,indices,python_executable):
    # JSON round-trip freezes caller-owned mutable data without importing ops.
    case=json.loads(json.dumps(case,allow_nan=False));exe=str(Path(python_executable).resolve())
    return dict(schema_version='native-prebalance-request@1',operation='gravity_prebalance_and_subdomain',case=case,
        case_fingerprint=fingerprint(case),method_fingerprint=method_fingerprint(),python_executable=exe,
        runtime_identity=runtime_identity(exe),target_elements=sorted(indices),budget=dict(worker_wall_s=150.,parent_timeout_s=180.),
        preflight=preflight(case,indices))


def validate_request(request):
    keys={'schema_version','operation','case','case_fingerprint','method_fingerprint','python_executable','runtime_identity','target_elements','budget','preflight'}
    if set(request)!=keys or request['schema_version']!='native-prebalance-request@1' or request['operation']!='gravity_prebalance_and_subdomain':raise ValueError('invalid prebalance request scope')
    if request['case_fingerprint']!=fingerprint(request['case']) or request['method_fingerprint']!=method_fingerprint():raise ValueError('预平衡输入或方法已改变，需重新准备并确认')
    if request['runtime_identity']!=runtime_identity(request['python_executable']):raise ValueError('预平衡原生运行时已改变')
    if request['budget']!=dict(worker_wall_s=150.,parent_timeout_s=180.):raise ValueError('预平衡预算不符')
    if request['preflight']!=preflight(request['case'],request['target_elements']):raise ValueError('预平衡范围不符')
    return request


def run_worker(request,output):
    validate_request(request)
    if Path(sys.executable).resolve()!=Path(request['python_executable']).resolve():raise ValueError('预平衡解释器不符')
    import openseespy.opensees as ops
    from .native_reference import build_nonlinear_reference,equilibrate_gravity,finite_diagnostics,safe_fields
    from .native_subdomain import extract_and_verify
    output=Path(output);output.mkdir(parents=True,exist_ok=True);started=time.monotonic();model=None;parent=None
    def check():
        if time.monotonic()-started>=request['budget']['worker_wall_s']:raise TimeoutError('prebalance_worker_deadline')
    def status(phase,**values):json_write(output/'worker-status.json',dict(phase=phase,wall_s=time.monotonic()-started,blast_applied=False,**values))
    status('building',case_fingerprint=request['case_fingerprint'])
    try:
        model=build_nonlinear_reference(ops,request['case'],execution_scope='three_storey_prebalance',check=check)
        check();status('gravity',structural_nodes=len(model['nodes']),native_nodes=model['native_node_count'])
        def progress(phase,report):
            names={'accepted':'accepted-state.json','trial':'trial-state.json','attempt':'pending-attempt.json'}
            json_write(output/names[phase],finite_diagnostics(report))
            status('gravity',accepted_load_factor=report.get('accepted_load_factor'),stage=phase)
        parent=equilibrate_gravity(ops,model,checkpoint_dir=output,wall_s=min(150.,150.-(time.monotonic()-started)),progress=progress)
        json_write(output/'parent-equilibrium.json',parent)
        check();status('subdomain');sub=extract_and_verify(ops,model,parent,request['target_elements'],check=check)
        check();json_write(output/'thirteen-element-result.json',sub)
        result=dict(status='completed',scope=request['operation'],case_fingerprint=request['case_fingerprint'],method_fingerprint=request['method_fingerprint'],
            wall_s=time.monotonic()-started,blast_applied=False,parent_load_factor=1.,subdomain_status=sub['status'],automatic_restarts=0)
        json_write(output/'result.json',result);status('completed');return result
    except Exception as exc:
        details=getattr(exc,'diagnostics',None)
        failure=finite_diagnostics(dict(status='failed',reason=str(exc),wall_s=time.monotonic()-started,blast_applied=False,
            case_fingerprint=request['case_fingerprint'],method_fingerprint=request['method_fingerprint'],automatic_restarts=0,
            diagnostics=details,parent=parent,returned_domain_fields=safe_fields(ops,model) if model else None))
        json_write(output/'failure.json',failure);status('failed',reason=str(exc));return failure
    finally:ops.wipe()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    source=Path(args.input)
    if source.stat().st_size>10_000_000:raise ValueError('prebalance input budget')
    request=json.loads(source.read_text(encoding='utf8'));result=run_worker(request,Path(args.output))
    if result['status']!='completed':raise SystemExit(1)


if __name__=='__main__':main()
