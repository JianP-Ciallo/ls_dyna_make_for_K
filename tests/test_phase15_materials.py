from __future__ import annotations

import unittest

from lsprepost_mcp.phase15_materials import (
    default_phase15_materials,
    render_phase15_material_cards,
    validate_phase15_materials,
)


class Phase15MaterialTests(unittest.TestCase):
    def test_default_material_bundle_is_complete_and_controlled(self) -> None:
        bundle = validate_phase15_materials(default_phase15_materials())

        self.assertEqual(set(bundle), {"air", "tnt", "concrete", "steel_hoop", "erosion"})
        self.assertEqual(bundle["concrete"]["parameter_mode"], "automatic")
        self.assertEqual(bundle["concrete"]["fpc_pa"], 133.5e6)
        self.assertEqual(bundle["concrete"]["nout"], 2)
        self.assertEqual(bundle["tnt"]["preset_id"], "tnt_jwl_phase15_reference")
        self.assertEqual(bundle["erosion"]["mode"], "off")

    def test_material_ranges_reject_uncontrolled_values(self) -> None:
        bundle = default_phase15_materials()
        bundle["steel_hoop"]["yield_strength_pa"] = 500.0e6

        with self.assertRaisesRegex(ValueError, "steel_hoop.yield_strength_pa"):
            validate_phase15_materials(bundle)

    def test_kc_damage_output_selector_is_locked(self) -> None:
        bundle = default_phase15_materials()
        bundle["concrete"]["nout"] = 0

        with self.assertRaisesRegex(ValueError, "concrete.nout"):
            validate_phase15_materials(bundle)

    def test_custom_erosion_requires_explicit_confirmation(self) -> None:
        bundle = default_phase15_materials()
        bundle["erosion"] = {"mode": "custom", "maximum_principal_strain": 0.04}

        with self.assertRaisesRegex(ValueError, "confirmed_by_user"):
            validate_phase15_materials(bundle)

    def test_material_renderer_emits_r12_kc_tnt_air_and_steel_cards(self) -> None:
        lines, metadata = render_phase15_material_cards(default_phase15_materials())
        keyword = "\n".join(lines)

        self.assertIn("*MAT_NULL", keyword)
        self.assertIn("*EOS_LINEAR_POLYNOMIAL", keyword)
        self.assertIn("*MAT_HIGH_EXPLOSIVE_BURN", keyword)
        self.assertIn("*EOS_JWL", keyword)
        self.assertIn("*MAT_CONCRETE_DAMAGE_REL3", keyword)
        self.assertIn("-133500000", keyword)
        self.assertIn("39.37", keyword)
        self.assertIn("0.00014504", keyword)
        output_comment_index = lines.index(
            "$# slambda      nout     edrop     rsize       ucf    lcrate    locwid      npts"
        )
        self.assertEqual("2", lines[output_comment_index + 1].split(",")[1])
        self.assertIn("*MAT_PLASTIC_KINEMATIC", keyword)
        steel_index = lines.index("*MAT_PLASTIC_KINEMATIC")
        self.assertEqual("0,0,1,0", lines[steel_index + 4])
        self.assertEqual(2, len([line for line in lines[steel_index + 1 :] if line and not line.startswith("$")]))
        self.assertNotIn("*MAT_ADD_EROSION", keyword)
        self.assertEqual(metadata["erosion"]["mode"], "off")
        self.assertEqual(metadata["kc_output"]["nout"], 2)
        self.assertEqual(
            metadata["kc_output"]["interpretation"],
            "scaled_damage_measure",
        )
        for line in lines:
            if line.startswith("*") or line.startswith("$"):
                continue
            self.assertTrue(all(len(field) <= 10 for field in line.split(",")), line)

    def test_controlled_erosion_emits_only_mxeps_and_is_labeled_numerical(self) -> None:
        bundle = default_phase15_materials()
        bundle["erosion"] = {"mode": "standard_observation"}

        lines, metadata = render_phase15_material_cards(bundle)
        keyword = "\n".join(lines)

        self.assertIn("*MAT_ADD_EROSION", keyword)
        self.assertIn("0,0,0,0.05,0,0,0,0", keyword)
        self.assertEqual(metadata["erosion"]["maximum_principal_strain"], 0.05)
        self.assertEqual(metadata["erosion"]["interpretation"], "numerical_element_deletion_only")

    def test_material_renderer_accepts_valid_custom_ids(self) -> None:
        bundle = default_phase15_materials()
        bundle["erosion"] = {"mode": "standard_observation"}

        lines, metadata = render_phase15_material_cards(
            bundle,
            material_ids={
                "air": 1,
                "tnt": 2,
                "concrete": 90,
                "steel_hoop": 4,
            },
            eos_ids={"air": 1, "tnt": 2},
        )

        concrete_index = lines.index("*MAT_CONCRETE_DAMAGE_REL3")
        self.assertEqual("90", lines[concrete_index + 2].split(",")[0])
        erosion_index = lines.index("*MAT_ADD_EROSION")
        self.assertEqual("90", lines[erosion_index + 2].split(",")[0])
        self.assertEqual(90, metadata["material_ids"]["concrete"])

    def test_material_renderer_rejects_invalid_custom_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique"):
            render_phase15_material_cards(
                default_phase15_materials(),
                material_ids={
                    "air": 1,
                    "tnt": 2,
                    "concrete": 2,
                    "steel_hoop": 4,
                },
            )

        with self.assertRaisesRegex(ValueError, "positive integer"):
            render_phase15_material_cards(
                default_phase15_materials(),
                eos_ids={"air": 1, "tnt": True},
            )


if __name__ == "__main__":
    unittest.main()
