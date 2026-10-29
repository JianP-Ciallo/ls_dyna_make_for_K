import tempfile
import unittest
from pathlib import Path

from blast_damage_assessment.contracts import AssessmentRequest, FileReference
from blast_damage_assessment.errors import ContractError
from blast_damage_assessment.output_store import AtomicAssessmentOutput
from blast_damage_assessment.source_evidence import inspect_source


class AtomicOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.result_dir = self.root / "solver-run"
        self.result_dir.mkdir()
        for name, data in {
            "model.k": b"model",
            "model.json": b"{}",
            "run.json": b"{}",
            "d3hsp": b"normal",
            "d3plot": b"states",
            "assessment_semantics.json": b"{}",
        }.items():
            (self.result_dir / name).write_bytes(data)
        import hashlib

        manifest = self.result_dir / "assessment_semantics.json"
        request = AssessmentRequest(
            schema_version="blast_damage.assessment_request@1",
            project_id="p",
            case_id="c",
            result_dir=self.result_dir,
            semantic_manifest=FileReference(manifest, hashlib.sha256(manifest.read_bytes()).hexdigest()),
            building_rule_pack="building_research_reference@1",
            ground_rule_pack="ground_research_reference@1",
            output_dir=self.root / "published",
        )
        self.evidence = inspect_source(request)
        self.output_dir = request.output_dir

    def test_commit_publishes_one_complete_directory(self):
        with AtomicAssessmentOutput(self.output_dir, self.evidence) as output:
            output.write_text("assessment_result.json", "{}")
            output.write_bytes("nested/evidence.bin", b"proof")
            output.commit()

        self.assertEqual((self.output_dir / "assessment_result.json").read_text(), "{}")
        self.assertEqual((self.output_dir / "nested/evidence.bin").read_bytes(), b"proof")
        self.assertFalse(any(self.root.glob(".published.staging-*")))

    def test_exception_discards_staging_and_never_publishes(self):
        with self.assertRaisesRegex(RuntimeError, "boom"):
            with AtomicAssessmentOutput(self.output_dir, self.evidence) as output:
                output.write_text("partial.json", "{}")
                raise RuntimeError("boom")
        self.assertFalse(self.output_dir.exists())
        self.assertFalse(any(self.root.glob(".published.staging-*")))

    def test_source_change_aborts_commit_without_publishing(self):
        with self.assertRaisesRegex(Exception, "changed"):
            with AtomicAssessmentOutput(self.output_dir, self.evidence) as output:
                output.write_text("assessment_result.json", "{}")
                (self.result_dir / "d3hsp").write_text("changed", encoding="utf-8")
                output.commit()
        self.assertFalse(self.output_dir.exists())

    def test_rejects_artifact_name_traversal_and_absolute_paths(self):
        with AtomicAssessmentOutput(self.output_dir, self.evidence) as output:
            for name in ("../escape.json", "a\\b.json", str(self.root / "absolute.json")):
                with self.subTest(name=name):
                    with self.assertRaisesRegex(ContractError, "artifact name"):
                        output.write_text(name, "bad")

    def test_never_overwrites_existing_final_directory(self):
        self.output_dir.mkdir()
        with self.assertRaisesRegex(ContractError, "already exists"):
            AtomicAssessmentOutput(self.output_dir, self.evidence)


if __name__ == "__main__":
    unittest.main()
