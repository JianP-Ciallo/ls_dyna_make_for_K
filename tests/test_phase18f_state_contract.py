from __future__ import annotations

import json
import subprocess
from pathlib import Path

from lsprepost_mcp.web.refined_blast_api import RefinedBlastApi
from lsprepost_mcp.refined_building.systems import ui_sections_for_structural_system
from test_phase18e_assembler import _artifact
from node_runtime import node_executable


ROOT = Path(__file__).resolve().parents[1]
STATE_RUNTIME = ROOT / "web" / "tests" / "refined-blast-state.runtime.cjs"
WORKBENCH_RUNTIME = ROOT / "web" / "tests" / "refined-blast-workbench.runtime.cjs"


def node_runner(case: str) -> dict[str, object]:
    result = subprocess.run(
        [str(node_executable()), str(STATE_RUNTIME), case],
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def workbench_runner(case: str) -> dict[str, object]:
    result = subprocess.run(
        [str(node_executable()), str(WORKBENCH_RUNTIME), case],
        cwd=str(ROOT), text=True, encoding="utf-8", capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_provider_switch_removes_inapplicable_values() -> None:
    """A provider change must discard, rather than hide, stale provider input."""
    result = node_runner("provider-switch")

    assert result["provider_id"] == "lbe_segment"
    assert "ale_mesh_size_m" not in result["draft"]["load_provider"]
    assert "ale_mesh_size_m" not in result["draft"]["load_provider"]["provider_input"]


def test_structural_system_changes_visible_sections() -> None:
    """A system-specific section disappears when the building system changes."""
    result = node_runner("structural-system")

    assert "rebar" in result["rc_visible"]
    assert "steel_connections" not in result["rc_visible"]
    assert "steel_connections" in result["steel_visible"]
    assert "rebar" not in result["steel_visible"]


def test_semantic_edits_increment_revision_and_invalidate_derived_state() -> None:
    """Changing a draft value invalidates stale validation and preview results."""
    result = node_runner("revision-invalidation")

    assert result["revision"] == 7
    assert result["draft_revision"] == 1
    assert result["validation"] is None
    assert result["preview"] is None
    assert result["no_op_revision"] == 7


def test_save_conflict_blocks_overwrite_and_keeps_local_draft() -> None:
    """A 409 save response must retain local input and require an explicit choice."""
    result = node_runner("save-conflict")

    assert result["request"] == {
        "url": "/api/refined-building-blast/projects/project-1/save",
        "expected_revision": 5,
    }
    assert result["conflict"]["blocking"] is True
    assert result["conflict"]["status"] == 409
    assert result["draft"]["scenario_id"] == "scenario-local"


def test_stale_save_completion_cannot_overwrite_newer_local_draft() -> None:
    """An earlier save completion must not replace an edit made after its request."""
    result = node_runner("stale-save")

    assert result["revision"] == 7
    assert result["draft"]["scenario_id"] == "scenario-newer"
    assert result["conflict"] is None


def test_actual_provider_shape_prunes_nested_objects_and_array_item_values() -> None:
    """Closed provider schemas remove stale nested and array-item keys recursively."""
    result = node_runner("deep-provider-pruning")

    assert result["draft"]["load_provider"]["provider_input"] == {
        "source": {"source_id": "charge-1", "position_m": [1, 2, 3]},
        "selection": {"surface_categories": ["exterior_surfaces"]},
        "targets": [{"face_id": "face-1"}],
    }


def test_selected_asset_controls_structural_pruning_and_scenario_kind() -> None:
    """A non-first asset and its provider capability determine applicable draft data."""
    result = node_runner("selected-asset")

    assert result["asset_id"] == "subway_entrance_detailed_building"
    assert result["structural_system"] == "rc_box"
    assert "rebar" in result["draft"]["building_placement"]
    assert "steel_connections" not in result["draft"]["building_placement"]
    assert result["scenario_kind"] == "external"


def test_workbench_schema_uses_selected_nonfirst_asset_and_provider_capabilities() -> None:
    """The workbench schema must be built from the explicitly selected asset."""
    result = workbench_runner("selected-asset-schema")

    assert result["asset_ids"] == ["first", "subway_entrance_detailed_building"]
    assert result["allowed_systems"] == ["rc_box"]
    assert result["scenario_kinds"] == ["external"]
    assert result["rc_sections"] == ["rebar"]
    assert result["provider_default"] == {"source": {"seed": "one"}}


def test_authoritative_workbench_schema_routes_only_applicable_fields_to_each_step() -> None:
    """All eight panels must consume the server field map, including mesh/ground controls."""
    result = workbench_runner("eight-step-field-routing")

    assert result == {
        "schema_version": "refined_blast.workbench_schema@1",
        "step_1": ["building.asset_id"],
        "step_6": [
            "building.mesh_profile",
            "draft.load_provider.provider_input.air_cell_size_m",
        ],
        "step_7": ["draft.load_provider.provider_input.charge_position_m"],
    }


def test_defaulted_middle_steps_are_reported_configured_after_schema_load() -> None:
    """Accepted backend defaults must not leave steps 3–6 misleadingly marked pending."""
    result = workbench_runner("eight-step-default-status")

    assert result["before_validation"] == [1, 2, 3, 4, 5, 6, 7]
    assert result["after_validation"] == [1, 2, 3, 4, 5, 6, 7, 8]


def test_capability_response_from_prior_mount_cannot_mutate_current_store() -> None:
    """A late response for an unmounted root must be ignored."""
    result = workbench_runner("stale-capability-load")

    assert result["fetch_paths"] == [
        "/api/refined-building-blast/capabilities",
        "/api/refined-building-blast/capabilities",
        "/api/refined-building-blast/assets",
    ]


def test_real_selector_autosaves_once_and_unmount_cancels_pending_timer() -> None:
    result = workbench_runner("autosave-unmount")

    assert result == {"save_calls": 1, "expected_revision": 4, "after_unmount_save_calls": 1}


def test_old_mount_create_completion_cannot_capture_new_mount_session() -> None:
    result = workbench_runner("cross-mount-create")

    assert result["write_paths"] == [
        "/api/refined-building-blast/projects",
        "/api/refined-building-blast/projects/project-b/save",
    ]
    assert result["create_schema_version"] == "refined_blast_create@2"


def test_store_forwards_save_abort_signal() -> None:
    assert node_runner("save-signal") == {"forwarded": True}


def test_save_timeout_and_unmount_abort_clear_the_busy_state() -> None:
    result = workbench_runner("save-abort-lifecycle")

    assert result == {
        "timeout_aborted": True,
        "busy_after_timeout": False,
        "timeout_label_ok": True,
        "unmount_aborted": True,
    }


def test_save_button_uses_closed_project_identity_and_current_revision() -> None:
    """The mounted save control issues the namespaced save request and enters busy state."""
    result = workbench_runner("save-button")

    assert result["request"] == {
        "url": "/api/refined-building-blast/projects/project-7/save",
        "expected_revision": 4,
    }
    assert result["busy_before_response"] is True
    assert result["busy_after_response"] is False


def test_task1_capabilities_publish_closed_provider_and_workbench_schemas(tmp_path: Path) -> None:
    """The browser must receive the authoritative nested schemas, not infer them."""
    api = RefinedBlastApi(tmp_path)
    try:
        capabilities = api.get("/capabilities", {})
        assets = api.get("/assets", {})
    finally:
        api._store.close()

    provider = next(row for row in capabilities["providers"] if row["provider_id"] == "lbe_segment")
    assert provider["input_schema"]["additionalProperties"] is False
    assert provider["input_schema"]["properties"]["source"]["additionalProperties"] is False
    assert assets["assets"][0]["building_recipe_schema"]["additionalProperties"] is False
    placement = capabilities["scenario_draft_schema"]["properties"]["building_placement"]
    assert placement["oneOf"][0]["additionalProperties"] is False
    assert capabilities["default_scenario_draft"]["load_provider"]["provider_input"]


def test_asset_ui_sections_are_authoritative_structural_semantics(tmp_path: Path) -> None:
    api = RefinedBlastApi(tmp_path)
    try:
        assets = api.get("/assets", {})["assets"]
    finally:
        api._store.close()
    by_system = {
        system: sections
        for asset in assets
        for system, sections in asset["ui_sections_by_structural_system"].items()
    }
    assert by_system["rc_box"] == ["rebar"]
    assert ui_sections_for_structural_system("steel_frame") == ("steel_connections",)
    assert by_system["steel_concrete_hybrid"] == ["rebar", "steel_connections"]


def test_workbench_payload_separates_building_recipe_from_scenario_draft() -> None:
    """Structural data belongs to the building create recipe, never ScenarioDraft placement."""
    result = node_runner("closed-payloads")

    assert result["building"]["structural_system"] == "rc_box"
    assert "structural_system" not in result["scenario"]["building_placement"]
    assert "rebar" not in result["scenario"]["building_placement"]


def test_precreation_building_fields_update_recipe_and_invalidate_derived_state() -> None:
    """Mesh/ground-step building edits must reach the create recipe without compiling."""
    result = node_runner("building-field-update")

    assert result == {
        "mesh_profile": "fine",
        "draft_revision": 1,
        "validation": None,
        "preview": None,
        "payload_mesh_profile": "fine",
        "persisted_mesh_profile": "standard",
    }


def test_expected_revision_tracks_server_not_local_edit_counter() -> None:
    result = node_runner("persisted-revision")

    assert result["requests"][1]["body"]["expected_revision"] == 1
    assert result["state"]["revision"] == 2
    assert result["state"]["draft_revision"] == 2


def test_persisted_project_rejects_building_asset_and_system_mutation() -> None:
    """A scenario CAS must never impersonate a building-recipe update."""
    result = node_runner("persisted-building-immutable")

    assert result["after"]["asset_id"] == result["before"]["asset_id"] == "asset-a"
    assert result["after"]["building"] == result["before"]["building"]
    assert result["after"]["draft_revision"] == result["before"]["draft_revision"]


def test_saved_project_detaches_to_editable_copy_before_building_mutation() -> None:
    """Editing a saved building must preserve the source and mutate a new local copy."""
    assert node_runner("building-edit-copy") == {
        "source": {
            "project_id": "project-original",
            "revision": 9,
            "mesh_profile": "standard",
        },
        "detached": {
            "project_id": None,
            "revision": 1,
            "persisted_draft_revision": None,
            "compilation_state": "pending",
            "scenario_id": "scenario-1",
            "mesh_profile": "standard",
            "validation": None,
            "preview": None,
        },
        "edited": {
            "project_id": None,
            "mesh_profile": "fine",
            "draft_revision": 3,
        },
    }


def test_generation_changes_building_definition_from_pending_to_compiled() -> None:
    """A restored draft stays editable until successful K-package generation freezes it."""
    assert node_runner("building-compilation-state") == {
        "restored": "pending",
        "applied": True,
        "generated": "compiled",
    }


def test_workbench_only_locks_generated_building_definitions() -> None:
    """Saving a draft must request copy-on-edit without disabling its building controls."""
    assert workbench_runner("building-definition-policy") == {
        "uncreated": {"locked": False, "requires_copy": False},
        "saved_pending": {"locked": False, "requires_copy": True},
        "generated": {"locked": True, "requires_copy": True},
    }


def test_schema_projection_rejects_under_and_oversized_structural_arrays() -> None:
    result = node_runner("array-cardinality")

    assert result == {"rows": []}


def test_provider_switch_uses_the_provider_owned_default_input() -> None:
    result = node_runner("provider-default")

    assert result == {"provider_id": "imported_pressure_history", "provider_input": {"seed": "imported"}}


def test_schema_form_recurses_to_provider_scalar_leaves() -> None:
    paths = node_runner("rendered-provider-leaves")

    assert "load_provider.provider_input.source.position_m" in paths
    assert "load_provider.provider_input.load.peak_pressure_pa" in paths


def test_schema_form_renders_three_number_vectors_as_xyz_inputs() -> None:
    result = node_runner("rendered-position-vector")

    assert result == {
        "tag": "FIELDSET",
        "legend": "position_m",
        "inputs": [
            {"type": "number", "value": 1.25, "path": "load_provider.provider_input.source.position_m", "axis": "X", "index": 0},
            {"type": "number", "value": -2.5, "path": "load_provider.provider_input.source.position_m", "axis": "Y", "index": 1},
            {"type": "number", "value": 3.75, "path": "load_provider.provider_input.source.position_m", "axis": "Z", "index": 2},
        ],
    }


def test_schema_form_renders_five_air_margins_as_direct_numeric_inputs() -> None:
    result = node_runner("rendered-air-margins-vector")

    assert result == {
        "tag": "FIELDSET",
        "size": 5,
        "inputs": [
            {"value": 2, "axis": "X−", "index": 0},
            {"value": 4, "axis": "X+", "index": 1},
            {"value": 3, "axis": "Y−", "index": 2},
            {"value": 5, "axis": "Y+", "index": 3},
            {"value": 6, "axis": "顶部", "index": 4},
        ],
    }


def test_solver_complete_mass_and_position_stay_in_primary_workbench_fields() -> None:
    result = workbench_runner("solver-complete-primary-fields")

    assert result == {
        "tnt_mass_advanced": False,
        "charge_position_advanced": False,
        "air_cell_size_advanced": True,
        "ground_cell_size_advanced": True,
    }


def test_restored_legacy_project_preserves_provider_migration_source() -> None:
    assert node_runner("persisted-migration-source") == [
        {
            "scenario_id": "scenario-1",
            "provider_id": "solver_complete_ale_fsi",
            "source_schema_version": "phase18.solver_blast.config@3",
            "target_schema_version": "phase18.solver_blast.config@4",
        }
    ]


def test_load_step_displays_the_accepted_provider_migration() -> None:
    result = workbench_runner("provider-migration-note")

    assert result["visible"] is True
    assert result["marker"] == "true"
    assert "phase18.solver_blast.config@3" in result["text"]
    assert "phase18.solver_blast.config@4" in result["text"]


def test_schema_form_keeps_structured_arrays_in_a_structured_editor() -> None:
    result = node_runner("rendered-structured-array")

    assert result == {
        "tag": "TEXTAREA",
        "schema_type": "array",
        "value": "[[0,0],[0.1,2]]",
    }


def test_structured_schema_values_are_rejected_before_draft_mutation() -> None:
    result = node_runner("structured-schema-validation")

    assert result == {
        "valid": True,
        "wrong_root_type": False,
        "wrong_row_shape": False,
        "wrong_scalar_type": False,
    }


def test_successful_save_reconciles_server_revision_after_a_local_edit() -> None:
    state = node_runner("save-success-after-edit")

    assert state["revision"] == 2
    assert state["draft"]["scenario_kind"] == "internal"


def test_successful_generation_reconciles_exact_next_server_revision() -> None:
    """Generation advances the persisted revision and invalidates the consumed gate."""
    result = node_runner("generated-revision-reconciliation")

    assert result["wrong"] is False
    assert result["applied"] is True
    assert result["state"]["revision"] == 8
    assert result["state"]["persisted_draft_revision"] == result["state"]["draft_revision"] == 3
    assert result["state"]["validation"] is None
    assert result["state"]["generation_gate"] is None
    assert result["can_generate"] is False


def test_capability_provider_defaults_are_json_safe_and_normalizer_valid(tmp_path: Path) -> None:
    api = RefinedBlastApi(tmp_path)
    try:
        providers = api.get("/capabilities", {})["providers"]
    finally:
        api._store.close()

    for descriptor in providers:
        provider = __import__("lsprepost_mcp.refined_blast.provider_registry", fromlist=["get_load_provider"]).get_load_provider(descriptor["provider_id"])
        assert provider.normalize(descriptor["default_input"])


def test_api_accepts_capability_default_draft_then_cas_save(tmp_path: Path, monkeypatch) -> None:
    """The published seed is a valid closed create payload, not a UI-only mock."""
    artifact = _artifact()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    try:
        capabilities = api.get("/capabilities", {})
        payload = {
            "schema_version": "refined_blast_create@1",
            "building": {"asset_id": artifact.asset_id, "structural_system": "rc_box"},
            "project": {
                "schema_version": "refined_building_blast@1", "project_id": "ui-default",
                "preset_reference": "browser_draft", "preset_version": "1",
                "project_overrides": {}, "expert_extensions": {},
                "scenario_set": [capabilities["default_scenario_draft"]],
                "confirmation_records": [], "provenance": {},
                "created_at": "2026-08-11T00:00:00Z", "updated_at": "2026-08-11T00:00:00Z",
            },
        }
        created = api.post("/projects", payload)
        saved = api.post("/projects/ui-default/save", {
            "expected_revision": created["project"]["revision"],
            "draft": capabilities["default_scenario_draft"],
        })
    finally:
        api._store.close()
    assert saved["project"]["revision"] == 2


def test_each_provider_default_can_replace_a_real_task1_draft(tmp_path: Path, monkeypatch) -> None:
    artifact = _artifact()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    try:
        capabilities = api.get("/capabilities", {})
        project = {
            "schema_version": "refined_building_blast@1", "project_id": "provider-switches",
            "preset_reference": "browser_draft", "preset_version": "1", "project_overrides": {},
            "expert_extensions": {}, "scenario_set": [capabilities["default_scenario_draft"]],
            "confirmation_records": [], "provenance": {}, "created_at": "2026-08-11T00:00:00Z",
            "updated_at": "2026-08-11T00:00:00Z",
        }
        created = api.post("/projects", {"schema_version": "refined_blast_create@1", "building": {"asset_id": artifact.asset_id, "structural_system": "rc_box"}, "project": project})
        revision = created["project"]["revision"]
        for provider in capabilities["providers"]:
            draft = dict(capabilities["default_scenario_draft"])
            draft["load_provider"] = {"provider_id": provider["provider_id"], "provider_input": provider["default_input"]}
            saved = api.post("/projects/provider-switches/save", {"expected_revision": revision, "draft": draft})
            revision = saved["project"]["revision"]
    finally:
        api._store.close()
    assert revision == 1 + len(capabilities["providers"])
