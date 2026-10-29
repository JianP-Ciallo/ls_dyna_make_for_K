from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


class Phase10TestMatrixTests(unittest.TestCase):
    def test_run_test_matrix_lists_supported_groups(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "run_test_matrix.ps1"
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-List",
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("default", completed.stdout)
        self.assertIn("critical", completed.stdout)
        self.assertIn("packaging", completed.stdout)
        self.assertIn("snapshots", completed.stdout)
        self.assertIn("errors", completed.stdout)
        self.assertIn("paths", completed.stdout)
        self.assertIn("gui", completed.stdout)
        self.assertIn("web", completed.stdout)
        self.assertIn("all", completed.stdout)

    def test_run_test_matrix_executes_lightweight_group(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "run_test_matrix.ps1"
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
            cwd=root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Running test matrix group: errors", completed.stdout)

    def test_run_test_matrix_executes_web_group(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "run_test_matrix.ps1"
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Group",
                "web",
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Running test matrix group: web", completed.stdout)


if __name__ == "__main__":
    unittest.main()
