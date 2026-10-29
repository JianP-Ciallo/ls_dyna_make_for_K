from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


class Phase10PathTests(unittest.TestCase):
    def test_doctor_script_runs_from_cwd_with_spaces_and_unicode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "doctor.ps1"
        with tempfile.TemporaryDirectory(prefix="lsprepost 路径 space ") as tmp:
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-Json",
                ],
                cwd=tmp,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn('"name":  "python_available"', completed.stdout)
        self.assertIn('"name":  "required_files"', completed.stdout)

    def test_setup_writes_output_dir_with_spaces_and_unicode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "setup.ps1"
        with tempfile.TemporaryDirectory(prefix="setup 输出 space ") as tmp:
            out = Path(tmp) / "生成 configs"
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-NonInteractive",
                    "-SkipDoctor",
                    "-SkipLsppValidation",
                    "-LsppExe",
                    "<LS_PREPOST_EXE>",
                    "-OutputDir",
                    str(out),
                ],
                cwd=tmp,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertTrue((out / "codex.mcp.json").exists())
            self.assertTrue((out / "lsprepost_mcp.local.env.ps1").exists())

    def test_pack_writes_output_path_with_spaces_and_unicode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "pack.ps1"
        with tempfile.TemporaryDirectory(prefix="pack 输出 space ") as tmp:
            output = Path(tmp) / "纯净 包.zip"
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-BuildLabel",
                    "unit-path-output",
                    "-OutputPath",
                    str(output),
                    "-Pure",
                ],
                cwd=tmp,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertTrue(output.exists())

    def test_run_test_matrix_errors_runs_from_cwd_with_spaces_and_unicode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "run_test_matrix.ps1"
        with tempfile.TemporaryDirectory(prefix="matrix 路径 space ") as tmp:
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-Group",
                    "errors",
                ],
                cwd=tmp,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Running test matrix group: errors", completed.stdout)


if __name__ == "__main__":
    unittest.main()
