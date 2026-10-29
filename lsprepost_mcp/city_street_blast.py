from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
import hashlib
import json
import math
from typing import Iterable

from .ale import default_ale_air_definition, render_ale_air_cards
from .component_library import component_definition, default_component_geometry
from .config import DEFAULT_UNIT_SYSTEM, JSONDict
from .city_editor import (
    city_instance_id,
    city_mobility_for,
    ensure_subway_entrance_instances,
    parked_vehicle_instance_id,
    subway_entrance_instance_id,
)
from .city_layout_contract import (
    city_editor_state_fingerprint,
    city_layout_fingerprint,
)
from .city_ground_crater import (
    ERODING_GROUND_MATERIAL_ID,
    ERODING_GROUND_PART_ID,
    ERODING_GROUND_SECTION_ID,
    ERODING_FSI_SURFACE_ID,
    PERIPHERAL_FSI_SURFACE_ID,
    SUPPORT_GROUND_MATERIAL_ID,
    SUPPORT_GROUND_PART_ID,
    SUPPORT_GROUND_SECTION_ID,
    build_ground_crater_model,
    normalize_ground_response,
    render_foundation_tie_cards,
    render_ground_crater_cards,
)
from .dyna_assembly import (
    Node,
    ShellElement,
    SolidElement,
    apply_transform,
    build_component_geometry,
)
from .materials import resolve_material
from .paths import safe_project_name
from .phase15_materials import (
    default_phase15_materials,
    render_phase15_material_cards,
)


AIR_PART_ID = 1
TNT_PART_ID = 2
AIR_SECTION_ID = 1
TNT_SECTION_ID = 2
AIR_MATERIAL_ID = 1
TNT_MATERIAL_ID = 2
URBAN_CONCRETE_MATERIAL_ID = 3
URBAN_STEEL_MATERIAL_ID = 4
ALE_PART_SET_ID = 1001
FSI_SEGMENT_SET_ID = 1002
OUTER_SEGMENT_SET_ID = 1003
FIXED_URBAN_NODE_SET_ID = 1004
ALE_PROBE_SOLID_SET_ID = 1005
VEHICLE_PART_SET_ID = 1006
VEHICLE_SUPPORT_PART_SET_ID = 1007
ALE_GROUND_NODE_SET_ID = 1008
RESPONSE_FSI_SURFACE_ID_BASE = 110
RESPONSE_FSI_SEGMENT_SET_ID_BASE = 1100
RESPONSE_SHELL_HISTORY_SET_ID_BASE = 1200
RESPONSE_NODE_HISTORY_SET_ID_BASE = 1300
TNT_GUIDE_MATERIAL_ID = 5
MIN_GROUNDED_SUPPORT_RATIO = 0.95
CITY_CRATER_D3PLOT_CURVE_ID = 990017


def default_city_street_blast_spec(
    project_name: str = "city_street_blast",
) -> JSONDict:
    explosive = default_phase15_materials()["tnt"]
    mass = 250.0
    diameter = 0.6
    radius = 0.5 * diameter
    length = mass / (
        float(explosive["density_kg_per_m3"]) * math.pi * radius * radius
    )
    urban_reference = resolve_material({"name": "concrete_linear_elastic_demo"})
    return {
        "project_name": project_name,
        "model_type": "city_street_blast_scene",
        "scene_id": "city_street_blast",
        "unit_system": DEFAULT_UNIT_SYSTEM,
        "domain": {
            "min_m": [-36.0, -36.0, 0.0],
            "max_m": [36.0, 36.0, 20.0],
        },
        "mesh": {
            "size_m": 0.2,
            "near_size_m": 0.2,
            "urban_size_m": 1.0,
            "far_size_m": 1.5,
            "near_half_width_m": 2.0,
            "urban_half_width_m": 14.0,
            "near_height_m": 4.0,
        },
        "explosive": {
            "geometry_type": "solid_cylinder",
            "material": "tnt_jwl_phase15_reference",
            "mass_kg": mass,
            "density_kg_per_m3": float(explosive["density_kg_per_m3"]),
            "diameter_m": diameter,
            "length_m": length,
            "base_center_m": [0.0, 0.0, 0.01],
            "detonation_point": "geometric_center",
        },
        "layout": {
            "road_width_m": 16.0,
            "road_thickness_m": 0.25,
            "residential_setback_m": 10.0,
            "supermarket": {
                **default_component_geometry("commercial_supermarket"),
                "origin_m": [-34.0, 12.0, 0.0],
            },
            "residential_community": {
                **default_component_geometry("residential_community"),
                "tower_length_m": 7.0,
                "tower_width_m": 8.0,
                "tower_height_m": 15.0,
                "tower_count": 2,
                "tower_spacing_m": 3.0,
                "origin_m": [-35.0, -26.0, 0.0],
            },
            "subway_entrance": {
                **default_component_geometry("subway_entrance"),
                "enclosure": "front_open_three_sides_enclosed",
                "open_side": "y_min",
                "instances": [
                    {
                        "instance_id": "subway_entrance",
                        "origin_m": [12.0, 12.0, 0.0],
                        "rotate_z_deg": 0.0,
                    }
                ],
            },
            "parking_lot": {
                **default_component_geometry("parking_lot"),
                "length_m": 18.0,
                "width_m": 14.0,
                "origin_m": [14.0, -32.0, 0.02],
            },
            "parked_vehicles": {
                **default_component_geometry("parked_vehicle"),
                "instances": [
                    {
                        "instance_id": "parked_vehicle_1",
                        "origin_m": [16.0, -30.0, 0.10],
                        "rotate_z_deg": 0.0,
                    },
                    {
                        "instance_id": "parked_vehicle_2",
                        "origin_m": [21.5, -30.0, 0.10],
                        "rotate_z_deg": 0.0,
                    },
                    {
                        "instance_id": "parked_vehicle_3",
                        "origin_m": [16.0, -25.5, 0.10],
                        "rotate_z_deg": 0.0,
                    },
                    {
                        "instance_id": "parked_vehicle_4",
                        "origin_m": [21.5, -25.5, 0.10],
                        "rotate_z_deg": 0.0,
                    },
                ],
            },
            "traffic_lights": {
                **default_component_geometry("traffic_light"),
                "instances": [
                    {"origin_m": [-9.0, -9.0, 0.0], "rotate_z_deg": 0.0},
                    {"origin_m": [9.0, -9.0, 0.0], "rotate_z_deg": 90.0},
                    {"origin_m": [9.0, 9.0, 0.0], "rotate_z_deg": 180.0},
                    {"origin_m": [-9.0, 9.0, 0.0], "rotate_z_deg": 270.0},
                ],
            },
            "library_components": {
                "shell_box": {
                    "length_m": 2.0,
                    "width_m": 1.2,
                    "height_m": 1.4,
                    "thickness_m": 0.01,
                    "instances": [],
                },
            },
        },
        "analysis": {
            "end_time_s": 0.05,
            "d3plot_dt_s": 0.001,
            "history_dt_s": 0.00005,
        },
        "geometry": {"scene": "city_street_blast", "dimensionality": "3d"},
        "material": urban_reference,
        "components": [],
        "contacts": [],
        "sets": [],
        "boundary_conditions": [{"type": "generated_node_spc", "set_id": FIXED_URBAN_NODE_SET_ID}],
        "loads": [],
        "curves": [],
        "hourglass": {},
        "analysis_control": {"termination": {"end_time_s": 0.05}},
        "database": {"d3plot_dt_s": 0.001},
        "solver_permission": "explicit_user_approval_required",
        "validation_status": "generated_not_solver_validated",
    }


def validate_city_street_blast_spec(raw: JSONDict) -> JSONDict:
    if not isinstance(raw, dict):
        raise ValueError("city street blast spec must be an object")
    spec = deepcopy(raw)
    project_name = str(spec.get("project_name", "")).strip()
    if not project_name or safe_project_name(project_name) != project_name:
        raise ValueError("project_name contains unsupported characters")
    if spec.get("scene_id") != "city_street_blast":
        raise ValueError("scene_id must be city_street_blast")
    if spec.get("unit_system") != DEFAULT_UNIT_SYSTEM:
        raise ValueError(f"unit_system must be {DEFAULT_UNIT_SYSTEM}")

    domain = _object(spec.get("domain"), "domain")
    domain_min = _vector3(domain.get("min_m"), "domain.min_m")
    domain_max = _vector3(domain.get("max_m"), "domain.max_m")
    for axis, low, high in zip("xyz", domain_min, domain_max):
        if high <= low:
            raise ValueError(f"domain {axis}-maximum must exceed its minimum")
    domain["min_m"] = domain_min
    domain["max_m"] = domain_max

    mesh = _object(spec.get("mesh"), "mesh")
    for name in (
        "near_size_m",
        "urban_size_m",
        "far_size_m",
        "near_half_width_m",
        "urban_half_width_m",
        "near_height_m",
    ):
        mesh[name] = _positive(mesh.get(name), f"mesh.{name}")
    mesh["size_m"] = mesh["near_size_m"]
    if not mesh["near_size_m"] <= mesh["urban_size_m"] <= mesh["far_size_m"]:
        raise ValueError("mesh sizes must increase from near to urban to far field")
    if not mesh["near_half_width_m"] < mesh["urban_half_width_m"]:
        raise ValueError("near_half_width_m must be smaller than urban_half_width_m")

    explosive = _object(spec.get("explosive"), "explosive")
    if explosive.get("geometry_type") != "solid_cylinder":
        raise ValueError("explosive.geometry_type must be solid_cylinder")
    if explosive.get("material") != "tnt_jwl_phase15_reference":
        raise ValueError("explosive.material must be tnt_jwl_phase15_reference")
    for name in ("mass_kg", "density_kg_per_m3", "diameter_m"):
        explosive[name] = _positive(explosive.get(name), f"explosive.{name}")
    radius = 0.5 * explosive["diameter_m"]
    expected_length = explosive["mass_kg"] / (
        explosive["density_kg_per_m3"] * math.pi * radius * radius
    )
    supplied_length = _positive(explosive.get("length_m"), "explosive.length_m")
    if not math.isclose(supplied_length, expected_length, rel_tol=1.0e-6):
        raise ValueError(
            "explosive.length_m must match mass, density, and diameter for the solid TNT cylinder"
        )
    explosive["length_m"] = expected_length
    explosive["base_center_m"] = _vector3(
        explosive.get("base_center_m"), "explosive.base_center_m"
    )
    diameter_cells = explosive["diameter_m"] / mesh["near_size_m"]
    if diameter_cells < 3.0 - 1.0e-12:
        raise ValueError("solid TNT cylinder diameter must span at least 3 near-field ALE cells")
    x0, y0, z0 = explosive["base_center_m"]
    center = [x0, y0, z0 + 0.5 * expected_length]
    near_half_width = float(mesh["near_half_width_m"])
    if (
        center[0] - near_half_width < domain_min[0]
        or center[0] + near_half_width > domain_max[0]
        or center[1] - near_half_width < domain_min[1]
        or center[1] + near_half_width > domain_max[1]
    ):
        raise ValueError(
            "blast_refinement_window_outside_domain: "
            "the source-centered ALE near-field window must fit inside the fixed domain"
        )
    if z0 < domain_min[2] or z0 + expected_length >= domain_max[2]:
        raise ValueError("solid TNT cylinder must lie inside the ALE domain")
    if not (
        domain_min[0] + radius < x0 < domain_max[0] - radius
        and domain_min[1] + radius < y0 < domain_max[1] - radius
    ):
        raise ValueError("solid TNT cylinder must lie inside the ALE domain")

    layout = _object(spec.get("layout"), "layout")
    layout["road_width_m"] = _positive(layout.get("road_width_m"), "layout.road_width_m")
    layout["road_thickness_m"] = _positive(
        layout.get("road_thickness_m"),
        "layout.road_thickness_m",
    )
    layout["residential_setback_m"] = _positive(
        layout.get("residential_setback_m"),
        "layout.residential_setback_m",
    )
    for key in (
        "supermarket",
        "residential_community",
        "subway_entrance",
        "parking_lot",
        "parked_vehicles",
        "traffic_lights",
    ):
        _object(layout.get(key), f"layout.{key}")
    library = layout.get("library_components")
    if library is None:
        library = {
            "shell_box": {
                "length_m": 2.0,
                "width_m": 1.2,
                "height_m": 1.4,
                "thickness_m": 0.01,
                "instances": [],
            },
        }
        layout["library_components"] = library
    library = _object(library, "layout.library_components")
    unknown_library_templates = sorted(set(library) - {"shell_box"})
    if unknown_library_templates:
        raise ValueError(
            "layout.library_components contains unsupported templates: "
            + ", ".join(unknown_library_templates)
        )
    shell_box = _object(
        library.get("shell_box"),
        "layout.library_components.shell_box",
    )
    for field in ("length_m", "width_m", "height_m", "thickness_m"):
        shell_box[field] = _positive(
            shell_box.get(field),
            f"layout.library_components.shell_box.{field}",
        )
    if shell_box["thickness_m"] >= 0.5 * min(
        shell_box["length_m"],
        shell_box["width_m"],
        shell_box["height_m"],
    ):
        raise ValueError(
            "layout.library_components.shell_box.thickness_m is too large"
        )
    shell_box_instances = shell_box.get("instances")
    if not isinstance(shell_box_instances, list) or len(shell_box_instances) > 6:
        raise ValueError(
            "layout.library_components.shell_box.instances must contain 0 to 6 boxes"
        )
    shell_box_ids: set[str] = set()
    for index, instance in enumerate(shell_box_instances):
        row = _object(
            instance,
            f"layout.library_components.shell_box.instances[{index}]",
        )
        component_id = city_instance_id(row, index, "shell_box")
        if component_id in shell_box_ids:
            raise ValueError(f"duplicate shell_box instance_id: {component_id}")
        shell_box_ids.add(component_id)
        row["instance_id"] = component_id
        row["origin_m"] = _vector3(
            row.get("origin_m"),
            f"layout.library_components.shell_box.instances[{index}].origin_m",
        )
        row["rotate_z_deg"] = _finite(
            row.get("rotate_z_deg", 0.0),
            f"layout.library_components.shell_box.instances[{index}].rotate_z_deg",
        )
    parked = layout["parked_vehicles"]
    instances = parked.get("instances")
    if not isinstance(instances, list) or not 1 <= len(instances) <= 12:
        raise ValueError("layout.parked_vehicles.instances must contain 1 to 12 vehicles")
    vehicle_instance_ids: set[str] = set()
    for index, instance in enumerate(instances):
        row = _object(instance, f"layout.parked_vehicles.instances[{index}]")
        component_id = parked_vehicle_instance_id(row, index)
        if component_id in vehicle_instance_ids:
            raise ValueError(
                f"duplicate parked vehicle instance_id: {component_id}"
            )
        vehicle_instance_ids.add(component_id)
        row["instance_id"] = component_id
        row["origin_m"] = _vector3(
            row.get("origin_m"),
            f"layout.parked_vehicles.instances[{index}].origin_m",
        )
        row["rotate_z_deg"] = _finite(
            row.get("rotate_z_deg", 0.0),
            f"layout.parked_vehicles.instances[{index}].rotate_z_deg",
        )
    subway = layout["subway_entrance"]
    if not math.isclose(float(subway.get("platform_height_m", 0.0)), 0.3, abs_tol=1.0e-12):
        raise ValueError("subway entrance platform_height_m must remain 0.3 m")
    if subway.get("enclosure") != "front_open_three_sides_enclosed":
        raise ValueError("subway entrance must keep the reviewed three-side enclosure")
    if subway.get("open_side") != "y_min":
        raise ValueError("subway entrance open side must face y_min toward the road")
    subway_instances = ensure_subway_entrance_instances(subway)
    if not 1 <= len(subway_instances) <= 6:
        raise ValueError(
            "layout.subway_entrance.instances must contain 1 to 6 entrances"
        )
    subway_instance_ids: set[str] = set()
    for index, instance in enumerate(subway_instances):
        row = _object(instance, f"layout.subway_entrance.instances[{index}]")
        component_id = subway_entrance_instance_id(row, index)
        if component_id in subway_instance_ids:
            raise ValueError(
                f"duplicate subway_entrance instance_id: {component_id}"
            )
        subway_instance_ids.add(component_id)
        row["instance_id"] = component_id
        row["origin_m"] = _vector3(
            row.get("origin_m"),
            f"layout.subway_entrance.instances[{index}].origin_m",
        )
        row["rotate_z_deg"] = _finite(
            row.get("rotate_z_deg", 0.0),
            f"layout.subway_entrance.instances[{index}].rotate_z_deg",
        )

    residential = layout["residential_community"]
    residential_extent_x = (
        int(residential["tower_count"]) * float(residential["tower_length_m"])
        + (int(residential["tower_count"]) - 1) * float(residential["tower_spacing_m"])
    )
    residential_origin = _vector3(residential.get("origin_m"), "layout.residential_community.origin_m")
    road_half = 0.5 * layout["road_width_m"]
    nearest_x = residential_origin[0] + residential_extent_x
    nearest_y = residential_origin[1] + float(residential["tower_width_m"])
    actual_setback = min(-road_half - nearest_x, -road_half - nearest_y)
    if actual_setback + 1.0e-9 < layout["residential_setback_m"]:
        raise ValueError("residential building boundary violates the requested road setback")

    ground_response = normalize_ground_response(
        spec.get("ground_response"),
        source_center_m=center,
        domain_bounds_m=(domain_min, domain_max),
        foundation_bounds=_ground_foundation_bounds(spec),
        mesh_size_m=mesh["near_size_m"],
    )
    if ground_response is None:
        if domain_min[2] != 0.0:
            raise ValueError("city air domain must start at ground elevation z=0")
    else:
        derived_lower_bound = -float(
            ground_response["ale_overlap_depth_m"]
        )
        if not (
            math.isclose(domain_min[2], 0.0, abs_tol=1.0e-12)
            or math.isclose(
                domain_min[2],
                derived_lower_bound,
                abs_tol=1.0e-12,
            )
        ):
            raise ValueError(
                "invalid_ground_geometry: domain.min_m[2] must be zero or "
                "the derived ALE overlap lower bound"
            )
        domain_min[2] = derived_lower_bound
        spec["ground_response"] = ground_response

    analysis = _object(spec.get("analysis"), "analysis")
    for name in ("end_time_s", "d3plot_dt_s", "history_dt_s"):
        analysis[name] = _positive(analysis.get(name), f"analysis.{name}")
    if analysis["d3plot_dt_s"] > analysis["end_time_s"]:
        raise ValueError("analysis.d3plot_dt_s must not exceed end_time_s")
    spec["analysis_control"] = {"termination": {"end_time_s": analysis["end_time_s"]}}
    spec["database"] = {"d3plot_dt_s": analysis["d3plot_dt_s"]}
    spec["solver_permission"] = "explicit_user_approval_required"
    spec["validation_status"] = "generated_not_solver_validated"
    return spec


def build_city_street_blast_keyword(raw: JSONDict) -> tuple[str, JSONDict]:
    spec = validate_city_street_blast_spec(raw)
    domain_min = spec["domain"]["min_m"]
    domain_max = spec["domain"]["max_m"]
    mesh = spec["mesh"]
    explosive = spec["explosive"]
    x0, y0, z0 = explosive["base_center_m"]
    z1 = z0 + explosive["length_m"]
    source_center = [x0, y0, 0.5 * (z0 + z1)]
    x_axis, x_near_bounds = _graded_horizontal_axis(
        domain_min[0],
        domain_max[0],
        source_center[0],
        mesh,
    )
    y_axis, y_near_bounds = _graded_horizontal_axis(
        domain_min[1],
        domain_max[1],
        source_center[1],
        mesh,
    )
    z_axis, z_near_bounds = _graded_vertical_axis(
        domain_min[2],
        domain_max[2],
        source_center[2],
        float(explosive["length_m"]),
        mesh,
    )
    nx, ny, nz = len(x_axis) - 1, len(y_axis) - 1, len(z_axis) - 1

    def domain_nid(ix: int, iy: int, iz: int) -> int:
        return iz * (ny + 1) * (nx + 1) + iy * (nx + 1) + ix + 1

    nodes: list[Node] = [
        (domain_nid(ix, iy, iz), x_axis[ix], y_axis[iy], z_axis[iz])
        for iz in range(nz + 1)
        for iy in range(ny + 1)
        for ix in range(nx + 1)
    ]
    solids: list[SolidElement] = []
    for iz in range(nz):
        for iy in range(ny):
            for ix in range(nx):
                solids.append(
                    (
                        len(solids) + 1,
                        AIR_PART_ID,
                        domain_nid(ix, iy, iz),
                        domain_nid(ix + 1, iy, iz),
                        domain_nid(ix + 1, iy + 1, iz),
                        domain_nid(ix, iy + 1, iz),
                        domain_nid(ix, iy, iz + 1),
                        domain_nid(ix + 1, iy, iz + 1),
                        domain_nid(ix + 1, iy + 1, iz + 1),
                        domain_nid(ix, iy + 1, iz + 1),
                    )
                )
    ale_solid_element_count = len(solids)

    crater_mode = "ground_response" in spec
    foundation_bounds = _ground_foundation_bounds(spec) if crater_mode else []
    ground_model = None
    if crater_mode:
        ground_model = build_ground_crater_model(
            spec["ground_response"],
            x_axis=x_axis,
            y_axis=y_axis,
            source_center_m=source_center,
            road_width_m=float(spec["layout"]["road_width_m"]),
            foundation_bounds=foundation_bounds,
            node_id_start=len(nodes) + 1,
            solid_element_id_start=len(solids) + 1,
        )
        nodes.extend(ground_model.nodes)
        solids.extend(ground_model.solids)

    component_specs = _urban_component_specs(spec)
    shells: list[ShellElement] = []
    fsi_segments: list[tuple[int, int, int, int]] = []
    residual_fsi_segments: list[tuple[int, int, int, int]] = []
    fixed_node_ids: list[int] = []
    excluded_fully_constrained_segments = 0
    vehicle_part_ids: list[int] = []
    vehicle_support_part_ids: list[int] = []
    component_metadata: dict[str, JSONDict] = {}
    semantic_objects: list[JSONDict] = []
    response_objects: list[JSONDict] = []
    part_rows: list[JSONDict] = []
    tied_base_node_ids: dict[str, list[int]] = {}
    next_node_id = len(nodes) + 1
    next_shell_id = len(solids) + 1
    next_part_id = 10
    for component in component_specs:
        pid = next_part_id
        next_part_id += 1
        role = str(component.get("role", "urban_structure"))
        if crater_mode and role in {"concrete_road", "ground_foundation"}:
            if ground_model is None or pid not in ground_model.part_element_ids:
                raise ValueError(
                    f"invalid_ground_geometry: ground part {pid} is empty"
                )
            if role == "concrete_road":
                vehicle_support_part_ids.append(pid)
            material_id = int(component["material_id"])
            title = str(component["title"])
            part_rows.append(
                {
                    "part_id": pid,
                    "section_id": pid,
                    "material_id": material_id,
                    "title": title,
                    "element_family": "solid",
                }
            )
            metadata_key = str(component["metadata_key"])
            component_bounds = ground_model.part_bounds_m[pid]
            semantic_objects.append(
                {
                    "object_id": str(component["id"]),
                    "group_id": metadata_key,
                    "template": "solid_ground_region",
                    "role": role,
                    "material_name": str(component["material"]["name"]),
                    "material_id": material_id,
                    "part_ids": [pid],
                    "constraint_mode": "continuum_ground",
                    "supports_ale_fsi": True,
                    "node_count": len(ground_model.part_node_ids[pid]),
                    "fixed_node_count": 0,
                    "fixed_node_ratio": 0.0,
                    "solid_element_count": len(
                        ground_model.part_element_ids[pid]
                    ),
                    "shell_island_count": 0,
                    "floating_shell_island_count": 0,
                    "fsi_segment_count": 0,
                    "fsi_excluded_fully_constrained_segment_count": 0,
                    "bounds_m": component_bounds,
                    "pivot_world_m": [
                        0.5
                        * (
                            float(component_bounds["min"][axis])
                            + float(component_bounds["max"][axis])
                        )
                        for axis in range(3)
                    ],
                    "translate_m": [0.0, 0.0, 0.0],
                    "rotate_deg": [0.0, 0.0, 0.0],
                    "mobility_profile": "fixed",
                    "allowed_dofs": [],
                    "support_object_id": None,
                    "support_clearance_m": 0.0,
                    "editor_modified": False,
                }
            )
            row = component_metadata.setdefault(
                metadata_key,
                {
                    "template": "solid_ground_region",
                    "material_name": str(component["material"]["name"]),
                    "material_id": material_id,
                    "part_ids": [],
                    "node_count": 0,
                    "solid_element_count": 0,
                    "shell_element_count": 0,
                    "detail_count": 0,
                    "constraint_mode": "continuum_ground",
                    "fixed_node_count": 0,
                    "fsi_segment_count": 0,
                    "fsi_excluded_fully_constrained_segment_count": 0,
                },
            )
            row["part_ids"].append(pid)
            row["node_count"] += len(ground_model.part_node_ids[pid])
            row["solid_element_count"] += len(
                ground_model.part_element_ids[pid]
            )
            continue
        local_nodes, local_shells, local_solids, section = build_component_geometry(component, pid)
        if local_solids:
            raise ValueError("city urban components must use shell geometry for explicit FSI surfaces")
        transformed = apply_transform(local_nodes, component)
        fixed_local_node_ids = _component_fixed_local_node_ids(
            component,
            transformed,
        )
        node_map: dict[int, int] = {}
        component_fixed_node_ids: set[int] = set()
        component_support_node_ids: set[int] = set()
        tie_to_ground = (
            crater_mode
            and component.get("constraint_mode") == "base_fixed"
        )
        component_node_ids: list[int] = []
        for old_nid, x, y, z in transformed:
            node_map[old_nid] = next_node_id
            nodes.append((next_node_id, x, y, z))
            component_node_ids.append(next_node_id)
            if old_nid in fixed_local_node_ids:
                component_support_node_ids.add(next_node_id)
                if not tie_to_ground:
                    fixed_node_ids.append(next_node_id)
                    component_fixed_node_ids.add(next_node_id)
            next_node_id += 1
        if tie_to_ground:
            tied_base_node_ids[str(component["id"])] = sorted(
                component_support_node_ids
            )
        component_fsi_segment_count = 0
        component_excluded_fsi_segment_count = 0
        component_fsi_segments: list[tuple[int, int, int, int]] = []
        component_shell_ids: list[int] = []
        component_shell_nodes: list[tuple[int, int, int, int]] = []
        for element in local_shells:
            mapped = tuple(node_map[nid] for nid in element[2:6])
            shells.append((next_shell_id, pid, *mapped))
            component_shell_ids.append(next_shell_id)
            component_shell_nodes.append(mapped)
            if component.get("include_in_fsi", True):
                if set(mapped).issubset(component_support_node_ids):
                    component_excluded_fsi_segment_count += 1
                    excluded_fully_constrained_segments += 1
                else:
                    fsi_segments.append(mapped)
                    component_fsi_segments.append(mapped)
                    component_fsi_segment_count += 1
            next_shell_id += 1
        if role == "movable_vehicle":
            vehicle_part_ids.append(pid)
        if role in {"concrete_road", "parking_support"}:
            vehicle_support_part_ids.append(pid)
        material_id = int(component["material_id"])
        title = str(component["title"])
        section_id = pid
        part_rows.append(
            {
                "part_id": pid,
                "section_id": section_id,
                "material_id": material_id,
                "title": title,
                "thickness_m": float(section["thickness_m"]),
                "element_family": "shell",
            }
        )
        metadata_key = str(component["metadata_key"])
        coordinates = [
            [float(x), float(y), float(z)]
            for _node_id, x, y, z in transformed
        ]
        component_bounds = {
            "min": [
                min(point[axis] for point in coordinates)
                for axis in range(3)
            ],
            "max": [
                max(point[axis] for point in coordinates)
                for axis in range(3)
            ],
        }
        object_id = str(component["id"])
        shell_island_count, floating_shell_island_count = (
            _shell_island_support_counts(
                component_shell_nodes,
                component_support_node_ids,
            )
        )
        if _is_required_response_object(component):
            movable_vehicle = role == "movable_vehicle"
            unsupported_islands = (
                shell_island_count != 1
                if movable_vehicle
                else floating_shell_island_count > 0
            )
            if unsupported_islands:
                raise ValueError(
                    "required city response object contains unsupported shell "
                    f"islands: {object_id}"
                )
            if not component_fsi_segments:
                raise ValueError(
                    f"required city response object has no FSI segments: {object_id}"
                )
            response_index = len(response_objects) + 1
            history_shell_ids = _sample_response_ids(
                [
                    shell_id
                    for shell_id, shell_nodes in zip(
                        component_shell_ids,
                        component_shell_nodes,
                        strict=True,
                    )
                    if not set(shell_nodes).issubset(
                        component_support_node_ids
                    )
                ]
            )
            history_node_ids = _sample_response_ids(
                [
                    node_id
                    for node_id in component_node_ids
                    if node_id not in component_support_node_ids
                ]
            )
            response_objects.append(
                {
                    "object_id": object_id,
                    "part_id": pid,
                    "fsi_segment_set_id": (
                        RESPONSE_FSI_SEGMENT_SET_ID_BASE + response_index
                    ),
                    "fsi_surface_id": (
                        RESPONSE_FSI_SURFACE_ID_BASE + response_index
                    ),
                    "fsi_segment_count": len(component_fsi_segments),
                    "fsi_segments": component_fsi_segments,
                    "shell_history_set_id": (
                        RESPONSE_SHELL_HISTORY_SET_ID_BASE + response_index
                    ),
                    "shell_element_ids": history_shell_ids,
                    "all_shell_element_count": len(component_shell_ids),
                    "node_history_set_id": (
                        RESPONSE_NODE_HISTORY_SET_ID_BASE + response_index
                    ),
                    "node_ids": history_node_ids,
                    "all_node_count": len(component_node_ids),
                    "expected_distance_m": _distance_to_bounds(
                        source_center,
                        component_bounds,
                    ),
                }
            )
        else:
            residual_fsi_segments.extend(component_fsi_segments)
        mobility = city_mobility_for(str(component["id"])) or {}
        semantic_objects.append(
            {
                "object_id": str(component["id"]),
                "group_id": metadata_key,
                "template": str(component["template"]),
                "role": role,
                "material_name": str(component["material"]["name"]),
                "material_id": material_id,
                "part_ids": [pid],
                "constraint_mode": (
                    "tied_to_ground"
                    if tie_to_ground
                    else str(component.get("constraint_mode", "fixed"))
                ),
                "supports_ale_fsi": bool(
                    component.get("include_in_fsi", True)
                ),
                "node_count": len(local_nodes),
                "fixed_node_count": len(component_fixed_node_ids),
                "ground_tied_base_node_count": (
                    len(component_support_node_ids) if tie_to_ground else 0
                ),
                "fixed_node_ratio": (
                    len(component_fixed_node_ids) / len(local_nodes)
                    if local_nodes
                    else 0.0
                ),
                "shell_island_count": shell_island_count,
                "floating_shell_island_count": floating_shell_island_count,
                "fsi_segment_count": component_fsi_segment_count,
                "fsi_excluded_fully_constrained_segment_count": (
                    component_excluded_fsi_segment_count
                ),
                "bounds_m": component_bounds,
                "pivot_world_m": _component_design_pivot(
                    component,
                    local_nodes,
                ),
                "translate_m": list(component["transform"].get("translate_m", [0.0, 0.0, 0.0])),
                "rotate_deg": list(component["transform"].get("rotate_deg", [0.0, 0.0, 0.0])),
                "mobility_profile": str(
                    mobility.get(
                        "mobility_profile",
                        "fixed",
                    )
                ),
                "allowed_dofs": list(
                    mobility.get(
                        "allowed_dofs",
                        [],
                    )
                ),
                "support_object_id": mobility.get("support_object_id"),
                "support_clearance_m": float(
                    mobility.get("support_clearance_m", 0.0)
                ),
                "editor_modified": bool(component.get("editor_modified", False)),
            }
        )
        row = component_metadata.setdefault(
            metadata_key,
            {
                "template": component["template"],
                "material_name": str(component["material"]["name"]),
                "material_id": material_id,
                "part_ids": [],
                "node_count": 0,
                "shell_element_count": 0,
                "detail_count": 0,
                "constraint_mode": component.get("constraint_mode", "fixed"),
                "fixed_node_count": 0,
                "fsi_segment_count": 0,
                "fsi_excluded_fully_constrained_segment_count": 0,
            },
        )
        row["part_ids"].append(pid)
        row["node_count"] += len(local_nodes)
        row["fixed_node_count"] += len(component_fixed_node_ids)
        if tie_to_ground:
            row["constraint_mode"] = "tied_to_ground"
            row["ground_tied_base_node_count"] = (
                int(row.get("ground_tied_base_node_count", 0))
                + len(component_support_node_ids)
            )
        row["shell_element_count"] += len(local_shells)
        row["fsi_segment_count"] += component_fsi_segment_count
        row["fsi_excluded_fully_constrained_segment_count"] += (
            component_excluded_fsi_segment_count
        )
        row["detail_count"] += int(section.get("detail_count", 0))
        for key in ("details", "enclosure", "platform_height_m", "tower_count"):
            if key in section:
                row[key] = section[key]

    if ground_model is not None:
        part_rows.extend(
            [
                {
                    "part_id": ERODING_GROUND_PART_ID,
                    "section_id": ERODING_GROUND_SECTION_ID,
                    "material_id": ERODING_GROUND_MATERIAL_ID,
                    "title": "Eroding K&C validation ground",
                    "element_family": "solid",
                },
                {
                    "part_id": SUPPORT_GROUND_PART_ID,
                    "section_id": SUPPORT_GROUND_SECTION_ID,
                    "material_id": SUPPORT_GROUND_MATERIAL_ID,
                    "title": "Non-eroding lower ground support",
                    "element_family": "solid",
                },
            ]
        )

    outer_segments = _nonreflecting_segments(domain_nid, nx, ny, nz)
    ale_ground_node_ids = [
        domain_nid(ix, iy, 0)
        for iy in range(ny + 1)
        for ix in range(nx + 1)
    ]
    radius = 0.5 * explosive["diameter_m"]
    detonation_z = 0.5 * (z0 + z1)
    fixed_node_id_set = set(fixed_node_ids)
    _validate_city_spatial_gates(
        domain_min=domain_min,
        domain_max=domain_max,
        explosive_bounds={
            "min": [x0 - radius, y0 - radius, z0],
            "max": [x0 + radius, y0 + radius, z1],
        },
        semantic_objects=semantic_objects,
    )
    probe_points = [
        (x0, y0, detonation_z),
        (_clamp(x0 + 4.0, domain_min[0], domain_max[0]), y0, 1.0),
        (_clamp(x0 + 8.0, domain_min[0], domain_max[0]), y0, 1.0),
        (-12.0, 12.0, 2.0),
        (12.0, 12.0, 2.0),
        (-18.0, -18.0, 2.0),
        (14.0, -16.0, 1.0),
    ]
    probe_solid_ids = sorted(
        {
            _solid_id_for_point(x_axis, y_axis, z_axis, point)
            for point in probe_points
        }
    )

    lines = [
        "*KEYWORD",
        "*TITLE",
        f"lsprepost-mcp city street blast: {spec['project_name']}",
        f"$ Unit system: {DEFAULT_UNIT_SYSTEM} (m, s, kg, N, Pa)",
        "$ Controlled city scene; LS-DYNA execution requires explicit user approval.",
        "$ TNT is an ALE high-explosive material cylinder, not a CONWEP point load.",
        "*CONTROL_TERMINATION",
        "$#  endtim",
        _field(spec["analysis"]["end_time_s"]),
        "*CONTROL_TIMESTEP",
        "$#  dtinit    tssfac",
        "0.0,0.67",
        "*CONTROL_ALE",
        "$#     dct      nadv      meth      afac      bfac      cfac      dfac      efac",
        "-1,1,2,-1.0,0.0,0.0,0.0,0.0",
        "$#   start       end     aafac     vfact    vlimit       ebc      pref   nsidebc",
        "0.0,1.0e20,1.0,1.0e-6,0,0,101325.0,0",
    ]
    if crater_mode:
        lines.extend(
            [
                "*DEFINE_CURVE_TITLE",
                "City crater R12 K&C curve table and d3plot interval",
                "$#    lcid      sidr       sfa       sfo      offa      offo    dattyp",
                f"{CITY_CRATER_D3PLOT_CURVE_ID},0,1,1,0,0,0",
                "$#               a1                  o1",
                f"0,{_field(spec['analysis']['d3plot_dt_s'])}",
                (
                    f"{_field(spec['analysis']['end_time_s'])},"
                    f"{_field(spec['analysis']['d3plot_dt_s'])}"
                ),
                "*DATABASE_BINARY_D3PLOT",
                "$#      dt      lcdt",
                f"0,{CITY_CRATER_D3PLOT_CURVE_ID}",
            ]
        )
    else:
        lines.extend(
            [
                "*DATABASE_BINARY_D3PLOT",
                _field(spec["analysis"]["d3plot_dt_s"]),
            ]
        )
    lines.extend(
        [
        "*DATABASE_GLSTAT",
        _field(spec["analysis"]["history_dt_s"]),
        "*DATABASE_MATSUM",
        _field(spec["analysis"]["history_dt_s"]),
        "*DATABASE_NODOUT",
        _field(spec["analysis"]["history_dt_s"]),
        "*DATABASE_ELOUT",
        _field(spec["analysis"]["history_dt_s"]),
        ]
    )
    if crater_mode:
        lines.extend(
            [
                "*DATABASE_EXTENT_BINARY",
                "0,3,4,1,1,1,1,1",
                "0,0,0,0,0,0,2,1",
                "1,0,1.0,0,0",
            ]
        )
    lines.extend(
        [
            "*DATABASE_FSI",
            _field(spec["analysis"]["history_dt_s"]),
        ]
    )
    if residual_fsi_segments:
        lines.append(f"1,{FSI_SEGMENT_SET_ID},2")
    if crater_mode:
        lines.extend(
            [
                f"{ERODING_FSI_SURFACE_ID},1209,2",
                f"{PERIPHERAL_FSI_SURFACE_ID},1202,2",
            ]
        )
    lines.extend(
        f"{item['fsi_surface_id']},{item['fsi_segment_set_id']},2"
        for item in response_objects
    )
    lines.extend(
        [
            "*DATABASE_ALE_MAT",
            f"{_field(spec['analysis']['history_dt_s'])},0",
            "*NODE",
            "$#   nid               x               y               z",
        ]
    )
    lines.extend(f"{nid},{_field(x)},{_field(y)},{_field(z)}" for nid, x, y, z in nodes)
    lines.extend(
        [
            "*ELEMENT_SOLID",
            "$#   eid     pid      n1      n2      n3      n4      n5      n6      n7      n8",
        ]
    )
    lines.extend(",".join(str(value) for value in element) for element in solids)
    lines.extend(["*ELEMENT_SHELL", "$#   eid     pid      n1      n2      n3      n4"])
    lines.extend(",".join(str(value) for value in element) for element in shells)
    lines.extend(_part_lines("ALE city air domain", AIR_PART_ID, AIR_SECTION_ID, AIR_MATERIAL_ID, 1))
    lines.extend(_part_lines("Entity TNT cylinder material group", TNT_PART_ID, TNT_SECTION_ID, TNT_MATERIAL_ID, 2))
    lines.extend(["*SECTION_SOLID", "1,11", "*SECTION_SOLID", "2,11"])
    for part in part_rows:
        lines.extend(
            _part_lines(
                part["title"],
                part["part_id"],
                part["section_id"],
                part["material_id"],
                0,
            )
        )
        if part.get("element_family") == "solid":
            lines.extend(
                [
                    "*SECTION_SOLID",
                    f"{part['section_id']},1",
                ]
            )
        else:
            thickness = _field(part["thickness_m"])
            lines.extend(
                [
                    "*SECTION_SHELL",
                    f"{part['section_id']},2,0.833,5,1.0",
                    f"{thickness},{thickness},{thickness},{thickness},0.0",
                ]
            )
    lines.extend(["*ALE_MULTI-MATERIAL_GROUP", "1,1", "2,1"])
    ground_material_metadata = None
    if crater_mode:
        ground_materials = default_phase15_materials()
        erosion_mode = str(spec["ground_response"]["erosion_mode"])
        ground_materials["erosion"] = {"mode": erosion_mode}
        if erosion_mode == "custom":
            ground_materials["erosion"].update(
                {
                    "maximum_principal_strain": spec["ground_response"][
                        "maximum_principal_strain"
                    ],
                    "confirmed_by_user": True,
                }
            )
        material_lines, ground_material_metadata = (
            render_phase15_material_cards(
                ground_materials,
                material_ids={
                    "air": AIR_MATERIAL_ID,
                    "tnt": TNT_MATERIAL_ID,
                    "concrete": ERODING_GROUND_MATERIAL_ID,
                    "steel_hoop": URBAN_STEEL_MATERIAL_ID,
                },
                eos_ids={"air": 1, "tnt": 2},
            )
        )
        lines.extend(material_lines)
    else:
        lines.extend(
            render_ale_air_cards(
                default_ale_air_definition(),
                material_id=AIR_MATERIAL_ID,
                eos_id=1,
            )
        )
        lines.extend(_tnt_material_lines())
    lines.extend(
        [
            "*MAT_ELASTIC",
            "$#   mid        ro         e        pr",
            "3,2400,3.0e10,0.2",
            "*MAT_ELASTIC",
            "$ non-structural, fixed display guide for the ALE TNT fill geometry",
            "$#   mid        ro         e        pr",
            f"{TNT_GUIDE_MATERIAL_ID},1.0,1.0e6,0.3",
            "*INITIAL_VOLUME_FRACTION_GEOMETRY",
            "$ entity TNT cylinder",
            "$#   fmsid   fmidtyp    bammg    ntrace",
            "1,1,1,0",
            "$# conttyp   fillopt    fammg",
            "4,0,2",
            "$#      x1        y1        z1        x2        y2        z2        r1        r2",
            f"{_field(x0)},{_field(y0)},{_field(z0)},{_field(x0)},{_field(y0)},{_field(z1)},{_field(radius)},{_field(radius)}",
            "*INITIAL_DETONATION",
            "$#     pid        x0        y0        z0        lt",
            f"{AIR_PART_ID},{_field(x0)},{_field(y0)},{_field(detonation_z)},0.0",
            "*SET_PART_LIST_TITLE",
            "ALE air and TNT material parts",
            str(ALE_PART_SET_ID),
            f"{AIR_PART_ID},{TNT_PART_ID}",
            "*SET_PART_LIST_TITLE",
            "Movable parked vehicle parts",
            str(VEHICLE_PART_SET_ID),
            ",".join(str(value) for value in vehicle_part_ids),
            "*SET_PART_LIST_TITLE",
            "Concrete road and parking support parts",
            str(VEHICLE_SUPPORT_PART_SET_ID),
            ",".join(str(value) for value in vehicle_support_part_ids),
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE",
            "$ movable parked vehicles against concrete road and parking surfaces",
            "$#   ssid      msid     sstyp     mstyp    sboxid    mboxid       spr       mpr",
            f"{VEHICLE_PART_SET_ID},{VEHICLE_SUPPORT_PART_SET_ID},2,2,0,0,0,0",
            "$#     fs        fd        dc        vc       vdc    penchk        bt        dt",
            "0.35,0.25,0.0,0.0,0.0,0,0.0,0.0",
            "$#    sfs       sfm       sst       mst      sfst      sfmt       fsf       vsf",
            "1.0,1.0,0.0,0.0,1.0,1.0,1.0,1.0",
            "*SET_SOLID_LIST_TITLE",
            "City air pressure path probes",
            str(ALE_PROBE_SOLID_SET_ID),
            ",".join(str(value) for value in probe_solid_ids),
        ]
    )
    if not crater_mode:
        lines.extend(
            [
                "*MAT_PLASTIC_KINEMATIC",
                "$#   mid        ro         e        pr      sigy      etan      beta",
                "4,7850,2.1e11,0.3,2.35e8,1.0e9,0.0",
                "$#    src       srp        fs        vp",
                "0,0,1,0",
            ]
        )
    if crater_mode:
        lines.extend(
            [
                "*MAT_ELASTIC",
                "$ non-eroding lower ground support",
                "$#   mid        ro         e        pr",
                f"{SUPPORT_GROUND_MATERIAL_ID},2400,3.0e10,0.2",
            ]
        )
    if residual_fsi_segments:
        lines.extend(
            [
                "*SET_SEGMENT_TITLE",
                "Urban exposed surfaces for ALE FSI",
                f"{FSI_SEGMENT_SET_ID},0,0,0,0",
            ]
        )
        lines.extend(
            ",".join(str(value) for value in segment)
            for segment in residual_fsi_segments
        )
        lines.extend(
            [
            "*CONSTRAINED_LAGRANGE_IN_SOLID",
            "$#   slave    master     sstyp     mstyp     nquad     ctype     direc     mcoup",
            f"{FSI_SEGMENT_SET_ID},{ALE_PART_SET_ID},2,0,4,4,2,0",
            "$#   start       end      pfac      fric    frcmin      norm   normtyp      damp",
            "0.0,0.0,0.1,0.0,0.3,0,0,0.1",
            "$#       k      hmin      hmax     ileak     pleak   lcidpor     nvent    iblock",
            "0.0,0.0,0.0,2,0.1,0,0,0",
            ]
        )
    for item in response_objects:
        lines.extend(
            [
                "*SET_SEGMENT_TITLE",
                f"City response FSI segments: {item['object_id']}",
                f"{item['fsi_segment_set_id']},0,0,0,0",
            ]
        )
        lines.extend(
            ",".join(str(value) for value in segment)
            for segment in item["fsi_segments"]
        )
        lines.extend(
            [
                "*CONSTRAINED_LAGRANGE_IN_SOLID",
                f"$ city FSI interface: {item['object_id']}",
                "$#   slave    master     sstyp     mstyp     nquad     ctype     direc     mcoup",
                f"{item['fsi_segment_set_id']},{ALE_PART_SET_ID},2,0,4,4,2,0",
                "$#   start       end      pfac      fric    frcmin      norm   normtyp      damp",
                "0.0,0.0,0.1,0.0,0.3,0,0,0.1",
                "$#       k      hmin      hmax     ileak     pleak   lcidpor     nvent    iblock",
                "0.0,0.0,0.0,2,0.1,0,0,0",
            ]
        )
    if ground_model is not None:
        lines.extend(
            render_ground_crater_cards(
                ground_model,
                ale_part_set_id=ALE_PART_SET_ID,
            )
        )
        lines.extend(
            render_foundation_tie_cards(
                ground_model,
                tied_base_node_ids,
            )
        )
    lines.extend(
        [
            "*SET_SEGMENT_TITLE",
            "City air outer non-reflecting sides and top",
            f"{OUTER_SEGMENT_SET_ID},0,0,0,0",
        ]
    )
    lines.extend(",".join(str(value) for value in segment) for segment in outer_segments)
    lines.extend(
        [
            "*BOUNDARY_NON_REFLECTING",
            f"{OUTER_SEGMENT_SET_ID},0.0,0.0",
            "*SET_NODE_LIST_TITLE",
            "Fixed urban structure nodes",
            str(FIXED_URBAN_NODE_SET_ID),
        ]
    )
    lines.extend(_chunked_ids(sorted(set(fixed_node_ids))))
    lines.extend(
        [
            "*BOUNDARY_SPC_SET",
            f"{FIXED_URBAN_NODE_SET_ID},0,1,1,1,1,1,1",
        ]
    )
    if not crater_mode:
        lines.extend(
            [
                "*SET_NODE_LIST_TITLE",
                "ALE ground reflection nodes",
                str(ALE_GROUND_NODE_SET_ID),
            ]
        )
        lines.extend(_chunked_ids(ale_ground_node_ids))
    for item in response_objects:
        lines.extend(
            [
                "*SET_SHELL_LIST_TITLE",
                f"City response shell history: {item['object_id']}",
                str(item["shell_history_set_id"]),
            ]
        )
        lines.extend(_chunked_ids(item["shell_element_ids"]))
        lines.extend(
            [
                "*SET_NODE_LIST_TITLE",
                f"City response node history: {item['object_id']}",
                str(item["node_history_set_id"]),
            ]
        )
        lines.extend(_chunked_ids(item["node_ids"]))
        lines.extend(
            [
                "*DATABASE_HISTORY_SHELL_SET",
                str(item["shell_history_set_id"]),
                "*DATABASE_HISTORY_NODE_SET",
                str(item["node_history_set_id"]),
            ]
        )
    if not crater_mode:
        lines.extend(
            [
                "*BOUNDARY_SPC_SET",
                f"{ALE_GROUND_NODE_SET_ID},0,0,0,1,0,0,0",
            ]
        )
    lines.append("*END")

    x_local_cell_size = _maximum_overlapping_cell_size(
        x_axis,
        x0 - radius,
        x0 + radius,
    )
    y_local_cell_size = _maximum_overlapping_cell_size(
        y_axis,
        y0 - radius,
        y0 + radius,
    )
    z_local_cell_size = _maximum_overlapping_cell_size(z_axis, z0, z1)
    diameter_cells_actual = min(
        explosive["diameter_m"] / x_local_cell_size,
        explosive["diameter_m"] / y_local_cell_size,
    )
    length_cells_actual = explosive["length_m"] / z_local_cell_size
    if diameter_cells_actual < 3.0 - 1.0e-12:
        raise ValueError(
            "solid TNT cylinder diameter must span at least 3 actual ALE cells"
        )
    if length_cells_actual < 3.0 - 1.0e-12:
        raise ValueError(
            "solid TNT cylinder length must span at least 3 actual ALE cells"
        )
    mesh_fingerprint = _mesh_fingerprint(x_axis, y_axis, z_axis)

    metadata: JSONDict = {
        "unit_system": spec["unit_system"],
        "model_type": "city_street_blast_scene",
        "scene_id": spec["scene_id"],
        "validation_status": "generated_not_solver_validated",
        "solver_permission": "explicit_user_approval_required",
        "validation_profile": "mm_ale_urban_blast_v1",
        "validation_capabilities": [
            "mm_ale",
            "mm_ale_3d",
            "high_explosive_jwl",
            "lagrangian_shell_structure",
            "ale_fsi",
            "fsi_segment_interface",
            "ale_nonreflecting_3d",
            "ale_pressure_outputs_r12_safe",
            "steel_plasticity",
            "movable_surface_contact",
        ]
        + (
            ["city_ground_crater_v1", "kc_concrete", "element_erosion"]
            if crater_mode
            else []
        ),
        "node_count": len(nodes),
        "element_count": len(solids) + len(shells),
        "solid_element_count": len(solids),
        "shell_element_count": len(shells),
        "part_count": 2 + len(part_rows),
        "material_count": 7 if crater_mode else 5,
        "section_count": 2 + len(part_rows),
        "constraint_count": (
            7 + len(response_objects) + len(tied_base_node_ids)
            if crater_mode
            else 2 + len(response_objects)
        ),
        "generated_constraint_anchor_count": (
            4 + len(response_objects)
            if crater_mode
            else 2 + len(response_objects)
        ),
        "node_set_count": 2 + len(response_objects),
        "part_set_count": 3,
        "segment_set_count": 2 + len(response_objects),
        "load_count": 0,
        "initial_condition_count": 2,
        "curve_count": 0,
        "control_count": 3,
        "database_count": (
            11 + 2 * len(response_objects)
            if crater_mode
            else 8 + 2 * len(response_objects)
        ),
        "contact_count": 1 + len(tied_base_node_ids),
        "controlled_contact_cards": [
            "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE"
        ]
        + (["*CONTACT_TIED_NODES_TO_SURFACE"] if crater_mode else []),
        "ale_domain": {
            "part_id": AIR_PART_ID,
            "bounds_m": {"min": domain_min, "max": domain_max},
            "cells": [nx, ny, nz],
            "solid_element_count": ale_solid_element_count,
            "refinement_center_m": list(source_center),
            "near_field_bounds_m": {
                "min": [x_near_bounds[0], y_near_bounds[0], z_near_bounds[0]],
                "max": [x_near_bounds[1], y_near_bounds[1], z_near_bounds[1]],
            },
            "local_cell_size_m": {
                "x": x_local_cell_size,
                "y": y_local_cell_size,
                "z": z_local_cell_size,
            },
            "mesh_fingerprint": mesh_fingerprint,
            "remesh_reason": "blast_source_regenerated",
            "minimum_cell_size_m": min(
                min(_axis_deltas(x_axis)),
                min(_axis_deltas(y_axis)),
                min(_axis_deltas(z_axis)),
            ),
        },
        "explosive": {
            "part_id": TNT_PART_ID,
            "geometry_type": "solid_cylinder",
            "material": explosive["material"],
            "mass_kg": explosive["mass_kg"],
            "density_kg_per_m3": explosive["density_kg_per_m3"],
            "diameter_m": explosive["diameter_m"],
            "length_m": explosive["length_m"],
            "base_center_m": [x0, y0, z0],
            "center_m": list(source_center),
            "diameter_cells": round(explosive["diameter_m"] / mesh["near_size_m"], 12),
            "diameter_cells_actual": round(diameter_cells_actual, 12),
            "length_cells_actual": round(length_cells_actual, 12),
            "initialization": "*INITIAL_VOLUME_FRACTION_GEOMETRY CONTTYP=4",
            "detonation": "*INITIAL_DETONATION",
            "visible_geometry": {
                "role": "non_structural_visual_guide",
                "description": "fixed shell outline only; TNT mass and energy remain defined exclusively by the ALE volume fraction",
            },
        },
        "fsi": {
            "segment_set_id": (
                FSI_SEGMENT_SET_ID if residual_fsi_segments else None
            ),
            "residual_slave_segment_count": len(residual_fsi_segments),
            "slave_segment_count": len(fsi_segments),
            "master_part_set_id": ALE_PART_SET_ID,
            "ctype": 4,
            "fully_constrained_slave_segment_count": sum(
                1
                for segment in fsi_segments
                if set(segment).issubset(fixed_node_id_set)
            ),
            "excluded_fully_constrained_segment_count": (
                excluded_fully_constrained_segments
            ),
        },
        "response_objects": [
            {
                key: value
                for key, value in item.items()
                if key != "fsi_segments"
            }
            for item in response_objects
        ],
        "nonreflecting_boundary": {
            "segment_set_id": OUTER_SEGMENT_SET_ID,
            "segment_count": len(outer_segments),
            "faces": ["x_min", "x_max", "y_min", "y_max", "z_max"],
        },
        "city_semantic_schema_version": "phase16a.city_semantics.v1",
        "semantic_objects": semantic_objects,
        "urban_components": component_metadata,
        "vehicle_contact": {
            "slave_part_set_id": VEHICLE_PART_SET_ID,
            "master_part_set_id": VEHICLE_SUPPORT_PART_SET_ID,
            "vehicle_part_ids": vehicle_part_ids,
            "support_part_ids": vehicle_support_part_ids,
            "fixed_vehicle_nodes": 0,
        },
        "resolved_spec": deepcopy(spec),
    }
    if ground_model is not None:
        metadata["ground_response"] = {
            **deepcopy(ground_model.metadata),
            "material": deepcopy(ground_material_metadata),
            "foundation_tied_object_ids": sorted(tied_base_node_ids),
            "ground_tied_base_node_count": sum(
                len(node_ids) for node_ids in tied_base_node_ids.values()
            ),
        }
    metadata["layout_fingerprint"] = city_layout_fingerprint(spec, metadata)
    metadata["editor_state_fingerprint"] = city_editor_state_fingerprint(
        spec,
        metadata,
    )
    return "\n".join(lines) + "\n", metadata


def _is_required_response_object(component: JSONDict) -> bool:
    template = str(component.get("template", ""))
    return (
        component_definition(template).city_response_policy
        == "required_individual"
    )


def _distance_to_bounds(
    point: list[float],
    bounds: JSONDict,
) -> float:
    squared = 0.0
    for coordinate, lower, upper in zip(
        point,
        bounds["min"],
        bounds["max"],
        strict=True,
    ):
        delta = max(float(lower) - coordinate, 0.0, coordinate - float(upper))
        squared += delta * delta
    return math.sqrt(squared)


def _shell_island_support_counts(
    shells: list[tuple[int, int, int, int]],
    fixed_node_ids: set[int],
) -> tuple[int, int]:
    if not shells:
        return 0, 0
    node_to_shells: dict[int, set[int]] = {}
    for shell_index, shell in enumerate(shells):
        for node_id in shell:
            node_to_shells.setdefault(node_id, set()).add(shell_index)
    adjacency = [set() for _shell in shells]
    for shell_ids in node_to_shells.values():
        for shell_id in shell_ids:
            adjacency[shell_id].update(shell_ids - {shell_id})
    remaining = set(range(len(shells)))
    island_count = 0
    floating_count = 0
    while remaining:
        island_count += 1
        pending = [remaining.pop()]
        island_nodes: set[int] = set()
        while pending:
            shell_id = pending.pop()
            island_nodes.update(shells[shell_id])
            neighbors = adjacency[shell_id] & remaining
            remaining.difference_update(neighbors)
            pending.extend(neighbors)
        if not island_nodes.intersection(fixed_node_ids):
            floating_count += 1
    return island_count, floating_count


def _sample_response_ids(
    values: list[int],
    maximum_count: int = 24,
) -> list[int]:
    if not values:
        raise ValueError("response history source ids must not be empty")
    if len(values) <= maximum_count:
        return list(values)
    indices = {
        round(index * (len(values) - 1) / (maximum_count - 1))
        for index in range(maximum_count)
    }
    return [values[index] for index in sorted(indices)]


def _component_design_pivot(
    component: JSONDict,
    local_nodes: list[Node],
) -> list[float]:
    local_center = (
        1,
        *[
            0.5
            * (
                min(float(node[axis]) for node in local_nodes)
                + max(float(node[axis]) for node in local_nodes)
            )
            for axis in (1, 2, 3)
        ],
    )
    _node_id, x, y, z = apply_transform([local_center], component)[0]
    return [float(x), float(y), float(z)]


def _ground_foundation_bounds(spec: JSONDict) -> list[JSONDict]:
    bounds: list[JSONDict] = []
    for component in _urban_component_specs(spec):
        if component.get("constraint_mode") != "base_fixed":
            continue
        local_nodes, _shells, _solids, _section = (
            build_component_geometry(component, 1)
        )
        transformed = apply_transform(local_nodes, component)
        base_node_ids = _component_fixed_local_node_ids(
            component,
            transformed,
        )
        footprint_nodes = [
            node for node in transformed if node[0] in base_node_ids
        ]
        bounds.append(
            {
                "object_id": str(component["id"]),
                "min": [
                    min(float(node[axis]) for node in footprint_nodes)
                    for axis in (1, 2, 3)
                ],
                "max": [
                    max(float(node[axis]) for node in footprint_nodes)
                    for axis in (1, 2, 3)
                ],
            }
        )
    return bounds


def _urban_component_specs(spec: JSONDict) -> list[JSONDict]:
    layout = spec["layout"]
    domain = spec["domain"]
    road_width = float(layout["road_width_m"])
    road_half = 0.5 * road_width
    road_thickness = float(layout["road_thickness_m"])
    xmin, ymin, _zmin = domain["min_m"]
    xmax, ymax, _zmax = domain["max_m"]
    road_pieces = [
        ("west", [xmin, -road_half, 0.0], -road_half - xmin, road_width),
        ("east", [road_half, -road_half, 0.0], xmax - road_half, road_width),
        ("south", [-road_half, ymin, 0.0], road_width, -road_half - ymin),
        ("north", [-road_half, road_half, 0.0], road_width, ymax - road_half),
        ("intersection", [-road_half, -road_half, 0.0], road_width, road_width),
    ]
    components: list[JSONDict] = []
    for name, origin, length, width in road_pieces:
        components.append(
            _component(
                f"concrete_road_{name}",
                f"Concrete road {name}",
                "shell_plate",
                {
                    "length_m": length,
                    "width_m": width,
                    "thickness_m": road_thickness,
                },
                1.0,
                origin,
                URBAN_CONCRETE_MATERIAL_ID,
                "concrete_roads",
                include_in_fsi=False,
                role="concrete_road",
            )
        )
    ground_pieces = [
        ("northwest", [xmin, road_half, 0.0], -road_half - xmin, ymax - road_half),
        ("northeast", [road_half, road_half, 0.0], xmax - road_half, ymax - road_half),
        ("southwest", [xmin, ymin, 0.0], -road_half - xmin, -road_half - ymin),
        ("southeast", [road_half, ymin, 0.0], xmax - road_half, -road_half - ymin),
    ]
    for name, origin, ground_length, ground_width in ground_pieces:
        components.append(
            _component(
                f"ground_foundation_{name}",
                f"Urban ground foundation {name}",
                "shell_plate",
                {
                    "length_m": ground_length,
                    "width_m": ground_width,
                    "thickness_m": road_thickness,
                },
                1.5,
                origin,
                URBAN_CONCRETE_MATERIAL_ID,
                "ground_foundation",
                include_in_fsi=False,
                role="ground_foundation",
            )
        )
    components.extend(
        [
        _component_from_layout(
            "commercial_supermarket",
            "Commercial supermarket",
            "commercial_supermarket",
            layout["supermarket"],
            2.0,
            URBAN_CONCRETE_MATERIAL_ID,
            constraint_mode="base_fixed",
        ),
        _component_from_layout(
            "residential_community",
            "Residential community",
            "residential_community",
            layout["residential_community"],
            2.0,
            URBAN_CONCRETE_MATERIAL_ID,
            constraint_mode="base_fixed",
        ),
        ]
    )
    subway = layout["subway_entrance"]
    subway_geometry = {
        key: value
        for key, value in subway.items()
        if key != "instances"
    }
    for index, instance in enumerate(subway["instances"]):
        component_id = subway_entrance_instance_id(instance, index)
        component = _component_from_layout(
            component_id,
            (
                "Subway entrance"
                if component_id == "subway_entrance"
                else f"Subway entrance {component_id.removeprefix('subway_entrance_')}"
            ),
            "subway_entrance",
            {**subway_geometry, **instance},
            0.5,
            URBAN_CONCRETE_MATERIAL_ID,
            metadata_key="subway_entrance",
            constraint_mode="base_fixed",
        )
        components.append(component)
    parking = _component_from_layout(
            "parking_lot",
            "Parking lot",
            "parking_lot",
            layout["parking_lot"],
            1.0,
            URBAN_CONCRETE_MATERIAL_ID,
    )
    parking["role"] = "parking_support"
    parking["include_in_fsi"] = False
    components.append(parking)

    explosive = spec["explosive"]
    radius = 0.5 * float(explosive["diameter_m"])
    guide_thickness = 0.001
    guide_origin = list(explosive["base_center_m"])
    guide_parts = [
        _component(
            "tnt_entity_side_guide",
            "Entity TNT cylinder side guide",
            "shell_tube",
            {
                "radius_m": radius,
                "length_m": float(explosive["length_m"]),
                "thickness_m": guide_thickness,
            },
            min(0.1, radius / 2.0),
            guide_origin,
            TNT_GUIDE_MATERIAL_ID,
            "tnt_entity_guide",
            include_in_fsi=False,
            role="non_structural_visual_guide",
            material_name="visualization_reference",
        ),
        _component(
            "tnt_entity_bottom_guide",
            "Entity TNT cylinder bottom guide",
            "circular_plate",
            {"radius_m": radius, "thickness_m": guide_thickness},
            min(0.1, radius / 2.0),
            guide_origin,
            TNT_GUIDE_MATERIAL_ID,
            "tnt_entity_guide",
            include_in_fsi=False,
            role="non_structural_visual_guide",
            material_name="visualization_reference",
        ),
        _component(
            "tnt_entity_top_guide",
            "Entity TNT cylinder top guide",
            "circular_plate",
            {"radius_m": radius, "thickness_m": guide_thickness},
            min(0.1, radius / 2.0),
            [
                guide_origin[0],
                guide_origin[1],
                guide_origin[2] + float(explosive["length_m"]),
            ],
            TNT_GUIDE_MATERIAL_ID,
            "tnt_entity_guide",
            include_in_fsi=False,
            role="non_structural_visual_guide",
            material_name="visualization_reference",
        ),
    ]
    components.extend(guide_parts)

    vehicles = layout["parked_vehicles"]
    vehicle_geometry = {
        key: value
        for key, value in vehicles.items()
        if key != "instances"
    }
    for index, instance in enumerate(vehicles["instances"]):
        component_id = parked_vehicle_instance_id(instance, index)
        component = _component(
            component_id,
            f"Movable parked vehicle {component_id.removeprefix('parked_vehicle_')}",
            "parked_vehicle",
            vehicle_geometry,
            0.35,
            instance["origin_m"],
            URBAN_STEEL_MATERIAL_ID,
            "parked_vehicles",
            constraint_mode="free",
            role="movable_vehicle",
            material_name="mild_steel",
        )
        component["transform"]["rotate_deg"] = [
            0.0,
            0.0,
            float(instance["rotate_z_deg"]),
        ]
        component["editor_modified"] = bool(instance.get("editor_modified", False))
        components.append(component)

    shell_box = layout["library_components"]["shell_box"]
    shell_box_geometry = {
        key: value
        for key, value in shell_box.items()
        if key != "instances"
    }
    for index, instance in enumerate(shell_box["instances"]):
        component_id = city_instance_id(instance, index, "shell_box")
        component = _component(
            component_id,
            f"Steel protective box {component_id.removeprefix('shell_box_')}",
            "shell_box",
            shell_box_geometry,
            0.25,
            instance["origin_m"],
            URBAN_STEEL_MATERIAL_ID,
            "protection_boxes",
            constraint_mode="base_fixed",
            role="protective_equipment",
            material_name="mild_steel",
        )
        component["transform"]["rotate_deg"] = [
            0.0,
            0.0,
            float(instance["rotate_z_deg"]),
        ]
        component["editor_modified"] = bool(
            instance.get("editor_modified", False)
        )
        components.append(component)

    traffic = layout["traffic_lights"]
    traffic_geometry = {
        key: value
        for key, value in traffic.items()
        if key not in {"instances"}
    }
    for index, instance in enumerate(traffic["instances"], start=1):
        component = _component(
            f"traffic_light_{index}",
            f"Traffic lights {index}",
            "traffic_light",
            traffic_geometry,
            0.1,
            instance["origin_m"],
            URBAN_STEEL_MATERIAL_ID,
            "traffic_lights",
            constraint_mode="base_fixed",
            material_name="mild_steel",
        )
        component["transform"]["rotate_deg"] = [0.0, 0.0, float(instance["rotate_z_deg"])]
        components.append(component)
    for component in components:
        if _is_required_response_object(component):
            component["structural_response_mode"] = (
                "supported_shell_details"
            )
    return components


def _component_from_layout(
    component_id: str,
    title: str,
    template: str,
    raw: JSONDict,
    mesh_size: float,
    material_id: int,
    *,
    metadata_key: str | None = None,
    constraint_mode: str = "fixed",
) -> JSONDict:
    geometry = {
        key: value
        for key, value in raw.items()
        if key
        not in {
            "origin_m",
            "enclosure",
            "open_side",
            "rotate_z_deg",
            "editor_modified",
        }
    }
    component = _component(
        component_id,
        title,
        template,
        geometry,
        mesh_size,
        raw["origin_m"],
        material_id,
        metadata_key or component_id,
        constraint_mode=constraint_mode,
    )
    component["transform"]["rotate_deg"] = [
        0.0,
        0.0,
        float(raw.get("rotate_z_deg", 0.0)),
    ]
    component["editor_modified"] = bool(raw.get("editor_modified", False))
    return component


def _component(
    component_id: str,
    title: str,
    template: str,
    geometry: JSONDict,
    mesh_size: float,
    origin: list[float],
    material_id: int,
    metadata_key: str,
    *,
    constraint_mode: str = "fixed",
    include_in_fsi: bool = True,
    role: str = "urban_structure",
    material_name: str = "concrete_linear_elastic_demo",
) -> JSONDict:
    return {
        "id": component_id,
        "title": title,
        "metadata_key": metadata_key,
        "template": template,
        "geometry": deepcopy(geometry),
        "mesh": {"size_m": mesh_size},
        "material": {"name": material_name},
        "material_id": material_id,
        "transform": {"translate_m": list(origin)},
        "constraint_mode": constraint_mode,
        "include_in_fsi": include_in_fsi,
        "role": role,
    }


def _component_fixed_local_node_ids(
    component: JSONDict,
    transformed_nodes: list[Node],
) -> set[int]:
    mode = str(component.get("constraint_mode", "fixed"))
    if mode == "free":
        return set()
    if mode == "fixed":
        return {node_id for node_id, _x, _y, _z in transformed_nodes}
    if mode != "base_fixed":
        raise ValueError(f"unsupported city constraint_mode: {mode}")
    if not transformed_nodes:
        raise ValueError("base_fixed city component must contain nodes")
    base_z = min(z for _node_id, _x, _y, z in transformed_nodes)
    mesh_size = float(component.get("mesh", {}).get("size_m", 1.0))
    tolerance = max(1.0e-12, abs(mesh_size) * 1.0e-9)
    fixed = {
        node_id
        for node_id, _x, _y, z in transformed_nodes
        if abs(z - base_z) <= tolerance
    }
    if not fixed or len(fixed) == len(transformed_nodes):
        raise ValueError(
            "base_fixed city component must have both supported and free nodes"
        )
    return fixed


def _graded_horizontal_axis(
    low: float,
    high: float,
    center: float,
    mesh: JSONDict,
) -> tuple[list[float], tuple[float, float]]:
    near = float(mesh["near_half_width_m"])
    urban = float(mesh["urban_half_width_m"])
    near_low = center - near
    near_high = center + near
    if near_low < low or near_high > high:
        raise ValueError(
            "blast_refinement_window_outside_domain: "
            "the source-centered ALE near-field window must fit inside the fixed domain"
        )
    urban_low = max(low, center - urban)
    urban_high = min(high, center + urban)
    axis = _axis_from_segments(
        [
            (low, urban_low, float(mesh["far_size_m"])),
            (urban_low, near_low, float(mesh["urban_size_m"])),
            (near_low, near_high, float(mesh["near_size_m"])),
            (near_high, urban_high, float(mesh["urban_size_m"])),
            (urban_high, high, float(mesh["far_size_m"])),
        ]
    )
    return axis, (near_low, near_high)


def _graded_vertical_axis(
    low: float,
    high: float,
    center: float,
    explosive_length: float,
    mesh: JSONDict,
) -> tuple[list[float], tuple[float, float]]:
    near_height = float(mesh["near_height_m"])
    if near_height > high - low:
        raise ValueError(
            "blast_refinement_window_outside_domain: "
            "the ALE near-field height exceeds the fixed domain"
        )
    near_low = _clamp(center - 0.5 * near_height, low, high - near_height)
    near_high = near_low + near_height
    near_size = min(
        float(mesh["near_size_m"]),
        explosive_length / 3.0,
    )
    axis = _axis_from_segments(
        [
            (low, near_low, float(mesh["urban_size_m"])),
            (near_low, near_high, near_size),
            (near_high, high, float(mesh["urban_size_m"])),
        ]
    )
    return axis, (near_low, near_high)


def _axis_from_segments(segments: list[tuple[float, float, float]]) -> list[float]:
    result: list[float] = []
    for low, high, target in segments:
        if high <= low:
            continue
        count = max(1, math.ceil((high - low) / target))
        step = (high - low) / count
        values = [low + index * step for index in range(count)]
        if not result:
            result.extend(values)
        else:
            result.extend(value for value in values if value > result[-1] + 1.0e-12)
        result.append(high)
    normalized: list[float] = []
    for value in result:
        if not normalized or value > normalized[-1] + 1.0e-12:
            normalized.append(value)
    return normalized


def _axis_deltas(axis: list[float]) -> list[float]:
    return [axis[index + 1] - axis[index] for index in range(len(axis) - 1)]


def _validate_city_spatial_gates(
    *,
    domain_min: list[float],
    domain_max: list[float],
    explosive_bounds: JSONDict,
    semantic_objects: list[JSONDict],
) -> None:
    structural_objects = [
        item
        for item in semantic_objects
        if item.get("role") != "non_structural_visual_guide"
    ]
    for item in structural_objects:
        bounds = item["bounds_m"]
        if item.get("editor_modified") and any(
            bounds["min"][axis] < domain_min[axis] - 1.0e-12
            or bounds["max"][axis] > domain_max[axis] + 1.0e-12
            for axis in range(3)
        ):
            raise ValueError(
                "city_object_outside_ale_domain: "
                f"{item['object_id']} leaves the fixed ALE domain"
            )
        if _bounds_have_volume_overlap(explosive_bounds, bounds):
            raise ValueError(
                "blast_source_intersects_structure: "
                f"TNT volume intersects {item['object_id']}"
            )
        if item.get("mobility_profile") in {"grounded", "surface_dynamic"}:
            _validate_grounded_support(item, structural_objects)

    moved_objects = [
        item for item in structural_objects if item.get("editor_modified")
    ]
    for moved in moved_objects:
        for other in structural_objects:
            if moved is other:
                continue
            if _bounds_have_volume_overlap(
                moved["bounds_m"],
                other["bounds_m"],
            ):
                raise ValueError(
                    "city_object_initial_penetration: "
                    f"{moved['object_id']} intersects {other['object_id']}"
                )


def _validate_grounded_support(
    item: JSONDict,
    semantic_objects: list[JSONDict],
) -> None:
    support_id = item.get("support_object_id")
    if not isinstance(support_id, str) or not support_id:
        raise ValueError(
            "city_object_lost_support: "
            f"{item['object_id']} has no declared support object"
        )
    supports = [
        candidate
        for candidate in semantic_objects
        if candidate is not item
        and _matches_support_object(candidate, support_id)
    ]
    footprint = item["bounds_m"]
    footprint_area = (
        float(footprint["max"][0] - footprint["min"][0])
        * float(footprint["max"][1] - footprint["min"][1])
    )
    if footprint_area <= 1.0e-12:
        raise ValueError(
            "city_object_lost_support: "
            f"{item['object_id']} has an invalid support footprint"
        )

    support_clearance = float(item.get("support_clearance_m", 0.0))
    contact_z = float(footprint["min"][2]) - support_clearance
    rectangles: list[tuple[float, float, float, float]] = []
    for support in supports:
        bounds = support["bounds_m"]
        if abs(float(bounds["max"][2]) - contact_z) > 1.0e-6:
            continue
        xmin = max(float(footprint["min"][0]), float(bounds["min"][0]))
        xmax = min(float(footprint["max"][0]), float(bounds["max"][0]))
        ymin = max(float(footprint["min"][1]), float(bounds["min"][1]))
        ymax = min(float(footprint["max"][1]), float(bounds["max"][1]))
        if xmax - xmin > 1.0e-12 and ymax - ymin > 1.0e-12:
            rectangles.append((xmin, xmax, ymin, ymax))

    support_ratio = _rectangle_union_area(rectangles) / footprint_area
    if support_ratio + 1.0e-12 < MIN_GROUNDED_SUPPORT_RATIO:
        raise ValueError(
            "city_object_lost_support: "
            f"{item['object_id']} support coverage is "
            f"{support_ratio:.3f}, below {MIN_GROUNDED_SUPPORT_RATIO:.2f}"
        )


def _matches_support_object(candidate: JSONDict, support_id: str) -> bool:
    object_id = str(candidate.get("object_id", ""))
    role = str(candidate.get("role", ""))
    if support_id == "ground_foundation":
        return role == support_id or object_id.startswith(f"{support_id}_")
    return object_id == support_id or role == support_id


def _rectangle_union_area(
    rectangles: list[tuple[float, float, float, float]],
) -> float:
    if not rectangles:
        return 0.0
    x_coordinates = sorted(
        {coordinate for xmin, xmax, _ymin, _ymax in rectangles for coordinate in (xmin, xmax)}
    )
    area = 0.0
    for index in range(len(x_coordinates) - 1):
        x0 = x_coordinates[index]
        x1 = x_coordinates[index + 1]
        if x1 - x0 <= 1.0e-12:
            continue
        y_intervals = sorted(
            (ymin, ymax)
            for xmin, xmax, ymin, ymax in rectangles
            if xmin < x1 - 1.0e-12 and xmax > x0 + 1.0e-12
        )
        if not y_intervals:
            continue
        covered_y = 0.0
        merged_min, merged_max = y_intervals[0]
        for ymin, ymax in y_intervals[1:]:
            if ymin <= merged_max + 1.0e-12:
                merged_max = max(merged_max, ymax)
            else:
                covered_y += merged_max - merged_min
                merged_min, merged_max = ymin, ymax
        covered_y += merged_max - merged_min
        area += (x1 - x0) * covered_y
    return area


def _bounds_have_volume_overlap(left: JSONDict, right: JSONDict) -> bool:
    return all(
        min(left["max"][axis], right["max"][axis])
        - max(left["min"][axis], right["min"][axis])
        > 1.0e-9
        for axis in range(3)
    )


def _maximum_overlapping_cell_size(
    axis: list[float],
    low: float,
    high: float,
) -> float:
    widths = [
        axis[index + 1] - axis[index]
        for index in range(len(axis) - 1)
        if axis[index] < high and axis[index + 1] > low
    ]
    if not widths:
        raise ValueError("explosive does not overlap any ALE cells")
    return max(widths)


def _mesh_fingerprint(
    x_axis: list[float],
    y_axis: list[float],
    z_axis: list[float],
) -> str:
    payload = json.dumps(
        {
            "x": [round(float(_field(value)), 12) for value in x_axis],
            "y": [round(float(_field(value)), 12) for value in y_axis],
            "z": [round(float(_field(value)), 12) for value in z_axis],
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _nonreflecting_segments(
    nid: object,
    nx: int,
    ny: int,
    nz: int,
) -> list[tuple[int, int, int, int]]:
    node = nid
    segments: list[tuple[int, int, int, int]] = []
    for iz in range(nz):
        for iy in range(ny):
            segments.append((node(0, iy, iz), node(0, iy + 1, iz), node(0, iy + 1, iz + 1), node(0, iy, iz + 1)))
            segments.append((node(nx, iy, iz), node(nx, iy, iz + 1), node(nx, iy + 1, iz + 1), node(nx, iy + 1, iz)))
    for iz in range(nz):
        for ix in range(nx):
            segments.append((node(ix, 0, iz), node(ix, 0, iz + 1), node(ix + 1, 0, iz + 1), node(ix + 1, 0, iz)))
            segments.append((node(ix, ny, iz), node(ix + 1, ny, iz), node(ix + 1, ny, iz + 1), node(ix, ny, iz + 1)))
    for iy in range(ny):
        for ix in range(nx):
            segments.append((node(ix, iy, nz), node(ix + 1, iy, nz), node(ix + 1, iy + 1, nz), node(ix, iy + 1, nz)))
    return segments


def _solid_id_for_point(
    x_axis: list[float],
    y_axis: list[float],
    z_axis: list[float],
    point: tuple[float, float, float],
) -> int:
    ix = min(max(bisect_right(x_axis, point[0]) - 1, 0), len(x_axis) - 2)
    iy = min(max(bisect_right(y_axis, point[1]) - 1, 0), len(y_axis) - 2)
    iz = min(max(bisect_right(z_axis, point[2]) - 1, 0), len(z_axis) - 2)
    nx = len(x_axis) - 1
    ny = len(y_axis) - 1
    return iz * nx * ny + iy * nx + ix + 1


def _part_lines(title: str, pid: int, secid: int, mid: int, eosid: int) -> list[str]:
    return [
        "*PART",
        title,
        "$#     pid     secid       mid     eosid      hgid      grav    adpopt      tmid",
        f"{pid},{secid},{mid},{eosid},0,0,0,0",
    ]


def _tnt_material_lines() -> list[str]:
    tnt = default_phase15_materials()["tnt"]
    jwl = tnt["jwl"]
    return [
        "*MAT_HIGH_EXPLOSIVE_BURN",
        "$#   mid        ro         d       pcj      beta",
        (
            f"{TNT_MATERIAL_ID},{_field(tnt['density_kg_per_m3'])},"
            f"{_field(tnt['detonation_velocity_m_per_s'])},"
            f"{_field(tnt['chapman_jouget_pressure_pa'])},{_field(tnt.get('beta', 0.0))}"
        ),
        "*EOS_JWL",
        "$# eosid         a         b        r1        r2     omega        e0        v0",
        (
            f"2,{_field(jwl['a_pa'])},{_field(jwl['b_pa'])},{_field(jwl['r1'])},"
            f"{_field(jwl['r2'])},{_field(jwl['omega'])},"
            f"{_field(jwl['initial_internal_energy_density_j_per_m3'])},"
            f"{_field(jwl['initial_relative_volume'])}"
        ),
    ]


def _field(value: object) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("keyword numeric value must be finite")
    for precision in range(9, 0, -1):
        candidate = f"{number:.{precision}g}"
        if len(candidate) <= 10:
            return candidate
    raise ValueError(f"cannot format LS-DYNA numeric field: {value!r}")


def _chunked_ids(values: Iterable[int]) -> list[str]:
    items = list(values)
    return [
        ",".join(str(value) for value in items[index : index + 8])
        for index in range(0, len(items), 8)
    ]


def _object(value: object, path: str) -> JSONDict:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _vector3(value: object, path: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{path} must contain exactly three finite numbers")
    return [_finite(item, f"{path}[{index}]") for index, item in enumerate(value)]


def _finite(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{path} must be a finite number")
    return number


def _positive(value: object, path: str) -> float:
    number = _finite(value, path)
    if number <= 0.0:
        raise ValueError(f"{path} must be positive")
    return number
