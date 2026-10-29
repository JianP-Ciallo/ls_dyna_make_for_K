import math
import unittest

from lsprepost_mcp.ale import (
    default_ale_air_definition,
    phase14_capability_catalog,
    render_ale_air_cards,
    render_ale_multimaterial_setup,
    render_control_ale,
    validate_ale_air_definition,
)


class Phase14AleFoundationTests(unittest.TestCase):
    def test_default_air_definition_is_valid_si_demo(self) -> None:
        air = validate_ale_air_definition(default_ale_air_definition())
        self.assertEqual(air["unit_system"], "SI_m_s_kg_N_Pa")
        self.assertAlmostEqual(air["initial_pressure_pa"], 101325.0)

    def test_air_cards_include_null_material_and_eos(self) -> None:
        lines = render_ale_air_cards(material_id=11, eos_id=21)
        text = "\n".join(lines)
        self.assertIn("*MAT_NULL", text)
        self.assertIn("11,1.225", text)
        self.assertIn("*EOS_LINEAR_POLYNOMIAL", text)
        self.assertIn("21,0,0,0,0,0.4,0.4,0", text)
        self.assertNotIn("*MAT_HIGH_EXPLOSIVE_BURN", text)
        self.assertNotIn("*EOS_JWL", text)

    def test_air_definition_rejects_nonfinite_and_unknown_values(self) -> None:
        raw = default_ale_air_definition()
        raw["density_kg_per_m3"] = math.nan
        with self.assertRaisesRegex(ValueError, "finite"):
            validate_ale_air_definition(raw)

        raw = default_ale_air_definition()
        raw["unreviewed"] = 1
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            validate_ale_air_definition(raw)

        with self.assertRaisesRegex(ValueError, "type"):
            render_ale_air_cards({}, material_id=1, eos_id=1)

    def test_multimaterial_setup_requires_two_unique_groups(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least two"):
            render_ale_multimaterial_setup(section_id=1, material_part_ids=[10])
        with self.assertRaisesRegex(ValueError, "unique"):
            render_ale_multimaterial_setup(section_id=1, material_part_ids=[10, 10])

        text = "\n".join(
            render_ale_multimaterial_setup(section_id=7, material_part_ids=[10, 20])
        )
        self.assertIn("7,11", text)
        self.assertIn("*ALE_MULTI-MATERIAL_GROUP", text)
        self.assertIn("10,1", text)
        self.assertIn("20,1", text)

    def test_control_ale_is_restricted_to_reviewed_preset(self) -> None:
        self.assertEqual(
            render_control_ale(),
            [
                "*CONTROL_ALE",
                "$#     dct      nadv      meth      afac      bfac      cfac      dfac      efac",
                "-1,1,2,-1.0,0.0,0.0,0.0,0.0",
                "$#   start       end     aafac     vfact    vlimit       ebc      pref   nsidebc",
                "0.0,1.0e20,1.0,1.0e-6,0,0,101325.0,0",
            ],
        )
        with self.assertRaisesRegex(ValueError, "finite"):
            render_control_ale({})
        with self.assertRaisesRegex(ValueError, "restricted"):
            render_control_ale({"dct": -1, "nadv": 2, "meth": 2, "afac": -1.0})

    def test_catalog_keeps_explosive_and_solver_gated(self) -> None:
        catalog = {item["capability"]: item["status"] for item in phase14_capability_catalog()}
        self.assertEqual(
            catalog["explosive_material_and_jwl"],
            "implemented_controlled_reference",
        )
        self.assertEqual(catalog["ale_lagrange_coupling"], "implemented_controlled_reference")
        self.assertEqual(catalog["mesh_sensitivity_plan"], "implemented_not_solved")
        self.assertEqual(catalog["lsdyna_solve"], "explicit_user_approval_required")


if __name__ == "__main__":
    unittest.main()
