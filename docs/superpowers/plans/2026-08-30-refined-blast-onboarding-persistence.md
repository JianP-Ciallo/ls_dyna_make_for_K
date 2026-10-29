# Refined Blast Onboarding and Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the refined blast workbench self-explanatory on first use and preserve the selected scenario across navigation.

**Architecture:** Keep project data authoritative on the existing server API. Add a small browser persistence boundary that stores only the latest project identity in `localStorage` and an unpersisted draft snapshot in `sessionStorage`; render onboarding and scenario explanations from stable presentation metadata.

**Tech Stack:** Vanilla ES modules, DOM APIs, browser storage, Python pytest, Node VM runtime contracts.

**Spec:** `docs/superpowers/specs/2026-08-30-refined-blast-onboarding-persistence-design.md`

## Global Constraints

- Saving a draft must remain lightweight and must not compile a detailed building.
- A server project is the only authoritative persisted scenario after creation.
- Browser storage failures must not block the workbench.
- Existing validation, generation, external-action and route isolation contracts remain unchanged.

---

### Task 1: Browser recovery boundary

**Files:**
- Create: `lsprepost_mcp/web/static/refined_blast_persistence.js`
- Test: `web/tests/refined-blast-persistence.runtime.cjs`
- Test: `tests/test_phase18f_persistence_contract.py`

**Interfaces:**
- Produces: `readLatestProjectId(storage)`, `writeLatestProjectId(storage, projectId)`, `readSessionDraft(storage)`, `writeSessionDraft(storage, snapshot)`, and `clearRecovery(storageOptions)`.

- [ ] Write runtime tests for valid IDs, malformed snapshots, unavailable storage, and clear behavior.
- [ ] Run the tests and confirm they fail because the module does not exist.
- [ ] Implement schema-versioned, exception-safe storage helpers.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Explicit first-save project lifecycle

**Files:**
- Modify: `lsprepost_mcp/web/static/refined_blast_workbench.js`
- Test: `web/tests/refined-blast-workbench.runtime.cjs`
- Test: `tests/test_phase18f_web_contract.py`

**Interfaces:**
- Consumes: persistence helpers from Task 1.
- Produces: dynamic project status, dynamic save label, saved project identity, and `onProjectCreated(projectId)` callback.

- [ ] Add failing tests proving the uncreated state says first save creates a project and the first successful save persists its ID.
- [ ] Run focused tests and confirm the new assertions fail.
- [ ] Update the shell and save renderer without changing the existing create/save API calls.
- [ ] Run focused tests and confirm they pass.

### Task 3: Onboarding and three-scenario explanations

**Files:**
- Modify: `lsprepost_mcp/web/static/refined_blast_workbench.js`
- Modify: `lsprepost_mcp/web/static/refined_blast_workbench.css`
- Test: `tests/test_phase18f_web_contract.py`

**Interfaces:**
- Produces: four-stage onboarding region and scenario explanation cards bound to the current asset/provider.

- [ ] Add failing static contracts for workflow wording, three Chinese scenario labels, propagation explanations, and responsive layout.
- [ ] Run the static contracts and confirm failure.
- [ ] Render the onboarding region and descriptive metadata next to the current selectors.
- [ ] Run the static contracts and accessibility regression tests.

### Task 4: Cross-route restoration and explicit new scenario

**Files:**
- Modify: `lsprepost_mcp/web/static/app.js`
- Modify: `lsprepost_mcp/web/static/refined_blast_workbench.js`
- Test: `web/tests/refined-workbench-startup.runtime.cjs`
- Test: `tests/test_phase18f_web_contract.py`

**Interfaces:**
- Consumes: latest project ID and session draft snapshot.
- Produces: URL-first/project-second/draft-third restoration and a new-scenario reset action.

- [ ] Add failing route runtime tests for return/re-entry restoration and reset.
- [ ] Run focused tests and confirm failure.
- [ ] Pass recovery options through `showRefinedBlastWorkbench`, persist uncreated edits, and remount cleanly on reset.
- [ ] Run startup, state and route tests.

### Task 5: First-user visual acceptance

**Files:**
- Create: screenshot artifacts outside the source tree.

**Interfaces:**
- Produces: one screenshot per user-visible step plus a return/re-entry restoration screenshot.

- [ ] Run the full focused Phase 18F Web/state suite.
- [ ] Start the local server on a verified free port.
- [ ] Complete one commercial-supermarket ALE/FSI draft through save, preview and validation.
- [ ] Capture and visually inspect every step.
- [ ] Return to the legacy workbench, re-enter, and capture the restored scenario.
- [ ] Commit verified source and documentation, then fast-forward the current project branch.
