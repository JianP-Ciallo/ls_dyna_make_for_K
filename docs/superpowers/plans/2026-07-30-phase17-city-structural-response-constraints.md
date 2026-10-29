# Phase 17 City Structural Response Constraints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate city blast decks where buildings and selected facilities receive ALE/FSI loading while only their foundations remain constrained.

**Architecture:** Extend the city component constraint contract with `fixed`, `base_fixed`, and `free` modes. Generate fixed-node and FSI segment sets from the same resolved component topology, exclude fully translation-constrained segments from FSI, and independently reconstruct the overlap from serialized keyword cards in `keyword_checks.py`.

**Tech Stack:** Python 3, LS-DYNA keyword generation, `unittest`, existing LS-PrePost and LS-DYNA launch/evidence tools.

## Global Constraints

- Do not modify or overwrite `E:\K文件模型\web_phase17_city_street_blast`.
- Roads, ground foundations, parking support, and TNT display guides remain fixed non-response supports.
- Buildings, subway entrances, protective equipment, and traffic lights use base-only constraints.
- Vehicles remain free and retain road/parking contact.
- No FSI slave segment may have all four nodes translation-constrained.
- Static checks do not substitute for a short real LS-DYNA propagation run.

---

### Task 1: Constraint Contract Regression Tests

**Files:**
- Modify: `tests/test_city_street_blast.py`

**Interfaces:**
- Consumes: `build_city_street_blast_keyword(spec) -> tuple[str, JSONDict]`
- Produces: Regression assertions for component constraint modes and FSI/SPC overlap.

- [ ] **Step 1: Write the failing tests**

```python
def test_response_components_use_base_constraints_without_fully_fixed_fsi_faces():
    keyword, metadata = build_city_street_blast_keyword(
        default_city_street_blast_spec("unit_city_supported_response")
    )
    by_id = {item["object_id"]: item for item in metadata["semantic_objects"]}
    assert by_id["commercial_supermarket"]["constraint_mode"] == "base_fixed"
    assert by_id["traffic_light_1"]["constraint_mode"] == "base_fixed"
    assert metadata["fsi"]["fully_constrained_slave_segment_count"] == 0
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m unittest tests.test_city_street_blast`

Expected: FAIL because response components are currently `fixed` and FSI overlap metadata is absent.

- [ ] **Step 3: Keep the test unchanged for Task 2 implementation**

### Task 2: Base-Only Supports and FSI Segment Filtering

**Files:**
- Modify: `lsprepost_mcp/city_street_blast.py`
- Test: `tests/test_city_street_blast.py`

**Interfaces:**
- Produces: `_component_fixed_local_node_ids(component, transformed) -> set[int]`
- Produces metadata fields `fixed_node_count`, `fixed_node_ratio`, `fsi_segment_count`, `fsi_excluded_fully_constrained_segment_count`.

- [ ] **Step 1: Resolve fixed local nodes**

```python
if mode == "fixed":
    return {node_id for node_id, *_ in transformed}
if mode == "base_fixed":
    base_z = min(z for _node_id, _x, _y, z in transformed)
    return {
        node_id
        for node_id, _x, _y, z in transformed
        if abs(z - base_z) <= tolerance
    }
if mode == "free":
    return set()
raise ValueError(f"unsupported city constraint_mode: {mode}")
```

- [ ] **Step 2: Filter fully constrained FSI faces**

Append a mapped segment only when it is not entirely contained in the component fixed-node set.

- [ ] **Step 3: Assign component modes**

Set buildings, subway entrances, protective equipment, and traffic lights to `base_fixed`; keep road/support/guide parts `fixed` with `include_in_fsi=False`; keep vehicles `free`.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `python -m unittest tests.test_city_street_blast tests.test_component_library`

Expected: PASS.

### Task 3: Serialized Keyword FSI/SPC Gate

**Files:**
- Modify: `lsprepost_mcp/keyword_checks.py`
- Modify: `tests/test_city_street_blast.py`

**Interfaces:**
- Extends `KeywordModel.boundary_spc_constraints`.
- Produces check `quality.phase17.fsi_fully_constrained_segments`.

- [ ] **Step 1: Write a failing mutation test**

Mutate a valid Phase 17 deck so one FSI segment's nodes are added to a node set constrained in X/Y/Z, then assert the new quality check fails.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m unittest tests.test_city_street_blast`

Expected: FAIL because the check does not exist.

- [ ] **Step 3: Parse SPC degrees of freedom**

Store `(node_set_id, dofx, dofy, dofz, dofrx, dofry, dofrz)` for every `*BOUNDARY_SPC_SET`.

- [ ] **Step 4: Reconstruct constrained FSI segments**

Resolve translation-fixed node sets and inspect every slave segment referenced by `*CONSTRAINED_LAGRANGE_IN_SOLID`.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `python -m unittest tests.test_city_street_blast tests.test_keyword_checks`

Expected: PASS.

### Task 4: New Project and Import Validation

**Files:**
- Create through project tools: `workspace/projects/web_phase17_city_street_blast_supported_response/`

**Interfaces:**
- Consumes: `tool_generate_city_street_blast`
- Consumes: `tool_validate_lsprepost_import`

- [ ] **Step 1: Generate a new project without touching the old one**

Use project name `web_phase17_city_street_blast_supported_response`.

- [ ] **Step 2: Verify checks and metadata**

Require static checks OK, production warning scope explicit, zero fully constrained FSI faces, nonzero building/facility FSI faces, and base-only fixed-node ratios strictly between zero and one.

- [ ] **Step 3: Run real LS-PrePost import validation**

Require Keyword Reader zero errors, zero warnings, and a valid non-empty PNG.

### Task 5: Short LS-DYNA Propagation Diagnostic

**Files:**
- Create through solver handoff: a new run directory associated with `web_phase17_city_street_blast_supported_response`.

**Interfaces:**
- Consumes existing LS-DYNA runner and evidence parsers.
- Produces `d3hsp`, `dbfsi`, `matsum`, `glstat`, and `d3plot` evidence.

- [ ] **Step 1: Run only a bounded short diagnostic**

Solve long enough for the wave to reach the nearest response structure, without launching the full 40 ms production run.

- [ ] **Step 2: Evaluate propagation gates**

Require ALE detonation energy conversion, DBFSI pressure/force above numerical noise, nonzero building/facility internal or kinetic energy after arrival, no pre-arrival structural response, and no fatal/negative-volume termination.

- [ ] **Step 3: Stop on failed gates**

Do not proceed to a complete run until the failed physical or numerical gate is corrected.

### Task 6: Regression and Distribution

**Files:**
- Modify only if required by packaging tests: `scripts/pack.ps1`

**Interfaces:**
- Produces a verified source tree and distribution archive.

- [ ] **Step 1: Run all tests**

Run: `python -m unittest discover -s tests`

- [ ] **Step 2: Compile Python sources**

Run: `python -m compileall -q .\lsprepost_mcp`

- [ ] **Step 3: Package and inspect**

Run `scripts\pack.ps1` with a Phase 17 supported-response build label and reject runtime/project/local-path contamination.
