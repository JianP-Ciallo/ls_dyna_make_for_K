from __future__ import annotations

import json
import shutil
import subprocess
import unittest
import zipfile
import re
from pathlib import Path

from lsprepost_mcp.config import ROOT


class PackagingAndIntegrationBoundaryTests(unittest.TestCase):
    def test_doctor_reports_damage_assessment_as_optional(self) -> None:
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
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        checks = {item["name"]: item for item in payload["checks"]}
        self.assertIn("damage_assessment_optional", checks)
        self.assertIn(checks["damage_assessment_optional"]["status"], {"ok", "warning"})

    def test_test_matrix_lists_optional_assessment_lane(self) -> None:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "scripts" / "run_test_matrix.ps1"),
                "-List",
            ],
            cwd=str(ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("assessment:", result.stdout)

    def test_pack_rejects_single_backslash_windows_paths(self) -> None:
        probe = ROOT / "docs" / "pack_local_path_probe.txt"
        dist_pack = ROOT / "dist" / ".pack"
        foreign_stage = dist_pack / "foreign-stage-must-survive"
        foreign_marker = foreign_stage / "marker.txt"
        stage_pattern = "lsprepost-mcp_unit-local-path-probe_*"
        stages_before = set(dist_pack.glob(stage_pattern)) if dist_pack.exists() else set()
        drive = "E:"
        probe.write_text(f"local path example: {drive}\\Temp\\lspp\\model.k\n", encoding="utf-8")
        foreign_stage.mkdir(parents=True, exist_ok=True)
        foreign_marker.write_text("owned by another pack process\n", encoding="utf-8")
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
                    "unit-local-path-probe",
                ],
                cwd=str(ROOT),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=60,
            )
            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, combined)
            self.assertIn("Package contains local absolute path examples", combined)
            self.assertTrue(foreign_marker.exists(), "pack must not delete another process's staging directory")
            stages_after = set(dist_pack.glob(stage_pattern))
            self.assertEqual(stages_before, stages_after, "failed pack must clean its own staging directory")
        finally:
            if probe.exists():
                probe.unlink()
            if foreign_stage.exists():
                shutil.rmtree(foreign_stage)

    def test_integration_smoke_uses_managed_cfile_tools(self) -> None:
        source = (ROOT / "tests" / "test_integration_lsprepost.py").read_text(encoding="utf-8")
        self.assertNotIn("subprocess.run", source)
        self.assertNotIn("write_text('open keyword", source)
        self.assertIn("tool_validate_lsprepost_import", source)

    def test_pure_package_excludes_intermediate_artifacts(self) -> None:
        build_probe = ROOT / "packages/blast_damage_assessment/build/codex_pack_probe.tmp"
        build_probe.parent.mkdir(parents=True, exist_ok=True)
        build_probe.write_text("build output must not ship", encoding="utf-8")
        output = ROOT / "dist" / "unit-pure-package.zip"
        dist_pack = ROOT / "dist" / ".pack"
        stage_pattern = "lsprepost-mcp_unit-pure-package_*"
        stages_before = set(dist_pack.glob(stage_pattern)) if dist_pack.exists() else set()
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
                    "unit-pure-package",
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
            combined = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, combined)
            with zipfile.ZipFile(output) as archive:
                names = [name.replace("\\", "/") for name in archive.namelist()]
            forbidden_prefixes = [
                "packages/blast_damage_assessment/build/",
                "demo/",
                "dist/",
                "workspace/",
                "var/",
                "docx_render_check/",
                "extras/",
                "examples/phase",
                "docs/internal/",
                "docs/钢筋冲击钢盔_真实生成讲解/",
            ]
            for prefix in forbidden_prefixes:
                self.assertFalse(any(name.startswith(prefix) for name in names), prefix)
            self.assertIn("README.zh-CN.md", names)
            self.assertIn("pytest.ini", names)
            self.assertIn("conftest.py", names)
            self.assertIn("AGENTS.md", names)
            self.assertIn("start_web_app.cmd", names)
            self.assertIn("lsprepost_mcp/server.py", names)
            self.assertIn("scripts/start_web_app.ps1", names)
            self.assertIn("scripts/setup_damage_assessment.ps1", names)
            self.assertIn("packages/blast_damage_assessment/pyproject.toml", names)
            self.assertIn("packages/blast_damage_assessment/src/blast_damage_assessment/api.py", names)
            self.assertIn("lsprepost_mcp/web/app.py", names)
            self.assertIn("lsprepost_mcp/web/static/index.html", names)
            self.assertIn("examples/generate_model.jsonl", names)
            self.assertIn("resources/materials/builtin/mild_steel.json", names)
            self.assertIn("resources/materials/phase18/two_storey_rc_frame_blast_reference/two_storey_rc_frame_mid5_concrete_kc.json", names)
            self.assertIn("resources/model_library/structural/phase18/two_storey_rc_frame_blast_reference/two_storey_rc_frame_sections.json", names)
            self.assertIn("resources/reviews/phase18/two_storey_rc_frame_blast_reference_syntax_unit_review.json", names)
            self.assertFalse(any("/phase18/2k/" in name for name in names))
            self.assertNotIn("resources/reviews/phase18/2k_syntax_unit_review.json", names)
            self.assertIn("resources/templates/cfile/open_keyword.cfile", names)
            self.assertFalse(any(name.endswith(".docx") for name in names))
            windows_path_re = re.compile(r"[A-Za-z]:\\")
            with zipfile.ZipFile(output) as archive:
                text_hits = []
                for info in archive.infolist():
                    name = info.filename.replace("\\", "/")
                    if name == "scripts/pack.ps1":
                        continue
                    if not name.endswith((".py", ".ps1", ".md", ".json", ".jsonl", ".txt", ".cmd", ".sh", ".cfile")):
                        continue
                    text = archive.read(info).decode("utf-8", errors="ignore")
                    if windows_path_re.search(text):
                        text_hits.append(name)
            self.assertEqual([], text_hits)
            stages_after = set(dist_pack.glob(stage_pattern))
            self.assertEqual(stages_before, stages_after, "successful pack must clean its own staging directory")
        finally:
            build_probe.unlink(missing_ok=True)
            if output.exists():
                output.unlink()

    def test_readmes_describe_current_web_and_lsrun_handoff(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        detailed = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

        for text in (readme, detailed):
            self.assertIn("start_web_app.cmd", text)
            self.assertIn("导入 LS-Run", text)
            self.assertIn("导入 LS-DYNA", text)
            self.assertIn("打开 LS-Run", text)
            self.assertIn("不自动", text)
        self.assertNotIn("钢筋自由落体冲击", readme)

    def test_developer_package_excludes_binary_drafts_and_keeps_review_sources(self) -> None:
        output = ROOT / "dist" / "unit-developer-package.zip"
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
                    "unit-developer-package",
                    "-OutputPath",
                    str(output),
                ],
                cwd=str(ROOT),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=60,
            )
            combined = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, combined)
            with zipfile.ZipFile(output) as archive:
                names = [name.replace("\\", "/") for name in archive.namelist()]
            self.assertIn("README.md", names)
            self.assertIn("lsprepost_mcp/web/solve_api.py", names)
            self.assertIn(
                "lsprepost_mcp/web/static/vendor/three/three.core.min.js",
                names,
            )
            self.assertIn(
                "lsprepost_mcp/web/static/vendor/three/LICENSE",
                names,
            )
            self.assertIn("tests/test_packaging_and_integration_boundaries.py", names)
            self.assertFalse(any(name.lower().endswith(".docx") for name in names), names)
            self.assertFalse(any("/node_modules/" in name for name in names), names)
        finally:
            if output.exists():
                output.unlink()


if __name__ == "__main__":
    unittest.main()
