from __future__ import annotations

from copy import deepcopy
import math

from .ale import default_ale_air_definition, render_ale_air_cards
from .config import JSONDict


EROSION_PRESETS = {
    "off": None,
    "delayed": 0.10,
    "standard_observation": 0.05,
    "early_sensitivity": 0.03,
}


def default_phase15_materials() -> JSONDict:
    return {
        "air": default_ale_air_definition(),
        "tnt": {
            "preset_id": "tnt_jwl_phase15_reference",
            "density_kg_per_m3": 1630.0,
            "detonation_velocity_m_per_s": 6930.0,
            "chapman_jouget_pressure_pa": 21.0e9,
            "beta": 0.0,
            "jwl": {
                "a_pa": 371.2e9,
                "b_pa": 3.231e9,
                "r1": 4.15,
                "r2": 0.95,
                "omega": 0.30,
                "initial_internal_energy_density_j_per_m3": 7.0e9,
                "initial_relative_volume": 1.0,
            },
            "source": "Phase 15 controlled TNT/JWL reference preset",
            "validation_status": "reference_unvalidated_for_specific_batch",
        },
        "concrete": {
            "preset_id": "kc_a1_automatic_reference",
            "type": "concrete_damage_rel3",
            "parameter_mode": "automatic",
            "tensile_mode": "automatic",
            "density_kg_per_m3": 2480.0,
            "poisson": 0.20,
            "fpc_pa": 133.5e6,
            "rsize_in_per_user_length": 39.37,
            "ucf_psi_per_user_stress": 1.4503773773e-4,
            "lcrate": -1,
            "nout": 2,
            "source": "Phase 15 A-1 source and LS-DYNA R12 automatic K&C generation",
            "validation_status": "automatic_reference_not_cf120_calibration",
        },
        "steel_hoop": {
            "preset_id": "steel_hoop_elastoplastic_reference",
            "density_kg_per_m3": 7850.0,
            "youngs_pa": 210.0e9,
            "poisson": 0.30,
            "yield_strength_pa": 210.0e6,
            "tangent_modulus_pa": 1.0e9,
            "beta": 0.0,
            "source": "Phase 15 controlled ideal elastoplastic steel hoop reference",
            "validation_status": "reference_unvalidated_for_specific_steel",
        },
        "erosion": {"mode": "off"},
    }


def validate_phase15_materials(raw: JSONDict) -> JSONDict:
    if not isinstance(raw, dict):
        raise ValueError("Phase 15 materials must be an object")
    required = {"air", "tnt", "concrete", "steel_hoop", "erosion"}
    if set(raw) != required:
        raise ValueError("Phase 15 materials must contain exactly air, tnt, concrete, steel_hoop, erosion")
    result = deepcopy(raw)
    tnt = _object(result["tnt"], "tnt")
    concrete = _object(result["concrete"], "concrete")
    steel = _object(result["steel_hoop"], "steel_hoop")
    erosion = _object(result["erosion"], "erosion")

    _range(tnt, "density_kg_per_m3", 1550.0, 1650.0, "tnt")
    _range(tnt, "detonation_velocity_m_per_s", 6800.0, 7000.0, "tnt")
    _range(tnt, "chapman_jouget_pressure_pa", 19.0e9, 22.0e9, "tnt")
    jwl = _object(tnt.get("jwl"), "tnt.jwl")
    locked_jwl = {
        "a_pa": 371.2e9,
        "b_pa": 3.231e9,
        "r1": 4.15,
        "r2": 0.95,
        "omega": 0.30,
        "initial_relative_volume": 1.0,
    }
    for field, expected in locked_jwl.items():
        value = _finite(jwl.get(field), f"tnt.jwl.{field}")
        if not math.isclose(value, expected, rel_tol=1.0e-12, abs_tol=0.0):
            raise ValueError(f"tnt.jwl.{field} is locked by the controlled preset")
    _range(jwl, "initial_internal_energy_density_j_per_m3", 6.0e9, 7.5e9, "tnt.jwl")

    if concrete.get("parameter_mode") != "automatic":
        raise ValueError("concrete.parameter_mode must remain automatic in Phase 15")
    _range(concrete, "density_kg_per_m3", 2300.0, 2600.0, "concrete")
    _range(concrete, "fpc_pa", 120.0e6, 160.0e6, "concrete")
    _range(concrete, "poisson", 0.10, 0.30, "concrete")
    tensile_mode = str(concrete.get("tensile_mode", "automatic"))
    if tensile_mode not in {"automatic", "user_specified"}:
        raise ValueError("concrete.tensile_mode must be automatic or user_specified")
    if tensile_mode == "user_specified":
        _range(concrete, "ft_pa", 5.0e6, 10.0e6, "concrete")
        if concrete.get("confirmed_by_user") is not True:
            raise ValueError("concrete user-specified tensile strength requires confirmed_by_user=true")
        concrete["validation_status"] = "user_confirmed_unvalidated"
    elif "ft_pa" in concrete:
        raise ValueError("concrete.ft_pa is disabled while tensile_mode is automatic")
    if concrete.get("nout") != 2:
        raise ValueError("concrete.nout must be 2 for scaled damage output")
    for field, expected in {
        "rsize_in_per_user_length": 39.37,
        "ucf_psi_per_user_stress": 1.4503773773e-4,
    }.items():
        value = _finite(concrete.get(field), f"concrete.{field}")
        if not math.isclose(value, expected, rel_tol=1.0e-10, abs_tol=0.0):
            raise ValueError(f"concrete.{field} must match the R12 SI conversion preset")
    if int(concrete.get("lcrate", 0)) != -1:
        raise ValueError("concrete.lcrate must be -1 for seconds-based rate curves")

    _range(steel, "density_kg_per_m3", 7750.0, 8050.0, "steel_hoop")
    _range(steel, "youngs_pa", 195.0e9, 210.0e9, "steel_hoop")
    _range(steel, "poisson", 0.27, 0.30, "steel_hoop")
    _range(steel, "yield_strength_pa", 200.0e6, 355.0e6, "steel_hoop")
    _positive(steel, "tangent_modulus_pa", "steel_hoop")

    mode = str(erosion.get("mode", "off"))
    if mode in EROSION_PRESETS:
        erosion["maximum_principal_strain"] = EROSION_PRESETS[mode]
    elif mode == "custom":
        _range(erosion, "maximum_principal_strain", 0.02, 0.15, "erosion")
        if erosion.get("confirmed_by_user") is not True:
            raise ValueError("custom erosion requires confirmed_by_user=true")
    else:
        raise ValueError("erosion.mode is unsupported")
    erosion["interpretation"] = "numerical_element_deletion_only"
    return result


def render_phase15_material_cards(
    raw: JSONDict,
    *,
    material_ids: dict[str, int] | None = None,
    eos_ids: dict[str, int] | None = None,
) -> tuple[list[str], JSONDict]:
    materials = validate_phase15_materials(raw)
    resolved_material_ids = _id_mapping(
        material_ids,
        {"air": 1, "tnt": 2, "concrete": 3, "steel_hoop": 4},
        "material_ids",
    )
    resolved_eos_ids = _id_mapping(
        eos_ids,
        {"air": 1, "tnt": 2},
        "eos_ids",
    )
    lines = render_ale_air_cards(
        materials["air"],
        material_id=resolved_material_ids["air"],
        eos_id=resolved_eos_ids["air"],
    )
    tnt = materials["tnt"]
    jwl = tnt["jwl"]
    lines.extend(
        [
            "*MAT_HIGH_EXPLOSIVE_BURN",
            "$#   mid        ro         d       pcj      beta",
            _join(resolved_material_ids["tnt"], tnt["density_kg_per_m3"], tnt["detonation_velocity_m_per_s"], tnt["chapman_jouget_pressure_pa"], tnt.get("beta", 0.0)),
            "*EOS_JWL",
            "$# eosid         a         b        r1        r2     omega        e0        v0",
            _join(resolved_eos_ids["tnt"], jwl["a_pa"], jwl["b_pa"], jwl["r1"], jwl["r2"], jwl["omega"], jwl["initial_internal_energy_density_j_per_m3"], jwl["initial_relative_volume"]),
        ]
    )
    concrete = materials["concrete"]
    ft = concrete.get("ft_pa", "") if concrete.get("tensile_mode") == "user_specified" else ""
    card2 = [ft, -float(concrete["fpc_pa"]), "", "", "", "", ""]
    card3 = [
        "",
        concrete["nout"],
        "",
        concrete["rsize_in_per_user_length"],
        concrete["ucf_psi_per_user_stress"],
        concrete["lcrate"],
        "",
        "",
    ]
    blank = ",".join([""] * 8)
    lines.extend(
        [
            "*MAT_CONCRETE_DAMAGE_REL3",
            "$#   mid        ro        pr",
            _join(resolved_material_ids["concrete"], concrete["density_kg_per_m3"], concrete["poisson"]),
            "$#    ft        a0        a1        a2        b1     omega       a1f",
            _join(*card2),
            "$# slambda      nout     edrop     rsize       ucf    lcrate    locwid      npts",
            _join(*card3),
            "$# lambda01 lambda02 lambda03 lambda04 lambda05 lambda06 lambda07 lambda08",
            blank,
            "$# lambda09 lambda10 lambda11 lambda12 lambda13       b3      a0y      a1y",
            blank,
            "$# eta01    eta02    eta03    eta04    eta05    eta06    eta07    eta08",
            blank,
            "$# eta09    eta10    eta11    eta12    eta13       b2      a2f      a2y",
            blank,
        ]
    )
    steel = materials["steel_hoop"]
    lines.extend(
        [
            "*MAT_PLASTIC_KINEMATIC",
            "$#   mid        ro         e        pr      sigy      etan      beta",
            _join(resolved_material_ids["steel_hoop"], steel["density_kg_per_m3"], steel["youngs_pa"], steel["poisson"], steel["yield_strength_pa"], steel["tangent_modulus_pa"], steel.get("beta", 0.0)),
            "$#    src       srp        fs        vp",
            "0,0,1,0",
        ]
    )
    erosion = materials["erosion"]
    if erosion["mode"] != "off":
        lines.extend(
            [
                "*MAT_ADD_EROSION",
                "$#   mid      excl    mxpres     mneps    effeps    voleps    numfip       ncs",
                f"{resolved_material_ids['concrete']},0,0,0,0,0,1,1",
                "$# mnpres     sigp1     sigvm     mxeps     epssh     sigth   impulse    failtm",
                _join(0, 0, 0, erosion["maximum_principal_strain"], 0, 0, 0, 0),
            ]
        )
    metadata = {
        "material_ids": dict(resolved_material_ids),
        "eos_ids": dict(resolved_eos_ids),
        "presets": {name: value.get("preset_id") for name, value in materials.items() if isinstance(value, dict)},
        "erosion": deepcopy(erosion),
        "kc_interpretation": "automatic_reference_not_cf120_calibration",
        "kc_output": {
            "nout": 2,
            "elout_field": "plastic_strain",
            "interpretation": "scaled_damage_measure",
        },
    }
    return lines, metadata


def _id_mapping(
    value: dict[str, int] | None,
    defaults: dict[str, int],
    field: str,
) -> dict[str, int]:
    if value is None:
        return dict(defaults)
    if not isinstance(value, dict) or set(value) != set(defaults):
        raise ValueError(
            f"{field} must contain exactly " + ", ".join(defaults)
        )
    resolved: dict[str, int] = {}
    for name, identifier in value.items():
        if (
            isinstance(identifier, bool)
            or not isinstance(identifier, int)
            or identifier <= 0
        ):
            raise ValueError(f"{field}.{name} must be a positive integer")
        resolved[name] = identifier
    if len(set(resolved.values())) != len(resolved):
        raise ValueError(f"{field} values must be unique")
    return resolved


def _object(value: object, field: str) -> JSONDict:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number")
    return result


def _range(raw: JSONDict, field: str, minimum: float, maximum: float, prefix: str) -> float:
    value = _finite(raw.get(field), f"{prefix}.{field}")
    if not minimum <= value <= maximum:
        raise ValueError(f"{prefix}.{field} must be between {minimum:g} and {maximum:g}")
    raw[field] = value
    return value


def _positive(raw: JSONDict, field: str, prefix: str) -> float:
    value = _finite(raw.get(field), f"{prefix}.{field}")
    if value <= 0.0:
        raise ValueError(f"{prefix}.{field} must be positive")
    raw[field] = value
    return value


def _join(*values: object) -> str:
    return ",".join(
        "" if value == "" else _r12_field(value) if isinstance(value, (int, float)) else str(value)
        for value in values
    )


def _r12_field(value: object) -> str:
    number = float(value)
    for precision in range(9, 0, -1):
        candidate = f"{number:.{precision}g}"
        if len(candidate) <= 10:
            return candidate
    raise ValueError(f"cannot format LS-DYNA R12 numeric field: {value!r}")
