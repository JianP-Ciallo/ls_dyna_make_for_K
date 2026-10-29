"""Replay accepted solver evidence through the project-owned bridge (no solver launch)."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import platform
import shutil
import time
import threading
from pathlib import Path

from lsprepost_mcp.assessment_result_source import register_assessment_result_source
from lsprepost_mcp.damage_assessment_bridge import (
    assess_completed_run, assessment_capabilities, latest_registered_assessment,
)
from lsprepost_mcp.refined_blast.store import RefinedBlastStore
from lsprepost_mcp.web.damage_assessment_api import DamageAssessmentWebApi


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def verify_http_recovery(root: Path, reference: dict) -> dict:
    """Recover actual evidence in an acceptance-only workbench; use real HTTP handlers."""
    from lsprepost_mcp.refined_blast.assembler import RefinedBlastPackage
    from lsprepost_mcp.refined_blast.contracts import default_scenario_draft
    from lsprepost_mcp.web.app import create_server
    from lsprepost_mcp.web import refined_blast_api as api_module

    api = api_module.RefinedBlastApi(root)
    project_id = "phase18-reference-acceptance"
    scenario = api_module._json_value(default_scenario_draft())
    scenario["scenario_id"] = "commercial"
    payload = {
        "schema_version": "refined_blast_create@2",
        "building": {"asset_id": "commercial_supermarket_detailed_building"},
        "project": {
            "schema_version": "refined_building_blast@1", "project_id": project_id,
            "preset_reference": "none", "preset_version": "1", "project_overrides": {},
            "expert_extensions": {}, "scenario_set": [scenario], "confirmation_records": [],
            "provenance": {},
            "created_at": "2026-09-08T00:00:00Z", "updated_at": "2026-09-08T00:00:00Z",
        },
    }
    api.post("/projects", payload)
    store = api._store
    stored = store.load_project(project_id)
    original = Path(reference["result_dir"])
    manifest = Path(reference["manifest"])
    package = RefinedBlastPackage(
        files={"model.k": (original / "model.k").read_bytes(), "manifest.json": manifest.read_bytes()},
        manifest={"schema_version": "recovered_reference_package@1", "source_model_sha256": digest(original / "model.k")},
        symbol_to_numeric_id={}, building_artifact_fingerprint=stored.project.building_artifact_fingerprint,
    )
    artifact = store.commit_generated_package(
        project_id, "commercial", api_module._package_payload(package), stored.revision,
        before_project_commit=lambda item, projected: api._write_generated_index(item, package.package_fingerprint, projected),
    )
    identity = {
        "scenario_id": "commercial", "generated_revision": artifact.revision,
        "artifact_fingerprint": artifact.fingerprint, "package_fingerprint": package.package_fingerprint,
    }
    snapshot = store.materialize_action_snapshot(project_id, "recovered-commercial-http", package.files)
    run = snapshot / "solver_runs" / original.name
    shutil.copytree(original, run)
    shutil.copy2(manifest, run / "manifest.json")
    shutil.copy2(run / "run.json", run.parent / "latest.json")
    register_assessment_result_source(
        store=store, project_id=project_id, snapshot=snapshot, identity=identity,
        run_record=json.loads((run / "run.json").read_text(encoding="utf-8")),
        semantic_format="legacy_deck_manifest",
    )
    # Select the server-owned store without replacing any handler or assessment function.
    api_module._DEFAULT_API = api
    server = create_server("127.0.0.1", 0, open_browser=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(method: str, path: str, body=None):
        conn = http.client.HTTPConnection(*server.server_address, timeout=180)
        conn.request(method, path, body=None if body is None else json.dumps(body),
                     headers={} if body is None else {"Content-Type": "application/json"})
        response = conn.getresponse()
        data = response.read()
        status = response.status
        conn.close()
        assert status == 200, (status, data.decode("utf-8"))
        return data

    try:
        capability = json.loads(request("GET", "/api/damage-assessment/capabilities"))["result"]
        assert capability["available"]
        prefix = f"/api/refined-building-blast/projects/{project_id}"
        result = json.loads(request("POST", prefix + "/assess-latest-run", {
            "schema_version": "lsprepost_mcp.damage_assessment_request@1", **identity,
        }))["result"]
        latest = json.loads(request("GET", prefix + "/assessments/latest"))["result"]
        assert result["assessment_id"] == latest["assessment_id"]
        assert result["assessment_fingerprint"] == reference["fingerprint"]
        for name, artifact_ref in result["artifacts"].items():
            data = request("GET", prefix + f"/assessments/{result['assessment_id']}/artifacts/{name}")
            assert hashlib.sha256(data).hexdigest() == artifact_ref["sha256"]
        return {"status": "passed", "real_http": True, "restored_reference_fixture": True,
                "fingerprint": result["assessment_fingerprint"], "gate": result["gate"],
                "all_eight_artifacts_verified": True}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        api_module._DEFAULT_API = None
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accepted-summary", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    accepted = json.loads(args.accepted_summary.read_text(encoding="utf-8"))
    root = args.output_root.absolute()
    root.mkdir(parents=True, exist_ok=False)
    capabilities = assessment_capabilities()
    if capabilities.get("available") is not True:
        raise RuntimeError("the accepted optional assessment dependency is unavailable")
    summary = {
        "schema_version": "lsprepost_mcp.damage_bridge_acceptance@1",
        "python": platform.python_version(), "capabilities": capabilities,
        "accepted_summary_sha256": digest(args.accepted_summary),
        "cases": {}, "status": "running",
    }
    try:
        for label, reference in accepted["cases"].items():
            started = time.monotonic()
            original = Path(reference["result_dir"])
            manifest = Path(reference["manifest"])
            before = {str(path): digest(path) for path in original.iterdir() if path.is_file()}
            before[str(manifest)] = digest(manifest)
            project_id = "phase18-reference-acceptance"
            with RefinedBlastStore(root / label) as store:
                project = store._layout(project_id, create=True)
                snapshot = store.materialize_action_snapshot(
                    project_id, f"recovered-{label}",
                    {"model.k": (original / "model.k").read_bytes(), "manifest.json": manifest.read_bytes()},
                )
                run = snapshot / "solver_runs" / original.name
                shutil.copytree(original, run)
                shutil.copy2(manifest, run / "manifest.json")
                shutil.copy2(original / "run.json", run.parent / "latest.json")
                run_record = json.loads((run / "run.json").read_text(encoding="utf-8"))
                identity = {
                    "scenario_id": label, "generated_revision": 1,
                    "artifact_fingerprint": digest(snapshot / "model.k"),
                    "package_fingerprint": digest(snapshot / "manifest.json"),
                }
                register_assessment_result_source(
                    store=store, project_id=project_id, snapshot=snapshot,
                    identity=identity, run_record=run_record,
                    semantic_format="legacy_deck_manifest",
                )
                result = assess_completed_run(
                    project_id=project_id, case_id=label, project_dir=project,
                    run_dir=run, semantic_manifest=snapshot / "manifest.json",
                )
                assert result["assessment_fingerprint"] == reference["fingerprint"], label
                assert result["gate"] == "provisional", label
                assert result["registration_state"] == "registered", label
                latest = latest_registered_assessment(project)
                assert latest["assessment_id"] == result["assessment_id"]
                web = DamageAssessmentWebApi(store)
                for name in result["artifacts"]:
                    status, headers, data = web.artifact(
                        project_dir=project, assessment_id=result["assessment_id"], artifact_name=name,
                    )
                    assert status == 200 and "Content-Type" in headers
                    assert hashlib.sha256(data).hexdigest() == result["artifacts"][name]["sha256"]
                for raw_path, expected in before.items():
                    assert digest(Path(raw_path)) == expected, "source evidence changed"
                output = project / result["output_relative_path"]
                envelope = json.loads((output / "assessment_result.json").read_text(encoding="utf-8"))
                row = {
                    "assessment_id": result["assessment_id"],
                    "fingerprint": result["assessment_fingerprint"],
                    "gate": result["gate"], "severity": result["severity"],
                    "same_standalone_fingerprint": True, "source_unchanged": True,
                    "all_eight_web_artifacts_verified": True,
                    "result_sha256": digest(output / "assessment_result.json"),
                    "output": output.relative_to(root).as_posix(),
                    "runtime_seconds": time.monotonic() - started,
                }
                assert envelope["assessment_id"] == row["assessment_id"]
                summary["cases"][label] = row
                print(json.dumps({"case": label, **row}), flush=True)
        summary["http_recovery"] = verify_http_recovery(root / "http-recovery", accepted["cases"]["commercial"])
        summary["status"] = "passed"
    except Exception as exc:
        summary["status"] = "failed"
        summary["failure_type"] = type(exc).__name__
        raise
    finally:
        (root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
