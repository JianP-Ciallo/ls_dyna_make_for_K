from __future__ import annotations

import unittest

from lsprepost_mcp.scene_prompts import SCENE_TEMPLATE_REGISTRY
from lsprepost_mcp.schema import SUPPORTED_COMPONENT_TEMPLATES, default_model_spec, parse_model_spec
from lsprepost_mcp.tools import tool_list


class Phase12BaselineTests(unittest.TestCase):
    def test_four_controlled_scene_ids_remain_registered(self) -> None:
        self.assertEqual(
            {
                "cube_top_corner_load",
                "plate_pressure",
                "rebar_drop_on_helmet",
                "rod_impact_plate",
            },
            set(SCENE_TEMPLATE_REGISTRY),
        )

    def test_phase11_core_tool_contract_is_preserved(self) -> None:
        self.assertLessEqual(
            {
                "archive_project",
                "assemble_components",
                "create_plate_demo",
                "export_preview_gif",
                "export_preview_image",
                "export_preview_images",
                "generate_model",
                "generate_ale_blast_demo",
                "generate_tunnel_blast_demo",
                "generate_scene_from_prompt",
                "get_material",
                "get_component_template",
                "import_keyword",
                "list_materials",
                "list_component_templates",
                "list_physics_actions",
                "list_projects",
                "model_summary",
                "open_in_lsprepost",
                "read_project",
                "run_cfile",
                "server_info",
                "validate_lsprepost_import",
                "validate_model",
            },
            {item["name"] for item in tool_list()["tools"]},
        )

    def test_phase12_component_boundary_is_explicit(self) -> None:
        self.assertEqual(
            {
                "beam_bar",
                "circular_plate",
                "commercial_supermarket",
                "ellipsoid_shell",
                "parking_lot",
                "parked_vehicle",
                "residential_community",
                "shell_box",
                "shell_plate",
                "shell_tube",
                "solid_block",
                "solid_cylinder",
                "sphere_shell",
                "subway_entrance",
                "traffic_light",
            },
            SUPPORTED_COMPONENT_TEMPLATES,
        )

    def test_assembly_requires_at_least_one_component(self) -> None:
        raw = default_model_spec("phase12_single_component_probe", "assembly_scene")
        raw["components"] = []
        with self.assertRaisesRegex(ValueError, "at least one component"):
            parse_model_spec(raw)


if __name__ == "__main__":
    unittest.main()
