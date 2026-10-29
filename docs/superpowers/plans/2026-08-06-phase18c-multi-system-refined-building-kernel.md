# Phase 18C Multi-System Refined Building Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the isolated Phase 18C kernel that normalizes real building spaces and voids, selects a declared structural system, generates system-appropriate Solid/Shell/Beam artifacts, and publishes deterministic manifests and fluid-exposed surface catalogs.

**Architecture:** Add a new `lsprepost_mcp.refined_building` package instead of extending the existing monolithic schema or assembly modules. A normalized building contract feeds a spatial-topology compiler and a structural-system registry; independent backends produce immutable mesh fragments that are assembled and validated by a small facade. RC-specific reinforcement rules remain an RC backend capability, while steel, hybrid, and RC-box systems expose their own member and connection roles.

**Tech Stack:** Python 3 standard library, frozen dataclasses, JSON-compatible manifests, LS-DYNA node/Solid/Shell/Beam primitives, `unittest`, SHA-256 deterministic fingerprints.

## Global Constraints

- Work in the current checkout because required Phase 18A-1/18B modules and resources are not fully represented by `HEAD`; never stage unrelated worktree changes.
- Do not import or call any existing scene generator from `refined_building`.
- Do not add Phase 18C logic to `lsprepost_mcp/schema.py`, `lsprepost_mcp/dyna_assembly.py`, or `lsprepost_mcp/tool_generation.py`.
- Old lightweight building IDs, generators, meshes, and default behavior remain unchanged.
- Old Phase 18A-1 K resources are fixed reference fixtures; never stretch or scale them into parameterized outputs.
- Spaces, corridors, shafts, atria, stairs, and openings are first-class void semantics and must not be filled by generated structural Solid elements.
- The first registered systems are exactly `rc_frame`, `rc_frame_shear_wall`, `steel_frame`, `steel_concrete_hybrid`, `rc_box`, and `custom_hybrid`.
- `full_reinforced`, `concrete_only`, and `custom` are RC-backend generation modes only.
- Every public artifact contains normalized inputs, resource/module versions, counts, dependency manifests, validation findings, and deterministic fingerprints.
- Software acceptance does not grant `engineering_validated`; generated research assets retain `requires_project_review=true`.

---

### Task 1: Isolated Building Contract and Normalization

**Files:**
- Create: `lsprepost_mcp/refined_building/__init__.py`
- Create: `lsprepost_mcp/refined_building/contracts.py`
- Test: `tests/test_phase18c_contracts.py`

**Interfaces:**
- Produces: `default_building_definition(asset_id: str = "refined_building", structural_system: str = "rc_frame") -> JSONDict`.
- Produces: `normalize_building_definition(value: Mapping[str, object]) -> JSONDict`.
- Produces normalized keys: `schema_version`, `asset_id`, `unit_system`, `envelope`, `levels`, `grid_axes`, `spaces`, `openings`, `structural_system`, `nonstructural`, `fidelity_profile`, and `requires_project_review`.

- [ ] **Step 1: Write failing contract tests**

```python
def test_default_contract_contains_real_space_and_declared_system(self) -> None:
    normalized = normalize_building_definition(default_building_definition())
    self.assertEqual("SI_m_s_kg_N_Pa", normalized["unit_system"])
    self.assertEqual("rc_frame", normalized["structural_system"]["type"])
    self.assertEqual("room_1", normalized["spaces"][0]["id"])
    self.assertTrue(normalized["requires_project_review"])

def test_contract_rejects_duplicate_ids_and_out_of_envelope_space(self) -> None:
    value = default_building_definition()
    value["spaces"].append(dict(value["spaces"][0]))
    with self.assertRaisesRegex(ValueError, "duplicate space id"):
        normalize_building_definition(value)
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_phase18c_contracts -v`
Expected: import failure because `lsprepost_mcp.refined_building.contracts` does not exist.

- [ ] **Step 3: Implement normalization**

Implement strict finite-number, monotonic-axis, positive-envelope, unique-ID, bounds-containment, level-membership, opening-connectivity, fidelity and unit checks. Return new dictionaries/lists; never mutate caller input. Use this normalized default:

```python
{
    "schema_version": "1.0.0",
    "asset_id": asset_id,
    "unit_system": "SI_m_s_kg_N_Pa",
    "envelope": {"origin_m": [0.0, 0.0, 0.0], "size_m": [6.0, 6.0, 3.0]},
    "levels": [{"id": "level_1", "elevation_m": 0.0, "height_m": 3.0}],
    "grid_axes": {"x_m": [0.0, 3.0, 6.0], "y_m": [0.0, 3.0, 6.0]},
    "spaces": [{"id": "room_1", "level_id": "level_1", "kind": "room", "bounds_m": [0.25, 0.25, 0.25, 5.75, 5.75, 2.75]}],
    "openings": [],
    "structural_system": {"type": structural_system, "parameters": {}},
    "nonstructural": [],
    "fidelity_profile": "blast_response",
    "requires_project_review": True,
}
```

- [ ] **Step 4: Run GREEN**

Run: `python -m unittest tests.test_phase18c_contracts -v`
Expected: all contract tests pass.

- [ ] **Step 5: Commit only Task 1 paths**

```powershell
git add -- lsprepost_mcp/refined_building/__init__.py lsprepost_mcp/refined_building/contracts.py tests/test_phase18c_contracts.py
git commit -m "feat: add phase18c building contract"
```

### Task 2: Spatial Topology, Voids, and Openings

**Files:**
- Create: `lsprepost_mcp/refined_building/spatial.py`
- Test: `tests/test_phase18c_spatial.py`

**Interfaces:**
- Consumes: normalized output from `normalize_building_definition`.
- Produces: frozen `AxisAlignedBox(min_x, min_y, min_z, max_x, max_y, max_z)` with `volume_m3`, `contains_point`, `intersects`, and `contains_box`.
- Produces: frozen `SpatialTopology(void_regions, adjacency, gross_volume_m3, void_volume_m3, fingerprint)`.
- Produces: `compile_spatial_topology(definition: Mapping[str, object]) -> SpatialTopology`.
- Produces: `SpatialTopology.classify_point(point_m) -> Literal["void", "envelope", "outside"]` and `to_manifest() -> JSONDict`.

- [ ] **Step 1: Write failing void/topology tests**

```python
def test_room_is_void_and_envelope_corner_is_not(self) -> None:
    topology = compile_spatial_topology(default_building_definition())
    self.assertEqual("void", topology.classify_point((3.0, 3.0, 1.5)))
    self.assertEqual("envelope", topology.classify_point((0.1, 0.1, 0.1)))
    self.assertEqual("outside", topology.classify_point((7.0, 3.0, 1.5)))

def test_opening_builds_symmetric_space_adjacency(self) -> None:
    value = two_room_fixture_with_door()
    topology = compile_spatial_topology(value)
    self.assertEqual({"room_b"}, set(topology.adjacency["room_a"]))
    self.assertEqual({"room_a"}, set(topology.adjacency["room_b"]))
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_phase18c_spatial -v`
Expected: import failure because `spatial.py` does not exist.

- [ ] **Step 3: Implement topology compilation**

Compile normalized space boxes into sorted void regions. Reject positive-volume space overlaps, openings whose `connects` endpoints are unknown, openings that connect the same endpoint twice, and duplicate adjacency edges. Compute the fingerprint from canonical JSON using `sort_keys=True` and compact separators.

- [ ] **Step 4: Run GREEN**

Run: `python -m unittest tests.test_phase18c_contracts tests.test_phase18c_spatial -v`
Expected: all tests pass.

- [ ] **Step 5: Commit only Task 2 paths**

```powershell
git add -- lsprepost_mcp/refined_building/spatial.py tests/test_phase18c_spatial.py
git commit -m "feat: compile phase18c spatial topology"
```

### Task 3: Structural-System Registry and Capability Scoping

**Files:**
- Create: `lsprepost_mcp/refined_building/systems.py`
- Test: `tests/test_phase18c_systems.py`

**Interfaces:**
- Produces: frozen `StructuralSystemDescriptor(system_id, display_name, backend_key, element_families, capabilities, allowed_generation_modes)`.
- Produces: `list_structural_systems() -> tuple[StructuralSystemDescriptor, ...]`.
- Produces: `get_structural_system(system_id: str) -> StructuralSystemDescriptor`.
- Produces: `normalize_structural_system_profile(value: Mapping[str, object]) -> JSONDict`.

- [ ] **Step 1: Write failing registry tests**

```python
def test_registry_has_exact_first_phase_systems(self) -> None:
    self.assertEqual(
        {"rc_frame", "rc_frame_shear_wall", "steel_frame", "steel_concrete_hybrid", "rc_box", "custom_hybrid"},
        {row.system_id for row in list_structural_systems()},
    )

def test_reinforcement_modes_are_rc_scoped(self) -> None:
    self.assertIn("full_reinforced", get_structural_system("rc_frame").allowed_generation_modes)
    self.assertEqual((), get_structural_system("steel_frame").allowed_generation_modes)
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_phase18c_systems -v`
Expected: import failure because `systems.py` does not exist.

- [ ] **Step 3: Implement immutable registry**

Use literal descriptors. RC systems advertise `solid_concrete`, `rebar_beam`, and `embedded_coupling`; steel advertises `frame_beam`, `shell_plate`, and `steel_connection`; hybrid advertises both concrete and steel roles plus `composite_interface`; RC box advertises `solid_concrete`, `rebar_beam`, `embedded_coupling`, and `box_structure`; custom hybrid requires two or more registered non-custom subsystem IDs and explicit non-overlapping `zones`.

- [ ] **Step 4: Run GREEN**

Run: `python -m unittest tests.test_phase18c_contracts tests.test_phase18c_spatial tests.test_phase18c_systems -v`
Expected: all tests pass.

- [ ] **Step 5: Add dependency-boundary test**

Create `tests/test_phase18c_dependency_boundaries.py` and parse every Python file below `lsprepost_mcp/refined_building` with `ast`. Assert that imports do not start with `lsprepost_mcp.city_`, `lsprepost_mcp.ale_blast`, or `lsprepost_mcp.dyna_assembly`.

- [ ] **Step 6: Run boundary GREEN**

Run: `python -m unittest tests.test_phase18c_dependency_boundaries -v`
Expected: pass.

- [ ] **Step 7: Commit only Task 3 paths**

```powershell
git add -- lsprepost_mcp/refined_building/systems.py tests/test_phase18c_systems.py tests/test_phase18c_dependency_boundaries.py
git commit -m "feat: register phase18c structural systems"
```

### Task 4: Immutable Mesh and Building Artifacts

**Files:**
- Create: `lsprepost_mcp/refined_building/artifacts.py`
- Create: `lsprepost_mcp/refined_building/meshing.py`
- Test: `tests/test_phase18c_meshing.py`

**Interfaces:**
- Produces: frozen `Node`, `SolidElement`, `ShellElement`, `BeamElement`, `PartBinding`, `ConnectionArtifact`, `MeshFragment`, and `BuildingArtifact` dataclasses.
- Produces: `mesh_axis_aligned_block(bounds: AxisAlignedBox, target_size_m: float, part_role: str) -> MeshFragment`.
- Produces: `merge_fragments(fragments: Iterable[MeshFragment]) -> MeshFragment` with deterministic collision-free ID remapping.
- Produces: `BuildingArtifact.to_manifest() -> JSONDict` and deterministic `fingerprint`.

- [ ] **Step 1: Write failing meshing tests**

```python
def test_block_mesh_uses_eight_node_solids_and_exact_bounds(self) -> None:
    fragment = mesh_axis_aligned_block(AxisAlignedBox(0, 0, 0, 1, 0.4, 0.4), 0.2, "rc_beam")
    self.assertTrue(fragment.solids)
    self.assertTrue(all(len(element.node_ids) == 8 for element in fragment.solids))
    self.assertEqual((0.0, 0.0, 0.0, 1.0, 0.4, 0.4), fragment.bounds_m)

def test_merge_is_deterministic_and_has_unique_ids(self) -> None:
    merged_a = merge_fragments([fixture_a(), fixture_b()])
    merged_b = merge_fragments([fixture_a(), fixture_b()])
    self.assertEqual(merged_a, merged_b)
    self.assertEqual(len(merged_a.nodes), len({node.node_id for node in merged_a.nodes}))
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_phase18c_meshing -v`
Expected: import failure.

- [ ] **Step 3: Implement regular hexahedral meshing and artifact hashing**

Segment each axis with `ceil(length / target_size_m)` and recompute exact equal spacing. Reject non-finite sizes, zero-volume bounds, negative Jacobian orientation, dangling connectivity, duplicate IDs, and empty fragments. Keep mesh DTOs independent of `ModelSpec` and scene schemas.

- [ ] **Step 4: Run GREEN and commit**

Run: `python -m unittest tests.test_phase18c_meshing -v`
Expected: pass.

```powershell
git add -- lsprepost_mcp/refined_building/artifacts.py lsprepost_mcp/refined_building/meshing.py tests/test_phase18c_meshing.py
git commit -m "feat: add phase18c mesh artifacts"
```

### Task 5: RC Frame and Frame-Shear-Wall Backend

**Files:**
- Create: `lsprepost_mcp/refined_building/backends/__init__.py`
- Create: `lsprepost_mcp/refined_building/backends/rc.py`
- Create: `lsprepost_mcp/refined_building/reinforcement.py`
- Test: `tests/test_phase18c_rc_backend.py`

**Interfaces:**
- Produces: `compile_rc_structure(definition: JSONDict, topology: SpatialTopology, descriptor: StructuralSystemDescriptor) -> BuildingArtifact`.
- Consumes RC parameters: column/beam dimensions, slab/wall/foundation thickness, cover, bar diameters, bar counts, stirrup/distribution spacing, end-zone spacing, mesh profile, and `generation_mode`.
- Produces reinforcement roles `column_longitudinal`, `column_stirrup`, `beam_longitudinal`, `beam_stirrup`, `slab_rebar`, `wall_rebar`, and `foundation_rebar` only when applicable.

- [ ] **Step 1: Write failing RC behavior tests**

```python
def test_full_reinforced_frame_has_solid_beam_and_embedded_roles(self) -> None:
    artifact = compile_fixture("rc_frame", "full_reinforced")
    self.assertGreater(len(artifact.mesh.solids), 0)
    self.assertGreater(len(artifact.mesh.beams), 0)
    self.assertTrue(artifact.connections_by_type("embedded_rebar"))

def test_concrete_only_has_no_rebar_or_embedding(self) -> None:
    artifact = compile_fixture("rc_frame", "concrete_only")
    self.assertEqual((), artifact.mesh.beams)
    self.assertFalse(artifact.connections_by_type("embedded_rebar"))

def test_room_center_is_not_inside_any_structural_solid(self) -> None:
    artifact = compile_fixture("rc_frame", "full_reinforced")
    self.assertFalse(artifact.solid_contains_point((1.5, 1.5, 1.5)))
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_phase18c_rc_backend -v`
Expected: import failure.

- [ ] **Step 3: Implement RC member generation and reinforcement**

Generate columns at grid intersections, beams on grid spans at level tops, slabs/foundations as bounded structural layers, and shear walls only for declared wall lines. Generate reinforcement from target spacing and cover; never scale reference K topology. Reject cover/bar combinations that do not fit, requested coupling without bars, zero direction vectors, bars outside their host member, and overlapping duplicate concrete members.

- [ ] **Step 4: Run GREEN and commit**

Run: `python -m unittest tests.test_phase18c_rc_backend -v`
Expected: pass.

```powershell
git add -- lsprepost_mcp/refined_building/backends lsprepost_mcp/refined_building/reinforcement.py tests/test_phase18c_rc_backend.py
git commit -m "feat: generate phase18c reinforced concrete systems"
```

### Task 6: Steel, Hybrid, and RC-Box Backends

**Files:**
- Create: `lsprepost_mcp/refined_building/backends/steel.py`
- Create: `lsprepost_mcp/refined_building/backends/hybrid.py`
- Create: `lsprepost_mcp/refined_building/backends/rc_box.py`
- Create: `lsprepost_mcp/refined_building/connections.py`
- Test: `tests/test_phase18c_structural_backends.py`

**Interfaces:**
- Produces: `compile_steel_frame`, `compile_steel_concrete_hybrid`, and `compile_rc_box`, each returning `BuildingArtifact`.
- Steel produces frame Beam/Shell members and explicit `steel_connection` artifacts; it never accepts RC generation modes.
- Hybrid composes a steel frame, RC slab/foundation, and explicit `composite_interface` artifacts.
- RC box generates wall/floor/roof solids around declared voids and applies RC reinforcement rules.

- [ ] **Step 1: Write failing backend tests**

```python
def test_steel_frame_has_connections_but_no_rebar_embedding(self) -> None:
    artifact = compile_system_fixture("steel_frame")
    self.assertTrue(artifact.connections_by_type("steel_connection"))
    self.assertFalse(artifact.connections_by_type("embedded_rebar"))

def test_hybrid_declares_concrete_steel_interface(self) -> None:
    artifact = compile_system_fixture("steel_concrete_hybrid")
    self.assertTrue(artifact.mesh.solids)
    self.assertTrue(artifact.mesh.beams)
    self.assertTrue(artifact.connections_by_type("composite_interface"))

def test_rc_box_preserves_internal_void(self) -> None:
    artifact = compile_system_fixture("rc_box")
    self.assertFalse(artifact.solid_contains_point((3.0, 3.0, 1.5)))
```

- [ ] **Step 2: Run RED, implement minimally, then run GREEN**

Run before implementation: `python -m unittest tests.test_phase18c_structural_backends -v`
Expected: import failure. Implement only the declared roles and validation above.
Run after implementation: same command.
Expected: pass.

- [ ] **Step 3: Commit only backend paths**

```powershell
git add -- lsprepost_mcp/refined_building/backends lsprepost_mcp/refined_building/connections.py tests/test_phase18c_structural_backends.py
git commit -m "feat: add phase18c multi-system backends"
```

### Task 7: Nonstructural Components and Fluid-Exposed Surface Catalog

**Files:**
- Create: `lsprepost_mcp/refined_building/nonstructural.py`
- Create: `lsprepost_mcp/refined_building/surfaces.py`
- Test: `tests/test_phase18c_surfaces.py`

**Interfaces:**
- Produces: `compile_nonstructural(definition: JSONDict, structural: BuildingArtifact) -> MeshFragment`.
- Produces: `build_fluid_exposed_surface_catalog(artifact: BuildingArtifact, topology: SpatialTopology) -> JSONDict`.
- Catalog keys: `exterior_surfaces`, `interior_cavity_surfaces`, `opening_boundaries`, `ground_contact_surfaces`, and `user_selectable_surfaces`.

- [ ] **Step 1: Write failing classification tests**

```python
def test_surface_catalog_separates_exterior_and_room_surfaces(self) -> None:
    catalog = fixture_catalog_with_room_and_door()
    self.assertTrue(catalog["exterior_surfaces"])
    self.assertTrue(catalog["interior_cavity_surfaces"])
    self.assertTrue(catalog["opening_boundaries"])
    self.assertFalse(set(catalog["exterior_surfaces"]) & set(catalog["interior_cavity_surfaces"]))

def test_partition_does_not_become_structural_without_declared_connection(self) -> None:
    artifact = fixture_with_partition()
    self.assertFalse(artifact.connections_by_type("structural_common_node"))
```

- [ ] **Step 2: Run RED, implement, and run GREEN**

Run: `python -m unittest tests.test_phase18c_surfaces -v` before and after implementation.
Expected before: import failure. Expected after: pass.

Compute boundary faces by canonical sorted-node keys, remove shared internal faces, classify face centroids/normals against the envelope, void boxes and opening boxes, and reject duplicate membership across mutually exclusive categories.

- [ ] **Step 3: Commit only Task 7 paths**

```powershell
git add -- lsprepost_mcp/refined_building/nonstructural.py lsprepost_mcp/refined_building/surfaces.py tests/test_phase18c_surfaces.py
git commit -m "feat: classify phase18c building surfaces"
```

### Task 8: Compiler Facade, Validation, and Deterministic Manifests

**Files:**
- Create: `lsprepost_mcp/refined_building/compiler.py`
- Create: `lsprepost_mcp/refined_building/validation.py`
- Modify: `lsprepost_mcp/refined_building/__init__.py`
- Test: `tests/test_phase18c_compiler.py`

**Interfaces:**
- Produces: `compile_refined_building(value: Mapping[str, object]) -> BuildingArtifact`.
- Produces: `validate_building_artifact(artifact: BuildingArtifact) -> JSONDict`.
- Facade sequence: normalize contract -> compile spatial topology -> resolve structural backend -> compile structure -> compile nonstructural -> build surface catalog -> cross-module validation -> fingerprint.

- [ ] **Step 1: Write failing end-to-end tests**

```python
def test_every_first_phase_system_compiles_a_minimum_building(self) -> None:
    for system_id in ("rc_frame", "rc_frame_shear_wall", "steel_frame", "steel_concrete_hybrid", "rc_box"):
        with self.subTest(system_id=system_id):
            artifact = compile_refined_building(fixture(system_id))
            report = validate_building_artifact(artifact)
            self.assertTrue(report["valid"])
            self.assertGreater(report["element_count"], 0)

def test_reordered_input_maps_produce_same_fingerprint(self) -> None:
    self.assertEqual(
        compile_refined_building(fixture("rc_frame")).fingerprint,
        compile_refined_building(reordered_fixture("rc_frame")).fingerprint,
    )
```

- [ ] **Step 2: Run RED, implement facade, and run GREEN**

Run: `python -m unittest tests.test_phase18c_compiler -v` before and after implementation.
Expected before: import failure. Expected after: pass.

Validation must report zero duplicate IDs, dangling node references, non-positive Solid volumes, undeclared overlaps, Solid centroids in void regions, missing material/section roles, dangling connections, or mutually exclusive surface-category duplicates.

- [ ] **Step 3: Run the complete Phase 18C matrix**

Run:

```powershell
python -m unittest tests.test_phase18c_contracts tests.test_phase18c_spatial tests.test_phase18c_systems tests.test_phase18c_dependency_boundaries tests.test_phase18c_meshing tests.test_phase18c_rc_backend tests.test_phase18c_structural_backends tests.test_phase18c_surfaces tests.test_phase18c_compiler -v
```

Expected: zero failures and zero unexpected skips.

- [ ] **Step 4: Commit only Task 8 paths**

```powershell
git add -- lsprepost_mcp/refined_building/__init__.py lsprepost_mcp/refined_building/compiler.py lsprepost_mcp/refined_building/validation.py tests/test_phase18c_compiler.py
git commit -m "feat: compile phase18c refined buildings"
```

### Task 9: Documentation, Packaging, and Full Regression Gate

**Files:**
- Modify: `docs/ROADMAP.zh-CN.md`
- Create: `docs/reviews/phase18/PHASE18C_MULTI_SYSTEM_KERNEL_REPORT.zh-CN.md`
- Modify: `tests/test_packaging_and_integration_boundaries.py`
- Test: all Phase 18C and existing project tests

**Interfaces:**
- Documents exact implemented systems, limitations, mesh profiles, counts, fingerprints, `requires_project_review` status, and deferred Phase 18D asset work.

- [ ] **Step 1: Add failing packaging assertions**

Assert the pure package contains `lsprepost_mcp/refined_building/compiler.py`, excludes runtime caches, and the dependency-boundary test remains packaged.

- [ ] **Step 2: Run packaging RED then GREEN**

Run: `python -m unittest tests.test_packaging_and_integration_boundaries -v`.
Expected RED before packaging changes, then pass after updating packaging inputs if required.

- [ ] **Step 3: Write the implementation report and update roadmap status**

Record commands and exact counts from the verified run. State that Phase 18C software contracts are complete only if Tasks 1-8 pass; do not claim Phase 18D assets, Phase 18E blast scenarios, material calibration, mesh convergence, or engineering validation.

- [ ] **Step 4: Run full verification**

```powershell
python -m compileall -q lsprepost_mcp
python -m unittest discover -s tests
git diff --check
```

Expected: compile exit 0; all software tests pass; environment-dependent skips reported separately; no whitespace errors.

- [ ] **Step 5: Review and commit only Phase 18C-owned paths**

Use path-restricted staging. Do not stage unrelated pre-existing modifications from the shared dirty worktree. If a required tracked file overlaps unrelated changes, leave it unstaged and report the exact path.
