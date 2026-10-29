"""CPU worker environment and parent-enforced lifecycle; no structural solves."""
import importlib
import importlib.util
import sys
import threading
import time


def runtime():
    name = 'lsprepost_mcp.architecture.cpu_response.runtime'
    try:
        found = importlib.util.find_spec(name)
    except ModuleNotFoundError:
        found = None
    assert found is not None, 'isolated CPU runtime adapter is missing'
    return importlib.import_module(name)


def test_missing_interpreter_reports_unavailable_without_crashing(tmp_path):
    info = runtime().inspect_runtime(str(tmp_path / 'missing.exe'))
    assert info['available'] is False
    assert info['reason']


def test_parent_terminates_blocked_owned_worker_before_deadline(tmp_path):
    module = runtime()
    start = time.monotonic()
    result = module.run_process(
        [sys.executable, '-c', 'import time; time.sleep(60)'],
        timeout_s=0.25, log_dir=tmp_path,
    )
    assert result['status'] == 'timeout'
    assert result['returncode'] is not None
    assert time.monotonic() - start < 5


def test_parent_cancel_reaps_worker_and_keeps_exit_diagnostic(tmp_path):
    cancel = threading.Event()
    timer = threading.Timer(0.15, cancel.set)
    timer.start()
    try:
        result = runtime().run_process(
            [sys.executable, '-c', 'import time; time.sleep(60)'],
            timeout_s=5, log_dir=tmp_path, cancel=cancel,
        )
    finally:
        timer.cancel()
    assert result['status'] == 'cancelled'
    assert result['returncode'] is not None


def test_nonzero_child_exit_is_failure_not_a_completed_result(tmp_path):
    result = runtime().run_process(
        [sys.executable, '-c', 'import sys; print("diagnostic"); sys.exit(7)'],
        timeout_s=5, log_dir=tmp_path,
    )
    assert result['status'] == 'failed'
    assert result['returncode'] == 7
    assert 'diagnostic' in (tmp_path / 'stdout.log').read_text()


def test_import_does_not_load_opensees_or_spawn_a_probe():
    runtime()
    assert 'openseespy.opensees' not in sys.modules


def test_parent_enforces_per_case_budget_within_a_reused_worker(tmp_path):
    phase=tmp_path/'phase.json'
    command=[sys.executable,'-c',
             'import json,time,pathlib; pathlib.Path('+repr(str(phase))+').write_text(json.dumps({"phase_id":1})); time.sleep(60)']
    result=runtime().run_process(command,timeout_s=5,case_timeout_s=0.2,phase_file=phase,log_dir=tmp_path)
    assert result['status']=='timeout'
    assert result['wall_s']<3
    assert result['phase_observations'][0]['phase_id']==1


def test_runtime_identity_changes_when_owned_executable_is_replaced(tmp_path):
    exe=tmp_path/'python.exe';exe.write_bytes(b'first executable')
    first=runtime().runtime_identity(exe)
    exe.write_bytes(b'changed executable')
    assert runtime().runtime_identity(exe)!=first
