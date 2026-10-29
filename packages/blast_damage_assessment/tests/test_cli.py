import io
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import blast_damage_assessment
from blast_damage_assessment.api import assess, capabilities
from blast_damage_assessment.cli import main
from blast_damage_assessment.errors import ContractError
from packages.blast_damage_assessment.tests.test_pipeline import FakePipelineAdapter, PipelineCase


class ApiCliTests(PipelineCase, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_api_and_cli_share_one_deterministic_pipeline(self):
        root, _, api_request = self.make_case("api-output")
        api_result = assess(api_request, adapter=FakePipelineAdapter())
        cli_request = {**api_request, "output_dir": str(root / "cli-output")}
        request_path = root / "request.json"
        request_path.write_text(json.dumps(cli_request), encoding="utf-8")
        stdout, stderr = io.StringIO(), io.StringIO()
        code = main(
            ["evaluate", "--request", str(request_path)],
            adapter=FakePipelineAdapter(),
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(code, 0, stderr.getvalue())
        cli_envelope = json.loads(stdout.getvalue())
        self.assertEqual(cli_envelope["assessment_id"], api_result.assessment_id)
        self.assertEqual(cli_envelope["assessment_fingerprint"], api_result.assessment_fingerprint)
        api_snapshot = json.loads((root / "api-output" / "assessment_snapshot.json").read_text(encoding="utf-8"))
        cli_snapshot = json.loads((root / "cli-output" / "assessment_snapshot.json").read_text(encoding="utf-8"))
        self.assertEqual(api_snapshot, cli_snapshot)

    def test_cli_exit_codes_distinguish_valid_blocked_contract_and_operation(self):
        root, _, request = self.make_case("blocked-output")
        request_path = root / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        self.assertEqual(
            main(["evaluate", "--request", str(request_path)], adapter=FakePipelineAdapter(blocked=True), stdout=io.StringIO(), stderr=io.StringIO()),
            0,
        )
        bad = root / "bad.json"
        bad.write_text("{}", encoding="utf-8")
        self.assertEqual(
            main(["evaluate", "--request", str(bad)], stdout=io.StringIO(), stderr=io.StringIO()),
            2,
        )
        _, _, failed_request = self.make_case("failed-output")
        failed = root / "failed.json"
        failed.write_text(json.dumps(failed_request), encoding="utf-8")
        self.assertEqual(
            main(["evaluate", "--request", str(failed)], adapter=FakePipelineAdapter(fail=True), stdout=io.StringIO(), stderr=io.StringIO()),
            3,
        )
        class InvalidResultAdapter(FakePipelineAdapter):
            def probe(self, result_dir):
                raise ContractError("corrupt d3plot")

        self.assertEqual(
            main(["evaluate", "--request", str(failed)], adapter=InvalidResultAdapter(), stdout=io.StringIO(), stderr=io.StringIO()), 3)

    def test_capabilities_are_static_and_include_lasso_rules_and_schemas(self):
        value = capabilities()
        self.assertEqual(value["package"]["version"], "0.1.0")
        self.assertIn("lasso_python", value["dependencies"])
        self.assertIn("numpy", value["dependencies"])
        self.assertEqual(len(value["rule_packs"]), 2)
        self.assertIn("blast_damage.assessment_request@1", value["schemas"]["request"])
        self.assertNotIn("deepseek", json.dumps(value).lower())

    def test_cli_maps_internal_value_and_key_errors_to_operational_failure(self):
        root, _, request = self.make_case("internal-error")
        request_path = root / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        for error in (ValueError("invalid result shape"), KeyError("missing runtime field")):
            with self.subTest(error=type(error).__name__):
                stderr = io.StringIO()
                with patch("blast_damage_assessment.cli.assess", side_effect=error):
                    code = main(
                        ["evaluate", "--request", str(request_path)],
                        stdout=io.StringIO(),
                        stderr=stderr,
                    )
                self.assertEqual(code, 3)
                self.assertIn("assessment failed", stderr.getvalue())

    def test_assess_and_capabilities_are_exported_at_package_root(self):
        self.assertIs(blast_damage_assessment.assess, assess)
        self.assertIs(blast_damage_assessment.capabilities, capabilities)


if __name__ == "__main__":
    unittest.main()
