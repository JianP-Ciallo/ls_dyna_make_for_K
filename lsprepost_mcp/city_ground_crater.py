from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math

from .config import JSONDict


CAPABILITY_VERSION = "city_ground_crater_v1"
GROUND_RESPONSE_MODE = "validation_crater"
CONTROLLED_MATERIAL_PRESET = "kc_a1_automatic_reference"
CONTROLLED_EROSION_PRESET = "standard_observation"
CONTROLLED_MAXIMUM_PRINCIPAL_STRAIN = 0.05
ALLOWED_GROUND_MESH_SIZES_M = (0.20, 0.15, 0.10)
ALLOWED_ALE_OVERLAP_LAYERS = (5, 7)
DERIVED_GROUND_RESPONSE_FIELDS = {
    "actual_ale_overlap_layers",
    "ale_overlap_depth_m",
    "eroding_zone_half_width_m",
    "eroding_ground_depth_m",
    "support_depth_m",
    "total_ground_depth_m",
    "local_mesh_size_m",
    "foundation_guard_distance_m",
    "interpretation",
    "erosion_interpretation",
    "material_validation_status",
}

ERODING_GROUND_PART_ID = 90
ERODING_GROUND_SECTION_ID = 90
ERODING_GROUND_MATERIAL_ID = 90
SUPPORT_GROUND_PART_ID = 92
SUPPORT_GROUND_SECTION_ID = 92
SUPPORT_GROUND_MATERIAL_ID = 91
ERODING_PART_SET_ID = 1201
PERIPHERAL_FSI_SEGMENT_SET_ID = 1202
GROUND_NONREFLECTING_SEGMENT_SET_ID = 1203
GROUND_PROBE_SOLID_SET_ID = 1204
GROUND_HISTORY_NODE_SET_ID = 1205
GROUND_ANCHOR_NODE_SET_IDS = (1206, 1207, 1208)
ERODING_INITIAL_SEGMENT_SET_ID = 1209
ERODING_FSI_SURFACE_ID = 91
PERIPHERAL_FSI_SURFACE_ID = 92
FOUNDATION_NODE_SET_ID_BASE = 1500
FOUNDATION_SEGMENT_SET_ID_BASE = 1400

Node = tuple[int, float, float, float]
SolidElement = tuple[int, int, int, int, int, int, int, int, int, int]
Segment = tuple[int, int, int, int]


@dataclass(frozen=True)
class GroundCraterModel:
    nodes: list[Node]
    solids: list[SolidElement]
    part_node_ids: dict[int, list[int]]
    part_element_ids: dict[int, list[int]]
    part_bounds_m: dict[int, JSONDict]
    eroding_initial_segments: list[Segment]
    peripheral_exposed_segments: list[Segment]
    nonreflecting_segments: list[Segment]
    foundation_segments: dict[str, list[Segment]]
    anchor_node_ids: tuple[int, int, int]
    probe_solid_ids: list[int]
    history_node_ids: list[int]
    metadata: JSONDict


def default_ground_response() -> JSONDict:
    return {
        "mode": GROUND_RESPONSE_MODE,
        "anticipated_crater_depth_m": 0.6,
        "ale_overlap_layers": 5,
        "erosion_mode": CONTROLLED_EROSION_PRESET,
        "material_preset": CONTROLLED_MATERIAL_PRESET,
        "capability_version": CAPABILITY_VERSION,
    }


def normalize_ground_response(
    value: object,
    *,
    source_center_m: list[float],
    domain_bounds_m: tuple[list[float], list[float]],
    foundation_bounds: list[JSONDict],
    mesh_size_m: float,
) -> JSONDict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("ground_response must be an object")
    input_fields = {
        "mode",
        "anticipated_crater_depth_m",
        "ale_overlap_layers",
        "erosion_mode",
        "material_preset",
        "capability_version",
        "maximum_principal_strain",
        "confirmed_by_user",
    }
    derived_fields = set(DERIVED_GROUND_RESPONSE_FIELDS)
    if value.get("erosion_mode") == CONTROLLED_EROSION_PRESET:
        derived_fields.add("maximum_principal_strain")
    unknown = sorted(set(value) - input_fields - derived_fields)
    if unknown:
        raise ValueError(
            "ground_response contains unknown properties: "
            + ", ".join(unknown)
        )

    provided_derived = {
        key: deepcopy(value[key]) for key in derived_fields if key in value
    }
    result = deepcopy(
        {key: item for key, item in value.items() if key not in derived_fields}
    )
    if result.get("mode") != GROUND_RESPONSE_MODE:
        raise ValueError(
            f"ground_response.mode must be {GROUND_RESPONSE_MODE}"
        )
    if result.get("capability_version") != CAPABILITY_VERSION:
        raise ValueError(
            f"ground_response.capability_version must be {CAPABILITY_VERSION}"
        )
    if result.get("material_preset") != CONTROLLED_MATERIAL_PRESET:
        raise ValueError(
            "ground_response.material_preset must be "
            f"{CONTROLLED_MATERIAL_PRESET}"
        )

    mesh_size = _finite(mesh_size_m, "ground mesh size")
    if not any(
        math.isclose(mesh_size, allowed_size, abs_tol=1.0e-12)
        for allowed_size in ALLOWED_GROUND_MESH_SIZES_M
    ):
        raise ValueError("ground mesh size must be 0.20, 0.15, or 0.10 m")

    anticipated_depth = _finite(
        result.get("anticipated_crater_depth_m"),
        "ground_response.anticipated_crater_depth_m",
    )
    if anticipated_depth <= 0.0:
        raise ValueError(
            "ground_response.anticipated_crater_depth_m must be positive"
        )
    requested_layers = result.get("ale_overlap_layers")
    if (
        isinstance(requested_layers, bool)
        or not isinstance(requested_layers, int)
        or requested_layers not in ALLOWED_ALE_OVERLAP_LAYERS
    ):
        raise ValueError("ground_response.ale_overlap_layers must be 5 or 7")

    erosion_mode = result.get("erosion_mode")
    if erosion_mode == CONTROLLED_EROSION_PRESET:
        if "maximum_principal_strain" in result:
            raise ValueError(
                "maximum_principal_strain is fixed by standard_observation"
            )
        if "confirmed_by_user" in result:
            raise ValueError(
                "confirmed_by_user is only valid for custom erosion"
            )
        maximum_principal_strain = CONTROLLED_MAXIMUM_PRINCIPAL_STRAIN
    elif erosion_mode == "custom":
        maximum_principal_strain = _finite(
            result.get("maximum_principal_strain"),
            "ground_response.maximum_principal_strain",
        )
        if not 0.02 <= maximum_principal_strain <= 0.15:
            raise ValueError(
                "ground_response.maximum_principal_strain must be between "
                "0.02 and 0.15"
            )
        if result.get("confirmed_by_user") is not True:
            raise ValueError("custom erosion requires confirmed_by_user=true")
    else:
        raise ValueError(
            "ground_response.erosion_mode must be standard_observation or "
            "confirmed custom"
        )

    actual_layers = max(
        requested_layers,
        math.ceil(anticipated_depth / mesh_size) + 2,
        4,
    )
    overlap_depth = actual_layers * mesh_size
    raw_half_width = max(
        3.0,
        2.0 * anticipated_depth + 4.0 * mesh_size,
    )
    half_width = math.ceil(raw_half_width / mesh_size) * mesh_size
    eroding_ground_depth = overlap_depth + 2.0 * mesh_size
    support_depth = max(0.4, 2.0 * mesh_size)
    total_ground_depth = eroding_ground_depth + support_depth
    guard_distance = 2.0 * mesh_size

    source_x, source_y = source_center_m[:2]
    domain_min, domain_max = domain_bounds_m
    if not (
        domain_min[0] + half_width + guard_distance <= source_x
        <= domain_max[0] - half_width - guard_distance
        and domain_min[1] + half_width + guard_distance <= source_y
        <= domain_max[1] - half_width - guard_distance
    ):
        raise ValueError(
            "invalid_ground_geometry: eroding zone and two-cell guard must "
            "fit inside the city domain"
        )

    zone_min_x = source_x - half_width - guard_distance
    zone_max_x = source_x + half_width + guard_distance
    zone_min_y = source_y - half_width - guard_distance
    zone_max_y = source_y + half_width + guard_distance
    for foundation in foundation_bounds:
        lower = foundation["min"]
        upper = foundation["max"]
        if (
            zone_min_x < float(upper[0])
            and zone_max_x > float(lower[0])
            and zone_min_y < float(upper[1])
            and zone_max_y > float(lower[1])
        ):
            object_id = str(foundation.get("object_id", "unknown"))
            raise ValueError(
                "crater_zone_intersects_foundation: "
                f"eroding zone is too close to {object_id}"
            )

    result.update(
        {
            "anticipated_crater_depth_m": anticipated_depth,
            "ale_overlap_layers": requested_layers,
            "actual_ale_overlap_layers": actual_layers,
            "ale_overlap_depth_m": overlap_depth,
            "eroding_zone_half_width_m": half_width,
            "eroding_ground_depth_m": eroding_ground_depth,
            "support_depth_m": support_depth,
            "total_ground_depth_m": total_ground_depth,
            "local_mesh_size_m": mesh_size,
            "foundation_guard_distance_m": guard_distance,
            "maximum_principal_strain": maximum_principal_strain,
            "interpretation": "validation_only_uncalibrated_ground",
            "erosion_interpretation": "numerical_element_deletion_only",
            "material_validation_status": (
                "automatic_reference_not_site_calibrated"
            ),
        }
    )
    for key, provided in provided_derived.items():
        expected = result[key]
        if (
            isinstance(provided, (int, float))
            and not isinstance(provided, bool)
            and isinstance(expected, (int, float))
            and not isinstance(expected, bool)
        ):
            matches = math.isclose(
                float(provided),
                float(expected),
                rel_tol=1.0e-12,
                abs_tol=1.0e-12,
            )
        else:
            matches = provided == expected
        if not matches:
            raise ValueError(
                "derived ground_response field does not match current inputs: "
                f"{key}"
            )
    return result


def build_ground_crater_model(
    config: JSONDict,
    *,
    x_axis: list[float],
    y_axis: list[float],
    source_center_m: list[float],
    road_width_m: float,
    foundation_bounds: list[JSONDict],
    node_id_start: int,
    solid_element_id_start: int,
) -> GroundCraterModel:
    h = float(config["local_mesh_size_m"])
    total_depth = float(config["total_ground_depth_m"])
    eroding_depth = float(config["eroding_ground_depth_m"])
    half_width = float(config["eroding_zone_half_width_m"])
    layer_count = round(total_depth / h)
    if not math.isclose(layer_count * h, total_depth, abs_tol=1.0e-9):
        raise ValueError("invalid_ground_geometry: depth is not mesh aligned")
    z_axis = [-total_depth + index * h for index in range(layer_count + 1)]
    z_axis[-1] = 0.0
    nx = len(x_axis) - 1
    ny = len(y_axis) - 1
    nz = len(z_axis) - 1
    if min(nx, ny, nz) <= 0:
        raise ValueError("invalid_ground_geometry: empty ground mesh")

    def nid(ix: int, iy: int, iz: int) -> int:
        return (
            node_id_start
            + iz * (ny + 1) * (nx + 1)
            + iy * (nx + 1)
            + ix
        )

    nodes = [
        (nid(ix, iy, iz), x_axis[ix], y_axis[iy], z_axis[iz])
        for iz in range(nz + 1)
        for iy in range(ny + 1)
        for ix in range(nx + 1)
    ]
    source_x, source_y = source_center_m[:2]
    road_half_width = 0.5 * road_width_m

    def surface_part_id(x: float, y: float) -> int:
        if -road_half_width <= y <= road_half_width:
            if x < -road_half_width:
                return 10
            if x > road_half_width:
                return 11
            return 14
        if -road_half_width <= x <= road_half_width:
            return 12 if y < -road_half_width else 13
        if x < -road_half_width:
            return 15 if y > road_half_width else 17
        return 16 if y > road_half_width else 18

    solids: list[SolidElement] = []
    part_element_ids: dict[int, list[int]] = {}
    part_node_sets: dict[int, set[int]] = {}
    minimum_volume = math.inf
    top_segments_by_cell: dict[tuple[int, int], Segment] = {}
    top_part_by_cell: dict[tuple[int, int], int] = {}
    element_id_by_cell: dict[tuple[int, int, int], int] = {}
    for iz in range(nz):
        z_center = 0.5 * (z_axis[iz] + z_axis[iz + 1])
        support_layer = z_center < -eroding_depth - 1.0e-12
        for iy in range(ny):
            y_center = 0.5 * (y_axis[iy] + y_axis[iy + 1])
            for ix in range(nx):
                x_center = 0.5 * (x_axis[ix] + x_axis[ix + 1])
                central = (
                    abs(x_center - source_x) <= half_width + 1.0e-12
                    and abs(y_center - source_y) <= half_width + 1.0e-12
                )
                if support_layer:
                    pid = SUPPORT_GROUND_PART_ID
                elif central:
                    pid = ERODING_GROUND_PART_ID
                else:
                    pid = surface_part_id(x_center, y_center)
                n1 = nid(ix, iy, iz)
                n2 = nid(ix + 1, iy, iz)
                n3 = nid(ix + 1, iy + 1, iz)
                n4 = nid(ix, iy + 1, iz)
                n5 = nid(ix, iy, iz + 1)
                n6 = nid(ix + 1, iy, iz + 1)
                n7 = nid(ix + 1, iy + 1, iz + 1)
                n8 = nid(ix, iy + 1, iz + 1)
                element_id = solid_element_id_start + len(solids)
                element = (
                    element_id,
                    pid,
                    n1,
                    n2,
                    n3,
                    n4,
                    n5,
                    n6,
                    n7,
                    n8,
                )
                solids.append(element)
                element_id_by_cell[(ix, iy, iz)] = element_id
                part_element_ids.setdefault(pid, []).append(element_id)
                part_node_sets.setdefault(pid, set()).update(element[2:10])
                minimum_volume = min(
                    minimum_volume,
                    (x_axis[ix + 1] - x_axis[ix])
                    * (y_axis[iy + 1] - y_axis[iy])
                    * (z_axis[iz + 1] - z_axis[iz]),
                )
                if iz == nz - 1:
                    top_segments_by_cell[(ix, iy)] = (n5, n6, n7, n8)
                    top_part_by_cell[(ix, iy)] = pid

    foundation_segments: dict[str, list[Segment]] = {
        str(item["object_id"]): [] for item in foundation_bounds
    }
    covered_cells: set[tuple[int, int]] = set()
    for cell, segment in top_segments_by_cell.items():
        ix, iy = cell
        matching = [
            item
            for item in foundation_bounds
            if x_axis[ix] < float(item["max"][0])
            and x_axis[ix + 1] > float(item["min"][0])
            and y_axis[iy] < float(item["max"][1])
            and y_axis[iy + 1] > float(item["min"][1])
        ]
        if len(matching) > 1:
            raise ValueError(
                "invalid_ground_geometry: overlapping foundation footprints"
            )
        if matching:
            object_id = str(matching[0]["object_id"])
            foundation_segments[object_id].append(segment)
            covered_cells.add(cell)

    empty_foundations = sorted(
        object_id
        for object_id, segments in foundation_segments.items()
        if not segments
    )
    if empty_foundations:
        raise ValueError(
            "invalid_ground_geometry: no ground target segments below "
            + ", ".join(empty_foundations)
        )

    eroding_initial_segments = [
        segment
        for cell, segment in top_segments_by_cell.items()
        if top_part_by_cell[cell] == ERODING_GROUND_PART_ID
    ]
    peripheral_exposed_segments = [
        segment
        for cell, segment in top_segments_by_cell.items()
        if top_part_by_cell[cell] != ERODING_GROUND_PART_ID
        and cell not in covered_cells
    ]
    if not eroding_initial_segments or not peripheral_exposed_segments:
        raise ValueError("ground_fsi_invalid: exposed ground segment set is empty")

    nonreflecting_segments: list[Segment] = []
    for iz in range(nz):
        for iy in range(ny):
            nonreflecting_segments.append(
                (
                    nid(0, iy, iz),
                    nid(0, iy + 1, iz),
                    nid(0, iy + 1, iz + 1),
                    nid(0, iy, iz + 1),
                )
            )
            nonreflecting_segments.append(
                (
                    nid(nx, iy, iz),
                    nid(nx, iy, iz + 1),
                    nid(nx, iy + 1, iz + 1),
                    nid(nx, iy + 1, iz),
                )
            )
        for ix in range(nx):
            nonreflecting_segments.append(
                (
                    nid(ix, 0, iz),
                    nid(ix, 0, iz + 1),
                    nid(ix + 1, 0, iz + 1),
                    nid(ix + 1, 0, iz),
                )
            )
            nonreflecting_segments.append(
                (
                    nid(ix, ny, iz),
                    nid(ix + 1, ny, iz),
                    nid(ix + 1, ny, iz + 1),
                    nid(ix, ny, iz + 1),
                )
            )
    for iy in range(ny):
        for ix in range(nx):
            nonreflecting_segments.append(
                (
                    nid(ix, iy, 0),
                    nid(ix + 1, iy, 0),
                    nid(ix + 1, iy + 1, 0),
                    nid(ix, iy + 1, 0),
                )
            )

    anchor_node_ids = (
        nid(0, 0, 0),
        nid(nx, 0, 0),
        nid(0, ny, 0),
    )
    center_ix = _cell_index(x_axis, source_x)
    center_iy = _cell_index(y_axis, source_y)
    target_depths = (
        -0.5 * h,
        -0.5 * float(config["ale_overlap_depth_m"]),
        -float(config["ale_overlap_depth_m"]) - 0.5 * h,
    )
    probe_solid_ids = []
    for target_z in target_depths:
        probe_iz = min(
            range(nz),
            key=lambda index: abs(
                0.5 * (z_axis[index] + z_axis[index + 1]) - target_z
            ),
        )
        probe_solid_ids.append(
            element_id_by_cell[(center_ix, center_iy, probe_iz)]
        )
    top_iz = nz
    history_node_ids = sorted(
        {
            nid(center_ix, center_iy, top_iz),
            nid(center_ix + 1, center_iy + 1, top_iz),
            nid(_nearest_index(x_axis, source_x - half_width), center_iy, top_iz),
            nid(_nearest_index(x_axis, source_x + half_width), center_iy, top_iz),
            nid(center_ix, _nearest_index(y_axis, source_y - half_width), top_iz),
            nid(center_ix, _nearest_index(y_axis, source_y + half_width), top_iz),
        }
    )

    part_node_ids = {
        pid: sorted(node_ids) for pid, node_ids in part_node_sets.items()
    }
    coordinates = {node_id: (x, y, z) for node_id, x, y, z in nodes}
    part_bounds_m = {
        pid: {
            "min": [
                min(coordinates[node_id][axis] for node_id in node_ids)
                for axis in range(3)
            ],
            "max": [
                max(coordinates[node_id][axis] for node_id in node_ids)
                for axis in range(3)
            ],
        }
        for pid, node_ids in part_node_ids.items()
    }
    fingerprint_payload = {
        "x_axis": x_axis,
        "y_axis": y_axis,
        "z_axis": z_axis,
        "source_center_m": source_center_m,
        "part_element_counts": {
            str(pid): len(ids) for pid, ids in sorted(part_element_ids.items())
        },
    }
    mesh_fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    eroding_faces = {tuple(sorted(segment)) for segment in eroding_initial_segments}
    peripheral_faces = {
        tuple(sorted(segment)) for segment in peripheral_exposed_segments
    }
    metadata: JSONDict = {
        **deepcopy(config),
        "source_center_m": list(source_center_m),
        "mesh_fingerprint": mesh_fingerprint,
        "solid_element_count": len(solids),
        "ground_node_count": len(nodes),
        "minimum_initial_solid_volume_m3": minimum_volume,
        "eroding_part_id": ERODING_GROUND_PART_ID,
        "support_part_id": SUPPORT_GROUND_PART_ID,
        "surface_part_ids": list(range(10, 19)),
        "part_element_counts": {
            str(pid): len(ids) for pid, ids in sorted(part_element_ids.items())
        },
        "eroding_fsi": {
            "ctype": 5,
            "slave_part_ids": [ERODING_GROUND_PART_ID],
            "part_set_id": ERODING_PART_SET_ID,
            "surface_id": ERODING_FSI_SURFACE_ID,
            "initial_segment_set_id": ERODING_INITIAL_SEGMENT_SET_ID,
            "initial_exposed_segment_count": len(eroding_initial_segments),
        },
        "peripheral_fsi": {
            "ctype": 4,
            "segment_set_id": PERIPHERAL_FSI_SEGMENT_SET_ID,
            "surface_id": PERIPHERAL_FSI_SURFACE_ID,
            "exposed_segment_count": len(peripheral_exposed_segments),
        },
        "duplicate_fsi_face_count": len(eroding_faces & peripheral_faces),
        "covered_ground_segment_count": len(covered_cells),
        "foundation_target_segment_counts": {
            object_id: len(segments)
            for object_id, segments in foundation_segments.items()
        },
        "foundation_tie_count": len(foundation_segments),
        "nonreflecting_segment_count": len(nonreflecting_segments),
        "anchor_node_ids": list(anchor_node_ids),
        "probe_solid_ids": list(probe_solid_ids),
        "history_node_ids": list(history_node_ids),
        "z_axis_m": z_axis,
    }
    return GroundCraterModel(
        nodes=nodes,
        solids=solids,
        part_node_ids=part_node_ids,
        part_element_ids=part_element_ids,
        part_bounds_m=part_bounds_m,
        eroding_initial_segments=eroding_initial_segments,
        peripheral_exposed_segments=peripheral_exposed_segments,
        nonreflecting_segments=nonreflecting_segments,
        foundation_segments=foundation_segments,
        anchor_node_ids=anchor_node_ids,
        probe_solid_ids=probe_solid_ids,
        history_node_ids=history_node_ids,
        metadata=metadata,
    )


def render_ground_crater_cards(
    model: GroundCraterModel,
    *,
    ale_part_set_id: int,
) -> list[str]:
    lines = [
        "*SET_PART_LIST_TITLE",
        "Eroding K&C ground part",
        str(ERODING_PART_SET_ID),
        str(ERODING_GROUND_PART_ID),
        "*SET_SEGMENT_TITLE",
        "Initial exposed K&C ground surface",
        f"{ERODING_INITIAL_SEGMENT_SET_ID},0,0,0,0",
    ]
    lines.extend(_segment_lines(model.eroding_initial_segments))
    lines.extend(
        [
            "*SET_SEGMENT_TITLE",
            "Exposed non-eroding city ground surface",
            f"{PERIPHERAL_FSI_SEGMENT_SET_ID},0,0,0,0",
        ]
    )
    lines.extend(_segment_lines(model.peripheral_exposed_segments))
    lines.extend(
        [
            "*CONSTRAINED_LAGRANGE_IN_SOLID",
            "$ ground crater eroding FSI CTYPE=5",
            "$#   slave    master     sstyp     mstyp     nquad     ctype     direc     mcoup",
            f"{ERODING_PART_SET_ID},{ale_part_set_id},0,0,4,5,2,0",
            "$#   start       end      pfac      fric    frcmin      norm   normtyp      damp",
            "0.0,0.0,0.1,0.0,0.3,0,0,0.1",
            "$#       k      hmin      hmax     ileak     pleak   lcidpor     nvent    iblock",
            "0.0,0.0,0.0,2,0.1,0,0,0",
            "*CONSTRAINED_LAGRANGE_IN_SOLID",
            "$ ground crater peripheral FSI CTYPE=4",
            "$#   slave    master     sstyp     mstyp     nquad     ctype     direc     mcoup",
            f"{PERIPHERAL_FSI_SEGMENT_SET_ID},{ale_part_set_id},2,0,4,4,2,0",
            "$#   start       end      pfac      fric    frcmin      norm   normtyp      damp",
            "0.0,0.0,0.1,0.0,0.3,0,0,0.1",
            "$#       k      hmin      hmax     ileak     pleak   lcidpor     nvent    iblock",
            "0.0,0.0,0.0,2,0.1,0,0,0",
            "*SET_SEGMENT_TITLE",
            "Ground lateral and bottom non-reflecting boundary",
            f"{GROUND_NONREFLECTING_SEGMENT_SET_ID},0,0,0,0",
        ]
    )
    lines.extend(_segment_lines(model.nonreflecting_segments))
    lines.extend(
        [
            "*BOUNDARY_NON_REFLECTING",
            f"{GROUND_NONREFLECTING_SEGMENT_SET_ID},0.0,0.0",
            "*SET_SOLID_LIST_TITLE",
            "K&C crater response and deletion history",
            str(GROUND_PROBE_SOLID_SET_ID),
        ]
    )
    lines.extend(
        _chunked_ids(model.part_element_ids[ERODING_GROUND_PART_ID])
    )
    lines.extend(
        [
            "*DATABASE_HISTORY_SOLID_SET",
            str(GROUND_PROBE_SOLID_SET_ID),
            "*SET_NODE_LIST_TITLE",
            "Ground crater displacement and reflection probes",
            str(GROUND_HISTORY_NODE_SET_ID),
            ",".join(str(value) for value in model.history_node_ids),
            "*DATABASE_HISTORY_NODE_SET",
            str(GROUND_HISTORY_NODE_SET_ID),
        ]
    )
    anchor_dofs = ((1, 1, 1), (0, 1, 1), (0, 0, 1))
    for set_id, node_id, dofs in zip(
        GROUND_ANCHOR_NODE_SET_IDS,
        model.anchor_node_ids,
        anchor_dofs,
        strict=True,
    ):
        lines.extend(
            [
                "*SET_NODE_LIST_TITLE",
                "Minimal ground rigid-body anchor",
                str(set_id),
                str(node_id),
                "*BOUNDARY_SPC_SET",
                f"{set_id},0,{dofs[0]},{dofs[1]},{dofs[2]},0,0,0",
            ]
        )
    return lines


def render_foundation_tie_cards(
    model: GroundCraterModel,
    base_node_ids: dict[str, list[int]],
) -> list[str]:
    if set(base_node_ids) != set(model.foundation_segments):
        raise ValueError("invalid_ground_geometry: foundation tie identities differ")
    lines: list[str] = []
    for index, object_id in enumerate(sorted(base_node_ids), start=1):
        node_ids = sorted(set(base_node_ids[object_id]))
        segments = model.foundation_segments[object_id]
        if not node_ids or not segments:
            raise ValueError(
                f"invalid_ground_geometry: empty foundation tie for {object_id}"
            )
        node_set_id = FOUNDATION_NODE_SET_ID_BASE + index
        segment_set_id = FOUNDATION_SEGMENT_SET_ID_BASE + index
        lines.extend(
            [
                "*SET_NODE_LIST_TITLE",
                f"Ground-tied base nodes: {object_id}",
                str(node_set_id),
            ]
        )
        lines.extend(_chunked_ids(node_ids))
        lines.extend(
            [
                "*SET_SEGMENT_TITLE",
                f"Ground target surface: {object_id}",
                f"{segment_set_id},0,0,0,0",
            ]
        )
        lines.extend(_segment_lines(segments))
        lines.extend(
            [
                "*CONTACT_TIED_NODES_TO_SURFACE",
                f"$ city foundation tie: {object_id}",
                "$#   ssid      msid     sstyp     mstyp    sboxid    mboxid       spr       mpr",
                f"{node_set_id},{segment_set_id},4,0,0,0,0,0",
                "$#     fs        fd        dc        vc       vdc    penchk        bt        dt",
                "0,0,0,0,0,0,0,0",
                "$#    sfs       sfm       sst       mst      sfst      sfmt       fsf       vsf",
                "0,0,0,0,0,0,0,0",
            ]
        )
    return lines


def _cell_index(axis: list[float], value: float) -> int:
    for index in range(len(axis) - 1):
        if axis[index] - 1.0e-12 <= value <= axis[index + 1] + 1.0e-12:
            return min(index, len(axis) - 2)
    raise ValueError("invalid_ground_geometry: source lies outside ground mesh")


def _nearest_index(axis: list[float], value: float) -> int:
    return min(range(len(axis)), key=lambda index: abs(axis[index] - value))


def _segment_lines(segments: list[Segment]) -> list[str]:
    return [",".join(str(value) for value in segment) for segment in segments]


def _chunked_ids(values: list[int], width: int = 8) -> list[str]:
    return [
        ",".join(str(value) for value in values[index : index + width])
        for index in range(0, len(values), width)
    ]


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number")
    return result
