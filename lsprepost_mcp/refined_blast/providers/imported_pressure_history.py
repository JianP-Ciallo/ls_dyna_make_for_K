"""Audited imported pressure-history load provider.

The compiler only accepts caller-supplied bytes or rows.  It never opens a
path, launches a program, or treats an imported curve as calibrated engineering
evidence.  Its output is a deterministic, review-required neutral fragment.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from ..contracts import Finding
from .common import (
    FrozenMapping,
    ProviderContext,
    ProviderEstimate,
    ProviderEvidence,
    ProviderFragment,
    fingerprint_value,
    freeze_value,
    source_space_evidence,
    surface_geometry_from_artifact,
    validate_source_space,
)


_ROOT_KEYS = frozenset({"schema_version", "unit_system", "source", "units", "curve", "mapping", "budgets"})
_SOURCE_BASE_KEYS = frozenset(
    {"schema_version", "source_id", "source_name", "form", "source_space_id"}
)
_LEGACY_SOURCE_BASE_KEYS = frozenset(
    {"schema_version", "source_id", "source_name", "form"}
)
_UNITS_KEYS = frozenset({"schema_version", "time_unit", "pressure_unit"})
_CURVE_KEYS = frozenset({"schema_version", "interpolation", "scale"})
_NORMALIZED_SOURCE_KEYS = _SOURCE_BASE_KEYS | frozenset({"source_sha256"})
_NORMALIZED_CURVE_KEYS = _CURVE_KEYS | frozenset(
    {
        "normalized_curve_si",
        "source_sha256",
        "normalized_curve_sha256",
        "source_byte_count",
    }
)
_MAPPING_KEYS = frozenset({"schema_version", "surface_category", "target_face_ids"})
_BUDGET_KEYS = frozenset({"schema_version", "max_input_bytes", "max_row_count", "max_target_surface_count"})
_VERSIONS = {
    "input": "imported_pressure_history@2",
    "source": "imported_pressure_history.source@2",
    "units": "imported_pressure_history.units@1",
    "curve": "imported_pressure_history.curve@1",
    "mapping": "imported_pressure_history.mapping@1",
    "budgets": "imported_pressure_history.budgets@1",
}
_LEGACY_INPUT_VERSION = "imported_pressure_history@1"
_LEGACY_SOURCE_VERSION = "imported_pressure_history.source@1"
_UNIT_SYSTEM = "SI_m_s_kg_N_Pa"
_TIME_FACTORS_TO_S = MappingProxyType({"s": 1.0, "ms": 1.0e-3, "us": 1.0e-6})
_PRESSURE_FACTORS_TO_PA = MappingProxyType({"Pa": 1.0, "kPa": 1.0e3, "MPa": 1.0e6, "bar": 1.0e5})
_INTERPOLATIONS = frozenset({"linear", "step"})
_MAPPING_CATEGORIES = frozenset({"exterior_surfaces", "interior_cavity_surfaces"})
_CATEGORIES_BY_KIND = {
    "external": frozenset({"exterior_surfaces"}),
    "internal": frozenset({"interior_cavity_surfaces"}),
    "semi_enclosed": frozenset({"exterior_surfaces", "interior_cavity_surfaces"}),
}
_SAFE_ID_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
_SAFE_SURFACE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]*")
_AREA_TOLERANCE_M2 = 1.0e-12
_GEOMETRY_TOLERANCE = 1.0e-9
_HARD_MAX_INPUT_BYTES = 4 * 1024 * 1024
_HARD_MAX_ROW_COUNT = 1_000_000
_HARD_MAX_TARGET_SURFACE_COUNT = 100_000
_MAX_STRUCTURED_INTEGER_BITS = 4096


def _input_ui_schema() -> dict[str, object]:
    string = {"type": "string"}
    number = {"type": "number"}
    def source_branch(version: str, *, current: bool, form: str) -> dict[str, object]:
        properties = {"schema_version": {"type": "string", "const": version}, "source_id": string, "source_name": string, "form": {"type": "string", "const": form}}
        if current: properties["source_space_id"] = string
        if form == "structured_rows": properties["rows"] = {"type": "array", "items": {"type": "array", "items": number, "minItems": 2, "maxItems": 2}}
        else: properties["utf8_csv_base64"] = string
        required = list(properties)
        return {"type": "object", "additionalProperties": False, "required": sorted(required), "properties": properties}
    return {
        "type": "object", "additionalProperties": False, "required": sorted(_ROOT_KEYS), "properties": {
            "schema_version": {"type": "string", "enum": [_LEGACY_INPUT_VERSION, _VERSIONS["input"]]}, "unit_system": {"type": "string", "const": _UNIT_SYSTEM},
            # Browser transport is JSON-only.  The bytes variant remains a
            # programmatic provider contract, but is deliberately not claimed
            # by this browser UI schema until a reviewed transport adapter is
            # introduced.
            "source": {"oneOf": [source_branch(_LEGACY_SOURCE_VERSION, current=False, form="structured_rows"), source_branch(_VERSIONS["source"], current=True, form="structured_rows")]},
            "units": {"type": "object", "additionalProperties": False, "required": sorted(_UNITS_KEYS), "properties": {"schema_version": {"type": "string", "const": _VERSIONS["units"]}, "time_unit": {"type": "string", "enum": sorted(_TIME_FACTORS_TO_S)}, "pressure_unit": {"type": "string", "enum": sorted(_PRESSURE_FACTORS_TO_PA)}}},
            "curve": {"type": "object", "additionalProperties": False, "required": sorted(_CURVE_KEYS), "properties": {"schema_version": {"type": "string", "const": _VERSIONS["curve"]}, "interpolation": {"type": "string", "enum": sorted(_INTERPOLATIONS)}, "scale": number}},
            "mapping": {"type": "object", "additionalProperties": False, "required": sorted(_MAPPING_KEYS), "properties": {"schema_version": {"type": "string", "const": _VERSIONS["mapping"]}, "surface_category": {"type": "string", "enum": sorted(_MAPPING_CATEGORIES)}, "target_face_ids": {"type": "array", "items": string}}},
            "budgets": {"type": "object", "additionalProperties": False, "required": sorted(_BUDGET_KEYS), "properties": {key: ({"type": "string", "const": _VERSIONS["budgets"]} if key == "schema_version" else {"type": "integer"}) for key in _BUDGET_KEYS}},
        },
    }
@dataclass(frozen=True, slots=True)
class _TargetFace:
    face_id: str
    element_id: int
    area_m2: float


@dataclass(frozen=True, slots=True)
class _ValidatedState:
    normalized: FrozenMapping
    source_sha256: str
    normalized_curve_sha256: str
    source_byte_count: int
    normalized_curve_si: tuple[tuple[float, float], ...]
    targets: tuple[_TargetFace, ...]
    source_space_id: str


class ImportedPressureHistoryProvider:
    """Compile a finite, unit-normalized imported pressure curve.

    Import provenance, calibration, and engineering applicability are not
    validated by software.  They remain explicit project-review obligations.
    """

    provider_id = "imported_pressure_history"

    def default_input(self) -> Mapping[str, object]:
        """JSON-safe structured-row seed; byte upload has no web transport yet."""

        return {
            "schema_version": _LEGACY_INPUT_VERSION, "unit_system": _UNIT_SYSTEM,
            "source": {"schema_version": _LEGACY_SOURCE_VERSION, "source_id": "history-1", "source_name": "default-history", "form": "structured_rows", "rows": [[0.0, 0.0], [0.1, 1.0]]},
            "units": {"schema_version": _VERSIONS["units"], "time_unit": "s", "pressure_unit": "Pa"},
            "curve": {"schema_version": _VERSIONS["curve"], "interpolation": "linear", "scale": 1.0},
            "mapping": {"schema_version": _VERSIONS["mapping"], "surface_category": "exterior_surfaces", "target_face_ids": []},
            "budgets": {"schema_version": _VERSIONS["budgets"], "max_input_bytes": 4096, "max_row_count": 100, "max_target_surface_count": 1000},
        }

    def schema(self) -> Mapping[str, object]:
        value = freeze_value(
            {
                "schema_version": _VERSIONS["input"],
                "unit_system": _UNIT_SYSTEM,
                "exact_root_keys": tuple(sorted(_ROOT_KEYS)),
                "source_forms": ("structured_rows", "utf8_csv_bytes"),
                "browser_transport_forms": ("structured_rows",),
                "time_units": tuple(sorted(_TIME_FACTORS_TO_S)),
                "pressure_units": tuple(sorted(_PRESSURE_FACTORS_TO_PA)),
                "interpolations": tuple(sorted(_INTERPOLATIONS)),
                "nested_schema_versions": dict(sorted(_VERSIONS.items())),
                "accepted_migrations": (_LEGACY_INPUT_VERSION,),
                "input_schema": _input_ui_schema(),
            },
            "schema",
        )
        assert isinstance(value, Mapping)
        return value

    def capabilities(self) -> Mapping[str, object]:
        value = freeze_value(
            {
                "provider_id": self.provider_id,
                "scenario_kinds": ("external", "internal", "semi_enclosed"),
                "source_forms": ("structured_rows", "utf8_csv_bytes"),
                "filesystem_paths_accepted": False,
                "launches_external_programs": False,
                "software_candidate_only": True,
                "solver_ready": False,
                "requires_project_review": True,
                "engineering_validated": False,
                "provenance_calibration_and_applicability_validated": False,
            },
            "capabilities",
        )
        assert isinstance(value, Mapping)
        return value

    def normalize(self, value: Mapping[str, object]) -> FrozenMapping:
        raw = _closed_mapping(value, _ROOT_KEYS, "imported_pressure_history")
        input_version = _safe_string(raw.get("schema_version"), "schema_version")
        if input_version not in {_VERSIONS["input"], _LEGACY_INPUT_VERSION}:
            raise ValueError(
                "imported_pressure_history.schema_version must be "
                f"{_VERSIONS['input']!r} or legacy {_LEGACY_INPUT_VERSION!r}"
            )
        is_legacy = input_version == _LEGACY_INPUT_VERSION
        _require_literal(raw, "unit_system", _UNIT_SYSTEM, "imported_pressure_history")

        budgets = _closed_mapping(raw["budgets"], _BUDGET_KEYS, "imported_pressure_history.budgets")
        _require_literal(budgets, "schema_version", _VERSIONS["budgets"], "budgets")
        normalized_budgets = {
            "schema_version": _VERSIONS["budgets"],
            "max_input_bytes": _bounded_positive_integer(
                budgets.get("max_input_bytes"), "budgets.max_input_bytes", _HARD_MAX_INPUT_BYTES
            ),
            "max_row_count": _bounded_positive_integer(
                budgets.get("max_row_count"), "budgets.max_row_count", _HARD_MAX_ROW_COUNT
            ),
            "max_target_surface_count": _bounded_positive_integer(
                budgets.get("max_target_surface_count"),
                "budgets.max_target_surface_count",
                _HARD_MAX_TARGET_SURFACE_COUNT,
            ),
        }
        source_mapping = _as_mapping(raw["source"], "imported_pressure_history.source")
        if input_version == _VERSIONS["input"] and "source_sha256" in source_mapping:
            return _normalize_persisted_input(raw, normalized_budgets)
        legacy_space: str | None = None
        if is_legacy:
            legacy_mapping = _as_mapping(raw["mapping"], "imported_pressure_history.mapping")
            legacy_category = _safe_string(
                legacy_mapping.get("surface_category"), "mapping.surface_category"
            )
            if legacy_category != "exterior_surfaces":
                raise ValueError(
                    "legacy imported pressure input cannot infer an interior source_space_id; "
                    "migrate explicitly to imported_pressure_history@2"
                )
            legacy_space = "exterior"
        source, source_sha256, source_byte_count, rows = self._normalize_source(
            raw["source"], normalized_budgets, legacy_space=legacy_space
        )

        units = _closed_mapping(raw["units"], _UNITS_KEYS, "imported_pressure_history.units")
        _require_literal(units, "schema_version", _VERSIONS["units"], "units")
        time_unit = _safe_string(units.get("time_unit"), "units.time_unit")
        pressure_unit = _safe_string(units.get("pressure_unit"), "units.pressure_unit")
        if time_unit not in _TIME_FACTORS_TO_S:
            raise ValueError(f"unsupported time_unit: {time_unit!r}")
        if pressure_unit not in _PRESSURE_FACTORS_TO_PA:
            raise ValueError(f"unsupported pressure_unit: {pressure_unit!r}")

        curve = _closed_mapping(raw["curve"], _CURVE_KEYS, "imported_pressure_history.curve")
        _require_literal(curve, "schema_version", _VERSIONS["curve"], "curve")
        interpolation = _safe_string(curve.get("interpolation"), "curve.interpolation")
        if interpolation not in _INTERPOLATIONS:
            raise ValueError(f"unsupported interpolation: {interpolation!r}")
        scale = _finite_number(curve.get("scale"), "curve.scale")
        if scale < 0.0:
            raise ValueError("curve.scale must not be negative")
        normalized_curve = _normalize_curve_rows(
            rows,
            time_factor=_TIME_FACTORS_TO_S[time_unit],
            pressure_factor=_PRESSURE_FACTORS_TO_PA[pressure_unit],
            scale=scale,
        )
        normalized_curve_sha256 = _sha256_canonical(normalized_curve)

        mapping = _closed_mapping(raw["mapping"], _MAPPING_KEYS, "imported_pressure_history.mapping")
        _require_literal(mapping, "schema_version", _VERSIONS["mapping"], "mapping")
        category = _safe_string(mapping.get("surface_category"), "mapping.surface_category")
        if category not in _MAPPING_CATEGORIES:
            raise ValueError(f"unsupported surface category: {category!r}")
        target_ids = _string_sequence(mapping.get("target_face_ids"), "mapping.target_face_ids")
        target_ids = tuple(
            _safe_surface_id(item, f"mapping.target_face_ids[{index}]")
            for index, item in enumerate(target_ids)
        )
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("mapping.target_face_ids must not contain duplicate ids")
        if len(target_ids) > normalized_budgets["max_target_surface_count"]:
            raise ValueError("target surface count budget exceeded before surface allocation")

        normalized = freeze_value(
            {
                "schema_version": _VERSIONS["input"],
                "unit_system": _UNIT_SYSTEM,
                "source": source,
                "units": {
                    "schema_version": _VERSIONS["units"],
                    "time_unit": time_unit,
                    "pressure_unit": pressure_unit,
                },
                "curve": {
                    "schema_version": _VERSIONS["curve"],
                    "interpolation": interpolation,
                    "scale": scale,
                    "normalized_curve_si": normalized_curve,
                    "source_sha256": source_sha256,
                    "normalized_curve_sha256": normalized_curve_sha256,
                    "source_byte_count": source_byte_count,
                },
                "mapping": {
                    "schema_version": _VERSIONS["mapping"],
                    "surface_category": category,
                    "target_face_ids": target_ids,
                },
                "budgets": normalized_budgets,
            },
            "imported_pressure_history",
        )
        assert isinstance(normalized, Mapping)
        return normalized

    def validate(self, value: Mapping[str, object], context: ProviderContext) -> tuple[Finding, ...]:
        try:
            self._validate_state(self.normalize(value), context)
        except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError, csv.Error) as exc:
            return (
                Finding(
                    finding_id=f"imported_pressure_history:{fingerprint_value(str(exc))[:16]}",
                    severity="error",
                    message=str(exc),
                ),
            )
        return ()

    def estimate(self, value: Mapping[str, object], context: ProviderContext) -> ProviderEstimate:
        return self._estimate_state(self._validate_state(self.normalize(value), context))

    def compile(self, value: Mapping[str, object], context: ProviderContext) -> ProviderFragment:
        state = self._validate_state(self.normalize(value), context)
        estimate = self._estimate_state(state)
        source = _nested_mapping(state.normalized, "source")
        curve = _nested_mapping(state.normalized, "curve")
        mapping = _nested_mapping(state.normalized, "mapping")
        face_ids = tuple(target.face_id for target in state.targets)
        element_ids = tuple(target.element_id for target in state.targets)
        required_ids = frozenset(
            (
                *(f"surface:{face_id}" for face_id in face_ids),
                *(f"building:element:{element_id}" for element_id in element_ids),
                f"artifact:{context.artifact.fingerprint}",
                f"topology:{context.topology.fingerprint}",
            )
        )
        declared_base = frozenset(
            {
                f"imported_pressure_history:source:{_mapping_string(source, 'source_id')}",
                f"estimate:{estimate.fingerprint}",
            }
        )
        evidence = self._build_evidence(state, context, estimate)
        declared_ids = declared_base | frozenset(row.evidence_id for row in evidence)
        evidence_source_ids = frozenset(source_id for row in evidence for source_id in row.source_ids)
        missing = (required_ids | evidence_source_ids) - (context.available_ids | declared_ids)
        if missing:
            raise ValueError(f"provider fragment has unclosed id: {sorted(missing)[0]!r}")
        manifest = {
            "schema_version": "imported_pressure_history.fragment@1",
            "provider_id": self.provider_id,
            "scenario_kind": context.scenario_kind,
            "building_artifact_fingerprint": context.artifact.fingerprint,
            "topology_fingerprint": context.topology.fingerprint,
            "input_fingerprint": fingerprint_value(state.normalized),
            "source": source,
            "normalized_curve_si": state.normalized_curve_si,
            "curve": curve,
            "mapping": {
                "surface_category": _mapping_string(mapping, "surface_category"),
                "target_face_ids": face_ids,
                "target_element_ids": element_ids,
                "target_total_area_m2": math.fsum(
                    target.area_m2 for target in state.targets
                ),
            },
            "allocation": {
                "estimate": estimate.to_manifest(),
                "actual_node_count": 0,
                "actual_element_count": 0,
                "actual_curve_row_count": len(state.normalized_curve_si),
                "actual_target_surface_count": len(face_ids),
                "budget_checked_before_allocation": True,
            },
            "evidence_fingerprints": tuple(row.fingerprint for row in evidence),
            "id_closure": {
                "required_ids": tuple(sorted(required_ids)),
                "declared_ids": tuple(sorted(declared_ids)),
                "evidence_ids": tuple(row.evidence_id for row in evidence),
                "closed": True,
            },
            "software_candidate_only": True,
            "solver_ready": False,
            "requires_project_review": True,
            "engineering_validated": False,
            "imported_history_provenance_calibration_and_applicability_validated": False,
            "external_program_started": False,
        }
        return ProviderFragment(
            provider_id=self.provider_id,
            normalized_input=state.normalized,
            axes_m=((), (), ()),
            node_ids=(),
            element_ids=(),
            fsi_face_ids=face_ids,
            required_ids=required_ids,
            declared_ids=declared_ids,
            evidence=evidence,
            manifest=manifest,
        )

    def preview(self, value: Mapping[str, object], context: ProviderContext) -> FrozenMapping:
        state = self._validate_state(self.normalize(value), context)
        value = freeze_value(
            {
                "provider_id": self.provider_id,
                "scenario_kind": context.scenario_kind,
                "normalized_curve_si": state.normalized_curve_si,
                "target_face_ids": tuple(target.face_id for target in state.targets),
                "software_candidate_only": True,
                "solver_ready": False,
                "requires_project_review": True,
            },
            "imported_pressure_history.preview",
        )
        assert isinstance(value, Mapping)
        return value

    def _normalize_source(
        self,
        value: object,
        budgets: Mapping[str, object],
        *,
        legacy_space: str | None,
    ) -> tuple[dict[str, object], str, int, tuple[tuple[float, float], ...]]:
        source = _as_mapping(value, "imported_pressure_history.source")
        form = _safe_string(source.get("form"), "source.form")
        base_keys = _LEGACY_SOURCE_BASE_KEYS if legacy_space is not None else _SOURCE_BASE_KEYS
        expected = base_keys | ({"rows"} if form == "structured_rows" else {"bytes"} if form == "utf8_csv_bytes" else set())
        _require_exact_keys(source, expected, "imported_pressure_history.source")
        _require_literal(
            source,
            "schema_version",
            _LEGACY_SOURCE_VERSION if legacy_space is not None else _VERSIONS["source"],
            "source",
        )
        source_id = _safe_identifier(source.get("source_id"), "source.source_id")
        source_name = _safe_identifier(source.get("source_name"), "source.source_name")
        source_space_id = _safe_identifier(
            legacy_space if legacy_space is not None else source.get("source_space_id"),
            "source.source_space_id",
        )
        max_bytes = _mapping_integer(budgets, "max_input_bytes")
        max_rows = _mapping_integer(budgets, "max_row_count")
        if form == "structured_rows":
            raw_rows = source.get("rows")
            if not _is_sequence(raw_rows):
                raise ValueError("source.rows must be a sequence")
            if len(raw_rows) > max_rows:
                raise ValueError("row count budget exceeded before row normalization")
            _validate_structured_row_shapes(raw_rows)
            try:
                raw_bytes = _bounded_json_bytes(raw_rows, max_bytes)
            except (TypeError, ValueError) as exc:
                if str(exc).startswith("input byte budget exceeded"):
                    raise
                raise ValueError("source.rows must contain JSON-compatible values") from exc
            rows = tuple(_row_pair(row, f"source.rows[{index}]") for index, row in enumerate(raw_rows))
        elif form == "utf8_csv_bytes":
            raw_bytes = source.get("bytes")
            if not isinstance(raw_bytes, bytes):
                raise ValueError("source.bytes must be immutable bytes")
            if len(raw_bytes) > max_bytes:
                raise ValueError("input byte budget exceeded before decoding")
            rows = _decode_csv_rows(raw_bytes, max_rows)
        else:
            raise ValueError(f"unsupported source.form: {form!r}")
        if len(raw_bytes) > max_bytes:
            raise ValueError("input byte budget exceeded before curve normalization")
        return (
            {
                "schema_version": _VERSIONS["source"],
                "source_id": source_id,
                "source_name": source_name,
                "form": form,
                "source_space_id": source_space_id,
                "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            },
            hashlib.sha256(raw_bytes).hexdigest(),
            len(raw_bytes),
            rows,
        )

    def _validate_state(self, normalized: FrozenMapping, context: ProviderContext) -> _ValidatedState:
        mapping = _nested_mapping(normalized, "mapping")
        category = _mapping_string(mapping, "surface_category")
        if category not in _CATEGORIES_BY_KIND[context.scenario_kind]:
            raise ValueError(
                f"surface category {category!r} is invalid for {context.scenario_kind} scenario"
            )
        budgets = _nested_mapping(normalized, "budgets")
        source_space_id = validate_source_space(
            _mapping_string(_nested_mapping(normalized, "source"), "source_space_id"),
            context,
            surface_category=category,
        )
        targets = _validated_targets(
            context,
            category,
            _string_sequence(mapping.get("target_face_ids"), "mapping.target_face_ids"),
            _mapping_integer(budgets, "max_target_surface_count"),
        )
        curve = _nested_mapping(normalized, "curve")
        rows = _curve_rows(curve.get("normalized_curve_si"), "curve.normalized_curve_si")
        if len(rows) > _mapping_integer(budgets, "max_row_count"):
            raise ValueError("row count budget exceeded before fragment allocation")
        return _ValidatedState(
            normalized=normalized,
            source_sha256=_mapping_string(curve, "source_sha256"),
            normalized_curve_sha256=_mapping_string(curve, "normalized_curve_sha256"),
            source_byte_count=_mapping_integer(curve, "source_byte_count"),
            normalized_curve_si=rows,
            targets=targets,
            source_space_id=source_space_id,
        )

    def _estimate_state(self, state: _ValidatedState) -> ProviderEstimate:
        budgets = _nested_mapping(state.normalized, "budgets")
        return ProviderEstimate(
            provider_id=self.provider_id,
            axis_point_counts=(0, 0, 0),
            node_count=0,
            element_count=0,
            budget_limits=MappingProxyType(
                {
                    "max_input_bytes": _mapping_integer(budgets, "max_input_bytes"),
                    "max_row_count": _mapping_integer(budgets, "max_row_count"),
                    "max_target_surface_count": _mapping_integer(budgets, "max_target_surface_count"),
                }
            ),
            budget_checked_before_allocation=True,
        )

    def _build_evidence(
        self, state: _ValidatedState, context: ProviderContext, estimate: ProviderEstimate
    ) -> tuple[ProviderEvidence, ...]:
        mapping = _nested_mapping(state.normalized, "mapping")
        source = _nested_mapping(state.normalized, "source")
        source_declared_id = (
            f"imported_pressure_history:source:{_mapping_string(source, 'source_id')}"
        )
        source_evidence = source_space_evidence(
            provider_id=self.provider_id,
            source_declared_id=source_declared_id,
            source_space_id=state.source_space_id,
            context=context,
            determination="declared_surface_mapping",
            surface_category=_mapping_string(mapping, "surface_category"),
        )
        rows = (
            (
                "imported_pressure_history_normalization",
                (f"artifact:{context.artifact.fingerprint}", f"topology:{context.topology.fingerprint}"),
                {
                    "source_sha256": state.source_sha256,
                    "normalized_curve_sha256": state.normalized_curve_sha256,
                    "source_byte_count": state.source_byte_count,
                    "normalized_row_count": len(state.normalized_curve_si),
                    "normalization_parameters": {
                        "time_unit": _mapping_string(_nested_mapping(state.normalized, "units"), "time_unit"),
                        "pressure_unit": _mapping_string(_nested_mapping(state.normalized, "units"), "pressure_unit"),
                        "scale": _mapping_number(_nested_mapping(state.normalized, "curve"), "scale"),
                        "interpolation": _mapping_string(_nested_mapping(state.normalized, "curve"), "interpolation"),
                    },
                },
            ),
            (
                "pressure_history_surface_mapping",
                tuple(f"surface:{target.face_id}" for target in state.targets),
                {
                    "surface_category": _mapping_string(mapping, "surface_category"),
                    "target_face_ids": tuple(target.face_id for target in state.targets),
                    "target_element_ids": tuple(target.element_id for target in state.targets),
                    "target_total_area_m2": math.fsum(
                        target.area_m2 for target in state.targets
                    ),
                },
            ),
            (
                "preallocation_budget",
                (f"estimate:{estimate.fingerprint}",),
                {
                    "input_byte_count": state.source_byte_count,
                    "row_count": len(state.normalized_curve_si),
                    "target_surface_count": len(state.targets),
                    "budget_checked_before_allocation": True,
                },
            ),
            (
                "imported_history_engineering_boundary",
                (),
                {
                    "solver_ready": False,
                    "requires_project_review": True,
                    "engineering_validated": False,
                    "provenance_calibration_and_engineering_applicability_validated": False,
                },
            ),
        )
        result: list[ProviderEvidence] = []
        for index, (kind, source_ids, claims) in enumerate(rows, start=1):
            digest = fingerprint_value({"kind": kind, "source_ids": source_ids, "claims": claims})
            result.append(
                ProviderEvidence(
                    evidence_id=f"imported_pressure_history:evidence:{index}:{digest[:16]}",
                    evidence_kind=kind,
                    source_ids=source_ids,
                    claims=claims,
                )
            )
        result.append(source_evidence)
        return tuple(result)


def _validated_targets(
    context: ProviderContext, category: str, requested_ids: tuple[str, ...], maximum: int
) -> tuple[_TargetFace, ...]:
    context_rows = _catalog_sequence(context.surface_catalog, category)
    if not requested_ids and len(context_rows) > maximum:
        raise ValueError("target surface count budget exceeded before target catalog allocation")
    selected_ids = tuple(sorted(requested_ids)) if requested_ids else ()
    wanted_ids = set(selected_ids)
    context_by_id: dict[str, Mapping[str, object]] = {}
    for raw_row in context_rows:
        row = _as_mapping(raw_row, f"surface_catalog.{category}")
        face_id = _mapping_string(row, "face_id")
        if not requested_ids:
            wanted_ids.add(face_id)
        if face_id not in wanted_ids:
            continue
        if face_id in context_by_id:
            raise ValueError(f"surface catalog contains duplicate face id: {face_id!r}")
        context_by_id[face_id] = row
    if not wanted_ids:
        raise ValueError("surface mapping has no target faces")
    if len(wanted_ids) > maximum:
        raise ValueError("target surface count budget exceeded before target allocation")
    missing_context = sorted(wanted_ids - set(context_by_id))
    if missing_context:
        raise ValueError(f"target face is not in selected surface category: {missing_context[0]!r}")

    artifact_rows = _catalog_sequence(context.artifact.surface_catalog, category)
    artifact_by_id: dict[str, Mapping[str, object]] = {}
    for raw_row in artifact_rows:
        row = _as_mapping(raw_row, f"artifact.surface_catalog.{category}")
        face_id = _mapping_string(row, "face_id")
        if face_id not in wanted_ids:
            continue
        if face_id in artifact_by_id:
            raise ValueError(f"artifact surface catalog contains duplicate face id: {face_id!r}")
        artifact_by_id[face_id] = row
    missing_artifact = sorted(wanted_ids - set(artifact_by_id))
    if missing_artifact:
        raise ValueError(f"surface {missing_artifact[0]!r} does not match artifact surface catalog")

    selected_ids = tuple(sorted(wanted_ids))
    element_by_id = {
        element.element_id: element
        for element in (*context.artifact.mesh.solids, *context.artifact.mesh.shells)
    }
    targets: list[_TargetFace] = []
    for face_id in selected_ids:
        row = context_by_id[face_id]
        if fingerprint_value(row) != fingerprint_value(artifact_by_id[face_id]):
            raise ValueError(f"surface {face_id!r} does not match artifact surface catalog")
        element_id = _mapping_integer(row, "element_id")
        element = element_by_id.get(element_id)
        if element is None:
            raise ValueError(f"surface {face_id!r} element_id does not exist in the structural mesh")
        raw_nodes = row.get("node_ids")
        if not _is_sequence(raw_nodes) or len(raw_nodes) not in {3, 4}:
            raise ValueError(f"surface {face_id!r} must contain three or four structural node ids")
        area, centroid, normal = surface_geometry_from_artifact(
            context.artifact, row, f"surface {face_id!r}"
        )
        if area <= _AREA_TOLERANCE_M2:
            raise ValueError(f"surface {face_id!r} must have positive area")
        targets.append(_TargetFace(face_id, element_id, area))
    return tuple(targets)


def _normalize_persisted_input(
    raw: Mapping[str, object], normalized_budgets: Mapping[str, object]
) -> FrozenMapping:
    """Validate and preserve the canonical, source-free Store representation."""

    source = _closed_mapping(
        raw["source"], _NORMALIZED_SOURCE_KEYS, "imported_pressure_history.source"
    )
    _require_literal(source, "schema_version", _VERSIONS["source"], "source")
    source_id = _safe_identifier(source.get("source_id"), "source.source_id")
    source_name = _safe_identifier(source.get("source_name"), "source.source_name")
    source_space_id = _safe_identifier(source.get("source_space_id"), "source.source_space_id")
    form = _safe_string(source.get("form"), "source.form")
    if form not in {"structured_rows", "utf8_csv_bytes"}:
        raise ValueError(f"unsupported source.form: {form!r}")
    source_sha256 = _sha256_digest(source.get("source_sha256"), "source.source_sha256")

    units = _closed_mapping(raw["units"], _UNITS_KEYS, "imported_pressure_history.units")
    _require_literal(units, "schema_version", _VERSIONS["units"], "units")
    time_unit = _safe_string(units.get("time_unit"), "units.time_unit")
    pressure_unit = _safe_string(units.get("pressure_unit"), "units.pressure_unit")
    if time_unit not in _TIME_FACTORS_TO_S:
        raise ValueError(f"unsupported time_unit: {time_unit!r}")
    if pressure_unit not in _PRESSURE_FACTORS_TO_PA:
        raise ValueError(f"unsupported pressure_unit: {pressure_unit!r}")

    curve = _closed_mapping(raw["curve"], _NORMALIZED_CURVE_KEYS, "imported_pressure_history.curve")
    _require_literal(curve, "schema_version", _VERSIONS["curve"], "curve")
    interpolation = _safe_string(curve.get("interpolation"), "curve.interpolation")
    if interpolation not in _INTERPOLATIONS:
        raise ValueError(f"unsupported interpolation: {interpolation!r}")
    scale = _finite_number(curve.get("scale"), "curve.scale")
    if scale < 0.0:
        raise ValueError("curve.scale must not be negative")
    rows = _curve_rows(curve.get("normalized_curve_si"), "curve.normalized_curve_si")
    rows = _normalize_curve_rows(rows, time_factor=1.0, pressure_factor=1.0, scale=1.0)
    if len(rows) > _mapping_integer(normalized_budgets, "max_row_count"):
        raise ValueError("row count budget exceeded in persisted normalized curve")
    curve_source_sha256 = _sha256_digest(curve.get("source_sha256"), "curve.source_sha256")
    if curve_source_sha256 != source_sha256:
        raise ValueError("persisted source hashes do not match")
    normalized_sha256 = _sha256_digest(
        curve.get("normalized_curve_sha256"), "curve.normalized_curve_sha256"
    )
    if normalized_sha256 != _sha256_canonical(rows):
        raise ValueError("persisted normalized curve hash does not match its rows")
    source_byte_count = _bounded_positive_integer(
        curve.get("source_byte_count"),
        "curve.source_byte_count",
        _mapping_integer(normalized_budgets, "max_input_bytes"),
    )

    mapping = _closed_mapping(raw["mapping"], _MAPPING_KEYS, "imported_pressure_history.mapping")
    _require_literal(mapping, "schema_version", _VERSIONS["mapping"], "mapping")
    category = _safe_string(mapping.get("surface_category"), "mapping.surface_category")
    if category not in _MAPPING_CATEGORIES:
        raise ValueError(f"unsupported surface category: {category!r}")
    target_ids = tuple(
        _safe_surface_id(value, f"mapping.target_face_ids[{index}]")
        for index, value in enumerate(
            _string_sequence(mapping.get("target_face_ids"), "mapping.target_face_ids")
        )
    )
    if len(target_ids) != len(set(target_ids)):
        raise ValueError("mapping.target_face_ids must not contain duplicate ids")
    if len(target_ids) > _mapping_integer(normalized_budgets, "max_target_surface_count"):
        raise ValueError("target surface count budget exceeded in persisted input")

    normalized = freeze_value(
        {
            "schema_version": _VERSIONS["input"],
            "unit_system": _UNIT_SYSTEM,
            "source": {
                "schema_version": _VERSIONS["source"],
                "source_id": source_id,
                "source_name": source_name,
                "source_space_id": source_space_id,
                "form": form,
                "source_sha256": source_sha256,
            },
            "units": {"schema_version": _VERSIONS["units"], "time_unit": time_unit, "pressure_unit": pressure_unit},
            "curve": {
                "schema_version": _VERSIONS["curve"],
                "interpolation": interpolation,
                "scale": scale,
                "normalized_curve_si": rows,
                "source_sha256": source_sha256,
                "normalized_curve_sha256": normalized_sha256,
                "source_byte_count": source_byte_count,
            },
            "mapping": {"schema_version": _VERSIONS["mapping"], "surface_category": category, "target_face_ids": target_ids},
            "budgets": dict(normalized_budgets),
        },
        "imported_pressure_history",
    )
    assert isinstance(normalized, Mapping)
    return normalized


def _normalize_curve_rows(
    rows: tuple[tuple[float, float], ...], *, time_factor: float, pressure_factor: float, scale: float
) -> tuple[tuple[float, float], ...]:
    if not rows:
        raise ValueError("pressure-history rows must not be empty")
    normalized: list[tuple[float, float]] = []
    previous_time: float | None = None
    for index, (time_value, pressure_value) in enumerate(rows):
        time_s = time_value * time_factor
        pressure_pa = pressure_value * pressure_factor * scale
        if not math.isfinite(time_s) or not math.isfinite(pressure_pa):
            raise ValueError(f"normalized curve row {index} must contain finite numbers")
        if previous_time is not None and time_s <= previous_time:
            raise ValueError("pressure-history time values must be strictly increasing")
        normalized.append((time_s, pressure_pa))
        previous_time = time_s
    return tuple(normalized)


def _decode_csv_rows(raw_bytes: bytes, maximum_rows: int) -> tuple[tuple[float, float], ...]:
    rows: list[tuple[float, float]] = []
    try:
        with io.TextIOWrapper(io.BytesIO(raw_bytes), encoding="utf-8", errors="strict", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            for index, row in enumerate(reader):
                if index >= maximum_rows:
                    raise ValueError("row count budget exceeded before row normalization")
                rows.append(_csv_row_pair(row, f"source.csv[{index}]"))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("source bytes must be strict UTF-8 CSV") from exc
    return tuple(rows)


def _row_pair(value: object, path: str) -> tuple[float, float]:
    if not _is_sequence(value) or len(value) != 2:
        raise ValueError(f"{path} must contain exactly time and pressure values")
    return _finite_number(value[0], f"{path}[0]"), _finite_number(value[1], f"{path}[1]")


def _validate_structured_row_shapes(rows: Sequence[object]) -> None:
    """Reject deep/container values before bounded source serialization."""

    for index, row in enumerate(rows):
        path = f"source.rows[{index}]"
        if not _is_sequence(row) or len(row) != 2:
            raise ValueError(f"{path} must contain exactly time and pressure values")
        for value_index, value in enumerate(row):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{path}[{value_index}] must be a finite number")
            if isinstance(value, int) and int.bit_length(value) > _MAX_STRUCTURED_INTEGER_BITS:
                raise ValueError(
                    f"{path}[{value_index}] integer decimal width exceeds bounded source limit"
                )


def _csv_row_pair(value: object, path: str) -> tuple[float, float]:
    if not _is_sequence(value) or len(value) != 2:
        raise ValueError(f"{path} must contain exactly time and pressure values")
    return _csv_number(value[0], f"{path}[0]"), _csv_number(value[1], f"{path}[1]")


def _csv_number(value: object, path: str) -> float:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{path} must be a finite number")
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"{path} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{path} must be a finite number")
    return number


def _curve_rows(value: object, path: str) -> tuple[tuple[float, float], ...]:
    if not _is_sequence(value):
        raise ValueError(f"{path} must be a sequence")
    return tuple(_row_pair(row, f"{path}[{index}]") for index, row in enumerate(value))


def _closed_mapping(value: object, expected: frozenset[str], path: str) -> Mapping[str, object]:
    mapping = _as_mapping(value, path)
    _require_exact_keys(mapping, expected, path)
    return mapping


def _require_exact_keys(mapping: Mapping[str, object], expected: frozenset[str] | set[str], path: str) -> None:
    unknown = sorted(set(mapping) - expected)
    missing = sorted(expected - set(mapping))
    if unknown:
        raise ValueError(f"{path} has unknown field: {unknown[0]!r}")
    if missing:
        raise ValueError(f"{path} is missing required field: {missing[0]!r}")


def _as_mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be a mapping")
    if any(not isinstance(key, str) or not key for key in value):
        raise ValueError(f"{path} keys must be non-empty strings")
    return value


def _nested_mapping(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    return _as_mapping(value.get(key), key)


def _require_literal(mapping: Mapping[str, object], key: str, expected: str, path: str) -> None:
    if mapping.get(key) != expected:
        raise ValueError(f"{path}.{key} must be {expected!r}")


def _safe_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value.strip()


def _safe_identifier(value: object, path: str) -> str:
    token = _safe_string(value, path)
    if value != token or token in {".", ".."} or _SAFE_ID_TOKEN_RE.fullmatch(token) is None:
        raise ValueError(f"{path} must be a safe identifier token")
    return token


def _safe_surface_id(value: object, path: str) -> str:
    token = _safe_string(value, path)
    if value != token or token in {".", ".."} or _SAFE_SURFACE_ID_RE.fullmatch(token) is None:
        raise ValueError(f"{path} must be a safe surface identifier")
    return token


def _sha256_digest(value: object, path: str) -> str:
    digest = _safe_string(value, path)
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError(f"{path} must be a lowercase SHA-256 digest")
    return digest


def _finite_number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{path} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{path} must be a finite number")
    return number


def _positive_integer(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{path} must be a positive integer")
    return value


def _bounded_positive_integer(value: object, path: str, maximum: int) -> int:
    number = _positive_integer(value, path)
    if number > maximum:
        raise ValueError(f"{path} exceeds hard safety limit {maximum}")
    return number


def _mapping_integer(mapping: Mapping[str, object], key: str) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _mapping_number(mapping: Mapping[str, object], key: str) -> float:
    return _finite_number(mapping.get(key), key)


def _mapping_string(mapping: Mapping[str, object], key: str) -> str:
    return _safe_string(mapping.get(key), key)


def _string_sequence(value: object, path: str) -> tuple[str, ...]:
    if not _is_sequence(value):
        raise ValueError(f"{path} must be a sequence")
    return tuple(_safe_string(row, f"{path}[{index}]") for index, row in enumerate(value))


def _vector(value: object, size: int, path: str) -> tuple[float, ...]:
    if not _is_sequence(value) or len(value) != size:
        raise ValueError(f"{path} must contain exactly {size} finite numbers")
    return tuple(_finite_number(item, f"{path}[{index}]") for index, item in enumerate(value))


def _surface_rows(catalog: Mapping[str, object], category: str) -> tuple[Mapping[str, object], ...]:
    raw = catalog.get(category)
    if not _is_sequence(raw):
        raise ValueError(f"surface_catalog.{category} must be a sequence")
    return tuple(_as_mapping(row, f"surface_catalog.{category}") for row in raw)


def _catalog_sequence(catalog: Mapping[str, object], category: str) -> Sequence[object]:
    raw = catalog.get(category)
    if not _is_sequence(raw):
        raise ValueError(f"surface_catalog.{category} must be a sequence")
    return raw


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _bounded_json_bytes(value: object, maximum: int) -> bytes:
    """Serialize shallow structured rows without allocating beyond the input budget."""

    encoder = json.JSONEncoder(
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=True,
    )
    result = bytearray()
    for chunk in encoder.iterencode(value):
        encoded = chunk.encode("utf-8")
        if len(result) + len(encoded) > maximum:
            raise ValueError("input byte budget exceeded before row normalization")
        result.extend(encoded)
    return bytes(result)


def _sha256_canonical(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


__all__ = ["ImportedPressureHistoryProvider"]
