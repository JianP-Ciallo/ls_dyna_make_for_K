"""Authoritative, external-launch-free Phase 18E orchestration service."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from lsprepost_mcp.refined_building.artifacts import BuildingArtifact

from .assembler import RefinedBlastPackage, assemble_refined_blast_project
from .contracts import RefinedBlastProject, ScenarioDraft
from .preview import RefinedBlastPreview, build_refined_blast_preview
from .provider_registry import get_load_provider
from .providers.common import (
    ProviderContext,
    fingerprint_value,
    surface_geometry_from_artifact,
    thaw_value,
)
from .store import DraftConflictError, RefinedBlastStore, StoredProject
from .validation import ValidationFinding, ValidationResult, validation_result


_ADAPTER_FINGERPRINT = fingerprint_value(
    {
        "service": "refined_blast.service@1",
        "assembler": "refined_blast.keyword_package@1",
        "preview_primitives": "refined_blast.neutral_primitives@2",
    }
)
_MAX_PUBLIC_INTEGER_BITS = 4_096
_MAX_PUBLIC_CONTAINER_ITEMS = 1_000_000
_MAX_LSDYNA_ID = 2_147_483_647
_PACKAGE_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "unit_system",
        "project_fingerprint",
        "building_artifact_fingerprint",
        "provider_fingerprint",
        "fragment_fingerprints",
        "include_order",
        "files",
        "rendered_counts",
        "dependency_closure",
        "id_allocation",
        "research_candidate",
        "solver_ready",
        "requires_project_review",
        "engineering_validated",
        "external_program_started",
    }
)
_RENDERED_COUNT_KEYS = frozenset(
    {
        "building_nodes",
        "building_elements",
        "provider_nodes",
        "provider_elements",
        "provider_fsi_faces",
        "module_new_nodes",
        "module_new_elements",
        "symbolic_ids",
    }
)
_PROVIDER_MANIFEST_KEYS = {
    "explicit_ale_fsi": frozenset(
        {
            "schema_version", "provider_id", "scenario_kind",
            "building_artifact_fingerprint", "topology_fingerprint",
            "input_fingerprint", "allocation", "fsi", "resources",
            "evidence_fingerprints", "id_closure", "software_candidate_only",
            "solver_ready", "requires_project_review", "engineering_validated",
            "external_program_started",
        }
    ),
    "lbe_segment": frozenset(
        {
            "schema_version", "provider_id", "scenario_kind",
            "building_artifact_fingerprint", "topology_fingerprint",
            "input_fingerprint", "surface_categories", "selection", "load",
            "allocation", "evidence_fingerprints", "id_closure",
            "software_candidate_only", "solver_ready", "requires_project_review",
            "engineering_validated", "lbe_is_not_ale_fsi_equivalent",
            "external_program_started",
        }
    ),
    "imported_pressure_history": frozenset(
        {
            "schema_version", "provider_id", "scenario_kind",
            "building_artifact_fingerprint", "topology_fingerprint",
            "input_fingerprint", "source", "normalized_curve_si", "curve",
            "mapping", "allocation", "evidence_fingerprints", "id_closure",
            "software_candidate_only", "solver_ready", "requires_project_review",
            "engineering_validated",
            "imported_history_provenance_calibration_and_applicability_validated",
            "external_program_started",
        }
    ),
    "solver_complete_ale_fsi": frozenset(
        {
            "schema_version", "provider_id", "scenario_kind",
            "building_artifact_fingerprint", "topology_fingerprint",
            "input_fingerprint", "allocation", "fsi_face_ids",
            "evidence_fingerprints", "id_closure",
            "solver_complete", "solver_ready", "requires_project_review",
            "engineering_validated", "external_program_started",
        }
    ),
}


@dataclass(frozen=True, slots=True)
class WarningAcknowledgement:
    finding_id: str
    finding_content_hash: str
    project_revision: int
    validation_fingerprint: str
    acknowledged_at: str


@dataclass(frozen=True, slots=True)
class ScenarioPackage:
    scenario_id: str
    package: RefinedBlastPackage
    result_id: str

    @property
    def package_fingerprint(self) -> str:
        return self.package.package_fingerprint


@dataclass(frozen=True, slots=True)
class ScenarioSetResult:
    project_id: str
    project_revision: int
    packages: tuple[ScenarioPackage, ...]
    fingerprint: str


class RefinedBlastService:
    """Validate, preview and compile one immutable building without side effects."""

    def __init__(
        self,
        store: RefinedBlastStore,
        project_id: str,
        artifact: BuildingArtifact,
    ):
        if not isinstance(store, RefinedBlastStore):
            raise TypeError("store must be a RefinedBlastStore")
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty identifier")
        if not isinstance(artifact, BuildingArtifact):
            raise TypeError("artifact must be a BuildingArtifact")
        self._store = store
        self._project_id = project_id
        self._artifact = artifact
        self._acknowledgements: dict[tuple[str, str], WarningAcknowledgement] = {}
        self._preview_cache: dict[str, RefinedBlastPreview] = {}

    def validate(self, *, expected_revision: int) -> ValidationResult:
        stored = self._load_current(expected_revision)
        project = stored.project
        revision = stored.revision
        findings: list[ValidationFinding] = []
        bounded_errors = _bounded_public_project_errors(project)
        if bounded_errors:
            for index, message in enumerate(bounded_errors):
                findings.append(_finding("error", "service", "project", message, "Use finite, bounded values within the declared schema budgets.", f"public-boundary-{index}"))
            project_fingerprint = fingerprint_value({"project_id": project.project_id, "building": project.building_artifact_fingerprint, "invalid": bounded_errors})
            return validation_result(project_id=project.project_id, project_revision=revision, project_fingerprint=project_fingerprint, findings=findings)

        project_fingerprint = fingerprint_value(_project_semantics(project))
        if project.building_artifact_fingerprint != self._artifact.fingerprint:
            findings.append(_finding("error", "building", "building_artifact_fingerprint", "project building artifact fingerprint does not match the supplied immutable artifact", "Reload the referenced Phase 18C/D building artifact.", "building-fingerprint"))
        if project.building_reference.get("asset_id") != self._artifact.asset_id:
            findings.append(_finding("error", "building", "building_reference.asset_id", "project building reference does not match the supplied immutable artifact", "Select the referenced building artifact.", "building-reference"))

        for scenario in project.scenario_set:
            findings.extend(self._validate_scenario(project, scenario))
            findings.append(
                _finding(
                    "warning",
                    "project_review",
                    f"scenario_set.{scenario.scenario_id}",
                    "Phase 18E output is a research candidate and requires project review",
                    "Review the evidence, budgets and layered preview before generation.",
                    f"review-{scenario.scenario_id}",
                    evidence={"scenario_id": scenario.scenario_id, "scenario_fingerprint": fingerprint_value(_scenario_semantics(scenario))},
                )
            )
        return validation_result(project_id=project.project_id, project_revision=revision, project_fingerprint=project_fingerprint, findings=findings)

    def preview(self, *, expected_revision: int) -> RefinedBlastPreview:
        stored = self._load_current(expected_revision)
        project = stored.project
        revision = stored.revision
        validation = self.validate(expected_revision=revision)
        if validation.errors:
            raise ValueError("blocking validation errors prevent preview compilation")
        if len(project.scenario_set) != 1:
            raise ValueError("preview requires exactly one scenario")
        package = assemble_refined_blast_project(project, self._artifact)
        validate_public_package(
            package,
            self._store,
            self._project_id,
            self._artifact,
            expected_revision=revision,
        )
        provider_preview = self._provider_preview(project.scenario_set[0])
        module_payloads = _module_preview_payloads(
            package, self._artifact, provider_preview
        )
        cache_key = _cache_key(project, self._artifact, package, revision)
        final = not self._unacknowledged(validation)
        cached = self._preview_cache.get(cache_key)
        if cached is not None and cached.is_final == final:
            return cached
        preview = build_refined_blast_preview(
            project,
            self._artifact,
            package,
            provider_preview=provider_preview,
            module_payloads=module_payloads,
            revision=revision,
            cache_key=cache_key,
            is_final=final,
        )
        self._preview_cache[cache_key] = preview
        return preview

    def acknowledge(
        self,
        validation: ValidationResult,
        finding_id: str,
        *,
        acknowledged_at: str | None = None,
    ) -> WarningAcknowledgement:
        if not isinstance(validation, ValidationResult):
            raise TypeError("validation must be a ValidationResult")
        current = self.validate(expected_revision=validation.project_revision)
        if current.fingerprint != validation.fingerprint:
            raise DraftConflictError("validation does not match the current persisted project")
        rows = tuple(row for row in validation.warnings if row.finding_id == finding_id)
        if len(rows) != 1:
            raise ValueError("finding_id must identify one current warning")
        row = rows[0]
        record = WarningAcknowledgement(
            finding_id=row.finding_id,
            finding_content_hash=row.content_hash,
            project_revision=validation.project_revision,
            validation_fingerprint=validation.fingerprint,
            acknowledged_at=acknowledged_at or _utc_timestamp(),
        )
        self._acknowledgements[(validation.fingerprint, row.finding_id)] = record
        return record

    def generation_gate(self, validation: ValidationResult) -> dict[str, object]:
        """Return the authoritative, acknowledgement-aware generation decision."""

        if not isinstance(validation, ValidationResult):
            raise TypeError("validation must be a ValidationResult")
        current = self.validate(expected_revision=validation.project_revision)
        if current.fingerprint != validation.fingerprint:
            raise DraftConflictError("validation does not match the current persisted project")
        blocking = tuple(row.finding_id for row in current.errors)
        unacknowledged = tuple(row.finding_id for row in self._unacknowledged(current))
        return {
            "allowed": not blocking and not unacknowledged,
            "project_id": current.project_id,
            "project_revision": current.project_revision,
            "validation_fingerprint": current.fingerprint,
            "blocking_error_ids": list(blocking),
            "unacknowledged_warning_ids": list(unacknowledged),
        }

    def generate(self, *, expected_revision: int) -> RefinedBlastPackage:
        stored = self._load_current(expected_revision)
        project = stored.project
        revision = stored.revision
        validation = self.validate(expected_revision=revision)
        if validation.errors:
            raise ValueError("blocking validation errors prevent generation")
        if self._unacknowledged(validation):
            raise ValueError("unacknowledged warning prevents generation")
        if len(project.scenario_set) != 1:
            raise ValueError("generate requires exactly one scenario; use compile_scenario_set")
        package = assemble_refined_blast_project(project, self._artifact)
        validate_public_package(
            package,
            self._store,
            self._project_id,
            self._artifact,
            expected_revision=revision,
        )
        return package

    def compile_scenario_set(
        self, *, expected_revision: int
    ) -> ScenarioSetResult:
        stored = self._load_current(expected_revision)
        project = stored.project
        revision = stored.revision
        validation = self.validate(expected_revision=revision)
        if validation.errors:
            raise ValueError("blocking validation errors prevent ScenarioSet compilation")
        _reject_duplicate_scenarios(project.scenario_set)
        if self._unacknowledged(validation):
            raise ValueError("unacknowledged warning prevents ScenarioSet compilation")
        packages: list[ScenarioPackage] = []
        for scenario in project.scenario_set:
            isolated = replace(project, scenario_set=(scenario,))
            package = assemble_refined_blast_project(isolated, self._artifact)
            validate_public_package(
                package,
                self._store,
                self._project_id,
                self._artifact,
                expected_revision=revision,
            )
            result_id = "result-" + fingerprint_value({"project_id": project.project_id, "revision": revision, "scenario_id": scenario.scenario_id, "package_fingerprint": package.package_fingerprint})[:24]
            packages.append(ScenarioPackage(scenario.scenario_id, package, result_id))
        fingerprint = fingerprint_value({"project_id": project.project_id, "revision": revision, "packages": tuple((row.scenario_id, row.package_fingerprint, row.result_id) for row in packages)})
        return ScenarioSetResult(project.project_id, revision, tuple(packages), fingerprint)

    def _load_current(self, expected_revision: int) -> StoredProject:
        expected = _positive_revision(expected_revision)
        current = self._store.load_project(self._project_id)
        if current.revision != expected:
            raise DraftConflictError(
                f"expected revision {expected}, found revision {current.revision}"
            )
        return current

    def _validate_scenario(
        self, project: RefinedBlastProject, scenario: ScenarioDraft
    ) -> tuple[ValidationFinding, ...]:
        rows: list[ValidationFinding] = []
        provider_id = "load_provider"
        try:
            raw_provider_id = scenario.load_provider["provider_id"]
            if not isinstance(raw_provider_id, str):
                raise ValueError("load_provider.provider_id must be a string")
            provider_id = raw_provider_id
            provider_input = scenario.load_provider["provider_input"]
            if not isinstance(provider_input, Mapping):
                raise ValueError("load_provider.provider_input must be a mapping")
            provider = get_load_provider(provider_id)
            context = ProviderContext.from_artifact(
                self._artifact,
                scenario_kind=scenario.scenario_kind,
                available_ids=frozenset(_provider_resource_ids(provider_input)),
            )
            provider_findings = provider.validate(provider_input, context)
            rows.extend(
                _finding(row.severity, provider_id, f"scenario_set.{scenario.scenario_id}.load_provider.provider_input", row.message, "Correct the provider input and revalidate.", row.finding_id)
                for row in provider_findings
            )
            if not any(row.severity == "error" for row in rows):
                assemble_refined_blast_project(replace(project, scenario_set=(scenario,)), self._artifact)
        except (ArithmeticError, LookupError, TypeError, ValueError) as exc:
            rows.append(_finding("error", provider_id, f"scenario_set.{scenario.scenario_id}", _safe_exception_message(exc), "Correct the scenario, module or resource evidence and revalidate.", f"compile-{scenario.scenario_id}"))
        return tuple(rows)

    def _provider_preview(self, scenario: ScenarioDraft) -> Mapping[str, object]:
        provider_id = scenario.load_provider["provider_id"]
        provider_input = scenario.load_provider["provider_input"]
        if not isinstance(provider_id, str) or not isinstance(provider_input, Mapping):
            raise ValueError("provider preview requires a closed load_provider input")
        provider = get_load_provider(provider_id)
        preview_method = getattr(provider, "preview", None)
        if not callable(preview_method):
            raise ValueError(f"provider {provider_id!r} has no public preview path")
        context = ProviderContext.from_artifact(
            self._artifact,
            scenario_kind=scenario.scenario_kind,
            available_ids=frozenset(_provider_resource_ids(provider_input)),
        )
        preview = preview_method(provider_input, context)
        if not isinstance(preview, Mapping):
            raise ValueError("provider preview must be an immutable mapping")
        return preview

    def _unacknowledged(self, validation: ValidationResult) -> tuple[ValidationFinding, ...]:
        result: list[ValidationFinding] = []
        for row in validation.warnings:
            record = self._acknowledgements.get((validation.fingerprint, row.finding_id))
            if record is None or record.finding_content_hash != row.content_hash or record.project_revision != validation.project_revision:
                result.append(row)
        return tuple(result)


def validate_refined_blast_project(
    store: RefinedBlastStore,
    project_id: str,
    artifact: BuildingArtifact,
    *,
    expected_revision: int,
) -> ValidationResult:
    return RefinedBlastService(store, project_id, artifact).validate(
        expected_revision=expected_revision
    )


def compile_scenario_set(
    service: RefinedBlastService,
    *,
    expected_revision: int,
) -> ScenarioSetResult:
    if not isinstance(service, RefinedBlastService):
        raise TypeError("service must be a RefinedBlastService with current acknowledgements")
    return service.compile_scenario_set(expected_revision=expected_revision)


def validate_public_package(
    package: RefinedBlastPackage,
    store: RefinedBlastStore,
    project_id: str,
    artifact: BuildingArtifact,
    *,
    expected_revision: int,
) -> RefinedBlastPackage:
    """Recompute public manifest evidence before a package crosses the service boundary."""

    if not isinstance(package, RefinedBlastPackage):
        raise TypeError("package must be a RefinedBlastPackage")
    if not isinstance(store, RefinedBlastStore):
        raise TypeError("store must be a RefinedBlastStore")
    revision = _positive_revision(expected_revision)
    stored = store.load_project(project_id)
    if stored.revision != revision:
        raise DraftConflictError(
            f"expected revision {revision}, found revision {stored.revision}"
        )
    manifest = package.manifest
    if set(manifest) != _PACKAGE_MANIFEST_KEYS:
        raise ValueError("package manifest evidence schema is not closed")
    if manifest.get("schema_version") != "refined_blast.keyword_package@1":
        raise ValueError("package manifest evidence has unsupported schema_version")
    if package.building_artifact_fingerprint != artifact.fingerprint or manifest.get("building_artifact_fingerprint") != artifact.fingerprint:
        raise ValueError("package manifest evidence does not bind the current building artifact")
    for key, expected in (("solver_ready", False), ("requires_project_review", True), ("engineering_validated", False), ("external_program_started", False)):
        if manifest.get(key) is not expected:
            raise ValueError(f"package manifest evidence must keep {key}={expected!r}")
    include_order = manifest.get("include_order")
    if not isinstance(include_order, Sequence) or isinstance(include_order, (str, bytes, bytearray)) or tuple(include_order) != tuple(path for path in package.files if path != "main.k"):
        raise ValueError("package manifest evidence include_order does not match files")
    parsed_includes = _parse_main_includes(package.files.get("main.k", b""))
    if parsed_includes != tuple(include_order):
        raise ValueError("main.k INCLUDE order or closure does not match manifest evidence")
    raw_rows = manifest.get("files")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes, bytearray)) or len(raw_rows) != len(package.files):
        raise ValueError("package manifest evidence files do not match package bytes")
    expected_rows = tuple(
        {
            "path": path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "byte_count": len(content),
            "line_count": len(content.decode("utf-8").splitlines()),
        }
        for path, content in package.files.items()
    )
    actual_rows = tuple(dict(row) if isinstance(row, Mapping) else {} for row in raw_rows)
    if actual_rows != expected_rows:
        raise ValueError("package manifest evidence file hashes or counts do not match bytes")
    rendered = manifest.get("rendered_counts")
    if not isinstance(rendered, Mapping) or set(rendered) != _RENDERED_COUNT_KEYS:
        raise ValueError("package manifest evidence has no rendered counts")
    for name, value in rendered.items():
        if not isinstance(name, str) or not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > _MAX_PUBLIC_CONTAINER_ITEMS:
            raise ValueError("package manifest evidence contains invalid rendered count")
    for symbol, numeric_id in package.symbol_to_numeric_id.items():
        _bounded_numeric_id(numeric_id, f"package symbol {symbol!r}")
    building_mesh = _parse_keyword_mesh(
        package.files.get("01_building.k", b""), "01_building.k"
    )
    _validate_building_keyword(building_mesh, artifact)
    provider_mesh = _parse_keyword_mesh(
        package.files.get("02_provider.k", b""), "02_provider.k"
    )
    _validate_generated_mesh(provider_mesh, package, "02_provider.k")
    provider_manifest = _provider_manifest(package.files.get("02_provider.k", b""))
    _validate_provider_mesh(provider_mesh, provider_manifest, package, artifact)
    provider_fsi_faces = _provider_fsi_face_count(provider_manifest)
    module_nodes = 0
    module_elements = 0
    for path, content in package.files.items():
        if path in {"main.k", "01_building.k", "02_provider.k"}:
            continue
        mesh = _parse_keyword_mesh(content, path)
        _validate_generated_mesh(mesh, package, path, artifact=artifact)
        module_nodes += len(mesh.nodes)
        module_elements += len(mesh.elements)
        if path.endswith("_support_ground.k"):
            _validate_ground_manifest(content, mesh, package, artifact)
    expected_counts = {
        "building_nodes": len(artifact.mesh.nodes),
        "building_elements": len(artifact.mesh.solids)
        + len(artifact.mesh.shells)
        + len(artifact.mesh.beams),
        "provider_nodes": len(provider_mesh.nodes),
        "provider_elements": len(provider_mesh.elements),
        "provider_fsi_faces": provider_fsi_faces,
        "module_new_nodes": module_nodes,
        "module_new_elements": module_elements,
        "symbolic_ids": len(package.symbol_to_numeric_id),
    }
    for name, expected in expected_counts.items():
        if rendered.get(name) != expected:
            raise ValueError(
                f"package manifest evidence rendered count {name!r} does not match bytes"
            )
    canonical = _canonical_package_for_persisted_project(package, stored, artifact)
    _require_exact_canonical_package(package, canonical)
    return package


def _canonical_package_for_persisted_project(
    package: RefinedBlastPackage,
    stored: StoredProject,
    artifact: BuildingArtifact,
) -> RefinedBlastPackage:
    project = stored.project
    candidates = tuple(
        assemble_refined_blast_project(
            replace(project, scenario_set=(scenario,)), artifact
        )
        for scenario in project.scenario_set
    )
    matches = tuple(
        candidate
        for candidate in candidates
        if candidate.manifest.get("project_fingerprint")
        == package.manifest.get("project_fingerprint")
    )
    if len(matches) != 1:
        raise ValueError(
            "public package does not identify one canonical persisted scenario"
        )
    return matches[0]


def _require_exact_canonical_package(
    package: RefinedBlastPackage, canonical: RefinedBlastPackage
) -> None:
    if tuple(package.files.items()) != tuple(canonical.files.items()):
        raise ValueError("public package files do not match canonical persisted bytes")
    for key in (
        "provider_fingerprint",
        "fragment_fingerprints",
        "dependency_closure",
        "id_allocation",
        "include_order",
    ):
        if thaw_value(package.manifest.get(key)) != thaw_value(
            canonical.manifest.get(key)
        ):
            raise ValueError(f"public package canonical {key} does not match")
    if thaw_value(package.manifest) != thaw_value(canonical.manifest):
        raise ValueError("public package complete manifest is not canonical")
    if dict(package.symbol_to_numeric_id) != dict(canonical.symbol_to_numeric_id):
        raise ValueError("public package ID allocation is not canonical")
    if package.building_artifact_fingerprint != canonical.building_artifact_fingerprint:
        raise ValueError("public package building identity is not canonical")


def _finding(
    severity: str,
    module: str,
    field_path: str,
    message: str,
    correction: str,
    identity: str,
    *,
    evidence: Mapping[str, object] | None = None,
) -> ValidationFinding:
    safe_identity = hashlib.sha256(
        f"{module}|{field_path}|{identity}".encode("utf-8")
    ).hexdigest()[:16]
    return ValidationFinding(f"{module}:{safe_identity}", severity, module, field_path, message, correction, evidence or {})  # type: ignore[arg-type]


def _positive_revision(revision: int) -> int:
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("revision must be a positive integer")
    return revision


def _bounded_public_project_errors(project: RefinedBlastProject) -> tuple[str, ...]:
    try:
        _walk_bounded(_project_semantics(project), "project", frozenset())
    except RecursionError:
        return ("project contains a cyclic public value",)
    except (ArithmeticError, TypeError, ValueError) as exc:
        return (_safe_exception_message(exc),)
    return ()


def _walk_bounded(value: object, path: str, ancestors: frozenset[int]) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must be finite")
        return
    if isinstance(value, int):
        if value.bit_length() > _MAX_PUBLIC_INTEGER_BITS:
            raise ValueError(f"{path} integer exceeds bounded public width")
        return
    if isinstance(value, Mapping):
        if id(value) in ancestors:
            raise ValueError(f"{path} contains a cyclic public value")
        if len(value) > _MAX_PUBLIC_CONTAINER_ITEMS:
            raise ValueError(f"{path} exceeds public container budget")
        next_ancestors = ancestors | {id(value)}
        for key, nested in value.items():
            _walk_bounded(nested, f"{path}.{key}", next_ancestors)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if id(value) in ancestors:
            raise ValueError(f"{path} contains a cyclic public value")
        if len(value) > _MAX_PUBLIC_CONTAINER_ITEMS:
            raise ValueError(f"{path} exceeds public container budget")
        next_ancestors = ancestors | {id(value)}
        for index, nested in enumerate(value):
            _walk_bounded(nested, f"{path}[{index}]", next_ancestors)
        return
    if isinstance(value, bytes):
        if len(value) > _MAX_PUBLIC_CONTAINER_ITEMS:
            raise ValueError(f"{path} exceeds public byte budget")
        return
    raise ValueError(f"{path} contains an unsupported public value")


def _project_semantics(project: RefinedBlastProject) -> Mapping[str, object]:
    return {
        "schema_version": project.schema_version,
        "project_id": project.project_id,
        "building_reference": thaw_value(project.building_reference),
        "building_artifact_fingerprint": project.building_artifact_fingerprint,
        "preset_reference": project.preset_reference,
        "preset_version": project.preset_version,
        "project_overrides": thaw_value(project.project_overrides),
        "expert_extensions": thaw_value(project.expert_extensions),
        "scenario_set": tuple(_scenario_semantics(row) for row in project.scenario_set),
        "confirmation_records": tuple(thaw_value(row) for row in project.confirmation_records),
        "provenance": thaw_value(project.provenance),
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def _scenario_semantics(scenario: ScenarioDraft, *, include_identity: bool = True) -> Mapping[str, object]:
    result = {
        "scenario_kind": scenario.scenario_kind,
        "building_placement": thaw_value(scenario.building_placement),
        "support_and_ground": thaw_value(scenario.support_and_ground),
        "load_provider": thaw_value(scenario.load_provider),
        "blast_source": thaw_value(scenario.blast_source),
        "fluid_domain": thaw_value(scenario.fluid_domain),
        "boundaries": thaw_value(scenario.boundaries),
        "interactions": thaw_value(scenario.interactions),
        "solver_controls": thaw_value(scenario.solver_controls),
        "output_requests": thaw_value(scenario.output_requests),
        "resource_versions": thaw_value(scenario.resource_versions),
    }
    if include_identity:
        result["scenario_id"] = scenario.scenario_id
        result["acknowledged_warning_ids"] = scenario.acknowledged_warning_ids
    return result


def _provider_resource_ids(provider_input: Mapping[str, object]) -> set[str]:
    resources = provider_input.get("resources")
    if not isinstance(resources, Mapping):
        return set()
    result: set[str] = set()
    for row in resources.values():
        if isinstance(row, Mapping) and isinstance(row.get("resource_id"), str) and isinstance(row.get("version"), str):
            result.add(f"resource:{row['resource_id']}@{row['version']}")
    return result


def _reject_duplicate_scenarios(scenarios: Sequence[ScenarioDraft]) -> None:
    fingerprints: dict[str, str] = {}
    for scenario in scenarios:
        fingerprint = fingerprint_value(_scenario_semantics(scenario, include_identity=False))
        if fingerprint in fingerprints:
            raise ValueError(f"duplicate scenario semantics: {fingerprints[fingerprint]!r} and {scenario.scenario_id!r}")
        fingerprints[fingerprint] = scenario.scenario_id


def _cache_key(project: RefinedBlastProject, artifact: BuildingArtifact, package: RefinedBlastPackage, revision: int) -> str:
    return fingerprint_value({
        "revision": revision,
        "project": _project_semantics(project),
        "building": artifact.fingerprint,
        "provider": package.manifest["provider_fingerprint"],
        "modules": package.manifest["fragment_fingerprints"],
        "resources": tuple((row.scenario_id, thaw_value(row.resource_versions), thaw_value(row.load_provider).get("provider_input")) for row in project.scenario_set),
        "adapter": _ADAPTER_FINGERPRINT,
    })


def _safe_exception_message(exc: BaseException) -> str:
    try:
        message = str(exc)
    except BaseException:
        message = exc.__class__.__name__
    return message[:2_000] or exc.__class__.__name__


@dataclass(frozen=True, slots=True)
class _ParsedKeywordMesh:
    nodes: Mapping[int, tuple[float, float, float]]
    elements: tuple[tuple[str, int, int, tuple[int, ...]], ...]


def _parse_main_includes(content: bytes) -> tuple[str, ...]:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("main.k INCLUDE evidence is not UTF-8") from exc
    significant = tuple(
        line.strip() for line in lines if line.strip() and not line.lstrip().startswith("$")
    )
    if not significant or significant[0].upper() != "*KEYWORD" or significant[-1].upper() != "*END":
        raise ValueError("main.k INCLUDE evidence requires *KEYWORD and *END")
    includes: list[str] = []
    index = 1
    while index < len(significant) - 1:
        if significant[index].upper() != "*INCLUDE" or index + 1 >= len(significant) - 1:
            raise ValueError("main.k contains an unsupported record outside INCLUDE closure")
        path = significant[index + 1]
        if path in includes:
            raise ValueError("main.k INCLUDE evidence contains a duplicate")
        includes.append(path)
        index += 2
    return tuple(includes)


def _parse_keyword_mesh(content: bytes, label: str) -> _ParsedKeywordMesh:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} is not UTF-8") from exc
    nodes: dict[int, tuple[float, float, float]] = {}
    elements: list[tuple[str, int, int, tuple[int, ...]]] = []
    section = ""
    allowed = _allowed_include_keywords(label)
    scalar_record_counts: dict[str, int] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("$"):
            continue
        if line.startswith("*"):
            keyword = line.upper()
            if keyword not in allowed:
                raise ValueError(f"{label} contains unknown keyword card {keyword!r}")
            section = keyword
            continue
        if section == "*NODE":
            fields = tuple(field.strip() for field in line.split(","))
            if len(fields) != 4:
                raise ValueError(f"{label} node row must contain ID and three coordinates")
            node_id = _parse_numeric_id(fields[0], f"{label} node ID")
            coordinates = tuple(_parse_finite_float(value, f"{label} node coordinate") for value in fields[1:])
            if node_id in nodes:
                raise ValueError(f"{label} duplicates node ID {node_id}")
            nodes[node_id] = coordinates  # type: ignore[assignment]
        elif section.startswith("*ELEMENT_"):
            fields = tuple(field.strip() for field in line.split(","))
            if len(fields) < 4:
                raise ValueError(f"{label} element row is incomplete")
            element_id = _parse_numeric_id(fields[0], f"{label} element ID")
            part_id = _parse_numeric_id(fields[1], f"{label} part ID")
            node_fields = fields[2:-1] if section == "*ELEMENT_BEAM" else fields[2:]
            node_ids = tuple(
                _parse_numeric_id(value, f"{label} connectivity ID") for value in node_fields
            )
            elements.append((section, element_id, part_id, node_ids))
        elif section in {
            "*CONTROL_TERMINATION",
            "*CONTROL_TIMESTEP",
            "*DATABASE_BINARY_D3PLOT",
            "*DATABASE_BINARY_D3THDT",
        }:
            expected_fields = 2 if section == "*CONTROL_TIMESTEP" else 1
            fields = tuple(field.strip() for field in line.split(","))
            if len(fields) != expected_fields:
                raise ValueError(f"{label} has an invalid {section} record")
            for value in fields:
                _parse_finite_float(value, f"{label} {section} value")
            scalar_record_counts[section] = scalar_record_counts.get(section, 0) + 1
            if scalar_record_counts[section] > 1:
                raise ValueError(f"{label} duplicates {section} record")
        else:
            raise ValueError(f"{label} contains a record outside a known keyword card")
    if len({row[1] for row in elements}) != len(elements):
        raise ValueError(f"{label} contains duplicate element IDs")
    return _ParsedKeywordMesh(nodes, tuple(elements))


def _allowed_include_keywords(label: str) -> frozenset[str]:
    if label == "01_building.k":
        return frozenset(
            {"*NODE", "*ELEMENT_SOLID", "*ELEMENT_SHELL", "*ELEMENT_BEAM"}
        )
    if label == "02_provider.k" or label.endswith("_support_ground.k"):
        return frozenset({"*NODE", "*ELEMENT_SOLID"})
    if label.endswith("_controls.k"):
        return frozenset({"*CONTROL_TERMINATION", "*CONTROL_TIMESTEP"})
    if label.endswith("_outputs.k"):
        return frozenset(
            {"*DATABASE_BINARY_D3PLOT", "*DATABASE_BINARY_D3THDT"}
        )
    return frozenset()


def _validate_building_keyword(
    mesh: _ParsedKeywordMesh, artifact: BuildingArtifact
) -> None:
    expected_nodes = {node.node_id: node.coordinates for node in artifact.mesh.nodes}
    if dict(mesh.nodes) != expected_nodes:
        raise ValueError("building keyword node IDs or coordinates do not match artifact")
    roles = sorted(
        {
            row.part_role
            for row in (*artifact.mesh.solids, *artifact.mesh.shells, *artifact.mesh.beams)
        }
    )
    part_ids = {role: index for index, role in enumerate(roles, start=1)}
    expected_elements = {
        *( ("*ELEMENT_SOLID", row.element_id, part_ids[row.part_role], row.node_ids) for row in artifact.mesh.solids ),
        *( ("*ELEMENT_SHELL", row.element_id, part_ids[row.part_role], row.node_ids) for row in artifact.mesh.shells ),
        *( ("*ELEMENT_BEAM", row.element_id, part_ids[row.part_role], row.node_ids) for row in artifact.mesh.beams ),
    }
    if set(mesh.elements) != expected_elements:
        raise ValueError("building keyword element IDs, parts or connectivity do not match artifact")


def _validate_generated_mesh(
    mesh: _ParsedKeywordMesh,
    package: RefinedBlastPackage,
    label: str,
    *,
    artifact: BuildingArtifact | None = None,
) -> None:
    allocated = set(package.symbol_to_numeric_id.values())
    external_nodes = set(node.node_id for node in artifact.mesh.nodes) if artifact else set()
    if not set(mesh.nodes) <= allocated | external_nodes:
        raise ValueError(f"{label} node IDs are outside declared symbol allocation")
    for _, element_id, part_id, node_ids in mesh.elements:
        if element_id not in allocated or part_id not in allocated:
            raise ValueError(f"{label} element or part ID is outside declared symbol allocation")
        if not set(node_ids) <= set(mesh.nodes) | external_nodes:
            raise ValueError(f"{label} element connectivity is not closed")


def _provider_manifest(content: bytes) -> Mapping[str, object]:
    for line in content.decode("utf-8").splitlines():
        if line.startswith("$ {"):
            value = json.loads(line[2:])
            if not isinstance(value, Mapping):
                break
            return value
    raise ValueError("provider include has no closed manifest evidence")


def _validate_provider_mesh(
    mesh: _ParsedKeywordMesh,
    manifest: Mapping[str, object],
    package: RefinedBlastPackage,
    artifact: BuildingArtifact,
) -> None:
    provider_id = manifest.get("provider_id")
    if provider_id not in {
        "explicit_ale_fsi",
        "lbe_segment",
        "imported_pressure_history",
        "solver_complete_ale_fsi",
    }:
        raise ValueError("provider include has unsupported manifest identity")
    if set(manifest) != _PROVIDER_MANIFEST_KEYS[provider_id]:
        raise ValueError("provider include manifest schema is not closed")
    if manifest.get("building_artifact_fingerprint") != artifact.fingerprint:
        raise ValueError("provider manifest does not bind the building artifact")
    if manifest.get("topology_fingerprint") != artifact.topology_manifest.get(
        "fingerprint"
    ):
        raise ValueError("provider manifest does not bind the building topology")
    for key, expected in (
        ("solver_ready", False),
        ("requires_project_review", True),
        ("engineering_validated", False),
        ("external_program_started", False),
    ):
        if manifest.get(key) is not expected:
            raise ValueError(f"provider manifest must keep {key}={expected!r}")
    _validate_provider_faces(manifest, artifact)
    if provider_id != "explicit_ale_fsi":
        if mesh.nodes or mesh.elements:
            raise ValueError(f"provider {provider_id} mesh must be empty")
        return

    allocation = manifest.get("allocation")
    actual = allocation.get("actual") if isinstance(allocation, Mapping) else None
    counts = actual.get("axis_point_counts") if isinstance(actual, Mapping) else None
    if (
        not isinstance(counts, Sequence)
        or isinstance(counts, (str, bytes, bytearray))
        or len(counts) != 3
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 2
            for value in counts
        )
    ):
        raise ValueError("explicit provider mesh has invalid declared axis counts")
    nx, ny, nz = counts
    node_symbols = {
        (ix, iy, iz): f"explicit_ale_fsi:node:{ix}:{iy}:{iz}"
        for ix in range(nx)
        for iy in range(ny)
        for iz in range(nz)
    }
    element_symbols = {
        (ix, iy, iz): f"explicit_ale_fsi:solid:{ix}:{iy}:{iz}"
        for ix in range(nx - 1)
        for iy in range(ny - 1)
        for iz in range(nz - 1)
    }
    symbol_map = package.symbol_to_numeric_id
    if not set(node_symbols.values()) <= set(symbol_map) or not set(
        element_symbols.values()
    ) <= set(symbol_map):
        raise ValueError("explicit provider mesh symbol allocation is incomplete")
    expected_node_ids = {
        index: symbol_map[symbol] for index, symbol in node_symbols.items()
    }
    if set(mesh.nodes) != set(expected_node_ids.values()):
        raise ValueError("explicit provider mesh node IDs do not match allocation")
    axes = (
        tuple(mesh.nodes[expected_node_ids[(ix, 0, 0)]][0] for ix in range(nx)),
        tuple(mesh.nodes[expected_node_ids[(0, iy, 0)]][1] for iy in range(ny)),
        tuple(mesh.nodes[expected_node_ids[(0, 0, iz)]][2] for iz in range(nz)),
    )
    if any(
        not all(axis[index] < axis[index + 1] for index in range(len(axis) - 1))
        for axis in axes
    ):
        raise ValueError("explicit provider mesh axes must be strictly increasing")
    for (ix, iy, iz), numeric_id in expected_node_ids.items():
        if mesh.nodes[numeric_id] != (axes[0][ix], axes[1][iy], axes[2][iz]):
            raise ValueError("explicit provider mesh node coordinates are not structured")
    excluded = set(node_symbols.values()) | set(element_symbols.values())
    part_candidates = tuple(
        symbol
        for symbol in sorted(symbol_map)
        if symbol not in excluded
        and (
            symbol.startswith("charge:")
            or symbol.startswith("estimate:")
            or symbol.startswith("explicit_ale_fsi:evidence:")
        )
    )
    if not part_candidates:
        raise ValueError("explicit provider mesh has no declared part allocation")
    part_id = symbol_map[part_candidates[0]]
    expected_elements = set()
    for (ix, iy, iz), symbol in element_symbols.items():
        corners = (
            (ix, iy, iz),
            (ix + 1, iy, iz),
            (ix + 1, iy + 1, iz),
            (ix, iy + 1, iz),
            (ix, iy, iz + 1),
            (ix + 1, iy, iz + 1),
            (ix + 1, iy + 1, iz + 1),
            (ix, iy + 1, iz + 1),
        )
        expected_elements.add(
            (
                "*ELEMENT_SOLID",
                symbol_map[symbol],
                part_id,
                tuple(expected_node_ids[index] for index in corners),
            )
        )
    if set(mesh.elements) != expected_elements:
        raise ValueError("explicit provider mesh connectivity does not match structure")
    if actual.get("node_count") != len(mesh.nodes) or actual.get(
        "element_count"
    ) != len(mesh.elements):
        raise ValueError("explicit provider mesh counts do not match manifest")


def _validate_provider_faces(
    manifest: Mapping[str, object], artifact: BuildingArtifact
) -> None:
    provider_id = manifest["provider_id"]
    if provider_id == "explicit_ale_fsi":
        nested = manifest.get("fsi")
        rows = nested.get("face_ids") if isinstance(nested, Mapping) else None
    elif provider_id == "lbe_segment":
        nested = manifest.get("selection")
        included = nested.get("included_faces") if isinstance(nested, Mapping) else None
        rows = (
            tuple(row.get("face_id") for row in included)
            if isinstance(included, Sequence)
            and not isinstance(included, (str, bytes, bytearray))
            and all(isinstance(row, Mapping) for row in included)
            else None
        )
    elif provider_id == "solver_complete_ale_fsi":
        rows = manifest.get("fsi_face_ids")
    else:
        nested = manifest.get("mapping")
        rows = nested.get("target_face_ids") if isinstance(nested, Mapping) else None
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise ValueError("provider manifest has invalid target faces")
    face_ids = tuple(rows)
    if any(not isinstance(face_id, str) or not face_id for face_id in face_ids):
        raise ValueError("provider manifest has invalid target face ID")
    if len(face_ids) != len(set(face_ids)):
        raise ValueError("provider manifest has duplicate target face IDs")
    catalog = {
        row["face_id"]: (row, category)
        for category in (
            "exterior_surfaces",
            "interior_cavity_surfaces",
            "ground_contact_surfaces",
            "unclassified_boundary_surfaces",
        )
        for row in artifact.surface_catalog.get(category, ())
        if isinstance(row, Mapping) and isinstance(row.get("face_id"), str)
    }
    if not set(face_ids) <= set(catalog):
        raise ValueError("provider manifest target faces are outside the artifact catalog")
    geometry: dict[str, tuple[int, str, float]] = {}
    for face_id in face_ids:
        row, category = catalog[face_id]
        area, _, _ = surface_geometry_from_artifact(
            artifact, row, f"provider target face {face_id!r}"
        )
        element_id = row.get("element_id")
        if isinstance(element_id, bool) or not isinstance(element_id, int):
            raise ValueError("provider target face has invalid catalog element ID")
        geometry[face_id] = (element_id, category, area)
    if provider_id == "solver_complete_ale_fsi":
        if face_ids:
            raise ValueError("solver-complete neutral provider faces must be deferred to generation")
        return
    if provider_id == "explicit_ale_fsi":
        assert isinstance(nested, Mapping)
        if set(nested) != {
            "surface_categories", "face_ids", "structural_element_ids", "catalog_only"
        } or nested.get("catalog_only") is not True:
            raise ValueError("explicit provider FSI manifest schema is not closed")
        categories = nested.get("surface_categories")
        element_ids = nested.get("structural_element_ids")
        if (
            not isinstance(categories, Sequence)
            or isinstance(categories, (str, bytes, bytearray))
            or not isinstance(element_ids, Sequence)
            or isinstance(element_ids, (str, bytes, bytearray))
            or tuple(element_ids)
            != tuple(f"building:element:{geometry[row][0]}" for row in face_ids)
            or any(geometry[row][1] not in categories for row in face_ids)
        ):
            raise ValueError("explicit provider FSI faces do not match artifact geometry")
    elif provider_id == "lbe_segment":
        assert isinstance(nested, Mapping)
        included = nested.get("included_faces")
        if set(nested) != {
            "occlusion_policy", "candidate_face_ids", "included_faces", "total_area_m2"
        } or not isinstance(included, Sequence) or isinstance(
            included, (str, bytes, bytearray)
        ):
            raise ValueError("LBE provider selection manifest schema is not closed")
        included_areas: list[float] = []
        for row in included:
            if not isinstance(row, Mapping) or set(row) != {
                "face_id", "element_id", "category", "area_m2", "range_m", "reason"
            }:
                raise ValueError("LBE included face manifest schema is not closed")
            face_id = row["face_id"]
            element_id, category, area = geometry[face_id]
            if (
                row.get("element_id") != element_id
                or row.get("category") != category
                or not math.isclose(
                    _finite_public_number(row.get("area_m2"), "LBE included area"),
                    area,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                or _finite_public_number(row.get("range_m"), "LBE included range") <= 0.0
                or not isinstance(row.get("reason"), str)
                or not row["reason"]
            ):
                raise ValueError("LBE included face does not match artifact geometry")
            included_areas.append(area)
        if not math.isclose(
            _finite_public_number(nested.get("total_area_m2"), "LBE total area"),
            math.fsum(included_areas),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("LBE total area does not match artifact geometry")
    else:
        assert isinstance(nested, Mapping)
        if set(nested) != {
            "surface_category", "target_face_ids", "target_element_ids",
            "target_total_area_m2",
        }:
            raise ValueError("imported provider mapping manifest schema is not closed")
        element_ids = nested.get("target_element_ids")
        if (
            not isinstance(element_ids, Sequence)
            or isinstance(element_ids, (str, bytes, bytearray))
            or tuple(element_ids) != tuple(geometry[row][0] for row in face_ids)
            or any(geometry[row][1] != nested.get("surface_category") for row in face_ids)
        ):
            raise ValueError("imported provider targets do not match artifact geometry")
        if not math.isclose(
            _finite_public_number(
                nested.get("target_total_area_m2"), "imported target total area"
            ),
            math.fsum(geometry[row][2] for row in face_ids),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("imported provider area does not match artifact geometry")


def _module_preview_payloads(
    package: RefinedBlastPackage,
    artifact: BuildingArtifact,
    provider_preview: Mapping[str, object],
) -> Mapping[str, Mapping[str, object]]:
    payloads: dict[str, Mapping[str, object]] = {}
    for module_id in ("fluid_domain", "boundaries", "support_ground"):
        suffix = f"_{module_id}.k"
        matches = tuple(
            (path, content)
            for path, content in package.files.items()
            if path.endswith(suffix)
        )
        if not matches:
            payloads[module_id] = {}
            continue
        if len(matches) != 1:
            raise ValueError(f"preview has duplicate {module_id} includes")
        path, content = matches[0]
        manifest = _module_manifest(content, path)
        roles, connections = _typed_fragment_records(content, path)
        if module_id == "fluid_domain":
            regions = _fluid_preview_regions(manifest, artifact, provider_preview)
            payload: Mapping[str, object] = {
                "manifest": manifest,
                "regions": regions,
                "openings": artifact.normalized_input.get("openings", ()),
                "roles": roles,
                "connections": connections,
            }
        elif module_id == "boundaries":
            assignments = manifest.get("assignments")
            if not isinstance(assignments, Sequence) or isinstance(
                assignments, (str, bytes, bytearray)
            ):
                raise ValueError("boundary preview assignments are invalid")
            face_ids = {
                row[1]
                for row in assignments
                if isinstance(row, Sequence)
                and not isinstance(row, (str, bytes, bytearray))
                and len(row) >= 2
                and isinstance(row[1], str)
            }
            surfaces = tuple(
                row
                for category in (
                    "exterior_surfaces",
                    "interior_cavity_surfaces",
                    "ground_contact_surfaces",
                    "unclassified_boundary_surfaces",
                )
                for row in artifact.surface_catalog.get(category, ())
                if isinstance(row, Mapping) and row.get("face_id") in face_ids
            )
            payload = {
                "manifest": manifest,
                "surfaces": surfaces,
                "roles": roles,
                "connections": connections,
            }
        else:
            mesh = _parse_keyword_mesh(content, path)
            payload = {
                "manifest": manifest,
                "nodes": tuple(
                    {"node_id": node_id, "coordinates_m": coordinates}
                    for node_id, coordinates in sorted(mesh.nodes.items())
                ),
                "elements": tuple(
                    {
                        "keyword": keyword,
                        "element_id": element_id,
                        "part_id": part_id,
                        "node_ids": node_ids,
                    }
                    for keyword, element_id, part_id, node_ids in mesh.elements
                ),
                "support_surfaces": tuple(
                    row
                    for row in artifact.surface_catalog.get("ground_contact_surfaces", ())
                    if isinstance(row, Mapping)
                    and row.get("face_id") in set(manifest.get("support_face_ids", ()))
                ),
                "roles": roles,
                "connections": connections,
            }
        _walk_bounded(payload, f"preview.{module_id}", frozenset())
        payloads[module_id] = payload
    return payloads


def _module_manifest(content: bytes, path: str) -> Mapping[str, object]:
    for line in content.decode("utf-8").splitlines():
        if line.startswith("$ manifest="):
            value = json.loads(line[len("$ manifest="):])
            if isinstance(value, Mapping):
                return value
    raise ValueError(f"{path} has no closed module manifest")


def _typed_fragment_records(
    content: bytes, path: str
) -> tuple[tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]:
    roles: list[Mapping[str, object]] = []
    connections: list[Mapping[str, object]] = []
    target: list[Mapping[str, object]] | None = None
    role_keys = frozenset(
        {"participant_id", "role", "kind", "member_ids", "numeric_id"}
    )
    connection_keys = frozenset(
        {
            "interface_id",
            "kind",
            "source_participant_id",
            "target_participant_id",
            "member_ids",
            "shared_node_ids",
            "master_member_ids",
            "slave_member_ids",
            "numeric_id",
        }
    )
    for line in content.decode("utf-8").splitlines():
        if line == "$ typed_participants":
            target = roles
            continue
        if line == "$ typed_interfaces":
            target = connections
            continue
        if line == "$ symbolic_id,numeric_id":
            target = None
            continue
        if target is None or not line.startswith("$ {"):
            continue
        value = json.loads(line[2:])
        expected = role_keys if target is roles else connection_keys
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ValueError(f"{path} contains an unclosed typed preview record")
        target.append(value)
    return tuple(roles), tuple(connections)


def _fluid_preview_regions(
    manifest: Mapping[str, object],
    artifact: BuildingArtifact,
    provider_preview: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    spaces = {
        row["id"]: row["bounds_m"]
        for row in artifact.topology_manifest.get("void_regions", ())
        if isinstance(row, Mapping)
        and isinstance(row.get("id"), str)
        and isinstance(row.get("bounds_m"), Sequence)
    }
    rows: list[Mapping[str, object]] = [
        {"region_id": space_id, "bounds_m": spaces[space_id], "kind": "interior_cavity"}
        for space_id in manifest.get("included_space_ids", ())
        if space_id in spaces
    ]
    if manifest.get("external_buffer_included") is True:
        provider_bounds = provider_preview.get("domain_bounds_m")
        if isinstance(provider_bounds, Sequence) and not isinstance(
            provider_bounds, (str, bytes, bytearray)
        ) and len(provider_bounds) == 6:
            bounds = tuple(provider_bounds)
            source = "provider"
        else:
            envelope = artifact.topology_manifest.get("envelope_bounds_m")
            buffer = manifest.get("external_buffer_m")
            if not isinstance(envelope, Sequence) or len(envelope) != 6 or not isinstance(buffer, (int, float)):
                raise ValueError("fluid preview cannot derive a bounded external region")
            bounds = tuple(
                float(envelope[index]) + (-float(buffer) if index < 3 else float(buffer))
                for index in range(6)
            )
            source = "topology_plus_declared_buffer"
        rows.append({"region_id": "exterior_buffer", "bounds_m": bounds, "kind": source})
    return tuple(rows)


def _provider_fsi_face_count(manifest: Mapping[str, object]) -> int:
    provider_id = manifest.get("provider_id")
    if provider_id == "explicit_ale_fsi":
        nested = manifest.get("fsi")
        rows = nested.get("face_ids") if isinstance(nested, Mapping) else None
    elif provider_id == "lbe_segment":
        nested = manifest.get("selection")
        rows = nested.get("included_faces") if isinstance(nested, Mapping) else None
    elif provider_id == "imported_pressure_history":
        nested = manifest.get("mapping")
        rows = nested.get("target_face_ids") if isinstance(nested, Mapping) else None
    elif provider_id == "solver_complete_ale_fsi":
        rows = manifest.get("fsi_face_ids")
    else:
        raise ValueError("provider include has unsupported manifest identity")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise ValueError("provider include has invalid FSI face evidence")
    return len(rows)


def _validate_ground_manifest(
    content: bytes,
    mesh: _ParsedKeywordMesh,
    package: RefinedBlastPackage,
    artifact: BuildingArtifact,
) -> None:
    manifest: Mapping[str, object] | None = None
    for line in content.decode("utf-8").splitlines():
        if line.startswith("$ manifest="):
            value = json.loads(line[len("$ manifest="):])
            if isinstance(value, Mapping):
                manifest = value
            break
    if manifest is None or not isinstance(manifest.get("ground_geometry"), Mapping):
        raise ValueError("support/ground include has no closed geometry manifest")
    geometry = manifest["ground_geometry"]
    assert isinstance(geometry, Mapping)
    raw_nodes = geometry.get("nodes")
    raw_elements = geometry.get("elements")
    if not isinstance(raw_nodes, Sequence) or not isinstance(raw_elements, Sequence):
        raise ValueError("support/ground include geometry manifest is invalid")
    symbol_map = package.symbol_to_numeric_id
    expected_nodes: dict[int, tuple[float, float, float]] = {}
    for row in raw_nodes:
        if (
            not isinstance(row, Mapping)
            or not isinstance(row.get("node_id"), str)
            or not isinstance(row.get("coordinates_m"), Sequence)
            or isinstance(row.get("coordinates_m"), (str, bytes, bytearray))
            or len(row["coordinates_m"]) != 3
        ):
            raise ValueError("support/ground node manifest is invalid")
        symbol = row["node_id"]
        coordinates = tuple(
            _finite_public_number(value, "support/ground node coordinate")
            for value in row["coordinates_m"]
        )
        if symbol in symbol_map:
            expected_nodes[symbol_map[symbol]] = coordinates  # type: ignore[assignment]
        elif symbol.startswith("building:node:"):
            node_id = _parse_numeric_id(symbol.rsplit(":", 1)[1], "support/ground building node")
            if node_id not in {node.node_id for node in artifact.mesh.nodes}:
                raise ValueError("support/ground manifest references an unknown building node")
            expected_nodes[node_id] = coordinates  # type: ignore[assignment]
        else:
            raise ValueError("support/ground manifest node is not allocated")
    roles, _ = _typed_fragment_records(content, "support/ground include")
    ground_roles = tuple(
        row
        for row in roles
        if row.get("role") == "ground_support"
        and row.get("kind") == "ground_mesh"
        and isinstance(row.get("numeric_id"), int)
    )
    if len(ground_roles) != 1:
        raise ValueError("support/ground include has no exact ground mesh role")
    part_id = _bounded_numeric_id(
        ground_roles[0]["numeric_id"], "support/ground part ID"  # type: ignore[arg-type]
    )
    expected_elements: set[tuple[str, int, int, tuple[int, ...]]] = set()
    for row in raw_elements:
        if (
            not isinstance(row, Mapping)
            or row.get("element_id") not in symbol_map
            or not isinstance(row.get("node_ids"), Sequence)
            or isinstance(row.get("node_ids"), (str, bytes, bytearray))
            or len(row["node_ids"]) != 8
        ):
            raise ValueError("support/ground element manifest is invalid")
        try:
            node_ids = tuple(
                symbol_map[value]
                if value in symbol_map
                else _parse_numeric_id(
                    str(value).rsplit(":", 1)[1], "support/ground connectivity ID"
                )
                if isinstance(value, str) and value.startswith("building:node:")
                else None
                for value in row["node_ids"]
            )
        except (IndexError, TypeError) as exc:
            raise ValueError("support/ground element manifest is invalid") from exc
        if any(value is None for value in node_ids):
            raise ValueError("support/ground element manifest has unresolved connectivity")
        expected_elements.add(
            (
                "*ELEMENT_SOLID",
                symbol_map[row["element_id"]],
                part_id,
                node_ids,  # type: ignore[arg-type]
            )
        )
    if dict(mesh.nodes) != expected_nodes or set(mesh.elements) != expected_elements:
        raise ValueError("support/ground include does not match declared geometry manifest")


def _parse_numeric_id(value: str, path: str) -> int:
    if not value or not value.isdecimal():
        raise ValueError(f"{path} must be a bounded positive integer ID")
    return _bounded_numeric_id(int(value), path)


def _bounded_numeric_id(value: int, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= _MAX_LSDYNA_ID:
        raise ValueError(f"{path} must be a bounded positive integer ID")
    return value


def _parse_finite_float(value: str, path: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise ValueError(f"{path} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{path} must be finite")
    return result


def _finite_public_number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{path} must be finite")
    return result


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "RefinedBlastService",
    "ScenarioPackage",
    "ScenarioSetResult",
    "WarningAcknowledgement",
    "compile_scenario_set",
    "validate_public_package",
    "validate_refined_blast_project",
]
