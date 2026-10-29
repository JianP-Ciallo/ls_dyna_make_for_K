"""Strict Web projection of the authoritative Phase 18E preview contract."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from lsprepost_mcp.refined_blast.preview import (
    PREVIEW_COUNT_METRICS,
    PREVIEW_LAYER_IDS,
    RefinedBlastPreview,
)
from lsprepost_mcp.refined_blast.providers.common import fingerprint_value, thaw_value


_PREVIEW_KEYS = frozenset(
    {
        "project_id", "scenario_id", "project_revision", "cache_key",
        "is_final", "fingerprint", "layers", "counts",
    }
)
_LAYER_KEYS = frozenset({"layer_id", "payload", "source_fingerprints", "fingerprint"})
_COUNT_KEYS = frozenset({"metric", "value", "semantics"})
_NEUTRAL_REPRESENTATION_KEYS = frozenset(
    {
        "schema_version", "representation", "source_item_count",
        "rendered_item_count", "coverage", "primitive_count",
        "payload_byte_count", "fingerprint",
    }
)
_MAX_NEUTRAL_PRIMITIVES_PER_LAYER = 4
_MAX_NEUTRAL_PRIMITIVE_BYTES_PER_LAYER = 2_000_000
_MAX_NEUTRAL_SOURCE_ITEMS_PER_LAYER = 512
_MAX_PREVIEW_SOURCE_ITEMS = 1_000_000
_NEUTRAL_SCHEMA_VERSION = "refined_blast.neutral_primitives@1"


def build_refined_blast_web_preview(
    preview: RefinedBlastPreview | Mapping[str, object] | None,
) -> dict[str, object] | None:
    """Project one Phase 18E preview without deriving new preview semantics.

    ``None`` represents a request that never produced an authoritative preview,
    for example because validation blocked compilation.  Mapping inputs are
    accepted for cache/restoration checks, but must still satisfy the same
    closed layer and metric order as the domain object.
    """

    if preview is None:
        return None
    raw = _domain_payload(preview) if isinstance(preview, RefinedBlastPreview) else _mapping_payload(preview)
    unknown = sorted(set(raw) - _PREVIEW_KEYS)
    missing = sorted(_PREVIEW_KEYS - set(raw))
    if unknown:
        raise ValueError(f"preview has unknown field: {unknown[0]!r}")
    if missing:
        raise ValueError(f"preview is missing field: {missing[0]!r}")
    for key in ("project_id", "scenario_id", "cache_key", "fingerprint"):
        _string(raw.get(key), key)
    if not isinstance(raw.get("is_final"), bool):
        raise ValueError("preview is_final must be a boolean")
    layers = _sequence(raw.get("layers"), "preview layers")
    layer_rows = tuple(_closed_mapping(row, _LAYER_KEYS, "preview layer") for row in layers)
    layer_ids = tuple(_string(row.get("layer_id"), "layer_id") for row in layer_rows)
    if layer_ids != PREVIEW_LAYER_IDS:
        raise ValueError("preview layer order does not match the closed Phase 18E contract")
    verified_layer_fingerprints: list[str] = []
    for row in layer_rows:
        payload = _mapping(row.get("payload"), "preview layer payload")
        primitives = _sequence(payload.get("neutral_primitives"), "preview neutral_primitives")
        representation = _closed_mapping(
            payload.get("neutral_representation"),
            _NEUTRAL_REPRESENTATION_KEYS,
            "preview neutral_representation",
        )
        primitive_count = _bounded_integer(
            representation.get("primitive_count"), "neutral primitive_count",
            _MAX_NEUTRAL_PRIMITIVES_PER_LAYER,
        )
        if primitive_count != len(primitives):
            raise ValueError("neutral primitive_count does not match payload")
        source_count = _bounded_integer(
            representation.get("source_item_count"), "neutral source_item_count",
            _MAX_PREVIEW_SOURCE_ITEMS,
        )
        rendered_count = _bounded_integer(
            representation.get("rendered_item_count"), "neutral rendered_item_count",
            _MAX_NEUTRAL_SOURCE_ITEMS_PER_LAYER,
        )
        if rendered_count > source_count:
            raise ValueError("neutral rendered_item_count exceeds source_item_count")
        coverage = representation.get("coverage")
        if isinstance(coverage, bool) or not isinstance(coverage, (int, float)) or not 0 <= coverage <= 1:
            raise ValueError("neutral coverage must be between zero and one")
        expected_coverage = 1.0 if source_count == 0 else rendered_count / source_count
        if float(coverage) != expected_coverage:
            raise ValueError("neutral coverage does not match rendered/source item counts")
        expected_representation = "deterministic_lod" if rendered_count < source_count else "full_geometry"
        if representation.get("representation") != expected_representation:
            raise ValueError("neutral representation does not match item counts")
        if representation.get("schema_version") != _NEUTRAL_SCHEMA_VERSION:
            raise ValueError("neutral schema_version is invalid")
        expected_primitive_fingerprint = fingerprint_value(primitives)
        if representation.get("fingerprint") != expected_primitive_fingerprint:
            raise ValueError("neutral primitive fingerprint does not match payload")
        canonical_primitives = json.dumps(
            thaw_value(primitives), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        payload_byte_count = _bounded_integer(
            representation.get("payload_byte_count"), "neutral payload_byte_count",
            _MAX_NEUTRAL_PRIMITIVE_BYTES_PER_LAYER,
        )
        if payload_byte_count != len(canonical_primitives):
            raise ValueError("neutral payload_byte_count does not match canonical payload")
        fingerprints = _sequence(row.get("source_fingerprints"), "preview layer source_fingerprints")
        if any(not isinstance(value, str) or not value for value in fingerprints):
            raise ValueError("preview layer source_fingerprints must contain non-empty strings")
        layer_fingerprint = _string(row.get("fingerprint"), "preview layer fingerprint")
        expected_layer_fingerprint = fingerprint_value(
            {
                "layer_id": row.get("layer_id"),
                "payload": payload,
                "source_fingerprints": tuple(fingerprints),
            }
        )
        if layer_fingerprint != expected_layer_fingerprint:
            raise ValueError("preview layer fingerprint does not match layer payload")
        verified_layer_fingerprints.append(layer_fingerprint)

    counts = _sequence(raw.get("counts"), "preview counts")
    count_rows = tuple(_closed_mapping(row, _COUNT_KEYS, "preview count") for row in counts)
    metric_ids = tuple(_string(row.get("metric"), "metric") for row in count_rows)
    if metric_ids != PREVIEW_COUNT_METRICS:
        raise ValueError("preview metric order does not match the closed Phase 18E contract")
    for count in count_rows:
        value = count.get("value")
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("preview count value must be a non-negative integer")
        if count.get("semantics") not in {"exact", "upper_bound"}:
            raise ValueError("preview count semantics must be exact or upper_bound")

    revision = raw.get("project_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("preview project_revision must be a positive integer")
    expected_preview_fingerprint = fingerprint_value(
        {
            "project_id": raw.get("project_id"),
            "scenario_id": raw.get("scenario_id"),
            "project_revision": revision,
            "cache_key": raw.get("cache_key"),
            "layers": tuple(verified_layer_fingerprints),
            "counts": tuple(
                (row.get("metric"), row.get("value"), row.get("semantics"))
                for row in count_rows
            ),
            "is_final": raw.get("is_final"),
        }
    )
    if raw.get("fingerprint") != expected_preview_fingerprint:
        raise ValueError("preview fingerprint does not match authoritative payload")
    return thaw_value(raw)


def _domain_payload(preview: RefinedBlastPreview) -> dict[str, object]:
    return {
        "project_id": preview.project_id,
        "scenario_id": preview.scenario_id,
        "project_revision": preview.project_revision,
        "cache_key": preview.cache_key,
        "is_final": preview.is_final,
        "fingerprint": preview.fingerprint,
        "layers": [
            {
                "layer_id": layer.layer_id,
                "payload": thaw_value(layer.payload),
                "source_fingerprints": list(layer.source_fingerprints),
                "fingerprint": layer.fingerprint,
            }
            for layer in preview.layers
        ],
        "counts": [
            {"metric": row.metric, "value": row.value, "semantics": row.semantics}
            for row in preview.counts
        ],
    }


def _mapping_payload(preview: Mapping[str, object]) -> dict[str, object]:
    return {str(key): thaw_value(value) for key, value in preview.items()}


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _closed_mapping(
    value: object, expected: frozenset[str], label: str,
) -> Mapping[str, object]:
    row = _mapping(value, label)
    unknown = sorted(set(row) - expected)
    missing = sorted(expected - set(row))
    if unknown:
        raise ValueError(f"{label} has unknown field: {unknown[0]!r}")
    if missing:
        raise ValueError(f"{label} is missing field: {missing[0]!r}")
    return row


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label} must be an array")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _bounded_integer(value: object, label: str, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
        raise ValueError(f"{label} must be a bounded non-negative integer")
    return value


__all__ = ["build_refined_blast_web_preview"]
