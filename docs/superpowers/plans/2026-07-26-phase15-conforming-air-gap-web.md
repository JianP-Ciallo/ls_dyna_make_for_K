# Phase 15 Conforming Air-Gap Web Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a parameterized, zero-overlap Phase 15 air-gap model that generates a validated K file in a new project, hands an isolated snapshot to LS-Run, recovers and qualifies LS-DYNA results, and opens the immutable result in LS-PrePost from the existing Web application.

**Architecture:** Extend the existing Phase 15 geometry and keyword compilers with a third `conforming_air_gap` mode. Reuse the project store, locks, evidence manifests, solver parsers, LS-PrePost launcher, and Web API; add one focused LS-Run handoff module because no current module owns isolated external-run preparation and recovery. Existing projects are read-only and the immersed reference remains the default.

**Tech Stack:** Python 3.10+ standard library, `unittest`, LS-DYNA keyword format, LS-Run 1.0, LS-PrePost 4.12, existing vanilla HTML/CSS/JavaScript Web UI.

## Global Constraints

- Do not modify any project directory that existed before this work.
- Create conforming projects with a new project name and `if_exists=error`.
- Keep `immersed_clis` as the default and preserve its generated keyword behavior.
- Keep `conforming_shared_nodes` readable but `experimental_unqualified`.
- Expose only `immersed_clis` and `conforming_air_gap` in the Web UI.
- Require at least three actual ALE cells in side and bottom air gaps.
- Require zero ALE/concrete volume overlap and zero TNT/concrete node or edge sharing.
- Reuse existing path, lock, process, evidence, cfile, and JSON helpers.
- Do not qualify propagation from static validation or normal termination alone.
- Do not claim calibrated engineering accuracy for the K&C material.

---

### Task 1: Public Contract and Existing-Project Protection

**Files:**
- Modify: `lsprepost_mcp/phase15.py`
- Modify: `lsprepost_mcp/tool_generation.py`
- Modify: `tests/test_phase15_conforming.py`
- Modify: `tests/test_phase15_prerequisites.py`

**Interfaces:**
- Produces: `PHASE15_COUPLING_MODES` including `conforming_air_gap`
- Produces: `resolve_phase15_air_gap(inputs: JSONDict) -> JSONDict`
- Enforces: conforming generation accepts only `if_exists="error"`
- Preserves: calls omitting `coupling_mode` resolve to `immersed_clis`

- [ ] **Step 1: Write failing coupling and immutability tests**

Add tests equivalent to:

```python
def test_conforming_air_gap_is_explicit_and_immersed_remains_default(self):
    defaults = default_phase15_a1_inputs()
    self.assertEqual(defaults["coupling_mode"], "immersed_clis")
    defaults["coupling_mode"] = "conforming_air_gap"
    resolved = resolve_phase15_air_gap(defaults)
    self.assertEqual(resolved["minimum_gap_cells"], 3)

def test_conforming_generation_rejects_destructive_if_exists_modes(self):
    for mode in ("overwrite", "archive_then_write", "versioned"):
        with self.assertRaisesRegex(ValueError, "if_exists=error"):
            tool_generate_phase15_a1({
                "project_name": "new_conforming_contract",
                "coupling_mode": "conforming_air_gap",
                "consistency_mode": "mass_priority_adjust_length",
                "if_exists": mode,
                "dry_run": True,
            })
```

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_phase15_conforming tests.test_phase15_prerequisites
```

Expected: failures because `conforming_air_gap` and `resolve_phase15_air_gap` do not exist.

- [ ] **Step 3: Implement the minimal public contract**

Add constants:

```python
PHASE15_COUPLING_MODES = (
    "conforming_shared_nodes",
    "conforming_air_gap",
    "immersed_clis",
)
MIN_PHASE15_AIR_GAP_CELLS = 3
DEFAULT_PHASE15_AIR_GAP_CELLS = 4
```

Resolve defaults as explicit dimensions:

```python
def resolve_phase15_air_gap(inputs: JSONDict) -> JSONDict:
    mesh = _positive(inputs.get("mesh_size_m"), "mesh_size_m")
    radius = _positive(inputs.get("tnt_radius_m"), "tnt_radius_m")
    borehole = _positive(
        inputs.get("borehole_radius_m", radius + DEFAULT_PHASE15_AIR_GAP_CELLS * mesh),
        "borehole_radius_m",
    )
    bottom = _positive(
        inputs.get("bottom_air_gap_m", DEFAULT_PHASE15_AIR_GAP_CELLS * mesh),
        "bottom_air_gap_m",
    )
    return {
        "borehole_radius_m": borehole,
        "side_air_gap_m": borehole - radius,
        "bottom_air_gap_m": bottom,
        "minimum_gap_cells": MIN_PHASE15_AIR_GAP_CELLS,
    }
```

Add schema properties for `borehole_radius_m` and `bottom_air_gap_m`. Reject
`fsi_overlap_layers` outside `immersed_clis`. In `tool_generate_phase15_a1`,
reject every conforming `if_exists` value except `error`, including dry runs.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run:

```powershell
python -m unittest tests.test_phase15_conforming tests.test_phase15_prerequisites
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/phase15.py lsprepost_mcp/tool_generation.py tests/test_phase15_conforming.py tests/test_phase15_prerequisites.py
git commit -m "feat: define phase15 conforming air-gap contract"
```

### Task 2: Parameterized Zero-Overlap Geometry

**Files:**
- Modify: `lsprepost_mcp/phase15.py`
- Modify: `tests/test_phase15_conforming.py`

**Interfaces:**
- Consumes: `resolve_phase15_air_gap(inputs)`
- Produces: resolved `borehole_radius_m`, `borehole_bottom_z_m`, actual gap sizes and cell counts
- Produces: `regions["air"]` containing bottom, side, top, and opening air
- Produces: `interfaces["tnt_to_concrete"]` with zero matches in the new mode

- [ ] **Step 1: Write failing geometry tests**

Cover:

```python
def test_air_gap_separates_tnt_from_concrete(self):
    plan = compile_phase15_a1_mesh_plan(_inputs("conforming_air_gap"))
    gap = plan["phase15_air_gap"]
    self.assertGreaterEqual(gap["side_air_gap_cells"], 3)
    self.assertGreaterEqual(gap["bottom_air_gap_cells"], 3)
    self.assertEqual(plan["interfaces"]["tnt_to_concrete"]["shared_node_count"], 0)
    self.assertEqual(plan["fsi_coupling"]["overlap_depth_m"], 0.0)

def test_air_gap_below_three_actual_cells_is_rejected(self):
    values = _inputs("conforming_air_gap")
    values["mesh_size_m"] = 0.01
    values["borehole_radius_m"] = float(values["tnt_radius_m"]) + 0.02
    with self.assertRaisesRegex(ValueError, "at least 3 actual ALE cells"):
        compile_phase15_a1_mesh_plan(values)
```

Also assert that no TNT element node belongs to a concrete element and no ALE
element centroid lies in the concrete material region.

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```powershell
python -m unittest tests.test_phase15_conforming
```

Expected: failures because the compiler still uses the TNT radius as the cavity radius.

- [ ] **Step 3: Implement the conforming air-gap mesh**

For `conforming_air_gap`:

```python
borehole_radius = air_gap["borehole_radius_m"]
borehole_bottom = charge_bottom - air_gap["bottom_air_gap_m"]
concrete_r = _segmented_coordinates([0.0, borehole_radius, radius], mesh_size)
concrete_z = _segmented_coordinates(
    [0.0, borehole_bottom, charge_bottom, charge_top, target_top],
    mesh_size,
)
```

Exclude the borehole from concrete using `borehole_radius` and
`borehole_bottom`. Build ALE coordinates through
`borehole_bottom`, `charge_bottom`, `charge_top`, `target_top`, and `air_top`.
Exclude only the TNT volume from the air material region. Record actual cell
counts from coordinate intervals rather than dividing requested values.

Name active surfaces `borehole_bottom` and `borehole_side`. Keep existing
immersed and historical conforming branches unchanged.

- [ ] **Step 4: Run focused and legacy tests**

Run:

```powershell
python -m unittest tests.test_phase15_conforming tests.test_phase15_prerequisites
```

Expected: all tests pass and the immersed assertions remain unchanged.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/phase15.py tests/test_phase15_conforming.py
git commit -m "feat: generate phase15 zero-overlap air-gap geometry"
```

### Task 3: Shared Interface Assembly, Keyword Cards, and Probes

**Files:**
- Modify: `lsprepost_mcp/phase15_keyword.py`
- Modify: `lsprepost_mcp/phase15_fsi.py`
- Modify: `tests/test_phase15_keyword.py`
- Modify: `tests/test_phase15_conforming.py`

**Interfaces:**
- Consumes: new mesh-plan surfaces and gap metadata
- Produces: `interface_surfaces`, shared node/edge counts, TNT/concrete adjacency count
- Produces: named ALE probes `TNT_NEAR`, `AIR_MID_GAP`, `AIR_INTERFACE`
- Preserves: CLIS and DBFSI cards only for `immersed_clis`

- [ ] **Step 1: Write failing solver-model and keyword tests**

Assert:

```python
model = compile_phase15_a1_solver_model(_inputs("conforming_air_gap"))
self.assertEqual(model["interfaces"]["tnt_concrete_shared_node_count"], 0)
self.assertGreater(model["interfaces"]["shared_edge_count"], 0)
self.assertEqual(
    {probe["id"] for probe in model["probes"]["ale"]},
    {"TNT_NEAR", "AIR_MID_GAP", "AIR_INTERFACE"},
)
```

Require keyword text to contain ALE smoothing and history sets, and not contain:

```text
*CONSTRAINED_LAGRANGE_IN_SOLID
*DATABASE_FSI
```

Require metadata ALE extents to equal actual generated coordinates.

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_phase15_keyword tests.test_phase15_conforming
```

Expected: failures because probes are unnamed IDs and the interface still uses charge dimensions.

- [ ] **Step 3: Assemble shared nodes only at borehole side and bottom**

Reuse the existing node-merging and smoothing helpers. Pass the resolved
borehole radius to radial smoothing. Build interface segment metadata from
`borehole_bottom` and `borehole_side`; do not alias it to CLIS
`fsi_surfaces`.

Change `_select_ale_probes` to return:

```python
[
    {"id": "TNT_NEAR", "element_id": source_id, "location_r_z_m": [...]},
    {"id": "AIR_MID_GAP", "element_id": mid_id, "location_r_z_m": [...]},
    {"id": "AIR_INTERFACE", "element_id": interface_id, "location_r_z_m": [...]},
]
```

Use the returned element IDs in `ALE_PROBE_SHELL_SET_ID`. Add static validation
for complete adjacency, zero TNT/concrete sharing, and three unique ALE probes.

- [ ] **Step 4: Run keyword and conforming tests**

Run:

```powershell
python -m unittest tests.test_phase15_keyword tests.test_phase15_conforming
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/phase15_keyword.py lsprepost_mcp/phase15_fsi.py tests/test_phase15_keyword.py tests/test_phase15_conforming.py
git commit -m "feat: emit phase15 conforming interface and probes"
```

### Task 4: Air-to-Concrete Propagation Acceptance

**Files:**
- Modify: `lsprepost_mcp/phase15_fsi.py`
- Modify: `lsprepost_mcp/lsdyna_runner.py`
- Modify: `tests/test_phase15_fsi.py`
- Modify: `tests/test_lsdyna_runner.py`

**Interfaces:**
- Produces: `parse_phase15_ale_elout(path: Path, probe_metadata: list[JSONDict]) -> JSONDict`
- Extends: `evaluate_phase15_wave_transfer(..., ale_probe_metadata=None, history_output_dt_s=None)`
- Produces: `transfer_evidence` and qualification status for `conforming_air_gap`

- [ ] **Step 1: Write failing parser and ordering tests**

Use synthetic `elout` states for material 1 and material 3. Cover:

- TNT-near, mid-gap, and interface ALE arrivals in order;
- concrete interface response after ALE interface arrival;
- rejection of a one-state spike;
- rejection of pre-arrival concrete displacement;
- readable finite damage equal to zero remains readable;
- non-finite values fail closed.

The key assertion is:

```python
self.assertEqual(
    [item["probe_id"] for item in report["transfer_evidence"]["arrivals"]],
    ["TNT_NEAR", "AIR_MID_GAP", "AIR_INTERFACE", "CONCRETE_INTERFACE"],
)
self.assertTrue(report["wave_transfer_verified"])
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_phase15_fsi tests.test_lsdyna_runner
```

Expected: failures because conforming ALE history is not parsed.

- [ ] **Step 3: Implement baseline, duration, and arrival gates**

Parse material-1 ALE probe stress/pressure states separately from K&C damage
states. For each series compute:

```python
baseline = statistics.fmean(pre_arrival_values)
noise = max(abs(value - baseline) for value in pre_arrival_values)
threshold = max(1.0e6, 10.0 * noise)
```

Require at least two consecutive samples above threshold. Permit arrival
ordering tolerance of one `history_output_dt_s`. Add explicit checks for
normal termination, negative-volume markers, finite energy, ordered air
arrivals, interface transfer, concrete propagation, K&C readability, and
post-load displacement.

Pass probe metadata and output interval from `_phase15_wave_transfer_acceptance`
in `lsdyna_runner.py`.

- [ ] **Step 4: Run acceptance tests**

Run:

```powershell
python -m unittest tests.test_phase15_fsi tests.test_lsdyna_runner
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/phase15_fsi.py lsprepost_mcp/lsdyna_runner.py tests/test_phase15_fsi.py tests/test_lsdyna_runner.py
git commit -m "feat: qualify phase15 air-gap wave transfer"
```

### Task 5: Isolated LS-Run Handoff and Evidence Recovery

**Files:**
- Create: `lsprepost_mcp/lsrun_handoff.py`
- Modify: `lsprepost_mcp/web/solve_api.py`
- Modify: `lsprepost_mcp/web/app.py`
- Create: `tests/test_lsrun_handoff.py`
- Modify: `tests/test_web_api.py`

**Interfaces:**
- Produces: `prepare_lsrun_handoff(project: Path, lsrun: Path, lsdyna: Path | None, *, ncpu: int, memory: str) -> JSONDict`
- Produces: `launch_lsrun_handoff(project: Path, handoff: JSONDict) -> JSONDict`
- Produces: `recover_lsrun_result(project: Path, run_id: str) -> JSONDict`
- Reuses: project locks, atomic JSON writes, evidence sealing and validation, solver output inspection

- [ ] **Step 1: Write failing handoff tests**

In a temporary project, assert preparation:

```python
record = prepare_lsrun_handoff(project, lsrun, lsdyna, ncpu=4, memory="512m")
run_dir = Path(record["run_dir"])
self.assertEqual((run_dir / "model.k").read_bytes(), (project / "model.k").read_bytes())
self.assertEqual(record["status"], "handoff_prepared")
self.assertNotEqual(run_dir, project)
```

Assert:

- an existing project file hash is unchanged;
- no path escapes the project `solver_runs` directory;
- opening LS-Run records `handoff_opened`, not `running`;
- recovery refuses changed `model.k`;
- recovery requires `d3hsp`, `d3plot`, `elout`, and mode-specific histories;
- recovery seals output hashes and calls the existing solver evaluation.

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_lsrun_handoff tests.test_web_api
```

Expected: import failure for the missing module.

- [ ] **Step 3: Implement the focused handoff module**

Create the run directory under a project lock, copy `model.k` and `model.json`
atomically, hash both, and write `run.json` plus the project
`solver_runs/latest.json` pointer. Launch:

```python
subprocess.Popen(
    [str(lsrun), str(run_dir / "model.k")],
    cwd=str(run_dir),
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
)
```

If the process accepts no input argument, preserve `handoff_opened` and return
the exact INPUT path. Never infer job submission from the LS-Run PID.

Recovery verifies input hashes before inspecting output, evaluates the run,
seals evidence through `seal_phase14_run_evidence`, validates it, and updates
the run record atomically.

Update `/api/solve/open-lsrun` to prepare and launch the snapshot. Add
`POST /api/solve/recover-lsrun`.

- [ ] **Step 4: Run handoff and Web API tests**

Run:

```powershell
python -m unittest tests.test_lsrun_handoff tests.test_web_api
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/lsrun_handoff.py lsprepost_mcp/web/solve_api.py lsprepost_mcp/web/app.py tests/test_lsrun_handoff.py tests/test_web_api.py
git commit -m "feat: add isolated LS-Run handoff and recovery"
```

### Task 6: Immutable LS-PrePost Result Opening

**Files:**
- Modify: `lsprepost_mcp/lspp/launcher.py`
- Modify: `lsprepost_mcp/tool_lsprepost.py`
- Modify: `lsprepost_mcp/web/app.py`
- Modify: `tests/test_tools.py`
- Modify: `tests/test_web_api.py`

**Interfaces:**
- Produces: `validate_d3plot_path(project_path: Path, d3plot_path: Path) -> Path`
- Produces: `launch_d3plot(project_path: Path, d3plot_path: Path, timeout_s: float | None = None) -> JSONDict`
- Produces: Web endpoint `POST /api/project/open-result-lsprepost`

- [ ] **Step 1: Write failing result-boundary tests**

Require:

- only a non-empty `d3plot` file below `project/solver_runs/<run_id>` is valid;
- project-root, external, directory, symlink escape, and arbitrary extension are rejected;
- the selected run input and evidence manifest validate before launch;
- launcher command references the immutable run result.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_tools tests.test_web_api
```

Expected: missing `launch_d3plot` and endpoint failures.

- [ ] **Step 3: Implement result launch by reusing process controls**

Validate the result path, then call the existing
`launch_lsprepost_command` with mode `d3plot_result` and:

```python
[str(exe), str(d3plot_path)]
```

Record `d3plot_path`, run ID, d3plot hash, and evidence-manifest hash in the
process record. The Web endpoint resolves the latest qualified or completed
run and launches that result, never the project-root K file.

- [ ] **Step 4: Run tool and API tests**

Run:

```powershell
python -m unittest tests.test_tools tests.test_web_api
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/lspp/launcher.py lsprepost_mcp/tool_lsprepost.py lsprepost_mcp/web/app.py tests/test_tools.py tests/test_web_api.py
git commit -m "feat: open immutable solver results in LS-PrePost"
```

### Task 7: Web Controls and Status Semantics

**Files:**
- Modify: `lsprepost_mcp/web/static/index.html`
- Modify: `lsprepost_mcp/web/static/app.js`
- Modify: `lsprepost_mcp/web/static/styles.css`
- Modify: `tests/test_web_static.py`
- Modify: `tests/test_web_api.py`

**Interfaces:**
- Consumes: Phase 15 prepare/generate and LS-Run recovery endpoints
- Produces: conditional conforming controls and independent status badges

- [ ] **Step 1: Write failing static UI tests**

Require stable IDs:

```text
phase15CouplingMode
phase15ConformingFields
phase15BoreholeRadius
phase15BottomAirGap
phase15AirGapSummary
recoverLsrun
openResultLspp
phase15StaticBadge
phase15SolverBadge
phase15TransferBadge
phase15CalibrationBadge
```

Require the Web payload to omit `fsi_overlap_layers` for conforming mode and
omit air-gap fields for immersed mode.

- [ ] **Step 2: Run Web tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_web_static tests.test_web_api
```

Expected: missing-element and payload failures.

- [ ] **Step 3: Add conditional controls and status rendering**

Add a coupling selector and unframed conditional field groups. Show actual
side/bottom gap cell counts from the prepare response; do not duplicate the
backend cell-count calculation in JavaScript.

Change `sendToLsrun()` to include CPU and memory options and display the run
snapshot path. Add `recoverLsrun()` and `openResultLspp()`. Render static,
solver, transfer, and calibration states independently so normal termination
cannot display as qualified transfer.

- [ ] **Step 4: Run Web tests**

Run:

```powershell
python -m unittest tests.test_web_static tests.test_web_api
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/web/static/index.html lsprepost_mcp/web/static/app.js lsprepost_mcp/web/static/styles.css tests/test_web_static.py tests/test_web_api.py
git commit -m "feat: expose phase15 conforming workflow in web app"
```

### Task 8: Full Regression, New Project, LS-Run, and LS-PrePost Qualification

**Files:**
- Modify: `tests/test_integration_lsprepost.py`
- Modify: `docs/ROADMAP.zh-CN.md`
- Create at runtime only: `workspace/projects/phase15_conforming_air_gap_<timestamp>/`

**Interfaces:**
- Uses: all interfaces from Tasks 1-7
- Produces: a new project, isolated LS-Run evidence, acceptance report, and LS-PrePost artifacts
- Must not modify: any pre-existing project directory

- [ ] **Step 1: Add opt-in integration coverage**

Add an opt-in test guarded by `LSPP_INTEGRATION=1` and
`LSDYNA_INTEGRATION=1`. It generates a uniquely named project, validates the K
file, prepares the LS-Run directory, and verifies recovered result identity.
The test never names or opens an existing project.

- [ ] **Step 2: Run all unit tests**

Run:

```powershell
python -m unittest discover -s tests
python -m compileall -q .\lsprepost_mcp
```

Expected: all non-integration tests pass; opt-in tests are skipped.

- [ ] **Step 3: Hash existing project files before real work**

Create an in-memory or temporary-file inventory of every existing file below
`workspace/projects`, excluding the new project name. Record relative path,
size, and SHA-256. Do not write the inventory inside an old project.

- [ ] **Step 4: Generate and statically validate a new conforming project**

Use a unique name beginning `phase15_conforming_air_gap_`. Use:

```json
{
  "coupling_mode": "conforming_air_gap",
  "consistency_mode": "mass_priority_adjust_length",
  "mesh_size_m": 0.006,
  "borehole_radius_m": 0.073,
  "bottom_air_gap_m": 0.024,
  "if_exists": "error"
}
```

Require zero keyword errors, zero overlap, zero TNT/concrete shared nodes, at
least three cells in both gaps, and complete shared interface edges.

- [ ] **Step 5: Run initialization and LS-Run qualification**

With the user's explicit process-launch approval, open the configured LS-Run
on the isolated snapshot:

```text
E:\dyna\25-26-2土木工程数值模拟技术-教学资料\3.LS-RUN\LS-Run 1.0\lsrun.exe
```

Use the configured R12 LS-DYNA solver, 4 CPUs, and at least `512m` memory. Run
an initialization check first. Proceed to the full `0.0002 s` controlled solve
only when no negative-volume or keyword-reader failure is present.

- [ ] **Step 6: Recover and evaluate evidence**

Require status `qualified`, ordered ALE and concrete arrivals, finite K&C
pressure/stress/damage, no pre-arrival displacement, and a valid immutable
evidence manifest. Preserve failed runs for diagnosis without weakening gates.

- [ ] **Step 7: Open and render in LS-PrePost**

Open the recovered run `d3plot` with:

```text
E:\LS-prepost\LS-PrePost-2025R1(4.12)\lsprepost4.12.exe
```

Generate pressure, principal-stress, damage, and true-scale deformation
artifacts. Verify each image is non-empty and linked to run and input hashes.

- [ ] **Step 8: Verify old projects are unchanged**

Recompute the pre-existing project inventory and require every recorded
relative path, size, and SHA-256 to match. New files are allowed only below the
new conforming project.

- [ ] **Step 9: Verify the Web UI**

Start the existing Web app, inspect desktop and narrow viewport layouts, and
exercise prepare, generate, LS-Run handoff, recover, and LS-PrePost-open
actions. Confirm conditional fields do not shift or overlap controls.

- [ ] **Step 10: Update status documentation and commit**

Record actual qualification status and evidence paths without claiming K&C
calibration.

```powershell
git add tests/test_integration_lsprepost.py docs/ROADMAP.zh-CN.md
git commit -m "test: qualify phase15 conforming air-gap workflow"
```

## Final Verification

Run:

```powershell
python -m unittest discover -s tests
python -m compileall -q .\lsprepost_mcp
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\pack.ps1
```

Confirm:

- all tests pass, with only documented opt-in skips;
- package path scanning reports no local absolute-path leak;
- old project inventories are unchanged;
- the new K file passes static and LS-PrePost import validation;
- LS-Run output is recovered into an immutable evidence manifest;
- propagation is qualified numerically before visual claims;
- LS-PrePost displays the pressure wave entering concrete.
