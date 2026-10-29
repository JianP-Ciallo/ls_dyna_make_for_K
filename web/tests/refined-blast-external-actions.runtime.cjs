const { prepareWorkbenchSource } = require("./workbench-dependencies.cjs");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.resolve(__dirname, "..", "..");
const workbenchPath = path.join(root, "lsprepost_mcp", "web", "static", "refined_blast_workbench.js");

function load(confirm, requests) {
  const controls = new Map([
    ["[data-refined-generate]", { disabled: false }],
    ["[data-refined-open-lsprepost]", { disabled: true }],
    ["[data-refined-launch-lsdyna]", { disabled: true }],
    ["[data-refined-external-status]", { textContent: "" }],
  ]);
  const rootElement = { querySelector: (selector) => controls.get(selector) ?? null, querySelectorAll: () => [] };
  const fetch = async (url, options) => {
    requests.push({ url, body: JSON.parse(options.body) });
    if (url.endsWith("action-confirmations")) return { ok: true, status: 200, json: async () => ({ result: { confirmation: { nonce: "nonce-1", action: "open_lsprepost", project_id: "project-1", scenario_id: "scenario-1", generated_revision: 2, artifact_fingerprint: "artifact", package_fingerprint: "package" } } }) };
    return { ok: true, status: 200, json: async () => ({ result: {
      action: "open_lsprepost", scenario_id: "scenario-1", generated_revision: 2,
      artifact_fingerprint: "artifact", package_fingerprint: "package",
      external_program_started: true, solver_ready: false, requires_project_review: true
    } }) };
  };
  const context = vm.createContext({
    module: { exports: {} }, JSON, Object, Array, Promise, Set, Map, structuredClone,
    window: { confirm, fetch, location: { pathname: "/refined-building-blast" } },
    document: {}, createRefinedBlastStore: () => ({}), renderSchemaFields: () => ({}), renderRefinedBlastPreview: () => null,
  });
  let source = fs.readFileSync(workbenchPath, "utf8")
    .replace('import { createRefinedBlastStore, renderSchemaFields } from "./refined_blast_state.js";', "")
    .replace('import { renderRefinedBlastPreview } from "./refined_blast_viewer.js";', "")
    .replace(/export function /g, "function ")
    .concat("\nfunction activateForTest(session) { activeSession = session; mountedRoot = session.root; }\nmodule.exports = { requestExternalAction, activateForTest };\n");
  new vm.Script(prepareWorkbenchSource(source, context), { filename: workbenchPath }).runInContext(context);
  return { requestExternalAction: context.module.exports.requestExternalAction, activateForTest: context.module.exports.activateForTest, rootElement, controls, fetch };
}

async function runCase(name) {
  const requests = [];
  const ui = load(() => name !== "cancel", requests);
  const state = { project_id: "project-1", revision: name === "stale" ? 3 : 2, draft_revision: name === "dirty" ? 4 : 3, persisted_draft_revision: 3, draft: { scenario_id: "scenario-1" }, conflict: null };
  const session = {
    root: ui.rootElement, token: 1, detached: false, projectId: "project-1", fetch: ui.fetch,
    persistedDraftRevision: 3, saveError: null,
    store: { getState: () => structuredClone(state), canGenerate: () => true },
    generated: { project_id: "project-1", scenario_id: "scenario-1", generated_revision: 2, artifact_fingerprint: "artifact", package_fingerprint: "package" },
    actionInFlight: false,
  };
  ui.activateForTest(session);
  const result = await ui.requestExternalAction(ui.rootElement, session, "open_lsprepost");
  return { result, requests, open_disabled: ui.controls.get("[data-refined-open-lsprepost]").disabled };
}

runCase(process.argv[2]).then((row) => process.stdout.write(`${JSON.stringify(row)}\n`)).catch((error) => { console.error(error.stack); process.exitCode = 1; });
