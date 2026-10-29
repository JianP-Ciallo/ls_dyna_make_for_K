from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from lsprepost_mcp.refined_blast.assembler import assemble_refined_blast_project
from lsprepost_mcp.refined_building.artifacts import MeshFragment, SolidElement
from lsprepost_mcp.refined_blast.preview import (
    PREVIEW_COUNT_METRICS,
    PREVIEW_LAYER_IDS,
    PreviewCount,
    PreviewLayer,
    RefinedBlastPreview,
)
from lsprepost_mcp.refined_blast.providers.common import fingerprint_value
from test_phase18e_assembler import (
    _artifact,
    _artifact_with_numeric_offset,
    _explicit_input,
    _project,
)
from node_runtime import node_executable


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "web" / "tests" / "refined-blast-preview.runtime.cjs"


def _web_adapter():
    from lsprepost_mcp.web.refined_blast_preview import (
        build_refined_blast_web_preview,
    )

    return build_refined_blast_web_preview


def _authoritative_preview(*, revision: int = 3, cache_key: str = "cache-one") -> RefinedBlastPreview:
    layer_rows = []
    for index, layer_id in enumerate(PREVIEW_LAYER_IDS):
        primitives = ({
            "primitive_id": f"{layer_id}:primitive",
            "kind": "mesh",
            "nodes": ((float(index), 0.0, 0.0), (float(index), 1.0, 0.0)),
            "faces": (),
            "edges": ((0, 1),),
        },)
        byte_count = len(json.dumps(primitives, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        layer_rows.append(PreviewLayer(
            layer_id,
            {
                "ordinal": index,
                "neutral_representation": {
                    "schema_version": "refined_blast.neutral_primitives@1",
                    "representation": "full_geometry",
                    "source_item_count": 1,
                    "rendered_item_count": 1,
                    "coverage": 1.0,
                    "primitive_count": 1,
                    "payload_byte_count": byte_count,
                    "fingerprint": fingerprint_value(primitives),
                },
                "neutral_primitives": primitives,
            },
            (f"source-{index}",),
        ))
    layers = tuple(layer_rows)
    counts = tuple(
        PreviewCount(metric, index + 10, "exact" if index in {0, 1, 7} else "upper_bound")
        for index, metric in enumerate(PREVIEW_COUNT_METRICS)
    )
    return RefinedBlastPreview(
        project_id="project-1",
        scenario_id="scenario-1",
        project_revision=revision,
        cache_key=cache_key,
        layers=layers,
        counts=counts,
        is_final=False,
    )


def _node(case: str) -> dict[str, object]:
    result = subprocess.run(
        [str(node_executable()), str(RUNTIME), case],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_web_adapter_preserves_closed_layer_order_and_all_count_semantics() -> None:
    """Dropping/reordering a layer or recomputing a badge must break this boundary."""
    payload = _web_adapter()(_authoritative_preview())

    assert [row["layer_id"] for row in payload["layers"]] == list(PREVIEW_LAYER_IDS)
    assert [row["metric"] for row in payload["counts"]] == list(PREVIEW_COUNT_METRICS)
    assert [row["semantics"] for row in payload["counts"]] == [
        "exact", "exact", "upper_bound", "upper_bound",
        "upper_bound", "upper_bound", "upper_bound", "exact",
    ]
    assert [row["payload"]["ordinal"] for row in payload["layers"]] == list(range(9))


def test_web_adapter_fails_closed_for_invalid_or_blocked_preview() -> None:
    """An invalid closed family must never become a renderable browser payload."""
    build = _web_adapter()
    assert build(None) is None
    wrong = build(_authoritative_preview())
    wrong["layers"] = list(reversed(wrong["layers"]))
    with pytest.raises(ValueError, match="layer order"):
        build(wrong)
    unknown = build(_authoritative_preview())
    unknown["derived_mesh"] = {"legacy": True}
    with pytest.raises(ValueError, match="unknown field"):
        build(unknown)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("is_final",), 0, "is_final"),
        (("fingerprint",), 17, "fingerprint"),
        (("cache_key",), False, "cache_key"),
        (("project_id",), [], "project_id"),
        (("scenario_id",), {}, "scenario_id"),
        (("layers", 0, "extra"), True, "unknown field"),
        (("layers", 0, "fingerprint"), 4, "fingerprint"),
        (("layers", 0, "source_fingerprints"), ["ok", 4], "source_fingerprints"),
        (("counts", 0, "extra"), True, "unknown field"),
    ],
)
def test_web_adapter_closes_nested_objects_and_identity_types(
    path: tuple[object, ...], value: object, message: str,
) -> None:
    payload = _web_adapter()(_authoritative_preview())
    target: object = payload
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(ValueError, match=message):
        _web_adapter()(payload)


def test_same_cache_key_never_reuses_an_old_response_revision() -> None:
    """A cached scene may be reused, but the response identity stays current."""
    build = _web_adapter()
    build(_authoritative_preview(revision=2, cache_key="semantic-key"))
    current = build(_authoritative_preview(revision=3, cache_key="semantic-key"))

    assert current["project_revision"] == 3


def test_phase18e_preview_payloads_expose_authoritative_neutral_primitives() -> None:
    artifact = _artifact()
    project = _project(artifact)
    package = assemble_refined_blast_project(project, artifact)
    provider_preview = {"detonation_position_m": (-1.0, 3.0, 1.5)}
    from lsprepost_mcp.refined_blast.preview import build_refined_blast_preview

    preview = build_refined_blast_preview(
        project, artifact, package,
        provider_preview=provider_preview,
        module_payloads={}, revision=1, cache_key="authoritative", is_final=False,
    )
    by_id = {layer.layer_id: layer.payload for layer in preview.layers}

    assert all("neutral_primitives" in by_id[layer_id] for layer_id in PREVIEW_LAYER_IDS)
    assert by_id["structure"]["neutral_primitives"][0]["kind"] == "mesh"
    assert by_id["structure"]["neutral_primitives"][0]["nodes"]
    assert by_id["blast_source"]["neutral_primitives"][0]["kind"] == "blast_source"


def test_preview_source_budget_fails_before_neutral_primitive_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import lsprepost_mcp.refined_blast.preview as preview_module

    artifact = _artifact()
    project = _project(artifact)
    package = assemble_refined_blast_project(project, artifact)
    materialized = False

    def forbidden(*_args, **_kwargs):
        nonlocal materialized
        materialized = True
        raise AssertionError("neutral primitives were materialized before source budget check")

    monkeypatch.setattr(preview_module, "_MAX_PREVIEW_SOURCE_ELEMENTS", 0)
    monkeypatch.setattr(preview_module, "_artifact_mesh_primitives", forbidden)
    with pytest.raises(ValueError, match="source element budget"):
        preview_module.build_refined_blast_preview(
            project, artifact, package,
            provider_preview={"detonation_position_m": (-1.0, 3.0, 1.5)},
            module_payloads={}, revision=1, cache_key="budget", is_final=False,
        )
    assert materialized is False


@pytest.mark.parametrize("family", ["artifact_nodes", "openings", "void_regions"])
def test_every_authoritative_source_family_is_budgeted_before_node_indexing(
    monkeypatch: pytest.MonkeyPatch, family: str,
) -> None:
    import lsprepost_mcp.refined_blast.preview as preview_module

    artifact = _artifact()
    package = assemble_refined_blast_project(_project(artifact), artifact)
    if family == "openings":
        artifact = replace(artifact, normalized_input={"openings": [{"bounds_m": [0, 0, 0, 1, 1, 1]}] * 4})
    elif family == "void_regions":
        artifact = replace(artifact, topology_manifest={"void_regions": [{"bounds_m": [0, 0, 0, 1, 1, 1]}] * 4})
    monkeypatch.setattr(preview_module, "_MAX_PREVIEW_SOURCE_ELEMENTS", 5 if family == "artifact_nodes" else 3)
    indexed = False
    def forbidden(*_args, **_kwargs):
        nonlocal indexed
        indexed = True
        raise AssertionError("primitive/index allocation occurred before complete source preflight")
    monkeypatch.setattr(preview_module, "_artifact_mesh_primitives", forbidden)
    monkeypatch.setattr(preview_module, "_bounds_primitives", forbidden)
    with pytest.raises(ValueError, match="source element budget"):
        preview_module.build_refined_blast_preview(
            _project(artifact), artifact, package,
            provider_preview={"detonation_position_m": (-1.0, 3.0, 1.5)},
            module_payloads={}, revision=1, cache_key="budget-family", is_final=False,
        )
    assert indexed is False


def test_legal_large_preview_uses_deterministic_deduplicated_bounded_lod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import lsprepost_mcp.refined_blast.preview as preview_module
    from lsprepost_mcp.refined_blast.providers.common import thaw_value

    base = _artifact()
    shared = base.mesh.solids[0]
    solids = (shared,) + tuple(
        SolidElement(1_000 + index, shared.node_ids, shared.part_role)
        for index in range(19)
    )
    artifact = replace(base, mesh=MeshFragment(base.mesh.nodes, solids=solids))
    project = _project(artifact)
    package = assemble_refined_blast_project(project, artifact)
    monkeypatch.setattr(preview_module, "_MAX_NEUTRAL_SOURCE_ITEMS_PER_LAYER", 3)

    def build():
        return preview_module.build_refined_blast_preview(
            project, artifact, package,
            provider_preview={"detonation_position_m": (-1.0, 3.0, 1.5)},
            module_payloads={}, revision=1, cache_key="lod", is_final=False,
        )

    first = build()
    second = build()
    assert first.fingerprint == second.fingerprint
    first_layers = {layer.layer_id: thaw_value(layer.payload) for layer in first.layers}
    second_layers = {layer.layer_id: thaw_value(layer.payload) for layer in second.layers}
    assert first_layers == second_layers

    for layer_id in PREVIEW_LAYER_IDS:
        payload = first_layers[layer_id]
        evidence = payload["neutral_representation"]
        primitives = payload["neutral_primitives"]
        assert evidence["primitive_count"] == len(primitives)
        assert evidence["primitive_count"] <= preview_module._MAX_NEUTRAL_PRIMITIVES_PER_LAYER
        assert evidence["payload_byte_count"] <= preview_module._MAX_NEUTRAL_PRIMITIVE_BYTES_PER_LAYER
        assert len(json.dumps(primitives, separators=(",", ":")).encode("utf-8")) <= preview_module._MAX_NEUTRAL_PRIMITIVE_BYTES_PER_LAYER

    structure = first_layers["structure"]
    assert structure["neutral_representation"]["representation"] == "deterministic_lod"
    assert structure["neutral_representation"]["source_item_count"] == 20
    assert structure["neutral_representation"]["rendered_item_count"] == 3
    assert structure["neutral_representation"]["coverage"] == pytest.approx(0.15)
    assert len(structure["neutral_primitives"][0]["nodes"]) == 8
    expected_counts = {row.metric: int(package.manifest["rendered_counts"][row.metric]) for row in first.counts}
    assert {row.metric: row.value for row in first.counts} == expected_counts


def test_deterministic_lod_samples_across_the_complete_source_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import lsprepost_mcp.refined_blast.preview as preview_module

    monkeypatch.setattr(preview_module, "_MAX_NEUTRAL_SOURCE_ITEMS_PER_LAYER", 3)
    assert preview_module._lod_rows(tuple(range(20))) == (0, 6, 13)
    assert preview_module._lod_positions(20) == frozenset({0, 6, 13})


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("coverage", "coverage"),
        ("representation", "representation"),
        ("byte_count", "byte_count"),
        ("primitive_fingerprint", "fingerprint"),
        ("layer_fingerprint", "layer fingerprint"),
        ("preview_fingerprint", "preview fingerprint"),
        ("source_cap", "source_item_count"),
    ],
)
def test_mapping_adapter_rejects_inconsistent_neutral_and_identity_evidence(
    mutation: str, message: str,
) -> None:
    payload = _web_adapter()(_authoritative_preview())
    evidence = payload["layers"][0]["payload"]["neutral_representation"]
    if mutation == "coverage":
        evidence["source_item_count"] = 2
        evidence["coverage"] = 1.0
    elif mutation == "representation":
        evidence["representation"] = "deterministic_lod"
    elif mutation == "byte_count":
        evidence["payload_byte_count"] = 0
    elif mutation == "primitive_fingerprint":
        payload["layers"][0]["payload"]["neutral_primitives"][0]["nodes"][0][0] = 99
    elif mutation == "layer_fingerprint":
        payload["layers"][0]["fingerprint"] = "forged-layer"
    elif mutation == "preview_fingerprint":
        payload["fingerprint"] = "forged-preview"
    elif mutation == "source_cap":
        evidence["source_item_count"] = 1_000_001

    with pytest.raises(ValueError, match=message):
        _web_adapter()(payload)


def test_phase18e_cache_key_covers_building_scenario_provider_resource_and_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every authoritative semantic dependency must invalidate the Phase 18E key."""
    import lsprepost_mcp.refined_blast.service as service_module

    artifact = _artifact()
    base = _project(artifact)
    scenario_changed = _project(
        artifact,
        output_requests={
            "schema_version": "refined_blast.output_requests@1",
            "unit_system": "SI_m_s_kg_N_Pa",
            "d3plot_interval_s": 0.002,
            "history_interval_s": 0.0002,
        },
    )
    provider_changed = _project(artifact, peak_pressure_pa=300_000.0)
    resource_input = _explicit_input()
    resource_project = _project(
        artifact,
        provider_id="explicit_ale_fsi",
        provider_input=resource_input,
    )
    resource_changed_input = json.loads(json.dumps(resource_input))
    resource_changed_input["resources"]["air_material"]["version"] = "1.0.1"
    resource_changed = _project(
        artifact,
        provider_id="explicit_ale_fsi",
        provider_input=resource_changed_input,
    )
    changed_artifact = _artifact_with_numeric_offset(100)
    building_changed = _project(changed_artifact)

    def key(project, current_artifact):
        package = assemble_refined_blast_project(project, current_artifact)
        return service_module._cache_key(project, current_artifact, package, 1)

    keys = {
        key(base, artifact),
        key(scenario_changed, artifact),
        key(provider_changed, artifact),
        key(resource_project, artifact),
        key(resource_changed, artifact),
        key(building_changed, changed_artifact),
    }
    original_adapter = service_module._ADAPTER_FINGERPRINT
    monkeypatch.setattr(service_module, "_ADAPTER_FINGERPRINT", "adapter-v-next")
    keys.add(key(base, artifact))
    monkeypatch.setattr(service_module, "_ADAPTER_FINGERPRINT", original_adapter)

    assert len(keys) == 7


def test_store_rejects_late_other_project_unmounted_and_stale_draft_responses() -> None:
    result = _node("guard-matrix")

    assert result == {
        "late_preview": "r3",
        "other_project_applied": False,
        "stale_draft_applied": False,
        "old_mount_applied": False,
        "current_mount_preview": "mount-b",
        "prior_revision_applied": False,
    }


def test_layer_visibility_is_viewer_local_and_preserves_authoritative_identity() -> None:
    result = _node("viewer-local")

    assert result["visible_layers"] == list(PREVIEW_LAYER_IDS[1:])
    assert result["draft_unchanged"] is True
    assert result["revision"] == 3
    assert result["fingerprint"] == "preview-fingerprint"
    assert result["metric_semantics"] == [
        "exact", "exact", "upper_bound", "upper_bound",
        "upper_bound", "upper_bound", "upper_bound", "exact",
    ]
    assert result["current_response_applied"] is True


def test_viewer_dispose_removes_canvas_and_listeners_and_rejects_old_updates() -> None:
    result = _node("dispose")

    assert result == {
        "children": 0,
        "listener_count": 0,
        "old_update_accepted": False,
        "webgl_destroyed": True,
    }


def test_viewer_consumes_neutral_primitives_hides_layers_and_uses_real_camera_presets() -> None:
    result = _node("viewer-primitives")

    assert result == {
        "primitive_mutations_changed_mesh": 9,
        "hidden_layer_part_count": 8,
        "visibility_preserved_camera": True,
        "camera_presets": ["iso", "front", "top"],
        "distinct_camera_presets": 3,
    }


def test_fluid_domain_is_translucent_so_structure_and_blast_source_remain_visible() -> None:
    result = _node("viewer-fluid-domain-presentation")

    assert result == {
        "structure_opacity": 1.0,
        "fluid_opacity": 0.14,
        "fluid_is_translucent": True,
    }


def test_layered_proxy_styles_distinguish_foundation_ground_air_and_grid_lines() -> None:
    result = _node("viewer-layered-proxy-styles")

    assert result["foundation_color"] != result["ground_color"]
    assert result["air_opacity"] == pytest.approx(0.14)
    assert result["ground_opacity"] < 1.0
    assert result["grid_faces_visible"] is False
    assert result["boundary_faces_visible"] is False


def test_viewer_supports_point_and_axis_drag_blast_source_editing() -> None:
    result = _node("viewer-blast-source-editor")

    assert result == {
        "point_selection_enabled_before": False,
        "point_selection_enabled_after": True,
        "point_commit": [4, 5, 6],
        "drag_preview": [6, 5, 6],
        "drag_commit": [6, 5, 6],
        "cancel_restored": [6, 5, 6],
        "commit_count_after_cancel": 2,
        "escape_restored": [6, 5, 6],
        "escape_released_capture": True,
        "keyboard_commit": [6.1, 5, 6],
        "source_marker_updates": [[1, 2, 3], [4, 5, 6], [6, 5, 6], [7, 5, 6], [6, 5, 6], [8, 5, 6], [6, 5, 6], [6.1, 5, 6]],
        "drag_controls": ["X", "Y", "Z"],
    }


def test_workbench_aborts_superseded_fetch_and_keeps_identity_guard_after_abort() -> None:
    result = _node("workbench-request")

    assert result == {
        "expected_revisions": [3, 3, 3],
        "first_aborted": True,
        "rendered_markers": ["current"],
        "post_unmount_rendered": False,
    }


def test_preview_flushes_edit_queued_behind_an_inflight_save() -> None:
    result = _node("flush-before-preview")

    assert result == {"save_calls": 2, "saved_draft_revisions": [1, 2], "pending_timers": 0}


def test_failed_save_clears_old_preview_and_never_requests_stale_persisted_revision() -> None:
    result = _node("save-failure-blocks-preview")

    assert result == {"save_calls": 1, "preview_calls": 0, "old_viewer_disposed": True}


@pytest.mark.parametrize("case", ["background-save-400", "background-save-409"])
def test_background_failed_or_conflicting_save_clears_old_preview_without_refresh(case: str) -> None:
    result = _node(case)

    assert result == {
        "save_calls": 1,
        "preview_calls": 0,
        "old_viewer_disposed": True,
        "save_status_is_failure": True,
    }


def test_refined_preview_has_no_legacy_route_state_or_cache_truth_references() -> None:
    paths = (
        ROOT / "lsprepost_mcp" / "web" / "refined_blast_preview.py",
        ROOT / "lsprepost_mcp" / "web" / "static" / "refined_blast_viewer.js",
        ROOT / "lsprepost_mcp" / "web" / "static" / "refined_blast_workbench.js",
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    for forbidden in (
        "/api/editor/",
        "/api/project/preview-mesh",
        "cityDraft",
        "previewMeshCache",
    ):
        assert forbidden not in source
