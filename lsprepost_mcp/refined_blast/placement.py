"""Single-building placement fragment compiler."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from .fragments import (
    FragmentParticipant,
    KeywordFragment,
    ScenarioModuleContext,
    closed_mapping,
    require_literal,
    require_si_budgets,
)


_SURFACE_PARTICIPANTS = {
    "exterior_surfaces": ("exterior", "exterior_surface_set"),
    "interior_cavity_surfaces": ("interior", "interior_surface_set"),
    "ground_contact_surfaces": ("ground_contact", "ground_contact_surface_set"),
    "unclassified_boundary_surfaces": ("unclassified", "unclassified_surface_set"),
}


class PlacementCompiler:
    module_id = "placement"

    def compile(self, context: ScenarioModuleContext) -> KeywordFragment:
        raw = closed_mapping(
            context.input_for(self.module_id),
            frozenset({"schema_version", "unit_system", "building_count", "translation_m", "budgets"}),
            "placement",
        )
        require_literal(raw, "schema_version", "refined_blast.placement@1", "placement")
        count = raw["building_count"]
        if isinstance(count, bool) or not isinstance(count, int):
            raise ValueError("placement.building_count must be an integer")
        if count != 1:
            raise ValueError("multi-building placement is unsupported")
        translation = _vector(raw["translation_m"], "placement.translation_m")
        if translation != (0.0, 0.0, 0.0):
            raise ValueError("placement supports only zero translation until a full transform mechanism exists")
        budgets = require_si_budgets(raw, "placement")
        scenario_id = context.draft.scenario_id
        structure_id = f"building:{scenario_id}"
        structure_members = frozenset(
            {
                *(f"building:node:{node.node_id}" for node in context.provider_context.artifact.mesh.nodes),
                *(
                    f"building:element:{element.element_id}"
                    for element in (
                        *context.provider_context.artifact.mesh.solids,
                        *context.provider_context.artifact.mesh.shells,
                        *context.provider_context.artifact.mesh.beams,
                    )
                ),
            }
        )
        participants = [
            FragmentParticipant(
                participant_id=structure_id,
                role="building_structure",
                kind="structural_mesh",
                member_ids=structure_members,
            )
        ]
        required_ids = set(structure_members) | {
            f"artifact:{context.provider_context.artifact.fingerprint}"
        }
        for category, (suffix, kind) in _SURFACE_PARTICIPANTS.items():
            rows = context.provider_context.surface_catalog.get(category)
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
                raise ValueError(f"surface_catalog.{category} must be a sequence")
            members = frozenset(f"surface:{row['face_id']}" for row in rows if isinstance(row, Mapping))
            participant_id = f"building_surface:{scenario_id}:{suffix}"
            participants.append(
                FragmentParticipant(
                    participant_id=participant_id,
                    role="boundary_surface",
                    kind=kind,
                    member_ids=members,
                )
            )
            required_ids.update(members)
        return KeywordFragment(
            module_id=self.module_id,
            declared_ids=frozenset(
                {f"placement:{scenario_id}", *(row.participant_id for row in participants)}
            ),
            required_ids=frozenset(required_ids),
            estimates={"building_count": 1, "new_nodes": 0, "new_elements": 0, "budget_limits": budgets, "budget_checked_before_allocation": True},
            manifest={"translation_m": translation, "building_mesh_reused": True, "unit_system": "SI_m_s_kg_N_Pa"},
            participants=tuple(participants),
        )


def _vector(value: object, path: str) -> tuple[float, float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)) or len(value) != 3:
        raise ValueError(f"{path} must contain exactly three finite numbers")
    numbers: list[float] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise ValueError(f"{path}[{index}] must be finite")
        numbers.append(float(item))
    return tuple(numbers)  # type: ignore[return-value]
