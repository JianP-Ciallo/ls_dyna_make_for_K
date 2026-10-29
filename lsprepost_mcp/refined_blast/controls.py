"""Closed, SI-only solver-control records for Phase 18E candidate packages."""

from __future__ import annotations

import math
from collections.abc import Mapping

from .fragments import KeywordFragment, require_token
from .providers.common import FrozenMapping, freeze_value


_SCHEMA_VERSION = "refined_blast.solver_controls@1"
_UNIT_SYSTEM = "SI_m_s_kg_N_Pa"
_INPUT_KEYS = frozenset(
    {"schema_version", "unit_system", "termination_time_s", "timestep_scale_factor"}
)
_DERIVED_KEYS = frozenset(
    {"research_candidate", "solver_ready", "requires_project_review", "engineering_validated"}
)
_DEFAULT = {
    "schema_version": _SCHEMA_VERSION,
    "unit_system": _UNIT_SYSTEM,
    "termination_time_s": 0.1,
    "timestep_scale_factor": 0.67,
}


def solver_controls_ui_schema() -> dict[str, object]:
    """Closed browser schema emitted from this normalizer's key contract."""
    properties = {
        key: ({"type": "string", "const": _SCHEMA_VERSION} if key == "schema_version" else {"type": "string", "const": _UNIT_SYSTEM} if key == "unit_system" else {"type": "number", "minimum": 0} if key in {"termination_time_s", "timestep_scale_factor"} else {"type": "boolean", "const": key in {"research_candidate", "requires_project_review"}})
        for key in sorted(_INPUT_KEYS | _DERIVED_KEYS)
    }
    return {"oneOf": [{"type": "object", "additionalProperties": False, "required": [], "properties": {}}, {"type": "object", "additionalProperties": False, "required": sorted(_INPUT_KEYS), "properties": properties}]}


def normalize_solver_controls(value: Mapping[str, object] | None) -> FrozenMapping:
    """Return a closed immutable control record; empty input uses conservative defaults."""

    raw = dict(value or _DEFAULT)
    unknown = sorted(set(raw) - (_INPUT_KEYS | _DERIVED_KEYS))
    missing = sorted(_INPUT_KEYS - set(raw))
    if unknown:
        raise ValueError(f"solver_controls has unknown field: {unknown[0]!r}")
    if missing:
        raise ValueError(f"solver_controls is missing required field: {missing[0]!r}")
    if raw["schema_version"] != _SCHEMA_VERSION:
        raise ValueError(f"solver_controls.schema_version must be {_SCHEMA_VERSION!r}")
    if raw["unit_system"] != _UNIT_SYSTEM:
        raise ValueError(f"solver_controls.unit_system must be {_UNIT_SYSTEM!r}")
    termination = _finite_positive(raw["termination_time_s"], "termination_time_s")
    scale = _finite_positive(raw["timestep_scale_factor"], "timestep_scale_factor")
    if scale > 1.0:
        raise ValueError("solver_controls.timestep_scale_factor must not exceed 1")
    _require_conservative_flags(raw)
    frozen = freeze_value(
        {
            "schema_version": _SCHEMA_VERSION,
            "unit_system": _UNIT_SYSTEM,
            "termination_time_s": termination,
            "timestep_scale_factor": scale,
            "research_candidate": True,
            "solver_ready": False,
            "requires_project_review": True,
            "engineering_validated": False,
        },
        "solver_controls",
    )
    assert isinstance(frozen, Mapping)
    return frozen


def compile_solver_controls(
    value: Mapping[str, object] | None, scenario_id: str
) -> KeywordFragment:
    normalized = normalize_solver_controls(value)
    scenario = require_token(scenario_id, "scenario_id")
    return KeywordFragment(
        module_id="controls",
        declared_ids=frozenset({f"controls:{scenario}"}),
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
        raise ValueError(f"solver_controls.{field} must be a finite positive number")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"solver_controls.{field} must be a finite positive number")
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
            raise ValueError(f"solver_controls.{key} must be {expected_value!r}")


__all__ = ["compile_solver_controls", "normalize_solver_controls", "solver_controls_ui_schema"]
