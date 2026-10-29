"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const baseUrl = process.env.MODEL_VIEWER_BASE_URL;
const projectName = process.env.MODEL_VIEWER_PROJECT
  || "web_phase17_city_ground_crater_validation_v5_v2";
const evidenceDir = process.env.MODEL_VIEWER_EVIDENCE_DIR
  || path.join(process.cwd(), "web", "test-results", "model-viewer-webgl");

if (!baseUrl) throw new Error("MODEL_VIEWER_BASE_URL is required.");
let activeBrowser = null;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function browserExecutable() {
  const configured = process.env.MODEL_VIEWER_BROWSER_EXE;
  const candidates = [
    configured,
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    chromium.executablePath(),
  ].filter(Boolean);
  const executable = candidates.find((candidate) => fs.existsSync(candidate));
  if (!executable) throw new Error("No Chromium browser is available.");
  return executable;
}

async function waitForViewer(page) {
  await page.waitForFunction(
    () => window.__MODEL_VIEWER_METRICS__?.geometryBuilds > 0
      && window.__MODEL_VIEWER_METRICS__?.partCount > 0,
    null,
    { timeout: 60_000 },
  );
  await page.waitForFunction(
    () => document.body.getAttribute("aria-busy") !== "true",
    null,
    { timeout: 60_000 },
  );
}

async function run() {
  fs.mkdirSync(evidenceDir, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    executablePath: browserExecutable(),
    args: ["--no-sandbox", "--disable-gpu-sandbox"],
  });
  activeBrowser = browser;
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.waitForFunction(
    () => document.querySelector("#modelCanvas")?.dataset.renderer,
  );
  const renderer = await page.locator("#modelCanvas").getAttribute("data-renderer");
  assert(renderer === "webgl", `Expected WebGL renderer, received ${renderer}.`);

  await page.locator("#projectName").fill(projectName);
  const coldStarted = Date.now();
  await page.evaluate((name) => {
    window.loadInteractiveMesh(name);
  }, projectName);
  await waitForViewer(page);
  const coldLoadMs = Date.now() - coldStarted;
  const initialMetrics = await page.evaluate(() => ({ ...window.__MODEL_VIEWER_METRICS__ }));
  assert(initialMetrics.partCount >= 20, `Unexpected part count: ${initialMetrics.partCount}`);
  assert(initialMetrics.faceCount >= 30_000, `Unexpected face count: ${initialMetrics.faceCount}`);
  assert(initialMetrics.edgeCount >= 60_000, `Full edge set was not uploaded: ${initialMetrics.edgeCount}`);
  assert(initialMetrics.geometryBuilds === 1, "Initial model should build GPU geometry exactly once.");

  const canvas = page.locator("#modelCanvas");
  const box = await canvas.boundingBox();
  assert(box && box.width > 500 && box.height > 300, "Model canvas has invalid dimensions.");
  await canvas.screenshot({ path: path.join(evidenceDir, "desktop-initial.png") });

  const framesBefore = initialMetrics.frames;
  const interactionStarted = Date.now();
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.72, box.y + box.height * 0.62, { steps: 36 });
  await page.mouse.up();
  await page.waitForTimeout(250);
  const interactionMs = Date.now() - interactionStarted;
  const interactionMetrics = await page.evaluate(() => ({ ...window.__MODEL_VIEWER_METRICS__ }));
  assert(interactionMetrics.geometryBuilds === 1, "Camera interaction rebuilt model geometry.");
  assert(interactionMetrics.frames > framesBefore, "Camera interaction did not render new frames.");
  assert(interactionMetrics.lastRenderMs < 33.4, `Last render exceeded 30 FPS budget: ${interactionMetrics.lastRenderMs} ms.`);
  await canvas.screenshot({ path: path.join(evidenceDir, "desktop-rotated.png") });

  await page.locator("#topView").click();
  await page.waitForTimeout(100);
  await canvas.screenshot({ path: path.join(evidenceDir, "desktop-top.png") });

  const contextRecoveryStatus = await page.evaluate(async () => {
    const target = document.querySelector("#modelCanvas");
    const gl = target.getContext("webgl2") || target.getContext("webgl");
    const extension = gl?.getExtension("WEBGL_lose_context");
    if (!extension) return "extension_unavailable";
    const waitFor = (eventName) => new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error(`${eventName} timeout`)), 5000);
      target.addEventListener(eventName, () => {
        clearTimeout(timeout);
        resolve();
      }, { once: true });
    });
    try {
      const lost = waitFor("webglcontextlost");
      extension.loseContext();
      await lost;
      const restored = waitFor("webglcontextrestored");
      extension.restoreContext();
      await restored;
      return "restored";
    } catch (error) {
      return error.message || "restore_failed";
    }
  });
  if (contextRecoveryStatus === "restored") {
    await page.waitForFunction(
      () => window.__MODEL_VIEWER_METRICS__?.geometryBuilds >= 2,
      null,
      { timeout: 10_000 },
    );
  }

  const warmStarted = Date.now();
  const warmResult = await page.evaluate(async (name) => {
    const response = await fetch(`/api/project/preview-mesh?project_name=${encodeURIComponent(name)}`);
    const payload = await response.json();
    return { status: response.status, ok: payload.ok, partCount: payload.result?.parts?.length || 0 };
  }, projectName);
  const warmLoadMs = Date.now() - warmStarted;
  assert(warmResult.status === 200 && warmResult.ok, "Warm preview request failed.");
  assert(warmResult.partCount === initialMetrics.partCount, "Warm preview payload changed part count.");

  await page.setViewportSize({ width: 900, height: 760 });
  await page.waitForTimeout(150);
  await page.screenshot({ path: path.join(evidenceDir, "narrow-layout.png"), fullPage: true });

  const fallbackPage = await context.newPage();
  await fallbackPage.goto(`${baseUrl}?viewer=canvas`, { waitUntil: "networkidle" });
  await fallbackPage.waitForFunction(
    () => document.querySelector("#modelCanvas")?.dataset.renderer,
  );
  const fallbackRenderer = await fallbackPage.locator("#modelCanvas").getAttribute("data-renderer");
  assert(fallbackRenderer === "canvas", `Canvas fallback was not selected: ${fallbackRenderer}`);
  await fallbackPage.close();

  assert(pageErrors.length === 0, `Browser errors: ${pageErrors.join(" | ")}`);
  const report = {
    ok: true,
    projectName,
    renderer,
    coldLoadMs,
    warmLoadMs,
    interactionMs,
    initialMetrics,
    interactionMetrics,
    contextRecoveryStatus,
    fallbackRenderer,
  };
  fs.writeFileSync(
    path.join(evidenceDir, "model-viewer-webgl.json"),
    JSON.stringify(report, null, 2),
    "utf8",
  );
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  await browser.close();
  activeBrowser = null;
}

run().catch(async (error) => {
  if (activeBrowser) await activeBrowser.close().catch(() => {});
  console.error(error);
  process.exitCode = 1;
});
