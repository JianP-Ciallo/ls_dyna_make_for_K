"""Software-candidate compiler for an explicit ALE/FSI load fragment.

This module prepares deterministic neutral data only.  It neither launches an
external solver nor claims engineering equivalence to an ALE analysis.
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
    ProviderTopology,
    TopologyOpening,
    fingerprint_value,
    freeze_value,
    source_space_evidence,
)


_ROOT_KEYS = frozenset(
    {"schema_version", "unit_system", "charge", "domain", "fsi", "resources", "budgets"}
)
_CHARGE_KEYS = frozenset(
    {
        "schema_version",
        "source_id",
        "position_m",
        "tnt_equivalent_kg",
        "detonation_time_s",
    }
)
_DOMAIN_KEYS = frozenset(
    {
        "schema_version",
        "bounds_m",
        "target_cell_size_m",
        "minimum_margin_m",
        "external_buffer_m",
    }
)
_FSI_KEYS = frozenset({"schema_version", "surface_categories", "coupling_mode"})
_RESOURCE_KEYS = frozenset(
    {
        "schema_version",
        "air_material",
        "explosive_material",
        "equation_of_state",
        "ale_keyword",
    }
)
_RESOURCE_REF_KEYS = frozenset({"resource_id", "version"})
_BUDGET_KEYS = frozenset(
    {"schema_version", "max_axis_points", "max_node_count", "max_element_count"}
)
_VERSIONS = {
    "input": "explicit_ale_fsi@1",
    "charge": "explicit_ale_fsi.charge@1",
    "domain": "explicit_ale_fsi.domain@1",
    "fsi": "explicit_ale_fsi.fsi@1",
    "resources": "explicit_ale_fsi.resources@1",
    "budgets": "explicit_ale_fsi.budgets@1",
}
_UNIT_SYSTEM = "SI_m_s_kg_N_Pa"
_COUPLING_MODE = "constrained_lagrange_in_solid"
_SAFE_ID_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
_SURFACE_GEOMETRY_TOLERANCE = 1.0e-9
_SURFACE_AREA_TOLERANCE_M2 = 1.0e-12
_CLASSIFIED_FSI_CATEGORIES = frozenset(
    {
        "exterior_surfaces",
        "interior_cavity_surfaces",
        "ground_contact_surfaces",
        "unclassified_boundary_surfaces",
    }
)
_CATEGORIES_BY_KIND = {
    "external": frozenset({"exterior_surfaces"}),
    "internal": frozenset({"interior_cavity_surfaces"}),
    "semi_enclosed": frozenset({"interior_cavity_surfaces", "exterior_surfaces"}),
}


def _input_ui_schema() -> dict[str, object]:
    number = {"type": "number"}
    string = {"type": "string"}
    resource = {"type": "object", "additionalProperties": False, "required": sorted(_RESOURCE_REF_KEYS), "properties": {"resource_id": string, "version": string}}
    return {
        "type": "object", "additionalProperties": False, "required": sorted(_ROOT_KEYS), "properties": {
            "schema_version": {"type": "string", "const": _VERSIONS["input"]}, "unit_system": {"type": "string", "const": _UNIT_SYSTEM},
            "charge": {"type": "object", "additionalProperties": False, "required": sorted(_CHARGE_KEYS), "properties": {"schema_version": {"type": "string", "const": _VERSIONS["charge"]}, "source_id": string, "position_m": {"type": "array", "items": number, "minItems": 3, "maxItems": 3}, "tnt_equivalent_kg": number, "detonation_time_s": number}},
            "domain": {"type": "object", "additionalProperties": False, "required": sorted(_DOMAIN_KEYS), "properties": {"schema_version": {"type": "string", "const": _VERSIONS["domain"]}, "bounds_m": {"type": "array", "items": number, "minItems": 6, "maxItems": 6}, "target_cell_size_m": number, "minimum_margin_m": number, "external_buffer_m": number}},
            "fsi": {"type": "object", "additionalProperties": False, "required": sorted(_FSI_KEYS), "properties": {"schema_version": {"type": "string", "const": _VERSIONS["fsi"]}, "surface_categories": {"type": "array", "items": {"type": "string", "enum": sorted(_CLASSIFIED_FSI_CATEGORIES)}}, "coupling_mode": {"type": "string", "const": _COUPLING_MODE}}},
            "resources": {"type": "object", "additionalProperties": False, "required": sorted(_RESOURCE_KEYS), "properties": {key: ({"type": "string", "const": _VERSIONS["resources"]} if key == "schema_version" else resource) for key in _RESOURCE_KEYS}},
            "budgets": {"type": "object", "additionalProperties": False, "required": sorted(_BUDGET_KEYS), "properties": {key: ({"type": "string", "const": _VERSIONS["budgets"]} if key == "schema_version" else {"type": "integer"}) for key in _BUDGET_KEYS}},
        },
    }


@dataclass(frozen=True, slots=True)
class _ValidatedState:
    normalized: FrozenMapping
    bounds_m: tuple[float, float, float, float, float, float]
    position_m: tuple[float, float, float]
    cell_size_m: float
    categories: tuple[str, ...]
    fsi_face_ids: tuple[str, ...]
    fsi_element_ids: tuple[int, ...]
    resource_ids: tuple[str, ...]
    containing_space_id: str | None
    external_opening_ids: tuple[str, ...]


class ExplicitAleFsiProvider:
    """Compile a review-required neutral ALE/FSI software candidate."""

    provider_id = "explicit_ale_fsi"

    def default_input(self) -> Mapping[str, object]:
        return {
            "schema_version": _VERSIONS["input"], "unit_system": _UNIT_SYSTEM,
            "charge": {"schema_version": _VERSIONS["charge"], "source_id": "charge-1", "position_m": [-1.0, 3.0, 1.5], "tnt_equivalent_kg": 2.0, "detonation_time_s": 0.0},
            "domain": {"schema_version": _VERSIONS["domain"], "bounds_m": [-3.0, -2.0, -1.0, 9.0, 8.0, 5.0], "target_cell_size_m": 2.0, "minimum_margin_m": 1.0, "external_buffer_m": 0.5},
            "fsi": {"schema_version": _VERSIONS["fsi"], "surface_categories": ["exterior_surfaces"], "coupling_mode": "constrained_lagrange_in_solid"},
            "resources": {"schema_version": _VERSIONS["resources"], "air_material": {"resource_id": "neutral-air", "version": "1.0.0"}, "explosive_material": {"resource_id": "neutral-tnt", "version": "1.0.0"}, "equation_of_state": {"resource_id": "neutral-eos", "version": "1.0.0"}, "ale_keyword": {"resource_id": "neutral-ale-keywords", "version": "1.0.0"}},
            "budgets": {"schema_version": _VERSIONS["budgets"], "max_axis_points": 20, "max_node_count": 1000, "max_element_count": 1000},
        }

    def schema(self) -> Mapping[str, object]:
        schema = {
            "schema_version": _VERSIONS["input"],
            "unit_system": _UNIT_SYSTEM,
            "exact_root_keys": tuple(sorted(_ROOT_KEYS)),
            "nested_schema_versions": dict(sorted(_VERSIONS.items())),
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
                "software_candidate_only": True,
                "solver_ready": False,
                "requires_project_review": True,
                "engineering_validated": False,
                "launches_external_programs": False,
            },
            "capabilities",
        )
        assert isinstance(capabilities, Mapping)
        return capabilities

    def normalize(self, value: Mapping[str, object]) -> FrozenMapping:
        raw = _closed_mapping(value, _ROOT_KEYS, "explicit_ale_fsi")
        _require_literal(raw, "schema_version", _VERSIONS["input"], "explicit_ale_fsi")
        _require_literal(raw, "unit_system", _UNIT_SYSTEM, "explicit_ale_fsi")

        charge = _closed_mapping(raw["charge"], _CHARGE_KEYS, "explicit_ale_fsi.charge")
        _require_literal(charge, "schema_version", _VERSIONS["charge"], "charge")
        normalized_charge = {
            "schema_version": _VERSIONS["charge"],
            "source_id": _safe_identifier_token(
                charge.get("source_id"), "charge.source_id"
            ),
            "position_m": _vector(charge.get("position_m"), 3, "charge.position_m"),
            "tnt_equivalent_kg": _positive_number(
                charge.get("tnt_equivalent_kg"), "charge.tnt_equivalent_kg"
            ),
            "detonation_time_s": _nonnegative_number(
                charge.get("detonation_time_s"), "charge.detonation_time_s"
            ),
        }

        domain = _closed_mapping(raw["domain"], _DOMAIN_KEYS, "explicit_ale_fsi.domain")
        _require_literal(domain, "schema_version", _VERSIONS["domain"], "domain")
        normalized_domain = {
            "schema_version": _VERSIONS["domain"],
            "bounds_m": _bounds(domain.get("bounds_m"), "domain.bounds_m"),
            "target_cell_size_m": _positive_number(
                domain.get("target_cell_size_m"), "domain.target_cell_size_m"
            ),
            "minimum_margin_m": _nonnegative_number(
                domain.get("minimum_margin_m"), "domain.minimum_margin_m"
            ),
            "external_buffer_m": _nonnegative_number(
                domain.get("external_buffer_m"), "domain.external_buffer_m"
            ),
        }

        fsi = _closed_mapping(raw["fsi"], _FSI_KEYS, "explicit_ale_fsi.fsi")
        _require_literal(fsi, "schema_version", _VERSIONS["fsi"], "fsi")
        categories = _string_sequence(fsi.get("surface_categories"), "fsi.surface_categories")
        if not categories:
            raise ValueError("fsi.surface_categories must not be empty")
        if len(categories) != len(set(categories)):
            raise ValueError("fsi.surface_categories must not contain duplicates")
        unknown_categories = sorted(set(categories) - _CLASSIFIED_FSI_CATEGORIES)
        if unknown_categories:
            raise ValueError(f"unsupported FSI surface category: {unknown_categories[0]!r}")
        _require_literal(fsi, "coupling_mode", _COUPLING_MODE, "fsi")
        normalized_fsi = {
            "schema_version": _VERSIONS["fsi"],
            "surface_categories": tuple(sorted(categories)),
            "coupling_mode": _COUPLING_MODE,
        }

        resources = _closed_mapping(
            raw["resources"], _RESOURCE_KEYS, "explicit_ale_fsi.resources"
        )
        _require_literal(resources, "schema_version", _VERSIONS["resources"], "resources")
        normalized_resources: dict[str, object] = {"schema_version": _VERSIONS["resources"]}
        for key in (
            "air_material",
            "explosive_material",
            "equation_of_state",
            "ale_keyword",
        ):
            reference = _closed_mapping(resources[key], _RESOURCE_REF_KEYS, f"resources.{key}")
            normalized_resources[key] = {
                "resource_id": _safe_identifier_token(
                    reference.get("resource_id"), f"resources.{key}.resource_id"
                ),
                "version": _safe_identifier_token(
                    reference.get("version"), f"resources.{key}.version"
                ),
            }

        budgets = _closed_mapping(raw["budgets"], _BUDGET_KEYS, "explicit_ale_fsi.budgets")
        _require_literal(budgets, "schema_version", _VERSIONS["budgets"], "budgets")
        normalized_budgets = {
            "schema_version": _VERSIONS["budgets"],
            "max_axis_points": _positive_integer(
                budgets.get("max_axis_points"), "budgets.max_axis_points"
            ),
            "max_node_count": _positive_integer(
                budgets.get("max_node_count"), "budgets.max_node_count"
            ),
            "max_element_count": _positive_integer(
                budgets.get("max_element_count"), "budgets.max_element_count"
            ),
        }
        normalized = freeze_value(
            {
                "schema_version": _VERSIONS["input"],
                "unit_system": _UNIT_SYSTEM,
                "charge": normalized_charge,
                "domain": normalized_domain,
                "fsi": normalized_fsi,
                "resources": normalized_resources,
                "budgets": normalized_budgets,
            },
            "explicit_ale_fsi",
        )
        assert isinstance(normalized, Mapping)
        return normalized

    def validate(
        self, value: Mapping[str, object], context: ProviderContext
    ) -> tuple[Finding, ...]:
        try:
            state = self._validate_state(self.normalize(value), context)
            self._estimate_state(state)
        except (TypeError, ValueError) as exc:
            return (
                Finding(
                    finding_id=f"explicit_ale_fsi:{fingerprint_value(str(exc))[:16]}",
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

    def _estimate_state(self, state: _ValidatedState) -> ProviderEstimate:
        budgets = _nested_mapping(state.normalized, "budgets")
        extents = tuple(state.bounds_m[axis + 3] - state.bounds_m[axis] for axis in range(3))
        max_axis_points = _mapping_integer(budgets, "max_axis_points")
        axis_ratios = tuple(extent / state.cell_size_m for extent in extents)
        if any(not math.isfinite(ratio) for ratio in axis_ratios):
            raise ValueError(
                "axis point budget exceeded: estimated axis count is non-finite"
            )
        axis_counts = tuple(math.ceil(ratio) + 1 for ratio in axis_ratios)
        if any(count > max_axis_points for count in axis_counts):
            raise ValueError(
                f"axis point budget exceeded: estimated {axis_counts}, limit {max_axis_points}"
            )
        node_count = math.prod(axis_counts)
        element_count = math.prod(count - 1 for count in axis_counts)
        max_nodes = _mapping_integer(budgets, "max_node_count")
        max_elements = _mapping_integer(budgets, "max_element_count")
        if node_count > max_nodes:
            raise ValueError(f"node budget exceeded: estimated {node_count}, limit {max_nodes}")
        if element_count > max_elements:
            raise ValueError(
                f"element budget exceeded: estimated {element_count}, limit {max_elements}"
            )
        return ProviderEstimate(
            provider_id=self.provider_id,
            axis_point_counts=axis_counts,  # type: ignore[arg-type]
            node_count=node_count,
            element_count=element_count,
            budget_limits=MappingProxyType(
                {
                    "max_axis_points": max_axis_points,
                    "max_node_count": max_nodes,
                    "max_element_count": max_elements,
                }
            ),
            budget_checked_before_allocation=True,
        )

    def compile(
        self, value: Mapping[str, object], context: ProviderContext
    ) -> ProviderFragment:
        normalized = self.normalize(value)
        state = self._validate_state(normalized, context)
        estimate = self._estimate_state(state)
        axes, node_ids, element_ids = self._allocate_mesh(state, estimate)

        required_ids = frozenset(
            (
                *(f"surface:{face_id}" for face_id in state.fsi_face_ids),
                *(f"building:element:{element_id}" for element_id in state.fsi_element_ids),
                f"artifact:{context.artifact.fingerprint}",
                f"topology:{context.topology.fingerprint}",
                *(f"resource:{identity}" for identity in state.resource_ids),
            )
        )
        resource_ids = state.resource_ids
        charge = _nested_mapping(normalized, "charge")
        base_declared_ids = frozenset(
            (
                *node_ids,
                *element_ids,
                f"charge:{_mapping_string(charge, 'source_id')}",
                f"estimate:{estimate.fingerprint}",
            )
        )
        actual = {
            "axis_point_counts": tuple(len(axis) for axis in axes),
            "node_count": len(node_ids),
            "element_count": len(element_ids),
        }
        expected = {
            "axis_point_counts": estimate.axis_point_counts,
            "node_count": estimate.node_count,
            "element_count": estimate.element_count,
        }
        evidence = self._build_evidence(state, context, estimate, actual, resource_ids)
        declared_ids = base_declared_ids | frozenset(row.evidence_id for row in evidence)
        evidence_source_ids = frozenset(
            source_id for row in evidence for source_id in row.source_ids
        )
        id_universe = context.available_ids | declared_ids
        closure_missing = (required_ids | evidence_source_ids) - id_universe
        if closure_missing:
            raise ValueError(f"provider fragment has unclosed id: {sorted(closure_missing)[0]!r}")
        manifest = {
            "schema_version": "explicit_ale_fsi.fragment@1",
            "provider_id": self.provider_id,
            "scenario_kind": context.scenario_kind,
            "building_artifact_fingerprint": context.artifact.fingerprint,
            "topology_fingerprint": context.topology.fingerprint,
            "input_fingerprint": fingerprint_value(normalized),
            "allocation": {
                "estimate": expected,
                "actual": actual,
                "estimate_matches_actual": expected == actual,
                "budget_checked_before_allocation": estimate.budget_checked_before_allocation,
            },
            "fsi": {
                "surface_categories": state.categories,
                "face_ids": state.fsi_face_ids,
                "structural_element_ids": tuple(
                    f"building:element:{element_id}" for element_id in state.fsi_element_ids
                ),
                "catalog_only": True,
            },
            "resources": resource_ids,
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
            "external_program_started": False,
        }
        return ProviderFragment(
            provider_id=self.provider_id,
            normalized_input=normalized,
            axes_m=axes,
            node_ids=node_ids,
            element_ids=element_ids,
            fsi_face_ids=state.fsi_face_ids,
            required_ids=required_ids,
            declared_ids=declared_ids,
            evidence=evidence,
            manifest=manifest,
        )

    def preview(
        self, value: Mapping[str, object], context: ProviderContext
    ) -> FrozenMapping:
        state = self._validate_state(self.normalize(value), context)
        estimate = self.estimate(state.normalized, context)
        preview = freeze_value(
            {
                "schema_version": "explicit_ale_fsi.preview@1",
                "provider_id": self.provider_id,
                "scenario_kind": context.scenario_kind,
                "domain_bounds_m": state.bounds_m,
                "detonation_position_m": state.position_m,
                "fsi_face_ids": state.fsi_face_ids,
                "estimate": estimate.to_manifest(),
                "software_candidate_only": True,
                "solver_ready": False,
                "requires_project_review": True,
                "engineering_validated": False,
            },
            "preview",
        )
        assert isinstance(preview, Mapping)
        return preview

    def _validate_state(
        self, normalized: FrozenMapping, context: ProviderContext
    ) -> _ValidatedState:
        if not isinstance(context, ProviderContext):
            raise TypeError("context must be an immutable ProviderContext")
        domain = _nested_mapping(normalized, "domain")
        charge = _nested_mapping(normalized, "charge")
        fsi = _nested_mapping(normalized, "fsi")
        bounds = _bounds(domain.get("bounds_m"), "domain.bounds_m")
        position = _vector(charge.get("position_m"), 3, "charge.position_m")
        margin = _mapping_number(domain, "minimum_margin_m")
        if not _point_in_box(position, bounds, strict=False):
            raise ValueError("charge.position_m is outside fluid domain")
        if any(
            position[axis] - bounds[axis] < margin
            or bounds[axis + 3] - position[axis] < margin
            for axis in range(3)
        ):
            raise ValueError("fluid domain does not provide the declared minimum margin")
        if _point_in_structural_volume(position, context):
            raise ValueError("charge has positive-volume structural overlap")

        containing_space = _containing_space(position, context.topology)
        external_openings: tuple[str, ...] = ()
        if context.scenario_kind == "external":
            if _point_in_box(position, context.topology.envelope_bounds_m, strict=False):
                raise ValueError("external detonation point must be outside the building envelope")
        elif context.scenario_kind == "internal":
            if containing_space is None:
                raise ValueError("internal detonation point must be strictly inside a real space")
        else:
            if containing_space is None:
                raise ValueError("semi_enclosed detonation point must be strictly inside a real space")
            passage_paths = _external_passage_paths(containing_space, context.topology)
            if not passage_paths:
                raise ValueError("semi_enclosed scenario lacks a proven open passage to exterior")
            openings_by_id = {row.opening_id: row for row in context.topology.openings}
            envelope_paths = tuple(
                passage
                for passage in passage_paths
                if _terminal_opening_directions(
                    openings_by_id[passage[-1]], context.topology
                )
            )
            if not envelope_paths:
                raise ValueError(
                    "semi_enclosed terminal exterior opening must touch building envelope"
                )
            contained_paths = tuple(
                passage
                for passage in envelope_paths
                if all(
                    _box_contains_box(bounds, openings_by_id[opening_id].bounds_m)
                    for opening_id in passage
                )
            )
            if not contained_paths:
                raise ValueError(
                    "semi_enclosed open passage is not contained by fluid domain"
                )
            external_buffer = _mapping_number(domain, "external_buffer_m")
            buffered_paths = tuple(
                passage
                for passage in contained_paths
                if _domain_has_external_buffer(
                    bounds, context.topology, passage, external_buffer
                )
            )
            if external_buffer <= 0.0 or not buffered_paths:
                raise ValueError("semi_enclosed fluid domain lacks the declared external buffer")
            external_openings = buffered_paths[0]

        categories = tuple(_string_sequence(fsi.get("surface_categories"), "fsi.surface_categories"))
        allowed = _CATEGORIES_BY_KIND[context.scenario_kind]
        wrong = sorted(set(categories) - allowed)
        if wrong:
            raise ValueError(
                f"FSI surface category {wrong[0]!r} is invalid for {context.scenario_kind}"
            )
        if context.scenario_kind == "semi_enclosed" and "interior_cavity_surfaces" not in categories:
            raise ValueError("semi_enclosed FSI requires interior_cavity_surfaces")
        face_rows: list[Mapping[str, object]] = []
        artifact_node_ids = {node.node_id: node for node in context.artifact.mesh.nodes}
        for category in categories:
            raw_rows = context.surface_catalog.get(category)
            if not _is_sequence(raw_rows) or not raw_rows:
                raise ValueError(f"surface catalog category {category!r} is empty or invalid")
            artifact_rows_raw = context.artifact.surface_catalog.get(category)
            if not _is_sequence(artifact_rows_raw):
                raise ValueError(f"artifact surface catalog category {category!r} is invalid")
            artifact_rows = {
                _mapping_string(
                    _as_mapping(candidate, f"artifact.surface_catalog.{category}"),
                    "face_id",
                ): _as_mapping(candidate, f"artifact.surface_catalog.{category}")
                for candidate in artifact_rows_raw
            }
            for index, raw in enumerate(raw_rows):
                row = _as_mapping(raw, f"surface_catalog.{category}[{index}]")
                if not {"face_id", "element_id"} <= set(row):
                    raise ValueError(f"surface_catalog.{category}[{index}] is not a structural face")
                face_id = _mapping_string(row, "face_id")
                artifact_row = artifact_rows.get(face_id)
                if artifact_row is None or fingerprint_value(row) != fingerprint_value(artifact_row):
                    raise ValueError(
                        f"FSI face {face_id!r} does not match artifact surface catalog"
                    )
                raw_node_ids = row.get("node_ids")
                if not _is_sequence(raw_node_ids) or len(raw_node_ids) not in {3, 4}:
                    raise ValueError(
                        f"FSI face {face_id!r} must contain three or four structural node ids"
                    )
                face_coordinates: list[tuple[float, float, float]] = []
                for raw_node_id in raw_node_ids:
                    if isinstance(raw_node_id, bool) or not isinstance(raw_node_id, int):
                        raise ValueError(f"FSI face {face_id!r} has an invalid node id")
                    node = artifact_node_ids.get(raw_node_id)
                    if node is None:
                        raise ValueError(f"FSI face {face_id!r} references an unknown node")
                    face_coordinates.append(node.coordinates)
                    if not _point_in_box(node.coordinates, bounds, strict=False):
                        raise ValueError(f"FSI face {face_id!r} is outside fluid domain")
                area_m2, centroid_m, normal = _surface_geometry(tuple(face_coordinates))
                if area_m2 <= _SURFACE_AREA_TOLERANCE_M2:
                    raise ValueError(f"FSI face {face_id!r} must have positive area")
                catalog_centroid = _vector(
                    row.get("centroid_m"), 3, f"FSI face {face_id!r} centroid_m"
                )
                catalog_normal = _vector(
                    row.get("normal"), 3, f"FSI face {face_id!r} normal"
                )
                if math.sqrt(sum(value * value for value in catalog_normal)) <= _SURFACE_GEOMETRY_TOLERANCE:
                    raise ValueError(f"FSI face {face_id!r} catalog normal must be non-zero")
                if any(
                    abs(catalog_centroid[axis] - centroid_m[axis])
                    > _SURFACE_GEOMETRY_TOLERANCE
                    for axis in range(3)
                ):
                    raise ValueError(f"FSI face {face_id!r} catalog centroid does not match mesh")
                if any(
                    abs(catalog_normal[axis] - normal[axis])
                    > _SURFACE_GEOMETRY_TOLERANCE
                    for axis in range(3)
                ):
                    raise ValueError(f"FSI face {face_id!r} catalog normal does not match mesh")
                face_rows.append(row)
        ordered_rows = sorted(face_rows, key=lambda row: _mapping_string(row, "face_id"))
        face_ids = tuple(_mapping_string(row, "face_id") for row in ordered_rows)
        if len(face_ids) != len(set(face_ids)):
            raise ValueError("FSI surface catalog contains duplicate face ids")
        element_ids = tuple(_mapping_integer(row, "element_id") for row in ordered_rows)
        required = {f"surface:{face_id}" for face_id in face_ids}
        if not required <= context.available_ids:
            missing = sorted(required - context.available_ids)
            raise ValueError(f"FSI surface id is unavailable: {missing[0]!r}")
        resources = _nested_mapping(normalized, "resources")
        resource_ids = tuple(
            _resource_identity(_nested_mapping(resources, key))
            for key in (
                "air_material",
                "explosive_material",
                "equation_of_state",
                "ale_keyword",
            )
        )
        unavailable_resources = sorted(
            f"resource:{identity}"
            for identity in resource_ids
            if f"resource:{identity}" not in context.available_ids
        )
        if unavailable_resources:
            raise ValueError(f"neutral resource is unavailable: {unavailable_resources[0]!r}")
        return _ValidatedState(
            normalized=normalized,
            bounds_m=bounds,
            position_m=position,  # type: ignore[arg-type]
            cell_size_m=_mapping_number(domain, "target_cell_size_m"),
            categories=categories,
            fsi_face_ids=face_ids,
            fsi_element_ids=element_ids,
            resource_ids=resource_ids,
            containing_space_id=containing_space,
            external_opening_ids=external_openings,
        )

    def _allocate_mesh(
        self, state: _ValidatedState, estimate: ProviderEstimate
    ) -> tuple[
        tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]],
        tuple[str, ...],
        tuple[str, ...],
    ]:
        axes = tuple(
            tuple(
                state.bounds_m[axis]
                + (state.bounds_m[axis + 3] - state.bounds_m[axis]) * index / (count - 1)
                for index in range(count)
            )
            for axis, count in enumerate(estimate.axis_point_counts)
        )
        nx, ny, nz = estimate.axis_point_counts
        node_ids = tuple(
            f"explicit_ale_fsi:node:{ix}:{iy}:{iz}"
            for iz in range(nz)
            for iy in range(ny)
            for ix in range(nx)
        )
        element_ids = tuple(
            f"explicit_ale_fsi:solid:{ix}:{iy}:{iz}"
            for iz in range(nz - 1)
            for iy in range(ny - 1)
            for ix in range(nx - 1)
        )
        return axes, node_ids, element_ids  # type: ignore[return-value]

    def _build_evidence(
        self,
        state: _ValidatedState,
        context: ProviderContext,
        estimate: ProviderEstimate,
        actual: Mapping[str, object],
        resource_ids: tuple[str, ...],
    ) -> tuple[ProviderEvidence, ...]:
        charge = _nested_mapping(state.normalized, "charge")
        source_declared_id = f"charge:{_mapping_string(charge, 'source_id')}"
        source_evidence = source_space_evidence(
            provider_id=self.provider_id,
            source_declared_id=source_declared_id,
            source_space_id=state.containing_space_id or "exterior",
            context=context,
            determination="verified_position_containment",
            external_opening_ids=state.external_opening_ids,
        )
        rows = (
            (
                "classified_surface_catalog",
                tuple(f"surface:{face_id}" for face_id in state.fsi_face_ids),
                {"categories": state.categories, "catalog_only": True},
            ),
            (
                "preallocation_budget",
                (f"estimate:{estimate.fingerprint}",),
                {
                    "estimated_node_count": estimate.node_count,
                    "estimated_element_count": estimate.element_count,
                    "actual": actual,
                    "budget_checked_before_allocation": True,
                },
            ),
            (
                "neutral_resource_lineage",
                tuple(f"resource:{identity}" for identity in resource_ids),
                {"versioned": True, "solver_material_validation": False},
            ),
        )
        evidence: list[ProviderEvidence] = [source_evidence]
        for index, (kind, source_ids, claims) in enumerate(rows, start=2):
            digest = fingerprint_value(
                {"kind": kind, "source_ids": source_ids, "claims": claims}
            )
            evidence.append(
                ProviderEvidence(
                    evidence_id=f"explicit_ale_fsi:evidence:{index}:{digest[:16]}",
                    evidence_kind=kind,
                    source_ids=source_ids,
                    claims=claims,
                )
            )
        return tuple(evidence)


def _closed_mapping(
    value: object, expected_keys: frozenset[str], path: str
) -> Mapping[str, object]:
    mapping = _as_mapping(value, path)
    actual = set(mapping)
    unknown = sorted(actual - expected_keys)
    missing = sorted(expected_keys - actual)
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


def _require_literal(
    value: Mapping[str, object], key: str, expected: str, path: str
) -> None:
    actual = value.get(key)
    if actual != expected:
        raise ValueError(f"{path}.{key} must be {expected!r}")


def _safe_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value.strip()


def _safe_identifier_token(value: object, path: str) -> str:
    token = _safe_string(value, path)
    if (
        not isinstance(value, str)
        or value != token
        or token in {".", ".."}
        or _SAFE_ID_TOKEN_RE.fullmatch(token) is None
    ):
        raise ValueError(f"{path} must be a safe identifier token")
    return token


def _mapping_string(value: Mapping[str, object], key: str) -> str:
    return _safe_string(value.get(key), key)


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


def _nonnegative_number(value: object, path: str) -> float:
    number = _finite_number(value, path)
    if number < 0.0:
        raise ValueError(f"{path} must be non-negative")
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


def _vector(value: object, size: int, path: str) -> tuple[float, ...]:
    if not _is_sequence(value) or len(value) != size:
        raise ValueError(f"{path} must contain exactly {size} finite numbers")
    return tuple(_finite_number(item, f"{path}[{index}]") for index, item in enumerate(value))


def _bounds(value: object, path: str) -> tuple[float, float, float, float, float, float]:
    numbers = _vector(value, 6, path)
    if any(numbers[axis + 3] <= numbers[axis] for axis in range(3)):
        raise ValueError(f"{path} must have positive extent on every axis")
    return numbers  # type: ignore[return-value]


def _string_sequence(value: object, path: str) -> tuple[str, ...]:
    if not _is_sequence(value):
        raise ValueError(f"{path} must be a sequence")
    return tuple(_safe_string(item, f"{path}[{index}]") for index, item in enumerate(value))


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _point_in_box(
    point: Sequence[float], bounds: Sequence[float], *, strict: bool
) -> bool:
    comparator = (
        (lambda axis: bounds[axis] < point[axis] < bounds[axis + 3])
        if strict
        else (lambda axis: bounds[axis] <= point[axis] <= bounds[axis + 3])
    )
    return all(comparator(axis) for axis in range(3))


def _point_in_structural_volume(point: Sequence[float], context: ProviderContext) -> bool:
    node_by_id = {node.node_id: node for node in context.artifact.mesh.nodes}
    for solid in context.artifact.mesh.solids:
        coordinates = tuple(node_by_id[node_id].coordinates for node_id in solid.node_ids)
        bounds = tuple(
            (
                min(row[axis] for row in coordinates)
                if side == 0
                else max(row[axis] for row in coordinates)
            )
            for side in (0, 1)
            for axis in range(3)
        )
        reordered = (*bounds[:3], *bounds[3:])
        if _point_in_box(point, reordered, strict=True):
            return True
    return False


def _surface_geometry(
    coordinates: tuple[tuple[float, float, float], ...],
) -> tuple[float, tuple[float, float, float], tuple[float, float, float]]:
    origin = coordinates[0]
    area_vector = [0.0, 0.0, 0.0]
    for index in range(1, len(coordinates) - 1):
        first = tuple(coordinates[index][axis] - origin[axis] for axis in range(3))
        second = tuple(coordinates[index + 1][axis] - origin[axis] for axis in range(3))
        cross = (
            first[1] * second[2] - first[2] * second[1],
            first[2] * second[0] - first[0] * second[2],
            first[0] * second[1] - first[1] * second[0],
        )
        for axis in range(3):
            area_vector[axis] += cross[axis]
    magnitude = math.sqrt(sum(value * value for value in area_vector))
    area_m2 = magnitude / 2.0
    centroid = tuple(
        sum(point[axis] for point in coordinates) / len(coordinates)
        for axis in range(3)
    )
    normal = (
        tuple(value / magnitude for value in area_vector)
        if magnitude > _SURFACE_AREA_TOLERANCE_M2 * 2.0
        else (0.0, 0.0, 0.0)
    )
    return area_m2, centroid, normal  # type: ignore[return-value]


def _containing_space(point: Sequence[float], topology: ProviderTopology) -> str | None:
    matches = tuple(
        row.region_id for row in topology.spaces if _point_in_box(point, row.bounds_m, strict=True)
    )
    if len(matches) > 1:
        raise ValueError("detonation point is contained by multiple spaces")
    return matches[0] if matches else None


def _external_passage_paths(
    source_space_id: str, topology: ProviderTopology
) -> tuple[tuple[str, ...], ...]:
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for opening in topology.openings:
        left, right = opening.connects
        adjacency.setdefault(left, []).append((right, opening.opening_id))
        adjacency.setdefault(right, []).append((left, opening.opening_id))
    frontier: list[tuple[str, tuple[str, ...], frozenset[str]]] = [
        (source_space_id, (), frozenset({source_space_id}))
    ]
    paths: list[tuple[str, ...]] = []
    while frontier:
        current, passage, visited = frontier.pop(0)
        for neighbour, opening_id in sorted(adjacency.get(current, ())):
            next_passage = (*passage, opening_id)
            if neighbour == "exterior":
                paths.append(next_passage)
                continue
            if neighbour not in visited:
                frontier.append((neighbour, next_passage, visited | {neighbour}))
    return tuple(paths)


def _box_contains_box(outer: Sequence[float], inner: Sequence[float]) -> bool:
    return all(
        outer[axis] <= inner[axis] and outer[axis + 3] >= inner[axis + 3]
        for axis in range(3)
    )


def _domain_has_external_buffer(
    domain: Sequence[float],
    topology: ProviderTopology,
    opening_ids: tuple[str, ...],
    buffer_m: float,
) -> bool:
    envelope = topology.envelope_bounds_m
    openings = {row.opening_id: row for row in topology.openings}
    terminal = openings[opening_ids[-1]]
    return any(
        domain[axis] <= envelope[axis] - buffer_m
        if side == "min"
        else domain[axis + 3] >= envelope[axis + 3] + buffer_m
        for axis, side in _terminal_opening_directions(terminal, topology)
    )


def _terminal_opening_directions(
    opening: object, topology: ProviderTopology
) -> tuple[tuple[int, str], ...]:
    if not isinstance(opening, TopologyOpening) or "exterior" not in opening.connects:
        return ()
    envelope = topology.envelope_bounds_m
    tolerance = 1.0e-12
    directions: list[tuple[int, str]] = []
    for axis in range(3):
        other_axes = tuple(candidate for candidate in range(3) if candidate != axis)
        has_in_plane_overlap = all(
            min(opening.bounds_m[other + 3], envelope[other + 3])
            - max(opening.bounds_m[other], envelope[other])
            > tolerance
            for other in other_axes
        )
        if not has_in_plane_overlap:
            continue
        if (
            opening.bounds_m[axis] - tolerance
            <= envelope[axis]
            <= opening.bounds_m[axis + 3] + tolerance
        ):
            directions.append((axis, "min"))
        if (
            opening.bounds_m[axis] - tolerance
            <= envelope[axis + 3]
            <= opening.bounds_m[axis + 3] + tolerance
        ):
            directions.append((axis, "max"))
    return tuple(directions)


def _resource_identity(value: Mapping[str, object]) -> str:
    return f"{_mapping_string(value, 'resource_id')}@{_mapping_string(value, 'version')}"


__all__ = ["ExplicitAleFsiProvider"]
