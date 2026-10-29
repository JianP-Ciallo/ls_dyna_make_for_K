from __future__ import annotations

import unittest

from lsprepost_mcp.schema import default_model_spec, parse_model_spec


class Phase10ErrorInputTests(unittest.TestCase):
    def test_rejects_nan_string_geometry_value(self) -> None:
        raw = default_model_spec("unit_bad_nan", "shell_plate")
        raw["geometry"]["length_m"] = "NaN"
        with self.assertRaisesRegex(ValueError, "geometry.length_m"):
            parse_model_spec(raw)

    def test_rejects_unknown_material_without_confirmation(self) -> None:
        raw = default_model_spec("unit_bad_material", "shell_plate")
        raw["material"] = {"name": "not_in_library"}
        with self.assertRaisesRegex(ValueError, "unknown material"):
            parse_model_spec(raw)

    def test_rejects_custom_material_string_confirmation(self) -> None:
        raw = default_model_spec("unit_bad_custom_material", "shell_plate")
        raw["material"] = {
            "type": "elastic",
            "name": "custom_elastic",
            "source": "unit test",
            "confirmed_by_user": "false",
            "density_kg_per_m3": 7850,
            "youngs_pa": 210e9,
            "poisson": 0.3,
        }
        with self.assertRaisesRegex(ValueError, "confirmed_by_user"):
            parse_model_spec(raw)

    def test_rejects_unknown_contact_type(self) -> None:
        raw = default_model_spec("unit_bad_contact", "assembly_scene")
        raw["contacts"] = [{"type": "automatic_magic_contact", "slave": "rod", "master": "plate"}]
        with self.assertRaisesRegex(ValueError, "contacts\\[\\]\\.type"):
            parse_model_spec(raw)


if __name__ == "__main__":
    unittest.main()
