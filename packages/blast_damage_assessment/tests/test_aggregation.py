import unittest
from dataclasses import dataclass

from blast_damage_assessment.aggregation import AggregateAssessment, aggregate_assessment
from blast_damage_assessment.contracts import GateState, Severity


@dataclass(frozen=True)
class SubjectStub:
    gate: GateState
    severity: Severity | None
    governing_rule_hits: tuple[str, ...]
    subratings: dict[str, object] | None = None


class AggregationTruthTableTests(unittest.TestCase):
    def subject(self, gate, severity, *hits, subratings=None):
        return SubjectStub(gate, severity, tuple(hits), subratings)

    def test_both_assessable_use_maximum_credible_severity(self):
        building = self.subject(GateState.FORMAL, Severity.MODERATE, "building:deflection")
        ground = self.subject(GateState.FORMAL, Severity.SEVERE, "ground:crater")
        result = aggregate_assessment(building, ground)
        self.assertIsInstance(result, AggregateAssessment)
        self.assertEqual(result.gate, GateState.FORMAL)
        self.assertEqual(result.severity, Severity.SEVERE)
        self.assertFalse(result.partial_assessment)
        self.assertEqual(result.governing_subjects, ("ground",))
        self.assertEqual(result.governing_rule_hits, ("ground:crater",))

    def test_any_provisional_caps_overall_gate(self):
        result = aggregate_assessment(
            self.subject(GateState.FORMAL, Severity.MINOR, "building:minor"),
            self.subject(GateState.PROVISIONAL, Severity.MODERATE, "ground:moderate"),
        )
        self.assertEqual(result.gate, GateState.PROVISIONAL)
        self.assertEqual(result.severity, Severity.MODERATE)

    def test_any_blocked_nulls_overall_but_retains_unblocked_subject(self):
        result = aggregate_assessment(
            self.subject(GateState.BLOCKED, None),
            self.subject(GateState.PROVISIONAL, Severity.MODERATE, "ground:moderate"),
        )
        self.assertEqual(result.gate, GateState.BLOCKED)
        self.assertIsNone(result.severity)
        self.assertTrue(result.partial_assessment)
        self.assertIsNone(result.subjects["building"].severity)
        self.assertEqual(result.subjects["ground"].severity, Severity.MODERATE)

    def test_unavailable_submetric_cannot_enter_maximum(self):
        unavailable = type("Rating", (), {"available": False, "severity": Severity.EXTREME})()
        result = aggregate_assessment(
            self.subject(GateState.FORMAL, Severity.MINOR, "building:minor"),
            self.subject(
                GateState.FORMAL,
                Severity.MODERATE,
                "ground:crater",
                subratings={"unsupported_material": unavailable},
            ),
        )
        self.assertEqual(result.severity, Severity.MODERATE)

    def test_ties_retain_all_governing_subjects_and_rule_hits_deterministically(self):
        result = aggregate_assessment(
            self.subject(GateState.PROVISIONAL, Severity.SEVERE, "z-rule", "a-rule"),
            self.subject(GateState.PROVISIONAL, Severity.SEVERE, "ground-rule", "a-rule"),
        )
        self.assertEqual(result.governing_subjects, ("building", "ground"))
        self.assertEqual(result.governing_rule_hits, ("a-rule", "z-rule", "ground-rule"))

    def test_rejects_inconsistent_blocked_or_assessable_subject(self):
        with self.assertRaisesRegex(ValueError, "blocked subject severity"):
            aggregate_assessment(
                self.subject(GateState.BLOCKED, Severity.SEVERE),
                self.subject(GateState.FORMAL, Severity.MINOR, "ground:minor"),
            )
        with self.assertRaisesRegex(ValueError, "assessable subject severity"):
            aggregate_assessment(
                self.subject(GateState.FORMAL, None),
                self.subject(GateState.FORMAL, Severity.MINOR, "ground:minor"),
            )


if __name__ == "__main__":
    unittest.main()
