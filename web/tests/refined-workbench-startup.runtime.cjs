const fs = require("fs");
const vm = require("vm");

const appPath = process.argv[2];

function createElement(id) {
  const classes = new Set();
  return {
    id,
    dataset: {}, style: {}, value: "", textContent: "", disabled: false,
    classList: {
      add(...names) { names.forEach((name) => classes.add(name)); },
      remove(...names) { names.forEach((name) => classes.delete(name)); },
      contains(name) { return classes.has(name); },
      toggle(name, force) { if (force) classes.add(name); else classes.delete(name); },
    },
    listeners: [],
    addEventListener(type) { this.listeners.push(type); },
    setAttribute() {},
    removeAttribute() {},
    append() {},
    appendChild() {},
    replaceChildren() {},
    focus() {},
    querySelector() {
      return createElement("refined-back");
    }
  };
}

async function runDirectRefinedBoot(pathname) {
  const elements = new Map();
  const fetchPaths = [];
  const mounts = [];
  const document = {
    createElement(tag) { return createElement(tag); },
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, createElement(id));
      return elements.get(id);
    },
    querySelector(selector) { return createElement(selector); },
    querySelectorAll() {
      return [];
    },
    addEventListener() {}
  };
  const window = {
    location: { pathname, search: "?viewer=canvas" },
    addEventListener() {}
  };
  const context = vm.createContext({
    URLSearchParams,
    Promise,
    console,
    document,
    fetch: async (path) => {
      fetchPaths.push(path);
      return { ok: true, json: async () => ({}) };
    },
    history: { pushState() {}, replaceState() {} },
    PopStateEvent: class {},
    window
  });
  const workbenchModule = new vm.SyntheticModule(
    ["mountRefinedBlastWorkbench", "unmountRefinedBlastWorkbench"],
    function initializeWorkbenchExports() {
      this.setExport("mountRefinedBlastWorkbench", (root, options) => {
        mounts.push({
          root: root.id,
          updateHistory: options.updateHistory,
          projectId: options.projectId,
          restoreProject: options.restoreProject,
        });
      });
      this.setExport("unmountRefinedBlastWorkbench", () => {});
    },
    { context }
  );
  await workbenchModule.link(() => {});
  await workbenchModule.evaluate();
  const persistenceModule = new vm.SyntheticModule(
    ["readLatestProjectId", "readSessionDraft"],
    function initializePersistenceExports() {
      this.setExport("readLatestProjectId", () => "stored-refined-project");
      this.setExport("readSessionDraft", () => null);
    },
    { context }
  );
  await persistenceModule.link(() => {});
  await persistenceModule.evaluate();

  let source = fs.readFileSync(appPath, "utf8");
  source = source.replace("boot().catch(showError);", "globalThis.__bootPromise = boot(); globalThis.__showLegacy = showLegacyWorkbench;");
  const script = new vm.Script(source, {
    filename: appPath,
    importModuleDynamically(specifier) {
      if (specifier === "/refined_blast_workbench.js") return workbenchModule;
      if (specifier === "/refined_blast_persistence.js") return persistenceModule;
      throw new Error(`unexpected module: ${specifier}`);
    }
  });
  script.runInContext(context);
  await context.__bootPromise;
  const directFetchPaths = [...fetchPaths];
  window.location.pathname = "/";
  context.__showLegacy();
  await Promise.resolve();
  return { directFetchPaths, fetchPaths, mounts, lazyLegacyStarted: elements.get("prompt")?.listeners.includes("input") === true };
}

(async () => {
  const results = [];
  for (const pathname of ["/refined-building-blast", "/refined-building-blast/"]) {
    results.push(await runDirectRefinedBoot(pathname));
  }
  for (const result of results) {
    if (result.directFetchPaths.length !== 0) throw new Error(`legacy fetches during direct boot: ${result.directFetchPaths.join(",")}`);
    if (result.mounts.length !== 1 || result.mounts[0].root !== "refinedBlastWorkbenchRoot") {
      throw new Error(`refined workbench did not mount: ${JSON.stringify(result.mounts)}`);
    }
    if (result.mounts[0].projectId !== "stored-refined-project" || result.mounts[0].restoreProject !== true) {
      throw new Error(`latest refined project was not restored: ${JSON.stringify(result.mounts[0])}`);
    }
    if (!result.lazyLegacyStarted) throw new Error("legacy workbench did not lazily initialize on Back");
    if (!result.fetchPaths.includes("/api/config")) throw new Error("legacy configuration was not loaded on Back");
  }
  process.stdout.write(`${JSON.stringify(results)}\n`);
})().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
