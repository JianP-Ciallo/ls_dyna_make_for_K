"""Controlled ALE keyword foundations used by the Phase 14 scene compiler.

The complete reference assembly lives in :mod:`lsprepost_mcp.ale_blast`.
Neither module launches LS-Run or LS-DYNA.
"""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping, Sequence


ALE_UNIT_SYSTEM = "SI_m_s_kg_N_Pa"

_AIR_DEMO = {
    "type": "null_linear_polynomial_air",
    "name": "air_null_linear_polynomial_demo",
    "unit_system": ALE_UNIT_SYSTEM,
    "validation_status": "static_demo",
    "density_kg_per_m3": 1.225,
    "pressure_cutoff_pa": 0.0,
    "dynamic_viscosity_pa_s": 0.0,
    "eos": {
        "c0": 0.0,
        "c1": 0.0,
        "c2": 0.0,
        "c3": 0.0,
        "c4": 0.4,
        "c5": 0.4,
        "c6": 0.0,
        "initial_internal_energy_density_j_per_m3": 253312.5,
        "initial_relative_volume": 1.0,
    },
    "source": "LS-DYNA Eulerian/ALE documentation; SI demonstration values",
    "limitations": (
        "Static card demonstration only. It is not a validated explosive-air "
        "domain and must not be presented as solve-ready."
    ),
}

_AIR_KEYS = {
    "type",
    "name",
    "unit_system",
    "validation_status",
    "density_kg_per_m3",
    "pressure_cutoff_pa",
    "dynamic_viscosity_pa_s",
    "eos",
    "source",
    "limitations",
}
_EOS_KEYS = {
    "c0",
    "c1",
    "c2",
    "c3",
    "c4",
    "c5",
    "c6",
    "initial_internal_energy_density_j_per_m3",
    "initial_relative_volume",
}


def default_ale_air_definition() -> dict[str, Any]:
    """Return an isolated copy of the controlled Phase 14 air definition."""

    return deepcopy(_AIR_DEMO)


def phase14_capability_catalog() -> list[dict[str, str]]:
    """Describe implemented and gated Phase 14 capabilities."""

    return [
        {
            "capability": "air_material_and_eos",
            "status": "implemented_static",
            "note": "Controlled *MAT_NULL and *EOS_LINEAR_POLYNOMIAL cards.",
        },
        {
            "capability": "ale_multimaterial_section",
            "status": "implemented_static",
            "note": "ELFORM=11 setup requires at least two material groups.",
        },
        {
            "capability": "ale_control",
            "status": "implemented_static",
            "note": "A small reviewed *CONTROL_ALE preset is available.",
        },
        {
            "capability": "explosive_material_and_jwl",
            "status": "implemented_controlled_reference",
            "note": "Published SI Composition B reference parameters with review-required provenance.",
        },
        {
            "capability": "ale_lagrange_coupling",
            "status": "implemented_controlled_reference",
            "note": "Plate-to-ALE part-set coupling, volume fraction initialization, and non-reflecting boundaries.",
        },
        {
            "capability": "mesh_sensitivity_plan",
            "status": "implemented_not_solved",
            "note": "Coarse, baseline, and fine resource estimates are generated without claiming convergence.",
        },
        {
            "capability": "lsdyna_solve",
            "status": "explicit_user_approval_required",
            "note": "The project must never start LS-Run/LS-DYNA without approval.",
        },
    ]


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number")
    return result


def _positive_id(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _reject_unknown(raw: Mapping[str, object], allowed: set[str], field: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"{field} contains unknown fields: {', '.join(unknown)}")


def validate_ale_air_definition(raw: Mapping[str, object]) -> dict[str, Any]:
    """Validate the controlled SI air definition and return normalized values."""

    if not isinstance(raw, Mapping):
        raise ValueError("ALE air definition must be an object")
    _reject_unknown(raw, _AIR_KEYS, "ALE air definition")

    if raw.get("type") != "null_linear_polynomial_air":
        raise ValueError("ALE air type must be null_linear_polynomial_air")
    if raw.get("unit_system") != ALE_UNIT_SYSTEM:
        raise ValueError(f"ALE air unit_system must be {ALE_UNIT_SYSTEM}")
    if raw.get("validation_status") != "static_demo":
        raise ValueError("ALE air validation_status must be static_demo")
    if not isinstance(raw.get("name"), str) or not str(raw["name"]).strip():
        raise ValueError("ALE air name must be a non-empty string")
    if not isinstance(raw.get("source"), str) or not str(raw["source"]).strip():
        raise ValueError("ALE air source must be a non-empty string")
    if not isinstance(raw.get("limitations"), str) or not str(raw["limitations"]).strip():
        raise ValueError("ALE air limitations must be a non-empty string")

    density = _finite_number(raw.get("density_kg_per_m3"), "density_kg_per_m3")
    if density <= 0.0:
        raise ValueError("density_kg_per_m3 must be greater than zero")
    pressure_cutoff = _finite_number(raw.get("pressure_cutoff_pa"), "pressure_cutoff_pa")
    viscosity = _finite_number(
        raw.get("dynamic_viscosity_pa_s"), "dynamic_viscosity_pa_s"
    )
    if viscosity < 0.0:
        raise ValueError("dynamic_viscosity_pa_s must be non-negative")

    eos_raw = raw.get("eos")
    if not isinstance(eos_raw, Mapping):
        raise ValueError("eos must be an object")
    _reject_unknown(eos_raw, _EOS_KEYS, "eos")
    eos = {name: _finite_number(eos_raw.get(name), f"eos.{name}") for name in _EOS_KEYS}
    if eos["initial_internal_energy_density_j_per_m3"] <= 0.0:
        raise ValueError("eos.initial_internal_energy_density_j_per_m3 must be positive")
    if eos["initial_relative_volume"] <= 0.0:
        raise ValueError("eos.initial_relative_volume must be positive")

    normalized = deepcopy(dict(raw))
    normalized["density_kg_per_m3"] = density
    normalized["pressure_cutoff_pa"] = pressure_cutoff
    normalized["dynamic_viscosity_pa_s"] = viscosity
    normalized["eos"] = eos
    normalized["initial_pressure_pa"] = (
        eos["c4"] * eos["initial_internal_energy_density_j_per_m3"]
    )
    return normalized


def _fmt(value: float | int) -> str:
    if isinstance(value, int):
        return str(value)
    return format(value, ".10g")


def render_ale_air_cards(
    raw: Mapping[str, object] | None = None,
    *,
    material_id: int,
    eos_id: int,
) -> list[str]:
    """Render controlled *MAT_NULL and linear-polynomial EOS cards."""

    mid = _positive_id(material_id, "material_id")
    eid = _positive_id(eos_id, "eos_id")
    air = validate_ale_air_definition(
        default_ale_air_definition() if raw is None else raw
    )
    eos = air["eos"]
    coefficients = ",".join(_fmt(eos[f"c{index}"]) for index in range(7))
    return [
        "*MAT_NULL",
        "$#     mid        ro        pc        mu     terod     cerod        ym        pr",
        ",".join(
            _fmt(value)
            for value in (
                mid,
                air["density_kg_per_m3"],
                air["pressure_cutoff_pa"],
                air["dynamic_viscosity_pa_s"],
                0.0,
                0.0,
                0.0,
                0.0,
            )
        ),
        "*EOS_LINEAR_POLYNOMIAL",
        "$#   eosid        c0        c1        c2        c3        c4        c5        c6",
        f"{eid},{coefficients}",
        "$#      e0        v0",
        ",".join(
            _fmt(value)
            for value in (
                eos["initial_internal_energy_density_j_per_m3"],
                eos["initial_relative_volume"],
            )
        ),
    ]


def render_control_ale(raw: Mapping[str, object] | None = None) -> list[str]:
    """Render the reviewed two-card LS-DYNA R12 *CONTROL_ALE preset."""

    values = dict(
        {"dct": -1, "nadv": 1, "meth": 2, "afac": -1.0}
        if raw is None
        else raw
    )
    _reject_unknown(values, {"dct", "nadv", "meth", "afac"}, "CONTROL_ALE")
    expected = {"dct": -1, "nadv": 1, "meth": 2, "afac": -1.0}
    for field, expected_value in expected.items():
        value = _finite_number(values.get(field), f"CONTROL_ALE.{field}")
        if value != expected_value:
            raise ValueError(
                f"CONTROL_ALE.{field} is restricted to {expected_value} for R12"
            )
    return [
        "*CONTROL_ALE",
        "$#     dct      nadv      meth      afac      bfac      cfac      dfac      efac",
        "-1,1,2,-1.0,0.0,0.0,0.0,0.0",
        "$#   start       end     aafac     vfact    vlimit       ebc      pref   nsidebc",
        "0.0,1.0e20,1.0,1.0e-6,0,0,101325.0,0",
    ]


def render_ale_multimaterial_setup(
    *, section_id: int, material_part_ids: Sequence[int]
) -> list[str]:
    """Render ELFORM=11 and groups, refusing an invalid single-material setup."""

    sid = _positive_id(section_id, "section_id")
    if isinstance(material_part_ids, (str, bytes)):
        raise ValueError("material_part_ids must be a sequence of positive integers")
    part_ids = [_positive_id(value, "material_part_ids item") for value in material_part_ids]
    if len(part_ids) < 2:
        raise ValueError("ELFORM=11 requires at least two ALE material groups")
    if len(set(part_ids)) != len(part_ids):
        raise ValueError("material_part_ids must be unique")

    lines = [
        "*SECTION_SOLID",
        "$#   secid    elform",
        f"{sid},11",
        "*ALE_MULTI-MATERIAL_GROUP",
        "$#     sid    idtype",
    ]
    lines.extend(f"{part_id},1" for part_id in part_ids)
    return lines
