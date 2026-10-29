from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Phase17WebE2EContractTests(unittest.TestCase):
    def test_playwright_runner_is_pinned_and_declared(self) -> None:
        package = json.loads(
            (ROOT / "web" / "package.json").read_text(encoding="utf-8")
        )
        workspace = (ROOT / "web" / "pnpm-workspace.yaml").read_text(
            encoding="utf-8"
        )

        self.assertEqual(
            "1.61.1",
            package["devDependencies"]["playwright"],
        )
        self.assertEqual(
            "node tests/phase17-editor.e2e.cjs",
            package["scripts"]["test:phase17"],
        )
        self.assertIn("esbuild: true", workspace)
        self.assertNotIn("set this to true or false", workspace)

    def test_e2e_entry_points_exist_and_do_not_reference_solvers(self) -> None:
        runner = ROOT / "web" / "tests" / "phase17-editor.e2e.cjs"
        orchestrator = ROOT / "scripts" / "test_phase17_web.ps1"

        self.assertTrue(runner.is_file())
        self.assertTrue(orchestrator.is_file())
        combined = (
            runner.read_text(encoding="utf-8")
            + orchestrator.read_text(encoding="utf-8")
        ).lower()
        self.assertIn("phase17canvas", combined)
        self.assertIn("startphase17city", combined)
        self.assertNotIn("lsrun.exe", combined)
        self.assertNotIn("lsdyna.exe", combined)
        self.assertNotIn("Start-Process", orchestrator.read_text(encoding="utf-8"))
        self.assertIn(
            "System.Diagnostics.ProcessStartInfo",
            orchestrator.read_text(encoding="utf-8"),
        )

    def test_test_matrix_exposes_phase17_browser_group(self) -> None:
        matrix = (ROOT / "scripts" / "run_test_matrix.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn('"web-e2e"', matrix)
        self.assertIn("test_phase17_web.ps1", matrix)

    def test_preview_revision_is_monotonic_across_history_restore(self) -> None:
        editor = (
            ROOT / "lsprepost_mcp" / "web" / "static" / "phase17_editor.js"
        ).read_text(encoding="utf-8")

        self.assertIn("revisionCounter: 0", editor)
        self.assertIn("const revision = ++state.revisionCounter;", editor)
        self.assertIn("state.draft.revision = revision;", editor)
        self.assertIn("preview.revision !== job.revision", editor)
        self.assertNotIn("state.draft.revision += 1", editor)

    def test_editor_coalesces_preview_work_and_protects_unsaved_state(self) -> None:
        editor = (
            ROOT / "lsprepost_mcp" / "web" / "static" / "phase17_editor.js"
        ).read_text(encoding="utf-8")

        self.assertIn("pendingPreviewJob: null", editor)
        self.assertIn("previewWorker: null", editor)
        self.assertIn("async function runPreviewQueue()", editor)
        self.assertIn('window.addEventListener("beforeunload"', editor)
        self.assertIn("if (!state.dirty) return;", editor)
        self.assertIn("if (state.generating) return;", editor)
        self.assertIn("token !== state.generationToken", editor)
        self.assertIn("state.history.length > 100", editor)

    def test_editor_preserves_camera_across_scene_rebuilds(self) -> None:
        editor = (
            ROOT / "lsprepost_mcp" / "web" / "static" / "phase17_editor.js"
        ).read_text(encoding="utf-8")
        app = (
            ROOT / "lsprepost_mcp" / "web" / "static" / "app.js"
        ).read_text(encoding="utf-8")

        self.assertIn("cameraInitialized: false", editor)
        self.assertIn("if (!state.cameraInitialized)", editor)
        self.assertIn('window.addEventListener("phase17:view"', editor)
        self.assertIn('window.addEventListener("phase17:get-camera-pose"', editor)
        self.assertIn('dispatchPhase17View("fit"', app)
        self.assertIn('dispatchPhase17View("iso"', app)
        self.assertIn('dispatchPhase17View("top"', app)
        self.assertIn('dispatchPhase17View("front"', app)

    def test_browser_acceptance_covers_city_mobility_and_component_addition(self) -> None:
        runner = (
            ROOT / "web" / "tests" / "phase17-editor.e2e.cjs"
        ).read_text(encoding="utf-8")

        self.assertIn('"subway_entrance"', runner)
        self.assertIn('"parked_vehicle_1"', runner)
        self.assertIn('"parked_vehicle_5"', runner)
        self.assertIn('"parked_vehicle_6"', runner)
        self.assertIn('data-city-add="parked_vehicle"', runner)
        self.assertIn('data-city-add="subway_entrance"', runner)
        self.assertIn('"subway_entrance_2"', runner)
        self.assertIn('"subway_entrance_3"', runner)
        self.assertIn("#phase17DuplicateComponent", runner)
        self.assertIn("#phase17DeleteComponent", runner)
        self.assertIn("component_delete_undo_redo_works", runner)
        self.assertIn("subway_multi_instance_works", runner)
        self.assertIn('data-city-add="shell_box"', runner)
        self.assertIn('"shell_box_1"', runner)
        self.assertIn("existing_library_shell_box_works", runner)
        self.assertIn("camera_preserved_across_component_add", runner)

    def test_numeric_editor_rejects_blank_values_before_history_mutation(self) -> None:
        editor = (
            ROOT / "lsprepost_mcp" / "web" / "static" / "phase17_editor.js"
        ).read_text(encoding="utf-8")

        self.assertIn("function finiteInputValue(id)", editor)
        self.assertIn('throw new Error("变换值不能为空。")', editor)
        values_index = editor.index("const values = {", editor.index("applyNumericTransform"))
        history_index = editor.index("rememberDraft();", values_index)
        self.assertLess(values_index, history_index)


if __name__ == "__main__":
    unittest.main()
