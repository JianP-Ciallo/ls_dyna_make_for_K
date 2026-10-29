from __future__ import annotations

import unittest
from unittest.mock import patch

from lsprepost_mcp.refined_building.backends.rc import _build_member_boxes, compile_rc_structure
from lsprepost_mcp.refined_building.contracts import default_building_definition
from lsprepost_mcp.refined_building.spatial import compile_spatial_topology
from lsprepost_mcp.refined_building.systems import get_structural_system
from lsprepost_mcp.refined_building.validation import validate_building_artifact


def compile_fixture(system_id: str, generation_mode: str):
    value = default_building_definition(structural_system=system_id)
    value["structural_system"]["parameters"] = {
        "generation_mode": generation_mode,
        "mesh_size_m": 0.5,
        "rebar_spacing_m": 0.4,
    }
    return compile_rc_structure(
        value,
        compile_spatial_topology(value),
        get_structural_system(system_id),
    )


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


def two_level_fixture():
    value = default_building_definition(structural_system="rc_frame")
    value["envelope"]["size_m"][2] = 6.0
    value["levels"].append({"id": "level_2", "elevation_m": 3.0, "height_m": 3.0})
    value["spaces"].append(
        {
            "id": "room_2",
            "level_id": "level_2",
            "kind": "room",
            "bounds_m": [0.25, 0.25, 3.25, 5.75, 5.75, 5.75],
        }
    )
    value["structural_system"]["parameters"] = {
        "generation_mode": "concrete_only",
        "mesh_size_m": 0.5,
    }
    return compile_rc_structure(
        value,
        compile_spatial_topology(value),
        get_structural_system("rc_frame"),
    )


class Phase18CRCBackendTests(unittest.TestCase):
    def test_default_three_by_three_grid_generates_every_frame_member(self) -> None:
        value = default_building_definition(structural_system="rc_frame")
        topology = compile_spatial_topology(value)

        members = _build_member_boxes(
            value,
            topology,
            "rc_frame",
            column_width=0.3,
            column_depth=0.3,
            beam_width=0.3,
            beam_depth=0.4,
            slab_thickness=0.2,
            foundation_thickness=0.2,
        )

        self.assertEqual(9, sum(role == "rc_column" for role, _ in members))
        self.assertEqual(6, sum(role == "rc_beam_x" for role, _ in members))
        self.assertEqual(6, sum(role == "rc_beam_y" for role, _ in members))
        self.assertTrue(
            any(
                role == "rc_column" and box.contains_point((3.0, 3.0, 1.5))
                for role, box in members
            )
        )

    def test_room_space_does_not_cut_the_center_column(self) -> None:
        artifact = compile_fixture("rc_frame", "concrete_only")
        nodes = {node.node_id: node for node in artifact.mesh.nodes}

        center_is_in_column = any(
            solid.part_role == "rc_column"
            and all(
                min(nodes[node_id].coordinates[axis] for node_id in solid.node_ids)
                <= (3.0, 3.0, 1.5)[axis]
                <= max(nodes[node_id].coordinates[axis] for node_id in solid.node_ids)
                for axis in range(3)
            )
            for solid in artifact.mesh.solids
        )

        self.assertTrue(center_is_in_column)

    def test_two_level_rc_concrete_is_one_connected_component(self) -> None:
        artifact = two_level_fixture()
        report = validate_building_artifact(artifact)

        self.assertEqual(1, solid_connected_component_count(artifact))
        self.assertNotIn(
            "disconnected_concrete",
            {row["code"] for row in report["findings"]},
        )

    def test_nonzero_lowest_level_stays_connected_to_its_foundation(self) -> None:
        value = default_building_definition(structural_system="rc_frame")
        value["envelope"]["size_m"][2] = 4.0
        value["levels"][0] = {"id": "level_1", "elevation_m": 1.0, "height_m": 3.0}
        value["spaces"][0]["bounds_m"] = [0.25, 0.25, 1.25, 5.75, 5.75, 3.75]
        value["structural_system"]["parameters"] = {
            "generation_mode": "concrete_only",
            "mesh_size_m": 0.5,
        }

        artifact = compile_rc_structure(
            value,
            compile_spatial_topology(value),
            get_structural_system("rc_frame"),
        )

        self.assertEqual(1, solid_connected_component_count(artifact))

    def test_concrete_mesh_is_conforming_and_connected(self) -> None:
        artifact = compile_fixture("rc_frame", "concrete_only")
        nodes = {node.node_id: node for node in artifact.mesh.nodes}
        solid_node_ids = {node_id for solid in artifact.mesh.solids for node_id in solid.node_ids}
        coordinates = [nodes[node_id].coordinates for node_id in solid_node_ids]

        self.assertEqual(len(coordinates), len(set(coordinates)))
        self.assertEqual(1, solid_connected_component_count(artifact))
        finding_codes = {row["code"] for row in validate_building_artifact(artifact)["findings"]}
        self.assertNotIn("duplicate_structural_coordinate", finding_codes)
        self.assertNotIn("disconnected_concrete", finding_codes)

    def test_full_reinforced_frame_has_solid_beam_and_embedded_roles(self) -> None:
        artifact = compile_fixture("rc_frame", "full_reinforced")

        self.assertGreater(len(artifact.mesh.solids), 0)
        self.assertGreater(len(artifact.mesh.beams), 0)
        self.assertTrue(artifact.connections_by_type("embedded_rebar"))
        self.assertIn("column_longitudinal", {beam.part_role for beam in artifact.mesh.beams})
        self.assertIn("beam_stirrup", {beam.part_role for beam in artifact.mesh.beams})

    def test_concrete_only_has_no_rebar_or_embedding(self) -> None:
        artifact = compile_fixture("rc_frame", "concrete_only")

        self.assertEqual((), artifact.mesh.beams)
        self.assertFalse(artifact.connections_by_type("embedded_rebar"))

    def test_room_air_point_away_from_grid_is_not_inside_any_structural_solid(self) -> None:
        artifact = compile_fixture("rc_frame", "full_reinforced")

        self.assertFalse(artifact.solid_contains_point((1.5, 1.5, 1.5)))

    def test_larger_building_regenerates_concrete_and_rebar(self) -> None:
        small = compile_fixture("rc_frame", "full_reinforced")
        value = default_building_definition(structural_system="rc_frame")
        value["envelope"]["size_m"][0] = 9.0
        value["grid_axes"]["x_m"] = [0.0, 3.0, 6.0, 9.0]
        value["spaces"][0]["bounds_m"][3] = 8.75
        value["structural_system"]["parameters"] = {
            "generation_mode": "full_reinforced",
            "mesh_size_m": 0.5,
            "rebar_spacing_m": 0.4,
        }

        large = compile_rc_structure(
            value,
            compile_spatial_topology(value),
            get_structural_system("rc_frame"),
        )

        self.assertGreater(len(large.mesh.solids), len(small.mesh.solids))
        self.assertGreater(len(large.mesh.beams), len(small.mesh.beams))
        self.assertEqual(9.0, large.mesh.bounds_m[3])

    def test_custom_mode_can_generate_only_selected_reinforcement_role(self) -> None:
        value = default_building_definition(structural_system="rc_frame")
        value["structural_system"]["parameters"] = {
            "generation_mode": "custom",
            "include_reinforcement_roles": ["column_longitudinal"],
            "mesh_size_m": 0.5,
        }
        artifact = compile_rc_structure(
            value,
            compile_spatial_topology(value),
            get_structural_system("rc_frame"),
        )

        self.assertEqual(
            {"column_longitudinal"},
            {beam.part_role for beam in artifact.mesh.beams},
        )
        self.assertTrue(artifact.connections_by_type("embedded_rebar"))

    def test_impossible_cover_is_rejected(self) -> None:
        value = default_building_definition(structural_system="rc_frame")
        value["structural_system"]["parameters"] = {
            "generation_mode": "full_reinforced",
            "column_width_m": 0.3,
            "column_depth_m": 0.3,
            "cover_m": 0.16,
        }

        with self.assertRaisesRegex(ValueError, "cover"):
            compile_rc_structure(
                value,
                compile_spatial_topology(value),
                get_structural_system("rc_frame"),
            )

    def test_beam_depth_cannot_exceed_its_level_height(self) -> None:
        value = default_building_definition(structural_system="rc_frame")
        value["structural_system"]["parameters"] = {
            "generation_mode": "concrete_only",
            "beam_depth_m": 4.0,
        }

        with self.assertRaisesRegex(ValueError, "beam_depth_m"):
            compile_rc_structure(
                value,
                compile_spatial_topology(value),
                get_structural_system("rc_frame"),
            )

    def test_beam_depth_that_pushes_actual_beam_below_level_is_rejected(self) -> None:
        value = default_building_definition(structural_system="rc_frame")
        value["structural_system"]["parameters"] = {
            "generation_mode": "concrete_only",
            "beam_depth_m": 3.0,
        }

        with self.assertRaisesRegex(ValueError, "beam_depth_m"):
            compile_rc_structure(
                value,
                compile_spatial_topology(value),
                get_structural_system("rc_frame"),
            )

    def test_declared_shear_wall_must_be_inside_envelope(self) -> None:
        value = default_building_definition(structural_system="rc_frame_shear_wall")
        value["structural_system"]["parameters"] = {
            "generation_mode": "concrete_only",
            "wall_bounds_m": [[-0.1, 0.0, 0.0, 0.1, 6.0, 3.0]],
        }

        with self.assertRaisesRegex(ValueError, "wall_bounds_m"):
            compile_rc_structure(
                value,
                compile_spatial_topology(value),
                get_structural_system("rc_frame_shear_wall"),
            )

    def test_declared_shear_wall_guard_runs_before_union_mesh(self) -> None:
        value = default_building_definition(structural_system="rc_frame_shear_wall")
        value["structural_system"]["parameters"] = {
            "generation_mode": "concrete_only",
            "wall_bounds_m": [[-0.1, 0.0, 0.0, 0.1, 6.0, 3.0]],
        }

        with patch(
            "lsprepost_mcp.refined_building.backends.rc.mesh_axis_aligned_union",
            side_effect=AssertionError("union mesh called before wall guard"),
        ):
            with self.assertRaisesRegex(ValueError, "wall_bounds_m"):
                compile_rc_structure(
                    value,
                    compile_spatial_topology(value),
                    get_structural_system("rc_frame_shear_wall"),
                )


if __name__ == "__main__":
    unittest.main()
