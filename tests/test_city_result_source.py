from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from lsprepost_mcp.city_result_source import (
    register_city_result_source,
    resolve_city_result_source,
    validate_city_result_source,
)
from lsprepost_mcp.io import read_json
from lsprepost_mcp.run_evidence import seal_phase14_run_evidence


class CityResultSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.project = self.root / "city_project"
        self.result = self.root / "selected_result"
        self.other_result = self.root / "other_result"
        self.project.mkdir()
        self._write_city_model(self.project)
        self._write_result(self.result)
        self._write_result(self.other_result)
        self.model_hash = hashlib.sha256((self.project / "model.k").read_bytes()).hexdigest()
        self.record_path = self.project / "artifacts" / "city_result_source.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_registers_matching_external_result_without_copying_d3plot(self) -> None:
        record = register_city_result_source(self.project, self.result)

        self.assertEqual("registered_external", record["source_kind"])
        self.assertEqual(self.model_hash, record["model_sha256"])
        self.assertIn("d3plot01", record["evidence"])
        self.assertFalse((self.project / "d3plot01").exists())

    def test_rejects_result_with_different_model_hash(self) -> None:
        (self.result / "model.k").write_text("*KEYWORD\n$changed\n*END\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "model.k hash"):
            register_city_result_source(self.project, self.result)

    def test_prefers_valid_internal_solver_run_over_registered_external_result(self) -> None:
        self._write_completed_internal_run()
        register_city_result_source(self.project, self.result)

        resolved = resolve_city_result_source(self.project)

        self.assertEqual("solver_run", resolved["source_kind"])

    def test_registered_output_change_is_invalid_evidence(self) -> None:
        record = register_city_result_source(self.project, self.result)
        (self.result / "dbfsi").write_text("changed\n", encoding="utf-8")

        validation = validate_city_result_source(self.project, record)

        self.assertFalse(validation["ok"])
        self.assertIn("dbfsi", validation["changed_files"])

    def test_invalid_new_registration_preserves_previous_record(self) -> None:
        first = register_city_result_source(self.project, self.result)
        (self.other_result / "nodout").unlink()

        with self.assertRaisesRegex(ValueError, "nodout"):
            register_city_result_source(self.project, self.other_result)

        self.assertEqual(first["result_dir"], read_json(self.record_path)["result_dir"])

    def test_rejects_missing_response_objects(self) -> None:
        self._write_matching_city_models(response_objects=[])

        with self.assertRaisesRegex(ValueError, "response_objects"):
            register_city_result_source(self.project, self.result)

    def test_rejects_unbound_duplicate_and_incomplete_response_mappings(self) -> None:
        cases = (
            (
                "unbound object",
                [{"object_id": "unbound", "fsi_surface_id": 1, "shell_element_ids": [101], "node_ids": [1001]}],
                [{"object_id": "building", "part_ids": [19]}],
                "unbound response object_id",
            ),
            (
                "duplicate object",
                [
                    {"object_id": "building", "fsi_surface_id": 1, "shell_element_ids": [101], "node_ids": [1001]},
                    {"object_id": "building", "fsi_surface_id": 2, "shell_element_ids": [102], "node_ids": [1002]},
                ],
                [{"object_id": "building", "part_ids": [19]}],
                "duplicate response object_id",
            ),
            (
                "duplicate surface",
                [
                    {"object_id": "building", "fsi_surface_id": 1, "shell_element_ids": [101], "node_ids": [1001]},
                    {"object_id": "shelter", "fsi_surface_id": 1, "shell_element_ids": [102], "node_ids": [1002]},
                ],
                [
                    {"object_id": "building", "part_ids": [19]},
                    {"object_id": "shelter", "part_ids": [20]},
                ],
                "duplicate response fsi_surface_id",
            ),
            (
                "empty shell elements",
                [{"object_id": "building", "fsi_surface_id": 1, "shell_element_ids": [], "node_ids": [1001]}],
                [{"object_id": "building", "part_ids": [19]}],
                "shell_element_ids",
            ),
            (
                "non-positive node",
                [{"object_id": "building", "fsi_surface_id": 1, "shell_element_ids": [101], "node_ids": [0]}],
                [{"object_id": "building", "part_ids": [19]}],
                "node_ids",
            ),
        )
        for label, response_objects, semantic_objects, message in cases:
            with self.subTest(label=label):
                self._write_matching_city_models(
                    response_objects=response_objects,
                    semantic_objects=semantic_objects,
                )
                with self.assertRaisesRegex(ValueError, message):
                    register_city_result_source(self.project, self.result)

    def test_rejects_tampered_sealed_internal_run(self) -> None:
        run_dir = self._write_completed_internal_run(record_ok=True)
        register_city_result_source(self.project, self.result)
        (run_dir / "dbfsi").write_text("tampered\n", encoding="utf-8")

        resolved = resolve_city_result_source(self.project)

        self.assertEqual("registered_external", resolved["source_kind"])

    def test_selects_evidence_valid_failed_internal_run_for_assessment_gates(self) -> None:
        self._write_completed_internal_run(status="solver_failed", returncode=1)
        register_city_result_source(self.project, self.result)

        resolved = resolve_city_result_source(self.project)

        self.assertEqual("solver_run", resolved["source_kind"])

    def test_registers_urban_components_only_model_with_expanded_response_objects(self) -> None:
        self._write_urban_components_city_model(self.project)
        self._write_urban_components_city_model(self.result)

        record = register_city_result_source(self.project, self.result)

        self.assertEqual("registered_external", record["source_kind"])

    def test_resolves_complete_project_root_as_validated_legacy_source(self) -> None:
        for name in ("d3hsp", "dbfsi", "glstat", "elout", "nodout", "d3plot", "d3plot01"):
            (self.project / name).write_bytes(f"{name}\n".encode("ascii"))

        resolved = resolve_city_result_source(self.project)

        self.assertEqual("legacy_project_root", resolved["source_kind"])
        self.assertEqual(str(self.project.resolve()), resolved["result_dir"])
        self.assertTrue(resolved["validation"]["ok"])
        self.assertIn("d3plot01", resolved["evidence"])

    def test_registered_external_precedes_legacy_project_root(self) -> None:
        for name in ("d3hsp", "dbfsi", "glstat", "elout", "nodout", "d3plot"):
            (self.project / name).write_bytes(f"{name}\n".encode("ascii"))
        register_city_result_source(self.project, self.result)

        resolved = resolve_city_result_source(self.project)

        self.assertEqual("registered_external", resolved["source_kind"])

    def test_incomplete_project_root_is_not_a_result_source(self) -> None:
        for name in ("d3hsp", "dbfsi", "glstat", "d3plot"):
            (self.project / name).write_bytes(f"{name}\n".encode("ascii"))

        resolved = resolve_city_result_source(self.project)

        self.assertEqual("none", resolved["source_kind"])
        self.assertFalse(resolved["validation"]["ok"])

    def _write_city_model(
        self,
        directory: Path,
        *,
        response_objects: list[dict[str, object]] | None = None,
        semantic_objects: list[dict[str, object]] | None = None,
    ) -> None:
        if response_objects is None:
            response_objects = [
                {
                    "object_id": "building",
                    "fsi_surface_id": 1,
                    "shell_element_ids": [101],
                    "node_ids": [1001],
                }
            ]
        if semantic_objects is None:
            semantic_objects = [{"object_id": "building", "part_ids": [19]}]
        (directory / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")
        (directory / "model.json").write_text(
            json.dumps(
                {
                    "metadata": {
                        "model_type": "city_street_blast_scene",
                        "semantic_objects": semantic_objects,
                        "response_objects": response_objects,
                    },
                }
            ),
            encoding="utf-8",
        )

    def _write_result(self, directory: Path) -> None:
        directory.mkdir()
        self._write_city_model(directory)
        for name in ("d3hsp", "dbfsi", "glstat", "elout", "nodout", "d3plot", "d3plot01"):
            (directory / name).write_bytes(f"{name}\n".encode("ascii"))

    def _write_matching_city_models(
        self,
        *,
        response_objects: list[dict[str, object]],
        semantic_objects: list[dict[str, object]] | None = None,
    ) -> None:
        self._write_city_model(
            self.project,
            response_objects=response_objects,
            semantic_objects=semantic_objects,
        )
        self._write_city_model(
            self.result,
            response_objects=response_objects,
            semantic_objects=semantic_objects,
        )

    def _write_urban_components_city_model(self, directory: Path) -> None:
        response_objects = [
            {
                "object_id": "commercial_supermarket",
                "fsi_surface_id": 1,
                "shell_element_ids": [101],
                "node_ids": [1001],
            },
            {
                "object_id": "parked_vehicle_1",
                "fsi_surface_id": 2,
                "shell_element_ids": [102],
                "node_ids": [1002],
            },
            {
                "object_id": "parked_vehicle_2",
                "fsi_surface_id": 3,
                "shell_element_ids": [103],
                "node_ids": [1003],
            },
            {
                "object_id": "traffic_light_1",
                "fsi_surface_id": 4,
                "shell_element_ids": [104],
                "node_ids": [1004],
            },
        ]
        urban_components = {
            "commercial_supermarket": {"part_ids": [19]},
            "parked_vehicles": {"part_ids": [26, 27]},
            "traffic_lights": {"part_ids": [35]},
        }
        (directory / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")
        (directory / "model.json").write_text(
            json.dumps(
                {
                    "metadata": {
                        "model_type": "city_street_blast_scene",
                        "urban_components": urban_components,
                        "response_objects": response_objects,
                    },
                }
            ),
            encoding="utf-8",
        )

    def _write_completed_internal_run(
        self,
        *,
        record_ok: bool = False,
        status: str = "completed",
        returncode: int = 0,
    ) -> Path:
        run_id = "run_20260731T000000000000Z_city"
        runs_dir = self.project / "solver_runs"
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True)
        self._write_city_model(run_dir)
        for name in ("d3hsp", "dbfsi", "glstat", "elout", "nodout", "d3plot", "d3plot01"):
            (run_dir / name).write_bytes(f"{name}\n".encode("ascii"))
        evidence = seal_phase14_run_evidence(
            run_dir,
            required_output_prefixes=("d3hsp", "d3plot", "dbfsi", "elout", "nodout"),
        )
        record = {
            "ok": record_ok,
            "status": status,
            "returncode": returncode,
            "run_id": run_id,
            "result_variant": "city_street_blast",
            "evidence_integrity": {"ok": True},
            "evidence_manifest": evidence,
            "evidence_manifest_sha256": evidence["sha256"],
            "wave_transfer_acceptance": {"wave_transfer_verified": False},
        }
        (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
        (runs_dir / "latest.json").write_text(json.dumps(record), encoding="utf-8")
        return run_dir


if __name__ == "__main__":
    unittest.main()
