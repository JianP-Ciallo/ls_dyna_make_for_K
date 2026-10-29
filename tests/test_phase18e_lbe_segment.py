from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError, replace

import pytest

from lsprepost_mcp.refined_blast import get_load_provider
from lsprepost_mcp.refined_blast.providers import ProviderContext
from lsprepost_mcp.refined_blast.providers.lbe_segment import LbeSegmentProvider
from lsprepost_mcp.refined_building.compiler import compile_refined_building
from lsprepost_mcp.refined_building.contracts import default_building_definition


@pytest.fixture(scope="module")
def detailed_artifact():
    value = default_building_definition(structural_system="rc_box")
    value["spaces"] = [
        {
            "id": "room_1",
            "level_id": "level_1",
            "kind": "room",
            "bounds_m": [0.25, 0.25, 0.25, 5.75, 5.75, 2.75],
        }
    ]
    value["openings"] = [
        {
            "id": "door_external",
            "kind": "door",
            "bounds_m": [0.0, 2.5, 0.25, 0.25, 3.5, 2.25],
            "connects": ["room_1", "exterior"],
        }
    ]
    value["structural_system"]["parameters"] = {
        "generation_mode": "concrete_only",
        "box_thickness_m": 0.25,
        "mesh_size_m": 0.5,
    }
    return compile_refined_building(value)


def context(artifact, *, kind: str = "external") -> ProviderContext:
    return ProviderContext.from_artifact(artifact, scenario_kind=kind)


def valid_lbe_input(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "lbe_segment@1",
        "unit_system": "SI_m_s_kg_N_Pa",
        "source": {
            "schema_version": "lbe_segment.source@1",
            "source_id": "charge-1",
            "position_m": [-1.0, 3.0, 1.5],
            "direction_unit_vector": [1.0, 0.0, 0.0],
            "maximum_range_m": 20.0,
        },
        "selection": {
            "schema_version": "lbe_segment.selection@1",
            "surface_categories": ["exterior_surfaces"],
            "occlusion_policy": "none",
            "user_surface_ids": [],
        },
        "load": {
            "schema_version": "lbe_segment.load@1",
            "peak_pressure_pa": 250000.0,
            "positive_phase_duration_s": 0.02,
        },
        "budgets": {
            "schema_version": "lbe_segment.budgets@1",
            "max_surface_count": 10000,
            "max_total_area_m2": 100000.0,
        },
    }
    value.update(overrides)
    return value


def test_external_lbe_never_selects_internal_faces(detailed_artifact):
    fragment = LbeSegmentProvider().compile(valid_lbe_input(), context(detailed_artifact))

    assert fragment.manifest["surface_categories"] == ("exterior_surfaces",)
    assert all(
        face_id in {row["face_id"] for row in detailed_artifact.surface_catalog["exterior_surfaces"]}
        for face_id in fragment.fsi_face_ids
    )
    source_space = next(
        row for row in fragment.evidence if row.evidence_kind == "provider_source_space"
    )
    assert source_space.claims["source_space_id"] == "exterior"
    assert source_space.claims["source_declared_id"] == "lbe_segment:source:charge-1"


def test_lbe_derives_exactly_one_source_space_and_rejects_structural_ambiguity(
    detailed_artifact,
):
    internal = valid_lbe_input()
    internal["source"]["position_m"] = [3.0, 3.0, 1.5]
    internal["selection"]["surface_categories"] = ["interior_cavity_surfaces"]
    fragment = LbeSegmentProvider().compile(
        internal, context(detailed_artifact, kind="internal")
    )
    source_space = next(
        row for row in fragment.evidence if row.evidence_kind == "provider_source_space"
    )
    assert source_space.claims["source_space_id"] == "room_1"

    ambiguous = valid_lbe_input()
    ambiguous["source"]["position_m"] = [0.1, 3.0, 1.5]
    with pytest.raises(ValueError, match="structural|ambiguous"):
        LbeSegmentProvider().compile(ambiguous, context(detailed_artifact))


def test_user_surface_set_must_be_subset_of_computed_candidates(detailed_artifact):
    internal_face = detailed_artifact.surface_catalog["interior_cavity_surfaces"][0]["face_id"]
    raw = valid_lbe_input()
    raw["selection"]["user_surface_ids"] = [internal_face]

    with pytest.raises(ValueError, match="candidate"):
        LbeSegmentProvider().compile(raw, context(detailed_artifact))


def test_lbe_selection_is_deterministic_and_records_each_inclusion_reason(detailed_artifact):
    provider = LbeSegmentProvider()
    first = provider.compile(valid_lbe_input(), context(detailed_artifact))
    second = provider.compile(valid_lbe_input(), context(detailed_artifact))

    assert first.fingerprint == second.fingerprint
    assert first.fsi_face_ids == tuple(sorted(first.fsi_face_ids))
    inclusion = first.manifest["selection"]["included_faces"]
    assert tuple(row["face_id"] for row in inclusion) == first.fsi_face_ids
    assert all(row["reason"] == "automatic_candidate" for row in inclusion)
    assert first.manifest["solver_ready"] is False
    assert first.manifest["requires_project_review"] is True
    assert first.manifest["lbe_is_not_ale_fsi_equivalent"] is True


def test_user_subset_records_user_selection_reason(detailed_artifact):
    automatic = LbeSegmentProvider().compile(valid_lbe_input(), context(detailed_artifact))
    raw = valid_lbe_input()
    raw["selection"]["user_surface_ids"] = [automatic.fsi_face_ids[0]]

    selected = LbeSegmentProvider().compile(raw, context(detailed_artifact))

    assert selected.fsi_face_ids == (automatic.fsi_face_ids[0],)
    assert selected.manifest["selection"]["included_faces"][0]["reason"] == "user_subset"


def test_direction_range_and_positive_mesh_area_define_candidates(detailed_artifact):
    provider = LbeSegmentProvider()
    backward = valid_lbe_input()
    backward["source"]["direction_unit_vector"] = [-1.0, 0.0, 0.0]
    with pytest.raises(ValueError, match="no candidate"):
        provider.compile(backward, context(detailed_artifact))

    short_range = valid_lbe_input()
    short_range["source"]["maximum_range_m"] = 0.01
    with pytest.raises(ValueError, match="no candidate"):
        provider.compile(short_range, context(detailed_artifact))

    catalog = copy.deepcopy(detailed_artifact.surface_catalog)
    row = catalog["exterior_surfaces"][0]
    node_ids = set(row["node_ids"])
    anchor = next(node for node in detailed_artifact.mesh.nodes if node.node_id in node_ids)
    collapsed = replace(
        detailed_artifact,
        mesh=replace(
            detailed_artifact.mesh,
            nodes=tuple(
                replace(node, x=anchor.x, y=anchor.y, z=anchor.z)
                if node.node_id in node_ids
                else node
                for node in detailed_artifact.mesh.nodes
            ),
        ),
        surface_catalog=catalog,
    )
    with pytest.raises(ValueError, match="positive area"):
        provider.compile(valid_lbe_input(), context(collapsed))


def test_closed_schema_budgets_occlusion_and_id_closure_are_enforced(detailed_artifact):
    provider = LbeSegmentProvider()
    raw = valid_lbe_input()
    raw["selection"]["occlusion_policy"] = "inferred"
    with pytest.raises(ValueError, match="occlusion"):
        provider.normalize(raw)

    raw = valid_lbe_input()
    raw["budgets"]["max_surface_count"] = 1
    with pytest.raises(ValueError, match="surface count budget"):
        provider.compile(raw, context(detailed_artifact))

    fragment = provider.compile(valid_lbe_input(), context(detailed_artifact))
    assert fragment.required_ids <= context(detailed_artifact).available_ids | fragment.declared_ids
    assert fragment.manifest["id_closure"]["closed"] is True
    assert isinstance(get_load_provider("lbe_segment"), LbeSegmentProvider)


def test_catalog_tampering_and_unsafe_source_ids_fail_closed(detailed_artifact):
    catalog = copy.deepcopy(detailed_artifact.surface_catalog)
    catalog["exterior_surfaces"][0]["centroid_m"] = [999.0, 999.0, 999.0]
    with pytest.raises(ValueError, match="does not match artifact"):
        LbeSegmentProvider().compile(
            valid_lbe_input(), replace(context(detailed_artifact), surface_catalog=catalog)
        )

    raw = valid_lbe_input()
    raw["source"]["source_id"] = "../source"
    with pytest.raises(ValueError, match="safe identifier token"):
        LbeSegmentProvider().normalize(raw)


@pytest.mark.parametrize(
    ("catalog_key", "forged_value", "message"),
    [
        ("centroid_m", [999.0, 999.0, 999.0], "centroid"),
        ("normal", [1.0, 0.0, 0.0], "normal"),
    ],
)
def test_lbe_recomputes_catalog_geometry_from_artifact_mesh(
    detailed_artifact, catalog_key, forged_value, message
):
    catalog = copy.deepcopy(detailed_artifact.surface_catalog)
    catalog["exterior_surfaces"][0][catalog_key] = forged_value
    forged_artifact = replace(detailed_artifact, surface_catalog=catalog)

    with pytest.raises(ValueError, match=message):
        LbeSegmentProvider().compile(valid_lbe_input(), context(forged_artifact))


def test_duplicate_catalog_surface_ids_fail_closed_before_budgeting(detailed_artifact):
    catalog = copy.deepcopy(detailed_artifact.surface_catalog)
    catalog["exterior_surfaces"].append(copy.deepcopy(catalog["exterior_surfaces"][0]))
    duplicate_artifact = replace(detailed_artifact, surface_catalog=catalog)

    with pytest.raises(ValueError, match="duplicate.*face id"):
        LbeSegmentProvider().compile(valid_lbe_input(), context(duplicate_artifact))


def test_lbe_fragment_is_deeply_immutable(detailed_artifact):
    fragment = LbeSegmentProvider().compile(valid_lbe_input(), context(detailed_artifact))
    with pytest.raises(TypeError):
        fragment.manifest["solver_ready"] = True
    with pytest.raises(TypeError):
        fragment.evidence[0].claims["changed"] = True
    with pytest.raises(FrozenInstanceError):
        fragment.provider_id = "changed"


def test_lbe_estimate_counts_only_fragment_elements_not_target_surface_faces(detailed_artifact):
    provider = LbeSegmentProvider()
    raw = valid_lbe_input()
    provider_context = context(detailed_artifact)

    estimate = provider.estimate(raw, provider_context)
    fragment = provider.compile(raw, provider_context)

    assert estimate.element_count == len(fragment.element_ids) == 0
    assert fragment.manifest["allocation"]["actual_element_count"] == 0
    assert fragment.manifest["allocation"]["actual_target_surface_count"] == len(
        fragment.fsi_face_ids
    )
