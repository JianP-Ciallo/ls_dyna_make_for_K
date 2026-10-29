"""Reviewed SI material presets for solver-complete Phase 18 blast decks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ...phase15_materials import (
    default_phase15_materials,
    render_phase15_material_cards,
)


AIR_MATERIAL_ID = 1
TNT_MATERIAL_ID = 2
CONCRETE_MATERIAL_ID = 3
STEEL_MATERIAL_ID = 4
GLASS_MATERIAL_ID = 5
NONSTRUCTURAL_MATERIAL_ID = 6
SOIL_MATERIAL_ID = 7
ELASTIC_RC_MATERIAL_ID = 8
ALE_VACUUM_MATERIAL_ID = 9
ALE_VACUUM_DENSITY_KG_PER_M3 = 1.225e-5
AIR_EOS_ID = 1
TNT_EOS_ID = 2


@dataclass(frozen=True, slots=True)
class SolverBlastMaterialEvidence:
    role_to_material_id: tuple[tuple[str, int], ...]
    material_ids: tuple[int, ...]
    eos_ids: tuple[int, ...]
    erosion_mode: str
    erosion_maximum_principal_strain: float
    validation_status: str


@dataclass(frozen=True, slots=True)
class MaterialReviewRecord:
    profile: str
    engineering_validated: bool
    requires_project_review: bool
    provenance: str
    assumptions: tuple[str, ...]
    fingerprint: str


def material_review_record(profile: str) -> MaterialReviewRecord:
    """Describe what the selected preset proves without overstating validation."""

    if profile not in {"verification_reference", "project_calibrated"}:
        raise ValueError(
            "material profile must be 'verification_reference' or 'project_calibrated'"
        )
    provenance = (
        "phase15_reference_si_presets"
        if profile == "verification_reference"
        else "project_profile_name_without_signed_calibration_record"
    )
    assumptions = (
        "solver cards are preliminary and require project-specific calibration",
        "no signed laboratory, code-check, or engineer approval record is attached",
    )
    identity = {
        "schema_version": "phase18.solver_blast.material_review@1",
        "profile": profile,
        "engineering_validated": False,
        "requires_project_review": True,
        "provenance": provenance,
        "assumptions": list(assumptions),
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return MaterialReviewRecord(
        profile=profile,
        engineering_validated=False,
        requires_project_review=True,
        provenance=provenance,
        assumptions=assumptions,
        fingerprint=fingerprint,
    )

def render_ale_vacuum_material(material_id: int) -> tuple[str, ...]:
    return (
        "*MAT_ALE_VACUUM_TITLE",
        "Visible coupling buffer vacuum",
        f"{material_id},{ALE_VACUUM_DENSITY_KG_PER_M3:.4g}",
    )


def material_id_for_role(material_role: str) -> int:
    normalized = material_role.strip().lower()
    if (
        "steel" in normalized
        or "rebar" in normalized
        or "reinforc" in normalized
        or normalized in {"metal_roof", "escalator_equipment"}
    ):
        return STEEL_MATERIAL_ID
    if (
        "glass" in normalized
        or "glaz" in normalized
        or normalized == "escalator_balustrade"
    ):
        return GLASS_MATERIAL_ID
    if (
        normalized.startswith("rc_")
        or "_rc_" in normalized
        or normalized.startswith("fixed_stair_")
        or "_landing" in normalized
        or normalized.startswith("upper_landing")
    ):
        return ELASTIC_RC_MATERIAL_ID
    if "concrete" in normalized or "masonry" in normalized or normalized == "rc":
        return CONCRETE_MATERIAL_ID
    return NONSTRUCTURAL_MATERIAL_ID


def render_solver_blast_material_cards(
    material_roles: tuple[str, ...],
) -> tuple[list[str], SolverBlastMaterialEvidence]:
    phase15_materials = default_phase15_materials()
    phase15_materials["erosion"] = {"mode": "standard_observation"}
    phase15_lines, phase15_evidence = render_phase15_material_cards(
        phase15_materials,
        material_ids={
            "air": AIR_MATERIAL_ID,
            "tnt": TNT_MATERIAL_ID,
            "concrete": CONCRETE_MATERIAL_ID,
            "steel_hoop": STEEL_MATERIAL_ID,
        },
        eos_ids={"air": AIR_EOS_ID, "tnt": TNT_EOS_ID},
    )
    lines = list(phase15_lines)
    lines.extend(render_ale_vacuum_material(ALE_VACUUM_MATERIAL_ID))
    lines.extend(
        [
            "*DEFINE_CURVE_TITLE",
            "K&C seconds-based strain-rate scale",
            "$#    lcid      sidr       sfa       sfo      offa      offo    dattyp     lcint",
            "1,0,1,1,0,0,0,0",
            "$#                a1                  o1",
            "0,1",
            "1000000,1",
            "*MAT_ELASTIC_TITLE",
            "Architectural glass preliminary elastic preset",
            "$#   mid        ro         e        pr",
            f"{GLASS_MATERIAL_ID},2500,7.0e10,0.22",
            "*MAT_ELASTIC_TITLE",
            "Nonstructural preliminary elastic preset",
            "$#   mid        ro         e        pr",
            f"{NONSTRUCTURAL_MATERIAL_ID},1200,5.0e9,0.25",
            "*MAT_ELASTIC_TITLE",
            "Diagnostic soil preliminary elastic preset",
            "$#   mid        ro         e        pr",
            f"{SOIL_MATERIAL_ID},1900,1.0e8,0.30",
            "*MAT_ELASTIC_TITLE",
            "Reinforced concrete preliminary elastic SI preset",
            "$#   mid        ro         e        pr",
            f"{ELASTIC_RC_MATERIAL_ID},2400,3.0e10,0.20",
        ]
    )
    role_to_material = tuple(
        (role, material_id_for_role(role)) for role in sorted(set(material_roles))
    )
    return lines, SolverBlastMaterialEvidence(
        role_to_material_id=role_to_material,
        material_ids=tuple(range(AIR_MATERIAL_ID, ALE_VACUUM_MATERIAL_ID + 1)),
        eos_ids=(AIR_EOS_ID, TNT_EOS_ID),
        erosion_mode=str(phase15_evidence["erosion"]["mode"]),
        erosion_maximum_principal_strain=float(
            phase15_evidence["erosion"]["maximum_principal_strain"]
        ),
        validation_status=(
            "review_required_preliminary_si_presets_with_standard_concrete_erosion_and_elastic_rc"
        ),
    )
