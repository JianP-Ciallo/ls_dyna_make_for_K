from __future__ import annotations

import unittest

from lsprepost_mcp.refined_building.artifacts import BeamElement, MeshFragment, Node, ShellElement
from lsprepost_mcp.refined_building.meshing import (
    merge_fragments,
    mesh_axis_aligned_block,
    mesh_axis_aligned_block_excluding,
    mesh_axis_aligned_union,
)
from lsprepost_mcp.refined_building.spatial import AxisAlignedBox


def line_fragment(role: str, offset: float) -> MeshFragment:
    return MeshFragment(
        nodes=(Node(1, offset, 0.0, 0.0), Node(2, offset + 1.0, 0.0, 0.0)),
        beams=(BeamElement(1, (1, 2), role),),
    )


class Phase18CMeshingTests(unittest.TestCase):
    def test_union_mesh_reuses_nodes_and_emits_overlap_once(self) -> None:
        fragment = mesh_axis_aligned_union(
            (
                ("column", AxisAlignedBox(0.0, 0.0, 0.0, 1.0, 1.0, 2.0)),
                ("beam", AxisAlignedBox(0.0, 0.0, 1.0, 2.0, 1.0, 2.0)),
            ),
            1.0,
        )
        nodes = {node.node_id: node for node in fragment.nodes}
        volumes = []
        geometries = set()
        for solid in fragment.solids:
            coordinates = tuple(nodes[node_id].coordinates for node_id in solid.node_ids)
            xs = [row[0] for row in coordinates]
            ys = [row[1] for row in coordinates]
            zs = [row[2] for row in coordinates]
            volumes.append((max(xs) - min(xs)) * (max(ys) - min(ys)) * (max(zs) - min(zs)))
            geometries.add(tuple(sorted(coordinates)))

        self.assertEqual(3, len(fragment.solids))
        self.assertAlmostEqual(3.0, sum(volumes))
        self.assertEqual(len(fragment.nodes), len({node.coordinates for node in fragment.nodes}))
        self.assertEqual(len(fragment.solids), len(geometries))

    def test_block_mesh_uses_eight_node_solids_and_exact_bounds(self) -> None:
        fragment = mesh_axis_aligned_block(
            AxisAlignedBox(0.0, 0.0, 0.0, 1.0, 0.4, 0.4),
            0.2,
            "rc_beam",
        )

        self.assertTrue(fragment.solids)
        self.assertTrue(all(len(element.node_ids) == 8 for element in fragment.solids))
        self.assertEqual((0.0, 0.0, 0.0, 1.0, 0.4, 0.4), fragment.bounds_m)
        self.assertEqual(20, len(fragment.solids))
        self.assertEqual(54, len(fragment.nodes))

    def test_merge_is_deterministic_and_has_unique_ids(self) -> None:
        merged_a = merge_fragments([line_fragment("a", 0.0), line_fragment("b", 2.0)])
        merged_b = merge_fragments([line_fragment("a", 0.0), line_fragment("b", 2.0)])

        self.assertEqual(merged_a, merged_b)
        self.assertEqual(len(merged_a.nodes), len({node.node_id for node in merged_a.nodes}))
        self.assertEqual(len(merged_a.beams), len({beam.element_id for beam in merged_a.beams}))
        self.assertEqual((1, 2), merged_a.beams[0].node_ids)
        self.assertEqual((3, 4), merged_a.beams[1].node_ids)

    def test_mesh_rejects_invalid_size_and_fragment_rejects_dangling_node(self) -> None:
        with self.assertRaisesRegex(ValueError, "target_size_m"):
            mesh_axis_aligned_block(AxisAlignedBox(0, 0, 0, 1, 1, 1), 0.0, "wall")

        with self.assertRaisesRegex(ValueError, "dangling"):
            MeshFragment(
                nodes=(Node(1, 0.0, 0.0, 0.0),),
                beams=(BeamElement(1, (1, 2), "rebar"),),
            )

    def test_fingerprint_changes_when_geometry_changes(self) -> None:
        first = mesh_axis_aligned_block(AxisAlignedBox(0, 0, 0, 1, 1, 1), 0.5, "block")
        second = mesh_axis_aligned_block(AxisAlignedBox(0, 0, 0, 2, 1, 1), 0.5, "block")

        self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_merge_preserves_cross_family_element_order_for_connection_ids(self) -> None:
        mixed = MeshFragment(
            nodes=(
                Node(1, 0.0, 0.0, 0.0),
                Node(2, 1.0, 0.0, 0.0),
                Node(3, 1.0, 1.0, 0.0),
                Node(4, 0.0, 1.0, 0.0),
            ),
            beams=(BeamElement(1, (1, 2), "frame"),),
            shells=(ShellElement(2, (1, 2, 3, 4), "deck"),),
        )

        merged = merge_fragments((mixed, line_fragment("next", 2.0)))

        self.assertEqual(1, merged.beams[0].element_id)
        self.assertEqual(2, merged.shells[0].element_id)
        self.assertEqual(3, merged.beams[1].element_id)

    def test_block_exclusion_creates_a_real_solid_void(self) -> None:
        opening = AxisAlignedBox(0.0, 0.4, 0.2, 0.2, 0.6, 0.8)
        fragment = mesh_axis_aligned_block_excluding(
            AxisAlignedBox(0.0, 0.0, 0.0, 0.2, 1.0, 1.0),
            0.25,
            "wall",
            (opening,),
        )
        nodes = {node.node_id: node for node in fragment.nodes}

        for solid in fragment.solids:
            centroid = tuple(
                sum(nodes[node_id].coordinates[axis] for node_id in solid.node_ids) / 8.0
                for axis in range(3)
            )
            self.assertFalse(opening.contains_point(centroid))
        self.assertEqual(28, len(fragment.solids))


if __name__ == "__main__":
    unittest.main()
