"""Directly assemblable foundation support and symbolic ground geometry."""

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
    require_string_sequence,
)
from .providers.common import fingerprint_value


_GROUND_DEPTH_M = 1.0


class SupportGroundCompiler:
    module_id = "support_ground"

    def compile(self, context: ScenarioModuleContext) -> KeywordFragment:
        raw = closed_mapping(
            context.input_for(self.module_id),
            frozenset(
                {
                    "schema_version",
                    "unit_system",
                    "support_face_ids",
                    "coupling_semantics",
                    "budgets",
                }
            ),
            "support_ground",
        )
        require_literal(
            raw, "schema_version", "refined_blast.support_ground@1", "support_ground"
        )
        semantics = raw["coupling_semantics"]
        if semantics not in {"shared_node", "tied"}:
            raise ValueError("support_ground.coupling_semantics must be shared_node or tied")
        face_ids = require_string_sequence(
            raw["support_face_ids"], "support_ground.support_face_ids"
        )
        if not face_ids:
            raise ValueError("support_ground.support_face_ids must not be empty")
        budgets = require_si_budgets(raw, "support_ground")

        foundation_rows = _verified_foundation_rows(context)
        invalid = sorted(set(face_ids) - set(foundation_rows))
        if invalid:
            raise ValueError(f"support face {invalid[0]!r} is not a real foundation interface")
        selected_rows = tuple(foundation_rows[face_id] for face_id in sorted(face_ids))
        for row in selected_rows:
            node_ids = row.get("node_ids")
            if (
                not isinstance(node_ids, Sequence)
                or isinstance(node_ids, (str, bytes, bytearray))
                or len(node_ids) != 4
                or len(set(node_ids)) != 4
                or any(isinstance(node_id, bool) or not isinstance(node_id, int) for node_id in node_ids)
            ):
                raise ValueError("foundation interface must be one four-node structural face")

        structure = _one_participant(context, role="building_structure", kind="structural_mesh")
        ground_surfaces = _one_participant(
            context, role="boundary_surface", kind="ground_contact_surface_set"
        )
        missing_surface_members = {
            f"surface:{face_id}" for face_id in face_ids
        } - ground_surfaces.member_ids
        if missing_surface_members:
            raise ValueError("foundation surface participant does not contain requested support face")

        unique_node_ids = tuple(
            sorted({node_id for row in selected_rows for node_id in row["node_ids"]})
        )
        new_node_count = len(unique_node_ids) * (1 if semantics == "shared_node" else 2)
        new_element_count = len(selected_rows)
        if new_node_count > budgets["max_new_nodes"]:
            raise ValueError("support_ground node budget exceeded before geometry allocation")
        if new_element_count > budgets["max_new_elements"]:
            raise ValueError("support_ground element budget exceeded before geometry allocation")

        scenario_id = context.draft.scenario_id
        support_id = f"support:{scenario_id}"
        ground_id = f"ground:{scenario_id}"
        node_by_id = {
            node.node_id: node.coordinates for node in context.provider_context.artifact.mesh.nodes
        }
        geometry_coordinates: dict[str, tuple[float, float, float]] = {
            f"building:node:{node_id}": coordinates
            for node_id, coordinates in node_by_id.items()
        }
        geometry_nodes: list[dict[str, object]] = []
        top_id_by_structure: dict[int, str] = {}
        bottom_id_by_structure: dict[int, str] = {}
        for node_id in unique_node_ids:
            coordinates = node_by_id.get(node_id)
            if coordinates is None:
                raise ValueError(f"foundation interface references unknown node: {node_id}")
            structure_node_id = f"building:node:{node_id}"
            if semantics == "tied":
                top_id = f"ground:{scenario_id}:node:top:{node_id}"
                top_id_by_structure[node_id] = top_id
                geometry_nodes.append(
                    {
                        "node_id": top_id,
                        "coordinates_m": coordinates,
                        "layer": "top",
                        "coincident_with": structure_node_id,
                    }
                )
                geometry_coordinates[top_id] = coordinates
            else:
                top_id_by_structure[node_id] = structure_node_id
            bottom_id = f"ground:{scenario_id}:node:bottom:{node_id}"
            bottom_id_by_structure[node_id] = bottom_id
            geometry_nodes.append(
                {
                    "node_id": bottom_id,
                    "coordinates_m": (
                        coordinates[0],
                        coordinates[1],
                        coordinates[2] - _GROUND_DEPTH_M,
                    ),
                    "layer": "bottom",
                    "coincident_with": "",
                }
            )
            geometry_coordinates[bottom_id] = (
                coordinates[0], coordinates[1], coordinates[2] - _GROUND_DEPTH_M
            )

        geometry_elements: list[dict[str, object]] = []
        interfaces: list[FragmentInterface] = []
        ground_member_ids: set[str] = {
            row["node_id"] for row in geometry_nodes  # type: ignore[misc]
        }
        required_ids: set[str] = {
            structure.participant_id,
            ground_surfaces.participant_id,
            *(f"building:node:{node_id}" for node_id in unique_node_ids),
        }
        for index, row in enumerate(selected_rows, start=1):
            face_id = str(row["face_id"])
            structure_surface_id = f"surface:{face_id}"
            structure_element_id = f"building:element:{row['element_id']}"
            ground_element_id = f"ground:{scenario_id}:solid:{index}"
            ground_face_id = f"ground:{scenario_id}:face:top:{index}"
            interface_id = f"support_interface:{scenario_id}:{index}"
            ordered_node_ids = tuple(row["node_ids"])
            raw_connectivity = (
                *(top_id_by_structure[node_id] for node_id in ordered_node_ids),
                *(bottom_id_by_structure[node_id] for node_id in ordered_node_ids),
            )
            connectivity, corner_jacobians = _positive_hex_connectivity(
                raw_connectivity, geometry_coordinates
            )
            geometry_elements.append(
                {
                    "element_id": ground_element_id,
                    "node_ids": connectivity,
                    "top_face_id": ground_face_id,
                    "source_foundation_face_id": structure_surface_id,
                    "corner_jacobians_m3": corner_jacobians,
                }
            )
            ground_member_ids.update({ground_element_id, ground_face_id})
            required_ids.update({structure_surface_id, structure_element_id})
            interfaces.append(
                FragmentInterface(
                    interface_id=interface_id,
                    kind=(
                        "support_shared_node"
                        if semantics == "shared_node"
                        else "support_tied"
                    ),
                    source_participant_id=support_id,
                    target_participant_id=structure.participant_id,
                    member_ids=frozenset(
                        {
                            structure_surface_id,
                            structure_element_id,
                            ground_element_id,
                            ground_face_id,
                        }
                    ),
                    shared_node_ids=(
                        tuple(f"building:node:{node_id}" for node_id in ordered_node_ids)
                        if semantics == "shared_node"
                        else ()
                    ),
                    master_member_ids=(structure_surface_id,) if semantics == "tied" else (),
                    slave_member_ids=(ground_face_id,) if semantics == "tied" else (),
                )
            )

        support_participant = FragmentParticipant(
            participant_id=support_id,
            role="ground_support",
            kind="support_definition",
            member_ids=frozenset(row.interface_id for row in interfaces),
        )
        ground_participant = FragmentParticipant(
            participant_id=ground_id,
            role="ground_support",
            kind="ground_mesh",
            member_ids=frozenset(ground_member_ids),
        )
        declared_ids = {
            support_id,
            ground_id,
            *(row.interface_id for row in interfaces),
            *ground_member_ids,
        }
        return KeywordFragment(
            module_id=self.module_id,
            declared_ids=frozenset(declared_ids),
            required_ids=frozenset(required_ids),
            estimates={
                "support_face_count": len(face_ids),
                "new_nodes": new_node_count,
                "new_elements": new_element_count,
                "budget_limits": budgets,
                "budget_checked_before_allocation": True,
            },
            manifest={
                "support_face_ids": tuple(sorted(face_ids)),
                "coupling_semantics": semantics,
                "foundation_interfaces_verified": True,
                "unit_system": "SI_m_s_kg_N_Pa",
                "ground_geometry": {
                    "schema_version": "refined_blast.symbolic_ground_geometry@1",
                    "ground_depth_m": _GROUND_DEPTH_M,
                    "nodes": tuple(geometry_nodes),
                    "elements": tuple(geometry_elements),
                },
            },
            participants=(support_participant, ground_participant),
            interfaces=tuple(interfaces),
        )


def _verified_foundation_rows(
    context: ScenarioModuleContext,
) -> dict[str, Mapping[str, object]]:
    context_rows = _rows(
        context.provider_context.surface_catalog.get("ground_contact_surfaces"),
        "ground_contact_surfaces",
    )
    artifact_rows = _rows(
        context.provider_context.artifact.surface_catalog.get("ground_contact_surfaces"),
        "artifact.ground_contact_surfaces",
    )
    artifact_by_id = {str(row.get("face_id")): row for row in artifact_rows}
    result: dict[str, Mapping[str, object]] = {}
    for row in context_rows:
        face_id = str(row.get("face_id"))
        if face_id in result:
            raise ValueError(f"duplicate foundation face id: {face_id!r}")
        artifact_row = artifact_by_id.get(face_id)
        if artifact_row is None or fingerprint_value(row) != fingerprint_value(artifact_row):
            raise ValueError(f"foundation face {face_id!r} does not match building artifact")
        result[face_id] = row
    return result


def _one_participant(
    context: ScenarioModuleContext, *, role: str, kind: str
) -> FragmentParticipant:
    matches = tuple(
        participant
        for fragment in context.prior_fragments
        for participant in fragment.participants
        if participant.role == role and participant.kind == kind
    )
    if len(matches) != 1:
        raise ValueError(f"support_ground requires exactly one typed {role}/{kind} participant")
    return matches[0]


def _rows(value: object, path: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"surface_catalog.{path} must be a sequence")
    if any(not isinstance(row, Mapping) for row in value):
        raise ValueError(f"surface_catalog.{path} contains an invalid row")
    return tuple(value)  # type: ignore[return-value]


def _positive_hex_connectivity(
    raw: tuple[str, ...],
    coordinates: Mapping[str, tuple[float, float, float]],
) -> tuple[tuple[str, ...], tuple[float, ...]]:
    """Orient one extruded HEX8 and fail closed unless all corner Jacobians are positive."""

    if len(raw) != 8:
        raise ValueError("ground solid connectivity must contain exactly eight nodes")
    top = raw[:4]
    bottom = raw[4:]
    candidates: list[tuple[str, ...]] = []
    for reverse in (False, True):
        top_ring = top if not reverse else (top[0], top[3], top[2], top[1])
        bottom_ring = bottom if not reverse else (
            bottom[0], bottom[3], bottom[2], bottom[1]
        )
        for offset in range(4):
            candidates.append(
                top_ring[offset:] + top_ring[:offset]
                + bottom_ring[offset:] + bottom_ring[:offset]
            )
    for candidate in candidates:
        points = tuple(coordinates[node_id] for node_id in candidate)
        extents = tuple(
            max(point[axis] for point in points)
            - min(point[axis] for point in points)
            for axis in range(3)
        )
        scale = extents[0] * extents[1] * extents[2]
        if scale <= 0.0:
            continue
        threshold = max(scale * 1.0e-12, 1.0e-18)
        jacobians = _hex_corner_jacobians(points)
        if all(value > threshold for value in jacobians):
            return candidate, jacobians
    raise ValueError(
        "ground solid cannot be oriented with positive Jacobian at every corner"
    )


def _hex_corner_jacobians(
    points: tuple[tuple[float, float, float], ...],
) -> tuple[float, ...]:
    natural = (
        (-1.0, -1.0, -1.0),
        (1.0, -1.0, -1.0),
        (1.0, 1.0, -1.0),
        (-1.0, 1.0, -1.0),
        (-1.0, -1.0, 1.0),
        (1.0, -1.0, 1.0),
        (1.0, 1.0, 1.0),
        (-1.0, 1.0, 1.0),
    )
    result: list[float] = []
    for xi, eta, zeta in natural:
        jacobian = [[0.0] * 3 for _ in range(3)]
        for point, (node_xi, node_eta, node_zeta) in zip(
            points, natural, strict=True
        ):
            derivatives = (
                node_xi * (1.0 + node_eta * eta) * (1.0 + node_zeta * zeta) / 8.0,
                node_eta * (1.0 + node_xi * xi) * (1.0 + node_zeta * zeta) / 8.0,
                node_zeta * (1.0 + node_xi * xi) * (1.0 + node_eta * eta) / 8.0,
            )
            for physical_axis in range(3):
                for natural_axis in range(3):
                    jacobian[physical_axis][natural_axis] += (
                        point[physical_axis] * derivatives[natural_axis]
                    )
        result.append(
            jacobian[0][0]
            * (jacobian[1][1] * jacobian[2][2] - jacobian[1][2] * jacobian[2][1])
            - jacobian[0][1]
            * (jacobian[1][0] * jacobian[2][2] - jacobian[1][2] * jacobian[2][0])
            + jacobian[0][2]
            * (jacobian[1][0] * jacobian[2][1] - jacobian[1][1] * jacobian[2][0])
        )
    return tuple(result)


__all__ = ["SupportGroundCompiler"]
