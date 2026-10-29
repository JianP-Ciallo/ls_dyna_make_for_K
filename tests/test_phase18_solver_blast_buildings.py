from __future__ import annotations

import math
from functools import lru_cache
from dataclasses import replace

import pytest

from lsprepost_mcp.keyword_checks import hexa_gauss_jacobians
from lsprepost_mcp.refined_building import asset_templates
from lsprepost_mcp.refined_building.asset_compiler import (
    DetailedBuildingPackage,
    compile_detailed_building_asset,
)
from lsprepost_mcp.refined_building.artifacts import Node
from lsprepost_mcp.refined_building.meshing import (
    AxisAlignedBox,
    merge_fragments_welded,
    mesh_axis_aligned_block_excluding,
)
from lsprepost_mcp.refined_building.solver_blast import audit_physical_members
from lsprepost_mcp.refined_building.solver_blast.physical_building import (
    PhysicalBuildingModel,
    _commercial_column_boxes,
    audit_physical_building,
    build_physical_building,
)


COMMERCIAL = "commercial_supermarket_detailed_building"
RESIDENTIAL = "residential_community_detailed_building"
SUBWAY = "subway_entrance_detailed_building"


@lru_cache(maxsize=3)
def _package(resource_id: str) -> DetailedBuildingPackage:
    if resource_id == COMMERCIAL:
        return compile_detailed_building_asset(
            resource_id,
            legacy_geometry={
                "length_m": 6.0,
                "width_m": 4.0,
                "height_m": 4.0,
                "wall_thickness_m": 0.2,
                "entrance_width_m": 2.0,
                "entrance_height_m": 2.2,
            },
            mesh_profile="coarse",
            fidelity_profile="blast_response",
            generation_options={"rebar_spacing_m": 0.5},
        )
    if resource_id == RESIDENTIAL:
        return compile_detailed_building_asset(
            resource_id,
            legacy_geometry={
                "tower_count": 1,
                "tower_length_m": 4.0,
                "tower_width_m": 4.0,
                "tower_height_m": 6.0,
                "tower_spacing_m": 2.0,
                "wall_thickness_m": 0.2,
                "balcony_depth_m": 0.8,
            },
            mesh_profile="coarse",
            fidelity_profile="blast_response",
            generation_options={"storey_count": 2, "rebar_spacing_m": 0.5},
        )
    if resource_id == SUBWAY:
        return compile_detailed_building_asset(
            resource_id,
            legacy_geometry={
                "length_m": 4.0,
                "width_m": 3.0,
                "platform_height_m": 0.3,
                "enclosure_height_m": 2.4,
                "wall_thickness_m": 0.2,
                "roof_thickness_m": 0.2,
            },
            mesh_profile="coarse",
            fidelity_profile="blast_response",
            generation_options={"rebar_spacing_m": 0.5},
        )
    raise AssertionError(resource_id)


@pytest.mark.parametrize("resource_id", [COMMERCIAL, RESIDENTIAL, SUBWAY])
def test_solver_building_has_reviewed_load_path_and_element_families(
    resource_id: str,
) -> None:
    model = build_physical_building(_package(resource_id))
    assert isinstance(model, PhysicalBuildingModel)
    assert audit_physical_members(model.members) == ()
    assert model.load_path.foundation_roles
    assert model.load_path.vertical_roles
    assert model.load_path.floor_or_roof_roles
    assert model.load_path.continuous is True
    assert audit_physical_building(model) == ()
    interface_ids = {row.interface_id for row in model.interfaces}
    assert interface_ids
    for member in model.members:
        assert set(member.connection_ids) <= interface_ids


@pytest.mark.parametrize("resource_id", [COMMERCIAL, RESIDENTIAL, SUBWAY])
def test_physical_interfaces_have_measured_or_artifact_connection_evidence(
    resource_id: str,
) -> None:
    model = build_physical_building(_package(resource_id))
    for interface in model.interfaces:
        assert interface.source_roles
        assert interface.target_roles
        assert interface.source_element_count > 0
        assert interface.target_element_count > 0
        assert (
            interface.shared_node_count > 0
            or interface.positive_contact_area_m2 > 0.0
            or interface.positive_contact_length_m > 0.0
            or interface.connection_type == "artifact_constraint"
        )


def test_commercial_opaque_facade_is_solid_while_thin_roof_and_frame_remain_physical() -> None:
    package = _package(COMMERCIAL)
    original_fingerprint = package.package_fingerprint
    model = build_physical_building(package)
    assert model.family_for_role("opaque_facade") == "Solid"
    assert model.family_for_role("steel_roof_deck") == "Shell"
    assert model.family_for_role("commercial_rc_column") == "Solid"
    assert model.family_for_role("commercial_column_longitudinal_rebar") == "Beam"
    assert model.family_for_role("commercial_column_stirrup") == "Beam"
    assert "steel_column" in model.excluded_base_part_roles
    assert "steel_opening_jamb" in model.excluded_base_part_roles
    assert "steel_opening_header" in model.excluded_base_part_roles
    assert "nonstructural_facade" in model.excluded_base_part_roles
    assert sum(len(row.solids) for row in model.supplement_fragments) > 0
    assert any(
        interface.connection_type == "shared_node_weld_on_assembly"
        and "opaque_facade" in interface.source_roles
        and interface.shared_node_count > 0
        for interface in model.interfaces
    )
    assert package.package_fingerprint == original_fingerprint


def test_commercial_columns_are_solid_hosts_with_longitudinal_bars_and_closed_stirrups() -> None:
    model = build_physical_building(_package(COMMERCIAL))
    fragments = model.supplement_fragments
    solid_count = sum(
        element.part_role == "commercial_rc_column"
        for fragment in fragments
        for element in fragment.solids
    )
    longitudinal = tuple(
        element
        for fragment in fragments
        for element in fragment.beams
        if element.part_role == "commercial_column_longitudinal_rebar"
    )
    stirrups = tuple(
        element
        for fragment in fragments
        for element in fragment.beams
        if element.part_role == "commercial_column_stirrup"
    )
    assert solid_count > 0
    assert longitudinal
    assert stirrups
    assert all(
        abs(nodes[element.node_ids[0]].z - nodes[element.node_ids[1]].z) > 0.0
        and nodes[element.node_ids[0]].x == pytest.approx(nodes[element.node_ids[1]].x)
        and nodes[element.node_ids[0]].y == pytest.approx(nodes[element.node_ids[1]].y)
        for fragment in fragments
        for nodes in ({node.node_id: node for node in fragment.nodes},)
        for element in fragment.beams
        if element.part_role == "commercial_column_longitudinal_rebar"
    )
    assert all(
        nodes[element.node_ids[0]].z == pytest.approx(nodes[element.node_ids[1]].z)
        for fragment in fragments
        for nodes in ({node.node_id: node for node in fragment.nodes},)
        for element in fragment.beams
        if element.part_role == "commercial_column_stirrup"
    )
    embedded = {
        (row.source_roles, row.target_roles)
        for row in model.interfaces
        if row.connection_type == "embedded_beam_in_solid"
    }
    assert (("commercial_column_longitudinal_rebar",), ("commercial_rc_column",)) in embedded
    assert (("commercial_column_stirrup",), ("commercial_rc_column",)) in embedded


def test_commercial_column_sections_preserve_axes_and_clear_declared_entrance() -> None:
    package = _package(COMMERCIAL)
    boxes = _commercial_column_boxes(package)
    assert boxes
    assert all(box.max_x - box.min_x == pytest.approx(0.3) for box in boxes)
    assert all(box.max_y - box.min_y == pytest.approx(0.3) for box in boxes)
    assert any((box.min_x + box.max_x) / 2.0 == pytest.approx(1.5) for box in boxes)
    assert any(box.max_x == pytest.approx(2.0) for box in boxes)
    assert any(box.min_x == pytest.approx(4.0) for box in boxes)
    opening = package.artifacts[0].normalized_input["openings"][0]["bounds_m"]
    assert all(
        not all(
            min(box.as_tuple()[axis + 3], opening[axis + 3])
            - max(box.as_tuple()[axis], opening[axis])
            > 1.0e-10
            for axis in range(3)
        )
        for box in boxes
    )
    column_record = next(
        row
        for row in build_physical_building(package).members
        if row.role == "commercial_rc_column"
    )
    assert "exterior building boundary" in column_record.selection_basis
    assert "outer-face lines shifted inward" in column_record.selection_basis


def test_commercial_solid_facade_has_both_reinforcement_directions_clear_of_openings() -> None:
    package = _package(COMMERCIAL)
    model = build_physical_building(package)
    fragments = model.supplement_fragments
    roles = {
        element.part_role
        for fragment in fragments
        for element in fragment.beams
    }
    assert "commercial_wall_vertical_rebar" in roles
    assert "commercial_wall_horizontal_rebar" in roles
    opening_rows = package.artifacts[0].normalized_input["openings"]
    exterior_openings = tuple(
        row["bounds_m"] for row in opening_rows if "exterior" in row.get("connects", ())
    )
    for fragment in fragments:
        nodes = {node.node_id: node for node in fragment.nodes}
        for element in fragment.beams:
            if element.part_role not in {
                "commercial_wall_vertical_rebar",
                "commercial_wall_horizontal_rebar",
            }:
                continue
            left, right = (nodes[node_id] for node_id in element.node_ids)
            midpoint = (
                (left.x + right.x) / 2.0,
                (left.y + right.y) / 2.0,
                (left.z + right.z) / 2.0,
            )
            assert not any(
                bounds[0] < midpoint[0] < bounds[3]
                and bounds[1] - 1.0e-12 < midpoint[1] < bounds[4] + 1.0e-12
                and bounds[2] < midpoint[2] < bounds[5]
                for bounds in exterior_openings
            )


def test_residential_solver_envelope_closes_unplanned_storey_gaps() -> None:
    model = build_physical_building(_package(RESIDENTIAL))
    assert model.family_for_role("opaque_facade") == "Solid"
    assert "nonstructural_facade" in model.excluded_base_part_roles
    assert "nonstructural_balcony_slab" in model.excluded_base_part_roles
    assert model.unplanned_exterior_gap_intervals_m == ()
    assert model.declared_opening_count > 0


def test_opening_boundary_does_not_create_roundoff_sliver_before_welding() -> None:
    wall = mesh_axis_aligned_block_excluding(
        AxisAlignedBox(0.0, 0.0, 0.2, 4.0, 0.2, 2.8),
        0.1,
        "opaque_facade",
        (AxisAlignedBox(0.8, 0.0, 1.2, 3.2, 0.2, 2.2),),
    )

    welded = merge_fragments_welded((wall,))

    assert all(len(set(element.node_ids)) == 8 for element in welded.solids)


def test_pavilion_profile_prefers_stair_break_over_nearby_regular_bay() -> None:
    values = asset_templates._merge_physical_profile_breaks(
        hard_bounds=(0.0, 5.0),
        priority_breaks=(1.7973174555521587, 2.512369611108685),
        regular_breaks=(0.4, 1.1, 1.8, 2.5, 3.2, 3.9, 4.6),
        minimum_span_m=0.05,
    )

    assert 1.7973174555521587 in values
    assert 2.512369611108685 in values
    assert 1.8 not in values
    assert 2.5 not in values
    assert min(right - left for left, right in zip(values, values[1:])) >= 0.05


def test_subway_publishes_real_grade_above_below_grade_rc_box() -> None:
    model = build_physical_building(_package(SUBWAY))
    circulation = _package(SUBWAY).geometry_manifest["subway_circulation"]
    expected_grade = circulation["walkable_surface_elevations_m"]["upper_landing"]
    below_grade_bounds = circulation["below_grade_rc_enclosure_bounds_m"]
    assert model.grade_elevation_m == pytest.approx(expected_grade)
    assert model.grade_elevation_m < below_grade_bounds[5]
    assert model.family_for_role("rc_box_wall") == "Solid"
    assert model.family_for_role("pavilion_glazing") == "Shell"
    assert model.family_for_role("pavilion_frame") == "Beam"
    assert model.family_for_role("pavilion_opaque_solid_roof") == "Solid"
    assert "pavilion_metal_roof" in model.excluded_base_part_roles
    assert "generic_signage" in model.excluded_base_part_roles
    assert "nonstructural_architectural_finish" in model.excluded_base_part_roles
    assert all(member.role != "generic_signage" for member in model.members)
    glazing_ties = tuple(
        interface
        for interface in model.interfaces
        if interface.connection_type == "tied_shell_edge_to_frame"
        and interface.source_roles == ("pavilion_glazing",)
        and interface.target_roles == ("pavilion_frame",)
    )
    assert len(glazing_ties) == 1
    assert glazing_ties[0].positive_contact_length_m > 0.0
    assert glazing_ties[0].maximum_gap_m <= glazing_ties[0].connection_tolerance_m


def test_subway_solid_opaque_roof_has_positive_gauss_point_jacobians() -> None:
    package = _package(SUBWAY)
    model = build_physical_building(package)
    roof_fragments = tuple(
        fragment
        for fragment in model.supplement_fragments
        if any(row.part_role == "pavilion_opaque_solid_roof" for row in fragment.solids)
    )
    assert len(roof_fragments) == 1
    roof = roof_fragments[0]
    nodes = {node.node_id: node.coordinates for node in roof.nodes}
    assert all(
        min(hexa_gauss_jacobians(nodes, element.node_ids)) > 0.0
        for element in roof.solids
    )
    source = package.artifacts[0]
    source_nodes = {node.node_id: node.coordinates for node in source.mesh.nodes}
    used_ids = sorted(
        {
            node_id
            for element in source.mesh.shells
            if element.part_role == "pavilion_metal_roof"
            for node_id in element.node_ids
        }
    )
    half = len(used_ids)
    roof_nodes = {node.node_id: node.coordinates for node in roof.nodes}
    thickness = package.generation_options.get("pavilion_roof_thickness_m", 0.05)
    support_ids = {
        node_id
        for element in source.mesh.solids
        if element.part_role == "rc_box_roof"
        for node_id in element.node_ids
    }
    support_clearance_z = max(
        0.0,
        max(source_nodes[node_id][2] for node_id in support_ids)
        - min(source_nodes[node_id][2] for node_id in used_ids),
    )
    for index, source_id in enumerate(used_ids, start=1):
        bottom = roof_nodes[index]
        top = roof_nodes[half + index]
        expected_bottom = (
            source_nodes[source_id][0],
            source_nodes[source_id][1],
            source_nodes[source_id][2] + support_clearance_z,
        )
        assert bottom == pytest.approx(expected_bottom)
        assert math.dist(bottom, top) == pytest.approx(thickness)
        assert top[2] > bottom[2]
    assert any(
        row.connection_type == "tied_solid_nodes_to_frame"
        and row.source_roles == ("pavilion_opaque_solid_roof",)
        and row.target_roles == ("pavilion_frame",)
        for row in model.interfaces
    )


def test_physical_building_fingerprint_is_deterministic() -> None:
    package = _package(COMMERCIAL)
    assert build_physical_building(package).fingerprint == build_physical_building(
        package
    ).fingerprint


def test_physical_audit_rejects_missing_commercial_horizontal_wall_rebar() -> None:
    model = build_physical_building(_package(COMMERCIAL))
    forged = replace(
        model,
        members=tuple(
            row for row in model.members if row.role != "commercial_wall_horizontal_rebar"
        ),
    )

    assert "commercial_required_physics_missing" in {
        row.finding_id for row in audit_physical_building(forged)
    }


def test_physical_audit_rejects_commercial_rebar_that_leaves_its_solid_host() -> None:
    model = build_physical_building(_package(COMMERCIAL))
    fragment_index = next(
        index
        for index, fragment in enumerate(model.supplement_fragments)
        if any(
            element.part_role == "commercial_wall_horizontal_rebar"
            for element in fragment.beams
        )
    )
    fragment = model.supplement_fragments[fragment_index]
    beam = next(
        element
        for element in fragment.beams
        if element.part_role == "commercial_wall_horizontal_rebar"
    )
    forged_coordinates = {
        beam.node_ids[0]: (3.0, 0.1, 1.0),
        beam.node_ids[1]: (3.5, 0.1, 1.0),
    }
    forged_nodes = tuple(
        Node(node.node_id, *forged_coordinates[node.node_id])
        if node.node_id in forged_coordinates
        else node
        for node in fragment.nodes
    )
    forged_fragment = replace(fragment, nodes=forged_nodes)
    forged_fragments = list(model.supplement_fragments)
    forged_fragments[fragment_index] = forged_fragment
    forged = replace(model, supplement_fragments=tuple(forged_fragments))

    assert "commercial_rebar_not_contained" in {
        row.finding_id for row in audit_physical_building(forged)
    }


def test_physical_audit_recomputes_closed_commercial_stirrup_topology() -> None:
    model = build_physical_building(_package(COMMERCIAL))
    fragment_index = next(
        index
        for index, fragment in enumerate(model.supplement_fragments)
        if any(
            element.part_role == "commercial_column_stirrup"
            for element in fragment.beams
        )
    )
    fragment = model.supplement_fragments[fragment_index]
    removed = next(
        element
        for element in fragment.beams
        if element.part_role == "commercial_column_stirrup"
    )
    forged_fragment = replace(
        fragment,
        beams=tuple(element for element in fragment.beams if element != removed),
    )
    forged_fragments = list(model.supplement_fragments)
    forged_fragments[fragment_index] = forged_fragment
    forged = replace(model, supplement_fragments=tuple(forged_fragments))

    assert "commercial_column_stirrup_not_closed" in {
        row.finding_id for row in audit_physical_building(forged)
    }


def test_physical_audit_recomputes_subway_roof_frame_geometry() -> None:
    model = build_physical_building(_package(SUBWAY))
    interface_index = next(
        index
        for index, row in enumerate(model.interfaces)
        if row.connection_type == "tied_solid_nodes_to_frame"
    )
    forged_interfaces = list(model.interfaces)
    forged_interfaces[interface_index] = replace(
        forged_interfaces[interface_index],
        maximum_gap_m=forged_interfaces[interface_index].maximum_gap_m * 0.5,
    )
    forged = replace(model, interfaces=tuple(forged_interfaces))

    assert "subway_roof_frame_geometry_not_closed" in {
        row.finding_id for row in audit_physical_building(forged)
    }
