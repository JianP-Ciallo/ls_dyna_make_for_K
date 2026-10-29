const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require(path.join(process.argv[2], 'playwright'));

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1600, height: 1050 } });
    const errors = [], writes = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { if (!['GET', 'HEAD'].includes(request.method())) writes.push(request.url()); });
    await page.goto(process.argv[3] + '/refined-building-blast', { waitUntil: 'networkidle' });
    const original = await page.evaluate(() => ({ local: JSON.stringify(localStorage), session: JSON.stringify(sessionStorage), url: location.href }));
    const entry = page.locator('[data-refined-assessment]');
    if (!(await entry.isVisible())) await entry.locator('xpath=ancestor::details[1]/summary').click();
    await entry.click();
    await page.locator('[data-damage-demo]').click();
    const demo = page.frameLocator('[data-damage-demo-frame]');
    await demo.locator('[data-demo-state="ready"]').waitFor({ timeout: 10000 });
    const demoFrame = page.frames().find(f => f.url().includes('/damage_assessment_demo.html'));
    await demoFrame.evaluate(async () => {
      const THREE = await import('three');
      const original = THREE.Mesh.prototype.onBeforeRender;
      THREE.Mesh.prototype.onBeforeRender = function (...args) {
        original?.apply(this, args);
        if (!this.userData.partId) return;
        const colors = this.geometry.getAttribute('color');
        const array = colors ? Array.from(colors.array) : [];
        const unique = new Set();
        for (let i = 0; i < array.length; i += 3) unique.add(array.slice(i, i + 3).map(v => v.toFixed(4)).join(','));
        (window.__demoDraws ??= {})[this.userData.partId] = {
          colored: this.material.vertexColors, unique: unique.size, tint: this.material.color.toArray(),
          hex: this.material.color.getHexString(),
        };
      };
    });
    // Tiny real-renderer probe: optional color arrays must not change legacy/invalid parts.
    await demoFrame.evaluate(async () => {
      const { createModelViewer } = await import('/model_viewer_webgl.js');
      const canvas = document.createElement('canvas');
      canvas.style.cssText = 'position:fixed;left:0;top:0;width:80px;height:80px';
      document.body.append(canvas);
      const viewer = createModelViewer({ canvas });
      const nodes = [[-1, -1, 0], [1, -1, 0], [0, 1, 0]];
      window.__probe = { canvas, viewer };
      viewer.sync({ mesh: { parts: [{ part_id: 'legacy-probe', nodes, faces: [[0, 1, 2]], color: '#123456',
        vertex_colors: [[1, 0, 0]] }], bounds: { min: [-1, -1, -1], max: [1, 1, 1] } } });
    });
    await demoFrame.waitForFunction(() => window.__demoDraws?.['legacy-probe']);
    const legacy = await demoFrame.evaluate(() => {
      window.__probe.viewer.destroy(); window.__probe.canvas.remove(); delete window.__probe;
      return window.__demoDraws['legacy-probe'];
    });
    assert.equal(legacy.colored, false);
    assert.equal(legacy.hex, '123456');
    assert.equal(await demo.locator('[data-demo-evaluate]').count(), 1, 'Replacement must allow a new evaluation');
    assert.match(await demo.locator('[data-demo-building]').innerText(), /未评估/);
    assert.equal(await demo.locator('[data-demo-report]').getAttribute('href'), null);
    const run = async () => {
      const response = page.waitForResponse(r => r.url().endsWith('/api/damage-assessment/demo/evaluate') && r.request().method() === 'POST');
      await demo.locator('[data-demo-evaluate]').click();
      const result = await (await response).json();
      await demo.locator('[data-demo-state="evaluated"]').waitFor();
      assert.equal(result.result.synthetic_demo, true);
      return result.result;
    };
    const first = await run();
    assert.match(await demo.locator('[data-demo-field-legend]').innerText(), /演示影响分布/);
    await demoFrame.waitForFunction(() => window.__demoDraws?.['1001']?.unique > 20);
    const drawing = await demoFrame.evaluate(() => window.__demoDraws['1001']);
    assert.equal(drawing.colored, true, 'GPU material must enable per-vertex colors');
    assert.deepEqual(drawing.tint, [1, 1, 1], 'Whole-part grade must not tint or replace the local field');
    assert.match(await demo.locator('[data-demo-building]').innerText(), new RegExp('等级 ' + first.snapshot.building.severity));
    const graded = demo.locator('[data-component-id][data-grade]:not([data-grade="missing"])');
    assert(await graded.count() > 0);
    const selected = graded.first();
    await selected.click();
    assert.match(await demo.locator('[data-demo-detail]').innerText(), /相对变形/);
    assert.match(await demo.locator('[data-demo-detail]').innerText(), /判定依据/);
    const canvas = await demo.locator('canvas').boundingBox();
    await page.mouse.click(canvas.x + canvas.width * .5, canvas.y + canvas.height * .5);
    assert.equal(await demo.locator('[data-component-id][aria-pressed="true"]').count(), 1, 'Canvas picking must select a real component');
    await demo.locator('[data-demo-hide-walls]').check();
    await demo.locator('[data-demo-fit]').click();
    await page.screenshot({ path: path.join(process.argv[4], 'damage-demo-desktop.png') });
    await page.mouse.move(canvas.x + canvas.width * .5, canvas.y + canvas.height * .5);
    await page.mouse.wheel(0, -500);
    await page.waitForTimeout(250);
    await demo.locator('canvas').screenshot({ path: path.join(process.argv[4], 'damage-demo-gradient-detail.png') });
    await demo.locator('[data-demo-fit]').click();
    const reportText = await demo.locator('[data-demo-report]').evaluate(async a => (await fetch(a.href)).text());
    assert.match(reportText, /合成数据演示/);
    assert.match(reportText, new RegExp(first.snapshot.assessment_id));
    const evidence = await demo.locator('[data-demo-evidence]').evaluate(async a => (await (await fetch(a.href)).json()));
    assert.equal(Object.keys(evidence.artifacts).length, 8);
    assert.equal(evidence.synthetic_demo, true);
    assert.equal(evidence.display_field.assessment_id, first.snapshot.assessment_id);
    assert.equal(evidence.display_field.quantity, 'dimensionless_display_influence');
    assert(new Set(evidence.display_field.parts[0].values).size > 20);
    for (const selector of ['[data-demo-building-csv]', '[data-demo-ground-csv]']) {
      assert.match(await demo.locator(selector).evaluate(async a => (await fetch(a.href)).text()), /合成数据演示/);
    }
    await demo.locator('[data-source-x]').first().fill('5');
    assert.equal(await demo.locator('[data-demo-report]').getAttribute('href'), null);
    assert.equal(await demo.locator('[data-component-id]:not([data-grade="missing"])').count(), 0);
    await demoFrame.waitForFunction(() => window.__demoDraws?.['1001']?.colored === false);
    const moved = await run();
    assert.notEqual(moved.snapshot.assessment_fingerprint, first.snapshot.assessment_fingerprint);
    await demo.locator('[data-demo-add-source]').click();
    assert.equal(await demo.locator('[data-source-row]').count(), 2);
    await demo.locator('[data-source-z]').last().fill('8');
    await demo.locator('[data-source-quantity]').last().fill('600');
    const multiple = await run();
    assert.equal(multiple.input.sources.length, 2);
    assert.equal(multiple.input.sources[1].position_m[2], 8);
    assert.equal(multiple.input.sources[1].equivalent_kg, 600);
    await demo.locator('[data-source-remove]').last().click();
    assert.equal(await demo.locator('[data-source-row]').count(), 1);
    await demo.locator('[data-demo-mode]').selectOption('partial');
    const partial = await run();
    assert.equal(partial.snapshot.ground.severity, null);
    assert.match(await demo.locator('[data-demo-ground]').innerText(), /不可评估/);
    assert(await demo.locator('[data-component-role="ground"][data-grade="missing"]').count() > 0);
    await demo.locator('[data-demo-mode]').selectOption('blocked');
    await run();
    assert.match(await demo.locator('[data-demo-building]').innerText(), /不可评估/);
    assert.equal(await demo.locator('[data-component-id]:not([data-grade="missing"])').count(), 0);
    await demo.locator('[data-demo-mode]').selectOption('complete');
    await page.route('**/api/damage-assessment/demo/evaluate', route => route.fulfill({
      status: 503, contentType: 'application/json', body: JSON.stringify({ ok: false, error: { message: '演示依赖不可用' } }) }));
    await demo.locator('[data-demo-evaluate]').click();
    await demo.locator('[data-demo-state="error"]').waitFor();
    assert.equal(await demo.locator('[data-demo-report]').getAttribute('href'), null);
    await page.unroute('**/api/damage-assessment/demo/evaluate');
    await run();
    await demo.locator('[data-source-quantity]').first().fill('300');
    await page.route('**/api/damage-assessment/demo/evaluate', async route => {
      const response = await route.fetch();
      const body = await response.json();
      body.result.artifacts['damage_report.html'].text += 'tampered';
      await route.fulfill({ response, json: body });
    });
    await demo.locator('[data-demo-evaluate]').click();
    await demo.locator('[data-demo-state="error"]').waitFor();
    assert.match(await demo.locator('[data-demo-status]').innerText(), /校验失败/);
    assert.equal(await demo.locator('[data-demo-report]').getAttribute('href'), null);
    assert.equal(await demo.locator('[data-component-id]:not([data-grade="missing"])').count(), 0);
    await page.unroute('**/api/damage-assessment/demo/evaluate');
    await demo.locator('[data-demo-reset]').click();
    assert.equal(await demo.locator('[data-source-x]').first().inputValue(), '-6');
    assert.equal(await demo.locator('[data-demo-mode]').inputValue(), 'complete');
    await page.locator('[data-damage-demo-exit]').click();
    assert.equal(await page.locator('[data-damage-demo-frame]').count(), 0);
    assert.deepEqual(await page.evaluate(() => ({ local: JSON.stringify(localStorage), session: JSON.stringify(sessionStorage), url: location.href })), original);
    await page.locator('[data-damage-demo]').click();
    await demo.locator('[data-demo-state="ready"]').waitFor();
    assert.match(await demo.locator('[data-demo-building]').innerText(), /未评估/);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(process.argv[4], 'damage-demo-mobile.png') });
    assert(await demo.locator('body').evaluate(el => el.scrollWidth <= window.innerWidth + 1));
    await page.locator('[data-damage-demo-exit]').focus();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('[data-damage-demo-frame]').count(), 0);
    assert(writes.length > 0);
    assert(writes.every(url => url.endsWith('/api/damage-assessment/demo/evaluate')), 'No real project writes');
    assert.deepEqual(errors, []);
    console.log('Interactive synthetic assessment, picking, stale clearing, sources, gates, sealed exports, tamper rejection, reset, desktop/mobile and project isolation passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
