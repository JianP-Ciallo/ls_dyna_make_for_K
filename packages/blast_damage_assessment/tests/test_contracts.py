import json
import math
import unittest
from pathlib import Path

from blast_damage_assessment.canonical import canonical_json_bytes, sha256_json
from blast_damage_assessment.contracts import (
    ArtifactReference,
    AssessmentResult,
    AssessmentRequest,
    FileReference,
    GateState,
    Issue,
    MetricValue,
    Severity,
)
from blast_damage_assessment.errors import ContractError, UnsupportedSchemaError
from blast_damage_assessment.schema import parse_request


def valid_request(**overrides):
    raw = {
        "schema_version": "blast_damage.assessment_request@1",
        "project_id": "project-01",
        "case_id": "commercial-01",
        "result_dir": "results\\run-01",
        "semantic_manifest": {
            "path": "case\\manifest.json",
            "sha256": "a" * 64,
        },
        "building_rule_pack": "building_research_reference@1",
        "ground_rule_pack": "ground_research_reference@1",
        "output_dir": "assessment\\run-01",
        "state_chunk_size": 4,
    }
    raw.update(overrides)
    return raw


class RequestContractTests(unittest.TestCase):
    def test_parses_v1_request_into_immutable_contract(self):
        request = parse_request(valid_request())

        self.assertIsInstance(request, AssessmentRequest)
        self.assertEqual(request.result_dir.as_posix(), "results/run-01")
        self.assertEqual(request.semantic_manifest.path.as_posix(), "case/manifest.json")
        self.assertEqual(request.state_chunk_size, 4)
        with self.assertRaises(Exception):
            request.case_id = "changed"

    def test_rejects_unknown_major_version(self):
        raw = valid_request(schema_version="blast_damage.assessment_request@2")
        with self.assertRaisesRegex(UnsupportedSchemaError, "@2"):
            parse_request(raw)

    def test_rejects_unknown_root_field(self):
        raw = {**valid_request(), "deepseek_api_key": "must-not-be-accepted"}
        with self.assertRaisesRegex(ContractError, "unknown fields"):
            parse_request(raw)

    def test_rejects_unknown_file_reference_field(self):
        raw = valid_request()
        raw["semantic_manifest"] = {**raw["semantic_manifest"], "trusted": True}
        with self.assertRaisesRegex(ContractError, "unknown fields"):
            parse_request(raw)

    def test_severity_rejects_boolean_and_out_of_range_values(self):
        for value in (True, False, -1, 5):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    Severity(value)

    def test_optional_v1_fields_may_be_absent(self):
        raw = valid_request()
        raw.pop("state_chunk_size")
        request = parse_request(json.dumps(raw))

        self.assertEqual(request.state_chunk_size, 4)
        self.assertIsNone(request.semantic_manifest.schema_version)

    def test_rejects_duplicate_json_keys(self):
        duplicate = '{"schema_version":"blast_damage.assessment_request@1",' \
            '"schema_version":"blast_damage.assessment_request@1"}'
        with self.assertRaisesRegex(ContractError, "duplicate key"):
            parse_request(duplicate)

    def test_rejects_invalid_identifiers_hashes_and_chunk_sizes(self):
        cases = (
            ({"project_id": ""}, "project_id"),
            ({"case_id": "   "}, "case_id"),
            ({"state_chunk_size": 0}, "state_chunk_size"),
            ({"state_chunk_size": True}, "state_chunk_size"),
            ({"semantic_manifest": {"path": "manifest.json", "sha256": "bad"}}, "sha256"),
        )
        for changes, expected in cases:
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(ContractError, expected):
                    parse_request(valid_request(**changes))

    def test_rejects_nonfinite_numbers_from_json(self):
        raw = json.dumps(valid_request()).replace(
            '"state_chunk_size": 4', '"state_chunk_size": NaN'
        )
        with self.assertRaisesRegex(ContractError, "non-finite"):
            parse_request(raw)


class CanonicalJsonTests(unittest.TestCase):
    def test_mapping_insertion_order_does_not_change_hash(self):
        first = {"b": [2, 3], "a": 1}
        second = {"a": 1, "b": [2, 3]}
        self.assertEqual(sha256_json(first), sha256_json(second))

    def test_required_value_change_changes_hash(self):
        self.assertNotEqual(
            sha256_json(valid_request(case_id="a")),
            sha256_json(valid_request(case_id="b")),
        )

    def test_paths_enums_and_dataclasses_have_stable_records(self):
        reference = FileReference(Path("a\\b.json"), "b" * 64)
        encoded = canonical_json_bytes(
            {"gate": GateState.PROVISIONAL, "reference": reference}
        ).decode("utf-8")
        self.assertEqual(
            encoded,
            '{"gate":"provisional","reference":{"path":"a/b.json",'
            '"schema_version":null,"sha256":"' + "b" * 64 + '"}}',
        )

    def test_rejects_nonfinite_and_unknown_values(self):
        for value in (math.nan, math.inf, object()):
            with self.subTest(value=value):
                with self.assertRaises((TypeError, ValueError)):
                    canonical_json_bytes({"value": value})


class ValueContractTests(unittest.TestCase):
    def test_metric_preserves_raw_and_standard_units(self):
        metric = MetricValue(
            raw_value=12.0,
            raw_unit="mm",
            standard_value=0.012,
            standard_unit="m",
            conversion_id="length.mm_to_m@1",
        )
        self.assertEqual(metric.raw_value, 12.0)
        self.assertEqual(metric.standard_value, 0.012)

    def test_supporting_contracts_validate_required_fields(self):
        issue = Issue(code="manifest.inferred", message="Legacy semantics inferred")
        artifact = ArtifactReference(
            path=Path("evidence\\index.json"),
            sha256="c" * 64,
            media_type="application/json",
            size_bytes=10,
        )
        self.assertEqual(issue.code, "manifest.inferred")
        self.assertEqual(artifact.path.as_posix(), "evidence/index.json")

        with self.assertRaises(ValueError):
            FileReference(Path("manifest.json"), "not-a-hash")
        with self.assertRaises(ValueError):
            MetricValue(1.0, "m", float("nan"), "m", "identity.si@1")

    def test_assessment_result_has_explicit_json_safe_public_representation(self):
        result = AssessmentResult(
            schema_version="blast_damage.assessment_result@1",
            assessment_id="a" * 24,
            execution_status="completed",
            gate=GateState.PROVISIONAL,
            severity=2,
            assessment_fingerprint="b" * 64,
            artifacts={
                "damage_report.html": ArtifactReference(
                    path=Path("damage_report.html"),
                    sha256="c" * 64,
                    media_type="text/html; charset=utf-8",
                    size_bytes=12,
                )
            },
            warnings=(
                Issue(
                    code="manifest.inferred",
                    message="Legacy semantics inferred",
                    details={"source": "manifest.json"},
                ),
            ),
            blockers=(),
            review_items=(Issue(code="review.required", message="Review required"),),
            state_chunk_size=4,
        )

        assert result.to_dict() == {
            "schema_version": "blast_damage.assessment_result@1",
            "assessment_id": "a" * 24,
            "execution_status": "completed",
            "gate": "provisional",
            "severity": 2,
            "assessment_fingerprint": "b" * 64,
            "artifacts": {
                "damage_report.html": {
                    "path": "damage_report.html",
                    "sha256": "c" * 64,
                    "media_type": "text/html; charset=utf-8",
                    "size_bytes": 12,
                    "schema_version": None,
                }
            },
            "warnings": [
                {
                    "code": "manifest.inferred",
                    "message": "Legacy semantics inferred",
                    "details": {"source": "manifest.json"},
                }
            ],
            "blockers": [],
            "review_items": [
                {
                    "code": "review.required",
                    "message": "Review required",
                    "details": {},
                }
            ],
            "state_chunk_size": 4,
        }


if __name__ == "__main__":
    unittest.main()
