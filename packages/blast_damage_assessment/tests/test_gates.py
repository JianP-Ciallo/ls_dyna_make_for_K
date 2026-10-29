import hashlib
import unittest
from pathlib import Path

from blast_damage_assessment.contracts import FileReference, GateState
from blast_damage_assessment.gates import (
    BuildingGateFacts,
    CommonGateFacts,
    GroundGateFacts,
    combine_gate_states,
    evaluate_building_gate,
    evaluate_common_gate,
    evaluate_ground_gate,
)
from blast_damage_assessment.semantics import load_semantics


SEMANTIC_FIXTURES = Path(__file__).parent / "fixtures" / "semantics"


def common(**changes):
    values = {
        "termination": "normal",
        "final_time": 1.0,
        "target_time": 1.0,
        "units_known": True,
        "evidence_unchanged": True,
        "request_schema_supported": True,
        "legacy_inference": False,
        "preliminary_materials": False,
    }
    values.update(changes)
    return CommonGateFacts(**values)


class CommonGateTests(unittest.TestCase):
    def test_hard_failures_block_both_subjects(self):
        cases = (
            ({"termination": "abnormal"}, "solver.termination"),
            ({"final_time": 0.98}, "solver.coverage"),
            ({"units_known": False}, "semantics.units"),
            ({"evidence_unchanged": False}, "evidence.changed"),
            ({"request_schema_supported": False}, "request.schema"),
        )
        for changes, code in cases:
            with self.subTest(changes=changes):
                decision = evaluate_common_gate(common(**changes), subject_id="case:building")
                self.assertEqual(decision.state, GateState.BLOCKED)
                self.assertIn(code, {issue.code for issue in decision.issues})

    def test_legacy_and_preliminary_materials_cap_at_provisional(self):
        for changes in ({"legacy_inference": True}, {"preliminary_materials": True}):
            with self.subTest(changes=changes):
                self.assertEqual(
                    evaluate_common_gate(common(**changes), subject_id="case").state,
                    GateState.PROVISIONAL,
                )

    def test_every_transition_issue_has_provenance_and_remediation(self):
        decision = evaluate_common_gate(common(units_known=False), subject_id="case:ground")
        details = decision.issues[0].details
        for key in ("subject_id", "gate_state", "source_evidence_ids", "affected_metrics", "remediation"):
            self.assertIn(key, details)


class SubjectGateTests(unittest.TestCase):
    def test_missing_building_identity_blocks_building_not_ground(self):
        building = evaluate_building_gate(BuildingGateFacts(common(), identity_available=False))
        ground = evaluate_ground_gate(GroundGateFacts(common()))
        self.assertEqual(building.state, GateState.BLOCKED)
        self.assertEqual(ground.state, GateState.FORMAL)

    def test_missing_ground_identity_blocks_ground_not_building(self):
        ground = evaluate_ground_gate(GroundGateFacts(common(), identity_available=False))
        building = evaluate_building_gate(BuildingGateFacts(common()))
        self.assertEqual(ground.state, GateState.BLOCKED)
        self.assertEqual(building.state, GateState.FORMAL)

    def test_missing_strain_and_stress_with_deformation_is_provisional(self):
        decision = evaluate_building_gate(
            BuildingGateFacts(common(), deformation_available=True, stress_available=False, strain_available=False)
        )
        self.assertEqual(decision.state, GateState.PROVISIONAL)
        self.assertEqual(set(decision.unavailable_metrics), {"stress", "strain"})

    def test_missing_velocity_only_caps_ground_and_forbids_residual_wording(self):
        building = evaluate_building_gate(BuildingGateFacts(common()))
        ground = evaluate_ground_gate(GroundGateFacts(common(), velocity_available=False))
        self.assertEqual(building.state, GateState.FORMAL)
        self.assertEqual(ground.state, GateState.PROVISIONAL)
        self.assertFalse(ground.residual_wording_allowed)

    def test_combination_uses_worst_state_and_cannot_upgrade(self):
        self.assertEqual(combine_gate_states(GateState.FORMAL, GateState.PROVISIONAL), GateState.PROVISIONAL)
        self.assertEqual(combine_gate_states(GateState.FORMAL, GateState.BLOCKED), GateState.BLOCKED)
        decision = evaluate_common_gate(common(legacy_inference=True), subject_id="case")
        self.assertEqual(decision.degrade(GateState.FORMAL).state, GateState.PROVISIONAL)

    def test_all_legacy_fixtures_remain_provisional_with_complete_solver_fields(self):
        for name in ("legacy_phase18_manifest_v1.json", "legacy_phase18_manifest_v4.json"):
            path = SEMANTIC_FIXTURES / name
            semantics = load_semantics(FileReference(path, hashlib.sha256(path.read_bytes()).hexdigest()))
            facts = common(
                legacy_inference=semantics.legacy,
                preliminary_materials=not semantics.formal_eligible,
            )
            with self.subTest(name=name):
                self.assertEqual(evaluate_building_gate(BuildingGateFacts(facts)).state, GateState.PROVISIONAL)
                self.assertEqual(evaluate_ground_gate(GroundGateFacts(facts)).state, GateState.PROVISIONAL)


if __name__ == "__main__":
    unittest.main()
