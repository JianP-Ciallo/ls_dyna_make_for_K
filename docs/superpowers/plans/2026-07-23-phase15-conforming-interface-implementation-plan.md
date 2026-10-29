# Phase 15 Conforming Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a zero-gap, zero-overlap, shared-node ALE/K&C interface mode to Phase 15 while preserving the configurable immersed CLIS mode and its solver output.

**Architecture:** `phase15.py` resolves the coupling mode and builds mode-specific physical regions. A new `phase15_conforming.py` module owns shared-interface topology and geometric validation. `phase15_keyword.py` assembles either the existing immersed CLIS deck or the new shared-node deck, and the LS-DYNA runner dispatches to mode-specific acceptance logic.

**Tech Stack:** Python standard library, LS-DYNA R12 2D axisymmetric ALE and Lagrangian shell formulations, JSON project records, `unittest`.

## Global Constraints

- Preserve `immersed_clis`, including configurable `fsi_overlap_layers` values from 1 through 3.
- New Phase 15 projects default to `conforming_shared_nodes`.
- Existing project records without `coupling_mode` resolve to `immersed_clis`.
- Conforming mode has no ALE elements inside concrete, no CLIS card, and no CLIS slave-segment acceptance requirement.
- Conforming ALE and concrete interface nodes use identical node IDs.
- Static validation alone and normal solver termination do not prove pressure transfer.
- Do not mix coupling modes in convergence evidence.
- Do not overwrite existing runtime projects or solver runs.
- Use only Python standard-library dependencies in distributable source.

---

### Task 1: Resolve Coupling Mode Without Regressing Immersed CLIS

**Files:**
- Modify: `lsprepost_mcp/phase15.py`
- Modify: `lsprepost_mcp/tool_generation.py`
- Test: `tests/test_phase15_prerequisites.py`
- Test: `tests/test_phase15_keyword.py`

**Interfaces:**
- Produces: `resolve_phase15_coupling_mode(inputs: JSONDict, *, legacy_default: bool = False) -> str`.
- Produces: input field `coupling_mode` with values `conforming_shared_nodes` and `immersed_clis`.
- Preserves: `resolve_phase15_fsi_overlap_layers(inputs) -> int` for immersed mode.

- [ ] **Step 1: Add failing resolver and schema tests**

Add tests that assert:

```python
self.assertEqual(
    resolve_phase15_coupling_mode({"coupling_mode": "conforming_shared_nodes"}),
    "conforming_shared_nodes",
)
self.assertEqual(
    resolve_phase15_coupling_mode({"coupling_mode": "immersed_clis"}),
    "immersed_clis",
)
self.assertEqual(
    resolve_phase15_coupling_mode({}, legacy_default=True),
    "immersed_clis",
)
with self.assertRaisesRegex(ValueError, "coupling_mode"):
    resolve_phase15_coupling_mode({"coupling_mode": "unknown"})
```

Assert `phase15_a1_input_schema()` exposes a strict enum and that unknown top-level arguments remain rejected.
Update pre-existing overlap-focused fixtures to pass
`"coupling_mode": "immersed_clis"` explicitly; do not change their expected
layer counts or keyword cards.

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```powershell
python -m unittest tests.test_phase15_prerequisites tests.test_phase15_keyword -v
```

Expected: failures because the mode resolver and schema field do not exist.

- [ ] **Step 3: Implement strict mode resolution**

Add to `phase15.py`:

```python
PHASE15_COUPLING_MODES = ("conforming_shared_nodes", "immersed_clis")
DEFAULT_PHASE15_COUPLING_MODE = "conforming_shared_nodes"

def resolve_phase15_coupling_mode(
    inputs: JSONDict,
    *,
    legacy_default: bool = False,
) -> str:
    default = "immersed_clis" if legacy_default else DEFAULT_PHASE15_COUPLING_MODE
    value = inputs.get("coupling_mode", default)
    if not isinstance(value, str) or value not in PHASE15_COUPLING_MODES:
        raise ValueError(
            "coupling_mode must be conforming_shared_nodes or immersed_clis"
        )
    return value
```

Add the new default to `default_phase15_a1_inputs()`.

- [ ] **Step 4: Extend tool schemas and argument copying**

Add this property to `phase15_a1_input_schema()`:

```python
"coupling_mode": {
    "type": "string",
    "enum": ["conforming_shared_nodes", "immersed_clis"],
    "default": "conforming_shared_nodes",
}
```

Copy `coupling_mode` in both preparation and generation tools. Only resolve
`fsi_overlap_layers` when the selected mode is `immersed_clis`; reject an
explicit `fsi_overlap_layers` argument in conforming mode with
`"fsi_overlap_layers is only valid for immersed_clis"`.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m unittest tests.test_phase15_prerequisites tests.test_phase15_keyword -v
```

Expected: all existing immersed tests and new mode tests pass.

---

### Task 2: Build and Validate the Physical Conforming Regions

**Files:**
- Create: `lsprepost_mcp/phase15_conforming.py`
- Modify: `lsprepost_mcp/phase15.py`
- Create: `tests/test_phase15_conforming.py`

**Interfaces:**
- Produces: `build_phase15_conforming_interface(...) -> JSONDict`.
- Produces: `validate_phase15_conforming_interface(...) -> list[JSONDict]`.
- Consumes: ALE and concrete element lists after final node-ID assembly.

- [ ] **Step 1: Add failing physical-region tests**

Compile a conforming mesh plan and assert:

```python
plan = compile_phase15_a1_mesh_plan(
    {**resolved_inputs, "coupling_mode": "conforming_shared_nodes"}
)
self.assertEqual(plan["fsi_coupling"]["mode"], "conforming_shared_nodes")
self.assertEqual(plan["fsi_coupling"]["overlap_layers"], 0)
self.assertEqual(plan["fsi_coupling"]["overlap_depth_m"], 0.0)
```

For every ALE element centroid `(r, z)`, assert it lies in:

```python
fluid = (
    (r < charge_radius and charge_bottom <= z <= target_top)
    or z >= target_top
)
```

and never in the concrete predicate:

```python
concrete = 0.0 <= r <= target_radius and 0.0 <= z <= target_top and not (
    r < charge_radius and z > charge_bottom
)
```

- [ ] **Step 2: Run the new test and verify failure**

Run:

```powershell
python -m unittest tests.test_phase15_conforming -v
```

Expected: failure because conforming mode still uses immersed overlap geometry.

- [ ] **Step 3: Split mode-specific ALE region generation**

In `compile_phase15_a1_mesh_plan()`, preserve the existing air coordinates and
predicate unchanged under `immersed_clis`. For `conforming_shared_nodes`, use:

```python
air_r = list(concrete_r)
air_z = sorted(
    {
        *_segmented_coordinates([charge_bottom, target_top], mesh_size),
        *_segmented_coordinates([target_top, air_top], mesh_size),
    }
)

def conforming_air(r: float, z: float) -> bool:
    in_borehole = r < charge_radius and charge_bottom <= z < target_top
    above_target = target_top <= z <= air_top
    in_tnt = (
        r < charge_radius
        and charge_bottom < z < charge_top
    )
    return (in_borehole or above_target) and not in_tnt
```

Retain the separate TNT region so its elements complete the ALE mesh in the
charge volume before TNT volume-fraction initialization.

- [ ] **Step 4: Implement conforming topology validation**

Create:

```python
def build_phase15_conforming_interface(
    ale_elements: list[list[int]],
    concrete_elements: list[list[int]],
    node_coordinates: dict[int, tuple[float, float, float]],
    geometry: JSONDict,
    *,
    mesh_size_m: float,
) -> JSONDict:
    ...

def validate_phase15_conforming_interface(
    interface: JSONDict,
    ale_elements: list[list[int]],
    concrete_elements: list[list[int]],
    node_coordinates: dict[int, tuple[float, float, float]],
    geometry: JSONDict,
    *,
    mesh_size_m: float,
) -> list[JSONDict]:
    ...
```

Count normalized edges for each part. Classify common edges as
`charge_bottom`, `borehole_wall`, or `concrete_top` using the same geometry
tolerance and expected normals as `phase15_fsi.py`. Return:

```python
{
    "mode": "conforming_shared_nodes",
    "surfaces": {
        "charge_bottom": [[n1, n2], ...],
        "borehole_wall": [[n1, n2], ...],
        "concrete_top": [[n1, n2], ...],
    },
    "shared_node_ids": [...],
    "shared_node_count": int,
    "geometric_gap_max_m": float,
    "ale_concrete_overlap_area_m2": 0.0,
    "ale_elements_inside_concrete": [],
}
```

Emit stable issue IDs:

```text
conforming_surface_missing
conforming_interface_gap
conforming_interface_nodes_not_shared
conforming_edge_adjacency_invalid
conforming_ale_inside_concrete
conforming_overlap_nonzero
```

- [ ] **Step 5: Run topology tests**

Run:

```powershell
python -m unittest tests.test_phase15_conforming -v
```

Expected: all physical-region tests pass.

---

### Task 3: Assemble Shared Nodes and Emit Mode-Specific Keywords

**Files:**
- Modify: `lsprepost_mcp/phase15_keyword.py`
- Modify: `tests/test_phase15_keyword.py`
- Modify: `tests/test_phase15_conforming.py`

**Interfaces:**
- Consumes: `build_phase15_conforming_interface()`.
- Produces: mode-specific `interfaces` metadata and keyword text.
- Preserves: existing immersed CLIS segment sets and cards byte-for-byte for the same inputs.

- [ ] **Step 1: Add failing shared-node and keyword tests**

For conforming mode assert:

```python
self.assertGreater(model["interfaces"]["shared_node_count"], 0)
self.assertEqual(model["interfaces"]["geometric_gap_max_m"], 0.0)
self.assertEqual(model["interfaces"]["ale_concrete_overlap_area_m2"], 0.0)
self.assertNotIn("*CONSTRAINED_LAGRANGE_IN_SOLID", keyword)
self.assertNotIn("FSI computational overlap", keyword)
```

For each interface edge, assert the node IDs are used by one PID 1 ALE element
and one PID 3 concrete element.

Add an immersed regression assertion:

```python
self.assertIn("*CONSTRAINED_LAGRANGE_IN_SOLID", immersed_keyword)
self.assertEqual(immersed_model["interfaces"]["fsi_coupling"]["overlap_layers"], 2)
self.assertTrue(immersed_model["interfaces"]["fsi_ale_overlap"]["all_two_sided"])
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m unittest tests.test_phase15_keyword tests.test_phase15_conforming -v
```

Expected: conforming tests fail because ALE and concrete currently receive
independent node IDs and CLIS is always emitted.

- [ ] **Step 3: Add coordinate-aware final node assembly**

Add:

```python
def _merge_all_region_nodes(
    regions: list[JSONDict],
    *,
    share_across_families: bool,
    node_id_start: int,
) -> tuple[list[list[float | int]], list[dict[int, int]], int]:
    ...
```

When `share_across_families=False`, delegate to the existing separate ALE and
Lagrange merge path without changing its output. When true, map identical
rounded `(r, z, third)` coordinates across TNT, air, concrete, and steel to the
same final node ID. Use:

```python
key = (round(r, 12), round(z, 12), round(third, 12))
```

Compile all elements after this final mapping.

- [ ] **Step 4: Store mode-specific interface metadata**

For conforming mode store:

```python
"interfaces": {
    "coupling_mode": "conforming_shared_nodes",
    "interface_surfaces": interface["surfaces"],
    "shared_node_ids": interface["shared_node_ids"],
    "shared_node_count": interface["shared_node_count"],
    "geometric_gap_max_m": interface["geometric_gap_max_m"],
    "ale_concrete_overlap_area_m2": 0.0,
    "ale_elements_inside_concrete": [],
}
```

For immersed mode retain current keys and add only:

```python
"coupling_mode": "immersed_clis"
```

- [ ] **Step 5: Branch validation and keyword emission**

In `validate_phase15_a1_solver_model()`, call the conforming validator only for
`conforming_shared_nodes`; call existing surface and two-sided overlap
validation only for `immersed_clis`.

In `build_phase15_a1_keyword()`, emit the three segment sets,
`*SET_SEGMENT_ADD`, and `*CONSTRAINED_LAGRANGE_IN_SOLID` only for
`immersed_clis`. For conforming mode add a comment:

```text
$ Phase15 coupling mode: conforming_shared_nodes; ALE/concrete interface nodes are shared.
```

- [ ] **Step 6: Run keyword tests**

Run:

```powershell
python -m unittest tests.test_phase15_keyword tests.test_phase15_conforming -v
```

Expected: both modes pass and the immersed keyword regression remains intact.

---

### Task 4: Make Tool and Project Metadata Mode-Aware

**Files:**
- Modify: `lsprepost_mcp/tool_generation.py`
- Modify: `tests/test_phase15_prerequisites.py`
- Modify: `tests/test_phase15_keyword.py`

**Interfaces:**
- Produces: explicit `coupling_mode` in preparation summaries, generated specs,
  project metadata, and readiness output.

- [ ] **Step 1: Add failing metadata tests**

Assert preparation and dry-run generation return:

```python
self.assertEqual(
    result["fsi_coupling"]["coupling_mode"],
    "conforming_shared_nodes",
)
self.assertEqual(result["fsi_coupling"]["overlap_layers"], 0)
```

Assert an explicit immersed request reports its requested layer count and the
generated `model.json` records `immersed_clis`.

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```powershell
python -m unittest tests.test_phase15_prerequisites tests.test_phase15_keyword -v
```

Expected: failures because summaries still assume overlap.

- [ ] **Step 3: Return mode-specific summaries**

For conforming mode:

```python
"fsi_coupling": {
    "coupling_mode": "conforming_shared_nodes",
    "overlap_layers": 0,
    "overlap_depth_m": 0.0,
    "shared_node_interface": True,
}
```

For immersed mode:

```python
"fsi_coupling": {
    "coupling_mode": "immersed_clis",
    "overlap_layers": inputs["fsi_overlap_layers"],
    "overlap_depth_m": (
        int(inputs["fsi_overlap_layers"]) * float(inputs["mesh_size_m"])
    ),
    "shared_node_interface": False,
}
```

Record `coupling_mode` under both `spec` and `metadata.phase15`.
Add `coupling_mode` to every item returned by `phase15_sensitivity_matrix()`.
The matrix must be generated for one selected mode at a time and must reject a
list containing both mode values. This prevents later convergence tooling from
silently comparing different coupling formulations.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
python -m unittest tests.test_phase15_prerequisites tests.test_phase15_keyword -v
```

Expected: all metadata tests pass.

---

### Task 5: Dispatch Solver Acceptance by Coupling Mode

**Files:**
- Modify: `lsprepost_mcp/phase15_fsi.py`
- Modify: `lsprepost_mcp/lsdyna_runner.py`
- Modify: `tests/test_phase15_fsi.py`
- Modify: `tests/test_lsdyna_runner.py`

**Interfaces:**
- Preserves: `evaluate_phase15_wave_transfer()` for immersed CLIS.
- Produces: `evaluate_phase15_conforming_wave_transfer(...) -> JSONDict`.
- Produces: mode-aware `_phase15_wave_transfer_acceptance()`.

- [ ] **Step 1: Add failing acceptance-dispatch tests**

Create model records for both modes. Assert:

```python
with patch(
    "lsprepost_mcp.lsdyna_runner.evaluate_phase15_conforming_wave_transfer"
) as conforming:
    _phase15_wave_transfer_acceptance(project, run_dir)
    conforming.assert_called_once()
```

Assert the immersed model still calls `evaluate_phase15_wave_transfer()` and
still fails when CLIS slave segments or `dbfsi` evidence are missing.

- [ ] **Step 2: Add failing conforming evidence tests**

Use small ALE-probe and concrete ELOUT fixtures with ordered arrivals:

```text
ALE source pressure arrival < interface-node motion arrival
< first concrete probe stress arrival < deeper concrete probe arrival
```

Reject reversed order, missing interface nodes, non-finite values, and responses
below the existing stress/pressure noise floors.

- [ ] **Step 3: Implement conforming evaluator**

Add:

```python
def evaluate_phase15_conforming_wave_transfer(
    run_dir: Path,
    *,
    interface_node_ids: set[int],
    concrete_probe_element_ids: set[int],
    ale_probe_element_ids: set[int],
) -> JSONDict:
    ...
```

Return checks:

```text
conforming_interface_nodes_present
ale_pressure_response_valid
interface_motion_response_valid
concrete_pressure_response_valid
concrete_principal_stress_response_valid
source_interface_concrete_arrival_ordered
kc_scaled_damage_readable
kc_scaled_damage_finite
```

Do not require `dbfsi`, `fsifor`, an FSI interface count, or a CLIS slave
segment count.

- [ ] **Step 4: Dispatch by recorded mode**

Read `metadata.phase15.coupling_mode`, falling back to `immersed_clis` for old
projects. Dispatch both initial completion and `_refresh_terminal_record()`
through the same `_phase15_wave_transfer_acceptance()` helper.

For conforming mode, required outputs are `d3plot`, `nodout`, `elout`, and ALE
probe output; `dbfsi` is optional. For immersed mode preserve the current
required-output logic.

- [ ] **Step 5: Run acceptance tests**

Run:

```powershell
python -m unittest tests.test_phase15_fsi tests.test_lsdyna_runner -v
```

Expected: both acceptance modes pass their focused tests.

---

### Task 6: Regression and Real Solver Gate

**Files:**
- Modify only if R12 diagnostics require corrections:
  - `lsprepost_mcp/phase15.py`
  - `lsprepost_mcp/phase15_conforming.py`
  - `lsprepost_mcp/phase15_keyword.py`
  - `lsprepost_mcp/phase15_fsi.py`
  - `lsprepost_mcp/lsdyna_runner.py`
- Runtime output: new `workspace/projects/phase15_*_conforming_*` directories.

**Interfaces:**
- Produces: separate initialization and full-solve evidence for the conforming
  mode without modifying prior immersed runs.

- [ ] **Step 1: Run all Phase 15 tests**

Run:

```powershell
python -m unittest tests.test_phase15_prerequisites tests.test_phase15_materials tests.test_phase15_fsi tests.test_phase15_conforming tests.test_phase15_keyword tests.test_lsdyna_runner -v
```

Expected: all tests pass.

- [ ] **Step 2: Run full regression and compile checks**

Run:

```powershell
python -m unittest discover -s tests
python -m compileall -q .\lsprepost_mcp
```

Expected: all tests pass; optional external integrations may be skipped; compile
check has no output.

- [ ] **Step 3: Generate separate mode projects**

Generate:

```text
phase15_a1_kc_axisymmetric_immersed_regression
phase15_a1_kc_axisymmetric_conforming_init
```

Use `if_exists="error"`. Confirm the immersed project contains CLIS and the
conforming project contains no CLIS.

- [ ] **Step 4: Run R12 conforming initialization**

Require:

```text
normal initialization
no duplicate-node error
no incompatible ALE/Lagrange shared-node error
no negative or zero-area element diagnostic
```

Do not start the full solve if any initialization gate fails.

- [ ] **Step 5: Run the real conforming solve**

Use the configured local R12 solver with a new run directory and wait for
terminal completion. Do not overwrite any immersed run.

- [ ] **Step 6: Verify physical transfer**

Require:

```python
assert report["coupling_mode"] == "conforming_shared_nodes"
assert report["wave_transfer_verified"] is True
assert report["arrival_order"]["ordered"] is True
assert report["concrete_response"]["peak_hydrostatic_pressure_response_pa"] > 1.0e3
assert report["concrete_response"]["peak_principal_stress_response_pa"] > 1.0e3
assert report["kc_scaled_damage"]["readable"] is True
```

Also require acceptable mass, energy, negative-volume, leakage, and solver
termination diagnostics.

- [ ] **Step 7: Review final scope**

Run:

```powershell
git diff --check
git status --short
```

Review only the files named by this plan. Do not clean or revert unrelated
working-tree changes.
