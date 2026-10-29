from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import threading
from time import monotonic
from types import SimpleNamespace

import pytest

from lsprepost_mcp.web.http_utils import ApiError
from lsprepost_mcp.web.app import create_server
from lsprepost_mcp.web.refined_blast_api import RefinedBlastApi
from lsprepost_mcp.refined_building.asset_compiler import compile_detailed_building_asset
import lsprepost_mcp.web.refined_blast_api as refined_api_module
from test_phase18e_assembler import _artifact
from node_runtime import node_executable


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH = ROOT / "lsprepost_mcp" / "web" / "static" / "refined_blast_workbench.js"
APP = ROOT / "lsprepost_mcp" / "web" / "static" / "app.js"
REAL_HTTP_RUNTIME = ROOT / "web" / "tests" / "refined-blast-real-http.runtime.cjs"


def test_public_provider_workflow_is_explicitly_marked_heavy() -> None:
    marks = getattr(test_public_refined_workbench_workflow_covers_each_provider, "pytestmark", [])
    assert any(mark.name == "heavy_provider_e2e" for mark in marks)


def test_production_browser_workflow_uses_real_http_and_keeps_project_assets_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Removing HTTP routing, URL restore, CAS, or project-bound artifacts fails this test."""
    base_artifact = _artifact()

    def compile_small_audited_artifact(recipe):
        return replace(
            base_artifact,
            asset_id=recipe["asset_id"],
            system_id=recipe.get("structural_system") or base_artifact.system_id,
        )

    launches: list[str] = []

    def forbidden_external_delegate(*_args, **_kwargs):
        launches.append("forbidden")
        raise AssertionError("real HTTP browser workflow must not delegate an external launch")

    api = RefinedBlastApi(tmp_path)
    monkeypatch.setattr(refined_api_module, "_compile_building", compile_small_audited_artifact)
    monkeypatch.setattr(
        refined_api_module,
        "_compile_building_package",
        lambda recipe: SimpleNamespace(
            artifacts=(compile_small_audited_artifact(recipe),),
            package_fingerprint="e" * 64,
        ),
    )
    monkeypatch.setattr(refined_api_module, "_DEFAULT_API", api)
    monkeypatch.setattr(api, "_delegate_lsprepost_snapshot", forbidden_external_delegate)
    monkeypatch.setattr(api, "_delegate_lsdyna_snapshot", forbidden_external_delegate)

    server = create_server("127.0.0.1", 0, open_browser=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://{server.server_address[0]}:{server.server_address[1]}"
        completed = subprocess.run(
            [str(node_executable()), "--experimental-vm-modules", str(REAL_HTTP_RUNTIME), base_url],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=120,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    evidence = json.loads(completed.stdout)
    assert evidence["transport"] == "real-global-fetch"
    assert evidence["browser_flow"] == [
        "legacy-entry", "capabilities", "assets", "create", "save", "preview",
        "validate", "acknowledge", "generate", "artifact-read", "reload-get",
        "back-unmount", "forward-remount",
    ]
    assert evidence["project_a"]["project_id"] != evidence["project_b"]["project_id"]
    assert evidence["project_a"]["asset_id"] != evidence["project_b"]["asset_id"]
    assert evidence["artifact_read"]["project_id"] == evidence["project_a"]["project_id"]
    assert evidence["artifact_read"]["scenario_id"] == evidence["project_a"]["scenario_id"]
    assert evidence["artifact_read"]["external_program_started"] is False
    assert evidence["generation_ui"] == {
        "state_revision": evidence["artifact_read"]["revision"],
        "artifact_revision": evidence["artifact_read"]["revision"],
        "validation_invalidated": True,
        "open_enabled": True,
        "solve_enabled": True,
    }
    assert evidence["url_isolation"]["project_id"] == evidence["project_b"]["project_id"]
    assert evidence["url_isolation"]["asset_id"] == evidence["project_b"]["asset_id"]
    assert evidence["url_isolation"]["returned_project_id"] == evidence["project_a"]["project_id"]
    assert evidence["url_isolation"]["delayed_a_cannot_replace_b"] is True
    assert evidence["reload"]["project_id"] == evidence["project_a"]["project_id"]
    assert evidence["reload"]["scenario_id"] == evidence["project_a"]["scenario_id"]
    assert evidence["reload"]["asset_id"] == evidence["project_a"]["asset_id"]
    assert evidence["reload"]["structural_system"] == evidence["reload"]["expected_structural_system"]
    assert evidence["stale_save"]["status"] == 409
    assert evidence["stale_save"]["local_scenario_id"] == evidence["project_a"]["scenario_id"]
    assert evidence["stale_save"]["local_provider_id"] == "imported_pressure_history"
    assert evidence["lifecycle"]["viewer_dispose_count"] == 1
    assert evidence["cross_project_get"]["status"] in {400, 404, 409}
    assert evidence["cross_project_generate"]["status"] in {404, 409}
    assert evidence["cross_project_artifact"]["status"] in {404, 409}
    assert evidence["external_action_requests"] == []
    assert launches == []


SMALL_GEOMETRIES = {
    "commercial_supermarket_detailed_building": {
        "length_m": 6.0, "width_m": 6.0, "height_m": 3.0,
        "wall_thickness_m": 0.25, "entrance_width_m": 2.0, "entrance_height_m": 2.0,
    },
    "residential_community_detailed_building": {
        "tower_count": 1, "tower_length_m": 3.6, "tower_width_m": 3.6,
        "tower_height_m": 3.0, "tower_spacing_m": 2.0, "wall_thickness_m": 0.2,
        "balcony_depth_m": 0.5,
    },
    # This is the approved Phase 18D subway recipe, intentionally unmodified.
    "subway_entrance_detailed_building": {},
}


def _real_create_payload(api: RefinedBlastApi, *, project_id: str, provider_id: str, asset_id: str) -> dict[str, object]:
    """Build a public create request from the live capability and asset contracts."""
    capabilities = api.get("/capabilities", {})
    assets = {row["asset_id"]: row for row in api.get("/assets", {})["assets"]}
    provider = next(row for row in capabilities["providers"] if row["provider_id"] == provider_id)
    asset = assets[asset_id]
    draft = deepcopy(capabilities["default_scenario_draft"])
    draft["scenario_id"] = f"{project_id}-scenario"
    draft["load_provider"] = {
        "provider_id": provider_id,
        "provider_input": deepcopy(provider["default_input"]),
    }
    provider_input = draft["load_provider"]["provider_input"]
    if provider_id == "explicit_ale_fsi":
        provider_input["budgets"].update({"max_axis_points": 20, "max_node_count": 1_000, "max_element_count": 1_000})
    elif provider_id == "lbe_segment":
        # The approved Phase 18D subway path uses this real public source and
        # bounded allocation envelope; 10,000 surfaces rejects its 10,571-face
        # catalog before the workflow can reach acknowledgement/generation.
        provider_input["source"]["position_m"] = [-2.0, 1.5, 1.5]
        provider_input["budgets"].update({"max_surface_count": 100_000, "max_total_area_m2": 1_000_000.0})
    else:
        provider_input["budgets"].update({"max_input_bytes": 4_096, "max_row_count": 100, "max_target_surface_count": 1_000})
        compiled = compile_detailed_building_asset(
            asset_id,
            legacy_geometry=SMALL_GEOMETRIES[asset_id],
            structural_system=asset["default_structural_system"],
            fidelity_profile="structural_core",
            mesh_profile="coarse",
            generation_options={},
            material_overrides={},
        )
        provider_input["mapping"]["target_face_ids"] = [
            compiled.artifacts[0].surface_catalog["exterior_surfaces"][0]["face_id"]
        ]
    return {
        "schema_version": "refined_blast_create@1",
        "building": {
            "asset_id": asset_id,
            "legacy_geometry": SMALL_GEOMETRIES[asset_id],
            "structural_system": asset["default_structural_system"],
            "fidelity_profile": "structural_core",
            "mesh_profile": "coarse",
            "generation_options": {},
            "material_overrides": {},
        },
        "project": {
            "schema_version": "refined_building_blast@1",
            "project_id": project_id,
            "preset_reference": "browser_draft",
            "preset_version": "1",
            "project_overrides": {},
            "expert_extensions": {},
            "scenario_set": [draft],
            "confirmation_records": [],
            "provenance": {},
            "created_at": "2026-08-15T00:00:00Z",
            "updated_at": "2026-08-15T00:00:00Z",
        },
    }


def _acknowledge_current_warnings(api: RefinedBlastApi, project_id: str, validation: dict[str, object]) -> None:
    for finding in validation["findings"]:
        if finding["severity"] == "warning":
            api.post(
                f"/projects/{project_id}/acknowledgements",
                {
                    "expected_revision": validation["project_revision"],
                    "validation_fingerprint": validation["fingerprint"],
                    "finding_id": finding["finding_id"],
                },
            )


def _timed(name: str, operation):
    started = monotonic()
    result = operation()
    elapsed = monotonic() - started
    print(f"[task7 timing] {name}={elapsed:.3f}s")
    return result


def test_timing_observability_records_slow_duration_without_making_it_a_correctness_gate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A slow shared host remains observable without failing a functional workflow."""
    ticks = iter((10.0, 140.5))
    monkeypatch.setattr(sys.modules[__name__], "monotonic", lambda: next(ticks))

    result = _timed("controlled-operation", lambda: {"status": "ok"})

    assert result == {"status": "ok"}
    assert "[task7 timing] controlled-operation=130.500s" in capsys.readouterr().out


@pytest.mark.heavy_provider_e2e
@pytest.mark.parametrize(
    ("provider_id", "asset_id"),
    (
        ("explicit_ale_fsi", "commercial_supermarket_detailed_building"),
        ("lbe_segment", "subway_entrance_detailed_building"),
        ("imported_pressure_history", "residential_community_detailed_building"),
    ),
)
def test_public_refined_workbench_workflow_covers_each_provider(tmp_path: Path, provider_id: str, asset_id: str) -> None:
    """A missing refined route, CAS guard, acknowledgement gate, or artifact isolation fails here."""
    api = RefinedBlastApi(tmp_path)
    project_id = f"public-workbench-{provider_id}"
    created = _timed("create", lambda: api.post("/projects", _real_create_payload(api, project_id=project_id, provider_id=provider_id, asset_id=asset_id)))["project"]
    # The public project references the compiled BuildingArtifact, whose identity
    # can intentionally differ from the selected resource (e.g. residential's
    # first tower is ``tower_001``).  Successful create/reload/generate below
    # exercises the server-verified selected resource recipe without assuming
    # that those two identity layers share a string value.
    assert created["project"]["building_reference"]["asset_id"]
    assert created["project"]["scenario_set"][0]["load_provider"]["provider_id"] == provider_id
    draft = deepcopy(created["project"]["scenario_set"][0])
    saved = _timed("save", lambda: api.post(f"/projects/{project_id}/save", {"expected_revision": 1, "draft": draft}))["project"]
    assert saved["revision"] == 2
    with pytest.raises(ApiError, match="revision") as stale:
        api.post(f"/projects/{project_id}/save", {"expected_revision": 1, "draft": draft})
    assert stale.value.status == 409
    preview = _timed("preview", lambda: api.post(f"/projects/{project_id}/preview", {"expected_revision": 2}))["preview"]
    assert preview["project_id"] == project_id
    validation = _timed("validate", lambda: api.post(f"/projects/{project_id}/validate", {"expected_revision": 2}))["validation"]
    assert validation["generation_gate"]["allowed"] is False
    _timed("acknowledge", lambda: _acknowledge_current_warnings(api, project_id, validation))
    generated = _timed("generate", lambda: api.post(f"/projects/{project_id}/generate", {"expected_revision": 2}))
    assert generated["external_program_started"] is False
    assert generated["solver_ready"] is False
    assert generated["requires_project_review"] is True
    reloaded = RefinedBlastApi(tmp_path)
    loaded = reloaded.get(f"/projects/{project_id}", {})["project"]
    assert loaded["revision"] == saved["revision"] + 1
    artifact = generated["artifact"]
    package = _timed("artifact-read", lambda: reloaded.get(f"/projects/{project_id}/artifacts/{artifact['scenario_id']}/{artifact['revision']}/{generated['package_fingerprint']}", {}))
    assert package["artifact"]["project_id"] == project_id
    assert package["package"]["external_program_started"] is False


def test_refined_route_shell_has_unique_labeled_keyboard_controls_and_no_legacy_dependencies() -> None:
    """A removed label/id, enabled unsafe action, or legacy dependency fails the static safety boundary."""
    workbench = WORKBENCH.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    assert 'id="refinedBlastBack"' in workbench
    assert 'aria-label="返回原工作台"' in workbench
    assert 'id="refinedBlastLayer-${layer.id}"' in workbench
    assert 'for="refinedBlastLayer-${layer.id}"' in workbench
    assert 'aria-live="assertive"' in workbench
    assert 'id="refinedBlastConflict"' in workbench
    assert "shell.tabIndex = -1" in workbench and "shell.focus?.()" in workbench
    assert 'data-refined-generate disabled' in workbench
    assert 'data-refined-open-lsprepost disabled' in workbench
    assert 'data-refined-launch-lsdyna disabled' in workbench
    assert "/api/editor/" not in workbench
    assert "cityDraft" not in workbench
    assert '"/refined-building-blast"' in app
    assert '"/refined-building-blast/"' in app
