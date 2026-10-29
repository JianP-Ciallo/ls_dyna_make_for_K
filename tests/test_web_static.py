from __future__ import annotations

import json
import http.client
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path

from lsprepost_mcp.config import ROOT as PROJECT_ROOT
from lsprepost_mcp.web.app import create_server


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "lsprepost_mcp" / "web" / "static" / "app.js"
MODEL_VIEWER_WEBGL_JS = (
    ROOT / "lsprepost_mcp" / "web" / "static" / "model_viewer_webgl.js"
)
PHASE17_JS = ROOT / "lsprepost_mcp" / "web" / "static" / "phase17_editor.js"
STYLES_CSS = ROOT / "lsprepost_mcp" / "web" / "static" / "styles.css"
PACKAGE_JSON = ROOT / "web" / "package.json"
REFINED_WORKBENCH_JS = ROOT / "lsprepost_mcp" / "web" / "static" / "refined_blast_workbench.js"


@contextmanager
def web_test_server():
    server = create_server("127.0.0.1", 0, open_browser=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request_raw(address, path: str):
    conn = http.client.HTTPConnection(address[0], address[1], timeout=10)
    conn.request("GET", path)
    response = conn.getresponse()
    data = response.read()
    headers = dict(response.getheaders())
    conn.close()
    return response.status, headers, data


def request_json(address, method: str, path: str, payload: dict | None = None):
    body = json.dumps(payload or {}).encode("utf-8") if method == "POST" else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    conn = http.client.HTTPConnection(address[0], address[1], timeout=10)
    conn.request(method, path, body=body, headers=headers)
    response = conn.getresponse()
    data = json.loads(response.read().decode("utf-8"))
    conn.close()
    return response.status, data


class WebStaticFallbackTests(unittest.TestCase):
    def test_phase12_catalog_endpoints_expose_components_and_actions(self) -> None:
        with web_test_server() as address:
            component_status, components = request_json(address, "GET", "/api/components")
            action_status, actions = request_json(address, "GET", "/api/physics-actions")

        self.assertEqual(200, component_status)
        self.assertEqual(15, components["result"]["count"])
        self.assertEqual(200, action_status)
        self.assertEqual(8, actions["result"]["count"])

    def test_phase13_blast_case_endpoints_expose_controlled_presets(self) -> None:
        with web_test_server() as address:
            catalog_status, catalog = request_json(address, "GET", "/api/blast-cases")
            case_status, case = request_json(
                address,
                "GET",
                "/api/blast-case?case_id=blast_on_helmet&project_name=web_phase13_helmet",
            )

        self.assertEqual(200, catalog_status)
        self.assertEqual(3, catalog["result"]["count"])
        self.assertEqual(200, case_status)
        self.assertEqual("web_phase13_helmet", case["result"]["payload"]["project_name"])
        self.assertEqual("blast_on_helmet", case["result"]["payload"]["case_id"])

    def test_phase14_ale_validate_endpoint_is_dry_run_only(self) -> None:
        with web_test_server() as address:
            status, result = request_json(
                address,
                "POST",
                "/api/ale-blast/validate",
                {"project_name": "web_phase14_contract"},
            )

        self.assertEqual(200, status)
        self.assertEqual("validated_only", result["result"]["status"])
        self.assertEqual("MM-ALE", result["result"]["metadata"]["analysis_method"])
        self.assertEqual(
            "explicit_user_approval_required",
            result["result"]["solver_permission"],
        )

    def test_static_ui_nests_phase14_ale_under_controlled_scenes(self) -> None:
        html = (ROOT / "lsprepost_mcp" / "web" / "static" / "index.html").read_text(encoding="utf-8")
        js = APP_JS.read_text(encoding="utf-8")

        model_mode_markup = html.split('<select id="modelMode">', 1)[1].split("</select>", 1)[0]
        self.assertNotIn('value="ale_blast"', model_mode_markup)
        self.assertIn('const aleBlastSceneId = "ale_blast";', js)
        self.assertIn("option.value = aleBlastSceneId;", js)
        self.assertIn(
            'return byId("modelMode").value === "controlled" && byId("scene").value === aleBlastSceneId;',
            js,
        )
        self.assertIn('id="controlledSceneFields"', html)
        self.assertIn('id="aleBlastPanel"', html)
        self.assertIn('id="aleExplosiveMass"', html)
        self.assertIn('id="aleMeshSize"', html)
        self.assertIn("受控仅表示输入与生成路径受控", html)
        self.assertIn("网格收敛性尚未证明", html)
        self.assertIn("钢板周边完全固定", html)
        self.assertIn("受控场景不等于工程验证；钢板周边完全固定，网格收敛性尚未证明。", js)
        self.assertIn("/api/ale-blast/validate", js)
        self.assertIn("/api/ale-blast/generate", js)
        self.assertIn("default_hidden_part_ids", js)

    def test_tunnel_ui_contains_parametric_geometry_and_labeled_uniform_mesh(self) -> None:
        html = (ROOT / "lsprepost_mcp" / "web" / "static" / "index.html").read_text(encoding="utf-8")
        js = APP_JS.read_text(encoding="utf-8")

        for control_id in (
            "tunnelLength",
            "tunnelWidth",
            "tunnelHeight",
            "tunnelWallThickness",
            "tunnelExplosiveX",
            "tunnelExplosiveY",
            "tunnelExplosiveZ",
            "tunnelAirMesh",
            "tunnelPlateX",
            "tunnelPlateY",
            "tunnelPlateZ",
            "tunnelPlateMaterial",
            "tunnelMeshEstimate",
        ):
            self.assertIn(f'id="{control_id}"', html)
        self.assertIn('value="0.075"', html)
        self.assertIn("较高精细度，计算量较大", html)
        self.assertIn("均衡，推荐", html)
        self.assertIn("快速预览，不适合定量分析", html)
        self.assertIn("function estimateTunnelAleCells", js)
        self.assertIn("function updateTunnelMeshEstimate", js)
        self.assertIn("function updateTunnelPositionLimits", js)
        self.assertIn("if (!globalBusy && isTunnelBlastMode()) updateTunnelMeshEstimate();", js)
        self.assertIn("plate_material_name", js)
        self.assertIn("plate_center_m", js)
        self.assertIn('<option value="tunnel_blast">参数化通道爆炸</option>', html)
        self.assertIn('return "参数化通道爆炸";', js)
        self.assertNotIn("Phase 14 通道爆炸", html)

    def test_phase15_ui_exposes_controlled_generation_after_preparation(self) -> None:
        html = (ROOT / "lsprepost_mcp" / "web" / "static" / "index.html").read_text(encoding="utf-8")
        js = APP_JS.read_text(encoding="utf-8")

        self.assertIn('<option value="phase15_a1">K&amp;C 柱形埋置装药</option>', html)
        self.assertIn('id="phase15Panel"', html)
        self.assertIn('id="phase15ConsistencyMode"', html)
        self.assertIn('id="phase15TntMass"', html)
        self.assertIn('id="phase15MeshSize"', html)
        self.assertIn('id="phase15CouplingMode"', html)
        self.assertIn('id="phase15ConformingFields"', html)
        self.assertIn('id="phase15BoreholeRadius"', html)
        self.assertIn('id="phase15BottomAirGap"', html)
        self.assertIn('id="phase15AirGapSummary"', html)
        self.assertIn('id="phase15FsiOverlapLayers"', html)
        self.assertIn('id="phase15FsiOverlapSummary"', html)
        self.assertIn('id="phase15ConcreteFpcMpa"', html)
        self.assertIn('id="phase15ErosionMode"', html)
        self.assertIn('id="phase15EndTimeMs"', html)
        self.assertIn("/api/phase15/prepare", js)
        self.assertIn("/api/phase15/generate", js)
        self.assertIn("Phase 15 A-1 二维轴对称求解草案", js)
        self.assertIn("result.axisymmetric_region_mesh", js)
        self.assertIn("四区网格", js)
        self.assertIn('coupling_mode: couplingMode', js)
        self.assertIn('if (couplingMode === "immersed_clis")', js)
        self.assertIn('payload.fsi_overlap_layers =', js)
        self.assertIn('payload.borehole_radius_m =', js)
        self.assertIn('payload.bottom_air_gap_m =', js)
        self.assertIn("updatePhase15FsiOverlapSummary", js)
        self.assertIn("updatePhase15CouplingControls", js)

        with web_test_server() as address:
            status, result = request_json(
                address,
                "POST",
                "/api/phase15/prepare",
                {"consistency_mode": "mass_priority_adjust_length"},
            )

        self.assertEqual(200, status)
        self.assertTrue(result["result"]["ready_for_axisymmetric_compiler"])
        self.assertTrue(result["result"]["generation_available"])
        self.assertEqual(result["result"]["axisymmetric_region_mesh"]["quality_issue_count"], 0)
        self.assertEqual(
            set(result["result"]["axisymmetric_region_mesh"]["regions"]),
            {"concrete", "tnt", "air", "steel_hoop"},
        )

    def test_phase15_ui_exposes_independent_qualification_statuses(self) -> None:
        html = (ROOT / "lsprepost_mcp" / "web" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        js = APP_JS.read_text(encoding="utf-8")

        for element_id in (
            "recoverLsrun",
            "openResultLspp",
            "phase15StaticBadge",
            "phase15SolverBadge",
            "phase15TransferBadge",
            "phase15CalibrationBadge",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn("/api/solve/recover-lsrun", js)
        self.assertIn("/api/project/open-result-lsprepost", js)
        self.assertIn("handoff_opened", js)
        self.assertIn("wave_transfer_verified", js)

    def test_phase16a_ui_exposes_city_impact_without_claiming_missing_results(self) -> None:
        html = (ROOT / "lsprepost_mcp" / "web" / "static" / "index.html").read_text(encoding="utf-8")
        js = APP_JS.read_text(encoding="utf-8")

        for control_id in (
            "cityImpactSection",
            "cityImpactStatus",
            "cityImpactObjects",
            "cityImpactDetail",
            "readCityImpact",
            "exportCityImpact",
        ):
            self.assertIn(f'id="{control_id}"', html)
        self.assertIn("/api/project/city-impact?", js)
        self.assertIn("/api/project/city-impact-report", js)
        self.assertIn("riskByPartId", js)
        self.assertIn("无法评估", html)

    def test_phase12_assembly_validate_endpoint_does_not_write(self) -> None:
        from lsprepost_mcp.schema import default_model_spec

        raw = default_model_spec("web_assembly_validate", "assembly_scene")
        with web_test_server() as address:
            status, result = request_json(
                address,
                "POST",
                "/api/assembly/validate",
                {"project_name": "web_assembly_validate", "components": raw["components"], "actions": []},
            )

        self.assertEqual(200, status)
        self.assertEqual("validated_only", result["result"]["status"])
    def test_root_serves_fallback_html(self) -> None:
        with web_test_server() as address:
            status, headers, data = request_raw(address, "/")

        text = data.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("lsprepost-mcp 本地建模工作台", text)
        self.assertIn("app.js", text)

    def test_app_js_contains_scene_loader(self) -> None:
        with web_test_server() as address:
            status, headers, data = request_raw(address, "/app.js")

        text = data.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers["Content-Type"])
        self.assertIn("loadScenes", text)

    def test_static_ui_contains_lsprepost_path_configuration_controls(self) -> None:
        html = (ROOT / "lsprepost_mcp" / "web" / "static" / "index.html").read_text(encoding="utf-8")
        js = APP_JS.read_text(encoding="utf-8")

        self.assertIn('id="lsppExe"', html)
        self.assertIn('id="importLspp"', html)
        self.assertIn('id="saveLspp"', html)
        self.assertIn("/api/config/select-lsprepost", js)
        self.assertIn("/api/config/check-lsprepost", js)
        self.assertIn("/api/config/lsprepost", js)

    def test_static_ui_contains_user_export_directory_controls(self) -> None:
        html = (ROOT / "lsprepost_mcp" / "web" / "static" / "index.html").read_text(encoding="utf-8")
        js = APP_JS.read_text(encoding="utf-8")

        self.assertIn('id="exportDirStatus"', html)
        self.assertIn('id="selectExportDir"', html)
        self.assertIn('id="exportDir"', html)
        self.assertIn('id="saveExportDir"', html)
        self.assertIn("/api/config/select-export-dir", js)
        self.assertIn("/api/config/export-dir", js)

    def test_static_ui_contains_right_side_lsrun_controls(self) -> None:
        html = (ROOT / "lsprepost_mcp" / "web" / "static" / "index.html").read_text(encoding="utf-8")
        js = APP_JS.read_text(encoding="utf-8")

        self.assertIn('id="lsrunStatus"', html)
        self.assertIn('id="importLsrun"', html)
        self.assertIn('id="lsrunExe"', html)
        self.assertIn('id="importLsdyna"', html)
        self.assertIn('id="lsdynaExe"', html)
        self.assertIn('id="checkLsrun"', html)
        self.assertIn('id="saveLsrun"', html)
        self.assertIn('id="sendToLsrun"', html)
        self.assertIn('id="solveNcpu"', html)
        self.assertIn('id="solveMemory"', html)
        self.assertIn('id="solveTimeout"', html)
        self.assertIn('id="solveProjectConfirmation"', html)
        self.assertIn('id="runLsdyna"', html)
        self.assertIn('id="readSolveStatus"', html)
        self.assertIn("/api/config/select-lsrun", js)
        self.assertIn("/api/config/check-lsrun", js)
        self.assertIn("/api/config/lsrun", js)
        self.assertIn("/api/config/select-lsdyna", js)
        self.assertIn("/api/config/lsdyna", js)
        self.assertIn("/api/solve/open-lsrun", js)
        self.assertIn("/api/solve/run-lsdyna", js)
        self.assertIn("/api/solve/status", js)
        self.assertIn("confirmation_project_name", js)

    def test_static_ui_contains_complete_model_package_import_controls(self) -> None:
        html = (ROOT / "lsprepost_mcp" / "web" / "static" / "index.html").read_text(encoding="utf-8")
        js = APP_JS.read_text(encoding="utf-8")

        self.assertIn('id="importPackageStatus"', html)
        self.assertIn('id="selectImportPackageDir"', html)
        self.assertIn('id="importPackageDir"', html)
        self.assertIn('id="importPackageProjectName"', html)
        self.assertIn('id="importPackage"', html)
        self.assertIn("/api/project/select-import-package", js)
        self.assertIn("/api/project/import-package", js)

    def test_static_ui_is_chinese_workbench_with_center_viewport(self) -> None:
        html = (ROOT / "lsprepost_mcp" / "web" / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn('lang="zh-CN"', html)
        self.assertIn("本地建模工作台", html)
        self.assertIn('id="leftWorkbench"', html)
        self.assertIn('id="modelViewport"', html)
        self.assertIn('id="rightInspector"', html)
        self.assertIn("三维视窗", html)
        self.assertIn("导入 LS-PrePost", html)
        self.assertNotIn(">Check Path<", html)
        self.assertNotIn(">Save Path<", html)
        self.assertNotIn(">Projects<", html)
        self.assertNotIn(">Use<", html)

    def test_static_ui_contains_interactive_canvas_viewer(self) -> None:
        html = (ROOT / "lsprepost_mcp" / "web" / "static" / "index.html").read_text(encoding="utf-8")
        js = APP_JS.read_text(encoding="utf-8")

        self.assertIn('id="modelCanvas"', html)
        self.assertIn('id="viewerHint"', html)
        self.assertIn("/api/project/preview-mesh", js)
        self.assertIn("renderInteractiveMesh", js)
        self.assertIn("pointerdown", js)
        self.assertIn("wheel", js)

    def test_static_ui_loads_webgl_model_viewer_module(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertTrue(MODEL_VIEWER_WEBGL_JS.is_file())
        viewer_js = MODEL_VIEWER_WEBGL_JS.read_text(encoding="utf-8")
        self.assertIn('import("/model_viewer_webgl.js")', app_js)
        self.assertIn('from "three"', viewer_js)
        self.assertIn("THREE.LineSegments", viewer_js)
        self.assertIn("part.edges", viewer_js)
        self.assertIn("record.edges.visible = true", viewer_js)
        self.assertIn("requestAnimationFrame", viewer_js)
        self.assertIn("webglcontextlost", viewer_js)

    def test_preview_mesh_loader_cancels_stale_project_requests(self) -> None:
        app_js = APP_JS.read_text(encoding="utf-8")

        self.assertIn("previewMeshAbortController.abort()", app_js)
        self.assertIn("new AbortController()", app_js)
        self.assertIn("previewMeshRequestSequence", app_js)
        self.assertIn("error.name === \"AbortError\"", app_js)

    def test_phase17_editor_uses_local_threejs_and_preserves_cumulative_transforms(self) -> None:
        html = (ROOT / "lsprepost_mcp" / "web" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        js = PHASE17_JS.read_text(encoding="utf-8")
        css = STYLES_CSS.read_text(encoding="utf-8")

        self.assertIn('id="phase17Canvas"', html)
        self.assertIn('id="phase17ValidateLspp"', html)
        self.assertIn('id="phase17LsppEvidence"', html)
        self.assertIn('id="phase17ValidationImage"', html)
        self.assertIn("LS-PrePost 导入检查", html)
        self.assertNotIn("LS-PrePost 验收", html)
        self.assertIn('id="phase17Reset"', html)
        self.assertIn('type="importmap"', html)
        self.assertIn("/vendor/three/three.module.min.js", html)
        self.assertIn("/vendor/three/addons/controls/TransformControls.js", js)
        self.assertNotIn("cdn.", html.lower())
        self.assertIn("object.userData.previewPosition", js)
        self.assertIn("Number(existing.translate_m?.[0] || 0)", js)
        self.assertIn("Number(existing.rotate_deg?.[2] || 0)", js)
        self.assertIn("async function resetDraft()", js)
        self.assertIn("function invalidateGeneratedProject()", js)
        self.assertIn("async function preflightLsppConfiguration()", js)
        self.assertIn("function focusLsppConfiguration()", js)
        self.assertIn("function renderLsppEvidence(result)", js)
        self.assertIn("lsprepost_not_configured", js)
        self.assertIn(
            'byId("phase17ProjectName").addEventListener("input", () => {',
            js,
        )
        self.assertIn("syncDirty();", js)
        self.assertIn("/api/editor/validate-lsprepost", js)
        self.assertIn('"surface_dynamic"', js)
        self.assertIn('subway_entrance: "地铁入口"', js)
        self.assertIn('parked_vehicle_4: "停车场车辆 4"', js)
        self.assertIn('id="phase17ObjectsTab"', html)
        self.assertIn('id="phase17LibraryTab"', html)
        self.assertIn('id="phase17LibraryList"', html)
        self.assertIn('id="phase17DuplicateComponent"', html)
        self.assertIn('id="phase17DeleteComponent"', html)
        self.assertIn('id="phase17ComponentSummary"', html)
        self.assertIn('id="phase17GroundCraterEnabled"', html)
        self.assertIn('id="phase17GroundCraterDepth"', html)
        self.assertIn('id="phase17GroundOverlapLayers"', html)
        self.assertIn("async function applyGroundCraterControls()", js)
        self.assertIn('capability_version: "city_ground_crater_v1"', js)
        self.assertIn("async function addCityComponent(template)", js)
        self.assertIn("async function mutateCityComponent(operation)", js)
        self.assertIn("function renderComponentSummary()", js)
        self.assertIn('if (state.active && !canvas.classList.contains("hidden"))', js)
        self.assertIn("Math.min(window.devicePixelRatio || 1, 1.5)", js)
        self.assertIn('["parked_vehicle", "subway_entrance"]', js)
        self.assertIn('id.startsWith("subway_entrance_")', js)
        self.assertIn('shell_box: "钢制防护箱"', js)
        self.assertIn('id.startsWith("shell_box_")', js)
        self.assertIn('request("/api/editor/city-component"', js)
        self.assertIn("definition.city_editor?.instance_operations", js)
        self.assertNotIn("function nextVehiclePlacement", js)
        self.assertIn('request("/api/components")', js)
        self.assertIn(".phase17-component-summary", css)

        with web_test_server() as address:
            module_status, _, module_data = request_raw(
                address, "/vendor/three/three.module.min.js"
            )
            core_status, _, core_data = request_raw(
                address, "/vendor/three/three.core.min.js"
            )

        self.assertEqual(200, module_status)
        self.assertGreater(len(module_data), 100_000)
        self.assertEqual(200, core_status)
        self.assertGreater(len(core_data), 100_000)

    def test_canvas_viewer_uses_world_grid_and_rotating_axis_widget(self) -> None:
        js = APP_JS.read_text(encoding="utf-8")
        css = (ROOT / "lsprepost_mcp" / "web" / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("function drawWorldGrid", js)
        self.assertIn("function drawRotatingAxes", js)
        self.assertIn("function projectWorldPoint", js)
        self.assertIn("function rotateViewVector", js)
        self.assertNotIn("for (let x = 0; x <= width; x += 44)", js)
        self.assertIn(".viewport-grid", css)
        self.assertIn("display: none", css)

    def test_preview_button_refreshes_interactive_mesh_not_gif_overlay(self) -> None:
        text = APP_JS.read_text(encoding="utf-8")

        self.assertIn("async function previewInteractiveModel()", text)
        self.assertIn('byId("preview").addEventListener("click", previewInteractiveModel)', text)
        self.assertNotIn('byId("preview").addEventListener("click", previewGif)', text)

    def test_static_js_filters_unnamed_projects_and_limits_sidebar(self) -> None:
        text = APP_JS.read_text(encoding="utf-8")

        self.assertIn("有效项目", text)
        self.assertIn(".filter((project)", text)
        self.assertIn("project.name", text)
        self.assertIn(".slice(0, 5)", text)
        self.assertIn('button.textContent = "使用"', text)

    def test_app_js_updates_project_name_from_generation_result(self) -> None:
        text = APP_JS.read_text(encoding="utf-8")

        self.assertIn("result.write_result.project", text)
        self.assertIn('byId("projectName").value = generatedProjectName', text)
        self.assertIn("lastProjectName = generatedProjectName", text)

    def test_app_js_replaces_existing_controlled_scene_project_name_when_scene_changes(self) -> None:
        text = APP_JS.read_text(encoding="utf-8")
        start = text.index("function updateProjectNameForScene")
        end = text.index("function renderFields")
        function_text = text[start:end]

        self.assertIn("controlledScenePrefix", text)
        self.assertIn("currentStartsWithControlledPrefix", text)
        self.assertIn("input.value = `web_${scene.id}`", function_text)

    def test_app_js_refreshes_projects_inside_generate_action(self) -> None:
        text = APP_JS.read_text(encoding="utf-8")
        start = text.index("async function generateScene()")
        end = text.index("async function previewInteractiveModel()")
        generate_scene = text[start:end]

        self.assertIn("await loadProjects();", generate_scene)
        self.assertLess(generate_scene.index("await loadProjects();"), generate_scene.index("return result;"))
        self.assertNotIn("if (result) await loadProjects();", generate_scene)

    def test_app_js_renders_user_friendly_operation_summary(self) -> None:
        text = APP_JS.read_text(encoding="utf-8")

        self.assertIn("function showOperationSummary", text)
        self.assertIn("function summarizeResult", text)
        self.assertIn("查看详细信息", text)
        self.assertNotIn("showResult(result);", text)

    def test_static_ui_contains_workflow_reliability_panels(self) -> None:
        html = (ROOT / "lsprepost_mcp" / "web" / "static" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "lsprepost_mcp" / "web" / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="contextStatus"', html)
        self.assertIn('id="partLegend"', html)
        self.assertIn("context-status", css)
        self.assertIn("part-legend", css)

    def test_static_ui_uses_compact_resource_parameter_and_inspector_navigation(self) -> None:
        html = (ROOT / "lsprepost_mcp" / "web" / "static" / "index.html").read_text(encoding="utf-8")
        js = APP_JS.read_text(encoding="utf-8")
        css = (ROOT / "lsprepost_mcp" / "web" / "static" / "styles.css").read_text(encoding="utf-8")

        for panel_id in ("lsppResourcePanel", "exportResourcePanel", "importResourcePanel"):
            self.assertIn(f'data-resource-panel="{panel_id}"', html)
            self.assertIn(f'id="{panel_id}" class="resource-panel hidden"', html)
        for panel_id in ("inspectorSolve", "cityImpactSection", "inspectorProjects", "inspectorResults"):
            self.assertIn(f'data-inspector-target="{panel_id}"', html)
        self.assertIn('class="parameter-group"', html)
        self.assertIn("function setupWorkbenchNavigation", js)
        self.assertIn("function createParameterGroup", js)
        self.assertIn("function fieldGroup", js)
        self.assertIn(".resource-buttons", css)
        self.assertIn(".inspector-tabs", css)
        self.assertIn(".parameter-group", css)

    def test_center_viewport_supports_inspection_and_honest_result_mode(self) -> None:
        html = (ROOT / "lsprepost_mcp" / "web" / "static" / "index.html").read_text(encoding="utf-8")
        js = APP_JS.read_text(encoding="utf-8")
        css = (ROOT / "lsprepost_mcp" / "web" / "static" / "styles.css").read_text(encoding="utf-8")

        for control_id in (
            "modelViewMode",
            "resultViewMode",
            "displayMode",
            "toggleGrid",
            "toggleLegend",
            "toggleBlastSources",
            "showAllParts",
            "fullscreenView",
            "selectionPanel",
            "isolateSelectedPart",
            "hideSelectedPart",
            "resultEmptyState",
            "resultControls",
            "resultVariable",
            "resultTimeline",
            "refreshResultStatus",
        ):
            self.assertIn(f'id="{control_id}"', html)
        for function_name in (
            "setViewportMode",
            "loadViewportResultStatus",
            "pickPartAt",
            "selectViewerPart",
            "setViewerDisplayMode",
            "toggleViewportFullscreen",
        ):
            self.assertIn(f"function {function_name}", js)
        self.assertIn("/api/solve/status?project_name=", js)
        self.assertIn("浏览器尚未解析 d3plot 结果帧", js)
        self.assertIn(".selection-panel", css)
        self.assertIn(".result-controls", css)
        self.assertIn(".viewport-panel:fullscreen", css)

    def test_native_picker_actions_show_feedback_in_the_active_panel(self) -> None:
        js = APP_JS.read_text(encoding="utf-8")

        self.assertIn("async function runPickerAction", js)
        picker_action = js.split("async function runPickerAction", 1)[1].split(
            "async function resolveScene", 1
        )[0]
        self.assertIn("setPickerBusy(true)", picker_action)
        self.assertIn("setPickerBusy(false)", picker_action)
        self.assertNotIn("setBusy(true)", picker_action)
        self.assertNotIn("setBusy(false)", picker_action)
        self.assertIn("选择窗口打开期间，其他功能仍可使用", picker_action)
        self.assertIn("const PICKER_BUTTON_IDS", js)
        self.assertIn('runPickerAction("正在打开模型文件夹选择窗口", "importPackageStatus"', js)
        self.assertIn('runPickerAction("正在打开 LS-PrePost 文件选择窗口", "lsppStatus"', js)
        self.assertIn('runPickerAction("正在打开模型保存位置选择窗口", "exportDirStatus"', js)
        self.assertIn('runPickerAction("正在打开 LS-Run 文件选择窗口", "lsrunStatus"', js)
        self.assertIn('runPickerAction("正在打开 LS-DYNA 文件选择窗口", "lsrunStatus"', js)
        self.assertIn("如未看到系统窗口，请检查任务栏或按 Alt+Tab", js)

    def test_global_busy_state_does_not_overwrite_contextual_button_disabling(self) -> None:
        js = APP_JS.read_text(encoding="utf-8")
        busy_state = js.split("function applyBusyState()", 1)[1].split(
            "function setBusy", 1
        )[0]

        self.assertIn('document.body.classList.toggle("global-busy", globalBusy)', busy_state)
        self.assertNotIn("button.disabled = globalBusy", busy_state)
        self.assertIn('event.stopImmediatePropagation()', js)

    def test_project_action_availability_refreshes_after_generation_and_import(self) -> None:
        js = APP_JS.read_text(encoding="utf-8")
        self.assertIn("function refreshActionAvailability()", js)
        generated = js.split("function rememberGeneratedProjectName", 1)[1].split(
            "function normalizePath", 1
        )[0]
        imported = js.split("async function finishImportedProject", 1)[1].split(
            "async function selectImportPackageDir", 1
        )[0]
        self.assertIn("refreshActionAvailability();", generated)
        self.assertIn("refreshActionAvailability();", imported)

    def test_phase12_static_ui_contains_free_assembly_editor(self) -> None:
        html = (ROOT / "lsprepost_mcp" / "web" / "static" / "index.html").read_text(encoding="utf-8")
        js = APP_JS.read_text(encoding="utf-8")

        self.assertIn('id="modelMode"', html)
        self.assertIn('id="assemblyPanel"', html)
        self.assertIn('id="assemblyComponents"', html)
        self.assertIn('id="assemblyActions"', html)
        self.assertIn('id="addComponent"', html)
        self.assertIn('id="addPhysicsAction"', html)
        self.assertIn("/api/assembly/validate", js)
        self.assertIn("/api/assembly/generate", js)
        self.assertIn("function renderAssemblyComponents", js)
        self.assertIn("function renderAssemblyActions", js)

    def test_phase13_static_ui_contains_presets_multi_target_editor_and_comparison(self) -> None:
        html = (ROOT / "lsprepost_mcp" / "web" / "static" / "index.html").read_text(encoding="utf-8")
        js = APP_JS.read_text(encoding="utf-8")

        self.assertIn('id="blastCaseSelect"', html)
        self.assertIn('id="loadPhase13BlastCase"', html)
        self.assertIn('id="compareProjectA"', html)
        self.assertIn('id="compareProjectB"', html)
        self.assertIn('id="compareBlastRuns"', html)
        self.assertIn("/api/blast-cases", js)
        self.assertIn("/api/blast-case", js)
        self.assertIn("/api/solve/compare", js)
        self.assertIn("function blastTargetsEditor", js)
        self.assertIn("function appendPhase13MetricRows", js)
        self.assertIn("峰值等效应力", js)
        self.assertIn("正相冲量", js)

    def test_app_js_confirms_generation_and_tracks_current_context(self) -> None:
        text = APP_JS.read_text(encoding="utf-8")
        start = text.index("async function generateScene()")
        end = text.index("async function previewInteractiveModel()")
        generate_scene = text[start:end]

        self.assertIn("function buildGenerationConfirmationSummary", text)
        self.assertIn("function confirmGeneration", text)
        self.assertIn("window.confirm", text)
        self.assertIn("if (!confirmGeneration())", generate_scene)
        self.assertIn("function updateContextStatus", text)
        self.assertIn("viewer.projectName", text)

    def test_app_js_renders_part_legend_and_filters_hidden_parts(self) -> None:
        text = APP_JS.read_text(encoding="utf-8")
        legend = text[text.index("function renderPartLegend"):text.index("function togglePartVisibility")]

        self.assertIn("hiddenParts: new Set()", text)
        self.assertIn("function renderPartLegend", text)
        self.assertIn("function togglePartVisibility", text)
        self.assertIn("const partId = String(part.part_id)", text)
        self.assertIn("viewer.hiddenParts.has(partId)", text)
        self.assertIn('const label = document.createElement("div");', legend)
        self.assertIn('label.setAttribute("role", "button");', legend)
        self.assertNotIn('const label = document.createElement("label");', legend)

    def test_project_list_accepts_backend_project_name_contract(self) -> None:
        text = APP_JS.read_text(encoding="utf-8")
        project_list = text[text.index("function projectListName"):text.index("function impactMetricText")]

        self.assertIn("project.project_name || project.name", project_list)
        self.assertIn(".map(projectListName)", project_list)


class RefinedBlastStaticIsolationTests(unittest.TestCase):
    def test_refined_workbench_keeps_accessible_controls_and_legacy_boundary(self) -> None:
        source = REFINED_WORKBENCH_JS.read_text(encoding="utf-8")

        self.assertIn('id="refinedBlastBack"', source)
        self.assertIn('id="refinedBlastLayer-${layer.id}"', source)
        self.assertIn('for="refinedBlastLayer-${layer.id}"', source)
        self.assertIn('id="refinedBlastConflict"', source)
        self.assertIn('aria-live="assertive"', source)
        self.assertIn("root.replaceChildren(shell);\n  shell.focus?.();", source)
        self.assertIn('asset.id = "refinedBlastAsset"', source)
        self.assertIn('structuralSystem.id = "refinedBlastStructuralSystem"', source)
        self.assertIn('provider.id = "refinedBlastProvider"', source)
        self.assertIn('assetLabel.htmlFor = asset.id', source)
        self.assertIn('structuralSystemLabel.htmlFor = structuralSystem.id', source)
        self.assertIn('providerLabel.htmlFor = provider.id', source)
        self.assertIn('session.saveError?.message', source)
        self.assertNotIn("/api/editor/", source)
        self.assertNotIn("cityDraft", source)


class WebVitePackageTests(unittest.TestCase):
    def test_package_scripts_include_named_vite_commands(self) -> None:
        package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
        scripts = package["scripts"]

        self.assertEqual(scripts["dev:vite"], "vite")
        self.assertEqual(scripts["build:vite"], "node scripts/build-workbench.mjs")
        self.assertEqual(scripts.get("dev"), "vite")
        self.assertEqual(scripts.get("build"), "node scripts/build-workbench.mjs")


class WebBuildSelectionTests(unittest.TestCase):
    def test_stale_build_cannot_replace_the_production_workbench(self) -> None:
        from lsprepost_mcp.web.app import static_root

        dist = PROJECT_ROOT / "web" / "dist"
        index = dist / "index.html"
        had_dist = dist.exists()
        original = index.read_text(encoding="utf-8") if index.exists() else None

        dist.mkdir(parents=True, exist_ok=True)
        index.write_text("<!doctype html><title>built</title>", encoding="utf-8")
        try:
            self.assertEqual(static_root(), PROJECT_ROOT / "lsprepost_mcp" / "web" / "static")
            self.assertIn('id="refinedBlastWorkbenchRoot"', (static_root() / "index.html").read_text(encoding="utf-8"))
        finally:
            if original is None:
                index.unlink(missing_ok=True)
            else:
                index.write_text(original, encoding="utf-8")
            if not had_dist:
                try:
                    dist.rmdir()
                except OSError:
                    pass


if __name__ == "__main__":
    unittest.main()
