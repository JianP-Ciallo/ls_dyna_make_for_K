# Literature 14 Blast Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the V2 35 kg TNT, 20 m gable-side MM-ALE literature baseline as a discoverable tool and refined-blast workbench feature, then generate validated coarse and baseline LS-DYNA `.k` snapshots.

**Architecture:** Add a focused `lsprepost_mcp.blast_baseline` domain package whose registry, resource loader, rigid-building geometry, streaming ALE writer, snapshot validator, and result evaluator remain independent. Public MCP tools and a narrow HTTP adapter call the same service; a small panel mounts inside the existing refined-building-blast workbench. Solver launch reuses the configured-executable handoff and passes the entire server-generated include closure.

**Tech Stack:** Python 3.11+, dataclasses, JSON resources, LS-DYNA keyword text, existing project locking/path helpers, stdlib HTTP server, vanilla JavaScript modules, Three.js preview adapter, pytest/unittest, Node runtime contract tests.

**Spec:** `baseline.md`

## Global Constraints

- Stable baseline ID: `literature14_v2_gable_35kg`; version: `literature14-v2-gable-35kg@1.0.0`.
- Unit system: `SI_m_s_kg_N_Pa`.
- V2 source: 35 kg spherical TNT at `(-20.0, 0.0, 0.6) m`; front gable is `x=0`; termination time is `0.100 s`.
- Building envelope: depth `4.5 m`, gable width `9.0 m`, eave `6.0 m`, ridge `9.4 m`; retain the documented approximate 36° slope as source evidence and the derived 37.1° geometry as the implementation value.
- ALE bounds: `[-23.0, -10.0, 0.0, 10.0, 10.0, 12.0] m` in `(xmin,ymin,zmin,xmax,ymax,zmax)` order.
- Mesh profiles: `coarse=0.40 m`, `baseline=0.20 m`, `refined=0.10 m`; generation must preflight before allocation and stream the large node/element files.
- Required gauges: `Ps01`–`Ps09` plus ten front/side/roof/rear representative gauges; pressure history interval `0.00005 s`, 3D output interval `0.0005 s`.
- Hard physical gates are ordering and signal validity; the broad pressure/time bands are reported as similarity observations, not single-point software failures.
- Until real run evidence exists, retain `validation_status=research_candidate`, `solver_ready=false`, `requires_project_review=true`, and `engineering_validated=false`.
- Generated snapshots live below `workspace/baselines/`; public APIs never accept arbitrary executable paths or unrestricted filesystem targets.
- Do not modify or stage the pre-existing dirty files `lsprepost_mcp/lsdyna_runner.py`, `lsprepost_mcp/solver_results.py`, `lsprepost_mcp/refined_building/solver_validation.py`, `scripts/generate_phase18_refined_validation_models.py`, or `tests/test_phase18_solver_validation.py` unless the user separately resolves ownership.
- Execute implementation in an isolated worktree created from commit `e9f4b31` or a later plan-only commit.

## File Map

New domain files:

- `lsprepost_mcp/blast_baseline/contracts.py`: immutable public values and exact schema constants.
- `lsprepost_mcp/blast_baseline/registry.py`: discover and normalize baseline JSON definitions.
- `lsprepost_mcp/blast_baseline/resources.py`: load and validate the four-version material bundle.
- `lsprepost_mcp/blast_baseline/geometry.py`: rigid gable shell and gauge coordinates.
- `lsprepost_mcp/blast_baseline/mesh.py`: mesh estimates and streaming structured ALE rows.
- `lsprepost_mcp/blast_baseline/keyword.py`: modular LS-DYNA card renderers.
- `lsprepost_mcp/blast_baseline/snapshot.py`: atomic generation, hashes, include closure, and static validation.
- `lsprepost_mcp/blast_baseline/results.py`: normalized pressure histories and broad similarity report.
- `lsprepost_mcp/blast_baseline/service.py`: application-facing list/get/preview/validate/generate/evaluate facade.
- `lsprepost_mcp/blast_baseline/__init__.py`: intentionally small public exports.
- `lsprepost_mcp/tool_blast_baselines.py`: MCP argument adapters.
- `lsprepost_mcp/web/blast_baseline_api.py`: safe HTTP routes and configured external handoffs.
- `lsprepost_mcp/web/static/blast_baseline_panel.js`: panel state, API calls, confirmations, and callbacks.
- `lsprepost_mcp/web/static/blast_baseline_panel.css`: panel-only styles.
- `scripts/generate_literature14_baseline.py`: reproducible operator command for coarse/baseline snapshots.

New resources:

- `resources/model_library/baselines/literature14_v2_gable_35kg/baseline.json`
- `resources/materials/baselines/literature14_v2_gable_35kg/air.json`
- `resources/materials/baselines/literature14_v2_gable_35kg/tnt.json`
- `resources/materials/baselines/literature14_v2_gable_35kg/rigid_building.json`
- `resources/materials/baselines/literature14_v2_gable_35kg/rigid_ground.json`

Existing integration files:

- `lsprepost_mcp/config.py:9-21`: add the source and generated baseline roots.
- `lsprepost_mcp/tools.py:8-112`: import and register the six public tools.
- `lsprepost_mcp/web/app.py:54-60,214-330`: route the baseline API prefix.
- `lsprepost_mcp/web/static/refined_blast_workbench.js:157-259,888-944,1047-1087`: mount/unmount the baseline panel and forward preview payloads.
- `lsprepost_mcp/web/static/index.html:653-664`: load the panel stylesheet.
- `lsprepost_mcp/web/refined_blast_preview.py`: accept the shared preview primitive shape only if its existing contract needs a small additive branch.
- `README.zh-CN.md`: document the baseline tools, UI entry, generation cost, and evidence status.

---

### Task 1: Baseline contract, definition registry, and reviewed material bundle

**Files:**

- Create: `lsprepost_mcp/blast_baseline/__init__.py`
- Create: `lsprepost_mcp/blast_baseline/contracts.py`
- Create: `lsprepost_mcp/blast_baseline/registry.py`
- Create: `lsprepost_mcp/blast_baseline/resources.py`
- Create: `resources/model_library/baselines/literature14_v2_gable_35kg/baseline.json`
- Create: `resources/materials/baselines/literature14_v2_gable_35kg/air.json`
- Create: `resources/materials/baselines/literature14_v2_gable_35kg/tnt.json`
- Create: `resources/materials/baselines/literature14_v2_gable_35kg/rigid_building.json`
- Create: `resources/materials/baselines/literature14_v2_gable_35kg/rigid_ground.json`
- Modify: `lsprepost_mcp/config.py:9-21`
- Test: `tests/test_blast_baseline_registry.py`
- Test: `tests/test_blast_baseline_resources.py`

**Interfaces:**

- Consumes: `config.MODEL_LIBRARY_DIR`, `config.MATERIALS_DIR`, `DEFAULT_UNIT_SYSTEM`.
- Produces: `MeshProfile`, `BlastBaselineDefinition`, `MaterialBundle`; `list_blast_baselines() -> tuple[BlastBaselineDefinition, ...]`; `get_blast_baseline(baseline_id: str) -> BlastBaselineDefinition`; `load_material_bundle(definition: BlastBaselineDefinition) -> MaterialBundle`.

- [ ] **Step 1: Write failing registry and resource tests**

```python
def test_literature14_definition_is_closed_and_discoverable():
    rows = list_blast_baselines()
    assert [row.baseline_id for row in rows] == ["literature14_v2_gable_35kg"]
    row = get_blast_baseline("literature14_v2_gable_35kg")
    assert row.charge_mass_kg == 35.0
    assert row.charge_center_m == (-20.0, 0.0, 0.6)
    assert row.ale_bounds_m == (-23.0, -10.0, 0.0, 10.0, 10.0, 12.0)
    assert tuple(row.mesh_profiles) == ("coarse", "baseline", "refined")

def test_material_bundle_has_exact_roles_and_research_evidence():
    bundle = load_material_bundle(get_blast_baseline("literature14_v2_gable_35kg"))
    assert set(bundle.resources) == {"air", "tnt", "rigid_building", "rigid_ground"}
    assert bundle.resources["air"]["density_kg_per_m3"] == 1.225
    assert bundle.resources["tnt"]["jwl_si"]["a_pa"] == 640_000_000_000.0
    assert all(row["requires_project_review"] is True for row in bundle.resources.values())
```

- [ ] **Step 2: Run the focused tests and confirm import failure**

Run: `pytest tests/test_blast_baseline_registry.py tests/test_blast_baseline_resources.py -q`

Expected: collection fails because `lsprepost_mcp.blast_baseline` does not exist.

- [ ] **Step 3: Add exact immutable contracts**

```python
@dataclass(frozen=True, slots=True)
class MeshProfile:
    profile_id: str
    target_cell_size_m: float
    max_axis_points: int
    max_node_count: int
    max_element_count: int

@dataclass(frozen=True, slots=True)
class BlastBaselineDefinition:
    baseline_id: str
    version: str
    unit_system: str
    charge_mass_kg: float
    charge_center_m: tuple[float, float, float]
    ale_bounds_m: tuple[float, float, float, float, float, float]
    building: Mapping[str, float]
    mesh_profiles: Mapping[str, MeshProfile]
    material_resource_ids: Mapping[str, str]
    end_time_s: float
    pressure_dt_s: float
    d3plot_dt_s: float
```

The normalizer must reject unknown/missing keys, booleans as numbers, non-finite values, a baseline ID other than `literature14_v2_gable_35kg`, and any status that overclaims validation.

- [ ] **Step 4: Add the definition and four resource JSON files**

Use the exact physical values from `baseline.md`. The TNT resource must contain:

```json
{
  "id": "literature14_v2_tnt_jwl_reference",
  "version": "1.0.0",
  "unit_system": "SI_m_s_kg_N_Pa",
  "validation_status": "source_reference",
  "requires_project_review": true,
  "density_kg_per_m3": 1550.0,
  "detonation_velocity_m_per_s": 8193.0,
  "cj_pressure_pa": 28000000000.0,
  "jwl_si": {"a_pa": 640000000000.0, "b_pa": 13900000000.0, "r1": 4.5, "r2": 1.4, "omega": 0.25, "e0_j_per_m3": 8700000000.0, "v0": 1.0},
  "source_lineage": {"relation": "project_reference_assumption", "resource_id": "two_storey_rc_frame_mid3_tnt_eos1"}
}
```

- [ ] **Step 5: Implement strict discovery and material validation**

`registry.py` must scan only `MODEL_LIBRARY_DIR / "baselines"`; `resources.py` must resolve only the four IDs named by the normalized definition. Copy values before freezing them and compute a canonical SHA-256 for each resource.

- [ ] **Step 6: Run focused tests**

Run: `pytest tests/test_blast_baseline_registry.py tests/test_blast_baseline_resources.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit Task 1**

```bash
git add lsprepost_mcp/blast_baseline lsprepost_mcp/config.py resources/model_library/baselines resources/materials/baselines tests/test_blast_baseline_registry.py tests/test_blast_baseline_resources.py
git commit -m "feat: register literature blast baseline resources"
```

### Task 2: Rigid gable geometry and paper/representative gauges

**Files:**

- Create: `lsprepost_mcp/blast_baseline/geometry.py`
- Modify: `lsprepost_mcp/blast_baseline/contracts.py`
- Test: `tests/test_blast_baseline_geometry.py`

**Interfaces:**

- Consumes: `BlastBaselineDefinition`, `MeshProfile`.
- Produces: `Node(node_id, xyz_m)`, `Shell(shell_id, part_id, node_ids, surface_role)`, `PressureGauge(gauge_id, xyz_m, group, source_basis)`, `RigidBuildingGeometry`; `build_rigid_gable_geometry(definition, profile) -> RigidBuildingGeometry`; `build_pressure_gauges(definition, profile, geometry) -> tuple[PressureGauge, ...]`.

- [ ] **Step 1: Write failing geometry tests**

```python
def test_gable_geometry_preserves_envelope_and_closed_surface():
    definition = get_blast_baseline("literature14_v2_gable_35kg")
    geometry = build_rigid_gable_geometry(definition, definition.mesh_profiles["coarse"])
    assert geometry.bounds_m == (0.0, -4.5, 0.0, 4.5, 4.5, 9.4)
    assert geometry.is_closed is True
    assert set(geometry.surface_roles) == {"front_gable", "left_wall", "right_wall", "rear_gable", "left_roof", "right_roof"}
    assert abs(geometry.derived_roof_slope_deg - 37.073) < 0.01

def test_gauges_match_paper_distances_and_representative_groups():
    gauges = build_pressure_gauges(definition, profile, geometry)
    by_id = {row.gauge_id: row for row in gauges}
    assert by_id["Ps01"].xyz_m == (-12.0, 0.0, 0.3)
    assert by_id["Ps09"].xyz_m == (-6.0, 0.0, 2.0)
    assert len(gauges) == 19
    assert {row.group for row in gauges} >= {"free_field", "front", "side", "roof", "rear"}
```

- [ ] **Step 2: Verify the tests fail**

Run: `pytest tests/test_blast_baseline_geometry.py -q`

Expected: import failure for `build_rigid_gable_geometry`.

- [ ] **Step 3: Implement a watertight structured shell generator**

Generate front and rear gables as lower rectangles plus triangular roof faces, two rectangular side walls, and two roof planes. Subdivide edges by `ceil(length / min(profile.target_cell_size_m, 0.40))`, weld nodes by rounded SI coordinates, orient every shell normal outward, and verify every undirected edge belongs to exactly two shells.

- [ ] **Step 4: Implement deterministic gauges**

Use the nine exact free-field coordinates. For the ten representative surface gauges, use three front/rear heights `(1.5, 4.5, 7.5)`, wall midpoints at `(2.25, ±4.5, 3.0)`, and roof midpoints at `(2.25, ±2.25, roof_z)`. Offset surface sample points outward by `0.51 * target_cell_size_m` and retain the unoffset surface point in evidence.

- [ ] **Step 5: Add failure tests for geometry leaks and domain escape**

```python
@pytest.mark.parametrize("mutation", ["ridge_below_eave", "charge_ground_overlap", "gauge_outside_domain"])
def test_invalid_baseline_geometry_fails_closed(mutation):
    with pytest.raises(ValueError):
        compile_geometry_fixture(mutation)
```

- [ ] **Step 6: Run geometry tests**

Run: `pytest tests/test_blast_baseline_geometry.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add lsprepost_mcp/blast_baseline/contracts.py lsprepost_mcp/blast_baseline/geometry.py tests/test_blast_baseline_geometry.py
git commit -m "feat: build rigid gable baseline geometry"
```

### Task 3: Memory-bounded ALE estimates and streaming mesh rows

**Files:**

- Create: `lsprepost_mcp/blast_baseline/mesh.py`
- Modify: `lsprepost_mcp/blast_baseline/contracts.py`
- Test: `tests/test_blast_baseline_mesh.py`

**Interfaces:**

- Consumes: `BlastBaselineDefinition`, `MeshProfile`, `PressureGauge`.
- Produces: `AleMeshEstimate(axis_counts, node_count, element_count, estimated_keyword_bytes, gauge_solid_ids, fingerprint)`; `estimate_ale_mesh(definition, profile, gauges) -> AleMeshEstimate`; `iter_ale_node_lines(...) -> Iterator[str]`; `iter_ale_element_lines(...) -> Iterator[str]`; `solid_id_for_point(...) -> int`.

- [ ] **Step 1: Write failing count and budget tests**

```python
@pytest.mark.parametrize(("profile_id", "axis_counts", "elements"), [
    ("coarse", (84, 51, 31), 124_500),
    ("baseline", (166, 101, 61), 990_000),
    ("refined", (331, 201, 121), 7_920_000),
])
def test_mesh_estimates_match_fixed_domain(profile_id, axis_counts, elements):
    estimate = estimate_fixture(profile_id)
    assert estimate.axis_counts == axis_counts
    assert estimate.element_count == elements

def test_budget_is_checked_before_iterator_consumption():
    with pytest.raises(ValueError, match="element budget exceeded"):
        estimate_fixture("baseline", max_element_count=100)
```

- [ ] **Step 2: Run and observe failure**

Run: `pytest tests/test_blast_baseline_mesh.py -q`

Expected: import failure for `estimate_ale_mesh`.

- [ ] **Step 3: Implement uniform axes and preflight**

Compute each axis cell count as `ceil(extent / target_cell_size_m)` and place the final point exactly on the configured bound; record the resulting axis spacing, which must be positive and no larger than the target size. This yields 83 × 50 × 30 coarse cells because 33 m is not an integer multiple of 0.40 m. Reject any profile whose estimated counts exceed its axis, node, or element caps. Estimate bytes from conservative per-row maxima before opening output files.

- [ ] **Step 4: Implement streaming node and solid rows**

Use stable ID ranges: ALE nodes start at `1_000_001`; ALE solids at `2_000_001`; building nodes/shells use ranges beginning `10_000_001`/`11_000_001`. Iterators yield one line at a time and never return an accumulated list.

```python
def iter_ale_node_lines(definition, estimate):
    for k, z in enumerate(estimate.z_axis):
        for j, y in enumerate(estimate.y_axis):
            for i, x in enumerate(estimate.x_axis):
                yield f"{node_id(i,j,k)},{x:.9g},{y:.9g},{z:.9g}\n"
```

- [ ] **Step 5: Bind every gauge to one real ALE solid**

Map the sampled point to `(i,j,k)` by half-open cell intervals, reject boundary ambiguity, and expose `gauge_solid_ids` in stable gauge-ID order. Add a test that every gauge element ID lies in the generated solid range and is unique unless two documented points intentionally share a cell; the current profile definitions must produce unique IDs.

- [ ] **Step 6: Run mesh tests**

Run: `pytest tests/test_blast_baseline_mesh.py -q`

Expected: all tests pass without materializing a baseline-sized list.

- [ ] **Step 7: Commit Task 3**

```bash
git add lsprepost_mcp/blast_baseline/contracts.py lsprepost_mcp/blast_baseline/mesh.py tests/test_blast_baseline_mesh.py
git commit -m "feat: stream literature baseline ALE mesh"
```

### Task 4: Modular LS-DYNA keyword compiler

**Files:**

- Create: `lsprepost_mcp/blast_baseline/keyword.py`
- Test: `tests/test_blast_baseline_keyword.py`

**Interfaces:**

- Consumes: normalized definition, material bundle, rigid geometry, gauges, and mesh estimate.
- Produces: `write_keyword_modules(target_dir: Path, context: BaselineCompileContext) -> tuple[KeywordFileEvidence, ...]`; exact files `model.k`, `main.k`, `00_control.k` … `70_gauges_output.k`.

- [ ] **Step 1: Write failing small-deck tests**

Use a test-only definition with a `2.0 m` cell size and reduced domain, while retaining the same keyword families.

```python
def test_small_compiler_writes_exact_include_closure(tmp_path):
    evidence = write_keyword_modules(tmp_path, small_context())
    assert [row.path for row in evidence] == [
        "model.k", "main.k", "00_control.k", "10_materials.k",
        "20_building_rigid.k", "30_ground.k", "40_ale_domain.k",
        "50_charge.k", "60_coupling_boundary.k", "70_gauges_output.k",
    ]
    text = "\n".join((tmp_path / row.path).read_text() for row in evidence)
    for card in ("*CONTROL_TERMINATION", "*MAT_NULL", "*EOS_JWL", "*MAT_RIGID", "*ALE_MULTI-MATERIAL_GROUP", "*INITIAL_DETONATION", "*CONSTRAINED_LAGRANGE_IN_SOLID", "*BOUNDARY_NON_REFLECTING"):
        assert card in text
```

- [ ] **Step 2: Run and observe failure**

Run: `pytest tests/test_blast_baseline_keyword.py -q`

Expected: import failure for `write_keyword_modules`.

- [ ] **Step 3: Render entrypoints and controls**

`model.k` and `main.k` contain `*KEYWORD`, the same ordered `*INCLUDE` list, and one `*END`. `00_control.k` sets `0.100 s` termination, ALE/time-step controls, `0.0005 s` d3plot output, and conservative hourglass/energy database outputs.

- [ ] **Step 4: Render materials, parts, and MM-ALE domain**

Render air as `*MAT_NULL` + `*EOS_LINEAR_POLYNOMIAL`, TNT as `*MAT_HIGH_EXPLOSIVE_BURN` + `*EOS_JWL`, and building/ground as distinct `*MAT_RIGID` IDs. `40_ale_domain.k` writes the streamed nodes/elements, ALE section/part, and a two-material `*ALE_MULTI-MATERIAL_GROUP`.

- [ ] **Step 5: Render the entity charge and detonation**

Use `*INITIAL_VOLUME_FRACTION_GEOMETRY` with a sphere centered at the normalized charge coordinate and radius derived from `r=(3m/(4πρ))^(1/3)`. Add `*INITIAL_DETONATION` at the same center and assert the rendered mass reconstructed from the sphere and resource density differs from 35 kg by less than `1e-9` relative.

- [ ] **Step 6: Render building FSI and boundaries**

Create stable segment sets by `surface_role`, couple the full rigid-building exterior to the ALE part set with `*CONSTRAINED_LAGRANGE_IN_SOLID`, make only the five non-ground ALE faces non-reflecting, and keep `z=0` as the reflecting ground. Do not apply a non-reflecting card to a building or ground set.

- [ ] **Step 7: Render gauge output sets**

Create one titled solid set containing all 19 bound ALE solid IDs, plus group sets for free-field/front/side/roof/rear. Emit `*DATABASE_ALE_MAT` and `*DATABASE_HISTORY_SOLID_SET` at `0.00005 s`; record the exact gauge-to-solid mapping in keyword comments and later in `baseline.json`.

- [ ] **Step 8: Run keyword tests**

Run: `pytest tests/test_blast_baseline_keyword.py -q`

Expected: all tests pass and the test deck contains one `*END` per entrypoint only.

- [ ] **Step 9: Commit Task 4**

```bash
git add lsprepost_mcp/blast_baseline/keyword.py tests/test_blast_baseline_keyword.py
git commit -m "feat: compile modular literature baseline keywords"
```

### Task 5: Atomic snapshots, hashes, and static closure validation

**Files:**

- Create: `lsprepost_mcp/blast_baseline/snapshot.py`
- Modify: `lsprepost_mcp/blast_baseline/contracts.py`
- Modify: `lsprepost_mcp/blast_baseline/__init__.py`
- Modify: `lsprepost_mcp/config.py:9-21`
- Test: `tests/test_blast_baseline_snapshot.py`

**Interfaces:**

- Consumes: Task 1–4 interfaces.
- Produces: `BaselineSnapshot(snapshot_id, path, baseline_id, mesh_profile, manifest_sha256, files, estimate)`; `generate_baseline_snapshot(baseline_id, mesh_profile, *, snapshot_root=BLAST_BASELINES_DIR) -> BaselineSnapshot`; `validate_baseline_snapshot(path: Path) -> Mapping[str, object]`; `resolve_baseline_snapshot(snapshot_id: str) -> Path`.

- [ ] **Step 1: Write failing atomicity and tamper tests**

```python
def test_snapshot_generation_is_atomic_and_manifest_verified(tmp_path):
    snapshot = generate_test_snapshot(tmp_path)
    report = validate_baseline_snapshot(snapshot.path)
    assert report["ok"] is True
    assert report["file_count"] == 12  # ten K/entry files + baseline.json + manifest.json
    assert not list(tmp_path.glob(".*.tmp_*"))

def test_snapshot_rejects_rehashed_semantic_tampering(tmp_path):
    snapshot = generate_test_snapshot(tmp_path)
    charge = snapshot.path / "50_charge.k"
    charge.write_text(charge.read_text().replace("35 kg", "36 kg"), encoding="utf-8")
    with pytest.raises(ValueError, match="hash|charge evidence"):
        validate_baseline_snapshot(snapshot.path)
```

- [ ] **Step 2: Run and observe failure**

Run: `pytest tests/test_blast_baseline_snapshot.py -q`

Expected: import failure for `generate_baseline_snapshot`.

- [ ] **Step 3: Implement a safe snapshot root and unique IDs**

Add `BLAST_BASELINE_RESOURCES_DIR` and `BLAST_BASELINES_DIR` to `config.py`. Resolve every generated path beneath `BLAST_BASELINES_DIR`; use IDs matching `snapshot_YYYYMMDDTHHMMSSffffffZ_<12 hex>`. The public resolver accepts only this grammar and rejects symlinks or traversal.

- [ ] **Step 4: Write to a temporary sibling then atomically rename**

Write keyword modules, `baseline.json`, and finally `manifest.json`; validate the temporary directory before `Path.replace(final_path)`. On failure, remove only the verified temporary sibling and preserve every completed snapshot.

- [ ] **Step 5: Implement streaming static validation**

Verify exact include order, SHA-256/byte counts, unique keyword IDs by namespace, streamed node/element counts, all element-node references, charge/detonation identity, material IDs, five non-reflecting outer faces, reflecting ground, 19 gauge bindings, and manifest/definition fingerprints. The validator must not concatenate `40_ale_domain.k` into memory.

- [ ] **Step 6: Run snapshot tests**

Run: `pytest tests/test_blast_baseline_snapshot.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit Task 5**

```bash
git add lsprepost_mcp/blast_baseline lsprepost_mcp/config.py tests/test_blast_baseline_snapshot.py
git commit -m "feat: persist verified baseline snapshots"
```

### Task 6: Application service and six public MCP tools

**Files:**

- Create: `lsprepost_mcp/blast_baseline/service.py`
- Create: `lsprepost_mcp/tool_blast_baselines.py`
- Modify: `lsprepost_mcp/blast_baseline/__init__.py`
- Modify: `lsprepost_mcp/tools.py:8-112,663-670`
- Test: `tests/test_blast_baseline_service.py`
- Test: `tests/test_blast_baseline_tools.py`

**Interfaces:**

- Consumes: registry, resources, geometry, mesh, and snapshot interfaces.
- Produces: `BlastBaselineService.list/get/preview/validate/generate/evaluate`; MCP handlers `tool_list_blast_baselines`, `tool_get_blast_baseline`, `tool_preview_blast_baseline`, `tool_validate_blast_baseline`, `tool_generate_blast_baseline`, `tool_evaluate_blast_baseline`.

- [ ] **Step 1: Write failing service/tool registration tests**

```python
def test_baseline_tools_are_registered_with_closed_schemas():
    expected = {"list_blast_baselines", "get_blast_baseline", "preview_blast_baseline", "validate_blast_baseline", "generate_blast_baseline", "evaluate_blast_baseline"}
    assert expected <= set(TOOLS)
    for name in expected:
        assert TOOLS[name][1]["additionalProperties"] is False

def test_preview_is_read_only_and_exposes_mesh_cost(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BLAST_BASELINES_DIR", tmp_path)
    result = BlastBaselineService().preview("literature14_v2_gable_35kg", "coarse")
    assert result["estimate"]["element_count"] == 124_500
    assert result["gauge_count"] == 19
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Run and observe failure**

Run: `pytest tests/test_blast_baseline_service.py tests/test_blast_baseline_tools.py -q`

Expected: missing service/tool imports.

- [ ] **Step 3: Implement the facade without duplicating domain logic**

`preview` returns immutable JSON-ready geometry primitives, charge sphere, ALE bounds, gauge markers, mesh counts, resource versions, and warnings. `validate` returns findings without writing. `generate` calls only `generate_baseline_snapshot` and returns the safe snapshot identity/path plus manifest evidence.

- [ ] **Step 4: Add strict MCP schemas and adapters**

The generation schema accepts only `baseline_id`, `mesh_profile`, and `generate_project_name` (optional safe label used in metadata); it does not accept `output_dir`, executable paths, LS-DYNA options, or keyword fragments. The evaluation tool accepts only `snapshot_id` and `run_id`.

- [ ] **Step 5: Run service/tool tests and server schema tests**

Run: `pytest tests/test_blast_baseline_service.py tests/test_blast_baseline_tools.py tests/test_server.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 6**

```bash
git add lsprepost_mcp/blast_baseline lsprepost_mcp/tool_blast_baselines.py lsprepost_mcp/tools.py tests/test_blast_baseline_service.py tests/test_blast_baseline_tools.py
git commit -m "feat: expose blast baseline tools"
```

### Task 7: Safe HTTP API and configured LS-PrePost/LS-DYNA handoffs

**Files:**

- Create: `lsprepost_mcp/web/blast_baseline_api.py`
- Modify: `lsprepost_mcp/web/app.py:54-60,214-330`
- Reuse: `lsprepost_mcp/web/refined_blast_handoff.py`
- Test: `tests/test_blast_baseline_web_api.py`

**Interfaces:**

- Consumes: `BlastBaselineService`, `resolve_baseline_snapshot`, `validate_baseline_snapshot`, `configured_action_doctor`, `open_lsprepost_snapshot`, `launch_lsdyna_snapshot`.
- Produces: API prefix `/api/blast-baselines`; GET catalog/item/snapshot status; POST preview/validate/generate/evaluate; nonce-bound POST open/launch actions.

- [ ] **Step 1: Write failing route tests**

```python
def test_baseline_catalog_preview_and_generate_routes(web_server):
    status, catalog = request_json(web_server, "GET", "/api/blast-baselines")
    assert status == 200
    assert catalog["result"]["baselines"][0]["baseline_id"] == "literature14_v2_gable_35kg"
    status, preview = request_json(web_server, "POST", "/api/blast-baselines/preview", {"baseline_id": "literature14_v2_gable_35kg", "mesh_profile": "coarse"})
    assert status == 200
    assert preview["result"]["preview"]["gauge_count"] == 19

def test_external_action_rejects_missing_or_stale_confirmation(web_server):
    status, payload = request_json(web_server, "POST", "/api/blast-baselines/snapshots/snapshot_invalid/launch-lsdyna", {})
    assert status in {400, 404, 409}
    assert payload["ok"] is False
```

- [ ] **Step 2: Run and observe 404 failures**

Run: `pytest tests/test_blast_baseline_web_api.py -q`

Expected: routes return 404.

- [ ] **Step 3: Implement narrow routing and exact payload keys**

Follow `refined_blast_api.py` error translation and same-origin protections. Route only paths below `BLAST_BASELINE_API_PREFIX = "/api/blast-baselines"`; reject legacy/refined project payloads and all unknown fields.

- [ ] **Step 4: Implement snapshot-bound action confirmations**

Prepare a one-use nonce bound to `(action, snapshot_id, manifest_sha256)`, expire it after five minutes, consume it atomically, and revalidate the snapshot immediately before delegation. A changed snapshot must invalidate the nonce.

- [ ] **Step 5: Reuse configured handoff functions**

Write identical include entrypoints `main.k` and `model.k`, then call `open_lsprepost_snapshot(snapshot, snapshot / "main.k")` or `launch_lsdyna_snapshot(snapshot, snapshot / "main.k")`. Do not accept solver paths, CPU, memory, timeout, or arbitrary directories from the route.

- [ ] **Step 6: Run API and security regression tests**

Run: `pytest tests/test_blast_baseline_web_api.py tests/test_phase18f_external_actions.py tests/test_web_config.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit Task 7**

```bash
git add lsprepost_mcp/web/app.py lsprepost_mcp/web/blast_baseline_api.py tests/test_blast_baseline_web_api.py
git commit -m "feat: add blast baseline web API"
```

### Task 8: Baseline panel inside the refined-building-blast workbench

**Files:**

- Create: `lsprepost_mcp/web/static/blast_baseline_panel.js`
- Create: `lsprepost_mcp/web/static/blast_baseline_panel.css`
- Modify: `lsprepost_mcp/web/static/refined_blast_workbench.js:1-2,157-259,888-944,1047-1087`
- Modify: `lsprepost_mcp/web/static/index.html:653-664`
- Create: `web/tests/blast-baseline-panel.runtime.cjs`
- Modify: `tests/test_phase18f_web_contract.py`
- Test: `tests/test_blast_baseline_web_contract.py`

**Interfaces:**

- Consumes: Task 7 HTTP endpoints; existing `renderRefinedBlastPreview` callback.
- Produces: `mountBlastBaselinePanel(root, {fetchImpl, onPreview, onGenerated})`; `unmountBlastBaselinePanel()`.

- [ ] **Step 1: Write failing static and runtime contracts**

```python
def test_refined_workbench_mounts_literature_baseline_panel():
    source = WORKBENCH_JS.read_text(encoding="utf-8")
    assert 'data-blast-baseline-panel' in source
    assert 'mountBlastBaselinePanel' in source
    panel = PANEL_JS.read_text(encoding="utf-8")
    assert '/api/blast-baselines' in panel
    assert '35 kg TNT' in panel
    assert '20 m' in panel
    assert 'research_candidate' in panel
```

The Node runtime contract must simulate catalog → preview → generate, cancel an external confirmation without issuing a request, and confirm that a successful action performs confirmation preparation before delegation.

- [ ] **Step 2: Run and observe missing-file failures**

Run: `pytest tests/test_blast_baseline_web_contract.py tests/test_phase18f_web_contract.py -q`

Expected: the panel module and mount markup are missing.

- [ ] **Step 3: Build a compact baseline card**

Render a selector fixed to the registered baseline, mesh profile selector, immutable summary (35 kg, 20 m, 0.6 m, 100 ms), estimated nodes/elements/file size, evidence badge, and buttons for preview, validate, generate, open LS-PrePost, launch LS-DYNA, and evaluate. Disable actions while a request is active and surface server errors as text.

- [ ] **Step 4: Connect preview to the existing main canvas**

The panel calls `onPreview(result.preview)`; the workbench translates the returned domain box, rigid-shell mesh, charge sphere, and gauge markers into the existing `renderRefinedBlastPreview` payload. Do not create a second Three.js renderer or animation loop.

- [ ] **Step 5: Add explicit external-action confirmation**

Show a browser confirmation containing snapshot ID, mesh profile, estimated element count, `solver_ready=false`, and project-review warning. Only after approval request a nonce and immediately invoke the bound action. A cancel issues zero network requests.

- [ ] **Step 6: Add scoped CSS and accessibility**

Use only `.blast-baseline-*` selectors. Label every select/button, expose request status with `aria-live="polite"`, keep keyboard focus within normal document flow, and preserve the existing responsive workbench grid.

- [ ] **Step 7: Run frontend contracts**

Run: `pytest tests/test_blast_baseline_web_contract.py tests/test_phase18f_web_contract.py tests/test_phase18f_web_e2e_contract.py -q`

Expected: all tests pass.

- [ ] **Step 8: Commit Task 8**

```bash
git add lsprepost_mcp/web/static/blast_baseline_panel.js lsprepost_mcp/web/static/blast_baseline_panel.css lsprepost_mcp/web/static/refined_blast_workbench.js lsprepost_mcp/web/static/index.html web/tests/blast-baseline-panel.runtime.cjs tests/test_blast_baseline_web_contract.py tests/test_phase18f_web_contract.py
git commit -m "feat: add literature baseline to blast workbench"
```

### Task 9: Pressure-history parser and broad similarity evaluation

**Files:**

- Create: `lsprepost_mcp/blast_baseline/results.py`
- Modify: `lsprepost_mcp/blast_baseline/service.py`
- Modify: `lsprepost_mcp/web/blast_baseline_api.py`
- Test: `tests/test_blast_baseline_results.py`

**Interfaces:**

- Consumes: `baseline.json` gauge mapping; a completed run directory containing either normalized `baseline_pressure_history.csv` or LS-DYNA `elout` solid histories.
- Produces: `parse_pressure_histories(run_dir, gauge_map) -> Mapping[str, tuple[tuple[float, float], ...]]`; `evaluate_pressure_histories(definition, histories) -> Mapping[str, object]`; `evaluate_baseline_run(snapshot_id, run_id) -> Mapping[str, object>`.

- [ ] **Step 1: Write synthetic signal and failure tests**

```python
def test_evaluation_accepts_valid_propagation_order_and_reports_bands(tmp_path):
    histories = synthetic_histories(
        arrivals={"Ps01": 0.014, "Ps04": 0.023, "Ps07": 0.031, "front_mid": 0.038},
        peaks={"Ps01": 150_000.0, "Ps04": 100_000.0, "Ps07": 75_000.0, "front_mid": 72_000.0, "side_left": 24_000.0, "roof_left": 20_000.0, "rear_mid": 8_000.0},
    )
    report = evaluate_pressure_histories(definition, histories)
    assert report["hard_gates"]["free_field_arrival_order"]["ok"] is True
    assert report["hard_gates"]["surface_peak_order"]["ok"] is True
    assert report["similarity"]["front_peak"]["inside_observation_band"] is True

def test_constant_or_missing_signal_fails_closed():
    with pytest.raises(ValueError, match="signal|gauge"):
        evaluate_pressure_histories(definition, {"Ps01": ((0.0, 0.0), (0.1, 0.0))})
```

- [ ] **Step 2: Run and observe failure**

Run: `pytest tests/test_blast_baseline_results.py -q`

Expected: missing `results` module.

- [ ] **Step 3: Implement normalized CSV and bounded `elout` parsing**

The normalized CSV columns are exactly `gauge_id,time_s,pressure_pa`. Reject duplicate `(gauge_id,time_s)`, non-monotonic times, non-finite values, unknown gauges, files above a configured byte cap, and unit labels other than Pa/s. The `elout` parser accepts only the generated solid IDs from `baseline.json` and converts LS-DYNA SI pressure directly to Pa.

- [ ] **Step 4: Implement arrival and peak calculations**

Subtract the initial atmospheric pressure when histories contain absolute pressure. Define arrival as the first positive crossing of `max(2_000 Pa, 0.05 * gauge_peak)` with linear interpolation. Record positive peak and its time; reject fewer than three samples or a non-positive dynamic peak.

- [ ] **Step 5: Implement hard gates and broad bands**

Hard gates: `Ps01/Ps04/Ps07` arrival and peak distance ordering, valid positive pulses, and front > mean(side,roof) > rear surface peak ordering. Broad bands: front `50–100 kPa`, side/roof `10–40 kPa`, rear `0–20 kPa`, front arrival `30–50 ms`. A band miss is `observation`, not a hard-gate failure.

- [ ] **Step 6: Persist machine and Markdown reports**

Write `baseline_evaluation.json` and `baseline_evaluation.md` under the immutable run directory using atomic sibling replacement; include snapshot/run identities, source hashes, all gauge metrics, hard gates, band observations, and the research-candidate disclaimer.

- [ ] **Step 7: Run result and API tests**

Run: `pytest tests/test_blast_baseline_results.py tests/test_blast_baseline_web_api.py -q`

Expected: all tests pass.

- [ ] **Step 8: Commit Task 9**

```bash
git add lsprepost_mcp/blast_baseline/results.py lsprepost_mcp/blast_baseline/service.py lsprepost_mcp/web/blast_baseline_api.py tests/test_blast_baseline_results.py tests/test_blast_baseline_web_api.py
git commit -m "feat: evaluate literature baseline pressure histories"
```

### Task 10: Operator generator, real `.k` snapshots, and end-to-end verification

**Files:**

- Create: `scripts/generate_literature14_baseline.py`
- Modify: `README.zh-CN.md`
- Test: `tests/test_generate_literature14_baseline_script.py`
- Generate (runtime, not Git): `workspace/baselines/literature14_v2_gable_35kg/<snapshot_id>/...`

**Interfaces:**

- Consumes: `BlastBaselineService.generate/validate`, generated snapshot validator.
- Produces: reproducible CLI summary JSON; one coarse and one baseline snapshot containing the required `.k` closure.

- [ ] **Step 1: Write a failing CLI contract test**

```python
def test_generator_cli_supports_dry_run_and_safe_profile(tmp_path):
    result = subprocess.run(
        [sys.executable, "scripts/generate_literature14_baseline.py", "--mesh-profile", "coarse", "--dry-run"],
        cwd=ROOT, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["baseline_id"] == "literature14_v2_gable_35kg"
    assert payload["estimate"]["element_count"] == 124_500
```

- [ ] **Step 2: Run and observe missing-script failure**

Run: `pytest tests/test_generate_literature14_baseline_script.py -q`

Expected: Python cannot open the generator script.

- [ ] **Step 3: Implement the operator CLI**

Accept only `--mesh-profile {coarse,baseline,refined}`, `--dry-run`, and `--json-indent`. Dry-run calls preview/validate only. Real generation writes below the configured baseline root and prints the snapshot ID, absolute path, element count, byte count, and manifest hash as JSON.

- [ ] **Step 4: Run the focused CLI test**

Run: `pytest tests/test_generate_literature14_baseline_script.py -q`

Expected: pass.

- [ ] **Step 5: Run the complete new subsystem suite**

Run: `pytest tests/test_blast_baseline_registry.py tests/test_blast_baseline_resources.py tests/test_blast_baseline_geometry.py tests/test_blast_baseline_mesh.py tests/test_blast_baseline_keyword.py tests/test_blast_baseline_snapshot.py tests/test_blast_baseline_service.py tests/test_blast_baseline_tools.py tests/test_blast_baseline_results.py tests/test_blast_baseline_web_api.py tests/test_blast_baseline_web_contract.py tests/test_generate_literature14_baseline_script.py -q`

Expected: all tests pass.

- [ ] **Step 6: Run affected existing regressions**

Run: `pytest tests/test_server.py tests/test_tools.py tests/test_web_static.py tests/test_phase18f_api.py tests/test_phase18f_external_actions.py tests/test_phase18f_preview.py tests/test_phase18f_state_contract.py tests/test_phase18f_validation_flow.py tests/test_phase18f_web_contract.py tests/test_phase18f_web_e2e_contract.py -q`

Expected: all tests pass.

- [ ] **Step 7: Generate and validate the coarse K closure**

Run: `python scripts/generate_literature14_baseline.py --mesh-profile coarse`

The generator must call `validate_baseline_snapshot()` before returning success and print its validation summary in the same JSON response. Expected evidence: `124,500` ALE solids, `19` gauges, exact include closure, no dangling IDs, and matching hashes.

- [ ] **Step 8: Generate and validate the baseline K closure**

Run: `python scripts/generate_literature14_baseline.py --mesh-profile baseline`

Expected evidence: `990,000` ALE solids, `1,022,726` ALE nodes, `19` gauges, complete modular files, and a successful streaming validation report. Record wall time and output bytes; do not commit generated runtime files.

- [ ] **Step 9: Perform optional configured-program checks**

If LS-PrePost is configured, open the coarse `main.k` and capture its normal server handoff record. If LS-DYNA is configured and the user confirms the external action, run the bounded initialization check first; only start a full 100 ms coarse solve after the initialization record has no fatal keyword errors. Absence of an executable or license is reported as `external_program_unavailable`, not a software-generation failure.

- [ ] **Step 10: Update user documentation**

Document the six tools, `/refined-building-blast` baseline panel, mesh element counts, runtime output path, generated file names, explicit external confirmation, broad similarity bands, and the distinction between `research_candidate`, initialization checked, and completed run evidence.

- [ ] **Step 11: Run final verification**

Run: `pytest -q`

Expected: full repository suite passes. If environment-only integration tests are skipped, list each skip reason in the handoff.

- [ ] **Step 12: Commit Task 10**

```bash
git add scripts/generate_literature14_baseline.py tests/test_generate_literature14_baseline_script.py README.zh-CN.md
git commit -m "feat: generate literature blast baseline snapshots"
```

## Plan Self-Review Record

- Spec coverage: registry, geometry, charge, domain, mesh profiles, materials, modular K files, tools, frontend, external handoffs, evaluation, tests, coarse generation, and baseline generation each map to Tasks 1–10.
- Scope: all components are sequential dependencies of one user-visible baseline workflow; no independent subsystem needs a separate plan.
- Type consistency: registry returns `BlastBaselineDefinition`; Tasks 2–5 consume it; service/tools/API call the same snapshot and evaluation interfaces; frontend consumes only the HTTP boundary.
- Safety: generated paths remain under `workspace/baselines`; external executable paths are server-owned; the existing dirty solver files are excluded.
- Large-model behavior: preview is estimate-only and generation streams nodes/elements; the baseline-sized model is never accumulated as one Python string or list.
