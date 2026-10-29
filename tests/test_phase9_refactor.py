import unittest


class Phase9RefactorTests(unittest.TestCase):
    def test_tool_helpers_are_extracted_without_breaking_tools_imports(self):
        import lsprepost_mcp.tool_helpers as helpers
        import lsprepost_mcp.tools as tools

        self.assertIs(tools.bool_arg, helpers.bool_arg)
        self.assertIs(tools.automation_timeout, helpers.automation_timeout)
        self.assertIs(tools.verify_png_artifact, helpers.verify_png_artifact)
        self.assertIs(tools.record_lsprepost_verification, helpers.record_lsprepost_verification)
        self.assertIs(tools.PNG_SIGNATURE, helpers.PNG_SIGNATURE)
        self.assertIs(tools.PREVIEW_DISPLAY_MODES, helpers.PREVIEW_DISPLAY_MODES)

    def test_tool_list_still_exposes_core_phase6_and_phase7_tools(self):
        from lsprepost_mcp.tools import tool_list

        tool_names = {tool["name"] for tool in tool_list()["tools"]}

        self.assertIn("generate_model", tool_names)
        self.assertIn("generate_scene_from_prompt", tool_names)
        self.assertIn("export_preview_image", tool_names)
        self.assertIn("export_preview_gif", tool_names)
        self.assertIn("validate_lsprepost_import", tool_names)

    def test_lsprepost_tools_are_extracted_without_breaking_tools_imports(self):
        import lsprepost_mcp.tool_lsprepost as lsprepost_tools
        import lsprepost_mcp.tools as tools

        self.assertIs(tools.tool_open_in_lsprepost, lsprepost_tools.tool_open_in_lsprepost)
        self.assertIs(tools.tool_export_preview_image, lsprepost_tools.tool_export_preview_image)
        self.assertIs(tools.tool_export_preview_images, lsprepost_tools.tool_export_preview_images)
        self.assertIs(tools.tool_export_preview_gif, lsprepost_tools.tool_export_preview_gif)
        self.assertIs(tools.tool_validate_lsprepost_import, lsprepost_tools.tool_validate_lsprepost_import)
        self.assertIs(tools.tool_run_cfile, lsprepost_tools.tool_run_cfile)

    def test_project_material_and_server_tools_are_extracted_without_breaking_imports(self):
        import lsprepost_mcp.tool_materials as material_tools
        import lsprepost_mcp.tool_project as project_tools
        import lsprepost_mcp.tool_server as server_tools
        import lsprepost_mcp.tools as tools

        self.assertIs(tools.tool_validate_model, project_tools.tool_validate_model)
        self.assertIs(tools.tool_model_summary, project_tools.tool_model_summary)
        self.assertIs(tools.tool_list_projects, project_tools.tool_list_projects)
        self.assertIs(tools.tool_read_project, project_tools.tool_read_project)
        self.assertIs(tools.tool_archive_project, project_tools.tool_archive_project)
        self.assertIs(tools.tool_import_keyword, project_tools.tool_import_keyword)
        self.assertIs(tools.tool_list_materials, material_tools.tool_list_materials)
        self.assertIs(tools.tool_get_material, material_tools.tool_get_material)
        self.assertIs(tools.tool_server_info, server_tools.tool_server_info)

    def test_generation_tools_are_extracted_without_breaking_imports(self):
        import lsprepost_mcp.tool_generation as generation_tools
        import lsprepost_mcp.tools as tools

        self.assertIs(tools.tool_generate_model, generation_tools.tool_generate_model)
        self.assertIs(tools.tool_create_plate_demo, generation_tools.tool_create_plate_demo)
        self.assertIs(tools.tool_generate_scene_from_prompt, generation_tools.tool_generate_scene_from_prompt)


if __name__ == "__main__":
    unittest.main()
