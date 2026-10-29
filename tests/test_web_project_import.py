from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_web_api import request_json, web_test_server

from lsprepost_mcp.paths import project_dir
from lsprepost_mcp.web.http_utils import ApiError
from lsprepost_mcp.web.native_dialogs import NativeDialogUnavailable
from lsprepost_mcp.web.project_import import import_project_package, inspect_project_package


def write_export_package(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")
    (path / "model.json").write_text(json.dumps({"spec": {"project_name": path.name}}), encoding="utf-8")
    (path / "checks.json").write_text(json.dumps({"ok": True, "counts": {"nodes": 0}}), encoding="utf-8")
    (path / "export_manifest.json").write_text(
        json.dumps({"source_project_dir": "unit", "files": ["model.k", "model.json", "checks.json"]}),
        encoding="utf-8",
    )


class WebProjectImportTests(unittest.TestCase):
    def tearDown(self) -> None:
        for name in ["unit_import_package", "unit_import_route", "unit_import_selected", "unit_import_rollback"]:
            path = project_dir(name)
            if path.exists():
                shutil.rmtree(path)

    def test_inspect_project_package_requires_all_export_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "bad_package"
            write_export_package(source)
            (source / "checks.json").unlink()

            with self.assertRaises(ApiError) as raised:
                inspect_project_package(source)

        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.code, "invalid_import_package")
        self.assertIn("checks.json", raised.exception.message)

    def test_import_project_package_reconstructs_optional_export_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "legacy_package"
            write_export_package(source)
            (source / "export_manifest.json").unlink()

            inspected = inspect_project_package(source)
            result = import_project_package(source, "unit_import_package", if_exists="overwrite")

        imported = project_dir("unit_import_package")
        manifest = json.loads((imported / "export_manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(inspected["manifest_present"])
        self.assertEqual(result["copied_files"], ["model.k", "model.json", "checks.json"])
        self.assertEqual(result["generated_files"], ["export_manifest.json"])
        self.assertTrue(result["manifest_reconstructed"])
        self.assertEqual(manifest["provenance"]["kind"], "reconstructed_on_import")
        self.assertFalse(manifest["provenance"]["original_manifest_present"])

    def test_import_project_package_copies_complete_export_package_into_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source_package"
            write_export_package(source)

            result = import_project_package(source, "unit_import_package", if_exists="overwrite")

        imported = project_dir("unit_import_package")
        self.assertEqual(result["project_name"], "unit_import_package")
        self.assertEqual(result["project_dir"], str(imported))
        self.assertEqual(
            result["copied_files"],
            ["model.k", "model.json", "checks.json", "export_manifest.json"],
        )
        self.assertEqual(result["generated_files"], [])
        self.assertFalse(result["manifest_reconstructed"])
        self.assertTrue((imported / "model.k").is_file())
        self.assertTrue((imported / "model.json").is_file())
        self.assertTrue((imported / "checks.json").is_file())
        self.assertTrue((imported / "export_manifest.json").is_file())
        model = json.loads((imported / "model.json").read_text(encoding="utf-8"))
        self.assertEqual(model["spec"]["project_name"], "unit_import_package")
        checks = json.loads((imported / "checks.json").read_text(encoding="utf-8"))
        self.assertFalse(checks["ok"], "import must recompute checks instead of trusting the package")
        self.assertFalse(result["checks_ok"])

    def test_import_overwrite_copy_failure_preserves_existing_project(self) -> None:
        target = project_dir("unit_import_rollback")
        target.mkdir(parents=True)
        (target / "model.k").write_text("original project\n", encoding="utf-8")
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source_package"
            write_export_package(source)
            real_copy = shutil.copy2

            def flaky_copy(src, dst, *args, **kwargs):
                if Path(src).name == "model.json":
                    raise OSError("simulated copy failure")
                return real_copy(src, dst, *args, **kwargs)

            with patch("lsprepost_mcp.web.project_import.shutil.copy2", side_effect=flaky_copy):
                with self.assertRaises(OSError):
                    import_project_package(source, "unit_import_rollback", if_exists="overwrite")

        self.assertEqual((target / "model.k").read_text(encoding="utf-8"), "original project\n")
        temp_dirs = list(target.parent.glob(".unit_import_rollback.tmp_*"))
        self.assertEqual([], temp_dirs)

    def test_inspect_project_package_rejects_oversized_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "large_package"
            write_export_package(source)
            with patch("lsprepost_mcp.web.project_import.MAX_IMPORT_PACKAGE_BYTES", 1):
                with self.assertRaises(ApiError) as raised:
                    inspect_project_package(source)
        self.assertEqual(raised.exception.code, "import_package_too_large")

    def test_inspect_project_package_rejects_nonstandard_json_constants(self) -> None:
        for name in ("model.json", "checks.json", "export_manifest.json"):
            for constant in ("NaN", "Infinity", "-Infinity"):
                with (
                    self.subTest(name=name, constant=constant),
                    tempfile.TemporaryDirectory() as temp_dir,
                ):
                    source = Path(temp_dir) / "nonstandard_json_package"
                    write_export_package(source)
                    (source / name).write_text(
                        f'{{"value": {constant}}}',
                        encoding="utf-8",
                    )

                    with self.assertRaises(ApiError) as raised:
                        inspect_project_package(source)

                    self.assertEqual(raised.exception.status, 400)
                    self.assertEqual(raised.exception.code, "invalid_import_package")
                    self.assertIn(name, raised.exception.message)

    def test_import_package_route_imports_manual_folder_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "route_package"
            write_export_package(source)
            with web_test_server() as address:
                status, payload = request_json(
                    address,
                    "POST",
                    "/api/project/import-package",
                    {
                        "source_dir": str(source),
                        "project_name": "unit_import_route",
                        "if_exists": "overwrite",
                    },
                )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["project_name"], "unit_import_route")
        self.assertTrue(project_dir("unit_import_route").is_dir())

    def test_select_import_package_route_uses_backend_folder_picker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "selected_package"
            write_export_package(source)
            with patch("lsprepost_mcp.web.project_import.choose_import_package_dir", return_value=source):
                with web_test_server() as address:
                    status, payload = request_json(
                        address,
                        "POST",
                        "/api/project/select-import-package",
                        {"project_name": "unit_import_selected", "if_exists": "overwrite"},
                    )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["project_name"], "unit_import_selected")
        self.assertTrue(project_dir("unit_import_selected").is_dir())

    def test_select_import_package_route_reports_unavailable_native_dialog(self) -> None:
        with patch(
            "lsprepost_mcp.web.project_import.choose_import_package_dir",
            side_effect=NativeDialogUnavailable("无法打开系统文件选择窗口"),
        ):
            with web_test_server() as address:
                status, payload = request_json(
                    address,
                    "POST",
                    "/api/project/select-import-package",
                    {},
                )

        self.assertEqual(status, 503)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "native_dialog_unavailable")


if __name__ == "__main__":
    unittest.main()
