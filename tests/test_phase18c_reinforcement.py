from __future__ import annotations

import unittest

from lsprepost_mcp.refined_building.reinforcement import generate_reinforcement
from lsprepost_mcp.refined_building.spatial import AxisAlignedBox


class Phase18CReinforcementTests(unittest.TestCase):
    def test_off_centre_door_filter_keeps_only_referenced_nodes_stably(self) -> None:
        members = (("rc_box_wall", AxisAlignedBox(0.0, 0.0, 0.0, 0.2, 6.0, 3.0)),)
        parameters = {
            "cover_m": 0.04,
            "bar_diameter_m": 0.016,
            "rebar_spacing_m": 0.3,
        }
        opening = AxisAlignedBox(0.0, 0.7, 0.2, 0.2, 1.2, 2.2)

        first = generate_reinforcement(
            members,
            parameters,
            frozenset({"wall_rebar"}),
            excluded_boxes=(opening,),
        )
        second = generate_reinforcement(
            members,
            parameters,
            frozenset({"wall_rebar"}),
            excluded_boxes=(opening,),
        )
        unfiltered = generate_reinforcement(
            members,
            parameters,
            frozenset({"wall_rebar"}),
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNotNone(unfiltered)
        assert first is not None
        assert second is not None
        assert unfiltered is not None
        used_node_ids = {
            node_id for beam in first.beams for node_id in beam.node_ids
        }
        all_node_ids = {node.node_id for node in first.nodes}
        self.assertEqual(all_node_ids, used_node_ids)
        self.assertEqual(
            tuple(range(1, len(first.nodes) + 1)),
            tuple(node.node_id for node in first.nodes),
        )
        self.assertEqual(
            tuple(node.coordinates for node in first.nodes),
            tuple(node.coordinates for node in second.nodes),
        )
        self.assertEqual(
            tuple(beam.node_ids for beam in first.beams),
            tuple(beam.node_ids for beam in second.beams),
        )
        retained_element_ids = {beam.element_id for beam in first.beams}
        self.assertEqual(
            tuple(
                (beam.element_id, beam.part_role)
                for beam in unfiltered.beams
                if beam.element_id in retained_element_ids
            ),
            tuple((beam.element_id, beam.part_role) for beam in first.beams),
        )
        retained_roles = {beam.part_role for beam in first.beams}
        self.assertEqual(
            tuple(
                binding
                for binding in unfiltered.part_bindings
                if binding.part_role in retained_roles
            ),
            first.part_bindings,
        )


if __name__ == "__main__":
    unittest.main()
