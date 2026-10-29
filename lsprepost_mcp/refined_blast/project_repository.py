"""Project creation transactions, recovery and authoritative metadata.

The repository owns persisted identity and transaction state. It does not compile
models, construct HTTP responses or launch external programs.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from lsprepost_mcp.config import JSONDict
from . import store as store_module
from .store import RefinedBlastStore, StoredProject, validate_storage_identifier
from .contracts import RefinedBlastProject, normalize_refined_blast_project
from ..refined_building.artifacts import BuildingArtifact
from .record_contract import (
    RecordError,
    is_sha256,
    require_exact_keys,
    require_mapping,
    nonempty_string,
    json_value,
)
from .project_metadata import (
    CLIENT_PROJECT_KEYS,
    METADATA_SCHEMA_VERSION,
    DEFERRED_METADATA_SCHEMA_VERSION,
    METADATA_NAME,
    COMPILATION_STATES,
    building_definition_fingerprint,
    normalize_building_recipe,
    initial_project_evidence,
    create_request_fingerprint,
    accepted_provider_input_migrations,
)
from .store import read_store_json

CREATE_TRANSACTION_SCHEMA_VERSION = "phase18f_create_transaction@1"


CREATE_TRANSACTION_DIR = ".phase18f_create_transactions"


CREATE_STATES = ("preparing", "project_written", "metadata_written", "complete")


class ProjectRepository:
    def __init__(self, store: RefinedBlastStore) -> None:
        self._store = store

    def materialize_building(
        self,
        stored: StoredProject,
        metadata: Mapping[str, object],
        artifact: BuildingArtifact,
        *,
        selected_resource_id: str,
    ) -> StoredProject:
        if selected_resource_id != stored.project.building_reference.get("asset_id"):
            raise RecordError(
                "project_integrity_error",
                "compiled building resource identity does not match the project",
            )
        project = replace(
            stored.project,
            building_reference={"asset_id": artifact.asset_id},
            building_artifact_fingerprint=artifact.fingerprint,
        )
        materialized = StoredProject(
            project_id=stored.project_id,
            revision=stored.revision,
            project=project,
            fingerprints=store_module._fingerprints(project),
            invalidation=store_module.derive_invalidation(
                stored.project, project
            ),
        )
        raw_metadata = read_store_json(
            self.metadata_path(stored.project_id), self._store
        )
        if (
            raw_metadata.get("schema_version")
            != DEFERRED_METADATA_SCHEMA_VERSION
            or raw_metadata.get("compilation_state") != "pending"
            or raw_metadata.get("building_definition_fingerprint")
            != metadata["definition_fingerprint"]
        ):
            raise RecordError(
                "metadata_integrity_error",
                "pending building metadata cannot be materialized",
            )
        next_metadata = dict(raw_metadata)
        next_metadata["asset_id"] = artifact.asset_id
        next_metadata["building_artifact_fingerprint"] = artifact.fingerprint
        next_metadata["compilation_state"] = "compiled"
        transaction = read_store_json(
            self.transaction_path(stored.project_id, create=False),
            self._store,
        )
        validate_create_transaction(transaction, stored.project_id)
        next_transaction = dict(transaction)
        next_transaction["expected_artifact_fingerprint"] = artifact.fingerprint
        store_module._atomic_write_json(
            self.metadata_path(stored.project_id),
            next_metadata,
            root=self._store._safe_root(),
            anchor=self._store._root_anchor,
        )
        self._write_transaction(next_transaction)
        self._store._write_project(materialized)
        return materialized

    def metadata_path(self, project_id: str) -> Path:
        return self._store._layout(project_id, create=False) / METADATA_NAME

    def _transaction_dir(self, *, create: bool) -> Path:
        root = self._store._safe_root()
        workspace = root / "workspace"
        base = workspace / "refined_building_blast"
        if create:
            store_module._create_safe_directory(workspace, root)
            store_module._create_safe_directory(base, root)
            store_module._create_safe_directory(base / CREATE_TRANSACTION_DIR, root)
        else:
            store_module._assert_safe_directory(workspace, root)
            store_module._assert_safe_directory(base, root)
            store_module._assert_safe_directory(base / CREATE_TRANSACTION_DIR, root)
        return base / CREATE_TRANSACTION_DIR

    def transaction_path(self, project_id: str, *, create: bool) -> Path:
        safe_id = validate_storage_identifier(project_id, "project_id")
        return self._transaction_dir(create=create) / f"{safe_id}.json"

    def create(
        self,
        project: RefinedBlastProject,
        recipe: Mapping[str, object],
        *,
        compilation_state: str,
        definition_fingerprint: str,
    ) -> StoredProject:
        if compilation_state not in COMPILATION_STATES:
            raise ValueError("unsupported building compilation state")
        if not is_sha256(definition_fingerprint):
            raise ValueError("building definition fingerprint is invalid")
        request_fingerprint = create_request_fingerprint(project, recipe)
        with self._store.project_transaction(project.project_id):
            transaction = self._load_or_prepare_transaction(
                project, request_fingerprint, create=True
            )
            state = transaction["state"]
            if state == "preparing":
                stored = self._create_project_locked(project)
                transaction = self._advance_transaction(transaction, "project_written")
                state = "project_written"
            else:
                stored = self._load_transaction_project(
                    project, require_exact_project=state != "complete"
                )
            if state == "project_written":
                self._write_metadata_locked(
                    stored,
                    recipe,
                    compilation_state=compilation_state,
                    definition_fingerprint=definition_fingerprint,
                )
                transaction = self._advance_transaction(transaction, "metadata_written")
                state = "metadata_written"
            if state == "metadata_written":
                self._verify_metadata_identity(
                    stored,
                    recipe,
                    request_fingerprint,
                    compilation_state=compilation_state,
                    definition_fingerprint=definition_fingerprint,
                )
                transaction = self._advance_transaction(transaction, "complete")
                state = "complete"
            if state != "complete":
                raise ValueError("create transaction did not reach complete")
            self._verify_metadata_identity(
                stored,
                recipe,
                request_fingerprint,
                compilation_state=compilation_state,
                definition_fingerprint=definition_fingerprint,
            )
        verified, _, _ = self.verified_record(project.project_id)
        return verified

    def _load_or_prepare_transaction(
        self, project: RefinedBlastProject, request_fingerprint: str, *, create: bool
    ) -> JSONDict:
        path = self.transaction_path(project.project_id, create=create)
        try:
            raw = read_store_json(path, self._store)
        except FileNotFoundError:
            root = self._store._safe_root()
            project_dir = root / "workspace" / "refined_building_blast" / project.project_id
            if store_module._path_lstat(project_dir) is None:
                raw = {
                    "schema_version": CREATE_TRANSACTION_SCHEMA_VERSION,
                    "project_id": project.project_id,
                    "request_fingerprint": request_fingerprint,
                    "expected_artifact_fingerprint": project.building_artifact_fingerprint,
                    "state": "preparing",
                }
                self._write_transaction(raw)
                return raw
            try:
                persisted = self._store.load_project(project.project_id)
            except FileNotFoundError:
                # A concurrent recovery may remove an incomplete project only by
                # an external administrative action; it is safe to retry prepare.
                raw = {
                    "schema_version": CREATE_TRANSACTION_SCHEMA_VERSION,
                    "project_id": project.project_id,
                    "request_fingerprint": request_fingerprint,
                    "expected_artifact_fingerprint": project.building_artifact_fingerprint,
                    "state": "preparing",
                }
                self._write_transaction(raw)
                return raw
            try:
                _, original_request_fingerprint, _, _ = self.read_metadata_evidence(
                    persisted
                )
            except RecordError as exc:
                raise RecordError(
                    "project_creation_incomplete",
                    "existing refined project cannot be recovered without authoritative metadata",
                ) from exc
            if (
                original_request_fingerprint != request_fingerprint
                or persisted.project.building_artifact_fingerprint != project.building_artifact_fingerprint
            ):
                raise RecordError("project_exists", "existing project has a different create request")
            raw = {
                "schema_version": CREATE_TRANSACTION_SCHEMA_VERSION,
                "project_id": project.project_id,
                "request_fingerprint": original_request_fingerprint,
                "expected_artifact_fingerprint": persisted.project.building_artifact_fingerprint,
                "state": "complete",
            }
            self._write_transaction(raw)
            return raw
        validate_create_transaction(raw, project.project_id)
        if (
            raw["request_fingerprint"] != request_fingerprint
            or raw["expected_artifact_fingerprint"] != project.building_artifact_fingerprint
        ):
            raise RecordError("project_exists", "existing create transaction has a different request")
        return raw

    def _write_transaction(self, transaction: Mapping[str, object]) -> None:
        validate_create_transaction(transaction, nonempty_string(transaction.get("project_id"), "transaction project_id"))
        store_module._atomic_write_json(
            self.transaction_path(str(transaction["project_id"]), create=True),
            dict(transaction),
            root=self._store._safe_root(),
            anchor=self._store._root_anchor,
        )

    def _advance_transaction(self, transaction: Mapping[str, object], state: str) -> JSONDict:
        if state not in CREATE_STATES:
            raise ValueError("unsupported create transaction state")
        current = transaction_state_index(transaction["state"])
        expected = current + 1
        if transaction_state_index(state) != expected:
            raise ValueError("create transaction state transition is invalid")
        next_transaction = dict(transaction)
        next_transaction["state"] = state
        self._write_transaction(next_transaction)
        return next_transaction

    def _create_project_locked(self, project: RefinedBlastProject) -> StoredProject:
        project_dir = self._store._layout(project.project_id, create=True)
        if (project_dir / "project.json").exists():
            return self._load_transaction_project(project)
        stored = StoredProject(
            project_id=project.project_id,
            revision=1,
            project=project,
            fingerprints=store_module._fingerprints(project),
            invalidation=store_module._no_invalidation(),
        )
        self._store._write_project(stored)
        return stored

    def _load_transaction_project(
        self, project: RefinedBlastProject, *, require_exact_project: bool = True
    ) -> StoredProject:
        stored = self._store.load_project(project.project_id)
        if require_exact_project and stored.project != project:
            raise RecordError("project_exists", "stored project does not match create transaction")
        if (
            stored.project.building_reference != project.building_reference
            or stored.project.building_artifact_fingerprint != project.building_artifact_fingerprint
        ):
            raise RecordError("project_exists", "stored project building does not match create transaction")
        return stored

    def _write_metadata_locked(
        self,
        stored: StoredProject,
        recipe: Mapping[str, object],
        *,
        compilation_state: str,
        definition_fingerprint: str,
    ) -> None:
        payload = {
            "schema_version": (
                DEFERRED_METADATA_SCHEMA_VERSION
                if compilation_state == "pending"
                else METADATA_SCHEMA_VERSION
            ),
            "project_id": stored.project_id,
            "asset_id": stored.project.building_reference["asset_id"],
            "building_artifact_fingerprint": stored.project.building_artifact_fingerprint,
            "building_recipe": json_value(recipe),
            "initial_project": initial_project_evidence(stored.project),
            "original_request_fingerprint": create_request_fingerprint(stored.project, recipe),
        }
        if compilation_state == "pending":
            payload["compilation_state"] = compilation_state
            payload["building_definition_fingerprint"] = definition_fingerprint
        store_module._atomic_write_json(
            self.metadata_path(stored.project_id),
            payload,
            root=self._store._safe_root(),
            anchor=self._store._root_anchor,
        )

    def _verify_metadata_identity(
        self,
        stored: StoredProject,
        recipe: Mapping[str, object],
        request_fingerprint: str,
        *,
        compilation_state: str,
        definition_fingerprint: str,
    ) -> None:
        (
            persisted,
            original_request_fingerprint,
            _,
            metadata,
        ) = self.read_metadata_evidence(stored)
        if (
            dict(persisted) != dict(recipe)
            or original_request_fingerprint != request_fingerprint
            or metadata["compilation_state"] != compilation_state
            or metadata["definition_fingerprint"] != definition_fingerprint
        ):
            raise RecordError("project_integrity_error", "persisted building recipe does not match create transaction")

    def verified_record(
        self, project_id: str
    ) -> tuple[StoredProject, Mapping[str, object], Mapping[str, object]]:
        """Verify project, recipe, transaction and metadata without compilation."""

        with self._store.project_transaction(project_id):
            try:
                transaction = read_store_json(
                    self.transaction_path(project_id, create=False), self._store
                )
                validate_create_transaction(transaction, project_id)
            except FileNotFoundError as exc:
                try:
                    self._store.load_project(project_id)
                except FileNotFoundError:
                    raise exc
                raise RecordError(
                    "transaction_integrity_error",
                    "refined project creation transaction is missing or invalid",
                ) from exc
            except (OSError, ValueError, RecordError) as exc:
                raise RecordError(
                    "transaction_integrity_error",
                    "refined project creation transaction is missing or invalid",
                ) from exc
            if transaction["state"] != "complete":
                raise RecordError("project_creation_incomplete", "refined project creation is not complete")
            try:
                stored = self._store.load_project(project_id)
            except FileNotFoundError:
                raise RecordError("project_integrity_error", "stored refined project is missing") from None
            except (OSError, ValueError) as exc:
                raise RecordError("project_integrity_error", "stored refined project is invalid") from exc
            (
                recipe,
                original_request_fingerprint,
                _,
                metadata,
            ) = self.read_metadata_evidence(stored)
            expected_artifact_fingerprint = stored.project.building_artifact_fingerprint
            if (
                transaction["expected_artifact_fingerprint"] != expected_artifact_fingerprint
                or transaction["request_fingerprint"]
                != original_request_fingerprint
            ):
                raise RecordError(
                    "transaction_integrity_error",
                    "refined project creation transaction does not match authoritative project evidence",
                )
            if (
                metadata["compilation_state"] == "pending"
                and expected_artifact_fingerprint
                != metadata["definition_fingerprint"]
            ):
                raise RecordError(
                    "project_integrity_error",
                    "pending project definition identity is invalid",
                )
            return stored, recipe, metadata

    def read_metadata_evidence(
        self, stored: StoredProject
    ) -> tuple[
        Mapping[str, object],
        str,
        RefinedBlastProject,
        Mapping[str, object],
    ]:
        try:
            raw = read_store_json(self.metadata_path(stored.project_id), self._store)
            legacy_keys = frozenset({
                "schema_version", "project_id", "asset_id", "building_artifact_fingerprint",
                "building_recipe", "initial_project", "original_request_fingerprint",
            })
            deferred_keys = legacy_keys | frozenset(
                {"compilation_state", "building_definition_fingerprint"}
            )
            schema_version = raw.get("schema_version")
            if schema_version == METADATA_SCHEMA_VERSION:
                require_exact_keys(raw, legacy_keys, "refined project metadata")
                compilation_state = "compiled"
                definition_fingerprint = building_definition_fingerprint(
                    require_mapping(raw["building_recipe"], "metadata building_recipe")
                )
            elif schema_version == DEFERRED_METADATA_SCHEMA_VERSION:
                require_exact_keys(raw, deferred_keys, "refined project metadata")
                compilation_state = nonempty_string(
                    raw["compilation_state"], "metadata compilation_state"
                )
                definition_fingerprint = nonempty_string(
                    raw["building_definition_fingerprint"],
                    "metadata building_definition_fingerprint",
                )
                if (
                    compilation_state not in COMPILATION_STATES
                    or not is_sha256(definition_fingerprint)
                ):
                    raise ValueError("invalid deferred building metadata")
            else:
                raise ValueError("unsupported refined project metadata schema")
            if raw["project_id"] != stored.project_id:
                raise ValueError("metadata project_id does not match project")
            if raw["asset_id"] != stored.project.building_reference.get("asset_id"):
                raise ValueError("metadata asset_id does not match project")
            if raw["building_artifact_fingerprint"] != stored.project.building_artifact_fingerprint:
                raise ValueError("metadata artifact fingerprint does not match project")
            recipe = normalize_building_recipe(
                require_mapping(raw["building_recipe"], "metadata building_recipe")
            )
            original_raw = require_mapping(raw["initial_project"], "metadata initial_project")
            require_exact_keys(original_raw, CLIENT_PROJECT_KEYS, "metadata initial_project")
            reconstructed_raw = dict(original_raw)
            reconstructed_raw["building_reference"] = {"asset_id": raw["asset_id"]}
            reconstructed_raw["building_artifact_fingerprint"] = raw[
                "building_artifact_fingerprint"
            ]
            initial_project = normalize_refined_blast_project(reconstructed_raw)
            canonical_initial_evidence = initial_project_evidence(initial_project)
            provider_input_migrations = accepted_provider_input_migrations(
                original_raw,
                canonical_initial_evidence,
            )
            if (
                not provider_input_migrations
                and canonical_initial_evidence != json_value(original_raw)
            ):
                raise ValueError("metadata initial project is not canonical")
            original_request_fingerprint = nonempty_string(
                raw["original_request_fingerprint"], "metadata original_request_fingerprint"
            )
            expected_request_fingerprint = (
                store_module._sha256(
                    {
                        "project": json_value(original_raw),
                        "building": json_value(recipe),
                    }
                )
                if provider_input_migrations
                else create_request_fingerprint(initial_project, recipe)
            )
            if (
                not is_sha256(original_request_fingerprint)
                or original_request_fingerprint
                != expected_request_fingerprint
            ):
                raise ValueError("metadata original request fingerprint is invalid")
            if definition_fingerprint != building_definition_fingerprint(recipe):
                raise ValueError("metadata building definition fingerprint is invalid")
            return (
                recipe,
                original_request_fingerprint,
                initial_project,
                {
                    "schema_version": schema_version,
                    "compilation_state": compilation_state,
                    "definition_fingerprint": definition_fingerprint,
                    "provider_input_migrations": provider_input_migrations,
                },
            )
        except RecordError as exc:
            raise RecordError("metadata_integrity_error", "refined project metadata is missing or invalid") from exc
        except (OSError, ValueError, KeyError) as exc:
            raise RecordError("metadata_integrity_error", "refined project metadata is missing or invalid") from exc


def transaction_state_index(value: object) -> int:
    if not isinstance(value, str) or value not in CREATE_STATES:
        raise ValueError("create transaction state is invalid")
    return CREATE_STATES.index(value)


def validate_create_transaction(value: Mapping[str, object], project_id: str) -> None:
    require_exact_keys(
        value,
        frozenset(
            {
                "schema_version",
                "project_id",
                "request_fingerprint",
                "expected_artifact_fingerprint",
                "state",
            }
        ),
        "create transaction",
    )
    if value["schema_version"] != CREATE_TRANSACTION_SCHEMA_VERSION:
        raise ValueError("create transaction schema is invalid")
    if value["project_id"] != project_id:
        raise ValueError("create transaction project identity is invalid")
    if not is_sha256(value["request_fingerprint"]) or not is_sha256(value["expected_artifact_fingerprint"]):
        raise ValueError("create transaction fingerprint is invalid")
    transaction_state_index(value["state"])
