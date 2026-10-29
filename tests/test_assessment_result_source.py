from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from lsprepost_mcp.assessment_result_source import (
    ASSESSMENT_RESULT_SOURCE_SCHEMA_VERSION,
    register_assessment_result_source,
    resolve_assessment_result_source,
)
from lsprepost_mcp.refined_blast.store import RefinedBlastStore

from test_phase18e_assembler import _artifact, _project


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_fixture(tmp_path: Path):
    store = RefinedBlastStore(tmp_path)
    store.create(_project(_artifact()))
    project_dir = store._layout("project-1", create=False)
    snapshot = store.materialize_action_snapshot(
        "project-1",
        "action-launch-lsdyna-2-sourcefixture",
        {
            "main.k": b"*KEYWORD\n*END\n",
            "model.k": b"*KEYWORD\n*END\n",
            "manifest.json": b'{"schema_version":"phase18.solver_blast.deck_manifest@4"}',
            "assessment_semantics.json": b'{"schema_version":"blast_damage.model_semantics@1"}',
        },
    )
    run_id = "run_20260904T000000000000Z_fixture"
    run_dir = snapshot / "solver_runs" / run_id
    run_dir.mkdir(parents=True)
    for name in ("model.k", "manifest.json", "assessment_semantics.json"):
        shutil.copy2(snapshot / name, run_dir / name)
    record = {
        "run_id": run_id,
        "status": "completed",
        "returncode": 0,
        "ok": True,
        "input_sha256": _sha(run_dir / "model.k"),
        "model_json_sha256": None,
        "evidence_manifest_sha256": None,
        "run_dir": str(tmp_path / "attacker-controlled-but-ignored"),
        "solver_evaluation": {"ok": True},
    }
    (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
    (snapshot / "solver_runs" / "latest.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    identity = {
        "scenario_id": "scenario-1",
        "generated_revision": 2,
        "artifact_fingerprint": "a" * 64,
        "package_fingerprint": "b" * 64,
    }
    return store, project_dir, snapshot, run_dir, record, identity


def test_registers_only_project_relative_terminal_solver_source(tmp_path: Path) -> None:
    store, project_dir, snapshot, run_dir, run_record, identity = _source_fixture(tmp_path)

    public = register_assessment_result_source(
        store=store,
        project_id="project-1",
        snapshot=snapshot,
        identity=identity,
        run_record=run_record,
    )

    persisted_path = project_dir / "damage_assessment_source.json"
    persisted_text = persisted_path.read_text(encoding="utf-8")
    persisted = json.loads(persisted_text)
    assert str(project_dir) not in persisted_text
    assert str(snapshot) not in persisted_text
    assert persisted["schema_version"] == ASSESSMENT_RESULT_SOURCE_SCHEMA_VERSION
    assert persisted["snapshot_relative_path"].startswith("generated/action-launch-lsdyna-")
    assert persisted["run_id"] == run_record["run_id"]
    assert persisted["run_status"] == "completed"
    assert persisted["model_sha256"] == _sha(run_dir / "model.k")
    assert persisted["manifest_sha256"] == _sha(run_dir / "manifest.json")
    assert persisted["semantics_sha256"] == _sha(run_dir / "assessment_semantics.json")
    assert public == {
        "schema_version": ASSESSMENT_RESULT_SOURCE_SCHEMA_VERSION,
        "registered": True,
        "run_id": run_record["run_id"],
        "run_status": "completed",
        **identity,
        "model_sha256": persisted["model_sha256"],
        "manifest_sha256": persisted["manifest_sha256"],
        "semantics_sha256": persisted["semantics_sha256"],
    }

    resolved = resolve_assessment_result_source(project_dir)
    assert resolved["run_dir"] == run_dir
    assert resolved["semantic_manifest"] == run_dir / "assessment_semantics.json"
    assert resolved["record"] == persisted


def test_explicit_legacy_registration_keeps_original_manifest_location(tmp_path: Path) -> None:
    store, project_dir, snapshot, run_dir, run_record, identity = _source_fixture(tmp_path)
    (snapshot / "assessment_semantics.json").unlink()
    (run_dir / "assessment_semantics.json").unlink()
    with pytest.raises((ValueError, OSError)):
        register_assessment_result_source(store=store, project_id="project-1", snapshot=snapshot, identity=identity, run_record=run_record)
    register_assessment_result_source(store=store, project_id="project-1", snapshot=snapshot, identity=identity, run_record=run_record, semantic_format="legacy_deck_manifest")
    resolved = resolve_assessment_result_source(project_dir)
    assert resolved["semantic_manifest"] == snapshot / "manifest.json"
    assert resolved["record"]["semantic_format"] == "legacy_deck_manifest"
    assert resolved["record"]["semantics_sha256"] == _sha(snapshot / "manifest.json")
    (run_dir / "manifest.json").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        resolve_assessment_result_source(project_dir)


@pytest.mark.parametrize("status", ["starting", "running", "launch_failed"])
def test_registration_rejects_nonterminal_or_unusable_run_status(
    tmp_path: Path, status: str
) -> None:
    store, _project_dir, snapshot, _run_dir, run_record, identity = _source_fixture(tmp_path)
    run_record["status"] = status

    with pytest.raises(ValueError, match="terminal"):
        register_assessment_result_source(
            store=store,
            project_id="project-1",
            snapshot=snapshot,
            identity=identity,
            run_record=run_record,
        )


def test_registration_rejects_returned_record_that_disagrees_with_persisted_run(
    tmp_path: Path,
) -> None:
    store, _project_dir, snapshot, _run_dir, run_record, identity = _source_fixture(tmp_path)
    run_record["run_id"] = "run_20260904T000000000000Z_other"

    with pytest.raises(ValueError, match="identity"):
        register_assessment_result_source(
            store=store,
            project_id="project-1",
            snapshot=snapshot,
            identity=identity,
            run_record=run_record,
        )


def test_resolution_rejects_redirected_snapshot_record(tmp_path: Path) -> None:
    store, project_dir, snapshot, _run_dir, run_record, identity = _source_fixture(tmp_path)
    register_assessment_result_source(
        store=store,
        project_id="project-1",
        snapshot=snapshot,
        identity=identity,
        run_record=run_record,
    )
    source_path = project_dir / "damage_assessment_source.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["snapshot_relative_path"] = "../outside"
    source_path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(ValueError, match="snapshot"):
        resolve_assessment_result_source(project_dir)


@pytest.mark.parametrize("changed_name", ["model.k", "manifest.json", "assessment_semantics.json"])
def test_resolution_rejects_changed_model_or_semantic_evidence(
    tmp_path: Path, changed_name: str
) -> None:
    store, project_dir, snapshot, run_dir, run_record, identity = _source_fixture(tmp_path)
    register_assessment_result_source(
        store=store,
        project_id="project-1",
        snapshot=snapshot,
        identity=identity,
        run_record=run_record,
    )
    (run_dir / changed_name).write_bytes(b"changed")

    with pytest.raises(ValueError, match="hash"):
        resolve_assessment_result_source(project_dir)


def test_resolution_rejects_latest_run_identity_change(tmp_path: Path) -> None:
    store, project_dir, snapshot, _run_dir, run_record, identity = _source_fixture(tmp_path)
    register_assessment_result_source(
        store=store,
        project_id="project-1",
        snapshot=snapshot,
        identity=identity,
        run_record=run_record,
    )
    latest_path = snapshot / "solver_runs" / "latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    latest["status"] = "running"
    latest_path.write_text(json.dumps(latest), encoding="utf-8")

    with pytest.raises(ValueError, match="identity"):
        resolve_assessment_result_source(project_dir)
