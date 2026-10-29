# Phase 17 City Scene Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally packaged Three.js city-scene editor that moves the real ALE TNT source and authorized grounded buildings, regenerates all dependent physics, and creates a new immutable LS-DYNA project.

**Architecture:** Add a source-aware in-memory editor preview service and PreviewMesh v2 contract, then render that contract in a dedicated Three.js model canvas while preserving the existing result canvas as read-only. Mobility profiles restrict each semantic object to valid degrees of freedom: city buildings use grounded X/Y/yaw motion, the real ALE explosive uses X/Y/Z translation, ordinary assembly components retain full translation/rotation, and future airborne objects use a separately gated profile. The Python backend remains authoritative for ALE initialization, geometry, support, FSI, probes, semantic mapping, K-file generation, and project immutability.

Phase 17 consumes the existing Phase 16A semantic/result contract and Phase 16B study pipeline. A canonical `phase17.city_layout.v1` fingerprint isolates edited layouts from prior metrics, matrices, authorizations, refinement plans, surrogate models, and protection rankings without breaking historical project reads.

**Tech Stack:** Python 3.10+ standard library, `unittest`, vanilla HTML/CSS/JavaScript, `three@0.180.0`, Playwright, existing LS-DYNA component/keyword builders.

## Global Constraints

- Do not modify any existing project directory, K file, solver run, or result artifact.
- Phase 17 edits only complete semantic objects and the real ALE explosive source.
- City buildings use `grounded`: X/Y translation and Z-axis rotation only.
- The city TNT source uses `blast_source`: X/Y/Z translation only.
- Freeze but do not expose `airborne`: X/Y/Z translation and X/Y/Z rotation.
- Ordinary assembly components use `free_component`: X/Y/Z translation and X/Y/Z rotation.
- Do not add scaling or node/element editing.
- Use world coordinates, metres, degrees, and X-then-Y-then-Z Euler rotation.
- Keep model preview editable and solver-result views read-only.
- Build draft previews in memory; do not create temporary project directories.
- Generate with a new project name and `if_exists="error"`.
- Bundle Three.js and controls locally; browser runtime must not access a CDN.
- Keep current PreviewMesh v1 project reads compatible.
- Reject NaN, Infinity, malformed vectors, invalid contact references, invalid fixed regions, and blocking geometry/impact errors.
- Reject blast-source boundary violations, TNT/structure overlap, marker-only moves, unsupported building DOFs, missing ground support, stale FSI sets, and stale city-result mappings.
- Preserve Phase 16A stable `object_id`, metric names, units, threshold provenance, and `phase16a.city_impact.v1` reads.
- Map the real source position to existing Phase 16B `blast_center_x_m`, `blast_center_y_m`, and `blast_center_z_m`.
- Bind every Phase 17 city project, Phase 16B matrix, registered result, refinement plan, and surrogate model to `layout_fingerprint`.
- Bind each exact source position and layout combination to `editor_state_fingerprint` and the existing Phase 16B case parameters.
- Never register an edited building layout into an older Phase 16B matrix or reuse its solver authorization.
- Never reuse one Phase 16B case authorization after moving the blast source.
- Reject surrogate prediction with `layout_out_of_surrogate_domain` before nearest-neighbor evaluation.
- Do not start LS-PrePost, LS-Run, or LS-DYNA during default Phase 17 tests.
- Do not mark Phase 17 complete without Playwright screenshots and nonblank canvas pixel checks.

---

### Task 1: Freeze PreviewMesh v2, Editor Draft, and Mobility Contracts

**Files:**
- Create: `lsprepost_mcp/web/draft_preview.py`
- Modify: `lsprepost_mcp/web/preview_mesh.py`
- Create: `tests/test_phase17_draft_preview.py`
- Modify: `tests/test_web_preview_mesh.py`

**Interfaces:**
- Produces: `build_preview_mesh_from_keyword(keyword: str, metadata: JSONDict, *, project_name: str, revision: int | None = None) -> JSONDict`
- Produces: `build_editor_draft_preview(payload: JSONDict) -> JSONDict`
- Produces: mobility profiles `fixed`, `grounded`, `blast_source`, `free_component`, and protocol-only `airborne`
- Produces: response format `lsprepost_mcp_preview_mesh_v2`
- Preserves: `build_preview_mesh(project_path: Path) -> JSONDict`

- [ ] **Step 1: Write failing compatibility and v2 mapping tests**

Add tests equivalent to:

```python
def test_v1_project_preview_remains_compatible(self):
    preview = build_preview_mesh(self.project)
    self.assertEqual(preview["format"], "lsprepost_mcp_preview_mesh_v1")

def test_draft_preview_maps_every_part_to_component(self):
    preview = build_editor_draft_preview({
        "source_kind": "assembly",
        "revision": 7,
        "project_name": "phase17_draft",
        "components": valid_rebar_helmet_components(),
        "actions": valid_rebar_helmet_actions(),
    })
    self.assertEqual(preview["format"], "lsprepost_mcp_preview_mesh_v2")
    self.assertEqual(preview["revision"], 7)
    mapped = {
        part_id
        for component in preview["components"]
        for part_id in component["part_ids"]
    }
    self.assertEqual(mapped, {part["part_id"] for part in preview["parts"]})

def test_city_preview_exposes_real_blast_source_and_grounded_building(self):
    preview = build_editor_draft_preview(valid_city_editor_payload(revision=8))
    source = next(item for item in preview["editable_sources"] if item["source_id"] == "city_tnt")
    building = next(item for item in preview["components"] if item["component_id"] == "commercial_supermarket")
    self.assertEqual(source["mobility_profile"], "blast_source")
    self.assertEqual(source["allowed_dofs"], ["tx", "ty", "tz"])
    self.assertEqual(building["mobility_profile"], "grounded")
    self.assertEqual(building["allowed_dofs"], ["tx", "ty", "rz"])
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_phase17_draft_preview tests.test_web_preview_mesh
```

Expected: import failure for `lsprepost_mcp.web.draft_preview`.

- [ ] **Step 3: Refactor keyword mesh parsing without changing v1 output**

Move the keyword-to-parts portion of `build_preview_mesh()` behind:

```python
def build_preview_mesh_from_keyword(
    keyword: str,
    metadata: JSONDict,
    *,
    project_name: str,
    revision: int | None = None,
) -> JSONDict:
    nodes, shell_elements, solid_elements = parse_keyword_mesh(keyword)
    components = component_preview_records(metadata)
    return {
        "format": "lsprepost_mcp_preview_mesh_v2" if revision is not None else "lsprepost_mcp_preview_mesh_v1",
        "project_name": project_name,
        **({"revision": revision} if revision is not None else {}),
        "parts": build_part_meshes(nodes, shell_elements, solid_elements, metadata),
        "components": components,
        "bounds": mesh_bounds(nodes),
        "node_count": len(nodes),
    }
```

`build_preview_mesh()` must continue loading `model.k` and `model.json`, then remove v2-only fields if necessary to retain its existing snapshots.

- [ ] **Step 4: Implement in-memory draft compilation**

Implement:

```python
def build_editor_draft_preview(payload: JSONDict) -> JSONDict:
    revision = strict_nonnegative_int(payload.get("revision"), "revision")
    source_kind = strict_choice(payload.get("source_kind"), {"assembly", "controlled_scene", "city_street_blast"})
    compiled = compile_editor_source(source_kind, payload)
    keyword, metadata = compiled.keyword, compiled.metadata
    preview = build_preview_mesh_from_keyword(
        keyword,
        metadata,
        project_name=compiled.project_name,
        revision=revision,
    )
    preview["validation"] = {
        "ok": True,
        "status": compiled.status,
        "issues": compiled.issues,
    }
    return preview
```

Do not call `write_model_project()` and do not use a filesystem temporary directory.

- [ ] **Step 5: Run tests and confirm GREEN**

Run:

```powershell
python -m unittest tests.test_phase17_draft_preview tests.test_web_preview_mesh
```

Expected: all tests pass and no `workspace/projects/phase17_draft` directory exists.

- [ ] **Step 6: Commit**

```powershell
git add lsprepost_mcp/web/draft_preview.py lsprepost_mcp/web/preview_mesh.py tests/test_phase17_draft_preview.py tests/test_web_preview_mesh.py
git commit -m "feat: add phase17 in-memory preview contract"
```

---

### Task 2: Add the Source-Aware Editor Preview API

**Files:**
- Modify: `lsprepost_mcp/web/app.py`
- Modify: `tests/test_web_app.py`
- Modify: `tests/test_phase17_draft_preview.py`

**Interfaces:**
- Consumes: `build_editor_draft_preview(payload)`
- Produces: `POST /api/editor/preview`
- Preserves: existing assembly, controlled-scene, and city generation routes
- Returns: PreviewMesh v2 or the existing structured API error format

- [ ] **Step 1: Write failing route and no-write tests**

```python
def test_assembly_preview_route_returns_revision(self):
    response = self.post_json("/api/editor/preview", valid_draft_payload(revision=9))
    self.assertEqual(response.status, 200)
    self.assertEqual(response.json()["result"]["revision"], 9)

def test_assembly_preview_route_never_creates_project(self):
    name = "phase17_route_no_write"
    self.post_json("/api/editor/preview", valid_draft_payload(project_name=name, revision=1))
    self.assertFalse(project_dir(name).exists())
```

Add invalid tests for:

- missing `revision`;
- boolean revision;
- negative revision;
- non-object body;
- more than 32 components;
- unknown component fields.
- unknown `source_kind`;
- city building Z/pitch/roll edits;
- blast-source rotations;
- `airborne` profile submitted by the browser.

- [ ] **Step 2: Run route tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_web_app tests.test_phase17_draft_preview
```

Expected: `/api/editor/preview` returns 404.

- [ ] **Step 3: Add the API route**

Add the import and route:

```python
from .draft_preview import build_editor_draft_preview

if path == "/api/editor/preview":
    return json_ok(build_editor_draft_preview(payload))
```

Keep the route behind existing JSON content-type, local-origin, body-size, and object-body checks.

- [ ] **Step 4: Run route tests and full Web tests**

Run:

```powershell
python -m unittest tests.test_web_app tests.test_phase17_draft_preview tests.test_web_preview_mesh
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/web/app.py tests/test_web_app.py tests/test_phase17_draft_preview.py
git commit -m "feat: expose phase17 draft preview api"
```

---

### Task 3: Vendor Three.js and Establish a Separate Model Canvas

**Files:**
- Create: `package.json`
- Create: `package-lock.json`
- Create: `scripts/vendor_three.mjs`
- Create: `lsprepost_mcp/web/static/vendor/three.module.js`
- Create: `lsprepost_mcp/web/static/vendor/addons/controls/OrbitControls.js`
- Create: `lsprepost_mcp/web/static/vendor/addons/controls/TransformControls.js`
- Create: `lsprepost_mcp/web/static/vendor/THIRD_PARTY_NOTICES.txt`
- Modify: `lsprepost_mcp/web/static/index.html`
- Modify: `lsprepost_mcp/web/static/style.css`
- Modify: `scripts/pack.ps1`
- Create: `tests/test_phase17_static_assets.py`

**Interfaces:**
- Produces: browser import specifiers `three` and `three/addons/`
- Produces: `#modelViewerCanvas` for WebGL model editing
- Preserves: existing result canvas as `#resultViewerCanvas`

- [ ] **Step 1: Write failing local-asset and dual-canvas tests**

```python
def test_three_assets_are_local_and_pinned(self):
    package = json.loads(Path("package.json").read_text(encoding="utf-8"))
    self.assertEqual(package["dependencies"]["three"], "0.180.0")
    html = static_text("index.html")
    self.assertIn('"/vendor/three.module.js"', html)
    self.assertNotIn("cdn.", html.lower())

def test_model_and_result_canvases_are_separate(self):
    html = static_text("index.html")
    self.assertIn('id="modelViewerCanvas"', html)
    self.assertIn('id="resultViewerCanvas"', html)
```

- [ ] **Step 2: Run the asset tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_phase17_static_assets
```

Expected: missing `package.json` and local Three.js files.

- [ ] **Step 3: Add deterministic dependency copying**

Use:

```json
{
  "private": true,
  "dependencies": {
    "three": "0.180.0"
  },
  "devDependencies": {
    "@playwright/test": "1.55.0"
  },
  "scripts": {
    "vendor:three": "node scripts/vendor_three.mjs",
    "test:e2e": "playwright test"
  }
}
```

`vendor_three.mjs` must copy the exact three files from `node_modules/three`, calculate SHA-256 hashes, and regenerate `THIRD_PARTY_NOTICES.txt`. It must fail if the installed version is not exactly `0.180.0`.

- [ ] **Step 4: Add import map and dual canvases**

Add:

```html
<script type="importmap">
{
  "imports": {
    "three": "/vendor/three.module.js",
    "three/addons/": "/vendor/addons/"
  }
}
</script>
<canvas id="modelViewerCanvas" aria-label="三维建模预览"></canvas>
<canvas id="resultViewerCanvas" aria-label="只读求解结果"></canvas>
<script type="module" src="/phase17_viewer.js"></script>
<script src="/app.js"></script>
```

Only one canvas may be visible for the active tab.

- [ ] **Step 5: Include vendor assets in packaging**

Extend `scripts/pack.ps1` checks so the package fails when:

- any required Three.js asset is missing;
- a runtime HTML/JS file contains `http://`, `https://`, or `//cdn`;
- `THIRD_PARTY_NOTICES.txt` is missing.

- [ ] **Step 6: Run asset and packaging tests**

Run:

```powershell
python -m unittest tests.test_phase17_static_assets
powershell -ExecutionPolicy Bypass -File .\scripts\pack.ps1
```

Expected: both pass; generated zip contains the three local modules and notice.

- [ ] **Step 7: Commit**

```powershell
git add package.json package-lock.json scripts/vendor_three.mjs lsprepost_mcp/web/static/vendor lsprepost_mcp/web/static/index.html lsprepost_mcp/web/static/style.css scripts/pack.ps1 tests/test_phase17_static_assets.py
git commit -m "build: vendor phase17 threejs runtime"
```

---

### Task 4: Implement the Three.js Read-Only Model Renderer

**Files:**
- Create: `lsprepost_mcp/web/static/phase17_viewer.js`
- Modify: `lsprepost_mcp/web/static/app.js`
- Modify: `lsprepost_mcp/web/static/style.css`
- Create: `tests/web/phase17_viewer.test.mjs`

**Interfaces:**
- Produces: `window.phase17Viewer`
- Produces: `loadPreview(preview: PreviewMeshV2): void`
- Produces: `setView(name: "fit" | "iso" | "top" | "front"): void`
- Produces: `setDisplayMode(mode: string): void`
- Emits: `phase17-viewer-ready`

- [ ] **Step 1: Write failing JavaScript geometry tests**

Test:

```javascript
test("builds indexed geometry for a preview part", () => {
  const geometry = buildPartGeometry({
    nodes: [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
    faces: [[0, 1, 2]]
  });
  assert.equal(geometry.getAttribute("position").count, 3);
  assert.equal(geometry.index.count, 3);
});

test("disposes old geometry on reload", () => {
  const tracker = loadThenReplacePreview();
  assert.equal(tracker.disposedGeometries, tracker.oldGeometryCount);
});
```

- [ ] **Step 2: Run JavaScript tests and confirm RED**

Run:

```powershell
node --test tests/web/phase17_viewer.test.mjs
```

Expected: module is missing.

- [ ] **Step 3: Implement renderer lifecycle**

`phase17_viewer.js` must:

```javascript
export class Phase17Viewer {
  constructor(canvas, callbacks) {}
  loadPreview(preview) {}
  clear() {}
  resize() {}
  fit() {}
  setView(name) {}
  setDisplayMode(mode) {}
  dispose() {}
}
```

Use:

- `WebGLRenderer({canvas, antialias: true, alpha: false})`;
- a perspective camera;
- `OrbitControls`;
- ambient plus directional lighting;
- stable grid and XYZ axes;
- indexed `BufferGeometry`;
- one `Group` per semantic component;
- one child mesh per Part;
- one editable volume object for the real ALE explosive source;
- explicit disposal of geometry, material, outline, and controls.

- [ ] **Step 4: Bridge current model loading to the new viewer**

Change `loadInteractiveMesh(projectName)` so model mode sends preview data to `window.phase17Viewer.loadPreview(mesh)`. Keep result drawing on the legacy result canvas.

The bridge must tolerate viewer initialization order:

```javascript
window.addEventListener("phase17-viewer-ready", () => {
  if (viewer.mesh) window.phase17Viewer.loadPreview(viewer.mesh);
});
```

- [ ] **Step 5: Run JavaScript and Python Web tests**

Run:

```powershell
node --test tests/web/phase17_viewer.test.mjs
python -m unittest tests.test_web_app tests.test_web_preview_mesh tests.test_phase17_static_assets
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add lsprepost_mcp/web/static/phase17_viewer.js lsprepost_mcp/web/static/app.js lsprepost_mcp/web/static/style.css tests/web/phase17_viewer.test.mjs
git commit -m "feat: render model previews with threejs"
```

---

### Task 5: Add Semantic Selection and Mobility-Aware Transform Controls

**Files:**
- Modify: `lsprepost_mcp/web/static/phase17_viewer.js`
- Modify: `lsprepost_mcp/web/static/app.js`
- Modify: `lsprepost_mcp/web/static/index.html`
- Modify: `lsprepost_mcp/web/static/style.css`
- Modify: `tests/web/phase17_viewer.test.mjs`

**Interfaces:**
- Produces: `selectComponent(componentId: string | null): void`
- Produces: `selectSource(sourceId: string | null): void`
- Produces: `setTransformMode(mode: "translate" | "rotate"): void`
- Emits: `onSelectionChange(componentId)`
- Emits: `onTransformPreview(componentId, transform)`
- Emits: `onTransformCommit(componentId, before, after)`

- [ ] **Step 1: Write failing selection and commit tests**

```javascript
test("clicking any part selects its entire component", () => {
  const viewer = viewerWithTwoPartsForOneComponent();
  viewer.pickObject(viewer.partObject(2));
  assert.equal(viewer.selectedComponentId, "rebar");
  assert.equal(viewer.highlightedPartCount(), 2);
});

test("one drag emits one committed transform", () => {
  const events = simulateTransformDrag("rebar", [0, 0, 0], [0.1, 0, 0]);
  assert.equal(events.preview.length > 1, true);
  assert.equal(events.commit.length, 1);
});

test("grounded buildings expose only tx ty rz", () => {
  const viewer = viewerWithGroundedBuilding();
  viewer.selectComponent("commercial_supermarket");
  assert.deepEqual(viewer.enabledDofs(), ["tx", "ty", "rz"]);
});

test("blast source exposes translation only", () => {
  const viewer = viewerWithCityBlastSource();
  viewer.selectSource("city_tnt");
  assert.deepEqual(viewer.enabledDofs(), ["tx", "ty", "tz"]);
});
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
node --test tests/web/phase17_viewer.test.mjs
```

Expected: selection and transform methods are absent.

- [ ] **Step 3: Implement raycast selection and component groups**

Each mesh must carry:

```javascript
mesh.userData = {
  partId: String(part.part_id),
  componentId: component.component_id,
  editable: component.editable === true
};
```

Raycast only visible meshes. Resolve a hit to `componentId` or `sourceId`, highlight the entire semantic object, attach `TransformControls` to its pivot object, and detach it for read-only or hidden objects.

- [ ] **Step 4: Implement translate/rotate controls**

Requirements:

- mode buttons use familiar move and rotate icons with tooltips;
- only world space is enabled;
- scale handles are disabled;
- `grounded` enables X/Y translation and Z rotation only;
- `blast_source` enables X/Y/Z translation only;
- `free_component` enables X/Y/Z translation and X/Y/Z rotation;
- `fixed` and protocol-only `airborne` expose no manipulator in the first release;
- OrbitControls is disabled during transform drag;
- Escape restores the pre-drag transform;
- pointer-up emits one commit;
- transform values are converted to metres and X/Y/Z degrees using the backend order.

- [ ] **Step 5: Synchronize component list selection**

Add a selected component ID to the draft state. Selecting from the component cards calls `phase17Viewer.selectComponent(id)`. Viewer selection scrolls the corresponding component card into view without changing component order.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
node --test tests/web/phase17_viewer.test.mjs
python -m unittest tests.test_phase17_static_assets
```

Expected: all pass.

- [ ] **Step 7: Commit**

```powershell
git add lsprepost_mcp/web/static/phase17_viewer.js lsprepost_mcp/web/static/app.js lsprepost_mcp/web/static/index.html lsprepost_mcp/web/static/style.css tests/web/phase17_viewer.test.mjs
git commit -m "feat: add component selection and transform gizmos"
```

---

### Task 6: Build Source-Aware Draft State, Numeric Sync, and Edit History

**Files:**
- Create: `lsprepost_mcp/web/static/phase17_draft.js`
- Modify: `lsprepost_mcp/web/static/app.js`
- Modify: `lsprepost_mcp/web/static/index.html`
- Modify: `lsprepost_mcp/web/static/style.css`
- Create: `tests/web/phase17_draft.test.mjs`

**Interfaces:**
- Produces: `createDraft(payload) -> EditableSceneDraft`
- Produces: `commitObjectTransform(objectId, transform) -> number`
- Produces: `undo()`, `redo()`, `resetComponent(componentId)`
- Produces: monotonically increasing `revision`

- [ ] **Step 1: Write failing history and finite-number tests**

```javascript
test("one committed drag creates one undo entry", () => {
  const draft = draftFixture();
  draft.commitObjectTransform("rebar", transform([0.1, 0, 0], [0, 0, 0]));
  assert.equal(draft.historyLength(), 1);
  draft.undo();
  assert.deepEqual(draft.component("rebar").transform.translate_m, [0, 0, 0.62]);
});

test("grounded building rejects z translation and pitch", () => {
  const draft = cityDraftFixture();
  assert.throws(
    () => draft.commitObjectTransform(
      "commercial_supermarket",
      transform([1, 2, 0.1], [5, 0, 15])
    ),
    /mobility profile/
  );
});

test("rejects non-finite numeric input", () => {
  const draft = draftFixture();
  assert.throws(
    () => draft.commitComponentTransform("rebar", transform([NaN, 0, 0], [0, 0, 0])),
    /finite/
  );
});
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
node --test tests/web/phase17_draft.test.mjs
```

Expected: draft module missing.

- [ ] **Step 3: Implement immutable history records**

Use:

```javascript
{
  componentId: "rebar",
  before: {translate_m: [...], rotate_deg: [...]},
  after: {translate_m: [...], rotate_deg: [...]}
}
```

Cap undo history at 100 entries. A new commit clears redo. Revision increases on commit, undo, redo, reset, component add/remove, and physics action change.

- [ ] **Step 4: Add numeric transform controls**

Add X/Y/Z metre and X/Y/Z degree inputs for the selected component. Input commit must:

1. parse with `Number`;
2. require `Number.isFinite`;
3. commit the whole six-value transform atomically;
4. update the gizmo;
5. request a new preview.

- [ ] **Step 5: Debounce preview and discard stale responses**

Implement:

```javascript
async function refreshDraftPreview(expectedRevision) {
  const result = await api("/api/editor/preview", {
    method: "POST",
    body: draft.previewPayload()
  });
  if (result.revision !== draft.revision || result.revision !== expectedRevision) return;
  phase17Viewer.loadPreview(result);
}
```

Use a 150 ms debounce for numeric edits. Transform drag previews stay client-side; pointer-up performs the backend refresh.

- [ ] **Step 6: Run JavaScript tests**

Run:

```powershell
node --test tests/web/phase17_draft.test.mjs tests/web/phase17_viewer.test.mjs
```

Expected: all pass.

- [ ] **Step 7: Commit**

```powershell
git add lsprepost_mcp/web/static/phase17_draft.js lsprepost_mcp/web/static/app.js lsprepost_mcp/web/static/index.html lsprepost_mcp/web/static/style.css tests/web/phase17_draft.test.mjs
git commit -m "feat: add phase17 draft history and numeric transforms"
```

---

### Task 7: Add Mobility, Geometry, ALE, and Physics Gates

**Files:**
- Create: `lsprepost_mcp/assembly_validation.py`
- Create: `lsprepost_mcp/city_editor.py`
- Modify: `lsprepost_mcp/city_street_blast.py`
- Modify: `lsprepost_mcp/tool_generation.py`
- Modify: `lsprepost_mcp/keyword_checks.py`
- Create: `tests/test_phase17_assembly_validation.py`
- Create: `tests/test_phase17_city_editor.py`
- Modify: `tests/test_tools.py`

**Interfaces:**
- Produces: `validate_assembly_layout(spec: ModelSpec, metadata: JSONDict) -> list[JSONDict]`
- Produces blocking codes:
  - `component_transform_nonfinite`
  - `component_initial_penetration`
  - `contact_component_missing`
  - `fixed_region_empty`
- Produces city blocking codes:
  - `unsupported_object_dof`
  - `ground_support_missing`
  - `city_object_outside_ale_domain`
  - `city_object_initial_penetration`
  - `blast_source_outside_air`
  - `blast_source_intersects_structure`
  - `blast_marker_only_move`
  - `city_fsi_surface_empty`
  - `city_probe_mapping_stale`
- Consumed by: draft preview, assembly validation, and final generation

- [ ] **Step 1: Write failing validation tests**

```python
def test_nonfinite_rotation_is_rejected(self):
    payload = valid_assembly()
    payload["components"][0]["transform"]["rotate_deg"] = [0.0, float("inf"), 0.0]
    with self.assertRaisesRegex(ValueError, "finite"):
        tool_assemble_components({**payload, "dry_run": True})

def test_initial_penetration_blocks_generation(self):
    payload = penetrating_rebar_helmet_assembly()
    result = validate_assembly_payload(payload)
    self.assertIn(
        "component_initial_penetration",
        {issue["code"] for issue in result["blocking_issues"]},
    )

def test_city_building_is_projected_to_ground(self):
    spec = valid_city_editor_spec()
    move_object(spec, "commercial_supermarket", translate_m=[2.0, 1.0, 0.0], rotate_deg=[0, 0, 20])
    resolved = validate_city_editor_spec(spec)
    self.assertTrue(all_building_base_nodes_supported(resolved, "commercial_supermarket"))

def test_city_blast_source_cannot_overlap_building(self):
    spec = valid_city_editor_spec()
    move_blast_source_into(spec, "commercial_supermarket")
    issues = validate_city_editor_layout(spec)
    self.assertIn("blast_source_intersects_structure", {item["code"] for item in issues})
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_phase17_assembly_validation tests.test_tools
```

Expected: no layout validator and penetration is accepted.

- [ ] **Step 3: Implement structured validation**

Implement:

```python
def validate_assembly_layout(spec: ModelSpec, metadata: JSONDict) -> list[JSONDict]:
    issues: list[JSONDict] = []
    issues.extend(validate_component_transforms(spec.components))
    issues.extend(validate_component_bounds(metadata["components"]))
    issues.extend(validate_contact_references(spec, metadata))
    issues.extend(validate_fixed_regions(metadata))
    issues.extend(validate_disallowed_penetrations(spec, metadata))
    return issues

def validate_city_editor_layout(spec: JSONDict, compiled: JSONDict) -> list[JSONDict]:
    issues: list[JSONDict] = []
    issues.extend(validate_mobility_profiles(spec))
    issues.extend(validate_ground_support(spec, compiled))
    issues.extend(validate_city_domain_containment(spec, compiled))
    issues.extend(validate_city_object_intersections(spec, compiled))
    issues.extend(validate_real_explosive_placement(spec, compiled))
    issues.extend(validate_city_fsi_and_probe_mappings(spec, compiled))
    return issues
```

Penetration broad phase uses component AABBs. Candidate pairs use element boundary triangles and a tolerance based on `min(mesh_size_m) * 1.0e-4`, bounded below by `1.0e-9 m`. Existing intentional contact at zero gap is allowed; positive volume penetration is blocking.

- [ ] **Step 4: Integrate one authoritative validation path**

Assembly generation and city-street generation must call their authoritative validators for:

- `dry_run=True`;
- draft preview;
- final generation.

Return structured issues in dry-run and preview responses. Final generation raises a value error containing blocking issue codes.

For a city blast-source move, validate that `base_center_m`, TNT ALE volume fractions, `*INITIAL_DETONATION`, preview metadata, and emitted K cards all resolve to the same position. Reject a payload that changes only preview `blast_sources`.

- [ ] **Step 5: Run assembly and keyword tests**

Run:

```powershell
python -m unittest tests.test_phase17_assembly_validation tests.test_phase17_city_editor tests.test_tools tests.test_keyword_checks
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add lsprepost_mcp/assembly_validation.py lsprepost_mcp/city_editor.py lsprepost_mcp/city_street_blast.py lsprepost_mcp/tool_generation.py lsprepost_mcp/keyword_checks.py tests/test_phase17_assembly_validation.py tests/test_phase17_city_editor.py tests/test_tools.py
git commit -m "feat: validate phase17 scene transforms"
```

---

### Task 8: Qualify the Editable City Street Blast Scene

**Files:**
- Modify: `lsprepost_mcp/city_street_blast.py`
- Modify: `lsprepost_mcp/city_editor.py`
- Modify: `lsprepost_mcp/web/preview_mesh.py`
- Modify: `lsprepost_mcp/web/static/app.js`
- Modify: `tests/test_phase17_city_editor.py`
- Create: `tests/test_phase17_rebar_helmet.py`
- Modify: `tests/test_city_street_blast.py`
- Modify: `tests/test_scene_prompts.py`

**Interfaces:**
- Produces: editable draft source `source_kind="city_street_blast"`
- Produces: `city_editable_objects(spec) -> list[JSONDict]`
- Produces: `apply_city_editor_transforms(spec, transforms) -> JSONDict`
- Produces: real editable source `source_id="city_tnt"`
- Preserves: stable city semantic object IDs and existing default city geometry
- Keeps: `rebar_drop_on_helmet` as a non-city transform regression
- Produces: source-centered graded ALE axes while preserving fixed domain bounds
- Produces: actual local-cell coverage evidence and an ALE mesh fingerprint

- [ ] **Step 1: Write failing city editing contract tests**

```python
def test_city_catalog_marks_only_authorized_buildings_grounded(self):
    objects = {item["object_id"]: item for item in city_editable_objects(default_city_spec())}
    self.assertEqual(objects["commercial_supermarket"]["mobility_profile"], "grounded")
    self.assertEqual(objects["commercial_supermarket"]["allowed_dofs"], ["tx", "ty", "rz"])
    self.assertEqual(objects["ground_foundation"]["mobility_profile"], "fixed")
    self.assertEqual(objects["concrete_roads"]["mobility_profile"], "fixed")

def test_moving_tnt_changes_real_ale_initialization(self):
    original = compile_city(default_city_spec())
    moved_spec = default_city_spec()
    moved_spec["explosive"]["base_center_m"] = [1.0, -0.5, 0.25]
    moved = compile_city(moved_spec)
    self.assertNotEqual(original.tnt_volume_fraction_cards, moved.tnt_volume_fraction_cards)
    self.assertEqual(parse_initial_detonation(moved.initial_detonation_card).position_m, [1.0, -0.5, 0.75])
    self.assertEqual(moved.metadata["explosive"]["base_center_m"], [1.0, -0.5, 0.25])

def test_grounded_building_cannot_be_lifted_or_tilted(self):
    spec = default_city_spec()
    transforms = {
        "commercial_supermarket": {
            "translate_m": [1.0, 2.0, 0.2],
            "rotate_deg": [5.0, 0.0, 15.0],
        }
    }
    with self.assertRaisesRegex(ValueError, "grounded"):
        apply_city_editor_transforms(spec, transforms)

def test_blast_move_recenters_ale_refinement_without_moving_domain(self):
    baseline = default_city_street_blast_spec("baseline")
    _keyword, before = build_city_street_blast_keyword(baseline)
    moved = deepcopy(baseline)
    moved["explosive"]["base_center_m"] = [6.0, -5.0, 0.61]
    _keyword, after = build_city_street_blast_keyword(moved)
    self.assertEqual(before["ale_domain"]["bounds_m"], after["ale_domain"]["bounds_m"])
    self.assertNotEqual(
        before["ale_domain"]["mesh_fingerprint"],
        after["ale_domain"]["mesh_fingerprint"],
    )
    self.assertEqual(
        after["ale_domain"]["refinement_center_m"],
        after["explosive"]["center_m"],
    )
    self.assertGreaterEqual(after["explosive"]["diameter_cells_actual"], 3.0)
    self.assertGreaterEqual(after["explosive"]["length_cells_actual"], 3.0)
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_phase17_city_editor tests.test_city_street_blast
```

Expected: city editor interfaces are missing.

- [ ] **Step 3: Add explicit mobility metadata**

Add an allowlist to the controlled city specification:

```python
CITY_MOBILITY = {
    "commercial_supermarket": {
        "mobility_profile": "grounded",
        "support_object_id": "ground_foundation",
        "allowed_dofs": ["tx", "ty", "rz"],
    },
    "residential_community": {
        "mobility_profile": "grounded",
        "support_object_id": "ground_foundation",
        "allowed_dofs": ["tx", "ty", "rz"],
    },
}
```

All unlisted semantic objects are `fixed`. The real TNT source is declared separately as `blast_source`.

- [ ] **Step 4: Apply grounded building transforms before meshing**

`apply_city_editor_transforms()` must:

1. validate finite values and exact allowed DOFs;
2. calculate the support-plane Z from `support_object_id`;
3. apply X/Y translation and Z rotation to the complete semantic object definition;
4. regenerate nodes, elements, named regions, fixed nodes, FSI faces, Part metadata, and result mappings;
5. preserve `object_id`;
6. reject domain exit, exclusion-region entry, missing support, and initial penetration.

- [ ] **Step 5: Move the real TNT initialization**

`city_tnt.position_m` is the TNT geometric center. Convert it to `spec["explosive"]["base_center_m"]` by subtracting half the current TNT length from Z, then run the existing city compiler. Add an invariant:

```python
assert_real_blast_source_binding(
    requested_position=editor_source["position_m"],
    explosive_metadata=metadata["explosive"],
    initial_detonation=parsed_initial_detonation,
    initialized_tnt_cells=metadata["tnt_initialization"]["cells"],
)
```

The invariant returns `blast_marker_only_move` if only preview metadata changed.

Generate the horizontal and vertical ALE axes around the TNT geometric center.
Clip only urban/far transition extents; never clip the required near-field window.
If that window cannot fit inside the fixed domain, fail with
`blast_refinement_window_outside_domain`. Compute TNT coverage from the actual
containing cell widths. Recompute probes, outer boundaries, initialization,
detonation, and all element/set references from the rebuilt mesh.

- [ ] **Step 6: Recompute probes and invalidate results**

Pressure-path probes must be derived from the moved source and current target positions. The new draft carries no city-impact result. An editable copy stores the source model hash only as provenance; it must not copy `object_metrics.json`, `d3plot`, `matsum`, or a prior risk classification.

- [ ] **Step 7: Keep rebar-on-helmet as a regression**

Add a focused test proving `free_component` still allows steel rebar X/Y/Z translation and X/Y/Z rotation, while its initial velocity remains a world vector. This test does not define Phase 17 completion.

- [ ] **Step 8: Run city and component regressions**

Run:

```powershell
python -m unittest tests.test_phase17_city_editor tests.test_city_street_blast tests.test_phase17_rebar_helmet tests.test_scene_prompts tests.test_tools
node --test tests/web/phase17_draft.test.mjs tests/web/phase17_viewer.test.mjs
```

Expected: all pass.

The generated project must also pass `validate_project_files()`. When LS-PrePost is
configured, run the controlled import check and bind its evidence to the generated
`model.k` SHA-256; stale import evidence must not qualify a regenerated mesh.

- [ ] **Step 9: Commit**

```powershell
git add lsprepost_mcp/city_street_blast.py lsprepost_mcp/city_editor.py lsprepost_mcp/web/preview_mesh.py lsprepost_mcp/web/static/app.js tests/test_phase17_city_editor.py tests/test_phase17_rebar_helmet.py tests/test_city_street_blast.py tests/test_scene_prompts.py
git commit -m "feat: qualify editable city blast scene"
```

---

### Task 9: Integrate Phase 16A/16B Compatibility

**Files:**
- Create: `lsprepost_mcp/city_layout_contract.py`
- Modify: `lsprepost_mcp/city_editor.py`
- Modify: `lsprepost_mcp/city_street_blast.py`
- Modify: `lsprepost_mcp/city_impact.py`
- Modify: `lsprepost_mcp/phase16b.py`
- Modify: `lsprepost_mcp/web/static/app.js`
- Create: `tests/test_phase17_phase16_compat.py`
- Modify: `tests/test_city_impact.py`
- Modify: `tests/test_phase16b.py`

**Interfaces:**
- Produces: `CITY_LAYOUT_SCHEMA_VERSION = "phase17.city_layout.v1"`
- Produces: `CITY_EDITOR_STATE_SCHEMA_VERSION = "phase17.city_editor_state.v1"`
- Produces: `build_city_layout_contract(resolved_spec: JSONDict, metadata: JSONDict) -> JSONDict`
- Produces: `city_layout_fingerprint(resolved_spec: JSONDict, metadata: JSONDict) -> str`
- Produces: `city_editor_state_fingerprint(resolved_spec: JSONDict, metadata: JSONDict) -> str`
- Produces: additive `layout_fingerprint` in Phase 16A assessments
- Produces: `reference_layout_fingerprint` in new Phase 16B matrices
- Produces blocking codes:
  - `layout_fingerprint_missing`
  - `layout_fingerprint_mismatch`
  - `layout_out_of_surrogate_domain`
  - `layout_changed_refinement_stale`
- Preserves: historical Phase 16A assessment reads and Phase 16B artifacts

- [ ] **Step 1: Write failing canonical-layout tests**

```python
def test_layout_fingerprint_is_stable_across_part_renumbering(self):
    spec, metadata = city_fixture()
    first = city_layout_fingerprint(spec, metadata)
    metadata["semantic_objects"][0]["part_ids"] = [9001]
    second = city_layout_fingerprint(spec, metadata)
    self.assertEqual(first, second)

def test_layout_fingerprint_changes_when_building_moves(self):
    spec, metadata = city_fixture()
    before = city_layout_fingerprint(spec, metadata)
    spec["layout"]["supermarket"]["origin_m"][0] += 1.0
    moved_keyword, moved_metadata = build_city_street_blast_keyword(spec)
    after = city_layout_fingerprint(spec, moved_metadata)
    self.assertNotEqual(before, after)

def test_layout_contract_normalizes_negative_zero(self):
    spec, metadata = city_fixture()
    metadata["semantic_objects"][0]["translate_m"] = [-0.0, 0.0, 0.0]
    contract = build_city_layout_contract(spec, metadata)
    self.assertEqual(contract["objects"][0]["translate_m"][0], 0.0)

def test_blast_move_changes_editor_state_but_not_layout(self):
    spec, metadata = city_fixture()
    layout_before = city_layout_fingerprint(spec, metadata)
    state_before = city_editor_state_fingerprint(spec, metadata)
    spec["explosive"]["base_center_m"][0] += 1.0
    _keyword, moved_metadata = build_city_street_blast_keyword(spec)
    self.assertEqual(layout_before, city_layout_fingerprint(spec, moved_metadata))
    self.assertNotEqual(state_before, city_editor_state_fingerprint(spec, moved_metadata))
```

- [ ] **Step 2: Run compatibility tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_phase17_phase16_compat tests.test_city_impact tests.test_phase16b
```

Expected: `city_layout_contract` is missing.

- [ ] **Step 3: Implement the canonical layout contract**

Implement:

```python
CITY_LAYOUT_SCHEMA_VERSION = "phase17.city_layout.v1"
CITY_EDITOR_STATE_SCHEMA_VERSION = "phase17.city_editor_state.v1"

def build_city_layout_contract(
    resolved_spec: JSONDict,
    metadata: JSONDict,
) -> JSONDict:
    objects = []
    for item in sorted(metadata["semantic_objects"], key=lambda row: row["object_id"]):
        objects.append({
            "object_id": str(item["object_id"]),
            "mobility_profile": str(item.get("mobility_profile", "fixed")),
            "translate_m": finite_vector3(item.get("translate_m", [0.0, 0.0, 0.0])),
            "rotate_z_deg": canonical_number(item.get("rotate_z_deg", 0.0)),
            "bounds_m": canonical_bounds(item["bounds_m"]),
            "support_object_id": item.get("support_object_id"),
        })
    return {
        "schema_version": CITY_LAYOUT_SCHEMA_VERSION,
        "semantic_schema_version": str(metadata["city_semantic_schema_version"]),
        "objects": objects,
    }

def city_layout_fingerprint(resolved_spec: JSONDict, metadata: JSONDict) -> str:
    payload = json.dumps(
        build_city_layout_contract(resolved_spec, metadata),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()

def city_editor_state_fingerprint(
    resolved_spec: JSONDict,
    metadata: JSONDict,
) -> str:
    return digest({
        "schema_version": CITY_EDITOR_STATE_SCHEMA_VERSION,
        "layout_fingerprint": city_layout_fingerprint(resolved_spec, metadata),
        "blast_center_m": observed_blast_center(resolved_spec),
    })
```

`canonical_number()` must reject booleans/non-finite values and convert every numeric zero to `0.0`. Do not include project name, timestamps, Part IDs, mesh, materials, or results.

- [ ] **Step 4: Add Phase 16A compatibility and dirty-state invalidation**

Add `layout_fingerprint` to the Phase 16A assessment as an optional additive field while retaining `CITY_IMPACT_SCHEMA_VERSION = "phase16a.city_impact.v1"`.

Add tests proving:

- an old project without `layout_fingerprint` still renders its own assessment;
- moved geometry changes `model_sha256` and invalidates old metrics;
- the first draft edit clears `viewer.riskByPartId`, object metrics, report links, and readiness;
- the UI shows `布局已修改，尚未求解`;
- the editor never copies Phase 16A result artifacts.

- [ ] **Step 5: Bind new Phase 16B studies and repositories to layout**

For newly created matrices add:

```python
matrix_core["reference_layout_fingerprint"] = city_layout_fingerprint(
    resolved_spec,
    model["metadata"],
)
```

Propagate the layout field into authorization, result index, registered records, comparison output, uncertainty output, refinement plans, surrogate models, predictions, and protection rankings. Store `editor_state_fingerprint` in exact generated-project and case evidence.

Enforce:

- registration requires result layout fingerprint to equal the matrix reference;
- old authorization cannot authorize a new-layout matrix;
- moving only the blast source keeps the layout fingerprint but changes `blast_center_x_m/y_m/z_m`, case ID, editor-state fingerprint, model hash, and required authorization;
- a new blast-center combination must be declared by a matrix version rather than appended to an existing immutable matrix;
- `allow_mixed_mesh` never bypasses layout mismatch;
- `allow_semantic_variants` does not suppress `layout_fingerprint_mismatch`;
- historical matrices without layout fingerprint remain readable by legacy operations but are rejected by Phase 17 layout operations with `layout_fingerprint_missing`.

- [ ] **Step 6: Bind refinement and surrogate applicability**

Add tests equivalent to:

```python
def test_moved_layout_invalidates_refinement_plan(self):
    plan = accepted_refinement_plan(layout_fingerprint="a" * 64)
    result = validate_refinement_for_layout(plan, "b" * 64)
    self.assertEqual(result["status"], "stale")
    self.assertIn("layout_changed_refinement_stale", result["blocking_reasons"])

def test_surrogate_rejects_layout_before_knn(self):
    model = accepted_surrogate(layout_fingerprint="a" * 64)
    with self.assertRaisesRegex(ValueError, "layout_out_of_surrogate_domain"):
        predict_surrogate_response(
            model,
            parameters=valid_parameters(),
            layout_fingerprint="b" * 64,
        )

def test_blast_move_keeps_layout_but_invalidates_exact_plan(self):
    plan = accepted_refinement_plan(
        layout_fingerprint="a" * 64,
        editor_state_fingerprint="b" * 64,
    )
    result = validate_refinement_for_state(
        plan,
        layout_fingerprint="a" * 64,
        editor_state_fingerprint="c" * 64,
    )
    self.assertEqual(result["status"], "stale")
    self.assertIn("case_parameters_changed_refinement_stale", result["blocking_reasons"])
```

Prediction must compare layout fingerprints before range normalization, neighbor search, or estimation. A Phase 16B.6 held-out layout must be tagged `independent_layout_validation=true` and rejected from training samples.

- [ ] **Step 7: Reuse Phase 16B blast coordinates**

The editor adapter must map:

```python
{
    "blast_center_x_m": center[0],
    "blast_center_y_m": center[1],
    "blast_center_z_m": center[2],
}
```

to the existing Phase 16B parameter contract. Add a regression proving there is no second `explosive_x_m`, `source_position_m`, or equivalent public field.

- [ ] **Step 8: Run Phase 16 and Phase 17 compatibility tests**

Run:

```powershell
python -m unittest tests.test_phase17_phase16_compat tests.test_city_impact tests.test_phase16b tests.test_phase17_city_editor tests.test_city_street_blast
```

Expected: all current Phase 16 behavior remains green; new-layout misuse fails closed.

- [ ] **Step 9: Commit**

```powershell
git add lsprepost_mcp/city_layout_contract.py lsprepost_mcp/city_editor.py lsprepost_mcp/city_street_blast.py lsprepost_mcp/city_impact.py lsprepost_mcp/phase16b.py lsprepost_mcp/web/static/app.js tests/test_phase17_phase16_compat.py tests/test_city_impact.py tests/test_phase16b.py
git commit -m "feat: bind phase17 layouts to phase16 studies"
```

---

### Task 10: Enforce Immutable Generation and Editor Provenance

**Files:**
- Modify: `lsprepost_mcp/tool_generation.py`
- Modify: `lsprepost_mcp/project_store.py`
- Modify: `lsprepost_mcp/web/static/app.js`
- Create: `tests/test_phase17_project_immutability.py`
- Modify: `tests/test_tools.py`

**Interfaces:**
- Consumes: validated source-aware editor draft
- Produces: `editor_provenance` in `model.json`
- Enforces: Phase 17 Web generation uses `if_exists="error"`
- Produces: “创建可编辑副本” flow for existing assembly and city projects

- [ ] **Step 1: Write failing immutability tests**

```python
def test_phase17_generation_refuses_existing_project(self):
    create_existing_project("phase17_existing")
    with self.assertRaises(FileExistsError):
        generate_phase17_project(project_name="phase17_existing")

def test_phase17_generation_records_source_hash(self):
    result = generate_phase17_project(
        project_name="phase17_copy",
        source_project_name="baseline",
        source_model_sha256="a" * 64,
        source_layout_fingerprint="b" * 64,
        source_editor_state_fingerprint="c" * 64,
        draft_revision=14,
    )
    model = read_json(Path(result["project_path"]) / "model.json")
    self.assertEqual(model["editor_provenance"]["editor_phase"], 17)
    self.assertEqual(model["editor_provenance"]["draft_revision"], 14)
    self.assertEqual(model["editor_provenance"]["source_layout_fingerprint"], "b" * 64)
    self.assertRegex(model["editor_provenance"]["layout_fingerprint"], r"^[0-9a-f]{64}$")
    self.assertRegex(model["editor_provenance"]["editor_state_fingerprint"], r"^[0-9a-f]{64}$")

def test_city_editable_copy_does_not_copy_results(self):
    result = create_city_editable_copy("city_source", "city_layout_copy")
    copied = Path(result["project_path"])
    for name in ("d3plot", "matsum", "object_metrics.json", "city_impact.json"):
        self.assertFalse((copied / name).exists())

def test_city_editable_copy_does_not_inherit_phase16b_authorization(self):
    result = create_city_editable_copy("city_source", "city_layout_copy")
    copied = Path(result["project_path"])
    self.assertFalse((copied / "artifacts" / "phase16b").exists())
    self.assertEqual(result["phase16b_status"], "new_layout_requires_new_study")
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_phase17_project_immutability tests.test_tools
```

Expected: provenance absent.

- [ ] **Step 3: Add strict editor provenance**

Accept an internal structured field:

```python
editor_provenance = {
    "editor_phase": 17,
    "source_project_name": source_project_name,
    "source_model_sha256": source_model_sha256,
    "source_layout_fingerprint": source_layout_fingerprint,
    "source_editor_state_fingerprint": source_editor_state_fingerprint,
    "layout_fingerprint": layout_fingerprint,
    "editor_state_fingerprint": editor_state_fingerprint,
    "draft_revision": draft_revision,
}
```

Validate project names, 64-character lowercase SHA-256 strings, and nonnegative revision. Recompute `layout_fingerprint` and `editor_state_fingerprint` from the final compiled metadata instead of trusting the browser. Store final component/source transforms and mobility profiles in the resolved spec persisted by the project writer.

- [ ] **Step 4: Implement editable-copy UI**

Existing project model views remain read-only. For assembly and city projects with complete structured provenance, enable “创建可编辑副本”. The action:

1. reads the structured source spec;
2. creates a draft;
3. clears any solver-result selection;
4. requires a new project name;
5. generates with `if_exists="error"`.
6. excludes every prior solver result, city metric, risk classification, preview artifact, and run record.
7. excludes every prior Phase 16B matrix, authorization, repository, refinement plan, surrogate model, prediction, and ranking.
8. displays `新布局需要新建 Phase 16B 研究`.

Projects without reconstructable component/source provenance remain read-only.

- [ ] **Step 5: Run project tests**

Run:

```powershell
python -m unittest tests.test_phase17_project_immutability tests.test_tools tests.test_web_app
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add lsprepost_mcp/tool_generation.py lsprepost_mcp/project_store.py lsprepost_mcp/web/static/app.js tests/test_phase17_project_immutability.py tests/test_tools.py
git commit -m "feat: preserve phase17 project immutability"
```

---

### Task 11: Add Playwright Visual and Interaction Acceptance

**Files:**
- Create: `playwright.config.mjs`
- Create: `tests/e2e/phase17-editor.spec.mjs`
- Create: `scripts/test_phase17_web.ps1`
- Modify: `scripts/run_test_matrix.ps1`
- Modify: `docs/ROADMAP.zh-CN.md`
- Modify: `README.zh-CN.md`

**Interfaces:**
- Produces: desktop and mobile screenshot evidence
- Verifies: WebGL canvas nonblank, city model framed, real source/building selectable, mobility-specific gizmos active, transform committed
- Preserves: external solver launch remains opt-in

- [ ] **Step 1: Write the failing Playwright test**

The test must:

```javascript
test("moves city blast source and grounded building without mutating source", async ({ page }) => {
  await page.goto("/");
  await selectModelMode(page, "city_street_blast");
  await prepareCityDraft(page);
  await expect(page.locator("#modelViewerCanvas")).toBeVisible();
  await expectNonBlankCanvas(page, "#modelViewerCanvas");
  await page.getByRole("button", {name: "城市 TNT 爆源"}).click();
  await expectEnabledDofs(page, ["tx", "ty", "tz"]);
  const sourceX = await page.locator('[data-field="translate-x"]').inputValue();
  await dragTransformAxis(page, "x", 48);
  await expect(page.locator('[data-field="translate-x"]')).not.toHaveValue("0");
  await page.getByRole("button", {name: "撤销"}).click();
  await expect(page.locator('[data-field="translate-x"]')).toHaveValue(sourceX);
  await page.getByRole("button", {name: "商业超市"}).click();
  await expectEnabledDofs(page, ["tx", "ty", "rz"]);
  await expect(page.locator('[data-axis="tz"]')).toBeHidden();
  await dragTransformAxis(page, "y", 32);
  await expect(page.locator('[data-field="translate-y"]')).not.toHaveValue("0");
});
```

Add tests that:

- move the TNT volume outside the ALE air bounds and confirm `blast_source_outside_air`;
- move the TNT volume into a building and confirm `blast_source_intersects_structure`;
- attempt to lift a grounded building and confirm the Z field and Z handle are unavailable;
- move a building into another structure and confirm `city_object_initial_penetration`;
- generate a valid moved city scene under a new project name and confirm source hashes are unchanged;
- confirm the first edit clears Phase 16A risk coloring and shows `布局已修改，尚未求解`;
- confirm the generated project has a different `layout_fingerprint`;
- in a source-only edit, confirm `layout_fingerprint` is unchanged while `editor_state_fingerprint` changes;
- confirm old Phase 16B authorization is absent and no old matrix accepts the new layout;
- confirm a source-only edit cannot reuse another case ID or case authorization;
- confirm surrogate prediction refuses the new layout before computing an estimate;
- retain one rebar-on-helmet selection/rotation regression.

- [ ] **Step 2: Run Playwright and confirm RED**

Run:

```powershell
npx playwright test tests/e2e/phase17-editor.spec.mjs
```

Expected: selectors or Phase 17 controls are missing.

- [ ] **Step 3: Add deterministic Web server orchestration**

`scripts/test_phase17_web.ps1` must:

1. choose a free localhost port;
2. start `python -m lsprepost_mcp.web.app`;
3. poll the health endpoint;
4. run Playwright;
5. stop the exact child process tree in `finally`;
6. fail when the server or browser remains alive.

- [ ] **Step 4: Add visual acceptance matrix**

Run at:

- desktop `1440x1000`;
- compact desktop `1024x768`;
- mobile `390x844`.

For each viewport verify:

- canvas pixel variance exceeds a fixed nonblank threshold;
- model bounding box occupies 20%-90% of the canvas;
- toolbar, outliner, numeric controls and canvas do not overlap;
- the longest Chinese labels remain inside their controls;
- screenshots contain no browser error overlay.

- [ ] **Step 5: Run complete verification**

Run:

```powershell
python -m unittest discover -s tests
python -m compileall -q .\lsprepost_mcp
node --test tests/web/*.test.mjs
powershell -ExecutionPolicy Bypass -File .\scripts\test_phase17_web.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\pack.ps1
```

Expected:

- all Python tests pass;
- all Node tests pass;
- all Playwright tests pass;
- package is generated;
- no runtime directory, local absolute path, CDN reference, `node_modules`, or Playwright output is included.

- [ ] **Step 6: Update status without overstating completion**

Update the roadmap to:

- mark Phase 17.0-17.10 according to completed evidence;
- keep external LS-DYNA solve acceptance separate;
- state that visual editing completion does not establish engineering accuracy.

- [ ] **Step 7: Commit**

```powershell
git add playwright.config.mjs tests/e2e/phase17-editor.spec.mjs scripts/test_phase17_web.ps1 scripts/run_test_matrix.ps1 docs/ROADMAP.zh-CN.md README.zh-CN.md
git commit -m "test: qualify phase17 city scene editor"
```

---

## Final Verification Gate

Before reporting Phase 17 complete:

```powershell
python -m unittest discover -s tests
python -m compileall -q .\lsprepost_mcp
node --test tests/web/*.test.mjs
powershell -ExecutionPolicy Bypass -File .\scripts\test_phase17_web.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\pack.ps1
git diff --check
```

Review the generated evidence and confirm:

- the selected building is a semantic object, not an arbitrary Part;
- the selected city source controls the real TNT ALE initialization, not only a marker;
- grounded buildings expose only X/Y translation and Z rotation;
- future `airborne` metadata does not enable its UI in the first release;
- transform values in the Web draft equal generated `model.json`;
- sampled generated K nodes equal preview nodes within `1.0e-9 m`;
- moved TNT volume fractions and `*INITIAL_DETONATION` agree with the requested source position;
- moved-building FSI sets, support nodes, probes, and semantic mappings are regenerated and nonempty;
- out-of-domain, intersecting, unsupported, or marker-only edits are blocked;
- Phase 16A object IDs and metric units remain unchanged;
- the first layout edit clears old risk colors and object metrics;
- the edited project has a new layout fingerprint and cannot enter the old Phase 16B matrix;
- a source-only move retains the layout fingerprint but changes its exact case/editor-state evidence;
- old batch authorization, refinement plans, surrogate models, and rankings are not inherited;
- a mismatched surrogate returns `layout_out_of_surrogate_domain`;
- the Phase 16B.6 held-out layout is absent from surrogate training samples;
- rebar-on-helmet still passes the generic component regression;
- source projects and solver artifacts have unchanged hashes;
- result mode exposes no transform controls;
- Three.js assets are local and pinned;
- WebGL canvas screenshots are nonblank and correctly framed;
- no external solver was launched without explicit authorization.
