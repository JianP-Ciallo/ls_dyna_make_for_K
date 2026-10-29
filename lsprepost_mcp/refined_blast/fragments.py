"""Immutable, symbolic fragments shared by Phase 18E scenario modules."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, TypeAlias

from .contracts import ScenarioDraft
from .providers.common import (
    FrozenMapping,
    ProviderContext,
    ProviderFragment,
    fingerprint_value,
    freeze_value,
    thaw_value,
    validate_source_space,
)


_DEFAULT_FLAGS = {
    "solver_ready": False,
    "requires_project_review": True,
    "engineering_validated": False,
}
_MODULE_BUDGET_HARD_LIMIT = 10_000_000
_PARTICIPANT_ROLES = frozenset(
    {
        "fluid_domain",
        "building_structure",
        "ground_support",
        "boundary_surface",
        "blast_source",
    }
)
_PARTICIPANT_KINDS = frozenset(
    {
        "fluid_mesh",
        "fluid_region",
        "structural_mesh",
        "ground_mesh",
        "support_definition",
        "exterior_surface_set",
        "interior_surface_set",
        "ground_contact_surface_set",
        "unclassified_surface_set",
        "provider_source",
    }
)
_INTERFACE_KINDS = frozenset(
    {
        "fsi",
        "fsi_candidate_surface",
        "support_shared_node",
        "support_tied",
        "boundary_non_reflecting",
        "boundary_rigid",
    }
)


@dataclass(frozen=True, slots=True)
class FragmentParticipant:
    """Typed resource owner; roles are never inferred from identifier text."""

    participant_id: str
    role: str
    kind: str
    member_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "participant_id", _require_token(self.participant_id, "participant_id"))
        if self.role not in _PARTICIPANT_ROLES:
            raise ValueError(f"unsupported participant role: {self.role!r}")
        if self.kind not in _PARTICIPANT_KINDS:
            raise ValueError(f"unsupported participant kind: {self.kind!r}")
        members = frozenset(
            _require_token(value, "participant.member_id") for value in self.member_ids
        )
        if self.participant_id in members:
            raise ValueError("participant cannot own its participant_id as a member")
        object.__setattr__(self, "member_ids", members)

    def to_manifest(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "participant_id": self.participant_id,
                "role": self.role,
                "kind": self.kind,
                "member_ids": tuple(sorted(self.member_ids)),
            }
        )


@dataclass(frozen=True, slots=True)
class FragmentInterface:
    """Directed typed relation with explicit support coupling membership."""

    interface_id: str
    kind: str
    source_participant_id: str
    target_participant_id: str
    member_ids: frozenset[str] = frozenset()
    shared_node_ids: tuple[str, ...] = ()
    master_member_ids: tuple[str, ...] = ()
    slave_member_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "interface_id", _require_token(self.interface_id, "interface_id"))
        if self.kind not in _INTERFACE_KINDS:
            raise ValueError(f"unsupported interface kind: {self.kind!r}")
        source = _require_token(self.source_participant_id, "interface.source_participant_id")
        target = _require_token(self.target_participant_id, "interface.target_participant_id")
        if source == target:
            raise ValueError("interface source and target participants must differ")
        object.__setattr__(self, "source_participant_id", source)
        object.__setattr__(self, "target_participant_id", target)
        members = frozenset(_require_token(value, "interface.member_id") for value in self.member_ids)
        shared = _unique_tokens(self.shared_node_ids, "interface.shared_node_ids")
        master = _unique_tokens(self.master_member_ids, "interface.master_member_ids")
        slave = _unique_tokens(self.slave_member_ids, "interface.slave_member_ids")
        if self.kind == "support_shared_node":
            if not shared or master or slave:
                raise ValueError("shared-node support requires only explicit shared_node_ids")
        elif self.kind == "support_tied":
            if shared or not master or not slave:
                raise ValueError("tied support requires explicit master and slave members")
        elif shared or master or slave:
            raise ValueError(f"{self.kind} interface cannot carry support coupling fields")
        object.__setattr__(self, "member_ids", members)
        object.__setattr__(self, "shared_node_ids", shared)
        object.__setattr__(self, "master_member_ids", master)
        object.__setattr__(self, "slave_member_ids", slave)

    def to_manifest(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "interface_id": self.interface_id,
                "kind": self.kind,
                "source_participant_id": self.source_participant_id,
                "target_participant_id": self.target_participant_id,
                "member_ids": tuple(sorted(self.member_ids)),
                "shared_node_ids": self.shared_node_ids,
                "master_member_ids": self.master_member_ids,
                "slave_member_ids": self.slave_member_ids,
            }
        )


@dataclass(frozen=True, slots=True)
class KeywordFragment:
    """A neutral module result with symbolic, not numeric, resource IDs."""

    module_id: str
    declared_ids: frozenset[str]
    required_ids: frozenset[str]
    estimates: FrozenMapping
    manifest: FrozenMapping
    participants: tuple[FragmentParticipant, ...] = ()
    interfaces: tuple[FragmentInterface, ...] = ()
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        _require_token(self.module_id, "module_id")
        declared = frozenset(_require_token(value, "declared_id") for value in self.declared_ids)
        required = frozenset(_require_token(value, "required_id") for value in self.required_ids)
        if declared & required:
            raise ValueError("fragment declared_ids and required_ids must be disjoint")
        participants = tuple(self.participants)
        interfaces = tuple(self.interfaces)
        participant_ids = tuple(row.participant_id for row in participants)
        interface_ids = tuple(row.interface_id for row in interfaces)
        if len(participant_ids) != len(set(participant_ids)):
            raise ValueError("fragment contains duplicate participant id")
        if len(interface_ids) != len(set(interface_ids)):
            raise ValueError("fragment contains duplicate interface id")
        cross_kind_ids = set(participant_ids) & set(interface_ids)
        if cross_kind_ids:
            raise ValueError(
                "participant and interface IDs share one global symbol namespace: "
                f"{sorted(cross_kind_ids)[0]!r}"
            )
        universe = declared | required
        typed_ids = {
            *(row.participant_id for row in participants),
            *(member for row in participants for member in row.member_ids),
            *(row.interface_id for row in interfaces),
            *(row.source_participant_id for row in interfaces),
            *(row.target_participant_id for row in interfaces),
            *(member for row in interfaces for member in row.member_ids),
            *(member for row in interfaces for member in row.shared_node_ids),
            *(member for row in interfaces for member in row.master_member_ids),
            *(member for row in interfaces for member in row.slave_member_ids),
        }
        missing_typed_ids = typed_ids - universe
        if missing_typed_ids:
            raise ValueError(f"unclosed typed record id: {sorted(missing_typed_ids)[0]!r}")
        object.__setattr__(self, "declared_ids", declared)
        object.__setattr__(self, "required_ids", required)
        object.__setattr__(self, "participants", participants)
        object.__setattr__(self, "interfaces", interfaces)
        estimates = freeze_value(self.estimates, "estimates")
        manifest = freeze_value({**_DEFAULT_FLAGS, **dict(self.manifest)}, "manifest")
        assert isinstance(estimates, Mapping)
        assert isinstance(manifest, Mapping)
        if manifest["solver_ready"] is not False:
            raise ValueError("Phase 18E fragments must keep solver_ready=false")
        if manifest["requires_project_review"] is not True:
            raise ValueError("Phase 18E fragments require project review")
        if manifest["engineering_validated"] is not False:
            raise ValueError("Phase 18E fragments cannot claim engineering validation")
        object.__setattr__(self, "estimates", estimates)
        object.__setattr__(self, "manifest", manifest)
        object.__setattr__(
            self,
            "fingerprint",
            fingerprint_value(
                {
                    "module_id": self.module_id,
                    "declared_ids": sorted(declared),
                    "required_ids": sorted(required),
                    "estimates": estimates,
                    "manifest": manifest,
                    "participants": tuple(row.to_manifest() for row in participants),
                    "interfaces": tuple(row.to_manifest() for row in interfaces),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ScenarioModuleContext:
    """Immutable input boundary for small, independently compiled modules."""

    draft: ScenarioDraft
    provider_context: ProviderContext
    provider_fragment: ProviderFragment
    prior_fragments: tuple[KeywordFragment, ...] = ()

    def __post_init__(self) -> None:
        if self.draft.scenario_kind != self.provider_context.scenario_kind:
            raise ValueError("draft and provider context scenario kinds must match")
        if self.provider_fragment.provider_id != self.draft.load_provider["provider_id"]:
            raise ValueError("draft and provider fragment provider identities must match")
        if self.provider_context.artifact.fingerprint not in self.provider_context.available_ids:
            # The public context uses a namespaced artifact identifier.
            if f"artifact:{self.provider_context.artifact.fingerprint}" not in self.provider_context.available_ids:
                raise ValueError("provider context must expose the building artifact")
        manifest = self.provider_fragment.manifest
        if manifest.get("provider_id") != self.provider_fragment.provider_id:
            raise ValueError("provider fragment manifest identity does not match")
        if manifest.get("scenario_kind") != self.draft.scenario_kind:
            raise ValueError("provider fragment scenario kind does not match draft")
        if manifest.get("building_artifact_fingerprint") != self.provider_context.artifact.fingerprint:
            raise ValueError("provider fragment artifact fingerprint does not match context")
        provider_input = self.draft.load_provider.get("provider_input")
        if provider_input is not None and fingerprint_value(provider_input) != fingerprint_value(
            self.provider_fragment.normalized_input
        ):
            raise ValueError("provider fragment normalized input does not match the persisted draft")
        unresolved = self.provider_fragment.required_ids - (
            self.provider_context.available_ids | self.provider_fragment.declared_ids
        )
        if unresolved:
            raise ValueError(f"provider fragment has unresolved requirement: {sorted(unresolved)[0]!r}")
        evidence_sources = {
            source_id
            for evidence in self.provider_fragment.evidence
            for source_id in evidence.source_ids
        }
        unresolved_evidence = evidence_sources - (
            self.provider_context.available_ids | self.provider_fragment.declared_ids
        )
        if unresolved_evidence:
            raise ValueError(
                f"provider evidence has unresolved source id: {sorted(unresolved_evidence)[0]!r}"
            )
        self._provider_source_space_claim()
        object.__setattr__(self, "prior_fragments", tuple(self.prior_fragments))
        module_ids = tuple(fragment.module_id for fragment in self.prior_fragments)
        if len(module_ids) != len(set(module_ids)):
            raise ValueError("prior fragments must have unique module identities")
        participant_owners: dict[str, str] = {}
        interface_owners: dict[str, str] = {}
        member_owners: dict[str, str] = {}
        interface_endpoints: list[tuple[str, str, str]] = []
        for fragment in self.prior_fragments:
            for participant in fragment.participants:
                previous = participant_owners.get(participant.participant_id)
                if previous is not None:
                    raise ValueError(
                        f"typed participant is duplicated or conflicts: {participant.participant_id!r}"
                    )
                participant_owners[participant.participant_id] = fragment.module_id
                for member_id in participant.member_ids:
                    previous_member = member_owners.get(member_id)
                    if previous_member is not None:
                        raise ValueError(f"conflicting member id: {member_id!r}")
                    member_owners[member_id] = participant.participant_id
            for interface in fragment.interfaces:
                previous = interface_owners.get(interface.interface_id)
                if previous is not None:
                    raise ValueError(
                        f"typed interface is duplicated or conflicts: {interface.interface_id!r}"
                    )
                interface_owners[interface.interface_id] = fragment.module_id
                interface_endpoints.append(
                    (
                        interface.interface_id,
                        interface.source_participant_id,
                        interface.target_participant_id,
                    )
                )
        for interface_id, source_id, target_id in interface_endpoints:
            if source_id not in participant_owners or target_id not in participant_owners:
                raise ValueError(
                    f"typed interface references an unknown participant: {interface_id!r}"
                )
        cross_kind_ids = set(participant_owners) & set(interface_owners)
        if cross_kind_ids:
            raise ValueError(
                "participant and interface IDs collide in the global symbol namespace: "
                f"{sorted(cross_kind_ids)[0]!r}"
            )

    @classmethod
    def from_draft(
        cls,
        draft: ScenarioDraft,
        provider_context: ProviderContext,
        provider_fragment: ProviderFragment,
    ) -> "ScenarioModuleContext":
        return cls(draft=draft, provider_context=provider_context, provider_fragment=provider_fragment)

    @property
    def available_ids(self) -> frozenset[str]:
        return frozenset(
            set(self.provider_context.available_ids)
            | set(self.provider_fragment.declared_ids)
            | {item for fragment in self.prior_fragments for item in fragment.declared_ids}
        )

    def prior_fragment(self, module_id: str) -> KeywordFragment:
        for fragment in self.prior_fragments:
            if fragment.module_id == module_id:
                return fragment
        raise ValueError(f"required prior fragment is missing: {module_id}")

    @property
    def provider_source_space_id(self) -> str:
        """Return the single standardized, topology-closed provider source space."""

        return self._provider_source_space_claim()["source_space_id"]  # type: ignore[return-value]

    @property
    def provider_source_declared_id(self) -> str:
        return self._provider_source_space_claim()["source_declared_id"]  # type: ignore[return-value]

    def _provider_source_space_claim(self) -> Mapping[str, object]:
        rows = tuple(
            evidence
            for evidence in self.provider_fragment.evidence
            if evidence.evidence_kind == "provider_source_space"
        )
        if len(rows) != 1:
            raise ValueError("provider source-space evidence must contain exactly one standardized claim")
        claims = rows[0].claims
        expected = frozenset(
            {
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
        )
        closed_mapping(claims, expected, "provider_source_space.claims")
        require_literal(
            claims,
            "schema_version",
            "provider_source_space_evidence@1",
            "provider_source_space.claims",
        )
        if claims.get("provider_id") != self.provider_fragment.provider_id:
            raise ValueError("provider source-space evidence provider identity does not match")
        if claims.get("scenario_kind") != self.draft.scenario_kind:
            raise ValueError("provider source-space evidence scenario kind does not match")
        if claims.get("topology_fingerprint") != self.provider_context.topology.fingerprint:
            raise ValueError("provider source-space evidence topology fingerprint does not match")
        source_declared_id = require_token(
            claims.get("source_declared_id"), "provider_source_space.source_declared_id"
        )
        if source_declared_id not in self.provider_fragment.declared_ids:
            raise ValueError("provider source-space evidence source is not provider-declared")
        source_space_id = require_token(
            claims.get("source_space_id"), "provider_source_space.source_space_id"
        )
        validate_source_space(source_space_id, self.provider_context)
        require_token(claims.get("determination"), "provider_source_space.determination")
        category = claims.get("surface_category")
        if category is not None and category not in {
            "exterior_surfaces",
            "interior_cavity_surfaces",
        }:
            raise ValueError("provider source-space evidence has unsupported surface category")
        require_string_sequence(
            claims.get("external_opening_ids"),
            "provider_source_space.external_opening_ids",
        )
        return claims

    def with_prior_fragments(self, *fragments: KeywordFragment) -> "ScenarioModuleContext":
        existing = {fragment.module_id: fragment for fragment in self.prior_fragments}
        for fragment in fragments:
            previous = existing.get(fragment.module_id)
            if previous is not None:
                raise ValueError(f"prior fragment is duplicated or conflicts: {fragment.module_id}")
            existing[fragment.module_id] = fragment
        return ScenarioModuleContext(
            draft=self.draft,
            provider_context=self.provider_context,
            provider_fragment=self.provider_fragment,
            prior_fragments=tuple(existing.values()),
        )

    def input_for(self, module_name: str) -> Mapping[str, object]:
        _require_token(module_name, "module name")
        field_by_module = {
            "placement": "building_placement",
            "support_ground": "support_and_ground",
            "blast_source": "blast_source",
            "fluid_domain": "fluid_domain",
            "boundaries": "boundaries",
            "interactions": "interactions",
        }
        field = field_by_module.get(module_name)
        if field is None:
            raise ValueError(f"unsupported module name: {module_name!r}")
        value = getattr(self.draft, field)
        if not isinstance(value, Mapping):
            raise ValueError(f"module_inputs.{module_name} must be a mapping")
        return value

def closed_mapping(
    value: object, expected_keys: frozenset[str], path: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be a mapping")
    actual = set(value)
    unknown = sorted(actual - expected_keys)
    missing = sorted(expected_keys - actual)
    if unknown:
        raise ValueError(f"{path} has unknown field: {unknown[0]!r}")
    if missing:
        raise ValueError(f"{path} is missing required field: {missing[0]!r}")
    return value


def require_literal(value: Mapping[str, object], key: str, expected: str, path: str) -> None:
    if value.get(key) != expected:
        raise ValueError(f"{path}.{key} must be {expected!r}")


def require_token(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty safe identifier")
    token = value.strip()
    if any(character.isspace() for character in token) or any(
        character in token for character in ("/", "\\", "\x00")
    ) or token in {".", ".."}:
        raise ValueError(f"{path} must be a safe identifier")
    return token


def require_string_sequence(value: object, path: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{path} must be a sequence")
    result = tuple(require_token(item, f"{path}[{index}]") for index, item in enumerate(value))
    if len(result) != len(set(result)):
        raise ValueError(f"{path} contains duplicate identifiers")
    return result


def require_si_budgets(value: Mapping[str, object], path: str) -> FrozenMapping:
    """Validate the shared bounded, SI-only module envelope before allocation."""

    if value.get("unit_system") != "SI_m_s_kg_N_Pa":
        raise ValueError(f"{path}.unit_system must be 'SI_m_s_kg_N_Pa'")
    budgets = closed_mapping(
        value.get("budgets"),
        frozenset({"schema_version", "max_new_nodes", "max_new_elements"}),
        f"{path}.budgets",
    )
    require_literal(budgets, "schema_version", "refined_blast.module_budgets@1", f"{path}.budgets")
    checked: dict[str, int] = {}
    for key in ("max_new_nodes", "max_new_elements"):
        raw = budgets[key]
        if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
            raise ValueError(f"{path}.budgets.{key} must be a positive integer")
        if raw > _MODULE_BUDGET_HARD_LIMIT:
            raise ValueError(
                f"{path}.budgets.{key} exceeds hard safety limit "
                f"{_MODULE_BUDGET_HARD_LIMIT}"
            )
        checked[key] = raw
    frozen = freeze_value(checked, f"{path}.budgets")
    assert isinstance(frozen, Mapping)
    return frozen


def _require_token(value: object, path: str) -> str:
    return require_token(value, path)


def _unique_tokens(values: Sequence[str], path: str) -> tuple[str, ...]:
    result = tuple(_require_token(value, f"{path}[{index}]") for index, value in enumerate(values))
    if len(result) != len(set(result)):
        raise ValueError(f"{path} contains duplicate identifiers")
    return result


__all__ = [
    "FragmentInterface",
    "FragmentParticipant",
    "KeywordFragment",
    "ScenarioModuleContext",
    "closed_mapping",
    "require_literal",
    "require_si_budgets",
    "require_string_sequence",
    "require_token",
]
