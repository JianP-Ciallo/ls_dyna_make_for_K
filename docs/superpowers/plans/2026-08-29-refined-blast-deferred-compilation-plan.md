# Refined Blast Deferred Compilation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make draft save and browser preview lightweight while reserving full detailed-building compilation for K-package generation and preserving editable TNT coordinates.

**Architecture:** Keep legacy create protocol `@1` unchanged and add deferred protocol `@2`. Deferred projects persist a tagged building-definition fingerprint and compilation state, use a deterministic proxy preview/validation path, and atomically materialize the real artifact fingerprint during generation.

**Tech Stack:** Python dataclasses and JSON store, Phase18 refined-blast service, browser ES modules, Node runtime harness, Pytest.

**Spec:** `docs/superpowers/specs/2026-08-29-refined-blast-deferred-compilation-design.md`

## Global Constraints

- Save and preview must not call `compile_detailed_building_asset` for deferred projects.
- Full detailed compilation occurs only from the generate route.
- Legacy create `refined_blast_create@1` and persisted metadata v2 remain readable.
- Lightweight preview is non-solver evidence and must preserve the strict nine-layer web contract.
- Generation consumes the latest persisted `charge_position_m`.

---

### Task 1: Deferred create and save authority

**Files:**
- Modify: `lsprepost_mcp/web/refined_blast_api.py`
- Test: `tests/test_phase18f_api.py`

**Interfaces:**
- Produces: `refined_blast_create@2`, tagged definition fingerprint, metadata compilation state, and a project-record operation that verifies storage without compiling.

- [ ] Add failing tests that patch `_compile_building_package`/`_compile_building` to raise and assert `@2` create, GET, and save succeed without compiler calls.
- [ ] Run the focused tests and verify they fail because `@2` is unsupported.
- [ ] Implement version dispatch, v3 metadata compatibility, pending definition identity, and non-compiling project-record verification.
- [ ] Run the focused tests and the full `tests/test_phase18f_api.py` module.

### Task 2: Deterministic lightweight preview and validation

**Files:**
- Modify: `lsprepost_mcp/refined_blast/preview.py`
- Modify: `lsprepost_mcp/web/refined_blast_api.py`
- Test: `tests/test_phase18f_api.py`
- Test: `tests/test_phase18e_validation_preview.py`

**Interfaces:**
- Produces: `build_lightweight_refined_blast_preview(...) -> RefinedBlastPreview` and configuration-only validation/generation gate payloads.

- [ ] Add failing API tests asserting preview and validation do not invoke the compiler and that preview includes structure, visible fluid domain, ground, and the persisted TNT position.
- [ ] Run the focused tests and verify the current service path compiles.
- [ ] Implement deterministic proxy geometry using existing neutral primitive helpers and strict preview fingerprints.
- [ ] Implement configuration-only provider normalization and non-blocking validation for deferred projects.
- [ ] Run preview, API, and web projection tests.

### Task 3: Materialize and generate from the latest TNT configuration

**Files:**
- Modify: `lsprepost_mcp/web/refined_blast_api.py`
- Test: `tests/test_phase18f_api.py`
- Test: `tests/test_phase18_solver_blast_provider.py`

**Interfaces:**
- Consumes: pending metadata from Task 1 and strict persisted scenario state.
- Produces: atomically materialized artifact identity and generated package whose manifest contains current `charge_position_m`.

- [ ] Add a failing test that saves a changed TNT position after create, generates, and asserts exactly one detailed compile plus the updated position in the generated package.
- [ ] Run the focused test and verify it fails on the old eager-create path.
- [ ] Add locked materialization of project, metadata, and transaction identity; reuse one `DetailedBuildingPackage` for solver-complete K generation.
- [ ] Run focused generation tests and all Phase18F API tests.

### Task 4: Save timeout, abort lifecycle, and TNT editing continuity

**Files:**
- Modify: `lsprepost_mcp/web/static/refined_blast_state.js`
- Modify: `lsprepost_mcp/web/static/refined_blast_workbench.js`
- Test: `web/tests/refined-blast-state.runtime.cjs`
- Test: `web/tests/refined-blast-workbench.runtime.cjs`
- Test: `tests/test_phase18f_web_contract.py`

**Interfaces:**
- Produces: `store.save(..., {signal})`, a 10-second save deadline, unmount cancellation, and deferred create payload `@2`.

- [ ] Add failing runtime cases for save signal forwarding, timeout cleanup, unmount abort, and X/Y/Z edits on `charge_position_m`.
- [ ] Run each runtime case through the bundled Node executable and verify RED.
- [ ] Implement save request options, save controller/deadline cleanup, explicit timeout status, and `@2` payload selection.
- [ ] Preserve the existing three-axis schema editor and preview drag path so both update the same draft value.
- [ ] Run all relevant browser runtime and Python web-contract tests.

### Task 5: Regression and integration verification

**Files:**
- Modify if needed: the files above only.

**Interfaces:**
- Produces: evidence that legacy and deferred routes coexist without regressing Phase18.

- [ ] Run `python -m pytest tests/test_phase18f_api.py tests/test_phase18f_web_contract.py tests/test_phase18e_validation_preview.py -q --basetemp .pytest_tmp_deferred_final`.
- [ ] Run every relevant Node runtime case using the bundled Node executable.
- [ ] Run `git diff --check` and inspect the final diff for accidental changes.
- [ ] Record exact passing commands and any intentionally retained research/review flags in the final handoff.

