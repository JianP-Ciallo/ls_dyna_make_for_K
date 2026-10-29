"""Directed interactions resolved exclusively through first-class typed records."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

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


class InteractionCompiler:
    module_id = "interactions"

    def compile(self, context: ScenarioModuleContext) -> KeywordFragment:
        raw = closed_mapping(
            context.input_for(self.module_id),
            frozenset({"schema_version", "unit_system", "pairs", "budgets"}),
            "interactions",
        )
        require_literal(
            raw, "schema_version", "refined_blast.interactions@1", "interactions"
        )
        pairs = raw["pairs"]
        if not isinstance(pairs, Sequence) or isinstance(pairs, (str, bytes, bytearray)):
            raise ValueError("interactions.pairs must be a sequence")
        budgets = require_si_budgets(raw, "interactions")
        participants = tuple(
            participant
            for fragment in context.prior_fragments
            for participant in fragment.participants
        )
        prior_interfaces = tuple(
            interface
            for fragment in context.prior_fragments
            for interface in fragment.interfaces
        )
        pair_keys: set[tuple[str, str]] = set()
        interaction_ids: set[str] = set()
        interfaces: list[FragmentInterface] = []
        canonical: list[tuple[str, str, str, str, str, str]] = []
        required_ids: set[str] = set()
        for index, item in enumerate(pairs):
            row = closed_mapping(
                item,
                frozenset({"interaction_id", "interaction_type", "source_id", "target_id"}),
                f"interactions.pairs[{index}]",
            )
            interaction_id = require_token(
                row["interaction_id"], f"interactions.pairs[{index}].interaction_id"
            )
            interaction_type = row["interaction_type"]
            requested_source_id = require_token(
                row["source_id"], f"interactions.pairs[{index}].source_id"
            )
            requested_target_id = require_token(
                row["target_id"], f"interactions.pairs[{index}].target_id"
            )
            if interaction_type not in {"fsi_candidate", "tie_candidate"}:
                raise ValueError("interactions contains unsupported interaction_type")
            if interaction_id in interaction_ids:
                raise ValueError("interactions contains a duplicate interaction id")

            if interaction_type == "fsi_candidate":
                source = _exact_participant(
                    participants,
                    requested_source_id,
                    role="fluid_domain",
                    kinds={"fluid_mesh", "fluid_region"},
                    label="FSI fluid source",
                )
                target = _participant_or_member(
                    participants,
                    requested_target_id,
                    role="building_structure",
                    kinds={"structural_mesh"},
                    label="FSI building target",
                )
                typed_candidates = tuple(
                    relation
                    for relation in prior_interfaces
                    if relation.kind == "fsi_candidate_surface"
                    and relation.source_participant_id == source.participant_id
                    and relation.target_participant_id == target.participant_id
                )
                if len(typed_candidates) != 1:
                    raise ValueError(
                        "FSI interaction requires one exact typed fluid-to-structure surface candidate"
                    )
                candidate = typed_candidates[0]
                member_ids = {candidate.interface_id, *candidate.member_ids}
                if requested_target_id != target.participant_id:
                    member_ids.add(requested_target_id)
                compiled_interface = FragmentInterface(
                    interface_id=f"interaction:{interaction_id}",
                    kind="fsi",
                    source_participant_id=source.participant_id,
                    target_participant_id=target.participant_id,
                    member_ids=frozenset(member_ids),
                )
            else:
                source = _exact_participant(
                    participants,
                    requested_source_id,
                    role="ground_support",
                    kinds={"support_definition"},
                    label="support interaction source",
                )
                target = _participant_or_member(
                    participants,
                    requested_target_id,
                    role="building_structure",
                    kinds={"structural_mesh"},
                    label="support building target",
                )
                matching_support = tuple(
                    relation
                    for relation in prior_interfaces
                    if relation.kind in {"support_shared_node", "support_tied"}
                    and relation.source_participant_id == source.participant_id
                    and relation.target_participant_id == target.participant_id
                    and (
                        requested_target_id == target.participant_id
                        or requested_target_id in relation.member_ids
                    )
                )
                if not matching_support:
                    raise ValueError(
                        "support interaction target is unrelated to the exact foundation interface"
                    )
                support_kinds = {relation.kind for relation in matching_support}
                if len(support_kinds) != 1:
                    raise ValueError("support interaction mixes incompatible support interface kinds")
                member_ids = {
                    *(relation.interface_id for relation in matching_support),
                    *(
                        member
                        for relation in matching_support
                        for member in relation.member_ids
                    ),
                }
                compiled_interface = FragmentInterface(
                    interface_id=f"interaction:{interaction_id}",
                    kind=next(iter(support_kinds)),
                    source_participant_id=source.participant_id,
                    target_participant_id=target.participant_id,
                    member_ids=frozenset(member_ids),
                    shared_node_ids=_unique_members(
                        relation.shared_node_ids for relation in matching_support
                    ),
                    master_member_ids=_unique_members(
                        relation.master_member_ids for relation in matching_support
                    ),
                    slave_member_ids=_unique_members(
                        relation.slave_member_ids for relation in matching_support
                    ),
                )

            pair_key = tuple(
                sorted(
                    (
                        compiled_interface.source_participant_id,
                        compiled_interface.target_participant_id,
                    )
                )
            )
            if pair_key in pair_keys:
                raise ValueError("interactions contains a duplicate or reversed interaction pair")
            pair_keys.add(pair_key)
            interaction_ids.add(interaction_id)
            interfaces.append(compiled_interface)
            required_ids.update(
                {
                    compiled_interface.source_participant_id,
                    compiled_interface.target_participant_id,
                    *compiled_interface.member_ids,
                    *compiled_interface.shared_node_ids,
                    *compiled_interface.master_member_ids,
                    *compiled_interface.slave_member_ids,
                }
            )
            canonical.append(
                (
                    interaction_id,
                    str(interaction_type),
                    compiled_interface.source_participant_id,
                    compiled_interface.target_participant_id,
                    requested_source_id,
                    requested_target_id,
                )
            )
        canonical.sort()
        return KeywordFragment(
            module_id=self.module_id,
            declared_ids=frozenset(row.interface_id for row in interfaces),
            required_ids=frozenset(required_ids),
            estimates={
                "pair_count": len(canonical),
                "new_nodes": 0,
                "new_elements": 0,
                "budget_limits": budgets,
                "budget_checked_before_allocation": True,
            },
            manifest={
                "pairs": tuple(canonical),
                "pair_count": len(canonical),
                "id_closure": {"closed": True},
                "unit_system": "SI_m_s_kg_N_Pa",
            },
            interfaces=tuple(interfaces),
        )


def _exact_participant(
    participants: tuple[FragmentParticipant, ...],
    requested_id: str,
    *,
    role: str,
    kinds: set[str],
    label: str,
) -> FragmentParticipant:
    matches = tuple(
        participant
        for participant in participants
        if participant.participant_id == requested_id
        and participant.role == role
        and participant.kind in kinds
    )
    if len(matches) != 1:
        raise ValueError(f"{label} requires one participant with the exact typed role")
    return matches[0]


def _participant_or_member(
    participants: tuple[FragmentParticipant, ...],
    requested_id: str,
    *,
    role: str,
    kinds: set[str],
    label: str,
) -> FragmentParticipant:
    matches = tuple(
        participant
        for participant in participants
        if participant.role == role
        and participant.kind in kinds
        and (
            participant.participant_id == requested_id
            or requested_id in participant.member_ids
        )
    )
    if len(matches) != 1:
        raise ValueError(f"{label} requires one participant or exact typed member")
    return matches[0]


def _unique_members(groups: Iterable[Sequence[str]]) -> tuple[str, ...]:
    # Adjacent foundation faces can intentionally share coupling nodes or
    # members.  Individual typed interfaces already reject duplicates; the
    # aggregate interaction owns the deterministic union.
    return tuple(sorted({member for group in groups for member in group}))


__all__ = ["InteractionCompiler"]
