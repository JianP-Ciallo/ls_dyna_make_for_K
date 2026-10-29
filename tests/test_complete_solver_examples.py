from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path

from lsprepost_mcp.config import ROOT
from lsprepost_mcp.provenance import verify_generated_project


EXAMPLES_ROOT = ROOT / "examples" / "complete_solver_cases"
CORE_FILES = {
    "model.k",
    "model.json",
    "checks.json",
    "open_model.cfile",
    "export_manifest.json",
    "summary.json",
    "solver_preflight.json",
    "sample_manifest.json",
    "artifacts/cfiles.json",
}
CASE_CARDS = {
    "sample_rod_impact_plate": {
        "*INITIAL_VELOCITY_NODE",
        "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE",
        "*BOUNDARY_SPC_SET",
        "*CONTROL_TERMINATION",
        "*DATABASE_BINARY_D3PLOT",
    },
    "sample_cube_top_corner_load": {
        "*HOURGLASS_TITLE",
        "*DEFINE_CURVE",
        "*LOAD_NODE_SET",
        "*BOUNDARY_SPC_SET",
        "*CONTROL_TERMINATION",
        "*DATABASE_BINARY_D3PLOT",
    },
    "sample_plate_pressure": {
        "*SET_SEGMENT",
        "*DEFINE_CURVE",
        "*LOAD_SEGMENT_SET",
        "*BOUNDARY_SPC_SET",
        "*CONTROL_SHELL",
        "*CONTROL_TERMINATION",
        "*DATABASE_BINARY_D3PLOT",
    },
}


class CompleteSolverExampleTests(unittest.TestCase):
    def test_examples_are_generated_solver_drafts_with_valid_manifests(self) -> None:
        self.assertTrue((EXAMPLES_ROOT / "README.zh-CN.md").is_file())
        for project_name, required_cards in CASE_CARDS.items():
            with self.subTest(project_name=project_name):
                project = EXAMPLES_ROOT / project_name
                relative_files = {
                    path.relative_to(project).as_posix()
                    for path in project.rglob("*")
                    if path.is_file()
                }
                self.assertTrue(CORE_FILES.issubset(relative_files))

                checks = json.loads((project / "checks.json").read_text(encoding="utf-8"))
                preflight = json.loads((project / "solver_preflight.json").read_text(encoding="utf-8"))
                keyword = (project / "model.k").read_text(encoding="utf-8")
                self.assertTrue(checks["ok"])
                self.assertTrue(checks["readiness"]["ok_for_solver_draft"])
                self.assertEqual(preflight["status"], "solver_input_draft_ready")
                self.assertTrue(preflight["provenance_ok"])
                self.assertFalse(preflight["real_lsdyna_run_completed"])
                for card in required_cards:
                    self.assertIn(card, keyword)

                provenance = verify_generated_project(project)
                self.assertTrue(provenance["ok"], provenance)
                self.assertEqual(provenance["classification"], "generated_by_lsprepost_mcp")

                manifest = json.loads((project / "sample_manifest.json").read_text(encoding="utf-8"))
                for name, expected_hash in manifest["files"].items():
                    actual_hash = hashlib.sha256((project / name).read_bytes()).hexdigest()
                    self.assertEqual(actual_hash, expected_hash, name)

                for path in project.rglob("*"):
                    if not path.is_file() or path.suffix.lower() not in {".json", ".cfile", ".k"}:
                        continue
                    text = path.read_text(encoding="utf-8", errors="replace")
                    self.assertIsNone(re.search(r"[A-Za-z]:\\", text), str(path))


if __name__ == "__main__":
    unittest.main()
