# Phase 15 FSI Wave Transfer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a non-empty, correctly oriented 2D concrete/ALE FSI interface and make real LS-DYNA wave transfer into concrete a machine-enforced acceptance condition.

**Architecture:** A focused `phase15_fsi.py` module owns concrete exterior-edge extraction, geometric classification, and Phase 15 response evaluation. `phase15_keyword.py` consumes that topology to emit explicit two-node `*SET_SEGMENT_TITLE` cards with `SSTYP=2`; `lsdyna_runner.py` recognizes the Phase 15 model variant and fail-closes on the generated wave-transfer report.

**Tech Stack:** Python standard library, LS-DYNA R12 keywords, `unittest`, existing JSON project/run records.

## Global Constraints

- Preserve the existing 2D axisymmetric MM-ALE/K&C model and SI unit system.
- Do not treat normal solver termination, non-empty `dbfsi`, or static validation as proof of wave transfer.
- Keep `NQUAD=4`, `DIREC=2`, and `MCOUP=1`.
- Use `CTYPE=4` without concrete erosion and `CTYPE=5` with erosion.
- A Phase 15 run is accepted only when slave segment count is positive and concrete pressure/stress responses are finite and non-zero.
- K&C scaled damage must be readable and finite; scaled damage greater than zero is reported but is not required for wave-transfer acceptance.
- Do not overwrite prior Phase 15 projects or solver runs.
- Use only Python standard-library dependencies in distributable source.

---

### Task 1: Extract and validate the three concrete FSI line surfaces

**Files:**
- Create: `lsprepost_mcp/phase15_fsi.py`
- Create: `tests/test_phase15_fsi.py`

**Interfaces:**
- Consumes: merged Phase 15 concrete elements as `list[list[int]]`, node coordinates as `dict[int, tuple[float, float, float]]`, and geometry as `JSONDict`.
- Produces: `build_phase15_fsi_surfaces(...) -> JSONDict` with `charge_bottom`, `borehole_wall`, `concrete_top`, `all_segments`, and counts.

- [ ] **Step 1: Write failing topology tests**

Add tests that compile the default resolved Phase 15 mesh and assert:

```python
surfaces = build_phase15_fsi_surfaces(
    concrete_elements,
    node_coordinates,
    model["geometry"],
    mesh_size_m=float(model["mesh_size_m"]),
)
self.assertGreater(len(surfaces["charge_bottom"]), 0)
self.assertGreater(len(surfaces["borehole_wall"]), 0)
self.assertGreater(len(surfaces["concrete_top"]), 0)
self.assertEqual(
    len(surfaces["all_segments"]),
    sum(len(surfaces[name]) for name in FSI_SURFACE_NAMES),
)
```

Also assert every normalized edge occurs once, every segment has two distinct nodes, each named surface is connected, and an intentionally injected interior edge is rejected.

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```powershell
python -m unittest tests.test_phase15_fsi -v
```

Expected: import failure because `lsprepost_mcp.phase15_fsi` does not exist.

- [ ] **Step 3: Implement exterior-edge extraction**

Create these public names:

```python
FSI_SURFACE_NAMES = ("charge_bottom", "borehole_wall", "concrete_top")

def build_phase15_fsi_surfaces(
    concrete_elements: list[list[int]],
    node_coordinates: dict[int, tuple[float, float, float]],
    geometry: JSONDict,
    *,
    mesh_size_m: float,
) -> JSONDict:
    ...

def validate_phase15_fsi_surfaces(
    surfaces: JSONDict,
    concrete_elements: list[list[int]],
    node_coordinates: dict[int, tuple[float, float, float]],
    geometry: JSONDict,
    *,
    mesh_size_m: float,
) -> list[JSONDict]:
    ...
```

Count undirected edges `(n1,n2)`, `(n2,n3)`, `(n3,n4)`, `(n4,n1)` from concrete quads. Only count-one edges are eligible. Classify by midpoint and endpoint coordinates using:

```python
tolerance = max(1.0e-10, mesh_size_m * 1.0e-6)
```

Geometry rules:

```python
charge_bottom:
    z == charge_bottom_z_m and 0 <= r <= charge_radius_m
borehole_wall:
    r == charge_radius_m and charge_bottom_z_m <= z <= target_top_z_m
concrete_top:
    z == target_top_z_m and charge_radius_m <= r <= target_radius_m
```

Orient segments so the right-hand in-plane normal `(dz, -dr)` points toward ALE:

```python
charge_bottom expected normal: (0.0, +1.0)
borehole_wall expected normal: (-1.0, 0.0)
concrete_top expected normal: (0.0, +1.0)
```

Reverse `(n1, n2)` when its dot product with the expected normal is negative.

- [ ] **Step 4: Implement fail-closed validation**

Return stable issue IDs:

```text
fsi_surface_missing
fsi_segment_invalid_node
fsi_segment_not_exterior
fsi_segment_duplicate
fsi_surface_disconnected
fsi_surface_geometry_mismatch
fsi_surface_normal_mismatch
```

Reject any issue before keyword generation.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m unittest tests.test_phase15_fsi -v
```

Expected: all topology tests pass.

---

### Task 2: Emit explicit 2D segment sets and select K&C damage output

**Files:**
- Modify: `lsprepost_mcp/phase15_keyword.py`
- Modify: `lsprepost_mcp/phase15_materials.py`
- Modify: `tests/test_phase15_keyword.py`
- Modify: `tests/test_phase15_materials.py`

**Interfaces:**
- Consumes: `build_phase15_fsi_surfaces()` from Task 1.
- Produces: three explicit two-node segment sets and FSI cards with `SSTYP=2`; K&C card with `NOUT=2`.

- [ ] **Step 1: Add failing keyword tests**

Assert the compiled model exposes:

```python
surfaces = model["interfaces"]["fsi_surfaces"]
self.assertGreater(surfaces["counts"]["charge_bottom"], 0)
self.assertGreater(surfaces["counts"]["borehole_wall"], 0)
self.assertGreater(surfaces["counts"]["concrete_top"], 0)
```

Assert keyword cards contain three titled segment sets and that the FSI first card uses a controlled combined segment-set ID with `SSTYP=2`, not `slave=3,SSTYP=1`.

Assert each segment data row has exactly two positive node IDs.

- [ ] **Step 2: Add failing K&C output test**

Parse the first data row following:

```text
$# slambda      nout     edrop ...
```

Assert field 2 is `2`.

- [ ] **Step 3: Run tests and verify failure**

Run:

```powershell
python -m unittest tests.test_phase15_keyword tests.test_phase15_materials -v
```

Expected: failures for missing FSI surfaces and blank `NOUT`.

- [ ] **Step 4: Integrate FSI surfaces into the solver model**

In `compile_phase15_a1_solver_model()`:

```python
fsi_surfaces = build_phase15_fsi_surfaces(
    concrete_elements,
    node_coordinates,
    plan["geometry"],
    mesh_size_m=float(plan["mesh_size_m"]),
)
```

Store named segments, counts, expected normals, and total count under:

```python
result["interfaces"]["fsi_surfaces"]
```

Extend `validate_phase15_a1_solver_model()` with the fail-closed surface validator and a positive total-count check.

- [ ] **Step 5: Render the three sets and their union**

Define unique IDs in `phase15_keyword.py`:

```python
FSI_CHARGE_BOTTOM_SET_ID = 15101
FSI_BOREHOLE_WALL_SET_ID = 15102
FSI_CONCRETE_TOP_SET_ID = 15103
FSI_ALL_CONCRETE_ALE_SET_ID = 15110
```

Add:

```python
def _append_2d_segment_set(
    lines: list[str],
    set_id: int,
    title: str,
    segments: list[list[int]],
) -> None:
    ...
```

Emit each line as free-format `n1,n2`. Emit `*SET_SEGMENT_ADD` for the union. Change the FSI card to:

```python
f"{FSI_ALL_CONCRETE_ALE_SET_ID},{ALE_PART_SET_ID},2,0,4,{fsi_ctype},2,1"
```

- [ ] **Step 6: Set `NOUT=2`**

Change the controlled concrete preset to include:

```python
"nout": 2,
```

Require exactly `2` in `validate_phase15_materials()` and render it in the second field of Material Card 3. Record:

```python
"kc_output": {
    "nout": 2,
    "elout_field": "plastic_strain",
    "interpretation": "scaled_damage_measure",
}
```

- [ ] **Step 7: Run keyword and material tests**

Run:

```powershell
python -m unittest tests.test_phase15_keyword tests.test_phase15_materials -v
```

Expected: all tests pass.

- [ ] **Step 8: Run an LS-DYNA initialization smoke**

Generate a new project, then execute:

```powershell
python -m unittest tests.test_phase15_prerequisites -v
```

Run the existing initialization-smoke entry point against:

```text
E:\dyna\25-26-2土木工程数值模拟技术-教学资料\4.求解器\R12\lsdyna.exe
```

Expected: normal initialization and `d3hsp` reports a positive FSI slave-segment count. If two-node free-format segment rows are rejected, correct only `_append_2d_segment_set()` according to the R12 diagnostic and repeat.

---

### Task 3: Parse FSI initialization and concrete response evidence

**Files:**
- Modify: `lsprepost_mcp/solver_results.py`
- Modify: `lsprepost_mcp/phase15_fsi.py`
- Modify: `tests/test_solver_results.py`
- Modify: `tests/test_phase15_fsi.py`

**Interfaces:**
- Produces: `parse_fsi_interfaces(text: str) -> JSONDict`.
- Produces: `parse_phase15_elout(path: Path, concrete_element_ids: set[int]) -> JSONDict`.
- Produces: `evaluate_phase15_wave_transfer(run_dir: Path, probe_element_ids: set[int]) -> JSONDict`.

- [ ] **Step 1: Add failing `d3hsp` parser tests**

Use fixtures containing:

```text
FSI Interface ID 1
number of slave segments for coupling = 0
```

and:

```text
FSI Interface ID 1
number of slave segments for coupling = 243
```

Assert zero is parsed but rejected, positive is accepted, and a missing interface is not treated as zero or success.

- [ ] **Step 2: Implement `parse_fsi_interfaces()`**

Return:

```python
{
    "interface_count": int,
    "interfaces": [
        {"interface_id": int | None, "slave_segment_count": int}
    ],
    "total_slave_segment_count": int,
    "all_nonempty": bool,
}
```

Only parse the exact `number of slave segments for coupling` diagnostic.

- [ ] **Step 3: Add failing ELOUT parser tests**

Create a small fixture with two states and one concrete element:

```text
element  materl(global)
  11153-      3
1- 15 elastic  0 0 0 0 0 0 0
...
  11153-      3
1- 15 plastic -3.0E+06 -2.0E+06 -1.0E+06 5.0E+05 0 0 2.0E-02
```

Assert:

- hydrostatic pressure is `2.0e6 Pa`;
- principal stresses are finite and non-zero;
- scaled damage is readable as `0.02`;
- all-zero stress fails response gates but passes damage readability when scaled damage is finite;
- missing `elout`, missing probe rows, and NaN values fail closed.

- [ ] **Step 4: Implement streaming ELOUT parsing**

Do not load the production ELOUT into memory. Parse line by line and keep only requested concrete probes.

For the axisymmetric stress tensor:

```python
mean = 0.5 * (sigma_xx + sigma_yy)
radius = math.sqrt((0.5 * (sigma_xx - sigma_yy)) ** 2 + sigma_xy ** 2)
principal = sorted((mean + radius, mean - radius, sigma_zz), reverse=True)
hydrostatic_pressure = -(sigma_xx + sigma_yy + sigma_zz) / 3.0
```

Compute response relative to each probe's first state. Use:

```python
PHASE15_STRESS_RESPONSE_FLOOR_PA = 1.0e3
```

as the absolute numerical-noise floor.

- [ ] **Step 5: Implement the wave-transfer evaluator**

Required checks:

```text
fsi_interfaces_present
fsi_slave_segments_nonzero
concrete_probe_states_present
concrete_stress_values_finite
concrete_hydrostatic_pressure_response
concrete_principal_stress_response
kc_scaled_damage_readable
kc_scaled_damage_finite
```

Return `wave_transfer_verified=True` only when every required check passes. Report `kc_scaled_damage_positive` separately without including it in the required conjunction.

- [ ] **Step 6: Run parser/evaluator tests**

Run:

```powershell
python -m unittest tests.test_solver_results tests.test_phase15_fsi -v
```

Expected: all tests pass.

---

### Task 4: Make the LS-DYNA runner fail closed for Phase 15

**Files:**
- Modify: `lsprepost_mcp/lsdyna_runner.py`
- Modify: `tests/test_lsdyna_runner.py`

**Interfaces:**
- Consumes: `evaluate_phase15_wave_transfer()` from Task 3.
- Produces: `result_variant="phase15_axisymmetric_blast"` and `wave_transfer_acceptance` in `run.json`.

- [ ] **Step 1: Add failing variant and acceptance tests**

Create a model record with:

```python
{"spec": {"model_type": "phase15_axisymmetric_blast"}}
```

Assert `_result_variant()` returns `phase15_axisymmetric_blast`.

Mock a completed solver run with normal termination but a zero FSI segment fixture. Assert:

```python
self.assertFalse(result["ok"])
self.assertFalse(result["wave_transfer_acceptance"]["wave_transfer_verified"])
```

Mock positive FSI and concrete response fixtures and assert the run is accepted.

- [ ] **Step 2: Add Phase 15 variant detection**

Change `_result_variant()` to distinguish:

```text
standard
ale_blast
phase15_axisymmetric_blast
```

- [ ] **Step 3: Integrate acceptance into new and refreshed records**

After ordinary solver evaluation:

```python
if result_variant == "phase15_axisymmetric_blast":
    acceptance = evaluate_phase15_wave_transfer(
        run_dir,
        probe_element_ids=_phase15_probe_element_ids(project),
    )
    record["wave_transfer_acceptance"] = acceptance
    required_outputs_ok = required_outputs_ok and acceptance["wave_transfer_verified"]
```

Apply the same logic in `_refresh_terminal_record()` so `latest_lsdyna_run()` cannot revive a failed Phase 15 run based only on normal termination.

Write the standalone report atomically to:

```text
<run_dir>/wave_transfer_acceptance.json
```

- [ ] **Step 4: Run runner tests**

Run:

```powershell
python -m unittest tests.test_lsdyna_runner -v
```

Expected: all tests pass.

---

### Task 5: Complete regression and real LS-DYNA acceptance

**Files:**
- Modify only if required by observed R12 diagnostics:
  - `lsprepost_mcp/phase15_fsi.py`
  - `lsprepost_mcp/phase15_keyword.py`
  - `lsprepost_mcp/phase15_materials.py`
  - `lsprepost_mcp/solver_results.py`
  - `lsprepost_mcp/lsdyna_runner.py`
- Generate runtime evidence under a new `workspace/projects/phase15_*` project; do not commit runtime output.

**Interfaces:**
- Produces: a real `wave_transfer_acceptance.json` with `wave_transfer_verified=true`.

- [ ] **Step 1: Run the focused Phase 15 suite**

Run:

```powershell
python -m unittest tests.test_phase15_fsi tests.test_phase15_keyword tests.test_phase15_materials tests.test_phase15_prerequisites tests.test_solver_results tests.test_lsdyna_runner -v
```

Expected: all focused tests pass.

- [ ] **Step 2: Run the full unit suite and compile check**

Run:

```powershell
python -m unittest discover -s tests
python -m compileall -q .\lsprepost_mcp
```

Expected: all tests pass, optional external integrations may remain skipped, compile check has no output.

- [ ] **Step 3: Generate a new acceptance project**

Use project name:

```text
phase15_a1_kc_axisymmetric_fsi_fixed
```

Use `if_exists="error"` and the existing controlled A-1 input with `consistency_mode="mass_priority_adjust_length"`.

- [ ] **Step 4: Run initialization acceptance**

Run R12 initialization and inspect `d3hsp`.

Required evidence:

```text
total_slave_segment_count > 0
all_nonempty == true
```

Do not start the full solve until this passes.

- [ ] **Step 5: Run a real LS-DYNA solve**

Use:

```text
solver: E:\dyna\25-26-2土木工程数值模拟技术-教学资料\4.求解器\R12\lsdyna.exe
ncpu: 4
memory: 2g
timeout_s: 7200
```

Keep solver output in the new run directory and wait for completion.

- [ ] **Step 6: Verify the hard acceptance report**

Require:

```python
assert report["wave_transfer_verified"] is True
assert report["fsi"]["total_slave_segment_count"] > 0
assert report["concrete_response"]["peak_hydrostatic_pressure_response_pa"] > 1.0e3
assert report["concrete_response"]["peak_principal_stress_response_pa"] > 1.0e3
assert report["kc_scaled_damage"]["readable"] is True
```

Record whether scaled damage became positive without making it a mandatory transfer gate.

- [ ] **Step 7: Inspect solver diagnostics**

Review `d3hsp`, `messag`, `glstat`, and `matsum` for error termination, NaN/Infinity, negative volume, excessive hourglass energy, and FSI leakage warnings. A passing transfer report does not waive these solver-quality checks.

- [ ] **Step 8: Review the final diff**

Run:

```powershell
git diff -- lsprepost_mcp/phase15_fsi.py lsprepost_mcp/phase15_keyword.py lsprepost_mcp/phase15_materials.py lsprepost_mcp/solver_results.py lsprepost_mcp/lsdyna_runner.py tests/test_phase15_fsi.py tests/test_phase15_keyword.py tests/test_phase15_materials.py tests/test_solver_results.py tests/test_lsdyna_runner.py
git diff --check
```

Expected: only Phase 15 FSI and acceptance changes; no whitespace errors.

