import { generatedPath } from "./work-paths.mjs";
import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const baseUrl = process.argv[2] ?? "http://127.0.0.1:8766";
const outputDir = process.argv[3] ?? generatedPath("soft_copyright_work", "runtime_screens_v2");
const fullName = "城市关键基础设施爆炸毁伤数字化建模与智能评估系统";

await fs.mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({ headless: true, executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe" });
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 1,
  locale: "zh-CN",
});
const page = await context.newPage();

async function normalizeBrand() {
  await page.evaluate((name) => {
    document.title = name;
    const legacyTitle = document.querySelector("#legacyWorkbenchRoot .topbar h1");
    if (legacyTitle) legacyTitle.textContent = name;
    const refinedTitle = document.querySelector("#refinedBlastWorkbenchTitle");
    if (refinedTitle) refinedTitle.textContent = name;
    const refinedButton = document.querySelector("#openRefinedBlastWorkbench");
    if (refinedButton) refinedButton.textContent = "关键基础设施精细化爆炸";
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

await page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 15000 });
await page.waitForTimeout(1500);
await page.waitForSelector("#legacyWorkbenchRoot:not(.hidden)");
await normalizeBrand();
await shot("01-launch-workbench.png");

await page.click("#openRefinedBlastWorkbench");
await page.waitForSelector("#refinedBlastWorkbenchRoot:not(.hidden) #refinedBlastWorkbenchTitle");
await page.waitForTimeout(3000);
await page.waitForTimeout(300);
await shot("02-refined-overview.png");

await page.click('[data-refined-section="2"]');
await page.waitForTimeout(250);
await shot("03-structure-configuration.png");

await page.click('[data-refined-section="5"]');
await page.waitForTimeout(250);
await shot("04-material-configuration.png");

await page.click('[data-refined-section="6"]');
await page.waitForTimeout(250);
await shot("05-mesh-configuration.png");

await page.click('[data-refined-section="7"]');
await page.waitForTimeout(250);
await shot("06-blast-load-configuration.png");

await page.click('[data-refined-preview]');
await page.waitForFunction(() => {
  const text = document.querySelector("#refinedBlastPreviewStatus")?.textContent ?? "";
  return text.includes("revision") || text.includes("被验证阻断") || text.includes("请求失败");
}, { timeout: 3000 }).catch(() => {});
await page.waitForTimeout(800);
await page.click('[data-refined-layer-toggle]');
await page.waitForTimeout(250);
await shot("07-layered-preview.png");

await page.click('[data-refined-section="8"]');
await page.waitForTimeout(200);
await page.click('#refinedBlastValidate');
await page.waitForTimeout(1200);
await shot("08-validation-and-generation.png");

await page.click('[data-refined-back]');
await page.waitForSelector("#legacyWorkbenchRoot:not(.hidden)");
await normalizeBrand();
await page.click('[data-inspector-target="cityImpactSection"]');
await page.waitForTimeout(300);
await shot("09-intelligent-damage-assessment.png");

await browser.close();
