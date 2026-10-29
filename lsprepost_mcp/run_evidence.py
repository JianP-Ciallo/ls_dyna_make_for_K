from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import JSONDict


EVIDENCE_MANIFEST_NAME = "evidence_manifest.json"
EVIDENCE_SCHEMA_VERSION = 1
RUN_IDENTITY_FIELDS = (
    "run_id",
    "status",
    "returncode",
    "ok",
    "input_sha256",
    "model_json_sha256",
    "evidence_manifest_sha256",
)
_EXACT_EVIDENCE_NAMES = {"model.k", "model.json"}
_EVIDENCE_PREFIXES = ("d3hsp", "dbfsi", "nodout", "d3plot")
_SELECTED_EVIDENCE_PREFIXES = (*_EVIDENCE_PREFIXES, "elout")
_SUPPORTED_EVIDENCE_PREFIXES = (*_SELECTED_EVIDENCE_PREFIXES, "matsum")
_OPTIONAL_EVIDENCE_PREFIXES = ("glstat",)


def seal_phase14_run_evidence(
    run_dir: Path,
    *,
    required_output_prefixes: tuple[str, ...] | list[str] | None = None,
) -> JSONDict:
    run_dir = run_dir.resolve()
    required_prefixes = _normalize_required_prefixes(required_output_prefixes)
    files = _selected_evidence_files(run_dir, required_prefixes)
    entries = [_file_entry(path) for path in files]
    present_names = {str(item["name"]).lower() for item in entries}
    missing = [
        requirement
        for requirement in ("model.k", "model.json", *required_prefixes)
        if not _requirement_present(requirement, present_names)
    ]
    manifest: JSONDict = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
        "required_output_prefixes": list(required_prefixes),
        "files": entries,
        "missing_required_files": missing,
    }
    manifest_path = run_dir / EVIDENCE_MANIFEST_NAME
    _write_json_atomic(manifest_path, manifest)
    return {
        "path": EVIDENCE_MANIFEST_NAME,
        "sha256": _sha256(manifest_path),
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "file_count": len(entries),
    }


def validate_phase14_run_evidence(
    run_dir: Path,
    reference: Any,
    *,
    required_output_prefixes: tuple[str, ...] | list[str] | None = None,
) -> JSONDict:
    run_dir = run_dir.resolve()
    result: JSONDict = {
        "ok": False,
        "reason": "invalid_evidence",
        "mismatched_files": [],
        "missing_files": [],
        "unexpected_files": [],
    }
    if not isinstance(reference, dict):
        result["reason"] = "evidence_manifest_reference_missing"
        return result
    relative_path = reference.get("path")
    expected_sha256 = reference.get("sha256")
    if (
        relative_path != EVIDENCE_MANIFEST_NAME
        or not isinstance(expected_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
    ):
        result["reason"] = "evidence_manifest_reference_missing"
        return result

    manifest_path = (run_dir / relative_path).resolve()
    if manifest_path.parent != run_dir or not manifest_path.is_file():
        result["reason"] = "evidence_manifest_missing"
        return result
    actual_manifest_sha256 = _sha256(manifest_path)
    result["manifest_sha256"] = actual_manifest_sha256
    if actual_manifest_sha256 != expected_sha256:
        result["reason"] = "evidence_manifest_hash_mismatch"
        return result

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        result["reason"] = "evidence_manifest_unreadable"
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != EVIDENCE_SCHEMA_VERSION
        or not isinstance(manifest.get("files"), list)
    ):
        result["reason"] = "evidence_manifest_schema_invalid"
        return result
    try:
        expected_required = _normalize_required_prefixes(required_output_prefixes)
        manifest_required_raw = manifest.get("required_output_prefixes")
        manifest_required = (
            _normalize_required_prefixes(manifest_required_raw)
            if manifest_required_raw is not None
            else _EVIDENCE_PREFIXES
        )
    except (TypeError, ValueError):
        result["reason"] = "evidence_manifest_schema_invalid"
        return result
    if required_output_prefixes is not None and manifest_required != expected_required:
        result["reason"] = "evidence_required_outputs_mismatch"
        result["expected_required_outputs"] = list(expected_required)
        result["manifest_required_outputs"] = list(manifest_required)
        return result

    expected_entries: dict[str, JSONDict] = {}
    for item in manifest["files"]:
        if not isinstance(item, dict):
            result["reason"] = "evidence_manifest_schema_invalid"
            return result
        name = item.get("name")
        size = item.get("size_bytes")
        digest = item.get("sha256")
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or name in expected_entries
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            result["reason"] = "evidence_manifest_schema_invalid"
            return result
        expected_entries[name] = item

    current_files = {
        path.name: path
        for path in _selected_evidence_files(run_dir, manifest_required)
    }
    expected_names = set(expected_entries)
    current_names = set(current_files)
    result["missing_files"] = sorted(expected_names - current_names)
    result["unexpected_files"] = sorted(current_names - expected_names)
    mismatched: list[str] = []
    for name in sorted(expected_names & current_names):
        path = current_files[name]
        expected = expected_entries[name]
        if (
            path.stat().st_size != expected["size_bytes"]
            or _sha256(path) != expected["sha256"]
        ):
            mismatched.append(name)
    result["mismatched_files"] = mismatched

    present_names = {name.lower() for name in current_names}
    missing_required = [
        requirement
        for requirement in ("model.k", "model.json", *manifest_required)
        if not _requirement_present(requirement, present_names)
    ]
    result["missing_required_files"] = missing_required
    result["file_count"] = len(current_files)
    result["ok"] = not any(
        (
            result["missing_files"],
            result["unexpected_files"],
            result["mismatched_files"],
            missing_required,
        )
    )
    result["reason"] = "verified" if result["ok"] else "evidence_files_changed"
    return result


def validate_run_record_identity(
    latest_record: Any,
    run_record: Any,
) -> JSONDict:
    if not isinstance(latest_record, dict) or not isinstance(run_record, dict):
        return {
            "ok": False,
            "reason": "run_record_unreadable",
            "mismatched_fields": list(RUN_IDENTITY_FIELDS),
        }
    mismatched = [
        field
        for field in RUN_IDENTITY_FIELDS
        if latest_record.get(field) != run_record.get(field)
    ]
    latest_solver_ok = _nested_bool(latest_record, "solver_evaluation", "ok")
    run_solver_ok = _nested_bool(run_record, "solver_evaluation", "ok")
    if latest_solver_ok != run_solver_ok:
        mismatched.append("solver_evaluation.ok")
    return {
        "ok": not mismatched,
        "reason": "verified" if not mismatched else "run_record_identity_mismatch",
        "mismatched_fields": mismatched,
    }


def _selected_evidence_files(
    run_dir: Path,
    required_prefixes: tuple[str, ...] = (),
) -> list[Path]:
    if not run_dir.is_dir():
        return []
    selected: list[Path] = []
    for path in run_dir.iterdir():
        lower = path.name.lower()
        if not path.is_file():
            continue
        if lower in _EXACT_EVIDENCE_NAMES or any(
            lower.startswith(prefix)
            for prefix in (
                *_SELECTED_EVIDENCE_PREFIXES,
                *required_prefixes,
                *_OPTIONAL_EVIDENCE_PREFIXES,
            )
        ):
            selected.append(path)
    return sorted(selected, key=lambda path: path.name.lower())


def _requirement_present(requirement: str, names: set[str]) -> bool:
    if requirement in _EXACT_EVIDENCE_NAMES:
        return requirement in names
    return any(name.startswith(requirement) for name in names)


def _normalize_required_prefixes(
    prefixes: tuple[str, ...] | list[str] | None,
) -> tuple[str, ...]:
    if prefixes is None:
        return _EVIDENCE_PREFIXES
    if not isinstance(prefixes, (tuple, list)):
        raise TypeError("required_output_prefixes must be a list or tuple")
    normalized: list[str] = []
    for value in prefixes:
        if (
            not isinstance(value, str)
            or not re.fullmatch(r"[a-z0-9_]+", value)
            or value not in _SUPPORTED_EVIDENCE_PREFIXES
        ):
            raise ValueError(f"unsupported evidence output prefix: {value!r}")
        if value not in normalized:
            normalized.append(value)
    if not normalized:
        raise ValueError("required_output_prefixes must not be empty")
    return tuple(normalized)


def _file_entry(path: Path) -> JSONDict:
    return {
        "name": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _nested_bool(value: JSONDict, outer: str, inner: str) -> bool | None:
    nested = value.get(outer)
    return nested.get(inner) if isinstance(nested, dict) and isinstance(nested.get(inner), bool) else None


def _write_json_atomic(path: Path, data: JSONDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
