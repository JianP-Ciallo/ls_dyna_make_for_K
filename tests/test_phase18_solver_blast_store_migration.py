from __future__ import annotations

import json
from pathlib import Path

import pytest

from lsprepost_mcp.refined_blast.contracts import normalize_refined_blast_project
from lsprepost_mcp.refined_blast.providers.solver_complete_ale_fsi import (
    SolverCompleteAleFsiProvider,
)
from lsprepost_mcp.refined_blast.store import RefinedBlastStore
import lsprepost_mcp.refined_blast.store as store_module
from lsprepost_mcp.web.refined_blast_api import RefinedBlastApi
from test_phase18e_store import minimal_project
from test_phase18f_api import _deferred_solver_create_payload


def _solver_project():
    raw = store_module._project_to_raw(minimal_project())
    raw["scenario_set"][0]["load_provider"] = {
        "provider_id": "solver_complete_ale_fsi",
        "provider_input": dict(SolverCompleteAleFsiProvider().default_input()),
    }
    return normalize_refined_blast_project(raw)


def _legacy_v3_input() -> dict[str, object]:
    return {
        "schema_version": "phase18.solver_blast.config@3",
        "unit_system": "SI_m_s_kg_N_Pa",
        "tnt_equivalent_mass_kg": 2.0,
        "charge_position_m": [-2.0, 1.5, 4.0],
        "detonation_time_s": 0.0,
        "air_cell_size_m": 0.225,
        "air_margin_m": [3.0, 3.0, 3.0],
        "ground_cell_size_m": 0.25,
        "termination_time_s": 5.0e-5,
    }


def _rewrite_project_as_valid_legacy_v3(
    store: RefinedBlastStore,
    project_id: str,
) -> Path:
    path = store._layout(project_id, create=False) / "project.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    scenario_rows = payload["project"]["scenario_set"]
    scenario_rows[0]["load_provider"]["provider_input"] = _legacy_v3_input()
    fingerprints = dict(payload["fingerprints"])
    fingerprints["provider"] = store_module._sha256({
        "building": fingerprints["building"],
        "providers": [
            {
                "load_provider": row["load_provider"],
                "scenario_id": row["scenario_id"],
            }
            for row in scenario_rows
        ],
    })
    fingerprints["assembly"] = store_module._sha256({
        "building": fingerprints["building"],
        "output_requests": fingerprints["output_requests"],
        "provider": fingerprints["provider"],
        "scenario_input": fingerprints["scenario_input"],
    })
    fingerprints["results"] = store_module._sha256({
        "assembly": fingerprints["assembly"],
        "output_requests": fingerprints["output_requests"],
        "preview": fingerprints["preview"],
    })
    payload["fingerprints"] = fingerprints
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return path


def _rewrite_as_valid_legacy_v3(store: RefinedBlastStore) -> Path:
    created = store.create(_solver_project())
    return _rewrite_project_as_valid_legacy_v3(store, created.project_id)


def test_store_uniquely_migrates_valid_legacy_solver_config_to_v4(
    tmp_path: Path,
) -> None:
    store = RefinedBlastStore(tmp_path)
    _rewrite_as_valid_legacy_v3(store)

    loaded = store.load_project("project-1")
    provider_input = loaded.project.scenario_set[0].load_provider["provider_input"]

    assert provider_input["schema_version"] == "phase18.solver_blast.config@4"
    assert provider_input["near_field_cell_size_m"] == pytest.approx(0.15)
    assert provider_input["coupling_buffer_layers"] == 2
    assert loaded.fingerprints == store_module._fingerprints(loaded.project)


def test_store_rejects_tampered_legacy_solver_config(
    tmp_path: Path,
) -> None:
    store = RefinedBlastStore(tmp_path)
    path = _rewrite_as_valid_legacy_v3(store)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["project"]["scenario_set"][0]["load_provider"][
        "provider_input"
    ]["tnt_equivalent_mass_kg"] = 3.0
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="corrupt project.json"):
        store.load_project("project-1")


def test_api_restores_legacy_solver_project_with_visible_migration_source(
    tmp_path: Path,
) -> None:
    api = RefinedBlastApi(tmp_path)
    created = api.post("/projects", _deferred_solver_create_payload())["project"]
    project_id = created["project_id"]
    _rewrite_project_as_valid_legacy_v3(api._store, project_id)

    metadata_path = api._repository.metadata_path(project_id)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["initial_project"]["scenario_set"][0]["load_provider"][
        "provider_input"
    ] = _legacy_v3_input()
    legacy_request_fingerprint = store_module._sha256({
        "project": metadata["initial_project"],
        "building": metadata["building_recipe"],
    })
    metadata["original_request_fingerprint"] = legacy_request_fingerprint
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    transaction_path = api._repository.transaction_path(project_id, create=False)
    transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
    transaction["request_fingerprint"] = legacy_request_fingerprint
    transaction_path.write_text(
        json.dumps(transaction, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    restored = api.get(f"/projects/{project_id}", {})["project"]

    assert restored["project"]["scenario_set"][0]["load_provider"][
        "provider_input"
    ]["schema_version"] == "phase18.solver_blast.config@4"
    assert restored["provider_input_migrations"] == [
        {
            "scenario_id": restored["project"]["scenario_set"][0]["scenario_id"],
            "provider_id": "solver_complete_ale_fsi",
            "source_schema_version": "phase18.solver_blast.config@3",
            "target_schema_version": "phase18.solver_blast.config@4",
        }
    ]
