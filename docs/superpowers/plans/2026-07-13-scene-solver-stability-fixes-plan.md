# Scene Solver Stability Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the three non-baseline controlled scenes generate numerically defensible LS-DYNA decks and add checks that distinguish normal termination from a valid solution.

**Architecture:** Scene constructors define stable controlled defaults; selectors resolve geometry-derived node sets; keyword checks validate generated semantics; a focused solver-results module parses `d3hsp` without launching arbitrary processes. Real LS-DYNA runs remain an explicit integration step.

**Tech Stack:** Python 3.13, `unittest`, LS-DYNA keyword free format, local LS-DYNA R12 integration executable.

## Global Constraints

- Preserve `rebar_drop_on_helmet` behavior.
- Keep `uuc_like_single_element_demo` outside the natural-language scene registry.
- Do not expose raw keyword or solver command execution.
- Use test-first changes and preserve the existing SI unit system.

---

### Task 1: Stable controlled scene specifications

**Files:**
- Modify: `tests/test_schema.py`
- Modify: `tests/test_generation.py`
- Modify: `lsprepost_mcp/schema.py`
- Modify: `lsprepost_mcp/scene_prompts.py`

**Interfaces:**
- Consumes: `rod_impact_plate_spec()`, `cube_top_corner_load_spec()`, `plate_pressure_spec()`.
- Produces: scene specs with perimeter constraints, refined cube mesh, ramp curves, energy/timestep controls, and hourglass definitions.

- [ ] Add tests asserting rod plate fixed faces are `x_min/x_max/y_min/y_max`, cube mesh yields at least four cells per axis, both quasi-static loads use `curve.type == "ramp"`, and cube/pressure controls include energy and timestep entries.
- [ ] Run `python -m unittest tests.test_schema tests.test_generation` and confirm failures describe the old defaults.
- [ ] Update scene constructors and parameter application so changed force/pressure values also update ramp end values.
- [ ] Re-run the focused tests and confirm they pass.

### Task 2: Geometry-derived top-corner node selection

**Files:**
- Modify: `tests/test_generation.py`
- Modify: `lsprepost_mcp/dyna_selectors.py`
- Modify: `lsprepost_mcp/dyna_conditions.py`
- Modify: `lsprepost_mcp/schema.py`

**Interfaces:**
- Produces: `nodes_from_selector(spec, nodes, selector) -> list[int]` with `face_corners` support.

- [ ] Add a test generating the refined cube and assert its loaded node set contains exactly the four `z_max` geometric corners rather than hard-coded IDs.
- [ ] Run the focused test and confirm it fails because the selector is unsupported.
- [ ] Implement `face_corners` selection with coordinate tolerances derived from model spans and route node sets through it.
- [ ] Re-run the focused tests and confirm four correct nodes are emitted.

### Task 3: Assembly-aware static semantic checks

**Files:**
- Modify: `tests/test_keyword_checks.py`
- Modify: `lsprepost_mcp/keyword_checks.py`
- Modify: `lsprepost_mcp/dyna_assembly.py`

**Interfaces:**
- Consumes: assembly metadata containing component node IDs/counts and component mesh/thickness.
- Produces: correct per-component shell thickness ratios and a failed check when a deformable shell component is fully fixed.

- [ ] Add tests for actual rod-plate thickness ratio `0.004 / 0.05 == 0.08` and for detection of a shell component whose fixed set covers every component node.
- [ ] Run `python -m unittest tests.test_keyword_checks` and confirm expected failures.
- [ ] Record component node ranges, mesh size, shell thickness, and fixed node IDs in assembly metadata; update the checks to use this metadata.
- [ ] Re-run focused checks and ensure the helmet baseline remains solver-draft ready.

### Task 4: Solver-result energy gate

**Files:**
- Create: `lsprepost_mcp/solver_results.py`
- Create: `tests/test_solver_results.py`

**Interfaces:**
- Produces: `parse_d3hsp(text: str) -> dict` and `evaluate_solver_result(text: str, mode: str) -> dict`.

- [ ] Add fixtures for valid impact, valid quasi-static, negative internal energy, excessive hourglass energy, and normal termination with invalid energy.
- [ ] Run `python -m unittest tests.test_solver_results` and confirm import/function failures.
- [ ] Implement finite-number parsing, termination detection, final/max energy extraction, and explicit threshold results without executing processes.
- [ ] Re-run focused tests and confirm all cases classify correctly.

### Task 5: Full regression and real solver verification

**Files:**
- Regenerate only temporary audit decks under `tmp/scene_solver_fix_20260713/`.

**Interfaces:**
- Consumes: generated keyword decks and configured local LS-DYNA executable.
- Produces: `d3hsp`, `messag`, binary results, and an energy-gate report for each controlled scene.

- [ ] Run `python -m unittest discover -s tests` and require zero failures.
- [ ] Run `python -m compileall -q .\lsprepost_mcp` and require exit code 0.
- [ ] Generate fresh rod, cube, and pressure decks from current constructors.
- [ ] Run LS-DYNA in isolated directories with timeout and parse each `d3hsp` through `evaluate_solver_result`.
- [ ] If a scene fails the energy gate, adjust only its mesh/control/load defaults, add or update a failing regression test first, then repeat the real solve.
- [ ] Confirm the baseline rebar and UUC unit tests remain unchanged and passing.
