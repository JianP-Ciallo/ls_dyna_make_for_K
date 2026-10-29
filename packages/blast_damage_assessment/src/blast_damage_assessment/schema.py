"""Closed parsing for public assessment request schema version 1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from .contracts import AssessmentRequest, FileReference
from .errors import ContractError, UnsupportedSchemaError


REQUEST_SCHEMA_V1 = "blast_damage.assessment_request@1"
_ROOT_FIELDS = {
    "schema_version",
    "project_id",
    "case_id",
    "result_dir",
    "semantic_manifest",
    "building_rule_pack",
    "ground_rule_pack",
    "output_dir",
    "state_chunk_size",
}
_REQUIRED_ROOT_FIELDS = _ROOT_FIELDS - {"state_chunk_size"}
_FILE_REFERENCE_FIELDS = {"path", "sha256", "schema_version"}
_REQUIRED_FILE_REFERENCE_FIELDS = {"path", "sha256"}


def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ContractError(f"non-finite JSON number is not allowed: {value}")


def _load_document(raw: str | bytes | bytearray) -> object:
    try:
        return json.loads(
            raw,
            object_pairs_hook=_closed_object,
            parse_constant=_reject_constant,
        )
    except ContractError:
        raise
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid assessment request JSON: {exc}") from exc


def _validate_keys(
    value: Mapping[str, object],
    allowed: set[str],
    required: set[str],
    location: str,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ContractError(f"{location} has unknown fields: {', '.join(unknown)}")
    missing = sorted(required - set(value))
    if missing:
        raise ContractError(f"{location} is missing required fields: {', '.join(missing)}")


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field_name} must be a non-empty string")
    return value


def _path(value: object, field_name: str) -> Path:
    return Path(_text(value, field_name))


def parse_request(raw: AssessmentRequest | Mapping[str, object] | str | bytes | bytearray) -> AssessmentRequest:
    if isinstance(raw, AssessmentRequest):
        return raw
    value: object = _load_document(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
    if not isinstance(value, Mapping):
        raise ContractError("assessment request root must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ContractError("assessment request field names must be strings")
    _validate_keys(value, _ROOT_FIELDS, _REQUIRED_ROOT_FIELDS, "assessment request")

    schema_version = _text(value["schema_version"], "schema_version")
    if schema_version != REQUEST_SCHEMA_V1:
        raise UnsupportedSchemaError(
            f"unsupported assessment request schema {schema_version!r}; expected {REQUEST_SCHEMA_V1}"
        )

    manifest = value["semantic_manifest"]
    if not isinstance(manifest, Mapping):
        raise ContractError("semantic_manifest must be an object")
    if not all(isinstance(key, str) for key in manifest):
        raise ContractError("semantic_manifest field names must be strings")
    _validate_keys(
        manifest,
        _FILE_REFERENCE_FIELDS,
        _REQUIRED_FILE_REFERENCE_FIELDS,
        "semantic_manifest",
    )

    try:
        reference = FileReference(
            path=_path(manifest["path"], "semantic_manifest.path"),
            sha256=_text(manifest["sha256"], "semantic_manifest.sha256"),
            schema_version=(
                _text(manifest["schema_version"], "semantic_manifest.schema_version")
                if manifest.get("schema_version") is not None
                else None
            ),
        )
        return AssessmentRequest(
            schema_version=schema_version,
            project_id=_text(value["project_id"], "project_id"),
            case_id=_text(value["case_id"], "case_id"),
            result_dir=_path(value["result_dir"], "result_dir"),
            semantic_manifest=reference,
            building_rule_pack=_text(value["building_rule_pack"], "building_rule_pack"),
            ground_rule_pack=_text(value["ground_rule_pack"], "ground_rule_pack"),
            output_dir=_path(value["output_dir"], "output_dir"),
            state_chunk_size=value.get("state_chunk_size", 4),
        )
    except ContractError:
        raise
    except (TypeError, ValueError) as exc:
        raise ContractError(str(exc)) from exc
