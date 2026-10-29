const { prepareWorkbenchSource } = require("./workbench-dependencies.cjs");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const rootPath = path.resolve(__dirname, "../..");
class Element {
  constructor() { this.textContent = ""; this.disabled = false; this.hidden = false; this.children = []; this.attributes = {}; this.dataset = {}; this.open = false; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  getAttribute(key) { return this.attributes[key] ?? null; }
  removeAttribute(key) { delete this.attributes[key]; }
  focus() { this.focused = true; }
  showModal() { this.open = true; }
  close() { this.open = false; }
}
const id = "a".repeat(24);
const identity = { project_id: "project-1", scenario_id: "case-1", generated_revision: 2, artifact_fingerprint: "b".repeat(64), package_fingerprint: "c".repeat(64) };
const record = {
  schema_version: "lsprepost_mcp.damage_assessment_response@1",
  registration_state: "registered", assessment_id: id, gate: "provisional", severity: 2,
  assessment_fingerprint: "d".repeat(64), registered_at: "2026-09-08T08:00:00Z",
  source: { run_id: "run-1", run_status: "completed" }, artifacts: {},
  warnings: [{ code: "reference_rule", message: "<script>unsafe()</script>", details: {} }],
  blockers: [], review_items: [],
};
const snapshot = {
  schema_version: "blast_damage.assessment_snapshot@1", assessment_id: id,
  assessment_fingerprint: "d".repeat(64), identity: { project_id: "project-1", case_id: "case-1" },
  overall: { gate: "provisional", severity: 2, partial_assessment: false },
  building: { gate: "provisional", severity: 2, components: [] },
  ground: { gate: "provisional", severity: 1 }, limitations: ["研究参考"],
};
function response(result, status = 200) {
  return { ok: status < 400, status, json: async () => status < 400 ? { ok: true, result } : { ok: false, error: { code: result } } };
}
function createUi(options = {}) {
  const controls = new Map();
  for (const name of ["panel", "project", "capability", "source", "status", "result", "building", "ground", "issues", "start", "refresh", "close", "view", "download", "building-csv", "ground-csv"]) controls.set("[data-damage-" + name + "]", new Element());
  controls.set("[data-refined-assessment]", new Element());
  const root = { querySelector: key => controls.get(key) ?? null, querySelectorAll: () => [] };
  const requests = [];
  const storageValues = new Map();
  const storage = { getItem: key => storageValues.get(key) ?? null, setItem: (key, value) => storageValues.set(key, value), removeItem: key => storageValues.delete(key) };
  let state = { project_id: "project-1", revision: 2, draft_revision: 0, draft: { scenario_id: "case-1" }, conflict: null };
  const fetch = async (url, init = {}) => {
    requests.push({ url, method: init.method ?? "GET", body: init.body ? JSON.parse(init.body) : null });
    if (options.fetch) return options.fetch(url, init);
    if (url.endsWith("/capabilities")) return response({ schema_version: "lsprepost_mcp.damage_assessment_capabilities@1", available: options.available !== false, reason: "package_missing" });
    if (url.endsWith("/assessments/latest")) return options.latest ? response(structuredClone(record)) : response("assessment_not_found", 404);
    if (url.endsWith("/assessment_snapshot.json")) return options.snapshotError ? response(options.snapshotError, 409)
      : { ok: true, status: 200, json: async () => structuredClone(options.snapshot ?? snapshot) };
    if (url.endsWith("/assess-latest-run")) {
      if (options.error) return response(options.error, 409);
      return response({ ...structuredClone(record), ...options.result });
    }
    throw new Error("unexpected route " + url);
  };
  const context = vm.createContext({
    module: { exports: {} }, JSON, Object, Array, Promise, Set, Map, structuredClone, AbortController,
    document: { createElement: () => new Element() },
    window: { fetch, localStorage: storage }, setTimeout, clearTimeout,
  });
  const source = fs.readFileSync(path.join(rootPath, "lsprepost_mcp/web/static/refined_blast_workbench.js"), "utf8")
    .replace(/^import .*;\r?$/gm, "").replace(/export function /g, "function ")
    + "\nmodule.exports = { open: typeof openDamageAssessment === 'function' ? openDamageAssessment : null, run: typeof requestDamageAssessment === 'function' ? requestDamageAssessment : null, render: typeof renderDamageAssessment === 'function' ? renderDamageAssessment : null, close: typeof closeDamageAssessment === 'function' ? closeDamageAssessment : null, remember: typeof rememberDamageAssessmentIdentity === 'function' ? rememberDamageAssessmentIdentity : null, activate(s) { activeSession=s; mountedRoot=s.root; refinedBlastStore=s.store; } };";
  new vm.Script(prepareWorkbenchSource(source, context)).runInContext(context);
  const functions = context.module.exports;
  assert.equal(typeof functions.open, "function", "评估入口控制器尚未实现");
  const session = { root, token: 1, detached: false, projectId: "project-1", fetch, localStorage: storage,
    store: { getState: () => structuredClone(state) }, generated: structuredClone(identity),
    persistedDraftRevision: 0, saveError: null, actionInFlight: false, damageAssessment: null };
  functions.activate(session);
  return { ...functions, root, session, requests, controls, state, storage, node: name => controls.get("[data-damage-" + name + "]") };
}
async function runCase(name) {
  const ui = createUi({ available: name !== "unavailable", latest: ["latest", "latest-bad-snapshot"].includes(name),
    snapshotError: name === "bad-artifact" ? "assessment_artifact_integrity_error" : undefined,
    error: name === "no-source" ? "assessment_source_unavailable" : undefined,
    result: name === "unregistered" ? { registration_state: "completed_unregistered" }
      : name === "blocked" ? { gate: "blocked", severity: null, blockers: [{ code: "missing", message: "缺少必要证据", details: {} }] } : undefined,
    snapshot: ["bad-snapshot", "latest-bad-snapshot"].includes(name) ? { ...snapshot, identity: { project_id: "another-project" } }
      : name === "blocked" ? { ...snapshot, overall: { gate: "blocked", severity: null }, building: { gate: "blocked", severity: null }, ground: { gate: "blocked", severity: null } } : undefined });
  if (name === "no-project") { ui.state.project_id = null; ui.session.projectId = null; }
  if (name === "dirty") ui.state.draft_revision = 1;
  if (name === "stale") ui.state.revision = 3;
  if (name === "restore") { ui.remember(ui.session); ui.session.generated = null; }
  if (name === "corrupt-cache") {
    ui.remember(ui.session); ui.session.generated = null;
    ui.storage.setItem("refined-blast.assessment-identity.project-1", '{"schema_version":"bad"}');
  }
  await ui.open(ui.root, ui.session);
  assert.equal(ui.node("panel").open, true);
  assert.equal(ui.requests.some(item => item.method === "POST"), false, "打开面板不得自动评估");
  if (name === "open") {
    assert.equal(ui.node("start").disabled, false);
    assert.match(ui.node("source").textContent, /核验/);
    ui.close(ui.root, ui.session);
    assert.equal(ui.node("panel").open, false);
    assert.equal(ui.controls.get("[data-refined-assessment]").focused, true);
  } else if (["unavailable", "no-project", "dirty", "stale", "corrupt-cache"].includes(name)) {
    assert.equal(ui.node("start").disabled, true);
    await ui.run(ui.root, ui.session);
    assert.equal(ui.requests.some(item => item.method === "POST"), false);
  } else if (name === "latest-bad-snapshot") {
    assert.match(ui.node("status").textContent, /校验/);
    assert.doesNotMatch(ui.node("result").textContent, /等级 [0-4]/);
    assert.equal(ui.node("view").getAttribute("href"), null);
  } else if (name === "latest") {
    assert.match(ui.node("result").textContent, /已登记/);
    assert.equal(ui.node("view").getAttribute("href"), "/api/refined-building-blast/projects/project-1/assessments/" + id + "/artifacts/damage_report.html");
  } else {
    await ui.run(ui.root, ui.session);
    const posts = ui.requests.filter(item => item.method === "POST");
    assert.equal(posts.length, 1);
    assert.deepEqual(posts[0].body, { schema_version: "lsprepost_mcp.damage_assessment_request@1", scenario_id: "case-1", generated_revision: 2, artifact_fingerprint: "b".repeat(64), package_fingerprint: "c".repeat(64) });
    if (name === "no-source") {
      assert.match(ui.node("status").textContent, /求解结果/);
      assert.equal(ui.node("view").getAttribute("href"), null);
    } else if (name === "unregistered") {
      assert.match(ui.node("status").textContent, /登记/);
      assert.equal(ui.node("view").getAttribute("href"), null);
    } else if (["bad-snapshot", "bad-artifact"].includes(name)) {
      assert.match(ui.node("status").textContent, /校验/);
      assert.doesNotMatch(ui.node("result").textContent, /等级 [0-4]/, "未经快照校验不得保留总等级");
      assert.doesNotMatch(ui.node("building").textContent, /等级 2/);
    } else if (name === "blocked") {
      assert.match(ui.node("result").textContent, /证据不足/);
      assert.doesNotMatch(ui.node("building").textContent, /等级 [0-4]/);
    } else {
      assert.match(ui.node("building").textContent, /等级 2/);
      assert.match(ui.node("ground").textContent, /等级 1/);
      assert.equal(ui.node("download").getAttribute("download"), "damage_report.html");
      assert.equal(ui.node("issues").children.some(child => child.textContent.includes("<script>")), true);
      assert.equal(ui.node("view").getAttribute("rel"), "noopener noreferrer");
    }
  }
  return { case: name, passed: true };
}
runCase(process.argv[2]).then(result => process.stdout.write(JSON.stringify(result) + "\n")).catch(error => { console.error(error); process.exitCode = 1; });
