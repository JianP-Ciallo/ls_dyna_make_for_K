# Phase 18F API Transaction Rebaseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Phase 18F project-scoped Web API operation linearizable across threads and processes and make Web route identifiers exactly match Store-safe identifiers.

**Architecture:** Add a re-entrant, per-root/per-project Store transaction context whose outer acquisition owns the existing hardened OS lock. Refactor the Web adapter so verification and the entire state-dependent route operation execute inside one project lease, and route dynamic segments consume the Store's shared identifier validator.

**Tech Stack:** Python context managers and thread-local state, existing hardened Windows/POSIX Store locks, `ThreadingHTTPServer` adapter, pytest, multiprocessing regression tests.

## Global Constraints

- Same-project operations are linearizable across threads and processes; unrelated project IDs remain concurrent.
- The project lease covers authority verification, business operation, integrity checks, and complete response snapshot construction.
- Nested Store/service calls reuse the outer project lease and must not reacquire the OS lock file.
- Project and scenario route IDs use the Store grammar `[A-Za-z0-9][A-Za-z0-9_.-]*`, excluding `.` and `..`.
- Existing response schemas, error codes, Phase 18E package bytes/fingerprints, Phase 18D fingerprints, legacy routes, host/origin/body gates, and external-launch policy remain unchanged.
- All production changes follow RED → GREEN TDD and receive independent task review before Phase 18F Task 2 begins.

---

### Task 1: Project operation lease and shared identifier grammar

**Files:**
- Modify: `lsprepost_mcp/refined_blast/store.py`
- Modify: `lsprepost_mcp/web/refined_blast_api.py`
- Modify: `tests/test_phase18e_store.py`
- Modify: `tests/test_phase18f_api.py`

**Interfaces:**
- Produces: `validate_storage_identifier(value: object, label: str) -> str` in `refined_blast.store`.
- Produces: `RefinedBlastStore.project_transaction(project_id: str) -> ContextManager[None]`.
- Produces: one private Phase 18F API project-operation context that yields the verified `StoredProject`, building recipe, `BuildingArtifact`, and artifact-bound `RefinedBlastService` while the Store lease remains held.
- Consumes: the existing Store local lock, hardened Windows/POSIX process lock, transaction/metadata evidence, and Phase 18E service APIs.

- [ ] **Step 1: Write Store re-entrancy and exception-release tests**

Add tests that wrap `save_draft()` and generated-package operations inside `project_transaction()`, instrument the process-lock context, and assert one outer OS-lock acquisition. Inject an exception inside the nested operation and assert a later independent transaction succeeds.

- [ ] **Step 2: Run the Store tests and verify RED**

Run: `python -m pytest -q tests/test_phase18e_store.py -k "project_transaction or reentrant"`

Expected: fail because `project_transaction` does not exist or the OS lock is reacquired.

- [ ] **Step 3: Write dotted-ID and unsafe-ID parity tests**

Create `project.v1` / `scenario.v1`, address every project route, generate a package, and retrieve it. Parameterize rejected dynamic segments for `.`, `..`, empty, whitespace, slash, backslash, colon, and non-ASCII lookalikes. Assert Store and Web make the same accept/reject decision.

- [ ] **Step 4: Run identifier tests and verify RED**

Run: `python -m pytest -q tests/test_phase18f_api.py -k "dotted or identifier_grammar"`

Expected: dotted identifiers create successfully but route access returns `not_found`.

- [ ] **Step 5: Write deterministic same-project race tests**

Use two `RefinedBlastApi` instances sharing one Store root. Pause the first request after verified authority is available but before its save or artifact response snapshot completes. Assert the second same-project operation cannot enter its mutation until the first finishes. Assert the first response is coherent at its lease linearization point and the second observes the resulting revision.

Add a real multiprocessing test that holds `project_transaction(project_id)` in one process and proves a second process blocks for that project while a distinct project transaction can proceed.

- [ ] **Step 6: Run race tests and verify RED**

Run: `python -m pytest -q tests/test_phase18f_api.py tests/test_phase18e_store.py -k "linearizable or cross_process_project_transaction"`

Expected: the second operation enters after verification but before the first operation completes, or the public project transaction API is missing.

- [ ] **Step 7: Implement the minimal Store transaction contract**

Promote the existing identifier check to `validate_storage_identifier()`. Add `project_transaction()` and a thread-local depth map keyed by captured Store-root identity plus project ID. Only depth zero acquires the global local `RLock` and hardened OS process lock. Every `finally` path removes the outer ownership entry.

- [ ] **Step 8: Refactor project-scoped API routes under one lease**

Replace verify-then-use flows with a single project-operation context. Keep load, save, validate, preview, acknowledgement, generate, generated-index mutation, artifact integrity checks, and response snapshot creation within that context. Route parsing calls `validate_storage_identifier()` for dynamic segments and maps failure to the existing `404 not_found` response.

- [ ] **Step 9: Run focused GREEN tests**

Run: `python -m pytest -q tests/test_phase18f_api.py tests/test_phase18e_store.py`

Expected: all pass, with the new tests proving they fail when the lease is shortened or dot support is removed.

- [ ] **Step 10: Run compatibility gates**

Run: `python -m pytest -q tests/test_web_api.py tests/test_web_startup.py tests/test_phase17_draft_preview.py tests/test_phase17_phase16_compat.py tests/test_phase18e_validation_preview.py tests/test_phase18e_scenario_set.py`

Run: `python -m compileall -q lsprepost_mcp/refined_blast lsprepost_mcp/web`

Run: `git diff --check`

Expected: all exit zero. No Phase 18D asset or fingerprint file changes.

- [ ] **Step 11: Self-review, report, and commit**

Write the RED/GREEN evidence, exact commands, concurrency semantics, touched paths, and remaining concerns to the task report generated for this plan. Commit only the four scoped code/test files plus this design and plan if they are not already committed.

Commit: `fix: linearize phase18f project operations`

- [ ] **Step 12: Independent task review**

Review spec compliance and task quality using the plan brief, report, and complete BASE..HEAD diff. Any Critical or Important finding enters the scoped fix loop before returning to the original Phase 18F plan.
