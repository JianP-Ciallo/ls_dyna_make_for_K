from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from lsprepost_mcp.keyword_decomposition import decompose_keyword_deck, write_decomposition_package
from lsprepost_mcp.materials import get_material, list_materials
from lsprepost_mcp.model_library import get_model_resource, list_model_resources
from lsprepost_mcp.structural_resources import list_structural_resources


SOURCE_SHA256 = "c1c02a9e832852854b47cd3720bc9348cf48989484d25e1a54036836d0697a22"
MATERIAL_IDS = {
    "two_storey_rc_frame_mid5_concrete_kc",
    "two_storey_rc_frame_mid8_rebar_d8_d18",
    "two_storey_rc_frame_mid12_rebar_d12",
    "two_storey_rc_frame_mid14_rebar_d20",
    "two_storey_rc_frame_mid2_air_eos2",
    "two_storey_rc_frame_mid3_tnt_eos1",
}


class Phase18ResourceLibraryTests(unittest.TestCase):
    def test_formal_phase18_resources_are_effectively_reviewed(self) -> None:
        listed_materials = {row["id"]: row for row in list_materials()}
        for material_id in MATERIAL_IDS:
            with self.subTest(material_id=material_id):
                material = get_material(material_id)
                self.assertEqual("source_reference", material["validation_status"])
                self.assertEqual("syntax_unit_reviewed", material["effective_validation_status"])
                self.assertEqual("syntax_unit_reviewed", listed_materials[material_id]["effective_validation_status"])
                self.assertTrue(material["requires_project_review"])
                self.assertEqual(material_id, material["review"]["id"])

        structural = [row for row in list_structural_resources() if row["id"].startswith("two_storey_rc_frame_")]
        self.assertEqual(5, len(structural))
        self.assertTrue(all(row["effective_validation_status"] == "syntax_unit_reviewed" for row in structural))

    def test_six_source_material_bundles_are_in_material_library(self) -> None:
        listed = {row["id"] for row in list_materials()}
        self.assertTrue(MATERIAL_IDS.issubset(listed))

        for material_id in MATERIAL_IDS:
            material = get_material(material_id)
            self.assertEqual(SOURCE_SHA256, material["provenance"]["source_sha256"])
            self.assertEqual("source_reference", material["validation_status"])
            self.assertTrue(material["requires_project_review"])
            self.assertEqual("SI_m_s_kg_N_Pa", material["unit_system"])
            self.assertIn("source_cards", material)

    def test_material_values_and_dependencies_are_normalized(self) -> None:
        concrete = get_material("two_storey_rc_frame_mid5_concrete_kc")
        self.assertEqual(2400.0, concrete["density_kg_per_m3"])
        self.assertEqual(-30.4e6, concrete["parameters_si"]["a0_pa"])
        self.assertNotIn("ft_pa", concrete["parameters_si"])
        self.assertEqual("K&C automatic/default sentinel retained from source; it is not a physical zero tensile strength.", concrete["solver_semantics"]["ft"]["meaning"])
        self.assertNotIn("rsize_m", concrete["parameters_si"])
        self.assertNotIn("ucf", concrete["parameters_si"])
        self.assertEqual(0.03937, concrete["solver_unit_conversion"]["rsize_in_per_user_length_unit"])
        self.assertEqual(145.0, concrete["solver_unit_conversion"]["ucf_psi_per_user_stress_unit"])
        self.assertEqual(1, concrete["dependencies"]["rate_curve"]["lcid"])
        self.assertEqual(0.15, concrete["dependencies"]["mat_add_erosion"]["mxeps"])

        steel8 = get_material("two_storey_rc_frame_mid8_rebar_d8_d18")
        self.assertEqual([8.0, 18.0], steel8["section_diameters_mm"])
        self.assertEqual(455e6, steel8["yield_strength_pa"])
        self.assertEqual(6844.0, steel8["parameters_si"]["src_per_s"])

        self.assertEqual(460e6, get_material("two_storey_rc_frame_mid12_rebar_d12")["yield_strength_pa"])
        self.assertEqual(445e6, get_material("two_storey_rc_frame_mid14_rebar_d20")["yield_strength_pa"])

        air = get_material("two_storey_rc_frame_mid2_air_eos2")
        self.assertEqual(1.22, air["density_kg_per_m3"])
        self.assertEqual(250000.0, air["eos_si"]["e0_j_per_m3"])

        tnt = get_material("two_storey_rc_frame_mid3_tnt_eos1")
        self.assertEqual(1550.0, tnt["density_kg_per_m3"])
        self.assertEqual(8193.0, tnt["parameters_si"]["detonation_velocity_m_per_s"])
        self.assertEqual(28e9, tnt["parameters_si"]["cj_pressure_pa"])
        self.assertEqual(640e9, tnt["eos_si"]["a_pa"])
        self.assertEqual(13.9e9, tnt["eos_si"]["b_pa"])

    def test_complete_model_bundle_is_registered_with_mesh_and_relationships(self) -> None:
        listed = {row["id"] for row in list_model_resources()}
        self.assertIn("two_storey_rc_frame_blast_reference", listed)

        model = get_model_resource("two_storey_rc_frame_blast_reference")
        self.assertEqual(SOURCE_SHA256, model["provenance"]["source_sha256"])
        self.assertEqual(461452, model["mesh_statistics"]["nodes"])
        self.assertEqual(286840, model["mesh_statistics"]["solid_elements"])
        self.assertEqual(61961, model["mesh_statistics"]["beam_elements"])
        self.assertEqual(12, len(model["parts"]))
        self.assertEqual(6, len(model["sections"]))
        self.assertEqual(5, len(model["couplings"]))
        self.assertEqual(MATERIAL_IDS, set(model["material_resource_ids"]))
        self.assertFalse(model["solver_ready"])
        self.assertEqual("source_reference", model["validation_status"])

        json.dumps(model)
        payload_path = Path(model["_resource_dir"]) / model["payload"]["path"]
        self.assertTrue(payload_path.is_file())
        digest = hashlib.sha256(payload_path.read_bytes()).hexdigest()
        self.assertEqual(model["payload"]["sha256"], digest)
        with gzip.open(payload_path, "rt", encoding="utf-8", errors="replace") as handle:
            head = "".join(handle.readline() for _ in range(32))
        self.assertIn("*KEYWORD", head)
        self.assertIn("*PART", head)

    def test_payload_full_scan_matches_audited_mesh_and_excludes_unused_cards(self) -> None:
        model = get_model_resource("two_storey_rc_frame_blast_reference")
        payload_path = Path(model["_resource_dir"]) / model["payload"]["path"]
        active = ""
        data_rows = {"*NODE": 0, "*ELEMENT_SOLID": 0, "*ELEMENT_BEAM": 0}
        keyword_counts: dict[str, int] = {}
        with gzip.open(payload_path, "rt", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped.startswith("*"):
                    active = stripped.split()[0].upper()
                    keyword_counts[active] = keyword_counts.get(active, 0) + 1
                elif active in data_rows and stripped and not stripped.startswith("$"):
                    data_rows[active] += 1

        self.assertEqual(461452, data_rows["*NODE"])
        self.assertEqual(286840, data_rows["*ELEMENT_SOLID"] // 2)
        self.assertEqual(61961, data_rows["*ELEMENT_BEAM"])
        self.assertEqual(12, keyword_counts["*PART"])
        self.assertEqual(3, keyword_counts["*MAT_PLASTIC_KINEMATIC_TITLE"])
        self.assertEqual(5, keyword_counts["*CONSTRAINED_LAGRANGE_IN_SOLID_TITLE"])
        self.assertEqual(7, sum(count for keyword, count in keyword_counts.items() if keyword.startswith("*SET_")))
        for dependency_keyword in (
            "*MAT_ADD_EROSION", "*INITIAL_DETONATION", "*LOAD_BODY_PARTS", "*LOAD_BODY_Z",
            "*ALE_MULTI-MATERIAL_GROUP", "*BOUNDARY_SPC_SET", "*BOUNDARY_NON_REFLECTING",
        ):
            self.assertIn(dependency_keyword, keyword_counts)
        self.assertNotIn("*MAT_RHT_TITLE", keyword_counts)
        self.assertNotIn("*MAT_ELASTIC", keyword_counts)

    def test_package_writer_rehashes_the_source_instead_of_trusting_report_metadata(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "phase18" / "2k_minimal_reference.k"
        forged = decompose_keyword_deck(fixture, "tonne_mm_s_N_MPa")
        forged["source"]["sha256"] = SOURCE_SHA256
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "source SHA-256"):
                write_decomposition_package(forged, Path(directory) / "model")

    @unittest.skipUnless(Path("E:/Desktop/2.k").is_file(), "audited E:/Desktop/2.k is unavailable")
    def test_phase18b_assets_regenerate_byte_identically_without_local_paths(self) -> None:
        report = decompose_keyword_deck(Path("E:/Desktop/2.k"), "tonne_mm_s_N_MPa")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = []
            for name in ("first", "second"):
                output = root / name
                write_decomposition_package(
                    report,
                    output / "model",
                    output / "materials",
                    output / "structural",
                )
                outputs.append(output)

            first_files = sorted(path.relative_to(outputs[0]) for path in outputs[0].rglob("*") if path.is_file())
            second_files = sorted(path.relative_to(outputs[1]) for path in outputs[1].rglob("*") if path.is_file())
            self.assertEqual(first_files, second_files)
            for relative in first_files:
                with self.subTest(relative=str(relative)):
                    self.assertEqual((outputs[0] / relative).read_bytes(), (outputs[1] / relative).read_bytes())
                    if relative.suffix == ".json":
                        text = (outputs[0] / relative).read_text(encoding="utf-8")
                        self.assertNotIn("E:" + chr(92) + "Desktop", text)
                        self.assertNotIn("C:" + chr(92) + "Users", text)
                        self.assertNotIn('"_path"', text)
                        self.assertNotIn('"_resource_dir"', text)

    def test_unused_cards_exist_only_in_audit(self) -> None:
        model = get_model_resource("two_storey_rc_frame_blast_reference")
        audit = model["audit"]
        self.assertEqual([7, 8], audit["unused_section_ids"])
        self.assertEqual([9, 10, 11, 13], audit["unused_material_ids"])
        self.assertEqual([5, 7, 8], audit["unused_part_set_ids"])
        self.assertTrue(audit["excluded_from_payload"])
        self.assertFalse({"2k_mid9", "2k_mid10", "2k_mid11", "2k_mid13"} & {row["id"] for row in list_materials()})


if __name__ == "__main__":
    unittest.main()
