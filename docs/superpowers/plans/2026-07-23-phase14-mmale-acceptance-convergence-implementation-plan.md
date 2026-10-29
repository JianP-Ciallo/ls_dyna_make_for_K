# Phase 14 MM-ALE Acceptance and Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Phase 14 MM-ALE solver success depend on verified FSI load transfer and provide a fail-closed three-or-more-level mesh-convergence result from real solver outputs.

**Architecture:** Extend the existing FSI parser without changing its legacy Phase 15 contract, then add a focused `phase14_acceptance.py` module for wave-transfer and convergence evaluation. Integrate the wave gate into both initial and refreshed LS-DYNA records, and attach/persist convergence evidence from the existing solve comparison API.

**Tech Stack:** Python 3 standard library, `unittest`, existing JSON project/run records, existing `ProjectLock`, LS-DYNA ASCII `d3hsp`, `dbfsi`, and `nodout` outputs.

## Global Constraints

- Apply only to `result_variant == "ale_blast"` plate scenes; reject `geometry.scene_variant == "open_concrete_tunnel"`.
- A valid slave definition is explicit slave segments greater than zero or slave material/part count greater than zero.
- Require at least two `dbfsi` states, positive finite pressure/force/impulse, at least two `nodout` states, positive finite displacement, and displacement peak time not earlier than pressure peak time.
- Convergence requires 3-8 unique, otherwise identical projects, positive distinct mesh sizes, verified wave transfer, finest-pair relative difference at most `0.10`, and non-increasing final error.
- Do not claim material calibration or experimental validation.
- Do not start a new LS-DYNA run unless the three existing real runs fail the implemented evidence checks.
- Preserve unrelated changes in the dirty shared worktree. Do not create commits unless the user explicitly requests one.

---

### Task 1: Parse Part-Based FSI Slave Definitions

**Files:**
- Modify: `lsprepost_mcp/solver_results.py`
- Test: `tests/test_solver_results.py`

**Interfaces:**
- Consumes: LS-DYNA `d3hsp` text.
- Produces: `parse_fsi_interfaces(text)` fields `slave_material_count`, `has_slave_definition`, and `slave_definition_mode`, while preserving `all_nonempty`.

- [ ] **Step 1: Write the failing parser tests**

```python
def test_parse_fsi_interfaces_accepts_part_based_slave_definition(self) -> None:
    result = parse_fsi_interfaces("""
 FSI Interface ID ...........................         1
 number of slave materials ..................         1
 number of slave segments for coupling ......         0
""")
    self.assertEqual(1, result["slave_material_count"])
    self.assertTrue(result["has_slave_definition"])
    self.assertEqual("part_or_material", result["slave_definition_mode"])
    self.assertFalse(result["all_nonempty"])

def test_parse_fsi_interfaces_rejects_empty_slave_definition(self) -> None:
    result = parse_fsi_interfaces("""
 FSI Interface ID ...........................         1
 number of slave materials ..................         0
 number of slave segments for coupling ......         0
""")
    self.assertFalse(result["has_slave_definition"])
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m unittest tests.test_solver_results.SolverResultTests.test_parse_fsi_interfaces_accepts_part_based_slave_definition tests.test_solver_results.SolverResultTests.test_parse_fsi_interfaces_rejects_empty_slave_definition`

Expected: failures because the new fields do not exist.

- [ ] **Step 3: Implement minimal compatible parsing**

Add a slave-material regex, retain the current per-interface segment parsing, and derive:

```python
slave_material_count = sum(parsed_slave_material_counts)
has_segments = total > 0
has_materials = slave_material_count > 0
slave_definition_mode = (
    "segments_and_part_or_material" if has_segments and has_materials
    else "explicit_segments" if has_segments
    else "part_or_material" if has_materials
    else "missing"
)
```

Do not redefine `all_nonempty`; Phase 15 continues to require explicit nonempty segment sets.

- [ ] **Step 4: Run the focused parser tests**

Run: `python -m unittest tests.test_solver_results`

Expected: all tests pass.

---

### Task 2: Add Phase 14 Wave-Transfer Acceptance

**Files:**
- Create: `lsprepost_mcp/phase14_acceptance.py`
- Create: `tests/test_phase14_acceptance.py`

**Interfaces:**
- Consumes: `evaluate_phase14_wave_transfer(project: Path, run_dir: Path)`.
- Produces: JSON-compatible result with `wave_transfer_verified`, `status`, `checks`, `fsi`, `dbfsi`, `nodout`, and normalized `metrics`.

- [ ] **Step 1: Write fixture helpers and failing acceptance tests**

Create temporary projects containing:

```python
{
    "spec": {
        "project_name": "mmale",
        "model_type": "ale_blast_scene",
        "geometry": {},
        "mesh": {"size_m": 0.0125},
    },
    "metadata": {
        "coupling_count": 1,
        "lagrangian_shell_element_count": 16,
        "components": [{"id": "target_plate", "response_node_ids": [10]}],
    },
}
```

Tests must cover:

```python
self.assertTrue(evaluate_phase14_wave_transfer(project, run_dir)["wave_transfer_verified"])
self.assertFalse(evaluate_phase14_wave_transfer(project, missing_dbfsi)["wave_transfer_verified"])
self.assertFalse(evaluate_phase14_wave_transfer(project, zero_impulse)["wave_transfer_verified"])
self.assertFalse(evaluate_phase14_wave_transfer(project, early_displacement)["wave_transfer_verified"])
self.assertFalse(evaluate_phase14_wave_transfer(tunnel_project, run_dir)["applicable"])
```

- [ ] **Step 2: Run the new module tests and verify RED**

Run: `python -m unittest tests.test_phase14_acceptance`

Expected: import failure because `lsprepost_mcp.phase14_acceptance` does not exist.

- [ ] **Step 3: Implement fail-closed evaluation**

Implement:

```python
def evaluate_phase14_wave_transfer(project: Path, run_dir: Path) -> JSONDict:
    ...
```

Use `parse_d3hsp`, `parse_fsi_interfaces`, `parse_dbfsi`, and `parse_nodout`. Convert every requirement into a structured check:

```python
{"id": "fsi_slave_definition_valid", "ok": bool(...), "actual": {...}}
```

Catch file, JSON, and parser failures and return `wave_transfer_verified=False` with a specific check/error instead of raising. Locate response nodes by finding the `metadata.components` list item with `id == "target_plate"`.

- [ ] **Step 4: Run Phase 14 acceptance and parser tests**

Run: `python -m unittest tests.test_phase14_acceptance tests.test_solver_results`

Expected: all tests pass.

---

### Task 3: Gate Initial and Refreshed Solver Records

**Files:**
- Modify: `lsprepost_mcp/lsdyna_runner.py`
- Modify: `tests/test_lsdyna_runner.py`

**Interfaces:**
- Consumes: `evaluate_phase14_wave_transfer(project, run_dir)`.
- Produces: `record["wave_transfer_acceptance"]`, `wave_transfer_acceptance.json`, and top-level `ok` gated by `wave_transfer_verified`.

- [ ] **Step 1: Write failing runner tests**

Add tests that patch Phase 14 acceptance:

```python
acceptance = {"applicable": True, "wave_transfer_verified": False, "checks": []}
with patch(
    "lsprepost_mcp.lsdyna_runner.evaluate_phase14_wave_transfer",
    return_value=acceptance,
):
    result = execute_lsdyna_run(...)
self.assertFalse(result["ok"])
self.assertEqual(acceptance, result["wave_transfer_acceptance"])
```

Add a refresh regression where stale `latest.json` says `ok=True`, the refreshed acceptance fails, and `latest_lsdyna_run(project)["ok"]` becomes false. Add a Phase 15 regression proving its existing evaluator is still used.

- [ ] **Step 2: Run focused runner tests and verify RED**

Run: `python -m unittest tests.test_lsdyna_runner`

Expected: Phase 14 record remains successful or lacks the acceptance field.

- [ ] **Step 3: Integrate the shared Phase 14 gate**

Import `evaluate_phase14_wave_transfer`. In both `execute_lsdyna_run()` and `_refresh_terminal_record()`:

```python
if result_variant == "ale_blast":
    acceptance = evaluate_phase14_wave_transfer(project, run_dir)
    record["wave_transfer_acceptance"] = acceptance
    _write_json_atomic(run_dir / "wave_transfer_acceptance.json", acceptance)
    wave_transfer_ok = bool(acceptance.get("wave_transfer_verified"))
```

Keep the existing required-file checks as prerequisites, but require `wave_transfer_ok` in the final `record["ok"]`.

- [ ] **Step 4: Run runner and Phase 15 tests**

Run: `python -m unittest tests.test_lsdyna_runner tests.test_phase15_fsi`

Expected: all tests pass.

---

### Task 4: Evaluate Real Mesh Convergence

**Files:**
- Modify: `lsprepost_mcp/phase14_acceptance.py`
- Modify: `tests/test_phase14_acceptance.py`

**Interfaces:**
- Consumes: `evaluate_phase14_mesh_convergence(projects: list[Path], tolerance: float = 0.10)`.
- Produces: sorted project evidence, model fingerprint, pairwise metric differences, and `convergence_verified`.

- [ ] **Step 1: Write failing convergence tests**

Create three otherwise-identical temporary projects with mesh sizes `0.015`, `0.0125`, and `0.010`, each with a completed latest run and valid raw evidence. Assert:

```python
result = evaluate_phase14_mesh_convergence(projects)
self.assertEqual("converged", result["status"])
self.assertTrue(result["convergence_verified"])
self.assertEqual(
    ["coarse", "baseline", "fine"],
    [item["project_name"] for item in result["projects"]],
)
```

Also test mismatched specs, duplicate mesh sizes, one failed wave gate, a final error above `0.10`, and a final error greater than the previous pair.

- [ ] **Step 2: Run convergence tests and verify RED**

Run: `python -m unittest tests.test_phase14_acceptance`

Expected: failure because the convergence function does not exist.

- [ ] **Step 3: Implement comparison and fingerprinting**

Normalize each model spec by deep-copying it and removing only:

```python
normalized.pop("project_name", None)
normalized.get("mesh", {}).pop("size_m", None)
```

Reject tunnel variants, missing terminal runs, non-positive/non-finite metrics, and failed wave acceptance. Sort descending by mesh size and compute:

```python
relative_difference = abs(finer - coarser) / abs(finer)
```

Return `invalid_evidence` for invalid inputs/evidence and `not_converged` for valid evidence that misses numeric rules.

- [ ] **Step 4: Run acceptance tests**

Run: `python -m unittest tests.test_phase14_acceptance`

Expected: all tests pass.

---

### Task 5: Expose and Persist Convergence Through Solve Comparison

**Files:**
- Modify: `lsprepost_mcp/web/solve_api.py`
- Modify: `tests/test_web_api.py`

**Interfaces:**
- Consumes: 2-8 `project_names`.
- Produces: unchanged generic comparison for two projects; `mmale_mesh_convergence` for 3-8 applicable Phase 14 projects.

- [ ] **Step 1: Write failing API tests**

Patch `find_project_dir`, `latest_lsdyna_run`, and
`evaluate_phase14_mesh_convergence`. For three MM-ALE projects assert:

```python
result = compare_lsdyna_payload({"project_names": names})
self.assertTrue(result["mmale_mesh_convergence"]["convergence_verified"])
self.assertTrue((fine_project / "artifacts" / "mmale_mesh_convergence.json").is_file())
```

Assert two-project comparisons do not call the convergence evaluator and do not add the field.

- [ ] **Step 2: Run API tests and verify RED**

Run: `python -m unittest tests.test_web_api`

Expected: no `mmale_mesh_convergence` field or artifact.

- [ ] **Step 3: Integrate locked atomic persistence**

After generic comparison, evaluate convergence only for at least three applicable projects. Add:

```python
with ProjectLock(finest_project.name, namespace="mmale_convergence"):
    artifacts.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(artifacts / "mmale_mesh_convergence.json", report)
```

Use the evaluator’s sorted project evidence to select the finest project. Include generated time, run IDs, and normalized model fingerprint in the report.

- [ ] **Step 4: Run API tests**

Run: `python -m unittest tests.test_web_api`

Expected: all tests pass.

---

### Task 6: Re-evaluate Existing Real Runs and Run Full Regression

**Files:**
- Modify only generated run/artifact JSON under the three named workspace projects.
- No source changes unless a failing regression exposes a defect, in which case add a failing test before fixing it.

**Interfaces:**
- Consumes: existing coarse, baseline, and fine project outputs.
- Produces: refreshed per-run acceptance evidence and finest-project convergence artifact.

- [ ] **Step 1: Run the three-project evaluator without launching LS-DYNA**

Run a short Python command importing `evaluate_phase14_mesh_convergence` over:

```text
phase14_mmale_blast_plate_acceptance_v2_mesh_coarse
phase14_mmale_blast_plate_acceptance_v2_mesh_baseline
phase14_mmale_blast_plate_acceptance_v2_mesh_fine
```

Expected: each run reports `wave_transfer_verified=true`; convergence reports `convergence_verified=true`.

- [ ] **Step 2: Verify exact baseline metrics from raw files**

Confirm the evaluator returns approximately:

```text
fine-pair pressure difference:     0.0996314819689392
fine-pair impulse difference:      0.011073983414944883
fine-pair displacement difference: 0.04942625232574372
```

If not, inspect the raw parser result and tests before considering a refined run.

- [ ] **Step 3: Run focused and full regression**

Run:

```text
python -m unittest tests.test_solver_results tests.test_phase14_acceptance tests.test_lsdyna_runner tests.test_web_api tests.test_phase15_fsi
python -m unittest discover -s tests
python -m compileall -q .\lsprepost_mcp
git diff --check
```

Expected: all tests pass, compile exits zero, and diff check emits no errors.

- [ ] **Step 4: Decide whether a refined solve is necessary**

Do not launch LS-DYNA when the existing three levels pass. Only generate and solve the `0.009375 m` refined project when the real evaluator returns `not_converged`; record that decision in the final report.
