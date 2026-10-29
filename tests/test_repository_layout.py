from __future__ import annotations

import unittest
from pathlib import Path

from lsprepost_mcp.cfile import CFILE_TEMPLATE_DIR
from lsprepost_mcp.config import LOCAL_WEB_CONFIG_PATH, MATERIALS_DIR, ROOT


class RepositoryLayoutTests(unittest.TestCase):
    def test_repository_uses_grouped_resource_and_runtime_directories(self) -> None:
        expected_directories = (
            ROOT / "resources" / "materials",
            ROOT / "resources" / "templates",
            ROOT / "docs" / "internal",
            ROOT / "docs" / "reviews",
            ROOT / "extras" / "special_pages_rod_impact",
            ROOT / "var" / "generated_configs",
            ROOT / "var" / "tmp",
        )
        for directory in expected_directories:
            with self.subTest(directory=directory):
                self.assertTrue(directory.is_dir())

    def test_legacy_top_level_directories_are_removed(self) -> None:
        for name in (
            "materials",
            "templates",
            "internal_docs",
            "special_pages_rod_impact",
            "generated_configs",
            "tmp",
        ):
            with self.subTest(name=name):
                self.assertFalse((ROOT / name).exists())

    def test_configured_paths_follow_the_grouped_layout(self) -> None:
        self.assertEqual(ROOT / "resources" / "materials", MATERIALS_DIR)
        self.assertEqual(
            ROOT / "resources" / "templates" / "cfile",
            CFILE_TEMPLATE_DIR,
        )
        self.assertEqual(
            ROOT / "var" / "generated_configs" / "web_app.local.json",
            LOCAL_WEB_CONFIG_PATH,
        )

    def test_workspace_and_distribution_roots_stay_in_place(self) -> None:
        self.assertTrue((ROOT / "workspace").is_dir())
        self.assertTrue((ROOT / "dist").is_dir())


if __name__ == "__main__":
    unittest.main()
