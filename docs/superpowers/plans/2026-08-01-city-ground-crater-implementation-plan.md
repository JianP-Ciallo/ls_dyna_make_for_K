# City Ground Crater Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the opt-in `city_ground_crater_v1` city mode, generate an LS-DYNA deck with ALE-to-eroding-ground coupling, and produce a test project under `E:\K文件模型` without changing legacy city behavior.

**Architecture:** Keep scene assembly in `city_street_blast.py`, but move crater specification, solid-ground meshing, ground keyword cards, and ground metadata into a focused `city_ground_crater.py` module. Reuse the controlled Phase15 K&C preset through an ID-parameterized renderer, add crater-specific static and solver evidence gates, and expose only the closed preset controls in the existing Phase17 Web editor.

**Tech Stack:** Python 3 standard library, LS-DYNA keyword generation, LS-PrePost import validation, unittest, vanilla JavaScript/HTML/CSS.

## Global Constraints

- `ground_response` is opt-in; an absent block preserves legacy fixed-shell ground output byte-for-byte except for unrelated existing changes.
- Capability name is exactly `city_ground_crater_v1`; mode is exactly `validation_crater`.
- Allowed local mesh sizes are `0.20`, `0.15`, and `0.10 m`; allowed requested overlap layers are `5` and `7`.
- Central ground uses `kc_a1_automatic_reference`, `NOUT=2`, and erosion preset `standard_observation` with maximum principal strain `0.05`.
- Peripheral/support ground uses `*MAT_ELASTIC`: density `2400 kg/m^3`, Young's modulus `3.0e10 Pa`, Poisson ratio `0.20`.
- Eroding ground uses CLIS `CTYPE=5`; exposed non-eroding ground and each required city object use independent `CTYPE=4` interfaces.
- A generated deck or normal solver termination is not acceptance without propagation, damage, erosion, crater, numerical-quality, and immutable-evidence gates.
- Existing generated projects and result directories are not overwritten.
- The final test deck is generated into a new directory below `E:\K文件模型`.

---

### Task 1: Crater Specification and Derived Geometry

**Files:**
- Create: `lsprepost_mcp/city_ground_crater.py`
- Modify: `lsprepost_mcp/city_street_blast.py`
- Test: `tests/test_city_ground_crater.py`

**Interfaces:**
- Produces: `default_ground_response() -> JSONDict`
- Produces: `normalize_ground_response(value, *, source_center_m, domain_bounds_m, foundation_bounds, mesh_size_m) -> JSONDict | None`
- Produces: normalized fields `actual_ale_overlap_layers`, `ale_overlap_depth_m`, `eroding_zone_half_width_m`, `eroding_ground_depth_m`, `support_depth_m`, and `total_ground_depth_m`.

- [ ] **Step 1: Write failing normalization tests**

```python
def test_crater_defaults_resolve_mesh_aligned_depths():
    spec = crater_spec("unit_crater_defaults")
    resolved = validate_city_street_blast_spec(spec)["ground_response"]
    assert resolved["actual_ale_overlap_layers"] == 5
    assert resolved["ale_overlap_depth_m"] == 1.0
    assert resolved["eroding_zone_half_width_m"] == 3.0

def test_crater_rejects_foundation_intersection():
    spec = crater_spec("unit_crater_foundation")
    spec["explosive"]["base_center_m"] = [-30.0, 16.0, 0.01]
    with self.assertRaisesRegex(ValueError, "crater_zone_intersects_foundation"):
        validate_city_street_blast_spec(spec)
```

- [ ] **Step 2: Run the focused test and verify failure**

```powershell
python -m unittest tests.test_city_ground_crater -v
```

Expected: import or missing-field failure.

- [ ] **Step 3: Implement strict normalization and integrate it before ALE bounds validation**

```python
actual_layers = max(
    requested_layers,
    math.ceil(anticipated_depth / mesh_size_m) + 2,
    4,
)
overlap_depth = actual_layers * mesh_size_m
raw_half_width = max(3.0, 2.0 * anticipated_depth + 4.0 * mesh_size_m)
half_width = math.ceil(raw_half_width / mesh_size_m) * mesh_size_m
```

Reject unknown properties, non-finite values, unsupported presets, invalid source clearance, and custom erosion unless `confirmed_by_user is True`.

- [ ] **Step 4: Run focused and legacy city tests**

```powershell
python -m unittest tests.test_city_ground_crater tests.test_city_street_blast -v
```

- [ ] **Step 5: Commit the task**

```powershell
git add lsprepost_mcp/city_ground_crater.py lsprepost_mcp/city_street_blast.py tests/test_city_ground_crater.py
git commit -m "feat: normalize city crater specifications"
```

### Task 2: Reusable K&C Material Rendering

**Files:**
- Modify: `lsprepost_mcp/phase15_materials.py`
- Test: `tests/test_phase15_materials.py`
- Test: `tests/test_city_ground_crater.py`

**Interfaces:**
- Produces: `render_phase15_material_cards(raw, *, material_ids=None, eos_ids=None) -> tuple[list[str], JSONDict]`
- Consumes: city IDs for air, TNT, K&C ground, and steel without rewriting card text.

- [ ] **Step 1: Write a failing custom-ID rendering test**

```python
lines, metadata = render_phase15_material_cards(
    materials,
    material_ids={"air": 1, "tnt": 2, "concrete": 90, "steel_hoop": 4},
    eos_ids={"air": 1, "tnt": 2},
)
assert metadata["material_ids"]["concrete"] == 90
assert "90,0,0,0,0,0,1,1" in lines
```

- [ ] **Step 2: Verify the test fails before implementation**

```powershell
python -m unittest tests.test_phase15_materials -v
```

- [ ] **Step 3: Parameterize IDs while retaining exact legacy defaults**

Use immutable default mappings and replace every hard-coded material/EOS ID in the renderer. Validate positive unique integer IDs and keep the no-argument output unchanged.

- [ ] **Step 4: Run Phase15 and crater material tests**

```powershell
python -m unittest tests.test_phase15_materials tests.test_phase15_keyword tests.test_city_ground_crater -v
```

- [ ] **Step 5: Commit the task**

```powershell
git add lsprepost_mcp/phase15_materials.py tests/test_phase15_materials.py tests/test_city_ground_crater.py
git commit -m "refactor: parameterize controlled KC material ids"
```

### Task 3: Connected Solid Ground and Coupling Cards

**Files:**
- Modify: `lsprepost_mcp/city_ground_crater.py`
- Modify: `lsprepost_mcp/city_street_blast.py`
- Test: `tests/test_city_ground_crater.py`

**Interfaces:**
- Produces: `build_ground_crater_model(...) -> GroundCraterModel`
- `GroundCraterModel` contains nodes, solids, parts, exposed segments, eroding part set, support boundaries, anchor nodes, history sets, and metadata.
- Produces: `render_ground_crater_cards(model) -> list[str]`.

- [ ] **Step 1: Write failing mesh/topology tests**

```python
keyword, metadata = build_city_street_blast_keyword(crater_spec("unit_crater_mesh"))
ground = metadata["ground_response"]
assert ground["solid_element_count"] > 0
assert ground["eroding_fsi"]["ctype"] == 5
assert ground["eroding_fsi"]["slave_part_ids"] == [ground["eroding_part_id"]]
assert ground["peripheral_fsi"]["ctype"] == 4
assert ground["duplicate_fsi_face_count"] == 0
assert ground["minimum_initial_solid_volume_m3"] > 0.0
```

Add mutation tests for a covered foundation face, duplicate FSI face, fixed eroding part, and source movement without regenerated fingerprints.

- [ ] **Step 2: Verify the topology tests fail**

```powershell
python -m unittest tests.test_city_ground_crater -v
```

- [ ] **Step 3: Build a source-aligned shared-node hexa mesh**

Use the ALE X/Y axes and a uniform `h` ground Z axis. Assign top columns to existing road/foundation PIDs, override the central square with eroding PID `90`, and assign the lower support to PID `92`. Skip legacy road/foundation shell generation while reserving their IDs so building/facility IDs remain stable.

- [ ] **Step 4: Render explicit FSI, support, history, and output cards**

```text
*CONSTRAINED_LAGRANGE_IN_SOLID    $ central part set, CTYPE=5
*CONSTRAINED_LAGRANGE_IN_SOLID    $ exposed peripheral segments, CTYPE=4
*BOUNDARY_NON_REFLECTING           $ ground side and bottom segments
*DATABASE_EXTENT_BINARY            $ solid stress/history variables
*DATABASE_HISTORY_SOLID_SET        $ K&C probe solids
*DATABASE_HISTORY_NODE_SET         $ surface and guard nodes
```

Remove the legacy ALE `z=0` reflection SPC in crater mode. Keep three support-layer anchor sets with XYZ, YZ, and Z constraints.

- [ ] **Step 5: Tie fixed-facility bases to the ground top surface**

Render one `*CONTACT_TIED_NODES_TO_SURFACE` per building/fixed facility using its base-node set as slave and its footprint-clipped ground top segment set as master. Crater mode must not place these base nodes in `FIXED_URBAN_NODE_SET_ID`.

- [ ] **Step 6: Run city, Phase15, and keyword tests**

```powershell
python -m unittest tests.test_city_ground_crater tests.test_city_street_blast tests.test_keyword_checks tests.test_phase15_keyword -v
```

- [ ] **Step 7: Commit the task**

```powershell
git add lsprepost_mcp/city_ground_crater.py lsprepost_mcp/city_street_blast.py tests/test_city_ground_crater.py
git commit -m "feat: generate eroding solid city ground"
```

### Task 4: Static Validation and Preflight Gates

**Files:**
- Modify: `lsprepost_mcp/keyword_checks.py`
- Modify: `lsprepost_mcp/validation_profiles.py`
- Modify: `lsprepost_mcp/preflight.py`
- Test: `tests/test_city_ground_crater.py`
- Test: `tests/test_keyword_checks.py`
- Test: `tests/test_validation_profiles.py`

**Interfaces:**
- Produces: `check_city_ground_crater_contract(keyword, spec, metadata, model, add) -> None`
- Produces validation capability `city_ground_crater_v1` and named quality checks.

- [ ] **Step 1: Write failing contract-mutation tests**

```python
checks = keyword_quality_checks(mutated_keyword, spec, metadata)
assert failed(checks, "quality.city_crater.eroding_ctype5")
assert failed(checks, "quality.city_crater.no_duplicate_fsi_faces")
assert failed(checks, "quality.city_crater.foundation_exclusion")
assert failed(checks, "quality.city_crater.anchor_scope")
```

- [ ] **Step 2: Verify mutation tests fail for the intended missing checks**

```powershell
python -m unittest tests.test_city_ground_crater tests.test_keyword_checks -v
```

- [ ] **Step 3: Implement model-backed checks and element/output estimates**

Validate actual part/set/card references from parsed keyword data, not metadata alone. Include ground nodes/elements and expected d3plot history in preflight estimates.

- [ ] **Step 4: Run validation suites**

```powershell
python -m unittest tests.test_city_ground_crater tests.test_keyword_checks tests.test_validation_profiles -v
```

- [ ] **Step 5: Commit the task**

```powershell
git add lsprepost_mcp/keyword_checks.py lsprepost_mcp/validation_profiles.py lsprepost_mcp/preflight.py tests/test_city_ground_crater.py tests/test_keyword_checks.py tests/test_validation_profiles.py
git commit -m "feat: gate city crater keyword topology"
```

### Task 5: Solver Evidence and Crater Acceptance

**Files:**
- Create: `lsprepost_mcp/city_crater_results.py`
- Create: `templates/cfile/city_ground_crater_results.cfile`
- Modify: `lsprepost_mcp/cfile.py`
- Modify: `lsprepost_mcp/lsdyna_runner.py`
- Modify: `lsprepost_mcp/city_impact.py`
- Modify: `lsprepost_mcp/run_evidence.py`
- Test: `tests/test_city_crater_results.py`
- Test: `tests/test_lsdyna_runner.py`
- Test: `tests/test_city_impact.py`

**Interfaces:**
- Produces: `evaluate_city_ground_crater(project_path, run_dir, *, result_payload=None) -> JSONDict`
- Produces: `ground_crater_metrics.json` and `ground_crater_acceptance.json` bound to the run evidence manifest.

- [ ] **Step 1: Write synthetic-history failure tests**

Cover missing DBFSI rise, unreadable K&C damage, no deleted element, disconnected erosion, protected-boundary deletion, no negative-Z response, reflected-wave ordering, and short observation window.

- [ ] **Step 2: Verify tests fail before evaluator implementation**

```powershell
python -m unittest tests.test_city_crater_results -v
```

- [ ] **Step 3: Implement deterministic metrics and gate evaluation**

```python
accepted = all([
    propagation["ok"],
    damage["ok"],
    crater["ok"],
    displacement["ok"],
    numerical_quality["ok"],
    evidence["ok"],
])
```

Measure crater depth from initial `z=0` to the deepest newly exposed intact face and diameter from the deleted top-column X/Y footprint. Reject non-finite values and do not infer metrics from screenshots.

- [ ] **Step 4: Bind outputs and hashes into run and Phase16 assessment records**

Register the crater as its own semantic object. A global FSI value must not satisfy its object-level evidence.

Generate the four required LS-PrePost views from the controlled cfile template:
`ground_pressure.png`, `ground_principal_stress.png`, `ground_kc_damage.png`, and
`ground_z_displacement.png`. The template accepts only manifest-bound result and
output paths; it cannot accept raw cfile commands.

Add `evaluate_city_crater_sensitivity(runs) -> JSONDict`. It requires the
`0.20/0.15/0.10 m` mesh series for both `5` and `7` requested overlap layers,
rejects material/source drift, and classifies each metric sequence as monotonic,
oscillatory, or divergent.

- [ ] **Step 5: Run focused solver/evidence tests**

```powershell
python -m unittest tests.test_city_crater_results tests.test_lsdyna_runner tests.test_city_impact tests.test_run_evidence -v
```

- [ ] **Step 6: Commit the task**

```powershell
git add lsprepost_mcp/city_crater_results.py templates/cfile/city_ground_crater_results.cfile lsprepost_mcp/cfile.py lsprepost_mcp/lsdyna_runner.py lsprepost_mcp/city_impact.py lsprepost_mcp/run_evidence.py tests/test_city_crater_results.py tests/test_lsdyna_runner.py tests/test_city_impact.py
git commit -m "feat: evaluate city crater solver evidence"
```

### Task 6: Phase17 Web Controls and Preview

**Files:**
- Modify: `lsprepost_mcp/web/static/index.html`
- Modify: `lsprepost_mcp/web/static/phase17_editor.js`
- Modify: `lsprepost_mcp/web/static/styles.css`
- Modify: `lsprepost_mcp/web/draft_preview.py`
- Modify: `lsprepost_mcp/web/preview_mesh.py`
- Test: `tests/test_phase17_draft_preview.py`
- Test: `tests/test_web_static.py`
- Test: `tests/test_phase17_web_e2e_contract.py`

**Interfaces:**
- Produces closed UI payload `ground_response`.
- Produces non-physical preview guides for eroding-zone footprint and ALE lower plane.

- [ ] **Step 1: Write failing Web contract tests**

Assert legacy default omission, validation-crater payload fields, derived readouts, disabled generation on foundation collision, and preview guide roles excluded from physical statistics.

- [ ] **Step 2: Verify Web tests fail**

```powershell
python -m unittest tests.test_phase17_draft_preview tests.test_web_static tests.test_phase17_web_e2e_contract -v
```

- [ ] **Step 3: Add compact controls and derived status**

Use a select for mode, selects for mesh/overlap/preset, numeric anticipated-depth input, and plain derived values. Preserve the existing editor workflow and do not create a separate landing view.

- [ ] **Step 4: Wire payload generation and preview guide geometry**

Only emit `ground_response` when validation crater is selected. The backend remains authoritative and returns normalized dimensions or an explicit failure state.

- [ ] **Step 5: Run Web tests**

```powershell
python -m unittest tests.test_phase17_draft_preview tests.test_web_static tests.test_phase17_web_e2e_contract tests.test_web_project_export -v
```

- [ ] **Step 6: Commit the task**

```powershell
git add lsprepost_mcp/web/static/index.html lsprepost_mcp/web/static/phase17_editor.js lsprepost_mcp/web/static/styles.css lsprepost_mcp/web/draft_preview.py lsprepost_mcp/web/preview_mesh.py tests/test_phase17_draft_preview.py tests/test_web_static.py tests/test_phase17_web_e2e_contract.py
git commit -m "feat: expose city crater controls in phase17"
```

### Task 7: Generate and Validate the Test Deck

**Files:**
- Create: `scripts/generate_city_ground_crater_validation.py`
- Modify: `docs/ROADMAP.zh-CN.md`
- Generate: `E:\K文件模型\web_phase17_city_ground_crater_validation_v1\model.k`
- Generate: `E:\K文件模型\web_phase17_city_ground_crater_validation_v1\model.json`
- Generate: `E:\K文件模型\web_phase17_city_ground_crater_validation_v1\checks.json`

**Interfaces:**
- Consumes: completed generator and validation checks.
- Produces: a new immutable test project for user-run LS-DYNA solving.

- [ ] **Step 1: Run the complete Python regression suite**

```powershell
python -m unittest discover -s tests
python -m compileall -q .\lsprepost_mcp
```

- [ ] **Step 2: Generate the new test project without overwriting an existing directory**

```powershell
python .\scripts\generate_city_ground_crater_validation.py --output-root "E:\K文件模型" --project-name "web_phase17_city_ground_crater_validation_v1"
```

The script calls `default_city_street_blast_spec()`, adds the controlled
`ground_response` block, calls `build_city_street_blast_keyword()`, runs
`keyword_quality_checks()`, and atomically writes `model.k`, `model.json`, and
`checks.json`. It exits nonzero if the output directory exists or any static
gate fails; it never manually concatenates keyword text.

- [ ] **Step 3: Run static gates and LS-PrePost import validation**

```powershell
python -m unittest tests.test_city_ground_crater -v
```

Run the existing controlled LS-PrePost import tool against the generated `model.k`. Require zero keyword reader errors and a non-empty preview artifact.

- [ ] **Step 4: Inspect generated evidence**

Confirm one `CTYPE=5` ground coupling, separate `CTYPE=4` peripheral/object interfaces, K&C and erosion cards, solid ground parts, no legacy ALE ground SPC, ground history/output cards, and `checks.ok=true` with static-only scope.

- [ ] **Step 5: Update the roadmap and commit source changes**

```powershell
git add scripts/generate_city_ground_crater_validation.py docs/ROADMAP.zh-CN.md
git commit -m "docs: record city crater validation capability"
```

- [ ] **Step 6: Report the exact test-project path and remaining solver gate**

The final report must state that LS-PrePost import/static validation is not a real LS-DYNA crater acceptance. Real acceptance remains pending until the generated deck is solved and `ground_crater_acceptance.json` passes.
