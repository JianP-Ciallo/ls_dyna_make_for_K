const { prepareWorkbenchSource } = require("./workbench-dependencies.cjs");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.resolve(__dirname, "..", "..");
const statePath = path.join(root, "lsprepost_mcp", "web", "static", "refined_blast_state.js");
const workbenchPath = path.join(root, "lsprepost_mcp", "web", "static", "refined_blast_workbench.js");

function draft(kind = "external") {
  return {
    scenario_id: "scenario-1", scenario_kind: kind,
    building_placement: {}, load_provider: {},
  };
}

function finding(severity, id, hash = `hash-${id}`) {
  return {
    finding_id: id, severity, module: "load_provider",
    field_path: "scenario_set.scenario-1.load_provider.provider_input",
    message: `${id} message`, correction: `${id} correction`, content_hash: hash,
  };
}

function validation({
  projectId = "project-1", revision = 3, fingerprint = "validation-3",
  findings = [finding("warning", "warning-1")], allowed = false,
} = {}) {
  return {
    project_id: projectId, project_revision: revision,
    project_fingerprint: `project-fingerprint-${revision}`, fingerprint, findings,
    generation_gate: {
      allowed, project_id: projectId, project_revision: revision,
      validation_fingerprint: fingerprint,
      blocking_error_ids: findings.filter((row) => row.severity === "error").map((row) => row.finding_id),
      unacknowledged_warning_ids: allowed ? [] : findings.filter((row) => row.severity === "warning").map((row) => row.finding_id),
    },
  };
}

function acknowledgement(validationRow, id = "warning-1", hash = "hash-warning-1", allowed = true) {
  return {
    acknowledgement: {
      finding_id: id, finding_content_hash: hash,
      project_revision: validationRow.project_revision,
      validation_fingerprint: validationRow.fingerprint,
      acknowledged_at: "2026-08-13T12:00:00Z",
    },
    generation_gate: {
      allowed, project_id: validationRow.project_id,
      project_revision: validationRow.project_revision,
      validation_fingerprint: validationRow.fingerprint,
      blocking_error_ids: [], unacknowledged_warning_ids: allowed ? [] : [id],
    },
  };
}

function loadState(fetchImpl = () => Promise.reject(new Error("unexpected fetch"))) {
  const source = fs.readFileSync(statePath, "utf8")
    .replace(/export function /g, "function ")
    .concat("\nmodule.exports = { createRefinedBlastStore, canGenerate, validationBudgetRows };\n");
  const context = vm.createContext({
    module: { exports: {} }, structuredClone, JSON, Object, Array, Promise, Set, Map,
    fetch: fetchImpl,
  });
  new vm.Script(source, { filename: statePath }).runInContext(context);
  return context.module.exports;
}

function storeOptions(fetchImpl) {
  return {
    project_id: "project-1", revision: 3, draft: draft(), fetch: fetchImpl,
  };
}

function applyValidation(store, row, mount = "mount-a") {
  const issue = store.beginValidationRequest({ mount_token: mount, project_id: "project-1" });
  if (!store.applyValidation(row, issue)) throw new Error("validation did not apply");
  return issue;
}

function gateMatrix() {
  const { createRefinedBlastStore, canGenerate } = loadState();
  const store = createRefinedBlastStore(storeOptions());

  applyValidation(store, validation({ findings: [finding("error", "error-1")], allowed: false }));
  const with_error = canGenerate(store.getState());

  const warningValidation = validation();
  applyValidation(store, warningValidation);
  const unacknowledged_warning = canGenerate(store.getState());
  const ackIssue = store.beginAcknowledgementRequest("warning-1", { mount_token: "mount-a" });
  store.applyAcknowledgement(acknowledgement(warningValidation), ackIssue);
  const acknowledged_current_warning = canGenerate(store.getState());

  const changedHash = store.getState();
  changedHash.validation.findings[0].content_hash = "changed-hash";
  const changed_warning_hash = canGenerate(changedHash);
  const changedFingerprint = store.getState();
  changedFingerprint.validation.fingerprint = "changed-fingerprint";
  const changed_validation_fingerprint = canGenerate(changedFingerprint);
  const staleRevision = store.getState();
  staleRevision.revision += 1;
  const stale_revision = canGenerate(staleRevision);
  const dirty = store.getState();
  dirty.draft_revision += 1;
  const local_unsaved_edit = canGenerate(dirty);
  const gateDenied = store.getState();
  gateDenied.generation_gate.allowed = false;
  const backend_gate_denied = canGenerate(gateDenied);

  applyValidation(store, validation({ findings: [finding("info", "info-1")], allowed: true, fingerprint: "info-validation" }));
  const info_only = canGenerate(store.getState());

  return {
    with_error, unacknowledged_warning, acknowledged_current_warning,
    changed_warning_hash, changed_validation_fingerprint, stale_revision,
    local_unsaved_edit, backend_gate_denied, info_only,
  };
}

async function identityMatrix() {
  const { createRefinedBlastStore, canGenerate } = loadState();
  const store = createRefinedBlastStore(storeOptions());
  const old = store.beginValidationRequest({ mount_token: "mount-a", project_id: "project-1" });
  const current = store.beginValidationRequest({ mount_token: "mount-a", project_id: "project-1" });
  const currentApplied = store.applyValidation(validation({ fingerprint: "current" }), current);
  const lateApplied = store.applyValidation(validation({ fingerprint: "late" }), old);

  const other = store.beginValidationRequest({ mount_token: "mount-a", project_id: "project-1" });
  const otherProjectApplied = store.applyValidation(validation({ projectId: "project-2", fingerprint: "other" }), other);

  const beforeEdit = store.beginValidationRequest({ mount_token: "mount-a", project_id: "project-1" });
  store.updateDraft((value) => { value.scenario_kind = "internal"; });
  const afterEditApplied = store.applyValidation(validation({ fingerprint: "stale-edit" }), beforeEdit);

  const cleanStore = createRefinedBlastStore(storeOptions());
  const fresh = cleanStore.beginValidationRequest({ mount_token: "mount-a", project_id: "project-1" });
  cleanStore.applyValidation(validation({ fingerprint: "ack-current" }), fresh);
  const oldAck = cleanStore.beginAcknowledgementRequest("warning-1", { mount_token: "mount-a" });
  applyValidation(cleanStore, validation({ fingerprint: "new-validation" }));
  const lateAckApplied = cleanStore.applyAcknowledgement(
    acknowledgement(validation({ fingerprint: "ack-current" })), oldAck,
  );

  const disposed = cleanStore.beginValidationRequest({ mount_token: "mount-a", project_id: "project-1" });
  cleanStore.disposeValidationRequests("mount-a");
  const unmountedApplied = cleanStore.applyValidation(validation({ fingerprint: "unmounted" }), disposed);

  applyValidation(cleanStore, validation({ fingerprint: "conflict-validation" }), "mount-b");
  const conflictAck = cleanStore.beginAcknowledgementRequest("warning-1", { mount_token: "mount-b" });
  const conflictApplied = cleanStore.rejectAcknowledgementRequest(conflictAck, 409, { code: "validation_conflict" });

  let resolveSave;
  const saveStore = createRefinedBlastStore(storeOptions(() => new Promise((resolve) => { resolveSave = resolve; })));
  const saveValidation = validation({ fingerprint: "before-save" });
  applyValidation(saveStore, saveValidation);
  const ackBeforeSave = saveStore.beginAcknowledgementRequest("warning-1", { mount_token: "mount-a" });
  const saving = saveStore.save("project-1");
  const validationClearedOnSave = saveStore.getState().validation === null;
  resolveSave({ ok: true, status: 200, json: async () => ({ project: { revision: 4 } }) });
  await saving;
  const lateAckAfterSave = saveStore.applyAcknowledgement(acknowledgement(saveValidation), ackBeforeSave);

  return {
    current_applied: currentApplied, late_applied: lateApplied,
    current_fingerprint: currentApplied ? "current" : null,
    other_project_applied: otherProjectApplied, edit_response_applied: afterEditApplied,
    late_ack_applied: lateAckApplied, unmounted_applied: unmountedApplied,
    conflict_applied: conflictApplied, conflict_blocking: cleanStore.getState().conflict?.blocking === true,
    generate_after_conflict: canGenerate(cleanStore.getState()),
    validation_cleared_on_save: validationClearedOnSave,
    late_ack_after_save: lateAckAfterSave,
    saved_revision: saveStore.getState().revision,
  };
}

function budgetRows() {
  const { validationBudgetRows } = loadState();
  const counts = [
    { metric: "building_nodes", value: 140, semantics: "exact" },
    { metric: "provider_elements", value: 900, semantics: "upper_bound" },
  ];
  const preview = { counts: structuredClone(counts) };
  const before = JSON.stringify(preview);
  const rows = validationBudgetRows(preview);
  return {
    rows, preview_unchanged: JSON.stringify(preview) === before,
    exact_label: rows[0].semantics, upper_label: rows[1].semantics,
  };
}

class FakeElement {
  constructor(tag = "div") {
    this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {};
    this.listeners = new Map(); this.textContent = ""; this.disabled = false;
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = [...children]; }
  addEventListener(type, listener) { this.listeners.set(type, listener); }
  querySelectorAll() { return []; }
}

function loadWorkbench(store, fetchImpl, controls) {
  const document = { createElement: (tag) => new FakeElement(tag), createDocumentFragment: () => new FakeElement("fragment") };
  const context = vm.createContext({
    module: { exports: {} }, structuredClone, JSON, Object, Array, Promise, Set, Map,
    setTimeout, clearTimeout, AbortController, document,
    window: { fetch: fetchImpl, location: { pathname: "/refined-building-blast" } },
    createRefinedBlastStore: () => store, renderSchemaFields: () => new FakeElement("fragment"),
    renderRefinedBlastPreview: () => null,
  });
  const source = fs.readFileSync(workbenchPath, "utf8")
    .replace('import { createRefinedBlastStore, renderSchemaFields } from "./refined_blast_state.js";', "")
    .replace('import { renderRefinedBlastPreview } from "./refined_blast_viewer.js";', "")
    .replace(/export function /g, "function ")
    .concat("\nfunction activateForTest(session) { activeSession = session; mountedRoot = session.root; refinedBlastStore = session.store; }\nmodule.exports = { requestValidation, acknowledgeWarning, refreshPreview, renderValidationState, activateForTest };\n");
  new vm.Script(prepareWorkbenchSource(source, context), { filename: workbenchPath }).runInContext(context);
  const rootElement = {
    querySelector(selector) { return controls.get(selector) ?? null; },
    querySelectorAll() { return []; },
  };
  return { app: context.module.exports, rootElement };
}

async function workbenchRequests() {
  const requests = [];
  const responses = [];
  const fetchImpl = (url, options) => {
    requests.push({ url, body: JSON.parse(options.body), method: options.method });
    return Promise.resolve(responses.shift());
  };
  const { createRefinedBlastStore, canGenerate } = loadState(fetchImpl);
  const store = createRefinedBlastStore(storeOptions(fetchImpl));
  const controls = new Map([
    ["[data-refined-validation-findings]", new FakeElement()],
    ["[data-refined-validation-status]", new FakeElement()],
    ["[data-refined-budget-rows]", new FakeElement()],
    ["[data-refined-generate]", new FakeElement("button")],
    ["[data-refined-save]", new FakeElement("button")],
    ["#refinedBlastPreviewStatus", new FakeElement("span")],
  ]);
  const { app, rootElement } = loadWorkbench(store, fetchImpl, controls);
  const session = {
    root: rootElement, token: 41, store, projectId: "project-1", detached: false,
    timer: null, inFlight: null, flushPromise: null, queued: false,
    persistedDraftRevision: 0, saveError: null, fetch: fetchImpl,
    validationAbortController: null, acknowledgementAbortControllers: new Map(),
  };
  app.activateForTest(session);

  const warningValidation = validation();
  responses.push({ ok: true, status: 200, json: async () => ({ result: { validation: warningValidation } }) });
  const validated = await app.requestValidation(rootElement, session);
  const findingNode = controls.get("[data-refined-validation-findings]").children[0];
  const rendered = {
    severity: findingNode.dataset.severity, text: findingNode.textContent,
    id: findingNode.dataset.findingId, hash: findingNode.dataset.contentHash,
  };

  responses.push({ ok: true, status: 200, json: async () => ({ result: acknowledgement(warningValidation) }) });
  const acknowledged = await app.acknowledgeWarning(rootElement, session, "warning-1");
  const enabledAfterAck = canGenerate(store.getState()) && controls.get("[data-refined-generate]").disabled === false;

  app.renderValidationState(rootElement, session);
  const warningNode = controls.get("[data-refined-validation-findings]").children[0];
  const acknowledgementButton = warningNode.children.find(
    (child) => child.dataset?.refinedAcknowledge !== undefined,
  );
  const acknowledgementButtonDisabled = acknowledgementButton?.disabled === true;

  return {
    validated, acknowledged, requests, rendered, enabled_after_ack: enabledAfterAck,
    acknowledgement_button_disabled: acknowledgementButtonDisabled,
  };
}

async function workbenchConflict() {
  const requests = [];
  const fetchImpl = async (url, options) => {
    requests.push({ url, body: JSON.parse(options.body) });
    return { ok: false, status: 409, json: async () => ({ error: { code: "validation_conflict" } }) };
  };
  const { createRefinedBlastStore } = loadState(fetchImpl);
  const store = createRefinedBlastStore(storeOptions(fetchImpl));
  applyValidation(store, validation(), 9);
  const controls = new Map([
    ["[data-refined-validation-findings]", new FakeElement()],
    ["[data-refined-validation-status]", new FakeElement()],
    ["[data-refined-budget-rows]", new FakeElement()],
    ["[data-refined-generate]", new FakeElement("button")],
  ]);
  const { app, rootElement } = loadWorkbench(store, fetchImpl, controls);
  const session = {
    root: rootElement, token: 9, store, projectId: "project-1", detached: false,
    timer: null, inFlight: null, flushPromise: null, queued: false,
    persistedDraftRevision: 0, saveError: null, fetch: fetchImpl,
    validationAbortController: null, acknowledgementAbortControllers: new Map(),
  };
  app.activateForTest(session);
  const applied = await app.acknowledgeWarning(rootElement, session, "warning-1");
  return {
    applied, requests, blocking: store.getState().conflict?.blocking === true,
    validation_cleared: store.getState().validation === null,
    message: controls.get("[data-refined-validation-status]").textContent,
  };
}

async function workbenchPreviewConflict() {
  const requests = [];
  const fetchImpl = async (url, options) => {
    requests.push({ url, body: JSON.parse(options.body), method: options.method });
    return { ok: false, status: 409, json: async () => ({ error: { code: "revision_conflict" } }) };
  };
  const { createRefinedBlastStore, canGenerate } = loadState(fetchImpl);
  const store = createRefinedBlastStore(storeOptions(fetchImpl));
  const validationRow = validation();
  applyValidation(store, validationRow, 10);
  const acknowledgementIssue = store.beginAcknowledgementRequest("warning-1", { mount_token: 10 });
  store.applyAcknowledgement(acknowledgement(validationRow), acknowledgementIssue);
  const controls = new Map([
    ["[data-refined-validation-findings]", new FakeElement()],
    ["[data-refined-validation-status]", new FakeElement()],
    ["[data-refined-budget-rows]", new FakeElement()],
    ["[data-refined-generate]", new FakeElement("button")],
    ["[data-refined-preview-canvas]", new FakeElement()],
    ["[data-refined-preview-counts]", new FakeElement()],
    ["#refinedBlastPreviewStatus", new FakeElement("span")],
  ]);
  const { app, rootElement } = loadWorkbench(store, fetchImpl, controls);
  const session = {
    root: rootElement, token: 10, store, projectId: "project-1", detached: false,
    timer: null, inFlight: null, flushPromise: null, queued: false,
    persistedDraftRevision: 0, saveError: null, fetch: fetchImpl,
    previewAbortController: null, previewRequest: null, viewer: null,
    validationAbortController: null, acknowledgementAbortControllers: new Map(),
  };
  app.activateForTest(session);
  const applied = await app.refreshPreview(rootElement, session);
  return {
    applied,
    blocking: store.getState().conflict?.blocking === true,
    validation_cleared: store.getState().validation === null,
    generate_enabled: canGenerate(store.getState()),
    request: requests[0],
  };
}

async function runCase(name) {
  if (name === "gate-matrix") return gateMatrix();
  if (name === "identity-matrix") return identityMatrix();
  if (name === "budget-rows") return budgetRows();
  if (name === "workbench-requests") return workbenchRequests();
  if (name === "workbench-conflict") return workbenchConflict();
  if (name === "workbench-preview-conflict") return workbenchPreviewConflict();
  throw new Error(`unknown case: ${name}`);
}

runCase(process.argv[2])
  .then((result) => process.stdout.write(`${JSON.stringify(result)}\n`))
  .catch((error) => { console.error(error.stack); process.exitCode = 1; });
