from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from lsprepost_mcp.refined_blast.store import _project_to_raw
from lsprepost_mcp.web.http_utils import ApiError
from lsprepost_mcp.web.refined_blast_api import RefinedBlastApi
import lsprepost_mcp.web.refined_blast_handoff as handoff

from test_phase18e_assembler import _artifact, _project


def _create_payload():
    artifact = _artifact()
    raw = _project_to_raw(_project(artifact))
    raw.pop("building_reference")
    raw.pop("building_artifact_fingerprint")
    return artifact, {
        "schema_version": "refined_blast_create@1",
        "project": raw,
        "building": {
            "asset_id": artifact.asset_id,
            "legacy_geometry": {},
            "mesh_profile": "standard",
            "structural_system": "rc_box",
            "generation_options": {},
            "material_overrides": {},
        },
    }


def _generated(api: RefinedBlastApi, project_id: str) -> dict[str, object]:
    validation = api.post(f"/projects/{project_id}/validate", {"expected_revision": 1})
    for finding in validation["validation"]["findings"]:
        if finding["severity"] == "warning":
            api.post(f"/projects/{project_id}/acknowledgements", {
                "expected_revision": 1,
                "validation_fingerprint": validation["validation"]["fingerprint"],
                "finding_id": finding["finding_id"],
            })
    return api.post(f"/projects/{project_id}/generate", {"expected_revision": 1})


def _identity(generated: dict[str, object]) -> dict[str, object]:
    artifact = generated["artifact"]
    return {
        "scenario_id": artifact["scenario_id"],
        "generated_revision": artifact["revision"],
        "artifact_fingerprint": artifact["fingerprint"],
        "package_fingerprint": generated["package_fingerprint"],
    }


def test_external_action_requires_current_identity_and_single_use_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]
    generated = _generated(api, project_id)
    delegated: list[Path] = []
    monkeypatch.setattr(api, "_external_action_doctor", lambda action: True)
    monkeypatch.setattr(api, "_delegate_lsprepost_snapshot", lambda model: delegated.append(model) or {"started": True})

    confirmation = api.post(f"/projects/{project_id}/action-confirmations", {
        "action": "open_lsprepost", **_identity(generated),
    })
    assert confirmation["confirmation"]["project_id"] == project_id
    result = api.post(f"/projects/{project_id}/open-lsprepost", {
        "confirmation_nonce": confirmation["confirmation"]["nonce"], **_identity(generated),
    })

    assert result["external_program_started"] is True
    assert len(delegated) == 1
    assert delegated[0].name == "main.k"
    assert "workspace" in delegated[0].parts and "projects" not in delegated[0].parts
    with pytest.raises(ApiError) as reused:
        api.post(f"/projects/{project_id}/open-lsprepost", {
            "confirmation_nonce": confirmation["confirmation"]["nonce"], **_identity(generated),
        })
    assert reused.value.code == "confirmation_invalid"


def test_external_action_rejects_browser_process_controls_and_stale_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]
    generated = _generated(api, project_id)
    with pytest.raises(ApiError) as unknown:
        api.post(f"/projects/{project_id}/action-confirmations", {
            "action": "open_lsprepost", "exe": "bad.exe", **_identity(generated),
        })
    assert unknown.value.code == "unknown_field"
    stale = _identity(generated)
    stale["package_fingerprint"] = "0" * 64
    with pytest.raises(ApiError) as rejected:
        api.post(f"/projects/{project_id}/action-confirmations", {"action": "open_lsprepost", **stale})
    assert rejected.value.code in {"artifact_stale", "artifact_integrity_error", "not_found"}


@pytest.mark.parametrize("run_status", [None, "completed", "solver_failed", "timed_out"])
def test_external_action_preflights_doctor_then_delegates_exactly_once_with_only_trusted_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, run_status: str | None,
) -> None:
    """Removing the doctor gate or passing browser process options must fail this contract."""

    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]
    generated = _generated(api, project_id)
    observed: list[tuple[Path, Path]] = []
    delegated: dict[str, object] = {"started": True}
    if run_status is not None:
        delegated["record"] = {"status": run_status}
    monkeypatch.setattr(api, "_external_action_doctor", lambda action: True)
    monkeypatch.setattr(
        api,
        "_delegate_lsdyna_snapshot",
        lambda snapshot, main: observed.append((snapshot, main)) or delegated,
    )

    confirmation = api.post(f"/projects/{project_id}/action-confirmations", {
        "action": "launch_lsdyna", **_identity(generated),
    })
    result = api.post(f"/projects/{project_id}/launch-lsdyna", {
        "confirmation_nonce": confirmation["confirmation"]["nonce"], **_identity(generated),
    })

    assert result["external_program_started"] is True
    assert "snapshot" not in result
    assert result["action"] == "launch_lsdyna"
    assert {key: result[key] for key in _identity(generated)} == _identity(generated)
    assert len(observed) == 1
    snapshot, main = observed[0]
    assert main == snapshot / "main.k"
    assert snapshot.parent.name == "generated"
    assert (snapshot / "action.json").is_file()
    assert result["solver_ready"] is False
    assert result["requires_project_review"] is True
    assert not (snapshot / "assessment_semantics.json").exists()
    assert "damage_assessment_source" not in result


def test_terminal_lsdyna_action_registers_project_owned_assessment_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr(
        "lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact
    )
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]
    generated = _generated(api, project_id)
    identity = _identity(generated)
    package = __import__(
        "lsprepost_mcp.refined_blast.assembler", fromlist=["RefinedBlastPackage"]
    ).RefinedBlastPackage(
        files={
            "model.k": b"*KEYWORD\n*END\n",
            "manifest.json": b'{"schema_version":"phase18.solver_blast.deck_manifest@4"}',
            "assessment_semantics.json": b'{"schema_version":"blast_damage.model_semantics@1"}',
        },
        manifest={"schema_version": "phase18.solver_blast.web_package_manifest@1"},
        symbol_to_numeric_id={},
        building_artifact_fingerprint=artifact.fingerprint,
    )
    monkeypatch.setattr(
        api,
        "_current_generated_package",
        lambda _project_id, _stored, _payload: (identity, package),
    )
    monkeypatch.setattr(api, "_external_action_doctor", lambda _action: True)

    def completed_run(snapshot: Path, main: Path):
        assert main == snapshot / "main.k"
        assert (snapshot / "manifest.json").is_file()
        assert (snapshot / "assessment_semantics.json").is_file()
        run_id = "run_20260904T000000000000Z_websource"
        runs = snapshot / "solver_runs"
        run_dir = runs / run_id
        run_dir.mkdir(parents=True)
        for name in ("model.k", "manifest.json", "assessment_semantics.json"):
            shutil.copy2(snapshot / name, run_dir / name)
        digest = hashlib.sha256((run_dir / "model.k").read_bytes()).hexdigest()
        record = {
            "run_id": run_id,
            "status": "completed",
            "returncode": 0,
            "ok": True,
            "input_sha256": digest,
            "model_json_sha256": None,
            "evidence_manifest_sha256": None,
            "solver_evaluation": {"ok": True},
            "run_dir": str(tmp_path / "must-not-be-trusted"),
        }
        (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
        (runs / "latest.json").write_text(json.dumps(record), encoding="utf-8")
        return {"started": True, "record": record}

    monkeypatch.setattr(api, "_delegate_lsdyna_snapshot", completed_run)
    confirmation = api.post(
        f"/projects/{project_id}/action-confirmations",
        {"action": "launch_lsdyna", **identity},
    )
    result = api.post(
        f"/projects/{project_id}/launch-lsdyna",
        {
            "confirmation_nonce": confirmation["confirmation"]["nonce"],
            **identity,
        },
    )

    source = result["damage_assessment_source"]
    assert source["registered"] is True
    assert source["run_status"] == "completed"
    assert source["package_fingerprint"] == identity["package_fingerprint"]
    assert str(tmp_path) not in json.dumps(result)
    project_dir = api._store._layout(project_id, create=False)
    assert (project_dir / "damage_assessment_source.json").is_file()


def test_lsdyna_handoff_passes_complete_snapshot_closure_to_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "main.k").write_text("*KEYWORD\n*INCLUDE\npart.k\n*END\n", encoding="utf-8")
    (snapshot / "model.k").write_text("*KEYWORD\n*INCLUDE\npart.k\n*END\n", encoding="utf-8")
    (snapshot / "part.k").write_text("*KEYWORD\n*PART\n*END\n", encoding="utf-8")
    (snapshot / "manifest.json").write_text("{}", encoding="utf-8")
    (snapshot / "assessment_semantics.json").write_text("{}", encoding="utf-8")
    solver = tmp_path / "lsdyna.exe"
    solver.write_bytes(b"fake")
    monkeypatch.setattr(handoff, "configured_lsdyna_exe", lambda: solver)
    monkeypatch.setattr(handoff, "doctor_named_exe", lambda *_args, **_kwargs: type("Doctor", (), {"ok": True})())
    observed: dict[str, object] = {}
    monkeypatch.setattr(handoff, "execute_lsdyna_run", lambda *_args, **kwargs: observed.update(kwargs) or {"status": "completed"})

    result = handoff.launch_lsdyna_snapshot(snapshot, snapshot / "main.k")

    assert result["started"] is True
    assert set(observed["input_closure"]) >= {"model.k", "main.k", "part.k"}
    assert "manifest.json" in observed["input_closure"]
    assert "assessment_semantics.json" in observed["input_closure"]


def test_action_snapshot_is_rehashed_immediately_before_delegation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]
    generated = _generated(api, project_id)
    monkeypatch.setattr(api, "_external_action_doctor", lambda _action: True)
    delegated: list[Path] = []
    monkeypatch.setattr(
        api,
        "_delegate_lsprepost_snapshot",
        lambda model: delegated.append(model) or {"started": True},
    )
    original_verify = api._store.verify_action_snapshot

    def tamper_before_verify(project: str, snapshot: Path, digests):
        (snapshot / "main.k").write_bytes(b"tampered")
        return original_verify(project, snapshot, digests)

    monkeypatch.setattr(api._store, "verify_action_snapshot", tamper_before_verify)
    confirmation = api.post(f"/projects/{project_id}/action-confirmations", {
        "action": "open_lsprepost", **_identity(generated),
    })

    with pytest.raises(ApiError) as rejected:
        api.post(f"/projects/{project_id}/open-lsprepost", {
            "confirmation_nonce": confirmation["confirmation"]["nonce"],
            **_identity(generated),
        })

    assert rejected.value.code == "artifact_integrity_error"
    assert delegated == []


def test_store_action_snapshot_rejects_escaping_resource_paths(tmp_path: Path) -> None:
    store = __import__(
        "lsprepost_mcp.refined_blast.store", fromlist=["RefinedBlastStore"]
    ).RefinedBlastStore(tmp_path)
    store._layout("project-1", create=True)

    with pytest.raises(ValueError, match="safe identifier"):
        store.materialize_action_snapshot(
            "project-1", "action-open-1-deadbeef", {"../outside.k": b"*END\n"}
        )


def test_external_action_unconfigured_or_failed_delegate_consumes_confirmation_and_never_claims_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing preflight or delegate truthfulness must fail closed at the route boundary."""

    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]
    generated = _generated(api, project_id)
    monkeypatch.setattr(api, "_external_action_doctor", lambda action: False)
    descriptor = api.post(f"/projects/{project_id}/action-confirmations", {
        "action": "open_lsprepost", **_identity(generated),
    })
    with pytest.raises(ApiError) as unconfigured:
        api.post(f"/projects/{project_id}/open-lsprepost", {
            "confirmation_nonce": descriptor["confirmation"]["nonce"], **_identity(generated),
        })
    assert unconfigured.value.code == "external_program_unavailable"

    monkeypatch.setattr(api, "_external_action_doctor", lambda action: True)
    monkeypatch.setattr(api, "_delegate_lsprepost_snapshot", lambda model: {"started": False})
    descriptor = api.post(f"/projects/{project_id}/action-confirmations", {
        "action": "open_lsprepost", **_identity(generated),
    })
    result = api.post(f"/projects/{project_id}/open-lsprepost", {
        "confirmation_nonce": descriptor["confirmation"]["nonce"], **_identity(generated),
    })
    assert result["external_program_started"] is False
    with pytest.raises(ApiError) as replay:
        api.post(f"/projects/{project_id}/open-lsprepost", {
            "confirmation_nonce": descriptor["confirmation"]["nonce"], **_identity(generated),
        })
    assert replay.value.code == "confirmation_invalid"


def test_lsprepost_path_delegate_reports_the_reviewed_launcher_start_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing the neutral launch mode or discarding its start evidence must fail."""

    model = tmp_path / "main.k"
    model.write_text("*KEYWORD\n*END\n", encoding="utf-8")
    executable = tmp_path / "lsprepost.exe"
    executable.write_bytes(b"not launched")
    monkeypatch.setattr(handoff, "configured_lspp_exe", lambda: (executable, "test", True))
    monkeypatch.setattr(handoff, "doctor_lsprepost_exe", lambda _: type("Doctor", (), {"ok": True})())
    calls: list[tuple[Path, list[str], str]] = []
    monkeypatch.setattr(
        handoff,
        "launch_lsprepost_command",
        lambda parent, command, mode, **_: calls.append((parent, command, mode)) or {"status": "started"},
    )

    result = handoff.open_lsprepost_snapshot(model)

    assert result["started"] is True
    assert calls == [(model.parent, [str(executable), f"k={model.resolve()}"], "keyword_preview")]
