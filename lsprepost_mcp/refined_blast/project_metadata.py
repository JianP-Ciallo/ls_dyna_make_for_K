"""Canonical creation evidence and versioned project metadata contracts."""
from __future__ import annotations

from collections.abc import Mapping
import copy
import json

from lsprepost_mcp.config import JSONDict
from . import store as store_module
from .contracts import RefinedBlastProject
from .provider_registry import get_load_provider
from .record_contract import (
    RecordError,
    require_allowed_keys,
    optional_mapping,
    optional_string,
    nonempty_string,
    sequence_or_default,
    json_value,
)

CLIENT_PROJECT_KEYS = frozenset(
    {
        "schema_version",
        "project_id",
        "preset_reference",
        "preset_version",
        "project_overrides",
        "expert_extensions",
        "scenario_set",
        "confirmation_records",
        "provenance",
        "created_at",
        "updated_at",
    }
)


METADATA_SCHEMA_VERSION = "phase18f_refined_blast_metadata@2"


DEFERRED_METADATA_SCHEMA_VERSION = "phase18f_refined_blast_metadata@3"


METADATA_NAME = "phase18f_refined_blast_metadata.json"


COMPILATION_STATES = frozenset({"pending", "compiled"})


BUILDING_KEYS = frozenset(
    {
        "asset_id",
        "legacy_geometry",
        "origin_m",
        "rotation_deg",
        "structural_system",
        "fidelity_profile",
        "mesh_profile",
        "generation_options",
        "material_overrides",
    }
)

def building_definition_fingerprint(value: Mapping[str, object]) -> str:
    """Identify one normalized building recipe without claiming mesh evidence."""

    recipe = normalize_building_recipe(value)
    return store_module._sha256(
        {
            "schema_version": "phase18f_building_definition@1",
            "building_recipe": json_value(recipe),
        }
    )


def normalize_building_recipe(value: Mapping[str, object]) -> Mapping[str, object]:
    require_allowed_keys(value, BUILDING_KEYS, "building")
    if "asset_id" not in value:
        raise RecordError("missing_field", "building is missing required field: asset_id")
    recipe: dict[str, object] = {
        "asset_id": nonempty_string(value["asset_id"], "building.asset_id"),
        "legacy_geometry": optional_mapping(value.get("legacy_geometry"), "building.legacy_geometry") or {},
        "origin_m": list(sequence_or_default(value.get("origin_m"), "building.origin_m", (0.0, 0.0, 0.0))),
        "rotation_deg": list(sequence_or_default(value.get("rotation_deg"), "building.rotation_deg", (0.0, 0.0, 0.0))),
        "structural_system": optional_string(value.get("structural_system"), "building.structural_system"),
        "fidelity_profile": optional_string(value.get("fidelity_profile"), "building.fidelity_profile") or "blast_response",
        "mesh_profile": optional_string(value.get("mesh_profile"), "building.mesh_profile") or "standard",
        "generation_options": optional_mapping(value.get("generation_options"), "building.generation_options") or {},
        "material_overrides": optional_mapping(value.get("material_overrides"), "building.material_overrides") or {},
    }
    try:
        return json.loads(json.dumps(recipe, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise RecordError("invalid_request", "building recipe must be finite JSON data") from exc


def initial_project_evidence(project: RefinedBlastProject) -> JSONDict:
    """Persist the complete normalized project supplied at creation time.

    It is immutable web metadata, rather than an inference from a later
    editable draft.  Only server-owned building identity fields are excluded:
    every client project field, including initial scenario and confirmation
    records, remains part of the original-create evidence.
    """

    raw = store_module._project_to_raw(project)
    raw.pop("building_reference")
    raw.pop("building_artifact_fingerprint")
    return raw


def create_request_fingerprint(
    project: RefinedBlastProject, recipe: Mapping[str, object]
) -> str:
    """Fingerprint the complete canonical original client create request."""

    return store_module._sha256(
        {"project": initial_project_evidence(project), "building": json_value(recipe)}
    )


def accepted_provider_input_migrations(
    original: Mapping[str, object],
    canonical: Mapping[str, object],
) -> list[JSONDict]:
    """Return declared provider migrations when they are the only difference.

    The immutable original create request remains the fingerprint authority.  A
    migration is accepted only when the provider publishes the exact source and
    target pair and replacing those provider inputs reproduces the complete
    canonical project byte-for-byte.
    """

    raw = json_value(original)
    expected = json_value(canonical)
    if raw == expected:
        return []
    if not isinstance(raw, dict) or not isinstance(expected, dict):
        return []
    migrated = copy.deepcopy(raw)
    raw_rows = migrated.get("scenario_set")
    expected_rows = expected.get("scenario_set")
    if (
        not isinstance(raw_rows, list)
        or not isinstance(expected_rows, list)
        or len(raw_rows) != len(expected_rows)
    ):
        return []

    records: list[JSONDict] = []
    for index, raw_row in enumerate(raw_rows):
        expected_row = expected_rows[index]
        if not isinstance(raw_row, dict) or not isinstance(expected_row, dict):
            return []
        raw_provider = raw_row.get("load_provider")
        expected_provider = expected_row.get("load_provider")
        if not isinstance(raw_provider, dict) or not isinstance(expected_provider, dict):
            return []
        raw_input = raw_provider.get("provider_input")
        expected_input = expected_provider.get("provider_input")
        source_version = (
            raw_input.get("schema_version") if isinstance(raw_input, dict) else None
        )
        target_version = (
            expected_input.get("schema_version")
            if isinstance(expected_input, dict)
            else None
        )
        provider_id = raw_provider.get("provider_id")
        if (
            raw_provider != expected_provider
            and isinstance(provider_id, str)
            and provider_id == expected_provider.get("provider_id")
            and isinstance(source_version, str)
            and isinstance(target_version, str)
            and provider_declares_migration(
                provider_id,
                source_version,
                target_version,
            )
        ):
            raw_provider["provider_input"] = copy.deepcopy(expected_input)
            records.append(
                {
                    "scenario_id": expected_row.get("scenario_id"),
                    "provider_id": provider_id,
                    "source_schema_version": source_version,
                    "target_schema_version": target_version,
                }
            )
    if not records or migrated != expected:
        return []
    return records


def provider_declares_migration(
    provider_id: str,
    source_version: str,
    target_version: str,
) -> bool:
    try:
        provider = get_load_provider(provider_id)
        schema = provider.schema()
        rows = schema.get("accepted_migrations", ())
        return any(
            (
                isinstance(row, str)
                and row == source_version
                and schema.get("schema_version") == target_version
            )
            or (
                isinstance(row, Mapping)
                and row.get("source_schema_version") == source_version
                and row.get("target_schema_version") == target_version
            )
            for row in rows
        )
    except (KeyError, TypeError, ValueError):
        return False
