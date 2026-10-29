from __future__ import annotations

import hashlib
import json
import math
import shutil
import unittest

from lsprepost_mcp.city_impact import CITY_METRICS_SCHEMA_VERSION
from lsprepost_mcp.paths import project_dir
from lsprepost_mcp.phase16b import (
    analyze_case_uncertainty,
    authorize_case_batch,
    compare_case_results,
    create_controlled_case_matrix,
    plan_local_refinement,
    predict_surrogate_response,
    rank_protection_options,
    register_case_result,
    train_surrogate_model,
)
from lsprepost_mcp.tools import TOOLS
from lsprepost_mcp.tool_phase16b import (
    tool_analyze_city_case_uncertainty,
    tool_compare_city_case_results,
    tool_plan_city_local_refinement,
    tool_predict_city_surrogate,
    tool_prepare_city_case_matrix,
    tool_rank_city_protection_options,
    tool_train_city_surrogate,
)
from tests.test_web_api import request_json, web_test_server


class Phase16BTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reference = project_dir("unit_phase16b_reference")
        self.case_a = project_dir("unit_phase16b_case_a")
        self.case_b = project_dir("unit_phase16b_case_b")
        self.extra_projects = []
        for path in (self.reference, self.case_a, self.case_b, *self.extra_projects):
            if path.exists():
                shutil.rmtree(path)
        self._write_city_project(self.reference, tnt_mass_kg=100.0, mesh_size_m=0.2)

    def tearDown(self) -> None:
        for path in (self.reference, self.case_a, self.case_b, *self.extra_projects):
            if path.exists():
                shutil.rmtree(path)

    def test_matrix_is_deterministic_persisted_and_never_executes(self) -> None:
        first = create_controlled_case_matrix(
            self.reference,
            "mass_mesh_study",
            {
                "tnt_mass_kg": [100.0, 150.0],
                "near_mesh_size_m": [0.2, 0.15],
            },
        )
        second = create_controlled_case_matrix(
            self.reference,
            "mass_mesh_study",
            {
                "near_mesh_size_m": [0.15, 0.2],
                "tnt_mass_kg": [150.0, 100.0],
            },
        )

        self.assertEqual(first["matrix_id"], second["matrix_id"])
        self.assertEqual(4, first["case_count"])
        self.assertEqual(
            [item["case_id"] for item in first["cases"]],
            [item["case_id"] for item in second["cases"]],
        )
        self.assertEqual("prepared", first["status"])
        self.assertFalse(first["solver_execution_started"])
        self.assertTrue(first["requires_explicit_solver_authorization"])
        self.assertTrue((self.reference / first["relative_manifest_path"]).is_file())
        self.assertTrue(all(item["status"] == "prepared" for item in first["cases"]))

    def test_phase16b_tools_are_registered_with_closed_schemas(self) -> None:
        expected = {
            "prepare_city_case_matrix",
            "authorize_city_case_batch",
            "register_city_case_result",
            "compare_city_case_results",
            "analyze_city_case_uncertainty",
            "plan_city_local_refinement",
            "train_city_surrogate",
            "predict_city_surrogate",
            "rank_city_protection_options",
        }
        self.assertTrue(expected.issubset(TOOLS))
        for name in expected:
            self.assertFalse(TOOLS[name][1]["additionalProperties"])

    def test_tool_wrappers_prepare_and_compare_without_solver_execution(self) -> None:
        prepared = tool_prepare_city_case_matrix(
            {
                "project_name": self.reference.name,
                "study_id": "tool_study",
                "dimensions": {"tnt_mass_kg": [100.0]},
            }
        )
        self.assertFalse(prepared["solver_execution_started"])
        case_id = prepared["cases"][0]["case_id"]
        self._write_city_project(
            self.case_a,
            tnt_mass_kg=100.0,
            mesh_size_m=0.2,
            complete=True,
        )
        register_case_result(
            self.reference,
            "tool_study",
            case_id,
            self.case_a,
        )
        compared = tool_compare_city_case_results(
            {
                "project_name": self.reference.name,
                "study_id": "tool_study",
                "object_id": "commercial_supermarket",
            }
        )
        self.assertTrue(compared["comparable"])

    def test_web_api_prepares_matrix_without_solver_execution(self) -> None:
        with web_test_server() as address:
            status, payload = request_json(
                address,
                "POST",
                "/api/phase16b/case-matrix",
                {
                    "project_name": self.reference.name,
                    "study_id": "web_study",
                    "dimensions": {"tnt_mass_kg": [100.0, 150.0]},
                },
            )

        self.assertEqual(200, status)
        result = payload["result"]
        self.assertEqual(2, result["case_count"])
        self.assertFalse(result["solver_execution_started"])

    def test_matrix_rejects_unknown_nonfinite_and_excessive_dimensions(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported controlled parameter"):
            create_controlled_case_matrix(
                self.reference,
                "bad_parameter",
                {"raw_keyword": ["*DELETE_FILE"]},
            )
        with self.assertRaisesRegex(ValueError, "finite"):
            create_controlled_case_matrix(
                self.reference,
                "bad_number",
                {"tnt_mass_kg": [float("nan")]},
            )
        with self.assertRaisesRegex(ValueError, "64"):
            create_controlled_case_matrix(
                self.reference,
                "too_many",
                {
                    "tnt_mass_kg": [10.0 + index for index in range(9)],
                    "near_mesh_size_m": [0.1, 0.15, 0.2],
                    "end_time_s": [0.01, 0.02, 0.03],
                },
            )

    def test_batch_authorization_requires_exact_phrase_and_known_cases(self) -> None:
        matrix = create_controlled_case_matrix(
            self.reference,
            "authorization_study",
            {"tnt_mass_kg": [100.0, 150.0]},
        )
        case_ids = [item["case_id"] for item in matrix["cases"]]

        with self.assertRaisesRegex(ValueError, "approval_text"):
            authorize_case_batch(
                self.reference,
                "authorization_study",
                case_ids,
                "yes",
            )
        with self.assertRaisesRegex(ValueError, "unknown case_id"):
            authorize_case_batch(
                self.reference,
                "authorization_study",
                [case_ids[0], "case_unknown"],
                matrix["authorization"]["approval_text"],
            )

        result = authorize_case_batch(
            self.reference,
            "authorization_study",
            case_ids,
            matrix["authorization"]["approval_text"],
        )

        self.assertEqual("authorized_not_started", result["status"])
        self.assertFalse(result["solver_execution_started"])
        self.assertEqual(case_ids, result["authorized_case_ids"])

        with self.assertRaisesRegex(ValueError, "new study_id"):
            create_controlled_case_matrix(
                self.reference,
                "authorization_study",
                {"tnt_mass_kg": [200.0]},
            )

    def test_result_repository_rejects_incomplete_or_mismatched_case(self) -> None:
        matrix = create_controlled_case_matrix(
            self.reference,
            "result_gate_study",
            {"tnt_mass_kg": [100.0]},
        )
        case_id = matrix["cases"][0]["case_id"]
        self._write_city_project(
            self.case_a,
            tnt_mass_kg=100.0,
            mesh_size_m=0.2,
            complete=False,
        )
        with self.assertRaisesRegex(ValueError, "Phase 16A quality gate"):
            register_case_result(
                self.reference,
                "result_gate_study",
                case_id,
                self.case_a,
            )

        self._write_city_project(
            self.case_a,
            tnt_mass_kg=125.0,
            mesh_size_m=0.2,
            complete=True,
        )
        with self.assertRaisesRegex(ValueError, "does not match"):
            register_case_result(
                self.reference,
                "result_gate_study",
                case_id,
                self.case_a,
            )

    def test_repository_compares_same_object_and_blocks_silent_mesh_mixing(self) -> None:
        matrix = create_controlled_case_matrix(
            self.reference,
            "comparison_study",
            {
                "tnt_mass_kg": [100.0, 150.0],
                "near_mesh_size_m": [0.2, 0.15],
            },
        )
        cases_by_controls = {
            (
                item["parameters"]["tnt_mass_kg"],
                item["parameters"]["near_mesh_size_m"],
            ): item
            for item in matrix["cases"]
        }
        self._write_city_project(
            self.case_a,
            tnt_mass_kg=100.0,
            mesh_size_m=0.2,
            complete=True,
            peak_pressure_pa=20.0,
        )
        self._write_city_project(
            self.case_b,
            tnt_mass_kg=150.0,
            mesh_size_m=0.2,
            complete=True,
            peak_pressure_pa=35.0,
        )
        register_case_result(
            self.reference,
            "comparison_study",
            cases_by_controls[(100.0, 0.2)]["case_id"],
            self.case_a,
        )
        register_case_result(
            self.reference,
            "comparison_study",
            cases_by_controls[(150.0, 0.2)]["case_id"],
            self.case_b,
        )

        comparison = compare_case_results(
            self.reference,
            "comparison_study",
            "commercial_supermarket",
            case_ids=[
                cases_by_controls[(100.0, 0.2)]["case_id"],
                cases_by_controls[(150.0, 0.2)]["case_id"],
            ],
        )

        self.assertTrue(comparison["comparable"])
        self.assertEqual(2, comparison["case_count"])
        pressure = comparison["metrics"]["peak_pressure_pa"]
        self.assertEqual(20.0, pressure["minimum"])
        self.assertEqual(35.0, pressure["maximum"])
        self.assertEqual(15.0, pressure["range"])

        self._write_city_project(
            self.case_b,
            tnt_mass_kg=150.0,
            mesh_size_m=0.15,
            complete=True,
            peak_pressure_pa=38.0,
        )
        register_case_result(
            self.reference,
            "comparison_study",
            cases_by_controls[(150.0, 0.15)]["case_id"],
            self.case_b,
        )

        blocked = compare_case_results(
            self.reference,
            "comparison_study",
            "commercial_supermarket",
            case_ids=[
                cases_by_controls[(100.0, 0.2)]["case_id"],
                cases_by_controls[(150.0, 0.15)]["case_id"],
            ],
        )
        self.assertFalse(blocked["comparable"])
        self.assertIn("mesh_fingerprint", blocked["blocking_differences"])
        explicit = compare_case_results(
            self.reference,
            "comparison_study",
            "commercial_supermarket",
            case_ids=[
                cases_by_controls[(100.0, 0.2)]["case_id"],
                cases_by_controls[(150.0, 0.15)]["case_id"],
            ],
            allow_mixed_mesh=True,
        )
        self.assertTrue(explicit["comparable"])
        self.assertTrue(explicit["mixed_mesh"])

    def test_uncertainty_analysis_reports_coverage_sensitivity_and_fidelity(self) -> None:
        matrix = create_controlled_case_matrix(
            self.reference,
            "uncertainty_study",
            {
                "tnt_mass_kg": [100.0, 150.0, 200.0],
                "near_mesh_size_m": [0.2, 0.15],
            },
        )
        for index, case in enumerate(matrix["cases"], start=1):
            parameters = case["parameters"]
            sample_path = project_dir(f"unit_phase16b_uncertainty_{index}")
            self.extra_projects.append(sample_path)
            pressure = (
                0.2 * parameters["tnt_mass_kg"]
                + (2.0 if parameters["near_mesh_size_m"] == 0.2 else 0.0)
            )
            self._write_city_project(
                sample_path,
                tnt_mass_kg=parameters["tnt_mass_kg"],
                mesh_size_m=parameters["near_mesh_size_m"],
                complete=True,
                peak_pressure_pa=pressure,
            )
            register_case_result(
                self.reference,
                "uncertainty_study",
                case["case_id"],
                sample_path,
            )

        result = analyze_case_uncertainty(
            self.reference,
            "uncertainty_study",
            "commercial_supermarket",
            "peak_pressure_pa",
        )

        self.assertTrue(result["ready"])
        self.assertEqual(6, result["sample_coverage"]["analyzed_case_count"])
        self.assertEqual(1.0, result["sample_coverage"]["registered_fraction"])
        self.assertEqual("Pa", result["response"]["unit"])
        self.assertLess(
            result["response"]["mean_confidence_interval"]["lower"],
            result["response"]["mean"],
        )
        self.assertGreater(
            result["response"]["mean_confidence_interval"]["upper"],
            result["response"]["mean"],
        )
        mass = next(
            item
            for item in result["parameter_sensitivity"]
            if item["parameter_id"] == "tnt_mass_kg"
        )
        self.assertGreater(mass["pearson_r"], 0.95)
        self.assertEqual("input", mass["uncertainty_source"])
        mesh = next(
            item
            for item in result["parameter_sensitivity"]
            if item["parameter_id"] == "near_mesh_size_m"
        )
        self.assertEqual("model_resolution", mesh["uncertainty_source"])
        fidelity = result["fidelity_difference"]
        self.assertEqual(3, fidelity["paired_group_count"])
        self.assertAlmostEqual(2.0, fidelity["mean_absolute_difference"])
        self.assertEqual(
            "not_sampled",
            result["uncertainty_components"]["material"]["status"],
        )
        self.assertTrue(
            (self.reference / result["relative_analysis_path"]).is_file()
        )

        tool_result = tool_analyze_city_case_uncertainty(
            {
                "project_name": self.reference.name,
                "study_id": "uncertainty_study",
                "object_id": "commercial_supermarket",
                "metric_id": "peak_pressure_pa",
            }
        )
        self.assertTrue(tool_result["ready"])
        with web_test_server() as address:
            status, payload = request_json(
                address,
                "POST",
                "/api/phase16b/analyze-uncertainty",
                {
                    "project_name": self.reference.name,
                    "study_id": "uncertainty_study",
                    "object_id": "commercial_supermarket",
                    "metric_id": "peak_pressure_pa",
                },
            )
        self.assertEqual(200, status)
        self.assertTrue(payload["result"]["ready"])

    def test_local_refinement_plan_explains_regions_mesh_and_acceptance_target(self) -> None:
        matrix = create_controlled_case_matrix(
            self.reference,
            "refinement_study",
            {
                "tnt_mass_kg": [100.0, 150.0, 200.0],
                "near_mesh_size_m": [0.2, 0.15],
            },
        )
        for index, case in enumerate(matrix["cases"], start=1):
            parameters = case["parameters"]
            sample_path = project_dir(f"unit_phase16b_refinement_{index}")
            self.extra_projects.append(sample_path)
            pressure = (
                0.2 * parameters["tnt_mass_kg"]
                + (4.0 if parameters["near_mesh_size_m"] == 0.2 else 0.0)
            )
            self._write_city_project(
                sample_path,
                tnt_mass_kg=parameters["tnt_mass_kg"],
                mesh_size_m=parameters["near_mesh_size_m"],
                complete=True,
                peak_pressure_pa=pressure,
            )
            register_case_result(
                self.reference,
                "refinement_study",
                case["case_id"],
                sample_path,
            )

        result = plan_local_refinement(
            self.reference,
            "refinement_study",
            "commercial_supermarket",
            "peak_pressure_pa",
            refinement_factor=0.5,
            padding_cells=4,
        )

        self.assertTrue(result["ready"])
        self.assertEqual("planned", result["status"])
        self.assertFalse(result["solver_execution_started"])
        self.assertEqual("planning_only", result["implementation_status"])
        self.assertEqual("commercial_supermarket", result["object"]["object_id"])
        self.assertEqual(
            {"blast_source", "propagation_corridor", "target_object"},
            {item["region_type"] for item in result["regions"]},
        )
        self.assertAlmostEqual(0.075, result["mesh"]["target_size_m"])
        self.assertIn(
            result["mesh"]["target_size_m"],
            TOOLS["prepare_city_case_matrix"][1]["properties"]["dimensions"][
                "properties"
            ]["near_mesh_size_m"]["items"]["enum"],
        )
        self.assertLess(
            result["mesh"]["target_size_m"],
            result["mesh"]["finest_observed_size_m"],
        )
        self.assertFalse(result["expected_benefit"]["guaranteed"])
        self.assertIn(
            "paired_model_difference",
            result["decision"]["drivers"],
        )
        self.assertTrue(
            (self.reference / result["relative_plan_path"]).is_file()
        )

        tool_result = tool_plan_city_local_refinement(
            {
                "project_name": self.reference.name,
                "study_id": "refinement_study",
                "object_id": "commercial_supermarket",
                "metric_id": "peak_pressure_pa",
                "refinement_factor": 0.5,
                "padding_cells": 4,
            }
        )
        self.assertTrue(tool_result["ready"])
        with web_test_server() as address:
            status, payload = request_json(
                address,
                "POST",
                "/api/phase16b/plan-refinement",
                {
                    "project_name": self.reference.name,
                    "study_id": "refinement_study",
                    "object_id": "commercial_supermarket",
                    "metric_id": "peak_pressure_pa",
                },
            )
        self.assertEqual(200, status)
        self.assertTrue(payload["result"]["ready"])

    def test_local_refinement_plan_blocks_when_sample_analysis_is_not_ready(self) -> None:
        matrix = create_controlled_case_matrix(
            self.reference,
            "refinement_small_sample",
            {"tnt_mass_kg": [100.0, 150.0]},
        )
        for index, case in enumerate(matrix["cases"], start=1):
            sample_path = project_dir(f"unit_phase16b_refinement_small_{index}")
            self.extra_projects.append(sample_path)
            mass = case["parameters"]["tnt_mass_kg"]
            self._write_city_project(
                sample_path,
                tnt_mass_kg=mass,
                mesh_size_m=0.2,
                complete=True,
                peak_pressure_pa=0.2 * mass,
            )
            register_case_result(
                self.reference,
                "refinement_small_sample",
                case["case_id"],
                sample_path,
            )

        result = plan_local_refinement(
            self.reference,
            "refinement_small_sample",
            "commercial_supermarket",
            "peak_pressure_pa",
        )

        self.assertFalse(result["ready"])
        self.assertEqual("blocked", result["status"])
        self.assertIn("uncertainty_analysis_not_ready", result["blocking_reasons"])
        self.assertEqual([], result["regions"])

    def test_local_refinement_plan_blocks_without_semantic_object_bounds(self) -> None:
        matrix = create_controlled_case_matrix(
            self.reference,
            "refinement_missing_bounds",
            {
                "tnt_mass_kg": [100.0, 150.0, 200.0],
                "near_mesh_size_m": [0.2, 0.15],
            },
        )
        for index, case in enumerate(matrix["cases"], start=1):
            parameters = case["parameters"]
            sample_path = project_dir(f"unit_phase16b_refinement_no_bounds_{index}")
            self.extra_projects.append(sample_path)
            self._write_city_project(
                sample_path,
                tnt_mass_kg=parameters["tnt_mass_kg"],
                mesh_size_m=parameters["near_mesh_size_m"],
                complete=True,
                peak_pressure_pa=0.2 * parameters["tnt_mass_kg"],
                include_object_bounds=False,
            )
            register_case_result(
                self.reference,
                "refinement_missing_bounds",
                case["case_id"],
                sample_path,
            )

        result = plan_local_refinement(
            self.reference,
            "refinement_missing_bounds",
            "commercial_supermarket",
            "peak_pressure_pa",
        )

        self.assertFalse(result["ready"])
        self.assertEqual("blocked", result["status"])
        self.assertIn("semantic_object_bounds_missing", result["blocking_reasons"])
        self.assertEqual([], result["regions"])

    def test_surrogate_training_cross_validates_and_predicts_inside_domain(self) -> None:
        self._register_surrogate_study("surrogate_study")

        model = train_surrogate_model(
            self.reference,
            "surrogate_study",
            "commercial_supermarket",
            "peak_pressure_pa",
            neighbor_count=1,
            max_normalized_rmse=0.25,
        )

        self.assertTrue(model["ready"])
        self.assertEqual("accepted", model["status"])
        self.assertTrue(model["accepted_for_prediction"])
        self.assertEqual(
            "leave_one_out",
            model["cross_validation"]["method"],
        )
        self.assertLessEqual(
            model["cross_validation"]["normalized_rmse"],
            0.25,
        )
        self.assertEqual(
            {"near_mesh_size_m", "tnt_mass_kg"},
            {item["parameter_id"] for item in model["features"]},
        )
        self.assertTrue(
            (self.reference / model["relative_model_path"]).is_file()
        )

        prediction = predict_surrogate_response(
            self.reference,
            "surrogate_study",
            "commercial_supermarket",
            "peak_pressure_pa",
            {
                "tnt_mass_kg": 125.0,
                "near_mesh_size_m": 0.15,
            },
        )
        self.assertTrue(prediction["ready"])
        self.assertEqual("estimated", prediction["status"])
        self.assertEqual("Pa", prediction["estimate"]["unit"])
        self.assertFalse(prediction["estimate"]["deterministic"])
        self.assertTrue(prediction["estimate"]["prediction_interval"]["empirical"])
        self.assertGreaterEqual(len(prediction["neighbors"]), 1)

        tool_model = tool_train_city_surrogate(
            {
                "project_name": self.reference.name,
                "study_id": "surrogate_study",
                "object_id": "commercial_supermarket",
                "metric_id": "peak_pressure_pa",
            }
        )
        self.assertTrue(tool_model["ready"])
        tool_prediction = tool_predict_city_surrogate(
            {
                "project_name": self.reference.name,
                "study_id": "surrogate_study",
                "object_id": "commercial_supermarket",
                "metric_id": "peak_pressure_pa",
                "parameters": {
                    "tnt_mass_kg": 125.0,
                    "near_mesh_size_m": 0.15,
                },
            }
        )
        self.assertTrue(tool_prediction["ready"])

        with web_test_server() as address:
            train_status, train_payload = request_json(
                address,
                "POST",
                "/api/phase16b/train-surrogate",
                {
                    "project_name": self.reference.name,
                    "study_id": "surrogate_study",
                    "object_id": "commercial_supermarket",
                    "metric_id": "peak_pressure_pa",
                },
            )
            predict_status, predict_payload = request_json(
                address,
                "POST",
                "/api/phase16b/predict-surrogate",
                {
                    "project_name": self.reference.name,
                    "study_id": "surrogate_study",
                    "object_id": "commercial_supermarket",
                    "metric_id": "peak_pressure_pa",
                    "parameters": {
                        "tnt_mass_kg": 125.0,
                        "near_mesh_size_m": 0.15,
                    },
                },
            )
        self.assertEqual(200, train_status)
        self.assertTrue(train_payload["result"]["ready"])
        self.assertEqual(200, predict_status)
        self.assertTrue(predict_payload["result"]["ready"])

    def test_surrogate_prediction_refuses_extrapolation(self) -> None:
        self._register_surrogate_study("surrogate_extrapolation")
        train_surrogate_model(
            self.reference,
            "surrogate_extrapolation",
            "commercial_supermarket",
            "peak_pressure_pa",
        )

        result = predict_surrogate_response(
            self.reference,
            "surrogate_extrapolation",
            "commercial_supermarket",
            "peak_pressure_pa",
            {
                "tnt_mass_kg": 250.0,
                "near_mesh_size_m": 0.15,
            },
        )

        self.assertFalse(result["ready"])
        self.assertEqual("outside_applicability_domain", result["status"])
        self.assertIn("tnt_mass_kg", result["refusal_reasons"])
        self.assertNotIn("estimate", result)

    def test_surrogate_training_rejects_high_cross_validation_error(self) -> None:
        self._register_surrogate_study(
            "surrogate_poor_quality",
            response=lambda mass, mesh: (
                100.0
                if (mass == 150.0) != (mesh == 0.2)
                else 1.0
            ),
        )

        model = train_surrogate_model(
            self.reference,
            "surrogate_poor_quality",
            "commercial_supermarket",
            "peak_pressure_pa",
            neighbor_count=1,
            max_normalized_rmse=0.15,
        )

        self.assertFalse(model["ready"])
        self.assertEqual("rejected_quality", model["status"])
        self.assertFalse(model["accepted_for_prediction"])
        self.assertIn("cross_validation_error_too_high", model["blocking_reasons"])

    def test_surrogate_training_blocks_too_few_samples(self) -> None:
        matrix = create_controlled_case_matrix(
            self.reference,
            "surrogate_small_sample",
            {
                "tnt_mass_kg": [100.0, 150.0],
                "near_mesh_size_m": [0.2, 0.15],
            },
        )
        for index, case in enumerate(matrix["cases"], start=1):
            parameters = case["parameters"]
            sample_path = project_dir(f"unit_phase16b_surrogate_small_{index}")
            self.extra_projects.append(sample_path)
            self._write_city_project(
                sample_path,
                tnt_mass_kg=parameters["tnt_mass_kg"],
                mesh_size_m=parameters["near_mesh_size_m"],
                complete=True,
                peak_pressure_pa=0.02 * parameters["tnt_mass_kg"],
            )
            register_case_result(
                self.reference,
                "surrogate_small_sample",
                case["case_id"],
                sample_path,
            )

        model = train_surrogate_model(
            self.reference,
            "surrogate_small_sample",
            "commercial_supermarket",
            "peak_pressure_pa",
        )

        self.assertFalse(model["ready"])
        self.assertEqual("blocked", model["status"])
        self.assertIn("minimum_surrogate_sample_count", model["blocking_reasons"])

    def test_protection_options_are_ranked_with_cost_benefit_and_constraints(self) -> None:
        cases = self._register_protection_study("protection_study")
        objectives = [
            {
                "object_id": "commercial_supermarket",
                "metric_id": "peak_pressure_pa",
                "weight": 1.0,
            }
        ]
        options = [
            {
                "option_id": "moderate_setback",
                "label": "Increase setback to 5 m",
                "case_id": cases[5.0],
                "measure_type": "increase_standoff",
                "incremental_cost": {"value": 10.0, "unit": "relative_cost"},
                "physical_basis": "Greater stand-off reduces incident blast pressure.",
                "constraints": ["Keep the existing building footprint."],
            },
            {
                "option_id": "large_setback",
                "label": "Increase setback to 10 m",
                "case_id": cases[10.0],
                "measure_type": "increase_standoff",
                "incremental_cost": {"value": 50.0, "unit": "relative_cost"},
                "physical_basis": "Greater stand-off reduces incident blast pressure.",
                "constraints": ["Requires a larger exclusion zone."],
            },
        ]

        result = rank_protection_options(
            self.reference,
            "protection_study",
            cases[0.0],
            objectives,
            options,
            effectiveness_weight=0.7,
            cost_weight=0.3,
            budget_limit=60.0,
            metric_limits=[
                {
                    "object_id": "commercial_supermarket",
                    "metric_id": "peak_pressure_pa",
                    "maximum_value": 70.0,
                }
            ],
        )

        self.assertEqual("ranked", result["status"])
        self.assertEqual("moderate_setback", result["recommendation"]["option_id"])
        self.assertEqual("relative_cost", result["cost_unit"])
        self.assertTrue(result["recommendation"]["feasible"])
        self.assertEqual(35.0, result["ranked_options"][0]["absolute_benefit"])
        self.assertAlmostEqual(0.35, result["ranked_options"][0]["benefit_fraction"])
        self.assertEqual(1, result["ranked_options"][0]["rank"])
        self.assertTrue(result["ranked_options"][0]["physical_basis"])
        self.assertTrue(result["ranked_options"][0]["pareto_efficient"])
        self.assertFalse(result["solver_execution_started"])
        self.assertTrue(
            (self.reference / result["relative_ranking_path"]).is_file()
        )

        tool_result = tool_rank_city_protection_options(
            {
                "project_name": self.reference.name,
                "study_id": "protection_study",
                "baseline_case_id": cases[0.0],
                "objectives": objectives,
                "options": options,
                "effectiveness_weight": 0.7,
                "cost_weight": 0.3,
                "budget_limit": 60.0,
                "metric_limits": [
                    {
                        "object_id": "commercial_supermarket",
                        "metric_id": "peak_pressure_pa",
                        "maximum_value": 70.0,
                    }
                ],
            }
        )
        self.assertEqual("moderate_setback", tool_result["recommendation"]["option_id"])

        with web_test_server() as address:
            status, payload = request_json(
                address,
                "POST",
                "/api/phase16b/rank-protection",
                {
                    "project_name": self.reference.name,
                    "study_id": "protection_study",
                    "baseline_case_id": cases[0.0],
                    "objectives": objectives,
                    "options": options,
                    "budget_limit": 60.0,
                    "metric_limits": [
                        {
                            "object_id": "commercial_supermarket",
                            "metric_id": "peak_pressure_pa",
                            "maximum_value": 70.0,
                        }
                    ],
                },
            )
        self.assertEqual(200, status)
        self.assertEqual(
            "moderate_setback",
            payload["result"]["recommendation"]["option_id"],
        )

    def test_protection_ranking_reports_no_feasible_option(self) -> None:
        cases = self._register_protection_study("protection_budget_block")
        result = rank_protection_options(
            self.reference,
            "protection_budget_block",
            cases[0.0],
            [
                {
                    "object_id": "commercial_supermarket",
                    "metric_id": "peak_pressure_pa",
                    "weight": 1.0,
                }
            ],
            [
                {
                    "option_id": "setback",
                    "label": "Increase setback",
                    "case_id": cases[5.0],
                    "measure_type": "increase_standoff",
                    "incremental_cost": {"value": 10.0, "unit": "relative_cost"},
                    "physical_basis": "Greater stand-off reduces incident pressure.",
                    "constraints": [],
                }
            ],
            budget_limit=5.0,
        )

        self.assertEqual("no_feasible_option", result["status"])
        self.assertIsNone(result["recommendation"])
        self.assertIn(
            "budget_limit",
            result["ranked_options"][0]["constraint_violations"],
        )

    def test_protection_ranking_blocks_incompatible_cost_units(self) -> None:
        cases = self._register_protection_study("protection_cost_units")
        with self.assertRaisesRegex(ValueError, "same unit"):
            rank_protection_options(
                self.reference,
                "protection_cost_units",
                cases[0.0],
                [
                    {
                        "object_id": "commercial_supermarket",
                        "metric_id": "peak_pressure_pa",
                        "weight": 1.0,
                    }
                ],
                [
                    {
                        "option_id": "relative",
                        "label": "Relative-cost option",
                        "case_id": cases[5.0],
                        "measure_type": "increase_standoff",
                        "incremental_cost": {
                            "value": 10.0,
                            "unit": "relative_cost",
                        },
                        "physical_basis": "Greater stand-off reduces incident pressure.",
                        "constraints": [],
                    },
                    {
                        "option_id": "currency",
                        "label": "Currency option",
                        "case_id": cases[10.0],
                        "measure_type": "increase_standoff",
                        "incremental_cost": {"value": 20.0, "unit": "CNY"},
                        "physical_basis": "Greater stand-off reduces incident pressure.",
                        "constraints": [],
                    },
                ],
            )

    def test_protection_ranking_requires_explicit_physical_basis(self) -> None:
        cases = self._register_protection_study("protection_basis_gate")
        with self.assertRaisesRegex(ValueError, "physical_basis"):
            rank_protection_options(
                self.reference,
                "protection_basis_gate",
                cases[0.0],
                [
                    {
                        "object_id": "commercial_supermarket",
                        "metric_id": "peak_pressure_pa",
                        "weight": 1.0,
                    }
                ],
                [
                    {
                        "option_id": "setback",
                        "label": "Increase setback",
                        "case_id": cases[5.0],
                        "measure_type": "increase_standoff",
                        "incremental_cost": {
                            "value": 10.0,
                            "unit": "relative_cost",
                        },
                        "physical_basis": "",
                        "constraints": [],
                    }
                ],
            )

    def test_protection_ranking_requires_explicit_variant_compatibility(self) -> None:
        matrix = create_controlled_case_matrix(
            self.reference,
            "protection_variant_policy",
            {
                "blast_center_x_m": [0.0, 5.0],
                "near_mesh_size_m": [0.2, 0.15],
            },
        )
        cases = {
            (
                float(item["parameters"]["blast_center_x_m"]),
                float(item["parameters"]["near_mesh_size_m"]),
            ): item["case_id"]
            for item in matrix["cases"]
        }
        baseline_path = project_dir("unit_phase16b_protection_variant_baseline")
        option_path = project_dir("unit_phase16b_protection_variant_option")
        self.extra_projects.extend([baseline_path, option_path])
        self._write_city_project(
            baseline_path,
            tnt_mass_kg=100.0,
            mesh_size_m=0.2,
            peak_pressure_pa=100.0,
        )
        self._write_city_project(
            option_path,
            tnt_mass_kg=100.0,
            mesh_size_m=0.15,
            peak_pressure_pa=60.0,
            blast_center_x_m=5.0,
            object_bounds_x_offset_m=1.0,
        )
        baseline_case_id = cases[(0.0, 0.2)]
        option_case_id = cases[(5.0, 0.15)]
        register_case_result(
            self.reference,
            "protection_variant_policy",
            baseline_case_id,
            baseline_path,
        )
        register_case_result(
            self.reference,
            "protection_variant_policy",
            option_case_id,
            option_path,
        )
        objectives = [
            {
                "object_id": "commercial_supermarket",
                "metric_id": "peak_pressure_pa",
                "weight": 1.0,
            }
        ]
        options = [
            {
                "option_id": "geometry_variant",
                "label": "Geometry and mesh variant",
                "case_id": option_case_id,
                "measure_type": "combined",
                "incremental_cost": {"value": 20.0, "unit": "relative_cost"},
                "physical_basis": "Combined layout and discretization alternative.",
                "constraints": ["Requires explicit cross-variant comparison."],
            }
        ]

        blocked = rank_protection_options(
            self.reference,
            "protection_variant_policy",
            baseline_case_id,
            objectives,
            options,
        )
        self.assertEqual("blocked_incompatible_results", blocked["status"])
        self.assertIn("mesh_fingerprint", blocked["blocking_differences"])
        self.assertIn("semantic_fingerprint", blocked["blocking_differences"])

        explicit = rank_protection_options(
            self.reference,
            "protection_variant_policy",
            baseline_case_id,
            objectives,
            options,
            allow_mixed_mesh=True,
            allow_semantic_variants=True,
        )
        self.assertEqual("ranked", explicit["status"])
        self.assertTrue(
            explicit["compatibility_policy"]["allow_mixed_mesh"]
        )
        self.assertTrue(
            explicit["compatibility_policy"]["allow_semantic_variants"]
        )

    def test_uncertainty_analysis_refuses_deterministic_claim_for_too_few_samples(self) -> None:
        matrix = create_controlled_case_matrix(
            self.reference,
            "small_sample_study",
            {"tnt_mass_kg": [100.0, 150.0]},
        )
        for index, case in enumerate(matrix["cases"], start=1):
            sample_path = project_dir(f"unit_phase16b_small_sample_{index}")
            self.extra_projects.append(sample_path)
            mass = case["parameters"]["tnt_mass_kg"]
            self._write_city_project(
                sample_path,
                tnt_mass_kg=mass,
                mesh_size_m=0.2,
                complete=True,
                peak_pressure_pa=0.2 * mass,
            )
            register_case_result(
                self.reference,
                "small_sample_study",
                case["case_id"],
                sample_path,
            )

        result = analyze_case_uncertainty(
            self.reference,
            "small_sample_study",
            "commercial_supermarket",
            "peak_pressure_pa",
        )

        self.assertFalse(result["ready"])
        self.assertIn("minimum_sample_count", result["blocking_reasons"])
        self.assertEqual("insufficient_samples", result["status"])

    def test_uncertainty_analysis_blocks_mixed_material_contracts(self) -> None:
        matrix = create_controlled_case_matrix(
            self.reference,
            "mixed_material_study",
            {"tnt_mass_kg": [100.0, 150.0, 200.0]},
        )
        for index, case in enumerate(matrix["cases"], start=1):
            sample_path = project_dir(f"unit_phase16b_mixed_material_{index}")
            self.extra_projects.append(sample_path)
            mass = case["parameters"]["tnt_mass_kg"]
            self._write_city_project(
                sample_path,
                tnt_mass_kg=mass,
                mesh_size_m=0.2,
                complete=True,
                peak_pressure_pa=0.2 * mass,
                concrete_material_name=(
                    "alternate_concrete" if index == 3 else "concrete_reference"
                ),
            )
            register_case_result(
                self.reference,
                "mixed_material_study",
                case["case_id"],
                sample_path,
            )

        result = analyze_case_uncertainty(
            self.reference,
            "mixed_material_study",
            "commercial_supermarket",
            "peak_pressure_pa",
        )

        self.assertFalse(result["ready"])
        self.assertEqual("incompatible_results", result["status"])
        self.assertIn(
            "incompatible_result_contracts",
            result["blocking_reasons"],
        )
        self.assertIn(
            "material_fingerprint",
            result["compatibility_differences"],
        )

    def test_uncertainty_analysis_rejects_repository_from_another_matrix(self) -> None:
        matrix = create_controlled_case_matrix(
            self.reference,
            "stale_repository_study",
            {"tnt_mass_kg": [100.0]},
        )
        self._write_city_project(
            self.case_a,
            tnt_mass_kg=100.0,
            mesh_size_m=0.2,
            complete=True,
        )
        register_case_result(
            self.reference,
            "stale_repository_study",
            matrix["cases"][0]["case_id"],
            self.case_a,
        )
        index_path = (
            self.reference
            / "artifacts"
            / "phase16b"
            / "stale_repository_study"
            / "result_index.json"
        )
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["matrix_id"] = "matrix_from_another_study"
        index_path.write_text(json.dumps(index), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "another matrix"):
            analyze_case_uncertainty(
                self.reference,
                "stale_repository_study",
                "commercial_supermarket",
                "peak_pressure_pa",
            )

    def _write_city_project(
        self,
        path,
        *,
        tnt_mass_kg: float,
        mesh_size_m: float,
        complete: bool = True,
        peak_pressure_pa: float = 20.0,
        concrete_material_name: str = "concrete_reference",
        include_object_bounds: bool = True,
        blast_center_x_m: float = 0.0,
        object_bounds_x_offset_m: float = 0.0,
    ) -> None:
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
        (path / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")
        tnt_diameter_m = 0.6
        tnt_density_kg_per_m3 = 1600.0
        tnt_length_m = tnt_mass_kg / (
            tnt_density_kg_per_m3 * math.pi * (0.5 * tnt_diameter_m) ** 2
        )
        resolved_spec = {
            "project_name": path.name,
            "model_type": "city_street_blast_scene",
            "scene_id": "city_street_blast",
            "unit_system": "SI_m_kg_s_Pa",
            "domain": {"min_m": [-36.0, -36.0, 0.0], "max_m": [36.0, 36.0, 20.0]},
            "mesh": {"near_size_m": mesh_size_m},
            "explosive": {
                "mass_kg": tnt_mass_kg,
                "diameter_m": tnt_diameter_m,
                "length_m": tnt_length_m,
                "density_kg_per_m3": tnt_density_kg_per_m3,
                "base_center_m": [blast_center_x_m, 0.0, 0.01],
                "material": "tnt_reference",
            },
            "material": {"name": concrete_material_name},
            "analysis": {"end_time_s": 0.01},
        }
        model = {
            "schema_version": "0.2.0",
            "spec": resolved_spec,
            "metadata": {
                "model_type": "city_street_blast_scene",
                "validation_profile": "mm_ale_urban_blast_v1",
                "city_semantic_schema_version": "phase16a.city_semantics.v1",
                "resolved_spec": resolved_spec,
                "semantic_objects": [
                    {
                        "object_id": "commercial_supermarket",
                        "group_id": "commercial_supermarket",
                        "category": "commercial_building",
                        "part_ids": [19],
                        "constraint_mode": "fixed",
                        **(
                            {
                                "bounds_m": {
                                    "min": [
                                        10.0 + object_bounds_x_offset_m,
                                        -5.0,
                                        0.0,
                                    ],
                                    "max": [
                                        20.0 + object_bounds_x_offset_m,
                                        5.0,
                                        8.0,
                                    ],
                                }
                            }
                            if include_object_bounds
                            else {}
                        ),
                    }
                ],
                "required_response_object_ids": ["commercial_supermarket"],
                "response_objects": [
                    {
                        "object_id": "commercial_supermarket",
                        "fsi_surface_id": 1,
                        "shell_element_ids": [101],
                        "node_ids": [1001],
                    }
                ],
                "urban_components": {
                    "commercial_supermarket": {
                        "part_ids": [19],
                        "constraint_mode": "fixed",
                    }
                },
            },
        }
        (path / "model.json").write_text(json.dumps(model), encoding="utf-8")
        problem_time = 0.03 if complete else 0.001
        termination = "Normal termination\n" if complete else ""
        (path / "d3hsp").write_text(
            f"Problem time = {problem_time:.6E}\nProblem cycle = 100\n{termination}",
            encoding="utf-8",
        )
        (path / "glstat").write_text(
            (
                " time...........................   0.00000E+00\n"
                " total energy / initial energy..   1.00000E+00\n"
                f" time...........................   {problem_time:.6E}\n"
                " total energy / initial energy..   1.01000E+00\n"
            ),
            encoding="utf-8",
        )
        (path / "dbfsi").write_text(
            (
                "time= 0.00000E+00\n"
                "1 0.0 0.0 0.0 0.0 0.0\n"
                "time= 1.00000E-03\n"
                "1 1000.0 10.0 0.0 0.0 0.0\n"
                "time= 2.00000E-03\n"
                "1 500.0 5.0 0.0 0.0 0.0\n"
                f"time= {problem_time:.6E}\n"
                "1 0.0 0.0 0.0 0.0 0.0\n"
            ),
            encoding="utf-8",
        )
        if not complete:
            return
        structural_peak_pa = max(200.0, abs(float(peak_pressure_pa)) * 10.0)
        (path / "elout").write_text(
            (
                "element stress calculations for time step 1 ( at time 0.000 )\n"
                "    101-      3\n"
                "      1- 1 lower 0 0 0 0 0 0 0\n"
                "element stress calculations for time step 2 ( at time 0.001 )\n"
                "    101-      3\n"
                f"      1- 1 lower -{structural_peak_pa:.6g} -{structural_peak_pa:.6g} "
                f"-{structural_peak_pa:.6g} 0 0 0 0\n"
                "element stress calculations for time step 3 ( at time 0.002 )\n"
                "    101-      3\n"
                f"      1- 1 lower -{structural_peak_pa:.6g} -{structural_peak_pa:.6g} "
                f"-{structural_peak_pa:.6g} 0 0 0 0\n"
                f"element stress calculations for time step 4 ( at time {problem_time:.6E} )\n"
                "    101-      3\n"
                "      1- 1 lower -1 -1 -1 0 0 0 0\n"
            ),
            encoding="utf-8",
        )
        (path / "nodout").write_text(
            (
                "nodal print out for time step 1 ( at time 0.000 )\n"
                "nodal point  x-disp     y-disp      z-disp      x-vel\n"
                "1001 0 0 0 0\n"
                f"nodal print out for time step 2 ( at time {problem_time:.6E} )\n"
                "nodal point  x-disp     y-disp      z-disp      x-vel\n"
                "1001 0.001 0 0 0\n"
            ),
            encoding="utf-8",
        )
        (path / "d3plot").write_bytes(b"d3plot\n")
        (path / "d3plot01").write_bytes(b"d3plot01\n")
        artifacts = path / "artifacts"
        artifacts.mkdir()
        model_hash = hashlib.sha256((path / "model.k").read_bytes()).hexdigest()
        evidence = {}
        for name in (
            "d3hsp",
            "dbfsi",
            "glstat",
            "elout",
            "nodout",
            "d3plot",
            "d3plot01",
        ):
            evidence_path = path / name
            evidence[name] = {
                "size_bytes": evidence_path.stat().st_size,
                "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            }
        evidence_digest = hashlib.sha256(
            json.dumps(
                evidence,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        material_sha256 = hashlib.sha256(
            json.dumps(
                resolved_spec["material"],
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        metrics = {
            "schema_version": CITY_METRICS_SCHEMA_VERSION,
            "model_sha256": model_hash,
            "result_evidence_digest": evidence_digest,
            "source": "unit_test_postprocessor",
            "threshold_profile": {
                "status": "user_confirmed",
                "source": "unit test thresholds",
                "binding": {
                    "model_sha256": model_hash,
                    "material_sha256": material_sha256,
                    "applicability": {
                        "model_type": "city_street_blast_scene",
                        "categories": ["commercial_building"],
                    },
                },
                "limits": {
                    "commercial_building": {
                        "peak_pressure_pa": {
                            "attention": 10.0,
                            "high": 30.0,
                            "severe": 50.0,
                        }
                    }
                },
            },
            "objects": {
                "commercial_supermarket": {
                    "peak_pressure_pa": peak_pressure_pa,
                    "pressure_impulse_pa_s": 2.0,
                }
            },
        }
        (artifacts / "city_impact_metrics.json").write_text(
            json.dumps(metrics),
            encoding="utf-8",
        )

    def _register_surrogate_study(
        self,
        study_id: str,
        *,
        response=None,
    ) -> None:
        response_fn = response or (
            lambda mass, mesh: 0.02 * mass + (4.0 if mesh == 0.2 else 0.0)
        )
        matrix = create_controlled_case_matrix(
            self.reference,
            study_id,
            {
                "tnt_mass_kg": [100.0, 150.0, 200.0],
                "near_mesh_size_m": [0.2, 0.15],
            },
        )
        for index, case in enumerate(matrix["cases"], start=1):
            parameters = case["parameters"]
            sample_path = project_dir(
                f"unit_phase16b_{study_id}_{index}"
            )
            self.extra_projects.append(sample_path)
            self._write_city_project(
                sample_path,
                tnt_mass_kg=parameters["tnt_mass_kg"],
                mesh_size_m=parameters["near_mesh_size_m"],
                complete=True,
                peak_pressure_pa=response_fn(
                    parameters["tnt_mass_kg"],
                    parameters["near_mesh_size_m"],
                ),
            )
            register_case_result(
                self.reference,
                study_id,
                case["case_id"],
                sample_path,
            )

    def _register_protection_study(self, study_id: str) -> dict[float, str]:
        matrix = create_controlled_case_matrix(
            self.reference,
            study_id,
            {"blast_center_x_m": [0.0, 5.0, 10.0]},
        )
        pressure_by_x = {0.0: 100.0, 5.0: 65.0, 10.0: 50.0}
        case_ids: dict[float, str] = {}
        for index, case in enumerate(matrix["cases"], start=1):
            blast_x = float(case["parameters"]["blast_center_x_m"])
            sample_path = project_dir(
                f"unit_phase16b_{study_id}_{index}"
            )
            self.extra_projects.append(sample_path)
            self._write_city_project(
                sample_path,
                tnt_mass_kg=100.0,
                mesh_size_m=0.2,
                complete=True,
                peak_pressure_pa=pressure_by_x[blast_x],
                blast_center_x_m=blast_x,
            )
            register_case_result(
                self.reference,
                study_id,
                case["case_id"],
                sample_path,
            )
            case_ids[blast_x] = case["case_id"]
        return case_ids


if __name__ == "__main__":
    unittest.main()
