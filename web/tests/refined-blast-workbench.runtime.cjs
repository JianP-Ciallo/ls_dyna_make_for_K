const { prepareWorkbenchSource } = require("./workbench-dependencies.cjs");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.resolve(__dirname, "..", "..");
const statePath = path.join(root, "lsprepost_mcp", "web", "static", "refined_blast_state.js");
const workbenchPath = path.join(root, "lsprepost_mcp", "web", "static", "refined_blast_workbench.js");

function loadModule() {
  const stateSource = fs.readFileSync(statePath, "utf8").replace(/export function /g, "function ")
    .concat("\nmodule.exports = { createRefinedBlastStore, renderSchemaFields };\n");
  const stateContext = vm.createContext({ module: { exports: {} }, structuredClone, JSON, Object, Array, Set, Map });
  new vm.Script(stateSource, { filename: statePath }).runInContext(stateContext);
  let source = fs.readFileSync(workbenchPath, "utf8")
    .replace('import { createRefinedBlastStore, renderSchemaFields } from "./refined_blast_state.js";', "")
    .replace('import { renderRefinedBlastPreview } from "./refined_blast_viewer.js";', "")
    .replace(/export function /g, "function ")
    .concat("\nmodule.exports = { schemaForWorkbench, loadCapabilities, fieldBelongsInAdvanced, workbenchFieldsForStep, configuredWorkbenchSteps, renderProviderMigrationNote, buildingDefinitionPolicy };\n");
  const context = vm.createContext({
    module: { exports: {} }, structuredClone, JSON, Object, Array, Promise,
    createRefinedBlastStore: stateContext.module.exports.createRefinedBlastStore,
    renderSchemaFields: stateContext.module.exports.renderSchemaFields,
    document: { createElement() { return { append() {}, addEventListener() {}, dataset: {}, replaceChildren() {} }; }, createDocumentFragment() { return { append() {}, querySelectorAll() { return []; } }; } }
  });
  new vm.Script(prepareWorkbenchSource(source, context), { filename: workbenchPath }).runInContext(context);
  return context.module.exports;
}

async function runCase(caseName) {
  const { schemaForWorkbench, fieldBelongsInAdvanced, workbenchFieldsForStep, configuredWorkbenchSteps, renderProviderMigrationNote, buildingDefinitionPolicy } = loadModule();
  if (caseName === "building-definition-policy") {
    return {
      uncreated: buildingDefinitionPolicy({ project_id: null, building_compilation_state: "pending" }),
      saved_pending: buildingDefinitionPolicy({ project_id: "project-1", building_compilation_state: "pending" }),
      generated: buildingDefinitionPolicy({ project_id: "project-1", building_compilation_state: "compiled" }),
    };
  }
  if (caseName === "solver-complete-primary-fields") {
    return {
      tnt_mass_advanced: fieldBelongsInAdvanced("load_provider.provider_input.tnt_equivalent_mass_kg", "number"),
      charge_position_advanced: fieldBelongsInAdvanced("load_provider.provider_input.charge_position_m", "array"),
      air_cell_size_advanced: fieldBelongsInAdvanced("load_provider.provider_input.air_cell_size_m", "number"),
      ground_cell_size_advanced: fieldBelongsInAdvanced("load_provider.provider_input.ground_cell_size_m", "number")
    };
  }
  if (caseName === "selected-asset-schema") {
    const schema = schemaForWorkbench({ providers: [{ provider_id: "lbe_segment", supported_scenario_kinds: ["external"], default_input: { source: { seed: "one" } }, input_schema: { type: "object", additionalProperties: false, properties: { source: { type: "object", additionalProperties: false, properties: {} } } } }] }, [
      { asset_id: "first", allowed_structural_systems: ["steel_frame"], default_structural_system: "steel_frame" },
      { asset_id: "subway_entrance_detailed_building", allowed_structural_systems: ["rc_box"], default_structural_system: "rc_box", ui_sections_by_structural_system: { rc_box: ["rebar"] } }
    ], "subway_entrance_detailed_building");
    return {
      asset_ids: schema.assets.map((asset) => asset.asset_id),
      allowed_systems: schema.assets.find((asset) => asset.asset_id === schema.asset_id).allowed_structural_systems,
      scenario_kinds: schema.providers.lbe_segment.supported_scenario_kinds,
      rc_sections: schema.assets.find((asset) => asset.asset_id === schema.asset_id).ui_sections_by_structural_system.rc_box,
      provider_default: schema.providers.lbe_segment.default_input
    };
  }
  if (caseName === "provider-migration-note") {
    const note = renderProviderMigrationNote({
      draft: {
        scenario_id: "scenario-1",
        load_provider: { provider_id: "solver_complete_ale_fsi" },
      },
      provider_input_migrations: [{
        scenario_id: "scenario-1", provider_id: "solver_complete_ale_fsi",
        source_schema_version: "phase18.solver_blast.config@3",
        target_schema_version: "phase18.solver_blast.config@4",
      }],
    });
    return {
      visible: Boolean(note), marker: note?.dataset?.refinedMigrationSource,
      text: note?.textContent,
    };
  }
  if (caseName === "eight-step-field-routing") {
    const workbench_schema = {
      schema_version: "refined_blast.workbench_schema@1",
      sections: [
        { section_id: "building_space", step: 1, label_zh: "建筑空间与洞口" },
        { section_id: "mesh_ground", step: 6, label_zh: "网格、地面与局部加密" },
        { section_id: "blast_load", step: 7, label_zh: "载荷与爆源" },
      ],
      fields: [
        { path: "building.asset_id", section_id: "building_space", editable: true, schema: { type: "string" } },
        { path: "building.mesh_profile", section_id: "mesh_ground", editable: true, applicability: { asset_ids: ["asset"] }, schema: { type: "string" } },
        { path: "draft.load_provider.provider_input.air_cell_size_m", section_id: "mesh_ground", editable: true, applicability: { provider_ids: ["solver_complete_ale_fsi"] }, schema: { type: "number" } },
        { path: "draft.load_provider.provider_input.charge_position_m", section_id: "blast_load", editable: true, applicability: { provider_ids: ["solver_complete_ale_fsi"] }, schema: { type: "array" } },
        { path: "building.generation_options.glazing_bay_count", section_id: "nonstructural", editable: true, applicability: { asset_ids: ["subway"] }, schema: { type: "integer" } },
      ],
    };
    const schema = schemaForWorkbench({ providers: [{ provider_id: "solver_complete_ale_fsi", supported_scenario_kinds: ["external"], input_schema: { type: "object", properties: {} }, default_input: {} }], workbench_schema }, [{ asset_id: "asset", allowed_structural_systems: ["rc_frame"], default_structural_system: "rc_frame" }], "asset");
    const state = { activeSchema: schema, asset_id: "asset", building: { structural_system: "rc_frame" }, draft: { load_provider: { provider_id: "solver_complete_ale_fsi", provider_input: {} } } };
    const paths = (step) => workbenchFieldsForStep(state, step).map((field) => field.path);
    return { schema_version: schema.workbench_schema.schema_version, step_1: paths(1), step_6: paths(6), step_7: paths(7) };
  }
  if (caseName === "eight-step-default-status") {
    const activeSchema = {
      workbench_schema: {
        sections: [1, 2, 3, 4, 5, 6, 7, 8].map((step) => ({ step, section_id: `step-${step}` })),
        fields: [1, 2, 3, 4, 5, 6, 7].map((step) => ({ path: step === 1 ? "building.asset_id" : step === 2 ? "building.structural_system" : step === 6 ? "building.mesh_profile" : step === 7 ? "draft.load_provider.provider_id" : `building.generation_options.step_${step}`, section_id: `step-${step}`, editable: true, schema: { type: "string" } })),
      },
    };
    const base = { activeSchema, asset_id: "asset", building: { structural_system: "rc_frame", mesh_profile: "standard" }, draft: { load_provider: { provider_id: "solver_complete_ale_fsi", provider_input: {} } }, validation: null };
    return { before_validation: [...configuredWorkbenchSteps(base)], after_validation: [...configuredWorkbenchSteps({ ...base, validation: { fingerprint: "ok" } })] };
  }
  if (caseName === "stale-capability-load") {
    const deferred = [];
    const fetchPaths = [];
    const controls = new Map();
    const control = (key) => {
      if (!controls.has(key)) controls.set(key, { dataset: {}, disabled: false, addEventListener(type, listener) { this.listener = listener; }, replaceChildren() {} });
      return controls.get(key);
    };
    const rootFor = (name) => ({
      replaceChildren() {},
      querySelector(selector) {
        if (selector === "[data-refined-back]") return control(`${name}-back`);
        if (selector === "[data-refined-save]") return control(`${name}-save`);
        if (selector === "[data-refined-schema-panel]") return { replaceChildren() {} };
        if (selector === ".refined-blast-validation-panel .summary") return control(`${name}-summary`);
        if (selector === "#refinedBlastPreviewStatus") return control(`${name}-status`);
        return control(`${name}-${selector}`);
      }
    });
    const stateSource = fs.readFileSync(statePath, "utf8").replace("const REFINED_BLAST_API_PREFIX", "const _STATE_API_PREFIX").replace(/REFINED_BLAST_API_PREFIX/g, "_STATE_API_PREFIX").replace(/export function /g, "function ")
      .concat("\nmodule.exports = { createRefinedBlastStore, renderSchemaFields };\n");
    const issueFetch = (...args) => new Promise((resolve) => { fetchPaths.push(args[0]); deferred.push({ args, resolve }); });
    const context = vm.createContext({
      module: { exports: {} }, structuredClone, JSON, Object, Array, Promise, Set, Map, fetch: issueFetch,
      document: { createElement() { return { append() {}, addEventListener() {}, dataset: {}, replaceChildren() {}, set textContent(_) {} }; }, createDocumentFragment() { return { append() {}, querySelectorAll() { return []; } }; } },
      window: { location: { pathname: "/refined-building-blast" }, fetch: issueFetch, history: { replaceState() {} }, dispatchEvent() {} }, history: { pushState() {} }, PopStateEvent: class {}
    });
    new vm.Script(stateSource, { filename: statePath }).runInContext(context);
    let source = fs.readFileSync(workbenchPath, "utf8").replace('import { createRefinedBlastStore, renderSchemaFields } from "./refined_blast_state.js";', "").replace('import { renderRefinedBlastPreview } from "./refined_blast_viewer.js";', "").replace(/export function /g, "function ")
      .concat("\nmodule.exports = { mountRefinedBlastWorkbench, unmountRefinedBlastWorkbench };\n");
    context.createRefinedBlastStore = context.module.exports.createRefinedBlastStore;
    context.renderSchemaFields = context.module.exports.renderSchemaFields;
    context.module = { exports: {} };
    new vm.Script(prepareWorkbenchSource(source, context), { filename: workbenchPath }).runInContext(context);
    const app = context.module.exports;
    app.mountRefinedBlastWorkbench(rootFor("old"), { updateHistory: false });
    await new Promise((resolve) => setTimeout(resolve, 0));
    app.unmountRefinedBlastWorkbench();
    app.mountRefinedBlastWorkbench(rootFor("current"), { updateHistory: false });
    await new Promise((resolve) => setTimeout(resolve, 0));
    deferred[1].resolve({ ok: true, json: async () => ({ providers: [] }) });
    await new Promise((resolve) => setTimeout(resolve, 0));
    deferred[2].resolve({ ok: true, json: async () => ({ assets: [] }) });
    await new Promise((resolve) => setTimeout(resolve, 0));
    deferred[0].resolve({ ok: true, json: async () => ({ providers: [{ provider_id: "stale" }] }) });
    await new Promise((resolve) => setTimeout(resolve, 0));
    return { fetch_paths: fetchPaths };
  }
  if (caseName === "save-button") {
    const controls = new Map();
    function control(key) {
      if (!controls.has(key)) controls.set(key, { dataset: {}, disabled: false, addEventListener(type, listener) { this.listener = listener; }, replaceChildren() {} });
      return controls.get(key);
    }
    const rootElement = {
      replaceChildren() {},
      querySelector(selector) {
        if (selector === "[data-refined-back]") return control("back");
        if (selector === "[data-refined-save]") return control("save");
        if (selector === "[data-refined-schema-panel]") return { replaceChildren() {} };
        if (selector === ".refined-blast-validation-panel .summary") return control("summary");
        if (selector === "#refinedBlastPreviewStatus") return control("status");
        return control(selector);
      }
    };
    const deferred = [];
    const stateSource = fs.readFileSync(statePath, "utf8").replace("const REFINED_BLAST_API_PREFIX", "const _STATE_API_PREFIX").replace(/REFINED_BLAST_API_PREFIX/g, "_STATE_API_PREFIX").replace(/export function /g, "function ")
      .concat("\nmodule.exports = { createRefinedBlastStore, renderSchemaFields };\n");
    const context = vm.createContext({
      module: { exports: {} }, structuredClone, JSON, Object, Array, Promise, Set, Map,
      createRefinedBlastStore: undefined, renderSchemaFields: undefined,
      document: { createElement() { return { append() {}, addEventListener() {}, dataset: {}, replaceChildren() {}, set textContent(_) {} }; }, createDocumentFragment() { return { append() {}, querySelectorAll() { return []; } }; } },
      fetch: (...args) => new Promise((resolve) => deferred.push({ args, resolve })),
      window: { location: { pathname: "/refined-building-blast" }, fetch: (...args) => new Promise((resolve) => deferred.push({ args, resolve })), history: { replaceState() {} }, dispatchEvent() {} },
      history: { pushState() {} }, PopStateEvent: class {}
    });
    new vm.Script(stateSource, { filename: statePath }).runInContext(context);
    let source = fs.readFileSync(workbenchPath, "utf8")
      .replace('import { createRefinedBlastStore, renderSchemaFields } from "./refined_blast_state.js";', "")
      .replace('import { renderRefinedBlastPreview } from "./refined_blast_viewer.js";', "")
      .replace(/export function /g, "function ")
      .concat("\nmodule.exports = { mountRefinedBlastWorkbench, unmountRefinedBlastWorkbench };\n");
    context.createRefinedBlastStore = context.module.exports.createRefinedBlastStore;
    context.renderSchemaFields = context.module.exports.renderSchemaFields;
    context.module = { exports: {} };
    new vm.Script(prepareWorkbenchSource(source, context), { filename: workbenchPath }).runInContext(context);
    context.module.exports.mountRefinedBlastWorkbench(rootElement, { updateHistory: false, projectId: "project-7", revision: 4 });
    await new Promise((resolve) => setTimeout(resolve, 0));
    deferred.shift().resolve({ ok: true, json: async () => ({ providers: [] }) });
    await new Promise((resolve) => setTimeout(resolve, 0));
    deferred.shift().resolve({ ok: true, json: async () => ({ assets: [] }) });
    await new Promise((resolve) => setTimeout(resolve, 0));
    const click = controls.get("save").listener();
    const busy_before_response = controls.get("save").dataset.busy === "true";
    const save = deferred.shift();
    const request = { url: save.args[0], expected_revision: JSON.parse(save.args[1].body).expected_revision };
    save.resolve({ ok: true, status: 200, json: async () => ({ project: { revision: 5 } }) });
    await click;
    return { request, busy_before_response, busy_after_response: controls.get("save").dataset.busy === "true" };
  }
  if (caseName === "autosave-unmount") {
    const controls = new Map(); const timers = []; const requests = []; const createdElements = [];
    const control = (key) => {
      if (!controls.has(key)) controls.set(key, { dataset: {}, disabled: false, append() {}, addEventListener(type, listener) { this.listener = listener; }, replaceChildren(...children) { this.children = children; } });
      return controls.get(key);
    };
    const rootElement = { replaceChildren() {}, querySelector(selector) {
      if (selector === "[data-refined-back]") return control("back");
      if (selector === "[data-refined-save]") return control("save");
      if (selector === "[data-refined-schema-panel]") return control("panel");
      if (selector === ".refined-blast-validation-panel .summary") return control("summary");
      if (selector === "#refinedBlastPreviewStatus") return control("status"); return control(selector);
    }};
    const stateSource = fs.readFileSync(statePath, "utf8").replace("const REFINED_BLAST_API_PREFIX", "const _STATE_API_PREFIX").replace(/REFINED_BLAST_API_PREFIX/g, "_STATE_API_PREFIX").replace(/export function /g, "function ").concat("\nmodule.exports = { createRefinedBlastStore, renderSchemaFields };\n");
    const fetch = (url, options) => {
      requests.push({ url, options });
      if (url.endsWith("capabilities")) return Promise.resolve({ ok: true, json: async () => ({ providers: [{ provider_id: "lbe_segment", supported_scenario_kinds: ["external"], input_schema: { type: "object", properties: {} }, default_input: {} }, { provider_id: "imported_pressure_history", supported_scenario_kinds: ["external"], input_schema: { type: "object", properties: {} }, default_input: {} }], default_scenario_draft: { scenario_id: "one", scenario_kind: "external", building_placement: {}, load_provider: { provider_id: "lbe_segment", provider_input: {} } } }) });
      if (url.endsWith("assets")) return Promise.resolve({ ok: true, json: async () => ({ assets: [{ asset_id: "asset", default_structural_system: "rc_box", allowed_structural_systems: ["rc_box"], building_recipe_schema: { type: "object", properties: { asset_id: { type: "string" }, structural_system: { type: "string" } } } }] }) });
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ project: { revision: 5 } }) });
    };
    const context = vm.createContext({ module: { exports: {} }, structuredClone, JSON, Object, Array, Promise, Set, Map, fetch, setTimeout(fn) { timers.push(fn); return timers.length - 1; }, clearTimeout(id) { timers[id] = null; }, document: { createElement() { const element = { dataset: {}, children: [], append(...children) { this.children.push(...children); }, addEventListener(type, listener) { this.listener = listener; }, querySelectorAll() { return []; } }; createdElements.push(element); return element; }, createDocumentFragment() { return { append() {}, querySelectorAll() { return []; } }; } }, window: { location: { pathname: "/refined-building-blast" }, fetch, history: { replaceState() {} }, dispatchEvent() {} }, history: { pushState() {} }, PopStateEvent: class {} });
    new vm.Script(stateSource, { filename: statePath }).runInContext(context);
    let source = fs.readFileSync(workbenchPath, "utf8").replace('import { createRefinedBlastStore, renderSchemaFields } from "./refined_blast_state.js";', "").replace('import { renderRefinedBlastPreview } from "./refined_blast_viewer.js";', "").replace(/export function /g, "function ").concat("\nmodule.exports = { mountRefinedBlastWorkbench, unmountRefinedBlastWorkbench };\n");
    context.createRefinedBlastStore = context.module.exports.createRefinedBlastStore; context.renderSchemaFields = context.module.exports.renderSchemaFields; context.module = { exports: {} }; new vm.Script(prepareWorkbenchSource(source, context), { filename: workbenchPath }).runInContext(context);
    const app = context.module.exports; app.mountRefinedBlastWorkbench(rootElement, { updateHistory: false, projectId: "project-7", revision: 4 });
    await vm.runInContext("capabilitiesRequest", context);
    const provider = createdElements.find((child) => child.dataset?.refinedProvider === "true"); provider.value = "imported_pressure_history"; provider.listener();
    const timer = timers.find(Boolean); await timer(); await Promise.resolve();
    const saveCalls = requests.filter((row) => row.url.endsWith("/save"));
    provider.listener(); app.unmountRefinedBlastWorkbench();
    const pending = timers.filter(Boolean); for (const callback of pending) await callback();
    return { save_calls: saveCalls.length, expected_revision: JSON.parse(saveCalls[0].options.body).expected_revision, after_unmount_save_calls: requests.filter((row) => row.url.endsWith("/save")).length };
  }
  if (caseName === "cross-mount-create") {
    const controls = new Map(); const requests = []; let resolveCreate;
    const control = (key) => { if (!controls.has(key)) controls.set(key, { dataset: {}, disabled: false, append() {}, addEventListener(type, listener) { this.listener = listener; }, replaceChildren(...children) { this.children = children; } }); return controls.get(key); };
    const rootFor = (name) => ({ replaceChildren() {}, querySelector(selector) { if (selector === "[data-refined-back]") return control(`${name}-back`); if (selector === "[data-refined-save]") return control(`${name}-save`); if (selector === "[data-refined-schema-panel]") return control(`${name}-panel`); if (selector === ".refined-blast-validation-panel .summary") return control(`${name}-summary`); if (selector === "#refinedBlastPreviewStatus") return control(`${name}-status`); return control(`${name}-${selector}`); } });
    const stateSource = fs.readFileSync(statePath, "utf8").replace("const REFINED_BLAST_API_PREFIX", "const _STATE_API_PREFIX").replace(/REFINED_BLAST_API_PREFIX/g, "_STATE_API_PREFIX").replace(/export function /g, "function ").concat("\nmodule.exports = { createRefinedBlastStore, renderSchemaFields };\n");
    const fetch = (url, options) => { requests.push({ url, options }); if (url.endsWith("capabilities")) return Promise.resolve({ ok: true, json: async () => ({ providers: [{ provider_id: "lbe_segment", supported_scenario_kinds: ["external"], input_schema: { type: "object", properties: {} }, default_input: {} }], default_scenario_draft: { scenario_id: "one", scenario_kind: "external", building_placement: {}, load_provider: { provider_id: "lbe_segment", provider_input: {} } } }) }); if (url.endsWith("assets")) return Promise.resolve({ ok: true, json: async () => ({ assets: [] }) }); if (url.endsWith("/projects")) return new Promise((resolve) => { resolveCreate = resolve; }); return Promise.resolve({ ok: true, status: 200, json: async () => ({ project: { revision: 2 } }) }); };
    const context = vm.createContext({ module: { exports: {} }, structuredClone, JSON, Object, Array, Promise, Set, Map, fetch, document: { createElement() { return { dataset: {}, append() {}, addEventListener(type, listener) { this.listener = listener; }, querySelectorAll() { return []; } }; }, createDocumentFragment() { return { append() {}, querySelectorAll() { return []; } }; } }, window: { location: { pathname: "/refined-building-blast" }, fetch, history: { replaceState() {} }, dispatchEvent() {} }, history: { pushState() {} }, PopStateEvent: class {} });
    new vm.Script(stateSource, { filename: statePath }).runInContext(context); let source = fs.readFileSync(workbenchPath, "utf8").replace('import { createRefinedBlastStore, renderSchemaFields } from "./refined_blast_state.js";', "").replace('import { renderRefinedBlastPreview } from "./refined_blast_viewer.js";', "").replace(/export function /g, "function ").concat("\nmodule.exports = { mountRefinedBlastWorkbench, unmountRefinedBlastWorkbench };\n"); context.createRefinedBlastStore = context.module.exports.createRefinedBlastStore; context.renderSchemaFields = context.module.exports.renderSchemaFields; context.module = { exports: {} }; new vm.Script(prepareWorkbenchSource(source, context), { filename: workbenchPath }).runInContext(context);
    const app = context.module.exports; app.mountRefinedBlastWorkbench(rootFor("a"), { updateHistory: false }); await vm.runInContext("capabilitiesRequest", context); const aSave = control("a-save").listener(); await Promise.resolve(); app.unmountRefinedBlastWorkbench(); app.mountRefinedBlastWorkbench(rootFor("b"), { updateHistory: false, projectId: "project-b", revision: 1 }); await vm.runInContext("capabilitiesRequest", context); await control("b-save").listener(); resolveCreate({ ok: true, status: 200, json: async () => ({ project: { project_id: "project-a", revision: 1 } }) }); await aSave; const writes = requests.filter((item) => item.options?.method === "POST"); return { write_paths: writes.map((item) => item.url), create_schema_version: JSON.parse(writes[0].options.body).schema_version };
  }
  if (caseName === "save-abort-lifecycle") {
    const controls = new Map(); const saveRequests = []; let deadline = null;
    const control = (key) => {
      if (!controls.has(key)) controls.set(key, { dataset: {}, disabled: false, append() {}, addEventListener(type, listener) { this.listener = listener; }, replaceChildren() {} });
      return controls.get(key);
    };
    const rootElement = { replaceChildren() {}, querySelector(selector) {
      if (selector === "[data-refined-back]") return control("back");
      if (selector === "[data-refined-save]") return control("save");
      if (selector === "[data-refined-schema-panel]") return control("panel");
      if (selector === ".refined-blast-validation-panel .summary") return control("summary");
      if (selector === "#refinedBlastPreviewStatus") return control("status");
      return control(selector);
    }};
    const stateSource = fs.readFileSync(statePath, "utf8").replace("const REFINED_BLAST_API_PREFIX", "const _STATE_API_PREFIX").replace(/REFINED_BLAST_API_PREFIX/g, "_STATE_API_PREFIX").replace(/export function /g, "function ").concat("\nmodule.exports = { createRefinedBlastStore, renderSchemaFields };\n");
    const fetch = (url, options = {}) => {
      if (url.endsWith("capabilities")) return Promise.resolve({ ok: true, json: async () => ({ providers: [] }) });
      if (url.endsWith("assets")) return Promise.resolve({ ok: true, json: async () => ({ assets: [] }) });
      return new Promise((_resolve, reject) => {
        saveRequests.push(options);
        options.signal?.addEventListener("abort", () => {
          const error = new Error("aborted"); error.name = "AbortError"; reject(error);
        }, { once: true });
      });
    };
    const context = vm.createContext({
      module: { exports: {} }, structuredClone, JSON, Object, Array, Promise, Set, Map, AbortController,
      fetch,
      setTimeout(callback, delay) { if (delay === 10000) deadline = callback; return 91; },
      clearTimeout() {},
      document: { createElement() { return { dataset: {}, append() {}, addEventListener(type, listener) { this.listener = listener; }, querySelectorAll() { return []; } }; }, createDocumentFragment() { return { append() {}, querySelectorAll() { return []; } }; } },
      window: { location: { pathname: "/refined-building-blast" }, fetch, history: { replaceState() {} }, dispatchEvent() {} },
      history: { pushState() {} }, PopStateEvent: class {},
    });
    new vm.Script(stateSource, { filename: statePath }).runInContext(context);
    let source = fs.readFileSync(workbenchPath, "utf8").replace('import { createRefinedBlastStore, renderSchemaFields } from "./refined_blast_state.js";', "").replace('import { renderRefinedBlastPreview } from "./refined_blast_viewer.js";', "").replace(/export function /g, "function ").concat("\nmodule.exports = { mountRefinedBlastWorkbench, unmountRefinedBlastWorkbench };\n");
    context.createRefinedBlastStore = context.module.exports.createRefinedBlastStore; context.renderSchemaFields = context.module.exports.renderSchemaFields; context.module = { exports: {} }; new vm.Script(prepareWorkbenchSource(source, context), { filename: workbenchPath }).runInContext(context);
    const app = context.module.exports;
    app.mountRefinedBlastWorkbench(rootElement, { updateHistory: false, projectId: "project-7", revision: 4 });
    await vm.runInContext("capabilitiesRequest", context);
    const timed = control("save").listener().catch(() => false);
    await Promise.resolve(); const firstSignal = saveRequests[0].signal; deadline(); await timed;
    const busyAfterTimeout = control("save").dataset.busy === "true";
    const timeoutLabel = control("[data-refined-action-status]").textContent;
    deadline = null;
    const detached = control("save").listener().catch(() => false);
    await Promise.resolve(); const secondSignal = saveRequests[1].signal; app.unmountRefinedBlastWorkbench(); await detached;
    return { timeout_aborted: firstSignal.aborted, busy_after_timeout: busyAfterTimeout, timeout_label_ok: timeoutLabel === "保存超时，请重试", unmount_aborted: secondSignal.aborted };
  }
  throw new Error(`unknown case: ${caseName}`);
}
runCase(process.argv[2]).then((result) => process.stdout.write(`${JSON.stringify(result)}\n`)).catch((error) => { console.error(error.stack); process.exitCode = 1; });
