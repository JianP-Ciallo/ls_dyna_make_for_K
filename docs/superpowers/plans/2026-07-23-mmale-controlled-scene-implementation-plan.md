# MM-ALE Controlled Scene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move only the MM-ALE blast entry under the controlled-scene selector while preserving its existing generator and API behavior.

**Architecture:** Keep MM-ALE as a specialized frontend workflow selected by `modelMode === "controlled"` and `scene.value === "ale_blast"`. Populate the special option in the browser without adding it to the generic backend scene catalog, because generic scenes require prompt fields and material fields that do not apply to MM-ALE.

**Tech Stack:** Static HTML, browser JavaScript, Python `unittest`.

## Global Constraints

- Do not change MM-ALE keyword generation, solver execution, or API payloads.
- Do not move parameterized tunnel blast or Phase 15 K&C blast.
- Preserve `/api/ale-blast/validate` and `/api/ale-blast/generate`.
- Use test-first development.

---

### Task 1: Lock the navigation and safety-copy contract

**Files:**
- Modify: `tests/test_web_static.py`
- Modify: `lsprepost_mcp/web/static/index.html`
- Modify: `lsprepost_mcp/web/static/app.js`

**Interfaces:**
- Consumes: Existing `#modelMode`, `#scene`, `#controlledScenePanel`, `#aleBlastPanel`, `isAleBlastMode()`, and MM-ALE API actions.
- Produces: A controlled-scene option with value `ale_blast` and a mode predicate requiring both controlled mode and that scene value.

- [x] **Step 1: Write the failing static contract test**

Replace the existing Phase 14 UI assertion with checks that:

```python
model_mode_markup = html.split('<select id="modelMode">', 1)[1].split("</select>", 1)[0]
self.assertNotIn('value="ale_blast"', model_mode_markup)
self.assertIn('const aleBlastSceneId = "ale_blast";', js)
self.assertIn('option.value = aleBlastSceneId;', js)
self.assertIn(
    'return byId("modelMode").value === "controlled" && byId("scene").value === aleBlastSceneId;',
    js,
)
self.assertIn('id="controlledSceneFields"', html)
self.assertIn("受控仅表示输入与生成路径受控", html)
self.assertIn("网格收敛性尚未证明", html)
self.assertIn("钢板周边完全固定", html)
```

- [x] **Step 2: Run the targeted test and verify RED**

Run:

```powershell
python -m unittest tests.test_web_static.WebStaticFallbackTests.test_static_ui_nests_phase14_ale_under_controlled_scenes
```

Expected: failure because MM-ALE is still a top-level option and the new controlled-scene contract is absent.

- [x] **Step 3: Implement the minimum HTML and JavaScript changes**

In `index.html`:

- Remove the top-level `<option value="ale_blast">`.
- Wrap the generic controlled-scene summary, prompt and fields in `#controlledSceneFields`.
- Keep `#scene` outside that wrapper so users can switch away from MM-ALE.
- Add the approved risk statement to `#aleBlastPanel`.

In `app.js`:

```javascript
const aleBlastSceneId = "ale_blast";

function isAleBlastMode() {
  return byId("modelMode").value === "controlled" && byId("scene").value === aleBlastSceneId;
}
```

Append the MM-ALE option in `loadScenes()`, hide only `#controlledSceneFields` for MM-ALE, and invoke `setModelMode()` after a scene change. Keep the existing MM-ALE validate and generate branches unchanged.

- [x] **Step 4: Run the targeted test and verify GREEN**

Run:

```powershell
python -m unittest tests.test_web_static.WebStaticFallbackTests.test_static_ui_nests_phase14_ale_under_controlled_scenes
```

Expected: `OK`.

- [x] **Step 5: Run frontend and backend regression tests**

Run:

```powershell
python -m unittest tests.test_web_static tests.test_web_api tests.test_phase14_complete
```

Expected: all tests pass, with only the repository's documented integration skips if applicable.

- [x] **Step 6: Run full verification**

Run:

```powershell
python -m unittest discover -s tests
python -m compileall -q .\lsprepost_mcp
```

Expected: both commands exit with status `0`.
