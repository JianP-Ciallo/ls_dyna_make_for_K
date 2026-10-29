from __future__ import annotations

import hashlib
import http.client
import json
from pathlib import Path

import pytest

import lsprepost_mcp.web.damage_assessment_api as damage_api
import lsprepost_mcp.web.refined_blast_api as refined_api_module
from lsprepost_mcp.web.http_utils import ApiError
from lsprepost_mcp.web.refined_blast_api import RefinedBlastApi

from test_phase18f_api import _post, _web_server
from test_phase18f_external_actions import (
    _create_payload,
    _generated,
    _identity,
)


REQUEST_SCHEMA = "lsprepost_mcp.damage_assessment_request@1"


def _prepared_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[RefinedBlastApi, str, dict[str, object]]:
    artifact, payload = _create_payload()
    monkeypatch.setattr(
        refined_api_module,
        "_compile_building",
        lambda _value: artifact,
    )
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]
    generated = _generated(api, project_id)
    return api, project_id, _identity(generated)


def _request_payload(identity: dict[str, object]) -> dict[str, object]:
    return {"schema_version": REQUEST_SCHEMA, **identity}


def _source(
    project_dir: Path, identity: dict[str, object]
) -> dict[str, object]:
    run_dir = (
        project_dir
        / "generated"
        / "action-launch-lsdyna-fixture"
        / "solver_runs"
        / "run_20260904T000000000000Z_web"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    semantics = run_dir / "assessment_semantics.json"
    semantics.write_text(
        '{"schema_version":"blast_damage.model_semantics@1"}',
        encoding="utf-8",
    )
    return {
        "record": {
            "schema_version": "lsprepost_mcp.damage_assessment_source@1",
            "project_id": project_dir.name,
            **identity,
            "snapshot_relative_path": "generated/action-launch-lsdyna-fixture",
            "run_id": run_dir.name,
            "run_status": "completed",
            "model_sha256": "1" * 64,
            "manifest_sha256": "2" * 64,
            "semantics_sha256": hashlib.sha256(semantics.read_bytes()).hexdigest(),
            "registered_at": "2026-09-04T00:00:00Z",
        },
        "run_dir": run_dir,
        "semantic_manifest": semantics,
    }


def _available() -> dict[str, object]:
    return {
        "schema_version": "lsprepost_mcp.damage_assessment_capabilities@1",
        "available": True,
    }


def _result() -> dict[str, object]:
    return {
        "schema_version": "lsprepost_mcp.damage_assessment_response@1",
        "registration_state": "registered",
        "assessment_id": "a" * 24,
        "execution_status": "completed",
        "gate": "provisional",
        "severity": 2,
        "assessment_fingerprint": "b" * 64,
        "output_relative_path": "artifacts/damage_assessments/assessment_" + "c" * 32,
        "artifacts": {},
        "warnings": [],
        "blockers": [],
        "review_items": [],
    }


def _raw_get(
    address: tuple[str, int], path: str
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection(*address, timeout=10)
    connection.request("GET", path)
    response = connection.getresponse()
    body = response.read()
    headers = {key.lower(): value for key, value in response.getheaders()}
    status = response.status
    connection.close()
    return status, headers, body


def test_capability_endpoint_reports_optional_absence_without_breaking_modeling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        damage_api.bridge,
        "assessment_capabilities",
        lambda: {
            "schema_version": "lsprepost_mcp.damage_assessment_capabilities@1",
            "available": False,
            "reason": "optional_package_not_installed",
        },
    )

    with _web_server() as address:
        status, _headers, body = _raw_get(
            address, "/api/damage-assessment/capabilities"
        )
        modeling_status, _headers, modeling_body = _raw_get(
            address, "/api/refined-building-blast/capabilities"
        )

    payload = json.loads(body)
    assert status == 200
    assert payload["result"]["available"] is False
    assert payload["result"]["reason"] == "optional_package_not_installed"
    assert modeling_status == 200
    assert json.loads(modeling_body)["result"]["schema_version"] == "refined_building_blast@1"


def test_assess_latest_accepts_only_current_identity_and_supplies_trusted_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api, project_id, identity = _prepared_api(tmp_path, monkeypatch)
    project_dir = api._store._layout(project_id, create=False)
    source = _source(project_dir, identity)
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        damage_api.bridge, "assessment_capabilities", _available
    )
    monkeypatch.setattr(
        damage_api, "resolve_assessment_result_source", lambda _path: source
    )

    def assess(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return _result()

    monkeypatch.setattr(damage_api.bridge, "assess_completed_run", assess)
    monkeypatch.setattr(api, "_project_operation", lambda *_: pytest.fail("assessment must not rebuild the model"))

    result = api.post(
        f"/projects/{project_id}/assess-latest-run",
        _request_payload(identity),
    )

    assert result["assessment_id"] == "a" * 24
    assert observed == {
        "project_id": project_id,
        "case_id": identity["scenario_id"],
        "project_dir": project_dir,
        "run_dir": source["run_dir"],
        "semantic_manifest": source["semantic_manifest"],
    }
    assert str(project_dir) not in json.dumps(result)


def test_assess_latest_rejects_browser_paths_rules_and_stale_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api, project_id, identity = _prepared_api(tmp_path, monkeypatch)
    for field, value in (
        ("result_dir", "C:/attacker"),
        ("semantic_manifest", "../manifest.json"),
        ("python_module", "evil"),
        ("building_rule_pack", "unreviewed@1"),
    ):
        with pytest.raises(ApiError) as unknown:
            api.post(
                f"/projects/{project_id}/assess-latest-run",
                {**_request_payload(identity), field: value},
            )
        assert unknown.value.code == "unknown_field"

    stale = _request_payload(identity)
    stale["generated_revision"] = int(identity["generated_revision"]) + 1
    with pytest.raises(ApiError) as rejected:
        api.post(f"/projects/{project_id}/assess-latest-run", stale)
    assert rejected.value.code == "artifact_stale"


def test_assessment_unavailable_returns_409_and_does_not_resolve_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api, project_id, identity = _prepared_api(tmp_path, monkeypatch)
    monkeypatch.setattr(
        damage_api.bridge,
        "assessment_capabilities",
        lambda: {
            "schema_version": "lsprepost_mcp.damage_assessment_capabilities@1",
            "available": False,
            "reason": "optional_package_not_installed",
        },
    )
    resolved: list[Path] = []
    monkeypatch.setattr(
        damage_api,
        "resolve_assessment_result_source",
        lambda path: resolved.append(path),
    )

    with pytest.raises(ApiError) as unavailable:
        api.post(
            f"/projects/{project_id}/assess-latest-run",
            _request_payload(identity),
        )

    assert unavailable.value.status == 409
    assert unavailable.value.code == "assessment_unavailable"
    assert resolved == []
    assert api.get("/capabilities", {})["schema_version"] == "refined_building_blast@1"

    monkeypatch.setattr(refined_api_module, "_DEFAULT_API", api)
    with _web_server() as address:
        status, response = _post(
            address,
            f"/api/refined-building-blast/projects/{project_id}/assess-latest-run",
            _request_payload(identity),
        )

    assert status == 409
    assert response["ok"] is False
    assert response["error"]["code"] == "assessment_unavailable"


def test_source_identity_mismatch_is_rejected_before_bridge_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api, project_id, identity = _prepared_api(tmp_path, monkeypatch)
    project_dir = api._store._layout(project_id, create=False)
    source = _source(project_dir, identity)
    source["record"]["package_fingerprint"] = "0" * 64
    monkeypatch.setattr(damage_api.bridge, "assessment_capabilities", _available)
    monkeypatch.setattr(
        damage_api, "resolve_assessment_result_source", lambda _path: source
    )
    invoked: list[object] = []
    monkeypatch.setattr(
        damage_api.bridge,
        "assess_completed_run",
        lambda **kwargs: invoked.append(kwargs),
    )

    with pytest.raises(ApiError) as stale:
        api.post(
            f"/projects/{project_id}/assess-latest-run",
            _request_payload(identity),
        )

    assert stale.value.code == "assessment_source_stale"
    assert invoked == []


def test_latest_route_returns_registered_envelope_without_absolute_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api, project_id, _identity_value = _prepared_api(tmp_path, monkeypatch)
    monkeypatch.setattr(
        damage_api.bridge,
        "latest_registered_assessment",
        lambda _project: _result(),
    )

    result = api.get(f"/projects/{project_id}/assessments/latest", {})

    assert result["assessment_id"] == "a" * 24
    assert str(tmp_path) not in json.dumps(result)


def test_dedicated_artifact_route_serves_only_registered_hash_matched_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api, project_id, _identity_value = _prepared_api(tmp_path, monkeypatch)
    project_dir = api._store._layout(project_id, create=False)
    assessment_id = "a" * 24
    relative = (
        "artifacts/damage_assessments/assessment_"
        + "c" * 32
        + "/damage_report.html"
    )
    target = project_dir.joinpath(*relative.split("/"))
    target.parent.mkdir(parents=True)
    data = b"<html>registered report</html>"
    target.write_bytes(data)
    record = {
        **_result(),
        "artifacts": {
            "damage_report.html": {
                "path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
                "media_type": "text/html; charset=utf-8",
                "size_bytes": len(data),
                "schema_version": None,
            }
        },
    }
    monkeypatch.setattr(
        damage_api.bridge,
        "registered_assessment",
        lambda _project, _assessment: record,
    )
    monkeypatch.setattr(refined_api_module, "_DEFAULT_API", api)

    with _web_server() as address:
        status, headers, body = _raw_get(
            address,
            f"/api/refined-building-blast/projects/{project_id}/assessments/"
            f"{assessment_id}/artifacts/damage_report.html",
        )

    assert status == 200
    assert headers["content-type"] == "text/html; charset=utf-8"
    assert body == data

    target.write_bytes(b"tampered")
    with pytest.raises(ApiError) as changed:
        api.assessment_artifact(
            f"/projects/{project_id}/assessments/{assessment_id}/artifacts/"
            "damage_report.html",
            {},
        )
    assert changed.value.code == "assessment_artifact_integrity_error"


def test_closed_schema_and_artifact_allowlist_reject_before_project_or_registry_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = RefinedBlastApi(tmp_path)
    payload = _request_payload({
        "scenario_id": "case-1", "generated_revision": 1,
        "artifact_fingerprint": "a" * 64, "package_fingerprint": "b" * 64,
    })
    payload["schema_version"] = "lsprepost_mcp.damage_assessment_request@2"
    with pytest.raises(ApiError) as unsupported:
        api.post("/projects/not-created/assess-latest-run", payload)
    assert unsupported.value.status == 400
    monkeypatch.setattr(
        damage_api.bridge, "registered_assessment",
        lambda *_: pytest.fail("unknown artifacts must not query the registry"),
    )
    for name in ("model.k", "../damage_report.html", "registry.json"):
        with pytest.raises(ApiError) as unknown:
            api._damage_assessment.artifact(
                project_dir=tmp_path, assessment_id="a" * 24, artifact_name=name,
            )
        assert unknown.value.status == 404
    api._store.close()
