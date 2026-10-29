from __future__ import annotations

import sys
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from test_phase18e_assembler import _artifact, _lbe_input, _project

from lsprepost_mcp.refined_blast.preview import PREVIEW_LAYER_IDS
from lsprepost_mcp.refined_blast.assembler import RefinedBlastPackage
from lsprepost_mcp.refined_blast.providers.common import surface_geometry_from_artifact
from lsprepost_mcp.refined_blast.service import RefinedBlastService, validate_public_package
from lsprepost_mcp.refined_blast.store import DraftConflictError, RefinedBlastStore
from lsprepost_mcp.refined_building.compiler import compile_refined_building
from lsprepost_mcp.refined_building.asset_compiler import compile_detailed_building_asset
from lsprepost_mcp.refined_building.contracts import default_building_definition


def test_validation_preview_acknowledgement_and_revision_are_one_closed_gate(tmp_path):
    artifact = _artifact()
    project = _project(artifact)
    with RefinedBlastStore(tmp_path) as store:
        stored = store.create(project)
        service = RefinedBlastService(store, stored.project_id, artifact)

        validation = service.validate(expected_revision=1)
        assert not validation.errors
        assert len(validation.warnings) == 1
        warning = validation.warnings[0]
        assert warning.module == "project_review"

        draft_preview = service.preview(expected_revision=1)
        assert draft_preview.is_final is False
        assert tuple(layer.layer_id for layer in draft_preview.layers) == PREVIEW_LAYER_IDS
        assert {row.semantics for row in draft_preview.counts} == {"exact", "upper_bound"}
        blast_layer = next(row for row in draft_preview.layers if row.layer_id == "blast_source")
        assert blast_layer.payload["provider_preview"]["selected_face_ids"] == (
            "solid:1:face:x_max",
        )

        acknowledgement = service.acknowledge(validation, warning.finding_id)
        final_preview = service.preview(expected_revision=1)
        assert final_preview.is_final is True
        assert acknowledgement.finding_content_hash == warning.content_hash
        assert acknowledgement.project_revision == 1

        generated = service.generate(expected_revision=1)
        assert generated.manifest["solver_ready"] is False
        assert generated.manifest["external_program_started"] is False
        assert final_preview.compare_generated(generated) == ()

        forged_manifest = dict(generated.manifest)
        forged_counts = dict(forged_manifest["rendered_counts"])
        forged_counts["unknown_metric"] = 0
        forged_manifest["rendered_counts"] = forged_counts
        forged = RefinedBlastPackage(
            files=generated.files,
            manifest=forged_manifest,
            symbol_to_numeric_id=generated.symbol_to_numeric_id,
            building_artifact_fingerprint=generated.building_artifact_fingerprint,
        )
        assert "unknown generated count" in final_preview.compare_generated(forged)[0]

        negative_manifest = dict(generated.manifest)
        negative_counts = dict(negative_manifest["rendered_counts"])
        negative_counts["provider_fsi_faces"] = -1
        negative_manifest["rendered_counts"] = negative_counts
        negative = RefinedBlastPackage(
            files=generated.files,
            manifest=negative_manifest,
            symbol_to_numeric_id=generated.symbol_to_numeric_id,
            building_artifact_fingerprint=generated.building_artifact_fingerprint,
        )
        assert "invalid generated count" in final_preview.compare_generated(negative)[0]

        with pytest.raises(DraftConflictError, match="expected revision 2"):
            service.generate(expected_revision=2)


def test_blocking_provider_error_and_provider_change_invalidate_preview_cache(tmp_path):
    artifact = _artifact()
    valid = _project(artifact)
    changed = _project(artifact, peak_pressure_pa=300_000.0)

    with RefinedBlastStore(tmp_path) as store:
        stored = store.create(valid)
        service = RefinedBlastService(store, stored.project_id, artifact)
        first = service.preview(expected_revision=1)
        stored = store.save_draft(
            stored.project_id, changed.scenario_set[0], expected_revision=1
        )
        second = service.preview(expected_revision=stored.revision)
        assert first.cache_key != second.cache_key

        overlapping_input = _lbe_input()
        overlapping_input["source"]["position_m"] = [0.5, 0.5, 0.5]
        overlapping = _project(artifact, provider_input=overlapping_input)
        stored = store.save_draft(
            stored.project_id, overlapping.scenario_set[0], expected_revision=2
        )
        validation = service.validate(expected_revision=stored.revision)
        assert validation.errors
        assert any(row.module == "lbe_segment" and "source" in row.message for row in validation.errors)
        with pytest.raises(ValueError, match="blocking"):
            service.generate(expected_revision=stored.revision)


def test_large_integer_is_rejected_before_it_can_escape_the_store_boundary(tmp_path):
    artifact = _artifact()
    huge_input = _lbe_input()
    huge_input["source"]["maximum_range_m"] = 10**100_000
    project = _project(artifact)
    scenario = replace(
        project.scenario_set[0],
        load_provider={"provider_id": "lbe_segment", "provider_input": huge_input},
    )
    project = replace(project, scenario_set=(scenario,))

    with RefinedBlastStore(tmp_path) as store:
        with pytest.raises(ValueError):
            store.create(project)


def test_malformed_or_cyclic_public_draft_fails_closed_at_store_boundary(tmp_path):
    artifact = _artifact()
    project = _project(artifact)
    cyclic: dict[str, object] = {}
    cyclic["cycle"] = cyclic
    malformed = replace(project.scenario_set[0], load_provider=cyclic)

    with RefinedBlastStore(tmp_path / "cyclic") as store:
        with pytest.raises((ValueError, RecursionError)):
            store.create(replace(project, scenario_set=(malformed,)))

    missing_provider = replace(project.scenario_set[0], load_provider={})
    with RefinedBlastStore(tmp_path / "missing") as store:
        with pytest.raises(ValueError):
            store.create(replace(project, scenario_set=(missing_provider,)))


def test_draft_content_change_invalidates_acknowledgement(tmp_path):
    artifact = _artifact()
    original = _project(artifact)
    changed = _project(artifact, peak_pressure_pa=325_000.0)
    with RefinedBlastStore(tmp_path) as store:
        stored = store.create(original)
        service = RefinedBlastService(store, stored.project_id, artifact)
        validation = service.validate(expected_revision=1)
        for warning in validation.warnings:
            service.acknowledge(validation, warning.finding_id)
        stored = store.save_draft(
            stored.project_id, changed.scenario_set[0], expected_revision=1
        )

        with pytest.raises(ValueError, match="unacknowledged warning"):
            service.generate(expected_revision=stored.revision)


def test_findings_are_unique_and_scenario_path_bound_for_repeated_errors(tmp_path):
    artifact = _artifact()
    project = _project(artifact)
    bad_input = _lbe_input()
    bad_input["source"]["position_m"] = [0.5, 0.5, 0.5]
    first = replace(
        project.scenario_set[0],
        load_provider={"provider_id": "lbe_segment", "provider_input": bad_input},
    )
    second = replace(first, scenario_id="scenario-2")
    project = replace(project, scenario_set=(first, second))

    with RefinedBlastStore(tmp_path) as store:
        stored = store.create(project)
        service = RefinedBlastService(store, stored.project_id, artifact)
        result = service.validate(expected_revision=stored.revision)

    errors = result.errors
    assert len(errors) == 2
    assert len({row.finding_id for row in errors}) == 2
    assert {row.field_path.split(".")[1] for row in errors} == {
        "scenario-1",
        "scenario-2",
    }


def test_service_reads_authoritative_store_and_rejects_stale_revision(tmp_path):
    artifact = _artifact()
    original = _project(artifact)
    changed_project = _project(artifact, peak_pressure_pa=325_000.0)

    with RefinedBlastStore(tmp_path) as store:
        stored = store.create(original)
        service = RefinedBlastService(store, stored.project_id, artifact)
        first = service.validate(expected_revision=1)
        assert first.project_revision == 1

        updated = store.save_draft(
            stored.project_id,
            changed_project.scenario_set[0],
            expected_revision=1,
        )
        with pytest.raises(DraftConflictError, match="expected revision 1"):
            service.validate(expected_revision=1)
        current = service.validate(expected_revision=updated.revision)
        assert current.project_revision == 2
        assert current.project_fingerprint != first.project_fingerprint

        for warning in current.warnings:
            service.acknowledge(current, warning.finding_id)
        next_project = _project(artifact, peak_pressure_pa=350_000.0)
        store.save_draft(
            stored.project_id,
            next_project.scenario_set[0],
            expected_revision=2,
        )
        with pytest.raises(DraftConflictError, match="expected revision 2"):
            service.generate(expected_revision=2)


def test_real_phase18c_rc_frame_compiles_all_three_public_providers(tmp_path):
    artifact = compile_refined_building(
        default_building_definition(asset_id="phase18c-rc", structural_system="rc_frame")
    )
    lbe = _lbe_input()
    lbe["source"]["position_m"] = [-2.0, 3.0, 1.5]
    lbe["budgets"]["max_surface_count"] = 1_000
    lbe["budgets"]["max_total_area_m2"] = 10_000.0
    from test_phase18e_assembler import _explicit_input, _imported_input

    explicit = _explicit_input()
    explicit["charge"]["position_m"] = [-2.0, 3.0, 1.5]
    explicit["domain"]["bounds_m"] = [-4.0, -2.0, -2.0, 9.0, 8.0, 5.0]
    explicit["budgets"]["max_node_count"] = 10_000
    explicit["budgets"]["max_element_count"] = 10_000
    rows = (
        ("lbe_segment", lbe),
        ("explicit_ale_fsi", explicit),
        ("imported_pressure_history", _imported_input()),
    )

    for index, (provider_id, provider_input) in enumerate(rows):
        project = _project(
            artifact,
            provider_id=provider_id,
            provider_input=provider_input,
        )
        root = tmp_path / str(index)
        with RefinedBlastStore(root) as store:
            stored = store.create(project)
            service = RefinedBlastService(store, stored.project_id, artifact)
            validation = service.validate(expected_revision=1)
            assert not validation.errors, (provider_id, validation.errors)


def test_surface_geometry_rejects_non_face_hex_node_cycle():
    artifact = _artifact()
    forged = dict(artifact.surface_catalog["exterior_surfaces"][0])
    forged["node_ids"] = [1, 3, 6, 8]
    for key in ("area_m2", "centroid_m", "normal"):
        forged.pop(key, None)

    with pytest.raises(ValueError, match="oriented boundary face"):
        surface_geometry_from_artifact(artifact, forged, "forged diagonal")


def test_approved_subway_lbe_area_is_stable_through_scenario_set_compilation(tmp_path):
    artifact = compile_detailed_building_asset(
        "subway_entrance_detailed_building",
        legacy_geometry={
            "length_m": 4.0,
            "width_m": 3.0,
            "platform_height_m": 0.30,
            "enclosure_height_m": 2.40,
            "wall_thickness_m": 0.20,
            "roof_thickness_m": 0.20,
        },
        mesh_profile="coarse",
        generation_options={"rebar_spacing_m": 0.50},
    ).artifacts[0]
    provider_input = _lbe_input()
    provider_input["source"]["position_m"] = [-2.0, 1.5, 1.5]
    provider_input["budgets"]["max_surface_count"] = 100_000
    provider_input["budgets"]["max_total_area_m2"] = 1_000_000.0
    project = replace(
        _project(artifact, provider_input=provider_input),
        project_id="acceptance-18d-subway-lbe-external",
    )

    with RefinedBlastStore(tmp_path) as store:
        stored = store.create(project)
        service = RefinedBlastService(store, stored.project_id, artifact)
        validation = service.validate(expected_revision=stored.revision)
        assert validation.errors == ()
        for warning in validation.warnings:
            service.acknowledge(validation, warning.finding_id)
        result = service.compile_scenario_set(expected_revision=stored.revision)

    assert len(result.packages) == 1
    assert result.packages[0].scenario_id == "scenario-1"


def test_real_module_preview_layers_are_renderable_and_count_family_is_complete(tmp_path):
    artifact = compile_refined_building(
        default_building_definition(asset_id="phase18c-modules", structural_system="rc_frame")
    )
    lbe = _lbe_input()
    lbe["source"]["position_m"] = [-2.0, 3.0, 1.5]
    lbe["budgets"]["max_surface_count"] = 1_000
    lbe["budgets"]["max_total_area_m2"] = 10_000.0
    project = _project(artifact, provider_input=lbe)
    budget = {
        "schema_version": "refined_blast.module_budgets@1",
        "max_new_nodes": 10_000,
        "max_new_elements": 10_000,
    }
    ground_face = artifact.surface_catalog["ground_contact_surfaces"][0]["face_id"]
    exterior_face = artifact.surface_catalog["exterior_surfaces"][0]["face_id"]
    scenario = replace(
        project.scenario_set[0],
        building_placement={
            "schema_version": "refined_blast.placement@1",
            "unit_system": "SI_m_s_kg_N_Pa",
            "building_count": 1,
            "translation_m": [0.0, 0.0, 0.0],
            "budgets": budget,
        },
        support_and_ground={
            "schema_version": "refined_blast.support_ground@1",
            "unit_system": "SI_m_s_kg_N_Pa",
            "support_face_ids": [ground_face],
            "coupling_semantics": "shared_node",
            "budgets": budget,
        },
        blast_source={
            "schema_version": "refined_blast.blast_source@1",
            "unit_system": "SI_m_s_kg_N_Pa",
            "source_declared_id": "lbe_segment:source:charge-1",
            "source_space_id": "exterior",
            "budgets": budget,
        },
        fluid_domain={
            "schema_version": "refined_blast.fluid_domain@1",
            "unit_system": "SI_m_s_kg_N_Pa",
            "source_space_id": "exterior",
            "opening_states": {},
            "external_buffer_m": 1.0,
            "budgets": budget,
        },
        boundaries={
            "schema_version": "refined_blast.boundaries@1",
            "unit_system": "SI_m_s_kg_N_Pa",
            "assignments": [
                {
                    "boundary_id": "exterior-outflow",
                    "face_id": exterior_face,
                    "boundary_type": "non_reflecting",
                }
            ],
            "budgets": budget,
        },
    )
    project = replace(project, scenario_set=(scenario,))

    with RefinedBlastStore(tmp_path) as store:
        stored = store.create(project)
        service = RefinedBlastService(store, stored.project_id, artifact)
        preview = service.preview(expected_revision=1)
        validation = service.validate(expected_revision=1)
        for warning in validation.warnings:
            service.acknowledge(validation, warning.finding_id)
        package = service.generate(expected_revision=1)

    assert {row.metric for row in preview.counts} == {
        "building_nodes",
        "building_elements",
        "provider_nodes",
        "provider_elements",
        "provider_fsi_faces",
        "module_new_nodes",
        "module_new_elements",
        "symbolic_ids",
    }
    by_id = {row.layer_id: row.payload for row in preview.layers}
    assert by_id["fluid_domain"]["regions"]
    assert by_id["fluid_domain"]["roles"]
    assert by_id["boundaries"]["surfaces"][0]["node_ids"]
    assert by_id["boundaries"]["connections"]
    assert by_id["support_ground"]["nodes"]
    assert by_id["support_ground"]["elements"]
    assert by_id["support_ground"]["roles"]

    files = dict(package.files)
    support_path = next(path for path in files if path.endswith("_support_ground.k"))
    support = files[support_path]
    node_marker = next(
        line for line in support.splitlines() if line and line[0:1].isdigit() and line.count(b",") == 3
    )
    fields = node_marker.split(b",")
    fields[1] = str(float(fields[1]) + 0.25).encode("ascii")
    files[support_path] = support.replace(node_marker, b",".join(fields), 1)
    manifest = dict(package.manifest)
    manifest["files"] = tuple(
        {
            "path": path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "byte_count": len(content),
            "line_count": len(content.decode("utf-8").splitlines()),
        }
        for path, content in files.items()
    )
    forged = RefinedBlastPackage(
        files=files,
        manifest=manifest,
        symbol_to_numeric_id=package.symbol_to_numeric_id,
        building_artifact_fingerprint=package.building_artifact_fingerprint,
    )
    with RefinedBlastStore(tmp_path) as store:
        with pytest.raises(ValueError, match="support/ground.*manifest"):
            validate_public_package(
                forged,
                store,
                "project-1",
                artifact,
                expected_revision=1,
            )
