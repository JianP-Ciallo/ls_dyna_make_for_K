"""Cross-module validation for compiled refined-building artifacts."""

from __future__ import annotations

from collections import Counter

from .artifacts import BuildingArtifact, Node, SolidElement
from .contracts import JSONDict
from .reinforcement import REINFORCEMENT_ROLES, _segment_crosses_box_interior
from .spatial import compile_spatial_topology


def validate_building_artifact(artifact: BuildingArtifact) -> JSONDict:
    """Return a machine-readable software validation report."""

    findings: list[dict[str, object]] = []
    nodes = {node.node_id: node for node in artifact.mesh.nodes}
    valid_node_ids = set(nodes)
    all_elements = (*artifact.mesh.solids, *artifact.mesh.shells, *artifact.mesh.beams)
    element_ids = {element.element_id for element in all_elements}

    _report_duplicates(
        findings,
        "duplicate_node_id",
        [node.node_id for node in artifact.mesh.nodes],
    )
    _report_duplicates(
        findings,
        "duplicate_element_id",
        [element.element_id for element in all_elements],
    )
    for element in all_elements:
        missing = sorted(set(element.node_ids) - valid_node_ids)
        if missing:
            findings.append(
                {
                    "code": "dangling_node_reference",
                    "element_id": element.element_id,
                    "node_ids": missing,
                }
            )

    topology = compile_spatial_topology(artifact.normalized_input)
    exclusion_regions = topology.opening_regions
    structural_node_ids = sorted(
        {node_id for element in all_elements for node_id in element.node_ids}
    )
    for node_id in structural_node_ids:
        node = nodes.get(node_id)
        if node is not None and not topology.envelope.contains_point(node.coordinates):
            findings.append(
                {
                    "code": "structural_node_outside_envelope",
                    "node_id": node_id,
                    "coordinates_m": list(node.coordinates),
                }
            )
    for beam in artifact.mesh.beams:
        if beam.part_role not in REINFORCEMENT_ROLES:
            continue
        start = nodes[beam.node_ids[0]].coordinates
        end = nodes[beam.node_ids[1]].coordinates
        for region_id, box in exclusion_regions:
            if _segment_crosses_box_interior(start, end, box):
                findings.append(
                    {
                        "code": "reinforcement_crosses_void",
                        "element_id": beam.element_id,
                        "region_id": region_id,
                    }
                )
    solid_node_ids = sorted(
        {node_id for solid in artifact.mesh.solids for node_id in solid.node_ids}
    )
    coordinate_owners: dict[tuple[float, float, float], int] = {}
    duplicate_coordinate_rows: list[dict[str, object]] = []
    for node_id in solid_node_ids:
        node = nodes[node_id]
        coordinate = tuple(round(value, 12) for value in node.coordinates)
        previous = coordinate_owners.get(coordinate)
        if previous is None:
            coordinate_owners[coordinate] = node_id
        elif previous != node_id:
            duplicate_coordinate_rows.append(
                {
                    "coordinate_m": list(coordinate),
                    "node_ids": [previous, node_id],
                }
            )
    if duplicate_coordinate_rows:
        findings.append(
            {
                "code": "duplicate_structural_coordinate",
                "duplicates": duplicate_coordinate_rows,
            }
        )

    if artifact.system_id in {"rc_frame", "rc_frame_shear_wall", "rc_box"}:
        component_count = _solid_connected_component_count(artifact.mesh.solids)
        if component_count != 1:
            findings.append(
                {
                    "code": "disconnected_concrete",
                    "component_count": component_count,
                }
            )

    solid_geometry: dict[tuple[tuple[float, float, float], ...], int] = {}
    for solid in artifact.mesh.solids:
        solid_nodes = tuple(nodes[node_id] for node_id in solid.node_ids)
        volume = _signed_corner_volume(solid_nodes)
        if volume <= 0.0:
            findings.append(
                {
                    "code": "non_positive_solid_volume",
                    "element_id": solid.element_id,
                    "signed_corner_volume_m3": volume,
                }
            )
        key = tuple(sorted(tuple(round(value, 12) for value in node.coordinates) for node in solid_nodes))
        previous = solid_geometry.get(key)
        if previous is not None:
            findings.append(
                {
                    "code": "duplicate_solid_geometry",
                    "element_ids": [previous, solid.element_id],
                }
            )
        else:
            solid_geometry[key] = solid.element_id
        centroid = tuple(
            sum(node.coordinates[axis] for node in solid_nodes) / len(solid_nodes)
            for axis in range(3)
        )
        if any(box.contains_point(centroid) for _, box in topology.opening_regions):
            findings.append(
                {
                    "code": "solid_centroid_in_void",
                    "element_id": solid.element_id,
                    "centroid_m": list(centroid),
                }
            )

    bindings = {binding.part_role: binding for binding in artifact.mesh.part_bindings}
    for role in sorted({element.part_role for element in all_elements}):
        binding = bindings.get(role)
        if binding is None:
            findings.append({"code": "missing_part_binding", "part_role": role})
        elif not binding.material_role.strip() or not binding.section_role.strip():
            findings.append({"code": "incomplete_part_binding", "part_role": role})

    for connection in artifact.connections:
        missing_source = sorted(set(connection.source_element_ids) - element_ids)
        missing_target = sorted(set(connection.target_element_ids) - element_ids)
        if missing_source or missing_target:
            findings.append(
                {
                    "code": "dangling_connection",
                    "connection_id": connection.connection_id,
                    "missing_source_ids": missing_source,
                    "missing_target_ids": missing_target,
                }
            )

    mutually_exclusive = (
        "exterior_surfaces",
        "interior_cavity_surfaces",
        "opening_boundaries",
        "ground_contact_surfaces",
    )
    membership: dict[str, str] = {}
    for category in mutually_exclusive:
        rows = artifact.surface_catalog.get(category, [])
        if not isinstance(rows, list):
            findings.append({"code": "invalid_surface_category", "category": category})
            continue
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("face_id"), str):
                findings.append({"code": "invalid_surface_entry", "category": category})
                continue
            face_id = row["face_id"]
            previous = membership.get(face_id)
            if previous is not None:
                findings.append(
                    {
                        "code": "duplicate_surface_membership",
                        "face_id": face_id,
                        "categories": [previous, category],
                    }
                )
            else:
                membership[face_id] = category

    return {
        "schema_version": "1.0.0",
        "valid": not findings,
        "findings": findings,
        "node_count": len(artifact.mesh.nodes),
        "solid_count": len(artifact.mesh.solids),
        "shell_count": len(artifact.mesh.shells),
        "beam_count": len(artifact.mesh.beams),
        "element_count": len(all_elements),
        "connection_count": len(artifact.connections),
        "requires_project_review": artifact.requires_project_review,
    }


def _report_duplicates(
    findings: list[dict[str, object]], code: str, values: list[int]
) -> None:
    duplicates = sorted(value for value, count in Counter(values).items() if count > 1)
    if duplicates:
        findings.append({"code": code, "ids": duplicates})


def _signed_corner_volume(nodes: tuple[Node, ...]) -> float:
    if len(nodes) != 8:
        return 0.0
    origin = nodes[0].coordinates
    first = tuple(nodes[1].coordinates[index] - origin[index] for index in range(3))
    second = tuple(nodes[3].coordinates[index] - origin[index] for index in range(3))
    third = tuple(nodes[4].coordinates[index] - origin[index] for index in range(3))
    cross = (
        second[1] * third[2] - second[2] * third[1],
        second[2] * third[0] - second[0] * third[2],
        second[0] * third[1] - second[1] * third[0],
    )
    return first[0] * cross[0] + first[1] * cross[1] + first[2] * cross[2]


def _solid_connected_component_count(solids: tuple[SolidElement, ...]) -> int:
    if not solids:
        return 0
    node_to_elements: dict[int, list[int]] = {}
    for index, solid in enumerate(solids):
        for node_id in solid.node_ids:
            node_to_elements.setdefault(node_id, []).append(index)

    remaining = set(range(len(solids)))
    component_count = 0
    while remaining:
        component_count += 1
        frontier = [remaining.pop()]
        while frontier:
            index = frontier.pop()
            for node_id in solids[index].node_ids:
                for neighbour in node_to_elements[node_id]:
                    if neighbour in remaining:
                        remaining.remove(neighbour)
                        frontier.append(neighbour)
    return component_count
