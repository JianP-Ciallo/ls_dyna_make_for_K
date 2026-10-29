from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lsprepost_mcp.lsdyna_runner import (
    CITY_REQUIRED_EVIDENCE,
    _city_wave_transfer_acceptance,
    _evaluate_d3hsp,
    _phase15_wave_transfer_acceptance,
    _result_mode,
    _result_variant,
    execute_lsdyna_initialization_smoke,
    execute_lsdyna_run,
    latest_lsdyna_run,
    parse_run_options,
    record_blast_pressure_history,
    record_lsprepost_postprocessing,
)
from lsprepost_mcp.run_evidence import seal_phase14_run_evidence
from lsprepost_mcp.solver_results import parse_dbfsi


VALID_D3HSP = """
 kinetic energy.................   8.00000E+01
 internal energy................   1.50000E+01
 hourglass energy ..............   5.00000E+00
 total energy...................   1.00000E+02
 total energy / initial energy..   1.01000E+00
 *** termination time reached ***
"""
VALID_NODOUT = """
 n o d a l   p r i n t   o u t   f o r   t i m e  s t e p      25 ( at time 1.0000000E-03 )
 nodal point  x-disp     y-disp      z-disp      x-vel
       10  3.00000E-03-4.00000E-03 0.00000E+00 0.0
"""


class FakeProcess:
    pid = 4321

    def __init__(self, returncode: int = 0, timeout: bool = False) -> None:
        self.returncode = returncode
        self.timeout = timeout

    def wait(self, timeout: float | None = None) -> int:
        if self.timeout:
            raise subprocess.TimeoutExpired("lsdyna", timeout)
        return self.returncode


class LsDynaRunnerTests(unittest.TestCase):
    def test_city_required_evidence_includes_object_histories(self) -> None:
        self.assertIn("elout", CITY_REQUIRED_EVIDENCE)
        self.assertIn("nodout", CITY_REQUIRED_EVIDENCE)

    def test_phase15_reactive_energy_release_is_not_treated_as_conservation_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "d3hsp").write_text(
                """
 kinetic energy.................   8.00000E+06
 internal energy................   1.90000E+07
 hourglass energy ..............   1.00000E+05
 total energy...................   2.70000E+07
 total energy / initial energy..   5.97094E+00
 *** termination time reached ***
 """,
                encoding="utf-8",
            )

            result = _evaluate_d3hsp(
                run_dir,
                "blast",
                "phase15_axisymmetric_blast",
            )

            self.assertTrue(result["ok"])
            check = next(
                item
                for item in result["checks"]
                if item["id"] == "ale_reactive_energy_ratio_finite"
            )
            self.assertTrue(check["ok"])
            self.assertAlmostEqual(5.97094, check["actual"])
            self.assertEqual(
                5.97094,
                result["metrics"]["reactive_total_initial_energy_ratio"],
            )

    def test_initialization_smoke_uses_bounded_memory_check_cycles(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._blast_project(Path(temp_dir) / "phase15_demo")
            solver = Path(temp_dir) / "lsdyna.exe"
            solver.write_bytes(b"fake solver")
            captured: list[str] = []

            def fake_popen(command, cwd, **_kwargs):
                captured.extend(command)
                run_dir = Path(cwd)
                (run_dir / "d3hsp").write_text(
                    "Memory required to begin solution: 103M\n"
                    "Problem cycle = 10\n"
                    "CPU time per zone cycle = 4037.305 nanoseconds\n"
                    "N o r m a l  t e r m i n a t i o n\n",
                    encoding="utf-8",
                )
                return FakeProcess()

            with patch("lsprepost_mcp.lsdyna_runner.subprocess.Popen", side_effect=fake_popen):
                result = execute_lsdyna_initialization_smoke(
                    project,
                    solver,
                    ncpu=4,
                    memory="1g",
                    timeout_s=30,
                )

            self.assertTrue(result["ok"])
            self.assertEqual(
                captured[1:],
                ["i=model.k", "ncpu=4", "memory=1g", "mcheck=y"],
            )
            self.assertEqual(result["evidence"]["maximum_cycle"], 10)
            self.assertTrue(result["evidence"]["memory_check_completed"])
            self.assertTrue(result["evidence"]["terminated_normally"])
            self.assertTrue((Path(result["smoke_dir"]) / "smoke.json").is_file())

    def test_initialization_smoke_rejects_zero_solver_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._blast_project(Path(temp_dir) / "phase15_demo")
            solver = Path(temp_dir) / "lsdyna.exe"
            solver.write_bytes(b"fake solver")

            def fake_popen(_command, cwd, **_kwargs):
                (Path(cwd) / "d3hsp").write_text(
                    "Memory required to begin solution: 103M\n"
                    "Problem cycle = 0\n"
                    "N o r m a l  t e r m i n a t i o n\n",
                    encoding="utf-8",
                )
                return FakeProcess()

            with patch("lsprepost_mcp.lsdyna_runner.subprocess.Popen", side_effect=fake_popen):
                result = execute_lsdyna_initialization_smoke(
                    project,
                    solver,
                    timeout_s=30,
                )

            self.assertFalse(result["ok"])
            self.assertEqual(0, result["evidence"]["maximum_cycle"])
            self.assertFalse(result["evidence"]["solver_cycles_completed"])

    def test_parse_dbfsi_extracts_pressure_force_and_impulse(self) -> None:
        result = parse_dbfsi(
            """Fluid-structure interaction output
time= 0.0
1 0.0 0.0 0.0 0.0 0.0
time= 0.1
1 20.0 0.0 0.0 10.0 0.0
time= 0.2
1 0.0 0.0 0.0 0.0 0.0
"""
        )
        self.assertEqual(result["peak_coupled_surface_pressure_pa"], 20.0)
        self.assertEqual(result["peak_resultant_force_n"], 10.0)
        self.assertAlmostEqual(result["fsi_impulse_magnitude_n_s"], 1.0)

    def test_parse_dbfsi_ignores_r12_continuation_row_integer_values(self) -> None:
        result = parse_dbfsi(
            """Fluid-structure interaction output
Number of surfaces: 1
time= 0.0
         1    0.0000E+00    0.0000E+00    0.0000E+00    0.0000E+00    0.0000E+00
              0.0000E+00    0.0000E+00    0.0000E+00    0.0000E+00    0.0000E+00    0.0000E+00
time= 0.1
         1    2.0000E+02    1.0000E+01    2.0000E+01    3.0000E+01    0.0000E+00
              0.2000E+01    0.0000E+00    0.0000E+00    0.0000E+00    0.0000E+00    0.0000E+00
time= 0.2
         1    0.0000E+00    0.0000E+00    0.0000E+00    0.0000E+00    0.0000E+00
              0.3000E+01    0.0000E+00    0.0000E+00    0.0000E+00    0.0000E+00    0.0000E+00
"""
        )

        self.assertEqual([1], result["surface_ids"])
        self.assertEqual(1, result["surface_count"])
        self.assertEqual(200.0, result["peak_pressure_rise_pa"])

    def test_phase14_ale_scene_is_classified_as_blast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "model.json").write_text(
                json.dumps({"spec": {"model_type": "ale_blast_scene", "loads": []}}),
                encoding="utf-8",
            )
            self.assertEqual(_result_mode(project), "blast")
            self.assertEqual(_result_variant(project), "ale_blast")

    def test_phase15_scene_is_classified_as_gated_ale_blast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._phase15_project(Path(tmp) / "phase15_demo")
            self.assertEqual(_result_mode(project), "blast")
            self.assertEqual(
                _result_variant(project),
                "phase15_axisymmetric_blast",
            )

    def test_city_scene_is_classified_as_gated_ale_blast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "model.json").write_text(
                json.dumps(
                    {
                        "spec": {
                            "model_type": "city_street_blast_scene",
                            "loads": [],
                        }
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(_result_mode(project), "blast")
            self.assertEqual(
                _result_variant(project),
                "city_street_blast",
            )

    def test_city_acceptance_requires_fsi_and_each_response_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "city"
            run_dir = Path(tmp) / "run"
            project.mkdir()
            run_dir.mkdir()
            model = {
                "metadata": {
                    "model_type": "city_street_blast_scene",
                    "fsi": {
                        "slave_segment_count": 12,
                        "fully_constrained_slave_segment_count": 0,
                    },
                    "semantic_objects": [
                        {
                            "object_id": "building",
                            "part_ids": [19],
                            "constraint_mode": "base_fixed",
                            "supports_ale_fsi": True,
                        }
                    ],
                }
            }
            (project / "model.json").write_text(
                json.dumps(model),
                encoding="utf-8",
            )
            (run_dir / "dbfsi").write_text(
                "\n".join(
                    [
                        "time= 0.0",
                        "1 0.0 0.0 0.0 0.0 0.0",
                        "time= 0.001",
                        "1 10000.0 0.0 0.0 1000.0 0.0",
                        "time= 0.002",
                        "1 0.0 0.0 0.0 0.0 0.0",
                    ]
                ),
                encoding="utf-8",
            )
            (run_dir / "matsum").write_text(
                "\n".join(
                    [
                        " time = 0.0000E+00",
                        " mat.#= 19 inten= 0.0000E+00 kinen= 0.0000E+00",
                        " time = 1.0000E-03",
                        " mat.#= 19 inten= 2.0000E+00 kinen= 3.0000E+00",
                    ]
                ),
                encoding="utf-8",
            )

            accepted = _city_wave_transfer_acceptance(project, run_dir)
            self.assertFalse(accepted["wave_transfer_verified"])
            self.assertIn(
                "city_object_response_contract",
                accepted["blocking_check_ids"],
            )
            self.assertEqual([], accepted["responding_object_ids"])

            (run_dir / "matsum").write_text(
                " time = 0.0000E+00\n"
                " mat.#= 19 inten= 0.0000E+00 kinen= 0.0000E+00\n",
                encoding="utf-8",
            )
            rejected = _city_wave_transfer_acceptance(project, run_dir)
            self.assertFalse(rejected["wave_transfer_verified"])
            self.assertIn(
                "city_response_objects",
                rejected["blocking_check_ids"],
            )

    def test_city_acceptance_rejects_matsum_only_object_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "city"
            run_dir = Path(tmp) / "run"
            project.mkdir()
            run_dir.mkdir()
            model = {
                "metadata": {
                    "model_type": "city_street_blast_scene",
                    "fsi": {
                        "slave_segment_count": 12,
                        "fully_constrained_slave_segment_count": 0,
                    },
                    "semantic_objects": [
                        {
                            "object_id": "building",
                            "part_ids": [19],
                            "constraint_mode": "base_fixed",
                            "supports_ale_fsi": True,
                        }
                    ],
                    "response_objects": [
                        {
                            "object_id": "building",
                            "part_id": 19,
                            "fsi_surface_id": 111,
                            "fsi_segment_count": 12,
                            "shell_element_ids": [101],
                            "node_ids": [1001],
                        }
                    ],
                }
            }
            (project / "model.json").write_text(
                json.dumps(model),
                encoding="utf-8",
            )
            (run_dir / "dbfsi").write_text(
                "\n".join(
                    [
                        "time= 0.0",
                        "111 0.0 0.0 0.0 0.0 0.0",
                        "time= 0.001",
                        "111 10000.0 0.0 0.0 1000.0 0.0",
                        "time= 0.002",
                        "111 5000.0 0.0 0.0 500.0 0.0",
                    ]
                ),
                encoding="utf-8",
            )
            (run_dir / "matsum").write_text(
                "\n".join(
                    [
                        " time = 0.0000E+00",
                        " mat.#= 19 inten= 0.0000E+00 kinen= 0.0000E+00",
                        " time = 1.0000E-03",
                        " mat.#= 19 inten= 2.0000E+00 kinen= 3.0000E+00",
                    ]
                ),
                encoding="utf-8",
            )

            result = _city_wave_transfer_acceptance(project, run_dir)

            self.assertFalse(result["wave_transfer_verified"])
            self.assertIn(
                "city_object_structural_response",
                result["blocking_check_ids"],
            )

    def test_city_acceptance_rejects_response_before_fsi_arrival(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "city"
            run_dir = Path(tmp) / "run"
            project.mkdir()
            run_dir.mkdir()
            response_object = {
                "object_id": "building",
                "part_id": 19,
                "fsi_surface_id": 111,
                "fsi_segment_count": 12,
                "shell_element_ids": [101],
                "node_ids": [1001],
            }
            (project / "model.json").write_text(
                json.dumps(
                    {
                        "spec": {
                            "analysis": {
                                "history_dt_s": 0.0001,
                                "end_time_s": 0.05,
                            }
                        },
                        "metadata": {
                            "fsi": {
                                "slave_segment_count": 12,
                                "fully_constrained_slave_segment_count": 0,
                            },
                            "response_objects": [response_object],
                            "semantic_objects": [
                                {
                                    "object_id": "building",
                                    "part_ids": [19],
                                    "bounds_m": {
                                        "min": [0.0, 0.0, 0.0],
                                        "max": [10.0, 10.0, 5.0],
                                    },
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "dbfsi").write_text(
                "time=0\n111 0 0 0 0 0\n"
                "time=0.001\n111 1000 10 0 0 0\n",
                encoding="utf-8",
            )
            (run_dir / "elout").write_text("placeholder\n", encoding="utf-8")
            (run_dir / "nodout").write_text("placeholder\n", encoding="utf-8")
            with patch(
                "lsprepost_mcp.lsdyna_runner.parse_city_object_responses",
                return_value={
                    "building": {
                        "fsi_present": True,
                        "peak_fsi_pressure_rise_pa": 1000.0,
                        "fsi_positive_pressure_sample_count": 3,
                        "fsi_positive_pressure_duration_s": 0.001,
                        "fsi_arrival_time_s": 0.002,
                        "peak_structural_pressure_pa": 500.0,
                        "peak_principal_stress_pa": 800.0,
                        "structural_arrival_time_s": 0.001,
                        "peak_displacement_m": 0.001,
                        "last_response_time_s": 0.05,
                    }
                },
            ):
                result = _city_wave_transfer_acceptance(project, run_dir)

            self.assertFalse(result["wave_transfer_verified"])
            self.assertIn(
                "city_object_arrival_order",
                result["blocking_check_ids"],
            )

    def test_city_acceptance_includes_validation_crater_result_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "city"
            run_dir = Path(tmp) / "run"
            project.mkdir()
            run_dir.mkdir()
            ground_metadata = {"mode": "validation_crater"}
            (project / "model.json").write_text(
                json.dumps(
                    {
                        "metadata": {
                            "fsi": {},
                            "ground_response": ground_metadata,
                        }
                    }
                ),
                encoding="utf-8",
            )
            crater_result = {
                "verified": False,
                "blocking_check_ids": ["city_ground_element_deletion"],
                "checks": [
                    {
                        "id": "city_ground_element_deletion",
                        "ok": False,
                        "actual": 0,
                        "limit": {"minimum_deleted_element_count": 1},
                    }
                ],
            }

            with patch(
                "lsprepost_mcp.lsdyna_runner.evaluate_city_ground_crater",
                return_value=crater_result,
            ) as evaluate:
                result = _city_wave_transfer_acceptance(project, run_dir)

        evaluate.assert_called_once_with(run_dir, ground_metadata)
        self.assertEqual(crater_result, result["ground_crater"])
        self.assertIn(
            "city_ground_element_deletion",
            result["blocking_check_ids"],
        )

    def test_phase15_acceptance_dispatches_conforming_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._phase15_project(Path(temp_dir) / "phase15_demo")
            model = json.loads((project / "model.json").read_text(encoding="utf-8"))
            model["metadata"]["phase15"]["coupling_mode"] = (
                "conforming_shared_nodes"
            )
            (project / "model.json").write_text(
                json.dumps(model),
                encoding="utf-8",
            )
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir()
            expected = {"wave_transfer_verified": False, "checks": []}
            with patch(
                "lsprepost_mcp.lsdyna_runner.evaluate_phase15_wave_transfer",
                return_value=expected,
            ) as evaluator:
                result = _phase15_wave_transfer_acceptance(project, run_dir)

        self.assertEqual(expected, result)
        self.assertEqual(
            "conforming_shared_nodes",
            evaluator.call_args.kwargs["coupling_mode"],
        )

    def test_phase15_acceptance_passes_air_gap_probe_and_output_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._phase15_project(Path(temp_dir) / "phase15_demo")
            model = json.loads((project / "model.json").read_text(encoding="utf-8"))
            phase15 = model["metadata"]["phase15"]
            phase15["coupling_mode"] = "conforming_air_gap"
            phase15["probes"]["ale"] = [
                {"id": "TNT_NEAR", "element_id": 11},
                {"id": "AIR_MID_GAP", "element_id": 12},
                {"id": "AIR_INTERFACE", "element_id": 13},
            ]
            phase15["output"] = {"history_output_dt_s": 2.0e-6}
            (project / "model.json").write_text(
                json.dumps(model),
                encoding="utf-8",
            )
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir()
            expected = {"wave_transfer_verified": False, "checks": []}
            with patch(
                "lsprepost_mcp.lsdyna_runner.evaluate_phase15_wave_transfer",
                return_value=expected,
            ) as evaluator:
                result = _phase15_wave_transfer_acceptance(project, run_dir)

        self.assertEqual(expected, result)
        self.assertEqual(
            phase15["probes"]["ale"],
            evaluator.call_args.kwargs["ale_probe_metadata"],
        )
        self.assertEqual(
            2.0e-6,
            evaluator.call_args.kwargs["history_output_dt_s"],
        )

    def test_phase15_acceptance_prefers_the_run_model_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._phase15_project(Path(temp_dir) / "phase15_demo")
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir()
            snapshot = json.loads(
                (project / "model.json").read_text(encoding="utf-8")
            )
            snapshot["metadata"]["phase15"]["coupling_mode"] = (
                "conforming_air_gap"
            )
            (run_dir / "model.json").write_text(
                json.dumps(snapshot),
                encoding="utf-8",
            )
            expected = {
                "applicable": True,
                "wave_transfer_verified": True,
            }

            with patch(
                "lsprepost_mcp.lsdyna_runner.evaluate_phase15_wave_transfer",
                return_value=expected,
            ) as evaluator:
                result = _phase15_wave_transfer_acceptance(project, run_dir)

        self.assertEqual(expected, result)
        self.assertEqual(
            "conforming_air_gap",
            evaluator.call_args.kwargs["coupling_mode"],
        )

    def test_phase15_run_fails_closed_when_wave_transfer_is_not_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._phase15_project(Path(temp_dir) / "phase15_demo")
            solver = Path(temp_dir) / "lsdyna.exe"
            solver.write_bytes(b"fake solver")

            def fake_popen(_command, cwd, **_kwargs):
                run_dir = Path(cwd)
                (run_dir / "d3hsp").write_text(
                    "*** termination time reached ***\n",
                    encoding="utf-8",
                )
                (run_dir / "glstat").write_text(VALID_D3HSP, encoding="utf-8")
                (run_dir / "d3plot").write_bytes(b"d3plot-data")
                (run_dir / "dbfsi").write_text("fsi output\n", encoding="utf-8")
                (run_dir / "elout").write_text("elout output\n", encoding="utf-8")
                return FakeProcess()

            acceptance = {
                "wave_transfer_verified": False,
                "checks": [
                    {"id": "fsi_slave_segments_nonzero", "ok": False, "actual": 0}
                ],
            }
            with (
                patch(
                    "lsprepost_mcp.lsdyna_runner.subprocess.Popen",
                    side_effect=fake_popen,
                ),
                patch(
                    "lsprepost_mcp.lsdyna_runner.evaluate_phase15_wave_transfer",
                    return_value=acceptance,
                ),
            ):
                result = execute_lsdyna_run(
                    project,
                    solver,
                    ncpu=4,
                    memory="20m",
                    timeout_s=30,
                )

            self.assertFalse(result["ok"])
            self.assertEqual(acceptance, result["wave_transfer_acceptance"])
            saved = json.loads(
                (Path(result["run_dir"]) / "wave_transfer_acceptance.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(acceptance, saved)

    def test_phase15_run_accepts_verified_concrete_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._phase15_project(Path(temp_dir) / "phase15_demo")
            solver = Path(temp_dir) / "lsdyna.exe"
            solver.write_bytes(b"fake solver")

            def fake_popen(_command, cwd, **_kwargs):
                run_dir = Path(cwd)
                (run_dir / "d3hsp").write_text(
                    "*** termination time reached ***\n",
                    encoding="utf-8",
                )
                (run_dir / "glstat").write_text(VALID_D3HSP, encoding="utf-8")
                (run_dir / "d3plot").write_bytes(b"d3plot-data")
                (run_dir / "dbfsi").write_text("fsi output\n", encoding="utf-8")
                (run_dir / "elout").write_text("elout output\n", encoding="utf-8")
                return FakeProcess()

            acceptance = {
                "wave_transfer_verified": True,
                "checks": [
                    {"id": "fsi_slave_segments_nonzero", "ok": True, "actual": 193}
                ],
            }
            with (
                patch(
                    "lsprepost_mcp.lsdyna_runner.subprocess.Popen",
                    side_effect=fake_popen,
                ),
                patch(
                    "lsprepost_mcp.lsdyna_runner.evaluate_phase15_wave_transfer",
                    return_value=acceptance,
                ),
            ):
                result = execute_lsdyna_run(
                    project,
                    solver,
                    ncpu=4,
                    memory="20m",
                    timeout_s=30,
                )

            self.assertTrue(result["ok"])
            self.assertTrue(result["wave_transfer_acceptance"]["wave_transfer_verified"])

    def test_phase14_run_fails_closed_when_wave_transfer_is_not_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._phase14_project(Path(temp_dir) / "phase14_demo")
            solver = Path(temp_dir) / "lsdyna.exe"
            solver.write_bytes(b"fake solver")

            def fake_popen(_command, cwd, **_kwargs):
                run_dir = Path(cwd)
                (run_dir / "d3hsp").write_text(
                    "*** termination time reached ***\n",
                    encoding="utf-8",
                )
                (run_dir / "glstat").write_text(VALID_D3HSP, encoding="utf-8")
                (run_dir / "d3plot").write_bytes(b"d3plot-data")
                (run_dir / "dbfsi").write_text("fsi output\n", encoding="utf-8")
                (run_dir / "nodout").write_text("nodout output\n", encoding="utf-8")
                return FakeProcess()

            acceptance = {
                "applicable": True,
                "wave_transfer_verified": False,
                "checks": [{"id": "fsi_impulse_positive_finite", "ok": False}],
            }
            with (
                patch(
                    "lsprepost_mcp.lsdyna_runner.subprocess.Popen",
                    side_effect=fake_popen,
                ),
                patch(
                    "lsprepost_mcp.lsdyna_runner.evaluate_phase14_wave_transfer",
                    return_value=acceptance,
                ),
            ):
                result = execute_lsdyna_run(
                    project,
                    solver,
                    ncpu=4,
                    memory="20m",
                    timeout_s=30,
                )

            self.assertFalse(result["ok"])
            self.assertEqual(acceptance, result["wave_transfer_acceptance"])
            saved = json.loads(
                (Path(result["run_dir"]) / "wave_transfer_acceptance.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(acceptance, saved)

    def test_phase14_run_accepts_verified_wave_transfer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._phase14_project(Path(temp_dir) / "phase14_demo")
            solver = Path(temp_dir) / "lsdyna.exe"
            solver.write_bytes(b"fake solver")

            def fake_popen(_command, cwd, **_kwargs):
                run_dir = Path(cwd)
                (run_dir / "d3hsp").write_text(
                    "*** termination time reached ***\n",
                    encoding="utf-8",
                )
                (run_dir / "glstat").write_text(VALID_D3HSP, encoding="utf-8")
                (run_dir / "d3plot").write_bytes(b"d3plot-data")
                (run_dir / "dbfsi").write_text("fsi output\n", encoding="utf-8")
                (run_dir / "nodout").write_text("nodout output\n", encoding="utf-8")
                return FakeProcess()

            acceptance = {
                "applicable": True,
                "wave_transfer_verified": True,
                "checks": [{"id": "fsi_impulse_positive_finite", "ok": True}],
            }
            with (
                patch(
                    "lsprepost_mcp.lsdyna_runner.subprocess.Popen",
                    side_effect=fake_popen,
                ),
                patch(
                    "lsprepost_mcp.lsdyna_runner.evaluate_phase14_wave_transfer",
                    return_value=acceptance,
                ),
            ):
                result = execute_lsdyna_run(
                    project,
                    solver,
                    ncpu=4,
                    memory="20m",
                    timeout_s=30,
                )

            self.assertTrue(result["ok"])
            self.assertEqual(acceptance, result["wave_transfer_acceptance"])
            run_dir = Path(result["run_dir"])
            model_snapshot = run_dir / "model.json"
            self.assertTrue(model_snapshot.is_file())
            self.assertEqual(
                hashlib.sha256(model_snapshot.read_bytes()).hexdigest(),
                result["model_json_sha256"],
            )

    def test_phase14_run_fails_closed_when_evidence_sealing_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._phase14_project(Path(temp_dir) / "phase14_demo")
            solver = Path(temp_dir) / "lsdyna.exe"
            solver.write_bytes(b"fake solver")

            def fake_popen(_command, cwd, **_kwargs):
                run_dir = Path(cwd)
                (run_dir / "d3hsp").write_text(VALID_D3HSP, encoding="utf-8")
                (run_dir / "d3plot").write_bytes(b"d3plot-data")
                (run_dir / "dbfsi").write_text("fsi output\n", encoding="utf-8")
                (run_dir / "nodout").write_text("nodout output\n", encoding="utf-8")
                return FakeProcess()

            with (
                patch(
                    "lsprepost_mcp.lsdyna_runner.subprocess.Popen",
                    side_effect=fake_popen,
                ),
                patch(
                    "lsprepost_mcp.lsdyna_runner.seal_phase14_run_evidence",
                    side_effect=OSError("disk unavailable"),
                ),
            ):
                result = execute_lsdyna_run(
                    project,
                    solver,
                    ncpu=4,
                    memory="20m",
                    timeout_s=30,
                )

            self.assertFalse(result["ok"])
            self.assertEqual(
                "evidence_manifest_write_failed",
                result["evidence_integrity"]["reason"],
            )

    def test_phase14_invalid_evidence_cannot_bypass_gate_as_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._phase14_project(Path(temp_dir) / "phase14_demo")
            solver = Path(temp_dir) / "lsdyna.exe"
            solver.write_bytes(b"fake solver")

            def fake_popen(_command, cwd, **_kwargs):
                run_dir = Path(cwd)
                (run_dir / "d3hsp").write_text(
                    "*** termination time reached ***\n",
                    encoding="utf-8",
                )
                (run_dir / "glstat").write_text(VALID_D3HSP, encoding="utf-8")
                (run_dir / "d3plot").write_bytes(b"d3plot-data")
                (run_dir / "dbfsi").write_text("fsi output\n", encoding="utf-8")
                return FakeProcess()

            acceptance = {
                "applicable": False,
                "status": "invalid_evidence",
                "wave_transfer_verified": False,
                "checks": [{"id": "model_json_readable", "ok": False}],
            }
            with (
                patch(
                    "lsprepost_mcp.lsdyna_runner.subprocess.Popen",
                    side_effect=fake_popen,
                ),
                patch(
                    "lsprepost_mcp.lsdyna_runner.evaluate_phase14_wave_transfer",
                    return_value=acceptance,
                ),
            ):
                result = execute_lsdyna_run(
                    project,
                    solver,
                    ncpu=4,
                    memory="20m",
                    timeout_s=30,
                )

            self.assertFalse(result["ok"])

    def test_phase14_latest_run_refresh_reapplies_wave_transfer_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._phase14_project(Path(temp_dir) / "phase14_demo")
            runs_dir = project / "solver_runs"
            run_id = "run_20260716T000000000000Z_phase14"
            run_dir = runs_dir / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")
            (run_dir / "d3hsp").write_text(
                "*** termination time reached ***\n",
                encoding="utf-8",
            )
            (run_dir / "glstat").write_text(VALID_D3HSP, encoding="utf-8")
            (run_dir / "d3plot").write_bytes(b"d3plot-data")
            (run_dir / "dbfsi").write_text("fsi output\n", encoding="utf-8")
            stale_record = {
                "ok": True,
                "status": "completed",
                "returncode": 0,
                "run_id": run_id,
                "result_mode": "blast",
                "result_variant": "ale_blast",
            }
            (run_dir / "run.json").write_text(
                json.dumps(stale_record),
                encoding="utf-8",
            )
            (runs_dir / "latest.json").write_text(
                json.dumps(stale_record),
                encoding="utf-8",
            )
            acceptance = {
                "applicable": True,
                "wave_transfer_verified": False,
                "checks": [{"id": "plate_displacement_positive_finite", "ok": False}],
            }

            with patch(
                "lsprepost_mcp.lsdyna_runner.evaluate_phase14_wave_transfer",
                return_value=acceptance,
            ):
                refreshed = latest_lsdyna_run(project)

            self.assertFalse(refreshed["ok"])
            self.assertEqual(
                "invalid_evidence",
                refreshed["wave_transfer_acceptance"]["status"],
            )
            saved = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertFalse(saved["ok"])
            self.assertEqual(
                "invalid_evidence",
                saved["wave_transfer_acceptance"]["status"],
            )

    def test_phase14_latest_run_rejects_tampered_sealed_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._phase14_project(Path(temp_dir) / "phase14_demo")
            runs_dir = project / "solver_runs"
            run_id = "run_20260716T000000000000Z_sealed"
            run_dir = runs_dir / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "model.k").write_bytes((project / "model.k").read_bytes())
            (run_dir / "model.json").write_bytes((project / "model.json").read_bytes())
            (run_dir / "d3hsp").write_text(VALID_D3HSP, encoding="utf-8")
            (run_dir / "d3plot").write_bytes(b"d3plot-data")
            (run_dir / "dbfsi").write_text("fsi output\n", encoding="utf-8")
            (run_dir / "nodout").write_text("nodout output\n", encoding="utf-8")
            evidence = seal_phase14_run_evidence(run_dir)
            record = {
                "ok": True,
                "status": "completed",
                "returncode": 0,
                "run_id": run_id,
                "result_mode": "blast",
                "result_variant": "ale_blast",
                "input_sha256": hashlib.sha256(
                    (run_dir / "model.k").read_bytes()
                ).hexdigest(),
                "model_json_sha256": hashlib.sha256(
                    (run_dir / "model.json").read_bytes()
                ).hexdigest(),
                "evidence_manifest": evidence,
                "evidence_manifest_sha256": evidence["sha256"],
                "solver_evaluation": {"ok": True},
            }
            (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
            (runs_dir / "latest.json").write_text(json.dumps(record), encoding="utf-8")
            (run_dir / "model.k").write_text(
                "*KEYWORD\n$ modified after solve\n*END\n",
                encoding="utf-8",
            )

            refreshed = latest_lsdyna_run(project)

            self.assertFalse(refreshed["ok"])
            self.assertEqual(
                "evidence_files_changed",
                refreshed["evidence_integrity"]["reason"],
            )

    def test_phase14_ale_runner_does_not_enable_incompatible_fsifor_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "ale_blast_demo"
            project.mkdir()
            (project / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")
            (project / "model.json").write_text(
                json.dumps(
                    {
                        "spec": {
                            "model_type": "ale_blast_scene",
                            "geometry": {},
                            "loads": [],
                        }
                    }
                ),
                encoding="utf-8",
            )
            solver = Path(temp_dir) / "lsdyna.exe"
            solver.write_bytes(b"fake solver")
            captured: list[str] = []

            def fake_popen(command, **_kwargs):
                captured.extend(command)
                return FakeProcess(returncode=1)

            with patch("lsprepost_mcp.lsdyna_runner.subprocess.Popen", side_effect=fake_popen):
                execute_lsdyna_run(project, solver, ncpu=4, memory="20m", timeout_s=30)

            self.assertEqual(captured[1:], ["i=model.k", "ncpu=4", "memory=20m"])
            self.assertNotIn("h=fsifor", captured)

    def test_parse_run_options_requires_exact_project_confirmation(self) -> None:
        with self.assertRaisesRegex(ValueError, "confirmation_project_name"):
            parse_run_options(
                {
                    "project_name": "blast_demo",
                    "confirmation_project_name": "other_project",
                }
            )

    def test_parse_run_options_rejects_unsafe_resource_values(self) -> None:
        invalid = [
            {"ncpu": 0},
            {"ncpu": True},
            {"ncpu": 65},
            {"memory": "20m & calc"},
            {"memory": "0m"},
            {"timeout_s": 0},
            {"timeout_s": 7201},
        ]
        for update in invalid:
            with self.subTest(update=update):
                payload = {
                    "project_name": "blast_demo",
                    "confirmation_project_name": "blast_demo",
                    **update,
                }
                with self.assertRaises(ValueError):
                    parse_run_options(payload)

    def test_successful_blast_run_uses_snapshot_and_records_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._blast_project(Path(temp_dir) / "blast_demo")
            solver = Path(temp_dir) / "lsdyna.exe"
            solver.write_bytes(b"fake solver")

            def fake_popen(command, cwd, **_kwargs):
                self.assertEqual(command[1], "i=model.k")
                self.assertEqual(command[2], "ncpu=4")
                self.assertEqual(command[3], "memory=20m")
                run_dir = Path(cwd)
                (run_dir / "d3hsp").write_text("*** termination time reached ***\n", encoding="utf-8")
                (run_dir / "glstat").write_text(VALID_D3HSP, encoding="utf-8")
                (run_dir / "d3plot").write_bytes(b"d3plot-data")
                (run_dir / "blstfor").write_bytes(b"blast-force-data")
                (run_dir / "nodout").write_text(VALID_NODOUT, encoding="utf-8")
                return FakeProcess()

            with patch("lsprepost_mcp.lsdyna_runner.subprocess.Popen", side_effect=fake_popen):
                result = execute_lsdyna_run(project, solver, ncpu=4, memory="20m", timeout_s=30)

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["result_mode"], "blast")
            self.assertTrue(result["outputs"]["d3plot"]["ok"])
            self.assertTrue(result["outputs"]["blstfor"]["ok"])
            self.assertTrue(result["solver_evaluation"]["ok"])
            self.assertEqual(0.005, result["solver_evaluation"]["metrics"]["peak_displacement_m"])
            self.assertEqual(10, result["solver_evaluation"]["metrics"]["peak_displacement_node_id"])
            self.assertEqual("available", result["solver_evaluation"]["nodout"]["status"])
            self.assertEqual(result["postprocessing"]["status"], "requires_lsprepost_verification")
            run_dir = Path(result["run_dir"])
            self.assertEqual((run_dir / "model.k").read_text(encoding="utf-8"), "*KEYWORD\n*END\n")
            self.assertTrue((run_dir / "run.json").is_file())
            self.assertEqual(latest_lsdyna_run(project)["run_id"], result["run_id"])

    def test_timeout_is_persisted_and_process_tree_is_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._blast_project(Path(temp_dir) / "blast_demo")
            solver = Path(temp_dir) / "lsdyna.exe"
            solver.write_bytes(b"fake solver")
            with (
                patch("lsprepost_mcp.lsdyna_runner.subprocess.Popen", return_value=FakeProcess(timeout=True)),
                patch("lsprepost_mcp.lsdyna_runner.terminate_process_tree", return_value=True) as terminate,
            ):
                result = execute_lsdyna_run(project, solver, ncpu=2, memory="10m", timeout_s=1)

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "timed_out")
            self.assertTrue(result["termination_confirmed"])
            terminate.assert_called_once_with(4321)
            saved = json.loads((Path(result["run_dir"]) / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "timed_out")

    def test_latest_run_refreshes_terminal_output_and_energy_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._blast_project(Path(temp_dir) / "blast_demo")
            runs_dir = project / "solver_runs"
            run_id = "run_20260716T000000000000Z_test1234"
            run_dir = runs_dir / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")
            (run_dir / "d3hsp").write_text("*** termination time reached ***\n", encoding="utf-8")
            (run_dir / "glstat").write_text(VALID_D3HSP, encoding="utf-8")
            (run_dir / "d3plot").write_bytes(b"d3plot-data")
            (run_dir / "blstfor").write_bytes(b"blast-force-data")
            (run_dir / "nodout").write_text(VALID_NODOUT, encoding="utf-8")
            stale_record = {
                "ok": False,
                "status": "completed",
                "returncode": 0,
                "run_id": run_id,
                "result_mode": "blast",
                "solver_evaluation": {"ok": False},
                "postprocessing": {"stress_cloud_recorded": False},
            }
            (run_dir / "run.json").write_text(json.dumps(stale_record), encoding="utf-8")
            runs_dir.mkdir(exist_ok=True)
            (runs_dir / "latest.json").write_text(json.dumps(stale_record), encoding="utf-8")

            refreshed = latest_lsdyna_run(project)

            self.assertTrue(refreshed["ok"])
            self.assertTrue(refreshed["solver_evaluation"]["ok"])
            self.assertTrue(refreshed["outputs"]["d3plot"]["ok"])
            self.assertTrue(refreshed["outputs"]["blstfor"]["ok"])
            self.assertEqual(0.005, refreshed["solver_evaluation"]["metrics"]["peak_displacement_m"])
            self.assertIn("equivalent_mass_kg", refreshed["blast_configuration"])
            saved = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertTrue(saved["solver_evaluation"]["ok"])
            self.assertEqual(
                refreshed["blast_configuration"]["equivalent_mass_kg"],
                saved["blast_configuration"]["equivalent_mass_kg"],
            )

    def test_latest_city_run_keeps_live_solver_record_running(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "city"
            project.mkdir()
            (project / "model.json").write_text(
                json.dumps({"spec": {"model_type": "city_street_blast_scene"}}),
                encoding="utf-8",
            )
            runs_dir = project / "solver_runs"
            run_id = "run_20260730T000000000000Z_citylive"
            run_dir = runs_dir / run_id
            run_dir.mkdir(parents=True)
            record = {
                "ok": False,
                "status": "running",
                "run_id": run_id,
                "pid": 4321,
                "result_mode": "blast",
                "result_variant": "city_street_blast",
                "solver": {"path": str(Path(temp_dir) / "lsdyna.exe")},
            }
            (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
            (runs_dir / "latest.json").write_text(json.dumps(record), encoding="utf-8")

            with patch(
                "lsprepost_mcp.lsdyna_runner._recorded_solver_process_is_running",
                return_value=True,
            ):
                refreshed = latest_lsdyna_run(project)

            self.assertEqual("running", refreshed["status"])
            self.assertNotIn("recovery", refreshed)

    def test_latest_city_run_recovers_orphaned_normal_termination(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "city"
            project.mkdir()
            (project / "model.json").write_text(
                json.dumps({"spec": {"model_type": "city_street_blast_scene"}}),
                encoding="utf-8",
            )
            runs_dir = project / "solver_runs"
            run_id = "run_20260730T000000000000Z_cityorphan"
            run_dir = runs_dir / run_id
            run_dir.mkdir(parents=True)
            (run_dir / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")
            (run_dir / "model.json").write_text(
                json.dumps({"spec": {"model_type": "city_street_blast_scene"}}),
                encoding="utf-8",
            )
            for name in (
                "d3plot",
                "d3hsp",
                "matsum",
                "dbfsi",
                "elout",
                "nodout",
            ):
                (run_dir / name).write_text("result\n", encoding="utf-8")
            record = {
                "ok": False,
                "status": "running",
                "run_id": run_id,
                "pid": 4321,
                "result_mode": "blast",
                "result_variant": "city_street_blast",
                "solver": {"path": str(Path(temp_dir) / "lsdyna.exe")},
                "started_at_utc": "2026-07-30T00:00:00+00:00",
            }
            (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
            (runs_dir / "latest.json").write_text(json.dumps(record), encoding="utf-8")
            solver_evaluation = {
                "ok": True,
                "parsed": {"terminated_normally": True},
            }
            city_acceptance = {
                "applicable": True,
                "wave_transfer_verified": True,
                "blocking_check_ids": [],
            }

            with (
                patch(
                    "lsprepost_mcp.lsdyna_runner._recorded_solver_process_is_running",
                    return_value=False,
                ),
                patch(
                    "lsprepost_mcp.lsdyna_runner._evaluate_d3hsp",
                    return_value=solver_evaluation,
                ),
                patch(
                    "lsprepost_mcp.lsdyna_runner._city_wave_transfer_acceptance",
                    return_value=city_acceptance,
                ),
            ):
                refreshed = latest_lsdyna_run(project)

            self.assertTrue(refreshed["ok"])
            self.assertEqual("completed", refreshed["status"])
            self.assertEqual(0, refreshed["returncode"])
            self.assertEqual(
                "d3hsp_normal_termination",
                refreshed["recovery"]["returncode_source"],
            )
            self.assertTrue(refreshed["wave_transfer_acceptance"]["wave_transfer_verified"])
            self.assertTrue(refreshed["outputs"]["d3plot"]["ok"])
            self.assertTrue(refreshed["outputs"]["d3hsp"]["ok"])
            self.assertTrue(refreshed["outputs"]["matsum"]["ok"])
            self.assertTrue(refreshed["outputs"]["dbfsi"]["ok"])
            self.assertTrue(refreshed["outputs"]["elout"]["ok"])
            self.assertTrue(refreshed["outputs"]["nodout"]["ok"])
            self.assertTrue(refreshed["evidence_integrity"]["ok"])
            self.assertEqual(
                ["d3hsp", "d3plot", "dbfsi", "matsum", "elout", "nodout"],
                refreshed["required_outputs"],
            )
            saved = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual("completed", saved["status"])
            self.assertTrue(saved["ok"])

    def test_latest_city_run_does_not_retroactively_seal_completed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "city"
            project.mkdir()
            (project / "model.json").write_text(
                json.dumps({"spec": {"model_type": "city_street_blast_scene"}}),
                encoding="utf-8",
            )
            runs_dir = project / "solver_runs"
            run_id = "run_20260730T000000000000Z_citylegacy"
            run_dir = runs_dir / run_id
            run_dir.mkdir(parents=True)
            for name in ("model.k", "model.json", "d3plot", "d3hsp", "matsum", "dbfsi"):
                (run_dir / name).write_text("result\n", encoding="utf-8")
            record = {
                "ok": True,
                "status": "completed",
                "returncode": 0,
                "run_id": run_id,
                "result_mode": "blast",
                "result_variant": "city_street_blast",
            }
            (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
            (runs_dir / "latest.json").write_text(json.dumps(record), encoding="utf-8")

            with (
                patch(
                    "lsprepost_mcp.lsdyna_runner._evaluate_d3hsp",
                    return_value={"ok": True, "parsed": {"terminated_normally": True}},
                ),
                patch(
                    "lsprepost_mcp.lsdyna_runner._city_wave_transfer_acceptance",
                    return_value={
                        "applicable": True,
                        "wave_transfer_verified": True,
                        "blocking_check_ids": [],
                    },
                ),
            ):
                refreshed = latest_lsdyna_run(project)

            self.assertFalse(refreshed["ok"])
            self.assertEqual(
                "evidence_manifest_reference_missing",
                refreshed["evidence_integrity"]["reason"],
            )
            self.assertFalse((run_dir / "evidence_manifest.json").exists())

    def test_latest_city_run_rejects_latest_and_run_record_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "city"
            project.mkdir()
            runs_dir = project / "solver_runs"
            run_id = "run_20260730T000000000000Z_cityidentity"
            run_dir = runs_dir / run_id
            run_dir.mkdir(parents=True)
            (project / "model.json").write_text(
                json.dumps({"spec": {"model_type": "city_street_blast_scene"}}),
                encoding="utf-8",
            )
            for name in (
                "model.k",
                "model.json",
                "d3plot",
                "d3hsp",
                "matsum",
                "dbfsi",
                "elout",
                "nodout",
            ):
                (run_dir / name).write_text("result\n", encoding="utf-8")
            evidence = seal_phase14_run_evidence(
                run_dir,
                required_output_prefixes=CITY_REQUIRED_EVIDENCE,
            )
            record = {
                "ok": True,
                "status": "completed",
                "returncode": 0,
                "run_id": run_id,
                "result_mode": "blast",
                "result_variant": "city_street_blast",
                "input_sha256": hashlib.sha256(
                    (run_dir / "model.k").read_bytes()
                ).hexdigest(),
                "model_json_sha256": hashlib.sha256(
                    (run_dir / "model.json").read_bytes()
                ).hexdigest(),
                "evidence_manifest": evidence,
                "evidence_manifest_sha256": evidence["sha256"],
                "solver_evaluation": {"ok": True},
            }
            (run_dir / "run.json").write_text(
                json.dumps(record),
                encoding="utf-8",
            )
            tampered = dict(record)
            tampered["ok"] = False
            (runs_dir / "latest.json").write_text(
                json.dumps(tampered),
                encoding="utf-8",
            )

            with (
                patch(
                    "lsprepost_mcp.lsdyna_runner._evaluate_d3hsp",
                    return_value={"ok": True, "parsed": {"terminated_normally": True}},
                ),
                patch(
                    "lsprepost_mcp.lsdyna_runner._city_wave_transfer_acceptance",
                    return_value={
                        "applicable": True,
                        "wave_transfer_verified": True,
                        "blocking_check_ids": [],
                    },
                ),
            ):
                refreshed = latest_lsdyna_run(project)

            self.assertFalse(refreshed["ok"])
            self.assertEqual("invalid_evidence", refreshed["status"])
            self.assertEqual(
                ["ok"],
                refreshed["evidence_integrity"]["run_record_identity"][
                    "mismatched_fields"
                ],
            )

    def test_postprocessing_record_requires_latest_valid_png(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._blast_project(Path(temp_dir) / "blast_demo")
            runs_dir = project / "solver_runs"
            run_id = "run_20260716T000000000000Z_test1234"
            run_dir = runs_dir / run_id
            run_dir.mkdir(parents=True)
            record = {
                "run_id": run_id,
                "status": "completed",
                "returncode": 0,
                "postprocessing": {
                    "blast_pressure": {
                        "peak_pressure_pa": 2.5e6,
                        "source_sha256": "b" * 64,
                    }
                },
            }
            (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
            (runs_dir / "latest.json").write_text(json.dumps(record), encoding="utf-8")
            artifacts = project / "artifacts"
            artifacts.mkdir()
            image = artifacts / "stress.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\ncontour")

            result = record_lsprepost_postprocessing(
                project,
                run_id,
                image,
                state_number=22,
                component_label="Effective Stress (v-m)",
                lspp_returncode=0,
                cfile_sha256="a" * 64,
                maximum_value_pa=1.5e8,
            )

            self.assertTrue(result["stress_cloud_recorded"])
            self.assertEqual("verified", result["status"])
            saved = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(
                str(Path("artifacts") / "stress.png"),
                saved["postprocessing"]["image_relative_path"],
            )
            self.assertEqual(2.5e6, saved["postprocessing"]["blast_pressure"]["peak_pressure_pa"])
            self.assertNotIn("note", saved["postprocessing"])

    def test_postprocessing_record_accepts_controlled_pressure_contour(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._phase15_project(Path(temp_dir) / "phase15_demo")
            runs_dir = project / "solver_runs"
            run_id = "run_20260723T061038743070Z_fcf6fa0a"
            run_dir = runs_dir / run_id
            run_dir.mkdir(parents=True)
            record = {
                "run_id": run_id,
                "status": "completed",
                "returncode": 0,
                "postprocessing": {},
            }
            (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
            (runs_dir / "latest.json").write_text(json.dumps(record), encoding="utf-8")
            artifacts = project / "artifacts"
            artifacts.mkdir()
            image = artifacts / "concrete_pressure.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\npressure-contour")

            result = record_lsprepost_postprocessing(
                project,
                run_id,
                image,
                state_number=58,
                component_label="Pressure",
                lspp_returncode=0,
                cfile_sha256="c" * 64,
                maximum_value_pa=4.245e8,
                state_time_s=1.3194e-4,
            )

            self.assertTrue(result["pressure_cloud_recorded"])
            self.assertNotIn("stress_cloud_recorded", result)
            self.assertEqual("Pressure", result["component"])

    def test_blast_pressure_history_is_extracted_and_persisted_with_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._blast_project(Path(temp_dir) / "blast_demo")
            runs_dir = project / "solver_runs"
            run_id = "run_20260716T000000000000Z_test1234"
            run_dir = runs_dir / run_id
            run_dir.mkdir(parents=True)
            record = {
                "run_id": run_id,
                "project_name": project.name,
                "status": "completed",
                "returncode": 0,
                "postprocessing": {"status": "verified", "maximum_value_pa": 1.5e8},
            }
            (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
            (runs_dir / "latest.json").write_text(json.dumps(record), encoding="utf-8")
            artifacts = project / "artifacts"
            artifacts.mkdir()
            history = artifacts / "blast_pressure_history.csv"
            history.write_text(
                "time_s,pressure_pa\n0.0,0\n0.001,100\n0.002,200\n0.003,100\n0.004,0\n",
                encoding="utf-8",
            )

            result = record_blast_pressure_history(project, run_id, history)

            self.assertEqual(200.0, result["peak_pressure_pa"])
            self.assertAlmostEqual(0.002, result["positive_duration_s"])
            self.assertAlmostEqual(0.3, result["positive_impulse_pa_s"])
            self.assertEqual("LS-PrePost exported pressure history", result["extraction_method"])
            saved = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(1.5e8, saved["postprocessing"]["maximum_value_pa"])
            self.assertEqual(64, len(saved["postprocessing"]["blast_pressure"]["source_sha256"]))

    def test_blast_pressure_history_rejects_non_monotonic_or_external_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._blast_project(Path(temp_dir) / "blast_demo")
            runs_dir = project / "solver_runs"
            run_id = "run_20260716T000000000000Z_test1234"
            run_dir = runs_dir / run_id
            run_dir.mkdir(parents=True)
            record = {"run_id": run_id, "status": "completed", "returncode": 0}
            (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
            (runs_dir / "latest.json").write_text(json.dumps(record), encoding="utf-8")
            external = Path(temp_dir) / "history.csv"
            external.write_text("0,1\n1,2\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "project artifacts"):
                record_blast_pressure_history(project, run_id, external)

            artifacts = project / "artifacts"
            artifacts.mkdir()
            history = artifacts / "history.csv"
            history.write_text("0,1\n0,2\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "strictly increasing"):
                record_blast_pressure_history(project, run_id, history)

    def _blast_project(self, path: Path) -> Path:
        path.mkdir(parents=True)
        (path / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")
        (path / "model.json").write_text(
            json.dumps({"spec": {"loads": [{"type": "blast_enhanced"}]}}),
            encoding="utf-8",
        )
        return path

    def _phase14_project(self, path: Path) -> Path:
        path.mkdir(parents=True)
        (path / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")
        (path / "model.json").write_text(
            json.dumps(
                {
                    "spec": {
                        "model_type": "ale_blast_scene",
                        "geometry": {},
                        "mesh": {"size_m": 0.0125},
                        "loads": [],
                    },
                    "metadata": {
                        "coupling_count": 1,
                        "lagrangian_shell_element_count": 16,
                        "components": [
                            {"id": "target_plate", "response_node_ids": [10]}
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )
        return path

    def _phase15_project(self, path: Path) -> Path:
        path.mkdir(parents=True)
        (path / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")
        (path / "model.json").write_text(
            json.dumps(
                {
                    "spec": {
                        "model_type": "phase15_axisymmetric_blast",
                        "loads": [],
                    },
                    "metadata": {
                        "phase15": {
                            "probes": {
                                "concrete": [
                                    {"id": "FSI_BOTTOM", "element_id": 9236}
                                ]
                            }
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    unittest.main()
