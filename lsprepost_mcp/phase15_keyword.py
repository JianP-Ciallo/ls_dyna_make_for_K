"""Controlled Phase 15 A-1 two-dimensional axisymmetric keyword compiler.

This module only builds and validates keyword text. It never starts LS-PrePost,
LS-Run, or LS-DYNA.
"""

from __future__ import annotations

from copy import deepcopy
import math

from .config import DEFAULT_UNIT_SYSTEM, JSONDict
from .phase15 import compile_phase15_a1_mesh_plan
from .phase15_fsi import (
    build_phase15_fsi_surfaces,
    evaluate_phase15_fsi_ale_overlap,
    validate_phase15_fsi_surfaces,
)
from .phase15_materials import default_phase15_materials, render_phase15_material_cards


ALE_PART_SET_ID = 1
AXIS_NODE_SET_ID = 201
NONREFLECTING_NODE_SET_ID = 202
CONCRETE_PROBE_SHELL_SET_ID = 301
STEEL_HISTORY_SHELL_SET_ID = 302
ALE_PROBE_SHELL_SET_ID = 303
CONCRETE_PROBE_NODE_SET_ID = 401
D3PLOT_INTERVAL_CURVE_ID = 990015
FSI_CHARGE_BOTTOM_SET_ID = 15101
FSI_BOREHOLE_WALL_SET_ID = 15102
FSI_CONCRETE_TOP_SET_ID = 15103
FSI_ALL_CONCRETE_ALE_SET_ID = 15110
FSI_TNT_AMMG_SET_ID = 15120


def default_phase15_output() -> JSONDict:
    return {
        "end_time_s": 0.0002,
        "early_output_dt_s": 2.0e-6,
        "late_output_dt_s": 5.0e-6,
        "output_transition_time_s": 0.0001,
        "history_output_dt_s": 2.0e-6,
        "probe_depths_from_top_m": [1.26, 1.31, 1.36],
    }


def phase15_sensitivity_matrix() -> list[JSONDict]:
    cases: list[JSONDict] = []
    for mesh_size in (0.004, 0.006, 0.008):
        for erosion_mode in ("off", "standard_observation"):
            cases.append(
                {
                    "case_id": f"phase15_a1_mesh_{mesh_size:g}_erosion_{erosion_mode}",
                    "mesh_size_m": mesh_size,
                    "erosion_mode": erosion_mode,
                    "status": "planned_not_solved",
                    "solver_permission": "explicit_user_approval_required",
                    "interpretation": "workflow sensitivity only; not a CF120 calibration",
                }
            )
    return cases


def compile_phase15_a1_solver_model(
    inputs: JSONDict,
    materials: JSONDict | None = None,
    output: JSONDict | None = None,
) -> JSONDict:
    plan = compile_phase15_a1_mesh_plan(inputs)
    resolved_materials = deepcopy(
        default_phase15_materials() if materials is None else materials
    )
    material_cards, material_metadata = render_phase15_material_cards(
        resolved_materials
    )
    wave_speed_estimate = _phase15_conservative_wave_speed(resolved_materials)
    output_config = _validate_output(output or default_phase15_output(), plan["geometry"])
    regions = plan["regions"]

    nodes: list[list[float | int]] = []
    elements: list[list[int]] = []
    element_regions: dict[int, str] = {}
    next_node_id = 1
    next_element_id = 1
    coupling_mode = str(plan["fsi_coupling"]["mode"])
    is_conforming = coupling_mode in {
        "conforming_shared_nodes",
        "conforming_air_gap",
    }

    if is_conforming:
        merged_nodes, merged_maps, next_node_id = _merge_region_nodes(
            [
                regions["tnt"],
                regions["air"],
                regions["concrete"],
                regions["steel_hoop"],
            ],
            next_node_id,
        )
        nodes.extend(merged_nodes)
        ale_maps = {
            "tnt": merged_maps["tnt"],
            "air": merged_maps["air"],
        }
        lagrange_maps = {
            "concrete": merged_maps["concrete"],
            "steel_hoop": merged_maps["steel_hoop"],
        }
    else:
        ale_nodes, ale_maps, next_node_id = _merge_region_nodes(
            [regions["tnt"], regions["air"]], next_node_id
        )
        nodes.extend(ale_nodes)
        lagrange_nodes, lagrange_maps, next_node_id = _merge_region_nodes(
            [regions["concrete"], regions["steel_hoop"]], next_node_id
        )
        nodes.extend(lagrange_nodes)

    for region_name in ("tnt", "air"):
        region = regions[region_name]
        node_map = ale_maps[region_name]
        for raw in region["elements"]:
            elements.append(
                [next_element_id, 1, *[node_map[int(value)] for value in raw[2:6]]]
            )
            element_regions[next_element_id] = "ale_background"
            next_element_id += 1

    for region_name, part_id in (("concrete", 3), ("steel_hoop", 4)):
        region = regions[region_name]
        node_map = lagrange_maps[region_name]
        for raw in region["elements"]:
            elements.append(
                [next_element_id, part_id, *[node_map[int(value)] for value in raw[2:6]]]
            )
            element_regions[next_element_id] = region_name
            next_element_id += 1

    node_coordinates = {
        int(node[0]): (float(node[1]), float(node[2]), float(node[3])) for node in nodes
    }
    axis_node_ids = sorted(
        {
            node_id
            for node_id, (radius, _z, _third) in node_coordinates.items()
            if abs(radius) <= 1.0e-12
        }
    )
    if coupling_mode == "conforming_shared_nodes":
        nonreflecting_ids = sorted(
            {
                ale_maps["air"][int(value)]
                for value in regions["air"]["boundaries"]["opening_nonreflecting"]
            },
            key=lambda node_id: node_coordinates[node_id][0],
        )
    else:
        nonreflecting_ids = _ordered_nonreflecting_nodes(
            regions["air"], ale_maps["air"], node_coordinates
        )
    concrete_outer = {
        lagrange_maps["concrete"][int(value)]
        for value in regions["concrete"]["boundaries"]["outer_surface"]
    }
    steel_inner = {
        lagrange_maps["steel_hoop"][int(value)]
        for value in regions["steel_hoop"]["boundaries"]["inner_surface"]
    }

    concrete_elements = [element for element in elements if int(element[1]) == 3]
    steel_elements = [element for element in elements if int(element[1]) == 4]
    ale_elements = [element for element in elements if int(element[1]) == 1]
    surface_geometry = deepcopy(plan["geometry"])
    if coupling_mode == "conforming_air_gap":
        surface_geometry["charge_radius_m"] = surface_geometry["borehole_radius_m"]
        surface_geometry["charge_bottom_z_m"] = surface_geometry["borehole_bottom_z_m"]
    candidate_surfaces = build_phase15_fsi_surfaces(
        concrete_elements,
        node_coordinates,
        surface_geometry,
        mesh_size_m=float(plan["mesh_size_m"]),
    )
    if coupling_mode == "immersed_clis":
        fsi_surfaces = candidate_surfaces
        interface_surfaces: JSONDict = {}
        fsi_ale_overlap = evaluate_phase15_fsi_ale_overlap(
            fsi_surfaces,
            ale_elements,
            node_coordinates,
            mesh_size_m=float(plan["mesh_size_m"]),
            overlap_layers=int(plan["fsi_coupling"]["overlap_layers"]),
        )
        shared_interface_edges: set[tuple[int, int]] = set()
    else:
        fsi_surfaces = {}
        if coupling_mode == "conforming_air_gap":
            interface_surfaces = {
                "borehole_bottom": deepcopy(candidate_surfaces["charge_bottom"]),
                "borehole_side": deepcopy(candidate_surfaces["borehole_wall"]),
                "concrete_top": deepcopy(candidate_surfaces["concrete_top"]),
            }
            interface_surfaces["all_segments"] = [
                *interface_surfaces["borehole_bottom"],
                *interface_surfaces["borehole_side"],
                *interface_surfaces["concrete_top"],
            ]
            interface_surfaces["counts"] = {
                "borehole_bottom": len(interface_surfaces["borehole_bottom"]),
                "borehole_side": len(interface_surfaces["borehole_side"]),
                "concrete_top": len(interface_surfaces["concrete_top"]),
            }
            interface_surfaces["total_count"] = len(
                interface_surfaces["all_segments"]
            )
        else:
            interface_surfaces = deepcopy(candidate_surfaces)
            interface_surfaces["concrete_top"] = []
            interface_surfaces["all_segments"] = [
                *interface_surfaces["charge_bottom"],
                *interface_surfaces["borehole_wall"],
            ]
            interface_surfaces["counts"]["concrete_top"] = 0
            interface_surfaces["total_count"] = len(
                interface_surfaces["all_segments"]
            )
        fsi_ale_overlap = None
        ale_edges = _element_edges(ale_elements)
        shared_interface_edges = {
            tuple(sorted((int(segment[0]), int(segment[1]))))
            for segment in interface_surfaces["all_segments"]
            if tuple(sorted((int(segment[0]), int(segment[1])))) in ale_edges
        }
    shared_interface_nodes = sorted(
        {
            node_id
            for edge in shared_interface_edges
            for node_id in edge
        }
    )
    tnt_concrete_shared_node_count = len(
        set(ale_maps["tnt"].values()).intersection(
            lagrange_maps["concrete"].values()
        )
    )
    ale_smoothing_constraints = (
        _radial_ale_smoothing_constraints(
            ale_elements,
            node_coordinates,
            set(shared_interface_nodes),
            float(
                plan["geometry"].get(
                    "borehole_radius_m",
                    plan["geometry"]["charge_radius_m"],
                )
            ),
        )
        if is_conforming
        else []
    )
    concrete_probes = _select_concrete_probes(
        concrete_elements,
        node_coordinates,
        output_config["probe_depths_from_top_m"],
        plan["geometry"],
        float(plan["mesh_size_m"]),
    )
    ale_probes = _select_ale_probes(
        ale_elements,
        node_coordinates,
        plan["geometry"],
        float(plan["mesh_size_m"]),
        coupling_mode=coupling_mode,
    )
    ale_probe_ids = sorted(int(probe["element_id"]) for probe in ale_probes)

    result: JSONDict = {
        "case_id": plan["case_id"],
        "status": "phase15_static_solver_model",
        "coordinate_system": "axisymmetric_r_z_in_global_xy",
        "nodes": nodes,
        "elements": elements,
        "element_regions": element_regions,
        "geometry": plan["geometry"],
        "mesh_size_m": plan["mesh_size_m"],
        "phase15_air_gap": deepcopy(plan.get("phase15_air_gap")),
        "materials": material_metadata,
        "material_cards": material_cards,
        "quality_estimates": {
            "maximum_characteristic_speed_m_per_s": wave_speed_estimate,
            "safety_factor": 1.10,
            "purpose": "static explicit stable-timestep preflight only",
            "basis": [
                "controlled TNT detonation velocity",
                "controlled steel longitudinal wave speed",
                "controlled air initial acoustic speed",
            ],
        },
        "output": output_config,
        "counts": {
            "nodes": len(nodes),
            "elements": len(elements),
            "ale_elements": len(ale_elements),
            "tnt_elements": 0,
            "concrete_elements": len(concrete_elements),
            "steel_elements": len(steel_elements),
        },
        "boundaries": {
            "axis_node_ids": axis_node_ids,
            "nonreflecting_2d_node_ids": nonreflecting_ids,
            "concrete_bottom": "free",
        },
        "ale_smoothing_constraints": ale_smoothing_constraints,
        "interfaces": {
            "coupling_mode": coupling_mode,
            "tnt_is_volume_fraction": True,
            "ale_background_part_id": 1,
            "tnt_material_group_part_id": 2,
            "concrete_fsi_part_id": 3,
            "fsi_surfaces": fsi_surfaces,
            "fsi_ale_overlap": fsi_ale_overlap,
            "fsi_coupling": deepcopy(plan["fsi_coupling"]),
            "interface_surfaces": interface_surfaces,
            "shared_node_ids": shared_interface_nodes,
            "shared_node_count": len(shared_interface_nodes),
            "shared_edge_count": len(shared_interface_edges),
            "tnt_concrete_shared_node_count": tnt_concrete_shared_node_count,
            "geometric_gap_max_m": (
                0.0 if is_conforming else None
            ),
            "ale_concrete_overlap_area_m2": (
                0.0 if is_conforming else None
            ),
            "fsi_ale_material_group_set_id": FSI_TNT_AMMG_SET_ID,
            "fsi_ale_material_group_ids": [2],
            "concrete_steel_shared_nodes": concrete_outer == steel_inner,
            "concrete_steel_shared_node_count": len(concrete_outer.intersection(steel_inner)),
            "fsi_ctype": 4 if material_metadata["erosion"]["mode"] == "off" else 5,
        },
        "probes": {
            "concrete": concrete_probes,
            "ale": ale_probes,
            "ale_element_ids": ale_probe_ids,
            "steel_element_ids": [int(element[0]) for element in steel_elements],
        },
        "section_formulations": {
            "ale": {"keyword": "*SECTION_ALE2D", "aleform": 11, "elform": 14},
            "lagrange": {"keyword": "*SECTION_SHELL", "elform": 15, "nip": 4},
        },
    }
    result["static_issues"] = validate_phase15_a1_solver_model(result)
    return result


def validate_phase15_a1_solver_model(model: JSONDict) -> list[JSONDict]:
    issues: list[JSONDict] = []
    nodes = model.get("nodes", [])
    elements = model.get("elements", [])
    node_ids = [int(node[0]) for node in nodes]
    element_ids = [int(element[0]) for element in elements]
    if len(node_ids) != len(set(node_ids)):
        issues.append({"id": "duplicate_node_ids"})
    if len(element_ids) != len(set(element_ids)):
        issues.append({"id": "duplicate_element_ids"})
    coordinates = {int(node[0]): (float(node[1]), float(node[2])) for node in nodes}
    for element in elements:
        try:
            points = [coordinates[int(value)] for value in element[2:6]]
        except KeyError:
            issues.append({"id": "missing_element_node", "element_id": int(element[0])})
            continue
        area = 0.5 * sum(
            points[index][0] * points[(index + 1) % 4][1]
            - points[(index + 1) % 4][0] * points[index][1]
            for index in range(4)
        )
        if not math.isfinite(area) or area <= 0.0:
            issues.append({"id": "nonpositive_area", "element_id": int(element[0])})
    counts = model.get("counts", {})
    if int(counts.get("tnt_elements", -1)) != 0:
        issues.append({"id": "tnt_must_not_have_separate_elements"})
    interfaces = model.get("interfaces", {})
    if not interfaces.get("tnt_is_volume_fraction"):
        issues.append({"id": "tnt_volume_fraction_missing"})
    if not interfaces.get("concrete_steel_shared_nodes"):
        issues.append({"id": "concrete_steel_not_bonded"})
    coupling_mode = interfaces.get("coupling_mode")
    fsi_coupling = interfaces.get("fsi_coupling")
    if not isinstance(fsi_coupling, dict):
        issues.append({"id": "fsi_coupling_configuration_missing"})
    fsi_surfaces = interfaces.get("fsi_surfaces")
    if not isinstance(fsi_surfaces, dict):
        issues.append({"id": "fsi_surfaces_missing"})
    else:
        if coupling_mode == "immersed_clis":
            issues.extend(
                validate_phase15_fsi_surfaces(
                    fsi_surfaces,
                    [element for element in elements if int(element[1]) == 3],
                    {
                        node_id: (coordinate[0], coordinate[1], 0.0)
                        for node_id, coordinate in coordinates.items()
                    },
                    model.get("geometry", {}),
                    mesh_size_m=float(model.get("mesh_size_m", 0.0)),
                )
            )
            if int(fsi_surfaces.get("total_count", 0)) <= 0:
                issues.append({"id": "fsi_slave_segments_empty"})
        elif fsi_surfaces:
            issues.append({"id": "conforming_fsi_surfaces_must_be_empty"})

        if coupling_mode in {"conforming_shared_nodes", "conforming_air_gap"}:
            interface_surfaces = interfaces.get("interface_surfaces")
            expected_edges = (
                int(interface_surfaces.get("total_count", 0))
                if isinstance(interface_surfaces, dict)
                else 0
            )
            if expected_edges <= 0:
                issues.append({"id": "conforming_interface_surfaces_empty"})
            if int(interfaces.get("shared_edge_count", -1)) != expected_edges:
                issues.append(
                    {
                        "id": "conforming_interface_edges_not_shared",
                        "expected": expected_edges,
                        "actual": interfaces.get("shared_edge_count"),
                    }
                )
            if int(interfaces.get("shared_node_count", 0)) <= 0:
                issues.append({"id": "conforming_interface_nodes_not_shared"})
            if interfaces.get("geometric_gap_max_m") != 0.0:
                issues.append({"id": "conforming_interface_gap"})
            if interfaces.get("ale_concrete_overlap_area_m2") != 0.0:
                issues.append({"id": "conforming_overlap_nonzero"})
            if interfaces.get("fsi_ale_overlap") is not None:
                issues.append({"id": "conforming_overlap_record_present"})
            if (
                coupling_mode == "conforming_air_gap"
                and int(interfaces.get("tnt_concrete_shared_node_count", -1)) != 0
            ):
                issues.append({"id": "conforming_tnt_concrete_nodes_shared"})
            smoothing = model.get("ale_smoothing_constraints")
            if not isinstance(smoothing, list) or not smoothing:
                issues.append({"id": "conforming_ale_smoothing_missing"})
            else:
                shared_nodes = set(interfaces.get("shared_node_ids", []))
                for constraint in smoothing:
                    if not isinstance(constraint, dict):
                        issues.append({"id": "conforming_ale_smoothing_invalid"})
                        continue
                    node_values = [
                        constraint.get("slave_node_id"),
                        constraint.get("axis_node_id"),
                        constraint.get("wall_node_id"),
                    ]
                    if any(value not in coordinates for value in node_values):
                        issues.append(
                            {"id": "conforming_ale_smoothing_node_missing"}
                        )
                    if constraint.get("slave_node_id") in shared_nodes:
                        issues.append(
                            {"id": "conforming_ale_smoothing_moves_interface"}
                        )
                    if constraint.get("ipre") != 0:
                        issues.append(
                            {"id": "conforming_ale_smoothing_ipre_invalid"}
                        )
        elif coupling_mode == "immersed_clis":
            overlap_layers = (
                fsi_coupling.get("overlap_layers", 0)
                if isinstance(fsi_coupling, dict)
                else 0
            )
            try:
                overlap = evaluate_phase15_fsi_ale_overlap(
                    fsi_surfaces,
                    [element for element in elements if int(element[1]) == 1],
                    {
                        node_id: (coordinate[0], coordinate[1], 0.0)
                        for node_id, coordinate in coordinates.items()
                    },
                    mesh_size_m=float(model.get("mesh_size_m", 0.0)),
                    overlap_layers=overlap_layers,
                )
            except ValueError:
                issues.append(
                    {"id": "fsi_overlap_layers_invalid", "value": overlap_layers}
                )
                overlap = None
            stored_overlap = interfaces.get("fsi_ale_overlap")
            try:
                stored_overlap_depth = float(
                    stored_overlap.get("overlap_depth_m", math.nan)
                    if isinstance(stored_overlap, dict)
                    else math.nan
                )
            except (TypeError, ValueError):
                stored_overlap_depth = math.nan
            if (
                isinstance(overlap, dict)
                and (
                    not isinstance(stored_overlap, dict)
                    or stored_overlap.get("overlap_layers")
                    != overlap["overlap_layers"]
                    or not math.isclose(
                        stored_overlap_depth,
                        float(overlap["overlap_depth_m"]),
                        rel_tol=0.0,
                        abs_tol=1.0e-12,
                    )
                )
            ):
                issues.append({"id": "fsi_overlap_record_mismatch"})
            if isinstance(overlap, dict) and not bool(overlap["all_two_sided"]):
                issues.append(
                    {
                        "id": "fsi_ale_two_sided_overlap_missing",
                        "surfaces": overlap["surfaces"],
                    }
                )
        else:
            issues.append({"id": "coupling_mode_invalid", "value": coupling_mode})
    boundary = model.get("boundaries", {}).get("nonreflecting_2d_node_ids", [])
    if len(boundary) < 3 or len(boundary) != len(set(boundary)):
        issues.append({"id": "nonreflecting_boundary_invalid"})
    if not model.get("probes", {}).get("concrete"):
        issues.append({"id": "concrete_probes_missing"})
    return issues


def build_phase15_a1_keyword(
    project_name: str,
    inputs: JSONDict,
    materials: JSONDict | None = None,
    output: JSONDict | None = None,
) -> tuple[str, JSONDict, JSONDict]:
    if not project_name or not isinstance(project_name, str):
        raise ValueError("project_name is required")
    model = compile_phase15_a1_solver_model(inputs, materials=materials, output=output)
    issues = validate_phase15_a1_solver_model(model)
    if issues:
        raise ValueError(f"Phase 15 static solver model failed validation: {issues}")

    geometry = model["geometry"]
    output_config = model["output"]
    lines = [
        "*KEYWORD",
        "*TITLE",
        f"lsprepost-mcp phase15_axisymmetric_blast: {project_name}",
        f"$ Unit system: {DEFAULT_UNIT_SYSTEM} (m, s, kg, N, Pa)",
        "$ Controlled A-1 workflow reference; not a calibrated CF120 engineering model.",
        "$ Solver execution requires separate explicit user approval.",
        *(
            [
                (
                    "$ FSI computational overlap: "
                    f"{model['interfaces']['fsi_coupling']['overlap_layers']} ALE layer(s), "
                    f"{_number(model['interfaces']['fsi_coupling']['overlap_depth_m'])} m. "
                    "This is not physical air thickness."
                )
            ]
            if model["interfaces"]["coupling_mode"] == "immersed_clis"
            else [
                f"$ Phase15 coupling mode: {model['interfaces']['coupling_mode']}; "
                "ALE/concrete interface nodes are shared."
            ]
        ),
        "*CONTROL_TERMINATION",
        "$#  endtim    endcyc     dtmin    endeng    endmas",
        f"{_number(output_config['end_time_s'])},0,0,0,0",
        "*CONTROL_TIMESTEP",
        "0,0.8,0,0,0,0",
        "*CONTROL_ENERGY",
        "2,2,2,2",
        "*CONTROL_ALE",
        (
            "-1,1,2,1.0,0.0,0.0,0.0,0.0"
            if model["interfaces"]["coupling_mode"]
            in {"conforming_shared_nodes", "conforming_air_gap"}
            else "-1,1,2,-1.0,0.0,0.0,0.0,0.0"
        ),
        "0.0,1.0e20,1.0,1.0e-6,0,0,101325.0,0",
    ]
    lines.extend(
        _database_lines(
            output_config,
            include_fsi=model["interfaces"]["coupling_mode"] == "immersed_clis",
        )
    )
    lines.extend(["*NODE", "$#   nid               x               y               z"])
    lines.extend(
        f"{int(node[0])},{_number(node[1])},{_number(node[2])},{_number(node[3])}"
        for node in model["nodes"]
    )
    lines.extend(["*ELEMENT_SHELL", "$#   eid     pid      n1      n2      n3      n4"])
    lines.extend(",".join(str(value) for value in element) for element in model["elements"])
    lines.extend(_part_lines("MM-ALE air background", 1, 1, 1, 1))
    lines.extend(_part_lines("TNT material group initialized by volume fraction", 2, 1, 2, 2))
    lines.extend(_part_lines("K&C concrete target", 3, 3, 3, 0))
    lines.extend(_part_lines("Bonded elastoplastic steel hoop", 4, 4, 4, 0))
    lines.extend(
        [
            "*SECTION_ALE2D",
            "$# secid   aleform       aet    elform",
            "1,11,0,14",
            "*SECTION_SHELL",
            "$# secid    elform      shrf       nip     propt",
            "3,15,0.833,4,1.0",
            "$#     t1        t2        t3        t4      nloc",
            "0,0,0,0,0",
            "*SECTION_SHELL",
            "4,15,0.833,4,1.0",
            "0,0,0,0,0",
        ]
    )
    lines.extend(model["material_cards"])
    lines.extend(
        [
            "*ALE_MULTI-MATERIAL_GROUP",
            "$#     sid    idtype",
            "1,1",
            "2,1",
            "*SET_MULTI-MATERIAL_GROUP_LIST",
            "$# ammsid",
            str(FSI_TNT_AMMG_SET_ID),
            "$# ammgid1",
            "2",
            "*INITIAL_VOLUME_FRACTION_GEOMETRY",
            "$#   fmsid   fmidtyp    bammg    ntrace",
            "1,1,1,0",
            "$# conttyp   fillopt    fammg",
            "4,0,2",
            "$# Axisymmetric r-z TNT section: x1,y1,x2,y2,x3,y3,x4,y4 clockwise",
            (
                f"0,{_number(geometry['charge_bottom_z_m'])},"
                f"0,{_number(geometry['charge_top_z_m'])},"
                f"{_number(geometry['charge_radius_m'])},{_number(geometry['charge_top_z_m'])},"
                f"{_number(geometry['charge_radius_m'])},{_number(geometry['charge_bottom_z_m'])}"
            ),
            "*INITIAL_DETONATION",
            "$#     pid        x0        y0        z0        lt",
            (
                f"1,0,{_number(0.5 * (float(geometry['charge_bottom_z_m']) + float(geometry['charge_top_z_m'])))},0,0"
            ),
            "*SET_PART_LIST_TITLE",
            "ALE air and TNT material parts",
            str(ALE_PART_SET_ID),
            "1,2",
        ]
    )
    if model["interfaces"]["coupling_mode"] == "immersed_clis":
        fsi_surfaces = model["interfaces"]["fsi_surfaces"]
        _append_2d_segment_set(
            lines,
            FSI_CHARGE_BOTTOM_SET_ID,
            "Phase15 FSI charge bottom",
            fsi_surfaces["charge_bottom"],
        )
        _append_2d_segment_set(
            lines,
            FSI_BOREHOLE_WALL_SET_ID,
            "Phase15 FSI borehole wall",
            fsi_surfaces["borehole_wall"],
        )
        _append_2d_segment_set(
            lines,
            FSI_CONCRETE_TOP_SET_ID,
            "Phase15 FSI concrete top",
            fsi_surfaces["concrete_top"],
        )
        lines.extend(
            [
                "*SET_SEGMENT_ADD",
                str(FSI_ALL_CONCRETE_ALE_SET_ID),
                (
                    f"{FSI_CHARGE_BOTTOM_SET_ID},{FSI_BOREHOLE_WALL_SET_ID},"
                    f"{FSI_CONCRETE_TOP_SET_ID}"
                ),
                "*CONSTRAINED_LAGRANGE_IN_SOLID",
                "$#   slave    master     sstyp     mstyp     nquad     ctype     direc     mcoup",
                (
                    f"{FSI_ALL_CONCRETE_ALE_SET_ID},{ALE_PART_SET_ID},2,0,4,"
                    f"{model['interfaces']['fsi_ctype']},2,{-FSI_TNT_AMMG_SET_ID}"
                ),
                "$#   start       end      pfac      fric    frcmin      norm   normtyp      damp",
                "0.0,0.0,0.1,0.0,0.3,0,0,0.1",
                "$#       k      hmin      hmax     ileak     pleak   lcidpor     nvent    iblock",
                "0.0,0.0,0.0,2,0.1,0,0,0",
            ]
        )
    else:
        for constraint in model["ale_smoothing_constraints"]:
            lines.extend(
                [
                    "*ALE_SMOOTHING",
                    (
                        f"{constraint['slave_node_id']},"
                        f"{constraint['axis_node_id']},"
                        f"{constraint['wall_node_id']},"
                        f"{constraint['ipre']},0,0,0"
                    ),
                ]
            )
    _append_node_set(lines, AXIS_NODE_SET_ID, "Axisymmetric r=0 nodes", model["boundaries"]["axis_node_ids"])
    lines.extend(["*BOUNDARY_SPC_SET", f"{AXIS_NODE_SET_ID},0,1,0,0,0,0,0"])
    _append_node_set(
        lines,
        NONREFLECTING_NODE_SET_ID,
        "Ordered top and outer MM-ALE boundary",
        model["boundaries"]["nonreflecting_2d_node_ids"],
    )
    lines.extend(["*BOUNDARY_NON_REFLECTING_2D", str(NONREFLECTING_NODE_SET_ID)])
    concrete_probe_elements = [probe["element_id"] for probe in model["probes"]["concrete"]]
    concrete_probe_nodes = [probe["node_id"] for probe in model["probes"]["concrete"]]
    _append_shell_set(lines, CONCRETE_PROBE_SHELL_SET_ID, "Concrete pressure and damage probes", concrete_probe_elements)
    _append_shell_set(lines, STEEL_HISTORY_SHELL_SET_ID, "Steel hoop stress history", model["probes"]["steel_element_ids"])
    _append_shell_set(lines, ALE_PROBE_SHELL_SET_ID, "ALE pressure path probes", model["probes"]["ale_element_ids"])
    _append_node_set(lines, CONCRETE_PROBE_NODE_SET_ID, "Concrete response probe nodes", concrete_probe_nodes)
    lines.extend(
        [
            "*DATABASE_HISTORY_SHELL_SET",
            str(CONCRETE_PROBE_SHELL_SET_ID),
            "*DATABASE_HISTORY_SHELL_SET",
            str(STEEL_HISTORY_SHELL_SET_ID),
            "*DATABASE_HISTORY_SHELL_SET",
            str(ALE_PROBE_SHELL_SET_ID),
            "*DATABASE_HISTORY_NODE_SET",
            str(CONCRETE_PROBE_NODE_SET_ID),
            "*END",
        ]
    )
    keyword = "\n".join(lines) + "\n"
    coordinate_by_node = {
        int(node[0]): (float(node[1]), float(node[2]), float(node[3]))
        for node in model["nodes"]
    }
    ale_node_ids = {
        int(node_id)
        for element in model["elements"]
        if int(element[1]) == 1
        for node_id in element[2:6]
    }
    ale_coordinates = [coordinate_by_node[node_id] for node_id in ale_node_ids]
    ale_bounds = {
        "min": [
            min(item[0] for item in ale_coordinates),
            min(item[1] for item in ale_coordinates),
            min(item[2] for item in ale_coordinates),
        ],
        "max": [
            max(item[0] for item in ale_coordinates),
            max(item[1] for item in ale_coordinates),
            max(item[2] for item in ale_coordinates),
        ],
    }
    metadata: JSONDict = {
        "unit_system": DEFAULT_UNIT_SYSTEM,
        "model_type": "phase15_axisymmetric_blast",
        "element_family": "shell",
        "analysis_method": "MM-ALE 2D axisymmetric",
        "validation_profile": "mm_ale_axisymmetric_kc_blast_v1",
        "validation_capabilities": [
            "mm_ale",
            "high_explosive_jwl",
            "lagrangian_shell_structure",
            *(
                ["ale_fsi", "fsi_segment_interface"]
                if model["interfaces"]["coupling_mode"] == "immersed_clis"
                else ["conforming_ale_lagrange_interface"]
            ),
            "ale_nonreflecting_2d",
            "kc_concrete",
            "steel_plasticity",
            "axisymmetric_ale",
        ],
        "node_count": model["counts"]["nodes"],
        "element_count": model["counts"]["elements"],
        "part_count": 4,
        "material_count": 4,
        "section_count": 3,
        "constraint_count": (
            2
            if model["interfaces"]["coupling_mode"] == "immersed_clis"
            else 1 + len(model["ale_smoothing_constraints"])
        ),
        "curve_count": 1,
        "components": [
            {"id": "MM-ALE air and bore domain", "part_id": 1, "element_family": "shell"},
            {"id": "K&C concrete target", "part_id": 3, "element_family": "shell"},
            {"id": "Bonded steel hoop", "part_id": 4, "element_family": "shell"},
        ],
        "blast_sources": [
            {
                "kind": "ale_explosive_volume",
                "label": "TNT cylindrical initialization region",
                "position_m": [
                    0.0,
                    0.5
                    * (
                        float(geometry["charge_bottom_z_m"])
                        + float(geometry["charge_top_z_m"])
                    ),
                    0.0,
                ],
                "radius_m": float(geometry["charge_radius_m"]),
                "length_m": float(geometry["charge_length_m"]),
                "mass_kg": float(geometry["tnt_effective_mass_kg"]),
            }
        ],
        "ale_domain": {
            "part_id": 1,
            "bounds_m": ale_bounds,
        },
        "phase15": {
            "coupling_mode": model["interfaces"]["coupling_mode"],
            "fsi_coupling": deepcopy(model["interfaces"]["fsi_coupling"]),
            "geometry": deepcopy(geometry),
            "phase15_air_gap": deepcopy(model.get("phase15_air_gap")),
            "counts": deepcopy(model["counts"]),
            "interfaces": deepcopy(model["interfaces"]),
            "probes": deepcopy(model["probes"]),
            "output": deepcopy(output_config),
            "materials": deepcopy(model["materials"]),
            "quality_estimates": deepcopy(model["quality_estimates"]),
        },
        "static_readiness": {
            "issues": issues,
            "ls_prepost_import": "not_run",
            "lsrun_smoke": "not_authorized_not_run",
            "full_sensitivity": "not_authorized_not_run",
        },
    }
    spec: JSONDict = {
        "project_name": project_name,
        "model_type": "phase15_axisymmetric_blast",
        "coupling_mode": model["interfaces"]["coupling_mode"],
        "unit_system": DEFAULT_UNIT_SYSTEM,
        "geometry": deepcopy(geometry),
        "mesh": {"size_m": model["mesh_size_m"], "mode": "axisymmetric_2d"},
        "material": {
            "name": "kc_a1_automatic_reference",
            "type": "concrete_damage_rel3",
            "density_kg_per_m3": 2480.0,
            "wave_speed_m_per_s": model["quality_estimates"][
                "maximum_characteristic_speed_m_per_s"
            ],
            "wave_speed_basis": deepcopy(model["quality_estimates"]),
            "unit_system": DEFAULT_UNIT_SYSTEM,
            "source": "Phase 15 controlled K&C automatic reference preset",
            "source_type": "material_library",
            "version": "phase15-r1",
        },
        "curves": [],
        "hourglass": {},
        "analysis_control": {"termination": {"end_time_s": output_config["end_time_s"]}},
        "database": deepcopy(output_config),
        "components": [],
        "contacts": [],
        "sets": [],
        "boundary_conditions": [{"type": "spc_node_set", "set_id": AXIS_NODE_SET_ID}],
        "loads": [],
        "warnings": [
            {
                "id": "phase15_material_not_calibrated",
                "message": "K&C automatic parameters are a workflow reference, not calibrated CF120 data.",
            }
        ],
        "phase15_inputs": deepcopy(inputs),
        "phase15_materials": deepcopy(materials or default_phase15_materials()),
    }
    return keyword, metadata, spec


def _phase15_conservative_wave_speed(materials: JSONDict) -> float:
    tnt = materials["tnt"]
    steel = materials["steel_hoop"]
    air = materials["air"]
    air_eos = air["eos"]

    steel_density = float(steel["density_kg_per_m3"])
    steel_youngs = float(steel["youngs_pa"])
    steel_poisson = float(steel["poisson"])
    steel_longitudinal = math.sqrt(
        steel_youngs
        * (1.0 - steel_poisson)
        / (
            steel_density
            * (1.0 + steel_poisson)
            * (1.0 - 2.0 * steel_poisson)
        )
    )
    air_density = float(air["density_kg_per_m3"])
    air_pressure = (
        float(air_eos["c4"])
        * float(air_eos["initial_internal_energy_density_j_per_m3"])
    )
    air_gamma = 1.0 + float(air_eos["c4"])
    air_acoustic = math.sqrt(air_gamma * air_pressure / air_density)
    tnt_detonation = float(tnt["detonation_velocity_m_per_s"])
    return 1.10 * max(tnt_detonation, steel_longitudinal, air_acoustic)


def _validate_output(raw: JSONDict, geometry: JSONDict) -> JSONDict:
    if not isinstance(raw, dict):
        raise ValueError("Phase 15 output must be an object")
    result = deepcopy(raw)
    limits = {
        "end_time_s": (0.0002, 0.02),
        "early_output_dt_s": (1.0e-6, 2.0e-5),
        "late_output_dt_s": (2.0e-6, 1.0e-4),
        "output_transition_time_s": (1.0e-5, 0.005),
        "history_output_dt_s": (1.0e-6, 2.0e-5),
    }
    for field, (minimum, maximum) in limits.items():
        value = _finite(result.get(field), field)
        if not minimum <= value <= maximum:
            raise ValueError(f"{field} must be between {minimum:g} and {maximum:g}")
        result[field] = value
    if result["late_output_dt_s"] < result["early_output_dt_s"]:
        raise ValueError("late_output_dt_s must not be smaller than early_output_dt_s")
    if result["output_transition_time_s"] >= result["end_time_s"]:
        raise ValueError("output_transition_time_s must be earlier than end_time_s")
    depths = result.get("probe_depths_from_top_m")
    if not isinstance(depths, list) or len(depths) != 3:
        raise ValueError("probe_depths_from_top_m must contain exactly three values")
    target_height = float(geometry["target_height_m"])
    normalized = [_finite(value, f"probe_depths_from_top_m[{index}]") for index, value in enumerate(depths)]
    if normalized != sorted(normalized) or any(value <= 0.0 or value >= target_height for value in normalized):
        raise ValueError("probe depths must be increasing and lie inside the concrete target")
    result["probe_depths_from_top_m"] = normalized
    return result


def _merge_region_nodes(
    regions: list[JSONDict], node_id_start: int
) -> tuple[list[list[float | int]], dict[str, dict[int, int]], int]:
    coordinate_to_id: dict[tuple[float, float, float], int] = {}
    nodes: list[list[float | int]] = []
    maps: dict[str, dict[int, int]] = {}
    next_node_id = int(node_id_start)
    for region in regions:
        local_map: dict[int, int] = {}
        for raw in region["nodes"]:
            key = (round(float(raw[1]), 12), round(float(raw[2]), 12), round(float(raw[3]), 12))
            if key not in coordinate_to_id:
                coordinate_to_id[key] = next_node_id
                nodes.append([next_node_id, float(raw[1]), float(raw[2]), float(raw[3])])
                next_node_id += 1
            local_map[int(raw[0])] = coordinate_to_id[key]
        maps[str(region["name"])] = local_map
    return nodes, maps, next_node_id


def _element_edges(elements: list[list[int]]) -> set[tuple[int, int]]:
    edges: set[tuple[int, int]] = set()
    for element in elements:
        node_ids = [int(value) for value in element[2:6]]
        for index in range(4):
            edges.add(
                tuple(
                    sorted(
                        (
                            node_ids[index],
                            node_ids[(index + 1) % 4],
                        )
                    )
                )
            )
    return edges


def _radial_ale_smoothing_constraints(
    elements: list[list[int]],
    coordinates: dict[int, tuple[float, float, float]],
    shared_interface_nodes: set[int],
    wall_radius: float,
) -> list[JSONDict]:
    ale_node_ids = {
        int(node_id)
        for element in elements
        for node_id in element[2:6]
    }
    rows: dict[float, list[int]] = {}
    for node_id in ale_node_ids:
        rows.setdefault(round(coordinates[node_id][1], 12), []).append(node_id)

    constraints: list[JSONDict] = []
    tolerance = max(1.0e-12, wall_radius * 1.0e-9)
    for node_ids in rows.values():
        ordered = sorted(node_ids, key=lambda node_id: coordinates[node_id][0])
        axis = next(
            (
                node_id
                for node_id in ordered
                if abs(coordinates[node_id][0]) <= tolerance
            ),
            None,
        )
        wall = next(
            (
                node_id
                for node_id in reversed(ordered)
                if abs(coordinates[node_id][0] - wall_radius) <= tolerance
            ),
            None,
        )
        if axis is None or wall is None or axis == wall:
            continue
        for slave in ordered:
            radius = coordinates[slave][0]
            if (
                slave in shared_interface_nodes
                or radius <= tolerance
                or radius >= wall_radius - tolerance
            ):
                continue
            constraints.append(
                {
                    "slave_node_id": slave,
                    "axis_node_id": axis,
                    "wall_node_id": wall,
                    "ipre": 0,
                }
            )
    return constraints


def _ordered_nonreflecting_nodes(
    air: JSONDict,
    node_map: dict[int, int],
    coordinates: dict[int, tuple[float, float, float]],
) -> list[int]:
    top = {node_map[int(value)] for value in air["boundaries"]["top_nonreflecting"]}
    outer = {node_map[int(value)] for value in air["boundaries"]["outer_nonreflecting"]}
    ordered_top = sorted(top, key=lambda node_id: coordinates[node_id][0])
    ordered_outer = sorted(outer, key=lambda node_id: coordinates[node_id][1], reverse=True)
    return ordered_top + [node_id for node_id in ordered_outer if node_id not in top]


def _select_concrete_probes(
    elements: list[list[int]],
    coordinates: dict[int, tuple[float, float, float]],
    depths: list[float],
    geometry: JSONDict,
    mesh_size: float,
) -> list[JSONDict]:
    target_top_z = float(geometry["target_top_z_m"])
    charge_radius = float(geometry["charge_radius_m"])
    charge_bottom_z = float(geometry["charge_bottom_z_m"])
    charge_top_z = float(geometry["charge_top_z_m"])
    interface_radius = float(geometry.get("borehole_radius_m", charge_radius))
    interface_bottom_z = float(
        geometry.get("borehole_bottom_z_m", charge_bottom_z)
    )
    conforming_air_gap = "borehole_radius_m" in geometry
    centers = [
        (
            int(element[0]),
            sum(coordinates[int(node_id)][0] for node_id in element[2:6]) / 4.0,
            sum(coordinates[int(node_id)][1] for node_id in element[2:6]) / 4.0,
            [int(value) for value in element[2:6]],
        )
        for element in elements
    ]
    probes: list[JSONDict] = []
    targets: list[tuple[str, float, float, str | None]] = [
        (
            "INTERFACE_BOTTOM" if conforming_air_gap else "FSI_BOTTOM",
            0.5 * interface_radius,
            interface_bottom_z - 0.5 * mesh_size,
            "borehole_bottom" if conforming_air_gap else "charge_bottom",
        ),
        (
            "INTERFACE_WALL" if conforming_air_gap else "FSI_WALL",
            interface_radius + 0.5 * mesh_size,
            0.5 * (charge_bottom_z + charge_top_z),
            "borehole_side" if conforming_air_gap else "borehole_wall",
        ),
        (
            "FSI_TOP",
            charge_radius + 0.5 * mesh_size,
            target_top_z - 0.5 * mesh_size,
            "concrete_top",
        ),
    ]
    targets.extend(
        (f"P{index}", 0.5 * mesh_size, target_top_z - float(depth), None)
        for index, depth in enumerate(depths, 1)
    )
    for probe_id, requested_r, requested_z, surface in targets:
        element_id, center_r, center_z, element_nodes = min(
            centers,
            key=lambda item: (item[1] - requested_r) ** 2
            + (item[2] - requested_z) ** 2,
        )
        node_id = min(
            element_nodes,
            key=lambda value: (coordinates[value][0] - requested_r) ** 2
            + (coordinates[value][1] - requested_z) ** 2,
        )
        probe: JSONDict = {
            "id": probe_id,
            "depth_from_top_m": target_top_z - requested_z,
            "requested_r_z_m": [requested_r, requested_z],
            "element_center_r_z_m": [center_r, center_z],
            "element_id": element_id,
            "node_id": node_id,
        }
        if surface is not None:
            probe["surface"] = surface
        probes.append(probe)
    return probes


def _select_ale_probes(
    elements: list[list[int]],
    coordinates: dict[int, tuple[float, float, float]],
    geometry: JSONDict,
    mesh_size: float,
    *,
    coupling_mode: str,
) -> list[JSONDict]:
    charge_top = float(geometry["charge_top_z_m"])
    charge_bottom = float(geometry["charge_bottom_z_m"])
    target_top = float(geometry["target_top_z_m"])
    if coupling_mode == "conforming_air_gap":
        charge_radius = float(geometry["charge_radius_m"])
        borehole_radius = float(geometry["borehole_radius_m"])
        radial_gap = borehole_radius - charge_radius
        axial = 0.5 * (charge_bottom + charge_top)
        requested = [
            ("TNT_NEAR", charge_radius + min(0.5 * mesh_size, radial_gap / 6.0), axial),
            ("AIR_MID_GAP", charge_radius + 0.5 * radial_gap, axial),
            (
                "AIR_INTERFACE",
                borehole_radius - min(0.5 * mesh_size, radial_gap / 6.0),
                axial,
            ),
        ]
    else:
        requested = [
            ("ALE_SOURCE", 0.5 * mesh_size, charge_top + mesh_size),
            ("ALE_PATH", 0.5 * mesh_size, 0.5 * (charge_top + target_top)),
            (
                "ALE_OPENING",
                0.5 * float(geometry["target_radius_m"]),
                target_top + 0.5 * mesh_size,
            ),
        ]
    centers = [
        (
            int(element[0]),
            sum(coordinates[int(node_id)][0] for node_id in element[2:6]) / 4.0,
            sum(coordinates[int(node_id)][1] for node_id in element[2:6]) / 4.0,
        )
        for element in elements
    ]
    result: list[JSONDict] = []
    for probe_id, requested_r, requested_z in requested:
        element_id, center_r, center_z = min(
            centers,
            key=lambda item: (item[1] - requested_r) ** 2
            + (item[2] - requested_z) ** 2,
        )
        result.append(
            {
                "id": probe_id,
                "element_id": element_id,
                "requested_r_z_m": [requested_r, requested_z],
                "element_center_r_z_m": [center_r, center_z],
            }
        )
    return result


def _database_lines(output: JSONDict, *, include_fsi: bool) -> list[str]:
    transition = float(output["output_transition_time_s"])
    end_time = float(output["end_time_s"])
    early = float(output["early_output_dt_s"])
    late = float(output["late_output_dt_s"])
    history = float(output["history_output_dt_s"])
    epsilon = max(1.0e-12, transition * 1.0e-9)
    lines = [
        "*DATABASE_FORMAT",
        "0,1",
        "*DEFINE_CURVE_TITLE",
        "Phase 15 staged d3plot output interval",
        f"{D3PLOT_INTERVAL_CURVE_ID},0,1,1,0,0,0,0",
        f"0,{_number(early)}",
        f"{_number(transition)},{_number(early)}",
        f"{_number(transition + epsilon)},{_number(late)}",
        f"{_number(end_time)},{_number(late)}",
        "*DATABASE_BINARY_D3PLOT",
        f"0,{D3PLOT_INTERVAL_CURVE_ID}",
        "*DATABASE_BINARY_D3THDT",
        _number(history),
        "*DATABASE_GLSTAT",
        _number(history),
        "*DATABASE_MATSUM",
        _number(history),
        "*DATABASE_NODOUT",
        _number(history),
        "*DATABASE_ELOUT",
        _number(history),
    ]
    if include_fsi:
        lines.extend(
            [
                "*DATABASE_FSI",
                _number(history),
                "1,3,1",
            ]
        )
    lines.extend(
        [
        "*DATABASE_ALE_MAT",
        f"{_number(history)},0",
        "*DATABASE_EXTENT_BINARY",
        "0,3,4,1,1,1,1,1",
        "0,0,0,0,0,0,2,1",
        "1,0,1.0,0,0",
        ]
    )
    return lines


def _part_lines(title: str, part_id: int, section_id: int, material_id: int, eos_id: int) -> list[str]:
    return [
        "*PART",
        title,
        "$#   pid     secid       mid     eosid      hgid      grav    adpopt      tmid",
        f"{part_id},{section_id},{material_id},{eos_id},0,0,0,0",
    ]


def _append_node_set(lines: list[str], set_id: int, title: str, node_ids: list[int]) -> None:
    lines.extend(["*SET_NODE_LIST_TITLE", title, str(set_id)])
    for index in range(0, len(node_ids), 8):
        lines.append(",".join(str(value) for value in node_ids[index : index + 8]))


def _append_shell_set(lines: list[str], set_id: int, title: str, element_ids: list[int]) -> None:
    lines.extend(["*SET_SHELL_LIST_TITLE", title, str(set_id)])
    for index in range(0, len(element_ids), 8):
        lines.append(",".join(str(value) for value in element_ids[index : index + 8]))


def _append_2d_segment_set(
    lines: list[str],
    set_id: int,
    title: str,
    segments: list[list[int]],
) -> None:
    if not segments:
        raise ValueError(f"Phase 15 FSI segment set {set_id} must not be empty")
    lines.extend(
        [
            "*SET_SEGMENT_TITLE",
            title,
            "$#   sid       da1       da2       da3       da4",
            f"{set_id},0,0,0,0",
            "$#    n1      n2",
        ]
    )
    for segment in segments:
        if len(segment) != 2:
            raise ValueError(f"Phase 15 FSI segment set {set_id} must contain 2D lines")
        lines.append(f"{int(segment[0])},{int(segment[1])}")


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


def _number(value: object) -> str:
    number = float(value)
    for precision in range(9, 0, -1):
        candidate = f"{number:.{precision}g}"
        if len(candidate) <= 10:
            return candidate
    raise ValueError(f"cannot format LS-DYNA R12 numeric field: {value!r}")
