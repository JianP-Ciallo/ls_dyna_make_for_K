"""Real exterior-segment extraction for solver-complete ALE/FSI scenes."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace

from ..artifacts import MeshFragment, Node, ShellElement, SolidElement
from ..meshing import merge_fragments_welded
from .scene import SolverBlastScene
from .surface_topology import SurfaceTopology, classify_surface_topology


@dataclass(frozen=True, slots=True)
class FsiSegment:
    node_ids: tuple[int, int, int, int]
    owner_element_id: int
    owner_part_role: str
    area_m2: float
    normal: tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class FsiInterface:
    building_mesh: MeshFragment
    segments: tuple[FsiSegment, ...]
    ground_segments: tuple[FsiSegment, ...]
    building_ground_contact_segments: tuple[FsiSegment, ...]
    ground_contact_segments: tuple[FsiSegment, ...]
    fingerprint: str


_HEX8_FACES = (
    (0, 3, 2, 1),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (1, 2, 6, 5),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
)


def extract_fsi_segments(
    scene: SolverBlastScene,
    surface_topology: SurfaceTopology | None = None,
) -> FsiInterface:
    if not isinstance(scene, SolverBlastScene):
        raise TypeError("scene must be a SolverBlastScene")
    if surface_topology is None:
        surface_topology = classify_surface_topology(scene)
    if not isinstance(surface_topology, SurfaceTopology):
        raise TypeError("surface_topology must be a SurfaceTopology")
    if not surface_topology.belongs_to(scene):
        raise ValueError(
            "surface topology does not belong to this scene fingerprint"
        )
    building_mesh = surface_topology.building_mesh
    nodes = {row.node_id: row for row in building_mesh.nodes}
    selected: dict[tuple[int, tuple[int, int, int, int]], FsiSegment] = {}
    building_ground_contacts: dict[
        tuple[int, tuple[int, int, int, int]], FsiSegment
    ] = {}
    for row in surface_topology.surfaces:
        key = (row.owner_element_id, row.face_key)
        segment = FsiSegment(
            node_ids=row.node_ids,
            owner_element_id=row.owner_element_id,
            owner_part_role=row.owner_part_role,
            area_m2=row.area_m2,
            normal=row.normal,
        )
        if row.surface_class == "soil_contact":
            building_ground_contacts[key] = FsiSegment(
                node_ids=row.node_ids,
                owner_element_id=row.owner_element_id,
                owner_part_role=row.owner_part_role,
                area_m2=row.area_m2,
                normal=row.normal,
            )
            continue
        if row.surface_class not in {
            "external_air_exposed",
            "internal_air_exposed",
        }:
            continue
        if row.adjacent_active_air_component is None:
            continue
        selected[key] = segment

    segments = tuple(selected[key] for key in sorted(selected))
    if not segments:
        raise ValueError("physical building has no real exterior FSI segments")
    building_ground_contact_segments = tuple(
        building_ground_contacts[key] for key in sorted(building_ground_contacts)
    )
    if not building_ground_contact_segments:
        raise ValueError("physical building has no real ground-contact segments")
    ground_segments, ground_contact_segments = _extract_ground_segments(
        scene,
        building_ground_contact_segments,
        nodes,
    )
    if not ground_segments:
        raise ValueError("physical ground has no real air-exposed FSI segments")
    if not ground_contact_segments:
        raise ValueError("physical ground has no real building-contact segments")
    identity = {
        "schema_version": "phase18.solver_blast.fsi@2",
        "surface_topology_fingerprint": surface_topology.fingerprint,
        "building_mesh_fingerprint": building_mesh.fingerprint,
        "segments": [
            {
                "node_ids": list(row.node_ids),
                "owner_element_id": row.owner_element_id,
                "owner_part_role": row.owner_part_role,
                "area_m2": row.area_m2,
                "normal": list(row.normal),
            }
            for row in segments
        ],
        "ground_segments": [
            {
                "node_ids": list(row.node_ids),
                "owner_element_id": row.owner_element_id,
                "owner_part_role": row.owner_part_role,
                "area_m2": row.area_m2,
                "normal": list(row.normal),
            }
            for row in ground_segments
        ],
        "building_ground_contact_segments": [
            {
                "node_ids": list(row.node_ids),
                "owner_element_id": row.owner_element_id,
                "owner_part_role": row.owner_part_role,
                "area_m2": row.area_m2,
                "normal": list(row.normal),
            }
            for row in building_ground_contact_segments
        ],
        "ground_contact_segments": [
            {
                "node_ids": list(row.node_ids),
                "owner_element_id": row.owner_element_id,
                "owner_part_role": row.owner_part_role,
                "area_m2": row.area_m2,
                "normal": list(row.normal),
            }
            for row in ground_contact_segments
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return FsiInterface(
        building_mesh=building_mesh,
        segments=segments,
        ground_segments=ground_segments,
        building_ground_contact_segments=building_ground_contact_segments,
        ground_contact_segments=ground_contact_segments,
        fingerprint=fingerprint,
    )


def _extract_ground_segments(
    scene: SolverBlastScene,
    building_contacts: tuple[FsiSegment, ...],
    building_nodes: dict[int, Node],
) -> tuple[tuple[FsiSegment, ...], tuple[FsiSegment, ...]]:
    nodes = {
        node.node_id: node
        for fragment in scene.ground.fragments
        for node in fragment.nodes
    }
    face_owners: dict[
        tuple[int, int, int, int],
        list[tuple[SolidElement, tuple[int, int, int, int]]],
    ] = {}
    for fragment in scene.ground.fragments:
        for element in fragment.solids:
            for offsets in _HEX8_FACES:
                face = tuple(element.node_ids[index] for index in offsets)
                face_owners.setdefault(tuple(sorted(face)), []).append((element, face))

    contact_rectangles = _contact_rectangles(building_contacts, building_nodes)
    selected: list[FsiSegment] = []
    ground_contacts: list[FsiSegment] = []
    for key in sorted(face_owners):
        owners = face_owners[key]
        if len(owners) != 1:
            continue
        element, face = owners[0]
        oriented, normal, area = _orient_solid_face(face, element, nodes)
        if _is_far_ground_boundary(oriented, nodes, scene.ground.bounds_m):
            continue
        segment = FsiSegment(
            node_ids=oriented,
            owner_element_id=element.element_id,
            owner_part_role=scene.ground.part_role,
            area_m2=area,
            normal=normal,
        )
        if _face_matches_contact(oriented, nodes, contact_rectangles):
            ground_contacts.append(segment)
        else:
            selected.append(segment)
    return tuple(selected), tuple(ground_contacts)


def _contact_rectangles(
    contacts: tuple[FsiSegment, ...],
    nodes: dict[int, Node],
) -> tuple[tuple[str, float, str, float, float, str, float, float], ...]:
    rectangles: list[tuple[str, float, str, float, float, str, float, float]] = []
    for contact in contacts:
        plane = _axis_aligned_face_plane(contact.node_ids, nodes)
        if plane is None:
            raise ValueError("building-ground contact face must be axis aligned")
        axis, value, first_axis, second_axis = plane
        points = tuple(nodes[node_id] for node_id in contact.node_ids)
        rectangles.append(
            (
                axis,
                value,
                first_axis,
                min(getattr(node, first_axis) for node in points),
                max(getattr(node, first_axis) for node in points),
                second_axis,
                min(getattr(node, second_axis) for node in points),
                max(getattr(node, second_axis) for node in points),
            )
        )
    return tuple(rectangles)


def _face_matches_contact(
    face: tuple[int, int, int, int],
    nodes: dict[int, Node],
    rectangles: tuple[tuple[str, float, str, float, float, str, float, float], ...],
) -> bool:
    plane = _axis_aligned_face_plane(face, nodes)
    if plane is None:
        return False
    axis, value, first_axis, second_axis = plane
    tolerance = 1.0e-10
    points = tuple(nodes[node_id] for node_id in face)
    candidates = tuple(
        row for row in rectangles if row[0] == axis and abs(row[1] - value) <= tolerance
    )
    if not candidates:
        return False
    first_min = min(getattr(point, first_axis) for point in points)
    first_max = max(getattr(point, first_axis) for point in points)
    second_min = min(getattr(point, second_axis) for point in points)
    second_max = max(getattr(point, second_axis) for point in points)
    return any(
        min(first_max, row[4]) - max(first_min, row[3]) > tolerance
        and min(second_max, row[7]) - max(second_min, row[6]) > tolerance
        for row in candidates
    )


def _axis_aligned_face_plane(
    face: tuple[int, int, int, int],
    nodes: dict[int, Node],
) -> tuple[str, float, str, str] | None:
    tolerance = 1.0e-10
    points = tuple(nodes[node_id] for node_id in face)
    for axis, other_axes in (
        ("x", ("y", "z")),
        ("y", ("x", "z")),
        ("z", ("x", "y")),
    ):
        values = tuple(getattr(node, axis) for node in points)
        if max(values) - min(values) <= tolerance:
            return axis, sum(values) / len(values), other_axes[0], other_axes[1]
    return None


def _is_far_ground_boundary(
    face: tuple[int, int, int, int],
    nodes: dict[int, Node],
    bounds: tuple[float, float, float, float, float, float],
) -> bool:
    tolerance = 1.0e-10
    points = tuple(nodes[node_id] for node_id in face)
    return any(
        all(abs(getattr(node, axis) - value) <= tolerance for node in points)
        for axis, value in (
            ("x", bounds[0]),
            ("x", bounds[3]),
            ("y", bounds[1]),
            ("y", bounds[4]),
            ("z", bounds[2]),
        )
    )


def _assemble_building_mesh(scene: SolverBlastScene) -> MeshFragment:
    excluded = set(scene.building.excluded_base_part_roles)
    fragments = tuple(
        _filter_fragment(artifact.mesh, excluded)
        for artifact in scene.building.artifacts
    ) + tuple(
        _filter_fragment(fragment, frozenset())
        for fragment in scene.building.supplement_fragments
    )
    mesh = _detach_embedded_beam_nodes(
        scene,
        merge_fragments_welded(fragments),
    )
    if max(row.node_id for row in mesh.nodes) >= 20_000_001:
        raise ValueError("welded building node IDs exceed the reserved building range")
    elements = (*mesh.solids, *mesh.shells, *mesh.beams)
    if max(row.element_id for row in elements) >= 30_000_001:
        raise ValueError("welded building element IDs exceed the reserved building range")
    return mesh


def _detach_embedded_beam_nodes(
    scene: SolverBlastScene,
    mesh: MeshFragment,
) -> MeshFragment:
    """Keep embedded Beam geometry coincident without sharing Solid node IDs.

    LS-DYNA R12 rejects *CONSTRAINED_BEAM_IN_SOLID when a slave Beam node is
    also referenced by any Solid in the coupled master-part set.  Welding is
    still used for the structural geometry, then only coincident embedded-Beam
    endpoint identities are duplicated.  Their coordinates and Beam-to-Beam
    continuity remain unchanged.
    """
    embedded_roles = {
        role
        for interface in scene.building.interfaces
        if interface.connection_type == "embedded_beam_in_solid"
        for role in interface.source_roles
    }
    if not embedded_roles:
        return mesh
    solid_node_ids = {
        node_id for element in mesh.solids for node_id in element.node_ids
    }
    detached_source_ids = sorted(
        {
            node_id
            for element in mesh.beams
            if element.part_role in embedded_roles
            for node_id in element.node_ids
            if node_id in solid_node_ids
        }
    )
    if not detached_source_ids:
        return mesh
    next_node_id = max(node.node_id for node in mesh.nodes) + 1
    if next_node_id + len(detached_source_ids) > 20_000_001:
        raise ValueError("detached embedded Beam node IDs exceed the reserved building range")
    remap = {
        source_id: next_node_id + offset
        for offset, source_id in enumerate(detached_source_ids)
    }
    nodes = {node.node_id: node for node in mesh.nodes}
    detached_nodes = tuple(
        Node(remap[source_id], *nodes[source_id].coordinates)
        for source_id in detached_source_ids
    )
    beams = tuple(
        replace(
            element,
            node_ids=tuple(remap.get(node_id, node_id) for node_id in element.node_ids),
        )
        if element.part_role in embedded_roles
        else element
        for element in mesh.beams
    )
    return MeshFragment(
        nodes=(*mesh.nodes, *detached_nodes),
        solids=mesh.solids,
        shells=mesh.shells,
        beams=beams,
        part_bindings=mesh.part_bindings,
    )


def _filter_fragment(
    fragment: MeshFragment,
    excluded_roles: set[str] | frozenset[str],
) -> MeshFragment:
    solids = tuple(row for row in fragment.solids if row.part_role not in excluded_roles)
    shells = tuple(row for row in fragment.shells if row.part_role not in excluded_roles)
    beams = tuple(row for row in fragment.beams if row.part_role not in excluded_roles)
    retained_elements = (*solids, *shells, *beams)
    retained_roles = {row.part_role for row in retained_elements}
    retained_node_ids = {
        node_id for element in retained_elements for node_id in element.node_ids
    }
    return MeshFragment(
        nodes=tuple(
            row for row in fragment.nodes if row.node_id in retained_node_ids
        ),
        solids=solids,
        shells=shells,
        beams=beams,
        part_bindings=tuple(
            row for row in fragment.part_bindings if row.part_role in retained_roles
        ),
    )


def _orient_solid_face(
    face: tuple[int, int, int, int],
    element: SolidElement,
    nodes: dict[int, Node],
) -> tuple[tuple[int, int, int, int], tuple[float, float, float], float]:
    element_center = _centroid(element.node_ids, nodes)
    return _orient_face(face, nodes, _subtract(_centroid(face, nodes), element_center))


def _orient_shell_face(
    element: ShellElement,
    nodes: dict[int, Node],
    building_center: tuple[float, float, float],
) -> tuple[tuple[int, int, int, int], tuple[float, float, float], float]:
    face = element.node_ids
    return _orient_face(face, nodes, _subtract(_centroid(face, nodes), building_center))


def _orient_face(
    face: tuple[int, int, int, int],
    nodes: dict[int, Node],
    outward_reference: tuple[float, float, float],
) -> tuple[tuple[int, int, int, int], tuple[float, float, float], float]:
    points = tuple(nodes[node_id].coordinates for node_id in face)
    first = _cross(_subtract(points[1], points[0]), _subtract(points[2], points[0]))
    second = _cross(_subtract(points[2], points[0]), _subtract(points[3], points[0]))
    vector = tuple(first[index] + second[index] for index in range(3))
    magnitude = math.sqrt(_dot(vector, vector))
    area = 0.5 * (
        math.sqrt(_dot(first, first)) + math.sqrt(_dot(second, second))
    )
    if not math.isfinite(area) or area <= 1.0e-14 or magnitude <= 1.0e-14:
        raise ValueError("FSI segment has zero or non-finite area")
    normal = tuple(value / magnitude for value in vector)
    if _dot(normal, outward_reference) < 0.0:
        face = (face[0], face[3], face[2], face[1])
        normal = tuple(-value for value in normal)
    return face, normal, area


def _is_ground_contact(
    face: tuple[int, int, int, int],
    normal: tuple[float, float, float],
    nodes: dict[int, Node],
    scene: SolverBlastScene,
) -> bool:
    tolerance = 1.0e-10
    points = tuple(nodes[node_id] for node_id in face)
    if max(node.z for node in points) > scene.ground.grade_elevation_m + tolerance:
        return False
    if not scene.ground.excavation_bounds_m:
        return normal[2] < -0.5
    bounds = scene.building.bounds_m
    return any(
        all(abs(getattr(node, axis) - value) <= tolerance for node in points)
        for axis, value in (
            ("x", bounds[0]),
            ("x", bounds[3]),
            ("y", bounds[1]),
            ("y", bounds[4]),
            ("z", bounds[2]),
        )
    )


def _centroid(
    node_ids: tuple[int, ...],
    nodes: dict[int, Node],
) -> tuple[float, float, float]:
    return tuple(
        sum(nodes[node_id].coordinates[axis] for node_id in node_ids) / len(node_ids)
        for axis in range(3)
    )


def _subtract(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(left[index] - right[index] for index in range(3))


def _cross(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _dot(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    return sum(left[index] * right[index] for index in range(3))
