"""Thin, fail-closed bridge to the optional blast damage assessment package."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import stat
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from lsprepost_mcp.assessment_result_source import (
    resolve_assessment_result_source,
)
from lsprepost_mcp.config import JSONDict
from lsprepost_mcp.refined_blast import store as store_module
from lsprepost_mcp.refined_blast.store import (
    RefinedBlastStore,
    validate_storage_identifier,
)


CAPABILITY_SCHEMA = "lsprepost_mcp.damage_assessment_capabilities@1"
REGISTRY_SCHEMA = "lsprepost_mcp.damage_assessment_registry@1"
RESPONSE_SCHEMA = "lsprepost_mcp.damage_assessment_response@1"
REQUEST_SCHEMA = "blast_damage.assessment_request@1"
RESULT_SCHEMA = "blast_damage.assessment_result@1"
DEFAULT_BUILDING_RULE_PACK = "building_research_reference@1"
DEFAULT_GROUND_RULE_PACK = "ground_research_reference@1"
_ASSESSMENT_PACKAGE = "blast-damage-assessment"
_ADAPTER_ID = "lsdyna_d3plot"
_SEMANTICS_SCHEMA = "blast_damage.model_semantics@1"
_ACCEPTED_LASSO_VERSION = "2.0.4"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ASSESSMENT_ID_RE = re.compile(r"^[0-9a-f]{24}$")
_RUN_ID_RE = re.compile(r"^run_[A-Za-z0-9_]+$")
_TERMINAL_RUN_STATUSES = frozenset({"completed", "solver_failed", "timed_out"})
_GATES = frozenset({"formal", "provisional", "blocked"})
_ARTIFACT_NAMES = frozenset(
    {
        "assessment_request.json",
        "assessment_result.json",
        "assessment_snapshot.json",
        "evidence_index.json",
        "rule_snapshot.json",
        "damage_report.html",
        "building_components.csv",
        "ground_regions.csv",
    }
)
_RESULT_KEYS = frozenset(
    {
        "schema_version",
        "assessment_id",
        "execution_status",
        "gate",
        "severity",
        "assessment_fingerprint",
        "artifacts",
        "warnings",
        "blockers",
        "review_items",
        "state_chunk_size",
    }
)
_ARTIFACT_KEYS = frozenset(
    {"path", "sha256", "media_type", "size_bytes", "schema_version"}
)
_ISSUE_KEYS = frozenset({"code", "message", "details"})
_REGISTRY_KEYS = frozenset({"schema_version", "records"})
_RECORD_KEYS = frozenset(
    {
        "assessment_id",
        "request_schema_version",
        "result_schema_version",
        "package",
        "adapter",
        "rule_packs",
        "gate",
        "severity",
        "assessment_fingerprint",
        "source_evidence_digest",
        "source",
        "output_relative_path",
        "artifacts",
        "warnings",
        "blockers",
        "review_items",
        "registered_at",
    }
)


class DamageAssessmentUnavailableError(RuntimeError):
    """Raised when the optional package cannot satisfy the bridge contract."""


class DamageAssessmentNotFoundError(FileNotFoundError):
    """Raised when a project has no registered assessment."""


class DamageAssessmentRegistryConflictError(ValueError):
    """Raised when one assessment identity is presented with conflicting data."""


class _CapabilityError(ValueError):
    pass


def assessment_capabilities() -> JSONDict:
    """Return a stable, path-free availability envelope."""

    try:
        capabilities, _assess = _assessment_api()
    except ModuleNotFoundError as exc:
        return _unavailable(
            "optional_package_not_installed"
            if exc.name in {None, "blast_damage_assessment"}
            else "optional_package_dependency_missing"
        )
    except Exception:
        return _unavailable("optional_package_import_failed")
    try:
        return _normalize_capabilities(capabilities())
    except Exception:
        return _unavailable("incompatible_capabilities")


def assess_completed_run(
    *,
    project_id: str,
    case_id: str,
    project_dir: Path,
    run_dir: Path,
    semantic_manifest: Path,
    building_rule_pack: str = DEFAULT_BUILDING_RULE_PACK,
    ground_rule_pack: str = DEFAULT_GROUND_RULE_PACK,
) -> JSONDict:
    """Assess exactly one revalidated, server-owned terminal solver run."""

    safe_project = validate_storage_identifier(project_id, "project_id")
    safe_case = validate_storage_identifier(case_id, "case_id")
    project = _validated_project_dir(safe_project, project_dir)
    requested_run = _absolute_path(run_dir)
    requested_semantics = _absolute_path(semantic_manifest)

    capabilities_fn, assess_fn = _load_available_api()
    try:
        normalized_capabilities = _normalize_capabilities(capabilities_fn())
    except Exception as exc:
        raise DamageAssessmentUnavailableError(
            "incompatible_capabilities"
        ) from exc
    selected_rules = _select_rules(
        normalized_capabilities, building_rule_pack, ground_rule_pack
    )
    source = _trusted_source(
        safe_project, project, requested_run, requested_semantics
    )
    source_record = source["record"]
    assert isinstance(source_record, dict)
    semantic_schema = _semantic_schema(
        requested_semantics,
        expected_sha256=_digest(source_record.get("semantics_sha256"), "semantics_sha256"),
        supported=normalized_capabilities["semantic_schemas"],
    )
    source_evidence_digest = _source_digest(source_record)
    output_dir = _new_output_dir(safe_project, project)
    request: JSONDict = {
        "schema_version": REQUEST_SCHEMA,
        "project_id": safe_project,
        "case_id": safe_case,
        "result_dir": str(requested_run),
        "semantic_manifest": {
            "path": str(requested_semantics),
            "sha256": source_record["semantics_sha256"],
            "schema_version": semantic_schema,
        },
        "building_rule_pack": building_rule_pack,
        "ground_rule_pack": ground_rule_pack,
        "output_dir": str(output_dir),
        "state_chunk_size": 4,
    }

    result_object = assess_fn(request)
    to_dict = getattr(result_object, "to_dict", None)
    if not callable(to_dict):
        raise ValueError("assessment result does not expose public to_dict()")
    result = _validate_result(to_dict(), output_dir)

    current_source = _trusted_source(
        safe_project, project, requested_run, requested_semantics
    )
    current_record = current_source["record"]
    if (
        not isinstance(current_record, dict)
        or _source_digest(current_record) != source_evidence_digest
    ):
        raise ValueError("trusted assessment source changed during assessment")

    record = _registry_record(
        result=result,
        capabilities=normalized_capabilities,
        selected_rules=selected_rules,
        source_record=source_record,
        source_evidence_digest=source_evidence_digest,
        project_dir=project,
        output_dir=output_dir,
    )
    try:
        registered_record, registration_state = _register_result(
            safe_project, project, record
        )
    except DamageAssessmentRegistryConflictError:
        raise
    except (OSError, RuntimeError, TimeoutError):
        return _public_result(
            result,
            record,
            registration_state="completed_unregistered",
        )
    return _public_result(
        result,
        registered_record,
        registration_state=registration_state,
    )


def latest_registered_assessment(project_dir: Path) -> JSONDict:
    """Return the latest immutable registry record for one project."""

    project = _absolute_path(project_dir)
    safe_project = validate_storage_identifier(project.name, "project_id")
    project = _validated_project_dir(safe_project, project)
    with _project_store(safe_project, project) as store:
        with store.project_transaction(safe_project):
            registry = _read_registry(store, project, missing_ok=True)
            records = registry["records"]
            if not records:
                raise DamageAssessmentNotFoundError(
                    f"no registered damage assessment for project {safe_project}"
                )
            record = _validate_registry_record(records[-1])
    return {
        "schema_version": RESPONSE_SCHEMA,
        "registration_state": "registered",
        **record,
    }


def registered_assessment(project_dir: Path, assessment_id: str) -> JSONDict:
    """Return one historical registry record selected only by a closed ID."""

    if (
        not isinstance(assessment_id, str)
        or _ASSESSMENT_ID_RE.fullmatch(assessment_id) is None
    ):
        raise ValueError("assessment_id must be 24 lowercase hexadecimal characters")
    project = _absolute_path(project_dir)
    safe_project = validate_storage_identifier(project.name, "project_id")
    project = _validated_project_dir(safe_project, project)
    with _project_store(safe_project, project) as store:
        with store.project_transaction(safe_project):
            registry = _read_registry(store, project, missing_ok=True)
            for item in registry["records"]:
                record = _validate_registry_record(item)
                if record["assessment_id"] == assessment_id:
                    return {
                        "schema_version": RESPONSE_SCHEMA,
                        "registration_state": "registered",
                        **record,
                    }
    raise DamageAssessmentNotFoundError(
        f"damage assessment is not registered: {assessment_id}"
    )


def _assessment_api() -> tuple[Callable[[], object], Callable[[object], object]]:
    module = importlib.import_module("blast_damage_assessment.api")
    capabilities = getattr(module, "capabilities", None)
    assess = getattr(module, "assess", None)
    if not callable(capabilities) or not callable(assess):
        raise _CapabilityError("optional assessment public API is incomplete")
    return capabilities, assess


def _load_available_api() -> tuple[Callable[[], object], Callable[[object], object]]:
    try:
        capabilities, assess = _assessment_api()
    except Exception as exc:
        raise DamageAssessmentUnavailableError(
            assessment_capabilities()["reason"]
        ) from exc
    return capabilities, assess


def _normalize_capabilities(value: object) -> JSONDict:
    if not isinstance(value, Mapping):
        raise _CapabilityError("capabilities must be an object")
    package = value.get("package")
    schemas = value.get("schemas")
    adapters = value.get("adapters")
    dependencies = value.get("dependencies")
    rule_packs = value.get("rule_packs")
    if not all(
        isinstance(item, Mapping)
        for item in (package, schemas, dependencies)
    ):
        raise _CapabilityError("capability sections are invalid")
    assert isinstance(package, Mapping)
    assert isinstance(schemas, Mapping)
    assert isinstance(dependencies, Mapping)
    if package.get("name") != _ASSESSMENT_PACKAGE:
        raise _CapabilityError("unexpected package")
    package_version = _text(package.get("version"), "package.version")
    request_schemas = _string_list(schemas.get("request"), "schemas.request")
    result_schemas = _string_list(schemas.get("result"), "schemas.result")
    semantic_schemas = _string_list(schemas.get("semantics"), "schemas.semantics")
    if REQUEST_SCHEMA not in request_schemas or RESULT_SCHEMA not in result_schemas:
        raise _CapabilityError("required schemas are unavailable")
    if _SEMANTICS_SCHEMA not in semantic_schemas:
        raise _CapabilityError("native semantic schema is unavailable")
    if not isinstance(adapters, list):
        raise _CapabilityError("adapters must be a list")
    adapter: JSONDict | None = None
    for item in adapters:
        if isinstance(item, Mapping) and item.get("id") == _ADAPTER_ID:
            adapter = {
                "id": _ADAPTER_ID,
                "version": _text(item.get("version"), "adapter.version"),
            }
            break
    if adapter is None:
        raise _CapabilityError("LS-DYNA adapter is unavailable")
    lasso_version = _text(
        dependencies.get("lasso_python"), "dependencies.lasso_python"
    )
    if lasso_version != _ACCEPTED_LASSO_VERSION:
        raise _CapabilityError("lasso-python version is incompatible")
    numpy_version = _text(dependencies.get("numpy"), "dependencies.numpy")
    if not isinstance(rule_packs, list):
        raise _CapabilityError("rule_packs must be a list")
    normalized_rules: list[JSONDict] = []
    seen: set[str] = set()
    for item in rule_packs:
        if not isinstance(item, Mapping):
            raise _CapabilityError("rule pack entry is invalid")
        pack_id = _text(item.get("id"), "rule_pack.id")
        if pack_id in seen:
            raise _CapabilityError("duplicate rule pack")
        seen.add(pack_id)
        subject = _text(item.get("subject"), "rule_pack.subject")
        if subject not in {"building", "ground"}:
            raise _CapabilityError("rule pack subject is invalid")
        normalized_rules.append(
            {
                "id": pack_id,
                "subject": subject,
                "sha256": _digest(item.get("sha256"), "rule_pack.sha256"),
                "formal_eligible": item.get("formal_eligible") is True,
            }
        )
    _select_rules(
        {"rule_packs": normalized_rules},
        DEFAULT_BUILDING_RULE_PACK,
        DEFAULT_GROUND_RULE_PACK,
    )
    return {
        "schema_version": CAPABILITY_SCHEMA,
        "available": True,
        "package": {"name": _ASSESSMENT_PACKAGE, "version": package_version},
        "request_schema": REQUEST_SCHEMA,
        "result_schema": RESULT_SCHEMA,
        "semantic_schemas": semantic_schemas,
        "adapter": adapter,
        "dependencies": {
            "lasso_python": lasso_version,
            "numpy": numpy_version,
        },
        "rule_packs": normalized_rules,
    }


def _unavailable(reason: str) -> JSONDict:
    return {
        "schema_version": CAPABILITY_SCHEMA,
        "available": False,
        "reason": reason,
    }


def _select_rules(
    capabilities: Mapping[str, object],
    building_rule_pack: str,
    ground_rule_pack: str,
) -> JSONDict:
    building_id = _text(building_rule_pack, "building_rule_pack")
    ground_id = _text(ground_rule_pack, "ground_rule_pack")
    raw = capabilities.get("rule_packs")
    if not isinstance(raw, list):
        raise _CapabilityError("rule packs are unavailable")
    by_id = {
        str(item.get("id")): item
        for item in raw
        if isinstance(item, Mapping)
    }
    selected: JSONDict = {}
    for subject, pack_id in (("building", building_id), ("ground", ground_id)):
        item = by_id.get(pack_id)
        if not isinstance(item, Mapping) or item.get("subject") != subject:
            raise _CapabilityError(f"required {subject} rule pack is unavailable")
        selected[subject] = {
            "id": pack_id,
            "sha256": _digest(item.get("sha256"), f"{subject} rule sha256"),
        }
    return selected


def _trusted_source(
    project_id: str,
    project_dir: Path,
    run_dir: Path,
    semantic_manifest: Path,
) -> JSONDict:
    resolved = resolve_assessment_result_source(project_dir)
    if not isinstance(resolved, dict):
        raise ValueError("trusted assessment source is malformed")
    record = resolved.get("record")
    if not isinstance(record, dict):
        raise ValueError("trusted assessment source record is malformed")
    if (
        record.get("project_id") != project_id
        or record.get("run_status") not in _TERMINAL_RUN_STATUSES
    ):
        raise ValueError("trusted assessment source is not an eligible terminal run")
    resolved_run = _absolute_path(resolved.get("run_dir"))
    resolved_semantics = _absolute_path(resolved.get("semantic_manifest"))
    if resolved_run != run_dir or resolved_semantics != semantic_manifest:
        raise ValueError("requested paths do not match the trusted assessment source")
    return {
        "record": record,
        "run_dir": resolved_run,
        "semantic_manifest": resolved_semantics,
    }


def _semantic_schema(
    path: Path, *, expected_sha256: str, supported: object
) -> str:
    _assert_plain_file(path, "semantic manifest")
    if _sha256(path) != expected_sha256:
        raise ValueError("semantic manifest hash does not match trusted source")
    value = _read_json(path)
    schema = _text(value.get("schema_version"), "semantic manifest schema_version")
    legacy_supported = (
        isinstance(supported, list)
        and "phase18.solver_blast.deck_manifest@1-4" in supported
        and re.fullmatch(r"phase18\.solver_blast\.deck_manifest@[1-4]", schema) is not None
    )
    if not isinstance(supported, list) or (schema not in supported and not legacy_supported):
        raise ValueError("semantic manifest schema is unsupported")
    return schema


def _new_output_dir(project_id: str, project_dir: Path) -> Path:
    with _project_store(project_id, project_dir) as store:
        with store.project_transaction(project_id):
            root = store._safe_root()
            artifacts = project_dir / "artifacts"
            assessments = artifacts / "damage_assessments"
            store_module._create_safe_directory(artifacts, root)
            store_module._create_safe_directory(assessments, root)
            for _attempt in range(8):
                output = assessments / f"assessment_{uuid.uuid4().hex}"
                if not output.exists():
                    return output
    raise RuntimeError("could not allocate a unique assessment output directory")


def _validate_result(value: object, output_dir: Path) -> JSONDict:
    if not isinstance(value, dict) or set(value) != _RESULT_KEYS:
        raise ValueError("assessment result schema is invalid")
    assessment_id = value.get("assessment_id")
    if not isinstance(assessment_id, str) or _ASSESSMENT_ID_RE.fullmatch(assessment_id) is None:
        raise ValueError("assessment result ID is invalid")
    if value.get("schema_version") != RESULT_SCHEMA:
        raise ValueError("assessment result schema version is unsupported")
    if value.get("execution_status") != "completed":
        raise ValueError("assessment result execution is incomplete")
    gate = value.get("gate")
    if gate not in _GATES:
        raise ValueError("assessment result gate is invalid")
    severity = value.get("severity")
    if severity is not None and (
        isinstance(severity, bool)
        or not isinstance(severity, int)
        or severity not in range(5)
    ):
        raise ValueError("assessment result severity is invalid")
    if gate == "blocked" and severity is not None:
        raise ValueError("blocked assessment result severity must be null")
    fingerprint = _digest(
        value.get("assessment_fingerprint"), "assessment_fingerprint"
    )
    if value.get("state_chunk_size") != 4:
        raise ValueError("assessment result state chunk size is incompatible")
    issues = {
        name: _issues(value.get(name), name)
        for name in ("warnings", "blockers", "review_items")
    }
    raw_artifacts = value.get("artifacts")
    if not isinstance(raw_artifacts, dict) or set(raw_artifacts) != _ARTIFACT_NAMES:
        raise ValueError("assessment result artifact set is invalid")
    _assert_plain_directory(output_dir, "assessment output")
    verified: JSONDict = {}
    for name in sorted(_ARTIFACT_NAMES):
        reference = _artifact_reference(name, raw_artifacts[name])
        path = output_dir / name
        _assert_plain_file(path, f"assessment artifact {name}")
        data = path.read_bytes()
        if len(data) != reference["size_bytes"]:
            raise ValueError(f"assessment artifact size mismatch: {name}")
        if _sha_bytes(data) != reference["sha256"]:
            raise ValueError(f"assessment artifact hash mismatch: {name}")
        verified[name] = reference
    disk_result = _read_json(output_dir / "assessment_result.json")
    expected_disk = {
        **value,
        "artifacts": {
            name: raw_artifacts[name]
            for name in sorted(_ARTIFACT_NAMES - {"assessment_result.json"})
        },
    }
    if disk_result != expected_disk:
        raise ValueError("assessment_result.json does not match public result")
    return {
        "schema_version": RESULT_SCHEMA,
        "assessment_id": assessment_id,
        "execution_status": "completed",
        "gate": gate,
        "severity": severity,
        "assessment_fingerprint": fingerprint,
        "artifacts": verified,
        **issues,
        "state_chunk_size": 4,
    }


def _artifact_reference(name: str, value: object) -> JSONDict:
    if not isinstance(value, dict) or set(value) != _ARTIFACT_KEYS:
        raise ValueError(f"assessment artifact reference is invalid: {name}")
    path = value.get("path")
    if path != name or PurePosixPath(str(path)).parts != (name,):
        raise ValueError(f"assessment artifact path is invalid: {name}")
    size = value.get("size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError(f"assessment artifact size is invalid: {name}")
    schema_version = value.get("schema_version")
    if schema_version is not None:
        _text(schema_version, f"artifact {name} schema_version")
    return {
        "path": name,
        "sha256": _digest(value.get("sha256"), f"artifact {name} sha256"),
        "media_type": _text(value.get("media_type"), f"artifact {name} media_type"),
        "size_bytes": size,
        "schema_version": schema_version,
    }


def _issues(value: object, label: str) -> list[JSONDict]:
    if not isinstance(value, list):
        raise ValueError(f"assessment result {label} must be a list")
    result: list[JSONDict] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != _ISSUE_KEYS:
            raise ValueError(f"assessment result {label} entry is invalid")
        details = item.get("details")
        if not isinstance(details, dict):
            raise ValueError(f"assessment result {label} details are invalid")
        result.append(
            {
                "code": _text(item.get("code"), f"{label}.code"),
                "message": _text(item.get("message"), f"{label}.message"),
                "details": details,
            }
        )
    _canonical_bytes(result)
    return result


def _registry_record(
    *,
    result: Mapping[str, object],
    capabilities: Mapping[str, object],
    selected_rules: Mapping[str, object],
    source_record: Mapping[str, object],
    source_evidence_digest: str,
    project_dir: Path,
    output_dir: Path,
) -> JSONDict:
    output_relative = output_dir.relative_to(project_dir).as_posix()
    artifacts: JSONDict = {}
    raw_artifacts = result["artifacts"]
    assert isinstance(raw_artifacts, dict)
    for name, reference in raw_artifacts.items():
        assert isinstance(reference, dict)
        artifacts[name] = {
            **reference,
            "path": f"{output_relative}/{name}",
        }
    return {
        "assessment_id": result["assessment_id"],
        "request_schema_version": REQUEST_SCHEMA,
        "result_schema_version": RESULT_SCHEMA,
        "package": capabilities["package"],
        "adapter": capabilities["adapter"],
        "rule_packs": dict(selected_rules),
        "gate": result["gate"],
        "severity": result["severity"],
        "assessment_fingerprint": result["assessment_fingerprint"],
        "source_evidence_digest": source_evidence_digest,
        "source": {
            "run_id": source_record["run_id"],
            "run_status": source_record["run_status"],
            "model_sha256": source_record["model_sha256"],
            "manifest_sha256": source_record["manifest_sha256"],
            "semantics_sha256": source_record["semantics_sha256"],
        },
        "output_relative_path": output_relative,
        "artifacts": artifacts,
        "warnings": result["warnings"],
        "blockers": result["blockers"],
        "review_items": result["review_items"],
        "registered_at": _utc_now(),
    }


def _register_result(
    project_id: str, project_dir: Path, record: JSONDict
) -> tuple[JSONDict, str]:
    with _project_store(project_id, project_dir) as store:
        with store.project_transaction(project_id):
            registry = _read_registry(store, project_dir, missing_ok=True)
            records = registry["records"]
            assert isinstance(records, list)
            for existing in records:
                validated = _validate_registry_record(existing)
                if validated["assessment_id"] != record["assessment_id"]:
                    continue
                if (
                    validated["assessment_fingerprint"]
                    != record["assessment_fingerprint"]
                    or validated["source_evidence_digest"]
                    != record["source_evidence_digest"]
                ):
                    raise DamageAssessmentRegistryConflictError(
                        "assessment ID has a conflicting fingerprint or source"
                    )
                return validated, "registered_existing"
            validated_record = _validate_registry_record(record)
            updated = {
                "schema_version": REGISTRY_SCHEMA,
                "records": [*records, validated_record],
            }
            _write_registry(
                store,
                project_dir / "artifacts" / "damage_assessments" / "registry.json",
                updated,
            )
            return validated_record, "registered"


def _write_registry(
    store: RefinedBlastStore, path: Path, registry: Mapping[str, object]
) -> None:
    store_module._atomic_write_json(
        path,
        registry,
        root=store._safe_root(),
        anchor=store._root_anchor,
    )


def _read_registry(
    store: RefinedBlastStore, project_dir: Path, *, missing_ok: bool
) -> JSONDict:
    path = project_dir / "artifacts" / "damage_assessments" / "registry.json"
    if not path.exists():
        if missing_ok:
            return {"schema_version": REGISTRY_SCHEMA, "records": []}
        raise DamageAssessmentNotFoundError("damage assessment registry is missing")
    store_module._assert_safe_file(path, store._safe_root(), missing_ok=False)
    raw = _json_object(
        store_module._read_text_file(
            path, root=store._safe_root(), anchor=store._root_anchor
        )
    )
    if set(raw) != _REGISTRY_KEYS or raw.get("schema_version") != REGISTRY_SCHEMA:
        raise ValueError("damage assessment registry schema is invalid")
    records = raw.get("records")
    if not isinstance(records, list):
        raise ValueError("damage assessment registry records must be a list")
    return {
        "schema_version": REGISTRY_SCHEMA,
        "records": [_validate_registry_record(item) for item in records],
    }


def _validate_registry_record(value: object) -> JSONDict:
    if not isinstance(value, dict) or set(value) != _RECORD_KEYS:
        raise ValueError("damage assessment registry record is invalid")
    _canonical_bytes(value)
    assessment_id = value.get("assessment_id")
    if not isinstance(assessment_id, str) or _ASSESSMENT_ID_RE.fullmatch(assessment_id) is None:
        raise ValueError("damage assessment registry ID is invalid")
    if value.get("request_schema_version") != REQUEST_SCHEMA:
        raise ValueError("damage assessment registry request schema is invalid")
    if value.get("result_schema_version") != RESULT_SCHEMA:
        raise ValueError("damage assessment registry result schema is invalid")
    gate = value.get("gate")
    if gate not in _GATES:
        raise ValueError("damage assessment registry gate is invalid")
    severity = value.get("severity")
    if severity is not None and (
        isinstance(severity, bool)
        or not isinstance(severity, int)
        or severity not in range(5)
    ):
        raise ValueError("damage assessment registry severity is invalid")
    if gate == "blocked" and severity is not None:
        raise ValueError(
            "blocked damage assessment registry severity must be null"
        )
    package = value.get("package")
    if not isinstance(package, dict) or set(package) != {"name", "version"}:
        raise ValueError("damage assessment registry package is invalid")
    if package.get("name") != _ASSESSMENT_PACKAGE:
        raise ValueError("damage assessment registry package name is invalid")
    _text(package.get("version"), "registry package version")
    adapter = value.get("adapter")
    if not isinstance(adapter, dict) or set(adapter) != {"id", "version"}:
        raise ValueError("damage assessment registry adapter is invalid")
    if adapter.get("id") != _ADAPTER_ID:
        raise ValueError("damage assessment registry adapter ID is invalid")
    _text(adapter.get("version"), "registry adapter version")
    rules = value.get("rule_packs")
    if not isinstance(rules, dict) or set(rules) != {"building", "ground"}:
        raise ValueError("damage assessment registry rule packs are invalid")
    for subject in ("building", "ground"):
        rule = rules[subject]
        if not isinstance(rule, dict) or set(rule) != {"id", "sha256"}:
            raise ValueError("damage assessment registry rule pack is invalid")
        _text(rule.get("id"), f"registry {subject} rule ID")
        _digest(rule.get("sha256"), f"registry {subject} rule sha256")
    source = value.get("source")
    source_keys = {
        "run_id",
        "run_status",
        "model_sha256",
        "manifest_sha256",
        "semantics_sha256",
    }
    if not isinstance(source, dict) or set(source) != source_keys:
        raise ValueError("damage assessment registry source is invalid")
    run_id = source.get("run_id")
    if not isinstance(run_id, str) or _RUN_ID_RE.fullmatch(run_id) is None:
        raise ValueError("damage assessment registry source run ID is invalid")
    if source.get("run_status") not in _TERMINAL_RUN_STATUSES:
        raise ValueError("damage assessment registry source status is invalid")
    for name in ("model_sha256", "manifest_sha256", "semantics_sha256"):
        _digest(source.get(name), f"registry source {name}")
    _digest(value.get("assessment_fingerprint"), "assessment_fingerprint")
    _digest(value.get("source_evidence_digest"), "source_evidence_digest")
    output = _relative_path(value.get("output_relative_path"), "output_relative_path")
    if output.parts[:2] != ("artifacts", "damage_assessments") or len(output.parts) != 3:
        raise ValueError("damage assessment output path is invalid")
    if re.fullmatch(r"assessment_[0-9a-f]{32}", output.parts[2]) is None:
        raise ValueError("damage assessment output identity is invalid")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != _ARTIFACT_NAMES:
        raise ValueError("damage assessment registry artifacts are invalid")
    for name, reference in artifacts.items():
        if not isinstance(reference, dict) or set(reference) != _ARTIFACT_KEYS:
            raise ValueError("damage assessment registry artifact is invalid")
        expected = f"{output.as_posix()}/{name}"
        if reference.get("path") != expected:
            raise ValueError("damage assessment registry artifact path is invalid")
        _digest(reference.get("sha256"), f"registry artifact {name} sha256")
        size = reference.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError("damage assessment registry artifact size is invalid")
        _text(
            reference.get("media_type"),
            f"registry artifact {name} media_type",
        )
        schema_version = reference.get("schema_version")
        if schema_version is not None:
            _text(
                schema_version,
                f"registry artifact {name} schema_version",
            )
    _issues(value.get("warnings"), "registry warnings")
    _issues(value.get("blockers"), "registry blockers")
    _issues(value.get("review_items"), "registry review_items")
    _timestamp(value.get("registered_at"))
    return json.loads(json.dumps(value))


def _public_result(
    result: Mapping[str, object],
    record: Mapping[str, object],
    *,
    registration_state: str,
) -> JSONDict:
    return {
        "schema_version": RESPONSE_SCHEMA,
        "registration_state": registration_state,
        "assessment_id": result["assessment_id"],
        "execution_status": result["execution_status"],
        "gate": result["gate"],
        "severity": result["severity"],
        "assessment_fingerprint": result["assessment_fingerprint"],
        "output_relative_path": record["output_relative_path"],
        "artifacts": record["artifacts"],
        "warnings": result["warnings"],
        "blockers": result["blockers"],
        "review_items": result["review_items"],
    }


def _validated_project_dir(project_id: str, value: object) -> Path:
    project = _absolute_path(value)
    if (
        project.name != project_id
        or project.parent.name != "refined_building_blast"
        or project.parent.parent.name != "workspace"
    ):
        raise ValueError("project directory is outside the refined-blast store layout")
    with _project_store(project_id, project) as store:
        if store._layout(project_id, create=False) != project:
            raise ValueError("project directory does not match the owning store")
    return project


def _project_store(project_id: str, project_dir: Path) -> RefinedBlastStore:
    del project_id
    return RefinedBlastStore(project_dir.parents[2])


def _source_digest(record: Mapping[str, object]) -> str:
    evidence = {key: value for key, value in record.items() if key != "registered_at"}
    return _sha_bytes(_canonical_bytes(evidence))


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _read_json(path: Path) -> JSONDict:
    return _json_object(path.read_text(encoding="utf-8"))


def _json_object(text: str) -> JSONDict:
    value = json.loads(text, object_pairs_hook=store_module._reject_duplicate_json_keys)
    if not isinstance(value, dict):
        raise ValueError("JSON document must be an object")
    return value


def _absolute_path(value: object) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise ValueError("path must be a string or Path")
    return Path(os.path.abspath(Path(value)))


def _relative_path(value: object, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError(f"{label} is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} is invalid")
    return path


def _assert_plain_directory(path: Path, label: str) -> None:
    metadata = path.lstat()
    if store_module._is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{label} must be a plain directory")


def _assert_plain_file(path: Path, label: str) -> None:
    metadata = path.lstat()
    if store_module._is_link_or_reparse(metadata) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{label} must be a plain file")


def _sha256(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise _CapabilityError(f"{label} must be a non-empty list")
    result = [_text(item, label) for item in value]
    if len(set(result)) != len(result):
        raise _CapabilityError(f"{label} contains duplicates")
    return result


def _timestamp(value: object) -> str:
    text = _text(value, "registered_at")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("registered_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("registered_at must include a timezone")
    if parsed.utcoffset().total_seconds() != 0:
        raise ValueError("registered_at must use UTC")
    return text


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


__all__ = [
    "CAPABILITY_SCHEMA",
    "REGISTRY_SCHEMA",
    "RESPONSE_SCHEMA",
    "DamageAssessmentNotFoundError",
    "DamageAssessmentRegistryConflictError",
    "DamageAssessmentUnavailableError",
    "assessment_capabilities",
    "assess_completed_run",
    "latest_registered_assessment",
    "registered_assessment",
]
