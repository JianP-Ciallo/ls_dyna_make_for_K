from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache

import pytest

from lsprepost_mcp.refined_building.solver_blast import (
    build_solver_blast_scene,
    classify_surface_topology,
    extract_fsi_segments,
    inspect_solver_blast_deck,
    normalize_solver_blast_config,
    write_solver_blast_deck,
)
from lsprepost_mcp.refined_building.solver_blast.materials import (
    CONCRETE_MATERIAL_ID,
    ELASTIC_RC_MATERIAL_ID,
    GLASS_MATERIAL_ID,
    NONSTRUCTURAL_MATERIAL_ID,
    STEEL_MATERIAL_ID,
    material_id_for_role,
)
from test_phase18_solver_blast_scene import COMMERCIAL, SUBWAY, _config, _model


SURFACE_CLASS_ORDER = (
    "external_air_exposed",
    "internal_air_exposed",
    "soil_contact",
    "sealed_internal",
    "structural_connection",
)
SURFACE_TOPOLOGY_MANIFEST_KEYS = {
    "schema_version",
    "fingerprint",
    "counts",
    "boundary_face_count",
    "unclassified_count",
    "multiply_classified_count",
}
MESH_QUALITY_MANIFEST_KEYS = {
    "schema_version",
    "fingerprint",
    "solid_count",
    "shell_count",
    "beam_count",
    "minimum_corner_jacobian_m3",
    "maximum_aspect_ratio",
    "orphan_node_count",
    "duplicate_element_count",
    "solid_overlap_pair_count",
    "unresolved_overlap_candidate_count",
    "finding_count",
}


@lru_cache(maxsize=1)
def _scene():
    return build_solver_blast_scene(_model(COMMERCIAL), _config())


@lru_cache(maxsize=1)
def _subway_scene():
    model = _model(SUBWAY)
    return build_solver_blast_scene(
        model,
        _config(position=(-1.0, 2.0, model.grade_elevation_m + 1.0)),
    )


@pytest.mark.parametrize(
    ("role", "material_id"),
    [
        ("rc_beam_x_material", ELASTIC_RC_MATERIAL_ID),
        ("rc_foundation_material", ELASTIC_RC_MATERIAL_ID),
        ("pavilion_rc_plinth_material", ELASTIC_RC_MATERIAL_ID),
        ("fixed_stair_A_material", ELASTIC_RC_MATERIAL_ID),
        ("lower_landing_8_material", ELASTIC_RC_MATERIAL_ID),
        ("upper_landing_material", ELASTIC_RC_MATERIAL_ID),
        ("metal_roof", STEEL_MATERIAL_ID),
        ("escalator_equipment", STEEL_MATERIAL_ID),
        ("escalator_balustrade", GLASS_MATERIAL_ID),
        ("escalator_handrail", NONSTRUCTURAL_MATERIAL_ID),
        ("nonstructural", NONSTRUCTURAL_MATERIAL_ID),
    ],
)
def test_structural_material_roles_resolve_to_physical_presets(
    role: str,
    material_id: int,
) -> None:
    assert material_id_for_role(role) == material_id


def test_fsi_uses_welded_unique_building_mesh_and_real_positive_segments() -> None:
    scene = _scene()
    interface = extract_fsi_segments(scene)
    source_node_count = sum(
        len(artifact.mesh.nodes) for artifact in scene.building.artifacts
    ) + sum(len(fragment.nodes) for fragment in scene.building.supplement_fragments)

    assert len(interface.building_mesh.nodes) < source_node_count
    assert len({row.node_id for row in interface.building_mesh.nodes}) == len(
        interface.building_mesh.nodes
    )
    elements = (
        *interface.building_mesh.solids,
        *interface.building_mesh.shells,
        *interface.building_mesh.beams,
    )
    assert len({row.element_id for row in elements}) == len(elements)
    assert interface.segments
    assert all(row.area_m2 > 0.0 for row in interface.segments)
    assert len({tuple(sorted(row.node_ids)) for row in interface.segments}) == len(
        interface.segments
    )


def test_welded_building_mesh_contains_no_orphan_nodes() -> None:
    mesh = extract_fsi_segments(_scene()).building_mesh
    used_node_ids = {
        node_id
        for element in (*mesh.solids, *mesh.shells, *mesh.beams)
        for node_id in element.node_ids
    }

    assert {node.node_id for node in mesh.nodes} == used_node_ids


def test_subway_fsi_classifies_circulation_and_plinth_by_face_location() -> None:
    scene = _subway_scene()
    topology = classify_surface_topology(scene)
    interface = extract_fsi_segments(scene, topology)
    coupled_roles = {row.owner_part_role for row in interface.segments}

    assert {
        "fixed_stair_A",
        "escalator_1_step_band",
        "escalator_2_step_band",
        "pavilion_rc_plinth",
        "upper_landing",
    }.issubset(coupled_roles)
    assert coupled_roles.isdisjoint(
        {
            "lower_landing_8",
            "escalator_1_truss_guides",
            "escalator_2_truss_guides",
        }
    )
    plinth_classes = {
        row.surface_class
        for row in topology.surfaces
        if row.owner_part_role == "pavilion_rc_plinth"
    }
    upper_landing_classes = {
        row.surface_class
        for row in topology.surfaces
        if row.owner_part_role == "upper_landing"
    }
    assert {"soil_contact", "external_air_exposed"} <= plinth_classes
    assert {"internal_air_exposed", "sealed_internal"} <= upper_landing_classes
    coupled_keys = {
        (row.owner_element_id, tuple(sorted(row.node_ids)))
        for row in interface.segments
    }
    non_exposed_keys = {
        (row.owner_element_id, row.face_key)
        for row in topology.surfaces
        if row.surface_class
        not in {"external_air_exposed", "internal_air_exposed"}
    }
    assert coupled_keys.isdisjoint(non_exposed_keys)
    assert {"rc_box_wall", "rc_box_roof", "pavilion_glazing"}.issubset(
        coupled_roles
    )


def test_solver_complete_deck_contains_real_ale_tnt_fsi_and_closed_evidence(
    tmp_path,
) -> None:
    scene = _scene()
    evidence = write_solver_blast_deck(scene, tmp_path)
    model_path = tmp_path / "model.k"
    payload = model_path.read_bytes()
    text = payload.decode("utf-8")

    for card in (
        "*MAT_NULL",
        "*EOS_LINEAR_POLYNOMIAL",
        "*MAT_HIGH_EXPLOSIVE_BURN",
        "*EOS_JWL",
        "*ALE_MULTI-MATERIAL_GROUP",
        "*INITIAL_DETONATION",
        "*CONSTRAINED_LAGRANGE_IN_SOLID",
        "*BOUNDARY_NON_REFLECTING",
        "*DATABASE_FSI",
        "*CONSTRAINED_INTERPOLATION",
        "*CONSTRAINED_BEAM_IN_SOLID",
        "*MAT_ADD_EROSION",
    ):
        assert card in text
    assert "*INITIAL_VOLUME_FRACTION_GEOMETRY" not in text
    assert text.startswith("*KEYWORD\n")
    assert text.rstrip().endswith("*END")
    assert "*DATABASE_ALE\n" not in text
    assert "*DATABASE_ALE_MAT\n" in text
    assert "*DATABASE_HISTORY_SOLID_SET\n" in text
    assert evidence.model_sha256 == hashlib.sha256(payload).hexdigest()
    assert evidence.model_byte_count == len(payload)
    assert evidence.fsi_slave_segment_count > 0
    assert evidence.ground_fsi_segment_count > 0
    assert evidence.total_fsi_segment_count == (
        evidence.fsi_slave_segment_count + evidence.ground_fsi_segment_count
    )
    assert evidence.ale_node_count == scene.air.node_count
    assert evidence.ale_element_count == scene.air.element_count
    assert evidence.ale_air_element_count == scene.air.air_element_count
    assert evidence.ale_buffer_element_count == scene.air.buffer_element_count
    assert evidence.tnt_element_count == scene.air.tnt_element_count
    nx = len(scene.air.x_coordinates) - 1
    ny = len(scene.air.y_coordinates) - 1
    nz = len(scene.air.z_coordinates) - 1
    assert evidence.side_nonreflecting_segment_count == 2 * nz * (nx + ny)
    assert evidence.top_nonreflecting_segment_count == nx * ny
    assert evidence.bottom_nonreflecting_segment_count == 0
    assert evidence.bottom_no_flow_segment_count == nx * ny
    assert evidence.bottom_closed_node_count == (nx + 1) * (ny + 1)
    assert evidence.mesh_quality_finding_count == 0
    assert evidence.mesh_quality_orphan_node_count == 0
    assert evidence.mesh_quality_duplicate_element_count == 0
    assert evidence.mesh_quality_solid_overlap_pair_count == 0
    assert evidence.mesh_quality_unresolved_overlap_candidate_count == 0
    assert evidence.mesh_quality_minimum_corner_jacobian_m3 > 0.0
    assert evidence.mesh_quality_maximum_aspect_ratio >= 1.0
    assert evidence.engineering_validated is False
    assert evidence.requires_project_review is True
    manifest = json.loads(evidence.manifest_path.read_text(encoding="utf-8"))
    assert manifest["fsi_slave_segment_count"] == evidence.fsi_slave_segment_count
    assert manifest["ground_fsi_segment_count"] == evidence.ground_fsi_segment_count
    assert manifest["total_fsi_segment_count"] == evidence.total_fsi_segment_count
    assert manifest["materials"]["erosion_mode"] == "standard_observation"
    assert manifest["materials"]["erosion_maximum_principal_strain"] == 0.05
    assert manifest["charge"]["geometry_kind"] == "mass_conserving_cuboid"
    assert manifest["charge"]["solid_element_count"] == scene.air.tnt_element_count
    assert manifest["charge"]["realized_mass_kg"] == pytest.approx(
        scene.charge.mass_kg
    )
    assert manifest["schema_version"] == "phase18.solver_blast.deck_manifest@4"
    quality = manifest["mesh_quality"]
    assert set(quality) == MESH_QUALITY_MANIFEST_KEYS
    assert quality["schema_version"] == "phase18.solver_blast.mesh_quality@1"
    assert quality["fingerprint"] == evidence.mesh_quality_fingerprint
    assert quality["solid_count"] + quality["shell_count"] + quality["beam_count"] == (
        evidence.total_element_count
        - evidence.ale_element_count
        - sum(len(fragment.solids) for fragment in scene.ground.fragments)
    )
    assert quality["finding_count"] == 0
    assert (
        "$P18MQ=" + evidence.mesh_quality_fingerprint
        in text.splitlines()
    )


def test_deck_evidence_and_manifest_close_the_classified_surface_topology(
    tmp_path,
) -> None:
    scene = _scene()
    evidence = write_solver_blast_deck(scene, tmp_path)

    assert len(evidence.surface_topology_fingerprint) == 64
    int(evidence.surface_topology_fingerprint, 16)
    from lsprepost_mcp.refined_building.solver_blast.surface_topology import (
        classify_surface_topology,
    )

    topology = classify_surface_topology(scene)
    expected_counts = tuple(
        (surface_class, topology.counts[surface_class])
        for surface_class in SURFACE_CLASS_ORDER
    )
    assert evidence.surface_topology_fingerprint == topology.fingerprint
    assert evidence.surface_class_counts == expected_counts
    assert evidence.surface_boundary_face_count == topology.boundary_face_count
    assert evidence.surface_unclassified_count == topology.unclassified_count
    assert (
        evidence.surface_multiply_classified_count
        == topology.multiply_classified_count
    )
    assert evidence.fsi_slave_segment_count == (
        topology.counts["external_air_exposed"]
        + topology.counts["internal_air_exposed"]
    )

    manifest = json.loads(evidence.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "phase18.solver_blast.deck_manifest@4"
    persisted = manifest["surface_topology"]
    assert set(persisted) == SURFACE_TOPOLOGY_MANIFEST_KEYS
    assert persisted == {
        "schema_version": "phase18.solver_blast.surface_topology@1",
        "fingerprint": topology.fingerprint,
        "counts": [list(row) for row in expected_counts],
        "boundary_face_count": topology.boundary_face_count,
        "unclassified_count": topology.unclassified_count,
        "multiply_classified_count": topology.multiply_classified_count,
    }


def test_fsi_removes_initial_immersed_penetration_before_penalty_loading(tmp_path) -> None:
    evidence = write_solver_blast_deck(_scene(), tmp_path)
    lines = evidence.model_path.read_text(encoding="utf-8").splitlines()
    marker = lines.index("*CONSTRAINED_LAGRANGE_IN_SOLID")

    assert lines[marker + 2] == "92001,91001,2,0,1,4,2,0"
    assert lines[marker + 7] == "$#   iboxid   ipenchk   intforc   ialesof    lagmul    pfacmm       thk"
    assert lines[marker + 8] == "0,1,0,0,0,0,0"
    assert inspect_solver_blast_deck(tmp_path).ok is True


def test_r12_interpolation_cards_use_only_positive_weights_that_close(tmp_path) -> None:
    evidence = write_solver_blast_deck(_scene(), tmp_path)
    lines = evidence.model_path.read_text(encoding="utf-8").splitlines()
    markers = [index for index, line in enumerate(lines) if line == "*CONSTRAINED_INTERPOLATION"]

    assert markers
    for marker in markers:
        rows = []
        cursor = marker + 4
        while cursor < len(lines) and not lines[cursor].startswith("*"):
            rows.append(lines[cursor])
            cursor += 1
        weights = [float(row[20:30]) for row in rows]
        assert weights
        assert all(0.0 < weight <= 1.0 for weight in weights)
        assert math.isclose(math.fsum(weights), 1.0, rel_tol=0.0, abs_tol=2.0e-8)
        assert all(float(row[30:40]) == weights[index] for index, row in enumerate(rows))
        assert all(float(row[40:50]) == weights[index] for index, row in enumerate(rows))


def test_fsi_includes_real_exposed_ground_faces_but_not_far_soil_boundaries() -> None:
    scene = _scene()
    interface = extract_fsi_segments(scene)
    bounds = scene.ground.bounds_m
    nodes = {
        node.node_id: node
        for fragment in scene.ground.fragments
        for node in fragment.nodes
    }

    assert interface.ground_segments
    assert all(
        row.owner_part_role == scene.ground.part_role
        for row in interface.ground_segments
    )
    assert all(row.area_m2 > 0.0 for row in interface.ground_segments)
    for segment in interface.ground_segments:
        points = tuple(nodes[node_id] for node_id in segment.node_ids)
        assert not all(abs(node.x - bounds[0]) <= 1.0e-10 for node in points)
        assert not all(abs(node.x - bounds[3]) <= 1.0e-10 for node in points)
        assert not all(abs(node.y - bounds[1]) <= 1.0e-10 for node in points)
        assert not all(abs(node.y - bounds[4]) <= 1.0e-10 for node in points)
        assert not all(abs(node.z - bounds[2]) <= 1.0e-10 for node in points)


def test_ground_contact_faces_are_not_published_as_air_fsi() -> None:
    scene = _scene()
    interface = extract_fsi_segments(scene)
    nodes = {row.node_id: row for row in interface.building_mesh.nodes}
    grade = scene.ground.grade_elevation_m

    assert interface.building_ground_contact_segments
    assert interface.ground_contact_segments
    assert all(
        row.owner_part_role == scene.ground.part_role
        for row in interface.ground_contact_segments
    )

    for segment in interface.segments:
        coordinates = tuple(nodes[node_id].coordinates for node_id in segment.node_ids)
        assert not (
            max(point[2] for point in coordinates) <= grade + 1.0e-10
            and segment.normal[2] < -0.5
        )


def test_subway_buried_outer_box_faces_are_not_published_as_air_fsi() -> None:
    scene = _subway_scene()
    interface = extract_fsi_segments(scene)
    nodes = {row.node_id: row for row in interface.building_mesh.nodes}
    bounds = scene.building.bounds_m
    tolerance = 1.0e-10

    for segment in interface.segments:
        points = tuple(nodes[node_id] for node_id in segment.node_ids)
        below_grade = max(node.z for node in points) <= scene.ground.grade_elevation_m + tolerance
        on_buried_outer_plane = any(
            all(abs(getattr(node, axis) - value) <= tolerance for node in points)
            for axis, value in (
                ("x", bounds[0]),
                ("x", bounds[3]),
                ("y", bounds[1]),
                ("y", bounds[4]),
                ("z", bounds[2]),
            )
        )
        assert not (below_grade and on_buried_outer_plane)


def test_subway_glazing_edge_connection_uses_r12_interpolation_to_frame_beams(
    tmp_path,
) -> None:
    evidence = write_solver_blast_deck(_subway_scene(), tmp_path)
    part_roles = set(dict(evidence.part_ids))
    lines = evidence.model_path.read_text(encoding="utf-8").splitlines()
    mesh = extract_fsi_segments(_subway_scene()).building_mesh
    glazing_nodes = {
        node_id
        for element in mesh.shells
        if element.part_role == "pavilion_glazing"
        for node_id in element.node_ids
    }
    frame_nodes = {
        node_id
        for element in mesh.beams
        if element.part_role == "pavilion_frame"
        for node_id in element.node_ids
    }
    markers = [
        index
        for index, line in enumerate(lines)
        if line == "*CONSTRAINED_INTERPOLATION"
    ]

    assert markers
    assert "pavilion_opaque_solid_roof" in part_roles
    assert "pavilion_metal_roof" not in part_roles
    assert "*CONTACT_TIED_SHELL_EDGE_TO_SURFACE_BEAM_OFFSET" not in lines
    dependent_nodes = set()
    for marker in markers:
        identity = lines[marker + 2]
        dependent = int(identity[10:20])
        if dependent not in glazing_nodes:
            continue
        independent_rows = []
        cursor = marker + 4
        while cursor < len(lines) and not lines[cursor].startswith("*"):
            independent_rows.append(lines[cursor])
            cursor += 1
        assert len(identity) == 30
        assert 1 <= len(independent_rows) <= 2
        assert all(len(value) == 80 for value in independent_rows)
        dependent_nodes.add(dependent)
        assert int(identity[20:30]) == 123
        assert all(int(value[:10]) in frame_nodes for value in independent_rows)
        assert all(int(value[10:20]) == 123 for value in independent_rows)
        weights = [float(value[20:30]) for value in independent_rows]
        assert all(weight > 0.0 for weight in weights)
        assert math.isclose(math.fsum(weights), 1.0, rel_tol=0.0, abs_tol=2.0e-8)
    assert dependent_nodes <= glazing_nodes


def test_subway_building_soil_contact_assigns_each_node_to_one_ground_interpolation(
    tmp_path,
) -> None:
    evidence = write_solver_blast_deck(_subway_scene(), tmp_path)
    lines = evidence.model_path.read_text(encoding="utf-8").splitlines()
    interface = extract_fsi_segments(_subway_scene())
    building_contact_nodes = {
        node_id
        for segment in interface.building_ground_contact_segments
        for node_id in segment.node_ids
    }
    ground_contact_nodes = {
        node_id
        for segment in interface.ground_contact_segments
        for node_id in segment.node_ids
    }
    dependent_nodes = []
    for marker, line in enumerate(lines):
        if line != "*CONSTRAINED_INTERPOLATION":
            continue
        identity = lines[marker + 2]
        dependent = int(identity[10:20])
        if dependent not in building_contact_nodes:
            continue
        dependent_nodes.append(dependent)
        assert int(identity[20:30]) == 123
        independent_rows = []
        cursor = marker + 4
        while cursor < len(lines) and not lines[cursor].startswith("*"):
            independent_rows.append(lines[cursor])
            cursor += 1
        assert 1 <= len(independent_rows) <= 4
        assert all(len(row) == 80 for row in independent_rows)
        assert all(int(row[:10]) in ground_contact_nodes for row in independent_rows)
        assert all(int(row[10:20]) == 123 for row in independent_rows)
        weights = [float(row[20:30]) for row in independent_rows]
        assert all(weight > 0.0 for weight in weights)
        assert math.isclose(math.fsum(weights), 1.0, rel_tol=0.0, abs_tol=2.0e-8)

    assert "*CONTACT_TIED_SURFACE_TO_SURFACE" not in lines
    assert set(dependent_nodes) == building_contact_nodes
    assert len(dependent_nodes) == len(set(dependent_nodes))


def test_deck_refuses_nonempty_output_directory(tmp_path) -> None:
    (tmp_path / "existing.txt").write_text("owned", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        write_solver_blast_deck(_scene(), tmp_path)


def test_r12_numeric_fields_fit_fixed_ten_character_columns(tmp_path) -> None:
    write_solver_blast_deck(_scene(), tmp_path)
    lines = (tmp_path / "model.k").read_text(encoding="utf-8").splitlines()
    marker = lines.index("$#     pid        x0        y0        z0        lt")
    values = lines[marker + 1].split(",")

    assert all(len(value) <= 10 for value in values)


def test_minimum_tnt_mass_identity_roundtrips_through_r12_fixed_width(tmp_path) -> None:
    config = normalize_solver_blast_config(
        {
            "schema_version": "phase18.solver_blast.config@1",
            "unit_system": "SI_m_s_kg_N_Pa",
            "tnt_equivalent_mass_kg": 0.1,
            "charge_position_m": [-1.0, 2.0, 4.0],
            "detonation_time_s": 0.0,
            "air_cell_size_m": 0.4,
            "air_margin_m": [3.0, 3.0, 3.0],
            "termination_time_s": 0.001,
        }
    )
    scene = build_solver_blast_scene(_model(COMMERCIAL), config)
    write_solver_blast_deck(scene, tmp_path)

    report = inspect_solver_blast_deck(tmp_path)

    assert report.ok is True
    assert report.charge_radius_m == pytest.approx(scene.charge.radius_m, rel=5.0e-8)
    assert report.air_element_count == scene.air.air_element_count
    assert report.tnt_element_count == scene.air.tnt_element_count
    assert report.tnt_element_count >= 27
    assert report.tnt_realized_mass_kg == pytest.approx(
        scene.air.realized_tnt_mass_kg
    )
    assert report.tnt_bounds_m == pytest.approx(scene.charge.bounds_m)


def test_concrete_rate_curve_and_database_fsi_reference_real_ids(tmp_path) -> None:
    evidence = write_solver_blast_deck(_scene(), tmp_path)
    lines = (tmp_path / "model.k").read_text(encoding="utf-8").splitlines()

    assert "*DEFINE_CURVE_TITLE" in lines
    database_index = lines.index("*DATABASE_FSI")
    referenced_part_id = int(lines[database_index + 2].split(",")[1])
    assert referenced_part_id in dict(evidence.part_ids).values()


def test_embedded_rebar_uses_r12_two_card_field_layout(tmp_path) -> None:
    evidence = write_solver_blast_deck(_scene(), tmp_path)
    lines = (tmp_path / "model.k").read_text(encoding="utf-8").splitlines()
    part_roles = set(dict(evidence.part_ids))
    marker = lines.index("*CONSTRAINED_BEAM_IN_SOLID")

    assert {
        "commercial_rc_column",
        "commercial_column_longitudinal_rebar",
        "commercial_column_stirrup",
        "commercial_wall_vertical_rebar",
        "commercial_wall_horizontal_rebar",
    } <= part_roles
    assert {"steel_column", "steel_opening_jamb", "steel_opening_header"}.isdisjoint(
        part_roles
    )
    identity_card = lines[marker + 2]
    option_card = lines[marker + 4]
    assert len(identity_card) == 80
    assert tuple(identity_card[index : index + 10].strip() for index in range(0, 80, 10)) == (
        "91002",
        "91003",
        "0",
        "0",
        "",
        "",
        "1",
        "0",
    )
    assert len(option_card) == 40
    assert tuple(option_card[index : index + 10].strip() for index in range(0, 40, 10)) == (
        "0",
        "0",
        "",
        "0",
    )


def test_embedded_beam_nodes_are_detached_from_all_solid_nodes() -> None:
    mesh = extract_fsi_segments(_scene()).building_mesh
    embedded_roles = {
        role
        for interface in _scene().building.interfaces
        if interface.connection_type == "embedded_beam_in_solid"
        for role in interface.source_roles
    }
    beam_node_ids = {
        node_id
        for element in mesh.beams
        if element.part_role in embedded_roles
        for node_id in element.node_ids
    }
    solid_node_ids = {
        node_id for element in mesh.solids for node_id in element.node_ids
    }

    assert beam_node_ids
    assert beam_node_ids.isdisjoint(solid_node_ids)

def test_r12_beams_reference_explicit_non_collinear_orientation_nodes(tmp_path) -> None:
    evidence = write_solver_blast_deck(_scene(), tmp_path)
    lines = evidence.model_path.read_text(encoding="utf-8").splitlines()
    node_marker = lines.index("*NODE")
    element_marker = lines.index("*ELEMENT_SOLID")
    nodes = {
        int(row.split(",")[0]): tuple(float(value) for value in row.split(",")[1:4])
        for row in lines[node_marker + 2 : element_marker]
    }
    beam_marker = lines.index("*ELEMENT_BEAM")
    beam_rows = []
    cursor = beam_marker + 2
    while cursor < len(lines) and not lines[cursor].startswith("*"):
        beam_rows.append(lines[cursor])
        cursor += 1

    assert beam_rows
    for row in beam_rows:
        values = tuple(int(row[index : index + 8]) for index in range(0, len(row), 8))
        assert len(values) == 5
        _, _, first_id, second_id, orientation_id = values
        first, second, orientation = nodes[first_id], nodes[second_id], nodes[orientation_id]
        axis = tuple(second[index] - first[index] for index in range(3))
        reference = tuple(orientation[index] - first[index] for index in range(3))
        cross = (
            axis[1] * reference[2] - axis[2] * reference[1],
            axis[2] * reference[0] - axis[0] * reference[2],
            axis[0] * reference[1] - axis[1] * reference[0],
        )
        assert math.sqrt(math.fsum(value * value for value in cross)) > 1.0e-8


def test_commercial_column_and_subway_roof_connections_render_as_interpolations(
    tmp_path,
) -> None:
    commercial_dir = tmp_path / "commercial"
    subway_dir = tmp_path / "subway"
    commercial = write_solver_blast_deck(_scene(), commercial_dir)
    subway = write_solver_blast_deck(_subway_scene(), subway_dir)

    for scene, evidence, source_role in (
        (_scene(), commercial, "commercial_rc_column"),
        (_subway_scene(), subway, "pavilion_opaque_solid_roof"),
    ):
        mesh = extract_fsi_segments(scene).building_mesh
        source_nodes = {
            node_id
            for element in mesh.solids
            if element.part_role == source_role
            for node_id in element.node_ids
        }
        lines = evidence.model_path.read_text(encoding="utf-8").splitlines()
        dependent_nodes = {
            int(lines[index + 2][10:20])
            for index, line in enumerate(lines)
            if line == "*CONSTRAINED_INTERPOLATION"
        }
        assert source_nodes & dependent_nodes


def test_tnt_is_rendered_as_explicit_solid_part_and_owns_detonation(tmp_path) -> None:
    scene = _scene()
    write_solver_blast_deck(scene, tmp_path)
    lines = (tmp_path / "model.k").read_text(encoding="utf-8").splitlines()
    solid_start = lines.index("*ELEMENT_SOLID") + 2
    solid_end = next(
        index
        for index in range(solid_start, len(lines))
        if lines[index].startswith("*")
    )
    solid_rows = [line for line in lines[solid_start:solid_end] if line and not line.startswith("$")]
    tnt_rows = [line for line in solid_rows if int(line[8:16]) == 9_002]
    air_rows = [line for line in solid_rows if int(line[8:16]) == 9_001]
    detonation = lines.index("*INITIAL_DETONATION")

    assert "*INITIAL_VOLUME_FRACTION_GEOMETRY" not in lines
    assert len(tnt_rows) == scene.air.tnt_element_count
    assert len(air_rows) == scene.air.air_element_count
    assert int(lines[detonation + 2].split(",")[0]) == 9_002


def test_element_cards_fit_r12_eighty_column_fixed_format(tmp_path) -> None:
    write_solver_blast_deck(_scene(), tmp_path)
    lines = (tmp_path / "model.k").read_text(encoding="utf-8").splitlines()
    first_ale = next(line for line in lines if line.startswith("50000001"))

    assert len(first_ale) == 80
    fields = tuple(int(first_ale[index : index + 8]) for index in range(0, 80, 8))
    assert fields[:2] == (50_000_001, 9_003)
    assert len(set(fields[2:])) == 8
    assert all(node_id >= 40_000_001 for node_id in fields[2:])
    assert first_ale == "".join(f"{value:>8d}" for value in fields)
