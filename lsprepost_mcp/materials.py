from __future__ import annotations

from collections.abc import Mapping
import math
from pathlib import Path

from .config import DEFAULT_UNIT_SYSTEM, JSONDict, MATERIALS_DIR
from .io import read_json
from .phase18_reference_naming import MATERIAL_RESOURCE_ALIASES
from .phase18_resource_review import (
    SOURCE_2K_SHA256,
    apply_effective_review,
    canonical_resource_sha256,
    load_phase18_review_manifest,
)
from .resource_aliases import build_alias_index, normalize_resource_identity, resolve_resource_id


MATERIAL_NUMERIC_KEYS = ["density_kg_per_m3", "youngs_pa", "poisson"]
OPTIONAL_NUMERIC_KEYS = ["yield_strength_pa"]
PIECEWISE_LINEAR_KEYS = ["yield_strength_pa", "tangent_modulus_pa"]


def _material_files(root: Path = MATERIALS_DIR) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob("*.json"), key=lambda item: str(item).lower())


def load_materials(root: Path = MATERIALS_DIR) -> dict[str, JSONDict]:
    materials: dict[str, JSONDict] = {}
    for path in _material_files(root):
        data = read_json(path)
        raw_id = str(data.get("id") or data.get("name") or path.stem)
        normalized = normalize_resource_identity(data, raw_id, MATERIAL_RESOURCE_ALIASES, "material")
        material_id = str(normalized["id"])
        if material_id in materials:
            previous = materials[material_id]["_path"]
            raise ValueError(
                f"duplicate material resource id '{material_id}' in '{previous}' and '{path}'"
            )
        normalized.setdefault("name", material_id)
        relative = path.relative_to(root)
        normalized.setdefault("library_section", relative.parts[0] if len(relative.parts) > 1 else "legacy_flat")
        normalized["_path"] = str(path)
        materials[material_id] = normalized
    build_alias_index(materials, "material")
    return materials


def list_materials() -> list[JSONDict]:
    rows = []
    for material in load_materials().values():
        provenance = material.get("provenance")
        if isinstance(provenance, Mapping) and provenance.get("source_sha256") == SOURCE_2K_SHA256:
            public = apply_effective_review(material, expected_resource_kind="material")
        else:
            public = {**material, "effective_validation_status": material.get("validation_status", "demo")}
        rows.append(
            {
                "id": public["id"],
                "name": public.get("name", public["id"]),
                "display_name": public.get("display_name", public["id"]),
                "category": public.get("category", "unknown"),
                "type": public.get("type", "unknown"),
                "unit_system": public.get("unit_system", "unknown"),
                "density_kg_per_m3": public.get("density_kg_per_m3"),
                "youngs_pa": public.get("youngs_pa"),
                "poisson": public.get("poisson"),
                "yield_strength_pa": public.get("yield_strength_pa"),
                "tangent_modulus_pa": public.get("tangent_modulus_pa"),
                "validation_status": public.get("validation_status", "demo"),
                "effective_validation_status": public.get("effective_validation_status"),
                "library_section": public.get("library_section", "legacy_flat"),
                "source": public.get("source", ""),
                "version": public.get("version", "unknown"),
                "requires_project_review": bool(public.get("requires_project_review", True)),
            }
        )
    return rows


def get_material(material_id: str) -> JSONDict:
    key = str(material_id).strip()
    if not key:
        raise ValueError("material_id is required")
    materials = load_materials()
    try:
        _, resolved = resolve_resource_id(key, materials, "material")
    except ValueError as exc:
        raise ValueError(str(exc).replace("unknown material resource", "unknown material")) from exc
    material = dict(resolved)
    material.pop("_path", None)
    provenance = material.get("provenance")
    if isinstance(provenance, Mapping) and provenance.get("source_sha256") == SOURCE_2K_SHA256:
        return apply_effective_review(material, expected_resource_kind="material")
    material["effective_validation_status"] = material.get("validation_status", "demo")
    return material


def resolve_material(material: JSONDict) -> JSONDict:
    raw = dict(material)
    name = str(raw.get("name", "mild_steel")).strip() or "mild_steel"
    materials = load_materials()
    if name in materials:
        resolved = material_from_library(materials[name], raw)
    else:
        resolved = material_from_confirmed_custom(raw, name)
    validate_material(resolved)
    return resolved


def material_from_library(library_material: JSONDict, overrides: JSONDict) -> JSONDict:
    if library_material.get("type") == "source_keyword_bundle":
        raise ValueError("source keyword bundles require their dedicated reconstruction compiler")
    resolved = {
        "name": library_material["id"],
        "display_name": library_material.get("display_name", library_material["id"]),
        "type": library_material.get("type", "elastic"),
        "density_kg_per_m3": float(library_material["density_kg_per_m3"]),
        "youngs_pa": float(library_material["youngs_pa"]),
        "poisson": float(library_material["poisson"]),
        "unit_system": library_material.get("unit_system", DEFAULT_UNIT_SYSTEM),
        "source": library_material.get("source", ""),
        "source_url": library_material.get("source_url", ""),
        "version": library_material.get("version", "unknown"),
        "library_id": library_material["id"],
        "source_type": "material_library",
        "requires_project_review": bool(library_material.get("requires_project_review", True)),
        "validation_status": library_material.get("validation_status", "demo"),
        "notes": library_material.get("notes", ""),
    }
    for key in ["yield_strength_pa", "tangent_modulus_pa"]:
        if library_material.get(key) is not None:
            resolved[key] = float(library_material[key])
    for key in ["display_name"]:
        if key in overrides:
            resolved[key] = overrides[key]
    return resolved


def material_from_confirmed_custom(raw: JSONDict, name: str) -> JSONDict:
    if raw.get("confirmed_by_user") is not True:
        raise ValueError(
            f"unknown material '{name}'. Use list_materials/get_material, or provide confirmed_by_user=true with full custom material parameters and source."
        )
    missing = [key for key in MATERIAL_NUMERIC_KEYS if key not in raw]
    if missing:
        raise ValueError(f"custom material '{name}' is missing required fields: {', '.join(missing)}")
    if not str(raw.get("source", "")).strip():
        raise ValueError(f"custom material '{name}' must include material.source")
    resolved = dict(raw)
    resolved["name"] = name
    resolved.setdefault("type", "elastic")
    resolved.setdefault("unit_system", DEFAULT_UNIT_SYSTEM)
    resolved.setdefault("version", "user-confirmed")
    resolved["source_type"] = "user_confirmed_custom"
    resolved["requires_project_review"] = True
    return resolved


def validate_material(material: JSONDict) -> None:
    if material.get("unit_system") != DEFAULT_UNIT_SYSTEM:
        raise ValueError(f"material.unit_system must be '{DEFAULT_UNIT_SYSTEM}'")
    material_type = str(material.get("type", "elastic"))
    if material_type not in {"elastic", "piecewise_linear_plasticity"}:
        raise ValueError("material.type must be elastic or piecewise_linear_plasticity")
    for key in ["density_kg_per_m3", "youngs_pa"]:
        if float(material.get(key, 0)) <= 0:
            raise ValueError(f"material.{key} must be positive")
    poisson = float(material.get("poisson", 0))
    if not 0.0 < poisson < 0.5:
        raise ValueError("material.poisson must be between 0 and 0.5")
    if "yield_strength_pa" in material and material["yield_strength_pa"] is not None:
        if float(material["yield_strength_pa"]) <= 0:
            raise ValueError("material.yield_strength_pa must be positive when provided")
    if material_type == "piecewise_linear_plasticity":
        for key in PIECEWISE_LINEAR_KEYS:
            if float(material.get(key, 0)) <= 0:
                raise ValueError(f"material.{key} must be positive for piecewise_linear_plasticity")


def _resource_mapping(resource: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = resource.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"material resource '{resource.get('id')}' requires {key}")
    return value


def _finite_number(
    values: Mapping[str, object],
    key: str,
    *,
    positive: bool = False,
) -> float:
    try:
        value = float(values[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"material resource field '{key}' must be numeric") from exc
    if not math.isfinite(value):
        raise ValueError(f"material resource field '{key}' must be finite")
    if positive and value <= 0:
        raise ValueError(f"material resource field '{key}' must be positive")
    return value


def _source_keywords(resource: Mapping[str, object]) -> set[str]:
    cards = resource.get("source_cards")
    if not isinstance(cards, list) or not cards:
        raise ValueError(f"material resource '{resource.get('id')}' requires source_cards")
    keywords: set[str] = set()
    for card in cards:
        if not isinstance(card, Mapping):
            raise ValueError("material source card must be an object")
        keyword = str(card.get("keyword", "")).strip().upper()
        if not keyword:
            raise ValueError("material source card keyword is required")
        _finite_number(card, "source_id")
        line_start = _finite_number(card, "line_start", positive=True)
        line_end = _finite_number(card, "line_end", positive=True)
        if line_end < line_start:
            raise ValueError("material source card line_end must not precede line_start")
        keywords.add(keyword)
    return keywords


def _validate_common_resource_fields(resource: Mapping[str, object]) -> None:
    resource_id = str(resource.get("id", "")).strip()
    if not resource_id:
        raise ValueError("material resource id is required")
    if resource.get("unit_system") != DEFAULT_UNIT_SYSTEM:
        raise ValueError(f"material resource unit_system must be '{DEFAULT_UNIT_SYSTEM}'")
    if resource.get("validation_status") != "source_reference":
        raise ValueError("raw Phase 18 material validation_status must be source_reference")
    if resource.get("requires_project_review") is not True:
        raise ValueError("Phase 18 material requires_project_review must be true")
    provenance = _resource_mapping(resource, "provenance")
    if provenance.get("source_sha256") != SOURCE_2K_SHA256:
        raise ValueError("material resource source SHA-256 does not match the accepted 2.k source")
    if provenance.get("source_unit_system") != "tonne_mm_s_N_MPa":
        raise ValueError("material resource source_unit_system must be tonne_mm_s_N_MPa")
    _finite_number(resource, "density_kg_per_m3", positive=True)
    _source_keywords(resource)


def _validate_concrete_damage_rel3(resource: Mapping[str, object]) -> None:
    if _finite_number(resource, "density_kg_per_m3", positive=True) != 2400.0:
        raise ValueError("concrete density_kg_per_m3 must preserve source value 2400")
    poisson = _finite_number(resource, "poisson", positive=True)
    if poisson >= 0.5:
        raise ValueError("concrete poisson must be below 0.5")
    parameters = _resource_mapping(resource, "parameters_si")
    for key in ("a0_pa", "a1", "a2", "b1", "b2", "omega"):
        _finite_number(parameters, key)
    dependencies = _resource_mapping(resource, "dependencies")
    rate_curve = _resource_mapping(dependencies, "rate_curve")
    if int(_finite_number(rate_curve, "lcid")) != 1 or int(_finite_number(rate_curve, "point_count")) != 23:
        raise ValueError("concrete rate_curve must reference Curve 1 with 23 points")
    erosion = _resource_mapping(dependencies, "mat_add_erosion")
    if int(_finite_number(erosion, "mid")) != 5 or _finite_number(erosion, "mxeps") != 0.15:
        raise ValueError("concrete mat_add_erosion must preserve MID 5 and mxeps 0.15")
    semantics = _resource_mapping(resource, "solver_semantics")
    ft = _resource_mapping(semantics, "ft")
    if _finite_number(ft, "source_value") != 0.0 or not str(ft.get("meaning", "")).strip():
        raise ValueError("concrete ft sentinel semantics are incomplete")
    conversion = _resource_mapping(resource, "solver_unit_conversion")
    _finite_number(conversion, "rsize_in_per_user_length_unit", positive=True)
    _finite_number(conversion, "ucf_psi_per_user_stress_unit", positive=True)
    keywords = _source_keywords(resource)
    required = {"*MAT_CONCRETE_DAMAGE_REL3_TITLE", "*MAT_ADD_EROSION", "*DEFINE_CURVE"}
    if not required.issubset(keywords):
        raise ValueError("concrete source_cards must include MAT, erosion and rate curve")


def _validate_plastic_kinematic(resource: Mapping[str, object]) -> None:
    for key in ("youngs_pa", "yield_strength_pa", "tangent_modulus_pa"):
        _finite_number(resource, key, positive=True)
    poisson = _finite_number(resource, "poisson", positive=True)
    if poisson >= 0.5:
        raise ValueError("rebar poisson must be below 0.5")
    parameters = _resource_mapping(resource, "parameters_si")
    _finite_number(parameters, "src_per_s", positive=True)
    _finite_number(parameters, "srp", positive=True)
    diameters = resource.get("section_diameters_mm")
    if not isinstance(diameters, list) or not diameters:
        raise ValueError("rebar section_diameters_mm must be a non-empty list")
    if any(not math.isfinite(float(value)) or float(value) <= 0 for value in diameters):
        raise ValueError("rebar section diameters must be finite and positive")
    keywords = _source_keywords(resource)
    if "*MAT_PLASTIC_KINEMATIC_TITLE" not in keywords or "*SECTION_BEAM_TITLE" not in keywords:
        raise ValueError("rebar source_cards must include MAT and beam section cards")


def _validate_air_eos(resource: Mapping[str, object]) -> None:
    parameters = _resource_mapping(resource, "parameters_si")
    _finite_number(parameters, "pressure_cutoff_pa")
    _finite_number(parameters, "dynamic_viscosity_pa_s")
    eos = _resource_mapping(resource, "eos_si")
    if int(_finite_number(eos, "eos_id")) != 2:
        raise ValueError("air EOS must preserve EOS ID 2")
    for key in ("c0_pa", "c1_pa", "c2_pa", "c3_pa", "c4", "c5", "c6", "e0_j_per_m3", "v0_solver_semantic"):
        _finite_number(eos, key)
    keywords = _source_keywords(resource)
    if {"*MAT_NULL_TITLE", "*EOS_LINEAR_POLYNOMIAL_TITLE"} - keywords:
        raise ValueError("air source_cards must include MAT_NULL and linear polynomial EOS")


def _validate_tnt_jwl(resource: Mapping[str, object]) -> None:
    parameters = _resource_mapping(resource, "parameters_si")
    _finite_number(parameters, "detonation_velocity_m_per_s", positive=True)
    _finite_number(parameters, "cj_pressure_pa", positive=True)
    eos = _resource_mapping(resource, "eos_si")
    if int(_finite_number(eos, "eos_id")) != 1:
        raise ValueError("TNT EOS must preserve EOS ID 1")
    for key in ("a_pa", "b_pa", "r1", "r2", "omega", "e0_j_per_m3", "v0"):
        _finite_number(eos, key, positive=True)
    dependencies = _resource_mapping(resource, "dependencies")
    detonation = _resource_mapping(dependencies, "initial_detonation")
    if int(_finite_number(detonation, "pid")) != 1002:
        raise ValueError("TNT initial_detonation must reference source PID 1002")
    xyz = detonation.get("xyz_m")
    if not isinstance(xyz, list) or len(xyz) != 3 or any(not math.isfinite(float(value)) for value in xyz):
        raise ValueError("TNT initial_detonation xyz_m must contain three finite values")
    _finite_number(detonation, "time_s")
    keywords = _source_keywords(resource)
    required = {"*MAT_HIGH_EXPLOSIVE_BURN_TITLE", "*EOS_JWL_TITLE", "*INITIAL_DETONATION"}
    if not required.issubset(keywords):
        raise ValueError("TNT source_cards must include MAT, JWL EOS and detonation cards")


_RESOURCE_VALIDATORS = {
    "concrete_damage_rel3": _validate_concrete_damage_rel3,
    "plastic_kinematic": _validate_plastic_kinematic,
    "mat_null_eos_linear_polynomial": _validate_air_eos,
    "high_explosive_burn_eos_jwl": _validate_tnt_jwl,
}


def validate_material_resource(material: Mapping[str, object]) -> JSONDict:
    if material.get("type") == "source_keyword_bundle":
        from .source_rebuild_resources import validate_resource
        return validate_resource(material)
    material_type = str(material.get("type", "")).strip()
    try:
        validate_family = _RESOURCE_VALIDATORS[material_type]
    except KeyError as exc:
        raise ValueError(f"unsupported material resource type '{material_type}'") from exc
    _validate_common_resource_fields(material)
    validate_family(material)
    provenance = _resource_mapping(material, "provenance")
    return {
        "valid": True,
        "resource_id": str(material["id"]),
        "material_type": material_type,
        "source_sha256": str(provenance["source_sha256"]),
        "canonical_sha256": canonical_resource_sha256(material),
    }


def get_reviewed_material_resource(
    material_id: str,
    allowed_types: set[str],
    *,
    review_manifest: Mapping[str, object] | None = None,
) -> JSONDict:
    resource = get_material(material_id)
    report = validate_material_resource(resource)
    evidence = review_manifest if review_manifest is not None else load_phase18_review_manifest()
    reviewed = apply_effective_review(resource, evidence, expected_resource_kind="material")
    if reviewed["effective_validation_status"] != "syntax_unit_reviewed":
        raise ValueError(f"material resource '{material_id}' is not syntax_unit_reviewed")
    if report["material_type"] not in allowed_types:
        raise ValueError(f"material resource '{material_id}' is not an allowed material type")
    return reviewed
