from __future__ import annotations

import copy
import importlib
import math
from collections import Counter
from dataclasses import replace
from functools import lru_cache
from types import ModuleType
from typing import get_args

import pytest

from lsprepost_mcp.refined_building.artifacts import (
    MeshFragment,
    Node,
    SolidElement,
)
from lsprepost_mcp.refined_building.meshing import mesh_axis_aligned_block
from lsprepost_mcp.refined_building.meshing import merge_fragments_welded
from lsprepost_mcp.refined_building.solver_blast import build_solver_blast_scene
from lsprepost_mcp.refined_building.solver_blast.fsi import extract_fsi_segments
from lsprepost_mcp.refined_building.spatial import (
    AxisAlignedBox,
    compile_spatial_topology,
)
from test_phase18_solver_blast_buildings import COMMERCIAL, RESIDENTIAL, SUBWAY
from test_phase18_solver_blast_scene import _config, _model


SURFACE_CLASSES = frozenset(
    {
        "external_air_exposed",
        "internal_air_exposed",
        "soil_contact",
        "sealed_internal",
        "structural_connection",
    }
)
AIR_EXPOSED_CLASSES = frozenset(
    {"external_air_exposed", "internal_air_exposed"}
)
REAL_SCENES = (COMMERCIAL, RESIDENTIAL, SUBWAY)
_SURFACE_MODULE = (
    "lsprepost_mcp.refined_building.solver_blast.surface_topology"
)


def _surface_api() -> ModuleType:
    try:
        return importlib.import_module(_SURFACE_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name != _SURFACE_MODULE:
            raise
        pytest.fail(
            "Task4 surface_topology API is missing; implement SurfaceClass, "
            "SurfaceTopology, and classify_surface_topology",
            pytrace=False,
        )


@lru_cache(maxsize=3)
def _scene(resource_id: str):
    model = _model(resource_id)
    charge_z = max(model.grade_elevation_m + 1.0, 1.5)
    return build_solver_blast_scene(
        model,
        _config(position=(-1.0, 2.0, charge_z)),
    )


@lru_cache(maxsize=3)
def _topology(resource_id: str):
    return _surface_api().classify_surface_topology(_scene(resource_id))


def _surface_key(row) -> tuple[int, tuple[int, int, int, int]]:
    return row.owner_element_id, tuple(sorted(row.face_key))


def _fsi_key(row) -> tuple[int, tuple[int, int, int, int]]:
    return row.owner_element_id, tuple(sorted(row.node_ids))


def _coupled_fsi_rows(fsi):
    return (*fsi.segments, *fsi.ground_segments)


def test_surface_class_is_the_closed_five_class_contract() -> None:
    surface_class = _surface_api().SurfaceClass

    assert set(get_args(surface_class)) == SURFACE_CLASSES


@pytest.mark.parametrize("resource_id", REAL_SCENES)
def test_every_real_scene_surface_is_uniquely_and_completely_classified(
    resource_id: str,
) -> None:
    topology = _topology(resource_id)
    surfaces = topology.surfaces
    observed = Counter(row.surface_class for row in surfaces)
    instance_keys = tuple(_surface_key(row) for row in surfaces)

    assert surfaces
    assert topology.unclassified_count == 0
    assert topology.multiply_classified_count == 0
    assert set(topology.counts) == SURFACE_CLASSES
    assert dict(topology.counts) == {
        surface_class: observed[surface_class]
        for surface_class in SURFACE_CLASSES
    }
    assert sum(topology.counts.values()) == topology.boundary_face_count
    assert topology.boundary_face_count == len(surfaces)
    assert len(instance_keys) == len(set(instance_keys))

    for row in surfaces:
        assert row.surface_class in SURFACE_CLASSES
        assert len(row.face_key) == 4
        assert len(set(row.face_key)) == 4
        assert tuple(sorted(row.face_key)) == row.face_key
        assert math.isfinite(row.area_m2)
        assert row.area_m2 > 0.0
        assert len(row.normal) == 3
        assert all(math.isfinite(value) for value in row.normal)
        assert math.sqrt(sum(value * value for value in row.normal)) == pytest.approx(
            1.0,
            abs=1.0e-10,
        )


def test_subway_box_roles_are_classified_by_face_location_not_role_name() -> None:
    topology = _topology(SUBWAY)

    wall_classes = {
        row.surface_class
        for row in topology.surfaces
        if row.owner_part_role == "rc_box_wall"
    }
    floor_classes = {
        row.surface_class
        for row in topology.surfaces
        if row.owner_part_role == "rc_box_floor"
    }

    assert {"soil_contact", "internal_air_exposed"} <= wall_classes
    assert {"soil_contact", "sealed_internal"} <= floor_classes


@pytest.mark.parametrize("resource_id", REAL_SCENES)
def test_fsi_is_exactly_the_active_air_exposed_topology_projection(
    resource_id: str,
) -> None:
    topology = _topology(resource_id)
    scene = _scene(resource_id)
    fsi = extract_fsi_segments(scene, topology)
    expected = {
        _surface_key(row)
        for row in topology.surfaces
        if row.surface_class in AIR_EXPOSED_CLASSES
        and row.adjacent_active_air_component is not None
    }
    actual_rows = tuple(_fsi_key(row) for row in fsi.segments)

    assert expected
    assert len(actual_rows) == len(set(actual_rows))
    assert set(actual_rows) == expected


def test_subway_surfaces_completely_below_ale_zmin_never_enter_fsi() -> None:
    topology = _topology(SUBWAY)
    scene = _scene(SUBWAY)
    fsi = extract_fsi_segments(scene, topology)
    node_z = {
        node.node_id: node.z
        for node in fsi.building_mesh.nodes
    }
    node_z.update(
        {
            node.node_id: node.z
            for fragment in scene.ground.fragments
            for node in fragment.nodes
        }
    )
    zmin = scene.air.bounds.min_z
    below = {
        _surface_key(row)
        for row in topology.surfaces
        if all(node_id in node_z for node_id in row.face_key)
        and max(node_z[node_id] for node_id in row.face_key) < zmin - 1.0e-10
    }
    coupled = {_fsi_key(row) for row in _coupled_fsi_rows(fsi)}

    assert below, "the real subway fixture must exercise the below-ALE-domain case"
    assert below.isdisjoint(coupled)


def test_extract_fsi_rejects_topology_from_another_scene() -> None:
    commercial_topology = _topology(COMMERCIAL)

    with pytest.raises(
        ValueError,
        match=r"(?i)(surface topology|topology).*(scene|fingerprint|belong)",
    ):
        extract_fsi_segments(_scene(RESIDENTIAL), commercial_topology)


def test_surface_topology_rejects_a_face_with_more_than_two_owners() -> None:
    surface_api = _surface_api()
    scene = _scene(COMMERCIAL)
    fragments = list(scene.building.supplement_fragments)
    fragment_index = next(
        index for index, fragment in enumerate(fragments) if fragment.solids
    )
    fragment = fragments[fragment_index]
    source = fragment.solids[0]
    maximum_element_id = max(
        row.element_id
        for row in (*fragment.solids, *fragment.shells, *fragment.beams)
    )
    forged_fragment = replace(
        fragment,
        solids=(
            *fragment.solids,
            SolidElement(
                maximum_element_id + 1,
                source.node_ids,
                source.part_role,
            ),
            SolidElement(
                maximum_element_id + 2,
                source.node_ids,
                source.part_role,
            ),
        ),
    )
    fragments[fragment_index] = forged_fragment
    forged_building = replace(
        scene.building,
        supplement_fragments=tuple(fragments),
        fingerprint="forged-non-manifold-building",
    )
    forged_scene = replace(
        scene,
        building=forged_building,
        fingerprint="forged-non-manifold-scene",
    )

    with pytest.raises(
        ValueError,
        match=r"(?i)(non.?manifold|more than two|owner)",
    ):
        surface_api.classify_surface_topology(forged_scene)


def test_synchronized_exterior_opening_without_mesh_aperture_is_rejected() -> None:
    surface_api = _surface_api()
    scene = _scene(COMMERCIAL)
    artifact = scene.building.artifacts[0]
    normalized_input = copy.deepcopy(artifact.normalized_input)
    normalized_input["openings"] = [
        *normalized_input["openings"],
        {
            "id": "forged_rear_opening",
            "kind": "door",
            "bounds_m": [1.0, 3.8, 0.2, 2.0, 4.0, 1.2],
            "connects": ["sales_hall", "exterior"],
        },
    ]
    forged_artifact = replace(
        artifact,
        normalized_input=normalized_input,
        topology_manifest=compile_spatial_topology(normalized_input).to_manifest(),
    )
    forged_building = replace(
        scene.building,
        artifacts=(forged_artifact, *scene.building.artifacts[1:]),
        declared_opening_count=scene.building.declared_opening_count + 1,
        fingerprint="forged-opening-without-mesh-aperture",
    )

    with pytest.raises(
        ValueError,
        match=r"(?i)(opening.*(aperture|mesh)|mesh.*opening)",
    ):
        forged_scene = build_solver_blast_scene(forged_building, scene.config)
        surface_api.classify_surface_topology(forged_scene)


def test_internal_fsi_requires_an_exterior_reachable_active_air_component() -> None:
    surface_api = _surface_api()
    scene = _scene(COMMERCIAL)
    sealing_wall = mesh_axis_aligned_block(
        AxisAlignedBox(0.0, 0.6, 0.0, 4.0, 0.8, 4.0),
        10.0,
        "mutation_sealing_wall",
    )
    forged_building = replace(
        scene.building,
        supplement_fragments=(
            *scene.building.supplement_fragments,
            sealing_wall,
        ),
        fingerprint="forged-sealed-sales-hall",
    )
    forged_scene = replace(
        scene,
        building=forged_building,
        fingerprint="forged-sealed-sales-hall-scene",
    )

    topology = surface_api.classify_surface_topology(forged_scene)
    nodes = {row.node_id: row for row in topology.building_mesh.nodes}
    wall_faces = tuple(
        row
        for row in topology.surfaces
        if row.owner_part_role == "mutation_sealing_wall"
    )
    entrance_side = next(
        row
        for row in wall_faces
        if row.normal[1] < -0.9
        and sum(nodes[node_id].y for node_id in row.node_ids) / 4.0
        == pytest.approx(0.6)
    )
    sealed_side = next(
        row
        for row in wall_faces
        if row.normal[1] > 0.9
        and sum(nodes[node_id].y for node_id in row.node_ids) / 4.0
        == pytest.approx(0.8)
    )

    assert entrance_side.surface_class == "internal_air_exposed"
    assert entrance_side.adjacent_active_air_component == (
        "internal:commercial_supermarket_detailed_building:sales_hall"
    )
    assert sealed_side.surface_class == "sealed_internal"
    assert sealed_side.adjacent_active_air_component is None


def test_opening_is_blocked_by_one_full_projected_section_inside_its_depth() -> None:
    opening = AxisAlignedBox(0.0, 0.0, 0.0, 0.2, 1.0, 1.0)
    transverse_slab = (0.08, 0.0, 0.0, 0.12, 1.0, 1.0)

    assert not _surface_api()._opening_has_positive_aperture(
        opening,
        (transverse_slab,),
        (),
    )


def test_multileaf_wall_with_a_real_aligned_hole_keeps_positive_aperture() -> None:
    opening = AxisAlignedBox(0.0, 0.0, 0.0, 0.2, 1.0, 1.0)
    wall_leaves = (
        (0.02, 0.0, 0.0, 0.08, 0.8, 1.0),
        (0.12, 0.0, 0.0, 0.18, 0.8, 1.0),
    )

    assert _surface_api()._opening_has_positive_aperture(
        opening,
        wall_leaves,
        (),
    )


def _unit_cube_nodes() -> tuple[Node, ...]:
    return (
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 1.0, 0.0, 0.0),
        Node(3, 1.0, 1.0, 0.0),
        Node(4, 0.0, 1.0, 0.0),
        Node(5, 0.0, 0.0, 1.0),
        Node(6, 1.0, 0.0, 1.0),
        Node(7, 1.0, 1.0, 1.0),
        Node(8, 0.0, 1.0, 1.0),
    )


def test_two_coincident_hex8_volumes_are_rejected_instead_of_disappearing() -> None:
    nodes = _unit_cube_nodes()
    node_ids = tuple(row.node_id for row in nodes)
    mesh = MeshFragment(
        nodes=nodes,
        solids=(
            SolidElement(1, node_ids, "first_cube"),
            SolidElement(2, node_ids, "second_cube"),
        ),
    )

    with pytest.raises(ValueError, match=r"(?i)(overlap|coincident|duplicate)"):
        _surface_api()._boundary_candidates(
            mesh,
            {row.node_id: row for row in nodes},
        )


def test_more_than_two_balanced_face_owners_are_never_silently_accepted() -> None:
    left = mesh_axis_aligned_block(
        AxisAlignedBox(0.0, 0.0, 0.0, 1.0, 1.0, 1.0),
        2.0,
        "left_a",
    )
    right = mesh_axis_aligned_block(
        AxisAlignedBox(1.0, 0.0, 0.0, 2.0, 1.0, 1.0),
        2.0,
        "right_a",
    )
    welded = merge_fragments_welded((left, right))
    first, second = welded.solids
    mesh = replace(
        welded,
        solids=(
            first,
            second,
            SolidElement(3, first.node_ids, "left_b"),
            SolidElement(4, second.node_ids, "right_b"),
        ),
    )

    with pytest.raises(ValueError, match=r"(?i)(more than two|owner)"):
        _surface_api()._boundary_candidates(
            mesh,
            {row.node_id: row for row in mesh.nodes},
        )


def test_two_adjacent_hex8_volumes_keep_only_their_shared_face_internal() -> None:
    left = mesh_axis_aligned_block(
        AxisAlignedBox(0.0, 0.0, 0.0, 1.0, 1.0, 1.0),
        2.0,
        "left",
    )
    right = mesh_axis_aligned_block(
        AxisAlignedBox(1.0, 0.0, 0.0, 2.0, 1.0, 1.0),
        2.0,
        "right",
    )
    mesh = merge_fragments_welded((left, right))

    candidates = _surface_api()._boundary_candidates(
        mesh,
        {row.node_id: row for row in mesh.nodes},
    )

    assert len(candidates) == 10
