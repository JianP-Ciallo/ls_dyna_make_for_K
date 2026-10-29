import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

from blast_damage_assessment.contracts import FileReference
from blast_damage_assessment.errors import ContractError
from blast_damage_assessment.material_capabilities import (
    capability_for_material,
    meaning_for_alive_state,
)
from blast_damage_assessment.semantics import load_semantics


FIXTURES = Path(__file__).parent / "fixtures" / "semantics"


def reference(path: Path) -> FileReference:
    return FileReference(path, hashlib.sha256(path.read_bytes()).hexdigest())


class SemanticTests(unittest.TestCase):
    def test_loads_explicit_native_components_zones_axes_and_ground(self):
        semantics = load_semantics(reference(FIXTURES / "native_semantics_v1.json"))
        self.assertFalse(semantics.legacy)
        self.assertEqual(semantics.vertical_axis, "z")
        self.assertEqual(semantics.blast_center_m, (0.0, 0.0, 1.0))
        self.assertEqual(semantics.components[0].component_id, "column-a")
        self.assertEqual(semantics.components[0].zone_id, "zone-a")
        self.assertEqual(semantics.ground.part_ids, (8001,))
        self.assertEqual(semantics.inferences, ())

    def test_native_records_inferred_generator_classification_provenance(self):
        raw = json.loads((FIXTURES / "native_semantics_v1.json").read_text())
        raw["classification"] = {
            "source": "inferred_generator_mapping@1",
            "part_role_bindings": [
                {
                    "part_role": "column-role",
                    "part_id": 1001,
                    "component_id": "column-a",
                    "material_id": 3,
                },
                {
                    "part_role": "column-rebar-role",
                    "part_id": 1002,
                    "component_id": "column-a",
                    "material_id": 4,
                },
            ],
            "generator_fingerprints": {
                "building_artifact": "a" * 64,
                "solver_scene": "b" * 64,
            },
        }

        semantics = self.load_temp(raw)

        self.assertEqual(semantics.classification_source, "inferred_generator_mapping@1")
        self.assertFalse(semantics.importance_explicit)
        self.assertTrue(any(row.reason == "inferred_generator_mapping@1" for row in semantics.inferences))

    def test_native_rejects_component_edge_to_unknown_zone(self):
        raw = json.loads((FIXTURES / "native_semantics_v1.json").read_text())
        raw["building"]["components"][0]["zone_id"] = "missing"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "unknown zone"):
                load_semantics(reference(path))

    def test_native_rejects_nonfinite_or_inconsistent_axes(self):
        base = json.loads((FIXTURES / "native_semantics_v1.json").read_text())
        variants = []
        nonfinite = json.loads(json.dumps(base))
        nonfinite["blast_center_m"][0] = math.nan
        variants.append((nonfinite, "finite"))
        duplicate_axis = json.loads(json.dumps(base))
        duplicate_axis["axes"] = {"vertical": "z", "horizontal": ["x", "z"]}
        variants.append((duplicate_axis, "permutation"))
        wrong_surface_axis = json.loads(json.dumps(base))
        wrong_surface_axis["ground"]["surface"]["axis"] = "y"
        variants.append((wrong_surface_axis, "vertical"))
        for raw, message in variants:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ContractError, message):
                    self.load_temp(raw)

    def test_native_rejects_unknown_fields_enums_and_material_references(self):
        base = json.loads((FIXTURES / "native_semantics_v1.json").read_text())
        variants = []
        unknown = json.loads(json.dumps(base))
        unknown["building"]["components"][0]["typo_field"] = True
        variants.append((unknown, "unknown field"))
        importance = json.loads(json.dumps(base))
        importance["building"]["components"][0]["importance_class"] = "critical-ish"
        variants.append((importance, "importance_class"))
        missing_material = json.loads(json.dumps(base))
        missing_material["building"]["components"][0]["material_ids"] = [999]
        variants.append((missing_material, "unknown material"))
        duplicate_material = json.loads(json.dumps(base))
        duplicate_material["materials"].append(dict(duplicate_material["materials"][0]))
        variants.append((duplicate_material, "duplicate material"))
        for raw, message in variants:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ContractError, message):
                    self.load_temp(raw)

    def test_native_rejects_classification_binding_that_disagrees_with_component(self):
        raw = json.loads((FIXTURES / "native_semantics_v1.json").read_text())
        raw["classification"] = {
            "source": "inferred_generator_mapping@1",
            "part_role_bindings": [{
                "part_role": "wrong", "part_id": 9999,
                "component_id": "column-a", "material_id": 3,
            }],
            "generator_fingerprints": {"solver_scene": "a" * 64},
        }
        with self.assertRaisesRegex(ContractError, "classification binding"):
            self.load_temp(raw)

    def test_normalizes_legacy_v1_and_v4_and_caps_formality(self):
        for name in ("legacy_phase18_manifest_v1.json", "legacy_phase18_manifest_v4.json"):
            with self.subTest(name=name):
                semantics = load_semantics(reference(FIXTURES / name))
                self.assertTrue(semantics.legacy)
                self.assertFalse(semantics.formal_eligible)
                self.assertTrue(semantics.inferences)
                self.assertEqual(semantics.ground.part_ids, (8001,))
                self.assertTrue(any(c.role == "column" for c in semantics.components))

    def test_groups_structural_subparts_and_keeps_nonstructural_separate(self):
        semantics = load_semantics(reference(FIXTURES / "legacy_phase18_manifest_v1.json"))
        columns = next(c for c in semantics.components if c.role == "column")
        self.assertEqual(set(columns.part_ids), {1001, 1002, 1003})
        partition = next(c for c in semantics.components if c.role == "partition")
        self.assertFalse(partition.primary_load_path)
        self.assertEqual(partition.importance_class, "nonstructural")


    def test_context_specific_rebar_parts_join_their_structural_component(self):
        raw = json.loads((FIXTURES / "legacy_phase18_manifest_v1.json").read_text())
        raw["part_ids"].extend(
            [
                ["hybrid_foundation", 1100],
                ["foundation_rebar", 1101],
                ["hybrid_slab", 1102],
                ["slab_rebar", 1103],
            ]
        )
        semantics = self.load_temp(raw)
        foundation = next(c for c in semantics.components if c.component_id == "commercial_foundation")
        slab = next(c for c in semantics.components if c.component_id == "commercial_slab")
        self.assertEqual(set(foundation.part_ids), {1100, 1101})
        self.assertEqual(set(slab.part_ids), {1102, 1103})
        self.assertEqual(len([c for c in semantics.components if c.role == "foundation"]), 1)
        self.assertEqual(len([c for c in semantics.components if c.role == "slab"]), 1)
    def test_unknown_noncritical_part_is_visible_but_excluded(self):
        raw = json.loads((FIXTURES / "legacy_phase18_manifest_v1.json").read_text())
        raw["part_ids"].append(["custom_signage", 77])
        semantics = self.load_temp(raw)
        self.assertIn(77, semantics.excluded_part_ids)
        self.assertTrue(any(issue.code == "semantics.unclassified_noncritical" for issue in semantics.warnings))
        self.assertEqual(semantics.building_blockers, ())

    def test_unclassified_primary_part_blocks_building_only(self):
        raw = json.loads((FIXTURES / "legacy_phase18_manifest_v1.json").read_text())
        raw["part_ids"].append(["custom_transfer_member", 78])
        raw["primary_load_path_part_ids"] = [78]
        semantics = self.load_temp(raw)
        self.assertTrue(semantics.building_blockers)
        self.assertFalse(semantics.ground_blockers)

    def test_missing_or_ambiguous_diagnostic_ground_blocks_ground_only(self):
        base = json.loads((FIXTURES / "legacy_phase18_manifest_v1.json").read_text())
        cases = (
            [row for row in base["part_ids"] if row[0] != "diagnostic_soil_ground"],
            base["part_ids"] + [["diagnostic_soil_ground", 8002]],
        )
        for part_ids in cases:
            with self.subTest(part_ids=part_ids):
                raw = {**base, "part_ids": part_ids}
                semantics = self.load_temp(raw)
                self.assertTrue(semantics.ground_blockers)
                self.assertFalse(semantics.building_blockers)

    def load_temp(self, raw):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "manifest.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        return load_semantics(reference(path))


class MaterialCapabilityTests(unittest.TestCase):
    def test_kandc_nout_2_is_scaled_damage_not_generic_eps(self):
        capability = capability_for_material(
            {"material_id": 3, "model": "MAT_072R3", "nout": 2, "engineering_validated": True}
        )
        self.assertEqual(capability.history_meanings[0], "scaled_damage_measure")
        self.assertNotIn("effective_plastic_strain", capability.history_meanings.values())

    def test_elastic_material_has_no_plastic_damage_conclusion(self):
        capability = capability_for_material(
            {"material_id": 7, "model": "elastic", "engineering_validated": False}
        )
        self.assertIn("stress", capability.supported_metrics)
        self.assertIn("deformation", capability.supported_metrics)
        self.assertNotIn("plastic_damage", capability.supported_metrics)

    def test_steel_eps_requires_yield_and_calibration_metadata(self):
        incomplete = capability_for_material({"material_id": 4, "model": "steel_plasticity"})
        complete = capability_for_material(
            {
                "material_id": 4,
                "model": "steel_plasticity",
                "yield_stress_pa": 355e6,
                "calibration_id": "steel-a@1",
                "engineering_validated": True,
            }
        )
        self.assertNotIn("effective_plastic_strain", incomplete.supported_metrics)
        self.assertIn("effective_plastic_strain", complete.supported_metrics)

    def test_alive_state_means_numerical_deletion_only(self):
        self.assertEqual(meaning_for_alive_state(), "numerical_deletion")


if __name__ == "__main__":
    unittest.main()
