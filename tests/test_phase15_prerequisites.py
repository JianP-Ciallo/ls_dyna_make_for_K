import math
import unittest

from lsprepost_mcp.dyna_keyword import build_keyword
from lsprepost_mcp.keyword_checks import r12_kc_automatic_issues
from lsprepost_mcp.phase15 import (
    build_axisymmetric_grid,
    compile_phase15_a1_mesh_plan,
    compile_axisymmetric_quad_mesh,
    default_phase15_a1_inputs,
    derive_phase15_a1_geometry,
    resolve_phase15_coupling_mode,
    resolve_tnt_consistency,
    validate_phase15_a1_mesh_plan,
)
from lsprepost_mcp.schema import default_model_spec, parse_model_spec
from lsprepost_mcp.tool_generation import phase15_a1_input_schema, tool_prepare_phase15_a1
from lsprepost_mcp.tools import TOOLS


class Phase15PrerequisiteTests(unittest.TestCase):
    def test_coupling_mode_resolution_defaults_new_and_legacy_records_correctly(self) -> None:
        self.assertEqual(
            resolve_phase15_coupling_mode({"coupling_mode": "conforming_shared_nodes"}),
            "conforming_shared_nodes",
        )
        self.assertEqual(
            resolve_phase15_coupling_mode({"coupling_mode": "immersed_clis"}),
            "immersed_clis",
        )
        self.assertEqual(
            resolve_phase15_coupling_mode({"coupling_mode": "conforming_air_gap"}),
            "conforming_air_gap",
        )
        self.assertEqual(
            resolve_phase15_coupling_mode({}, legacy_default=True),
            "immersed_clis",
        )
        self.assertEqual(
            resolve_phase15_coupling_mode({}),
            "immersed_clis",
        )
        with self.assertRaisesRegex(ValueError, "coupling_mode"):
            resolve_phase15_coupling_mode({"coupling_mode": "unknown"})

    def test_default_a1_inputs_expose_unresolved_tnt_mass_conflict(self) -> None:
        inputs = default_phase15_a1_inputs()

        self.assertEqual(inputs["consistency_mode"], "needs_confirmation")
        self.assertEqual(inputs["coupling_mode"], "immersed_clis")
        result = resolve_tnt_consistency(inputs)

        self.assertTrue(result["needs_confirmation"])
        self.assertAlmostEqual(result["geometric_mass_kg"], 6.7622671913, places=8)
        self.assertGreater(result["relative_mass_error"], 0.05)
        self.assertEqual(
            set(result["available_modes"]),
            {"mass_priority_adjust_length", "geometry_priority", "mass_priority_adjust_density"},
        )

    def test_tnt_mass_priority_computes_traceable_effective_length(self) -> None:
        inputs = default_phase15_a1_inputs()
        inputs["consistency_mode"] = "mass_priority_adjust_length"

        result = resolve_tnt_consistency(inputs)

        self.assertFalse(result["needs_confirmation"])
        self.assertAlmostEqual(result["effective_length_m"], 0.5205354803, places=8)
        self.assertAlmostEqual(result["effective_mass_kg"], 6.4, places=10)
        self.assertEqual(result["provenance"]["decision"], "mass_priority_adjust_length")

    def test_tnt_density_adjustment_outside_controlled_range_still_needs_confirmation(self) -> None:
        inputs = default_phase15_a1_inputs()
        inputs["consistency_mode"] = "mass_priority_adjust_density"

        result = resolve_tnt_consistency(inputs)

        self.assertTrue(result["needs_confirmation"])
        self.assertEqual(result["reason"], "effective TNT density is outside the controlled range")
        self.assertLess(result["effective_density_kg_per_m3"], 1550.0)

    def test_axisymmetric_grid_starts_on_axis_and_preserves_revolved_volume(self) -> None:
        grid = build_axisymmetric_grid(radius_m=0.12, height_m=0.18, mesh_size_m=0.03)

        self.assertEqual(grid["radial_coordinates_m"][0], 0.0)
        self.assertTrue(all(value >= 0.0 for value in grid["radial_coordinates_m"]))
        self.assertEqual(grid["radial_cells"], 4)
        self.assertEqual(grid["axial_cells"], 6)
        self.assertAlmostEqual(
            grid["revolved_volume_m3"],
            math.pi * 0.12**2 * 0.18,
            places=12,
        )

    def test_axisymmetric_quad_mesh_has_positive_area_and_named_boundaries(self) -> None:
        mesh = compile_axisymmetric_quad_mesh(radius_m=0.12, height_m=0.18, mesh_size_m=0.03)

        self.assertEqual(len(mesh["nodes"]), 35)
        self.assertEqual(len(mesh["elements"]), 24)
        self.assertEqual(len(mesh["boundaries"]["axis"]), 7)
        self.assertEqual(len(mesh["boundaries"]["outer_radius"]), 7)
        self.assertEqual(len(mesh["boundaries"]["bottom"]), 5)
        self.assertEqual(len(mesh["boundaries"]["top"]), 5)
        nodes = {node[0]: node[1:] for node in mesh["nodes"]}
        for _element_id, _part_id, n1, n2, n3, n4 in mesh["elements"]:
            coordinates = [nodes[node_id] for node_id in (n1, n2, n3, n4)]
            signed_area = 0.5 * sum(
                coordinates[index][0] * coordinates[(index + 1) % 4][1]
                - coordinates[(index + 1) % 4][0] * coordinates[index][1]
                for index in range(4)
            )
            self.assertGreater(signed_area, 0.0)

    def test_kc_automatic_material_emits_r12_unit_conversion_card(self) -> None:
        raw = default_model_spec("phase15_kc_auto", "single_solid_element_test")
        raw["material"] = {
            "name": "kc_cf120_demo_auto",
            "type": "concrete_damage_rel3",
            "parameter_mode": "automatic",
            "density_kg_per_m3": 2480.0,
            "poisson": 0.2,
            "fpc_pa": 133.5e6,
            "rsize_in_per_user_length": 39.37,
            "ucf_psi_per_user_stress": 1.4503773773e-4,
            "lcrate": -1,
            "source": "Phase 15 A-1 source plus LS-DYNA R12 automatic parameter generation",
            "confirmed_by_user": True,
            "validation_status": "demo_unvalidated",
        }
        raw["boundary_conditions"] = [
            {"type": "spc_node_set", "node_ids": [1], "dofs": ["x", "y", "z"]}
        ]

        keyword, _metadata = build_keyword(parse_model_spec(raw))

        self.assertIn("*MAT_CONCRETE_DAMAGE_REL3", keyword)
        self.assertIn("-133500000", keyword)
        self.assertIn("39.37", keyword)
        self.assertIn("0.00014503773773", keyword)
        self.assertIn(",-1,", keyword)
        material_block = keyword.split("*MAT_CONCRETE_DAMAGE_REL3\n", 1)[1].split("*", 1)[0]
        data_lines = [
            line
            for line in material_block.splitlines()
            if line and not line.startswith("$")
        ]
        self.assertEqual(len(data_lines), 7)
        self.assertEqual(r12_kc_automatic_issues(keyword), [])

    def test_kc_r12_gate_rejects_auto_rate_without_any_curve_table(self) -> None:
        keyword = """*KEYWORD
*MAT_CONCRETE_DAMAGE_REL3
1,2480,0.2
,-133500000,,,,,
,2,,39.37,0.00014504,-1,,
,,,,,,,
,,,,,,,
,,,,,,,
,,,,,,,
*END
"""

        issue_ids = {item["id"] for item in r12_kc_automatic_issues(keyword)}

        self.assertEqual(issue_ids, {"kc_automatic_curve_table_missing"})

    def test_kc_r12_gate_rejects_undefined_positive_rate_curve(self) -> None:
        keyword = """*KEYWORD
*MAT_CONCRETE_DAMAGE_REL3
1,2480,0.2
,-133500000,,,,,
,2,,39.37,0.00014504,42,,
,,,,,,,
,,,,,,,
,,,,,,,
,,,,,,,
*DEFINE_CURVE
41,0,1,1,0,0,0,0
0,0
1,1
*END
"""

        issue_ids = {item["id"] for item in r12_kc_automatic_issues(keyword)}

        self.assertEqual(issue_ids, {"kc_rate_curve_missing"})

    def test_kc_r12_gate_accepts_defined_positive_rate_curve(self) -> None:
        keyword = """*KEYWORD
*MAT_CONCRETE_DAMAGE_REL3
1,2480,0.2
,-133500000,,,,,
,2,,39.37,0.00014504,42,,
,,,,,,,
,,,,,,,
,,,,,,,
,,,,,,,
*DEFINE_CURVE_TITLE
K&C rate curve
42,0,1,1,0,0,0,0
0,0
1,1
*END
"""

        self.assertEqual([], r12_kc_automatic_issues(keyword))

    def test_kc_r12_gate_rejects_unsupported_negative_rate_curve(self) -> None:
        keyword = """*KEYWORD
*MAT_CONCRETE_DAMAGE_REL3
1,2480,0.2
,-133500000,,,,,
,2,,39.37,0.00014504,-2,,
,,,,,,,
,,,,,,,
,,,,,,,
,,,,,,,
*DEFINE_CURVE
41,0,1,1,0,0,0,0
0,0
1,1
*END
"""

        issue_ids = {item["id"] for item in r12_kc_automatic_issues(keyword)}

        self.assertEqual(issue_ids, {"kc_automatic_conversion_values"})

    def test_kc_r12_gate_rejects_missing_conversion_card(self) -> None:
        keyword = """*KEYWORD
*MAT_CONCRETE_DAMAGE_REL3
1,2480,0.2
,-133500000,,,,,
*END
"""

        issue_ids = {item["id"] for item in r12_kc_automatic_issues(keyword)}
        self.assertEqual(issue_ids, {"kc_automatic_card_count"})

    def test_kc_automatic_material_rejects_manual_strength_surface_mix(self) -> None:
        raw = default_model_spec("phase15_kc_bad_mix", "single_solid_element_test")
        raw["material"] = {
            "name": "kc_bad_mix",
            "type": "concrete_damage_rel3",
            "parameter_mode": "automatic",
            "density_kg_per_m3": 2480.0,
            "poisson": 0.2,
            "fpc_pa": 133.5e6,
            "a1": 0.1,
            "source": "unit test",
            "confirmed_by_user": True,
        }

        with self.assertRaisesRegex(ValueError, "automatic.*manual"):
            parse_model_spec(raw)

    def test_kc_automatic_material_rejects_unsupported_negative_rate_curve(self) -> None:
        raw = default_model_spec("phase15_kc_bad_lcrate", "single_solid_element_test")
        raw["material"] = {
            "name": "kc_bad_lcrate",
            "type": "concrete_damage_rel3",
            "parameter_mode": "automatic",
            "density_kg_per_m3": 2480.0,
            "poisson": 0.2,
            "fpc_pa": 133.5e6,
            "lcrate": -2,
            "source": "unit test",
            "confirmed_by_user": True,
        }

        with self.assertRaisesRegex(ValueError, "lcrate must be -1 or a positive"):
            parse_model_spec(raw)

    def test_phase15_preparation_tool_requires_an_explicit_mass_decision(self) -> None:
        result = tool_prepare_phase15_a1({})

        self.assertFalse(result["ok"])
        self.assertTrue(result["needs_confirmation"])
        self.assertFalse(result["generation_available"])
        self.assertEqual(result["solver_permission"], "explicit_user_approval_required")

    def test_phase15_preparation_rejects_invalid_overlap_before_mass_confirmation(self) -> None:
        with self.assertRaisesRegex(ValueError, "fsi_overlap_layers"):
            tool_prepare_phase15_a1(
                {"coupling_mode": "immersed_clis", "fsi_overlap_layers": "2"}
            )

    def test_phase15_preparation_rejects_overlap_for_conforming_mode(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "fsi_overlap_layers is only valid for immersed_clis"
        ):
            tool_prepare_phase15_a1(
                {
                    "coupling_mode": "conforming_shared_nodes",
                    "fsi_overlap_layers": 2,
                }
            )

    def test_phase15_preparation_tool_reports_axisymmetric_resource_estimate(self) -> None:
        result = tool_prepare_phase15_a1(
            {
                "consistency_mode": "mass_priority_adjust_length",
                "mesh_size_m": 0.006,
                "coupling_mode": "immersed_clis",
                "fsi_overlap_layers": 3,
            }
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["needs_confirmation"])
        self.assertTrue(result["ready_for_axisymmetric_compiler"])
        self.assertGreater(result["axisymmetric_target_mesh"]["element_count"], 30000)
        self.assertEqual(3, result["fsi_coupling"]["overlap_layers"])
        self.assertAlmostEqual(0.018, result["fsi_coupling"]["overlap_depth_m"])
        self.assertEqual(
            "computational_overlap_not_physical_air_thickness",
            result["fsi_coupling"]["physical_meaning"],
        )
        self.assertTrue(result["generation_available"])

    def test_phase15_preparation_tool_has_a_strict_public_schema(self) -> None:
        schema = phase15_a1_input_schema()

        self.assertFalse(schema["additionalProperties"])
        self.assertIn("needs_confirmation", schema["properties"]["consistency_mode"]["enum"])
        self.assertEqual(
            ["conforming_shared_nodes", "conforming_air_gap", "immersed_clis"],
            schema["properties"]["coupling_mode"]["enum"],
        )
        self.assertEqual(
            "immersed_clis",
            schema["properties"]["coupling_mode"]["default"],
        )
        self.assertEqual([1, 2, 3], schema["properties"]["fsi_overlap_layers"]["enum"])
        self.assertEqual(0.073, schema["properties"]["borehole_radius_m"]["default"])
        self.assertEqual(0.024, schema["properties"]["bottom_air_gap_m"]["default"])
        self.assertIn("prepare_phase15_a1", TOOLS)

    def test_a1_geometry_uses_the_resolved_charge_length_and_fixed_depth_convention(self) -> None:
        inputs = default_phase15_a1_inputs()
        inputs["consistency_mode"] = "mass_priority_adjust_length"

        geometry = derive_phase15_a1_geometry(inputs)

        self.assertEqual(geometry["coordinate_system"], "axisymmetric_r_z")
        self.assertEqual(geometry["depth_origin"], "target_top_positive_down")
        self.assertAlmostEqual(geometry["charge_bottom_z_m"], 0.54, places=12)
        self.assertAlmostEqual(geometry["charge_length_m"], 0.5205354803, places=8)
        self.assertAlmostEqual(
            geometry["charge_top_z_m"] - geometry["charge_bottom_z_m"],
            geometry["charge_length_m"],
            places=12,
        )
        self.assertAlmostEqual(geometry["air_top_z_m"], 1.7, places=12)
        self.assertAlmostEqual(geometry["steel_outer_radius_m"], 1.06, places=12)

    def test_a1_region_meshes_are_non_overlapping_and_preserve_the_borehole(self) -> None:
        inputs = default_phase15_a1_inputs()
        inputs["consistency_mode"] = "mass_priority_adjust_length"
        inputs["mesh_size_m"] = 0.01
        inputs["coupling_mode"] = "immersed_clis"

        plan = compile_phase15_a1_mesh_plan(inputs)

        self.assertEqual(set(plan["regions"]), {"concrete", "tnt", "air", "steel_hoop"})
        geometry = plan["geometry"]
        concrete = plan["regions"]["concrete"]
        concrete_nodes = {node[0]: node[1:] for node in concrete["nodes"]}
        for _eid, _pid, n1, n2, n3, n4 in concrete["elements"]:
            coordinates = [concrete_nodes[node_id] for node_id in (n1, n2, n3, n4)]
            center_r = sum(item[0] for item in coordinates) / 4.0
            center_z = sum(item[1] for item in coordinates) / 4.0
            in_bore_or_charge = (
                center_r < geometry["charge_radius_m"]
                and center_z > geometry["charge_bottom_z_m"]
            )
            self.assertFalse(in_bore_or_charge)

        air = plan["regions"]["air"]
        air_nodes = {node[0]: node[1:] for node in air["nodes"]}
        self.assertTrue(
            any(
                sum(air_nodes[node_id][1] for node_id in element[2:]) / 4.0
                < geometry["target_top_z_m"]
                for element in air["elements"]
            )
        )

    def test_a1_mesh_interfaces_match_and_static_quality_gate_passes(self) -> None:
        inputs = default_phase15_a1_inputs()
        inputs["consistency_mode"] = "mass_priority_adjust_length"
        inputs["mesh_size_m"] = 0.01
        inputs["coupling_mode"] = "immersed_clis"

        plan = compile_phase15_a1_mesh_plan(inputs)

        self.assertEqual(validate_phase15_a1_mesh_plan(plan), [])
        interfaces = plan["interfaces"]
        self.assertGreater(interfaces["tnt_to_concrete"]["matched_node_count"], 0)
        self.assertGreater(interfaces["air_to_concrete"]["matched_node_count"], 0)
        self.assertGreater(interfaces["concrete_to_steel"]["matched_node_count"], 0)
        self.assertTrue(all(item["coordinates_match"] for item in interfaces.values()))

    def test_prepare_reports_four_region_axisymmetric_mesh_and_enables_generation(self) -> None:
        result = tool_prepare_phase15_a1(
            {
                "consistency_mode": "mass_priority_adjust_length",
                "mesh_size_m": 0.01,
                "coupling_mode": "immersed_clis",
            }
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["ready_for_axisymmetric_compiler"])
        self.assertEqual(
            set(result["axisymmetric_region_mesh"]["regions"]),
            {"concrete", "tnt", "air", "steel_hoop"},
        )
        self.assertEqual(result["axisymmetric_region_mesh"]["quality_issue_count"], 0)
        self.assertTrue(result["generation_available"])
        self.assertIsNone(result["reason_generation_is_disabled"])


if __name__ == "__main__":
    unittest.main()
