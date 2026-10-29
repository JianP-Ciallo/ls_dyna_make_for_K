# Phase 18F Refined Blast Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a visually consistent but state-isolated Web workbench that drives Phase 18E projects from asset selection through dynamic configuration, layered preview, validation, acknowledgement, generation, and separately authorized external actions.

**Architecture:** Keep the existing Web application shell and neutral WebGL primitives, but add a dedicated `/refined-building-blast` route, a thin API adapter, and a separate JavaScript state store. The browser never calls legacy editor endpoints for refined projects; all authoritative normalization and validation stay in the Phase 18E backend.

**Tech Stack:** Existing Python `ThreadingHTTPServer` Web app, vanilla JavaScript/CSS/HTML, existing WebGL viewer primitives, JSON APIs, pytest/unittest static and HTTP contracts.

## Global Constraints

- Entry is an existing-front-end button labelled `精细化建筑爆炸`.
- Route is `/refined-building-blast`; API prefix is `/api/refined-building-blast/`.
- Visual tokens and camera controls match the existing workbench; draft/API/cache/result state remains independent.
- Fields are driven by building capabilities plus load-provider schema; hidden inapplicable fields must not retain stale values.
- Draft, preview, generate, open LS-PrePost, and launch LS-DYNA are five separate actions.
- External launches require explicit user action and existing authorization checks on every invocation.
- Stale preview responses must never overwrite a newer draft revision.
- Existing city/legacy editor routes and default behavior must remain literal-compatible.

---

### Task 1: Thin Phase 18F API adapter and route delegation

**Files:**
- Create: `lsprepost_mcp/web/refined_blast_api.py`
- Modify: `lsprepost_mcp/web/app.py`
- Create: `tests/test_phase18f_api.py`

**Interfaces:**
- Consumes: Phase 18E `RefinedBlastStore` and service APIs.
- Produces: `handle_refined_blast_get(path, query)`, `handle_refined_blast_post(path, payload)`, and closed JSON responses under `/api/refined-building-blast/`.

- [ ] **Step 1: Write failing routing and isolation tests**

```python
def test_refined_api_is_namespaced(web_client):
    response = web_client.get("/api/refined-building-blast/capabilities")
    assert response.status == 200
    assert {p["provider_id"] for p in response.json["providers"]} == {
        "explicit_ale_fsi", "lbe_segment", "imported_pressure_history"
    }

def test_legacy_editor_does_not_accept_refined_project(web_client):
    response = web_client.post("/api/editor/preview", json=refined_payload())
    assert response.status == 400
```

Cover assets, presets, create/load/save, validate, preview, generate, acknowledgements, artifacts, unknown paths, wrong methods, body limits, host/origin checks, and project-type mismatch.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_phase18f_api.py`

Expected: `/api/refined-building-blast/capabilities` returns 404.

- [ ] **Step 3: Implement a thin delegate instead of expanding route logic inline**

```python
def handle_refined_blast_post(path: str, payload: JSONDict) -> JSONDict:
    route = _POST_ROUTES.get(path)
    if route is None:
        raise ApiError(404, "not_found", f"route not found: {path}")
    return route(payload)
```

`app.py` performs existing host/origin/body checks and delegates only the dedicated prefix.

- [ ] **Step 4: Run API and legacy Web regressions**

Run: `python -m pytest -q tests/test_phase18f_api.py tests/test_web_api.py tests/test_phase17_draft_preview.py`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/web/refined_blast_api.py lsprepost_mcp/web/app.py tests/test_phase18f_api.py
git commit -m "feat: expose isolated phase18f web api"
```

### Task 2: Existing-front-end entry and isolated route shell

**Files:**
- Modify: `lsprepost_mcp/web/static/index.html`
- Modify: `lsprepost_mcp/web/static/app.js`
- Create: `lsprepost_mcp/web/static/refined_blast_workbench.css`
- Create: `lsprepost_mcp/web/static/refined_blast_workbench.js`
- Modify: `tests/test_web_static.py`
- Create: `tests/test_phase18f_web_contract.py`

**Interfaces:**
- Consumes: `/api/refined-building-blast/capabilities`.
- Produces: `mountRefinedBlastWorkbench(root)`, `unmountRefinedBlastWorkbench()`, route `/refined-building-blast`, and the visible entry button.

- [ ] **Step 1: Write failing entry and legacy-state isolation tests**

```python
def test_index_has_refined_blast_entry():
    assert 'id="openRefinedBlastWorkbench"' in INDEX.read_text(encoding="utf-8")

def test_workbench_uses_only_refined_api_prefix():
    source = WORKBENCH_JS.read_text(encoding="utf-8")
    assert "/api/refined-building-blast/" in source
    assert "/api/editor/" not in source
    assert "cityDraft" not in source
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_phase18f_web_contract.py tests/test_web_static.py`

Expected: missing entry and workbench source.

- [ ] **Step 3: Implement route shell and visual-token reuse**

The workbench layout is left dynamic navigation, central layered preview, right schema/validation panel, and bottom independent action bar. Import existing color variables and button/input classes; define only Phase 18F-specific layout classes.

```javascript
export function mountRefinedBlastWorkbench(root) {
  root.replaceChildren(buildWorkbenchShell());
  history.pushState({ workspace: "refined-blast" }, "", "/refined-building-blast");
}
```

- [ ] **Step 4: Run static tests**

Run: `python -m pytest -q tests/test_phase18f_web_contract.py tests/test_web_static.py tests/test_web_startup.py`

Expected: all pass; legacy main view remains present.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/web/static/index.html lsprepost_mcp/web/static/app.js lsprepost_mcp/web/static/refined_blast_workbench.css lsprepost_mcp/web/static/refined_blast_workbench.js tests/test_web_static.py tests/test_phase18f_web_contract.py
git commit -m "feat: add phase18f workbench entry"
```

### Task 3: Schema-driven forms and single draft state

**Files:**
- Create: `lsprepost_mcp/web/static/refined_blast_state.js`
- Modify: `lsprepost_mcp/web/static/refined_blast_workbench.js`
- Create: `tests/test_phase18f_state_contract.py`

**Interfaces:**
- Consumes: capability, asset, preset, and provider schemas from Task 1.
- Produces: `createRefinedBlastStore()`, `normalizeDraftForSchema(draft, schema)`, `renderSchemaFields(section, schema, draft)`.

- [ ] **Step 1: Write failing dynamic-schema and stale-hidden-value tests**

```python
def test_provider_switch_removes_inapplicable_values(node_runner):
    result = node_runner("phase18f_state_provider_switch.mjs")
    assert result["provider_id"] == "lbe_segment"
    assert "ale_mesh_size_m" not in result["draft"]["load_provider"]

def test_structural_system_changes_visible_sections(node_runner):
    result = node_runner("phase18f_state_system_fields.mjs")
    assert "rebar" in result["rc_visible"]
    assert "steel_connections" in result["steel_visible"]
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_phase18f_state_contract.py`

Expected: missing state module.

- [ ] **Step 3: Implement revisioned single-source state**

```javascript
function updateDraft(mutator) {
  const next = structuredClone(state.draft);
  mutator(next);
  state.draft = normalizeDraftForSchema(next, state.activeSchema);
  state.revision += 1;
  state.validation = null;
  state.preview = null;
}
```

All form edits and viewer edits call `updateDraft`. Autosave sends `expected_revision`; a conflict displays a blocking choice instead of overwriting.

- [ ] **Step 4: Run state and API save tests**

Run: `python -m pytest -q tests/test_phase18f_state_contract.py tests/test_phase18f_api.py`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/web/static/refined_blast_state.js lsprepost_mcp/web/static/refined_blast_workbench.js tests/test_phase18f_state_contract.py
git commit -m "feat: drive phase18f forms from schemas"
```

### Task 4: Layered preview adapter, cache, and stale-response protection

**Files:**
- Create: `lsprepost_mcp/web/refined_blast_preview.py`
- Create: `lsprepost_mcp/web/static/refined_blast_viewer.js`
- Modify: `lsprepost_mcp/web/static/refined_blast_workbench.js`
- Create: `tests/test_phase18f_preview.py`

**Interfaces:**
- Consumes: Phase 18E layered preview payload and neutral viewer primitives.
- Produces: `build_refined_blast_web_preview(project, draft)`, `renderRefinedBlastPreview(payload)`, layer toggles, exact/upper count badges.

- [ ] **Step 1: Write failing layer and race tests**

```python
def test_preview_has_all_required_layers(refined_preview):
    assert set(refined_preview["layers"]) == {
        "cavities", "structure", "reinforcement_connections", "nonstructural",
        "exposed_surfaces", "blast_source", "fluid_domain", "boundaries", "support_ground"
    }

def test_stale_preview_cannot_replace_current_revision(node_runner):
    result = node_runner("phase18f_preview_race.mjs")
    assert result == {"draft_revision": 3, "preview_revision": 3}
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_phase18f_preview.py`

Expected: missing adapter/viewer.

- [ ] **Step 3: Implement revision-keyed preview queue and cache**

Cache key includes building, scenario input, provider, resource, and preview adapter fingerprints. Abort superseded requests where possible; always compare returned revision before applying.

- [ ] **Step 4: Run preview and existing viewer regressions**

Run: `python -m pytest -q tests/test_phase18f_preview.py tests/test_web_preview_cache.py tests/test_web_preview_mesh.py`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/web/refined_blast_preview.py lsprepost_mcp/web/static/refined_blast_viewer.js lsprepost_mcp/web/static/refined_blast_workbench.js tests/test_phase18f_preview.py
git commit -m "feat: preview layered phase18f scenarios"
```

### Task 5: Findings, warning acknowledgement, budgets, and generate gate

**Files:**
- Modify: `lsprepost_mcp/web/static/refined_blast_workbench.js`
- Modify: `lsprepost_mcp/web/static/refined_blast_state.js`
- Create: `tests/test_phase18f_validation_flow.py`

**Interfaces:**
- Consumes: Phase 18E findings and preflight manifests.
- Produces: blocking error view, content-hash warning acknowledgements, budget cards, and `canGenerate(state)`.

- [ ] **Step 1: Write failing gate tests**

```python
def test_error_blocks_generate_and_warning_needs_current_ack(node_runner):
    result = node_runner("phase18f_generate_gate.mjs")
    assert result["with_error"] is False
    assert result["unacknowledged_warning"] is False
    assert result["acknowledged_current_warning"] is True
    assert result["changed_warning_hash"] is False
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_phase18f_validation_flow.py`

Expected: gate function missing.

- [ ] **Step 3: Implement validation panel and provenance-bound acknowledgement**

Show severity, module, field path, message, and suggested correction. The acknowledgement payload contains finding ID, finding content hash, draft revision, and timestamp; a changed finding invalidates it.

- [ ] **Step 4: Run validation flow**

Run: `python -m pytest -q tests/test_phase18f_validation_flow.py tests/test_phase18f_api.py`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/web/static/refined_blast_workbench.js lsprepost_mcp/web/static/refined_blast_state.js tests/test_phase18f_validation_flow.py
git commit -m "feat: close phase18f validation workflow"
```

### Task 6: Generate, open, and solve as independently authorized actions

**Files:**
- Modify: `lsprepost_mcp/web/refined_blast_api.py`
- Modify: `lsprepost_mcp/web/static/refined_blast_workbench.js`
- Create: `tests/test_phase18f_external_actions.py`

**Interfaces:**
- Consumes: current generated package ID, existing neutral LS-PrePost and solver authorization services.
- Produces: explicit per-action authorization payloads and stale-package refusal.

- [ ] **Step 1: Write failing side-effect separation tests**

```python
def test_generate_never_launches_external_programs(monkeypatch, api):
    monkeypatch.setattr("lsprepost_mcp.tool_lsprepost.tool_open_in_lsprepost", forbidden)
    monkeypatch.setattr("lsprepost_mcp.web.solve_api.run_lsdyna_payload", forbidden)
    assert api.generate(valid_payload())["ok"] is True

def test_open_requires_current_generated_revision(api):
    with pytest.raises(ApiError, match="stale"):
        api.open_lsprepost(stale_generated_payload())
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_phase18f_external_actions.py`

Expected: endpoints or stale checks missing.

- [ ] **Step 3: Implement explicit confirmation dialogs and delegated actions**

The browser sends project ID, generated package ID, current package fingerprint, and one-time confirmation. Backend rechecks currentness and existing configured executable status before delegating. No authorization is cached for the next invocation.

- [ ] **Step 4: Run external-action and config regressions**

Run: `python -m pytest -q tests/test_phase18f_external_actions.py tests/test_web_config.py tests/test_lsrun_handoff.py`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/web/refined_blast_api.py lsprepost_mcp/web/static/refined_blast_workbench.js tests/test_phase18f_external_actions.py
git commit -m "feat: authorize phase18f external actions"
```

### Task 7: End-to-end workbench flow and accessibility/static safety

**Files:**
- Create: `tests/test_phase18f_web_e2e_contract.py`
- Modify: `tests/test_web_static.py`

**Interfaces:**
- Consumes: all Phase 18F APIs and browser modules.
- Produces: one complete save → preview → validate → acknowledge → generate workflow per provider.

- [ ] **Step 1: Write the full failing workflow tests**

```python
@pytest.mark.parametrize("provider", [
    "explicit_ale_fsi", "lbe_segment", "imported_pressure_history"
])
def test_workbench_minimal_flow(provider, web_client):
    project = create_refined_project(web_client, provider)
    preview = web_client.post(f"/api/refined-building-blast/projects/{project}/preview", json=minimal_draft(provider))
    assert preview.status == 200
    generated = acknowledge_and_generate(web_client, project, preview.json)
    assert generated["solver_ready"] is False
    assert generated["requires_project_review"] is True
```

Add keyboard-accessible labels, unique IDs, visible disabled states, route refresh, browser back, and legacy-view return tests.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_phase18f_web_e2e_contract.py`

Expected: incomplete workflow failures.

- [ ] **Step 3: Complete only the missing wiring**

Do not introduce a second state store or bypass backend validation. Keep provider-specific fields schema-driven.

- [ ] **Step 4: Run full Phase 18F and existing Web matrix**

Run:

```powershell
$phase18fTests = (Get-ChildItem tests -Filter 'test_phase18f_*.py').FullName
$webTests = (Get-ChildItem tests -Filter 'test_web_*.py').FullName
python -m pytest -q $phase18fTests $webTests tests/test_phase17_web_e2e_contract.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_phase18f_web_e2e_contract.py tests/test_web_static.py lsprepost_mcp/web/static/refined_blast_workbench.js
git commit -m "test: close phase18f workbench workflow"
```

### Task 8: Phase 18F software acceptance report

**Files:**
- Create: `docs/reviews/phase18/PHASE18F_REFINED_BLAST_WORKBENCH_REPORT.zh-CN.md`

**Interfaces:**
- Consumes: final workbench/API test output.
- Produces: UI/API/storage/preview/action evidence and explicit engineering boundary.

- [ ] **Step 1: Run fresh verification**

```powershell
$phase18fTests = (Get-ChildItem tests -Filter 'test_phase18f_*.py').FullName
$webTests = (Get-ChildItem tests -Filter 'test_web_*.py').FullName
python -m pytest -q $phase18fTests
python -m pytest -q $webTests tests/test_phase17_web_e2e_contract.py
python -m compileall -q lsprepost_mcp/web lsprepost_mcp/refined_blast
git diff --check
```

Expected: zero failures and exit code 0.

- [ ] **Step 2: Record exact UI/API cases and action boundaries**

Include provider-specific field evidence, revision race evidence, layer list, preview/final count comparison, acknowledgement invalidation, and proof that generate never launches external programs.

- [ ] **Step 3: Self-review unsupported claims and placeholders**

The report must retain `solver_ready=false`, `requires_project_review=true`, and say no real LS-PrePost/LS-DYNA validation was performed unless separately evidenced.

- [ ] **Step 4: Commit**

```powershell
git add docs/reviews/phase18/PHASE18F_REFINED_BLAST_WORKBENCH_REPORT.zh-CN.md
git commit -m "docs: record phase18f workbench verification"
```
