from __future__ import annotations

import copy
from collections import Counter
from dataclasses import replace

import pytest

from lsprepost_mcp.refined_building.solver_blast import (
    audit_air_topology,
    build_solver_blast_scene,
    classify_ale_cell,
    normalize_solver_blast_config,
)
from lsprepost_mcp.refined_building.solver_blast import air_topology, ale_domain
from test_phase18_solver_blast_buildings import COMMERCIAL, SUBWAY
from test_phase18_solver_blast_scene import _model


def _config(
    *,
    position: tuple[float, float, float],
    air_cell_size_m: float = 0.3,
    coupling_buffer_layers: int = 2,
    air_margins_m: tuple[float, float, float, float, float] = (
        3.0,
        3.0,
        3.0,
        3.0,
        3.0,
    ),
):
    return normalize_solver_blast_config(
        {
            "schema_version": "phase18.solver_blast.config@4",
            "unit_system": "SI_m_s_kg_N_Pa",
            "tnt_equivalent_mass_kg": 2.0,
            "charge_position_m": list(position),
            "detonation_time_s": 0.0,
            "air_cell_size_m": air_cell_size_m,
            "near_field_cell_size_m": min(0.15, air_cell_size_m),
            "ground_cell_size_m": 0.5,
            "air_margins_m": list(air_margins_m),
            "coupling_buffer_layers": coupling_buffer_layers,
            "material_profile": "verification_reference",
            "termination_time_s": 0.001,
        }
    )


def _commercial_scene(
    *,
    air_cell_size_m: float = 0.3,
    coupling_buffer_layers: int = 2,
    air_margins_m: tuple[float, float, float, float, float] = (
        3.0,
        3.0,
        3.0,
        3.0,
        3.0,
    ),
):
    building = _model(COMMERCIAL)
    return build_solver_blast_scene(
        building,
        _config(
            position=(-1.0, 2.0, 1.5),
            air_cell_size_m=air_cell_size_m,
            coupling_buffer_layers=coupling_buffer_layers,
            air_margins_m=air_margins_m,
        ),
    )


def _subway_scene(*, coupling_buffer_layers: int = 2):
    building = _model(SUBWAY)
    return build_solver_blast_scene(
        building,
        _config(
            position=(-1.0, 2.0, building.grade_elevation_m + 1.0),
            air_cell_size_m=0.3,
            coupling_buffer_layers=coupling_buffer_layers,
        ),
    )


def _cell_center(domain, ix: int, iy: int, iz: int) -> tuple[float, float, float]:
    return (
        0.5 * (domain.x_coordinates[ix] + domain.x_coordinates[ix + 1]),
        0.5 * (domain.y_coordinates[iy] + domain.y_coordinates[iy + 1]),
        0.5 * (domain.z_coordinates[iz] + domain.z_coordinates[iz + 1]),
    )


@pytest.mark.parametrize("coupling_buffer_layers", (1, 2, 3, 4, 5))
def test_coupling_buffer_uses_exact_requested_layer_count(
    coupling_buffer_layers: int,
) -> None:
    cell_size = 0.2
    scene = _commercial_scene(
        coupling_buffer_layers=coupling_buffer_layers,
        air_cell_size_m=cell_size,
    )

    assert scene.air.part_role == "ale_active_air_domain"
    assert scene.air.buffer_part_role == "ale_coupling_buffer"
    assert scene.air.active_air_bounds.min_z == pytest.approx(
        scene.ground.grade_elevation_m
    )
    assert scene.air.coupling_buffer_bounds.max_z == pytest.approx(
        scene.ground.grade_elevation_m
    )
    assert scene.air.coupling_buffer_bounds.min_z == pytest.approx(
        scene.ground.grade_elevation_m - coupling_buffer_layers * cell_size
    )
    below_grade_intervals = tuple(
        (left, right)
        for left, right in zip(scene.air.z_coordinates, scene.air.z_coordinates[1:])
        if right <= scene.ground.grade_elevation_m + 1.0e-12
    )
    assert len(below_grade_intervals) == coupling_buffer_layers
    assert below_grade_intervals[0][0] == pytest.approx(
        scene.ground.grade_elevation_m - coupling_buffer_layers * cell_size
    )
    assert below_grade_intervals[-1][1] == pytest.approx(
        scene.ground.grade_elevation_m
    )
    assert all(
        right - left == pytest.approx(cell_size)
        for left, right in below_grade_intervals
    )
    nx = len(scene.air.x_coordinates) - 1
    ny = len(scene.air.y_coordinates) - 1
    assert scene.air.buffer_element_count == coupling_buffer_layers * nx * ny
    assert scene.air.active_air_element_count > 0
    assert classify_ale_cell(scene.air, 0, 0, 0) == "coupling_buffer"
    assert (
        classify_ale_cell(
            scene.air,
            0,
            0,
            len(scene.air.z_coordinates) - 2,
        )
        == "active_air"
    )


def test_subway_connected_internal_air_remains_active_below_grade() -> None:
    scene = _subway_scene(coupling_buffer_layers=2)
    evidence = audit_air_topology(scene)

    assert evidence.connected_internal_air_cell_count > 0
    assert evidence.external_path_to_soil_contact_count == 0
    assert scene.air.air_region.connected_internal_bounds_m
    assert scene.air.air_region.connected_opening_bounds_m

    found_internal = False
    found_opening_connector = False
    for iz in range(len(scene.air.z_coordinates) - 1):
        for iy in range(len(scene.air.y_coordinates) - 1):
            for ix in range(len(scene.air.x_coordinates) - 1):
                center = _cell_center(scene.air, ix, iy, iz)
                if center[2] >= scene.ground.grade_elevation_m:
                    continue
                if classify_ale_cell(scene.air, ix, iy, iz) != "active_air":
                    continue
                in_space = any(
                    bounds[0] <= center[0] <= bounds[3]
                    and bounds[1] <= center[1] <= bounds[4]
                    and bounds[2] <= center[2] <= bounds[5]
                    for bounds in scene.air.air_region.connected_internal_bounds_m
                )
                in_opening = any(
                    bounds[0] <= center[0] <= bounds[3]
                    and bounds[1] <= center[1] <= bounds[4]
                    and bounds[2] <= center[2] <= bounds[5]
                    for bounds in scene.air.air_region.connected_opening_bounds_m
                )
                found_internal = True
                found_opening_connector = found_opening_connector or (
                    in_opening and not in_space
                )
                assert in_space or in_opening
    assert found_internal
    assert found_opening_connector


def test_underground_tnt_requires_a_dedicated_internal_ale_block() -> None:
    building = _model(SUBWAY)
    opening_rows = building.artifacts[0].normalized_input["openings"]
    assert isinstance(opening_rows, list)
    external_rows = tuple(
        row
        for row in opening_rows
        if isinstance(row, dict) and "exterior" in row["connects"]
    )
    front = min(external_rows, key=lambda row: float(row["bounds_m"][0]))
    bounds = tuple(float(value) for value in front["bounds_m"])
    position = (
        0.5 * (bounds[0] + bounds[3]),
        0.5 * (bounds[1] + bounds[4]),
        building.grade_elevation_m - 0.15,
    )

    with pytest.raises(ValueError, match="dedicated internal ALE block"):
        build_solver_blast_scene(
            building,
            _config(position=position, air_cell_size_m=0.3),
        )


def test_changed_normalized_input_must_match_the_published_topology_manifest() -> None:
    building = _model(SUBWAY)
    source_artifact = building.artifacts[0]
    changed_input = copy.deepcopy(source_artifact.normalized_input)
    envelope = changed_input["envelope"]
    assert isinstance(envelope, dict)
    size = envelope["size_m"]
    assert isinstance(size, list)
    size[0] = float(size[0]) + 0.01
    changed_artifact = replace(source_artifact, normalized_input=changed_input)
    changed_building = replace(building, artifacts=(changed_artifact,))

    with pytest.raises(ValueError, match="topology_manifest"):
        build_solver_blast_scene(
            changed_building,
            _config(
                position=(-1.0, 2.0, building.grade_elevation_m + 1.0),
                air_cell_size_m=0.3,
            ),
        )


def test_topology_audit_reuses_the_indexed_cell_plan(monkeypatch) -> None:
    scene = _subway_scene()

    def classification_scan_sentinel(*_args, **_kwargs):
        raise AssertionError("audit must not rescan every ALE cell")

    monkeypatch.setattr(
        air_topology, "classify_ale_cell", classification_scan_sentinel
    )

    assert audit_air_topology(scene) == scene.air_topology


def test_internal_air_plan_uses_a_compact_cell_mask() -> None:
    scene = _subway_scene()
    plan = scene.air.cell_plan

    assert isinstance(plan.connected_internal_cell_mask, bytes)
    assert len(plan.connected_internal_cell_mask) == scene.air.element_count
    assert (
        plan.connected_internal_cell_mask.count(1)
        == plan.connected_internal_air_cell_count
    )


def test_tnt_plan_uses_constant_size_index_bounds() -> None:
    scene = _commercial_scene()
    plan = scene.air.cell_plan
    ix0, iy0, iz0, ix1, iy1, iz1 = plan.tnt_index_bounds

    assert not hasattr(plan, "tnt_cell_indices")
    assert 0 <= ix0 < ix1 <= plan.nx
    assert 0 <= iy0 < iy1 <= plan.ny
    assert 0 <= iz0 < iz1 <= plan.nz
    assert (
        (ix1 - ix0) * (iy1 - iy0) * (iz1 - iz0)
        == plan.tnt_cell_count
    )


def test_tnt_keeps_one_refinement_cell_from_all_six_outer_boundaries() -> None:
    scene = _commercial_scene(air_margins_m=(1.1, 0.05, 0.05, 0.05, 0.05))
    charge = scene.charge.bounds_m
    domain = scene.air.bounds
    clearances = (
        charge[0] - domain.min_x,
        domain.max_x - charge[3],
        charge[1] - domain.min_y,
        domain.max_y - charge[4],
        charge[2] - domain.min_z,
        domain.max_z - charge[5],
    )

    assert len(clearances) == 6
    assert all(
        clearance >= scene.air.charge_refinement_cell_size_m - 1.0e-12
        for clearance in clearances
    )


def test_every_layered_cell_has_exactly_one_role_and_counts_match() -> None:
    scene = _commercial_scene()
    kinds = Counter(
        classify_ale_cell(scene.air, ix, iy, iz)
        for iz in range(len(scene.air.z_coordinates) - 1)
        for iy in range(len(scene.air.y_coordinates) - 1)
        for ix in range(len(scene.air.x_coordinates) - 1)
    )

    assert set(kinds) == {"active_air", "explicit_tnt", "coupling_buffer"}
    assert kinds["active_air"] == scene.air.active_air_element_count
    assert kinds["explicit_tnt"] == scene.air.tnt_element_count
    assert kinds["coupling_buffer"] == scene.air.buffer_element_count
    assert sum(kinds.values()) == scene.air.element_count
    assert audit_air_topology(scene) == scene.air_topology


def test_asymmetric_air_margins_are_applied_in_declared_axis_order() -> None:
    margins = (2.0, 4.0, 3.0, 5.0, 6.0)
    scene = _commercial_scene(air_margins_m=margins)
    building = scene.building.bounds_m

    assert scene.air.bounds.min_x == pytest.approx(
        building[0] - margins[0]
    )
    assert scene.air.bounds.max_x == pytest.approx(
        building[3] + margins[1]
    )
    assert scene.air.bounds.min_y == pytest.approx(
        building[1] - margins[2]
    )
    assert scene.air.bounds.max_y == pytest.approx(
        building[4] + margins[3]
    )
    assert scene.air.bounds.max_z == pytest.approx(
        max(building[5], scene.ground.grade_elevation_m) + margins[4]
    )


def test_buffer_budget_is_checked_before_axis_materialization(monkeypatch) -> None:
    scene = _commercial_scene()
    wide_ground = replace(
        scene.ground,
        bounds_m=(
            -100.0,
            -100.0,
            scene.ground.bounds_m[2],
            100.0,
            100.0,
            scene.ground.grade_elevation_m,
        ),
    )
    huge = _config(
        position=scene.charge.position_m,
        air_cell_size_m=0.15,
        air_margins_m=(100.0, 100.0, 100.0, 100.0, 100.0),
    )

    def allocation_sentinel(*_args, **_kwargs):
        raise AssertionError("axis coordinates must not be materialized")

    monkeypatch.setattr(ale_domain, "_axis_coordinates", allocation_sentinel)
    with pytest.raises(ValueError, match="ALE element budget exceeded"):
        ale_domain.estimate_ale_domain(
            scene.building,
            wide_ground,
            scene.charge,
            huge,
        )


def test_cell_plan_memory_budget_is_checked_before_axis_materialization(
    monkeypatch,
) -> None:
    scene = _commercial_scene()
    config = _config(
        position=scene.charge.position_m,
        air_cell_size_m=0.3,
    )

    def allocation_sentinel(*_args, **_kwargs):
        raise AssertionError("axis coordinates must not be materialized")

    monkeypatch.setattr(ale_domain, "_MAX_ALE_CELL_PLAN_BYTES", 1)
    monkeypatch.setattr(ale_domain, "_axis_coordinates", allocation_sentinel)
    with pytest.raises(ValueError, match="cell-plan memory budget exceeded"):
        ale_domain.estimate_ale_domain(
            scene.building,
            scene.ground,
            scene.charge,
            config,
        )
