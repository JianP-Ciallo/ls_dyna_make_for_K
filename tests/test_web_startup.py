from __future__ import annotations

import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from lsprepost_mcp.tool_server import source_fingerprint, tool_server_info
from lsprepost_mcp.web.app import create_server


ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = ROOT / "scripts" / "start_web_app.ps1"
ROOT_LAUNCHER = ROOT / "start_web_app.cmd"


class WebStartupTests(unittest.TestCase):
    def test_web_server_refuses_a_second_listener_on_the_same_port(self) -> None:
        first = create_server("127.0.0.1", 0)
        port = first.server_address[1]
        try:
            with self.assertRaises(OSError):
                second = create_server("127.0.0.1", port)
                second.server_close()
        finally:
            first.server_close()

    def test_web_module_help_runs(self) -> None:
        result = subprocess.run(
            ["python", "-m", "lsprepost_mcp.web.app", "--help"],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--port", result.stdout)
        self.assertIn("--lspp-exe", result.stdout)

    def test_start_web_app_script_exists_and_mentions_module(self) -> None:
        self.assertTrue(START_SCRIPT.exists())
        text = START_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("lsprepost_mcp.web.app", text)
        self.assertIn("LsppExe", text)
        self.assertIn("source_fingerprint", text)
        self.assertIn("Stopped stale lsprepost-mcp Web App", text)
        self.assertIn("Refusing to stop", text)

    def test_server_info_exposes_current_source_fingerprint(self) -> None:
        fingerprint = source_fingerprint()
        self.assertRegex(fingerprint, r"^[0-9a-f]{64}$")
        info = tool_server_info({})
        self.assertEqual(info["source_fingerprint"], fingerprint)
        self.assertGreater(info["process_id"], 0)

    def test_start_web_app_script_forwards_open_browser_flag(self) -> None:
        self.assertTrue(START_SCRIPT.exists())
        text = START_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("--open-browser", text)

    def test_start_script_reuses_healthy_instance_from_same_workspace(self) -> None:
        server = create_server("127.0.0.1", 0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(START_SCRIPT),
                    "-SkipDoctor",
                    "-Port",
                    str(port),
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("already running", output.lower())

    def test_start_script_runs_from_outside_workspace(self) -> None:
        server = create_server("127.0.0.1", 0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="web launcher cwd ") as temp_dir:
                result = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(START_SCRIPT),
                        "-SkipDoctor",
                        "-Port",
                        str(port),
                    ],
                    cwd=temp_dir,
                    text=True,
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("already running", output.lower())

    def test_start_script_does_not_reuse_an_unrelated_http_service(self) -> None:
        class ForeignHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                body = b'{"ok":true,"result":{"name":"another-app","workspace_root":"C:/other"}}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), ForeignHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(START_SCRIPT),
                    "-SkipDoctor",
                    "-Port",
                    str(port),
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertNotIn("already running", output.lower())

    def test_root_one_click_launcher_exists_and_opens_browser(self) -> None:
        self.assertTrue(ROOT_LAUNCHER.exists())
        text = ROOT_LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("scripts\\start_web_app.ps1", text)
        self.assertIn("-OpenBrowser", text)
        self.assertIn("-SkipDoctor", text)

    def test_root_one_click_launcher_pauses_on_startup_failure(self) -> None:
        self.assertTrue(ROOT_LAUNCHER.exists())
        text = ROOT_LAUNCHER.read_text(encoding="utf-8").lower()
        self.assertIn("if errorlevel 1", text)
        self.assertIn("pause", text)

    def test_start_web_app_script_forwards_open_browser_and_exits_on_invalid_port(self) -> None:
        fake_lspp_exe = ROOT / "tmp path with spaces" / "ls prepost.exe"
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(START_SCRIPT),
                "-SkipDoctor",
                "-OpenBrowser",
                "-LsppExe",
                str(fake_lspp_exe),
                "-Port",
                "-1",
            ],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=30,
        )
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertRegex(output.lower(), r"invalid|port|bind|argument")
        self.assertNotIn("lsprepost-mcp web app:", output)
        self.assertNotIn("unrecognized arguments", output.lower())

    def test_start_web_app_script_rejects_non_local_host(self) -> None:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(START_SCRIPT),
                "-SkipDoctor",
                "-HostName",
                "0.0.0.0",
                "-Port",
                "0",
            ],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("host must be localhost or 127.0.0.1", output)


if __name__ == "__main__":
    unittest.main()
