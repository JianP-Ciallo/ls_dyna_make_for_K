from __future__ import annotations

import unittest
from unittest.mock import patch

from lsprepost_mcp.refined_building.backends.hybrid import compile_steel_concrete_hybrid
from lsprepost_mcp.refined_building.backends.rc_box import compile_rc_box
from lsprepost_mcp.refined_building.backends.steel import compile_steel_frame
from lsprepost_mcp.refined_building.contracts import default_building_definition
from lsprepost_mcp.refined_building.spatial import compile_spatial_topology
from lsprepost_mcp.refined_building.systems import get_structural_system


def compile_system_fixture(system_id: str):
    value = default_building_definition(structural_system=system_id)
    topology = compile_spatial_topology(value)
    descriptor = get_structural_system(system_id)
    if system_id == "steel_frame":
        return compile_steel_frame(value, topology, descriptor)
    if system_id == "steel_concrete_hybrid":
        return compile_steel_concrete_hybrid(value, topology, descriptor)
    if system_id == "rc_box":
        return compile_rc_box(value, topology, descriptor)
    raise AssertionError(system_id)


def solid_connected_component_count(artifact) -> int:
    remaining = {solid.element_id: set(solid.node_ids) for solid in artifact.mesh.solids}
    component_count = 0
    while remaining:
        component_count += 1
        _, frontier_nodes = remaining.popitem()
        changed = True
        while changed:
            changed = False
            for element_id, node_ids in list(remaining.items()):
                if frontier_nodes & node_ids:
                    frontier_nodes.update(node_ids)
                    del remaining[element_id]
                    changed = True
    return component_count


def segment_crosses_box_interior(start, end, bounds) -> bool:
    enter, leave = 0.0, 1.0
    for axis in range(3):
        low, high = bounds[axis] + 1e-12, bounds[axis + 3] - 1e-12
        delta = end[axis] - start[axis]
        if abs(delta) <= 1e-12:
            if not low < start[axis] < high:
                return False
            continue
        first, second = sorted(((low - start[axis]) / delta, (high - start[axis]) / delta))
        enter, leave = max(enter, first), min(leave, second)
        if enter >= leave:
            return False
    return enter < leave


class Phase18CStructuralBackendTests(unittest.TestCase):
    def test_steel_frame_has_connections_but_no_rebar_embedding(self) -> None:
        artifact = compile_system_fixture("steel_frame")

        self.assertTrue(artifact.mesh.beams)
        self.assertTrue(artifact.mesh.shells)
        self.assertTrue(artifact.connections_by_type("steel_connection"))
        self.assertFalse(artifact.connections_by_type("embedded_rebar"))
        self.assertNotIn("reinforcing_steel", {row.material_role for row in artifact.mesh.part_bindings})

    def test_hybrid_declares_concrete_steel_interface(self) -> None:
        artifact = compile_system_fixture("steel_concrete_hybrid")

        self.assertTrue(artifact.mesh.solids)
        self.assertTrue(artifact.mesh.beams)
        self.assertTrue(artifact.connections_by_type("composite_interface"))
        self.assertTrue(artifact.connections_by_type("steel_connection"))

    def test_hybrid_foundation_thickness_cannot_exceed_envelope_height(self) -> None:
        value = default_building_definition(structural_system="steel_concrete_hybrid")
        value["structural_system"]["parameters"] = {"foundation_thickness_m": 4.0}

        with self.assertRaisesRegex(ValueError, "foundation_thickness_m"):
            compile_steel_concrete_hybrid(
                value,
                compile_spatial_topology(value),
                get_structural_system("steel_concrete_hybrid"),
            )

    def test_hybrid_foundation_guard_runs_before_mesh_entries(self) -> None:
        value = default_building_definition(structural_system="steel_concrete_hybrid")
        value["structural_system"]["parameters"] = {"foundation_thickness_m": 4.0}

        for entry_point in ("compile_steel_frame", "mesh_axis_aligned_union"):
            with self.subTest(entry_point=entry_point), patch(
                f"lsprepost_mcp.refined_building.backends.hybrid.{entry_point}",
                side_effect=AssertionError(f"{entry_point} called before foundation guard"),
            ):
                with self.assertRaisesRegex(ValueError, "foundation_thickness_m"):
                    compile_steel_concrete_hybrid(
                        value,
                        compile_spatial_topology(value),
                        get_structural_system("steel_concrete_hybrid"),
                    )

    def test_hybrid_slab_thickness_cannot_exceed_its_level_height(self) -> None:
        value = default_building_definition(structural_system="steel_concrete_hybrid")
        value["structural_system"]["parameters"] = {"slab_thickness_m": 4.0}

        with self.assertRaisesRegex(ValueError, "slab_thickness_m"):
            compile_steel_concrete_hybrid(
                value,
                compile_spatial_topology(value),
                get_structural_system("steel_concrete_hybrid"),
            )

    def test_hybrid_slab_guard_runs_before_mesh_entries(self) -> None:
        value = default_building_definition(structural_system="steel_concrete_hybrid")
        value["structural_system"]["parameters"] = {"slab_thickness_m": 4.0}

        for entry_point in ("compile_steel_frame", "mesh_axis_aligned_union"):
            with self.subTest(entry_point=entry_point), patch(
                f"lsprepost_mcp.refined_building.backends.hybrid.{entry_point}",
                side_effect=AssertionError(f"{entry_point} called before slab guard"),
            ):
                with self.assertRaisesRegex(ValueError, "slab_thickness_m"):
                    compile_steel_concrete_hybrid(
                        value,
                        compile_spatial_topology(value),
                        get_structural_system("steel_concrete_hybrid"),
                    )

    def test_room_space_does_not_cut_hybrid_concrete(self) -> None:
        value = default_building_definition(structural_system="steel_concrete_hybrid")
        value["spaces"][0]["bounds_m"] = [0.25, 0.25, 0.0, 5.75, 5.75, 3.0]

        artifact = compile_steel_concrete_hybrid(
            value,
            compile_spatial_topology(value),
            get_structural_system("steel_concrete_hybrid"),
        )

        self.assertTrue(artifact.solid_contains_point((3.0, 3.0, 0.1)))
        self.assertTrue(artifact.solid_contains_point((3.0, 3.0, 2.9)))

    def test_rc_box_preserves_internal_void_and_has_rebar(self) -> None:
        artifact = compile_system_fixture("rc_box")

        self.assertTrue(artifact.mesh.solids)
        self.assertTrue(artifact.mesh.beams)
        self.assertFalse(artifact.solid_contains_point((3.0, 3.0, 1.5)))
        self.assertTrue(artifact.connections_by_type("embedded_rebar"))

    def test_rc_box_room_overlapping_wall_does_not_cut_concrete_or_rebar(self) -> None:
        value = default_building_definition(structural_system="rc_box")
        value["spaces"][0]["bounds_m"] = [0.05, 0.25, 0.25, 5.75, 5.75, 2.75]
        value["structural_system"]["parameters"] = {
            "generation_mode": "full_reinforced",
            "box_thickness_m": 0.2,
            "mesh_size_m": 0.5,
            "rebar_spacing_m": 0.3,
        }

        topology = compile_spatial_topology(value)
        artifact = compile_rc_box(value, topology, get_structural_system("rc_box"))
        nodes = {node.node_id: node.coordinates for node in artifact.mesh.nodes}
        left_wall_rebar = [
            beam
            for beam in artifact.mesh.beams
            if beam.part_role == "wall_rebar"
            and all(abs(nodes[node_id][0] - 0.1) <= 1e-12 for node_id in beam.node_ids)
            and segment_crosses_box_interior(
                nodes[beam.node_ids[0]],
                nodes[beam.node_ids[1]],
                value["spaces"][0]["bounds_m"],
            )
        ]

        self.assertTrue(artifact.solid_contains_point((0.1, 3.0, 1.5)))
        self.assertTrue(left_wall_rebar)

    def test_rc_box_concrete_mesh_is_conforming_and_connected(self) -> None:
        artifact = compile_system_fixture("rc_box")
        nodes = {node.node_id: node for node in artifact.mesh.nodes}
        solid_node_ids = {node_id for solid in artifact.mesh.solids for node_id in solid.node_ids}
        coordinates = [nodes[node_id].coordinates for node_id in solid_node_ids]

        self.assertEqual(len(coordinates), len(set(coordinates)))
        self.assertEqual(1, solid_connected_component_count(artifact))

    def test_rc_box_concrete_only_switch_removes_internal_rebar(self) -> None:
        value = default_building_definition(structural_system="rc_box")
        value["structural_system"]["parameters"] = {"generation_mode": "concrete_only"}
        artifact = compile_rc_box(
            value,
            compile_spatial_topology(value),
            get_structural_system("rc_box"),
        )

        self.assertEqual((), artifact.mesh.beams)
        self.assertFalse(artifact.connections_by_type("embedded_rebar"))

    def test_rc_box_exterior_door_is_cut_out_of_wall_solids(self) -> None:
        value = default_building_definition(structural_system="rc_box")
        value["spaces"][0]["bounds_m"] = [0.2, 0.2, 0.2, 5.8, 5.8, 2.8]
        value["openings"] = [
            {
                "id": "entry_door",
                "kind": "door",
                "bounds_m": [0.0, 2.5, 0.2, 0.2, 3.5, 2.2],
                "connects": ["room_1", "exterior"],
            }
        ]
        value["structural_system"]["parameters"] = {
            "generation_mode": "concrete_only",
            "box_thickness_m": 0.2,
            "mesh_size_m": 0.5,
        }

        artifact = compile_rc_box(
            value,
            compile_spatial_topology(value),
            get_structural_system("rc_box"),
        )

        self.assertFalse(artifact.solid_contains_point((0.1, 3.0, 1.0)))

    def test_rc_box_off_centre_door_removes_every_crossing_rebar_segment(self) -> None:
        value = default_building_definition(structural_system="rc_box")
        value["spaces"][0]["bounds_m"] = [0.2, 0.2, 0.2, 5.8, 5.8, 2.8]
        opening_bounds = [0.0, 0.7, 0.2, 0.2, 1.2, 2.2]
        value["openings"] = [
            {
                "id": "off_centre_entry",
                "kind": "door",
                "bounds_m": opening_bounds,
                "connects": ["room_1", "exterior"],
            }
        ]
        value["structural_system"]["parameters"] = {
            "generation_mode": "full_reinforced",
            "box_thickness_m": 0.2,
            "mesh_size_m": 0.5,
            "rebar_spacing_m": 0.3,
        }

        artifact = compile_rc_box(
            value,
            compile_spatial_topology(value),
            get_structural_system("rc_box"),
        )
        nodes = {node.node_id: node.coordinates for node in artifact.mesh.nodes}
        crossing = [
            beam.element_id
            for beam in artifact.mesh.beams
            if segment_crosses_box_interior(
                nodes[beam.node_ids[0]], nodes[beam.node_ids[1]], opening_bounds
            )
        ]

        self.assertEqual([], crossing)


if __name__ == "__main__":
    unittest.main()
