# Phase 18 Solver Physical Detail and Ground Mesh Implementation Plan

**Goal:** Correct commercial reinforcement/column physics, solidify the subway opaque pavilion envelope, and expose a bounded independent ground mesh size without changing Phase 18D default assets.

**Architecture:** Extend only the solver-complete physical view and provider. Add deterministic solver-only supplemental fragments plus explicit interface evidence, migrate the closed provider config from `@1` to `@2`, and preserve old configs through one explicit migration.

**Spec:** `docs/superpowers/specs/2026-08-21-phase18-solver-physical-detail-ground-mesh-design.md`

## Task 1: Closed config migration and ground mesh control

- [ ] Add failing `@2`, `@1` migration, exact-key, range and Provider schema/default tests.
- [ ] Add `ground_cell_size_m` to the immutable config and canonical mappings.
- [ ] Make ground meshing use the independent value before allocation and retain hard budgets.
- [ ] Verify save/reload/fingerprint and focused contracts.

## Task 2: Commercial Solid columns and reinforcement

- [ ] Add failing tests for Solid RC columns, longitudinal bars, closed stirrups, two-way facade reinforcement and opening exclusion.
- [ ] Generate deterministic solver-only RC column Solid fragments from existing commercial axes.
- [ ] Generate longitudinal/stirrup and horizontal/vertical wall Beam fragments with cover and spacing bounds.
- [ ] Exclude duplicate solver-view steel column/jamb roles and publish embedded-rebar interfaces.
- [ ] Extend physical audit and keyword embedded coupling closure.

## Task 3: Subway opaque Solid pavilion envelope

- [ ] Add failing tests requiring Solid opaque roof/base while retaining Shell glazing and Beam frame.
- [ ] Replace solver-view thin metal roof with a finite-thickness Solid roof supplement.
- [ ] Publish verified roof-to-frame/base connection evidence and preserve passage openings.

## Task 4: Provider/UI and deterministic identity

- [ ] Expose the new bounded field through provider schema/default/normalized mappings.
- [ ] Verify generic workbench form rendering, persistence, stale request guards and package invalidation.
- [ ] Confirm Phase 18D default fingerprints remain unchanged.

## Task 5: Focused and compatibility verification

- [ ] Run solver-blast contracts/buildings/scene/provider/keyword/validation suites.
- [ ] Run affected Phase 18D, Phase 18E provider/assembler/store and Phase 18F API/UI contracts.
- [ ] Run compileall, Node syntax/runtime and `git diff --check`.
- [ ] Perform a scoped code review and fix Critical/Important findings with RED→GREEN tests.

## Task 6: Regenerate and validate solver packages

- [ ] Generate three new immutable output snapshots; do not overwrite prior evidence.
- [ ] Run LS-PrePost import and R12 mcheck serially.
- [ ] Run 1 ms serial solves only after mcheck passes.
- [ ] Record geometry roles, ground size, hashes, warnings and response evidence in an addendum report.

## Self-review

- The plan covers all four user findings and preserves Phase 18D isolation.
- Element-family choices follow the approved A boundary: load-bearing/opaque volume uses Solid, thin glazing uses Shell, reinforcement/frame uses Beam.
- No generated K file is edited by hand.
- No PASS claim is allowed without fresh terminal evidence for the modified snapshots.
