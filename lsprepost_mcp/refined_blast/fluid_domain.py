"""Topology-driven fluid-domain fragment compiler."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping

from .fragments import (
    FragmentInterface,
    FragmentParticipant,
    KeywordFragment,
    ScenarioModuleContext,
    closed_mapping,
    require_literal,
    require_si_budgets,
    require_token,
)


class FluidDomainCompiler:
    module_id = "fluid_domain"

    def compile(self, context: ScenarioModuleContext) -> KeywordFragment:
        raw = closed_mapping(
            context.input_for(self.module_id),
            frozenset({"schema_version", "unit_system", "source_space_id", "opening_states", "external_buffer_m", "budgets"}),
            "fluid_domain",
        )
        require_literal(raw, "schema_version", "refined_blast.fluid_domain@1", "fluid_domain")
        source_space = require_token(raw["source_space_id"], "fluid_domain.source_space_id")
        space_ids = {space.region_id for space in context.provider_context.topology.spaces}
        if source_space not in space_ids and not (
            context.draft.scenario_kind == "external" and source_space == "exterior"
        ):
            raise ValueError("fluid_domain.source_space_id must be a real room cavity")
        opening_states = _opening_states(raw["opening_states"], context)
        external_buffer = _nonnegative_number(raw["external_buffer_m"], "fluid_domain.external_buffer_m")
        budgets = require_si_budgets(raw, "fluid_domain")
        source_contract = context.draft.blast_source
        if not source_contract:
            raise ValueError("fluid domain requires a draft blast_source contract")
        if source_contract.get("source_space_id") != source_space:
            raise ValueError("fluid domain source space must match the blast source contract")
        provider_space = context.provider_source_space_id
        if provider_space is not None and provider_space != source_space:
            raise ValueError("fluid domain source space must match the provider topology evidence")
        reachable, predecessors = _reachable_spaces(context, source_space, opening_states)
        kind = context.draft.scenario_kind
        if kind == "external":
            if source_space != "exterior":
                raise ValueError("external fluid domain source must be exterior")
            included: tuple[str, ...] = ()
            vent_path: tuple[str, ...] = ()
            external_included = True
        else:
            if kind == "internal" and "exterior" in reachable:
                raise ValueError("internal fluid domain must not have an open path to exterior")
            included = tuple(sorted(reachable - {"exterior"}))
            external_included = kind == "semi_enclosed"
            vent_path = _path_to_exterior(predecessors)
            if kind == "semi_enclosed" and not vent_path:
                raise ValueError("semi_enclosed domain requires an open vent path to exterior")
            if kind == "internal":
                external_included = False
        scenario_id = context.draft.scenario_id
        fluid_id = f"fluid:{scenario_id}"
        declared = {fluid_id}
        region_member_ids = {
            f"fluid_region:{scenario_id}:{space_id}" for space_id in included
        }
        declared.update(region_member_ids)
        if external_included:
            region_member_ids.add(f"fluid_buffer:{scenario_id}")
            declared.add(f"fluid_buffer:{scenario_id}")
        provider_mesh_ids = {
            *context.provider_fragment.node_ids,
            *context.provider_fragment.element_ids,
        }
        participant = FragmentParticipant(
            participant_id=fluid_id,
            role="fluid_domain",
            kind="fluid_mesh" if provider_mesh_ids else "fluid_region",
            member_ids=frozenset(region_member_ids | provider_mesh_ids),
        )
        interfaces: tuple[FragmentInterface, ...] = ()
        coupling_face_ids = frozenset(
            f"surface:{face_id}" for face_id in context.provider_fragment.fsi_face_ids
        )
        if coupling_face_ids:
            prior_participants = tuple(
                row
                for fragment in context.prior_fragments
                for row in fragment.participants
            )
            structures = tuple(
                row
                for row in prior_participants
                if row.role == "building_structure" and row.kind == "structural_mesh"
            )
            if len(structures) != 1:
                raise ValueError(
                    "fluid_domain FSI candidates require exactly one typed building structure"
                )
            classified_members = {
                member
                for row in prior_participants
                if row.role == "boundary_surface"
                for member in row.member_ids
            }
            if not coupling_face_ids <= classified_members:
                raise ValueError(
                    "fluid_domain FSI candidates contain an untyped building surface"
                )
            candidate = FragmentInterface(
                interface_id=f"fluid_interface:{scenario_id}:fsi_candidate",
                kind="fsi_candidate_surface",
                source_participant_id=fluid_id,
                target_participant_id=structures[0].participant_id,
                member_ids=coupling_face_ids,
            )
            interfaces = (candidate,)
            declared.add(candidate.interface_id)
        return KeywordFragment(
            module_id=self.module_id,
            declared_ids=frozenset(declared),
            required_ids=frozenset(
                {
                    f"topology:{context.provider_context.topology.fingerprint}",
                    *provider_mesh_ids,
                    *coupling_face_ids,
                    *(row.target_participant_id for row in interfaces),
                }
            ),
            estimates={"fluid_region_count": len(included) + int(external_included), "new_nodes": 0, "new_elements": 0, "budget_limits": budgets, "budget_checked_before_allocation": True},
            manifest={
                "scenario_kind": kind,
                "included_space_ids": included,
                "opening_states": dict(sorted(opening_states.items())),
                "vent_path_opening_ids": vent_path,
                "external_buffer_m": external_buffer,
                "external_buffer_included": external_included,
                "topology_driven": True,
                "unit_system": "SI_m_s_kg_N_Pa",
            },
            participants=(participant,),
            interfaces=interfaces,
        )


def _opening_states(value: object, context: ScenarioModuleContext) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("fluid_domain.opening_states must be a mapping")
    actual_ids = {opening.opening_id for opening in context.provider_context.topology.openings}
    if set(value) != actual_ids:
        raise ValueError("fluid_domain.opening_states must define every real opening exactly once")
    states: dict[str, str] = {}
    for opening_id, state in value.items():
        require_token(opening_id, "fluid_domain.opening_states key")
        if state not in {"open", "closed"}:
            raise ValueError("fluid_domain opening state must be open or closed")
        states[opening_id] = state
    return states


def _reachable_spaces(
    context: ScenarioModuleContext, source_space: str, opening_states: Mapping[str, str]
) -> tuple[set[str], dict[str, tuple[str, str]]]:
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for opening in context.provider_context.topology.openings:
        if opening_states[opening.opening_id] != "open":
            continue
        first, second = opening.connects
        adjacency.setdefault(first, []).append((second, opening.opening_id))
        adjacency.setdefault(second, []).append((first, opening.opening_id))
    reached = {source_space}
    predecessor: dict[str, tuple[str, str]] = {}
    queue = deque([source_space])
    while queue:
        node = queue.popleft()
        for target, opening_id in sorted(adjacency.get(node, ()), key=lambda row: (row[0], row[1])):
            if target not in reached:
                reached.add(target)
                predecessor[target] = (node, opening_id)
                queue.append(target)
    return reached, predecessor


def _path_to_exterior(predecessors: Mapping[str, tuple[str, str]]) -> tuple[str, ...]:
    if "exterior" not in predecessors:
        return ()
    path: list[str] = []
    current = "exterior"
    while current in predecessors:
        previous, opening_id = predecessors[current]
        path.append(opening_id)
        current = previous
    return tuple(reversed(path))


def _nonnegative_number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{path} must be a finite number")
    number = float(value)
    if number < 0:
        raise ValueError(f"{path} must be non-negative")
    return number
