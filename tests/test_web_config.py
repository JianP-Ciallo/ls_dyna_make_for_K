from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from tests.test_web_api import request_json, web_test_server

from lsprepost_mcp.config import LOCAL_WEB_CONFIG_PATH, ROOT
from lsprepost_mcp.paths import project_dir
from lsprepost_mcp.web.config_api import write_web_config_patch
from lsprepost_mcp.web.native_dialogs import NativeDialogUnavailable


LOCAL_CONFIG = LOCAL_WEB_CONFIG_PATH


class WebConfigRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_lspp_exe = os.environ.pop("LSPP_EXE", None)
        self._old_config_text = LOCAL_CONFIG.read_text(encoding="utf-8") if LOCAL_CONFIG.exists() else None
        LOCAL_CONFIG.unlink(missing_ok=True)

    def tearDown(self) -> None:
        if self._old_lspp_exe is None:
            os.environ.pop("LSPP_EXE", None)
        else:
            os.environ["LSPP_EXE"] = self._old_lspp_exe
        if self._old_config_text is None:
            LOCAL_CONFIG.unlink(missing_ok=True)
        else:
            LOCAL_CONFIG.parent.mkdir(parents=True, exist_ok=True)
            LOCAL_CONFIG.write_text(self._old_config_text, encoding="utf-8")

    def test_config_route_reports_unconfigured_state(self) -> None:
        with web_test_server() as address:
            status, payload = request_json(address, "GET", "/api/config")

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        result = payload["result"]
        self.assertFalse(result["configured"])
        self.assertEqual(result["source"], "default")
        self.assertEqual(result["lspp_exe"], "lsprepost4.12.exe")
        self.assertFalse(result["export_dir_configured"])
        self.assertEqual(result["export_dir"], "")
        self.assertFalse(result["lsrun_configured"])
        self.assertEqual(result["lsrun_exe"], "")
        self.assertFalse(result["lsdyna_configured"])
        self.assertEqual(result["lsdyna_exe"], "")

    def test_concurrent_config_patches_do_not_lose_fields(self) -> None:
        from lsprepost_mcp.web import config_api

        original_load = config_api.load_local_web_config

        def delayed_load():
            data = original_load()
            time.sleep(0.01)
            return data

        updates = [{f"field_{index}": index} for index in range(8)]
        with patch("lsprepost_mcp.web.config_api.load_local_web_config", side_effect=delayed_load):
            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(write_web_config_patch, updates))

        saved = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8"))
        for index in range(8):
            self.assertEqual(saved[f"field_{index}"], index)

    def test_check_lsprepost_route_validates_without_saving(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            exe = Path(temp_dir) / "lsprepost4.12.exe"
            exe.write_text("fake exe", encoding="utf-8")
            with web_test_server() as address:
                status, payload = request_json(
                    address,
                    "POST",
                    "/api/config/check-lsprepost",
                    {"lspp_exe": str(exe)},
                )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["result"]["doctor"]["ok"])
        self.assertFalse(LOCAL_CONFIG.exists())

    def test_save_lsprepost_route_persists_path_and_updates_process_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            exe = Path(temp_dir) / "lsprepost4.12.exe"
            exe.write_text("fake exe", encoding="utf-8")
            with web_test_server() as address:
                status, payload = request_json(
                    address,
                    "POST",
                    "/api/config/lsprepost",
                    {"lspp_exe": str(exe)},
                )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(os.environ.get("LSPP_EXE"), str(exe))
        saved = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(saved["lspp_exe"], str(exe))
        self.assertTrue(payload["result"]["configured"])
        self.assertEqual(payload["result"]["source"], "local_config")

    def test_save_lsprepost_route_rejects_directory_that_looks_like_exe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_dir = Path(temp_dir) / "lsprepost4.12.exe"
            fake_dir.mkdir()
            with web_test_server() as address:
                status, payload = request_json(
                    address,
                    "POST",
                    "/api/config/lsprepost",
                    {"lspp_exe": str(fake_dir)},
                )

        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_lsprepost_path")

    def test_select_lsprepost_route_uses_backend_file_picker_and_saves_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            exe = Path(temp_dir) / "lsprepost4.12.exe"
            exe.write_text("fake exe", encoding="utf-8")
            with patch("lsprepost_mcp.web.config_api.choose_lsprepost_exe", return_value=exe):
                with web_test_server() as address:
                    status, payload = request_json(address, "POST", "/api/config/select-lsprepost", {})

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["result"]["configured"])
        self.assertEqual(os.environ.get("LSPP_EXE"), str(exe))

    def test_select_lsprepost_route_reports_cancelled_selection(self) -> None:
        with patch("lsprepost_mcp.web.config_api.choose_lsprepost_exe", return_value=None):
            with web_test_server() as address:
                status, payload = request_json(address, "POST", "/api/config/select-lsprepost", {})

        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "selection_cancelled")

    def test_select_lsprepost_route_distinguishes_unavailable_native_dialog(self) -> None:
        with patch(
            "lsprepost_mcp.web.config_api.choose_lsprepost_exe",
            side_effect=NativeDialogUnavailable("无法打开系统文件选择窗口"),
        ):
            with web_test_server() as address:
                status, payload = request_json(address, "POST", "/api/config/select-lsprepost", {})

        self.assertEqual(status, 503)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "native_dialog_unavailable")

    def test_save_export_dir_route_persists_path_without_removing_lsprepost_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            exe = Path(temp_dir) / "lsprepost4.12.exe"
            exe.write_text("fake exe", encoding="utf-8")
            export_dir = Path(temp_dir) / "exports"
            export_dir.mkdir()

            with web_test_server() as address:
                first_status, _first_payload = request_json(
                    address,
                    "POST",
                    "/api/config/lsprepost",
                    {"lspp_exe": str(exe)},
                )
                status, payload = request_json(
                    address,
                    "POST",
                    "/api/config/export-dir",
                    {"export_dir": str(export_dir)},
                )

        self.assertEqual(first_status, 200)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        result = payload["result"]
        self.assertTrue(result["export_dir_configured"])
        self.assertEqual(result["export_dir"], str(export_dir))
        saved = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(saved["lspp_exe"], str(exe))
        self.assertEqual(saved["export_dir"], str(export_dir))

    def test_save_export_dir_route_rejects_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "not_a_dir.txt"
            file_path.write_text("not a folder", encoding="utf-8")
            with web_test_server() as address:
                status, payload = request_json(
                    address,
                    "POST",
                    "/api/config/export-dir",
                    {"export_dir": str(file_path)},
                )

        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_export_dir")

    def test_select_export_dir_route_uses_backend_folder_picker_and_saves_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            export_dir = Path(temp_dir)
            with patch("lsprepost_mcp.web.config_api.choose_export_dir", return_value=export_dir):
                with web_test_server() as address:
                    status, payload = request_json(address, "POST", "/api/config/select-export-dir", {})

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["result"]["export_dir_configured"])
        self.assertEqual(payload["result"]["export_dir"], str(export_dir))

    def test_check_lsrun_route_validates_without_saving(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            exe = Path(temp_dir) / "lsrun.exe"
            exe.write_text("fake exe", encoding="utf-8")
            with web_test_server() as address:
                status, payload = request_json(
                    address,
                    "POST",
                    "/api/config/check-lsrun",
                    {"lsrun_exe": str(exe)},
                )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["result"]["doctor"]["ok"])
        self.assertFalse(LOCAL_CONFIG.exists())

    def test_save_lsrun_route_persists_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            exe = Path(temp_dir) / "lsrun.exe"
            exe.write_text("fake exe", encoding="utf-8")
            with web_test_server() as address:
                status, payload = request_json(
                    address,
                    "POST",
                    "/api/config/lsrun",
                    {"lsrun_exe": str(exe)},
                )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        saved = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(saved["lsrun_exe"], str(exe))
        self.assertTrue(payload["result"]["lsrun_configured"])
        self.assertEqual(payload["result"]["lsrun_exe"], str(exe))

    def test_save_lsrun_route_rejects_directory_that_looks_like_exe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_dir = Path(temp_dir) / "lsrun.exe"
            fake_dir.mkdir()
            with web_test_server() as address:
                status, payload = request_json(
                    address,
                    "POST",
                    "/api/config/lsrun",
                    {"lsrun_exe": str(fake_dir)},
                )

        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_lsrun_path")

    def test_select_lsrun_route_uses_backend_file_picker_and_saves_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            exe = Path(temp_dir) / "lsrun.exe"
            exe.write_text("fake exe", encoding="utf-8")
            with patch("lsprepost_mcp.web.config_api.choose_lsrun_exe", return_value=exe):
                with web_test_server() as address:
                    status, payload = request_json(address, "POST", "/api/config/select-lsrun", {})

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["result"]["lsrun_configured"])
        saved = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(saved["lsrun_exe"], str(exe))

    def test_save_lsdyna_route_persists_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            exe = Path(temp_dir) / "lsdyna.exe"
            exe.write_text("fake exe", encoding="utf-8")
            with web_test_server() as address:
                status, payload = request_json(
                    address,
                    "POST",
                    "/api/config/lsdyna",
                    {"lsdyna_exe": str(exe)},
                )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        saved = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(saved["lsdyna_exe"], str(exe))
        self.assertTrue(payload["result"]["lsdyna_configured"])
        self.assertEqual(payload["result"]["lsdyna_exe"], str(exe))

    def test_select_lsdyna_route_uses_backend_file_picker_and_saves_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            exe = Path(temp_dir) / "lsdyna.exe"
            exe.write_text("fake exe", encoding="utf-8")
            with patch("lsprepost_mcp.web.config_api.choose_lsdyna_exe", return_value=exe):
                with web_test_server() as address:
                    status, payload = request_json(address, "POST", "/api/config/select-lsdyna", {})

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["result"]["lsdyna_configured"])
        saved = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(saved["lsdyna_exe"], str(exe))

    def test_open_lsrun_route_prepares_and_launches_immutable_snapshot(self) -> None:
        project = project_dir("unit_web_lsrun_handoff")
        model = project / "model.k"
        snapshot = project / "solver_runs" / "run_unit" / "model.k"
        project.mkdir(parents=True, exist_ok=True)
        model.write_text("*KEYWORD\n*END\n", encoding="utf-8")
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                lsrun = Path(temp_dir) / "lsrun.exe"
                lsrun.write_text("fake exe", encoding="utf-8")
                with web_test_server() as address:
                    save_status, _save_payload = request_json(
                        address,
                        "POST",
                        "/api/config/lsrun",
                        {"lsrun_exe": str(lsrun)},
                    )
                    with (
                        patch(
                            "lsprepost_mcp.web.solve_api.validate_project_files",
                            return_value={
                                "ok": True,
                                "readiness": {"ok_for_solver_draft": True},
                            },
                        ),
                        patch(
                            "lsprepost_mcp.web.solve_api.prepare_lsrun_handoff",
                            return_value={
                                "run_id": "run_unit",
                                "run_dir": str(snapshot.parent),
                                "input": str(snapshot),
                            },
                        ) as prepare,
                        patch(
                            "lsprepost_mcp.web.solve_api.launch_lsrun_handoff"
                        ) as launcher,
                    ):
                        launcher.return_value = {
                            "lsrun_pid": 123,
                            "status": "handoff_opened",
                            "lsrun_exe": str(lsrun),
                            "input": str(snapshot),
                            "run_dir": str(snapshot.parent),
                        }
                        status, payload = request_json(
                            address,
                            "POST",
                            "/api/solve/open-lsrun",
                            {"project_name": "unit_web_lsrun_handoff"},
                        )
        finally:
            if project.exists():
                for child in sorted(project.rglob("*"), reverse=True):
                    if child.is_file():
                        child.unlink()
                    elif child.is_dir():
                        child.rmdir()
                project.rmdir()

        self.assertEqual(save_status, 200)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        prepare.assert_called_once()
        launcher.assert_called_once()
        self.assertEqual(payload["result"]["input"], str(snapshot))
        self.assertEqual(payload["result"]["status"], "handoff_opened")

    def test_recover_lsrun_route_dispatches_run_identity(self) -> None:
        project = project_dir("unit_web_lsrun_recover")
        project.mkdir(parents=True, exist_ok=True)
        expected = {
            "ok": True,
            "status": "completed",
            "run_id": "run_20260726T000000000000Z_12345678",
        }
        try:
            with patch(
                "lsprepost_mcp.web.solve_api.recover_lsrun_result",
                return_value=expected,
            ) as recover:
                with web_test_server() as address:
                    status, payload = request_json(
                        address,
                        "POST",
                        "/api/solve/recover-lsrun",
                        {
                            "project_name": "unit_web_lsrun_recover",
                            "run_id": expected["run_id"],
                        },
                    )
        finally:
            if project.exists():
                project.rmdir()

        self.assertEqual(status, 200)
        self.assertEqual(expected, payload["result"])
        recover.assert_called_once_with(project, expected["run_id"])

    def test_open_result_lsprepost_route_dispatches_qualified_result_tool(self) -> None:
        expected = {
            "ok": True,
            "project_name": "unit_web_result",
            "run_id": "run_unit",
            "d3plot_path": "solver_runs/run_unit/d3plot",
        }
        with patch(
            "lsprepost_mcp.web.app.tool_open_result_lsprepost",
            return_value=expected,
        ) as open_result:
            with web_test_server() as address:
                status, payload = request_json(
                    address,
                    "POST",
                    "/api/project/open-result-lsprepost",
                    {"project_name": "unit_web_result"},
                )

        self.assertEqual(status, 200)
        self.assertEqual(expected, payload["result"])
        open_result.assert_called_once_with({"project_name": "unit_web_result"})

    def test_run_lsdyna_route_requires_and_forwards_explicit_confirmation(self) -> None:
        expected = {
            "ok": True,
            "operation": "run_lsdyna",
            "project_name": "unit_web_solver",
            "status": "completed",
        }
        with patch("lsprepost_mcp.web.app.run_lsdyna_payload", return_value=expected) as runner:
            with web_test_server() as address:
                status, payload = request_json(
                    address,
                    "POST",
                    "/api/solve/run-lsdyna",
                    {
                        "project_name": "unit_web_solver",
                        "confirmation_project_name": "unit_web_solver",
                        "ncpu": 4,
                        "memory": "20m",
                        "timeout_s": 600,
                    },
                )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["status"], "completed")
        runner.assert_called_once_with(
            {
                "project_name": "unit_web_solver",
                "confirmation_project_name": "unit_web_solver",
                "ncpu": 4,
                "memory": "20m",
                "timeout_s": 600,
            }
        )

    def test_lsdyna_status_route_returns_latest_record(self) -> None:
        expected = {
            "ok": True,
            "operation": "lsdyna_status",
            "project_name": "unit_web_solver",
            "status": "not_started",
        }
        with patch("lsprepost_mcp.web.app.latest_lsdyna_payload", return_value=expected) as status_reader:
            with web_test_server() as address:
                status, payload = request_json(
                    address,
                    "GET",
                    "/api/solve/status?project_name=unit_web_solver",
                )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["status"], "not_started")
        status_reader.assert_called_once_with("unit_web_solver")


if __name__ == "__main__":
    unittest.main()
