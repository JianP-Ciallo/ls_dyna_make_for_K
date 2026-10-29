from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from lsprepost_mcp.web.http_utils import ApiError
from lsprepost_mcp.web.refined_blast_api import RefinedBlastApi
from test_phase18f_api import _create_payload
from node_runtime import node_executable


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "web" / "tests" / "refined-blast-validation.runtime.cjs"


def _node(case: str) -> dict[str, object]:
    result = subprocess.run(
        [str(node_executable()), str(RUNTIME), case],
        cwd=str(ROOT), text=True, encoding="utf-8", capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_generation_gate_is_server_bound_and_fail_closed_for_every_identity_change() -> None:
    result = _node("gate-matrix")

    assert result == {
        "with_error": False,
        "unacknowledged_warning": False,
        "acknowledged_current_warning": True,
        "changed_warning_hash": False,
        "changed_validation_fingerprint": False,
        "stale_revision": False,
        "local_unsaved_edit": False,
        "backend_gate_denied": False,
        "info_only": True,
    }


def test_late_other_project_dirty_unmounted_and_conflict_responses_are_rejected() -> None:
    result = _node("identity-matrix")

    assert result == {
        "current_applied": True,
        "late_applied": False,
        "current_fingerprint": "current",
        "other_project_applied": False,
        "edit_response_applied": False,
        "late_ack_applied": False,
        "unmounted_applied": False,
        "conflict_applied": True,
        "conflict_blocking": True,
        "generate_after_conflict": False,
        "validation_cleared_on_save": True,
        "late_ack_after_save": False,
        "saved_revision": 4,
    }


def test_budget_rows_preserve_task4_authoritative_exact_and_upper_semantics() -> None:
    result = _node("budget-rows")

    assert result["rows"] == [
        {"metric": "building_nodes", "value": 140, "semantics": "exact"},
        {"metric": "provider_elements", "value": 900, "semantics": "upper_bound"},
    ]
    assert result["preview_unchanged"] is True
    assert result["exact_label"] == "exact"
    assert result["upper_label"] == "upper_bound"


def test_workbench_uses_exact_validate_and_ack_payloads_and_renders_all_finding_fields() -> None:
    result = _node("workbench-requests")

    assert result["validated"] is True
    assert result["acknowledged"] is True
    assert result["requests"] == [
        {
            "url": "/api/refined-building-blast/projects/project-1/validate",
            "body": {"expected_revision": 3},
            "method": "POST",
        },
        {
            "url": "/api/refined-building-blast/projects/project-1/acknowledgements",
            "body": {
                "expected_revision": 3,
                "validation_fingerprint": "validation-3",
                "finding_id": "warning-1",
            },
            "method": "POST",
        },
    ]
    assert result["rendered"] == {
        "severity": "warning",
        "text": (
            "warning | load_provider | "
            "scenario_set.scenario-1.load_provider.provider_input | "
            "warning-1 message | warning-1 correction | warning-1 | hash-warning-1"
        ),
        "id": "warning-1",
        "hash": "hash-warning-1",
    }
    assert result["enabled_after_ack"] is True
    assert result["acknowledgement_button_disabled"] is True


def test_acknowledgement_409_is_a_blocking_conflict() -> None:
    result = _node("workbench-conflict")

    assert result["applied"] is False
    assert result["blocking"] is True
    assert result["validation_cleared"] is True
    assert result["requests"][0]["body"] == {
        "expected_revision": 3,
        "validation_fingerprint": "validation-3",
        "finding_id": "warning-1",
    }
    assert "409" in result["message"]


def test_preview_409_invalidates_the_current_generation_gate() -> None:
    result = _node("workbench-preview-conflict")

    assert result == {
        "applied": False,
        "blocking": True,
        "validation_cleared": True,
        "generate_enabled": False,
        "request": {
            "url": "/api/refined-building-blast/projects/project-1/preview",
            "body": {"expected_revision": 3},
            "method": "POST",
        },
    }


def test_api_publishes_authoritative_gate_before_and_after_warning_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    try:
        project_id = api.post("/projects", payload)["project"]["project_id"]
        validation = api.post(f"/projects/{project_id}/validate", {"expected_revision": 1})["validation"]
        warnings = [row for row in validation["findings"] if row["severity"] == "warning"]

        assert warnings
        assert validation["generation_gate"] == {
            "allowed": False,
            "project_id": project_id,
            "project_revision": 1,
            "validation_fingerprint": validation["fingerprint"],
            "blocking_error_ids": [],
            "unacknowledged_warning_ids": [row["finding_id"] for row in warnings],
        }
        last = None
        for warning in warnings:
            last = api.post(
                f"/projects/{project_id}/acknowledgements",
                {
                    "expected_revision": 1,
                    "validation_fingerprint": validation["fingerprint"],
                    "finding_id": warning["finding_id"],
                },
            )
        assert last is not None
        assert last["generation_gate"]["allowed"] is True
        assert last["generation_gate"]["unacknowledged_warning_ids"] == []
    finally:
        api._store.close()


@pytest.mark.parametrize(
    ("route", "payload"),
    [
        ("validate", {"expected_revision": 1, "finding_id": "unexpected"}),
        (
            "acknowledgements",
            {
                "expected_revision": 1,
                "validation_fingerprint": "fingerprint",
                "finding_id": "warning",
                "content_hash": "client-must-not-send-this",
            },
        ),
    ],
)
def test_validation_mutations_reject_non_contract_request_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route: str, payload: dict[str, object],
) -> None:
    artifact, create = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    try:
        project_id = api.post("/projects", create)["project"]["project_id"]
        with pytest.raises(ApiError) as raised:
            api.post(f"/projects/{project_id}/{route}", payload)
        assert raised.value.status == 400
        assert raised.value.code == "unknown_field"
    finally:
        api._store.close()
