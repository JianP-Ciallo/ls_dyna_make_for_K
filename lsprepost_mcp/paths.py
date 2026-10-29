from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .config import ARCHIVE_PROJECTS_DIR, LEGACY_PROJECTS_DIR, PROJECTS_DIR


def safe_project_name(name: str) -> str:
    raw = str(name)
    stripped = raw.strip()
    if raw != stripped:
        raise ValueError("project_name must not have leading or trailing whitespace")
    if stripped.endswith("."):
        raise ValueError("project_name must not end with a dot")
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stripped)
    if not cleaned:
        raise ValueError("project_name must not be empty")
    if cleaned in {".", ".."}:
        raise ValueError("project_name is not allowed")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if cleaned.upper() in reserved:
        raise ValueError("project_name is a reserved Windows device name")
    return cleaned


def checked_child(base: Path, name: str) -> Path:
    safe = safe_project_name(name)
    path = (base / safe).resolve()
    root = base.resolve()
    if root != path and root not in path.parents:
        raise ValueError("project path escaped workspace")
    return path


def project_dir(name: str) -> Path:
    return checked_child(PROJECTS_DIR, name)


def archive_project_dir(name: str) -> Path:
    return checked_child(ARCHIVE_PROJECTS_DIR, name)


def legacy_project_dir(name: str) -> Path:
    return checked_child(LEGACY_PROJECTS_DIR, name)


def find_project_dir(name: str) -> Path:
    active = project_dir(name)
    if active.exists():
        return active
    legacy = legacy_project_dir(name)
    if legacy.exists():
        return legacy
    archived = archive_project_dir(name)
    if archived.exists():
        return archived
    return active


def iso_mtime(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
