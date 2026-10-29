import unittest

import numpy as np

from blast_damage_assessment.contracts import GateState, Severity
from blast_damage_assessment.ground.evaluator import GroundEvaluationInput, evaluate_ground
from blast_damage_assessment.ground.metrics import GroundStateRecord, evaluate_stability
from blast_damage_assessment.material_capabilities import capability_for_material
from blast_damage_assessment.rules import load_rule_pack
from packages.blast_damage_assessment.tests.test_ground_surface import grid_surface


class StabilityTests(unittest.TestCase):
    def records(self, speed=0.0, regions=None):
        regions = regions or (5, 6, 9, 10)
        return tuple(
            GroundStateRecord(index, float(index), 0.5, -2.0, 4.0, speed, tuple(regions))
            for index in range(6)
        )

    def test_stable_tail_allows_residual_wording(self):
        result = evaluate_stability(self.records(), median_cell_length=1.0)
        self.assertTrue(result.stable)
        self.assertEqual(result.shape_term, "residual_shape")

    def test_missing_velocity_too_few_states_speed_drift_or_jaccard_forbid_residual(self):
        cases = (
            self.records(speed=None),
            self.records()[:4],
            self.records(speed=1.0),
            self.records()[:-1] + (GroundStateRecord(5, 5.0, 0.8, -3.0, 6.0, 0.0, (0,)),),
        )
        for records in cases:
            with self.subTest(count=len(records)):
                result = evaluate_stability(records, median_cell_length=1.0)
                self.assertFalse(result.stable)
                self.assertEqual(result.shape_term, "instantaneous_final_shape")


class GroundEvaluatorTests(unittest.TestCase):
    def test_rates_peak_and_final_geometry_and_marks_elastic_damage_unavailable(self):
        surface = grid_surface()
        displacements = np.zeros((10, 16))
        displacements[:, [5, 6, 9, 10]] = -0.5
        displacements[2, [5, 6, 9, 10]] = -0.8
        speeds = np.zeros((10, 16))
        elastic = capability_for_material({"material_id": 7, "model": "elastic"})
        result = evaluate_ground(
            GroundEvaluationInput(surface, np.arange(10.0), displacements, speeds, elastic),
            load_rule_pack("ground_research_reference@1"),
        )
        self.assertEqual(result.gate, GateState.PROVISIONAL)
        self.assertEqual(result.severity, Severity.SEVERE)
        self.assertEqual(result.peak.crater.maximum_depth, 0.8)
        self.assertEqual(result.final.crater.maximum_depth, 0.5)
        self.assertTrue(result.stability.stable)
        self.assertFalse(result.subratings["material_damage"].available)
        crater = result.subratings["crater"]
        self.assertEqual(crater.metric_name, "ground_depth_to_median_surface_cell")
        self.assertEqual(crater.actual_value, 0.8)
        self.assertEqual(crater.limit_value, 0.5)

    def test_missing_velocity_keeps_instantaneous_wording(self):
        surface = grid_surface()
        displacements = np.zeros((6, 16))
        displacements[:, [5, 6, 9, 10]] = -0.2
        result = evaluate_ground(
            GroundEvaluationInput(
                surface,
                np.arange(6.0),
                displacements,
                None,
                capability_for_material({"material_id": 7, "model": "elastic"}),
            ),
            load_rule_pack("ground_research_reference@1"),
        )
        self.assertFalse(result.stability.stable)
        self.assertEqual(result.stability.shape_term, "instantaneous_final_shape")

    def test_numerical_erosion_is_separate_from_geometric_crater(self):
        surface = grid_surface()
        displacements = np.zeros((6, 16))
        alive = np.ones((6, 16), dtype=bool)
        alive[-1, [5, 6, 9, 10]] = False
        result = evaluate_ground(
            GroundEvaluationInput(
                surface,
                np.arange(6.0),
                displacements,
                np.zeros((6, 16)),
                capability_for_material({"material_id": 7, "model": "elastic"}),
                alive=alive,
            ),
            load_rule_pack("ground_research_reference@1"),
        )
        self.assertEqual(result.final.crater.plan_area, 0.0)
        self.assertTrue(result.subratings["numerical_erosion"].available)
        self.assertGreater(result.subratings["numerical_erosion"].severity, Severity.NO_OBVIOUS)


if __name__ == "__main__":
    unittest.main()
