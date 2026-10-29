from __future__ import annotations

import math

from .config import JSONDict


TNT_CONSISTENCY_MODES = (
    "mass_priority_adjust_length",
    "geometry_priority",
    "mass_priority_adjust_density",
)
PHASE15_COUPLING_MODES = (
    "conforming_shared_nodes",
    "conforming_air_gap",
    "immersed_clis",
)
DEFAULT_PHASE15_COUPLING_MODE = "immersed_clis"
MIN_PHASE15_FSI_OVERLAP_LAYERS = 1
MAX_PHASE15_FSI_OVERLAP_LAYERS = 3
DEFAULT_PHASE15_FSI_OVERLAP_LAYERS = 2
MIN_PHASE15_AIR_GAP_CELLS = 3
DEFAULT_PHASE15_AIR_GAP_CELLS = 4
# Compatibility alias for callers that imported the former fixed setting.
PHASE15_FSI_OVERLAP_LAYERS = DEFAULT_PHASE15_FSI_OVERLAP_LAYERS


def default_phase15_a1_inputs() -> JSONDict:
    """Return the source-level A-1 inputs without silently resolving conflicts."""

    return {
        "case_id": "phase15_a1_kc_axisymmetric_blast",
        "unit_system": "m_s_kg_N_Pa",
        "target_radius_m": 1.05,
        "target_height_m": 1.4,
        "top_air_height_m": 0.3,
        "mesh_size_m": 0.006,
        "coupling_mode": DEFAULT_PHASE15_COUPLING_MODE,
        "fsi_overlap_layers": DEFAULT_PHASE15_FSI_OVERLAP_LAYERS,
        "borehole_radius_m": 0.073,
        "bottom_air_gap_m": 0.024,
        "tnt_mass_kg": 6.4,
        "tnt_radius_m": 0.049,
        "tnt_length_m": 0.55,
        "tnt_density_kg_per_m3": 1630.0,
        "tnt_density_range_kg_per_m3": [1550.0, 1650.0],
        "charge_bottom_depth_m": 0.86,
        "steel_thickness_m": 0.01,
        "concrete_fpc_pa": 133.5e6,
        "consistency_mode": "needs_confirmation",
        "source": {
            "geometry": "User-provided A-1 source images, July 2026",
            "material_model": "LS-DYNA R12 *MAT_CONCRETE_DAMAGE_REL3 automatic generation",
            "validation_status": "planned_demo_unvalidated",
        },
    }


def resolve_tnt_consistency(inputs: JSONDict) -> JSONDict:
    mass = _positive(inputs.get("tnt_mass_kg"), "tnt_mass_kg")
    radius = _positive(inputs.get("tnt_radius_m"), "tnt_radius_m")
    length = _positive(inputs.get("tnt_length_m"), "tnt_length_m")
    density = _positive(inputs.get("tnt_density_kg_per_m3"), "tnt_density_kg_per_m3")
    mode = str(inputs.get("consistency_mode", "needs_confirmation"))
    volume = math.pi * radius * radius * length
    geometric_mass = volume * density
    relative_error = (geometric_mass - mass) / mass
    common: JSONDict = {
        "requested_mass_kg": mass,
        "requested_radius_m": radius,
        "requested_length_m": length,
        "requested_density_kg_per_m3": density,
        "geometric_volume_m3": volume,
        "geometric_mass_kg": geometric_mass,
        "relative_mass_error": relative_error,
        "available_modes": list(TNT_CONSISTENCY_MODES),
    }
    if mode == "needs_confirmation":
        return {
            **common,
            "needs_confirmation": True,
            "reason": "TNT mass, cylindrical dimensions, and density are inconsistent",
        }
    if mode not in TNT_CONSISTENCY_MODES:
        raise ValueError(f"unsupported consistency_mode: {mode}")

    effective_length = length
    effective_density = density
    effective_mass = geometric_mass
    if mode == "mass_priority_adjust_length":
        effective_length = mass / (math.pi * radius * radius * density)
        effective_mass = mass
    elif mode == "mass_priority_adjust_density":
        effective_density = mass / volume
        effective_mass = mass

    density_range = inputs.get("tnt_density_range_kg_per_m3", [1550.0, 1650.0])
    density_min = _positive(density_range[0], "tnt_density_range_kg_per_m3[0]")
    density_max = _positive(density_range[1], "tnt_density_range_kg_per_m3[1]")
    outside_density_range = not density_min <= effective_density <= density_max

    result = {
        **common,
        "needs_confirmation": outside_density_range,
        "effective_radius_m": radius,
        "effective_length_m": effective_length,
        "effective_density_kg_per_m3": effective_density,
        "effective_mass_kg": effective_mass,
        "provenance": {
            "decision": mode,
            "requested_values_preserved": mode == "geometry_priority",
            "validation_status": "user_decision_required_before_generation",
        },
    }
    if outside_density_range:
        result["reason"] = "effective TNT density is outside the controlled range"
        result["controlled_density_range_kg_per_m3"] = [density_min, density_max]
    return result


def resolve_phase15_air_gap(inputs: JSONDict) -> JSONDict:
    """Resolve explicit side and bottom air-gap dimensions."""

    mesh_size = _positive(inputs.get("mesh_size_m"), "mesh_size_m")
    charge_radius = _positive(inputs.get("tnt_radius_m"), "tnt_radius_m")
    borehole_radius = _positive(
        inputs.get(
            "borehole_radius_m",
            charge_radius + DEFAULT_PHASE15_AIR_GAP_CELLS * mesh_size,
        ),
        "borehole_radius_m",
    )
    bottom_air_gap = _positive(
        inputs.get(
            "bottom_air_gap_m",
            DEFAULT_PHASE15_AIR_GAP_CELLS * mesh_size,
        ),
        "bottom_air_gap_m",
    )
    side_air_gap = borehole_radius - charge_radius
    if side_air_gap <= 0.0:
        raise ValueError("borehole_radius_m must be greater than the resolved TNT radius")
    return {
        "borehole_radius_m": borehole_radius,
        "side_air_gap_m": side_air_gap,
        "bottom_air_gap_m": bottom_air_gap,
        "minimum_gap_cells": MIN_PHASE15_AIR_GAP_CELLS,
        "default_gap_cells": DEFAULT_PHASE15_AIR_GAP_CELLS,
    }


def build_axisymmetric_grid(radius_m: float, height_m: float, mesh_size_m: float) -> JSONDict:
    radius = _positive(radius_m, "radius_m")
    height = _positive(height_m, "height_m")
    mesh_size = _positive(mesh_size_m, "mesh_size_m")
    radial_cells = max(1, round(radius / mesh_size))
    axial_cells = max(1, round(height / mesh_size))
    radial_coordinates = [radius * index / radial_cells for index in range(radial_cells + 1)]
    axial_coordinates = [height * index / axial_cells for index in range(axial_cells + 1)]
    revolved_volume = 0.0
    for radial_index in range(radial_cells):
        inner = radial_coordinates[radial_index]
        outer = radial_coordinates[radial_index + 1]
        annular_area = math.pi * (outer * outer - inner * inner)
        for axial_index in range(axial_cells):
            dz = axial_coordinates[axial_index + 1] - axial_coordinates[axial_index]
            revolved_volume += annular_area * dz
    return {
        "coordinate_system": "axisymmetric_r_z",
        "axis_m": 0.0,
        "radial_coordinates_m": radial_coordinates,
        "axial_coordinates_m": axial_coordinates,
        "radial_cells": radial_cells,
        "axial_cells": axial_cells,
        "node_count": (radial_cells + 1) * (axial_cells + 1),
        "element_count": radial_cells * axial_cells,
        "revolved_volume_m3": revolved_volume,
        "section_formulation": {
            "ale_high_explosive": 14,
            "lagrangian_structure": 15,
            "status": "requires_r12_import_and_solver_smoke",
        },
    }


def compile_axisymmetric_quad_mesh(
    radius_m: float,
    height_m: float,
    mesh_size_m: float,
    *,
    part_id: int = 1,
    node_id_start: int = 1,
    element_id_start: int = 1,
) -> JSONDict:
    grid = build_axisymmetric_grid(radius_m, height_m, mesh_size_m)
    radial = grid["radial_coordinates_m"]
    axial = grid["axial_coordinates_m"]
    nodes: list[list[float | int]] = []
    node_ids: dict[tuple[int, int], int] = {}
    next_node_id = int(node_id_start)
    for axial_index, axial_coordinate in enumerate(axial):
        for radial_index, radial_coordinate in enumerate(radial):
            node_ids[(radial_index, axial_index)] = next_node_id
            nodes.append([next_node_id, radial_coordinate, axial_coordinate, 0.0])
            next_node_id += 1

    elements: list[list[int]] = []
    next_element_id = int(element_id_start)
    for axial_index in range(int(grid["axial_cells"])):
        for radial_index in range(int(grid["radial_cells"])):
            n1 = node_ids[(radial_index, axial_index)]
            n2 = node_ids[(radial_index + 1, axial_index)]
            n3 = node_ids[(radial_index + 1, axial_index + 1)]
            n4 = node_ids[(radial_index, axial_index + 1)]
            elements.append([next_element_id, int(part_id), n1, n2, n3, n4])
            next_element_id += 1

    last_radial = int(grid["radial_cells"])
    last_axial = int(grid["axial_cells"])
    boundaries = {
        "axis": [node_ids[(0, axial_index)] for axial_index in range(last_axial + 1)],
        "outer_radius": [node_ids[(last_radial, axial_index)] for axial_index in range(last_axial + 1)],
        "bottom": [node_ids[(radial_index, 0)] for radial_index in range(last_radial + 1)],
        "top": [node_ids[(radial_index, last_axial)] for radial_index in range(last_radial + 1)],
    }
    return {
        "coordinate_system": "axisymmetric_r_z",
        "nodes": nodes,
        "elements": elements,
        "boundaries": boundaries,
        "next_node_id": next_node_id,
        "next_element_id": next_element_id,
        "grid": grid,
    }


def derive_phase15_a1_geometry(inputs: JSONDict) -> JSONDict:
    """Resolve the A-1 source dimensions into the internal r-z convention."""

    consistency = resolve_tnt_consistency(inputs)
    if bool(consistency["needs_confirmation"]):
        raise ValueError("TNT consistency decision is required before compiling A-1 geometry")

    target_radius = _positive(inputs.get("target_radius_m"), "target_radius_m")
    target_height = _positive(inputs.get("target_height_m"), "target_height_m")
    top_air_height = _positive(inputs.get("top_air_height_m"), "top_air_height_m")
    steel_thickness = _positive(inputs.get("steel_thickness_m"), "steel_thickness_m")
    charge_bottom_depth = _positive(
        inputs.get("charge_bottom_depth_m"), "charge_bottom_depth_m"
    )
    charge_radius = _positive(consistency.get("effective_radius_m"), "effective_radius_m")
    charge_length = _positive(consistency.get("effective_length_m"), "effective_length_m")
    if charge_radius >= target_radius:
        raise ValueError("charge radius must be smaller than target radius")
    if charge_bottom_depth >= target_height:
        raise ValueError("charge bottom depth must lie inside the concrete target")
    charge_top_depth = charge_bottom_depth - charge_length
    if charge_top_depth <= 0.0:
        raise ValueError("charge top must remain below the concrete target top")

    charge_bottom_z = target_height - charge_bottom_depth
    charge_top_z = charge_bottom_z + charge_length
    return {
        "coordinate_system": "axisymmetric_r_z",
        "depth_origin": "target_top_positive_down",
        "z_origin": "target_bottom_positive_up",
        "axis_radius_m": 0.0,
        "target_radius_m": target_radius,
        "target_height_m": target_height,
        "target_top_z_m": target_height,
        "air_top_z_m": target_height + top_air_height,
        "charge_radius_m": charge_radius,
        "charge_length_m": charge_length,
        "charge_bottom_depth_m": charge_bottom_depth,
        "charge_top_depth_m": charge_top_depth,
        "charge_bottom_z_m": charge_bottom_z,
        "charge_top_z_m": charge_top_z,
        "steel_thickness_m": steel_thickness,
        "steel_inner_radius_m": target_radius,
        "steel_outer_radius_m": target_radius + steel_thickness,
        "tnt_effective_density_kg_per_m3": consistency["effective_density_kg_per_m3"],
        "tnt_effective_mass_kg": consistency["effective_mass_kg"],
        "provenance": {
            "tnt_consistency_decision": consistency["provenance"]["decision"],
            "source_case": inputs.get("case_id", "phase15_a1_kc_axisymmetric_blast"),
            "validation_status": "phase15_geometry_frozen_static_only",
        },
    }


def compile_phase15_a1_mesh_plan(inputs: JSONDict) -> JSONDict:
    """Compile A-1 r-z regions for the selected ALE/concrete interface."""

    geometry = derive_phase15_a1_geometry(inputs)
    mesh_size = _positive(inputs.get("mesh_size_m"), "mesh_size_m")
    coupling_mode = resolve_phase15_coupling_mode(inputs)
    overlap_layers = (
        resolve_phase15_fsi_overlap_layers(inputs)
        if coupling_mode == "immersed_clis"
        else 0
    )
    radius = float(geometry["target_radius_m"])
    target_top = float(geometry["target_top_z_m"])
    air_top = float(geometry["air_top_z_m"])
    charge_radius = float(geometry["charge_radius_m"])
    charge_bottom = float(geometry["charge_bottom_z_m"])
    charge_top = float(geometry["charge_top_z_m"])
    steel_outer = float(geometry["steel_outer_radius_m"])
    phase15_air_gap: JSONDict | None = None
    cavity_radius = charge_radius
    cavity_bottom = charge_bottom
    if coupling_mode == "conforming_air_gap":
        phase15_air_gap = resolve_phase15_air_gap(inputs)
        cavity_radius = float(phase15_air_gap["borehole_radius_m"])
        cavity_bottom = charge_bottom - float(phase15_air_gap["bottom_air_gap_m"])
        if cavity_bottom <= 0.0:
            raise ValueError("bottom_air_gap_m places the borehole bottom outside the concrete")
        geometry = {
            **geometry,
            "borehole_radius_m": cavity_radius,
            "borehole_bottom_z_m": cavity_bottom,
            "side_air_gap_m": float(phase15_air_gap["side_air_gap_m"]),
            "bottom_air_gap_m": float(phase15_air_gap["bottom_air_gap_m"]),
        }

    concrete_r = _segmented_coordinates(
        [0.0, charge_radius, cavity_radius, radius],
        mesh_size,
    )
    concrete_z = _segmented_coordinates(
        [0.0, cavity_bottom, charge_bottom, charge_top, target_top],
        mesh_size,
    )
    overlap_depth = overlap_layers * mesh_size
    if coupling_mode == "immersed_clis":
        overlap_radius = min(radius, charge_radius + overlap_depth)
        overlap_bottom = max(0.0, charge_bottom - overlap_depth)
        overlap_top = max(charge_top, target_top - overlap_depth)
        air_z = sorted(
            {
                *(
                    coordinate
                    for coordinate in concrete_z
                    if coordinate >= overlap_bottom - 1.0e-12
                ),
                *_segmented_coordinates([target_top, air_top], mesh_size),
            }
        )
        air_r = list(concrete_r)
    elif coupling_mode == "conforming_air_gap":
        overlap_radius = cavity_radius
        overlap_top = target_top
        air_r = _segmented_coordinates(
            [0.0, charge_radius, cavity_radius, radius],
            mesh_size,
        )
        air_z = _segmented_coordinates(
            [cavity_bottom, charge_bottom, charge_top, target_top, air_top],
            mesh_size,
        )
        side_cells = sum(
            1
            for start, end in zip(air_r, air_r[1:])
            if start >= charge_radius - 1.0e-12
            and end <= cavity_radius + 1.0e-12
        )
        bottom_cells = sum(
            1
            for start, end in zip(air_z, air_z[1:])
            if start >= cavity_bottom - 1.0e-12
            and end <= charge_bottom + 1.0e-12
        )
        phase15_air_gap.update(
            {
                "side_air_gap_cells": side_cells,
                "bottom_air_gap_cells": bottom_cells,
            }
        )
        if (
            side_cells < MIN_PHASE15_AIR_GAP_CELLS
            or bottom_cells < MIN_PHASE15_AIR_GAP_CELLS
        ):
            raise ValueError(
                "conforming_air_gap requires at least 3 actual ALE cells in "
                "both side and bottom air gaps"
            )
    else:
        overlap_radius = charge_radius
        overlap_top = target_top
        air_z = _segmented_coordinates([charge_top, target_top], mesh_size)
        air_r = list(concrete_r)
    tnt_r = _segmented_coordinates([0.0, charge_radius], mesh_size)
    tnt_z = _segmented_coordinates([charge_bottom, charge_top], mesh_size)
    steel_r = _segmented_coordinates([radius, steel_outer], mesh_size)
    steel_z = _segmented_coordinates(
        [0.0, cavity_bottom, charge_bottom, charge_top, target_top], mesh_size
    )

    next_node = 1
    next_element = 1
    regions: dict[str, JSONDict] = {}

    concrete = _compile_axisymmetric_region(
        "concrete",
        concrete_r,
        concrete_z,
        lambda r, z: not (r < cavity_radius and z > cavity_bottom),
        part_id=3,
        section_formulation=15,
        node_id_start=next_node,
        element_id_start=next_element,
    )
    _set_region_boundaries(
        concrete,
        {
            "axis_below_charge": lambda r, z: _close(r, 0.0) and z <= cavity_bottom,
            "charge_bottom": lambda r, z: (
                coupling_mode != "conforming_air_gap"
                and _close(z, charge_bottom)
                and r <= charge_radius
            ),
            "charge_side": lambda r, z: (
                coupling_mode != "conforming_air_gap"
                and _close(r, charge_radius)
                and charge_bottom <= z <= charge_top
            ),
            "borehole_bottom": lambda r, z: (
                coupling_mode == "conforming_air_gap"
                and _close(z, cavity_bottom)
                and r <= cavity_radius
            ),
            "borehole_side": lambda r, z: (
                _close(r, cavity_radius)
                and (
                    cavity_bottom <= z <= target_top
                    if coupling_mode == "conforming_air_gap"
                    else charge_top <= z <= target_top
                )
            ),
            "top_surface": lambda r, z: _close(z, target_top) and r >= cavity_radius,
            "outer_surface": lambda r, z: _close(r, radius),
            "bottom_free": lambda r, z: _close(z, 0.0),
        },
    )
    regions["concrete"] = concrete
    next_node = int(concrete["next_node_id"])
    next_element = int(concrete["next_element_id"])

    tnt = _compile_axisymmetric_region(
        "tnt",
        tnt_r,
        tnt_z,
        lambda _r, _z: True,
        part_id=2,
        section_formulation=14,
        node_id_start=next_node,
        element_id_start=next_element,
    )
    _set_region_boundaries(
        tnt,
        {
            "axis": lambda r, z: _close(r, 0.0),
            "side": lambda r, z: _close(r, charge_radius),
            "bottom": lambda r, z: _close(z, charge_bottom),
            "top": lambda r, z: _close(z, charge_top),
        },
    )
    regions["tnt"] = tnt
    next_node = int(tnt["next_node_id"])
    next_element = int(tnt["next_element_id"])

    def include_air(radius_value: float, axial_value: float) -> bool:
        if coupling_mode == "immersed_clis":
            return (
                (
                    radius_value < overlap_radius
                    and axial_value < target_top
                )
                or axial_value > overlap_top
            ) and not (
                radius_value < charge_radius
                and charge_bottom < axial_value < charge_top
            )
        if coupling_mode == "conforming_air_gap":
            return (
                radius_value < cavity_radius
                or axial_value > target_top
            ) and not (
                radius_value < charge_radius
                and charge_bottom < axial_value < charge_top
            )
        return (
            radius_value < charge_radius
            and charge_top < axial_value < target_top
        )

    air = _compile_axisymmetric_region(
        "air",
        air_r,
        air_z,
        include_air,
        part_id=1,
        section_formulation=14,
        node_id_start=next_node,
        element_id_start=next_element,
    )
    _set_region_boundaries(
        air,
        {
            "axis": lambda r, z: _close(r, 0.0),
            "charge_bottom": lambda r, z: (
                coupling_mode == "conforming_air_gap"
                and _close(z, charge_bottom)
                and r <= charge_radius
            ),
            "charge_side": lambda r, z: (
                coupling_mode == "conforming_air_gap"
                and _close(r, charge_radius)
                and charge_bottom <= z <= charge_top
            ),
            "charge_top": lambda r, z: _close(z, charge_top) and r <= charge_radius,
            "borehole_bottom": lambda r, z: (
                coupling_mode == "conforming_air_gap"
                and _close(z, cavity_bottom)
                and r <= cavity_radius
            ),
            "borehole_side": lambda r, z: (
                _close(r, cavity_radius)
                and (
                    cavity_bottom <= z <= target_top
                    if coupling_mode == "conforming_air_gap"
                    else charge_top <= z <= target_top
                )
            ),
            "target_top": lambda r, z: _close(z, target_top) and r >= cavity_radius,
            "outer_nonreflecting": lambda r, z: (
                _close(r, radius)
                and z >= target_top
            ),
            "top_nonreflecting": lambda r, z: _close(z, air_top),
            "opening_nonreflecting": lambda r, z: (
                coupling_mode != "conforming_air_gap"
                and _close(z, target_top)
                and r <= cavity_radius
            ),
        },
    )
    regions["air"] = air
    next_node = int(air["next_node_id"])
    next_element = int(air["next_element_id"])

    steel = _compile_axisymmetric_region(
        "steel_hoop",
        steel_r,
        steel_z,
        lambda _r, _z: True,
        part_id=4,
        section_formulation=15,
        node_id_start=next_node,
        element_id_start=next_element,
    )
    _set_region_boundaries(
        steel,
        {
            "inner_surface": lambda r, z: _close(r, radius),
            "outer_surface": lambda r, z: _close(r, steel_outer),
            "bottom": lambda r, z: _close(z, 0.0),
            "top": lambda r, z: _close(z, target_top),
        },
    )
    regions["steel_hoop"] = steel

    if coupling_mode == "conforming_air_gap":
        tnt_to_concrete: JSONDict = {
            "first_region": "tnt",
            "second_region": "concrete",
            "first_boundaries": ["side", "bottom"],
            "second_boundaries": [],
            "first_node_count": len(
                set(tnt["boundaries"]["side"]) | set(tnt["boundaries"]["bottom"])
            ),
            "second_node_count": 0,
            "matched_node_count": 0,
            "coordinates_match": True,
            "active": False,
            "physical_meaning": "separated_by_ale_air_gap",
        }
        tnt_to_air = _interface_match(
            tnt,
            ["side", "bottom", "top"],
            air,
            ["charge_side", "charge_bottom", "charge_top"],
        )
        air_to_concrete = _interface_match(
            air,
            ["borehole_bottom", "borehole_side", "target_top"],
            concrete,
            ["borehole_bottom", "borehole_side", "top_surface"],
        )
    else:
        tnt_to_concrete = _interface_match(
            tnt,
            ["side", "bottom"],
            concrete,
            ["charge_side", "charge_bottom"],
        )
        tnt_to_air = _interface_match(tnt, ["top"], air, ["charge_top"])
        air_to_concrete = _interface_match(
            air,
            (
                ["borehole_side", "target_top"]
                if coupling_mode == "immersed_clis"
                else ["borehole_side"]
            ),
            concrete,
            (
                ["borehole_side", "top_surface"]
                if coupling_mode == "immersed_clis"
                else ["borehole_side"]
            ),
        )
    interfaces = {
        "tnt_to_concrete": tnt_to_concrete,
        "tnt_to_air": tnt_to_air,
        "air_to_concrete": air_to_concrete,
        "concrete_to_steel": _interface_match(
            concrete, ["outer_surface"], steel, ["inner_surface"]
        ),
    }
    plan: JSONDict = {
        "case_id": inputs.get("case_id", "phase15_a1_kc_axisymmetric_blast"),
        "status": "phase15_1_static_mesh_only",
        "coordinate_system": "axisymmetric_r_z",
        "mesh_size_m": mesh_size,
        "fsi_coupling": {
            "mode": coupling_mode,
            "solver_qualification": (
                "experimental_unqualified"
                if coupling_mode in {"conforming_shared_nodes", "conforming_air_gap"}
                else "controlled_reference"
            ),
            "production_default": coupling_mode == DEFAULT_PHASE15_COUPLING_MODE,
            "known_limitation": (
                "LS-DYNA R12 negative volume at the shared bore-wall interface; "
                "full-duration wave-transfer acceptance has not passed"
                if coupling_mode == "conforming_shared_nodes"
                else (
                    "zero-overlap air-gap transfer has not completed real solver qualification"
                    if coupling_mode == "conforming_air_gap"
                    else None
                )
            ),
            "overlap_layers": overlap_layers,
            "overlap_depth_m": overlap_depth,
            "physical_meaning": (
                "computational_overlap_not_physical_air_thickness"
                if coupling_mode == "immersed_clis"
                else (
                    "zero_overlap_air_gap_shared_node_interface"
                    if coupling_mode == "conforming_air_gap"
                    else "zero_overlap_shared_node_interface"
                )
            ),
            "allowed_overlap_layers": (
                [
                    MIN_PHASE15_FSI_OVERLAP_LAYERS,
                    MAX_PHASE15_FSI_OVERLAP_LAYERS,
                ]
                if coupling_mode == "immersed_clis"
                else [0, 0]
            ),
        },
        "geometry": geometry,
        "phase15_air_gap": phase15_air_gap,
        "regions": regions,
        "interfaces": interfaces,
        "next_node_id": int(steel["next_node_id"]),
        "next_element_id": int(steel["next_element_id"]),
    }
    return plan


def summarize_phase15_a1_mesh_plan(plan: JSONDict) -> JSONDict:
    issues = validate_phase15_a1_mesh_plan(plan)
    regions = plan.get("regions", {})
    region_summary: JSONDict = {}
    total_nodes = 0
    total_elements = 0
    for name, raw in regions.items():
        if not isinstance(raw, dict):
            continue
        node_count = len(raw.get("nodes", []))
        element_count = len(raw.get("elements", []))
        total_nodes += node_count
        total_elements += element_count
        region_summary[str(name)] = {
            "part_id": raw.get("part_id"),
            "section_formulation": raw.get("section_formulation"),
            "node_count": node_count,
            "element_count": element_count,
            "boundary_names": sorted(raw.get("boundaries", {})),
        }
    return {
        "status": plan.get("status"),
        "coordinate_system": plan.get("coordinate_system"),
        "mesh_size_m": plan.get("mesh_size_m"),
        "fsi_coupling": plan.get("fsi_coupling", {}),
        "phase15_air_gap": plan.get("phase15_air_gap"),
        "total_node_count": total_nodes,
        "total_element_count": total_elements,
        "regions": region_summary,
        "interfaces": plan.get("interfaces", {}),
        "quality_issue_count": len(issues),
        "quality_issues": issues,
    }


def validate_phase15_a1_mesh_plan(plan: JSONDict) -> list[JSONDict]:
    issues: list[JSONDict] = []
    mesh_size = plan.get("mesh_size_m")
    fsi_coupling = plan.get("fsi_coupling")
    if not isinstance(fsi_coupling, dict):
        issues.append({"id": "fsi_coupling_configuration_missing"})
    else:
        coupling_mode = fsi_coupling.get("mode")
        overlap_layers = fsi_coupling.get("overlap_layers")
        overlap_depth = fsi_coupling.get("overlap_depth_m")
        if coupling_mode in {"conforming_shared_nodes", "conforming_air_gap"}:
            if overlap_layers != 0 or overlap_depth != 0.0:
                issues.append(
                    {
                        "id": "conforming_overlap_must_be_zero",
                        "overlap_layers": overlap_layers,
                        "overlap_depth_m": overlap_depth,
                    }
                )
            if coupling_mode == "conforming_air_gap":
                air_gap = plan.get("phase15_air_gap")
                if not isinstance(air_gap, dict):
                    issues.append({"id": "conforming_air_gap_missing"})
                else:
                    for field in ("side_air_gap_cells", "bottom_air_gap_cells"):
                        value = air_gap.get(field)
                        if (
                            isinstance(value, bool)
                            or not isinstance(value, int)
                            or value < MIN_PHASE15_AIR_GAP_CELLS
                        ):
                            issues.append(
                                {
                                    "id": "conforming_air_gap_cells_insufficient",
                                    "field": field,
                                    "value": value,
                                }
                            )
        elif coupling_mode == "immersed_clis":
            if (
                isinstance(overlap_layers, bool)
                or not isinstance(overlap_layers, int)
                or not MIN_PHASE15_FSI_OVERLAP_LAYERS
                <= overlap_layers
                <= MAX_PHASE15_FSI_OVERLAP_LAYERS
            ):
                issues.append(
                    {"id": "fsi_overlap_layers_invalid", "value": overlap_layers}
                )
            else:
                try:
                    expected_depth = float(mesh_size) * overlap_layers
                    actual_depth = float(overlap_depth)
                except (TypeError, ValueError):
                    issues.append({"id": "fsi_overlap_depth_invalid"})
                else:
                    if not math.isfinite(actual_depth) or not math.isclose(
                        actual_depth,
                        expected_depth,
                        rel_tol=0.0,
                        abs_tol=1.0e-12,
                    ):
                        issues.append(
                            {
                                "id": "fsi_overlap_depth_mismatch",
                                "expected_m": expected_depth,
                                "actual_m": overlap_depth,
                            }
                        )
        else:
            issues.append({"id": "coupling_mode_invalid", "value": coupling_mode})
    regions = plan.get("regions")
    if not isinstance(regions, dict):
        return [{"id": "regions_missing", "message": "mesh plan regions must be an object"}]
    node_ids: set[int] = set()
    element_ids: set[int] = set()
    for region_name, raw in regions.items():
        if not isinstance(raw, dict):
            issues.append({"id": "region_invalid", "region": region_name})
            continue
        nodes = raw.get("nodes", [])
        elements = raw.get("elements", [])
        if not nodes or not elements:
            issues.append({"id": "region_empty", "region": region_name})
            continue
        local_nodes = {int(node[0]): node[1:] for node in nodes}
        duplicates = node_ids.intersection(local_nodes)
        if duplicates:
            issues.append({"id": "duplicate_node_id", "region": region_name})
        node_ids.update(local_nodes)
        if any(float(coordinates[0]) < -1.0e-12 for coordinates in local_nodes.values()):
            issues.append({"id": "negative_radius", "region": region_name})
        for element in elements:
            element_id = int(element[0])
            if element_id in element_ids:
                issues.append({"id": "duplicate_element_id", "region": region_name})
            element_ids.add(element_id)
            try:
                coordinates = [local_nodes[int(node_id)] for node_id in element[2:6]]
            except KeyError:
                issues.append({"id": "missing_element_node", "region": region_name})
                continue
            area = 0.5 * sum(
                float(coordinates[index][0]) * float(coordinates[(index + 1) % 4][1])
                - float(coordinates[(index + 1) % 4][0]) * float(coordinates[index][1])
                for index in range(4)
            )
            if not math.isfinite(area) or area <= 0.0:
                issues.append(
                    {"id": "nonpositive_element_area", "region": region_name, "element_id": element_id}
                )
    interfaces = plan.get("interfaces", {})
    if not isinstance(interfaces, dict):
        issues.append({"id": "interfaces_missing"})
    else:
        for interface_name, raw in interfaces.items():
            if (
                not isinstance(raw, dict)
                or (
                    raw.get("active", True) is not False
                    and not bool(raw.get("coordinates_match"))
                )
            ):
                issues.append({"id": "interface_mismatch", "interface": interface_name})
    return issues


def _segmented_coordinates(breakpoints: list[float], mesh_size: float) -> list[float]:
    points = sorted(set(float(value) for value in breakpoints))
    if len(points) < 2:
        raise ValueError("axisymmetric coordinate breakpoints require at least two values")
    coordinates = [points[0]]
    for start, end in zip(points, points[1:]):
        if end <= start:
            raise ValueError("axisymmetric coordinate breakpoints must be strictly increasing")
        count = max(1, math.ceil((end - start) / mesh_size - 1.0e-12))
        coordinates.extend(start + (end - start) * index / count for index in range(1, count + 1))
    return coordinates


def _compile_axisymmetric_region(
    name: str,
    radial: list[float],
    axial: list[float],
    selector: object,
    *,
    part_id: int,
    section_formulation: int,
    node_id_start: int,
    element_id_start: int,
) -> JSONDict:
    nodes: list[list[float | int]] = []
    node_ids: dict[tuple[int, int], int] = {}
    elements: list[list[int]] = []
    next_node = int(node_id_start)
    next_element = int(element_id_start)

    def node_id(radial_index: int, axial_index: int) -> int:
        nonlocal next_node
        key = (radial_index, axial_index)
        if key not in node_ids:
            node_ids[key] = next_node
            nodes.append([next_node, radial[radial_index], axial[axial_index], 0.0])
            next_node += 1
        return node_ids[key]

    for axial_index in range(len(axial) - 1):
        center_z = 0.5 * (axial[axial_index] + axial[axial_index + 1])
        for radial_index in range(len(radial) - 1):
            center_r = 0.5 * (radial[radial_index] + radial[radial_index + 1])
            if not selector(center_r, center_z):  # type: ignore[operator]
                continue
            n1 = node_id(radial_index, axial_index)
            n2 = node_id(radial_index + 1, axial_index)
            n3 = node_id(radial_index + 1, axial_index + 1)
            n4 = node_id(radial_index, axial_index + 1)
            elements.append([next_element, int(part_id), n1, n2, n3, n4])
            next_element += 1
    return {
        "name": name,
        "part_id": int(part_id),
        "section_formulation": int(section_formulation),
        "nodes": nodes,
        "elements": elements,
        "boundaries": {},
        "next_node_id": next_node,
        "next_element_id": next_element,
    }


def _set_region_boundaries(region: JSONDict, selectors: dict[str, object]) -> None:
    boundaries: JSONDict = {}
    for name, selector in selectors.items():
        boundaries[name] = [
            int(node[0])
            for node in region["nodes"]
            if selector(float(node[1]), float(node[2]))  # type: ignore[operator]
        ]
    region["boundaries"] = boundaries


def _interface_match(
    first: JSONDict,
    first_boundaries: list[str],
    second: JSONDict,
    second_boundaries: list[str],
) -> JSONDict:
    first_coordinates = _boundary_coordinates(first, first_boundaries)
    second_coordinates = _boundary_coordinates(second, second_boundaries)
    return {
        "first_region": first["name"],
        "second_region": second["name"],
        "first_boundaries": first_boundaries,
        "second_boundaries": second_boundaries,
        "first_node_count": len(first_coordinates),
        "second_node_count": len(second_coordinates),
        "matched_node_count": len(first_coordinates.intersection(second_coordinates)),
        "coordinates_match": first_coordinates == second_coordinates,
    }


def _boundary_coordinates(region: JSONDict, boundary_names: list[str]) -> set[tuple[float, float]]:
    nodes = {int(node[0]): node for node in region["nodes"]}
    node_ids: set[int] = set()
    for boundary_name in boundary_names:
        node_ids.update(int(value) for value in region["boundaries"].get(boundary_name, []))
    return {
        (round(float(nodes[node_id][1]), 12), round(float(nodes[node_id][2]), 12))
        for node_id in node_ids
    }


def _close(first: float, second: float) -> bool:
    return math.isclose(float(first), float(second), rel_tol=0.0, abs_tol=1.0e-10)


def _positive(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive finite number") from exc
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{name} must be a positive finite number")
    return number


def resolve_phase15_fsi_overlap_layers(inputs: JSONDict) -> int:
    value = inputs.get(
        "fsi_overlap_layers",
        DEFAULT_PHASE15_FSI_OVERLAP_LAYERS,
    )
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("fsi_overlap_layers must be an integer from 1 to 3")
    if not MIN_PHASE15_FSI_OVERLAP_LAYERS <= value <= MAX_PHASE15_FSI_OVERLAP_LAYERS:
        raise ValueError("fsi_overlap_layers must be an integer from 1 to 3")
    return value


def resolve_phase15_coupling_mode(
    inputs: JSONDict,
    *,
    legacy_default: bool = False,
) -> str:
    default = "immersed_clis" if legacy_default else DEFAULT_PHASE15_COUPLING_MODE
    value = inputs.get("coupling_mode", default)
    if not isinstance(value, str) or value not in PHASE15_COUPLING_MODES:
        raise ValueError(
            "coupling_mode must be conforming_shared_nodes, conforming_air_gap, "
            "or immersed_clis"
        )
    return value
