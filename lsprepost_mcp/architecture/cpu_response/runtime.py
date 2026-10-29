"""Own one hidden child process and enforce budgets outside native solver calls."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PYTHON = ROOT / '.venv' / 'cpu-response' / 'python.exe'
RuntimeInfo = dict
CapabilityReport = dict


def runtime_identity(python_executable) -> dict:
    """Read-only replacement identity. No native imports or subprocess probes.

    Setup separately records downloaded archive/wheel SHA256 values. These file
    metadata detect interpreter/core/package changes at the same installation path.
    """
    exe=Path(python_executable).resolve();root=exe.parent;site=root/'Lib'/'site-packages'
    files={exe,*root.glob('python*.dll')}
    for package in ('openseespy','openseespywin'):
        directory=site/package
        if directory.is_dir():
            files.update(p for p in directory.rglob('*') if p.suffix.lower() in ('.py','.pyd','.dll'))
        files.update(site.glob(package+'-*.dist-info/METADATA'))
    identities=[]
    for path in sorted(files,key=str):
        stat=path.stat()
        identities.append(dict(path=str(path),size=stat.st_size,mtime_ns=stat.st_mtime_ns,ctime_ns=stat.st_ctime_ns))
    return dict(method='absolute_path_size_mtime_ctime_v1',files=identities)


def run_process(command: list[str], *, timeout_s: float, log_dir: Path,
                cancel: threading.Event | None = None, phase_file: Path | None = None,
                case_timeout_s: float | None = None) -> dict:
    """Run a server-built argv; no shell and no process-name based termination."""
    if not 0 < timeout_s <= 180:
        raise ValueError('worker timeout must be in (0, 180] seconds')
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for key in ('PYTHONHOME', 'PYTHONPATH'):
        env.pop(key, None)
    env.update(PYTHONNOUSERSITE='1', PYTHONUTF8='1', OPENBLAS_NUM_THREADS='1',
               OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
    start = time.monotonic()
    phase_start=start;phase_id=None;phase_observations=[]
    peak = 0
    status = 'failed'
    with (log_dir / 'stdout.log').open('w', encoding='utf8') as stdout, \
            (log_dir / 'stderr.log').open('w', encoding='utf8') as stderr:
        try:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stdout,
                                       stderr=stderr, stdin=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except OSError as exc:
            return dict(status='failed', returncode=None, reason=str(exc), wall_s=time.monotonic()-start)
        try:
            import psutil
            observed = psutil.Process(process.pid)
        except (ImportError, OSError):
            observed = None
        while process.poll() is None:
            if phase_file is not None and phase_file.is_file():
                try:
                    current=json.loads(phase_file.read_text(encoding='utf8'))['phase_id']
                    if current!=phase_id:
                        phase_id=current;phase_start=time.monotonic()
                        phase_observations.append(dict(phase_id=current,observed_elapsed_s=phase_start-start))
                except (OSError,ValueError,KeyError):
                    pass
            if observed is not None:
                try:
                    peak = max(peak, observed.memory_info().rss)
                except (OSError, psutil.Error):
                    observed = None
            if cancel is not None and cancel.is_set():
                status = 'cancelled'
                break
            if time.monotonic() - start >= timeout_s or (case_timeout_s is not None and time.monotonic()-phase_start>=case_timeout_s):
                status = 'timeout'
                break
            time.sleep(0.02)
        cleanup_start = time.monotonic()
        if process.poll() is None:
            # TerminateProcess on Windows; on POSIX allow a short grace then kill.
            process.terminate()
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        else:
            if status not in ('cancelled','timeout'):
                status = 'completed' if process.returncode == 0 else 'failed'
        return dict(status=status, returncode=process.returncode,
                    wall_s=time.monotonic()-start, cleanup_s=time.monotonic()-cleanup_start,
                    peak_rss_bytes=peak, rss_sample_interval_s=0.02,phase_observations=phase_observations,
                    phase_observation_interval_s=0.02)


def inspect_runtime(python_executable: str) -> RuntimeInfo:
    path = Path(python_executable)
    if not path.is_file():
        return dict(available=False, reason='CPU interpreter is not installed', executable=str(path))
    # This explicit check is not called by a GET route.
    command = [str(path), '-c',
               'import sys,json,importlib.metadata as m; '
               'import openseespy.opensees as ops; '
               'print(json.dumps(dict(python=sys.version,solver=ops.version(),'
               'package=m.version("openseespy"),executable=sys.executable)))']
    try:
        run = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=15,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if run.returncode:
            return dict(available=False, reason=run.stderr.decode('utf8', 'replace')[-2000:], executable=str(path))
        value = json.loads(run.stdout.decode('utf8').strip().splitlines()[-1])
        return dict(value, available=True, platform=platform.platform())
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return dict(available=False, reason=str(exc), executable=str(path))


def probe_backend() -> CapabilityReport:
    """Executed explicitly inside the optional worker, never during HTTP GET."""
    try:
        from .native_probes import probe
        return probe()
    except (ImportError, OSError, RuntimeError, AssertionError) as exc:
        return dict(available=False, reason=str(exc), verified=False)
