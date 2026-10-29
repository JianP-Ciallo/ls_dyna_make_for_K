import math
import unittest

import numpy as np

from blast_damage_assessment.contracts import GateState
from blast_damage_assessment.errors import ContractError
from blast_damage_assessment.ground.metrics import detect_seeded_regions, region_metrics
from blast_damage_assessment.ground.surface import SurfaceCell, SurfaceMesh, extract_initial_surface


def one_cube():
    coordinates = np.array(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]],
        dtype=float,
    )
    return coordinates, np.array([[0, 1, 2, 3, 4, 5, 6, 7]]), np.array([8001])


def grid_surface(size=4):
    cells = []
    for y in range(size):
        for x in range(size):
            index = y * size + x
            cells.append(SurfaceCell(index, (index * 4, index * 4 + 1, index * 4 + 2, index * 4 + 3), (x + 0.5, y + 0.5, 0.0), 1.0))
    adjacency = []
    for y in range(size):
        for x in range(size):
            neighbors = []
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < size and 0 <= ny < size:
                    neighbors.append(ny * size + nx)
            adjacency.append(tuple(sorted(neighbors)))
    return SurfaceMesh(tuple(cells), tuple(adjacency), 1.0, 4.0, (1.5, 1.5, 0.0), False, GateState.FORMAL)


class SurfaceExtractionTests(unittest.TestCase):
    def test_extracts_unique_upper_boundary_and_projects_charge(self):
        coordinates, connectivity, parts = one_cube()
        surface = extract_initial_surface(coordinates, connectivity, parts, (8001,), (0.5, 0.5, 2.0), vertical_axis="z")
        self.assertEqual(len(surface.cells), 1)
        self.assertAlmostEqual(surface.cells[0].centroid[2], 1.0)
        self.assertEqual(surface.blast_projection, (0.5, 0.5, 1.0))
        self.assertEqual(surface.gate, GateState.FORMAL)
    def test_surface_faces_must_have_normals_aligned_with_vertical_axis(self):
        coordinates, connectivity, parts = one_cube()
        coordinates[5:7, 2] = 1.2
        surface = extract_initial_surface(
            coordinates,
            connectivity,
            parts,
            (8001,),
            (0.5, 0.5, 2.0),
        )
        self.assertEqual(len(surface.cells), 1)
        self.assertGreater(surface.cells[0].centroid[2], 1.0)

    def test_projection_in_a_bounding_box_gap_is_outside_modeled_ground(self):
        first, first_connectivity, _ = one_cube()
        second = first + np.array([2.0, 0.0, 0.0])
        coordinates = np.vstack((first, second))
        connectivity = np.vstack((first_connectivity, first_connectivity + 8))
        with self.assertRaisesRegex(ContractError, "outside"):
            extract_initial_surface(
                coordinates,
                connectivity,
                np.array([8001, 8001]),
                (8001,),
                (1.5, 0.5, 2.0),
            )


    def test_legacy_axis_or_charge_inference_caps_at_provisional(self):
        coordinates, connectivity, parts = one_cube()
        surface = extract_initial_surface(coordinates, connectivity, parts, (8001,), (0.5, 0.5, 2.0), inferred=True)
        self.assertEqual(surface.gate, GateState.PROVISIONAL)

    def test_rejects_missing_part_nonmanifold_faces_and_outside_projection(self):
        coordinates, connectivity, parts = one_cube()
        with self.assertRaisesRegex(ContractError, "ground Part"):
            extract_initial_surface(coordinates, connectivity, parts, (9999,), (0.5, 0.5, 2.0))
        with self.assertRaisesRegex(ContractError, "nonmanifold"):
            extract_initial_surface(coordinates, np.repeat(connectivity, 3, axis=0), np.array([8001, 8001, 8001]), (8001,), (0.5, 0.5, 2.0))
        with self.assertRaisesRegex(ContractError, "outside"):
            extract_initial_surface(coordinates, connectivity, parts, (8001,), (2.0, 0.5, 2.0))


class GroundRegionTests(unittest.TestCase):
    def test_seeded_crater_excludes_distant_isolated_depression(self):
        surface = grid_surface()
        vertical = np.zeros(16)
        vertical[[5, 6, 9, 10]] = -0.5
        vertical[15] = -1.0
        result = detect_seeded_regions(surface, vertical)
        self.assertEqual(set(result.crater.cell_indexes), {5, 6, 9, 10})
        self.assertNotIn(15, result.crater.cell_indexes)
        self.assertTrue(result.anomalies)

    def test_uplift_and_outside_settlement_are_separate_layers(self):
        surface = grid_surface()
        vertical = np.zeros(16)
        vertical[[5, 6, 9, 10]] = -0.5
        vertical[[1, 2]] = 0.25
        vertical[[12, 13]] = -0.2
        result = detect_seeded_regions(surface, vertical)
        self.assertTrue(set(result.uplift.cell_indexes).isdisjoint(result.crater.cell_indexes))
        self.assertTrue(set(result.settlement.cell_indexes).isdisjoint(result.crater.cell_indexes))

    def test_region_geometry_and_radial_rings(self):
        surface = grid_surface()
        vertical = np.zeros(16)
        vertical[[5, 6, 9, 10]] = -0.5
        detection = detect_seeded_regions(surface, vertical)
        metrics = region_metrics(surface, detection.crater, vertical)
        self.assertEqual(metrics.maximum_depth, 0.5)
        self.assertEqual(metrics.plan_area, 4.0)
        self.assertAlmostEqual(metrics.equivalent_diameter, math.sqrt(16.0 / math.pi))
        self.assertEqual(metrics.signed_prism_volume, -2.0)
        self.assertTrue(metrics.radial_rings)


if __name__ == "__main__":
    unittest.main()
