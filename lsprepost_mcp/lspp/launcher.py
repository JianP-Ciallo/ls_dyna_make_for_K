from __future__ import annotations

import csv
import shutil
import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..artifacts import artifacts_dir
from ..cfile import file_sha256, validate_server_cfile_path
from ..config import JSONDict, lspp_exe
from ..locks import ProjectLock
from ..run_evidence import validate_phase14_run_evidence

ALLOWED_KEYWORD_SUFFIXES = {".k", ".key", ".dyn"}
PROCESS_RECORD_LIMIT = 200
WEAK_IDENTITY_BLOCK_TTL_S = 5 * 60
CFILE_SNAPSHOT_LIMIT = 50
GUI_STARTUP_GRACE_S = 1.0

@dataclass(frozen=True)
class LsppDoctor:
    exe: str
    exists: bool
    is_file: bool
    suffix_ok: bool
    name_ok: bool
    ok: bool

    def to_json(self) -> JSONDict:
        return {
            "exe": self.exe,
            "exists": self.exists,
            "is_file": self.is_file,
            "suffix_ok": self.suffix_ok,
            "name_ok": self.name_ok,
            "ok": self.ok,
        }


def doctor_lsprepost_exe(exe: Path | None = None) -> LsppDoctor:
    path = exe or lspp_exe()
    exists = path.exists()
    is_file = path.is_file() if exists else False
    suffix_ok = path.suffix.lower() == ".exe"
    name_ok = path.name.lower().startswith("lsprepost")
    return LsppDoctor(str(path), exists, is_file, suffix_ok, name_ok, exists and is_file and suffix_ok and name_ok)


def require_lsprepost_exe(exe: Path | None = None) -> Path:
    path = exe or lspp_exe()
    doctor = doctor_lsprepost_exe(path)
    if not doctor.ok:
        raise FileNotFoundError(f"invalid LS-PrePost executable: {doctor.to_json()}")
    return path


def launch_keyword(project_path: Path, keyword_path: Path, timeout_s: float | None = None, allow_multiple: bool = False) -> JSONDict:
    exe = require_lsprepost_exe()
    project_path = project_path.resolve()
    keyword_path = validate_keyword_path(project_path, keyword_path)
    with ProjectLock(project_path.name):
        return launch_lsprepost_command(
            project_path,
            [str(exe), f"k={keyword_path}"],
            "keyword_preview",
            timeout_s=timeout_s,
            allow_multiple=allow_multiple,
            extra_record={"keyword_path": str(keyword_path)},
        )


def launch_cfile(project_path: Path, cfile_path: Path, timeout_s: float | None = None, allow_multiple: bool = False) -> JSONDict:
    exe = require_lsprepost_exe()
    project_path = project_path.resolve()
    cfile_path = validate_server_cfile_path(project_path, cfile_path)
    with ProjectLock(project_path.name):
        with ProjectLock(project_path.name, namespace="runtime"):
            cfile_path = validate_server_cfile_path(project_path, cfile_path)
            snapshot = cfile_snapshot_path(project_path, cfile_path)
            shutil.copyfile(cfile_path, snapshot)
            cleanup_cfile_snapshots(project_path)
            return launch_lsprepost_command(
                project_path,
                [str(exe), f"c={snapshot}"],
                "cfile",
                timeout_s=timeout_s,
                allow_multiple=allow_multiple,
                extra_record={
                    "cfile_path": str(cfile_path),
                    "cfile_sha256": file_sha256(cfile_path),
                    "cfile_snapshot_path": str(snapshot),
                    "cfile_snapshot_sha256": file_sha256(snapshot),
                },
                runtime_lock_held=True,
            )


def launch_d3plot(
    project_path: Path,
    d3plot_path: Path,
    timeout_s: float | None = None,
) -> JSONDict:
    exe = require_lsprepost_exe()
    project_path = project_path.resolve()
    with ProjectLock(project_path.name):
        d3plot_path = validate_d3plot_path(project_path, d3plot_path)
        run_dir = d3plot_path.parent
        record = _read_json_object(run_dir / "run.json")
        evidence = record["evidence_manifest"]
        return launch_lsprepost_command(
            project_path,
            [str(exe), str(d3plot_path)],
            "d3plot_result",
            timeout_s=timeout_s,
            allow_multiple=False,
            extra_record={
                "d3plot_path": str(d3plot_path),
                "d3plot_sha256": file_sha256(d3plot_path),
                "run_id": run_dir.name,
                "evidence_manifest_sha256": evidence["sha256"],
            },
        )


def launch_lsprepost_command(
    project_path: Path,
    command: list[str],
    mode: str,
    timeout_s: float | None = None,
    allow_multiple: bool = False,
    extra_record: JSONDict | None = None,
    runtime_lock_held: bool = False,
) -> JSONDict:
    exe = Path(command[0])
    if runtime_lock_held:
        return _launch_lsprepost_command_locked(project_path, command, exe, mode, timeout_s, allow_multiple, extra_record)
    with ProjectLock(project_path.name, namespace="runtime"):
        return _launch_lsprepost_command_locked(project_path, command, exe, mode, timeout_s, allow_multiple, extra_record)


def _launch_lsprepost_command_locked(
    project_path: Path,
    command: list[str],
    exe: Path,
    mode: str,
    timeout_s: float | None,
    allow_multiple: bool,
    extra_record: JSONDict | None,
) -> JSONDict:
    running = running_project_processes(project_path)
    if running and not allow_multiple:
        raise RuntimeError(f"LS-PrePost already appears to be running for this project: {running}")
    proc = subprocess.Popen(
        command,
        cwd=str(project_path),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    record = {
        "pid": proc.pid,
        "exe": str(exe),
        "exe_name": exe.name,
        "cwd": str(project_path),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
    }
    record.update(extra_record or {})
    process = process_info(proc.pid)
    if process:
        record.update(process_record_fields(process))

    if timeout_s is None and mode in {"keyword_preview", "d3plot_result"}:
        try:
            proc.wait(timeout=GUI_STARTUP_GRACE_S)
        except subprocess.TimeoutExpired:
            record["status"] = "started"
            record["process_running"] = True
            record_process(project_path, record)
            return record
        record["returncode"] = proc.returncode
        record["status"] = "exited_during_startup"
        record["process_running"] = False
        record_process(project_path, record)
        raise RuntimeError(
            f"LS-PrePost exited during startup with return code {proc.returncode}"
        )

    record_process(project_path, record)
    if timeout_s is not None and timeout_s > 0:
        try:
            proc.wait(timeout=timeout_s)
            record["returncode"] = proc.returncode
            record_process(project_path, record)
        except subprocess.TimeoutExpired:
            if terminate_process_tree(proc.pid):
                record["terminated_after_timeout_s"] = timeout_s
            else:
                record["termination_failed"] = True
                record["termination_timeout_s"] = timeout_s
            record_process(project_path, record)
            raise TimeoutError(f"LS-PrePost launch timed out after {timeout_s} seconds")
    return record


def cfile_snapshot_path(project_path: Path, cfile_path: Path) -> Path:
    snapshots = artifacts_dir(project_path) / "cfile_snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return snapshots / f"{cfile_path.stem}_{timestamp}.cfile"


def cleanup_cfile_snapshots(project_path: Path, keep: int = CFILE_SNAPSHOT_LIMIT) -> None:
    snapshots = artifacts_dir(project_path) / "cfile_snapshots"
    if not snapshots.exists():
        return
    files = sorted(
        (item for item in snapshots.glob("*.cfile") if item.is_file()),
        key=lambda item: item.stat().st_mtime,
    )
    protected = active_cfile_snapshot_paths(project_path)
    candidates = [item for item in files if item.resolve() not in protected]
    for stale in candidates[:-keep]:
        try:
            stale.unlink()
        except OSError:
            pass


def active_cfile_snapshot_paths(project_path: Path) -> set[Path]:
    records_path = artifacts_dir(project_path) / "lspp_processes.jsonl"
    protected: set[Path] = set()
    for record in read_process_records(records_path):
        if not is_active_record(record):
            continue
        snapshot = str(record.get("cfile_snapshot_path") or "")
        if not snapshot:
            continue
        try:
            protected.add(Path(snapshot).resolve())
        except OSError:
            continue
    return protected


def validate_keyword_path(project_path: Path, keyword_path: Path) -> Path:
    project = project_path.resolve()
    keyword = keyword_path.resolve()
    artifacts = (project / "artifacts").resolve()
    if not keyword.exists():
        raise FileNotFoundError(f"keyword file not found: {keyword}")
    if not keyword.is_file():
        raise ValueError(f"keyword path must be a file: {keyword}")
    if keyword.suffix.lower() not in ALLOWED_KEYWORD_SUFFIXES:
        raise ValueError(f"keyword file suffix must be one of {', '.join(sorted(ALLOWED_KEYWORD_SUFFIXES))}")
    if keyword == project / "model.k":
        return keyword
    if keyword.parent == artifacts:
        return keyword
    raise ValueError("keyword path must be the project model.k or a project artifact keyword file")


def validate_d3plot_path(project_path: Path, d3plot_path: Path) -> Path:
    project = Path(project_path).resolve()
    result = Path(d3plot_path).resolve()
    runs_dir = (project / "solver_runs").resolve()
    if runs_dir.parent != project:
        raise ValueError("solver_runs must remain inside the project")
    if not result.exists():
        raise FileNotFoundError(f"d3plot result not found: {result}")
    if not result.is_file():
        raise ValueError(f"d3plot path must be a file: {result}")
    if result.name.lower() != "d3plot":
        raise ValueError("result path must reference the base d3plot file")
    if result.stat().st_size <= 0:
        raise ValueError("d3plot result must be non-empty")
    run_dir = result.parent
    if run_dir.parent != runs_dir:
        raise ValueError("d3plot must be inside project/solver_runs/<run_id>")

    record = _read_json_object(run_dir / "run.json")
    if (
        record.get("run_id") != run_dir.name
        or record.get("status") != "completed"
        or record.get("ok") is not True
    ):
        raise ValueError("d3plot run is not a completed qualified run")
    for name, field in (
        ("model.k", "input_sha256"),
        ("model.json", "model_json_sha256"),
    ):
        source = run_dir / name
        expected = record.get(field)
        if (
            not source.is_file()
            or not isinstance(expected, str)
            or file_sha256(source) != expected
        ):
            raise ValueError(f"d3plot run input evidence changed: {name}")
    evidence = record.get("evidence_manifest")
    if (
        not isinstance(evidence, dict)
        or record.get("evidence_manifest_sha256") != evidence.get("sha256")
    ):
        raise ValueError("d3plot evidence manifest reference is invalid")
    required_outputs = record.get("required_outputs")
    validation = validate_phase14_run_evidence(
        run_dir,
        evidence,
        required_output_prefixes=(
            required_outputs if isinstance(required_outputs, list) else None
        ),
    )
    if validation.get("ok") is not True:
        raise ValueError(f"d3plot evidence validation failed: {validation}")
    return result


def _read_json_object(path: Path) -> JSONDict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"run record is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"run record must be a JSON object: {path}")
    return value


def record_process(project_path: Path, record: JSONDict) -> None:
    with ProjectLock(project_path.name, namespace="process_records"):
        path = artifacts_dir(project_path) / "lspp_processes.jsonl"
        records = read_process_records(path)
        records.append(record)
        records = compact_process_records(records)
        with path.open("w", encoding="utf-8") as handle:
            for item in records:
                handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


def running_project_processes(project_path: Path, fail_closed: bool = False) -> list[JSONDict]:
    path = artifacts_dir(project_path) / "lspp_processes.jsonl"
    if not path.exists():
        return []
    running: list[JSONDict] = []
    for record in read_process_records(path):
        if "returncode" in record or "terminated_after_timeout_s" in record:
            continue
        pid = int(record.get("pid", 0) or 0)
        if pid > 0 and process_matches_record(pid, record, fail_closed=fail_closed):
            running.append(record)
    return running


def read_process_records(path: Path) -> list[JSONDict]:
    if not path.exists():
        return []
    records: list[JSONDict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def compact_process_records(records: list[JSONDict], limit: int = PROCESS_RECORD_LIMIT) -> list[JSONDict]:
    if len(records) <= limit:
        return records
    active = [record for record in records if is_active_record(record)]
    finished = [record for record in records if not is_active_record(record)]
    remaining = max(0, limit - len(active))
    return [*active, *finished[-remaining:]]


def is_active_record(record: JSONDict) -> bool:
    return "returncode" not in record and "terminated_after_timeout_s" not in record


def process_matches_record(pid: int, record: JSONDict, fail_closed: bool = False) -> bool:
    info = process_info(pid)
    if info is None:
        return False
    if not fail_closed and record_identity_is_weak(record) and record_age_s(record) > WEAK_IDENTITY_BLOCK_TTL_S:
        return False
    recorded_name = str(record.get("exe_name") or Path(str(record.get("exe", ""))).name).lower()
    image_name = str(info.get("image_name", "")).lower()
    if recorded_name and image_name != recorded_name:
        return False

    if info.get("identity_source") == "tasklist":
        return bool(recorded_name)

    recorded_creation = str(record.get("process_creation_date", "") or "")
    current_creation = str(info.get("creation_date", "") or "")
    if recorded_creation:
        if not current_creation:
            return False
        if current_creation != recorded_creation:
            return False

    recorded_exe = normalize_path_for_compare(str(record.get("process_executable_path") or record.get("exe") or ""))
    current_exe = normalize_path_for_compare(str(info.get("executable_path") or ""))
    if recorded_exe:
        if not current_exe:
            return False
        if current_exe != recorded_exe:
            return False

    command_line = str(info.get("command_line") or "")
    keyword_path = str(record.get("keyword_path") or "")
    if keyword_path:
        if not command_line:
            return False
        if normalize_for_commandline(keyword_path) not in normalize_for_commandline(command_line):
            return False

    if recorded_name:
        return True
    return image_name.startswith("lsprepost")


def is_process_running(pid: int) -> bool:
    return process_info(pid) is not None


def process_info(pid: int) -> JSONDict | None:
    if os.name == "nt":
        cim = windows_process_info(pid)
        if cim is not None:
            return cim
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = result.stdout.strip()
    for row in csv.reader(line for line in output.splitlines() if line.strip()):
        if len(row) >= 2 and row[1].strip().isdigit() and int(row[1].strip()) == pid:
            return {"image_name": row[0].strip(), "pid": pid, "identity_source": "tasklist"}
    return None


def windows_process_info(pid: int) -> JSONDict | None:
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            f"Get-CimInstance Win32_Process -Filter \"ProcessId = {pid}\" | "
            "Select-Object ProcessId,Name,ExecutablePath,CommandLine,CreationDate | "
            "ConvertTo-Json -Compress"
        ),
    ]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = result.stdout.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict):
        return None
    process_id = int(data.get("ProcessId", 0) or 0)
    if process_id != pid:
        return None
    return {
        "pid": pid,
        "image_name": str(data.get("Name") or ""),
        "executable_path": str(data.get("ExecutablePath") or ""),
        "command_line": str(data.get("CommandLine") or ""),
        "creation_date": str(data.get("CreationDate") or ""),
        "identity_source": "cim",
    }


def process_record_fields(info: JSONDict) -> JSONDict:
    has_strong_identity = all(info.get(key) for key in ["creation_date", "executable_path", "command_line"])
    return {
        "process_creation_date": info.get("creation_date", ""),
        "process_executable_path": info.get("executable_path", ""),
        "process_command_line": info.get("command_line", ""),
        "process_identity_source": info.get("identity_source", ""),
        "process_identity_confidence": "strong" if has_strong_identity else "weak",
        "runtime_identity_incomplete": not has_strong_identity,
    }


def record_age_s(record: JSONDict) -> float:
    started_at = str(record.get("started_at") or "")
    if not started_at:
        return WEAK_IDENTITY_BLOCK_TTL_S + 1
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return WEAK_IDENTITY_BLOCK_TTL_S + 1
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - started).total_seconds())


def record_identity_is_weak(record: JSONDict) -> bool:
    return (
        record.get("runtime_identity_incomplete") is True
        or record.get("process_identity_confidence") == "weak"
        or not all(record.get(key) for key in ["process_creation_date", "process_executable_path", "process_command_line"])
    )


def normalize_path_for_compare(path: str) -> str:
    if not path:
        return ""
    try:
        return str(Path(path).resolve()).casefold()
    except OSError:
        return path.casefold()


def normalize_for_commandline(text: str) -> str:
    return text.replace('"', "").casefold()


def terminate_process_tree(pid: int) -> bool:
    try:
        primary = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    if primary.returncode != 0:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return False
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not is_process_running(pid):
            return True
        time.sleep(0.1)
    return not is_process_running(pid)
