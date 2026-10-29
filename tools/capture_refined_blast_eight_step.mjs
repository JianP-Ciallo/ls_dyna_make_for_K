import { createRequire } from "node:module";
import fs from "node:fs/promises";
import path from "node:path";

const require = createRequire(import.meta.url);
const playwrightRoot = process.argv[2];
const outputDir = process.argv[3];
const baseUrl = process.argv[4] ?? "http://127.0.0.1:8765";
if (!playwrightRoot || !outputDir) {
  throw new Error("usage: node capture_refined_blast_eight_step.mjs <node_modules> <output-dir> [base-url]");
}
const { chromium } = require(path.join(playwrightRoot, "playwright"));

const scenarios = [
  {
    assetId: "commercial_supermarket_detailed_building",
    slug: "commercial-supermarket",
    label: "商业超市",
    meshProfile: "standard",
    airCellSize: "0.225",
    groundCellSize: "0.25",
    tntMass: "2.0",
    tntPosition: ["-2.0", "1.5", "4.0"],
  },
  {
    assetId: "residential_community_detailed_building",
    slug: "residential-community",
    label: "住宅建筑",
    meshProfile: "coarse",
    airCellSize: "0.30",
    groundCellSize: "0.30",
    tntMass: "1.5",
    tntPosition: ["-1.5", "2.0", "3.0"],
  },
  {
    assetId: "subway_entrance_detailed_building",
    slug: "subway-entrance",
    label: "地铁入口",
    meshProfile: "fine",
    airCellSize: "0.20",
    groundCellSize: "0.15",
    tntMass: "1.0",
    // The subway asset publishes a real grade elevation of 2.7 m.
    // Keep this no-generation acceptance draft above grade so it is also
    // physically admissible when the same configuration is later compiled.
    tntPosition: ["-1.0", "1.0", "4.0"],
  },
];

await fs.mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ channel: "msedge", headless: true });
const context = await browser.newContext({
  viewport: { width: 1920, height: 1200 },
  deviceScaleFactor: 1,
});
const page = await context.newPage();
const records = [];
const acceptance = [];
const audits = [];

async function shot(name, label, scenario) {
  const target = path.join(outputDir, name);
  await page.screenshot({ path: target, fullPage: true });
  records.push({ name, label, scenario: scenario.assetId, url: page.url() });
}

async function visualAudit(scenario, step) {
  const result = await page.evaluate(() => {
    const shell = document.querySelector(".refined-blast-shell");
    const panel = document.querySelector("[data-refined-schema-panel]");
    if (!shell || !panel) return { shellMissing: !shell, panelMissing: !panel };
    const panelRect = panel.getBoundingClientRect();
    const controls = [...panel.querySelectorAll("input, select, textarea, button")]
      .filter((node) => node.getClientRects().length > 0)
      .map((node) => {
        const rect = node.getBoundingClientRect();
        return {
          name: node.getAttribute("name") ?? node.id ?? node.tagName,
          left: rect.left,
          right: rect.right,
          width: rect.width,
        };
      });
    const clippedControls = controls.filter((row) => (
      row.width <= 0 || row.left < panelRect.left - 1 || row.right > panelRect.right + 1
    ));
    const horizontalOverflow = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
    return {
      shellMissing: false,
      panelMissing: false,
      horizontalOverflow,
      panelHorizontalOverflow: panel.scrollWidth > panel.clientWidth + 2,
      clippedControls,
      panelTextLength: (panel.textContent ?? "").trim().length,
    };
  });
  const passed = !result.shellMissing && !result.panelMissing
    && !result.horizontalOverflow && !result.panelHorizontalOverflow
    && result.clippedControls.length === 0 && result.panelTextLength > 0;
  const record = { assetId: scenario.assetId, step, passed, ...result };
  audits.push(record);
  if (!passed) throw new Error(`visual layout audit failed: ${JSON.stringify(record)}`);
}

async function selectPath(pathValue, value) {
  const control = page.locator(`[data-refined-draft-path="${pathValue}"]`).first();
  await control.waitFor({ timeout: 15000 });
  const tag = await control.evaluate((node) => node.tagName);
  if (tag === "SELECT") await control.selectOption(value);
  else await control.fill(String(value));
  await control.dispatchEvent("change");
}

async function setVector(pathValue, values) {
  const controls = page.locator(`[data-refined-draft-path="${pathValue}"]`);
  if (await controls.count() !== 3) throw new Error(`expected three vector controls for ${pathValue}`);
  for (let index = 0; index < 3; index += 1) {
    await controls.nth(index).fill(values[index]);
    await controls.nth(index).dispatchEvent("change");
  }
}

async function waitUntilReady() {
  await page.locator("#refinedBlastAsset").waitFor({ timeout: 15000 });
  await page.locator("#refinedBlastPreviewStatus").filter({ hasText: "能力描述已载入" }).waitFor({ timeout: 15000 });
}

await page.goto(`${baseUrl}/refined-building-blast`, { waitUntil: "networkidle" });
await waitUntilReady();

for (let scenarioIndex = 0; scenarioIndex < scenarios.length; scenarioIndex += 1) {
  const scenario = scenarios[scenarioIndex];
  if (scenarioIndex > 0) {
    page.once("dialog", (dialog) => dialog.accept());
    await page.locator("[data-refined-new-scenario]").click();
    await page.locator("[data-refined-project-summary]").filter({ hasText: "待创建" }).waitFor({ timeout: 10000 });
    await waitUntilReady();
  }

  await page.locator('[data-refined-section="1"]').click();
  await page.locator("#refinedBlastAsset").selectOption(scenario.assetId);
  await page.waitForTimeout(300);
  await page.locator('[data-refined-section="7"]').click();
  await page.locator("#refinedBlastProvider").selectOption("solver_complete_ale_fsi");
  await page.waitForTimeout(300);

  for (let step = 1; step <= 8; step += 1) {
    await page.locator(`[data-refined-section="${step}"]`).click();
    if (step === 6) {
      await selectPath("building.mesh_profile", scenario.meshProfile);
      await selectPath("draft.load_provider.provider_input.air_cell_size_m", scenario.airCellSize);
      await selectPath("draft.load_provider.provider_input.ground_cell_size_m", scenario.groundCellSize);
    }
    if (step === 7) {
      await selectPath("draft.load_provider.provider_input.tnt_equivalent_mass_kg", scenario.tntMass);
      await setVector("draft.load_provider.provider_input.charge_position_m", scenario.tntPosition);
    }
    await page.waitForTimeout(250);
    await visualAudit(scenario, step);
    await shot(
      `${String(scenarioIndex + 1).padStart(2, "0")}-${scenario.slug}-step-${String(step).padStart(2, "0")}.png`,
      `${scenario.label} · 八步配置 ${step}/8`,
      scenario,
    );
  }

  await page.locator("[data-refined-save]").click();
  await page.waitForURL(/project_id=/, { timeout: 15000 });
  await page.getByText("已保存到独立项目", { exact: true }).first().waitFor({ timeout: 15000 });
  const projectUrl = page.url();
  await shot(`${String(scenarioIndex + 1).padStart(2, "0")}-${scenario.slug}-saved.png`, `${scenario.label} · 草稿已保存且未编译 K 包`, scenario);

  await page.locator("[data-refined-preview]").click();
  await page.locator("#refinedBlastPreviewStatus").filter({ hasText: "预览 revision" }).waitFor({ timeout: 20000 });
  await shot(`${String(scenarioIndex + 1).padStart(2, "0")}-${scenario.slug}-preview.png`, `${scenario.label} · 轻量三维预览`, scenario);

  await page.locator("[data-refined-validate]").last().click();
  await page.waitForTimeout(700);
  await page.locator('[data-refined-inspector-tab="checks"]').click();
  await shot(`${String(scenarioIndex + 1).padStart(2, "0")}-${scenario.slug}-validation.png`, `${scenario.label} · 当前保存修订检查`, scenario);

  await page.locator("[data-refined-back]").click();
  await page.locator("#openRefinedBlastWorkbench").waitFor({ timeout: 10000 });
  await page.locator("#openRefinedBlastWorkbench").click();
  await page.waitForURL(/refined-building-blast/, { timeout: 10000 });
  await page.locator("[data-refined-project-summary]").filter({ hasText: "refined-blast-" }).waitFor({ timeout: 15000 });
  const restoredAsset = await page.locator("#refinedBlastAsset").inputValue();
  await page.locator('[data-refined-section="7"]').click();
  const restoredProvider = await page.locator("#refinedBlastProvider").inputValue();
  await shot(`${String(scenarioIndex + 1).padStart(2, "0")}-${scenario.slug}-restored.png`, `${scenario.label} · 返回后恢复同一项目`, scenario);
  acceptance.push({
    assetId: scenario.assetId,
    providerId: "solver_complete_ale_fsi",
    projectUrl,
    restoredAsset,
    restoredProvider,
    meshProfile: scenario.meshProfile,
    airCellSize: Number(scenario.airCellSize),
    groundCellSize: Number(scenario.groundCellSize),
    tntMass: Number(scenario.tntMass),
    tntPosition: scenario.tntPosition.map(Number),
  });
}

await fs.writeFile(
  path.join(outputDir, "acceptance.json"),
  JSON.stringify({ schema_version: "phase18f.eight_step_acceptance@1", acceptance, audits, records }, null, 2),
  "utf8",
);
await browser.close();
console.log(JSON.stringify({ outputDir, scenarios: acceptance.length, screenshots: records.length, audits: audits.length, acceptance }));
