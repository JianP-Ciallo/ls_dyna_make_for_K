import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from lsprepost_mcp.io import write_json
from lsprepost_mcp.keyword_checks import r12_ale_compatibility_issues

from lsprepost_mcp.ale_blast import (
    default_ale_blast_spec,
    default_tunnel_blast_spec,
    phase14_mesh_sensitivity_report,
)
from lsprepost_mcp.dyna_keyword import build_keyword
from lsprepost_mcp.preflight import preflight_model_spec
from lsprepost_mcp.schema import parse_model_spec
from lsprepost_mcp.tool_generation import (
    tool_generate_ale_blast_demo,
    tool_generate_tunnel_blast_demo,
    tunnel_blast_demo_input_schema,
)
from lsprepost_mcp.web.preview_mesh import build_preview_mesh


class Phase14CompleteBackendTests(unittest.TestCase):
    def test_r12_ale_compatibility_gate_accepts_current_generators(self) -> None:
        for raw in (
            default_ale_blast_spec("phase14_r12_plate"),
            default_tunnel_blast_spec("phase14_r12_tunnel"),
        ):
            keyword, _metadata = build_keyword(parse_model_spec(raw))
            self.assertEqual(r12_ale_compatibility_issues(keyword), [])

    def test_r12_ale_compatibility_gate_rejects_known_regressions(self) -> None:
        keyword, _metadata = build_keyword(
            parse_model_spec(default_tunnel_blast_spec("phase14_r12_bad"))
        )
        bad_keyword = keyword.replace(
            "*DATABASE_FSI\n",
            "*DATABASE_BINARY_FSIFOR\n2e-05\n*DATABASE_FSI\n",
            1,
        ).replace(
            "*DATABASE_ALE_MAT\n$#   dtout     npltc\n2e-05,0",
            "*DATABASE_ALE_MAT\n$#   dtout    boxlow     boxup\n2e-05,0,0",
            1,
        ).replace(
            "0.0,0.0,0.0,2,0.1,0,0,0\n*CONSTRAINED_LAGRANGE_IN_SOLID",
            "0.0,0.0,0.0,2,0.1,0,0,0\n0,0,1,0,0,0.0,0.0\n*CONSTRAINED_LAGRANGE_IN_SOLID",
            1,
        ).replace(
            "1.5,0,0,0.05197815",
            "1.5,0,0,0.051978151",
            1,
        )

        issue_ids = {issue["id"] for issue in r12_ale_compatibility_issues(bad_keyword)}
        self.assertEqual(
            issue_ids,
            {
                "database_binary_fsifor",
                "database_ale_mat_field_count",
                "constrained_lagrange_extended_data",
                "initial_volume_fraction_field_width",
            },
        )

    def test_default_phase14_spec_builds_full_mmale_keyword(self) -> None:
        spec = parse_model_spec(default_ale_blast_spec("phase14_contract"))
        keyword, metadata = build_keyword(spec)

        required = {
            "*CONTROL_ALE",
            "*ALE_MULTI-MATERIAL_GROUP",
            "*MAT_NULL",
            "*EOS_LINEAR_POLYNOMIAL",
            "*MAT_HIGH_EXPLOSIVE_BURN",
            "*EOS_JWL",
            "*INITIAL_VOLUME_FRACTION_GEOMETRY",
            "*INITIAL_DETONATION",
            "*SET_PART_LIST_TITLE",
            "*CONSTRAINED_LAGRANGE_IN_SOLID",
            "*BOUNDARY_NON_REFLECTING",
            "*DATABASE_FSI",
            "*DATABASE_NODOUT",
            "*DATABASE_HISTORY_NODE_SET",
        }
        for card in required:
            self.assertIn(card, keyword)
        self.assertNotIn("*DATABASE_BINARY_FSIFOR", keyword)
        self.assertNotIn("*LOAD_BLAST_ENHANCED", keyword)
        self.assertEqual(metadata["analysis_method"], "MM-ALE")
        self.assertTrue(metadata["shock_wave_visible_in_d3plot"])
        self.assertEqual(metadata["ale_material_groups"], 2)
        self.assertEqual(metadata["part_set_count"], 1)
        self.assertGreater(metadata["ale_solid_element_count"], 0)
        self.assertGreater(metadata["lagrangian_shell_element_count"], 0)
        self.assertEqual(metadata["node_set_count"], 2)
        self.assertGreater(len(metadata["components"][2]["response_node_ids"]), 0)

    def test_default_phase14_parts_link_air_and_explosive_eos(self) -> None:
        spec = parse_model_spec(default_ale_blast_spec("phase14_part_eos"))
        keyword, _metadata = build_keyword(spec)
        self.assertIn("1,1,1,1,0,0,0,0", keyword)
        self.assertIn("2,2,2,2,0,0,0,0", keyword)
        self.assertIn("3,3,3,0,0,0,0,0", keyword)
        self.assertIn("3,1,1,0,4,4,2,0", keyword)
        self.assertIn("*INITIAL_DETONATION\n$#     pid        x0        y0        z0        lt\n1,0,0,0.2,0.0", keyword)
        self.assertIn("0.0,0.0,0.1,0.0,0.3,0,0,0.1", keyword)
        self.assertIn("0.0,0.0,0.0,2,0.1,0,0,0", keyword)
        self.assertIn("100,0,0,0,0", keyword)
        volume_fraction_radius = keyword.split("$#      x0        y0        z0        r0\n", 1)[1].splitlines()[0].split(",")[3]
        self.assertLessEqual(len(volume_fraction_radius), 10)

    def test_phase14_geometry_rejects_charge_outside_domain(self) -> None:
        raw = default_ale_blast_spec("phase14_bad_charge")
        raw["geometry"]["explosive_center_m"] = [0.0, 0.0, 1.0]
        with self.assertRaisesRegex(ValueError, "explosive sphere must be inside"):
            parse_model_spec(raw)

    def test_phase14_geometry_rejects_under_resolved_charge(self) -> None:
        raw = default_ale_blast_spec("phase14_bad_resolution")
        raw["mesh"]["size_m"] = 0.03
        with self.assertRaisesRegex(ValueError, "at least 3 cells"):
            parse_model_spec(raw)

    def test_phase14_preflight_counts_ale_and_plate_mesh(self) -> None:
        spec = parse_model_spec(default_ale_blast_spec("phase14_preflight"))
        result = preflight_model_spec(spec)
        self.assertEqual(result["model_type"], "ale_blast_scene")
        self.assertGreater(result["node_count"], 70_000)
        self.assertLess(result["element_count"], result["limits"]["max_elements"])

    def test_phase14_mesh_sensitivity_is_a_plan_not_a_fake_result(self) -> None:
        spec = parse_model_spec(default_ale_blast_spec("phase14_sensitivity"))
        report = phase14_mesh_sensitivity_report(spec)

        self.assertEqual(
            [item["name"] for item in report["levels"]],
            ["coarse", "baseline", "fine", "refined"],
        )
        self.assertTrue(all(item["within_generation_limits"] for item in report["levels"]))
        self.assertGreater(report["levels"][0]["charge_diameter_cells"], 3.0)
        self.assertFalse(report["convergence_claimed"])
        self.assertEqual(report["solver_permission"], "explicit_user_approval_required")

    def test_phase14_tool_dry_run_exposes_safety_and_pressure_outputs(self) -> None:
        result = tool_generate_ale_blast_demo(
            {"project_name": "phase14_tool_contract", "dry_run": True}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "validated_only")
        self.assertEqual(result["model_type"], "ale_blast_scene")
        self.assertTrue(result["metadata"]["shock_wave_visible_in_d3plot"])
        self.assertEqual(result["solver_permission"], "explicit_user_approval_required")
        self.assertEqual(result["mesh_sensitivity"]["status"], "planned_not_solved")

    def test_phase14_browser_preview_marks_charge_and_hides_air_by_default(self) -> None:
        with TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "model.k").write_text(
                """*KEYWORD
*NODE
1,0,0,0
2,1,0,0
3,1,1,0
4,0,1,0
5,0,0,1
6,1,0,1
7,1,1,1
8,0,1,1
*ELEMENT_SOLID
1,1,1,2,3,4,5,6,7,8
*END
""",
                encoding="utf-8",
            )
            write_json(
                project / "model.json",
                {
                    "metadata": {
                        "ale_domain": {"part_id": 1},
                        "explosive": {
                            "center_m": [0.5, 0.5, 0.5],
                            "radius_m": 0.1,
                            "mass_kg": 0.2,
                        },
                        "components": [
                            {"id": "ale_air_domain", "part_id": 1},
                        ],
                    }
                },
            )
            preview = build_preview_mesh(project)

        self.assertEqual(preview["default_hidden_part_ids"], [1])
        self.assertEqual(preview["parts"][0]["name"], "ale_air_domain")
        self.assertEqual(preview["blast_sources"][0]["kind"], "ale_explosive_volume")
        self.assertEqual(preview["blast_sources"][0]["radius_m"], 0.1)

    def test_phase14_baseline_emits_staged_output_and_ale_balance_cards(self) -> None:
        spec = parse_model_spec(default_ale_blast_spec("phase14_output_contract"))
        keyword, metadata = build_keyword(spec)

        self.assertIn("*DEFINE_CURVE", keyword)
        self.assertIn("*DATABASE_ALE_MAT", keyword)
        self.assertIn("*DATABASE_ALE", keyword)
        self.assertNotIn("$#   iboxid   ipenchk   intforc", keyword)
        ale_mat_line = keyword.split("*DATABASE_ALE_MAT\n", 1)[1].splitlines()[1]
        self.assertEqual(len(ale_mat_line.split(",")), 2)
        self.assertTrue(metadata["phase14_static_readiness"]["ale_mass_balance_output"])
        self.assertTrue(metadata["phase14_static_readiness"]["air_pressure_probe_output"])
        self.assertEqual(metadata["d3plot_output"]["mode"], "staged")

    def test_open_tunnel_scene_has_required_geometry_and_only_open_end_boundaries(self) -> None:
        spec = parse_model_spec(default_tunnel_blast_spec("phase14_tunnel_contract"))
        keyword, metadata = build_keyword(spec)

        self.assertEqual(metadata["scene_variant"], "open_concrete_tunnel")
        self.assertEqual(metadata["tunnel"]["inside_dimensions_m"], [6.0, 4.0, 4.0])
        self.assertEqual(metadata["tunnel"]["open_ends"], ["x_min", "x_max"])
        self.assertEqual(metadata["explosive"]["center_m"], [1.5, 0.0, 0.0])
        self.assertEqual(metadata["target_plate"]["center_m"], [4.5, 0.0, 0.0])
        self.assertAlmostEqual(metadata["target_plate"]["standoff_m"], 3.0)
        self.assertEqual(
            metadata["ale_domain"]["outer_segment_count"],
            2 * metadata["ale_domain"]["cells"][1] * metadata["ale_domain"]["cells"][2],
        )
        self.assertEqual(metadata["part_count"], 4)
        self.assertEqual(metadata["coupling_count"], 2)
        self.assertIn("1,3,1\n2,4,1", keyword)
        self.assertIn("Open tunnel ends only", keyword)
        self.assertIn("Concrete tunnel walls", keyword)
        self.assertIn("Vertical coupled steel target plate", keyword)
        self.assertIn("*DATABASE_ALE_MAT", keyword)
        self.assertIn("*DATABASE_ALE", keyword)
        self.assertNotIn("$#   iboxid   ipenchk   intforc", keyword)
        volume_fraction_radius = keyword.split("*INITIAL_VOLUME_FRACTION_GEOMETRY\n", 1)[1].splitlines()[2].split(",")[3]
        self.assertLessEqual(len(volume_fraction_radius), 10)

    def test_open_tunnel_scene_uses_uniform_air_mesh_and_stays_inside_generation_limits(self) -> None:
        spec = parse_model_spec(default_tunnel_blast_spec("phase14_tunnel_mesh"))
        result = preflight_model_spec(spec)
        keyword, metadata = build_keyword(spec)

        self.assertLess(metadata["node_count"], result["limits"]["max_nodes"])
        self.assertLess(metadata["element_count"], result["limits"]["max_elements"])
        self.assertEqual(metadata["mesh"]["mode"], "uniform_air_mesh")
        self.assertEqual(metadata["mesh"]["requested_air_size_m"], 0.1)
        self.assertLess(metadata["mesh"]["charge_diameter_cells"], 3.0)
        self.assertTrue(metadata["mesh"]["charge_resolution_warning"])
        self.assertGreater(len(keyword), 1_000_000)

    def test_tunnel_tool_schema_exposes_parametric_geometry_and_uniform_mesh(self) -> None:
        properties = tunnel_blast_demo_input_schema()["properties"]

        for field in (
            "tunnel_length_m",
            "tunnel_width_m",
            "tunnel_height_m",
            "tunnel_wall_thickness_m",
            "air_mesh_size_m",
            "explosive_center_m",
            "plate_center_m",
            "plate_material_name",
        ):
            self.assertIn(field, properties)
        self.assertEqual(properties["air_mesh_size_m"]["enum"], [0.075, 0.1, 0.125, 0.15])
        self.assertEqual(
            properties["plate_material_name"]["enum"],
            ["mild_steel_mat24_demo", "mild_steel", "aluminum_6061_t6"],
        )

    def test_tunnel_tool_applies_dimensions_positions_material_and_air_domain(self) -> None:
        result = tool_generate_tunnel_blast_demo(
            {
                "project_name": "phase14_parametric_tunnel",
                "tunnel_length_m": 8.0,
                "tunnel_width_m": 5.0,
                "tunnel_height_m": 3.5,
                "tunnel_wall_thickness_m": 0.3,
                "air_mesh_size_m": 0.125,
                "explosive_center_m": [2.0, 0.4, 0.2],
                "plate_center_m": [6.0, -0.3, 0.1],
                "plate_material_name": "aluminum_6061_t6",
                "dry_run": True,
            }
        )

        metadata = result["metadata"]
        self.assertEqual(metadata["ale_domain"]["bounds_m"]["min"], [0.0, -2.5, -1.75])
        self.assertEqual(metadata["ale_domain"]["bounds_m"]["max"], [8.0, 2.5, 1.75])
        self.assertEqual(metadata["explosive"]["center_m"], [2.0, 0.4, 0.2])
        self.assertEqual(metadata["target_plate"]["center_m"], [6.0, -0.3, 0.1])
        self.assertEqual(metadata["target_plate"]["material"], "aluminum_6061_t6")
        self.assertEqual(metadata["tunnel"]["wall_thickness_m"], 0.3)
        self.assertEqual(metadata["mesh"]["requested_air_size_m"], 0.125)
        self.assertLess(result["mesh_estimate"]["element_count"], 350_000)

    def test_tunnel_tool_rejects_unlisted_uniform_air_mesh(self) -> None:
        with self.assertRaisesRegex(ValueError, "air mesh size must be one of"):
            tool_generate_tunnel_blast_demo(
                {"project_name": "phase14_bad_uniform_mesh", "air_mesh_size_m": 0.08, "dry_run": True}
            )

    def test_tunnel_geometry_rejects_plate_outside_cross_section(self) -> None:
        with self.assertRaisesRegex(ValueError, "plate must fit inside"):
            tool_generate_tunnel_blast_demo(
                {
                    "project_name": "phase14_bad_plate_position",
                    "plate_center_m": [4.5, 1.7, 0.0],
                    "dry_run": True,
                }
            )

    def test_tunnel_tool_rejects_uniform_mesh_over_generation_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "safe generation limits"):
            tool_generate_tunnel_blast_demo(
                {
                    "project_name": "phase14_oversize_uniform_mesh",
                    "tunnel_length_m": 12.0,
                    "tunnel_width_m": 8.0,
                    "tunnel_height_m": 8.0,
                    "air_mesh_size_m": 0.075,
                    "explosive_center_m": [2.0, 0.0, 0.0],
                    "plate_center_m": [9.0, 0.0, 0.0],
                    "dry_run": True,
                }
            )

    def test_open_tunnel_tool_dry_run_never_claims_solver_execution(self) -> None:
        result = tool_generate_tunnel_blast_demo(
            {"project_name": "phase14_tunnel_tool", "dry_run": True}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "validated_only")
        self.assertEqual(result["scene_variant"], "open_concrete_tunnel")
        self.assertEqual(result["solver_permission"], "explicit_user_approval_required")
        self.assertNotIn("solver_result", result)


if __name__ == "__main__":
    unittest.main()
