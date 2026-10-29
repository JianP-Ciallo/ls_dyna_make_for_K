from __future__ import annotations

from copy import deepcopy
import unittest

from lsprepost_mcp.city_layout_contract import (
    city_editor_state_fingerprint,
    city_layout_fingerprint,
)
from lsprepost_mcp.city_editor import apply_city_component_operation
from lsprepost_mcp.city_street_blast import (
    build_city_street_blast_keyword,
    default_city_street_blast_spec,
)


class Phase17Phase16CompatibilityTests(unittest.TestCase):
    def test_layout_fingerprint_ignores_part_renumbering(self) -> None:
        spec = default_city_street_blast_spec("unit_phase17_layout")
        _keyword, metadata = build_city_street_blast_keyword(spec)
        before = city_layout_fingerprint(spec, metadata)
        moved_ids = deepcopy(metadata)
        moved_ids["semantic_objects"][0]["part_ids"] = [9001]

        self.assertEqual(before, city_layout_fingerprint(spec, moved_ids))

    def test_building_move_changes_layout_fingerprint(self) -> None:
        spec = default_city_street_blast_spec("unit_phase17_layout_move")
        _keyword, before_metadata = build_city_street_blast_keyword(spec)
        moved = deepcopy(spec)
        moved["layout"]["supermarket"]["origin_m"][0] += 1.0
        _keyword, after_metadata = build_city_street_blast_keyword(moved)

        self.assertNotEqual(
            city_layout_fingerprint(spec, before_metadata),
            city_layout_fingerprint(moved, after_metadata),
        )

    def test_blast_move_keeps_layout_but_changes_editor_state(self) -> None:
        spec = default_city_street_blast_spec("unit_phase17_source_move")
        _keyword, before = build_city_street_blast_keyword(spec)
        moved = deepcopy(spec)
        moved["explosive"]["base_center_m"] = [5.0, -4.0, 0.61]
        _keyword, after = build_city_street_blast_keyword(moved)

        self.assertEqual(
            city_layout_fingerprint(spec, before),
            city_layout_fingerprint(moved, after),
        )
        self.assertNotEqual(
            city_editor_state_fingerprint(spec, before),
            city_editor_state_fingerprint(moved, after),
        )
        self.assertEqual(
            after["layout_fingerprint"],
            city_layout_fingerprint(moved, after),
        )
        self.assertEqual(
            after["editor_state_fingerprint"],
            city_editor_state_fingerprint(moved, after),
        )

    def test_component_mutation_rebuilds_contact_and_semantic_dependencies(self) -> None:
        spec = default_city_street_blast_spec("unit_phase17_dependencies")
        added = apply_city_component_operation(
            spec,
            {"action": "add", "template": "parked_vehicle"},
        )["spec"]
        _keyword, added_metadata = build_city_street_blast_keyword(added)

        vehicle_objects = [
            item
            for item in added_metadata["semantic_objects"]
            if str(item["object_id"]).startswith("parked_vehicle_")
        ]
        vehicle_part_ids = [
            int(item["part_ids"][0])
            for item in vehicle_objects
        ]
        self.assertEqual(5, len(vehicle_objects))
        self.assertEqual(
            vehicle_part_ids,
            added_metadata["vehicle_contact"]["vehicle_part_ids"],
        )
        self.assertEqual(0, added_metadata["vehicle_contact"]["fixed_vehicle_nodes"])

        deleted = apply_city_component_operation(
            added,
            {"action": "delete", "component_id": "parked_vehicle_2"},
        )["spec"]
        _keyword, deleted_metadata = build_city_street_blast_keyword(deleted)
        deleted_ids = {
            str(item["object_id"])
            for item in deleted_metadata["semantic_objects"]
        }
        self.assertNotIn("parked_vehicle_2", deleted_ids)
        self.assertIn("parked_vehicle_5", deleted_ids)
        self.assertEqual(
            4,
            len(deleted_metadata["vehicle_contact"]["vehicle_part_ids"]),
        )
        self.assertNotEqual(
            added_metadata["layout_fingerprint"],
            deleted_metadata["layout_fingerprint"],
        )

    def test_subway_mutation_rebuilds_supported_fsi_and_semantic_dependencies(self) -> None:
        spec = default_city_street_blast_spec("unit_phase17_subway_dependencies")
        _keyword, before = build_city_street_blast_keyword(spec)
        added = apply_city_component_operation(
            spec,
            {"action": "add", "template": "subway_entrance"},
        )["spec"]
        _keyword, after = build_city_street_blast_keyword(added)

        subway_objects = [
            item
            for item in after["semantic_objects"]
            if str(item["object_id"]).startswith("subway_entrance")
        ]
        self.assertEqual(
            ["subway_entrance", "subway_entrance_2"],
            [item["object_id"] for item in subway_objects],
        )
        self.assertTrue(
            all(
                item["constraint_mode"] == "base_fixed"
                for item in subway_objects
            )
        )
        self.assertGreater(
            after["fsi"]["slave_segment_count"],
            before["fsi"]["slave_segment_count"],
        )
        self.assertNotEqual(
            after["layout_fingerprint"],
            before["layout_fingerprint"],
        )

        deleted = apply_city_component_operation(
            added,
            {"action": "delete", "component_id": "subway_entrance_2"},
        )["spec"]
        _keyword, rebuilt = build_city_street_blast_keyword(deleted)
        rebuilt_ids = {
            str(item["object_id"])
            for item in rebuilt["semantic_objects"]
        }
        self.assertIn("subway_entrance", rebuilt_ids)
        self.assertNotIn("subway_entrance_2", rebuilt_ids)
        self.assertEqual(
            before["fsi"]["slave_segment_count"],
            rebuilt["fsi"]["slave_segment_count"],
        )

    def test_existing_library_component_rebuilds_semantic_support_and_fsi(self) -> None:
        spec = default_city_street_blast_spec("unit_phase17_library_dependencies")
        _keyword, before = build_city_street_blast_keyword(spec)
        added = apply_city_component_operation(
            spec,
            {"action": "add", "template": "shell_box"},
        )["spec"]
        _keyword, after = build_city_street_blast_keyword(added)

        barrier = next(
            item
            for item in after["semantic_objects"]
            if item["object_id"] == "shell_box_1"
        )
        self.assertEqual("protection_boxes", barrier["group_id"])
        self.assertEqual("base_fixed", barrier["constraint_mode"])
        self.assertEqual("grounded", barrier["mobility_profile"])
        self.assertEqual("ground_foundation", barrier["support_object_id"])
        self.assertTrue(barrier["supports_ale_fsi"])
        self.assertGreater(
            after["fsi"]["slave_segment_count"],
            before["fsi"]["slave_segment_count"],
        )


if __name__ == "__main__":
    unittest.main()
