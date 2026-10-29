from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import hashlib
import json
import re

from .config import JSONDict, PHASE18_REVIEW_MANIFEST
from .io import read_json


SOURCE_2K_SHA256 = "c1c02a9e832852854b47cd3720bc9348cf48989484d25e1a54036836d0697a22"
REVIEW_SCHEMA_VERSION = "0.1.0"
REVIEW_METHOD = "automated_syntax_unit_dependency_audit"
REVIEWED_STATUS = "syntax_unit_reviewed"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REVIEW_METADATA_KEYS = {
    "_path",
    "_manifest_path",
    "_resource_dir",
    "validation_status",
    "effective_validation_status",
    "library_section",
    "review",
}


def canonical_resource_sha256(resource: Mapping[str, object]) -> str:
    payload = {key: value for key, value in resource.items() if key not in _REVIEW_METADATA_KEYS}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _review_records(manifest: Mapping[str, object]) -> dict[str, JSONDict]:
    raw_records = manifest.get("resources")
    if not isinstance(raw_records, list):
        raise ValueError("Phase 18 review manifest resources must be a list")
    records: dict[str, JSONDict] = {}
    for raw in raw_records:
        if not isinstance(raw, dict):
            raise ValueError("Phase 18 review resource record must be an object")
        resource_id = str(raw.get("id", "")).strip()
        if not resource_id:
            raise ValueError("Phase 18 review resource record id is required")
        if resource_id in records:
            raise ValueError(f"duplicate review resource id '{resource_id}'")
        records[resource_id] = dict(raw)
    return records


def _validate_review_manifest_header(manifest: Mapping[str, object]) -> None:
    if manifest.get("schema_version") != REVIEW_SCHEMA_VERSION:
        raise ValueError(f"Phase 18 review schema_version must be '{REVIEW_SCHEMA_VERSION}'")
    if manifest.get("source_sha256") != SOURCE_2K_SHA256:
        raise ValueError("Phase 18 review source SHA-256 does not match the accepted 2.k source")


def _validate_review_record(
    resource_id: str,
    resource: Mapping[str, object],
    record: Mapping[str, object],
    expected_resource_kind: str | None = None,
) -> None:
    resource_kind = record.get("resource_kind")
    if resource_kind not in {"material", "structural"}:
        raise ValueError(f"review resource '{resource_id}' has invalid resource_kind")
    if expected_resource_kind is not None and resource_kind != expected_resource_kind:
        raise ValueError(
            f"review resource '{resource_id}' resource_kind must be '{expected_resource_kind}'"
        )
    expected_hash = record.get("canonical_sha256")
    if not isinstance(expected_hash, str) or not _SHA256_PATTERN.fullmatch(expected_hash):
        raise ValueError(f"review resource '{resource_id}' has invalid canonical SHA-256")
    actual_hash = canonical_resource_sha256(resource)
    if expected_hash != actual_hash:
        raise ValueError(f"resource '{resource_id}' canonical SHA-256 does not match review evidence")
    if record.get("validation_status") != REVIEWED_STATUS:
        raise ValueError(f"review resource '{resource_id}' must use {REVIEWED_STATUS}")
    reviewed_on = record.get("reviewed_on")
    if not isinstance(reviewed_on, str):
        raise ValueError(f"review resource '{resource_id}' reviewed_on is required")
    try:
        date.fromisoformat(reviewed_on)
    except ValueError as exc:
        raise ValueError(f"review resource '{resource_id}' reviewed_on must be ISO-8601") from exc
    if record.get("review_method") != REVIEW_METHOD:
        raise ValueError(f"review resource '{resource_id}' has invalid review_method")
    evidence = record.get("evidence")
    if not isinstance(evidence, list) or not evidence or not all(
        isinstance(item, str) and bool(item.strip()) for item in evidence
    ):
        raise ValueError(f"review resource '{resource_id}' evidence must be a non-empty string list")


def validate_phase18_review_manifest(
    manifest: Mapping[str, object],
    resources: Mapping[str, Mapping[str, object]],
) -> JSONDict:
    _validate_review_manifest_header(manifest)

    records = _review_records(manifest)
    for resource_id, resource in resources.items():
        object_id = str(resource.get("id", "")).strip()
        if object_id != resource_id:
            raise ValueError(
                f"resource '{resource_id}' key/object identity mismatch: object id is '{object_id}'"
            )
    expected_ids = set(resources)
    actual_ids = set(records)
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - expected_ids)
        raise ValueError(f"Phase 18 review resource IDs do not match: missing={missing}, extra={extra}")

    for resource_id, record in records.items():
        _validate_review_record(resource_id, resources[resource_id], record)

    return {
        "valid": True,
        "source_sha256": SOURCE_2K_SHA256,
        "resource_count": len(records),
    }


def load_phase18_review_manifest() -> JSONDict:
    if not PHASE18_REVIEW_MANIFEST.is_file():
        return {
            "schema_version": REVIEW_SCHEMA_VERSION,
            "source_sha256": SOURCE_2K_SHA256,
            "resources": [],
        }
    manifest = read_json(PHASE18_REVIEW_MANIFEST)
    if not isinstance(manifest, dict):
        raise ValueError("Phase 18 review manifest must be an object")
    return manifest


def apply_effective_review(
    resource: Mapping[str, object],
    manifest: Mapping[str, object] | None = None,
    *,
    expected_resource_kind: str | None = None,
) -> JSONDict:
    evidence = manifest if manifest is not None else load_phase18_review_manifest()
    _validate_review_manifest_header(evidence)
    records = _review_records(evidence)
    resource_id = str(resource.get("id", "")).strip()
    record = records.get(resource_id)
    if record is None:
        return {**resource, "effective_validation_status": "source_reference"}
    _validate_review_record(resource_id, resource, record, expected_resource_kind)
    return {
        **resource,
        "effective_validation_status": REVIEWED_STATUS,
        "review": dict(record),
        "requires_project_review": True,
    }
