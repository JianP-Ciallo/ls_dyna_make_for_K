"""Fail-closed geometric quality audits for the final solver structural mesh."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..artifacts import BeamElement, MeshFragment, Node, ShellElement, SolidElement
from .contracts import AuditFinding, PhysicalMemberRecord


_HEX8_NATURAL_SIGNS = (
    (-1.0, -1.0, -1.0),
    (1.0, -1.0, -1.0),
    (1.0, 1.0, -1.0),
    (-1.0, 1.0, -1.0),
    (-1.0, -1.0, 1.0),
    (1.0, -1.0, 1.0),
    (1.0, 1.0, 1.0),
    (-1.0, 1.0, 1.0),
)
_HEX8_EDGES = (
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 0),
    (4, 5),
    (5, 6),
    (6, 7),
    (7, 4),
    (0, 4),
    (1, 5),
    (2, 6),
    (3, 7),
)
_HEX8_FACES = (
    (0, 3, 2, 1),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (1, 2, 6, 5),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
)
_COORDINATE_DIGITS = 12
_ABSOLUTE_TOLERANCE_M = 1.0e-12


@dataclass(frozen=True, slots=True)
class MeshQualityReport:
    solid_count: int
    shell_count: int
    beam_count: int
    minimum_corner_jacobian_m3: float
    maximum_aspect_ratio: float
    orphan_node_count: int
    duplicate_element_count: int
    solid_overlap_pair_count: int
    unresolved_overlap_candidate_count: int
    findings: tuple[AuditFinding, ...]
    fingerprint: str


def audit_mesh_quality(
    mesh: MeshFragment,
    members: Sequence[PhysicalMemberRecord] = (),
) -> MeshQualityReport:
    """Audit exact solver geometry without accepting role-name heuristics."""

    if not isinstance(mesh, MeshFragment):
        raise TypeError("mesh must be a MeshFragment")
    if isinstance(members, (str, bytes, bytearray)) or not isinstance(
        members, Sequence
    ):
        raise TypeError("members must be a sequence of PhysicalMemberRecord values")
    if any(not isinstance(row, PhysicalMemberRecord) for row in members):
        raise TypeError("members must contain PhysicalMemberRecord values")

    nodes = {row.node_id: row for row in mesh.nodes}
    member_by_role = _member_index(members)
    findings: list[AuditFinding] = []
    jacobians: list[float] = []
    aspect_ratios: list[float] = []

    for element in sorted(mesh.solids, key=lambda row: row.element_id):
        points = tuple(nodes[node_id].coordinates for node_id in element.node_ids)
        corner_values = tuple(
            _hex8_jacobian_determinant(points, *natural)
            for natural in _HEX8_NATURAL_SIGNS
        )
        jacobians.extend(corner_values)
        if any(not math.isfinite(value) or value <= 0.0 for value in corner_values):
            findings.append(
                AuditFinding(
                    "solid_nonpositive_corner_jacobian",
                    element.part_role,
                    f"Solid element {element.element_id} has a nonpositive HEX8 corner Jacobian",
                )
            )
        maximum_edge, minimum_edge = _edge_extrema(points, _HEX8_EDGES)
        aspect_ratio = (
            math.inf if minimum_edge <= 0.0 else maximum_edge / minimum_edge
        )
        aspect_ratios.append(aspect_ratio)
        local_scale = max(maximum_edge, _ABSOLUTE_TOLERANCE_M) ** 3
        if any(
            math.isfinite(value)
            and 0.0 < value <= local_scale * 1.0e-12
            for value in corner_values
        ):
            findings.append(
                AuditFinding(
                    "solid_near_singular_corner_jacobian",
                    element.part_role,
                    f"Solid element {element.element_id} has a near-singular HEX8 corner Jacobian",
                )
            )
        if not math.isfinite(aspect_ratio):
            findings.append(
                AuditFinding(
                    "solid_nonpositive_edge_length",
                    element.part_role,
                    f"Solid element {element.element_id} has a zero-length geometric edge",
                )
            )

    _audit_shells(mesh.shells, nodes, member_by_role, findings)
    _audit_beams(mesh.beams, nodes, member_by_role, findings)

    referenced_node_ids = {
        node_id
        for element in (*mesh.solids, *mesh.shells, *mesh.beams)
        for node_id in element.node_ids
    }
    orphan_node_ids = sorted(set(nodes) - referenced_node_ids)
    if orphan_node_ids:
        findings.append(
            AuditFinding(
                "orphan_mesh_node",
                "__mesh__",
                f"mesh contains {len(orphan_node_ids)} unreferenced node(s)",
            )
        )

    duplicate_count, duplicate_findings = _duplicate_geometry_findings(mesh, nodes)
    findings.extend(duplicate_findings)
    overlap_count, unresolved_count, overlap_findings = _solid_overlap_findings(
        mesh.solids, nodes
    )
    findings.extend(overlap_findings)
    ordered_findings = tuple(
        sorted(findings, key=lambda row: (row.member_role, row.finding_id, row.message))
    )
    minimum_jacobian = min(jacobians) if jacobians else 0.0
    maximum_aspect_ratio = max(aspect_ratios) if aspect_ratios else 0.0
    identity = {
        "schema_version": "phase18.solver_blast.mesh_quality@1",
        "mesh_fingerprint": mesh.fingerprint,
        "member_roles": sorted(member_by_role),
        "solid_count": len(mesh.solids),
        "shell_count": len(mesh.shells),
        "beam_count": len(mesh.beams),
        "minimum_corner_jacobian_m3": minimum_jacobian,
        "maximum_aspect_ratio": (
            maximum_aspect_ratio if math.isfinite(maximum_aspect_ratio) else "Infinity"
        ),
        "orphan_node_count": len(orphan_node_ids),
        "duplicate_element_count": duplicate_count,
        "solid_overlap_pair_count": overlap_count,
        "unresolved_overlap_candidate_count": unresolved_count,
        "findings": [
            {
                "finding_id": row.finding_id,
                "member_role": row.member_role,
                "message": row.message,
            }
            for row in ordered_findings
        ],
    }
    return MeshQualityReport(
        solid_count=len(mesh.solids),
        shell_count=len(mesh.shells),
        beam_count=len(mesh.beams),
        minimum_corner_jacobian_m3=minimum_jacobian,
        maximum_aspect_ratio=maximum_aspect_ratio,
        orphan_node_count=len(orphan_node_ids),
        duplicate_element_count=duplicate_count,
        solid_overlap_pair_count=overlap_count,
        unresolved_overlap_candidate_count=unresolved_count,
        findings=ordered_findings,
        fingerprint=_fingerprint(identity),
    )


def _member_index(
    members: Sequence[PhysicalMemberRecord],
) -> Mapping[str, PhysicalMemberRecord]:
    result: dict[str, PhysicalMemberRecord] = {}
    for row in members:
        if row.role in result:
            raise ValueError(f"duplicate member role {row.role!r}")
        result[row.role] = row
    return result


def _audit_shells(
    elements: Sequence[ShellElement],
    nodes: Mapping[int, Node],
    member_by_role: Mapping[str, PhysicalMemberRecord],
    findings: list[AuditFinding],
) -> None:
    edge_owners: dict[tuple[int, int], list[tuple[int, int, int, str]]] = {}
    for element in sorted(elements, key=lambda row: row.element_id):
        points = tuple(nodes[node_id].coordinates for node_id in element.node_ids)
        first = _cross(_subtract(points[1], points[0]), _subtract(points[2], points[0]))
        second = _cross(_subtract(points[2], points[0]), _subtract(points[3], points[0]))
        area = 0.5 * (_magnitude(first) + _magnitude(second))
        if not math.isfinite(area) or area <= 0.0:
            findings.append(
                AuditFinding(
                    "shell_nonpositive_area",
                    element.part_role,
                    f"Shell element {element.element_id} has nonpositive geometric area",
                )
            )
        member = member_by_role.get(element.part_role)
        if member is not None:
            if member.element_family != "Shell" or member.dimensions_m[2] <= 0.0:
                findings.append(
                    AuditFinding(
                        "shell_invalid_member_thickness",
                        element.part_role,
                        f"Shell element {element.element_id} has no positive Shell thickness declaration",
                    )
                )
        for start, end in zip(element.node_ids, (*element.node_ids[1:], element.node_ids[0])):
            edge_owners.setdefault(tuple(sorted((start, end))), []).append(
                (element.element_id, start, end, element.part_role)
            )
    for edge, owners in sorted(edge_owners.items()):
        owners_by_role: dict[str, list[tuple[int, int, int, str]]] = {}
        for owner in owners:
            owners_by_role.setdefault(owner[3], []).append(owner)
        for role, role_owners in sorted(owners_by_role.items()):
            if len(role_owners) > 2:
                findings.append(
                    AuditFinding(
                        "shell_nonmanifold_edge",
                        role,
                        f"Shell edge {edge} has {len(role_owners)} owners in physical part {role!r}",
                    )
                )
            elif (
                len(role_owners) == 2
                and role_owners[0][1:3] == role_owners[1][1:3]
            ):
                findings.append(
                    AuditFinding(
                        "shell_inconsistent_winding",
                        role,
                        f"Shell edge {edge} is traversed in the same direction by adjacent elements in physical part {role!r}",
                    )
                )


def _audit_beams(
    elements: Sequence[BeamElement],
    nodes: Mapping[int, Node],
    member_by_role: Mapping[str, PhysicalMemberRecord],
    findings: list[AuditFinding],
) -> None:
    for element in sorted(elements, key=lambda row: row.element_id):
        start, end = (nodes[node_id].coordinates for node_id in element.node_ids)
        tangent = _subtract(end, start)
        length = _magnitude(tangent)
        if not math.isfinite(length) or length <= 0.0:
            findings.append(
                AuditFinding(
                    "beam_nonpositive_length",
                    element.part_role,
                    f"Beam element {element.element_id} has nonpositive geometric length",
                )
            )
            continue
        member = member_by_role.get(element.part_role)
        if member is None:
            continue
        if member.element_family != "Beam" or any(
            value <= 0.0 for value in member.dimensions_m[1:]
        ):
            findings.append(
                AuditFinding(
                    "beam_invalid_section",
                    element.part_role,
                    f"Beam element {element.element_id} has no positive Beam section declaration",
                )
            )
        orientation = member.orientation_vector
        if orientation is None:
            findings.append(
                AuditFinding(
                    "beam_missing_orientation",
                    element.part_role,
                    f"Beam element {element.element_id} has no orientation vector",
                )
            )
        elif _magnitude(_cross(tangent, orientation)) <= (
            1.0e-12 * length * _magnitude(orientation)
        ):
            findings.append(
                AuditFinding(
                    "beam_orientation_parallel_to_axis",
                    element.part_role,
                    f"Beam element {element.element_id} orientation is parallel to its axis",
                )
            )


def _duplicate_geometry_findings(
    mesh: MeshFragment,
    nodes: Mapping[int, Node],
) -> tuple[int, tuple[AuditFinding, ...]]:
    seen: dict[tuple[str, tuple[tuple[float, float, float], ...]], tuple[int, str]] = {}
    findings: list[AuditFinding] = []
    count = 0
    for family, elements in (
        ("Solid", mesh.solids),
        ("Shell", mesh.shells),
        ("Beam", mesh.beams),
    ):
        for element in sorted(elements, key=lambda row: row.element_id):
            coordinates = tuple(
                sorted(_coordinate_key(nodes[node_id]) for node_id in element.node_ids)
            )
            key = family, coordinates
            previous = seen.get(key)
            if previous is None:
                seen[key] = (element.element_id, element.part_role)
                continue
            count += 1
            findings.append(
                AuditFinding(
                    "duplicate_element_geometry",
                    element.part_role,
                    f"{family} element {element.element_id} duplicates element {previous[0]} geometry",
                )
            )
    return count, tuple(findings)


def _solid_overlap_findings(
    elements: Sequence[SolidElement],
    nodes: Mapping[int, Node],
) -> tuple[int, int, tuple[AuditFinding, ...]]:
    rows = []
    for element in sorted(elements, key=lambda row: row.element_id):
        points = tuple(nodes[node_id].coordinates for node_id in element.node_ids)
        rows.append((element, points, _bounds(points), frozenset(element.node_ids)))
    cell_sizes = _broad_phase_cell_sizes(tuple(row[2] for row in rows))
    bins: dict[tuple[int, int, int], list[int]] = {}
    oversized: list[int] = []
    overlap_count = 0
    unresolved_count = 0
    findings: list[AuditFinding] = []
    for row_index, (element, points, bounds, node_ids) in enumerate(rows):
        keys = _broad_phase_bin_keys(bounds, cell_sizes)
        if keys is None:
            candidate_indices = range(row_index)
        else:
            candidates = set(oversized)
            for key in keys:
                candidates.update(bins.get(key, ()))
            candidate_indices = sorted(candidates)
        for other_index in candidate_indices:
            other, other_points, other_bounds, other_node_ids = rows[other_index]
            # A conforming structural mesh may meet at a face, edge, or node.
            # These topological neighbours are not independent bodies and their
            # warped HEX8 AABBs can overlap even when their interiors do not.
            # Duplicate geometry remains a separate hard finding above.
            if node_ids & other_node_ids:
                continue
            if not _positive_aabb_overlap(bounds, other_bounds):
                continue
            relation = _convex_hex_overlap_relation(points, other_points)
            roles = "|".join(sorted((other.part_role, element.part_role)))
            if relation == "positive":
                overlap_count += 1
                findings.append(
                    AuditFinding(
                        "solid_positive_volume_overlap",
                        roles,
                        f"Solid elements {other.element_id} and {element.element_id} overlap with positive volume",
                    )
                )
            elif relation == "unresolved":
                unresolved_count += 1
                findings.append(
                    AuditFinding(
                        "solid_overlap_unresolved",
                        roles,
                        f"Solid elements {other.element_id} and {element.element_id} have an unresolved overlap candidate",
                    )
                )
        if keys is None:
            oversized.append(row_index)
        else:
            for key in keys:
                bins.setdefault(key, []).append(row_index)
    return overlap_count, unresolved_count, tuple(findings)


def _broad_phase_cell_sizes(
    bounds_rows: Sequence[tuple[float, float, float, float, float, float]],
) -> tuple[float, float, float]:
    result: list[float] = []
    for axis in range(3):
        spans = sorted(
            row[axis + 3] - row[axis]
            for row in bounds_rows
            if row[axis + 3] - row[axis] > _ABSOLUTE_TOLERANCE_M
        )
        result.append(
            spans[len(spans) // 2]
            if spans
            else 1.0
        )
    return tuple(result)


def _broad_phase_bin_keys(
    bounds: tuple[float, float, float, float, float, float],
    cell_sizes: tuple[float, float, float],
    *,
    maximum_bin_count: int = 4096,
) -> tuple[tuple[int, int, int], ...] | None:
    ranges: list[range] = []
    bin_count = 1
    for axis, cell_size in enumerate(cell_sizes):
        start = math.floor(
            (bounds[axis] + _ABSOLUTE_TOLERANCE_M) / cell_size
        )
        stop = math.floor(
            (bounds[axis + 3] - _ABSOLUTE_TOLERANCE_M) / cell_size
        )
        if stop < start:
            center = 0.5 * (bounds[axis] + bounds[axis + 3])
            start = stop = math.floor(center / cell_size)
        axis_range = range(start, stop + 1)
        bin_count *= len(axis_range)
        if bin_count > maximum_bin_count:
            return None
        ranges.append(axis_range)
    return tuple(itertools.product(*ranges))


def _convex_hex_overlap_relation(
    left: tuple[tuple[float, float, float], ...],
    right: tuple[tuple[float, float, float], ...],
) -> str:
    if not _is_convex_hex(left) or not _is_convex_hex(right):
        return "unresolved"
    axes = [*_face_axes(left), *_face_axes(right)]
    left_edges = [_subtract(left[b], left[a]) for a, b in _HEX8_EDGES]
    right_edges = [_subtract(right[b], right[a]) for a, b in _HEX8_EDGES]
    axes.extend(_cross(first, second) for first in left_edges for second in right_edges)
    tested = 0
    touching = False
    scale = max(
        max(_edge_extrema(left, _HEX8_EDGES)[0], _edge_extrema(right, _HEX8_EDGES)[0]),
        1.0,
    )
    tolerance = 1.0e-10 * scale
    for axis in axes:
        magnitude = _magnitude(axis)
        if magnitude <= 1.0e-14:
            continue
        unit = tuple(value / magnitude for value in axis)
        left_projection = tuple(_dot(point, unit) for point in left)
        right_projection = tuple(_dot(point, unit) for point in right)
        overlap = min(max(left_projection), max(right_projection)) - max(
            min(left_projection), min(right_projection)
        )
        tested += 1
        if overlap < -tolerance:
            return "none"
        if overlap <= tolerance:
            touching = True
    if tested == 0:
        return "unresolved"
    return "none" if touching else "positive"


def _is_convex_hex(points: tuple[tuple[float, float, float], ...]) -> bool:
    center = tuple(math.fsum(point[axis] for point in points) / 8.0 for axis in range(3))
    scale = max(_edge_extrema(points, _HEX8_EDGES)[0], 1.0)
    tolerance = 1.0e-9 * scale
    for face in _HEX8_FACES:
        face_points = tuple(points[index] for index in face)
        for triangle in ((0, 1, 2), (0, 2, 3)):
            a, b, c = (face_points[index] for index in triangle)
            normal = _cross(_subtract(b, a), _subtract(c, a))
            magnitude = _magnitude(normal)
            if magnitude <= 1.0e-14:
                return False
            if _dot(normal, _subtract(center, a)) > 0.0:
                normal = tuple(-value for value in normal)
            for point in points:
                if _dot(normal, _subtract(point, a)) > tolerance * magnitude:
                    return False
    return True


def _face_axes(
    points: tuple[tuple[float, float, float], ...]
) -> list[tuple[float, float, float]]:
    axes: list[tuple[float, float, float]] = []
    for face in _HEX8_FACES:
        a, b, c, d = (points[index] for index in face)
        axes.append(_cross(_subtract(b, a), _subtract(c, a)))
        axes.append(_cross(_subtract(c, a), _subtract(d, a)))
    return axes


def _hex8_jacobian_determinant(
    points: tuple[tuple[float, float, float], ...],
    xi: float,
    eta: float,
    zeta: float,
) -> float:
    derivatives: list[tuple[float, float, float]] = []
    for sx, sy, sz in _HEX8_NATURAL_SIGNS:
        derivatives.append(
            (
                sx * (1.0 + sy * eta) * (1.0 + sz * zeta) / 8.0,
                sy * (1.0 + sx * xi) * (1.0 + sz * zeta) / 8.0,
                sz * (1.0 + sx * xi) * (1.0 + sy * eta) / 8.0,
            )
        )
    columns = tuple(
        tuple(
            math.fsum(points[node][coordinate] * derivatives[node][natural]
                      for node in range(8))
            for coordinate in range(3)
        )
        for natural in range(3)
    )
    return _dot(columns[0], _cross(columns[1], columns[2]))


def _edge_extrema(
    points: Sequence[tuple[float, float, float]],
    edges: Sequence[tuple[int, int]],
) -> tuple[float, float]:
    lengths = tuple(_magnitude(_subtract(points[b], points[a])) for a, b in edges)
    return max(lengths), min(lengths)


def _bounds(
    points: Sequence[tuple[float, float, float]],
) -> tuple[float, float, float, float, float, float]:
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        min(point[2] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
        max(point[2] for point in points),
    )


def _positive_aabb_overlap(
    left: Sequence[float], right: Sequence[float]
) -> bool:
    return all(
        min(left[axis + 3], right[axis + 3])
        - max(left[axis], right[axis])
        > _ABSOLUTE_TOLERANCE_M
        for axis in range(3)
    )


def _coordinate_key(node: Node) -> tuple[float, float, float]:
    return tuple(round(value, _COORDINATE_DIGITS) for value in node.coordinates)


def _subtract(
    left: Sequence[float], right: Sequence[float]
) -> tuple[float, float, float]:
    return tuple(float(left[index]) - float(right[index]) for index in range(3))


def _cross(
    left: Sequence[float], right: Sequence[float]
) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return math.fsum(float(left[index]) * float(right[index]) for index in range(3))


def _magnitude(value: Sequence[float]) -> float:
    return math.sqrt(_dot(value, value))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


__all__ = ["MeshQualityReport", "audit_mesh_quality"]
