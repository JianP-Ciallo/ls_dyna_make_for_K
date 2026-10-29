"""Deterministic, review-required LBE surface-load provider.

The provider produces a neutral surface-load selection only.  It deliberately
does not synthesize a fluid domain and must never be interpreted as an
ALE/FSI-equivalent calculation.
"""

from __future__ import annotations

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
    classify_source_space,
    fingerprint_value,
    freeze_value,
    source_space_evidence,
    surface_geometry_from_artifact,
    validate_source_space,
)


_ROOT_KEYS = frozenset({"schema_version", "unit_system", "source", "selection", "load", "budgets"})
_SOURCE_KEYS = frozenset(
    {"schema_version", "source_id", "position_m", "direction_unit_vector", "maximum_range_m"}
)
_SELECTION_KEYS = frozenset(
    {"schema_version", "surface_categories", "occlusion_policy", "user_surface_ids"}
)
_LOAD_KEYS = frozenset({"schema_version", "peak_pressure_pa", "positive_phase_duration_s"})
_BUDGET_KEYS = frozenset({"schema_version", "max_surface_count", "max_total_area_m2"})
_VERSIONS = {
    "input": "lbe_segment@1",
    "source": "lbe_segment.source@1",
    "selection": "lbe_segment.selection@1",
    "load": "lbe_segment.load@1",
    "budgets": "lbe_segment.budgets@1",
}
_UNIT_SYSTEM = "SI_m_s_kg_N_Pa"
_SAFE_ID_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
_SAFE_SURFACE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]*")
_LBE_CATEGORIES = frozenset({"exterior_surfaces", "interior_cavity_surfaces"})
_CATEGORIES_BY_KIND = {
    "external": frozenset({"exterior_surfaces"}),
    "internal": frozenset({"interior_cavity_surfaces"}),
    "semi_enclosed": frozenset({"exterior_surfaces", "interior_cavity_surfaces"}),
}
_OCCLUSION_POLICIES = frozenset({"none"})
_AREA_TOLERANCE_M2 = 1.0e-12
_DIRECTION_TOLERANCE = 1.0e-12
_GEOMETRY_TOLERANCE = 1.0e-9


def _input_ui_schema() -> dict[str, object]:
    """Public recursive contract emitted beside the normalizer it describes."""
    number = {"type": "number"}
    string = {"type": "string"}
    array_number = {"type": "array", "items": number}
    return {
        "type": "object", "additionalProperties": False,
        "required": sorted(_ROOT_KEYS),
        "properties": {
            "schema_version": {"type": "string", "const": _VERSIONS["input"]},
            "unit_system": {"type": "string", "const": _UNIT_SYSTEM},
            "source": {"type": "object", "additionalProperties": False, "required": sorted(_SOURCE_KEYS), "properties": {"schema_version": {"type": "string", "const": _VERSIONS["source"]}, "source_id": string, "position_m": {**array_number, "minItems": 3, "maxItems": 3}, "direction_unit_vector": {**array_number, "minItems": 3, "maxItems": 3}, "maximum_range_m": number}},
            "selection": {"type": "object", "additionalProperties": False, "required": sorted(_SELECTION_KEYS), "properties": {"schema_version": {"type": "string", "const": _VERSIONS["selection"]}, "surface_categories": {"type": "array", "items": {"type": "string", "enum": sorted(_LBE_CATEGORIES)}}, "occlusion_policy": {"type": "string", "enum": sorted(_OCCLUSION_POLICIES)}, "user_surface_ids": {"type": "array", "items": string}}},
            "load": {"type": "object", "additionalProperties": False, "required": sorted(_LOAD_KEYS), "properties": {"schema_version": {"type": "string", "const": _VERSIONS["load"]}, "peak_pressure_pa": number, "positive_phase_duration_s": number}},
            "budgets": {"type": "object", "additionalProperties": False, "required": sorted(_BUDGET_KEYS), "properties": {"schema_version": {"type": "string", "const": _VERSIONS["budgets"]}, "max_surface_count": {"type": "integer"}, "max_total_area_m2": number}},
        },
    }


@dataclass(frozen=True, slots=True)
class _Candidate:
    face_id: str
    element_id: int
    category: str
    area_m2: float
    centroid_m: tuple[float, float, float]
    range_m: float


@dataclass(frozen=True, slots=True)
class _ValidatedState:
    normalized: FrozenMapping
    candidates: tuple[_Candidate, ...]
    selected: tuple[_Candidate, ...]
    inclusion_reason: str
    source_space_id: str


class LbeSegmentProvider:
    """Compile a deterministic surface-load candidate for review.

    The only current occlusion policy is ``none``.  It is intentionally
    explicit: surfaces are filtered geometrically, but no unvalidated ray
    tracing or hidden-face inference is claimed.
    """

    provider_id = "lbe_segment"

    def default_input(self) -> Mapping[str, object]:
        """Return the browser's conservative, normalizer-valid seed input."""

        return {
            "schema_version": _VERSIONS["input"], "unit_system": _UNIT_SYSTEM,
            "source": {"schema_version": _VERSIONS["source"], "source_id": "charge-1", "position_m": [-1.0, 3.0, 1.5], "direction_unit_vector": [1.0, 0.0, 0.0], "maximum_range_m": 20.0},
            "selection": {"schema_version": _VERSIONS["selection"], "surface_categories": ["exterior_surfaces"], "occlusion_policy": "none", "user_surface_ids": []},
            "load": {"schema_version": _VERSIONS["load"], "peak_pressure_pa": 250000.0, "positive_phase_duration_s": 0.02},
            "budgets": {"schema_version": _VERSIONS["budgets"], "max_surface_count": 10000, "max_total_area_m2": 100000.0},
        }

    def schema(self) -> Mapping[str, object]:
        schema = {
            "schema_version": _VERSIONS["input"],
            "unit_system": _UNIT_SYSTEM,
            "exact_root_keys": tuple(sorted(_ROOT_KEYS)),
            "nested_schema_versions": dict(sorted(_VERSIONS.items())),
            "occlusion_policies": tuple(sorted(_OCCLUSION_POLICIES)),
            "input_schema": _input_ui_schema(),
        }
        frozen = freeze_value(schema, "schema")
        assert isinstance(frozen, Mapping)
        return frozen


    def capabilities(self) -> Mapping[str, object]:
        capabilities = freeze_value(
            {
                "provider_id": self.provider_id,
                "scenario_kinds": ("external", "internal", "semi_enclosed"),
                "surface_categories_by_kind": {
                    kind: tuple(sorted(categories))
                    for kind, categories in sorted(_CATEGORIES_BY_KIND.items())
                },
                "occlusion_policies": tuple(sorted(_OCCLUSION_POLICIES)),
                "software_candidate_only": True,
                "solver_ready": False,
                "requires_project_review": True,
                "engineering_validated": False,
                "lbe_is_not_ale_fsi_equivalent": True,
                "launches_external_programs": False,
            },
            "capabilities",
        )
        assert isinstance(capabilities, Mapping)
        return capabilities

    def normalize(self, value: Mapping[str, object]) -> FrozenMapping:
        raw = _closed_mapping(value, _ROOT_KEYS, "lbe_segment")
        _require_literal(raw, "schema_version", _VERSIONS["input"], "lbe_segment")
        _require_literal(raw, "unit_system", _UNIT_SYSTEM, "lbe_segment")

        source = _closed_mapping(raw["source"], _SOURCE_KEYS, "lbe_segment.source")
        _require_literal(source, "schema_version", _VERSIONS["source"], "source")
        direction = _unit_vector(source.get("direction_unit_vector"), "source.direction_unit_vector")
        normalized_source = {
            "schema_version": _VERSIONS["source"],
            "source_id": _safe_identifier_token(source.get("source_id"), "source.source_id"),
            "position_m": _vector(source.get("position_m"), 3, "source.position_m"),
            "direction_unit_vector": direction,
            "maximum_range_m": _positive_number(
                source.get("maximum_range_m"), "source.maximum_range_m"
            ),
        }

        selection = _closed_mapping(raw["selection"], _SELECTION_KEYS, "lbe_segment.selection")
        _require_literal(selection, "schema_version", _VERSIONS["selection"], "selection")
        categories = _string_sequence(
            selection.get("surface_categories"), "selection.surface_categories"
        )
        if not categories:
            raise ValueError("selection.surface_categories must not be empty")
        if len(categories) != len(set(categories)):
            raise ValueError("selection.surface_categories must not contain duplicates")
        unknown_categories = sorted(set(categories) - _LBE_CATEGORIES)
        if unknown_categories:
            raise ValueError(f"unsupported LBE surface category: {unknown_categories[0]!r}")
        policy = _safe_string(selection.get("occlusion_policy"), "selection.occlusion_policy")
        if policy not in _OCCLUSION_POLICIES:
            raise ValueError(f"unsupported occlusion policy: {policy!r}")
        user_surface_ids = _string_sequence(
            selection.get("user_surface_ids"), "selection.user_surface_ids"
        )
        user_surface_ids = tuple(
            _safe_surface_identifier(item, f"selection.user_surface_ids[{index}]")
            for index, item in enumerate(user_surface_ids)
        )
        if len(user_surface_ids) != len(set(user_surface_ids)):
            raise ValueError("selection.user_surface_ids must not contain duplicates")
        normalized_selection = {
            "schema_version": _VERSIONS["selection"],
            "surface_categories": tuple(sorted(categories)),
            "occlusion_policy": policy,
            "user_surface_ids": tuple(sorted(user_surface_ids)),
        }

        load = _closed_mapping(raw["load"], _LOAD_KEYS, "lbe_segment.load")
        _require_literal(load, "schema_version", _VERSIONS["load"], "load")
        normalized_load = {
            "schema_version": _VERSIONS["load"],
            "peak_pressure_pa": _positive_number(load.get("peak_pressure_pa"), "load.peak_pressure_pa"),
            "positive_phase_duration_s": _positive_number(
                load.get("positive_phase_duration_s"), "load.positive_phase_duration_s"
            ),
        }

        budgets = _closed_mapping(raw["budgets"], _BUDGET_KEYS, "lbe_segment.budgets")
        _require_literal(budgets, "schema_version", _VERSIONS["budgets"], "budgets")
        normalized_budgets = {
            "schema_version": _VERSIONS["budgets"],
            "max_surface_count": _positive_integer(
                budgets.get("max_surface_count"), "budgets.max_surface_count"
            ),
            "max_total_area_m2": _positive_number(
                budgets.get("max_total_area_m2"), "budgets.max_total_area_m2"
            ),
        }

        normalized = freeze_value(
            {
                "schema_version": _VERSIONS["input"],
                "unit_system": _UNIT_SYSTEM,
                "source": normalized_source,
                "selection": normalized_selection,
                "load": normalized_load,
                "budgets": normalized_budgets,
            },
            "lbe_segment",
        )
        assert isinstance(normalized, Mapping)
        return normalized

    def validate(
        self, value: Mapping[str, object], context: ProviderContext
    ) -> tuple[Finding, ...]:
        try:
            self._validate_state(self.normalize(value), context)
        except (TypeError, ValueError) as exc:
            return (
                Finding(
                    finding_id=f"lbe_segment:{fingerprint_value(str(exc))[:16]}",
                    severity="error",
                    message=str(exc),
                ),
            )
        return ()

    def estimate(
        self, value: Mapping[str, object], context: ProviderContext
    ) -> ProviderEstimate:
        state = self._validate_state(self.normalize(value), context)
        return self._estimate_state(state)

    def compile(
        self, value: Mapping[str, object], context: ProviderContext
    ) -> ProviderFragment:
        state = self._validate_state(self.normalize(value), context)
        estimate = self._estimate_state(state)
        selected_faces = tuple(candidate.face_id for candidate in state.selected)
        selected_elements = tuple(candidate.element_id for candidate in state.selected)
        source = _nested_mapping(state.normalized, "source")
        total_area_m2 = math.fsum(candidate.area_m2 for candidate in state.selected)
        required_ids = frozenset(
            (
                *(f"surface:{face_id}" for face_id in selected_faces),
                *(f"building:element:{element_id}" for element_id in selected_elements),
                f"artifact:{context.artifact.fingerprint}",
                f"topology:{context.topology.fingerprint}",
            )
        )
        declared_base = frozenset(
            {
                f"lbe_segment:source:{_mapping_string(source, 'source_id')}",
                f"estimate:{estimate.fingerprint}",
            }
        )
        evidence = self._build_evidence(state, context, estimate, total_area_m2)
        declared_ids = declared_base | frozenset(row.evidence_id for row in evidence)
        evidence_source_ids = frozenset(
            source_id for row in evidence for source_id in row.source_ids
        )
        missing = (required_ids | evidence_source_ids) - (context.available_ids | declared_ids)
        if missing:
            raise ValueError(f"provider fragment has unclosed id: {sorted(missing)[0]!r}")

        selection = _nested_mapping(state.normalized, "selection")
        manifest = {
            "schema_version": "lbe_segment.fragment@1",
            "provider_id": self.provider_id,
            "scenario_kind": context.scenario_kind,
            "building_artifact_fingerprint": context.artifact.fingerprint,
            "topology_fingerprint": context.topology.fingerprint,
            "input_fingerprint": fingerprint_value(state.normalized),
            "surface_categories": _string_sequence(
                selection.get("surface_categories"), "selection.surface_categories"
            ),
            "selection": {
                "occlusion_policy": _mapping_string(selection, "occlusion_policy"),
                "candidate_face_ids": tuple(candidate.face_id for candidate in state.candidates),
                "included_faces": tuple(
                    {
                        "face_id": candidate.face_id,
                        "element_id": candidate.element_id,
                        "category": candidate.category,
                        "area_m2": candidate.area_m2,
                        "range_m": candidate.range_m,
                        "reason": state.inclusion_reason,
                    }
                    for candidate in state.selected
                ),
                "total_area_m2": total_area_m2,
            },
            "load": _nested_mapping(state.normalized, "load"),
            "allocation": {
                "estimate": estimate.to_manifest(),
                "actual_node_count": len(()),
                "actual_element_count": len(()),
                "actual_loaded_surface_count": len(state.selected),
                "actual_target_surface_count": len(selected_faces),
                "actual_total_area_m2": total_area_m2,
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
            "lbe_is_not_ale_fsi_equivalent": True,
            "external_program_started": False,
        }
        return ProviderFragment(
            provider_id=self.provider_id,
            normalized_input=state.normalized,
            axes_m=((), (), ()),
            node_ids=(),
            element_ids=(),
            fsi_face_ids=selected_faces,
            required_ids=required_ids,
            declared_ids=declared_ids,
            evidence=evidence,
            manifest=manifest,
        )

    def preview(self, value: Mapping[str, object], context: ProviderContext) -> FrozenMapping:
        state = self._validate_state(self.normalize(value), context)
        preview = freeze_value(
            {
                "provider_id": self.provider_id,
                "scenario_kind": context.scenario_kind,
                "candidate_face_ids": tuple(candidate.face_id for candidate in state.candidates),
                "selected_face_ids": tuple(candidate.face_id for candidate in state.selected),
                "software_candidate_only": True,
                "solver_ready": False,
                "requires_project_review": True,
                "lbe_is_not_ale_fsi_equivalent": True,
            },
            "lbe_segment.preview",
        )
        assert isinstance(preview, Mapping)
        return preview

    def _validate_state(self, normalized: FrozenMapping, context: ProviderContext) -> _ValidatedState:
        selection = _nested_mapping(normalized, "selection")
        categories = _string_sequence(selection.get("surface_categories"), "selection.surface_categories")
        invalid = sorted(set(categories) - _CATEGORIES_BY_KIND[context.scenario_kind])
        if invalid:
            raise ValueError(
                f"LBE surface category {invalid[0]!r} is invalid for {context.scenario_kind}"
            )
        source = _nested_mapping(normalized, "source")
        position = _vector(source.get("position_m"), 3, "source.position_m")
        source_space_id = validate_source_space(
            classify_source_space(position, context), context
        )
        direction = _unit_vector(source.get("direction_unit_vector"), "source.direction_unit_vector")
        maximum_range_m = _positive_number(source.get("maximum_range_m"), "source.maximum_range_m")
        candidates = self._select_candidates(
            context, categories, position, direction, maximum_range_m
        )
        if not candidates:
            raise ValueError("LBE selection has no candidate face after direction, range, area, and occlusion filtering")

        selected_ids = _string_sequence(selection.get("user_surface_ids"), "selection.user_surface_ids")
        candidate_by_id = {candidate.face_id: candidate for candidate in candidates}
        if selected_ids:
            missing = sorted(set(selected_ids) - set(candidate_by_id))
            if missing:
                raise ValueError(f"user surface id is not a computed candidate: {missing[0]!r}")
            selected = tuple(candidate_by_id[face_id] for face_id in selected_ids)
            inclusion_reason = "user_subset"
        else:
            selected = candidates
            inclusion_reason = "automatic_candidate"
        budgets = _nested_mapping(normalized, "budgets")
        if len(selected) > _mapping_integer(budgets, "max_surface_count"):
            raise ValueError(
                "surface count budget exceeded: "
                f"estimated {len(selected)}, limit {_mapping_integer(budgets, 'max_surface_count')}"
            )
        total_area_m2 = math.fsum(candidate.area_m2 for candidate in selected)
        if total_area_m2 > _mapping_number(budgets, "max_total_area_m2"):
            raise ValueError(
                "surface area budget exceeded: "
                f"estimated {total_area_m2}, limit {_mapping_number(budgets, 'max_total_area_m2')}"
            )
        return _ValidatedState(
            normalized, candidates, selected, inclusion_reason, source_space_id
        )

    def _estimate_state(self, state: _ValidatedState) -> ProviderEstimate:
        budgets = _nested_mapping(state.normalized, "budgets")
        return ProviderEstimate(
            provider_id=self.provider_id,
            axis_point_counts=(0, 0, 0),
            node_count=0,
            # Surface faces are target dependencies, not new fragment elements.
            # This keeps estimates compatible with generic assemblers that use
            # element_count to reserve only element_ids emitted by a fragment.
            element_count=0,
            budget_limits=MappingProxyType(
                {
                    "max_surface_count": _mapping_integer(budgets, "max_surface_count"),
                    "max_total_area_m2": _mapping_number(budgets, "max_total_area_m2"),
                }
            ),
            budget_checked_before_allocation=True,
        )

    def _select_candidates(
        self,
        context: ProviderContext,
        categories: tuple[str, ...],
        position: tuple[float, float, float],
        direction: tuple[float, float, float],
        maximum_range_m: float,
    ) -> tuple[_Candidate, ...]:
        candidates: list[_Candidate] = []
        seen_context_face_ids: set[str] = set()
        seen_artifact_face_ids: set[str] = set()
        for category in categories:
            context_rows = _surface_rows(context.surface_catalog, category)
            for row in context_rows:
                face_id = _mapping_string(row, "face_id")
                if face_id in seen_context_face_ids:
                    raise ValueError(f"LBE surface catalog contains duplicate face id: {face_id!r}")
                seen_context_face_ids.add(face_id)
            artifact_category_rows = _surface_rows(context.artifact.surface_catalog, category)
            for row in artifact_category_rows:
                face_id = _mapping_string(row, "face_id")
                if face_id in seen_artifact_face_ids:
                    raise ValueError(f"artifact surface catalog contains duplicate face id: {face_id!r}")
                seen_artifact_face_ids.add(face_id)
            artifact_rows = {
                _mapping_string(row, "face_id"): row
                for row in artifact_category_rows
            }
            for row in context_rows:
                face_id = _mapping_string(row, "face_id")
                artifact_row = artifact_rows.get(face_id)
                if artifact_row is None or fingerprint_value(row) != fingerprint_value(artifact_row):
                    raise ValueError(f"LBE face {face_id!r} does not match artifact surface catalog")
                element_id = _mapping_integer(row, "element_id")
                area_m2, centroid_m, normal = surface_geometry_from_artifact(
                    context.artifact, row, f"LBE face {face_id!r}"
                )
                if area_m2 <= _AREA_TOLERANCE_M2:
                    raise ValueError(f"LBE face {face_id!r} must have positive area")
                radial = tuple(centroid_m[axis] - position[axis] for axis in range(3))
                range_m = math.sqrt(sum(value * value for value in radial))
                if range_m <= _DIRECTION_TOLERANCE or range_m > maximum_range_m:
                    continue
                if sum(direction[axis] * radial[axis] for axis in range(3)) / range_m <= _DIRECTION_TOLERANCE:
                    continue
                candidates.append(
                    _Candidate(face_id, element_id, category, area_m2, centroid_m, range_m)
                )
        return tuple(sorted(candidates, key=lambda candidate: candidate.face_id))

    def _build_evidence(
        self,
        state: _ValidatedState,
        context: ProviderContext,
        estimate: ProviderEstimate,
        total_area_m2: float,
    ) -> tuple[ProviderEvidence, ...]:
        source = _nested_mapping(state.normalized, "source")
        source_declared_id = f"lbe_segment:source:{_mapping_string(source, 'source_id')}"
        source_evidence = source_space_evidence(
            provider_id=self.provider_id,
            source_declared_id=source_declared_id,
            source_space_id=state.source_space_id,
            context=context,
            determination="verified_position_containment",
        )
        rows = (
            (
                "classified_surface_selection",
                (
                    f"artifact:{context.artifact.fingerprint}",
                    f"topology:{context.topology.fingerprint}",
                    *(f"surface:{candidate.face_id}" for candidate in state.selected),
                ),
                {
                    "scenario_kind": context.scenario_kind,
                    "candidate_face_ids": tuple(candidate.face_id for candidate in state.candidates),
                    "selected_face_ids": tuple(candidate.face_id for candidate in state.selected),
                    "inclusion_reason": state.inclusion_reason,
                },
            ),
            (
                "preallocation_budget",
                (f"estimate:{estimate.fingerprint}",),
                {
                    "loaded_surface_count": len(state.selected),
                    "loaded_total_area_m2": total_area_m2,
                    "budget_checked_before_allocation": True,
                },
            ),
            (
                "lbe_engineering_boundary",
                (),
                {
                    "solver_ready": False,
                    "requires_project_review": True,
                    "lbe_is_not_ale_fsi_equivalent": True,
                    "occlusion_policy": _mapping_string(
                        _nested_mapping(state.normalized, "selection"), "occlusion_policy"
                    ),
                },
            ),
        )
        evidence: list[ProviderEvidence] = [source_evidence]
        for index, (kind, source_ids, claims) in enumerate(rows, start=2):
            digest = fingerprint_value({"kind": kind, "source_ids": source_ids, "claims": claims})
            evidence.append(
                ProviderEvidence(
                    evidence_id=f"lbe_segment:evidence:{index}:{digest[:16]}",
                    evidence_kind=kind,
                    source_ids=source_ids,
                    claims=claims,
                )
            )
        return tuple(evidence)


def _closed_mapping(value: object, expected_keys: frozenset[str], path: str) -> Mapping[str, object]:
    mapping = _as_mapping(value, path)
    unknown = sorted(set(mapping) - expected_keys)
    missing = sorted(expected_keys - set(mapping))
    if unknown:
        raise ValueError(f"{path} has unknown field: {unknown[0]!r}")
    if missing:
        raise ValueError(f"{path} is missing required field: {missing[0]!r}")
    return mapping


def _as_mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be a mapping")
    if any(not isinstance(key, str) or not key for key in value):
        raise ValueError(f"{path} keys must be non-empty strings")
    return value


def _nested_mapping(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    return _as_mapping(value.get(key), key)


def _require_literal(value: Mapping[str, object], key: str, expected: str, path: str) -> None:
    if value.get(key) != expected:
        raise ValueError(f"{path}.{key} must be {expected!r}")


def _safe_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value.strip()


def _safe_identifier_token(value: object, path: str) -> str:
    token = _safe_string(value, path)
    if value != token or token in {".", ".."} or _SAFE_ID_TOKEN_RE.fullmatch(token) is None:
        raise ValueError(f"{path} must be a safe identifier token")
    return token


def _safe_surface_identifier(value: object, path: str) -> str:
    token = _safe_string(value, path)
    if value != token or token in {".", ".."} or _SAFE_SURFACE_ID_RE.fullmatch(token) is None:
        raise ValueError(f"{path} must be a safe surface identifier")
    return token


def _finite_number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{path} must be a finite number")
    return number


def _positive_number(value: object, path: str) -> float:
    number = _finite_number(value, path)
    if number <= 0.0:
        raise ValueError(f"{path} must be positive")
    return number


def _positive_integer(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{path} must be a positive integer")
    return value


def _mapping_integer(value: Mapping[str, object], key: str) -> int:
    raw = value.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"{key} must be an integer")
    return raw


def _mapping_number(value: Mapping[str, object], key: str) -> float:
    return _finite_number(value.get(key), key)


def _mapping_string(value: Mapping[str, object], key: str) -> str:
    return _safe_string(value.get(key), key)


def _vector(value: object, size: int, path: str) -> tuple[float, ...]:
    if not _is_sequence(value) or len(value) != size:
        raise ValueError(f"{path} must contain exactly {size} finite numbers")
    return tuple(_finite_number(item, f"{path}[{index}]") for index, item in enumerate(value))


def _unit_vector(value: object, path: str) -> tuple[float, float, float]:
    vector = _vector(value, 3, path)
    magnitude = math.sqrt(sum(item * item for item in vector))
    if not math.isfinite(magnitude) or magnitude <= _DIRECTION_TOLERANCE:
        raise ValueError(f"{path} must have positive magnitude")
    if not math.isclose(magnitude, 1.0, rel_tol=0.0, abs_tol=1.0e-9):
        raise ValueError(f"{path} must be a unit vector")
    return vector  # type: ignore[return-value]


def _string_sequence(value: object, path: str) -> tuple[str, ...]:
    if not _is_sequence(value):
        raise ValueError(f"{path} must be a sequence")
    return tuple(_safe_string(item, f"{path}[{index}]") for index, item in enumerate(value))


def _surface_rows(catalog: Mapping[str, object], category: str) -> tuple[Mapping[str, object], ...]:
    raw = catalog.get(category)
    if not _is_sequence(raw):
        raise ValueError(f"surface_catalog.{category} must be a sequence")
    return tuple(_as_mapping(row, f"surface_catalog.{category}") for row in raw)


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


__all__ = ["LbeSegmentProvider"]
