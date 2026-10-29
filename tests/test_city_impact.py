from __future__ import annotations

import hashlib
import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

import lsprepost_mcp.city_impact as city_impact_module
from lsprepost_mcp.city_impact import (
    CITY_METRICS_SCHEMA_VERSION,
    build_city_impact_assessment,
    write_city_impact_report,
)
from lsprepost_mcp.city_result_source import (
    register_city_result_source,
    resolve_city_result_source,
)
from lsprepost_mcp.paths import project_dir

from tests.test_web_api import request_json, web_test_server


class CityImpactAssessmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = project_dir("unit_phase16a_city_impact")
        if self.project.exists():
            shutil.rmtree(self.project)
        self.project.mkdir(parents=True)
        (self.project / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")
        self._write_model(end_time_s=0.01)
        self._write_complete_solver_outputs(problem_time_s=0.01)

    def tearDown(self) -> None:
        if self.project.exists():
            shutil.rmtree(self.project)

    def test_short_smoke_is_never_reported_as_low_risk(self) -> None:
        self._write_complete_solver_outputs(
            problem_time_s=0.001,
            sense_switch=True,
        )

        result = build_city_impact_assessment(self.project)

        self.assertEqual("incomplete_solver_result", result["status"])
        self.assertFalse(result["ready_for_risk"])
        self.assertIn(
            "solver.complete_time_coverage",
            result["quality"]["blocking_check_ids"],
        )
        self.assertTrue(result["objects"])
        self.assertEqual(
            {"unavailable"},
            {item["risk"]["level"] for item in result["objects"]},
        )

    def test_complete_result_with_confirmed_metrics_can_be_classified(self) -> None:
        self._prepare_registered_result()
        model_hash = self._model_hash()
        metrics = {
            "schema_version": "phase16a.city_object_metrics.v1",
            "model_sha256": model_hash,
            "source": "unit_test_postprocessor",
            "threshold_profile": {
                "status": "user_confirmed",
                "source": "unit test threshold table",
                "binding": self._threshold_binding(),
                "limits": {
                    "commercial_building": {
                        "peak_pressure_pa": {
                            "attention": 10.0,
                            "high": 20.0,
                            "severe": 30.0,
                        }
                    }
                },
            },
            "objects": {
                "commercial_supermarket": {
                    "peak_pressure_pa": 35.0,
                    "pressure_impulse_pa_s": 2.0,
                }
            },
        }
        artifacts = self.project / "artifacts"
        artifacts.mkdir(exist_ok=True)
        (artifacts / "city_impact_metrics.json").write_text(
            json.dumps(metrics),
            encoding="utf-8",
        )

        result = build_city_impact_assessment(self.project)

        self.assertEqual("ready", result["status"])
        self.assertTrue(result["ready_for_risk"])
        supermarket = next(
            item
            for item in result["objects"]
            if item["object_id"] == "commercial_supermarket"
        )
        self.assertEqual("severe", supermarket["risk"]["level"])
        self.assertEqual("严重", supermarket["risk"]["label"])
        vehicle = next(
            item
            for item in result["objects"]
            if item["object_id"] == "residential_community"
        )
        self.assertEqual("unavailable", vehicle["risk"]["level"])
        self.assertEqual("severe", result["part_risk"]["19"])

    def test_stale_metrics_cannot_substitute_for_valid_result_source(self) -> None:
        artifacts = self.project / "artifacts"
        artifacts.mkdir()
        (artifacts / "city_impact_metrics.json").write_text(
            json.dumps(
                {
                    "schema_version": CITY_METRICS_SCHEMA_VERSION,
                    "model_sha256": "0" * 64,
                    "source": "stale",
                    "objects": {},
                }
            ),
            encoding="utf-8",
        )

        result = build_city_impact_assessment(self.project)

        self.assertEqual("incomplete_solver_result", result["status"])
        self.assertFalse(result["ready_for_risk"])
        self.assertIn(
            "result_source.valid",
            result["response_acceptance"]["blocking_check_ids"],
        )

    def test_legacy_v1_metrics_remain_visible_but_cannot_replace_result_evidence(
        self,
    ) -> None:
        artifacts = self.project / "artifacts"
        artifacts.mkdir()
        (artifacts / "city_impact_metrics.json").write_text(
            json.dumps(
                {
                    "schema_version": "phase16a.city_object_metrics.v1",
                    "model_sha256": self._model_hash(),
                    "source": "legacy_postprocessor",
                    "objects": {
                        "commercial_supermarket": {
                            "peak_pressure_pa": 350.0,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        result = build_city_impact_assessment(self.project)

        supermarket = self._object(result, "commercial_supermarket")
        self.assertEqual(
            "phase16a.city_object_metrics.v1",
            result["metrics_contract"]["schema_version"],
        )
        self.assertTrue(supermarket["metrics"]["peak_pressure_pa"]["available"])
        self.assertEqual("failed", result["response_acceptance"]["status"])
        self.assertEqual("unavailable", supermarket["risk"]["level"])

    def test_evidence_bound_v2_legacy_metric_survives_response_regeneration(self) -> None:
        self._prepare_registered_result()
        source = resolve_city_result_source(self.project)
        evidence_digest = hashlib.sha256(
            json.dumps(
                source["evidence"],
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        metrics_path = self.project / "artifacts" / "city_impact_metrics.json"
        metrics_path.write_text(
            json.dumps(
                {
                    "schema_version": CITY_METRICS_SCHEMA_VERSION,
                    "model_sha256": self._model_hash(),
                    "result_evidence_digest": evidence_digest,
                    "source": "phase16b_unit_test",
                    "threshold_profile": {
                        "status": "missing",
                        "source": "",
                        "limits": {},
                    },
                    "objects": {
                        "commercial_supermarket": {
                            "peak_pressure_pa": 35.0,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        result = build_city_impact_assessment(self.project)

        building = self._object(result, "commercial_supermarket")
        self.assertEqual(35.0, building["metrics"]["peak_pressure_pa"]["value"])
        regenerated = json.loads(metrics_path.read_text(encoding="utf-8"))
        self.assertEqual(
            35.0,
            regenerated["objects"]["commercial_supermarket"]["peak_pressure_pa"],
        )

    def test_report_and_web_endpoints_use_same_assessment(self) -> None:
        self._prepare_registered_result()
        report = write_city_impact_report(self.project)

        self.assertTrue((self.project / report["relative_json_path"]).is_file())
        html_path = self.project / report["relative_html_path"]
        self.assertTrue(html_path.is_file())
        self.assertIn("城市爆炸影响评估", html_path.read_text(encoding="utf-8"))

        with web_test_server() as address:
            get_status, get_payload = request_json(
                address,
                "GET",
                "/api/project/city-impact?project_name=unit_phase16a_city_impact",
            )
            post_status, post_payload = request_json(
                address,
                "POST",
                "/api/project/city-impact-report",
                {"project_name": "unit_phase16a_city_impact"},
            )

        self.assertEqual(200, get_status)
        self.assertEqual("city_impact_assessment", get_payload["result"]["operation"])
        self.assertEqual("phase16a.city_impact.v1", get_payload["result"]["schema_version"])
        self.assertTrue(all(item["risk"]["level"] == "unavailable" for item in get_payload["result"]["objects"]))
        self.assertEqual("awaiting_threshold_profile", get_payload["result"]["status"])
        self.assertEqual(200, post_status)
        self.assertEqual(
            "write_city_impact_report",
            post_payload["result"]["operation"],
        )
        self.assertEqual("artifacts/city_impact_assessment.json", post_payload["result"]["relative_json_path"])
        self.assertEqual("artifacts/city_impact_report.html", post_payload["result"]["relative_html_path"])

    def test_assessment_accepts_spaced_normal_termination(self) -> None:
        self._prepare_registered_result(spaced_termination=True)

        result = build_city_impact_assessment(self.project)

        self.assertNotIn(
            "solver.normal_termination",
            result["quality"]["blocking_check_ids"],
        )
        self.assertEqual(
            "normal",
            result["quality"]["global_metrics"]["termination"],
        )

    def test_adverse_termination_markers_override_normal_text(self) -> None:
        cases = {
            "abnormal": ("abnormal termination", "abnormal"),
            "mixed": ("Normal termination\nabnormal termination", "abnormal"),
            "sense_switch": (
                (
                    "N o r m a l    t e r m i n a t i o n\n"
                    "*** termination due to sense switch: sw1. ***"
                ),
                "stopped_by_sense_switch",
            ),
        }
        for case_name, (termination_text, expected_state) in cases.items():
            with self.subTest(case=case_name):
                self._prepare_registered_result(
                    termination_text=termination_text,
                )

                result = build_city_impact_assessment(self.project)

                self.assertIn(
                    "solver.normal_termination",
                    result["quality"]["blocking_check_ids"],
                )
                self.assertEqual(
                    expected_state,
                    result["quality"]["global_metrics"]["termination"],
                )

    def test_time_coverage_gate_uses_exact_99_percent_boundary(self) -> None:
        cases = (
            (0.989, False),
            (0.990, True),
        )
        for coverage, expected_ok in cases:
            with self.subTest(coverage=coverage):
                self._prepare_registered_result(
                    result_problem_time_s=0.03 * coverage,
                )

                result = build_city_impact_assessment(self.project)

                blocked = (
                    "solver.complete_time_coverage"
                    in result["quality"]["blocking_check_ids"]
                )
                self.assertEqual(expected_ok, not blocked)

    def test_assessment_reads_registered_result_instead_of_project_root(self) -> None:
        self._prepare_registered_result(project_problem_time_s=0.001)

        result = build_city_impact_assessment(self.project)

        self.assertEqual("registered_external", result["result_source"]["source_kind"])
        self.assertEqual(1.0, result["quality"]["global_metrics"]["time_coverage_ratio"])

    def test_assessment_builds_object_metrics_from_registered_result(self) -> None:
        self._prepare_registered_result()

        result = build_city_impact_assessment(self.project)

        building = next(
            item
            for item in result["objects"]
            if item["object_id"] == "commercial_supermarket"
        )
        self.assertEqual(
            "phase17.city_object_metrics.v2",
            result["metrics_contract"]["schema_version"],
        )
        self.assertTrue(building["metrics"]["peak_fsi_pressure_rise_pa"]["available"])
        self.assertTrue(
            building["metrics"]["fsi_positive_pressure_impulse_pa_s"]["available"]
        )
        self.assertTrue(
            building["metrics"]["peak_structural_pressure_pa"]["available"]
        )
        self.assertTrue(
            building["metrics"]["peak_principal_stress_pa"]["available"]
        )
        self.assertTrue(building["metrics"]["peak_displacement_m"]["available"])
        self.assertEqual("unavailable", building["risk"]["level"])

    def test_demo_or_unbound_thresholds_cannot_produce_formal_risk(self) -> None:
        self._prepare_registered_result()
        binding = self._threshold_binding()
        profiles = (
            {
                "status": "demo_unvalidated",
                "source": "demo thresholds",
                "limits": self._commercial_pressure_limits(),
                "binding": binding,
            },
            {
                "status": "user_confirmed",
                "source": "legacy unbound thresholds",
                "limits": self._commercial_pressure_limits(),
            },
        )
        for profile in profiles:
            with self.subTest(status=profile["status"]):
                self._write_legacy_metrics(profile)

                result = build_city_impact_assessment(self.project)

                building = self._object(result, "commercial_supermarket")
                self.assertFalse(result["ready_for_risk"])
                self.assertEqual("unavailable", building["risk"]["level"])

    def test_threshold_binding_must_match_model_material_and_applicability(self) -> None:
        self._prepare_registered_result()
        valid_binding = self._threshold_binding()
        invalid_bindings = (
            {**valid_binding, "model_sha256": "0" * 64},
            {**valid_binding, "material_sha256": "0" * 64},
            {
                **valid_binding,
                "applicability": {
                    "model_type": "city_street_blast_scene",
                    "categories": ["street_equipment"],
                },
            },
        )
        for binding in invalid_bindings:
            with self.subTest(binding=binding):
                self._write_legacy_metrics(
                    {
                        "status": "reviewed",
                        "source": "reviewed thresholds",
                        "limits": self._commercial_pressure_limits(),
                        "binding": binding,
                    }
                )

                result = build_city_impact_assessment(self.project)

                self.assertFalse(result["ready_for_risk"])
                self.assertEqual(
                    "unavailable",
                    self._object(result, "commercial_supermarket")["risk"]["level"],
                )

    def test_source_mutation_before_metrics_commit_is_invalid_evidence(self) -> None:
        external = self._prepare_registered_result()
        build_city_impact_assessment(self.project)
        metrics_path = self.project / "artifacts" / "city_impact_metrics.json"
        previous_metrics = metrics_path.read_bytes()
        stable_source = resolve_city_result_source(self.project)
        call_count = 0

        def resolving(project: Path) -> dict[str, object]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return stable_source
            with (external / "dbfsi").open("a", encoding="utf-8") as stream:
                stream.write("$ mutated during assessment\n")
            return resolve_city_result_source(project)

        with mock.patch.object(
            city_impact_module,
            "resolve_city_result_source",
            side_effect=resolving,
        ):
            result = build_city_impact_assessment(self.project)

        self.assertEqual(2, call_count)
        self.assertEqual(previous_metrics, metrics_path.read_bytes())
        self.assertFalse(result["result_source"]["validation"]["ok"])
        self.assertIn(
            "result_source.invalid_evidence",
            result["response_acceptance"]["blocking_check_ids"],
        )
        self.assertIn(
            "invalid_evidence",
            " ".join(result["metrics_contract"]["issues"]),
        )

    def test_missing_required_response_object_does_not_shrink_denominator(self) -> None:
        self._prepare_registered_result()
        real_parser = city_impact_module.parse_city_object_responses

        def omit_residential(*args: object, **kwargs: object) -> dict[str, object]:
            parsed = real_parser(*args, **kwargs)
            parsed.pop("residential_community")
            return parsed

        with mock.patch.object(
            city_impact_module,
            "parse_city_object_responses",
            side_effect=omit_residential,
        ):
            result = build_city_impact_assessment(self.project)

        acceptance = result["response_acceptance"]
        residential = acceptance["objects"]["residential_community"]
        self.assertEqual(2, acceptance["required_object_count"])
        self.assertEqual("failed", residential["status"])
        self.assertIn(
            "residential_community.result_present",
            residential["blocking_check_ids"],
        )

    def test_explicit_required_response_ids_control_denominator(self) -> None:
        self._prepare_registered_result(
            required_response_object_ids=["commercial_supermarket"],
        )

        result = build_city_impact_assessment(self.project)

        self.assertEqual(1, result["response_acceptance"]["required_object_count"])
        self.assertEqual(
            {"commercial_supermarket"},
            set(result["response_acceptance"]["objects"]),
        )

    def test_partial_acceptance_when_one_object_has_short_observation_window(self) -> None:
        self._prepare_registered_result(residential_arrival_time_s=0.014)

        result = build_city_impact_assessment(self.project)

        self.assertEqual("partial", result["response_acceptance"]["status"])
        self.assertIn(
            "residential_community.observation_window",
            result["response_acceptance"]["blocking_check_ids"],
        )

    def test_global_dbfsi_metrics_aggregate_all_surfaces(self) -> None:
        self._prepare_registered_result()

        result = build_city_impact_assessment(self.project)

        object_impulse = sum(
            item["response"]["fsi_positive_pressure_impulse_pa_s"]
            for item in result["objects"]
            if item["response"].get("fsi_present")
        )
        global_fsi = result["quality"]["global_metrics"]["fsi"]
        self.assertEqual(2, global_fsi["surface_count"])
        self.assertAlmostEqual(
            object_impulse,
            global_fsi["positive_pressure_impulse_pa_s"],
        )

    def test_large_street_equipment_displacement_is_nonblocking_anomaly(self) -> None:
        self._prepare_registered_result(
            residential_category="street_equipment",
            residential_displacement_m=0.3,
        )

        result = build_city_impact_assessment(self.project)

        anomaly = next(
            item
            for item in result["anomalies"]
            if item["object_id"] == "residential_community"
        )
        self.assertEqual("passed", result["response_acceptance"]["status"])
        self.assertFalse(anomaly["blocking"])
        self.assertEqual(0.02, anomaly["limit"])
        self.assertEqual("unavailable", self._object(result, "residential_community")["risk"]["level"])

    def _write_model(self, end_time_s: float) -> None:
        model = {
            "schema_version": 1,
            "spec": {"analysis": {"end_time_s": end_time_s}},
            "metadata": {
                "model_type": "city_street_blast_scene",
                "urban_components": {
                    "commercial_supermarket": {
                        "part_ids": [19],
                        "constraint_mode": "fixed",
                    },
                    "parked_vehicles": {
                        "part_ids": [26, 27],
                        "constraint_mode": "free",
                    },
                },
                "response_objects": [
                    {
                        "object_id": "commercial_supermarket",
                        "fsi_surface_id": 111,
                        "shell_element_ids": [101],
                        "node_ids": [1001],
                    },
                    {
                        "object_id": "parked_vehicle_1",
                        "fsi_surface_id": 112,
                        "shell_element_ids": [102],
                        "node_ids": [1002],
                    },
                    {
                        "object_id": "parked_vehicle_2",
                        "fsi_surface_id": 113,
                        "shell_element_ids": [103],
                        "node_ids": [1003],
                    },
                ],
            },
        }
        (self.project / "model.json").write_text(
            json.dumps(model),
            encoding="utf-8",
        )

    def _prepare_registered_result(
        self,
        *,
        spaced_termination: bool = False,
        project_problem_time_s: float = 0.03,
        residential_arrival_time_s: float = 0.009,
        residential_category: str = "residential_building",
        residential_displacement_m: float = 0.002,
        result_problem_time_s: float = 0.03,
        termination_text: str | None = None,
        required_response_object_ids: list[str] | None = None,
    ) -> Path:
        end_time_s = 0.03
        model = {
            "schema_version": 1,
            "spec": {
                "analysis": {"end_time_s": end_time_s},
                "material": {
                    "name": "unit_test_concrete",
                    "type": "elastic",
                    "density_kg_per_m3": 2400.0,
                    "youngs_pa": 30.0e9,
                    "poisson": 0.2,
                },
            },
            "metadata": {
                "model_type": "city_street_blast_scene",
                "semantic_objects": [
                    {
                        "object_id": "commercial_supermarket",
                        "group_id": "commercial_supermarket",
                        "label": "商业超市",
                        "category": "commercial_building",
                        "part_ids": [19],
                        "constraint_mode": "base_fixed",
                        "bounds_m": {
                            "min": [0.0, 0.0, 0.0],
                            "max": [10.0, 8.0, 5.0],
                        },
                    },
                    {
                        "object_id": "residential_community",
                        "group_id": "residential_community",
                        "label": "住宅小区",
                        "category": residential_category,
                        "part_ids": [20],
                        "constraint_mode": "base_fixed",
                        "bounds_m": {
                            "min": [0.0, 0.0, 0.0],
                            "max": [12.0, 10.0, 8.0],
                        },
                    },
                ],
                "response_objects": [
                    {
                        "object_id": "commercial_supermarket",
                        "fsi_surface_id": 111,
                        "shell_element_ids": [101],
                        "node_ids": [1001],
                    },
                    {
                        "object_id": "residential_community",
                        "fsi_surface_id": 112,
                        "shell_element_ids": [102],
                        "node_ids": [1002],
                    },
                ],
            },
        }
        if required_response_object_ids is not None:
            model["metadata"]["required_response_object_ids"] = (
                required_response_object_ids
            )
        (self.project / "model.json").write_text(
            json.dumps(model),
            encoding="utf-8",
        )
        external = self.project / "_registered_result"
        if external.exists():
            shutil.rmtree(external)
        external.mkdir()
        shutil.copy2(self.project / "model.k", external / "model.k")
        shutil.copy2(self.project / "model.json", external / "model.json")

        termination = termination_text or (
            "N o r m a l    t e r m i n a t i o n"
            if spaced_termination
            else "Normal termination"
        )
        self._write_response_outputs(
            external,
            problem_time_s=result_problem_time_s,
            termination=termination,
            residential_arrival_time_s=residential_arrival_time_s,
            residential_displacement_m=residential_displacement_m,
        )
        self._write_response_outputs(
            self.project,
            problem_time_s=project_problem_time_s,
            termination=termination,
            residential_arrival_time_s=residential_arrival_time_s,
            residential_displacement_m=residential_displacement_m,
        )
        register_city_result_source(self.project, external)
        return external

    def _write_response_outputs(
        self,
        directory: Path,
        *,
        problem_time_s: float,
        termination: str,
        residential_arrival_time_s: float,
        residential_displacement_m: float,
    ) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "d3hsp").write_text(
            (
                f"Problem time = {problem_time_s:.6E}\n"
                "Problem cycle = 100\n"
                f"{termination}\n"
            ),
            encoding="utf-8",
        )
        (directory / "glstat").write_text(
            (
                " time...........................   0.00000E+00\n"
                " total energy / initial energy..   1.00000E+00\n"
                f" time...........................   {problem_time_s:.6E}\n"
                " total energy / initial energy..   1.01000E+00\n"
            ),
            encoding="utf-8",
        )
        (directory / "dbfsi").write_text(
            (
                "time=0.000\n"
                "111 0 0 0 0 0\n"
                "112 0 0 0 0 0\n"
                "time=0.005\n"
                "111 2000 20 0 0 0\n"
                "112 0 0 0 0 0\n"
                "time=0.006\n"
                "111 1000 10 0 0 0\n"
                "112 0 0 0 0 0\n"
                f"time={residential_arrival_time_s:.3f}\n"
                "111 0 0 0 0 0\n"
                "112 1200 12 0 0 0\n"
                f"time={residential_arrival_time_s + 0.001:.3f}\n"
                "111 0 0 0 0 0\n"
                "112 600 6 0 0 0\n"
                f"time={problem_time_s:.3f}\n"
                "111 0 0 0 0 0\n"
                "112 0 0 0 0 0\n"
            ),
            encoding="utf-8",
        )
        (directory / "elout").write_text(
            (
                "element stress calculations for time step 1 ( at time 0.000 )\n"
                "    101-      3\n"
                "      1- 1 lower 0 0 0 0 0 0 0\n"
                "    102-      3\n"
                "      1- 1 lower 0 0 0 0 0 0 0\n"
                "element stress calculations for time step 2 ( at time 0.005 )\n"
                "    101-      3\n"
                "      1- 1 lower -300 -300 -300 0 0 0 0\n"
                "    102-      3\n"
                "      1- 1 lower 0 0 0 0 0 0 0\n"
                "element stress calculations for time step 3 ( at time 0.006 )\n"
                "    101-      3\n"
                "      1- 1 lower -200 -200 -200 0 0 0 0\n"
                "    102-      3\n"
                "      1- 1 lower 0 0 0 0 0 0 0\n"
                "element stress calculations for time step 4 "
                f"( at time {residential_arrival_time_s:.3f} )\n"
                "    101-      3\n"
                "      1- 1 lower -50 -50 -50 0 0 0 0\n"
                "    102-      3\n"
                "      1- 1 lower -240 -240 -240 0 0 0 0\n"
                "element stress calculations for time step 5 "
                f"( at time {residential_arrival_time_s + 0.001:.3f} )\n"
                "    101-      3\n"
                "      1- 1 lower -30 -30 -30 0 0 0 0\n"
                "    102-      3\n"
                "      1- 1 lower -180 -180 -180 0 0 0 0\n"
                "element stress calculations for time step 6 "
                f"( at time {problem_time_s:.3f} )\n"
                "    101-      3\n"
                "      1- 1 lower -10 -10 -10 0 0 0 0\n"
                "    102-      3\n"
                "      1- 1 lower -10 -10 -10 0 0 0 0\n"
            ),
            encoding="utf-8",
        )
        (directory / "nodout").write_text(
            (
                "nodal print out for time step 1 ( at time 0.000 )\n"
                "nodal point  x-disp     y-disp      z-disp      x-vel\n"
                "1001 0 0 0 0\n"
                "1002 0 0 0 0\n"
                f"nodal print out for time step 2 ( at time {problem_time_s:.3f} )\n"
                "nodal point  x-disp     y-disp      z-disp      x-vel\n"
                "1001 0.001 0 0 0\n"
                f"1002 {residential_displacement_m:.6g} 0 0 0\n"
            ),
            encoding="utf-8",
        )
        (directory / "d3plot").write_bytes(b"d3plot\n")
        (directory / "d3plot01").write_bytes(b"d3plot01\n")

    @staticmethod
    def _object(result: dict[str, object], object_id: str) -> dict[str, object]:
        return next(
            item
            for item in result["objects"]
            if item["object_id"] == object_id
        )

    def _threshold_binding(self) -> dict[str, object]:
        model = json.loads((self.project / "model.json").read_text(encoding="utf-8"))
        material = model["spec"]["material"]
        material_sha256 = hashlib.sha256(
            json.dumps(
                material,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return {
            "model_sha256": self._model_hash(),
            "material_sha256": material_sha256,
            "applicability": {
                "model_type": "city_street_blast_scene",
                "categories": ["commercial_building"],
            },
        }

    @staticmethod
    def _commercial_pressure_limits() -> dict[str, object]:
        return {
            "commercial_building": {
                "peak_pressure_pa": {
                    "attention": 10.0,
                    "high": 20.0,
                    "severe": 30.0,
                }
            }
        }

    def _write_legacy_metrics(self, threshold_profile: dict[str, object]) -> None:
        path = self.project / "artifacts" / "city_impact_metrics.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": "phase16a.city_object_metrics.v1",
                    "model_sha256": self._model_hash(),
                    "source": "unit_test_postprocessor",
                    "threshold_profile": threshold_profile,
                    "objects": {
                        "commercial_supermarket": {
                            "peak_pressure_pa": 35.0,
                            "pressure_impulse_pa_s": 2.0,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    def _write_complete_solver_outputs(
        self,
        problem_time_s: float,
        sense_switch: bool = False,
    ) -> None:
        termination = (
            "*** termination due to sense switch: sw1. ***\n"
            if sense_switch
            else ""
        )
        (self.project / "d3hsp").write_text(
            (
                f"{termination}"
                f"Problem time = {problem_time_s:.6E}\n"
                "Problem cycle = 100\n"
                "Normal termination\n"
            ),
            encoding="utf-8",
        )
        (self.project / "glstat").write_text(
            (
                " time...........................   0.00000E+00\n"
                " total energy / initial energy..   1.00000E+00\n"
                f" time...........................   {problem_time_s:.6E}\n"
                " total energy / initial energy..   1.01000E+00\n"
            ),
            encoding="utf-8",
        )
        (self.project / "dbfsi").write_text(
            (
                "time= 0.00000E+00\n"
                "1 0.0000E+00 0.0000E+00 0.0000E+00 0.0000E+00 0.0000E+00\n"
                f"time= {problem_time_s:.6E}\n"
                "1 1.0000E+01 1.0000E+00 2.0000E+00 3.0000E+00 0.0000E+00\n"
            ),
            encoding="utf-8",
        )
        (self.project / "matsum").write_text(
            (
                "time = 0.0000E+00\n"
                "mat.#= 19 inten= 0.0000E+00 kinen= 0.0000E+00 eroded_ie= 0.0 eroded_ke= 0.0\n"
                "mat.#= 26 inten= 0.0000E+00 kinen= 0.0000E+00 eroded_ie= 0.0 eroded_ke= 0.0\n"
                f"time = {problem_time_s:.6E}\n"
                "mat.#= 19 inten= 2.0000E+00 kinen= 3.0000E+00 eroded_ie= 0.0 eroded_ke= 0.0\n"
                "mat.#= 26 inten= 4.0000E+00 kinen= 5.0000E+00 eroded_ie= 0.0 eroded_ke= 0.0\n"
            ),
            encoding="utf-8",
        )

    def _model_hash(self) -> str:
        return hashlib.sha256((self.project / "model.k").read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
