import { writeLatestProjectId, writeSessionDraft, clearRecovery, safeStorageWrite } from "./refined_blast_persistence.js";
import { saveCurrentDraft } from "./refined_blast_autosave.js";
import { fetchJson } from "./refined_blast_http.js";
import { createRefinedBlastStore, renderSchemaFields } from "./refined_blast_state.js";
import { renderRefinedBlastPreview } from "./refined_blast_viewer.js";

const REFINED_BLAST_API_PREFIX = "/api/refined-building-blast/";
const NAVIGATION_SECTIONS = [
  "建筑空间与洞口",
  "结构体系与承重构件",
  "钢筋、钢构或组合连接",
  "非承重构件",
  "材料、截面和失效模型",
  "网格、地面与局部加密",
  "载荷、爆源、空气域、边界与输出",
  "检查、预算、确认与生成"
];

const NAVIGATION_SHORT_LABELS = [
  "建筑", "结构", "连接", "构件", "材料", "网格", "爆源", "检查",
];

const GEOMETRY_FIELD_LABELS = {
  balcony_depth_m: "阳台进深", enclosure_height_m: "围护高度",
  entrance_height_m: "入口高度", entrance_width_m: "入口宽度",
  height_m: "建筑高度", length_m: "建筑长度", width_m: "建筑宽度",
  platform_height_m: "平台高度", roof_thickness_m: "屋面厚度",
  tower_count: "塔楼数量", tower_height_m: "塔楼高度",
  tower_length_m: "塔楼长度", tower_spacing_m: "塔楼间距",
  tower_width_m: "塔楼宽度", wall_thickness_m: "墙体厚度",
};

const STEP_STATUS_LABELS = {
  pending: "待配置", configured: "已配置", warning: "有警告", error: "有错误",
};

const PROVIDER_LABELS = {
  solver_complete_ale_fsi: "真实 ALE/FSI（LS-DYNA）",
  explicit_ale_fsi: "显式 ALE/FSI 中性候选",
  lbe_segment: "LBE 面载荷候选",
  imported_pressure_history: "导入压力时程",
};

const BUILDING_SCENARIOS = {
  commercial_supermarket_detailed_building: {
    label: "商业超市",
    summary: "大跨钢-混凝土混合结构，包含承重柱、屋盖、围护和实体地坪。",
    propagation: "ALE/FSI 空气域传播",
    recommendation: "适合研究空气冲击波与大跨结构、围护及承重构件的耦合响应。",
  },
  residential_community_detailed_building: {
    label: "住宅建筑",
    summary: "多层住宅实体墙、楼板、梁柱与门窗洞口组成的居住建筑。",
    propagation: "导入压力时程",
    recommendation: "适合把经过审查的压力—时间曲线施加到住宅外表面。",
  },
  subway_entrance_detailed_building: {
    label: "地铁入口",
    summary: "实体入口外壳、顶板、侧墙、地坪及地下过渡段组成的交通设施。",
    propagation: "LBE 等效面载荷",
    recommendation: "适合外部爆炸快速评估；需要完整空气传播时可改选真实 ALE/FSI。",
  },
};

const PROVIDER_DESCRIPTIONS = {
  solver_complete_ale_fsi: "显式建立可见空气域和 TNT 实体，通过 ALE/FSI 将爆炸能量传给建筑。",
  explicit_ale_fsi: "用于中性候选检查；生成前仍需工程化材料、边界和耦合复核。",
  lbe_segment: "不显式求解整块空气域，把爆炸效应换算为目标表面的等效压力载荷。",
  imported_pressure_history: "读取外部压力—时间曲线并施加到选定结构表面。",
};

const BLAST_SOURCE_POSITION_PATHS = {
  lbe_segment: "load_provider.provider_input.source.position_m",
  explicit_ale_fsi: "load_provider.provider_input.charge.position_m",
  solver_complete_ale_fsi: "load_provider.provider_input.charge_position_m",
};

const PREVIEW_LAYERS = [
  { id: "cavities_openings", label: "空腔与洞口" },
  { id: "structure", label: "主体结构与建筑网格" },
  { id: "reinforcement_connections", label: "钢筋与连接" },
  { id: "nonstructural", label: "非承重构件" },
  { id: "exposed_surfaces", label: "内外流体暴露面" },
  { id: "blast_source", label: "爆源与起爆点" },
  { id: "fluid_domain", label: "Active air 与空气网格" },
  { id: "boundaries", label: "空气域边界候选" },
  { id: "support_ground", label: "基础、支承地面与地面网格" }
];

let mountedRoot = null;
let capabilitiesRequest = null;
let refinedBlastStore = null;
let mountedInstanceToken = 0;
let activeSession = null;
const AUTOSAVE_DELAY_MS = 350;


function sessionIsActive(session) { return activeSession === session && !session.detached && mountedRoot === session.root; }

function optionalBrowserStorage(options, key) {
  if (Object.hasOwn(options, key)) return options[key];
  try { return window[key]; }
  catch (_) { return null; }
}

function persistUncreatedSession(session) {
  if (!sessionIsActive(session) || session.projectId) return;
  const state = session.store.getState();
  if (!state.asset_id || !state.draft) return;
  writeSessionDraft(session.sessionStorage, {
    asset_id: state.asset_id,
    building: state.building,
    draft: state.draft,
  });
}

export function buildingDefinitionPolicy(candidate = {}) {
  const saved = typeof candidate?.project_id === "string" && Boolean(candidate.project_id);
  return {
    locked: saved && candidate?.building_compilation_state === "compiled",
    requires_copy: saved,
  };
}

function beginBuildingEditCopy(root, session, { confirmMutation = false } = {}) {
  if (!sessionIsActive(session)) return false;
  const state = session.store.getState();
  const policy = buildingDefinitionPolicy(state);
  if (!policy.requires_copy) return true;
  if (confirmMutation) {
    const reason = policy.locked
      ? "当前项目已生成 K 包，建筑定义已冻结。"
      : "当前草稿已保存为独立项目。";
    const accepted = window.confirm?.(
      `${reason}继续修改会创建可编辑副本，原项目保持不变。是否继续？`,
    );
    if (accepted !== true) return false;
  }
  const source = { project_id: state.project_id, revision: state.revision };
  if (session.timer !== null) clearTimeout(session.timer);
  session.timer = null;
  session.queued = false;
  session.saveAbortController?.abort();
  session.restoreAbortController?.abort();
  session.previewAbortController?.abort();
  session.validationAbortController?.abort();
  for (const controller of session.acknowledgementAbortControllers.values()) controller.abort();
  const detached = session.store.beginBuildingEditCopy();
  session.projectId = null;
  session.projectMetadata = null;
  session.restoreProject = false;
  session.persistedDraftRevision = null;
  session.generated = null;
  session.saveError = null;
  session.copySource = source;
  writeLatestProjectId(session.localStorage, null);
  writeSessionDraft(session.sessionStorage, {
    asset_id: detached.asset_id,
    building: detached.building,
    draft: detached.draft,
  });
  window.history.replaceState(
    { workspace: "refined-blast" }, "", "/refined-building-blast",
  );
  clearRenderedPreview(root, session, "已创建可编辑副本；请刷新轻量预览。");
  renderSaveState(root, false, session);
  renderValidationState(root, session);
  return true;
}


function scheduleAutosave(root, session = activeSession) {
  if (!sessionIsActive(session)) return;
  persistUncreatedSession(session);
  session.generated = null;
  clearRenderedPreview(root, session, "草稿尚未持久化；预览已失效。");
  renderSaveState(root, false, session);
  renderValidationState(root, session);
  if (!session.projectId) return;
  if (session.timer !== null) clearTimeout(session.timer);
  session.timer = setTimeout(() => {
    session.timer = null;
    runAutosave(root, session).catch(() => {});
  }, AUTOSAVE_DELAY_MS);
}

function showSaveFailure(root, error) {
  const summary = root.querySelector(".refined-blast-validation-panel .summary");
  const timedOut = error?.code === "save_timeout";
  if (summary) summary.textContent = timedOut
    ? "草稿保存超时；配置仍保留，可直接重试。"
    : "草稿保存失败；请处理错误后重试。";
  const conflict = root.querySelector("#refinedBlastConflict");
  if (conflict) conflict.textContent = timedOut
    ? "保存请求已超时并取消；预览和生成保持禁用，重试不会创建重复项目。"
    : "草稿保存失败，预览和生成已保持禁用。";
}

async function runAutosave(root, session = activeSession) {
  if (!sessionIsActive(session) || session.store.getState().conflict?.blocking) return;
  if (session.inFlight) { session.queued = true; return session.inFlight; }
  const issuedDraftRevision = session.store.getState().draft_revision;
  session.inFlight = (async () => {
    renderSaveState(root, true);
    try {
      const savedState = await saveCurrentDraft(session, sessionIsActive);
      if (savedState?.conflict?.blocking) throw new Error("draft save conflict");
      session.persistedDraftRevision = issuedDraftRevision;
      session.saveError = null;
      if (sessionIsActive(session)) renderCurrentSchema(root);
      return true;
    } catch (error) {
      if (error?.name === "AbortError" && sessionIsActive(session) && !session.projectId) {
        session.saveError = null;
        return false;
      }
      session.saveError = error;
      if (sessionIsActive(session)) {
        clearRenderedPreview(root, session, "草稿保存失败；旧预览已清除。");
        showSaveFailure(root, error);
      }
      throw error;
    } finally {
      if (sessionIsActive(session)) {
        renderSaveState(root);
        renderValidationState(root, session);
      }
    }
  })();
  try { await session.inFlight; }
  finally { session.inFlight = null; }
  if (sessionIsActive(session) && (session.queued || session.store.getState().draft_revision !== issuedDraftRevision)) {
    session.queued = false;
    scheduleAutosave(root, session);
  }
}

function hasUnpersistedDraft(session) {
  return Boolean(session.saveError)
    || session.persistedDraftRevision !== session.store.getState().draft_revision;
}

async function flushSave(root, session = activeSession) {
  if (!sessionIsActive(session)) return;
  if (session.flushPromise) {
    if (session.inFlight) session.queued = true;
    return session.flushPromise;
  }
  session.flushPromise = (async () => {
    while (sessionIsActive(session)) {
      if (session.timer !== null) { clearTimeout(session.timer); session.timer = null; }
      if (session.inFlight) { session.queued = true; await session.inFlight; continue; }
      const issuedDraftRevision = session.store.getState().draft_revision;
      await runAutosave(root, session);
      if (!sessionIsActive(session)) return;
      if (session.timer !== null || session.queued || session.store.getState().draft_revision !== issuedDraftRevision) continue;
      return;
    }
  })();
  try { await session.flushPromise; }
  finally { if (session.flushPromise) session.flushPromise = null; }
}

function buildWorkbenchShell() {
  const shell = document.createElement("section");
  shell.className = "refined-blast-shell";
  shell.tabIndex = -1;
  shell.innerHTML = `
    <header class="topbar refined-blast-topbar">
      <div class="refined-blast-title-block">
        <h1 id="refinedBlastWorkbenchTitle">精细化建筑爆炸工作台</h1>
        <p>配置工况 · 预览模型 · 生成 K 包</p>
      </div>
      <div class="refined-blast-project-status" aria-label="项目状态">
        <span data-refined-project-summary>未创建项目</span>
        <span data-refined-save-summary>草稿未保存</span>
        <span data-refined-check-summary>尚未检查</span>
      </div>
      <div class="refined-blast-top-actions">
    <details class="refined-blast-onboarding workbench-menu" data-workbench-menu data-refined-onboarding aria-label="首次使用流程">
      <summary>使用指引</summary>
      <div class="workbench-menu-content">
      <ol>
        <li data-refined-workflow-step="select"><b>1</b><span>选择工况<small>建筑、结构和载荷方式</small></span></li>
        <li data-refined-workflow-step="save"><b>2</b><span>创建项目并保存草稿<small>首次保存将自动创建独立项目</small></span></li>
        <li data-refined-workflow-step="preview"><b>3</b><span>刷新轻量预览<small>不编译完整 K 文件</small></span></li>
        <li data-refined-workflow-step="validate"><b>4</b><span>验证并生成<small>检查通过后才生成 K 包</small></span></li>
      </ol>
      </div>
    </details>
        <button class="secondary-button" type="button" data-refined-new-scenario>新建工况</button>
        <button id="refinedBlastBack" class="secondary-button" type="button" data-refined-back aria-label="返回原工作台">返回原工作台</button>
      </div>
    </header>
    <div class="refined-blast-layout" aria-labelledby="refinedBlastWorkbenchTitle">
      <section class="viewport-panel refined-blast-preview" aria-label="分层预览">
        <div class="viewport-toolbar refined-blast-preview-toolbar">
          <div>
            <strong>模型预览</strong>
            <span id="refinedBlastPreviewStatus" class="panel-note">正在载入配置…</span>
          </div>
          <div class="refined-blast-camera-controls" aria-label="相机控制">
            <button class="secondary-button refined-blast-inspector-toggle" type="button" data-refined-inspector-toggle aria-expanded="true" aria-controls="refinedBlastInspector">配置</button>
            <button id="refinedBlastCameraFit" class="secondary-button" type="button" data-refined-camera="iso" aria-label="适配预览相机">适配</button>
            <details class="workbench-menu refined-blast-camera-menu" data-workbench-menu><summary>视角</summary><div class="workbench-menu-content">
            <button id="refinedBlastCameraIso" class="secondary-button" type="button" data-refined-camera="iso" aria-label="切换到等轴相机">等轴</button>
            <button id="refinedBlastCameraFront" class="secondary-button" type="button" data-refined-camera="front" aria-label="切换到正视相机">正视</button>
            <button id="refinedBlastCameraTop" class="secondary-button" type="button" data-refined-camera="top" aria-label="切换到俯视相机">俯视</button>
            </div></details>
          </div>
        </div>
        <div class="refined-blast-preview-stage">
          <div class="refined-blast-preview-canvas" role="region" data-refined-preview-canvas aria-label="精细化建筑爆炸分层预览区">
            <span>预览将在创建独立项目后显示。</span>
          </div>
          <button class="secondary-button refined-blast-layer-toggle" type="button" data-refined-layer-toggle aria-expanded="false" aria-controls="refinedBlastLayerPopover">图层 <span data-refined-layer-count>9/9</span></button>
          <section id="refinedBlastLayerPopover" class="refined-blast-layer-popover" data-refined-layer-popover hidden aria-labelledby="refinedBlastLayersHeading">
            <div class="refined-blast-popover-heading"><h2 id="refinedBlastLayersHeading">预览图层</h2><button type="button" class="secondary-button" data-refined-layer-close aria-label="关闭图层面板">关闭</button></div>
            <div class="refined-blast-layer-grid">
              ${PREVIEW_LAYERS.map((layer) => `<span class="refined-blast-layer-option"><input id="refinedBlastLayer-${layer.id}" type="checkbox" checked data-refined-layer="${layer.id}"><label for="refinedBlastLayer-${layer.id}">${layer.label}</label></span>`).join("")}
            </div>
          </section>
        </div>
        <details class="refined-blast-metrics"><summary>规模摘要 <span data-refined-metric-summary>尚未生成估算</span></summary><div class="summary refined-blast-estimate" data-refined-preview-counts>当前草稿没有估算。</div></details>
      </section>
      <aside id="refinedBlastInspector" class="sidebar refined-blast-inspector" aria-label="配置与验证">
      <div class="refined-blast-step-rail" aria-label="精细化建筑爆炸配置导航">
        <nav aria-label="工况配置步骤">
          <ol class="refined-blast-nav-list">
            ${NAVIGATION_SECTIONS.map((label, index) => `<li><button id="refinedBlastSection-${index + 1}" class="refined-blast-nav-button${index === 0 ? " is-active" : ""}" type="button" data-refined-section="${index + 1}" data-status="pending" aria-label="转到配置步骤 ${index + 1}: ${label}，待配置"${index === 0 ? ' aria-current="step"' : ""}><span>${String(index + 1).padStart(2, "0")}</span><b>${NAVIGATION_SHORT_LABELS[index]}</b><em data-refined-step-status>待配置</em><small>${label}</small></button></li>`).join("")}
          </ol>
        </nav>
      </div>
        <div class="inspector-heading">
          <div><span class="section-kicker">当前步骤</span><strong data-refined-step-title>01 · 建筑空间与洞口</strong></div>
          <div class="refined-blast-inspector-tabs" role="tablist" aria-label="配置与检查">
            <button id="refinedBlastConfigTab" type="button" role="tab" aria-selected="true" aria-controls="refinedBlastConfigPanel" tabindex="0" data-refined-inspector-tab="config">配置</button>
            <button id="refinedBlastChecksTab" type="button" role="tab" aria-selected="false" aria-controls="refinedBlastChecksPanel" tabindex="-1" data-refined-inspector-tab="checks">检查</button>
          </div>
        </div>
        <section id="refinedBlastConfigPanel" class="refined-blast-schema-panel" role="tabpanel" aria-labelledby="refinedBlastConfigTab" data-refined-schema-panel data-refined-inspector-panel="config">
          <h2>当前字段</h2>
          <p class="panel-note">尚未载入适用字段；请选择建筑资产和载荷提供器。</p>
        </section>
        <div id="refinedBlastChecksPanel" class="refined-blast-checks" role="tabpanel" aria-labelledby="refinedBlastChecksTab" data-refined-inspector-panel="checks" hidden>
          <section class="refined-blast-validation-panel" data-refined-validation-panel>
            <div class="refined-blast-section-heading"><h2>即时检查</h2><button class="secondary-button" type="button" data-refined-validate>验证当前版本</button></div>
            <div class="summary" data-refined-validation-status aria-live="polite">等待独立项目、草稿和能力描述。</div>
            <div id="refinedBlastConflict" class="refined-blast-conflict" role="alert" aria-live="assertive" aria-atomic="true"></div>
            <div class="refined-blast-finding-list" data-refined-validation-findings aria-live="polite"></div>
          </section>
          <section class="refined-blast-validation-panel" data-refined-budget-panel>
            <h2>预算与确认</h2>
            <p class="panel-note">确认与当前 validation/revision 绑定。</p>
            <div class="refined-blast-budget-list" data-refined-budget-rows></div>
          </section>
        </div>
      </aside>
    </div>
    <footer class="refined-blast-action-bar" aria-label="独立工况操作">
      <span class="refined-blast-save-state" data-refined-action-status>尚未保存</span>
      <div class="refined-blast-action-group">
        <button id="refinedBlastSave" class="secondary-button" type="button" data-refined-save disabled>创建项目并保存草稿</button>
        <button id="refinedBlastPreview" class="secondary-button" type="button" data-refined-preview>刷新预览</button>
      </div>
      <div class="refined-blast-action-group refined-blast-action-primary">
        <button id="refinedBlastValidate" class="secondary-button" type="button" data-refined-validate>验证</button>
        <button id="refinedBlastGenerate" type="button" data-refined-generate disabled aria-describedby="refinedBlastConflict">生成 K 包</button>
      </div>
      <details class="refined-blast-external-menu" data-workbench-menu>
        <summary>更多操作</summary>
        <div>
          <button id="refinedBlastOpenLsprepost" class="secondary-button" type="button" data-refined-open-lsprepost disabled aria-describedby="refinedBlastConflict">打开 LS-PrePost</button>
          <button id="refinedBlastLaunchLsdyna" class="secondary-button" type="button" data-refined-launch-lsdyna disabled aria-describedby="refinedBlastConflict">启动 LS-DYNA</button>
      <button id="refinedBlastAssessment" type="button" class="secondary-button refined-damage-entry" data-refined-assessment aria-haspopup="dialog" aria-controls="refinedDamagePanel">损伤评估</button>
        </div>
      </details>
      <span data-refined-external-status aria-live="polite"></span>
    </footer>
    <dialog id="refinedDamagePanel" class="refined-damage-panel" data-damage-panel aria-labelledby="refinedDamageTitle">
      <header class="refined-damage-heading">
        <div><span class="section-kicker">求解后分析</span><h2 id="refinedDamageTitle">建筑与地面损伤评估</h2></div>
        <button type="button" class="secondary-button" data-damage-close aria-label="关闭损伤评估面板">关闭</button>
      </header>
      <div class="refined-damage-content">
        <section class="refined-damage-card refined-damage-demo-intro">
          <h3>第一次使用？先看一个完整案例</h3>
          <p>进入三层建筑与地面的合成演示，修改爆源并重新评估，查看构件着色与报告。无需真实求解文件，不改动当前项目。</p>
          <button type="button" data-damage-demo aria-haspopup="dialog" aria-controls="refinedDamageDemo">查看演示</button>
        </section>
        <p class="refined-damage-project" data-damage-project>当前项目：未选择</p>
        <section class="refined-damage-card" aria-labelledby="refinedDamageConditions">
          <h3 id="refinedDamageConditions">评估条件</h3>
          <p data-damage-capability>评估模块：待检查</p>
          <p data-damage-source>求解结果：待核验</p>
          <p class="panel-note">只读取当前项目已有结果，不重新建模、不启动求解器。</p>
          <div class="refined-damage-actions">
            <button type="button" data-damage-start disabled>开始评估</button>
            <button type="button" class="secondary-button" data-damage-refresh>刷新状态与报告</button>
          </div>
          <p class="refined-damage-status" role="status" aria-live="polite" aria-atomic="true" data-damage-status>打开面板不会自动执行评估。</p>
        </section>
        <section class="refined-damage-card" aria-labelledby="refinedDamageResultTitle">
          <h3 id="refinedDamageResultTitle">评估结果</h3>
          <p data-damage-result>尚未评估</p>
          <div class="refined-damage-subjects">
            <div><h4>建筑</h4><p data-damage-building>待评估</p></div>
            <div><h4>地面</h4><p data-damage-ground>待评估</p></div>
          </div>
          <details class="refined-damage-evidence" open><summary>提示与证据不足原因</summary><div data-damage-issues></div></details>
        </section>
        <section class="refined-damage-card" aria-labelledby="refinedDamageReportTitle">
          <h3 id="refinedDamageReportTitle">报告与明细</h3>
          <div class="refined-damage-actions">
            <a class="secondary-button" data-damage-view aria-disabled="true" tabindex="-1">查看报告</a>
            <a class="secondary-button" data-damage-download aria-disabled="true" tabindex="-1">下载报告</a>
            <a class="secondary-button" data-damage-building-csv aria-disabled="true" tabindex="-1">建筑明细 CSV</a>
            <a class="secondary-button" data-damage-ground-csv aria-disabled="true" tabindex="-1">地面明细 CSV</a>
          </div>
          <p class="panel-note">仅提供已登记产物。最新报告可能属于较早版本，请核对报告中的求解记录。</p>
        </section>
      </div>
      <footer class="refined-damage-disclaimer">研究参考 · 不能替代专业结构安全鉴定；等级 0 不代表建筑安全。</footer>
    </dialog>
    <dialog id="refinedDamageDemo" class="refined-damage-demo" data-damage-demo-panel aria-labelledby="refinedDamageDemoTitle">
      <header class="refined-damage-demo-heading"><div><strong id="refinedDamageDemoTitle">损伤评估 · 交互演示</strong><span>合成数据演示，不修改当前项目</span></div><button type="button" class="secondary-button" data-damage-demo-exit>退出演示，返回原项目</button></header>
      <div class="refined-damage-demo-frame-host" data-damage-demo-host></div>
    </dialog>
  `;
  return shell;
}

function schemaForWorkbench(capabilities, assets, selectedAssetId) {
  const asset = (Array.isArray(assets) ? assets : []).find((row) => row?.asset_id === selectedAssetId)
    ?? (Array.isArray(assets) ? assets[0] ?? {} : {});
  const providers = Object.fromEntries((capabilities.providers ?? []).map((provider) => {
    return [provider.provider_id, {
      supported_scenario_kinds: provider.supported_scenario_kinds ?? provider.capabilities?.scenario_kinds ?? [],
      provider_input_schema: provider.input_schema ?? provider.schema?.input_schema ?? { type: "object", additionalProperties: false, properties: {} },
      default_input: provider.default_input ?? {},
      fields: []
    }];
  }));
  return {
    assets: Array.isArray(assets) ? assets : [],
    asset_id: asset.asset_id ?? null,
    providers,
    scenario_draft_schema: capabilities.scenario_draft_schema ?? null,
    workbench_schema: capabilities.workbench_schema ?? {
      schema_version: "refined_blast.workbench_schema@1",
      sections: [],
      fields: [],
    },
  };
}

function workbenchFieldsForStep(state, step) {
  const workbench = state?.activeSchema?.workbench_schema ?? {};
  const sectionId = (workbench.sections ?? []).find((section) => Number(section?.step) === Number(step))?.section_id;
  if (!sectionId) return [];
  const assetId = state?.asset_id;
  const structuralSystem = state?.building?.structural_system;
  const providerId = state?.draft?.load_provider?.provider_id;
  return (workbench.fields ?? []).filter((field) => {
    if (field?.section_id !== sectionId || field?.editable !== true) return false;
    const applicability = field.applicability ?? {};
    if (Array.isArray(applicability.asset_ids) && !applicability.asset_ids.includes(assetId)) return false;
    if (Array.isArray(applicability.structural_systems) && !applicability.structural_systems.includes(structuralSystem)) return false;
    if (Array.isArray(applicability.provider_ids) && !applicability.provider_ids.includes(providerId)) return false;
    return true;
  }).map((field) => {
    const resolved = { ...field };
    if (field.schema_by_provider?.[providerId]) resolved.schema = field.schema_by_provider[providerId];
    if (Array.isArray(field.enum_by_asset?.[assetId])) {
      resolved.schema = { ...(resolved.schema ?? {}), enum: field.enum_by_asset[assetId] };
    }
    return resolved;
  });
}

function setDraftPath(draft, path, rawValue) {
  const parts = path.split(".");
  let target = draft;
  for (const part of parts.slice(0, -1)) {
    if (!target[part] || typeof target[part] !== "object") target[part] = {};
    target = target[part];
  }
  if (typeof rawValue !== "string") { target[parts.at(-1)] = rawValue; return; }
  try { target[parts.at(-1)] = rawValue.trim().startsWith("{") || rawValue.trim().startsWith("[") ? JSON.parse(rawValue) : rawValue; }
  catch (_) { target[parts.at(-1)] = rawValue; }
}

function draftPathValue(draft, path) {
  return path.split(".").reduce((current, part) => current?.[part], draft);
}

function blastSourceEditorForDraft(root, session) {
  const state = session.store.getState();
  const providerId = state.draft.load_provider?.provider_id;
  const path = BLAST_SOURCE_POSITION_PATHS[providerId];
  if (!path) return null;
  const position = draftPathValue(state.draft, path);
  if (!Array.isArray(position) || position.length !== 3 || !position.every((value) => Number.isFinite(Number(value)))) return null;
  return {
    position_m: position.map(Number),
    drag_step_m: 0.01,
    onCommit(nextPosition) {
      if (!sessionIsActive(session) || !Array.isArray(nextPosition) || nextPosition.length !== 3) return;
      const before = session.store.getState().draft_revision;
      session.store.updateDraft((draft) => setDraftPath(draft, path, nextPosition.map(Number)));
      if (session.store.getState().draft_revision !== before) {
        renderCurrentSchema(root);
        scheduleAutosave(root, session);
      }
    },
  };
}

function formValue(input) {
  let value;
  if (input.dataset.refinedSchemaType === "boolean") value = Boolean(input.checked);
  else if (input.dataset.refinedSchemaType === "number" || input.dataset.refinedSchemaType === "integer") value = Number(input.value);
  else if (input.dataset.refinedSchemaType === "array" || input.dataset.refinedSchemaType === "object") value = JSON.parse(input.value);
  else value = input.value;
  const descriptor = JSON.parse(input.dataset.refinedSchema ?? "{}");
  if (!refinedBlastStore?.schemaValueIsValid?.(value, descriptor)) throw new Error("value does not match published schema");
  return value;
}

function setSchemaInputValueAtPath(target, path, input) {
  const vectorIndex = Number(input.dataset.refinedVectorIndex);
  const descriptor = JSON.parse(input.dataset.refinedSchema ?? "{}");
  const vectorSize = Number(descriptor.minItems);
  if (Number.isInteger(vectorIndex) && vectorIndex >= 0
      && Number.isInteger(vectorSize) && vectorSize > 0
      && vectorSize === Number(descriptor.maxItems) && vectorIndex < vectorSize) {
    const parts = path.split(".");
    let current = target;
    for (const part of parts.slice(0, -1)) current = current?.[part];
    const leaf = parts.at(-1);
    const vector = Array.isArray(current?.[leaf]) && current[leaf].length === vectorSize
      ? current[leaf].slice(0, vectorSize) : Array(vectorSize).fill(0);
    vector[vectorIndex] = Number(input.value);
    if (!refinedBlastStore?.schemaValueIsValid?.(vector, descriptor)) throw new Error("vector does not match published schema");
    setDraftPath(target, path, vector);
    return;
  }
  setDraftPath(target, path, formValue(input));
}

function renderWorkbenchStepFields(root, session, state, step, excludedPaths = []) {
  const excluded = new Set(excludedPaths);
  const rows = workbenchFieldsForStep(state, step)
    .filter((field) => !excluded.has(field.path))
    .map((field) => ({
      ...field,
      section: "workbench",
      label: `${(field.path.startsWith("building.legacy_geometry.") ? GEOMETRY_FIELD_LABELS[field.path.split(".").at(-1)] : null) ?? field.label_zh ?? field.path}${field.unit ? ` (${field.unit})` : ""}`,
    }));
  const fields = renderSchemaFields(
    "workbench",
    { fields: rows },
    { building: state.building, draft: state.draft },
  );
  fields.querySelectorAll?.("[data-refined-draft-path]").forEach((input) => {
    const path = input.dataset.refinedDraftPath ?? "";
    const buildingField = path.startsWith("building.");
    const buildingPolicy = buildingDefinitionPolicy(state);
    if (buildingField && buildingPolicy.locked) {
      input.disabled = true;
      input.title = "该项目已生成 K 包；请先复制后编辑。";
    }
    input.addEventListener("change", () => {
      if (buildingField && !beginBuildingEditCopy(root, session, { confirmMutation: true })) {
        renderCurrentSchema(root);
        return;
      }
      const before = session.store.getState().draft_revision;
      try {
        if (path.startsWith("building.")) {
          session.store.updateBuilding((building) => {
            setSchemaInputValueAtPath(building, path.slice("building.".length), input);
          });
        } else if (path.startsWith("draft.")) {
          session.store.updateDraft((draft) => {
            setSchemaInputValueAtPath(draft, path.slice("draft.".length), input);
          });
        } else {
          throw new Error("workbench field is outside the closed building/draft scopes");
        }
        input.removeAttribute?.("aria-invalid");
        input.removeAttribute?.("title");
      } catch (_) {
        input.setAttribute?.("aria-invalid", "true");
        input.setAttribute?.("title", "输入值不符合当前参数结构，未保存");
        return;
      }
      if (session.store.getState().draft_revision !== before) {
        renderCurrentSchema(root);
        scheduleAutosave(root, session);
      }
    });
  });
  return fields;
}

function fieldBelongsInAdvanced(path, schemaType) {
  if (path.endsWith(".charge_position_m")) return false;
  if ([".air_cell_size_m", ".near_field_cell_size_m", ".ground_cell_size_m", ".air_margin_m", ".air_margins_m", ".coupling_buffer_layers", ".termination_time_s"].some((suffix) => path.endsWith(suffix))) return true;
  if (schemaType === "array" || schemaType === "object") return true;
  return [".budgets.", ".selection.", ".resources.", ".fsi.", ".domain."].some((token) => path.includes(token))
    || path.endsWith(".schema_version") || path.endsWith(".unit_system");
}

function splitSchemaFields(fields) {
  const primary = document.createElement("div");
  primary.className = "refined-blast-primary-fields";
  const advancedFields = document.createElement("div");
  advancedFields.className = "refined-blast-advanced-fields";
  for (const field of Array.from(fields.children ?? [])) {
    const input = field.querySelector?.("[data-refined-draft-path]");
    (fieldBelongsInAdvanced(input?.dataset?.refinedDraftPath ?? "", input?.dataset?.refinedSchemaType) ? advancedFields : primary).append(field);
  }
  const details = document.createElement("details");
  details.className = "refined-blast-advanced";
  details.open = false;
  const summary = document.createElement("summary");
  summary.textContent = "高级参数";
  details.append(summary, advancedFields);
  return { primary, details, hasAdvanced: Boolean(advancedFields.children?.length) };
}

function renderCurrentSchema(root) {
  const panel = root.querySelector("[data-refined-schema-panel]");
  if (!panel || !refinedBlastStore) return;
  const state = refinedBlastStore.getState();
  const session = activeSession;
  const buildingPolicy = buildingDefinitionPolicy(state);
  const asset = document.createElement("select");
  asset.id = "refinedBlastAsset";
  asset.setAttribute?.("aria-label", "建筑资产");
  asset.dataset.refinedAsset = "true";
  asset.disabled = buildingPolicy.locked;
  asset.title = buildingPolicy.locked ? "该项目已生成 K 包；请先复制后编辑。" : "";
  for (const assetRow of state.activeSchema.assets ?? []) {
    const option = document.createElement("option");
    option.value = assetRow.asset_id;
    const scenario = BUILDING_SCENARIOS[assetRow.asset_id];
    option.textContent = scenario?.label ?? assetRow.asset_id;
    option.selected = assetRow.asset_id === state.asset_id;
    asset.append(option);
  }
  asset.addEventListener("change", () => {
    if (!beginBuildingEditCopy(root, session, { confirmMutation: true })) {
      renderCurrentSchema(root);
      return;
    }
    const before = refinedBlastStore.getState().draft_revision;
    refinedBlastStore.setAsset(asset.value);
    renderCurrentSchema(root);
    if (refinedBlastStore.getState().draft_revision !== before) scheduleAutosave(root, session);
  });
  const structuralSystem = document.createElement("select");
  structuralSystem.id = "refinedBlastStructuralSystem";
  structuralSystem.setAttribute?.("aria-label", "结构体系");
  structuralSystem.dataset.refinedStructuralSystem = "true";
  structuralSystem.disabled = buildingPolicy.locked;
  structuralSystem.title = buildingPolicy.locked ? "该项目已生成 K 包；请先复制后编辑。" : "";
  const selectedAsset = state.activeSchema.assets?.find((asset) => asset.asset_id === state.asset_id);
  for (const systemId of selectedAsset?.allowed_structural_systems ?? []) {
    const option = document.createElement("option");
    option.value = systemId;
    option.textContent = systemId;
    option.selected = systemId === state.building?.structural_system;
    structuralSystem.append(option);
  }
  structuralSystem.addEventListener("change", () => {
    if (!beginBuildingEditCopy(root, session, { confirmMutation: true })) {
      renderCurrentSchema(root);
      return;
    }
    const before = refinedBlastStore.getState().draft_revision;
    refinedBlastStore.setStructuralSystem(structuralSystem.value);
    renderCurrentSchema(root);
    if (refinedBlastStore.getState().draft_revision !== before) scheduleAutosave(root, session);
  });
  const provider = document.createElement("select");
  provider.id = "refinedBlastProvider";
  provider.setAttribute?.("aria-label", "载荷提供器");
  provider.dataset.refinedProvider = "true";
  for (const providerId of Object.keys(state.activeSchema.providers ?? {})) {
    const option = document.createElement("option");
    option.value = providerId;
    option.textContent = PROVIDER_LABELS[providerId] ?? providerId;
    option.selected = providerId === state.draft.load_provider?.provider_id;
    provider.append(option);
  }
  provider.addEventListener("change", () => {
    const before = refinedBlastStore.getState().draft_revision;
    refinedBlastStore.setProvider(provider.value);
    renderCurrentSchema(root);
    if (refinedBlastStore.getState().draft_revision !== before) scheduleAutosave(root, session);
  });
  const step = session?.currentStep ?? 1;
  const group = document.createElement("section");
  group.className = "refined-blast-control-group";
  const buildingNotice = renderBuildingDefinitionNotice(root, session, state);
  if (buildingNotice) group.append(buildingNotice);
  if (step === 1) {
    const assetLabel = document.createElement("label");
    assetLabel.htmlFor = asset.id;
    assetLabel.textContent = "建筑资产";
    const scenario = BUILDING_SCENARIOS[state.asset_id];
    const explanation = document.createElement("details");
    explanation.className = "refined-blast-scenario-explanation";
    explanation.dataset.refinedScenarioExplanation = "true";
    explanation.setAttribute?.("data-refined-scenario-explanation", "true");
    if (scenario) {
      const disclosure = document.createElement("summary");
      disclosure.textContent = "场景说明";
      explanation.append(disclosure);
      const title = document.createElement("strong");
      title.textContent = `${scenario.label} · ${scenario.propagation}`;
      const summary = document.createElement("p");
      summary.textContent = scenario.summary;
      const recommendation = document.createElement("small");
      recommendation.textContent = scenario.recommendation;
      explanation.append(title, summary, recommendation);
    }
    group.append(assetLabel, asset, explanation);
    group.append(renderWorkbenchStepFields(root, session, state, step, ["building.asset_id"]));
  } else if (step === 2) {
    const structuralSystemLabel = document.createElement("label");
    structuralSystemLabel.htmlFor = structuralSystem.id;
    structuralSystemLabel.textContent = "结构体系";
    group.append(structuralSystemLabel, structuralSystem);
    group.append(renderWorkbenchStepFields(root, session, state, step, ["building.structural_system"]));
  } else if (step === 7) {
    const providerLabel = document.createElement("label");
    providerLabel.htmlFor = provider.id;
    providerLabel.textContent = "载荷提供器";
    const providerExplanation = document.createElement("p");
    providerExplanation.className = "panel-note refined-blast-provider-explanation";
    providerExplanation.textContent = PROVIDER_DESCRIPTIONS[state.draft.load_provider?.provider_id] ?? "请选择载荷方式查看传播说明。";
    group.append(providerLabel, provider, providerExplanation);
    const fields = renderWorkbenchStepFields(
      root,
      session,
      state,
      step,
      ["draft.load_provider.provider_id"],
    );
    const split = splitSchemaFields(fields);
    group.append(split.primary);
    if (split.hasAdvanced) group.append(split.details);
    const migrationNote = renderProviderMigrationNote(state);
    if (migrationNote) group.append(migrationNote);
  } else {
    const fields = renderWorkbenchStepFields(root, session, state, step);
    if (fields.children?.length) group.append(fields);
    else {
      const message = document.createElement("p");
      message.className = "panel-note";
      message.textContent = "当前选项没有附加参数，已采用后端默认配置。";
      group.append(message);
    }
  }
  panel.replaceChildren(group);
}

function renderBuildingDefinitionNotice(root, session, state) {
  const policy = buildingDefinitionPolicy(state);
  if (!policy.requires_copy && !session?.copySource) return null;
  const notice = document.createElement("aside");
  notice.className = "refined-blast-building-edit-notice";
  notice.dataset.refinedBuildingEditNotice = "true";
  const message = document.createElement("span");
  if (session?.copySource && !state.project_id) {
    notice.dataset.state = "copy";
    message.textContent = `当前为 ${session.copySource.project_id} · r${session.copySource.revision} 的可编辑副本；保存草稿将创建新项目。`;
    notice.append(message);
    return notice;
  }
  if (!policy.locked) {
    notice.dataset.state = "pending";
    message.textContent = "该项目尚未生成 K 包；建筑参数可修改。首次修改会创建副本，原项目保留。";
    notice.append(message);
    return notice;
  }
  notice.dataset.state = "compiled";
  message.textContent = "该项目已生成 K 包，建筑定义已冻结。";
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "secondary-button";
  copy.dataset.refinedCopyBuilding = "true";
  copy.textContent = "复制后编辑";
  copy.addEventListener("click", () => {
    if (!beginBuildingEditCopy(root, session)) return;
    renderCurrentSchema(root);
  });
  notice.append(message, copy);
  return notice;
}

function renderProviderMigrationNote(state) {
  const rows = Array.isArray(state?.provider_input_migrations)
    ? state.provider_input_migrations
    : [];
  const current = rows.find((row) => (
    row?.scenario_id === state?.draft?.scenario_id
    && row?.provider_id === state?.draft?.load_provider?.provider_id
  ));
  if (!current) return null;
  const note = document.createElement("p");
  note.className = "panel-note refined-blast-provider-migration";
  note.dataset.refinedMigrationSource = "true";
  note.textContent = `兼容迁移：已从 ${current.source_schema_version} 自动规范化为 ${current.target_schema_version}；原始创建证据仍保留。`;
  return note;
}

function renderSaveState(root, busy = false, session = activeSession) {
  const button = root.querySelector("[data-refined-save]");
  if (!button) return;
  const state = session?.store?.getState?.() ?? refinedBlastStore?.getState?.();
  button.disabled = busy || !refinedBlastStore;
  button.textContent = state?.project_id ? "保存草稿" : "创建项目并保存草稿";
  button.dataset.busy = busy ? "true" : "false";
  const actionStatus = root.querySelector("[data-refined-action-status]");
  const saveSummary = root.querySelector("[data-refined-save-summary]");
  const label = busy ? "正在保存…"
    : session?.saveError?.code === "save_timeout" ? "保存超时，请重试"
      : session?.saveError ? "草稿保存失败"
      : session && hasUnpersistedDraft(session) ? "有未保存更改"
        : state?.project_id ? "已保存到独立项目" : "待创建 · 首次保存将自动建项";
  if (actionStatus) actionStatus.textContent = label;
  if (saveSummary) saveSummary.textContent = label;
  renderDamageAssessment(root, session);
  const summary = root.querySelector("[data-refined-validation-status]")
    ?? root.querySelector(".refined-blast-validation-panel .summary");
  const conflict = refinedBlastStore?.getState().conflict;
  if (summary && conflict?.blocking) summary.textContent = "草稿保存冲突：请先恢复或比较当前服务器版本，再决定如何继续。";
}

function visibleLayerIds(root) {
  return [...(root.querySelectorAll?.("[data-refined-layer]") ?? [])]
    .filter((input) => input.checked)
    .map((input) => input.dataset.refinedLayer);
}

function clearRenderedPreview(root, session, message) {
  session.viewer?.dispose();
  session.viewer = null;
  const container = root.querySelector("[data-refined-preview-canvas]");
  if (container?.replaceChildren) {
    const placeholder = document.createElement("span");
    placeholder.textContent = message;
    container.replaceChildren(placeholder);
  }
  const counts = root.querySelector("[data-refined-preview-counts]");
  if (counts) counts.textContent = "规模摘要：当前草稿没有可渲染预览。";
}

function renderPreviewPayload(root, session, payload) {
  if (!sessionIsActive(session)) return;
  const container = root.querySelector("[data-refined-preview-canvas]");
  if (!container) return;
  if (session.viewer) session.viewer.update(payload);
  else session.viewer = renderRefinedBlastPreview(container, payload, {
    visibleLayerIds: visibleLayerIds(root),
    blastSourceEditor: blastSourceEditorForDraft(root, session),
  });
  const counts = root.querySelector("[data-refined-preview-counts]");
  const metricSummary = root.querySelector("[data-refined-metric-summary]");
  if (counts) {
    const badges = session.viewer.getCountBadges();
    const isUncompiledEstimate = !payload.is_final
      && badges.length > 0
      && badges.every((row) => row.semantics === "upper_bound" && row.value === 100000000);
    if (metricSummary) metricSummary.textContent = isUncompiledEstimate ? "生成前未统计" : `${badges.length} 项规模指标`;
    if (isUncompiledEstimate) counts.textContent = "规模摘要：轻量预览不计算真实网格规模；生成 K 包时统计。";
    else counts.replaceChildren(...badges.map((row) => {
        const badge = document.createElement("span");
        badge.className = `refined-blast-count-badge ${row.semantics}`;
        badge.dataset.semantics = row.semantics;
        badge.textContent = `${row.metric}: ${row.value} (${row.semantics})`;
        return badge;
      }));
  }
  const status = root.querySelector("#refinedBlastPreviewStatus");
  if (status) status.textContent = `预览 revision ${payload.project_revision} · ${payload.is_final ? "final" : "draft"}`;
  renderValidationState(root, session);
}

function stepForFinding(finding) {
  const path = String(finding?.field_path ?? "");
  if (path.includes("load_provider")) return 7;
  if (path.includes("building") || path.includes("asset") || path.includes("structural")) return 1;
  return 8;
}

function configuredWorkbenchSteps(state) {
  const configured = new Set();
  const hasAsset = Boolean(state?.asset_id);
  const hasStructure = Boolean(state?.building?.structural_system);
  const hasProvider = Boolean(state?.draft?.load_provider?.provider_id);
  if (hasAsset) configured.add(1);
  if (hasAsset && hasStructure) {
    configured.add(2);
    configured.add(3);
    configured.add(4);
    configured.add(5);
    if (state?.building?.mesh_profile) configured.add(6);
  }
  if (hasProvider) configured.add(7);
  if (state?.validation) configured.add(8);
  return configured;
}

function renderStepStates(root, state) {
  const statuses = new Map();
  for (const step of configuredWorkbenchSteps(state)) statuses.set(step, "configured");
  for (const finding of state.validation?.findings ?? []) {
    const step = stepForFinding(finding);
    const current = statuses.get(step);
    if (finding.severity === "error" || (finding.severity === "warning" && current !== "error")) {
      statuses.set(step, finding.severity);
    }
  }
  root.querySelectorAll?.("[data-refined-section]").forEach((button) => {
    const step = Number(button.dataset.refinedSection);
    const status = statuses.get(step) ?? "pending";
    button.dataset.status = status;
    const statusLabel = STEP_STATUS_LABELS[status];
    const label = NAVIGATION_SECTIONS[step - 1] ?? "配置";
    const statusNode = button.querySelector?.("[data-refined-step-status]");
    if (statusNode) statusNode.textContent = statusLabel;
    button.setAttribute?.("aria-label", `转到配置步骤 ${step}: ${label}，${statusLabel}`);
  });
}

function renderWorkflowState(root, state, session) {
  const selected = Boolean(state.asset_id && state.building?.structural_system
    && state.draft?.load_provider?.provider_id);
  const saved = Boolean(state.project_id && !hasUnpersistedDraft(session));
  const previewed = Boolean(saved && state.preview?.project_id === state.project_id
    && state.preview?.project_revision === state.revision);
  const validated = Boolean(saved && state.validation?.project_id === state.project_id
    && state.validation?.project_revision === state.revision);
  const progress = { select: selected, save: saved, preview: previewed, validate: validated };
  const firstIncomplete = ["select", "save", "preview", "validate"].find((key) => !progress[key]) ?? "validate";
  root.querySelectorAll?.("[data-refined-workflow-step]").forEach((item) => {
    const key = item.dataset.refinedWorkflowStep;
    item.classList?.toggle("is-complete", Boolean(progress[key]));
    item.classList?.toggle("is-current", key === firstIncomplete);
  });
}

function renderValidationState(root, session = activeSession) {
  if (!sessionIsActive(session)) return;
  const state = session.store.getState();
  renderStepStates(root, state);
  renderWorkflowState(root, state, session);
  const status = root.querySelector("[data-refined-validation-status]");
  const conflict = root.querySelector("#refinedBlastConflict");
  const findings = root.querySelector("[data-refined-validation-findings]");
  const budgets = root.querySelector("[data-refined-budget-rows]");
  const generate = root.querySelector("[data-refined-generate]");
  const projectSummary = root.querySelector("[data-refined-project-summary]");
  const checkSummary = root.querySelector("[data-refined-check-summary]");
  if (projectSummary) projectSummary.textContent = state.project_id
    ? `${state.project_id} · r${state.revision}`
    : "待创建 · 首次保存将自动建项";
  if (generate) generate.disabled = Boolean(session.actionInFlight || session.damageAssessment?.busy)
    || typeof session.store.canGenerate !== "function" || !session.store.canGenerate();
  renderExternalActionState(root, session);
  renderDamageAssessment(root, session);
  if (budgets?.replaceChildren) {
    const rows = typeof session.store.validationBudgetRows === "function" ? session.store.validationBudgetRows() : [];
    budgets.replaceChildren(...rows.map((row) => {
      const item = document.createElement("div");
      item.className = `refined-blast-budget-row ${row.semantics}`;
      item.dataset.metric = row.metric;
      item.dataset.semantics = row.semantics;
      item.textContent = `${row.metric}: ${row.value} (${row.semantics})`;
      return item;
    }));
  }
  if (conflict) conflict.textContent = state.conflict?.blocking
    ? "草稿版本冲突：请恢复或比较当前服务器版本后重试。"
    : (session.saveError?.message ? `草稿保存失败：${session.saveError.message}` : "");
  if (state.conflict?.blocking) {
    if (status) status.textContent = "409 冲突：当前验证或确认已失效，请重新载入并保存。";
    findings?.replaceChildren?.();
    return;
  }
  if (!state.validation) {
    if (checkSummary) checkSummary.textContent = "尚未检查";
    if (status) status.textContent = state.project_id
      ? "当前持久化版本尚未验证。"
      : "请先创建并保存独立项目。";
    findings?.replaceChildren?.();
    return;
  }
  if (checkSummary) {
    const errorCount = state.validation.findings.filter((row) => row.severity === "error").length;
    const warningCount = state.validation.findings.filter((row) => row.severity === "warning").length;
    checkSummary.textContent = errorCount ? `${errorCount} 个错误` : warningCount ? `${warningCount} 个警告` : "检查通过";
  }
  if (status) status.textContent = `validation ${state.validation.fingerprint} · revision ${state.validation.project_revision}`;
  if (!findings?.replaceChildren) return;
  findings.replaceChildren(...state.validation.findings.map((row) => {
    const item = document.createElement("article");
    item.className = `refined-blast-finding severity-${row.severity}`;
    item.dataset.severity = row.severity;
    item.dataset.findingId = row.finding_id;
    item.dataset.contentHash = row.content_hash;
    item.textContent = [
      row.severity, row.module, row.field_path, row.message,
      row.correction, row.finding_id, row.content_hash,
    ].join(" | ");
    if (row.severity === "warning") {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary-button";
      button.dataset.refinedAcknowledge = row.finding_id;
      button.textContent = "确认当前警告";
      button.disabled = Boolean(state.acknowledgements?.[row.finding_id]);
      button.addEventListener("click", () => acknowledgeWarning(root, session, row.finding_id));
      item.append(button);
    }
    const locate = document.createElement("button");
    locate.type = "button";
    locate.className = "secondary-button refined-blast-locate-finding";
    locate.setAttribute?.("data-refined-locate", String(stepForFinding(row)));
    locate.textContent = "定位到相关步骤";
    locate.addEventListener("click", () => {
      root.querySelector(`[data-refined-section="${stepForFinding(row)}"]`)?.click?.();
      Promise.resolve().then(() => {
        const fieldPath = String(row.field_path ?? "");
        const field = Array.from(root.querySelectorAll?.("[data-refined-draft-path]") ?? []).find((input) => {
          const draftPath = String(input.dataset?.refinedDraftPath ?? "");
          return draftPath && (fieldPath.endsWith(draftPath) || draftPath.endsWith(fieldPath));
        });
        field?.focus?.();
      });
    });
    item.append(locate);
    return item;
  }));
}

// Presentation-only assessment client. Paths, rules and ratings remain server-owned.
const DAMAGE_IDENTITY_SCHEMA = "refined-blast.assessment-identity@1";
const DAMAGE_ERRORS = {
  assessment_unavailable: "评估模块不可用，请安装可选依赖并重启主项目服务。",
  assessment_source_unavailable: "没有可核验的终态求解结果。请先完成对应求解；历史结果需由服务端登记。",
  assessment_source_stale: "已有求解结果与当前生成包不一致，请核对项目版本和对应求解记录。",
  artifact_stale: "生成包身份已过期，请使用当前版本对应的求解结果。",
  assessment_integrity_error: "求解结果或报告完整性校验失败，已停止显示本次结果。",
  assessment_artifact_integrity_error: "报告文件完整性校验失败，已停止显示损伤等级。请核对服务端保留产物。",
  assessment_registry_integrity_error: "评估登记记录校验失败，暂时不能读取报告。",
  assessment_conflict: "评估身份与已有登记冲突，请检查已有报告和求解来源。",
  assessment_failed: "评估执行失败。请检查服务端日志；本页面不会自动重试。",
  invalid_result: "返回结果校验失败，不能据此显示损伤等级。",
  not_found: "当前服务未提供该评估接口或产物，请确认已更新并重启服务。",
  network: "请求未完成，后台可能仍在运行。请先刷新最新报告，确认后再手动重试。",
};

function damageContextKey(session) {
  const state = session.store.getState();
  return JSON.stringify([state.project_id, state.revision, state.draft_revision]);
}

function validDamageIdentity(candidate, state) {
  return candidate && candidate.project_id === state.project_id
    && candidate.scenario_id === state.draft?.scenario_id
    && Number.isSafeInteger(candidate.generated_revision) && candidate.generated_revision > 0
    && candidate.generated_revision === state.revision
    && [candidate.artifact_fingerprint, candidate.package_fingerprint].every(value => typeof value === "string" && /^[0-9a-f]{64}$/.test(value));
}

function rememberDamageAssessmentIdentity(session) {
  const state = session.store.getState();
  if (!validDamageIdentity(session.generated, state)) return;
  // A browser hint only: the existing POST revalidates every field against server records.
  safeStorageWrite(session.localStorage, "refined-blast.assessment-identity." + state.project_id,
    JSON.stringify({ schema_version: DAMAGE_IDENTITY_SCHEMA, ...session.generated }));
}

function currentDamageIdentity(session) {
  const state = session.store.getState();
  if (!state.project_id || state.conflict?.blocking || hasUnpersistedDraft(session)) return null;
  let candidate = session.generated;
  if (!candidate) {
    try {
      candidate = JSON.parse(session.localStorage?.getItem?.("refined-blast.assessment-identity." + state.project_id) ?? "null");
      if (candidate?.schema_version !== DAMAGE_IDENTITY_SCHEMA || Object.keys(candidate).length !== 6) return null;
    } catch (_) { return null; }
  }
  if (!validDamageIdentity(candidate, state)) return null;
  return { scenario_id: candidate.scenario_id, generated_revision: candidate.generated_revision,
    artifact_fingerprint: candidate.artifact_fingerprint, package_fingerprint: candidate.package_fingerprint };
}

function validDamageRating(value) {
  return value && ["blocked", "provisional", "formal"].includes(value.gate)
    && (value.gate === "blocked" ? value.severity === null
      : Number.isInteger(value.severity) && value.severity >= 0 && value.severity <= 4);
}

function validatedDamageRecord(value) {
  if (value?.schema_version !== "lsprepost_mcp.damage_assessment_response@1"
      || !["registered", "registered_existing", "completed_unregistered"].includes(value.registration_state)
      || typeof value.assessment_id !== "string" || !/^[0-9a-f]{24}$/.test(value.assessment_id)
      || typeof value.assessment_fingerprint !== "string" || !/^[0-9a-f]{64}$/.test(value.assessment_fingerprint)
      || !validDamageRating(value)) throw new Error("invalid_result");
  return value;
}

function damageArtifactUrl(projectId, assessmentId, name) {
  if (!/^[0-9a-f]{24}$/.test(assessmentId)
      || !["assessment_snapshot.json", "damage_report.html", "building_components.csv", "ground_regions.csv"].includes(name)) throw new Error("invalid_result");
  return REFINED_BLAST_API_PREFIX + "projects/" + encodeURIComponent(projectId)
    + "/assessments/" + assessmentId + "/artifacts/" + name;
}

async function readDamageJson(session, url, options = {}, raw = false) {
  const { response, body } = await fetchJson(session.fetch, url, { ...options, headers: { Accept: "application/json", ...options.headers } });
  if (!response.ok) throw new Error(typeof body?.error?.code === "string" ? body.error.code : "network");
  if (raw) return body;
  if (body?.ok !== true || !body.result || typeof body.result !== "object") throw new Error("invalid_result");
  return body.result;
}

function damageRequestIsCurrent(session, key, serial) {
  return sessionIsActive(session) && session.damageAssessment?.serial === serial && damageContextKey(session) === key;
}

async function loadDamageSnapshot(session, result, key, serial, controller) {
  if (result.registration_state === "completed_unregistered") return;
  const projectId = session.store.getState().project_id;
  const snapshot = await readDamageJson(session, damageArtifactUrl(projectId, result.assessment_id, "assessment_snapshot.json"),
    controller ? { signal: controller.signal } : {}, true);
  if (!damageRequestIsCurrent(session, key, serial)) return;
  if (snapshot?.schema_version !== "blast_damage.assessment_snapshot@1"
      || snapshot.assessment_id !== result.assessment_id || snapshot.assessment_fingerprint !== result.assessment_fingerprint
      || snapshot.identity?.project_id !== projectId || !validDamageRating(snapshot.overall)
      || snapshot.overall.gate !== result.gate || snapshot.overall.severity !== result.severity
      || !validDamageRating(snapshot.building) || !validDamageRating(snapshot.ground)) throw new Error("invalid_result");
  session.damageAssessment.snapshot = snapshot;
}

function damageRatingText(value) {
  if (!value) return "待评估";
  if (value.gate === "blocked") return "证据不足，未给出等级";
  return "等级 " + value.severity + " · " + (value.gate === "provisional" ? "研究参考" : "需专业复核");
}

function renderDamageAssessment(root, session = activeSession) {
  const assessment = session?.damageAssessment;
  if (!assessment || !sessionIsActive(session)) return;
  const state = session.store.getState();
  const key = damageContextKey(session);
  if (assessment.key !== key) {
    if (!assessment.busy) { assessment.controller?.abort(); assessment.serial += 1; assessment.loading = false; }
    assessment.key = key; assessment.result = null; assessment.snapshot = null;
    assessment.status = assessment.busy ? "项目版本已变化，本次响应不会用于新版本；后台请求可能仍在运行。" : "项目版本已变化，请重新核对结果；可刷新已登记报告。";
  }
  const setText = (name, text) => { const element = root.querySelector("[data-damage-" + name + "]"); if (element) element.textContent = text; };
  const identity = currentDamageIdentity(session);
  setText("project", state.project_id ? "当前项目：" + state.project_id + " · r" + state.revision : "当前项目：请先创建或打开项目");
  setText("capability", assessment.capabilities === null ? "评估模块：尚未确认"
    : assessment.capabilities.available ? "评估模块：可用"
      : "评估模块：不可用。请运行 scripts/setup_damage_assessment.ps1 安装可选依赖，并重启服务。");
  setText("source", !state.project_id ? "求解结果：尚未选择项目"
    : state.conflict?.blocking || hasUnpersistedDraft(session) ? "当前草稿有未保存更改或版本冲突，请先处理；旧报告仍可查看。"
      : identity ? "生成包已识别；是否有对应的终态求解结果，将在开始评估时由服务端核验。"
        : "当前浏览器未取得此版本的生成包身份。请在本页面生成 K 包并完成求解后评估；已有报告仍可查看。");
  setText("status", assessment.status || "只读检查完成。打开面板不会自动执行评估。");
  const start = root.querySelector("[data-damage-start]");
  if (start) {
    start.disabled = assessment.busy || assessment.loading || session.actionInFlight
      || assessment.capabilities?.available !== true || !identity;
    start.textContent = assessment.busy ? "正在评估…" : "开始评估";
  }
  const refresh = root.querySelector("[data-damage-refresh]");
  if (refresh) refresh.disabled = assessment.busy || assessment.loading;
  const result = assessment.result;
  setText("result", result ? (assessment.origin === "latest" ? "最新已登记报告（请核对版本）" : "本次评估")
    + " · " + damageRatingText(result) + " · " + result.assessment_id
    + (result.source?.run_id ? " · 求解 " + result.source.run_id : "") : "尚无可显示的评估结果");
  setText("building", damageRatingText(assessment.snapshot?.building));
  setText("ground", damageRatingText(assessment.snapshot?.ground));
  const issues = root.querySelector("[data-damage-issues]");
  if (issues?.replaceChildren) {
    const messages = [
      ...(result?.blockers ?? []), ...(result?.warnings ?? []), ...(result?.review_items ?? []),
      ...(assessment.snapshot?.limitations ?? []),
    ].filter(value => typeof value === "string" || typeof value?.message === "string").slice(0, 32);
    issues.replaceChildren(...messages.map(value => {
      const node = document.createElement("p");
      node.textContent = String(typeof value === "string" ? value : value.message).slice(0, 1200);
      return node;
    }));
  }
  const registered = result && result.registration_state !== "completed_unregistered" && assessment.snapshot;
  for (const [control, filename] of [["view", "damage_report.html"], ["download", "damage_report.html"], ["building-csv", "building_components.csv"], ["ground-csv", "ground_regions.csv"]]) {
    const link = root.querySelector("[data-damage-" + control + "]");
    if (!link) continue;
    link.setAttribute("aria-disabled", registered ? "false" : "true");
    link.setAttribute("tabindex", registered ? "0" : "-1");
    link.removeAttribute("href"); link.removeAttribute("download"); link.removeAttribute("target");
    if (registered) {
      link.setAttribute("href", damageArtifactUrl(state.project_id, result.assessment_id, filename));
      link.setAttribute("rel", "noopener noreferrer");
      if (control === "view") link.setAttribute("target", "_blank");
      else link.setAttribute("download", filename);
    }
  }
}

function openDamageDemo(root, session = activeSession) {
  if (!sessionIsActive(session)) return;
  const panel = root.querySelector("[data-damage-demo-panel]");
  if (!panel || panel.open) return;
  const frame = document.createElement("iframe");
  frame.setAttribute("data-damage-demo-frame", "");
  frame.setAttribute("title", "住宅建筑与地面模型及对应评估结果（只读演示）");
  frame.setAttribute("src", "/damage_assessment_demo.html");
  root.querySelector("[data-damage-demo-host]").replaceChildren(frame);
  panel.showModal();
  root.querySelector("[data-damage-demo-exit]")?.focus();
}

function closeDamageDemo(root) {
  try{root.querySelector('[data-damage-demo-frame]')?.contentWindow?.WorkbenchNavigation?.checkpoint();}
  catch(error){const note=root.querySelector('.refined-damage-demo-heading span');if(note)note.textContent=error.message;return;}
  root.querySelector("[data-damage-demo-host]")?.replaceChildren();
  root.querySelector("[data-damage-demo-panel]")?.close();
  root.querySelector("[data-damage-demo]")?.focus();
}

async function openDamageAssessment(root, session = activeSession) {
  if (!sessionIsActive(session)) return;
  if (!session.damageAssessment) session.damageAssessment = {
    key: damageContextKey(session), serial: 0, controller: null, capabilities: null,
    busy: false, loading: false, result: null, snapshot: null, status: "", origin: "latest",
  };
  const panel = root.querySelector("[data-damage-panel]");
  if (panel && !panel.open) panel.showModal();
  root.querySelector("[data-damage-close]")?.focus();
  renderDamageAssessment(root, session);
  if (!session.damageAssessment.busy) await refreshDamageAssessment(root, session);
}

function closeDamageAssessment(root, session = activeSession) {
  if (!sessionIsActive(session)) return;
  root.querySelector("[data-damage-panel]")?.close();
  root.querySelector("[data-refined-assessment]")?.focus();
}

async function refreshDamageAssessment(root, session = activeSession) {
  const assessment = session?.damageAssessment;
  if (!sessionIsActive(session) || !assessment || assessment.busy || assessment.loading) return;
  renderDamageAssessment(root, session);
  const key = damageContextKey(session), serial = ++assessment.serial;
  assessment.controller?.abort();
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  assessment.controller = controller; assessment.loading = true; assessment.status = "正在检查模块并读取最新报告…";
  assessment.result = null; assessment.snapshot = null; assessment.origin = "latest";
  renderDamageAssessment(root, session);
  const projectId = session.store.getState().project_id;
  const options = controller ? { signal: controller.signal } : {};
  try {
    const [capabilities, latest] = await Promise.all([
      readDamageJson(session, "/api/damage-assessment/capabilities", options).catch(error => ({ error })),
      projectId ? readDamageJson(session, REFINED_BLAST_API_PREFIX + "projects/" + encodeURIComponent(projectId) + "/assessments/latest", options).catch(error => ({ error })) : null,
    ]);
    if (!damageRequestIsCurrent(session, key, serial)) return;
    assessment.status = "";
    assessment.capabilities = null;
    if (!capabilities.error && capabilities.schema_version === "lsprepost_mcp.damage_assessment_capabilities@1"
        && typeof capabilities.available === "boolean") assessment.capabilities = capabilities;
    else assessment.status = "无法确认评估模块状态，请刷新重试。";
    if (latest?.error && latest.error.message !== "assessment_not_found") throw latest.error;
    if (latest && !latest.error) {
      const verifiedRecord = validatedDamageRecord(latest);
      if (latest.registration_state === "completed_unregistered") throw new Error("invalid_result");
      await loadDamageSnapshot(session, latest, key, serial, controller);
      if (!damageRequestIsCurrent(session, key, serial)) return;
      assessment.result = verifiedRecord;
    } else if (!assessment.status) assessment.status = projectId ? "暂无已登记报告。满足条件后可开始评估。" : "请先创建或打开项目。";
  } catch (error) {
    if (damageRequestIsCurrent(session, key, serial)) assessment.status = DAMAGE_ERRORS[error.message] ?? DAMAGE_ERRORS.network;
  } finally {
    if (sessionIsActive(session) && assessment.serial === serial) {
      assessment.loading = false; assessment.controller = null; renderDamageAssessment(root, session);
    }
  }
}

async function requestDamageAssessment(root, session = activeSession) {
  const assessment = session?.damageAssessment;
  if (!sessionIsActive(session) || !assessment || assessment.busy || assessment.loading || session.actionInFlight
      || assessment.capabilities?.available !== true) return false;
  const identity = currentDamageIdentity(session);
  if (!identity) return false;
  const key = damageContextKey(session), serial = ++assessment.serial;
  const projectId = session.store.getState().project_id;
  assessment.controller?.abort();
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  assessment.controller = controller; assessment.busy = true;
  assessment.result = null; assessment.snapshot = null; assessment.origin = "current";
  assessment.status = "正在核验求解结果并执行评估…关闭面板不会取消后台评估。";
  renderDamageAssessment(root, session); renderExternalActionState(root, session);
  try {
    const result = await readDamageJson(session, REFINED_BLAST_API_PREFIX + "projects/" + encodeURIComponent(projectId) + "/assess-latest-run", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ schema_version: "lsprepost_mcp.damage_assessment_request@1", ...identity }),
      ...(controller ? { signal: controller.signal } : {}),
    });
    if (!damageRequestIsCurrent(session, key, serial)) return false;
    const verifiedRecord = validatedDamageRecord(result);
    if (result.registration_state === "completed_unregistered") {
      assessment.result = verifiedRecord;
      assessment.status = "评估已生成产物，但登记失败。文件已保留；不能从页面下载未登记报告。确认原因后可手动重试。";
    } else {
      await loadDamageSnapshot(session, result, key, serial, controller);
      if (!damageRequestIsCurrent(session, key, serial)) return false;
      assessment.result = verifiedRecord;
      assessment.status = result.gate === "blocked" ? "证据不足，未给出总体损伤等级。可查看报告中的阻断原因。" : "评估完成，报告已登记。请结合证据和研究限制阅读结果。";
    }
    return true;
  } catch (error) {
    if (damageRequestIsCurrent(session, key, serial)) assessment.status = DAMAGE_ERRORS[error.message] ?? DAMAGE_ERRORS.network;
    return false;
  } finally {
    if (sessionIsActive(session) && assessment.serial === serial) {
      assessment.busy = false; assessment.controller = null;
      renderDamageAssessment(root, session); renderExternalActionState(root, session);
    }
  }
}

function currentGeneratedIdentity(session) {
  const state = session?.store?.getState?.();
  const generated = session?.generated;
  if (!state || !generated || state.conflict?.blocking || hasUnpersistedDraft(session)) return null;
  if (generated.project_id !== state.project_id || generated.scenario_id !== state.draft?.scenario_id
      || generated.generated_revision !== state.revision) return null;
  if (![generated.artifact_fingerprint, generated.package_fingerprint].every((value) => typeof value === "string" && value)) return null;
  return {
    scenario_id: generated.scenario_id, generated_revision: generated.generated_revision,
    artifact_fingerprint: generated.artifact_fingerprint, package_fingerprint: generated.package_fingerprint,
  };
}

function renderExternalActionState(root, session = activeSession) {
  const enabled = Boolean(currentGeneratedIdentity(session)) && !session?.actionInFlight && !session?.damageAssessment?.busy;
  const open = root.querySelector("[data-refined-open-lsprepost]");
  const solve = root.querySelector("[data-refined-launch-lsdyna]");
  if (open) open.disabled = !enabled;
  if (solve) solve.disabled = !enabled;
}

async function generatePackage(root, session = activeSession) {
  if (!sessionIsActive(session) || session.actionInFlight || session.damageAssessment?.busy) return false;
  if (hasUnpersistedDraft(session)) {
    try { await flushSave(root, session); } catch (_) { return false; }
  }
  const state = session.store.getState();
  if (!sessionIsActive(session) || !session.store.canGenerate?.() || state.conflict?.blocking) return false;
  session.actionInFlight = true;
  session.generated = null;
  renderValidationState(root, session);
  try {
    const { response, body: envelope } = await fetchJson(session.fetch, `${REFINED_BLAST_API_PREFIX}projects/${encodeURIComponent(state.project_id)}/generate`, {
      method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: state.revision }),
    });
    const result = envelope?.result ?? envelope;
    const artifact = result?.artifact;
    if (!response.ok || !sessionIsActive(session) || artifact?.project_id !== state.project_id
        || artifact?.scenario_id !== state.draft?.scenario_id || artifact?.revision !== state.revision + 1
        || typeof artifact?.fingerprint !== "string" || !artifact.fingerprint
        || typeof result?.package_fingerprint !== "string" || !result.package_fingerprint
        || result?.solver_ready !== false || result?.requires_project_review !== true
        || result?.external_program_started !== false
        || session.store.applyGeneratedRevision?.(artifact, state.revision) !== true) return false;
    session.generated = { project_id: artifact.project_id, scenario_id: artifact.scenario_id,
      generated_revision: artifact.revision, artifact_fingerprint: artifact.fingerprint,
      package_fingerprint: result.package_fingerprint };
    rememberDamageAssessmentIdentity(session);
    return true;
  } catch (_) { return false; }
  finally {
    session.actionInFlight = false;
    if (sessionIsActive(session)) {
      renderCurrentSchema(root);
      renderValidationState(root, session);
    }
  }
}

async function requestExternalAction(root, session = activeSession, action) {
  const identity = currentGeneratedIdentity(session);
  if (!sessionIsActive(session) || session.actionInFlight || session.damageAssessment?.busy || !identity) return false;
  const label = action === "open_lsprepost" ? "打开 LS-PrePost" : action === "launch_lsdyna" ? "启动 LS-DYNA" : null;
  if (!label || window.confirm(`确认${label}并交接当前不可变研究快照？`) !== true) return false;
  session.actionInFlight = true; renderExternalActionState(root, session);
  const status = root.querySelector("[data-refined-external-status]");
  try {
    const { response: descriptorResponse, body: descriptorEnvelope } = await fetchJson(session.fetch, `${REFINED_BLAST_API_PREFIX}projects/${encodeURIComponent(session.projectId)}/action-confirmations`, {
      method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ action, ...identity }),
    });
    const confirmation = (descriptorEnvelope?.result ?? descriptorEnvelope)?.confirmation;
    if (!descriptorResponse.ok || !currentGeneratedIdentity(session)
        || confirmation?.action !== action || confirmation?.project_id !== session.projectId || typeof confirmation?.nonce !== "string"
        || Object.keys(identity).some((key) => confirmation?.[key] !== identity[key])) return false;
    const route = action === "open_lsprepost" ? "open-lsprepost" : "launch-lsdyna";
    const { response, body: envelope } = await fetchJson(session.fetch, `${REFINED_BLAST_API_PREFIX}projects/${encodeURIComponent(session.projectId)}/${route}`, {
      method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ confirmation_nonce: confirmation.nonce, ...identity }),
    }); const result = envelope?.result ?? envelope;
    if (!response.ok || !currentGeneratedIdentity(session) || result?.action !== action
        || Object.keys(identity).some((key) => result?.[key] !== identity[key]) || result?.solver_ready !== false
        || result?.requires_project_review !== true || typeof result?.external_program_started !== "boolean") return false;
    if (status) status.textContent = result.external_program_started ? `${label}已启动。` : `${label}未启动。`;
    return result.external_program_started;
  } catch (_) { return false; }
  finally { session.actionInFlight = false; renderExternalActionState(root, session); }
}

async function requestValidation(root, session = activeSession) {
  if (!sessionIsActive(session)) return false;
  if (!session.projectId || session.timer !== null || session.inFlight || session.queued || hasUnpersistedDraft(session)) {
    try { await flushSave(root, session); }
    catch (_) { renderValidationState(root, session); return false; }
  }
  if (!sessionIsActive(session)) return false;
  const state = session.store.getState();
  session.projectId = state.project_id ?? session.projectId;
  if (!session.projectId || state.conflict?.blocking || hasUnpersistedDraft(session)) {
    renderValidationState(root, session);
    return false;
  }
  session.validationAbortController?.abort();
  const issue = session.store.beginValidationRequest({ mount_token: session.token, project_id: session.projectId });
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  session.validationAbortController = controller;
  renderValidationState(root, session);
  try {
    const { response, body: envelope } = await fetchJson(session.fetch, `${REFINED_BLAST_API_PREFIX}projects/${encodeURIComponent(session.projectId)}/validate`, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: issue.persisted_revision }),
      ...(controller ? { signal: controller.signal } : {}),
    });
    if (!response.ok) {
      session.store.rejectValidationRequest(issue, response.status, envelope);
      if (sessionIsActive(session)) renderValidationState(root, session);
      return false;
    }
    const payload = envelope?.result?.validation ?? envelope?.validation;
    const applied = session.store.applyValidation(payload, issue);
    if (sessionIsActive(session)) renderValidationState(root, session);
    return applied && sessionIsActive(session);
  } catch (error) {
    if (error?.name !== "AbortError") session.store.rejectValidationRequest(issue, 0, { message: error?.message ?? "validation failed" });
    if (sessionIsActive(session)) renderValidationState(root, session);
    return false;
  } finally {
    if (session.validationAbortController === controller) session.validationAbortController = null;
  }
}

async function acknowledgeWarning(root, session, findingId) {
  if (!sessionIsActive(session)) return false;
  let issue;
  try { issue = session.store.beginAcknowledgementRequest(findingId, { mount_token: session.token }); }
  catch (_) { renderValidationState(root, session); return false; }
  const prior = session.acknowledgementAbortControllers.get(findingId);
  prior?.abort();
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  if (controller) session.acknowledgementAbortControllers.set(findingId, controller);
  try {
    const { response, body: envelope } = await fetchJson(session.fetch, `${REFINED_BLAST_API_PREFIX}projects/${encodeURIComponent(issue.project_id)}/acknowledgements`, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_revision: issue.persisted_revision,
        validation_fingerprint: issue.validation_fingerprint,
        finding_id: issue.finding_id,
      }),
      ...(controller ? { signal: controller.signal } : {}),
    });
    if (!response.ok) {
      session.store.rejectAcknowledgementRequest(issue, response.status, envelope);
      if (sessionIsActive(session)) renderValidationState(root, session);
      return false;
    }
    const payload = envelope?.result ?? envelope;
    const applied = session.store.applyAcknowledgement(payload, issue);
    if (sessionIsActive(session)) renderValidationState(root, session);
    return applied && sessionIsActive(session);
  } catch (error) {
    if (error?.name !== "AbortError") session.store.rejectAcknowledgementRequest(issue, 0, { message: error?.message ?? "acknowledgement failed" });
    if (sessionIsActive(session)) renderValidationState(root, session);
    return false;
  } finally {
    if (session.acknowledgementAbortControllers.get(findingId) === controller) {
      session.acknowledgementAbortControllers.delete(findingId);
    }
  }
}

async function refreshPreview(root, session = activeSession) {
  if (!sessionIsActive(session)) return false;
  if (!session.projectId || session.timer !== null || session.inFlight || session.queued || hasUnpersistedDraft(session)) {
    try { await flushSave(root, session); }
    catch (_) {
      if (sessionIsActive(session)) clearRenderedPreview(root, session, "草稿保存失败，未请求旧版本预览。");
      return false;
    }
  }
  if (!sessionIsActive(session)) return false;
  const state = session.store.getState();
  session.projectId = state.project_id ?? session.projectId;
  if (!session.projectId || state.conflict?.blocking || hasUnpersistedDraft(session)) {
    clearRenderedPreview(root, session, "请先保存有效草稿，再刷新预览。");
    return false;
  }

  session.previewAbortController?.abort();
  const issue = session.store.beginPreviewRequest({ mount_token: session.token, project_id: session.projectId });
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  session.previewAbortController = controller;
  session.previewRequest = issue;
  const status = root.querySelector("#refinedBlastPreviewStatus");
  if (status) status.textContent = "正在生成当前持久版本的预览…";
  try {
    const { response, body: envelope } = await fetchJson(session.fetch, `${REFINED_BLAST_API_PREFIX}projects/${encodeURIComponent(session.projectId)}/preview`, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: issue.persisted_revision }),
      ...(controller ? { signal: controller.signal } : {}),
    });
    if (!response.ok) {
      if (session.store.rejectPreviewRequest(issue, response.status, envelope) && sessionIsActive(session)) {
        clearRenderedPreview(root, session, "当前草稿被验证阻断，没有可渲染预览。");
      }
      return false;
    }
    const payload = envelope?.result?.preview ?? envelope?.preview;
    if (!session.store.applyPreview(payload, issue) || !sessionIsActive(session)) return false;
    renderPreviewPayload(root, session, payload);
    return true;
  } catch (error) {
    if (error?.name === "AbortError") return false;
    if (session.store.rejectPreviewRequest(issue) && sessionIsActive(session)) {
      clearRenderedPreview(root, session, "预览请求失败；请检查当前草稿后重试。");
    }
    return false;
  } finally {
    if (session.previewAbortController === controller) session.previewAbortController = null;
  }
}

async function loadCapabilities(root, instanceToken) {
  const status = root.querySelector("#refinedBlastPreviewStatus");
  const session = activeSession;
  const loadIsCurrent = () => sessionIsActive(session)
    && session.token === instanceToken && session.store === refinedBlastStore;
  if (!loadIsCurrent()) return;
  try {
    const { response, body: capabilitiesEnvelope } = await fetchJson(session.fetch, `${REFINED_BLAST_API_PREFIX}capabilities`, {
      headers: { Accept: "application/json" }
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    if (!loadIsCurrent()) return;
    const { response: assetsResponse, body: assetsEnvelope } = await fetchJson(session.fetch, `${REFINED_BLAST_API_PREFIX}assets`, {
      headers: { Accept: "application/json" }
    });
    if (!assetsResponse.ok) throw new Error(`HTTP ${assetsResponse.status}`);
    const capabilities = capabilitiesEnvelope.result ?? capabilitiesEnvelope;
    const assets = assetsEnvelope.result?.assets ?? assetsEnvelope.assets ?? [];
    if (!loadIsCurrent()) return;
    const selectedAssetId = refinedBlastStore.getState().asset_id ?? assets[0]?.asset_id;
    refinedBlastStore.setSchema(schemaForWorkbench(capabilities, assets, selectedAssetId));
    if (session.pendingSessionDraft) {
      refinedBlastStore.replaceDraft(session.pendingSessionDraft);
      session.pendingSessionDraft = null;
    }
    if (session.restoreProject && session.projectId) {
      const requestedProjectId = session.projectId;
      const controller = typeof AbortController === "function" ? new AbortController() : null;
      session.restoreAbortController?.abort();
      session.restoreAbortController = controller;
      const { response: projectResponse, body: projectEnvelope } = await fetchJson(session.fetch, `${REFINED_BLAST_API_PREFIX}projects/${encodeURIComponent(requestedProjectId)}`, {
        headers: { Accept: "application/json" },
        ...(controller ? { signal: controller.signal } : {})
      });
      if (!projectResponse.ok) throw new Error(`HTTP ${projectResponse.status}`);
      if (!loadIsCurrent() || session.projectId !== requestedProjectId) return;
      const stored = projectEnvelope?.result?.project ?? projectEnvelope?.project;
      if (stored?.project_id !== requestedProjectId) throw new Error("persisted project identity does not match the requested URL");
      session.store.restorePersistedProject(stored, requestedProjectId);
      session.persistedDraftRevision = 0;
      writeLatestProjectId(session.localStorage, requestedProjectId);
      writeSessionDraft(session.sessionStorage, null);
      if (session.restoreAbortController === controller) session.restoreAbortController = null;
    }
    if (!refinedBlastStore.getState().draft?.scenario_id && capabilities.default_scenario_draft) {
      refinedBlastStore.replaceDraft(capabilities.default_scenario_draft);
    }
    if (selectedAssetId) refinedBlastStore.setAsset(selectedAssetId);
    const selectedAsset = refinedBlastStore.getState().activeSchema.assets
      ?.find((row) => row.asset_id === refinedBlastStore.getState().asset_id);
    const structuralSystems = selectedAsset?.allowed_structural_systems ?? [];
    if (structuralSystems.length && !refinedBlastStore.getState().building?.structural_system) {
      refinedBlastStore.setStructuralSystem(selectedAsset.default_structural_system ?? structuralSystems[0]);
    }
    const providerIds = Object.keys(refinedBlastStore.getState().activeSchema.providers);
    if (providerIds.length && !refinedBlastStore.getState().draft.load_provider?.provider_id) {
      refinedBlastStore.setProvider(providerIds[0]);
    }
    renderCurrentSchema(root);
    renderSaveState(root);
    renderValidationState(root, activeSession);
    status.textContent = "配置完成后，保存草稿并刷新预览。";
    await registerRefinedNavigation(root, session);
  } catch (error) {
    if (!loadIsCurrent()) return;
    status.textContent = "能力描述暂不可用；可在服务恢复后重新进入工作台。";
  }
}

async function registerRefinedNavigation(root,session) {
  const n=window.WorkbenchNavigation;if(!n||!sessionIsActive(session))return;
  await n.register('refined',{
    restoreIdentity:()=>session.projectId||'new',
    context:()=>({identity:session.projectId||'new',revision:session.projectId?session.store.getState().revision:'',label:session.projectId?'项目 '+session.projectId:'未创建项目 · 精细化草稿',url:'/refined-building-blast'+(session.projectId?'?project_id='+encodeURIComponent(session.projectId):'')}),
    beforeLeave:async()=>{
      if(session.actionInFlight)throw Error('当前项目操作尚未结束，请稍后切换。');
      let fields=n.captureFields(root);
      const keepFields=()=>{fields=n.captureFields(root);};
      root.addEventListener('input',keepFields,true);root.addEventListener('change',keepFields,true);
      if(session.timer!==null)clearTimeout(session.timer);session.timer=null;session.queued=false;
      try{if(session.inFlight)await session.inFlight.catch(()=>{});}
      finally{root.removeEventListener('input',keepFields,true);root.removeEventListener('change',keepFields,true);}
      if(session.timer!==null)clearTimeout(session.timer);session.timer=null;session.queued=false;
      n.restoreFields(root,fields);
    },
    capture:()=>{const s=session.store.getState();return {asset:s.asset_id,building:s.building,draft:s.draft,step:session.currentStep,fields:n.captureFields(root)};},
    restore:s=>{
      const current=session.store.getState();
      if(s.asset!==current.asset_id)throw Error('建筑资产不一致，原草稿另行保留。');
      if(!session.projectId)session.store.updateBuilding(b=>{Object.assign(b,structuredClone(s.building));});
      session.store.replaceDraft(s.draft);
      const step=Number.isInteger(s.step)&&s.step>=1&&s.step<=8?s.step:1;
      root.querySelector(`[data-refined-section="${step}"]`)?.click();
      n.restoreFields(root,s.fields);
      for(const input of root.querySelectorAll('[data-refined-draft-path]')){
        const path=input.dataset.refinedDraftPath;if(input.disabled)continue;
        try{
          if(path.startsWith('draft.'))session.store.updateDraft(d=>setSchemaInputValueAtPath(d,path.slice(6),input));
          else if(path.startsWith('building.')&&!session.projectId)session.store.updateBuilding(b=>setSchemaInputValueAtPath(b,path.slice(9),input));
        }catch{input.setAttribute('aria-invalid','true');}
      }
      renderSaveState(root);renderValidationState(root,session);
      statusText(root,'已恢复本标签页草稿；未自动保存、预览或生成。');
    },
  });
}

function statusText(root,text){const e=root.querySelector('#refinedBlastPreviewStatus');if(e)e.textContent=text;}

function installShellHandlers(root) {
  root.querySelector("[data-refined-assessment]")?.addEventListener("click", () => openDamageAssessment(root, activeSession));
  root.querySelector("[data-damage-close]")?.addEventListener("click", () => closeDamageAssessment(root, activeSession));
  root.querySelector("[data-damage-panel]")?.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeDamageAssessment(root, activeSession);
  });
  root.querySelector("[data-damage-start]")?.addEventListener("click", () => requestDamageAssessment(root, activeSession));
  root.querySelector("[data-damage-refresh]")?.addEventListener("click", () => refreshDamageAssessment(root, activeSession));
  root.querySelector("[data-damage-demo]")?.addEventListener("click", () => openDamageDemo(root, activeSession));
  root.querySelector("[data-damage-demo-exit]")?.addEventListener("click", () => closeDamageDemo(root));
  root.querySelector("[data-damage-demo-panel]")?.addEventListener("cancel", (event) => {
    event.preventDefault(); closeDamageDemo(root);
  });
  root.querySelector("[data-refined-back]").addEventListener("click", () => {
    if (window.location.pathname === "/refined-building-blast" || window.location.pathname === "/refined-building-blast/") {
      window.history.replaceState({ workspace: "legacy" }, "", "/");
      window.dispatchEvent(new PopStateEvent("popstate"));
    }
  });
  root.querySelector("[data-refined-save]").addEventListener("click", async () => {
    if (!refinedBlastStore) return;
    await flushSave(root, activeSession);
  });
  root.querySelector("[data-refined-new-scenario]")?.addEventListener("click", () => {
    const session = activeSession;
    if (!sessionIsActive(session)) return;
    if (session.projectId && window.confirm?.("新建工况会离开当前项目；已保存项目不会删除。是否继续？") !== true) return;
    const localStorage = session.localStorage;
    const sessionStorage = session.sessionStorage;
    const fetch = session.fetch;
    clearRecovery({ localStorage, sessionStorage });
    window.history.replaceState({ workspace: "refined-blast" }, "", "/refined-building-blast");
    unmountRefinedBlastWorkbench();
    mountRefinedBlastWorkbench(root, {
      updateHistory: false, fetch, localStorage, sessionStorage,
    });
  });
  root.querySelector("[data-refined-preview]").addEventListener("click", async () => {
    await refreshPreview(root, activeSession);
  });
  root.querySelectorAll?.("[data-refined-validate]").forEach((button) => button.addEventListener("click", async () => {
    await requestValidation(root, activeSession);
  }));
  root.querySelector("[data-refined-generate]").addEventListener("click", async () => {
    await generatePackage(root, activeSession);
  });
  root.querySelector("[data-refined-open-lsprepost]").addEventListener("click", async () => {
    await requestExternalAction(root, activeSession, "open_lsprepost");
  });
  root.querySelector("[data-refined-launch-lsdyna]").addEventListener("click", async () => {
    await requestExternalAction(root, activeSession, "launch_lsdyna");
  });
  root.querySelectorAll?.("[data-refined-layer]").forEach((input) => {
    input.addEventListener("change", () => {
      const session = activeSession;
      if (!sessionIsActive(session) || !session.viewer) return;
      session.viewer.setLayerVisible(input.dataset.refinedLayer, input.checked);
      const count = root.querySelector("[data-refined-layer-count]");
      if (count) count.textContent = `${visibleLayerIds(root).length}/${PREVIEW_LAYERS.length}`;
    });
  });
  const layerToggle = root.querySelector("[data-refined-layer-toggle]");
  const layerPopover = root.querySelector("[data-refined-layer-popover]");
  const setLayerPopoverOpen = (open) => {
    if (!layerPopover || !layerToggle) return;
    layerPopover.hidden = !open;
    layerToggle.setAttribute?.("aria-expanded", open ? "true" : "false");
  };
  layerToggle?.addEventListener("click", () => setLayerPopoverOpen(Boolean(layerPopover?.hidden)));
  root.querySelector("[data-refined-layer-close]")?.addEventListener("click", () => setLayerPopoverOpen(false));
  root.querySelectorAll?.("[data-refined-inspector-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const tab = button.dataset.refinedInspectorTab;
      root.querySelectorAll?.("[data-refined-inspector-tab]").forEach((candidate) => {
        candidate.setAttribute?.("aria-selected", candidate === button ? "true" : "false");
        candidate.tabIndex = candidate === button ? 0 : -1;
      });
      root.querySelectorAll?.("[data-refined-inspector-panel]").forEach((panel) => { panel.hidden = panel.dataset.refinedInspectorPanel !== tab; });
    });
    button.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      const tabs = [...(root.querySelectorAll?.("[data-refined-inspector-tab]") ?? [])];
      const offset = event.key === "ArrowRight" ? 1 : -1;
      const next = tabs[(tabs.indexOf(button) + offset + tabs.length) % tabs.length];
      next?.click?.(); next?.focus?.(); event.preventDefault?.();
    });
  });
  const inspector = root.querySelector("#refinedBlastInspector");
  const inspectorToggle = root.querySelector("[data-refined-inspector-toggle]");
  const setInspectorOpen = (open) => {
    inspector?.classList?.toggle("is-collapsed", !open);
    root.querySelector(".refined-blast-layout")?.classList?.toggle("is-inspector-collapsed", !open);
    inspectorToggle?.setAttribute?.("aria-expanded", open ? "true" : "false");
    if (inspectorToggle) inspectorToggle.textContent = open ? "收起配置" : "打开配置";
  };
  setInspectorOpen(true);
  inspectorToggle?.addEventListener("click", () => setInspectorOpen(inspector?.classList?.contains("is-collapsed")));
  root.querySelectorAll?.("[data-refined-section]").forEach((button) => {
    button.addEventListener("click", () => {
      const session = activeSession;
      if (!sessionIsActive(session)) return;
      setInspectorOpen(true);
      session.currentStep = Number(button.dataset.refinedSection) || 1;
      root.querySelectorAll?.("[data-refined-section]").forEach((candidate) => {
        const active = candidate === button;
        candidate.classList?.toggle("is-active", active);
        if (active) candidate.setAttribute?.("aria-current", "step"); else candidate.removeAttribute?.("aria-current");
      });
      const title = root.querySelector("[data-refined-step-title]");
      if (title) title.textContent = `${String(session.currentStep).padStart(2, "0")} · ${NAVIGATION_SECTIONS[session.currentStep - 1]}`;
      renderCurrentSchema(root);
      if (session.currentStep === 8) root.querySelector('[data-refined-inspector-tab="checks"]')?.click?.();
      else root.querySelector('[data-refined-inspector-tab="config"]')?.click?.();
    });
  });
  root.querySelectorAll?.("[data-refined-camera]").forEach((button) => {
    button.addEventListener("click", () => {
      const session = activeSession;
      if (sessionIsActive(session)) session.viewer?.fitView(button.dataset.refinedCamera);
    });
  });
}

export function mountRefinedBlastWorkbench(root, options = {}) {
  const instanceToken = ++mountedInstanceToken;
  mountedRoot = root;
  const shell = buildWorkbenchShell();
  root.replaceChildren(shell);
  shell.focus?.();
  refinedBlastStore = createRefinedBlastStore({
    draft: options.draft ?? {
      scenario_id: "",
      scenario_kind: "external",
      building_placement: {},
      load_provider: {}
    },
    asset_id: options.assetId ?? null,
    revision: options.revision,
    building: options.building,
    project_id: options.projectId ?? null,
    building_compilation_state: options.buildingCompilationState,
    fetch: options.fetch
  });
  activeSession = {
    root, token: instanceToken, store: refinedBlastStore,
    projectId: typeof options.projectId === "string" && options.projectId ? options.projectId : null,
    projectMetadata: options.project ?? null, restoreProject: options.restoreProject === true, timer: null, inFlight: null, flushPromise: null, queued: false, detached: false,
    fetch: options.fetch ?? window.fetch.bind(window), previewAbortController: null,
    saveAbortController: null, saveTimeoutId: null, saveTimedOut: false,
    previewRequest: null, viewer: null,
    restoreAbortController: null,
    validationAbortController: null, acknowledgementAbortControllers: new Map(),
    persistedDraftRevision: options.projectId ? refinedBlastStore.getState().draft_revision : null,
    saveError: null, generated: null, actionInFlight: false, damageAssessment: null,
    currentStep: 1,
    copySource: null,
    pendingSessionDraft: options.sessionDraft ?? null,
    localStorage: optionalBrowserStorage(options, "localStorage"),
    sessionStorage: optionalBrowserStorage(options, "sessionStorage"),
  };
  installShellHandlers(root);
  renderSaveState(root);
  renderValidationState(root, activeSession);
  if (options.updateHistory !== false) {
    history.pushState({ workspace: "refined-blast" }, "", "/refined-building-blast");
  }
  capabilitiesRequest = loadCapabilities(root, instanceToken);
}

export function unmountRefinedBlastWorkbench() {
  if (activeSession) {
    activeSession.detached = true;
    activeSession.damageAssessment?.controller?.abort();
    activeSession.saveAbortController?.abort();
    activeSession.restoreAbortController?.abort();
    activeSession.previewAbortController?.abort();
    activeSession.validationAbortController?.abort();
    for (const controller of activeSession.acknowledgementAbortControllers.values()) controller.abort();
    activeSession.store.disposePreviewRequests(activeSession.token);
    activeSession.store.disposeValidationRequests(activeSession.token);
    activeSession.viewer?.dispose();
    activeSession.previewAbortController = null;
    activeSession.saveAbortController = null;
    if (activeSession.saveTimeoutId !== null && typeof clearTimeout === "function") {
      clearTimeout(activeSession.saveTimeoutId);
    }
    activeSession.saveTimeoutId = null;
    activeSession.saveTimedOut = false;
    activeSession.previewRequest = null;
    activeSession.validationAbortController = null;
    activeSession.acknowledgementAbortControllers.clear();
    activeSession.viewer = null;
    activeSession.restoreAbortController = null;
    if (activeSession.timer !== null) clearTimeout(activeSession.timer);
    activeSession.timer = null; activeSession.queued = false;
  }
  activeSession = null;
  if (mountedRoot) mountedRoot.replaceChildren();
  mountedRoot = null;
  capabilitiesRequest = null;
  refinedBlastStore = null;
}
