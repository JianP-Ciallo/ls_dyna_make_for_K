from __future__ import annotations

import unittest

from lsprepost_mcp.refined_building.systems import (
    get_structural_system,
    list_structural_systems,
    normalize_structural_system_profile,
)


class Phase18CStructuralSystemTests(unittest.TestCase):
    def test_registry_has_exact_first_phase_systems(self) -> None:
        self.assertEqual(
            {
                "rc_frame",
                "rc_frame_shear_wall",
                "steel_frame",
                "steel_concrete_hybrid",
                "rc_box",
                "custom_hybrid",
            },
            {row.system_id for row in list_structural_systems()},
        )

    def test_reinforcement_modes_are_rc_scoped(self) -> None:
        self.assertIn(
            "full_reinforced",
            get_structural_system("rc_frame").allowed_generation_modes,
        )
        self.assertIn(
            "concrete_only",
            get_structural_system("rc_box").allowed_generation_modes,
        )
        self.assertEqual((), get_structural_system("steel_frame").allowed_generation_modes)
        self.assertEqual(
            (), get_structural_system("steel_concrete_hybrid").allowed_generation_modes
        )

    def test_normalization_supplies_rc_default_but_rejects_rc_mode_for_steel(self) -> None:
        rc = normalize_structural_system_profile({"type": "rc_frame", "parameters": {}})
        self.assertEqual("full_reinforced", rc["parameters"]["generation_mode"])

        with self.assertRaisesRegex(ValueError, "generation_mode"):
            normalize_structural_system_profile(
                {
                    "type": "steel_frame",
                    "parameters": {"generation_mode": "concrete_only"},
                }
            )

    def test_unknown_system_is_rejected_with_available_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown structural system"):
            get_structural_system("masonry_frame")

    def test_custom_hybrid_requires_two_subsystems_and_non_overlapping_zones(self) -> None:
        valid = normalize_structural_system_profile(
            {
                "type": "custom_hybrid",
                "parameters": {
                    "subsystems": ["steel_frame", "rc_frame"],
                    "zones": [
                        {
                            "id": "west",
                            "system_id": "steel_frame",
                            "bounds_m": [0.0, 0.0, 0.0, 3.0, 6.0, 3.0],
                        },
                        {
                            "id": "east",
                            "system_id": "rc_frame",
                            "bounds_m": [3.0, 0.0, 0.0, 6.0, 6.0, 3.0],
                        },
                    ],
                },
            }
        )
        self.assertEqual(["steel_frame", "rc_frame"], valid["parameters"]["subsystems"])

        with self.assertRaisesRegex(ValueError, "at least two"):
            normalize_structural_system_profile(
                {
                    "type": "custom_hybrid",
                    "parameters": {"subsystems": ["rc_frame"], "zones": []},
                }
            )

        with self.assertRaisesRegex(ValueError, "overlap"):
            normalize_structural_system_profile(
                {
                    "type": "custom_hybrid",
                    "parameters": {
                        "subsystems": ["steel_frame", "rc_frame"],
                        "zones": [
                            {
                                "id": "a",
                                "system_id": "steel_frame",
                                "bounds_m": [0.0, 0.0, 0.0, 4.0, 6.0, 3.0],
                            },
                            {
                                "id": "b",
                                "system_id": "rc_frame",
                                "bounds_m": [3.0, 0.0, 0.0, 6.0, 6.0, 3.0],
                            },
                        ],
                    },
                }
            )


if __name__ == "__main__":
    unittest.main()
