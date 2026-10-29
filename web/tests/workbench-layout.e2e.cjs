const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs/promises");
const { chromium } = require(process.env.PLAYWRIGHT_NODE_MODULES
  ? path.join(process.env.PLAYWRIGHT_NODE_MODULES, "playwright") : "playwright");

(async () => {
  const baseUrl = process.argv[2] || "http://127.0.0.1:8765";
  const output = path.resolve(process.argv[3] || path.join(__dirname, "../../var/tmp/frontend-simplification"));
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROME_EXECUTABLE ? { executablePath: process.env.CHROME_EXECUTABLE } : {}),
    args: ["--use-angle=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"],
  });
  const failures = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, locale: "zh-CN" });
    page.on("pageerror", error => failures.push(error.message));
    // Layout checks must never create projects, generate models or launch programs.
    await page.route("**/api/**", route => route.request().method() === "GET" ? route.continue() : route.abort());
    const noOverflow = async () => assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "page must fit viewport width");
    await page.goto(`${baseUrl}/refined-building-blast`);
    await page.locator("#refinedBlastAsset option").first().waitFor({ state: "attached" });
    const inspector = await page.locator("#refinedBlastInspector").boundingBox();
    const preview = await page.locator(".refined-blast-preview").boundingBox();
    const assetField = await page.locator("#refinedBlastAsset").boundingBox();
    assert(assetField.width > inspector.width * .8, "configuration fields must use the full panel width");
    assert(inspector.x < preview.x, "configuration must sit together on the left of the preview");
    assert(preview.width > 1440 * .60, "preview must retain most of the desktop workspace");
    assert.equal(await page.locator("[data-refined-onboarding]").evaluate(el => el.open), false, "guide should expand on request");
    for (const step of [2, 6, 7, 8, 1]) {
      await page.locator(`[data-refined-section="${step}"]`).click();
      assert.equal(await page.locator(`[data-refined-section="${step}"]`).getAttribute("aria-current"), "step");
    }
    await page.locator("[data-refined-inspector-toggle]").click();
    assert.equal(await page.locator("#refinedBlastInspector").isVisible(), false);
    await page.locator("[data-refined-inspector-toggle]").click();
    assert(await page.locator("#refinedBlastAsset").isVisible());
    await page.locator("[data-refined-onboarding] > summary").click();
    assert(await page.locator('[data-refined-workflow-step="save"]').isVisible());
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("[data-refined-onboarding]").evaluate(el => el.open), false);
    assert((await page.locator("[data-refined-schema-panel]").innerText()).includes("入口高度 (m)"));
    await page.locator("[data-refined-layer-toggle]").click();
    assert(await page.locator("#refinedBlastLayerPopover").isVisible());
    assert.equal(await page.locator("[data-refined-layer]").count(), 9);
    await page.locator("[data-refined-layer-close]").click();
    await page.locator(".refined-blast-external-menu > summary").click();
    await page.locator("[data-refined-assessment]").click();
    assert(await page.locator("#refinedDamagePanel").isVisible());
    await page.locator("[data-damage-close]").click();
    await page.keyboard.press("Escape");
    await noOverflow();
    await page.screenshot({ path: path.join(output, "after-refined-desktop.png") });

    await page.locator("[data-refined-back]").click();
    await page.locator("#modelMode").waitFor();
    assert.equal(await page.locator("#rightInspector").isVisible(), false, "solver settings should not compete with modeling by default");
    assert((await page.locator("#centerViewport").boundingBox()).width > 1440 * .65);
    await page.locator("#toggleTaskPanel").click();
    assert(await page.locator("#rightInspector").isVisible());
    await page.locator('[data-inspector-target="inspectorProjects"]').click();
    assert(await page.locator("#refresh").isVisible());
    await page.locator("#closeTaskPanel").click();
    assert.equal(await page.locator("#toggleTaskPanel").getAttribute("aria-expanded"), "false");
    await page.locator("#legacyDisplayMenu > summary").click();
    assert(await page.locator("#displayMode").isVisible());
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#legacyDisplayMenu").evaluate(el => el.open), false);
    await noOverflow();
    await page.screenshot({ path: path.join(output, "after-legacy-desktop.png") });

    for (const width of [1024, 390]) {
      await page.setViewportSize({ width, height: 844 });
      await noOverflow();
      await page.locator("#toggleTaskPanel").click();
      assert(await page.locator("#closeTaskPanel").isVisible());
      await page.locator("#closeTaskPanel").click();
      await page.screenshot({ path: path.join(output, `after-legacy-${width}.png`), fullPage: true });
      await page.locator("#openRefinedBlastWorkbench").click();
      await page.locator("#refinedBlastAsset").waitFor();
      await noOverflow();
      await page.locator('[data-refined-section="7"]').click();
      assert(await page.locator("#refinedBlastProvider").isVisible());
      await page.locator('[data-refined-section="1"]').click();
      await page.screenshot({ path: path.join(output, `after-refined-${width}.png`), fullPage: true });
      await page.locator("[data-refined-back]").click();
    }
    assert.deepEqual(failures, [], "browser must have no uncaught errors");
    console.log("PASS: both workbenches at 1440, 1024 and 390px; panels, navigation, keyboard dismissal; no API writes");
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
