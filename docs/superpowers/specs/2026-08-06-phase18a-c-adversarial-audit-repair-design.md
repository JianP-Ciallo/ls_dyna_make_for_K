# Phase 18A–18C Adversarial Audit Repair Design

**Date:** 2026-08-06

**Status:** Approved repair direction; implementation requires a separate test-driven plan.

## 1. Objective

Repair correctness defects found by adversarial testing across Phase 18A–18C without changing unrelated workflows or silently broadening engineering claims. The repaired system must preserve the audited Phase 18A source resources, strengthen Phase 18B trust and dependency gates, and make Phase 18C structural artifacts geometrically and semantically consistent.

## 2. Verified Baseline and Findings

The existing Phase 18A–18C matrix contains 115 passing tests. Additional read-only probes reproduced these uncovered defects:

1. A review manifest with an invalid schema, the wrong source hash, and no date, method, kind, or evidence can still promote a resource to `syntax_unit_reviewed`.
2. Structural dependency closure accepts a referenced rebar material with negative density.
3. The default RC frame contains 328 duplicate-coordinate node groups and 18 disconnected Solid components because member fragments are remapped rather than conformingly joined.
4. Midpoint-only reinforcement filtering leaves six bars crossing an off-centre exterior door in the tested RC box.
5. A space can be assigned to one level while its bounds lie entirely on another level.
6. An opening declared as connected to `exterior` can be placed wholly inside the envelope.
7. Two distinct doors between the same pair of spaces are rejected as a duplicate adjacency edge.
8. A steel-frame artifact with four roof Shell elements publishes no selectable exposed surfaces.

No reproducible Phase 18A parsing, source hashing, element partition, standalone payload, rigid transformation, namespace allocation, or deterministic-regeneration defect was found in this audit. Phase 18A receives additional cross-stage regression coverage but no speculative production rewrite.

## 3. Repair Boundary

### 3.1 Included

- Phase 18B review-record trust validation at every promotion boundary.
- Typed validation of every Phase 18 material referenced by the structural catalog.
- Phase 18C conforming union meshing for concrete Solid member collections.
- Removal of reinforcement segments that geometrically cross a void or opening.
- Level/space and opening/connectivity geometry validation.
- Multiple distinct openings between the same topology endpoints.
- Shell participation in the fluid-exposed surface catalog.
- New adversarial regression tests and full-project regression.

### 3.2 Excluded

- Automatic binding of all Phase 18C material roles to Phase 18B material cards. The available source resources do not contain a generally valid structural-steel card for every registered system.
- `custom_hybrid` mesh compilation.
- Detailed bolts, welds, anchorage, lap splices, RC joint-core design, material calibration, mesh convergence, LS-PrePost import evidence, or LS-DYNA solution evidence.
- Any modification outside the Phase 18 resource, refined-building, and directly associated test/documentation paths.

All generated or reviewed resources continue to require project review. Software repair does not grant `engineering_validated`.

## 4. Phase 18B Trust and Closure Repair

Review validation will use one shared record validator for both full-manifest audits and individual resource promotion. Promotion must reject a manifest unless all of the following hold:

- schema version is the accepted review schema;
- source SHA-256 equals the accepted reference-deck hash;
- resource ID exists exactly once;
- canonical resource hash matches;
- validation status is `syntax_unit_reviewed`;
- resource kind matches the caller's expected kind;
- review date is valid ISO-8601;
- review method is the accepted method;
- evidence is a non-empty list of non-empty strings.

Structural closure will resolve canonical material identities from the material objects, not only caller-supplied dictionary keys. Every referenced material will pass `validate_material_resource` before section/Part/coupling closure is accepted. A malformed unused material need not block closure, but a referenced malformed material must.

## 5. Phase 18C Conforming Concrete Union Mesh

The current pattern meshes every concrete member independently and then assigns new node IDs. The replacement will mesh a collection of axis-aligned concrete regions as one geometric union:

1. Collect every member and exclusion boundary on each axis.
2. Add target-size subdivisions inside each member extent.
3. Iterate deterministic adjacent coordinate cells.
4. Retain a cell when its centroid lies in at least one concrete member and in no void/opening exclusion.
5. If several member regions contain the cell, select one declared Part role by a stable priority; never emit duplicate Solid volume.
6. Allocate one node ID per exact canonical coordinate and reuse it across every retained cell.
7. Emit Part bindings only for roles that own at least one Solid.

RC frame, frame/shear-wall, and RC-box backends will use this union mesh. Their concrete artifacts must have no duplicate-coordinate node IDs, no duplicate Solid geometry, and one connected concrete component for the minimum accepted fixtures. Hybrid concrete regions may remain separately connected only when their connection to the steel subsystem is declared by a valid composite-interface artifact.

The existing independent-fragment merge remains available for components that must not acquire common nodes, including undeclared nonstructural attachments.

## 6. Reinforcement and Opening Geometry

Reinforcement removal will use a finite line-segment versus axis-aligned-box intersection test instead of testing only the segment midpoint. A bar is removed only when its segment crosses the positive interior of a declared void/opening; merely touching a boundary does not delete a correctly covered bar.

Contract normalization will enforce:

- each space's vertical bounds lie within its assigned level;
- an exterior opening has one endpoint `exterior`, one valid space endpoint, touches the building envelope, and touches the connected space boundary;
- an internal opening touches both connected space boundaries;
- opening bounds stay inside the building envelope;
- distinct opening IDs may connect the same endpoint pair; adjacency remains a deduplicated graph while the opening catalog preserves every physical opening.

Invalid geometry is rejected before meshing with an error naming the affected level, space, or opening.

## 7. Shell Surface Catalog

Every structural Shell is already a boundary surface and will be converted to the same manifest shape used for Solid boundary faces. Shell centroids and normals will be classified against the envelope, ground plane, void regions, and opening regions. Face IDs will use a separate `shell:<element_id>` namespace so Solid and Shell categories cannot collide.

The steel-frame minimum fixture must publish its roof-deck Shells as exterior and user-selectable surfaces. Mutually exclusive surface categories remain enforced.

## 8. Validation and Failure Behaviour

Cross-module validation will add findings for:

- duplicate coordinates assigned to different structural node IDs after conforming union meshing;
- unexpected disconnected concrete components;
- reinforcement segments crossing a declared void/opening;
- review evidence that is incomplete or belongs to the wrong resource kind;
- referenced Phase 18 materials that fail typed validation.

Validation must fail closed. It must not downgrade a defect to a warning merely to preserve an existing green test.

## 9. Test Strategy

Each reproduced defect receives a focused failing test before production changes:

- malformed review evidence cannot promote material or structural resources;
- structural closure rejects a referenced negative-density rebar resource;
- RC and RC-box minimum artifacts use unique coordinate nodes and expected concrete connectivity;
- an off-centre door has zero intersecting reinforcement segments;
- spaces outside their assigned levels are rejected;
- misplaced exterior openings are rejected;
- two distinct doors between the same spaces compile and both appear in the opening catalog;
- steel roof Shells appear in exterior and user-selectable surface sets.

Verification order:

1. individual RED/GREEN tests for each root cause;
2. complete Phase 18A–18C test matrix;
3. Python compile check;
4. full `unittest` discovery;
5. path-restricted diff and packaging checks.

## 10. Acceptance

The repair is accepted when:

- every new regression test was observed failing for the intended reason before its fix;
- all reproduced defects are no longer observable;
- Phase 18A audited counts, hashes, deterministic assets, aliases, and independent K exports remain unchanged;
- the complete Phase 18A–18C matrix passes with no unexpected skip;
- the full project suite has zero failures;
- no unrelated dirty-worktree file is staged or overwritten;
- the audit report distinguishes software correctness from engineering validation.
