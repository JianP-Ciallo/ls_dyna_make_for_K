from __future__ import annotations

import copy
import math
import unittest

from lsprepost_mcp.refined_building.contracts import (
    default_building_definition,
    normalize_building_definition,
)


class Phase18CBuildingContractTests(unittest.TestCase):
    def test_default_contract_contains_real_space_and_declared_system(self) -> None:
        normalized = normalize_building_definition(default_building_definition())

        self.assertEqual("SI_m_s_kg_N_Pa", normalized["unit_system"])
        self.assertEqual("rc_frame", normalized["structural_system"]["type"])
        self.assertEqual("room_1", normalized["spaces"][0]["id"])
        self.assertTrue(normalized["requires_project_review"])

    def test_normalization_returns_independent_data_without_mutating_input(self) -> None:
        value = default_building_definition()
        before = copy.deepcopy(value)

        normalized = normalize_building_definition(value)
        normalized["envelope"]["size_m"][0] = 99.0
        normalized["structural_system"]["parameters"]["column_width_m"] = 0.5

        self.assertEqual(before, value)

    def test_contract_rejects_non_positive_envelope_and_non_monotonic_axes(self) -> None:
        invalid_envelope = default_building_definition()
        invalid_envelope["envelope"]["size_m"][2] = 0.0
        with self.assertRaisesRegex(ValueError, "envelope.size_m"):
            normalize_building_definition(invalid_envelope)

        invalid_axes = default_building_definition()
        invalid_axes["grid_axes"]["x_m"] = [0.0, 3.0, 3.0]
        with self.assertRaisesRegex(ValueError, "grid_axes.x_m"):
            normalize_building_definition(invalid_axes)

    def test_contract_rejects_duplicate_ids_and_out_of_envelope_space(self) -> None:
        duplicate = default_building_definition()
        duplicate["spaces"].append(dict(duplicate["spaces"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate space id"):
            normalize_building_definition(duplicate)

        outside = default_building_definition()
        outside["spaces"][0]["bounds_m"] = [-0.1, 0.25, 0.25, 5.75, 5.75, 2.75]
        with self.assertRaisesRegex(ValueError, "inside envelope"):
            normalize_building_definition(outside)

    def test_contract_rejects_unknown_level_and_opening_endpoint(self) -> None:
        unknown_level = default_building_definition()
        unknown_level["spaces"][0]["level_id"] = "missing"
        with self.assertRaisesRegex(ValueError, "unknown level"):
            normalize_building_definition(unknown_level)

        bad_opening = default_building_definition()
        bad_opening["openings"] = [
            {
                "id": "door_1",
                "kind": "door",
                "bounds_m": [2.8, 0.2, 0.0, 3.2, 0.3, 2.1],
                "connects": ["room_1", "missing_room"],
            }
        ]
        with self.assertRaisesRegex(ValueError, "unknown endpoint"):
            normalize_building_definition(bad_opening)

    def test_space_must_lie_within_assigned_level(self) -> None:
        value = default_building_definition()
        value["envelope"]["size_m"][2] = 6.0
        value["levels"].append({"id": "level_2", "elevation_m": 3.0, "height_m": 3.0})
        value["spaces"][0]["bounds_m"] = [0.25, 0.25, 3.25, 5.75, 5.75, 5.75]

        with self.assertRaisesRegex(ValueError, "assigned level"):
            normalize_building_definition(value)

    def test_exterior_opening_must_touch_envelope_and_declared_space(self) -> None:
        inside_envelope = default_building_definition()
        inside_envelope["openings"] = [
            {
                "id": "floating_entry",
                "kind": "door",
                "bounds_m": [0.25, 2.5, 0.25, 0.5, 3.5, 2.25],
                "connects": ["room_1", "exterior"],
            }
        ]
        with self.assertRaisesRegex(ValueError, "envelope boundary"):
            normalize_building_definition(inside_envelope)

        misses_space = default_building_definition()
        misses_space["openings"] = [
            {
                "id": "orphan_entry",
                "kind": "door",
                "bounds_m": [0.0, 0.0, 0.25, 0.1, 0.1, 2.25],
                "connects": ["room_1", "exterior"],
            }
        ]
        with self.assertRaisesRegex(ValueError, "declared space"):
            normalize_building_definition(misses_space)

    def test_opening_may_connect_a_space_to_the_exterior(self) -> None:
        value = default_building_definition()
        value["openings"] = [
            {
                "id": "entry_door",
                "kind": "door",
                "bounds_m": [0.0, 2.5, 0.25, 0.25, 3.5, 2.25],
                "connects": ["room_1", "exterior"],
            }
        ]

        normalized = normalize_building_definition(value)

        self.assertEqual(["room_1", "exterior"], normalized["openings"][0]["connects"])

    def test_positive_volume_opening_overlap_is_rejected(self) -> None:
        value = default_building_definition()
        value["spaces"][0]["bounds_m"] = [0.2, 0.2, 0.2, 5.8, 5.8, 2.8]
        value["openings"] = [
            {
                "id": "door_1",
                "kind": "door",
                "bounds_m": [0.0, 1.0, 0.2, 0.2, 2.0, 2.2],
                "connects": ["room_1", "exterior"],
            },
            {
                "id": "door_2",
                "kind": "door",
                "bounds_m": [0.0, 1.5, 0.5, 0.2, 2.5, 2.5],
                "connects": ["room_1", "exterior"],
            },
        ]

        with self.assertRaisesRegex(ValueError, "opening regions overlap"):
            normalize_building_definition(value)

    def test_openings_that_only_share_a_face_are_preserved(self) -> None:
        value = default_building_definition()
        value["spaces"][0]["bounds_m"] = [0.2, 0.2, 0.2, 5.8, 5.8, 2.8]
        value["openings"] = [
            {
                "id": "door_1",
                "kind": "door",
                "bounds_m": [0.0, 1.0, 0.2, 0.2, 2.0, 2.2],
                "connects": ["room_1", "exterior"],
            },
            {
                "id": "door_2",
                "kind": "door",
                "bounds_m": [0.0, 2.0, 0.2, 0.2, 3.0, 2.2],
                "connects": ["room_1", "exterior"],
            },
        ]

        normalized = normalize_building_definition(value)

        self.assertEqual(["door_1", "door_2"], [row["id"] for row in normalized["openings"]])

    def test_contract_rejects_non_finite_numbers_and_unsupported_profiles(self) -> None:
        non_finite = default_building_definition()
        non_finite["levels"][0]["height_m"] = math.inf
        with self.assertRaisesRegex(ValueError, "finite"):
            normalize_building_definition(non_finite)

        bad_units = default_building_definition()
        bad_units["unit_system"] = "mm-tonne-ms"
        with self.assertRaisesRegex(ValueError, "unit_system"):
            normalize_building_definition(bad_units)

        bad_profile = default_building_definition()
        bad_profile["fidelity_profile"] = "lightweight_city"
        with self.assertRaisesRegex(ValueError, "fidelity_profile"):
            normalize_building_definition(bad_profile)


if __name__ == "__main__":
    unittest.main()
