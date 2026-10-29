from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import uuid
from pathlib import Path

from .config import WORKSPACE_DIR
from .paths import safe_project_name


LOCKS_DIR = WORKSPACE_DIR / "locks"
LOCK_EVENTS_PATH = LOCKS_DIR / "lock_events.jsonl"
DEFAULT_STALE_AFTER_S = 30 * 60
INVALID_METADATA_GRACE_S = 5.0


class ProjectLock:
    def __init__(
        self,
        project_name: str,
        timeout_s: float = 10.0,
        poll_s: float = 0.05,
        stale_after_s: float = DEFAULT_STALE_AFTER_S,
        namespace: str = "project",
    ) -> None:
        self.project_name = safe_project_name(project_name)
        self.namespace = safe_project_name(namespace)
        self.timeout_s = timeout_s
        self.poll_s = poll_s
        self.stale_after_s = stale_after_s
        self.path = LOCKS_DIR / self.namespace / f"{self.project_name}.lock"
        self._fd: int | None = None
        self._token = uuid.uuid4().hex
        self.diagnostics: list[dict[str, object]] = []

    def __enter__(self) -> "ProjectLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_s
        while True:
            try:
                self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, json.dumps(lock_payload(self._token), sort_keys=True).encode("utf-8"))
                return self
            except FileExistsError:
                if self._try_take_stale_lock():
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"project is locked: {self.project_name}")
                time.sleep(self.poll_s)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        deadline = time.monotonic() + max(0.25, min(self.timeout_s, 2.0))
        while True:
            payload = read_lock_payload(self.path)
            if payload.get("token") != self._token:
                return
            try:
                self.path.unlink()
                return
            except FileNotFoundError:
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(min(self.poll_s, 0.05))

    def _try_take_stale_lock(self) -> bool:
        original_signature = lock_file_signature(self.path)
        stale, reason, payload = is_stale_lock(self.path, self.stale_after_s)
        if not stale:
            return False
        event = {
            "event": "stale_project_lock_reclaimed",
            "project_name": self.project_name,
            "lock_path": str(self.path),
            "reason": reason,
            "previous_lock": payload,
            "reclaimed_at": time.time(),
            "reclaimed_by": lock_payload(self._token),
        }
        try:
            if lock_file_signature(self.path) != original_signature:
                event["event"] = "stale_project_lock_reclaim_skipped"
                event["reason"] = "lock changed before reclaim"
                self.diagnostics.append(event)
                write_lock_event(event)
                return False
            self.path.unlink()
            self.diagnostics.append(event)
            write_lock_event(event)
            return True
        except FileNotFoundError:
            return True
        except OSError as exc:
            event["event"] = "stale_project_lock_reclaim_failed"
            event["error"] = str(exc)
            self.diagnostics.append(event)
            write_lock_event(event)
            return False


def lock_payload(token: str | None = None) -> dict[str, object]:
    return {
        "pid": os.getpid(),
        "created_at": time.time(),
        "hostname": socket.gethostname(),
        "token": token or uuid.uuid4().hex,
    }


def read_lock_payload(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def lock_file_signature(path: Path) -> tuple[int, int, bytes] | None:
    try:
        stat = path.stat()
        data = path.read_bytes()
        return stat.st_mtime_ns, stat.st_size, data
    except OSError:
        return None


def is_stale_lock(path: Path, stale_after_s: float = DEFAULT_STALE_AFTER_S) -> tuple[bool, str, dict[str, object]]:
    payload = read_lock_payload(path)
    created_at = float(payload.get("created_at", 0) or 0)
    age_s = time.time() - created_at if created_at > 0 else stale_after_s + 1
    pid = int(payload.get("pid", 0) or 0)
    hostname = str(payload.get("hostname", "") or "")
    current_hostname = socket.gethostname()
    if created_at <= 0:
        file_age_s = lock_file_age_s(path)
        if file_age_s > INVALID_METADATA_GRACE_S:
            return True, "lock metadata is missing or invalid", payload
        return False, "lock metadata is invalid but still within grace period", payload
    if pid <= 0:
        if age_s > INVALID_METADATA_GRACE_S:
            return True, "lock pid is missing or invalid", payload
        return False, "lock pid is invalid but still within grace period", payload
    if hostname and hostname != current_hostname:
        if age_s > stale_after_s:
            return True, "lock hostname differs and owner cannot be verified locally", payload
        return False, "lock hostname differs and is still within stale threshold", payload
    if age_s > stale_after_s:
        if is_pid_alive(pid):
            return False, "lock is old but owner pid is still running", payload
        return True, "lock owner pid is not running", payload
    if not is_pid_alive(pid):
        return True, "lock owner pid is not running", payload
    return False, "", payload


def lock_file_age_s(path: Path) -> float:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return INVALID_METADATA_GRACE_S + 1


def is_pid_alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return tasklist_has_pid(result.stdout, pid)


def tasklist_has_pid(output: str, pid: int) -> bool:
    import csv

    for row in csv.reader(line for line in output.splitlines() if line.strip()):
        if len(row) >= 2 and row[1].strip().isdigit() and int(row[1].strip()) == pid:
            return True
    return False


def write_lock_event(event: dict[str, object]) -> None:
    try:
        LOCKS_DIR.mkdir(parents=True, exist_ok=True)
        with LOCK_EVENTS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        pass
