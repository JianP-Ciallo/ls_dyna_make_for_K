from __future__ import annotations

import subprocess
import unittest
import zipfile

from lsprepost_mcp.config import ROOT


class Phase18CPackagingTests(unittest.TestCase):
    def test_pure_package_contains_refined_building_kernel_without_caches(self) -> None:
        output = ROOT / "dist" / "unit-phase18c-pure-package.zip"
        if output.exists():
            output.unlink()
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ROOT / "scripts" / "pack.ps1"),
                    "-BuildLabel",
                    "unit-phase18c-pure-package",
                    "-OutputPath",
                    str(output),
                    "-Pure",
                ],
                cwd=str(ROOT),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            with zipfile.ZipFile(output) as archive:
                names = {name.replace("\\", "/") for name in archive.namelist()}
            self.assertIn("lsprepost_mcp/refined_building/compiler.py", names)
            self.assertIn("lsprepost_mcp/refined_building/backends/rc.py", names)
            self.assertIn("tests/test_phase18c_dependency_boundaries.py", names)
            self.assertFalse(any("/__pycache__/" in name for name in names))
            self.assertFalse(any(name.endswith((".pyc", ".pyo")) for name in names))
        finally:
            if output.exists():
                output.unlink()


if __name__ == "__main__":
    unittest.main()
