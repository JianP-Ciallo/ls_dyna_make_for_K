from __future__ import annotations

import copy
import unittest

from lsprepost_mcp.refined_building.contracts import default_building_definition
from lsprepost_mcp.refined_building.spatial import AxisAlignedBox, compile_spatial_topology


def two_room_fixture_with_door() -> dict[str, object]:
    value = default_building_definition()
    value["spaces"] = [
        {
            "id": "room_a",
            "level_id": "level_1",
            "kind": "room",
            "bounds_m": [0.25, 0.25, 0.25, 2.9, 5.75, 2.75],
        },
        {
            "id": "room_b",
            "level_id": "level_1",
            "kind": "room",
            "bounds_m": [3.1, 0.25, 0.25, 5.75, 5.75, 2.75],
        },
    ]
    value["openings"] = [
        {
            "id": "door_ab",
            "kind": "door",
            "bounds_m": [2.9, 2.5, 0.25, 3.1, 3.5, 2.25],
            "connects": ["room_a", "room_b"],
        }
    ]
    return value


class Phase18CSpatialTopologyTests(unittest.TestCase):
    def test_room_is_void_and_envelope_corner_is_not(self) -> None:
        topology = compile_spatial_topology(default_building_definition())

        self.assertEqual("void", topology.classify_point((3.0, 3.0, 1.5)))
        self.assertEqual("envelope", topology.classify_point((0.1, 0.1, 0.1)))
        self.assertEqual("outside", topology.classify_point((7.0, 3.0, 1.5)))
        self.assertAlmostEqual(108.0, topology.gross_volume_m3)
        self.assertAlmostEqual(5.5 * 5.5 * 2.5, topology.void_volume_m3)

    def test_opening_builds_symmetric_space_adjacency(self) -> None:
        topology = compile_spatial_topology(two_room_fixture_with_door())

        self.assertEqual({"room_b"}, set(topology.adjacency["room_a"]))
        self.assertEqual({"room_a"}, set(topology.adjacency["room_b"]))
        self.assertEqual("door_ab", topology.opening_regions[0][0])

    def test_multiple_openings_between_same_spaces_are_preserved(self) -> None:
        value = two_room_fixture_with_door()
        value["openings"].append(
            {
                "id": "door_ab_2",
                "kind": "door",
                "bounds_m": [2.9, 4.0, 0.25, 3.1, 4.8, 2.25],
                "connects": ["room_a", "room_b"],
            }
        )

        topology = compile_spatial_topology(value)

        self.assertEqual(("room_b",), topology.adjacency["room_a"])
        self.assertEqual(("room_a",), topology.adjacency["room_b"])
        self.assertEqual(["door_ab", "door_ab_2"], [row[0] for row in topology.opening_regions])

    def test_topology_is_deterministic_and_manifest_is_json_compatible(self) -> None:
        value = two_room_fixture_with_door()
        reordered = copy.deepcopy(value)
        reordered["spaces"] = list(reversed(reordered["spaces"]))

        first = compile_spatial_topology(value)
        second = compile_spatial_topology(reordered)

        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.to_manifest()["fingerprint"], first.fingerprint)
        self.assertEqual(["room_a", "room_b"], [row[0] for row in first.void_regions])

    def test_positive_volume_space_overlap_is_rejected(self) -> None:
        value = two_room_fixture_with_door()
        value["spaces"][1]["bounds_m"] = [2.8, 0.25, 0.25, 5.75, 5.75, 2.75]

        with self.assertRaisesRegex(ValueError, "overlap"):
            compile_spatial_topology(value)

    def test_axis_aligned_box_geometry_uses_positive_volume_intersection(self) -> None:
        box = AxisAlignedBox(0.0, 0.0, 0.0, 1.0, 2.0, 3.0)
        touching = AxisAlignedBox(1.0, 0.0, 0.0, 2.0, 1.0, 1.0)
        inner = AxisAlignedBox(0.1, 0.2, 0.3, 0.9, 1.8, 2.7)

        self.assertEqual(6.0, box.volume_m3)
        self.assertTrue(box.contains_point((0.0, 1.0, 3.0)))
        self.assertFalse(box.intersects(touching))
        self.assertTrue(box.contains_box(inner))


if __name__ == "__main__":
    unittest.main()
