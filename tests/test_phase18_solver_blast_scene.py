from __future__ import annotations

import math
from functools import lru_cache

import pytest

from lsprepost_mcp.refined_building.solver_blast import (
    TNT_DENSITY_KG_PER_M3,
    build_solver_blast_scene,
    iter_ale_elements,
    iter_ale_nodes,
    normalize_solver_blast_config,
)
from lsprepost_mcp.refined_building.solver_blast.physical_building import (
    build_physical_building,
)
from lsprepost_mcp.refined_building.spatial import AxisAlignedBox
from test_phase18_solver_blast_buildings import (
    COMMERCIAL,
    RESIDENTIAL,
    SUBWAY,
    _package,
)


@lru_cache(maxsize=3)
def _model(resource_id: str):
    return build_physical_building(_package(resource_id))


def _config(
    *,
    position: tuple[float, float, float] = (-1.0, 2.0, 1.5),
    air_margin_m: tuple[float, float, float] = (3.0, 3.0, 3.0),
    ground_cell_size_m: float = 0.25,
):
    return normalize_solver_blast_config(
        {
            "schema_version": "phase18.solver_blast.config@2",
            "unit_system": "SI_m_s_kg_N_Pa",
            "tnt_equivalent_mass_kg": 2.0,
            "charge_position_m": list(position),
            "detonation_time_s": 0.0,
            "air_cell_size_m": 0.4,
            "ground_cell_size_m": ground_cell_size_m,
            "air_margin_m": list(air_margin_m),
            "termination_time_s": 0.001,
        }
    )


def test_visible_active_air_covers_footprint_stops_at_grade_and_resolves_charge() -> None:
    scene = build_solver_blast_scene(_model(COMMERCIAL), _config())
    building_box = AxisAlignedBox.from_bounds(scene.building.bounds_m)

    assert scene.air.part_role == "ale_active_air_domain"
    assert scene.air.buffer_part_role == "ale_coupling_buffer"
    assert scene.air.tnt_part_role == scene.charge.material_role
    assert scene.air.visible is True
    assert scene.air.active_air_bounds.min_x <= building_box.min_x
    assert scene.air.active_air_bounds.min_y <= building_box.min_y
    assert scene.air.active_air_bounds.max_x >= building_box.max_x
    assert scene.air.active_air_bounds.max_y >= building_box.max_y
    assert scene.air.active_air_bounds.max_z >= building_box.max_z
    assert scene.air.active_air_bounds.min_z == pytest.approx(
        scene.ground.grade_elevation_m
    )
    assert scene.air.coupling_buffer_bounds.max_z == pytest.approx(
        scene.ground.grade_elevation_m
    )
    assert scene.air.bounds.contains_point(scene.charge.position_m)
    assert scene.air.minimum_charge_diameter_cells >= 3.0
    assert scene.air_topology.buffer_cell_count == scene.air.buffer_element_count
    assert scene.ground.visible_surface_z_m == pytest.approx(
        scene.building.grade_elevation_m
    )
    assert scene.ground.positive_soil_structure_overlap_m3 == 0.0


@pytest.mark.parametrize("resource_id", [COMMERCIAL, RESIDENTIAL, SUBWAY])
def test_ground_xy_contains_entire_coupling_buffer_for_all_assets(
    resource_id: str,
) -> None:
    model = _model(resource_id)
    scene = build_solver_blast_scene(
        model,
        _config(position=(-2.0, 1.5, max(model.grade_elevation_m + 1.0, 4.0))),
    )
    ground = AxisAlignedBox.from_bounds(scene.ground.bounds_m)
    buffer = scene.air.coupling_buffer_bounds

    assert ground.min_x <= buffer.min_x
    assert ground.min_y <= buffer.min_y
    assert ground.max_x >= buffer.max_x
    assert ground.max_y >= buffer.max_y


def test_moving_charge_inside_fixed_air_domain_does_not_resize_domain() -> None:
    building = _model(COMMERCIAL)
    left = build_solver_blast_scene(
        building,
        _config(position=(-2.0, 1.5, 4.0)),
    )
    right = build_solver_blast_scene(
        building,
        _config(position=(-1.0, 2.5, 4.0)),
    )

    assert left.air.bounds.as_tuple() == pytest.approx(right.air.bounds.as_tuple())
    assert left.air.coupling_buffer_bounds.as_tuple() == pytest.approx(
        right.air.coupling_buffer_bounds.as_tuple()
    )


def test_tnt_radius_preserves_requested_mass() -> None:
    scene = build_solver_blast_scene(_model(COMMERCIAL), _config())

    recovered_mass = (
        4.0
        * math.pi
        * scene.charge.radius_m**3
        * TNT_DENSITY_KG_PER_M3
        / 3.0
    )
    assert recovered_mass == pytest.approx(scene.charge.mass_kg)


def test_explicit_tnt_solids_partition_the_ale_grid_and_preserve_mass() -> None:
    scene = build_solver_blast_scene(_model(COMMERCIAL), _config())
    nodes = {node.node_id: node for node in iter_ale_nodes(scene.air)}
    elements = tuple(iter_ale_elements(scene.air))
    air = tuple(row for row in elements if row.part_role == scene.air.part_role)
    buffer = tuple(
        row for row in elements if row.part_role == scene.air.buffer_part_role
    )
    tnt = tuple(row for row in elements if row.part_role == scene.air.tnt_part_role)

    assert tnt
    assert len(tnt) == scene.air.tnt_element_count
    assert len(air) == scene.air.air_element_count
    assert len(buffer) == scene.air.buffer_element_count
    assert len(elements) == scene.air.element_count
    assert len(air) + len(buffer) + len(tnt) == len(elements)
    assert {row.element_id for row in air}.isdisjoint(
        row.element_id for row in tnt
    )
    assert {row.element_id for row in buffer}.isdisjoint(
        row.element_id for row in (*air, *tnt)
    )
    assert scene.air.tnt_subdivisions_per_axis >= 3

    volume = math.fsum(
        (max(nodes[node_id].x for node_id in row.node_ids) - min(nodes[node_id].x for node_id in row.node_ids))
        * (max(nodes[node_id].y for node_id in row.node_ids) - min(nodes[node_id].y for node_id in row.node_ids))
        * (max(nodes[node_id].z for node_id in row.node_ids) - min(nodes[node_id].z for node_id in row.node_ids))
        for row in tnt
    )
    assert volume == pytest.approx(scene.charge.volume_m3, rel=1.0e-12, abs=1.0e-15)
    assert volume * TNT_DENSITY_KG_PER_M3 == pytest.approx(
        scene.charge.mass_kg, rel=1.0e-12, abs=1.0e-12
    )
    assert scene.air.realized_tnt_mass_kg == pytest.approx(scene.charge.mass_kg)


def test_moving_charge_changes_scene_but_not_building_identity() -> None:
    left = build_solver_blast_scene(_model(COMMERCIAL), _config(position=(-1.0, 1.5, 1.5)))
    right = build_solver_blast_scene(_model(COMMERCIAL), _config(position=(-1.0, 2.5, 1.5)))

    assert left.building.fingerprint == right.building.fingerprint
    assert left.charge.fingerprint != right.charge.fingerprint
    assert left.fingerprint != right.fingerprint


@pytest.mark.parametrize("resource_id", [COMMERCIAL, RESIDENTIAL, SUBWAY])
def test_ground_is_visible_excavated_and_does_not_overlap_structure(resource_id: str) -> None:
    model = _model(resource_id)
    position = (-1.0, 2.0, max(model.grade_elevation_m + 1.0, 1.5))
    scene = build_solver_blast_scene(model, _config(position=position))

    assert scene.ground.part_role == "diagnostic_soil_ground"
    assert scene.ground.fragments
    assert scene.ground.positive_soil_structure_overlap_m3 == 0.0
    if resource_id == SUBWAY:
        assert scene.ground.excavation_bounds_m
        assert scene.ground.grade_elevation_m > scene.building.bounds_m[2]
        excavation = scene.ground.excavation_bounds_m[0]
        assert excavation[2] == pytest.approx(scene.building.bounds_m[2])
        assert any(
            abs(node.z - scene.building.bounds_m[2]) <= 1.0e-10
            for fragment in scene.ground.fragments
            for node in fragment.nodes
        )


def test_ground_mesh_uses_independent_user_cell_size_without_hidden_coarsening() -> None:
    requested = 0.2
    scene = build_solver_blast_scene(
        _model(COMMERCIAL),
        _config(ground_cell_size_m=requested),
    )
    fragment = scene.ground.fragments[0]
    nodes = {node.node_id: node for node in fragment.nodes}
    edge_pairs = (
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    )
    maximum_edge = max(
        math.dist(
            (nodes[element.node_ids[left]].x, nodes[element.node_ids[left]].y, nodes[element.node_ids[left]].z),
            (nodes[element.node_ids[right]].x, nodes[element.node_ids[right]].y, nodes[element.node_ids[right]].z),
        )
        for element in fragment.solids
        for left, right in edge_pairs
    )

    assert scene.ground.target_cell_size_m == pytest.approx(requested)
    assert maximum_edge <= requested + 1.0e-12


def test_ground_mesh_change_invalidates_ground_and_scene_but_not_building() -> None:
    building = _model(COMMERCIAL)
    coarse = build_solver_blast_scene(building, _config(ground_cell_size_m=0.5))
    fine = build_solver_blast_scene(building, _config(ground_cell_size_m=0.25))

    assert coarse.building.fingerprint == fine.building.fingerprint
    assert coarse.charge.fingerprint == fine.charge.fingerprint
    assert coarse.ground.fingerprint != fine.ground.fingerprint
    assert coarse.fingerprint != fine.fingerprint
@pytest.mark.parametrize("resource_id", [COMMERCIAL, RESIDENTIAL, SUBWAY])
def test_ground_mesh_has_no_massless_orphan_nodes(resource_id: str) -> None:
    model = _model(resource_id)
    scene = build_solver_blast_scene(
        model,
        _config(position=(-1.0, 2.0, max(model.grade_elevation_m + 1.0, 1.5))),
    )

    for fragment in scene.ground.fragments:
        used_node_ids = {
            node_id for element in fragment.solids for node_id in element.node_ids
        }
        assert {node.node_id for node in fragment.nodes} == used_node_ids


def test_charge_inside_structure_fails_before_air_axis_generation(monkeypatch) -> None:
    from lsprepost_mcp.refined_building.solver_blast import ale_domain

    def forbidden(*args, **kwargs):
        raise AssertionError("ALE axis generation must not run for an invalid charge")

    monkeypatch.setattr(ale_domain, "estimate_ale_domain", forbidden)
    with pytest.raises(ValueError, match="valid air"):
        build_solver_blast_scene(
            _model(COMMERCIAL),
            _config(position=(3.0, 2.0, 0.1)),
        )


def test_charge_inside_soil_is_rejected() -> None:
    with pytest.raises(ValueError, match="soil"):
        build_solver_blast_scene(
            _model(COMMERCIAL),
            _config(position=(-1.0, 2.0, -0.5)),
        )


def test_charge_centered_on_physical_shell_is_rejected() -> None:
    model = _model(COMMERCIAL)
    artifact = model.artifacts[0]
    nodes = {node.node_id: node for node in artifact.mesh.nodes}
    shell = next(
        row for row in artifact.mesh.shells if row.part_role == "nonstructural_partition"
    )
    position = tuple(
        sum(getattr(nodes[node_id], axis) for node_id in shell.node_ids)
        / len(shell.node_ids)
        for axis in ("x", "y", "z")
    )

    with pytest.raises(ValueError, match="valid air"):
        build_solver_blast_scene(model, _config(position=position))


def test_ale_iterators_match_preflight_counts_without_materializing_grid() -> None:
    scene = build_solver_blast_scene(_model(COMMERCIAL), _config())
    nodes = iter_ale_nodes(scene.air)
    elements = iter_ale_elements(scene.air)

    first_node = next(nodes)
    first_element = next(elements)
    assert first_node.node_id == scene.air.node_id_start
    assert first_element.element_id == scene.air.element_id_start
    assert len(set(first_element.node_ids)) == 8
    nx = len(scene.air.x_coordinates) - 1
    ny = len(scene.air.y_coordinates) - 1
    assert first_element.node_ids == (
        scene.air.node_id_start,
        scene.air.node_id_start + 1,
        scene.air.node_id_start + nx + 2,
        scene.air.node_id_start + nx + 1,
        scene.air.node_id_start + (ny + 1) * (nx + 1),
        scene.air.node_id_start + (ny + 1) * (nx + 1) + 1,
        scene.air.node_id_start + (ny + 1) * (nx + 1) + nx + 2,
        scene.air.node_id_start + (ny + 1) * (nx + 1) + nx + 1,
    )
    first_cell_volume = (
        (scene.air.x_coordinates[1] - scene.air.x_coordinates[0])
        * (scene.air.y_coordinates[1] - scene.air.y_coordinates[0])
        * (scene.air.z_coordinates[1] - scene.air.z_coordinates[0])
    )
    assert first_cell_volume > 0.0
    assert scene.air.node_count == len(scene.air.x_coordinates) * len(
        scene.air.y_coordinates
    ) * len(scene.air.z_coordinates)
    assert scene.air.element_count == (
        (len(scene.air.x_coordinates) - 1)
        * (len(scene.air.y_coordinates) - 1)
        * (len(scene.air.z_coordinates) - 1)
    )


def test_building_ground_and_ale_use_disjoint_stable_id_ranges() -> None:
    scene = build_solver_blast_scene(_model(COMMERCIAL), _config())
    building_fragments = tuple(
        artifact.mesh for artifact in scene.building.artifacts
    ) + scene.building.supplement_fragments
    building_node_ids = {
        node.node_id for fragment in building_fragments for node in fragment.nodes
    }
    building_element_ids = {
        element.element_id
        for fragment in building_fragments
        for element in (*fragment.solids, *fragment.shells, *fragment.beams)
    }
    ground_node_ids = {
        node.node_id for fragment in scene.ground.fragments for node in fragment.nodes
    }
    ground_element_ids = {
        element.element_id
        for fragment in scene.ground.fragments
        for element in fragment.solids
    }

    assert building_node_ids.isdisjoint(ground_node_ids)
    assert building_element_ids.isdisjoint(ground_element_ids)
    assert max(ground_node_ids) < scene.air.node_id_start
    assert max(ground_element_ids) < scene.air.element_id_start


def test_charge_outside_fixed_air_domain_is_rejected_before_allocation() -> None:
    with pytest.raises(ValueError, match="fixed ALE domain"):
        build_solver_blast_scene(
            _model(COMMERCIAL),
            _config(position=(-1_000_000.0, 2.0, 1.5)),
        )


def test_huge_ground_is_rejected_before_mesh_allocation(monkeypatch) -> None:
    from lsprepost_mcp.refined_building.solver_blast import ground

    def forbidden(*args, **kwargs):
        raise AssertionError("ground mesh allocation must not run past preflight")

    monkeypatch.setattr(ground, "mesh_axis_aligned_block_excluding", forbidden)
    with pytest.raises(ValueError, match="ground .* budget"):
        ground.build_ground(
            _model(COMMERCIAL),
            _config(air_margin_m=(100_000.0, 100_000.0, 100_000.0)),
        )


def test_air_margin_must_leave_one_local_charge_cell_before_far_boundary() -> None:
    with pytest.raises(ValueError, match="air_margins_m"):
        build_solver_blast_scene(
            _model(COMMERCIAL),
            _config(air_margin_m=(0.01, 3.0, 3.0)),
        )
