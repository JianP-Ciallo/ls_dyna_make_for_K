# Phase 18 Compatibility and Project Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove Phase 18E–F compatibility with Phase 18A–D, then prove the complete Phase 18 range does not change legacy project, Web, city, blast, import/export, or external-action behavior.

**Architecture:** Add dedicated black-box compatibility tests rather than coupling production packages. First lock public Phase 18 resources and fingerprints, then scan import boundaries and run legacy behavior matrices, followed by an independent final review and one bounded test-first fix wave if required.

**Tech Stack:** Python 3.13, pytest/unittest, AST dependency scanning, SHA-256 fingerprint fixtures, existing Web/project/keyword test suites, compileall, Git diff checks.

## Global Constraints

- Compatibility tests consume public APIs and generated manifests; they must not import private template helpers.
- Phase 18E/F must not change five Phase 18C literal fingerprints or three Phase 18D building artifact fingerprints when only a scenario changes.
- Existing city, old blast, old editor, project import/export, preview, and solve authorization defaults remain unchanged.
- No test may launch LS-PrePost or LS-DYNA without explicit authorization.
- Findings are classified Critical, Important, or Minor; software acceptance requires Critical 0 and Important 0.
- Test evidence is software evidence only and does not set `solver_ready=true`.

---

### Task 1: Phase 18A–D public-contract compatibility matrix

**Files:**
- Create: `tests/test_phase18ef_phase18abcd_compatibility.py`

**Interfaces:**
- Consumes: public resource/model/material APIs, Phase 18C compiler, Phase 18D asset compiler, Phase 18E service.
- Produces: one literal compatibility matrix covering aliases, resource closure, fingerprints, building immutability, and scenario-only invalidation.

- [ ] **Step 1: Write literal fingerprint and resource tests**

```python
PHASE18C_FINGERPRINTS = {
    "rc_frame": "48289fc948abd6cd9d6b1df627405a5cee8f91ad35d537321ed22b7a17baa03b",
    "rc_frame_shear_wall": "4f4fd26f4fac7ca607555805f89505b07c79b9752cd0589227067c53bcef6723",
    "steel_frame": "07d1119cdc7bf23848ede68acd644bedaac9594044f682a8fb0c981e5151f150",
    "steel_concrete_hybrid": "8adc42e4beeb973a1515f03e1734a8c782e978d76c322ba4c1b09b90ea3978cf",
    "rc_box": "fa4be2c35728d340da3ea6b97cf259678c018f6cac2f651c76f4ae1ecb6e8262",
}

def test_scenario_change_does_not_change_building_fingerprint(detailed_asset):
    before = detailed_asset.artifacts[0].fingerprint
    compile_refined_scenario(detailed_asset, source_x=5.0)
    compile_refined_scenario(detailed_asset, source_x=6.0)
    assert detailed_asset.artifacts[0].fingerprint == before
```

Use the full literal hashes from the Phase 18D report, not abbreviated strings in executable assertions. Validate reviewed materials, fixed-K aliases/canonical packages, component packages, and descriptor role closure.

- [ ] **Step 2: Run RED before compatibility adaptations**

Run: `python -m pytest -q tests/test_phase18ef_phase18abcd_compatibility.py`

Expected: Phase 18E service tests fail until all public adaptations are present; existing literal fingerprints already pass.

- [ ] **Step 3: Apply only public-boundary fixes proven by RED**

If a private Phase 18C/D helper is required, add a narrow public adapter in its owning package with no default-behavior change. Do not copy private logic into `refined_blast`.

- [ ] **Step 4: Run Phase 18A–F focused matrix**

Run:

```powershell
$phase18Tests = (Get-ChildItem tests -File | Where-Object { $_.Name -match '^test_phase18(a1|b|c|d|e|f|ef).*\.py$' }).FullName
python -m pytest -q $phase18Tests
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_phase18ef_phase18abcd_compatibility.py lsprepost_mcp/refined_building
git commit -m "test: prove phase18ef compatibility with phase18abcd"
```

Only add a `refined_building` path if a RED-proven public adapter was actually required.

### Task 2: Bidirectional dependency and namespace isolation

**Files:**
- Create: `tests/test_phase18ef_dependency_boundaries.py`

**Interfaces:**
- Consumes: repository Python and JavaScript import/reference graph.
- Produces: forbidden-import, route-prefix, project-type, storage-root, and ID-namespace assertions.

- [ ] **Step 1: Write failing AST and static-source scans**

```python
def test_refined_blast_does_not_import_legacy_domains():
    imported = package_imports(ROOT / "lsprepost_mcp" / "refined_blast")
    assert imported.isdisjoint({
        "lsprepost_mcp.city_street_blast",
        "lsprepost_mcp.blast_cases",
        "lsprepost_mcp.dyna_assembly",
        "lsprepost_mcp.web.draft_preview",
    })

def test_legacy_domains_do_not_import_refined_blast():
    for path in LEGACY_DOMAIN_FILES:
        assert "refined_blast" not in path.read_text(encoding="utf-8")
```

Also assert `/api/refined-building-blast/`, `/refined-building-blast`, `workspace/refined_building_blast/`, project IDs, artifact IDs, and result IDs remain separate.

- [ ] **Step 2: Verify boundary tests**

Run: `python -m pytest -q tests/test_phase18ef_dependency_boundaries.py`

Expected: pass if implementation followed the design; otherwise fail at the exact forbidden edge.

- [ ] **Step 3: Remove any forbidden edge at its source**

Extract only truly neutral functionality into an existing neutral module or a new small neutral module. Never solve the failure by weakening the forbidden set.

- [ ] **Step 4: Re-run boundaries and import smoke tests**

Run: `python -m pytest -q tests/test_phase18ef_dependency_boundaries.py tests/test_phase18c_dependency_boundaries.py tests/test_web_startup.py`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_phase18ef_dependency_boundaries.py
git commit -m "test: lock phase18 refined domain boundaries"
```

### Task 3: Legacy project and old blast behavior matrix

**Files:**
- Create: `tests/test_phase18_project_legacy_compatibility.py`

**Interfaces:**
- Consumes: existing public tools/APIs and golden summaries.
- Produces: before/after behavior assertions for old project types, old blast cases, city generation, old editor, import/export, and solve authorization.

- [ ] **Step 1: Write legacy black-box assertions**

```python
def test_legacy_routes_and_defaults_remain_unchanged(web_client):
    assert web_client.get("/api/scenes").json == EXPECTED_SCENE_CATALOG
    assert web_client.get("/api/blast-cases").json == EXPECTED_BLAST_CATALOG

def test_old_generate_does_not_see_refined_draft(monkeypatch):
    payload = legacy_city_payload()
    result = tool_generate_scene_from_prompt(payload)
    assert "refined_building_blast" not in json.dumps(result)
```

Use current committed expected values or precise semantic subsets where paths/timestamps are intentionally variable.

- [ ] **Step 2: Run the legacy matrix**

Run:

```powershell
$phase17Tests = (Get-ChildItem tests -Filter 'test_phase17_*.py').FullName
$webTests = (Get-ChildItem tests -Filter 'test_web_*.py').FullName
python -m pytest -q tests/test_phase18_project_legacy_compatibility.py tests/test_blast_case.py tests/test_blast_enhanced.py tests/test_city_street_blast.py $phase17Tests $webTests
```

Expected: all pass.

- [ ] **Step 3: Fix only observed default-behavior changes**

Route new project types before legacy parsing only within the dedicated prefix. Preserve old API response shapes and defaults. Add regression coverage for every fix.

- [ ] **Step 4: Re-run affected legacy tests**

Run the exact failing selector plus the complete command from Step 2.

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_phase18_project_legacy_compatibility.py
git commit -m "test: preserve legacy project behavior through phase18"
```

### Task 4: Full provider-by-building acceptance matrix

**Files:**
- Create: `tests/test_phase18_acceptance_matrix.py`

**Interfaces:**
- Consumes: commercial, residential, and subway Phase 18D assets; all three providers; all three scenario kinds where supported.
- Produces: deterministic package, preview, finding, budget, and invalidation records.

- [ ] **Step 1: Define explicit supported combinations**

```python
SUPPORTED = (
    ("commercial_supermarket_detailed_building", "explicit_ale_fsi", "external"),
    ("commercial_supermarket_detailed_building", "lbe_segment", "external"),
    ("commercial_supermarket_detailed_building", "imported_pressure_history", "internal"),
    ("residential_community_detailed_building", "explicit_ale_fsi", "external"),
    ("residential_community_detailed_building", "lbe_segment", "external"),
    ("residential_community_detailed_building", "imported_pressure_history", "internal"),
    ("subway_entrance_detailed_building", "explicit_ale_fsi", "semi_enclosed"),
    ("subway_entrance_detailed_building", "lbe_segment", "external"),
    ("subway_entrance_detailed_building", "imported_pressure_history", "semi_enclosed"),
)
```

Add explicit rejection tests for unsupported combinations rather than silent fallback.

- [ ] **Step 2: Run the matrix twice**

Run: `python -m pytest -q tests/test_phase18_acceptance_matrix.py`

Expected: all supported cases pass and produce the same fingerprints/counts across two independent runs.

- [ ] **Step 3: Compare preview, estimate, and final manifests**

For exact values require equality. For proved upper bounds require `actual <= estimate`. Require no blocking findings and preserve all engineering-review flags.

- [ ] **Step 4: Record a machine-readable evidence fixture**

Create the fixture only from observed output and lock it in the test. Do not hand-edit fingerprints.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_phase18_acceptance_matrix.py tests/fixtures/phase18_acceptance_matrix.json
git commit -m "test: verify the complete phase18 matrix"
```

### Task 5: Whole-project verification and independent review

**Files:**
- Create: `docs/reviews/phase18/PHASE18_OVERALL_COMPATIBILITY_REPORT.zh-CN.md`
- Modify: `docs/ROADMAP.zh-CN.md` only after isolating the exact Phase 18 status hunk from unrelated user edits.

**Interfaces:**
- Consumes: complete Phase 18 commit range and repository test suites.
- Produces: final software acceptance verdict, exact test evidence, review findings, and engineering boundary.

- [ ] **Step 1: Run fresh Phase 18 and full related project tests**

```powershell
$phase18Tests = (Get-ChildItem tests -Filter 'test_phase18*.py').FullName
$phase17Tests = (Get-ChildItem tests -Filter 'test_phase17_*.py').FullName
$webTests = (Get-ChildItem tests -Filter 'test_web_*.py').FullName
$projectTests = (Get-ChildItem tests -Filter 'test_project_*.py').FullName
python -m pytest -q $phase18Tests
python -m pytest -q tests/test_blast_case.py tests/test_blast_enhanced.py tests/test_city_street_blast.py $phase17Tests $webTests $projectTests
python -m compileall -q lsprepost_mcp
git diff --check
```

Expected: zero failures and exit code 0. Split long commands into named files only if the host timeout requires it; record every command and result.

- [ ] **Step 2: Perform an independent scoped code review**

Review the full Phase 18E–F range for specification compliance, closed schemas, determinism, allocation-before-budget, path safety, ID closure, provider truth sources, UI state races, external-action authorization, dependency isolation, and unsupported engineering claims.

Classify findings as Critical, Important, or Minor. Software acceptance requires Critical 0 and Important 0.

- [ ] **Step 3: If findings exist, run one bounded test-first fix wave**

For each Critical/Important finding: reproduce RED with a focused public test, implement the smallest root-cause fix, rerun the affected aggregate, then rerun the full matrices from Step 1. Do not broaden scope after review begins.

- [ ] **Step 4: Write report and update roadmap status**

Report exact commit range, files, line counts, providers, scenarios, asset combinations, fingerprints, counts, tests, review verdict, unresolved engineering evidence, and flags. Mark Phase 18E/F software-complete only if all gates pass.

If `docs/ROADMAP.zh-CN.md` contains unrelated dirty rewrites that cannot be staged independently, update the working file but commit only the standalone report and explicitly record the staging boundary.

- [ ] **Step 5: Verify documentation and commit scoped report**

```powershell
git diff --check
git add docs/reviews/phase18/PHASE18_OVERALL_COMPATIBILITY_REPORT.zh-CN.md
git diff --cached --check
git commit -m "docs: record complete phase18 software acceptance"
```

### Task 6: Final branch handoff

**Files:**
- No production files.

**Interfaces:**
- Consumes: verified final branch.
- Produces: user-selected merge, pull request, or preserved branch state.

- [ ] **Step 1: Run verification-before-completion on the final tree**

Re-run the exact final test commands claimed in the handoff and read complete outputs.

- [ ] **Step 2: Detect branch/worktree state**

```powershell
git rev-parse --git-dir
git rev-parse --git-common-dir
git branch --show-current
git status --short
```

- [ ] **Step 3: Present integration options**

Offer local merge to the confirmed base branch, push and create a PR, or keep the branch as-is. Do not merge, push, clean, reset, or discard without the user's explicit choice.
