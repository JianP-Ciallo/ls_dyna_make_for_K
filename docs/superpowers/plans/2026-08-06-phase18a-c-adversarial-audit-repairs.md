# Phase 18A–18C Adversarial Audit Repairs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the eight reproduced Phase 18B/18C correctness gaps while proving Phase 18A audited resources and compatibility remain unchanged.

**Architecture:** Phase 18B will share one fail-closed review-record validator and validate every referenced material at structural closure. Phase 18C will replace independent concrete-block remapping with a deterministic axis-aligned union mesher, strengthen spatial contracts, filter reinforcement by true segment/box intersection, and classify structural Shell surfaces. Existing independent fragment merging remains unchanged for nonstructural isolation.

**Tech Stack:** Python 3 standard library, frozen dataclasses, JSON resource manifests, SHA-256 evidence, LS-DYNA-inspired Solid/Shell/Beam DTOs, `unittest`.

## Global Constraints

- Preserve the accepted Phase 18 source hash, audited counts, canonical IDs, aliases, component payload bytes, and `requires_project_review=true` semantics.
- Do not modify source K resources or regenerate Phase 18A/18B assets unless a new failing test proves an asset defect.
- Do not add automatic Phase 18C-to-Phase 18B material binding in this repair.
- Do not add `custom_hybrid` compilation or external solver claims.
- Do not import scene generators into `lsprepost_mcp/refined_building`.
- Work in the current checkout because the required Phase 18A/18B files are uncommitted dependencies; stage only exact repair paths.
- Every production change requires an observed failing regression test first.

---

### Task 1: Fail-Closed Phase 18B Review Promotion

**Files:**
- Modify: `lsprepost_mcp/phase18_resource_review.py`
- Modify: `lsprepost_mcp/materials.py`
- Modify: `lsprepost_mcp/structural_resources.py`
- Test: `tests/test_phase18b_resource_review.py`

**Interfaces:**
- Produces: `_validate_review_record(resource_id, resource, record, expected_resource_kind) -> None`.
- Changes: `apply_effective_review(resource, manifest=None, *, expected_resource_kind=None) -> JSONDict`.
- Callers pass `expected_resource_kind="material"` or `"structural"` at trust boundaries.

- [ ] **Step 1: Add failing malformed-evidence tests**

Add tests that build a real canonical resource hash but vary one invalid review field at a time: wrong schema, wrong source SHA-256, missing `reviewed_on`, wrong `review_method`, empty `evidence`, and wrong `resource_kind`. Assert `apply_effective_review` raises a field-specific `ValueError` rather than returning `syntax_unit_reviewed`.

```python
def test_effective_review_rejects_invalid_manifest_header_and_incomplete_record(self) -> None:
    resource = self.material_fixture()
    manifest = self.review_manifest_for(resource)
    manifest["source_sha256"] = "0" * 64
    with self.assertRaisesRegex(ValueError, "source SHA-256"):
        apply_effective_review(resource, manifest, expected_resource_kind="material")
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_phase18b_resource_review -v`

Expected: the new test fails because the incomplete manifest currently promotes the resource.

- [ ] **Step 3: Centralize record validation**

Extract the full per-record checks currently embedded in `validate_phase18_review_manifest`. Make both full-manifest validation and `apply_effective_review` validate schema/source headers and call the same record validator. When an expected kind is supplied, require equality.

- [ ] **Step 4: Update trust-boundary callers**

Pass `expected_resource_kind="material"` from Phase 18 material accessors and `expected_resource_kind="structural"` from structural accessors. Preserve non-Phase-18 material behavior.

- [ ] **Step 5: Run GREEN**

Run: `python -m unittest tests.test_phase18b_resource_review tests.test_phase18_reference_naming_migration tests.test_phase18_resource_library -v`

Expected: all review, alias, and resource-library tests pass.

### Task 2: Validate Referenced Materials During Structural Closure

**Files:**
- Modify: `lsprepost_mcp/structural_resources.py`
- Test: `tests/test_phase18b_structural_resources.py`

**Interfaces:**
- Consumes: `validate_material_resource(material: Mapping[str, object]) -> JSONDict`.
- Produces: closure only after canonical identity and typed material validation succeed for every referenced material.

- [ ] **Step 1: Add failing negative-density and key/ID mismatch tests**

```python
def test_closure_rejects_invalid_referenced_material(self) -> None:
    materials = copy.deepcopy(self.materials)
    materials["two_storey_rc_frame_mid12_rebar_d12"]["density_kg_per_m3"] = -1.0
    with self.assertRaisesRegex(ValueError, "density_kg_per_m3"):
        validate_structural_catalog_closure(self.resources, materials)
```

Add a second test where a valid material object is stored under another material's canonical dictionary key. The closure must reject the identity mismatch.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_phase18b_structural_resources -v`

Expected: the invalid referenced material is incorrectly accepted.

- [ ] **Step 3: Validate only the referenced canonical materials**

Build the material lookup from each object's normalized canonical ID. Reject duplicate identities and key/object identity mismatch. After collecting Part references, invoke `validate_material_resource` for every referenced material before accepting dependency closure.

- [ ] **Step 4: Run GREEN**

Run: `python -m unittest tests.test_phase18b_structural_resources tests.test_phase18b_resource_review tests.test_phase18_resource_library -v`

Expected: all Phase 18B closure and generation tests pass.

### Task 3: Repair Level and Opening Spatial Semantics

**Files:**
- Modify: `lsprepost_mcp/refined_building/contracts.py`
- Modify: `lsprepost_mcp/refined_building/spatial.py`
- Test: `tests/test_phase18c_contracts.py`
- Test: `tests/test_phase18c_spatial.py`

**Interfaces:**
- Produces: assigned-level containment for every space.
- Produces: `_boxes_touch(left_bounds, right_bounds) -> bool` and `_opening_touches_envelope(bounds, envelope_min, envelope_max) -> bool` contract helpers.
- Preserves: multiple physical openings per adjacency pair while returning deduplicated topology neighbours.

- [ ] **Step 1: Add failing space and opening geometry tests**

Add tests proving that a space entirely above its assigned level is rejected, an exterior opening wholly inside the envelope is rejected, an opening not touching its declared space is rejected, and two distinct doors between the same spaces are accepted and preserved.

```python
def test_space_must_lie_within_assigned_level(self) -> None:
    value = two_level_fixture()
    value["spaces"][0]["bounds_m"] = [0.25, 0.25, 3.25, 5.75, 5.75, 5.75]
    with self.assertRaisesRegex(ValueError, "assigned level"):
        normalize_building_definition(value)
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_phase18c_contracts tests.test_phase18c_spatial -v`

Expected: invalid geometry is accepted and the two-door topology raises `duplicate adjacency edge`.

- [ ] **Step 3: Implement level and opening checks**

Index normalized levels by ID and require each space Z interval to lie inside its level interval. Require each opening to touch every declared space endpoint; an exterior opening must also have a face on the envelope. Use inclusive boundary contact with positive overlap on the two in-plane axes.

- [ ] **Step 4: Preserve multiple physical openings**

Remove adjacency-edge rejection. Continue storing neighbours in sets so the adjacency graph remains deduplicated, while `opening_regions` retains both opening IDs.

- [ ] **Step 5: Run GREEN**

Run: `python -m unittest tests.test_phase18c_contracts tests.test_phase18c_spatial -v`

Expected: all contract and topology tests pass.

### Task 4: Deterministic Conforming Concrete Union Mesher

**Files:**
- Modify: `lsprepost_mcp/refined_building/meshing.py`
- Modify: `lsprepost_mcp/refined_building/backends/rc.py`
- Modify: `lsprepost_mcp/refined_building/backends/rc_box.py`
- Modify: `lsprepost_mcp/refined_building/backends/hybrid.py`
- Modify: `lsprepost_mcp/refined_building/validation.py`
- Test: `tests/test_phase18c_meshing.py`
- Test: `tests/test_phase18c_rc_backend.py`
- Test: `tests/test_phase18c_structural_backends.py`
- Test: `tests/test_phase18c_compiler.py`

**Interfaces:**
- Produces: `mesh_axis_aligned_union(members: Iterable[tuple[str, AxisAlignedBox]], target_size_m: float, excluded_boxes: Iterable[AxisAlignedBox] = (), role_priority: Mapping[str, int] | None = None) -> MeshFragment`.
- The union mesher emits one node per canonical coordinate, one Solid per occupied cell, deterministic role ownership, and bindings only for used roles.

- [ ] **Step 1: Add failing union-mesh unit tests**

Create two overlapping blocks and assert the output has no duplicate coordinate nodes, no duplicate Solid geometry, and union volume equal to the hand-derived volume rather than the sum of both blocks.

```python
def test_union_mesh_reuses_nodes_and_emits_overlap_once(self) -> None:
    mesh = mesh_axis_aligned_union(
        (("column", AxisAlignedBox(0, 0, 0, 1, 1, 2)),
         ("beam", AxisAlignedBox(0, 0, 1, 2, 1, 2))),
        1.0,
    )
    self.assertEqual(3, len(mesh.solids))
    self.assertEqual(len(mesh.nodes), len({node.coordinates for node in mesh.nodes}))
```

- [ ] **Step 2: Run unit RED**

Run: `python -m unittest tests.test_phase18c_meshing -v`

Expected: import failure because `mesh_axis_aligned_union` does not exist.

- [ ] **Step 3: Implement union meshing**

Build sorted axes from every member's target-size coordinates, member boundaries, and clipped exclusion boundaries. For each adjacent cell, test its centroid against member boxes and exclusions. Resolve overlapping roles by `(priority, role)` and allocate node IDs from a coordinate dictionary only when the cell is retained.

- [ ] **Step 4: Run unit GREEN**

Run: `python -m unittest tests.test_phase18c_meshing -v`

Expected: all meshing tests pass.

- [ ] **Step 5: Add failing backend connectivity tests**

For RC frame and RC box artifacts, assert all structural node coordinates are unique and all concrete Solid elements form one connected component through shared node IDs. Assert validation reports no duplicate structural coordinates or disconnected concrete finding.

- [ ] **Step 6: Run backend RED**

Run: `python -m unittest tests.test_phase18c_rc_backend tests.test_phase18c_structural_backends tests.test_phase18c_compiler -v`

Expected: default RC has duplicate coordinates and multiple disconnected components.

- [ ] **Step 7: Switch concrete backends to union meshing**

RC frame/frame-wall and RC box pass their full member collections to the union mesher. Hybrid passes its concrete foundation/slab collection to the union mesher but retains explicit composite-interface semantics. Use stable priorities `foundation < column < wall < beam < slab < roof` only as deterministic ownership; priority must not duplicate volume.

- [ ] **Step 8: Add validation checks**

Report duplicate coordinates among Solid-referenced structural nodes. Compute Solid connected components by shared node IDs and require one component for `rc_frame`, `rc_frame_shear_wall`, and `rc_box`. Do not count Beam-only rebar nodes or undeclared nonstructural Shell nodes in that check.

- [ ] **Step 9: Run backend GREEN**

Run: `python -m unittest tests.test_phase18c_meshing tests.test_phase18c_rc_backend tests.test_phase18c_structural_backends tests.test_phase18c_compiler -v`

Expected: all tests pass with connected, non-overlapping concrete artifacts.

### Task 5: Remove Every Reinforcement Segment Crossing a Void

**Files:**
- Modify: `lsprepost_mcp/refined_building/reinforcement.py`
- Modify: `lsprepost_mcp/refined_building/validation.py`
- Test: `tests/test_phase18c_structural_backends.py`
- Test: `tests/test_phase18c_rc_backend.py`

**Interfaces:**
- Produces: `_segment_crosses_box_interior(start, end, box, tolerance=1e-12) -> bool`.
- Validation reports `reinforcement_crosses_void` when a Beam segment crosses a topology void/opening interior.

- [ ] **Step 1: Add failing off-centre-door regression**

Build the audited RC-box exterior-door fixture at Y=0.7–1.2 m and assert zero reinforcement Beam segments geometrically intersect the opening interior.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_phase18c_structural_backends -v`

Expected: six wall-rebar segments cross the opening.

- [ ] **Step 3: Implement segment/slab intersection filtering**

Use the slab method on segment parameter interval `[0, 1]`. Shrink the box by tolerance when testing positive interior so a segment merely lying on a boundary is retained. Replace midpoint filtering with this predicate.

- [ ] **Step 4: Validate the invariant**

Use the same predicate in artifact validation for reinforcement Beam roles and every topology void/opening. Emit an element-specific finding if any crossing remains.

- [ ] **Step 5: Run GREEN**

Run: `python -m unittest tests.test_phase18c_rc_backend tests.test_phase18c_structural_backends tests.test_phase18c_compiler -v`

Expected: all tests pass and the off-centre fixture has zero crossing bars.

### Task 6: Publish Structural Shell Surfaces

**Files:**
- Modify: `lsprepost_mcp/refined_building/surfaces.py`
- Test: `tests/test_phase18c_surfaces.py`
- Test: `tests/test_phase18c_compiler.py`

**Interfaces:**
- Produces Shell surface rows with `face_id="shell:<element_id>"`, element ID, node IDs, Part role, centroid and normal.
- Shell rows use the same mutually exclusive exterior/interior/opening/ground categories as Solid boundary faces.

- [ ] **Step 1: Add failing steel surface test**

Compile the default steel frame and assert four roof-deck Shell rows appear in both `exterior_surfaces` and `user_selectable_surfaces`.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_phase18c_surfaces -v`

Expected: exterior and selectable surface lists are empty.

- [ ] **Step 3: Add Shell face extraction and classification**

Convert each Shell to one surface row, compute its normal with the existing face-normal helper, and feed it through the same ordered category classifier. Reject degenerate or dangling Shell faces through existing mesh/validation gates.

- [ ] **Step 4: Run GREEN**

Run: `python -m unittest tests.test_phase18c_surfaces tests.test_phase18c_compiler -v`

Expected: all surface and compiler tests pass.

### Task 7: Cross-Phase Audit Report and Regression Gate

**Files:**
- Create: `docs/reviews/phase18/PHASE18A_C_ADVERSARIAL_AUDIT_REPAIR_REPORT.zh-CN.md`
- Modify: `docs/ROADMAP.zh-CN.md` only if the new paragraph can remain unstaged separately from prior edits
- Test: complete Phase 18A–18C matrix and full project suite

**Interfaces:**
- Records reproduced failures, root causes, exact fixes, tests, counts, fingerprints, unchanged Phase 18A evidence, and unresolved engineering limitations.

- [ ] **Step 1: Run complete Phase 18A–18C matrix**

Run the 15 modules used by the 115-test baseline plus all newly modified Phase 18 tests.

Expected: zero failures and zero unexpected skips.

- [ ] **Step 2: Re-run Phase 18A immutability evidence**

Run resource regeneration, payload hash/count, exact disjoint reassembly, alias, export, and compatibility tests. Record that source hash and audited counts are unchanged.

- [ ] **Step 3: Run compile and full regression**

```powershell
python -m compileall -q lsprepost_mcp
python -m unittest discover -s tests
git diff --check
```

Expected: compile exit 0, full suite has zero failures, and repair-owned paths have no whitespace errors.

- [ ] **Step 4: Write the audit repair report**

Include exact test totals and default artifact counts/fingerprints from the verified code. State that Phase 18C material role binding and external engineering validation remain pending.

- [ ] **Step 5: Commit only repair-owned paths**

Use path-restricted staging. Do not stage the pre-existing mixed `docs/ROADMAP.zh-CN.md` changes unless they can be isolated without including unrelated hunks.
