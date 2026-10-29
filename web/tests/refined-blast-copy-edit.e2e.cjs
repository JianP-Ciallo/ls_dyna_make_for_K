const fs = require("fs");
const path = require("path");

const playwrightRoot = process.argv[2];
const baseUrl = process.argv[3];
const outputDir = process.argv[4];
if (!playwrightRoot || !baseUrl || !outputDir) {
  throw new Error("usage: node refined-blast-copy-edit.e2e.cjs <node_modules> <base-url> <output-dir>");
}
const { chromium } = require(path.join(playwrightRoot, "playwright"));

(async () => {
  fs.mkdirSync(outputDir, { recursive: true });
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const context = await browser.newContext({ viewport: { width: 1920, height: 1200 } });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.goto(`${baseUrl}/refined-building-blast`, { waitUntil: "networkidle" });
  await page.locator("#refinedBlastAsset").waitFor({ timeout: 15000 });
  await page.locator("#refinedBlastAsset").selectOption("commercial_supermarket_detailed_building");
  await page.locator("[data-refined-save]").click();
  await page.waitForURL(/project_id=/, { timeout: 15000 });
  await page.getByText("已保存到独立项目", { exact: true }).first().waitFor({ timeout: 15000 });

  const sourceUrl = page.url();
  const sourceProjectId = new URL(sourceUrl).searchParams.get("project_id");
  const steps = {};
  for (let step = 1; step <= 6; step += 1) {
    await page.locator(`[data-refined-section="${step}"]`).click();
    const controls = page.locator('[data-refined-schema-panel] [data-refined-draft-path^="building."]');
    const disabled = await controls.evaluateAll((rows) => rows.filter((row) => row.disabled).map((row) => row.name));
    steps[String(step)] = { controls: await controls.count(), disabled };
  }
  await page.locator('[data-refined-section="1"]').click();
  const assetDisabled = await page.locator("#refinedBlastAsset").isDisabled();
  await page.locator('[data-refined-section="2"]').click();
  const structuralDisabled = await page.locator("#refinedBlastStructuralSystem").isDisabled();
  await page.locator('[data-refined-section="1"]').click();
  await page.screenshot({ path: path.join(outputDir, "01-saved-pending-editable.png"), fullPage: true });

  page.once("dialog", (dialog) => dialog.dismiss());
  await page.locator("#refinedBlastAsset").selectOption("residential_community_detailed_building");
  await page.waitForTimeout(150);
  const cancelledAsset = await page.locator("#refinedBlastAsset").inputValue();
  const cancelledUrl = page.url();

  const length = page.locator('[data-refined-draft-path="building.legacy_geometry.length_m"]').first();
  const priorLength = await length.inputValue();
  const nextLength = String(Number(priorLength) + 1);
  page.once("dialog", (dialog) => dialog.accept());
  await length.fill(nextLength);
  await length.dispatchEvent("change");
  await page.waitForURL((url) => !url.searchParams.has("project_id"), { timeout: 10000 });
  await page.locator('[data-refined-building-edit-notice][data-state="copy"]').waitFor({ timeout: 10000 });
  const copiedLength = await page.locator('[data-refined-draft-path="building.legacy_geometry.length_m"]').first().inputValue();
  const saveLabel = await page.locator("[data-refined-save]").textContent();
  await page.screenshot({ path: path.join(outputDir, "02-editable-copy.png"), fullPage: true });

  const sourceResponse = await page.request.get(`${baseUrl}/api/refined-building-blast/projects/${encodeURIComponent(sourceProjectId)}`);
  const sourcePayload = await sourceResponse.json();
  const sourceLength = sourcePayload.result.project.building.legacy_geometry.length_m;

  await page.locator("[data-refined-save]").click();
  await page.waitForURL(/project_id=/, { timeout: 15000 });
  const copyProjectId = new URL(page.url()).searchParams.get("project_id");
  const copyResponse = await page.request.get(`${baseUrl}/api/refined-building-blast/projects/${encodeURIComponent(copyProjectId)}`);
  const copyPayload = await copyResponse.json();
  const savedCopyLength = copyPayload.result.project.building.legacy_geometry.length_m;
  await page.screenshot({ path: path.join(outputDir, "03-copy-saved-as-new-project.png"), fullPage: true });

  await browser.close();
  const evidence = {
    sourceProjectId,
    copyProjectId,
    distinctProjectIds: sourceProjectId !== copyProjectId,
    savedPendingControls: { assetDisabled, structuralDisabled, steps },
    cancelledMutation: {
      asset: cancelledAsset,
      remainedOnSource: cancelledUrl === sourceUrl,
    },
    copiedMutation: {
      priorLength: Number(priorLength),
      copiedLength: Number(copiedLength),
      sourceLength,
      savedCopyLength,
      saveLabel,
    },
    consoleErrors,
  };
  const disabledBuildingControls = Object.values(steps).flatMap((row) => row.disabled);
  if (assetDisabled || structuralDisabled || disabledBuildingControls.length) {
    throw new Error(`saved pending project disabled building controls: ${JSON.stringify(evidence.savedPendingControls)}`);
  }
  if (cancelledAsset !== "commercial_supermarket_detailed_building" || cancelledUrl !== sourceUrl) {
    throw new Error(`cancelled copy-on-edit changed the source session: ${JSON.stringify(evidence.cancelledMutation)}`);
  }
  if (sourceProjectId === copyProjectId || Number(sourceLength) !== Number(priorLength)
      || Number(copiedLength) !== Number(nextLength) || Number(savedCopyLength) !== Number(nextLength)
      || saveLabel.trim() !== "创建项目并保存草稿") {
    throw new Error(`copy-on-edit did not preserve source and save a new project: ${JSON.stringify(evidence.copiedMutation)}`);
  }
  if (consoleErrors.length) throw new Error(`browser console errors: ${JSON.stringify(consoleErrors)}`);
  process.stdout.write(`${JSON.stringify(evidence)}\n`);
})().catch((error) => {
  console.error(error?.stack ?? error);
  process.exitCode = 1;
});
