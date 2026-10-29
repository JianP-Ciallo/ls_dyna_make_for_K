# Phase 18A-1 Component Model Resources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the audited `2.k` structural mesh into four independent, dependency-closed beam/column/slab/base keyword resources and make them safely callable from existing model-generation paths.

**Architecture:** A focused extractor writes normalized-SI component bundles from the audited source deck. A model-resource runtime validates, exports, transforms, and remaps each bundle into a `ComponentFragment`; the central keyword dispatcher attaches optional resource instances after the existing scene builder finishes, so old inputs remain byte-for-byte unchanged when no resource is selected.

**Tech Stack:** Python 3.12+, stdlib `gzip/hashlib/json/pathlib/tempfile`, existing LS-DYNA keyword parsers, `unittest`, JSON resource manifests.

## Global Constraints

- Source identity is fixed to SHA-256 `C1C02A9E832852854B47CD3720BC9348CF48989484D25E1A54036836D0697A22`.
- Source deck remains read-only; verify its hash before extraction and while streaming mesh records.
- Published payload units are `SI_m_s_kg_N_Pa`; provenance retains original `tonne_mm_s_N_MPa` values and IDs.
- Four resource IDs are fixed: `2k_rc_beam_reference`, `2k_rc_column_reference`, `2k_rc_slab_reference`, `2k_rc_base_reference`.
- Every bundle keeps Solid, Beam, N3 orientation nodes, Part, Section, material, Curve/erosion, Set, and coupling dependencies closed.
- Existing generation output must remain unchanged when `model_resources` is absent or empty.
- Never silently drop Beam or embedded coupling data for compatibility.
- All published resources remain `source_reference` and `requires_project_review=true`.
- Work in the current dirty checkout because Phase 18A prerequisites are uncommitted here; do not stage, commit, overwrite, or revert unrelated changes.

---

### Task 1: Component resource contracts and static split definitions

**Files:**
- Create: `lsprepost_mcp/component_model_resources.py`
- Create: `tests/test_phase18a1_component_resources.py`

**Interfaces:**
- Produces: `ComponentResourceSpec`, `COMPONENT_RESOURCE_SPECS`, `component_resource_spec(resource_id)`.
- Each spec exposes `resource_id`, `component_kind`, `part_ids`, `solid_count`, `beam_count`, `section_ids`, `material_ids`, `set_ids`, and one coupling identity.

- [ ] **Step 1: Write failing contract tests**

```python
def test_four_combined_component_specs_cover_structural_parts_once():
    specs = list(COMPONENT_RESOURCE_SPECS.values())
    assert {spec.resource_id for spec in specs} == {
        "2k_rc_beam_reference", "2k_rc_column_reference",
        "2k_rc_slab_reference", "2k_rc_base_reference",
    }
    assert sum(spec.solid_count for spec in specs) == 126290
    assert sum(spec.beam_count for spec in specs) == 61961
    assert sorted(pid for spec in specs for pid in spec.part_ids) == [201, 202, 203, 301, 302, 303, 401, 402, 501, 502]
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m unittest tests.test_phase18a1_component_resources -v`
Expected: import failure for `lsprepost_mcp.component_model_resources`.

- [ ] **Step 3: Implement immutable static contracts**

```python
@dataclass(frozen=True)
class ComponentResourceSpec:
    resource_id: str
    component_kind: str
    part_ids: tuple[int, ...]
    solid_count: int
    beam_count: int
    section_ids: tuple[int, ...]
    material_ids: tuple[int, ...]
    set_ids: tuple[int, ...]
    coupling: tuple[int, int, int, int]
```

Use exact audited mappings from the design document. Reject unknown IDs with a `ValueError` listing the four known resources.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m unittest tests.test_phase18a1_component_resources -v`
Expected: contract tests pass.

### Task 2: Streaming component extraction and normalized-SI package writer

**Files:**
- Modify: `lsprepost_mcp/component_model_resources.py`
- Modify: `scripts/import_2k_resources.py`
- Modify: `tests/test_phase18a1_component_resources.py`
- Generate: `resources/model_library/phase18/components/<resource-id>/manifest.json`
- Generate: `resources/model_library/phase18/components/<resource-id>/component.k.gz`
- Generate: `resources/model_library/phase18/components/<resource-id>/audit.json`

**Interfaces:**
- Consumes: `decompose_keyword_deck()` and audited material assets.
- Produces: `write_component_resource_packages(report, output_root) -> dict[str, dict[str, str]]`.

- [ ] **Step 1: Write failing extraction tests**

Tests must assert for all four packages:

```python
manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
assert manifest["unit_system"] == "SI_m_s_kg_N_Pa"
assert manifest["validation_status"] == "source_reference"
assert manifest["requires_project_review"] is True
assert manifest["payload"]["sha256"] == sha256(package / "component.k.gz")
assert manifest["solid_count"] == expected_solid_count
assert manifest["beam_count"] == expected_beam_count
```

Full payload scan must verify `*KEYWORD`, `*END`, expected Part IDs, no PID 1001/1002, no unused MAT 9/10/11/13, no missing node reference, and N3 nodes present.

- [ ] **Step 2: Run the extraction test and verify RED**

Run: `python -m unittest tests.test_phase18a1_component_resources.ComponentPackageWriterTests -v`
Expected: `write_component_resource_packages` is missing.

- [ ] **Step 3: Implement the two-pass streaming extractor**

Pass 1 selects Solid and Beam records for all four PID groups simultaneously and collects topology/N3 node IDs. Pass 2 selects only required Node records. Non-mesh cards are selected from the audited report by Part/Section/MAT/Curve/Set/Coupling identity.

Convert coordinates `mm -> m`, density `tonne/mm^3 -> kg/m^3`, stresses `MPa -> Pa`, and beam diameters `mm -> m`. Emit SI K&C/steel cards from audited typed material resources; do not reinterpret K&C sentinel values as physical zero values.

Write each package into a temporary sibling directory, validate it, then atomically replace the target directory. Rehash the source during mesh streaming and remove temporary output if the hash changes.

- [ ] **Step 4: Extend the import script**

`python scripts/import_2k_resources.py E:\Desktop\2.k --component-packages` must write the four directories after the existing full-resource package. JSON stdout must include a `component_packages` mapping.

- [ ] **Step 5: Run writer tests and generate real packages**

Run:

```powershell
python -m unittest tests.test_phase18a1_component_resources.ComponentPackageWriterTests -v
python scripts/import_2k_resources.py E:\Desktop\2.k --component-packages
```

Expected: four bundles are generated; totals equal 126,290 Solid and 61,961 Beam.

### Task 3: Resource validation, independent K export, and user-facing tools

**Files:**
- Modify: `lsprepost_mcp/model_library.py`
- Create: `lsprepost_mcp/tool_model_resources.py`
- Modify: `lsprepost_mcp/tools.py`
- Modify: `tests/test_phase18a1_component_resources.py`
- Modify: `tests/test_jsonrpc.py`

**Interfaces:**
- Produces: `validate_model_resource(resource_id)`, `export_model_resource(resource_id, output_path)`, MCP tools `list_model_resources`, `get_model_resource`, `export_model_resource`.

- [ ] **Step 1: Write failing library and tool tests**

```python
result = validate_model_resource("2k_rc_beam_reference")
self.assertTrue(result["valid"])
self.assertEqual(6600, result["solid_count"])

exported = export_model_resource("2k_rc_beam_reference", output_path)
self.assertTrue(exported.is_file())
self.assertTrue(exported.read_text(encoding="utf-8").startswith("*KEYWORD"))
```

Tool schemas must reject unknown arguments and paths outside the configured project workspace. Listing/get responses must be JSON serializable and must not expose the original absolute source path.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_phase18a1_component_resources tests.test_jsonrpc -v`
Expected: missing validation/export functions or missing tool registrations.

- [ ] **Step 3: Implement validation and controlled export**

Validation rehashes the payload, streams counts/references, and checks manifest dependencies. Export decompresses to an explicitly validated target below the project workspace using temporary-file replacement.

- [ ] **Step 4: Register MCP tools and schemas**

Tool arguments:

```json
{
  "resource_id": "2k_rc_beam_reference",
  "project_name": "beam_resource_export",
  "filename": "beam_component.k",
  "if_exists": "error"
}
```

The tool returns resource ID, output path, SHA-256, unit system, counts, and review status; it never starts external software.

- [ ] **Step 5: Run library/tool tests and verify GREEN**

Run: `python -m unittest tests.test_phase18a1_component_resources tests.test_jsonrpc tests.test_materials -v`.

### Task 4: Transform and collision-safe ID remapping

**Files:**
- Create: `lsprepost_mcp/component_resource_adapter.py`
- Modify: `lsprepost_mcp/component_model_resources.py`
- Modify: `tests/test_phase18a1_component_resources.py`

**Interfaces:**
- Produces: `ResourceIdNamespace`, `ComponentFragment`, `instantiate_model_resource(resource_id, transform, id_namespace, material_binding="source_reference")`.

- [ ] **Step 1: Write failing transform/remap tests**

Create two instances of the same compact resource with different namespaces and transforms. Assert disjoint Node/Element/Part/Section/Set IDs, translated/rotated coordinates, updated element connectivity, and updated Set/Coupling references.

```python
fragment = instantiate_model_resource(
    "2k_rc_beam_reference",
    transform={"translation_m": [2.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 90.0]},
    id_namespace=ResourceIdNamespace.from_offsets(node=1_000_000, element=2_000_000, part=3000, section=4000, material=5000, set_id=6000, curve=7000),
)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_phase18a1_component_resources.ComponentResourceAdapterTests -v`
Expected: adapter module or API missing.

- [ ] **Step 3: Implement typed parsing and remapping**

Parse only the audited component keyword subset. Remap all identity and reference fields together: Node, Element, Part, Section, Material, Curve, Set, and coupling IDs. Apply Z-Y-X rigid rotation then translation to node coordinates. Reject scale, reflection, unknown cards, unsupported material binding, or non-finite transforms.

- [ ] **Step 4: Emit `ComponentFragment` keyword and metadata**

The fragment exposes `keyword_text`, count fields, ID ranges, source-to-instance maps, interfaces, resource version, payload SHA, and a deterministic fingerprint. It must remain JSON serializable except for `keyword_text`, which is a plain string.

- [ ] **Step 5: Run adapter tests and verify GREEN**

Run: `python -m unittest tests.test_phase18a1_component_resources.ComponentResourceAdapterTests -v`.

### Task 5: Additive compatibility attachment in existing generation paths

**Files:**
- Modify: `lsprepost_mcp/schema.py`
- Modify: `lsprepost_mcp/dyna_keyword.py`
- Modify: `lsprepost_mcp/project_store.py`
- Modify: `tests/test_phase18a1_component_resources.py`
- Modify: `tests/test_tools.py`
- Modify: `tests/test_blast_case.py`
- Modify: `tests/test_phase14_ale.py`

**Interfaces:**
- Consumes: `instantiate_model_resource`.
- Produces: optional top-level `model_resources: list[JSONDict]` accepted by common model specs and attached centrally after the original builder returns.

- [ ] **Step 1: Write backward-compatibility tests first**

For three representative existing model types, build baseline specs without `model_resources` and assert the resulting keyword and normalized metadata are unchanged after the feature is introduced.

- [ ] **Step 2: Write failing resource-attachment tests**

```python
spec["model_resources"] = [{
    "id": "column_1",
    "model_resource_id": "2k_rc_column_reference",
    "transform": {"translation_m": [1.0, 2.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0]},
    "material_binding": "source_reference"
}]
keyword, metadata = build_keyword(parse_model_spec(spec))
self.assertIn("2k_rc_column_reference", keyword)
self.assertEqual(1, metadata["model_resource_instance_count"])
```

- [ ] **Step 3: Extend schema additively**

Validate stable instance IDs, known resource IDs, finite transforms, enum material binding, and no unknown fields. Empty/absent `model_resources` normalizes to `[]`.

- [ ] **Step 4: Attach fragments centrally**

`build_keyword()` calls the existing builder first. A central attachment function scans maximum host IDs, allocates non-overlapping namespaces, instantiates each resource, inserts fragment blocks immediately before the single final `*END`, and augments metadata without changing original fields.

Reject host unit systems other than `SI_m_s_kg_N_Pa` and callers that declare no Beam/embedded-coupling capability. Do not alter resource-free output.

- [ ] **Step 5: Run compatibility tests**

Run targeted assembly, simplified blast, ALE blast, schema, tool, and resource tests. Expected: resource-enabled specs contain closed fragments; resource-free baselines remain unchanged.

### Task 6: Full source audit, reassembly proof, and delivery verification

**Files:**
- Modify: `tests/test_phase18a1_component_resources.py`
- Generate: `resources/model_library/phase18/components/**`
- Create: `docs/reviews/phase18/PHASE18A1_COMPONENT_RESOURCE_REPORT.zh-CN.md`
- Modify: `docs/ROADMAP.zh-CN.md`

**Interfaces:**
- Produces: final evidence report and updated Phase 18A-1 status.

- [ ] **Step 1: Add full-source union tests**

Verify the four component Element source-ID sets are disjoint and their union equals all source elements for PIDs 201–502. Reassemble by `source_node_id` and source transforms; compare coordinates, connectivity, Part roles, and four coupling identities to the audited source.

- [ ] **Step 2: Verify deterministic regeneration**

Run the import twice and assert identical manifest JSON, audit JSON, and payload SHA-256 values.

- [ ] **Step 3: Run the complete relevant verification matrix**

```powershell
python -m unittest tests.test_phase18a1_component_resources tests.test_phase18_resource_library tests.test_keyword_decomposition tests.test_materials tests.test_schema tests.test_tools tests.test_jsonrpc -v
python -m compileall -q lsprepost_mcp scripts
git diff --check -- lsprepost_mcp scripts tests resources/model_library resources/materials docs/ROADMAP.zh-CN.md docs/reviews/phase18
```

- [ ] **Step 4: Write the evidence report**

Record source/payload hashes, per-resource Node/Solid/Beam counts, dependency closure, union/reassembly results, compatible generation paths, tests executed, known limitations, and `source_reference` status.

- [ ] **Step 5: Update roadmap status only after verification**

Mark Phase 18A-1 implemented only if all required commands exit zero. Do not claim LS-DYNA engineering validation or solver success.
