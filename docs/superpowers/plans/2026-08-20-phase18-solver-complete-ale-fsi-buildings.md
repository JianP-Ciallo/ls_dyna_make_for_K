# Phase 18 Solver-Complete ALE/FSI Buildings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate three physically reviewed refined-building models with visible MM-ALE air, movable TNT, real FSI energy transfer, and saved LS-PrePost/R12 1 ms evidence.

**Architecture:** Add an isolated `refined_building.solver_blast` compiler that consumes immutable Phase 18D artifacts plus reviewed physical supplements, then writes a dependency-closed solver deck. Keep the old gravity initializer and neutral Phase 18E provider unchanged; expose the new compiler as a distinct solver-complete provider and workbench option.

**Tech Stack:** Python 3.11+, immutable dataclasses, existing Phase 18D mesh/artifact contracts, streamed LS-DYNA keyword text, MM-ALE/TNT/CLIS patterns already exercised by Phase 14/15, pytest/unittest, vanilla JavaScript workbench, LS-PrePost, LS-DYNA R12.

**Spec:** `docs/superpowers/specs/2026-08-20-phase18-solver-complete-ale-fsi-buildings-design.md`

## Global Constraints

- Unit system is exactly `SI_m_s_kg_N_Pa`.
- Supported built-ins are exactly `commercial_supermarket_detailed_building`, `residential_community_detailed_building`, and `subway_entrance_detailed_building`.
- `Solid`, `Shell`, and `Beam` may coexist only with a recorded physical selection basis and an explicit connection.
- TNT input range is `0.1 <= tnt_equivalent_mass_kg <= 100.0`; default validation mass is `2.0 kg`.
- Charge position must remain in valid air, outside structure/soil, and clear of the far boundary by the computed radius plus local mesh clearance.
- Previous gravity validation output and Phase 18E neutral providers remain unchanged and retain their existing fingerprints.
- Runtime decks are written under `E:\K文件模型\Phase18_三类精细建筑_ALEFSI_20260820`; they are not committed.
- No model is called PASS until LS-PrePost import evidence, R12 mcheck, 1 ms normal termination, positive FSI slave count, and finite TNT-to-air-to-building response are all present.
- `engineering_validated=false` and `requires_project_review=true` remain true.

---

### Task 1: Closed physical-model and blast-scene contracts

**Files:**
- Create: `lsprepost_mcp/refined_building/solver_blast/__init__.py`
- Create: `lsprepost_mcp/refined_building/solver_blast/contracts.py`
- Create: `lsprepost_mcp/refined_building/solver_blast/physical_audit.py`
- Test: `tests/test_phase18_solver_blast_contracts.py`

**Interfaces:**
- Consumes: `BuildingArtifact`, Phase 18D resource ID, source identity.
- Produces: `SolverBlastConfig`, `PhysicalMemberRecord`, `PhysicalBuildingModel`, `SolverBlastScene`; `normalize_solver_blast_config(value) -> SolverBlastConfig`; `audit_physical_building(model) -> tuple[AuditFinding, ...]`.

- [ ] **Step 1: Write failing closed-contract tests**

```python
def test_config_normalizes_default_2kg_movable_charge():
    config = normalize_solver_blast_config({
        "schema_version": "phase18.solver_blast.config@1",
        "unit_system": "SI_m_s_kg_N_Pa",
        "tnt_equivalent_mass_kg": 2.0,
        "charge_position_m": [-2.0, 0.0, 1.5],
        "detonation_time_s": 0.0,
        "air_cell_size_m": 0.40,
        "air_margin_m": [3.0, 3.0, 3.0],
        "termination_time_s": 0.001,
    })
    assert config.tnt_equivalent_mass_kg == 2.0
    assert config.charge_position_m == (-2.0, 0.0, 1.5)

@pytest.mark.parametrize("mass", [0.099, 100.001, float("nan")])
def test_config_rejects_charge_outside_closed_range(mass):
    with pytest.raises(ValueError, match="tnt_equivalent_mass_kg"):
        normalize_solver_blast_config(config_dict(mass=mass))
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_phase18_solver_blast_contracts.py`

Expected: collection fails because `refined_building.solver_blast` does not exist.

- [ ] **Step 3: Implement immutable contracts and exact normalizer**

`contracts.py` defines frozen, slotted dataclasses and rejects missing/extra keys, booleans as numbers, non-finite values, unsupported units, invalid IDs, and invalid bounds. `PhysicalMemberRecord` includes `role`, `element_family`, `material_role`, `dimensions_m`, `selection_basis`, `connection_ids`, and `fluid_exposed`.

- [ ] **Step 4: Implement physical audit**

Audit every part binding and element role. Reject a Beam without section dimensions/orientation, Shell without positive thickness, Solid without positive volume evidence, duplicate role/family assignments, missing connection ownership, and any exterior opaque wall represented only by an unthickened shell.

- [ ] **Step 5: Run GREEN and commit**

Run: `python -m pytest -q tests/test_phase18_solver_blast_contracts.py`

Commit only Task 1 files with `feat: define solver-complete blast contracts`.

### Task 2: Physically reviewed commercial, residential, and subway building supplements

**Files:**
- Create: `lsprepost_mcp/refined_building/solver_blast/physical_building.py`
- Modify: `lsprepost_mcp/refined_building/asset_templates.py`
- Modify: `lsprepost_mcp/refined_building/asset_compiler.py`
- Test: `tests/test_phase18_solver_blast_buildings.py`
- Test: `tests/test_phase18d_commercial_supermarket.py`
- Test: `tests/test_phase18d_residential_subway.py`

**Interfaces:**
- Consumes: normal Phase 18D `DetailedBuildingPackage` plus `solver_blast_physical_envelope=True` in a dedicated compile call.
- Produces: `build_physical_building(package, config) -> PhysicalBuildingModel` with a welded structure fragment, retained thin components, member audit rows, bounds, openings, and real exterior faces.

- [ ] **Step 1: Write failing three-asset tests**

```python
@pytest.mark.parametrize("resource_id", SUPPORTED_IDS)
def test_solver_building_has_load_path_and_no_unreviewed_family(resource_id):
    model = build_fixture(resource_id)
    assert audit_physical_building(model) == ()
    assert model.load_path.foundation_roles
    assert model.load_path.vertical_roles
    assert model.load_path.floor_or_roof_roles

def test_commercial_opaque_facade_is_thick_solid_but_glazing_remains_shell():
    model = build_fixture(COMMERCIAL_ID)
    assert model.family_for_role("opaque_facade") == "Solid"
    assert model.family_for_role("glazing") == "Shell"
    assert model.has_continuous_column_to_foundation_path

def test_residential_has_no_unplanned_storey_envelope_gap():
    model = build_fixture(RESIDENTIAL_ID)
    assert model.unplanned_exterior_gap_intervals_m == ()

def test_subway_has_ground_and_nonoverlapping_excavation():
    model = build_fixture(SUBWAY_ID)
    assert model.grade_elevation_m > model.rc_box_bounds_m[2]
    assert model.positive_soil_structure_overlap_m3 == 0.0
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_phase18_solver_blast_buildings.py`

Expected: missing `physical_building` module and physical-envelope option.

- [ ] **Step 3: Add solver-only semantic supplements**

In the dedicated option path only:

- commercial: add axis-aligned opaque facade Solid boxes around explicit door/window openings; retain steel frame and physical glass/roof shell;
- residential: extend opaque Solid facade rows to meet slab bands, keep declared windows/openings empty, and do not connect towers;
- subway: retain RC box/stair geometry and publish grade/excavation evidence for Task 3.

Default Phase 18D calls must remain byte/fingerprint compatible.

- [ ] **Step 4: Weld and audit real load paths**

Use `mesh_axis_aligned_union` for overlapping structural/opaque solids, `merge_fragments_welded` where roles share coordinates, and explicit connection records for Beam/Shell-to-Solid boundaries. Compute exterior topology from actual element faces.

- [ ] **Step 5: Run focused and compatibility GREEN**

Run: `python -m pytest -q tests/test_phase18_solver_blast_buildings.py tests/test_phase18d_commercial_supermarket.py tests/test_phase18d_residential_subway.py`

Commit with `feat: build physical phase18 blast buildings`.

### Task 3: Ground, visible MM-ALE air, and movable TNT

**Files:**
- Create: `lsprepost_mcp/refined_building/solver_blast/ground.py`
- Create: `lsprepost_mcp/refined_building/solver_blast/ale_domain.py`
- Create: `lsprepost_mcp/refined_building/solver_blast/charge.py`
- Test: `tests/test_phase18_solver_blast_scene.py`

**Interfaces:**
- Consumes: `PhysicalBuildingModel`, `SolverBlastConfig`.
- Produces: `build_ground(model, config) -> GroundModel`; `estimate_ale_domain(...) -> AleDomainEstimate`; `iter_ale_nodes/elements(...)`; `build_charge(config, air_domain, occupied_volumes) -> ChargeModel`; `build_solver_blast_scene(...) -> SolverBlastScene`.

- [ ] **Step 1: Write failing air/charge/soil tests**

```python
def test_air_domain_encloses_visible_building_and_charge():
    scene = build_scene(COMMERCIAL_ID)
    assert scene.air.part_role == "ale_air_tnt_domain"
    assert scene.air.bounds.contains_box(scene.building.bounds)
    assert scene.air.bounds.contains_point(scene.charge.position_m)

def test_moving_charge_changes_scene_not_building():
    left = build_scene(COMMERCIAL_ID, position=(-2.0, 0.0, 1.5))
    right = build_scene(COMMERCIAL_ID, position=(-2.0, 1.0, 1.5))
    assert left.building.fingerprint == right.building.fingerprint
    assert left.charge.fingerprint != right.charge.fingerprint
    assert left.fingerprint != right.fingerprint

def test_charge_inside_structure_fails_before_ale_allocation():
    with pytest.raises(ValueError, match="valid air"):
        build_scene(COMMERCIAL_ID, position=inside_column())
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_phase18_solver_blast_scene.py`

- [ ] **Step 3: Implement bounded ground and excavation**

Commercial/residential use a diagnostic soil slab below grade. Subway uses soil blocks around a box-shaped excavation and entrance void. Mesh with positive HEX8 orientation and fix only far/bottom soil boundaries.

- [ ] **Step 4: Implement streamed structured ALE mesh**

Preflight axis/node/element/byte budgets before building axes. Use stable node/solid ranges, stream rows, expose six boundary face sets, and record the air Part as independently visible.

- [ ] **Step 5: Implement movable spherical TNT**

Compute `radius=(3*mass/(4*pi*density))**(1/3)`, validate valid-air clearance, and publish exact `*INITIAL_VOLUME_FRACTION_GEOMETRY` and detonation inputs without changing building identity.

- [ ] **Step 6: Run GREEN and commit**

Run: `python -m pytest -q tests/test_phase18_solver_blast_scene.py`

Commit with `feat: add movable tnt and visible ale air`.

### Task 4: Real exterior FSI and dependency-closed R12 keyword compiler

**Files:**
- Create: `lsprepost_mcp/refined_building/solver_blast/fsi.py`
- Create: `lsprepost_mcp/refined_building/solver_blast/keyword.py`
- Create: `lsprepost_mcp/refined_building/solver_blast/materials.py`
- Test: `tests/test_phase18_solver_blast_keyword.py`

**Interfaces:**
- Consumes: `SolverBlastScene`.
- Produces: `extract_fsi_segments(scene) -> FsiInterface`; `write_solver_blast_deck(scene, output_dir) -> SolverBlastDeckEvidence`.

- [ ] **Step 1: Write failing real-card tests**

```python
def test_small_scene_writes_solver_complete_keyword(tmp_path):
    evidence = write_solver_blast_deck(small_scene(), tmp_path)
    text = (tmp_path / "model.k").read_text(encoding="utf-8")
    for card in (
        "*MAT_NULL", "*EOS_LINEAR_POLYNOMIAL",
        "*MAT_HIGH_EXPLOSIVE_BURN", "*EOS_JWL",
        "*ALE_MULTI-MATERIAL_GROUP", "*INITIAL_VOLUME_FRACTION_GEOMETRY",
        "*INITIAL_DETONATION", "*CONSTRAINED_LAGRANGE_IN_SOLID",
    ):
        assert card in text
    assert evidence.fsi_slave_segment_count > 0
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_phase18_solver_blast_keyword.py`

- [ ] **Step 3: Extract real oriented boundary segments**

Count HEX8 faces by canonical node tuple, retain faces owned once, add physical Shell faces, remove ground-contact faces, orient outward using element centroids, and reject duplicate/zero-area/internal faces.

- [ ] **Step 4: Reuse reviewed Phase 14/15 R12 card patterns**

Render versioned air/TNT/material resources, ALE controls, multimaterial group, volume-fraction sphere, detonation, nonreflecting far boundaries, FSI set and coupling, termination/output/energy cards. Recompute all IDs and references from bytes after writing.

- [ ] **Step 5: Run GREEN and a real tiny R12 mcheck**

Run unit tests, then generate a tiny scene and invoke the configured R12 executable with `mcheck=y memory=1g`. Save stdout/stderr/d3hsp and add any discovered error as a failing test before changing the renderer.

Commit with `feat: compile solver-complete phase18 blast decks`.

### Task 5: Static, persisted, and solver-result validators

**Files:**
- Create: `lsprepost_mcp/refined_building/solver_blast/validation.py`
- Create: `lsprepost_mcp/refined_building/solver_blast/results.py`
- Test: `tests/test_phase18_solver_blast_validation.py`

**Interfaces:**
- Consumes: persisted model directory and R12 run directory.
- Produces: `inspect_solver_blast_deck(path) -> ValidationReport`; `evaluate_solver_blast_run(model_dir, run_dir) -> SolverBlastRunReport`.

- [ ] **Step 1: Write failing tamper and propagation tests**

```python
@pytest.mark.parametrize("mutation", [
    "missing_air_eos", "missing_tnt_jwl", "empty_fsi_set",
    "moved_charge_into_soil", "dangling_part", "changed_model_hash",
])
def test_persisted_deck_tampering_fails_closed(tmp_path, mutation):
    model = generated_small_model(tmp_path)
    mutate(model, mutation)
    assert inspect_solver_blast_deck(model).ok is False

def test_run_requires_real_tnt_air_structure_causality(run_fixture):
    report = evaluate_solver_blast_run(*run_fixture)
    assert report.normal_termination
    assert report.final_problem_time_s >= 0.001
    assert report.fsi_slave_segment_count > 0
    assert report.air_peak_pressure_pa > 0.0
    assert report.building_peak_response > report.response_noise_floor
    assert report.source_time_s <= report.air_arrival_time_s <= report.building_arrival_time_s
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_phase18_solver_blast_validation.py`

- [ ] **Step 3: Implement persisted closure inspection**

Reparse the monolithic K file, recompute hashes/counts/part sets/material-EOS relationships, reconstruct charge identity and FSI segments, and compare with immutable manifest values.

- [ ] **Step 4: Implement R12 evidence parser**

Read `d3hsp`, `glstat`, `messag`, `dbfsi`, and selected history outputs. Require explicit normal termination, final problem time, finite energies, no fatal/negative-volume/NaN record, positive reported slave count, nonzero air response and nonzero building response in causal order.

- [ ] **Step 5: Run GREEN and commit**

Commit with `feat: validate phase18 blast energy transfer`.

### Task 6: Phase 18E/F solver-complete provider and workbench controls

**Files:**
- Create: `lsprepost_mcp/refined_blast/providers/solver_complete_ale_fsi.py`
- Modify: `lsprepost_mcp/refined_blast/provider_registry.py`
- Modify: `lsprepost_mcp/web/refined_blast_api.py`
- Modify: `lsprepost_mcp/web/static/refined_blast_workbench.js`
- Modify: `lsprepost_mcp/web/static/refined_blast_workbench.css`
- Test: `tests/test_phase18_solver_blast_provider.py`
- Test: `tests/test_phase18f_api.py`
- Test: `tests/test_phase18f_web_contract.py`

**Interfaces:**
- Consumes: selected Phase 18D asset, config fields, persisted project revision.
- Produces: provider ID `solver_complete_ale_fsi`; preview layers for structure/soil/air/TNT/FSI; generated trusted solver deck; editable mass/XYZ/time fields.

- [ ] **Step 1: Write failing provider/API/UI tests**

```python
def test_capabilities_publish_solver_complete_provider():
    row = provider_by_id(api.capabilities(), "solver_complete_ale_fsi")
    assert row["default_input"]["tnt_equivalent_mass_kg"] == 2.0
    assert row["input_schema"]["properties"]["charge_position_m"]["minItems"] == 3

def test_generate_returns_solver_complete_evidence(tmp_path):
    response = generate_real_project(tmp_path, provider_id="solver_complete_ale_fsi")
    assert response["solver_complete"] is True
    assert response["external_program_started"] is False
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_phase18_solver_blast_provider.py tests/test_phase18f_api.py tests/test_phase18f_web_contract.py`

- [ ] **Step 3: Bind the new provider without changing neutral providers**

The provider normalizes the closed solver config, compiles the physical asset and preview estimate, and delegates final trusted generation to `solver_blast.service`. It never marks the old `explicit_ale_fsi` package solver-complete.

- [ ] **Step 4: Add focused workbench controls**

Show mass, X/Y/Z, detonation time and air margin in the basic flow; keep material/mesh/FSI values under advanced settings. Preview renders distinct visible layers. Generation remains separate from LS-PrePost/LS-DYNA launch and retains explicit confirmation.

- [ ] **Step 5: Run GREEN and compatibility tests**

Run provider/API/UI tests plus existing Phase 18E/F tests excluding declared heavyweight E2E. Commit with `feat: expose solver-complete ale fsi workflow`.

### Task 7: Generate and debug the three real R12 models

**Files:**
- Create: `scripts/generate_phase18_solver_blast_models.py`
- Create: `tests/test_phase18_solver_blast_script.py`
- Runtime only: `E:\K文件模型\Phase18_三类精细建筑_ALEFSI_20260820\...`

**Interfaces:**
- Consumes: the three built-in assets, default 2 kg config, configured R12 executable.
- Produces: three immutable model directories, LS-PrePost evidence, mcheck directories, 1 ms run directories, and `solver_blast_summary.json`.

- [ ] **Step 1: Write failing safe-CLI test**

```python
def test_cli_dry_run_lists_exact_three_models(tmp_path):
    result = run_cli("--output-root", str(tmp_path), "--dry-run")
    payload = json.loads(result.stdout)
    assert [row["resource_id"] for row in payload["models"]] == list(SUPPORTED_IDS)
    assert all(row["charge_mass_kg"] == 2.0 for row in payload["models"])
```

- [ ] **Step 2: Run RED, implement CLI, run GREEN**

The CLI accepts output root plus optional mass/position overrides, refuses nonempty targets, and never accepts an arbitrary executable path. It reads the configured R12 executable from the approved local validation configuration.

- [ ] **Step 3: Generate one small diagnostic scene first**

Run static inspection, LS-PrePost import check where automation is available, and R12 mcheck. Any error becomes a minimal failing test against the generating module before a production fix.

- [ ] **Step 4: Generate the exact three models once**

Write all model/config/manifest files below the new output root. Preserve the old structural model root unchanged.

- [ ] **Step 5: Run mcheck then 1 ms serially**

For each model: mcheck first; only on pass run 1 ms. Never run two large R12 jobs concurrently. Save stdout/stderr, d3hsp, glstat, messag, dbfsi and probe histories.

- [ ] **Step 6: Debug by source chain and rerun only the affected model**

For every real LS-DYNA error, add a failing regression test to the responsible geometry/material/keyword/FSI/result component. Do not edit generated K files by hand. Regenerate a new immutable snapshot after the source fix.

- [ ] **Step 7: Require three terminal PASS reports**

The summary reports `overall_pass=true` only if all three model reports independently pass every gate from Task 5. Commit only script/tests, not runtime K or solver outputs.

### Task 8: Full compatibility, independent review, and formal report

**Files:**
- Create: `docs/reviews/phase18/PHASE18_SOLVER_COMPLETE_ALE_FSI_REPORT.zh-CN.md`
- Modify: `docs/ROADMAP.zh-CN.md` only if all three real runs pass.

**Interfaces:**
- Consumes: Tasks 1–7 code, tests and runtime evidence.
- Produces: final software/solver acceptance report and exact Phase 18 status.

- [ ] **Step 1: Run solver-blast focused tests**

Run all `tests/test_phase18_solver_blast_*.py` and record exact counts/timings.

- [ ] **Step 2: Run Phase 18C–F compatibility/fingerprint gates**

Run the existing Phase 18C/D asset, Phase 18E provider/assembler/store, and Phase 18F API/UI suites. Assert neutral-provider and default-asset fingerprints remain unchanged unless the dedicated solver option is selected.

- [ ] **Step 3: Run repository affected core/static/package checks**

Run compileall, Node syntax/runtime fixtures, keyword checks, LS-DYNA runner tests, pack/distribution safety and `git diff --check`.

- [ ] **Step 4: Perform independent full-range review**

Review physical modeling, geometry/connectivity, keyword correctness, FSI truth, path safety, identity determinism and evidence claims. Fix all Critical/Important findings with RED→GREEN tests, then re-review the fix diff.

- [ ] **Step 5: Write the formal report without overclaiming**

List exact part families and physical bases, air/TNT/soil identities, charge positions, LS-PrePost evidence, R12 command/hash, mcheck/run IDs, times, energies, FSI counts, response metrics, warnings and remaining engineering limits. If any one model lacks a terminal PASS, keep Phase 18 status conditional and do not update ROADMAP to complete.

- [ ] **Step 6: Final verification and scoped commits**

Commit code/test tasks separately from the formal report. Verify clean tracked status while preserving pre-existing untracked `.codex_doc_review/` and `tmp/`.

## Plan Self-Review Record

- Spec coverage: physical unit selection, three asset corrections, ground/soil, visible air, movable TNT, real FSI, persisted K closure, Phase 18E/F integration, LS-PrePost/R12 evidence, three terminal PASS reports and engineering boundaries map to Tasks 1–8.
- Placeholder scan: no deferred implementation placeholder or undefined task handoff remains.
- Type consistency: Tasks 1–5 share `SolverBlastConfig`, `PhysicalBuildingModel`, `SolverBlastScene`, `SolverBlastDeckEvidence` and validator reports; Task 6 delegates to the same service; Task 7 consumes the same public API.
- Isolation: old gravity validation and neutral provider paths are read-only compatibility baselines; only the dedicated solver-complete provider uses the new compiler.
- Runtime safety: all external runs are serial, trusted-path only, mcheck precedes solve, and generated output is immutable and outside Git.
