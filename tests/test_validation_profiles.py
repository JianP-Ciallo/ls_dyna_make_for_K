from __future__ import annotations

import unittest

from lsprepost_mcp.validation_profiles import (
    required_card_groups_for_capabilities,
    required_cards_for_capabilities,
    validation_capabilities,
)
from lsprepost_mcp.project_store import required_keyword_card_present


class ValidationProfileTests(unittest.TestCase):
    def test_city_profile_requires_urban_blast_cards(self) -> None:
        capabilities = validation_capabilities(
            {"model_type": "city_street_blast_scene"},
            {},
        )
        cards = required_cards_for_capabilities(capabilities)
        self.assertIn("*CONSTRAINED_LAGRANGE_IN_SOLID", cards)
        self.assertIn("*SET_SEGMENT", cards)
        self.assertIn("*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE", cards)
        self.assertIn("*DATABASE_ALE_MAT", cards)
        self.assertNotIn("*DATABASE_ALE", cards)
        self.assertIn(
            (
                "*MAT_PLASTIC_KINEMATIC",
                "*MAT_PIECEWISE_LINEAR_PLASTICITY",
            ),
            required_card_groups_for_capabilities(capabilities),
        )

    def test_phase15_profile_requires_kc_axisymmetric_cards(self) -> None:
        capabilities = validation_capabilities(
            {"model_type": "phase15_axisymmetric_blast"},
            {},
        )
        cards = required_cards_for_capabilities(capabilities)
        self.assertIn("*MAT_CONCRETE_DAMAGE_REL3", cards)
        self.assertIn("*SECTION_ALE2D", cards)
        self.assertIn("*BOUNDARY_NON_REFLECTING_2D", cards)

    def test_explicit_capabilities_are_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown validation capability"):
            validation_capabilities(
                {"model_type": "shell_plate"},
                {"validation_capabilities": ["not_a_real_capability"]},
            )

    def test_conforming_interface_does_not_require_clis_cards(self) -> None:
        capabilities = validation_capabilities(
            {"model_type": "phase15_axisymmetric_blast"},
            {
                "validation_capabilities": [
                    "mm_ale",
                    "lagrangian_shell_structure",
                    "conforming_ale_lagrange_interface",
                ]
            },
        )
        cards = required_cards_for_capabilities(capabilities)
        self.assertNotIn("*CONSTRAINED_LAGRANGE_IN_SOLID", cards)
        self.assertNotIn("*DATABASE_FSI", cards)
        self.assertIn("*ALE_SMOOTHING", cards)

    def test_required_card_matching_does_not_confuse_2d_and_3d_boundary(self) -> None:
        tokens = {"*BOUNDARY_NON_REFLECTING_2D", "*SET_SEGMENT_TITLE"}
        self.assertFalse(
            required_keyword_card_present(tokens, "*BOUNDARY_NON_REFLECTING")
        )
        self.assertTrue(
            required_keyword_card_present(tokens, "*BOUNDARY_NON_REFLECTING_2D")
        )
        self.assertTrue(required_keyword_card_present(tokens, "*SET_SEGMENT"))


if __name__ == "__main__":
    unittest.main()
