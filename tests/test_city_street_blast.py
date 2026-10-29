from __future__ import annotations

from copy import deepcopy
import math
import shutil
import unittest

from lsprepost_mcp.city_street_blast import (
    build_city_street_blast_keyword,
    default_city_street_blast_spec,
    validate_city_street_blast_spec,
)
from lsprepost_mcp.config import PROJECTS_DIR
from lsprepost_mcp.keyword_checks import (
    keyword_quality_checks,
    parse_keyword_model,
)
from lsprepost_mcp.tool_generation import tool_generate_city_street_blast
from lsprepost_mcp.tools import TOOLS


class CityStreetBlastTests(unittest.TestCase):
    def test_default_scene_has_reviewed_urban_layout(self) -> None:
        spec = validate_city_street_blast_spec(default_city_street_blast_spec())
        self.assertEqual("city_street_blast", spec["scene_id"])
        self.assertEqual(10.0, spec["layout"]["residential_setback_m"])
        self.assertEqual(0.3, spec["layout"]["subway_entrance"]["platform_height_m"])
        self.assertEqual("front_open_three_sides_enclosed", spec["layout"]["subway_entrance"]["enclosure"])
        self.assertEqual("solid_cylinder", spec["explosive"]["geometry_type"])
        self.assertGreaterEqual(spec["analysis"]["end_time_s"], 0.05)
        self.assertLessEqual(
            spec["analysis"]["end_time_s"]
            / spec["analysis"]["d3plot_dt_s"],
            100,
        )
        expected_length = spec["explosive"]["mass_kg"] / (
            spec["explosive"]["density_kg_per_m3"]
            * math.pi
            * (0.5 * spec["explosive"]["diameter_m"]) ** 2
        )
        self.assertAlmostEqual(expected_length, spec["explosive"]["length_m"])

    def test_keyword_contains_entity_tnt_and_city_fsi(self) -> None:
        keyword, metadata = build_city_street_blast_keyword(
            default_city_street_blast_spec("unit_city_street_blast")
        )
        self.assertIn("*MAT_HIGH_EXPLOSIVE_BURN", keyword)
        self.assertIn("*EOS_JWL", keyword)
        self.assertIn("*INITIAL_VOLUME_FRACTION_GEOMETRY", keyword)
        self.assertIn("$ entity TNT cylinder", keyword)
        self.assertIn("\n4,0,2\n", keyword)
        self.assertIn("*INITIAL_DETONATION", keyword)
        self.assertIn("*CONSTRAINED_LAGRANGE_IN_SOLID", keyword)
        first_response = metadata["response_objects"][0]
        self.assertIn(
            f"{first_response['fsi_surface_id']},"
            f"{first_response['fsi_segment_set_id']},2",
            keyword,
        )
        self.assertNotIn("1,3,1\n2,4,1", keyword)
        self.assertIn("*SET_SEGMENT_TITLE", keyword)
        self.assertIn("*BOUNDARY_NON_REFLECTING", keyword)
        self.assertIn("*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE", keyword)
        self.assertIn("Commercial supermarket", keyword)
        self.assertIn("Residential community", keyword)
        self.assertIn("Subway entrance", keyword)
        self.assertIn("Parking lot", keyword)
        self.assertIn("Concrete road", keyword)
        self.assertIn("Urban ground foundation northwest", keyword)
        self.assertIn("Movable parked vehicle", keyword)
        self.assertIn("Entity TNT cylinder side guide", keyword)
        self.assertIn("Traffic lights", keyword)
        self.assertGreater(metadata["ale_domain"]["solid_element_count"], 0)
        self.assertGreater(metadata["fsi"]["slave_segment_count"], 0)
        self.assertEqual("solid_cylinder", metadata["explosive"]["geometry_type"])
        self.assertGreaterEqual(metadata["explosive"]["diameter_cells"], 3.0)
        self.assertGreater(
            metadata["urban_components"]["commercial_supermarket"]["detail_count"],
            0,
        )
        self.assertGreater(
            metadata["urban_components"]["residential_community"]["detail_count"],
            0,
        )
        self.assertGreater(
            metadata["urban_components"]["subway_entrance"]["detail_count"],
            0,
        )
        self.assertEqual(
            4,
            len(metadata["urban_components"]["ground_foundation"]["part_ids"]),
        )
        self.assertEqual("free", metadata["urban_components"]["parked_vehicles"]["constraint_mode"])
        self.assertEqual(
            "non_structural_visual_guide",
            metadata["explosive"]["visible_geometry"]["role"],
        )
        self.assertEqual(
            "phase16a.city_semantics.v1",
            metadata["city_semantic_schema_version"],
        )
        semantic_objects = metadata["semantic_objects"]
        object_ids = [item["object_id"] for item in semantic_objects]
        semantic_part_ids = [
            part_id
            for item in semantic_objects
            for part_id in item["part_ids"]
        ]
        self.assertEqual(len(object_ids), len(set(object_ids)))
        self.assertEqual(len(semantic_part_ids), len(set(semantic_part_ids)))
        self.assertTrue(all(item["group_id"] for item in semantic_objects))
        self.assertTrue(
            all(
                len(item["bounds_m"]["min"]) == 3
                and len(item["bounds_m"]["max"]) == 3
                and all(
                    lower <= upper
                    for lower, upper in zip(
                        item["bounds_m"]["min"],
                        item["bounds_m"]["max"],
                        strict=True,
                    )
                )
                for item in semantic_objects
            )
        )
        self.assertEqual(
            set(semantic_part_ids),
            {
                part_id
                for row in metadata["urban_components"].values()
                for part_id in row["part_ids"]
            },
        )

    def test_response_components_use_base_constraints_without_fully_fixed_fsi_faces(
        self,
    ) -> None:
        keyword, metadata = build_city_street_blast_keyword(
            default_city_street_blast_spec("unit_city_supported_response")
        )
        card_tokens = {
            line.strip().upper()
            for line in keyword.splitlines()
            if line.strip().startswith("*")
        }
        self.assertIn("*DATABASE_ALE_MAT", card_tokens)
        self.assertNotIn("*DATABASE_ALE", card_tokens)
        self.assertIn(
            "ale_pressure_outputs_r12_safe",
            metadata["validation_capabilities"],
        )
        self.assertNotIn(
            "ale_pressure_outputs",
            metadata["validation_capabilities"],
        )
        del keyword
        by_id = {
            item["object_id"]: item
            for item in metadata["semantic_objects"]
        }

        for object_id in (
            "commercial_supermarket",
            "residential_community",
            "subway_entrance",
            "traffic_light_1",
            "traffic_light_2",
            "traffic_light_3",
            "traffic_light_4",
        ):
            item = by_id[object_id]
            self.assertEqual("base_fixed", item["constraint_mode"])
            self.assertGreater(item["fixed_node_count"], 0)
            self.assertLess(item["fixed_node_count"], item["node_count"])
            self.assertGreater(item["fsi_segment_count"], 0)
            self.assertEqual(0, item["floating_shell_island_count"])
            if object_id.startswith("traffic_light_"):
                self.assertEqual("mild_steel", item["material_name"])

        for object_id in (
            "concrete_road_west",
            "concrete_road_east",
            "concrete_road_south",
            "concrete_road_north",
            "concrete_road_intersection",
            "ground_foundation_northwest",
            "ground_foundation_northeast",
            "ground_foundation_southwest",
            "ground_foundation_southeast",
            "parking_lot",
        ):
            item = by_id[object_id]
            self.assertEqual("fixed", item["constraint_mode"])
            self.assertFalse(item["supports_ale_fsi"])
            self.assertEqual(0, item["fsi_segment_count"])

        for index in range(1, 5):
            item = by_id[f"parked_vehicle_{index}"]
            self.assertEqual("free", item["constraint_mode"])
            self.assertEqual(0, item["fixed_node_count"])
            self.assertGreater(item["fsi_segment_count"], 0)

        self.assertEqual(
            0,
            metadata["fsi"]["fully_constrained_slave_segment_count"],
        )
        self.assertGreater(
            metadata["fsi"]["excluded_fully_constrained_segment_count"],
            0,
        )

    def test_required_response_objects_have_disjoint_fsi_and_history_sets(
        self,
    ) -> None:
        keyword, metadata = build_city_street_blast_keyword(
            default_city_street_blast_spec("unit_city_object_response_sets")
        )
        response_objects = metadata["response_objects"]
        expected_ids = {
            "commercial_supermarket",
            "parked_vehicle_1",
            "parked_vehicle_2",
            "parked_vehicle_3",
            "parked_vehicle_4",
            "residential_community",
            "subway_entrance",
            "traffic_light_1",
            "traffic_light_2",
            "traffic_light_3",
            "traffic_light_4",
        }

        self.assertEqual(
            expected_ids,
            {item["object_id"] for item in response_objects},
        )
        self.assertTrue(
            all(item["fsi_segment_count"] > 0 for item in response_objects)
        )
        self.assertTrue(
            all(item["shell_element_ids"] for item in response_objects)
        )
        self.assertTrue(all(item["node_ids"] for item in response_objects))
        self.assertTrue(
            all(
                len(item["shell_element_ids"]) <= 32
                for item in response_objects
            )
        )
        self.assertTrue(
            all(len(item["node_ids"]) <= 32 for item in response_objects)
        )
        for key in (
            "fsi_segment_set_id",
            "fsi_surface_id",
            "shell_history_set_id",
            "node_history_set_id",
        ):
            values = [item[key] for item in response_objects]
            self.assertEqual(len(values), len(set(values)), key)

        self.assertEqual(
            len(response_objects),
            keyword.count("*CONSTRAINED_LAGRANGE_IN_SOLID"),
        )
        self.assertEqual(
            len(response_objects),
            sum(
                1
                for line in keyword.splitlines()
                if line.startswith("$ city FSI interface:")
            ),
        )
        for item in response_objects:
            self.assertIn(
                f"City response FSI segments: {item['object_id']}",
                keyword,
            )
            self.assertIn(
                f"City response shell history: {item['object_id']}",
                keyword,
            )
            self.assertIn(
                f"City response node history: {item['object_id']}",
                keyword,
            )

    def test_added_vehicle_automatically_becomes_individual_response_object(
        self,
    ) -> None:
        spec = default_city_street_blast_spec(
            "unit_city_added_vehicle_response"
        )
        spec["layout"]["parked_vehicles"]["instances"].append(
            {
                "instance_id": "parked_vehicle_5",
                "origin_m": [27.0, -25.5, 0.1],
                "rotate_z_deg": 0.0,
            }
        )

        keyword, metadata = build_city_street_blast_keyword(spec)

        response_by_id = {
            item["object_id"]: item
            for item in metadata["response_objects"]
        }
        vehicle = response_by_id["parked_vehicle_5"]
        self.assertGreater(vehicle["fsi_segment_count"], 0)
        self.assertTrue(vehicle["shell_element_ids"])
        self.assertTrue(vehicle["node_ids"])
        self.assertIn(
            "City response FSI segments: parked_vehicle_5",
            keyword,
        )
        self.assertIn(
            "City response shell history: parked_vehicle_5",
            keyword,
        )
        self.assertIn(
            "City response node history: parked_vehicle_5",
            keyword,
        )

    def test_phase17_quality_gate_rejects_fully_constrained_fsi_segment(
        self,
    ) -> None:
        spec = default_city_street_blast_spec(
            "unit_city_fully_constrained_fsi"
        )
        keyword, metadata = build_city_street_blast_keyword(spec)
        first_response = metadata["response_objects"][0]
        first_segment = ",".join(
            str(node_id)
            for node_id in parse_keyword_model(keyword).segment_sets[
                first_response["fsi_segment_set_id"]
            ][0]
        )
        injected = "\n".join(
            [
                "*SET_NODE_LIST_TITLE",
                "Injected fully constrained FSI nodes",
                "990001",
                first_segment,
                "*BOUNDARY_SPC_SET",
                "990001,0,1,1,1,0,0,0",
            ]
        )
        broken = keyword.replace("*END\n", f"{injected}\n*END\n")

        valid_checks = keyword_quality_checks(keyword, spec, metadata)
        valid_by_id = {item["id"]: item for item in valid_checks}
        self.assertTrue(
            valid_by_id[
                "quality.phase17.fsi_fully_constrained_segments"
            ]["ok"]
        )

        broken_checks = keyword_quality_checks(broken, spec, metadata)
        broken_by_id = {item["id"]: item for item in broken_checks}
        self.assertFalse(
            broken_by_id[
                "quality.phase17.fsi_fully_constrained_segments"
            ]["ok"]
        )
        self.assertGreater(
            broken_by_id[
                "quality.phase17.fsi_fully_constrained_segments"
            ]["actual"]["segment_count"],
            0,
        )

    def test_city_quality_checks_detect_broken_fsi_reference(self) -> None:
        spec = default_city_street_blast_spec("unit_city_broken_fsi")
        keyword, metadata = build_city_street_blast_keyword(spec)
        first_response = metadata["response_objects"][0]
        valid_reference = (
            f"{first_response['fsi_surface_id']},"
            f"{first_response['fsi_segment_set_id']},2"
        )
        broken = keyword.replace(
            valid_reference,
            f"{first_response['fsi_surface_id']},999999,2",
            1,
        )
        checks = keyword_quality_checks(broken, spec, metadata)
        by_id = {item["id"]: item for item in checks}
        self.assertFalse(by_id["quality.ref.database_fsi_segment_sets"]["ok"])
        self.assertEqual(
            [999999],
            by_id["quality.ref.database_fsi_segment_sets"]["actual"],
        )

    def test_city_quality_checks_bind_phase17_mesh_and_source_metadata(self) -> None:
        spec = default_city_street_blast_spec("unit_city_phase17_checks")
        keyword, metadata = build_city_street_blast_keyword(spec)
        checks = keyword_quality_checks(keyword, spec, metadata)
        by_id = {item["id"]: item for item in checks}
        self.assertTrue(by_id["quality.phase17.ale_mesh_fingerprint"]["ok"])
        self.assertTrue(by_id["quality.phase17.source_refinement_binding"]["ok"])
        self.assertTrue(by_id["quality.phase17.initial_detonation_binding"]["ok"])

        stale = deepcopy(metadata)
        stale["explosive"]["center_m"][0] += 1.0
        stale_checks = keyword_quality_checks(keyword, spec, stale)
        stale_by_id = {item["id"]: item for item in stale_checks}
        self.assertFalse(
            stale_by_id["quality.phase17.source_refinement_binding"]["ok"]
        )
        self.assertFalse(
            stale_by_id["quality.phase17.initial_detonation_binding"]["ok"]
        )

    def test_tnt_requires_three_cells_across_diameter(self) -> None:
        spec = default_city_street_blast_spec()
        spec["mesh"]["near_size_m"] = spec["explosive"]["diameter_m"] / 2.0
        with self.assertRaisesRegex(ValueError, "at least 3"):
            validate_city_street_blast_spec(spec)

    def test_blast_move_recenters_ale_refinement_without_moving_domain(self) -> None:
        baseline = default_city_street_blast_spec("unit_city_mesh_baseline")
        _keyword, before = build_city_street_blast_keyword(baseline)
        moved = deepcopy(baseline)
        moved["project_name"] = "unit_city_mesh_moved"
        moved["explosive"]["base_center_m"] = [6.0, -5.0, 0.61]

        _keyword, after = build_city_street_blast_keyword(moved)

        self.assertEqual(
            before["ale_domain"]["bounds_m"],
            after["ale_domain"]["bounds_m"],
        )
        self.assertNotEqual(
            before["ale_domain"]["mesh_fingerprint"],
            after["ale_domain"]["mesh_fingerprint"],
        )
        self.assertEqual(
            after["ale_domain"]["refinement_center_m"],
            after["explosive"]["center_m"],
        )
        self.assertGreaterEqual(after["explosive"]["diameter_cells_actual"], 3.0)
        self.assertGreaterEqual(after["explosive"]["length_cells_actual"], 3.0)
        self.assertEqual(
            "blast_source_regenerated",
            after["ale_domain"]["remesh_reason"],
        )

    def test_blast_refinement_window_must_fit_fixed_domain(self) -> None:
        spec = default_city_street_blast_spec("unit_city_mesh_edge")
        spec["explosive"]["base_center_m"][0] = 35.0
        with self.assertRaisesRegex(
            ValueError,
            "blast_refinement_window_outside_domain",
        ):
            build_city_street_blast_keyword(spec)

    def test_tool_dry_run_does_not_write_project(self) -> None:
        project_name = "unit_city_street_blast_dry_run"
        project_dir = PROJECTS_DIR / project_name
        if project_dir.exists():
            shutil.rmtree(project_dir)
        result = tool_generate_city_street_blast(
            {"project_name": project_name, "dry_run": True}
        )
        self.assertTrue(result["ok"])
        self.assertEqual("validated_only", result["status"])
        self.assertFalse(project_dir.exists())
        self.assertEqual("explicit_user_approval_required", result["solver_permission"])

    def test_city_scene_tool_is_registered_with_bounded_inputs(self) -> None:
        self.assertIn("generate_city_street_blast", TOOLS)
        description, schema, handler = TOOLS["generate_city_street_blast"]
        self.assertIs(handler, tool_generate_city_street_blast)
        self.assertFalse(schema["additionalProperties"])
        self.assertIn("never launches LS-DYNA", description)
        self.assertEqual(
            [0.1, 0.15, 0.2],
            schema["properties"]["near_mesh_size_m"]["enum"],
        )


if __name__ == "__main__":
    unittest.main()
