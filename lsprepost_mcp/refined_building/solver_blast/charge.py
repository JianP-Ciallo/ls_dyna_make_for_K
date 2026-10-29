"""Movable TNT source validation for solver-blast scenes."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

from ..artifacts import MeshFragment
from ..spatial import AxisAlignedBox
from .contracts import SolverBlastConfig
from .ground import GroundModel
from .physical_building import PhysicalBuildingModel


TNT_DENSITY_KG_PER_M3 = 1630.0


@dataclass(frozen=True, slots=True)
class OccupiedVolume:
    role: str
    medium: str
    bounds: AxisAlignedBox
    geometry_kind: str = "box"
    points_m: tuple[tuple[float, float, float], ...] = ()
    clearance_m: float = 0.0


@dataclass(frozen=True, slots=True)
class ChargeModel:
    material_role: str
    geometry_kind: str
    mass_kg: float
    density_kg_per_m3: float
    position_m: tuple[float, float, float]
    radius_m: float
    volume_m3: float
    side_length_m: float
    bounds_m: tuple[float, float, float, float, float, float]
    detonation_time_s: float
    fingerprint: str


def tnt_radius_m(mass_kg: float) -> float:
    return (3.0 * mass_kg / (4.0 * math.pi * TNT_DENSITY_KG_PER_M3)) ** (1.0 / 3.0)


def tnt_side_length_m(mass_kg: float) -> float:
    """Return the edge length of a mass-conserving TNT cuboid."""

    return (mass_kg / TNT_DENSITY_KG_PER_M3) ** (1.0 / 3.0)


def collect_occupied_volumes(
    building: PhysicalBuildingModel,
    ground: GroundModel,
) -> tuple[OccupiedVolume, ...]:
    rows: list[OccupiedVolume] = []
    excluded = set(building.excluded_base_part_roles)
    member_dimensions = {
        row.role: row.dimensions_m for row in building.members
    }
    for artifact in building.artifacts:
        rows.extend(_solid_volumes(artifact.mesh, excluded, "structure"))
        rows.extend(
            _shell_and_beam_volumes(
                artifact.mesh,
                excluded,
                "structure",
                member_dimensions,
            )
        )
    for fragment in building.supplement_fragments:
        rows.extend(_solid_volumes(fragment, frozenset(), "structure"))
        rows.extend(
            _shell_and_beam_volumes(
                fragment,
                frozenset(),
                "structure",
                member_dimensions,
            )
        )
    for fragment in ground.fragments:
        rows.extend(_solid_volumes(fragment, frozenset(), "soil"))
    return tuple(rows)


def build_charge(
    config: SolverBlastConfig,
    occupied_volumes: tuple[OccupiedVolume, ...],
) -> ChargeModel:
    if not isinstance(config, SolverBlastConfig):
        raise TypeError("config must be a SolverBlastConfig")
    radius = tnt_radius_m(config.tnt_equivalent_mass_kg)
    volume = config.tnt_equivalent_mass_kg / TNT_DENSITY_KG_PER_M3
    side_length = tnt_side_length_m(config.tnt_equivalent_mass_kg)
    half_side = 0.5 * side_length
    bounds = (
        config.charge_position_m[0] - half_side,
        config.charge_position_m[1] - half_side,
        config.charge_position_m[2] - half_side,
        config.charge_position_m[0] + half_side,
        config.charge_position_m[1] + half_side,
        config.charge_position_m[2] + half_side,
    )
    # The circumscribed sphere makes the existing exact shell/beam distance tests
    # conservative for every point of the cuboid, including its corners.
    collision_radius = math.sqrt(3.0) * half_side
    for occupied in occupied_volumes:
        if _sphere_intersects_occupied(
            config.charge_position_m,
            collision_radius,
            occupied,
        ):
            if occupied.medium == "soil":
                raise ValueError(
                    f"charge position overlaps soil role {occupied.role!r}; move it into valid air"
                )
            raise ValueError(
                f"charge position overlaps structure role {occupied.role!r}; move it into valid air"
            )
    identity = {
        "schema_version": "phase18.solver_blast.charge@2",
        "material_role": "tnt_high_explosive",
        "geometry_kind": "mass_conserving_cuboid",
        "mass_kg": config.tnt_equivalent_mass_kg,
        "density_kg_per_m3": TNT_DENSITY_KG_PER_M3,
        "position_m": list(config.charge_position_m),
        "radius_m": radius,
        "volume_m3": volume,
        "side_length_m": side_length,
        "bounds_m": list(bounds),
        "detonation_time_s": config.detonation_time_s,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ChargeModel(
        material_role="tnt_high_explosive",
        geometry_kind="mass_conserving_cuboid",
        mass_kg=config.tnt_equivalent_mass_kg,
        density_kg_per_m3=TNT_DENSITY_KG_PER_M3,
        position_m=config.charge_position_m,
        radius_m=radius,
        volume_m3=volume,
        side_length_m=side_length,
        bounds_m=bounds,
        detonation_time_s=config.detonation_time_s,
        fingerprint=fingerprint,
    )


def _solid_volumes(
    fragment: MeshFragment,
    excluded: frozenset[str] | set[str],
    medium: str,
) -> list[OccupiedVolume]:
    nodes = {node.node_id: node for node in fragment.nodes}
    result: list[OccupiedVolume] = []
    for element in fragment.solids:
        if element.part_role in excluded:
            continue
        points = tuple(nodes[node_id] for node_id in element.node_ids)
        result.append(
            OccupiedVolume(
                role=element.part_role,
                medium=medium,
                bounds=AxisAlignedBox(
                    min(row.x for row in points),
                    min(row.y for row in points),
                    min(row.z for row in points),
                    max(row.x for row in points),
                    max(row.y for row in points),
                    max(row.z for row in points),
                ),
            )
        )
    return result


def _shell_and_beam_volumes(
    fragment: MeshFragment,
    excluded: frozenset[str] | set[str],
    medium: str,
    member_dimensions: dict[str, tuple[float, float, float]],
) -> list[OccupiedVolume]:
    nodes = {node.node_id: node for node in fragment.nodes}
    result: list[OccupiedVolume] = []
    for geometry_kind, elements in (
        ("shell", fragment.shells),
        ("segment", fragment.beams),
    ):
        for element in elements:
            if element.part_role in excluded:
                continue
            points = tuple(
                (nodes[node_id].x, nodes[node_id].y, nodes[node_id].z)
                for node_id in element.node_ids
            )
            dimensions = member_dimensions.get(element.part_role, (0.0, 0.0, 0.0))
            if geometry_kind == "shell":
                clearance = 0.5 * dimensions[2]
            else:
                clearance = 0.5 * max(dimensions[1], dimensions[2])
            result.append(
                OccupiedVolume(
                    role=element.part_role,
                    medium=medium,
                    bounds=_positive_bounds(points),
                    geometry_kind=geometry_kind,
                    points_m=points,
                    clearance_m=clearance,
                )
            )
    return result


def _positive_bounds(
    points: tuple[tuple[float, float, float], ...],
) -> AxisAlignedBox:
    lower = [min(row[axis] for row in points) for axis in range(3)]
    upper = [max(row[axis] for row in points) for axis in range(3)]
    for axis in range(3):
        if upper[axis] - lower[axis] <= 1.0e-12:
            lower[axis] -= 5.0e-13
            upper[axis] += 5.0e-13
    return AxisAlignedBox(*lower, *upper)


def _sphere_intersects_occupied(
    center: tuple[float, float, float],
    radius: float,
    occupied: OccupiedVolume,
) -> bool:
    effective_radius = radius + occupied.clearance_m
    if not _sphere_intersects_box(center, effective_radius, occupied.bounds):
        return False
    if occupied.geometry_kind == "box":
        return True
    if occupied.geometry_kind == "segment":
        return (
            _point_segment_distance_squared(
                center,
                occupied.points_m[0],
                occupied.points_m[-1],
            )
            < effective_radius * effective_radius
        )
    points = occupied.points_m
    return any(
        _point_triangle_distance_squared(center, points[0], points[index], points[index + 1])
        < effective_radius * effective_radius
        for index in range(1, len(points) - 1)
    )


def _point_segment_distance_squared(
    point: tuple[float, float, float],
    start: tuple[float, float, float],
    end: tuple[float, float, float],
) -> float:
    direction = _subtract(end, start)
    length_squared = _dot(direction, direction)
    if length_squared <= 1.0e-30:
        return _dot(_subtract(point, start), _subtract(point, start))
    parameter = max(
        0.0,
        min(1.0, _dot(_subtract(point, start), direction) / length_squared),
    )
    closest = tuple(start[index] + parameter * direction[index] for index in range(3))
    offset = _subtract(point, closest)
    return _dot(offset, offset)


def _point_triangle_distance_squared(
    point: tuple[float, float, float],
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> float:
    ab = _subtract(b, a)
    ac = _subtract(c, a)
    ap = _subtract(point, a)
    d1 = _dot(ab, ap)
    d2 = _dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return _dot(ap, ap)

    bp = _subtract(point, b)
    d3 = _dot(ab, bp)
    d4 = _dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return _dot(bp, bp)

    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        parameter = d1 / (d1 - d3)
        projection = tuple(a[index] + parameter * ab[index] for index in range(3))
        offset = _subtract(point, projection)
        return _dot(offset, offset)

    cp = _subtract(point, c)
    d5 = _dot(ab, cp)
    d6 = _dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return _dot(cp, cp)

    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        parameter = d2 / (d2 - d6)
        projection = tuple(a[index] + parameter * ac[index] for index in range(3))
        offset = _subtract(point, projection)
        return _dot(offset, offset)

    va = d3 * d6 - d5 * d4
    if va <= 0.0 and d4 - d3 >= 0.0 and d5 - d6 >= 0.0:
        edge = _subtract(c, b)
        parameter = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        projection = tuple(b[index] + parameter * edge[index] for index in range(3))
        offset = _subtract(point, projection)
        return _dot(offset, offset)

    denominator = va + vb + vc
    if abs(denominator) <= 1.0e-30:
        return min(
            _point_segment_distance_squared(point, a, b),
            _point_segment_distance_squared(point, b, c),
            _point_segment_distance_squared(point, c, a),
        )
    inverse = 1.0 / denominator
    v = vb * inverse
    w = vc * inverse
    projection = tuple(
        a[index] + v * ab[index] + w * ac[index] for index in range(3)
    )
    offset = _subtract(point, projection)
    return _dot(offset, offset)


def _subtract(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(left[index] - right[index] for index in range(3))


def _dot(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    return sum(left[index] * right[index] for index in range(3))


def _sphere_intersects_box(
    center: tuple[float, float, float],
    radius: float,
    box: AxisAlignedBox,
) -> bool:
    distance_squared = 0.0
    for value, lower, upper in zip(
        center,
        (box.min_x, box.min_y, box.min_z),
        (box.max_x, box.max_y, box.max_z),
    ):
        if value < lower:
            distance_squared += (lower - value) ** 2
        elif value > upper:
            distance_squared += (value - upper) ** 2
    return distance_squared < radius * radius
