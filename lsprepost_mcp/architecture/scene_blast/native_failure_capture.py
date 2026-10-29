"""One gravity capture; no backtracking, replay, subdomain or repair."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from .contracts import fingerprint
from .native_prebalance import method_fingerprint
from ..cpu_response.building_solver import validate_reference
from ..cpu_response.runtime import runtime_identity
from ..cpu_response.results import json_write

POLICY = dict(first_failed_step='stop_after_native_call_returns', backtracking=False,
              retry=False, subdomain=False, repair=False, TNT=False)
BUDGET = dict(worker_wall_s=150., parent_timeout_s=180.)


def prepare_request(case, python_executable):
    case = json.loads(json.dumps(case, allow_nan=False))
    validate_reference(case)
    if any(len(case[k]) > cap for k, cap in zip(('nodes', 'elements', 'mass_points'), (640, 600, 4000))):
        raise ValueError('capture model size budget')
    if 6 * (len(case['nodes']) - len(case['fixed_nodes'])) > 3072:
        raise ValueError('capture tangent budget')
    executable = str(Path(python_executable).resolve())
    module = Path(executable).parent / 'Lib/site-packages/openseespywin/opensees.pyd'
    return dict(schema_version='native-first-failure-capture@1', operation='gravity_first_failure_only',
                case=case, case_fingerprint=fingerprint(case), python_executable=executable,
                runtime_identity=runtime_identity(executable), module_sha256=hashlib.sha256(module.read_bytes()).hexdigest(),
                method_fingerprint=fingerprint(dict(base=method_fingerprint(),
                    capture=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())),
                policy=dict(POLICY), budget=dict(BUDGET))


def validate_request(request):
    if request != prepare_request(request['case'], request['python_executable']):
        raise ValueError('capture input, method, runtime or scope changed')
    return request


def run_worker(request, output):
    validate_request(request)
    if Path(sys.executable).resolve() != Path(request['python_executable']).resolve():
        raise ValueError('capture interpreter mismatch')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    event_path = output / 'native-first-failure.jsonl'
    event_path.touch(exist_ok=False)
    os.environ['OPENSEES_NATIVE_FAILURE_LOG'] = str(event_path)
    # Native environment setting MUST precede the first OpenSees import.
    import openseespy.opensees as ops
    from . import native_reference as n
    started = time.monotonic()
    model = None
    def check():
        if time.monotonic() - started >= 150.:
            raise TimeoutError('capture_worker_deadline')
        if event_path.stat().st_size > 0:
            raise RuntimeError('native_failure_event')
    def has_event():
        return event_path.stat().st_size > 0
    def progress(phase, report):
        check()
        if has_event():
            raise RuntimeError('native_failure_event')
        name = {'accepted': 'accepted-state.json', 'trial': 'returned-trial-state.json', 'attempt': 'pending-attempt.json'}[phase]
        json_write(output / name, n.finite_diagnostics(report))
        json_write(output / 'worker-status.json', dict(phase=phase, wall_s=time.monotonic()-started,
            accepted_load_factor=report.get('accepted_load_factor'), blast_applied=False))
    try:
        json_write(output / 'worker-status.json', dict(phase='building', wall_s=0., blast_applied=False))
        model = n.build_nonlinear_reference(ops, request['case'], execution_scope='three_storey_prebalance', check=check)
        check()
        if has_event():
            raise RuntimeError('native_failure_event_during_build')
        report = n.equilibrate_gravity(ops, model, checkpoint_dir=output,
            wall_s=min(150., 150.-(time.monotonic()-started)), progress=progress,
            stop_on_first_failure=True, failure_probe=has_event)
        result = dict(status='completed', parent_load_factor=1., diagnostics=report)
    except Exception as exc:
        result = dict(status='failed', reason=str(exc), diagnostics=getattr(exc, 'diagnostics', None),
            returned_domain_fields=n.safe_fields(ops, model) if model else None,
            returned_field_scope='after_native_return_no_refresh_or_restore')
    finally:
        ops.wipe()
    try:
        events = [json.loads(line) for line in event_path.read_text(encoding='utf8').splitlines() if line.strip()]
        result['native_event_count'] = len(events)
        if len(events) > 1:
            raise ValueError('more than one first-failure event')
        if events:
            result['status'] = 'failed'
    except Exception as exc:
        result.update(status='failed', diagnostic_read_error=str(exc))
    result.update(operation=request['operation'], case_fingerprint=request['case_fingerprint'],
        method_fingerprint=request['method_fingerprint'], wall_s=time.monotonic()-started,
        policy=request['policy'], automatic_restarts=0, blast_applied=False)
    json_write(output / 'capture-result.json', n.finite_diagnostics(result))
    json_write(output / 'worker-status.json', dict(phase=result['status'], wall_s=result['wall_s'], blast_applied=False))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    source = Path(args.input)
    if source.stat().st_size > 10_000_000:
        raise ValueError('capture request size budget')
    result = run_worker(json.loads(source.read_text(encoding='utf8')), args.output)
    if result['status'] != 'completed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
