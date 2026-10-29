import unittest

from blast_damage_assessment.contracts import Severity
from blast_damage_assessment.evidence import EvidenceGraph, validate_evidence_graph


def closed_graph() -> EvidenceGraph:
    graph = EvidenceGraph()
    graph.add_source("source:d3plot", path="d3plot", sha256="a" * 64)
    graph.add_field("field:displacement", source_id="source:d3plot", field_name="node_displacement")
    graph.add_observation(
        "observation:column-7-state-3",
        field_id="field:displacement",
        entity_type="solid",
        entity_id=7,
        state_index=3,
        time=0.003,
    )
    graph.add_metric(
        "metric:column-7-deformation",
        observation_ids=("observation:column-7-state-3",),
        metric_name="relative_deformation_ratio",
        raw_value=0.012,
        raw_unit="1",
        standard_value=0.012,
        standard_unit="1",
        conversion_id="identity@1",
    )
    graph.add_rule_hit(
        "rule-hit:column-7-severe",
        metric_id="metric:column-7-deformation",
        rule_id="building_relative_deformation_ratio",
        actual_value=0.012,
        limit_value=0.01,
        operator=">=",
        severity=Severity.SEVERE,
    )
    graph.add_local_severity(
        "local:column-7",
        rule_hit_ids=("rule-hit:column-7-severe",),
        subject_id="building:column-7",
        severity=Severity.SEVERE,
    )
    graph.add_aggregate_severity(
        "aggregate:overall",
        local_severity_ids=("local:column-7",),
        severity=Severity.SEVERE,
    )
    return graph


class EvidenceGraphTests(unittest.TestCase):
    def test_complete_chain_validates_and_serializes_deterministically(self):
        graph = closed_graph()
        validate_evidence_graph(graph)
        payload = graph.to_dict()
        self.assertEqual(payload["schema_version"], "blast-evidence-graph@1")
        self.assertEqual(
            [node["kind"] for node in payload["nodes"]],
            ["aggregate_severity", "field", "local_severity", "metric", "observation", "rule_hit", "source"],
        )

    def test_rejects_dangling_ids(self):
        graph = closed_graph()
        graph._nodes["metric:column-7-deformation"] = graph._nodes["metric:column-7-deformation"].with_dependencies(
            ("observation:missing",)
        )
        with self.assertRaisesRegex(ValueError, "dangling"):
            validate_evidence_graph(graph)

    def test_rejects_cycles(self):
        graph = closed_graph()
        graph._nodes["source:d3plot"] = graph._nodes["source:d3plot"].with_dependencies(("aggregate:overall",))
        with self.assertRaisesRegex(ValueError, "cyclic"):
            validate_evidence_graph(graph)

    def test_rejects_metric_without_complete_unit_conversion(self):
        graph = closed_graph()
        metric = graph._nodes["metric:column-7-deformation"]
        graph._nodes[metric.node_id] = metric.with_payload({**metric.payload, "conversion_id": ""})
        with self.assertRaisesRegex(ValueError, "unit conversion"):
            validate_evidence_graph(graph)
    def test_rejects_unknown_or_false_rule_comparisons(self):
        for operator, actual, message in (
            ("approximately", 0.012, "operator"),
            (">=", 0.001, "comparison"),
            ("<", 0.02, "comparison"),
        ):
            with self.subTest(operator=operator):
                graph = closed_graph()
                rule = graph._nodes["rule-hit:column-7-severe"]
                graph._nodes[rule.node_id] = rule.with_payload(
                    {**rule.payload, "operator": operator, "actual_value": actual}
                )
                with self.assertRaisesRegex(ValueError, message):
                    validate_evidence_graph(graph)


    def test_rejects_conclusion_without_rule_hit(self):
        graph = closed_graph()
        graph._nodes["local:column-7"] = graph._nodes["local:column-7"].with_dependencies(())
        with self.assertRaisesRegex(ValueError, "rule hit"):
            validate_evidence_graph(graph)

    def test_rejects_nonfinite_rule_actual_or_limit(self):
        for field_name in ("actual_value", "limit_value"):
            with self.subTest(field_name=field_name):
                graph = closed_graph()
                rule = graph._nodes["rule-hit:column-7-severe"]
                graph._nodes[rule.node_id] = rule.with_payload({**rule.payload, field_name: float("inf")})
                with self.assertRaisesRegex(ValueError, "finite"):
                    validate_evidence_graph(graph)

    def test_rejects_duplicate_ids_and_wrong_dependency_types(self):
        graph = closed_graph()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            graph.add_source("source:d3plot", path="copy", sha256="b" * 64)
        graph._nodes["metric:column-7-deformation"] = graph._nodes["metric:column-7-deformation"].with_dependencies(
            ("source:d3plot",)
        )
        with self.assertRaisesRegex(ValueError, "must derive"):
            validate_evidence_graph(graph)


if __name__ == "__main__":
    unittest.main()
