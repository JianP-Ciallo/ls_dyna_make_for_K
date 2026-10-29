# Phase 18B Reviewed Resource Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the six audited `2.k` material bundles and their used Section/Curve/Part/Set/Coupling relationships into hash-bound, syntax-and-unit-reviewed project resources that Phase 18C can consume without granting engineering-validation claims.

**Architecture:** Organize resources behind two stable public roots: a recursively discovered material library and a recursively discovered model library. Keep Section/Curve/Part/Set/Coupling catalogs under `model_library/structural`, keep source extraction immutable at `source_reference`, and store hash-bound review evidence in a separate checked-in audit area. Public IDs remain path-independent, duplicate IDs fail loudly, and Phase 18C receives only resources whose effective status is `syntax_unit_reviewed` and whose review evidence verifies.

**Tech Stack:** Python 3.12 standard library, `unittest`, JSON resource files, existing MCP tool registry, deterministic LS-DYNA keyword decomposition.

## Global Constraints

- The only accepted source deck SHA-256 is `c1c02a9e832852854b47cd3720bc9348cf48989484d25e1a54036836d0697a22`.
- Raw extraction always writes `validation_status="source_reference"`; extraction code must never self-promote a resource.
- Effective `syntax_unit_reviewed` status requires a matching canonical resource hash in the checked-in review manifest.
- `requires_project_review` remains `true` for every `2.k` resource, including reviewed resources.
- `syntax_unit_reviewed` proves syntax, dependency closure, source traceability and SI conversion consistency only; it never implies solver calibration, experiment correlation or `engineering_validated` status.
- Used resources are exactly MID 2/3/5/8/12/14, SECID 1–6, Curve 1, the 12 used Parts, the seven published Sets and the five source coupling records.
- Unused MID 9/10/11/13, SECID 7/8 and Part Set 5/7/8 remain audit-only and cannot appear in the production structural library.
- Existing generic material resolution and existing model-resource calls remain backward compatible.
- Material and model resource identity is ID-based and remains stable across the directory migration.
- Recursive discovery rejects duplicate IDs instead of silently replacing an earlier resource.
- No LS-PrePost or LS-DYNA process is launched by this plan.
- Every commit stages only the files named by its task because the shared worktree contains unrelated changes.

---

## File Structure

### New files

- `lsprepost_mcp/phase18_resource_review.py` — canonical hashes, review-manifest loading, evidence verification and effective-status overlay.
- `lsprepost_mcp/structural_resources.py` — list/get/validate API for reviewed Section/Curve/Part/Set/Coupling catalogs.
- `lsprepost_mcp/tool_structural_resources.py` — MCP handlers for structural-resource and review validation.
- `resources/reviews/phase18/2k_syntax_unit_review.json` — checked-in hash-bound review evidence.
- `resources/model_library/structural/phase18/2k/2k_sections_used.json` — six used section definitions and normalized dimensions.
- `resources/model_library/structural/phase18/2k/2k_curve1_kc_rate.json` — K&C rate curve and source dependency.
- `resources/model_library/structural/phase18/2k/2k_part_role_map.json` — 12 source Part roles and material/section/EOS bindings.
- `resources/model_library/structural/phase18/2k/2k_sets_used.json` — seven published Set definitions and source spans.
- `resources/model_library/structural/phase18/2k/2k_embedded_couplings.json` — five coupling records with resolved endpoint kinds.
- `scripts/review_phase18_resources.py` — candidate-manifest creation and checked-in-manifest verification.
- `tests/test_phase18b_resource_review.py` — pure review-contract and material-bundle tests.
- `tests/test_phase18b_structural_resources.py` — structural catalog generation, closure and public API tests.
- `docs/reviews/phase18/PHASE18B_RESOURCE_REVIEW.zh-CN.md` — final software-side review report and engineering boundary.

### Modified files

- `lsprepost_mcp/config.py` — resource and review paths.
- `lsprepost_mcp/materials.py` — typed resource validation and effective review status without changing generic material semantics.
- `lsprepost_mcp/keyword_decomposition.py` — deterministic structural-catalog extraction and writing.
- `lsprepost_mcp/tool_materials.py` — material-resource validation handler.
- `lsprepost_mcp/tools.py` — new public tool registrations.
- `scripts/import_2k_resources.py` — structural output and review verification switches.
- `tests/test_phase18_resource_library.py` — formal effective-status and closure assertions.
- `tests/test_jsonrpc.py` — tool registration and JSON-RPC calls.
- `tests/test_tools.py` — strict tool-schema coverage.
- `tests/test_packaging_and_integration_boundaries.py` — distribution inclusion and path-safety checks.
- `docs/ROADMAP.zh-CN.md` — Phase 18B completion status and report link after all gates pass.
- `docs/superpowers/specs/2026-08-05-phase18b-library-organization-design.md` — approved two-library and audit-area organization contract.

---

### Task 0: Recursive Two-Library Layout and Stable IDs

**Files:**
- Modify: `lsprepost_mcp/materials.py`
- Modify: `lsprepost_mcp/model_library.py`
- Modify: `scripts/import_2k_resources.py`
- Modify: `tests/test_materials.py`
- Modify: `tests/test_phase18a1_component_resources.py`

**Interfaces:**
- Consumes: nested material JSON files and nested model `manifest.json` files below the existing library roots.
- Produces: `_material_files(root: Path = MATERIALS_DIR)`, `load_materials(root: Path = MATERIALS_DIR)`, `_manifest_files(root: Path = MODEL_LIBRARY_DIR)`, and `load_model_resources(root: Path = MODEL_LIBRARY_DIR)` with recursive discovery and duplicate-ID rejection.

- [ ] **Step 1: Write failing recursive-discovery and duplicate-ID tests**

Use temporary nested directories to prove a resource is found independently of its physical location and two files with the same ID are rejected:

```python
def test_nested_material_resource_is_discovered_by_stable_id(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        write_json(root / "phase18" / "2k" / "steel.json", {"id": "stable_steel", "name": "Steel"})
        self.assertIn("stable_steel", load_materials(root))

def test_duplicate_material_id_is_rejected(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        write_json(root / "a" / "one.json", {"id": "duplicate"})
        write_json(root / "b" / "two.json", {"id": "duplicate"})
        with self.assertRaisesRegex(ValueError, "duplicate material resource id 'duplicate'"):
            load_materials(root)
```

Add equivalent nested-manifest and duplicate-model-ID tests for `load_model_resources(root)`.

- [ ] **Step 2: Run the layout tests and verify RED**

Run: `python -m unittest tests.test_materials tests.test_phase18a1_component_resources -v`

Expected: FAIL because the loaders do not accept an alternate root, material discovery is flat, and duplicate IDs are silently overwritten.

- [ ] **Step 3: Implement minimal recursive discovery and duplicate rejection**

Use sorted `rglob("*.json")` for materials and sorted `rglob("manifest.json")` for models. Material discovery must exclude non-material catalog and audit files by remaining rooted only below `MATERIALS_DIR`. Raise a `ValueError` containing the duplicate ID and both paths before insertion.

- [ ] **Step 4: Update import defaults to canonical destinations**

Use these defaults without changing CLI option names:

```python
--model-dir      resources/model_library/references/phase18/2k_complete_reference
--materials-dir  resources/materials/phase18/2k
--components-dir resources/model_library/components/phase18/2k
--structural-dir resources/model_library/structural/phase18/2k
```

- [ ] **Step 5: Run layout and existing compatibility tests**

Run: `python -m unittest tests.test_materials tests.test_phase18_resource_library tests.test_phase18a1_component_resources -v`

Expected: all selected tests pass before physical resources are migrated because recursive loaders continue to discover the old flat/legacy paths.

- [ ] **Step 6: Commit the organization foundation**

```powershell
git add -- lsprepost_mcp/materials.py lsprepost_mcp/model_library.py scripts/import_2k_resources.py tests/test_materials.py tests/test_phase18a1_component_resources.py docs/superpowers/specs/2026-08-05-phase18b-library-organization-design.md docs/superpowers/plans/2026-08-05-phase18b-reviewed-resource-library.md
git diff --cached --check
git commit -m "refactor: organize material and model resource discovery"
```

---

### Task 1: Hash-Bound Review Contract

**Files:**
- Create: `lsprepost_mcp/phase18_resource_review.py`
- Modify: `lsprepost_mcp/config.py`
- Create: `tests/test_phase18b_resource_review.py`

**Interfaces:**
- Consumes: JSON mappings loaded from material and structural resource files.
- Produces: `canonical_resource_sha256(resource) -> str`, `load_phase18_review_manifest() -> JSONDict`, `validate_phase18_review_manifest(manifest, resources) -> JSONDict`, and `apply_effective_review(resource, manifest) -> JSONDict`.

- [ ] **Step 1: Write failing canonical-hash and anti-self-promotion tests**

Add tests that prove metadata changes do not alter the canonical payload hash, content changes do, and an unmatched review record cannot promote a resource:

```python
def review_manifest_for(resource: dict[str, object], canonical_sha256: str | None = None) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "source_sha256": SOURCE_SHA256,
        "resources": [{
            "id": resource["id"],
            "resource_kind": "material",
            "canonical_sha256": canonical_sha256 or canonical_resource_sha256(resource),
            "validation_status": "syntax_unit_reviewed",
            "reviewed_on": "2026-08-05",
            "review_method": "automated_syntax_unit_dependency_audit",
            "evidence": ["source_identity", "source_spans", "si_conversion", "typed_fields", "dependency_closure"],
        }],
    }

class Phase18ReviewContractTests(unittest.TestCase):
    def test_canonical_hash_excludes_only_review_and_runtime_fields(self) -> None:
        base = {
            "id": "2k_mid12_rebar_d12",
            "density_kg_per_m3": 7850.0,
            "validation_status": "source_reference",
            "requires_project_review": True,
            "_path": "local-only.json",
        }
        changed_metadata = {**base, "validation_status": "syntax_unit_reviewed", "_path": "other.json"}
        changed_value = {**base, "density_kg_per_m3": 7800.0}
        self.assertEqual(canonical_resource_sha256(base), canonical_resource_sha256(changed_metadata))
        self.assertNotEqual(canonical_resource_sha256(base), canonical_resource_sha256(changed_value))

    def test_hash_mismatch_cannot_promote_source_reference(self) -> None:
        resource = {"id": "2k_mid12_rebar_d12", "validation_status": "source_reference", "requires_project_review": True}
        manifest = review_manifest_for(resource, canonical_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "canonical SHA-256"):
            apply_effective_review(resource, manifest)
```

- [ ] **Step 2: Run the review-contract tests and verify RED**

Run: `python -m unittest tests.test_phase18b_resource_review.Phase18ReviewContractTests -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'lsprepost_mcp.phase18_resource_review'`.

- [ ] **Step 3: Add exact resource paths**

Add to `lsprepost_mcp/config.py`:

```python
STRUCTURAL_RESOURCES_DIR = MODEL_LIBRARY_DIR / "structural" / "phase18" / "2k"
PHASE18_REVIEW_MANIFEST = ROOT / "resources" / "reviews" / "phase18" / "2k_syntax_unit_review.json"
```

- [ ] **Step 4: Implement canonical hashing and review verification**

Implement canonical JSON with sorted keys and compact separators. Exclude only `_path`, `_resource_dir`, `validation_status`, `effective_validation_status`, and `review`; preserve `requires_project_review`, provenance, source cards and all physical values.

```python
_REVIEW_METADATA_KEYS = {
    "_path", "_resource_dir", "validation_status", "effective_validation_status", "review"
}

def canonical_resource_sha256(resource: Mapping[str, object]) -> str:
    payload = {key: value for key, value in resource.items() if key not in _REVIEW_METADATA_KEYS}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

def apply_effective_review(resource: Mapping[str, object], manifest: Mapping[str, object]) -> JSONDict:
    resource_id = str(resource.get("id", ""))
    record = next((row for row in manifest["resources"] if row["id"] == resource_id), None)
    if record is None:
        return {**resource, "effective_validation_status": "source_reference"}
    actual = canonical_resource_sha256(resource)
    if actual != record["canonical_sha256"]:
        raise ValueError(f"resource '{resource_id}' canonical SHA-256 does not match review evidence")
    if record["validation_status"] != "syntax_unit_reviewed":
        raise ValueError("Phase 18B review records must use syntax_unit_reviewed")
    return {
        **resource,
        "effective_validation_status": "syntax_unit_reviewed",
        "review": dict(record),
        "requires_project_review": True,
    }
```

Validate manifest schema version `0.1.0`, exact source SHA, unique IDs, 64-character lowercase hex hashes, review date, review method `automated_syntax_unit_dependency_audit`, and a non-empty evidence list.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `python -m unittest tests.test_phase18b_resource_review.Phase18ReviewContractTests -v`

Expected: all `Phase18ReviewContractTests` pass.

- [ ] **Step 6: Commit the review contract**

```powershell
git add -- lsprepost_mcp/config.py lsprepost_mcp/phase18_resource_review.py tests/test_phase18b_resource_review.py
git diff --cached --check
git commit -m "feat: add hash-bound phase18 resource review contract"
```

---

### Task 2: Typed Material Resource Audit

**Files:**
- Modify: `lsprepost_mcp/materials.py`
- Modify: `tests/test_phase18b_resource_review.py`
- Modify: `tests/test_materials.py`

**Interfaces:**
- Consumes: six `2.k` source material mappings and the review contract from Task 1.
- Produces: `validate_material_resource(material) -> JSONDict` and `get_reviewed_material_resource(material_id, allowed_types, *, review_manifest=None) -> JSONDict`.

- [ ] **Step 1: Write failing tests for all four typed material families**

```python
class Phase18MaterialAuditTests(unittest.TestCase):
    def test_six_material_bundles_pass_typed_validation(self) -> None:
        for material_id in MATERIAL_IDS:
            report = validate_material_resource(get_material(material_id))
            self.assertTrue(report["valid"])
            self.assertEqual(material_id, report["resource_id"])
            self.assertEqual(SOURCE_SHA256, report["source_sha256"])

    def test_concrete_requires_curve_and_erosion_dependency(self) -> None:
        concrete = get_material("2k_mid5_concrete_kc")
        broken = copy.deepcopy(concrete)
        del broken["dependencies"]["rate_curve"]
        with self.assertRaisesRegex(ValueError, "rate_curve"):
            validate_material_resource(broken)

    def test_reviewed_accessor_rejects_unreviewed_or_wrong_role(self) -> None:
        with self.assertRaisesRegex(ValueError, "syntax_unit_reviewed"):
            get_reviewed_material_resource("2k_mid5_concrete_kc", {"concrete_damage_rel3"})
        air = get_material("2k_mid2_air_eos2")
        with self.assertRaisesRegex(ValueError, "allowed material type"):
            get_reviewed_material_resource(
                "2k_mid2_air_eos2",
                {"concrete_damage_rel3"},
                review_manifest=review_manifest_for(air),
            )
```

Use the `review_manifest_for()` test helper in the reviewed-accessor test until Task 4 installs the formal manifest.

- [ ] **Step 2: Run the material-audit tests and verify RED**

Run: `python -m unittest tests.test_phase18b_resource_review.Phase18MaterialAuditTests -v`

Expected: FAIL because `validate_material_resource` and `get_reviewed_material_resource` do not exist.

- [ ] **Step 3: Implement family-specific validators**

Keep existing `validate_material()` unchanged for generic elastic and piecewise-linear inputs. Add a separate dispatch:

```python
_RESOURCE_VALIDATORS = {
    "concrete_damage_rel3": _validate_concrete_damage_rel3,
    "plastic_kinematic": _validate_plastic_kinematic,
    "mat_null_eos_linear_polynomial": _validate_air_eos,
    "high_explosive_burn_eos_jwl": _validate_tnt_jwl,
}

def validate_material_resource(material: Mapping[str, object]) -> JSONDict:
    material_type = str(material.get("type", ""))
    try:
        validate_family = _RESOURCE_VALIDATORS[material_type]
    except KeyError as exc:
        raise ValueError(f"unsupported material resource type '{material_type}'") from exc
    validate_common_resource_fields(material)
    validate_family(material)
    return {
        "valid": True,
        "resource_id": str(material["id"]),
        "material_type": material_type,
        "source_sha256": str(material["provenance"]["source_sha256"]),
        "canonical_sha256": canonical_resource_sha256(material),
    }
```

Enforce exact dependency rules:

- concrete: density `2400`, Curve 1 with 23 points, MID 5 erosion with `mxeps=0.15`, documented `ft` sentinel and solver conversion factors;
- rebar: positive density/E/Poisson/yield/tangent modulus, positive diameters, positive `src_per_s`/`srp`, and source MAT plus matching beam-section cards;
- air: positive density, EOS ID 2, finite C0–C6/E0 fields and MAT/EOS source cards;
- TNT: positive density/detonation velocity/CJ pressure/JWL A/B/R1/R2/E0, EOS ID 1 and source MAT/EOS/detonation cards.

- [ ] **Step 4: Implement reviewed material access without weakening generic resolution**

```python
def get_reviewed_material_resource(
    material_id: str,
    allowed_types: set[str],
    *,
    review_manifest: Mapping[str, object] | None = None,
) -> JSONDict:
    resource = get_material(material_id)
    report = validate_material_resource(resource)
    evidence = review_manifest if review_manifest is not None else load_phase18_review_manifest()
    reviewed = apply_effective_review(resource, evidence)
    if reviewed["effective_validation_status"] != "syntax_unit_reviewed":
        raise ValueError(f"material resource '{material_id}' is not syntax_unit_reviewed")
    if report["material_type"] not in allowed_types:
        raise ValueError(f"material resource '{material_id}' is not an allowed material type")
    return reviewed
```

Do not route complex Phase 18 resources through `material_from_library()`; Phase 18C will call the explicit reviewed accessor.

- [ ] **Step 5: Run material and compatibility tests**

Run: `python -m unittest tests.test_phase18b_resource_review tests.test_materials tests.test_phase18_resource_library -v`

Expected: new typed tests pass and existing generic material tests remain green.

- [ ] **Step 6: Commit typed material validation**

```powershell
git add -- lsprepost_mcp/materials.py tests/test_phase18b_resource_review.py tests/test_materials.py
git diff --cached --check
git commit -m "feat: validate phase18 typed material resources"
```

---

### Task 3: Deterministic Structural Resource Catalogs

**Files:**
- Create: `lsprepost_mcp/structural_resources.py`
- Modify: `lsprepost_mcp/keyword_decomposition.py`
- Create: `tests/test_phase18b_structural_resources.py`

**Interfaces:**
- Consumes: `decompose_keyword_deck()` report with source spans and raw blocks.
- Produces: `_2k_structural_assets(report) -> list[JSONDict]`, `load_structural_resources()`, `list_structural_resources()`, `get_structural_resource(resource_id)`, and `validate_structural_resource(resource_id)`.

- [ ] **Step 1: Write failing extraction and closure tests**

```python
STRUCTURAL_RESOURCE_IDS = {
    "2k_sections_used",
    "2k_curve1_kc_rate",
    "2k_part_role_map",
    "2k_sets_used",
    "2k_embedded_couplings",
}

class StructuralCatalogWriterTests(unittest.TestCase):
    def test_writer_emits_five_source_reference_catalogs(self) -> None:
        assets = _2k_structural_assets(self.report)
        self.assertEqual(STRUCTURAL_RESOURCE_IDS, {row["id"] for row in assets})
        self.assertTrue(all(row["validation_status"] == "source_reference" for row in assets))
        self.assertTrue(all(row["requires_project_review"] for row in assets))

    def test_used_catalog_counts_and_si_dimensions_are_exact(self) -> None:
        by_id = {row["id"]: row for row in _2k_structural_assets(self.report)}
        self.assertEqual(6, len(by_id["2k_sections_used"]["items"]))
        self.assertEqual(0.008, by_id["2k_sections_used"]["items"][0]["diameter_m"])
        self.assertEqual(23, len(by_id["2k_curve1_kc_rate"]["points"]))
        self.assertEqual(12, len(by_id["2k_part_role_map"]["items"]))
        self.assertEqual(7, len(by_id["2k_sets_used"]["items"]))
        self.assertEqual(5, len(by_id["2k_embedded_couplings"]["items"]))
```

- [ ] **Step 2: Run structural tests and verify RED**

Run: `python -m unittest tests.test_phase18b_structural_resources.StructuralCatalogWriterTests -v`

Expected: FAIL because `_2k_structural_assets` and `structural_resources` do not exist.

- [ ] **Step 3: Extend source parsing only where catalog content is missing**

Enhance Curve and Set parsing to preserve normalized point/member values plus raw source spans. Preserve current summary fields for compatibility:

```python
curves.append({
    "id": card_id,
    "keyword": keyword,
    **span,
    "points": [[_float(row[1][0]), _float(row[1][1])] for row in rows[1:] if len(row[1]) >= 2],
})

sets.append({
    "id": card_id,
    "keyword": keyword,
    **span,
    "member_record_count": max(0, len(rows) - 1),
    "member_rows": [[_integer(value) for value in fields if value] for _, fields in rows[1:]],
})
```

The source fixture and full-source tests must lock exact counts so formatting lines cannot become members.

- [ ] **Step 4: Implement five deterministic source-reference assets**

Each asset contains `schema_version="0.1.0"`, source SHA, SI unit system, source spans, `validation_status="source_reference"`, `requires_project_review=true`, and type-specific items. Normalize beam diameters to metres while retaining `source_diameter_mm`.

Resolve each Part MID to a material resource ID using:

```python
_MID_TO_RESOURCE = {
    2: "2k_mid2_air_eos2",
    3: "2k_mid3_tnt_eos1",
    5: "2k_mid5_concrete_kc",
    8: "2k_mid8_rebar_d8_d18",
    12: "2k_mid12_rebar_d12",
    14: "2k_mid14_rebar_d20",
}
```

Mark coupling endpoints as `set` when type is `0` and `part` when type is `1`; retain original `sstyp/mstyp` values.

- [ ] **Step 5: Implement structural library validation**

`validate_structural_resource()` validates common provenance and dispatches by `resource_type`. Add `validate_structural_catalog_closure(resources, materials)` that proves:

- all 12 Part bindings reference one of six sections and one of six material resources;
- Curve 1 exists and matches the concrete dependency;
- every coupling endpoint resolves to a published Set or Part according to endpoint type;
- no audit-only ID appears;
- all source spans are positive and ordered.

- [ ] **Step 6: Run structural and decomposition tests**

Run: `python -m unittest tests.test_phase18b_structural_resources tests.test_keyword_decomposition tests.test_phase18_resource_library -v`

Expected: all tests pass with exact five-resource and dependency-closure assertions.

- [ ] **Step 7: Commit structural catalogs**

```powershell
git add -- lsprepost_mcp/keyword_decomposition.py lsprepost_mcp/structural_resources.py tests/test_phase18b_structural_resources.py
git diff --cached --check
git commit -m "feat: extract phase18 structural resource catalogs"
```

---

### Task 4: Review Manifest, Formal Resources and Reproducible Promotion

**Files:**
- Create: `scripts/review_phase18_resources.py`
- Modify: `scripts/import_2k_resources.py`
- Modify: `lsprepost_mcp/keyword_decomposition.py`
- Create: `resources/reviews/phase18/2k_syntax_unit_review.json`
- Create: `resources/model_library/structural/phase18/2k/2k_sections_used.json`
- Create: `resources/model_library/structural/phase18/2k/2k_curve1_kc_rate.json`
- Create: `resources/model_library/structural/phase18/2k/2k_part_role_map.json`
- Create: `resources/model_library/structural/phase18/2k/2k_sets_used.json`
- Create: `resources/model_library/structural/phase18/2k/2k_embedded_couplings.json`
- Move: `resources/materials/2k_mid2_air_eos2.json` to `resources/materials/phase18/2k/2k_mid2_air_eos2.json`
- Move: `resources/materials/2k_mid3_tnt_eos1.json` to `resources/materials/phase18/2k/2k_mid3_tnt_eos1.json`
- Move: `resources/materials/2k_mid5_concrete_kc.json` to `resources/materials/phase18/2k/2k_mid5_concrete_kc.json`
- Move: `resources/materials/2k_mid8_rebar_d8_d18.json` to `resources/materials/phase18/2k/2k_mid8_rebar_d8_d18.json`
- Move: `resources/materials/2k_mid12_rebar_d12.json` to `resources/materials/phase18/2k/2k_mid12_rebar_d12.json`
- Move: `resources/materials/2k_mid14_rebar_d20.json` to `resources/materials/phase18/2k/2k_mid14_rebar_d20.json`
- Modify: `tests/test_phase18_resource_library.py`
- Modify: `tests/test_phase18b_resource_review.py`
- Modify: `tests/test_phase18b_structural_resources.py`

**Interfaces:**
- Consumes: exact source deck, generated source-reference assets and pure validators.
- Produces: 11 hash-bound review records and formal effective `syntax_unit_reviewed` resources.

- [ ] **Step 1: Write failing formal-library review tests**

```python
def test_formal_phase18_resources_are_effectively_reviewed(self) -> None:
    for material_id in MATERIAL_IDS:
        material = get_material(material_id)
        self.assertEqual("source_reference", material["validation_status"])
        self.assertEqual("syntax_unit_reviewed", material["effective_validation_status"])
        self.assertTrue(material["requires_project_review"])
        self.assertEqual(material["id"], material["review"]["id"])

    resources = list_structural_resources()
    self.assertEqual(STRUCTURAL_RESOURCE_IDS, {row["id"] for row in resources})
    self.assertTrue(all(row["effective_validation_status"] == "syntax_unit_reviewed" for row in resources))
```

- [ ] **Step 2: Run formal-library tests and verify RED**

Run: `python -m unittest tests.test_phase18_resource_library tests.test_phase18b_resource_review tests.test_phase18b_structural_resources -v`

Expected: FAIL because the formal review manifest and structural JSON files do not exist.

- [ ] **Step 3: Add structural output to the import pipeline**

Change the writer signature to:

```python
def write_decomposition_package(
    report: dict[str, object],
    output_dir: Path,
    materials_dir: Path | None = None,
    structural_dir: Path | None = None,
) -> dict[str, str]:
```

Write five assets atomically to `structural_dir or output_dir / "structural"`. Add `--structural-dir` to `scripts/import_2k_resources.py`, defaulting to `resources/model_library/structural/phase18/2k`.

- [ ] **Step 4: Implement candidate review-manifest generation and verification**

`scripts/review_phase18_resources.py` supports exactly two mutually exclusive modes:

```powershell
python scripts/review_phase18_resources.py --candidate-output workspace/imports/phase18_review_candidate.json
python scripts/review_phase18_resources.py --verify resources/reviews/phase18/2k_syntax_unit_review.json
```

Candidate mode loads exactly six material and five structural resources, runs every typed and closure validator, computes canonical hashes, and writes sorted review records. Verify mode loads the checked-in manifest and exits nonzero on missing/extra IDs, hash mismatch, validator failure or wrong source SHA.

Each review record is built from validated resource data:

```python
record = {
    "id": resource["id"],
    "resource_kind": resource_kind,
    "canonical_sha256": canonical_resource_sha256(resource),
    "validation_status": "syntax_unit_reviewed",
    "reviewed_on": "2026-08-05",
    "review_method": "automated_syntax_unit_dependency_audit",
    "evidence": ["source_identity", "source_spans", "si_conversion", "typed_fields", "dependency_closure"],
}
```

- [ ] **Step 5: Regenerate formal source-reference assets from the exact source**

Run:

```powershell
python scripts/import_2k_resources.py E:/Desktop/2.k --component-packages
```

Expected: six material files, five structural files, the complete reference and four component packages are regenerated into the canonical two-library layout without absolute source paths in published JSON. Move the five existing built-in material JSON files to `resources/materials/builtin`, the complete reference package to `resources/model_library/references/phase18/2k_complete_reference`, and the four component packages to `resources/model_library/components/phase18/2k` using exact-path moves; do not retain duplicate copies.

- [ ] **Step 6: Generate, inspect and install the review manifest**

Run candidate mode, inspect that it contains exactly 11 unique records and the exact source SHA, then add the candidate content to `resources/reviews/phase18/2k_syntax_unit_review.json` using `apply_patch`. Run verify mode and expect exit code `0`.

- [ ] **Step 7: Make list/get APIs apply verified effective status**

`get_material()` and `get_structural_resource()` keep raw `validation_status="source_reference"` and add `effective_validation_status` plus the matched `review` record. If the manifest is absent, the resource remains effectively `source_reference`; if a matching ID has the wrong hash, list/get/validate fail loudly.

- [ ] **Step 8: Run formal resource tests**

Run: `python -m unittest tests.test_phase18_resource_library tests.test_phase18b_resource_review tests.test_phase18b_structural_resources tests.test_phase18a1_component_resources -v`

Expected: all tests pass; formal resources report effective `syntax_unit_reviewed`, component resources remain `source_reference`, and `requires_project_review` remains true.

- [ ] **Step 9: Commit reviewed formal resources**

```powershell
git add -- scripts/import_2k_resources.py scripts/review_phase18_resources.py lsprepost_mcp/keyword_decomposition.py resources/materials resources/model_library resources/reviews/phase18/2k_syntax_unit_review.json tests/test_phase18_resource_library.py tests/test_phase18b_resource_review.py tests/test_phase18b_structural_resources.py
git diff --cached --check
git commit -m "feat: publish reviewed phase18 resource catalogs"
```

---

### Task 5: Public Material and Structural Resource Tools

**Files:**
- Modify: `lsprepost_mcp/tool_materials.py`
- Create: `lsprepost_mcp/tool_structural_resources.py`
- Modify: `lsprepost_mcp/tools.py`
- Modify: `tests/test_jsonrpc.py`
- Modify: `tests/test_tools.py`

**Interfaces:**
- Consumes: material and structural library functions from Tasks 2–4.
- Produces: MCP tools `validate_material_resource`, `list_structural_resources`, `get_structural_resource`, and `validate_phase18_resource_review`.

- [ ] **Step 1: Write failing tool registration and call tests**

```python
def test_phase18_review_tools_are_registered(self) -> None:
    names = {tool["name"] for tool in tool_list()["tools"]}
    self.assertTrue({
        "validate_material_resource",
        "list_structural_resources",
        "get_structural_resource",
        "validate_phase18_resource_review",
    }.issubset(names))

def test_validate_material_resource_tool_returns_effective_status(self) -> None:
    result = call_tool("validate_material_resource", {"material_id": "2k_mid5_concrete_kc"})
    self.assertTrue(result["valid"])
    self.assertEqual("syntax_unit_reviewed", result["effective_validation_status"])
    self.assertTrue(result["requires_project_review"])
```

- [ ] **Step 2: Run tool tests and verify RED**

Run: `python -m unittest tests.test_jsonrpc tests.test_tools -v`

Expected: FAIL because the four tools are not registered.

- [ ] **Step 3: Implement strict handlers**

```python
def tool_validate_material_resource(args: JSONDict) -> JSONDict:
    material_id = str(args.get("material_id", ""))
    material = get_material(material_id)
    report = validate_material_resource(material)
    return {
        **report,
        "effective_validation_status": material.get("effective_validation_status", "source_reference"),
        "requires_project_review": bool(material.get("requires_project_review", True)),
    }
```

Structural handlers return public fields only and never expose `_path`. The review-validation tool accepts no arguments and returns counts for six materials, five structural resources, 11 matching review records, the source SHA and `valid=true`.

- [ ] **Step 4: Register strict schemas**

- `validate_material_resource`: required string `material_id`, no extra properties.
- `list_structural_resources`: empty object, no extra properties.
- `get_structural_resource`: required string `resource_id`, no extra properties.
- `validate_phase18_resource_review`: empty object, no extra properties.

- [ ] **Step 5: Run protocol and compatibility tests**

Run: `python -m unittest tests.test_jsonrpc tests.test_tools tests.test_phase9_refactor tests.test_phase12_baseline -v`

Expected: all tests pass, with old tool handlers retaining identity and old baseline tools still present.

- [ ] **Step 6: Commit public tools**

```powershell
git add -- lsprepost_mcp/tool_materials.py lsprepost_mcp/tool_structural_resources.py lsprepost_mcp/tools.py tests/test_jsonrpc.py tests/test_tools.py
git diff --cached --check
git commit -m "feat: expose reviewed structural resource tools"
```

---

### Task 6: Deterministic Regeneration and Distribution Boundaries

**Files:**
- Modify: `tests/test_phase18_resource_library.py`
- Modify: `tests/test_phase18b_structural_resources.py`
- Modify: `tests/test_packaging_and_integration_boundaries.py`
- Modify: `scripts/pack.ps1` only if the current recursive resource inclusion does not already package the new directories.

**Interfaces:**
- Consumes: exact source import, formal resources and review verifier.
- Produces: deterministic byte equality, path-safety and packaged-resource guarantees.

- [ ] **Step 1: Write failing deterministic regeneration test**

Generate materials and structural catalogs twice into separate temporary directories and compare relative file names and bytes:

```python
def test_phase18b_assets_regenerate_byte_identically(self) -> None:
    first = self.write_package("first")
    second = self.write_package("second")
    self.assertEqual(relative_files(first), relative_files(second))
    for relative in relative_files(first):
        self.assertEqual((first / relative).read_bytes(), (second / relative).read_bytes())
```

Also assert published JSON does not contain `E:\\Desktop`, `C:\\Users`, `_path`, or `_resource_dir`.

- [ ] **Step 2: Run deterministic tests and verify RED where coverage is missing**

Run: `python -m unittest tests.test_phase18_resource_library tests.test_phase18b_structural_resources tests.test_packaging_and_integration_boundaries -v`

Expected: the new structural resource packaging or distribution assertions fail before integration is completed.

- [ ] **Step 3: Make output ordering and atomic writes deterministic**

Sort resources by ID, sort catalog items by source ID, serialize with `ensure_ascii=False`, `indent=2`, and one trailing newline. Write through a sibling temporary file followed by `Path.replace()` so interrupted imports do not publish partial JSON.

- [ ] **Step 4: Verify package inclusion and secret/path exclusion**

Ensure `resources/materials/**`, `resources/model_library/structural/**` and `resources/reviews/phase18/**` appear in the built distribution while `workspace/imports/**`, local absolute paths and review candidates do not.

- [ ] **Step 5: Run the related regression matrix**

Run:

```powershell
python -m unittest tests.test_phase18_resource_library tests.test_phase18a1_component_resources tests.test_phase18b_resource_review tests.test_phase18b_structural_resources tests.test_materials tests.test_keyword_decomposition tests.test_jsonrpc tests.test_tools tests.test_packaging_and_integration_boundaries -v
```

Expected: zero failures; environment-dependent skips are reported but do not hide Phase 18B tests.

- [ ] **Step 6: Commit reproducibility and packaging gates**

```powershell
git add -- tests/test_phase18_resource_library.py tests/test_phase18b_structural_resources.py tests/test_packaging_and_integration_boundaries.py scripts/pack.ps1
git diff --cached --check
git commit -m "test: gate phase18 reviewed resource distribution"
```

If `scripts/pack.ps1` requires no change, omit it from `git add`.

---

### Task 7: Phase 18B Review Report and Final Verification

**Files:**
- Create: `docs/reviews/phase18/PHASE18B_RESOURCE_REVIEW.zh-CN.md`
- Modify: `docs/ROADMAP.zh-CN.md`

**Interfaces:**
- Consumes: verification outputs and formal resource counts.
- Produces: a traceable software-side Phase 18B acceptance record and updated roadmap status.

- [ ] **Step 1: Run focused review verification**

Run:

```powershell
python scripts/review_phase18_resources.py --verify resources/reviews/phase18/2k_syntax_unit_review.json
python -m unittest tests.test_phase18b_resource_review tests.test_phase18b_structural_resources tests.test_phase18_resource_library -v
```

Expected: manifest verification exits `0`; all Phase 18B tests pass.

- [ ] **Step 2: Run compile and full Python suite**

Run:

```powershell
python -m compileall -q lsprepost_mcp scripts
python -m unittest discover -s tests -v
```

Expected: compile exits `0`; full suite has zero failures. Record the exact pass and environment-skip counts from this run.

- [ ] **Step 3: Run formatting and staged-scope checks**

Run:

```powershell
git diff --check -- lsprepost_mcp scripts tests resources docs/ROADMAP.zh-CN.md docs/reviews/phase18
git status --short
```

Expected: no whitespace errors in task files. Preserve unrelated worktree changes.

- [ ] **Step 4: Write the Phase 18B report**

The report records:

- source SHA and unit systems;
- six reviewed material IDs and four typed material families;
- five structural catalogs with counts 6 Sections, 1 Curve/23 points, 12 Parts, seven Sets and five Couplings;
- canonical hashes and review-manifest verification result;
- focused/full test commands and exact outcomes;
- unused/audit-only exclusions;
- `requires_project_review=true`, no solver run and no engineering-validation claim;
- the remaining gate before Phase 18C: user confirmation of material roles and connection/coupling defaults.

- [ ] **Step 5: Update the roadmap only after all gates pass**

Set Phase 18B to “软件侧语法、单位、依赖审核入库完成”, link the report, and keep engineering calibration explicitly open. Do not mark Phase 18C started in this commit.

- [ ] **Step 6: Commit documentation with exact scope**

```powershell
git add -- docs/reviews/phase18/PHASE18B_RESOURCE_REVIEW.zh-CN.md
git diff --cached --check
git commit -m "docs: record phase18b resource review acceptance"
```

Because `docs/ROADMAP.zh-CN.md` already contains unrelated worktree changes, stage its Phase 18B hunks only after inspecting `git diff --cached`; otherwise leave the verified roadmap update uncommitted and report that fact.

---

## Plan Self-Review Checklist

- [ ] Every requirement in Phase 18B maps to a task: two-library layout and stable IDs (Task 0), materials (Task 2), Section/Curve/Part/Set/Coupling (Task 3), audit evidence (Tasks 1/4), public library access (Task 5), deterministic publishing (Task 6), acceptance report (Task 7).
- [ ] Source extraction cannot grant reviewed status; only matching checked-in review evidence can.
- [ ] All interface names used by later tasks are introduced by earlier tasks with identical spelling.
- [ ] No complex Phase 18 material is routed through the legacy elastic-material resolver.
- [ ] Unused source cards remain excluded from production resources.
- [ ] Existing component resources remain source references and retain their current validation behavior.
- [ ] No step invokes external preprocessing or solving software.
- [ ] Every task includes RED, GREEN, regression and exact-file commit steps.
