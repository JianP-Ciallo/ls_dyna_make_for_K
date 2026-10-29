# Phase17 City Object Response Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a new Phase17 city blast project whose single-layer shell buildings receive object-specific ALE/FSI loading and expose qualified structural pressure, stress, and displacement evidence after shock arrival.

**Architecture:** The city generator assigns every required response object a disjoint segment set, coupling card, shell-history set, and node-history set. A dedicated object-response evaluator joins DBFSI, ELOUT, NODOUT, MATSUM, model metadata, and d3plot evidence into fail-closed per-object acceptance. LS-PrePost creates one provenance-bound pressure image per building, while traffic lights are rebuilt as connected shell assemblies.

**Tech Stack:** Python 3 standard library, LS-DYNA keyword decks, LS-PrePost cfile automation, `unittest`, PowerShell integration scripts.

## Global Constraints

- Do not modify or overwrite existing generated projects or solver run directories.
- Generate the corrected project as `web_phase17_city_street_blast_response_v2`.
- Buildings remain single-layer structural shell models in this phase.
- “Pressure entering a building” means finite structural hydrostatic-pressure and stress response in the shell after qualified FSI arrival.
- Do not claim propagation through wall thickness or into an interior ALE volume.
- Required response objects are commercial building, residential building, subway entrance, and all traffic lights.
- Every required response object must have a stable, nonempty, disjoint FSI segment set.
- Every required response object must have shell and node history output sets.
- The legacy `1e-6 J` MATSUM test is diagnostic only and cannot pass acceptance.
- A required object cannot respond before its own FSI pressure arrival, except for one database-output interval of tolerance.
- The corrected solve must retain at least 20 ms of output after the farthest qualified arrival and default to at least 50 ms.
- Existing uncalibrated elastic concrete remains suitable only for qualitative workflow validation.
- Quantitative engineering acceptance remains blocked without calibrated material evidence and mesh convergence.
- Traffic-light pole, arm, and head must form one connected load-bearing topology with no floating shell island.

---

### Task 1: Object Response Keyword Contract

**Files:**
- Modify: `tests/test_city_street_blast.py`
- Modify: `lsprepost_mcp/city_street_blast.py`

**Interfaces:**
- Consumes: existing `build_city_street_blast_keyword(spec, project_name)` generator contract.
- Produces: `model["city_blast"]["response_objects"]`, where each item contains `object_id`, `part_id`, `fsi_segment_set_id`, `fsi_surface_id`, `shell_history_set_id`, `node_history_set_id`, and `expected_distance_m`.

- [ ] **Step 1: Write failing generator contract tests**

Add tests that generate the default city model and assert:

```python
response_objects = model["city_blast"]["response_objects"]
self.assertEqual(
    {item["object_id"] for item in response_objects},
    {"commercial_supermarket", "residential_community", "subway_entrance",
     "traffic_lights_1", "traffic_lights_2", "traffic_lights_3", "traffic_lights_4"},
)
self.assertTrue(all(item["fsi_segment_count"] > 0 for item in response_objects))
self.assertEqual(len({item["fsi_segment_set_id"] for item in response_objects}), len(response_objects))
self.assertEqual(len({item["fsi_surface_id"] for item in response_objects}), len(response_objects))
self.assertEqual(len({item["shell_history_set_id"] for item in response_objects}), len(response_objects))
self.assertEqual(len({item["node_history_set_id"] for item in response_objects}), len(response_objects))
```

Also parse all `*SET_SEGMENT` entries and assert no segment tuple appears in two required response sets.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_city_street_blast.CityStreetBlastTests.test_response_objects_have_disjoint_fsi_and_history_sets
```

Expected: FAIL because the generator currently emits one aggregate FSI set and no per-object history contract.

- [ ] **Step 3: Implement per-object topology collection**

Extend component assembly bookkeeping so each response object retains:

```python
{
    "object_id": str,
    "part_id": int,
    "fsi_segments": list[tuple[int, int, int, int]],
    "shell_element_ids": list[int],
    "node_ids": list[int],
    "expected_distance_m": float,
}
```

Reject empty response topology, duplicated FSI segments, and set-ID collisions during generation.

- [ ] **Step 4: Emit per-object LS-DYNA cards**

For every response object emit a titled segment set, one coupling card bound to the common ALE master, a shell-list set, and a node-list set. Add `*DATABASE_ELOUT`, `*DATABASE_NODOUT`, `*DATABASE_HISTORY_SHELL_SET`, and `*DATABASE_HISTORY_NODE_SET` using the existing database interval.

- [ ] **Step 5: Run focused and neighboring tests**

Run:

```powershell
python -m unittest tests.test_city_street_blast tests.test_keyword_checks
```

Expected: PASS.

- [ ] **Step 6: Commit the task**

```powershell
git add -- lsprepost_mcp/city_street_blast.py tests/test_city_street_blast.py
git commit -m "feat: emit per-object city FSI response sets"
```

### Task 2: Connected Traffic-Light Shell Topology

**Files:**
- Modify: `tests/test_component_library.py`
- Modify: `tests/test_city_street_blast.py`
- Modify: `lsprepost_mcp/dyna_assembly.py`
- Modify: `lsprepost_mcp/city_street_blast.py`

**Interfaces:**
- Consumes: `build_traffic_light_component(...)`.
- Produces: a connected traffic-light shell graph and correct `material_name="mild_steel"` metadata.

- [ ] **Step 1: Write failing connectivity and material tests**

Build one traffic light and construct a node-sharing adjacency graph over its shell elements. Assert that it has exactly one connected component, that all fixed nodes are at the base, that the arm/head contain no disconnected island, and that the generated semantic component reports `mild_steel`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_component_library tests.test_city_street_blast
```

Expected: FAIL because pole, arm, and head are currently merged only by ID renumbering and the city metadata omits the steel material name.

- [ ] **Step 3: Rebuild the traffic light with shared interface nodes**

Use a maximum local mesh size of `0.10 m`. Make pole-to-arm and arm-to-head interfaces share node IDs, preserve base-only constraints, and orient shell faces consistently. Do not add rigid constraints that suppress the intended structural response.

- [ ] **Step 4: Add a generic response-topology gate**

Before keyword emission, reject required response parts whose shell-element node graph contains more than one connected component. Components intentionally used only as visual guides remain excluded from FSI and response acceptance.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m unittest tests.test_component_library tests.test_city_street_blast
```

Expected: PASS.

- [ ] **Step 6: Commit the task**

```powershell
git add -- lsprepost_mcp/dyna_assembly.py lsprepost_mcp/city_street_blast.py tests/test_component_library.py tests/test_city_street_blast.py
git commit -m "fix: connect city traffic light shell topology"
```

### Task 3: Per-Object Structural Result Parsing

**Files:**
- Modify: `tests/test_solver_results.py`
- Modify: `lsprepost_mcp/solver_results.py`

**Interfaces:**
- Consumes: LS-DYNA `dbfsi`, `elout`, and `nodout` text plus model response-object metadata.
- Produces: `parse_city_object_responses(run_dir, response_objects) -> dict[str, dict]`.

- [ ] **Step 1: Write failing parser tests with two objects**

Create representative DBFSI fixtures with two surface IDs, ELOUT shell histories for two shell sets, and NODOUT displacement histories for two node sets. Assert independent baseline-subtracted values:

```python
self.assertEqual(result["building_a"]["fsi_surface_id"], 41)
self.assertGreater(result["building_a"]["peak_fsi_pressure_rise_pa"], 0.0)
self.assertGreater(result["building_a"]["peak_structural_pressure_pa"], 0.0)
self.assertGreater(result["building_a"]["peak_principal_stress_pa"], 0.0)
self.assertGreater(result["building_a"]["peak_displacement_m"], 0.0)
self.assertLess(result["building_a"]["fsi_arrival_time_s"], result["building_b"]["fsi_arrival_time_s"])
```

- [ ] **Step 2: Run parser tests and verify RED**

Run:

```powershell
python -m unittest tests.test_solver_results
```

Expected: FAIL because object-level ELOUT/NODOUT joining does not exist.

- [ ] **Step 3: Implement finite baseline and noise helpers**

Add helpers that reject non-finite samples, derive a pre-arrival baseline, compute robust noise amplitude from baseline samples, and require both an absolute floor and a noise multiplier. A one-sample spike must not qualify as arrival.

- [ ] **Step 4: Implement ELOUT and NODOUT object mapping**

Parse shell stress tensors and compute:

```python
hydrostatic_pressure = -(sigma_x + sigma_y + sigma_z) / 3.0
```

Compute finite principal-stress magnitude and resultant displacement. Map records only through the generator-provided shell/node sets; do not infer object identity from title prefixes.

- [ ] **Step 5: Run parser tests**

Run:

```powershell
python -m unittest tests.test_solver_results
```

Expected: PASS.

- [ ] **Step 6: Commit the task**

```powershell
git add -- lsprepost_mcp/solver_results.py tests/test_solver_results.py
git commit -m "feat: parse object-level city structural response"
```

### Task 4: Fail-Closed City Response Acceptance

**Files:**
- Modify: `tests/test_lsdyna_runner.py`
- Modify: `lsprepost_mcp/lsdyna_runner.py`

**Interfaces:**
- Consumes: `parse_city_object_responses(...)`, run evidence, model response-object metadata, and d3plot time states.
- Produces: `solver_evaluation["city_object_response"]` with per-object checks and a fail-closed aggregate result.

- [ ] **Step 1: Write failing acceptance tests**

Cover these independent failures:

```python
required_cases = [
    "missing_dbfsi_surface",
    "pressure_below_noise",
    "single_sample_pressure_spike",
    "missing_structural_stress",
    "missing_displacement",
    "response_before_arrival",
    "insufficient_post_arrival_window",
    "unstable_displacement",
]
```

Also assert that a nonzero `1e-6 J` MATSUM change cannot make a failed object pass.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_lsdyna_runner
```

Expected: FAIL because current acceptance uses aggregate DBFSI and the weak MATSUM threshold.

- [ ] **Step 3: Implement per-object gates**

For each required object require:

- matching DBFSI surface;
- nonempty segment count;
- finite pressure rise above absolute and baseline-noise thresholds;
- pressure duration spanning at least two samples;
- finite structural hydrostatic-pressure and principal-stress response;
- finite nontrivial displacement below a geometry-scaled instability cap;
- structural arrival no earlier than FSI arrival minus one output interval; and
- at least `0.020 s` from qualified arrival to the last d3plot state.

- [ ] **Step 4: Add propagation-order diagnostics**

Sort objects by `expected_distance_m` and report arrival inversions exceeding one output interval. Treat gross inversions as failure while retaining close/equidistant pairs as diagnostics.

- [ ] **Step 5: Replace the old aggregate pass path**

Keep global DBFSI and MATSUM values as diagnostics. Set the city response result to pass only when every required object passes the new gates and the solver/run evidence is valid.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
python -m unittest tests.test_lsdyna_runner tests.test_solver_results
```

Expected: PASS.

- [ ] **Step 7: Commit the task**

```powershell
git add -- lsprepost_mcp/lsdyna_runner.py tests/test_lsdyna_runner.py
git commit -m "fix: require qualified city object response"
```

### Task 5: Duration and Qualitative-Material Claim Boundaries

**Files:**
- Modify: `tests/test_city_street_blast.py`
- Modify: `tests/test_lsdyna_runner.py`
- Modify: `lsprepost_mcp/city_street_blast.py`
- Modify: `lsprepost_mcp/lsdyna_runner.py`

**Interfaces:**
- Consumes: scene geometry, blast center, database interval, and material metadata.
- Produces: corrected end time and explicit `qualitative_only`/`quantitative_claim_blockers`.

- [ ] **Step 1: Write failing duration and claim tests**

Assert default end time is at least `0.050 s`, and acceptance remains quantitatively blocked when MID 3 is `concrete_linear_elastic_demo` even if all propagation gates pass.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_city_street_blast tests.test_lsdyna_runner
```

Expected: FAIL for the current 30 ms default/qualitative claim behavior.

- [ ] **Step 3: Implement duration budgeting**

Set:

```python
required_end_time_s = max(
    requested_end_time_s,
    0.050,
    estimated_farthest_arrival_s + 0.020,
)
```

Record the requested and effective values in `model.json`.

- [ ] **Step 4: Implement material claim blockers**

Report workflow/qualitative acceptance separately from engineering/quantitative acceptance. Do not replace MID 3 with an invented K&C card. Require an explicit calibration artifact before removing the blocker.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m unittest tests.test_city_street_blast tests.test_lsdyna_runner
```

Expected: PASS.

- [ ] **Step 6: Commit the task**

```powershell
git add -- lsprepost_mcp/city_street_blast.py lsprepost_mcp/lsdyna_runner.py tests/test_city_street_blast.py tests/test_lsdyna_runner.py
git commit -m "fix: budget city response duration and claims"
```

### Task 6: LS-PrePost Per-Building Pressure Evidence

**Files:**
- Create: `resources/templates/cfile/city_object_pressure.cfile`
- Modify: `tests/test_tools.py`
- Modify: `tests/test_integration_lsprepost.py`
- Modify: `lsprepost_mcp/cfile.py`
- Modify: `lsprepost_mcp/tool_lsprepost.py`
- Modify: `lsprepost_mcp/tools.py`

**Interfaces:**
- Consumes: trusted d3plot, object PID, qualified peak state, and output artifact filename.
- Produces: provenance-bound PNG and `city_object_pressure_images.json`.

- [ ] **Step 1: Write failing cfile and tool tests**

Assert the tool rejects unknown PIDs, missing qualified peak states, untrusted result paths, and output paths outside project artifacts. Assert one image record per required building PID 19, 20, and 21.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_tools
```

Expected: FAIL because no object-isolated pressure export contract exists.

- [ ] **Step 3: Add the controlled cfile template**

The template must open the trusted d3plot, select the qualified state, isolate the requested PID, activate structural pressure fringe, fit the object, render a PNG, and quit. All arguments use the existing cfile parameter whitelist and manifest/hash checks.

- [ ] **Step 4: Implement the export tool**

Generate deterministic filenames such as:

```text
city_pressure_commercial_supermarket_pid19_state12.png
```

Validate PNG signature and nonzero size, hash each artifact, and store object ID, PID, state, time, pressure range, cfile hash, image hash, and generated time in the evidence manifest.

- [ ] **Step 5: Update integration smoke**

When `LSPP_INTEGRATION=1`, run the export for one generated building and verify the PNG signature and manifest binding. Keep it skipped by default.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
python -m unittest tests.test_tools tests.test_integration_lsprepost
```

Expected: PASS with the real GUI integration skipped unless enabled.

- [ ] **Step 7: Commit the task**

```powershell
git add -- resources/templates/cfile/city_object_pressure.cfile lsprepost_mcp/cfile.py lsprepost_mcp/tool_lsprepost.py lsprepost_mcp/tools.py tests/test_tools.py tests/test_integration_lsprepost.py
git commit -m "feat: export per-building pressure evidence"
```

### Task 7: Three-Mesh Object Response Convergence

**Files:**
- Modify: `tests/test_lsdyna_runner.py`
- Modify: `lsprepost_mcp/lsdyna_runner.py`
- Modify: `lsprepost_mcp/tools.py`

**Interfaces:**
- Consumes: three valid runs with immutable model/run evidence and identical physical parameters.
- Produces: `city_object_mesh_convergence.json`.

- [ ] **Step 1: Write failing convergence tests**

Use coarse/medium/fine fixtures and assert:

- mesh sizes are bound to each run snapshot;
- invalid solver or object-response runs are rejected;
- pressure, structural stress, and displacement are evaluated per object;
- monotonic, oscillatory, divergent, and insufficient-evidence classifications are distinct; and
- GCI is reported only when refinement ratios and observed order are valid.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_lsdyna_runner
```

Expected: FAIL because city object convergence does not exist.

- [ ] **Step 3: Implement convergence evaluation**

Require identical object IDs, materials, geometry, blast definition, end time, and response-set contract across runs. Bind mesh size to each immutable run snapshot. Never read the mutable current `model.json` for convergence evidence.

- [ ] **Step 4: Expose a controlled convergence tool**

Accept exactly three project/run identities and write the report into the selected project artifacts. Return `converged=false` for invalid, oscillatory without bounded uncertainty, divergent, or incomplete evidence.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m unittest tests.test_lsdyna_runner tests.test_tools
```

Expected: PASS.

- [ ] **Step 6: Commit the task**

```powershell
git add -- lsprepost_mcp/lsdyna_runner.py lsprepost_mcp/tools.py tests/test_lsdyna_runner.py tests/test_tools.py
git commit -m "feat: evaluate city object mesh convergence"
```

### Task 8: Generate and Validate the Corrected Project

**Files:**
- Modify: `docs/ROADMAP.zh-CN.md`
- Generated outside source tree: `E:\K文件模型\web_phase17_city_street_blast_response_v2`

**Interfaces:**
- Consumes: completed generator, solver runner, object acceptance, and LS-PrePost export tool.
- Produces: a new project and immutable validation evidence without modifying prior projects.

- [ ] **Step 1: Run the full automated baseline**

Run:

```powershell
python -m unittest discover -s tests
python -m compileall -q .\lsprepost_mcp
```

Expected: all unit tests pass; real GUI/solver tests may be skipped only when their explicit environment switches are absent.

- [ ] **Step 2: Generate the new project**

Generate `web_phase17_city_street_blast_response_v2`, mirror it to `E:\K文件模型`, and verify the old project hashes remain unchanged.

- [ ] **Step 3: Run static keyword and topology gates**

Require one ALE master, seven disjoint response interfaces, nonempty shell/node history sets, connected traffic lights, no duplicate FSI segment, exact `*KEYWORD`/`*END`, and no keyword-check error.

- [ ] **Step 4: Run LS-PrePost import validation**

Open/import the new `model.k` through the controlled launcher. Fail if LS-PrePost reports a keyword error or if required parts/sets are absent.

- [ ] **Step 5: Run the real LS-DYNA solve**

Solve at the effective duration of at least 50 ms. Require valid immutable run evidence, normal solver acceptance, seven DBFSI surfaces, ELOUT/NODOUT data, and complete d3plot states.

- [ ] **Step 6: Run object-level acceptance**

Require qualified response for PID 19 commercial, PID 20 residential, PID 21 subway, and all four traffic lights. If any object fails, retain the failed evidence, revise only the new project/generator, and repeat from the failing gate.

- [ ] **Step 7: Export building pressure images**

Generate and validate one structural-pressure PNG for each of PIDs 19, 20, and 21 at its qualified post-arrival peak state. Open the solved d3plot in LS-PrePost for user inspection.

- [ ] **Step 8: Run or explicitly block mesh convergence**

Run coarse/medium/fine solves if compute time permits. If not completed, write `converged=false` with `reason="three_mesh_campaign_not_completed"` and keep quantitative acceptance blocked.

- [ ] **Step 9: Update the roadmap and rerun verification**

Document shell-only semantics, per-object evidence, material limitations, real-run result, and remaining solid-wall work. Then rerun:

```powershell
python -m unittest discover -s tests
python -m compileall -q .\lsprepost_mcp
scripts\pack.ps1
```

- [ ] **Step 10: Commit source and documentation**

```powershell
git add -- lsprepost_mcp resources/templates/cfile tests docs/ROADMAP.zh-CN.md
git commit -m "feat: validate per-object city blast response"
```

