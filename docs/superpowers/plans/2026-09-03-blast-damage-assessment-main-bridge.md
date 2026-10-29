# Blast Damage Assessment Main-Project Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After standalone acceptance, connect the main modeling project to `blast_damage_assessment` through a thin, recoverable bridge that selects a trusted completed run, constructs the public v1 request, registers immutable result artifacts, and exposes versioned main-project endpoints without copying any assessment algorithm.

**Architecture:** `lsprepost_mcp` remains the authority for projects, generated-package identity, solver-run identity, locks, and artifact registration. The bridge lazily imports the independently installed package, calls only `capabilities()` and `assess()`, and stores only public result-envelope fields and artifact hashes. Refined-building generated packages retain `manifest.json` and a native assessment-semantics sidecar so later optimization can add optional semantics without changing the assessment core. Existing `/api/project/city-impact` and `/api/project/city-impact-report` behavior is preserved; migration of the old panel is outside this bridge.

**Tech Stack:** Existing Python 3 standard-library application, existing `unittest` suite and local HTTP server, PowerShell setup/packaging scripts, and the accepted `blast_damage_assessment` Python API.

**Spec:** `docs/superpowers/specs/2026-09-01-blast-damage-assessment-system-design.md`

**Prerequisite:** Every stop/go check in `docs/superpowers/plans/2026-09-03-blast-damage-assessment-core.md` has passed and its acceptance summary has been reviewed.

## Execution record (2026-09-08)

Tasks 1–5 are implemented and accepted for local integration. Evidence comprises the complete repository run (including all three heavy provider workflows), frozen-code reruns resolving its five environment/stale-fingerprint failure records, final bridge compatibility tests (60 + 93 tests in disjoint file groups), independent-package tests, three real-reference fingerprint comparisons, and the recovered real-HTTP flow. The original unittest-only commands below were superseded by the pytest commands in the acceptance record. The complete run itself was not all-green; root causes, corrective fixture preparation, successful reruns, and unexecuted opt-in/symlink cases are recorded in `docs/reviews/blast-damage-assessment/MAIN_PROJECT_BRIDGE_ACCEPTANCE.zh-CN.md`. Merge and post-merge evidence are tracked there separately.

## Global Constraints

- Do not begin this plan if any commercial, residential, or subway standalone result is `formal`, exceeds the resource limit, mutates source evidence, or lacks a closed evidence chain.
- The bridge may construct requests and register results; it must not import adapter, gate, rule, building, ground, evidence, or reporting internals.
- Import `blast_damage_assessment.api` lazily. The base modeling application must still start and model normally when the optional package is not installed.
- Never accept an arbitrary filesystem result path from a browser request. Resolve result directories from a server-owned project/run record.
- A solver result is eligible only after a terminal run record exists and its model/run identity matches the generated project snapshot. The assessment core performs the final source rehash and quality gate.
- Keep old city-impact endpoints and schemas unchanged during this plan. New assessment endpoints use new route names and v1 schemas.
- All assessment outputs live in a new directory below the owning project/action snapshot. Never overwrite a previous assessment directory or its index record.
- Do not expose local absolute paths in HTTP responses or distribution documentation. Return project-relative artifact paths and hashes.
- No DeepSeek dependency or interpretation endpoint belongs in this plan.
- Use the existing project/store locks for index mutation. Preserve unrelated work in the dirty worktree and commit only files listed by each task.

---

## Bridge Contracts

```python
# lsprepost_mcp/damage_assessment_bridge.py
def assessment_capabilities() -> JSONDict: ...

def assess_completed_run(
    *,
    project_id: str,
    case_id: str,
    project_dir: Path,
    run_dir: Path,
    semantic_manifest: Path,
    building_rule_pack: str = "building_research_reference@1",
    ground_rule_pack: str = "ground_research_reference@1",
) -> JSONDict: ...

def latest_registered_assessment(project_dir: Path) -> JSONDict: ...
```

The registry schema is `lsprepost_mcp.damage_assessment_registry@1` and contains append-only records with assessment ID, request/result schema versions, package/adapter/rule versions, gate, severity, assessment fingerprint, source-evidence digest, project-relative output directory, artifact relative paths and hashes, and registration time. It does not copy component metrics or rule logic from `assessment_snapshot.json`.

---

### Task 1: Add Optional Package Installation, Doctor, and Distribution Boundaries

**Files:**
- Create: `scripts/setup_damage_assessment.ps1`
- Modify: `scripts/doctor.ps1`
- Modify: `scripts/pack.ps1`
- Modify: `scripts/run_test_matrix.ps1`
- Modify: `tests/test_packaging_and_integration_boundaries.py`
- Modify: `README.zh-CN.md`

**Interfaces:** `setup_damage_assessment.ps1 -PythonExe <path>` installs the local nested distribution into the selected interpreter; base doctor reports `damage_assessment_optional` as `ok` or `warning`.

- [x] **Step 1: Write failing packaging-boundary tests**

```python
def test_distribution_contains_standalone_assessment_source(self):
    with zipfile.ZipFile(output) as archive:
        names = {name.replace("\\", "/") for name in archive.namelist()}
    self.assertIn("packages/blast_damage_assessment/pyproject.toml", names)
    self.assertIn("packages/blast_damage_assessment/src/blast_damage_assessment/api.py", names)
    self.assertIn("scripts/setup_damage_assessment.ps1", names)
```

- [x] **Step 2: Verify RED**

```powershell
python -m unittest tests.test_packaging_and_integration_boundaries -v
```

- [x] **Step 3: Implement explicit optional installation**

The setup script resolves the passed interpreter, runs `-m pip install` against `packages/blast_damage_assessment`, then calls `-c "from blast_damage_assessment.api import capabilities; ..."`. It does not download or configure DeepSeek. It returns nonzero if the accepted LASSO version or package capability is missing.

- [x] **Step 4: Include `packages` safely in the distribution**

Add `packages` to `$includedDirs`; keep virtual environments, caches, build outputs, wheels, real d3plots, `var/tmp`, and acceptance outputs excluded. Add package source compile/test commands to the assessment lane of `run_test_matrix.ps1`; do not force optional LASSO tests into the base stdlib-only lane.

- [x] **Step 5: Document the optional boundary**

The root README explains that modeling remains usable without the package, assessment capability requires running the setup script once for the chosen Python environment, and current results are research/provisional until project calibration is complete.

- [x] **Step 6: Run and commit**

```powershell
python -m unittest tests.test_packaging_and_integration_boundaries -v
powershell -ExecutionPolicy Bypass -File scripts/doctor.ps1
git add scripts/setup_damage_assessment.ps1 scripts/doctor.ps1 scripts/pack.ps1 scripts/run_test_matrix.ps1 tests/test_packaging_and_integration_boundaries.py README.zh-CN.md
git commit -m "build: distribute optional damage assessment"
```

---

### Task 2: Preserve Assessment Semantics and Register Trusted Solver Snapshots

**Files:**
- Create: `lsprepost_mcp/damage_assessment_semantics.py`
- Create: `lsprepost_mcp/assessment_result_source.py`
- Modify: `lsprepost_mcp/web/refined_blast_api.py`
- Modify: `tests/test_phase18f_external_actions.py`
- Create: `tests/test_damage_assessment_semantics.py`
- Create: `tests/test_assessment_result_source.py`

**Interfaces:** `build_assessment_semantics(detailed, compilation) -> JSONDict`, `register_assessment_result_source(...)`, and `resolve_assessment_result_source(project_dir) -> JSONDict`.

- [x] **Step 1: Write failing generated-package retention tests**

Assert that solver-complete refined packages contain `model.k`, `manifest.json`, and `assessment_semantics.json`; their hashes are in the immutable package manifest; action snapshots preserve all three; and changing any of them makes snapshot verification fail before launch.

- [x] **Step 2: Write the native semantics contract tests**

`assessment_semantics.json` has schema `blast_damage.model_semantics@1`, unit system, coordinate/vertical axes, blast center, building object, component groups, Part-role bindings, material capabilities, ground Part/surface identity, classification source, and generator fingerprints. Component importance is explicit only when the source asset declares it. Generator table inference is recorded as `inferred_generator_mapping@1`, so the assessment gate remains provisional.

- [x] **Step 3: Verify RED**

```powershell
python -m unittest tests.test_damage_assessment_semantics tests.test_phase18f_external_actions -v
```

- [x] **Step 4: Include semantic files without weakening closed manifests**

Do not add fields to the closed `phase18.solver_blast.deck_manifest@4`. Instead, add both byte files to `RefinedBlastPackage.files` and include their SHA-256 values in the existing web package's file evidence. The standalone core continues to support old `@1` through `@4` deck manifests when no sidecar exists.

- [x] **Step 5: Persist a server-owned result-source record after LS-DYNA returns**

`execute_lsdyna_run` is synchronous. When the returned record reaches a terminal status, write `damage_assessment_source.json` below the owning refined project using the store's atomic writer and project lock. Store only validated relative snapshot path, run ID, generated revision, scenario/package/artifact fingerprints, model/manifest/semantics hashes, run status, and registration time. Add these non-sensitive identity fields to the action response; do not return the absolute snapshot path.

- [x] **Step 6: Implement source resolution and tamper tests**

Resolve the record back under the owning store/project root, reject traversal/reparse escape, require `run_dir.parent == snapshot/solver_runs`, verify `latest.json` and `run.json` identity, require a terminal status, compare the run input/model hash with the snapshot model, and rehash the semantic manifest. Do not require `nodout` or `elout`. The core will perform full d3plot/text evidence validation.

- [x] **Step 7: Run and commit**

```powershell
python -m unittest tests.test_damage_assessment_semantics tests.test_assessment_result_source tests.test_phase18f_external_actions -v
python -m compileall -q lsprepost_mcp/damage_assessment_semantics.py lsprepost_mcp/assessment_result_source.py lsprepost_mcp/web/refined_blast_api.py
git add lsprepost_mcp/damage_assessment_semantics.py lsprepost_mcp/assessment_result_source.py lsprepost_mcp/web/refined_blast_api.py tests/test_damage_assessment_semantics.py tests/test_assessment_result_source.py tests/test_phase18f_external_actions.py
git commit -m "feat: retain assessment-ready solver sources"
```

---

### Task 3: Implement the Thin Python Bridge and Immutable Registry

**Files:**
- Create: `lsprepost_mcp/damage_assessment_bridge.py`
- Create: `tests/test_damage_assessment_bridge.py`

**Interfaces:** `assessment_capabilities`, `assess_completed_run`, and `latest_registered_assessment`.

- [x] **Step 1: Write optional-capability and import-isolation tests**

Mock `importlib.import_module` to simulate missing package, wrong request/result major version, missing required rule pack, and an accepted capability. Missing package returns `{available: false, reason: ...}` and never prevents importing `lsprepost_mcp.server` or starting the Web app.

- [x] **Step 2: Write request-construction tests**

Assert exact public fields, resolved read-only result directory, semantic manifest path/hash/schema, research rule IDs, unique absent output directory below `artifacts/damage_assessments`, and default chunk size `4`. Reject nonterminal or mismatched sources before calling the package.

- [x] **Step 3: Verify RED**

```powershell
python -m unittest tests.test_damage_assessment_bridge -v
```

- [x] **Step 4: Implement lazy public-API loading**

```python
def _assessment_api() -> tuple[Callable[..., object], Callable[..., object]]:
    module = importlib.import_module("blast_damage_assessment.api")
    return module.capabilities, module.assess
```

No other `blast_damage_assessment` module is imported. Validate the capability response before constructing a request. Convert only the public result dataclass through its documented `to_dict()` method; do not inspect private fields.

- [x] **Step 5: Register the completed result atomically**

After `assess()` returns, read and hash `assessment_result.json`, verify every artifact reference stays below the new output directory and matches the returned SHA-256, then append one record under a `ProjectLock`. Write a new registry file through temporary-file replacement. If registration fails, leave the immutable assessment directory intact and return a recoverable `completed_unregistered` state; a retry may register the same assessment ID once, but a conflicting fingerprint is rejected.

- [x] **Step 6: Add concurrency, idempotency, and failure tests**

Two simultaneous attempts cannot write the same output directory or lose a registry record. Re-registering the same assessment/fingerprint is idempotent. Source mutation, package exception, malformed result, artifact hash mismatch, or index write failure never overwrites an older registry.

- [x] **Step 7: Run and commit**

```powershell
python -m unittest tests.test_damage_assessment_bridge -v
python -m compileall -q lsprepost_mcp/damage_assessment_bridge.py
git add lsprepost_mcp/damage_assessment_bridge.py tests/test_damage_assessment_bridge.py
git commit -m "feat: bridge completed runs to damage assessment"
```

---

### Task 4: Expose Versioned Main-Project Endpoints Without Replacing Legacy City Impact

**Files:**
- Create: `lsprepost_mcp/web/damage_assessment_api.py`
- Modify: `lsprepost_mcp/web/app.py`
- Modify: `lsprepost_mcp/web/refined_blast_api.py`
- Create: `tests/test_damage_assessment_web_api.py`
- Modify: `tests/test_phase18f_api.py`
- Modify: `tests/test_city_impact.py`

**Interfaces:**
- GET `/api/damage-assessment/capabilities`
- POST `/api/refined-building-blast/projects/{project_id}/assess-latest-run`
- GET `/api/refined-building-blast/projects/{project_id}/assessments/latest`
- GET `/api/refined-building-blast/projects/{project_id}/assessments/{assessment_id}/artifacts/{artifact_name}`
- Existing GET `/api/project/city-impact` remains unchanged.
- Existing POST `/api/project/city-impact-report` remains unchanged.

- [x] **Step 1: Write failing capability and availability tests**

The capability endpoint returns HTTP 200 with `available=false` when the optional package is absent. The assessment action returns 409 `assessment_unavailable`; unrelated modeling endpoints continue to work.

- [x] **Step 2: Write trusted-route tests**

The POST body is closed and contains only `schema_version="lsprepost_mcp.damage_assessment_request@1"` plus the current generated identity (`scenario_id`, `generated_revision`, `artifact_fingerprint`, `package_fingerprint`). It contains no path, executable, threshold, Python module, or arbitrary rule JSON. The server verifies this identity against the current project and its persisted result-source record before invoking the bridge.

- [x] **Step 3: Verify RED**

```powershell
python -m unittest tests.test_damage_assessment_web_api tests.test_phase18f_api -v
```

- [x] **Step 4: Implement new routes and safe responses**

POST returns assessment ID, gate, severity, fingerprint, warnings/blockers/review-item summaries, and project-relative report/artifact paths. GET latest returns the registered envelope only. The dedicated artifact route accepts only the eight registered artifact names, resolves the project and assessment through the immutable registry, verifies the current file hash against the registry, and serves fixed content types for JSON, HTML, and CSV. It accepts no filesystem path and never falls back to the existing `/api/artifact` route.

- [x] **Step 5: Lock in legacy compatibility**

Run the existing city-impact tests unchanged and add assertions that their route names, operation names, schema versions, report filenames, and `risk.level` behavior are identical. The new assessment is not used as a silent fallback for old endpoints.

- [x] **Step 6: Run and commit**

```powershell
python -m unittest tests.test_damage_assessment_web_api tests.test_phase18f_api tests.test_city_impact -v
python -m compileall -q lsprepost_mcp/web
git add lsprepost_mcp/web/damage_assessment_api.py lsprepost_mcp/web/app.py lsprepost_mcp/web/refined_blast_api.py tests/test_damage_assessment_web_api.py tests/test_phase18f_api.py tests/test_city_impact.py
git commit -m "feat: expose damage assessment bridge endpoints"
```

---

### Task 5: Execute Integration Acceptance and Freeze the Compatibility Boundary

**Files:**
- Create: `docs/reviews/blast-damage-assessment/MAIN_PROJECT_BRIDGE_ACCEPTANCE.zh-CN.md`
- Modify: `docs/PROJECT_STRUCTURE.zh-CN.md`
- Modify: `README.zh-CN.md`

- [x] **Step 1: Install the already accepted local package into the integration interpreter**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_damage_assessment.ps1 -PythonExe python
```

Record exact Python, NumPy, LASSO, and assessment-package versions. Do not rebuild rule content during bridge acceptance.

- [x] **Step 2: Run focused bridge and compatibility suites**

```powershell
python -m unittest tests.test_damage_assessment_semantics tests.test_assessment_result_source tests.test_damage_assessment_bridge tests.test_damage_assessment_web_api tests.test_phase18f_external_actions tests.test_phase18f_api tests.test_city_impact -v
```

- [x] **Step 3: Run the complete repository and package suites**

```powershell
python -m unittest discover -s tests
python -m unittest discover -s packages/blast_damage_assessment/tests
python -m compileall -q lsprepost_mcp packages/blast_damage_assessment/src
```

- [x] **Step 4: Run one recovered refined-workbench result end to end**

Use a server-owned completed action snapshot. Query capabilities, invoke `assess-latest-run`, read latest, and open the returned HTML through the dedicated registered-assessment artifact route. Verify the source record cannot be redirected, output is under the owning project, source hashes remain unchanged, gate is provisional for current materials, and registry/artifact hashes match.

- [x] **Step 5: Re-run the three standalone reference cases through the bridge API**

For commercial, residential, and subway, compare bridge-created assessment fingerprints with the accepted standalone fingerprints. Absolute output paths and envelope timings may differ; deterministic snapshot, rules, gates, metrics, severities, and evidence must not.

- [x] **Step 6: Exercise failure recovery**

Test optional package absent, stale generated revision, missing result-source record, nonterminal run, changed manifest, changed d3plot, core returning blocked, core operational failure, and registry write failure. Confirm old city assessment and all modeling/generation flows remain available.

- [x] **Step 7: Document the final boundary**

The acceptance record includes exact commands/results, accepted package fingerprint, route schemas, current provisional limitation, immutable output paths, recovery behavior, and explicit confirmation that DeepSeek is not connected. The project structure document assigns algorithm ownership to the standalone package and project/run/registry ownership to `lsprepost_mcp`.

- [x] **Step 8: Inspect diff and commit documentation**

```powershell
git diff --check
git status --short
git add docs/reviews/blast-damage-assessment/MAIN_PROJECT_BRIDGE_ACCEPTANCE.zh-CN.md docs/PROJECT_STRUCTURE.zh-CN.md README.zh-CN.md
git commit -m "docs: accept damage assessment bridge"
```

---

## Bridge Acceptance Stop/Go Decision

The bridge is accepted only when the optional dependency is nonblocking, trusted result selection is path-safe, three standalone fingerprints are preserved, the registry is immutable/idempotent, the new endpoints expose no absolute paths, and the full existing repository suite—including unchanged city-impact behavior—passes. Frontend redesign and DeepSeek interpretation remain separate future work.
