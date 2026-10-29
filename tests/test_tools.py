from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from lsprepost_mcp.artifacts import artifact_path
from lsprepost_mcp.cfile import (
    read_cfile_manifest,
    register_server_cfile,
    render_cfile_template,
    validate_server_cfile_path,
    write_server_cfile,
)
from lsprepost_mcp.config import PROJECTS_DIR
from lsprepost_mcp.io import read_json
from lsprepost_mcp.locks import LOCKS_DIR, ProjectLock
from lsprepost_mcp.lspp.launcher import (
    active_cfile_snapshot_paths,
    compact_process_records,
    cleanup_cfile_snapshots,
    doctor_lsprepost_exe,
    is_process_running,
    launch_cfile,
    launch_d3plot,
    launch_keyword,
    process_matches_record,
    record_process,
    running_project_processes,
    validate_d3plot_path,
    validate_keyword_path,
)
from lsprepost_mcp.paths import project_dir
from lsprepost_mcp.project_store import (
    CHECKER_VERSION,
    RUNTIME_ARTIFACT_MARKER,
    archive_project,
    cleanup_stale_project_artifacts,
    import_keyword_project,
    iter_project_records,
    rebase_committed_checks,
    write_model_project,
)
from lsprepost_mcp.run_evidence import seal_phase14_run_evidence
from lsprepost_mcp.schema import default_model_spec, parse_model_spec, rebar_drop_on_helmet_spec
from lsprepost_mcp.tool_lsprepost import tool_open_result_lsprepost
from lsprepost_mcp.tool_project import tool_read_project
from lsprepost_mcp.tools import (
    tool_create_plate_demo,
    tool_export_preview_gif,
    tool_export_preview_image,
    tool_export_preview_images,
    tool_generate_scene_from_prompt,
    tool_open_in_lsprepost,
    tool_run_cfile,
    tool_validate_lsprepost_import,
)


def write_fake_lsprepost_outputs(project_path: Path, cfile_path: Path, payload: bytes = b"unit-preview") -> None:
    text = cfile_path.read_text(encoding="utf-8")
    output_path = None
    kwdmsg_path = None
    for line in text.splitlines():
        if line.startswith("print png "):
            output_path = project_path / line.split('"')[1]
        if line.startswith("save kwdmsg "):
            kwdmsg_path = project_path / line.split('"')[1]
    if output_path is None:
        raise AssertionError("test cfile did not contain print png command")
    if kwdmsg_path is None:
        raise AssertionError("test cfile did not contain save kwdmsg command")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"\x89PNG\r\n\x1a\n" + payload)
    kwdmsg_path.parent.mkdir(parents=True, exist_ok=True)
    kwdmsg_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<KeywordReaderMessages>\n  <Warnings/>\n  <Errors/>\n</KeywordReaderMessages>\n',
        encoding="utf-8",
    )


def write_fake_lsprepost_image_outputs(project_path: Path, cfile_path: Path) -> None:
    from PIL import Image

    text = cfile_path.read_text(encoding="utf-8")
    output_path = None
    kwdmsg_path = None
    for line in text.splitlines():
        if line.startswith("print png "):
            output_path = project_path / line.split('"')[1]
        if line.startswith("save kwdmsg "):
            kwdmsg_path = project_path / line.split('"')[1]
    if output_path is None or kwdmsg_path is None:
        raise AssertionError("test cfile did not contain expected output commands")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    color_seed = sum(output_path.name.encode("utf-8")) % 255
    Image.new("RGB", (8, 8), (color_seed, 80, 180)).save(output_path, format="PNG")
    kwdmsg_path.parent.mkdir(parents=True, exist_ok=True)
    kwdmsg_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<KeywordReaderMessages>\n  <Warnings/>\n  <Errors/>\n</KeywordReaderMessages>\n',
        encoding="utf-8",
    )


class ToolTests(unittest.TestCase):
    def test_checker_version_tracks_r12_solver_compatibility_rules(self) -> None:
        from lsprepost_mcp.project_store import project_checks_are_current, project_validation_fingerprint

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            fingerprint = project_validation_fingerprint(path)
            checks = {"validation_fingerprint": fingerprint}
            self.assertTrue(project_checks_are_current(path, checks))
            fingerprint["checker_version"] = "phase17.r12_solver_compatibility.v5"
            self.assertFalse(project_checks_are_current(path, checks))

    def test_rebase_committed_checks_updates_nested_project_summary(self) -> None:
        rebased = rebase_committed_checks(
            {
                "project_name": ".demo.tmp_20260730T000000Z",
                "summary": {
                    "project_name": ".demo.tmp_20260730T000000Z",
                    "model_type": "city_street_blast_scene",
                },
            },
            project_name="demo",
            project_path=Path("workspace/projects/demo"),
        )

        self.assertEqual("demo", rebased["project_name"])
        self.assertEqual("demo", rebased["summary"]["project_name"])

    def test_read_project_revalidates_stale_checks_against_current_model_files(self) -> None:
        path = project_dir("unit_validation_fingerprint")
        if path.exists():
            shutil.rmtree(path)
        try:
            spec = parse_model_spec(default_model_spec("unit_validation_fingerprint", "shell_plate"))
            written = write_model_project(spec)
            first_fingerprint = written["checks"]["validation_fingerprint"]
            self.assertEqual(CHECKER_VERSION, first_fingerprint["checker_version"])
            self.assertEqual(64, len(first_fingerprint["model_k_sha256"]))
            self.assertEqual(64, len(first_fingerprint["model_json_sha256"]))

            current = tool_read_project({"project_name": "unit_validation_fingerprint"})
            self.assertFalse(current["checks_freshness"]["revalidated"])
            self.assertEqual("current", current["checks_freshness"]["status"])

            keyword_path = path / "model.k"
            keyword = keyword_path.read_text(encoding="utf-8")
            keyword_path.write_text(
                keyword.replace("*END", "$ validation freshness probe\n*END"),
                encoding="utf-8",
            )

            refreshed = tool_read_project({"project_name": "unit_validation_fingerprint"})
            self.assertTrue(refreshed["checks_freshness"]["revalidated"])
            self.assertEqual("stale", refreshed["checks_freshness"]["previous_status"])
            self.assertNotEqual(
                first_fingerprint["model_k_sha256"],
                refreshed["checks"]["validation_fingerprint"]["model_k_sha256"],
            )
            persisted = read_json(path / "checks.json")
            self.assertEqual(
                refreshed["checks"]["validation_fingerprint"],
                persisted["validation_fingerprint"],
            )

            persisted["validation_fingerprint"]["checker_version"] = "legacy-checker"
            (path / "checks.json").write_text(
                json.dumps(persisted),
                encoding="utf-8",
            )
            upgraded = tool_read_project({"project_name": "unit_validation_fingerprint"})
            self.assertTrue(upgraded["checks_freshness"]["revalidated"])
            self.assertEqual("stale", upgraded["checks_freshness"]["previous_status"])
            self.assertEqual(
                CHECKER_VERSION,
                upgraded["checks"]["validation_fingerprint"]["checker_version"],
            )

            (path / "checks.json").write_text("{", encoding="utf-8")
            repaired = tool_read_project({"project_name": "unit_validation_fingerprint"})
            self.assertTrue(repaired["checks_freshness"]["revalidated"])
            self.assertEqual("invalid", repaired["checks_freshness"]["previous_status"])
            self.assertTrue(repaired["checks"]["ok"])
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_generate_model_refuses_existing_project_by_default_and_supports_versioned(self) -> None:
        base = project_dir("unit_if_exists")
        versioned = project_dir("unit_if_exists_v2")
        for path in [base, versioned]:
            if path.exists():
                shutil.rmtree(path)
        try:
            spec = parse_model_spec(default_model_spec("unit_if_exists", "shell_plate"))
            first = write_model_project(spec)
            self.assertEqual(first["project"], "unit_if_exists")
            self.assertFalse((base / RUNTIME_ARTIFACT_MARKER).exists())
            with self.assertRaises(FileExistsError):
                write_model_project(spec)
            second = write_model_project(spec, if_exists="versioned")
            self.assertEqual(second["project"], "unit_if_exists_v2")
            self.assertTrue(versioned.exists())
        finally:
            for path in [base, versioned]:
                if path.exists():
                    shutil.rmtree(path)

    def test_write_assembly_scene_project_records_components_and_contacts(self) -> None:
        path = project_dir("unit_assembly_project")
        if path.exists():
            shutil.rmtree(path)
        try:
            spec = parse_model_spec(default_model_spec("unit_assembly_project", "assembly_scene"))
            result = write_model_project(spec)
            self.assertEqual(result["metadata"]["model_type"], "assembly_scene")
            self.assertEqual(result["metadata"]["part_count"], 2)
            self.assertEqual(result["metadata"]["contact_count"], 1)
            self.assertTrue(result["checks"]["ok"])
            self.assertTrue((path / "model.k").exists())
            self.assertTrue((path / "model.json").exists())
            by_id = {item["id"]: item for item in result["checks"]["checks"]}
            self.assertTrue(by_id["quality.unsupported.contact_cards"]["ok"])
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_write_rebar_drop_on_helmet_project_records_solver_draft(self) -> None:
        path = project_dir("unit_rebar_drop_on_helmet_project")
        if path.exists():
            shutil.rmtree(path)
        try:
            spec = parse_model_spec(rebar_drop_on_helmet_spec("unit_rebar_drop_on_helmet_project"))
            result = write_model_project(spec)
            self.assertEqual(result["metadata"]["model_type"], "assembly_scene")
            self.assertEqual(result["metadata"]["part_count"], 2)
            self.assertEqual(result["metadata"]["contact_count"], 1)
            self.assertEqual(result["metadata"]["load_count"], 1)
            self.assertTrue(result["checks"]["ok"])
            self.assertTrue(result["checks"]["readiness"]["ok_for_solver_draft"])
            text = (path / "model.k").read_text(encoding="utf-8")
            self.assertIn("helmet_ellipsoid_shell", text)
            self.assertIn("*LOAD_BODY_Z", text)
            self.assertIn("*INITIAL_VELOCITY_NODE", text)
            self.assertIn("0,0,-10,0.0,0.0,0.0", text)
            self.assertIn("*DATABASE_BINARY_D3PLOT", text)
            self.assertIn("*DATABASE_EXTENT_BINARY", text)
            self.assertIn("*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE", text)
            self.assertIn("*ELEMENT_SHELL", text)
            self.assertIn("*ELEMENT_SOLID", text)
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_generate_scene_from_prompt_creates_rebar_helmet_project(self) -> None:
        path = project_dir("unit_scene_prompt_rebar_helmet")
        if path.exists():
            shutil.rmtree(path)
        try:
            result = tool_generate_scene_from_prompt(
                {
                    "project_name": "unit_scene_prompt_rebar_helmet",
                    "parameters": {"impact_velocity_m_per_s": 10.0},
                    "prompt": "生成一根1米长、半径12毫米的钢筋，从头盔上方10米自由落体，撞击固定在地面上的头盔",
                }
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["scene_template"], "rebar_drop_on_helmet")
            self.assertEqual(result["resolved_parameters"]["rebar_length_m"], 1.0)
            self.assertEqual(result["resolved_parameters"]["rebar_radius_m"], 0.012)
            self.assertEqual(result["resolved_parameters"]["drop_height_m"], 10.0)
            self.assertEqual(result["resolved_parameters"]["impact_velocity_m_per_s"], 10.0)
            self.assertTrue((path / "model.k").exists())
            model = read_json(path / "model.json")
            rebar = next(item for item in model["spec"]["components"] if item["id"] == "rebar")
            self.assertEqual(rebar["geometry"]["length_m"], 1.0)
            self.assertEqual(rebar["geometry"]["radius_m"], 0.012)
            self.assertEqual(rebar["transform"]["translate_m"][2], 10.12)
            self.assertEqual(rebar["initial_velocity_m_per_s"], [0.0, 0.0, -10.0])
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_generate_scene_from_prompt_honors_explicit_scene_id_over_prompt_text(self) -> None:
        path = project_dir("unit_scene_id_rebar_over_prompt")
        if path.exists():
            shutil.rmtree(path)
        result = tool_generate_scene_from_prompt(
            {
                "scene_id": "rebar_drop_on_helmet",
                "project_name": "unit_scene_id_rebar_over_prompt",
                "prompt": "Generate a rod impact on a fixed steel plate.",
                "parameters": {
                    "rebar_length_m": 1.0,
                    "rebar_radius_m": 0.012,
                    "drop_height_m": 10.0,
                    "impact_velocity_m_per_s": 10.0,
                    "material_name": "mild_steel",
                },
                "allow_defaults": True,
                "dry_run": True,
            }
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["scene_template"], "rebar_drop_on_helmet")
        self.assertEqual(result["resolved_spec"]["geometry"]["scene"], "rebar_drop_on_helmet")
        self.assertEqual(
            [component["id"] for component in result["resolved_spec"]["components"]],
            ["rebar", "helmet"],
        )
        self.assertFalse(path.exists())

    def test_generate_scene_from_prompt_defaults_rebar_helmet_to_near_field_initial_velocity(self) -> None:
        path = project_dir("unit_scene_prompt_rebar_velocity_default")
        if path.exists():
            shutil.rmtree(path)
        result = tool_generate_scene_from_prompt(
            {
                "scene_id": "rebar_drop_on_helmet",
                "project_name": "unit_scene_prompt_rebar_velocity_default",
                "prompt": "生成钢管撞击钢盔的受控场景。",
                "allow_defaults": True,
                "dry_run": True,
            }
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["resolved_parameters"]["drop_height_m"], 0.5)
        self.assertEqual(result["resolved_parameters"]["impact_velocity_m_per_s"], 10.0)
        rebar = next(item for item in result["resolved_spec"]["components"] if item["id"] == "rebar")
        self.assertEqual(rebar["transform"]["translate_m"][2], 0.62)
        self.assertEqual(rebar["initial_velocity_m_per_s"], [0.0, 0.0, -10.0])
        self.assertFalse(path.exists())

    def test_generate_scene_from_prompt_rejects_unknown_explicit_scene_id(self) -> None:
        with self.assertRaises(ValueError) as raised:
            tool_generate_scene_from_prompt(
                {
                    "scene_id": "not_a_scene",
                    "project_name": "unit_bad_scene_id",
                    "prompt": "Generate a model.",
                    "parameters": {},
                    "dry_run": True,
                }
            )
        self.assertIn("scene_id", str(raised.exception))

    def test_generate_scene_from_prompt_requires_confirmation_for_missing_parameters(self) -> None:
        path = project_dir("unit_scene_prompt_needs_confirmation")
        if path.exists():
            shutil.rmtree(path)
        result = tool_generate_scene_from_prompt(
            {
                "project_name": "unit_scene_prompt_needs_confirmation",
                "prompt": "做一个钢筋自由落体冲击固定头盔的模型",
            }
        )
        self.assertFalse(result["ok"])
        self.assertTrue(result["needs_confirmation"])
        self.assertEqual(result["scene_template"], "rebar_drop_on_helmet")
        self.assertIn("rebar_length_m", result["missing_parameters"])
        self.assertFalse(path.exists())

    def test_generate_scene_from_prompt_requires_confirmation_for_missing_material(self) -> None:
        path = project_dir("unit_scene_prompt_missing_material")
        if path.exists():
            shutil.rmtree(path)
        result = tool_generate_scene_from_prompt(
            {
                "project_name": "unit_scene_prompt_missing_material",
                "prompt": "生成一根长0.5米半径20毫米的圆柱杆，以12m/s向下撞击固定板，板长0.8米宽0.6米厚4毫米",
            }
        )
        self.assertFalse(result["ok"])
        self.assertTrue(result["needs_confirmation"])
        self.assertEqual(result["scene_template"], "rod_impact_plate")
        self.assertIn("material_name", result["missing_parameters"])
        self.assertFalse(path.exists())

    def test_generate_scene_from_prompt_requires_confirmation_for_mixed_material_cues(self) -> None:
        path = project_dir("unit_scene_prompt_mixed_material")
        if path.exists():
            shutil.rmtree(path)
        result = tool_generate_scene_from_prompt(
            {
                "project_name": "unit_scene_prompt_mixed_material",
                "prompt": "生成一根长0.5米半径20毫米的铝杆，以12m/s向下撞击固定钢板，钢板长0.8米宽0.6米厚4毫米",
            }
        )
        self.assertFalse(result["ok"])
        self.assertTrue(result["needs_confirmation"])
        self.assertEqual(result["scene_template"], "rod_impact_plate")
        self.assertIn("material_name", result["missing_parameters"])
        self.assertFalse(path.exists())

    def test_generate_scene_from_prompt_rejects_ambiguous_material_even_with_defaults(self) -> None:
        path = project_dir("unit_scene_prompt_ambiguous_material_defaults")
        if path.exists():
            shutil.rmtree(path)
        result = tool_generate_scene_from_prompt(
            {
                "project_name": "unit_scene_prompt_ambiguous_material_defaults",
                "prompt": "生成一根长0.5米半径20毫米的铝杆，以12m/s向下撞击固定钢板，钢板长0.8米宽0.6米厚4毫米",
                "allow_defaults": True,
            }
        )
        self.assertFalse(result["ok"])
        self.assertTrue(result["needs_confirmation"])
        self.assertEqual(result["reason"], "ambiguous_material")
        self.assertIn("material_name", result["missing_parameters"])
        self.assertFalse(path.exists())

    def test_generate_scene_from_prompt_allows_explicit_material_for_ambiguous_prompt(self) -> None:
        path = project_dir("unit_scene_prompt_ambiguous_explicit_material")
        if path.exists():
            shutil.rmtree(path)
        try:
            result = tool_generate_scene_from_prompt(
                {
                    "project_name": "unit_scene_prompt_ambiguous_explicit_material",
                    "prompt": "生成一根长0.5米半径20毫米的铝杆，以12m/s向下撞击固定钢板，钢板长0.8米宽0.6米厚4毫米",
                    "parameters": {"material_name": "aluminum_6061_t6"},
                    "allow_defaults": True,
                }
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["resolved_parameters"]["material_name"], "aluminum_6061_t6")
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_generate_scene_from_prompt_dry_run_rejects_invalid_resolved_spec(self) -> None:
        path = project_dir("unit_scene_prompt_dry_run_bad_material")
        if path.exists():
            shutil.rmtree(path)
        with self.assertRaisesRegex(ValueError, "unknown material"):
            tool_generate_scene_from_prompt(
                {
                    "project_name": "unit_scene_prompt_dry_run_bad_material",
                    "prompt": "生成一根长0.5米半径20毫米的圆柱杆，以12m/s向下撞击固定钢板，钢板长0.8米宽0.6米厚4毫米",
                    "parameters": {"material_name": "not_in_library"},
                    "dry_run": True,
                }
            )
        self.assertFalse(path.exists())

    def test_generate_scene_from_prompt_can_use_explicit_overrides_and_validation_pipeline(self) -> None:
        path = project_dir("unit_scene_prompt_pipeline")
        if path.exists():
            shutil.rmtree(path)
        try:
            def fake_launch(project_path, cfile_path, timeout_s=None, allow_multiple=False):
                write_fake_lsprepost_outputs(project_path, cfile_path, payload=cfile_path.name.encode("utf-8"))
                return {"pid": 115, "mode": "cfile", "cfile_path": str(cfile_path), "timeout_s": timeout_s, "returncode": 0}

            with mock.patch(
                "lsprepost_mcp.tool_lsprepost.require_lsprepost_exe",
                return_value=Path("lsprepost4.12.exe"),
            ):
                with mock.patch("lsprepost_mcp.lspp.launcher.launch_cfile", side_effect=fake_launch) as launch:
                    result = tool_generate_scene_from_prompt(
                        {
                            "project_name": "unit_scene_prompt_pipeline",
                            "prompt": "钢筋从头盔上方自由落体撞击固定头盔",
                            "parameters": {
                                "rebar_length_m": 1.2,
                                "rebar_diameter_m": 0.03,
                                "drop_height_m": 8.0,
                                "impact_velocity_m_per_s": 10.0,
                            },
                            "run_lsprepost_validation": True,
                            "export_previews": True,
                            "timeout_s": 5,
                        }
                    )
            self.assertTrue(result["ok"])
            self.assertEqual(result["resolved_parameters"]["rebar_length_m"], 1.2)
            self.assertEqual(result["resolved_parameters"]["rebar_radius_m"], 0.015)
            self.assertTrue(result["lsprepost_import"]["ok"])
            self.assertTrue(result["preview_images"]["ok"])
            self.assertEqual(result["preview_images"]["count"], 4)
            self.assertEqual(launch.call_count, 5)
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_generate_scene_from_prompt_can_export_preview_gif(self) -> None:
        path = project_dir("unit_scene_prompt_gif_pipeline")
        if path.exists():
            shutil.rmtree(path)
        try:
            def fake_launch(project_path, cfile_path, timeout_s=None, allow_multiple=False):
                write_fake_lsprepost_image_outputs(project_path, cfile_path)
                return {"pid": 118, "mode": "cfile", "cfile_path": str(cfile_path), "timeout_s": timeout_s, "returncode": 0}

            with mock.patch("lsprepost_mcp.lspp.launcher.launch_cfile", side_effect=fake_launch) as launch:
                result = tool_generate_scene_from_prompt(
                    {
                        "project_name": "unit_scene_prompt_gif_pipeline",
                        "parameters": {"impact_velocity_m_per_s": 10.0},
                        "prompt": "生成一根1米长、半径12毫米的钢筋，从头盔上方10米自由落体，撞击固定在地面上的头盔",
                        "export_preview_gif": True,
                        "timeout_s": 5,
                    }
                )
            self.assertTrue(result["ok"])
            self.assertTrue(result["preview_gif"]["ok"])
            self.assertEqual(result["preview_gif"]["frame_count"], 3)
            self.assertEqual((path / "artifacts" / "preview_summary.gif").read_bytes()[:3], b"GIF")
            self.assertEqual(launch.call_count, 3)
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_generate_scene_from_prompt_dry_run_returns_resolved_spec_without_writing(self) -> None:
        path = project_dir("unit_scene_prompt_dry_run_rod_plate")
        if path.exists():
            shutil.rmtree(path)
        result = tool_generate_scene_from_prompt(
            {
                "project_name": "unit_scene_prompt_dry_run_rod_plate",
                "prompt": "生成一根长0.5米半径20毫米的圆柱杆，以12m/s向下撞击固定钢板，钢板长0.8米宽0.6米厚4毫米",
                "dry_run": True,
            }
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "resolved_only")
        self.assertEqual(result["scene_template"], "rod_impact_plate")
        self.assertFalse(path.exists())
        self.assertIn("resolved_spec", result)
        self.assertIn("risk_notes", result)
        self.assertIn("impact_contact", result["risk_notes"])

    def test_generate_scene_from_prompt_creates_rod_impact_plate_project(self) -> None:
        path = project_dir("unit_scene_prompt_rod_plate")
        if path.exists():
            shutil.rmtree(path)
        try:
            result = tool_generate_scene_from_prompt(
                {
                    "project_name": "unit_scene_prompt_rod_plate",
                    "prompt": "生成一根长0.5米半径20毫米的圆柱杆，以12m/s向下撞击固定钢板，钢板长0.8米宽0.6米厚4毫米",
                }
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["scene_template"], "rod_impact_plate")
            self.assertTrue(result["checks"]["readiness"]["ok_for_solver_draft"])
            model = read_json(path / "model.json")
            self.assertEqual(model["spec"]["geometry"]["scene"], "rod_impact_plate")
            self.assertEqual([item["id"] for item in model["spec"]["components"]], ["rod", "plate"])
            self.assertEqual(model["spec"]["contacts"][0]["type"], "automatic_surface_to_surface")
            self.assertEqual(model["spec"]["components"][0]["initial_velocity_m_per_s"], [0.0, 0.0, -12.0])
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_generate_scene_from_prompt_creates_cube_top_corner_load_project(self) -> None:
        path = project_dir("unit_scene_prompt_cube_corners")
        if path.exists():
            shutil.rmtree(path)
        try:
            result = tool_generate_scene_from_prompt(
                {
                    "project_name": "unit_scene_prompt_cube_corners",
                    "prompt": "生成2x2x2米低碳钢立方体，底面固定，顶面四个角向下各施加1000N载荷",
                }
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["scene_template"], "cube_top_corner_load")
            self.assertTrue(result["checks"]["ok"])
            model = read_json(path / "model.json")
            self.assertEqual(model["spec"]["model_type"], "solid_block")
            self.assertEqual(model["spec"]["geometry"], {"length_m": 2.0, "width_m": 2.0, "height_m": 2.0, "scene": "cube_top_corner_load"})
            self.assertEqual(
                model["spec"]["sets"][0]["selector"],
                {"type": "face_corners", "face": "z_max"},
            )
            self.assertEqual(model["spec"]["loads"][0]["value_n"], -1000.0)
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_generate_scene_from_prompt_creates_plate_pressure_project(self) -> None:
        path = project_dir("unit_scene_prompt_plate_pressure")
        if path.exists():
            shutil.rmtree(path)
        try:
            result = tool_generate_scene_from_prompt(
                {
                    "project_name": "unit_scene_prompt_plate_pressure",
                    "prompt": "生成长1米宽0.5米厚3毫米的钢板，左边固定，在板面施加20000Pa均布压力",
                }
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["scene_template"], "plate_pressure")
            self.assertTrue(result["checks"]["ok"])
            model = read_json(path / "model.json")
            self.assertEqual(model["spec"]["model_type"], "shell_plate")
            self.assertEqual(model["spec"]["sets"][0]["type"], "segment_set")
            self.assertEqual(model["spec"]["loads"][0]["type"], "pressure_on_segment_set")
            self.assertEqual(model["spec"]["loads"][0]["pressure_pa"], 20000.0)
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_create_plate_demo_refuses_existing_project_without_explicit_policy(self) -> None:
        path = project_dir("unit_plate_compat_policy")
        if path.exists():
            shutil.rmtree(path)
        try:
            first = tool_create_plate_demo({"project_name": "unit_plate_compat_policy"})
            self.assertEqual(first["project"], "unit_plate_compat_policy")
            with self.assertRaises(FileExistsError):
                tool_create_plate_demo({"project_name": "unit_plate_compat_policy"})
            second = tool_create_plate_demo({"project_name": "unit_plate_compat_policy", "if_exists": "versioned"})
            self.assertEqual(second["project"], "unit_plate_compat_policy_v2")
        finally:
            for target in [path, project_dir("unit_plate_compat_policy_v2")]:
                if target.exists():
                    shutil.rmtree(target)

    def test_open_in_lsprepost_refuses_project_that_is_not_gui_ready(self) -> None:
        path = project_dir("unit_invalid_gui_gate")
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
        try:
            (path / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")
            (path / "model.json").write_text(
                '{"schema_version":"0.2.0","spec":{"project_name":"unit_invalid_gui_gate","model_type":"shell_plate"},"metadata":{}}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "not ready for LS-PrePost GUI preview"):
                tool_open_in_lsprepost({"project_name": "unit_invalid_gui_gate"})
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_import_keyword_requires_allow_external_for_external_path(self) -> None:
        target = project_dir("unit_import_external")
        if target.exists():
            shutil.rmtree(target)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "external.k"
            source.write_text("*KEYWORD\n*END\n", encoding="utf-8")
            try:
                with self.assertRaisesRegex(ValueError, "allow_external"):
                    import_keyword_project("unit_import_external", str(source))
                result = import_keyword_project("unit_import_external", str(source), allow_external=True)
                self.assertTrue(result["metadata"]["source_is_external"])
            finally:
                if target.exists():
                    shutil.rmtree(target)

    def test_import_keyword_rejects_late_binary_nul(self) -> None:
        target = project_dir("unit_import_binary")
        if target.exists():
            shutil.rmtree(target)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "external.k"
            source.write_bytes(b"*KEYWORD\n" + b"$ filler\n" * 600 + b"\x00\n*END\n")
            try:
                with self.assertRaisesRegex(ValueError, "binary"):
                    import_keyword_project("unit_import_binary", str(source), allow_external=True)
            finally:
                if target.exists():
                    shutil.rmtree(target)

    def test_import_keyword_rejects_fake_keyword_first_card(self) -> None:
        target = project_dir("unit_import_fake_keyword")
        if target.exists():
            shutil.rmtree(target)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "external.k"
            source.write_text("*KEYWORD_NOT_REAL\n*END\n", encoding="utf-8")
            try:
                with self.assertRaisesRegex(ValueError, "must start with \\*KEYWORD"):
                    import_keyword_project("unit_import_fake_keyword", str(source), allow_external=True)
            finally:
                if target.exists():
                    shutil.rmtree(target)

    def test_import_keyword_rejects_include_fragments_for_complete_deck_import(self) -> None:
        target = project_dir("unit_import_inc")
        if target.exists():
            shutil.rmtree(target)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "part.inc"
            source.write_text("*PART\npart\n1,1,1\n", encoding="utf-8")
            try:
                with self.assertRaisesRegex(ValueError, "complete keyword deck"):
                    import_keyword_project("unit_import_inc", str(source), allow_external=True)
            finally:
                if target.exists():
                    shutil.rmtree(target)

    def test_hidden_temp_projects_are_not_listed_and_can_be_cleaned(self) -> None:
        hidden_unmarked = PROJECTS_DIR / ".unit_tmp_probe.tmp_20200101T000000Z"
        hidden_marked = PROJECTS_DIR / ".unit_tmp_probe.tmp_20200101T000001000000Z"
        for hidden in [hidden_unmarked, hidden_marked]:
            if hidden.exists():
                shutil.rmtree(hidden)
            hidden.mkdir(parents=True)
        try:
            (hidden_unmarked / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")
            (hidden_marked / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")
            (hidden_marked / RUNTIME_ARTIFACT_MARKER).write_text("unit test marker\n", encoding="utf-8")
            names = {record["project_name"] for record in iter_project_records()}
            self.assertNotIn(hidden_unmarked.name, names)
            self.assertNotIn(hidden_marked.name, names)
            result = cleanup_stale_project_artifacts(max_age_seconds=0)
            self.assertGreaterEqual(result["removed_count"], 1)
            self.assertTrue(hidden_unmarked.exists())
            self.assertFalse(hidden_marked.exists())
        finally:
            for hidden in [hidden_unmarked, hidden_marked]:
                if hidden.exists():
                    shutil.rmtree(hidden)

    def test_stale_project_cleanup_is_best_effort(self) -> None:
        hidden = PROJECTS_DIR / ".unit_tmp_probe.tmp_20200101T000002000000Z"
        if hidden.exists():
            shutil.rmtree(hidden)
        hidden.mkdir(parents=True)
        try:
            (hidden / RUNTIME_ARTIFACT_MARKER).write_text("unit test marker\n", encoding="utf-8")
            with mock.patch("lsprepost_mcp.project_store.shutil.rmtree", side_effect=PermissionError("locked")):
                result = cleanup_stale_project_artifacts(max_age_seconds=0)
            self.assertEqual(result["removed_count"], 0)
            self.assertEqual(result["error_count"], 1)
            self.assertTrue(hidden.exists())
        finally:
            if hidden.exists():
                shutil.rmtree(hidden)

    def test_artifact_paths_are_confined_to_project_artifacts(self) -> None:
        path = project_dir("unit_artifact_policy")
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
        try:
            target = artifact_path(path, "preview.png")
            self.assertEqual(target.parent, path / "artifacts")
            target.write_text("existing", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                artifact_path(path, "preview.png")
            with self.assertRaises(ValueError):
                artifact_path(path, "preview.png", if_exists="archive_then_write")
            versioned = artifact_path(path, "preview.png", if_exists="versioned")
            self.assertEqual(versioned.name, "preview_v2.png")
            absolute_like = "C:" + "\\escape.png"
            for bad in ["..\\escape.png", "../escape.png", absolute_like, "bad name.png"]:
                with self.subTest(bad=bad):
                    with self.assertRaises(ValueError):
                        artifact_path(path, bad)
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_cfile_templates_are_parameterized_and_path_checked(self) -> None:
        path = project_dir("unit_cfile_policy")
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
        try:
            text = render_cfile_template("open_keyword.cfile", {"keyword_path": "model.k"})
            self.assertIn("model.k", text)
            cfile = path / "open_model.cfile"
            write_server_cfile(path, "open_model.cfile", "open_keyword.cfile", {"keyword_path": "model.k"}, if_exists="overwrite")
            self.assertEqual(validate_server_cfile_path(path, cfile), cfile.resolve())
            with self.assertRaises(ValueError):
                validate_server_cfile_path(path, Path("C:/unsafe/run.cfile"))
            with self.assertRaises(ValueError):
                render_cfile_template("open_keyword.cfile", {"keyword_path": "model.k\"\nquit"})
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_result_stress_template_uses_fixed_von_mises_command(self) -> None:
        text = render_cfile_template(
            "result_stress.cfile",
            {
                "d3plot_path": "solver_runs/run_demo/d3plot",
                "output_path": "artifacts/result_stress.png",
                "view_command": "quat 0.880476 0.279848 0.364705 0.115917",
                "state_number": 22,
            },
        )

        self.assertIn('openc d3plot "solver_runs/run_demo/d3plot"', text)
        self.assertIn("state 22", text)
        self.assertIn("fringe 9", text)
        self.assertIn('print png "artifacts/result_stress.png"', text)

        filtered = render_cfile_template(
            "result_stress.cfile",
            {
                "d3plot_path": "solver_runs/run_demo/d3plot",
                "output_path": "artifacts/result_stress.png",
                "view_command": "isometric",
                "state_number": 18,
                "display_commands": "partdata readlist 1 2\nclearid part\nhide",
            },
        )
        self.assertIn("partdata readlist 1 2\nclearid part\nhide\nstate 18", filtered)

        with self.assertRaisesRegex(ValueError, "state_number"):
            render_cfile_template(
                "result_stress.cfile",
                {
                    "d3plot_path": "solver_runs/run_demo/d3plot",
                    "output_path": "artifacts/result_stress.png",
                    "view_command": "",
                    "state_number": "22;quit",
                },
            )

    def test_result_pressure_templates_use_fixed_pressure_command(self) -> None:
        params = {
            "d3plot_path": "solver_runs/run_demo/d3plot",
            "output_path": "artifacts/result_pressure.png",
            "view_command": "isometric",
            "state_number": 14,
            "display_commands": "-m 1:2\n-m 4\n+m 3",
        }
        screenshot = render_cfile_template("result_pressure.cfile", params)

        self.assertIn("state 14", screenshot)
        self.assertIn("fringe 8", screenshot)
        self.assertNotIn("fringe 9", screenshot)
        self.assertIn("-m 1:2\n-m 4\n+m 3", screenshot)
        self.assertIn('print png "artifacts/result_pressure.png"', screenshot)

        interactive_params = dict(params)
        interactive_params.pop("output_path")
        interactive = render_cfile_template("open_result_pressure.cfile", interactive_params)
        self.assertIn("state 14", interactive)
        self.assertIn("fringe 8", interactive)
        self.assertNotIn("fringe 9", interactive)
        self.assertIn("interactive", interactive)
        self.assertNotIn("print png", interactive)
        self.assertNotIn("\nexit", interactive)

    def test_open_result_stress_template_uses_fixed_von_mises_command(self) -> None:
        text = render_cfile_template(
            "open_result_stress.cfile",
            {
                "d3plot_path": "solver_runs/run_demo/d3plot",
                "view_command": "isometric",
                "state_number": 75,
                "display_commands": "-m 1:2\n-m 4\n+m 3",
            },
        )

        self.assertIn("state 75", text)
        self.assertIn("fringe 9", text)
        self.assertIn("interactive", text)
        self.assertNotIn("print png", text)
        self.assertNotIn("\nexit", text)

    def test_root_open_model_cfile_must_be_manifested_and_hash_matched(self) -> None:
        path = project_dir("unit_root_cfile_manifest_policy")
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
        try:
            cfile = path / "open_model.cfile"
            cfile.write_text("ac\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_server_cfile_path(path, cfile)
            write_server_cfile(path, "open_model.cfile", "open_keyword.cfile", {"keyword_path": "model.k"}, if_exists="overwrite")
            self.assertEqual(validate_server_cfile_path(path, cfile), cfile.resolve())
            manifest = read_cfile_manifest(path)
            self.assertNotIn("path", manifest[0])
            self.assertEqual(manifest[0]["relative_path"], "open_model.cfile")
            cfile.write_text("quit\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_server_cfile_path(path, cfile)
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_register_server_cfile_rejects_unknown_template_name(self) -> None:
        path = project_dir("unit_cfile_template_name_policy")
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
        try:
            cfile = path / "open_model.cfile"
            cfile.write_text("ac\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                register_server_cfile(path, cfile, "custom.cfile", {})
            with self.assertRaises(ValueError):
                register_server_cfile(path, cfile, "open_keyword.cfile", {"keyword_path": "model.k"})
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_artifact_cfile_must_be_manifested_and_hash_matched(self) -> None:
        path = project_dir("unit_cfile_manifest_policy")
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
        try:
            artifact = path / "artifacts" / "preview.cfile"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("ac\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_server_cfile_path(path, artifact)
            write_server_cfile(
                path,
                "preview.cfile",
                "preview_image.cfile",
                {"keyword_path": "model.k", "output_path": "preview.png"},
                if_exists="overwrite",
            )
            self.assertEqual(validate_server_cfile_path(path, artifact), artifact.resolve())
            artifact.write_text("quit\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_server_cfile_path(path, artifact)
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_cfile_template_rejects_unknown_params(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported cfile template parameter"):
            render_cfile_template("open_keyword.cfile", {"keyword_path": "model.k", "extra": "ignored"})

    def test_lsprepost_doctor_checks_executable_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "lsprepost4.12.exe"
            good.write_text("", encoding="utf-8")
            bad = Path(tmp) / "not_lspp.txt"
            bad.write_text("", encoding="utf-8")
            self.assertTrue(doctor_lsprepost_exe(good).ok)
            self.assertFalse(doctor_lsprepost_exe(bad).ok)

    def test_launcher_restricts_keyword_path_to_project(self) -> None:
        path = project_dir("unit_keyword_path_policy")
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
        try:
            keyword = path / "model.k"
            keyword.write_text("*KEYWORD\n*END\n", encoding="utf-8")
            self.assertEqual(validate_keyword_path(path, keyword), keyword.resolve())
            bad_suffix = path / "model.txt"
            bad_suffix.write_text("*KEYWORD\n*END\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_keyword_path(path, bad_suffix)
            with tempfile.TemporaryDirectory() as tmp:
                external = Path(tmp) / "external.k"
                external.write_text("*KEYWORD\n*END\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    validate_keyword_path(path, external)
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_launcher_accepts_only_sealed_solver_run_d3plot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "phase15_result"
            run_dir = project / "solver_runs" / "run_unit"
            run_dir.mkdir(parents=True)
            for name, payload in (
                ("model.k", b"*KEYWORD\n*END\n"),
                ("model.json", b"{}\n"),
                ("d3hsp", b"normal termination\n"),
                ("d3plot", b"d3plot-data"),
                ("elout", b"elout-data"),
                ("nodout", b"nodout-data"),
            ):
                (run_dir / name).write_bytes(payload)
            evidence = seal_phase14_run_evidence(
                run_dir,
                required_output_prefixes=("d3hsp", "d3plot", "elout", "nodout"),
            )
            record = {
                "ok": True,
                "status": "completed",
                "run_id": "run_unit",
                "input_sha256": hashlib.sha256(
                    (run_dir / "model.k").read_bytes()
                ).hexdigest(),
                "model_json_sha256": hashlib.sha256(
                    (run_dir / "model.json").read_bytes()
                ).hexdigest(),
                "required_outputs": ["d3hsp", "d3plot", "elout", "nodout"],
                "evidence_manifest": evidence,
                "evidence_manifest_sha256": evidence["sha256"],
            }
            (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")

            self.assertEqual(
                run_dir / "d3plot",
                validate_d3plot_path(project, run_dir / "d3plot"),
            )
            project_root_result = project / "d3plot"
            project_root_result.write_bytes(b"not-controlled")
            with self.assertRaises(ValueError):
                validate_d3plot_path(project, project_root_result)
            arbitrary = run_dir / "result.bin"
            arbitrary.write_bytes(b"not-d3plot")
            with self.assertRaises(ValueError):
                validate_d3plot_path(project, arbitrary)
            with self.assertRaises(ValueError):
                validate_d3plot_path(project, run_dir)

            (run_dir / "d3plot").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "evidence"):
                validate_d3plot_path(project, run_dir / "d3plot")

    def test_launch_d3plot_uses_immutable_result_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "phase15_result"
            run_dir = project / "solver_runs" / "run_unit"
            run_dir.mkdir(parents=True)
            for name, payload in (
                ("model.k", b"*KEYWORD\n*END\n"),
                ("model.json", b"{}\n"),
                ("d3hsp", b"normal termination\n"),
                ("d3plot", b"d3plot-data"),
                ("elout", b"elout-data"),
                ("nodout", b"nodout-data"),
            ):
                (run_dir / name).write_bytes(payload)
            evidence = seal_phase14_run_evidence(
                run_dir,
                required_output_prefixes=("d3hsp", "d3plot", "elout", "nodout"),
            )
            record = {
                "ok": True,
                "status": "completed",
                "run_id": "run_unit",
                "input_sha256": hashlib.sha256(
                    (run_dir / "model.k").read_bytes()
                ).hexdigest(),
                "model_json_sha256": hashlib.sha256(
                    (run_dir / "model.json").read_bytes()
                ).hexdigest(),
                "required_outputs": ["d3hsp", "d3plot", "elout", "nodout"],
                "evidence_manifest": evidence,
                "evidence_manifest_sha256": evidence["sha256"],
            }
            (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")

            class RunningProc:
                pid = 6789

                def wait(self, timeout):
                    raise subprocess.TimeoutExpired("lsprepost", timeout)

            exe = Path(temp_dir) / "lsprepost4.12.exe"
            exe.write_bytes(b"fake")
            with (
                mock.patch(
                    "lsprepost_mcp.lspp.launcher.require_lsprepost_exe",
                    return_value=exe,
                ),
                mock.patch(
                    "lsprepost_mcp.lspp.launcher.process_info",
                    return_value=None,
                ),
                mock.patch(
                    "lsprepost_mcp.lspp.launcher.subprocess.Popen",
                    return_value=RunningProc(),
                ) as popen,
            ):
                launch = launch_d3plot(project, run_dir / "d3plot")

            self.assertEqual("d3plot_result", launch["mode"])
            self.assertEqual(str(run_dir / "d3plot"), launch["d3plot_path"])
            self.assertEqual([str(exe), str(run_dir / "d3plot")], popen.call_args.args[0])

    def test_open_result_tool_selects_latest_qualified_run(self) -> None:
        project = project_dir("unit_open_result_lsprepost")
        if project.exists():
            shutil.rmtree(project)
        run_dir = project / "solver_runs" / "run_20260726T000000000000Z_unit"
        run_dir.mkdir(parents=True)
        try:
            for name, payload in (
                ("model.k", b"*KEYWORD\n*END\n"),
                ("model.json", b"{}\n"),
                ("d3hsp", b"normal termination\n"),
                ("d3plot", b"d3plot-data"),
                ("elout", b"elout-data"),
                ("nodout", b"nodout-data"),
            ):
                (run_dir / name).write_bytes(payload)
            evidence = seal_phase14_run_evidence(
                run_dir,
                required_output_prefixes=("d3hsp", "d3plot", "elout", "nodout"),
            )
            record = {
                "ok": True,
                "status": "completed",
                "run_id": run_dir.name,
                "input_sha256": hashlib.sha256(
                    (run_dir / "model.k").read_bytes()
                ).hexdigest(),
                "model_json_sha256": hashlib.sha256(
                    (run_dir / "model.json").read_bytes()
                ).hexdigest(),
                "required_outputs": ["d3hsp", "d3plot", "elout", "nodout"],
                "evidence_manifest": evidence,
                "evidence_manifest_sha256": evidence["sha256"],
            }
            (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
            launch_record = {"pid": 7654, "mode": "d3plot_result"}

            with mock.patch(
                "lsprepost_mcp.lspp.launcher.launch_d3plot",
                return_value=launch_record,
            ) as launch:
                result = tool_open_result_lsprepost(
                    {"project_name": project.name}
                )

            self.assertTrue(result["ok"])
            self.assertEqual(run_dir.name, result["run_id"])
            self.assertEqual(str(run_dir / "d3plot"), result["d3plot_path"])
            launch.assert_called_once_with(
                project,
                run_dir / "d3plot",
                timeout_s=None,
            )
        finally:
            if project.exists():
                shutil.rmtree(project)

    def test_lsprepost_running_process_records_are_detected(self) -> None:
        path = project_dir("unit_lspp_process_record")
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
        try:
            record_process(
                path,
                {
                    "pid": 12345,
                    "mode": "keyword_preview",
                    "exe_name": "lsprepost4.12.exe",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "process_identity_confidence": "weak",
                    "runtime_identity_incomplete": True,
                },
            )
            with mock.patch(
                "lsprepost_mcp.lspp.launcher.process_info",
                return_value={"pid": 12345, "image_name": "lsprepost4.12.exe", "identity_source": "tasklist"},
            ):
                self.assertEqual(len(running_project_processes(path)), 1)
            with mock.patch("lsprepost_mcp.lspp.launcher.process_info", return_value=None):
                self.assertEqual(running_project_processes(path), [])
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_launch_cfile_executes_snapshot_not_mutable_source(self) -> None:
        path = project_dir("unit_launch_cfile_snapshot")
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
        try:
            cfile, _ = write_server_cfile(
                path,
                "preview.cfile",
                "preview_image.cfile",
                {"keyword_path": "model.k", "output_path": "preview.png"},
            )

            class FakeProc:
                pid = 23456

                def wait(self, timeout=None):
                    self.returncode = 0
                    return 0

            with mock.patch("lsprepost_mcp.lspp.launcher.require_lsprepost_exe", return_value=Path("lsprepost4.12.exe")):
                with mock.patch("lsprepost_mcp.lspp.launcher.process_info", return_value=None):
                    with mock.patch("lsprepost_mcp.lspp.launcher.subprocess.Popen", return_value=FakeProc()) as popen:
                        record = launch_cfile(path, cfile, timeout_s=None)
            command = popen.call_args.args[0]
            self.assertIn("c=", command[1])
            self.assertNotEqual(command[1], f"c={cfile.resolve()}")
            self.assertIn("cfile_snapshot_path", record)
            self.assertTrue(Path(record["cfile_snapshot_path"]).exists())
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_async_keyword_launch_requires_process_to_survive_startup_probe(self) -> None:
        path = project_dir("unit_keyword_startup_probe")
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
        (path / "model.k").write_text("*KEYWORD\n*END\n", encoding="utf-8")

        class RunningProc:
            pid = 34567
            returncode = None

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired("lsprepost4.12.exe", timeout)

        class ExitedProc:
            pid = 34568
            returncode = 3

            def wait(self, timeout=None):
                return self.returncode

        try:
            common_patches = (
                mock.patch(
                    "lsprepost_mcp.lspp.launcher.require_lsprepost_exe",
                    return_value=Path("lsprepost4.12.exe"),
                ),
                mock.patch("lsprepost_mcp.lspp.launcher.process_info", return_value=None),
            )
            with common_patches[0], common_patches[1]:
                with mock.patch(
                    "lsprepost_mcp.lspp.launcher.subprocess.Popen",
                    return_value=RunningProc(),
                ):
                    record = launch_keyword(path, path / "model.k", timeout_s=None)
            self.assertEqual(record["status"], "started")
            self.assertTrue(record["process_running"])

            with mock.patch(
                "lsprepost_mcp.lspp.launcher.require_lsprepost_exe",
                return_value=Path("lsprepost4.12.exe"),
            ), mock.patch(
                "lsprepost_mcp.lspp.launcher.process_info",
                return_value=None,
            ), mock.patch(
                "lsprepost_mcp.lspp.launcher.subprocess.Popen",
                return_value=ExitedProc(),
            ):
                with self.assertRaisesRegex(RuntimeError, "exited during startup"):
                    launch_keyword(path, path / "model.k", timeout_s=None)
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_launch_cfile_prunes_old_snapshots(self) -> None:
        path = project_dir("unit_launch_cfile_snapshot_prune")
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
        try:
            snapshots = path / "artifacts" / "cfile_snapshots"
            snapshots.mkdir(parents=True)
            for index in range(60):
                item = snapshots / f"old_{index}.cfile"
                item.write_text("old\n", encoding="utf-8")
            cfile, _ = write_server_cfile(
                path,
                "preview.cfile",
                "preview_image.cfile",
                {"keyword_path": "model.k", "output_path": "preview.png"},
            )

            class FakeProc:
                pid = 23457

            with mock.patch("lsprepost_mcp.lspp.launcher.require_lsprepost_exe", return_value=Path("lsprepost4.12.exe")):
                with mock.patch("lsprepost_mcp.lspp.launcher.process_info", return_value=None):
                    with mock.patch("lsprepost_mcp.lspp.launcher.subprocess.Popen", return_value=FakeProc()):
                        launch_cfile(path, cfile, timeout_s=None)
            self.assertLessEqual(len(list(snapshots.glob("*.cfile"))), 50)
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_snapshot_cleanup_preserves_active_references(self) -> None:
        path = project_dir("unit_snapshot_active_reference")
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
        try:
            snapshots = path / "artifacts" / "cfile_snapshots"
            snapshots.mkdir(parents=True)
            active = snapshots / "active_old.cfile"
            active.write_text("active\n", encoding="utf-8")
            for index in range(60):
                item = snapshots / f"old_{index}.cfile"
                item.write_text("old\n", encoding="utf-8")
            record_process(
                path,
                {
                    "pid": 23458,
                    "mode": "cfile",
                    "exe_name": "lsprepost4.12.exe",
                    "cfile_snapshot_path": str(active),
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "process_identity_confidence": "weak",
                    "runtime_identity_incomplete": True,
                },
            )
            self.assertIn(active.resolve(), active_cfile_snapshot_paths(path))
            cleanup_cfile_snapshots(path, keep=5)
            self.assertTrue(active.exists())
            self.assertLessEqual(len([item for item in snapshots.glob("*.cfile") if item.name.startswith("old_")]), 5)
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_process_detection_rejects_reused_pid_with_different_creation_time(self) -> None:
        lspp_exe = "C:" + "\\LS\\lsprepost4.12.exe"
        keyword_path = "C:" + "\\models\\model.k"
        record = {
            "pid": 12345,
            "mode": "keyword_preview",
            "exe_name": "lsprepost4.12.exe",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "process_creation_date": "old",
            "process_executable_path": lspp_exe,
            "keyword_path": keyword_path,
        }
        info = {
            "pid": 12345,
            "image_name": "lsprepost4.12.exe",
            "creation_date": "new",
            "executable_path": lspp_exe,
            "command_line": f'"{lspp_exe}" k={keyword_path}',
        }
        with mock.patch("lsprepost_mcp.lspp.launcher.process_info", return_value=info):
            self.assertFalse(process_matches_record(12345, record))

    def test_process_detection_tasklist_fallback_blocks_by_pid_and_image_name(self) -> None:
        lspp_exe = "C:" + "\\LS\\lsprepost4.12.exe"
        keyword_path = "C:" + "\\models\\model.k"
        record = {
            "pid": 12345,
            "mode": "keyword_preview",
            "exe_name": "lsprepost4.12.exe",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "process_creation_date": "old",
            "process_executable_path": lspp_exe,
            "keyword_path": keyword_path,
        }
        info = {"pid": 12345, "image_name": "lsprepost4.12.exe", "identity_source": "tasklist"}
        with mock.patch("lsprepost_mcp.lspp.launcher.process_info", return_value=info):
            self.assertTrue(process_matches_record(12345, record))

    def test_weak_process_identity_expires_after_ttl(self) -> None:
        record = {
            "pid": 12345,
            "mode": "keyword_preview",
            "exe_name": "lsprepost4.12.exe",
            "started_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
            "process_identity_confidence": "weak",
            "runtime_identity_incomplete": True,
        }
        info = {"pid": 12345, "image_name": "lsprepost4.12.exe", "identity_source": "tasklist"}
        with mock.patch("lsprepost_mcp.lspp.launcher.process_info", return_value=info):
            self.assertFalse(process_matches_record(12345, record))

    def test_weak_process_identity_fail_closed_ignores_ttl(self) -> None:
        record = {
            "pid": 12345,
            "mode": "keyword_preview",
            "exe_name": "lsprepost4.12.exe",
            "started_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
            "process_identity_confidence": "weak",
            "runtime_identity_incomplete": True,
        }
        info = {"pid": 12345, "image_name": "lsprepost4.12.exe", "identity_source": "tasklist"}
        with mock.patch("lsprepost_mcp.lspp.launcher.process_info", return_value=info):
            self.assertTrue(process_matches_record(12345, record, fail_closed=True))

    def test_lsprepost_process_detection_uses_exact_pid_csv_column(self) -> None:
        result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='"lsprepost4.12.exe","1234","Console","1","100 K"\n',
        )
        with mock.patch("lsprepost_mcp.lspp.launcher.subprocess.run", return_value=result):
            self.assertFalse(is_process_running(123))
            self.assertTrue(is_process_running(1234))

    def test_process_records_are_compacted(self) -> None:
        path = project_dir("unit_lspp_process_compact")
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
        try:
            for index in range(205):
                record_process(path, {"pid": index + 1, "mode": "keyword_preview", "exe_name": "lsprepost4.12.exe", "returncode": 0})
            records = (path / "artifacts" / "lspp_processes.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(records), 200)
            self.assertIn('"pid": 6', records[0])
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_process_record_compaction_preserves_active_records(self) -> None:
        records = [{"pid": 1, "mode": "keyword_preview", "exe_name": "lsprepost4.12.exe"}]
        records.extend({"pid": index + 2, "returncode": 0} for index in range(250))
        compacted = compact_process_records(records, limit=10)
        self.assertIn(records[0], compacted)
        self.assertEqual(len(compacted), 10)

    def test_project_lock_reclaims_stale_lock(self) -> None:
        name = "unit_stale_lock"
        lock_path = ProjectLock(name).path
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text('{"pid":999999,"created_at":1,"hostname":"unit"}', encoding="utf-8")
        try:
            with ProjectLock(name, timeout_s=1, stale_after_s=0) as lock:
                self.assertTrue(lock.diagnostics)
            self.assertFalse(lock_path.exists())
        finally:
            if lock_path.exists():
                lock_path.unlink()

    def test_project_lock_does_not_reclaim_old_live_pid_lock(self) -> None:
        name = "unit_live_old_lock"
        lock_path = ProjectLock(name).path
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            '{"pid":12345,"created_at":1,"hostname":"' + __import__("socket").gethostname() + '","token":"old"}',
            encoding="utf-8",
        )
        try:
            with mock.patch("lsprepost_mcp.locks.is_pid_alive", return_value=True):
                with self.assertRaises(TimeoutError):
                    with ProjectLock(name, timeout_s=0.01, poll_s=0.001, stale_after_s=0):
                        pass
            self.assertTrue(lock_path.exists())
        finally:
            if lock_path.exists():
                lock_path.unlink()

    def test_project_lock_release_does_not_unlink_replaced_lock(self) -> None:
        name = "unit_lock_token_release"
        lock_path = ProjectLock(name).path
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with ProjectLock(name, timeout_s=1) as lock:
            lock_path.write_text('{"pid":777,"created_at":1,"hostname":"unit","token":"replacement"}', encoding="utf-8")
        self.assertTrue(lock_path.exists())
        lock_path.unlink()

    def test_project_lock_release_retries_transient_windows_sharing_error(self) -> None:
        name = "unit_lock_release_retry"
        lock_path = ProjectLock(name).path
        try:
            with mock.patch.object(Path, "unlink", side_effect=[PermissionError("sharing violation"), None]) as unlink:
                with ProjectLock(name, timeout_s=1):
                    pass
            self.assertEqual(unlink.call_count, 2)
        finally:
            if lock_path.exists():
                lock_path.unlink()

    def test_project_overwrite_rejects_active_lsprepost_runtime(self) -> None:
        path = project_dir("unit_runtime_blocker")
        if path.exists():
            shutil.rmtree(path)
        try:
            spec = parse_model_spec(default_model_spec("unit_runtime_blocker", "shell_plate"))
            write_model_project(spec)
            record_process(
                path,
                {
                    "pid": 34567,
                    "mode": "keyword_preview",
                    "exe_name": "lsprepost4.12.exe",
                    "started_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
                    "process_identity_confidence": "weak",
                    "runtime_identity_incomplete": True,
                },
            )
            with mock.patch(
                "lsprepost_mcp.lspp.launcher.process_info",
                return_value={"pid": 34567, "image_name": "lsprepost4.12.exe", "identity_source": "tasklist"},
            ):
                with self.assertRaisesRegex(RuntimeError, "active LS-PrePost runtime"):
                    write_model_project(spec, if_exists="overwrite")
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_archive_project_rejects_active_lsprepost_runtime(self) -> None:
        path = project_dir("unit_runtime_archive_blocker")
        if path.exists():
            shutil.rmtree(path)
        try:
            spec = parse_model_spec(default_model_spec("unit_runtime_archive_blocker", "shell_plate"))
            write_model_project(spec)
            record_process(
                path,
                {
                    "pid": 45678,
                    "mode": "keyword_preview",
                    "exe_name": "lsprepost4.12.exe",
                    "started_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
                    "process_identity_confidence": "weak",
                    "runtime_identity_incomplete": True,
                },
            )
            with mock.patch(
                "lsprepost_mcp.lspp.launcher.process_info",
                return_value={"pid": 45678, "image_name": "lsprepost4.12.exe", "identity_source": "tasklist"},
            ):
                with self.assertRaisesRegex(RuntimeError, "active LS-PrePost runtime"):
                    archive_project("unit_runtime_archive_blocker", "unit_runtime_archive_blocker")
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_open_in_lsprepost_requires_ack_for_allow_multiple(self) -> None:
        with self.assertRaisesRegex(ValueError, "allow_multiple requires manual_ack"):
            tool_open_in_lsprepost({"project_name": "missing_project", "allow_multiple": True})

    def test_open_in_lsprepost_rejects_excessive_timeout(self) -> None:
        with self.assertRaisesRegex(ValueError, "timeout_s must be between"):
            tool_open_in_lsprepost({"project_name": "missing_project", "timeout_s": 301})

    def test_export_preview_image_uses_server_cfile_and_verifies_png(self) -> None:
        path = project_dir("unit_export_preview_tool")
        if path.exists():
            shutil.rmtree(path)
        try:
            write_model_project(parse_model_spec(default_model_spec("unit_export_preview_tool", "shell_plate")))

            def fake_launch(project_path, cfile_path, timeout_s=None, allow_multiple=False):
                write_fake_lsprepost_outputs(project_path, cfile_path)
                return {"pid": 111, "mode": "cfile", "cfile_path": str(cfile_path), "timeout_s": timeout_s}

            launch = mock.Mock(side_effect=fake_launch)
            with mock.patch("lsprepost_mcp.lspp.launcher.launch_cfile", side_effect=AssertionError("default launcher must not run")):
                result = tool_export_preview_image(
                    {
                        "project_name": "unit_export_preview_tool",
                        "timeout_s": 5,
                        "view": "top",
                        "display_mode": "loads_constraints",
                    },
                    launcher=SimpleNamespace(launch_cfile=launch),
                )
            self.assertTrue(result["ok"])
            self.assertEqual(result["view"], "top")
            self.assertEqual(result["display_controls"]["display_mode"], "loads_constraints")
            self.assertTrue(result["verification"]["png_signature_ok"])
            self.assertTrue(result["keyword_reader"]["ok"])
            self.assertTrue((path / "artifacts" / "preview_preview.cfile").exists())
            cfile_text = (path / "artifacts" / "preview_preview.cfile").read_text(encoding="utf-8")
            self.assertIn("quat 1 0 0 0", cfile_text)
            self.assertIn("displayentity Load Body on all", cfile_text)
            self.assertIn("save kwdmsg", cfile_text)
            self.assertTrue((path / "artifacts" / "lspp_verifications.json").exists())
            launch.assert_called_once()
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_export_preview_image_open_model_name_does_not_replace_root_cfile(self) -> None:
        path = project_dir("unit_export_preview_open_model_collision")
        if path.exists():
            shutil.rmtree(path)
        try:
            write_model_project(parse_model_spec(default_model_spec("unit_export_preview_open_model_collision", "shell_plate")))
            root_cfile = path / "open_model.cfile"
            root_before = root_cfile.read_text(encoding="utf-8")
            manifest_before = {
                entry["relative_path"]: entry
                for entry in read_cfile_manifest(path)
                if "relative_path" in entry
            }

            def fake_launch(project_path, cfile_path, timeout_s=None, allow_multiple=False):
                write_fake_lsprepost_outputs(project_path, cfile_path)
                return {"pid": 112, "mode": "cfile", "cfile_path": str(cfile_path), "timeout_s": timeout_s}

            with mock.patch("lsprepost_mcp.lspp.launcher.launch_cfile", side_effect=fake_launch):
                result = tool_export_preview_image(
                    {
                        "project_name": "unit_export_preview_open_model_collision",
                        "output_filename": "open_model.png",
                        "timeout_s": 5,
                    }
                )
            manifest_after = {
                entry["relative_path"]: entry
                for entry in read_cfile_manifest(path)
                if "relative_path" in entry
            }
            self.assertTrue(result["ok"])
            self.assertEqual(root_cfile.read_text(encoding="utf-8"), root_before)
            self.assertEqual(manifest_after["open_model.cfile"], manifest_before["open_model.cfile"])
            self.assertTrue((path / "artifacts" / "preview_open_model.cfile").exists())
            self.assertEqual(result["cfile_manifest"]["relative_path"], "artifacts\\preview_open_model.cfile")
            self.assertEqual(result["cfile_manifest"]["params"]["kwdmsg_path"], "artifacts/keyword_reader_messages_open_model.xml")
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_export_preview_images_exports_multiple_controlled_views(self) -> None:
        path = project_dir("unit_export_preview_batch_tool")
        if path.exists():
            shutil.rmtree(path)
        try:
            write_model_project(parse_model_spec(default_model_spec("unit_export_preview_batch_tool", "shell_plate")))

            def fake_launch(project_path, cfile_path, timeout_s=None, allow_multiple=False):
                write_fake_lsprepost_outputs(project_path, cfile_path, payload=cfile_path.name.encode("utf-8"))
                return {"pid": 113, "mode": "cfile", "cfile_path": str(cfile_path), "timeout_s": timeout_s}

            launch = mock.Mock(side_effect=fake_launch)
            with mock.patch("lsprepost_mcp.lspp.launcher.launch_cfile", side_effect=AssertionError("default launcher must not run")):
                result = tool_export_preview_images(
                    {
                        "project_name": "unit_export_preview_batch_tool",
                        "views": ["iso", "top"],
                        "output_prefix": "case",
                        "display_mode": "validation",
                        "timeout_s": 5,
                    },
                    launcher=SimpleNamespace(launch_cfile=launch),
                )
            self.assertTrue(result["ok"])
            self.assertEqual(result["views"], ["iso", "top"])
            self.assertEqual(result["display_mode"], "validation")
            self.assertEqual(result["count"], 2)
            self.assertEqual([item["view"] for item in result["results"]], ["iso", "top"])
            self.assertTrue((path / "artifacts" / "case_iso.png").exists())
            self.assertTrue((path / "artifacts" / "case_top.png").exists())
            self.assertTrue((path / "artifacts" / "keyword_reader_messages_case_iso.xml").exists())
            self.assertTrue((path / "artifacts" / "keyword_reader_messages_case_top.xml").exists())
            self.assertEqual(launch.call_count, 2)
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_export_preview_gif_combines_three_views(self) -> None:
        path = project_dir("unit_export_preview_gif_tool")
        if path.exists():
            shutil.rmtree(path)
        try:
            write_model_project(parse_model_spec(default_model_spec("unit_export_preview_gif_tool", "shell_plate")))

            def fake_launch(project_path, cfile_path, timeout_s=None, allow_multiple=False):
                write_fake_lsprepost_image_outputs(project_path, cfile_path)
                return {"pid": 117, "mode": "cfile", "cfile_path": str(cfile_path), "timeout_s": timeout_s, "returncode": 0}

            with mock.patch("lsprepost_mcp.lspp.launcher.launch_cfile", side_effect=fake_launch) as launch:
                result = tool_export_preview_gif(
                    {
                        "project_name": "unit_export_preview_gif_tool",
                        "views": ["iso", "top", "front"],
                        "output_filename": "summary.gif",
                        "duration_ms": 250,
                        "timeout_s": 5,
                    }
                )
            self.assertTrue(result["ok"])
            self.assertEqual(result["views"], ["iso", "top", "front"])
            self.assertEqual(result["frame_count"], 3)
            self.assertEqual(result["duration_ms"], 250)
            self.assertTrue(result["verification"]["gif_signature_ok"])
            self.assertEqual((path / "artifacts" / "summary.gif").read_bytes()[:3], b"GIF")
            self.assertTrue((path / "artifacts" / "preview_iso.png").exists())
            self.assertEqual(launch.call_count, 3)
            records = read_json(path / "artifacts" / "lspp_verifications.json")["verifications"]
            self.assertEqual(records[-1]["action"], "export_preview_gif")
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_validate_lsprepost_import_runs_preview_and_required_keyword_checks(self) -> None:
        path = project_dir("unit_validate_lsprepost_import")
        if path.exists():
            shutil.rmtree(path)
        try:
            write_model_project(parse_model_spec(rebar_drop_on_helmet_spec("unit_validate_lsprepost_import")))

            def fake_launch(project_path, cfile_path, timeout_s=None, allow_multiple=False):
                write_fake_lsprepost_outputs(project_path, cfile_path)
                return {"pid": 114, "mode": "cfile", "cfile_path": str(cfile_path), "timeout_s": timeout_s, "returncode": 0}

            with (
                mock.patch(
                    "lsprepost_mcp.tool_lsprepost.require_lsprepost_exe",
                    return_value=Path("lsprepost.exe"),
                ),
                mock.patch(
                    "lsprepost_mcp.lspp.launcher.launch_cfile",
                    side_effect=fake_launch,
                ) as launch,
            ):
                result = tool_validate_lsprepost_import({"project_name": "unit_validate_lsprepost_import", "timeout_s": 5})
            self.assertTrue(result["ok"])
            self.assertTrue(result["validation"]["static_checks_ok"])
            self.assertTrue(result["validation"]["keyword_reader_ok"])
            self.assertTrue(result["validation"]["preview_png_ok"])
            self.assertTrue(result["validation"]["required_keywords"]["ok"])
            self.assertEqual(result["display_controls"]["display_mode"], "validation")
            self.assertTrue((path / "artifacts" / "import_validation_iso.png").exists())
            self.assertTrue((path / "artifacts" / "lspp_verifications.json").exists())
            launch.assert_called_once()
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_validate_lsprepost_import_checks_executable_before_project_validation(self) -> None:
        with (
            mock.patch(
                "lsprepost_mcp.tool_lsprepost.require_lsprepost_exe",
                side_effect=FileNotFoundError("invalid LS-PrePost executable"),
            ),
            mock.patch(
                "lsprepost_mcp.tool_lsprepost.validate_project_files",
            ) as validate_project,
        ):
            with self.assertRaisesRegex(FileNotFoundError, "invalid LS-PrePost"):
                tool_validate_lsprepost_import(
                    {
                        "project_name": "web_phase17_city_street_blast",
                        "timeout_s": 5,
                    }
                )

        validate_project.assert_not_called()

    def test_export_preview_image_rejects_unknown_view(self) -> None:
        with self.assertRaisesRegex(ValueError, "view must be one of"):
            tool_export_preview_image({"project_name": "missing_project", "view": "diagonal"})
        with self.assertRaisesRegex(ValueError, "duplicate preview view"):
            tool_export_preview_images({"project_name": "missing_project", "views": ["iso", "iso"]})
        with self.assertRaisesRegex(ValueError, "duplicate preview view"):
            tool_export_preview_gif({"project_name": "missing_project", "views": ["iso", "iso"]})
        with self.assertRaisesRegex(ValueError, "display_mode must be one of"):
            tool_export_preview_image({"project_name": "missing_project", "display_mode": "raw"})

    def test_export_preview_image_rejects_non_png_output(self) -> None:
        path = project_dir("unit_export_preview_bad_suffix")
        if path.exists():
            shutil.rmtree(path)
        try:
            write_model_project(parse_model_spec(default_model_spec("unit_export_preview_bad_suffix", "shell_plate")))
            with self.assertRaisesRegex(ValueError, "must use .png"):
                tool_export_preview_image({"project_name": "unit_export_preview_bad_suffix", "output_filename": "preview.txt"})
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_export_preview_image_records_failure_when_png_missing(self) -> None:
        path = project_dir("unit_export_preview_failure_record")
        if path.exists():
            shutil.rmtree(path)
        try:
            write_model_project(parse_model_spec(default_model_spec("unit_export_preview_failure_record", "shell_plate")))

            def fake_launch(project_path, cfile_path, timeout_s=None, allow_multiple=False):
                text = cfile_path.read_text(encoding="utf-8")
                for line in text.splitlines():
                    if line.startswith("save kwdmsg "):
                        kwdmsg_path = project_path / line.split('"')[1]
                        kwdmsg_path.parent.mkdir(parents=True, exist_ok=True)
                        kwdmsg_path.write_text(
                            '<?xml version="1.0" encoding="UTF-8"?>\n<KeywordReaderMessages>\n  <Warnings/>\n  <Errors/>\n</KeywordReaderMessages>\n',
                            encoding="utf-8",
                        )
                return {"pid": 116, "mode": "cfile", "returncode": 0, "cfile_snapshot_sha256": "unit-sha"}

            with mock.patch("lsprepost_mcp.lspp.launcher.launch_cfile", side_effect=fake_launch):
                with self.assertRaisesRegex(FileNotFoundError, "preview image was not created"):
                    tool_export_preview_image({"project_name": "unit_export_preview_failure_record", "timeout_s": 5})
            records = read_json(path / "artifacts" / "lspp_verifications.json")["verifications"]
            self.assertEqual(records[-1]["action"], "export_preview_image")
            self.assertFalse(records[-1]["ok"])
            self.assertEqual(records[-1]["status"], "failed")
            self.assertEqual(records[-1]["error"]["type"], "FileNotFoundError")
            self.assertEqual(records[-1]["launch_record"]["cfile_snapshot_sha256"], "unit-sha")
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_run_cfile_runs_only_manifest_verified_server_cfile(self) -> None:
        path = project_dir("unit_run_cfile_tool")
        if path.exists():
            shutil.rmtree(path)
        try:
            write_model_project(parse_model_spec(default_model_spec("unit_run_cfile_tool", "shell_plate")))
            with mock.patch("lsprepost_mcp.lspp.launcher.launch_cfile", return_value={"pid": 222, "mode": "cfile", "returncode": 0}) as launch:
                result = tool_run_cfile({"project_name": "unit_run_cfile_tool", "cfile_filename": "open_model.cfile"})
            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "completed")
            launch.assert_called_once()

            bad = path / "artifacts" / "bad.cfile"
            bad.parent.mkdir(parents=True, exist_ok=True)
            bad.write_text("quit\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest-verified"):
                tool_run_cfile({"project_name": "unit_run_cfile_tool", "cfile_filename": "bad.cfile"})
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_run_cfile_rejects_zero_timeout_and_nonzero_returncode(self) -> None:
        path = project_dir("unit_run_cfile_completion_policy")
        if path.exists():
            shutil.rmtree(path)
        try:
            write_model_project(parse_model_spec(default_model_spec("unit_run_cfile_completion_policy", "shell_plate")))
            with self.assertRaisesRegex(ValueError, "greater than 0"):
                tool_run_cfile({"project_name": "unit_run_cfile_completion_policy", "timeout_s": 0})
            with mock.patch("lsprepost_mcp.lspp.launcher.launch_cfile", return_value={"pid": 223, "mode": "cfile", "returncode": 1}):
                with self.assertRaisesRegex(RuntimeError, "did not complete successfully"):
                    tool_run_cfile({"project_name": "unit_run_cfile_completion_policy", "timeout_s": 5})
            records = read_json(path / "artifacts" / "lspp_verifications.json")["verifications"]
            self.assertEqual(records[-1]["action"], "run_cfile")
            self.assertFalse(records[-1]["ok"])
            self.assertEqual(records[-1]["status"], "failed")
            self.assertEqual(records[-1]["launch_record"]["returncode"], 1)
            self.assertEqual(
                hashlib.sha256((path / "model.k").read_bytes()).hexdigest(),
                records[-1]["model_fingerprint"]["model_k_sha256"],
            )
            self.assertEqual(
                hashlib.sha256((path / "model.json").read_bytes()).hexdigest(),
                records[-1]["model_fingerprint"]["model_json_sha256"],
            )
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_automated_lsprepost_tools_reject_excessive_timeout(self) -> None:
        with self.assertRaisesRegex(ValueError, "120"):
            tool_export_preview_image({"project_name": "missing_project", "timeout_s": 121})
        with self.assertRaisesRegex(ValueError, "120"):
            tool_export_preview_images({"project_name": "missing_project", "timeout_s": 121})
        with self.assertRaisesRegex(ValueError, "120"):
            tool_export_preview_gif({"project_name": "missing_project", "timeout_s": 121})
        with self.assertRaisesRegex(ValueError, "120"):
            tool_validate_lsprepost_import({"project_name": "missing_project", "timeout_s": 121})
        with self.assertRaisesRegex(ValueError, "120"):
            tool_run_cfile({"project_name": "missing_project", "timeout_s": 121})


if __name__ == "__main__":
    unittest.main()
