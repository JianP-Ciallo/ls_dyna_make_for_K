import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from blast_damage_assessment.contracts import AssessmentRequest, FileReference
from blast_damage_assessment.errors import ContractError
from blast_damage_assessment.source_evidence import (
    SourceChangedError,
    continuous_d3plot_series,
    inspect_source,
    revalidate_source,
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.result_dir = self.root / "solver-run"
        self.result_dir.mkdir()
        for name, data in {
            "model.k": b"*KEYWORD\n*END\n",
            "model.json": b"{}",
            "run.json": b'{"status":"completed"}',
            "d3hsp": b"normal termination",
            "d3plot": b"base",
            "d3plot01": b"one",
            "d3plot02": b"two",
            "glstat": b"energy",
        }.items():
            (self.result_dir / name).write_bytes(data)
        self.manifest = self.result_dir / "assessment_semantics.json"
        self.manifest.write_text('{"schema_version":"test@1"}', encoding="utf-8")
        self.request = AssessmentRequest(
            schema_version="blast_damage.assessment_request@1",
            project_id="p1",
            case_id="c1",
            result_dir=self.result_dir,
            semantic_manifest=FileReference(self.manifest, digest(self.manifest), "test@1"),
            building_rule_pack="building_research_reference@1",
            ground_rule_pack="ground_research_reference@1",
            output_dir=self.root / "assessment-output",
        )

    def test_continuous_series_orders_base_and_numbered_files(self):
        series = continuous_d3plot_series(self.result_dir)
        self.assertEqual([path.name for path in series], ["d3plot", "d3plot01", "d3plot02"])

    def test_series_rejects_missing_base_gap_and_empty_files(self):
        (self.result_dir / "d3plot").unlink()
        with self.assertRaisesRegex(ContractError, "base"):
            continuous_d3plot_series(self.result_dir)
        (self.result_dir / "d3plot").write_bytes(b"base")
        (self.result_dir / "d3plot01").unlink()
        with self.assertRaisesRegex(ContractError, "gap"):
            continuous_d3plot_series(self.result_dir)
        (self.result_dir / "d3plot01").write_bytes(b"")
        with self.assertRaisesRegex(ContractError, "empty"):
            continuous_d3plot_series(self.result_dir)

    def test_inspection_records_required_and_optional_evidence(self):
        evidence = inspect_source(self.request)
        by_name = {item.relative_path: item for item in evidence.files}
        self.assertEqual(by_name["model.k"].role, "solver_input")
        self.assertEqual(by_name["d3plot02"].role, "state_database")
        self.assertEqual(by_name["glstat"].role, "solver_quality_optional")
        self.assertNotIn("matsum", by_name)
        self.assertEqual(by_name["model.json"].size_bytes, 2)

    def test_rejects_missing_or_empty_required_evidence(self):
        (self.result_dir / "d3hsp").unlink()
        with self.assertRaisesRegex(ContractError, "d3hsp"):
            inspect_source(self.request)
        (self.result_dir / "d3hsp").write_bytes(b"")
        with self.assertRaisesRegex(ContractError, "empty"):
            inspect_source(self.request)

    def test_rejects_unreadable_run_json(self):
        (self.result_dir / "run.json").write_text("not-json", encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "run.json"):
            inspect_source(self.request)

    def test_rejects_manifest_hash_mismatch(self):
        bad = AssessmentRequest(
            **{
                **self.request.__dict__,
                "semantic_manifest": FileReference(self.manifest, "0" * 64),
            }
        )
        with self.assertRaisesRegex(ContractError, "manifest hash"):
            inspect_source(bad)

    def test_rejects_relative_manifest_traversal(self):
        outside = self.root / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        bad = AssessmentRequest(
            **{
                **self.request.__dict__,
                "semantic_manifest": FileReference(Path("../outside.json"), digest(outside)),
            }
        )
        with self.assertRaisesRegex(ContractError, "traversal"):
            inspect_source(bad)

    def test_rejects_existing_or_contained_output(self):
        self.request.output_dir.mkdir()
        with self.assertRaisesRegex(ContractError, "already exists"):
            inspect_source(self.request)
        self.request.output_dir.rmdir()
        inside = AssessmentRequest(**{**self.request.__dict__, "output_dir": self.result_dir / "new"})
        with self.assertRaisesRegex(ContractError, "overlap"):
            inspect_source(inside)

    def test_rejects_output_parent_symlink_when_platform_allows_it(self):
        real_parent = self.root / "real-output-parent"
        real_parent.mkdir()
        linked_parent = self.root / "linked-output-parent"
        try:
            linked_parent.symlink_to(real_parent, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symlink creation is unavailable: {exc}")
        bad = AssessmentRequest(
            **{**self.request.__dict__, "output_dir": linked_parent / "assessment"}
        )
        with self.assertRaisesRegex(ContractError, "reparse|symlink"):
            inspect_source(bad)

    def test_source_change_is_detected(self):
        evidence = inspect_source(self.request)
        (self.result_dir / "d3hsp").write_text("mutated", encoding="utf-8")
        with self.assertRaises(SourceChangedError):
            revalidate_source(evidence)
        self.assertFalse(self.request.output_dir.exists())


if __name__ == "__main__":
    unittest.main()
