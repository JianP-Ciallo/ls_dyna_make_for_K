from __future__ import annotations

import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import contextmanager
from pathlib import Path

import pytest

from lsprepost_mcp.refined_blast.store import _project_to_raw
import lsprepost_mcp.refined_blast.store as store_module
from lsprepost_mcp.web.http_utils import ApiError
from lsprepost_mcp.web.app import create_server
from lsprepost_mcp.web.refined_blast_api import RefinedBlastApi

from test_phase18e_assembler import _artifact, _project


@contextmanager
def _web_server():
    import threading

    server = create_server("127.0.0.1", 0, open_browser=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request(address: tuple[str, int], path: str) -> tuple[int, dict[str, object]]:
    import http.client

    connection = http.client.HTTPConnection(*address, timeout=10)
    connection.request("GET", path)
    response = connection.getresponse()
    payload = json.loads(response.read().decode("utf-8"))
    connection.close()
    return response.status, payload


def _post(address: tuple[str, int], path: str, payload: dict[str, object], method: str = "POST") -> tuple[int, dict[str, object]]:
    import http.client

    connection = http.client.HTTPConnection(*address, timeout=10)
    connection.request(
        method,
        path,
        body=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    response = connection.getresponse()
    result = json.loads(response.read().decode("utf-8"))
    connection.close()
    return response.status, result


def test_refined_api_is_namespaced_and_declares_only_public_providers() -> None:
    with _web_server() as address:
        status, payload = _request(address, "/api/refined-building-blast/capabilities")

    assert status == 200
    assert payload["ok"] is True
    assert {row["provider_id"] for row in payload["result"]["providers"]} == {
        "explicit_ale_fsi",
        "lbe_segment",
        "imported_pressure_history",
        "solver_complete_ale_fsi",
    }


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


def _deferred_create_payload():
    artifact, payload = _create_payload()
    payload["schema_version"] = "refined_blast_create@2"
    return artifact, payload


def _deferred_solver_create_payload():
    from lsprepost_mcp.refined_blast.provider_registry import get_load_provider

    _, payload = _deferred_create_payload()
    payload["building"] = {
        "asset_id": "commercial_supermarket_detailed_building",
        "legacy_geometry": {},
        "mesh_profile": "standard",
        "structural_system": "steel_concrete_hybrid",
        "generation_options": {},
        "material_overrides": {},
    }
    payload["project"]["scenario_set"][0]["load_provider"] = {
        "provider_id": "solver_complete_ale_fsi",
        "provider_input": dict(
            get_load_provider("solver_complete_ale_fsi").default_input()
        ),
    }
    return payload


def test_deferred_create_get_and_save_never_compile_the_building(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lsprepost_mcp.web.refined_blast_api as api_module

    _, payload = _deferred_create_payload()

    def unexpected_compile(*_args, **_kwargs):
        raise AssertionError("draft persistence must not compile the detailed building")

    monkeypatch.setattr(api_module, "_compile_building", unexpected_compile)
    monkeypatch.setattr(api_module, "_compile_building_package", unexpected_compile)
    api = RefinedBlastApi(tmp_path)

    created = api.post("/projects", payload)["project"]
    project_id = created["project_id"]
    loaded = api.get(f"/projects/{project_id}", {})["project"]
    saved = api.post(
        f"/projects/{project_id}/save",
        {
            "expected_revision": loaded["revision"],
            "draft": payload["project"]["scenario_set"][0],
        },
    )["project"]

    assert created["building_compilation_state"] == "pending"
    assert loaded["building_compilation_state"] == "pending"
    assert saved["building_compilation_state"] == "pending"
    assert saved["revision"] == 2
    assert len(created["building_definition_fingerprint"]) == 64


def test_deferred_validation_and_preview_are_lightweight_and_show_tnt_air_and_ground(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lsprepost_mcp.web.refined_blast_api as api_module

    payload = _deferred_solver_create_payload()
    expected_position = [-2.0, 1.5, 4.0]

    def unexpected_compile(*_args, **_kwargs):
        raise AssertionError("configuration preview must not compile the detailed building")

    monkeypatch.setattr(api_module, "_compile_building", unexpected_compile)
    monkeypatch.setattr(api_module, "_compile_building_package", unexpected_compile)
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]

    validation = api.post(
        f"/projects/{project_id}/validate", {"expected_revision": 1}
    )["validation"]
    preview = api.post(
        f"/projects/{project_id}/preview", {"expected_revision": 1}
    )["preview"]

    assert validation["validation_mode"] == "configuration_only"
    assert validation["generation_gate"]["allowed"] is True
    layers = {row["layer_id"]: row["payload"] for row in preview["layers"]}
    assert layers["structure"]["neutral_primitives"]
    assert layers["fluid_domain"]["neutral_primitives"]
    assert layers["support_ground"]["neutral_primitives"]
    blast_primitives = layers["blast_source"]["neutral_primitives"]
    marker = next(row for row in blast_primitives if row["kind"] == "blast_source")
    assert marker["position_m"] == expected_position
    assert all(row["value"] == 100_000_000 for row in preview["counts"])
    assert all(row["semantics"] == "upper_bound" for row in preview["counts"])
    assert preview["is_final"] is False


def test_lightweight_preview_distinguishes_foundation_ground_and_representative_meshes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lsprepost_mcp.web.refined_blast_api as api_module

    def unexpected_compile(*_args, **_kwargs):
        raise AssertionError("representative grid preview must not compile the detailed building")

    monkeypatch.setattr(api_module, "_compile_building", unexpected_compile)
    monkeypatch.setattr(api_module, "_compile_building_package", unexpected_compile)
    payload = _deferred_solver_create_payload()
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]
    preview = api.post(
        f"/projects/{project_id}/preview", {"expected_revision": 1}
    )["preview"]

    layers = {row["layer_id"]: row["payload"] for row in preview["layers"]}
    primitive_ids = {
        layer_id: [row["primitive_id"] for row in layer["neutral_primitives"]]
        for layer_id, layer in layers.items()
    }
    assert "building-mesh-grid" in primitive_ids["structure"]
    assert primitive_ids["fluid_domain"] == [
        "active-air-proxy",
        "coupling-buffer-proxy",
        "air-mesh-grid",
    ]
    assert primitive_ids["support_ground"] == [
        "building-foundation-proxy",
        "support-ground-proxy",
        "ground-mesh-grid",
    ]
    assert primitive_ids["boundaries"] == ["active-air-flow-boundary"]
    assert "tnt-solid" in primitive_ids["blast_source"]
    assert layers["structure"]["mesh_profile"] == "standard"
    assert layers["fluid_domain"]["air_cell_size_m"] == pytest.approx(0.225)
    assert layers["support_ground"]["ground_cell_size_m"] == pytest.approx(0.25)


def test_lightweight_preview_uses_config4_asymmetric_air_and_exact_buffer_layers(
    tmp_path: Path,
) -> None:
    payload = _deferred_solver_create_payload()
    provider_input = payload["project"]["scenario_set"][0]["load_provider"][
        "provider_input"
    ]
    provider_input["air_margins_m"] = [2.0, 4.0, 3.0, 5.0, 6.0]
    provider_input["coupling_buffer_layers"] = 5
    provider_input["air_cell_size_m"] = 0.225
    provider_input["near_field_cell_size_m"] = 0.1
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]

    preview = api.post(
        f"/projects/{project_id}/preview", {"expected_revision": 1}
    )["preview"]

    layers = {row["layer_id"]: row["payload"] for row in preview["layers"]}
    fluid = layers["fluid_domain"]
    structure_bounds = fluid["building_envelope_bounds_m"]
    active = fluid["active_air_bounds_m"]
    buffer = fluid["coupling_buffer_bounds_m"]
    assert active == pytest.approx(
        [
            structure_bounds[0] - 2.0,
            structure_bounds[1] - 3.0,
            structure_bounds[2],
            structure_bounds[3] + 4.0,
            structure_bounds[4] + 5.0,
            structure_bounds[5] + 6.0,
        ]
    )
    assert buffer[:2] == pytest.approx(active[:2])
    assert buffer[3:5] == pytest.approx(active[3:5])
    assert buffer[5] == pytest.approx(active[2])
    assert buffer[2] == pytest.approx(active[2] - 5 * 0.225)
    assert fluid["coupling_buffer_layers"] == 5
    assert fluid["near_field_cell_size_m"] == pytest.approx(0.1)


def test_lightweight_grid_fingerprints_follow_mesh_air_and_ground_controls(
    tmp_path: Path,
) -> None:
    def preview_for(name: str, *, mesh: str, air: float, ground: float):
        payload = _deferred_solver_create_payload()
        payload["building"]["mesh_profile"] = mesh
        provider_input = payload["project"]["scenario_set"][0]["load_provider"]["provider_input"]
        provider_input["air_cell_size_m"] = air
        provider_input["ground_cell_size_m"] = ground
        api = RefinedBlastApi(tmp_path / name)
        project_id = api.post("/projects", payload)["project"]["project_id"]
        result = api.post(
            f"/projects/{project_id}/preview", {"expected_revision": 1}
        )["preview"]
        api._store.close()
        return {row["layer_id"]: row for row in result["layers"]}

    standard = preview_for("standard", mesh="standard", air=0.225, ground=0.25)
    changed = preview_for("changed", mesh="fine", air=0.5, ground=0.1)

    def geometry_fingerprint(layer):
        return layer["payload"]["neutral_representation"]["fingerprint"]

    assert geometry_fingerprint(standard["structure"]) != geometry_fingerprint(changed["structure"])
    assert geometry_fingerprint(standard["fluid_domain"]) != geometry_fingerprint(changed["fluid_domain"])
    assert geometry_fingerprint(standard["support_ground"]) != geometry_fingerprint(changed["support_ground"])


def test_deferred_generate_compiles_once_and_uses_latest_saved_tnt_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace
    from types import SimpleNamespace

    import lsprepost_mcp.web.refined_blast_api as api_module

    payload = _deferred_solver_create_payload()
    artifact = replace(
        _artifact(), asset_id="commercial_supermarket_detailed_building"
    )
    compiled = []
    captured_positions = []

    def compile_building_package(recipe):
        compiled.append(dict(recipe))
        return SimpleNamespace(
            artifacts=(artifact,), package_fingerprint="d" * 64
        )

    def compile_solver_package(detailed, scenario):
        assert detailed.artifacts == (artifact,)
        position = list(
            scenario.load_provider["provider_input"]["charge_position_m"]
        )
        captured_positions.append(position)
        return api_module.RefinedBlastPackage(
            files={"model.k": b"*KEYWORD\n*END\n"},
            manifest={
                "schema_version": "test.deferred.generate@1",
                "charge_position_m": position,
            },
            symbol_to_numeric_id={},
            building_artifact_fingerprint=artifact.fingerprint,
        )

    monkeypatch.setattr(
        api_module, "_compile_building_package", compile_building_package
    )
    monkeypatch.setattr(
        api_module, "_compile_solver_complete_web_package", compile_solver_package
    )
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]
    latest_position = [1.25, -0.75, 2.5]
    draft = dict(payload["project"]["scenario_set"][0])
    draft["load_provider"] = {
        **draft["load_provider"],
        "provider_input": {
            **draft["load_provider"]["provider_input"],
            "charge_position_m": latest_position,
        },
    }
    saved = api.post(
        f"/projects/{project_id}/save",
        {"expected_revision": 1, "draft": draft},
    )["project"]

    generated = api.post(
        f"/projects/{project_id}/generate",
        {"expected_revision": saved["revision"]},
    )
    loaded = api.get(f"/projects/{project_id}", {})["project"]

    assert len(compiled) == 1
    assert captured_positions == [latest_position]
    assert generated["artifact"]["revision"] == 3
    assert loaded["building_compilation_state"] == "compiled"
    assert (
        loaded["project"]["building_artifact_fingerprint"]
        == artifact.fingerprint
    )


@pytest.mark.parametrize(
    ("resource_id", "artifact_id"),
    (
        ("subway_entrance_detailed_building", "subway_entrance_compiled"),
        ("residential_community_detailed_building", "residential_tower_compiled"),
    ),
)
def test_legacy_create_keeps_compiled_artifact_identity_when_resource_id_differs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resource_id: str,
    artifact_id: str,
) -> None:
    from dataclasses import replace

    import lsprepost_mcp.web.refined_blast_api as api_module

    artifact, payload = _create_payload()
    artifact = replace(artifact, asset_id=artifact_id)
    payload["building"]["asset_id"] = resource_id
    monkeypatch.setattr(api_module, "_compile_building", lambda _: artifact)

    created = RefinedBlastApi(tmp_path).post("/projects", payload)["project"]

    assert created["project"]["building_reference"] == {"asset_id": artifact_id}
    assert created["project"]["building_artifact_fingerprint"] == artifact.fingerprint


@pytest.mark.parametrize(
    ("resource_id", "artifact_id"),
    (
        ("subway_entrance_detailed_building", "subway_entrance_compiled"),
        ("residential_community_detailed_building", "residential_tower_compiled"),
    ),
)
def test_deferred_generate_materializes_resource_identity_as_compiled_artifact_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resource_id: str,
    artifact_id: str,
) -> None:
    from dataclasses import replace
    from types import SimpleNamespace

    import lsprepost_mcp.web.refined_blast_api as api_module

    payload = _deferred_solver_create_payload()
    payload["building"]["asset_id"] = resource_id
    artifact = replace(_artifact(), asset_id=artifact_id)

    monkeypatch.setattr(
        api_module,
        "_compile_building_package",
        lambda _: SimpleNamespace(
            resource_id=resource_id,
            artifacts=(artifact,),
            package_fingerprint="d" * 64,
        ),
    )
    monkeypatch.setattr(
        api_module,
        "_compile_solver_complete_web_package",
        lambda _detailed, _scenario: api_module.RefinedBlastPackage(
            files={"model.k": b"*KEYWORD\n*END\n"},
            manifest={"schema_version": "test.deferred.identity@1"},
            symbol_to_numeric_id={},
            building_artifact_fingerprint=artifact.fingerprint,
        ),
    )
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]

    api.post(f"/projects/{project_id}/generate", {"expected_revision": 1})
    loaded = api.get(f"/projects/{project_id}", {})["project"]

    assert loaded["building_compilation_state"] == "compiled"
    assert loaded["project"]["building_reference"] == {"asset_id": artifact_id}
    assert loaded["project"]["building_artifact_fingerprint"] == artifact.fingerprint


def test_refined_adapter_creates_loads_and_rejects_unknown_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)

    created = api.post("/projects", payload)
    project_id = created["project"]["project_id"]
    loaded = api.get(f"/projects/{project_id}", {})

    assert loaded["project"]["revision"] == 1
    with pytest.raises(ApiError, match="unknown field") as raised:
        api.post("/projects", {**payload, "unexpected": True})
    assert raised.value.status == 400
    assert raised.value.code == "unknown_field"


def test_create_request_rejects_client_supplied_artifact_fingerprint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    payload["project"]["building_artifact_fingerprint"] = artifact.fingerprint

    with pytest.raises(ApiError) as raised:
        RefinedBlastApi(tmp_path).post("/projects", payload)

    assert raised.value.code == "unknown_field"


def test_http_create_uses_closed_recipe_and_server_owned_artifact_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lsprepost_mcp.web.refined_blast_api as api_module

    artifact, payload = _create_payload()
    monkeypatch.setattr(api_module, "_compile_building", lambda _: artifact)
    monkeypatch.setattr(api_module, "_DEFAULT_API", RefinedBlastApi(tmp_path))
    with _web_server() as address:
        status, response = _post(address, "/api/refined-building-blast/projects", payload)

    assert status == 200
    assert response["result"]["project"]["project"]["building_artifact_fingerprint"] == artifact.fingerprint


def test_refined_adapter_rejects_stale_revision_and_keeps_generate_external_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    created = api.post("/projects", payload)
    project_id = created["project"]["project_id"]
    validation = api.post(f"/projects/{project_id}/validate", {"expected_revision": 1})

    with pytest.raises(ApiError) as stale:
        api.post(f"/projects/{project_id}/validate", {"expected_revision": 2})
    assert stale.value.status == 409
    for finding in validation["validation"]["findings"]:
        if finding["severity"] == "warning":
            api.post(
                f"/projects/{project_id}/acknowledgements",
                {
                    "expected_revision": 1,
                    "validation_fingerprint": validation["validation"]["fingerprint"],
                    "finding_id": finding["finding_id"],
                },
            )
    generated = api.post(f"/projects/{project_id}/generate", {"expected_revision": 1})
    stored_artifact = generated["artifact"]
    retrieved = api.get(
        f"/projects/{project_id}/artifacts/{stored_artifact['scenario_id']}/{stored_artifact['revision']}/{generated['package_fingerprint']}",
        {},
    )

    assert generated["solver_ready"] is False
    assert generated["external_program_started"] is False
    assert generated["requires_project_review"] is True
    assert retrieved["package"]["external_program_started"] is False


def test_dotted_project_and_scenario_identifiers_address_every_project_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    payload["project"]["project_id"] = "project.v1"
    payload["project"]["scenario_set"][0]["scenario_id"] = "scenario.v1"
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)

    created = api.post("/projects", payload)
    loaded = api.get("/projects/project.v1", {})
    draft = dict(payload["project"]["scenario_set"][0])
    saved = api.post(
        "/projects/project.v1/save", {"expected_revision": 1, "draft": draft}
    )
    validation = api.post(
        "/projects/project.v1/validate", {"expected_revision": 2}
    )
    preview = api.post(
        "/projects/project.v1/preview", {"expected_revision": 2}
    )
    acknowledgements = []
    for finding in validation["validation"]["findings"]:
        if finding["severity"] == "warning":
            acknowledgements.append(
                api.post(
                    "/projects/project.v1/acknowledgements",
                    {
                        "expected_revision": 2,
                        "validation_fingerprint": validation["validation"]["fingerprint"],
                        "finding_id": finding["finding_id"],
                    },
                )
            )
    generated = api.post(
        "/projects/project.v1/generate", {"expected_revision": 2}
    )
    reference = generated["artifact"]
    retrieved = api.get(
        f"/projects/project.v1/artifacts/scenario.v1/{reference['revision']}/{generated['package_fingerprint']}",
        {},
    )

    assert store_module.validate_storage_identifier("project.v1", "project_id") == "project.v1"
    assert created["project"]["project_id"] == loaded["project"]["project_id"] == "project.v1"
    assert saved["project"]["revision"] == 2
    assert validation["validation"]["project_id"] == "project.v1"
    assert preview["preview"]["scenario_id"] == "scenario.v1"
    assert acknowledgements
    assert reference["scenario_id"] == "scenario.v1"
    assert retrieved["artifact"]["scenario_id"] == "scenario.v1"
    assert retrieved["package"]["package_fingerprint"] == generated["package_fingerprint"]


@pytest.mark.parametrize(
    "unsafe_identifier",
    (".", "..", "", " ", "project/name", "project\\name", "project:name", "project\uFF0Ev1", "proje\u0441t"),
)
def test_identifier_grammar_rejects_the_same_unsafe_dynamic_segments_in_store_and_web(
    tmp_path: Path, unsafe_identifier: str
) -> None:
    with pytest.raises(ValueError, match="safe identifier"):
        store_module.validate_storage_identifier(unsafe_identifier, "project_id")

    api = RefinedBlastApi(tmp_path)
    with pytest.raises(ApiError) as rejected:
        api.get(f"/projects/{unsafe_identifier}", {})
    assert rejected.value.status == 404
    assert rejected.value.code == "not_found"


@pytest.mark.parametrize("unsafe_scenario_id", ("scenario:name", "scenario name", "工况一", "scenario／name"))
def test_contract_rejects_scenario_identifiers_that_storage_cannot_address(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe_scenario_id: str
) -> None:
    artifact, payload = _create_payload()
    payload["project"]["scenario_set"][0]["scenario_id"] = unsafe_scenario_id
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)

    with pytest.raises(ApiError) as rejected:
        RefinedBlastApi(tmp_path).post("/projects", payload)

    assert rejected.value.status == 400
    assert rejected.value.code == "invalid_request"


def test_failed_generated_index_publication_does_not_advance_project_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]
    validation = api.post(f"/projects/{project_id}/validate", {"expected_revision": 1})["validation"]
    for finding in validation["findings"]:
        if finding["severity"] == "warning":
            api.post(f"/projects/{project_id}/acknowledgements", {
                "expected_revision": 1,
                "validation_fingerprint": validation["fingerprint"],
                "finding_id": finding["finding_id"],
            })
    monkeypatch.setattr(api._index, "publish", lambda *_: (_ for _ in ()).throw(OSError("injected index failure")))

    with pytest.raises(ApiError) as rejected:
        api.post(f"/projects/{project_id}/generate", {"expected_revision": 1})

    assert rejected.value.code == "storage_error"
    assert api._store.load_project(project_id).revision == 1


def test_generated_index_path_must_belong_to_the_current_project(tmp_path: Path) -> None:
    from lsprepost_mcp.web.refined_blast_api import _safe_generated_path

    store = store_module.RefinedBlastStore(tmp_path)
    root = store._safe_root()
    store._layout("project-1", create=True)
    store._layout("other-project", create=True)
    foreign = root / "workspace" / "refined_building_blast" / "other-project" / "generated" / "scenario-1" / ("revision-00000002-" + "a" * 64 + ".json")
    foreign.parent.mkdir(parents=True)
    foreign.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="current project"):
        _safe_generated_path(
            foreign.relative_to(root).as_posix(),
            store,
            "project-1",
            "scenario-1",
            2,
            "a" * 64,
        )


def test_same_project_save_is_linearizable_from_authority_through_response_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    first_api = RefinedBlastApi(tmp_path)
    first_api.post("/projects", payload)
    second_api = RefinedBlastApi(tmp_path)
    first_draft = _project_to_raw(_project(artifact, peak_pressure_pa=300_000.0))["scenario_set"][0]
    second_draft = _project_to_raw(_project(artifact, peak_pressure_pa=350_000.0))["scenario_set"][0]
    authority_available = threading.Event()
    release_first = threading.Event()
    second_mutation_entered = threading.Event()
    original_operation = first_api._project_operation
    original_second_save = second_api._store.save_draft

    @contextmanager
    def paused_operation(project_id: str):
        with original_operation(project_id) as operation:
            authority_available.set()
            assert release_first.wait(timeout=5)
            yield operation

    def observed_second_save(*args, **kwargs):
        second_mutation_entered.set()
        return original_second_save(*args, **kwargs)

    monkeypatch.setattr(first_api, "_project_operation", paused_operation)
    monkeypatch.setattr(second_api._store, "save_draft", observed_second_save)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            first_api.post,
            "/projects/project-1/save",
            {"expected_revision": 1, "draft": first_draft},
        )
        assert authority_available.wait(timeout=5)
        second = executor.submit(
            second_api.post,
            "/projects/project-1/save",
            {"expected_revision": 2, "draft": second_draft},
        )
        try:
            with pytest.raises(TimeoutError):
                second.result(timeout=0.1)
            assert not second_mutation_entered.is_set()
        finally:
            release_first.set()
        first_response = first.result(timeout=5)
        second_response = second.result(timeout=5)

    assert first_response["project"]["revision"] == 2
    assert second_response["project"]["revision"] == 3
    assert second_mutation_entered.is_set()


def test_artifact_response_snapshot_is_linearizable_before_a_same_project_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lsprepost_mcp.web.refined_blast_api as api_module

    artifact, payload = _create_payload()
    monkeypatch.setattr(api_module, "_compile_building", lambda _: artifact)
    first_api = RefinedBlastApi(tmp_path)
    first_api.post("/projects", payload)
    validation = first_api.post(
        "/projects/project-1/validate", {"expected_revision": 1}
    )
    for finding in validation["validation"]["findings"]:
        if finding["severity"] == "warning":
            first_api.post(
                "/projects/project-1/acknowledgements",
                {
                    "expected_revision": 1,
                    "validation_fingerprint": validation["validation"]["fingerprint"],
                    "finding_id": finding["finding_id"],
                },
            )
    generated = first_api.post(
        "/projects/project-1/generate", {"expected_revision": 1}
    )
    reference = generated["artifact"]
    route = (
        f"/projects/project-1/artifacts/scenario-1/{reference['revision']}/"
        f"{generated['package_fingerprint']}"
    )
    second_api = RefinedBlastApi(tmp_path)
    snapshot_started = threading.Event()
    release_snapshot = threading.Event()
    second_mutation_entered = threading.Event()
    original_package_payload = api_module._package_payload
    original_second_save = second_api._store.save_draft

    def paused_package_payload(package):
        snapshot_started.set()
        assert release_snapshot.wait(timeout=5)
        return original_package_payload(package)

    def observed_second_save(*args, **kwargs):
        second_mutation_entered.set()
        return original_second_save(*args, **kwargs)

    monkeypatch.setattr(api_module, "_package_payload", paused_package_payload)
    monkeypatch.setattr(second_api._store, "save_draft", observed_second_save)
    changed_draft = _project_to_raw(
        _project(artifact, peak_pressure_pa=300_000.0)
    )["scenario_set"][0]

    with ThreadPoolExecutor(max_workers=2) as executor:
        retrieval = executor.submit(first_api.get, route, {})
        assert snapshot_started.wait(timeout=5)
        save = executor.submit(
            second_api.post,
            "/projects/project-1/save",
            {"expected_revision": reference["revision"], "draft": changed_draft},
        )
        try:
            with pytest.raises(TimeoutError):
                save.result(timeout=0.1)
            assert not second_mutation_entered.is_set()
        finally:
            release_snapshot.set()
        artifact_response = retrieval.result(timeout=5)
        save_response = save.result(timeout=5)

    assert artifact_response["artifact"]["revision"] == reference["revision"]
    assert artifact_response["package"]["package_fingerprint"] == generated["package_fingerprint"]
    assert save_response["project"]["revision"] == reference["revision"] + 1
    assert second_mutation_entered.is_set()


def test_restart_rebuilds_custom_building_recipe_and_rechecks_artifact_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    compiled: list[dict[str, object]] = []

    def compile_recipe(recipe):
        compiled.append(dict(recipe))
        return artifact

    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", compile_recipe)
    project_id = RefinedBlastApi(tmp_path).post("/projects", payload)["project"]["project_id"]
    restarted = RefinedBlastApi(tmp_path)

    validated = restarted.post(f"/projects/{project_id}/validate", {"expected_revision": 1})

    assert validated["validation"]["project_id"] == project_id
    # Creation finalization and every project route independently reproduce
    # persisted artifact authority; a fresh process performs the third compile.
    assert len(compiled) == 3
    assert compiled[-1]["mesh_profile"] == "standard"


def test_duplicate_project_is_a_conflict_and_save_cannot_append_or_replace_scenario_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]

    different = _create_payload()[1]
    different["project"]["preset_version"] = "different"
    with pytest.raises(ApiError) as duplicate:
        api.post("/projects", different)
    assert duplicate.value.status == 409
    altered = _project_to_raw(_project(artifact))["scenario_set"][0]
    altered["scenario_id"] = "different-scenario"
    with pytest.raises(ApiError) as changed:
        api.post(f"/projects/{project_id}/save", {"expected_revision": 1, "draft": altered})
    assert changed.value.code == "scenario_identity_mismatch"


def test_generated_artifact_survives_restart_and_corruption_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]
    validation = api.post(f"/projects/{project_id}/validate", {"expected_revision": 1})
    for finding in validation["validation"]["findings"]:
        if finding["severity"] == "warning":
            api.post(f"/projects/{project_id}/acknowledgements", {
                "expected_revision": 1,
                "validation_fingerprint": validation["validation"]["fingerprint"],
                "finding_id": finding["finding_id"],
            })
    generated = api.post(f"/projects/{project_id}/generate", {"expected_revision": 1})
    reference = generated["artifact"]
    package_fingerprint = generated["package_fingerprint"]
    restarted = RefinedBlastApi(tmp_path)
    route = f"/projects/{project_id}/artifacts/{reference['scenario_id']}/{reference['revision']}/{package_fingerprint}"
    assert restarted.get(route, {})["package"]["package_fingerprint"] == package_fingerprint

    generated_path = next((tmp_path / "workspace" / "refined_building_blast" / project_id / "generated").rglob("*.json"))
    generated_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ApiError) as corrupted:
        restarted.get(route, {})
    assert corrupted.value.code == "artifact_integrity_error"


def test_artifact_get_rejects_current_project_or_metadata_that_no_longer_matches_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]
    validation = api.post(f"/projects/{project_id}/validate", {"expected_revision": 1})
    for finding in validation["validation"]["findings"]:
        if finding["severity"] == "warning":
            api.post(f"/projects/{project_id}/acknowledgements", {
                "expected_revision": 1,
                "validation_fingerprint": validation["validation"]["fingerprint"],
                "finding_id": finding["finding_id"],
            })
    generated = api.post(f"/projects/{project_id}/generate", {"expected_revision": 1})
    ref = generated["artifact"]
    route = f"/projects/{project_id}/artifacts/{ref['scenario_id']}/{ref['revision']}/{generated['package_fingerprint']}"
    changed_draft = _project_to_raw(_project(artifact, peak_pressure_pa=300_000.0))["scenario_set"][0]
    api.post(f"/projects/{project_id}/save", {"expected_revision": 2, "draft": changed_draft})

    with pytest.raises(ApiError) as stale:
        api.get(route, {})
    assert stale.value.code == "artifact_stale"


def test_create_metadata_write_failure_never_exposes_project_and_retry_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lsprepost_mcp.web.refined_blast_api as api_module

    artifact, payload = _create_payload()
    monkeypatch.setattr(api_module, "_compile_building", lambda _: artifact)
    original_write = store_module._atomic_write_json

    def fail_metadata(path, *args, **kwargs):
        if path.name == "phase18f_refined_blast_metadata.json":
            raise OSError("injected write failure")
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(store_module, "_atomic_write_json", fail_metadata)
    api = RefinedBlastApi(tmp_path)
    with pytest.raises(ApiError) as failed:
        api.post("/projects", payload)
    assert failed.value.code == "project_creation_incomplete"
    with pytest.raises(ApiError) as hidden:
        api.get("/projects/project-1", {})
    assert hidden.value.code == "project_creation_incomplete"

    monkeypatch.setattr(store_module, "_atomic_write_json", original_write)
    recovered = api.post("/projects", payload)
    assert recovered["project"]["project_id"] == "project-1"


def test_metadata_corruption_hides_loaded_project_with_stable_integrity_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    api.post("/projects", payload)
    metadata = tmp_path / "workspace" / "refined_building_blast" / "project-1" / "phase18f_refined_blast_metadata.json"
    metadata.write_text("{}", encoding="utf-8")

    with pytest.raises(ApiError) as corrupted:
        api.get("/projects/project-1", {})
    assert corrupted.value.status == 409
    assert corrupted.value.code == "metadata_integrity_error"


def test_generated_artifact_becomes_stale_after_revision_only_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]
    validation = api.post(f"/projects/{project_id}/validate", {"expected_revision": 1})
    for finding in validation["validation"]["findings"]:
        if finding["severity"] == "warning":
            api.post(f"/projects/{project_id}/acknowledgements", {
                "expected_revision": 1,
                "validation_fingerprint": validation["validation"]["fingerprint"],
                "finding_id": finding["finding_id"],
            })
    generated = api.post(f"/projects/{project_id}/generate", {"expected_revision": 1})
    ref = generated["artifact"]
    route = f"/projects/{project_id}/artifacts/{ref['scenario_id']}/{ref['revision']}/{generated['package_fingerprint']}"
    unchanged = _project_to_raw(_project(artifact))["scenario_set"][0]
    api.post(f"/projects/{project_id}/save", {"expected_revision": 2, "draft": unchanged})

    with pytest.raises(ApiError) as stale:
        api.get(route, {})
    assert stale.value.code == "artifact_stale"


def test_create_transaction_project_write_failure_rejects_save_and_same_request_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    original = api._store._write_project
    calls = 0

    def fail_once(stored):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected project write failure")
        return original(stored)

    monkeypatch.setattr(api._store, "_write_project", fail_once)
    with pytest.raises(ApiError) as failed:
        api.post("/projects", payload)
    assert failed.value.code == "project_creation_incomplete"
    with pytest.raises(ApiError) as save:
        api.post("/projects/project-1/save", {"expected_revision": 1, "draft": _project_to_raw(_project(artifact))["scenario_set"][0]})
    assert save.value.code == "project_creation_incomplete"

    recovered = api.post("/projects", payload)
    assert recovered["project"]["project_id"] == "project-1"


def test_create_transaction_final_confirmation_failure_recovers_idempotently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lsprepost_mcp.web.refined_blast_api as api_module

    artifact, payload = _create_payload()
    monkeypatch.setattr(api_module, "_compile_building", lambda _: artifact)
    original = store_module._atomic_write_json

    def fail_complete(path, value, *args, **kwargs):
        if path.parent.name == ".phase18f_create_transactions" and value.get("state") == "complete":
            raise OSError("injected confirmation failure")
        return original(path, value, *args, **kwargs)

    monkeypatch.setattr(store_module, "_atomic_write_json", fail_complete)
    api = RefinedBlastApi(tmp_path)
    with pytest.raises(ApiError) as failed:
        api.post("/projects", payload)
    assert failed.value.code == "project_creation_incomplete"
    monkeypatch.setattr(store_module, "_atomic_write_json", original)

    assert api.post("/projects", payload)["project"]["project_id"] == "project-1"


@pytest.mark.parametrize(
    ("failed_state", "persisted_state"),
    (("project_written", "preparing"), ("metadata_written", "project_written")),
)
def test_failed_creation_state_advances_recover_only_for_the_same_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_state: str,
    persisted_state: str,
) -> None:
    import lsprepost_mcp.web.refined_blast_api as api_module

    artifact, payload = _create_payload()
    monkeypatch.setattr(api_module, "_compile_building", lambda _: artifact)
    original_write = store_module._atomic_write_json

    def fail_one_advance(path, value, *args, **kwargs):
        if path.parent.name == ".phase18f_create_transactions" and value.get("state") == failed_state:
            raise OSError("injected transaction advance failure")
        return original_write(path, value, *args, **kwargs)

    monkeypatch.setattr(store_module, "_atomic_write_json", fail_one_advance)
    api = RefinedBlastApi(tmp_path)
    with pytest.raises(ApiError) as failed:
        api.post("/projects", payload)
    assert failed.value.code == "project_creation_incomplete"
    transaction = json.loads(api._repository.transaction_path("project-1", create=False).read_text(encoding="utf-8"))
    assert transaction["state"] == persisted_state
    different = _create_payload()[1]
    different["project"]["preset_version"] = "different"
    with pytest.raises(ApiError) as conflict:
        api.post("/projects", different)
    assert conflict.value.code == "project_exists"

    monkeypatch.setattr(store_module, "_atomic_write_json", original_write)
    assert api.post("/projects", payload)["project"]["project_id"] == "project-1"


def test_complete_transaction_mismatch_gates_every_project_route_even_with_cached_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]
    validation = api.post(f"/projects/{project_id}/validate", {"expected_revision": 1})
    transaction = api._repository.transaction_path(project_id, create=False)
    raw = json.loads(transaction.read_text(encoding="utf-8"))
    raw["expected_artifact_fingerprint"] = "0" * 64
    transaction.write_text(json.dumps(raw), encoding="utf-8")
    draft = _project_to_raw(_project(artifact))["scenario_set"][0]
    routes = (
        lambda: api.get(f"/projects/{project_id}", {}),
        lambda: api.post(f"/projects/{project_id}/save", {"expected_revision": 1, "draft": draft}),
        lambda: api.post(f"/projects/{project_id}/validate", {"expected_revision": 1}),
        lambda: api.post(f"/projects/{project_id}/preview", {"expected_revision": 1}),
        lambda: api.post(f"/projects/{project_id}/acknowledgements", {
            "expected_revision": 1,
            "validation_fingerprint": validation["validation"]["fingerprint"],
            "finding_id": validation["validation"]["findings"][0]["finding_id"],
        }),
        lambda: api.post(f"/projects/{project_id}/generate", {"expected_revision": 1}),
        lambda: api.get(f"/projects/{project_id}/artifacts/scenario-1/1/{'0' * 64}", {}),
    )
    for route in routes:
        with pytest.raises(ApiError) as rejected:
            route()
        assert rejected.value.status == 409
        assert rejected.value.code == "transaction_integrity_error"


def test_missing_transaction_can_only_be_rebuilt_by_the_exact_authoritative_create_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]
    transaction = api._repository.transaction_path(project_id, create=False)
    transaction.unlink()
    different = _create_payload()[1]
    different["project"]["preset_version"] = "different"
    with pytest.raises(ApiError) as conflict:
        api.post("/projects", different)
    assert conflict.value.code == "project_exists"
    assert not transaction.exists()

    assert api.post("/projects", payload)["project"]["project_id"] == project_id
    rebuilt = json.loads(transaction.read_text(encoding="utf-8"))
    assert rebuilt["state"] == "complete"


def test_transaction_rebuild_uses_immutable_original_create_evidence_after_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]
    changed = _project_to_raw(_project(artifact, peak_pressure_pa=300_000.0))["scenario_set"][0]
    api.post(f"/projects/{project_id}/save", {"expected_revision": 1, "draft": changed})
    transaction = api._repository.transaction_path(project_id, create=False)
    transaction.unlink()

    current_shape = _create_payload()[1]
    current_shape["project"]["scenario_set"] = [changed]
    with pytest.raises(ApiError) as altered:
        api.post("/projects", current_shape)
    assert altered.value.code == "project_exists"
    assert not transaction.exists()

    recovered = api.post("/projects", payload)
    assert recovered["project"]["revision"] == 2
    evidence = json.loads(api._repository.metadata_path(project_id).read_text(encoding="utf-8"))
    rebuilt = json.loads(transaction.read_text(encoding="utf-8"))
    assert evidence["original_request_fingerprint"] == rebuilt["request_fingerprint"]
    assert evidence["initial_project"]["scenario_set"] != [changed]


def test_missing_transaction_and_metadata_cannot_be_claimed_by_a_create_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]
    transaction = api._repository.transaction_path(project_id, create=False)
    metadata = api._repository.metadata_path(project_id)
    transaction.unlink()
    metadata.unlink()

    with pytest.raises(ApiError) as rejected:
        api.post("/projects", payload)
    assert rejected.value.code == "project_creation_incomplete"
    assert not transaction.exists()


@pytest.mark.parametrize("state", ("preparing", "project_written", "metadata_written"))
def test_incomplete_creation_states_gate_existing_project_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]
    validation = api.post(f"/projects/{project_id}/validate", {"expected_revision": 1})
    transaction = api._repository.transaction_path(project_id, create=False)
    raw = json.loads(transaction.read_text(encoding="utf-8"))
    raw["state"] = state
    transaction.write_text(json.dumps(raw), encoding="utf-8")

    draft = _project_to_raw(_project(artifact))["scenario_set"][0]
    routes = (
        lambda: api.get(f"/projects/{project_id}", {}),
        lambda: api.post(f"/projects/{project_id}/save", {"expected_revision": 1, "draft": draft}),
        lambda: api.post(f"/projects/{project_id}/validate", {"expected_revision": 1}),
        lambda: api.post(f"/projects/{project_id}/preview", {"expected_revision": 1}),
        lambda: api.post(f"/projects/{project_id}/acknowledgements", {
            "expected_revision": 1,
            "validation_fingerprint": validation["validation"]["fingerprint"],
            "finding_id": validation["validation"]["findings"][0]["finding_id"],
        }),
        lambda: api.post(f"/projects/{project_id}/generate", {"expected_revision": 1}),
        lambda: api.get(f"/projects/{project_id}/artifacts/scenario-1/1/{'0' * 64}", {}),
    )
    for route in routes:
        with pytest.raises(ApiError) as rejected:
            route()
        assert rejected.value.code == "project_creation_incomplete"


def test_complete_transaction_request_fingerprint_mismatch_is_never_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    project_id = api.post("/projects", payload)["project"]["project_id"]
    transaction = api._repository.transaction_path(project_id, create=False)
    raw = json.loads(transaction.read_text(encoding="utf-8"))
    raw["request_fingerprint"] = "f" * 64
    transaction.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ApiError) as rejected:
        api.post(f"/projects/{project_id}/validate", {"expected_revision": 1})
    assert rejected.value.code == "transaction_integrity_error"


def test_concurrent_create_is_serialized_without_poisoning_the_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, payload = _create_payload()
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: artifact)
    api = RefinedBlastApi(tmp_path)
    results: list[str] = []
    errors: list[BaseException] = []

    def create() -> None:
        try:
            results.append(api.post("/projects", payload)["project"]["project_id"])
        except BaseException as exc:
            errors.append(exc)

    workers = [threading.Thread(target=create) for _ in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)

    assert errors == []
    assert results == ["project-1"] * 8
    assert api.get("/projects/project-1", {})["project"]["revision"] == 1


def test_real_multiprocess_create_competition_keeps_one_complete_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = """
import json
import sys
from pathlib import Path
sys.path.insert(0, 'tests')
from test_phase18e_assembler import _artifact, _project
from lsprepost_mcp.refined_blast.store import _project_to_raw
import lsprepost_mcp.web.refined_blast_api as api_module
artifact = _artifact()
api_module._compile_building = lambda _: artifact
raw = _project_to_raw(_project(artifact))
raw.pop('building_reference')
raw.pop('building_artifact_fingerprint')
payload = {
  'schema_version': 'refined_blast_create@1',
  'project': raw,
  'building': {'asset_id': artifact.asset_id, 'legacy_geometry': {},
               'mesh_profile': 'standard', 'structural_system': 'rc_box',
               'generation_options': {}, 'material_overrides': {}},
}
try:
    out = api_module.RefinedBlastApi(Path(sys.argv[1])).post('/projects', payload)
    print(json.dumps({'ok': True, 'project_id': out['project']['project_id']}))
except api_module.ApiError as exc:
    print(json.dumps({'ok': False, 'code': exc.code}))
"""
    cwd = Path(__file__).resolve().parents[1]
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(tmp_path)],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(3)
    ]
    outcomes = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=45)
        assert process.returncode == 0, stderr
        outcomes.append(json.loads(stdout))

    assert outcomes == [{"ok": True, "project_id": "project-1"}] * 3
    monkeypatch.setattr("lsprepost_mcp.web.refined_blast_api._compile_building", lambda _: _artifact())
    check = RefinedBlastApi(tmp_path)
    assert check.get("/projects/project-1", {})["project"]["revision"] == 1


def test_real_multiprocess_same_and_different_create_races_are_stable_for_ten_rounds(
    tmp_path: Path,
) -> None:
    script = """
import json
import sys
from pathlib import Path
sys.path.insert(0, 'tests')
from test_phase18e_assembler import _artifact, _project
from lsprepost_mcp.refined_blast.store import _project_to_raw
import lsprepost_mcp.web.refined_blast_api as api_module
artifact = _artifact()
api_module._compile_building = lambda _: artifact
raw = _project_to_raw(_project(artifact))
raw.pop('building_reference')
raw.pop('building_artifact_fingerprint')
variant = sys.argv[2]
if variant == 'different':
    raw['preset_version'] = 'alternate-request'
payload = {
  'schema_version': 'refined_blast_create@1', 'project': raw,
  'building': {'asset_id': artifact.asset_id, 'legacy_geometry': {},
               'mesh_profile': 'standard', 'structural_system': 'rc_box',
               'generation_options': {}, 'material_overrides': {}},
}
try:
    out = api_module.RefinedBlastApi(Path(sys.argv[1])).post('/projects', payload)
    print(json.dumps({'variant': variant, 'ok': True,
                      'project_id': out['project']['project_id']}))
except api_module.ApiError as exc:
    print(json.dumps({'variant': variant, 'ok': False, 'code': exc.code}))
"""
    cwd = Path(__file__).resolve().parents[1]
    for round_index in range(10):
        root = tmp_path / f"round-{round_index}"
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(root), variant],
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for variant in ("same", "same", "different", "different")
        ]
        outcomes = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=45)
            assert process.returncode == 0, stderr
            outcomes.append(json.loads(stdout))
        successes = [row for row in outcomes if row["ok"]]
        failures = [row for row in outcomes if not row["ok"]]
        assert successes
        assert {row["variant"] for row in successes} in ({"same"}, {"different"})
        assert all(row["project_id"] == "project-1" for row in successes)
        assert all(row["code"] == "project_exists" for row in failures)
        transaction = json.loads(
            (root / "workspace" / "refined_building_blast" / ".phase18f_create_transactions" / "project-1.json").read_text(encoding="utf-8")
        )
        metadata = json.loads(
            (root / "workspace" / "refined_building_blast" / "project-1" / "phase18f_refined_blast_metadata.json").read_text(encoding="utf-8")
        )
        assert transaction["state"] == "complete"
        assert transaction["request_fingerprint"] == metadata["original_request_fingerprint"]


def test_refined_routes_reject_legacy_payload_and_unknown_route(tmp_path: Path) -> None:
    api = RefinedBlastApi(tmp_path)

    with pytest.raises(ApiError) as mismatch:
        api.post("/projects", {"project_name": "legacy", "scene_id": "city"})
    assert mismatch.value.code == "project_type_mismatch"
    with pytest.raises(ApiError) as missing:
        api.get("/missing", {})
    assert missing.value.status == 404


def test_legacy_editor_rejects_refined_project_and_refined_wrong_method_is_json() -> None:
    artifact, payload = _create_payload()
    with _web_server() as address:
        legacy_status, legacy = _post(address, "/api/editor/preview", {"schema_version": "refined_building_blast@1"})
        method_status, method = _post(address, "/api/refined-building-blast/capabilities", {})
        put_status, put = _post(address, "/api/refined-building-blast/capabilities", {}, method="PUT")
        trace_status, trace = _post(address, "/api/refined-building-blast/capabilities", {}, method="TRACE")
        query_status, query = _post(address, "/api/refined-building-blast/projects?unexpected=1", {})

    assert artifact.asset_id == "unit-building"
    assert legacy_status == 400
    assert legacy["error"]["code"] == "project_type_mismatch"
    assert method_status == 404
    assert method["error"]["code"] == "not_found"
    assert put_status == 405
    assert put["error"]["code"] == "method_not_allowed"
    assert trace_status == 405
    assert trace["error"]["code"] == "method_not_allowed"
    assert query_status == 400
    assert query["error"]["code"] == "unknown_query"


def test_default_adapter_initializes_once_when_first_requests_race(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import lsprepost_mcp.web.refined_blast_api as api_module

    created: list[RefinedBlastApi] = []
    monkeypatch.setattr(api_module, "_DEFAULT_API", None)
    monkeypatch.setattr(api_module, "WORKSPACE_DIR", tmp_path)
    original = api_module.RefinedBlastApi

    class CountingApi(original):
        def __init__(self):
            super().__init__()
            created.append(self)

    monkeypatch.setattr(api_module, "RefinedBlastApi", CountingApi)
    errors: list[BaseException] = []

    def request() -> None:
        try:
            api_module.handle_refined_blast_get("/capabilities", {})
        except BaseException as exc:
            errors.append(exc)

    workers = [threading.Thread(target=request) for _ in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)

    assert errors == []
    assert len(created) == 1
