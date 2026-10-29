from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from lsprepost_mcp.phase15 import default_phase15_a1_inputs
from lsprepost_mcp.phase15_keyword import (
    ALE_PART_SET_ID,
    FSI_ALL_CONCRETE_ALE_SET_ID,
    FSI_TNT_AMMG_SET_ID,
    build_phase15_a1_keyword,
    compile_phase15_a1_solver_model,
    default_phase15_output,
    phase15_sensitivity_matrix,
    validate_phase15_a1_solver_model,
)
from lsprepost_mcp.keyword_checks import keyword_quality_checks
from lsprepost_mcp.project_store import validate_project_files
from lsprepost_mcp.tool_generation import (
    phase15_a1_generate_input_schema,
    tool_generate_phase15_a1,
)
from lsprepost_mcp.tools import TOOLS


class Phase15KeywordTests(unittest.TestCase):
    def resolved_inputs(self):
        raw = default_phase15_a1_inputs()
        raw["consistency_mode"] = "mass_priority_adjust_length"
        raw["coupling_mode"] = "immersed_clis"
        return raw

    def test_solver_mesh_has_shared_ale_and_bonded_steel(self):
        model = compile_phase15_a1_solver_model(self.resolved_inputs())
        self.assertEqual([], validate_phase15_a1_solver_model(model))
        self.assertGreater(model["counts"]["ale_elements"], 0)
        self.assertGreater(model["counts"]["concrete_elements"], 0)
        self.assertGreater(model["counts"]["steel_elements"], 0)
        self.assertEqual(0, model["counts"]["tnt_elements"])
        self.assertTrue(model["interfaces"]["tnt_is_volume_fraction"])
        self.assertTrue(model["interfaces"]["concrete_steel_shared_nodes"])
        self.assertTrue(model["boundaries"]["nonreflecting_2d_node_ids"])
        surfaces = model["interfaces"]["fsi_surfaces"]
        self.assertGreater(surfaces["counts"]["charge_bottom"], 0)
        self.assertGreater(surfaces["counts"]["borehole_wall"], 0)
        self.assertGreater(surfaces["counts"]["concrete_top"], 0)
        self.assertEqual(
            surfaces["total_count"],
            sum(surfaces["counts"].values()),
        )

    def test_probe_coordinates_are_traceable(self):
        model = compile_phase15_a1_solver_model(self.resolved_inputs())
        probes = model["probes"]["concrete"]
        self.assertEqual(
            ["FSI_BOTTOM", "FSI_WALL", "FSI_TOP", "P1", "P2", "P3"],
            [probe["id"] for probe in probes],
        )
        self.assertEqual(
            ["charge_bottom", "borehole_wall", "concrete_top"],
            [probe["surface"] for probe in probes[:3]],
        )
        self.assertEqual(
            [1.26, 1.31, 1.36],
            [probe["depth_from_top_m"] for probe in probes[3:]],
        )
        self.assertTrue(all(probe["element_id"] > 0 for probe in probes))
        self.assertTrue(all(probe["node_id"] > 0 for probe in probes))

    def test_every_fsi_surface_has_two_sided_ale_overlap(self):
        model = compile_phase15_a1_solver_model(self.resolved_inputs())
        overlap = model["interfaces"]["fsi_ale_overlap"]

        self.assertEqual(2, overlap["overlap_layers"])
        self.assertAlmostEqual(0.012, overlap["overlap_depth_m"])
        self.assertTrue(overlap["all_two_sided"])
        for surface_name in ("charge_bottom", "borehole_wall", "concrete_top"):
            surface = overlap["surfaces"][surface_name]
            self.assertGreater(surface["segment_count"], 0, surface_name)
            self.assertEqual(
                surface["segment_count"],
                surface["two_sided_segment_count"],
                surface_name,
            )
            self.assertTrue(surface["all_two_sided"], surface_name)

    def test_fsi_overlap_layers_are_configurable_and_used_by_validation(self):
        for layers in (1, 3):
            inputs = self.resolved_inputs()
            inputs["fsi_overlap_layers"] = layers

            model = compile_phase15_a1_solver_model(inputs)
            overlap = model["interfaces"]["fsi_ale_overlap"]

            self.assertEqual(layers, overlap["overlap_layers"])
            self.assertAlmostEqual(
                layers * float(inputs["mesh_size_m"]),
                overlap["overlap_depth_m"],
            )
            self.assertTrue(overlap["all_two_sided"])
            self.assertEqual([], validate_phase15_a1_solver_model(model))

    def test_fsi_overlap_layers_reject_invalid_values(self):
        for invalid in (0, 4, True, 2.0, "2"):
            inputs = self.resolved_inputs()
            inputs["fsi_overlap_layers"] = invalid
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "fsi_overlap_layers"):
                    compile_phase15_a1_solver_model(inputs)

    def test_validation_rejects_inconsistent_fsi_overlap_metadata(self):
        model = compile_phase15_a1_solver_model(self.resolved_inputs())
        model["interfaces"]["fsi_coupling"]["overlap_layers"] = 1

        issue_ids = {issue["id"] for issue in validate_phase15_a1_solver_model(model)}

        self.assertIn("fsi_overlap_record_mismatch", issue_ids)

    def test_validation_reports_malformed_fsi_overlap_metadata(self):
        model = compile_phase15_a1_solver_model(self.resolved_inputs())
        model["interfaces"]["fsi_ale_overlap"]["overlap_depth_m"] = "invalid"

        issue_ids = {issue["id"] for issue in validate_phase15_a1_solver_model(model)}

        self.assertIn("fsi_overlap_record_mismatch", issue_ids)

    def test_keyword_contains_axisymmetric_ale_fsi_and_outputs(self):
        keyword, metadata, spec = build_phase15_a1_keyword(
            "phase15_keyword_test", self.resolved_inputs()
        )
        for card in (
            "*SECTION_ALE2D",
            "*ELEMENT_SHELL",
            "*MAT_CONCRETE_DAMAGE_REL3",
            "*INITIAL_VOLUME_FRACTION_GEOMETRY",
            "*INITIAL_DETONATION",
            "*CONSTRAINED_LAGRANGE_IN_SOLID",
            "*BOUNDARY_NON_REFLECTING_2D",
            "*DATABASE_BINARY_D3PLOT",
            "*DATABASE_ALE_MAT",
            "*DATABASE_FSI",
            "*DATABASE_HISTORY_SHELL_SET",
            "*DATABASE_HISTORY_NODE_SET",
            "*DATABASE_GLSTAT",
            "*DATABASE_MATSUM",
        ):
            self.assertIn(card, keyword)
        self.assertEqual("phase15_axisymmetric_blast", spec["model_type"])
        self.assertEqual("MM-ALE 2D axisymmetric", metadata["analysis_method"])
        self.assertEqual([], metadata["static_readiness"]["issues"])
        self.assertEqual(1, keyword.count("*END"))

    def test_conforming_air_gap_mesh_evidence_is_persisted(self):
        inputs = self.resolved_inputs()
        inputs["coupling_mode"] = "conforming_air_gap"
        inputs.pop("fsi_overlap_layers")

        model = compile_phase15_a1_solver_model(inputs)
        _keyword, metadata, _spec = build_phase15_a1_keyword(
            "phase15_conforming_gap_evidence",
            inputs,
        )

        self.assertEqual(
            model["phase15_air_gap"],
            metadata["phase15"]["phase15_air_gap"],
        )
        self.assertGreaterEqual(
            metadata["phase15"]["phase15_air_gap"]["side_air_gap_cells"],
            3,
        )
        self.assertGreaterEqual(
            metadata["phase15"]["phase15_air_gap"]["bottom_air_gap_cells"],
            3,
        )

    def test_phase15_solver_draft_has_conservative_timestep_but_remains_uncalibrated(self):
        inputs = self.resolved_inputs()
        inputs["coupling_mode"] = "conforming_air_gap"
        inputs.pop("fsi_overlap_layers")
        keyword, metadata, spec = build_phase15_a1_keyword(
            "phase15_conforming_readiness",
            inputs,
        )

        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            (project / "model.k").write_text(keyword, encoding="utf-8")
            (project / "model.json").write_text(
                json.dumps(
                    {
                        "schema_version": "0.2.0",
                        "spec": spec,
                        "metadata": metadata,
                    }
                ),
                encoding="utf-8",
            )
            checks = validate_project_files(project)

        by_id = {item["id"]: item for item in checks["checks"]}
        self.assertTrue(
            by_id["quality.estimate.stable_timestep"]["ok"],
            by_id["quality.estimate.stable_timestep"],
        )
        self.assertTrue(checks["readiness"]["ok_for_solver_draft"], checks)
        self.assertFalse(checks["readiness"]["ok_for_production_review"])
        self.assertIn(
            "K&C automatic parameters are a workflow reference",
            "\n".join(checks["warnings"]),
        )

    def test_keyword_uses_explicit_two_node_fsi_segment_sets(self):
        keyword, _metadata, _spec = build_phase15_a1_keyword(
            "phase15_fsi_segments", self.resolved_inputs()
        )
        lines = keyword.splitlines()

        self.assertEqual(3, lines.count("*SET_SEGMENT_TITLE"))
        self.assertIn("Phase15 FSI charge bottom", lines)
        self.assertIn("Phase15 FSI borehole wall", lines)
        self.assertIn("Phase15 FSI concrete top", lines)

        self.assertIn("*SET_SEGMENT_ADD", lines)
        self.assertIn("*SET_MULTI-MATERIAL_GROUP_LIST", lines)
        mmg_index = lines.index("*SET_MULTI-MATERIAL_GROUP_LIST")
        self.assertEqual(str(FSI_TNT_AMMG_SET_ID), lines[mmg_index + 2])
        self.assertEqual("2", lines[mmg_index + 4])
        coupling = (
            f"{FSI_ALL_CONCRETE_ALE_SET_ID},{ALE_PART_SET_ID},2,0,4,4,2,"
            f"{-FSI_TNT_AMMG_SET_ID}"
        )
        self.assertIn(coupling, lines)
        self.assertNotIn(f"3,{ALE_PART_SET_ID},1,0,4,4,2,1", lines)

        for index, line in enumerate(lines):
            if line != "*SET_SEGMENT_TITLE":
                continue
            cursor = index + 1
            data_rows = []
            while cursor < len(lines) and not lines[cursor].startswith("*"):
                if (
                    cursor > index + 2
                    and lines[cursor]
                    and not lines[cursor].startswith("$")
                ):
                    data_rows.append(lines[cursor])
                cursor += 1
            self.assertGreater(len(data_rows), 1)
            for row in data_rows[1:]:
                fields = row.split(",")
                self.assertEqual(2, len(fields), row)
                self.assertTrue(all(int(value) > 0 for value in fields), row)

    def test_phase15_quality_checks_resolve_composite_two_node_fsi_set(self):
        keyword, metadata, spec = build_phase15_a1_keyword(
            "phase15_quality_fsi_segments", self.resolved_inputs()
        )
        checks = keyword_quality_checks(keyword, spec, metadata)
        by_id = {item["id"]: item for item in checks}
        self.assertTrue(by_id["quality.ref.fsi_slave_segment_sets"]["ok"])
        self.assertTrue(by_id["quality.ref.fsi_slave_segment_sets_nonempty"]["ok"])
        self.assertTrue(by_id["quality.ref.segment_set_add_members"]["ok"])
        self.assertTrue(by_id["quality.topology.segment_sets_on_faces"]["ok"])
        self.assertTrue(by_id["quality.r12_kc.automatic_card"]["ok"])

    def test_axisymmetric_tnt_volume_fraction_uses_clockwise_quadrangle(self):
        keyword, metadata, _spec = build_phase15_a1_keyword(
            "phase15_volume_fraction", self.resolved_inputs()
        )
        lines = keyword.splitlines()
        index = lines.index("*INITIAL_VOLUME_FRACTION_GEOMETRY")
        data = []
        for line in lines[index + 1 :]:
            if line.startswith("*"):
                break
            if line and not line.startswith("$"):
                data.append(line)

        self.assertEqual(3, len(data))
        fields = data[2].split(",")
        self.assertEqual(8, len(fields))
        self.assertTrue(all(len(field) <= 10 for field in fields))

        geometry = metadata["phase15"]["geometry"]
        bottom = float(geometry["charge_bottom_z_m"])
        top = float(geometry["charge_top_z_m"])
        radius = float(geometry["charge_radius_m"])
        expected = [0.0, bottom, 0.0, top, radius, top, radius, bottom]
        for actual, target in zip((float(field) for field in fields), expected):
            self.assertAlmostEqual(target, actual, places=8)

    def test_output_ranges_are_controlled(self):
        output = default_phase15_output()
        self.assertEqual(0.0002, output["end_time_s"])
        compile_phase15_a1_solver_model(self.resolved_inputs(), output=output)

        output["end_time_s"] = 0.0
        with self.assertRaisesRegex(ValueError, "end_time_s"):
            compile_phase15_a1_solver_model(self.resolved_inputs(), output=output)

    def test_sensitivity_matrix_covers_mesh_and_erosion(self):
        matrix = phase15_sensitivity_matrix()
        self.assertEqual(6, len(matrix))
        self.assertEqual({0.004, 0.006, 0.008}, {case["mesh_size_m"] for case in matrix})
        self.assertEqual({"off", "standard_observation"}, {case["erosion_mode"] for case in matrix})
        self.assertTrue(all(case["solver_permission"] == "explicit_user_approval_required" for case in matrix))

    def test_generate_tool_dry_run_compiles_without_writing_or_solving(self):
        result = tool_generate_phase15_a1(
            {
                "project_name": "phase15_dry_run_test",
                "consistency_mode": "mass_priority_adjust_length",
                "mesh_size_m": 0.01,
                "coupling_mode": "immersed_clis",
                "dry_run": True,
            }
        )
        self.assertTrue(result["ok"])
        self.assertEqual("validated_only", result["status"])
        self.assertEqual("explicit_user_approval_required", result["solver_permission"])
        self.assertGreater(result["keyword_size_bytes"], 1000)
        self.assertNotIn("project_dir", result)

    def test_generate_tool_rejects_overlap_for_conforming_mode(self):
        with self.assertRaisesRegex(
            ValueError, "fsi_overlap_layers is only valid for immersed_clis"
        ):
            tool_generate_phase15_a1(
                {
                    "consistency_mode": "mass_priority_adjust_length",
                    "coupling_mode": "conforming_shared_nodes",
                    "fsi_overlap_layers": 2,
                    "dry_run": True,
                }
            )

    def test_generate_tool_schema_is_strict_and_registered(self):
        schema = phase15_a1_generate_input_schema()
        self.assertFalse(schema["additionalProperties"])
        self.assertIn("generate_phase15_a1", TOOLS)
        self.assertEqual("off", schema["properties"]["erosion_mode"]["default"])
        self.assertEqual(0.0002, schema["properties"]["end_time_s"]["minimum"])
        self.assertEqual(0.0002, schema["properties"]["end_time_s"]["default"])
        self.assertEqual(
            [1, 2, 3],
            schema["properties"]["fsi_overlap_layers"]["enum"],
        )
        self.assertEqual(2, schema["properties"]["fsi_overlap_layers"]["default"])
        self.assertEqual(
            ["conforming_shared_nodes", "conforming_air_gap", "immersed_clis"],
            schema["properties"]["coupling_mode"]["enum"],
        )


if __name__ == "__main__":
    unittest.main()
