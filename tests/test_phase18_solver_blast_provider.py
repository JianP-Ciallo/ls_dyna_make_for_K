from __future__ import annotations

import json
from dataclasses import replace

import pytest

from lsprepost_mcp.refined_blast.store import _project_to_raw
from lsprepost_mcp.refined_blast.provider_registry import (
    get_load_provider,
    list_load_providers,
)
from lsprepost_mcp.refined_blast.assembler import (
    ProjectAssembler,
    assemble_refined_blast_project,
)
from lsprepost_mcp.refined_blast.preview import build_refined_blast_preview
from lsprepost_mcp.refined_blast.providers.common import (
    ProviderContext,
    thaw_value,
)
from lsprepost_mcp.refined_building.solver_blast import (
    build_physical_building,
    build_solver_blast_scene,
    compile_solver_blast_deck,
    inspect_solver_blast_deck,
    normalize_solver_blast_config,
)
from test_phase18_solver_blast_buildings import (
    COMMERCIAL,
    RESIDENTIAL,
    SUBWAY,
    _package,
)
from test_phase18e_assembler import _project
from lsprepost_mcp.web.refined_blast_api import RefinedBlastApi


def test_solver_complete_provider_is_public_and_uses_closed_movable_tnt_contract() -> None:
    descriptors = {row.provider_id: row for row in list_load_providers()}
    assert "solver_complete_ale_fsi" in descriptors

    provider = get_load_provider("solver_complete_ale_fsi")
    default = provider.default_input()
    normalized = provider.normalize(default)
    provider_schema = provider.schema()
    schema = provider_schema["input_schema"]

    assert normalized["tnt_equivalent_mass_kg"] == pytest.approx(2.0)
    assert tuple(normalized["charge_position_m"]) == (-2.0, 1.5, 4.0)
    assert normalized["schema_version"] == "phase18.solver_blast.config@4"
    assert normalized["air_cell_size_m"] == pytest.approx(0.225)
    assert normalized["near_field_cell_size_m"] == pytest.approx(0.15)
    assert normalized["ground_cell_size_m"] == pytest.approx(0.25)
    assert tuple(normalized["air_margins_m"]) == (3.0, 3.0, 3.0, 3.0, 3.0)
    assert normalized["coupling_buffer_layers"] == 2
    assert normalized["material_profile"] == "verification_reference"
    assert normalized["termination_time_s"] == pytest.approx(5.0e-5)
    assert provider_schema["accepted_migrations"] == (
        "phase18.solver_blast.config@1",
        "phase18.solver_blast.config@2",
        "phase18.solver_blast.config@3",
    )
    assert schema["properties"]["tnt_equivalent_mass_kg"]["minimum"] == 0.1
    assert schema["properties"]["tnt_equivalent_mass_kg"]["maximum"] == 100.0
    assert schema["properties"]["charge_position_m"]["minItems"] == 3
    assert schema["properties"]["charge_position_m"]["maxItems"] == 3
    assert schema["properties"]["ground_cell_size_m"]["minimum"] == 0.1
    assert schema["properties"]["ground_cell_size_m"]["maximum"] == 0.5
    assert schema["properties"]["air_cell_size_m"]["minimum"] == 0.15
    assert schema["properties"]["air_cell_size_m"]["maximum"] == 0.5
    assert schema["properties"]["near_field_cell_size_m"]["minimum"] == 0.05
    assert schema["properties"]["air_margins_m"]["minItems"] == 5
    assert schema["properties"]["air_margins_m"]["maxItems"] == 5
    assert schema["properties"]["coupling_buffer_layers"]["minimum"] == 1
    assert schema["properties"]["coupling_buffer_layers"]["maximum"] == 5
    assert tuple(schema["properties"]["material_profile"]["enum"]) == (
        "verification_reference",
        "project_calibrated",
    )
    assert provider.capabilities()["solver_complete"] is True
    assert provider.capabilities()["solver_ready"] is False


def test_solver_complete_provider_preview_exposes_air_ground_charge_and_fsi() -> None:
    artifact = _package(COMMERCIAL).artifacts[0]
    provider = get_load_provider("solver_complete_ale_fsi")
    context = ProviderContext.from_artifact(
        artifact, scenario_kind="external"
    )

    preview = provider.preview(provider.default_input(), context)

    assert tuple(preview["detonation_position_m"]) == (-2.0, 1.5, 4.0)
    assert len(preview["domain_bounds_m"]) == 6
    assert len(preview["ground_bounds_m"]) == 6
    assert preview["domain_bounds_m"] == preview["active_air_bounds_m"]
    assert preview["active_air_bounds_m"][2] == pytest.approx(0.0)
    assert preview["coupling_buffer_bounds_m"][5] == pytest.approx(0.0)
    assert preview["coupling_buffer_bounds_m"][2] == pytest.approx(
        -2 * float(provider.default_input()["air_cell_size_m"])
    )
    assert preview["visible_air_domain"] is True
    assert preview["real_fsi_on_generation"] is True
    assert preview["tnt_equivalent_mass_kg"] == pytest.approx(2.0)
    assert preview["tnt_geometry_kind"] == "mass_conserving_cuboid"
    assert len(preview["tnt_bounds_m"]) == 6
    assert preview["tnt_minimum_solid_element_count"] == 27
    assert preview["tnt_realized_mass_kg"] == pytest.approx(2.0)


@pytest.mark.parametrize("resource_id", [COMMERCIAL, RESIDENTIAL, SUBWAY])
def test_solver_complete_default_charge_is_valid_air_for_every_supported_asset(
    resource_id: str,
) -> None:
    provider = get_load_provider("solver_complete_ale_fsi")
    config = normalize_solver_blast_config(provider.default_input())

    scene = build_solver_blast_scene(
        build_physical_building(_package(resource_id)),
        config,
    )

    assert scene.charge.position_m == (-2.0, 1.5, 4.0)


def test_solver_complete_subway_preview_marks_the_physical_upper_grade() -> None:
    detailed = _package(SUBWAY)
    physical = build_physical_building(detailed)
    artifact = detailed.artifacts[0]
    provider = get_load_provider("solver_complete_ale_fsi")

    preview = provider.preview(
        provider.default_input(),
        ProviderContext.from_artifact(artifact, scenario_kind="external"),
    )

    assert preview["ground_bounds_m"][5] == pytest.approx(
        physical.grade_elevation_m
    )


def test_solver_complete_provider_is_canonically_rebuilt_at_assembly_boundary() -> None:
    artifact = _package(COMMERCIAL).artifacts[0]
    provider = get_load_provider("solver_complete_ale_fsi")
    provider_input = dict(provider.default_input())
    context = ProviderContext.from_artifact(artifact, scenario_kind="external")
    estimate = provider.estimate(provider_input, context)
    fragment = provider.compile(provider_input, context)
    forged_manifest = thaw_value(fragment.manifest)
    forged_manifest["solver_complete"] = False
    forged = replace(fragment, manifest=forged_manifest)

    with pytest.raises(ValueError, match="canonical provider fragment mismatch"):
        ProjectAssembler().assemble(
            (),
            artifact=artifact,
            provider_fragment=forged,
            provider_estimate=estimate,
            provider_input=provider_input,
            scenario_kind="external",
        )


def test_solver_complete_preview_renders_visible_air_ground_and_charge_layers() -> None:
    artifact = _package(COMMERCIAL).artifacts[0]
    provider = get_load_provider("solver_complete_ale_fsi")
    project = _project(
        artifact,
        provider_id="solver_complete_ale_fsi",
        provider_input=dict(provider.default_input()),
    )
    neutral = assemble_refined_blast_project(project, artifact)
    provider_preview = provider.preview(
        provider.default_input(),
        ProviderContext.from_artifact(artifact, scenario_kind="external"),
    )

    preview = build_refined_blast_preview(
        project,
        artifact,
        neutral,
        provider_preview=provider_preview,
        module_payloads={},
        revision=1,
        cache_key="solver-complete-preview",
        is_final=False,
    )
    layers = {row.layer_id: row for row in preview.layers}

    assert layers["fluid_domain"].payload["representation"] == "visible_solver_complete_air_domain"
    assert [
        row["primitive_id"]
        for row in layers["fluid_domain"].payload["neutral_primitives"]
    ] == ["active-air-proxy", "coupling-buffer-proxy"]
    assert layers["support_ground"].payload["representation"] == "visible_solver_complete_ground"
    assert layers["support_ground"].payload["neutral_primitives"]
    blast_primitives = layers["blast_source"].payload["neutral_primitives"]
    tnt = next(row for row in blast_primitives if row["primitive_id"] == "tnt-solid")
    marker = next(row for row in blast_primitives if row["kind"] == "blast_source")

    assert tnt["kind"] == "mesh"
    assert len(tnt["nodes"]) == 8
    assert len(tnt["faces"]) == 6
    assert marker["position_m"] == (-2.0, 1.5, 4.0)


def test_solver_complete_service_writes_static_valid_real_deck(tmp_path) -> None:
    package = _package(COMMERCIAL)
    provider = get_load_provider("solver_complete_ale_fsi")

    compiled = compile_solver_blast_deck(
        package,
        provider.normalize(provider.default_input()),
        tmp_path,
    )

    report = inspect_solver_blast_deck(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    model = (tmp_path / "model.k").read_text(encoding="utf-8")
    assert report.ok is True
    assert compiled.validation.ok is True
    assert compiled.evidence.model_sha256 == report.model_sha256
    assert manifest["engineering_validated"] is False
    assert manifest["requires_project_review"] is True
    assert "*ALE_MULTI-MATERIAL_GROUP" in model
    assert "*INITIAL_DETONATION" in model
    assert "*CONSTRAINED_LAGRANGE_IN_SOLID" in model


def test_web_generate_returns_solver_complete_deck_without_starting_external_program(
    tmp_path,
) -> None:
    detailed = _package(COMMERCIAL)
    artifact = detailed.artifacts[0]
    provider = get_load_provider("solver_complete_ale_fsi")
    project = _project(
        artifact,
        provider_id="solver_complete_ale_fsi",
        provider_input=dict(provider.default_input()),
    )
    raw = _project_to_raw(project)
    raw.pop("building_reference")
    raw.pop("building_artifact_fingerprint")
    payload = {
        "schema_version": "refined_blast_create@1",
        "project": raw,
        "building": {
            "asset_id": COMMERCIAL,
            "legacy_geometry": {
                "length_m": 6.0,
                "width_m": 4.0,
                "height_m": 4.0,
                "wall_thickness_m": 0.2,
                "entrance_width_m": 2.0,
                "entrance_height_m": 2.2,
            },
            "mesh_profile": "coarse",
            "fidelity_profile": "blast_response",
            "generation_options": {"rebar_spacing_m": 0.5},
        },
    }
    api = RefinedBlastApi(tmp_path)
    created = api.post("/projects", payload)
    project_id = created["project"]["project_id"]
    validation = api.post(
        f"/projects/{project_id}/validate", {"expected_revision": 1}
    )["validation"]
    assert validation["generation_gate"]["blocking_error_ids"] == []
    for finding in validation["findings"]:
        if finding["severity"] == "warning":
            api.post(
                f"/projects/{project_id}/acknowledgements",
                {
                    "expected_revision": 1,
                    "validation_fingerprint": validation["fingerprint"],
                    "finding_id": finding["finding_id"],
                },
            )

    generated = api.post(
        f"/projects/{project_id}/generate", {"expected_revision": 1}
    )
    artifact_row = generated["artifact"]
    retrieved = api.get(
        f"/projects/{project_id}/artifacts/{artifact_row['scenario_id']}/"
        f"{artifact_row['revision']}/{generated['package_fingerprint']}",
        {},
    )
    file_paths = {row["path"] for row in retrieved["package"]["files"]}

    assert generated["solver_complete"] is True
    assert generated["solver_ready"] is False
    assert generated["external_program_started"] is False
    assert file_paths == {
        "model.k",
        "manifest.json",
        "assessment_semantics.json",
    }
    assert retrieved["package"]["manifest"]["static_validation_ok"] is True
