from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import lsprepost_mcp.damage_assessment_bridge as bridge


REQUEST_SCHEMA = "blast_damage.assessment_request@1"
RESULT_SCHEMA = "blast_damage.assessment_result@1"
SEMANTICS_SCHEMA = "blast_damage.model_semantics@1"
ARTIFACT_NAMES = {
    "assessment_request.json",
    "assessment_result.json",
    "assessment_snapshot.json",
    "evidence_index.json",
    "rule_snapshot.json",
    "damage_report.html",
    "building_components.csv",
    "ground_regions.csv",
}


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_path(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _capabilities(
    *,
    request_schema: str = REQUEST_SCHEMA,
    result_schema: str = RESULT_SCHEMA,
    include_ground: bool = True,
    lasso_version: str | None = "2.0.4",
) -> dict[str, object]:
    packs = [
        {
            "id": "building_research_reference@1",
            "subject": "building",
            "sha256": "b" * 64,
            "formal_eligible": False,
        }
    ]
    if include_ground:
        packs.append(
            {
                "id": "ground_research_reference@1",
                "subject": "ground",
                "sha256": "c" * 64,
                "formal_eligible": False,
            }
        )
    return {
        "package": {"name": "blast-damage-assessment", "version": "0.1.0"},
        "schemas": {
            "request": [request_schema],
            "result": [result_schema],
            "snapshot": ["blast_damage.assessment_snapshot@1"],
            "semantics": [SEMANTICS_SCHEMA],
        },
        "adapters": [{"id": "lsdyna_d3plot", "version": "1.0.0"}],
        "dependencies": {"lasso_python": lasso_version, "numpy": "2.3.5"},
        "rule_packs": packs,
        "unit_systems": ["SI_m_s_kg_N_Pa"],
        "available_fields": [],
    }


class _PublicResult:
    def __init__(self, value: dict[str, object]):
        self._value = value

    def to_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self._value))


class _AssessmentFake:
    def __init__(
        self,
        *,
        fingerprint: str = "d" * 64,
        assessment_id: str = "a" * 24,
        corrupt_artifact: bool = False,
        malformed: bool = False,
        failure: Exception | None = None,
        gate: str = "provisional",
    ):
        self.fingerprint = fingerprint
        self.assessment_id = assessment_id
        self.corrupt_artifact = corrupt_artifact
        self.malformed = malformed
        self.failure = failure
        self.gate = gate
        self.requests: list[dict[str, object]] = []
        self.output_existed: list[bool] = []
        self._lock = threading.Lock()

    def __call__(self, request: object) -> object:
        if self.failure is not None:
            raise self.failure
        assert isinstance(request, dict)
        output_dir = Path(str(request["output_dir"]))
        with self._lock:
            self.requests.append(dict(request))
            self.output_existed.append(output_dir.exists())
        output_dir.mkdir(parents=False, exist_ok=False)

        payloads = {
            "assessment_request.json": b'{"request":1}',
            "assessment_snapshot.json": b'{"snapshot":1}',
            "evidence_index.json": b'{"evidence":1}',
            "rule_snapshot.json": b'{"rules":1}',
            "damage_report.html": b"<html>report</html>",
            "building_components.csv": b"component_id,severity\n",
            "ground_regions.csv": b"region_id,severity\n",
        }
        artifacts: dict[str, dict[str, object]] = {}
        for name, data in payloads.items():
            path = output_dir / name
            path.write_bytes(data)
            artifacts[name] = {
                "path": name,
                "sha256": _sha_bytes(data),
                "media_type": (
                    "text/html; charset=utf-8"
                    if name.endswith(".html")
                    else "text/csv; charset=utf-8"
                    if name.endswith(".csv")
                    else "application/json"
                ),
                "size_bytes": len(data),
                "schema_version": None,
            }
        envelope = {
            "schema_version": RESULT_SCHEMA,
            "assessment_id": self.assessment_id,
            "execution_status": "completed",
            "gate": self.gate,
            "severity": None if self.gate == "blocked" else 2,
            "assessment_fingerprint": self.fingerprint,
            "artifacts": dict(artifacts),
            "warnings": [],
            "blockers": [],
            "review_items": [],
            "state_chunk_size": 4,
        }
        result_bytes = json.dumps(
            envelope, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        result_path = output_dir / "assessment_result.json"
        result_path.write_bytes(result_bytes)
        artifacts["assessment_result.json"] = {
            "path": "assessment_result.json",
            "sha256": _sha_bytes(result_bytes),
            "media_type": "application/json",
            "size_bytes": len(result_bytes),
            "schema_version": RESULT_SCHEMA,
        }
        if self.corrupt_artifact:
            report_path = output_dir / "damage_report.html"
            original = report_path.read_bytes()
            report_path.write_bytes(b"X" + original[1:])
        result = {**envelope, "artifacts": artifacts}
        if self.malformed:
            result.pop("gate")
        return _PublicResult(result)


class DamageAssessmentBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_parent = Path("var/tmp")
        temp_parent.mkdir(parents=True, exist_ok=True)
        self.root = (temp_parent / f"bridge-{uuid.uuid4().hex}").absolute()
        self.project_dir = (
            self.root
            / "workspace"
            / "refined_building_blast"
            / "project-1"
        )
        for name in ("drafts", "previews", "generated", "evidence", "results"):
            (self.project_dir / name).mkdir(parents=True, exist_ok=True)
        self.run_dir = (
            self.project_dir
            / "generated"
            / "action-launch-lsdyna-fixture"
            / "solver_runs"
            / "run_20260904T000000000000Z_fixture"
        )
        self.run_dir.mkdir(parents=True)
        self.semantic_manifest = self.run_dir / "assessment_semantics.json"
        self.semantic_manifest.write_text(
            json.dumps({"schema_version": SEMANTICS_SCHEMA}), encoding="utf-8"
        )
        (self.run_dir / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")
        (self.run_dir / "manifest.json").write_text(
            '{"schema_version":"phase18.solver_blast.deck_manifest@4"}',
            encoding="utf-8",
        )
        self.source_record = {
            "schema_version": "lsprepost_mcp.damage_assessment_source@1",
            "project_id": "project-1",
            "scenario_id": "scenario-1",
            "generated_revision": 2,
            "artifact_fingerprint": "1" * 64,
            "package_fingerprint": "2" * 64,
            "snapshot_relative_path": "generated/action-launch-lsdyna-fixture",
            "run_id": self.run_dir.name,
            "run_status": "completed",
            "model_sha256": _sha_path(self.run_dir / "model.k"),
            "manifest_sha256": _sha_path(self.run_dir / "manifest.json"),
            "semantics_sha256": _sha_path(self.semantic_manifest),
            "registered_at": "2026-09-04T00:00:00Z",
        }
        self.resolved = {
            "record": dict(self.source_record),
            "run_dir": self.run_dir,
            "semantic_manifest": self.semantic_manifest,
        }

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _module(
        self,
        assessment: _AssessmentFake | None = None,
        capabilities: dict[str, object] | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            capabilities=lambda: capabilities or _capabilities(),
            assess=assessment or _AssessmentFake(),
        )

    def _assess(
        self,
        assessment: _AssessmentFake | None = None,
        capabilities: dict[str, object] | None = None,
    ) -> dict[str, object]:
        with (
            mock.patch.object(
                bridge, "resolve_assessment_result_source", return_value=self.resolved
            ),
            mock.patch.object(
                bridge.importlib,
                "import_module",
                return_value=self._module(assessment, capabilities),
            ),
        ):
            return bridge.assess_completed_run(
                project_id="project-1",
                case_id="case-1",
                project_dir=self.project_dir,
                run_dir=self.run_dir,
                semantic_manifest=self.semantic_manifest,
            )

    def test_importing_bridge_does_not_import_optional_package(self) -> None:
        with mock.patch.object(bridge.importlib, "import_module") as loader:
            importlib.reload(bridge)
        loader.assert_not_called()

    def test_missing_optional_package_is_reported_without_raising(self) -> None:
        error = ModuleNotFoundError("No module named 'blast_damage_assessment'")
        error.name = "blast_damage_assessment"
        with mock.patch.object(bridge.importlib, "import_module", side_effect=error):
            result = bridge.assessment_capabilities()

        self.assertEqual(result["available"], False)
        self.assertEqual(result["reason"], "optional_package_not_installed")
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_capability_rejects_wrong_schema_and_missing_rule_pack(self) -> None:
        cases = (
            _capabilities(request_schema="blast_damage.assessment_request@2"),
            _capabilities(result_schema="blast_damage.assessment_result@2"),
            _capabilities(include_ground=False),
            _capabilities(lasso_version=None),
        )
        for capabilities in cases:
            with self.subTest(capabilities=capabilities):
                with mock.patch.object(
                    bridge.importlib,
                    "import_module",
                    return_value=self._module(capabilities=capabilities),
                ):
                    result = bridge.assessment_capabilities()
                self.assertEqual(result["available"], False)
                self.assertEqual(result["reason"], "incompatible_capabilities")

    def test_capability_accepts_public_v1_contract(self) -> None:
        with mock.patch.object(
            bridge.importlib, "import_module", return_value=self._module()
        ):
            result = bridge.assessment_capabilities()

        self.assertEqual(result["available"], True)
        self.assertEqual(result["request_schema"], REQUEST_SCHEMA)
        self.assertEqual(result["result_schema"], RESULT_SCHEMA)
        self.assertEqual(result["adapter"], {"id": "lsdyna_d3plot", "version": "1.0.0"})
        self.assertEqual(
            {item["id"] for item in result["rule_packs"]},
            {
                "building_research_reference@1",
                "ground_research_reference@1",
            },
        )

    def test_assessment_rejects_incompatible_package_as_unavailable_before_output(self) -> None:
        assessment = _AssessmentFake()
        incompatible = _capabilities(
            result_schema="blast_damage.assessment_result@2"
        )
        with (
            mock.patch.object(
                bridge, "resolve_assessment_result_source", return_value=self.resolved
            ),
            mock.patch.object(
                bridge.importlib,
                "import_module",
                return_value=self._module(assessment, incompatible),
            ),
            self.assertRaisesRegex(
                bridge.DamageAssessmentUnavailableError,
                "incompatible_capabilities",
            ),
        ):
            bridge.assess_completed_run(
                project_id="project-1",
                case_id="case-1",
                project_dir=self.project_dir,
                run_dir=self.run_dir,
                semantic_manifest=self.semantic_manifest,
            )
        self.assertEqual(assessment.requests, [])
        self.assertFalse((self.project_dir / "artifacts").exists())

    def test_constructs_exact_request_and_registers_verified_artifacts(self) -> None:
        assessment = _AssessmentFake()
        result = self._assess(assessment)

        self.assertEqual(len(assessment.requests), 1)
        request = assessment.requests[0]
        self.assertEqual(
            set(request),
            {
                "schema_version",
                "project_id",
                "case_id",
                "result_dir",
                "semantic_manifest",
                "building_rule_pack",
                "ground_rule_pack",
                "output_dir",
                "state_chunk_size",
            },
        )
        self.assertEqual(request["schema_version"], REQUEST_SCHEMA)
        self.assertEqual(Path(request["result_dir"]), self.run_dir)
        self.assertEqual(
            request["semantic_manifest"],
            {
                "path": str(self.semantic_manifest),
                "sha256": self.source_record["semantics_sha256"],
                "schema_version": SEMANTICS_SCHEMA,
            },
        )
        self.assertEqual(request["state_chunk_size"], 4)
        output_dir = Path(request["output_dir"])
        self.assertEqual(
            output_dir.parent,
            self.project_dir / "artifacts" / "damage_assessments",
        )
        self.assertEqual(assessment.output_existed, [False])
        self.assertEqual(result["registration_state"], "registered")
        self.assertEqual(result["assessment_id"], "a" * 24)
        self.assertEqual(set(result["artifacts"]), ARTIFACT_NAMES)

        registry_path = output_dir.parent / "registry.json"
        registry_text = registry_path.read_text(encoding="utf-8")
        self.assertNotIn(str(self.project_dir), registry_text)
        registry = json.loads(registry_text)
        self.assertEqual(
            registry["schema_version"],
            "lsprepost_mcp.damage_assessment_registry@1",
        )
        self.assertEqual(len(registry["records"]), 1)
        record = registry["records"][0]
        self.assertEqual(record["source_evidence_digest"], bridge._source_digest(self.source_record))
        self.assertEqual(record["output_relative_path"], output_dir.relative_to(self.project_dir).as_posix())
        self.assertEqual(
            bridge.latest_registered_assessment(self.project_dir)["assessment_id"],
            "a" * 24,
        )

    def test_rejects_mismatched_paths_before_calling_assess(self) -> None:
        assessment = _AssessmentFake()
        with (
            mock.patch.object(
                bridge, "resolve_assessment_result_source", return_value=self.resolved
            ),
            mock.patch.object(
                bridge.importlib,
                "import_module",
                return_value=self._module(assessment),
            ),
            self.assertRaisesRegex(ValueError, "trusted"),
        ):
            bridge.assess_completed_run(
                project_id="project-1",
                case_id="case-1",
                project_dir=self.project_dir,
                run_dir=self.run_dir.parent / "attacker",
                semantic_manifest=self.semantic_manifest,
            )
        self.assertEqual(assessment.requests, [])

    def test_package_exception_or_malformed_result_does_not_create_registry(self) -> None:
        for assessment in (
            _AssessmentFake(failure=RuntimeError("adapter failed")),
            _AssessmentFake(malformed=True),
        ):
            with self.subTest(assessment=assessment):
                with self.assertRaises((RuntimeError, ValueError)):
                    self._assess(assessment)
                self.assertFalse(
                    (self.project_dir / "artifacts" / "damage_assessments" / "registry.json").exists()
                )

    def test_artifact_hash_mismatch_does_not_overwrite_existing_registry(self) -> None:
        first = self._assess(_AssessmentFake())
        registry_path = self.project_dir / "artifacts" / "damage_assessments" / "registry.json"
        before = registry_path.read_bytes()

        with self.assertRaisesRegex(ValueError, "hash"):
            self._assess(
                _AssessmentFake(
                    assessment_id="e" * 24,
                    fingerprint="f" * 64,
                    corrupt_artifact=True,
                )
            )
        self.assertEqual(registry_path.read_bytes(), before)
        self.assertEqual(first["registration_state"], "registered")

    def test_source_mutation_after_assessment_prevents_registration(self) -> None:
        with (
            mock.patch.object(
                bridge,
                "resolve_assessment_result_source",
                side_effect=[self.resolved, ValueError("source hash mismatch")],
            ),
            mock.patch.object(
                bridge.importlib,
                "import_module",
                return_value=self._module(_AssessmentFake()),
            ),
            self.assertRaisesRegex(ValueError, "source hash mismatch"),
        ):
            bridge.assess_completed_run(
                project_id="project-1",
                case_id="case-1",
                project_dir=self.project_dir,
                run_dir=self.run_dir,
                semantic_manifest=self.semantic_manifest,
            )
        self.assertFalse(
            (self.project_dir / "artifacts" / "damage_assessments" / "registry.json").exists()
        )

    def test_registry_failure_is_recoverable_and_preserves_output(self) -> None:
        with mock.patch.object(
            bridge, "_write_registry", side_effect=OSError("disk unavailable")
        ):
            result = self._assess(_AssessmentFake())

        self.assertEqual(result["registration_state"], "completed_unregistered")
        output_dir = self.project_dir.joinpath(
            *Path(result["output_relative_path"]).parts
        )
        self.assertTrue((output_dir / "assessment_result.json").is_file())
        self.assertFalse(
            (self.project_dir / "artifacts" / "damage_assessments" / "registry.json").exists()
        )
        retry = self._assess(_AssessmentFake())
        self.assertEqual(retry["registration_state"], "registered")
        self.assertNotEqual(retry["output_relative_path"], result["output_relative_path"])
        self.assertTrue((output_dir / "assessment_result.json").is_file())

    def test_blocked_result_is_registered_without_inventing_severity(self) -> None:
        result = self._assess(_AssessmentFake(gate="blocked"))
        self.assertEqual(result["gate"], "blocked")
        self.assertIsNone(result["severity"])
        self.assertIsNone(bridge.latest_registered_assessment(self.project_dir)["severity"])

    def test_latest_rejects_malformed_registry_without_returning_it(self) -> None:
        self._assess(_AssessmentFake())
        registry_path = (
            self.project_dir
            / "artifacts"
            / "damage_assessments"
            / "registry.json"
        )
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["records"][0]["severity"] = True
        registry_path.write_text(json.dumps(registry), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "severity"):
            bridge.latest_registered_assessment(self.project_dir)

    def test_duplicate_is_idempotent_and_conflicting_fingerprint_is_rejected(self) -> None:
        self._assess(_AssessmentFake())
        # Re-registering unchanged source evidence must not change its identity.
        self.resolved["record"]["registered_at"] = "2026-09-08T12:00:00Z"
        second = self._assess(_AssessmentFake())
        registry_path = self.project_dir / "artifacts" / "damage_assessments" / "registry.json"
        self.assertEqual(len(json.loads(registry_path.read_text())["records"]), 1)
        self.assertEqual(second["registration_state"], "registered_existing")

        with self.assertRaisesRegex(ValueError, "conflicting fingerprint"):
            self._assess(
                _AssessmentFake(
                    assessment_id="a" * 24,
                    fingerprint="e" * 64,
                )
            )
        self.assertEqual(len(json.loads(registry_path.read_text())["records"]), 1)

    def test_concurrent_distinct_results_use_unique_outputs_and_lose_no_records(self) -> None:
        counter = iter(("a" * 24, "b" * 24))
        counter_lock = threading.Lock()
        requests: list[dict[str, object]] = []

        def concurrent_assess(request: object) -> object:
            with counter_lock:
                assessment_id = next(counter)
            assessment = _AssessmentFake(
                assessment_id=assessment_id,
                fingerprint=assessment_id[0] * 64,
            )
            result = assessment(request)
            with counter_lock:
                requests.extend(assessment.requests)
            return result

        module = SimpleNamespace(
            capabilities=lambda: _capabilities(),
            assess=concurrent_assess,
        )

        def assess_once(_index: int) -> dict[str, object]:
            return bridge.assess_completed_run(
                project_id="project-1",
                case_id="case-1",
                project_dir=self.project_dir,
                run_dir=self.run_dir,
                semantic_manifest=self.semantic_manifest,
            )

        with (
            mock.patch.object(
                bridge, "resolve_assessment_result_source", return_value=self.resolved
            ),
            mock.patch.object(bridge.importlib, "import_module", return_value=module),
        ):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(assess_once, range(2)))

        self.assertEqual(len(requests), 2)
        self.assertEqual(
            len({str(request["output_dir"]) for request in requests}),
            2,
        )
        self.assertEqual(
            len({result["output_relative_path"] for result in results}),
            2,
        )
        registry_path = self.project_dir / "artifacts" / "damage_assessments" / "registry.json"
        records = json.loads(registry_path.read_text())["records"]
        self.assertEqual({record["assessment_id"] for record in records}, {"a" * 24, "b" * 24})

    def test_registered_assessment_resolves_historical_record_by_closed_id(self) -> None:
        first = self._assess(_AssessmentFake())
        self._assess(
            _AssessmentFake(
                assessment_id="b" * 24,
                fingerprint="e" * 64,
            )
        )

        found = bridge.registered_assessment(self.project_dir, "a" * 24)

        self.assertEqual(found["assessment_id"], "a" * 24)
        self.assertEqual(found["output_relative_path"], first["output_relative_path"])
        with self.assertRaises(bridge.DamageAssessmentNotFoundError):
            bridge.registered_assessment(self.project_dir, "f" * 24)


if __name__ == "__main__":
    unittest.main()
