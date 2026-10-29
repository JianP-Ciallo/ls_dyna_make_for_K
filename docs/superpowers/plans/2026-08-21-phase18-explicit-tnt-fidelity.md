# Phase 18 Explicit TNT and Physical Fidelity Implementation Plan

**Goal:** Replace volume-fraction-only TNT with visible mass-conserving ALE Solid elements, expose authoritative TNT editing/preview, and raise the three default solver packages to a physically justified 45–70 MiB range.

**Architecture:** Partition one conforming structured ALE lattice into mutually exclusive air and TNT Solid parts, preserve exact TNT volume through a centered cuboid, add local physical refinement and audited building detail, and carry all new evidence through Phase 18E/F identity and preview contracts.

**Spec:** `docs/superpowers/specs/2026-08-21-phase18-explicit-tnt-fidelity-design.md`

## Task 1: Explicit TNT contracts and ALE partition

- [x] Add failing tests for nonzero TNT Solid cells, air/TNT disjointness, shared-grid conformity, exact mass and TNT-owned detonation.
- [x] Extend immutable charge/domain contracts with mass-conserving TNT bounds and subdivision evidence.
- [x] Partition ALE cells into air/TNT roles without overlap or holes.
- [x] Remove solver-complete volume-fraction geometry initialization and validate the new keyword closure.

## Task 2: Bounded physical refinement and size target

- [x] Add preflight tests for TNT, near-field, FSI and far-field element estimates before allocation.
- [x] Add deterministic transition coordinates and closed air-cell limits.
- [x] Define default per-asset fidelity presets using real structural/ALE detail only.
- [x] Verify default generated K sizes are 45–70 MiB and arbitrary user settings remain budget-gated rather than byte-padded.

## Task 3: Physical building detail audit

- [x] Add commercial/residential/subway element-family and load-path regression tests.
- [x] Add only physically justified Solid/Shell/Beam details and connection evidence.
- [x] Verify commercial two-way reinforcement and solid columns, residential floor continuity, and subway solid opaque envelope/ground.
- [x] Preserve Phase 18D default asset fingerprints.

## Task 4: Frontend TNT editing and authoritative preview

- [x] Add failing schema/UI/runtime tests for TNT mass and X/Y/Z editing.
- [x] Publish actual TNT cell geometry and evidence in the blast-source preview layer.
- [x] Render bounded TNT HEX8 geometry, mass/cell/bounds information and invalid-position feedback.
- [x] Verify save/reload/CAS/stale invalidation and direct-route compatibility.

## Task 5: Focused and cross-phase verification

- [x] Run all affected solver-blast, Provider, assembler, Store/API and workbench tests.
- [x] Run Phase 18C–F compatibility/fingerprint and packaging boundaries.
- [x] Run Python compileall, bundled Node syntax/runtime and `git diff --check`.
- [x] Complete scoped review and close Critical/Important findings with tests.

## Task 6: Generate and solve three default packages

- [x] Generate new immutable commercial/residential/subway snapshots under a new delivery directory.
- [x] Confirm each `model.k` is 45–70 MiB with entity-count and physical-detail evidence.
- [x] Run LS-PrePost import and R12 mcheck strictly serially.
- [x] Run 1 ms R12 solves strictly serially only after mcheck passes.
- [x] Record hashes, sizes, TNT cells/mass/location, mesh counts, response timings, warnings and findings in a new report.

## Completion rule

No completion claim is allowed until all three modified packages have fresh terminal PASS evidence. A historical PASS from the prior volume-fraction TNT packages cannot be reused for the new explicit-TNT models.
