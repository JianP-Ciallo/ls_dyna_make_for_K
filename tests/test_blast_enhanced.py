from __future__ import annotations

import unittest

from lsprepost_mcp.dyna_keyword import build_keyword
from lsprepost_mcp.physics_actions import compile_physics_actions
from lsprepost_mcp.schema import default_model_spec, parse_model_spec
from lsprepost_mcp.tool_generation import tool_assemble_components


class BlastEnhancedTests(unittest.TestCase):
    def blast_action(self) -> dict:
        return {
            "id": "blast_1",
            "type": "blast_enhanced",
            "charge_type": "tnt",
            "equivalent_mass_kg": 0.1,
            "position_m": [0.0, 0.0, 0.5],
            "mode": "free_air_burst",
            "targets": ["plate.top_surface"],
            "output_dt_s": 0.0001,
        }

    def test_blast_action_compiles_to_typed_load(self) -> None:
        raw = default_model_spec("blast_compile", "assembly_scene")
        compiled = compile_physics_actions(raw["components"], [self.blast_action()])
        load = compiled["loads"][0]
        self.assertEqual("blast_enhanced", load["type"])
        self.assertEqual(2, load["unit"])
        self.assertEqual(2, load["blast_type"])
        self.assertEqual([{"component": "plate", "surface": "top_surface"}], load["targets"])

    def test_blast_keyword_emits_r12_cards_and_target_segments(self) -> None:
        raw = default_model_spec("blast_keyword", "assembly_scene")
        compiled = compile_physics_actions(raw["components"], [self.blast_action()])
        raw["components"] = compiled["components"]
        raw["contacts"] = []
        raw["loads"] = compiled["loads"]
        raw["analysis_control"] = {"termination": {"end_time_s": 0.02}}
        raw["database"] = {"format": 0, "ibinary": 1, "d3plot_dt_s": 0.0001}
        keyword, metadata = build_keyword(parse_model_spec(raw))

        self.assertIn("*LOAD_BLAST_ENHANCED", keyword)
        self.assertIn("*LOAD_BLAST_SEGMENT_SET", keyword)
        self.assertIn("*DATABASE_BINARY_BLSTFOR", keyword)
        self.assertIn("*DATABASE_GLSTAT", keyword)
        self.assertIn("*DATABASE_MATSUM", keyword)
        self.assertIn("*DATABASE_SPCFORC", keyword)
        self.assertIn("$#   iform   ibinary\n0,1", keyword)
        self.assertEqual(1, metadata["blast_count"])
        self.assertGreater(metadata["blast_segment_count"], 0)
        self.assertEqual([0.0, 0.0, 0.5], metadata["blast_sources"][0]["position_m"])

    def test_blast_rejects_solid_target_surface(self) -> None:
        raw = default_model_spec("blast_bad_target", "assembly_scene")
        action = self.blast_action()
        action["targets"] = ["rod.outer_surface"]
        with self.assertRaisesRegex(ValueError, "shell component"):
            compile_physics_actions(raw["components"], [action])

    def test_assemble_components_accepts_blast_action(self) -> None:
        raw = default_model_spec("blast_tool", "assembly_scene")
        result = tool_assemble_components(
            {
                "project_name": "blast_tool",
                "components": raw["components"],
                "contacts": [],
                "actions": [self.blast_action()],
                "analysis_control": {"termination": {"end_time_s": 0.02}},
                "database": {"d3plot_dt_s": 0.0001},
                "dry_run": True,
            }
        )
        self.assertTrue(result["ok"])
        self.assertEqual(1, result["metadata"]["blast_count"])


if __name__ == "__main__":
    unittest.main()
