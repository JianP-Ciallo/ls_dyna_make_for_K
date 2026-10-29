from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lsprepost_mcp.run_evidence import (
    seal_phase14_run_evidence,
    validate_phase14_run_evidence,
    validate_run_record_identity,
)


class Phase14RunEvidenceTests(unittest.TestCase):
    def _run_dir(self, root: Path) -> Path:
        run_dir = root / "solver_runs" / "run_test"
        run_dir.mkdir(parents=True)
        files = {
            "model.k": "*KEYWORD\n*END\n",
            "model.json": '{"spec":{"mesh":{"size_m":0.01}}}',
            "d3hsp": "*** termination time reached ***\n",
            "dbfsi": "time = 0\n1 0 0 0 0 0\n",
            "nodout": "nodout\n",
        }
        for name, content in files.items():
            (run_dir / name).write_text(content, encoding="utf-8")
        (run_dir / "d3plot").write_bytes(b"d3plot")
        (run_dir / "d3plot01").write_bytes(b"d3plot-continued")
        return run_dir

    def test_sealed_evidence_detects_input_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = self._run_dir(Path(temp_dir))
            reference = seal_phase14_run_evidence(run_dir)
            (run_dir / "model.k").write_text("*KEYWORD\n$ changed\n*END\n", encoding="utf-8")

            result = validate_phase14_run_evidence(run_dir, reference)

        self.assertFalse(result["ok"])
        self.assertIn("model.k", result["mismatched_files"])

    def test_sealed_evidence_detects_output_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = self._run_dir(Path(temp_dir))
            reference = seal_phase14_run_evidence(run_dir)
            (run_dir / "dbfsi").write_text(
                "time = 0\n1 1000000 1000 0 0 0\n",
                encoding="utf-8",
            )

            result = validate_phase14_run_evidence(run_dir, reference)

        self.assertFalse(result["ok"])
        self.assertIn("dbfsi", result["mismatched_files"])

    def test_missing_evidence_manifest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = self._run_dir(Path(temp_dir))

            result = validate_phase14_run_evidence(run_dir, {})

        self.assertFalse(result["ok"])
        self.assertEqual("evidence_manifest_reference_missing", result["reason"])

    def test_run_and_latest_records_must_have_same_identity(self) -> None:
        run_record = {
            "run_id": "run_test",
            "status": "completed",
            "returncode": 0,
            "ok": True,
            "input_sha256": "a" * 64,
            "model_json_sha256": "b" * 64,
            "evidence_manifest_sha256": "c" * 64,
        }
        latest_record = json.loads(json.dumps(run_record))
        latest_record["input_sha256"] = "d" * 64

        result = validate_run_record_identity(latest_record, run_record)

        self.assertFalse(result["ok"])
        self.assertIn("input_sha256", result["mismatched_fields"])


if __name__ == "__main__":
    unittest.main()
