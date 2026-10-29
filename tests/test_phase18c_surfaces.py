from __future__ import annotations

import unittest

from lsprepost_mcp.refined_building.artifacts import (
    BuildingArtifact,
    MeshFragment,
    Node,
    ShellElement,
    SolidElement,
)
from lsprepost_mcp.refined_building.backends.rc import compile_rc_structure
from lsprepost_mcp.refined_building.backends.rc_box import compile_rc_box
from lsprepost_mcp.refined_building.backends.steel import compile_steel_frame
from lsprepost_mcp.refined_building.backends.hybrid import compile_steel_concrete_hybrid
from lsprepost_mcp.refined_building.contracts import default_building_definition
from lsprepost_mcp.refined_building.nonstructural import compile_nonstructural
from lsprepost_mcp.refined_building.spatial import compile_spatial_topology
from lsprepost_mcp.refined_building.surfaces import build_fluid_exposed_surface_catalog
from lsprepost_mcp.refined_building.systems import get_structural_system


def two_room_box_fixture() -> dict[str, object]:
    value = default_building_definition(structural_system="rc_box")
    value["spaces"] = [
        {
            "id": "room_a",
            "level_id": "level_1",
            "kind": "room",
            "bounds_m": [0.2, 0.2, 0.2, 2.9, 5.8, 2.8],
        },
        {
            "id": "room_b",
            "level_id": "level_1",
            "kind": "room",
            "bounds_m": [3.1, 0.2, 0.2, 5.8, 5.8, 2.8],
        },
    ]
    value["openings"] = [
        {
            "id": "door_ab",
            "kind": "door",
            "bounds_m": [2.9, 2.5, 0.2, 3.1, 3.5, 2.2],
            "connects": ["room_a", "room_b"],
        }
    ]
    value["structural_system"]["parameters"] = {
        "generation_mode": "concrete_only",
        "box_thickness_m": 0.2,
        "mesh_size_m": 0.5,
    }
    return value


def shell_and_solid_faces_fixture(
    shell_xy: tuple[tuple[float, float], ...],
    solid_faces_xy: tuple[tuple[tuple[float, float], ...], ...],
    *,
    bottom_z: float = 2.0,
) -> tuple[BuildingArtifact, object]:
    value = default_building_definition(structural_system="steel_concrete_hybrid")
    topology = compile_spatial_topology(value)
    nodes: list[Node] = []
    solids: list[SolidElement] = []
    for element_id, face_xy in enumerate(solid_faces_xy, start=1):
        first_node_id = len(nodes) + 1
        nodes.extend(Node(len(nodes) + 1, x, y, bottom_z) for x, y in face_xy)
        nodes.extend(Node(len(nodes) + 1, x, y, 3.0) for x, y in face_xy)
        solids.append(
            SolidElement(
                element_id,
                tuple(range(first_node_id, first_node_id + 8)),
                "concrete",
            )
        )
    shell_node_ids = tuple(range(len(nodes) + 1, len(nodes) + 5))
    nodes.extend(Node(len(nodes) + 1, x, y, 3.0) for x, y in shell_xy)
    artifact = BuildingArtifact(
        asset_id="shell-coverage-fixture",
        system_id="steel_concrete_hybrid",
        mesh=MeshFragment(
            nodes=tuple(nodes),
            solids=tuple(solids),
            shells=(ShellElement(len(solids) + 1, shell_node_ids, "steel_roof"),),
        ),
    )
    return artifact, topology


class Phase18CSurfaceTests(unittest.TestCase):
    def test_partially_covered_shell_is_still_user_selectable(self) -> None:
        value = default_building_definition(structural_system="steel_concrete_hybrid")
        topology = compile_spatial_topology(value)
        artifact = BuildingArtifact(
            asset_id="partial-shell-coverage",
            system_id="steel_concrete_hybrid",
            mesh=MeshFragment(
                nodes=(
                    Node(1, 2.0, 2.0, 2.0),
                    Node(2, 4.0, 2.0, 2.0),
                    Node(3, 4.0, 4.0, 2.0),
                    Node(4, 2.0, 4.0, 2.0),
                    Node(5, 2.0, 2.0, 3.0),
                    Node(6, 4.0, 2.0, 3.0),
                    Node(7, 4.0, 4.0, 3.0),
                    Node(8, 2.0, 4.0, 3.0),
                    Node(9, 0.0, 0.0, 3.0),
                    Node(10, 6.0, 0.0, 3.0),
                    Node(11, 6.0, 6.0, 3.0),
                    Node(12, 0.0, 6.0, 3.0),
                ),
                solids=(SolidElement(1, (1, 2, 3, 4, 5, 6, 7, 8), "concrete"),),
                shells=(ShellElement(2, (9, 10, 11, 12), "steel_roof"),),
            ),
        )

        catalog = build_fluid_exposed_surface_catalog(artifact, topology)
        published_shells = [
            row
            for row in catalog["user_selectable_surfaces"]
            if row["face_id"].startswith("shell:")
        ]

        self.assertEqual(["shell:2"], [row["face_id"] for row in published_shells])

    def test_non_axis_aligned_shell_requires_an_exact_face_match(self) -> None:
        value = default_building_definition(structural_system="steel_concrete_hybrid")
        topology = compile_spatial_topology(value)
        artifact = BuildingArtifact(
            asset_id="rotated-shell-coverage",
            system_id="steel_concrete_hybrid",
            mesh=MeshFragment(
                nodes=(
                    Node(1, 0.0, 0.0, 2.0),
                    Node(2, 4.0, 0.0, 2.0),
                    Node(3, 4.0, 4.0, 2.0),
                    Node(4, 0.0, 4.0, 2.0),
                    Node(5, 0.0, 0.0, 3.0),
                    Node(6, 4.0, 0.0, 3.0),
                    Node(7, 4.0, 4.0, 3.0),
                    Node(8, 0.0, 4.0, 3.0),
                    Node(9, 2.0, 0.5, 3.0),
                    Node(10, 3.5, 2.0, 3.0),
                    Node(11, 2.0, 3.5, 3.0),
                    Node(12, 0.5, 2.0, 3.0),
                ),
                solids=(SolidElement(1, (1, 2, 3, 4, 5, 6, 7, 8), "concrete"),),
                shells=(ShellElement(2, (9, 10, 11, 12), "rotated_roof"),),
            ),
        )

        catalog = build_fluid_exposed_surface_catalog(artifact, topology)

        self.assertIn(
            "shell:2",
            {row["face_id"] for row in catalog["user_selectable_surfaces"]},
        )

    def test_adjacent_and_overlapping_solid_faces_cover_shell_as_a_union(self) -> None:
        artifact, topology = shell_and_solid_faces_fixture(
            ((0.0, 0.0), (3.0, 0.0), (3.0, 2.0), (0.0, 2.0)),
            (
                ((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)),
                ((1.0, 0.0), (3.0, 0.0), (3.0, 2.0), (1.0, 2.0)),
            ),
        )

        catalog = build_fluid_exposed_surface_catalog(artifact, topology)

        self.assertNotIn(
            "shell:3",
            {row["face_id"] for row in catalog["user_selectable_surfaces"]},
        )

    def test_rotated_solid_face_cannot_suppress_axis_aligned_shell(self) -> None:
        artifact, topology = shell_and_solid_faces_fixture(
            ((0.5, 0.5), (3.5, 0.5), (3.5, 3.5), (0.5, 3.5)),
            (((2.0, 0.0), (4.0, 2.0), (2.0, 4.0), (0.0, 2.0)),),
        )

        catalog = build_fluid_exposed_surface_catalog(artifact, topology)

        self.assertIn(
            "shell:2",
            {row["face_id"] for row in catalog["user_selectable_surfaces"]},
        )

    def test_narrow_positive_area_strip_completes_shell_coverage(self) -> None:
        split = 0.9999999999
        artifact, topology = shell_and_solid_faces_fixture(
            ((0.0, 0.0), (1.0, 0.0), (1.0, 100.0), (0.0, 100.0)),
            (
                ((0.0, 0.0), (split, 0.0), (split, 100.0), (0.0, 100.0)),
                ((split, 0.0), (1.0, 0.0), (1.0, 100.0), (split, 100.0)),
            ),
            bottom_z=-97.0,
        )

        catalog = build_fluid_exposed_surface_catalog(artifact, topology)

        self.assertNotIn(
            "shell:3",
            {row["face_id"] for row in catalog["user_selectable_surfaces"]},
        )

    def test_steel_roof_shells_are_exterior_and_user_selectable(self) -> None:
        value = default_building_definition(structural_system="steel_frame")
        topology = compile_spatial_topology(value)
        artifact = compile_steel_frame(value, topology, get_structural_system("steel_frame"))

        catalog = build_fluid_exposed_surface_catalog(artifact, topology)
        exterior_shells = [
            row for row in catalog["exterior_surfaces"] if row["face_id"].startswith("shell:")
        ]
        selectable_shells = [
            row
            for row in catalog["user_selectable_surfaces"]
            if row["face_id"].startswith("shell:")
        ]

        self.assertEqual(4, len(exterior_shells))
        self.assertEqual(4, len(selectable_shells))
        self.assertEqual(
            {shell.element_id for shell in artifact.mesh.shells},
            {row["element_id"] for row in exterior_shells},
        )

    def test_shell_coincident_with_solid_face_is_not_published_twice(self) -> None:
        value = default_building_definition(structural_system="steel_concrete_hybrid")
        topology = compile_spatial_topology(value)
        artifact = compile_steel_concrete_hybrid(
            value,
            topology,
            get_structural_system("steel_concrete_hybrid"),
        )

        catalog = build_fluid_exposed_surface_catalog(artifact, topology)
        published_shells = [
            row
            for row in catalog["user_selectable_surfaces"]
            if row["face_id"].startswith("shell:")
        ]

        self.assertEqual([], published_shells)

    def test_surface_catalog_separates_exterior_room_and_opening_surfaces(self) -> None:
        value = two_room_box_fixture()
        topology = compile_spatial_topology(value)
        artifact = compile_rc_box(value, topology, get_structural_system("rc_box"))
        catalog = build_fluid_exposed_surface_catalog(artifact, topology)

        self.assertTrue(catalog["exterior_surfaces"])
        self.assertTrue(catalog["interior_cavity_surfaces"])
        self.assertTrue(catalog["opening_boundaries"])
        exterior = {row["face_id"] for row in catalog["exterior_surfaces"]}
        interior = {row["face_id"] for row in catalog["interior_cavity_surfaces"]}
        ground = {row["face_id"] for row in catalog["ground_contact_surfaces"]}
        openings = {row["face_id"] for row in catalog["opening_boundaries"]}
        self.assertFalse(exterior & interior)
        self.assertFalse(exterior & ground)
        self.assertFalse(interior & openings)

    def test_partition_is_nonstructural_and_does_not_add_structural_connection(self) -> None:
        value = default_building_definition(structural_system="rc_frame")
        value["structural_system"]["parameters"] = {"generation_mode": "concrete_only"}
        value["nonstructural"] = [
            {
                "id": "partition_1",
                "kind": "partition",
                "bounds_m": [2.95, 0.25, 0.25, 3.05, 5.75, 2.75],
                "material_role": "gypsum_partition",
            }
        ]
        topology = compile_spatial_topology(value)
        structural = compile_rc_structure(
            value, topology, get_structural_system("rc_frame")
        )
        nonstructural = compile_nonstructural(value, structural)

        self.assertTrue(nonstructural.shells)
        self.assertEqual(
            {"nonstructural_partition"},
            {shell.part_role for shell in nonstructural.shells},
        )
        self.assertFalse(structural.connections_by_type("structural_common_node"))


if __name__ == "__main__":
    unittest.main()
