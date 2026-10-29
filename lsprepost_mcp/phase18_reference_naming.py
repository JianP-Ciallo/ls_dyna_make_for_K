from __future__ import annotations


REFERENCE_FAMILY_ID = "two_storey_rc_frame_blast_reference"
REFERENCE_DISPLAY_NAME_EN = "Two-Storey Reinforced Concrete Frame Blast Reference Model"
REFERENCE_DISPLAY_NAME_ZH = "双层钢筋混凝土框架爆炸参考模型"
LEGACY_SOURCE_FILENAME = "2.k"

MODEL_RESOURCE_ALIASES = {
    "2k_complete_reference": REFERENCE_FAMILY_ID,
    "2k_rc_beam_reference": "two_storey_rc_frame_beam_reference",
    "2k_rc_column_reference": "two_storey_rc_frame_column_reference",
    "2k_rc_slab_reference": "two_storey_rc_frame_slab_reference",
    "2k_rc_base_reference": "two_storey_rc_frame_foundation_reference",
}

MATERIAL_RESOURCE_ALIASES = {
    "2k_mid2_air_eos2": "two_storey_rc_frame_mid2_air_eos2",
    "2k_mid3_tnt_eos1": "two_storey_rc_frame_mid3_tnt_eos1",
    "2k_mid5_concrete_kc": "two_storey_rc_frame_mid5_concrete_kc",
    "2k_mid8_rebar_d8_d18": "two_storey_rc_frame_mid8_rebar_d8_d18",
    "2k_mid12_rebar_d12": "two_storey_rc_frame_mid12_rebar_d12",
    "2k_mid14_rebar_d20": "two_storey_rc_frame_mid14_rebar_d20",
}

STRUCTURAL_RESOURCE_ALIASES = {
    "2k_sections_used": "two_storey_rc_frame_sections",
    "2k_curve1_kc_rate": "two_storey_rc_frame_kc_rate_curve",
    "2k_part_role_map": "two_storey_rc_frame_part_roles",
    "2k_sets_used": "two_storey_rc_frame_sets",
    "2k_embedded_couplings": "two_storey_rc_frame_embedded_couplings",
}

MODEL_DISPLAY_NAMES = {
    REFERENCE_FAMILY_ID: REFERENCE_DISPLAY_NAME_EN,
    "two_storey_rc_frame_beam_reference": "Two-Storey RC Frame Reinforced Concrete Beam Reference",
    "two_storey_rc_frame_column_reference": "Two-Storey RC Frame Reinforced Concrete Column Reference",
    "two_storey_rc_frame_slab_reference": "Two-Storey RC Frame Reinforced Concrete Slab Reference",
    "two_storey_rc_frame_foundation_reference": "Two-Storey RC Frame Reinforced Concrete Foundation Reference",
}

MATERIAL_DISPLAY_NAMES = {
    "two_storey_rc_frame_mid2_air_eos2": "Two-Storey RC Frame Reference Air MID 2 + EOS 2",
    "two_storey_rc_frame_mid3_tnt_eos1": "Two-Storey RC Frame Reference TNT MID 3 + EOS 1",
    "two_storey_rc_frame_mid5_concrete_kc": "Two-Storey RC Frame Reference Concrete MID 5 (K&C)",
    "two_storey_rc_frame_mid8_rebar_d8_d18": "Two-Storey RC Frame Reference Rebar MID 8 (D8/D18)",
    "two_storey_rc_frame_mid12_rebar_d12": "Two-Storey RC Frame Reference Rebar MID 12 (D12)",
    "two_storey_rc_frame_mid14_rebar_d20": "Two-Storey RC Frame Reference Rebar MID 14 (D20)",
}

STRUCTURAL_DISPLAY_NAMES = {
    "two_storey_rc_frame_sections": "Two-Storey RC Frame Used Sections",
    "two_storey_rc_frame_kc_rate_curve": "Two-Storey RC Frame K&C Rate Curve 1",
    "two_storey_rc_frame_part_roles": "Two-Storey RC Frame Part Role and Binding Map",
    "two_storey_rc_frame_sets": "Two-Storey RC Frame Published Sets",
    "two_storey_rc_frame_embedded_couplings": "Two-Storey RC Frame Embedded Coupling Relationships",
}


def aliases_for(canonical_id: str, aliases: dict[str, str]) -> list[str]:
    return sorted(legacy for legacy, canonical in aliases.items() if canonical == canonical_id)
