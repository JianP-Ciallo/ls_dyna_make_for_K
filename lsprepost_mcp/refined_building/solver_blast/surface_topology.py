"""Closed structural-surface classification for Phase 18 ALE/FSI scenes."""

from __future__ import annotations

import bisect
import hashlib
import json
import math
from collections import Counter, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from ..artifacts import BeamElement, MeshFragment, Node, ShellElement, SolidElement
from ..meshing import merge_fragments_welded
from ..spatial import AxisAlignedBox, SpatialTopology, compile_spatial_topology
from .air_topology import classify_ale_cell
from .ale_domain import AleDomainEstimate
from .ground import GroundModel
from .physical_building import PhysicalBuildingModel

if TYPE_CHECKING:
    from .scene import SolverBlastScene


SurfaceClass = Literal[
    "external_air_exposed",
    "internal_air_exposed",
    "soil_contact",
    "sealed_internal",
    "structural_connection",
]

SURFACE_CLASSES: tuple[SurfaceClass, ...] = (
    "external_air_exposed",
    "internal_air_exposed",
    "soil_contact",
    "sealed_internal",
    "structural_connection",
)

_HEX8_FACES = (
    (0, 3, 2, 1),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (1, 2, 6, 5),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
)
_TOLERANCE_M = 1.0e-10
_MAX_RAW_BUILDING_FACES = 2_000_000


@dataclass(frozen=True, slots=True)
class ClassifiedSurface:
    face_key: tuple[int, int, int, int]
    node_ids: tuple[int, int, int, int]
    owner_element_id: int
    owner_local_face_index: int
    owner_part_role: str
    owner_family: Literal["Solid", "Shell"]
    surface_class: SurfaceClass
    area_m2: float
    normal: tuple[float, float, float]
    adjacent_active_air_component: str | None


@dataclass(frozen=True, slots=True)
class SurfaceTopology:
    building_mesh: MeshFragment
    surfaces: tuple[ClassifiedSurface, ...]
    counts: Mapping[str, int]
    boundary_face_count: int
    unclassified_count: int
    multiply_classified_count: int
    source_scene_fingerprint: str
    source_building_fingerprint: str
    source_ground_fingerprint: str
    source_air_fingerprint: str
    fingerprint: str

    def belongs_to(self, scene: "SolverBlastScene") -> bool:
        return bool(
            self.source_scene_fingerprint == scene.fingerprint
            and self.source_building_fingerprint == scene.building.fingerprint
            and self.source_ground_fingerprint == scene.ground.fingerprint
            and self.source_air_fingerprint == scene.air.fingerprint
        )


@dataclass(frozen=True, slots=True)
class _FaceCandidate:
    node_ids: tuple[int, int, int, int]
    owner_element_id: int
    owner_local_face_index: int
    owner_part_role: str
    owner_family: Literal["Solid", "Shell"]
    area_m2: float
    normal: tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class _RectFace:
    axis: int
    coordinate: float
    sign: int
    first_axis: int
    second_axis: int
    first_min: float
    first_max: float
    second_min: float
    second_max: float

    @property
    def area(self) -> float:
        return (self.first_max - self.first_min) * (
            self.second_max - self.second_min
        )


@dataclass(frozen=True, slots=True)
class _PlaneRows:
    rows: tuple[_RectFace, ...]
    starts: tuple[float, ...]
    maximum_first_span: float


@dataclass(frozen=True, slots=True)
class _ArtifactAirSemantics:
    asset_id: str
    topology: SpatialTopology
    connected_space_ids: frozenset[str]
    opening_connections: tuple[
        tuple[str, AxisAlignedBox, tuple[str, str]],
        ...,
    ]
    full_section_barriers: Mapping[
        str,
        tuple[tuple[int, float, float], ...],
    ]


def classify_surface_topology(scene: "SolverBlastScene") -> SurfaceTopology:
    """Classify each real structural boundary face exactly once."""

    from .scene import SolverBlastScene

    if not isinstance(scene, SolverBlastScene):
        raise TypeError("scene must be a SolverBlastScene")
    mesh = assemble_building_mesh(scene.building)
    return _build_surface_topology(
        scene_fingerprint=scene.fingerprint,
        building=scene.building,
        ground=scene.ground,
        air=scene.air,
        mesh=mesh,
    )


def assemble_building_mesh(building: PhysicalBuildingModel) -> MeshFragment:
    """Build the one welded structural mesh shared by topology and keyword output."""

    if not isinstance(building, PhysicalBuildingModel):
        raise TypeError("building must be a PhysicalBuildingModel")
    excluded = set(building.excluded_base_part_roles)
    fragments = tuple(
        _split_ruled_shell_role_at_horizontal_plane(
            _filter_fragment(artifact.mesh, excluded),
            role="pavilion_glazing",
            elevation_m=building.grade_elevation_m,
        )
        for artifact in building.artifacts
    ) + tuple(
        _filter_fragment(fragment, frozenset())
        for fragment in building.supplement_fragments
    )
    mesh = _reconcile_solver_mesh(
        _detach_embedded_beam_nodes(
            building,
            merge_fragments_welded(fragments),
        )
    )
    if max(row.node_id for row in mesh.nodes) >= 20_000_001:
        raise ValueError("welded building node IDs exceed the reserved building range")
    elements = (*mesh.solids, *mesh.shells, *mesh.beams)
    if not elements:
        raise ValueError("physical building mesh contains no elements")
    if max(row.element_id for row in elements) >= 30_000_001:
        raise ValueError("welded building element IDs exceed the reserved building range")
    return mesh


def _reconcile_solver_mesh(mesh: MeshFragment) -> MeshFragment:
    """Reconcile exact shared bars and shell orientation after artifact welding."""

    nodes = {row.node_id: row for row in mesh.nodes}
    seen_beams: set[
        tuple[str, tuple[tuple[float, float, float], tuple[float, float, float]]]
    ] = set()
    joint_stirrup_index: dict[
        tuple[tuple[float, float, float], tuple[float, float, float]],
        int,
    ] = {}
    beams: list[BeamElement] = []
    for beam in sorted(mesh.beams, key=lambda row: row.element_id):
        endpoints = tuple(sorted(
            tuple(round(value, 12) for value in nodes[node_id].coordinates)
            for node_id in beam.node_ids
        ))
        key = beam.part_role, endpoints
        if key in seen_beams:
            continue
        seen_beams.add(key)
        if beam.part_role in {"column_stirrup", "beam_stirrup"}:
            previous_index = joint_stirrup_index.get(endpoints)
            if previous_index is not None:
                previous = beams[previous_index]
                if previous.part_role != beam.part_role:
                    # The column cage owns the joint core.  A coincident beam
                    # stirrup is not a second physical bar in the same space.
                    if beam.part_role == "column_stirrup":
                        beams[previous_index] = beam
                    continue
            else:
                joint_stirrup_index[endpoints] = len(beams)
        beams.append(beam)

    edge_owners: dict[
        tuple[str, tuple[int, int]],
        list[tuple[int, int, int]],
    ] = {}
    shells = tuple(sorted(mesh.shells, key=lambda row: row.element_id))
    for index, shell in enumerate(shells):
        for start, end in zip(
            shell.node_ids,
            (*shell.node_ids[1:], shell.node_ids[0]),
        ):
            edge_owners.setdefault(
                (shell.part_role, tuple(sorted((start, end)))),
                [],
            ).append((index, start, end))

    neighbours: dict[int, list[tuple[int, bool]]] = {}
    for owners in edge_owners.values():
        if len(owners) != 2:
            continue
        left, right = owners
        same_direction = left[1:] == right[1:]
        neighbours.setdefault(left[0], []).append((right[0], same_direction))
        neighbours.setdefault(right[0], []).append((left[0], same_direction))

    flips: dict[int, bool] = {}
    for root in range(len(shells)):
        if root in flips:
            continue
        flips[root] = False
        queue = deque((root,))
        while queue:
            current = queue.popleft()
            for neighbour, same_direction in neighbours.get(current, ()):
                expected = flips[current] ^ same_direction
                previous = flips.get(neighbour)
                if previous is not None:
                    if previous != expected:
                        raise ValueError(
                            "physical shell surface is not consistently orientable"
                        )
                    continue
                flips[neighbour] = expected
                queue.append(neighbour)

    oriented_shells = tuple(
        ShellElement(
            shell.element_id,
            (
                (shell.node_ids[0], *reversed(shell.node_ids[1:]))
                if flips[index]
                else shell.node_ids
            ),
            shell.part_role,
        )
        for index, shell in enumerate(shells)
    )
    used_node_ids = {
        node_id
        for element in (*mesh.solids, *oriented_shells, *beams)
        for node_id in element.node_ids
    }
    return MeshFragment(
        nodes=tuple(row for row in mesh.nodes if row.node_id in used_node_ids),
        solids=mesh.solids,
        shells=oriented_shells,
        beams=tuple(beams),
        part_bindings=mesh.part_bindings,
    )


def _build_surface_topology(
    *,
    scene_fingerprint: str,
    building: PhysicalBuildingModel,
    ground: GroundModel,
    air: AleDomainEstimate,
    mesh: MeshFragment,
) -> SurfaceTopology:
    raw_face_count = 6 * len(mesh.solids) + len(mesh.shells)
    if raw_face_count > _MAX_RAW_BUILDING_FACES:
        raise ValueError(
            "building surface-face budget exceeded before owner-table allocation: "
            f"estimated {raw_face_count}, limit {_MAX_RAW_BUILDING_FACES}"
        )
    nodes = {row.node_id: row for row in mesh.nodes}
    candidates = _boundary_candidates(mesh, nodes)
    ground_index = _ground_boundary_index(ground)
    semantics = _air_semantics(building, mesh, nodes)
    interface_roles = frozenset(
        role
        for interface in building.interfaces
        for role in (*interface.source_roles, *interface.target_roles)
    )
    epsilon = _probe_epsilon(mesh, air)
    surfaces: list[ClassifiedSurface] = []
    for candidate in candidates:
        soil_status = _ground_coverage(candidate, nodes, ground_index)
        if soil_status == "partial":
            raise ValueError(
                "structural surface has partial ground coverage; mesh contact must close"
            )
        if soil_status == "full":
            air_status = _candidate_air_status(candidate, nodes, air, epsilon)
            if air_status == "active":
                raise ValueError(
                    "external active-air path reaches soil-contact surface"
                )
            surface_class: SurfaceClass = "soil_contact"
            component = None
        else:
            surface_class, component = _classify_nonsoil_surface(
                candidate,
                nodes,
                semantics,
                interface_roles,
                air,
                epsilon,
            )
        surfaces.append(
            ClassifiedSurface(
                face_key=tuple(sorted(candidate.node_ids)),
                node_ids=candidate.node_ids,
                owner_element_id=candidate.owner_element_id,
                owner_local_face_index=candidate.owner_local_face_index,
                owner_part_role=candidate.owner_part_role,
                owner_family=candidate.owner_family,
                surface_class=surface_class,
                area_m2=candidate.area_m2,
                normal=candidate.normal,
                adjacent_active_air_component=component,
            )
        )
    surfaces.sort(
        key=lambda row: (
            row.owner_element_id,
            row.owner_local_face_index,
            row.face_key,
        )
    )
    instance_keys = tuple(
        (row.owner_element_id, row.face_key) for row in surfaces
    )
    multiply_classified = len(instance_keys) - len(set(instance_keys))
    if multiply_classified:
        raise ValueError("structural surface instance was classified more than once")
    observed = Counter(row.surface_class for row in surfaces)
    counts = MappingProxyType(
        {surface_class: observed[surface_class] for surface_class in SURFACE_CLASSES}
    )
    fingerprint = _surface_fingerprint(
        scene_fingerprint,
        building,
        ground,
        air,
        mesh,
        surfaces,
    )
    return SurfaceTopology(
        building_mesh=mesh,
        surfaces=tuple(surfaces),
        counts=counts,
        boundary_face_count=len(surfaces),
        unclassified_count=0,
        multiply_classified_count=0,
        source_scene_fingerprint=scene_fingerprint,
        source_building_fingerprint=building.fingerprint,
        source_ground_fingerprint=ground.fingerprint,
        source_air_fingerprint=air.fingerprint,
        fingerprint=fingerprint,
    )


def _boundary_candidates(
    mesh: MeshFragment,
    nodes: Mapping[int, Node],
) -> tuple[_FaceCandidate, ...]:
    solid_geometry_owners: dict[
        tuple[tuple[float, float, float], ...],
        SolidElement,
    ] = {}
    owners: dict[
        tuple[int, int, int, int],
        tuple[_FaceCandidate, ...],
    ] = {}
    for element in mesh.solids:
        geometry_key = tuple(
            sorted(
                tuple(round(value, 12) for value in nodes[node_id].coordinates)
                for node_id in element.node_ids
            )
        )
        previous = solid_geometry_owners.get(geometry_key)
        if previous is not None:
            raise ValueError(
                "coincident duplicate solid-volume owners are not permitted: "
                f"owners={previous.element_id}:{previous.part_role},"
                f"{element.element_id}:{element.part_role}"
            )
        solid_geometry_owners[geometry_key] = element
        for local_index, offsets in enumerate(_HEX8_FACES):
            face = tuple(element.node_ids[index] for index in offsets)
            oriented, normal, area = _orient_solid_face(face, element, nodes)
            candidate = _FaceCandidate(
                node_ids=oriented,
                owner_element_id=element.element_id,
                owner_local_face_index=local_index,
                owner_part_role=element.part_role,
                owner_family="Solid",
                area_m2=area,
                normal=normal,
            )
            key = tuple(sorted(face))
            rows = (*owners.get(key, ()), candidate)
            owners[key] = rows

    for key, rows in owners.items():
        if len(rows) <= 2:
            continue
        owner_summary = ", ".join(
            f"{row.owner_element_id}:{row.owner_part_role}" for row in rows
        )
        raise ValueError(
            "non-manifold structural face has more than two owners: "
            f"face={key}, owners=[{owner_summary}]"
        )

    result = [rows[0] for rows in owners.values() if len(rows) == 1]
    solid_keys = set(owners)
    for element in mesh.shells:
        key = tuple(sorted(element.node_ids))
        if key in solid_keys:
            continue
        oriented, normal, area = _shell_face_geometry(element, nodes)
        result.append(
            _FaceCandidate(
                node_ids=oriented,
                owner_element_id=element.element_id,
                owner_local_face_index=0,
                owner_part_role=element.part_role,
                owner_family="Shell",
                area_m2=area,
                normal=normal,
            )
        )
    return tuple(result)


def _air_semantics(
    building: PhysicalBuildingModel,
    mesh: MeshFragment,
    nodes: Mapping[int, Node],
) -> tuple[_ArtifactAirSemantics, ...]:
    element_boxes = tuple(
        _element_bounds(row.node_ids, nodes) for row in mesh.solids
    )
    shell_boxes = tuple(
        _element_bounds(row.node_ids, nodes) for row in mesh.shells
    )
    result: list[_ArtifactAirSemantics] = []
    for artifact in building.artifacts:
        topology = compile_spatial_topology(artifact.normalized_input)
        if topology.to_manifest() != artifact.topology_manifest:
            raise ValueError(
                "artifact topology_manifest does not match normalized_input"
            )
        raw_openings = artifact.normalized_input.get("openings")
        if not isinstance(raw_openings, list):
            raise ValueError("artifact normalized openings must be a list")
        topology_openings = dict(topology.opening_regions)
        adjacency: dict[str, set[str]] = {
            key: set() for key in topology.adjacency
        }
        opening_connections: list[
            tuple[str, AxisAlignedBox, tuple[str, str]]
        ] = []
        for raw in raw_openings:
            if not isinstance(raw, Mapping):
                raise ValueError("artifact opening row must be a mapping")
            opening_id = raw.get("id")
            connects = raw.get("connects")
            if (
                not isinstance(opening_id, str)
                or opening_id not in topology_openings
                or not isinstance(connects, list)
                or len(connects) != 2
            ):
                raise ValueError("artifact opening identity is invalid")
            box = topology_openings[opening_id]
            has_aperture = _opening_has_positive_aperture(
                box,
                element_boxes,
                shell_boxes,
            )
            if not has_aperture:
                if "exterior" in connects:
                    raise ValueError(
                        f"opening {opening_id!r} has no positive-area mesh aperture"
                    )
                continue
            left, right = str(connects[0]), str(connects[1])
            opening_connections.append((opening_id, box, (left, right)))
            adjacency.setdefault(left, set()).add(right)
            adjacency.setdefault(right, set()).add(left)
        connected = _reachable(adjacency, "exterior")
        result.append(
            _ArtifactAirSemantics(
                asset_id=artifact.asset_id,
                topology=topology,
                connected_space_ids=frozenset(connected),
                opening_connections=tuple(sorted(opening_connections)),
                full_section_barriers=_full_section_barriers(
                    topology,
                    element_boxes,
                    shell_boxes,
                ),
            )
        )
    return tuple(result)


def _full_section_barriers(
    topology: SpatialTopology,
    solid_boxes: Sequence[tuple[float, float, float, float, float, float]],
    shell_boxes: Sequence[tuple[float, float, float, float, float, float]],
) -> Mapping[str, tuple[tuple[int, float, float], ...]]:
    result: dict[str, tuple[tuple[int, float, float], ...]] = {}
    typed_boxes = tuple((box, False) for box in solid_boxes) + tuple(
        (box, True) for box in shell_boxes
    )
    for space_id, space in topology.void_regions:
        bounds = space.as_tuple()
        barriers: list[tuple[int, float, float]] = []
        for axis in range(3):
            projected = tuple(index for index in range(3) if index != axis)
            target = (
                bounds[projected[0]],
                bounds[projected[0] + 3],
                bounds[projected[1]],
                bounds[projected[1] + 3],
            )
            target_area = (target[1] - target[0]) * (target[3] - target[2])
            grouped: dict[
                tuple[float, float],
                list[tuple[float, float, float, float]],
            ] = {}
            for box, is_shell in typed_boxes:
                lower = max(bounds[axis], box[axis])
                upper = min(bounds[axis + 3], box[axis + 3])
                if upper - lower <= _TOLERANCE_M and not is_shell:
                    continue
                if is_shell:
                    coordinate = 0.5 * (box[axis] + box[axis + 3])
                    if not (
                        bounds[axis] - _TOLERANCE_M
                        <= coordinate
                        <= bounds[axis + 3] + _TOLERANCE_M
                    ):
                        continue
                    lower = upper = coordinate
                rectangle = _clip_projected_rectangle(box, projected, target)
                if rectangle is None:
                    continue
                grouped.setdefault(
                    (round(lower, 12), round(upper, 12)),
                    [],
                ).append(rectangle)
            tolerance = max(1.0e-12, target_area * 1.0e-9)
            for (lower, upper), rectangles in grouped.items():
                possible_area = math.fsum(
                    (row[1] - row[0]) * (row[3] - row[2])
                    for row in rectangles
                )
                if possible_area < target_area - tolerance:
                    continue
                covered_area = _projected_rectangle_union_area(rectangles, target)
                if math.isclose(
                    covered_area,
                    target_area,
                    rel_tol=0.0,
                    abs_tol=tolerance,
                ):
                    barriers.append((axis, lower, upper))
        result[space_id] = tuple(sorted(set(barriers)))
    return MappingProxyType(result)


def _projected_rectangle_union_area(
    rectangles: Sequence[tuple[float, float, float, float]],
    target: tuple[float, float, float, float],
) -> float:
    first_breaks = sorted(
        {target[0], target[1], *(value for row in rectangles for value in row[:2])}
    )
    second_breaks = sorted(
        {target[2], target[3], *(value for row in rectangles for value in row[2:])}
    )
    area = 0.0
    for first_left, first_right in zip(first_breaks, first_breaks[1:]):
        if first_right - first_left <= _TOLERANCE_M:
            continue
        first_center = 0.5 * (first_left + first_right)
        for second_left, second_right in zip(second_breaks, second_breaks[1:]):
            if second_right - second_left <= _TOLERANCE_M:
                continue
            second_center = 0.5 * (second_left + second_right)
            if any(
                row[0] - _TOLERANCE_M <= first_center <= row[1] + _TOLERANCE_M
                and row[2] - _TOLERANCE_M
                <= second_center
                <= row[3] + _TOLERANCE_M
                for row in rectangles
            ):
                area += (first_right - first_left) * (
                    second_right - second_left
                )
    return area


def _opening_has_positive_aperture(
    opening: AxisAlignedBox,
    solid_boxes: Sequence[tuple[float, float, float, float, float, float]],
    shell_boxes: Sequence[tuple[float, float, float, float, float, float]],
) -> bool:
    bounds = opening.as_tuple()
    spans = tuple(bounds[index + 3] - bounds[index] for index in range(3))
    thin_axis = min(range(3), key=lambda index: spans[index])
    projected = tuple(index for index in range(3) if index != thin_axis)
    target = (
        bounds[projected[0]],
        bounds[projected[0] + 3],
        bounds[projected[1]],
        bounds[projected[1] + 3],
    )
    solid_layers: list[
        tuple[tuple[float, float, float, float], float, float]
    ] = []
    for box in solid_boxes:
        thin_min = max(bounds[thin_axis], box[thin_axis])
        thin_max = min(bounds[thin_axis + 3], box[thin_axis + 3])
        if thin_max - thin_min <= _TOLERANCE_M:
            continue
        rectangle = _clip_projected_rectangle(box, projected, target)
        if rectangle is not None:
            solid_layers.append((rectangle, thin_min, thin_max))
    shell_barriers: list[tuple[float, float, float, float]] = []
    for box in shell_boxes:
        shell_span = box[thin_axis + 3] - box[thin_axis]
        if shell_span > _TOLERANCE_M:
            continue
        coordinate = 0.5 * (box[thin_axis] + box[thin_axis + 3])
        if not bounds[thin_axis] - _TOLERANCE_M <= coordinate <= bounds[thin_axis + 3] + _TOLERANCE_M:
            continue
        rectangle = _clip_projected_rectangle(box, projected, target)
        if rectangle is not None:
            shell_barriers.append(rectangle)
    target_area = (target[1] - target[0]) * (target[3] - target[2])
    covered = _through_thickness_blocked_area(
        solid_layers,
        shell_barriers,
        target,
        (bounds[thin_axis], bounds[thin_axis + 3]),
    )
    return target_area - covered > max(1.0e-12, target_area * 1.0e-9)


def _clip_projected_rectangle(
    box: Sequence[float],
    axes: tuple[int, int],
    target: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    clipped = (
        max(target[0], box[axes[0]]),
        min(target[1], box[axes[0] + 3]),
        max(target[2], box[axes[1]]),
        min(target[3], box[axes[1] + 3]),
    )
    if (
        clipped[1] - clipped[0] <= _TOLERANCE_M
        or clipped[3] - clipped[2] <= _TOLERANCE_M
    ):
        return None
    return clipped


def _through_thickness_blocked_area(
    solid_layers: Sequence[
        tuple[tuple[float, float, float, float], float, float]
    ],
    shell_barriers: Sequence[tuple[float, float, float, float]],
    target: tuple[float, float, float, float],
    thin_target: tuple[float, float],
) -> float:
    rectangles = tuple(row[0] for row in solid_layers) + tuple(shell_barriers)
    if not rectangles:
        return 0.0
    first_breaks = sorted(
        {
            target[0],
            target[1],
            *(value for row in rectangles for value in row[:2]),
        }
    )
    second_breaks = sorted(
        {target[2], target[3], *(value for row in rectangles for value in row[2:])}
    )
    area = 0.0
    for first_left, first_right in zip(first_breaks, first_breaks[1:]):
        if first_right - first_left <= _TOLERANCE_M:
            continue
        first_center = 0.5 * (first_left + first_right)
        for second_left, second_right in zip(second_breaks, second_breaks[1:]):
            if second_right - second_left <= _TOLERANCE_M:
                continue
            second_center = 0.5 * (second_left + second_right)
            shell_blocked = any(
                row[0] - _TOLERANCE_M <= first_center <= row[1] + _TOLERANCE_M
                and row[2] - _TOLERANCE_M <= second_center <= row[3] + _TOLERANCE_M
                for row in shell_barriers
            )
            solid_intervals = tuple(
                (thin_min, thin_max)
                for rectangle, thin_min, thin_max in solid_layers
                if rectangle[0] - _TOLERANCE_M
                <= first_center
                <= rectangle[1] + _TOLERANCE_M
                and rectangle[2] - _TOLERANCE_M
                <= second_center
                <= rectangle[3] + _TOLERANCE_M
            )
            if shell_blocked or solid_intervals:
                area += (first_right - first_left) * (
                    second_right - second_left
                )
    return area


def _intervals_cover_target(
    intervals: Sequence[tuple[float, float]],
    target: tuple[float, float],
) -> bool:
    cursor = target[0]
    for lower, upper in sorted(intervals):
        if upper <= cursor + _TOLERANCE_M:
            continue
        if lower > cursor + _TOLERANCE_M:
            return False
        cursor = max(cursor, upper)
        if cursor >= target[1] - _TOLERANCE_M:
            return True
    return False


def _reachable(adjacency: Mapping[str, set[str]], start: str) -> set[str]:
    if start not in adjacency:
        return set()
    reached = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for neighbour in adjacency.get(current, set()):
            if neighbour not in reached:
                reached.add(neighbour)
                queue.append(neighbour)
    return reached


def _classify_nonsoil_surface(
    candidate: _FaceCandidate,
    nodes: Mapping[int, Node],
    semantics: Sequence[_ArtifactAirSemantics],
    interface_roles: frozenset[str],
    air: AleDomainEstimate,
    epsilon: float,
) -> tuple[SurfaceClass, str | None]:
    centroid = _centroid(candidate.node_ids, nodes)
    directions = (1.0,) if candidate.owner_family == "Solid" else (1.0, -1.0)
    exposures: list[tuple[SurfaceClass, str]] = []
    any_semantic_component = False
    any_active = False
    for direction in directions:
        probe = tuple(
            centroid[index]
            + direction * epsilon * candidate.normal[index]
            for index in range(3)
        )
        component_kind, component = _point_component(probe, semantics)
        if component_kind is None and _probe_points_through_exterior_skin(
            probe,
            tuple(
                direction * candidate.normal[index] for index in range(3)
            ),
            semantics,
        ):
            component_kind, component = "external", "external"
        if component_kind is not None:
            any_semantic_component = True
        status = _candidate_air_status(
            candidate,
            nodes,
            air,
            epsilon,
            direction=direction,
        )
        if status == "mixed":
            coordinates = tuple(
                nodes[node_id].coordinates for node_id in candidate.node_ids
            )
            raise ValueError(
                "structural surface spans mixed active-air, buffer, TNT, or "
                f"domain coverage: owner={candidate.owner_element_id}:"
                f"{candidate.owner_part_role}, face={coordinates}"
            )
        if status != "active":
            continue
        any_active = True
        if component_kind == "external":
            exposures.append(("external_air_exposed", "external"))
        elif (
            component_kind == "internal_connected"
            and component is not None
            and _internal_probe_reaches_exterior(probe, component, semantics)
        ):
            exposures.append(("internal_air_exposed", component))
    if exposures:
        exposures.sort(
            key=lambda row: (0 if row[0] == "external_air_exposed" else 1, row[1])
        )
        return exposures[0]
    if (
        not any_semantic_component
        and not any_active
        and candidate.owner_part_role in interface_roles
    ):
        return "structural_connection", None
    return "sealed_internal", None


def _internal_probe_reaches_exterior(
    point: tuple[float, float, float],
    component: str,
    semantics: Sequence[_ArtifactAirSemantics],
) -> bool:
    prefix = "internal:"
    if not component.startswith(prefix):
        return False
    identity = component[len(prefix):]
    asset_id, separator, initial_space_id = identity.rpartition(":")
    if not separator:
        return False
    artifact = next(
        (row for row in semantics if row.asset_id == asset_id),
        None,
    )
    if artifact is None:
        return False
    spaces = dict(artifact.topology.void_regions)
    if initial_space_id not in spaces:
        return False
    openings_by_space: dict[
        str,
        list[tuple[str, AxisAlignedBox, str]],
    ] = {}
    for opening_id, box, connects in artifact.opening_connections:
        left, right = connects
        openings_by_space.setdefault(left, []).append((opening_id, box, right))
        openings_by_space.setdefault(right, []).append((opening_id, box, left))
    queue = deque([(initial_space_id, point, "probe")])
    visited: set[tuple[str, str]] = set()
    while queue:
        space_id, origin, entry_id = queue.popleft()
        state = (space_id, entry_id)
        if state in visited:
            continue
        visited.add(state)
        space = spaces.get(space_id)
        if space is None:
            continue
        barriers = artifact.full_section_barriers.get(space_id, ())
        for opening_id, opening, neighbour in openings_by_space.get(space_id, ()):
            if opening_id == entry_id:
                continue
            target = _opening_point_inside_space(opening, space)
            if _full_section_barrier_separates(origin, target, barriers):
                continue
            if neighbour == "exterior":
                return True
            neighbour_space = spaces.get(neighbour)
            if neighbour_space is None:
                continue
            queue.append(
                (
                    neighbour,
                    _opening_point_inside_space(opening, neighbour_space),
                    opening_id,
                )
            )
    return False


def _opening_point_inside_space(
    opening: AxisAlignedBox,
    space: AxisAlignedBox,
) -> tuple[float, float, float]:
    opening_bounds = opening.as_tuple()
    space_bounds = space.as_tuple()
    epsilon = max(
        _TOLERANCE_M * 10.0,
        min(
            space_bounds[axis + 3] - space_bounds[axis]
            for axis in range(3)
        )
        * 1.0e-8,
    )
    return tuple(
        min(
            space_bounds[axis + 3] - epsilon,
            max(
                space_bounds[axis] + epsilon,
                0.5 * (opening_bounds[axis] + opening_bounds[axis + 3]),
            ),
        )
        for axis in range(3)
    )


def _full_section_barrier_separates(
    start: Sequence[float],
    target: Sequence[float],
    barriers: Sequence[tuple[int, float, float]],
) -> bool:
    for axis, lower, upper in barriers:
        path_min = min(start[axis], target[axis])
        path_max = max(start[axis], target[axis])
        if (
            path_min < lower - _TOLERANCE_M
            and path_max > upper + _TOLERANCE_M
        ):
            return True
    return False


def _point_component(
    point: tuple[float, float, float],
    semantics: Sequence[_ArtifactAirSemantics],
) -> tuple[str | None, str | None]:
    containing_envelopes = 0
    matched: list[tuple[str, str, bool]] = []
    for artifact in semantics:
        if artifact.topology.envelope.contains_point(point):
            containing_envelopes += 1
        for space_id, box in artifact.topology.void_regions:
            if _strictly_inside(box, point):
                matched.append(
                    (
                        artifact.asset_id,
                        space_id,
                        space_id in artifact.connected_space_ids,
                    )
                )
    if len(matched) > 1:
        raise ValueError("surface probe lies in multiple declared air spaces")
    if matched:
        asset_id, space_id, connected = matched[0]
        if connected:
            return "internal_connected", f"internal:{asset_id}:{space_id}"
        return "internal_sealed", f"sealed:{asset_id}:{space_id}"
    if containing_envelopes == 0:
        return "external", "external"
    return None, None


def _probe_points_through_exterior_skin(
    point: tuple[float, float, float],
    direction: tuple[float, float, float],
    semantics: Sequence[_ArtifactAirSemantics],
) -> bool:
    """Recognize offset facade/glazing skins between void and envelope bounds."""

    maximum_skin = 0.5
    for artifact in semantics:
        envelope = artifact.topology.envelope
        if not envelope.contains_point(point):
            continue
        envelope_bounds = envelope.as_tuple()
        voids = tuple(box for _space_id, box in artifact.topology.void_regions)
        for axis in range(3):
            if direction[axis] < -_TOLERANCE_M:
                gaps = tuple(
                    box.as_tuple()[axis] - envelope_bounds[axis]
                    for box in voids
                    if box.as_tuple()[axis] > envelope_bounds[axis] + _TOLERANCE_M
                )
                skin = min(maximum_skin, min(gaps, default=maximum_skin))
                if point[axis] - envelope_bounds[axis] <= skin + _TOLERANCE_M:
                    return True
            if direction[axis] > _TOLERANCE_M:
                gaps = tuple(
                    envelope_bounds[axis + 3] - box.as_tuple()[axis + 3]
                    for box in voids
                    if box.as_tuple()[axis + 3]
                    < envelope_bounds[axis + 3] - _TOLERANCE_M
                )
                skin = min(maximum_skin, min(gaps, default=maximum_skin))
                if (
                    envelope_bounds[axis + 3] - point[axis]
                    <= skin + _TOLERANCE_M
                ):
                    return True
    return False


def _candidate_air_status(
    candidate: _FaceCandidate,
    nodes: Mapping[int, Node],
    air: AleDomainEstimate,
    epsilon: float,
    *,
    direction: float = 1.0,
) -> str:
    rect = _axis_aligned_rectangle(candidate.node_ids, nodes, candidate.normal)
    if rect is not None:
        sign = rect.sign if direction > 0.0 else -rect.sign
        return _ale_rectangle_side_status(rect, sign, air, epsilon)
    return _ale_polygon_side_status(candidate, nodes, air, epsilon, direction)


def _ale_polygon_side_status(
    candidate: _FaceCandidate,
    nodes: Mapping[int, Node],
    air: AleDomainEstimate,
    epsilon: float,
    direction: float,
) -> str:
    """Classify the ALE cells touched by a positive area of an offset face."""

    offset = tuple(
        direction * epsilon * candidate.normal[axis] for axis in range(3)
    )
    points = tuple(
        tuple(nodes[node_id].coordinates[axis] + offset[axis] for axis in range(3))
        for node_id in candidate.node_ids
    )
    kinds: set[str] = set()
    for triangle in (
        (points[0], points[1], points[2]),
        (points[0], points[2], points[3]),
    ):
        triangle_area = _polygon_area_3d(triangle)
        if triangle_area <= 1.0e-14:
            continue
        area_tolerance = max(1.0e-14, triangle_area * 1.0e-10)
        bounds = tuple(
            (
                min(point[axis] for point in triangle),
                max(point[axis] for point in triangle),
            )
            for axis in range(3)
        )
        interval_indices = tuple(
            _surface_interval_candidates(axis, lower, upper)
            for axis, (lower, upper) in zip(
                (air.x_coordinates, air.y_coordinates, air.z_coordinates),
                bounds,
            )
        )
        if any(not rows for rows in interval_indices):
            continue
        for ix in interval_indices[0]:
            for iy in interval_indices[1]:
                for iz in interval_indices[2]:
                    cell_bounds = (
                        air.x_coordinates[ix],
                        air.y_coordinates[iy],
                        air.z_coordinates[iz],
                        air.x_coordinates[ix + 1],
                        air.y_coordinates[iy + 1],
                        air.z_coordinates[iz + 1],
                    )
                    clipped = _clip_polygon_to_box(triangle, cell_bounds)
                    if _polygon_area_3d(clipped) <= area_tolerance:
                        continue
                    kinds.add(classify_ale_cell(air, ix, iy, iz))
                    if "explicit_tnt" in kinds or kinds >= {
                        "active_air",
                        "coupling_buffer",
                    }:
                        return "mixed"

    if kinds == {"active_air"}:
        return "active"
    if not kinds:
        return "absent"
    if kinds == {"coupling_buffer"}:
        return "inactive"
    return "mixed"


def _surface_interval_candidates(
    axis: tuple[float, ...],
    lower: float,
    upper: float,
) -> tuple[int, ...]:
    """Return cells whose closed interval can share surface area with a face."""

    start = max(0, bisect.bisect_left(axis, lower) - 1)
    stop = min(len(axis) - 1, bisect.bisect_right(axis, upper))
    return tuple(
        index
        for index in range(start, stop)
        if axis[index + 1] >= lower - _TOLERANCE_M
        and axis[index] <= upper + _TOLERANCE_M
    )


def _clip_polygon_to_box(
    polygon: Sequence[tuple[float, float, float]],
    bounds: Sequence[float],
) -> tuple[tuple[float, float, float], ...]:
    clipped = tuple(polygon)
    for axis in range(3):
        clipped = _clip_polygon_halfspace(
            clipped, axis, float(bounds[axis]), keep_above=True
        )
        if len(clipped) < 3:
            return ()
        clipped = _clip_polygon_halfspace(
            clipped, axis, float(bounds[axis + 3]), keep_above=False
        )
        if len(clipped) < 3:
            return ()
    return clipped


def _clip_polygon_halfspace(
    polygon: Sequence[tuple[float, float, float]],
    axis: int,
    boundary: float,
    *,
    keep_above: bool,
) -> tuple[tuple[float, float, float], ...]:
    if not polygon:
        return ()

    def inside(point: Sequence[float]) -> bool:
        if keep_above:
            return point[axis] >= boundary - _TOLERANCE_M
        return point[axis] <= boundary + _TOLERANCE_M

    result: list[tuple[float, float, float]] = []
    previous = polygon[-1]
    previous_inside = inside(previous)
    for current in polygon:
        current_inside = inside(current)
        if current_inside != previous_inside:
            denominator = current[axis] - previous[axis]
            if abs(denominator) > 1.0e-15:
                fraction = (boundary - previous[axis]) / denominator
                fraction = min(1.0, max(0.0, fraction))
                result.append(
                    tuple(
                        previous[index]
                        + fraction * (current[index] - previous[index])
                        for index in range(3)
                    )
                )
        if current_inside:
            result.append(tuple(float(value) for value in current))
        previous = current
        previous_inside = current_inside
    return tuple(result)


def _polygon_area_3d(
    polygon: Sequence[tuple[float, float, float]],
) -> float:
    if len(polygon) < 3:
        return 0.0
    origin = polygon[0]
    return 0.5 * math.fsum(
        math.sqrt(_dot(cross, cross))
        for index in range(1, len(polygon) - 1)
        for cross in (
            _cross(
                _subtract(polygon[index], origin),
                _subtract(polygon[index + 1], origin),
            ),
        )
    )


def _ale_rectangle_side_status(
    rect: _RectFace,
    sign: int,
    air: AleDomainEstimate,
    epsilon: float,
) -> str:
    axes = (air.x_coordinates, air.y_coordinates, air.z_coordinates)
    normal_probe = rect.coordinate + sign * epsilon
    normal_index = bisect.bisect_right(axes[rect.axis], normal_probe) - 1
    if normal_index < 0 or normal_index >= len(axes[rect.axis]) - 1:
        return "absent"
    first_indices = _overlapping_intervals(
        axes[rect.first_axis], rect.first_min, rect.first_max
    )
    second_indices = _overlapping_intervals(
        axes[rect.second_axis], rect.second_min, rect.second_max
    )
    if not first_indices or not second_indices:
        return "absent"
    first_coverage = math.fsum(
        min(axes[rect.first_axis][index + 1], rect.first_max)
        - max(axes[rect.first_axis][index], rect.first_min)
        for index in first_indices
    )
    second_coverage = math.fsum(
        min(axes[rect.second_axis][index + 1], rect.second_max)
        - max(axes[rect.second_axis][index], rect.second_min)
        for index in second_indices
    )
    covered_area = first_coverage * second_coverage
    if covered_area <= _TOLERANCE_M:
        return "absent"
    full_coverage = math.isclose(
        covered_area,
        rect.area,
        rel_tol=0.0,
        abs_tol=max(1.0e-12, rect.area * 1.0e-9),
    )
    kinds: set[str] = set()
    for first_index in first_indices:
        for second_index in second_indices:
            indices = [0, 0, 0]
            indices[rect.axis] = normal_index
            indices[rect.first_axis] = first_index
            indices[rect.second_axis] = second_index
            kinds.add(classify_ale_cell(air, *indices))
    if not full_coverage:
        if "explicit_tnt" in kinds or len(kinds) > 1:
            return "mixed"
        if kinds == {"active_air"}:
            return "active"
        return "inactive"
    if kinds == {"active_air"}:
        return "active"
    if "active_air" in kinds or "explicit_tnt" in kinds:
        return "mixed"
    return "inactive"


def _overlapping_intervals(
    axis: tuple[float, ...],
    lower: float,
    upper: float,
) -> tuple[int, ...]:
    start = max(0, bisect.bisect_right(axis, lower) - 1)
    stop = min(len(axis) - 1, bisect.bisect_left(axis, upper) + 1)
    return tuple(
        index
        for index in range(start, stop)
        if min(axis[index + 1], upper) - max(axis[index], lower) > _TOLERANCE_M
    )


def _ground_boundary_index(
    ground: GroundModel,
) -> dict[tuple[int, float, int], _PlaneRows]:
    rows_by_plane: dict[tuple[int, float, int], list[_RectFace]] = {}
    for fragment in ground.fragments:
        nodes = {row.node_id: row for row in fragment.nodes}
        owners: dict[
            tuple[int, int, int, int],
            tuple[SolidElement, tuple[int, int, int, int]] | None,
        ] = {}
        counts: Counter[tuple[int, int, int, int]] = Counter()
        for element in fragment.solids:
            for offsets in _HEX8_FACES:
                face = tuple(element.node_ids[index] for index in offsets)
                key = tuple(sorted(face))
                counts[key] += 1
                if counts[key] > 2:
                    raise ValueError("non-manifold ground face has more than two owners")
                owners[key] = (element, face)
        for key, count in counts.items():
            if count != 1:
                continue
            owner = owners[key]
            assert owner is not None
            element, face = owner
            oriented, normal, _area = _orient_solid_face(face, element, nodes)
            rect = _axis_aligned_rectangle(oriented, nodes, normal)
            if rect is None:
                raise ValueError("ground boundary face must be axis aligned")
            plane_key = (rect.axis, round(rect.coordinate, 12), rect.sign)
            rows_by_plane.setdefault(plane_key, []).append(rect)
    result: dict[tuple[int, float, int], _PlaneRows] = {}
    for key, rows in rows_by_plane.items():
        rows.sort(
            key=lambda row: (
                row.first_min,
                row.second_min,
                row.first_max,
                row.second_max,
            )
        )
        result[key] = _PlaneRows(
            rows=tuple(rows),
            starts=tuple(row.first_min for row in rows),
            maximum_first_span=max(row.first_max - row.first_min for row in rows),
        )
    return result


def _ground_coverage(
    candidate: _FaceCandidate,
    nodes: Mapping[int, Node],
    index: Mapping[tuple[int, float, int], _PlaneRows],
) -> str:
    rect = _axis_aligned_rectangle(candidate.node_ids, nodes, candidate.normal)
    if rect is None:
        return "none"
    rows = index.get((rect.axis, round(rect.coordinate, 12), -rect.sign))
    if rows is None:
        return "none"
    start = bisect.bisect_left(
        rows.starts,
        rect.first_min - rows.maximum_first_span - _TOLERANCE_M,
    )
    stop = bisect.bisect_right(rows.starts, rect.first_max + _TOLERANCE_M)
    coverage = 0.0
    for ground_rect in rows.rows[start:stop]:
        first = min(rect.first_max, ground_rect.first_max) - max(
            rect.first_min, ground_rect.first_min
        )
        second = min(rect.second_max, ground_rect.second_max) - max(
            rect.second_min, ground_rect.second_min
        )
        if first > _TOLERANCE_M and second > _TOLERANCE_M:
            coverage += first * second
    tolerance = max(1.0e-12, rect.area * 1.0e-8)
    if coverage <= tolerance:
        return "none"
    if math.isclose(coverage, rect.area, rel_tol=0.0, abs_tol=tolerance):
        return "full"
    if coverage > rect.area + tolerance:
        raise ValueError("ground boundary faces overlap on a structural contact")
    return "partial"


def _axis_aligned_rectangle(
    face: tuple[int, int, int, int],
    nodes: Mapping[int, Node],
    normal: tuple[float, float, float],
) -> _RectFace | None:
    points = tuple(nodes[node_id].coordinates for node_id in face)
    fixed = tuple(
        axis
        for axis in range(3)
        if max(point[axis] for point in points)
        - min(point[axis] for point in points)
        <= _TOLERANCE_M
    )
    if len(fixed) != 1:
        return None
    axis = fixed[0]
    other = tuple(index for index in range(3) if index != axis)
    first_min = min(point[other[0]] for point in points)
    first_max = max(point[other[0]] for point in points)
    second_min = min(point[other[1]] for point in points)
    second_max = max(point[other[1]] for point in points)
    if (
        first_max - first_min <= _TOLERANCE_M
        or second_max - second_min <= _TOLERANCE_M
    ):
        return None
    rectangle_area = (first_max - first_min) * (second_max - second_min)
    _oriented, _normal, area = _orient_face(face, nodes, normal)
    if not math.isclose(
        rectangle_area,
        area,
        rel_tol=0.0,
        abs_tol=max(1.0e-12, rectangle_area * 1.0e-8),
    ):
        return None
    return _RectFace(
        axis=axis,
        coordinate=math.fsum(point[axis] for point in points) / len(points),
        sign=1 if normal[axis] >= 0.0 else -1,
        first_axis=other[0],
        second_axis=other[1],
        first_min=first_min,
        first_max=first_max,
        second_min=second_min,
        second_max=second_max,
    )


def _orient_solid_face(
    face: tuple[int, int, int, int],
    element: SolidElement,
    nodes: Mapping[int, Node],
) -> tuple[tuple[int, int, int, int], tuple[float, float, float], float]:
    reference = _subtract(
        _centroid(face, nodes),
        _centroid(element.node_ids, nodes),
    )
    return _orient_face(face, nodes, reference)


def _shell_face_geometry(
    element: ShellElement,
    nodes: Mapping[int, Node],
) -> tuple[tuple[int, int, int, int], tuple[float, float, float], float]:
    face = element.node_ids
    points = tuple(nodes[node_id].coordinates for node_id in face)
    first = _cross(_subtract(points[1], points[0]), _subtract(points[2], points[0]))
    second = _cross(_subtract(points[2], points[0]), _subtract(points[3], points[0]))
    vector = tuple(first[index] + second[index] for index in range(3))
    magnitude = math.sqrt(_dot(vector, vector))
    area = 0.5 * (
        math.sqrt(_dot(first, first)) + math.sqrt(_dot(second, second))
    )
    if not math.isfinite(area) or area <= 1.0e-14 or magnitude <= 1.0e-14:
        raise ValueError("structural Shell surface has zero or non-finite area")
    return face, tuple(value / magnitude for value in vector), area


def _orient_face(
    face: tuple[int, int, int, int],
    nodes: Mapping[int, Node],
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
        raise ValueError("structural surface has zero or non-finite area")
    normal = tuple(value / magnitude for value in vector)
    if _dot(normal, outward_reference) < 0.0:
        face = (face[0], face[3], face[2], face[1])
        normal = tuple(-value for value in normal)
    return face, normal, area


def _probe_epsilon(mesh: MeshFragment, air: AleDomainEstimate) -> float:
    minimum_air_spacing = min(
        right - left
        for axis in (air.x_coordinates, air.y_coordinates, air.z_coordinates)
        for left, right in zip(axis, axis[1:])
    )
    spans = tuple(
        mesh.bounds_m[index + 3] - mesh.bounds_m[index] for index in range(3)
    )
    return max(1.0e-9, min(minimum_air_spacing, *spans) * 1.0e-6)


def _strictly_inside(
    box: AxisAlignedBox,
    point: Sequence[float],
) -> bool:
    bounds = box.as_tuple()
    return all(
        bounds[index] + _TOLERANCE_M
        < point[index]
        < bounds[index + 3] - _TOLERANCE_M
        for index in range(3)
    )


def _element_bounds(
    node_ids: Sequence[int],
    nodes: Mapping[int, Node],
) -> tuple[float, float, float, float, float, float]:
    return (
        *(min(nodes[node_id].coordinates[index] for node_id in node_ids) for index in range(3)),
        *(max(nodes[node_id].coordinates[index] for node_id in node_ids) for index in range(3)),
    )


def _positive_box_overlap(
    left: Sequence[float],
    right: Sequence[float],
) -> bool:
    return all(
        min(left[index + 3], right[index + 3])
        - max(left[index], right[index])
        > _TOLERANCE_M
        for index in range(3)
    )


def _surface_fingerprint(
    scene_fingerprint: str,
    building: PhysicalBuildingModel,
    ground: GroundModel,
    air: AleDomainEstimate,
    mesh: MeshFragment,
    surfaces: Sequence[ClassifiedSurface],
) -> str:
    digest = hashlib.sha256()
    header = {
        "schema_version": "phase18.solver_blast.surface_topology@1",
        "scene_fingerprint": scene_fingerprint,
        "building_fingerprint": building.fingerprint,
        "ground_fingerprint": ground.fingerprint,
        "air_fingerprint": air.fingerprint,
        "building_mesh_fingerprint": mesh.fingerprint,
        "surface_count": len(surfaces),
    }
    digest.update(
        json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    for row in surfaces:
        semantic = (
            row.owner_element_id,
            row.owner_local_face_index,
            row.owner_part_role,
            row.face_key,
            row.surface_class,
            row.adjacent_active_air_component,
        )
        digest.update(b"\n")
        digest.update(
            json.dumps(semantic, separators=(",", ":")).encode("utf-8")
        )
    return digest.hexdigest()


def _detach_embedded_beam_nodes(
    building: PhysicalBuildingModel,
    mesh: MeshFragment,
) -> MeshFragment:
    embedded_roles = {
        role
        for interface in building.interfaces
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
        nodes=tuple(row for row in fragment.nodes if row.node_id in retained_node_ids),
        solids=solids,
        shells=shells,
        beams=beams,
        part_bindings=tuple(
            row for row in fragment.part_bindings if row.part_role in retained_roles
        ),
    )


def _split_ruled_shell_role_at_horizontal_plane(
    fragment: MeshFragment,
    *,
    role: str,
    elevation_m: float,
) -> MeshFragment:
    """Conform ruled pavilion glazing to grade without mutating source assets."""

    source_nodes = {node.node_id: node for node in fragment.nodes}
    crossing = tuple(
        element
        for element in fragment.shells
        if element.part_role == role
        and min(source_nodes[node_id].z for node_id in element.node_ids)
        < elevation_m - _TOLERANCE_M
        and max(source_nodes[node_id].z for node_id in element.node_ids)
        > elevation_m + _TOLERANCE_M
    )
    if not crossing:
        return fragment

    coordinate_to_id = {
        tuple(round(value, 12) for value in node.coordinates): node.node_id
        for node in fragment.nodes
    }
    nodes = list(fragment.nodes)
    next_node_id = max(source_nodes) + 1

    def allocate(point: Sequence[float]) -> int:
        nonlocal next_node_id
        key = tuple(round(float(value), 12) for value in point)
        existing = coordinate_to_id.get(key)
        if existing is not None:
            return existing
        node_id = next_node_id
        next_node_id += 1
        coordinate_to_id[key] = node_id
        nodes.append(Node(node_id, *key))
        return node_id

    crossing_ids = {element.element_id for element in crossing}
    shells = [
        element
        for element in fragment.shells
        if element.element_id not in crossing_ids
    ]
    all_elements = (*fragment.solids, *fragment.shells, *fragment.beams)
    next_element_id = max(element.element_id for element in all_elements) + 1
    for element in crossing:
        points = tuple(
            source_nodes[node_id].coordinates for node_id in element.node_ids
        )
        for quad in _split_ruled_quad_at_elevation(points, elevation_m):
            node_ids = tuple(allocate(point) for point in quad)
            if len(set(node_ids)) != 4:
                raise ValueError("grade-conformed glazing shell became degenerate")
            shells.append(
                ShellElement(next_element_id, node_ids, element.part_role)
            )
            next_element_id += 1
    return MeshFragment(
        nodes=tuple(nodes),
        solids=fragment.solids,
        shells=tuple(shells),
        beams=fragment.beams,
        part_bindings=fragment.part_bindings,
    )


def _split_ruled_quad_at_elevation(
    points: Sequence[tuple[float, float, float]],
    elevation_m: float,
) -> tuple[
    tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ],
    ...,
]:
    if len(points) != 4:
        raise ValueError("ruled glazing shell must have four nodes")
    bottom_left, bottom_right, top_right, top_left = points
    if (
        0.5 * (bottom_left[2] + bottom_right[2])
        >= 0.5 * (top_left[2] + top_right[2]) - _TOLERANCE_M
    ):
        raise ValueError("pavilion glazing shell is not bottom-to-top ruled")

    breaks = {0.0, 1.0}
    for left, right in (
        (bottom_left, bottom_right),
        (top_left, top_right),
    ):
        delta = right[2] - left[2]
        if abs(delta) <= _TOLERANCE_M:
            continue
        fraction = (elevation_m - left[2]) / delta
        if _TOLERANCE_M < fraction < 1.0 - _TOLERANCE_M:
            breaks.add(fraction)

    def interpolate(
        left: Sequence[float],
        right: Sequence[float],
        fraction: float,
    ) -> tuple[float, float, float]:
        return tuple(
            float(left[axis])
            + fraction * (float(right[axis]) - float(left[axis]))
            for axis in range(3)
        )

    result: list[
        tuple[
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
        ]
    ] = []

    def append_polygon(polygon: Sequence[tuple[float, float, float]]) -> None:
        cleaned: list[tuple[float, float, float]] = []
        for point in polygon:
            if cleaned and _distance(cleaned[-1], point) <= _TOLERANCE_M:
                continue
            cleaned.append(point)
        if len(cleaned) > 1 and _distance(cleaned[0], cleaned[-1]) <= _TOLERANCE_M:
            cleaned.pop()
        if _polygon_area_3d(cleaned) <= 1.0e-14:
            return
        if len(cleaned) == 4:
            result.append(tuple(cleaned))  # type: ignore[arg-type]
            return
        if len(cleaned) != 3:
            raise ValueError("grade split produced an unsupported shell polygon")
        first, second, third = cleaned
        first_second = _midpoint(first, second)
        second_third = _midpoint(second, third)
        third_first = _midpoint(third, first)
        center = tuple(
            math.fsum(point[axis] for point in cleaned) / 3.0
            for axis in range(3)
        )
        result.extend(
            (
                (first, first_second, center, third_first),
                (second, second_third, center, first_second),
                (third, third_first, center, second_third),
            )
        )

    ordered = sorted(breaks)
    for start, stop in zip(ordered, ordered[1:]):
        lower_start = interpolate(bottom_left, bottom_right, start)
        lower_stop = interpolate(bottom_left, bottom_right, stop)
        upper_start = interpolate(top_left, top_right, start)
        upper_stop = interpolate(top_left, top_right, stop)
        midpoint = 0.5 * (start + stop)
        lower_mid_z = interpolate(bottom_left, bottom_right, midpoint)[2]
        upper_mid_z = interpolate(top_left, top_right, midpoint)[2]
        if lower_mid_z < elevation_m - _TOLERANCE_M < upper_mid_z:
            grade_start = _vertical_intersection(
                lower_start, upper_start, elevation_m
            )
            grade_stop = _vertical_intersection(
                lower_stop, upper_stop, elevation_m
            )
            append_polygon((lower_start, lower_stop, grade_stop, grade_start))
            append_polygon((grade_start, grade_stop, upper_stop, upper_start))
        else:
            append_polygon((lower_start, lower_stop, upper_stop, upper_start))
    return tuple(
        quad
        for quad in result
        if _polygon_area_3d(quad) > 1.0e-14
    )


def _vertical_intersection(
    lower: Sequence[float],
    upper: Sequence[float],
    elevation_m: float,
) -> tuple[float, float, float]:
    span = float(upper[2]) - float(lower[2])
    if span <= _TOLERANCE_M:
        raise ValueError("glazing grade split has no positive vertical span")
    fraction = (elevation_m - float(lower[2])) / span
    point = tuple(
        float(lower[axis])
        + fraction * (float(upper[axis]) - float(lower[axis]))
        for axis in range(3)
    )
    return (point[0], point[1], elevation_m)


def _midpoint(
    left: Sequence[float],
    right: Sequence[float],
) -> tuple[float, float, float]:
    return tuple(
        0.5 * (float(left[axis]) + float(right[axis])) for axis in range(3)
    )


def _distance(left: Sequence[float], right: Sequence[float]) -> float:
    return math.sqrt(
        math.fsum(
            (float(left[axis]) - float(right[axis])) ** 2 for axis in range(3)
        )
    )


def _centroid(
    node_ids: Sequence[int],
    nodes: Mapping[int, Node],
) -> tuple[float, float, float]:
    return tuple(
        math.fsum(nodes[node_id].coordinates[axis] for node_id in node_ids)
        / len(node_ids)
        for axis in range(3)
    )


def _subtract(
    left: Sequence[float],
    right: Sequence[float],
) -> tuple[float, float, float]:
    return tuple(float(left[index]) - float(right[index]) for index in range(3))


def _cross(
    left: Sequence[float],
    right: Sequence[float],
) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return math.fsum(left[index] * right[index] for index in range(3))
