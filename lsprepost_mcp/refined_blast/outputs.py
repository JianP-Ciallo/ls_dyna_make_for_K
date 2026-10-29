"""Closed, SI-only output-request records for Phase 18E candidate packages."""

from __future__ import annotations

import math
from collections.abc import Mapping

from .fragments import KeywordFragment, require_token
from .providers.common import FrozenMapping, freeze_value


_SCHEMA_VERSION = "refined_blast.output_requests@1"
_UNIT_SYSTEM = "SI_m_s_kg_N_Pa"
_INPUT_KEYS = frozenset(
    {"schema_version", "unit_system", "d3plot_interval_s", "history_interval_s"}
)
_DERIVED_KEYS = frozenset(
    {"research_candidate", "solver_ready", "requires_project_review", "engineering_validated"}
)
_DEFAULT = {
    "schema_version": _SCHEMA_VERSION,
    "unit_system": _UNIT_SYSTEM,
    "d3plot_interval_s": 0.001,
    "history_interval_s": 0.0001,
}


def output_requests_ui_schema() -> dict[str, object]:
    """Closed browser schema emitted from this normalizer's key contract."""
    properties = {
        key: ({"type": "string", "const": _SCHEMA_VERSION} if key == "schema_version" else {"type": "string", "const": _UNIT_SYSTEM} if key == "unit_system" else {"type": "number", "minimum": 0} if key in {"d3plot_interval_s", "history_interval_s"} else {"type": "boolean", "const": key in {"research_candidate", "requires_project_review"}})
        for key in sorted(_INPUT_KEYS | _DERIVED_KEYS)
    }
    return {"oneOf": [{"type": "object", "additionalProperties": False, "required": [], "properties": {}}, {"type": "object", "additionalProperties": False, "required": sorted(_INPUT_KEYS), "properties": properties}]}


def normalize_output_requests(value: Mapping[str, object] | None) -> FrozenMapping:
    """Return a closed immutable output record; empty input uses conservative defaults."""

    raw = dict(value or _DEFAULT)
    unknown = sorted(set(raw) - (_INPUT_KEYS | _DERIVED_KEYS))
    missing = sorted(_INPUT_KEYS - set(raw))
    if unknown:
        raise ValueError(f"output_requests has unknown field: {unknown[0]!r}")
    if missing:
        raise ValueError(f"output_requests is missing required field: {missing[0]!r}")
    if raw["schema_version"] != _SCHEMA_VERSION:
        raise ValueError(f"output_requests.schema_version must be {_SCHEMA_VERSION!r}")
    if raw["unit_system"] != _UNIT_SYSTEM:
        raise ValueError(f"output_requests.unit_system must be {_UNIT_SYSTEM!r}")
    d3plot = _finite_positive(raw["d3plot_interval_s"], "d3plot_interval_s")
    history = _finite_positive(raw["history_interval_s"], "history_interval_s")
    _require_conservative_flags(raw)
    frozen = freeze_value(
        {
            "schema_version": _SCHEMA_VERSION,
            "unit_system": _UNIT_SYSTEM,
            "d3plot_interval_s": d3plot,
            "history_interval_s": history,
            "research_candidate": True,
            "solver_ready": False,
            "requires_project_review": True,
            "engineering_validated": False,
        },
        "output_requests",
    )
    assert isinstance(frozen, Mapping)
    return frozen


def compile_output_requests(
    value: Mapping[str, object] | None, scenario_id: str
) -> KeywordFragment:
    normalized = normalize_output_requests(value)
    scenario = require_token(scenario_id, "scenario_id")
    return KeywordFragment(
        module_id="outputs",
        declared_ids=frozenset({f"outputs:{scenario}"}),
        required_ids=frozenset(),
        estimates={
            "new_nodes": 0,
            "new_elements": 0,
            "budget_limits": {"max_new_nodes": 1, "max_new_elements": 1},
            "budget_checked_before_allocation": True,
        },
        manifest=normalized,
    )


def _finite_positive(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"output_requests.{field} must be a finite positive number")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"output_requests.{field} must be a finite positive number")
    return number


def _require_conservative_flags(value: Mapping[str, object]) -> None:
    expected = {
        "research_candidate": True,
        "solver_ready": False,
        "requires_project_review": True,
        "engineering_validated": False,
    }
    for key, expected_value in expected.items():
        if key in value and value[key] is not expected_value:
            raise ValueError(f"output_requests.{key} must be {expected_value!r}")


__all__ = ["compile_output_requests", "normalize_output_requests", "output_requests_ui_schema"]
