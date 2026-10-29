import unittest

import numpy as np

from blast_damage_assessment.building.evaluator import (
    ComponentEvaluationInput,
    evaluate_building,
    evaluate_component,
    evaluate_material_metrics,
)
from blast_damage_assessment.contracts import GateState, Severity
from blast_damage_assessment.material_capabilities import capability_for_material
from blast_damage_assessment.rules import load_rule_pack
from blast_damage_assessment.semantics import ComponentSemantics


def component(component_id="c1", importance="primary", primary=True, zone=None):
    return ComponentSemantics(component_id, "column", (1,), (3,), importance, primary, zone)


class ComponentEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.rules = load_rule_pack("building_research_reference@1")
        self.entity_ids = np.arange(100, 200)
        self.connectivity = np.array([[i, i + 1] for i in range(100)])

    def evaluate(self, values, **changes):
        inputs = ComponentEvaluationInput(
            component=component(),
            entity_ids=self.entity_ids,
            relative_deformation=np.asarray(values, dtype=float),
            connectivity=self.connectivity,
            entity_kind="beam",
            support_semantics_explicit=True,
            load_path_semantics_explicit=True,
            **changes,
        )
        return evaluate_component(inputs, self.rules)

    def test_isolated_raw_spike_is_anomaly_and_cannot_raise_severity(self):
        values = np.zeros(100)
        values[50] = 0.03
        result = self.evaluate(values)
        self.assertEqual(result.severity, Severity.NO_OBVIOUS)
        self.assertTrue(result.anomalies)
        self.assertEqual(result.connected_affected_count, 0)
    def test_connected_region_can_be_restricted_to_a_persistent_state(self):
        values = np.zeros(100)
        values[40:44] = 0.03
        result = self.evaluate(
            values,
            connected_affected=np.zeros(100, dtype=bool),
            connected_metric=np.zeros(100),
        )
        self.assertEqual(result.connected_affected_count, 0)


    def test_connected_region_of_four_can_govern(self):
        values = np.zeros(100)
        values[40:44] = 0.03
        result = self.evaluate(values)
        self.assertEqual(result.severity, Severity.EXTREME)
        self.assertEqual(result.connected_affected_count, 4)
        self.assertEqual(result.governing_relative_deformation, 0.03)

    def test_numerical_deletion_requires_connection_or_corroboration(self):
        values = np.zeros(100)
        alive = np.ones(100, dtype=bool)
        alive[50] = False
        isolated = self.evaluate(values, alive=alive)
        self.assertEqual(isolated.severity, Severity.NO_OBVIOUS)
        alive[20:24] = False
        connected = self.evaluate(values, alive=alive)
        evidence = next(
            item for item in connected.rule_evidence
            if item.rule_id == "numerical_deletion_connected"
        )
        self.assertEqual(evidence.metric_name, "connected_deleted_element_count")
        self.assertEqual(evidence.actual_value, 4.0)
        self.assertEqual(evidence.limit_value, 4.0)
        self.assertEqual(evidence.operator, ">=")

        self.assertGreaterEqual(connected.severity, Severity.SEVERE)
        self.assertEqual(connected.gate, GateState.PROVISIONAL)

    def test_inferred_motion_reference_caps_formality(self):
        result = self.evaluate(np.zeros(100), reference_motion_inferred=True)
        self.assertEqual(result.gate, GateState.PROVISIONAL)

    def test_material_metric_names_follow_capability(self):
        kandc = capability_for_material({"material_id": 3, "model": "MAT_072R3", "nout": 2})
        elastic = capability_for_material({"material_id": 7, "model": "elastic"})
        k_metrics = evaluate_material_metrics(kandc, history=np.array([0.4]), effective_plastic_strain=None)
        e_metrics = evaluate_material_metrics(elastic, history=None, effective_plastic_strain=np.array([0.2]))
        self.assertTrue(k_metrics["scaled_damage_measure"].available)
        self.assertFalse(e_metrics["effective_plastic_strain"].available)


class BuildingAggregationTests(unittest.TestCase):
    def test_nonstructural_extreme_does_not_raise_whole_building_without_consequence(self):
        primary = evaluate_component(
            ComponentEvaluationInput(component(), np.arange(10), np.zeros(10), np.array([[i, i + 1] for i in range(10)]), "beam", True, True),
            load_rule_pack("building_research_reference@1"),
        )
        nonstructural = primary.with_classification("nonstructural", Severity.EXTREME)
        result = evaluate_building((primary, nonstructural))
        self.assertEqual(result.severity, Severity.NO_OBVIOUS)
        self.assertEqual(result.class_severities["nonstructural"], Severity.EXTREME)

    def test_hazardous_debris_can_raise_whole_building_consequence(self):
        base = evaluate_component(
            ComponentEvaluationInput(component(), np.arange(10), np.zeros(10), np.array([[i, i + 1] for i in range(10)]), "beam", True, True),
            load_rule_pack("building_research_reference@1"),
        )
        debris = base.with_classification("nonstructural", Severity.SEVERE, hazardous_debris=True)
        self.assertEqual(evaluate_building((base, debris)).severity, Severity.SEVERE)


if __name__ == "__main__":
    unittest.main()
