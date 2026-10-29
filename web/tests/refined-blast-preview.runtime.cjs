const { prepareWorkbenchSource } = require("./workbench-dependencies.cjs");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.resolve(__dirname, "..", "..");
const statePath = path.join(root, "lsprepost_mcp", "web", "static", "refined_blast_state.js");
const viewerPath = path.join(root, "lsprepost_mcp", "web", "static", "refined_blast_viewer.js");
const workbenchPath = path.join(root, "lsprepost_mcp", "web", "static", "refined_blast_workbench.js");
const layerIds = [
  "cavities_openings", "structure", "reinforcement_connections", "nonstructural",
  "exposed_surfaces", "blast_source", "fluid_domain", "boundaries", "support_ground",
];
const metricIds = [
  "building_nodes", "building_elements", "provider_nodes", "provider_elements",
  "provider_fsi_faces", "module_new_nodes", "module_new_elements", "symbolic_ids",
];

function preview(projectId, revision, marker) {
  return {
    project_id: projectId, scenario_id: "scenario-1", project_revision: revision,
    cache_key: "semantic-cache", fingerprint: "preview-fingerprint", is_final: false,
    layers: layerIds.map((layer_id, ordinal) => ({
      layer_id,
      payload: {
        ordinal,
        neutral_representation: {
          schema_version: "refined_blast.neutral_primitives@1", representation: "full_geometry",
          source_item_count: 1, rendered_item_count: 1, coverage: 1,
          primitive_count: 1, payload_byte_count: 1, fingerprint: `primitive-${ordinal}`,
        },
        neutral_primitives: [{
          primitive_id: `${layer_id}:primitive`,
          kind: "mesh",
          nodes: [[ordinal, 0, 0], [ordinal, 1, 0]], faces: [], edges: [[0, 1]],
        }],
      },
      source_fingerprints: [`source-${ordinal}`], fingerprint: `layer-${ordinal}`,
    })),
    counts: metricIds.map((metric, index) => ({ metric, value: index + 1, semantics: [0, 1, 7].includes(index) ? "exact" : "upper_bound" })),
    marker,
  };
}

function loadState(fetchImpl = () => Promise.reject(new Error("unexpected fetch"))) {
  const source = fs.readFileSync(statePath, "utf8")
    .replace(/export function /g, "function ")
    .concat("\nmodule.exports = { createRefinedBlastStore };\n");
  const context = vm.createContext({ module: { exports: {} }, structuredClone, JSON, Object, Array, Promise, Set, Map, fetch: fetchImpl });
  new vm.Script(source, { filename: statePath }).runInContext(context);
  return context.module.exports;
}

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase(); this.children = []; this.dataset = {};
    this.listeners = new Map(); this.parentNode = null; this.textContent = "";
  }
  append(...children) { for (const child of children) { child.parentNode = this; this.children.push(child); } }
  replaceChildren(...children) { for (const child of this.children) child.parentNode = null; this.children = []; this.append(...children); }
  remove() { if (!this.parentNode) return; this.parentNode.children = this.parentNode.children.filter((child) => child !== this); this.parentNode = null; }
  addEventListener(type, listener) { if (!this.listeners.has(type)) this.listeners.set(type, new Set()); this.listeners.get(type).add(listener); }
  removeEventListener(type, listener) { this.listeners.get(type)?.delete(listener); }
  setAttribute(name, value) { this[name] = String(value); }
  setPointerCapture(pointerId) { this.capturedPointerId = pointerId; }
  hasPointerCapture(pointerId) { return this.capturedPointerId === pointerId; }
  releasePointerCapture(pointerId) {
    if (!this.hasPointerCapture(pointerId)) throw new Error("invalid pointer capture release");
    this.capturedPointerId = null;
  }
  querySelectorAll(selector) {
    const matches = [];
    const visit = (element) => {
      if (selector === "[data-refined-source-axis]" && element.dataset?.refinedSourceAxis) matches.push(element);
      if (selector === "[data-refined-source-place]" && element.dataset?.refinedSourcePlace) matches.push(element);
      for (const child of element.children ?? []) visit(child);
    };
    visit(this);
    return matches;
  }
  dispatch(type, event = {}) { for (const listener of this.listeners.get(type) ?? []) listener({ preventDefault() {}, ...event }); }
  getContext() {
    return {
      clearRect() {}, fillRect() {}, fillText() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {},
      set fillStyle(_) {}, set strokeStyle(_) {}, set font(_) {}, set textBaseline(_) {},
    };
  }
  getBoundingClientRect() { return { width: 640, height: 360 }; }
}

function loadViewer() {
  const webglCalls = { sync: [], fitView: [], destroyed: false, sourcePositions: [], pointSelectionEnabled: false };
  const createModelViewer = ({ canvas, onPointSelected }) => {
    const contextLoss = () => {};
    canvas.addEventListener("webglcontextlost", contextLoss);
    return {
      supported: true,
      sync(view) { webglCalls.sync.push(structuredClone({ ...view, hiddenParts: [...view.hiddenParts] })); },
      fitView(preset) { webglCalls.fitView.push(preset); },
      setPointSelectionEnabled(enabled) { webglCalls.pointSelectionEnabled = enabled; },
      updateBlastSourcePosition(_sourceId, position) { webglCalls.sourcePositions.push([...position]); },
      destroy() {
        canvas.removeEventListener("webglcontextlost", contextLoss);
        webglCalls.destroyed = true;
      },
    };
  };
  webglCalls.selectPoint = (point) => webglCalls.onPointSelected?.(point);
  const source = fs.readFileSync(viewerPath, "utf8")
    .replace('import { createModelViewer } from "./model_viewer_webgl.js";', "")
    .replace(/export function /g, "function ")
    .replace(/export \{ PREVIEW_COUNT_METRICS, PREVIEW_LAYER_IDS \};/g, "")
    .concat("\nmodule.exports = { renderRefinedBlastPreview, styleForPrimitive };\n");
  const document = { createElement: (tag) => new FakeElement(tag) };
  const context = vm.createContext({
    module: { exports: {} }, structuredClone, JSON, Object, Array, Set, Map,
    document, createModelViewer: (options) => { webglCalls.onPointSelected = options.onPointSelected; return createModelViewer(options); }, window: { devicePixelRatio: 1 }, requestAnimationFrame: (callback) => { callback(); return 1; }, cancelAnimationFrame() {},
  });
  new vm.Script(source, { filename: viewerPath }).runInContext(context);
  return { ...context.module.exports, document, webglCalls };
}

function storeOptions(projectId = "project-1", revision = 3, fetchImpl) {
  return {
    project_id: projectId, revision, fetch: fetchImpl,
    draft: { scenario_id: "scenario-1", scenario_kind: "external", building_placement: {}, load_provider: {} },
  };
}

async function guardMatrix() {
  const { createRefinedBlastStore } = loadState();
  const store = createRefinedBlastStore(storeOptions());
  const r2 = store.beginPreviewRequest({ mount_token: "mount-a", project_id: "project-1" });
  const r3 = store.beginPreviewRequest({ mount_token: "mount-a", project_id: "project-1" });
  store.applyPreview(preview("project-1", 3, "r3"), r3);
  store.applyPreview(preview("project-1", 3, "r2"), r2);
  const late_preview = store.getState().preview.marker;

  const other = store.beginPreviewRequest({ mount_token: "mount-a", project_id: "project-1" });
  const other_project_applied = store.applyPreview(preview("project-other", 3, "other"), other);

  const stale = store.beginPreviewRequest({ mount_token: "mount-a", project_id: "project-1" });
  store.updateDraft((draft) => { draft.scenario_kind = "internal"; });
  const stale_draft_applied = store.applyPreview(preview("project-1", 3, "stale"), stale);

  const oldMount = store.beginPreviewRequest({ mount_token: "mount-a", project_id: "project-1" });
  store.disposePreviewRequests("mount-a");
  const mountB = store.beginPreviewRequest({ mount_token: "mount-b", project_id: "project-1" });
  const old_mount_applied = store.applyPreview(preview("project-1", 3, "mount-a"), oldMount);
  store.applyPreview(preview("project-1", 3, "mount-b"), mountB);

  let resolveSave;
  const saving = new Promise((resolve) => { resolveSave = resolve; });
  const loaded = loadState(() => saving);
  const persistedStore = loaded.createRefinedBlastStore(storeOptions("project-1", 3, () => saving));
  const prior = persistedStore.beginPreviewRequest({ mount_token: "mount-a", project_id: "project-1" });
  const savePromise = persistedStore.save("project-1");
  resolveSave({ ok: true, status: 200, json: async () => ({ project: { revision: 4 } }) });
  await savePromise;
  const prior_revision_applied = persistedStore.applyPreview(preview("project-1", 3, "prior"), prior);

  return {
    late_preview, other_project_applied, stale_draft_applied, old_mount_applied,
    current_mount_preview: store.getState().preview.marker, prior_revision_applied,
  };
}

function viewerLocal() {
  const { renderRefinedBlastPreview, document } = loadViewer();
  const container = document.createElement("div");
  const payload = preview("project-1", 3, "viewer");
  const draft = { scenario_id: "scenario-1", revision: 3 };
  const beforePayload = JSON.stringify(payload); const beforeDraft = JSON.stringify(draft);
  const viewer = renderRefinedBlastPreview(container, preview("project-1", 2, "cached-scene"));
  const current_response_applied = viewer.update(payload) && viewer.projectRevision === 3;
  viewer.setLayerVisible("cavities_openings", false);
  return {
    visible_layers: viewer.getVisibleLayerIds(),
    draft_unchanged: JSON.stringify(payload) === beforePayload && JSON.stringify(draft) === beforeDraft,
    revision: payload.project_revision, fingerprint: payload.fingerprint,
    metric_semantics: viewer.getCountBadges().map((row) => row.semantics),
    current_response_applied,
  };
}

function dispose() {
  const { renderRefinedBlastPreview, document, webglCalls } = loadViewer();
  const container = document.createElement("div");
  const viewer = renderRefinedBlastPreview(container, preview("project-1", 3, "viewer"));
  const canvas = container.children[0];
  viewer.dispose();
  const listenerCount = [...canvas.listeners.values()].reduce((total, rows) => total + rows.size, 0);
  return {
    children: container.children.length, listener_count: listenerCount,
    old_update_accepted: viewer.setLayerVisible("structure", false), webgl_destroyed: webglCalls.destroyed,
  };
}

function viewerPrimitives() {
  const { renderRefinedBlastPreview, document, webglCalls } = loadViewer();
  const container = document.createElement("div");
  const payload = preview("project-1", 3, "viewer");
  const viewer = renderRefinedBlastPreview(container, payload);
  const firstMesh = JSON.stringify(webglCalls.sync.at(-1).mesh);
  webglCalls.fitView.length = 0;
  const changed = structuredClone(payload);
  let previousMesh = firstMesh; let primitiveMutationsChangedMesh = 0;
  for (let index = 0; index < changed.layers.length; index += 1) {
    changed.layers[index].payload.neutral_primitives[0].nodes[0][0] += 100 + index;
    changed.layers[index].payload.neutral_representation.fingerprint = `primitive-mutated-${index}`;
    changed.layers[index].fingerprint = `layer-mutated-${index}`;
    viewer.update(changed);
    const currentMesh = JSON.stringify(webglCalls.sync.at(-1).mesh);
    if (currentMesh !== previousMesh) primitiveMutationsChangedMesh += 1;
    previousMesh = currentMesh;
  }
  viewer.setLayerVisible("cavities_openings", false);
  const hiddenLayerPartCount = webglCalls.sync.at(-1).mesh.parts.length;
  const visibilityPreservedCamera = webglCalls.sync.at(-1).preserveCamera === true;
  webglCalls.fitView.length = 0;
  viewer.fitView("iso"); viewer.fitView("front"); viewer.fitView("top");
  const cameraPresets = webglCalls.fitView;
  return {
    primitive_mutations_changed_mesh: primitiveMutationsChangedMesh,
    hidden_layer_part_count: hiddenLayerPartCount,
    visibility_preserved_camera: visibilityPreservedCamera,
    camera_presets: cameraPresets,
    distinct_camera_presets: new Set(cameraPresets).size,
  };
}

function viewerFluidDomainPresentation() {
  const { renderRefinedBlastPreview, document, webglCalls } = loadViewer();
  const container = document.createElement("div");
  renderRefinedBlastPreview(container, preview("project-1", 3, "fluid-presentation"));
  const parts = webglCalls.sync.at(-1).mesh.parts;
  const structure = parts.find((part) => part.part_id.startsWith("structure::"));
  const fluid = parts.find((part) => part.part_id.startsWith("fluid_domain::"));
  return {
    structure_opacity: structure?.opacity,
    fluid_opacity: fluid?.opacity,
    fluid_is_translucent: Number(fluid?.opacity) > 0 && Number(fluid?.opacity) < 0.25,
  };
}

function viewerLayeredProxyStyles() {
  const { styleForPrimitive } = loadViewer();
  const foundation = styleForPrimitive("support_ground", "building-foundation-proxy");
  const ground = styleForPrimitive("support_ground", "support-ground-proxy");
  const air = styleForPrimitive("fluid_domain", "active-air-proxy");
  const grid = styleForPrimitive("support_ground", "ground-mesh-grid");
  const boundary = styleForPrimitive("boundaries", "active-air-flow-boundary");
  return { foundation_color: foundation.color, ground_color: ground.color, air_opacity: air.opacity, ground_opacity: ground.opacity, grid_faces_visible: grid.facesVisible, boundary_faces_visible: boundary.facesVisible };
}

function viewerBlastSourceEditor() {
  const { renderRefinedBlastPreview, document, webglCalls } = loadViewer();
  const container = document.createElement("div");
  const payload = preview("project-1", 3, "viewer");
  const sourceLayer = payload.layers.find((layer) => layer.layer_id === "blast_source");
  sourceLayer.payload.neutral_primitives = [{
    primitive_id: "source-1", kind: "blast_source", position_m: [1, 2, 3],
  }];
  sourceLayer.payload.neutral_representation.fingerprint = "source-editor";
  const commits = [];
  renderRefinedBlastPreview(container, payload, {
    blastSourceEditor: { position_m: [1, 2, 3], drag_step_m: 0.1, onCommit: (point) => commits.push([...point]) },
  });
  const pointSelectionEnabledBefore = webglCalls.pointSelectionEnabled;
  const place = container.querySelectorAll("[data-refined-source-place]")[0];
  place.dispatch("click");
  const pointSelectionEnabledAfter = webglCalls.pointSelectionEnabled;
  webglCalls.selectPoint([4, 5, 6]);
  const controls = container.querySelectorAll("[data-refined-source-axis]");
  const x = controls.find((control) => control.dataset.refinedSourceAxis === "X");
  x.dispatch("pointerdown", { clientX: 10, clientY: 10, pointerId: 1 });
  x.dispatch("pointermove", { clientX: 30, clientY: 10, pointerId: 1 });
  const dragPreview = webglCalls.sourcePositions.at(-1);
  x.dispatch("pointerup", { clientX: 30, clientY: 10, pointerId: 1 });
  x.dispatch("pointerdown", { clientX: 30, clientY: 10, pointerId: 2 });
  x.dispatch("pointermove", { clientX: 40, clientY: 10, pointerId: 2 });
  x.dispatch("pointercancel", { clientX: 40, clientY: 10, pointerId: 2 });
  const cancelRestored = webglCalls.sourcePositions.at(-1);
  const commitCountAfterCancel = commits.length;
  x.dispatch("pointerdown", { clientX: 30, clientY: 10, pointerId: 3 });
  x.dispatch("pointermove", { clientX: 50, clientY: 10, pointerId: 3 });
  x.dispatch("keydown", { key: "Escape" });
  const escapeRestored = webglCalls.sourcePositions.at(-1);
  const escapeReleasedCapture = x.capturedPointerId === null;
  x.dispatch("keydown", { key: "ArrowRight" });
  return {
    point_selection_enabled_before: pointSelectionEnabledBefore,
    point_selection_enabled_after: pointSelectionEnabledAfter,
    point_commit: commits[0], drag_preview: dragPreview, drag_commit: commits[1],
    cancel_restored: cancelRestored, commit_count_after_cancel: commitCountAfterCancel,
    escape_restored: escapeRestored, escape_released_capture: escapeReleasedCapture,
    keyboard_commit: commits[2],
    source_marker_updates: webglCalls.sourcePositions,
    drag_controls: controls.map((control) => control.dataset.refinedSourceAxis),
  };
}

async function workbenchRequest() {
  const requests = []; const renderedMarkers = []; const controls = new Map();
  const control = (key) => {
    if (!controls.has(key)) controls.set(key, {
      dataset: {}, disabled: false, checked: true, value: "", children: [],
      append(...children) { this.children.push(...children); },
      replaceChildren(...children) { this.children = children; },
      addEventListener(type, listener) { this.listener = listener; },
      setAttribute() {},
    });
    return controls.get(key);
  };
  const rootElement = {
    replaceChildren() {},
    querySelector(selector) { return control(selector); },
    querySelectorAll(selector) {
      if (selector === "[data-refined-layer]") return layerIds.map((id) => {
        const row = control(`layer-${id}`); row.dataset.refinedLayer = id; return row;
      });
      if (selector === "[data-refined-camera]") return [];
      return [];
    },
  };
  const deferred = [];
  const fetch = (url, options = {}) => {
    if (url.endsWith("capabilities")) return Promise.resolve({ ok: true, json: async () => ({
      providers: [], default_scenario_draft: { scenario_id: "scenario-1", scenario_kind: "external", building_placement: {}, load_provider: {} },
    }) });
    if (url.endsWith("assets")) return Promise.resolve({ ok: true, json: async () => ({ assets: [] }) });
    return new Promise((resolve) => { const row = { url, options, resolve }; requests.push(row); deferred.push(row); });
  };
  const stateSource = fs.readFileSync(statePath, "utf8")
    .replace("const REFINED_BLAST_API_PREFIX", "const _STATE_API_PREFIX")
    .replace(/REFINED_BLAST_API_PREFIX/g, "_STATE_API_PREFIX")
    .replace(/export function /g, "function ")
    .concat("\nmodule.exports = { createRefinedBlastStore, renderSchemaFields };\n");
  const context = vm.createContext({
    module: { exports: {} }, structuredClone, JSON, Object, Array, Promise, Set, Map,
    fetch, AbortController, setTimeout, clearTimeout,
    document: {
      createElement() { return control(`created-${controls.size}`); },
      createDocumentFragment() { return { append() {}, querySelectorAll() { return []; } }; },
    },
    window: { location: { pathname: "/refined-building-blast" }, fetch, history: { replaceState() {} }, dispatchEvent() {} },
    history: { pushState() {} }, PopStateEvent: class {},
    renderRefinedBlastPreview(_container, payload) {
      renderedMarkers.push(payload.marker);
      return { setLayerVisible() { return true; }, fitView() {}, dispose() {}, getCountBadges() { return payload.counts; } };
    },
  });
  new vm.Script(stateSource, { filename: statePath }).runInContext(context);
  context.createRefinedBlastStore = context.module.exports.createRefinedBlastStore;
  context.renderSchemaFields = context.module.exports.renderSchemaFields;
  context.module = { exports: {} };
  const workbenchSource = fs.readFileSync(workbenchPath, "utf8")
    .replace('import { createRefinedBlastStore, renderSchemaFields } from "./refined_blast_state.js";', "")
    .replace('import { renderRefinedBlastPreview } from "./refined_blast_viewer.js";', "")
    .replace(/export function /g, "function ")
    .concat("\nmodule.exports = { mountRefinedBlastWorkbench, unmountRefinedBlastWorkbench };\n");
  new vm.Script(prepareWorkbenchSource(workbenchSource, context), { filename: workbenchPath }).runInContext(context);
  const app = context.module.exports;
  app.mountRefinedBlastWorkbench(rootElement, {
    updateHistory: false, projectId: "project-1", revision: 3,
    draft: { scenario_id: "scenario-1", scenario_kind: "external", building_placement: {}, load_provider: {} },
  });
  await vm.runInContext("capabilitiesRequest", context);

  const first = control("[data-refined-preview]").listener();
  const second = control("[data-refined-preview]").listener();
  await Promise.resolve();
  deferred[1].resolve({ ok: true, json: async () => ({ preview: preview("project-1", 3, "current") }) });
  await second;
  deferred[0].resolve({ ok: true, json: async () => ({ preview: preview("project-1", 3, "late") }) });
  await first;
  const third = control("[data-refined-preview]").listener();
  await Promise.resolve();
  app.unmountRefinedBlastWorkbench();
  deferred[2].resolve({ ok: true, json: async () => ({ preview: preview("project-1", 3, "unmounted") }) });
  await third;
  return {
    expected_revisions: requests.map((row) => JSON.parse(row.options.body).expected_revision),
    first_aborted: requests[0].options.signal.aborted,
    rendered_markers: renderedMarkers,
    post_unmount_rendered: renderedMarkers.includes("unmounted"),
  };
}

async function flushBeforePreview() {
  let draftRevision = 1; let saveCalls = 0; let resolveFirst;
  const timers = [];
  const button = { dataset: {}, disabled: false };
  const rootElement = { querySelector() { return button; } };
  const store = {
    getState() { return { draft_revision: draftRevision, conflict: null }; },
    save() {
      saveCalls += 1;
      if (saveCalls === 1) return new Promise((resolve) => { resolveFirst = resolve; });
      return Promise.resolve({});
    },
  };
  const context = vm.createContext({
    module: { exports: {} }, structuredClone, JSON, Object, Array, Promise, Set, Map,
    setTimeout(callback) { timers.push(callback); return timers.length - 1; },
    clearTimeout(id) { timers[id] = null; },
    document: { createElement() { return {}; } },
    window: { fetch() {} }, renderRefinedBlastPreview() {},
    createRefinedBlastStore() {}, renderSchemaFields() {},
  });
  const source = fs.readFileSync(workbenchPath, "utf8")
    .replace('import { createRefinedBlastStore, renderSchemaFields } from "./refined_blast_state.js";', "")
    .replace('import { renderRefinedBlastPreview } from "./refined_blast_viewer.js";', "")
    .replace(/export function /g, "function ")
    .concat("\nfunction setActiveSessionForTest(session) { activeSession = session; mountedRoot = session.root; }\nmodule.exports = { flushSave, setActiveSessionForTest };\n");
  new vm.Script(prepareWorkbenchSource(source, context), { filename: workbenchPath }).runInContext(context);
  const session = {
    root: rootElement, store, projectId: "project-1", timer: null, inFlight: null,
    queued: false, detached: false,
  };
  context.module.exports.setActiveSessionForTest(session);
  const first = context.module.exports.flushSave(rootElement, session);
  await Promise.resolve();
  draftRevision = 2;
  const second = context.module.exports.flushSave(rootElement, session);
  resolveFirst({});
  await Promise.all([first, second]);
  return {
    save_calls: saveCalls,
    saved_draft_revisions: saveCalls === 2 ? [1, 2] : [1],
    pending_timers: timers.filter(Boolean).length,
  };
}

async function saveFailureBlocksPreview() {
  let saveCalls = 0; let previewCalls = 0; let disposed = false;
  const fetch = async (url) => {
    if (url.endsWith("/save")) {
      saveCalls += 1;
      return { ok: false, status: 400, json: async () => ({ error: { message: "invalid draft" } }) };
    }
    if (url.endsWith("/preview")) {
      previewCalls += 1;
      return { ok: true, status: 200, json: async () => ({ preview: preview("project-1", 3, "stale") }) };
    }
    throw new Error(`unexpected fetch ${url}`);
  };
  const { createRefinedBlastStore } = loadState(fetch);
  const store = createRefinedBlastStore(storeOptions("project-1", 3, fetch));
  store.updateDraft((draft) => { draft.scenario_kind = "internal"; });
  const placeholder = new FakeElement("span");
  const canvas = new FakeElement("div"); canvas.append(placeholder);
  const status = new FakeElement("span");
  const rootElement = {
    querySelector(selector) {
      if (selector === "[data-refined-preview-canvas]") return canvas;
      if (selector === "#refinedBlastPreviewStatus") return status;
      if (selector === "[data-refined-preview-counts]") return new FakeElement("div");
      return new FakeElement("button");
    },
  };
  const context = vm.createContext({
    module: { exports: {} }, structuredClone, JSON, Object, Array, Promise, Set, Map,
    setTimeout, clearTimeout, AbortController,
    document: { createElement: (tag) => new FakeElement(tag) },
    window: { fetch }, createRefinedBlastStore() {}, renderSchemaFields() {}, renderRefinedBlastPreview() {},
  });
  const source = fs.readFileSync(workbenchPath, "utf8")
    .replace('import { createRefinedBlastStore, renderSchemaFields } from "./refined_blast_state.js";', "")
    .replace('import { renderRefinedBlastPreview } from "./refined_blast_viewer.js";', "")
    .replace(/export function /g, "function ")
    .concat("\nfunction setActiveSessionForTest(session) { activeSession = session; mountedRoot = session.root; }\nmodule.exports = { refreshPreview, setActiveSessionForTest };\n");
  new vm.Script(prepareWorkbenchSource(source, context), { filename: workbenchPath }).runInContext(context);
  const session = {
    root: rootElement, token: 1, store, projectId: "project-1", timer: null,
    inFlight: null, flushPromise: null, queued: false, detached: false, fetch,
    persistedDraftRevision: 0, saveError: null, previewAbortController: null,
    viewer: { dispose() { disposed = true; } },
  };
  context.module.exports.setActiveSessionForTest(session);
  await context.module.exports.refreshPreview(rootElement, session);
  return { save_calls: saveCalls, preview_calls: previewCalls, old_viewer_disposed: disposed };
}

async function backgroundSaveFailureClearsPreview(statusCode) {
  let saveCalls = 0; let previewCalls = 0; let disposed = false;
  const timers = [];
  const fetch = async (url) => {
    if (url.endsWith("/save")) {
      saveCalls += 1;
      return {
        ok: false, status: statusCode,
        json: async () => statusCode === 409 ? ({ conflict: true }) : ({ error: { message: "invalid" } }),
      };
    }
    if (url.endsWith("/preview")) { previewCalls += 1; throw new Error("stale preview requested"); }
    throw new Error(`unexpected fetch ${url}`);
  };
  const { createRefinedBlastStore } = loadState(fetch);
  const store = createRefinedBlastStore(storeOptions("project-1", 3, fetch));
  const canvas = new FakeElement("div");
  const actionStatus = new FakeElement("span");
  const rootElement = {
    querySelector(selector) {
      if (selector === "[data-refined-preview-canvas]") return canvas;
      if (selector === "[data-refined-preview-counts]") return new FakeElement("div");
      if (selector === "#refinedBlastPreviewStatus") return new FakeElement("span");
      if (selector === "[data-refined-action-status]" || selector === "[data-refined-save-summary]") return actionStatus;
      return new FakeElement("button");
    },
  };
  const context = vm.createContext({
    module: { exports: {} }, structuredClone, JSON, Object, Array, Promise, Set, Map,
    setTimeout(callback) { timers.push(callback); return timers.length - 1; },
    clearTimeout(id) { timers[id] = null; }, AbortController,
    document: { createElement: (tag) => new FakeElement(tag) },
    window: { fetch }, createRefinedBlastStore() {}, renderSchemaFields() {}, renderRefinedBlastPreview() {},
  });
  const source = fs.readFileSync(workbenchPath, "utf8")
    .replace('import { createRefinedBlastStore, renderSchemaFields } from "./refined_blast_state.js";', "")
    .replace('import { renderRefinedBlastPreview } from "./refined_blast_viewer.js";', "")
    .replace(/export function /g, "function ")
    .concat("\nfunction setActiveSessionForTest(session) { activeSession = session; mountedRoot = session.root; }\nmodule.exports = { scheduleAutosave, setActiveSessionForTest };\n");
  new vm.Script(prepareWorkbenchSource(source, context), { filename: workbenchPath }).runInContext(context);
  const session = {
    root: rootElement, token: 1, store, projectId: "project-1", timer: null,
    inFlight: null, flushPromise: null, queued: false, detached: false, fetch,
    persistedDraftRevision: 0, saveError: null, previewAbortController: null,
    viewer: { dispose() { disposed = true; } },
  };
  context.module.exports.setActiveSessionForTest(session);
  store.updateDraft((draft) => { draft.scenario_kind = "internal"; });
  context.module.exports.scheduleAutosave(rootElement, session);
  const callback = timers.find(Boolean); await callback();
  for (let index = 0; index < 6; index += 1) await Promise.resolve();
  await new Promise((resolve) => setImmediate(resolve));
  return { save_calls: saveCalls, preview_calls: previewCalls, old_viewer_disposed: disposed, save_status_is_failure: actionStatus.textContent === "草稿保存失败" };
}

async function runCase(name) {
  if (name === "guard-matrix") return guardMatrix();
  if (name === "viewer-local") return viewerLocal();
  if (name === "dispose") return dispose();
  if (name === "viewer-primitives") return viewerPrimitives();
  if (name === "viewer-fluid-domain-presentation") return viewerFluidDomainPresentation();
  if (name === "viewer-layered-proxy-styles") return viewerLayeredProxyStyles();
  if (name === "viewer-blast-source-editor") return viewerBlastSourceEditor();
  if (name === "workbench-request") return workbenchRequest();
  if (name === "flush-before-preview") return flushBeforePreview();
  if (name === "save-failure-blocks-preview") return saveFailureBlocksPreview();
  if (name === "background-save-400") return backgroundSaveFailureClearsPreview(400);
  if (name === "background-save-409") return backgroundSaveFailureClearsPreview(409);
  throw new Error(`unknown case: ${name}`);
}

runCase(process.argv[2])
  .then((result) => process.stdout.write(`${JSON.stringify(result)}\n`))
  .catch((error) => { console.error(error.stack); process.exitCode = 1; });
