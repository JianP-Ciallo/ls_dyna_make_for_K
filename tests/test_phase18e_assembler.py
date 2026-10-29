from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import copy
from dataclasses import replace
from types import MappingProxyType

import pytest

from lsprepost_mcp.refined_blast.assembler import (
    ProjectAssembler,
    assemble_refined_blast_project,
)
from lsprepost_mcp.refined_blast.contracts import normalize_refined_blast_project
from lsprepost_mcp.refined_blast.provider_registry import get_load_provider
from lsprepost_mcp.refined_blast.controls import (
    compile_solver_controls,
    normalize_solver_controls,
)
from lsprepost_mcp.refined_blast.fragments import (
    FragmentInterface,
    FragmentParticipant,
    KeywordFragment,
)
from lsprepost_mcp.refined_blast.outputs import (
    compile_output_requests,
    normalize_output_requests,
)
from lsprepost_mcp.refined_blast.store import RefinedBlastStore
from lsprepost_mcp.refined_blast.providers.common import (
    ProviderEstimate,
    ProviderEvidence,
    ProviderFragment,
    ProviderContext,
    thaw_value,
)
from lsprepost_mcp.refined_building.artifacts import (
    BuildingArtifact,
    MeshFragment,
    Node,
    PartBinding,
    SolidElement,
)


def _fragment(
    module_id: str,
    *,
    declared: tuple[str, ...],
    required: tuple[str, ...] = (),
    participants: tuple[FragmentParticipant, ...] = (),
    interfaces: tuple[FragmentInterface, ...] = (),
) -> KeywordFragment:
    return KeywordFragment(
        module_id=module_id,
        declared_ids=frozenset(declared),
        required_ids=frozenset(required),
        estimates={
            "new_nodes": 0,
            "new_elements": 0,
            "budget_limits": {"max_new_nodes": 10, "max_new_elements": 10},
            "budget_checked_before_allocation": True,
        },
        manifest={"unit_system": "SI_m_s_kg_N_Pa"},
        participants=participants,
        interfaces=interfaces,
    )


def _artifact() -> BuildingArtifact:
    nodes = (
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 1.0, 0.0, 0.0),
        Node(3, 1.0, 1.0, 0.0),
        Node(4, 0.0, 1.0, 0.0),
        Node(5, 0.0, 0.0, 1.0),
        Node(6, 1.0, 0.0, 1.0),
        Node(7, 1.0, 1.0, 1.0),
        Node(8, 0.0, 1.0, 1.0),
    )
    face = {
        "face_id": "solid:1:face:x_max",
        "element_id": 1,
        "node_ids": [2, 3, 7, 6],
        "centroid_m": [1.0, 0.5, 0.5],
        "normal": [1.0, 0.0, 0.0],
        "area_m2": 1.0,
    }
    return BuildingArtifact(
        asset_id="unit-building",
        system_id="rc_box",
        mesh=MeshFragment(
            nodes=nodes,
            solids=(SolidElement(1, (1, 2, 3, 4, 5, 6, 7, 8), "concrete"),),
            part_bindings=(PartBinding("concrete", "concrete", "solid"),),
        ),
        normalized_input={"openings": []},
        topology_manifest={
            "envelope_bounds_m": [0.0, 0.0, 0.0, 1.0, 1.0, 1.0],
            "void_regions": [],
            "fingerprint": "topology-unit",
        },
        surface_catalog={
            "exterior_surfaces": [face],
            "interior_cavity_surfaces": [],
            "ground_contact_surfaces": [],
            "unclassified_boundary_surfaces": [],
        },
    )


def _artifact_with_numeric_offset(offset: int) -> BuildingArtifact:
    base = _artifact()
    mapping = {node.node_id: node.node_id + offset for node in base.mesh.nodes}
    nodes = tuple(replace(node, node_id=mapping[node.node_id]) for node in base.mesh.nodes)
    solid = base.mesh.solids[0]
    mesh = replace(
        base.mesh,
        nodes=nodes,
        solids=(
            replace(
                solid,
                element_id=solid.element_id + offset,
                node_ids=tuple(mapping[node_id] for node_id in solid.node_ids),
            ),
        ),
    )
    catalog = copy.deepcopy(base.surface_catalog)
    face = catalog["exterior_surfaces"][0]
    face["element_id"] = solid.element_id + offset
    face["node_ids"] = [mapping[node_id] for node_id in face["node_ids"]]
    return replace(base, mesh=mesh, surface_catalog=catalog)


def _lbe_input(peak_pressure_pa: float = 250_000.0) -> dict[str, object]:
    return {
        "schema_version": "lbe_segment@1",
        "unit_system": "SI_m_s_kg_N_Pa",
        "source": {
            "schema_version": "lbe_segment.source@1",
            "source_id": "charge-1",
            "position_m": [-1.0, 0.5, 0.5],
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
            "peak_pressure_pa": peak_pressure_pa,
            "positive_phase_duration_s": 0.02,
        },
        "budgets": {
            "schema_version": "lbe_segment.budgets@1",
            "max_surface_count": 100,
            "max_total_area_m2": 100.0,
        },
    }


def _explicit_input() -> dict[str, object]:
    resource = lambda resource_id: {"resource_id": resource_id, "version": "1.0.0"}
    return {
        "schema_version": "explicit_ale_fsi@1",
        "unit_system": "SI_m_s_kg_N_Pa",
        "charge": {
            "schema_version": "explicit_ale_fsi.charge@1",
            "source_id": "charge-1",
            "position_m": [-1.0, 0.5, 0.5],
            "tnt_equivalent_kg": 2.0,
            "detonation_time_s": 0.0,
        },
        "domain": {
            "schema_version": "explicit_ale_fsi.domain@1",
            "bounds_m": [-3.0, -2.0, -2.0, 3.0, 3.0, 3.0],
            "target_cell_size_m": 2.0,
            "minimum_margin_m": 1.0,
            "external_buffer_m": 0.5,
        },
        "fsi": {
            "schema_version": "explicit_ale_fsi.fsi@1",
            "surface_categories": ["exterior_surfaces"],
            "coupling_mode": "constrained_lagrange_in_solid",
        },
        "resources": {
            "schema_version": "explicit_ale_fsi.resources@1",
            "air_material": resource("neutral-air"),
            "explosive_material": resource("neutral-tnt"),
            "equation_of_state": resource("neutral-eos"),
            "ale_keyword": resource("neutral-ale-keywords"),
        },
        "budgets": {
            "schema_version": "explicit_ale_fsi.budgets@1",
            "max_axis_points": 20,
            "max_node_count": 1_000,
            "max_element_count": 1_000,
        },
    }


def _imported_input() -> dict[str, object]:
    return {
        "schema_version": "imported_pressure_history@1",
        "unit_system": "SI_m_s_kg_N_Pa",
        "source": {
            "schema_version": "imported_pressure_history.source@1",
            "source_id": "history-1",
            "source_name": "test-history",
            "form": "structured_rows",
            "rows": [[0.0, 0.0], [100.0, 2.0]],
        },
        "units": {
            "schema_version": "imported_pressure_history.units@1",
            "time_unit": "ms",
            "pressure_unit": "kPa",
        },
        "curve": {
            "schema_version": "imported_pressure_history.curve@1",
            "interpolation": "linear",
            "scale": 1.0,
        },
        "mapping": {
            "schema_version": "imported_pressure_history.mapping@1",
            "surface_category": "exterior_surfaces",
            "target_face_ids": [],
        },
        "budgets": {
            "schema_version": "imported_pressure_history.budgets@1",
            "max_input_bytes": 4_096,
            "max_row_count": 100,
            "max_target_surface_count": 1_000,
        },
    }


def _project(
    artifact: BuildingArtifact,
    peak_pressure_pa: float = 250_000.0,
    *,
    provider_id: str = "lbe_segment",
    provider_input: dict[str, object] | None = None,
    solver_controls: dict[str, object] | None = None,
    output_requests: dict[str, object] | None = None,
):
    return normalize_refined_blast_project(
        {
            "schema_version": "refined_building_blast@1",
            "project_id": "project-1",
            "building_reference": {"asset_id": artifact.asset_id},
            "building_artifact_fingerprint": artifact.fingerprint,
            "preset_reference": "none",
            "preset_version": "1",
            "project_overrides": {},
            "expert_extensions": {},
            "scenario_set": [
                {
                    "scenario_id": "scenario-1",
                    "scenario_kind": "external",
                    "building_placement": {},
                    "support_and_ground": {},
                    "load_provider": {
                        "provider_id": provider_id,
                        "provider_input": provider_input or _lbe_input(peak_pressure_pa),
                    },
                    "blast_source": {},
                    "fluid_domain": {},
                    "boundaries": {},
                    "interactions": {},
                    "solver_controls": solver_controls or {},
                    "output_requests": output_requests or {},
                    "resource_versions": {},
                    "acknowledged_warning_ids": [],
                }
            ],
            "confirmation_records": [],
            "provenance": {},
            "created_at": "2026-08-11T00:00:00Z",
            "updated_at": "2026-08-11T00:00:00Z",
        }
    )


def _provider_fragment() -> ProviderFragment:
    return ProviderFragment(
        provider_id="unit_provider",
        normalized_input=MappingProxyType({"schema_version": "unit_provider@1"}),
        axes_m=((0.0, 1.0), (0.0, 1.0), (0.0, 1.0)),
        node_ids=tuple(f"provider:node:{index}" for index in range(8)),
        element_ids=("provider:solid:1",),
        fsi_face_ids=(),
        required_ids=frozenset(),
        declared_ids=frozenset(
            {
                *(f"provider:node:{index}" for index in range(8)),
                "provider:solid:1",
            }
        ),
        evidence=(),
        manifest=MappingProxyType(
            {
                "provider_id": "unit_provider",
                "scenario_kind": "external",
                "building_artifact_fingerprint": "a" * 64,
                "allocation": {
                    "actual_node_count": 8,
                    "actual_element_count": 1,
                },
                "solver_ready": False,
                "requires_project_review": True,
                "engineering_validated": False,
            }
        ),
    )


def _real_lbe_provider_rows():
    artifact = _artifact()
    context = ProviderContext.from_artifact(artifact, scenario_kind="external")
    provider = get_load_provider("lbe_segment")
    value = _lbe_input()
    return artifact, context, provider.estimate(value, context), provider.compile(value, context)


def _real_provider_rows(provider_id: str, value: dict[str, object]):
    artifact = _artifact()
    resources = _neutral_resource_ids()
    context = ProviderContext.from_artifact(
        artifact, scenario_kind="external", available_ids=resources
    )
    provider = get_load_provider(provider_id)
    return artifact, provider.estimate(value, context), provider.compile(value, context)


def _neutral_resource_ids() -> frozenset[str]:
    return frozenset(
        {
            "resource:neutral-air@1.0.0",
            "resource:neutral-tnt@1.0.0",
            "resource:neutral-eos@1.0.0",
            "resource:neutral-ale-keywords@1.0.0",
        }
    )


def test_control_and_output_contracts_are_closed_versioned_si_and_conservative():
    controls = normalize_solver_controls(
        {
            "schema_version": "refined_blast.solver_controls@1",
            "unit_system": "SI_m_s_kg_N_Pa",
            "termination_time_s": 0.1,
            "timestep_scale_factor": 0.67,
        }
    )
    outputs = normalize_output_requests(
        {
            "schema_version": "refined_blast.output_requests@1",
            "unit_system": "SI_m_s_kg_N_Pa",
            "d3plot_interval_s": 0.001,
            "history_interval_s": 0.0001,
        }
    )

    assert controls["research_candidate"] is True
    assert outputs["solver_ready"] is False
    assert compile_solver_controls(controls, "scenario-1").manifest["requires_project_review"] is True
    assert compile_output_requests(outputs, "scenario-1").manifest["engineering_validated"] is False

    with pytest.raises(ValueError, match="unknown field"):
        normalize_solver_controls({**dict(controls), "legacy_dt": 1.0})
    with pytest.raises(ValueError, match="unit_system"):
        normalize_output_requests({**dict(outputs), "unit_system": "mm_ms_kg"})
    with pytest.raises(ValueError, match="finite positive"):
        normalize_solver_controls({**dict(controls), "termination_time_s": math.nan})


def test_task7_public_api_is_exported_from_refined_blast_package():
    from lsprepost_mcp import refined_blast

    assert refined_blast.ProjectAssembler is ProjectAssembler
    assert refined_blast.assemble_refined_blast_project is assemble_refined_blast_project
    assert refined_blast.normalize_solver_controls is normalize_solver_controls
    assert refined_blast.normalize_output_requests is normalize_output_requests


def test_controls_and_outputs_are_persisted_custom_contracts_and_invalidate_package(tmp_path):
    artifact = _artifact()
    controls = {
        "schema_version": "refined_blast.solver_controls@1",
        "unit_system": "SI_m_s_kg_N_Pa",
        "termination_time_s": 0.25,
        "timestep_scale_factor": 0.55,
    }
    outputs = {
        "schema_version": "refined_blast.output_requests@1",
        "unit_system": "SI_m_s_kg_N_Pa",
        "d3plot_interval_s": 0.002,
        "history_interval_s": 0.0002,
    }
    project = _project(artifact, solver_controls=controls, output_requests=outputs)
    assert project.scenario_set[0].solver_controls["termination_time_s"] == 0.25
    assert project.scenario_set[0].output_requests["d3plot_interval_s"] == 0.002

    with RefinedBlastStore(tmp_path) as store:
        stored = store.create(project)
        loaded = store.load_project(stored.project_id)
    assert loaded.project.scenario_set[0].solver_controls == project.scenario_set[0].solver_controls
    assert loaded.project.scenario_set[0].output_requests == project.scenario_set[0].output_requests

    custom_package = assemble_refined_blast_project(project, artifact)
    default_package = assemble_refined_blast_project(_project(artifact), artifact)
    assert custom_package.package_fingerprint != default_package.package_fingerprint
    assert b"0.25" in custom_package.files["80_controls.k"]
    assert b"0.002" in custom_package.files["90_outputs.k"]


def test_assembler_revalidates_controls_and_outputs_instead_of_trusting_fragment_flags():
    invalid_controls = KeywordFragment(
        module_id="controls",
        declared_ids=frozenset({"controls:s"}),
        required_ids=frozenset(),
        estimates={"new_nodes": 0, "new_elements": 0, "budget_limits": {"max_new_nodes": 1, "max_new_elements": 1}, "budget_checked_before_allocation": True},
        manifest={
            "schema_version": "refined_blast.solver_controls@1",
            "unit_system": "SI_m_s_kg_N_Pa",
            "termination_time_s": 0.1,
            "timestep_scale_factor": 0.67,
            "research_candidate": True,
            "legacy_dt": 1.0,
        },
    )
    invalid_outputs = KeywordFragment(
        module_id="outputs",
        declared_ids=frozenset({"outputs:s"}),
        required_ids=frozenset(),
        estimates={"new_nodes": 0, "new_elements": 0, "budget_limits": {"max_new_nodes": 1, "max_new_elements": 1}, "budget_checked_before_allocation": True},
        manifest={
            "schema_version": "refined_blast.output_requests@1",
            "unit_system": "SI_m_s_kg_N_Pa",
            "d3plot_interval_s": 0.001,
            "history_interval_s": 0.0001,
            "research_candidate": True,
            "unexpected": "bypass",
        },
    )
    with pytest.raises(ValueError, match="unknown field"):
        ProjectAssembler().assemble((invalid_controls,))
    with pytest.raises(ValueError, match="unknown field"):
        ProjectAssembler().assemble((invalid_outputs,))


def test_assembler_is_deterministic_and_manifest_matches_every_file_byte():
    fragments = (
        _fragment("placement", declared=("placement:a",)),
        _fragment("support_ground", declared=("support:b",), required=("placement:a",)),
    )

    first = ProjectAssembler().assemble(fragments)
    second = ProjectAssembler().assemble(fragments)

    assert first.package_fingerprint == second.package_fingerprint
    assert first.files == second.files
    assert first.manifest["include_order"] == tuple(first.files)[1:]
    for row in first.manifest["files"]:
        content = first.files[row["path"]]
        assert row["sha256"] == hashlib.sha256(content).hexdigest()
        assert row["byte_count"] == len(content)
        assert row["line_count"] == len(content.decode("utf-8").splitlines())


def test_assembler_fails_closed_for_missing_duplicate_and_cyclic_dependencies():
    with pytest.raises(ValueError, match="unresolved dependency"):
        ProjectAssembler().assemble(
            (_fragment("placement", declared=("placement:a",), required=("missing:x",)),)
        )

    with pytest.raises(ValueError, match="duplicate declaration"):
        ProjectAssembler().assemble(
            (
                _fragment("placement", declared=("same:id",)),
                _fragment("support_ground", declared=("same:id",)),
            )
        )

    with pytest.raises(ValueError, match="cyclic dependency"):
        ProjectAssembler().assemble(
            (
                _fragment("placement", declared=("placement:a",), required=("support:b",)),
                _fragment("support_ground", declared=("support:b",), required=("placement:a",)),
            )
        )


def test_assembler_rejects_declarations_that_collide_with_external_namespace():
    with pytest.raises(ValueError, match="external namespace"):
        ProjectAssembler(external_ids=frozenset({"surface:one"})).assemble(
            (_fragment("placement", declared=("surface:one",)),)
        )


def test_assembler_rejects_keyword_fragment_geometry_count_mismatch():
    fragment = KeywordFragment(
        module_id="support_ground",
        declared_ids=frozenset({"ground:one"}),
        required_ids=frozenset(),
        estimates={
            "new_nodes": 2,
            "new_elements": 1,
            "budget_limits": {"max_new_nodes": 10, "max_new_elements": 10},
            "budget_checked_before_allocation": True,
        },
        manifest={
            "unit_system": "SI_m_s_kg_N_Pa",
            "ground_geometry": {"nodes": ({"node_id": "ground:node:1"},), "elements": ()},
        },
    )
    with pytest.raises(ValueError, match="geometry count consistency"):
        ProjectAssembler().assemble((fragment,))


def test_assembler_rejects_nonzero_rendered_counts_without_geometry():
    fragment = KeywordFragment(
        module_id="support_ground",
        declared_ids=frozenset({"ground:a"}),
        required_ids=frozenset(),
        estimates={
            "new_nodes": 1,
            "new_elements": 0,
            "budget_limits": {"max_new_nodes": 10, "max_new_elements": 10},
            "budget_checked_before_allocation": True,
        },
        manifest={"unit_system": "SI_m_s_kg_N_Pa"},
    )
    with pytest.raises(ValueError, match="geometry count consistency"):
        ProjectAssembler().assemble((fragment,))


def test_assembler_rejects_whitespace_module_ids_and_range_overflow():
    whitespace = _fragment(" placement ", declared=("placement:a",))
    with pytest.raises(ValueError, match="module_id.*trimmed"):
        ProjectAssembler().assemble((whitespace,))

    with pytest.raises(ValueError, match="range capacity"):
        ProjectAssembler(range_capacity=2).assemble(
            (_fragment("placement", declared=("a:1", "a:2", "a:3")),)
        )


def test_numeric_ranges_move_as_one_reserved_block_away_from_building_ids():
    # The original placement range starts at 10_200_001; this building occupies it.
    artifact = _artifact_with_numeric_offset(10_200_000)
    package = ProjectAssembler().assemble(
        (_fragment("placement", declared=("placement:a",)),), artifact=artifact
    )
    building_ids = {
        *(node.node_id for node in artifact.mesh.nodes),
        *(element.element_id for element in artifact.mesh.solids),
        1,  # deterministic rendered building part ID
    }
    assert not (set(package.symbol_to_numeric_id.values()) & building_ids)
    ranges = package.manifest["id_allocation"]["reserved_ranges"]
    assert len(ranges) == 9
    assert all(
        not any(row["start"] <= value <= row["end"] for value in building_ids)
        for row in ranges
    )


def test_ground_geometry_renders_real_nodes_solids_counts_and_relation_audit():
    artifact = _artifact()
    bottom_ids = tuple(f"ground:s:node:{index}" for index in range(1, 5))
    solid_id = "ground:s:solid:1"
    face_id = "ground:s:face:top:1"
    participant_id = "ground:s"
    interface_id = "support_interface:s:1"
    participant = FragmentParticipant(
        participant_id,
        "ground_support",
        "ground_mesh",
        frozenset({*bottom_ids, solid_id, face_id}),
    )
    structure = FragmentParticipant(
        "building:s", "building_structure", "structural_mesh"
    )
    relation = FragmentInterface(
        interface_id,
        "support_shared_node",
        participant_id,
        "building:s",
            frozenset({solid_id, face_id, "building:element:1", "surface:solid:1:face:x_max"}),
        shared_node_ids=("building:node:1", "building:node:2", "building:node:3", "building:node:4"),
    )
    nodes = tuple(
        {
            "node_id": node_id,
            "coordinates_m": coordinates,
            "layer": "bottom",
            "coincident_with": "",
        }
        for node_id, coordinates in zip(
            bottom_ids,
            ((0.0, 0.0, -1.0), (1.0, 0.0, -1.0), (1.0, 1.0, -1.0), (0.0, 1.0, -1.0)),
            strict=True,
        )
    )
    element = {
        "element_id": solid_id,
        "node_ids": (
            "building:node:1", "building:node:2", "building:node:3", "building:node:4",
            *bottom_ids,
        ),
        "top_face_id": face_id,
        "source_foundation_face_id": "surface:solid:1:face:x_max",
        "corner_jacobians_m3": (0.125,) * 8,
    }
    fragment = KeywordFragment(
        module_id="support_ground",
        declared_ids=frozenset({participant_id, "building:s", interface_id, solid_id, face_id, *bottom_ids}),
        required_ids=frozenset({
            "building:node:1", "building:node:2", "building:node:3", "building:node:4",
            "building:element:1", "surface:solid:1:face:x_max",
        }),
        estimates={"new_nodes": 4, "new_elements": 1, "budget_limits": {"max_new_nodes": 10, "max_new_elements": 10}, "budget_checked_before_allocation": True},
        manifest={
            "unit_system": "SI_m_s_kg_N_Pa",
            "ground_geometry": {
                "schema_version": "refined_blast.symbolic_ground_geometry@1",
                "ground_depth_m": 1.0,
                "nodes": nodes,
                "elements": (element,),
            },
        },
        participants=(participant, structure),
        interfaces=(relation,),
    )
    package = ProjectAssembler().assemble((fragment,), artifact=artifact)
    rendered = package.files["30_support_ground.k"].decode("utf-8")
    assert "*NODE" in rendered
    assert "*ELEMENT_SOLID" in rendered
    assert str(package.symbol_to_numeric_id[bottom_ids[0]]) in rendered
    assert ",1,2,3,4," in rendered
    assert interface_id in rendered and "support_shared_node" in rendered
    assert package.manifest["rendered_counts"]["module_new_nodes"] == 4
    assert package.manifest["rendered_counts"]["module_new_elements"] == 1


def test_assembler_closes_typed_participant_interface_and_member_graph():
    participant_a = FragmentParticipant("participant:a", "building_structure", "structural_mesh")
    participant_b = FragmentParticipant("participant:b", "fluid_domain", "fluid_region")
    relation = FragmentInterface(
        "interface:ab",
        "fsi",
        "participant:b",
        "participant:a",
        frozenset({"surface:one"}),
    )
    fragments = (
        _fragment("placement", declared=("participant:a",), participants=(participant_a,)),
        _fragment(
            "fluid_domain",
            declared=("participant:b",),
            participants=(participant_b,),
        ),
        _fragment(
            "interactions",
            declared=("interface:ab",),
            required=("participant:a", "participant:b", "surface:one"),
            interfaces=(relation,),
        ),
    )
    package = ProjectAssembler(external_ids=frozenset({"surface:one"})).assemble(fragments)
    assert package.manifest["dependency_closure"]["closed"] is True

    forged = replace(
        fragments[1],
        declared_ids=frozenset({"participant:a"}),
        participants=(replace(participant_b, participant_id="participant:a"),),
    )
    with pytest.raises(ValueError, match="typed participant|duplicate declaration"):
        ProjectAssembler(external_ids=frozenset({"surface:one"})).assemble(
            (fragments[0], forged, fragments[2])
        )


@pytest.mark.parametrize(
    "mutation, message",
    [
        ({"node_ids": ("provider:node:0",) * 8}, "duplicate provider node"),
        ({"axes_m": ((0.0, math.nan), (0.0, 1.0), (0.0, 1.0))}, "finite"),
        ({"element_ids": ()}, "count consistency"),
        ({"provider_id": " unit_provider "}, "provider_id.*trimmed"),
    ],
)
def test_assembler_revalidates_public_provider_fragment_invariants(mutation, message):
    fragment = replace(_provider_fragment(), **mutation)
    with pytest.raises(ValueError, match=message):
        ProjectAssembler().assemble((), provider_fragment=fragment)


def test_assembler_revalidates_provider_estimate_counts_before_allocation():
    estimate = ProviderEstimate(
        provider_id="unit_provider",
        axis_point_counts=(2, 2, 2),
        node_count=7,
        element_count=1,
        budget_limits=MappingProxyType(
            {"max_axis_points": 10, "max_node_count": 100, "max_element_count": 100}
        ),
    )
    with pytest.raises(ValueError, match="estimate.*count consistency"):
        ProjectAssembler().assemble(
            (), provider_fragment=_provider_fragment(), provider_estimate=estimate
        )


def test_provider_estimate_budget_keys_are_closed_for_the_real_provider():
    artifact, _, estimate, fragment = _real_lbe_provider_rows()
    forged = replace(
        estimate,
        budget_limits=MappingProxyType(
            {**dict(estimate.budget_limits), "unexpected_limit": 10}
        ),
    )
    with pytest.raises(ValueError, match="budget.*key|unknown.*budget"):
        ProjectAssembler().assemble(
            (), artifact=artifact, provider_fragment=fragment, provider_estimate=forged
        )


def test_provider_fragment_actual_surface_allocation_cannot_exceed_estimate_budget():
    artifact, _, estimate, fragment = _real_lbe_provider_rows()
    manifest = thaw_value(fragment.manifest)
    manifest["allocation"]["actual_loaded_surface_count"] = (
        estimate.budget_limits["max_surface_count"] + 1
    )
    forged = replace(fragment, manifest=manifest)
    with pytest.raises(ValueError, match="surface.*budget"):
        ProjectAssembler().assemble(
            (), artifact=artifact, provider_fragment=forged, provider_estimate=estimate
        )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("actual_loaded_surface_count", 0),
        ("actual_target_surface_count", 0),
        ("actual_total_area_m2", 0.0),
    ],
)
def test_provider_fragment_actual_surface_claims_match_catalog(key, value):
    artifact, _, estimate, fragment = _real_lbe_provider_rows()
    manifest = thaw_value(fragment.manifest)
    manifest["allocation"][key] = value
    forged = replace(fragment, manifest=manifest)
    with pytest.raises(ValueError, match="surface.*(count|area).*match"):
        ProjectAssembler().assemble(
            (), artifact=artifact, provider_fragment=forged, provider_estimate=estimate
        )


def test_provider_fragment_ids_must_be_trimmed_at_assembly_boundary():
    artifact, _, estimate, fragment = _real_lbe_provider_rows()
    forged = replace(fragment, declared_ids=frozenset({*fragment.declared_ids, " bad:id "}))
    with pytest.raises(ValueError, match="declared.*trimmed"):
        ProjectAssembler().assemble(
            (), artifact=artifact, provider_fragment=forged, provider_estimate=estimate
        )


def test_provider_fsi_faces_must_be_real_required_catalog_surfaces():
    artifact, _, estimate, fragment = _real_lbe_provider_rows()
    forged = replace(fragment, fsi_face_ids=("invented-face",))
    with pytest.raises(ValueError, match="FSI face.*catalog|required"):
        ProjectAssembler().assemble(
            (), artifact=artifact, provider_fragment=forged, provider_estimate=estimate
        )


@pytest.mark.parametrize("field", ["input_fingerprint", "topology_fingerprint"])
def test_provider_manifest_identity_is_bound_to_input_and_artifact(field):
    artifact, _, estimate, fragment = _real_lbe_provider_rows()
    manifest = thaw_value(fragment.manifest)
    manifest[field] = "0" * 64
    forged = replace(fragment, manifest=manifest)
    with pytest.raises(ValueError, match=field.replace("_", " ") + "|identity"):
        ProjectAssembler().assemble(
            (), artifact=artifact, provider_fragment=forged, provider_estimate=estimate
        )


def test_provider_source_claim_identity_is_bound_to_fragment_context():
    artifact, _, estimate, fragment = _real_lbe_provider_rows()
    evidence_rows = list(fragment.evidence)
    index = next(
        position
        for position, evidence in enumerate(evidence_rows)
        if evidence.evidence_kind == "provider_source_space"
    )
    claims = thaw_value(evidence_rows[index].claims)
    claims["provider_id"] = "explicit_ale_fsi"
    evidence_rows[index] = replace(evidence_rows[index], claims=claims)
    forged = replace(fragment, evidence=tuple(evidence_rows))
    with pytest.raises(ValueError, match="source.*provider identity|evidence.*identity"):
        ProjectAssembler().assemble(
            (), artifact=artifact, provider_fragment=forged, provider_estimate=estimate
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_space_id", "invented-space"),
        ("determination", "forged-determination"),
        ("surface_category", "exterior_surfaces"),
        ("external_opening_ids", ["invented-opening"]),
    ],
)
def test_provider_source_claims_are_derived_from_input_and_topology(field, value):
    artifact, _, estimate, fragment = _real_lbe_provider_rows()
    evidence_rows = list(fragment.evidence)
    index = next(
        position
        for position, evidence in enumerate(evidence_rows)
        if evidence.evidence_kind == "provider_source_space"
    )
    claims = thaw_value(evidence_rows[index].claims)
    claims[field] = value
    evidence_rows[index] = replace(evidence_rows[index], claims=claims)
    manifest = thaw_value(fragment.manifest)
    manifest["evidence_fingerprints"] = [row.fingerprint for row in evidence_rows]
    forged = replace(fragment, evidence=tuple(evidence_rows), manifest=manifest)

    with pytest.raises(ValueError, match="canonical provider fragment mismatch"):
        ProjectAssembler().assemble(
            (),
            artifact=artifact,
            provider_fragment=forged,
            provider_estimate=estimate,
            provider_input=_lbe_input(),
            scenario_kind="external",
        )


def test_provider_canonical_rebuild_rejects_forged_ale_resources():
    artifact, estimate, fragment = _real_provider_rows(
        "explicit_ale_fsi", _explicit_input()
    )
    manifest = thaw_value(fragment.manifest)
    manifest["resources"][0] = "forged-air@9.9.9"
    forged = replace(fragment, manifest=manifest)

    with pytest.raises(ValueError, match="canonical provider fragment mismatch"):
        ProjectAssembler(external_ids=_neutral_resource_ids()).assemble(
            (),
            artifact=artifact,
            provider_fragment=forged,
            provider_estimate=estimate,
            provider_input=_explicit_input(),
            scenario_kind="external",
        )


def test_provider_canonical_rebuild_rejects_forged_lbe_peak_pressure():
    artifact, estimate, fragment = _real_provider_rows("lbe_segment", _lbe_input())
    manifest = thaw_value(fragment.manifest)
    manifest["load"]["peak_pressure_pa"] = 999_999.0
    forged = replace(fragment, manifest=manifest)

    with pytest.raises(ValueError, match="canonical provider fragment mismatch"):
        ProjectAssembler().assemble(
            (),
            artifact=artifact,
            provider_fragment=forged,
            provider_estimate=estimate,
            provider_input=_lbe_input(),
            scenario_kind="external",
        )


def test_provider_canonical_rebuild_rejects_forged_imported_curve():
    artifact, estimate, fragment = _real_provider_rows(
        "imported_pressure_history", _imported_input()
    )
    manifest = thaw_value(fragment.manifest)
    manifest["normalized_curve_si"][1][1] = 9_999.0
    manifest["curve"]["normalized_curve_si"][1][1] = 9_999.0
    forged = replace(fragment, manifest=manifest)

    with pytest.raises(ValueError, match="canonical provider fragment mismatch"):
        ProjectAssembler().assemble(
            (),
            artifact=artifact,
            provider_fragment=forged,
            provider_estimate=estimate,
            provider_input=_imported_input(),
            scenario_kind="external",
        )


def test_provider_canonical_rebuild_rejects_cross_category_ale_ids():
    artifact, estimate, fragment = _real_provider_rows(
        "explicit_ale_fsi", _explicit_input()
    )
    forged = replace(
        fragment,
        node_ids=(fragment.element_ids[0], *fragment.node_ids[1:]),
    )

    with pytest.raises(ValueError, match="canonical provider fragment mismatch"):
        ProjectAssembler(external_ids=_neutral_resource_ids()).assemble(
            (),
            artifact=artifact,
            provider_fragment=forged,
            provider_estimate=estimate,
            provider_input=_explicit_input(),
            scenario_kind="external",
        )


def test_provider_canonical_rebuild_rejects_synchronized_lbe_budget_forgery():
    artifact, estimate, fragment = _real_provider_rows("lbe_segment", _lbe_input())
    forged_estimate = replace(
        estimate,
        budget_limits=MappingProxyType(
            {**dict(estimate.budget_limits), "max_surface_count": 101}
        ),
    )
    manifest = thaw_value(fragment.manifest)
    manifest["allocation"]["estimate"] = thaw_value(forged_estimate.to_manifest())
    forged_fragment = replace(fragment, manifest=manifest)

    with pytest.raises(ValueError, match="canonical provider estimate mismatch"):
        ProjectAssembler().assemble(
            (),
            artifact=artifact,
            provider_fragment=forged_fragment,
            provider_estimate=forged_estimate,
            provider_input=_lbe_input(),
            scenario_kind="external",
        )


def test_high_level_assembly_renders_building_mesh_and_preserves_artifact_fingerprint():
    artifact = _artifact()
    before = artifact.fingerprint
    package = assemble_refined_blast_project(_project(artifact), artifact)

    assert artifact.fingerprint == before == package.building_artifact_fingerprint
    building = package.files["01_building.k"].decode("utf-8")
    assert "*NODE" in building
    assert "*ELEMENT_SOLID" in building
    assert package.manifest["rendered_counts"]["building_nodes"] == 8
    assert package.manifest["rendered_counts"]["building_elements"] == 1
    assert package.manifest["solver_ready"] is False
    assert package.manifest["requires_project_review"] is True
    assert package.manifest["engineering_validated"] is False


@pytest.mark.parametrize(
    ("provider_id", "provider_input"),
    [
        ("explicit_ale_fsi", _explicit_input()),
        ("lbe_segment", _lbe_input()),
        ("imported_pressure_history", _imported_input()),
    ],
)
def test_high_level_assembly_accepts_real_fragments_from_all_load_providers(
    provider_id, provider_input
):
    artifact = _artifact()
    package = assemble_refined_blast_project(
        _project(artifact, provider_id=provider_id, provider_input=provider_input), artifact
    )

    assert package.manifest["provider_fingerprint"]
    assert package.manifest["building_artifact_fingerprint"] == artifact.fingerprint
    assert package.manifest["rendered_counts"]["provider_fsi_faces"] == 1


def test_scenario_change_invalidates_package_but_not_building_artifact():
    artifact = _artifact()
    first = assemble_refined_blast_project(_project(artifact, 250_000.0), artifact)
    second = assemble_refined_blast_project(_project(artifact, 300_000.0), artifact)

    assert first.building_artifact_fingerprint == second.building_artifact_fingerprint
    assert first.package_fingerprint != second.package_fingerprint
    assert first.files["01_building.k"] == second.files["01_building.k"]


def test_assembly_is_fresh_process_deterministic():
    script = r'''
import json
from lsprepost_mcp.refined_blast.assembler import ProjectAssembler
from lsprepost_mcp.refined_blast.fragments import KeywordFragment
fragment = KeywordFragment(
    module_id="placement",
    declared_ids=frozenset({"placement:a", "placement:b"}),
    required_ids=frozenset(),
    estimates={"new_nodes": 0, "new_elements": 0, "budget_limits": {"max_new_nodes": 2, "max_new_elements": 2}, "budget_checked_before_allocation": True},
    manifest={"unit_system": "SI_m_s_kg_N_Pa"},
)
package = ProjectAssembler().assemble((fragment,))
print(json.dumps({"fingerprint": package.package_fingerprint, "files": {k: v.decode("utf-8") for k, v in package.files.items()}}, sort_keys=True))
'''
    rows = []
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
        rows.append(json.loads(result.stdout))
    assert rows[0] == rows[1]
