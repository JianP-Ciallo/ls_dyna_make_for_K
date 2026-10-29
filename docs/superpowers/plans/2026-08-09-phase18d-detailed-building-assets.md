# Phase 18D Detailed Building Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add discoverable, parameterized detailed-building asset packages for the commercial supermarket, residential community, and subway entrance, then prove and repair compatibility with Phase 18A–C.

**Architecture:** Keep legacy component templates untouched and add a focused Phase 18D asset layer under `lsprepost_mcp/refined_building/`. Model-library manifests describe stable asset families; template builders create normalized Phase 18C definitions; the package compiler resolves material candidates, compiles one or more `BuildingArtifact` instances, and emits deterministic geometry, mesh, quality, and dependency manifests. Optional meshing extensions preserve all Phase 18C defaults and activate only when Phase 18D passes explicit parameters.

**Tech Stack:** Python 3.13, frozen dataclasses, JSON resource manifests, existing Phase 18B material/model loaders, Phase 18C `BuildingArtifact` compiler, `unittest`, `compileall`.

## Global Constraints

- Do not modify the legacy template IDs, default geometries, or default generator behavior for `commercial_supermarket`, `residential_community`, or `subway_entrance`.
- Do not import any blast-scenario generator from `lsprepost_mcp/refined_building/`.
- All Phase 18D resources and outputs must keep `solver_ready=false` and `requires_project_review=true`.
- Supported fidelity profiles are exactly `structural_core`, `blast_response`, and `research_detailed`; default is `blast_response`.
- Supported mesh profiles are exactly `coarse`, `standard`, and `fine`; default is `standard`.
- Existing Phase 18C calls without new optional parameters must retain their prior normalized output and fingerprints.
- Phase 18B fixed Part/Section/Set/coupling data must not be silently applied to geometry for which it was not authored.
- No work in later load-case or user-interface phases is part of this plan.

---

### Task 1: Parametric Detailed-Building Resource Registration

**Files:**
- Create: `lsprepost_mcp/refined_building/asset_resources.py`
- Create: `resources/model_library/detailed_buildings/phase18d/commercial_supermarket_detailed_building/asset.json`
- Create: `resources/model_library/detailed_buildings/phase18d/residential_community_detailed_building/asset.json`
- Create: `resources/model_library/detailed_buildings/phase18d/subway_entrance_detailed_building/asset.json`
- Test: `tests/test_phase18d_asset_resources.py`

**Interfaces:**
- Consumes: `MODEL_LIBRARY_DIR`; the fixed-K `load_model_resources()` result is used only as a compatibility snapshot.
- Produces: `DetailedBuildingAssetDescriptor`, `load_detailed_building_asset_rows(root: Path | None = None) -> dict[str, dict[str, object]]`, `list_detailed_building_assets() -> tuple[DetailedBuildingAssetDescriptor, ...]`, `get_detailed_building_asset(resource_id: str) -> DetailedBuildingAssetDescriptor`, and `validate_detailed_building_asset_resource(resource: Mapping[str, object]) -> dict[str, object]`.

- [ ] **Step 1: Write failing resource-discovery and validation tests**

```python
def test_phase18d_resources_are_discoverable_without_replacing_legacy_ids(self):
    ids = {row.resource_id for row in list_detailed_building_assets()}
    self.assertEqual(
        {
            "commercial_supermarket_detailed_building",
            "residential_community_detailed_building",
            "subway_entrance_detailed_building",
        },
        ids,
    )
    fixed_k_ids = {row["id"] for row in list_model_resources()}
    self.assertTrue(ids.isdisjoint(fixed_k_ids))
    self.assertFalse(get_detailed_building_asset("commercial_supermarket_detailed_building").solver_ready)

def test_parametric_resource_validation_rejects_payload_and_review_bypass(self):
    resource = load_detailed_building_asset_rows()["commercial_supermarket_detailed_building"]
    resource["payload"] = {"path": "forbidden.k.gz"}
    with self.assertRaisesRegex(ValueError, "must not declare a fixed payload"):
        validate_detailed_building_asset_resource(resource)
    resource.pop("payload")
    resource["requires_project_review"] = False
    with self.assertRaisesRegex(ValueError, "requires_project_review"):
        validate_detailed_building_asset_resource(resource)
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m unittest tests.test_phase18d_asset_resources -v`
Expected: import failure for `refined_building.asset_resources`.

- [ ] **Step 3: Add strict descriptors and manifests**

Implement a frozen descriptor whose constructor validates stable IDs, exact profile sets, legacy geometry-field/default closure, allowed/default structural systems, mesh rows, material candidates, unit system, `solver_ready=false`, and `requires_project_review=true`. Each JSON manifest must declare `source_type="parametric_detailed_building"`, `generator="refined_building.asset_compiler@1"`, and no payload.

- [ ] **Step 4: Keep fixed-K discovery isolated**

Load only `asset.json` beneath `resources/model_library/detailed_buildings/`; reject any row that declares a fixed payload. Add an assertion that `load_model_resources()` still returns only its pre-18D fixed-K IDs and that all existing `validate_model_resource()` behavior is unchanged.

- [ ] **Step 5: Run focused and Phase 18A/B resource tests**

Run: `python -m unittest tests.test_phase18d_asset_resources tests.test_phase18a1_component_resources tests.test_phase18_resource_library tests.test_phase18_reference_naming_migration -v`
Expected: all tests pass; fixed K validation counts and aliases remain unchanged.

- [ ] **Step 6: Commit only Task 1 paths**

```powershell
git add lsprepost_mcp/refined_building/asset_resources.py resources/model_library/detailed_buildings/phase18d tests/test_phase18d_asset_resources.py
git commit -m "feat: register phase18d detailed building assets"
```

### Task 2: Opt-In Fine Discretization for Phase 18D

**Files:**
- Modify: `lsprepost_mcp/refined_building/contracts.py`
- Modify: `lsprepost_mcp/refined_building/meshing.py`
- Modify: `lsprepost_mcp/refined_building/nonstructural.py`
- Modify: `lsprepost_mcp/refined_building/reinforcement.py`
- Modify: `lsprepost_mcp/refined_building/backends/steel.py`
- Modify: `lsprepost_mcp/refined_building/backends/hybrid.py`
- Modify: `lsprepost_mcp/refined_building/backends/rc_box.py`
- Test: `tests/test_phase18d_mesh_extensions.py`

**Interfaces:**
- Consumes: normalized Phase 18C definitions and existing `compile_refined_building()`.
- Produces: three accepted fidelity strings; optional nonstructural `mesh_size_m` and `plane_at`; optional `rebar_target_length_m`; optional steel `member_target_length_m`; optional hybrid `concrete_reinforcement_mode`; optional RC-box `floor_thickness_m`, `wall_thickness_m`, and `roof_thickness_m`.

- [ ] **Step 1: Write failing tests for observable discretization behavior**

```python
def test_rebar_target_length_subdivides_long_bars_without_changing_geometry(self):
    coarse = compile_refined_building(rc_definition(rebar_target_length_m=None))
    refined = compile_refined_building(rc_definition(rebar_target_length_m=0.20))
    self.assertGreater(len(refined.mesh.beams), len(coarse.mesh.beams))
    self.assertLessEqual(max_beam_length(refined, REINFORCEMENT_ROLES), 0.20 + 1e-12)

def test_hybrid_can_generate_or_omit_rc_reinforcement(self):
    reinforced = compile_refined_building(hybrid_definition("full_reinforced"))
    concrete_only = compile_refined_building(hybrid_definition("concrete_only"))
    self.assertTrue({"foundation_rebar", "slab_rebar"} & beam_roles(reinforced))
    self.assertTrue(reinforced.connections_by_type("embedded_rebar"))
    self.assertFalse({"foundation_rebar", "slab_rebar"} & beam_roles(concrete_only))
    self.assertFalse(concrete_only.connections_by_type("embedded_rebar"))

def test_nonstructural_panel_is_subdivided_and_can_lie_on_envelope_plane(self):
    artifact = compile_refined_building(panel_definition(mesh_size_m=0.5, plane_at="min"))
    self.assertEqual(8, len(artifact.mesh.shells))
    self.assertTrue(any(row["part_role"] == "nonstructural_facade" for row in artifact.surface_catalog["exterior_surfaces"]))

def test_rc_box_accepts_distinct_floor_wall_and_roof_thicknesses(self):
    artifact = compile_refined_building(rc_box_definition(0.30, 0.20, 0.15))
    roles = {solid.part_role for solid in artifact.mesh.solids}
    self.assertEqual({"rc_box_floor", "rc_box_wall", "rc_box_roof"}, roles)

def test_sparse_union_keeps_literal_mesh_order_and_fingerprint(self):
    members = (
        ("base", AxisAlignedBox(0.0, 0.0, 0.0, 1.0, 0.5, 0.25)),
        ("wall", AxisAlignedBox(0.75, 0.0, 0.0, 1.0, 0.5, 1.0)),
    )
    fragment = mesh_axis_aligned_union(members, 0.25, role_priority={"wall": 1})
    self.assertEqual(48, len(fragment.nodes))
    self.assertEqual(14, len(fragment.solids))
    self.assertEqual((1, 2, 3, 4, 5, 6, 7, 8), fragment.solids[0].node_ids)
    self.assertEqual("base", fragment.solids[0].part_role)
    self.assertEqual("wall", fragment.solids[-1].part_role)
    self.assertEqual("f4555b1d1c3dcfb6e8a4a965e7f94c9e134e66e1e1e7f4bc54cbe643a4423916", fragment.fingerprint)
```

- [ ] **Step 2: Run the tests and verify RED for missing optional behavior**

Run: `python -m unittest tests.test_phase18d_mesh_extensions -v`
Expected: unsupported fidelity/profile parameters or beam-length assertions fail against current code.

- [ ] **Step 3: Implement opt-in segment subdivision**

Add a deterministic polyline subdivision helper that inserts `ceil(length / target)` equal segments, preserves endpoints, and rejects non-positive/non-finite targets. Call it only when `rebar_target_length_m` or `member_target_length_m` is present so old fingerprints remain stable.

- [ ] **Step 4: Replace dense union occupancy scanning with equivalent sparse indexing**

Build the same global axes first. Map each member and exclusion to the exact cell-index ranges whose centroids it contains, collect role owners per occupied `(ix, iy, iz)` cell, then emit non-excluded cells in the original `(z, y, x)` order. Preserve role priority, coordinate values, node allocation order, element IDs, PartBinding order, and all five Phase 18C baseline fingerprints.

- [ ] **Step 5: Implement hybrid RC reinforcement and RC-box thickness overrides**

Map `hybrid_foundation` to `foundation_rebar` and `hybrid_slab` to `slab_rebar`. Validate `concrete_reinforcement_mode` against `full_reinforced`, `concrete_only`, and `custom`, then add a separate `embedded_rebar` connection without changing the existing steel and composite connections. RC-box optional thicknesses must default to `box_thickness_m`.

- [ ] **Step 6: Implement meshed nonstructural panels and fidelity acceptance**

For each panel, subdivide its two in-plane dimensions by `ceil(length / mesh_size_m)` and place the fixed coordinate at min, midpoint, or max according to `plane_at`. Preserve the existing one-quad midpoint behavior when neither optional field is supplied.

- [ ] **Step 7: Run Phase 18C plus new extension tests**

Run: `python -m unittest tests.test_phase18d_mesh_extensions tests.test_phase18c_contracts tests.test_phase18c_reinforcement tests.test_phase18c_structural_backends tests.test_phase18c_surfaces tests.test_phase18c_compiler -v`
Expected: all pass and legacy Phase 18C fingerprints remain equal to their existing literal baselines.

- [ ] **Step 8: Commit only Task 2 paths**

```powershell
git add lsprepost_mcp/refined_building/contracts.py lsprepost_mcp/refined_building/meshing.py lsprepost_mcp/refined_building/nonstructural.py lsprepost_mcp/refined_building/reinforcement.py lsprepost_mcp/refined_building/backends/steel.py lsprepost_mcp/refined_building/backends/hybrid.py lsprepost_mcp/refined_building/backends/rc_box.py tests/test_phase18d_mesh_extensions.py
git commit -m "feat: add opt-in detailed building discretization"
```

### Task 3: Commercial Supermarket Detailed Asset

**Files:**
- Create: `lsprepost_mcp/refined_building/asset_templates.py`
- Create: `lsprepost_mcp/refined_building/asset_compiler.py`
- Create: `lsprepost_mcp/refined_building/asset_surfaces.py`
- Modify: `lsprepost_mcp/refined_building/__init__.py`
- Test: `tests/test_phase18d_commercial_supermarket.py`

**Interfaces:**
- Consumes: Task 1 descriptors and Task 2 optional mesh parameters.
- Produces: frozen `DetailedBuildingPackage`; `compile_detailed_building_asset(resource_id, *, legacy_geometry=None, origin_m=(0, 0, 0), rotation_deg=(0, 0, 0), structural_system=None, fidelity_profile="blast_response", mesh_profile="standard", generation_options=None, material_overrides=None) -> DetailedBuildingPackage`.

- [ ] **Step 1: Write failing supermarket behavior tests**

```python
def test_supermarket_default_is_hybrid_solid_steel_and_reinforced_concrete(self):
    package = compile_detailed_building_asset(
        "commercial_supermarket_detailed_building",
        legacy_geometry={"length_m": 6.0, "width_m": 4.0, "height_m": 3.0, "wall_thickness_m": 0.20, "entrance_width_m": 2.0, "entrance_height_m": 2.0},
        mesh_profile="coarse",
    )
    artifact = package.artifacts[0]
    self.assertEqual("steel_concrete_hybrid", artifact.system_id)
    self.assertGreater(len(artifact.mesh.solids), 0)
    self.assertIn("steel_column", {row.part_role for row in artifact.mesh.beams})
    self.assertIn("foundation_rebar", {row.part_role for row in artifact.mesh.beams})
    self.assertFalse(artifact.validation_findings)

def test_supermarket_entrance_and_rooms_remain_void_and_connected(self):
    package = compile_small_supermarket()
    artifact = package.artifacts[0]
    self.assertFalse(artifact.solid_contains_point((3.0, 1.0, 1.5)))
    self.assertIn("exterior", artifact.topology_manifest["adjacency"]["sales_hall"])
    self.assertIn("front_entrance", {row["opening_id"] for row in artifact.surface_catalog["opening_boundaries"]})

def test_asset_surface_catalog_reclassifies_room_facing_structural_faces(self):
    package = compile_small_rc_supermarket()
    self.assertGreater(len(package.refined_surface_catalog["interior_cavity_surfaces"]), 0)
    self.assertLess(
        len(package.refined_surface_catalog["unclassified_boundary_surfaces"]),
        len(package.artifacts[0].surface_catalog["unclassified_boundary_surfaces"]),
    )
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m unittest tests.test_phase18d_commercial_supermarket -v`
Expected: import failure for `asset_compiler`.

- [ ] **Step 3: Implement the supermarket definition builder**

Generate one level, a four-by-three bay grid, sales/stock/service spaces, a split front facade around the declared entrance, service openings, fidelity-dependent panels, and explicit mesh/generation parameters. Reject entrance dimensions outside the facade and any unsupported system before calling Phase 18C.

- [ ] **Step 4: Implement package aggregation and material resolution**

Resolve every used material role to a material-library row or an explicit `unresolved` record. Record resource ID, version, unit system, effective status, and canonical hash where available. Aggregate exact counts from child artifacts, compute Solid volume from element coordinates, compute gross and net cavity volume by subtracting legal structural intersections from declared spaces, distinguish columns from erroneous slab/wall fill, list unresolved mass roles, store validated `origin_m`/`rotation_deg` in `placement`, and fingerprint the canonical package summary. Before mesh generation, estimate Solid count and reject requests above `generation_options.max_solid_elements` without silently changing the selected mesh profile.

Create the 18D surface catalog by copying the 18C catalog and probing both sides of each unclassified face along its normal. Move a face to `interior_cavity_surfaces` when either probe lies inside a declared space; keep the original artifact catalog untouched so Phase 18C fingerprints do not change.

- [ ] **Step 5: Verify deterministic fingerprints and invalidation**

Add literal behavior assertions that two identical normalized requests have equal fingerprints, while changing mesh profile, structural system, reinforcement mode, or material override changes the package fingerprint.

- [ ] **Step 6: Run focused tests**

Run: `python -m unittest tests.test_phase18d_commercial_supermarket tests.test_phase18d_asset_resources tests.test_phase18d_mesh_extensions -v`
Expected: all pass.

- [ ] **Step 7: Commit only Task 3 paths**

```powershell
git add lsprepost_mcp/refined_building/asset_templates.py lsprepost_mcp/refined_building/asset_compiler.py lsprepost_mcp/refined_building/asset_surfaces.py lsprepost_mcp/refined_building/__init__.py tests/test_phase18d_commercial_supermarket.py
git commit -m "feat: generate detailed commercial supermarket assets"
```

### Task 4: Residential Community and Subway Entrance Assets

**Files:**
- Modify: `lsprepost_mcp/refined_building/asset_templates.py`
- Modify: `lsprepost_mcp/refined_building/asset_compiler.py`
- Modify only when required by a failing Task 4 test: `lsprepost_mcp/refined_building/meshing.py`
- Test: `tests/test_phase18d_residential_subway.py`

**Interfaces:**
- Consumes: Task 3 package compiler.
- Produces: a multi-artifact residential package and a single-artifact subway package through the same `compile_detailed_building_asset()` signature.

**Approved subway baseline (supersedes the earlier simple entrance-box interpretation):**

- Binding specification: `docs/superpowers/specs/2026-08-09-phase18d-subway-entrance-approved-baseline.md`.
- Binding visual asset: `docs/assets/phase18d/subway_entrance_cn_generic_A_approved_2026-08-09.png`, SHA-256 `9D372CBF379A141ED0483A58B8BC0E086DFB37F27E97F114B536638F4067CD15`.
- Plan topology is authoritative: one fixed staircase `A` and exactly two escalators `B/C` are parallel and descend in the same longitudinal direction from one upper landing to common lower landing `8`; hollow independent passage `9` continues straight on the same axis to terminal interface plane `10`.
- The asset must not contain a turn, side corridor, additional stair/escalator, or station hall.
- The surface pavilion is a long glazed enclosure over the complete descent, with a shallow continuous curved metal roof, entrance overhang, regular glazing bays, a structural frame, and an RC plinth/base. Generic signage is a replaceable non-structural role; no city, station, line, or exit identity is compiled by default.
- Below-grade RC floor/walls/roof, lower landing, fixed stair, and passage are explicit structural geometry with real voids and optional reinforcement. Pavilion frame, glazing, metal roof, signage, and both escalators have independent non-concrete Part/Section/Material roles. Escalators are two separate equipment assemblies, not RC solids.
- The approved image fixes topology and architectural language, not engineering dimensions. All stair, escalator, pavilion, passage, RC thickness, reinforcement, and equipment-envelope dimensions must be normalized parameters with deterministic review-only defaults, strict validation, and user overrides. Outputs remain `solver_ready=false` and `requires_project_review=true`.

- [ ] **Step 1: Write failing multi-building and RC-box tests**

```python
def test_residential_community_compiles_one_independent_artifact_per_tower(self):
    package = compile_small_residential(tower_count=2)
    self.assertEqual(2, len(package.artifacts))
    self.assertEqual(2, len({artifact.asset_id for artifact in package.artifacts}))
    self.assertTrue(all(artifact.system_id == "rc_frame_shear_wall" for artifact in package.artifacts))
    self.assertTrue(all("wall_rebar" in beam_roles(artifact) for artifact in package.artifacts))
    left_max = package.artifacts[0].mesh.bounds_m[3]
    right_min = package.artifacts[1].mesh.bounds_m[0]
    self.assertGreater(right_min, left_max)

def test_subway_front_opening_cuts_wall_but_preserves_side_wall_rebar(self):
    package = compile_small_subway()
    artifact = package.artifacts[0]
    self.assertFalse(artifact.solid_contains_point((3.0, 0.10, 1.5)))
    self.assertTrue(any(row.part_role == "wall_rebar" for row in artifact.mesh.beams))
    self.assertIn("exterior", artifact.topology_manifest["adjacency"]["entrance_passage"])

def test_subway_matches_approved_one_stair_two_escalator_topology(self):
    package = compile_small_subway()
    manifest = package.geometry_manifest["subway_circulation"]
    self.assertEqual(1, manifest["fixed_stair_count"])
    self.assertEqual(2, manifest["escalator_count"])
    self.assertEqual(("A", "B", "C"), tuple(manifest["parallel_lane_ids"]))
    self.assertEqual(("upper_landing", "A_B_C", "lower_landing_8", "passage_9", "interface_10"), tuple(manifest["longitudinal_route"]))
    self.assertFalse(manifest["has_turn"])

def test_subway_passage_is_hollow_and_pavilion_equipment_roles_are_distinct(self):
    package = compile_small_subway()
    artifact = package.artifacts[0]
    self.assertFalse(artifact.solid_contains_point(package.geometry_manifest["subway_circulation"]["passage_probe_m"]))
    roles = package.geometry_manifest["subway_circulation"]["component_roles"]
    self.assertIn("pavilion_frame", roles)
    self.assertIn("pavilion_glazing", roles)
    self.assertIn("pavilion_metal_roof", roles)
    self.assertIn("escalator_1", roles)
    self.assertIn("escalator_2", roles)
    self.assertNotEqual(roles["escalator_1"]["part_ids"], roles["escalator_2"]["part_ids"])
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m unittest tests.test_phase18d_residential_subway -v`
Expected: unsupported asset template branch and the approved subway topology/equipment assertions fail.

- [ ] **Step 3: Implement residential tower templates**

Derive an integer storey count from total height unless explicitly supplied, create independent tower origins using `tower_length_m + tower_spacing_m`, define four occupied zones plus a core void per level, define core-wall boxes and doorway connectivity, and aggregate tower artifacts without joining the gap.

- [ ] **Step 4: Implement subway entrance template**

Implement the approved baseline rather than a bare entrance box. Map platform, wall, and roof legacy thicknesses to RC overrides; create the hollow descending RC enclosure, fixed stair, common lower landing, straight independent passage, and terminal-interface metadata. Add the long glazed surface pavilion and exactly two independent escalator equipment assemblies. Keep all circulation lanes and passage on one longitudinal axis. Preserve side/back RC concrete and reinforcement, expose the street opening, and keep the station hall outside this asset.

- [ ] **Step 5: Add fidelity and generation-mode coverage**

Assert `structural_core` has fewer Shells than `blast_response`, `research_detailed` is not less detailed than `blast_response`, and `concrete_only` removes reinforcement and embedded connections without removing Solid elements. Across all fidelity modes, assert the fixed-stair/escalator counts, straight route, hollow passage, and independent pavilion/equipment roles do not change. Reject non-positive dimensions, overlapping lane envelopes, a passage narrower than the circulation connection, or any option that requests a turn/additional lane.

- [ ] **Step 6: Run all Phase 18D tests**

Run: `python -m unittest tests.test_phase18d_asset_resources tests.test_phase18d_mesh_extensions tests.test_phase18d_commercial_supermarket tests.test_phase18d_residential_subway -v`
Expected: all pass.

- [ ] **Step 7: Commit only Task 4 paths**

```powershell
git add lsprepost_mcp/refined_building/asset_templates.py lsprepost_mcp/refined_building/asset_compiler.py lsprepost_mcp/refined_building/meshing.py tests/test_phase18d_residential_subway.py docs/assets/phase18d/subway_entrance_cn_generic_A_approved_2026-08-09.png docs/superpowers/specs/2026-08-09-phase18d-subway-entrance-approved-baseline.md
git commit -m "feat: add residential and subway detailed assets"
```

### Task 5: Phase 18A–C Compatibility Audit and Repair

**Files:**
- Create: `tests/test_phase18d_phase18abc_compatibility.py`
- Modify only if a failing regression proves a bug: scoped Phase 18A/B/C module or test file named by the failure.

**Interfaces:**
- Consumes: all Phase 18D public APIs and the exact Phase 18A–C resource and kernel APIs.
- Produces: a regression suite proving old resources, aliases, contracts, fingerprints, and dependency boundaries remain compatible.

- [ ] **Step 1: Write compatibility tests from independent snapshots**

```python
LEGACY_BUILDING_SNAPSHOT = {
    "commercial_supermarket": {
        "length_m": 22.0, "width_m": 18.0, "height_m": 8.0,
        "wall_thickness_m": 0.25, "entrance_width_m": 6.0, "entrance_height_m": 3.2,
    },
    "residential_community": {
        "tower_length_m": 8.0, "tower_width_m": 10.0, "tower_height_m": 18.0,
        "tower_count": 3, "tower_spacing_m": 4.0, "wall_thickness_m": 0.20,
        "balcony_depth_m": 1.2,
    },
    "subway_entrance": {
        "length_m": 6.0, "width_m": 4.0, "platform_height_m": 0.3,
        "enclosure_height_m": 2.8, "wall_thickness_m": 0.2, "roof_thickness_m": 0.2,
    },
}
PHASE18C_FINGERPRINTS = {
    "rc_frame": "48289fc948abd6cd9d6b1df627405a5cee8f91ad35d537321ed22b7a17baa03b",
    "rc_frame_shear_wall": "4f4fd26f4fac7ca607555805f89505b07c79b9752cd0589227067c53bcef6723",
    "steel_frame": "07d1119cdc7bf23848ede68acd644bedaac9594044f682a8fb0c981e5151f150",
    "steel_concrete_hybrid": "8adc42e4beeb973a1515f03e1734a8c782e978d76c322ba4c1b09b90ea3978cf",
    "rc_box": "fa4be2c35728d340da3ea6b97cf259678c018f6cac2f651c76f4ae1ecb6e8262",
}
COMPONENT_ALIAS_PAIRS = (
    ("2k_complete_reference", "two_storey_rc_frame_blast_reference"),
    ("2k_rc_beam_reference", "two_storey_rc_frame_beam_reference"),
    ("2k_rc_column_reference", "two_storey_rc_frame_column_reference"),
    ("2k_rc_slab_reference", "two_storey_rc_frame_slab_reference"),
    ("2k_rc_base_reference", "two_storey_rc_frame_foundation_reference"),
)

def test_legacy_building_catalog_contract_is_unchanged(self):
    for template_id, expected_geometry in LEGACY_BUILDING_SNAPSHOT.items():
        definition = component_definition(template_id)
        self.assertEqual("shell", definition.element_family)
        self.assertEqual(expected_geometry, default_component_geometry(template_id))

def test_phase18d_does_not_change_phase18c_default_fingerprints(self):
    for system_id, expected_fingerprint in PHASE18C_FINGERPRINTS.items():
        definition = default_building_definition(structural_system=system_id)
        self.assertEqual(expected_fingerprint, compile_refined_building(definition).fingerprint)

def test_phase18_resource_review_and_fixed_component_aliases_remain_valid(self):
    self.assertTrue(validate_phase18_resource_review()["valid"])
    for alias, canonical in COMPONENT_ALIAS_PAIRS:
        self.assertEqual(
            validate_model_resource(canonical)["payload_sha256"],
            validate_model_resource(alias)["payload_sha256"],
        )
```

- [ ] **Step 2: Run the compatibility suite and full Phase 18A–C matrix**

Run the exact archive matrix recorded in `docs/reviews/phase18/PHASE18A_C_ADVERSARIAL_AUDIT_REPAIR_REPORT.zh-CN.md`, plus `tests.test_phase18d_phase18abc_compatibility`.
Expected: either all pass, or a reproducible failure identifies the compatibility defect.

- [ ] **Step 3: For each failure, apply systematic debugging and TDD**

For every discovered defect: isolate the smallest real input, add one failing regression naming the broken contract, verify RED, implement the smallest repair without changing unrelated public output, then rerun the focused test and the dependency closure. Do not edit any unrelated package merely to make collection succeed.

- [ ] **Step 4: Run static dependency and dirty-scope checks**

Run:

```powershell
python -m unittest tests.test_phase18c_dependency_boundaries tests.test_phase18d_phase18abc_compatibility -v
python -m compileall -q lsprepost_mcp
git diff --check
git status --short
```

Expected: no forbidden imports, compile exit 0, diff check exit 0, and no unrelated path changed by Phase 18D.

- [ ] **Step 5: Commit the compatibility suite and only proven repairs**

```powershell
git add tests/test_phase18d_phase18abc_compatibility.py lsprepost_mcp/refined_building
git commit -m "test: prove phase18d compatibility with phase18a-c"
```

### Task 6: Phase 18D Review Report and Final Verification

**Files:**
- Create: `docs/reviews/phase18/PHASE18D_DETAILED_BUILDING_ASSET_REPORT.zh-CN.md`
- Modify: `docs/ROADMAP.zh-CN.md` only in the Phase 18D implementation-status paragraph.

**Interfaces:**
- Consumes: exact test outputs and generated asset-package manifests.
- Produces: a reviewable implementation report with completed, pending, and engineering-validation boundaries.

- [ ] **Step 1: Generate three small deterministic acceptance packages**

Run a read-only Python command that compiles one small package per asset at `coarse` mesh and writes only console JSON summaries containing resource ID, child artifact count, counts, structural system, package fingerprint, validation findings, material statuses, and `requires_project_review`.

- [ ] **Step 2: Run the final verification matrix**

Run all Phase 18D tests, the exact Phase 18A–C matrix, `python -m compileall -q lsprepost_mcp`, `git diff --check`, and scoped package/resource discovery checks. Record command, revision, counts, exit status, and duration.

- [ ] **Step 3: Request independent code review**

Ask a fresh reviewer to inspect the Phase 18D commit range for spec compliance, data-contract safety, deterministic behavior, resource closure, legacy compatibility, dependency boundaries, and unsupported engineering claims. If findings exist, perform one test-first final fix wave and rerun the entire matrix.

- [ ] **Step 4: Write the report and update roadmap status**

The report must separately state implemented software capability, unresolved material/section roles, unavailable real LS-PrePost/LS-DYNA evidence, and why software acceptance is not engineering validation. The roadmap status must not mark Phase 18E or 18F as started.

- [ ] **Step 5: Commit scoped documentation**

```powershell
git add docs/reviews/phase18/PHASE18D_DETAILED_BUILDING_ASSET_REPORT.zh-CN.md docs/ROADMAP.zh-CN.md
git commit -m "docs: record phase18d detailed building verification"
```
