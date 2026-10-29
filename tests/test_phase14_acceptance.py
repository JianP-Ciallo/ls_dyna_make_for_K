from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from lsprepost_mcp.phase14_acceptance import (
    evaluate_phase14_mesh_convergence,
    evaluate_phase14_wave_transfer,
)
from lsprepost_mcp.run_evidence import seal_phase14_run_evidence


VALID_D3HSP = """
 FSI Interface ID ...........................         1
 number of slave materials ..................         1
 number of slave segments for coupling ......         0
 *** termination time reached ***
"""


def phase14_deck(*, response_node_id: int = 1) -> str:
    return f"""*KEYWORD
*ELEMENT_SHELL
1,3,1,2,3,4
*CONSTRAINED_LAGRANGE_IN_SOLID
3,1,1,0,4,4,2,0
*SET_NODE_LIST_TITLE
Fixed target plate perimeter
200
4
*BOUNDARY_SPC_SET
200,0,1,1,1,1,1,1
*SET_NODE_LIST_TITLE
Free target plate response nodes
201
{response_node_id}
*END
"""


def dbfsi_text(
    *,
    peak_pressure_pa: float = 200.0,
    peak_force_n: float = 10.0,
) -> str:
    return f"""
 time = 0.0000000E+00
 1 0.0 0.0 0.0 0.0 0.0
 time = 1.0000000E-03
 1 {peak_pressure_pa} {peak_force_n} 0.0 0.0 0.0
 time = 2.0000000E-03
 1 100.0 {peak_force_n * 0.5} 0.0 0.0 0.0
"""


def nodout_text(
    *,
    peak_time_s: float = 2.0e-3,
    peak_displacement_m: float = 5.0e-3,
    node_id: int = 1,
) -> str:
    return f"""
 n o d a l   p r i n t   o u t   f o r   t i m e  s t e p       1 ( at time 0.0000000E+00 )
 nodal point  x-disp     y-disp      z-disp      x-vel
       {node_id}  0.00000E+00 0.00000E+00 0.00000E+00 0.0
 n o d a l   p r i n t   o u t   f o r   t i m e  s t e p       2 ( at time {peak_time_s:.7E} )
 nodal point  x-disp     y-disp      z-disp      x-vel
       {node_id}  {peak_displacement_m:.7E} 0.00000E+00 0.00000E+00 0.0
"""


class Phase14WaveTransferTests(unittest.TestCase):
    def _project(
        self,
        root: Path,
        *,
        scene_variant: str | None = None,
        mesh_size_m: float = 0.0125,
    ) -> Path:
        project = root / "mmale_plate"
        project.mkdir(parents=True)
        geometry = {}
        if scene_variant is not None:
            geometry["scene_variant"] = scene_variant
        model = {
            "spec": {
                "project_name": project.name,
                "model_type": "ale_blast_scene",
                "geometry": geometry,
                "mesh": {"size_m": mesh_size_m},
            },
            "metadata": {
                "coupling_count": 1,
                "lagrangian_shell_element_count": 16,
                "ale_quantitative_outputs": {
                    "pressure_probe_set_id": 300,
                },
                "components": [
                    {
                        "id": "target_plate",
                        "part_id": 3,
                        "response_node_ids": [1],
                    }
                ],
            },
        }
        (project / "model.json").write_text(
            json.dumps(model),
            encoding="utf-8",
        )
        (project / "model.k").write_text(phase14_deck(), encoding="utf-8")
        return project

    def _run(
        self,
        project: Path,
        *,
        d3hsp: str = VALID_D3HSP,
        dbfsi: str | None = None,
        nodout: str | None = None,
    ) -> Path:
        run_dir = project / "solver_runs" / "run_test"
        run_dir.mkdir(parents=True)
        (run_dir / "model.k").write_text(
            (project / "model.k").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (run_dir / "model.json").write_bytes((project / "model.json").read_bytes())
        (run_dir / "d3hsp").write_text(d3hsp, encoding="utf-8")
        (run_dir / "d3plot").write_bytes(b"d3plot-data")
        if dbfsi is not None:
            (run_dir / "dbfsi").write_text(dbfsi, encoding="utf-8")
        if nodout is not None:
            (run_dir / "nodout").write_text(nodout, encoding="utf-8")
        evidence = seal_phase14_run_evidence(run_dir)
        record = {
            "ok": True,
            "status": "completed",
            "returncode": 0,
            "run_id": "run_test",
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
        (project / "solver_runs" / "latest.json").write_text(
            json.dumps(record),
            encoding="utf-8",
        )
        return run_dir

    def test_rejects_tampered_run_snapshot_after_sealing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._project(Path(temp_dir))
            run_dir = self._run(
                project,
                dbfsi=dbfsi_text(),
                nodout=nodout_text(),
            )
            (run_dir / "model.k").write_text(
                phase14_deck(response_node_id=99),
                encoding="utf-8",
            )

            result = evaluate_phase14_wave_transfer(project, run_dir)

        self.assertFalse(result["wave_transfer_verified"])
        self.assertEqual("invalid_evidence", result["status"])

    def test_rejects_response_node_disconnected_from_target_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._project(Path(temp_dir))
            (project / "model.k").write_text(
                phase14_deck(response_node_id=99),
                encoding="utf-8",
            )
            run_dir = self._run(
                project,
                dbfsi=dbfsi_text(),
                nodout=nodout_text(node_id=99),
            )

            result = evaluate_phase14_wave_transfer(project, run_dir)

        self.assertFalse(result["wave_transfer_verified"])
        checks = {item["id"]: item for item in result["checks"]}
        self.assertFalse(checks["response_nodes_belong_to_target_shell"]["ok"])

    def test_rejects_response_node_with_fixed_translation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._project(Path(temp_dir))
            (project / "model.k").write_text(
                phase14_deck(response_node_id=4),
                encoding="utf-8",
            )
            run_dir = self._run(
                project,
                dbfsi=dbfsi_text(),
                nodout=nodout_text(node_id=4),
            )

            result = evaluate_phase14_wave_transfer(project, run_dir)

        self.assertFalse(result["wave_transfer_verified"])
        checks = {item["id"]: item for item in result["checks"]}
        self.assertFalse(checks["response_nodes_are_translationally_free"]["ok"])

    def test_rejects_multiple_fsi_surfaces_without_target_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._project(Path(temp_dir))
            d3hsp = """
 FSI Interface ID ...........................         1
 number of slave materials ..................         1
 number of slave segments for coupling ......         0
 FSI Interface ID ...........................         2
 number of slave materials ..................         1
 number of slave segments for coupling ......         0
 *** termination time reached ***
"""
            dbfsi = """
 time = 0.0000000E+00
 1 0.0 0.0 0.0 0.0 0.0
 2 0.0 0.0 0.0 0.0 0.0
 time = 1.0000000E-03
 1 200.0 10.0 0.0 0.0 0.0
 2 0.0 0.0 0.0 0.0 0.0
 time = 2.0000000E-03
 1 100.0 5.0 0.0 0.0 0.0
 2 0.0 0.0 0.0 0.0 0.0
"""
            run_dir = self._run(
                project,
                d3hsp=d3hsp,
                dbfsi=dbfsi,
                nodout=nodout_text(),
            )

            result = evaluate_phase14_wave_transfer(project, run_dir)

        self.assertFalse(result["wave_transfer_verified"])
        checks = {item["id"]: item for item in result["checks"]}
        self.assertFalse(checks["single_target_fsi_interface"]["ok"])

    def test_rejects_numerically_insignificant_transfer_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._project(Path(temp_dir))
            dbfsi = """
 time = 0.0000000E+00
 1 0.0 0.0 0.0 0.0 0.0
 time = 1.0000000E-03
 1 1.0E-100 1.0E-100 0.0 0.0 0.0
 time = 2.0000000E-03
 1 5.0E-101 5.0E-101 0.0 0.0 0.0
"""
            run_dir = self._run(
                project,
                dbfsi=dbfsi,
                nodout=nodout_text(peak_displacement_m=1.0e-100),
            )

            result = evaluate_phase14_wave_transfer(project, run_dir)

        self.assertFalse(result["wave_transfer_verified"])
        checks = {item["id"]: item for item in result["checks"]}
        self.assertFalse(checks["fsi_pressure_signal_significant"]["ok"])
        self.assertFalse(checks["plate_displacement_signal_significant"]["ok"])

    def test_accepts_part_based_slave_definition_with_measured_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._project(Path(temp_dir))
            run_dir = self._run(
                project,
                dbfsi=dbfsi_text(),
                nodout=nodout_text(),
            )

            result = evaluate_phase14_wave_transfer(project, run_dir)

        self.assertTrue(result["applicable"])
        self.assertTrue(result["wave_transfer_verified"])
        self.assertEqual("part_or_material", result["fsi"]["slave_definition_mode"])
        self.assertEqual(200.0, result["metrics"]["peak_coupled_surface_pressure_pa"])
        self.assertEqual(0.005, result["metrics"]["peak_displacement_m"])

    def test_missing_dbfsi_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._project(Path(temp_dir))
            run_dir = self._run(project, nodout=nodout_text())

            result = evaluate_phase14_wave_transfer(project, run_dir)

        self.assertFalse(result["wave_transfer_verified"])
        check = next(
            item
            for item in result["checks"]
            if item["id"] == "sealed_run_evidence_valid"
        )
        self.assertFalse(check["ok"])

    def test_missing_run_directory_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._project(Path(temp_dir))

            result = evaluate_phase14_wave_transfer(
                project,
                project / "solver_runs" / "missing",
            )

        self.assertFalse(result["wave_transfer_verified"])
        check = next(
            item
            for item in result["checks"]
            if item["id"] == "sealed_run_evidence_valid"
        )
        self.assertFalse(check["ok"])

    def test_zero_force_and_impulse_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._project(Path(temp_dir))
            run_dir = self._run(
                project,
                dbfsi=dbfsi_text(peak_force_n=0.0),
                nodout=nodout_text(),
            )

            result = evaluate_phase14_wave_transfer(project, run_dir)

        self.assertFalse(result["wave_transfer_verified"])
        checks = {item["id"]: item for item in result["checks"]}
        self.assertFalse(checks["fsi_peak_force_positive_finite"]["ok"])
        self.assertFalse(checks["fsi_impulse_positive_finite"]["ok"])

    def test_displacement_peak_before_pressure_peak_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._project(Path(temp_dir))
            run_dir = self._run(
                project,
                dbfsi=dbfsi_text(),
                nodout=nodout_text(peak_time_s=5.0e-4),
            )

            result = evaluate_phase14_wave_transfer(project, run_dir)

        self.assertFalse(result["wave_transfer_verified"])
        check = next(
            item
            for item in result["checks"]
            if item["id"] == "response_peak_not_before_pressure_peak"
        )
        self.assertFalse(check["ok"])

    def test_displacement_from_non_target_node_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._project(Path(temp_dir))
            run_dir = self._run(
                project,
                dbfsi=dbfsi_text(),
                nodout=nodout_text(node_id=99),
            )

            result = evaluate_phase14_wave_transfer(project, run_dir)

        self.assertFalse(result["wave_transfer_verified"])
        check = next(
            item
            for item in result["checks"]
            if item["id"] == "plate_response_node_matches_target"
        )
        self.assertFalse(check["ok"])

    def test_current_metadata_mutation_does_not_rebind_historical_response_nodes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._project(Path(temp_dir))
            run_dir = self._run(
                project,
                dbfsi=dbfsi_text(),
                nodout=nodout_text(node_id=1),
            )
            model_path = project / "model.json"
            model = json.loads(model_path.read_text(encoding="utf-8"))
            model["metadata"]["components"][0]["response_node_ids"] = [99]
            model_path.write_text(json.dumps(model), encoding="utf-8")

            result = evaluate_phase14_wave_transfer(project, run_dir)

        self.assertTrue(result["wave_transfer_verified"])
        self.assertEqual(
            "run_model_k",
            result["model_evidence"]["response_nodes_source"],
        )

    def test_non_utf8_current_model_json_does_not_replace_sealed_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._project(Path(temp_dir))
            run_dir = self._run(
                project,
                dbfsi=dbfsi_text(),
                nodout=nodout_text(),
            )
            (project / "model.json").write_bytes(b"\xff\xfe")

            result = evaluate_phase14_wave_transfer(project, run_dir)

        self.assertTrue(result["wave_transfer_verified"])
        self.assertEqual(
            "run_model_json",
            result["model_evidence"]["model_json_source"],
        )

    def test_open_concrete_tunnel_is_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self._project(
                Path(temp_dir),
                scene_variant="open_concrete_tunnel",
            )
            run_dir = self._run(
                project,
                dbfsi=dbfsi_text(),
                nodout=nodout_text(),
            )
            tunnel_deck = "*KEYWORD\n*END\n"
            (project / "model.k").write_text(tunnel_deck, encoding="utf-8")
            (run_dir / "model.k").write_text(tunnel_deck, encoding="utf-8")

            result = evaluate_phase14_wave_transfer(project, run_dir)

        self.assertFalse(result["applicable"])
        self.assertFalse(result["wave_transfer_verified"])


class Phase14MeshConvergenceTests(unittest.TestCase):
    def _reseal_run(self, project: Path) -> None:
        run_dir = project / "solver_runs" / "run_test"
        evidence = seal_phase14_run_evidence(run_dir)
        latest_path = project / "solver_runs" / "latest.json"
        record = json.loads(latest_path.read_text(encoding="utf-8"))
        record["input_sha256"] = hashlib.sha256(
            (run_dir / "model.k").read_bytes()
        ).hexdigest()
        record["model_json_sha256"] = hashlib.sha256(
            (run_dir / "model.json").read_bytes()
        ).hexdigest()
        record["evidence_manifest"] = evidence
        record["evidence_manifest_sha256"] = evidence["sha256"]
        (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
        latest_path.write_text(json.dumps(record), encoding="utf-8")

    def _bind_deck(self, project: Path, deck: str) -> None:
        run_dir = project / "solver_runs" / "run_test"
        (run_dir / "model.k").write_text(deck, encoding="utf-8")
        (project / "model.k").write_text(deck, encoding="utf-8")
        self._reseal_run(project)

    def _project(
        self,
        root: Path,
        name: str,
        *,
        mesh_size_m: float,
        pressure_pa: float,
        force_n: float,
        displacement_m: float,
        geometry_marker: str = "same",
        valid_wave_transfer: bool = True,
    ) -> Path:
        project = root / name
        project.mkdir(parents=True)
        model = {
            "spec": {
                "project_name": name,
                "model_type": "ale_blast_scene",
                "geometry": {"configuration_marker": geometry_marker},
                "mesh": {"size_m": mesh_size_m},
                "termination": {"end_time_s": 0.002},
            },
            "metadata": {
                "coupling_count": 1,
                "lagrangian_shell_element_count": 16,
                "ale_quantitative_outputs": {
                    "pressure_probe_set_id": 300,
                },
                "components": [
                    {
                        "id": "target_plate",
                        "part_id": 3,
                        "response_node_ids": [1],
                    }
                ],
            },
        }
        (project / "model.json").write_text(
            json.dumps(model),
            encoding="utf-8",
        )
        model_k = phase14_deck()
        (project / "model.k").write_text(model_k, encoding="utf-8")
        run_id = "run_test"
        run_dir = project / "solver_runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "model.k").write_text(model_k, encoding="utf-8")
        (run_dir / "model.json").write_bytes((project / "model.json").read_bytes())
        (run_dir / "d3hsp").write_text(VALID_D3HSP, encoding="utf-8")
        (run_dir / "d3plot").write_bytes(b"d3plot-data")
        (run_dir / "dbfsi").write_text(
            dbfsi_text(
                peak_pressure_pa=pressure_pa,
                peak_force_n=force_n if valid_wave_transfer else 0.0,
            ),
            encoding="utf-8",
        )
        (run_dir / "nodout").write_text(
            nodout_text(peak_displacement_m=displacement_m),
            encoding="utf-8",
        )
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
            "blast_configuration": {"mesh_sizes_m": [mesh_size_m]},
        }
        (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
        (project / "solver_runs" / "latest.json").write_text(
            json.dumps(record),
            encoding="utf-8",
        )
        return project

    def _three_projects(
        self,
        root: Path,
        *,
        pressures: tuple[float, float, float] = (160.0, 190.0, 200.0),
    ) -> list[Path]:
        return [
            self._project(
                root,
                "coarse",
                mesh_size_m=0.015,
                pressure_pa=pressures[0],
                force_n=8.0,
                displacement_m=0.004,
            ),
            self._project(
                root,
                "baseline",
                mesh_size_m=0.0125,
                pressure_pa=pressures[1],
                force_n=9.7,
                displacement_m=0.0048,
            ),
            self._project(
                root,
                "fine",
                mesh_size_m=0.010,
                pressure_pa=pressures[2],
                force_n=10.0,
                displacement_m=0.005,
            ),
        ]

    def test_three_valid_levels_converge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = evaluate_phase14_mesh_convergence(
                self._three_projects(Path(temp_dir))
            )

        self.assertEqual("converged", result["status"])
        self.assertTrue(result["convergence_verified"])
        self.assertEqual(
            ["coarse", "baseline", "fine"],
            [item["project_name"] for item in result["projects"]],
        )
        pressure = result["metric_comparisons"][
            "peak_coupled_surface_pressure_pa"
        ]
        self.assertAlmostEqual(0.05, pressure["pairs"][-1]["relative_difference"])
        self.assertGreater(pressure["observed_order"], 0.0)
        self.assertLessEqual(pressure["fine_grid_gci"], result["tolerance"])

    def test_current_configuration_change_does_not_rebind_sealed_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            projects = self._three_projects(root)
            model_path = projects[-1] / "model.json"
            model = json.loads(model_path.read_text(encoding="utf-8"))
            model["spec"]["geometry"]["configuration_marker"] = "different"
            model_path.write_text(json.dumps(model), encoding="utf-8")

            result = evaluate_phase14_mesh_convergence(projects)

        self.assertEqual("converged", result["status"])
        self.assertTrue(result["convergence_verified"])

    def test_mismatched_run_configuration_is_invalid_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            projects = self._three_projects(Path(temp_dir))
            run_model_path = projects[-1] / "solver_runs" / "run_test" / "model.json"
            model = json.loads(run_model_path.read_text(encoding="utf-8"))
            model["spec"]["geometry"]["configuration_marker"] = "different"
            run_model_path.write_text(json.dumps(model), encoding="utf-8")
            self._reseal_run(projects[-1])

            result = evaluate_phase14_mesh_convergence(projects)

        self.assertEqual("invalid_evidence", result["status"])
        checks = {item["id"]: item for item in result["checks"]}
        self.assertFalse(checks["model_specs_match_except_mesh"]["ok"])

    def test_run_model_json_snapshot_is_used_for_convergence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            projects = self._three_projects(root)
            for project in projects:
                (project / "solver_runs" / "run_test" / "model.json").write_bytes(
                    (project / "model.json").read_bytes()
                )
            model_path = projects[-1] / "model.json"
            model = json.loads(model_path.read_text(encoding="utf-8"))
            model["spec"]["geometry"]["configuration_marker"] = "changed_later"
            model_path.write_text(json.dumps(model), encoding="utf-8")

            result = evaluate_phase14_mesh_convergence(projects)

        self.assertEqual("converged", result["status"])
        self.assertTrue(result["convergence_verified"])

    def test_current_mesh_size_change_does_not_rebind_sealed_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            projects = self._three_projects(root)
            model_path = projects[-1] / "model.json"
            model = json.loads(model_path.read_text(encoding="utf-8"))
            model["spec"]["mesh"]["size_m"] = 0.0125
            model_path.write_text(json.dumps(model), encoding="utf-8")

            result = evaluate_phase14_mesh_convergence(projects)

        self.assertEqual("converged", result["status"])
        self.assertTrue(result["convergence_verified"])

    def test_recorded_mesh_size_mismatch_is_invalid_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            projects = self._three_projects(Path(temp_dir))
            project = projects[-1]
            for path in (
                project / "solver_runs" / "latest.json",
                project / "solver_runs" / "run_test" / "run.json",
            ):
                record = json.loads(path.read_text(encoding="utf-8"))
                record["blast_configuration"]["mesh_sizes_m"] = [0.009]
                path.write_text(json.dumps(record), encoding="utf-8")

            result = evaluate_phase14_mesh_convergence(projects)

        self.assertEqual("invalid_evidence", result["status"])
        checks = {item["id"]: item for item in result["checks"]}
        self.assertFalse(checks["mesh_sizes_bound_to_runs"]["ok"])

    def test_rejected_solver_record_is_invalid_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            projects = self._three_projects(Path(temp_dir))
            project = projects[1]
            for path in (
                project / "solver_runs" / "latest.json",
                project / "solver_runs" / "run_test" / "run.json",
            ):
                record = json.loads(path.read_text(encoding="utf-8"))
                record["ok"] = False
                record["solver_evaluation"] = {"ok": False}
                path.write_text(json.dumps(record), encoding="utf-8")

            result = evaluate_phase14_mesh_convergence(projects)

        self.assertEqual("invalid_evidence", result["status"])
        checks = {item["id"]: item for item in result["checks"]}
        self.assertFalse(checks["all_terminal_runs_accepted"]["ok"])

    def test_failed_wave_transfer_is_invalid_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            projects = self._three_projects(root)
            (projects[1] / "solver_runs" / "run_test" / "dbfsi").write_text(
                dbfsi_text(peak_force_n=0.0),
                encoding="utf-8",
            )

            result = evaluate_phase14_mesh_convergence(projects)

        self.assertEqual("invalid_evidence", result["status"])
        checks = {item["id"]: item for item in result["checks"]}
        self.assertFalse(checks["all_wave_transfer_verified"]["ok"])

    def test_project_modified_after_run_does_not_change_sealed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            projects = self._three_projects(root)
            (projects[-1] / "model.k").write_text(
                "*KEYWORD\n*CONTROL_TERMINATION\n0.003\n*END\n",
                encoding="utf-8",
            )

            result = evaluate_phase14_mesh_convergence(projects)

        self.assertEqual("converged", result["status"])
        self.assertTrue(result["convergence_verified"])

    def test_output_only_deck_change_preserves_run_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            projects = self._three_projects(root)
            (projects[-1] / "model.k").write_text(
                phase14_deck().replace(
                    "*END",
                    "*DATABASE_GLSTAT\n1.0e-5\n*END",
                ),
                encoding="utf-8",
            )

            result = evaluate_phase14_mesh_convergence(projects)

        self.assertEqual("converged", result["status"])
        self.assertTrue(result["convergence_verified"])

    def test_existing_declared_output_set_mutation_is_invalid_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            projects = self._three_projects(root)
            project = projects[-1]
            run_dir = project / "solver_runs" / "run_test"
            original = (
                "*KEYWORD\n"
                "*SET_SOLID_LIST_TITLE\n"
                "ALE pressure-path probe elements\n"
                "300\n"
                "1\n"
                "*END\n"
            )
            (run_dir / "model.k").write_text(original, encoding="utf-8")
            (project / "model.k").write_text(original, encoding="utf-8")
            latest_path = project / "solver_runs" / "latest.json"
            latest = json.loads(latest_path.read_text(encoding="utf-8"))
            latest["input_sha256"] = hashlib.sha256(
                (run_dir / "model.k").read_bytes()
            ).hexdigest()
            latest_path.write_text(json.dumps(latest), encoding="utf-8")
            (project / "model.k").write_text(
                original.replace("\n1\n*END", "\n2\n*END"),
                encoding="utf-8",
            )

            result = evaluate_phase14_mesh_convergence(projects)

        self.assertEqual("invalid_evidence", result["status"])
        checks = {item["id"]: item for item in result["checks"]}
        self.assertFalse(checks["all_run_evidence_integrity_valid"]["ok"])

    def test_cross_level_control_card_difference_is_invalid_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            projects = self._three_projects(root)
            different_control = phase14_deck().replace(
                "*END",
                "*CONTROL_TERMINATION\n0.003\n*END",
            )
            self._bind_deck(projects[-1], different_control)

            result = evaluate_phase14_mesh_convergence(projects)

        self.assertEqual("invalid_evidence", result["status"])
        checks = {item["id"]: item for item in result["checks"]}
        self.assertFalse(checks["physical_controls_match_across_levels"]["ok"])

    def test_current_fixed_field_change_does_not_change_sealed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            projects = self._three_projects(root)
            first_field = f"{1.0:>10}{'':>10}"
            shared_deck = phase14_deck().replace(
                "*END",
                f"*CONTROL_TERMINATION\n{first_field}\n*END",
            )
            for project in projects:
                self._bind_deck(project, shared_deck)
            second_field = f"{'':>10}{1.0:>10}"
            (projects[-1] / "model.k").write_text(
                shared_deck.replace(first_field, second_field),
                encoding="utf-8",
            )

            result = evaluate_phase14_mesh_convergence(projects)

        self.assertEqual("converged", result["status"])
        self.assertTrue(result["convergence_verified"])

    def test_finest_pair_above_tolerance_is_not_converged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            projects = self._three_projects(
                Path(temp_dir),
                pressures=(160.0, 170.0, 200.0),
            )

            result = evaluate_phase14_mesh_convergence(projects)

        self.assertEqual("not_converged", result["status"])
        self.assertFalse(result["convergence_verified"])
        pressure = result["metric_comparisons"][
            "peak_coupled_surface_pressure_pa"
        ]
        self.assertFalse(pressure["finest_pair_within_tolerance"])

    def test_increasing_final_error_is_not_converged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            projects = self._three_projects(
                Path(temp_dir),
                pressures=(185.0, 190.0, 200.0),
            )

            result = evaluate_phase14_mesh_convergence(projects)

        self.assertEqual("not_converged", result["status"])
        pressure = result["metric_comparisons"][
            "peak_coupled_surface_pressure_pa"
        ]
        self.assertTrue(pressure["finest_pair_within_tolerance"])
        self.assertFalse(pressure["final_error_nonincreasing"])

    def test_oscillating_response_is_not_converged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            projects = self._three_projects(
                Path(temp_dir),
                pressures=(120.0, 100.0, 110.0),
            )

            result = evaluate_phase14_mesh_convergence(projects)

        self.assertEqual("not_converged", result["status"])
        pressure = result["metric_comparisons"][
            "peak_coupled_surface_pressure_pa"
        ]
        self.assertFalse(pressure["monotonic"])

    def test_nearly_identical_fine_meshes_are_invalid_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            projects = [
                self._project(
                    root,
                    "coarse",
                    mesh_size_m=1.0,
                    pressure_pa=160.0,
                    force_n=8.0,
                    displacement_m=0.004,
                ),
                self._project(
                    root,
                    "baseline",
                    mesh_size_m=0.010001,
                    pressure_pa=190.0,
                    force_n=9.7,
                    displacement_m=0.0048,
                ),
                self._project(
                    root,
                    "fine",
                    mesh_size_m=0.010,
                    pressure_pa=200.0,
                    force_n=10.0,
                    displacement_m=0.005,
                ),
            ]

            result = evaluate_phase14_mesh_convergence(projects)

        self.assertEqual("invalid_evidence", result["status"])
        checks = {item["id"]: item for item in result["checks"]}
        self.assertFalse(checks["refinement_ratios_meaningful"]["ok"])


if __name__ == "__main__":
    unittest.main()
