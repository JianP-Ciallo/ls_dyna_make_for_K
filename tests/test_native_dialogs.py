from __future__ import annotations

import subprocess
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from lsprepost_mcp.web import native_dialogs


class NativeDialogTests(unittest.TestCase):
    def test_directory_dialog_uses_isolated_windows_sta_process(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="E:/模型/示例",
            stderr="",
        )
        with patch.object(native_dialogs.subprocess, "run", return_value=completed) as run:
            selected = native_dialogs.choose_directory("选择模型文件夹")

        self.assertEqual(selected, Path("E:/模型/示例"))
        args = run.call_args.args[0]
        options = run.call_args.kwargs
        self.assertIn("-STA", args)
        self.assertIn("BrowseForFolder", args[-1])
        self.assertNotIn("FolderBrowserDialog", args[-1])
        self.assertIn("CenterScreen", args[-1])
        self.assertNotIn("-32000", args[-1])
        self.assertIn("$rootFolder = 0", args[-1])
        self.assertEqual(options["env"]["LSPP_PICKER_MODE"], "directory")
        self.assertEqual(options["env"]["LSPP_PICKER_TITLE"], "选择模型文件夹")
        self.assertEqual(options["encoding"], "utf-8")
        self.assertEqual(options["timeout"], 120)

    def test_file_dialog_passes_filter_to_windows_process(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="E:/tools/lsprepost4.12.exe",
            stderr="",
        )
        with patch.object(native_dialogs.subprocess, "run", return_value=completed) as run:
            selected = native_dialogs.choose_file(
                "选择程序",
                [("LS-PrePost executable", "lsprepost*.exe"), ("Windows executable", "*.exe")],
            )

        self.assertEqual(selected, Path("E:/tools/lsprepost4.12.exe"))
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["LSPP_PICKER_MODE"], "file")
        self.assertEqual(
            env["LSPP_PICKER_FILTER"],
            "LS-PrePost executable|lsprepost*.exe|Windows executable|*.exe",
        )

    def test_cancel_returns_none_but_process_failure_is_explicit(self) -> None:
        cancelled = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch.object(native_dialogs.subprocess, "run", return_value=cancelled):
            self.assertIsNone(native_dialogs.choose_directory("选择目录"))

        failed = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="dialog failed",
        )
        with patch.object(native_dialogs.subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(native_dialogs.NativeDialogUnavailable, "dialog failed"):
                native_dialogs.choose_directory("选择目录")

    def test_missing_powershell_and_timeout_are_explicit(self) -> None:
        with patch.object(
            native_dialogs.subprocess,
            "run",
            side_effect=FileNotFoundError("powershell.exe"),
        ):
            with self.assertRaisesRegex(native_dialogs.NativeDialogUnavailable, "PowerShell"):
                native_dialogs.choose_directory("选择目录")

        with patch.object(
            native_dialogs.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired("powershell.exe", 600),
        ):
            with self.assertRaisesRegex(native_dialogs.NativeDialogUnavailable, "超时"):
                native_dialogs.choose_directory("选择目录")

    def test_picker_is_safe_to_call_from_web_request_thread(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="E:/models/threaded",
            stderr="",
        )
        with patch.object(native_dialogs.subprocess, "run", return_value=completed):
            with ThreadPoolExecutor(max_workers=1) as executor:
                selected = executor.submit(
                    native_dialogs.choose_directory,
                    "选择模型文件夹",
                ).result(timeout=2)

        self.assertEqual(selected, Path("E:/models/threaded"))


if __name__ == "__main__":
    unittest.main()
