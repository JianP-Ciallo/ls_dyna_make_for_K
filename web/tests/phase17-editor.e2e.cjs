"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const baseUrl = process.env.PHASE17_BASE_URL || "http://127.0.0.1:8765/";
const evidenceDir =
  process.env.PHASE17_EVIDENCE_DIR ||
  path.resolve(__dirname, "..", "..", "workspace", "phase17_web_e2e");

function browserExecutable() {
  const configured = process.env.PHASE17_BROWSER_EXE;
  if (configured) {
    if (!fs.existsSync(configured)) {
      throw new Error(`PHASE17_BROWSER_EXE does not exist: ${configured}`);
    }
    return configured;
  }
  const bundled = chromium.executablePath();
  if (fs.existsSync(bundled)) return bundled;
  const candidates =
    process.platform === "win32"
      ? [
          "C:/Program Files/Google/Chrome/Application/chrome.exe",
          "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
          "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
        ]
      : ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"];
  const found = candidates.find((candidate) => fs.existsSync(candidate));
  if (!found) {
    throw new Error(
      "No Chromium browser found. Install Playwright Chromium or set PHASE17_BROWSER_EXE."
    );
  }
  return found;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function canvasEvidence(page) {
  return page.locator("#phase17Canvas").evaluate(
    (canvas) =>
      new Promise((resolve, reject) => {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            try {
              const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
              if (!gl) throw new Error("Phase 17 canvas has no WebGL context");
              const width = Number(canvas.width);
              const height = Number(canvas.height);
              if (width < 100 || height < 100) {
                throw new Error(`Phase 17 canvas is too small: ${width}x${height}`);
              }
              const pixels = new Uint8Array(width * height * 4);
              gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
              const colors = new Set();
              let opaqueSamples = 0;
              const stride = Math.max(
                4,
                Math.floor(pixels.length / 12000 / 4) * 4
              );
              for (let index = 0; index < pixels.length; index += stride) {
                if (pixels[index + 3] > 0) opaqueSamples += 1;
                colors.add(
                  `${pixels[index]},${pixels[index + 1]},${pixels[index + 2]},${pixels[index + 3]}`
                );
                if (colors.size > 64) break;
              }
              resolve({
                width,
                height,
                sampledColorCount: colors.size,
                opaqueSamples,
              });
            } catch (error) {
              reject(error);
            }
          });
        });
      })
  );
}

async function waitForDraft(page, minimumRevision) {
  await page.waitForFunction(
    ({ revision }) => {
      const status = document.querySelector("#phase17EditorStatus")?.textContent || "";
      const options = document.querySelector("#phase17ObjectSelect")?.options.length || 0;
      const canvas = document.querySelector("#phase17Canvas");
      return (
        options >= 3 &&
        canvas &&
        !canvas.classList.contains("hidden") &&
        status.startsWith(`草案 r${revision} `)
      );
    },
    { revision: minimumRevision },
    { timeout: 120000 }
  );
}

async function hasUnsavedWarning(page) {
  return page.evaluate(() => {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  });
}

async function phase17CameraPose(page) {
  return page.evaluate(() => {
    const detail = {};
    window.dispatchEvent(new CustomEvent("phase17:get-camera-pose", { detail }));
    return detail.pose;
  });
}

function cameraPosesMatch(left, right, tolerance = 1.0e-8) {
  if (!left || !right) return false;
  for (const key of ["position", "target", "up"]) {
    if (!Array.isArray(left[key]) || !Array.isArray(right[key])) return false;
    if (left[key].length !== right[key].length) return false;
    for (let index = 0; index < left[key].length; index += 1) {
      if (Math.abs(left[key][index] - right[key][index]) > tolerance) return false;
    }
  }
  return Math.abs(Number(left.zoom) - Number(right.zoom)) <= tolerance;
}

async function run() {
  fs.mkdirSync(evidenceDir, { recursive: true });
  const browser = await chromium.launch({
    headless: process.env.PHASE17_HEADED !== "1",
    executablePath: browserExecutable(),
    args: [
      "--no-sandbox",
      "--disable-gpu-sandbox",
      "--enable-unsafe-swiftshader",
      "--use-angle=swiftshader-webgl",
    ],
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const pageErrors = [];
  const failedRequests = [];
  let previewRequestCount = 0;
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("request", (request) => {
    if (request.url().includes("/api/editor/preview")) previewRequestCount += 1;
  });
  page.on("requestfailed", (request) => {
    failedRequests.push(`${request.url()}: ${request.failure()?.errorText || "failed"}`);
  });

  try {
    await page.goto(baseUrl, { waitUntil: "networkidle", timeout: 30000 });
    await page.locator("#startPhase17City").click();
    await waitForDraft(page, 1);

    assert(
      (await page.locator("#phase17ObjectSelect").inputValue()) === "city_tnt",
      "The real city TNT source was not selected by default."
    );
    const editableObjectIds = await page
      .locator("#phase17ObjectSelect option")
      .evaluateAll((options) => options.map((option) => option.value));
    assert(
      editableObjectIds.includes("subway_entrance"),
      "The subway entrance is missing from the editable city objects."
    );
    assert(
      editableObjectIds.includes("parked_vehicle_1") &&
        editableObjectIds.includes("parked_vehicle_4"),
      "Independent parked vehicles are missing from the editable city objects."
    );
    await page.locator("#phase17ObjectSelect").selectOption("subway_entrance");
    assert(
      await page.locator("#phase17Z").isDisabled(),
      "The grounded subway entrance must not expose vertical translation."
    );
    assert(
      !(await page.locator("#phase17Rz").isDisabled()),
      "The subway entrance must expose plan rotation."
    );
    await page.locator("#phase17ObjectSelect").selectOption("parked_vehicle_1");
    assert(
      await page.locator("#phase17Z").isDisabled(),
      "A surface-dynamic vehicle must remain on the parking surface."
    );
    assert(
      !(await page.locator("#phase17Rz").isDisabled()),
      "A surface-dynamic vehicle must expose plan rotation."
    );
    await page.locator("#phase17ObjectSelect").selectOption("city_tnt");
    for (const id of ["#phase17X", "#phase17Y", "#phase17Z"]) {
      assert(!(await page.locator(id).isDisabled()), `${id} must be enabled for TNT.`);
    }
    assert(
      await page.locator("#phase17Rz").isDisabled(),
      "TNT rotation must remain disabled."
    );
    assert(
      await page.locator("#phase17RotateMode").isDisabled(),
      "TNT rotate mode must remain disabled."
    );

    const desktopCanvas = await canvasEvidence(page);
    assert(
      desktopCanvas.sampledColorCount > 8,
      `Desktop canvas appears blank: ${JSON.stringify(desktopCanvas)}`
    );

    const initialX = Number(await page.locator("#phase17X").inputValue());
    assert(
      await page.locator("#phase17Undo").isDisabled(),
      "Undo must be disabled before the first valid edit."
    );
    await page.locator("#phase17X").fill("");
    await page.locator("#phase17ApplyTransform").click();
    await page.waitForFunction(
      () =>
        document.querySelector("#phase17EditorStatus")?.textContent ===
        "变换值不能为空。",
      null,
      { timeout: 5000 }
    );
    assert(
      await page.locator("#phase17Undo").isDisabled(),
      "A rejected blank transform must not create an undo history entry."
    );

    await page.locator("#phase17X").fill((initialX + 0.25).toFixed(6));
    await page.locator("#phase17ApplyTransform").click();
    await waitForDraft(page, 2);
    assert(
      Math.abs(Number(await page.locator("#phase17X").inputValue()) - initialX - 0.25) <
        1.0e-6,
      "TNT numeric translation was not committed."
    );
    assert(
      await hasUnsavedWarning(page),
      "A committed edit must activate the unsaved-change guard."
    );

    await page.locator("#phase17Undo").click();
    await waitForDraft(page, 3);
    assert(
      Math.abs(Number(await page.locator("#phase17X").inputValue()) - initialX) < 1.0e-6,
      "Undo did not restore the TNT position."
    );
    assert(
      !(await hasUnsavedWarning(page)),
      "Undoing back to the saved template must clear the unsaved-change guard."
    );

    const requestsBeforeBurst = previewRequestCount;
    for (const offset of [0.1, 0.2, 0.3]) {
      await page.locator("#phase17X").fill((initialX + offset).toFixed(6));
      await page.locator("#phase17ApplyTransform").click();
    }
    await waitForDraft(page, 6);
    const burstPreviewRequests = previewRequestCount - requestsBeforeBurst;
    assert(
      burstPreviewRequests >= 1 && burstPreviewRequests <= 2,
      `Rapid preview edits were not coalesced: ${burstPreviewRequests} requests.`
    );
    assert(
      Math.abs(Number(await page.locator("#phase17X").inputValue()) - initialX - 0.3) <
        1.0e-6,
      "The newest coalesced preview edit was not preserved."
    );

    await page.locator("#phase17Reset").click();
    await waitForDraft(page, 7);
    assert(
      !(await hasUnsavedWarning(page)),
      "Resetting to the saved template must clear the unsaved-change guard."
    );

    await page.locator("#topView").click();
    const topPoseBeforeApply = await phase17CameraPose(page);
    assert(topPoseBeforeApply, "Phase 17 camera diagnostics did not return a pose.");
    const stableX = await page.locator("#phase17X").inputValue();
    await page.locator("#phase17X").fill(stableX);
    await page.locator("#phase17ApplyTransform").click();
    await waitForDraft(page, 8);
    const topPoseAfterApply = await phase17CameraPose(page);
    assert(
      cameraPosesMatch(topPoseBeforeApply, topPoseAfterApply),
      `Applying a model edit reset the Phase 17 camera: ${JSON.stringify({
        before: topPoseBeforeApply,
        after: topPoseAfterApply,
      })}`
    );
    await page.locator("#isoView").click();
    const isoPose = await phase17CameraPose(page);
    assert(
      !cameraPosesMatch(topPoseAfterApply, isoPose),
      "The Phase 17 isometric view command did not change the camera."
    );
    await page.locator("#fitView").click();
    const fittedPose = await phase17CameraPose(page);
    assert(
      fittedPose.position[2] > fittedPose.target[2] &&
        Math.abs(fittedPose.position[0] - fittedPose.target[0]) > 1.0e-6 &&
        Math.abs(fittedPose.position[1] - fittedPose.target[1]) > 1.0e-6,
      `The fitted Phase 17 view is not a normal low-oblique view: ${JSON.stringify(
        fittedPose
      )}`
    );

    const poseBeforeComponentAdd = await phase17CameraPose(page);
    await page.locator("#phase17LibraryTab").click();
    await page.waitForFunction(
      () => !document.querySelector("#phase17LibraryPanel")?.classList.contains("hidden"),
      null,
      { timeout: 5000 }
    );
    const addVehicleButton = page.locator(
      '#phase17LibraryList button[data-city-add="parked_vehicle"]'
    );
    assert(
      await addVehicleButton.isEnabled(),
      "The controlled parked-vehicle component is not available for placement."
    );
    await addVehicleButton.click();
    await waitForDraft(page, 9);
    assert(
      (await page.locator("#phase17ObjectSelect").inputValue()) ===
        "parked_vehicle_5",
      "The newly added vehicle was not selected as an independent city object."
    );
    assert(
      cameraPosesMatch(poseBeforeComponentAdd, await phase17CameraPose(page)),
      "Adding a controlled city component reset the camera pose."
    );
    assert(
      await page.locator("#phase17DuplicateComponent").isEnabled(),
      "A selected vehicle cannot be duplicated."
    );
    assert(
      await page.locator("#phase17DeleteComponent").isEnabled(),
      "A selected vehicle cannot be deleted."
    );
    await page.locator("#phase17DuplicateComponent").click();
    await waitForDraft(page, 10);
    assert(
      (await page.locator("#phase17ObjectSelect").inputValue()) ===
        "parked_vehicle_6",
      "Duplicating a vehicle did not create a stable new component id."
    );
    await page.locator("#phase17DeleteComponent").click();
    await waitForDraft(page, 11);
    assert(
      (await page.locator('#phase17ObjectSelect option[value="parked_vehicle_6"]').count()) ===
        0,
      "Deleting a vehicle left its semantic object in the scene."
    );
    assert(
      (await page.locator('#phase17ObjectSelect option[value="parked_vehicle_5"]').count()) ===
        1,
      "Deleting vehicle 6 renumbered the previously added vehicle 5."
    );
    await page.locator("#phase17Undo").click();
    await waitForDraft(page, 12);
    assert(
      (await page.locator('#phase17ObjectSelect option[value="parked_vehicle_6"]').count()) ===
        1,
      "Undo did not restore a deleted component."
    );
    await page.locator("#phase17Redo").click();
    await waitForDraft(page, 13);
    assert(
      (await page.locator('#phase17ObjectSelect option[value="parked_vehicle_6"]').count()) ===
        0,
      "Redo did not reapply component deletion."
    );

    await page.locator("#phase17LibraryTab").click();
    const addSubwayButton = page.locator(
      '#phase17LibraryList button[data-city-add="subway_entrance"]'
    );
    assert(
      await addSubwayButton.isEnabled(),
      "The controlled subway-entrance component is not available for placement."
    );
    await addSubwayButton.click();
    await waitForDraft(page, 14);
    assert(
      (await page.locator("#phase17ObjectSelect").inputValue()) ===
        "subway_entrance_2",
      "Adding a subway entrance did not create the stable second instance."
    );
    assert(
      await page.locator("#phase17ComponentSummary").getByText("求解中固定").isVisible(),
      "The selected subway entrance does not expose its fixed solver semantics."
    );
    assert(
      await page.locator("#phase17ComponentSummary").getByText("参与 ALE/FSI").isVisible(),
      "The selected subway entrance does not expose its ALE/FSI semantics."
    );
    await page.locator("#phase17DuplicateComponent").click();
    await waitForDraft(page, 15);
    assert(
      (await page.locator("#phase17ObjectSelect").inputValue()) ===
        "subway_entrance_3",
      "Duplicating a subway entrance did not create a stable third instance."
    );
    await page.locator("#phase17DeleteComponent").click();
    await waitForDraft(page, 16);
    assert(
      (await page.locator('#phase17ObjectSelect option[value="subway_entrance_3"]').count()) ===
        0,
      "Deleting a subway entrance left its semantic object in the scene."
    );
    assert(
      (await page.locator('#phase17ObjectSelect option[value="subway_entrance_2"]').count()) ===
        1,
      "Deleting subway entrance 3 renumbered subway entrance 2."
    );

    await page.locator("#phase17LibraryTab").click();
    const addShellBoxButton = page.locator(
      '#phase17LibraryList button[data-city-add="shell_box"]'
    );
    assert(
      await addShellBoxButton.isEnabled(),
      "The existing shell-box component is not available for city placement."
    );
    await addShellBoxButton.click();
    await waitForDraft(page, 17);
    assert(
      (await page.locator("#phase17ObjectSelect").inputValue()) === "shell_box_1",
      "Adding a shell box did not create a stable library component instance."
    );
    assert(
      await page.locator("#phase17ComponentSummary").getByText("求解中固定").isVisible(),
      "The shell box does not expose its fixed solver semantics."
    );
    assert(
      await page.locator("#phase17ComponentSummary").getByText("参与 ALE/FSI").isVisible(),
      "The shell box does not expose its ALE/FSI semantics."
    );
    const shellBoxX = Number(await page.locator("#phase17X").inputValue());
    await page.locator("#phase17X").fill((shellBoxX + 0.25).toFixed(6));
    await page.locator("#phase17ApplyTransform").click();
    await waitForDraft(page, 18);
    assert(
      Math.abs(Number(await page.locator("#phase17X").inputValue()) - shellBoxX - 0.25) <
        1.0e-6,
      "The shell-box placement edit was not committed."
    );
    await page.locator("#phase17DuplicateComponent").click();
    await waitForDraft(page, 19);
    assert(
      (await page.locator("#phase17ObjectSelect").inputValue()) === "shell_box_2",
      "Duplicating a shell box did not create a stable second instance."
    );
    await page.locator("#phase17DeleteComponent").click();
    await waitForDraft(page, 20);
    assert(
      (await page.locator('#phase17ObjectSelect option[value="shell_box_2"]').count()) === 0,
      "Deleting shell box 2 left its semantic object in the scene."
    );
    await page.locator("#phase17ObjectSelect").selectOption("shell_box_1");
    assert(
      await page.locator("#phase17DeleteComponent").isEnabled(),
      "The final optional shell-box instance cannot be removed."
    );
    await page.locator("#phase17DeleteComponent").click();
    await waitForDraft(page, 21);
    assert(
      (await page.locator('#phase17ObjectSelect option[value^="shell_box_"]').count()) === 0,
      "Removing the final shell box left a stale semantic object."
    );

    let releaseGeneration;
    let markGenerationStarted;
    const generationRelease = new Promise((resolve) => {
      releaseGeneration = resolve;
    });
    const generationStarted = new Promise((resolve) => {
      markGenerationStarted = resolve;
    });
    await page.route("**/api/editor/generate", async (route) => {
      markGenerationStarted();
      await generationRelease;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          result: {
            project: "stale_phase17_project",
            checks: { ok: true },
          },
        }),
      });
    });
    const originalProjectName = await page.locator("#phase17ProjectName").inputValue();
    await page.locator("#phase17Generate").click();
    await generationStarted;
    await page
      .locator("#phase17ProjectName")
      .fill(`${originalProjectName}_changed_during_generation`);
    releaseGeneration();
    await page.waitForFunction(
      () =>
        document.querySelector("#phase17EditorStatus")?.textContent ===
        "草案或项目名称已更改，旧生成结果已忽略。",
      null,
      { timeout: 5000 }
    );
    assert(
      await page.locator("#phase17ValidateLspp").isDisabled(),
      "A stale generation response must not enable LS-PrePost validation."
    );
    await page.locator("#phase17ProjectName").fill(originalProjectName);
    await page.unroute("**/api/editor/generate");

    await page.locator("#phase17ObjectSelect").selectOption("commercial_supermarket");
    assert(!(await page.locator("#phase17X").isDisabled()), "Building X must be enabled.");
    assert(!(await page.locator("#phase17Y").isDisabled()), "Building Y must be enabled.");
    assert(await page.locator("#phase17Z").isDisabled(), "Grounded building Z must be disabled.");
    assert(
      !(await page.locator("#phase17Rz").isDisabled()),
      "Grounded building yaw must be enabled."
    );
    assert(
      !(await page.locator("#phase17RotateMode").isDisabled()),
      "Grounded building rotate mode must be enabled."
    );

    const desktopPath = path.join(evidenceDir, "phase17_editor_desktop.png");
    await page.screenshot({ path: desktopPath, fullPage: true });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(300);
    const mobileLayout = await page.evaluate(() => ({
      viewportWidth: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
    }));
    assert(
      mobileLayout.documentWidth <= mobileLayout.viewportWidth + 1,
      `Mobile page overflows horizontally: ${JSON.stringify(mobileLayout)}`
    );
    const mobileCanvas = await canvasEvidence(page);
    assert(
      mobileCanvas.sampledColorCount > 8,
      `Mobile canvas appears blank: ${JSON.stringify(mobileCanvas)}`
    );
    const mobilePath = path.join(evidenceDir, "phase17_editor_mobile.png");
    await page.screenshot({ path: mobilePath, fullPage: true });

    assert(pageErrors.length === 0, `Browser errors: ${pageErrors.join(" | ")}`);
    assert(
      failedRequests.length === 0,
      `Failed browser requests: ${failedRequests.join(" | ")}`
    );

    const result = {
      ok: true,
      base_url: baseUrl,
      desktop: { path: desktopPath, canvas: desktopCanvas },
      mobile: { path: mobilePath, canvas: mobileCanvas },
      checks: {
        real_tnt_selected: true,
        tnt_translation_only: true,
        grounded_building_xy_rz_only: true,
        numeric_transform_committed: true,
        undo_restored_position: true,
        blank_transform_rejected: true,
        unsaved_change_guard: true,
        preview_requests_coalesced: true,
        camera_preserved_across_apply: true,
        phase17_view_commands_work: true,
        subway_and_vehicles_editable: true,
        controlled_vehicle_addition_works: true,
        stable_component_duplicate_delete_works: true,
        component_delete_undo_redo_works: true,
        subway_multi_instance_works: true,
        existing_library_shell_box_works: true,
        camera_preserved_across_component_add: true,
        stale_generation_ignored: true,
        no_page_errors: true,
        no_failed_requests: true,
      },
    };
    fs.writeFileSync(
      path.join(evidenceDir, "phase17_web_e2e.json"),
      `${JSON.stringify(result, null, 2)}\n`,
      "utf8"
    );
    process.stdout.write(`${JSON.stringify(result)}\n`);
  } finally {
    await browser.close();
  }
}

run().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
