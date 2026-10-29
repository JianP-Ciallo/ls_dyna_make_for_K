"""Closed, immutable input contracts for refined-building blast projects."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Protocol, TypeAlias


ScenarioKind: TypeAlias = Literal["external", "internal", "semi_enclosed"]
_SCHEMA_VERSION = "refined_building_blast@1"
_SCENARIO_KINDS = frozenset({"external", "internal", "semi_enclosed"})
_PROVIDER_IDS = frozenset(
    {
        "explicit_ale_fsi",
        "lbe_segment",
        "imported_pressure_history",
        "solver_complete_ale_fsi",
    }
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SAFE_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_EMPTY_MAPPING_KEYS = frozenset[str]()
_BUILDING_REFERENCE_KEYS = frozenset({"asset_id"})
_LOAD_PROVIDER_KEYS = frozenset({"provider_id", "provider_input"})
_MODULE_COMMON_KEYS = frozenset({"schema_version", "unit_system", "budgets"})
_MODULE_BUDGET_KEYS = frozenset({"schema_version", "max_new_nodes", "max_new_elements"})
_PLACEMENT_KEYS = _MODULE_COMMON_KEYS | frozenset({"building_count", "translation_m"})
_SUPPORT_KEYS = _MODULE_COMMON_KEYS | frozenset({"support_face_ids", "coupling_semantics"})
_SOURCE_KEYS = _MODULE_COMMON_KEYS | frozenset({"source_declared_id", "source_space_id"})
_FLUID_KEYS = _MODULE_COMMON_KEYS | frozenset(
    {"source_space_id", "opening_states", "external_buffer_m"}
)
_BOUNDARY_KEYS = _MODULE_COMMON_KEYS | frozenset({"assignments"})
_INTERACTION_KEYS = _MODULE_COMMON_KEYS | frozenset({"pairs"})
_MODULE_SCHEMA_BY_PATH = {
    "scenario.building_placement": "refined_blast.placement@1",
    "scenario.support_and_ground": "refined_blast.support_ground@1",
    "scenario.blast_source": "refined_blast.blast_source@1",
    "scenario.fluid_domain": "refined_blast.fluid_domain@1",
    "scenario.boundaries": "refined_blast.boundaries@1",
    "scenario.interactions": "refined_blast.interactions@1",
}
_MODULE_UNIT_SYSTEM = "SI_m_s_kg_N_Pa"
_MODULE_BUDGET_VERSION = "refined_blast.module_budgets@1"
_MODULE_BUDGET_HARD_LIMIT = 10_000_000
_BOUNDARY_ASSIGNMENT_KEYS = frozenset({"boundary_id", "face_id", "boundary_type"})
_INTERACTION_PAIR_KEYS = frozenset(
    {"interaction_id", "interaction_type", "source_id", "target_id"}
)
_PROJECT_KEYS = frozenset(
    {
        "schema_version",
        "project_id",
        "building_reference",
        "building_artifact_fingerprint",
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
_SCENARIO_KEYS = frozenset(
    {
        "scenario_id",
        "scenario_kind",
        "building_placement",
        "support_and_ground",
        "load_provider",
        "blast_source",
        "fluid_domain",
        "boundaries",
        "interactions",
        "solver_controls",
        "output_requests",
        "resource_versions",
        "acknowledged_warning_ids",
    }
)


def scenario_draft_ui_schema(
    provider_input_schemas: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Public closed browser shape for the ScenarioDraft contract.

    Provider input alternatives are attached by the API after it has loaded the
    registered provider-owned schemas; all other modules are closed here beside
    their authoritative key sets.
    """
    scalar: dict[str, object] = {"ui_validation": "backend_normalizer"}
    def module(keys: frozenset[str]) -> dict[str, object]:
        properties = {key: scalar for key in sorted(keys)}
        if "budgets" in properties:
            properties["budgets"] = {
                "type": "object", "additionalProperties": False,
                "required": sorted(_MODULE_BUDGET_KEYS),
                "properties": {
                    "schema_version": {"type": "string", "const": _MODULE_BUDGET_VERSION},
                    "max_new_nodes": {"type": "integer", "minimum": 1},
                    "max_new_elements": {"type": "integer", "minimum": 1},
                },
            }
        if "assignments" in properties:
            properties["assignments"] = {
                "type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": sorted(_BOUNDARY_ASSIGNMENT_KEYS),
                    "properties": {key: {"type": "string"} for key in sorted(_BOUNDARY_ASSIGNMENT_KEYS)},
                },
            }
        if "pairs" in properties:
            properties["pairs"] = {
                "type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": sorted(_INTERACTION_PAIR_KEYS),
                    "properties": {key: {"type": "string"} for key in sorted(_INTERACTION_PAIR_KEYS)},
                },
            }
        if "opening_states" in properties:
            properties["opening_states"] = {
                "type": "object", "additionalProperties": {"type": "string", "enum": ["open", "closed"]},
                "properties": {},
            }
        full = {"type": "object", "additionalProperties": False, "required": sorted(keys), "properties": properties}
        # The canonical contract deliberately retains legacy-empty module maps.
        return {"oneOf": [{"type": "object", "additionalProperties": False, "required": [], "properties": {}}, full]}
    providers = provider_input_schemas or {}
    load_provider_branches = [
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["provider_id", "provider_input"],
            "properties": {
                "provider_id": {"type": "string", "const": provider_id},
                "provider_input": dict(input_schema),
            },
        }
        for provider_id, input_schema in sorted(providers.items())
    ]
    return {
        "type": "object", "additionalProperties": False, "required": sorted(_SCENARIO_KEYS), "properties": {
            "scenario_id": {"type": "string"}, "scenario_kind": {"type": "string", "enum": sorted(_SCENARIO_KINDS)},
            "building_placement": module(_PLACEMENT_KEYS), "support_and_ground": module(_SUPPORT_KEYS),
            "load_provider": {"oneOf": load_provider_branches} if load_provider_branches else {"type": "object", "additionalProperties": False, "required": ["provider_id", "provider_input"], "properties": {"provider_id": {"type": "string", "enum": sorted(_PROVIDER_IDS)}, "provider_input": {}}},
            "blast_source": module(_SOURCE_KEYS), "fluid_domain": module(_FLUID_KEYS), "boundaries": module(_BOUNDARY_KEYS), "interactions": module(_INTERACTION_KEYS),
            "solver_controls": _solver_controls_ui_schema(),
            "output_requests": _output_requests_ui_schema(),
            "resource_versions": {"type": "object", "additionalProperties": False, "required": [], "properties": {}},
            "acknowledged_warning_ids": {"type": "array", "items": {"type": "string"}},
        },
    }


def _solver_controls_ui_schema() -> dict[str, object]:
    from .controls import solver_controls_ui_schema
    return solver_controls_ui_schema()


def _output_requests_ui_schema() -> dict[str, object]:
    from .outputs import output_requests_ui_schema
    return output_requests_ui_schema()


def default_scenario_draft() -> dict[str, object]:
    """Return a normalizer-valid browser seed from provider-owned defaults."""

    from .provider_registry import get_load_provider

    provider = get_load_provider("lbe_segment")
    return {
        "scenario_id": "scenario-1", "scenario_kind": "external",
        "building_placement": {}, "support_and_ground": {},
        "load_provider": {"provider_id": provider.provider_id, "provider_input": dict(getattr(provider, "default_input")())},
        "blast_source": {}, "fluid_domain": {}, "boundaries": {}, "interactions": {},
        "solver_controls": {}, "output_requests": {}, "resource_versions": {},
        "acknowledged_warning_ids": [],
    }


FrozenMapping: TypeAlias = Mapping[str, object]


@dataclass(frozen=True)
class ScenarioDraft:
    """One independently compilable blast scenario, normalized without defaults."""

    scenario_id: str
    scenario_kind: ScenarioKind
    building_placement: FrozenMapping
    support_and_ground: FrozenMapping
    load_provider: FrozenMapping
    blast_source: FrozenMapping
    fluid_domain: FrozenMapping
    boundaries: FrozenMapping
    interactions: FrozenMapping
    solver_controls: FrozenMapping
    output_requests: FrozenMapping
    resource_versions: FrozenMapping
    acknowledged_warning_ids: tuple[str, ...]


@dataclass(frozen=True)
class RefinedBlastProject:
    """Versioned project root; every nested collection is canonical and immutable."""

    schema_version: Literal["refined_building_blast@1"]
    project_id: str
    building_reference: FrozenMapping
    building_artifact_fingerprint: str
    preset_reference: str
    preset_version: str
    project_overrides: FrozenMapping
    expert_extensions: FrozenMapping
    scenario_set: tuple[ScenarioDraft, ...]
    confirmation_records: tuple[FrozenMapping, ...]
    provenance: FrozenMapping
    created_at: str
    updated_at: str


class ScenarioContext(Protocol):
    """Marker protocol for the later immutable scenario compilation context."""


@dataclass(frozen=True)
class Finding:
    """Minimal immutable diagnostic shared by providers and later validation."""

    finding_id: str
    severity: Literal["error", "warning", "info"]
    message: str


class BlastLoadProvider(Protocol):
    provider_id: str

    def schema(self) -> Mapping[str, object]:
        raise NotImplementedError

    def capabilities(self) -> Mapping[str, object]:
        raise NotImplementedError

    def normalize(self, value: Mapping[str, object]) -> Mapping[str, object]:
        raise NotImplementedError

    def default_input(self) -> Mapping[str, object]:
        """Return a normalizer-valid JSON-safe seed for isolated drafts."""
        raise NotImplementedError

    def validate(
        self, value: Mapping[str, object], context: ScenarioContext
    ) -> tuple[Finding, ...]:
        raise NotImplementedError


def normalize_refined_blast_project(value: Mapping[str, object]) -> RefinedBlastProject:
    """Return a closed-schema, immutable project or reject the input safely."""

    raw = _require_mapping(value, "project")
    _require_exact_keys(raw, _PROJECT_KEYS, "project")
    schema_version = _require_string(raw, "schema_version", "project")
    if schema_version != _SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {_SCHEMA_VERSION!r}")
    project_id = _require_safe_identifier(raw, "project_id", "project")
    fingerprint = _require_sha256(raw, "building_artifact_fingerprint", "project")
    scenario_rows = _require_sequence(raw, "scenario_set", "project")
    if not scenario_rows:
        raise ValueError("project.scenario_set must not be empty")
    scenarios = tuple(
        normalize_scenario_draft(_require_mapping(row, f"project.scenario_set[{index}]"))
        for index, row in enumerate(scenario_rows)
    )
    _require_unique((scenario.scenario_id for scenario in scenarios), "scenario id")
    records = _require_sequence(raw, "confirmation_records", "project")
    if records:
        raise ValueError("project.confirmation_records has no declared record contract")
    building_reference = _canonical_closed_mapping(
        raw["building_reference"], _BUILDING_REFERENCE_KEYS, "project.building_reference"
    )
    _require_safe_identifier(building_reference, "asset_id", "project.building_reference")
    return RefinedBlastProject(
        schema_version="refined_building_blast@1",
        project_id=project_id,
        building_reference=building_reference,
        building_artifact_fingerprint=fingerprint,
        preset_reference=_require_string(raw, "preset_reference", "project"),
        preset_version=_require_string(raw, "preset_version", "project"),
        project_overrides=_canonical_closed_mapping(
            raw["project_overrides"], _EMPTY_MAPPING_KEYS, "project.project_overrides"
        ),
        expert_extensions=_canonical_closed_mapping(
            raw["expert_extensions"], _EMPTY_MAPPING_KEYS, "project.expert_extensions"
        ),
        scenario_set=scenarios,
        confirmation_records=(),
        provenance=_canonical_closed_mapping(
            raw["provenance"], _EMPTY_MAPPING_KEYS, "project.provenance"
        ),
        created_at=_require_string(raw, "created_at", "project"),
        updated_at=_require_string(raw, "updated_at", "project"),
    )


def normalize_scenario_draft(value: Mapping[str, object]) -> ScenarioDraft:
    """Return a closed-schema, immutable scenario draft with no inferred behavior."""

    raw = _require_mapping(value, "scenario")
    _require_exact_keys(raw, _SCENARIO_KEYS, "scenario")
    kind = _require_string(raw, "scenario_kind", "scenario")
    if kind not in _SCENARIO_KINDS:
        raise ValueError(f"unsupported scenario_kind: {kind!r}")
    provider = _normalize_load_provider(raw["load_provider"])
    provider_id = _require_string(provider, "provider_id", "scenario.load_provider")
    if provider_id not in _PROVIDER_IDS:
        raise ValueError(f"unsupported load_provider.provider_id: {provider_id!r}")
    warning_ids = _require_sequence(raw, "acknowledged_warning_ids", "scenario")
    normalized_warning_ids = tuple(
        _require_safe_string(warning_id, f"scenario.acknowledged_warning_ids[{index}]")
        for index, warning_id in enumerate(warning_ids)
    )
    _require_unique(normalized_warning_ids, "acknowledged_warning_id")
    return ScenarioDraft(
        scenario_id=_require_safe_identifier(raw, "scenario_id", "scenario"),
        scenario_kind=kind,  # type: ignore[arg-type]
        building_placement=_canonical_module_mapping(
            raw["building_placement"], _PLACEMENT_KEYS, "scenario.building_placement"
        ),
        support_and_ground=_canonical_module_mapping(
            raw["support_and_ground"], _SUPPORT_KEYS, "scenario.support_and_ground"
        ),
        load_provider=provider,
        blast_source=_canonical_module_mapping(raw["blast_source"], _SOURCE_KEYS, "scenario.blast_source"),
        fluid_domain=_canonical_module_mapping(raw["fluid_domain"], _FLUID_KEYS, "scenario.fluid_domain"),
        boundaries=_canonical_module_mapping(raw["boundaries"], _BOUNDARY_KEYS, "scenario.boundaries"),
        interactions=_canonical_module_mapping(raw["interactions"], _INTERACTION_KEYS, "scenario.interactions"),
        solver_controls=_normalize_solver_controls(raw["solver_controls"]),
        output_requests=_normalize_output_requests(raw["output_requests"]),
        resource_versions=_canonical_closed_mapping(
            raw["resource_versions"], _EMPTY_MAPPING_KEYS, "scenario.resource_versions"
        ),
        acknowledged_warning_ids=normalized_warning_ids,
    )


def _require_exact_keys(value: Mapping[str, object], expected: frozenset[str], path: str) -> None:
    actual = set(value)
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unknown:
        raise ValueError(f"{path} has unknown field: {unknown[0]!r}")
    if missing:
        raise ValueError(f"{path} is missing required field: {missing[0]!r}")


def _require_mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be a mapping")
    if any(not isinstance(key, str) or not key for key in value):
        raise ValueError(f"{path} keys must be non-empty strings")
    return value


def _require_sequence(value: Mapping[str, object], key: str, path: str) -> Sequence[object]:
    nested = value.get(key)
    if not isinstance(nested, Sequence) or isinstance(nested, (str, bytes, bytearray)):
        raise ValueError(f"{path}.{key} must be a sequence")
    return nested


def _require_string(value: Mapping[str, object], key: str, path: str) -> str:
    return _require_safe_string(value.get(key), f"{path}.{key}")


def _require_safe_identifier(value: Mapping[str, object], key: str, path: str) -> str:
    identifier = _require_string(value, key, path)
    return validate_refined_identifier(identifier, f"{path}.{key}")


def validate_refined_identifier(value: object, label: str) -> str:
    """Return the one ASCII identifier grammar used by contracts, routes and storage."""

    if (
        not isinstance(value, str)
        or _SAFE_IDENTIFIER_RE.fullmatch(value) is None
        or value in {".", ".."}
    ):
        raise ValueError(f"{label} must be a safe identifier")
    return value


def _require_safe_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value.strip()


def _require_sha256(value: Mapping[str, object], key: str, path: str) -> str:
    digest = _require_string(value, key, path).lower()
    if not _SHA256_RE.fullmatch(digest):
        raise ValueError(f"{path}.{key} must be a SHA-256 fingerprint")
    return digest


def _canonical_closed_mapping(
    value: object, expected_keys: frozenset[str], path: str
) -> FrozenMapping:
    mapping = _require_mapping(value, path)
    _require_exact_keys(mapping, expected_keys, path)
    canonical = {
        key: _canonical_value(nested, f"{path}.{key}", frozenset({id(mapping)}))
        for key, nested in sorted(mapping.items())
    }
    return MappingProxyType(canonical)


def _canonical_module_mapping(
    value: object, expected_keys: frozenset[str], path: str
) -> FrozenMapping:
    """Preserve legacy-empty maps while accepting only a complete module schema."""

    mapping = _require_mapping(value, path)
    if not mapping:
        return MappingProxyType({})
    _require_exact_keys(mapping, expected_keys, path)
    budgets = _require_mapping(mapping["budgets"], f"{path}.budgets")
    _require_exact_keys(budgets, _MODULE_BUDGET_KEYS, f"{path}.budgets")
    canonical = MappingProxyType(
        {
            key: _canonical_value(nested, f"{path}.{key}", frozenset({id(mapping)}))
            for key, nested in sorted(mapping.items())
        }
    )
    _validate_module_values(canonical, path)
    return canonical


def _validate_module_values(value: FrozenMapping, path: str) -> None:
    expected_schema = _MODULE_SCHEMA_BY_PATH[path]
    if value.get("schema_version") != expected_schema:
        raise ValueError(f"{path}.schema_version must be {expected_schema!r}")
    if value.get("unit_system") != _MODULE_UNIT_SYSTEM:
        raise ValueError(f"{path}.unit_system must be {_MODULE_UNIT_SYSTEM!r}")
    budgets = _require_mapping(value.get("budgets"), f"{path}.budgets")
    if budgets.get("schema_version") != _MODULE_BUDGET_VERSION:
        raise ValueError(
            f"{path}.budgets.schema_version must be {_MODULE_BUDGET_VERSION!r}"
        )
    for key in ("max_new_nodes", "max_new_elements"):
        raw = budgets.get(key)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
            raise ValueError(f"{path}.budgets.{key} must be a positive integer")
        if raw > _MODULE_BUDGET_HARD_LIMIT:
            raise ValueError(
                f"{path}.budgets.{key} exceeds hard safety limit "
                f"{_MODULE_BUDGET_HARD_LIMIT}"
            )

    if path == "scenario.building_placement":
        count = value.get("building_count")
        if isinstance(count, bool) or not isinstance(count, int) or count != 1:
            raise ValueError(f"{path}.building_count must be exactly 1")
        _finite_vector(value.get("translation_m"), 3, f"{path}.translation_m")
    elif path == "scenario.support_and_ground":
        _token_sequence(value.get("support_face_ids"), f"{path}.support_face_ids", nonempty=True)
        if value.get("coupling_semantics") not in {"shared_node", "tied"}:
            raise ValueError(f"{path}.coupling_semantics must be shared_node or tied")
    elif path == "scenario.blast_source":
        _safe_token_value(value.get("source_declared_id"), f"{path}.source_declared_id")
        _safe_token_value(value.get("source_space_id"), f"{path}.source_space_id")
    elif path == "scenario.fluid_domain":
        _safe_token_value(value.get("source_space_id"), f"{path}.source_space_id")
        states = _require_mapping(value.get("opening_states"), f"{path}.opening_states")
        for opening_id, state in states.items():
            _safe_token_value(opening_id, f"{path}.opening_states key")
            if state not in {"open", "closed"}:
                raise ValueError(f"{path}.opening_states.{opening_id} must be open or closed")
        external_buffer = _finite_number(value.get("external_buffer_m"), f"{path}.external_buffer_m")
        if external_buffer < 0:
            raise ValueError(f"{path}.external_buffer_m must be non-negative")
    elif path == "scenario.boundaries":
        rows = _module_rows(value.get("assignments"), f"{path}.assignments")
        for index, row in enumerate(rows):
            row_path = f"{path}.assignments[{index}]"
            _require_exact_keys(row, _BOUNDARY_ASSIGNMENT_KEYS, row_path)
            _safe_token_value(row.get("boundary_id"), f"{row_path}.boundary_id")
            _safe_token_value(row.get("face_id"), f"{row_path}.face_id")
            if row.get("boundary_type") not in {"non_reflecting", "rigid"}:
                raise ValueError(f"{row_path}.boundary_type is unsupported")
    elif path == "scenario.interactions":
        rows = _module_rows(value.get("pairs"), f"{path}.pairs")
        for index, row in enumerate(rows):
            row_path = f"{path}.pairs[{index}]"
            _require_exact_keys(row, _INTERACTION_PAIR_KEYS, row_path)
            for key in ("interaction_id", "source_id", "target_id"):
                _safe_token_value(row.get(key), f"{row_path}.{key}")
            if row.get("interaction_type") not in {"fsi_candidate", "tie_candidate"}:
                raise ValueError(f"{row_path}.interaction_type is unsupported")


def _module_rows(value: object, path: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{path} must be a sequence")
    return tuple(_require_mapping(row, f"{path}[{index}]") for index, row in enumerate(value))


def _token_sequence(value: object, path: str, *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{path} must be a sequence")
    result = tuple(_safe_token_value(row, f"{path}[{index}]") for index, row in enumerate(value))
    if nonempty and not result:
        raise ValueError(f"{path} must not be empty")
    _require_unique(result, path)
    return result


def _safe_token_value(value: object, path: str) -> str:
    token = _require_safe_string(value, path)
    if any(character.isspace() for character in token) or any(
        character in token for character in ("/", "\\", "\x00")
    ) or token in {".", ".."}:
        raise ValueError(f"{path} must be a safe identifier")
    return token


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


def _finite_vector(value: object, size: int, path: str) -> tuple[float, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)) or len(value) != size:
        raise ValueError(f"{path} must contain exactly {size} finite numbers")
    return tuple(_finite_number(row, f"{path}[{index}]") for index, row in enumerate(value))


def _normalize_load_provider(value: object) -> FrozenMapping:
    """Close a provider identity and its exact, provider-normalized input together."""

    mapping = _require_mapping(value, "scenario.load_provider")
    unknown = sorted(set(mapping) - _LOAD_PROVIDER_KEYS)
    if unknown:
        raise ValueError(f"scenario.load_provider has unknown field: {unknown[0]!r}")
    provider_id = _require_safe_identifier(mapping, "provider_id", "scenario.load_provider")
    if provider_id not in _PROVIDER_IDS:
        raise ValueError(f"unsupported load_provider.provider_id: {provider_id!r}")
    if "provider_input" not in mapping:
        raise ValueError("scenario.load_provider is missing required field: 'provider_input'")
    normalized: dict[str, object] = {"provider_id": provider_id}
    input_value = _require_mapping(mapping["provider_input"], "scenario.load_provider.provider_input")
    from .provider_registry import get_load_provider

    try:
        provider_input = get_load_provider(provider_id).normalize(input_value)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError(f"scenario.load_provider.provider_input is invalid: {exc}") from exc
    normalized["provider_input"] = _canonical_value(
        provider_input,
        "scenario.load_provider.provider_input",
        frozenset(),
    )
    return MappingProxyType(normalized)


def _normalize_solver_controls(value: object) -> FrozenMapping:
    from .controls import normalize_solver_controls

    normalized = normalize_solver_controls(
        _require_mapping(value, "scenario.solver_controls")
    )
    return MappingProxyType(dict(normalized))


def _normalize_output_requests(value: object) -> FrozenMapping:
    from .outputs import normalize_output_requests

    normalized = normalize_output_requests(
        _require_mapping(value, "scenario.output_requests")
    )
    return MappingProxyType(dict(normalized))


def _canonical_value(value: object, path: str, ancestors: frozenset[int]) -> object:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        raise ValueError(f"{path} must not use bool as a number")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must be finite")
        return value
    if isinstance(value, Mapping):
        if id(value) in ancestors:
            raise ValueError(f"{path} must not contain cyclic containers")
        nested_ancestors = ancestors | {id(value)}
        return MappingProxyType(
            {
                key: _canonical_value(nested, f"{path}.{key}", nested_ancestors)
                for key, nested in sorted(_require_mapping(value, path).items())
            }
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if id(value) in ancestors:
            raise ValueError(f"{path} must not contain cyclic containers")
        nested_ancestors = ancestors | {id(value)}
        return tuple(
            _canonical_value(item, f"{path}[{index}]", nested_ancestors)
            for index, item in enumerate(value)
        )
    raise ValueError(f"{path} must contain only canonical JSON values")


def _require_unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value!r}")
        seen.add(value)
