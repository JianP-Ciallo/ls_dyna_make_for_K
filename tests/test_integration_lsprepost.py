from __future__ import annotations

import os
import shutil
import time
import unittest

from lsprepost_mcp.config import lspp_exe
from lsprepost_mcp.lsdyna_runner import execute_lsdyna_run
from lsprepost_mcp.paths import project_dir
from lsprepost_mcp.project_store import validate_project_files, write_model_project
from lsprepost_mcp.schema import default_model_spec, parse_model_spec, rebar_drop_on_helmet_spec
from lsprepost_mcp.tools import (
    tool_export_preview_gif,
    tool_export_preview_image,
    tool_export_preview_images,
    tool_generate_phase15_a1,
    tool_generate_scene_from_prompt,
    tool_validate_lsprepost_import,
)
from lsprepost_mcp.web.config_api import configured_lsdyna_exe


@unittest.skipUnless(os.environ.get("LSPP_INTEGRATION") == "1", "set LSPP_INTEGRATION=1 to run LS-PrePost GUI integration smoke")
class LsPrePostIntegrationSmoke(unittest.TestCase):
    def test_preview_image_template_exports_nonempty_artifact(self) -> None:
        exe = lspp_exe()
        if not exe.exists():
            self.skipTest(f"LSPP_EXE does not exist: {exe}")

        name = f"integration_preview_{int(time.time())}"
        path = project_dir(name)
        if path.exists():
            shutil.rmtree(path)
        try:
            result = write_model_project(parse_model_spec(default_model_spec(name, "shell_plate")))
            path = project_dir(result["project"])
            output = path / "artifacts" / "preview.png"
            result = tool_export_preview_image({"project_name": name, "timeout_s": 45.0, "output_filename": "preview.png"})
            self.assertEqual(result["keyword_reader"]["warnings"], 0)
            self.assertEqual(result["keyword_reader"]["errors"], 0)
            deadline = time.monotonic() + 45.0
            while time.monotonic() < deadline:
                if output.exists() and output.stat().st_size > 0:
                    break
                time.sleep(0.5)
            self.assertTrue(output.exists(), f"preview image was not created: {output}")
            self.assertGreater(output.stat().st_size, 0)
            self.assertEqual(output.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_rebar_drop_on_helmet_exports_preview_and_clean_keyword_messages(self) -> None:
        exe = lspp_exe()
        if not exe.exists():
            self.skipTest(f"LSPP_EXE does not exist: {exe}")

        name = f"integration_rebar_helmet_{int(time.time())}"
        path = project_dir(name)
        if path.exists():
            shutil.rmtree(path)
        try:
            result = write_model_project(parse_model_spec(rebar_drop_on_helmet_spec(name)))
            path = project_dir(result["project"])
            output = path / "artifacts" / "preview.png"
            result = tool_export_preview_image({"project_name": name, "timeout_s": 45.0, "output_filename": "preview.png", "view": "iso"})
            self.assertEqual(result["view"], "iso")
            self.assertEqual(result["keyword_reader"]["warnings"], 0)
            self.assertEqual(result["keyword_reader"]["errors"], 0)
            self.assertTrue(output.exists(), f"preview image was not created: {output}")
            self.assertGreater(output.stat().st_size, 0)
            self.assertEqual(output.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

            validation = tool_validate_lsprepost_import({"project_name": name, "timeout_s": 45.0})
            self.assertTrue(validation["ok"])
            self.assertTrue(validation["validation"]["keyword_reader_ok"])
            self.assertTrue(validation["validation"]["required_keywords"]["ok"])
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_rebar_drop_on_helmet_controlled_views_export_distinct_pngs(self) -> None:
        exe = lspp_exe()
        if not exe.exists():
            self.skipTest(f"LSPP_EXE does not exist: {exe}")

        name = f"integration_rebar_views_{int(time.time())}"
        path = project_dir(name)
        if path.exists():
            shutil.rmtree(path)
        try:
            write_model_project(parse_model_spec(rebar_drop_on_helmet_spec(name)))
            import hashlib

            result = tool_export_preview_images({"project_name": name, "timeout_s": 45.0})
            self.assertTrue(result["ok"])
            self.assertEqual(result["views"], ["iso", "top", "front", "side"])
            digests: set[bytes] = set()
            for item in result["results"]:
                view = item["view"]
                output = path / "artifacts" / f"preview_{view}.png"
                self.assertEqual(item["keyword_reader"]["warnings"], 0)
                self.assertEqual(item["keyword_reader"]["errors"], 0)
                self.assertTrue(output.exists(), f"preview image was not created: {output}")
                digests.add(hashlib.sha256(output.read_bytes()).digest())
            self.assertGreater(len(digests), 1)
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_rebar_drop_on_helmet_exports_preview_gif(self) -> None:
        exe = lspp_exe()
        if not exe.exists():
            self.skipTest(f"LSPP_EXE does not exist: {exe}")

        name = f"integration_rebar_gif_{int(time.time())}"
        path = project_dir(name)
        if path.exists():
            shutil.rmtree(path)
        try:
            write_model_project(parse_model_spec(rebar_drop_on_helmet_spec(name)))
            result = tool_export_preview_gif({"project_name": name, "timeout_s": 45.0})
            self.assertTrue(result["ok"])
            self.assertEqual(result["views"], ["iso", "top", "front"])
            self.assertEqual(result["frame_count"], 3)
            output = path / "artifacts" / "preview_summary.gif"
            self.assertTrue(output.exists(), f"preview GIF was not created: {output}")
            self.assertGreater(output.stat().st_size, 0)
            self.assertIn(output.read_bytes()[:6], {b"GIF87a", b"GIF89a"})
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_rebar_drop_on_helmet_validate_lsprepost_import(self) -> None:
        exe = lspp_exe()
        if not exe.exists():
            self.skipTest(f"LSPP_EXE does not exist: {exe}")

        name = f"integration_rebar_import_validation_{int(time.time())}"
        path = project_dir(name)
        if path.exists():
            shutil.rmtree(path)
        try:
            write_model_project(parse_model_spec(rebar_drop_on_helmet_spec(name)))
            result = tool_validate_lsprepost_import({"project_name": name, "timeout_s": 45.0})
            self.assertTrue(result["ok"])
            self.assertTrue(result["validation"]["static_checks_ok"])
            self.assertTrue(result["validation"]["keyword_reader_ok"])
            self.assertTrue(result["validation"]["preview_png_ok"])
            self.assertTrue(result["validation"]["required_keywords"]["ok"])
            self.assertEqual(result["display_controls"]["display_mode"], "validation")
            output = path / "artifacts" / "import_validation_iso.png"
            self.assertTrue(output.exists(), f"validation image was not created: {output}")
            self.assertGreater(output.stat().st_size, 0)
            self.assertEqual(output.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_generate_scene_from_prompt_runs_rebar_helmet_validation_pipeline(self) -> None:
        exe = lspp_exe()
        if not exe.exists():
            self.skipTest(f"LSPP_EXE does not exist: {exe}")

        name = f"integration_scene_prompt_rebar_{int(time.time())}"
        path = project_dir(name)
        if path.exists():
            shutil.rmtree(path)
        try:
            result = tool_generate_scene_from_prompt(
                {
                    "project_name": name,
                    "prompt": "生成一根1米长、半径12毫米的钢筋，从头盔上方10米自由落体，撞击固定在地面上的头盔",
                    "run_lsprepost_validation": True,
                    "export_previews": True,
                    "timeout_s": 45.0,
                }
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["scene_template"], "rebar_drop_on_helmet")
            self.assertTrue(result["checks"]["ok"])
            self.assertTrue(result["lsprepost_import"]["ok"])
            self.assertTrue(result["preview_images"]["ok"])
            self.assertEqual(result["preview_images"]["count"], 4)
            self.assertTrue((path / "model.k").exists())
            self.assertTrue((path / "artifacts" / "import_validation_iso.png").exists())
            for view in ["iso", "top", "front", "side"]:
                output = path / "artifacts" / f"preview_{view}.png"
                self.assertTrue(output.exists(), f"preview image was not created: {output}")
                self.assertEqual(output.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        finally:
            if path.exists():
                shutil.rmtree(path)


@unittest.skipUnless(
    os.environ.get("LSPP_INTEGRATION") == "1"
    and os.environ.get("LSDYNA_INTEGRATION") == "1",
    "set LSPP_INTEGRATION=1 and LSDYNA_INTEGRATION=1 to run Phase 15 qualification",
)
class Phase15ConformingIntegrationSmoke(unittest.TestCase):
    def test_unique_air_gap_project_uses_managed_solver_runner(self) -> None:
        lsdyna = configured_lsdyna_exe()
        if lsdyna is None or not lsdyna.is_file():
            self.skipTest("configured LS-DYNA executable is unavailable")

        name = f"phase15_conforming_air_gap_integration_{time.time_ns()}"
        path = project_dir(name)
        if path.exists():
            shutil.rmtree(path)
        try:
            generated = tool_generate_phase15_a1(
                {
                    "project_name": name,
                    "coupling_mode": "conforming_air_gap",
                    "consistency_mode": "mass_priority_adjust_length",
                    "mesh_size_m": 0.006,
                    "borehole_radius_m": 0.073,
                    "bottom_air_gap_m": 0.024,
                    "end_time_s": 0.0002,
                    "if_exists": "error",
                }
            )
            self.assertTrue(generated["ok"])
            completed = execute_lsdyna_run(
                path,
                lsdyna,
                ncpu=4,
                memory="512m",
                timeout_s=900.0,
                static_validation=validate_project_files(path),
            )
            self.assertEqual(0, completed["returncode"])
            self.assertTrue(completed["solver_evaluation"]["ok"])
            self.assertTrue(
                completed["wave_transfer_acceptance"]["wave_transfer_verified"]
            )
            self.assertTrue(completed["ok"])
        finally:
            if path.exists():
                shutil.rmtree(path)


if __name__ == "__main__":
    unittest.main()
