# WebGL Model Viewer Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the imported-project Canvas 2D viewer with an on-demand Three.js/WebGL viewer that keeps every mesh edge visible and renders the Phase17 V5 crater model smoothly on integrated graphics.

**Architecture:** Keep the existing preview-mesh JSON contract, add a bounded hash-keyed backend cache, and upload each part once as one indexed surface mesh plus one complete line-segment buffer built from `part.edges`. `app.js` remains the business-state owner and delegates rendering through a small viewer interface, while the old Canvas path remains an explicit fallback.

**Tech Stack:** Python 3 standard library, existing HTTP server, Three.js 0.180.0, OrbitControls, Node.js built-in assertions, Playwright 1.61.1, Python unittest.

## Global Constraints

- All preview edges remain visible during rotation, pan, and zoom.
- No geometry decimation, LOD edge removal, or interaction-time edge hiding.
- Do not modify model.k, model.json, checks.json, or solver outputs.
- Target 1920x1080 integrated graphics at 30 FPS or better for the V5 project.
- Preserve selection, visibility, isolation, risk colors, blast sources, view presets, fullscreen, and Canvas fallback.
- Cap renderer pixel ratio at 1.5 without changing geometry.

---

### Task 1: Lock the WebGL viewer contract with failing tests

**Files:**
- Create: `web/tests/model-viewer-webgl.e2e.cjs`
- Modify: `tests/test_web_static.py`
- Modify: `web/package.json`

**Interfaces:**
- Consumes: existing `/api/project/preview-mesh` response.
- Produces: browser test hook `window.__MODEL_VIEWER_METRICS__` and npm script `test:model-viewer`.

- [ ] **Step 1: Add a failing static contract test**

```python
def test_static_ui_loads_webgl_model_viewer_module(self) -> None:
    module = STATIC_DIR / "model_viewer_webgl.js"
    self.assertTrue(module.is_file())
    app = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    self.assertIn('import("/model_viewer_webgl.js")', app)
```

- [ ] **Step 2: Run the static test and verify RED**

Run: `python -m unittest tests.test_web_static.WebStaticTests.test_static_ui_loads_webgl_model_viewer_module`

Expected: FAIL because `model_viewer_webgl.js` does not exist and `app.js` has no dynamic import.

- [ ] **Step 3: Add the Playwright contract skeleton**

The test must load the page, select a supplied project, and assert that `window.__MODEL_VIEWER_METRICS__.backend === "webgl"`, `edgeCount > 0`, and `surfaceCount > 0`.

- [ ] **Step 4: Add the npm entry point**

```json
"test:model-viewer": "node tests/model-viewer-webgl.e2e.cjs"
```

### Task 2: Implement the standalone WebGL renderer

**Files:**
- Create: `lsprepost_mcp/web/static/model_viewer_webgl.js`
- Test: `tests/test_web_static.py`
- Test: `web/tests/model-viewer-webgl.e2e.cjs`

**Interfaces:**
- Consumes: `{canvas, onPartSelected}` and preview mesh v1/v2 payloads.
- Produces: `createModelViewer(options)` with the interface defined in the design spec.

- [ ] **Step 1: Implement geometry conversion**

Create indexed surface geometry from `part.faces` and indexed line geometry from every pair in `part.edges`. Throw a descriptive error for out-of-range indices rather than silently dropping geometry.

- [ ] **Step 2: Implement scene ownership**

Create one Group, one Mesh, and one LineSegments per part. Store records by string part ID. Add HemisphereLight and DirectionalLight once.

- [ ] **Step 3: Implement on-demand rendering**

```javascript
function invalidate() {
  if (framePending) return;
  framePending = true;
  requestAnimationFrame((time) => {
    framePending = false;
    render(time);
  });
}
```

- [ ] **Step 4: Implement selection and visibility**

Raycast only visible Mesh objects. Update surface and line material colors without rebuilding geometry. Keep all edge LineSegments visible in `solid_edges` and `wireframe` modes.

- [ ] **Step 5: Implement lifecycle and metrics**

Dispose all geometries and materials on reload/dispose. Publish backend, edge count, surface count, render calls, frame samples, geometry count, and material count through `getMetrics()` and the browser test hook.

- [ ] **Step 6: Run the static test and verify GREEN**

Run: `python -m unittest tests.test_web_static.WebStaticTests.test_static_ui_loads_webgl_model_viewer_module`

Expected: PASS after Task 3 connects the dynamic import; renderer-specific static assertions may pass in this task.

### Task 3: Route the main application through WebGL with Canvas fallback

**Files:**
- Modify: `lsprepost_mcp/web/static/app.js`
- Modify: `lsprepost_mcp/web/static/styles.css`
- Test: `tests/test_web_static.py`
- Test: `web/tests/frontend-patrol.e2e.cjs`

**Interfaces:**
- Consumes: `createModelViewer()` from Task 2.
- Produces: default WebGL main viewport and `?viewer=canvas` diagnostic fallback.

- [ ] **Step 1: Load the module once**

Use `import("/model_viewer_webgl.js")` and retain one promise. Initialize the renderer during boot when WebGL is supported and the query does not force Canvas.

- [ ] **Step 2: Delegate model operations**

Route `renderInteractiveMesh`, part visibility, isolation, selection, display mode, risk colors, blast source visibility, view fitting, fullscreen resize, and window resize to the WebGL adapter.

- [ ] **Step 3: Disable duplicate Canvas pointer work**

Do not attach or execute the old pointer handlers when WebGL is active. OrbitControls owns pointer input in the WebGL path.

- [ ] **Step 4: Preserve fallback behavior**

When WebGL creation fails or `viewer=canvas` is present, retain the current Canvas functions and input handlers unchanged.

- [ ] **Step 5: Run frontend patrol regression**

Run: `powershell -ExecutionPolicy Bypass -File scripts/test_web_frontend_patrol.ps1`

Expected: existing navigation, forms, project selection, and viewer controls remain functional.

### Task 4: Add hash-keyed preview caching and request cancellation

**Files:**
- Create: `lsprepost_mcp/web/preview_cache.py`
- Modify: `lsprepost_mcp/web/app.py`
- Modify: `lsprepost_mcp/web/static/app.js`
- Create: `tests/test_web_preview_cache.py`
- Modify: `tests/test_web_api.py`

**Interfaces:**
- Produces: `PreviewMeshCache(max_entries=4, max_serialized_bytes=16 * 1024 * 1024)` and `get_preview_mesh(project: Path) -> JSONDict`.

- [ ] **Step 1: Write failing cache tests**

Cover cache hit without rebuilding, model.k hash invalidation, model.json hash invalidation, least-recently-used eviction, and byte-budget eviction.

- [ ] **Step 2: Run cache tests and verify RED**

Run: `python -m unittest tests.test_web_preview_cache`

Expected: FAIL because the cache module does not exist.

- [ ] **Step 3: Implement the bounded cache**

Use `OrderedDict`, SHA256 file streaming, and compact JSON size accounting. Never cache exceptions or incomplete values.

- [ ] **Step 4: Connect the API route**

Replace direct `build_preview_mesh(project)` in `/api/project/preview-mesh` with the cache service. Preserve the response schema.

- [ ] **Step 5: Cancel stale browser requests**

Store one AbortController for preview loading. Abort it before starting a new project request and ignore AbortError without clearing the current model.

- [ ] **Step 6: Run cache and API tests**

Run: `python -m unittest tests.test_web_preview_cache tests.test_web_api`

Expected: PASS.

### Task 5: Handle WebGL recovery and prevent GPU leaks

**Files:**
- Modify: `lsprepost_mcp/web/static/model_viewer_webgl.js`
- Modify: `web/tests/model-viewer-webgl.e2e.cjs`

**Interfaces:**
- Consumes: current in-memory preview payload.
- Produces: context-loss recovery and stable renderer resource counts.

- [ ] **Step 1: Add failing browser assertions**

Assert that loading the same model repeatedly does not increase geometry/material counts, and that a synthetic `webglcontextlost` followed by `webglcontextrestored` rebuilds a nonblank frame.

- [ ] **Step 2: Implement context recovery**

Prevent default context loss, retain the current payload, dispose stale records, and rebuild the scene after restoration.

- [ ] **Step 3: Verify repeated-load cleanup**

Load/unload the fixture 10 times and assert stable metrics after garbage-collection-independent explicit disposal.

### Task 6: V5 functional and performance acceptance

**Files:**
- Modify: `web/tests/model-viewer-webgl.e2e.cjs`
- Modify: `scripts/test_phase17_web.ps1`
- Modify: `docs/ROADMAP.zh-CN.md`

**Interfaces:**
- Consumes: imported project `web_phase17_city_ground_crater_validation_v5_v2` when present.
- Produces: screenshots, canvas pixel checks, edge-integrity metrics, and performance report.

- [ ] **Step 1: Add exact edge-integrity checks**

Compare the preview payload edge count with the WebGL metrics before, during, and after rotation. All three values must match.

- [ ] **Step 2: Add desktop and mobile screenshots**

Capture 1920x1080 and 390x844. Assert nonblank canvas pixels, model framing, no toolbar overlap, and visible edge contrast.

- [ ] **Step 3: Measure interaction performance**

Drive OrbitControls for 5 seconds. Record frame samples and require average FPS >= 30 and p95 frame duration <= 50 ms on the designated integrated-GPU acceptance machine.

- [ ] **Step 4: Verify cold and warm API timing**

Require cold preview <= 2 seconds and cache hit <= 0.5 seconds for V5.

- [ ] **Step 5: Run the complete verification set**

Run:

```powershell
python -m unittest tests.test_web_preview_mesh tests.test_web_preview_cache tests.test_web_api tests.test_web_static
python -m compileall -q .\lsprepost_mcp
powershell -ExecutionPolicy Bypass -File scripts\test_web_frontend_patrol.ps1
powershell -ExecutionPolicy Bypass -File scripts\test_phase17_web.ps1
```

Expected: all Python tests pass, compileall exits 0, Playwright screenshots are nonblank, no overlap is detected, and V5 meets the defined performance gates.

### Task 7: Final regression and rollback documentation

**Files:**
- Modify: `docs/ROADMAP.zh-CN.md`
- Modify: `README.zh-CN.md`

**Interfaces:**
- Produces: documented WebGL default path, Canvas diagnostic fallback, performance scope, and known limits.

- [ ] **Step 1: Document the renderer contract**

State that WebGL is default, complete edges remain visible, `?viewer=canvas` is diagnostic only, and browser preview is not d3plot post-processing.

- [ ] **Step 2: Run scoped diff checks**

Run: `git diff --check -- lsprepost_mcp/web tests web scripts docs README.zh-CN.md`

Expected: exit 0 with no whitespace errors.

- [ ] **Step 3: Record final evidence**

Report exact test counts, V5 face/edge counts, cold/warm timings, measured FPS, screenshots, and any residual limitations without claiming production solver validation.
