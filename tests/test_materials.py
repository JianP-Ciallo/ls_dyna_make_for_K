from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from lsprepost_mcp.dyna_cards import material_lines
from lsprepost_mcp.materials import get_material, list_materials, load_materials, resolve_material
from lsprepost_mcp.schema import default_model_spec, parse_model_spec


class MaterialsTests(unittest.TestCase):
    @staticmethod
    def _write_material(path: Path, material_id: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"id": material_id}), encoding="utf-8")

    def test_nested_material_resource_is_discovered_by_stable_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_material(root / "phase18" / "2k" / "steel.json", "stable_steel")

            self.assertIn("stable_steel", load_materials(root))

    def test_duplicate_material_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_material(root / "a" / "one.json", "duplicate")
            self._write_material(root / "b" / "two.json", "duplicate")

            with self.assertRaisesRegex(ValueError, "duplicate material resource id 'duplicate'"):
                load_materials(root)

    def test_list_materials_has_expected_entries(self) -> None:
        materials = {item["id"]: item for item in list_materials()}
        material_ids = set(materials)
        self.assertIn("mild_steel", material_ids)
        self.assertIn("aluminum_6061_t6", material_ids)
        self.assertIn("rubber_generic", material_ids)
        self.assertIn("mild_steel_mat24_demo", material_ids)
        self.assertEqual("builtin", materials["mild_steel"]["library_section"])
        self.assertEqual("phase18", materials["two_storey_rc_frame_mid5_concrete_kc"]["library_section"])

    def test_get_material_returns_source_and_version(self) -> None:
        material = get_material("mild_steel")
        self.assertEqual(material["unit_system"], "SI_m_s_kg_N_Pa")
        self.assertTrue(material["source"])
        self.assertTrue(material["version"])

    def test_resolve_material_rejects_unknown_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown material"):
            resolve_material({"name": "not_in_library"})

    def test_resolve_material_requires_literal_true_confirmation(self) -> None:
        base = {
            "name": "custom_elastic",
            "type": "elastic",
            "density_kg_per_m3": 7800,
            "youngs_pa": 200000000000,
            "poisson": 0.3,
            "source": "unit test",
        }
        for value in ["false", "true", 1]:
            with self.subTest(value=value):
                raw = dict(base)
                raw["confirmed_by_user"] = value
                with self.assertRaisesRegex(ValueError, "confirmed_by_user=true"):
                    resolve_material(raw)

        accepted = dict(base)
        accepted["confirmed_by_user"] = True
        self.assertEqual(resolve_material(accepted)["source_type"], "user_confirmed_custom")

    def test_resolve_mat24_library_material_preserves_plasticity_fields(self) -> None:
        material = resolve_material({"name": "mild_steel_mat24_demo"})
        self.assertEqual("piecewise_linear_plasticity", material["type"])
        self.assertEqual("demo", material["validation_status"])
        self.assertGreater(material["yield_strength_pa"], 0)
        self.assertGreater(material["tangent_modulus_pa"], 0)

    def test_mat24_rejects_nonpositive_plasticity_values(self) -> None:
        material = {
            "name": "custom_mat24",
            "type": "piecewise_linear_plasticity",
            "density_kg_per_m3": 7850,
            "youngs_pa": 210e9,
            "poisson": 0.3,
            "yield_strength_pa": 0,
            "tangent_modulus_pa": 1e9,
            "source": "unit test",
            "confirmed_by_user": True,
        }
        with self.assertRaisesRegex(ValueError, "yield_strength_pa"):
            resolve_material(material)

    def test_mat24_emits_required_r12_cards_three_and_four(self) -> None:
        raw = default_model_spec("mat24_card_test", "solid_cube")
        raw["material"] = {"name": "mild_steel_mat24_demo"}
        lines = material_lines(parse_model_spec(raw))

        self.assertIn("$#   eps1      eps2      eps3      eps4      eps5      eps6      eps7      eps8", lines)
        self.assertIn("$#    es1       es2       es3       es4       es5       es6       es7       es8", lines)
        self.assertEqual(2, lines.count("0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0"))


if __name__ == "__main__":
    unittest.main()
