from __future__ import annotations

import math
import subprocess
import sys

import pytest

from lsprepost_mcp.refined_blast import (
    get_load_provider,
    list_load_providers,
    normalize_refined_blast_project,
    normalize_scenario_draft,
)


def minimal_scenario_dict() -> dict[str, object]:
    return {
        "scenario_id": "scenario-1",
        "scenario_kind": "external",
        "building_placement": {},
        "support_and_ground": {},
        "load_provider": {"provider_id": "lbe_segment", "provider_input": valid_lbe_input()},
        "blast_source": {},
        "fluid_domain": {},
        "boundaries": {},
        "interactions": {},
        "solver_controls": {},
        "output_requests": {},
        "resource_versions": {},
        "acknowledged_warning_ids": [],
    }


def valid_lbe_input() -> dict[str, object]:
    return {
        "schema_version": "lbe_segment@1",
        "unit_system": "SI_m_s_kg_N_Pa",
        "source": {"schema_version": "lbe_segment.source@1", "source_id": "charge-1", "position_m": [-1.0, 3.0, 1.5], "direction_unit_vector": [1.0, 0.0, 0.0], "maximum_range_m": 20.0},
        "selection": {"schema_version": "lbe_segment.selection@1", "surface_categories": ["exterior_surfaces"], "occlusion_policy": "none", "user_surface_ids": []},
        "load": {"schema_version": "lbe_segment.load@1", "peak_pressure_pa": 250000.0, "positive_phase_duration_s": 0.02},
        "budgets": {"schema_version": "lbe_segment.budgets@1", "max_surface_count": 10000, "max_total_area_m2": 100000.0},
    }


def minimal_project_dict() -> dict[str, object]:
    return {
        "schema_version": "refined_building_blast@1",
        "project_id": "project-1",
        "building_reference": {"asset_id": "building-1"},
        "building_artifact_fingerprint": "a" * 64,
        "preset_reference": "none",
        "preset_version": "1",
        "project_overrides": {},
        "expert_extensions": {},
        "scenario_set": [minimal_scenario_dict()],
        "confirmation_records": [],
        "provenance": {},
        "created_at": "2026-08-11T00:00:00Z",
        "updated_at": "2026-08-11T00:00:00Z",
    }


def test_project_contract_is_closed_versioned_and_immutable():
    project = normalize_refined_blast_project(minimal_project_dict())

    assert project.schema_version == "refined_building_blast@1"
    assert project.scenario_set[0].scenario_id == "scenario-1"
    with pytest.raises(ValueError, match="unknown field"):
        normalize_refined_blast_project({**minimal_project_dict(), "city_layout": []})
    with pytest.raises(TypeError):
        project.project_overrides["mutated"] = True  # type: ignore[index]


def test_provider_input_normalizes_without_false_ancestor_cycle():
    raw = minimal_scenario_dict()
    raw["load_provider"] = {"provider_id": "lbe_segment", "provider_input": valid_lbe_input()}
    normalized = normalize_scenario_draft(raw)
    assert normalized.load_provider["provider_input"]["schema_version"] == "lbe_segment@1"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", "refined_building_blast@2", "schema_version"),
        ("project_id", "../escape", "project_id"),
        ("building_artifact_fingerprint", "not-a-digest", "fingerprint"),
        ("created_at", "", "created_at"),
    ],
)
def test_project_rejects_invalid_required_fields(field: str, value: object, message: str):
    raw = minimal_project_dict()
    raw[field] = value

    with pytest.raises(ValueError, match=message):
        normalize_refined_blast_project(raw)


def test_project_rejects_duplicate_scenario_ids_and_non_finite_values():
    raw = minimal_project_dict()
    raw["scenario_set"] = [minimal_scenario_dict(), minimal_scenario_dict()]
    with pytest.raises(ValueError, match="duplicate scenario id"):
        normalize_refined_blast_project(raw)

    raw = minimal_project_dict()
    raw["project_overrides"] = {"charge_kg": math.nan}
    with pytest.raises(ValueError, match="unknown field"):
        normalize_refined_blast_project(raw)


def test_scenario_contract_is_closed_canonical_and_rejects_bool_numbers():
    scenario = normalize_scenario_draft(minimal_scenario_dict())

    assert scenario.scenario_kind == "external"
    assert scenario.acknowledged_warning_ids == ()
    with pytest.raises(ValueError, match="unknown field"):
        normalize_scenario_draft({**minimal_scenario_dict(), "legacy_case": {}})

    raw = minimal_scenario_dict()
    raw["solver_controls"] = {"end_time_s": True}
    with pytest.raises(ValueError, match="unknown field"):
        normalize_scenario_draft(raw)


def test_scenario_rejects_undeclared_units_in_nested_configuration():
    raw = minimal_scenario_dict()
    raw["solver_controls"] = {"time_unit": "fortnight"}

    with pytest.raises(ValueError, match="unknown field"):
        normalize_scenario_draft(raw)


def test_scenario_rejects_undeclared_plural_unit_key():
    raw = minimal_scenario_dict()
    raw["fluid_domain"] = {"pressure_units": "fortnight"}

    with pytest.raises(ValueError, match="unknown field"):
        normalize_scenario_draft(raw)


@pytest.mark.parametrize(
    "field",
    [
        "building_placement",
        "support_and_ground",
        "blast_source",
        "fluid_domain",
        "boundaries",
        "interactions",
        "solver_controls",
        "output_requests",
        "resource_versions",
    ],
)
def test_scenario_rejects_unknown_fields_in_each_current_nested_contract(field: str):
    raw = minimal_scenario_dict()
    raw[field] = {"legacy_option": "not-declared"}

    with pytest.raises(ValueError, match="unknown field"):
        normalize_scenario_draft(raw)


def test_project_and_provider_nested_contracts_reject_unknown_fields():
    raw = minimal_project_dict()
    raw["building_reference"] = {"asset_id": "building-1", "city_layout": "legacy"}
    with pytest.raises(ValueError, match="unknown field"):
        normalize_refined_blast_project(raw)

    raw = minimal_project_dict()
    raw["project_overrides"] = {"legacy_option": "not-declared"}
    with pytest.raises(ValueError, match="unknown field"):
        normalize_refined_blast_project(raw)

    raw = minimal_scenario_dict()
    raw["load_provider"] = {
        "provider_id": "explicit_ale_fsi",
        "legacy_option": "not-declared",
    }
    with pytest.raises(ValueError, match="unknown field"):
        normalize_scenario_draft(raw)


def test_closed_mapping_checks_unknown_keys_before_canonicalizing_recursive_values():
    recursive: dict[str, object] = {}
    recursive["recursive"] = recursive
    raw = minimal_scenario_dict()
    raw["fluid_domain"] = recursive

    with pytest.raises(ValueError, match="unknown field"):
        normalize_scenario_draft(raw)


def test_known_closed_mapping_value_rejects_recursive_container_without_recursion_error():
    recursive: dict[str, object] = {}
    recursive["asset_id"] = recursive
    raw = minimal_project_dict()
    raw["building_reference"] = recursive

    with pytest.raises(ValueError, match="cyclic"):
        normalize_refined_blast_project(raw)


@pytest.mark.parametrize("kind", ["external", "internal", "semi_enclosed"])
def test_scenario_accepts_only_declared_kinds(kind: str):
    raw = minimal_scenario_dict()
    raw["scenario_kind"] = kind
    assert normalize_scenario_draft(raw).scenario_kind == kind


def test_scenario_rejects_unsupported_provider_and_duplicate_acknowledgements():
    raw = minimal_scenario_dict()
    raw["load_provider"] = {"provider_id": "legacy_blast"}
    with pytest.raises(ValueError, match="load_provider.provider_id"):
        normalize_scenario_draft(raw)

    raw = minimal_scenario_dict()
    raw["acknowledged_warning_ids"] = ["warning-1", "warning-1"]
    with pytest.raises(ValueError, match="duplicate acknowledged_warning_id"):
        normalize_scenario_draft(raw)


def test_provider_registry_lazily_loads_each_real_provider_as_singleton():
    descriptors = list_load_providers()

    assert tuple(descriptor.provider_id for descriptor in descriptors) == (
        "explicit_ale_fsi",
        "lbe_segment",
        "imported_pressure_history",
        "solver_complete_ale_fsi",
    )
    first = get_load_provider("explicit_ale_fsi")
    second = get_load_provider("explicit_ale_fsi")
    assert first.provider_id == "explicit_ale_fsi"
    assert first is second
    assert get_load_provider("lbe_segment").provider_id == "lbe_segment"
    imported_first = get_load_provider("imported_pressure_history")
    imported_second = get_load_provider("imported_pressure_history")
    assert imported_first.provider_id == "imported_pressure_history"
    assert imported_first is imported_second
    solver_complete_first = get_load_provider("solver_complete_ale_fsi")
    solver_complete_second = get_load_provider("solver_complete_ale_fsi")
    assert solver_complete_first.provider_id == "solver_complete_ale_fsi"
    assert solver_complete_first is solver_complete_second
    with pytest.raises(ValueError, match="unsupported provider"):
        get_load_provider("legacy_blast")


def test_root_package_lookup_loads_explicit_provider_in_a_fresh_interpreter():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from lsprepost_mcp.refined_blast import get_load_provider; "
                "a=get_load_provider('explicit_ale_fsi'); "
                "b=get_load_provider('explicit_ale_fsi'); "
                "print(a.provider_id, a is b)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "explicit_ale_fsi True"


def _complete_module_scenario() -> dict[str, object]:
    raw = minimal_scenario_dict()
    budget = {
        "schema_version": "refined_blast.module_budgets@1",
        "max_new_nodes": 1000,
        "max_new_elements": 1000,
    }
    raw.update(
        {
            "building_placement": {
                "schema_version": "refined_blast.placement@1",
                "unit_system": "SI_m_s_kg_N_Pa",
                "building_count": 1,
                "translation_m": [0.0, 0.0, 0.0],
                "budgets": dict(budget),
            },
            "support_and_ground": {
                "schema_version": "refined_blast.support_ground@1",
                "unit_system": "SI_m_s_kg_N_Pa",
                "support_face_ids": ["solid:1:face:0"],
                "coupling_semantics": "shared_node",
                "budgets": dict(budget),
            },
            "blast_source": {
                "schema_version": "refined_blast.blast_source@1",
                "unit_system": "SI_m_s_kg_N_Pa",
                "source_declared_id": "lbe_segment:source:charge-1",
                "source_space_id": "exterior",
                "budgets": dict(budget),
            },
            "fluid_domain": {
                "schema_version": "refined_blast.fluid_domain@1",
                "unit_system": "SI_m_s_kg_N_Pa",
                "source_space_id": "exterior",
                "opening_states": {"door-1": "closed"},
                "external_buffer_m": 1.0,
                "budgets": dict(budget),
            },
            "boundaries": {
                "schema_version": "refined_blast.boundaries@1",
                "unit_system": "SI_m_s_kg_N_Pa",
                "assignments": [
                    {
                        "boundary_id": "outflow-1",
                        "face_id": "solid:1:face:1",
                        "boundary_type": "non_reflecting",
                    }
                ],
                "budgets": dict(budget),
            },
            "interactions": {
                "schema_version": "refined_blast.interactions@1",
                "unit_system": "SI_m_s_kg_N_Pa",
                "pairs": [
                    {
                        "interaction_id": "fsi-1",
                        "interaction_type": "fsi_candidate",
                        "source_id": "fluid:scenario-1",
                        "target_id": "building:scenario-1",
                    }
                ],
                "budgets": dict(budget),
            },
        }
    )
    return raw


@pytest.mark.parametrize(
    ("field", "path", "bad_value", "message"),
    [
        ("building_placement", ("schema_version",), "refined_blast.placement@99", "schema_version"),
        ("support_and_ground", ("coupling_semantics",), "glued", "coupling_semantics"),
        ("blast_source", ("source_space_id",), "bad room", "source_space_id"),
        ("fluid_domain", ("external_buffer_m",), math.nan, "external_buffer_m"),
        ("boundaries", ("assignments", 0, "boundary_type"), "absorbing-ish", "boundary_type"),
        ("interactions", ("pairs", 0, "interaction_type"), "magic", "interaction_type"),
        ("building_placement", ("unit_system",), "mm_ms_kg", "unit_system"),
        ("building_placement", ("budgets", "max_new_nodes"), 0, "max_new_nodes"),
        ("building_placement", ("budgets", "max_new_elements"), True, "max_new_elements"),
        ("building_placement", ("budgets", "max_new_nodes"), 10**12, "hard safety limit"),
    ],
)
def test_task6_module_values_fail_closed_before_persistence(
    field: str, path: tuple[object, ...], bad_value: object, message: str
):
    raw = _complete_module_scenario()
    target: object = raw[field]
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = bad_value  # type: ignore[index]

    with pytest.raises(ValueError, match=message):
        normalize_scenario_draft(raw)
