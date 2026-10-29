from __future__ import annotations

import unittest

from lsprepost_mcp.phase15 import (
    compile_phase15_a1_mesh_plan,
    default_phase15_a1_inputs,
    resolve_phase15_air_gap,
)
from lsprepost_mcp.phase15_keyword import (
    build_phase15_a1_keyword,
    compile_phase15_a1_solver_model,
)
from lsprepost_mcp.tool_generation import (
    tool_generate_phase15_a1,
    tool_prepare_phase15_a1,
)


def _inputs(coupling_mode: str) -> dict[str, object]:
    result = default_phase15_a1_inputs()
    result["consistency_mode"] = "mass_priority_adjust_length"
    result["coupling_mode"] = coupling_mode
    if coupling_mode != "immersed_clis":
        result.pop("fsi_overlap_layers", None)
    return result


def _normalized_edges(elements: list[list[int]]) -> set[tuple[int, int]]:
    result: set[tuple[int, int]] = set()
    for element in elements:
        nodes = [int(value) for value in element[2:6]]
        for index in range(4):
            result.add(tuple(sorted((nodes[index], nodes[(index + 1) % 4]))))
    return result


class Phase15ConformingTests(unittest.TestCase):
    def test_conforming_air_gap_is_explicit_and_immersed_remains_default(self) -> None:
        defaults = default_phase15_a1_inputs()

        self.assertEqual(defaults["coupling_mode"], "immersed_clis")
        defaults["coupling_mode"] = "conforming_air_gap"
        resolved = resolve_phase15_air_gap(defaults)

        self.assertEqual(resolved["minimum_gap_cells"], 3)
        self.assertAlmostEqual(resolved["borehole_radius_m"], 0.073)
        self.assertAlmostEqual(resolved["side_air_gap_m"], 0.024)
        self.assertAlmostEqual(resolved["bottom_air_gap_m"], 0.024)

    def test_conforming_generation_rejects_destructive_if_exists_modes(self) -> None:
        for mode in ("overwrite", "archive_then_write", "versioned"):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(ValueError, "if_exists=error"):
                    tool_generate_phase15_a1(
                        {
                            "project_name": "new_conforming_contract",
                            "coupling_mode": "conforming_air_gap",
                            "consistency_mode": "mass_priority_adjust_length",
                            "if_exists": mode,
                            "dry_run": True,
                        }
                    )

    def test_conforming_air_gap_separates_tnt_from_concrete(self) -> None:
        plan = compile_phase15_a1_mesh_plan(_inputs("conforming_air_gap"))

        gap = plan["phase15_air_gap"]
        self.assertGreaterEqual(gap["side_air_gap_cells"], 3)
        self.assertGreaterEqual(gap["bottom_air_gap_cells"], 3)
        self.assertAlmostEqual(gap["side_air_gap_m"], 0.024)
        self.assertAlmostEqual(gap["bottom_air_gap_m"], 0.024)
        self.assertEqual(plan["fsi_coupling"]["overlap_layers"], 0)
        self.assertEqual(plan["fsi_coupling"]["overlap_depth_m"], 0.0)
        self.assertEqual(
            plan["interfaces"]["tnt_to_concrete"]["matched_node_count"],
            0,
        )
        self.assertFalse(plan["interfaces"]["tnt_to_concrete"]["active"])

        tnt_nodes = {
            int(node_id)
            for element in plan["regions"]["tnt"]["elements"]
            for node_id in element[2:6]
        }
        concrete_nodes = {
            int(node_id)
            for element in plan["regions"]["concrete"]["elements"]
            for node_id in element[2:6]
        }
        self.assertTrue(tnt_nodes.isdisjoint(concrete_nodes))
        self.assertGreater(
            plan["interfaces"]["air_to_concrete"]["matched_node_count"],
            0,
        )
        self.assertTrue(
            plan["interfaces"]["air_to_concrete"]["coordinates_match"]
        )

    def test_conforming_air_gap_below_three_actual_cells_is_rejected(self) -> None:
        values = _inputs("conforming_air_gap")
        values["mesh_size_m"] = 0.01
        values["borehole_radius_m"] = float(values["tnt_radius_m"]) + 0.02

        with self.assertRaisesRegex(ValueError, "at least 3 actual ALE cells"):
            compile_phase15_a1_mesh_plan(values)

    def test_conforming_air_gap_ale_centroids_do_not_enter_concrete(self) -> None:
        plan = compile_phase15_a1_mesh_plan(_inputs("conforming_air_gap"))
        geometry = plan["geometry"]
        borehole_radius = float(geometry["borehole_radius_m"])
        borehole_bottom = float(geometry["borehole_bottom_z_m"])
        target_top = float(geometry["target_top_z_m"])

        for region_name in ("tnt", "air"):
            region = plan["regions"][region_name]
            coordinates = {
                int(node[0]): (float(node[1]), float(node[2]))
                for node in region["nodes"]
            }
            for element in region["elements"]:
                points = [coordinates[int(node_id)] for node_id in element[2:6]]
                radius = sum(point[0] for point in points) / 4.0
                axial = sum(point[1] for point in points) / 4.0
                in_concrete = (
                    axial <= target_top
                    and not (
                        radius < borehole_radius
                        and axial > borehole_bottom
                    )
                )
                self.assertFalse(
                    in_concrete,
                    f"{region_name} element {element[0]} lies inside concrete",
                )

    def test_conforming_air_gap_includes_full_upper_air_bath(self) -> None:
        plan = compile_phase15_a1_mesh_plan(_inputs("conforming_air_gap"))
        geometry = plan["geometry"]
        air = plan["regions"]["air"]
        coordinates = {
            int(node[0]): (float(node[1]), float(node[2]))
            for node in air["nodes"]
        }
        centroids = [
            (
                sum(coordinates[int(node_id)][0] for node_id in element[2:6])
                / 4.0,
                sum(coordinates[int(node_id)][1] for node_id in element[2:6])
                / 4.0,
            )
            for element in air["elements"]
        ]
        target_top = float(geometry["target_top_z_m"])
        target_radius = float(geometry["target_radius_m"])
        air_top = float(geometry["air_top_z_m"])

        self.assertAlmostEqual(
            max(float(node[1]) for node in air["nodes"]),
            target_radius,
        )
        self.assertAlmostEqual(
            max(float(node[2]) for node in air["nodes"]),
            air_top,
        )
        self.assertTrue(
            any(
                radius > 0.9 * target_radius and axial > target_top
                for radius, axial in centroids
            )
        )
        self.assertGreater(len(air["boundaries"]["target_top"]), 0)
        self.assertEqual([], air["boundaries"]["opening_nonreflecting"])

    def test_conforming_plan_has_only_physical_fluid_region(self) -> None:
        plan = compile_phase15_a1_mesh_plan(_inputs("conforming_shared_nodes"))
        self.assertEqual(plan["fsi_coupling"]["mode"], "conforming_shared_nodes")
        self.assertEqual(plan["fsi_coupling"]["overlap_layers"], 0)
        self.assertEqual(plan["fsi_coupling"]["overlap_depth_m"], 0.0)

        geometry = plan["geometry"]
        charge_radius = float(geometry["charge_radius_m"])
        charge_bottom = float(geometry["charge_bottom_z_m"])
        target_top = float(geometry["target_top_z_m"])
        target_radius = float(geometry["target_radius_m"])
        for region_name in ("tnt", "air"):
            region = plan["regions"][region_name]
            coordinates = {
                int(node[0]): (float(node[1]), float(node[2]))
                for node in region["nodes"]
            }
            for element in region["elements"]:
                points = [coordinates[int(node_id)] for node_id in element[2:6]]
                radius = sum(point[0] for point in points) / 4.0
                axial = sum(point[1] for point in points) / 4.0
                in_concrete = (
                    0.0 <= radius <= target_radius
                    and 0.0 <= axial <= target_top
                    and not (
                        radius < charge_radius
                        and axial > charge_bottom
                    )
                )
                self.assertFalse(
                    in_concrete,
                    f"{region_name} element {element[0]} lies inside concrete",
                )
        air_nodes = plan["regions"]["air"]["nodes"]
        self.assertLessEqual(
            max(float(node[2]) for node in air_nodes),
            float(geometry["target_top_z_m"]),
        )

    def test_conforming_solver_uses_shared_interface_edges(self) -> None:
        model = compile_phase15_a1_solver_model(
            _inputs("conforming_shared_nodes")
        )
        self.assertEqual(
            model["interfaces"]["coupling_mode"],
            "conforming_shared_nodes",
        )
        self.assertGreater(model["interfaces"]["shared_node_count"], 0)
        self.assertEqual(model["interfaces"]["geometric_gap_max_m"], 0.0)
        self.assertEqual(
            model["interfaces"]["ale_concrete_overlap_area_m2"],
            0.0,
        )
        self.assertEqual(
            model["interfaces"]["interface_surfaces"]["concrete_top"],
            [],
        )
        self.assertEqual(
            model["interfaces"]["interface_surfaces"]["total_count"],
            len(model["interfaces"]["interface_surfaces"]["charge_bottom"])
            + len(model["interfaces"]["interface_surfaces"]["borehole_wall"]),
        )
        smoothing = model["ale_smoothing_constraints"]
        self.assertGreater(len(smoothing), 0)
        shared_nodes = set(model["interfaces"]["shared_node_ids"])
        coordinates = {
            int(node[0]): (float(node[1]), float(node[2]))
            for node in model["nodes"]
        }
        for constraint in smoothing:
            slave, axis, wall = (
                int(constraint["slave_node_id"]),
                int(constraint["axis_node_id"]),
                int(constraint["wall_node_id"]),
            )
            self.assertEqual(constraint["ipre"], 0)
            self.assertNotIn(slave, shared_nodes)
            self.assertEqual(coordinates[axis][0], 0.0)
            self.assertAlmostEqual(
                coordinates[wall][0],
                float(model["geometry"]["charge_radius_m"]),
            )
            self.assertAlmostEqual(coordinates[slave][1], coordinates[axis][1])
            self.assertAlmostEqual(coordinates[slave][1], coordinates[wall][1])

        ale_edges = _normalized_edges(
            [element for element in model["elements"] if int(element[1]) == 1]
        )
        concrete_edges = _normalized_edges(
            [element for element in model["elements"] if int(element[1]) == 3]
        )
        for segment in model["interfaces"]["interface_surfaces"]["all_segments"]:
            edge = tuple(sorted((int(segment[0]), int(segment[1]))))
            self.assertIn(edge, ale_edges)
            self.assertIn(edge, concrete_edges)

    def test_conforming_air_gap_solver_uses_borehole_and_top_interfaces(self) -> None:
        model = compile_phase15_a1_solver_model(_inputs("conforming_air_gap"))

        interfaces = model["interfaces"]
        self.assertEqual(interfaces["coupling_mode"], "conforming_air_gap")
        self.assertEqual(interfaces["fsi_surfaces"], {})
        self.assertEqual(interfaces["tnt_concrete_shared_node_count"], 0)
        self.assertGreater(interfaces["shared_node_count"], 0)
        self.assertGreater(interfaces["shared_edge_count"], 0)
        self.assertEqual(interfaces["geometric_gap_max_m"], 0.0)
        self.assertEqual(interfaces["ale_concrete_overlap_area_m2"], 0.0)
        self.assertEqual(
            set(interfaces["interface_surfaces"]),
            {
                "borehole_bottom",
                "borehole_side",
                "concrete_top",
                "all_segments",
                "counts",
                "total_count",
            },
        )
        self.assertEqual(
            interfaces["shared_edge_count"],
            interfaces["interface_surfaces"]["total_count"],
        )

        coordinates = {
            int(node[0]): (float(node[1]), float(node[2]))
            for node in model["nodes"]
        }
        for constraint in model["ale_smoothing_constraints"]:
            wall = int(constraint["wall_node_id"])
            self.assertAlmostEqual(
                coordinates[wall][0],
                float(model["geometry"]["borehole_radius_m"]),
            )

        self.assertEqual(
            {probe["id"] for probe in model["probes"]["ale"]},
            {"TNT_NEAR", "AIR_MID_GAP", "AIR_INTERFACE"},
        )
        self.assertEqual(
            sorted(probe["element_id"] for probe in model["probes"]["ale"]),
            model["probes"]["ale_element_ids"],
        )

    def test_conforming_air_gap_keyword_is_not_clis(self) -> None:
        keyword, metadata, _ = build_phase15_a1_keyword(
            "phase15_conforming_air_gap_test",
            _inputs("conforming_air_gap"),
        )

        self.assertIn(
            "Phase15 coupling mode: conforming_air_gap",
            keyword,
        )
        self.assertNotIn("*CONSTRAINED_LAGRANGE_IN_SOLID", keyword)
        self.assertNotIn("*DATABASE_FSI", keyword)
        self.assertIn("*ALE_SMOOTHING", keyword)
        self.assertEqual(
            metadata["phase15"]["interfaces"]["tnt_concrete_shared_node_count"],
            0,
        )
        self.assertEqual(
            metadata["ale_domain"]["bounds_m"]["max"][0],
            metadata["phase15"]["geometry"]["target_radius_m"],
        )
        self.assertEqual(
            metadata["ale_domain"]["bounds_m"]["min"][1],
            metadata["phase15"]["geometry"]["borehole_bottom_z_m"],
        )

    def test_keywords_are_mode_specific(self) -> None:
        conforming_keyword, conforming_metadata, _ = build_phase15_a1_keyword(
            "phase15_conforming_test",
            _inputs("conforming_shared_nodes"),
        )
        self.assertIn(
            "Phase15 coupling mode: conforming_shared_nodes",
            conforming_keyword,
        )
        self.assertNotIn("*CONSTRAINED_LAGRANGE_IN_SOLID", conforming_keyword)
        self.assertNotIn("*DATABASE_FSI", conforming_keyword)
        self.assertNotIn("FSI computational overlap", conforming_keyword)
        self.assertIn("*ALE_SMOOTHING", conforming_keyword)
        self.assertRegex(
            conforming_keyword,
            r"\*ALE_SMOOTHING\n\d+,\d+,\d+,0,0,0,0",
        )
        self.assertIn(
            "*CONTROL_ALE\n-1,1,2,1.0,0.0,0.0,0.0,0.0",
            conforming_keyword,
        )
        self.assertIn(
            "conforming_ale_lagrange_interface",
            conforming_metadata["validation_capabilities"],
        )
        self.assertNotIn(
            "fsi_segment_interface",
            conforming_metadata["validation_capabilities"],
        )
        self.assertNotIn(
            "ale_fsi",
            conforming_metadata["validation_capabilities"],
        )
        self.assertEqual(
            conforming_metadata["phase15"]["fsi_coupling"]["solver_qualification"],
            "experimental_unqualified",
        )
        self.assertFalse(
            conforming_metadata["phase15"]["fsi_coupling"]["production_default"]
        )
        self.assertEqual(
            conforming_metadata["constraint_count"],
            1 + conforming_keyword.count("*ALE_SMOOTHING"),
        )

        immersed_keyword, immersed_metadata, _ = build_phase15_a1_keyword(
            "phase15_immersed_test",
            _inputs("immersed_clis"),
        )
        self.assertIn("*CONSTRAINED_LAGRANGE_IN_SOLID", immersed_keyword)
        self.assertIn("FSI computational overlap", immersed_keyword)
        self.assertNotIn("*ALE_SMOOTHING", immersed_keyword)
        self.assertIn(
            "*CONTROL_ALE\n-1,1,2,-1.0,0.0,0.0,0.0,0.0",
            immersed_keyword,
        )
        self.assertEqual(
            immersed_metadata["phase15"]["coupling_mode"],
            "immersed_clis",
        )
        self.assertEqual(
            immersed_metadata["phase15"]["fsi_coupling"]["overlap_layers"],
            2,
        )

    def test_tools_report_conforming_zero_overlap(self) -> None:
        prepared = tool_prepare_phase15_a1(
            {
                "consistency_mode": "mass_priority_adjust_length",
                "coupling_mode": "conforming_shared_nodes",
                "mesh_size_m": 0.01,
            }
        )
        self.assertTrue(prepared["ok"])
        self.assertEqual(
            prepared["fsi_coupling"]["mode"],
            "conforming_shared_nodes",
        )
        self.assertEqual(prepared["fsi_coupling"]["overlap_layers"], 0)
        self.assertEqual(prepared["fsi_coupling"]["overlap_depth_m"], 0.0)

        generated = tool_generate_phase15_a1(
            {
                "project_name": "phase15_conforming_dry_run",
                "consistency_mode": "mass_priority_adjust_length",
                "coupling_mode": "conforming_shared_nodes",
                "mesh_size_m": 0.01,
                "dry_run": True,
            }
        )
        self.assertTrue(generated["ok"])
        self.assertEqual(
            generated["metadata"]["phase15"]["coupling_mode"],
            "conforming_shared_nodes",
        )
        self.assertEqual(
            generated["metadata"]["phase15"]["fsi_coupling"]["overlap_layers"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
