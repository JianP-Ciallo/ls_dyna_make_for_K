"use strict";

let sceneCatalog = [];
let componentCatalog = [];
let physicsActionCatalog = [];
let blastCaseCatalog = [];
let lastProjectName = "";
let promptEdited = false;
let lsppConfigured = false;
let lsrunConfigured = false;
let lsdynaConfigured = false;
let lastLsrunRunId = "";
let lastQualifiedD3plot = "";
const assemblyState = {
  components: [],
  actions: [],
  analysisControl: null,
  database: null,
  caseId: ""
};
const viewer = {
  mesh: null,
  yaw: -0.65,
  pitch: 0.55,
  zoom: 1,
  panX: 0,
  panY: 0,
  projectName: "",
  hiddenParts: new Set(),
  riskByPartId: new Map(),
  selectedImpactPartIds: new Set(),
  selectedPartId: "",
  displayMode: "solid_edges",
  mode: "model",
  showGrid: true,
  showBlastSources: true,
  showLegend: true,
  projectedFaces: [],
  resultRecord: null,
  dragging: false,
  dragButton: 0,
  pointerStartX: 0,
  pointerStartY: 0,
  pointerMoved: false,
  lastX: 0,
  lastY: 0
};
const forceCanvasViewer = new URLSearchParams(window.location.search).get("viewer") === "canvas";
const webglModelViewerModule = forceCanvasViewer
  ? Promise.resolve(null)
  : import("/model_viewer_webgl.js");
let webglModelViewer = null;
let previewMeshAbortController = null;
let previewMeshRequestSequence = 0;
const riskColors = {
  low: "#4f9d69",
  attention: "#d5aa24",
  high: "#df842f",
  severe: "#c84450"
};

async function initializeModelViewer() {
  if (forceCanvasViewer) {
    byId("modelCanvas").dataset.renderer = "canvas";
    return;
  }
  try {
    const module = await webglModelViewerModule;
    const candidate = module.createModelViewer({
      canvas: byId("modelCanvas"),
      onPartSelected: (partId) => selectViewerPart(partId),
      onContextLost: () => {
        const hint = byId("viewerHint");
        hint.textContent = "三维渲染上下文已丢失，正在等待浏览器恢复。";
        hint.classList.remove("hidden");
      },
      onContextRestored: () => {
        byId("viewerHint").classList.add("hidden");
      }
    });
    if (candidate && candidate.supported) {
      webglModelViewer = candidate;
      byId("modelCanvas").dataset.renderer = "webgl";
      return;
    }
  } catch (error) {
    console.warn("WebGL model viewer initialization failed; using Canvas fallback.", error);
  }
  byId("modelCanvas").dataset.renderer = "canvas";
}

const scenePrompts = {
  rebar_drop_on_helmet: "生成钢筋以初速度冲击头盔的受控场景。",
  rod_impact_plate: "生成圆柱杆冲击固定板的受控场景。",
  cube_top_corner_load: "生成立方体顶面四角向下受载的受控场景。",
  plate_pressure: "生成壳板受均布压力的受控场景。"
};
const controlledScenePrefix = "web_";
const aleBlastSceneId = "ale_blast";
const sceneDisplayNames = {
  rebar_drop_on_helmet: "钢筋冲击头盔",
  rod_impact_plate: "圆柱杆冲击钢板",
  cube_top_corner_load: "立方体四角受载",
  plate_pressure: "钢板均布压力",
  ale_blast: "MM-ALE 爆炸"
};
const sceneDisplaySummaries = {
  rebar_drop_on_helmet: "竖直实体钢筋从头盔上方起始，并以给定初速度冲击固定椭球壳。",
  rod_impact_plate: "实体圆柱杆以给定初速度冲击固定钢板。",
  cube_top_corner_load: "固定立方体的顶面四角承受竖直向下载荷。",
  plate_pressure: "周边固定的壳板承受均布压力。"
};
const fieldDisplayNames = {
  rebar_length_m: "钢筋长度",
  rebar_radius_m: "钢筋半径",
  drop_height_m: "起始间距",
  impact_velocity_m_per_s: "冲击初速度",
  rod_length_m: "圆柱杆长度",
  rod_radius_m: "圆柱杆半径",
  plate_length_m: "钢板长度",
  plate_width_m: "钢板宽度",
  plate_thickness_m: "钢板厚度",
  cube_length_m: "立方体长度",
  cube_width_m: "立方体宽度",
  cube_height_m: "立方体高度",
  corner_force_n: "单角载荷",
  pressure_pa: "均布压力",
  material_name: "材料"
};

function byId(id) {
  return document.getElementById(id);
}

function setTaskPanelOpen(open) {
  const panel = byId("rightInspector");
  if (panel) panel.hidden = !open;
  document.querySelector("#legacyWorkbenchRoot .workbench-layout")?.classList.toggle("is-inspector-open", open);
  const toggle = byId("toggleTaskPanel");
  toggle?.setAttribute("aria-expanded", String(open));
  if (open) toggle?.removeAttribute("data-has-update");
}

function selectInspectorPanel(panelId) {
  setTaskPanelOpen(true);
  for (const panel of document.querySelectorAll(".inspector-panel")) {
    panel.classList.toggle("hidden", panel.id !== panelId);
  }
  for (const tab of document.querySelectorAll(".inspector-tab")) {
    const active = tab.dataset.inspectorTarget === panelId;
    tab.classList.toggle("active", active);
    tab.classList.remove("has-update");
    tab.setAttribute("aria-selected", String(active));
  }
}

function markInspectorUpdate(panelId) {
  const panel = byId(panelId);
  if (byId("rightInspector")?.hidden) byId("toggleTaskPanel")?.setAttribute("data-has-update", "true");
  if (!panel || !panel.classList.contains("hidden")) return;
  const tab = document.querySelector(`[data-inspector-target="${panelId}"]`);
  if (tab) tab.classList.add("has-update");
}

function setupWorkbenchNavigation() {
  byId("toggleTaskPanel")?.addEventListener("click", () => setTaskPanelOpen(Boolean(byId("rightInspector")?.hidden)));
  byId("closeTaskPanel")?.addEventListener("click", () => {
    setTaskPanelOpen(false);
    byId("toggleTaskPanel")?.focus();
  });
  for (const button of document.querySelectorAll("[data-resource-panel]")) {
    button.addEventListener("click", () => {
      const panelId = button.dataset.resourcePanel;
      const target = byId(panelId);
      const shouldOpen = target.classList.contains("hidden");
      for (const panel of document.querySelectorAll(".resource-panel")) {
        panel.classList.add("hidden");
      }
      for (const item of document.querySelectorAll("[data-resource-panel]")) {
        item.setAttribute("aria-selected", "false");
      }
      if (shouldOpen) {
        target.classList.remove("hidden");
        button.setAttribute("aria-selected", "true");
      }
    });
  }
  for (const button of document.querySelectorAll("[data-close-resource]")) {
    button.addEventListener("click", () => {
      button.closest(".resource-panel").classList.add("hidden");
      for (const item of document.querySelectorAll("[data-resource-panel]")) {
        item.setAttribute("aria-selected", "false");
      }
    });
  }
  for (const tab of document.querySelectorAll("[data-inspector-target]")) {
    tab.addEventListener("click", () => selectInspectorPanel(tab.dataset.inspectorTarget));
  }
}

const PICKER_BUTTON_IDS = new Set([
  "importLspp",
  "selectExportDir",
  "selectImportPackageDir",
  "importLsrun",
  "importLsdyna"
]);
let globalBusy = false;
let pickerBusy = false;
const pickerDisabledState = new Map();

function applyBusyState() {
  document.body.classList.toggle("global-busy", globalBusy);
  document.body.setAttribute("aria-busy", String(globalBusy));
  for (const id of PICKER_BUTTON_IDS) {
    const button = byId(id);
    if (!button) continue;
    if (pickerBusy) {
      if (!pickerDisabledState.has(button)) pickerDisabledState.set(button, button.disabled);
      button.disabled = true;
    } else if (pickerDisabledState.has(button)) {
      button.disabled = pickerDisabledState.get(button);
      pickerDisabledState.delete(button);
    }
  }
  if (!globalBusy && isTunnelBlastMode()) updateTunnelMeshEstimate();
}

function setBusy(isBusy) {
  globalBusy = isBusy;
  applyBusyState();
}

function setPickerBusy(isBusy) {
  pickerBusy = isBusy;
  applyBusyState();
}

document.addEventListener("click", (event) => {
  if (!globalBusy) return;
  const button = event.target.closest("button");
  if (!button) return;
  event.preventDefault();
  event.stopImmediatePropagation();
}, true);

function showResult(value) {
  byId("result").textContent = JSON.stringify(value, null, 2);
}

function summaryRow(label, value) {
  if (value === undefined || value === null || value === "") return null;
  const row = document.createElement("div");
  row.className = "summary-row";
  const labelNode = document.createElement("span");
  labelNode.className = "summary-label";
  labelNode.textContent = label;
  const valueNode = document.createElement("span");
  valueNode.className = "summary-value";
  valueNode.textContent = Array.isArray(value) ? value.join("、") : String(value);
  row.appendChild(labelNode);
  row.appendChild(valueNode);
  return row;
}

function summarizeResult(label, result) {
  const rows = [["操作", label], ["状态", "完成"]];
  const writeResult = result && result.write_result ? result.write_result : {};
  const projectName = result.project_name || result.project || writeResult.project || "";
  const projectDir = result.project_dir || writeResult.project_dir || "";

  if (result.mode === "keyword_preview") {
    rows[1][1] = result.status === "started" ? "已启动" : "启动状态待确认";
    rows.push(["项目名称", projectName]);
    rows.push(["进程编号", result.pid]);
    rows.push(["进程存活", result.process_running ? "已确认" : "未确认"]);
    rows.push(["模型文件", result.keyword_path]);
    return rows;
  }

  if (result.operation === "import_project_package") {
    rows.push(["项目名称", result.project_name]);
    rows.push(["导入来源", result.source_dir]);
    rows.push(["模型文件", "已导入 model.k"]);
    rows.push(["附带信息", result.copied_files]);
    rows.push(["检查结果", result.checks_ok ? "通过" : "需要复核"]);
    rows.push(["保存位置", result.project_dir]);
    return rows;
  }

  if (result.operation === "open_lsrun" || result.operation === "lsrun_handoff") {
    rows.push(["项目名称", result.project_name]);
    rows.push(["输入 K 文件", result.input]);
    rows.push(["独立运行目录", result.run_dir || result.workdir]);
    if (result.run_id) rows.push(["运行编号", result.run_id]);
    rows.push(["交接状态", result.status || "handoff_opened"]);
    rows.push(["LS-Run", result.lsrun_exe]);
    if (result.lsdyna_exe) rows.push(["LS-DYNA 求解器", result.lsdyna_exe]);
    rows.push(["命令预览", result.command_preview]);
    return rows;
  }

  if (result.operation === "run_lsdyna" || result.operation === "lsdyna_status") {
    rows.push(["项目名称", result.project_name]);
    rows.push(["求解状态", result.status]);
    if (result.run_id) rows.push(["运行编号", result.run_id]);
    if (result.run_dir) rows.push(["独立运行目录", result.run_dir]);
    if (result.returncode !== undefined && result.returncode !== null) rows.push(["返回码", result.returncode]);
    if (result.outputs && result.outputs.d3plot) {
      rows.push(["d3plot", result.outputs.d3plot.ok ? "已生成" : "缺失"]);
    }
    if (result.outputs && result.outputs.blstfor) {
      rows.push(["爆炸载荷结果", result.outputs.blstfor.ok ? "已生成" : "缺失"]);
    }
    if (result.postprocessing) rows.push(["云图复核", result.postprocessing.status]);
    if (result.phase13_metrics && result.phase13_metrics.metrics) {
      const available = Object.values(result.phase13_metrics.metrics)
        .filter((metric) => metric.status === "available").length;
      rows.push(["可比较指标", `${available} 项`]);
      appendPhase13MetricRows(rows, result.phase13_metrics.metrics);
    }
    return rows;
  }

  if (result.run_count && result.comparisons) {
    rows.push(["对比运行", `${result.run_count} 个`]);
    rows.push(["共同可用指标", `${Object.keys(result.comparisons).length} 项`]);
    for (const [metricId, comparison] of Object.entries(result.comparisons)) {
      rows.push([
        `${phase13MetricLabel(metricId)}范围`,
        `${formatMetricNumber(comparison.minimum)} - ${formatMetricNumber(comparison.maximum)} ${comparison.unit}`
      ]);
    }
    const configuration = result.configuration_comparison || {};
    if (configuration.warning) rows.push(["方案变量提示", configuration.warning.message]);
    return rows;
  }

  if (result.tnt_consistency) {
    rows[1][1] = result.needs_confirmation ? "需要用户确认" : "几何准备完成";
    const consistency = result.tnt_consistency;
    const provenance = consistency.provenance || {};
    rows.push(["装药冲突决策", provenance.decision || "尚未选择"]);
    if (consistency.geometric_mass_kg !== undefined) {
      rows.push(["按原尺寸计算质量", `${formatMetricNumber(consistency.geometric_mass_kg)} kg`]);
    }
    if (consistency.effective_mass_kg !== undefined) {
      rows.push(["采用质量", `${formatMetricNumber(consistency.effective_mass_kg)} kg`]);
    }
    if (consistency.effective_length_m !== undefined) {
      rows.push(["采用药柱长度", `${formatMetricNumber(consistency.effective_length_m)} m`]);
    }
    if (result.axisymmetric_region_mesh) {
      const mesh = result.axisymmetric_region_mesh;
      rows.push(["四区网格", `${mesh.total_element_count} 个单元，${mesh.total_node_count} 个节点`]);
      const regionLabels = {
        concrete: "混凝土",
        tnt: "TNT",
        air: "空气与孔道",
        steel_hoop: "外侧钢箍"
      };
      for (const [regionName, region] of Object.entries(mesh.regions || {})) {
        rows.push([`${regionLabels[regionName] || regionName}区域`, `${region.element_count} 个单元`]);
      }
      rows.push(["接口与网格门禁", mesh.quality_issue_count === 0 ? "通过" : `${mesh.quality_issue_count} 项问题`]);
    }
    rows.push(["K 文件生成", result.generation_available ? "已开放" : "尚未开放"]);
    if (result.reason_generation_is_disabled) {
      rows.push(["未开放原因", result.reason_generation_is_disabled]);
    }
    return rows;
  }

  if (projectName) rows.push(["项目名称", projectName]);
  if (projectDir) rows.push(["保存位置", projectDir]);
  if (result.output_path) rows.push(["输出文件", result.output_path]);
  if (result.user_export && result.user_export.project_export_dir) {
    rows.push(["额外保存位置", result.user_export.project_export_dir]);
  }
  if (result.message) rows.push(["说明", result.message]);
  if (result.parts && result.nodes !== undefined) {
    rows.push(["模型内容", `${result.parts.length} 个部件，${result.nodes} 个节点，${result.faces} 个面`]);
  }
  if (result.sensitivity) {
    rows.push(["简化爆炸检查", result.sensitivity.ok_for_demo ? "通过演示门禁" : "存在阻塞项"]);
    rows.push(["敏感性提示", `${(result.sensitivity.warnings || []).length} 项`]);
  }
  return rows;
}

function appendPhase13MetricRows(rows, metrics) {
  for (const [metricId, metric] of Object.entries(metrics || {})) {
    if (!metric || metric.status !== "available") continue;
    let value = `${formatMetricNumber(metric.value)} ${metric.unit}`;
    if (metric.time_s !== undefined && metric.time_s !== null) {
      value += `，发生于 ${formatMetricNumber(metric.time_s)} s`;
    }
    if (metric.quality) {
      const qualityLabels = { adequate: "充分", limited: "有限", coarse: "粗略" };
      value += `，采样质量：${qualityLabels[metric.quality] || metric.quality}`;
    }
    rows.push([phase13MetricLabel(metricId), value]);
  }
}

function phase13MetricLabel(metricId) {
  const labels = {
    hourglass_energy_ratio: "沙漏能占比",
    total_initial_energy_ratio: "总能量比",
    peak_von_mises_stress: "峰值等效应力",
    peak_displacement: "峰值位移",
    peak_blast_pressure: "峰值爆炸压力",
    positive_phase_impulse: "正相冲量",
    positive_phase_duration: "正相持续时间",
    d3plot_size: "d3plot 大小",
    blstfor_size: "blstfor 大小",
    nodout_size: "nodout 大小"
  };
  return labels[metricId] || metricId;
}

function formatMetricNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "不可用";
  const absolute = Math.abs(number);
  if ((absolute > 0 && absolute < 0.001) || absolute >= 1000000) return number.toExponential(4);
  return Number(number.toPrecision(6)).toString();
}

function showOperationSummary(label, result) {
  const box = byId("result");
  box.innerHTML = "";

  const wrapper = document.createElement("div");
  wrapper.className = "operation-summary";
  const title = document.createElement("h3");
  title.textContent = "操作结果";
  wrapper.appendChild(title);

  const list = document.createElement("div");
  list.className = "summary-list";
  for (const [rowLabel, rowValue] of summarizeResult(label, result || {})) {
    const row = summaryRow(rowLabel, rowValue);
    if (row) list.appendChild(row);
  }
  wrapper.appendChild(list);

  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "查看详细信息";
  const pre = document.createElement("pre");
  pre.className = "detail-json";
  pre.textContent = JSON.stringify(result, null, 2);
  details.appendChild(summary);
  details.appendChild(pre);
  wrapper.appendChild(details);

  box.appendChild(wrapper);
  markInspectorUpdate("inspectorResults");
}

function showStatus(message) {
  byId("result").innerHTML = "";
  const span = document.createElement("span");
  span.className = "status";
  span.textContent = message;
  byId("result").appendChild(span);
  markInspectorUpdate("inspectorResults");
}

function showError(error) {
  const message = error && error.message ? error.message : String(error);
  showOperationSummary("操作失败", { operation: "error", message });
  if (!byId("legacyWorkbenchRoot")?.classList.contains("hidden")) selectInspectorPanel("inspectorResults");
}

function setLsppStatus(config) {
  const doctor = config.doctor || {};
  lsppConfigured = Boolean(config.configured && doctor.ok);
  byId("lsppExe").value = config.lspp_exe || "";
  byId("lsppStatus").textContent = lsppConfigured
    ? `LS-PrePost 已配置：${config.lspp_exe}`
    : "尚未配置 LS-PrePost。生成 K 文件仍可使用，预览和打开功能需要导入有效的 lsprepost*.exe。";
  setExportDirStatus(config);
  setSolveStatus(config);
}

function setExportDirStatus(config) {
  const exportDir = config.export_dir || "";
  byId("exportDir").value = exportDir;
  byId("exportDirStatus").textContent = config.export_dir_configured
    ? `模型会额外保存到：${exportDir}`
    : "未配置自定义保存路径。模型仍会保存在项目 workspace 中。";
}

function setSolveStatus(config) {
  const lsrunDoctor = config.lsrun_doctor || {};
  const lsdynaDoctor = config.lsdyna_doctor || {};
  lsrunConfigured = Boolean(config.lsrun_configured && lsrunDoctor.ok);
  lsdynaConfigured = Boolean(config.lsdyna_configured && lsdynaDoctor.ok);
  byId("lsrunExe").value = config.lsrun_exe || "";
  byId("lsdynaExe").value = config.lsdyna_exe || "";
  byId("solveNcpu").value = config.solve_ncpu || 4;
  byId("solveMemory").value = config.solve_memory || "20m";
  byId("solveTimeout").value = config.solve_timeout_s || 600;
  byId("solveCommandPreview").textContent = config.solve_command_template || '"$SOLVER" i="$INPUT" ncpu=$NCPU memory=$MEMORY';
  if (lsrunConfigured && config.lsdyna_configured && lsdynaDoctor.ok) {
    byId("lsrunStatus").textContent = `LS-Run 与求解器已配置。LS-Run：${config.lsrun_exe}`;
  } else if (lsrunConfigured) {
    byId("lsrunStatus").textContent = `LS-Run 已配置：${config.lsrun_exe}。可先送入 LS-Run，求解器路径建议继续配置。`;
  } else {
    byId("lsrunStatus").textContent = "尚未配置 LS-Run。需要选择真实存在的 lsrun.exe。";
  }
}

async function api(path, options) {
  const request = Object.assign({ headers: { Accept: "application/json" } }, options || {});
  if (request.body) {
    request.headers = Object.assign({}, request.headers, { "Content-Type": "application/json" });
  }

  const response = await fetch(path, request);
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    const error = payload.error || { message: `请求失败：${response.status}` };
    throw new Error(error.message || error.code || "请求失败");
  }
  return payload.result;
}

async function loadConfig() {
  const config = await api("/api/config");
  setLsppStatus(config);
  return config;
}

async function importLsppPath() {
  return runPickerAction("正在打开 LS-PrePost 文件选择窗口", "lsppStatus", async () => {
    const result = await api("/api/config/select-lsprepost", {
      method: "POST",
      body: JSON.stringify({})
    });
    setLsppStatus(result);
    return result;
  });
}

async function checkLsppPath() {
  return runAction("正在检测 LS-PrePost 路径", async () => {
    const result = await api("/api/config/check-lsprepost", {
      method: "POST",
      body: JSON.stringify({ lspp_exe: byId("lsppExe").value.trim() })
    });
    byId("lsppStatus").textContent = result.doctor && result.doctor.ok
      ? `路径有效：${result.lspp_exe}`
      : "路径无效。请选择真实存在的 lsprepost*.exe 文件。";
    return result;
  });
}

async function saveLsppPath() {
  return runAction("正在保存 LS-PrePost 路径", async () => {
    const result = await api("/api/config/lsprepost", {
      method: "POST",
      body: JSON.stringify({ lspp_exe: byId("lsppExe").value.trim() })
    });
    setLsppStatus(result);
    return result;
  });
}

async function selectExportDir() {
  return runPickerAction("正在打开模型保存位置选择窗口", "exportDirStatus", async () => {
    const result = await api("/api/config/select-export-dir", {
      method: "POST",
      body: JSON.stringify({})
    });
    setExportDirStatus(result);
    return result;
  });
}

async function saveExportDir() {
  return runAction("正在保存模型保存路径", async () => {
    const result = await api("/api/config/export-dir", {
      method: "POST",
      body: JSON.stringify({ export_dir: byId("exportDir").value.trim() })
    });
    setExportDirStatus(result);
    return result;
  });
}

async function checkLsrunPath() {
  return runAction("正在检测 LS-Run 路径", async () => {
    const result = await api("/api/config/check-lsrun", {
      method: "POST",
      body: JSON.stringify({ lsrun_exe: byId("lsrunExe").value.trim() })
    });
    byId("lsrunStatus").textContent = result.doctor && result.doctor.ok
      ? `LS-Run 路径有效：${result.lsrun_exe}`
      : "LS-Run 路径无效。请选择真实存在的 lsrun.exe 文件。";
    return result;
  });
}

async function importLsrunPath() {
  return runPickerAction("正在打开 LS-Run 文件选择窗口", "lsrunStatus", async () => {
    const result = await api("/api/config/select-lsrun", {
      method: "POST",
      body: JSON.stringify({})
    });
    setSolveStatus(result);
    return result;
  });
}

async function saveLsrunPath() {
  return runAction("正在保存 LS-Run 路径", async () => {
    const result = await api("/api/config/lsrun", {
      method: "POST",
      body: JSON.stringify({ lsrun_exe: byId("lsrunExe").value.trim() })
    });
    setSolveStatus(result);
    return result;
  });
}

async function importLsdynaPath() {
  return runPickerAction("正在打开 LS-DYNA 文件选择窗口", "lsrunStatus", async () => {
    const result = await api("/api/config/select-lsdyna", {
      method: "POST",
      body: JSON.stringify({})
    });
    setSolveStatus(result);
    return result;
  });
}

async function checkLsdynaPath() {
  return runAction("正在检测 LS-DYNA 求解器路径", async () => {
    const result = await api("/api/config/check-lsdyna", {
      method: "POST",
      body: JSON.stringify({ lsdyna_exe: byId("lsdynaExe").value.trim() })
    });
    byId("lsrunStatus").textContent = result.doctor && result.doctor.ok
      ? `LS-DYNA 求解器路径有效：${result.lsdyna_exe}`
      : "LS-DYNA 求解器路径无效。请选择真实存在的 .exe 文件。";
    return result;
  });
}

async function saveLsdynaPath() {
  return runAction("正在保存 LS-DYNA 求解器路径", async () => {
    const result = await api("/api/config/lsdyna", {
      method: "POST",
      body: JSON.stringify({ lsdyna_exe: byId("lsdynaExe").value.trim() })
    });
    setSolveStatus(result);
    return result;
  });
}

function importProjectNameValue() {
  return byId("importPackageProjectName").value.trim();
}

async function finishImportedProject(result) {
  lastProjectName = result.project_name || "";
  if (lastProjectName) {
    byId("projectName").value = lastProjectName;
    if (!byId("importPackageProjectName").value.trim()) {
      byId("importPackageProjectName").value = lastProjectName;
    }
  }
  if (result.source_dir) {
    byId("importPackageDir").value = result.source_dir;
  }
  refreshActionAvailability();
  byId("importPackageStatus").textContent = result.project_name
    ? `已导入模型：${result.project_name}`
    : "模型已导入。";
  updateContextStatus();
  await loadProjects();
  if (lastProjectName) {
    await loadInteractiveMesh(lastProjectName);
  }
}

async function selectImportPackageDir() {
  return runPickerAction("正在打开模型文件夹选择窗口", "importPackageStatus", async () => {
    const result = await api("/api/project/select-import-package", {
      method: "POST",
      body: JSON.stringify({
        project_name: importProjectNameValue(),
        if_exists: "versioned"
      })
    });
    await finishImportedProject(result);
    return result;
  });
}

async function importPackage() {
  return runAction("正在导入完整模型文件夹", async () => {
    const result = await api("/api/project/import-package", {
      method: "POST",
      body: JSON.stringify({
        source_dir: byId("importPackageDir").value.trim(),
        project_name: importProjectNameValue(),
        if_exists: "versioned"
      })
    });
    await finishImportedProject(result);
    return result;
  });
}

function selectedScene() {
  const id = byId("scene").value;
  return sceneCatalog.find((scene) => scene.id === id) || sceneCatalog[0] || null;
}

function defaultPrompt(scene) {
  if (!scene) return "";
  return scenePrompts[scene.id] || `生成${scene.title}。`;
}

function currentProjectName() {
  return byId("projectName").value.trim();
}

function isAssemblyMode() {
  return byId("modelMode").value === "assembly";
}

function isAleBlastMode() {
  return byId("modelMode").value === "controlled" && byId("scene").value === aleBlastSceneId;
}

function isTunnelBlastMode() {
  return byId("modelMode").value === "tunnel_blast";
}

function isPhase15Mode() {
  return byId("modelMode").value === "phase15_a1";
}

const phase15PreparationNotice = "Phase 15 A-1 二维轴对称求解草案";

function refreshActionAvailability() {
  const currentReady = Boolean(lastProjectName && lastProjectName === currentProjectName());
  byId("generate").disabled = false;
  byId("preview").disabled = !currentReady;
  byId("openLspp").disabled = !currentReady;
  byId("recoverLsrun").disabled = !lastLsrunRunId;
  byId("openResultLspp").disabled = !lastQualifiedD3plot;
}

function updatePhase15FsiOverlapSummary() {
  const meshSize = Number(byId("phase15MeshSize").value);
  const layers = Number(byId("phase15FsiOverlapLayers").value);
  const depthMm = meshSize * layers * 1000;
  const guidance = layers === 1
    ? "最小覆盖，生成后需重点检查所有耦合线段是否双侧覆盖。"
    : layers === 2
      ? "当前稳定基线，适合保持既有 Phase 15 行为。"
      : "增强搜索范围，仅建议用于敏感性比较。";
  byId("phase15FsiOverlapSummary").textContent =
    `当前数值侵入深度为 ${depthMm.toFixed(1)} mm（${layers} 层 × ${(meshSize * 1000).toFixed(1)} mm）。${guidance} 这不是物理空气层厚度。`;
}

function updatePhase15AirGapSummary(resolvedAirGap) {
  const chargeRadius = Number(byId("phase15TntDiameter").value) / 2;
  const boreholeRadius = Number(byId("phase15BoreholeRadius").value);
  const bottomGap = Number(byId("phase15BottomAirGap").value);
  const sideGap = boreholeRadius - chargeRadius;
  const summary = byId("phase15AirGapSummary");
  if (resolvedAirGap && Number.isInteger(resolvedAirGap.side_air_gap_cells) && Number.isInteger(resolvedAirGap.bottom_air_gap_cells)) {
    const sideCells = resolvedAirGap.side_air_gap_cells;
    const bottomCells = resolvedAirGap.bottom_air_gap_cells;
    const valid = sideCells >= 3 && bottomCells >= 3;
    summary.classList.toggle("warning", !valid);
    summary.textContent = valid
      ? `侧向空气间隙 ${(sideGap * 1000).toFixed(1)} mm（${sideCells} 个实际单元）；底部空气间隙 ${(bottomGap * 1000).toFixed(1)} mm（${bottomCells} 个实际单元）。`
      : `实际网格不足：侧向 ${sideCells} 个单元，底部 ${bottomCells} 个单元；两处都必须至少为 3 个实际 ALE 单元。`;
    return;
  }
  const dimensionsValid = sideGap > 0 && bottomGap > 0;
  summary.classList.toggle("warning", !dimensionsValid);
  summary.textContent = dimensionsValid
    ? `侧向空气间隙 ${(sideGap * 1000).toFixed(1)} mm；底部空气间隙 ${(bottomGap * 1000).toFixed(1)} mm。检查参数后显示后端生成的实际单元数。`
    : "孔半径必须大于 TNT 半径，底部空气间隙必须大于 0。";
}

function updatePhase15CouplingControls() {
  const conforming = byId("phase15CouplingMode").value === "conforming_air_gap";
  byId("phase15ImmersedFields").classList.toggle("hidden", conforming);
  byId("phase15ConformingFields").classList.toggle("hidden", !conforming);
  if (conforming) updatePhase15AirGapSummary();
  else updatePhase15FsiOverlapSummary();
}

function phase15Payload() {
  const couplingMode = byId("phase15CouplingMode").value;
  const payload = {
    project_name: currentProjectName(),
    coupling_mode: couplingMode,
    tnt_mass_kg: aleBlastNumber("phase15TntMass"),
    tnt_diameter_m: aleBlastNumber("phase15TntDiameter"),
    tnt_length_m: aleBlastNumber("phase15TntLength"),
    tnt_density_kg_per_m3: aleBlastNumber("phase15TntDensity"),
    consistency_mode: byId("phase15ConsistencyMode").value,
    target_radius_m: aleBlastNumber("phase15TargetRadius"),
    target_height_m: aleBlastNumber("phase15TargetHeight"),
    mesh_size_m: aleBlastNumber("phase15MeshSize"),
    steel_thickness_m: aleBlastNumber("phase15SteelThickness"),
    concrete_fpc_pa: aleBlastNumber("phase15ConcreteFpcMpa") * 1.0e6,
    concrete_density_kg_per_m3: aleBlastNumber("phase15ConcreteDensity"),
    steel_yield_strength_pa: aleBlastNumber("phase15SteelYieldMpa") * 1.0e6,
    erosion_mode: byId("phase15ErosionMode").value,
    end_time_s: aleBlastNumber("phase15EndTimeMs") * 1.0e-3,
    early_output_dt_s: aleBlastNumber("phase15EarlyDtUs") * 1.0e-6,
    late_output_dt_s: aleBlastNumber("phase15LateDtUs") * 1.0e-6,
    history_output_dt_s: aleBlastNumber("phase15HistoryDtUs") * 1.0e-6
  };
  if (couplingMode === "immersed_clis") {
    payload.fsi_overlap_layers = Number(byId("phase15FsiOverlapLayers").value);
  } else {
    payload.borehole_radius_m = aleBlastNumber("phase15BoreholeRadius");
    payload.bottom_air_gap_m = aleBlastNumber("phase15BottomAirGap");
  }
  return payload;
}

function phase15PreparationPayload() {
  const payload = phase15Payload();
  const preparation = {
    coupling_mode: payload.coupling_mode,
    tnt_mass_kg: payload.tnt_mass_kg,
    tnt_diameter_m: payload.tnt_diameter_m,
    tnt_length_m: payload.tnt_length_m,
    tnt_density_kg_per_m3: payload.tnt_density_kg_per_m3,
    consistency_mode: payload.consistency_mode,
    target_radius_m: payload.target_radius_m,
    target_height_m: payload.target_height_m,
    mesh_size_m: payload.mesh_size_m
  };
  if (payload.coupling_mode === "immersed_clis") {
    preparation.fsi_overlap_layers = payload.fsi_overlap_layers;
  } else {
    preparation.borehole_radius_m = payload.borehole_radius_m;
    preparation.bottom_air_gap_m = payload.bottom_air_gap_m;
  }
  return preparation;
}

function setPhase15Badge(id, state, text) {
  const badge = byId(id);
  badge.dataset.state = state;
  const detail = badge.querySelector("small");
  if (detail) detail.textContent = text;
}

function resetPhase15Qualification() {
  setPhase15Badge("phase15StaticBadge", "pending", "待检查");
  setPhase15Badge("phase15SolverBadge", "pending", "待运行");
  setPhase15Badge("phase15TransferBadge", "pending", "待验证");
  setPhase15Badge("phase15CalibrationBadge", "warning", "未标定");
  lastLsrunRunId = "";
  lastQualifiedD3plot = "";
  refreshActionAvailability();
}

function updatePhase15Qualification(result) {
  if (!result || typeof result !== "object") return;
  if (result.ready_for_axisymmetric_compiler !== undefined) {
    setPhase15Badge(
      "phase15StaticBadge",
      result.ready_for_axisymmetric_compiler ? "passed" : "failed",
      result.ready_for_axisymmetric_compiler ? "参数通过" : "参数失败"
    );
  }
  if (result.operation === "generate_phase15_a1" || result.write_result) {
    setPhase15Badge("phase15StaticBadge", result.ok === false ? "failed" : "passed", result.ok === false ? "生成失败" : "K 文件通过");
  }
  if (result.run_id) lastLsrunRunId = result.run_id;
  if (result.status === "handoff_opened") {
    setPhase15Badge("phase15SolverBadge", "pending", "LS-Run 已打开");
    setPhase15Badge("phase15TransferBadge", "pending", "等待回收");
  }
  if (result.solver_evaluation) {
    setPhase15Badge(
      "phase15SolverBadge",
      result.solver_evaluation.ok ? "passed" : "failed",
      result.solver_evaluation.ok ? "正常完成" : "求解未通过"
    );
  }
  if (result.wave_transfer_acceptance) {
    const transferOk = result.wave_transfer_acceptance.wave_transfer_verified === true;
    setPhase15Badge(
      "phase15TransferBadge",
      transferOk ? "passed" : "failed",
      transferOk ? "传播已验证" : "传播未通过"
    );
  }
  const d3plotReady = result.ok === true && result.status === "completed";
  lastQualifiedD3plot = d3plotReady ? String(result.run_id || "") : "";
  setPhase15Badge("phase15CalibrationBadge", "warning", "K&C 未标定");
  refreshActionAvailability();
}

function aleBlastNumber(id) {
  const value = Number(byId(id).value);
  if (!Number.isFinite(value)) throw new Error(`${id} 必须是有限数值。`);
  return value;
}

function aleBlastPayload(extra) {
  const domainX = aleBlastNumber("aleDomainX");
  const domainY = aleBlastNumber("aleDomainY");
  const domainZ = aleBlastNumber("aleDomainZ");
  const bottomZ = -0.05;
  const projectName = currentProjectName();
  lastProjectName = projectName;
  return Object.assign({
    project_name: projectName,
    domain_min_m: [-0.5 * domainX, -0.5 * domainY, bottomZ],
    domain_max_m: [0.5 * domainX, 0.5 * domainY, bottomZ + domainZ],
    explosive_center_m: [0, 0, aleBlastNumber("aleExplosiveZ")],
    explosive_mass_kg: aleBlastNumber("aleExplosiveMass"),
    mesh_size_m: aleBlastNumber("aleMeshSize"),
    plate_length_m: aleBlastNumber("alePlateLength"),
    plate_width_m: aleBlastNumber("alePlateWidth"),
    plate_thickness_m: aleBlastNumber("alePlateThickness"),
    plate_z_m: 0,
    end_time_s: aleBlastNumber("aleEndTime")
  }, extra || {});
}

const tunnelMeshLabels = {
  "0.075": "较高精细度，计算量较大",
  "0.1": "均衡，推荐",
  "0.125": "较快速，细节较少",
  "0.15": "快速预览，不适合定量分析"
};

function estimateTunnelAleCells() {
  const length = aleBlastNumber("tunnelLength");
  const width = aleBlastNumber("tunnelWidth");
  const height = aleBlastNumber("tunnelHeight");
  const mesh = aleBlastNumber("tunnelAirMesh");
  const nx = Math.max(1, Math.round(length / mesh));
  const ny = Math.max(1, Math.round(width / mesh));
  const nz = Math.max(1, Math.round(height / mesh));
  const aleElements = nx * ny * nz;
  const wallElements = 2 * nx * ny + 2 * nx * nz;
  const plateNy = Math.max(1, Math.round(aleBlastNumber("tunnelPlateLength") / 0.05));
  const plateNz = Math.max(1, Math.round(aleBlastNumber("tunnelPlateWidth") / 0.05));
  const plateElements = plateNy * plateNz;
  return {
    mesh,
    cells: [nx, ny, nz],
    aleElements,
    estimatedTotalElements: aleElements + wallElements + plateElements
  };
}

function updateTunnelPositionLimits() {
  const length = aleBlastNumber("tunnelLength");
  const width = aleBlastNumber("tunnelWidth");
  const height = aleBlastNumber("tunnelHeight");
  const mass = aleBlastNumber("tunnelExplosiveMass");
  const plateLength = aleBlastNumber("tunnelPlateLength");
  const plateWidth = aleBlastNumber("tunnelPlateWidth");
  const chargeRadius = Math.cbrt((3 * mass) / (4 * Math.PI * 1700));
  const epsilon = 0.000001;
  const ranges = {
    tunnelExplosiveX: [chargeRadius + epsilon, length - chargeRadius - epsilon],
    tunnelExplosiveY: [-0.5 * width + chargeRadius + epsilon, 0.5 * width - chargeRadius - epsilon],
    tunnelExplosiveZ: [-0.5 * height + chargeRadius + epsilon, 0.5 * height - chargeRadius - epsilon],
    tunnelPlateX: [epsilon, length - epsilon],
    tunnelPlateY: [-0.5 * width + 0.5 * plateLength + epsilon, 0.5 * width - 0.5 * plateLength - epsilon],
    tunnelPlateZ: [-0.5 * height + 0.5 * plateWidth + epsilon, 0.5 * height - 0.5 * plateWidth - epsilon]
  };
  for (const [id, range] of Object.entries(ranges)) {
    const input = byId(id);
    input.min = String(range[0]);
    input.max = String(range[1]);
    input.title = `允许范围：${range[0].toFixed(3)} 至 ${range[1].toFixed(3)} m`;
  }
  return ranges;
}

function updateTunnelMeshEstimate() {
  const box = byId("tunnelMeshEstimate");
  if (!box) return;
  try {
    updateTunnelPositionLimits();
    const estimate = estimateTunnelAleCells();
    const label = tunnelMeshLabels[String(estimate.mesh)] || "自定义";
    const overLimit = estimate.estimatedTotalElements > 350000;
    box.classList.toggle("warning", overLimit);
    box.textContent = overLimit
      ? `预计总单元 ${estimate.estimatedTotalElements.toLocaleString()}，超过 350,000 上限。请增大网格或减小通道尺寸。`
      : `统一空气网格 ${estimate.cells.join(" × ")}；ALE 单元约 ${estimate.aleElements.toLocaleString()}，预计总单元 ${estimate.estimatedTotalElements.toLocaleString()}。${label}。`;
    if (isTunnelBlastMode()) {
      byId("resolve").disabled = overLimit;
      byId("generate").disabled = overLimit;
      byId("preview").disabled = overLimit;
    }
  } catch (error) {
    box.classList.add("warning");
    box.textContent = `无法估算网格：${error.message}`;
  }
}

function tunnelBlastPayload(extra) {
  const projectName = currentProjectName();
  lastProjectName = projectName;
  return Object.assign({
    project_name: projectName,
    tunnel_length_m: aleBlastNumber("tunnelLength"),
    tunnel_width_m: aleBlastNumber("tunnelWidth"),
    tunnel_height_m: aleBlastNumber("tunnelHeight"),
    tunnel_wall_thickness_m: aleBlastNumber("tunnelWallThickness"),
    air_mesh_size_m: aleBlastNumber("tunnelAirMesh"),
    explosive_center_m: [
      aleBlastNumber("tunnelExplosiveX"),
      aleBlastNumber("tunnelExplosiveY"),
      aleBlastNumber("tunnelExplosiveZ")
    ],
    explosive_mass_kg: aleBlastNumber("tunnelExplosiveMass"),
    plate_length_m: aleBlastNumber("tunnelPlateLength"),
    plate_width_m: aleBlastNumber("tunnelPlateWidth"),
    plate_thickness_m: aleBlastNumber("tunnelPlateThickness"),
    plate_center_m: [
      aleBlastNumber("tunnelPlateX"),
      aleBlastNumber("tunnelPlateY"),
      aleBlastNumber("tunnelPlateZ")
    ],
    plate_material_name: byId("tunnelPlateMaterial").value,
    end_time_s: aleBlastNumber("tunnelEndTime")
  }, extra || {});
}

function componentDefinition(template) {
  return componentCatalog.find((item) => item.name === template) || null;
}

function nextComponentId(template) {
  const base = String(template || "component").replace(/[^A-Za-z0-9_]/g, "_");
  const used = new Set(assemblyState.components.map((item) => item.id));
  let index = 1;
  while (used.has(`${base}_${index}`)) index += 1;
  return `${base}_${index}`;
}

function newAssemblyComponent(template) {
  const definition = componentDefinition(template) || componentCatalog[0];
  if (!definition) return null;
  return {
    id: nextComponentId(definition.name),
    template: definition.name,
    geometry: Object.assign({}, definition.default_geometry || {}),
    mesh: { size_m: Number(definition.default_mesh_size_m || 0.02) },
    material: { name: "mild_steel" },
    transform: { translate_m: [0, 0, 0] }
  };
}

function availableRegions(componentId) {
  const component = assemblyState.components.find((item) => item.id === componentId);
  const definition = component ? componentDefinition(component.template) : null;
  if (!definition) return ["z_min"];
  const supported = new Set([
    "x_min", "x_max", "y_min", "y_max", "z_min", "z_max",
    "four_edges", "x_min_edge", "x_max_edge", "y_min_edge", "y_max_edge",
    "rim", "bottom_ring", "top_ring", "bottom_end", "top_end", "start_end", "finish_end"
  ]);
  const regions = [...(definition.named_surfaces || []), ...(definition.named_edges || [])]
    .filter((name) => supported.has(name));
  return regions.length ? regions : ["z_min"];
}

function availableBlastSurfaces(componentId) {
  const component = assemblyState.components.find((item) => item.id === componentId);
  const definition = component ? componentDefinition(component.template) : null;
  if (!definition || definition.element_family !== "shell") return [];
  const supported = new Set(["top_surface", "bottom_surface", "outer_surface", "inner_surface"]);
  return (definition.named_surfaces || []).filter((name) => supported.has(name));
}

function firstBlastTargetComponent() {
  const component = assemblyState.components.find((item) => availableBlastSurfaces(item.id).length);
  return component ? component.id : "";
}

function newPhysicsAction(type) {
  const first = assemblyState.components[0] ? assemblyState.components[0].id : "";
  const second = assemblyState.components[1] ? assemblyState.components[1].id : first;
  if (type === "fixed_region") return { type, component: second, region: availableRegions(second)[0] };
  if (type === "initial_velocity") return { type, component: first, vector_m_per_s: [0, 0, -10] };
  if (type === "automatic_nodes_to_surface") {
    return { type, slave: first, master: second, slave_region: availableRegions(first)[0], friction: 0.2 };
  }
  if (type === "automatic_surface_to_surface") return { type, slave: first, master: second, friction: 0.2 };
  if (type === "blast_enhanced") {
    const component = firstBlastTargetComponent();
    const surface = availableBlastSurfaces(component)[0] || "top_surface";
    return {
      id: "blast_1",
      type,
      charge_type: "tnt",
      equivalent_mass_kg: 0.1,
      position_m: [0, 0, 0.5],
      mode: "free_air_burst",
      targets: [`${component}.${surface}`],
      output_dt_s: 0.0001
    };
  }
  if (type === "gravity") return { type, direction: "z", acceleration_m_per_s2: -9.81 };
  if (type === "pressure") return { type, face: "z_max", pressure_pa: -100000 };
  return { type: "nodal_force", edge: "x_min", dof: "z", value_n: -1000 };
}

function initializeAssemblyState() {
  if (assemblyState.components.length || !componentCatalog.length) return;
  const plate = newAssemblyComponent("shell_plate");
  if (plate) assemblyState.components.push(plate);
  const impactor = newAssemblyComponent("solid_cylinder");
  if (impactor) {
    impactor.transform.translate_m = [0.25, 0.25, 0.15];
    assemblyState.components.push(impactor);
  }
  if (assemblyState.components.length >= 2) {
    assemblyState.actions.push(newPhysicsAction("fixed_region"));
    assemblyState.actions.push(newPhysicsAction("automatic_surface_to_surface"));
  }
}

function optionSelect(values, selected, onChange, labeler) {
  const select = document.createElement("select");
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = labeler ? labeler(value) : value;
    option.selected = value === selected;
    select.appendChild(option);
  }
  select.addEventListener("change", () => onChange(select.value));
  return select;
}

function editorField(labelText, control) {
  const label = document.createElement("label");
  label.className = "field compact-field";
  const title = document.createElement("span");
  title.textContent = labelText;
  label.appendChild(title);
  label.appendChild(control);
  return label;
}

function numberInput(value, onChange) {
  const input = document.createElement("input");
  input.type = "number";
  input.step = "any";
  input.value = String(value);
  input.addEventListener("change", () => {
    const number = Number(input.value);
    if (Number.isFinite(number)) onChange(number);
  });
  return input;
}

function textInput(value, onChange) {
  const input = document.createElement("input");
  input.type = "text";
  input.value = String(value || "");
  input.addEventListener("change", () => onChange(input.value.trim()));
  return input;
}

function cardHeader(titleText, onCopy, onDelete) {
  const header = document.createElement("div");
  header.className = "assembly-card-header";
  const title = document.createElement("strong");
  title.textContent = titleText;
  const buttons = document.createElement("div");
  buttons.className = "mini-actions";
  if (onCopy) {
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "icon-text-button";
    copy.textContent = "复制";
    copy.addEventListener("click", onCopy);
    buttons.appendChild(copy);
  }
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "danger-button";
  remove.textContent = "删除";
  remove.addEventListener("click", onDelete);
  buttons.appendChild(remove);
  header.appendChild(title);
  header.appendChild(buttons);
  return header;
}

function renderAssemblyComponents() {
  const box = byId("assemblyComponents");
  box.innerHTML = "";
  assemblyState.components.forEach((component, index) => {
    const card = document.createElement("div");
    card.className = "assembly-card";
    card.appendChild(cardHeader(
      `组件 ${index + 1}`,
      () => {
        const clone = JSON.parse(JSON.stringify(component));
        clone.id = nextComponentId(component.template);
        assemblyState.components.splice(index + 1, 0, clone);
        renderAssemblyEditors();
      },
      () => {
        assemblyState.components.splice(index, 1);
        renderAssemblyEditors();
      }
    ));
    const grid = document.createElement("div");
    grid.className = "editor-grid";
    grid.appendChild(editorField("组件 ID", textInput(component.id, (value) => {
      component.id = value;
      renderAssemblyActions();
    })));
    grid.appendChild(editorField("基础模型", optionSelect(
      componentCatalog.map((item) => item.name),
      component.template,
      (value) => {
        const definition = componentDefinition(value);
        component.template = value;
        component.geometry = Object.assign({}, definition.default_geometry || {});
        component.mesh.size_m = Number(definition.default_mesh_size_m || 0.02);
        renderAssemblyEditors();
      }
    )));
    grid.appendChild(editorField("材料", optionSelect(
      ["mild_steel", "mild_steel_mat24_demo"],
      component.material.name,
      (value) => { component.material = { name: value }; },
      (value) => value === "mild_steel_mat24_demo" ? "低碳钢 MAT_024（演示）" : "低碳钢（弹性）"
    )));
    grid.appendChild(editorField("网格尺寸 (m)", numberInput(component.mesh.size_m, (value) => {
      component.mesh.size_m = value;
    })));
    for (const [name, value] of Object.entries(component.geometry)) {
      grid.appendChild(editorField(`${name} (m)`, numberInput(value, (number) => {
        component.geometry[name] = number;
      })));
    }
    ["X", "Y", "Z"].forEach((axis, axisIndex) => {
      grid.appendChild(editorField(`位置 ${axis} (m)`, numberInput(
        component.transform.translate_m[axisIndex],
        (value) => { component.transform.translate_m[axisIndex] = value; }
      )));
    });
    card.appendChild(grid);
    box.appendChild(card);
  });
  if (!assemblyState.components.length) box.textContent = "尚未添加组件。";
}

function componentSelect(value, onChange) {
  return optionSelect(assemblyState.components.map((item) => item.id), value, onChange);
}

function addActionField(grid, label, control) {
  grid.appendChild(editorField(label, control));
}

function blastTargetsEditor(action) {
  const container = document.createElement("div");
  container.className = "blast-targets";
  const current = new Map((action.targets || []).map((value) => {
    const parts = String(value).split(".");
    return [parts[0], parts[1] || "top_surface"];
  }));
  const shellComponents = assemblyState.components.filter((item) => availableBlastSurfaces(item.id).length);
  for (const component of shellComponents) {
    const row = document.createElement("label");
    row.className = "blast-target-row";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = current.has(component.id);
    const name = document.createElement("span");
    name.textContent = component.id;
    const surfaces = availableBlastSurfaces(component.id);
    const select = optionSelect(surfaces, current.get(component.id) || surfaces[0], () => updateTargets());
    function updateTargets() {
      const retained = (action.targets || []).filter((value) => !String(value).startsWith(`${component.id}.`));
      action.targets = checkbox.checked ? [...retained, `${component.id}.${select.value}`] : retained;
    }
    checkbox.addEventListener("change", updateTargets);
    row.appendChild(checkbox);
    row.appendChild(name);
    row.appendChild(select);
    container.appendChild(row);
  }
  return container;
}

function renderAssemblyActions() {
  const box = byId("assemblyActions");
  box.innerHTML = "";
  assemblyState.actions.forEach((action, index) => {
    const card = document.createElement("div");
    card.className = "assembly-card action-card";
    card.appendChild(cardHeader(`动作 ${index + 1}`, null, () => {
      assemblyState.actions.splice(index, 1);
      renderAssemblyActions();
    }));
    const grid = document.createElement("div");
    grid.className = "editor-grid";
    addActionField(grid, "动作类型", optionSelect(
      physicsActionCatalog.map((item) => item.type),
      action.type,
      (type) => {
        assemblyState.actions[index] = newPhysicsAction(type);
        renderAssemblyActions();
      }
    ));
    if (action.type === "fixed_region") {
      addActionField(grid, "组件", componentSelect(action.component, (value) => {
        action.component = value;
        action.region = availableRegions(value)[0];
        renderAssemblyActions();
      }));
      addActionField(grid, "固定区域", optionSelect(availableRegions(action.component), action.region, (value) => { action.region = value; }));
    } else if (action.type === "initial_velocity") {
      addActionField(grid, "组件", componentSelect(action.component, (value) => { action.component = value; }));
      ["X", "Y", "Z"].forEach((axis, axisIndex) => addActionField(
        grid,
        `初速度 ${axis} (m/s)`,
        numberInput(action.vector_m_per_s[axisIndex], (value) => { action.vector_m_per_s[axisIndex] = value; })
      ));
    } else if (action.type === "automatic_surface_to_surface" || action.type === "automatic_nodes_to_surface") {
      addActionField(grid, "从组件", componentSelect(action.slave, (value) => {
        action.slave = value;
        if (action.slave_region) action.slave_region = availableRegions(value)[0];
        renderAssemblyActions();
      }));
      addActionField(grid, "到组件", componentSelect(action.master, (value) => { action.master = value; }));
      if (action.type === "automatic_nodes_to_surface") {
        addActionField(grid, "从组件区域", optionSelect(availableRegions(action.slave), action.slave_region, (value) => { action.slave_region = value; }));
      }
      addActionField(grid, "摩擦系数", numberInput(action.friction || 0, (value) => { action.friction = value; }));
    } else if (action.type === "blast_enhanced") {
      addActionField(grid, "目标壳组件与表面", blastTargetsEditor(action));
      addActionField(grid, "TNT 当量 (kg)", numberInput(action.equivalent_mass_kg, (value) => { action.equivalent_mass_kg = value; }));
      ["X", "Y", "Z"].forEach((axis, axisIndex) => addActionField(
        grid,
        `爆心 ${axis} (m)`,
        numberInput(action.position_m[axisIndex], (value) => { action.position_m[axisIndex] = value; })
      ));
      addActionField(grid, "爆压输出间隔 (s)", numberInput(action.output_dt_s, (value) => { action.output_dt_s = value; }));
    } else if (action.type === "gravity") {
      addActionField(grid, "方向", optionSelect(["x", "y", "z"], action.direction, (value) => { action.direction = value; }));
      addActionField(grid, "加速度 (m/s²)", numberInput(action.acceleration_m_per_s2, (value) => { action.acceleration_m_per_s2 = value; }));
    } else if (action.type === "pressure") {
      addActionField(grid, "全局面", optionSelect(["x_min", "x_max", "y_min", "y_max", "z_min", "z_max"], action.face, (value) => { action.face = value; }));
      addActionField(grid, "压力 (Pa)", numberInput(action.pressure_pa, (value) => { action.pressure_pa = value; }));
    } else if (action.type === "nodal_force") {
      addActionField(grid, "全局边", optionSelect(["x_min", "x_max", "y_min", "y_max", "z_min", "z_max"], action.edge, (value) => { action.edge = value; }));
      addActionField(grid, "方向", optionSelect(["x", "y", "z"], action.dof, (value) => { action.dof = value; }));
      addActionField(grid, "节点力 (N)", numberInput(action.value_n, (value) => { action.value_n = value; }));
    }
    card.appendChild(grid);
    box.appendChild(card);
  });
  if (!assemblyState.actions.length) box.textContent = "尚未添加物理动作。";
}

function renderAssemblyEditors() {
  renderAssemblyComponents();
  renderAssemblyActions();
  updateContextStatus();
}

function assemblyPayload(extra) {
  const projectName = currentProjectName();
  lastProjectName = projectName;
  const payload = {
      project_name: projectName,
      components: JSON.parse(JSON.stringify(assemblyState.components)),
      actions: JSON.parse(JSON.stringify(assemblyState.actions))
  };
  if (assemblyState.analysisControl) {
    payload.analysis_control = JSON.parse(JSON.stringify(assemblyState.analysisControl));
  }
  if (assemblyState.database) payload.database = JSON.parse(JSON.stringify(assemblyState.database));
  return Object.assign(payload, extra || {});
}

function setModelMode() {
  const controlled = byId("modelMode").value === "controlled";
  const assembly = isAssemblyMode();
  const aleBlast = isAleBlastMode();
  const tunnelBlast = isTunnelBlastMode();
  const phase15 = isPhase15Mode();
  byId("controlledScenePanel").classList.toggle("hidden", !controlled);
  byId("controlledSceneFields").classList.toggle("hidden", !controlled || aleBlast);
  byId("assemblyPanel").classList.toggle("hidden", !assembly);
  byId("aleBlastPanel").classList.toggle("hidden", !aleBlast);
  byId("tunnelBlastPanel").classList.toggle("hidden", !tunnelBlast);
  byId("phase15Panel").classList.toggle("hidden", !phase15);
  byId("resolve").textContent = phase15 ? "检查 Phase 15 参数" : assembly ? "检查装配" : aleBlast || tunnelBlast ? "检查 ALE 模型" : "解析参数";
  if (assembly && (!currentProjectName() || currentProjectName().startsWith("web_"))) {
    byId("projectName").value = "web_assembly_model";
  }
  if (assembly) renderAssemblyEditors();
  if (aleBlast && (!currentProjectName() || currentProjectName().startsWith("web_"))) {
    byId("projectName").value = "web_phase14_mmale_blast";
  }
  if (tunnelBlast && (!currentProjectName() || currentProjectName().startsWith("web_"))) {
    byId("projectName").value = "web_phase14_open_tunnel_blast";
  }
  if (phase15 && (!currentProjectName() || currentProjectName().startsWith("web_"))) {
    byId("projectName").value = "web_phase15_a1_kc_blast";
  }
  if (tunnelBlast) {
    updateTunnelMeshEstimate();
  } else {
    byId("resolve").disabled = false;
    byId("generate").disabled = false;
    byId("preview").disabled = false;
  }
  refreshActionAvailability();
  if (phase15) updatePhase15CouplingControls();
  updateContextStatus();
}

function currentSceneLabel() {
  if (isAssemblyMode()) return "自由装配";
  if (isAleBlastMode()) return "MM-ALE 冲击波爆炸";
  if (isTunnelBlastMode()) return "参数化通道爆炸";
  if (isPhase15Mode()) return "K&C 柱形埋置装药";
  const scene = selectedScene();
  return scene ? (sceneDisplayNames[scene.id] || scene.title) : "未选择";
}

function updateContextStatus() {
  const box = byId("contextStatus");
  if (!box) return;
  const sceneName = currentSceneLabel();
  const projectName = currentProjectName();
  const previewProject = viewer.projectName || "";
  const isStalePreview = Boolean(projectName && previewProject && projectName !== previewProject);
  box.classList.toggle("warning", isStalePreview);
  box.innerHTML = "";
  const chips = [
    ["场景", sceneName],
    ["项目", projectName || "未填写"],
    ["视窗", previewProject || "尚未加载模型"]
  ];
  for (const [label, value] of chips) {
    const chip = document.createElement("span");
    chip.className = "context-chip";
    const chipLabel = document.createElement("b");
    chipLabel.textContent = label;
    const chipValue = document.createElement("span");
    chipValue.textContent = value;
    chip.appendChild(chipLabel);
    chip.appendChild(chipValue);
    box.appendChild(chip);
  }
  const status = document.createElement("span");
  status.className = `context-state ${isStalePreview ? "warning" : "ok"}`;
  status.textContent = isStalePreview ? "预览已过期，请重新生成或刷新" : (previewProject ? "预览与当前项目一致" : "等待加载模型");
  box.appendChild(status);
}

function setViewportMode(mode) {
  viewer.mode = mode === "results" ? "results" : "model";
  for (const button of document.querySelectorAll("[data-viewport-mode]")) {
    const active = button.dataset.viewportMode === viewer.mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  }
  byId("modelViewport").classList.toggle("result-mode", viewer.mode === "results");
  byId("resultControls").classList.toggle("hidden", viewer.mode !== "results");
  if (viewer.mode === "results") {
    loadViewportResultStatus();
  } else {
    byId("resultEmptyState").classList.add("hidden");
  }
  drawViewer();
}

function resultOutputIsAvailable(record, name) {
  return Boolean(
    record
    && record.outputs
    && record.outputs[name]
    && record.outputs[name].ok
  );
}

function renderViewportResultStatus(record, errorMessage = "") {
  viewer.resultRecord = record || null;
  const box = byId("resultEmptyState");
  const title = byId("resultEmptyTitle");
  const message = byId("resultEmptyMessage");
  const variable = byId("resultVariable");
  const controlsEnabled = false;
  variable.disabled = !controlsEnabled;
  byId("resultPlay").disabled = !controlsEnabled;
  byId("resultTimeline").disabled = !controlsEnabled;

  if (errorMessage) {
    title.textContent = "无法读取求解状态";
    message.textContent = errorMessage;
  } else if (!record || record.status === "not_started") {
    title.textContent = "当前项目尚无求解结果";
    message.textContent = "这里不会自动启动求解。请在右侧求解面板完成并确认求解后，再刷新状态。";
  } else if (resultOutputIsAvailable(record, "d3plot")) {
    const verified = record.postprocessing && record.postprocessing.status === "verified";
    title.textContent = verified ? "已检测到真实求解结果与后处理记录" : "已检测到真实 d3plot";
    message.textContent = "浏览器尚未解析 d3plot 结果帧，因此不会显示模拟云图。请使用 LS-PrePost 查看真实压力、应力和位移结果。";
  } else {
    title.textContent = "求解记录中没有可用 d3plot";
    message.textContent = `最近状态：${record.status || "未知"}。请在右侧查看求解摘要和错误信息。`;
  }
  box.classList.toggle("hidden", viewer.mode !== "results");
}

async function loadViewportResultStatus() {
  if (viewer.mode !== "results") return null;
  const projectName = currentProjectName() || viewer.projectName || lastProjectName;
  if (!projectName) {
    renderViewportResultStatus(null);
    return null;
  }
  byId("resultEmptyTitle").textContent = "正在读取求解状态";
  byId("resultEmptyMessage").textContent = `项目：${projectName}`;
  byId("resultEmptyState").classList.remove("hidden");
  try {
    const record = await api(`/api/solve/status?project_name=${encodeURIComponent(projectName)}`);
    renderViewportResultStatus(record);
    return record;
  } catch (error) {
    renderViewportResultStatus(null, error && error.message ? error.message : String(error));
    return null;
  }
}

function buildGenerationConfirmationSummary() {
  if (isAssemblyMode()) {
    const lines = [
      "请确认即将生成自由装配模型：",
      `项目名称：${currentProjectName() || "未填写"}`,
      `组件：${assemblyState.components.length} 个`,
      `物理动作：${assemblyState.actions.length} 个`
    ];
    if (assemblyState.caseId) lines.push(`爆炸预设：${assemblyState.caseId}`);
    for (const component of assemblyState.components) {
      lines.push(`- ${component.id}: ${component.template}, ${component.material.name}`);
    }
    return lines.join("\n");
  }
  if (isAleBlastMode()) {
    const payload = aleBlastPayload();
    return [
      "请确认即将生成 Phase 14 MM-ALE 求解草案：",
      `项目名称：${payload.project_name || "未填写"}`,
      `空气域：${aleBlastNumber("aleDomainX")} x ${aleBlastNumber("aleDomainY")} x ${aleBlastNumber("aleDomainZ")} m`,
      `炸药：Composition B，${payload.explosive_mass_kg} kg，爆心高度 ${payload.explosive_center_m[2]} m`,
      `目标板：${payload.plate_length_m} x ${payload.plate_width_m} x ${payload.plate_thickness_m} m`,
      `网格：${payload.mesh_size_m} m；终止时间：${payload.end_time_s} s`,
      "受控场景不等于工程验证；钢板周边完全固定，网格收敛性尚未证明。",
      "本操作只生成与校验 K 文件，不启动 LS-DYNA。"
    ].join("\n");
  }
  if (isTunnelBlastMode()) {
    const payload = tunnelBlastPayload();
    const estimate = estimateTunnelAleCells();
    const standoff = Math.hypot(
      payload.plate_center_m[0] - payload.explosive_center_m[0],
      payload.plate_center_m[1] - payload.explosive_center_m[1],
      payload.plate_center_m[2] - payload.explosive_center_m[2]
    );
    return [
      "请确认即将生成参数化通道爆炸模型：",
      `项目名称：${payload.project_name || "未填写"}`,
      `通道内部：${payload.tunnel_length_m} x ${payload.tunnel_width_m} x ${payload.tunnel_height_m} m；墙厚 ${payload.tunnel_wall_thickness_m} m`,
      `炸药：Composition B，${payload.explosive_mass_kg} kg；爆心 [${payload.explosive_center_m.join(", ")}] m`,
      `目标板：${payload.plate_length_m} x ${payload.plate_width_m} x ${payload.plate_thickness_m} m；中心 [${payload.plate_center_m.join(", ")}] m`,
      `钢板材料：${payload.plate_material_name}；中心爆距 ${standoff.toFixed(3)} m`,
      `统一空气网格：${payload.air_mesh_size_m} m（${tunnelMeshLabels[String(payload.air_mesh_size_m)]}）；预计总单元 ${estimate.estimatedTotalElements.toLocaleString()}`,
      `终止时间：${payload.end_time_s} s`,
      "本操作只生成与校验 K 文件，不启动 LS-DYNA。"
    ].join("\n");
  }
  if (isPhase15Mode()) {
    const payload = phase15Payload();
    const couplingSummary = payload.coupling_mode === "immersed_clis"
      ? `侵入式 CLIS：${payload.fsi_overlap_layers} 层，共 ${(payload.mesh_size_m * payload.fsi_overlap_layers * 1000).toFixed(1)} mm 数值重叠`
      : `共形空气间隙：孔半径 ${payload.borehole_radius_m} m，底部间隙 ${payload.bottom_air_gap_m} m，ALE/混凝土零体积重叠`;
    return [
      phase15PreparationNotice,
      `项目名称：${payload.project_name || "未填写"}`,
      `TNT：${payload.tnt_mass_kg} kg，直径 ${payload.tnt_diameter_m} m，长度 ${payload.tnt_length_m} m`,
      `密度：${payload.tnt_density_kg_per_m3} kg/m3；一致性策略：${payload.consistency_mode}`,
      `轴对称靶体：半径 ${payload.target_radius_m} m，高度 ${payload.target_height_m} m，网格 ${payload.mesh_size_m} m`,
      couplingSummary,
      `K&C 抗压强度：${payload.concrete_fpc_pa / 1.0e6} MPa；钢箍厚度 ${payload.steel_thickness_m} m；侵蚀 ${payload.erosion_mode}`,
      `终止时间：${payload.end_time_s * 1000} ms；早期/后期云图间隔 ${payload.early_output_dt_s * 1.0e6}/${payload.late_output_dt_s * 1.0e6} μs`,
      "生成二维轴对称 K 文件；不会自动启动 LS-Run 或 LS-DYNA。K&C 自动参数未按特定 CF120 批次标定。"
    ].join("\n");
  }
  const scene = selectedScene();
  const parameters = collectParameters();
  const lines = [
    "请确认即将生成模型：",
    `场景：${scene ? scene.title : "未选择"}`,
    `项目名称：${currentProjectName() || "未填写"}`,
    `需求描述：${byId("prompt").value.trim() || "未填写"}`,
    "参数："
  ];
  for (const [key, value] of Object.entries(parameters)) {
    lines.push(`- ${key}: ${value}`);
  }
  return lines.join("\n");
}

function confirmGeneration() {
  return window.confirm(buildGenerationConfirmationSummary());
}

function updatePromptForScene(scene) {
  if (!promptEdited || !byId("prompt").value.trim()) {
    byId("prompt").value = defaultPrompt(scene);
    promptEdited = false;
  }
}

function updateProjectNameForScene(scene) {
  if (!scene) return;
  const input = byId("projectName");
  const current = input.value.trim();
  const currentStartsWithControlledPrefix = sceneCatalog.some(
    (item) => current === `${controlledScenePrefix}${item.id}` || current.startsWith(`${controlledScenePrefix}${item.id}_`)
  );
  const currentIsAleBlastDefault = current === "web_phase14_mmale_blast";
  if (!current || current === "web_scene_demo" || currentStartsWithControlledPrefix || currentIsAleBlastDefault) {
    input.value = `web_${scene.id}`;
  }
  updateContextStatus();
}

function fieldGroup(fieldName) {
  if (fieldName === "material_name") return { id: "material", label: "材料", hint: "1 项" };
  if (/velocity|force|pressure/.test(fieldName)) {
    return { id: "physics", label: "载荷与运动", hint: "物理输入" };
  }
  return { id: "geometry", label: "几何与位置", hint: "尺寸参数" };
}

function createParameterGroup(group, open) {
  const details = document.createElement("details");
  details.className = "parameter-group";
  details.open = open;
  details.dataset.fieldGroup = group.id;
  const summary = document.createElement("summary");
  const title = document.createElement("span");
  title.textContent = group.label;
  const hint = document.createElement("small");
  hint.textContent = group.hint;
  summary.appendChild(title);
  summary.appendChild(hint);
  const body = document.createElement("div");
  body.className = "parameter-group-body fields";
  details.appendChild(summary);
  details.appendChild(body);
  return { details, body };
}

function renderFields() {
  const fields = byId("fields");
  fields.innerHTML = "";
  if (isAleBlastMode()) {
    byId("sceneSummary").textContent = "";
    updateContextStatus();
    return;
  }
  const scene = selectedScene();
  if (!scene) {
    byId("sceneSummary").textContent = "服务端没有返回可用场景模板。";
    updateContextStatus();
    return;
  }

  byId("sceneSummary").textContent = sceneDisplaySummaries[scene.id] || scene.summary || "";
  updatePromptForScene(scene);
  updateProjectNameForScene(scene);

  const groups = new Map();
  for (const field of scene.fields || []) {
    const group = fieldGroup(field.name);
    if (!groups.has(group.id)) {
      const nodes = createParameterGroup(group, groups.size === 0);
      groups.set(group.id, nodes);
      fields.appendChild(nodes.details);
    }
    const label = document.createElement("label");
    label.className = "field";

    const title = document.createElement("span");
    const displayName = fieldDisplayNames[field.name] || field.label;
    title.textContent = `${displayName}${field.unit ? ` (${field.unit})` : ""}`;
    label.appendChild(title);

    let input;
    if (field.kind === "select") {
      input = document.createElement("select");
      for (const option of field.options || []) {
        const item = document.createElement("option");
        item.value = option;
        item.textContent = option;
        input.appendChild(item);
      }
    } else if (field.kind === "boolean") {
      input = document.createElement("select");
      for (const option of ["true", "false"]) {
        const item = document.createElement("option");
        item.value = option;
        item.textContent = option === "true" ? "是" : "否";
        input.appendChild(item);
      }
    } else {
      input = document.createElement("input");
      input.type = field.kind === "number" ? "number" : "text";
      if (field.kind === "number") input.step = "any";
    }

    input.value = String(field.default);
    input.dataset.param = field.name;
    input.dataset.kind = field.kind;
    label.appendChild(input);
    groups.get(group.id).body.appendChild(label);
  }
  updateContextStatus();
}

function collectParameters() {
  const parameters = {};
  for (const input of byId("fields").querySelectorAll("[data-param]")) {
    const key = input.dataset.param;
    if (!key) continue;
    if (input.dataset.kind === "number") {
      const value = Number(input.value);
      if (Number.isFinite(value)) parameters[key] = value;
    } else if (input.dataset.kind === "boolean") {
      parameters[key] = input.value === "true";
    } else {
      parameters[key] = input.value;
    }
  }
  return parameters;
}

function scenePayload(extra) {
  const scene = selectedScene();
  const projectName = byId("projectName").value.trim();
  lastProjectName = projectName;
  return Object.assign(
    {
      scene_id: scene ? scene.id : "",
      project_name: projectName,
      prompt: byId("prompt").value.trim(),
      parameters: collectParameters(),
      allow_defaults: true
    },
    extra || {}
  );
}

function rememberGeneratedProjectName(result) {
  const generatedProjectName =
    (result.write_result && result.write_result.project) || result.project || result.project_name || "";
  if (typeof generatedProjectName === "string" && generatedProjectName.trim()) {
    lastProjectName = generatedProjectName;
    byId("projectName").value = generatedProjectName;
  }
  refreshActionAvailability();
  updateContextStatus();
}

function normalizePath(value) {
  return String(value || "").replace(/\\/g, "/").replace(/\/+/g, "/").replace(/\/$/, "");
}

function relativeArtifactPath(projectDir, outputPath) {
  const root = normalizePath(projectDir);
  const output = normalizePath(outputPath);
  if (!root || !output) {
    throw new Error("预览结果缺少 project_dir 或 output_path。");
  }

  const rootWithSlash = `${root}/`;
  if (output.toLowerCase().indexOf(rootWithSlash.toLowerCase()) !== 0) {
    throw new Error("预览输出路径不在项目目录内。");
  }

  const relative = output.slice(rootWithSlash.length);
  const parts = relative.split("/");
  if (!relative || relative.startsWith("/") || parts.some((part) => part === ".." || part.includes(":"))) {
    throw new Error("预览输出路径不是安全的项目相对路径。");
  }
  return relative;
}

function renderPreviewArtifact(result) {
  const relativePath = relativeArtifactPath(result.project_dir, result.output_path);
  const projectName = result.project_name || lastProjectName || byId("projectName").value.trim();
  const url = `/api/artifact?project_name=${encodeURIComponent(projectName)}&relative_path=${encodeURIComponent(relativePath)}`;
  const img = document.createElement("img");
  img.alt = "LS-PrePost 预览";
  img.src = url;

  const box = byId("previewBox");
  box.innerHTML = "";
  box.classList.remove("hidden");
  byId("viewerHint").classList.add("hidden");
  box.appendChild(img);
}

async function loadInteractiveMesh(projectName) {
  if (!projectName) return null;
  previewMeshRequestSequence += 1;
  const requestSequence = previewMeshRequestSequence;
  if (previewMeshAbortController) previewMeshAbortController.abort();
  previewMeshAbortController = new AbortController();
  try {
    const mesh = await api(
      `/api/project/preview-mesh?project_name=${encodeURIComponent(projectName)}`,
      { signal: previewMeshAbortController.signal }
    );
    if (requestSequence !== previewMeshRequestSequence) return null;
    if (mesh && !mesh.project_name) {
      mesh.project_name = projectName;
    }
    renderInteractiveMesh(mesh);
    return mesh;
  } catch (error) {
    if (error && error.name === "AbortError") return null;
    throw error;
  } finally {
    if (requestSequence === previewMeshRequestSequence) {
      previewMeshAbortController = null;
    }
  }
}

function renderInteractiveMesh(mesh) {
  const projectChanged = viewer.projectName !== (mesh && mesh.project_name ? mesh.project_name : "");
  viewer.mesh = mesh;
  viewer.projectName = mesh && mesh.project_name ? mesh.project_name : "";
  viewer.hiddenParts = new Set((mesh && mesh.default_hidden_part_ids || []).map(String));
  if (projectChanged) {
    viewer.riskByPartId = new Map();
    viewer.selectedImpactPartIds = new Set();
    viewer.selectedPartId = "";
    viewer.resultRecord = null;
  }
  viewer.zoom = 1;
  viewer.panX = 0;
  viewer.panY = 0;
  byId("previewBox").classList.add("hidden");
  byId("viewerHint").classList.add("hidden");
  setViewportMode("model");
  renderSelectionPanel();
  renderPartLegend(mesh);
  updateContextStatus();
  drawViewer();
}

function renderPartLegend(mesh) {
  const box = byId("partLegend");
  if (!box) return;
  const parts = mesh && Array.isArray(mesh.parts) ? mesh.parts : [];
  box.innerHTML = "";
  if (!parts.length) {
    box.classList.add("hidden");
    return;
  }

  box.classList.toggle("hidden", !viewer.showLegend);
  const title = document.createElement("div");
  title.className = "part-legend-title";
  title.textContent = `部件 ${parts.length}`;
  box.appendChild(title);

  for (const part of parts) {
    const partId = String(part.part_id);
    const label = document.createElement("div");
    label.className = "part-legend-item";
    label.setAttribute("role", "button");
    label.tabIndex = 0;
    label.classList.toggle("selected", viewer.selectedPartId === partId);
    label.title = `选择 ${part.name || `Part ${partId}`}`;

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = !viewer.hiddenParts.has(partId);
    checkbox.addEventListener("click", (event) => event.stopPropagation());
    checkbox.addEventListener("change", () => togglePartVisibility(partId, checkbox.checked));

    const swatch = document.createElement("span");
    swatch.className = "part-swatch";
    const riskLevel = viewer.riskByPartId.get(partId);
    swatch.style.background = riskColors[riskLevel] || part.color || "#d94157";

    const name = document.createElement("span");
    name.className = "part-name";
    name.textContent = part.name || `Part ${partId}`;

    label.appendChild(checkbox);
    label.appendChild(swatch);
    label.appendChild(name);
    label.addEventListener("click", () => selectViewerPart(partId));
    label.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      selectViewerPart(partId);
    });
    box.appendChild(label);
  }
}

function togglePartVisibility(partId, visible) {
  const id = String(partId);
  if (visible) {
    viewer.hiddenParts.delete(id);
  } else {
    viewer.hiddenParts.add(id);
  }
  if (!visible && viewer.selectedPartId === id) viewer.selectedPartId = "";
  renderSelectionPanel();
  renderPartLegend(viewer.mesh);
  drawViewer();
  updateContextStatus();
}

function findViewerPart(partId) {
  const id = String(partId || "");
  return viewer.mesh && Array.isArray(viewer.mesh.parts)
    ? viewer.mesh.parts.find((part) => String(part.part_id) === id)
    : null;
}

function selectViewerPart(partId) {
  const part = findViewerPart(partId);
  viewer.selectedPartId = part ? String(part.part_id) : "";
  renderSelectionPanel();
  renderPartLegend(viewer.mesh);
  drawViewer();
}

function renderSelectionPanel() {
  const panel = byId("selectionPanel");
  if (!panel) return;
  const part = findViewerPart(viewer.selectedPartId);
  panel.classList.toggle("hidden", !part);
  if (!part) return;
  const partId = String(part.part_id);
  byId("selectedPartName").textContent = part.name || `Part ${partId}`;
  const details = [
    `Part ID ${partId}`,
    part.element_family || "未知单元",
    part.semantic_category || part.semantic_group_id || ""
  ].filter(Boolean);
  byId("selectedPartMeta").textContent = details.join(" · ");
}

function hideSelectedPart() {
  if (!viewer.selectedPartId) return;
  viewer.hiddenParts.add(viewer.selectedPartId);
  viewer.selectedPartId = "";
  renderSelectionPanel();
  renderPartLegend(viewer.mesh);
  drawViewer();
}

function isolateSelectedPart() {
  if (!viewer.selectedPartId || !viewer.mesh) return;
  viewer.hiddenParts = new Set(
    (viewer.mesh.parts || [])
      .map((part) => String(part.part_id))
      .filter((partId) => partId !== viewer.selectedPartId)
  );
  renderPartLegend(viewer.mesh);
  drawViewer();
}

function showAllViewerParts() {
  viewer.hiddenParts = new Set();
  renderPartLegend(viewer.mesh);
  drawViewer();
}

function setViewerDisplayMode(mode) {
  viewer.displayMode = ["solid_edges", "solid", "wireframe"].includes(mode) ? mode : "solid_edges";
  drawViewer();
}

function toggleViewerOption(option, buttonId) {
  viewer[option] = !viewer[option];
  const button = byId(buttonId);
  if (button) button.classList.toggle("active", viewer[option]);
  if (option === "showLegend") renderPartLegend(viewer.mesh);
  drawViewer();
}

async function toggleViewportFullscreen() {
  const panel = byId("centerViewport");
  if (!document.fullscreenElement) {
    if (panel.requestFullscreen) await panel.requestFullscreen();
  } else if (document.exitFullscreen) {
    await document.exitFullscreen();
  }
}

function updateFullscreenButton() {
  const button = byId("fullscreenView");
  if (!button) return;
  button.textContent = document.fullscreenElement ? "退出全屏" : "全屏";
  window.setTimeout(drawViewer, 0);
}

function canvasContext() {
  const canvas = byId("modelCanvas");
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.floor(rect.width * ratio));
  const height = Math.max(1, Math.floor(rect.height * ratio));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { canvas, ctx, width: rect.width, height: rect.height };
}

function drawViewer() {
  if (webglModelViewer) {
    webglModelViewer.sync({
      mesh: viewer.mesh,
      hiddenParts: viewer.hiddenParts,
      riskByPartId: viewer.riskByPartId,
      selectedImpactPartIds: viewer.selectedImpactPartIds,
      selectedPartId: viewer.selectedPartId,
      displayMode: viewer.displayMode,
      showGrid: viewer.showGrid,
      showBlastSources: viewer.showBlastSources,
      riskColors
    });
    return;
  }
  const { ctx, width, height } = canvasContext();
  ctx.clearRect(0, 0, width, height);
  if (viewer.showGrid) drawWorldGrid(ctx, width, height);
  if (!viewer.mesh) {
    drawRotatingAxes(ctx, width, height);
    viewer.projectedFaces = [];
    return;
  }
  const projected = collectProjectedFaces(width, height);
  projected.sort((a, b) => a.depth - b.depth);
  viewer.projectedFaces = projected;
  for (const item of projected) {
    drawFace(ctx, item);
  }
  if (viewer.showBlastSources) drawBlastSources(ctx, width, height);
  drawRotatingAxes(ctx, width, height);
}

function drawBlastSources(ctx, width, height) {
  const sources = viewer.mesh && Array.isArray(viewer.mesh.blast_sources) ? viewer.mesh.blast_sources : [];
  if (!sources.length) return;
  const transform = viewTransform(width, height);
  for (const source of sources) {
    const point = projectWorldPoint(source.position_m || [0, 0, 0], transform);
    ctx.save();
    ctx.strokeStyle = "#ffd54a";
    ctx.fillStyle = "#ffd54a";
    ctx.lineWidth = 2;
    const radius = Math.max(8, Number(source.radius_m || 0) * transform.scale);
    ctx.beginPath();
    ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(point.x - 12, point.y);
    ctx.lineTo(point.x + 12, point.y);
    ctx.moveTo(point.x, point.y - 12);
    ctx.lineTo(point.x, point.y + 12);
    ctx.stroke();
    ctx.font = "12px Microsoft YaHei, sans-serif";
    const label = source.label || `爆心 ${source.equivalent_mass_kg || "?"} kg TNT`;
    ctx.fillText(label, point.x + radius + 6, point.y - 10);
    ctx.restore();
  }
}

function viewTransform(width, height) {
  const bounds = viewer.mesh && viewer.mesh.bounds
    ? viewer.mesh.bounds
    : { min: [-0.5, -0.5, 0], max: [0.5, 0.5, 0.05], center: [0, 0, 0] };
  const span = Math.max(
    Math.abs(bounds.max[0] - bounds.min[0]),
    Math.abs(bounds.max[1] - bounds.min[1]),
    Math.abs(bounds.max[2] - bounds.min[2]),
    1e-9
  );
  const scale = (0.72 * Math.min(width, height) * viewer.zoom) / span;
  const center = bounds.center || [
    (bounds.min[0] + bounds.max[0]) * 0.5,
    (bounds.min[1] + bounds.max[1]) * 0.5,
    (bounds.min[2] + bounds.max[2]) * 0.5
  ];
  return { bounds, span, scale, center, width, height };
}

function collectProjectedFaces(width, height) {
  const transform = viewTransform(width, height);
  const items = [];
  for (const part of viewer.mesh.parts || []) {
    const partId = String(part.part_id);
    if (viewer.hiddenParts.has(partId)) continue;
    const riskLevel = viewer.riskByPartId.get(partId);
    const fill = riskColors[riskLevel] || part.color || "#d94157";
    const selected = viewer.selectedPartId === partId || viewer.selectedImpactPartIds.has(partId);
    const projectedNodes = (part.nodes || []).map((node) => projectWorldPoint(node, transform));
    for (const face of part.faces || []) {
      const points = face.map((index) => projectedNodes[index]).filter(Boolean);
      if (points.length < 3) continue;
      const depth = points.reduce((sum, point) => sum + point.depth, 0) / points.length;
      items.push({ points, depth, fill, selected, partId, part });
    }
  }
  return items;
}

function pointInPolygon(x, y, points) {
  let inside = false;
  for (let index = 0, previous = points.length - 1; index < points.length; previous = index, index += 1) {
    const currentPoint = points[index];
    const previousPoint = points[previous];
    const crosses = ((currentPoint.y > y) !== (previousPoint.y > y))
      && (x < ((previousPoint.x - currentPoint.x) * (y - currentPoint.y))
        / ((previousPoint.y - currentPoint.y) || Number.EPSILON) + currentPoint.x);
    if (crosses) inside = !inside;
  }
  return inside;
}

function pickPartAt(clientX, clientY) {
  const canvas = byId("modelCanvas");
  const rect = canvas.getBoundingClientRect();
  const x = clientX - rect.left;
  const y = clientY - rect.top;
  for (let index = viewer.projectedFaces.length - 1; index >= 0; index -= 1) {
    const face = viewer.projectedFaces[index];
    if (pointInPolygon(x, y, face.points)) {
      selectViewerPart(face.partId);
      return face.part;
    }
  }
  selectViewerPart("");
  return null;
}

function rotateViewVector(vector) {
  const x = Number(vector[0]);
  const y = Number(vector[1]);
  const z = Number(vector[2]);
  const cy = Math.cos(viewer.yaw);
  const sy = Math.sin(viewer.yaw);
  const cp = Math.cos(viewer.pitch);
  const sp = Math.sin(viewer.pitch);
  const x1 = x * cy - y * sy;
  const y1 = x * sy + y * cy;
  const z1 = z;
  const y2 = y1 * cp - z1 * sp;
  const z2 = y1 * sp + z1 * cp;
  return { x: x1, y: y2, z: z2 };
}

function projectWorldPoint(node, transform) {
  const local = [
    Number(node[0]) - transform.center[0],
    Number(node[1]) - transform.center[1],
    Number(node[2]) - transform.center[2]
  ];
  const rotated = rotateViewVector(local);
  return {
    x: transform.width * 0.5 + viewer.panX + rotated.x * transform.scale,
    y: transform.height * 0.5 + viewer.panY - rotated.z * transform.scale,
    depth: rotated.y
  };
}

function projectNode(node, center, scale, width, height) {
  return projectWorldPoint(node, { center, scale, width, height });
}

function drawFace(ctx, item) {
  ctx.beginPath();
  ctx.moveTo(item.points[0].x, item.points[0].y);
  for (const point of item.points.slice(1)) {
    ctx.lineTo(point.x, point.y);
  }
  ctx.closePath();
  if (viewer.displayMode !== "wireframe") {
    ctx.fillStyle = item.fill;
    ctx.globalAlpha = viewer.mode === "results" ? 0.5 : 0.9;
    ctx.fill();
    ctx.globalAlpha = 1;
  }
  if (viewer.displayMode !== "solid" || item.selected) {
    ctx.strokeStyle = item.selected ? "#ffffff" : "rgba(10, 18, 22, 0.72)";
    ctx.lineWidth = item.selected ? 2.5 : 1;
    ctx.stroke();
  }
}

function niceGridStep(span) {
  const raw = Math.max(span / 10, 1e-6);
  const exponent = Math.floor(Math.log10(raw));
  const base = raw / 10 ** exponent;
  const rounded = base <= 1 ? 1 : base <= 2 ? 2 : base <= 5 ? 5 : 10;
  return rounded * 10 ** exponent;
}

function drawWorldGrid(ctx, width, height) {
  const transform = viewTransform(width, height);
  const center = transform.center;
  const floorZ = Math.min(0, transform.bounds.min[2]);
  const step = niceGridStep(transform.span);
  const count = 18;
  const startX = center[0] - count * step;
  const endX = center[0] + count * step;
  const startY = center[1] - count * step;
  const endY = center[1] + count * step;
  ctx.save();
  ctx.lineWidth = 1;
  for (let index = -count; index <= count; index += 1) {
    const y = center[1] + index * step;
    const a = projectWorldPoint([startX, y, floorZ], transform);
    const b = projectWorldPoint([endX, y, floorZ], transform);
    ctx.strokeStyle = index === 0 ? "rgba(91, 190, 156, 0.35)" : "rgba(255,255,255,0.08)";
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }
  for (let index = -count; index <= count; index += 1) {
    const x = center[0] + index * step;
    const a = projectWorldPoint([x, startY, floorZ], transform);
    const b = projectWorldPoint([x, endY, floorZ], transform);
    ctx.strokeStyle = index === 0 ? "rgba(91, 190, 156, 0.35)" : "rgba(255,255,255,0.08)";
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }
  ctx.restore();
}

function drawRotatingAxes(ctx, width, height) {
  const origin = { x: 36, y: height - 38 };
  const axes = [
    { label: "X", color: "#ff6f61", vector: [1, 0, 0] },
    { label: "Y", color: "#67d77f", vector: [0, 1, 0] },
    { label: "Z", color: "#74a7ff", vector: [0, 0, 1] }
  ];
  ctx.save();
  ctx.font = "700 13px Microsoft YaHei, Arial";
  ctx.lineCap = "round";
  for (const axis of axes) {
    const rotated = rotateViewVector(axis.vector);
    const dx = rotated.x * 44;
    const dy = -rotated.z * 44;
    ctx.strokeStyle = axis.color;
    ctx.fillStyle = axis.color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(origin.x, origin.y);
    ctx.lineTo(origin.x + dx, origin.y + dy);
    ctx.stroke();
    ctx.fillText(axis.label, origin.x + dx + 5, origin.y + dy + 4);
  }
  ctx.restore();
}

function setView(yaw, pitch) {
  viewer.yaw = yaw;
  viewer.pitch = pitch;
  viewer.panX = 0;
  viewer.panY = 0;
  if (webglModelViewer) {
    const preset = yaw === 0 && pitch === 0
      ? "top"
      : yaw === 0 && Math.abs(pitch - Math.PI / 2) < 1e-9
        ? "front"
        : "iso";
    webglModelViewer.fitView(preset);
    return;
  }
  drawViewer();
}

function fitView() {
  viewer.zoom = 1;
  viewer.panX = 0;
  viewer.panY = 0;
  if (webglModelViewer) {
    webglModelViewer.fitView("iso");
    return;
  }
  drawViewer();
}

function dispatchPhase17View(view, fallback) {
  const phase17Canvas = byId("phase17Canvas");
  if (phase17Canvas && !phase17Canvas.classList.contains("hidden")) {
    window.dispatchEvent(new CustomEvent("phase17:view", { detail: { view } }));
    return;
  }
  fallback();
}

async function loadScenes() {
  const catalog = await api("/api/scenes");
  sceneCatalog = catalog.scenes || [];
  const select = byId("scene");
  select.innerHTML = "";
  for (const scene of sceneCatalog) {
    const option = document.createElement("option");
    option.value = scene.id;
    option.textContent = sceneDisplayNames[scene.id] || scene.title;
    select.appendChild(option);
  }
  const option = document.createElement("option");
  option.value = aleBlastSceneId;
  option.textContent = "MM-ALE 爆炸";
  select.appendChild(option);
  renderFields();
}

async function loadAssemblyCatalogs() {
  const [components, actions, blastCases] = await Promise.all([
    api("/api/components"),
    api("/api/physics-actions"),
    api("/api/blast-cases")
  ]);
  componentCatalog = components.components || [];
  physicsActionCatalog = actions.actions || [];
  blastCaseCatalog = blastCases.cases || [];
  const blastSelect = byId("blastCaseSelect");
  blastSelect.innerHTML = "";
  for (const item of blastCaseCatalog) {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.display_name;
    blastSelect.appendChild(option);
  }
  initializeAssemblyState();
  renderAssemblyEditors();
}

async function loadBlastDemo() {
  return runAction("正在载入钢板爆炸样例", async () => {
    const result = await api("/api/blast-demo");
    const payload = result.payload || {};
    assemblyState.components = JSON.parse(JSON.stringify(payload.components || []));
    assemblyState.actions = JSON.parse(JSON.stringify(payload.actions || []));
    assemblyState.analysisControl = JSON.parse(JSON.stringify(payload.analysis_control || null));
    assemblyState.database = JSON.parse(JSON.stringify(payload.database || null));
    assemblyState.caseId = "phase12_blast_plate_demo";
    byId("projectName").value = payload.project_name || "phase12_blast_plate_demo";
    renderAssemblyEditors();
    return {
      ok: true,
      operation: "load_blast_demo",
      project_name: byId("projectName").value,
      component_count: assemblyState.components.length,
      action_count: assemblyState.actions.length,
      notice: payload.engineering_notice
    };
  });
}

async function loadPhase13BlastCase() {
  const caseId = byId("blastCaseSelect").value;
  const selected = blastCaseCatalog.find((item) => item.id === caseId);
  const projectName = selected ? selected.default_project_name : `phase13_${caseId}`;
  return runAction("正在载入 Phase 13 爆炸预设", async () => {
    const result = await api(
      `/api/blast-case?case_id=${encodeURIComponent(caseId)}&project_name=${encodeURIComponent(projectName)}`
    );
    const payload = result.payload || {};
    assemblyState.components = JSON.parse(JSON.stringify(payload.components || []));
    assemblyState.actions = JSON.parse(JSON.stringify(payload.actions || []));
    assemblyState.analysisControl = JSON.parse(JSON.stringify(payload.analysis_control || null));
    assemblyState.database = JSON.parse(JSON.stringify(payload.database || null));
    assemblyState.caseId = payload.case_id || caseId;
    byId("projectName").value = payload.project_name || projectName;
    renderAssemblyEditors();
    return {
      ok: true,
      operation: "load_phase13_blast_case",
      project_name: byId("projectName").value,
      case_id: assemblyState.caseId,
      component_count: assemblyState.components.length,
      action_count: assemblyState.actions.length,
      notice: payload.engineering_notice
    };
  });
}

function projectListName(project) {
  if (!project || typeof project !== "object") return "";
  const name = project.project_name || project.name || "";
  return typeof name === "string" ? name.trim() : "";
}

function renderProjects(projects) {
  const box = byId("projects");
  box.innerHTML = "";
  const 有效项目 = projects
    .filter((project) => projectListName(project))
    .slice(0, 5);
  if (!有效项目.length) {
    box.textContent = "暂无项目。";
    return;
  }

  for (const project of 有效项目) {
    const projectName = projectListName(project);
    const row = document.createElement("div");
    row.className = "project-item";

    const text = document.createElement("div");
    const name = document.createElement("div");
    name.className = "project-name";
    name.textContent = projectName;
    const source = document.createElement("div");
    source.className = "project-source";
    source.textContent = project.source || "workspace";
    text.appendChild(name);
    text.appendChild(source);

    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "使用";
    button.addEventListener("click", () => {
      byId("projectName").value = projectName;
      lastProjectName = projectName;
      refreshActionAvailability();
      updateContextStatus();
    });

    row.appendChild(text);
    row.appendChild(button);
    box.appendChild(row);
  }
}

function updateComparisonProjectOptions(projects) {
  const names = projects
    .map(projectListName)
    .filter(Boolean);
  for (const [id, fallbackIndex] of [["compareProjectA", 0], ["compareProjectB", 1]]) {
    const select = byId(id);
    const previous = select.value;
    select.innerHTML = "";
    for (const name of names) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      select.appendChild(option);
    }
    if (names.includes(previous)) select.value = previous;
    else if (names[fallbackIndex]) select.value = names[fallbackIndex];
  }
}

async function loadProjects() {
  const result = await api("/api/projects");
  renderProjects(result.projects || []);
  updateComparisonProjectOptions(result.projects || []);
}

function impactMetricText(metric) {
  if (!metric || !metric.available) return "不可用";
  const value = Number(metric.value);
  const formatted = Number.isFinite(value)
    ? (Math.abs(value) >= 10000 || (Math.abs(value) > 0 && Math.abs(value) < 0.001)
      ? value.toExponential(3)
      : value.toLocaleString("zh-CN", { maximumSignificantDigits: 5 }))
    : "非有限值";
  return `${formatted} ${metric.unit || ""}`.trim();
}

function showImpactObjectDetail(item) {
  viewer.selectedImpactPartIds = new Set((item.part_ids || []).map(String));
  drawViewer();
  const box = byId("cityImpactDetail");
  box.innerHTML = "";
  box.classList.remove("hidden");
  const title = document.createElement("h3");
  title.textContent = `${item.label} · ${item.risk.label}`;
  box.appendChild(title);
  for (const metric of Object.values(item.metrics || {})) {
    const row = document.createElement("div");
    row.className = "impact-metric";
    const label = document.createElement("span");
    label.textContent = metric.label || "指标";
    const value = document.createElement("strong");
    value.textContent = impactMetricText(metric);
    row.appendChild(label);
    row.appendChild(value);
    box.appendChild(row);
  }
  if (item.diagnostics && item.diagnostics.source === "matsum") {
    const row = document.createElement("div");
    row.className = "impact-metric";
    const label = document.createElement("span");
    label.textContent = "响应诊断";
    const value = document.createElement("strong");
    value.textContent = Number(item.diagnostics.peak_kinetic_energy_j || 0) > 0
      ? "检测到能量响应"
      : "当前时段未检测到明显响应";
    row.appendChild(label);
    row.appendChild(value);
    box.appendChild(row);
  }
}

function renderCityImpactAssessment(assessment) {
  const status = byId("cityImpactStatus");
  const coverage = Number(
    assessment.quality
    && assessment.quality.global_metrics
    && assessment.quality.global_metrics.time_coverage_ratio
  );
  const coverageText = Number.isFinite(coverage) ? `；时间覆盖 ${(coverage * 100).toFixed(1)}%` : "";
  status.textContent = `${assessment.status_label || assessment.status}${coverageText}`;

  viewer.riskByPartId = new Map(
    Object.entries(assessment.part_risk || {}).filter((entry) => riskColors[entry[1]])
  );
  viewer.selectedImpactPartIds = new Set();
  if (viewer.mesh) renderPartLegend(viewer.mesh);
  drawViewer();

  const list = byId("cityImpactObjects");
  list.innerHTML = "";
  for (const item of assessment.objects || []) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "impact-object";
    const name = document.createElement("span");
    name.className = "impact-object-name";
    name.textContent = item.label;
    const risk = document.createElement("span");
    risk.className = `risk-chip risk-${item.risk.level}`;
    risk.textContent = item.risk.label;
    button.appendChild(name);
    button.appendChild(risk);
    button.addEventListener("click", () => showImpactObjectDetail(item));
    list.appendChild(button);
  }
  byId("cityImpactDetail").classList.add("hidden");
  byId("cityImpactDetail").innerHTML = "";
}

async function readCityImpact() {
  const projectName = currentProjectName() || lastProjectName;
  if (!projectName) return showError(new Error("请先选择一个城市街道项目。"));
  return runAction("正在读取城市影响评估", async () => {
    if (viewer.projectName !== projectName) await loadInteractiveMesh(projectName);
    const result = await api(
      `/api/project/city-impact?project_name=${encodeURIComponent(projectName)}`
    );
    renderCityImpactAssessment(result);
    return result;
  });
}

async function exportCityImpactReport() {
  const projectName = currentProjectName() || lastProjectName;
  if (!projectName) return showError(new Error("请先选择一个城市街道项目。"));
  return runAction("正在导出城市影响报告", () =>
    api("/api/project/city-impact-report", {
      method: "POST",
      body: JSON.stringify({ project_name: projectName })
    })
  );
}

async function compareBlastRuns() {
  const projectA = byId("compareProjectA").value;
  const projectB = byId("compareProjectB").value;
  if (!projectA || !projectB) return showError(new Error("请选择两个已有求解记录的项目。"));
  if (projectA === projectB) return showError(new Error("两个对比项目不能相同。"));
  return runAction("正在比较爆炸结果", () => api("/api/solve/compare", {
    method: "POST",
    body: JSON.stringify({ project_names: [projectA, projectB] })
  }));
}

async function runAction(label, action) {
  try {
    setBusy(true);
    showStatus(`${label}...`);
    const result = await action();
    showOperationSummary(label, result);
    return result;
  } catch (error) {
    showError(error);
    return null;
  } finally {
    setBusy(false);
  }
}

async function runPickerAction(label, statusId, action) {
  const statusBox = byId(statusId);
  if (pickerBusy) {
    if (statusBox) {
      statusBox.classList.add("warning");
      statusBox.textContent = "已有一个系统选择窗口正在等待操作。";
    }
    return null;
  }
  try {
    setPickerBusy(true);
    if (statusBox) {
      statusBox.classList.remove("warning");
      statusBox.classList.add("pending");
      statusBox.textContent = `${label}。选择窗口打开期间，其他功能仍可使用；如未看到系统窗口，请检查任务栏或按 Alt+Tab。`;
    }
    showStatus(`${label}...`);
    const result = await action();
    if (statusBox) statusBox.classList.remove("pending", "warning");
    showOperationSummary(label, result);
    return result;
  } catch (error) {
    const message = error && error.message ? error.message : String(error);
    if (statusBox) {
      statusBox.classList.remove("pending");
      statusBox.classList.add("warning");
      statusBox.textContent = /cancelled|取消/i.test(message)
        ? "已取消选择，没有修改当前配置。"
        : `选择未完成：${message}`;
    }
    showError(error);
    return null;
  } finally {
    setPickerBusy(false);
  }
}

async function resolveScene() {
  if (isAssemblyMode()) {
    return runAction("正在检查自由装配", () =>
      api("/api/assembly/validate", {
        method: "POST",
        body: JSON.stringify(assemblyPayload())
      })
    );
  }
  if (isAleBlastMode()) {
    return runAction("正在检查 MM-ALE 爆炸模型", () =>
      api("/api/ale-blast/validate", {
        method: "POST",
        body: JSON.stringify(aleBlastPayload())
      })
    );
  }
  if (isTunnelBlastMode()) {
    return runAction("正在检查通道爆炸模型", () =>
      api("/api/tunnel-blast/validate", {
        method: "POST",
        body: JSON.stringify(tunnelBlastPayload())
      })
    );
  }
  if (isPhase15Mode()) {
    return runAction("正在检查 Phase 15 A-1 参数", async () => {
      const result = await api("/api/phase15/prepare", {
        method: "POST",
        body: JSON.stringify(phase15PreparationPayload())
      });
      const meshSummary = result.axisymmetric_region_mesh || {};
      updatePhase15AirGapSummary(meshSummary.phase15_air_gap);
      updatePhase15Qualification(result);
      return result;
    });
  }
  return runAction("正在解析参数", () =>
    api("/api/scene/resolve", {
      method: "POST",
      body: JSON.stringify(scenePayload())
    })
  );
}

async function generateScene() {
  if (!confirmGeneration()) return null;
  if (isPhase15Mode()) {
    return runAction("正在生成 Phase 15 A-1 二维轴对称模型", async () => {
      const payload = phase15Payload();
      const ifExists = payload.coupling_mode === "conforming_air_gap" ? "error" : "versioned";
      const result = await api("/api/phase15/generate", {
        method: "POST",
        body: JSON.stringify(Object.assign(payload, { if_exists: ifExists }))
      });
      rememberGeneratedProjectName(result);
      await loadProjects();
      await loadInteractiveMesh(lastProjectName);
      updatePhase15Qualification(result);
      refreshActionAvailability();
      return result;
    });
  }
  if (isAssemblyMode()) {
    return runAction("正在生成自由装配模型", async () => {
      const result = await api("/api/assembly/generate", {
        method: "POST",
        body: JSON.stringify(assemblyPayload({ if_exists: "versioned" }))
      });
      rememberGeneratedProjectName(result);
      await loadProjects();
      await loadInteractiveMesh(lastProjectName);
      return result;
    });
  }
  if (isAleBlastMode()) {
    return runAction("正在生成 MM-ALE 爆炸模型", async () => {
      const result = await api("/api/ale-blast/generate", {
        method: "POST",
        body: JSON.stringify(aleBlastPayload({ if_exists: "versioned" }))
      });
      rememberGeneratedProjectName(result);
      await loadProjects();
      await loadInteractiveMesh(lastProjectName);
      return result;
    });
  }
  if (isTunnelBlastMode()) {
    return runAction("正在生成通道爆炸模型", async () => {
      const result = await api("/api/tunnel-blast/generate", {
        method: "POST",
        body: JSON.stringify(tunnelBlastPayload({ if_exists: "versioned" }))
      });
      rememberGeneratedProjectName(result);
      await loadProjects();
      await loadInteractiveMesh(lastProjectName);
      return result;
    });
  }
  return runAction("正在生成模型", async () => {
    const result = await api("/api/scene/generate", {
      method: "POST",
      body: JSON.stringify(scenePayload({ if_exists: "versioned" }))
    });
    rememberGeneratedProjectName(result);
    await loadProjects();
    await loadInteractiveMesh(lastProjectName);
    return result;
  });
}

async function previewInteractiveModel() {
  const projectName = byId("projectName").value.trim() || lastProjectName;
  return runAction("正在刷新三维预览", () => loadInteractiveMesh(projectName));
}

async function openLsPrePost() {
  const projectName = byId("projectName").value.trim() || lastProjectName;
  return runAction("打开 LS-PrePost", () =>
    api("/api/project/open-lsprepost", {
      method: "POST",
      body: JSON.stringify({ project_name: projectName })
    })
  );
}

async function sendToLsrun() {
  const projectName = byId("projectName").value.trim() || lastProjectName;
  return runAction("正在送入 LS-Run", async () => {
    const result = await api("/api/solve/open-lsrun", {
      method: "POST",
      body: JSON.stringify({
        project_name: projectName,
        ncpu: Number(byId("solveNcpu").value),
        memory: byId("solveMemory").value.trim()
      })
    });
    updatePhase15Qualification(result);
    byId("solverRunStatus").textContent =
      `LS-Run 已打开；运行编号：${result.run_id}。这不代表 LS-DYNA 已提交，请在 LS-Run 中确认作业。`;
    return result;
  });
}

async function recoverLsrun() {
  const projectName = byId("projectName").value.trim() || lastProjectName;
  if (!lastLsrunRunId) throw new Error("没有可回收的 LS-Run 运行编号。");
  return runAction("正在回收 LS-Run 求解结果", async () => {
    const result = await api("/api/solve/recover-lsrun", {
      method: "POST",
      body: JSON.stringify({
        project_name: projectName,
        run_id: lastLsrunRunId
      })
    });
    updatePhase15Qualification(result);
    byId("solverRunStatus").textContent = result.ok
      ? `求解证据与传播门禁通过：${result.run_id}`
      : `结果尚未验收：${result.status}。`;
    return result;
  });
}

async function openResultLspp() {
  const projectName = byId("projectName").value.trim() || lastProjectName;
  if (!lastQualifiedD3plot) throw new Error("当前没有通过证据校验的 d3plot。");
  return runAction("正在用 LS-PrePost 打开求解结果", () =>
    api("/api/project/open-result-lsprepost", {
      method: "POST",
      body: JSON.stringify({
        project_name: projectName,
        run_id: lastQualifiedD3plot
      })
    })
  );
}

function directSolvePayload() {
  const projectName = byId("projectName").value.trim() || lastProjectName;
  const confirmation = byId("solveProjectConfirmation").value;
  const ncpu = Number(byId("solveNcpu").value);
  const timeout = Number(byId("solveTimeout").value);
  const memory = byId("solveMemory").value.trim();
  if (!projectName) throw new Error("请先选择或生成一个项目。");
  if (!lsdynaConfigured) throw new Error("请先导入有效的 LS-DYNA 求解器。");
  if (confirmation !== projectName) throw new Error("求解确认名称必须与当前项目名称完全一致。");
  if (!Number.isInteger(ncpu) || ncpu < 1 || ncpu > 64) throw new Error("CPU 核数必须是 1 到 64 的整数。");
  if (!/^[1-9][0-9]{0,5}[mMgG]$/.test(memory)) throw new Error("内存格式应类似 20m 或 2g。");
  if (!Number.isFinite(timeout) || timeout < 1 || timeout > 7200) throw new Error("超时必须在 1 到 7200 秒之间。");
  return {
    project_name: projectName,
    confirmation_project_name: confirmation,
    ncpu,
    memory,
    timeout_s: timeout
  };
}

async function runLsdyna() {
  return runAction("正在运行 LS-DYNA", async () => {
    const result = await api("/api/solve/run-lsdyna", {
      method: "POST",
      body: JSON.stringify(directSolvePayload())
    });
    byId("solverRunStatus").textContent = result.ok
      ? `求解完成：${result.run_id}`
      : `求解未通过：${result.status}。请查看下方结果摘要。`;
    updatePhase15Qualification(result);
    return result;
  });
}

async function readSolveStatus() {
  const projectName = byId("projectName").value.trim() || lastProjectName;
  if (!projectName) return showError(new Error("请先选择一个项目。"));
  return runAction("正在读取求解记录", async () => {
    const result = await api(`/api/solve/status?project_name=${encodeURIComponent(projectName)}`);
    byId("solverRunStatus").textContent = result.status === "not_started"
      ? "当前项目尚未启动直接求解。"
      : `最近求解状态：${result.status}；运行编号：${result.run_id || "无"}`;
    updatePhase15Qualification(result);
    return result;
  });
}

function isRefinedBlastWorkbenchPath(pathname) {
  return pathname === "/refined-building-blast" || pathname === "/refined-building-blast/";
}

function refinedBlastProjectIdFromLocation() {
  const projectId = new URLSearchParams(window.location.search).get("project_id");
  return projectId && /^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(projectId) ? projectId : null;
}

let refinedBlastWorkbenchModule = null;
let refinedBlastPersistenceModule = null;
let refinedBlastRouteReady = false;
let legacyWorkbenchBootStarted = false;

async function boot() {
  setupRefinedBlastWorkbenchRoute();
  if (isRefinedBlastWorkbenchPath(window.location.pathname)) {
    await showRefinedBlastWorkbench({ updateHistory: false, projectId: refinedBlastProjectIdFromLocation(), restoreProject: true });
    return;
  }
  if (legacyWorkbenchBootStarted) return;
  legacyWorkbenchBootStarted = true;
  setupWorkbenchNavigation();
  resetPhase15Qualification();
  updatePhase15CouplingControls();
  byId("prompt").addEventListener("input", () => {
    promptEdited = true;
  });
  byId("projectName").addEventListener("input", () => {
    byId("solveProjectConfirmation").value = "";
    resetPhase15Qualification();
    updateContextStatus();
  });
  byId("scene").addEventListener("change", () => {
    renderFields();
    setModelMode();
  });
  byId("modelMode").addEventListener("change", setModelMode);
  byId("phase15CouplingMode").addEventListener("change", updatePhase15CouplingControls);
  byId("phase15MeshSize").addEventListener("change", updatePhase15CouplingControls);
  byId("phase15FsiOverlapLayers").addEventListener("change", updatePhase15FsiOverlapSummary);
  ["phase15TntDiameter", "phase15BoreholeRadius", "phase15BottomAirGap"]
    .forEach((id) => byId(id).addEventListener("input", updatePhase15AirGapSummary));
  [
    "tunnelLength", "tunnelWidth", "tunnelHeight", "tunnelWallThickness",
    "tunnelExplosiveMass", "tunnelExplosiveX", "tunnelExplosiveY", "tunnelExplosiveZ",
    "tunnelPlateLength", "tunnelPlateWidth", "tunnelPlateThickness",
    "tunnelPlateX", "tunnelPlateY", "tunnelPlateZ", "tunnelAirMesh"
  ].forEach((id) => byId(id).addEventListener("input", updateTunnelMeshEstimate));
  byId("addComponent").addEventListener("click", () => {
    const component = newAssemblyComponent(componentCatalog[0] && componentCatalog[0].name);
    if (component) assemblyState.components.push(component);
    renderAssemblyEditors();
  });
  byId("addPhysicsAction").addEventListener("click", () => {
    const type = physicsActionCatalog[0] ? physicsActionCatalog[0].type : "fixed_region";
    assemblyState.actions.push(newPhysicsAction(type));
    renderAssemblyActions();
  });
  byId("loadBlastDemo").addEventListener("click", loadBlastDemo);
  byId("loadPhase13BlastCase").addEventListener("click", loadPhase13BlastCase);
  byId("refresh").addEventListener("click", () => runAction("正在刷新项目", loadProjects));
  byId("importLspp").addEventListener("click", importLsppPath);
  byId("checkLspp").addEventListener("click", checkLsppPath);
  byId("saveLspp").addEventListener("click", saveLsppPath);
  byId("selectExportDir").addEventListener("click", selectExportDir);
  byId("saveExportDir").addEventListener("click", saveExportDir);
  byId("importLsrun").addEventListener("click", importLsrunPath);
  byId("checkLsrun").addEventListener("click", checkLsrunPath);
  byId("saveLsrun").addEventListener("click", saveLsrunPath);
  byId("importLsdyna").addEventListener("click", importLsdynaPath);
  byId("checkLsdyna").addEventListener("click", checkLsdynaPath);
  byId("saveLsdyna").addEventListener("click", saveLsdynaPath);
  byId("runLsdyna").addEventListener("click", runLsdyna);
  byId("readSolveStatus").addEventListener("click", readSolveStatus);
  byId("compareBlastRuns").addEventListener("click", compareBlastRuns);
  byId("readCityImpact").addEventListener("click", readCityImpact);
  byId("exportCityImpact").addEventListener("click", exportCityImpactReport);
  byId("sendToLsrun").addEventListener("click", sendToLsrun);
  byId("recoverLsrun").addEventListener("click", recoverLsrun);
  byId("openResultLspp").addEventListener("click", openResultLspp);
  byId("selectImportPackageDir").addEventListener("click", selectImportPackageDir);
  byId("importPackage").addEventListener("click", importPackage);
  byId("resolve").addEventListener("click", resolveScene);
  byId("generate").addEventListener("click", generateScene);
  byId("preview").addEventListener("click", previewInteractiveModel);
  byId("openLspp").addEventListener("click", openLsPrePost);
  byId("fitView").addEventListener("click", () =>
    dispatchPhase17View("fit", fitView)
  );
  byId("isoView").addEventListener("click", () =>
    dispatchPhase17View("iso", () => setView(-0.65, 0.55))
  );
  byId("topView").addEventListener("click", () =>
    dispatchPhase17View("top", () => setView(0, 0))
  );
  byId("frontView").addEventListener("click", () =>
    dispatchPhase17View("front", () => setView(0, Math.PI / 2))
  );
  byId("modelViewMode").addEventListener("click", () => setViewportMode("model"));
  byId("resultViewMode").addEventListener("click", () => setViewportMode("results"));
  byId("displayMode").addEventListener("change", (event) => setViewerDisplayMode(event.target.value));
  byId("toggleGrid").addEventListener("click", () => toggleViewerOption("showGrid", "toggleGrid"));
  byId("toggleLegend").addEventListener("click", () => toggleViewerOption("showLegend", "toggleLegend"));
  byId("toggleBlastSources").addEventListener("click", () => toggleViewerOption("showBlastSources", "toggleBlastSources"));
  byId("showAllParts").addEventListener("click", showAllViewerParts);
  byId("clearPartSelection").addEventListener("click", () => selectViewerPart(""));
  byId("hideSelectedPart").addEventListener("click", hideSelectedPart);
  byId("isolateSelectedPart").addEventListener("click", isolateSelectedPart);
  byId("fullscreenView").addEventListener("click", () => toggleViewportFullscreen().catch(showError));
  byId("refreshResultStatus").addEventListener("click", loadViewportResultStatus);
  document.addEventListener("fullscreenchange", updateFullscreenButton);
  await initializeModelViewer();
  if (!webglModelViewer) setupViewerInput();

  await loadConfig();
  await loadScenes();
  await loadAssemblyCatalogs();
  await loadProjects();
  setModelMode();
  updateContextStatus();
  drawViewer();
  await registerLegacyNavigation();
}

boot().catch(showError);

async function registerLegacyNavigation() {
  const navigation=window.WorkbenchNavigation;if(!navigation)return;
  const root=byId('legacyWorkbenchRoot');
  let pendingPhase17=null;
  await navigation.register('modeling',{
    restoreIdentity:()=>{const name=new URL(location.href).searchParams.get('project_name');return name===null?null:name.trim()||'new';},
    context:()=>({identity:currentProjectName()||'new',label:currentProjectName()||'未命名建模草稿',url:'/?project_name='+encodeURIComponent(currentProjectName()||'')}),
    capture:()=>{
      const detail={};window.dispatchEvent(new CustomEvent('phase17:get-navigation-state',{detail}));
      return {fields:navigation.captureFields(root),assembly:structuredClone(assemblyState),promptEdited,lastProjectName,phase17:detail.snapshot||pendingPhase17};
    },
    restore:saved=>{
      for(const id of ['modelMode','scene']){const f=saved.fields?.find(f=>f.key==='id:'+id);if(f&&Array.from(byId(id).options).some(o=>o.value===f.value))byId(id).value=f.value;}
      if(saved.assembly&&Array.isArray(saved.assembly.components)&&Array.isArray(saved.assembly.actions))Object.assign(assemblyState,structuredClone(saved.assembly));
      renderFields();setModelMode();navigation.restoreFields(root,saved.fields);
      promptEdited=!!saved.promptEdited;lastProjectName=saved.lastProjectName||'';
      pendingPhase17=saved.phase17||null;
      const restoreCity=()=>{
        window.dispatchEvent(new CustomEvent('phase17:restore-navigation-state',{detail:{snapshot:pendingPhase17}}));
        navigation.restoreFields(root,saved.fields);
      };
      restoreCity();if(pendingPhase17)window.addEventListener('phase17:navigation-ready',restoreCity,{once:true});
      updatePhase15CouplingControls();updateTunnelMeshEstimate();refreshActionAvailability();updateContextStatus();
    },
  });
}

async function loadRefinedBlastWorkbenchModule() {
  if (!refinedBlastWorkbenchModule) {
    refinedBlastWorkbenchModule = import("/refined_blast_workbench.js");
  }
  return refinedBlastWorkbenchModule;
}

async function loadRefinedBlastPersistenceModule() {
  if (!refinedBlastPersistenceModule) {
    refinedBlastPersistenceModule = import("/refined_blast_persistence.js");
  }
  return refinedBlastPersistenceModule;
}

async function refinedBlastRecoveryOptions(options = {}) {
  const persistence = await loadRefinedBlastPersistenceModule();
  const urlProjectId = refinedBlastProjectIdFromLocation();
  let storedProjectId = null;
  let sessionDraft = null;
  try {
    storedProjectId = persistence.readLatestProjectId(window.localStorage);
    sessionDraft = persistence.readSessionDraft(window.sessionStorage);
  } catch (_) {}
  const projectId = options.projectId || urlProjectId || storedProjectId;
  return {
    ...(!projectId && sessionDraft ? {
      assetId: sessionDraft.asset_id,
      building: sessionDraft.building,
      sessionDraft: sessionDraft.draft,
    } : {}),
    ...options,
    projectId,
    restoreProject: Boolean(projectId),
  };
}

async function showRefinedBlastWorkbench(options = {}) {
  const legacyRoot = byId("legacyWorkbenchRoot");
  const refinedRoot = byId("refinedBlastWorkbenchRoot");
  legacyRoot.classList.add("hidden");
  refinedRoot.classList.remove("hidden");
  const module = await loadRefinedBlastWorkbenchModule();
  const recoveredOptions = await refinedBlastRecoveryOptions(options);
  module.unmountRefinedBlastWorkbench();
  module.mountRefinedBlastWorkbench(refinedRoot, recoveredOptions);
  refinedRoot.querySelector("[data-refined-back]").focus();
}

function showLegacyWorkbench() {
  const legacyRoot = byId("legacyWorkbenchRoot");
  const refinedRoot = byId("refinedBlastWorkbenchRoot");
  legacyRoot.classList.remove("hidden");
  refinedRoot.classList.add("hidden");
  if (refinedBlastWorkbenchModule) {
    refinedBlastWorkbenchModule.then((module) => module.unmountRefinedBlastWorkbench());
  }
  boot().catch(showError);
  byId("openRefinedBlastWorkbench").focus();
}

function setupRefinedBlastWorkbenchRoute() {
  if (refinedBlastRouteReady) return;
  refinedBlastRouteReady = true;
  byId("openRefinedBlastWorkbench").addEventListener("click", () => {
    showRefinedBlastWorkbench().catch(showError);
  });
  window.addEventListener("popstate", () => {
    if (isRefinedBlastWorkbenchPath(window.location.pathname)) {
      showRefinedBlastWorkbench({ updateHistory: false, projectId: refinedBlastProjectIdFromLocation(), restoreProject: true }).catch(showError);
      return;
    }
    showLegacyWorkbench();
  });
}

function setupViewerInput() {
  const canvas = byId("modelCanvas");
  canvas.addEventListener("pointerdown", (event) => {
    viewer.dragging = true;
    viewer.dragButton = event.button;
    viewer.pointerStartX = event.clientX;
    viewer.pointerStartY = event.clientY;
    viewer.pointerMoved = false;
    viewer.lastX = event.clientX;
    viewer.lastY = event.clientY;
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!viewer.dragging) return;
    const dx = event.clientX - viewer.lastX;
    const dy = event.clientY - viewer.lastY;
    if (Math.hypot(event.clientX - viewer.pointerStartX, event.clientY - viewer.pointerStartY) > 4) {
      viewer.pointerMoved = true;
    }
    viewer.lastX = event.clientX;
    viewer.lastY = event.clientY;
    if (viewer.dragButton === 2 || event.buttons === 4) {
      viewer.panX += dx;
      viewer.panY += dy;
    } else {
      viewer.yaw += dx * 0.01;
      viewer.pitch = Math.max(-1.45, Math.min(1.45, viewer.pitch + dy * 0.01));
    }
    drawViewer();
  });
  canvas.addEventListener("pointerup", (event) => {
    const shouldPick = viewer.dragButton === 0 && !viewer.pointerMoved;
    viewer.dragging = false;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    if (shouldPick && viewer.mode === "model") pickPartAt(event.clientX, event.clientY);
  });
  canvas.addEventListener("pointerleave", () => {
    viewer.dragging = false;
  });
  canvas.addEventListener("contextmenu", (event) => event.preventDefault());
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const factor = event.deltaY < 0 ? 1.1 : 0.9;
    viewer.zoom = Math.max(0.12, Math.min(30, viewer.zoom * factor));
    drawViewer();
  }, { passive: false });
  window.addEventListener("resize", drawViewer);
}
