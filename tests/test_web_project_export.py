from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lsprepost_mcp.web.app import attach_user_export
from lsprepost_mcp.web.project_export import export_project_copy


class WebProjectExportTests(unittest.TestCase):
    def test_attach_user_export_can_be_disabled_for_isolated_browser_patrols(self) -> None:
        result = {"project_dir": "unused"}
        with (
            patch.dict("os.environ", {"LSPP_WEB_DISABLE_USER_EXPORT": "1"}),
            patch("lsprepost_mcp.web.app.configured_export_dir") as configured,
        ):
            self.assertIs(attach_user_export(result), result)
        configured.assert_not_called()

    def test_export_project_copy_copies_core_project_files_to_user_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "workspace" / "projects" / "demo_project"
            project.mkdir(parents=True)
            (project / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")
            (project / "model.json").write_text('{"project":"demo"}\n', encoding="utf-8")
            (project / "checks.json").write_text('{"ok":true}\n', encoding="utf-8")
            (project / "ignored.tmp").write_text("ignore", encoding="utf-8")

            export_dir = root / "user_exports"
            result = export_project_copy(project, export_dir)

            copied_root = export_dir / "demo_project"
            self.assertEqual(result["project_export_dir"], str(copied_root))
            self.assertTrue((copied_root / "model.k").is_file())
            self.assertTrue((copied_root / "model.json").is_file())
            self.assertTrue((copied_root / "checks.json").is_file())
            self.assertFalse((copied_root / "ignored.tmp").exists())
            manifest = json.loads((copied_root / "export_manifest.json").read_text(encoding="utf-8"))
            self.assertNotIn("source_project_dir", manifest)
            self.assertEqual(manifest["source_project_name"], "demo_project")
            self.assertEqual(manifest["files"], ["model.k", "model.json", "checks.json"])

    def test_export_copy_failure_preserves_previous_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "workspace" / "projects" / "demo_project"
            project.mkdir(parents=True)
            for name in ("model.k", "model.json", "checks.json"):
                (project / name).write_text(f"new {name}\n", encoding="utf-8")
            export_dir = root / "exports"
            previous = export_dir / "demo_project"
            previous.mkdir(parents=True)
            (previous / "model.k").write_text("previous export\n", encoding="utf-8")
            real_copy = shutil.copy2

            def flaky_copy(src, dst, *args, **kwargs):
                if Path(src).name == "model.json":
                    raise OSError("simulated copy failure")
                return real_copy(src, dst, *args, **kwargs)

            with patch("lsprepost_mcp.web.project_export.shutil.copy2", side_effect=flaky_copy):
                with self.assertRaises(OSError):
                    export_project_copy(project, export_dir)

            self.assertEqual((previous / "model.k").read_text(encoding="utf-8"), "previous export\n")
            self.assertEqual([], list(export_dir.glob(".demo_project.tmp_*")))

    def test_export_rejects_destination_inside_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "demo_project"
            project.mkdir()
            for name in ("model.k", "model.json", "checks.json"):
                (project / name).write_text(name, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "outside the project"):
                export_project_copy(project, project / "exports")


if __name__ == "__main__":
    unittest.main()
