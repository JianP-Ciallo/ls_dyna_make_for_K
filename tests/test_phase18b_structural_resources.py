from __future__ import annotations

import copy
from pathlib import Path
import unittest

from lsprepost_mcp.keyword_decomposition import _2k_structural_assets, decompose_keyword_deck
from lsprepost_mcp.materials import get_material
from lsprepost_mcp.structural_resources import validate_structural_catalog_closure


SOURCE_2K = Path("E:/Desktop/2.k")
STRUCTURAL_RESOURCE_IDS = {
    "two_storey_rc_frame_sections",
    "two_storey_rc_frame_kc_rate_curve",
    "two_storey_rc_frame_part_roles",
    "two_storey_rc_frame_sets",
    "two_storey_rc_frame_embedded_couplings",
}
MATERIAL_IDS = {
    "two_storey_rc_frame_mid2_air_eos2",
    "two_storey_rc_frame_mid3_tnt_eos1",
    "two_storey_rc_frame_mid5_concrete_kc",
    "two_storey_rc_frame_mid8_rebar_d8_d18",
    "two_storey_rc_frame_mid12_rebar_d12",
    "two_storey_rc_frame_mid14_rebar_d20",
}


@unittest.skipUnless(SOURCE_2K.is_file(), "audited E:/Desktop/2.k is unavailable")
class StructuralCatalogWriterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = decompose_keyword_deck(SOURCE_2K, "tonne_mm_s_N_MPa")
        cls.assets = _2k_structural_assets(cls.report)
        cls.by_id = {row["id"]: row for row in cls.assets}

    def _closure_fixture(self) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
        return (
            copy.deepcopy(self.assets),
            copy.deepcopy({material_id: get_material(material_id) for material_id in MATERIAL_IDS}),
        )

    def test_writer_emits_five_source_reference_catalogs(self) -> None:
        self.assertEqual(STRUCTURAL_RESOURCE_IDS, set(self.by_id))
        self.assertTrue(all(row["validation_status"] == "source_reference" for row in self.assets))
        self.assertTrue(all(row["requires_project_review"] for row in self.assets))

    def test_used_catalog_counts_and_si_dimensions_are_exact(self) -> None:
        self.assertEqual(6, len(self.by_id["two_storey_rc_frame_sections"]["items"]))
        self.assertEqual(0.008, self.by_id["two_storey_rc_frame_sections"]["items"][0]["diameter_m"])
        self.assertEqual(23, len(self.by_id["two_storey_rc_frame_kc_rate_curve"]["points"]))
        self.assertEqual(12, len(self.by_id["two_storey_rc_frame_part_roles"]["items"]))
        self.assertEqual(7, len(self.by_id["two_storey_rc_frame_sets"]["items"]))
        self.assertEqual(5, len(self.by_id["two_storey_rc_frame_embedded_couplings"]["items"]))

    def test_catalog_excludes_audit_only_ids_and_resolves_endpoint_kinds(self) -> None:
        sections = {item["secid"] for item in self.by_id["two_storey_rc_frame_sections"]["items"]}
        set_keys = {(item["set_type"], item["source_id"]) for item in self.by_id["two_storey_rc_frame_sets"]["items"]}
        couplings = self.by_id["two_storey_rc_frame_embedded_couplings"]["items"]

        self.assertEqual({1, 2, 3, 4, 5, 6}, sections)
        self.assertNotIn(("part", 5), set_keys)
        self.assertTrue(all(row["slave_kind"] in {"set", "part"} for row in couplings))
        self.assertTrue(all(row["master_kind"] in {"set", "part"} for row in couplings))

    def test_structural_catalog_dependency_closure_is_valid(self) -> None:
        materials = {material_id: get_material(material_id) for material_id in MATERIAL_IDS}

        try:
            report = validate_structural_catalog_closure(self.assets, materials)
        except ValueError as exc:
            self.fail(f"canonical structural catalog should validate: {exc}")

        self.assertTrue(report["valid"])
        self.assertEqual(6, report["section_count"])
        self.assertEqual(12, report["part_count"])
        self.assertEqual(5, report["coupling_count"])

    def test_closure_rejects_invalid_referenced_material(self) -> None:
        materials = {material_id: get_material(material_id) for material_id in MATERIAL_IDS}
        material_id = "two_storey_rc_frame_mid12_rebar_d12"
        materials[material_id] = copy.deepcopy(materials[material_id])
        materials[material_id]["density_kg_per_m3"] = -1.0

        with self.assertRaisesRegex(ValueError, "density_kg_per_m3"):
            validate_structural_catalog_closure(self.assets, materials)

    def test_closure_rejects_material_key_and_object_identity_mismatch(self) -> None:
        materials = {material_id: get_material(material_id) for material_id in MATERIAL_IDS}
        first_id = "two_storey_rc_frame_mid12_rebar_d12"
        second_id = "two_storey_rc_frame_mid14_rebar_d20"
        materials[first_id], materials[second_id] = materials[second_id], materials[first_id]

        with self.assertRaisesRegex(ValueError, "key/object identity mismatch"):
            validate_structural_catalog_closure(self.assets, materials)

    def test_closure_rejects_duplicate_set_identity(self) -> None:
        assets, materials = self._closure_fixture()
        by_id = {row["id"]: row for row in assets}
        set_items = by_id["two_storey_rc_frame_sets"]["items"]
        set_items[-1] = copy.deepcopy(set_items[0])

        with self.assertRaisesRegex(ValueError, "duplicate Set identity"):
            validate_structural_catalog_closure(assets, materials)

    def test_closure_rejects_duplicate_coupling_index(self) -> None:
        assets, materials = self._closure_fixture()
        by_id = {row["id"]: row for row in assets}
        coupling_items = by_id["two_storey_rc_frame_embedded_couplings"]["items"]
        coupling_items[-1]["coupling_index"] = coupling_items[0]["coupling_index"]

        with self.assertRaisesRegex(ValueError, "duplicate coupling_index"):
            validate_structural_catalog_closure(assets, materials)

    def test_closure_rejects_duplicate_coupling_relation(self) -> None:
        assets, materials = self._closure_fixture()
        by_id = {row["id"]: row for row in assets}
        coupling_items = by_id["two_storey_rc_frame_embedded_couplings"]["items"]
        for field in ("slave_kind", "ssid", "master_kind", "msid", "sstyp", "mstyp"):
            coupling_items[-1][field] = coupling_items[0][field]

        with self.assertRaisesRegex(ValueError, "duplicate coupling relation"):
            validate_structural_catalog_closure(assets, materials)


if __name__ == "__main__":
    unittest.main()
