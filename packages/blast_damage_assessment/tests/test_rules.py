import json
import tempfile
import unittest
from pathlib import Path

from blast_damage_assessment.errors import ContractError, UnsupportedSchemaError
from blast_damage_assessment.rules import (
    check_rule_applicability,
    load_rule_pack,
    snapshot_rule_pack,
)


FIXTURES = Path(__file__).parent / "fixtures" / "rules"


class RulePackTests(unittest.TestCase):
    def test_research_packs_have_exact_bands_and_are_not_formal(self):
        building = load_rule_pack("building_research_reference@1")
        ground = load_rule_pack("ground_research_reference@1")
        self.assertEqual(building.rule("building_relative_deformation_ratio")["bands"], (0.0025, 0.005, 0.01, 0.02))
        self.assertEqual(building.rule("building_stress_to_declared_yield_ratio")["bands"], (0.8, 1.0, 1.2, 1.5))
        self.assertEqual(ground.rule("ground_depth_to_median_surface_cell")["bands"], (0.1, 0.25, 0.5, 1.0))
        self.assertEqual(ground.rule("ground_connected_area_in_surface_cells")["bands"], (4, 16, 64, 256))
        self.assertFalse(building.formal_eligible)
        self.assertFalse(ground.formal_eligible)

    def test_snapshot_is_stable_and_loaded_payload_is_immutable(self):
        pack = load_rule_pack("building_research_reference@1")
        first = snapshot_rule_pack(pack)
        second = snapshot_rule_pack(load_rule_pack("building_research_reference@1"))
        self.assertEqual(first.sha256, second.sha256)
        with self.assertRaises(TypeError):
            pack.payload["label"] = "mutated"
        with self.assertRaises(TypeError):
            pack.rule("building_relative_deformation_ratio")["bands"][0] = 99

    def test_rejects_schema_duplicates_bands_and_missing_basis(self):
        base = json.loads((FIXTURES / "building_project_calibrated_v1.json").read_text())
        variants = []
        variants.append(({**base, "schema_version": "blast_damage.rule_pack@2"}, UnsupportedSchemaError, "@2"))
        duplicate = {**base, "rules": base["rules"] * 2}
        variants.append((duplicate, ContractError, "duplicate"))
        nonmonotonic = json.loads(json.dumps(base))
        nonmonotonic["rules"][0]["bands"] = [0.1, 0.2, 0.2, 0.4]
        variants.append((nonmonotonic, ContractError, "monotonic"))
        no_citations = {**base, "citations": []}
        variants.append((no_citations, ContractError, "citation"))
        no_applicability = json.loads(json.dumps(base))
        no_applicability["rules"][0]["applicability"] = []
        variants.append((no_applicability, ContractError, "applicability"))
        for raw, error, message in variants:
            with self.subTest(message=message):
                with self.assertRaisesRegex(error, message):
                    load_rule_pack(self.write(raw))

    def test_formal_pack_requires_complete_matching_review_binding(self):
        valid = load_rule_pack(FIXTURES / "building_project_calibrated_v1.json")
        subject = {
            "unit_system": "SI_m_s_kg_N_Pa",
            "material_ids": [3, 4],
            "subject_family": "reinforced_concrete",
            "geometry_assumptions": {"response": "flexural"},
            "response_type": True,
            "support_definition": True,
        }
        self.assertTrue(check_rule_applicability(valid, subject).applicable)
        mismatch = {**subject, "material_ids": [3]}
        self.assertFalse(check_rule_applicability(valid, mismatch).applicable)

        raw = json.loads((FIXTURES / "building_project_calibrated_v1.json").read_text())
        raw["review_record"].pop("reviewer")
        with self.assertRaisesRegex(ContractError, "review"):
            load_rule_pack(self.write(raw))

    def test_both_calibrated_fixtures_are_formal_and_hash_bound(self):
        for name in ("building_project_calibrated_v1.json", "ground_project_calibrated_v1.json"):
            with self.subTest(name=name):
                pack = load_rule_pack(FIXTURES / name)
                self.assertTrue(pack.formal_eligible)
                self.assertEqual(len(snapshot_rule_pack(pack).sha256), 64)

    def test_pdc_profiles_preserve_terms_mapping_and_closed_applicability(self):
        pack = load_rule_pack("building_research_reference@1")
        profile = pack.rule("pdc_rc_each_face_qualifying_shear")
        self.assertEqual(profile["severity_mapping"], (0, 2, 3, 4))
        self.assertEqual(profile["original_terms"][-1], "Hazardous Failure")
        incomplete = {name: True for name in profile["applicability"][:-1]}
        result = check_rule_applicability(pack, incomplete, rule_id=profile["id"])
        self.assertFalse(result.applicable)
        self.assertIn("inbound_rebound_handling", result.missing)

    def write(self, raw):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "rule.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
