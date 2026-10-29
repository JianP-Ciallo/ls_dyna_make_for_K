"""Deterministic, dependency-closed Phase 18E keyword package assembly."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from lsprepost_mcp.refined_building.artifacts import BuildingArtifact

from .blast_source import BlastSourceCompiler
from .boundaries import BoundaryCompiler
from .contracts import RefinedBlastProject
from .controls import compile_solver_controls
from .fluid_domain import FluidDomainCompiler
from .fragments import KeywordFragment, ScenarioModuleContext
from .interactions import InteractionCompiler
from .outputs import compile_output_requests
from .placement import PlacementCompiler
from .provider_registry import get_load_provider
from .providers.common import (
    FrozenMapping,
    ProviderContext,
    ProviderEstimate,
    ProviderEvidence,
    ProviderFragment,
    fingerprint_value,
    freeze_value,
    surface_geometry_from_artifact,
    thaw_value,
)
from .support_ground import SupportGroundCompiler


_MODULE_ORDER = (
    "placement",
    "support_ground",
    "blast_source",
    "fluid_domain",
    "boundaries",
    "interactions",
    "controls",
    "outputs",
)
_MODULE_INDEX = {module_id: index for index, module_id in enumerate(_MODULE_ORDER, start=2)}
_BASE_NUMERIC_ID = 10_000_000
_DEFAULT_RANGE_CAPACITY = 100_000
_MAX_NUMERIC_ID = 2_147_483_647
_RESERVED_RANGE_COUNT = 1 + len(_MODULE_ORDER)
_PROVIDER_BUDGET_KEYS = {
    "explicit_ale_fsi": frozenset(
        {"max_axis_points", "max_node_count", "max_element_count"}
    ),
    "lbe_segment": frozenset({"max_surface_count", "max_total_area_m2"}),
    "imported_pressure_history": frozenset(
        {"max_input_bytes", "max_row_count", "max_target_surface_count"}
    ),
    "solver_complete_ale_fsi": frozenset(),
}


@dataclass(frozen=True, slots=True)
class RefinedBlastPackage:
    """Immutable package bytes plus their exact audited manifest."""

    files: Mapping[str, bytes]
    manifest: FrozenMapping
    symbol_to_numeric_id: Mapping[str, int]
    building_artifact_fingerprint: str
    package_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        copied_files: dict[str, bytes] = {}
        for path, content in self.files.items():
            _safe_path(path, "package file path")
            if not isinstance(content, bytes):
                raise ValueError("package file content must be bytes")
            copied_files[path] = bytes(content)
        copied_ids: dict[str, int] = {}
        for symbol, numeric_id in self.symbol_to_numeric_id.items():
            _safe_token(symbol, "package symbol")
            if isinstance(numeric_id, bool) or not isinstance(numeric_id, int) or numeric_id <= 0:
                raise ValueError("package numeric IDs must be positive integers")
            copied_ids[symbol] = numeric_id
        if len(copied_ids.values()) != len(set(copied_ids.values())):
            raise ValueError("package numeric IDs must be globally unique")
        frozen_manifest = freeze_value(self.manifest, "package.manifest")
        assert isinstance(frozen_manifest, Mapping)
        object.__setattr__(self, "files", MappingProxyType(copied_files))
        object.__setattr__(self, "manifest", frozen_manifest)
        object.__setattr__(self, "symbol_to_numeric_id", MappingProxyType(copied_ids))
        object.__setattr__(
            self,
            "package_fingerprint",
            fingerprint_value(
                {
                    "files": [
                        {
                            "path": path,
                            "sha256": hashlib.sha256(content).hexdigest(),
                        }
                        for path, content in copied_files.items()
                    ],
                    "manifest": frozen_manifest,
                    "symbol_to_numeric_id": copied_ids,
                    "building_artifact_fingerprint": self.building_artifact_fingerprint,
                }
            ),
        )


class ProjectAssembler:
    """Close symbolic dependencies, allocate IDs, then render immutable bytes."""

    def __init__(
        self,
        *,
        range_capacity: int = _DEFAULT_RANGE_CAPACITY,
        external_ids: frozenset[str] = frozenset(),
    ) -> None:
        if isinstance(range_capacity, bool) or not isinstance(range_capacity, int) or range_capacity <= 0:
            raise ValueError("range_capacity must be a positive integer")
        self._range_capacity = range_capacity
        self._external_ids = frozenset(
            _safe_token(value, "external id") for value in external_ids
        )

    def assemble(
        self,
        fragments: Sequence[KeywordFragment],
        *,
        artifact: BuildingArtifact | None = None,
        provider_fragment: ProviderFragment | None = None,
        provider_estimate: ProviderEstimate | None = None,
        provider_input: Mapping[str, object] | None = None,
        scenario_kind: str | None = None,
        project_fingerprint: str = "",
    ) -> RefinedBlastPackage:
        ordered_fragments = tuple(fragments)
        self._validate_fragments(ordered_fragments)
        if artifact is not None and not isinstance(artifact, BuildingArtifact):
            raise TypeError("artifact must be a BuildingArtifact")
        if provider_estimate is not None:
            _validate_provider_estimate(provider_estimate)
            if provider_fragment is None:
                raise ValueError("provider estimate requires a provider fragment")
            if provider_estimate.provider_id != provider_fragment.provider_id:
                raise ValueError("provider estimate identity does not match provider fragment")
            if provider_estimate.node_count != len(provider_fragment.node_ids) or provider_estimate.element_count != len(provider_fragment.element_ids):
                raise ValueError("provider estimate and fragment count consistency check failed")
        if provider_fragment is not None:
            _validate_provider_fragment(
                provider_fragment, artifact=artifact, estimate=provider_estimate
            )
            _validate_canonical_provider_bundle(
                provider_fragment,
                provider_estimate,
                artifact,
                provider_input=provider_input,
                scenario_kind=scenario_kind,
            )

        external_ids = set(self._external_ids)
        if artifact is not None:
            external_ids.update(_artifact_external_ids(artifact))
        declarations, owners = _declaration_owners(ordered_fragments, provider_fragment)
        external_collisions = declarations & external_ids
        if external_collisions:
            raise ValueError(
                "declaration collides with external namespace: "
                f"{sorted(external_collisions)[0]!r}"
            )
        unresolved = _all_requirements(ordered_fragments, provider_fragment) - declarations - external_ids
        if unresolved:
            raise ValueError(f"unresolved dependency: {sorted(unresolved)[0]!r}")
        _validate_dependency_graph(ordered_fragments, provider_fragment, owners)
        _validate_typed_graph(ordered_fragments)
        occupied_numeric_ids = _building_numeric_ids(artifact) if artifact is not None else set()
        symbol_map, reserved_ranges = self._allocate_ids(
            ordered_fragments, provider_fragment, occupied_numeric_ids
        )
        render_ids = dict(_artifact_render_ids(artifact)) if artifact is not None else {}
        render_ids.update(symbol_map)

        includes: list[tuple[str, bytes]] = []
        if artifact is not None:
            includes.append(("01_building.k", _render_building(artifact)))
        if provider_fragment is not None:
            includes.append(("02_provider.k", _render_provider(provider_fragment, render_ids)))
        for fragment in sorted(ordered_fragments, key=_fragment_order_key):
            index = _MODULE_INDEX[fragment.module_id]
            includes.append(
                (
                    f"{index * 10:02d}_{fragment.module_id}.k",
                    _render_fragment(fragment, render_ids),
                )
            )
        include_order = tuple(path for path, _ in includes)
        main_bytes = _render_main(include_order)
        files = {"main.k": main_bytes, **dict(includes)}
        file_manifest = tuple(_file_manifest(path, content) for path, content in files.items())
        rendered_counts = {
            "building_nodes": len(artifact.mesh.nodes) if artifact is not None else 0,
            "building_elements": (
                len(artifact.mesh.solids) + len(artifact.mesh.shells) + len(artifact.mesh.beams)
                if artifact is not None
                else 0
            ),
            "provider_nodes": len(provider_fragment.node_ids) if provider_fragment is not None else 0,
            "provider_elements": len(provider_fragment.element_ids) if provider_fragment is not None else 0,
            "provider_fsi_faces": len(provider_fragment.fsi_face_ids)
            if provider_fragment is not None
            else 0,
            "module_new_nodes": sum(
                int(fragment.estimates["new_nodes"]) for fragment in ordered_fragments
            ),
            "module_new_elements": sum(
                int(fragment.estimates["new_elements"]) for fragment in ordered_fragments
            ),
            "symbolic_ids": len(symbol_map),
        }
        manifest = {
            "schema_version": "refined_blast.keyword_package@1",
            "unit_system": "SI_m_s_kg_N_Pa",
            "project_fingerprint": project_fingerprint,
            "building_artifact_fingerprint": artifact.fingerprint if artifact is not None else "",
            "provider_fingerprint": provider_fragment.fingerprint if provider_fragment is not None else "",
            "fragment_fingerprints": tuple(
                (fragment.module_id, fragment.fingerprint)
                for fragment in sorted(ordered_fragments, key=_fragment_order_key)
            ),
            "include_order": include_order,
            "files": file_manifest,
            "rendered_counts": rendered_counts,
            "dependency_closure": {
                "closed": True,
                "declared_id_count": len(declarations),
                "external_id_count": len(external_ids),
            },
            "id_allocation": {
                "range_capacity": self._range_capacity,
                "module_order": ("provider", *_MODULE_ORDER),
                "symbol_count": len(symbol_map),
                "reserved_ranges": reserved_ranges,
            },
            "research_candidate": True,
            "solver_ready": False,
            "requires_project_review": True,
            "engineering_validated": False,
            "external_program_started": False,
        }
        return RefinedBlastPackage(
            files=files,
            manifest=manifest,
            symbol_to_numeric_id=symbol_map,
            building_artifact_fingerprint=artifact.fingerprint if artifact is not None else "",
        )

    def _validate_fragments(self, fragments: tuple[KeywordFragment, ...]) -> None:
        module_ids: set[str] = set()
        for fragment in fragments:
            if not isinstance(fragment, KeywordFragment):
                raise TypeError("assembler accepts only KeywordFragment instances")
            module_id = _safe_token(fragment.module_id, "fragment.module_id")
            if module_id != fragment.module_id:
                raise ValueError("fragment.module_id must be trimmed")
            if module_id not in _MODULE_INDEX:
                raise ValueError(f"unsupported fragment module_id: {module_id!r}")
            if module_id in module_ids:
                raise ValueError(f"duplicate fragment module_id: {module_id!r}")
            module_ids.add(module_id)
            _validate_keyword_fragment(fragment)

    def _allocate_ids(
        self,
        fragments: tuple[KeywordFragment, ...],
        provider_fragment: ProviderFragment | None,
        occupied_numeric_ids: set[int],
    ) -> tuple[Mapping[str, int], tuple[Mapping[str, object], ...]]:
        groups: list[tuple[int, tuple[str, ...]]] = []
        if provider_fragment is not None:
            groups.append((1, tuple(sorted(provider_fragment.declared_ids))))
        for fragment in sorted(fragments, key=_fragment_order_key):
            groups.append((_MODULE_INDEX[fragment.module_id], tuple(sorted(fragment.declared_ids))))
        range_base = _choose_range_base(occupied_numeric_ids, self._range_capacity)
        result: dict[str, int] = {}
        for module_index, symbols in groups:
            if len(symbols) > self._range_capacity:
                raise ValueError(
                    f"module ID range capacity exceeded for index {module_index}: "
                    f"{len(symbols)} > {self._range_capacity}"
                )
            start = range_base + module_index * self._range_capacity
            for offset, symbol in enumerate(symbols, start=1):
                result[symbol] = start + offset
        labels = ("provider", *_MODULE_ORDER)
        reserved_ranges = tuple(
            MappingProxyType(
                {
                    "module_id": label,
                    "start": range_base + index * self._range_capacity + 1,
                    "end": range_base + (index + 1) * self._range_capacity,
                    "capacity": self._range_capacity,
                }
            )
            for index, label in enumerate(labels, start=1)
        )
        return MappingProxyType(result), reserved_ranges


def assemble_refined_blast_project(
    project: RefinedBlastProject, artifact: BuildingArtifact
) -> RefinedBlastPackage:
    """Compile one persisted scenario without touching legacy or external programs."""

    if not isinstance(project, RefinedBlastProject):
        raise TypeError("project must be a normalized RefinedBlastProject")
    if not isinstance(artifact, BuildingArtifact):
        raise TypeError("artifact must be a BuildingArtifact")
    if project.building_artifact_fingerprint != artifact.fingerprint:
        raise ValueError("project building artifact fingerprint does not match artifact")
    if len(project.scenario_set) != 1:
        raise ValueError("assemble_refined_blast_project requires exactly one scenario")
    draft = project.scenario_set[0]
    provider = get_load_provider(str(draft.load_provider["provider_id"]))
    provider_input = draft.load_provider["provider_input"]
    assert isinstance(provider_input, Mapping)
    resource_ids = _declared_provider_resources(provider_input)
    provider_context = ProviderContext.from_artifact(
        artifact,
        scenario_kind=draft.scenario_kind,
        available_ids=frozenset(resource_ids),
    )
    estimate_method = getattr(provider, "estimate", None)
    provider_estimate = (
        estimate_method(provider_input, provider_context) if callable(estimate_method) else None
    )
    compile_method = getattr(provider, "compile", None)
    if not callable(compile_method):
        raise ValueError(f"provider {provider.provider_id!r} cannot compile")
    provider_fragment = compile_method(provider_input, provider_context)
    if not isinstance(provider_fragment, ProviderFragment):
        raise ValueError("provider compile result must be a ProviderFragment")

    context = ScenarioModuleContext.from_draft(draft, provider_context, provider_fragment)
    compilers = (
        (draft.building_placement, PlacementCompiler()),
        (draft.support_and_ground, SupportGroundCompiler()),
        (draft.blast_source, BlastSourceCompiler()),
        (draft.fluid_domain, FluidDomainCompiler()),
        (draft.boundaries, BoundaryCompiler()),
        (draft.interactions, InteractionCompiler()),
    )
    fragments: list[KeywordFragment] = []
    for raw, compiler in compilers:
        if raw:
            fragment = compiler.compile(context)
            fragments.append(fragment)
            context = context.with_prior_fragments(fragment)
    fragments.extend(
        (
            compile_solver_controls(draft.solver_controls, draft.scenario_id),
            compile_output_requests(draft.output_requests, draft.scenario_id),
        )
    )
    project_fingerprint = fingerprint_value(
        {
            "project_id": project.project_id,
            "scenario": {
                "scenario_id": draft.scenario_id,
                "scenario_kind": draft.scenario_kind,
                "building_placement": draft.building_placement,
                "support_and_ground": draft.support_and_ground,
                "load_provider": draft.load_provider,
                "blast_source": draft.blast_source,
                "fluid_domain": draft.fluid_domain,
                "boundaries": draft.boundaries,
                "interactions": draft.interactions,
                "solver_controls": draft.solver_controls,
                "output_requests": draft.output_requests,
                "resource_versions": draft.resource_versions,
                "acknowledged_warning_ids": draft.acknowledged_warning_ids,
            },
            "provider_fragment": provider_fragment.fingerprint,
        }
    )
    return ProjectAssembler(external_ids=provider_context.available_ids).assemble(
        tuple(fragments),
        artifact=artifact,
        provider_fragment=provider_fragment,
        provider_estimate=provider_estimate,
        provider_input=provider_input,
        scenario_kind=draft.scenario_kind,
        project_fingerprint=project_fingerprint,
    )


def _validate_provider_estimate(estimate: ProviderEstimate) -> None:
    provider_id = _safe_token(estimate.provider_id, "provider estimate provider_id")
    if provider_id != estimate.provider_id:
        raise ValueError("provider estimate provider_id must be trimmed")
    counts = estimate.axis_point_counts
    if len(counts) != 3 or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts
    ):
        raise ValueError("provider estimate axis counts must be three non-negative integers")
    expected_nodes, expected_elements = _structured_counts(counts)
    if estimate.node_count != expected_nodes or estimate.element_count != expected_elements:
        raise ValueError("provider estimate count consistency check failed")
    if estimate.budget_checked_before_allocation is not True:
        raise ValueError("provider estimate must be budget-checked before allocation")
    expected_keys = _PROVIDER_BUDGET_KEYS.get(estimate.provider_id)
    if expected_keys is not None and set(estimate.budget_limits) != expected_keys:
        raise ValueError(
            f"provider estimate has unknown or missing budget key for {estimate.provider_id}"
        )
    for key, value in estimate.budget_limits.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
            raise ValueError(f"provider estimate budget {key!r} must be finite and positive")
    rebuilt = ProviderEstimate(
        provider_id=estimate.provider_id,
        axis_point_counts=tuple(estimate.axis_point_counts),
        node_count=estimate.node_count,
        element_count=estimate.element_count,
        budget_limits=estimate.budget_limits,
        budget_checked_before_allocation=estimate.budget_checked_before_allocation,
    )
    if rebuilt.fingerprint != estimate.fingerprint:
        raise ValueError("provider estimate fingerprint mismatch")


def _validate_canonical_provider_bundle(
    fragment: ProviderFragment,
    estimate: ProviderEstimate | None,
    artifact: BuildingArtifact | None,
    *,
    provider_input: Mapping[str, object] | None,
    scenario_kind: str | None,
) -> None:
    """Recompile known providers from persisted authority and compare all fields."""

    if fragment.provider_id not in _PROVIDER_BUDGET_KEYS:
        return
    if artifact is None or estimate is None:
        raise ValueError("canonical provider validation requires artifact and estimate")
    if provider_input is None:
        raise ValueError("canonical provider validation requires persisted provider_input")
    canonical_scenario_kind = _safe_token(
        scenario_kind, "canonical provider scenario_kind"
    )
    provider = get_load_provider(fragment.provider_id)
    normalize_method = getattr(provider, "normalize", None)
    estimate_method = getattr(provider, "estimate", None)
    compile_method = getattr(provider, "compile", None)
    if not all(callable(method) for method in (normalize_method, estimate_method, compile_method)):
        raise ValueError("canonical provider does not expose normalize/estimate/compile")
    normalized = normalize_method(provider_input)
    if fingerprint_value(normalized) != fingerprint_value(fragment.normalized_input):
        raise ValueError("canonical provider normalized input mismatch")
    context = ProviderContext.from_artifact(
        artifact,
        scenario_kind=canonical_scenario_kind,
        available_ids=frozenset(_declared_provider_resources(normalized)),
    )
    canonical_estimate = estimate_method(normalized, context)
    canonical_fragment = compile_method(normalized, context)
    if _provider_estimate_semantics(estimate) != _provider_estimate_semantics(
        canonical_estimate
    ):
        raise ValueError("canonical provider estimate mismatch")
    if _provider_fragment_semantics(fragment) != _provider_fragment_semantics(
        canonical_fragment
    ):
        raise ValueError("canonical provider fragment mismatch")


def _provider_estimate_semantics(estimate: ProviderEstimate) -> object:
    return thaw_value(estimate.to_manifest())


def _provider_fragment_semantics(fragment: ProviderFragment) -> object:
    return thaw_value(
        {
            "provider_id": fragment.provider_id,
            "normalized_input": fragment.normalized_input,
            "axes_m": fragment.axes_m,
            "node_ids": fragment.node_ids,
            "element_ids": fragment.element_ids,
            "fsi_face_ids": fragment.fsi_face_ids,
            "required_ids": tuple(sorted(fragment.required_ids)),
            "declared_ids": tuple(sorted(fragment.declared_ids)),
            "evidence": tuple(
                {
                    "evidence_id": row.evidence_id,
                    "evidence_kind": row.evidence_kind,
                    "source_ids": row.source_ids,
                    "claims": row.claims,
                    "fingerprint": row.fingerprint,
                }
                for row in fragment.evidence
            ),
            "manifest": fragment.manifest,
            "fingerprint": fragment.fingerprint,
        }
    )


def _validate_provider_fragment(
    fragment: ProviderFragment,
    *,
    artifact: BuildingArtifact | None,
    estimate: ProviderEstimate | None,
) -> None:
    provider_id = _safe_token(fragment.provider_id, "provider_fragment.provider_id")
    if provider_id != fragment.provider_id:
        raise ValueError("provider_fragment.provider_id must be trimmed")
    if len(fragment.axes_m) != 3:
        raise ValueError("provider fragment must contain exactly three axes")
    axis_counts: list[int] = []
    for axis_index, axis in enumerate(fragment.axes_m):
        values = tuple(_finite_number(value, f"provider axis {axis_index}") for value in axis)
        if values and len(values) < 2:
            raise ValueError("provider non-empty axes must contain at least two points")
        if any(second <= first for first, second in zip(values, values[1:])):
            raise ValueError("provider axes must be strictly increasing")
        axis_counts.append(len(values))
    if any(axis_counts) and not all(axis_counts):
        raise ValueError("provider axes must be all empty or all non-empty")
    node_ids = _unique_trimmed_tokens(fragment.node_ids, "provider node")
    element_ids = _unique_trimmed_tokens(fragment.element_ids, "provider element")
    _unique_trimmed_tokens(fragment.fsi_face_ids, "provider FSI face")
    expected_nodes, expected_elements = _structured_counts(tuple(axis_counts))
    if len(node_ids) != expected_nodes or len(element_ids) != expected_elements:
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("duplicate provider node id")
        raise ValueError("provider fragment count consistency check failed")
    declared_tokens = tuple(
        _safe_token(value, "provider declared id") for value in fragment.declared_ids
    )
    required_tokens = tuple(
        _safe_token(value, "provider required id") for value in fragment.required_ids
    )
    if any(
        _safe_token(value, "provider declared id") != value
        for value in fragment.declared_ids
    ):
        raise ValueError("provider declared IDs must be trimmed")
    if any(
        _safe_token(value, "provider required id") != value
        for value in fragment.required_ids
    ):
        raise ValueError("provider required IDs must be trimmed")
    declared = frozenset(declared_tokens)
    required = frozenset(required_tokens)
    if declared & required:
        raise ValueError("provider declared and required IDs must be disjoint")
    mesh_symbols = set(node_ids) | set(element_ids)
    if not mesh_symbols <= declared:
        raise ValueError("provider mesh IDs must be declared")
    evidence_ids: set[str] = set()
    for evidence in fragment.evidence:
        _validate_provider_evidence(evidence)
        if evidence.evidence_id in evidence_ids:
            raise ValueError("duplicate provider evidence id")
        evidence_ids.add(evidence.evidence_id)
        if evidence.evidence_id not in declared:
            raise ValueError("provider evidence id must be declared")
        if not set(evidence.source_ids) <= declared | required:
            raise ValueError("provider evidence contains unresolved source id")
    manifest = fragment.manifest
    if manifest.get("provider_id") != fragment.provider_id:
        raise ValueError("provider fragment manifest identity mismatch")
    _validate_conservative_flags(manifest, "provider fragment")
    if manifest.get("input_fingerprint") not in {
        None,
        fingerprint_value(fragment.normalized_input),
    }:
        raise ValueError("provider input fingerprint identity mismatch")
    if fragment.provider_id in _PROVIDER_BUDGET_KEYS and manifest.get(
        "input_fingerprint"
    ) != fingerprint_value(fragment.normalized_input):
        raise ValueError("provider input fingerprint identity is missing")
    if artifact is not None:
        if manifest.get("building_artifact_fingerprint") != artifact.fingerprint:
            raise ValueError("provider building artifact identity mismatch")
        topology_fingerprint = artifact.topology_manifest.get("fingerprint")
        if manifest.get("topology_fingerprint") != topology_fingerprint:
            raise ValueError("provider topology fingerprint identity mismatch")
        _validate_provider_faces(fragment, artifact)
    _validate_provider_evidence_identity(fragment, artifact)
    allocation = manifest.get("allocation")
    if isinstance(allocation, Mapping):
        for key, actual in (
            ("actual_node_count", len(node_ids)),
            ("actual_element_count", len(element_ids)),
        ):
            if key in allocation and allocation[key] != actual:
                raise ValueError(f"provider fragment allocation {key} count consistency failed")
        actual = allocation.get("actual")
        if isinstance(actual, Mapping):
            if actual.get("node_count") not in {None, len(node_ids)} or actual.get("element_count") not in {None, len(element_ids)}:
                raise ValueError("provider fragment allocation count consistency failed")
    if estimate is not None:
        _validate_provider_actual_budgets(fragment, estimate, artifact)
    rebuilt = ProviderFragment(
        provider_id=fragment.provider_id,
        normalized_input=fragment.normalized_input,
        axes_m=fragment.axes_m,
        node_ids=fragment.node_ids,
        element_ids=fragment.element_ids,
        fsi_face_ids=fragment.fsi_face_ids,
        required_ids=fragment.required_ids,
        declared_ids=fragment.declared_ids,
        evidence=fragment.evidence,
        manifest=fragment.manifest,
    )
    if rebuilt.fingerprint != fragment.fingerprint:
        raise ValueError("provider fragment fingerprint mismatch")


def _validate_provider_evidence(evidence: ProviderEvidence) -> None:
    for field, value in (
        ("evidence_id", evidence.evidence_id),
        ("evidence_kind", evidence.evidence_kind),
    ):
        if _safe_token(value, f"provider evidence {field}") != value:
            raise ValueError(f"provider evidence {field} must be trimmed")
    _unique_trimmed_tokens(evidence.source_ids, "provider evidence source")
    rebuilt = ProviderEvidence(
        evidence_id=evidence.evidence_id,
        evidence_kind=evidence.evidence_kind,
        source_ids=evidence.source_ids,
        claims=evidence.claims,
    )
    if rebuilt.fingerprint != evidence.fingerprint:
        raise ValueError("provider evidence fingerprint mismatch")


def _validate_provider_faces(
    fragment: ProviderFragment, artifact: BuildingArtifact
) -> None:
    catalog: dict[str, Mapping[str, object]] = {}
    for category in (
        "exterior_surfaces",
        "interior_cavity_surfaces",
        "ground_contact_surfaces",
        "unclassified_boundary_surfaces",
    ):
        rows = artifact.surface_catalog.get(category, ())
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
            raise ValueError(f"artifact surface catalog category {category!r} is invalid")
        for row in rows:
            if not isinstance(row, Mapping) or not isinstance(row.get("face_id"), str):
                raise ValueError("artifact surface catalog contains an invalid face")
            face_id = str(row["face_id"])
            if face_id in catalog:
                raise ValueError(f"artifact surface catalog duplicates face {face_id!r}")
            catalog[face_id] = row
    for face_id in fragment.fsi_face_ids:
        row = catalog.get(face_id)
        if row is None:
            raise ValueError(f"provider FSI face is not in artifact catalog: {face_id!r}")
        if f"surface:{face_id}" not in fragment.required_ids:
            raise ValueError(f"provider FSI face is not a required surface: {face_id!r}")
        element_id = row.get("element_id")
        if (
            isinstance(element_id, bool)
            or not isinstance(element_id, int)
            or f"building:element:{element_id}" not in fragment.required_ids
        ):
            raise ValueError(f"provider FSI face lacks its required structural element: {face_id!r}")
    manifest_faces: object = None
    if fragment.provider_id == "explicit_ale_fsi":
        fsi = fragment.manifest.get("fsi")
        manifest_faces = fsi.get("face_ids") if isinstance(fsi, Mapping) else None
    elif fragment.provider_id == "lbe_segment":
        selection = fragment.manifest.get("selection")
        included = selection.get("included_faces") if isinstance(selection, Mapping) else None
        if isinstance(included, Sequence) and not isinstance(included, (str, bytes, bytearray)):
            manifest_faces = tuple(
                row.get("face_id") for row in included if isinstance(row, Mapping)
            )
    elif fragment.provider_id == "imported_pressure_history":
        mapping = fragment.manifest.get("mapping")
        manifest_faces = mapping.get("target_face_ids") if isinstance(mapping, Mapping) else None
    elif fragment.provider_id == "solver_complete_ale_fsi":
        manifest_faces = fragment.manifest.get("fsi_face_ids")
    if fragment.provider_id in _PROVIDER_BUDGET_KEYS:
        if (
            not isinstance(manifest_faces, Sequence)
            or isinstance(manifest_faces, (str, bytes, bytearray))
            or tuple(manifest_faces) != fragment.fsi_face_ids
        ):
            raise ValueError("provider FSI face manifest identity mismatch")


def _validate_provider_evidence_identity(
    fragment: ProviderFragment, artifact: BuildingArtifact | None
) -> None:
    manifest_evidence = fragment.manifest.get("evidence_fingerprints")
    actual_fingerprints = tuple(evidence.fingerprint for evidence in fragment.evidence)
    if manifest_evidence is not None:
        if (
            not isinstance(manifest_evidence, Sequence)
            or isinstance(manifest_evidence, (str, bytes, bytearray))
            or tuple(manifest_evidence) != actual_fingerprints
        ):
            raise ValueError("provider evidence fingerprint identity mismatch")
    source_rows = tuple(
        evidence
        for evidence in fragment.evidence
        if evidence.evidence_kind == "provider_source_space"
    )
    if fragment.provider_id in _PROVIDER_BUDGET_KEYS and len(source_rows) != 1:
        raise ValueError("provider source-space evidence identity must be unique")
    if not source_rows:
        return
    source = source_rows[0]
    claims = source.claims
    expected_keys = {
        "schema_version",
        "provider_id",
        "source_declared_id",
        "source_space_id",
        "scenario_kind",
        "topology_fingerprint",
        "determination",
        "surface_category",
        "external_opening_ids",
    }
    if set(claims) != expected_keys:
        raise ValueError("provider source evidence claims are not closed")
    if claims.get("schema_version") != "provider_source_space_evidence@1":
        raise ValueError("provider source evidence schema identity mismatch")
    if claims.get("provider_id") != fragment.provider_id:
        raise ValueError("provider source provider identity mismatch")
    if claims.get("scenario_kind") != fragment.manifest.get("scenario_kind"):
        raise ValueError("provider source scenario identity mismatch")
    if claims.get("topology_fingerprint") != fragment.manifest.get("topology_fingerprint"):
        raise ValueError("provider source topology identity mismatch")
    source_declared_id = _safe_token(
        claims.get("source_declared_id"), "provider source declared id"
    )
    if source_declared_id not in fragment.declared_ids:
        raise ValueError("provider source identity is not fragment-declared")
    expected_source_id = _expected_source_declared_id(fragment)
    if expected_source_id is not None and source_declared_id != expected_source_id:
        raise ValueError("provider source identity does not match normalized input")
    expected_sources = {
        source_declared_id,
        f"topology:{claims['topology_fingerprint']}",
    }
    if artifact is not None:
        expected_sources.add(f"artifact:{artifact.fingerprint}")
    if not expected_sources <= set(source.source_ids):
        raise ValueError("provider source evidence lineage identity is incomplete")


def _expected_source_declared_id(fragment: ProviderFragment) -> str | None:
    if fragment.provider_id == "explicit_ale_fsi":
        charge = fragment.normalized_input.get("charge")
        if isinstance(charge, Mapping) and isinstance(charge.get("source_id"), str):
            return f"charge:{charge['source_id']}"
    elif fragment.provider_id == "lbe_segment":
        source = fragment.normalized_input.get("source")
        if isinstance(source, Mapping) and isinstance(source.get("source_id"), str):
            return f"lbe_segment:source:{source['source_id']}"
    elif fragment.provider_id == "imported_pressure_history":
        source = fragment.normalized_input.get("source")
        if isinstance(source, Mapping) and isinstance(source.get("source_id"), str):
            return f"imported_pressure_history:source:{source['source_id']}"
    elif fragment.provider_id == "solver_complete_ale_fsi":
        return "solver_complete_ale_fsi:charge"
    return None


def _validate_provider_actual_budgets(
    fragment: ProviderFragment,
    estimate: ProviderEstimate,
    artifact: BuildingArtifact | None,
) -> None:
    allocation = fragment.manifest.get("allocation")
    if not isinstance(allocation, Mapping):
        raise ValueError("provider fragment allocation manifest is missing")
    embedded_estimate = allocation.get("estimate")
    if not isinstance(embedded_estimate, Mapping):
        raise ValueError("provider allocation estimate identity is missing")
    limits = estimate.budget_limits
    if fragment.provider_id == "explicit_ale_fsi":
        expected_counts = {
            "axis_point_counts": estimate.axis_point_counts,
            "node_count": estimate.node_count,
            "element_count": estimate.element_count,
        }
        if fingerprint_value(embedded_estimate) != fingerprint_value(expected_counts):
            raise ValueError("provider allocation estimate identity mismatch")
        actual = allocation.get("actual")
        if not isinstance(actual, Mapping):
            raise ValueError("provider actual allocation is missing")
        if fingerprint_value(actual) != fingerprint_value(expected_counts):
            raise ValueError("provider actual allocation does not match estimate")
        if allocation.get("estimate_matches_actual") is not True:
            raise ValueError("provider actual allocation is not confirmed")
        axes = actual.get("axis_point_counts")
        if (
            not isinstance(axes, Sequence)
            or isinstance(axes, (str, bytes, bytearray))
            or len(axes) != 3
            or any(isinstance(count, bool) or not isinstance(count, int) for count in axes)
        ):
            raise ValueError("provider actual axis allocation is invalid")
        if any(count > limits["max_axis_points"] for count in axes):
            raise ValueError("provider axis budget exceeded")
        node_count = actual.get("node_count")
        element_count = actual.get("element_count")
        if node_count != len(fragment.node_ids) or node_count > limits["max_node_count"]:
            raise ValueError("provider node budget exceeded")
        if element_count != len(fragment.element_ids) or element_count > limits["max_element_count"]:
            raise ValueError("provider element budget exceeded")
    elif fragment.provider_id == "lbe_segment":
        if fingerprint_value(embedded_estimate) != fingerprint_value(estimate.to_manifest()):
            raise ValueError("provider allocation estimate identity mismatch")
        surface_count = allocation.get("actual_loaded_surface_count")
        target_count = allocation.get("actual_target_surface_count")
        total_area = allocation.get("actual_total_area_m2")
        if (
            isinstance(surface_count, bool)
            or not isinstance(surface_count, int)
            or surface_count < 0
            or surface_count > limits["max_surface_count"]
        ):
            raise ValueError("provider surface count budget exceeded")
        if (
            isinstance(total_area, bool)
            or not isinstance(total_area, (int, float))
            or not math.isfinite(float(total_area))
            or float(total_area) < 0
            or float(total_area) > limits["max_total_area_m2"]
        ):
            raise ValueError("provider surface area budget exceeded")
        expected_count, expected_area = _provider_catalog_totals(fragment, artifact)
        if surface_count != expected_count or target_count != expected_count:
            raise ValueError("provider surface count does not match catalog allocation")
        if not math.isclose(
            float(total_area), expected_area, rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError("provider surface area does not match catalog allocation")
    elif fragment.provider_id == "imported_pressure_history":
        if fingerprint_value(embedded_estimate) != fingerprint_value(estimate.to_manifest()):
            raise ValueError("provider allocation estimate identity mismatch")
        curve_rows = allocation.get("actual_curve_row_count")
        targets = allocation.get("actual_target_surface_count")
        curve = fragment.manifest.get("curve")
        source_bytes = curve.get("source_byte_count") if isinstance(curve, Mapping) else None
        normalized_curve = fragment.manifest.get("normalized_curve_si")
        expected_count, _ = _provider_catalog_totals(fragment, artifact)
        if targets != expected_count:
            raise ValueError("provider surface count does not match catalog allocation")
        if (
            not isinstance(normalized_curve, Sequence)
            or isinstance(normalized_curve, (str, bytes, bytearray))
            or curve_rows != len(normalized_curve)
        ):
            raise ValueError("provider curve row count does not match normalized curve")
        normalized_curve_manifest = fragment.normalized_input.get("curve")
        expected_source_bytes = (
            normalized_curve_manifest.get("source_byte_count")
            if isinstance(normalized_curve_manifest, Mapping)
            else None
        )
        if source_bytes != expected_source_bytes:
            raise ValueError("provider input byte count does not match normalized input")
        for value, key, limit_key in (
            (curve_rows, "curve row", "max_row_count"),
            (targets, "target surface", "max_target_surface_count"),
            (source_bytes, "input byte", "max_input_bytes"),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or value > limits[limit_key]
            ):
                raise ValueError(f"provider {key} budget exceeded")


def _provider_catalog_totals(
    fragment: ProviderFragment, artifact: BuildingArtifact | None
) -> tuple[int, float]:
    if artifact is None:
        raise ValueError("real provider budget validation requires a building artifact")
    requested = set(fragment.fsi_face_ids)
    found: set[str] = set()
    areas: list[float] = []
    for category in (
        "exterior_surfaces",
        "interior_cavity_surfaces",
        "ground_contact_surfaces",
        "unclassified_boundary_surfaces",
    ):
        rows = artifact.surface_catalog.get(category, ())
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
            continue
        for row in rows:
            if not isinstance(row, Mapping) or row.get("face_id") not in requested:
                continue
            face_id = str(row["face_id"])
            area, _, _ = surface_geometry_from_artifact(
                artifact, row, f"provider FSI face {face_id}"
            )
            found.add(face_id)
            areas.append(area)
    if found != requested:
        raise ValueError("provider FSI catalog allocation is incomplete")
    return len(found), math.fsum(areas)


def _validate_keyword_fragment(fragment: KeywordFragment) -> None:
    declared = frozenset(_safe_token(value, "fragment declared id") for value in fragment.declared_ids)
    required = frozenset(_safe_token(value, "fragment required id") for value in fragment.required_ids)
    if any(_safe_token(value, "fragment declared id") != value for value in fragment.declared_ids):
        raise ValueError("fragment declared IDs must be trimmed")
    if any(_safe_token(value, "fragment required id") != value for value in fragment.required_ids):
        raise ValueError("fragment required IDs must be trimmed")
    if declared & required:
        raise ValueError("fragment declared and required IDs must be disjoint")
    estimates = fragment.estimates
    for key in ("new_nodes", "new_elements"):
        value = estimates.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"fragment estimate {key} must be a non-negative integer")
    if estimates.get("budget_checked_before_allocation") is not True:
        raise ValueError("fragment must be budget-checked before allocation")
    limits = estimates.get("budget_limits")
    if not isinstance(limits, Mapping):
        raise ValueError("fragment estimates require budget_limits")
    for count_key, limit_key in (("new_nodes", "max_new_nodes"), ("new_elements", "max_new_elements")):
        limit = limits.get(limit_key)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError(f"fragment budget {limit_key} must be a positive integer")
        if estimates[count_key] > limit:
            raise ValueError(f"fragment {count_key} exceeds declared budget")
    geometry = fragment.manifest.get("ground_geometry")
    if not isinstance(geometry, Mapping) and (
        estimates["new_nodes"] != 0 or estimates["new_elements"] != 0
    ):
        raise ValueError("keyword fragment geometry count consistency check failed")
    if isinstance(geometry, Mapping):
        nodes = geometry.get("nodes")
        elements = geometry.get("elements")
        if (
            not isinstance(nodes, Sequence)
            or isinstance(nodes, (str, bytes, bytearray))
            or not isinstance(elements, Sequence)
            or isinstance(elements, (str, bytes, bytearray))
            or len(nodes) != estimates["new_nodes"]
            or len(elements) != estimates["new_elements"]
        ):
            raise ValueError("keyword fragment geometry count consistency check failed")
    if fragment.module_id == "controls":
        from .controls import normalize_solver_controls

        normalized = normalize_solver_controls(fragment.manifest)
        if fingerprint_value(normalized) != fingerprint_value(fragment.manifest):
            raise ValueError("controls fragment differs from its canonical closed contract")
    elif fragment.module_id == "outputs":
        from .outputs import normalize_output_requests

        normalized = normalize_output_requests(fragment.manifest)
        if fingerprint_value(normalized) != fingerprint_value(fragment.manifest):
            raise ValueError("outputs fragment differs from its canonical closed contract")
    _validate_conservative_flags(fragment.manifest, "keyword fragment")
    rebuilt = KeywordFragment(
        module_id=fragment.module_id,
        declared_ids=fragment.declared_ids,
        required_ids=fragment.required_ids,
        estimates=fragment.estimates,
        manifest=fragment.manifest,
        participants=fragment.participants,
        interfaces=fragment.interfaces,
    )
    if rebuilt.fingerprint != fragment.fingerprint:
        raise ValueError("keyword fragment fingerprint mismatch")


def _declaration_owners(
    fragments: tuple[KeywordFragment, ...], provider: ProviderFragment | None
) -> tuple[set[str], dict[str, str]]:
    owners: dict[str, str] = {}
    rows: list[tuple[str, Iterable[str]]] = []
    if provider is not None:
        rows.append(("provider", provider.declared_ids))
    rows.extend((fragment.module_id, fragment.declared_ids) for fragment in fragments)
    for owner, symbols in rows:
        for symbol in symbols:
            previous = owners.get(symbol)
            if previous is not None:
                raise ValueError(
                    f"duplicate declaration across namespaces: {symbol!r} ({previous}, {owner})"
                )
            owners[symbol] = owner
    return set(owners), owners


def _all_requirements(
    fragments: tuple[KeywordFragment, ...], provider: ProviderFragment | None
) -> set[str]:
    result = {symbol for fragment in fragments for symbol in fragment.required_ids}
    if provider is not None:
        result.update(provider.required_ids)
        result.update(
            source_id for evidence in provider.evidence for source_id in evidence.source_ids
        )
    return result


def _validate_dependency_graph(
    fragments: tuple[KeywordFragment, ...],
    provider: ProviderFragment | None,
    owners: Mapping[str, str],
) -> None:
    requirements: dict[str, set[str]] = {
        fragment.module_id: set(fragment.required_ids) for fragment in fragments
    }
    if provider is not None:
        requirements["provider"] = set(provider.required_ids) | {
            source_id for evidence in provider.evidence for source_id in evidence.source_ids
        }
    graph: dict[str, set[str]] = {owner: set() for owner in requirements}
    for owner, symbols in requirements.items():
        for symbol in symbols:
            dependency_owner = owners.get(symbol)
            if dependency_owner is not None and dependency_owner != owner:
                graph[owner].add(dependency_owner)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(owner: str) -> None:
        if owner in visiting:
            raise ValueError(f"cyclic dependency detected at module {owner!r}")
        if owner in visited:
            return
        visiting.add(owner)
        for dependency in sorted(graph[owner]):
            visit(dependency)
        visiting.remove(owner)
        visited.add(owner)

    for owner in sorted(graph):
        visit(owner)


def _validate_typed_graph(fragments: tuple[KeywordFragment, ...]) -> None:
    participants: dict[str, str] = {}
    interfaces: set[str] = set()
    member_owner: dict[str, str] = {}
    for fragment in fragments:
        for participant in fragment.participants:
            if participant.participant_id in participants:
                raise ValueError(f"typed participant is duplicated: {participant.participant_id!r}")
            participants[participant.participant_id] = fragment.module_id
            for member in participant.member_ids:
                previous = member_owner.get(member)
                if previous is not None and previous != participant.participant_id:
                    raise ValueError(f"typed member has conflicting owners: {member!r}")
                member_owner[member] = participant.participant_id
        for interface in fragment.interfaces:
            if interface.interface_id in interfaces:
                raise ValueError(f"typed interface is duplicated: {interface.interface_id!r}")
            interfaces.add(interface.interface_id)
    if set(participants) & interfaces:
        raise ValueError("typed participant and interface namespaces overlap")
    for fragment in fragments:
        for interface in fragment.interfaces:
            if interface.source_participant_id not in participants or interface.target_participant_id not in participants:
                raise ValueError(f"typed interface references unknown participant: {interface.interface_id!r}")


def _render_main(include_order: tuple[str, ...]) -> bytes:
    lines = [
        "*KEYWORD",
        "$ Phase 18E research candidate; solver readiness is intentionally false.",
    ]
    for path in include_order:
        lines.extend(("*INCLUDE", path))
    lines.append("*END")
    return _lines_bytes(lines)


def _render_building(artifact: BuildingArtifact) -> bytes:
    roles = sorted(
        {
            element.part_role
            for element in (*artifact.mesh.solids, *artifact.mesh.shells, *artifact.mesh.beams)
        }
    )
    part_ids = {role: index for index, role in enumerate(roles, start=1)}
    lines = [
        "$ Phase 18C/D immutable building mesh; material/section cards remain project-review inputs.",
        "*NODE",
    ]
    lines.extend(
        f"{node.node_id},{_number(node.x)},{_number(node.y)},{_number(node.z)}"
        for node in sorted(artifact.mesh.nodes, key=lambda row: row.node_id)
    )
    if artifact.mesh.solids:
        lines.append("*ELEMENT_SOLID")
        lines.extend(
            ",".join(
                str(value)
                for value in (element.element_id, part_ids[element.part_role], *element.node_ids)
            )
            for element in sorted(artifact.mesh.solids, key=lambda row: row.element_id)
        )
    if artifact.mesh.shells:
        lines.append("*ELEMENT_SHELL")
        lines.extend(
            ",".join(
                str(value)
                for value in (element.element_id, part_ids[element.part_role], *element.node_ids)
            )
            for element in sorted(artifact.mesh.shells, key=lambda row: row.element_id)
        )
    if artifact.mesh.beams:
        lines.append("*ELEMENT_BEAM")
        lines.extend(
            ",".join(
                str(value)
                for value in (
                    element.element_id,
                    part_ids[element.part_role],
                    *element.node_ids,
                    0,
                )
            )
            for element in sorted(artifact.mesh.beams, key=lambda row: row.element_id)
        )
    lines.append("$ Part-role to candidate numeric PID mapping (no material cards invented).")
    lines.extend(f"$ {part_ids[role]} = {role}" for role in roles)
    return _lines_bytes(lines)


def _render_provider(fragment: ProviderFragment, symbol_map: Mapping[str, int]) -> bytes:
    lines = [
        f"$ Provider {fragment.provider_id}; research candidate only.",
        "$ " + _canonical_text(fragment.manifest),
    ]
    if fragment.node_ids:
        x_axis, y_axis, z_axis = fragment.axes_m
        lines.append("*NODE")
        index = 0
        for z in z_axis:
            for y in y_axis:
                for x in x_axis:
                    symbol = fragment.node_ids[index]
                    lines.append(
                        f"{symbol_map[symbol]},{_number(x)},{_number(y)},{_number(z)}"
                    )
                    index += 1
        part_symbol = next(
            (
                symbol
                for symbol in sorted(fragment.declared_ids)
                if symbol not in set(fragment.node_ids) | set(fragment.element_ids)
            ),
            fragment.element_ids[0],
        )
        part_id = symbol_map[part_symbol]
        lines.append("*ELEMENT_SOLID")
        nx, ny, nz = (len(axis) for axis in fragment.axes_m)
        element_index = 0
        for iz in range(nz - 1):
            for iy in range(ny - 1):
                for ix in range(nx - 1):
                    node_index = lambda x, y, z: z * nx * ny + y * nx + x
                    corners = (
                        node_index(ix, iy, iz),
                        node_index(ix + 1, iy, iz),
                        node_index(ix + 1, iy + 1, iz),
                        node_index(ix, iy + 1, iz),
                        node_index(ix, iy, iz + 1),
                        node_index(ix + 1, iy, iz + 1),
                        node_index(ix + 1, iy + 1, iz + 1),
                        node_index(ix, iy + 1, iz + 1),
                    )
                    element_symbol = fragment.element_ids[element_index]
                    lines.append(
                        ",".join(
                            str(value)
                            for value in (
                                symbol_map[element_symbol],
                                part_id,
                                *(symbol_map[fragment.node_ids[index]] for index in corners),
                            )
                        )
                    )
                    element_index += 1
    else:
        lines.append("$ No provider mesh; load mapping remains in the audited neutral manifest.")
    return _lines_bytes(lines)


def _render_fragment(fragment: KeywordFragment, symbol_map: Mapping[str, int]) -> bytes:
    lines = [
        f"$ Phase 18E module {fragment.module_id}",
        "$ manifest=" + _canonical_text(fragment.manifest),
    ]
    if fragment.module_id == "controls":
        lines.extend(
            (
                "*CONTROL_TERMINATION",
                _number(fragment.manifest["termination_time_s"]),
                "*CONTROL_TIMESTEP",
                f"0,{_number(fragment.manifest['timestep_scale_factor'])}",
            )
        )
    elif fragment.module_id == "outputs":
        lines.extend(
            (
                "*DATABASE_BINARY_D3PLOT",
                _number(fragment.manifest["d3plot_interval_s"]),
                "*DATABASE_BINARY_D3THDT",
                _number(fragment.manifest["history_interval_s"]),
            )
        )
    geometry = fragment.manifest.get("ground_geometry")
    if isinstance(geometry, Mapping):
        nodes, elements, part_symbol = _validated_ground_geometry(fragment, geometry, symbol_map)
        lines.append("*NODE")
        lines.extend(
            f"{symbol_map[row['node_id']]},{_number(row['coordinates_m'][0])},"
            f"{_number(row['coordinates_m'][1])},{_number(row['coordinates_m'][2])}"
            for row in nodes
        )
        lines.append("*ELEMENT_SOLID")
        lines.extend(
            ",".join(
                str(value)
                for value in (
                    symbol_map[row["element_id"]],
                    symbol_map[part_symbol],
                    *(symbol_map[node_id] for node_id in row["node_ids"]),
                )
            )
            for row in elements
        )
    if fragment.participants:
        lines.append("$ typed_participants")
        lines.extend(
            "$ "
            + _canonical_text(
                {
                    **dict(row.to_manifest()),
                    "numeric_id": symbol_map.get(row.participant_id),
                }
            )
            for row in sorted(fragment.participants, key=lambda item: item.participant_id)
        )
    if fragment.interfaces:
        lines.append("$ typed_interfaces")
        lines.extend(
            "$ "
            + _canonical_text(
                {
                    **dict(row.to_manifest()),
                    "numeric_id": symbol_map.get(row.interface_id),
                }
            )
            for row in sorted(fragment.interfaces, key=lambda item: item.interface_id)
        )
    lines.append("$ symbolic_id,numeric_id")
    lines.extend(
        f"$ {symbol},{symbol_map[symbol]}" for symbol in sorted(fragment.declared_ids)
    )
    return _lines_bytes(lines)


def _artifact_external_ids(artifact: BuildingArtifact) -> set[str]:
    result = {
        f"artifact:{artifact.fingerprint}",
        f"topology:{artifact.topology_manifest.get('fingerprint', '')}",
        *(f"building:node:{node.node_id}" for node in artifact.mesh.nodes),
        *(
            f"building:element:{element.element_id}"
            for element in (*artifact.mesh.solids, *artifact.mesh.shells, *artifact.mesh.beams)
        ),
    }
    for category in (
        "exterior_surfaces",
        "interior_cavity_surfaces",
        "ground_contact_surfaces",
        "unclassified_boundary_surfaces",
    ):
        rows = artifact.surface_catalog.get(category, ())
        if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray)):
            result.update(
                f"surface:{row['face_id']}" for row in rows if isinstance(row, Mapping)
            )
    topology = artifact.topology_manifest
    for row in topology.get("void_regions", ()):
        if isinstance(row, Mapping) and isinstance(row.get("id"), str):
            result.add(f"space:{row['id']}")
    for row in artifact.normalized_input.get("openings", ()):
        if isinstance(row, Mapping) and isinstance(row.get("id"), str):
            result.add(f"opening:{row['id']}")
    return {_safe_token(value, "artifact external id") for value in result if value.split(":", 1)[-1]}


def _artifact_render_ids(artifact: BuildingArtifact) -> Mapping[str, int]:
    result = {
        **{f"building:node:{node.node_id}": node.node_id for node in artifact.mesh.nodes},
        **{
            f"building:element:{element.element_id}": element.element_id
            for element in (*artifact.mesh.solids, *artifact.mesh.shells, *artifact.mesh.beams)
        },
    }
    return MappingProxyType(result)


def _building_numeric_ids(artifact: BuildingArtifact) -> set[int]:
    roles = {
        element.part_role
        for element in (*artifact.mesh.solids, *artifact.mesh.shells, *artifact.mesh.beams)
    }
    return {
        *(node.node_id for node in artifact.mesh.nodes),
        *(
            element.element_id
            for element in (*artifact.mesh.solids, *artifact.mesh.shells, *artifact.mesh.beams)
        ),
        *(range(1, len(roles) + 1)),
    }


def _choose_range_base(occupied: set[int], capacity: int) -> int:
    """Choose one deterministic block for every reserved module range."""

    span = (_RESERVED_RANGE_COUNT + 1) * capacity
    base = _BASE_NUMERIC_ID
    while base + span <= _MAX_NUMERIC_ID:
        first = base + capacity + 1
        last = base + span
        if not any(first <= numeric_id <= last for numeric_id in occupied):
            return base
        base += span
    raise ValueError("no collision-free fixed-capacity ID range is available")


def _validated_ground_geometry(
    fragment: KeywordFragment,
    geometry: Mapping[str, object],
    symbol_map: Mapping[str, int],
) -> tuple[tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...], str]:
    raw_nodes = geometry.get("nodes")
    raw_elements = geometry.get("elements")
    if (
        not isinstance(raw_nodes, Sequence)
        or isinstance(raw_nodes, (str, bytes, bytearray))
        or not isinstance(raw_elements, Sequence)
        or isinstance(raw_elements, (str, bytes, bytearray))
    ):
        raise ValueError("ground geometry nodes/elements must be sequences")
    nodes: list[Mapping[str, object]] = []
    node_ids: set[str] = set()
    for index, raw in enumerate(raw_nodes):
        if not isinstance(raw, Mapping):
            raise ValueError("ground geometry node must be a mapping")
        node_id = _safe_token(raw.get("node_id"), f"ground node {index}")
        if node_id not in fragment.declared_ids or node_id in node_ids:
            raise ValueError("ground geometry node must be uniquely fragment-declared")
        coordinates = raw.get("coordinates_m")
        if (
            not isinstance(coordinates, Sequence)
            or isinstance(coordinates, (str, bytes, bytearray))
            or len(coordinates) != 3
        ):
            raise ValueError("ground geometry node coordinates must contain three values")
        canonical_coordinates = tuple(
            _finite_number(value, f"ground node {node_id} coordinate") for value in coordinates
        )
        nodes.append({**dict(raw), "node_id": node_id, "coordinates_m": canonical_coordinates})
        node_ids.add(node_id)
    elements: list[Mapping[str, object]] = []
    element_ids: set[str] = set()
    for index, raw in enumerate(raw_elements):
        if not isinstance(raw, Mapping):
            raise ValueError("ground geometry element must be a mapping")
        element_id = _safe_token(raw.get("element_id"), f"ground element {index}")
        connectivity = raw.get("node_ids")
        if (
            element_id not in fragment.declared_ids
            or element_id in element_ids
            or not isinstance(connectivity, Sequence)
            or isinstance(connectivity, (str, bytes, bytearray))
            or len(connectivity) != 8
        ):
            raise ValueError("ground solid must be unique, declared and contain eight nodes")
        node_symbols = tuple(
            _safe_token(value, f"ground element {element_id} node") for value in connectivity
        )
        missing = set(node_symbols) - set(symbol_map)
        if missing:
            raise ValueError(f"ground solid has unresolved node: {sorted(missing)[0]!r}")
        elements.append({**dict(raw), "element_id": element_id, "node_ids": node_symbols})
        element_ids.add(element_id)
    ground_participants = tuple(
        participant
        for participant in fragment.participants
        if participant.role == "ground_support"
        and participant.kind == "ground_mesh"
        and element_ids <= participant.member_ids
        and node_ids <= participant.member_ids
    )
    if len(ground_participants) != 1:
        raise ValueError("ground geometry requires one exact typed ground_mesh participant")
    part_symbol = ground_participants[0].participant_id
    if part_symbol not in symbol_map:
        raise ValueError("ground mesh participant has no allocated numeric ID")
    return tuple(nodes), tuple(elements), part_symbol


def _declared_provider_resources(value: Mapping[str, object]) -> set[str]:
    resources = value.get("resources")
    if not isinstance(resources, Mapping):
        return set()
    result: set[str] = set()
    for row in resources.values():
        if not isinstance(row, Mapping):
            continue
        resource_id = row.get("resource_id")
        version = row.get("version")
        if isinstance(resource_id, str) and isinstance(version, str):
            result.add(f"resource:{resource_id}@{version}")
    return result


def _structured_counts(counts: Sequence[int]) -> tuple[int, int]:
    if len(counts) != 3:
        raise ValueError("structured grid counts must contain three axes")
    if not any(counts):
        return 0, 0
    if not all(count >= 2 for count in counts):
        raise ValueError("structured grid axes must be all empty or contain at least two points")
    return math.prod(counts), math.prod(count - 1 for count in counts)


def _unique_trimmed_tokens(values: Sequence[str], label: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        token = _safe_token(value, label)
        if token != value:
            raise ValueError(f"{label} IDs must be trimmed")
        result.append(token)
    if len(result) != len(set(result)):
        raise ValueError(f"duplicate {label} id")
    return tuple(result)


def _safe_token(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty safe identifier")
    token = value.strip()
    if any(character.isspace() for character in token) or any(
        character in token for character in ("/", "\\", "\x00")
    ) or token in {".", ".."}:
        raise ValueError(f"{path} must be a safe identifier")
    return token


def _safe_path(value: object, path: str) -> str:
    token = _safe_token(value, path)
    allowed_sidecars = {"manifest.json", "assessment_semantics.json"}
    if ":" in token or not (
        token.endswith(".k") or token in allowed_sidecars
    ):
        raise ValueError(
            f"{path} must be one local .k filename or approved JSON sidecar"
        )
    return token


def _finite_number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be finite")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{path} must be finite")
    return number


def _validate_conservative_flags(value: Mapping[str, object], path: str) -> None:
    expected = {
        "solver_ready": False,
        "requires_project_review": True,
        "engineering_validated": False,
    }
    for key, expected_value in expected.items():
        if value.get(key) is not expected_value:
            raise ValueError(f"{path} must keep {key}={expected_value!r}")


def _fragment_order_key(fragment: KeywordFragment) -> tuple[int, str]:
    return _MODULE_INDEX[fragment.module_id], fragment.module_id


def _canonical_text(value: object) -> str:
    import json

    return json.dumps(
        thaw_value(value), ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )


def _number(value: object) -> str:
    return format(_finite_number(value, "rendered number"), ".17g")


def _lines_bytes(lines: Iterable[str]) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


def _file_manifest(path: str, content: bytes) -> dict[str, object]:
    return {
        "path": path,
        "sha256": hashlib.sha256(content).hexdigest(),
        "byte_count": len(content),
        "line_count": len(content.decode("utf-8").splitlines()),
    }


__all__ = [
    "ProjectAssembler",
    "RefinedBlastPackage",
    "assemble_refined_blast_project",
]
