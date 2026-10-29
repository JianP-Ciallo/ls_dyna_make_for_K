from __future__ import annotations

import math
import unittest

from lsprepost_mcp.server import handle_message, reject_json_constant, validate_json_schema


class JsonRpcTests(unittest.TestCase):
    def test_initialize_and_tools_list(self) -> None:
        init_response = handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(init_response["result"]["serverInfo"]["name"], "lsprepost-mcp")

        tools_response = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tool_names = {item["name"] for item in tools_response["result"]["tools"]}
        self.assertIn("generate_model", tool_names)
        self.assertIn("generate_scene_from_prompt", tool_names)
        self.assertIn("open_in_lsprepost", tool_names)
        self.assertIn("export_preview_image", tool_names)
        self.assertIn("export_preview_images", tool_names)
        self.assertIn("export_preview_gif", tool_names)
        self.assertIn("validate_lsprepost_import", tool_names)
        self.assertIn("run_cfile", tool_names)
        self.assertIn("list_materials", tool_names)
        self.assertIn("get_material", tool_names)
        self.assertIn("list_model_resources", tool_names)
        self.assertIn("get_model_resource", tool_names)
        self.assertIn("validate_model_resource", tool_names)
        self.assertIn("export_model_resource", tool_names)
        self.assertIn("validate_material_resource", tool_names)
        self.assertIn("list_structural_resources", tool_names)
        self.assertIn("get_structural_resource", tool_names)
        self.assertIn("validate_phase18_resource_review", tool_names)

    def test_tools_list_timeout_schema_matches_tool_semantics(self) -> None:
        response = handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        tools = {item["name"]: item for item in response["result"]["tools"]}
        open_timeout = tools["open_in_lsprepost"]["inputSchema"]["properties"]["timeout_s"]
        preview_timeout = tools["export_preview_image"]["inputSchema"]["properties"]["timeout_s"]
        gif_schema = tools["export_preview_gif"]["inputSchema"]
        scene_schema = tools["generate_scene_from_prompt"]["inputSchema"]
        run_timeout = tools["run_cfile"]["inputSchema"]["properties"]["timeout_s"]
        batch_timeout = tools["export_preview_images"]["inputSchema"]["properties"]["timeout_s"]
        import_timeout = tools["validate_lsprepost_import"]["inputSchema"]["properties"]["timeout_s"]
        self.assertEqual(open_timeout["default"], 0)
        self.assertIn("returns after launch", open_timeout["description"])
        self.assertNotIn("successful completion", open_timeout["description"])
        self.assertEqual(preview_timeout["default"], 45)
        self.assertIn("preview export cfile", preview_timeout["description"])
        self.assertEqual(gif_schema["properties"]["views"]["default"], ["iso", "top", "front"])
        self.assertEqual(gif_schema["properties"]["output_filename"]["default"], "preview_summary.gif")
        self.assertEqual(gif_schema["properties"]["duration_ms"]["default"], 900)
        self.assertFalse(scene_schema["properties"]["export_preview_gif"]["default"])
        self.assertFalse(scene_schema["properties"]["dry_run"]["default"])
        self.assertIn("scene_id", scene_schema["properties"])
        self.assertIn("rebar_drop_on_helmet", scene_schema["properties"]["scene_id"]["enum"])
        self.assertEqual(run_timeout["default"], 45)
        self.assertIn("greater than 0", run_timeout["description"])
        self.assertIn("successful completion", run_timeout["description"])
        self.assertEqual(batch_timeout["default"], 45)
        self.assertEqual(import_timeout["default"], 45)

    def test_batch_message(self) -> None:
        response = handle_message(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            ]
        )
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0]["result"], {})

    def test_get_material_tool(self) -> None:
        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_material", "arguments": {"material_id": "mild_steel"}},
            }
        )
        text = response["result"]["content"][0]["text"]
        self.assertIn("mild_steel", text)
        self.assertIn("SI_m_s_kg_N_Pa", text)

    def test_get_component_model_resource_tool(self) -> None:
        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_model_resource", "arguments": {"resource_id": "2k_rc_column_reference"}},
            }
        )
        text = response["result"]["content"][0]["text"]
        self.assertIn("2k_rc_column_reference", text)
        self.assertIn("SI_m_s_kg_N_Pa", text)
        self.assertNotIn("_manifest_path", text)
        self.assertNotIn("_resource_dir", text)

    def test_phase18_reviewed_resource_tools_return_verified_results(self) -> None:
        calls = (
            ("validate_material_resource", {"material_id": "2k_mid5_concrete_kc"}, '"effective_validation_status": "syntax_unit_reviewed"'),
            ("list_structural_resources", {}, '"id": "two_storey_rc_frame_sections"'),
            ("get_structural_resource", {"resource_id": "2k_sections_used"}, '"resource_type": "sections"'),
            ("validate_phase18_resource_review", {}, '"resource_count": 11'),
        )
        for tool_name, arguments, expected in calls:
            with self.subTest(tool_name=tool_name):
                response = handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": tool_name, "arguments": arguments},
                    }
                )
                self.assertNotIn("error", response)
                self.assertIn(expected, response["result"]["content"][0]["text"])

    def test_tools_call_rejects_unknown_top_level_arguments(self) -> None:
        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "open_in_lsprepost",
                    "arguments": {"project_name": "missing_project", "allow_multiple": True},
                },
            }
        )
        self.assertIn("unsupported argument", response["error"]["message"])

    def test_tools_call_rejects_wrong_boolean_type(self) -> None:
        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "import_keyword",
                    "arguments": {
                        "keyword_path": "external.k",
                        "allow_external": "false",
                    },
                },
            }
        )
        self.assertIn("allow_external must be boolean", response["error"]["message"])

    def test_tools_call_rejects_non_object_arguments(self) -> None:
        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "server_info", "arguments": []},
            }
        )
        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("arguments must be an object", response["error"]["message"])

    def test_tools_call_rejects_non_string_name(self) -> None:
        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": ["server_info"], "arguments": {}},
            }
        )
        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("name must be a non-empty string", response["error"]["message"])

    def test_tools_call_rejects_wrong_enum_value(self) -> None:
        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "create_plate_demo",
                    "arguments": {
                        "project_name": "unit_bad_enum",
                        "if_exists": "replace",
                    },
                },
            }
        )
        self.assertIn("if_exists must be one of", response["error"]["message"])

    def test_tools_call_rejects_nested_unknown_spec_field(self) -> None:
        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "generate_model",
                    "arguments": {
                        "spec": {
                            "project_name": "unit_nested_unknown",
                            "model_type": "shell_plate",
                            "unexpected": True,
                        }
                    },
                },
            }
        )
        self.assertIn("unsupported field", response["error"]["message"])

    def test_tools_call_rejects_non_finite_number(self) -> None:
        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "open_in_lsprepost",
                    "arguments": {
                        "project_name": "unit_nonfinite",
                        "timeout_s": math.nan,
                    },
                },
            }
        )
        self.assertIn("timeout_s must be number", response["error"]["message"])

    def test_params_must_be_object(self) -> None:
        response = handle_message({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": []})
        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("params must be an object", response["error"]["message"])

    def test_json_schema_rejects_infinity(self) -> None:
        with self.assertRaisesRegex(ValueError, "field must be number"):
            validate_json_schema(math.inf, {"type": "number"}, "field")

    def test_json_constant_rejector_rejects_nan(self) -> None:
        with self.assertRaisesRegex(ValueError, "NaN"):
            reject_json_constant("NaN")


if __name__ == "__main__":
    unittest.main()
