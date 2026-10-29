# Parametric Tunnel Blast Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the open tunnel MM-ALE scene safely configurable for tunnel size, uniform air mesh, explosive position, and target plate position/material.

**Architecture:** Keep `open_concrete_tunnel` as a controlled scene. The Python generator owns normalization, geometry validation, unit-count limits, and keyword generation; the Web UI mirrors those constraints for early feedback but never replaces backend validation.

**Tech Stack:** Python standard library, unittest, static HTML/CSS/JavaScript, LS-DYNA keyword generation.

## Global Constraints

- LS-Run and LS-DYNA must not be started without explicit user approval.
- The ALE air mesh is uniform and selected from `0.075`, `0.100`, `0.125`, or `0.150` m.
- Tunnel generation remains below the existing 350,000-element preflight limit.
- The target plate remains normal to the tunnel X axis; only its X/Y/Z center is configurable.
- Existing user worktree changes must not be reverted.

---

### Task 1: Backend contract and geometry validation

**Files:**
- Modify: `tests/test_phase14_complete.py`
- Modify: `lsprepost_mcp/ale_blast.py`
- Modify: `lsprepost_mcp/preflight.py`
- Modify: `lsprepost_mcp/tool_generation.py`

**Interfaces:**
- Consumes: `tool_generate_tunnel_blast_demo(args)` and `default_tunnel_blast_spec(project_name)`.
- Produces: tunnel fields `tunnel_length_m`, `tunnel_width_m`, `tunnel_height_m`, `tunnel_wall_thickness_m`, `air_mesh_size_m`, `explosive_center_m`, `plate_center_m`, and `plate_material_name`.

- [ ] Add failing tests for public schema fields, uniform ALE cell dimensions, dynamic air-domain bounds, full XYZ plate placement, material selection, invalid mesh choices, out-of-domain charge/plate, and preflight overflow.
- [ ] Run `python -m unittest tests.test_phase14_complete` and confirm the new tests fail because the fields and uniform mesh mode are absent.
- [ ] Implement normalized geometry and uniform-axis generation with backend validation.
- [ ] Run `python -m unittest tests.test_phase14_complete` and confirm all tests pass.

### Task 2: Web controls and summaries

**Files:**
- Modify: `tests/test_web_static.py`
- Modify: `lsprepost_mcp/web/static/index.html`
- Modify: `lsprepost_mcp/web/static/app.js`
- Modify: `lsprepost_mcp/web/static/styles.css` only if existing field styles are insufficient.

**Interfaces:**
- Consumes: the Task 1 public tool arguments.
- Produces: a tunnel payload and summary containing dimensions, mesh label, estimated ALE cells, explosive center, plate center, standoff, and plate material.

- [ ] Add failing static UI tests for every new control and the four labeled mesh options.
- [ ] Run `python -m unittest tests.test_web_static` and confirm failure for missing controls.
- [ ] Replace local-refinement controls with tunnel, charge, plate, material, and uniform mesh controls.
- [ ] Add client-side unit estimation and warnings while retaining backend authority.
- [ ] Run `python -m unittest tests.test_web_static` and confirm all tests pass.

### Task 3: Regression verification

**Files:**
- Modify: `docs/ROADMAP.zh-CN.md` only if the current Phase 14 section tracks this acceptance item.

- [ ] Run `python -m unittest tests.test_phase14_complete tests.test_web_static`.
- [ ] Run `python -m unittest discover -s tests`.
- [ ] Run `python -m compileall -q .\lsprepost_mcp`.
- [ ] Confirm no LS-Run or LS-DYNA process was started.

