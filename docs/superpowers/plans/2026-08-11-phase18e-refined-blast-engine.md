# Phase 18E Refined Blast Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the isolated `refined_building_blast@1` backend with three load providers, modular keyword assembly, deterministic budgets, preview data, storage, and scenario invalidation.

**Architecture:** Add a new `lsprepost_mcp/refined_blast/` domain package that consumes only public Phase 18C–D artifacts and stable neutral keyword/resource APIs. Each compiler returns an immutable fragment; a single assembler closes IDs and dependencies without importing or mutating legacy blast generators.

**Tech Stack:** Python 3.13, frozen dataclasses, JSON contracts, SHA-256 fingerprints, existing `refined_building` artifacts, existing neutral keyword/resource helpers, pytest/unittest.

## Global Constraints

- Project schema is exactly `refined_building_blast@1`.
- Supported providers are exactly `explicit_ale_fsi`, `lbe_segment`, and `imported_pressure_history`.
- Supported scenario kinds are exactly `external`, `internal`, and `semi_enclosed`.
- The new package must not import city generators, legacy blast generators, legacy editor state, or `dyna_assembly.py`.
- Building artifacts remain immutable; scenario-only changes must not alter their fingerprints.
- Unknown fields, invalid units, NaN/Inf, duplicate IDs, unsafe paths, unsupported combinations, and budget overruns fail closed.
- No real solver claim is permitted; generated packages remain `solver_ready=false`, `requires_project_review=true`, and `engineering_validated=false`.
- External program launch is not part of Phase 18E compilation.

---

### Task 1: Closed contracts and provider registry

**Files:**
- Create: `lsprepost_mcp/refined_blast/__init__.py`
- Create: `lsprepost_mcp/refined_blast/contracts.py`
- Create: `lsprepost_mcp/refined_blast/provider_registry.py`
- Create: `tests/test_phase18e_contracts.py`
- Create: `tests/test_phase18e_dependency_boundaries.py`

**Interfaces:**
- Consumes: no Phase 18 implementation code.
- Produces: `normalize_refined_blast_project(value) -> RefinedBlastProject`, `normalize_scenario_draft(value) -> ScenarioDraft`, `get_load_provider(provider_id) -> BlastLoadProvider`, `list_load_providers() -> tuple[ProviderDescriptor, ...]`.

- [ ] **Step 1: Write failing closed-schema and dependency tests**

```python
def test_project_contract_is_closed_and_versioned():
    raw = minimal_project_dict()
    assert normalize_refined_blast_project(raw).schema_version == "refined_building_blast@1"
    with pytest.raises(ValueError, match="unknown field"):
        normalize_refined_blast_project({**raw, "city_layout": []})

def test_refined_blast_has_no_legacy_imports():
    forbidden = {"city_street_blast", "blast_cases", "dyna_assembly", "web.draft_preview"}
    assert imported_module_tokens(Path("lsprepost_mcp/refined_blast")).isdisjoint(forbidden)
```

- [ ] **Step 2: Run tests to verify RED**

Run: `python -m pytest -q tests/test_phase18e_contracts.py tests/test_phase18e_dependency_boundaries.py`

Expected: collection failure because `lsprepost_mcp.refined_blast` does not exist.

- [ ] **Step 3: Implement frozen contracts and registry**

```python
@dataclass(frozen=True)
class ScenarioDraft:
    scenario_id: str
    scenario_kind: Literal["external", "internal", "semi_enclosed"]
    load_provider: Mapping[str, object]
    blast_source: Mapping[str, object]
    fluid_domain: Mapping[str, object]
    boundaries: Mapping[str, object]
    interactions: Mapping[str, object]
    solver_controls: Mapping[str, object]
    output_requests: Mapping[str, object]

class BlastLoadProvider(Protocol):
    provider_id: str
    def schema(self) -> Mapping[str, object]:
        raise NotImplementedError
    def capabilities(self) -> Mapping[str, object]:
        raise NotImplementedError
    def normalize(self, value: Mapping[str, object]) -> Mapping[str, object]:
        raise NotImplementedError
    def validate(self, value: Mapping[str, object], context: "ScenarioContext") -> tuple["Finding", ...]:
        raise NotImplementedError
```

Require exact key sets, reject bool-as-number, require finite floats, canonicalize mappings and tuples, and keep the registry descriptor-driven.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest -q tests/test_phase18e_contracts.py tests/test_phase18e_dependency_boundaries.py`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/refined_blast/__init__.py lsprepost_mcp/refined_blast/contracts.py lsprepost_mcp/refined_blast/provider_registry.py tests/test_phase18e_contracts.py tests/test_phase18e_dependency_boundaries.py
git commit -m "feat: define isolated phase18e blast contracts"
```

### Task 2: Project store, immutable snapshots, and invalidation

**Files:**
- Create: `lsprepost_mcp/refined_blast/store.py`
- Create: `tests/test_phase18e_store.py`

**Interfaces:**
- Consumes: `RefinedBlastProject`, `ScenarioDraft` from Task 1.
- Produces: `RefinedBlastStore(root: Path)`, `save_draft(project_id: str, draft: ScenarioDraft, expected_revision: int) -> StoredProject`, `load_project(project_id: str) -> StoredProject`, `commit_generated_package(project_id: str, scenario_id: str, package: RefinedBlastPackage, expected_revision: int) -> StoredArtifact`, `derive_invalidation(previous: RefinedBlastProject, current: RefinedBlastProject) -> InvalidationRecord`.

- [ ] **Step 1: Write failing revision, path, and invalidation tests**

```python
def test_scenario_only_change_preserves_building_cache(tmp_path):
    store = RefinedBlastStore(tmp_path)
    first = store.create(minimal_project())
    second = store.save_draft(first.project_id, changed_charge(first), expected_revision=1)
    assert second.invalidation.building is False
    assert second.invalidation.scenario is True
    assert second.invalidation.results is True

def test_project_id_cannot_escape_store(tmp_path):
    with pytest.raises(ValueError, match="project_id"):
        RefinedBlastStore(tmp_path).load_project("../city")
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_phase18e_store.py`

Expected: import failure for `RefinedBlastStore`.

- [ ] **Step 3: Implement atomic storage and fingerprints**

Use `workspace/refined_building_blast/<project_id>/` with `project.json`, `drafts/`, `previews/`, `generated/`, `evidence/`, and `results/`. Write a temporary sibling file, flush, then replace atomically. A stale `expected_revision` raises `DraftConflictError` and never overwrites current state.

Compute separate SHA-256 values for building, scenario input, provider, output requests, assembly, preview, and result dependencies.

- [ ] **Step 4: Run storage tests**

Run: `python -m pytest -q tests/test_phase18e_store.py`

Expected: all pass, including unchanged-building and output-only invalidation.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/refined_blast/store.py tests/test_phase18e_store.py
git commit -m "feat: persist versioned phase18e projects"
```

### Task 3: Common provider types and explicit ALE-FSI provider

**Files:**
- Create: `lsprepost_mcp/refined_blast/providers/__init__.py`
- Create: `lsprepost_mcp/refined_blast/providers/common.py`
- Create: `lsprepost_mcp/refined_blast/providers/explicit_ale_fsi.py`
- Create: `tests/test_phase18e_explicit_ale_fsi.py`

**Interfaces:**
- Consumes: public `BuildingArtifact`, surface catalog, neutral material/keyword resources.
- Produces: `ExplicitAleFsiProvider`, `ProviderEstimate`, `ProviderFragment`, `ProviderEvidence`.

- [ ] **Step 1: Write failing valid external/internal/semi-enclosed tests**

```python
@pytest.mark.parametrize("kind", ["external", "internal", "semi_enclosed"])
def test_explicit_provider_compiles_minimal_kind(kind, detailed_artifact):
    context = scenario_context(detailed_artifact, kind=kind)
    fragment = ExplicitAleFsiProvider().compile(valid_explicit_input(kind), context)
    assert fragment.provider_id == "explicit_ale_fsi"
    assert fragment.manifest["solver_ready"] is False
    assert fragment.required_ids <= context.available_ids | fragment.declared_ids
```

Add RED cases for source outside fluid, positive-volume structural overlap, invalid detonation point, insufficient domain margin, wrong FSI category, non-finite values, and element budgets enforced before allocation.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_phase18e_explicit_ale_fsi.py`

Expected: import failure for `ExplicitAleFsiProvider`.

- [ ] **Step 3: Implement normalization, estimate, compile, preview, and evidence**

Return immutable fragments only. Use the public exposed-surface catalog for FSI. Internal source containment uses real room/void topology; semi-enclosed validation includes the open passage to the external buffer domain.

```python
class ExplicitAleFsiProvider:
    provider_id = "explicit_ale_fsi"
    def estimate(self, value, context) -> ProviderEstimate:
        return estimate_ale_domain_before_coordinate_allocation(value, context)
```

- [ ] **Step 4: Run provider and Phase 18C surface regressions**

Run: `python -m pytest -q tests/test_phase18e_explicit_ale_fsi.py tests/test_phase18c_surfaces.py tests/test_phase18c_dependency_boundaries.py`

Expected: all pass; Phase 18C fingerprints remain literal-equal.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/refined_blast/providers tests/test_phase18e_explicit_ale_fsi.py
git commit -m "feat: compile explicit ale fsi blast loads"
```

### Task 4: LBE segment provider

**Files:**
- Create: `lsprepost_mcp/refined_blast/providers/lbe_segment.py`
- Create: `tests/test_phase18e_lbe_segment.py`

**Interfaces:**
- Consumes: `ScenarioContext`, classified surface catalog.
- Produces: `LbeSegmentProvider` and an immutable surface-load fragment.

- [ ] **Step 1: Write failing automatic and user-subset selection tests**

```python
def test_external_lbe_never_selects_internal_faces(external_context):
    fragment = LbeSegmentProvider().compile(valid_lbe_input(), external_context)
    assert set(fragment.manifest["surface_categories"]) == {"exterior"}

def test_user_surface_set_must_be_subset_of_candidates(external_context):
    with pytest.raises(ValueError, match="candidate"):
        LbeSegmentProvider().compile(lbe_with_internal_face(), external_context)
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_phase18e_lbe_segment.py`

Expected: import failure.

- [ ] **Step 3: Implement deterministic candidate selection**

Use direction, range, surface category, positive physical area, and explicit occlusion policy. Record why each selected face was included. Do not claim LBE is equivalent to ALE-FSI.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest -q tests/test_phase18e_lbe_segment.py tests/test_phase18c_surfaces.py`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/refined_blast/providers/lbe_segment.py tests/test_phase18e_lbe_segment.py
git commit -m "feat: add phase18e lbe surface provider"
```

### Task 5: Imported pressure-history provider

**Files:**
- Create: `lsprepost_mcp/refined_blast/providers/imported_pressure_history.py`
- Create: `tests/test_phase18e_imported_pressure_history.py`

**Interfaces:**
- Consumes: imported bytes or structured rows plus target surface context.
- Produces: `ImportedPressureHistoryProvider`, normalized curve fragment, source and normalized SHA-256 evidence.

- [ ] **Step 1: Write failing curve and mapping tests**

```python
def test_pressure_history_is_strictly_increasing(pressure_context):
    with pytest.raises(ValueError, match="strictly increasing"):
        compile_history([(0.0, 0.0), (0.1, 2.0), (0.1, 1.0)], pressure_context)

def test_source_and_normalized_hashes_are_recorded(pressure_context):
    result = compile_history([(0.0, 0.0), (0.1, 2.0)], pressure_context)
    assert len(result.evidence["source_sha256"]) == 64
    assert len(result.evidence["normalized_curve_sha256"]) == 64
```

Include NaN/Inf, duplicate time, negative scale, unknown unit, empty curve, oversized curve, unsafe path, and wrong surface-category cases.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_phase18e_imported_pressure_history.py`

Expected: import failure.

- [ ] **Step 3: Implement finite unit-aware normalization**

Support only declared SI-convertible time and pressure units. Store original source hash, normalized SI rows, interpolation rule, scale, mapping evidence, and target face IDs.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest -q tests/test_phase18e_imported_pressure_history.py`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/refined_blast/providers/imported_pressure_history.py tests/test_phase18e_imported_pressure_history.py
git commit -m "feat: import audited phase18e pressure histories"
```

### Task 6: Placement, support, source, domain, boundaries, and interactions

**Files:**
- Create: `lsprepost_mcp/refined_blast/fragments.py`
- Create: `lsprepost_mcp/refined_blast/placement.py`
- Create: `lsprepost_mcp/refined_blast/support_ground.py`
- Create: `lsprepost_mcp/refined_blast/blast_source.py`
- Create: `lsprepost_mcp/refined_blast/fluid_domain.py`
- Create: `lsprepost_mcp/refined_blast/boundaries.py`
- Create: `lsprepost_mcp/refined_blast/interactions.py`
- Create: `tests/test_phase18e_modules.py`

**Interfaces:**
- Consumes: normalized `ScenarioDraft`, immutable building artifact, provider fragment.
- Produces: `KeywordFragment` instances with declared/required IDs, estimates, manifest, and fingerprint.

- [ ] **Step 1: Write failing module-closure tests**

```python
@pytest.mark.parametrize("compiler", ALL_MODULE_COMPILERS)
def test_module_does_not_mutate_inputs(compiler, frozen_context):
    before = json_fingerprint(frozen_context)
    compiler.compile(frozen_context)
    assert json_fingerprint(frozen_context) == before

def test_internal_domain_uses_room_connectivity(internal_context):
    domain = FluidDomainCompiler().compile(internal_context)
    assert domain.manifest["included_space_ids"] == ["sales_hall"]
    assert "solid_envelope_fill" not in domain.manifest
```

Add shared-node support, invalid boundary overlap, closed/open door connectivity, semi-enclosed vent path, duplicate interaction, and unsupported multi-building cases.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_phase18e_modules.py`

Expected: imports fail for missing compilers.

- [ ] **Step 3: Implement one responsibility per compiler**

Use stable ID requests rather than final numeric IDs. Preserve building mesh exactly. Generate fluid regions from actual topology and opening state. Require support faces to be real foundation interfaces.

- [ ] **Step 4: Run focused module tests**

Run: `python -m pytest -q tests/test_phase18e_modules.py tests/test_phase18c_spatial.py tests/test_phase18c_surfaces.py`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/refined_blast/fragments.py lsprepost_mcp/refined_blast/placement.py lsprepost_mcp/refined_blast/support_ground.py lsprepost_mcp/refined_blast/blast_source.py lsprepost_mcp/refined_blast/fluid_domain.py lsprepost_mcp/refined_blast/boundaries.py lsprepost_mcp/refined_blast/interactions.py tests/test_phase18e_modules.py
git commit -m "feat: compile modular refined blast fragments"
```

### Task 7: Controls, outputs, deterministic assembler, and keyword package

**Files:**
- Create: `lsprepost_mcp/refined_blast/controls.py`
- Create: `lsprepost_mcp/refined_blast/outputs.py`
- Create: `lsprepost_mcp/refined_blast/assembler.py`
- Create: `tests/test_phase18e_assembler.py`

**Interfaces:**
- Consumes: ordered immutable fragments from Tasks 3–6.
- Produces: `RefinedBlastPackage`, `assemble_refined_blast_project(project, artifact)`, deterministic K/Include files and package manifest.

- [ ] **Step 1: Write failing ID and dependency tests**

```python
def test_assembler_is_deterministic(minimal_fragments):
    first = ProjectAssembler().assemble(minimal_fragments)
    second = ProjectAssembler().assemble(minimal_fragments)
    assert first.package_fingerprint == second.package_fingerprint
    assert first.files == second.files

def test_missing_dependency_fails_closed(minimal_fragments):
    with pytest.raises(ValueError, match="unresolved dependency"):
        ProjectAssembler().assemble(with_missing_surface_set(minimal_fragments))
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_phase18e_assembler.py`

Expected: import failure.

- [ ] **Step 3: Implement stable ID ranges and Include order**

Assign module ranges in declared module order, sort symbolic IDs within modules, close resource dependencies, and render through neutral keyword writers. Manifest exact counts must match rendered content. Controls remain `research_candidate` unless evidence says otherwise.

- [ ] **Step 4: Run assembler and keyword checks**

Run: `python -m pytest -q tests/test_phase18e_assembler.py tests/test_keyword_checks.py tests/test_keyword_snapshots.py tests/test_keyword_decomposition.py`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/refined_blast/controls.py lsprepost_mcp/refined_blast/outputs.py lsprepost_mcp/refined_blast/assembler.py tests/test_phase18e_assembler.py
git commit -m "feat: assemble deterministic refined blast packages"
```

### Task 8: Cross-module validation, preview, budgets, and ScenarioSet

**Files:**
- Create: `lsprepost_mcp/refined_blast/validation.py`
- Create: `lsprepost_mcp/refined_blast/preview.py`
- Create: `lsprepost_mcp/refined_blast/presets.py`
- Create: `lsprepost_mcp/refined_blast/service.py`
- Create: `tests/test_phase18e_validation_preview.py`
- Create: `tests/test_phase18e_scenario_set.py`

**Interfaces:**
- Consumes: project, building artifact, module estimates/fragments.
- Produces: `validate_refined_blast_project`, `build_refined_blast_preview`, `compile_scenario_set`, immutable findings and layered preview payloads.

- [ ] **Step 1: Write failing error/warning/budget and invalidation tests**

```python
def test_error_blocks_generation_but_warning_requires_confirmation(service):
    bad = service.validate(project_with_source_overlap())
    assert any(f.severity == "error" for f in bad.findings)
    with pytest.raises(ValueError, match="blocking"):
        service.generate(bad.project)

def test_scenario_set_has_independent_packages(service):
    result = service.compile_scenario_set(two_scenarios())
    assert len({p.package_fingerprint for p in result.packages}) == 2
    assert len({p.result_id for p in result.packages}) == 2
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest -q tests/test_phase18e_validation_preview.py tests/test_phase18e_scenario_set.py`

Expected: missing service functions.

- [ ] **Step 3: Implement findings, exact/upper budgets, preview layers, and service orchestration**

Preview layers must include cavities/openings, structure, reinforcement/connections, nonstructural components, exposed faces, source, fluid, boundaries, and support. Acknowledgements bind to finding content hash and revision.

- [ ] **Step 4: Run complete Phase 18E matrix**

Run:

```powershell
$phase18eTests = (Get-ChildItem tests -Filter 'test_phase18e_*.py').FullName
python -m pytest -q $phase18eTests
```

Expected: all Phase 18E tests pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/refined_blast/validation.py lsprepost_mcp/refined_blast/preview.py lsprepost_mcp/refined_blast/presets.py lsprepost_mcp/refined_blast/service.py tests/test_phase18e_validation_preview.py tests/test_phase18e_scenario_set.py
git commit -m "feat: validate and preview phase18e scenarios"
```

### Task 9: Phase 18E software acceptance report

**Files:**
- Create: `docs/reviews/phase18/PHASE18E_REFINED_BLAST_ENGINE_REPORT.zh-CN.md`
- Modify: `docs/ROADMAP.zh-CN.md` only if its existing unrelated dirty content can be scoped safely; otherwise leave the status update unstaged and document the reason.

**Interfaces:**
- Consumes: all Phase 18E code and tests.
- Produces: reproducible software acceptance evidence without engineering claims.

- [ ] **Step 1: Run fresh acceptance commands**

```powershell
$phase18eTests = (Get-ChildItem tests -Filter 'test_phase18e_*.py').FullName
python -m pytest -q $phase18eTests
python -m pytest -q tests/test_phase18c_dependency_boundaries.py tests/test_phase18d_phase18abc_compatibility.py
python -m compileall -q lsprepost_mcp/refined_blast
git diff --check
```

Expected: zero failures and exit code 0 for every command.

- [ ] **Step 2: Record exact counts, fingerprints, limits, findings, and engineering boundary**

The report must state all tested provider/scenario combinations, generated counts, deterministic rerun evidence, unresolved engineering inputs, `solver_ready=false`, and `requires_project_review=true`.

- [ ] **Step 3: Self-review the report**

Search for unsupported claims including `engineering_validated=true`, “已完成真实求解”, and placeholders. Confirm every command and fingerprint was actually observed.

- [ ] **Step 4: Commit scoped files**

```powershell
git add docs/reviews/phase18/PHASE18E_REFINED_BLAST_ENGINE_REPORT.zh-CN.md
git commit -m "docs: record phase18e software verification"
```
