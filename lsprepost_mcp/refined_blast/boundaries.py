"""Directed boundary interfaces over typed domains and classified surfaces."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

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


_CATEGORIES = (
    "exterior_surfaces",
    "interior_cavity_surfaces",
    "ground_contact_surfaces",
    "unclassified_boundary_surfaces",
)
_BOUNDARY_MATRIX = {
    "non_reflecting": (
        ("fluid_domain", frozenset({"fluid_mesh", "fluid_region"})),
        frozenset({"exterior_surface_set", "unclassified_surface_set"}),
        "boundary_non_reflecting",
    ),
    "rigid": (
        ("ground_support", frozenset({"support_definition"})),
        frozenset({"ground_contact_surface_set"}),
        "boundary_rigid",
    ),
}


class BoundaryCompiler:
    module_id = "boundaries"

    def compile(self, context: ScenarioModuleContext) -> KeywordFragment:
        raw = closed_mapping(
            context.input_for(self.module_id),
            frozenset({"schema_version", "unit_system", "assignments", "budgets"}),
            "boundaries",
        )
        require_literal(
            raw, "schema_version", "refined_blast.boundaries@1", "boundaries"
        )
        assignments = raw["assignments"]
        if not isinstance(assignments, Sequence) or isinstance(
            assignments, (str, bytes, bytearray)
        ):
            raise ValueError("boundaries.assignments must be a sequence")
        budgets = require_si_budgets(raw, "boundaries")
        real_faces = {
            str(row["face_id"]): category
            for category in _CATEGORIES
            for row in _rows(context.provider_context.surface_catalog.get(category), category)
        }
        participants = tuple(
            participant
            for fragment in context.prior_fragments
            for participant in fragment.participants
        )
        seen_faces: set[str] = set()
        seen_ids: set[str] = set()
        interfaces: list[FragmentInterface] = []
        canonical: list[tuple[str, str, str, str, str, str]] = []
        required_ids: set[str] = set()
        for index, item in enumerate(assignments):
            row = closed_mapping(
                item,
                frozenset({"boundary_id", "face_id", "boundary_type"}),
                f"boundaries.assignments[{index}]",
            )
            boundary_id = require_token(
                row["boundary_id"], f"boundaries.assignments[{index}].boundary_id"
            )
            face_id = require_token(
                row["face_id"], f"boundaries.assignments[{index}].face_id"
            )
            boundary_type = row["boundary_type"]
            matrix = _BOUNDARY_MATRIX.get(boundary_type)  # type: ignore[arg-type]
            if matrix is None:
                raise ValueError("boundaries assignment has an incompatible boundary_type")
            if boundary_id in seen_ids:
                raise ValueError("boundaries contains duplicate boundary id")
            if face_id in seen_faces:
                raise ValueError("boundaries contains an overlap on one boundary face")
            category = real_faces.get(face_id)
            if category is None:
                raise ValueError("boundaries assignment must reference a real domain boundary face")
            (source_role, source_kinds), target_kinds, interface_kind = matrix
            source = _one_matching(
                participants,
                lambda participant: participant.role == source_role
                and participant.kind in source_kinds,
                f"typed {source_role} participant",
            )
            surface_id = f"surface:{face_id}"
            target = _one_matching(
                participants,
                lambda participant: participant.role == "boundary_surface"
                and participant.kind in target_kinds
                and surface_id in participant.member_ids,
                "compatible typed boundary surface participant",
            )
            interface_id = f"boundary:{boundary_id}"
            interfaces.append(
                FragmentInterface(
                    interface_id=interface_id,
                    kind=interface_kind,
                    source_participant_id=source.participant_id,
                    target_participant_id=target.participant_id,
                    member_ids=frozenset({surface_id}),
                )
            )
            required_ids.update({source.participant_id, target.participant_id, surface_id})
            seen_ids.add(boundary_id)
            seen_faces.add(face_id)
            canonical.append(
                (
                    boundary_id,
                    face_id,
                    str(boundary_type),
                    category,
                    source.participant_id,
                    target.participant_id,
                )
            )
        canonical.sort()
        return KeywordFragment(
            module_id=self.module_id,
            declared_ids=frozenset(row.interface_id for row in interfaces),
            required_ids=frozenset(required_ids),
            estimates={
                "assignment_count": len(canonical),
                "new_nodes": 0,
                "new_elements": 0,
                "budget_limits": budgets,
                "budget_checked_before_allocation": True,
            },
            manifest={
                "assignments": tuple(canonical),
                "assignment_count": len(canonical),
                "unit_system": "SI_m_s_kg_N_Pa",
            },
            interfaces=tuple(interfaces),
        )


def _one_matching(
    participants: tuple[FragmentParticipant, ...], predicate: object, label: str
) -> FragmentParticipant:
    matches = tuple(row for row in participants if predicate(row))  # type: ignore[operator]
    if len(matches) != 1:
        raise ValueError(f"boundaries requires exactly one {label}")
    return matches[0]


def _rows(value: object, path: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"surface_catalog.{path} must be a sequence")
    if any(not isinstance(row, Mapping) for row in value):
        raise ValueError(f"surface_catalog.{path} contains an invalid row")
    return tuple(value)  # type: ignore[return-value]


__all__ = ["BoundaryCompiler"]
