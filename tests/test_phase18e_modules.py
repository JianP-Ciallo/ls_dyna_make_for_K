from __future__ import annotations

import copy
import json
from dataclasses import replace
from types import MappingProxyType

import pytest

from lsprepost_mcp.refined_blast.contracts import ScenarioDraft, normalize_scenario_draft
from lsprepost_mcp.refined_blast.providers import (
    ProviderContext,
    ProviderEvidence,
    ProviderFragment,
)
from lsprepost_mcp.refined_blast.providers.common import thaw_value
from lsprepost_mcp.refined_blast.fragments import ScenarioModuleContext
from lsprepost_mcp.refined_building.compiler import compile_refined_building
from lsprepost_mcp.refined_building.contracts import default_building_definition


def _frozen(value: object) -> MappingProxyType:
    assert isinstance(value, dict)
    return MappingProxyType(value)


@pytest.fixture()
def detailed_artifact():
    value = default_building_definition(structural_system="rc_box")
    value["spaces"] = [
        {
            "id": "sales_hall",
            "level_id": "level_1",
            "kind": "room",
            "bounds_m": [0.25, 0.25, 0.25, 2.9, 5.75, 2.75],
        },
        {
            "id": "back_room",
            "level_id": "level_1",
            "kind": "room",
            "bounds_m": [3.1, 0.25, 0.25, 5.75, 5.75, 2.75],
        },
    ]
    value["openings"] = [
        {
            "id": "door_hall_back",
            "kind": "door",
            "bounds_m": [2.9, 2.5, 0.25, 3.1, 3.5, 2.25],
            "connects": ["sales_hall", "back_room"],
        },
        {
            "id": "vent_back_outside",
            "kind": "vent",
            "bounds_m": [5.75, 2.5, 1.0, 6.0, 3.0, 2.0],
            "connects": ["back_room", "exterior"],
        },
    ]
    value["structural_system"]["parameters"] = {
        "generation_mode": "concrete_only",
        "box_thickness_m": 0.25,
        "mesh_size_m": 0.5,
    }
    return compile_refined_building(value)


def _draft(kind: str = "internal", module_inputs: dict[str, object] | None = None) -> ScenarioDraft:
    inputs = copy.deepcopy(module_inputs or {})
    if inputs.get("fluid_domain") and not inputs.get("blast_source"):
        inputs["blast_source"] = {
            "schema_version": "refined_blast.blast_source@1",
            "source_declared_id": "charge:source-1",
            "source_space_id": "sales_hall" if kind != "external" else "exterior",
        }
    for value in inputs.values():
        if isinstance(value, dict) and value:
            value.setdefault("unit_system", "SI_m_s_kg_N_Pa")
            value.setdefault(
                "budgets",
                {
                    "schema_version": "refined_blast.module_budgets@1",
                    "max_new_nodes": 100_000,
                    "max_new_elements": 100_000,
                },
            )
    return normalize_scenario_draft(
        {
            "scenario_id": "scenario-1",
            "scenario_kind": kind,
            "building_placement": inputs.get("placement", {}),
            "support_and_ground": inputs.get("support_ground", {}),
            "load_provider": {"provider_id": "explicit_ale_fsi", "provider_input": _explicit_input(kind)},
            "blast_source": inputs.get("blast_source", {}),
            "fluid_domain": inputs.get("fluid_domain", {}),
            "boundaries": inputs.get("boundaries", {}),
            "interactions": inputs.get("interactions", {}),
            "solver_controls": {},
            "output_requests": {},
            "resource_versions": {},
            "acknowledged_warning_ids": [],
        }
    )


def _explicit_input(kind: str) -> dict[str, object]:
    position = [-1.0, 3.0, 1.5] if kind == "external" else [1.0, 3.0, 1.5]
    category = "exterior_surfaces" if kind == "external" else "interior_cavity_surfaces"
    ref = lambda resource_id: {"resource_id": resource_id, "version": "1.0.0"}
    return {
        "schema_version": "explicit_ale_fsi@1", "unit_system": "SI_m_s_kg_N_Pa",
        "charge": {"schema_version": "explicit_ale_fsi.charge@1", "source_id": "source-1", "position_m": position, "tnt_equivalent_kg": 2.0, "detonation_time_s": 0.0},
        "domain": {"schema_version": "explicit_ale_fsi.domain@1", "bounds_m": [-3.0, -2.0, -1.0, 9.0, 8.0, 5.0], "target_cell_size_m": 2.0, "minimum_margin_m": 1.0, "external_buffer_m": 0.5},
        "fsi": {"schema_version": "explicit_ale_fsi.fsi@1", "surface_categories": [category], "coupling_mode": "constrained_lagrange_in_solid"},
        "resources": {"schema_version": "explicit_ale_fsi.resources@1", "air_material": ref("neutral-air"), "explosive_material": ref("neutral-tnt"), "equation_of_state": ref("neutral-eos"), "ale_keyword": ref("neutral-ale-keywords")},
        "budgets": {"schema_version": "explicit_ale_fsi.budgets@1", "max_axis_points": 20, "max_node_count": 1000, "max_element_count": 1000},
    }


def _provider_fragment(artifact, kind: str = "internal") -> ProviderFragment:
    from lsprepost_mcp.refined_blast.providers.explicit_ale_fsi import ExplicitAleFsiProvider

    return ProviderFragment(
        provider_id="explicit_ale_fsi",
        normalized_input=ExplicitAleFsiProvider().normalize(_explicit_input(kind)),
        axes_m=((), (), ()),
        node_ids=(),
        element_ids=(),
        fsi_face_ids=(
            artifact.surface_catalog[
                "exterior_surfaces" if kind == "external" else "interior_cavity_surfaces"
            ][0]["face_id"],
        ),
        required_ids=frozenset(),
        declared_ids=frozenset({"charge:source-1", "provider:explicit_ale_fsi"}),
        evidence=(
            ProviderEvidence(
                evidence_id="source-evidence",
                evidence_kind="provider_source_space",
                source_ids=(
                    f"artifact:{artifact.fingerprint}",
                    f"topology:{artifact.topology_manifest['fingerprint']}",
                    "charge:source-1",
                ),
                claims=_frozen(
                    {
                        "schema_version": "provider_source_space_evidence@1",
                        "provider_id": "explicit_ale_fsi",
                        "source_declared_id": "charge:source-1",
                        "source_space_id": "sales_hall" if kind != "external" else "exterior",
                        "scenario_kind": kind,
                        "topology_fingerprint": artifact.topology_manifest["fingerprint"],
                        "determination": "verified_position_containment",
                        "surface_category": None,
                        "external_opening_ids": (),
                    }
                ),
            ),
        ),
        manifest=_frozen(
            {
                "provider_id": "explicit_ale_fsi",
                "scenario_kind": kind,
                "building_artifact_fingerprint": artifact.fingerprint,
                "solver_ready": False,
                "requires_project_review": True,
                "engineering_validated": False,
            }
        ),
    )


def module_context(artifact, *, kind: str = "internal", module_inputs: dict[str, object] | None = None):
    from lsprepost_mcp.refined_blast.fragments import ScenarioModuleContext

    module_inputs = dict(module_inputs or {})
    if "fluid_domain" in module_inputs and "placement" not in module_inputs:
        module_inputs["placement"] = {
            "schema_version": "refined_blast.placement@1",
            "building_count": 1,
            "translation_m": [0.0, 0.0, 0.0],
        }

    return ScenarioModuleContext.from_draft(
        _draft(kind, module_inputs),
        ProviderContext.from_artifact(artifact, scenario_kind=kind),
        _provider_fragment(artifact, kind),
    )


def fluid_with_placement(context):
    from lsprepost_mcp.refined_blast.fluid_domain import FluidDomainCompiler
    from lsprepost_mcp.refined_blast.placement import PlacementCompiler

    placement = PlacementCompiler().compile(context)
    return FluidDomainCompiler().compile(context.with_prior_fragments(placement))


def with_module_input(context, name: str, value: dict[str, object]):
    raw = {
        "placement": thaw_value(context.draft.building_placement),
        "support_ground": thaw_value(context.draft.support_and_ground),
        "blast_source": thaw_value(context.draft.blast_source),
        "fluid_domain": thaw_value(context.draft.fluid_domain),
        "boundaries": thaw_value(context.draft.boundaries),
        "interactions": thaw_value(context.draft.interactions),
    }
    raw[name] = value
    return ScenarioModuleContext.from_draft(
        _draft(context.draft.scenario_kind, raw),
        context.provider_context,
        context.provider_fragment,
    ).with_prior_fragments(*context.prior_fragments)


def test_module_imports_are_initially_missing():
    from lsprepost_mcp.refined_blast import placement

    assert placement is not None


def test_placement_rejects_multi_building_and_is_deterministic(detailed_artifact):
    from lsprepost_mcp.refined_blast.placement import PlacementCompiler

    context = module_context(
        detailed_artifact,
        module_inputs={
            "placement": {
                "schema_version": "refined_blast.placement@1",
                "building_count": 1,
                "translation_m": [0.0, 0.0, 0.0],
            }
        },
    )
    first = PlacementCompiler().compile(context)
    second = PlacementCompiler().compile(context)
    assert first.fingerprint == second.fingerprint
    assert first.declared_ids == frozenset(
        {
            "placement:scenario-1",
            "building:scenario-1",
            "building_surface:scenario-1:exterior",
            "building_surface:scenario-1:ground_contact",
            "building_surface:scenario-1:interior",
            "building_surface:scenario-1:unclassified",
        }
    )

    with pytest.raises(ValueError, match="building_count must be exactly 1"):
        with_module_input(
            context,
            "placement",
            {
                "schema_version": "refined_blast.placement@1",
                "building_count": 2,
                "translation_m": [0.0, 0.0, 0.0],
            },
        )
    with pytest.raises(ValueError, match="zero translation"):
        PlacementCompiler().compile(
            with_module_input(
                context,
                "placement",
                {
                    "schema_version": "refined_blast.placement@1",
                    "building_count": 1,
                    "translation_m": [0.1, 0.0, 0.0],
                },
            )
        )


def test_support_requires_real_foundation_face_and_declares_shared_node_semantics(detailed_artifact):
    from lsprepost_mcp.refined_blast.placement import PlacementCompiler
    from lsprepost_mcp.refined_blast.support_ground import SupportGroundCompiler

    face_id = detailed_artifact.surface_catalog["ground_contact_surfaces"][0]["face_id"]
    context = module_context(
        detailed_artifact,
        module_inputs={
            "placement": {
                "schema_version": "refined_blast.placement@1",
                "building_count": 1,
                "translation_m": [0.0, 0.0, 0.0],
            },
            "support_ground": {
                "schema_version": "refined_blast.support_ground@1",
                "support_face_ids": [face_id],
                "coupling_semantics": "shared_node",
            }
        },
    )
    placement = PlacementCompiler().compile(context)
    context = context.with_prior_fragments(placement)
    result = SupportGroundCompiler().compile(context)
    assert result.manifest["coupling_semantics"] == "shared_node"
    assert f"surface:{face_id}" in result.required_ids
    interface = result.interfaces[0]
    assert interface.kind == "support_shared_node"
    assert interface.source_participant_id == "support:scenario-1"
    assert interface.target_participant_id == "building:scenario-1"
    expected_shared = tuple(
        f"building:node:{node_id}"
        for node_id in detailed_artifact.surface_catalog["ground_contact_surfaces"][0]["node_ids"]
    )
    assert set(interface.shared_node_ids) == set(expected_shared)
    geometry = result.manifest["ground_geometry"]
    assert len(geometry["nodes"]) == result.estimates["new_nodes"] == 4
    assert len(geometry["elements"]) == result.estimates["new_elements"] == 1
    assert all(row["coordinates_m"][2] < 0.0 for row in geometry["nodes"])

    bad = with_module_input(context,
        "support_ground",
        {
            "schema_version": "refined_blast.support_ground@1",
            "support_face_ids": ["not-a-foundation"],
            "coupling_semantics": "tied",
        },
    )
    with pytest.raises(ValueError, match="foundation"):
        SupportGroundCompiler().compile(bad)


def test_tied_ground_has_distinct_coincident_top_nodes_and_directed_master_slave_faces(
    detailed_artifact,
):
    from lsprepost_mcp.refined_blast.placement import PlacementCompiler
    from lsprepost_mcp.refined_blast.support_ground import SupportGroundCompiler

    face = detailed_artifact.surface_catalog["ground_contact_surfaces"][0]
    context = module_context(
        detailed_artifact,
        module_inputs={
            "placement": {
                "schema_version": "refined_blast.placement@1",
                "building_count": 1,
                "translation_m": [0.0, 0.0, 0.0],
            },
            "support_ground": {
                "schema_version": "refined_blast.support_ground@1",
                "support_face_ids": [face["face_id"]],
                "coupling_semantics": "tied",
            },
        },
    )
    placement = PlacementCompiler().compile(context)
    result = SupportGroundCompiler().compile(context.with_prior_fragments(placement))
    relation = result.interfaces[0]
    geometry = result.manifest["ground_geometry"]

    assert relation.kind == "support_tied"
    assert relation.master_member_ids == (f"surface:{face['face_id']}",)
    assert len(relation.slave_member_ids) == 1
    assert len(geometry["nodes"]) == result.estimates["new_nodes"] == 8
    top = [row for row in geometry["nodes"] if row["layer"] == "top"]
    bottom = [row for row in geometry["nodes"] if row["layer"] == "bottom"]
    structural = {
        node.node_id: node.coordinates
        for node in detailed_artifact.mesh.nodes
        if node.node_id in face["node_ids"]
    }
    assert {tuple(row["coordinates_m"]) for row in top} == set(structural.values())
    assert all(row["node_id"].startswith("ground:scenario-1:node:top:") for row in top)
    assert all(row["coordinates_m"][2] < 0.0 for row in bottom)


@pytest.mark.parametrize("semantics", ["shared_node", "tied"])
@pytest.mark.parametrize("reverse_foundation_orientation", [False, True])
def test_ground_solids_have_positive_corner_jacobians_for_real_foundation_orientations(
    detailed_artifact, semantics, reverse_foundation_orientation
):
    from lsprepost_mcp.refined_blast.placement import PlacementCompiler
    from lsprepost_mcp.refined_blast.support_ground import SupportGroundCompiler

    artifact = detailed_artifact
    if reverse_foundation_orientation:
        catalog = copy.deepcopy(artifact.surface_catalog)
        face = catalog["ground_contact_surfaces"][0]
        face["node_ids"] = tuple(reversed(face["node_ids"]))
        artifact = replace(artifact, surface_catalog=catalog)
    face = artifact.surface_catalog["ground_contact_surfaces"][0]
    context = module_context(
        artifact,
        module_inputs={
            "placement": {
                "schema_version": "refined_blast.placement@1",
                "building_count": 1,
                "translation_m": [0.0, 0.0, 0.0],
            },
            "support_ground": {
                "schema_version": "refined_blast.support_ground@1",
                "support_face_ids": [face["face_id"]],
                "coupling_semantics": semantics,
            },
        },
    )
    placement = PlacementCompiler().compile(context)
    support = SupportGroundCompiler().compile(context.with_prior_fragments(placement))
    geometry = support.manifest["ground_geometry"]
    coordinates = {
        f"building:node:{node.node_id}": node.coordinates for node in artifact.mesh.nodes
    }
    coordinates.update(
        {row["node_id"]: tuple(row["coordinates_m"]) for row in geometry["nodes"]}
    )

    for solid in geometry["elements"]:
        corner_determinants = _hex_corner_jacobian_determinants(
            tuple(coordinates[node_id] for node_id in solid["node_ids"])
        )
        assert min(corner_determinants) > 1.0e-12
        assert tuple(solid["corner_jacobians_m3"]) == pytest.approx(
            corner_determinants
        )


def test_ground_solid_fails_closed_when_no_positive_hex_orientation_exists(
    detailed_artifact,
):
    from lsprepost_mcp.refined_blast.placement import PlacementCompiler
    from lsprepost_mcp.refined_blast.support_ground import SupportGroundCompiler

    catalog = copy.deepcopy(detailed_artifact.surface_catalog)
    face = catalog["ground_contact_surfaces"][0]
    nodes = tuple(face["node_ids"])
    face["node_ids"] = (nodes[0], nodes[2], nodes[1], nodes[3])
    artifact = replace(detailed_artifact, surface_catalog=catalog)
    context = module_context(
        artifact,
        module_inputs={
            "placement": {
                "schema_version": "refined_blast.placement@1",
                "building_count": 1,
                "translation_m": [0.0, 0.0, 0.0],
            },
            "support_ground": {
                "schema_version": "refined_blast.support_ground@1",
                "support_face_ids": [face["face_id"]],
                "coupling_semantics": "shared_node",
            },
        },
    )
    placement = PlacementCompiler().compile(context)
    with pytest.raises(ValueError, match="positive Jacobian"):
        SupportGroundCompiler().compile(context.with_prior_fragments(placement))


def test_blast_source_is_evidence_bound_and_never_solver_ready(detailed_artifact):
    from lsprepost_mcp.refined_blast.blast_source import BlastSourceCompiler

    context = module_context(
        detailed_artifact,
        module_inputs={
            "blast_source": {
                "schema_version": "refined_blast.blast_source@1",
                "source_declared_id": "charge:source-1",
                "source_space_id": "sales_hall",
            }
        },
    )
    fragment = BlastSourceCompiler().compile(context)
    assert fragment.manifest["provider_id"] == "explicit_ale_fsi"
    assert context.provider_source_space_id == "sales_hall"
    assert fragment.manifest["solver_ready"] is False
    with pytest.raises(ValueError, match="declared provider source"):
        BlastSourceCompiler().compile(
            with_module_input(context,
                "blast_source",
                {"schema_version": "refined_blast.blast_source@1", "source_declared_id": "charge:invented", "source_space_id": "sales_hall"},
            )
        )
    with pytest.raises(ValueError, match="source space.*provider|provider.*source space"):
        BlastSourceCompiler().compile(
            with_module_input(
                context,
                "blast_source",
                {
                    "schema_version": "refined_blast.blast_source@1",
                    "source_declared_id": "charge:source-1",
                    "source_space_id": "back_room",
                },
            )
        )


def test_module_context_requires_one_closed_standardized_provider_source_claim(
    detailed_artifact,
):
    base = module_context(detailed_artifact)
    missing = replace(base.provider_fragment, evidence=())
    with pytest.raises(ValueError, match="provider source-space evidence"):
        replace(base, provider_fragment=missing)


def test_internal_domain_uses_opening_state_connectivity_without_solid_fill(detailed_artifact):
    from lsprepost_mcp.refined_blast.fluid_domain import FluidDomainCompiler

    context = module_context(
        detailed_artifact,
        module_inputs={
            "fluid_domain": {
                "schema_version": "refined_blast.fluid_domain@1",
                "source_space_id": "sales_hall",
                "opening_states": {"door_hall_back": "closed", "vent_back_outside": "closed"},
                "external_buffer_m": 0.0,
            }
        },
    )
    closed = fluid_with_placement(context)
    assert closed.manifest["included_space_ids"] == ("sales_hall",)
    assert "solid_envelope_fill" not in closed.manifest

    opened = fluid_with_placement(
        with_module_input(context,
            "fluid_domain",
            {
                "schema_version": "refined_blast.fluid_domain@1",
                "source_space_id": "sales_hall",
                "opening_states": {"door_hall_back": "open", "vent_back_outside": "closed"},
                "external_buffer_m": 0.0,
            },
        )
    )
    assert opened.manifest["included_space_ids"] == ("back_room", "sales_hall")
    with pytest.raises(ValueError, match="must not have an open path"):
        fluid_with_placement(
            with_module_input(
                context,
                "fluid_domain",
                {
                    "schema_version": "refined_blast.fluid_domain@1",
                    "source_space_id": "sales_hall",
                    "opening_states": {"door_hall_back": "open", "vent_back_outside": "open"},
                    "external_buffer_m": 0.0,
                },
            )
        )


def test_semi_enclosed_domain_requires_open_vent_path(detailed_artifact):
    from lsprepost_mcp.refined_blast.fluid_domain import FluidDomainCompiler

    context = module_context(
        detailed_artifact,
        kind="semi_enclosed",
        module_inputs={
            "fluid_domain": {
                "schema_version": "refined_blast.fluid_domain@1",
                "source_space_id": "sales_hall",
                "opening_states": {"door_hall_back": "open", "vent_back_outside": "open"},
                "external_buffer_m": 1.0,
            }
        },
    )
    fragment = fluid_with_placement(context)
    assert fragment.manifest["external_buffer_included"] is True
    assert fragment.manifest["vent_path_opening_ids"] == ("door_hall_back", "vent_back_outside")

    with pytest.raises(ValueError, match="open vent path"):
        fluid_with_placement(
            with_module_input(context,
                "fluid_domain",
                {
                    "schema_version": "refined_blast.fluid_domain@1",
                    "source_space_id": "sales_hall",
                    "opening_states": {"door_hall_back": "open", "vent_back_outside": "closed"},
                    "external_buffer_m": 1.0,
                },
            )
        )


def test_boundary_overlap_is_rejected_and_real_faces_are_closed(detailed_artifact):
    from lsprepost_mcp.refined_blast.boundaries import BoundaryCompiler
    from lsprepost_mcp.refined_blast.fluid_domain import FluidDomainCompiler
    from lsprepost_mcp.refined_blast.placement import PlacementCompiler

    face_id = detailed_artifact.surface_catalog["exterior_surfaces"][0]["face_id"]
    context = module_context(
        detailed_artifact,
        kind="external",
        module_inputs={
            "placement": {
                "schema_version": "refined_blast.placement@1",
                "building_count": 1,
                "translation_m": [0.0, 0.0, 0.0],
            },
            "fluid_domain": {
                "schema_version": "refined_blast.fluid_domain@1",
                "source_space_id": "exterior",
                "opening_states": {
                    "door_hall_back": "closed",
                    "vent_back_outside": "closed",
                },
                "external_buffer_m": 1.0,
            },
            "boundaries": {
                "schema_version": "refined_blast.boundaries@1",
                "assignments": [
                    {"boundary_id": "outflow-a", "face_id": face_id, "boundary_type": "non_reflecting"}
                ],
            }
        },
    )
    placement = PlacementCompiler().compile(context)
    fluid = FluidDomainCompiler().compile(context.with_prior_fragments(placement))
    context = context.with_prior_fragments(placement, fluid)
    assert BoundaryCompiler().compile(context).manifest["assignment_count"] == 1
    assert BoundaryCompiler().compile(context).interfaces[0].kind == "boundary_non_reflecting"
    with pytest.raises(ValueError, match="overlap"):
        BoundaryCompiler().compile(
            with_module_input(context,
                "boundaries",
                {
                    "schema_version": "refined_blast.boundaries@1",
                    "assignments": [
                        {"boundary_id": "outflow-a", "face_id": face_id, "boundary_type": "non_reflecting"},
                        {"boundary_id": "outflow-b", "face_id": face_id, "boundary_type": "rigid"},
                    ],
                },
            )
        )


def test_interactions_close_unique_pairs_and_reject_reversed_duplicates(detailed_artifact):
    from lsprepost_mcp.refined_blast.fluid_domain import FluidDomainCompiler
    from lsprepost_mcp.refined_blast.interactions import InteractionCompiler
    from lsprepost_mcp.refined_blast.placement import PlacementCompiler

    context = module_context(
        detailed_artifact,
        module_inputs={
            "placement": {
                "schema_version": "refined_blast.placement@1",
                "building_count": 1,
                "translation_m": [0.0, 0.0, 0.0],
            },
            "fluid_domain": {
                "schema_version": "refined_blast.fluid_domain@1",
                "source_space_id": "sales_hall",
                "opening_states": {"door_hall_back": "closed", "vent_back_outside": "closed"},
                "external_buffer_m": 0.0,
            },
            "interactions": {
                "schema_version": "refined_blast.interactions@1",
                "pairs": [
                    {
                        "interaction_id": "fsi-1",
                        "interaction_type": "fsi_candidate",
                        "source_id": "fluid:scenario-1",
                        "target_id": f"building:element:{detailed_artifact.mesh.solids[0].element_id}",
                    }
                ],
            }
        },
    )
    context = context.with_prior_fragments(
        PlacementCompiler().compile(context), fluid_with_placement(context)
    )
    interaction = InteractionCompiler().compile(context)
    assert interaction.manifest["pair_count"] == 1
    assert interaction.interfaces[0].kind == "fsi"
    assert interaction.interfaces[0].source_participant_id == "fluid:scenario-1"
    assert interaction.interfaces[0].target_participant_id == "building:scenario-1"
    with pytest.raises(ValueError, match="duplicate|reversed|requires"):
        InteractionCompiler().compile(
            with_module_input(context,
                "interactions",
                {
                    "schema_version": "refined_blast.interactions@1",
                    "pairs": [
                        {
                            "interaction_id": "fsi-1",
                            "interaction_type": "fsi_candidate",
                            "source_id": "fluid:scenario-1",
                            "target_id": f"building:element:{detailed_artifact.mesh.solids[0].element_id}",
                        },
                        {
                            "interaction_id": "fsi-2",
                            "interaction_type": "fsi_candidate",
                            "source_id": f"building:element:{detailed_artifact.mesh.solids[0].element_id}",
                            "target_id": "fluid:scenario-1",
                        },
                    ],
                },
            )
        )


def test_fsi_interaction_requires_compiled_fluid_and_structural_participants(detailed_artifact):
    from lsprepost_mcp.refined_blast.interactions import InteractionCompiler

    context = module_context(
        detailed_artifact,
        module_inputs={
            "interactions": {
                "schema_version": "refined_blast.interactions@1",
                "pairs": [
                    {
                        "interaction_id": "invalid-fsi",
                        "interaction_type": "fsi_candidate",
                        "source_id": "provider:explicit_ale_fsi",
                        "target_id": "building:element:1000",
                    }
                ],
            }
        },
    )
    with pytest.raises(ValueError, match="(?i)fluid.*participant"):
        InteractionCompiler().compile(context)


def test_tie_interaction_uses_the_compiled_support_participant(detailed_artifact):
    from lsprepost_mcp.refined_blast.interactions import InteractionCompiler
    from lsprepost_mcp.refined_blast.placement import PlacementCompiler
    from lsprepost_mcp.refined_blast.support_ground import SupportGroundCompiler

    face_id = detailed_artifact.surface_catalog["ground_contact_surfaces"][0]["face_id"]
    element_id = detailed_artifact.mesh.solids[0].element_id
    context = module_context(
        detailed_artifact,
        module_inputs={
            "placement": {
                "schema_version": "refined_blast.placement@1",
                "building_count": 1,
                "translation_m": [0.0, 0.0, 0.0],
            },
            "support_ground": {
                "schema_version": "refined_blast.support_ground@1",
                "support_face_ids": [face_id],
                "coupling_semantics": "tied",
            },
            "interactions": {
                "schema_version": "refined_blast.interactions@1",
                "pairs": [
                    {
                        "interaction_id": "support-tie",
                        "interaction_type": "tie_candidate",
                        "source_id": "support:scenario-1",
                        "target_id": f"building:element:{element_id}",
                    }
                ],
            },
        },
    )
    placement = PlacementCompiler().compile(context)
    support = SupportGroundCompiler().compile(context.with_prior_fragments(placement))
    target = next(
        member
        for member in support.interfaces[0].member_ids
        if member.startswith("building:element:")
    )
    context = with_module_input(
        context,
        "interactions",
        {
            "schema_version": "refined_blast.interactions@1",
            "pairs": [{"interaction_id": "support-tie", "interaction_type": "tie_candidate", "source_id": "support:scenario-1", "target_id": target}],
        },
    ).with_prior_fragments(placement, support)
    compiled = InteractionCompiler().compile(context)
    assert compiled.manifest["pair_count"] == 1
    assert compiled.interfaces[0].kind == "support_tied"
    assert compiled.interfaces[0].master_member_ids == support.interfaces[0].master_member_ids


def test_interactions_reject_forged_typed_roles_and_unrelated_support_members(
    detailed_artifact,
):
    from lsprepost_mcp.refined_blast.fragments import FragmentParticipant, KeywordFragment
    from lsprepost_mcp.refined_blast.interactions import InteractionCompiler
    from lsprepost_mcp.refined_blast.placement import PlacementCompiler
    from lsprepost_mcp.refined_blast.support_ground import SupportGroundCompiler

    ground_face = detailed_artifact.surface_catalog["ground_contact_surfaces"][0]["face_id"]
    context = module_context(
        detailed_artifact,
        module_inputs={
            "placement": {
                "schema_version": "refined_blast.placement@1",
                "building_count": 1,
                "translation_m": [0.0, 0.0, 0.0],
            },
            "support_ground": {
                "schema_version": "refined_blast.support_ground@1",
                "support_face_ids": [ground_face],
                "coupling_semantics": "tied",
            },
            "interactions": {
                "schema_version": "refined_blast.interactions@1",
                "pairs": [
                    {
                        "interaction_id": "forged-fsi",
                        "interaction_type": "fsi_candidate",
                        "source_id": "fluid:forged",
                        "target_id": "building:scenario-1",
                    }
                ],
            },
        },
    )
    placement = PlacementCompiler().compile(context)
    forged = KeywordFragment(
        module_id="forged",
        declared_ids=frozenset({"fluid:forged", "forged:member"}),
        required_ids=frozenset(),
        estimates={},
        manifest={},
        participants=(
            FragmentParticipant(
                participant_id="fluid:forged",
                role="blast_source",
                kind="provider_source",
                member_ids=frozenset({"forged:member"}),
            ),
        ),
    )
    with pytest.raises(ValueError, match="fluid.*building|typed.*role"):
        InteractionCompiler().compile(
            context.with_prior_fragments(placement, forged)
        )

    support = SupportGroundCompiler().compile(context.with_prior_fragments(placement))
    unrelated = next(
        f"building:element:{element.element_id}"
        for element in detailed_artifact.mesh.solids
        if f"building:element:{element.element_id}" not in support.interfaces[0].member_ids
    )
    bad = with_module_input(
        context,
        "interactions",
        {
            "schema_version": "refined_blast.interactions@1",
            "pairs": [
                {
                    "interaction_id": "unrelated-support",
                    "interaction_type": "tie_candidate",
                    "source_id": "support:scenario-1",
                    "target_id": unrelated,
                }
            ],
        },
    ).with_prior_fragments(placement, support)
    with pytest.raises(ValueError, match="support.*interface|foundation"):
        InteractionCompiler().compile(bad)


def test_compilers_leave_artifact_and_context_literal_equal(detailed_artifact):
    from lsprepost_mcp.refined_blast.blast_source import BlastSourceCompiler
    from lsprepost_mcp.refined_blast.boundaries import BoundaryCompiler
    from lsprepost_mcp.refined_blast.fluid_domain import FluidDomainCompiler
    from lsprepost_mcp.refined_blast.interactions import InteractionCompiler
    from lsprepost_mcp.refined_blast.placement import PlacementCompiler
    from lsprepost_mcp.refined_blast.support_ground import SupportGroundCompiler

    ground_face = detailed_artifact.surface_catalog["ground_contact_surfaces"][0]["face_id"]
    exterior_face = detailed_artifact.surface_catalog["exterior_surfaces"][0]["face_id"]
    context = module_context(
        detailed_artifact,
        module_inputs={
            "placement": {"schema_version": "refined_blast.placement@1", "building_count": 1, "translation_m": [0, 0, 0]},
            "support_ground": {"schema_version": "refined_blast.support_ground@1", "support_face_ids": [ground_face], "coupling_semantics": "shared_node"},
            "blast_source": {"schema_version": "refined_blast.blast_source@1", "source_declared_id": "charge:source-1", "source_space_id": "sales_hall"},
            "fluid_domain": {"schema_version": "refined_blast.fluid_domain@1", "source_space_id": "sales_hall", "opening_states": {"door_hall_back": "closed", "vent_back_outside": "closed"}, "external_buffer_m": 0.0},
            "boundaries": {"schema_version": "refined_blast.boundaries@1", "assignments": [{"boundary_id": "outflow-a", "face_id": exterior_face, "boundary_type": "non_reflecting"}]},
            "interactions": {"schema_version": "refined_blast.interactions@1", "pairs": []},
        },
    )
    before = json.dumps(detailed_artifact.to_manifest(), sort_keys=True)
    context_before = json.dumps(
        {
            "placement": context.draft.building_placement,
            "support": context.draft.support_and_ground,
            "source": context.draft.blast_source,
            "fluid": context.draft.fluid_domain,
            "boundaries": context.draft.boundaries,
            "interactions": context.draft.interactions,
        },
        default=dict,
        sort_keys=True,
    )
    accumulated = context
    for compiler in (
        PlacementCompiler(),
        SupportGroundCompiler(),
        BlastSourceCompiler(),
        FluidDomainCompiler(),
        BoundaryCompiler(),
        InteractionCompiler(),
    ):
        fragment = compiler.compile(accumulated)
        accumulated = accumulated.with_prior_fragments(fragment)
    assert json.dumps(detailed_artifact.to_manifest(), sort_keys=True) == before
    assert json.dumps(
        {
            "placement": context.draft.building_placement,
            "support": context.draft.support_and_ground,
            "source": context.draft.blast_source,
            "fluid": context.draft.fluid_domain,
            "boundaries": context.draft.boundaries,
            "interactions": context.draft.interactions,
        },
        default=dict,
        sort_keys=True,
    ) == context_before


def test_module_contracts_require_declared_si_units_and_preallocation_budgets(detailed_artifact):
    from lsprepost_mcp.refined_blast.placement import PlacementCompiler

    context = module_context(
        detailed_artifact,
        module_inputs={
            "placement": {
                "schema_version": "refined_blast.placement@1",
                "unit_system": "SI_m_s_kg_N_Pa",
                "building_count": 1,
                "translation_m": [0.0, 0.0, 0.0],
                "budgets": {
                    "schema_version": "refined_blast.module_budgets@1",
                    "max_new_nodes": 100_000,
                    "max_new_elements": 100_000,
                },
            }
        },
    )
    fragment = PlacementCompiler().compile(context)
    assert fragment.estimates["budget_checked_before_allocation"] is True
    assert fragment.manifest["unit_system"] == "SI_m_s_kg_N_Pa"


def test_unresolved_provider_requirements_cannot_be_used_as_interaction_participants(detailed_artifact):
    from lsprepost_mcp.refined_blast.interactions import InteractionCompiler

    base = module_context(
        detailed_artifact,
        module_inputs={
            "interactions": {
                "schema_version": "refined_blast.interactions@1",
                "pairs": [
                    {
                        "interaction_id": "invalid-provider-dependency",
                        "interaction_type": "fsi_candidate",
                        "source_id": "resource:not-yet-declared",
                        "target_id": "artifact:" + detailed_artifact.fingerprint,
                    }
                ],
            }
        },
    )
    with pytest.raises(ValueError, match="unresolved requirement"):
        replace(
            base,
            provider_fragment=replace(
                base.provider_fragment,
                required_ids=frozenset({"resource:not-yet-declared"}),
            ),
        )


def test_module_context_derives_closed_configs_only_from_normalized_draft(detailed_artifact):
    from lsprepost_mcp.refined_blast.contracts import normalize_scenario_draft
    from lsprepost_mcp.refined_blast.fragments import ScenarioModuleContext

    raw = {
        "scenario_id": "scenario-1",
        "scenario_kind": "internal",
        "building_placement": {
            "schema_version": "refined_blast.placement@1",
            "unit_system": "SI_m_s_kg_N_Pa",
            "building_count": 1,
            "translation_m": [0.0, 0.0, 0.0],
            "budgets": {"schema_version": "refined_blast.module_budgets@1", "max_new_nodes": 100_000, "max_new_elements": 100_000},
        },
        "support_and_ground": {},
            "load_provider": {"provider_id": "explicit_ale_fsi", "provider_input": _explicit_input("internal")},
        "blast_source": {},
        "fluid_domain": {},
        "boundaries": {},
        "interactions": {},
        "solver_controls": {},
        "output_requests": {},
        "resource_versions": {},
        "acknowledged_warning_ids": [],
    }
    draft = normalize_scenario_draft(raw)
    context = ScenarioModuleContext.from_draft(
        draft,
        ProviderContext.from_artifact(detailed_artifact, scenario_kind="internal"),
        _provider_fragment(detailed_artifact),
    )
    assert context.input_for("placement") == draft.building_placement
    assert not hasattr(context, "module_inputs")


def test_prior_fragments_accumulate_instead_of_replacing(detailed_artifact):
    from lsprepost_mcp.refined_blast.placement import PlacementCompiler
    from lsprepost_mcp.refined_blast.support_ground import SupportGroundCompiler

    face_id = detailed_artifact.surface_catalog["ground_contact_surfaces"][0]["face_id"]
    context = module_context(
        detailed_artifact,
        module_inputs={
            "placement": {"schema_version": "refined_blast.placement@1", "building_count": 1, "translation_m": [0.0, 0.0, 0.0]},
            "support_ground": {"schema_version": "refined_blast.support_ground@1", "support_face_ids": [face_id], "coupling_semantics": "shared_node"},
        },
    )
    placement = PlacementCompiler().compile(context)
    support = SupportGroundCompiler().compile(context.with_prior_fragments(placement))
    assert tuple(item.module_id for item in context.with_prior_fragments(placement).with_prior_fragments(support).prior_fragments) == ("placement", "support_ground")


@pytest.mark.parametrize("unsafe_budget", [0, 10_000_001])
def test_compiler_budget_envelope_fails_closed_even_for_prebuilt_mappings(unsafe_budget):
    from lsprepost_mcp.refined_blast.fragments import require_si_budgets

    raw = {
        "unit_system": "SI_m_s_kg_N_Pa",
        "budgets": {
            "schema_version": "refined_blast.module_budgets@1",
            "max_new_nodes": unsafe_budget,
            "max_new_elements": 100,
        },
    }
    with pytest.raises(ValueError, match="positive|hard safety limit"):
        require_si_budgets(raw, "test_module")


def test_fragment_typed_records_are_first_class_fingerprinted_and_exactly_closed():
    from lsprepost_mcp.refined_blast.fragments import (
        FragmentInterface,
        FragmentParticipant,
        KeywordFragment,
    )

    fluid = FragmentParticipant(
        participant_id="fluid:scenario-1",
        role="fluid_domain",
        kind="fluid_mesh",
        member_ids=frozenset({"fluid:element:1"}),
    )
    structure = FragmentParticipant(
        participant_id="building:scenario-1",
        role="building_structure",
        kind="structural_mesh",
        member_ids=frozenset({"building:element:1"}),
    )
    interface = FragmentInterface(
        interface_id="interface:fsi-1",
        kind="fsi",
        source_participant_id=fluid.participant_id,
        target_participant_id=structure.participant_id,
        member_ids=frozenset({"fluid:element:1", "building:element:1"}),
    )
    first = KeywordFragment(
        module_id="typed-test",
        declared_ids=frozenset(
            {
                fluid.participant_id,
                structure.participant_id,
                interface.interface_id,
                "fluid:element:1",
            }
        ),
        required_ids=frozenset({"building:element:1"}),
        estimates={},
        manifest={},
        participants=(fluid, structure),
        interfaces=(interface,),
    )
    changed = replace(
        first,
        participants=(
            replace(fluid, kind="fluid_region"),
            structure,
        ),
    )

    assert first.fingerprint != changed.fingerprint
    assert first.participants == (fluid, structure)
    assert first.interfaces == (interface,)
    with pytest.raises(ValueError, match="unclosed typed record id"):
        replace(first, required_ids=frozenset())


def test_module_context_rejects_duplicate_typed_participants_interfaces_and_members(
    detailed_artifact,
):
    from lsprepost_mcp.refined_blast.fragments import (
        FragmentInterface,
        FragmentParticipant,
        KeywordFragment,
    )

    context = module_context(detailed_artifact)
    participant = FragmentParticipant(
        participant_id="participant:one",
        role="building_structure",
        kind="structural_mesh",
        member_ids=frozenset({"member:one"}),
    )
    first = KeywordFragment(
        module_id="first",
        declared_ids=frozenset({"participant:one", "member:one"}),
        required_ids=frozenset(),
        estimates={},
        manifest={},
        participants=(participant,),
    )
    duplicate_participant = replace(first, module_id="second")
    with pytest.raises(ValueError, match="participant.*duplicate|duplicate.*participant"):
        context.with_prior_fragments(first, duplicate_participant)

    second_participant = replace(
        participant,
        participant_id="participant:two",
    )
    conflicting_member = replace(
        first,
        module_id="second",
        declared_ids=frozenset({"participant:two", "member:one"}),
        participants=(second_participant,),
    )
    with pytest.raises(ValueError, match="member.*conflict|conflicting member"):
        context.with_prior_fragments(first, conflicting_member)

    relation = FragmentInterface(
        interface_id="interface:one",
        kind="fsi",
        source_participant_id="participant:one",
        target_participant_id="participant:two",
        member_ids=frozenset(),
    )
    left = replace(
        first,
        module_id="left",
        required_ids=frozenset({"participant:two"}),
        interfaces=(relation,),
        declared_ids=first.declared_ids | {relation.interface_id},
    )
    right = KeywordFragment(
        module_id="right",
        declared_ids=frozenset({"participant:two", "member:two", relation.interface_id}),
        required_ids=frozenset({"participant:one"}),
        estimates={},
        manifest={},
        participants=(
            replace(
                second_participant,
                member_ids=frozenset({"member:two"}),
            ),
        ),
        interfaces=(relation,),
    )
    with pytest.raises(ValueError, match="interface.*duplicate|duplicate.*interface"):
        context.with_prior_fragments(left, right)

    dangling = replace(
        first,
        declared_ids=first.declared_ids | {"participant:missing", "interface:dangling"},
        interfaces=(
            replace(
                relation,
                interface_id="interface:dangling",
                target_participant_id="participant:missing",
            ),
        ),
    )
    with pytest.raises(ValueError, match="interface.*participant"):
        context.with_prior_fragments(dangling)


def test_participant_and_interface_ids_share_one_global_symbol_namespace(detailed_artifact):
    from lsprepost_mcp.refined_blast.fragments import (
        FragmentInterface,
        FragmentParticipant,
        KeywordFragment,
    )

    left = FragmentParticipant(
        participant_id="participant:left",
        role="fluid_domain",
        kind="fluid_region",
    )
    right = FragmentParticipant(
        participant_id="participant:right",
        role="building_structure",
        kind="structural_mesh",
    )
    collision = FragmentInterface(
        interface_id=left.participant_id,
        kind="fsi",
        source_participant_id=left.participant_id,
        target_participant_id=right.participant_id,
    )
    with pytest.raises(ValueError, match="global.*symbol|participant.*interface"):
        KeywordFragment(
            module_id="same-fragment",
            declared_ids=frozenset(
                {left.participant_id, right.participant_id}
            ),
            required_ids=frozenset(),
            estimates={},
            manifest={},
            participants=(left, right),
            interfaces=(collision,),
        )

    participants = KeywordFragment(
        module_id="participants",
        declared_ids=frozenset({left.participant_id, right.participant_id}),
        required_ids=frozenset(),
        estimates={},
        manifest={},
        participants=(left, right),
    )
    relation = KeywordFragment(
        module_id="relation",
        declared_ids=frozenset({left.participant_id}),
        required_ids=frozenset({right.participant_id}),
        estimates={},
        manifest={},
        interfaces=(collision,),
    )
    with pytest.raises(ValueError, match="global.*symbol|participant.*interface"):
        module_context(detailed_artifact).with_prior_fragments(participants, relation)


def _hex_corner_jacobian_determinants(coordinates):
    natural = (
        (-1.0, -1.0, -1.0),
        (1.0, -1.0, -1.0),
        (1.0, 1.0, -1.0),
        (-1.0, 1.0, -1.0),
        (-1.0, -1.0, 1.0),
        (1.0, -1.0, 1.0),
        (1.0, 1.0, 1.0),
        (-1.0, 1.0, 1.0),
    )
    determinants = []
    for xi, eta, zeta in natural:
        jacobian = [[0.0] * 3 for _ in range(3)]
        for point, (node_xi, node_eta, node_zeta) in zip(
            coordinates, natural, strict=True
        ):
            derivatives = (
                node_xi * (1.0 + node_eta * eta) * (1.0 + node_zeta * zeta) / 8.0,
                node_eta * (1.0 + node_xi * xi) * (1.0 + node_zeta * zeta) / 8.0,
                node_zeta * (1.0 + node_xi * xi) * (1.0 + node_eta * eta) / 8.0,
            )
            for physical_axis in range(3):
                for natural_axis in range(3):
                    jacobian[physical_axis][natural_axis] += (
                        point[physical_axis] * derivatives[natural_axis]
                    )
        determinants.append(
            jacobian[0][0]
            * (jacobian[1][1] * jacobian[2][2] - jacobian[1][2] * jacobian[2][1])
            - jacobian[0][1]
            * (jacobian[1][0] * jacobian[2][2] - jacobian[1][2] * jacobian[2][0])
            + jacobian[0][2]
            * (jacobian[1][0] * jacobian[2][1] - jacobian[1][1] * jacobian[2][0])
        )
    return tuple(determinants)
