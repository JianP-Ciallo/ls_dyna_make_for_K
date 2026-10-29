"""Trusted, project-owned selection of one completed refined-blast solver run."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from lsprepost_mcp.config import JSONDict
from lsprepost_mcp.refined_blast import store as store_module
from lsprepost_mcp.refined_blast.store import (
    RefinedBlastStore,
    validate_storage_identifier,
)
from lsprepost_mcp.run_evidence import validate_run_record_identity


ASSESSMENT_RESULT_SOURCE_SCHEMA_VERSION = (
    "lsprepost_mcp.damage_assessment_source@1"
)
_RECORD_NAME = "damage_assessment_source.json"
_TERMINAL_STATUSES = frozenset({"completed", "solver_failed", "timed_out"})
_RUN_ID_RE = re.compile(r"run_[A-Za-z0-9_]+")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_IDENTITY_KEYS = frozenset(
    {
        "scenario_id",
        "generated_revision",
        "artifact_fingerprint",
        "package_fingerprint",
    }
)
_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "project_id",
        "scenario_id",
        "generated_revision",
        "artifact_fingerprint",
        "package_fingerprint",
        "snapshot_relative_path",
        "run_id",
        "run_status",
        "model_sha256",
        "manifest_sha256",
        "semantics_sha256",
        "registered_at",
    }
)


def register_assessment_result_source(
    *,
    store: RefinedBlastStore,
    project_id: str,
    snapshot: Path,
    identity: Mapping[str, object],
    run_record: Mapping[str, object],
    semantic_format: str = "native",
) -> JSONDict:
    """Persist the exact terminal run selected by a server-owned action."""

    if not isinstance(store, RefinedBlastStore):
        raise TypeError("store must be a RefinedBlastStore")
    safe_project = validate_storage_identifier(project_id, "project_id")
    if semantic_format not in {"native", "legacy_deck_manifest"}:
        raise ValueError("unsupported assessment semantic format")
    normalized_identity = _validate_identity(identity)
    returned_status = run_record.get("status") if isinstance(run_record, Mapping) else None
    if returned_status not in _TERMINAL_STATUSES:
        raise ValueError("assessment source requires a terminal solver run")
    run_id = _run_id(run_record.get("run_id"))

    with store.project_transaction(safe_project):
        root = store._safe_root()
        project_dir = store._layout(safe_project, create=False)
        expected_generated = project_dir / "generated"
        snapshot_path = Path(os.path.abspath(snapshot))
        validate_storage_identifier(snapshot_path.name, "snapshot_name")
        if snapshot_path.parent != expected_generated:
            raise ValueError("assessment source snapshot is outside the owning project")
        _assert_safe_tree(project_dir, snapshot_path)
        store_module._assert_safe_directory(snapshot_path, root)

        runs_dir = snapshot_path / "solver_runs"
        _assert_safe_tree(project_dir, runs_dir)
        store_module._assert_safe_directory(runs_dir, root)
        latest = _read_store_json(runs_dir / "latest.json", store)
        if latest.get("run_id") != run_id:
            raise ValueError("assessment source returned/latest run identity mismatch")
        run_dir = runs_dir / run_id
        if run_dir.parent != runs_dir:
            raise ValueError("assessment source run escaped solver_runs")
        _assert_safe_tree(project_dir, run_dir)
        store_module._assert_safe_directory(run_dir, root)

        persisted_run = _read_store_json(run_dir / "run.json", store)
        if not validate_run_record_identity(latest, persisted_run).get("ok"):
            raise ValueError("assessment source latest/run identity mismatch")
        if not validate_run_record_identity(persisted_run, dict(run_record)).get("ok"):
            raise ValueError("assessment source returned/persisted run identity mismatch")
        if (
            persisted_run.get("run_id") != run_id
            or persisted_run.get("status") not in _TERMINAL_STATUSES
            or latest.get("status") not in _TERMINAL_STATUSES
        ):
            raise ValueError("assessment source requires matching terminal run records")

        hashes = _verified_source_hashes(snapshot_path, run_dir, persisted_run, store, semantic_format)
        relative_snapshot = snapshot_path.relative_to(project_dir).as_posix()
        record: JSONDict = {
            "schema_version": ASSESSMENT_RESULT_SOURCE_SCHEMA_VERSION,
            "project_id": safe_project,
            **normalized_identity,
            "snapshot_relative_path": relative_snapshot,
            "run_id": run_id,
            "run_status": str(persisted_run["status"]),
            **hashes,
            "registered_at": _utc_now(),
        }
        if semantic_format != "native":
            record["semantic_format"] = semantic_format
        store_module._atomic_write_json(
            project_dir / _RECORD_NAME,
            record,
            root=root,
            anchor=store._root_anchor,
        )
    return _public_record(record)


def resolve_assessment_result_source(project_dir: Path) -> dict[str, object]:
    """Resolve and revalidate one persisted source without trusting stored paths."""

    project = Path(os.path.abspath(project_dir))
    _assert_plain_directory(project, "assessment project")
    source_path = project / _RECORD_NAME
    _assert_plain_file(source_path, "assessment source record")
    raw = _read_json(source_path)
    record = _validate_record(raw, project.name)

    relative = _snapshot_relative(record["snapshot_relative_path"])
    snapshot = project.joinpath(*relative.parts)
    expected = project / "generated" / relative.parts[1]
    if snapshot != expected:
        raise ValueError("assessment source snapshot layout is invalid")
    _assert_safe_tree(project, snapshot)

    run_id = _run_id(record["run_id"])
    runs_dir = snapshot / "solver_runs"
    run_dir = runs_dir / run_id
    if run_dir.parent != runs_dir:
        raise ValueError("assessment source run escaped solver_runs")
    _assert_safe_tree(project, run_dir)

    latest = _read_json_checked(runs_dir / "latest.json", "latest run record")
    run = _read_json_checked(run_dir / "run.json", "run record")
    if not validate_run_record_identity(latest, run).get("ok"):
        raise ValueError("assessment source latest/run identity mismatch")
    if (
        latest.get("run_id") != run_id
        or run.get("run_id") != run_id
        or latest.get("status") != record["run_status"]
        or run.get("status") != record["run_status"]
        or record["run_status"] not in _TERMINAL_STATUSES
    ):
        raise ValueError("assessment source terminal run identity mismatch")

    semantic_format = str(record.get("semantic_format", "native"))
    current = _verified_source_hashes_plain(snapshot, run_dir, run, semantic_format)
    for name, digest in current.items():
        if record[name] != digest:
            raise ValueError(f"assessment source {name} hash mismatch")
    return {
        "record": record,
        "run_dir": run_dir,
        "semantic_manifest": (snapshot / "manifest.json" if semantic_format == "legacy_deck_manifest" else run_dir / "assessment_semantics.json"),
    }


def _verified_source_hashes(
    snapshot: Path,
    run_dir: Path,
    run: Mapping[str, object],
    store: RefinedBlastStore,
    semantic_format: str = "native",
) -> JSONDict:
    root = store._safe_root()
    names = ("model.k", "manifest.json", "assessment_semantics.json")
    if semantic_format == "legacy_deck_manifest":
        names = ("model.k", "manifest.json")
    snapshot_hashes: dict[str, str] = {}
    run_hashes: dict[str, str] = {}
    for name in names:
        snapshot_path = snapshot / name
        run_path = run_dir / name
        store_module._assert_safe_file(snapshot_path, root, missing_ok=False)
        store_module._assert_safe_file(run_path, root, missing_ok=False)
        snapshot_hashes[name] = hashlib.sha256(
            store_module._read_bytes_file(
                snapshot_path, root=root, anchor=store._root_anchor
            )
        ).hexdigest()
        run_hashes[name] = hashlib.sha256(
            store_module._read_bytes_file(
                run_path, root=root, anchor=store._root_anchor
            )
        ).hexdigest()
    return _compare_source_hashes(snapshot_hashes, run_hashes, run)


def _verified_source_hashes_plain(
    snapshot: Path, run_dir: Path, run: Mapping[str, object],
    semantic_format: str = "native",
) -> JSONDict:
    names = ("model.k", "manifest.json", "assessment_semantics.json")
    if semantic_format == "legacy_deck_manifest":
        names = ("model.k", "manifest.json")
    snapshot_hashes = {}
    run_hashes = {}
    for name in names:
        snapshot_path = snapshot / name
        run_path = run_dir / name
        _assert_plain_file(snapshot_path, f"snapshot {name}")
        _assert_plain_file(run_path, f"run {name}")
        snapshot_hashes[name] = _sha256(snapshot_path)
        run_hashes[name] = _sha256(run_path)
    return _compare_source_hashes(snapshot_hashes, run_hashes, run)


def _compare_source_hashes(
    snapshot_hashes: Mapping[str, str],
    run_hashes: Mapping[str, str],
    run: Mapping[str, object],
) -> JSONDict:
    for name in snapshot_hashes:
        if snapshot_hashes[name] != run_hashes[name]:
            raise ValueError(f"assessment source {name} snapshot/run hash mismatch")
    if run.get("input_sha256") != run_hashes["model.k"]:
        raise ValueError("assessment source model input hash mismatch")
    return {
        "model_sha256": run_hashes["model.k"],
        "manifest_sha256": run_hashes["manifest.json"],
        "semantics_sha256": run_hashes.get("assessment_semantics.json", run_hashes["manifest.json"]),
    }


def _validate_identity(identity: Mapping[str, object]) -> JSONDict:
    if not isinstance(identity, Mapping) or set(identity) != _IDENTITY_KEYS:
        raise ValueError("assessment source generated identity is invalid")
    scenario = validate_storage_identifier(identity["scenario_id"], "scenario_id")
    revision = identity["generated_revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("assessment source generated revision is invalid")
    artifact = _digest(identity["artifact_fingerprint"], "artifact_fingerprint")
    package = _digest(identity["package_fingerprint"], "package_fingerprint")
    return {
        "scenario_id": scenario,
        "generated_revision": revision,
        "artifact_fingerprint": artifact,
        "package_fingerprint": package,
    }


def _validate_record(value: object, project_name: str) -> JSONDict:
    if not isinstance(value, dict) or set(value) not in (_RECORD_KEYS, _RECORD_KEYS | {"semantic_format"}):
        raise ValueError("assessment source record schema is invalid")
    semantic_format = value.get("semantic_format", "native")
    if semantic_format not in {"native", "legacy_deck_manifest"}:
        raise ValueError("unsupported assessment semantic format")
    if value.get("schema_version") != ASSESSMENT_RESULT_SOURCE_SCHEMA_VERSION:
        raise ValueError("assessment source record schema version is unsupported")
    project_id = validate_storage_identifier(value.get("project_id"), "project_id")
    if project_id != project_name:
        raise ValueError("assessment source record belongs to another project")
    identity = _validate_identity({key: value[key] for key in _IDENTITY_KEYS})
    run_status = value.get("run_status")
    if run_status not in _TERMINAL_STATUSES:
        raise ValueError("assessment source record is not terminal")
    registered_at = value.get("registered_at")
    if not isinstance(registered_at, str) or not registered_at:
        raise ValueError("assessment source registration time is invalid")
    return {
        "schema_version": ASSESSMENT_RESULT_SOURCE_SCHEMA_VERSION,
        "project_id": project_id,
        **identity,
        **({"semantic_format": semantic_format} if "semantic_format" in value else {}),
        "snapshot_relative_path": _snapshot_relative(
            value.get("snapshot_relative_path")
        ).as_posix(),
        "run_id": _run_id(value.get("run_id")),
        "run_status": run_status,
        "model_sha256": _digest(value.get("model_sha256"), "model_sha256"),
        "manifest_sha256": _digest(value.get("manifest_sha256"), "manifest_sha256"),
        "semantics_sha256": _digest(value.get("semantics_sha256"), "semantics_sha256"),
        "registered_at": registered_at,
    }


def _snapshot_relative(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("assessment source snapshot path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or len(path.parts) != 2 or path.parts[0] != "generated":
        raise ValueError("assessment source snapshot path is invalid")
    validate_storage_identifier(path.parts[1], "snapshot_name")
    return path


def _public_record(record: Mapping[str, object]) -> JSONDict:
    return {
        "schema_version": record["schema_version"],
        "registered": True,
        "run_id": record["run_id"],
        "run_status": record["run_status"],
        "scenario_id": record["scenario_id"],
        "generated_revision": record["generated_revision"],
        "artifact_fingerprint": record["artifact_fingerprint"],
        "package_fingerprint": record["package_fingerprint"],
        "model_sha256": record["model_sha256"],
        "manifest_sha256": record["manifest_sha256"],
        "semantics_sha256": record["semantics_sha256"],
    }


def _read_store_json(path: Path, store: RefinedBlastStore) -> JSONDict:
    text = store_module._read_text_file(
        path, root=store._safe_root(), anchor=store._root_anchor
    )
    return _json_object(text)


def _read_json_checked(path: Path, label: str) -> JSONDict:
    _assert_plain_file(path, label)
    return _read_json(path)


def _read_json(path: Path) -> JSONDict:
    return _json_object(path.read_text(encoding="utf-8"))


def _json_object(text: str) -> JSONDict:
    value = json.loads(text, object_pairs_hook=store_module._reject_duplicate_json_keys)
    if not isinstance(value, dict):
        raise ValueError("assessment source JSON must be an object")
    return value


def _assert_safe_tree(root: Path, target: Path) -> None:
    root = Path(os.path.abspath(root))
    target = Path(os.path.abspath(target))
    try:
        parts = target.relative_to(root).parts
    except ValueError as exc:
        raise ValueError("assessment source path escapes the owning project") from exc
    _assert_plain_directory(root, "assessment project")
    current = root
    for part in parts:
        current = current / part
        metadata = current.lstat()
        if store_module._is_link_or_reparse(metadata):
            raise ValueError("assessment source path contains a link or reparse point")
    if target.resolve(strict=True) != target:
        raise ValueError("assessment source path changed during resolution")


def _assert_plain_directory(path: Path, label: str) -> None:
    metadata = path.lstat()
    if store_module._is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{label} must be a plain directory")


def _assert_plain_file(path: Path, label: str) -> None:
    metadata = path.lstat()
    if store_module._is_link_or_reparse(metadata) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{label} must be a plain file")


def _run_id(value: object) -> str:
    if not isinstance(value, str) or _RUN_ID_RE.fullmatch(value) is None:
        raise ValueError("assessment source run identity is invalid")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"assessment source {label} is invalid")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "ASSESSMENT_RESULT_SOURCE_SCHEMA_VERSION",
    "register_assessment_result_source",
    "resolve_assessment_result_source",
]
