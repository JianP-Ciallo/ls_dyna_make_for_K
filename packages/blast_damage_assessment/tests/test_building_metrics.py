import unittest

import numpy as np

from blast_damage_assessment.building.connectivity import build_element_adjacency, largest_connected_region
from blast_damage_assessment.building.metrics import (
    BuildingAccumulator,
    relative_deformation,
    stress_invariants,
)


class BuildingMetricTests(unittest.TestCase):
    def test_accumulator_reports_peak_final_quantiles_fraction_and_stable_extreme(self):
        accumulator = BuildingAccumulator(np.array([30, 10, 20]))
        accumulator.update(0, 0.0, np.array([1.0, 3.0, 3.0]))
        accumulator.update(1, 1.0, np.array([4.0, 2.0, 3.0]))
        summary = accumulator.summary(affected_threshold=2.5)
        self.assertEqual(summary.peak_max, 4.0)
        self.assertEqual(summary.final_max, 4.0)
        self.assertEqual(summary.residual_max, 4.0)
        self.assertAlmostEqual(summary.p95, np.quantile([3.0, 3.0, 4.0], 0.95, method="linear"))
        self.assertAlmostEqual(summary.p99, np.quantile([3.0, 3.0, 4.0], 0.99, method="linear"))
        self.assertEqual(summary.affected_fraction, 1.0)
        self.assertEqual(summary.extreme_entity_id, 30)
        self.assertEqual(summary.extreme_time_index, 1)

    def test_tied_extreme_uses_lowest_time_then_lowest_entity_id(self):
        accumulator = BuildingAccumulator(np.array([20, 10]))
        accumulator.update(2, 2.0, np.array([5.0, 0.0]))
        accumulator.update(1, 1.0, np.array([5.0, 5.0]))
        summary = accumulator.summary()
        self.assertEqual((summary.extreme_time_index, summary.extreme_entity_id), (1, 10))

    def test_uniform_rigid_translation_is_not_component_deformation(self):
        coordinates = np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [1.0, 1.0, 0.0]])
        displacement = np.tile([3.0, -2.0, 1.0], (3, 1))
        result = relative_deformation(coordinates, displacement, support_node_indexes=[0, 1])
        np.testing.assert_allclose(result.ratios, 0.0)
        self.assertFalse(result.reference_motion_inferred)

    def test_missing_supports_uses_component_median_and_marks_inferred(self):
        coordinates = np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [1.0, 1.0, 0.0]])
        displacement = np.array([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.1, 0.0, 0.0]])
        result = relative_deformation(coordinates, displacement)
        self.assertTrue(result.reference_motion_inferred)
        self.assertGreater(result.ratios[2], 0.0)

    def test_von_mises_and_principal_stress_use_tensor_convention(self):
        result = stress_invariants(np.array([[100.0, 0.0, 0.0, 0.0, 0.0, 0.0]]))
        self.assertAlmostEqual(result.von_mises[0], 100.0)
        self.assertAlmostEqual(result.maximum_principal[0], 100.0)


class ConnectivityTests(unittest.TestCase):
    def test_solid_shell_and_beam_adjacency_require_face_edge_and_end_node(self):
        solid = np.array([[0, 1, 2, 3, 4, 5, 6, 7], [4, 5, 6, 7, 8, 9, 10, 11], [0, 1, 12, 13, 14, 15, 16, 17]])
        shell = np.array([[0, 1, 2, 3], [2, 3, 4, 5], [3, 6, 7, 8]])
        beam = np.array([[0, 1], [1, 2], [3, 4]])
        self.assertEqual(build_element_adjacency(solid, "solid"), ((1,), (0,), ()))
        self.assertEqual(build_element_adjacency(shell, "shell"), ((1,), (0,), ()))
        self.assertEqual(build_element_adjacency(beam, "beam"), ((1,), (0,), ()))

    def test_largest_connected_region_is_deterministic(self):
        adjacency = ((1,), (0, 2), (1,), (4,), (3,))
        region = largest_connected_region(np.array([True, True, True, True, True]), adjacency, np.array([30, 20, 10, 50, 40]))
        self.assertEqual(region.entity_ids, (10, 20, 30))
        self.assertEqual(region.size, 3)


if __name__ == "__main__":
    unittest.main()
