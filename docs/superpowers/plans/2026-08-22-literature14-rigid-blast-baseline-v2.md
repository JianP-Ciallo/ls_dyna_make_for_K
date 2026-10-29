# Literature 14 Rigid Blast Baseline V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Add the Literature 14 35 kg TNT near-ground blast as a deterministic, model-generation-only baseline that can be listed, previewed, statically validated, and generated from the API, MCP tool, and an independent “文献基准实验” frontend entry.

**Architecture:** Keep the baseline domain independent from refined-building assets and from solver execution. Reuse only target-neutral Phase18 TNT/material/ALE primitives behind compatibility-preserving wrappers. Compile a rigid calibration target into six modular LS-DYNA include files, stream-validate the resulting package, and atomically publish content-addressed snapshots under the configured baseline workspace.

**Tech Stack:** Python 3.13, frozen dataclasses, pytest, LS-DYNA keyword text, vanilla JavaScript ES modules, WebGL viewer adapter, Node runtime contract tests.

**Spec:** baseline.md (literature14-v2-gable-35kg@2.0.0) is authoritative. This plan may make implementation choices only where that file is silent.

## Global Constraints

- This phase ends at a generated, statically valid model. It must not start LS-DYNA, LS-PrePost, a subprocess, or another external program.
- Public operations are exactly list, detail, preview, validate, and generate. Do not expose solve, evaluate, executable paths, arbitrary output paths, pressure curves, or paper-similarity claims.
- preview, baseline, and refined correspond to 0.40 m, 0.20 m, and 0.15 m target air cells. paper_reference is visible as 0.10 m but locked before any grid allocation.
- The fixed ALE box is x=[-23,10], y=[-10,10], z=[0,12] m. Its z_min face is a dedicated *BOUNDARY_SPC_SET with only dofz=1; exactly the other five faces use *BOUNDARY_NON_REFLECTING.
- TNT is 35 kg at (-20, 0, 0.6) m and uses the current Phase18 density of 1630 kg/m³. Persist both the mass-conserving cuboid and its equal-volume sphere metadata.
- The rigid gable target is x=[0,4.5], y=[-4.5,4.5], with 6 m eaves and a 9.4 m ridge. The left roof overhang is a real 0.6 m sloped shell whose outer edge is y=-5.1, z=5.546666666666667 m.
- The hidden bottom seal closes the rigid core but is excluded from FSI and surface gauges. The overhang is included in FSI.
- Bind all 9 paper free-field gauges and 10 representative surface gauges to 19 distinct air ALE cells. Emit one *SET_SOLID_LIST_TITLE containing all 19 element IDs and one matching *DATABASE_HISTORY_SOLID_SET.
- materials.k is the only file allowed to own *MAT* or *EOS* cards. It contains only air, TNT, and rigid-building material roles and the air/TNT EOS cards.
- Use 0.100 s termination, 0.00005 s pressure-history interval, and 0.0005 s D3PLOT interval.
- Persist validation_status=research_candidate, solver_ready=false, requires_project_review=true, and engineering_validated=false together with every modeling assumption distinguished from paper evidence.
- Keep compile_solver_blast_deck(DetailedBuildingPackage, config, output_dir) and all existing Phase18 outputs and validation behavior unchanged.
- Existing user changes outside this feature are out of scope. Do not rewrite, clean, reset, or commit them.

## Execution Setup

- [ ] Work in the existing clean worktree E:\workplace\codex_mcp_k\.worktrees\literature14-blast-baseline on branch codex/literature14-blast-baseline.
- [ ] Merge the current optimized branch with git merge --no-edit codex/phase15-conforming-air-gap. If baseline.md conflicts, retain the v2 file from the optimized branch; inspect every other conflict rather than taking a whole-side resolution.
- [ ] Initialize the SDD workspace with plan identity docs/superpowers/plans/2026-08-22-literature14-rigid-blast-baseline-v2.md under .superpowers/sdd/2026-08-22-literature14-rigid-blast-baseline-v2/.
- [ ] Record the pre-existing partial implementation (lsprepost_mcp/blast_baseline/) in the ledger. Treat it as migration input, not as accepted v2 behavior.
- [ ] Run the existing Phase15/Phase18 regression slice before changing production code:

~~~powershell
python -m pytest -p no:cacheprovider tests/test_phase15_materials.py tests/test_phase18_solver_blast_contracts.py tests/test_phase18_solver_blast_scene.py tests/test_phase18_solver_blast_buildings.py tests/test_phase18_solver_blast_keyword.py tests/test_phase18_solver_blast_validation.py tests/test_phase18_solver_blast_provider.py tests/test_phase18_solver_blast_script.py -q
~~~

---

## Task 1: Migrate the partial baseline into strict v2 contracts and catalog

**Files:**

- Create: lsprepost_mcp/blast_baselines/__init__.py
- Create: lsprepost_mcp/blast_baselines/contracts.py
- Create: lsprepost_mcp/blast_baselines/catalog.py
- Create: lsprepost_mcp/blast_baselines/resources.py
- Create: resources/blast_baselines/literature14_v2_gable_35kg/baseline.json
- Create: resources/blast_baselines/literature14_v2_gable_35kg/rigid_building.json
- Test: tests/test_blast_baselines_contracts.py
- Test: tests/test_blast_baselines_catalog.py
- Retire after parity: lsprepost_mcp/blast_baseline/ and its v1-only tests/resources

- [ ] Write failing tests that import only the plural package and assert one catalog entry with baseline_id=literature14_v2_gable_35kg, version=2.0.0, qualified version literature14-v2-gable-35kg@2.0.0, fixed charge/building/ALE values, 0.40/0.20/0.15 m generatable profiles, and locked 0.10 m paper profile.
- [ ] Assert fixed-domain base estimates of about 124,500, 990,000, 2,358,400, and 7,920,000 elements are labeled as estimates and never substituted for actual refined counts.
- [ ] Test strict closed-field parsing, finite-number validation, positive dimensions, immutable returned values, stable ordering, and duplicate catalog/resource rejection.
- [ ] Test material bindings contain exactly air, tnt_high_explosive, and rigid_building; reflecting_ground_plane and nonreflecting_air_boundary are boundary presets, while rigid_ground, soil, concrete, and steel roles are absent.
- [ ] Run those tests and capture the expected import/assertion failure before adding production files.
- [ ] Implement frozen, slotted values with an explicit profile contract:

~~~python
@dataclass(frozen=True, slots=True)
class BaselineGridProfile:
    name: Literal["preview", "baseline", "refined", "paper_reference"]
    target_cell_size_m: float
    generatable: bool
    locked_reason: str | None
~~~

- [ ] Make JSON resources descriptive and hashable while Python validation remains the trust boundary. Bind air/TNT to the current Phase15/18 owner and give the rigid target a versioned preset; do not duplicate historical 1550 kg/m³ TNT data.
- [ ] Replace v1 imports/resources with the plural package only after new tests pass. Do not leave a second registry with divergent values.
- [ ] Run python -m pytest -p no:cacheprovider tests/test_blast_baselines_contracts.py tests/test_blast_baselines_catalog.py -q and commit the task.

## Task 2: Build the real rigid target, gauge definitions, and authoritative preview

**Files:**

- Create: lsprepost_mcp/blast_baselines/geometry.py
- Create: lsprepost_mcp/blast_baselines/gauges.py
- Create: lsprepost_mcp/blast_baselines/preview.py
- Test: tests/test_blast_baselines_geometry.py
- Test: tests/test_blast_baselines_gauges.py
- Test: tests/test_blast_baselines_preview.py

- [ ] First write geometry tests for positive-area shared-node shells, exact wall/eave/ridge extents, closed core edge incidence, and a separate open overhang attached along the left eave.
- [ ] Assert the overhang follows the roof pitch, its outer edge is 0.6 m from the wall, and its elevation is 6 - 0.6 * (3.4 / 4.5).
- [ ] Assert fsi_shell_ids equals exposed_core_shell_ids union overhang_shell_ids; the hidden seal remains in the rigid core but not FSI or pressure-surface candidates.
- [ ] Define all 9 free-field and 10 representative surface gauge targets from the exact table in baseline.md. Test names, stable order, surface groups, and outward unit normals derived from geometry.
- [ ] Lock Ps01–Ps09 to x=-12,-9,-6 m, y=0, with z=0.3,1.0,2.0 m in distance-major order.
- [ ] Lock surface targets to front (0,0,1.5/4.5/7.5), sides (2.25,-4.5/4.5,3.0), roofs (2.25,-2.25/2.25,7.7), and rear (4.5,0,1.5/4.5/7.5), with the exact fixed/derived outward normals in baseline.md.
- [ ] Keep target and sampled coordinates distinct. Use one rule for every surface gauge:

~~~python
h_local = min(bound_cell.dx, bound_cell.dy, bound_cell.dz)
sample_m = target_m + outward_unit_normal * (0.51 * h_local)
~~~

- [ ] Build preview primitives from the same immutable geometry and gauges used by compilation. Return exactly building, overhang, air_domain, tnt, ground, free_field_gauges, and surface_gauges.
- [ ] Prove preview includes the true overhang, TNT cuboid and equal-volume sphere metadata, a visual ground plane without ground material/solid, and target/sample gauge positions.
- [ ] Run all three files, observe red before implementation and green afterward, then commit.

## Task 3: Extract compatibility-protected TNT/material/ALE primitives

**Files:**

- Modify: lsprepost_mcp/phase15_materials.py
- Modify: lsprepost_mcp/refined_building/solver_blast/charge.py
- Create: lsprepost_mcp/refined_building/solver_blast/ale_grid.py
- Modify: lsprepost_mcp/refined_building/solver_blast/ale_domain.py
- Modify only as delegation wrappers: lsprepost_mcp/refined_building/solver_blast/materials.py
- Test: tests/test_phase15_materials.py
- Test: tests/test_phase18_solver_blast_charge.py
- Test: tests/test_phase18_solver_blast_ale_grid.py
- Test: tests/test_phase18_solver_blast_keyword.py

- [ ] Before refactoring, add regression tests that freeze compile_solver_blast_deck signature, input rejection, single-file layout, material text, boundary semantics, and deterministic representative output.
- [ ] Run regressions against untouched code and record green in the task report.
- [ ] Add a configuration-independent TNT constructor and retain the old delegating wrapper:

~~~python
def build_mass_conserving_tnt(
    *,
    mass_kg: float,
    position_m: tuple[float, float, float],
    detonation_time_s: float,
    occupied_volumes: tuple[OccupiedVolume, ...],
) -> ChargeModel: ...
~~~

- [ ] Extract an air/TNT-only renderer from the Phase15 owner. Make Phase18 delegate without byte changes or loss of its eight existing roles. Baseline appends only *MAT_RIGID.
- [ ] Implement immutable StructuredAleGrid and AleCellBinding values without adding baseline fields to SolverBlastConfig.
- [ ] Reject budget overflow from an upper-bound count before materializing coordinates. Preserve TNT three-cells-per-axis refinement and 6,000,000-element/8,000,000-node limits.
- [ ] Bind using bisect_right(axis, value)-1, clamp an exact maximum to the last cell, and calculate ID as element_id_start + (iz * ny + iy) * nx + ix. Reject out-of-bounds and TNT gauge cells.
- [ ] Add iterators for named ALE faces and their nodes. Preserve the old auto-margin estimator and six-face wrapper; baseline explicitly selects five faces plus z_min nodes.
- [ ] Run all listed tests and the Phase18 slice, then commit only with demonstrated compatibility.

## Task 4: Bind 19 gauges and compile a modular, reparseable K package

**Files:**

- Create: lsprepost_mcp/blast_baselines/materials.py
- Create: lsprepost_mcp/blast_baselines/compiler.py
- Create: lsprepost_mcp/blast_baselines/validation.py
- Test: tests/test_blast_baselines_materials.py
- Test: tests/test_blast_baselines_compiler.py
- Test: tests/test_blast_baselines_validation.py

- [ ] Write failing tests with a small fixed-grid fixture while retaining real geometry/charge and real keyword paths.
- [ ] Test all 19 sampled points bind to distinct air elements for each generatable profile; persist ID, indices, cell bounds, centroid, target, sample, and local size.
- [ ] Test the exact include graph and order:

~~~text
main.k
  materials.k
  rigid_gable_building.k
  ale_air_tnt.k
  boundaries_fsi.k
  pressure_gauges.k
~~~

- [ ] Implement compile_rigid_baseline_deck(target: RigidCalibrationTarget, ..., output_dir: Path) as a distinct entry point. Reject nonempty destinations and never accept DetailedBuildingPackage or invoke target-specific refined scene/FSI code.
- [ ] Stream ALE nodes/elements and SHA-256 to disk; never construct the whole ALE include in memory.
- [ ] Assert the locally refined TNT region has at least 3 cells on each axis and at least 27 TNT solids, and its discretized volume times 1630 kg/m³ reconstructs exactly 35 kg within the declared tolerance.
- [ ] Emit only air/TNT/rigid roles. Assert materials.k solely owns every *MAT and *EOS keyword; represent the building with *MAT_RIGID and fixed rigid-body freedoms, not an elastic substitute.
- [ ] Emit hidden seal as rigid but not FSI; emit real overhang as rigid and FSI-exposed.
- [ ] Emit z_min nodes in *SET_NODE_LIST_TITLE and *BOUNDARY_SPC_SET with translation flags (0,0,1). Emit non-reflecting segment sets for only x_min, x_max, y_min, y_max, and z_max.
- [ ] Allow side segments to share edge nodes with z_min, but never put a z_min face segment into a non-reflecting set.
- [ ] Emit exactly one titled solid set containing all 19 gauge element IDs and one matching *DATABASE_HISTORY_SOLID_SET request. Assert 19 unique air element IDs and no TNT element.
- [ ] Emit *CONTROL_TERMINATION at 0.100 s, pressure histories at 0.00005 s, and *DATABASE_BINARY_D3PLOT at 0.0005 s.
- [ ] Implement an independent line-streaming validator for includes, continuous ranges, material ownership/references, rigid/FSI membership, face counts, bottom DOFs, output intervals, gauge/history cards, and closure.
- [ ] Validate the small fixture and real 0.40 m preview profile, run Task 4 tests, and commit.

## Task 5: Add deterministic content-addressed snapshots and the service boundary

**Files:**

- Create: lsprepost_mcp/blast_baselines/store.py
- Create: lsprepost_mcp/blast_baselines/service.py
- Modify: the existing application configuration module that owns workspace paths
- Test: tests/test_blast_baselines_store.py
- Test: tests/test_blast_baselines_service.py

- [ ] Write failures for read-only list/detail/preview/validate, lock-before-allocation, generate-only writes, deterministic reuse, tamper rejection, and concurrent same-identity generation.
- [ ] Use exact canonical identity encoding:

~~~python
identity_bytes = json.dumps(
    generation_identity,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
).encode("utf-8")
full_identity_sha256 = hashlib.sha256(identity_bytes).hexdigest()
~~~

- [ ] Include baseline ID/version, complete profile, air/TNT/rigid IDs/versions/SHA-256, and geometry/gauge/compiler/keyword schema versions. Exclude times, paths, random values, PIDs, and temporary names.
- [ ] Derive snapshot_id exactly as baseline_ + full_identity_sha256[0:24].
- [ ] Publish beneath workspace/baselines/literature14_v2_gable_35kg/<snapshot_id>/. Never accept caller output paths.
- [ ] Under a snapshot lock, verify recorded hashes before reuse. Otherwise compile in a sibling temp directory, stream-validate, write preview.json/static_validation.json/final manifest.json, revalidate, and publish with os.replace.
- [ ] Avoid self-reference: manifest files cover the six K files plus preview.json and static_validation.json, not manifest.json. Reuse checks full identity, eight hashes, and manifest structure.
- [ ] Return collision/tamper errors for mismatches; never overwrite or silently reuse.
- [ ] Return solver_ready: false in detail, validation, generation, and manifest responses.
- [ ] Run store/service tests, including a subprocess spy that fails if called, and commit.

## Task 6: Expose an isolated HTTP API and one strict MCP facade

**Files:**

- Create: lsprepost_mcp/web/blast_baselines_api.py
- Modify: lsprepost_mcp/web/app.py
- Modify: lsprepost_mcp/tools.py
- Modify only if required: lsprepost_mcp/server.py
- Test: tests/test_blast_baselines_web_contract.py
- Test: tests/test_blast_baselines_mcp.py
- Test: tests/test_blast_baselines_dependency_boundaries.py

- [ ] Write failing HTTP tests for list/detail and POST preview/validate/generate under /api/blast-baselines.
- [ ] Assert {ok: true, result: ...}, structured 4xx, JSON 405 throughout the prefix, strict fields, locked-profile errors, and rejection of solve/evaluate/output-path/executable fields.
- [ ] Register one blast_baselines MCP tool with action list|detail|preview|validate|generate. Enforce action-specific keys in the tool.
- [ ] Share one BlastBaselineService between API and MCP; do not duplicate domain decisions.
- [ ] Add an AST/import-boundary test excluding refined catalogs/providers/stores, evaluators, runners, and subprocess launchers.
- [ ] Run new and existing web/MCP contracts and commit.

## Task 7: Add the independent “文献基准实验” frontend workbench

**Files:**

- Modify: lsprepost_mcp/web/static/index.html
- Modify: lsprepost_mcp/web/static/app.js
- Create: lsprepost_mcp/web/static/blast_baselines_workbench.js
- Create: lsprepost_mcp/web/static/blast_baselines_viewer.js
- Create: lsprepost_mcp/web/static/blast_baselines_workbench.css
- Create: lsprepost_mcp/web/tests/blast-baselines-workbench.runtime.cjs
- Create: lsprepost_mcp/web/tests/blast-baselines-viewer.runtime.cjs
- Extend: tests/test_blast_baselines_web_contract.py

- [ ] Add failing DOM/runtime tests for a visible “文献基准实验” entry, independent /blast-baselines route, lazy lifecycle, accessible controls/status, and no solve/evaluate UI.
- [ ] Show all profiles, mark paper_reference locked, and prevent its request before network dispatch.
- [ ] Provide only detail, preview, validation, and generation actions. Show snapshot metadata and solver_ready=false, not solver progress.
- [ ] Adapt seven neutral layers to existing createModelViewer in model_viewer_webgl.js; do not create another renderer.
- [ ] Give each request an AbortController, ignore late results with a mount token, and abort/dispose on unmount.
- [ ] Keep generation disabled until static validation has passed for the currently selected scene/profile identity.
- [ ] Preserve refined-blast routing and lifecycle without importing or mutating refined state.
- [ ] Run Python contracts and both CJS suites with bundled Node, then commit.

## Task 8: Generate the real model, verify the whole feature, and close review findings

**Files:**

- Create but do not commit large artifacts: workspace/baselines/literature14_v2_gable_35kg/<snapshot_id>/...
- Modify as needed: README.md and focused developer/API documentation
- Test: tests/test_blast_baselines_integration.py

- [ ] Add end-to-end service generation at 0.40 m into a temp store, reparse modules, and independently compare counts/hashes/identity.
- [ ] Generate the real 0.20 m baseline snapshot in configured workspace. Confirm all six K modules plus preview.json, static_validation.json, and manifest.json.
- [ ] Reinspect from disk and record snapshot ID, nodes/elements, reconstructed TNT mass, 19 bindings, boundary counts, and every SHA-256. Do not run a solver.
- [ ] Verify identical generation reuses bytes and a tampered copy is rejected.
- [ ] Run focused baseline tests, the Phase15/Phase18 regression slice, then python -m pytest -p no:cacheprovider -q.
- [ ] Run frontend build/runtime tests with bundled Node/pnpm.
- [ ] Scan for forbidden solver/evaluator/process surface and placeholders, then run git diff --check.
- [ ] Request whole-branch review against baseline.md, fix findings test-first, rerun affected/full suites, and obtain a clean re-review.
- [ ] Use verification-before-completion before reporting success. Report model-generation evidence only.

## Definition of Done

- Frontend, HTTP, and MCP expose one v2 baseline, three generatable profiles, and one visibly locked paper profile.
- Preview and K modules derive from one geometry/gauge/grid authority and agree on coordinates, roles, IDs, and counts.
- The 0.20 m package is generated, content-addressed, byte-reusable, independently stream-reparsed, and statically valid.
- Phase18 compilation and existing tests remain unchanged and green.
- No solver/evaluator/external-process capability is added, and solver_ready remains false.
- Generated metadata reports research_candidate, requires_project_review=true, and engineering_validated=false without presenting assumptions as paper measurements.
