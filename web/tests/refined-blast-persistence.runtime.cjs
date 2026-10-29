const fs = require("fs");
const vm = require("vm");

const modulePath = process.argv[2];
const caseName = process.argv[3];

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, String(value)); },
    removeItem(key) { values.delete(key); },
  };
}

function loadModule() {
  const source = fs.readFileSync(modulePath, "utf8")
    .replace(/export function /g, "function ")
    .concat("\nmodule.exports = { readLatestProjectId, writeLatestProjectId, readSessionDraft, writeSessionDraft, clearRecovery };\n");
  const context = vm.createContext({ module: { exports: {} }, JSON, Object });
  new vm.Script(source, { filename: modulePath }).runInContext(context);
  return context.module.exports;
}

function run() {
  const api = loadModule();
  if (caseName === "project-id") {
    const local = memoryStorage();
    api.writeLatestProjectId(local, "refined-blast-42");
    return { valid: api.readLatestProjectId(local), rejected: api.readLatestProjectId(memoryStorage({ "refined-blast.latest-project": "../bad" })) };
  }
  if (caseName === "session-draft") {
    const session = memoryStorage();
    const snapshot = { asset_id: "subway_entrance_detailed_building", building: { structural_system: "rc_box" }, draft: { scenario_id: "scenario-1" } };
    api.writeSessionDraft(session, snapshot);
    return { restored: api.readSessionDraft(session), malformed: api.readSessionDraft(memoryStorage({ "refined-blast.session-draft": "{" })) };
  }
  if (caseName === "clear-and-unavailable") {
    const local = memoryStorage();
    const session = memoryStorage();
    api.writeLatestProjectId(local, "project-1");
    api.writeSessionDraft(session, { asset_id: "commercial_supermarket_detailed_building", building: {}, draft: {} });
    api.clearRecovery({ localStorage: local, sessionStorage: session });
    const broken = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); }, removeItem() { throw new Error("blocked"); } };
    return { project: api.readLatestProjectId(local), draft: api.readSessionDraft(session), safe_project: api.readLatestProjectId(broken), safe_draft: api.readSessionDraft(broken) };
  }
  throw new Error(`unknown case: ${caseName}`);
}

try { process.stdout.write(`${JSON.stringify(run())}\n`); }
catch (error) { console.error(error.stack || error); process.exitCode = 1; }
