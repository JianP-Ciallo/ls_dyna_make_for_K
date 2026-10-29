const fs = require("fs");
const path = require("path");
const vm = require("vm");

const baseUrl = process.argv[2];
if (!baseUrl) throw new Error("base URL is required");

const root = path.resolve(__dirname, "..", "..");
const statePath = path.join(root, "lsprepost_mcp", "web", "static", "refined_blast_state.js");
const workbenchPath = path.join(root, "lsprepost_mcp", "web", "static", "refined_blast_workbench.js");
const persistencePath = path.join(root, "lsprepost_mcp", "web", "static", "refined_blast_persistence.js");
const appPath = path.join(root, "lsprepost_mcp", "web", "static", "app.js");
const nativeFetch = globalThis.fetch;

function dataName(name) {
  return name.slice(5).replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
}

function selectorAttribute(selector) {
  const match = /^\[([^=\]]+)(?:="([^"]*)")?\]$/.exec(selector);
  return match ? { name: match[1], value: match[2] } : null;
}

class MiniElement {
  constructor(tagName, ownerDocument) {
    this.tagName = String(tagName).toUpperCase();
    this.ownerDocument = ownerDocument;
    this.parentNode = null;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.listeners = new Map();
    this.className = "";
    this.id = "";
    this.type = "";
    this.value = "";
    this.checked = false;
    this.selected = false;
    this.disabled = false;
    this.textContent = "";
    this.style = {};
    this.classList = {
      add: (...names) => {
        const current = new Set(this.className.split(/\s+/).filter(Boolean));
        for (const name of names) current.add(name);
        this.className = [...current].join(" ");
      },
      remove: (...names) => {
        const removed = new Set(names);
        this.className = this.className.split(/\s+/).filter((name) => name && !removed.has(name)).join(" ");
      },
      contains: (name) => this.className.split(/\s+/).includes(name),
      toggle: (name, force) => {
        const present = this.classList.contains(name);
        const next = force === undefined ? !present : Boolean(force);
        if (next) this.classList.add(name); else this.classList.remove(name);
        return next;
      },
    };
  }

  set innerHTML(source) {
    this.children = [];
    const expression = /<([a-zA-Z0-9-]+)([^>]*)>/g;
    for (const match of source.matchAll(expression)) {
      const child = new MiniElement(match[1], this.ownerDocument);
      const attributes = match[2];
      for (const attribute of attributes.matchAll(/([:\w-]+)(?:="([^"]*)")?/g)) {
        const name = attribute[1];
        if (name === match[1]) continue;
        child.setAttribute(name, attribute[2] === undefined ? "" : attribute[2]);
      }
      if (/\sdisabled(?:\s|>|$)/.test(`${attributes}>`)) child.disabled = true;
      if (/\schecked(?:\s|>|$)/.test(`${attributes}>`)) child.checked = true;
      this.append(child);
    }
  }

  get innerHTML() { return ""; }

  setAttribute(name, value) {
    const text = String(value);
    this.attributes[name] = text;
    if (name === "id") this.id = text;
    else if (name === "class") this.className = text;
    else if (name === "value") this.value = text;
    else if (name === "disabled") this.disabled = true;
    else if (name === "checked") this.checked = true;
    else if (name.startsWith("data-")) this.dataset[dataName(name)] = text;
  }

  getAttribute(name) {
    if (name === "id") return this.id || null;
    if (name === "class") return this.className || null;
    if (name.startsWith("data-")) return this.dataset[dataName(name)] ?? null;
    return this.attributes[name] ?? null;
  }

  append(...nodes) {
    for (const node of nodes.flat()) {
      if (!node) continue;
      if (node.tagName === "#FRAGMENT") {
        this.append(...node.children);
        continue;
      }
      if (node.parentNode) node.parentNode.children = node.parentNode.children.filter((row) => row !== node);
      node.parentNode = this;
      this.children.push(node);
      if (this.tagName === "SELECT" && node.tagName === "OPTION" && (node.selected || !this.value)) {
        this.value = node.value;
      }
    }
  }

  appendChild(node) { this.append(node); return node; }

  replaceChildren(...nodes) {
    for (const child of this.children) child.parentNode = null;
    this.children = [];
    this.append(...nodes);
  }

  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }

  async dispatch(type, detail = {}) {
    if (type === "click" && this.disabled) return;
    const event = { type, target: this, currentTarget: this, preventDefault() {}, ...detail };
    for (const listener of this.listeners.get(type) ?? []) await listener(event);
  }

  click() { return this.dispatch("click"); }

  focus() { this.ownerDocument.activeElement = this; }

  matches(selector) {
    if (selector.startsWith("#")) return this.id === selector.slice(1);
    if (selector.startsWith(".")) return this.classList.contains(selector.slice(1));
    const attribute = selectorAttribute(selector);
    if (attribute) {
      const actual = attribute.name.startsWith("data-")
        ? this.dataset[dataName(attribute.name)]
        : this.getAttribute(attribute.name);
      return actual !== undefined && actual !== null && (attribute.value === undefined || actual === attribute.value);
    }
    return this.tagName.toLowerCase() === selector.toLowerCase();
  }

  descendants() {
    return this.children.flatMap((child) => [child, ...child.descendants()]);
  }

  querySelector(selector) {
    if (selector === ".refined-blast-validation-panel .summary") {
      return this.descendants().find((node) => node.matches("[data-refined-validation-status]")) ?? null;
    }
    return this.descendants().find((node) => node.matches(selector)) ?? null;
  }

  querySelectorAll(selector) {
    return this.descendants().filter((node) => node.matches(selector));
  }
}

class MiniDocument {
  constructor() {
    this.activeElement = null;
    this.byId = new Map();
    this.listeners = new Map();
    this.body = new MiniElement("body", this);
  }

  createElement(tagName) { return new MiniElement(tagName, this); }

  createDocumentFragment() { return new MiniElement("#fragment", this); }

  getElementById(id) {
    const inTree = this.body.descendants().find((node) => node.id === id);
    if (inTree) return inTree;
    if (!this.byId.has(id)) {
      const element = this.createElement("div");
      element.id = id;
      this.byId.set(id, element);
      this.body.append(element);
    }
    return this.byId.get(id);
  }

  querySelector(selector) { return this.body.querySelector(selector); }

  querySelectorAll(selector) { return this.body.querySelectorAll(selector); }

  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }
}

function makeBrowser() {
  const document = new MiniDocument();
  const initialElements = {
    legacyWorkbenchRoot: "main",
    refinedBlastWorkbenchRoot: "main",
    openRefinedBlastWorkbench: "button",
  };
  for (const [id, tag] of Object.entries(initialElements)) {
    const element = document.createElement(tag);
    element.id = id;
    if (id === "refinedBlastWorkbenchRoot") element.classList.add("hidden");
    document.byId.set(id, element);
    document.body.append(element);
  }

  const windowListeners = new Map();
  const location = { pathname: "/", search: "?viewer=canvas" };
  const entries = ["/?viewer=canvas"];
  let cursor = 0;

  function applyLocation(raw) {
    const url = new URL(raw, baseUrl);
    location.pathname = url.pathname;
    location.search = url.search;
  }

  const window = {
    location,
    confirm() { return false; },
    addEventListener(type, listener) {
      if (!windowListeners.has(type)) windowListeners.set(type, []);
      windowListeners.get(type).push(listener);
    },
    dispatchEvent(event) {
      for (const listener of windowListeners.get(event.type) ?? []) listener(event);
      return true;
    },
  };

  const history = {
    pushState(_state, _unused, raw) {
      entries.splice(cursor + 1);
      entries.push(String(raw));
      cursor = entries.length - 1;
      applyLocation(raw);
    },
    replaceState(_state, _unused, raw) {
      entries[cursor] = String(raw);
      applyLocation(raw);
    },
    back() {
      if (cursor === 0) return;
      cursor -= 1;
      applyLocation(entries[cursor]);
      window.dispatchEvent(new PopStateEvent("popstate"));
    },
    forward() {
      if (cursor + 1 >= entries.length) return;
      cursor += 1;
      applyLocation(entries[cursor]);
      window.dispatchEvent(new PopStateEvent("popstate"));
    },
    entries,
  };
  window.history = history;
  return { document, window, history };
}

class PopStateEvent {
  constructor(type) { this.type = type; }
}

function sleep(milliseconds) { return new Promise((resolve) => setTimeout(resolve, milliseconds)); }

async function waitFor(predicate, label, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = predicate();
    if (value) return value;
    await sleep(10);
  }
  throw new Error(`timed out waiting for ${label}`);
}

async function main() {
  const { document, window, history } = makeBrowser();
  const fetchRecords = [];
  let delayedProjectGet = null;
  let viewerDisposeCount = 0;

  async function realHttpFetch(input, init = {}) {
    const absolute = new URL(typeof input === "string" ? input : input.url, baseUrl).href;
    const response = await nativeFetch(absolute, init);
    const requestPath = new URL(absolute).pathname + new URL(absolute).search;
    const delay = delayedProjectGet;
    if ((init.method ?? "GET") === "GET" && delay?.path === requestPath) {
      delay.markStarted();
      await delay.release;
      if (delayedProjectGet === delay) delayedProjectGet = null;
    }
    let payload = null;
    try { payload = await response.clone().json(); } catch (_error) {}
    fetchRecords.push({
      method: init.method ?? "GET",
      path: requestPath,
      status: response.status,
      request: init.body ? JSON.parse(init.body) : null,
      response: payload,
    });
    return response;
  }

  const context = vm.createContext({
    AbortController,
    Array,
    Date,
    Error,
    JSON,
    Map,
    Math,
    Number,
    Object,
    PopStateEvent,
    Promise,
    Set,
    String,
    URL,
    URLSearchParams,
    clearTimeout,
    console,
    document,
    fetch: realHttpFetch,
    history,
    setTimeout,
    structuredClone,
    window,
  });
  window.fetch = realHttpFetch;

  const stateModule = new vm.SourceTextModule(fs.readFileSync(statePath, "utf8"), {
    context,
    identifier: statePath,
  });
  const viewerModule = new vm.SyntheticModule(["renderRefinedBlastPreview"], function initialize() {
    this.setExport("renderRefinedBlastPreview", (_container, _payload) => ({
      update() {},
      dispose() { viewerDisposeCount += 1; },
      fitView() {},
      setLayerVisible() {},
      getCountBadges() { return []; },
    }));
  }, { context, identifier: "refined_blast_viewer.js" });
  const workbenchSource = `${fs.readFileSync(workbenchPath, "utf8")}\nexport function __runtimeState() { return refinedBlastStore?.getState?.() ?? null; }\n`;
  const workbenchModule = new vm.SourceTextModule(workbenchSource, {
    context,
    identifier: workbenchPath,
  });
  const persistenceModule = new vm.SourceTextModule(fs.readFileSync(persistencePath, "utf8"), {
    context,
    identifier: persistencePath,
  });
  await stateModule.link(() => { throw new Error("state module has no imports"); });
  await viewerModule.link(() => {});
  await persistenceModule.link(() => { throw new Error("persistence module has no imports"); });
  const httpModule = new vm.SourceTextModule(fs.readFileSync(path.join(path.dirname(workbenchPath), "refined_blast_http.js"), "utf8"), { context });
  const autosaveModule = new vm.SourceTextModule(fs.readFileSync(path.join(path.dirname(workbenchPath), "refined_blast_autosave.js"), "utf8"), { context });
  await httpModule.link(() => { throw new Error("HTTP module has no imports"); });
  await autosaveModule.link((specifier) => {
    if (specifier === "./refined_blast_persistence.js") return persistenceModule;
    throw new Error(`unexpected autosave import: ${specifier}`);
  });
  await workbenchModule.link((specifier) => {
    if (specifier === "./refined_blast_persistence.js") return persistenceModule;
    if (specifier === "./refined_blast_http.js") return httpModule;
    if (specifier === "./refined_blast_autosave.js") return autosaveModule;
    if (specifier === "./refined_blast_state.js") return stateModule;
    if (specifier === "./refined_blast_viewer.js") return viewerModule;
    throw new Error(`unexpected workbench import: ${specifier}`);
  });
  await stateModule.evaluate();
  await viewerModule.evaluate();
  await persistenceModule.evaluate();
  await workbenchModule.evaluate();

  let appSource = fs.readFileSync(appPath, "utf8");
  appSource = appSource.replace(
    "function showError(error) {",
    "function showError(error) { globalThis.__refinedAppLastError = error?.stack ?? error?.message ?? String(error);",
  );
  appSource = appSource.replace(
    "boot().catch(showError);",
    "globalThis.__refinedApp = { boot, setupRefinedBlastWorkbenchRoute, showRefinedBlastWorkbench, showLegacyWorkbench, refinedBlastProjectIdFromLocation };",
  );
  const appScript = new vm.Script(appSource, {
    filename: appPath,
    importModuleDynamically(specifier) {
      if (specifier === "/refined_blast_workbench.js") return workbenchModule;
      if (specifier === "/refined_blast_persistence.js") return persistenceModule;
      throw new Error(`unexpected app import: ${specifier}`);
    },
  });
  appScript.runInContext(context);
  context.__refinedApp.setupRefinedBlastWorkbenchRoute();

  const browserFlow = ["legacy-entry"];
  await document.getElementById("openRefinedBlastWorkbench").click();
  const refinedRoot = document.getElementById("refinedBlastWorkbenchRoot");
  try {
    await waitFor(() => refinedRoot.querySelector("[data-refined-asset]"), "real capability and asset controls");
  } catch (error) {
    const requestSummary = fetchRecords.map(({ method, path, status }) => ({ method, path, status }));
    const previewStatus = refinedRoot.querySelector("#refinedBlastPreviewStatus")?.textContent ?? null;
    const legacyError = document.getElementById("result")?.textContent ?? null;
    throw new Error(`${error.message}; preview_status=${JSON.stringify(previewStatus)}; legacy_error=${JSON.stringify(legacyError)}; app_error=${JSON.stringify(context.__refinedAppLastError ?? null)}; requests=${JSON.stringify(requestSummary)}`);
  }
  browserFlow.push("capabilities", "assets");
  const openProviderStep = async () => {
    const button = await waitFor(() => refinedRoot.querySelector('[data-refined-section="7"]'), "guided provider step");
    await button.click();
    return waitFor(() => refinedRoot.querySelector("[data-refined-provider]"), "provider control in guided step");
  };

  let asset = refinedRoot.querySelector("[data-refined-asset]");
  const assetOptions = asset.children.map((option) => option.value);
  if (assetOptions.length < 2) throw new Error("real asset contract must expose at least two assets");
  asset.value = assetOptions[1];
  await asset.dispatch("change");
  const structureStep = await waitFor(() => refinedRoot.querySelector('[data-refined-section="2"]'), "guided structure step");
  await structureStep.click();
  let system = await waitFor(() => refinedRoot.querySelector("[data-refined-structural-system]"), "structural system in guided step");
  if (!system || !system.value) throw new Error("real asset contract did not produce a structural system");
  const systemOptions = system.children.map((option) => option.value);
  if (systemOptions.length < 2) throw new Error("selected real asset must expose two structural systems");
  system.value = systemOptions[1];
  await system.dispatch("change");
  const projectASystem = system.value;
  let provider = await openProviderStep();
  provider.value = "lbe_segment";
  await provider.dispatch("change");

  await refinedRoot.querySelector("[data-refined-save]").click();
  const createRecord = await waitFor(
    () => fetchRecords.find((record) => record.method === "POST" && record.path === "/api/refined-building-blast/projects" && record.status === 200),
    "real HTTP project create",
  );
  browserFlow.push("create");
  const projectAStored = createRecord.response.result.project;
  const projectAId = projectAStored.project_id;
  const projectAScenario = projectAStored.project.scenario_set[0].scenario_id;
  if (!window.location.search.includes(encodeURIComponent(projectAId))) throw new Error("created project identity was not persisted in the URL");

  await refinedRoot.querySelector("[data-refined-save]").click();
  await waitFor(
    () => fetchRecords.find((record) => record.path.endsWith(`/${projectAId}/save`) && record.status === 200),
    "real HTTP project save",
  );
  browserFlow.push("save");

  await refinedRoot.querySelector("[data-refined-preview]").click();
  await waitFor(
    () => fetchRecords.find((record) => record.path.endsWith(`/${projectAId}/preview`) && record.status === 200),
    "real HTTP preview",
  );
  browserFlow.push("preview");

  await refinedRoot.querySelector("[data-refined-validate]").click();
  const validationRecord = await waitFor(
    () => fetchRecords.find((record) => record.path.endsWith(`/${projectAId}/validate`) && record.status === 200),
    "real HTTP validation",
  );
  browserFlow.push("validate");
  const warningCount = validationRecord.response.result.validation.findings.filter((finding) => finding.severity === "warning").length;
  for (let index = 0; index < warningCount; index += 1) {
    const acknowledgement = await waitFor(
      () => refinedRoot.querySelector("[data-refined-acknowledge]"),
      `warning acknowledgement ${index + 1}`,
    );
    await acknowledgement.click();
  }
  await waitFor(
    () => fetchRecords.filter((record) => record.path.endsWith(`/${projectAId}/acknowledgements`) && record.status === 200).length === warningCount,
    "all real HTTP warning acknowledgements",
  );
  browserFlow.push("acknowledge");

  await waitFor(() => !refinedRoot.querySelector("[data-refined-generate]").disabled, "enabled generation gate");
  await refinedRoot.querySelector("[data-refined-generate]").click();
  const generationRecord = await waitFor(
    () => fetchRecords.find((record) => record.path.endsWith(`/${projectAId}/generate`) && record.status === 200),
    "real HTTP generation",
    30000,
  );
  browserFlow.push("generate");
  const generated = generationRecord.response.result;
  const generatedState = workbenchModule.namespace.__runtimeState();
  const generationUi = {
    state_revision: generatedState?.revision,
    artifact_revision: generated.artifact.revision,
    validation_invalidated: generatedState?.validation === null && generatedState?.generation_gate === null,
    open_enabled: refinedRoot.querySelector("[data-refined-open-lsprepost]")?.disabled === false,
    solve_enabled: refinedRoot.querySelector("[data-refined-launch-lsdyna]")?.disabled === false,
  };
  if (generationUi.state_revision !== generationUi.artifact_revision
      || !generationUi.validation_invalidated || !generationUi.open_enabled || !generationUi.solve_enabled) {
    throw new Error(`production browser did not reconcile generation: ${JSON.stringify(generationUi)}`);
  }
  const artifactPath = `/api/refined-building-blast/projects/${encodeURIComponent(projectAId)}/artifacts/${encodeURIComponent(generated.artifact.scenario_id)}/${generated.artifact.revision}/${generated.package_fingerprint}`;
  const artifactResponse = await realHttpFetch(artifactPath, { headers: { Accept: "application/json" } });
  if (!artifactResponse.ok) throw new Error(`artifact read failed: ${artifactResponse.status}`);
  const artifactEnvelope = await artifactResponse.json();
  const artifactRead = artifactEnvelope.result;
  browserFlow.push("artifact-read");

  const parsedProjectId = context.__refinedApp.refinedBlastProjectIdFromLocation();
  if (parsedProjectId !== projectAId) throw new Error("production app did not parse the persisted URL identity");
  await context.__refinedApp.showRefinedBlastWorkbench({ updateHistory: false, projectId: parsedProjectId, restoreProject: true });
  await waitFor(
    () => fetchRecords.filter((record) => record.method === "GET" && record.path.endsWith(`/projects/${projectAId}`) && record.status === 200).length >= 1,
    "URL project GET restore",
  );
  const reloadAssetId = refinedRoot.querySelector("[data-refined-asset]")?.value;
  const reloadStructureStep = await waitFor(() => refinedRoot.querySelector('[data-refined-section="2"]'), "restored structure step");
  await reloadStructureStep.click();
  const reloadSystemId = (await waitFor(
    () => refinedRoot.querySelector("[data-refined-structural-system]"),
    "restored structural system",
  )).value;
  await openProviderStep();
  await waitFor(() => refinedRoot.querySelector("[data-refined-provider]")?.value === "lbe_segment", "restored provider state");
  browserFlow.push("reload-get");

  history.back();
  await waitFor(() => refinedRoot.children.length === 0, "back navigation unmount");
  browserFlow.push("back-unmount");
  history.forward();
  await openProviderStep();
  await waitFor(() => refinedRoot.querySelector("[data-refined-provider]")?.value === "lbe_segment", "forward navigation remount");
  browserFlow.push("forward-remount");

  const capabilities = fetchRecords.find((record) => record.path === "/api/refined-building-blast/capabilities").response.result;
  const assets = fetchRecords.find((record) => record.path === "/api/refined-building-blast/assets").response.result.assets;
  const projectBAsset = assets[0];
  const projectBId = `real-http-project-b-${Date.now()}`;
  const projectBDraft = structuredClone(capabilities.default_scenario_draft);
  projectBDraft.scenario_id = `${projectBId}-scenario`;
  const lbe = capabilities.providers.find((row) => row.provider_id === "lbe_segment");
  projectBDraft.load_provider = { provider_id: "lbe_segment", provider_input: structuredClone(lbe.default_input) };
  const timestamp = new Date().toISOString();
  const projectBPayload = {
    schema_version: "refined_blast_create@1",
    building: {
      asset_id: projectBAsset.asset_id,
      legacy_geometry: structuredClone(projectBAsset.default_geometry),
      structural_system: projectBAsset.default_structural_system,
      fidelity_profile: projectBAsset.default_fidelity_profile,
      mesh_profile: projectBAsset.default_mesh_profile,
      generation_options: {},
      material_overrides: {},
    },
    project: {
      schema_version: "refined_building_blast@1",
      project_id: projectBId,
      preset_reference: "browser_draft",
      preset_version: "1",
      project_overrides: {},
      expert_extensions: {},
      scenario_set: [projectBDraft],
      confirmation_records: [],
      provenance: {},
      created_at: timestamp,
      updated_at: timestamp,
    },
  };
  const projectBCreate = await realHttpFetch("/api/refined-building-blast/projects", {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(projectBPayload),
  });
  if (!projectBCreate.ok) throw new Error(`project B create failed: ${projectBCreate.status} ${await projectBCreate.text()}`);
  const projectBEnvelope = await projectBCreate.json();
  const projectBStored = projectBEnvelope.result.project;
  if (projectBStored.project_id !== projectBId) throw new Error("project B create returned a different identity");

  let markDelayedStarted;
  let releaseDelayed;
  const delayedStarted = new Promise((resolve) => { markDelayedStarted = resolve; });
  const delayedRelease = new Promise((resolve) => { releaseDelayed = resolve; });
  delayedProjectGet = {
    path: `/api/refined-building-blast/projects/${projectAId}`,
    markStarted: markDelayedStarted,
    release: delayedRelease,
  };
  history.replaceState({ workspace: "refined-blast" }, "", `/refined-building-blast?project_id=${encodeURIComponent(projectAId)}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
  await delayedStarted;
  history.replaceState({ workspace: "refined-blast" }, "", `/refined-building-blast?project_id=${encodeURIComponent(projectBStored.project_id)}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
  const projectBGet = await waitFor(
    () => [...fetchRecords].reverse().find((record) => record.method === "GET" && record.path.endsWith(`/projects/${projectBStored.project_id}`) && record.status === 200),
    "project B URL restore",
  );
  await waitFor(() => refinedRoot.querySelector("[data-refined-asset]")?.value === projectBAsset.asset_id, "project B asset restore");
  releaseDelayed();
  await sleep(50);
  const stateAfterDelayedA = workbenchModule.namespace.__runtimeState();
  const urlIsolation = {
    project_id: projectBGet.response.result.project.project_id,
    asset_id: refinedRoot.querySelector("[data-refined-asset]").value,
    delayed_a_cannot_replace_b: stateAfterDelayedA?.project_id === projectBStored.project_id
      && refinedRoot.querySelector("[data-refined-asset]")?.value === projectBAsset.asset_id,
  };
  const projectAGetCount = fetchRecords.filter((record) => record.method === "GET" && record.path.endsWith(`/projects/${projectAId}`)).length;
  history.replaceState({ workspace: "refined-blast" }, "", `/refined-building-blast?project_id=${encodeURIComponent(projectAId)}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
  await waitFor(() => refinedRoot.querySelector("[data-refined-asset]")?.value === projectAStored.project.building_reference.asset_id, "project A URL return");
  const projectAReturnGet = await waitFor(
    () => {
      const rows = fetchRecords.filter((record) => record.method === "GET" && record.path.endsWith(`/projects/${projectAId}`) && record.status === 200);
      return rows.length > projectAGetCount ? rows.at(-1) : null;
    },
    "project A URL return GET",
  );
  urlIsolation.returned_project_id = projectAReturnGet.response.result.project.project_id;

  const crossGet = await realHttpFetch(`/api/refined-building-blast/projects/${projectAId}?project_id=${encodeURIComponent(projectBId)}`, {
    headers: { Accept: "application/json" },
  });
  const crossGenerate = await realHttpFetch(`/api/refined-building-blast/projects/${projectBId}/generate`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ expected_revision: generated.artifact.revision }),
  });
  const crossArtifact = await realHttpFetch(`/api/refined-building-blast/projects/${projectBId}/artifacts/${encodeURIComponent(generated.artifact.scenario_id)}/${generated.artifact.revision}/${generated.package_fingerprint}`, {
    headers: { Accept: "application/json" },
  });

  const currentProjectA = await (await realHttpFetch(`/api/refined-building-blast/projects/${projectAId}`, { headers: { Accept: "application/json" } })).json();
  const directSave = await realHttpFetch(`/api/refined-building-blast/projects/${projectAId}/save`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({
      expected_revision: currentProjectA.result.project.revision,
      draft: currentProjectA.result.project.project.scenario_set[0],
    }),
  });
  if (!directSave.ok) throw new Error(`direct competing save failed: ${directSave.status}`);
  await openProviderStep();
  provider = refinedRoot.querySelector("[data-refined-provider]");
  provider.value = "imported_pressure_history";
  await provider.dispatch("change");
  try {
    await refinedRoot.querySelector("[data-refined-save]").click();
  } catch (error) {
    if (error?.message !== "draft save conflict") throw error;
  }
  const staleSave = await waitFor(
    () => [...fetchRecords].reverse().find((record) => record.path.endsWith(`/${projectAId}/save`) && record.status === 409),
    "browser stale CAS conflict",
  );
  const localState = workbenchModule.namespace.__runtimeState();
  const localProvider = refinedRoot.querySelector("[data-refined-provider]").value;

  const reloadGet = [...fetchRecords].reverse().find(
    (record) => record.method === "GET" && record.path.endsWith(`/projects/${projectAId}`) && record.status === 200,
  );
  const externalRequests = fetchRecords.filter((record) => /\/(action-confirmations|open-lsprepost|launch-lsdyna)$/.test(record.path));
  process.stdout.write(`${JSON.stringify({
    transport: "real-global-fetch",
    browser_flow: browserFlow,
    project_a: {
      project_id: projectAId,
      scenario_id: projectAScenario,
      asset_id: projectAStored.project.building_reference.asset_id,
    },
    project_b: {
      project_id: projectBStored.project_id,
      scenario_id: projectBStored.project.scenario_set[0].scenario_id,
      asset_id: projectBStored.project.building_reference.asset_id,
    },
    artifact_read: {
      project_id: artifactRead.artifact.project_id,
      scenario_id: artifactRead.artifact.scenario_id,
      revision: artifactRead.artifact.revision,
      external_program_started: artifactRead.package.external_program_started,
    },
    generation_ui: generationUi,
    url_isolation: urlIsolation,
    reload: {
      project_id: reloadGet.response.result.project.project_id,
      scenario_id: reloadGet.response.result.project.project.scenario_set[0].scenario_id,
      asset_id: reloadAssetId,
      structural_system: reloadSystemId,
      expected_structural_system: projectASystem,
    },
    stale_save: {
      status: staleSave.status,
      local_scenario_id: localState?.draft?.scenario_id,
      local_provider_id: localState?.draft?.load_provider?.provider_id ?? localProvider,
    },
    lifecycle: { viewer_dispose_count: viewerDisposeCount },
    cross_project_get: { status: crossGet.status },
    cross_project_generate: { status: crossGenerate.status },
    cross_project_artifact: { status: crossArtifact.status },
    external_action_requests: externalRequests.map((record) => record.path),
  })}\n`);
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
