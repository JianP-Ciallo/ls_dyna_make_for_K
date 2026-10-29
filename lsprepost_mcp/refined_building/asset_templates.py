"""Semantic Phase 18D templates built on the Phase 18C kernel contract."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .asset_resources import DetailedBuildingAssetDescriptor
from .backends.rc import _build_member_boxes
from .contracts import JSONDict, normalize_building_definition
from .meshing import count_axis_aligned_union_cells
from .spatial import AxisAlignedBox, compile_spatial_topology


_COMMERCIAL_SUPERMARKET_ID = "commercial_supermarket_detailed_building"
_RESIDENTIAL_COMMUNITY_ID = "residential_community_detailed_building"
_SUBWAY_ENTRANCE_ID = "subway_entrance_detailed_building"
_MAX_TEMPLATE_INTERVALS = 100_000
_MAX_TEMPLATE_AXIS_COORDINATES = 1_000_000
_TEMPLATE_FAMILY_LIMITS = {
    "max_solid_elements": 5_000_000,
    "max_beam_elements": 1_000_000,
    "max_shell_elements": 1_000_000,
    "max_node_count": 8_000_000,
    "max_total_elements": 6_000_000,
}


@dataclass(frozen=True, slots=True)
class DetailedBuildingTemplate:
    """Normalized, still-unmeshed input for one detailed-building package."""

    definitions: tuple[JSONDict, ...]
    geometry_manifest: JSONDict
    unmodeled_scope: tuple[str, ...]
    solid_element_estimate: int
    solid_estimate_kind: str


def normalize_asset_geometry(
    descriptor: DetailedBuildingAssetDescriptor,
    legacy_geometry: Mapping[str, object] | None,
) -> dict[str, float]:
    """Merge a user geometry override into the immutable resource snapshot."""

    result = {key: float(value) for key, value in descriptor.default_geometry.items()}
    if legacy_geometry is not None:
        if not isinstance(legacy_geometry, Mapping):
            raise TypeError("legacy_geometry must be a mapping")
        if any(not isinstance(key, str) for key in legacy_geometry):
            raise ValueError("geometry field names must be strings")
        unknown = set(legacy_geometry) - set(descriptor.geometry_fields)
        if unknown:
            raise ValueError(f"unknown geometry fields: {sorted(unknown)}")
        for key, value in legacy_geometry.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"legacy_geometry.{key} must be a finite positive number")
            number = float(value)
            if not math.isfinite(number) or number <= 0.0:
                raise ValueError(f"legacy_geometry.{key} must be a finite positive number")
            result[key] = number
    return result


def build_detailed_building_template(
    descriptor: DetailedBuildingAssetDescriptor,
    geometry: Mapping[str, float],
    *,
    structural_system: str,
    fidelity_profile: str,
    mesh_profile: str,
    generation_options: Mapping[str, object],
) -> DetailedBuildingTemplate:
    """Dispatch a registered asset family to its semantic template builder."""

    if descriptor.resource_id == _COMMERCIAL_SUPERMARKET_ID:
        return _build_commercial_supermarket(
            descriptor,
            geometry,
            structural_system=structural_system,
            fidelity_profile=fidelity_profile,
            mesh_profile=mesh_profile,
            generation_options=generation_options,
        )
    if descriptor.resource_id == _RESIDENTIAL_COMMUNITY_ID:
        return _build_residential_community(
            descriptor,
            geometry,
            structural_system=structural_system,
            fidelity_profile=fidelity_profile,
            mesh_profile=mesh_profile,
            generation_options=generation_options,
        )
    if descriptor.resource_id == _SUBWAY_ENTRANCE_ID:
        return _build_subway_entrance(
            descriptor,
            geometry,
            structural_system=structural_system,
            fidelity_profile=fidelity_profile,
            mesh_profile=mesh_profile,
            generation_options=generation_options,
        )
    raise NotImplementedError(
        f"detailed building template {descriptor.resource_id!r} is not implemented"
    )


def _build_commercial_supermarket(
    descriptor: DetailedBuildingAssetDescriptor,
    geometry: Mapping[str, float],
    *,
    structural_system: str,
    fidelity_profile: str,
    mesh_profile: str,
    generation_options: Mapping[str, object],
) -> DetailedBuildingTemplate:
    length = float(geometry["length_m"])
    width = float(geometry["width_m"])
    height = float(geometry["height_m"])
    wall = float(geometry["wall_thickness_m"])
    entrance_width = float(geometry["entrance_width_m"])
    entrance_height = float(geometry["entrance_height_m"])
    _validate_supermarket_geometry(
        length,
        width,
        height,
        wall,
        entrance_width,
        entrance_height,
    )

    mesh_row_raw = descriptor.mesh_profile_rows[mesh_profile]
    mesh_row = {key: float(value) for key, value in mesh_row_raw.items()}
    member_foundation_target = mesh_row["member_foundation_target_m"]
    slab_wall_target = mesh_row["slab_wall_target_m"]
    minimum_thickness_layers = int(mesh_row_raw["minimum_thickness_layers"])
    panel_target = mesh_row["panel_target_m"]
    rebar_target = mesh_row["rebar_target_length_m"]
    steel_target = mesh_row["steel_member_target_length_m"]

    minimum_bay = min(length / 4.0, width / 3.0)
    column_width = min(0.30, minimum_bay / 3.0)
    column_depth = min(0.30, minimum_bay / 3.0)
    beam_width = min(0.30, minimum_bay / 3.0)
    beam_depth = min(0.40, (height - 2.0 * wall) / 4.0)
    if structural_system == "steel_concrete_hybrid":
        minimum_solid_thickness = wall
    elif structural_system == "rc_frame":
        minimum_solid_thickness = min(
            wall,
            column_width,
            column_depth,
            beam_width,
            beam_depth,
        )
    else:  # guarded by the descriptor, retained as a narrow template boundary
        raise ValueError(f"structural system {structural_system!r} is not supported")
    solid_target = min(
        member_foundation_target,
        slab_wall_target,
        minimum_solid_thickness / minimum_thickness_layers,
    )

    x_axes = [length * index / 4.0 for index in range(5)]
    y_axes = [width * index / 3.0 for index in range(4)]
    x_min, y_min, z_min = wall, wall, wall
    x_max, y_max, z_max = length - wall, width - wall, height - wall
    partition_x = length * 2.0 / 3.0
    partition_y = width * 2.0 / 3.0

    spaces: list[JSONDict] = [
        {
            "id": "sales_hall",
            "level_id": "level_1",
            "kind": "sales_hall",
            "bounds_m": [x_min, y_min, z_min, partition_x, y_max, z_max],
        },
        {
            "id": "stockroom",
            "level_id": "level_1",
            "kind": "stockroom",
            "bounds_m": [partition_x, y_min, z_min, x_max, partition_y, z_max],
        },
        {
            "id": "service_room",
            "level_id": "level_1",
            "kind": "service_room",
            "bounds_m": [partition_x, partition_y, z_min, x_max, y_max, z_max],
        },
    ]

    entrance_min_x = (length - entrance_width) / 2.0
    entrance_max_x = entrance_min_x + entrance_width
    entrance_max_z = z_min + entrance_height
    thin = min(0.05, wall / 2.0)
    stock_door_y = _centered_interval(y_min, partition_y, min(0.70, (partition_y - y_min) / 3.0))
    service_door_y = _centered_interval(
        partition_y,
        y_max,
        min(0.60, (y_max - partition_y) / 2.0),
    )
    stock_service_door_x = _centered_interval(
        partition_x,
        x_max,
        min(0.80, (x_max - partition_x) / 3.0),
    )
    door_top = min(z_max, z_min + min(2.0, (z_max - z_min) * 0.8))
    openings: list[JSONDict] = [
        {
            "id": "front_entrance",
            "kind": "entrance",
            "bounds_m": [
                entrance_min_x,
                0.0,
                z_min,
                entrance_max_x,
                wall,
                entrance_max_z,
            ],
            "connects": ["sales_hall", "exterior"],
        },
        {
            "id": "sales_stock_door",
            "kind": "door",
            "bounds_m": [
                partition_x - thin,
                stock_door_y[0],
                z_min,
                partition_x,
                stock_door_y[1],
                door_top,
            ],
            "connects": ["sales_hall", "stockroom"],
        },
        {
            "id": "sales_service_door",
            "kind": "door",
            "bounds_m": [
                partition_x - thin,
                service_door_y[0],
                z_min,
                partition_x,
                service_door_y[1],
                door_top,
            ],
            "connects": ["sales_hall", "service_room"],
        },
        {
            "id": "stock_service_door",
            "kind": "door",
            "bounds_m": [
                stock_service_door_x[0],
                partition_y - thin,
                z_min,
                stock_service_door_x[1],
                partition_y,
                door_top,
            ],
            "connects": ["stockroom", "service_room"],
        },
    ]

    nonstructural = _commercial_panels(
        length=length,
        width=width,
        height=height,
        wall=wall,
        partition_x=partition_x,
        partition_y=partition_y,
        space_bounds=(x_min, y_min, z_min, x_max, y_max, z_max),
        entrance=(entrance_min_x, z_min, entrance_max_x, entrance_max_z),
        stock_door=(stock_door_y[0], z_min, stock_door_y[1], door_top),
        service_door=(service_door_y[0], z_min, service_door_y[1], door_top),
        stock_service_door=(
            stock_service_door_x[0],
            z_min,
            stock_service_door_x[1],
            door_top,
        ),
        fidelity_profile=fidelity_profile,
        panel_target=panel_target,
    )

    reinforcement_mode = str(generation_options["reinforcement_mode"])
    rebar_parameters: dict[str, object] = {
        "cover_m": float(generation_options["cover_m"]),
        "bar_diameter_m": float(generation_options["bar_diameter_m"]),
        "rebar_spacing_m": float(generation_options["rebar_spacing_m"]),
        "rebar_target_length_m": rebar_target,
    }
    opening_frame_profile: dict[str, object] = {
        "profile_id": "commercial_front_entrance_v1",
        "opening_id": "front_entrance",
        "section_width_m": column_width,
        "section_depth_m": beam_depth,
    }
    include_roles = generation_options.get("include_reinforcement_roles")
    if structural_system == "steel_concrete_hybrid":
        concrete_reinforcement: dict[str, object] = {
            "mode": reinforcement_mode,
            **rebar_parameters,
        }
        if reinforcement_mode == "custom":
            concrete_reinforcement["include_roles"] = list(include_roles or ())
        system_parameters: dict[str, object] = {
            "mesh_size_m": solid_target,
            "slab_thickness_m": wall,
            "foundation_thickness_m": wall,
            "member_target_length_m": steel_target,
            "opening_frame_profile": opening_frame_profile,
            "concrete_reinforcement": concrete_reinforcement,
        }
        predicted = (
            _cell_count((length, width, wall), solid_target)
            + _cell_count(
                (length, width, height - (height - wall)),
                solid_target,
            )
        )
        estimate_kind = "exact"
    elif structural_system == "rc_frame":
        system_parameters = {
            "mesh_size_m": solid_target,
            "column_width_m": column_width,
            "column_depth_m": column_depth,
            "beam_width_m": beam_width,
            "beam_depth_m": beam_depth,
            "slab_thickness_m": wall,
            "foundation_thickness_m": wall,
            "generation_mode": reinforcement_mode,
            "opening_frame_profile": opening_frame_profile,
            **rebar_parameters,
        }
        if reinforcement_mode == "custom":
            system_parameters["include_reinforcement_roles"] = list(include_roles or ())
        predicted = 0
        estimate_kind = "conservative_upper_bound"
    definition: JSONDict = {
        "schema_version": "1.0.0",
        "asset_id": descriptor.resource_id,
        "unit_system": "SI_m_s_kg_N_Pa",
        "envelope": {"origin_m": [0.0, 0.0, 0.0], "size_m": [length, width, height]},
        "levels": [{"id": "level_1", "elevation_m": 0.0, "height_m": height}],
        "grid_axes": {"x_m": x_axes, "y_m": y_axes},
        "spaces": spaces,
        "openings": openings,
        "structural_system": {"type": structural_system, "parameters": system_parameters},
        "nonstructural": nonstructural,
        "fidelity_profile": fidelity_profile,
        "requires_project_review": True,
    }
    if structural_system == "rc_frame":
        predicted = _rc_union_grid_upper_bound(
            definition,
            solid_target,
            max_cells=int(generation_options.get("max_solid_elements", 5_000_000)),
        )
    return DetailedBuildingTemplate(
        definitions=(copy.deepcopy(definition),),
        geometry_manifest={
            "legacy_asset_id": descriptor.legacy_asset_id,
            "normalized_legacy_geometry": dict(sorted(geometry.items())),
            "local_envelope_bounds_m": [0.0, 0.0, 0.0, length, width, height],
            "bay_count": {"x": 4, "y": 3},
            "space_ids": ["sales_hall", "stockroom", "service_room"],
            "opening_ids": [row["id"] for row in openings],
        },
        unmodeled_scope=(
            "steel connection constitutive cards and final section-card selection",
            "facade glazing door and partition material cards",
            "MEP equipment shelving contents and architectural finishes",
            "material calibration mesh convergence and solver validation evidence",
        ),
        solid_element_estimate=predicted,
        solid_estimate_kind=estimate_kind,
    )


def _build_residential_community(
    descriptor: DetailedBuildingAssetDescriptor,
    geometry: Mapping[str, float],
    *,
    structural_system: str,
    fidelity_profile: str,
    mesh_profile: str,
    generation_options: Mapping[str, object],
) -> DetailedBuildingTemplate:
    tower_count = _bounded_integer(geometry["tower_count"], "tower_count", 1, 6)
    length = float(geometry["tower_length_m"])
    width = float(geometry["tower_width_m"])
    height = float(geometry["tower_height_m"])
    spacing = float(geometry["tower_spacing_m"])
    wall = float(geometry["wall_thickness_m"])
    balcony_depth = float(geometry["balcony_depth_m"])
    storey_count = _positive_integer(
        generation_options.get("storey_count"), "storey_count"
    )
    storey_intervals = tower_count * storey_count
    reinforcement_mode = str(generation_options["reinforcement_mode"])
    include_roles = generation_options.get("include_reinforcement_roles")
    if reinforcement_mode == "full_reinforced":
        beam_lower_bound = storey_intervals
    elif reinforcement_mode == "custom" and include_roles:
        selected = {str(role) for role in include_roles}  # type: ignore[union-attr]
        if structural_system == "rc_frame":
            selected.discard("wall_rebar")
        storey_scoped_roles = {
            "column_longitudinal",
            "column_stirrup",
            "beam_longitudinal",
            "beam_stirrup",
            "slab_rebar",
            "wall_rebar",
        }
        if selected & storey_scoped_roles:
            beam_lower_bound = storey_intervals
        elif "foundation_rebar" in selected:
            beam_lower_bound = tower_count
        else:
            beam_lower_bound = 0
    else:
        beam_lower_bound = 0
    solid_lower_bound = storey_intervals
    shell_lower_bound = 2 * storey_intervals
    _enforce_template_family_lower_bounds(
        generation_options,
        {
            "solid_elements": solid_lower_bound,
            "beam_elements": beam_lower_bound,
            "shell_elements": shell_lower_bound,
            "node_count": storey_intervals,
            "total_elements": (
                solid_lower_bound + beam_lower_bound + shell_lower_bound
            ),
        },
    )
    if storey_intervals > _MAX_TEMPLATE_INTERVALS:
        raise ValueError(
            "residential template intervals exceed internal hard cap "
            f"{_MAX_TEMPLATE_INTERVALS}"
        )
    storey_height = height / storey_count
    if wall * 4.0 >= min(length, width):
        raise ValueError("wall_thickness_m leaves no valid residential interior")
    if balcony_depth >= width - 2.0 * wall:
        raise ValueError("balcony_depth_m leaves no valid residential floor depth")
    if 2.0 * wall >= storey_height:
        raise ValueError("storey_count leaves no valid clear storey height")

    mesh_row_raw = descriptor.mesh_profile_rows[mesh_profile]
    mesh_row = {key: float(value) for key, value in mesh_row_raw.items()}
    minimum_layers = int(mesh_row_raw["minimum_thickness_layers"])
    column_width = min(0.30, length / 6.0)
    column_depth = min(0.30, width / 6.0)
    beam_width = min(0.30, min(length, width) / 6.0)
    beam_depth = min(0.40, (storey_height - 2.0 * wall) / 3.0)
    minimum_thickness = min(
        wall,
        column_width,
        column_depth,
        beam_width,
        beam_depth,
    )
    solid_target = min(
        mesh_row["member_foundation_target_m"],
        math.nextafter(minimum_thickness / minimum_layers, math.inf),
    )
    rebar_parameters: dict[str, object] = {
        "cover_m": float(generation_options["cover_m"]),
        "bar_diameter_m": float(generation_options["bar_diameter_m"]),
        "rebar_spacing_m": float(generation_options["rebar_spacing_m"]),
        "rebar_target_length_m": mesh_row["rebar_target_length_m"],
    }
    definitions: list[JSONDict] = []
    artifact_rows: list[JSONDict] = []
    predicted = 0
    solid_limit = int(generation_options["max_solid_elements"])
    for tower_index in range(tower_count):
        if predicted >= solid_limit:
            predicted = solid_limit + 1
            break
        tower_id = f"tower_{tower_index + 1:03d}"
        origin_x = tower_index * (length + spacing)
        levels = [
            {
                "id": f"{tower_id}_level_{level_index + 1:02d}",
                "elevation_m": level_index * storey_height,
                "height_m": storey_height,
            }
            for level_index in range(storey_count)
        ]
        spaces, openings, wall_bounds = _residential_spatial_rows(
            tower_id=tower_id,
            origin_x=origin_x,
            length=length,
            width=width,
            height=height,
            wall=wall,
            storey_count=storey_count,
        )
        parameters: dict[str, object] = {
            "mesh_size_m": solid_target,
            "column_width_m": column_width,
            "column_depth_m": column_depth,
            "beam_width_m": beam_width,
            "beam_depth_m": beam_depth,
            "slab_thickness_m": wall,
            "foundation_thickness_m": wall,
            "generation_mode": reinforcement_mode,
            **rebar_parameters,
        }
        if structural_system == "rc_frame_shear_wall":
            parameters["wall_bounds_m"] = wall_bounds
        elif structural_system != "rc_frame":
            raise ValueError(f"structural system {structural_system!r} is not supported")
        if reinforcement_mode == "custom":
            parameters["include_reinforcement_roles"] = list(include_roles or ())
        definition: JSONDict = {
            "schema_version": "1.0.0",
            "asset_id": tower_id,
            "unit_system": "SI_m_s_kg_N_Pa",
            "envelope": {
                "origin_m": [origin_x, 0.0, 0.0],
                "size_m": [length, width, height],
            },
            "levels": levels,
            "grid_axes": {
                "x_m": [origin_x, origin_x + length / 2.0, origin_x + length],
                "y_m": [0.0, width / 2.0, width],
            },
            "spaces": spaces,
            "openings": openings,
            "structural_system": {
                "type": structural_system,
                "parameters": parameters,
            },
            "nonstructural": _residential_panels(
                tower_id=tower_id,
                origin_x=origin_x,
                length=length,
                width=width,
                height=height,
                wall=wall,
                balcony_depth=balcony_depth,
                storey_count=storey_count,
                openings=openings,
                fidelity_profile=fidelity_profile,
                panel_target=mesh_row["panel_target_m"],
            ),
            "fidelity_profile": fidelity_profile,
            "requires_project_review": True,
        }
        definition_count = _count_rc_definition_solids(
            definition,
            structural_system,
            solid_target,
            max_cells=solid_limit - predicted,
        )
        predicted += definition_count
        definitions.append(copy.deepcopy(definition))
        artifact_rows.append(
            {
                "artifact_id": tower_id,
                "local_origin_m": [origin_x, 0.0, 0.0],
                "local_envelope_bounds_m": [
                    origin_x,
                    0.0,
                    0.0,
                    origin_x + length,
                    width,
                    height,
                ],
                "storey_count": storey_count,
                "predicted_solid_elements": definition_count,
            }
        )
    return DetailedBuildingTemplate(
        definitions=tuple(definitions),
        geometry_manifest={
            "legacy_asset_id": descriptor.legacy_asset_id,
            "normalized_legacy_geometry": dict(sorted(geometry.items())),
            "tower_count": tower_count,
            "storey_count": storey_count,
            "tower_pitch_m": length + spacing,
            "tower_clear_spacing_m": spacing,
            "artifacts": artifact_rows,
        },
        unmodeled_scope=(
            "stairs lifts utility risers facade material cards and architectural finishes",
            "member section detailing material calibration and solver validation evidence",
        ),
        solid_element_estimate=predicted,
        solid_estimate_kind="exact",
    )


def _residential_spatial_rows(
    *,
    tower_id: str,
    origin_x: float,
    length: float,
    width: float,
    height: float,
    wall: float,
    storey_count: int,
) -> tuple[list[JSONDict], list[JSONDict], list[list[float]]]:
    storey_height = height / storey_count
    core_min_x = origin_x + length * 0.35
    core_max_x = origin_x + length * 0.65
    core_min_y = width * 0.35
    core_max_y = width * 0.65
    core_width = core_max_x - core_min_x
    core_depth = core_max_y - core_min_y
    thin = min(0.05, wall / 2.0)
    door_width_x = min(0.22, core_width * 0.18)
    door_width_y = min(0.22, core_depth * 0.18)
    spaces: list[JSONDict] = []
    openings: list[JSONDict] = []
    wall_bounds: list[list[float]] = []
    for level_index in range(storey_count):
        level_number = level_index + 1
        level_id = f"{tower_id}_level_{level_number:02d}"
        prefix = level_id
        level_base = level_index * storey_height
        level_top = level_base + storey_height
        z_min = level_base + wall
        z_max = level_top - wall
        door_top = min(z_max, z_min + min(2.0, (z_max - z_min) * 0.85))
        regions = (
            ("apartment_west", "apartment", [origin_x + wall, wall, z_min, core_min_x, width - wall, z_max]),
            ("apartment_east", "apartment", [core_max_x, wall, z_min, origin_x + length - wall, width - wall, z_max]),
            ("apartment_south", "apartment", [core_min_x, wall, z_min, core_max_x, core_min_y, z_max]),
            ("apartment_north", "apartment", [core_min_x, core_max_y, z_min, core_max_x, width - wall, z_max]),
            ("core", "circulation_core", [core_min_x, core_min_y, z_min, core_max_x, core_max_y, z_max]),
        )
        ids: dict[str, str] = {}
        for suffix, kind, bounds in regions:
            space_id = f"{prefix}_{suffix}"
            ids[suffix] = space_id
            spaces.append(
                {
                    "id": space_id,
                    "level_id": level_id,
                    "kind": kind,
                    "bounds_m": bounds,
                }
            )

        west_y = (core_min_y + core_max_y) / 2.0
        east_y = west_y
        south_x = core_min_x + core_width * 0.25
        north_x = core_min_x + core_width * 0.50
        apartment_doors = (
            (
                "west",
                [core_min_x - thin, west_y - door_width_y / 2.0, z_min, core_min_x + wall, west_y + door_width_y / 2.0, door_top],
                [ids["apartment_west"], ids["core"]],
            ),
            (
                "east",
                [core_max_x - wall, east_y - door_width_y / 2.0, z_min, core_max_x + thin, east_y + door_width_y / 2.0, door_top],
                [ids["apartment_east"], ids["core"]],
            ),
            (
                "south",
                [south_x - door_width_x / 2.0, core_min_y - thin, z_min, south_x + door_width_x / 2.0, core_min_y + thin, door_top],
                [ids["apartment_south"], ids["core"]],
            ),
            (
                "north",
                [north_x - door_width_x / 2.0, core_max_y - thin, z_min, north_x + door_width_x / 2.0, core_max_y + thin, door_top],
                [ids["apartment_north"], ids["core"]],
            ),
        )
        for suffix, bounds, connects in apartment_doors:
            openings.append(
                {
                    "id": f"{prefix}_apartment_{suffix}_door",
                    "kind": "apartment_door",
                    "bounds_m": bounds,
                    "connects": connects,
                }
            )
        if level_index == 0:
            entrance_x = core_min_x + core_width * 0.78
            entrance_width = min(0.20, core_width * 0.16)
            openings.append(
                {
                    "id": f"{prefix}_core_exterior_entrance",
                    "kind": "entrance",
                    "bounds_m": [
                        entrance_x - entrance_width / 2.0,
                        0.0,
                        z_min,
                        entrance_x + entrance_width / 2.0,
                        core_min_y,
                        door_top,
                    ],
                    "connects": [ids["core"], "exterior"],
                }
            )
        wall_bounds.extend(
            (
                [
                    core_min_x,
                    core_min_y,
                    z_min,
                    core_min_x + wall,
                    core_max_y,
                    z_max,
                ],
                [
                    core_max_x - wall,
                    core_min_y,
                    z_min,
                    core_max_x,
                    core_max_y,
                    z_max,
                ],
            )
        )
    return spaces, openings, wall_bounds


def _residential_panels(
    *,
    tower_id: str,
    origin_x: float,
    length: float,
    width: float,
    height: float,
    wall: float,
    balcony_depth: float,
    storey_count: int,
    openings: Sequence[JSONDict],
    fidelity_profile: str,
    panel_target: float,
) -> list[JSONDict]:
    thin = min(0.05, wall / 2.0)
    storey_height = height / storey_count
    rows: list[JSONDict] = []
    for level_index in range(storey_count):
        prefix = f"{tower_id}_level_{level_index + 1:02d}"
        z_min = level_index * storey_height + wall
        z_max = (level_index + 1) * storey_height - wall
        balcony_x0 = origin_x + length * 0.20
        balcony_x1 = origin_x + length * 0.80
        rows.extend(
            (
                {
                    "id": f"{prefix}_balcony_slab",
                    "kind": "balcony_slab",
                    "material_role": "concrete",
                    "bounds_m": [
                        balcony_x0,
                        0.0,
                        z_min - thin / 2.0,
                        balcony_x1,
                        balcony_depth,
                        z_min + thin / 2.0,
                    ],
                    "mesh_size_m": panel_target,
                },
                {
                    "id": f"{prefix}_balcony_barrier",
                    "kind": "balcony_barrier",
                    "material_role": "structural_steel",
                    "bounds_m": [
                        balcony_x0,
                        0.0,
                        z_min,
                        balcony_x1,
                        thin,
                        min(z_max, z_min + 1.10),
                    ],
                    "plane_at": "min",
                    "mesh_size_m": panel_target,
                },
            )
        )
        if fidelity_profile == "structural_core":
            continue
        level_openings = [
            row
            for row in openings
            if str(row["id"]).startswith(prefix)
        ]
        front_holes = tuple(
            (
                float(row["bounds_m"][0]),
                float(row["bounds_m"][2]),
                float(row["bounds_m"][3]),
                float(row["bounds_m"][5]),
            )
            for row in level_openings
            if row["kind"] == "entrance"
        )
        for side, fixed_axis, fixed_bounds, u_axis, u_bounds, plane in (
            ("front", 1, (0.0, thin), 0, (origin_x, origin_x + length), "min"),
            ("rear", 1, (width - thin, width), 0, (origin_x, origin_x + length), "max"),
            ("left", 0, (origin_x, origin_x + thin), 1, (0.0, width), "min"),
            ("right", 0, (origin_x + length - thin, origin_x + length), 1, (0.0, width), "max"),
        ):
            rows.extend(
                _split_panel(
                    prefix=f"{prefix}_{side}_facade",
                    fixed_axis=fixed_axis,
                    fixed_bounds=fixed_bounds,
                    u_axis=u_axis,
                    u_bounds=u_bounds,
                    v_axis=2,
                    v_bounds=(z_min, z_max),
                    holes=front_holes if side == "front" else (),
                    plane_at=plane,
                    kind="facade",
                    material_role="facade",
                    mesh_size_m=panel_target,
                )
            )
        core_min_x = origin_x + length * 0.35
        core_max_x = origin_x + length * 0.65
        core_min_y = width * 0.35
        core_max_y = width * 0.65
        for side, fixed_axis, fixed_bounds, u_axis, u_bounds in (
            ("core_west", 0, (core_min_x - thin / 2.0, core_min_x + thin / 2.0), 1, (core_min_y, core_max_y)),
            ("core_east", 0, (core_max_x - thin / 2.0, core_max_x + thin / 2.0), 1, (core_min_y, core_max_y)),
            ("core_south", 1, (core_min_y - thin / 2.0, core_min_y + thin / 2.0), 0, (core_min_x, core_max_x)),
            ("core_north", 1, (core_max_y - thin / 2.0, core_max_y + thin / 2.0), 0, (core_min_x, core_max_x)),
        ):
            panel_holes = tuple(
                (
                    float(row["bounds_m"][u_axis]),
                    float(row["bounds_m"][2]),
                    float(row["bounds_m"][u_axis + 3]),
                    float(row["bounds_m"][5]),
                )
                for row in level_openings
                if row["kind"] == "apartment_door" and side.endswith(str(row["id"]).split("_")[-2])
            )
            rows.extend(
                _split_panel(
                    prefix=f"{prefix}_{side}",
                    fixed_axis=fixed_axis,
                    fixed_bounds=fixed_bounds,
                    u_axis=u_axis,
                    u_bounds=u_bounds,
                    v_axis=2,
                    v_bounds=(z_min, z_max),
                    holes=panel_holes,
                    plane_at="mid",
                    kind="partition",
                    material_role="nonstructural",
                    mesh_size_m=panel_target,
                )
            )
        if fidelity_profile == "research_detailed":
            rows.extend(
                _split_panel(
                    prefix=f"{prefix}_research_lobby_screen",
                    fixed_axis=1,
                    fixed_bounds=(core_min_y + thin, core_min_y + 2.0 * thin),
                    u_axis=0,
                    u_bounds=(core_min_x, core_max_x),
                    v_axis=2,
                    v_bounds=(z_min + 0.20, min(z_max, z_min + 1.60)),
                    holes=(),
                    plane_at="mid",
                    kind="glazing",
                    material_role="glazing",
                    mesh_size_m=panel_target,
                )
            )
    return rows


def _build_subway_entrance(
    descriptor: DetailedBuildingAssetDescriptor,
    geometry: Mapping[str, float],
    *,
    structural_system: str,
    fidelity_profile: str,
    mesh_profile: str,
    generation_options: Mapping[str, object],
) -> DetailedBuildingTemplate:
    width = float(geometry["width_m"])
    floor = float(generation_options["passage_floor_thickness_m"])
    wall = float(generation_options["passage_wall_thickness_m"])
    roof = float(generation_options["passage_roof_thickness_m"])
    passage_height = float(generation_options["passage_clear_height_m"])
    passage_width = float(generation_options["passage_clear_width_m"])
    passage_length = float(generation_options["passage_length_m"])
    upper_length = float(generation_options["upper_landing_length_m"])
    lower_length = float(generation_options["lower_landing_length_m"])
    pavilion_length = float(generation_options["pavilion_length_m"])
    pavilion_width = float(generation_options["pavilion_width_m"])
    pavilion_height = float(generation_options["pavilion_clear_height_m"])
    roof_rise = float(generation_options["pavilion_roof_arc_rise_m"])
    descent_rise = float(generation_options["escalator_rise_m"])
    escalator_angle = float(generation_options["escalator_angle_deg"])
    descent_length = descent_rise / math.tan(math.radians(escalator_angle))
    fixed_stair_slope = float(generation_options["fixed_stair_slope_deg"])
    stair_descent_length = descent_rise / math.tan(
        math.radians(fixed_stair_slope)
    )
    upper_landing_width = float(
        generation_options["upper_landing_clear_width_m"]
    )
    lower_landing_width = float(
        generation_options["lower_landing_clear_width_m"]
    )
    total_length = upper_length + descent_length + lower_length + passage_length
    roof_base_z = floor + descent_rise + pavilion_height
    rc_height = floor + passage_height + roof
    if 2.0 * wall >= min(total_length, width):
        raise ValueError("passage_wall_thickness_m leaves no valid subway passage")
    mesh_row_raw = descriptor.mesh_profile_rows[mesh_profile]
    mesh_row = {key: float(value) for key, value in mesh_row_raw.items()}
    minimum_layers = int(mesh_row_raw["minimum_thickness_layers"])
    minimum_thickness = min(floor, wall, roof)
    solid_target = min(
        mesh_row["member_foundation_target_m"],
        math.nextafter(minimum_thickness / minimum_layers, math.inf),
    )
    lower_start = upper_length + descent_length
    passage_start = lower_start + lower_length
    passage_min_y = (width - passage_width) / 2.0
    passage_max_y = passage_min_y + passage_width
    circulation_void = [
        wall,
        wall,
        floor,
        passage_start,
        width - wall,
        floor + passage_height,
    ]
    passage = [
        passage_start,
        passage_min_y,
        floor,
        total_length - wall,
        passage_max_y,
        floor + passage_height,
    ]
    opening = [0.0, wall, floor, wall, width - wall, floor + passage_height]
    terminal_opening = [
        total_length - wall,
        passage_min_y,
        floor,
        total_length,
        passage_max_y,
        floor + passage_height,
    ]
    passage_interface = [
        passage_start,
        passage_min_y,
        floor,
        passage_start + wall / 2.0,
        passage_max_y,
        floor + passage_height,
    ]
    lanes = _subway_lane_envelopes(
        width=width,
        wall=wall,
        stair_width=float(generation_options["stair_width_m"]),
        escalator_width=float(generation_options["escalator_width_m"]),
        equipment_envelope=float(
            generation_options["escalator_equipment_envelope_m"]
        ),
        lane_gap=float(generation_options["lane_gap_m"]),
        upper_length=upper_length,
        descent_length=descent_length,
        stair_descent_length=stair_descent_length,
        floor=floor,
        rise=descent_rise,
    )
    stair_members = _subway_stair_members(
        lane=lanes["A"],
        floor=floor,
        descent_length=stair_descent_length,
        stair_tread=float(generation_options["stair_tread_m"]),
        stair_rise=float(generation_options["stair_rise_m"]),
    )
    landing_thickness = min(floor, max(wall, floor * 0.50))
    upper_walk_z = floor + descent_rise
    rc_roof_bottom = floor + passage_height
    upper_landing_y0 = (width - upper_landing_width) / 2.0
    upper_landing_y1 = upper_landing_y0 + upper_landing_width
    lower_landing_y0 = (width - lower_landing_width) / 2.0
    lower_landing_y1 = lower_landing_y0 + lower_landing_width
    solid_members: list[JSONDict] = [
        {"part_role": "rc_box_floor", "bounds_m": [0.0, 0.0, 0.0, total_length, width, floor]},
        {"part_role": "rc_box_roof", "bounds_m": [lower_start, 0.0, rc_roof_bottom, total_length, width, rc_height]},
        {"part_role": "rc_box_wall", "bounds_m": [0.0, 0.0, floor, wall, width, rc_roof_bottom]},
        {"part_role": "rc_box_wall", "bounds_m": [total_length - wall, 0.0, floor, total_length, width, rc_roof_bottom]},
        {"part_role": "rc_box_wall", "bounds_m": [wall, 0.0, floor, total_length - wall, wall, rc_roof_bottom]},
        {"part_role": "rc_box_wall", "bounds_m": [wall, width - wall, floor, total_length - wall, width, rc_roof_bottom]},
        {
            "part_role": "upper_landing",
            "bounds_m": [
                0.0,
                upper_landing_y0,
                upper_walk_z - landing_thickness,
                upper_length,
                upper_landing_y1,
                upper_walk_z,
            ],
        },
    ]
    stair_upper_x = float(lanes["A"][0])
    if stair_upper_x > upper_length + 1.0e-12:
        solid_members.append(
            {
                "part_role": "upper_landing",
                "bounds_m": [
                    upper_length,
                    float(lanes["A"][1]),
                    upper_walk_z - landing_thickness,
                    stair_upper_x,
                    float(lanes["A"][4]),
                    upper_walk_z,
                ],
            }
        )
    solid_members.extend(
        {"part_role": "fixed_stair_A", "bounds_m": bounds}
        for bounds in stair_members
    )
    solid_members.append(
        {
            "part_role": "lower_landing_8",
            "bounds_m": [
                lower_start,
                lower_landing_y0,
                floor - landing_thickness,
                passage_start,
                lower_landing_y1,
                floor,
            ],
        }
    )
    pavilion_overhang = float(generation_options["pavilion_overhang_m"])
    pavilion_frame_size = float(generation_options["pavilion_frame_size_m"])
    pavilion_glazing_thickness = float(
        generation_options["pavilion_glazing_thickness_m"]
    )
    pavilion_roof_thickness = float(
        generation_options["pavilion_roof_thickness_m"]
    )
    pavilion_end = pavilion_length
    frame_start = pavilion_overhang
    frame_y0 = (width - pavilion_width) / 2.0 + pavilion_frame_size / 2.0
    frame_y1 = (width + pavilion_width) / 2.0 - pavilion_frame_size / 2.0
    plinth_height = max(0.10, pavilion_frame_size)
    bay_count = int(generation_options["glazing_bay_count"])
    frame_x_values = tuple(
        frame_start + (pavilion_end - frame_start) * index / bay_count
        for index in range(bay_count + 1)
    )
    plinth_interface_coordinates: list[list[float]] = []
    for x in frame_x_values:
        surface = _subway_route_walkable_elevation(
            x,
            upper_length,
            descent_length,
            floor,
            descent_rise,
            stair_members,
        )
        for y in (frame_y0, frame_y1):
            plinth_interface_coordinates.append([x, y, surface + plinth_height])
            solid_members.append(
                {
                    "part_role": "pavilion_rc_plinth",
                    "bounds_m": [
                        x - pavilion_frame_size / 2.0,
                        y - pavilion_frame_size / 2.0,
                        surface,
                        x + pavilion_frame_size / 2.0,
                        y + pavilion_frame_size / 2.0,
                        surface + plinth_height,
                    ],
                }
            )
    components = _subway_pavilion_and_equipment_components(
        lanes=lanes,
        width=width,
        floor=floor,
        wall=wall,
        upper_length=upper_length,
        descent_length=descent_length,
        pavilion_length=pavilion_length,
        pavilion_width=pavilion_width,
        pavilion_height=pavilion_height,
        roof_base_z=roof_base_z,
        roof_rise=roof_rise,
        rise=descent_rise,
        stair_members=stair_members,
        overhang=pavilion_overhang,
        frame_size=pavilion_frame_size,
        glazing_thickness=pavilion_glazing_thickness,
        roof_thickness=pavilion_roof_thickness,
        plinth_height=plinth_height,
        total_length=total_length,
        equipment_envelope=float(
            generation_options["escalator_equipment_envelope_m"]
        ),
        bay_count=bay_count,
        shell_element_limit=int(
            generation_options.get(
                "max_shell_elements", _TEMPLATE_FAMILY_LIMITS["max_shell_elements"]
            )
        ),
    )
    roof_components = [
        row
        for row in components
        if row.get("part_role") == "pavilion_metal_roof"
    ]
    if not roof_components:
        raise ValueError("pavilion roof components are required")
    roof_shell_normal_projection_factor = max(
        float(row["physical_normal_projection_factor"])
        for row in roof_components
    )
    roof_shell_vertical_half_envelope = max(
        float(row["physical_vertical_half_envelope_m"])
        for row in roof_components
    )
    physical_roof_top = max(
        max(float(point[2]) for point in row["points_m"])
        + float(row["physical_vertical_half_thickness_m"])
        for row in roof_components
    )
    total_height = max(rc_height, physical_roof_top)
    reinforcement_mode = str(generation_options["reinforcement_mode"])
    rebar_parameters: dict[str, object] = {
        "generation_mode": reinforcement_mode,
        "cover_m": float(generation_options["cover_m"]),
        "bar_diameter_m": float(generation_options["bar_diameter_m"]),
        "rebar_spacing_m": float(generation_options["rebar_spacing_m"]),
        "rebar_target_length_m": mesh_row["rebar_target_length_m"],
        "fixed_stair_longitudinal_spacing_m": float(
            generation_options["fixed_stair_longitudinal_spacing_m"]
        ),
        "fixed_stair_distribution_spacing_m": float(
            generation_options["fixed_stair_distribution_spacing_m"]
        ),
        "fixed_stair_local_densification_factor": float(
            generation_options["fixed_stair_local_densification_factor"]
        ),
        "connection_simplification_level": str(
            generation_options["connection_simplification_level"]
        ),
    }
    if reinforcement_mode == "custom":
        rebar_parameters["include_reinforcement_roles"] = list(
            generation_options.get("include_reinforcement_roles") or ()
        )
    if structural_system == "rc_box":
        parameters: dict[str, object] = {
            "mesh_size_m": solid_target,
            "box_thickness_m": wall,
            "floor_thickness_m": floor,
            "wall_thickness_m": wall,
            "roof_thickness_m": roof,
            "task4_subway_solid_target_m": solid_target,
            "task4_subway_solid_members": solid_members,
            "task4_subway_components": components,
            "task4_pavilion_plinth_interface_coordinates_m": plinth_interface_coordinates,
            **rebar_parameters,
        }
    elif structural_system == "rc_frame_shear_wall":
        member_size = min(0.30, min(total_length, width) / 6.0)
        frame_wall_members = copy.deepcopy(solid_members)
        frame_x_centers = (passage_start, total_length - wall - member_size / 2.0)
        for x_center in frame_x_centers:
            x0 = x_center - member_size / 2.0
            x1 = x_center + member_size / 2.0
            for y0, y1 in ((0.0, wall), (width - wall, width)):
                frame_wall_members.append(
                    {
                        "part_role": "rc_frame_column",
                        "bounds_m": [
                            x0,
                            y0,
                            floor,
                            x1,
                            y1,
                            floor + passage_height,
                        ],
                    }
                )
            frame_wall_members.append(
                {
                    "part_role": "rc_frame_roof_beam",
                    "bounds_m": [
                        x0,
                        0.0,
                        floor + passage_height,
                        x1,
                        width,
                        rc_height,
                    ],
                }
            )
        parameters = {
            "mesh_size_m": solid_target,
            "column_width_m": member_size,
            "column_depth_m": member_size,
            "beam_width_m": member_size,
            "beam_depth_m": min(0.40, passage_height / 4.0),
            "slab_thickness_m": roof,
            "foundation_thickness_m": floor,
            "wall_bounds_m": [
                [0.0, 0.0, floor, total_length, wall, floor + passage_height],
                [0.0, width - wall, floor, total_length, width, floor + passage_height],
                [total_length - wall, wall, floor, total_length, width - wall, floor + passage_height],
            ],
            "task4_subway_solid_target_m": solid_target,
            "task4_subway_solid_members": frame_wall_members,
            "task4_subway_components": components,
            "task4_pavilion_plinth_interface_coordinates_m": plinth_interface_coordinates,
            **rebar_parameters,
        }
    else:
        raise ValueError(f"structural system {structural_system!r} is not supported")
    definition: JSONDict = {
        "schema_version": "1.0.0",
        "asset_id": "subway_entrance_001",
        "unit_system": "SI_m_s_kg_N_Pa",
        "envelope": {
            "origin_m": [0.0, 0.0, 0.0],
            "size_m": [total_length, width, total_height],
        },
        "levels": [
            {"id": "entrance_level", "elevation_m": 0.0, "height_m": total_height}
        ],
        "grid_axes": {
            "x_m": [0.0, upper_length, lower_start, passage_start, total_length],
            "y_m": [0.0, width / 2.0, width],
        },
        "spaces": [
            {
                "id": "entrance_passage",
                "level_id": "entrance_level",
                "kind": "passage",
                "bounds_m": circulation_void,
            },
            {
                "id": "passage_9",
                "level_id": "entrance_level",
                "kind": "passage",
                "bounds_m": passage,
            },
        ],
        "openings": [
            {
                "id": "front_entrance",
                "kind": "entrance",
                "bounds_m": opening,
                "connects": ["entrance_passage", "exterior"],
            },
            {
                "id": "lower_landing_8_to_passage_9",
                "kind": "interface",
                "bounds_m": passage_interface,
                "connects": ["entrance_passage", "passage_9"],
            },
            {
                "id": "terminal_interface_10",
                "kind": "interface",
                "bounds_m": terminal_opening,
                "connects": ["passage_9", "exterior"],
            },
        ],
        "structural_system": {"type": structural_system, "parameters": parameters},
        "nonstructural": _subway_panels(
            passage_start=passage_start,
            total_length=total_length,
            width=width,
            floor=floor,
            clear_height=passage_height,
            wall=wall,
            opening=opening,
            fidelity_profile=fidelity_profile,
            panel_target=mesh_row["panel_target_m"],
        ),
        "fidelity_profile": fidelity_profile,
        "requires_project_review": True,
    }
    normalized = normalize_building_definition(definition)
    topology = compile_spatial_topology(normalized)
    counted_members = parameters["task4_subway_solid_members"]
    assert isinstance(counted_members, list)
    member_boxes = tuple(
        (str(row["part_role"]), AxisAlignedBox.from_bounds(row["bounds_m"]))
        for row in counted_members
    )
    base_members = tuple(
        (role, box) for role, box in member_boxes if role.startswith("rc_")
    )
    circulation_members = tuple(
        (role, box) for role, box in member_boxes if not role.startswith("rc_")
    )
    priorities = {
        "rc_box_floor": 0,
        "rc_box_wall": 1,
        "rc_box_roof": 2,
        "rc_frame_column": 3,
        "rc_frame_roof_beam": 3,
        "pavilion_rc_plinth": 3,
        "lower_landing_8": 4,
        "upper_landing": 4,
        "fixed_stair_A": 5,
    }
    opening_boxes = tuple(box for _, box in topology.opening_regions)
    solid_limit = int(generation_options["max_solid_elements"])
    predicted = count_axis_aligned_union_cells(
        base_members,
        solid_target,
        (*opening_boxes, *(box for _, box in circulation_members)),
        priorities,
        max_cells=solid_limit,
    )
    if predicted >= solid_limit:
        predicted = solid_limit + 1
    else:
        predicted += count_axis_aligned_union_cells(
            circulation_members,
            solid_target,
            opening_boxes,
            priorities,
            plinth_interface_coordinates,
            max_cells=solid_limit - predicted,
        )
    passage_probe = [
        (passage_start + total_length - wall) / 2.0,
        (passage_min_y + passage_max_y) / 2.0,
        floor + passage_height / 2.0,
    ]
    passage_wall_probe = [
        passage_probe[0],
        width - wall / 2.0,
        passage_probe[2],
    ]
    component_roles = {
        role: {"part_ids": [role]}
        for role in (
            "fixed_stair_A",
            "upper_landing",
            "lower_landing_8",
            "pavilion_rc_plinth",
            "pavilion_frame",
            "pavilion_glazing",
            "pavilion_metal_roof",
            "generic_signage",
        )
    }
    for equipment_id in ("escalator_1", "escalator_2"):
        component_roles[equipment_id] = {
            "part_ids": [
                f"{equipment_id}_truss_guides",
                f"{equipment_id}_step_band",
                f"{equipment_id}_balustrade",
                f"{equipment_id}_handrails",
            ]
        }
    return DetailedBuildingTemplate(
        definitions=(copy.deepcopy(definition),),
        geometry_manifest={
            "legacy_asset_id": descriptor.legacy_asset_id,
            "normalized_legacy_geometry": dict(sorted(geometry.items())),
            "local_envelope_bounds_m": [0.0, 0.0, 0.0, total_length, width, total_height],
            "passage_bounds_m": passage,
            "opening_ids": [
                "front_entrance",
                "lower_landing_8_to_passage_9",
                "terminal_interface_10",
            ],
            "predicted_solid_elements": predicted,
            "subway_circulation": {
                "fixed_stair_count": 1,
                "escalator_count": 2,
                "parallel_lane_ids": ["A", "B", "C"],
                "longitudinal_axis": "x",
                "longitudinal_route": [
                    "upper_landing",
                    "A_B_C",
                    "lower_landing_8",
                    "passage_9",
                    "interface_10",
                ],
                "has_turn": False,
                "has_station_hall": False,
                "lane_envelopes_m": lanes,
                "walkable_surface_elevations_m": {
                    "upper_landing": upper_walk_z,
                    "lower_landing_8": floor,
                    "passage_9": floor,
                },
                "upper_landing_bounds_m": [0.0, upper_landing_y0, upper_walk_z - landing_thickness, upper_length, upper_landing_y1, upper_walk_z],
                "lower_landing_8_bounds_m": [lower_start, lower_landing_y0, floor - landing_thickness, passage_start, lower_landing_y1, floor],
                "passage_9_bounds_m": passage,
                "interface_10_plane_m": [total_length - wall, passage_min_y, floor, total_length - wall, passage_max_y, floor + passage_height],
                "passage_probe_m": passage_probe,
                "passage_wall_probe_m": passage_wall_probe,
                "below_grade_rc_enclosure_bounds_m": [0.0, 0.0, 0.0, total_length, width, rc_height],
                "pavilion_validation_bounds_m": [0.0, 0.0, floor, pavilion_length + pavilion_overhang, width, total_height],
                "pavilion_glazing_void_probe_m": [pavilion_length / 2.0, (width - pavilion_width) / 2.0, (rc_height + roof_base_z) / 2.0],
                "passage_roof_probe_m": [passage_probe[0], passage_probe[1], rc_height - roof / 2.0],
                "component_roles": component_roles,
                "pavilion": {
                    "form": "long_glazed_enclosure",
                    "roof_profile": "shallow_continuous_curved_metal",
                    "clear_height_reference": "physical_roof_shell_lower_surface",
                    "physical_clear_height_m": pavilion_height,
                    "physical_roof_top_m": physical_roof_top,
                    "roof_shell_thickness_direction": "symmetric_shell_normal",
                    "roof_shell_normal_projection_factor": roof_shell_normal_projection_factor,
                    "roof_shell_vertical_half_envelope_m": roof_shell_vertical_half_envelope,
                    "covers_complete_descent": True,
                    "entrance_overhang_m": float(generation_options["pavilion_overhang_m"]),
                    "glazing_bay_count": int(generation_options["glazing_bay_count"]),
                    "generic_replaceable_signage_only": True,
                },
            },
        },
        unmodeled_scope=(
            "station hall and all geometry beyond terminal interface 10",
            "project-specific signage identity drainage fire egress and accessibility details",
            "material calibration soil interaction mesh convergence and solver validation evidence",
        ),
        solid_element_estimate=predicted,
        solid_estimate_kind="exact",
    )


def _subway_panels(
    *,
    passage_start: float,
    total_length: float,
    width: float,
    floor: float,
    clear_height: float,
    wall: float,
    opening: Sequence[float],
    fidelity_profile: str,
    panel_target: float,
) -> list[JSONDict]:
    if fidelity_profile == "structural_core":
        return []
    thin = min(0.05, wall / 2.0)
    rows: list[JSONDict] = [
        {
            "id": "blast_passage_wall_finish",
            "kind": "architectural_finish",
            "material_role": "nonstructural",
            "bounds_m": [passage_start, wall, floor + 0.1, total_length - wall, wall + thin, floor + clear_height - 0.1],
        }
    ]
    if fidelity_profile == "research_detailed":
        rows.append(
            {
                "id": "research_passage_wall_finish",
                "kind": "research_finish",
                "material_role": "nonstructural",
                "bounds_m": [passage_start, width - wall - thin, floor + 0.1, total_length - wall, width - wall, floor + clear_height - 0.1],
            }
        )
    return rows


def _subway_lane_envelopes(
    *,
    width: float,
    wall: float,
    stair_width: float,
    escalator_width: float,
    equipment_envelope: float,
    lane_gap: float,
    upper_length: float,
    descent_length: float,
    stair_descent_length: float,
    floor: float,
    rise: float,
) -> dict[str, list[float]]:
    equipment_width = escalator_width + 2.0 * equipment_envelope
    connection_width = stair_width + 2.0 * equipment_width + 2.0 * lane_gap
    cursor = (width - connection_width) / 2.0
    result: dict[str, list[float]] = {}
    for lane_id, lane_width in (
        ("A", stair_width),
        ("B", equipment_width),
        ("C", equipment_width),
    ):
        lower_x = upper_length + descent_length
        upper_x = (
            lower_x - stair_descent_length
            if lane_id == "A"
            else upper_length
        )
        result[lane_id] = [
            upper_x,
            cursor,
            floor,
            lower_x,
            cursor + lane_width,
            floor + rise,
        ]
        cursor += lane_width + lane_gap
    return result


def _subway_walkable_elevation(
    x: float,
    upper_length: float,
    descent_length: float,
    floor: float,
    rise: float,
) -> float:
    if x <= upper_length:
        return floor + rise
    if x >= upper_length + descent_length:
        return floor
    return floor + rise * (
        1.0 - (x - upper_length) / descent_length
    )


def _subway_route_walkable_elevation(
    x: float,
    upper_length: float,
    descent_length: float,
    floor: float,
    rise: float,
    stair_members: Sequence[Sequence[float]],
) -> float:
    """Return the highest walkable surface across the three parallel lanes."""

    escalator_elevation = _subway_walkable_elevation(
        x, upper_length, descent_length, floor, rise
    )
    if not stair_members:
        return escalator_elevation
    tolerance = 1.0e-12
    stair_start = min(float(bounds[0]) for bounds in stair_members)
    stair_end = max(float(bounds[3]) for bounds in stair_members)
    if x < stair_start - tolerance:
        stair_elevation = floor + rise
    elif x > stair_end + tolerance:
        stair_elevation = floor
    else:
        containing_treads = (
            float(bounds[5])
            for bounds in stair_members
            if float(bounds[0]) - tolerance <= x <= float(bounds[3]) + tolerance
        )
        stair_elevation = max(containing_treads, default=floor)
    return max(escalator_elevation, stair_elevation)


def _subway_route_clearance_elevation(
    x: float,
    upper_length: float,
    descent_length: float,
    floor: float,
    rise: float,
    stair_members: Sequence[Sequence[float]],
) -> float:
    """Return a continuous roof-control surface above every stair tread."""

    escalator_elevation = _subway_walkable_elevation(
        x, upper_length, descent_length, floor, rise
    )
    if not stair_members:
        return escalator_elevation
    ordered = sorted(stair_members, key=lambda bounds: float(bounds[0]))
    if x <= float(ordered[0][0]):
        stair_envelope = float(ordered[0][5])
    else:
        stair_envelope = float(ordered[-1][5])
        for index, bounds in enumerate(ordered):
            x0 = float(bounds[0])
            x1 = float(bounds[3])
            if x <= x1 + 1.0e-12:
                current_top = float(bounds[5])
                if index == 0:
                    stair_envelope = current_top
                else:
                    previous_top = float(ordered[index - 1][5])
                    fraction = min(1.0, max(0.0, (x - x0) / (x1 - x0)))
                    stair_envelope = previous_top + (
                        current_top - previous_top
                    ) * fraction
                break
    return max(escalator_elevation, stair_envelope)


def _subway_stair_members(
    *,
    lane: Sequence[float],
    floor: float,
    descent_length: float,
    stair_tread: float,
    stair_rise: float,
) -> list[list[float]]:
    total_rise = float(lane[5]) - floor
    step_count = max(
        1,
        math.ceil(total_rise / stair_rise),
        math.ceil(descent_length / stair_tread),
    )
    tread = descent_length / step_count
    actual_rise = total_rise / step_count
    structural_depth = max(actual_rise + 0.25 * stair_tread, 0.12)
    result: list[list[float]] = []
    for index in range(step_count):
        x_min = float(lane[0]) + index * tread
        x_max = float(lane[0]) + (index + 1) * tread
        top = floor + total_rise * (step_count - index) / step_count
        result.append(
            [
                x_min,
                float(lane[1]),
                max(floor, top - structural_depth),
                x_max,
                float(lane[4]),
                top,
            ]
        )
    return result


def _quality_subdivided_glazing_band(
    panels: tuple[
        tuple[
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
        ],
        ...,
    ],
    *,
    max_shells: int,
) -> tuple[
    tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ],
    ...,
]:
    """Mesh a glazing band with one conforming vertical layer schedule."""

    if not panels:
        return ()
    if max_shells < len(panels):
        raise ValueError("max_shell_elements leaves no budget for pavilion glazing")

    def subtract(
        left: tuple[float, float, float], right: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        return (
            left[0] - right[0],
            left[1] - right[1],
            left[2] - right[2],
        )

    def norm(vector: tuple[float, float, float]) -> float:
        return math.sqrt(sum(value * value for value in vector))

    square_scale_pieces = 1
    for points in panels:
        horizontal_span = max(
            norm(subtract(points[1], points[0])),
            norm(subtract(points[2], points[3])),
        )
        vertical_span = max(
            norm(subtract(points[3], points[0])),
            norm(subtract(points[2], points[1])),
        )
        if horizontal_span <= 1.0e-12 or vertical_span <= 1.0e-12:
            raise ValueError("pavilion glazing shell has a degenerate edge")
        square_scale_pieces = max(
            square_scale_pieces,
            math.ceil(vertical_span / horizontal_span),
        )

    candidate_limit = min(max_shells // len(panels), square_scale_pieces)
    for piece_count in range(1, candidate_limit + 1):
        if all(
            _shell_shape_quality(
                _vertical_shell_piece(
                    points,
                    index / piece_count,
                    (index + 1) / piece_count,
                )
            )
            >= 0.1001
            for points in panels
            for index in range(piece_count)
        ):
            return tuple(
                _vertical_shell_piece(
                    points,
                    index / piece_count,
                    (index + 1) / piece_count,
                )
                for points in panels
                for index in range(piece_count)
            )
    raise ValueError(
        "pavilion glazing band cannot meet the R12 shell shape criterion within "
        "max_shell_elements"
    )


def _vertical_shell_piece(
    points: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ],
    lower_fraction: float,
    upper_fraction: float,
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]:
    def interpolate(
        start: tuple[float, float, float],
        end: tuple[float, float, float],
        fraction: float,
    ) -> tuple[float, float, float]:
        return (
            start[0] + (end[0] - start[0]) * fraction,
            start[1] + (end[1] - start[1]) * fraction,
            start[2] + (end[2] - start[2]) * fraction,
        )

    return (
        interpolate(points[0], points[3], lower_fraction),
        interpolate(points[1], points[2], lower_fraction),
        interpolate(points[1], points[2], upper_fraction),
        interpolate(points[0], points[3], upper_fraction),
    )


def _shell_shape_quality(
    points: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ],
) -> float:
    def subtract(
        left: tuple[float, float, float], right: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        return (
            left[0] - right[0],
            left[1] - right[1],
            left[2] - right[2],
        )

    def norm(vector: tuple[float, float, float]) -> float:
        return math.sqrt(sum(value * value for value in vector))

    def cross(
        left: tuple[float, float, float], right: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        return (
            left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0],
        )

    area = 0.5 * norm(
        cross(subtract(points[1], points[0]), subtract(points[2], points[0]))
    )
    area += 0.5 * norm(
        cross(subtract(points[2], points[0]), subtract(points[3], points[0]))
    )
    longest_diagonal = max(
        norm(subtract(points[2], points[0])),
        norm(subtract(points[3], points[1])),
    )
    if longest_diagonal <= 1.0e-12:
        return 0.0
    return area / (longest_diagonal * longest_diagonal)


def _merge_physical_profile_breaks(
    *,
    hard_bounds: tuple[float, float],
    priority_breaks: Sequence[float],
    regular_breaks: Sequence[float],
    minimum_span_m: float,
) -> tuple[float, ...]:
    """Prefer physical discontinuities when a regular bay would create a sliver."""

    start, end = (float(value) for value in hard_bounds)
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise ValueError("physical profile hard bounds must be finite and ordered")
    if not math.isfinite(minimum_span_m) or minimum_span_m <= 0.0:
        raise ValueError("minimum_span_m must be positive and finite")
    selected = [start, end]
    for value in sorted({float(row) for row in priority_breaks if start < row < end}):
        if min(abs(value - existing) for existing in selected) < minimum_span_m:
            continue
        selected.append(value)
    for value in sorted({float(row) for row in regular_breaks if start < row < end}):
        if min(abs(value - existing) for existing in selected) < minimum_span_m:
            continue
        selected.append(value)
    result = tuple(sorted(selected))
    if any(right - left < minimum_span_m for left, right in zip(result, result[1:])):
        raise ValueError("physical profile contains an unresolved sub-thickness sliver")
    return result


def _subway_pavilion_and_equipment_components(
    *,
    lanes: Mapping[str, Sequence[float]],
    width: float,
    floor: float,
    wall: float,
    upper_length: float,
    descent_length: float,
    pavilion_length: float,
    pavilion_width: float,
    pavilion_height: float,
    roof_base_z: float,
    roof_rise: float,
    rise: float,
    stair_members: Sequence[Sequence[float]],
    overhang: float,
    frame_size: float,
    glazing_thickness: float,
    roof_thickness: float,
    plinth_height: float,
    total_length: float,
    equipment_envelope: float,
    bay_count: int,
    shell_element_limit: int,
) -> list[JSONDict]:
    rows: list[JSONDict] = []
    shell_count = 0

    def append_shell(row: JSONDict) -> None:
        nonlocal shell_count
        if shell_count >= shell_element_limit:
            raise ValueError(
                "Shell elements proved lower bound exceeds max_shell_elements "
                "while resolving pavilion components"
            )
        rows.append(row)
        shell_count += 1

    del roof_base_z
    body_y0 = (width - pavilion_width) / 2.0
    body_y1 = body_y0 + pavilion_width
    frame_y0 = body_y0 + frame_size / 2.0
    frame_y1 = body_y1 - frame_size / 2.0
    glazing_y0 = body_y0 + glazing_thickness / 2.0
    glazing_y1 = body_y1 - glazing_thickness / 2.0
    frame_start = overhang
    frame_end = pavilion_length
    roof_start = 0.0
    roof_end = pavilion_length + overhang

    def walk_z(x: float) -> float:
        return _subway_route_walkable_elevation(
            x,
            upper_length,
            descent_length,
            floor,
            rise,
            stair_members,
        )

    def clearance_z(x: float) -> float:
        return _subway_route_clearance_elevation(
            x,
            upper_length,
            descent_length,
            floor,
            rise,
            stair_members,
        )

    def glazing_base_z(x: float) -> float:
        # The side glazing sits on the continuous pavilion curb, not on the
        # saw-tooth walking surface of the fixed stair lane.  Keeping this
        # edge continuous also prevents highly skewed transition quads.
        return _subway_walkable_elevation(
            x,
            upper_length,
            descent_length,
            floor,
            rise,
        ) + plinth_height

    frame_x_values = tuple(
        frame_start + (frame_end - frame_start) * index / bay_count
        for index in range(bay_count + 1)
    )
    stair_breaks = {
        float(bounds[index])
        for bounds in stair_members
        for index in (0, 3)
    }
    minimum_profile_span = max(frame_size, glazing_thickness, roof_thickness) / 2.0
    frame_profile_x_values = _merge_physical_profile_breaks(
        hard_bounds=(frame_start, frame_end),
        priority_breaks=tuple(stair_breaks),
        regular_breaks=frame_x_values,
        minimum_span_m=minimum_profile_span,
    )
    roof_facets = 8
    roof_x_values = _merge_physical_profile_breaks(
        hard_bounds=(roof_start, roof_end),
        priority_breaks=tuple(stair_breaks),
        regular_breaks=frame_x_values,
        minimum_span_m=minimum_profile_span,
    )
    roof_width = frame_y1 - frame_y0
    roof_y_values = tuple(
        frame_y0 + roof_width * index / roof_facets
        for index in range(roof_facets + 1)
    )
    roof_arc_values = tuple(
        roof_rise * (1.0 - (2.0 * index / roof_facets - 1.0) ** 2)
        for index in range(roof_facets + 1)
    )
    half_roof_thickness = roof_thickness / 2.0
    base_x_slopes = tuple(
        (clearance_z(x1) - clearance_z(x0)) / (x1 - x0)
        for x0, x1 in zip(roof_x_values, roof_x_values[1:])
    )
    base_y_slopes = tuple(
        (arc1 - arc0) / (y1 - y0)
        for arc0, arc1, y0, y1 in zip(
            roof_arc_values,
            roof_arc_values[1:],
            roof_y_values,
            roof_y_values[1:],
        )
    )
    roof_normal_projection_factor = max(
        math.sqrt(1.0 + x_slope * x_slope + y_slope * y_slope)
        for x_slope in base_x_slopes
        for y_slope in base_y_slopes
    )
    roof_vertical_half_envelope = (
        half_roof_thickness * roof_normal_projection_factor
    )
    x_compensation = [roof_vertical_half_envelope] * len(roof_x_values)
    y_compensation = [0.0] * len(roof_y_values)
    roof_x_indices = {
        value: index for index, value in enumerate(roof_x_values)
    }

    def roof_reference_z(x: float, y_index: int) -> float:
        x_index = roof_x_indices.get(x)
        if x_index is not None:
            x_offset = x_compensation[x_index]
        else:
            for interval, (x0, x1) in enumerate(
                zip(roof_x_values, roof_x_values[1:])
            ):
                if x0 < x < x1:
                    fraction = (x - x0) / (x1 - x0)
                    x_offset = (
                        x_compensation[interval] * (1.0 - fraction)
                        + x_compensation[interval + 1] * fraction
                    )
                    break
            else:
                raise ValueError("pavilion roof reference x is outside its grid")
        return (
            clearance_z(x)
            + pavilion_height
            + roof_arc_values[y_index]
            + x_offset
            + y_compensation[y_index]
        )

    def local_vertical_half_thickness(x_index: int, y_index: int) -> float:
        x0 = roof_x_values[x_index]
        x1 = roof_x_values[x_index + 1]
        y0 = roof_y_values[y_index]
        y1 = roof_y_values[y_index + 1]
        x_slope = (
            roof_reference_z(x1, y_index)
            - roof_reference_z(x0, y_index)
        ) / (x1 - x0)
        y_slope = (
            roof_reference_z(x0, y_index + 1)
            - roof_reference_z(x0, y_index)
        ) / (y1 - y0)
        return roof_thickness / 2.0 * math.sqrt(
            1.0 + x_slope * x_slope + y_slope * y_slope
        )

    left_edge_index = 0
    right_edge_index = roof_facets
    for x in frame_x_values:
        for y, y_index in (
            (frame_y0, left_edge_index),
            (frame_y1, right_edge_index),
        ):
            rows.append({"kind": "beam", "part_role": "pavilion_frame", "material_role": "structural_steel", "points_m": [[x, y, walk_z(x) + plinth_height], [x, y, roof_reference_z(x, y_index)]]})
    for y, y_index in (
        (frame_y0, left_edge_index),
        (frame_y1, right_edge_index),
    ):
        for x0, x1 in zip(
            frame_profile_x_values, frame_profile_x_values[1:]
        ):
            rows.append({"kind": "beam", "part_role": "pavilion_frame", "material_role": "structural_steel", "points_m": [[x0, y, roof_reference_z(x0, y_index)], [x1, y, roof_reference_z(x1, y_index)]]})
    glazing_panels: list[
        tuple[
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
        ]
    ] = []
    for x0, x1 in zip(
        frame_profile_x_values, frame_profile_x_values[1:]
    ):
        for y, y_index in (
            (glazing_y0, left_edge_index),
            (glazing_y1, right_edge_index),
        ):
            glazing_points = (
                (x0, y, glazing_base_z(x0)),
                (x1, y, glazing_base_z(x1)),
                (x1, y, roof_reference_z(x1, y_index)),
                (x0, y, roof_reference_z(x0, y_index)),
            )
            glazing_panels.append(glazing_points)
    reserved_non_glazing_shells = (
        (len(roof_x_values) - 1) * roof_facets
        + 1  # generic signage
        + 2 * 3  # one step band and two balustrades per escalator
    )
    glazing_budget = (
        shell_element_limit - shell_count - reserved_non_glazing_shells
    )
    for points in _quality_subdivided_glazing_band(
        tuple(glazing_panels),
        max_shells=glazing_budget,
    ):
        append_shell(
            {
                "kind": "shell",
                "part_role": "pavilion_glazing",
                "material_role": "glazing",
                "points_m": [list(point) for point in points],
            }
        )
    for x_index, (x0, x1) in enumerate(
        zip(roof_x_values, roof_x_values[1:])
    ):
        for index in range(roof_facets):
            y0 = roof_y_values[index]
            y1 = roof_y_values[index + 1]
            append_shell({"kind": "shell", "part_role": "pavilion_metal_roof", "material_role": "metal_roof", "physical_thickness_direction": "symmetric_shell_normal", "physical_normal_projection_factor": roof_normal_projection_factor, "physical_vertical_half_envelope_m": roof_vertical_half_envelope, "physical_vertical_half_thickness_m": local_vertical_half_thickness(x_index, index), "physical_clear_height_m": pavilion_height, "points_m": [[x0, y0, roof_reference_z(x0, index)], [x1, y0, roof_reference_z(x1, index)], [x1, y1, roof_reference_z(x1, index + 1)], [x0, y1, roof_reference_z(x0, index + 1)]]})
    sign_x = frame_start + wall / 2.0
    sign_x1 = min(frame_end, sign_x + width * 0.20)
    sign_top_z = min(
        roof_reference_z(sign_x, left_edge_index),
        roof_reference_z(sign_x1, left_edge_index),
    ) - 0.1
    append_shell({"kind": "shell", "part_role": "generic_signage", "material_role": "signage", "points_m": [[sign_x, body_y0, sign_top_z - 0.4], [sign_x1, body_y0, sign_top_z - 0.4], [sign_x1, body_y0, sign_top_z], [sign_x, body_y0, sign_top_z]]})
    for lane_id, role in (("B", "escalator_1"), ("C", "escalator_2")):
        lane = lanes[lane_id]
        upper_x = float(lane[0])
        lower_x = float(lane[3])
        y0 = float(lane[1]) + equipment_envelope
        y1 = float(lane[4]) - equipment_envelope
        upper_z = float(lane[5])
        truss_role = f"{role}_truss_guides"
        step_role = f"{role}_step_band"
        balustrade_role = f"{role}_balustrade"
        handrail_role = f"{role}_handrails"
        for y in (y0, y1):
            rows.append({"kind": "beam", "part_role": truss_role, "material_role": "structural_steel", "points_m": [[upper_x, y, upper_z], [lower_x, y, floor]]})
        append_shell({"kind": "shell", "part_role": step_role, "material_role": "escalator_equipment", "points_m": [[upper_x, y0, upper_z], [upper_x, y1, upper_z], [lower_x, y1, floor], [lower_x, y0, floor]]})
        balustrade_height = min(1.0, pavilion_height * 0.40)
        for y in (y0, y1):
            append_shell({"kind": "shell", "part_role": balustrade_role, "material_role": "escalator_balustrade", "points_m": [[upper_x, y, upper_z], [lower_x, y, floor], [lower_x, y, floor + balustrade_height], [upper_x, y, upper_z + balustrade_height]]})
            rows.append({"kind": "beam", "part_role": handrail_role, "material_role": "escalator_handrail", "points_m": [[upper_x, y, upper_z + balustrade_height], [lower_x, y, floor + balustrade_height]]})
    return rows


def _count_rc_definition_solids(
    definition: JSONDict,
    system_id: str,
    target: float,
    *,
    max_cells: int | None = None,
) -> int:
    normalized = normalize_building_definition(definition)
    topology = compile_spatial_topology(normalized)
    profile = normalized["structural_system"]
    assert isinstance(profile, dict)
    parameters = profile["parameters"]
    assert isinstance(parameters, dict)
    members = _build_member_boxes(
        normalized,
        topology,
        system_id,
        column_width=float(parameters["column_width_m"]),
        column_depth=float(parameters["column_depth_m"]),
        beam_width=float(parameters["beam_width_m"]),
        beam_depth=float(parameters["beam_depth_m"]),
        slab_thickness=float(parameters["slab_thickness_m"]),
        foundation_thickness=float(parameters["foundation_thickness_m"]),
    )
    return count_axis_aligned_union_cells(
        members,
        target,
        (box for _, box in topology.opening_regions),
        {
            "rc_foundation": 0,
            "rc_column": 1,
            "rc_shear_wall": 2,
            "rc_beam_x": 3,
            "rc_beam_y": 3,
            "rc_opening_jamb": 3,
            "rc_opening_header": 3,
            "rc_slab": 4,
        },
        max_cells=max_cells,
    )


def _count_rc_box_definition_solids(definition: JSONDict, target: float) -> int:
    normalized = normalize_building_definition(definition)
    topology = compile_spatial_topology(normalized)
    profile = normalized["structural_system"]
    assert isinstance(profile, dict)
    parameters = profile["parameters"]
    assert isinstance(parameters, dict)
    floor = float(parameters["floor_thickness_m"])
    wall = float(parameters["wall_thickness_m"])
    roof = float(parameters["roof_thickness_m"])
    envelope = topology.envelope
    members = (
        ("rc_box_floor", AxisAlignedBox(envelope.min_x, envelope.min_y, envelope.min_z, envelope.max_x, envelope.max_y, envelope.min_z + floor)),
        ("rc_box_roof", AxisAlignedBox(envelope.min_x, envelope.min_y, envelope.max_z - roof, envelope.max_x, envelope.max_y, envelope.max_z)),
        ("rc_box_wall", AxisAlignedBox(envelope.min_x, envelope.min_y, envelope.min_z + floor, envelope.min_x + wall, envelope.max_y, envelope.max_z - roof)),
        ("rc_box_wall", AxisAlignedBox(envelope.max_x - wall, envelope.min_y, envelope.min_z + floor, envelope.max_x, envelope.max_y, envelope.max_z - roof)),
        ("rc_box_wall", AxisAlignedBox(envelope.min_x + wall, envelope.min_y, envelope.min_z + floor, envelope.max_x - wall, envelope.min_y + wall, envelope.max_z - roof)),
        ("rc_box_wall", AxisAlignedBox(envelope.min_x + wall, envelope.max_y - wall, envelope.min_z + floor, envelope.max_x - wall, envelope.max_y, envelope.max_z - roof)),
    )
    return count_axis_aligned_union_cells(
        members,
        target,
        (box for _, box in topology.opening_regions),
        {"rc_box_floor": 0, "rc_box_wall": 1, "rc_box_roof": 2},
    )


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _bounded_integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not float(value).is_integer()
    ):
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")
    result = int(value)
    if not minimum <= result <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")
    return result


def _validate_supermarket_geometry(
    length: float,
    width: float,
    height: float,
    wall: float,
    entrance_width: float,
    entrance_height: float,
) -> None:
    if wall * 4.0 >= min(length, width) or wall * 2.0 >= height:
        raise ValueError("wall_thickness_m leaves no valid supermarket interior")
    partition_x = length * 2.0 / 3.0
    entrance_min = (length - entrance_width) / 2.0
    entrance_max = entrance_min + entrance_width
    if entrance_min < wall or entrance_max > partition_x:
        raise ValueError("entrance_width_m must fit the sales-hall front facade")
    if wall + entrance_height >= height - wall:
        raise ValueError("entrance_height_m must fit below the roof layer")


def _centered_interval(start: float, end: float, extent: float) -> tuple[float, float]:
    center = (start + end) / 2.0
    half = extent / 2.0
    return (center - half, center + half)


def _commercial_panels(
    *,
    length: float,
    width: float,
    height: float,
    wall: float,
    partition_x: float,
    partition_y: float,
    space_bounds: tuple[float, float, float, float, float, float],
    entrance: tuple[float, float, float, float],
    stock_door: tuple[float, float, float, float],
    service_door: tuple[float, float, float, float],
    stock_service_door: tuple[float, float, float, float],
    fidelity_profile: str,
    panel_target: float,
) -> list[JSONDict]:
    if fidelity_profile == "structural_core":
        return []
    thin = min(0.05, wall / 2.0)
    x_min, y_min, z_min, x_max, y_max, z_max = space_bounds
    rows: list[JSONDict] = []
    rows.extend(
        _split_panel(
            prefix="front_facade",
            fixed_axis=1,
            fixed_bounds=(0.0, thin),
            u_axis=0,
            u_bounds=(0.0, length),
            v_axis=2,
            v_bounds=(z_min, z_max),
            holes=(entrance,),
            plane_at="min",
            kind="facade",
            material_role="facade",
            mesh_size_m=panel_target,
        )
    )
    rows.extend(
        _split_panel(
            prefix="sales_back_partition",
            fixed_axis=0,
            fixed_bounds=(partition_x - thin / 2.0, partition_x + thin / 2.0),
            u_axis=1,
            u_bounds=(y_min, y_max),
            v_axis=2,
            v_bounds=(z_min, z_max),
            holes=(stock_door, service_door),
            plane_at="mid",
            kind="partition",
            material_role="nonstructural",
            mesh_size_m=panel_target,
        )
    )
    rows.extend(
        _split_panel(
            prefix="stock_service_partition",
            fixed_axis=1,
            fixed_bounds=(partition_y - thin / 2.0, partition_y + thin / 2.0),
            u_axis=0,
            u_bounds=(partition_x, x_max),
            v_axis=2,
            v_bounds=(z_min, z_max),
            holes=(stock_service_door,),
            plane_at="mid",
            kind="partition",
            material_role="nonstructural",
            mesh_size_m=panel_target,
        )
    )
    rows.extend(
        _split_panel(
            prefix="rear_facade",
            fixed_axis=1,
            fixed_bounds=(width - thin, width),
            u_axis=0,
            u_bounds=(0.0, length),
            v_axis=2,
            v_bounds=(z_min, z_max),
            holes=(),
            plane_at="max",
            kind="facade",
            material_role="facade",
            mesh_size_m=panel_target,
        )
    )
    for side, x_bounds, plane in (
        ("left", (0.0, thin), "min"),
        ("right", (length - thin, length), "max"),
    ):
        rows.extend(
            _split_panel(
                prefix=f"{side}_facade",
                fixed_axis=0,
                fixed_bounds=x_bounds,
                u_axis=1,
                u_bounds=(0.0, width),
                v_axis=2,
                v_bounds=(z_min, z_max),
                holes=(),
                plane_at=plane,
                kind="facade",
                material_role="facade",
                mesh_size_m=panel_target,
            )
        )
    if fidelity_profile == "research_detailed":
        screen_x = partition_x + (x_max - partition_x) * 0.65
        screen_y_margin = (y_max - partition_y) * 0.20
        rows.extend(
            _split_panel(
                prefix="research_service_glazing",
                fixed_axis=0,
                fixed_bounds=(screen_x - thin / 2.0, screen_x + thin / 2.0),
                u_axis=1,
                u_bounds=(partition_y + screen_y_margin, y_max - screen_y_margin),
                v_axis=2,
                v_bounds=(z_min + 0.40, min(z_max, z_min + 1.80)),
                holes=(),
                plane_at="mid",
                kind="glazing",
                material_role="glazing",
                mesh_size_m=panel_target,
            )
        )
    return rows


def _split_panel(
    *,
    prefix: str,
    fixed_axis: int,
    fixed_bounds: tuple[float, float],
    u_axis: int,
    u_bounds: tuple[float, float],
    v_axis: int,
    v_bounds: tuple[float, float],
    holes: Sequence[tuple[float, float, float, float]],
    plane_at: str,
    kind: str,
    material_role: str,
    mesh_size_m: float,
) -> list[JSONDict]:
    u_values = {u_bounds[0], u_bounds[1]}
    v_values = {v_bounds[0], v_bounds[1]}
    clipped_holes: list[tuple[float, float, float, float]] = []
    for u_min, v_min, u_max, v_max in holes:
        clipped = (
            max(u_bounds[0], u_min),
            max(v_bounds[0], v_min),
            min(u_bounds[1], u_max),
            min(v_bounds[1], v_max),
        )
        if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
            continue
        clipped_holes.append(clipped)
        u_values.update((clipped[0], clipped[2]))
        v_values.update((clipped[1], clipped[3]))
    us = sorted(u_values)
    vs = sorted(v_values)
    rows: list[JSONDict] = []
    for u_index, (u_min, u_max) in enumerate(zip(us, us[1:])):
        for v_index, (v_min, v_max) in enumerate(zip(vs, vs[1:])):
            u_mid = (u_min + u_max) / 2.0
            v_mid = (v_min + v_max) / 2.0
            if any(
                hole[0] < u_mid < hole[2] and hole[1] < v_mid < hole[3]
                for hole in clipped_holes
            ):
                continue
            bounds = [0.0] * 6
            bounds[fixed_axis] = fixed_bounds[0]
            bounds[fixed_axis + 3] = fixed_bounds[1]
            bounds[u_axis] = u_min
            bounds[u_axis + 3] = u_max
            bounds[v_axis] = v_min
            bounds[v_axis + 3] = v_max
            rows.append(
                {
                    "id": f"{prefix}_{u_index}_{v_index}",
                    "kind": kind,
                    "material_role": material_role,
                    "bounds_m": bounds,
                    "mesh_size_m": mesh_size_m,
                    "plane_at": plane_at,
                }
            )
    return rows


def _cell_count(dimensions: Sequence[float], target: float) -> int:
    result = 1
    for dimension in dimensions:
        result *= max(1, math.ceil(dimension / target))
    return result


def _enforce_template_family_lower_bounds(
    generation_options: Mapping[str, object],
    lower_bounds: Mapping[str, int],
) -> None:
    option_keys = {
        "solid_elements": "max_solid_elements",
        "beam_elements": "max_beam_elements",
        "shell_elements": "max_shell_elements",
        "node_count": "max_node_count",
        "total_elements": "max_total_elements",
    }
    labels = {
        "solid_elements": "Solid elements",
        "beam_elements": "Beam elements",
        "shell_elements": "Shell elements",
        "node_count": "Node count",
        "total_elements": "Total elements",
    }
    ordered_families = sorted(
        lower_bounds,
        key=lambda family: (
            option_keys[family] not in generation_options
            or option_keys[family] == "max_solid_elements"
        ),
    )
    for family in ordered_families:
        lower_bound = lower_bounds[family]
        option_key = option_keys[family]
        limit = int(
            generation_options.get(option_key, _TEMPLATE_FAMILY_LIMITS[option_key])
        )
        if lower_bound > limit:
            raise ValueError(
                f"{labels[family]} proved lower bound {lower_bound} exceeds limit {limit}"
            )


def _rc_union_grid_upper_bound(
    definition: JSONDict,
    target: float,
    *,
    max_cells: int | None = None,
) -> int:
    """Count the complete global union grid without allocating FE entities.

    The sparse mesher emits a subset of this Cartesian grid. Keeping every
    locally generated coordinate (including near-equal float variants) can
    only over-count the mesher's tolerance-merged axes, so this is a proven
    upper bound for the emitted Solid count.
    """

    normalized = normalize_building_definition(definition)
    topology = compile_spatial_topology(normalized)
    profile = normalized["structural_system"]
    assert isinstance(profile, dict)
    parameters = profile["parameters"]
    assert isinstance(parameters, dict)
    members = _build_member_boxes(
        normalized,
        topology,
        "rc_frame",
        column_width=float(parameters["column_width_m"]),
        column_depth=float(parameters["column_depth_m"]),
        beam_width=float(parameters["beam_width_m"]),
        beam_depth=float(parameters["beam_depth_m"]),
        slab_thickness=float(parameters["slab_thickness_m"]),
        foundation_thickness=float(parameters["foundation_thickness_m"]),
    )
    exclusions = tuple(box for _, box in topology.opening_regions)
    if max_cells is not None:
        for role, box in members:
            if role != "rc_foundation" or any(
                _positive_volume_overlap(box, exclusion) for exclusion in exclusions
            ):
                continue
            bounds = box.as_tuple()
            member_cells = _cell_count(
                tuple(bounds[axis + 3] - bounds[axis] for axis in range(3)),
                target,
            )
            if member_cells > max_cells:
                return max_cells + 1
    candidate_count = 0
    for _, box in members:
        bounds = box.as_tuple()
        candidate_count += sum(
            max(1, math.ceil((bounds[axis + 3] - bounds[axis]) / target)) + 1
            for axis in range(3)
        )
        if candidate_count > _MAX_TEMPLATE_AXIS_COORDINATES:
            raise ValueError(
                "axis coordinate allocation exceeds internal hard cap "
                f"{_MAX_TEMPLATE_AXIS_COORDINATES}"
            )
    overall = (
        min(box.min_x for _, box in members),
        min(box.min_y for _, box in members),
        min(box.min_z for _, box in members),
        max(box.max_x for _, box in members),
        max(box.max_y for _, box in members),
        max(box.max_z for _, box in members),
    )
    axes: list[set[float]] = [set(), set(), set()]
    for _, box in members:
        bounds = box.as_tuple()
        for axis in range(3):
            axes[axis].update(
                _axis_coordinates_for_upper_bound(
                    bounds[axis], bounds[axis + 3], target
                )
            )
    for exclusion in exclusions:
        bounds = exclusion.as_tuple()
        for axis in range(3):
            axes[axis].add(max(overall[axis], min(overall[axis + 3], bounds[axis])))
            axes[axis].add(
                max(overall[axis], min(overall[axis + 3], bounds[axis + 3]))
            )
    return math.prod(max(0, len(values) - 1) for values in axes)


def _axis_coordinates_for_upper_bound(
    start: float, end: float, target: float
) -> tuple[float, ...]:
    segment_count = max(1, math.ceil((end - start) / target))
    if segment_count + 1 > _MAX_TEMPLATE_AXIS_COORDINATES:
        raise ValueError(
            "axis coordinate allocation exceeds internal hard cap "
            f"{_MAX_TEMPLATE_AXIS_COORDINATES}"
        )
    spacing = (end - start) / segment_count
    return tuple(start + spacing * index for index in range(segment_count)) + (end,)


def _positive_volume_overlap(left: AxisAlignedBox, right: AxisAlignedBox) -> bool:
    left_bounds = left.as_tuple()
    right_bounds = right.as_tuple()
    return all(
        min(left_bounds[axis + 3], right_bounds[axis + 3])
        - max(left_bounds[axis], right_bounds[axis])
        > 1.0e-12
        for axis in range(3)
    )
