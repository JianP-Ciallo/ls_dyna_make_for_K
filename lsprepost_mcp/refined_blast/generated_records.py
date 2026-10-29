"""Persisted generated-artifact index and integrity verification."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import base64

from lsprepost_mcp.config import JSONDict
from . import store as store_module
from .store import (
    read_store_json,
    RefinedBlastStore,
    StoredProject,
    StoredArtifact,
    DraftConflictError,
    validate_storage_identifier,
)
from .assembler import RefinedBlastPackage
from .record_contract import (
    RecordError,
    is_sha256,
    require_exact_keys,
    require_mapping,
    nonempty_string,
    positive_revision,
)

GENERATED_INDEX_SCHEMA_VERSION = "phase18f_refined_blast_generated_index@1"


GENERATED_INDEX_NAME = "phase18f_refined_blast_generated_index.json"


class GeneratedArtifactIndex:
    def __init__(self, store: RefinedBlastStore) -> None:
        self._store = store

    def path(self, project_id: str) -> Path:
        return self._store._layout(project_id, create=False) / GENERATED_INDEX_NAME

    def publish(
        self, artifact: StoredArtifact, package_fingerprint: str, stored: StoredProject
    ) -> None:
        if not is_sha256(package_fingerprint):
            raise RecordError("artifact_integrity_error", "generated package fingerprint is invalid")
        relative_path = artifact.path.relative_to(self._store._safe_root()).as_posix()
        record = {
            "scenario_id": artifact.scenario_id,
            "revision": artifact.revision,
            "generated_revision": artifact.revision,
            "store_artifact_fingerprint": artifact.fingerprint,
            "package_fingerprint": package_fingerprint,
            "relative_path": relative_path,
            "project_content_fingerprint": project_content_fingerprint(stored),
            "scenario_content_fingerprint": scenario_content_fingerprint(stored, artifact.scenario_id),
        }
        if stored.project_id != artifact.project_id or stored.revision != artifact.revision:
            raise DraftConflictError(
                f"generated index revision {artifact.revision} does not match projected project"
            )
        path = self.path(artifact.project_id)
        if path.exists():
            raw = read_store_json(path, self._store)
            rows = generated_index_records(raw, artifact.project_id)
        else:
            rows = []
        identity = (artifact.scenario_id, artifact.revision)
        matching = [row for row in rows if (row["scenario_id"], row["revision"]) == identity]
        if matching:
            if len(matching) == 1 and matching[0] == record:
                return
            raise RecordError("artifact_conflict", "generated artifact index identity already exists")
        rows.append(record)
        store_module._atomic_write_json(
            path,
            {
                "schema_version": GENERATED_INDEX_SCHEMA_VERSION,
                "project_id": artifact.project_id,
                "records": rows,
            },
            root=self._store._safe_root(),
            anchor=self._store._root_anchor,
        )


def generated_index_records(raw: Mapping[str, object], project_id: str) -> list[JSONDict]:
    require_exact_keys(raw, frozenset({"schema_version", "project_id", "records"}), "generated index")
    if raw["schema_version"] != GENERATED_INDEX_SCHEMA_VERSION or raw["project_id"] != project_id:
        raise ValueError("generated index identity does not match project")
    records = raw["records"]
    if not isinstance(records, list):
        raise ValueError("generated index records must be an array")
    result: list[JSONDict] = []
    identities: set[tuple[str, int]] = set()
    expected = frozenset({
        "scenario_id", "revision", "generated_revision", "store_artifact_fingerprint", "package_fingerprint", "relative_path",
        "project_content_fingerprint", "scenario_content_fingerprint",
    })
    for index, row in enumerate(records):
        mapping = require_mapping(row, f"generated index records[{index}]")
        require_exact_keys(mapping, expected, f"generated index records[{index}]")
        scenario_id = nonempty_string(mapping["scenario_id"], "generated scenario_id")
        revision = positive_revision(mapping["revision"])
        generated_revision = positive_revision(mapping["generated_revision"])
        if revision != generated_revision:
            raise ValueError("generated index revision mismatch")
        if not is_sha256(mapping["store_artifact_fingerprint"]) or not is_sha256(mapping["package_fingerprint"]):
            raise ValueError("generated index fingerprint is invalid")
        if not is_sha256(mapping["project_content_fingerprint"]) or not is_sha256(mapping["scenario_content_fingerprint"]):
            raise ValueError("generated index content fingerprint is invalid")
        relative_path = nonempty_string(mapping["relative_path"], "generated relative_path")
        identity = (scenario_id, revision)
        if identity in identities:
            raise ValueError("generated index has duplicate artifact identity")
        identities.add(identity)
        result.append({
            "scenario_id": scenario_id,
            "revision": revision,
            "generated_revision": generated_revision,
            "store_artifact_fingerprint": mapping["store_artifact_fingerprint"],
            "package_fingerprint": mapping["package_fingerprint"],
            "relative_path": relative_path,
            "project_content_fingerprint": mapping["project_content_fingerprint"],
            "scenario_content_fingerprint": mapping["scenario_content_fingerprint"],
        })
    return result


def safe_generated_path(
    relative_path: str,
    store: RefinedBlastStore,
    project_id: str,
    scenario_id: str,
    revision: int,
    artifact_fingerprint: str,
) -> Path:
    candidate = Path(relative_path.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise ValueError("generated artifact path is invalid")
    root = store._safe_root()
    path = root.joinpath(candidate)
    generated = store._layout(project_id, create=False) / "generated"
    safe_scenario = validate_storage_identifier(scenario_id, "scenario_id")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("generated artifact revision is invalid")
    if not is_sha256(artifact_fingerprint):
        raise ValueError("generated artifact fingerprint is invalid")
    expected = generated / safe_scenario / (
        f"revision-{revision:08d}-{artifact_fingerprint}.json"
    )
    if path != expected:
        raise ValueError("generated artifact path is outside the current project layout")
    store_module._assert_safe_file(path, root, missing_ok=False)
    return path


def verified_generated_package(
    raw: Mapping[str, object],
    *,
    project_id: str,
    scenario_id: str,
    revision: int,
    store_fingerprint: str,
    package_fingerprint: str,
) -> RefinedBlastPackage:
    require_exact_keys(raw, frozenset({"package", "package_fingerprint", "project_id", "revision", "scenario_id"}), "generated artifact")
    if (
        raw["project_id"] != project_id
        or raw["scenario_id"] != scenario_id
        or raw["revision"] != revision
        or raw["package_fingerprint"] != store_fingerprint
    ):
        raise ValueError("generated artifact identity does not match index")
    package_raw = require_mapping(raw["package"], "generated package")
    if store_module._sha256(package_raw) != store_fingerprint:
        raise ValueError("generated artifact store fingerprint mismatch")
    expected = frozenset({
        "schema_version", "building_artifact_fingerprint", "package_fingerprint", "manifest",
        "symbol_to_numeric_id", "files", "solver_ready", "requires_project_review", "external_program_started",
    })
    require_exact_keys(package_raw, expected, "generated package")
    if (
        package_raw["schema_version"] != "refined_blast_web_package@1"
        or package_raw["solver_ready"] is not False
        or package_raw["requires_project_review"] is not True
        or package_raw["external_program_started"] is not False
        or not is_sha256(package_raw["package_fingerprint"])
    ):
        raise ValueError("generated package public boundary is invalid")
    file_rows = package_raw["files"]
    if not isinstance(file_rows, list):
        raise ValueError("generated package files must be an array")
    files: dict[str, bytes] = {}
    for index, row in enumerate(file_rows):
        record = require_mapping(row, f"generated package files[{index}]")
        require_exact_keys(record, frozenset({"path", "encoding", "content"}), f"generated package files[{index}]")
        path = nonempty_string(record["path"], "generated package file path")
        if record["encoding"] != "base64" or not isinstance(record["content"], str) or path in files:
            raise ValueError("generated package file record is invalid")
        try:
            files[path] = base64.b64decode(record["content"], validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("generated package file encoding is invalid") from exc
    package = RefinedBlastPackage(
        files=files,
        manifest=require_mapping(package_raw["manifest"], "generated package manifest"),
        symbol_to_numeric_id=require_mapping(package_raw["symbol_to_numeric_id"], "generated package IDs"),
        building_artifact_fingerprint=nonempty_string(
            package_raw["building_artifact_fingerprint"], "generated package building fingerprint"
        ),
    )
    if package.package_fingerprint != package_raw["package_fingerprint"] or package.package_fingerprint != package_fingerprint:
        raise ValueError("generated package fingerprint mismatch")
    return package


def project_content_fingerprint(stored: StoredProject) -> str:
    return store_module._sha256(store_module._project_to_raw(stored.project))


def scenario_content_fingerprint(stored: StoredProject, scenario_id: str) -> str:
    rows = [row for row in stored.project.scenario_set if row.scenario_id == scenario_id]
    if len(rows) != 1:
        raise RecordError("artifact_stale", "generated scenario is no longer uniquely present in the current project")
    return store_module._sha256(store_module._scenario_to_raw(rows[0]))
