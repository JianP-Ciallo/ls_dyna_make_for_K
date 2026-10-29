from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from .config import ARCHIVE_PROJECTS_DIR, JSONDict, LEGACY_PROJECTS_DIR, MATERIALS_DIR, PROJECTS_DIR, ROOT, lspp_exe
from .lspp.launcher import doctor_lsprepost_exe


SOURCE_FILE_SUFFIXES = {".py", ".js", ".css", ".html"}


def _compute_source_fingerprint() -> str:
    digest = hashlib.sha256()
    package_dir = ROOT / "lsprepost_mcp"
    source_files = sorted(
        path
        for path in package_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SOURCE_FILE_SUFFIXES
    )
    for path in source_files:
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


SOURCE_FINGERPRINT = _compute_source_fingerprint()


def source_fingerprint() -> str:
    return SOURCE_FINGERPRINT


def tool_server_info(_: JSONDict) -> JSONDict:
    exe = lspp_exe()
    doctor = doctor_lsprepost_exe(exe).to_json()
    return {
        "name": "lsprepost-mcp",
        "version": "0.2.0",
        "source_fingerprint": source_fingerprint(),
        "process_id": os.getpid(),
        "python_executable": sys.executable,
        "workspace_root": str(ROOT),
        "projects_dir": str(PROJECTS_DIR),
        "legacy_projects_dir": str(LEGACY_PROJECTS_DIR),
        "archive_projects_dir": str(ARCHIVE_PROJECTS_DIR),
        "materials_dir": str(MATERIALS_DIR),
        "lspp_exe": str(exe),
        "lspp_exe_exists": exe.exists(),
        "lspp_doctor": doctor,
        "transport": "stdio-jsonrpc-newline",
    }
