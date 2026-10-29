import { mkdir } from "node:fs/promises";
import { dirname } from "node:path";
import { generatedPath } from "./work-paths.mjs";
import { chromium } from "file:///C:/Users/14989/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";

const baseUrl = process.argv[2] ?? "http://127.0.0.1:8767";
const screenshotPath = process.argv[3] ?? generatedPath("soft_copyright_work", "preview-debug.png");
await mkdir(dirname(screenshotPath), { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, locale: "zh-CN" });

const events = [];
page.on("console", (message) => events.push(`console:${message.type()}:${message.text()}`));
page.on("pageerror", (error) => events.push(`pageerror:${error.message}`));
page.on("requestfailed", (request) => events.push(`requestfailed:${request.method()}:${request.url()}:${request.failure()?.errorText}`));
page.on("response", (response) => {
  if (response.url().includes("refined-building-blast")) {
    events.push(`response:${response.status()}:${response.request().method()}:${response.url()}`);
  }
});

await page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 15000 });
await page.waitForTimeout(1000);
await page.click("#openRefinedBlastWorkbench");
await page.waitForSelector("#refinedBlastWorkbenchRoot:not(.hidden)");
await page.waitForFunction(() => {
  const value = document.querySelector("#refinedBlastPreviewStatus")?.textContent ?? "";
  return value !== "等待能力描述。";
}, { timeout: 20000 }).catch((error) => events.push(`capability-wait:${error.message}`));

const before = await page.evaluate(() => ({
  previewStatus: document.querySelector("#refinedBlastPreviewStatus")?.textContent,
  projectSummary: document.querySelector("[data-refined-project-summary]")?.textContent,
  saveSummary: document.querySelector("[data-refined-save-summary]")?.textContent,
  actionStatus: document.querySelector("[data-refined-action-status]")?.textContent,
  fieldCount: document.querySelectorAll("[data-refined-draft-path]").length,
  assetOptions: [...document.querySelectorAll('select[name="asset_id"] option')].map((option) => option.textContent),
  providerOptions: [...document.querySelectorAll('select[name="load_provider.provider_id"] option')].map((option) => option.textContent),
}));

if (process.argv.includes("--capabilities-only")) {
  await page.screenshot({ path: screenshotPath, fullPage: false, animations: "disabled" });
  console.log(JSON.stringify({ before, events }, null, 2));
  await browser.close();
  process.exit(0);
}

await page.click("#refinedBlastPreview");
await page.waitForFunction(() => {
  const text = document.querySelector("#refinedBlastPreviewStatus")?.textContent ?? "";
  return text.includes("revision") || text.includes("阻断") || text.includes("失败");
}, { timeout: 30000 }).catch((error) => events.push(`preview-wait:${error.message}`));
await page.waitForTimeout(1000);

const after = await page.evaluate(() => ({
  previewStatus: document.querySelector("#refinedBlastPreviewStatus")?.textContent,
  projectSummary: document.querySelector("[data-refined-project-summary]")?.textContent,
  saveSummary: document.querySelector("[data-refined-save-summary]")?.textContent,
  actionStatus: document.querySelector("[data-refined-action-status]")?.textContent,
  validationStatus: document.querySelector("[data-refined-validation-status]")?.textContent,
  conflict: document.querySelector("#refinedBlastConflict")?.textContent,
  previewChildren: document.querySelector("[data-refined-preview-canvas]")?.children.length,
  previewText: document.querySelector("[data-refined-preview-canvas]")?.textContent,
  canvasCount: document.querySelectorAll("[data-refined-preview-canvas] canvas").length,
  svgCount: document.querySelectorAll("[data-refined-preview-canvas] svg").length,
}));

await page.screenshot({ path: screenshotPath, fullPage: false, animations: "disabled" });
console.log(JSON.stringify({ before, after, events }, null, 2));
await browser.close();
