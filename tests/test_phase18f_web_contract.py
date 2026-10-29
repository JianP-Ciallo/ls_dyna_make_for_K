from __future__ import annotations

import http.client
import json
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path

from lsprepost_mcp.web.app import create_server
from node_runtime import node_executable


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "lsprepost_mcp" / "web" / "static" / "index.html"
WORKBENCH_JS = ROOT / "lsprepost_mcp" / "web" / "static" / "refined_blast_workbench.js"
WORKBENCH_CSS = ROOT / "lsprepost_mcp" / "web" / "static" / "refined_blast_workbench.css"
APP_JS = ROOT / "lsprepost_mcp" / "web" / "static" / "app.js"
DIRECT_BOOT_RUNTIME = ROOT / "web" / "tests" / "refined-workbench-startup.runtime.cjs"
EXTERNAL_ACTION_RUNTIME = ROOT / "web" / "tests" / "refined-blast-external-actions.runtime.cjs"


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


def request_static(address: tuple[str, int], path: str) -> tuple[int, str]:
    connection = http.client.HTTPConnection(address[0], address[1], timeout=10)
    connection.request("GET", path)
    response = connection.getresponse()
    payload = response.read().decode("utf-8")
    connection.close()
    return response.status, payload


def test_index_has_refined_blast_entry() -> None:
    assert 'id="openRefinedBlastWorkbench"' in INDEX.read_text(encoding="utf-8")


def test_workbench_uses_only_refined_api_prefix() -> None:
    source = WORKBENCH_JS.read_text(encoding="utf-8")
    assert "/api/refined-building-blast/" in source
    assert "/api/editor/" not in source
    assert "cityDraft" not in source


def test_workbench_declares_deferred_create_and_bounded_save_lifecycle() -> None:
    source = WORKBENCH_JS.read_text(encoding="utf-8")

    autosave = WORKBENCH_JS.with_name('refined_blast_autosave.js').read_text(encoding='utf-8')
    assert 'const SAVE_TIMEOUT_MS = 10000' in autosave
    assert '"refined_blast_create@2"' in autosave
    assert "saveAbortController" in source
    assert "activeSession.saveAbortController?.abort()" in source


def test_guided_canvas_reduces_the_always_visible_workbench_chrome() -> None:
    """The refined route must keep the preview primary instead of restoring the old three-panel wall."""
    source = WORKBENCH_JS.read_text(encoding="utf-8")
    styles = WORKBENCH_CSS.read_text(encoding="utf-8")

    assert 'class="refined-blast-step-rail"' in source
    assert 'data-refined-inspector-tab="config"' in source
    assert 'data-refined-inspector-tab="checks"' in source
    assert 'data-refined-layer-popover' in source
    assert 'data-refined-layer-toggle' in source
    assert 'class="refined-blast-external-menu"' in source
    assert "grid-template-columns: 340px minmax(0, 1fr)" in styles
    assert "@media (max-width: 1180px)" in styles
    assert "[hidden] { display: none !important; }" in styles
    assert "data-refined-inspector-toggle" in source
    assert ".refined-blast-inspector.is-collapsed" in styles
    assert 'role="tabpanel"' in source
    assert 'aria-controls="refinedBlastConfigPanel"' in source


def test_first_use_flow_explains_project_creation_and_next_actions() -> None:
    source = WORKBENCH_JS.read_text(encoding="utf-8")

    assert 'data-refined-onboarding' in source
    assert "选择工况" in source
    assert "创建项目并保存草稿" in source
    assert "刷新轻量预览" in source
    assert "验证并生成" in source
    assert "首次保存将自动创建独立项目" in source
    assert 'data-refined-new-scenario' in source


def test_uncreated_edits_wait_for_explicit_project_creation() -> None:
    source = WORKBENCH_JS.read_text(encoding="utf-8")
    schedule = source.split("function scheduleAutosave", 1)[1].split("function showSaveFailure", 1)[0]

    assert "persistUncreatedSession(session)" in schedule
    assert "if (!session.projectId) return;" in schedule


def test_three_building_scenarios_and_load_propagation_are_explained() -> None:
    source = WORKBENCH_JS.read_text(encoding="utf-8")

    for label in ("商业超市", "住宅建筑", "地铁入口"):
        assert label in source
    for explanation in ("ALE/FSI 空气域传播", "导入压力时程", "LBE 等效面载荷"):
        assert explanation in source
    assert "data-refined-scenario-explanation" in source


def test_all_eight_steps_render_authoritative_controls_instead_of_empty_placeholders() -> None:
    source = WORKBENCH_JS.read_text(encoding="utf-8")

    assert "function renderWorkbenchStepFields" in source
    assert "workbenchFieldsForStep(state, step)" in source
    assert "本步骤只显示当前资产与结构体系适用的字段；暂无适用字段时无需配置。" not in source


def test_refined_route_restores_latest_project_and_uncreated_session_draft() -> None:
    source = APP_JS.read_text(encoding="utf-8")

    assert 'readLatestProjectId(window.localStorage)' in source
    assert 'readSessionDraft(window.sessionStorage)' in source
    assert "restoreProject: Boolean(projectId)" in source


def test_uncreated_session_draft_is_restored_only_after_capability_schema_loads() -> None:
    source = WORKBENCH_JS.read_text(encoding="utf-8")
    mount = source.split("export function mountRefinedBlastWorkbench", 1)[1]
    load = source.split("async function loadCapabilities", 1)[1].split("function installShellHandlers", 1)[0]

    assert "pendingSessionDraft" in mount
    assert load.index("setSchema(") < load.index("replaceDraft(session.pendingSessionDraft)")


def test_guided_canvas_keeps_expert_json_collapsed_by_default() -> None:
    source = WORKBENCH_JS.read_text(encoding="utf-8")

    assert 'className = "refined-blast-advanced"' in source
    assert 'summary.textContent = "高级参数"' in source
    assert 'details.open = false' in source
    assert 'schemaType === "array"' in source
    assert 'schemaType === "object"' in source
    assert 'input.setAttribute?.("aria-invalid", "true")' in source
    assert 'schemaValueIsValid?.(value, descriptor)' in source


def test_step_statuses_are_exposed_as_text_and_accessible_names() -> None:
    source = WORKBENCH_JS.read_text(encoding="utf-8")

    assert 'data-refined-step-status' in source
    assert 'button.setAttribute?.("aria-label", `转到配置步骤 ${step}: ${label}，${statusLabel}`)' in source


def test_preview_container_preserves_interactive_descendant_semantics() -> None:
    source = WORKBENCH_JS.read_text(encoding="utf-8")

    assert 'role="region" data-refined-preview-canvas' in source
    assert 'role="img" data-refined-preview-canvas' not in source
    assert "data-refined-metric-summary" in source
    assert "metricSummary.textContent" in source


def test_step_rail_surfaces_configuration_and_validation_state() -> None:
    source = WORKBENCH_JS.read_text(encoding="utf-8")

    assert "function renderStepStates" in source
    assert "button.dataset.status" in source
    assert "data-refined-locate" in source


def test_guided_canvas_exposes_only_provider_owned_blast_source_positions() -> None:
    source = WORKBENCH_JS.read_text(encoding="utf-8")

    assert 'lbe_segment: "load_provider.provider_input.source.position_m"' in source
    assert 'explicit_ale_fsi: "load_provider.provider_input.charge.position_m"' in source
    assert "imported_pressure_history" not in source.split("const BLAST_SOURCE_POSITION_PATHS", 1)[1].split("};", 1)[0]
    assert "blastSourceEditorForDraft" in source
    assert "onCommit" in source


def test_workbench_back_control_restores_the_legacy_route() -> None:
    source = WORKBENCH_JS.read_text(encoding="utf-8")
    app_source = APP_JS.read_text(encoding="utf-8")
    assert 'window.history.replaceState({ workspace: "legacy" }, "", "/")' in source
    assert "if (isRefinedBlastWorkbenchPath(window.location.pathname))" in app_source


def test_refined_route_uses_server_verified_project_identity_for_reload() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert "function refinedBlastProjectIdFromLocation()" in source
    assert "projectId: refinedBlastProjectIdFromLocation()" in source


def test_direct_refined_boot_short_circuits_legacy_initializers() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    boot = source.split("async function boot()", 1)[1].split("boot().catch(showError)", 1)[0]
    direct_route = boot.index("if (isRefinedBlastWorkbenchPath(window.location.pathname))")
    direct_return = boot.index("return;", direct_route)

    for legacy_initializer in (
        "setupWorkbenchNavigation();",
        "await loadConfig();",
        "await loadScenes();",
        "await loadAssemblyCatalogs();",
        "await loadProjects();",
    ):
        assert direct_return < boot.index(legacy_initializer)


def test_both_refined_route_forms_serve_and_select_the_isolated_workbench() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert 'pathname === "/refined-building-blast" || pathname === "/refined-building-blast/"' in source

    with web_test_server() as address:
        for path in ("/refined-building-blast", "/refined-building-blast/"):
            status, body = request_static(address, path)
            assert status == 200
            assert 'id="refinedBlastWorkbenchRoot"' in body


def test_direct_refined_startup_mounts_without_legacy_state_or_tdz_error() -> None:
    result = subprocess.run(
        [str(node_executable()), "--experimental-vm-modules", str(DIRECT_BOOT_RUNTIME), str(APP_JS)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_refined_external_actions_require_a_fresh_browser_confirmation_without_cancel_fetch() -> None:
    """Deleting the explicit prompt or issuing an action after cancel must fail this runtime contract."""

    def run(case: str) -> dict[str, object]:
        result = subprocess.run(
            [str(node_executable()), str(EXTERNAL_ACTION_RUNTIME), case],
            cwd=str(ROOT), text=True, capture_output=True, timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    cancelled = run("cancel")
    assert cancelled["result"] is False
    assert cancelled["requests"] == []

    for invalid_identity in ("dirty", "stale"):
        rejected = run(invalid_identity)
        assert rejected["result"] is False
        assert rejected["requests"] == []

    confirmed = run("confirm")
    assert confirmed["result"] is True
    assert [row["url"].rsplit("/", 1)[-1] for row in confirmed["requests"]] == [
        "action-confirmations", "open-lsprepost",
    ]
    assert confirmed["requests"][1]["body"] == {
        "confirmation_nonce": "nonce-1", "scenario_id": "scenario-1", "generated_revision": 2,
        "artifact_fingerprint": "artifact", "package_fingerprint": "package",
    }
