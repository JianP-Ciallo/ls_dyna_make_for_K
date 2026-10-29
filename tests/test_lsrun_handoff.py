from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lsprepost_mcp.lsrun_handoff import (
    launch_lsrun_handoff,
    prepare_lsrun_handoff,
    recover_lsrun_result,
)


class FakeProcess:
    pid = 4321


class LsRunHandoffTests(unittest.TestCase):
    def make_project(self, root: Path) -> Path:
        project = root / "phase15_air_gap"
        project.mkdir()
        (project / "model.k").write_text(
            "*KEYWORD\n*TITLE\nPhase 15 conforming air gap\n*END\n",
            encoding="utf-8",
        )
        (project / "model.json").write_text(
            json.dumps(
                {
                    "spec": {"model_type": "phase15_axisymmetric_blast"},
                    "metadata": {
                        "phase15": {
                            "coupling_mode": "conforming_air_gap",
                            "probes": {
                                "concrete": [
                                    {
                                        "id": "INTERFACE_WALL",
                                        "element_id": 101,
                                    },
                                    {"id": "P1", "element_id": 102},
                                    {"id": "P2", "element_id": 103},
                                    {"id": "P3", "element_id": 104},
                                ],
                                "ale": [
                                    {"id": "TNT_NEAR", "element_id": 11},
                                    {"id": "AIR_MID_GAP", "element_id": 12},
                                    {"id": "AIR_INTERFACE", "element_id": 13},
                                ],
                            },
                            "output": {"history_output_dt_s": 2.0e-6},
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        return project

    def make_executables(self, root: Path) -> tuple[Path, Path]:
        lsrun = root / "lsrun.exe"
        lsdyna = root / "lsdyna.exe"
        lsrun.write_bytes(b"fake lsrun")
        lsdyna.write_bytes(b"fake lsdyna")
        return lsrun, lsdyna

    def prepare(self, root: Path) -> tuple[Path, dict]:
        project = self.make_project(root)
        lsrun, lsdyna = self.make_executables(root)
        return project, prepare_lsrun_handoff(
            project,
            lsrun,
            lsdyna,
            ncpu=4,
            memory="512m",
        )

    def write_required_outputs(self, run_dir: Path) -> None:
        (run_dir / "d3hsp").write_text(
            "kinetic energy ........ 1\n"
            "internal energy ....... 1\n"
            "total energy .......... 2\n"
            "*** normal termination ***\n",
            encoding="utf-8",
        )
        (run_dir / "d3plot").write_bytes(b"d3plot-data")
        (run_dir / "elout").write_text("elout-data\n", encoding="utf-8")
        (run_dir / "nodout").write_text("nodout-data\n", encoding="utf-8")

    def test_prepare_snapshots_inputs_without_changing_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = self.make_project(root)
            lsrun, lsdyna = self.make_executables(root)
            source_hash = hashlib.sha256((project / "model.k").read_bytes()).hexdigest()

            record = prepare_lsrun_handoff(
                project,
                lsrun,
                lsdyna,
                ncpu=4,
                memory="512m",
            )

            run_dir = Path(record["run_dir"])
            self.assertEqual("handoff_prepared", record["status"])
            self.assertNotEqual(project.resolve(), run_dir.resolve())
            self.assertEqual(project / "solver_runs", run_dir.parent)
            self.assertEqual(
                (project / "model.k").read_bytes(),
                (run_dir / "model.k").read_bytes(),
            )
            self.assertEqual(
                source_hash,
                hashlib.sha256((project / "model.k").read_bytes()).hexdigest(),
            )
            self.assertEqual(record, json.loads((run_dir / "run.json").read_text()))

    def test_launch_records_opened_not_running(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, handoff = self.prepare(root)

            with patch(
                "lsprepost_mcp.lsrun_handoff.subprocess.Popen",
                return_value=FakeProcess(),
            ) as popen:
                record = launch_lsrun_handoff(project, handoff)

            self.assertEqual("handoff_opened", record["status"])
            self.assertNotEqual("running", record["status"])
            self.assertEqual(4321, record["lsrun_pid"])
            command = popen.call_args.args[0]
            self.assertEqual(Path(handoff["lsrun_exe"]), Path(command[0]))
            self.assertEqual(Path(handoff["input"]), Path(command[1]))
            self.assertEqual(Path(handoff["run_dir"]), Path(popen.call_args.kwargs["cwd"]))

    def test_recovery_refuses_changed_input_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, handoff = self.prepare(root)
            run_dir = Path(handoff["run_dir"])
            (run_dir / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")

            result = recover_lsrun_result(project, str(handoff["run_id"]))

            self.assertFalse(result["ok"])
            self.assertEqual("invalid_evidence", result["status"])
            self.assertIn("model.k", result["mismatched_inputs"])

    def test_recovery_requires_conforming_outputs_without_dbfsi(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, handoff = self.prepare(root)
            run_dir = Path(handoff["run_dir"])
            (run_dir / "d3hsp").write_text(
                "*** normal termination ***\n",
                encoding="utf-8",
            )
            (run_dir / "d3plot").write_bytes(b"d3plot-data")
            (run_dir / "elout").write_text("elout-data\n", encoding="utf-8")

            result = recover_lsrun_result(project, str(handoff["run_id"]))

            self.assertFalse(result["ok"])
            self.assertEqual("incomplete_outputs", result["status"])
            self.assertEqual(["nodout"], result["missing_required_outputs"])

    def test_recovery_evaluates_and_seals_conforming_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, handoff = self.prepare(root)
            run_dir = Path(handoff["run_dir"])
            self.write_required_outputs(run_dir)
            solver_evaluation = {"ok": True, "checks": []}
            wave_evaluation = {"wave_transfer_verified": True, "checks": []}

            with (
                patch(
                    "lsprepost_mcp.lsrun_handoff._evaluate_d3hsp",
                    return_value=solver_evaluation,
                ) as solver,
                patch(
                    "lsprepost_mcp.lsrun_handoff.evaluate_phase15_wave_transfer",
                    return_value=wave_evaluation,
                ) as wave,
            ):
                result = recover_lsrun_result(project, str(handoff["run_id"]))

            self.assertTrue(result["ok"])
            self.assertEqual("completed", result["status"])
            self.assertTrue(result["evidence_validation"]["ok"])
            self.assertTrue((run_dir / "evidence_manifest.json").is_file())
            solver.assert_called_once()
            wave.assert_called_once()
            self.assertFalse((run_dir / "dbfsi").exists())

    def test_recovery_rejects_unsafe_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self.make_project(Path(temp_dir))

            with self.assertRaisesRegex(ValueError, "run_id"):
                recover_lsrun_result(project, "../outside")


if __name__ == "__main__":
    unittest.main()
