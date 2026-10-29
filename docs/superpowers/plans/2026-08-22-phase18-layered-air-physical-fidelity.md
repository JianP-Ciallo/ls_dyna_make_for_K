# Phase 18 Layered Air and Physical Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the three Phase 18 solver-complete buildings to use a versioned layered ALE air/vacuum domain, topology-proven exposed-face FSI, realistic structural load paths, a clear four-step workbench, and fresh serial R12 propagation evidence.

**Architecture:** Preserve immutable Phase 18D assets and build a solver-only `config@4` view around them. Separate configuration, structured ALE regions, surface topology, physical building generation, validation, Web projection, and external evidence so each boundary is independently testable and fail-closed. Heavy LS-PrePost and R12 runs occur only after all deterministic software gates pass.

**Tech Stack:** Python 3.12/3.13, frozen dataclasses, pytest, deterministic JSON/SHA-256 manifests, JavaScript ES modules, bundled Node runtime, LS-PrePost 4.12, LS-DYNA R12.

**Spec:** `docs/superpowers/specs/2026-08-21-phase18-layered-air-physical-fidelity-design.md`

## Global Constraints

- Use `SI_m_s_kg_N_Pa` throughout; no implicit unit conversion.
- Preserve published `phase18.solver_blast.config@1`, `@2`, and `@3` exact-key semantics; the new canonical contract is `phase18.solver_blast.config@4`.
- TNT remains a visible mass-conserving HEX8 part, editable from `0.1–100 kg`, with a finite X/Y/Z center and default mass `2 kg`.
- Air cell size remains `0.15–0.50 m`; ground cell size remains `0.10–0.50 m`; the coupling buffer is an integer `1–5` layers with default `2`.
- `45–70 MiB` is an observation-only size band. Never fail a model solely because its K file is outside the band and never add nonphysical records to enter the band.
- Solid, Shell, and Beam may coexist only with recorded physical basis and verified connections.
- `verification_reference` material data never sets `engineering_validated=true` or global `solver_ready=true`.
- Never launch LS-PrePost or LS-DYNA without an explicit user action and a fresh package identity check.
- Run the three heavy models strictly serially. A timeout, interruption, missing terminal summary, or historical run is not fresh PASS evidence.
- Do not mutate Phase 18D asset IDs or silently rebaseline their fingerprints.
- Official R12 material authority for the buffer is `*MAT_ALE_VACUUM` (`*MAT_140`); production use still requires the isolated R12 fixture in Task 3 to pass.

---

### Task 1: Publish the closed `config@4` contract and deterministic migration

**Files:**
- Modify: `lsprepost_mcp/refined_building/solver_blast/contracts.py:10-233`
- Modify: `lsprepost_mcp/refined_blast/providers/solver_complete_ale_fsi.py:28-326`
- Modify: `scripts/generate_phase18_solver_blast_models.py:79-129,281-335`
- Modify: `tests/test_phase18_solver_blast_contracts.py`
- Modify: `tests/test_phase18_solver_blast_provider.py`
- Modify: `tests/test_phase18_solver_blast_script.py`

**Interfaces:**
- Consumes: published `SolverBlastConfig` `@1–@3` mappings.
- Produces: canonical `SolverBlastConfig` with `air_margins_m: tuple[float, float, float, float, float]`, `near_field_cell_size_m: float`, `coupling_buffer_layers: int`, and `material_profile: str`.
- Produces: `normalize_solver_blast_config(value) -> SolverBlastConfig`, always returning `schema_version == "phase18.solver_blast.config@4"`.

- [ ] **Step 1: Add failing migration, exact-key, range, and provider-schema tests**

```python
def test_v3_migrates_to_closed_v4_without_changing_symmetric_extent() -> None:
    value = _valid_config_v3()
    config = normalize_solver_blast_config(value)
    assert config.schema_version == "phase18.solver_blast.config@4"
    assert config.air_margins_m == (3.0, 3.0, 3.0, 3.0, 3.0)
    assert config.near_field_cell_size_m == pytest.approx(0.15)
    assert config.coupling_buffer_layers == 2
    assert config.material_profile == "verification_reference"


def test_v4_accepts_asymmetric_air_and_rejects_unknown_keys() -> None:
    value = _valid_config_v4()
    value["air_margins_m"] = [2.0, 4.0, 3.0, 5.0, 6.0]
    assert normalize_solver_blast_config(value).air_margins_m == (2.0, 4.0, 3.0, 5.0, 6.0)
    value["unexpected"] = 1
    with pytest.raises(ValueError, match="unexpected keys"):
        normalize_solver_blast_config(value)


@pytest.mark.parametrize("layers", [0, 6, 1.5, True])
def test_v4_rejects_invalid_coupling_buffer_layers(layers: object) -> None:
    value = _valid_config_v4()
    value["coupling_buffer_layers"] = layers
    with pytest.raises(ValueError, match="coupling_buffer_layers"):
        normalize_solver_blast_config(value)
```

- [ ] **Step 2: Run the RED tests**

Run:

```powershell
python -m pytest -q tests/test_phase18_solver_blast_contracts.py tests/test_phase18_solver_blast_provider.py tests/test_phase18_solver_blast_script.py
```

Expected: failures because `@4`, the five margins, near-field size, layer count, and material profile do not exist.

- [ ] **Step 3: Implement exact versioned normalization**

Use these canonical fields and migration rules:

```python
_SCHEMA_VERSION_V3 = "phase18.solver_blast.config@3"
_SCHEMA_VERSION = "phase18.solver_blast.config@4"
_MATERIAL_PROFILES = frozenset({"verification_reference", "project_calibrated"})

@dataclass(frozen=True, slots=True)
class SolverBlastConfig:
    schema_version: str
    unit_system: str
    tnt_equivalent_mass_kg: float
    charge_position_m: tuple[float, float, float]
    detonation_time_s: float
    air_cell_size_m: float
    near_field_cell_size_m: float
    ground_cell_size_m: float
    air_margins_m: tuple[float, float, float, float, float]
    coupling_buffer_layers: int
    material_profile: str
    termination_time_s: float
```

For `@1–@3`, map `[mx, my, mz]` to `[mx, mx, my, my, mz]`, set near-field size to `min(0.15, air_cell_size_m)`, layers to `2`, and material profile to `verification_reference`. For `@4`, accept only the exact new keys. Require `0.05 <= near_field_cell_size_m <= air_cell_size_m`.

- [ ] **Step 4: Update Provider schema/defaults and generation CLI**

Expose exact fields:

```python
"air_margins_m": {
    "type": "array", "items": {"type": "number", "exclusiveMinimum": 0.0},
    "minItems": 5, "maxItems": 5,
    "title": "空气域 X-/X+/Y-/Y+/顶部余量 (m)",
},
"coupling_buffer_layers": {
    "type": "integer", "minimum": 1, "maximum": 5,
    "title": "地坪下耦合缓冲层数",
},
"material_profile": {
    "type": "string", "enum": ["verification_reference", "project_calibrated"],
    "title": "材料档案",
},
```

Replace `--air-margin X Y Z` with `--air-margins XMIN XMAX YMIN YMAX TOP`, add `--near-field-cell-size-m`, `--coupling-buffer-layers`, and `--material-profile`. Keep old config files loadable only through the Python migration, not through ambiguous CLI aliases.

- [ ] **Step 5: Run focused GREEN tests and commit**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_contracts.py tests/test_phase18_solver_blast_provider.py tests/test_phase18_solver_blast_script.py
git add lsprepost_mcp/refined_building/solver_blast/contracts.py lsprepost_mcp/refined_blast/providers/solver_complete_ale_fsi.py scripts/generate_phase18_solver_blast_models.py tests/test_phase18_solver_blast_contracts.py tests/test_phase18_solver_blast_provider.py tests/test_phase18_solver_blast_script.py
git commit -m "feat: version layered phase18 blast config"
```

Expected: all selected tests PASS; no `@3` input accepts an `@4`-only key.

---

### Task 2: Build the structured active-air, TNT, and coupling-buffer topology

**Files:**
- Create: `lsprepost_mcp/refined_building/solver_blast/air_topology.py`
- Modify: `lsprepost_mcp/refined_building/solver_blast/ale_domain.py`
- Modify: `lsprepost_mcp/refined_building/solver_blast/scene.py`
- Modify: `lsprepost_mcp/refined_building/solver_blast/ground.py`
- Create: `tests/test_phase18_solver_blast_layered_domain.py`
- Modify: `tests/test_phase18_solver_blast_scene.py`

**Interfaces:**
- Consumes: `PhysicalBuildingModel`, `GroundModel`, `ChargeModel`, and canonical `SolverBlastConfig@4`.
- Produces: `AirRegionModel`, `AirTopologyEvidence`, `classify_ale_cell(domain, ix, iy, iz) -> str`, and `audit_air_topology(scene) -> AirTopologyEvidence`.
- Produces part roles: `ale_active_air_domain`, `ale_coupling_buffer`, and existing TNT role.

- [ ] **Step 1: Write failing topology and budget tests**

```python
def test_air_stops_at_grade_except_for_bounded_vacuum_buffer() -> None:
    scene = _scene(coupling_buffer_layers=3, air_cell_size_m=0.2)
    assert scene.air.active_air_bounds.min_z == pytest.approx(scene.ground.grade_elevation_m)
    assert scene.air.coupling_buffer_bounds.max_z == pytest.approx(scene.ground.grade_elevation_m)
    assert scene.air.coupling_buffer_bounds.min_z == pytest.approx(scene.ground.grade_elevation_m - 0.6)
    assert scene.air.buffer_element_count > 0
    assert scene.air.active_air_element_count > 0


def test_subway_connected_internal_air_remains_active_below_grade() -> None:
    scene = _subway_scene(coupling_buffer_layers=2)
    evidence = audit_air_topology(scene)
    assert evidence.connected_internal_air_cell_count > 0
    assert evidence.external_path_to_soil_contact_count == 0


def test_buffer_budget_is_checked_before_axis_materialization(monkeypatch) -> None:
    monkeypatch.setattr(ale_domain, "_axis_coordinates", _allocation_sentinel)
    with pytest.raises(ValueError, match="ALE element budget exceeded"):
        _scene_with_huge_asymmetric_margins()
```

- [ ] **Step 2: Run RED tests**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_layered_domain.py tests/test_phase18_solver_blast_scene.py
```

Expected: import or attribute failures for the new topology types and fields.

- [ ] **Step 3: Implement immutable region contracts**

```python
AirCellKind = Literal["active_air", "explicit_tnt", "coupling_buffer"]

@dataclass(frozen=True, slots=True)
class AirRegionModel:
    grade_elevation_m: float
    exterior_min_z_m: float
    connected_internal_bounds_m: tuple[tuple[float, float, float, float, float, float], ...]
    coupling_buffer_bounds_m: tuple[float, float, float, float, float, float]
    fingerprint: str

@dataclass(frozen=True, slots=True)
class AirTopologyEvidence:
    active_air_cell_count: int
    connected_internal_air_cell_count: int
    buffer_cell_count: int
    tnt_cell_count: int
    external_path_to_soil_contact_count: int
    buffer_contains_material_count: int
    fingerprint: str
```

Derive connected internal bounds only from versioned artifact `spaces` and real opening connectivity. Above-grade exterior is active air. Below-grade cells are vacuum buffer unless their center lies in a connected internal-air volume. TNT classification takes precedence only inside active air.

- [ ] **Step 4: Replace symmetric domain bounds and stream all cell roles**

Use margin order `(x_min, x_max, y_min, y_max, top)`. Set the grid bottom to `grade - coupling_buffer_layers * air_cell_size_m`, not to the soil bottom. Add `near_field_cell_size_m` to `_axis_coordinates`; the realized local cell target is:

```python
refinement = min(
    config.air_cell_size_m,
    config.near_field_cell_size_m,
    charge.side_length_m / 3.0,
)
```

`iter_ale_elements()` must stream each cell once and assign exactly one role. Update `AleDomainEstimate` counts, bounds, fingerprint, and boundary-face counts without materializing all nodes or elements.

- [ ] **Step 5: Run GREEN tests and commit**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_layered_domain.py tests/test_phase18_solver_blast_scene.py
git add lsprepost_mcp/refined_building/solver_blast/air_topology.py lsprepost_mcp/refined_building/solver_blast/ale_domain.py lsprepost_mcp/refined_building/solver_blast/scene.py lsprepost_mcp/refined_building/solver_blast/ground.py tests/test_phase18_solver_blast_layered_domain.py tests/test_phase18_solver_blast_scene.py
git commit -m "feat: layer phase18 active air and coupling buffer"
```

Expected: exact counts match iterators; no free active-air cell exists below grade outside a proven internal volume.

---

### Task 3: Prove the R12 vacuum buffer and split boundary cards before production use

**Files:**
- Create: `scripts/validate_phase18_ale_buffer_fixture.py`
- Create: `tests/test_phase18_solver_blast_buffer_fixture.py`
- Modify: `lsprepost_mcp/refined_building/solver_blast/materials.py`
- Modify: `lsprepost_mcp/refined_building/solver_blast/keyword.py:28-40,426-500,1119-1215`
- Modify: `tests/test_phase18_solver_blast_keyword.py`

**Interfaces:**
- Consumes: `ale_coupling_buffer` cells from Task 2.
- Produces: `render_ale_vacuum_material(material_id: int) -> tuple[str, ...]`.
- Produces separate `ALE_SIDE_SEGMENT_SET_ID`, `ALE_TOP_SEGMENT_SET_ID`, and `ALE_BOTTOM_NODE_SET_ID` identities.

- [ ] **Step 1: Write parser-level RED tests for material and boundary separation**

```python
def test_buffer_is_r12_ale_vacuum_not_air_or_tnt(tmp_path: Path) -> None:
    model = _write_small_layered_deck(tmp_path)
    text = model.read_text(encoding="utf-8")
    assert "*MAT_ALE_VACUUM" in text
    assert "Visible coupling buffer vacuum" in text
    assert _part_id_for_role(text, "ale_coupling_buffer") not in {
        _part_id_for_role(text, "ale_active_air_domain"),
        _part_id_for_role(text, "movable_tnt_material_group"),
    }


def test_bottom_faces_are_not_in_nonreflecting_sets(tmp_path: Path) -> None:
    evidence = _compile_small_layered_deck(tmp_path)
    assert evidence.side_nonreflecting_segment_count > 0
    assert evidence.top_nonreflecting_segment_count > 0
    assert evidence.bottom_nonreflecting_segment_count == 0
    assert evidence.bottom_closed_node_count > 0
```

- [ ] **Step 2: Run parser RED tests**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_buffer_fixture.py tests/test_phase18_solver_blast_keyword.py -k "buffer or boundary or nonreflecting"
```

Expected: failures because the deck currently puts all six outer faces in one non-reflecting set and has no vacuum part.

- [ ] **Step 3: Render the exact R12 candidate cards**

Implement the vacuum material with the R12 alias and a closed bottom normal constraint:

```python
def render_ale_vacuum_material(material_id: int) -> tuple[str, ...]:
    return (
        "*MAT_ALE_VACUUM_TITLE",
        "Visible coupling buffer vacuum",
        f"{material_id},1.0",
    )
```

Write four lateral faces to the side non-reflecting segment set, `z_max` to the top non-reflecting set, and `z_min` nodes to a dedicated bottom `*BOUNDARY_SPC_SET` that constrains only the normal Z degree of freedom. Do not place `z_min` faces in either non-reflecting set.

- [ ] **Step 4: Add and run the isolated R12 fixture**

The script writes a 4×4×4 active-air block over two vacuum layers, runs `mcheck=y`, then a `0.00005 s` smoke solve. It records executable SHA-256, model SHA-256, return code, normal termination, vacuum material acceptance, boundary counts, and finite energy histories in `fixture_result.json`.

```powershell
python scripts/validate_phase18_ale_buffer_fixture.py --output-root .phase18_ale_buffer_fixture
```

Expected: `all_ok=true`, no keyword Error, normal termination, and requested final time reached. If this fixture fails, stop the implementation at Task 3 and keep production generation disabled; do not substitute an unproven bottom or vacuum card.

- [ ] **Step 5: Run keyword regression and commit**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_buffer_fixture.py tests/test_phase18_solver_blast_keyword.py tests/test_phase18_solver_blast_validation.py
git add scripts/validate_phase18_ale_buffer_fixture.py tests/test_phase18_solver_blast_buffer_fixture.py lsprepost_mcp/refined_building/solver_blast/materials.py lsprepost_mcp/refined_building/solver_blast/keyword.py tests/test_phase18_solver_blast_keyword.py
git commit -m "feat: close phase18 ALE buffer boundaries"
```

---

### Task 4: Classify every structural surface and derive FSI only from active-air exposure

**Files:**
- Create: `lsprepost_mcp/refined_building/solver_blast/surface_topology.py`
- Modify: `lsprepost_mcp/refined_building/solver_blast/fsi.py`
- Modify: `lsprepost_mcp/refined_building/solver_blast/scene.py`
- Create: `tests/test_phase18_solver_blast_surface_topology.py`
- Modify: `tests/test_phase18_solver_blast_keyword.py`

**Interfaces:**
- Consumes: welded building mesh, ground mesh, openings, active-air structured grid, and Task 2 topology.
- Produces: `SurfaceClass`, `ClassifiedSurface`, `SurfaceTopology`, and `classify_surface_topology(scene) -> SurfaceTopology`.
- Produces: `extract_fsi_segments(scene, surface_topology) -> FsiInterface` containing only active-air-exposed faces.

- [ ] **Step 1: Write failing exhaustive/exclusive and mutation tests**

```python
SURFACE_CLASSES = {
    "external_air_exposed", "internal_air_exposed", "soil_contact",
    "sealed_internal", "structural_connection",
}

def test_every_boundary_face_has_exactly_one_surface_class() -> None:
    topology = classify_surface_topology(_commercial_scene())
    assert topology.unclassified_count == 0
    assert topology.multiply_classified_count == 0
    assert set(topology.counts) == SURFACE_CLASSES
    assert sum(topology.counts.values()) == topology.boundary_face_count


def test_subway_below_grade_exterior_never_enters_air_fsi() -> None:
    scene = _subway_scene()
    topology = classify_surface_topology(scene)
    fsi = extract_fsi_segments(scene, topology)
    soil_keys = {row.face_key for row in topology.surfaces if row.surface_class == "soil_contact"}
    assert soil_keys.isdisjoint({tuple(sorted(row.node_ids)) for row in fsi.segments})


def test_fake_opening_cannot_create_air_path_to_foundation_underside() -> None:
    scene = _scene_with_forged_opening_through_floor()
    with pytest.raises(ValueError, match="external active-air path reaches soil-contact surface"):
        classify_surface_topology(scene)
```

- [ ] **Step 2: Run RED tests**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_surface_topology.py tests/test_phase18_solver_blast_keyword.py -k "fsi or exposed or buried or topology"
```

Expected: missing module/signatures and the existing role-based FSI selection accepting insufficient evidence.

- [ ] **Step 3: Implement immutable surface topology**

```python
SurfaceClass = Literal[
    "external_air_exposed", "internal_air_exposed", "soil_contact",
    "sealed_internal", "structural_connection",
]

@dataclass(frozen=True, slots=True)
class ClassifiedSurface:
    face_key: tuple[int, int, int, int]
    owner_element_id: int
    owner_part_role: str
    surface_class: SurfaceClass
    area_m2: float
    normal: tuple[float, float, float]
    adjacent_active_air_component: str | None

@dataclass(frozen=True, slots=True)
class SurfaceTopology:
    surfaces: tuple[ClassifiedSurface, ...]
    counts: Mapping[str, int]
    boundary_face_count: int
    unclassified_count: int
    multiply_classified_count: int
    fingerprint: str
```

Use actual oriented boundary faces, ground-contact rectangles, declared openings, and an implicit structured-cell graph. Treat structural boundary faces as graph barriers; permit passage only through declared openings. Store graph visitation in a `bytearray` and bounded integer queue after the existing ALE budget gate.

- [ ] **Step 4: Make FSI consume classifications instead of `member.fluid_exposed` alone**

Select only `external_air_exposed` and connected `internal_air_exposed`. Keep ground contact, sealed, and structural connection faces disjoint. Persist classification counts and surface-topology fingerprint in `SolverBlastDeckEvidence` and `manifest.json`.

- [ ] **Step 5: Run GREEN tests and commit**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_surface_topology.py tests/test_phase18_solver_blast_keyword.py tests/test_phase18_solver_blast_validation.py
git add lsprepost_mcp/refined_building/solver_blast/surface_topology.py lsprepost_mcp/refined_building/solver_blast/fsi.py lsprepost_mcp/refined_building/solver_blast/scene.py tests/test_phase18_solver_blast_surface_topology.py tests/test_phase18_solver_blast_keyword.py
git commit -m "feat: classify phase18 exposed FSI surfaces"
```

---

### Task 5: Add mesh-quality, reinforcement-host, load-path, and material-profile audits

**Files:**
- Create: `lsprepost_mcp/refined_building/solver_blast/mesh_quality.py`
- Create: `lsprepost_mcp/refined_building/solver_blast/load_path.py`
- Modify: `lsprepost_mcp/refined_building/solver_blast/materials.py`
- Modify: `lsprepost_mcp/refined_building/solver_blast/physical_audit.py`
- Modify: `lsprepost_mcp/refined_building/solver_blast/service.py`
- Create: `tests/test_phase18_solver_blast_quality.py`
- Modify: `tests/test_phase18_solver_blast_buildings.py`

**Interfaces:**
- Consumes: `PhysicalBuildingModel`, welded `MeshFragment`, and `material_profile`.
- Produces: `MeshQualityReport`, `LoadPathReport`, `MaterialReviewRecord` and deterministic `AuditFinding` rows.
- `compile_solver_blast_deck()` must stop before scene/ALE allocation when any hard building audit fails.

- [ ] **Step 1: Write mutation-driven RED tests**

```python
def test_hex8_requires_positive_jacobian_at_all_natural_corners() -> None:
    report = audit_mesh_quality(_twisted_hex_fragment())
    assert "solid_nonpositive_corner_jacobian" in {row.finding_id for row in report.findings}


def test_rebar_requires_containment_cover_and_embedded_host() -> None:
    report = audit_reinforcement_hosts(_column_with_one_bar_outside_cover())
    assert "rebar_outside_host_cover" in {row.finding_id for row in report.findings}


def test_every_declared_load_bearing_member_reaches_soil() -> None:
    report = audit_load_paths(_building_with_disconnected_roof_column())
    assert report.continuous is False
    assert report.unreachable_roles == ("steel_roof_deck",)


def test_reference_material_profile_never_claims_engineering_validation() -> None:
    record = material_review_record("verification_reference")
    assert record.engineering_validated is False
    assert record.requires_project_review is True
```

- [ ] **Step 2: Run RED tests**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_quality.py tests/test_phase18_solver_blast_buildings.py
```

Expected: missing audit modules and mutation cases not rejected.

- [ ] **Step 3: Implement exact quality reports**

```python
@dataclass(frozen=True, slots=True)
class MeshQualityReport:
    solid_count: int
    shell_count: int
    beam_count: int
    minimum_corner_jacobian_m3: float
    maximum_aspect_ratio: float
    orphan_node_count: int
    duplicate_element_count: int
    findings: tuple[AuditFinding, ...]
    fingerprint: str

@dataclass(frozen=True, slots=True)
class LoadPathReport:
    source_roles: tuple[str, ...]
    foundation_roles: tuple[str, ...]
    soil_roles: tuple[str, ...]
    unreachable_roles: tuple[str, ...]
    continuous: bool
    fingerprint: str
```

Compute HEX8 Jacobians at all eight natural corners, Shell area/thickness/orientation, Beam length/section/orientation, duplicate connectivity, orphan nodes, and rebar host containment. Build a directed member/interface graph and require every load-bearing source role to reach a foundation and soil-contact role.

- [ ] **Step 4: Integrate fail-closed audits before ALE allocation**

`compile_solver_blast_deck()` order becomes: normalize → physical building → mesh/material/load-path audits → ground/charge/ALE scene → surface topology → deck → persisted reparse. Include audit fingerprints in manifest identity.

- [ ] **Step 5: Run GREEN tests and commit**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_quality.py tests/test_phase18_solver_blast_buildings.py tests/test_phase18_solver_blast_scene.py
git add lsprepost_mcp/refined_building/solver_blast/mesh_quality.py lsprepost_mcp/refined_building/solver_blast/load_path.py lsprepost_mcp/refined_building/solver_blast/materials.py lsprepost_mcp/refined_building/solver_blast/physical_audit.py lsprepost_mcp/refined_building/solver_blast/service.py tests/test_phase18_solver_blast_quality.py tests/test_phase18_solver_blast_buildings.py
git commit -m "feat: audit phase18 mesh and load paths"
```

---

### Task 6: Complete the commercial structural grid and reinforced load path

**Files:**
- Create: `lsprepost_mcp/refined_building/solver_blast/buildings/__init__.py`
- Create: `lsprepost_mcp/refined_building/solver_blast/buildings/common.py`
- Create: `lsprepost_mcp/refined_building/solver_blast/buildings/commercial.py`
- Modify: `lsprepost_mcp/refined_building/solver_blast/physical_building.py`
- Modify: `tests/test_phase18_solver_blast_buildings.py`
- Modify: `tests/test_phase18_solver_blast_quality.py`

**Interfaces:**
- Consumes: commercial Phase 18D package and shared meshing/interface helpers.
- Produces: `build_commercial_physical_model(package) -> BuildingPhysicalParts` with Solid RC columns/walls/slabs/foundations, Beam reinforcement/steel framing, and Shell thin roof where physically justified.

- [ ] **Step 1: Add failing physical and mutation tests**

```python
def test_commercial_every_grid_column_has_concrete_longitudinal_bars_and_stirrups() -> None:
    model = _commercial_building()
    evidence = commercial_column_evidence(model)
    assert evidence.column_count == evidence.longitudinal_host_count
    assert evidence.column_count == evidence.closed_stirrup_host_count
    assert evidence.unhosted_rebar_count == 0


def test_commercial_roof_and_floor_reach_foundation_on_every_grid_line() -> None:
    report = audit_load_paths(_commercial_building())
    assert report.continuous
    assert not report.unreachable_roles


def test_commercial_wall_rebar_is_two_way_and_clears_openings() -> None:
    evidence = commercial_wall_rebar_evidence(_commercial_building())
    assert evidence.horizontal_count > 0
    assert evidence.vertical_count > 0
    assert evidence.opening_intersection_count == 0
```

- [ ] **Step 2: Run RED tests**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_buildings.py tests/test_phase18_solver_blast_quality.py -k commercial
```

Expected: missing per-grid evidence and at least one incomplete load-path/detail assertion.

- [ ] **Step 3: Extract shared builders without changing behavior**

Move box meshing, beam segment generation, interval subtraction, cover checks, and interface construction from the 1,800-line `physical_building.py` into `buildings/common.py`. Keep `build_physical_building()` as the resource dispatcher and record assembler. Run the existing commercial tests before adding new geometry.

- [ ] **Step 4: Implement commercial detail**

Generate deterministic axes, Solid RC columns, longitudinal bars, closed stirrups with end confinement, floor/roof support, foundation/grade beams, two-way wall reinforcement, opening jamb/lintel reinforcement, and steel roof connections. Each generated role must publish material, family, dimensions, selection basis, and measured interface IDs.

- [ ] **Step 5: Run GREEN tests and commit**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_buildings.py tests/test_phase18_solver_blast_quality.py tests/test_phase18_solver_blast_keyword.py -k commercial
git add lsprepost_mcp/refined_building/solver_blast/buildings lsprepost_mcp/refined_building/solver_blast/physical_building.py tests/test_phase18_solver_blast_buildings.py tests/test_phase18_solver_blast_quality.py
git commit -m "feat: complete commercial structural load path"
```

---

### Task 7: Complete residential floors, core, stairs, walls, and internal-air connectivity

**Files:**
- Create: `lsprepost_mcp/refined_building/solver_blast/buildings/residential.py`
- Modify: `lsprepost_mcp/refined_building/solver_blast/physical_building.py`
- Modify: `tests/test_phase18_solver_blast_buildings.py`
- Modify: `tests/test_phase18_solver_blast_surface_topology.py`
- Modify: `tests/test_phase18_solver_blast_quality.py`

**Interfaces:**
- Consumes: residential Phase 18D package and `buildings/common.py`.
- Produces: `build_residential_physical_model(package) -> BuildingPhysicalParts` plus versioned connected internal-space/opening evidence.

- [ ] **Step 1: Add failing continuity and air-path tests**

```python
def test_residential_has_no_unplanned_storey_gap_or_unsupported_floor() -> None:
    model = _residential_building()
    assert model.unplanned_exterior_gap_intervals_m == ()
    assert audit_load_paths(model).unreachable_roles == ()


def test_residential_stairs_landings_core_and_balconies_are_supported() -> None:
    model = _residential_building()
    required = {"stair_flight", "stair_landing", "core_wall", "balcony_slab"}
    assert required <= {row.role for row in model.members}
    assert required.isdisjoint(audit_load_paths(model).unreachable_roles)


def test_residential_air_crosses_only_declared_openings() -> None:
    topology = classify_surface_topology(_residential_scene())
    assert topology.undeclared_wall_crossing_count == 0
    assert topology.undeclared_floor_crossing_count == 0
```

- [ ] **Step 2: Run RED tests**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_buildings.py tests/test_phase18_solver_blast_surface_topology.py tests/test_phase18_solver_blast_quality.py -k residential
```

- [ ] **Step 3: Implement the residential physical generator**

Generate continuous Solid slabs/beams/columns/shear walls/core, coupling beams, stair flights/landings, balcony support, wall boundary elements, opening reinforcement, and raft/strip foundation. Derive rooms, corridors, shafts, and door/window connections from artifact space/opening rows; closed walls and floors remain graph barriers.

- [ ] **Step 4: Verify deterministic multi-storey and multi-tower behavior**

Add a two-tower fixture and assert each tower independently reaches its foundation, no false cross-tower interface exists, and changing storey count invalidates only building/scene/package identities.

- [ ] **Step 5: Run GREEN tests and commit**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_buildings.py tests/test_phase18_solver_blast_surface_topology.py tests/test_phase18_solver_blast_quality.py -k residential
git add lsprepost_mcp/refined_building/solver_blast/buildings/residential.py lsprepost_mcp/refined_building/solver_blast/physical_building.py tests/test_phase18_solver_blast_buildings.py tests/test_phase18_solver_blast_surface_topology.py tests/test_phase18_solver_blast_quality.py
git commit -m "feat: complete residential physical topology"
```

---

### Task 8: Complete the subway RC box, pavilion, grade, excavation, and connected internal air

**Files:**
- Create: `lsprepost_mcp/refined_building/solver_blast/buildings/subway.py`
- Modify: `lsprepost_mcp/refined_building/solver_blast/physical_building.py`
- Modify: `lsprepost_mcp/refined_building/solver_blast/ground.py`
- Modify: `tests/test_phase18_solver_blast_buildings.py`
- Modify: `tests/test_phase18_solver_blast_surface_topology.py`
- Modify: `tests/test_phase18_solver_blast_quality.py`

**Interfaces:**
- Consumes: subway Phase 18D package and shared builders.
- Produces: `build_subway_physical_model(package) -> BuildingPhysicalParts`, excavation boxes, grade evidence, and connected entrance/interior-air evidence.

- [ ] **Step 1: Add failing underground enclosure and contact tests**

```python
def test_subway_rc_box_and_opaque_pavilion_are_solid() -> None:
    model = _subway_building()
    for role in ("subway_base_slab", "subway_side_wall", "subway_top_slab", "pavilion_opaque_solid_roof"):
        assert model.family_for_role(role) == "Solid"
    assert model.family_for_role("pavilion_glazing") == "Shell"
    assert model.family_for_role("pavilion_frame") == "Beam"


def test_subway_below_grade_exterior_is_all_soil_contact() -> None:
    topology = classify_surface_topology(_subway_scene())
    rows = [row for row in topology.surfaces if _centroid_z(row) < topology.grade_elevation_m]
    assert rows
    assert all(row.surface_class != "external_air_exposed" for row in rows if _is_outer_box(row))


def test_subway_entry_is_the_only_external_path_to_internal_air() -> None:
    evidence = audit_air_topology(_subway_scene())
    assert evidence.external_opening_ids == ("main_entrance",)
    assert evidence.external_path_to_soil_contact_count == 0
```

- [ ] **Step 2: Run RED tests**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_buildings.py tests/test_phase18_solver_blast_surface_topology.py tests/test_phase18_solver_blast_quality.py -k subway
```

- [ ] **Step 3: Implement the subway generator and excavation closure**

Generate Solid bottom/side/top slabs, haunches, shaft/retaining walls, stair flights/landings, Solid opaque pavilion walls/roof, Shell glazing, and Beam frame/rail/rebar. Subtract exact excavation boxes from soil. Expose interior-air boxes only through the main entrance/opening graph.

- [ ] **Step 4: Add no-overlap and passage-clearance audits**

Reject positive soil/RC overlap, blocked declared passages, unsupported stairs/platforms, pavilion edge gaps, glazing without frame interpolation, or below-grade external FSI.

- [ ] **Step 5: Run GREEN tests and commit**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_buildings.py tests/test_phase18_solver_blast_surface_topology.py tests/test_phase18_solver_blast_quality.py tests/test_phase18_solver_blast_scene.py -k subway
git add lsprepost_mcp/refined_building/solver_blast/buildings/subway.py lsprepost_mcp/refined_building/solver_blast/physical_building.py lsprepost_mcp/refined_building/solver_blast/ground.py tests/test_phase18_solver_blast_buildings.py tests/test_phase18_solver_blast_surface_topology.py tests/test_phase18_solver_blast_quality.py
git commit -m "feat: complete subway physical enclosure"
```

---

### Task 9: Expose authoritative layered previews and a four-step workbench

**Files:**
- Modify: `lsprepost_mcp/refined_blast/providers/solver_complete_ale_fsi.py:34-326`
- Modify: `lsprepost_mcp/refined_blast/preview.py:20-46,135-220`
- Modify: `lsprepost_mcp/web/refined_blast_preview.py`
- Modify: `lsprepost_mcp/web/refined_blast_api.py:1462-1575`
- Modify: `lsprepost_mcp/web/static/refined_blast_state.js`
- Modify: `lsprepost_mcp/web/static/refined_blast_workbench.js:6-55,269-484,845-960`
- Modify: `lsprepost_mcp/web/static/refined_blast_viewer.js:3-14`
- Modify: `lsprepost_mcp/web/static/refined_blast_workbench.css`
- Modify: `tests/test_phase18_solver_blast_provider.py`
- Modify: `tests/test_phase18f_preview.py`
- Modify: `tests/test_phase18f_state_contract.py`
- Modify: `tests/test_phase18f_web_contract.py`

**Interfaces:**
- Consumes: Provider `@4` schema/default, scene bounds, topology evidence, surface classifications, probes, and package identity.
- Produces: ten preview layers by adding `coupling_buffer` while retaining the existing nine IDs.
- Produces four workbench steps: `building`, `air_charge`, `audit_preview`, `generate_solve`.

- [ ] **Step 1: Add backend and browser RED tests**

```python
def test_solver_preview_distinguishes_active_air_buffer_tnt_and_soil() -> None:
    preview = _solver_complete_preview()
    assert preview["active_air_bounds_m"][2] == pytest.approx(preview["grade_elevation_m"])
    assert preview["coupling_buffer_bounds_m"][5] == pytest.approx(preview["grade_elevation_m"])
    assert preview["coupling_buffer_layers"] == 2
    assert preview["surface_class_counts"]["soil_contact"] > 0


def test_workbench_has_four_steps_and_collapses_expert_fields() -> None:
    source = _workbench_source()
    assert source.count('data-refined-step="') == 4
    assert 'data-refined-expert' in source
    assert 'hidden' in source
```

Add a Node runtime case that edits TNT mass/X/Y/Z, asymmetric margins, near-field size, ground size, and layer count; it must invalidate preview/generation and send only the provider-owned normalized payload.

- [ ] **Step 2: Run RED tests**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_provider.py tests/test_phase18f_preview.py tests/test_phase18f_state_contract.py tests/test_phase18f_web_contract.py
```

- [ ] **Step 3: Extend authoritative preview payloads**

Add `coupling_buffer` to Python/JS closed layer IDs, colors, byte/count budgets, fingerprints, visibility state, and viewer disposal. `fluid_domain` contains active air only; buffer has its own neutral bounds/HEX8 sample and legend. Persist surface-class counts, boundary sets, probes, material profile, and soft size estimate.

- [ ] **Step 4: Replace the eight-step rail with four task steps**

Render common fields directly, keep expert JSON collapsed, display units/ranges, and show validation gates as text. TNT position edits update the authoritative blast-source preview. Invalid collision/domain/budget feedback appears before save/generate. Preserve direct-route, back navigation, CAS, late-response guards, explicit external-action confirmation, and legacy workbench isolation.

- [ ] **Step 5: Run GREEN tests, Node syntax/runtime, and commit**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_provider.py tests/test_phase18f_preview.py tests/test_phase18f_state_contract.py tests/test_phase18f_web_contract.py tests/test_web_static.py tests/test_web_startup.py
python -m compileall -q lsprepost_mcp
git add lsprepost_mcp/refined_blast/providers/solver_complete_ale_fsi.py lsprepost_mcp/refined_blast/preview.py lsprepost_mcp/web/refined_blast_preview.py lsprepost_mcp/web/refined_blast_api.py lsprepost_mcp/web/static/refined_blast_state.js lsprepost_mcp/web/static/refined_blast_workbench.js lsprepost_mcp/web/static/refined_blast_viewer.js lsprepost_mcp/web/static/refined_blast_workbench.css tests/test_phase18_solver_blast_provider.py tests/test_phase18f_preview.py tests/test_phase18f_state_contract.py tests/test_phase18f_web_contract.py
git commit -m "feat: guide layered phase18 blast modeling"
```

---

### Task 10: Persist topology, boundary, probe, energy, and soft-size evidence

**Files:**
- Modify: `lsprepost_mcp/refined_building/solver_blast/keyword.py`
- Modify: `lsprepost_mcp/refined_building/solver_blast/validation.py`
- Modify: `lsprepost_mcp/refined_building/solver_blast/results.py`
- Modify: `scripts/generate_phase18_solver_blast_models.py:132-251`
- Modify: `scripts/run_phase18_solver_blast_validation.py`
- Modify: `tests/test_phase18_solver_blast_validation.py`
- Modify: `tests/test_phase18_solver_blast_script.py`

**Interfaces:**
- Consumes: all audit/topology/boundary identities and R12 output files.
- Produces: persisted manifest closure, `SolverBlastRunReport` energy/arrival/reflection fields, and observation-only `model_size_band` records.

- [ ] **Step 1: Add persisted tamper and result RED tests**

```python
def test_manifest_rejects_forged_surface_or_buffer_evidence(generated_model: Path) -> None:
    manifest = _read_manifest(generated_model)
    manifest["air_topology"]["buffer_cell_count"] += 1
    _rewrite_manifest_and_hash(generated_model, manifest)
    report = inspect_solver_blast_deck(generated_model)
    assert not report.ok
    assert "air_topology_mismatch" in {row.code for row in report.findings}


def test_file_size_band_is_observational_not_a_gate(tmp_path: Path) -> None:
    summary = _generate_small_valid_model(tmp_path)
    row = summary["models"][0]
    assert row["model_size_band_mib"] == [45.0, 70.0]
    assert row["model_size_observation"] in {"below", "within", "above"}
    assert summary["all_static_validation_ok"] is True
    assert "all_physical_size_targets_met" not in summary


def test_run_report_rejects_nonfinite_or_excess_hourglass_energy() -> None:
    report = evaluate_solver_blast_run(_model_dir(), _run_with_bad_hourglass_ratio())
    assert not report.ok
    assert "hourglass_energy_ratio" in {row.code for row in report.findings}
```

- [ ] **Step 2: Run RED tests**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_validation.py tests/test_phase18_solver_blast_script.py
```

- [ ] **Step 3: Extend closed evidence contracts**

Persist and reparse exact counts/fingerprints for active air, vacuum buffer, TNT, every surface class, side/top/bottom boundaries, probe sets, mesh quality, load path, material review, and file-size observation. Unknown manifest fields and synchronized forgeries remain rejected.

Extend `SolverBlastRunReport` with finite energy totals, hourglass ratio, contact/ALE leakage indicators, per-probe arrival rows, and boundary reflection timing. Software defaults are explicit constants and project overrides are persisted with old/new values, reason, scope, and reviewer.

- [ ] **Step 4: Add staged `mcheck`, smoke, and 1 ms summary states**

Add a closed `--stage {mcheck,smoke,propagation}` CLI. `run_phase18_solver_blast_validation.py` records the selections as separate immutable states named `mcheck`, `smoke_0p1ms`, and `propagation_1ms`. A later stage cannot become `ok` unless every earlier stage has the same K SHA-256 and solver SHA-256 and is `ok`. Add argparse/runtime tests for all three values and rejection of every other value.

- [ ] **Step 5: Run GREEN tests and commit**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_validation.py tests/test_phase18_solver_blast_script.py tests/test_phase18_solver_blast_keyword.py
git add lsprepost_mcp/refined_building/solver_blast/keyword.py lsprepost_mcp/refined_building/solver_blast/validation.py lsprepost_mcp/refined_building/solver_blast/results.py scripts/generate_phase18_solver_blast_models.py scripts/run_phase18_solver_blast_validation.py tests/test_phase18_solver_blast_validation.py tests/test_phase18_solver_blast_script.py
git commit -m "feat: persist phase18 propagation evidence"
```

---

### Task 11: Run software compatibility, packaging, and independent review gates

**Files:**
- Modify only when a failing compatibility test identifies an in-scope defect.
- Test: all files listed below.

**Interfaces:**
- Consumes: Tasks 1–10.
- Produces: fresh software compatibility evidence with zero unreviewed failures.

- [ ] **Step 1: Run solver-blast core tests**

```powershell
python -m pytest -q tests/test_phase18_solver_blast_contracts.py tests/test_phase18_solver_blast_buildings.py tests/test_phase18_solver_blast_layered_domain.py tests/test_phase18_solver_blast_surface_topology.py tests/test_phase18_solver_blast_quality.py tests/test_phase18_solver_blast_scene.py tests/test_phase18_solver_blast_keyword.py tests/test_phase18_solver_blast_validation.py tests/test_phase18_solver_blast_provider.py tests/test_phase18_solver_blast_script.py
```

Expected: all PASS.

- [ ] **Step 2: Run Phase 18C–F and Web compatibility**

```powershell
python -m pytest -q tests/test_phase18d_phase18abc_compatibility.py tests/test_phase18d_asset_resources.py tests/test_phase18e_explicit_ale_fsi.py tests/test_phase18e_validation_preview.py tests/test_phase18f_api.py tests/test_phase18f_preview.py tests/test_phase18f_state_contract.py tests/test_phase18f_validation_flow.py tests/test_phase18f_web_contract.py tests/test_web_static.py tests/test_web_startup.py
```

If the known approved-subway heavy node is included, run it once with a 900-second or greater process budget and preserve JUnit output; never restart it merely because output is buffered.

- [ ] **Step 3: Run static, Node, and packaging gates**

```powershell
python -m compileall -q lsprepost_mcp tests scripts
python -m pytest -q tests/test_packaging_and_integration_boundaries.py tests/test_phase18c_packaging.py tests/test_repo_layout.py
git diff --check
```

Use the bundled Node executable from `tests/node_runtime.py` to run `--check` on `app.js`, `refined_blast_state.js`, `refined_blast_workbench.js`, `refined_blast_viewer.js`, and `model_viewer_webgl.js`, then execute the affected runtime CJS fixtures.

- [ ] **Step 4: Request independent scoped review**

Review the complete implementation range against the approved spec. Report exact `Critical / Important / Minor` counts, spec PASS/FAIL, and readiness. Fix every Critical/Important finding with a failing regression test, rerun the affected aggregation, and request one bounded re-review.

- [ ] **Step 5: Verify the compatibility/review repair range is clean**

```powershell
git diff --check
git status --short
```

Every compatibility or review defect is repaired in its own bounded RED/GREEN task and commits exactly the files named by that repair. Task 11 creates no aggregate catch-all commit. If no defect is found, this step is verification-only.

---

### Task 12: Generate three immutable snapshots and obtain fresh LS-PrePost/R12 evidence

**Files:**
- Create: `scripts/run_phase18_solver_blast_sensitivity.py`
- Create: `docs/reviews/phase18/PHASE18_LAYERED_AIR_PHYSICAL_FIDELITY_REPORT.zh-CN.md`
- Modify: `tests/test_phase18_solver_blast_script.py`
- External output: `E:\K文件模型\Phase18_分层空气域_物理细化_20260822\`

**Interfaces:**
- Consumes: reviewed code, configured LS-PrePost 4.12, configured LS-DYNA R12, and immutable `config@4` defaults.
- Produces: three final package identities, import evidence, mcheck, 0.1 ms smoke, 1 ms propagation, sensitivity results, and one formal report.

- [ ] **Step 1: Add dry-run and strict-serial tests for sensitivity/acceptance scripts**

```python
def test_sensitivity_dry_run_is_one_model_three_margins_and_serial(tmp_path: Path) -> None:
    payload = _run_sensitivity_dry_run(tmp_path)
    assert payload["resource_id"] == "commercial_supermarket_detailed_building"
    assert payload["lateral_margin_m"] == [3.0, 4.5, 6.0]
    assert payload["parallel_jobs"] == 1
    assert payload["external_program_started"] is False
```

Run:

```powershell
python -m pytest -q tests/test_phase18_solver_blast_script.py
git add scripts/run_phase18_solver_blast_sensitivity.py tests/test_phase18_solver_blast_script.py
git commit -m "feat: add phase18 sensitivity runner"
```

- [ ] **Step 2: Generate a new immutable output root**

```powershell
python scripts/generate_phase18_solver_blast_models.py --output-root "E:\K文件模型\Phase18_分层空气域_物理细化_20260822" --mass-kg 2 --charge-position -2 1.5 4 --air-cell-size-m 0.225 --near-field-cell-size-m 0.15 --ground-cell-size-m 0.25 --air-margins 3 3 3 3 3 --coupling-buffer-layers 2 --material-profile verification_reference --termination-time-s 0.001
```

Expected: three folders, `all_static_validation_ok=true`, exact SHA-256 records, active-air/buffer/TNT counts, no hard size-band result, and no external program started.

- [ ] **Step 3: Run LS-PrePost imports strictly serially**

```powershell
python scripts/validate_phase18_solver_blast_imports.py --output-root "E:\K文件模型\Phase18_分层空气域_物理细化_20260822" --timeout-s 900
```

Expected: three import records with `ok=true`, zero keyword-reader errors, and saved screenshots showing structure, soil, active air, vacuum buffer, and TNT as distinct parts.

- [ ] **Step 4: Run R12 mcheck and 0.1 ms smoke strictly serially**

Use the already tested stage interface from Task 10 and run each folder in order:

```powershell
python scripts/run_phase18_solver_blast_validation.py --output-root "E:\K文件模型\Phase18_分层空气域_物理细化_20260822" --stage mcheck
python scripts/run_phase18_solver_blast_validation.py --output-root "E:\K文件模型\Phase18_分层空气域_物理细化_20260822" --stage smoke
```

Expected: all three mcheck and smoke records `ok=true`, no fatal/negative-volume/nonfinite findings, and identical K/solver hashes across stages.

- [ ] **Step 5: Run the three 1 ms propagation solves once, strictly serially**

```powershell
python scripts/run_phase18_solver_blast_validation.py --output-root "E:\K文件模型\Phase18_分层空气域_物理细化_20260822" --stage propagation
```

Expected: each model reaches `0.001 s`, terminates normally, reports nonzero active FSI segments, finite energy, TNT→air→building causal arrivals, and no unaccepted error. Preserve JUnit/JSON/terminal output; do not call interrupted or stdout-lost runs PASS.

- [ ] **Step 6: Run boundary/mesh sensitivity and record the soft size observation**

```powershell
python scripts/run_phase18_solver_blast_sensitivity.py --output-root "E:\K文件模型\Phase18_分层空气域_物理细化_20260822" --resource-id commercial_supermarket_detailed_building --lateral-margin-m 3 4.5 6 --parallel-jobs 1
```

Record pressure/impulse/arrival and structural-response differences. The software reference difference is 5%; exceeding it blocks the reference profile pending project review but does not redefine 5% as a universal engineering standard. Record each model size as `below`, `within`, or `above` the 45–70 MiB observation band without changing PASS.

- [ ] **Step 7: Write and verify the formal report**

The report must list exact commits, model/solver hashes, entity counts, material profile, layer count, surface classifications, boundary cards, import/mcheck/smoke/1 ms results, sensitivity, warnings, file sizes, and the unchanged engineering flags. Include every failed attempt and repair; do not overwrite historical evidence.

```powershell
git diff --check
git status --short
git add docs/reviews/phase18/PHASE18_LAYERED_AIR_PHYSICAL_FIDELITY_REPORT.zh-CN.md
git commit -m "docs: record phase18 layered-air validation"
```

Expected: the formal report is committed separately from production fixes; output packages remain external evidence and are not added to Git.

## Plan Self-Review

- Spec coverage: Tasks 1–4 cover versioning, layered air, 1–5 buffer, boundaries, topology, and exposed-face FSI; Tasks 5–8 cover materials, mesh, load paths, and all three buildings; Tasks 9–10 cover frontend, persistence, evidence, and soft size; Tasks 11–12 cover compatibility and final external validation.
- Placeholder scan: the plan contains no undefined task, deferred implementation, or generic “add tests/error handling” step. Every task has exact files, interfaces, RED command, GREEN command, and commit boundary.
- Type consistency: canonical margins use `(x_min, x_max, y_min, y_max, top)` everywhere; config target is `@4`; active air, TNT, and buffer part-role names are stable across domain, keyword, preview, manifest, and tests.
- Safety: external programs are invoked only in Tasks 3 and 12 after explicit approval; heavy models are serial; historical or interrupted runs are never accepted.
