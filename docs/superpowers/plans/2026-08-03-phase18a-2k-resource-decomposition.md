# Phase 18A 2.k Resource Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream-parse the 68.5 MB `2.k` deck, audit its dependency graph and publish only reviewed, traceable resources into the project material and model libraries.

**Architecture:** Add a standalone streaming decomposition module instead of increasing the existing 10 MiB whole-project import limit. It emits an ignored runtime audit package, while reviewed normalized assets are version-controlled separately and remain explicitly non-engineering-validated.

**Tech Stack:** Python standard library, `unittest`, existing LS-DYNA card renderers and project JSON conventions.

## Global Constraints

- The original `E:\Desktop\2.k` is read-only and must not be copied into Git.
- Source identity is SHA-256 `C1C02A9E832852854B47CD3720BC9348CF48989484D25E1A54036836D0697A22`.
- Source units are inferred as `tonne_mm_s_N_MPa`; normalized assets use `SI_m_s_kg_N_Pa` and retain original values.
- External K resources remain quarantined until dependency, unit and provenance review passes.
- Beam N3 orientation nodes must never be merged as ordinary duplicate topology nodes.
- Existing city generation behavior is outside this plan and must not change.

---

### Task 1: Streaming deck index and dependency graph

**Files:**
- Create: `lsprepost_mcp/keyword_decomposition.py`
- Create: `tests/test_keyword_decomposition.py`
- Create: `tests/fixtures/phase18/2k_minimal_reference.k`

**Interfaces:**
- Produces: `decompose_keyword_deck(path: Path, source_units: str) -> dict[str, object]`
- Produces: `write_decomposition_package(report: dict[str, object], output_dir: Path) -> dict[str, str]`

- [ ] Write a failing fixture test asserting literal keyword counts, Part→Section→Material/EOS references, Beam endpoint/N3 roles, exact coordinate duplicate classification and orphan-node classification.
- [ ] Run `python -m unittest tests.test_keyword_decomposition -v` and verify failure because the module is absent.
- [ ] Implement a line-streaming tokenizer and fixed-width/csv numeric field parser; do not call `Path.read_text()` or `splitlines()` on the full deck.
- [ ] Implement Part, Section, MAT, EOS, Curve, Solid, Beam, Node, Set and constrained-coupling indexing with source line spans.
- [ ] Run the focused test and verify it passes.
- [ ] Add malformed reference and unsupported-card tests; verify each test fails before adding the corresponding validation.

### Task 2: Unit normalization and usable-resource audit

**Files:**
- Modify: `lsprepost_mcp/keyword_decomposition.py`
- Modify: `tests/test_keyword_decomposition.py`

**Interfaces:**
- Produces: `normalize_2k_resource(candidate: dict[str, object]) -> dict[str, object]`
- Produces: `classify_resources(report: dict[str, object]) -> dict[str, list[dict[str, object]]]`

- [ ] Write failing table-driven tests with hand-derived conversions: `7.85e-9 tonne/mm^3 → 7850 kg/m^3`, `210000 MPa → 210e9 Pa`, `8193000 mm/s → 8193 m/s`, and `640000 MPa → 640e9 Pa`.
- [ ] Implement explicit conversion functions that return original value, factor, normalized value and unit labels.
- [ ] Write failing tests proving referenced MAT/EOS/Curve/erosion cards form a closed bundle and unused RHT/elastic/D16 resources remain audit-only.
- [ ] Implement used, dependency, unused and unsupported classifications.
- [ ] Run the focused suite and verify all tests pass.

### Task 3: Generate and independently verify the real 2.k audit package

**Files:**
- Create: `scripts/decompose_keyword_resources.py`
- Modify: `tests/test_keyword_decomposition.py`
- Runtime output only: `workspace/imports/phase18_2k_c1c02a9e8328/`

**Interfaces:**
- CLI: `python scripts/decompose_keyword_resources.py --input E:\Desktop\2.k --output workspace\imports\phase18_2k_c1c02a9e8328 --source-units tonne_mm_s_N_MPa`

- [ ] Write a failing CLI integration test using the minimal fixture and asserting the four JSON outputs and source hash.
- [ ] Implement the CLI with explicit input/output paths, no overwrite by default, and atomic JSON writes.
- [ ] Run the CLI integration test and verify it passes.
- [ ] Run the CLI on the real deck and compare literal totals with the independent audit: 461,452 nodes, 348,801 elements, 1,271 N3 duplicate-coordinate pairs and 13,592 orphan nodes.
- [ ] Inspect `audit_report.json` for unsupported or dangling dependencies; block publication if any used resource is unresolved.

### Task 4: Publish reviewed structural material assets

**Files:**
- Create: `resources/materials/concrete_kc_2k_reference.json`
- Create: `resources/materials/rebar_d8_mat003_2k_reference.json`
- Create: `resources/materials/rebar_d12_mat003_2k_reference.json`
- Create: `resources/materials/rebar_d20_mat003_2k_reference.json`
- Modify: `lsprepost_mcp/materials.py`
- Modify: `lsprepost_mcp/dyna_cards.py`
- Modify: `tests/test_materials.py`

**Interfaces:**
- `get_material(material_id)` returns normalized provenance and type-specific parameters.
- `resolve_material({"name": material_id})` validates advanced library entries without requiring duplicate user fields.
- `material_lines(spec)` renders `concrete_damage_rel3` and `plastic_kinematic` cards in project SI units.

- [ ] Write failing tests for all four material assets, exact normalized values, source hash, original MID, status and project-review warning.
- [ ] Write a failing golden-card test for `plastic_kinematic`; verify the renderer lacks this branch.
- [ ] Extend type-dispatched library validation and rendering minimally to pass the tests.
- [ ] Run `python -m unittest tests.test_materials -v` and the relevant advanced-card tests.

### Task 5: Publish reviewed scenario and model-reference assets

**Files:**
- Create: `resources/materials/air_linear_polynomial_2k_reference.json`
- Create: `resources/materials/tnt_jwl_2k_reference.json`
- Create: `resources/model_library/phase18/2k_rc_frame_reference.json`
- Create: `resources/model_library/phase18/commercial_supermarket_rc_seed.json`
- Create: `tests/test_phase18_reference_assets.py`

**Interfaces:**
- Scenario material entries expose a typed MAT+EOS bundle and provenance.
- Model reference contains roles, section diameters, Part mappings, mesh statistics and coupling topology without raw full-mesh nodes/elements.

- [ ] Write failing asset-contract tests for required IDs, units, provenance, status, referenced dependencies and absence of raw 461k-node payloads.
- [ ] Generate candidate JSON from the audited runtime package, then manually review every published field against source line spans.
- [ ] Add the reviewed JSON assets using `syntax_unit_reviewed` and `requires_project_review=true`.
- [ ] Run the asset tests and verify they pass.

### Task 6: Regression and handoff gates

**Files:**
- Modify only if required by failures: focused production/test files from Tasks 1–5.

- [ ] Run `python -m unittest tests.test_keyword_decomposition tests.test_materials tests.test_phase18_reference_assets -v`.
- [ ] Run `python -m compileall -q lsprepost_mcp scripts`.
- [ ] Run the existing material, keyword-check and packaging boundary suites.
- [ ] Confirm `git diff --check` reports no whitespace errors.
- [ ] Compare the generated audit manifest to the source SHA-256 and independent counts one final time.
- [ ] Record unresolved engineering-validation items for Phase 18C–18F; do not label reference assets as blast-certified.
