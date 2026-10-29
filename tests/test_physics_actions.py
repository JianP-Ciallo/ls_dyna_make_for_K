from __future__ import annotations

import copy
import unittest

from lsprepost_mcp.physics_actions import compile_physics_actions, physics_action_catalog
from lsprepost_mcp.schema import default_model_spec
from lsprepost_mcp.tool_generation import tool_assemble_components


class PhysicsActionTests(unittest.TestCase):
    def test_catalog_exposes_controlled_action_types(self) -> None:
        names = {item["type"] for item in physics_action_catalog()}
        self.assertEqual(
            {
                "automatic_nodes_to_surface",
                "automatic_surface_to_surface",
                "blast_enhanced",
                "fixed_region",
                "gravity",
                "initial_velocity",
                "nodal_force",
                "pressure",
            },
            names,
        )

    def test_compile_actions_does_not_mutate_input(self) -> None:
        raw = default_model_spec("actions_no_mutation", "assembly_scene")
        components = raw["components"]
        before = copy.deepcopy(components)
        compiled = compile_physics_actions(
            components,
            [
                {"type": "fixed_region", "component": "plate", "region": "four_edges"},
                {
                    "type": "initial_velocity",
                    "component": "rod",
                    "vector_m_per_s": [0.0, 0.0, -10.0],
                },
            ],
        )
        self.assertEqual(before, components)
        self.assertEqual(["x_min", "x_max", "y_min", "y_max"], compiled["components"][1]["fixed_faces"])
        self.assertEqual([0.0, 0.0, -10.0], compiled["components"][0]["initial_velocity_m_per_s"])

    def test_assemble_actions_emit_existing_stable_cards(self) -> None:
        raw = default_model_spec("actions_keyword", "assembly_scene")
        result = tool_assemble_components(
            {
                "project_name": "actions_keyword",
                "components": raw["components"],
                "actions": [
                    {"type": "fixed_region", "component": "plate", "region": "four_edges"},
                    {
                        "type": "initial_velocity",
                        "component": "rod",
                        "vector_m_per_s": [0.0, 0.0, -10.0],
                    },
                    {
                        "type": "automatic_surface_to_surface",
                        "slave": "rod",
                        "master": "plate",
                        "friction": 0.2,
                    },
                    {"type": "gravity", "direction": "z", "acceleration_m_per_s2": -9.81},
                    {"type": "pressure", "face": "z_max", "pressure_pa": -20000.0},
                    {"type": "nodal_force", "edge": "x_min", "dof": "z", "value_n": -1000.0},
                ],
                "dry_run": True,
            }
        )
        spec = result["resolved_spec"]
        self.assertEqual(["x_min", "x_max", "y_min", "y_max"], spec["components"][1]["fixed_faces"])
        self.assertEqual(1, len(spec["contacts"]))
        self.assertEqual(3, len(spec["loads"]))
        self.assertEqual(1, result["metadata"]["contact_count"])
        self.assertEqual(3, result["metadata"]["load_count"])

    def test_unknown_action_field_is_rejected(self) -> None:
        raw = default_model_spec("actions_bad_field", "assembly_scene")
        with self.assertRaisesRegex(ValueError, "unsupported field"):
            compile_physics_actions(
                raw["components"],
                [{"type": "gravity", "direction": "z", "acceleration_m_per_s2": -9.81, "magic": True}],
            )

    def test_action_rejects_unknown_component(self) -> None:
        raw = default_model_spec("actions_bad_component", "assembly_scene")
        with self.assertRaisesRegex(ValueError, "unknown component"):
            compile_physics_actions(
                raw["components"],
                [{"type": "fixed_region", "component": "missing", "region": "rim"}],
            )


if __name__ == "__main__":
    unittest.main()
