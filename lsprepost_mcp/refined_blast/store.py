"""Versioned, fail-closed storage for ``refined_building_blast@1`` projects."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Callable, ContextManager, Iterator, Protocol

from .contracts import (
    RefinedBlastProject,
    ScenarioDraft,
    normalize_refined_blast_project,
    normalize_scenario_draft,
    validate_refined_identifier,
)


_STATE_FORMAT = "refined_building_blast_store@1"
_LEGACY_SOLVER_CONFIG_VERSIONS = frozenset(
    {
        "phase18.solver_blast.config@1",
        "phase18.solver_blast.config@2",
        "phase18.solver_blast.config@3",
    }
)
_FINGERPRINT_KEYS = frozenset(
    {
        "building",
        "scenario_input",
        "provider",
        "output_requests",
        "assembly",
        "preview",
        "results",
    }
)
_PROJECT_LOCKS_GUARD = threading.Lock()
_PROJECT_LOCKS: dict[str, threading.RLock] = {}
_PROJECT_ROOT_ACQUISITION_LOCKS_GUARD = threading.Lock()
_PROJECT_ROOT_ACQUISITION_LOCKS: dict[object, threading.Lock] = {}
_PROJECT_TRANSACTION_DEPTHS = threading.local()
_WRITE_GUARD_HOOK: Callable[[Path], None] | None = None
_LOCK_GUARD_HOOK: Callable[[Path], None] | None = None
_ROOT_GUARD_HOOK: Callable[[Path], None] | None = None
_LOCK_FILE_GUARD_HOOK: Callable[[Path], None] | None = None
_DIRECTORY_GUARD_OPEN_HOOK: Callable[[Path], None] | None = None
_PROJECT_READ_GUARD_HOOK: Callable[[Path], None] | None = None
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


class DraftConflictError(RuntimeError):
    """Raised when a caller attempts to write against a stale project revision."""


class RefinedBlastPackage(Protocol):
    """The deliberately small boundary required before Task 7 defines packages."""

    def to_serializable(self) -> Mapping[str, object]:
        """Return the package's closed JSON payload."""


@dataclass(frozen=True)
class InvalidationRecord:
    building: bool
    scenario: bool
    provider: bool
    output_requests: bool
    assembly: bool
    preview: bool
    results: bool


@dataclass(frozen=True)
class StoredProject:
    project_id: str
    revision: int
    project: RefinedBlastProject
    fingerprints: Mapping[str, str]
    invalidation: InvalidationRecord


@dataclass(frozen=True)
class StoredArtifact:
    project_id: str
    scenario_id: str
    revision: int
    fingerprint: str
    path: Path


class RefinedBlastStore:
    """Persist immutable project snapshots under a root owned by the caller."""

    def __init__(self, root: Path):
        self._root = Path(os.path.abspath(Path(root)))
        self._lifecycle_lock = threading.RLock()
        self._lifecycle_condition = threading.Condition(self._lifecycle_lock)
        self._active_transactions = 0
        self._active_transaction_threads: dict[int, int] = {}
        self._closing = False
        self._closed = True
        self._root.mkdir(parents=True, exist_ok=True)
        anchor = _RootAnchor(self._root)
        try:
            hook = _ROOT_GUARD_HOOK
            if hook is not None:
                hook(self._root)
            anchor.verify()
        except BaseException:
            anchor.close()
            raise
        self._root_anchor = anchor
        self._closed = False

    def __enter__(self) -> "RefinedBlastStore":
        self._ensure_open()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except BaseException:
            pass

    def close(self) -> None:
        lock = getattr(self, "_lifecycle_lock", None)
        if lock is None:
            return
        with lock:
            if self._closed:
                return
            thread_id = threading.get_ident()
            if self._active_transaction_threads.get(thread_id, 0):
                raise RuntimeError("cannot close refined blast store during a project transaction")
            if self._closing:
                while not self._closed:
                    self._lifecycle_condition.wait()
                return
            self._closing = True
            while self._active_transactions:
                self._lifecycle_condition.wait()
            self._closed = True
            self._root_anchor.close()
            self._lifecycle_condition.notify_all()

    def _ensure_open(self) -> None:
        if getattr(self, "_closed", True) or (
            getattr(self, "_closing", False)
            and not getattr(self, "_active_transaction_threads", {}).get(
                threading.get_ident(), 0
            )
        ):
            raise RuntimeError("refined blast store is closed")

    def create(self, project: RefinedBlastProject) -> StoredProject:
        normalized = _normalize_project(project)
        project_id = validate_storage_identifier(normalized.project_id, "project_id")
        with self._write_lock(project_id):
            project_dir = self._layout(project_id, create=True)
            if (project_dir / "project.json").exists():
                raise FileExistsError(f"project already exists: {project_id!r}")
            for name in ("drafts", "previews", "generated", "evidence", "results"):
                _create_safe_directory(project_dir / name, self._safe_root())
            stored = StoredProject(
                project_id=project_id,
                revision=1,
                project=normalized,
                fingerprints=_fingerprints(normalized),
                invalidation=_no_invalidation(),
            )
            self._write_project(stored)
            return stored

    def load_project(self, project_id: str) -> StoredProject:
        with self._lifecycle_lock:
            self._ensure_open()
            safe_id = validate_storage_identifier(project_id, "project_id")
            state_path = self._layout(safe_id, create=False) / "project.json"
            _assert_safe_file(state_path, self._safe_root(), missing_ok=True)
            try:
                text = _read_text_file(
                    state_path, root=self._safe_root(), anchor=self._root_anchor
                )
            except FileNotFoundError as exc:
                raise FileNotFoundError(f"project does not exist: {safe_id!r}") from exc
            try:
                payload = json.loads(text, object_pairs_hook=_reject_duplicate_json_keys)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError("corrupt project.json") from exc
            return self._stored_from_payload(payload, safe_id)

    def save_draft(
        self, project_id: str, draft: ScenarioDraft, expected_revision: int
    ) -> StoredProject:
        safe_id = validate_storage_identifier(project_id, "project_id")
        with self._write_lock(safe_id):
            current = self.load_project(safe_id)
            _check_revision(current.revision, expected_revision)
            normalized_draft = _normalize_draft(draft)
            raw = _project_to_raw(current.project)
            raw["scenario_set"] = [
                _scenario_to_raw(normalized_draft)
                if scenario.scenario_id == normalized_draft.scenario_id
                else _scenario_to_raw(scenario)
                for scenario in current.project.scenario_set
            ]
            if not any(
                scenario.scenario_id == normalized_draft.scenario_id
                for scenario in current.project.scenario_set
            ):
                raw["scenario_set"].append(_scenario_to_raw(normalized_draft))
            raw["updated_at"] = _utc_timestamp()
            next_project = normalize_refined_blast_project(raw)
            stored = StoredProject(
                project_id=current.project_id,
                revision=current.revision + 1,
                project=next_project,
                fingerprints=_fingerprints(next_project),
                invalidation=derive_invalidation(current.project, next_project),
            )
            self._write_project(stored)
            return stored

    def commit_generated_package(
        self,
        project_id: str,
        scenario_id: str,
        package: RefinedBlastPackage,
        expected_revision: int,
        *,
        before_project_commit: Callable[[StoredArtifact, StoredProject], None] | None = None,
    ) -> StoredArtifact:
        safe_id = validate_storage_identifier(project_id, "project_id")
        with self._write_lock(safe_id):
            current = self.load_project(safe_id)
            _check_revision(current.revision, expected_revision)
            safe_scenario_id = validate_storage_identifier(scenario_id, "scenario_id")
            if safe_scenario_id not in {item.scenario_id for item in current.project.scenario_set}:
                raise ValueError(f"scenario_id is not in project: {safe_scenario_id!r}")
            package_payload = _package_to_raw(package)
            declared_scenario = package_payload.get("scenario_id")
            if declared_scenario is not None and declared_scenario != safe_scenario_id:
                raise ValueError("package scenario_id does not match target scenario_id")
            fingerprint = _sha256(package_payload)
            project_dir = self._layout(current.project_id, create=False)
            artifact_dir = project_dir / "generated" / safe_scenario_id
            _create_safe_directory(artifact_dir, self._safe_root())
            next_revision = current.revision + 1
            artifact_path = artifact_dir / f"revision-{next_revision:08d}-{fingerprint}.json"
            _assert_safe_file(artifact_path, self._safe_root(), missing_ok=True)
            artifact_payload = {
                "package": package_payload,
                "package_fingerprint": fingerprint,
                "project_id": current.project_id,
                "revision": next_revision,
                "scenario_id": safe_scenario_id,
            }
            if artifact_path.exists():
                try:
                    existing = json.loads(
                        artifact_path.read_text(encoding="utf-8"),
                        object_pairs_hook=_reject_duplicate_json_keys,
                    )
                except (OSError, json.JSONDecodeError, ValueError) as exc:
                    raise ValueError("corrupt generated artifact") from exc
                if existing != artifact_payload:
                    raise ValueError("generated artifact fingerprint collision")
            else:
                _atomic_write_json(
                    artifact_path, artifact_payload, root=self._safe_root(), anchor=self._root_anchor
                )
            artifact = StoredArtifact(
                project_id=current.project_id,
                scenario_id=safe_scenario_id,
                revision=next_revision,
                fingerprint=fingerprint,
                path=artifact_path,
            )
            next_project = StoredProject(
                project_id=current.project_id,
                revision=next_revision,
                project=current.project,
                fingerprints=current.fingerprints,
                invalidation=_no_invalidation(),
            )
            if before_project_commit is not None:
                before_project_commit(artifact, next_project)
            self._write_project(next_project)
            return artifact

    def materialize_action_snapshot(
        self, project_id: str, snapshot_name: str, files: Mapping[str, bytes]
    ) -> Path:
        """Publish one immutable action snapshot beneath the owning project."""

        safe_id = validate_storage_identifier(project_id, "project_id")
        safe_name = validate_storage_identifier(snapshot_name, "snapshot_name")
        normalized = _normalize_snapshot_files(files)
        with self._write_lock(safe_id):
            root = self._safe_root()
            generated = self._layout(safe_id, create=False) / "generated"
            temporary = generated / f"temporary-{safe_name}"
            final = generated / safe_name
            if _path_lstat(temporary) is not None or _path_lstat(final) is not None:
                raise ValueError("action snapshot identity already exists")
            _create_safe_directory(temporary, root)
            for relative, content in normalized.items():
                target = temporary.joinpath(*PurePosixPath(relative).parts)
                current = temporary
                for part in PurePosixPath(relative).parts[:-1]:
                    current = current / part
                    _create_safe_directory(current, root)
                _atomic_write_bytes(
                    target, content, root=root, anchor=self._root_anchor
                )
            with _DirectoryGuard(generated, root, anchor=self._root_anchor) as guard:
                guard.verify()
                _assert_safe_directory(temporary, root)
                if _path_lstat(final) is not None:
                    raise ValueError("action snapshot identity already exists")
                if os.name == "nt":
                    os.replace(temporary, final)
                else:
                    os.replace(
                        temporary.name,
                        final.name,
                        src_dir_fd=guard.fd,
                        dst_dir_fd=guard.fd,
                    )
                guard.verify()
            _assert_safe_directory(final, root)
            return final

    def verify_action_snapshot(
        self, project_id: str, snapshot: Path, expected_sha256: Mapping[str, str]
    ) -> Path:
        """Re-open and hash the exact project-bound snapshot before delegation."""

        safe_id = validate_storage_identifier(project_id, "project_id")
        normalized = _normalize_snapshot_digests(expected_sha256)
        with self._write_lock(safe_id):
            root = self._safe_root()
            generated = self._layout(safe_id, create=False) / "generated"
            name = validate_storage_identifier(Path(snapshot).name, "snapshot_name")
            expected_snapshot = generated / name
            if Path(os.path.abspath(snapshot)) != expected_snapshot:
                raise ValueError("action snapshot is outside the current project")
            _assert_safe_directory(expected_snapshot, root)
            with _DirectoryGuard(
                expected_snapshot, root, anchor=self._root_anchor
            ) as guard:
                for relative, expected_digest in normalized.items():
                    target = expected_snapshot.joinpath(*PurePosixPath(relative).parts)
                    _assert_safe_file(target, root, missing_ok=False)
                    actual = hashlib.sha256(
                        _read_bytes_file(target, root=root, anchor=self._root_anchor)
                    ).hexdigest()
                    if actual != expected_digest:
                        raise ValueError("action snapshot content fingerprint changed")
                guard.verify()
            return expected_snapshot

    @contextmanager
    def _write_lock(self, project_id: str):
        with self.project_transaction(project_id):
            yield

    def project_directory(self, project_id: str) -> Path:
        """Resolve an existing project directory with the store's path guards."""
        return self._layout(project_id, create=False)

    def project_transaction(self, project_id: str) -> ContextManager[None]:
        """Hold the cross-thread/process lease for one project's complete operation."""

        safe_id = validate_storage_identifier(project_id, "project_id")
        return self._project_transaction(safe_id)

    @contextmanager
    def _project_transaction(self, project_id: str) -> Iterator[None]:
        thread_id = threading.get_ident()
        with self._lifecycle_lock:
            self._ensure_open()
            self._root_anchor.verify()
            root_identity = self._root_anchor.identity
            self._active_transactions += 1
            self._active_transaction_threads[thread_id] = (
                self._active_transaction_threads.get(thread_id, 0) + 1
            )
        ownership_key = (root_identity, project_id)
        try:
            depths = getattr(_PROJECT_TRANSACTION_DEPTHS, "depths", None)
            if depths is None:
                depths = {}
                _PROJECT_TRANSACTION_DEPTHS.depths = depths
            depth = depths.get(ownership_key, 0)
            if depth:
                depths[ownership_key] = depth + 1
                try:
                    yield
                finally:
                    next_depth = depths[ownership_key] - 1
                    if next_depth:
                        depths[ownership_key] = next_depth
                    else:
                        depths.pop(ownership_key, None)
                return

            key = f"{root_identity!r}:{project_id}"
            with _PROJECT_LOCKS_GUARD:
                local_lock = _PROJECT_LOCKS.setdefault(key, threading.RLock())
            with local_lock:
                with self._process_lock(project_id):
                    depths[ownership_key] = 1
                    try:
                        yield
                    finally:
                        depths.pop(ownership_key, None)
        finally:
            with self._lifecycle_lock:
                self._active_transactions -= 1
                remaining = self._active_transaction_threads[thread_id] - 1
                if remaining:
                    self._active_transaction_threads[thread_id] = remaining
                else:
                    self._active_transaction_threads.pop(thread_id, None)
                if not self._active_transactions:
                    self._lifecycle_condition.notify_all()

    @contextmanager
    def _process_lock(self, project_id: str):
        root = self._safe_root()
        lock_dir = root / ".refined_blast_locks"
        safe_lock_name = f"{validate_storage_identifier(project_id, 'project_id')}.lock"
        if os.name != "nt":
            with ExitStack() as resources:
                with _project_root_acquisition_lock(self._root_anchor.identity):
                    with _posix_root_transaction_lock(self._root_anchor.fd):
                        lock_dir_fd = self._root_anchor.open_directory(
                            ".refined_blast_locks", create=True
                        )
                        resources.callback(os.close, lock_dir_fd)
                        hook = _LOCK_GUARD_HOOK
                        if hook is not None:
                            hook(lock_dir)
                        lock_path = lock_dir / safe_lock_name
                        lock_hook = _LOCK_FILE_GUARD_HOOK
                        if lock_hook is not None:
                            lock_hook(lock_path)
                        lock_fd = _open_posix_lock_file(lock_dir_fd, safe_lock_name)
                        handle = resources.enter_context(
                            _fdopen_owned(lock_fd, "r+b", buffering=0)
                        )
                        _locked_file_transaction(handle)
                try:
                    yield
                finally:
                    _unlock_file(handle)
            return

        _create_safe_directory(lock_dir, root)
        with _DirectoryGuard(lock_dir, root, anchor=self._root_anchor) as guard:
            hook = _LOCK_GUARD_HOOK
            if hook is not None:
                hook(lock_dir)
            guard.verify()
            lock_path = lock_dir / safe_lock_name
            lock_hook = _LOCK_FILE_GUARD_HOOK
            if lock_hook is not None:
                lock_hook(lock_path)
            with _open_windows_lock_file(lock_path, self._root_anchor) as handle:
                guard.verify()
                _locked_file_transaction(handle)
                try:
                    yield
                finally:
                    _unlock_file(handle)

    def _safe_root(self) -> Path:
        self._ensure_open()
        self._root_anchor.verify()
        return self._root

    def _layout(self, project_id: str, *, create: bool) -> Path:
        root = self._safe_root()
        workspace = root / "workspace"
        base = workspace / "refined_building_blast"
        for directory in (workspace, base):
            if create:
                _create_safe_directory(directory, root)
            else:
                _assert_safe_directory(directory, root)
        project_dir = base / validate_storage_identifier(project_id, "project_id")
        if create:
            _create_safe_directory(project_dir, root)
        else:
            _assert_safe_directory(project_dir, root)
        for name in ("drafts", "previews", "generated", "evidence", "results"):
            path = project_dir / name
            if create:
                _create_safe_directory(path, root)
            else:
                _assert_safe_directory(path, root)
        return project_dir

    def _write_project(self, stored: StoredProject) -> None:
        payload = {
            "fingerprints": dict(stored.fingerprints),
            "format": _STATE_FORMAT,
            "project": _project_to_raw(stored.project),
            "revision": stored.revision,
        }
        state_path = self._layout(stored.project_id, create=False) / "project.json"
        _assert_safe_file(state_path, self._safe_root(), missing_ok=True)
        _atomic_write_json(state_path, payload, root=self._safe_root(), anchor=self._root_anchor)

    def _stored_from_payload(self, payload: object, requested_id: str) -> StoredProject:
        if not isinstance(payload, Mapping) or set(payload) != {
            "fingerprints",
            "format",
            "project",
            "revision",
        }:
            raise ValueError("corrupt project.json")
        if payload["format"] != _STATE_FORMAT:
            raise ValueError("corrupt project.json")
        revision = payload["revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError("corrupt project.json")
        try:
            raw_project = _require_mapping(payload["project"], "project")
            project = normalize_refined_blast_project(raw_project)
            fingerprints = _validate_fingerprints(payload["fingerprints"])
        except (TypeError, ValueError) as exc:
            raise ValueError("corrupt project.json") from exc
        if project.project_id != requested_id:
            raise ValueError("corrupt project.json")
        canonical_fingerprints = _fingerprints(project)
        if fingerprints != canonical_fingerprints:
            if not _valid_legacy_solver_config_migration(
                raw_project,
                project,
                fingerprints,
            ):
                raise ValueError("corrupt project.json")
            fingerprints = canonical_fingerprints
        return StoredProject(
            project_id=requested_id,
            revision=revision,
            project=project,
            fingerprints=fingerprints,
            invalidation=_no_invalidation(),
        )


def derive_invalidation(
    previous: RefinedBlastProject, current: RefinedBlastProject
) -> InvalidationRecord:
    """Describe the narrowest cache invalidation implied by two snapshots."""

    before = _fingerprints(_require_project(previous))
    after = _fingerprints(_require_project(current))
    building = before["building"] != after["building"]
    scenario = before["scenario_input"] != after["scenario_input"]
    provider = before["provider"] != after["provider"]
    output_requests = before["output_requests"] != after["output_requests"]
    assembly = before["assembly"] != after["assembly"]
    preview = before["preview"] != after["preview"]
    results = before["results"] != after["results"]
    return InvalidationRecord(
        building=building,
        scenario=scenario,
        provider=provider,
        output_requests=output_requests,
        assembly=assembly,
        preview=preview,
        results=results,
    )


def _normalize_project(project: RefinedBlastProject) -> RefinedBlastProject:
    return normalize_refined_blast_project(_project_to_raw(_require_project(project)))


def _normalize_draft(draft: ScenarioDraft) -> ScenarioDraft:
    if not isinstance(draft, ScenarioDraft):
        raise ValueError("draft must be a ScenarioDraft")
    return normalize_scenario_draft(_scenario_to_raw(draft))


def _require_project(project: object) -> RefinedBlastProject:
    if not isinstance(project, RefinedBlastProject):
        raise ValueError("project must be a RefinedBlastProject")
    return project


def _fingerprints(project: RefinedBlastProject) -> Mapping[str, str]:
    building = _sha256(
        {
            "building_artifact_fingerprint": project.building_artifact_fingerprint,
            "building_reference": project.building_reference,
            "expert_extensions": project.expert_extensions,
            "preset_reference": project.preset_reference,
            "preset_version": project.preset_version,
            "project_overrides": project.project_overrides,
        }
    )
    scenario_rows = [_scenario_to_raw(item) for item in project.scenario_set]
    raw_scenario_input = [
        {key: value for key, value in row.items() if key not in {"load_provider", "output_requests"}}
        for row in scenario_rows
    ]
    scenario_input = _sha256({"building": building, "scenarios": raw_scenario_input})
    provider = _sha256(
        {
            "building": building,
            "providers": [
                {"load_provider": row["load_provider"], "scenario_id": row["scenario_id"]}
                for row in scenario_rows
            ],
        }
    )
    output_requests = _sha256(
        [
            {"output_requests": row["output_requests"], "scenario_id": row["scenario_id"]}
            for row in scenario_rows
        ]
    )
    assembly = _sha256(
        {
            "building": building,
            "output_requests": output_requests,
            "provider": provider,
            "scenario_input": scenario_input,
        }
    )
    preview = _sha256({"building": building, "scenario_input": scenario_input})
    results = _sha256(
        {"assembly": assembly, "output_requests": output_requests, "preview": preview}
    )
    return MappingProxyType(
        {
            "building": building,
            "scenario_input": scenario_input,
            "provider": provider,
            "output_requests": output_requests,
            "assembly": assembly,
            "preview": preview,
            "results": results,
        }
    )


def _valid_legacy_solver_config_migration(
    raw_project: Mapping[str, object],
    project: RefinedBlastProject,
    stored_fingerprints: Mapping[str, str],
) -> bool:
    """Accept only an intact legacy solver input with one canonical v4 image."""

    try:
        if stored_fingerprints != _fingerprints_from_raw_project(raw_project):
            return False
        migrated = copy.deepcopy(dict(raw_project))
        canonical = _project_to_raw(project)
        migrated_rows = migrated["scenario_set"]
        canonical_rows = canonical["scenario_set"]
        if (
            not isinstance(migrated_rows, list)
            or not isinstance(canonical_rows, list)
            or len(migrated_rows) != len(canonical_rows)
        ):
            return False
        changed = False
        for index, migrated_row in enumerate(migrated_rows):
            if not isinstance(migrated_row, dict):
                return False
            migrated_provider = migrated_row.get("load_provider")
            canonical_provider = canonical_rows[index].get("load_provider")
            if not isinstance(migrated_provider, dict) or not isinstance(
                canonical_provider, dict
            ):
                return False
            provider_input = migrated_provider.get("provider_input")
            source_version = (
                provider_input.get("schema_version")
                if isinstance(provider_input, dict)
                else None
            )
            if (
                migrated_provider.get("provider_id") == "solver_complete_ale_fsi"
                and source_version in _LEGACY_SOLVER_CONFIG_VERSIONS
            ):
                migrated_provider["provider_input"] = copy.deepcopy(
                    canonical_provider["provider_input"]
                )
                changed = True
        return changed and migrated == canonical
    except (KeyError, TypeError, ValueError):
        return False


def _fingerprints_from_raw_project(
    raw_project: Mapping[str, object],
) -> Mapping[str, str]:
    """Reproduce the v1 store fingerprint graph over already-canonical raw JSON."""

    scenario_rows = raw_project["scenario_set"]
    if not isinstance(scenario_rows, list) or not all(
        isinstance(row, Mapping) for row in scenario_rows
    ):
        raise ValueError("raw project scenarios are invalid")
    building = _sha256(
        {
            "building_artifact_fingerprint": raw_project[
                "building_artifact_fingerprint"
            ],
            "building_reference": raw_project["building_reference"],
            "expert_extensions": raw_project["expert_extensions"],
            "preset_reference": raw_project["preset_reference"],
            "preset_version": raw_project["preset_version"],
            "project_overrides": raw_project["project_overrides"],
        }
    )
    scenario_input = _sha256(
        {
            "building": building,
            "scenarios": [
                {
                    key: value
                    for key, value in row.items()
                    if key not in {"load_provider", "output_requests"}
                }
                for row in scenario_rows
            ],
        }
    )
    provider = _sha256(
        {
            "building": building,
            "providers": [
                {
                    "load_provider": row["load_provider"],
                    "scenario_id": row["scenario_id"],
                }
                for row in scenario_rows
            ],
        }
    )
    output_requests = _sha256(
        [
            {
                "output_requests": row["output_requests"],
                "scenario_id": row["scenario_id"],
            }
            for row in scenario_rows
        ]
    )
    assembly = _sha256(
        {
            "building": building,
            "output_requests": output_requests,
            "provider": provider,
            "scenario_input": scenario_input,
        }
    )
    preview = _sha256({"building": building, "scenario_input": scenario_input})
    results = _sha256(
        {
            "assembly": assembly,
            "output_requests": output_requests,
            "preview": preview,
        }
    )
    return MappingProxyType(
        {
            "building": building,
            "scenario_input": scenario_input,
            "provider": provider,
            "output_requests": output_requests,
            "assembly": assembly,
            "preview": preview,
            "results": results,
        }
    )


def _project_to_raw(project: RefinedBlastProject) -> dict[str, object]:
    return {
        "schema_version": project.schema_version,
        "project_id": project.project_id,
        "building_reference": _json_value(project.building_reference),
        "building_artifact_fingerprint": project.building_artifact_fingerprint,
        "preset_reference": project.preset_reference,
        "preset_version": project.preset_version,
        "project_overrides": _json_value(project.project_overrides),
        "expert_extensions": _json_value(project.expert_extensions),
        "scenario_set": [_scenario_to_raw(item) for item in project.scenario_set],
        "confirmation_records": [_json_value(item) for item in project.confirmation_records],
        "provenance": _json_value(project.provenance),
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def _scenario_to_raw(draft: ScenarioDraft) -> dict[str, object]:
    return {
        "scenario_id": draft.scenario_id,
        "scenario_kind": draft.scenario_kind,
        "building_placement": _json_value(draft.building_placement),
        "support_and_ground": _json_value(draft.support_and_ground),
        "load_provider": _json_value(draft.load_provider),
        "blast_source": _json_value(draft.blast_source),
        "fluid_domain": _json_value(draft.fluid_domain),
        "boundaries": _json_value(draft.boundaries),
        "interactions": _json_value(draft.interactions),
        "solver_controls": _json_value(draft.solver_controls),
        "output_requests": _json_value(draft.output_requests),
        "resource_versions": _json_value(draft.resource_versions),
        "acknowledged_warning_ids": list(draft.acknowledged_warning_ids),
    }


def _package_to_raw(package: object) -> dict[str, object]:
    if isinstance(package, Mapping):
        raw = package
    else:
        serializer = getattr(package, "to_serializable", None)
        if not callable(serializer):
            raise ValueError("package must be a mapping or implement to_serializable")
        raw = serializer()
    if not isinstance(raw, Mapping):
        raise ValueError("serialized package must be a mapping")
    return _require_mapping(_json_value(raw), "package")


def _validate_fingerprints(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or set(value) != _FINGERPRINT_KEYS:
        raise ValueError("invalid fingerprints")
    normalized: dict[str, str] = {}
    for key in sorted(_FINGERPRINT_KEYS):
        digest = value[key]
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("invalid fingerprint")
        normalized[key] = digest
    return MappingProxyType(normalized)


def validate_storage_identifier(value: object, label: str) -> str:
    """Return an ASCII storage identifier or reject the unsafe segment."""

    return validate_refined_identifier(value, label)


def _safe_snapshot_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("action snapshot resource path is unsafe")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts:
        raise ValueError("action snapshot resource path is unsafe")
    for part in path.parts:
        validate_storage_identifier(part, "action snapshot resource path")
    return path.as_posix()


def _normalize_snapshot_files(files: Mapping[str, bytes]) -> dict[str, bytes]:
    if not isinstance(files, Mapping) or not files:
        raise ValueError("action snapshot files must be a non-empty mapping")
    result: dict[str, bytes] = {}
    for relative, content in files.items():
        safe_relative = _safe_snapshot_relative_path(relative)
        if not isinstance(content, bytes):
            raise ValueError("action snapshot resources must be bytes")
        result[safe_relative] = content
    return result


def _normalize_snapshot_digests(digests: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(digests, Mapping) or not digests:
        raise ValueError("action snapshot fingerprints must be a non-empty mapping")
    result: dict[str, str] = {}
    for relative, digest in digests.items():
        safe_relative = _safe_snapshot_relative_path(relative)
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("action snapshot fingerprint is invalid")
        result[safe_relative] = digest
    return result


@contextmanager
def _project_root_acquisition_lock(root_identity: object) -> Iterator[None]:
    with _PROJECT_ROOT_ACQUISITION_LOCKS_GUARD:
        lock = _PROJECT_ROOT_ACQUISITION_LOCKS.setdefault(
            root_identity, threading.Lock()
        )
    with lock:
        yield


def _create_safe_directory(path: Path, root: Path) -> None:
    if _path_lstat(path) is None:
        try:
            path.mkdir(parents=path == root, exist_ok=False)
        except FileExistsError:
            # Another process may have created the same direct child after the
            # lstat above.  Never treat that race as success without rerunning
            # the regular no-link/no-reparse/within-root verification below.
            pass
    _assert_safe_directory(path, root)


def _assert_safe_directory(path: Path, root: Path) -> None:
    metadata = _path_lstat(path)
    if metadata is None:
        raise ValueError(f"storage directory is missing: {path.name}")
    if _is_link_or_reparse(metadata):
        raise ValueError(f"storage path is a link or reparse point: {path.name}")
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"storage path is not a directory: {path.name}")
    _assert_resolves_within(path, root)


def _assert_safe_file(path: Path, root: Path, *, missing_ok: bool) -> None:
    metadata = _path_lstat(path)
    if metadata is None:
        if missing_ok:
            _assert_safe_directory(path.parent, root)
            return
        raise ValueError(f"storage file is missing: {path.name}")
    if _is_link_or_reparse(metadata):
        raise ValueError(f"storage path is a link or reparse point: {path.name}")
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"storage path is not a regular file: {path.name}")
    _assert_resolves_within(path, root)


def _path_lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0) or 0
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_point)


def _assert_resolves_within(path: Path, root: Path) -> None:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise ValueError(f"storage path escapes root: {path.name}")


class _RootAnchor:
    """Own the immutable OS identity used as the base of every store operation."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None
        self._handle: int | None = None
        if os.name == "nt":
            handle = _win_open_path(path, directory=True, create=False)
            try:
                metadata = _win_handle_metadata(handle)
                _validate_windows_directory_metadata(metadata, "store root")
                self.identity = metadata.identity
                self.final_path = _win_final_path(handle)
            except BaseException:
                _win_close_handle(handle)
                raise
            self._handle = handle
        else:
            fd, identity = _open_posix_root(path)
            try:
                final_path = Path(os.path.realpath(path))
            except BaseException:
                os.close(fd)
                raise
            self.identity = identity
            self._fd = fd
            self.final_path = final_path

    @property
    def fd(self) -> int:
        if self._fd is None:
            raise RuntimeError("POSIX root descriptor is unavailable")
        return self._fd

    @property
    def handle(self) -> int:
        if self._handle is None:
            raise RuntimeError("Windows root handle is unavailable")
        return self._handle

    def verify(self) -> None:
        if self._fd is None and self._handle is None:
            raise RuntimeError("refined blast store is closed")
        if os.name == "nt":
            metadata = _win_handle_metadata(self.handle)
            _validate_windows_directory_metadata(metadata, "store root")
            if metadata.identity != self.identity:
                raise ValueError("store root identity changed")
            probe = _win_open_path(self.path, directory=True, create=False)
            try:
                probe_metadata = _win_handle_metadata(probe)
                _validate_windows_directory_metadata(probe_metadata, "store root")
                if probe_metadata.identity != self.identity:
                    raise ValueError("store root pathname was replaced")
                if _normalized_windows_path(_win_final_path(probe)) != _normalized_windows_path(
                    self.final_path
                ):
                    raise ValueError("store root pathname moved")
            finally:
                _win_close_handle(probe)
            return
        _verify_posix_root(self.fd, self.path, self.identity, self.final_path)

    def open_directory(self, name: str, *, create: bool) -> int:
        if os.name == "nt":
            raise RuntimeError("POSIX directory open is unavailable")
        self.verify()
        return _open_posix_directory(self.fd, name, create=create)

    def open_relative_directory(self, path: Path) -> int:
        if os.name == "nt":
            raise RuntimeError("POSIX directory traversal is unavailable")
        self.verify()
        try:
            relative = path.relative_to(self.path)
        except ValueError as exc:
            raise ValueError("storage directory escapes root") from exc
        current = os.dup(self.fd)
        try:
            for component in relative.parts:
                next_fd = os.open(
                    component,
                    os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW,
                    dir_fd=current,
                )
                os.close(current)
                current = next_fd
            metadata = os.fstat(current)
            if not stat.S_ISDIR(metadata.st_mode):
                raise ValueError("storage path is not a directory")
            return current
        except BaseException:
            os.close(current)
            raise

    def close(self) -> None:
        if self._fd is not None:
            fd, self._fd = self._fd, None
            os.close(fd)
        if self._handle is not None:
            handle, self._handle = self._handle, None
            _win_close_handle(handle)


@dataclass(frozen=True)
class _WindowsHandleMetadata:
    attributes: int
    reparse_tag: int
    identity: tuple[int, int]
    link_count: int


def _win_kernel32():
    import ctypes

    return ctypes.WinDLL("kernel32", use_last_error=True)


def _win_open_path(
    path: Path,
    *,
    directory: bool,
    create: bool,
    write: bool = True,
    share_delete: bool = False,
) -> int:
    import ctypes
    from ctypes import wintypes

    kernel32 = _win_kernel32()
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    generic_read = 0x80000000
    generic_write = 0x40000000
    share_read_write = 0x00000001 | 0x00000002
    share_delete_flag = 0x00000004
    open_always = 4
    open_existing = 3
    backup_semantics = 0x02000000
    open_reparse_point = 0x00200000
    desired_access = generic_read if directory or not write else generic_read | generic_write
    flags = open_reparse_point | backup_semantics
    handle = create_file(
        str(path),
        desired_access,
        share_read_write | (share_delete_flag if share_delete else 0),
        None,
        open_always if create else open_existing,
        flags,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle == invalid:
        error = ctypes.get_last_error()
        raise OSError(error, os.strerror(error), str(path))
    return int(handle)


def _win_close_handle(handle: int) -> None:
    from ctypes import wintypes

    kernel32 = _win_kernel32()
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    close_handle(handle)


def _win_atomic_replace(source: Path, destination: Path) -> None:
    import ctypes
    from ctypes import wintypes

    if not destination.exists():
        os.replace(source, destination)
        return
    kernel32 = _win_kernel32()
    replace_file = kernel32.ReplaceFileW
    replace_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    replace_file.restype = wintypes.BOOL
    if not replace_file(str(destination), str(source), None, 0, None, None):
        error = ctypes.get_last_error()
        raise OSError(error, os.strerror(error), str(destination))


def _win_handle_metadata(handle: int) -> _WindowsHandleMetadata:
    import ctypes
    from ctypes import wintypes

    class ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("creation_time", wintypes.FILETIME),
            ("access_time", wintypes.FILETIME),
            ("write_time", wintypes.FILETIME),
            ("volume_serial", wintypes.DWORD),
            ("file_size_high", wintypes.DWORD),
            ("file_size_low", wintypes.DWORD),
            ("link_count", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        ]

    class FileAttributeTagInformation(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("reparse_tag", wintypes.DWORD)]

    kernel32 = _win_kernel32()
    info = ByHandleFileInformation()
    get_info = kernel32.GetFileInformationByHandle
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(ByHandleFileInformation)]
    get_info.restype = wintypes.BOOL
    if not get_info(handle, ctypes.byref(info)):
        error = ctypes.get_last_error()
        raise OSError(error, os.strerror(error))
    tag = FileAttributeTagInformation()
    get_info_ex = kernel32.GetFileInformationByHandleEx
    get_info_ex.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    get_info_ex.restype = wintypes.BOOL
    if not get_info_ex(handle, 9, ctypes.byref(tag), ctypes.sizeof(tag)):
        error = ctypes.get_last_error()
        raise OSError(error, os.strerror(error))
    file_index = (int(info.file_index_high) << 32) | int(info.file_index_low)
    return _WindowsHandleMetadata(
        attributes=int(tag.attributes),
        reparse_tag=int(tag.reparse_tag),
        identity=(int(info.volume_serial), file_index),
        link_count=int(info.link_count),
    )


def _win_final_path(handle: int) -> Path:
    import ctypes
    from ctypes import wintypes

    kernel32 = _win_kernel32()
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    get_final_path.restype = wintypes.DWORD
    size = get_final_path(handle, None, 0, 0)
    if size == 0:
        error = ctypes.get_last_error()
        raise OSError(error, os.strerror(error))
    buffer = ctypes.create_unicode_buffer(size + 1)
    if get_final_path(handle, buffer, len(buffer), 0) == 0:
        error = ctypes.get_last_error()
        raise OSError(error, os.strerror(error))
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


def _normalized_windows_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _validate_windows_directory_metadata(metadata: _WindowsHandleMetadata, label: str) -> None:
    directory_attribute = 0x10
    reparse_attribute = 0x400
    if metadata.attributes & reparse_attribute or metadata.reparse_tag:
        raise ValueError(f"{label} is a link or reparse point")
    if not metadata.attributes & directory_attribute:
        raise ValueError(f"{label} is not a directory")


def _validate_windows_regular_handle(handle: int, anchor: _RootAnchor, label: str) -> None:
    metadata = _win_handle_metadata(handle)
    directory_attribute = 0x10
    reparse_attribute = 0x400
    if metadata.attributes & reparse_attribute or metadata.reparse_tag:
        raise ValueError(f"{label} is a link or reparse point")
    if metadata.attributes & directory_attribute or metadata.link_count != 1:
        raise ValueError(f"{label} is not a regular file")
    final_path = _normalized_windows_path(_win_final_path(handle))
    root_path = _normalized_windows_path(anchor.final_path)
    try:
        inside = os.path.commonpath([root_path, final_path]) == root_path
    except ValueError:
        inside = False
    if not inside:
        raise ValueError(f"{label} escapes captured store root")
    anchor.verify()


@contextmanager
def _open_windows_lock_file(path: Path, anchor: _RootAnchor):
    import msvcrt

    handle: int | None = _win_open_path(path, directory=False, create=True)
    fd: int | None = None
    try:
        _validate_windows_regular_handle(handle, anchor, "lock file")
        fd = msvcrt.open_osfhandle(handle, os.O_RDWR | getattr(os, "O_BINARY", 0))
        handle = None  # Ownership transferred to the CRT descriptor.
        try:
            file_handle = _fdopen_owned(fd, "r+b", buffering=0)
        except BaseException:
            fd = None  # _fdopen_owned closed it on failure.
            raise
        fd = None  # Ownership transferred to the Python file object.
        with file_handle:
            yield file_handle
    finally:
        if fd is not None:
            os.close(fd)
        if handle is not None:
            _win_close_handle(handle)


def _open_posix_lock_file(lock_dir_fd: int, name: str) -> int:
    fd = os.open(name, os.O_CREAT | os.O_RDWR | _O_NOFOLLOW, 0o600, dir_fd=lock_dir_fd)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("lock file is not a regular file with one link")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _open_posix_root(path: Path) -> tuple[int, tuple[int, int]]:
    fd = os.open(path, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("store root is not a directory")
        return fd, (metadata.st_dev, metadata.st_ino)
    except BaseException:
        os.close(fd)
        raise


def _open_posix_directory(parent_fd: int, name: str, *, create: bool) -> int:
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
    fd = os.open(name, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=parent_fd)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("lock directory is not a directory")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _verify_posix_root(
    root_fd: int, path: Path, identity: tuple[int, int], canonical_path: Path
) -> None:
    metadata = os.fstat(root_fd)
    path_metadata = os.stat(path, follow_symlinks=False)
    if not stat.S_ISDIR(metadata.st_mode) or _is_link_or_reparse(path_metadata):
        raise ValueError("store root is not a trusted directory")
    if (metadata.st_dev, metadata.st_ino) != identity or (
        path_metadata.st_dev,
        path_metadata.st_ino,
    ) != identity:
        raise ValueError("store root pathname was replaced")
    if Path(os.path.realpath(path)) != canonical_path:
        raise ValueError("store root pathname moved through an ancestor")


def _fdopen_owned(fd: int, *args: object, **kwargs: object):
    try:
        return os.fdopen(fd, *args, **kwargs)
    except BaseException:
        os.close(fd)
        raise


def _open_posix_regular_file(parent_fd: int, name: str) -> int:
    fd = os.open(name, os.O_RDONLY | _O_NOFOLLOW, dir_fd=parent_fd)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("project state is not a regular file with one link")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _read_text_file(path: Path, *, root: Path, anchor: _RootAnchor) -> str:
    with _DirectoryGuard(path.parent, root, anchor=anchor) as guard:
        hook = _PROJECT_READ_GUARD_HOOK
        if hook is not None:
            hook(path)
        guard.verify()
        if os.name == "nt":
            import msvcrt

            handle: int | None = _win_open_path(
                path,
                directory=False,
                create=False,
                write=False,
                share_delete=True,
            )
            fd: int | None = None
            try:
                _validate_windows_regular_handle(handle, anchor, "project state")
                guard.verify()
                fd = msvcrt.open_osfhandle(
                    handle, os.O_RDONLY | getattr(os, "O_BINARY", 0)
                )
                handle = None
                try:
                    file_handle = _fdopen_owned(fd, "r", encoding="utf-8")
                except BaseException:
                    fd = None
                    raise
                fd = None
                with file_handle:
                    text = file_handle.read()
                guard.verify()
                return text
            finally:
                if fd is not None:
                    os.close(fd)
                if handle is not None:
                    _win_close_handle(handle)
        fd = _open_posix_regular_file(guard.fd, path.name)
        file_handle = _fdopen_owned(fd, "r", encoding="utf-8")
        with file_handle:
            text = file_handle.read()
        guard.verify()
        return text


def _read_bytes_file(path: Path, *, root: Path, anchor: _RootAnchor) -> bytes:
    with _DirectoryGuard(path.parent, root, anchor=anchor) as guard:
        guard.verify()
        if os.name == "nt":
            import msvcrt

            handle: int | None = _win_open_path(
                path,
                directory=False,
                create=False,
                write=False,
                share_delete=True,
            )
            fd: int | None = None
            try:
                _validate_windows_regular_handle(handle, anchor, "snapshot file")
                guard.verify()
                fd = msvcrt.open_osfhandle(
                    handle, os.O_RDONLY | getattr(os, "O_BINARY", 0)
                )
                handle = None
                try:
                    file_handle = _fdopen_owned(fd, "rb")
                except BaseException:
                    fd = None
                    raise
                fd = None
                with file_handle:
                    content = file_handle.read()
                guard.verify()
                return content
            finally:
                if fd is not None:
                    os.close(fd)
                if handle is not None:
                    _win_close_handle(handle)
        fd = _open_posix_regular_file(guard.fd, path.name)
        file_handle = _fdopen_owned(fd, "rb")
        with file_handle:
            content = file_handle.read()
        guard.verify()
        return content


def _locked_file_transaction(handle: object) -> None:
    handle.seek(0)
    _lock_file(handle)
    handle.seek(0)
    if handle.read(1) == b"":
        handle.write(b"0")
        handle.flush()
        os.fsync(handle.fileno())
    handle.seek(0)


@contextmanager
def _posix_root_transaction_lock(root_fd: int):
    import fcntl

    deadline = time.monotonic() + 15.0
    while True:
        try:
            fcntl.flock(root_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise DraftConflictError("store root is locked")
            time.sleep(0.01)
    try:
        yield
    finally:
        fcntl.flock(root_fd, fcntl.LOCK_UN)


def _lock_file(handle: object) -> None:
    deadline = time.monotonic() + 15.0
    while True:
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise DraftConflictError("project revision is locked")
            time.sleep(0.01)


def _unlock_file(handle: object) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]


def _check_revision(actual: int, expected: int) -> None:
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
        raise ValueError("expected_revision must be a positive integer")
    if actual != expected:
        raise DraftConflictError(f"expected revision {expected}, found revision {actual}")


def _no_invalidation() -> InvalidationRecord:
    return InvalidationRecord(False, False, False, False, False, False, False)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class _DirectoryGuard:
    """Hold the exact directory object used for a guarded filesystem operation."""

    def __init__(self, path: Path, root: Path, *, anchor: _RootAnchor | None = None) -> None:
        self.path = path
        self.root = root
        self.anchor = anchor
        self._identity: tuple[int, int] | None = None
        self._handle: int | None = None
        self._fd: int | None = None

    @property
    def fd(self) -> int:
        if self._fd is None:
            raise RuntimeError("directory descriptor is unavailable")
        return self._fd

    def __enter__(self) -> "_DirectoryGuard":
        _assert_safe_directory(self.path, self.root)
        try:
            if os.name == "nt":
                self._handle = _win_open_path(self.path, directory=True, create=False)
                metadata = _win_handle_metadata(self._handle)
                _validate_windows_directory_metadata(metadata, "storage directory")
                self._identity = metadata.identity
            else:
                self._fd = (
                    self.anchor.open_relative_directory(self.path)
                    if self.anchor is not None
                    else os.open(self.path, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
                )
                metadata = os.fstat(self._fd)
                if not stat.S_ISDIR(metadata.st_mode):
                    raise ValueError("storage path is not a directory")
                self._identity = (metadata.st_dev, metadata.st_ino)
            hook = _DIRECTORY_GUARD_OPEN_HOOK
            if hook is not None:
                hook(self.path)
            self.verify()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def verify(self) -> None:
        if self.anchor is not None:
            self.anchor.verify()
        if os.name == "nt":
            if self._handle is None:
                raise RuntimeError("directory guard is closed")
            metadata = _win_handle_metadata(self._handle)
            _validate_windows_directory_metadata(metadata, "storage directory")
            if metadata.identity != self._identity:
                raise ValueError("storage directory changed during write")
            if self.anchor is not None:
                final_path = _normalized_windows_path(_win_final_path(self._handle))
                root_path = _normalized_windows_path(self.anchor.final_path)
                try:
                    inside = os.path.commonpath([root_path, final_path]) == root_path
                except ValueError:
                    inside = False
                if not inside:
                    raise ValueError("storage directory escapes captured root")
        else:
            if self._fd is None:
                raise RuntimeError("directory guard is closed")
            metadata = os.fstat(self._fd)
            if not stat.S_ISDIR(metadata.st_mode) or (
                metadata.st_dev,
                metadata.st_ino,
            ) != self._identity:
                raise ValueError("storage directory changed during write")
        _assert_safe_directory(self.path, self.root)
        if os.name == "nt":
            probe = _win_open_path(self.path, directory=True, create=False)
            try:
                if _win_handle_metadata(probe).identity != self._identity:
                    raise ValueError("storage directory changed during write")
            finally:
                _win_close_handle(probe)
        elif _directory_identity(self.path) != self._identity:
            raise ValueError("storage directory changed during write")

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._handle is not None:
            _win_close_handle(self._handle)
            self._handle = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


def _directory_identity(path: Path) -> tuple[int, int]:
    metadata = path.stat()
    return metadata.st_dev, metadata.st_ino


def _atomic_write_json(
    path: Path, payload: Mapping[str, object], *, root: Path, anchor: _RootAnchor
) -> None:
    temporary_path: Path | None = None
    temporary_name: str | None = None
    try:
        _assert_safe_directory(path.parent, root)
        with _DirectoryGuard(path.parent, root, anchor=anchor) as guard:
            try:
                hook = _WRITE_GUARD_HOOK
                if hook is not None:
                    hook(path.parent)
                guard.verify()
                _assert_safe_file(path, root, missing_ok=True)
                if os.name == "nt":
                    with tempfile.NamedTemporaryFile(
                        mode="w",
                        encoding="utf-8",
                        dir=path.parent,
                        prefix=f".{path.name}.",
                        suffix=".tmp",
                        delete=False,
                    ) as handle:
                        temporary_path = Path(handle.name)
                        json.dump(
                            payload,
                            handle,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        )
                        handle.flush()
                        os.fsync(handle.fileno())
                else:
                    temporary_name = f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
                    fd = os.open(
                        temporary_name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW,
                        0o600,
                        dir_fd=guard.fd,
                    )
                    with _fdopen_owned(fd, "w", encoding="utf-8") as handle:
                        json.dump(
                            payload,
                            handle,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        )
                        handle.flush()
                        os.fsync(handle.fileno())
                guard.verify()
                _assert_safe_file(path, root, missing_ok=True)
                if os.name == "nt":
                    _win_atomic_replace(temporary_path, path)
                else:
                    os.replace(
                        temporary_name,
                        path.name,
                        src_dir_fd=guard.fd,
                        dst_dir_fd=guard.fd,
                    )
                    temporary_name = None
                guard.verify()
            except BaseException:
                if temporary_name is not None and os.name != "nt":
                    try:
                        os.unlink(temporary_name, dir_fd=guard.fd)
                    except OSError:
                        pass
                raise
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _atomic_write_bytes(
    path: Path, content: bytes, *, root: Path, anchor: _RootAnchor
) -> None:
    temporary_path: Path | None = None
    temporary_name: str | None = None
    try:
        _assert_safe_directory(path.parent, root)
        with _DirectoryGuard(path.parent, root, anchor=anchor) as guard:
            try:
                hook = _WRITE_GUARD_HOOK
                if hook is not None:
                    hook(path.parent)
                guard.verify()
                _assert_safe_file(path, root, missing_ok=True)
                if os.name == "nt":
                    with tempfile.NamedTemporaryFile(
                        mode="wb",
                        dir=path.parent,
                        prefix=f".{path.name}.",
                        suffix=".tmp",
                        delete=False,
                    ) as handle:
                        temporary_path = Path(handle.name)
                        handle.write(content)
                        handle.flush()
                        os.fsync(handle.fileno())
                else:
                    temporary_name = (
                        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
                    )
                    fd = os.open(
                        temporary_name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW,
                        0o600,
                        dir_fd=guard.fd,
                    )
                    with _fdopen_owned(fd, "wb") as handle:
                        handle.write(content)
                        handle.flush()
                        os.fsync(handle.fileno())
                guard.verify()
                _assert_safe_file(path, root, missing_ok=True)
                if os.name == "nt":
                    _win_atomic_replace(temporary_path, path)
                else:
                    os.replace(
                        temporary_name,
                        path.name,
                        src_dir_fd=guard.fd,
                        dst_dir_fd=guard.fd,
                    )
                    temporary_name = None
                guard.verify()
            except BaseException:
                if temporary_name is not None and os.name != "nt":
                    try:
                        os.unlink(temporary_name, dir_fd=guard.fd)
                    except OSError:
                        pass
                raise
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _sha256(value: object) -> str:
    canonical = json.dumps(
        _json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_value(value: object, ancestors: frozenset[int] = frozenset()) -> object:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON values must be finite")
        return value
    if isinstance(value, Mapping):
        if id(value) in ancestors:
            raise ValueError("JSON values must not be cyclic")
        next_ancestors = ancestors | {id(value)}
        result: dict[str, object] = {}
        for key in sorted(value):
            if not isinstance(key, str) or not key:
                raise ValueError("JSON object keys must be non-empty strings")
            result[key] = _json_value(value[key], next_ancestors)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if id(value) in ancestors:
            raise ValueError("JSON values must not be cyclic")
        next_ancestors = ancestors | {id(value)}
        return [_json_value(item, next_ancestors) for item in value]
    raise ValueError("value is not JSON serializable")


def _require_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    result: dict[str, object] = {}
    for key, nested in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{label} keys must be non-empty strings")
        result[key] = nested
    return result


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def canonical_fingerprint(value: object) -> str:
    """Hash finite JSON using the persisted store's canonical representation."""
    return _sha256(value)


def read_store_json(path: Path, store: RefinedBlastStore) -> dict[str, object]:
    text = _read_text_file(
        path, root=store._safe_root(), anchor=store._root_anchor
    )
    raw = json.loads(text, object_pairs_hook=_reject_duplicate_json_keys)
    if not isinstance(raw, dict):
        raise ValueError("stored refined web metadata must be an object")
    return raw
