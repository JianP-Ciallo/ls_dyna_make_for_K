from __future__ import annotations

import copy
import math
from dataclasses import FrozenInstanceError, replace

import pytest

from lsprepost_mcp.refined_blast import get_load_provider
from lsprepost_mcp.refined_blast.providers import (
    ExplicitAleFsiProvider,
    LbeSegmentProvider,
    ProviderContext,
    ProviderFragment,
    ProviderTopology,
    TopologyOpening,
    TopologyRegion,
)
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


def scenario_context(artifact, *, kind: str) -> ProviderContext:
    return ProviderContext.from_artifact(
        artifact,
        scenario_kind=kind,
        available_ids={
            "resource:neutral-air@1.0.0",
            "resource:neutral-tnt@1.0.0",
            "resource:neutral-eos@1.0.0",
            "resource:neutral-ale-keywords@1.0.0",
        },
    )


def resource_ref(resource_id: str) -> dict[str, object]:
    return {"resource_id": resource_id, "version": "1.0.0"}


def valid_explicit_input(kind: str) -> dict[str, object]:
    position = [-1.0, 3.0, 1.5] if kind == "external" else [3.0, 3.0, 1.5]
    category = "exterior_surfaces" if kind == "external" else "interior_cavity_surfaces"
    return {
        "schema_version": "explicit_ale_fsi@1",
        "unit_system": "SI_m_s_kg_N_Pa",
        "charge": {
            "schema_version": "explicit_ale_fsi.charge@1",
            "source_id": "charge-1",
            "position_m": position,
            "tnt_equivalent_kg": 2.0,
            "detonation_time_s": 0.0,
        },
        "domain": {
            "schema_version": "explicit_ale_fsi.domain@1",
            "bounds_m": [-3.0, -2.0, -1.0, 9.0, 8.0, 5.0],
            "target_cell_size_m": 2.0,
            "minimum_margin_m": 1.0,
            "external_buffer_m": 0.5,
        },
        "fsi": {
            "schema_version": "explicit_ale_fsi.fsi@1",
            "surface_categories": [category],
            "coupling_mode": "constrained_lagrange_in_solid",
        },
        "resources": {
            "schema_version": "explicit_ale_fsi.resources@1",
            "air_material": resource_ref("neutral-air"),
            "explosive_material": resource_ref("neutral-tnt"),
            "equation_of_state": resource_ref("neutral-eos"),
            "ale_keyword": resource_ref("neutral-ale-keywords"),
        },
        "budgets": {
            "schema_version": "explicit_ale_fsi.budgets@1",
            "max_axis_points": 20,
            "max_node_count": 1_000,
            "max_element_count": 1_000,
        },
    }


@pytest.mark.parametrize("kind", ["external", "internal", "semi_enclosed"])
def test_explicit_provider_compiles_minimal_kind(kind, detailed_artifact):
    context = scenario_context(detailed_artifact, kind=kind)
    fragment = ExplicitAleFsiProvider().compile(valid_explicit_input(kind), context)

    assert isinstance(fragment, ProviderFragment)
    assert fragment.provider_id == "explicit_ale_fsi"
    assert fragment.manifest["solver_ready"] is False
    assert fragment.manifest["requires_project_review"] is True
    assert fragment.manifest["engineering_validated"] is False
    assert fragment.required_ids <= context.available_ids | fragment.declared_ids
    assert fragment.manifest["allocation"]["estimate_matches_actual"] is True
    assert fragment.manifest["allocation"]["budget_checked_before_allocation"] is True

    source_space = next(
        row for row in fragment.evidence if row.evidence_kind == "provider_source_space"
    )
    assert source_space.claims["source_space_id"] == (
        "exterior" if kind == "external" else "room_1"
    )
    assert source_space.claims["source_declared_id"] == "charge:charge-1"


def test_provider_is_bound_only_when_real_provider_package_is_imported():
    assert isinstance(get_load_provider("explicit_ale_fsi"), ExplicitAleFsiProvider)
    assert isinstance(get_load_provider("lbe_segment"), LbeSegmentProvider)
    assert get_load_provider("imported_pressure_history").provider_id == "imported_pressure_history"


def test_normalizer_is_closed_versioned_unit_aware_and_deeply_immutable():
    provider = ExplicitAleFsiProvider()
    raw = valid_explicit_input("external")
    raw["legacy_option"] = True
    with pytest.raises(ValueError, match="unknown field"):
        provider.normalize(raw)

    raw = valid_explicit_input("external")
    raw["charge"]["legacy_option"] = True
    with pytest.raises(ValueError, match="charge.*unknown field"):
        provider.normalize(raw)

    raw = valid_explicit_input("external")
    raw["unit_system"] = "mm_ms_kg"
    with pytest.raises(ValueError, match="unit_system"):
        provider.normalize(raw)

    normalized = provider.normalize(valid_explicit_input("external"))
    with pytest.raises(TypeError):
        normalized["charge"]["source_id"] = "changed"


def test_manual_topology_view_copies_mutable_inputs_into_immutable_tuples():
    envelope = [0.0, 0.0, 0.0, 6.0, 6.0, 3.0]
    space_bounds = [0.25, 0.25, 0.25, 5.75, 5.75, 2.75]
    opening_bounds = [0.0, 2.5, 0.25, 0.25, 3.5, 2.25]
    topology = ProviderTopology(
        envelope_bounds_m=envelope,  # type: ignore[arg-type]
        spaces=(TopologyRegion("room_1", space_bounds),),  # type: ignore[arg-type]
        openings=(
            TopologyOpening(
                "door_external",
                opening_bounds,  # type: ignore[arg-type]
                ["room_1", "exterior"],  # type: ignore[arg-type]
            ),
        ),
        fingerprint="a" * 64,
    )

    envelope[0] = -10.0
    space_bounds[0] = -10.0
    opening_bounds[0] = -10.0
    assert topology.envelope_bounds_m[0] == 0.0
    assert topology.spaces[0].bounds_m[0] == 0.25
    assert topology.openings[0].bounds_m[0] == 0.0
    assert topology.openings[0].connects == ("room_1", "exterior")


@pytest.mark.parametrize(
    ("path", "bad_value"),
    [
        (("charge", "position_m"), [math.nan, 3.0, 1.5]),
        (("charge", "tnt_equivalent_kg"), math.inf),
        (("domain", "target_cell_size_m"), math.nan),
        (("domain", "minimum_margin_m"), True),
    ],
)
def test_non_finite_and_bool_numeric_values_are_rejected(path, bad_value):
    raw = valid_explicit_input("external")
    raw[path[0]][path[1]] = bad_value
    with pytest.raises(ValueError, match="finite number"):
        ExplicitAleFsiProvider().normalize(raw)


def test_source_must_be_inside_fluid_domain(detailed_artifact):
    raw = valid_explicit_input("external")
    raw["domain"]["bounds_m"] = [0.0, 0.0, 0.0, 9.0, 8.0, 5.0]
    with pytest.raises(ValueError, match="outside fluid domain"):
        ExplicitAleFsiProvider().compile(
            raw, scenario_context(detailed_artifact, kind="external")
        )


def test_source_cannot_have_positive_volume_structural_overlap(detailed_artifact):
    raw = valid_explicit_input("external")
    raw["charge"]["position_m"] = [0.125, 0.125, 1.0]
    with pytest.raises(ValueError, match="structural overlap"):
        ExplicitAleFsiProvider().compile(
            raw, scenario_context(detailed_artifact, kind="external")
        )


def test_detonation_point_must_match_real_scenario_containment(detailed_artifact):
    raw = valid_explicit_input("internal")
    raw["charge"]["position_m"] = [-1.0, 3.0, 1.5]
    with pytest.raises(ValueError, match="internal.*space"):
        ExplicitAleFsiProvider().compile(
            raw, scenario_context(detailed_artifact, kind="internal")
        )


def test_domain_enforces_minimum_margin(detailed_artifact):
    raw = valid_explicit_input("external")
    raw["domain"]["bounds_m"] = [-1.5, -2.0, -1.0, 9.0, 8.0, 5.0]
    with pytest.raises(ValueError, match="minimum margin"):
        ExplicitAleFsiProvider().compile(
            raw, scenario_context(detailed_artifact, kind="external")
        )


def test_fsi_faces_must_come_from_kind_appropriate_classified_catalog(detailed_artifact):
    raw = valid_explicit_input("external")
    raw["fsi"]["surface_categories"] = ["interior_cavity_surfaces"]
    with pytest.raises(ValueError, match="FSI surface category"):
        ExplicitAleFsiProvider().compile(
            raw, scenario_context(detailed_artifact, kind="external")
        )


def test_fsi_catalog_rows_must_explicitly_identify_structural_faces(detailed_artifact):
    context = scenario_context(detailed_artifact, kind="external")
    malformed_catalog = dict(context.surface_catalog)
    malformed_catalog["exterior_surfaces"] = [
        {"face_id": "fabricated:face", "unexpected": "not-an-element"}
    ]
    malformed = replace(
        context,
        surface_catalog=malformed_catalog,
        available_ids=context.available_ids | {"surface:fabricated:face"},
    )

    with pytest.raises(ValueError, match="not a structural face"):
        ExplicitAleFsiProvider().compile(valid_explicit_input("external"), malformed)


def test_fsi_catalog_rows_cannot_be_forged_and_must_be_inside_fluid_domain(
    detailed_artifact,
):
    context = scenario_context(detailed_artifact, kind="external")
    catalog = dict(context.surface_catalog)
    rows = [dict(row) for row in catalog["exterior_surfaces"]]
    rows[0]["element_id"] = rows[-1]["element_id"]
    catalog["exterior_surfaces"] = rows
    forged = replace(context, surface_catalog=catalog)
    with pytest.raises(ValueError, match="does not match artifact surface catalog"):
        ExplicitAleFsiProvider().compile(valid_explicit_input("external"), forged)

    raw = valid_explicit_input("external")
    raw["domain"]["bounds_m"] = [-3.0, 2.0, 0.0, 0.1, 4.0, 3.0]
    with pytest.raises(ValueError, match="outside fluid domain"):
        ExplicitAleFsiProvider().compile(raw, context)


def test_versioned_neutral_resources_are_external_required_ids(detailed_artifact):
    context = scenario_context(detailed_artifact, kind="external")
    raw = valid_explicit_input("external")
    raw["resources"]["air_material"] = resource_ref("missing-air")
    with pytest.raises(ValueError, match="resource.*unavailable"):
        ExplicitAleFsiProvider().compile(raw, context)

    fragment = ExplicitAleFsiProvider().compile(
        valid_explicit_input("external"), context
    )
    resource_ids = {
        value for value in fragment.required_ids if value.startswith("resource:")
    }
    assert len(resource_ids) == 4
    assert not resource_ids & fragment.declared_ids


def test_semi_enclosed_requires_proven_open_passage_and_external_buffer(detailed_artifact):
    context = scenario_context(detailed_artifact, kind="semi_enclosed")
    without_openings = replace(context, topology=replace(context.topology, openings=()))
    with pytest.raises(ValueError, match="open passage"):
        ExplicitAleFsiProvider().compile(
            valid_explicit_input("semi_enclosed"), without_openings
        )

    raw = valid_explicit_input("semi_enclosed")
    raw["domain"]["bounds_m"] = [0.0, -2.0, -1.0, 9.0, 8.0, 5.0]
    with pytest.raises(ValueError, match="external buffer"):
        ExplicitAleFsiProvider().compile(raw, context)

    raw = valid_explicit_input("semi_enclosed")
    raw["charge"]["position_m"] = [3.0, 5.0, 1.5]
    raw["domain"]["bounds_m"] = [-1.0, 4.0, 0.0, 4.0, 6.0, 3.0]
    with pytest.raises(ValueError, match="open passage.*fluid domain"):
        ExplicitAleFsiProvider().compile(raw, context)


def test_semi_enclosed_accepts_any_complete_passage_inside_domain(detailed_artifact):
    base = scenario_context(detailed_artifact, kind="semi_enclosed")
    nodes = {node.node_id: node for node in detailed_artifact.mesh.nodes}
    candidate = next(
        row
        for row in base.surface_catalog["interior_cavity_surfaces"]
        if all(
            nodes[node_id].x <= 4.0 and nodes[node_id].y >= 3.5
            for node_id in row["node_ids"]
        )
    )
    catalog = dict(base.surface_catalog)
    catalog["interior_cavity_surfaces"] = [candidate]
    topology = replace(
        base.topology,
        openings=(
            TopologyOpening(
                "a_excluded",
                (0.0, 0.25, 0.25, 0.25, 1.0, 2.25),
                ("room_1", "exterior"),
            ),
            TopologyOpening(
                "z_included",
                (0.0, 4.0, 0.25, 0.25, 5.0, 2.25),
                ("room_1", "exterior"),
            ),
        ),
    )
    context = replace(base, surface_catalog=catalog, topology=topology)
    raw = valid_explicit_input("semi_enclosed")
    raw["charge"]["position_m"] = [3.0, 5.0, 1.5]
    raw["domain"]["bounds_m"] = [-1.0, 3.5, 0.0, 4.0, 6.0, 3.0]

    fragment = ExplicitAleFsiProvider().compile(raw, context)

    assert fragment.evidence[0].claims["external_opening_ids"] == ("z_included",)


def test_element_budgets_are_checked_before_any_axis_or_mesh_allocation(detailed_artifact):
    raw = valid_explicit_input("external")
    raw["domain"]["bounds_m"] = [-1.0e9, -1.0e9, -1.0e9, 1.0e9, 1.0e9, 1.0e9]
    raw["domain"]["target_cell_size_m"] = 1.0e-3
    raw["budgets"] = {
        "schema_version": "explicit_ale_fsi.budgets@1",
        "max_axis_points": 20,
        "max_node_count": 1_000,
        "max_element_count": 1_000,
    }
    with pytest.raises(ValueError, match="axis point budget"):
        ExplicitAleFsiProvider().compile(
            raw, scenario_context(detailed_artifact, kind="external")
        )


@pytest.mark.parametrize(
    ("budget_key", "budget_value", "message"),
    [
        ("max_axis_points", 2, "axis point budget"),
        ("max_node_count", 100, "node budget"),
        ("max_element_count", 50, "element budget"),
    ],
)
def test_validate_returns_blocking_finding_for_every_preallocation_budget(
    detailed_artifact, budget_key, budget_value, message
):
    raw = valid_explicit_input("external")
    raw["budgets"][budget_key] = budget_value

    findings = ExplicitAleFsiProvider().validate(
        raw, scenario_context(detailed_artifact, kind="external")
    )

    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert message in findings[0].message


def test_validate_converts_finite_axis_division_overflow_to_budget_finding(
    detailed_artifact,
):
    raw = valid_explicit_input("external")
    raw["domain"]["bounds_m"] = [-1.0e308, -1.0e308, -1.0e308, 1.0e308, 1.0e308, 1.0e308]
    raw["domain"]["target_cell_size_m"] = 1.0e-308

    findings = ExplicitAleFsiProvider().validate(
        raw, scenario_context(detailed_artifact, kind="external")
    )

    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert "axis point budget" in findings[0].message
    with pytest.raises(ValueError, match="axis point budget"):
        ExplicitAleFsiProvider().compile(
            raw, scenario_context(detailed_artifact, kind="external")
        )


def test_surface_geometry_is_recomputed_from_mesh_and_rejects_catalog_forgeries(
    detailed_artifact,
):
    catalog = copy.deepcopy(detailed_artifact.surface_catalog)
    row = catalog["exterior_surfaces"][0]
    row["centroid_m"] = [999.0, 999.0, 999.0]
    row["normal"] = [1.0, 0.0, 0.0]
    forged_artifact = replace(detailed_artifact, surface_catalog=catalog)

    with pytest.raises(ValueError, match="centroid|normal"):
        ExplicitAleFsiProvider().compile(
            valid_explicit_input("external"),
            scenario_context(forged_artifact, kind="external"),
        )


def test_surface_geometry_rejects_zero_area_mesh_face(detailed_artifact):
    first_face = detailed_artifact.surface_catalog["exterior_surfaces"][0]
    face_node_ids = set(first_face["node_ids"])
    anchor = next(node for node in detailed_artifact.mesh.nodes if node.node_id in face_node_ids)
    collapsed_nodes = tuple(
        replace(node, x=anchor.x, y=anchor.y, z=anchor.z)
        if node.node_id in face_node_ids
        else node
        for node in detailed_artifact.mesh.nodes
    )
    collapsed_artifact = replace(
        detailed_artifact,
        mesh=replace(detailed_artifact.mesh, nodes=collapsed_nodes),
    )

    with pytest.raises(ValueError, match="positive area"):
        ExplicitAleFsiProvider().compile(
            valid_explicit_input("external"),
            scenario_context(collapsed_artifact, kind="external"),
        )


def test_semi_enclosed_buffer_uses_only_terminal_exterior_opening(detailed_artifact):
    base = scenario_context(detailed_artifact, kind="semi_enclosed")
    topology = replace(
        base.topology,
        spaces=(
            *base.topology.spaces,
            TopologyRegion("room_2", (0.25, 0.25, 0.25, 1.0, 1.0, 1.0)),
        ),
        openings=(
            TopologyOpening(
                "internal_on_envelope",
                (0.0, 2.5, 0.25, 0.25, 3.5, 2.25),
                ("room_1", "room_2"),
            ),
            TopologyOpening(
                "terminal_not_on_envelope",
                (2.0, 2.0, 0.5, 2.5, 2.5, 1.5),
                ("room_2", "exterior"),
            ),
        ),
    )

    with pytest.raises(ValueError, match="terminal exterior opening.*envelope"):
        ExplicitAleFsiProvider().compile(
            valid_explicit_input("semi_enclosed"),
            replace(base, topology=topology),
        )


def test_semi_enclosed_terminal_opening_may_straddle_envelope_face(detailed_artifact):
    base = scenario_context(detailed_artifact, kind="semi_enclosed")
    straddling = TopologyOpening(
        "straddling_exit",
        (-0.1, 2.5, 0.25, 0.25, 3.5, 2.25),
        ("room_1", "exterior"),
    )
    context = replace(
        base,
        topology=replace(base.topology, openings=(straddling,)),
    )

    fragment = ExplicitAleFsiProvider().compile(
        valid_explicit_input("semi_enclosed"), context
    )

    assert fragment.evidence[0].claims["external_opening_ids"] == (
        "straddling_exit",
    )


@pytest.mark.parametrize(
    ("field_path", "token"),
    [
        (("charge", "source_id"), "../charge"),
        (("charge", "source_id"), "bad:charge"),
        (("charge", "source_id"), " charge-1 "),
        (("resources", "air_material", "resource_id"), "bad\\resource"),
        (("resources", "ale_keyword", "resource_id"), "bad resource"),
        (("resources", "equation_of_state", "version"), "1.0\n2"),
        (("resources", "explosive_material", "version"), ".."),
    ],
)
def test_user_tokens_entering_fragment_ids_must_be_safe(field_path, token):
    raw = valid_explicit_input("external")
    target = raw
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = token

    with pytest.raises(ValueError, match="safe identifier token"):
        ExplicitAleFsiProvider().normalize(raw)


def test_fragment_evidence_and_preview_are_deeply_immutable_and_deterministic(
    detailed_artifact,
):
    provider = ExplicitAleFsiProvider()
    context = scenario_context(detailed_artifact, kind="external")
    before = detailed_artifact.fingerprint
    first = provider.compile(valid_explicit_input("external"), context)
    second = provider.compile(valid_explicit_input("external"), context)

    assert first.fingerprint == second.fingerprint
    assert tuple(row.evidence_id for row in first.evidence) == tuple(
        row.evidence_id for row in second.evidence
    )
    evidence_ids = {row.evidence_id for row in first.evidence}
    evidence_sources = {
        source_id for row in first.evidence for source_id in row.source_ids
    }
    assert evidence_ids <= first.declared_ids
    assert evidence_sources <= context.available_ids | first.declared_ids
    assert first.manifest["id_closure"]["closed"] is True
    assert detailed_artifact.fingerprint == before
    with pytest.raises(TypeError):
        first.manifest["solver_ready"] = True
    with pytest.raises(TypeError):
        first.evidence[0].claims["verified"] = True
    with pytest.raises(FrozenInstanceError):
        first.provider_id = "changed"

    preview = provider.preview(valid_explicit_input("external"), context)
    assert preview["software_candidate_only"] is True
    with pytest.raises(TypeError):
        preview["software_candidate_only"] = False
