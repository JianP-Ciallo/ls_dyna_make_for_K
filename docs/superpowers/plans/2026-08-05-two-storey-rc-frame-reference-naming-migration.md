# Two-Storey RC Frame Reference Naming Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace non-descriptive `2k_*` public resource names with the approved two-storey reinforced-concrete frame blast reference identity while retaining old IDs as read-compatible aliases.

**Architecture:** A small naming module owns the canonical IDs and legacy mappings. Generated manifests declare aliases; recursive resource loaders index canonical IDs and aliases separately, list canonical resources once, and resolve either form for get/validate/export. The source filename `2.k` remains provenance only, and review hashes are regenerated against canonical resources.

**Tech Stack:** Python 3 standard library, JSON resource manifests, LS-DYNA keyword gzip payloads, `unittest`, PowerShell packaging checks.

## Global Constraints

- Canonical family ID is exactly `two_storey_rc_frame_blast_reference`.
- `2.k` remains only as source provenance, historical evidence, and compatibility naming.
- Existing `2k_*` callers must continue to resolve without duplicate resource listings or duplicate published files.
- Physical values, source spans, source SHA-256 and mesh topology must remain byte/content equivalent except for human-readable K comments and filenames.
- No resource gains `engineering_validated`; `requires_project_review=true` remains.
- Work in the current feature branch because required Phase 18A-1/18B resources are not fully represented by HEAD; do not overwrite unrelated worktree changes.

---

### Task 1: Canonical Naming Contract and Alias Resolution

**Files:**
- Create: `lsprepost_mcp/phase18_reference_naming.py`
- Create: `lsprepost_mcp/resource_aliases.py`
- Modify: `lsprepost_mcp/model_library.py`
- Modify: `lsprepost_mcp/materials.py`
- Modify: `lsprepost_mcp/structural_resources.py`
- Test: `tests/test_phase18_reference_naming_migration.py`

**Interfaces:**
- Produces: `MODEL_RESOURCE_ALIASES`, `MATERIAL_RESOURCE_ALIASES`, `STRUCTURAL_RESOURCE_ALIASES`, canonical ID constants and display-name constants.
- Produces: `build_alias_index(resources, kind) -> dict[str, str]` and `resolve_resource_id(requested_id, resources, kind) -> tuple[str, JSONDict]`.
- Consumers: all three resource loaders and the Phase 18 generators.

- [x] **Step 1: Write failing behavior tests**

Add tests proving: canonical IDs are listed; every old ID resolves to the canonical resource; old and canonical model exports have identical bytes; aliases never appear as duplicate list rows; duplicate/colliding aliases raise `ValueError`.

- [x] **Step 2: Verify RED**

Run: `python -m unittest tests.test_phase18_reference_naming_migration -v`  
Expected: failures because canonical IDs and alias resolution do not exist.

- [x] **Step 3: Implement the naming and alias modules**

Define literal mappings from the approved design. `build_alias_index` validates `aliases` as a list of unique non-empty strings, rejects self-aliases and canonical/alias collisions, and maps alias to canonical ID. `resolve_resource_id` returns the canonical ID and canonical resource.

- [x] **Step 4: Integrate loaders**

Keep `load_*` dictionaries canonical-only. Make `get_model_resource`, `get_material`, `resolve_material`, `get_structural_resource`, validation and export resolve aliases before accessing the canonical dictionary. Public resource data retains canonical `id` and exposes `aliases`.

- [x] **Step 5: Verify GREEN**

Run: `python -m unittest tests.test_phase18_reference_naming_migration -v`  
Expected: all naming and alias tests pass.

### Task 2: Canonical Generators and Manifests

**Files:**
- Modify: `lsprepost_mcp/keyword_decomposition.py`
- Modify: `lsprepost_mcp/component_model_resources.py`
- Modify: `lsprepost_mcp/structural_resources.py`
- Modify: `lsprepost_mcp/phase18_resource_review.py`
- Modify: `lsprepost_mcp/config.py`
- Test: `tests/test_phase18_reference_naming_migration.py`
- Test: `tests/test_phase18a1_component_resources.py`
- Test: `tests/test_phase18b_structural_resources.py`

**Interfaces:**
- Consumes: Task 1 canonical constants and aliases.
- Produces: canonical material, structural, complete-model and component manifests with `aliases` and descriptive display names.
- Preserves: `_2k_material_assets`, `_2k_structural_assets` and `SOURCE_2K_SHA256` as compatibility symbols where existing tests/importers require them.

- [x] **Step 1: Add failing generator tests**

Assert literal canonical IDs, alias arrays, descriptive display names, canonical material dependencies, new payload filename and unchanged source SHA/mesh counts.

- [x] **Step 2: Verify RED**

Run: `python -m unittest tests.test_phase18_reference_naming_migration tests.test_phase18b_structural_resources -v`  
Expected: canonical manifest assertions fail against old generator output.

- [x] **Step 3: Update generators minimally**

Use canonical constants for every generated `id`, `name`, `display_name`, material dependency and component spec. Retain `provenance.source_name="2.k"`, add descriptive source display metadata, and write the complete payload as `two_storey_rc_frame_blast_reference.k.gz`.

- [x] **Step 4: Update structural closure validation**

Validate canonical five-resource families and canonical material bindings. Resolve old IDs before validation so compatibility inputs remain accepted.

- [x] **Step 5: Verify GREEN**

Run: `python -m unittest tests.test_phase18_reference_naming_migration tests.test_phase18a1_component_resources tests.test_phase18b_structural_resources -v`  
Expected: all run tests pass; tests requiring the source deck may run when `E:/Desktop/2.k` is present.

### Task 3: Import Entrypoints and Physical Resource Migration

**Files:**
- Create: `scripts/import_two_storey_rc_frame_blast_reference.py`
- Modify: `scripts/import_2k_resources.py`
- Move/regenerate: `resources/materials/phase18/two_storey_rc_frame_blast_reference/`
- Move/regenerate: `resources/model_library/references/phase18/two_storey_rc_frame_blast_reference/`
- Move/regenerate: `resources/model_library/components/phase18/two_storey_rc_frame_blast_reference/`
- Move/regenerate: `resources/model_library/structural/phase18/two_storey_rc_frame_blast_reference/`
- Test: `tests/test_phase18_reference_naming_migration.py`

**Interfaces:**
- Produces: `main(argv: list[str] | None = None) -> int` in the canonical import script.
- Preserves: `scripts/import_2k_resources.py` as a thin compatibility entrypoint calling the canonical `main`.

- [x] **Step 1: Add failing CLI/default-path tests**

Exercise parser/default path behavior without mocking generation; assert the canonical directory layout and ensure the old wrapper imports the same `main`.

- [x] **Step 2: Verify RED**

Run: `python -m unittest tests.test_phase18_reference_naming_migration -v`  
Expected: failure because the canonical script and paths do not exist.

- [x] **Step 3: Implement canonical CLI and compatibility wrapper**

Move argument parsing into the canonical script with injectable `argv`. Keep the old script to import and execute canonical `main`.

- [x] **Step 4: Regenerate canonical resources**

Run: `python scripts/import_two_storey_rc_frame_blast_reference.py E:/Desktop/2.k --component-packages`  
Expected: 6 materials, 5 structural resources, one complete reference and 4 component packages under canonical directories.

- [x] **Step 5: Remove old physical directories after exact target verification**

Verify each old path resolves beneath `E:/workplace/codex_mcp_k/resources`; remove only the four superseded `.../2k` or `2k_complete_reference` directories after canonical generation and count/hash comparison.

- [x] **Step 6: Verify canonical and alias calls**

Run: `python -m unittest tests.test_phase18_reference_naming_migration tests.test_phase18_resource_library -v`  
Expected: canonical lists and old alias calls both pass.

### Task 4: Review Manifest and Public Tool Compatibility

**Files:**
- Modify: `scripts/review_phase18_resources.py`
- Replace: `resources/reviews/phase18/two_storey_rc_frame_blast_reference_syntax_unit_review.json`
- Modify: `tests/test_phase18b_resource_review.py`
- Modify: `tests/test_jsonrpc.py`
- Modify: `tests/test_packaging_and_integration_boundaries.py`

**Interfaces:**
- Consumes: canonical material and structural dictionaries.
- Produces: exactly 11 canonical review records.
- Preserves: tool calls with old IDs by resolving before review lookup.

- [x] **Step 1: Add failing review/tool tests**

Assert 11 canonical records, zero old review IDs, `syntax_unit_reviewed` for canonical and alias queries, and canonical IDs in JSON-RPC list responses.

- [x] **Step 2: Verify RED**

Run: `python -m unittest tests.test_phase18b_resource_review tests.test_jsonrpc tests.test_packaging_and_integration_boundaries -v`  
Expected: failures against the old review path/IDs.

- [x] **Step 3: Update review configuration and script**

Point `PHASE18_REVIEW_MANIFEST` to the descriptive filename. Candidate generation reads canonical resources only; alias queries canonicalize before `apply_effective_review`.

- [x] **Step 4: Generate and verify the formal manifest**

Run candidate generation to a temporary workspace path, install it as the formal manifest, then run:  
`python scripts/review_phase18_resources.py --verify resources/reviews/phase18/two_storey_rc_frame_blast_reference_syntax_unit_review.json`  
Expected: `valid=true`, `resource_count=11`, `material_count=6`, `structural_count=5`.

- [x] **Step 5: Verify GREEN**

Run the Step 2 command again.  
Expected: all tests pass.

### Task 5: Documentation, Determinism and Regression Gate

**Files:**
- Modify: `docs/ROADMAP.zh-CN.md`
- Modify: `docs/reviews/phase18/PHASE18A1_COMPONENT_RESOURCE_REPORT.zh-CN.md`
- Modify: `docs/reviews/phase18/PHASE18B_RESOURCE_REVIEW.zh-CN.md`
- Modify: `docs/superpowers/specs/2026-08-03-phase18a-1-component-model-resource-design.md`
- Modify: `docs/superpowers/specs/2026-08-05-phase18b-library-organization-design.md`
- Test: existing Phase 18, packaging and integration tests

**Interfaces:**
- Produces: user-facing documentation that leads with the descriptive name and uses `2.k` only for provenance/history.

- [x] **Step 1: Update current documentation**

Add a naming migration table, canonical directory paths and alias policy. Do not rewrite historical source evidence; label `2.k` as the original filename where retained.

- [x] **Step 2: Run deterministic double regeneration**

Generate twice into separate temporary directories and compare relative filenames and bytes. Scan published JSON for local absolute paths and runtime `_path`/`_resource_dir` fields.

- [x] **Step 3: Run focused tests**

Run: `python -m unittest tests.test_phase18_reference_naming_migration tests.test_phase18a1_component_resources tests.test_phase18_resource_library tests.test_phase18b_structural_resources tests.test_phase18b_resource_review -v`

- [x] **Step 4: Run full regression and compile checks**

Run: `python -m unittest discover -s tests`  
Run: `python -m compileall -q lsprepost_mcp scripts`  
Expected: zero failures; environment-dependent skips reported separately.

- [x] **Step 5: Run packaging boundary check**

Run: `python -m unittest tests.test_packaging_and_integration_boundaries -v`  
Expected: canonical nested resources and review manifest are present; old physical resource directories are absent.

- [ ] **Step 6: Review and commit only migration-owned changes**

Use path-restricted staging. Do not stage unrelated pre-existing modifications in shared tracked files; report any Phase 18 migration changes left unstaged because they overlap unrelated work.
