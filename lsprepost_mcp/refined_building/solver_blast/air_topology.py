"""Closed topology for active air, explicit TNT, and the grade buffer."""

from __future__ import annotations

import bisect
import hashlib
import json
import math
from array import array
from collections import deque
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ..spatial import AxisAlignedBox, compile_spatial_topology
from .physical_building import PhysicalBuildingModel

if TYPE_CHECKING:
    from .ale_domain import AleDomainEstimate
    from .ground import GroundModel
    from .scene import SolverBlastScene


AirCellKind = Literal["active_air", "explicit_tnt", "coupling_buffer"]
_TOLERANCE_M = 1.0e-12
ALE_CELL_INDEX_ITEMSIZE_BYTES = array("I").itemsize
if ALE_CELL_INDEX_ITEMSIZE_BYTES < 4:
    raise RuntimeError("ALE cell indices require an unsigned integer of at least 4 bytes")


@dataclass(frozen=True, slots=True)
class AirRegionModel:
    grade_elevation_m: float
    exterior_min_z_m: float
    connected_internal_bounds_m: tuple[
        tuple[float, float, float, float, float, float], ...
    ]
    connected_opening_bounds_m: tuple[
        tuple[float, float, float, float, float, float], ...
    ]
    exterior_opening_bounds_m: tuple[
        tuple[float, float, float, float, float, float], ...
    ]
    coupling_buffer_bounds_m: tuple[
        float, float, float, float, float, float
    ]
    topology_fingerprints: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class AirCellPlan:
    """Immutable indexed partition reused by audit and element streaming."""

    nx: int
    ny: int
    nz: int
    grade_index: int
    connected_candidate_cell_count: int
    connected_internal_cell_mask: bytes
    tnt_index_bounds: tuple[int, int, int, int, int, int]
    active_air_cell_count: int
    connected_internal_air_cell_count: int
    buffer_cell_count: int
    tnt_cell_count: int
    unreachable_internal_cell_count: int
    fingerprint: str


@dataclass(frozen=True, slots=True)
class AirTopologyEvidence:
    active_air_cell_count: int
    connected_internal_air_cell_count: int
    buffer_cell_count: int
    tnt_cell_count: int
    external_path_to_soil_contact_count: int
    buffer_contains_material_count: int
    soil_contact_audited: bool
    material_assignment_audited: bool
    fingerprint: str


def build_air_region(
    building: PhysicalBuildingModel,
    coupling_buffer_bounds: AxisAlignedBox,
) -> AirRegionModel:
    """Derive below-grade internal air from verified artifact topology."""

    if not isinstance(building, PhysicalBuildingModel):
        raise TypeError("building must be a PhysicalBuildingModel")
    grade = building.grade_elevation_m
    if abs(coupling_buffer_bounds.max_z - grade) > 1.0e-9:
        raise ValueError("coupling buffer must terminate exactly at grade")

    connected_bounds: list[tuple[float, float, float, float, float, float]] = []
    connected_opening_bounds: list[
        tuple[float, float, float, float, float, float]
    ] = []
    exterior_opening_bounds: list[
        tuple[float, float, float, float, float, float]
    ] = []
    topology_fingerprints: list[str] = []
    artifact_evidence: list[dict[str, object]] = []
    for artifact_index, artifact in enumerate(building.artifacts):
        definition = artifact.normalized_input
        if not isinstance(definition, Mapping):
            raise ValueError("artifact normalized_input must be a mapping")
        if definition.get("schema_version") != "1.0.0":
            raise ValueError("artifact normalized_input schema_version must be '1.0.0'")

        try:
            compiled = compile_spatial_topology(definition)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "artifact topology_manifest cannot be verified against "
                "normalized_input"
            ) from exc
        if compiled.to_manifest() != artifact.topology_manifest:
            raise ValueError(
                "artifact topology_manifest does not match normalized_input"
            )
        topology_fingerprints.append(compiled.fingerprint)
        boxes = dict(compiled.void_regions)
        opening_boxes = dict(compiled.opening_regions)
        openings = _mapping_rows(definition.get("openings", ()), "openings")

        adjacency: dict[str, set[str]] = {"exterior": set()}
        adjacency.update({space_id: set() for space_id in boxes})
        external_opening_ids: list[str] = []
        opening_records: list[tuple[str, str, str, AxisAlignedBox]] = []
        seen_openings: set[str] = set()
        for row in openings:
            opening_id = _nonempty_text(row.get("id"), "opening id")
            if opening_id in seen_openings:
                raise ValueError(f"duplicate opening id {opening_id!r}")
            seen_openings.add(opening_id)
            if opening_id not in opening_boxes:
                raise ValueError(
                    f"opening {opening_id!r} is absent from the verified topology"
                )
            connects = _sequence(
                row.get("connects"), f"opening {opening_id!r} connects"
            )
            if len(connects) != 2:
                raise ValueError(
                    f"opening {opening_id!r} connects must contain two endpoints"
                )
            left = _nonempty_text(connects[0], "opening endpoint")
            right = _nonempty_text(connects[1], "opening endpoint")
            if left == right:
                raise ValueError(
                    f"opening {opening_id!r} connects endpoints must differ"
                )
            opening_box = opening_boxes[opening_id]
            for endpoint in (left, right):
                if endpoint == "exterior":
                    continue
                if endpoint not in boxes:
                    raise ValueError(
                        f"opening {opening_id!r} references unknown space {endpoint!r}"
                    )
                if not _boxes_share_positive_area_face(opening_box, boxes[endpoint]):
                    raise ValueError(
                        f"opening {opening_id!r} does not touch space {endpoint!r}"
                    )
            if "exterior" in (left, right):
                if not _touches_active_exterior(opening_box, compiled.envelope, grade):
                    raise ValueError(
                        f"opening {opening_id!r} does not reach active exterior air"
                    )
                external_opening_ids.append(opening_id)
            adjacency.setdefault(left, set()).add(right)
            adjacency.setdefault(right, set()).add(left)
            opening_records.append((opening_id, left, right, opening_box))

        if set(opening_boxes) != seen_openings:
            raise ValueError("verified topology opening identity is incomplete")
        connected = _reachable_from_exterior(adjacency)
        artifact_connected: list[str] = []
        for space_id in sorted(connected.intersection(boxes)):
            clipped = _clip_box_top(boxes[space_id], grade)
            if clipped is None:
                continue
            connected_bounds.append(clipped)
            artifact_connected.append(space_id)
        artifact_connected_openings: list[str] = []
        for opening_id, left, right, box in sorted(opening_records):
            if left not in connected or right not in connected:
                continue
            clipped = _clip_box_top(box, grade)
            if clipped is None:
                continue
            connected_opening_bounds.append(clipped)
            artifact_connected_openings.append(opening_id)
            if "exterior" in (left, right):
                exterior_opening_bounds.append(clipped)
        artifact_evidence.append(
            {
                "artifact_index": artifact_index,
                "artifact_fingerprint": artifact.fingerprint,
                "topology_fingerprint": compiled.fingerprint,
                "schema_version": "1.0.0",
                "connected_space_ids": artifact_connected,
                "connected_opening_ids": artifact_connected_openings,
                "external_opening_ids": sorted(external_opening_ids),
            }
        )

    connected_bounds.sort()
    connected_opening_bounds.sort()
    exterior_opening_bounds.sort()
    identity = {
        "schema_version": "phase18.solver_blast.air_region@2",
        "grade_elevation_m": grade,
        "exterior_min_z_m": grade,
        "connected_internal_bounds_m": [list(row) for row in connected_bounds],
        "connected_opening_bounds_m": [
            list(row) for row in connected_opening_bounds
        ],
        "exterior_opening_bounds_m": [
            list(row) for row in exterior_opening_bounds
        ],
        "coupling_buffer_bounds_m": list(coupling_buffer_bounds.as_tuple()),
        "topology_fingerprints": topology_fingerprints,
        "artifact_evidence": artifact_evidence,
    }
    fingerprint = _fingerprint(identity)
    return AirRegionModel(
        grade_elevation_m=grade,
        exterior_min_z_m=grade,
        connected_internal_bounds_m=tuple(connected_bounds),
        connected_opening_bounds_m=tuple(connected_opening_bounds),
        exterior_opening_bounds_m=tuple(exterior_opening_bounds),
        coupling_buffer_bounds_m=coupling_buffer_bounds.as_tuple(),
        topology_fingerprints=tuple(topology_fingerprints),
        fingerprint=fingerprint,
    )


def build_air_cell_plan(
    x_coordinates: tuple[float, ...],
    y_coordinates: tuple[float, ...],
    z_coordinates: tuple[float, ...],
    air_region: AirRegionModel,
    tnt_bounds_m: Sequence[float],
) -> AirCellPlan:
    """Index topology once and prove face-connected internal-air reachability."""

    axes = (x_coordinates, y_coordinates, z_coordinates)
    if any(len(axis) < 2 for axis in axes):
        raise ValueError("ALE axes must each contain at least two coordinates")
    nx, ny, nz = (len(axis) - 1 for axis in axes)
    grade_index = _axis_break_index(z_coordinates, air_region.grade_elevation_m)
    total_cell_count = nx * ny * nz
    candidate_state = bytearray(total_cell_count)
    candidate_count = 0
    for cell_index in _iter_internal_candidate_indices(
        axes, air_region, grade_index
    ):
        if candidate_state[cell_index] == 0:
            candidate_state[cell_index] = 1
            candidate_count += 1
    seeds = (
        cell_index
        for bounds in air_region.exterior_opening_bounds_m
        for cell_index in _cell_indices_for_bounds(axes, bounds)
        if _unflatten(cell_index, nx, ny)[2] == grade_index - 1
    )
    reached_count, unreachable_count = _flood_fill(
        candidate_state, seeds, nx, ny, nz
    )
    if candidate_count and reached_count == 0:
        raise ValueError(
            "connected internal air has no face-connected route to exterior air"
        )
    if unreachable_count:
        raise ValueError(
            "declared internal air is not face-connected to exterior air: "
            f"{unreachable_count} cells unreachable"
        )
    for cell_index, state in enumerate(candidate_state):
        candidate_state[cell_index] = 1 if state == 2 else 0
    connected_mask = bytes(candidate_state)

    tnt_index_bounds = _index_bounds_for_bounds(axes, tnt_bounds_m)
    if tnt_index_bounds is None:
        raise ValueError("ALE TNT partition must contain explicit Solid elements")
    ix0, iy0, iz0, ix1, iy1, iz1 = tnt_index_bounds
    if iz0 < grade_index:
        raise ValueError("TNT charge must lie wholly inside active air")
    tnt_cell_count = (ix1 - ix0) * (iy1 - iy0) * (iz1 - iz0)

    active_total = nx * ny * (nz - grade_index) + reached_count
    active_air_count = active_total - tnt_cell_count
    buffer_count = nx * ny * nz - active_total
    identity = {
        "schema_version": "phase18.solver_blast.air_cell_plan@2",
        "dimensions": [nx, ny, nz],
        "grade_index": grade_index,
        "air_region_fingerprint": air_region.fingerprint,
        "connected_candidate_cell_count": candidate_count,
        "connected_internal_cell_hash": hashlib.sha256(connected_mask).hexdigest(),
        "tnt_index_bounds": list(tnt_index_bounds),
        "active_air_cell_count": active_air_count,
        "buffer_cell_count": buffer_count,
        "tnt_cell_count": tnt_cell_count,
    }
    return AirCellPlan(
        nx=nx,
        ny=ny,
        nz=nz,
        grade_index=grade_index,
        connected_candidate_cell_count=candidate_count,
        connected_internal_cell_mask=connected_mask,
        tnt_index_bounds=tnt_index_bounds,
        active_air_cell_count=active_air_count,
        connected_internal_air_cell_count=reached_count,
        buffer_cell_count=buffer_count,
        tnt_cell_count=tnt_cell_count,
        unreachable_internal_cell_count=unreachable_count,
        fingerprint=_fingerprint(identity),
    )


def classify_ale_cell(
    domain: "AleDomainEstimate",
    ix: int,
    iy: int,
    iz: int,
) -> AirCellKind:
    """Classify one structured cell in constant time."""

    plan = domain.cell_plan
    if ix < 0 or ix >= plan.nx or iy < 0 or iy >= plan.ny or iz < 0 or iz >= plan.nz:
        raise IndexError("ALE cell index is outside the structured domain")
    cell_index = _flatten(ix, iy, iz, plan.nx, plan.ny)
    ix0, iy0, iz0, ix1, iy1, iz1 = plan.tnt_index_bounds
    if ix0 <= ix < ix1 and iy0 <= iy < iy1 and iz0 <= iz < iz1:
        return "explicit_tnt"
    if iz >= plan.grade_index or plan.connected_internal_cell_mask[cell_index]:
        return "active_air"
    return "coupling_buffer"


def audit_air_topology(scene: "SolverBlastScene") -> AirTopologyEvidence:
    """Audit a completed scene against independent soil geometry."""

    return audit_air_domain(scene.air, scene.ground)


def audit_air_domain(
    domain: "AleDomainEstimate",
    ground: "GroundModel | None" = None,
) -> AirTopologyEvidence:
    """Audit indexed role closure without rescanning the full ALE grid."""

    plan = domain.cell_plan
    _validate_cell_plan(domain)
    axes = (domain.x_coordinates, domain.y_coordinates, domain.z_coordinates)
    seen = bytearray(domain.element_count)
    candidate_count = 0
    assigned_candidate_count = 0
    missing_internal_count = 0
    soil_contact_count = 0
    ground_box = (
        AxisAlignedBox.from_bounds(ground.bounds_m) if ground is not None else None
    )
    excavations = (
        tuple(
            AxisAlignedBox.from_bounds(bounds)
            for bounds in ground.excavation_bounds_m
        )
        if ground is not None
        else ()
    )
    for cell_index in _iter_internal_candidate_indices(
        axes, domain.air_region, plan.grade_index
    ):
        if seen[cell_index]:
            continue
        seen[cell_index] = 1
        candidate_count += 1
        if not plan.connected_internal_cell_mask[cell_index]:
            missing_internal_count += 1
            continue
        assigned_candidate_count += 1
        if ground_box is not None:
            ix, iy, iz = _unflatten(cell_index, plan.nx, plan.ny)
            center = _cell_center(domain, ix, iy, iz)
            if ground_box.contains_point(center) and not any(
                excavation.contains_point(center) for excavation in excavations
            ):
                soil_contact_count += 1
    if candidate_count != plan.connected_candidate_cell_count:
        raise ValueError("air cell plan candidate count does not match topology")
    unexpected_below_grade_count = (
        plan.connected_internal_air_cell_count - assigned_candidate_count
    )
    soil_contact_count += unexpected_below_grade_count

    identity = {
        "schema_version": "phase18.solver_blast.air_topology_evidence@2",
        "domain_fingerprint": domain.fingerprint,
        "air_region_fingerprint": domain.air_region.fingerprint,
        "cell_plan_fingerprint": plan.fingerprint,
        "active_air_cell_count": plan.active_air_cell_count,
        "connected_internal_air_cell_count": plan.connected_internal_air_cell_count,
        "buffer_cell_count": plan.buffer_cell_count,
        "tnt_cell_count": plan.tnt_cell_count,
        "external_path_to_soil_contact_count": soil_contact_count,
        "buffer_contains_material_count": missing_internal_count,
        "soil_contact_audited": ground is not None,
        "material_assignment_audited": False,
    }
    return AirTopologyEvidence(
        active_air_cell_count=plan.active_air_cell_count,
        connected_internal_air_cell_count=plan.connected_internal_air_cell_count,
        buffer_cell_count=plan.buffer_cell_count,
        tnt_cell_count=plan.tnt_cell_count,
        external_path_to_soil_contact_count=soil_contact_count,
        buffer_contains_material_count=missing_internal_count,
        soil_contact_audited=ground is not None,
        material_assignment_audited=False,
        fingerprint=_fingerprint(identity),
    )


def _iter_internal_candidate_indices(
    axes: tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]],
    region: AirRegionModel,
    grade_index: int,
) -> Iterator[int]:
    nx, ny = len(axes[0]) - 1, len(axes[1]) - 1
    for bounds in (
        *region.connected_internal_bounds_m,
        *region.connected_opening_bounds_m,
    ):
        for cell_index in _cell_indices_for_bounds(axes, bounds):
            _, _, iz = _unflatten(cell_index, nx, ny)
            if iz < grade_index:
                yield cell_index


def _index_bounds_for_bounds(
    axes: tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]],
    bounds: Sequence[float],
) -> tuple[int, int, int, int, int, int] | None:
    clipped: list[tuple[int, int]] = []
    for axis_index, axis in enumerate(axes):
        lower = max(axis[0], float(bounds[axis_index]))
        upper = min(axis[-1], float(bounds[axis_index + 3]))
        if upper <= lower + _TOLERANCE_M:
            return None
        clipped.append(
            (_axis_break_index(axis, lower), _axis_break_index(axis, upper))
        )
    return (
        clipped[0][0],
        clipped[1][0],
        clipped[2][0],
        clipped[0][1],
        clipped[1][1],
        clipped[2][1],
    )


def _cell_indices_for_bounds(
    axes: tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]],
    bounds: Sequence[float],
) -> Iterator[int]:
    index_bounds = _index_bounds_for_bounds(axes, bounds)
    if index_bounds is None:
        return
    ix0, iy0, iz0, ix1, iy1, iz1 = index_bounds
    nx, ny = len(axes[0]) - 1, len(axes[1]) - 1
    for iz in range(iz0, iz1):
        for iy in range(iy0, iy1):
            for ix in range(ix0, ix1):
                yield _flatten(ix, iy, iz, nx, ny)


def _axis_break_index(axis: tuple[float, ...], value: float) -> int:
    position = bisect.bisect_left(axis, value)
    candidates = tuple(
        index for index in (position - 1, position) if 0 <= index < len(axis)
    )
    for index in candidates:
        if math.isclose(axis[index], value, rel_tol=0.0, abs_tol=_TOLERANCE_M):
            return index
    raise ValueError(f"required topology break {value!r} is absent from ALE axis")


def _flood_fill(
    candidate_state: bytearray,
    seeds: Iterator[int],
    nx: int,
    ny: int,
    nz: int,
) -> tuple[int, int]:
    stack = array("I")
    reached_count = 0
    for cell_index in seeds:
        if candidate_state[cell_index] == 1:
            candidate_state[cell_index] = 2
            stack.append(cell_index)
            reached_count += 1
    while stack:
        cell_index = stack.pop()
        ix, iy, iz = _unflatten(cell_index, nx, ny)
        for dx, dy, dz in (
            (-1, 0, 0),
            (1, 0, 0),
            (0, -1, 0),
            (0, 1, 0),
            (0, 0, -1),
            (0, 0, 1),
        ):
            neighbour = (ix + dx, iy + dy, iz + dz)
            if not (
                0 <= neighbour[0] < nx
                and 0 <= neighbour[1] < ny
                and 0 <= neighbour[2] < nz
            ):
                continue
            neighbour_index = _flatten(*neighbour, nx, ny)
            if candidate_state[neighbour_index] == 1:
                candidate_state[neighbour_index] = 2
                stack.append(neighbour_index)
                reached_count += 1
    return reached_count, candidate_state.count(1)


def _validate_cell_plan(domain: "AleDomainEstimate") -> None:
    plan = domain.cell_plan
    dimensions = (
        len(domain.x_coordinates) - 1,
        len(domain.y_coordinates) - 1,
        len(domain.z_coordinates) - 1,
    )
    if dimensions != (plan.nx, plan.ny, plan.nz):
        raise ValueError("air cell plan dimensions do not match ALE axes")
    if len(plan.connected_internal_cell_mask) != domain.element_count:
        raise ValueError("air cell plan mask length does not match ALE element count")
    if plan.connected_internal_cell_mask.count(0) + plan.connected_internal_cell_mask.count(
        1
    ) != len(plan.connected_internal_cell_mask):
        raise ValueError("air cell plan mask contains an invalid role marker")
    if plan.connected_internal_cell_mask.count(1) != plan.connected_internal_air_cell_count:
        raise ValueError("air cell plan internal-air count does not match its mask")
    if not 0 < plan.grade_index < plan.nz:
        raise ValueError("air cell plan grade index lies outside the ALE domain")
    if not math.isclose(
        domain.z_coordinates[plan.grade_index],
        domain.air_region.grade_elevation_m,
        rel_tol=0.0,
        abs_tol=_TOLERANCE_M,
    ):
        raise ValueError("air cell plan grade index does not match grade elevation")
    ix0, iy0, iz0, ix1, iy1, iz1 = plan.tnt_index_bounds
    if not (
        0 <= ix0 < ix1 <= plan.nx
        and 0 <= iy0 < iy1 <= plan.ny
        and plan.grade_index <= iz0 < iz1 <= plan.nz
    ):
        raise ValueError("air cell plan TNT bounds lie outside active ALE air")
    if (ix1 - ix0) * (iy1 - iy0) * (iz1 - iz0) != plan.tnt_cell_count:
        raise ValueError("air cell plan TNT count does not match its index bounds")
    if plan.unreachable_internal_cell_count != 0:
        raise ValueError("air cell plan contains unreachable internal-air cells")
    if (
        plan.active_air_cell_count
        + plan.buffer_cell_count
        + plan.tnt_cell_count
        != domain.element_count
    ):
        raise ValueError("air cell plan role counts do not close to ALE element count")


def _cell_center(
    domain: "AleDomainEstimate", ix: int, iy: int, iz: int
) -> tuple[float, float, float]:
    return (
        0.5 * (domain.x_coordinates[ix] + domain.x_coordinates[ix + 1]),
        0.5 * (domain.y_coordinates[iy] + domain.y_coordinates[iy + 1]),
        0.5 * (domain.z_coordinates[iz] + domain.z_coordinates[iz + 1]),
    )


def _flatten(ix: int, iy: int, iz: int, nx: int, ny: int) -> int:
    return (iz * ny + iy) * nx + ix


def _unflatten(cell_index: int, nx: int, ny: int) -> tuple[int, int, int]:
    ix = cell_index % nx
    remainder = cell_index // nx
    iy = remainder % ny
    return ix, iy, remainder // ny


def _clip_box_top(
    box: AxisAlignedBox,
    grade: float,
) -> tuple[float, float, float, float, float, float] | None:
    clipped_top = min(box.max_z, grade)
    if clipped_top <= box.min_z + _TOLERANCE_M:
        return None
    return (
        box.min_x,
        box.min_y,
        box.min_z,
        box.max_x,
        box.max_y,
        clipped_top,
    )


def _boxes_share_positive_area_face(
    opening: AxisAlignedBox,
    space: AxisAlignedBox,
) -> bool:
    left, right = opening.as_tuple(), space.as_tuple()
    for axis in range(3):
        if not any(
            math.isclose(a, b, rel_tol=0.0, abs_tol=_TOLERANCE_M)
            for a in (left[axis], left[axis + 3])
            for b in (right[axis], right[axis + 3])
        ):
            continue
        tangent_axes = tuple(index for index in range(3) if index != axis)
        if all(
            min(left[index + 3], right[index + 3])
            - max(left[index], right[index])
            > _TOLERANCE_M
            for index in tangent_axes
        ):
            return True
    return False


def _touches_active_exterior(
    opening: AxisAlignedBox,
    envelope: AxisAlignedBox,
    grade: float,
) -> bool:
    bounds, outer = opening.as_tuple(), envelope.as_tuple()
    touches_envelope = any(
        math.isclose(bounds[axis], outer[axis], rel_tol=0.0, abs_tol=_TOLERANCE_M)
        or math.isclose(
            bounds[axis + 3],
            outer[axis + 3],
            rel_tol=0.0,
            abs_tol=_TOLERANCE_M,
        )
        for axis in range(3)
    )
    return touches_envelope and opening.max_z >= grade - _TOLERANCE_M


def _reachable_from_exterior(adjacency: Mapping[str, set[str]]) -> set[str]:
    reached = {"exterior"}
    queue: deque[str] = deque(("exterior",))
    while queue:
        current = queue.popleft()
        for neighbour in sorted(adjacency.get(current, ())):
            if neighbour in reached:
                continue
            reached.add(neighbour)
            queue.append(neighbour)
    return reached


def _mapping_rows(value: object, name: str) -> tuple[Mapping[str, object], ...]:
    rows = _sequence(value, name)
    if any(not isinstance(row, Mapping) for row in rows):
        raise ValueError(f"{name} must contain mappings")
    return tuple(row for row in rows if isinstance(row, Mapping))


def _sequence(value: object, name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a sequence")
    return value


def _nonempty_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value




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
