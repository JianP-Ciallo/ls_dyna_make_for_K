"""Closed HTTP adapter for the isolated Phase 18F refined-blast workspace.

The browser only receives JSON-safe views.  Project normalization, validation,
preview and package assembly remain owned by :mod:`lsprepost_mcp.refined_blast`.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import threading
import time
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterator

from lsprepost_mcp.assessment_result_source import (
    register_assessment_result_source,
)
from lsprepost_mcp.config import JSONDict, WORKSPACE_DIR
from lsprepost_mcp.damage_assessment_semantics import build_assessment_semantics
from lsprepost_mcp.refined_blast.contracts import (
    RefinedBlastProject,
    ScenarioDraft,
    normalize_refined_blast_project,
    normalize_scenario_draft,
    default_scenario_draft,
    scenario_draft_ui_schema,
)
from lsprepost_mcp.refined_blast.presets import list_refined_blast_presets
from lsprepost_mcp.refined_blast.preview import (
    build_lightweight_refined_blast_preview,
)
from lsprepost_mcp.refined_blast.provider_registry import (
    get_load_provider,
    list_load_providers,
)
from lsprepost_mcp.refined_blast.service import (
    RefinedBlastService,
    validate_public_package,
)
from lsprepost_mcp.refined_blast.project_repository import ProjectRepository
from lsprepost_mcp.refined_blast.generated_records import GeneratedArtifactIndex
from lsprepost_mcp.refined_blast.record_contract import RecordError
from lsprepost_mcp.refined_blast.record_contract import (
    is_sha256 as _is_sha256,
    require_exact_keys as _require_exact_keys,
    require_allowed_keys as _require_allowed_keys,
    require_mapping as _mapping,
    optional_mapping as _optional_mapping,
    optional_string as _optional_string,
    nonempty_string as _nonempty_string,
    positive_revision as _positive_revision,
    sequence_or_default as _sequence_or_default,
    json_value as _json_value,
)
from lsprepost_mcp.refined_blast.project_metadata import (
    CLIENT_PROJECT_KEYS as _CLIENT_PROJECT_KEYS,
    METADATA_SCHEMA_VERSION as _METADATA_SCHEMA_VERSION,
    DEFERRED_METADATA_SCHEMA_VERSION as _DEFERRED_METADATA_SCHEMA_VERSION,
    METADATA_NAME as _METADATA_NAME,
    COMPILATION_STATES as _COMPILATION_STATES,
    BUILDING_KEYS as _BUILDING_KEYS,
    building_definition_fingerprint as _building_definition_fingerprint,
    normalize_building_recipe as _normalize_building_recipe,
    initial_project_evidence as _initial_project_evidence,
    create_request_fingerprint as _create_request_fingerprint,
    accepted_provider_input_migrations as _accepted_provider_input_migrations,
    provider_declares_migration as _provider_declares_migration,
)
from lsprepost_mcp.refined_blast.generated_records import (
    GENERATED_INDEX_SCHEMA_VERSION as _GENERATED_INDEX_SCHEMA_VERSION,
    GENERATED_INDEX_NAME as _GENERATED_INDEX_NAME,
    generated_index_records as _generated_index_records,
    safe_generated_path as _safe_generated_path,
    verified_generated_package as _verified_generated_package,
    project_content_fingerprint as _project_content_fingerprint,
    scenario_content_fingerprint as _scenario_content_fingerprint,
)
from lsprepost_mcp.refined_blast.project_repository import (
    transaction_state_index as _transaction_state_index,
    validate_create_transaction as _validate_create_transaction,
)
from lsprepost_mcp.refined_blast.assembler import (
    RefinedBlastPackage,
    assemble_refined_blast_project,
)
from lsprepost_mcp.refined_blast.store import (
    DraftConflictError,
    RefinedBlastStore,
    StoredArtifact,
    StoredProject,
    validate_storage_identifier,
    canonical_fingerprint,
    read_store_json as _read_store_json,
)
from lsprepost_mcp.refined_building.artifacts import BuildingArtifact
from lsprepost_mcp.refined_building.asset_compiler import (
    DetailedBuildingPackage,
    compile_detailed_building_asset,
    generation_options_ui_schema,
)
from lsprepost_mcp.refined_building.solver_blast import compile_solver_blast_deck
from lsprepost_mcp.refined_building.systems import ui_sections_for_structural_system
from lsprepost_mcp.refined_building.asset_resources import list_detailed_building_assets
from lsprepost_mcp.web.damage_assessment_api import (
    ASSESSMENT_REQUEST_KEYS,
    ASSESSMENT_REQUEST_SCHEMA,
    DamageAssessmentWebApi,
)
from lsprepost_mcp.web.http_utils import ApiError
from lsprepost_mcp.web.refined_blast_handoff import (
    configured_action_doctor,
    launch_lsdyna_snapshot,
    open_lsprepost_snapshot,
)
from lsprepost_mcp.web.refined_blast_preview import build_refined_blast_web_preview
from lsprepost_mcp.web.refined_blast_workbench_schema import (
    build_refined_blast_workbench_schema,
)


REFINED_BLAST_API_PREFIX = "/api/refined-building-blast"
_PROJECT_CREATE_KEYS = frozenset({"schema_version", "project", "building"})
_CREATE_SCHEMA_VERSION = "refined_blast_create@1"
_DEFERRED_CREATE_SCHEMA_VERSION = "refined_blast_create@2"
_CREATE_SCHEMA_VERSIONS = frozenset(
    {_CREATE_SCHEMA_VERSION, _DEFERRED_CREATE_SCHEMA_VERSION}
)
_SAVE_KEYS = frozenset({"expected_revision", "draft"})
_REVISION_KEYS = frozenset({"expected_revision"})
_ACKNOWLEDGEMENT_KEYS = frozenset(
    {"expected_revision", "validation_fingerprint", "finding_id"}
)
_ACTION_CONFIRMATION_KEYS = frozenset({
    "action", "scenario_id", "generated_revision", "artifact_fingerprint", "package_fingerprint",
})
_ACTION_INVOKE_KEYS = frozenset({
    "confirmation_nonce", "scenario_id", "generated_revision", "artifact_fingerprint", "package_fingerprint",
})
_EXTERNAL_ACTIONS = frozenset({"open_lsprepost", "launch_lsdyna"})
_ACTION_CONFIRMATION_TTL_S = 5 * 60


class RefinedBlastApi:
    """HTTP operations backed by explicit project and artifact repositories."""

    def __init__(self, root: Path | None = None) -> None:
        self._store = RefinedBlastStore(root or WORKSPACE_DIR / "refined_blast_web")
        self._repository = ProjectRepository(self._store)
        self._index = GeneratedArtifactIndex(self._store)
        self._artifacts: dict[str, BuildingArtifact] = {}
        self._building_packages: dict[str, DetailedBuildingPackage] = {}
        self._services: dict[str, RefinedBlastService] = {}
        self._generated: dict[tuple[str, str, int], StoredArtifact] = {}
        self._action_confirmations: dict[str, JSONDict] = {}
        self._damage_assessment = DamageAssessmentWebApi(self._store)

    def get(self, path: str, query: Mapping[str, Sequence[str]]) -> JSONDict:
        return _call_api(lambda: self._get(path, query))

    def _get(self, path: str, query: Mapping[str, Sequence[str]]) -> JSONDict:
        _require_empty_query(query)
        if path == "/capabilities":
            return self._capabilities()
        if path == "/providers":
            return {"providers": self._capabilities()["providers"]}
        if path == "/assets":
            return {"assets": [_asset_descriptor(row) for row in list_detailed_building_assets()]}
        if path == "/presets":
            return {
                "presets": [
                    {
                        "preset_id": row.preset_id,
                        "version": row.version,
                        "building_systems": list(row.building_systems),
                        "provider_ids": list(row.provider_ids),
                        "status": row.status,
                    }
                    for row in list_refined_blast_presets()
                ]
            }
        segments = _path_segments(path)
        if len(segments) == 2 and segments[0] == "projects":
            project_id = _route_identifier(segments[1], "project_id", path)
            with self._project_read_operation(project_id) as (stored, recipe, metadata):
                return {
                    "project": {
                        **_stored_project_with_metadata(stored, metadata),
                        "building": _json_value(recipe),
                    }
                }
        if (
            len(segments) == 4
            and segments[0] == "projects"
            and segments[2:] == ("assessments", "latest")
        ):
            project_id = _route_identifier(segments[1], "project_id", path)
            with self._project_read_operation(project_id):
                project_dir = self._store.project_directory(project_id)
                return self._damage_assessment.latest(project_dir)
        if len(segments) == 6 and segments[0] == "projects" and segments[2] == "artifacts":
            project_id = _route_identifier(segments[1], "project_id", path)
            scenario_id = _route_identifier(segments[3], "scenario_id", path)
            revision = _revision_token(segments[4])
            return self._artifact_payload(project_id, scenario_id, revision, segments[5])
        raise ApiError(404, "not_found", f"route not found: {path}")

    def post(self, path: str, payload: JSONDict) -> JSONDict:
        return _call_api(lambda: self._post(path, payload))

    def _post(self, path: str, payload: JSONDict) -> JSONDict:
        if path == "/projects":
            return self._create(payload)
        segments = _path_segments(path)
        if len(segments) != 3 or segments[0] != "projects":
            raise ApiError(404, "not_found", f"route not found: {path}")
        project_id = _route_identifier(segments[1], "project_id", path)
        action = segments[2]
        if action == "save":
            return self._save(project_id, payload)
        if action == "validate":
            return self._validate(project_id, payload)
        if action == "preview":
            return self._preview(project_id, payload)
        if action == "acknowledgements":
            return self._acknowledge(project_id, payload)
        if action == "generate":
            return self._generate(project_id, payload)
        if action == "action-confirmations":
            return self._issue_action_confirmation(project_id, payload)
        if action == "open-lsprepost":
            return self._run_external_action(project_id, "open_lsprepost", payload)
        if action == "launch-lsdyna":
            return self._run_external_action(project_id, "launch_lsdyna", payload)
        if action == "assess-latest-run":
            return self._assess_latest_run(project_id, payload)
        raise ApiError(404, "not_found", f"route not found: {path}")

    def _assess_latest_run(self, project_id: str, payload: JSONDict) -> JSONDict:
        _require_exact_keys(
            payload,
            ASSESSMENT_REQUEST_KEYS,
            "damage assessment request",
        )
        if payload["schema_version"] != ASSESSMENT_REQUEST_SCHEMA:
            raise ApiError(
                400,
                "invalid_request",
                "damage assessment request schema_version is unsupported",
            )
        request_identity = {
            key: payload[key]
            for key in ASSESSMENT_REQUEST_KEYS
            if key != "schema_version"
        }
        with self._project_record_operation(project_id) as (stored, _, _):
            identity, _package = self._current_generated_package(
                project_id,
                stored,
                request_identity,
            )
            project_dir = self._store.project_directory(project_id)
            return self._damage_assessment.assess_current(
                project_id=project_id,
                case_id=str(identity["scenario_id"]),
                project_dir=project_dir,
                identity=identity,
            )

    def assessment_artifact(
        self,
        path: str,
        query: Mapping[str, Sequence[str]],
    ) -> tuple[int, dict[str, str], bytes]:
        return _call_api(  # type: ignore[return-value]
            lambda: self._assessment_artifact(path, query)
        )

    def _assessment_artifact(
        self,
        path: str,
        query: Mapping[str, Sequence[str]],
    ) -> tuple[int, dict[str, str], bytes]:
        _require_empty_query(query)
        segments = _path_segments(path)
        if (
            len(segments) != 6
            or segments[0] != "projects"
            or segments[2] != "assessments"
            or segments[4] != "artifacts"
        ):
            raise ApiError(404, "not_found", f"route not found: {path}")
        project_id = _route_identifier(segments[1], "project_id", path)
        assessment_id = _route_identifier(
            segments[3], "assessment_id", path
        )
        artifact_name = segments[5]
        with self._project_read_operation(project_id):
            project_dir = self._store.project_directory(project_id)
            return self._damage_assessment.artifact(
                project_dir=project_dir,
                assessment_id=assessment_id,
                artifact_name=artifact_name,
            )

    def _capabilities(self) -> JSONDict:
        providers: list[JSONDict] = []
        for descriptor in list_load_providers():
            provider = get_load_provider(descriptor.provider_id)
            providers.append(
                {
                    "provider_id": descriptor.provider_id,
                    "supported_scenario_kinds": list(descriptor.supported_scenario_kinds),
                    "schema_version": descriptor.schema_version,
                    "implementation_bound": True,
                    "schema": _json_value(provider.schema()),
                    "input_schema": _json_value(provider.schema()["input_schema"]),
                    "default_input": _json_value(provider.default_input()),
                    "capabilities": _json_value(provider.capabilities()),
                }
            )
        scenario_schema = scenario_draft_ui_schema(
            {
                descriptor.provider_id: _json_value(
                    get_load_provider(descriptor.provider_id).schema()["input_schema"]
                )
                for descriptor in list_load_providers()
            }
        )
        return {
            "workspace_type": "refined_building_blast",
            "schema_version": "refined_building_blast@1",
            "unit_system": "SI_m_s_kg_N_Pa",
            "providers": providers,
            "workbench_schema": build_refined_blast_workbench_schema(),
            "scenario_draft_schema": scenario_schema,
            "default_scenario_draft": _json_value(default_scenario_draft()),
            "solver_ready": False,
            "requires_project_review": True,
        }

    def _create(self, payload: JSONDict) -> JSONDict:
        _reject_legacy_payload(payload)
        _require_exact_keys(payload, _PROJECT_CREATE_KEYS, "create payload")
        create_version = payload["schema_version"]
        if create_version not in _CREATE_SCHEMA_VERSIONS:
            raise ApiError(
                400,
                "invalid_request",
                "create schema_version must be 'refined_blast_create@1' or "
                "'refined_blast_create@2'",
            )
        client_project = _mapping(payload["project"], "project")
        _require_exact_keys(client_project, _CLIENT_PROJECT_KEYS, "create project")
        if client_project.get("schema_version") != "refined_building_blast@1":
            raise ApiError(400, "invalid_request", "create project schema_version must be 'refined_building_blast@1'")
        recipe = _normalize_building_recipe(_mapping(payload["building"], "building"))
        deferred = create_version == _DEFERRED_CREATE_SCHEMA_VERSION
        artifact = None if deferred else _compile_building(recipe)
        definition_fingerprint = _building_definition_fingerprint(recipe)
        project_raw = dict(client_project)
        project_raw["building_reference"] = {
            "asset_id": recipe["asset_id"] if artifact is None else artifact.asset_id
        }
        project_raw["building_artifact_fingerprint"] = (
            definition_fingerprint if artifact is None else artifact.fingerprint
        )
        project = normalize_refined_blast_project(project_raw)
        if len(project.scenario_set) != 1:
            raise ApiError(400, "invalid_request", "web project creation requires exactly one scenario")
        try:
            with self._store.project_transaction(project.project_id):
                compilation_state = "pending" if deferred else "compiled"
                stored = self._repository.create(
                    project,
                    recipe,
                    compilation_state=compilation_state,
                    definition_fingerprint=definition_fingerprint,
                )
                if artifact is not None:
                    stored, _, _ = self._verified_project_context(project.project_id)
                    self._artifacts[stored.project_id] = artifact
                    self._services[stored.project_id] = RefinedBlastService(
                        self._store, stored.project_id, artifact
                    )
                return {
                    "project": _stored_project_with_metadata(
                        stored,
                        {
                            "compilation_state": compilation_state,
                            "definition_fingerprint": definition_fingerprint,
                        },
                    )
                }
        except (OSError, ValueError) as exc:
            raise ApiError(
                409,
                "project_creation_incomplete",
                "refined project creation is incomplete; retry the same create request to recover",
            ) from exc

    def _save(self, project_id: str, payload: JSONDict) -> JSONDict:
        _reject_legacy_payload(payload)
        _require_exact_keys(payload, _SAVE_KEYS, "save payload")
        with self._project_read_operation(project_id) as (current, _, metadata):
            if len(current.project.scenario_set) != 1:
                raise ApiError(409, "scenario_set_unsupported", "web save requires exactly one current scenario")
            draft = normalize_scenario_draft(_mapping(payload["draft"], "draft"))
            if draft.scenario_id != current.project.scenario_set[0].scenario_id:
                raise ApiError(400, "scenario_identity_mismatch", "save must replace the current scenario with the same scenario_id")
            stored = self._store.save_draft(
                project_id,
                draft,
                _positive_revision(payload["expected_revision"]),
            )
            return {"project": _stored_project_with_metadata(stored, metadata)}

    def _validate(self, project_id: str, payload: JSONDict) -> JSONDict:
        _require_exact_keys(payload, _REVISION_KEYS, "validate payload")
        if self._uses_deferred_lifecycle(project_id):
            with self._project_record_operation(project_id) as (stored, _, _):
                validation = _configuration_validation_payload(
                    stored,
                    _positive_revision(payload["expected_revision"]),
                )
                return {"validation": validation}
        with self._project_operation(project_id) as (_, _, _, service):
            validation = service.validate(
                expected_revision=_positive_revision(payload["expected_revision"])
            )
            result = _validation_payload(validation)
            result["generation_gate"] = service.generation_gate(validation)
            return {"validation": result}

    def _preview(self, project_id: str, payload: JSONDict) -> JSONDict:
        _require_exact_keys(payload, _REVISION_KEYS, "preview payload")
        if self._uses_deferred_lifecycle(project_id):
            revision = _positive_revision(payload["expected_revision"])
            with self._project_record_operation(project_id) as (stored, recipe, _):
                _require_current_revision(stored, revision)
                _configuration_validation_payload(stored, revision)
                preview = build_lightweight_refined_blast_preview(
                    stored.project,
                    recipe,
                    revision=revision,
                )
                return {"preview": _preview_payload(preview)}
        with self._project_operation(project_id) as (_, _, _, service):
            preview = service.preview(
                expected_revision=_positive_revision(payload["expected_revision"])
            )
            return {"preview": _preview_payload(preview)}

    def _acknowledge(self, project_id: str, payload: JSONDict) -> JSONDict:
        _require_exact_keys(payload, _ACKNOWLEDGEMENT_KEYS, "acknowledgement payload")
        revision = _positive_revision(payload["expected_revision"])
        with self._project_operation(project_id) as (_, _, _, service):
            validation = service.validate(expected_revision=revision)
            fingerprint = _nonempty_string(payload["validation_fingerprint"], "validation_fingerprint")
            if fingerprint != validation.fingerprint:
                raise ApiError(409, "validation_conflict", "validation fingerprint is no longer current")
            record = service.acknowledge(
                validation, _nonempty_string(payload["finding_id"], "finding_id")
            )
            return {
                "acknowledgement": {
                    "finding_id": record.finding_id,
                    "finding_content_hash": record.finding_content_hash,
                    "project_revision": record.project_revision,
                    "validation_fingerprint": record.validation_fingerprint,
                    "acknowledged_at": record.acknowledged_at,
                },
                "generation_gate": service.generation_gate(validation),
            }

    def _generate(self, project_id: str, payload: JSONDict) -> JSONDict:
        _require_exact_keys(payload, _REVISION_KEYS, "generate payload")
        revision = _positive_revision(payload["expected_revision"])
        if self._uses_deferred_lifecycle(project_id):
            return self._generate_deferred(project_id, revision)
        with self._project_operation(project_id) as (stored, recipe, artifact_view, service):
            scenario = stored.project.scenario_set[0]
            solver_complete = (
                scenario.load_provider.get("provider_id") == "solver_complete_ale_fsi"
            )
            if solver_complete:
                validation = service.validate(expected_revision=revision)
                gate = service.generation_gate(validation)
                if gate["blocking_error_ids"]:
                    raise ValueError("blocking validation errors prevent generation")
                if gate["unacknowledged_warning_ids"]:
                    raise ValueError("unacknowledged warning prevents generation")
                detailed = _compile_building_package(recipe)
                if (
                    len(detailed.artifacts) != 1
                    or detailed.artifacts[0].fingerprint
                    != artifact_view.fingerprint
                ):
                    raise ApiError(
                        409,
                        "project_integrity_error",
                        "solver-complete generation did not reproduce the stored building artifact",
                    )
                package = _compile_solver_complete_web_package(detailed, scenario)
            else:
                package = service.generate(expected_revision=revision)
            scenario_id = stored.project.scenario_set[0].scenario_id
            artifact = self._store.commit_generated_package(
                project_id,
                scenario_id,
                _package_payload(package),
                revision,
                before_project_commit=lambda candidate, projected: self._index.publish(
                    candidate, package.package_fingerprint, projected
                ),
            )
            self._generated[(project_id, scenario_id, artifact.revision)] = artifact
            return {
                "artifact": _stored_artifact(artifact),
                "package_fingerprint": package.package_fingerprint,
                "solver_complete": solver_complete,
                "solver_ready": False,
                "requires_project_review": True,
                "external_program_started": False,
            }

    def _generate_deferred(self, project_id: str, revision: int) -> JSONDict:
        with self._store.project_transaction(project_id):
            stored, recipe, metadata = self._repository.verified_record(project_id)
            _require_current_revision(stored, revision)
            detailed = self._building_packages.get(project_id)
            if detailed is None:
                detailed = _compile_building_package(recipe)
            if len(detailed.artifacts) != 1:
                raise ApiError(
                    400,
                    "unsupported_building_package",
                    "one refined blast project requires exactly one building artifact",
                )
            artifact_view = detailed.artifacts[0]
            if metadata["compilation_state"] == "pending":
                stored = self._repository.materialize_building(
                    stored,
                    metadata,
                    artifact_view,
                    selected_resource_id=str(recipe["asset_id"]),
                )
            elif (
                stored.project.building_artifact_fingerprint
                != artifact_view.fingerprint
            ):
                raise ApiError(
                    409,
                    "project_integrity_error",
                    "compiled building no longer matches the persisted recipe",
                )
            self._building_packages[project_id] = detailed
            self._artifacts[project_id] = artifact_view
            service = RefinedBlastService(self._store, project_id, artifact_view)
            self._services[project_id] = service
            scenario = stored.project.scenario_set[0]
            solver_complete = (
                scenario.load_provider.get("provider_id")
                == "solver_complete_ale_fsi"
            )
            if solver_complete:
                package = _compile_solver_complete_web_package(
                    detailed, scenario
                )
            else:
                full_validation = service.validate(expected_revision=revision)
                if full_validation.errors:
                    raise ValueError(
                        "blocking detailed-building validation errors prevent generation"
                    )
                package = assemble_refined_blast_project(
                    stored.project, artifact_view
                )
                validate_public_package(
                    package,
                    self._store,
                    project_id,
                    artifact_view,
                    expected_revision=revision,
                )
            scenario_id = scenario.scenario_id
            generated = self._store.commit_generated_package(
                project_id,
                scenario_id,
                _package_payload(package),
                revision,
                before_project_commit=lambda candidate, projected: self._index.publish(
                    candidate, package.package_fingerprint, projected
                ),
            )
            self._generated[
                (project_id, scenario_id, generated.revision)
            ] = generated
            return {
                "artifact": _stored_artifact(generated),
                "package_fingerprint": package.package_fingerprint,
                "solver_complete": solver_complete,
                "solver_ready": False,
                "requires_project_review": True,
                "external_program_started": False,
            }


    def _issue_action_confirmation(self, project_id: str, payload: JSONDict) -> JSONDict:
        _require_exact_keys(payload, _ACTION_CONFIRMATION_KEYS, "action confirmation payload")
        action = _external_action(payload["action"])
        with self._project_operation(project_id) as (stored, _, _, _):
            identity, _package = self._current_generated_package(project_id, stored, payload)
            nonce = uuid.uuid4().hex
            self._purge_expired_action_confirmations()
            self._action_confirmations[_confirmation_digest(nonce)] = {
                "binding": _confirmation_binding(action, project_id, identity),
                "expires_at": time.monotonic() + _ACTION_CONFIRMATION_TTL_S,
            }
            return {"confirmation": {"nonce": nonce, "action": action, "project_id": project_id, **identity}}

    def _run_external_action(self, project_id: str, action: str, payload: JSONDict) -> JSONDict:
        _require_exact_keys(payload, _ACTION_INVOKE_KEYS, "external action payload")
        with self._project_operation(project_id) as (stored, _, _, _):
            identity, package = self._current_generated_package(project_id, stored, payload)
            nonce = _nonempty_string(payload["confirmation_nonce"], "confirmation_nonce")
            confirmation = self._action_confirmations.pop(_confirmation_digest(nonce), None)
            if confirmation is None or confirmation.get("expires_at", 0.0) < time.monotonic() or confirmation.get("binding") != _confirmation_binding(action, project_id, identity):
                raise ApiError(409, "confirmation_invalid", "confirmation is missing, stale, wrong-action, or already consumed")
            if not self._external_action_doctor(action):
                raise ApiError(409, "external_program_unavailable", "configured external program is unavailable")
            snapshot, snapshot_hashes = self._materialize_action_snapshot(
                project_id, action, identity, package
            )
            try:
                snapshot = self._store.verify_action_snapshot(
                    project_id, snapshot, snapshot_hashes
                )
            except (OSError, ValueError) as exc:
                raise ApiError(
                    409,
                    "artifact_integrity_error",
                    "action snapshot changed before external delegation",
                ) from exc
            try:
                delegated = self._delegate_lsprepost_snapshot(snapshot / "main.k") if action == "open_lsprepost" else self._delegate_lsdyna_snapshot(snapshot, snapshot / "main.k")
            except Exception as exc:
                raise ApiError(409, "external_handoff_failed", "configured external handoff did not start") from exc
            started = bool(isinstance(delegated, Mapping) and delegated.get("started") is True)
            result: JSONDict = {
                "action": action,
                **identity,
                "external_program_started": started,
                "solver_ready": False,
                "requires_project_review": True,
            }
            # Eligibility comes from the verified package, not mutable file existence.
            # Legacy handoffs remain independent of the optional assessment module.
            if (
                action == "launch_lsdyna"
                and isinstance(delegated, Mapping)
                and "assessment_semantics.json" in package.files
            ):
                run_record = delegated.get("record")
                if (
                    isinstance(run_record, Mapping)
                    and run_record.get("status")
                    in {"completed", "solver_failed", "timed_out"}
                ):
                    try:
                        result["damage_assessment_source"] = (
                            register_assessment_result_source(
                                store=self._store,
                                project_id=project_id,
                                snapshot=snapshot,
                                identity=identity,
                                run_record=run_record,
                            )
                        )
                    except (OSError, TypeError, ValueError) as exc:
                        raise ApiError(
                            409,
                            "assessment_source_registration_failed",
                            "terminal solver result could not be registered for assessment",
                        ) from exc
            return result

    def _purge_expired_action_confirmations(self) -> None:
        now = time.monotonic()
        for digest, record in tuple(self._action_confirmations.items()):
            if record.get("expires_at", 0.0) < now:
                self._action_confirmations.pop(digest, None)

    def _external_action_doctor(self, action: str) -> bool:
        return configured_action_doctor(action)

    def _current_generated_package(self, project_id: str, stored: StoredProject, payload: Mapping[str, object]) -> tuple[JSONDict, RefinedBlastPackage]:
        scenario_id = _route_identifier(payload["scenario_id"], "scenario_id", "/external-action")
        revision = _positive_revision(payload["generated_revision"])
        artifact_fingerprint = _nonempty_string(payload["artifact_fingerprint"], "artifact_fingerprint")
        package_fingerprint = _nonempty_string(payload["package_fingerprint"], "package_fingerprint")
        if scenario_id not in {row.scenario_id for row in stored.project.scenario_set}:
            raise ApiError(409, "artifact_stale", "generated scenario is no longer current")
        raw_index = _read_store_json(self._index.path(project_id), self._store)
        rows = [row for row in _generated_index_records(raw_index, project_id) if row["scenario_id"] == scenario_id and row["revision"] == revision and row["store_artifact_fingerprint"] == artifact_fingerprint and row["package_fingerprint"] == package_fingerprint]
        if len(rows) != 1 or stored.revision != revision:
            raise ApiError(409, "artifact_stale", "generated package is not the current project revision")
        row = rows[0]
        if row["project_content_fingerprint"] != _project_content_fingerprint(stored) or row["scenario_content_fingerprint"] != _scenario_content_fingerprint(stored, scenario_id):
            raise ApiError(409, "artifact_stale", "generated package does not match current project content")
        raw = _read_store_json(
            _safe_generated_path(
                row["relative_path"],
                self._store,
                project_id,
                scenario_id,
                revision,
                artifact_fingerprint,
            ),
            self._store,
        )
        package = _verified_generated_package(raw, project_id=project_id, scenario_id=scenario_id, revision=revision, store_fingerprint=artifact_fingerprint, package_fingerprint=package_fingerprint)
        return {"scenario_id": scenario_id, "generated_revision": revision, "artifact_fingerprint": artifact_fingerprint, "package_fingerprint": package_fingerprint}, package

    def _materialize_action_snapshot(
        self,
        project_id: str,
        action: str,
        identity: Mapping[str, object],
        package: RefinedBlastPackage,
    ) -> tuple[Path, Mapping[str, str]]:
        name = f"action-{action}-{identity['generated_revision']}-{uuid.uuid4().hex}"
        files = dict(package.files)
        if "model.k" in files:
            files["main.k"] = files["model.k"]
        elif "main.k" in files:
            files["model.k"] = files["main.k"]
        else:
            raise ApiError(
                409,
                "artifact_integrity_error",
                "generated package lacks main.k/model.k",
            )
        files["model.json"] = json.dumps(
            {
                "status": "research",
                "solver_ready": False,
                "requires_project_review": True,
                "action": action,
                "identity": dict(identity),
            },
            sort_keys=True,
        ).encode("utf-8")
        files["action.json"] = json.dumps(
            {
                "schema_version": "phase18f_action_snapshot@1",
                "action": action,
                "identity": dict(identity),
                "package_fingerprint": package.package_fingerprint,
                "package_manifest": _json_value(package.manifest),
                "package_files": [
                    {
                        "path": path,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "byte_count": len(content),
                    }
                    for path, content in package.files.items()
                ],
                "handoff_input": "main.k",
                "solver_ready": False,
                "requires_project_review": True,
            },
            sort_keys=True,
        ).encode("utf-8")
        try:
            snapshot = self._store.materialize_action_snapshot(
                project_id, name, files
            )
        except (OSError, ValueError) as exc:
            raise ApiError(
                409,
                "artifact_integrity_error",
                "generated package snapshot could not be materialized safely",
            ) from exc
        return snapshot, {
            path: hashlib.sha256(content).hexdigest()
            for path, content in files.items()
        }

    def _delegate_lsprepost_snapshot(self, model: Path) -> JSONDict:
        return open_lsprepost_snapshot(model)

    def _delegate_lsdyna_snapshot(self, snapshot: Path, model: Path) -> JSONDict:
        return launch_lsdyna_snapshot(snapshot, model)

    @contextmanager
    def _project_record_operation(
        self, project_id: str
    ) -> Iterator[
        tuple[StoredProject, Mapping[str, object], Mapping[str, object]]
    ]:
        """Yield verified persisted authority without compiling a building."""

        with self._store.project_transaction(project_id):
            yield self._repository.verified_record(project_id)

    @contextmanager
    def _project_read_operation(
        self, project_id: str
    ) -> Iterator[
        tuple[StoredProject, Mapping[str, object], Mapping[str, object]]
    ]:
        """Use deferred reads only for projects created under the v3 lifecycle."""

        if self._uses_deferred_lifecycle(project_id):
            with self._project_record_operation(project_id) as operation:
                yield operation
            return
        with self._project_operation(project_id) as (stored, recipe, _, _):
            _, _, _, metadata = self._repository.read_metadata_evidence(stored)
            yield stored, recipe, metadata

    def _uses_deferred_lifecycle(self, project_id: str) -> bool:
        try:
            raw = _read_store_json(self._repository.metadata_path(project_id), self._store)
        except (FileNotFoundError, OSError, ValueError):
            return False
        return raw.get("schema_version") == _DEFERRED_METADATA_SCHEMA_VERSION

    @contextmanager
    def _project_operation(
        self, project_id: str
    ) -> Iterator[
        tuple[
            StoredProject,
            Mapping[str, object],
            BuildingArtifact,
            RefinedBlastService,
        ]
    ]:
        """Yield verified project authority while its Store lease remains held."""

        with self._store.project_transaction(project_id):
            stored, recipe, artifact = self._verified_project_context(project_id)
            service = self._services.get(project_id)
            if service is None or service._artifact.fingerprint != artifact.fingerprint:
                service = RefinedBlastService(self._store, project_id, artifact)
                self._services[project_id] = service
            self._artifacts[project_id] = artifact
            yield stored, recipe, artifact, service


    def _verified_project_context(
        self, project_id: str
    ) -> tuple[StoredProject, Mapping[str, object], BuildingArtifact]:
        """Compile and verify a building for operations that require the artifact."""

        stored, recipe, metadata = self._repository.verified_record(project_id)
        if metadata["compilation_state"] != "compiled":
            raise ApiError(
                409,
                "building_compilation_pending",
                "the detailed building is pending generation",
            )
        expected_artifact_fingerprint = stored.project.building_artifact_fingerprint
        artifact = self._artifacts.get(project_id)
        if artifact is None or artifact.fingerprint != expected_artifact_fingerprint:
            artifact = _compile_building(recipe)
        if (
            artifact.asset_id != stored.project.building_reference.get("asset_id")
            or artifact.fingerprint != expected_artifact_fingerprint
        ):
            raise ApiError(
                409,
                "project_integrity_error",
                "persisted building recipe does not reproduce the stored artifact",
            )
        return stored, recipe, artifact


    def _artifact_payload(
        self, project_id: str, scenario_id: str, revision: int, package_fingerprint: str
    ) -> JSONDict:
        if not _is_sha256(package_fingerprint):
            raise ApiError(404, "not_found", "package fingerprint is invalid")
        try:
            with self._project_operation(project_id) as (stored, _, _, _):
                if scenario_id not in {row.scenario_id for row in stored.project.scenario_set}:
                    raise ApiError(409, "artifact_stale", "generated scenario is no longer present in the current project")
                raw_index = _read_store_json(self._index.path(project_id), self._store)
                matches = [
                    row for row in _generated_index_records(raw_index, project_id)
                    if row["scenario_id"] == scenario_id
                    and row["revision"] == revision
                    and row["package_fingerprint"] == package_fingerprint
                ]
                if len(matches) != 1:
                    raise ApiError(404, "not_found", "generated artifact is not available")
                record = matches[0]
                if (
                    stored.revision != record["generated_revision"]
                    or revision != record["generated_revision"]
                    or
                    record["project_content_fingerprint"] != _project_content_fingerprint(stored)
                    or record["scenario_content_fingerprint"] != _scenario_content_fingerprint(stored, scenario_id)
                ):
                    raise ApiError(409, "artifact_stale", "generated artifact does not match the current project content")
                path = _safe_generated_path(
                    record["relative_path"],
                    self._store,
                    project_id,
                    scenario_id,
                    revision,
                    record["store_artifact_fingerprint"],
                )
                raw = _read_store_json(path, self._store)
                package = _verified_generated_package(
                    raw,
                    project_id=project_id,
                    scenario_id=scenario_id,
                    revision=revision,
                    store_fingerprint=record["store_artifact_fingerprint"],
                    package_fingerprint=package_fingerprint,
                )
                return {
                    "artifact": {
                        "project_id": project_id,
                        "scenario_id": scenario_id,
                        "revision": revision,
                        "fingerprint": record["store_artifact_fingerprint"],
                    },
                    "package": _package_payload(package),
                }
        except (ApiError, RecordError) as exc:
            if exc.code in {
                "not_found", "artifact_stale", "project_integrity_error",
                "metadata_integrity_error", "transaction_integrity_error",
                "project_creation_incomplete",
            }:
                raise
            raise ApiError(409, "artifact_integrity_error", "generated artifact failed integrity verification") from exc
        except (OSError, ValueError, KeyError) as exc:
            raise ApiError(409, "artifact_integrity_error", "generated artifact failed integrity verification") from exc


_DEFAULT_API: RefinedBlastApi | None = None
_DEFAULT_API_LOCK = threading.RLock()


def _default_api() -> RefinedBlastApi:
    global _DEFAULT_API
    with _DEFAULT_API_LOCK:
        if _DEFAULT_API is None:
            _DEFAULT_API = RefinedBlastApi()
        return _DEFAULT_API


def handle_refined_blast_get(path: str, query: Mapping[str, Sequence[str]]) -> JSONDict:
    """Handle an API-prefix-relative GET path using the isolated default adapter."""

    return _default_api().get(path, query)


def handle_refined_blast_artifact_get(
    path: str,
    query: Mapping[str, Sequence[str]],
) -> tuple[int, dict[str, str], bytes] | None:
    """Serve only the dedicated registered-assessment artifact route."""

    try:
        segments = _path_segments(path)
    except ApiError:
        return None
    if (
        len(segments) != 6
        or segments[0] != "projects"
        or segments[2] != "assessments"
        or segments[4] != "artifacts"
    ):
        return None
    return _default_api().assessment_artifact(path, query)


def handle_refined_blast_post(path: str, payload: JSONDict) -> JSONDict:
    """Handle an API-prefix-relative POST path using the isolated default adapter."""

    return _default_api().post(path, payload)


def _call_api(operation: Any) -> JSONDict:
    try:
        return operation()
    except ApiError:
        raise
    except RecordError as exc:
        status = 400 if exc.code in {"unknown_field", "missing_field", "invalid_request"} else 409
        raise ApiError(status, exc.code, exc.message) from exc
    except DraftConflictError as exc:
        raise ApiError(409, "revision_conflict", str(exc)) from exc
    except FileNotFoundError as exc:
        raise ApiError(404, "not_found", "requested refined blast resource was not found") from exc
    except OSError as exc:
        raise ApiError(409, "storage_error", "refined blast storage is unavailable") from exc
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "invalid_request", "request violates the refined blast API contract") from exc


def _compile_building_package(value: Mapping[str, object]) -> DetailedBuildingPackage:
    value = _normalize_building_recipe(value)
    asset_id = _nonempty_string(value["asset_id"], "building.asset_id")
    package = compile_detailed_building_asset(
        asset_id,
        legacy_geometry=_optional_mapping(value.get("legacy_geometry"), "building.legacy_geometry"),
        origin_m=_sequence_or_default(value.get("origin_m"), "building.origin_m", (0.0, 0.0, 0.0)),
        rotation_deg=_sequence_or_default(value.get("rotation_deg"), "building.rotation_deg", (0.0, 0.0, 0.0)),
        structural_system=_optional_string(value.get("structural_system"), "building.structural_system"),
        fidelity_profile=_optional_string(value.get("fidelity_profile"), "building.fidelity_profile") or "blast_response",
        mesh_profile=_optional_string(value.get("mesh_profile"), "building.mesh_profile") or "standard",
        generation_options=_optional_mapping(value.get("generation_options"), "building.generation_options"),
        material_overrides=_optional_mapping(value.get("material_overrides"), "building.material_overrides"),
    )
    if len(package.artifacts) != 1:
        raise ApiError(400, "unsupported_building_package", "one refined blast project requires exactly one building artifact")
    return package


def _compile_building(value: Mapping[str, object]) -> BuildingArtifact:
    return _compile_building_package(value).artifacts[0]


def _compile_solver_complete_web_package(
    detailed: DetailedBuildingPackage,
    scenario: ScenarioDraft,
) -> RefinedBlastPackage:
    if len(detailed.artifacts) != 1:
        raise ApiError(
            400,
            "unsupported_building_package",
            "one refined blast project requires exactly one building artifact",
        )
    artifact = detailed.artifacts[0]
    provider_input = scenario.load_provider.get("provider_input")
    if not isinstance(provider_input, Mapping):
        raise ApiError(400, "invalid_request", "solver-complete provider input is invalid")
    with tempfile.TemporaryDirectory(prefix="phase18-solver-complete-") as raw_dir:
        directory = Path(raw_dir)
        compilation = compile_solver_blast_deck(detailed, provider_input, directory)
        model = (directory / "model.k").read_bytes()
        deck_manifest = (directory / "manifest.json").read_bytes()
        semantics = json.dumps(
            build_assessment_semantics(detailed, compilation),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    manifest_sha = hashlib.sha256(deck_manifest).hexdigest()
    semantics_sha = hashlib.sha256(semantics).hexdigest()
    return RefinedBlastPackage(
        files={
            "model.k": model,
            "manifest.json": deck_manifest,
            "assessment_semantics.json": semantics,
        },
        manifest={
            "schema_version": "phase18.solver_blast.web_package_manifest@1",
            "provider_id": "solver_complete_ale_fsi",
            "scenario_id": scenario.scenario_id,
            "scenario_kind": scenario.scenario_kind,
            "building_artifact_fingerprint": artifact.fingerprint,
            "building_package_fingerprint": detailed.package_fingerprint,
            "provider_input_fingerprint": canonical_fingerprint(_json_value(provider_input)),
            "scene_fingerprint": compilation.evidence.scene_fingerprint,
            "model_sha256": compilation.evidence.model_sha256,
            "manifest_sha256": manifest_sha,
            "assessment_semantics_sha256": semantics_sha,
            "node_count": compilation.validation.node_count,
            "element_count": compilation.validation.element_count,
            "ale_node_count": compilation.validation.ale_node_count,
            "ale_element_count": compilation.validation.ale_element_count,
            "fsi_segment_count": compilation.validation.fsi_segment_count,
            "charge_position_m": compilation.validation.charge_position_m,
            "termination_time_s": compilation.validation.termination_time_s,
            "static_validation_ok": compilation.validation.ok,
            "solver_complete": True,
            "solver_ready": False,
            "requires_project_review": True,
            "engineering_validated": False,
            "external_program_started": False,
        },
        symbol_to_numeric_id={},
        building_artifact_fingerprint=artifact.fingerprint,
    )


def _path_segments(path: str) -> tuple[str, ...]:
    if not isinstance(path, str) or not path.startswith("/") or path.endswith("/"):
        raise ApiError(404, "not_found", f"route not found: {path}")
    parts = tuple(path[1:].split("/"))
    if not parts or any(not part for part in parts):
        raise ApiError(404, "not_found", f"route not found: {path}")
    return parts


def _external_action(value: object) -> str:
    action = _nonempty_string(value, "action")
    if action not in _EXTERNAL_ACTIONS:
        raise ApiError(400, "invalid_request", "action is not a supported refined external action")
    return action


def _confirmation_digest(nonce: str) -> str:
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def _confirmation_binding(action: str, project_id: str, identity: Mapping[str, object]) -> str:
    """Hash every immutable authorization field retained with a one-time nonce."""

    return hashlib.sha256(json.dumps({"action": action, "project_id": project_id, **identity}, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _route_identifier(value: object, label: str, path: str) -> str:
    try:
        return validate_storage_identifier(value, label)
    except ValueError as exc:
        raise ApiError(404, "not_found", f"route not found: {path}") from exc


def _require_empty_query(query: Mapping[str, Sequence[str]]) -> None:
    if not isinstance(query, Mapping):
        raise ApiError(400, "invalid_request", "query must be a mapping")
    if query:
        raise ApiError(400, "unknown_query", f"unknown query field: {next(iter(query))}")


def _reject_legacy_payload(payload: Mapping[str, object]) -> None:
    if "project_name" in payload or payload.get("scene_id") is not None:
        raise ApiError(400, "project_type_mismatch", "legacy project payload is not accepted by refined blast routes")


def is_refined_blast_payload(payload: Mapping[str, object]) -> bool:
    """Return true only for an explicit Phase 18E/18F project root payload."""

    project = payload.get("project") if isinstance(payload, Mapping) else None
    if not isinstance(project, Mapping):
        project = payload
    return isinstance(project, Mapping) and project.get("schema_version") == "refined_building_blast@1"


def _require_current_revision(stored: StoredProject, expected_revision: int) -> None:
    if stored.revision != expected_revision:
        raise DraftConflictError(
            f"expected revision {expected_revision}, found {stored.revision}"
        )


def _configuration_validation_payload(
    stored: StoredProject, expected_revision: int
) -> JSONDict:
    """Validate closed configuration only; detailed physics stays deferred."""

    _require_current_revision(stored, expected_revision)
    if len(stored.project.scenario_set) != 1:
        raise ValueError("configuration validation requires exactly one scenario")
    scenario = stored.project.scenario_set[0]
    provider_id = _nonempty_string(
        scenario.load_provider.get("provider_id"), "load provider id"
    )
    provider_input = _mapping(
        scenario.load_provider.get("provider_input"), "load provider input"
    )
    normalized = get_load_provider(provider_id).normalize(provider_input)
    input_fingerprint = canonical_fingerprint(_json_value(normalized))
    message = (
        "Configuration is valid; detailed mesh and physics checks are deferred "
        "until K-package generation."
    )
    correction = (
        "Generate the K package to run full detailed-building and solver-deck checks."
    )
    content_hash = canonical_fingerprint(
        {
            "severity": "info",
            "module": "deferred_compilation",
            "field_path": "building",
            "message": message,
            "correction": correction,
            "provider_input_fingerprint": input_fingerprint,
        }
    )
    finding = {
        "finding_id": "deferred-building-compilation",
        "severity": "info",
        "module": "deferred_compilation",
        "field_path": "building",
        "message": message,
        "correction": correction,
        "evidence": {
            "validation_mode": "configuration_only",
            "provider_input_fingerprint": input_fingerprint,
            "solver_ready": False,
            "requires_project_review": True,
        },
        "content_hash": content_hash,
    }
    project_fingerprint = _project_content_fingerprint(stored)
    validation_fingerprint = canonical_fingerprint(
        {
            "schema_version": "phase18f_configuration_validation@1",
            "project_id": stored.project_id,
            "project_revision": stored.revision,
            "project_fingerprint": project_fingerprint,
            "finding_content_hash": content_hash,
        }
    )
    gate = {
        "project_id": stored.project_id,
        "project_revision": stored.revision,
        "validation_fingerprint": validation_fingerprint,
        "allowed": True,
        "blocking_error_ids": [],
        "unacknowledged_warning_ids": [],
    }
    return {
        "project_id": stored.project_id,
        "project_revision": stored.revision,
        "project_fingerprint": project_fingerprint,
        "fingerprint": validation_fingerprint,
        "findings": [finding],
        "generation_gate": gate,
        "validation_mode": "configuration_only",
    }


def _revision_token(value: str) -> int:
    if not value.isdecimal():
        raise ApiError(404, "not_found", "artifact revision is invalid")
    return _positive_revision(int(value))


def _stored_project(stored: StoredProject) -> JSONDict:
    return {
        "project_id": stored.project_id,
        "revision": stored.revision,
        "project": _project_payload(stored.project),
        "fingerprints": _json_value(stored.fingerprints),
        "invalidation": {
            "building": stored.invalidation.building,
            "scenario": stored.invalidation.scenario,
            "provider": stored.invalidation.provider,
            "output_requests": stored.invalidation.output_requests,
            "assembly": stored.invalidation.assembly,
            "preview": stored.invalidation.preview,
            "results": stored.invalidation.results,
        },
    }


def _stored_project_with_metadata(
    stored: StoredProject, metadata: Mapping[str, object]
) -> JSONDict:
    payload = _stored_project(stored)
    payload["building_compilation_state"] = metadata["compilation_state"]
    payload["building_definition_fingerprint"] = metadata[
        "definition_fingerprint"
    ]
    payload["provider_input_migrations"] = _json_value(
        metadata.get("provider_input_migrations", [])
    )
    return payload


def _project_payload(project: RefinedBlastProject) -> JSONDict:
    return {
        "schema_version": project.schema_version,
        "project_id": project.project_id,
        "building_reference": _json_value(project.building_reference),
        "building_artifact_fingerprint": project.building_artifact_fingerprint,
        "preset_reference": project.preset_reference,
        "preset_version": project.preset_version,
        "project_overrides": _json_value(project.project_overrides),
        "expert_extensions": _json_value(project.expert_extensions),
        "scenario_set": [_scenario_payload(row) for row in project.scenario_set],
        "confirmation_records": [],
        "provenance": _json_value(project.provenance),
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def _scenario_payload(draft: ScenarioDraft) -> JSONDict:
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


def _validation_payload(validation: Any) -> JSONDict:
    return {
        "project_id": validation.project_id,
        "project_revision": validation.project_revision,
        "project_fingerprint": validation.project_fingerprint,
        "fingerprint": validation.fingerprint,
        "findings": [
            {
                "finding_id": row.finding_id,
                "severity": row.severity,
                "module": row.module,
                "field_path": row.field_path,
                "message": row.message,
                "correction": row.correction,
                "evidence": _json_value(row.evidence),
                "content_hash": row.content_hash,
            }
            for row in validation.findings
        ],
    }


def _preview_payload(preview: Any) -> JSONDict:
    payload = build_refined_blast_web_preview(preview)
    if payload is None:  # The service never returns None; keep the HTTP boundary fail-closed.
        raise ValueError("preview compilation produced no renderable payload")
    return payload


def _stored_artifact(artifact: StoredArtifact) -> JSONDict:
    return {
        "project_id": artifact.project_id,
        "scenario_id": artifact.scenario_id,
        "revision": artifact.revision,
        "fingerprint": artifact.fingerprint,
    }


def _package_payload(package: Any) -> JSONDict:
    """Persist a JSON-only package view without treating it as an executable action."""

    return {
        "schema_version": "refined_blast_web_package@1",
        "building_artifact_fingerprint": package.building_artifact_fingerprint,
        "package_fingerprint": package.package_fingerprint,
        "manifest": _json_value(package.manifest),
        "symbol_to_numeric_id": _json_value(package.symbol_to_numeric_id),
        "files": [
            {
                "path": path,
                "encoding": "base64",
                "content": base64.b64encode(content).decode("ascii"),
            }
            for path, content in package.files.items()
        ],
        "solver_ready": False,
        "requires_project_review": True,
        "external_program_started": False,
    }


def _asset_descriptor(row: Any) -> JSONDict:
    return {
        "asset_id": row.resource_id,
        "version": row.version,
        "legacy_asset_id": row.legacy_asset_id,
        "capability": row.capability,
        "default_geometry": _json_value(row.default_geometry),
        "geometry_fields": list(row.geometry_fields),
        "default_structural_system": row.default_structural_system,
        "allowed_structural_systems": list(row.allowed_structural_systems),
        "fidelity_profiles": list(row.fidelity_profiles),
        "default_fidelity_profile": row.default_fidelity_profile,
        "mesh_profiles": list(row.mesh_profiles),
        "default_mesh_profile": row.default_mesh_profile,
        "mesh_profiles_detail": _json_value(row.mesh_profile_rows),
        "material_candidates": _json_value(row.material_candidates),
        "unresolved_material_roles": list(row.unresolved_material_roles),
        "solver_ready": False,
        "requires_project_review": True,
        "building_recipe_schema": _building_recipe_ui_schema(row),
        "ui_sections_by_structural_system": {
            system_id: list(ui_sections_for_structural_system(system_id))
            for system_id in row.allowed_structural_systems
        },
        "generation_options_schema_by_structural_system": {
            system_id: generation_options_ui_schema(row.resource_id, system_id)
            for system_id in row.allowed_structural_systems
        },
    }


def _building_recipe_ui_schema(row: Any) -> JSONDict:
    """Closed create-recipe schema; UI-only sections remain outside this payload."""
    properties: JSONDict = {
        "asset_id": {"type": "string", "const": row.resource_id},
        "legacy_geometry": {"type": "object", "additionalProperties": False, "properties": {key: {"type": "number"} for key in row.geometry_fields}},
        "origin_m": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
        "rotation_deg": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
        "structural_system": {"type": "string", "enum": list(row.allowed_structural_systems)},
        "fidelity_profile": {"type": "string", "enum": list(row.fidelity_profiles)},
        "mesh_profile": {"type": "string", "enum": list(row.mesh_profiles)},
        "material_overrides": {"type": "object", "additionalProperties": False, "properties": {role: {"type": "string"} for role in row.material_override_roles}},
          # Selected-system applicability is provided as UI metadata above;
          # payload closure here is the compiler's union, not an ambiguous oneOf.
          "generation_options": {"type": "object", "additionalProperties": False, "properties": {
              key: {} for system in row.allowed_structural_systems
              for key in generation_options_ui_schema(row.resource_id, system)["properties"]
          }},
    }
    return {"type": "object", "additionalProperties": False, "required": ["asset_id"], "properties": properties}


__all__ = [
    "REFINED_BLAST_API_PREFIX",
    "RefinedBlastApi",
    "handle_refined_blast_artifact_get",
    "handle_refined_blast_get",
    "handle_refined_blast_post",
    "is_refined_blast_payload",
]
