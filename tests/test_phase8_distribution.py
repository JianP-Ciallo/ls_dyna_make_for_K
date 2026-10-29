from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from lsprepost_mcp.config import ROOT


class Phase8DistributionTests(unittest.TestCase):
    def test_doctor_json_reports_core_checks_ok_without_lsprepost_requirement(self) -> None:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "scripts" / "doctor.ps1"),
                "-Json",
            ],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], payload)
        check_names = {item["name"] for item in payload["checks"]}
        self.assertIn("python_available", check_names)
        self.assertIn("server_importable", check_names)
        self.assertIn("templates_present", check_names)
        self.assertIn("materials_present", check_names)
        self.assertIn("pillow_optional", check_names)
        self.assertIn("web_app_files", check_names)
        self.assertIn("node_optional", check_names)
        pillow = next(item for item in payload["checks"] if item["name"] == "pillow_optional")
        self.assertIn(pillow["status"], {"ok", "warning"})
        web_files = next(item for item in payload["checks"] if item["name"] == "web_app_files")
        self.assertEqual(web_files["status"], "ok")
        self.assertIsInstance(web_files["detail"], list)
        self.assertIn("lsprepost_mcp\\web\\http_utils.py", web_files["detail"])
        self.assertIn("lsprepost_mcp\\web\\scenes.py", web_files["detail"])
        self.assertIn("lsprepost_mcp\\web\\static\\styles.css", web_files["detail"])
        node = next(item for item in payload["checks"] if item["name"] == "node_optional")
        self.assertIn(node["status"], {"ok", "warning"})

    def test_doctor_require_lsprepost_fails_for_missing_exe(self) -> None:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "scripts" / "doctor.ps1"),
                "-Json",
                "-RequireLsPrePost",
                "-LsppExe",
                str(ROOT / "missing_lsprepost.exe"),
            ],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=60,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"], payload)
        lspp = next(item for item in payload["checks"] if item["name"] == "lsprepost_exe")
        self.assertEqual(lspp["status"], "error")

    def test_doctor_require_lsprepost_rejects_directory_named_like_exe(self) -> None:
        fake_exe_dir = ROOT / "tmp_doctor_dir_probe" / "lsprepost4.12.exe"
        if fake_exe_dir.parent.exists():
            shutil.rmtree(fake_exe_dir.parent)
        fake_exe_dir.mkdir(parents=True)
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ROOT / "scripts" / "doctor.ps1"),
                    "-Json",
                    "-RequireLsPrePost",
                    "-LsppExe",
                    str(fake_exe_dir),
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"], payload)
            lspp = next(item for item in payload["checks"] if item["name"] == "lsprepost_exe")
            self.assertEqual(lspp["status"], "error")
        finally:
            if fake_exe_dir.parent.exists():
                shutil.rmtree(fake_exe_dir.parent)

    def test_setup_noninteractive_fails_and_does_not_write_configs_when_strict_doctor_fails(self) -> None:
        out = ROOT / "var" / "generated_configs" / "unit_phase8_setup_missing"
        if out.exists():
            shutil.rmtree(out)
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "scripts" / "setup.ps1"),
                "-NonInteractive",
                "-LsppExe",
                str(ROOT / "definitely_missing" / "lsprepost4.12.exe"),
                "-OutputDir",
                str(out),
            ],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=60,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(out.exists())

    def test_setup_noninteractive_writes_generated_configs_without_validating_placeholder(self) -> None:
        out = ROOT / "var" / "generated_configs" / "unit_phase8_setup"
        if out.exists():
            shutil.rmtree(out)
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ROOT / "scripts" / "setup.ps1"),
                    "-NonInteractive",
                    "-SkipDoctor",
                    "-SkipLsppValidation",
                    "-LsppExe",
                    "<LS_PREPOST_EXE>",
                    "-OutputDir",
                    str(out),
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((out / "codex.mcp.json").exists())
            self.assertTrue((out / "vscode.mcp.json").exists())
            self.assertTrue((out / "lsprepost_mcp.local.env.ps1").exists())
            text = (out / "codex.mcp.json").read_text(encoding="utf-8")
            self.assertIn("<LS_PREPOST_EXE>", text)
        finally:
            if out.exists():
                shutil.rmtree(out)

    def test_install_to_vscode_writes_project_mcp_config_and_refuses_overwrite(self) -> None:
        target = ROOT / "var" / "generated_configs" / "unit_install_vscode_project"
        if target.exists():
            shutil.rmtree(target)
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ROOT / "scripts" / "install_to_vscode.ps1"),
                    "-TargetDir",
                    str(target),
                    "-LsppExe",
                    "<LS_PREPOST_EXE>",
                    "-SkipLsppValidation",
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            config = target / ".vscode" / "mcp.json"
            self.assertTrue(config.exists())
            payload = json.loads(config.read_text(encoding="utf-8-sig"))
            self.assertIn("servers", payload)
            self.assertEqual(payload["servers"]["lsprepost"]["env"]["LSPP_EXE"], "<LS_PREPOST_EXE>")

            second = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ROOT / "scripts" / "install_to_vscode.ps1"),
                    "-TargetDir",
                    str(target),
                    "-LsppExe",
                    "<LS_PREPOST_EXE>",
                    "-SkipLsppValidation",
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertNotEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn("already exists", second.stderr + second.stdout)

            forced = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ROOT / "scripts" / "install_to_vscode.ps1"),
                    "-TargetDir",
                    str(target),
                    "-LsppExe",
                    "<LS_PREPOST_EXE>",
                    "-SkipLsppValidation",
                    "-Force",
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(forced.returncode, 0, forced.stdout + forced.stderr)
        finally:
            if target.exists():
                shutil.rmtree(target)

    def test_install_to_cursor_writes_project_mcp_config(self) -> None:
        target = ROOT / "var" / "generated_configs" / "unit_install_cursor_project"
        if target.exists():
            shutil.rmtree(target)
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ROOT / "scripts" / "install_to_cursor.ps1"),
                    "-TargetDir",
                    str(target),
                    "-LsppExe",
                    "<LS_PREPOST_EXE>",
                    "-SkipLsppValidation",
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            config = target / ".cursor" / "mcp.json"
            self.assertTrue(config.exists())
            payload = json.loads(config.read_text(encoding="utf-8-sig"))
            self.assertIn("mcpServers", payload)
            self.assertEqual(payload["mcpServers"]["lsprepost"]["env"]["LSPP_EXE"], "<LS_PREPOST_EXE>")
        finally:
            if target.exists():
                shutil.rmtree(target)


if __name__ == "__main__":
    unittest.main()
