from __future__ import annotations

from collections.abc import Iterable

from .config import JSONDict


CAPABILITY_REQUIRED_CARDS: dict[str, tuple[str, ...]] = {
    "mm_ale": (
        "*CONTROL_ALE",
        "*ALE_MULTI-MATERIAL_GROUP",
        "*MAT_NULL",
        "*EOS_LINEAR_POLYNOMIAL",
    ),
    "mm_ale_3d": (
        "*ELEMENT_SOLID",
        "*SECTION_SOLID",
    ),
    "high_explosive_jwl": (
        "*MAT_HIGH_EXPLOSIVE_BURN",
        "*EOS_JWL",
        "*INITIAL_VOLUME_FRACTION_GEOMETRY",
        "*INITIAL_DETONATION",
    ),
    "lagrangian_shell_structure": (
        "*ELEMENT_SHELL",
        "*SECTION_SHELL",
    ),
    "ale_fsi": (
        "*SET_PART_LIST",
        "*CONSTRAINED_LAGRANGE_IN_SOLID",
        "*DATABASE_FSI",
    ),
    "fsi_segment_interface": ("*SET_SEGMENT",),
    "conforming_ale_lagrange_interface": ("*ALE_SMOOTHING",),
    "ale_nonreflecting_3d": ("*BOUNDARY_NON_REFLECTING",),
    "ale_nonreflecting_2d": ("*BOUNDARY_NON_REFLECTING_2D",),
    "ale_pressure_outputs": (
        "*DATABASE_ALE_MAT",
        "*DATABASE_ALE",
    ),
    "ale_pressure_outputs_r12_safe": ("*DATABASE_ALE_MAT",),
    "kc_concrete": (
        "*MAT_CONCRETE_DAMAGE_REL3",
        "*DATABASE_HISTORY_SHELL_SET",
        "*DATABASE_HISTORY_NODE_SET",
    ),
    "element_erosion": ("*MAT_ADD_EROSION",),
    "city_ground_crater_v1": (
        "*ELEMENT_SOLID",
        "*MAT_CONCRETE_DAMAGE_REL3",
        "*MAT_ADD_EROSION",
        "*DATABASE_EXTENT_BINARY",
        "*DATABASE_HISTORY_SOLID_SET",
        "*CONTACT_TIED_NODES_TO_SURFACE",
    ),
    "steel_plasticity": (),
    "movable_surface_contact": ("*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE",),
    "axisymmetric_ale": ("*SECTION_ALE2D",),
}

CAPABILITY_REQUIRED_CARD_GROUPS: dict[str, tuple[tuple[str, ...], ...]] = {
    "steel_plasticity": (
        (
            "*MAT_PLASTIC_KINEMATIC",
            "*MAT_PIECEWISE_LINEAR_PLASTICITY",
        ),
    ),
}


MODEL_TYPE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "ale_blast_scene": (
        "mm_ale",
        "mm_ale_3d",
        "high_explosive_jwl",
        "lagrangian_shell_structure",
        "ale_fsi",
        "ale_nonreflecting_3d",
        "ale_pressure_outputs",
        "steel_plasticity",
    ),
    "city_street_blast_scene": (
        "mm_ale",
        "mm_ale_3d",
        "high_explosive_jwl",
        "lagrangian_shell_structure",
        "ale_fsi",
        "fsi_segment_interface",
        "ale_nonreflecting_3d",
        "ale_pressure_outputs_r12_safe",
        "steel_plasticity",
        "movable_surface_contact",
    ),
    "phase15_axisymmetric_blast": (
        "mm_ale",
        "high_explosive_jwl",
        "lagrangian_shell_structure",
        "ale_fsi",
        "fsi_segment_interface",
        "ale_nonreflecting_2d",
        "kc_concrete",
        "steel_plasticity",
        "axisymmetric_ale",
    ),
}


def validation_capabilities(
    spec: JSONDict,
    metadata: JSONDict,
) -> tuple[str, ...]:
    declared = metadata.get("validation_capabilities")
    if isinstance(declared, list):
        values = _normalized_capabilities(declared)
        if values:
            return values
    model_type = str(
        spec.get("model_type")
        or metadata.get("model_type")
        or ""
    )
    return tuple(sorted(MODEL_TYPE_CAPABILITIES.get(model_type, ())))


def required_cards_for_capabilities(capabilities: Iterable[str]) -> tuple[str, ...]:
    cards: set[str] = set()
    for capability in capabilities:
        try:
            cards.update(CAPABILITY_REQUIRED_CARDS[capability])
        except KeyError as exc:
            raise ValueError(f"unknown validation capability: {capability}") from exc
    return tuple(sorted(cards))


def required_card_groups_for_capabilities(
    capabilities: Iterable[str],
) -> tuple[tuple[str, ...], ...]:
    groups: set[tuple[str, ...]] = set()
    for capability in capabilities:
        if capability not in CAPABILITY_REQUIRED_CARDS:
            raise ValueError(f"unknown validation capability: {capability}")
        groups.update(CAPABILITY_REQUIRED_CARD_GROUPS.get(capability, ()))
    return tuple(sorted(groups))


def _normalized_capabilities(values: Iterable[object]) -> tuple[str, ...]:
    result: set[str] = set()
    for value in values:
        name = str(value).strip()
        if not name:
            continue
        if name not in CAPABILITY_REQUIRED_CARDS:
            raise ValueError(f"unknown validation capability: {name}")
        result.add(name)
    return tuple(sorted(result))
