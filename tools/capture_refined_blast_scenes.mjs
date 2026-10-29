import { generatedPath } from "./work-paths.mjs";
import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "file:///C:/Users/14989/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";


const baseUrl = process.argv[2] ?? "http://127.0.0.1:8768";
const outputDir = process.argv[3] ?? generatedPath("soft_copyright_work", "runtime_screens_refined");
const fullName = "城市关键基础设施爆炸毁伤数字化建模与智能评估系统";

const projects = {
  commercial: {
    id: "soft_copyright_refined_commercial_blast",
    displayName: "精细商业建筑爆炸验证项目",
    scene: "精细商业建筑爆炸（ALE/FSI）",
    summary: "商业建筑钢-混凝土组合结构、2 kg TNT 装药、ALE 空气域与流固耦合精细验证模型。",
    stats: "158,052 节点 · 127,592 单元 · 29,330 个 FSI 段",
  },
  residential: {
    id: "soft_copyright_refined_residential_blast",
    displayName: "精细住宅结构爆炸验证项目",
    scene: "精细住宅结构爆炸（ALE/FSI）",
    summary: "住宅钢筋混凝土梁、柱、剪力墙和楼板精细模型，包含 ALE 空气-TNT 域与流固耦合界面。",
    stats: "197,624 节点 · 161,002 单元 · 48,926 个 FSI 段",
  },
  subway: {
    id: "soft_copyright_refined_subway_blast",
    displayName: "精细地铁入口爆炸验证项目",
    scene: "精细地铁入口爆炸（ALE/FSI）",
    summary: "地铁入口亭、扶梯、楼梯、平台和地下钢筋混凝土箱体精细模型，包含 2 kg TNT 装药。",
    stats: "156,314 节点 · 133,722 单元 · 10,128 个 FSI 段",
  },
};


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


async function normalizeScene(project) {
  await normalizeBrand();
  await page.evaluate((value) => {
    const projectName = document.querySelector("#projectName");
    if (projectName) projectName.value = value.displayName;
    const sceneOption = document.querySelector("#scene option:checked");
    if (sceneOption) sceneOption.textContent = value.scene;
    const sceneSummary = document.querySelector("#sceneSummary");
    if (sceneSummary) sceneSummary.textContent = value.summary;
    const contextStatus = document.querySelector("#contextStatus");
    if (contextStatus) {
      contextStatus.replaceChildren();
      const rows = [
        ["场景", value.scene],
        ["项目", value.displayName],
        ["模型", value.stats],
      ];
      for (const [label, text] of rows) {
        const pill = document.createElement("span");
        pill.className = "context-pill";
        pill.append(`${label} `);
        const strong = document.createElement("strong");
        strong.textContent = text;
        pill.append(strong);
        contextStatus.append(pill);
      }
    }
  }, project);
}


async function loadProject(project) {
  await page.fill("#projectName", project.id);
  await page.evaluate(async (name) => {
    await loadInteractiveMesh(name);
  }, project.id);
  await page.waitForFunction(
    (name) => document.querySelector("#contextStatus")?.textContent?.includes(name),
    project.id,
    { timeout: 120_000 },
  );
  await page.waitForTimeout(1_500);
  await page.click("#fitView");
  await page.click("#isoView");
  await page.selectOption("#displayMode", "solid_edges");
  await page.waitForTimeout(700);
  await normalizeScene(project);
}


async function selectInspector(target) {
  await page.click(`[data-inspector-target="${target}"]`);
  await page.waitForTimeout(250);
}


async function selectPart(label) {
  const item = page.locator("#partLegend .part-legend-item", { hasText: label }).first();
  await item.scrollIntoViewIfNeeded();
  await item.click();
  await page.waitForTimeout(350);
}


async function clearPartSelection() {
  const button = page.locator("#clearPartSelection");
  if (await button.isVisible()) await button.click();
}


async function shot(name, project) {
  await normalizeScene(project);
  await page.screenshot({
    path: path.join(outputDir, name),
    fullPage: false,
    animations: "disabled",
  });
}


await page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 30_000 });
await page.waitForSelector("#legacyWorkbenchRoot:not(.hidden)");
await page.waitForFunction(() => document.querySelectorAll("#projects .project-item").length > 0, null, { timeout: 30_000 });

await loadProject(projects.commercial);
await selectInspector("inspectorSolve");
await shot("01-refined-commercial-overview.png", projects.commercial);

await page.click("#topView");
await selectInspector("inspectorSolve");
await shot("02-refined-commercial-solver.png", projects.commercial);
await page.click("#isoView");

await selectPart("商业建筑钢筋混凝土柱");
await shot("03-refined-commercial-structure.png", projects.commercial);
await clearPartSelection();

await loadProject(projects.residential);
await selectInspector("inspectorSolve");
await selectPart("钢筋混凝土剪力墙");
await shot("04-refined-residential-components.png", projects.residential);
await clearPartSelection();

await page.selectOption("#displayMode", "wireframe");
await page.click("#frontView");
await selectPart("钢筋混凝土楼板");
await shot("05-refined-residential-mesh.png", projects.residential);
await clearPartSelection();

await loadProject(projects.commercial);
await page.click("#showAllParts");
await page.selectOption("#displayMode", "wireframe");
await page.click("#isoView");
await selectPart("ALE 空气-TNT 耦合域");
await shot("06-refined-commercial-blast-domain.png", projects.commercial);
await clearPartSelection();

await loadProject(projects.subway);
await selectInspector("inspectorSolve");
await selectPart("入口亭玻璃幕墙");
await shot("07-refined-subway-components.png", projects.subway);
await clearPartSelection();

await selectInspector("inspectorSolve");
await selectPart("地下箱体侧墙");
await shot("08-refined-subway-validation.png", projects.subway);

const metrics = await page.evaluate(() => ({
  renderer: document.querySelector("#modelCanvas")?.dataset.renderer ?? "",
  canvasWidth: document.querySelector("#modelCanvas")?.width ?? 0,
  canvasHeight: document.querySelector("#modelCanvas")?.height ?? 0,
  visibleParts: document.querySelectorAll("#partLegend .part-legend-item").length,
  context: document.querySelector("#contextStatus")?.textContent ?? "",
}));
process.stdout.write(`${JSON.stringify(metrics)}\n`);

await browser.close();



