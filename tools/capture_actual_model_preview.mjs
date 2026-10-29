import { generatedPath } from "./work-paths.mjs";
import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "file:///C:/Users/14989/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";

const baseUrl = process.argv[2] ?? "http://127.0.0.1:8767";
const outputDir = process.argv[3] ?? generatedPath("soft_copyright_work", "runtime_screens_actual");
const projectName = process.argv[4] ?? "web_phase17_city_ground_crater_validation_v5_v2";
const fullName = "城市关键基础设施爆炸毁伤数字化建模与智能评估系统";
const impactProjectName = "web_phase17_city_street_blast_response_v3_details";

await fs.mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({
  headless: true,
  executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
  args: ["--use-angle=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"],
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 1,
  locale: "zh-CN",
});
const page = await context.newPage();

page.on("console", (message) => {
  if (message.type() === "error") process.stderr.write(`[browser] ${message.text()}\n`);
});
page.on("pageerror", (error) => process.stderr.write(`[pageerror] ${error.stack ?? error.message}\n`));

async function normalizeBrand() {
  await page.evaluate((name) => {
    document.title = name;
    const title = document.querySelector("#legacyWorkbenchRoot .topbar h1");
    if (title) title.textContent = name;
  }, fullName);
}

async function shot(name) {
  await normalizeBrand();
  await page.screenshot({
    path: path.join(outputDir, name),
    fullPage: false,
    animations: "disabled",
  });
}

async function selectInspector(target) {
  await page.click(`[data-inspector-target="${target}"]`);
  await page.waitForTimeout(250);
}

await page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 30_000 });
await page.waitForSelector("#legacyWorkbenchRoot:not(.hidden)");
await page.waitForFunction(() => document.querySelectorAll("#projects .project-item").length > 0, null, { timeout: 30_000 });
await normalizeBrand();

await page.fill("#projectName", projectName);
await page.evaluate(async (name) => {
  await loadInteractiveMesh(name);
}, projectName);
await page.waitForFunction(
  (name) => document.querySelector("#contextStatus")?.textContent?.includes(name),
  projectName,
  { timeout: 90_000 },
);
await page.waitForTimeout(2_000);
await page.click("#fitView");
await page.waitForTimeout(1_000);

const metrics = await page.evaluate(() => {
  const canvas = document.querySelector("#modelCanvas");
  const legend = document.querySelectorAll("#partLegend .legend-item, #partLegend button").length;
  return {
    renderer: canvas?.dataset.renderer ?? "",
    width: canvas?.width ?? 0,
    height: canvas?.height ?? 0,
    contextStatus: document.querySelector("#contextStatus")?.textContent ?? "",
    legend,
  };
});
process.stdout.write(`${JSON.stringify(metrics)}\n`);

await selectInspector("inspectorProjects");
await shot("01-actual-model-overview.png");

await selectInspector("inspectorSolve");
await shot("02-actual-model-solver.png");

await page.selectOption("#displayMode", "solid_edges");
await page.click("#isoView");
await page.locator("#partLegend .part-legend-item", { hasText: "商业超市" }).click();
await page.waitForTimeout(500);
await shot("03-actual-model-wireframe.png");
await page.click("#clearPartSelection");

await page.selectOption("#displayMode", "solid_edges");
await page.click("#topView");
await page.waitForTimeout(500);
await shot("04-actual-model-top.png");

await page.click("#frontView");
await page.waitForTimeout(500);
await shot("05-actual-model-front.png");

await page.click("#isoView");
await page.waitForTimeout(500);
await page.click("#toggleBlastSources");
await page.waitForTimeout(250);
await page.click("#toggleBlastSources");
await page.waitForTimeout(250);
await shot("06-actual-model-blast-source.png");

await page.click("#toggleLegend");
await page.waitForTimeout(250);
await page.click("#toggleLegend");
await page.waitForTimeout(250);
await shot("07-actual-model-layers.png");

await page.click("#resultViewMode");
await page.waitForTimeout(700);
await shot("08-actual-model-validation.png");
await page.click("#modelViewMode");
await page.waitForTimeout(400);

await page.fill("#projectName", impactProjectName);
await page.evaluate(async (name) => {
  await loadInteractiveMesh(name);
}, impactProjectName);
await page.click("#fitView");
await selectInspector("cityImpactSection");
await page.click("#readCityImpact");
await page.waitForFunction(() => document.querySelector("#cityImpactStatus")?.textContent?.includes("100.0%"), null, { timeout: 60_000 });
await page.locator("#cityImpactObjects .impact-object", { hasText: "商业超市" }).click();
await page.waitForTimeout(700);
await shot("09-actual-model-impact.png");

await browser.close();
