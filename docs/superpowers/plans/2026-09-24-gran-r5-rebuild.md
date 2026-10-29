# GRAN_R5 MM-ALE reconstruction implementation plan

> **For agentic workers:** Use superpowers:executing-plans. The user approved the reconstruction design and implementation on 2026-09-24.

**Goal:** Regenerate the source model's mesh analytically and assemble its unchanged physical definitions through project generation, with registered resources, comparison, and previews.

**Architecture:** A source-pinned nonmesh resource bundle, a conforming analytic multiblock mesh using the existing Phase15 grid builder, and a dedicated project compiler/validator. Existing material/structural queries, project writing, provenance and previews receive additive adapters.

**Tech Stack:** Python standard library, existing project grid/writer, pytest; matplotlib for comparison plots only.

**Spec:** `workspace/imports/gran_r5_49abb80e7528/analysis_and_rebuild_plan.zh-CN.md` (approved).

## Global constraints

- Source hash: 49abb80e7528981f8d1b26d902225f674263ca7f49294084a3a5a1931251dfa3. SI confirmed; preserve MT=41 and its blank fields. User material implementation unavailable.
- No source node or element table may enter the generation path. Geometry is the measured 0.04 m charge inside the 0.9 m × ±0.9 m radial/axial domain.
- No added physical boundary/contact/air definitions. New mesh must share the material interface and have positive Jacobians.
- Preserve current uncommitted work. No cleanup, commits, worktree replacement, full regression, heavy cases or solver runs.
- Implement in the current working tree because the approved local project contains needed uncommitted changes. Keep pre-edit copies of touched files under the audit directory.

## Review focus

1. Source records with a recomputed but changed hash must not pass the pinned source contract.
2. Unknown mesh/geometry options must fail rather than silently falling back.
3. Shared curved interfaces must remain topologically connected, including their axial endpoints.
4. Altered generated mesh/card content must fail validation and regeneration checks.
5. Preview readiness must not imply solver readiness while MT=41 is unresolved.

## Task 1 — raw resource registration

Files: new `lsprepost_mcp/source_rebuild_resources.py`; additive adapters in `materials.py`, `structural_resources.py`; source-only JSON assets in distinct material and structural library directories.

Interfaces: `load_bundle() -> list[dict]`, `validate_resource(record) -> dict`, `register_source(path) -> dict`, `publish_resources(records, root) -> dict`. A fixed index binds IDs, source spans, card digests, categories and dependencies. Publication checks all conflicts before exclusive file creation. It never overwrites existing content.

- [x] Add tests rejecting modified cards even when their declared hash is recomputed, and rejecting publication conflicts.
- [x] Run these tests and capture expected missing-implementation failure.
- [x] Implement byte-preserving extraction after source SHA verification; exclude all mesh cards. Register 17 resources covering 18 cards.
- [x] Verify raw cards, original IDs, SI identity conversion, internal closure and missing external MT=41 implementation.

## Task 2 — analytic mesh and compiler

Files: new `gran_r5_mesh.py`, `gran_r5_rebuild.py`, `tests/test_gran_r5_rebuild.py`.

Interfaces: `build_mesh(mesh) -> dict`, `audit_mesh(nodes, elements) -> dict`, `default_spec(name, **mesh_parameters) -> dict`, `build_keyword(spec) -> (text, metadata)`.

- [x] Test the small case n=2, charge_layers=2, concrete_layers=3: 541 nodes, 490 quads (24 explosive, 466 surrounding), 8 shared material edges and one connected component.
- [x] Verify positive signed areas and corner/Gauss Jacobians, total section area 1.62 m², and positive axisymmetric volumes.
- [x] Use the existing Phase15 rectangular grid for a central rectangle, four analytic charge bands, four concrete bands and three far-field rectangles. Merge by rounded analytic coordinates; assign newly generated IDs starting at 1,000,001.
- [x] Preserve original nonmesh payload lines and order; normalize only line endings. Generate node/element cards from the newly generated in-memory mesh.
- [x] Strictly reject unknown options, nonfinite inputs, invalid subdivisions, oversized requested meshes and alternative physics.

## Task 3 — project and tool integration

Files: additive branches in `project_store.py`, `provenance.py`, `tools.py`; dedicated module CLI.

- [x] Add tests for real project writing, tampered-node rejection, unchanged raw UMAT, and preview/solver readiness distinction.
- [x] Route the new compiler through `write_compiled_keyword_project`, expose prepare/generate tools, and support `python -m lsprepost_mcp.gran_r5_rebuild`.
- [x] Static validator parses the actual generated deck and compares it to a deterministic fresh compile. Provenance independently re-compiles model.json. Record unresolved physics as explicit warnings and block solver readiness.
- [x] Run new and directly affected existing tests only. Save JUnit evidence; no full/heavy switches.

## Task 4 — actual reconstruction and delivery

- [x] Generate the 49,000-element requested model after small-case checks. The target generation is the requested artifact, not a heavy test case.
- [x] Run project static validation and `scripts/verify_generated_k.ps1`; confirm model.json regeneration matches.
- [x] Compare old/new mesh geometry, topology, material mappings and every nonmesh card; produce project preview and source/new comparison plot.
- [x] Attempt project LS-PrePost keyword reader/PNG validation, with bounded timeout and no solver.
- [x] One independent review of the targeted diff and artifacts; fix blocking findings with focused checks.
- [x] Deliver actual K/JSON/checks/preview/reproduction paths and explicitly list missing user material implementation and unrun solver checks.

## Ledger

- 2026-09-24: User approved the prior concrete plan and source changes. Execution stays inline to honor the minimal-subagent preference; only one independent final review.
- The Windows sandbox helper currently fails initialization. Shell read/write operations use reviewed escalation, confined to authorized source reads and project edits.

- 2026-09-24 completed: 17 source-reference resources registered (18 nonmesh blocks); analytic mesh generated through the project writer at workspace/projects/GRAN_R5_2D_MMALE_6MM_rebuilt.
- Targeted compatibility: 59 passed and 36 subtests passed; see workspace/imports/gran_r5_49abb80e7528/rebuild_compatibility.xml. No full/heavy/solver runs.
- Static checks, deterministic provenance, source-card comparison and actual LS-PrePost import/PNG passed. One independent review; compatibility findings fixed with targeted evidence.
- Remaining limitation: MT=41 implementation unavailable; solver and production readiness remain false. Low-impact geometry JSON bool-equality strictness suggestion is recorded in implementation_review.zh-CN.md.
- Delivery report: workspace/projects/GRAN_R5_2D_MMALE_6MM_rebuilt/REBUILD_REPORT.zh-CN.md.
