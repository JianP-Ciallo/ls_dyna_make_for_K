from __future__ import annotations

import unittest
from dataclasses import asdict
from pathlib import Path
import tempfile
import json
from unittest.mock import patch

from lsprepost_mcp.blast_analysis import (
    blast_sensitivity_report,
    compare_blast_run_records,
    summarize_blast_run,
)
from lsprepost_mcp.blast_cases import blast_case_catalog, blast_case_payload
from lsprepost_mcp.tool_generation import tool_assemble_components
from lsprepost_mcp.project_store import check_load_and_boundary_values, material_cards_for_spec
from lsprepost_mcp.dyna_keyword import build_keyword
from lsprepost_mcp.keyword_checks import keyword_quality_checks
from lsprepost_mcp.schema import parse_model_spec
from lsprepost_mcp.tool_helpers import validate_project_required_keywords
from lsprepost_mcp.web.solve_api import compare_lsdyna_payload


class Phase13BlastPresetTests(unittest.TestCase):
    def test_catalog_exposes_three_phase13_presets(self) -> None:
        ids = [item["id"] for item in blast_case_catalog() if item["phase"] == "13.1"]
        self.assertEqual(
            ["blast_on_helmet", "blast_on_circular_plate", "blast_on_multiple_targets"],
            ids,
        )

    def test_phase13_presets_compile_through_public_assembly_tool(self) -> None:
        expected_targets = {
            "blast_on_helmet": 1,
            "blast_on_circular_plate": 1,
            "blast_on_multiple_targets": 2,
        }
        for case_id, target_count in expected_targets.items():
            with self.subTest(case_id=case_id):
                payload = blast_case_payload(case_id, f"phase13_{case_id}")
                result = tool_assemble_components({**payload, "dry_run": True})
                self.assertTrue(result["ok"])
                self.assertEqual(1, result["metadata"]["blast_count"])
                self.assertEqual(target_count, result["metadata"]["blast_target_count"])
                self.assertTrue(result["sensitivity"]["ok_for_demo"])

    def test_phase13_presets_enable_nodout_for_displacement_audit(self) -> None:
        for case_id in ("blast_on_helmet", "blast_on_circular_plate", "blast_on_multiple_targets"):
            with self.subTest(case_id=case_id):
                payload = blast_case_payload(case_id, f"phase13_nodout_{case_id}")
                result = tool_assemble_components({**payload, "dry_run": True})
                self.assertEqual(0.001, result["resolved_spec"]["database"]["nodout_dt_s"])
                self.assertEqual(0.0001, result["resolved_spec"]["loads"][0]["output_dt_s"])
                parsed = parse_model_spec(result["resolved_spec"])
                keyword, metadata = build_keyword(parsed)
                self.assertIn("*DATABASE_NODOUT", keyword)
                self.assertIn("*DATABASE_HISTORY_NODE_SET", keyword)
                self.assertIn("nodout free response nodes", keyword)
                self.assertGreater(metadata["history_node_count"], 0)

    def test_circular_plate_rim_constraint_does_not_fix_entire_plate(self) -> None:
        payload = blast_case_payload("blast_on_circular_plate", "phase13_circle_rim")
        result = tool_assemble_components({**payload, "dry_run": True})
        plate = result["metadata"]["components"][0]
        self.assertGreater(len(plate["fixed_node_ids"]), 8)
        self.assertLess(len(plate["fixed_node_ids"]), plate["node_count"])
        self.assertEqual(["rim"], plate["fixed_regions"])

    def test_helmet_rim_constraint_does_not_fix_entire_shell(self) -> None:
        payload = blast_case_payload("blast_on_helmet", "phase13_helmet_rim")
        result = tool_assemble_components({**payload, "dry_run": True})
        helmet = result["metadata"]["components"][0]
        self.assertGreater(len(helmet["fixed_node_ids"]), 8)
        self.assertLess(len(helmet["fixed_node_ids"]), helmet["node_count"])

    def test_unknown_blast_case_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported blast case"):
            blast_case_payload("not_a_case")

    def test_assembly_validation_requires_actual_component_material_cards(self) -> None:
        payload = blast_case_payload("blast_on_multiple_targets", "phase13_material_cards")
        result = tool_assemble_components({**payload, "dry_run": True})
        self.assertEqual(
            ["*MAT_PIECEWISE_LINEAR_PLASTICITY"],
            material_cards_for_spec(result["resolved_spec"]),
        )

    def test_named_fixed_region_counts_as_constraint_anchor(self) -> None:
        payload = blast_case_payload("blast_on_circular_plate", "phase13_fixed_region")
        result = tool_assemble_components({**payload, "dry_run": True})
        checks = []

        def add_check(check_id, ok, message, **details):
            checks.append({"id": check_id, "ok": ok, "message": message, **details})

        check_load_and_boundary_values(result["resolved_spec"], add_check)
        anchor = next(item for item in checks if item["id"] == "boundary.constraint_anchor_count")
        self.assertTrue(anchor["ok"])
        self.assertEqual(1, anchor["actual"])

    def test_phase13_shell_presets_pass_aspect_ratio_solver_gate(self) -> None:
        for case_id in ("blast_on_helmet", "blast_on_circular_plate", "blast_on_multiple_targets"):
            with self.subTest(case_id=case_id):
                payload = blast_case_payload(case_id, f"phase13_quality_{case_id}")
                dry_run = tool_assemble_components({**payload, "dry_run": True})
                parsed = parse_model_spec(dry_run["resolved_spec"])
                keyword, metadata = build_keyword(parsed)
                checks = keyword_quality_checks(keyword, asdict(parsed), metadata)
                aspect = next(item for item in checks if item["id"] == "quality.geometry.shell_aspect_ratio")
                self.assertTrue(aspect["ok"], aspect["actual"])

    def test_import_keyword_gate_uses_blast_requirements_instead_of_phase6_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            keyword = root / "model.k"
            keyword.write_text(
                "*KEYWORD\n*PART\n*BOUNDARY_SPC_SET\n*DATABASE_BINARY_D3PLOT\n"
                "*LOAD_BLAST_ENHANCED\n*DATABASE_BINARY_BLSTFOR\n*END\n",
                encoding="utf-8",
            )
            model = root / "model.json"
            model.write_text(
                json.dumps({"spec": {"contacts": [], "loads": [{"type": "blast_enhanced"}]}}),
                encoding="utf-8",
            )
            result = validate_project_required_keywords(keyword, model)
            self.assertTrue(result["ok"])
            self.assertNotIn("contact", result["items"])
            self.assertNotIn("gravity", result["items"])
            self.assertIn("blast_load", result["items"])


class Phase13BlastAnalysisTests(unittest.TestCase):
    def test_sensitivity_report_identifies_demo_material_and_records_ratios(self) -> None:
        payload = blast_case_payload("blast_on_helmet", "phase13_sensitivity")
        report = blast_sensitivity_report(payload)
        self.assertTrue(report["ok_for_demo"])
        self.assertIn("demo_material", {item["id"] for item in report["warnings"]})
        self.assertGreater(report["targets"][0]["standoff_ratio"], 0.0)
        self.assertGreater(report["targets"][0]["mesh_thickness_ratio"], 0.0)

    def test_sensitivity_report_checks_end_time_and_blast_output_interval(self) -> None:
        payload = blast_case_payload("blast_on_circular_plate", "phase13_timing")
        payload["analysis_control"]["termination"]["end_time_s"] = 0.001
        payload["actions"][-1]["output_dt_s"] = 0.0005
        report = blast_sensitivity_report(payload)
        warning_ids = {item["id"] for item in report["warnings"]}
        self.assertIn("short_termination_time", warning_ids)
        self.assertIn("sparse_blast_output", warning_ids)

    def test_run_summary_preserves_units_sources_and_availability(self) -> None:
        record = {
            "ok": True,
            "status": "completed",
            "project_name": "blast_a",
            "run_id": "run_a",
            "solver_evaluation": {
                "metrics": {"hourglass_ratio": 0.03, "total_initial_ratio": 1.002},
            },
            "outputs": {
                "d3plot": {"ok": True, "total_size_bytes": 1000},
                "blstfor": {"ok": True, "total_size_bytes": 2000},
                "nodout": {"ok": True, "total_size_bytes": 3000},
            },
            "postprocessing": {
                "status": "verified",
                "maximum_value_pa": 1.8e8,
                "state_number": 22,
                "state_time_s": 0.012,
                "peak_displacement_m": 0.004,
                "peak_displacement_state": 23,
                "peak_displacement_time_s": 0.013,
            },
        }
        summary = summarize_blast_run(record)
        stress = summary["metrics"]["peak_von_mises_stress"]
        pressure = summary["metrics"]["peak_blast_pressure"]
        self.assertEqual("available", stress["status"])
        self.assertEqual("Pa", stress["unit"])
        self.assertEqual("LS-PrePost verified contour record", stress["source"])
        self.assertEqual(0.012, stress["time_s"])
        self.assertEqual("available", summary["metrics"]["peak_displacement"]["status"])
        self.assertEqual(3000.0, summary["metrics"]["nodout_size"]["value"])
        self.assertEqual("unavailable", pressure["status"])

    def test_run_summary_falls_back_to_d3hsp_blast_peak(self) -> None:
        record = {
            "ok": True,
            "status": "completed",
            "project_name": "blast_a",
            "run_id": "run_a",
            "solver_evaluation": {
                "metrics": {
                    "peak_blast_pressure_pa": 4.0174e6,
                    "peak_blast_pressure_time_s": 2.8444e-4,
                },
            },
            "outputs": {},
            "postprocessing": {},
        }

        pressure = summarize_blast_run(record)["metrics"]["peak_blast_pressure"]

        self.assertEqual("available", pressure["status"])
        self.assertEqual(4.0174e6, pressure["value"])
        self.assertEqual(2.8444e-4, pressure["time_s"])
        self.assertEqual("d3hsp enhanced blast summary", pressure["source"])

    def test_run_summary_uses_nodout_peak_displacement(self) -> None:
        record = {
            "ok": True,
            "status": "completed",
            "project_name": "blast_a",
            "run_id": "run_a",
            "solver_evaluation": {
                "metrics": {
                    "peak_displacement_m": 0.00379091,
                    "peak_displacement_node_id": 481,
                    "peak_displacement_time_step": 14513,
                    "peak_displacement_time_s": 0.0059998961,
                },
            },
            "outputs": {},
            "postprocessing": {},
        }

        displacement = summarize_blast_run(record)["metrics"]["peak_displacement"]

        self.assertEqual("available", displacement["status"])
        self.assertEqual(0.00379091, displacement["value"])
        self.assertEqual(481, displacement["node_id"])
        self.assertEqual(14513, displacement["time_step"])
        self.assertEqual(0.0059998961, displacement["time_s"])
        self.assertEqual("LS-DYNA nodout resultant displacement", displacement["source"])

    def test_run_summary_uses_binary_blstfor_history_without_overriding_d3hsp_peak(self) -> None:
        record = {
            "ok": True,
            "status": "completed",
            "project_name": "blast_a",
            "run_id": "run_a",
            "solver_evaluation": {
                "metrics": {
                    "peak_blast_pressure_pa": 4.0174e6,
                    "peak_blast_pressure_time_s": 2.8444e-4,
                },
                "blstfor": {
                    "status": "available",
                    "positive_phase_status": "available",
                    "positive_phase_quality": "coarse",
                    "positive_duration_s": 0.001997,
                    "positive_impulse_pa_s": 0.9612,
                    "quality_warnings": ["coarse sampling"],
                },
            },
            "outputs": {},
            "postprocessing": {},
        }

        metrics = summarize_blast_run(record)["metrics"]

        self.assertEqual(4.0174e6, metrics["peak_blast_pressure"]["value"])
        self.assertEqual("d3hsp enhanced blast summary", metrics["peak_blast_pressure"]["source"])
        self.assertEqual(0.001997, metrics["positive_phase_duration"]["value"])
        self.assertEqual("coarse", metrics["positive_phase_duration"]["quality"])
        self.assertEqual("LS-DYNA BLSTFOR binary pressure history", metrics["positive_phase_impulse"]["source"])

    def test_comparison_uses_only_available_metrics_with_matching_units(self) -> None:
        def record(project: str, stress: float, hourglass: float) -> dict:
            return {
                "ok": True,
                "status": "completed",
                "project_name": project,
                "run_id": f"run_{project}",
                "solver_evaluation": {
                    "metrics": {"hourglass_ratio": hourglass, "total_initial_ratio": 1.0},
                },
                "outputs": {},
                "postprocessing": {"maximum_value_pa": stress, "state_number": 2},
                "blast_configuration": {
                    "equivalent_mass_kg": [0.5 if project == "a" else 1.0],
                    "mesh_sizes_m": [0.02 if project == "a" else 0.01],
                    "material_names": ["mild_steel_mat24_demo"],
                },
            }

        result = compare_blast_run_records([record("a", 100.0, 0.02), record("b", 150.0, 0.03)])
        stress = result["comparisons"]["peak_von_mises_stress"]
        self.assertEqual("Pa", stress["unit"])
        self.assertEqual(50.0, stress["range"])
        self.assertEqual(1.5, stress["max_min_ratio"])
        self.assertEqual(
            ["equivalent_mass_kg", "mesh_sizes_m"],
            result["configuration_comparison"]["changed_critical_variables"],
        )
        self.assertEqual("multiple_variables_changed", result["configuration_comparison"]["warning"]["id"])

    def test_web_comparison_resolves_latest_runs_for_named_projects(self) -> None:
        records = {
            "blast_a": {
                "ok": True,
                "status": "completed",
                "project_name": "blast_a",
                "run_id": "run_a",
                "solver_evaluation": {"metrics": {"hourglass_ratio": 0.02}},
                "outputs": {},
                "postprocessing": {},
            },
            "blast_b": {
                "ok": True,
                "status": "completed",
                "project_name": "blast_b",
                "run_id": "run_b",
                "solver_evaluation": {"metrics": {"hourglass_ratio": 0.03}},
                "outputs": {},
                "postprocessing": {},
            },
        }

        def fake_find(name: str) -> Path:
            return Path("workspace") / "projects" / name

        with (
            patch("lsprepost_mcp.web.solve_api.find_project_dir", side_effect=fake_find),
            patch(
                "lsprepost_mcp.web.solve_api.latest_lsdyna_run",
                side_effect=lambda path: records[path.name],
            ),
            patch.object(Path, "is_dir", return_value=True),
        ):
            result = compare_lsdyna_payload({"project_names": ["blast_a", "blast_b"]})

        self.assertEqual(2, result["run_count"])
        self.assertIn("hourglass_energy_ratio", result["comparisons"])


if __name__ == "__main__":
    unittest.main()
