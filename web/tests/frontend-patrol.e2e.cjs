"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const baseUrl = process.env.UI_PATROL_BASE_URL;
const projectPrefix = process.env.UI_PATROL_PROJECT_PREFIX || `ui_patrol_${Date.now()}`;
const evidenceDir = process.env.UI_PATROL_EVIDENCE_DIR || process.cwd();

if (!baseUrl) throw new Error("UI_PATROL_BASE_URL is required.");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function browserExecutable() {
  const configured = process.env.UI_PATROL_BROWSER_EXE;
  if (configured && fs.existsSync(configured)) return configured;
  const bundled = chromium.executablePath();
  if (fs.existsSync(bundled)) return bundled;
  const candidates =
    process.platform === "win32"
      ? [
          "C:/Program Files/Google/Chrome/Application/chrome.exe",
          "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
          "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        ]
      : ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"];
  const found = candidates.find((candidate) => fs.existsSync(candidate));
  if (!found) throw new Error("No Chromium browser is available for the UI patrol.");
  return found;
}

function mockConfig() {
  return {
    configured: true,
    lspp_exe: "C:\\mock\\lsprepost4.12.exe",
    doctor: { ok: true },
    export_dir_configured: false,
    export_dir: "",
    lsrun_configured: true,
    lsrun_exe: "C:\\mock\\lsrun.exe",
    lsrun_doctor: { ok: true },
    lsdyna_configured: true,
    lsdyna_exe: "C:\\mock\\lsdyna.exe",
    lsdyna_doctor: { ok: true },
    solve_ncpu: 4,
    solve_memory: "20m",
    solve_timeout_s: 600,
    solve_command_template: '"$SOLVER" i="$INPUT" ncpu=$NCPU memory=$MEMORY',
  };
}

function jsonBody(result) {
  return JSON.stringify({ ok: true, result });
}

async function run() {
  fs.mkdirSync(evidenceDir, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    executablePath: browserExecutable(),
    args: [
      "--no-sandbox",
      "--disable-gpu-sandbox",
      "--enable-unsafe-swiftshader",
      "--use-angle=swiftshader-webgl",
    ],
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const clicked = new Set();
  const exercisedCases = [];
  const generatedProjects = [];
  const mockedExternalCalls = [];
  const pageErrors = [];
  const failedRequests = [];

  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("requestfailed", (request) => {
    failedRequests.push(`${request.url()}: ${request.failure()?.errorText || "failed"}`);
  });
  page.on("dialog", (dialog) => dialog.accept());
  await page.addInitScript(() => {
    window.__uiPatrolOpenedUrls = [];
    window.open = (...args) => {
      window.__uiPatrolOpenedUrls.push(args[0]);
      return null;
    };
  });

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const apiPath = url.pathname;
    const config = mockConfig();
    let result = null;

    if (request.method() === "GET" && apiPath === "/api/config") result = config;
    if (request.method() === "POST" && apiPath.startsWith("/api/config/")) {
      mockedExternalCalls.push(apiPath);
      result = config;
      if (apiPath.includes("check-lsprepost")) {
        result = { lspp_exe: config.lspp_exe, doctor: { ok: true } };
      } else if (apiPath.includes("check-lsrun")) {
        result = { lsrun_exe: config.lsrun_exe, doctor: { ok: true } };
      } else if (apiPath.includes("check-lsdyna")) {
        result = { lsdyna_exe: config.lsdyna_exe, doctor: { ok: true } };
      }
    }
    if (
      request.method() === "POST" &&
      ["/api/project/select-import-package", "/api/project/import-package"].includes(apiPath)
    ) {
      mockedExternalCalls.push(apiPath);
      const projectName = generatedProjects[0];
      result = {
        operation: "import_project_package",
        project_name: projectName,
        project_dir: `workspace/projects/${projectName}`,
        source_dir: `workspace/projects/${projectName}`,
        copied_files: ["model.k", "model.json", "checks.json", "export_manifest.json"],
        checks_ok: true,
      };
    }
    if (request.method() === "POST" && apiPath === "/api/project/open-lsprepost") {
      mockedExternalCalls.push(apiPath);
      const body = request.postDataJSON();
      result = {
        operation: "open_lsprepost",
        mode: "keyword_preview",
        status: "started",
        project_name: body.project_name,
        pid: 4242,
        process_running: true,
        keyword_path: `workspace/projects/${body.project_name}/model.k`,
      };
    }
    if (request.method() === "POST" && apiPath === "/api/solve/open-lsrun") {
      mockedExternalCalls.push(apiPath);
      const body = request.postDataJSON();
      result = {
        ok: true,
        operation: "open_lsrun",
        status: "handoff_opened",
        project_name: body.project_name,
        run_id: "mock_lsrun_1",
        input: "model.k",
        run_dir: "mock/run",
        lsrun_exe: config.lsrun_exe,
        lsdyna_exe: config.lsdyna_exe,
        command_preview: "mock command",
      };
    }
    if (request.method() === "POST" && apiPath === "/api/solve/recover-lsrun") {
      mockedExternalCalls.push(apiPath);
      const body = request.postDataJSON();
      result = {
        ok: true,
        operation: "recover_lsrun",
        status: "completed",
        project_name: body.project_name,
        run_id: body.run_id,
        solver_evaluation: { ok: true },
        wave_transfer_acceptance: { wave_transfer_verified: true },
        outputs: { d3plot: { ok: true }, blstfor: { ok: true } },
        postprocessing: { status: "verified" },
      };
    }
    if (request.method() === "POST" && apiPath === "/api/solve/run-lsdyna") {
      mockedExternalCalls.push(apiPath);
      const body = request.postDataJSON();
      result = {
        ok: true,
        operation: "run_lsdyna",
        status: "completed",
        project_name: body.project_name,
        run_id: "mock_direct_1",
        returncode: 0,
        outputs: { d3plot: { ok: true }, blstfor: { ok: true } },
        postprocessing: { status: "verified" },
      };
    }
    if (request.method() === "GET" && apiPath === "/api/solve/status") {
      mockedExternalCalls.push(apiPath);
      result = {
        ok: true,
        operation: "lsdyna_status",
        status: "completed",
        project_name: url.searchParams.get("project_name"),
        run_id: "mock_status_1",
        outputs: { d3plot: { ok: true }, blstfor: { ok: true } },
        postprocessing: { status: "verified" },
      };
    }
    if (request.method() === "POST" && apiPath === "/api/project/open-result-lsprepost") {
      mockedExternalCalls.push(apiPath);
      result = {
        ok: true,
        operation: "open_result_lsprepost",
        status: "started",
        project_name: request.postDataJSON().project_name,
      };
    }
    if (request.method() === "POST" && apiPath === "/api/solve/compare") {
      mockedExternalCalls.push(apiPath);
      result = {
        ok: true,
        run_count: 2,
        comparisons: {
          peak_blast_pressure: { minimum: 1, maximum: 2, unit: "Pa" },
        },
        configuration_comparison: {},
      };
    }
    if (request.method() === "GET" && apiPath === "/api/project/city-impact") {
      mockedExternalCalls.push(apiPath);
      result = {
        ok: true,
        status: "available",
        status_label: "巡检用城市影响评估",
        quality: { global_metrics: { time_coverage_ratio: 1 } },
        part_risk: {},
        objects: [
          {
            id: "mock_building",
            label: "巡检建筑",
            part_ids: [],
            risk: { level: "low", label: "低" },
            metrics: {
              pressure: { label: "峰值压力", available: true, value: 1, unit: "Pa" },
            },
          },
        ],
      };
    }
    if (request.method() === "POST" && apiPath === "/api/project/city-impact-report") {
      mockedExternalCalls.push(apiPath);
      result = {
        ok: true,
        operation: "export_city_impact_report",
        project_name: request.postDataJSON().project_name,
        output_path: "mock/city-impact.md",
      };
    }
    if (request.method() === "POST" && apiPath === "/api/editor/validate-lsprepost") {
      mockedExternalCalls.push(apiPath);
      const body = request.postDataJSON();
      result = {
        ok: true,
        project_name: body.project_name,
        output_relative_path: "artifacts/phase17_import_validation_iso.png",
        validation: { static_checks_ok: true, preview_png_ok: true },
        preview_result: { keyword_reader: { errors: 0, warnings: 0 } },
        model_fingerprint: { model_k_sha256: "0123456789abcdef" },
      };
    }

    if (result !== null) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: jsonBody(result),
      });
      return;
    }
    await route.continue();
  });

  async function click(selector, key = selector) {
    const target = page.locator(selector).first();
    assert((await target.count()) === 1, `Button not found: ${selector}`);
    assert(await target.isVisible(), `Button is not visible: ${selector}`);
    assert(await target.isEnabled(), `Button is unexpectedly disabled: ${selector}`);
    await target.click();
    clicked.add(key.replace(/^#/, ""));
  }

  async function clickApi(selector, apiPath, key = selector) {
    const target = page.locator(selector).first();
    assert((await target.count()) === 1, `Button not found: ${selector}`);
    assert(await target.isVisible(), `Button is not visible: ${selector}`);
    assert(await target.isEnabled(), `Button is unexpectedly disabled: ${selector}`);
    const [response] = await Promise.all([
      page.waitForResponse(
        (candidate) => new URL(candidate.url()).pathname === apiPath,
        { timeout: 120000 }
      ),
      target.click().then(() => clicked.add(key.replace(/^#/, ""))),
    ]);
    let payload;
    try {
      payload = await response.json();
    } catch (error) {
      throw new Error(`${apiPath} did not return JSON: ${error.message}`);
    }
    assert(response.ok() && payload.ok, `${apiPath} failed: ${JSON.stringify(payload)}`);
    if (payload.result) {
      const projectName =
        payload.result.project_name ||
        payload.result.project ||
        payload.result.write_result?.project;
      if (projectName && projectName.startsWith(projectPrefix)) {
        generatedProjects.push(projectName);
      }
    }
    return payload.result;
  }

  async function waitForWorkbenchAction() {
    await page.waitForFunction(
      () =>
        !document.querySelector("#result .status") &&
        Boolean(document.querySelector("#result .operation-summary")),
      null,
      { timeout: 120000 }
    );
  }

  async function exerciseGeneratedCase({ mode, scene, suffix, resolvePath, generatePath, configure }) {
    process.stderr.write(`PATROL case ${suffix}: configure\n`);
    await page.locator("#modelMode").selectOption(mode);
    if (scene) await page.locator("#scene").selectOption(scene);
    if (configure) await configure();
    const requestedName = `${projectPrefix}_${suffix}`;
    await page.locator("#projectName").fill(requestedName);
    await clickApi("#resolve", resolvePath);
    await waitForWorkbenchAction();
    process.stderr.write(`PATROL case ${suffix}: generate\n`);
    const generated = await clickApi("#generate", generatePath);
    await waitForWorkbenchAction();
    const actualName =
      generated.project_name || generated.project || generated.write_result?.project || requestedName;
    assert(actualName.startsWith(projectPrefix), `Unexpected generated project: ${actualName}`);
    process.stderr.write(`PATROL case ${suffix}: preview ${actualName}\n`);
    await clickApi("#preview", "/api/project/preview-mesh");
    await waitForWorkbenchAction();
    await page.waitForFunction(
      (name) => document.querySelector("#contextStatus")?.textContent.includes(name),
      actualName,
      { timeout: 30000 }
    );
    exercisedCases.push({ mode, scene: scene || "", project: actualName });
    return actualName;
  }

  try {
    await page.goto(baseUrl, { waitUntil: "networkidle", timeout: 30000 });
    assert(
      await page.locator("#resultPlay").isDisabled(),
      "Result playback must remain disabled until a real d3plot parser exists."
    );
    assert(
      await page.locator("#recoverLsrun").isDisabled(),
      "LS-Run recovery must be disabled before a handoff."
    );

    await clickApi("#refresh", "/api/projects");
    await page.waitForTimeout(100);

    for (const scene of [
      "rebar_drop_on_helmet",
      "rod_impact_plate",
      "cube_top_corner_load",
      "plate_pressure",
    ]) {
      await exerciseGeneratedCase({
        mode: "controlled",
        scene,
        suffix: scene,
        resolvePath: "/api/scene/resolve",
        generatePath: "/api/scene/generate",
      });
      assert(
        await page.locator("#resultPlay").isDisabled(),
        `Result playback was incorrectly enabled after ${scene}.`
      );
      assert(
        await page.locator("#recoverLsrun").isDisabled(),
        `LS-Run recovery was incorrectly enabled after ${scene}.`
      );
    }

    await exerciseGeneratedCase({
      mode: "controlled",
      scene: "ale_blast",
      suffix: "mmale",
      resolvePath: "/api/ale-blast/validate",
      generatePath: "/api/ale-blast/generate",
      configure: async () => {
        await page.locator("#aleBlastPanel details").evaluateAll((items) => {
          for (const item of items) item.open = true;
        });
        await page.locator("#aleDomainX").fill("0.3");
        await page.locator("#aleDomainY").fill("0.3");
        await page.locator("#aleDomainZ").fill("0.2");
        await page.locator("#aleMeshSize").fill("0.01");
        await page.locator("#aleExplosiveZ").fill("0.1");
        await page.locator("#alePlateLength").fill("0.2");
        await page.locator("#alePlateWidth").fill("0.2");
      },
    });

    await exerciseGeneratedCase({
      mode: "tunnel_blast",
      suffix: "tunnel",
      resolvePath: "/api/tunnel-blast/validate",
      generatePath: "/api/tunnel-blast/generate",
      configure: async () => {
        await page.locator("#tunnelBlastPanel details").evaluateAll((items) => {
          for (const item of items) item.open = true;
        });
        await page.locator("#tunnelLength").fill("4");
        await page.locator("#tunnelWidth").fill("2");
        await page.locator("#tunnelHeight").fill("2");
        await page.locator("#tunnelAirMesh").selectOption("0.15");
        await page.locator("#tunnelExplosiveX").fill("1");
        await page.locator("#tunnelPlateX").fill("3");
        await page.locator("#tunnelPlateLength").fill("1");
        await page.locator("#tunnelPlateWidth").fill("1");
      },
    });

    for (const coupling of ["immersed_clis", "conforming_air_gap"]) {
      await exerciseGeneratedCase({
        mode: "phase15_a1",
        suffix: `phase15_${coupling}`,
        resolvePath: "/api/phase15/prepare",
        generatePath: "/api/phase15/generate",
        configure: async () => {
          await page.locator("#phase15Panel details").evaluateAll((items) => {
            for (const item of items) item.open = true;
          });
          await page.locator("#phase15ConsistencyMode").selectOption("mass_priority_adjust_length");
          await page.locator("#phase15MeshSize").selectOption("0.01");
          await page.locator("#phase15TargetRadius").fill("0.8");
          await page.locator("#phase15TargetHeight").fill("1.4");
          await page.locator("#phase15EndTimeMs").fill("0.5");
          await page.locator("#phase15CouplingMode").selectOption(coupling);
        },
      });
    }

    await page.locator("#modelMode").selectOption("assembly");
    const initialComponentCount = await page.locator("#assemblyComponents .assembly-card").count();
    await click("#addComponent");
    assert(
      (await page.locator("#assemblyComponents .assembly-card").count()) === initialComponentCount + 1,
      "Add component did not create a component editor."
    );
    await click("#assemblyComponents .assembly-card:last-child .danger-button", "dynamicComponentDelete");
    await click("#assemblyComponents .assembly-card:first-child .icon-text-button", "dynamicComponentCopy");
    await click("#assemblyComponents .assembly-card:nth-child(2) .danger-button", "dynamicComponentCopyDelete");
    const initialActionCount = await page.locator("#assemblyActions .assembly-card").count();
    await click("#addPhysicsAction");
    assert(
      (await page.locator("#assemblyActions .assembly-card").count()) === initialActionCount + 1,
      "Add physics action did not create an action editor."
    );
    await click("#assemblyActions .assembly-card:last-child .danger-button", "dynamicActionDelete");

    await clickApi("#loadBlastDemo", "/api/blast-demo");
    await waitForWorkbenchAction();
    await exerciseGeneratedCase({
      mode: "assembly",
      suffix: "assembly_demo",
      resolvePath: "/api/assembly/validate",
      generatePath: "/api/assembly/generate",
    });

    const blastCaseIds = await page
      .locator("#blastCaseSelect option")
      .evaluateAll((options) => options.map((option) => option.value));
    for (const caseId of blastCaseIds) {
      await page.locator("#blastCaseSelect").selectOption(caseId);
      await clickApi("#loadPhase13BlastCase", "/api/blast-case");
      await waitForWorkbenchAction();
      await exerciseGeneratedCase({
        mode: "assembly",
        suffix: `phase13_${caseId}`,
        resolvePath: "/api/assembly/validate",
        generatePath: "/api/assembly/generate",
      });
    }

    await page.locator("#modelMode").selectOption("controlled");
    await page.locator("#scene").selectOption("plate_pressure");
    await page.locator("#projectName").fill(generatedProjects.at(-1));
    await clickApi("#openLspp", "/api/project/open-lsprepost");
    await waitForWorkbenchAction();

    for (const [panel, actionId, apiPath] of [
      ["lsppResourcePanel", "importLspp", "/api/config/select-lsprepost"],
      ["exportResourcePanel", "selectExportDir", "/api/config/select-export-dir"],
      ["importResourcePanel", "selectImportPackageDir", "/api/project/select-import-package"],
    ]) {
      await click(`[data-resource-panel="${panel}"]`, `resource:${panel}`);
      await clickApi(`#${actionId}`, apiPath);
      await waitForWorkbenchAction();
      await click(`#${panel} [data-close-resource]`, `close:${panel}`);
    }

    await click('[data-resource-panel="lsppResourcePanel"]', "resource:lsppResourcePanel:manual");
    await page.locator("#lsppResourcePanel details").evaluate((details) => {
      details.open = true;
    });
    await clickApi("#checkLspp", "/api/config/check-lsprepost");
    await waitForWorkbenchAction();
    await clickApi("#saveLspp", "/api/config/lsprepost");
    await waitForWorkbenchAction();
    await click('#lsppResourcePanel [data-close-resource]', "close:lsppResourcePanel:manual");

    await click('[data-resource-panel="exportResourcePanel"]', "resource:exportResourcePanel:manual");
    await page.locator("#exportResourcePanel details").evaluate((details) => {
      details.open = true;
    });
    await page.locator("#exportDir").fill("C:\\mock\\exports");
    await clickApi("#saveExportDir", "/api/config/export-dir");
    await waitForWorkbenchAction();
    await click('#exportResourcePanel [data-close-resource]', "close:exportResourcePanel:manual");

    await click('[data-resource-panel="importResourcePanel"]', "resource:importResourcePanel:manual");
    await page.locator("#importResourcePanel details").evaluate((details) => {
      details.open = true;
    });
    await page.locator("#importPackageDir").fill(`workspace/projects/${generatedProjects[0]}`);
    await clickApi("#importPackage", "/api/project/import-package");
    await waitForWorkbenchAction();
    await click('#importResourcePanel [data-close-resource]', "close:importResourcePanel:manual");

    for (const mode of ["solid", "solid_edges", "wireframe"]) {
      await page.locator("#displayMode").selectOption(mode);
    }
    for (const id of [
      "toggleGrid",
      "toggleLegend",
      "toggleBlastSources",
      "showAllParts",
      "fitView",
      "isoView",
      "topView",
      "frontView",
    ]) {
      await click(`#${id}`);
    }
    await click("#toggleLegend", "toggleLegend:restore");
    await click("#partLegend .part-legend-item .part-name", "dynamicPartSelect");
    await click("#isolateSelectedPart");
    await click("#clearPartSelection");
    await click("#partLegend .part-legend-item .part-name", "dynamicPartReselect");
    await click("#hideSelectedPart");
    await click("#showAllParts", "showAllParts:restore");
    await click("#fullscreenView");
    if (await page.evaluate(() => Boolean(document.fullscreenElement))) {
      await page.evaluate(() => document.exitFullscreen());
    }

    const resultStatusPromise = page.waitForResponse(
      (response) => new URL(response.url()).pathname === "/api/solve/status"
    );
    await click("#resultViewMode");
    await resultStatusPromise;
    await clickApi("#refreshResultStatus", "/api/solve/status");
    assert(
      await page.locator("#resultPlay").isDisabled(),
      "The unimplemented browser d3plot playback control must remain disabled."
    );
    await click("#modelViewMode");

    await click('[data-inspector-target="inspectorSolve"]', "tab:solve");
    await clickApi("#importLsrun", "/api/config/select-lsrun");
    await waitForWorkbenchAction();
    await clickApi("#importLsdyna", "/api/config/select-lsdyna");
    await waitForWorkbenchAction();
    await page.locator("#inspectorSolve details").first().locator("summary").click();
    await clickApi("#checkLsrun", "/api/config/check-lsrun");
    await waitForWorkbenchAction();
    await clickApi("#saveLsrun", "/api/config/lsrun");
    await waitForWorkbenchAction();
    await clickApi("#checkLsdyna", "/api/config/check-lsdyna");
    await waitForWorkbenchAction();
    await clickApi("#saveLsdyna", "/api/config/lsdyna");
    await waitForWorkbenchAction();

    const currentProject = await page.locator("#projectName").inputValue();
    await page.locator("#solveProjectConfirmation").evaluate((input) => {
      input.closest("details").open = true;
    });
    await page.locator("#solveProjectConfirmation").fill(currentProject);
    await clickApi("#runLsdyna", "/api/solve/run-lsdyna");
    await waitForWorkbenchAction();
    await clickApi("#sendToLsrun", "/api/solve/open-lsrun");
    await waitForWorkbenchAction();
    await clickApi("#recoverLsrun", "/api/solve/recover-lsrun");
    await waitForWorkbenchAction();
    await clickApi("#openResultLspp", "/api/project/open-result-lsprepost");
    await waitForWorkbenchAction();
    await clickApi("#readSolveStatus", "/api/solve/status");
    await waitForWorkbenchAction();

    await click('[data-inspector-target="cityImpactSection"]', "tab:impact");
    await clickApi("#readCityImpact", "/api/project/city-impact");
    await waitForWorkbenchAction();
    await click("#cityImpactObjects .impact-object", "dynamicImpactObject");
    await clickApi("#exportCityImpact", "/api/project/city-impact-report");
    await waitForWorkbenchAction();

    await click('[data-inspector-target="inspectorProjects"]', "tab:projects");
    await click("#projects .project-item button", "dynamicProjectUse");
    const compareOptions = await page.locator("#compareProjectA option").count();
    assert(compareOptions >= 2, "At least two generated projects are required for compare patrol.");
    await page.locator("#compareProjectA").selectOption({ index: 0 });
    await page.locator("#compareProjectB").selectOption({ index: 1 });
    await clickApi("#compareBlastRuns", "/api/solve/compare");
    await waitForWorkbenchAction();
    await click('[data-inspector-target="inspectorResults"]', "tab:results");

    await click("#startPhase17City");
    await page.waitForFunction(
      () =>
        document.querySelector("#phase17EditorStatus")?.textContent.startsWith("草案 r") &&
        !document.querySelector("#phase17Canvas")?.classList.contains("hidden"),
      null,
      { timeout: 120000 }
    );
    await click("#phase17EditorTab");
    await click("#phase17ObjectsTab");
    await page.locator("#phase17ObjectSelect").selectOption("parked_vehicle_1");
    await click("#phase17TranslateMode");
    const vehicleX = Number(await page.locator("#phase17X").inputValue());
    await page.locator("#phase17X").fill((vehicleX + 0.01).toFixed(6));
    await click("#phase17ApplyTransform");
    await page.waitForTimeout(400);
    await click("#phase17Undo");
    await page.waitForTimeout(400);
    await click("#phase17Redo");
    await page.waitForTimeout(400);
    await click("#phase17Reset");
    await page.waitForFunction(
      () => !document.querySelector("#phase17DuplicateComponent")?.disabled,
      null,
      { timeout: 120000 }
    );
    await click("#phase17RotateMode");
    await clickApi("#phase17DuplicateComponent", "/api/editor/city-component");
    await clickApi("#phase17DeleteComponent", "/api/editor/city-component");
    await click("#phase17LibraryTab");
    const libraryButtons = page.locator("#phase17LibraryList button[data-city-add]");
    assert((await libraryButtons.count()) >= 3, "Phase 17 component library is incomplete.");
    await clickApi(
      "#phase17LibraryList button[data-city-add]",
      "/api/editor/city-component",
      "dynamicPhase17LibraryAdd"
    );
    await page.waitForFunction(
      () => !document.querySelector("#phase17Generate")?.disabled,
      null,
      { timeout: 120000 }
    );

    const phase17Project = `${projectPrefix}_city`;
    await page.locator("#phase17ProjectName").fill(phase17Project);
    const editorResult = await clickApi("#phase17Generate", "/api/editor/generate");
    await page.waitForFunction(
      (name) => document.querySelector("#phase17EditorStatus")?.textContent.includes(name),
      editorResult.project,
      { timeout: 120000 }
    );
    await clickApi("#phase17ValidateLspp", "/api/editor/validate-lsprepost");
    await page.waitForFunction(
      () => !document.querySelector("#phase17ValidationImage")?.classList.contains("hidden"),
      null,
      { timeout: 5000 }
    );
    await click("#phase17ValidationImage");
    assert(
      (await page.evaluate(() => window.__uiPatrolOpenedUrls.length)) === 1,
      "Phase 17 validation image button did not open its artifact URL."
    );
    exercisedCases.push({ mode: "phase17_city", scene: "city_street_blast", project: editorResult.project });

    const requiredButtonIds = [
      "refresh", "importLspp", "checkLspp", "saveLspp", "selectExportDir",
      "saveExportDir", "selectImportPackageDir", "importPackage", "loadPhase13BlastCase",
      "loadBlastDemo", "addComponent", "addPhysicsAction", "resolve", "generate", "preview",
      "openLspp", "startPhase17City", "modelViewMode", "resultViewMode", "toggleGrid",
      "toggleLegend", "toggleBlastSources", "showAllParts", "fitView", "isoView", "topView",
      "frontView", "fullscreenView", "clearPartSelection", "isolateSelectedPart",
      "hideSelectedPart", "refreshResultStatus", "phase17EditorTab", "phase17ObjectsTab",
      "phase17LibraryTab", "phase17TranslateMode", "phase17RotateMode",
      "phase17ApplyTransform", "phase17Undo", "phase17Redo", "phase17Reset",
      "phase17DuplicateComponent", "phase17DeleteComponent", "phase17Generate",
      "phase17ValidateLspp", "phase17ValidationImage", "readCityImpact",
      "exportCityImpact", "importLsrun", "importLsdyna", "checkLsrun", "saveLsrun",
      "checkLsdyna", "saveLsdyna", "runLsdyna", "sendToLsrun", "recoverLsrun",
      "openResultLspp", "readSolveStatus", "compareBlastRuns",
    ];
    const missingClicks = requiredButtonIds.filter((id) => !clicked.has(id));
    assert(missingClicks.length === 0, `Buttons not exercised: ${missingClicks.join(", ")}`);
    assert(pageErrors.length === 0, `Browser errors: ${pageErrors.join(" | ")}`);
    assert(failedRequests.length === 0, `Failed requests: ${failedRequests.join(" | ")}`);

    const report = {
      ok: true,
      project_prefix: projectPrefix,
      button_ids_exercised: requiredButtonIds.length,
      result_play_verified_disabled: true,
      controlled_scene_count: 4,
      cases: exercisedCases,
      generated_projects: [...new Set(generatedProjects)],
      mocked_external_calls: [...new Set(mockedExternalCalls)],
      page_errors: pageErrors,
      failed_requests: failedRequests,
    };
    fs.writeFileSync(
      path.join(evidenceDir, "frontend-patrol.json"),
      `${JSON.stringify(report, null, 2)}\n`,
      "utf8"
    );
    process.stdout.write(`${JSON.stringify(report)}\n`);
  } finally {
    await browser.close();
  }
}

run().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
