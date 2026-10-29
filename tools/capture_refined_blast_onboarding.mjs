import { createRequire } from "node:module";
import fs from "node:fs/promises";
import path from "node:path";

const require = createRequire(import.meta.url);
const playwrightRoot = process.argv[2];
const outputDir = process.argv[3];
const baseUrl = process.argv[4] ?? "http://127.0.0.1:8765";
if (!playwrightRoot || !outputDir) throw new Error("usage: node capture_refined_blast_onboarding.mjs <node_modules> <output-dir> [base-url]");
const { chromium } = require(path.join(playwrightRoot, "playwright"));

await fs.mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ channel: "msedge", headless: true });
const context = await browser.newContext({ viewport: { width: 1920, height: 1200 }, deviceScaleFactor: 1 });
const page = await context.newPage();
const records = [];

async function shot(name, label) {
  const target = path.join(outputDir, name);
  await page.screenshot({ path: target, fullPage: true });
  records.push({ name, label, url: page.url() });
}

await page.goto(`${baseUrl}/refined-building-blast`, { waitUntil: "networkidle" });
await page.locator("[data-refined-onboarding]").waitFor();
await shot("01-first-entry.png", "首次进入：流程指引和待创建项目状态");

await page.locator('[data-refined-section="7"]').click();
await page.locator("#refinedBlastProvider").selectOption("solver_complete_ale_fsi");
await page.waitForTimeout(700);
await shot("02-select-scenario.png", "选择商业超市与真实 ALE/FSI 工况");

await page.locator("[data-refined-save]").click();
await page.waitForURL(/project_id=/, { timeout: 15000 });
await page.getByText("已保存到独立项目", { exact: true }).first().waitFor({ timeout: 15000 });
const projectUrl = page.url();
await shot("03-project-created.png", "首次保存自动创建项目并完成草稿持久化");

await page.locator("[data-refined-preview]").click();
await page.locator("#refinedBlastPreviewStatus").filter({ hasText: "预览 revision" }).waitFor({ timeout: 20000 });
await shot("04-light-preview.png", "刷新轻量三维预览，不生成 K 包");

const positionInputs = page.locator('input[data-refined-draft-path="load_provider.provider_input.charge_position_m"]');
if (await positionInputs.count() === 3) {
  await positionInputs.nth(0).fill("2.5");
  await positionInputs.nth(0).dispatchEvent("change");
  await positionInputs.nth(1).fill("1.5");
  await positionInputs.nth(1).dispatchEvent("change");
  await positionInputs.nth(2).fill("1.2");
  await positionInputs.nth(2).dispatchEvent("change");
  await page.waitForTimeout(900);
}
await shot("05-edit-tnt-position.png", "在前端修改 TNT 爆源 X/Y/Z 位置");

await page.locator("[data-refined-preview]").click();
await page.locator("#refinedBlastPreviewStatus").filter({ hasText: "预览 revision" }).waitFor({ timeout: 20000 });
await page.locator("[data-refined-validate]").last().click();
await page.waitForTimeout(1500);
await page.locator('[data-refined-inspector-tab="checks"]').click();
await shot("06-validation.png", "验证当前持久版本并查看检查结果");

await page.locator("[data-refined-back]").click();
await page.locator("#openRefinedBlastWorkbench").waitFor({ timeout: 10000 });
await page.locator("#openRefinedBlastWorkbench").click();
await page.waitForURL(/refined-building-blast/, { timeout: 10000 });
await page.locator('[data-refined-project-summary]').filter({ hasText: "refined-blast-" }).waitFor({ timeout: 15000 });
const restoredAsset = await page.locator("#refinedBlastAsset").inputValue();
await page.locator('[data-refined-section="7"]').click();
await page.locator("#refinedBlastProvider").waitFor({ timeout: 15000 });
const restoredProvider = await page.locator("#refinedBlastProvider").inputValue();
await shot("07-return-and-restore.png", "返回普通工作台后再次进入，恢复同一项目和工况");

page.once("dialog", (dialog) => dialog.accept());
await page.locator("[data-refined-new-scenario]").click();
await page.locator('[data-refined-project-summary]').filter({ hasText: "待创建" }).waitFor({ timeout: 10000 });
await page.locator('[data-refined-section="1"]').click();
await page.locator("#refinedBlastAsset").selectOption("residential_community_detailed_building");
await page.locator('[data-refined-section="7"]').click();
await page.locator("#refinedBlastProvider").selectOption("imported_pressure_history");
await page.waitForTimeout(500);
await shot("08-uncreated-selection.png", "未建项时选择住宅与导入压力时程");

await page.locator("[data-refined-back]").click();
await page.locator("#openRefinedBlastWorkbench").click();
await page.waitForURL(/refined-building-blast/, { timeout: 10000 });
await page.locator('[data-refined-project-summary]').filter({ hasText: "待创建" }).waitFor({ timeout: 10000 });
const uncreatedAsset = await page.locator("#refinedBlastAsset").inputValue();
await page.locator('[data-refined-section="7"]').click();
const uncreatedProvider = await page.locator("#refinedBlastProvider").inputValue();
await shot("09-uncreated-return-and-restore.png", "未保存建项也能在返回后恢复工况选择");

await fs.writeFile(path.join(outputDir, "acceptance.json"), JSON.stringify({
  projectUrl,
  restoredProvider,
  restoredAsset,
  uncreatedProvider,
  uncreatedAsset,
  records,
}, null, 2), "utf8");
await browser.close();
console.log(JSON.stringify({ outputDir, projectUrl, restoredProvider, restoredAsset, uncreatedProvider, uncreatedAsset, screenshots: records.length }));
