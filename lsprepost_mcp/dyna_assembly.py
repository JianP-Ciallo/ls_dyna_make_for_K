from __future__ import annotations

from dataclasses import replace
import math

from .component_library import AssemblyContext, ComponentInstance, component_definition
from .config import JSONDict
from .dyna_cards import common_header, database_lines, hourglass_lines, material_lines
from .dyna_blast import blast_keyword_lines
from .dyna_common import Segment
from .dyna_conditions import boundary_and_load_lines
from .dyna_selectors import node_set_lines, part_set_lines, solid_segments_from_elements
from .preflight import grid_count
from .schema import ModelSpec


Node = tuple[int, float, float, float]
ShellElement = tuple[int, int, int, int, int, int]
SolidElement = tuple[int, int, int, int, int, int, int, int, int, int]


def build_assembly_scene(spec: ModelSpec) -> tuple[str, JSONDict]:
    parts: list[JSONDict] = []
    all_nodes: list[Node] = []
    shell_elements: list[ShellElement] = []
    solid_elements: list[SolidElement] = []
    section_lines: list[str] = []
    material_card_lines: list[str] = []
    set_and_condition_lines: list[str] = []
    contact_lines: list[str] = []

    context = AssemblyContext()

    component_nodes: dict[str, list[Node]] = {}
    component_part_sets: dict[str, int] = {}
    component_part_ids: dict[str, int] = {}
    component_element_family: dict[str, str] = {}
    component_shell_segments: dict[str, list[Segment]] = {}

    for component in spec.components:
        instance = ComponentInstance.from_mapping(component)
        component_id = instance.component_id
        template = instance.template
        ids = context.allocate_component_ids()
        pid = ids.part_id
        secid = ids.section_id
        mid = ids.material_id

        local_nodes, local_shells, local_solids, section = build_component_geometry(component, pid)
        transformed_nodes = apply_transform(local_nodes, component)
        node_map = context.allocate_node_map([old_nid for old_nid, _, _, _ in transformed_nodes])
        nodes = [(node_map[nid], x, y, z) for nid, x, y, z in transformed_nodes]
        all_nodes.extend(nodes)
        component_nodes[component_id] = nodes

        if local_shells:
            mapped_segments: list[Segment] = []
            for element in local_shells:
                mapped = tuple(node_map[nid] for nid in element[2:6])
                shell_elements.append((context.allocate_shell_element_id(), pid, *mapped))
                mapped_segments.append(mapped)  # type: ignore[arg-type]
            component_shell_segments[component_id] = mapped_segments
            component_element_family[component_id] = "shell"
        if local_solids:
            for element in local_solids:
                solid_elements.append((context.allocate_solid_element_id(), pid, *(node_map[nid] for nid in element[2:10])))
            component_element_family[component_id] = "solid"
        title = f"{component_id}_{template}"
        part_metadata: JSONDict = {
            "id": component_id,
            "template": template,
            "part_id": pid,
            "section_id": secid,
            "material_id": mid,
            "element_family": component_element_family[component_id],
            "node_count": len(nodes),
            "node_ids": [nid for nid, _, _, _ in nodes],
            "node_id_range": [min(node_map.values()), max(node_map.values())],
            "mesh_size_m": float(component["mesh"]["size_m"]),
            "fixed_node_ids": [],
            "fixed_regions": list(component.get("fixed_regions", [])),
            "named_surfaces": list(instance.definition.named_surfaces),
            "named_edges": list(instance.definition.named_edges),
        }
        if section.get("type") == "shell":
            part_metadata["shell_thickness_m"] = float(section["thickness_m"])
        parts.append(part_metadata)
        section_lines.extend(part_lines(title, pid, secid, mid))
        section_lines.extend(section_lines_for_component(section, secid))
        component_spec = replace(spec, material={**component["material"], "id": mid})
        material_card_lines.extend(material_lines(component_spec))

        part_set_id = context.allocate_set_id()
        set_and_condition_lines.extend(part_set_lines(part_set_id, f"component {component_id}", [pid]))
        component_part_sets[component_id] = part_set_id
        component_part_ids[component_id] = pid

        fixed_node_ids: set[int] = set()
        for region in component.get("fixed_regions", []):
            local_node_ids = nodes_for_component_region(local_nodes, template, str(region))
            node_ids = [node_map[nid] for nid in local_node_ids]
            fixed_node_ids.update(node_ids)
            nsid = context.allocate_set_id()
            set_and_condition_lines.extend(node_set_lines(nsid, f"{component_id} fixed region {region}", node_ids))
            set_and_condition_lines.extend(
                [
                    "*BOUNDARY_SPC_SET",
                    "$#  nsid       cid      dofx      dofy      dofz     dofrx     dofry     dofrz",
                    f"{nsid},0,1,1,1,1,1,1",
                ]
            )
        for face in component.get("fixed_faces", []):
            node_ids = nodes_for_component_face(nodes, str(face))
            fixed_node_ids.update(node_ids)
            nsid = context.allocate_set_id()
            set_and_condition_lines.extend(node_set_lines(nsid, f"{component_id} fixed {face}", node_ids))
            set_and_condition_lines.extend(
                [
                    "*BOUNDARY_SPC_SET",
                    "$#  nsid       cid      dofx      dofy      dofz     dofrx     dofry     dofrz",
                    f"{nsid},0,1,1,1,1,1,1",
                ]
            )
        part_metadata["fixed_node_ids"] = sorted(fixed_node_ids)

        if "initial_velocity_m_per_s" in component:
            vx, vy, vz = [float(value) for value in component["initial_velocity_m_per_s"]]
            set_and_condition_lines.extend(
                [
                    "*INITIAL_VELOCITY_NODE",
                    "$#   nid        vx        vy        vz       vxr       vyr       vzr",
                ]
            )
            set_and_condition_lines.extend(f"{nid},{vx:.9g},{vy:.9g},{vz:.9g},0.0,0.0,0.0" for nid, _, _, _ in nodes)

    history_node_ids: list[int] = []
    if "nodout_dt_s" in spec.database:
        fixed_node_ids = {
            int(node_id)
            for part in parts
            for node_id in part.get("fixed_node_ids", [])
        }
        history_node_ids = sorted(
            nid for nid, _, _, _ in all_nodes if nid not in fixed_node_ids
        )
        if not history_node_ids:
            raise ValueError("database.nodout_dt_s requires at least one non-fixed response node")
        history_node_set_id = context.allocate_set_id()
        set_and_condition_lines.extend(
            node_set_lines(history_node_set_id, "nodout free response nodes", history_node_ids)
        )
        set_and_condition_lines.extend(
            [
                "*DATABASE_HISTORY_NODE_SET",
                "$#   nsid",
                str(history_node_set_id),
            ]
        )

    controlled_contacts: list[str] = []
    for contact in spec.contacts:
        contact_id = context.allocate_contact_id()
        slave = str(contact["slave"])
        master = str(contact["master"])
        contact_type = str(contact["type"])
        friction = float(contact.get("friction", 0.0))
        if contact_type == "automatic_nodes_to_surface":
            card = "*CONTACT_AUTOMATIC_NODES_TO_SURFACE"
            slave_face = str(contact.get("slave_face", "z_min"))
            slave_node_ids = nodes_for_component_face(component_nodes[slave], slave_face)
            slave_node_set = context.allocate_set_id()
            contact_lines.extend(node_set_lines(slave_node_set, f"contact slave {slave} {slave_face}", slave_node_ids))
            contact_lines.extend(
                [
                    card,
                    f"$ controlled contact {contact_id}: {slave} nodes -> {master} surface",
                    "$#   ssid      msid     sstyp     mstyp    sboxid    mboxid      spr      mpr",
                    f"{slave_node_set},{component_part_sets[master]},4,2,0,0,0,0",
                    "$#     fs        fd        dc        vc       vdc    penchk        bt        dt",
                    f"{friction:.9g},{friction:.9g},0.0,0.0,0.0,0,0.0,0.0",
                    "$#    sfs       sfm       sst       mst      sfst      sfmt       fsf       vsf",
                    "1.0,1.0,0.0,0.0,1.0,1.0,1.0,1.0",
                ]
            )
        else:
            card = "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE"
            contact_lines.extend(
                [
                    card,
                    f"$ controlled contact {contact_id}: {slave} -> {master}",
                    "$#   ssid      msid     sstyp     mstyp    sboxid    mboxid      spr      mpr",
                    f"{component_part_sets[slave]},{component_part_sets[master]},2,2,0,0,0,0",
                    "$#     fs        fd        dc        vc       vdc    penchk        bt        dt",
                    f"{friction:.9g},{friction:.9g},0.0,0.0,0.0,0,0.0,0.0",
                    "$#    sfs       sfm       sst       mst      sfst      sfmt       fsf       vsf",
                    "1.0,1.0,0.0,0.0,1.0,1.0,1.0,1.0",
                ]
            )
        controlled_contacts.append(card)

    lines = common_header(spec)
    lines.extend(["*NODE", "$#   nid               x               y               z"])
    lines.extend(f"{nid},{x:.9g},{y:.9g},{z:.9g}" for nid, x, y, z in all_nodes)
    if shell_elements:
        lines.extend(["*ELEMENT_SHELL", "$#   eid     pid      n1      n2      n3      n4"])
        lines.extend(",".join(str(value) for value in element) for element in shell_elements)
    if solid_elements:
        lines.extend(["*ELEMENT_SOLID", "$#   eid     pid      n1      n2      n3      n4      n5      n6      n7      n8"])
        lines.extend(",".join(str(value) for value in element) for element in solid_elements)
    lines.extend(section_lines)
    lines.extend(hourglass_lines(spec))
    lines.extend(material_card_lines)
    lines.extend(set_and_condition_lines)
    blast_loads = [load for load in spec.loads if load.get("type") == "blast_enhanced"]
    standard_loads = [load for load in spec.loads if load.get("type") != "blast_enhanced"]
    if standard_loads or spec.boundary_conditions or spec.sets:
        condition_spec = replace(spec, loads=standard_loads)
        condition_lines, condition_metadata = boundary_and_load_lines(
            condition_spec, all_nodes, all_segments(shell_elements, solid_elements)
        )
        lines.extend(condition_lines)
    else:
        condition_metadata = empty_condition_metadata()
    blast_lines, blast_metadata = blast_keyword_lines(blast_loads, component_shell_segments)
    lines.extend(blast_lines)
    lines.extend(contact_lines)
    lines.append("*END")

    fixed_count = sum(
        len(component.get("fixed_faces", [])) + len(component.get("fixed_regions", []))
        for component in spec.components
    )
    contact_node_set_count = sum(1 for contact in spec.contacts if contact.get("type") == "automatic_nodes_to_surface")
    initial_velocity_count = sum(1 for component in spec.components if "initial_velocity_m_per_s" in component)
    metadata = {
        "unit_system": spec.unit_system,
        "model_type": spec.model_type,
        "element_family": "mixed" if shell_elements and solid_elements else ("shell" if shell_elements else "solid"),
        "node_count": len(all_nodes),
        "element_count": len(shell_elements) + len(solid_elements),
        "shell_element_count": len(shell_elements),
        "solid_element_count": len(solid_elements),
        "part_count": len(parts),
        "material_count": len(parts),
        "section_count": len(parts),
        "constraint_count": fixed_count + int(condition_metadata.get("constraint_count", 0)),
        "node_set_count": fixed_count + contact_node_set_count + int(bool(history_node_ids)) + int(condition_metadata.get("node_set_count", 0)),
        "part_set_count": len(component_part_sets) + int(condition_metadata.get("part_set_count", 0)),
        "segment_set_count": int(condition_metadata.get("segment_set_count", 0)) + sum(len(load["targets"]) for load in blast_loads),
        "load_count": int(condition_metadata.get("load_count", 0)) + len(blast_loads),
        "initial_condition_count": initial_velocity_count + int(condition_metadata.get("initial_condition_count", 0)),
        "curve_count": int(condition_metadata.get("curve_count", 0)),
        "hourglass_count": 1 if spec.hourglass else 0,
        "control_count": 1 + sum(1 for key in ["energy", "shell", "timestep"] if isinstance(spec.analysis_control.get(key), dict)),
        "database_count": 1 + int("d3thdt_dt_s" in spec.database) + (2 if "nodout_dt_s" in spec.database else 0) + int(isinstance(spec.database.get("extent_binary"), dict)) + int("format" in spec.database) + (4 if blast_loads else 0),
        "history_node_count": len(history_node_ids),
        "contact_count": len(spec.contacts),
        "controlled_contact_cards": sorted(set(controlled_contacts)),
        "components": parts,
        **blast_metadata,
    }
    return "\n".join(lines) + "\n", metadata


def build_component_geometry(component: JSONDict, pid: int) -> tuple[list[Node], list[ShellElement], list[SolidElement], JSONDict]:
    template = str(component["template"])
    component_definition(template)
    if template == "beam_bar":
        return build_beam_bar_component(component, pid)
    if template == "circular_plate":
        return build_circular_plate_component(component, pid)
    if template == "commercial_supermarket":
        return build_commercial_supermarket_component(component, pid)
    if template == "shell_box":
        return build_shell_box_component(component, pid)
    if template == "shell_plate":
        return build_shell_plate_component(component, pid)
    if template == "shell_tube":
        return build_shell_tube_component(component, pid)
    if template == "solid_block":
        return build_solid_block_component(component, pid)
    if template == "solid_cylinder":
        return build_solid_cylinder_component(component, pid)
    if template == "ellipsoid_shell":
        return build_ellipsoid_shell_component(component, pid)
    if template == "parking_lot":
        return build_parking_lot_component(component, pid)
    if template == "parked_vehicle":
        return build_parked_vehicle_component(component, pid)
    if template == "residential_community":
        return build_residential_community_component(component, pid)
    if template == "sphere_shell":
        return build_sphere_shell_component(component, pid)
    if template == "subway_entrance":
        return build_subway_entrance_component(component, pid)
    if template == "traffic_light":
        return build_traffic_light_component(component, pid)
    raise ValueError(f"unsupported component template: {template}")


def _primitive_component(
    template: str,
    geometry: JSONDict,
    mesh_size: float,
) -> JSONDict:
    return {
        "id": template,
        "template": template,
        "geometry": geometry,
        "mesh": {"size_m": mesh_size},
        "material": {"name": "mild_steel"},
    }


def _merge_local_geometry(
    pieces: list[tuple[list[Node], list[ShellElement], list[SolidElement], tuple[float, float, float]]],
    pid: int,
    *,
    weld_tolerance: float | None = None,
) -> tuple[list[Node], list[ShellElement], list[SolidElement]]:
    nodes: list[Node] = []
    shells: list[ShellElement] = []
    solids: list[SolidElement] = []
    welded_nodes: dict[tuple[int, int, int], int] = {}
    next_node = 1
    next_shell = 1
    next_solid = 1
    for local_nodes, local_shells, local_solids, offset in pieces:
        node_map: dict[int, int] = {}
        ox, oy, oz = offset
        for old_nid, x, y, z in local_nodes:
            coordinates = (x + ox, y + oy, z + oz)
            welded_id: int | None = None
            if weld_tolerance is not None:
                key = tuple(
                    round(value / weld_tolerance)
                    for value in coordinates
                )
                welded_id = welded_nodes.get(key)
            if welded_id is None:
                welded_id = next_node
                nodes.append((next_node, *coordinates))
                next_node += 1
                if weld_tolerance is not None:
                    welded_nodes[key] = welded_id
            node_map[old_nid] = welded_id
        for element in local_shells:
            shells.append((next_shell, pid, *(node_map[nid] for nid in element[2:6])))
            next_shell += 1
        for element in local_solids:
            solids.append((next_solid, pid, *(node_map[nid] for nid in element[2:10])))
            next_solid += 1
    return nodes, shells, solids


def _shell_box_piece(
    geometry: JSONDict,
    mesh_size: float,
    pid: int,
    offset: tuple[float, float, float],
) -> tuple[list[Node], list[ShellElement], list[SolidElement], tuple[float, float, float]]:
    nodes, shells, solids, _metadata = build_shell_box_component(
        _primitive_component("shell_box", geometry, mesh_size),
        pid,
    )
    return nodes, shells, solids, offset


def _open_shell_box_piece(
    geometry: JSONDict,
    mesh_size: float,
    pid: int,
    offset: tuple[float, float, float],
    *,
    attached_faces: tuple[str, ...] = (),
) -> tuple[list[Node], list[ShellElement], list[SolidElement], tuple[float, float, float]]:
    nodes, shells, solids, piece_offset = _shell_box_piece(
        geometry,
        mesh_size,
        pid,
        offset,
    )
    if not attached_faces:
        return nodes, shells, solids, piece_offset
    coordinates = {
        node_id: (float(x), float(y), float(z))
        for node_id, x, y, z in nodes
    }
    axis_by_face = {
        "x_min": (0, min),
        "x_max": (0, max),
        "y_min": (1, min),
        "y_max": (1, max),
        "z_min": (2, min),
        "z_max": (2, max),
    }
    face_targets: list[tuple[int, float]] = []
    for face in attached_faces:
        if face not in axis_by_face:
            raise ValueError(f"unsupported attached shell-box face: {face}")
        axis, reducer = axis_by_face[face]
        target = reducer(point[axis] for point in coordinates.values())
        face_targets.append((axis, target))
    tolerance = 1.0e-12
    shells = [
        element
        for element in shells
        if not any(
            all(
                math.isclose(
                    coordinates[node_id][axis],
                    target,
                    abs_tol=tolerance,
                )
                for node_id in element[2:6]
            )
            for axis, target in face_targets
        )
    ]
    referenced_node_ids = {
        node_id
        for element in shells
        for node_id in element[2:6]
    }
    referenced_node_ids.update(
        node_id
        for element in solids
        for node_id in element[2:10]
    )
    nodes = [
        node
        for node in nodes
        if node[0] in referenced_node_ids
    ]
    return nodes, shells, solids, piece_offset


def build_commercial_supermarket_component(
    component: JSONDict,
    pid: int,
) -> tuple[list[Node], list[ShellElement], list[SolidElement], JSONDict]:
    g = component["geometry"]
    mesh_size = float(component["mesh"]["size_m"])
    length = float(g["length_m"])
    width = float(g["width_m"])
    height = float(g["height_m"])
    thickness = float(g["wall_thickness_m"])
    entrance_width = float(g["entrance_width_m"])
    entrance_height = float(g["entrance_height_m"])
    if not 0.0 < entrance_width < length or not 0.0 < entrance_height < height:
        raise ValueError("commercial_supermarket entrance dimensions must fit the facade")
    response_mode = component.get("structural_response_mode")
    if response_mode == "supported_shell_details":
        nx = grid_count(length, mesh_size)
        ny = grid_count(width, mesh_size)
        nz = grid_count(height, mesh_size)
        dx = length / nx
        dy = width / ny
        dz = height / nz
        center_index = nx // 2
        entrance_half_cells = max(
            1,
            math.ceil(0.5 * (entrance_width + 1.5) / dx),
        )
        canopy_start_index = max(0, center_index - entrance_half_cells)
        canopy_end_index = min(nx, center_index + entrance_half_cells)
        if canopy_end_index <= canopy_start_index:
            canopy_end_index = min(nx, canopy_start_index + 1)
        canopy_x0 = canopy_start_index * dx
        canopy_length = (canopy_end_index - canopy_start_index) * dx
        canopy_depth = max(1.5, dy)
        attach_z_index = min(
            nz - 1,
            max(1, round(entrance_height / dz)),
        )
        attach_z = attach_z_index * dz
        column_width = dx
        column_depth = min(canopy_depth, max(0.6, 0.5 * dy))
        sign_start_index = max(1, round(0.175 * nx))
        sign_end_index = min(nx - 1, max(sign_start_index + 1, round(0.825 * nx)))
        sign_z_index = min(nz - 1, max(1, round(0.65 * nz)))
        roof_x0_index = max(1, round(0.375 * nx))
        roof_x1_index = min(
            nx - 1,
            max(roof_x0_index + 1, round(0.625 * nx)),
        )
        roof_y0_index = max(1, round(0.35 * ny))
        roof_y1_index = min(
            ny - 1,
            max(roof_y0_index + 1, round(0.60 * ny)),
        )
        pieces = [
            _shell_box_piece(
                {
                    "length_m": length,
                    "width_m": width,
                    "height_m": height,
                    "thickness_m": thickness,
                },
                mesh_size,
                pid,
                (0.0, 0.0, 0.0),
            ),
            _open_shell_box_piece(
                {
                    "length_m": canopy_length,
                    "width_m": canopy_depth,
                    "height_m": 0.35,
                    "thickness_m": thickness,
                },
                mesh_size,
                pid,
                (canopy_x0, -canopy_depth, attach_z),
                attached_faces=("y_max",),
            ),
            _open_shell_box_piece(
                {
                    "length_m": column_width,
                    "width_m": column_depth,
                    "height_m": attach_z,
                    "thickness_m": thickness,
                },
                mesh_size,
                pid,
                (canopy_x0, -column_depth, 0.0),
                attached_faces=("y_max",),
            ),
            _open_shell_box_piece(
                {
                    "length_m": column_width,
                    "width_m": column_depth,
                    "height_m": attach_z,
                    "thickness_m": thickness,
                },
                mesh_size,
                pid,
                (canopy_x0 + canopy_length - column_width, -column_depth, 0.0),
                attached_faces=("y_max",),
            ),
            _open_shell_box_piece(
                {
                    "length_m": (sign_end_index - sign_start_index) * dx,
                    "width_m": 0.35,
                    "height_m": 0.9,
                    "thickness_m": thickness,
                },
                mesh_size,
                pid,
                (sign_start_index * dx, -0.35, sign_z_index * dz),
                attached_faces=("y_max",),
            ),
            _open_shell_box_piece(
                {
                    "length_m": (roof_x1_index - roof_x0_index) * dx,
                    "width_m": (roof_y1_index - roof_y0_index) * dy,
                    "height_m": 1.2,
                    "thickness_m": thickness,
                },
                mesh_size,
                pid,
                (roof_x0_index * dx, roof_y0_index * dy, height),
                attached_faces=("z_min",),
            ),
        ]
    else:
        pieces = [
            _shell_box_piece(
                {"length_m": length, "width_m": width, "height_m": height, "thickness_m": thickness},
                mesh_size,
                pid,
                (0.0, 0.0, 0.0),
            ),
            _shell_box_piece(
                {
                    "length_m": entrance_width + 1.5,
                    "width_m": 1.5,
                    "height_m": 0.35,
                    "thickness_m": thickness,
                },
                mesh_size,
                pid,
                ((length - entrance_width - 1.5) * 0.5, -1.5, entrance_height),
            ),
            _shell_box_piece(
                {
                    "length_m": 0.6,
                    "width_m": 0.6,
                    "height_m": entrance_height,
                    "thickness_m": thickness,
                },
                mesh_size,
                pid,
                ((length - entrance_width) * 0.5 - 0.3, -0.3, 0.0),
            ),
            _shell_box_piece(
                {
                    "length_m": 0.6,
                    "width_m": 0.6,
                    "height_m": entrance_height,
                    "thickness_m": thickness,
                },
                mesh_size,
                pid,
                ((length + entrance_width) * 0.5 - 0.3, -0.3, 0.0),
            ),
            _shell_box_piece(
                {
                    "length_m": length * 0.65,
                    "width_m": 0.35,
                    "height_m": 0.9,
                    "thickness_m": thickness,
                },
                mesh_size,
                pid,
                (length * 0.175, -0.35, height * 0.65),
            ),
            _shell_box_piece(
                {
                    "length_m": length * 0.25,
                    "width_m": width * 0.25,
                    "height_m": 1.2,
                    "thickness_m": thickness,
                },
                mesh_size,
                pid,
                (length * 0.375, width * 0.35, height),
            ),
        ]
    if response_mode == "supported_shell_envelope":
        pieces = pieces[:1]
    nodes, shells, solids = _merge_local_geometry(
        pieces,
        pid,
        weld_tolerance=1.0e-9 if response_mode == "supported_shell_details" else None,
    )
    return nodes, shells, solids, {
        "type": "shell",
        "thickness_m": thickness,
        "detail_count": len(pieces) - 1,
        "details": ["entrance_canopy", "facade_columns", "sign_band", "roof_service_room"],
    }


def build_residential_community_component(
    component: JSONDict,
    pid: int,
) -> tuple[list[Node], list[ShellElement], list[SolidElement], JSONDict]:
    g = component["geometry"]
    mesh_size = float(component["mesh"]["size_m"])
    tower_length = float(g["tower_length_m"])
    tower_width = float(g["tower_width_m"])
    tower_height = float(g["tower_height_m"])
    tower_count = int(g["tower_count"])
    spacing = float(g["tower_spacing_m"])
    thickness = float(g["wall_thickness_m"])
    balcony_depth = float(g["balcony_depth_m"])
    if not 1 <= tower_count <= 6:
        raise ValueError("residential_community tower_count must be between 1 and 6")
    pieces = []
    response_mode = component.get("structural_response_mode")
    supported_envelope = response_mode == "supported_shell_envelope"
    supported_details = response_mode == "supported_shell_details"
    nx = grid_count(tower_length, mesh_size)
    ny = grid_count(tower_width, mesh_size)
    nz = grid_count(tower_height, mesh_size)
    dx = tower_length / nx
    dy = tower_width / ny
    dz = tower_height / nz
    for index in range(tower_count):
        x0 = index * (tower_length + spacing)
        pieces.append(
            _shell_box_piece(
                {
                    "length_m": tower_length,
                    "width_m": tower_width,
                    "height_m": tower_height,
                    "thickness_m": thickness,
                },
                mesh_size,
                pid,
                (x0, 0.0, 0.0),
            )
        )
        if supported_details:
            roof_x0_index = 1 if nx > 2 else 0
            roof_x1_index = nx - 1 if nx > 2 else nx
            roof_y0_index = 1 if ny > 2 else 0
            roof_y1_index = ny - 1 if ny > 2 else ny
            pieces.append(
                _open_shell_box_piece(
                    {
                        "length_m": (roof_x1_index - roof_x0_index) * dx,
                        "width_m": (roof_y1_index - roof_y0_index) * dy,
                        "height_m": 1.5,
                        "thickness_m": thickness,
                    },
                    mesh_size,
                    pid,
                    (
                        x0 + roof_x0_index * dx,
                        roof_y0_index * dy,
                        tower_height,
                    ),
                    attached_faces=("z_min",),
                )
            )
            balcony_x0_index = 1 if nx > 2 else 0
            balcony_x1_index = nx - 1 if nx > 2 else nx
            for level_fraction in (0.28, 0.52, 0.76):
                level_index = min(
                    nz - 1,
                    max(1, round(level_fraction * nz)),
                )
                pieces.append(
                    _open_shell_box_piece(
                        {
                            "length_m": (
                                balcony_x1_index - balcony_x0_index
                            )
                            * dx,
                            "width_m": balcony_depth,
                            "height_m": 0.18,
                            "thickness_m": thickness,
                        },
                        mesh_size,
                        pid,
                        (
                            x0 + balcony_x0_index * dx,
                            -balcony_depth,
                            level_index * dz,
                        ),
                        attached_faces=("y_max",),
                    )
                )
        elif not supported_envelope:
            pieces.append(
                _shell_box_piece(
                    {
                        "length_m": tower_length * 0.4,
                        "width_m": tower_width * 0.35,
                        "height_m": 1.5,
                        "thickness_m": thickness,
                    },
                    mesh_size,
                    pid,
                    (
                        x0 + tower_length * 0.3,
                        tower_width * 0.325,
                        tower_height,
                    ),
                )
            )
            for level_fraction in (0.28, 0.52, 0.76):
                pieces.append(
                    _shell_box_piece(
                        {
                            "length_m": tower_length * 0.72,
                            "width_m": balcony_depth,
                            "height_m": 0.18,
                            "thickness_m": thickness,
                        },
                        mesh_size,
                        pid,
                        (
                            x0 + tower_length * 0.14,
                            -balcony_depth,
                            tower_height * level_fraction,
                        ),
                    )
                )
    total_length = tower_count * tower_length + (tower_count - 1) * spacing
    if supported_details:
        for index in range(tower_count - 1):
            pieces.append(
                _open_shell_box_piece(
                    {
                        "length_m": spacing,
                        "width_m": tower_width,
                        "height_m": min(1.2, dz),
                        "thickness_m": thickness,
                    },
                    mesh_size,
                    pid,
                    (
                        index * (tower_length + spacing) + tower_length,
                        0.0,
                        0.0,
                    ),
                    attached_faces=("x_min", "x_max"),
                )
            )
    elif not supported_envelope:
        pieces.append(
            _shell_box_piece(
                {
                    "length_m": total_length,
                    "width_m": tower_width + 2.0,
                    "height_m": 1.2,
                    "thickness_m": thickness,
                },
                mesh_size,
                pid,
                (0.0, -1.0, 0.0),
            )
        )
    nodes, shells, solids = _merge_local_geometry(
        pieces,
        pid,
        weld_tolerance=1.0e-9 if supported_details else None,
    )
    return nodes, shells, solids, {
        "type": "shell",
        "thickness_m": thickness,
        "tower_count": tower_count,
        "detail_count": len(pieces) - tower_count,
        "details": ["roof_service_rooms", "balcony_bands", "shared_podium"],
    }


def build_parking_lot_component(
    component: JSONDict,
    pid: int,
) -> tuple[list[Node], list[ShellElement], list[SolidElement], JSONDict]:
    g = component["geometry"]
    mesh_size = float(component["mesh"]["size_m"])
    thickness = float(g["thickness_m"])
    base_nodes, base_shells, base_solids, _meta = build_shell_plate_component(
        _primitive_component(
            "shell_plate",
            {
                "length_m": float(g["length_m"]),
                "width_m": float(g["width_m"]),
                "thickness_m": thickness,
            },
            mesh_size,
        ),
        pid,
    )
    return base_nodes, base_shells, base_solids, {
        "type": "shell",
        "thickness_m": thickness,
        "parking_rows": int(g["parking_rows"]),
        "spaces_per_row": int(g["spaces_per_row"]),
        "detail_count": int(g["parking_rows"]) * int(g["spaces_per_row"]),
    }


def build_parked_vehicle_component(
    component: JSONDict,
    pid: int,
) -> tuple[list[Node], list[ShellElement], list[SolidElement], JSONDict]:
    g = component["geometry"]
    mesh_size = float(component["mesh"]["size_m"])
    length = float(g["length_m"])
    width = float(g["width_m"])
    body_height = float(g["body_height_m"])
    cabin_height = float(g["cabin_height_m"])
    thickness = float(g["shell_thickness_m"])
    if min(length, width, body_height, cabin_height, thickness) <= 0.0:
        raise ValueError("parked_vehicle dimensions must be positive")
    cabin_length = 0.5 * length
    cabin_width = 0.82 * width
    bumper_depth = min(0.18, 0.04 * length)
    bumper_height = min(0.18, 0.25 * body_height)
    bumper_base = min(0.18, max(0.0, body_height - bumper_height))
    nodes, shells = _connected_shell_box_union(
        [
            (0.0, length, 0.0, width, 0.0, body_height),
            (
                0.25 * length,
                0.25 * length + cabin_length,
                0.09 * width,
                0.09 * width + cabin_width,
                body_height,
                body_height + cabin_height,
            ),
            (
                -bumper_depth,
                0.0,
                0.0,
                width,
                bumper_base,
                bumper_base + bumper_height,
            ),
            (
                length,
                length + bumper_depth,
                0.0,
                width,
                bumper_base,
                bumper_base + bumper_height,
            ),
        ],
        mesh_size,
        pid,
    )
    return nodes, shells, [], {
        "type": "shell",
        "thickness_m": thickness,
        "detail_count": 3,
        "details": ["raised_cabin", "front_bumper", "rear_bumper"],
        "mobility": "free_to_translate_and_deform",
        "topology": "connected_box_union_shell",
    }


def _connected_shell_box_union(
    boxes: list[tuple[float, float, float, float, float, float]],
    mesh_size: float,
    pid: int,
) -> tuple[list[Node], list[ShellElement]]:
    def axis_values(values: set[float]) -> list[float]:
        breakpoints = sorted(values)
        coordinates = [breakpoints[0]]
        for lower, upper in zip(breakpoints, breakpoints[1:]):
            count = grid_count(upper - lower, mesh_size)
            coordinates.extend(
                lower + (upper - lower) * index / count
                for index in range(1, count + 1)
            )
        return coordinates

    xs = axis_values({value for box in boxes for value in box[0:2]})
    ys = axis_values({value for box in boxes for value in box[2:4]})
    zs = axis_values({value for box in boxes for value in box[4:6]})

    occupied: set[tuple[int, int, int]] = set()
    for ix in range(len(xs) - 1):
        x = 0.5 * (xs[ix] + xs[ix + 1])
        for iy in range(len(ys) - 1):
            y = 0.5 * (ys[iy] + ys[iy + 1])
            for iz in range(len(zs) - 1):
                z = 0.5 * (zs[iz] + zs[iz + 1])
                if any(
                    xmin < x < xmax
                    and ymin < y < ymax
                    and zmin < z < zmax
                    for xmin, xmax, ymin, ymax, zmin, zmax in boxes
                ):
                    occupied.add((ix, iy, iz))

    nodes: list[Node] = []
    node_ids: dict[tuple[int, int, int], int] = {}

    def node(ix: int, iy: int, iz: int) -> int:
        key = (ix, iy, iz)
        if key not in node_ids:
            node_ids[key] = len(nodes) + 1
            nodes.append((node_ids[key], xs[ix], ys[iy], zs[iz]))
        return node_ids[key]

    shells: list[ShellElement] = []

    def add(indices: tuple[tuple[int, int, int], ...]) -> None:
        shells.append(
            (
                len(shells) + 1,
                pid,
                *(node(*indices[index]) for index in range(4)),
            )
        )

    for ix, iy, iz in sorted(occupied):
        if (ix - 1, iy, iz) not in occupied:
            add(((ix, iy, iz), (ix, iy, iz + 1), (ix, iy + 1, iz + 1), (ix, iy + 1, iz)))
        if (ix + 1, iy, iz) not in occupied:
            add(((ix + 1, iy, iz), (ix + 1, iy + 1, iz), (ix + 1, iy + 1, iz + 1), (ix + 1, iy, iz + 1)))
        if (ix, iy - 1, iz) not in occupied:
            add(((ix, iy, iz), (ix + 1, iy, iz), (ix + 1, iy, iz + 1), (ix, iy, iz + 1)))
        if (ix, iy + 1, iz) not in occupied:
            add(((ix, iy + 1, iz), (ix, iy + 1, iz + 1), (ix + 1, iy + 1, iz + 1), (ix + 1, iy + 1, iz)))
        if (ix, iy, iz - 1) not in occupied:
            add(((ix, iy, iz), (ix, iy + 1, iz), (ix + 1, iy + 1, iz), (ix + 1, iy, iz)))
        if (ix, iy, iz + 1) not in occupied:
            add(((ix, iy, iz + 1), (ix + 1, iy, iz + 1), (ix + 1, iy + 1, iz + 1), (ix, iy + 1, iz + 1)))
    return nodes, shells


def build_subway_entrance_component(
    component: JSONDict,
    pid: int,
) -> tuple[list[Node], list[ShellElement], list[SolidElement], JSONDict]:
    g = component["geometry"]
    mesh_size = float(component["mesh"]["size_m"])
    length = float(g["length_m"])
    width = float(g["width_m"])
    platform_height = float(g["platform_height_m"])
    enclosure_height = float(g["enclosure_height_m"])
    wall = float(g["wall_thickness_m"])
    roof = float(g["roof_thickness_m"])
    response_mode = component.get("structural_response_mode")
    if response_mode == "supported_shell_envelope":
        nodes, shells, solids, _metadata = build_shell_box_component(
            _primitive_component(
                "shell_box",
                {
                    "length_m": length,
                    "width_m": width,
                    "height_m": platform_height + enclosure_height + roof,
                    "thickness_m": wall,
                },
                mesh_size,
            ),
            pid,
        )
        return nodes, shells, solids, {
            "type": "shell",
            "thickness_m": wall,
            "platform_height_m": platform_height,
            "enclosure": "supported_shell_envelope",
            "detail_count": 0,
        }
    boxes = [
        (0.0, length, 0.0, width, 0.0, platform_height),
        (
            0.0,
            length,
            width - wall,
            width,
            platform_height,
            platform_height + enclosure_height,
        ),
        (
            0.0,
            wall,
            0.0,
            width,
            platform_height,
            platform_height + enclosure_height,
        ),
        (
            length - wall,
            length,
            0.0,
            width,
            platform_height,
            platform_height + enclosure_height,
        ),
        (
            0.0,
            length,
            0.0,
            width,
            platform_height + enclosure_height,
            platform_height + enclosure_height + roof,
        ),
    ]
    step_count = 5
    step_depth = width * 0.55 / step_count
    opening_width = length - 2.0 * wall
    for index in range(step_count):
        boxes.append(
            (
                wall,
                wall + opening_width,
                index * step_depth,
                (index + 1) * step_depth,
                0.0,
                max(
                    0.05,
                    platform_height * (step_count - index) / step_count,
                ),
            )
        )
    nodes, shells = _connected_shell_box_union(
        boxes,
        mesh_size,
        pid,
    )
    return nodes, shells, [], {
        "type": "shell",
        "thickness_m": wall,
        "platform_height_m": platform_height,
        "enclosure": "front_open_three_sides_enclosed",
        "detail_count": step_count + 4,
        "topology": "connected_box_union_shell",
    }


def build_traffic_light_component(
    component: JSONDict,
    pid: int,
) -> tuple[list[Node], list[ShellElement], list[SolidElement], JSONDict]:
    g = component["geometry"]
    mesh_size = min(float(component["mesh"]["size_m"]), 0.1)
    pole_height = float(g["pole_height_m"])
    pole_radius = float(g["pole_radius_m"])
    arm_length = float(g["arm_length_m"])
    head_width = float(g["head_width_m"])
    head_height = float(g["head_height_m"])
    thickness = float(g["thickness_m"])
    pole_nodes, pole_shells, pole_solids, _pole_meta = build_shell_tube_component(
        _primitive_component(
            "shell_tube",
            {"radius_m": pole_radius, "length_m": pole_height, "thickness_m": thickness},
            mesh_size,
        ),
        pid,
    )
    pieces = [
        (pole_nodes, pole_shells, pole_solids, (0.0, 0.0, 0.0)),
        _shell_box_piece(
            {
                "length_m": arm_length,
                "width_m": 2.0 * pole_radius,
                "height_m": 2.0 * pole_radius,
                "thickness_m": thickness,
            },
            mesh_size,
            pid,
            (0.0, -pole_radius, pole_height - pole_radius),
        ),
        _shell_box_piece(
            {
                "length_m": head_width,
                "width_m": max(head_width * 0.6, 0.1),
                "height_m": head_height,
                "thickness_m": thickness,
            },
            mesh_size,
            pid,
            (arm_length - head_width, -head_width * 0.3, pole_height - head_height),
        ),
    ]
    nodes, shells, solids = _merge_local_geometry(
        pieces,
        pid,
        weld_tolerance=1.0e-9,
    )
    return nodes, shells, solids, {
        "type": "shell",
        "thickness_m": thickness,
        "detail_count": 2,
        "details": ["mast_arm", "signal_head"],
    }


def build_shell_plate_component(component: JSONDict, pid: int) -> tuple[list[Node], list[ShellElement], list[SolidElement], JSONDict]:
    geometry = component["geometry"]
    mesh = component["mesh"]
    length = float(geometry["length_m"])
    width = float(geometry["width_m"])
    thickness = float(geometry["thickness_m"])
    mesh_size = float(mesh["size_m"])
    nx = grid_count(length, mesh_size)
    ny = grid_count(width, mesh_size)
    dx = length / nx
    dy = width / ny
    nodes = [(iy * (nx + 1) + ix + 1, ix * dx, iy * dy, 0.0) for iy in range(ny + 1) for ix in range(nx + 1)]
    elements: list[ShellElement] = []
    eid = 1
    for iy in range(ny):
        for ix in range(nx):
            n1 = iy * (nx + 1) + ix + 1
            elements.append((eid, pid, n1, n1 + 1, n1 + nx + 2, n1 + nx + 1))
            eid += 1
    return nodes, elements, [], {"type": "shell", "thickness_m": thickness}


def build_rectangular_solid_component(
    component: JSONDict,
    pid: int,
    *,
    centered_yz: bool,
) -> tuple[list[Node], list[ShellElement], list[SolidElement], JSONDict]:
    geometry = component["geometry"]
    mesh_size = float(component["mesh"]["size_m"])
    length = float(geometry["length_m"])
    width = float(geometry["width_m"])
    height = float(geometry["height_m"])
    nx, ny, nz = grid_count(length, mesh_size), grid_count(width, mesh_size), grid_count(height, mesh_size)
    dx, dy, dz = length / nx, width / ny, height / nz

    def nid(ix: int, iy: int, iz: int) -> int:
        return iz * (ny + 1) * (nx + 1) + iy * (nx + 1) + ix + 1

    y0 = -0.5 * width if centered_yz else 0.0
    z0 = -0.5 * height if centered_yz else 0.0
    nodes = [
        (nid(ix, iy, iz), ix * dx, y0 + iy * dy, z0 + iz * dz)
        for iz in range(nz + 1)
        for iy in range(ny + 1)
        for ix in range(nx + 1)
    ]
    elements: list[SolidElement] = []
    for iz in range(nz):
        for iy in range(ny):
            for ix in range(nx):
                elements.append(
                    (
                        len(elements) + 1,
                        pid,
                        nid(ix, iy, iz),
                        nid(ix + 1, iy, iz),
                        nid(ix + 1, iy + 1, iz),
                        nid(ix, iy + 1, iz),
                        nid(ix, iy, iz + 1),
                        nid(ix + 1, iy, iz + 1),
                        nid(ix + 1, iy + 1, iz + 1),
                        nid(ix, iy + 1, iz + 1),
                    )
                )
    return nodes, [], elements, {"type": "solid", "nx": nx, "ny": ny, "nz": nz}


def build_solid_block_component(component: JSONDict, pid: int) -> tuple[list[Node], list[ShellElement], list[SolidElement], JSONDict]:
    return build_rectangular_solid_component(component, pid, centered_yz=False)


def build_beam_bar_component(component: JSONDict, pid: int) -> tuple[list[Node], list[ShellElement], list[SolidElement], JSONDict]:
    nodes, shells, solids, metadata = build_rectangular_solid_component(component, pid, centered_yz=True)
    metadata["mesh_method"] = "solid_hexa_bar"
    return nodes, shells, solids, metadata


def build_shell_tube_component(component: JSONDict, pid: int) -> tuple[list[Node], list[ShellElement], list[SolidElement], JSONDict]:
    geometry = component["geometry"]
    radius = float(geometry["radius_m"])
    length = float(geometry["length_m"])
    thickness = float(geometry["thickness_m"])
    mesh_size = float(component["mesh"]["size_m"])
    nt = max(8, round(2.0 * math.pi * radius / mesh_size))
    nz = grid_count(length, mesh_size)
    dz = length / nz

    def nid(it: int, iz: int) -> int:
        return iz * nt + (it % nt) + 1

    nodes = [
        (nid(it, iz), radius * math.cos(2.0 * math.pi * it / nt), radius * math.sin(2.0 * math.pi * it / nt), iz * dz)
        for iz in range(nz + 1)
        for it in range(nt)
    ]
    elements: list[ShellElement] = []
    for iz in range(nz):
        for it in range(nt):
            elements.append((len(elements) + 1, pid, nid(it, iz), nid(it + 1, iz), nid(it + 1, iz + 1), nid(it, iz + 1)))
    return nodes, elements, [], {"type": "shell", "thickness_m": thickness, "nt": nt, "nz": nz}


def build_shell_box_component(component: JSONDict, pid: int) -> tuple[list[Node], list[ShellElement], list[SolidElement], JSONDict]:
    geometry = component["geometry"]
    length, width, height = (float(geometry[key]) for key in ("length_m", "width_m", "height_m"))
    thickness = float(geometry["thickness_m"])
    mesh_size = float(component["mesh"]["size_m"])
    nx, ny, nz = grid_count(length, mesh_size), grid_count(width, mesh_size), grid_count(height, mesh_size)
    dx, dy, dz = length / nx, width / ny, height / nz
    lookup: dict[tuple[int, int, int], int] = {}
    nodes: list[Node] = []

    def node(ix: int, iy: int, iz: int) -> int:
        key = (ix, iy, iz)
        if key not in lookup:
            lookup[key] = len(nodes) + 1
            nodes.append((lookup[key], ix * dx, iy * dy, iz * dz))
        return lookup[key]

    elements: list[ShellElement] = []
    def add(n1: int, n2: int, n3: int, n4: int) -> None:
        elements.append((len(elements) + 1, pid, n1, n2, n3, n4))

    for iz in (0, nz):
        for iy in range(ny):
            for ix in range(nx):
                add(node(ix, iy, iz), node(ix + 1, iy, iz), node(ix + 1, iy + 1, iz), node(ix, iy + 1, iz))
    for iy in (0, ny):
        for iz in range(nz):
            for ix in range(nx):
                add(node(ix, iy, iz), node(ix + 1, iy, iz), node(ix + 1, iy, iz + 1), node(ix, iy, iz + 1))
    for ix in (0, nx):
        for iz in range(nz):
            for iy in range(ny):
                add(node(ix, iy, iz), node(ix, iy + 1, iz), node(ix, iy + 1, iz + 1), node(ix, iy, iz + 1))
    return nodes, elements, [], {"type": "shell", "thickness_m": thickness, "nx": nx, "ny": ny, "nz": nz}


def build_circular_plate_component(component: JSONDict, pid: int) -> tuple[list[Node], list[ShellElement], list[SolidElement], JSONDict]:
    geometry = component["geometry"]
    radius = float(geometry["radius_m"])
    thickness = float(geometry["thickness_m"])
    mesh_size = float(component["mesh"]["size_m"])
    nxy = max(4, 2 * grid_count(radius, mesh_size))
    nodes: list[Node] = []
    for iy in range(nxy + 1):
        v = -1.0 + 2.0 * iy / nxy
        for ix in range(nxy + 1):
            u = -1.0 + 2.0 * ix / nxy
            x, y = square_to_disk(radius, u, v)
            nodes.append((len(nodes) + 1, x, y, 0.0))

    def node(ix: int, iy: int) -> int:
        return iy * (nxy + 1) + ix + 1

    elements: list[ShellElement] = []
    for iy in range(nxy):
        for ix in range(nxy):
            elements.append(
                (
                    len(elements) + 1,
                    pid,
                    node(ix, iy),
                    node(ix + 1, iy),
                    node(ix + 1, iy + 1),
                    node(ix, iy + 1),
                )
            )
    return nodes, elements, [], {
        "type": "shell",
        "thickness_m": thickness,
        "mesh_method": "mapped_square_to_disk_quad_plate",
        "nxy": nxy,
    }


def build_solid_cylinder_component(component: JSONDict, pid: int) -> tuple[list[Node], list[ShellElement], list[SolidElement], JSONDict]:
    geometry = component["geometry"]
    mesh = component["mesh"]
    radius = float(geometry["radius_m"])
    length = float(geometry["length_m"])
    mesh_size = float(mesh["size_m"])
    nxy = max(8, 2 * grid_count(radius, mesh_size))
    nz = grid_count(length, mesh_size)
    dz = length / nz

    nodes: list[Node] = []

    def get_node(ix: int, iy: int, iz: int) -> int:
        return iz * (nxy + 1) * (nxy + 1) + iy * (nxy + 1) + ix + 1

    for iz in range(nz + 1):
        z = iz * dz
        for iy in range(nxy + 1):
            v = -1.0 + 2.0 * iy / nxy
            for ix in range(nxy + 1):
                u = -1.0 + 2.0 * ix / nxy
                x, y = square_to_disk(radius, u, v)
                nodes.append((get_node(ix, iy, iz), x, y, z))

    elements: list[SolidElement] = []
    for iz in range(nz):
        for iy in range(nxy):
            for ix in range(nxy):
                elements.append(
                    (
                        len(elements) + 1,
                        pid,
                        get_node(ix, iy, iz),
                        get_node(ix + 1, iy, iz),
                        get_node(ix + 1, iy + 1, iz),
                        get_node(ix, iy + 1, iz),
                        get_node(ix, iy, iz + 1),
                        get_node(ix + 1, iy, iz + 1),
                        get_node(ix + 1, iy + 1, iz + 1),
                        get_node(ix, iy + 1, iz + 1),
                    )
                )
    return nodes, [], elements, {"type": "solid", "mesh_method": "mapped_square_to_disk_hexa_cylinder", "nxy": nxy, "nz": nz}


def square_to_disk(radius: float, u: float, v: float) -> tuple[float, float]:
    x = radius * u * math.sqrt(max(0.0, 1.0 - 0.5 * v * v))
    y = radius * v * math.sqrt(max(0.0, 1.0 - 0.5 * u * u))
    return x, y


def build_ellipsoid_shell_component(component: JSONDict, pid: int) -> tuple[list[Node], list[ShellElement], list[SolidElement], JSONDict]:
    geometry = component["geometry"]
    mesh = component["mesh"]
    rx = float(geometry["radius_x_m"])
    ry = float(geometry["radius_y_m"])
    height = float(geometry["height_m"])
    thickness = float(geometry["thickness_m"])
    mesh_size = float(mesh["size_m"])
    meridian_length = 0.5 * math.pi * max(rx, ry, height)
    nz = max(3, grid_count(meridian_length, mesh_size))
    target_nt = max(12, round(2.0 * math.pi * max(rx, ry) / mesh_size))
    # A constant ring topology becomes excessively slender near the pole when
    # circumferential refinement greatly exceeds meridional refinement.
    nt = min(target_nt, max(12, round(2.4 * nz)))

    nodes: list[Node] = []
    for iz in range(nz):
        polar_angle = 0.5 * math.pi * iz / nz
        z = height * math.sin(polar_angle)
        scale = math.cos(polar_angle)
        for it in range(nt):
            angle = 2.0 * math.pi * it / nt
            nodes.append((iz * nt + it + 1, rx * scale * math.cos(angle), ry * scale * math.sin(angle), z))
    top_node = len(nodes) + 1
    nodes.append((top_node, 0.0, 0.0, height))

    elements: list[ShellElement] = []
    eid = 1
    for iz in range(nz - 1):
        for it in range(nt):
            n1 = iz * nt + it + 1
            n2 = iz * nt + ((it + 1) % nt) + 1
            n3 = (iz + 1) * nt + ((it + 1) % nt) + 1
            n4 = (iz + 1) * nt + it + 1
            elements.append((eid, pid, n1, n2, n3, n4))
            eid += 1
    last_ring = (nz - 1) * nt
    for it in range(nt):
        n1 = last_ring + it + 1
        n2 = last_ring + ((it + 1) % nt) + 1
        elements.append((eid, pid, n1, n2, top_node, top_node))
        eid += 1
    return nodes, elements, [], {
        "type": "shell",
        "thickness_m": thickness,
        "mesh_method": "polar_angle_ellipsoid_quad_shell",
        "nt": nt,
        "nz": nz,
    }


def build_sphere_shell_component(component: JSONDict, pid: int) -> tuple[list[Node], list[ShellElement], list[SolidElement], JSONDict]:
    geometry = component["geometry"]
    radius = float(geometry["radius_m"])
    thickness = float(geometry["thickness_m"])
    mesh_size = float(component["mesh"]["size_m"])
    nt = max(12, round(2.0 * math.pi * radius / mesh_size))
    np = max(4, round(math.pi * radius / mesh_size))
    nodes: list[Node] = [(1, 0.0, 0.0, radius)]
    for ip in range(1, np):
        phi = math.pi * ip / np
        ring_radius = radius * math.sin(phi)
        z = radius * math.cos(phi)
        for it in range(nt):
            theta = 2.0 * math.pi * it / nt
            nodes.append((len(nodes) + 1, ring_radius * math.cos(theta), ring_radius * math.sin(theta), z))
    bottom_node = len(nodes) + 1
    nodes.append((bottom_node, 0.0, 0.0, -radius))

    def ring_node(ip: int, it: int) -> int:
        return 2 + (ip - 1) * nt + (it % nt)

    elements: list[ShellElement] = []
    for it in range(nt):
        n1, n2 = ring_node(1, it), ring_node(1, it + 1)
        elements.append((len(elements) + 1, pid, 1, n1, n2, n2))
    for ip in range(1, np - 1):
        for it in range(nt):
            elements.append(
                (len(elements) + 1, pid, ring_node(ip, it), ring_node(ip + 1, it), ring_node(ip + 1, it + 1), ring_node(ip, it + 1))
            )
    for it in range(nt):
        n1, n2 = ring_node(np - 1, it), ring_node(np - 1, it + 1)
        elements.append((len(elements) + 1, pid, n1, bottom_node, n2, n2))
    return nodes, elements, [], {"type": "shell", "thickness_m": thickness, "nt": nt, "np": np}


def apply_transform(nodes: list[Node], component: JSONDict) -> list[Node]:
    transform = component.get("transform", {})
    oriented = [apply_orientation_to_node(node, str(transform.get("orientation", "vertical_z"))) for node in nodes]
    rotated = [apply_euler_rotation_to_node(node, transform.get("rotate_deg", [0.0, 0.0, 0.0])) for node in oriented]
    positioned = apply_centering(rotated, transform.get("center_m"))
    tx, ty, tz = [float(value) for value in transform.get("translate_m", [0.0, 0.0, 0.0])]
    return [(nid, x + tx, y + ty, z + tz) for nid, x, y, z in positioned]


def apply_orientation_to_node(node: Node, orientation: str) -> Node:
    nid, x, y, z = node
    if orientation == "vertical_x":
        return nid, z, y, -x
    if orientation == "vertical_y":
        return nid, x, z, -y
    return node


def apply_euler_rotation_to_node(node: Node, rotate_deg: object) -> Node:
    nid, x, y, z = node
    if not isinstance(rotate_deg, list | tuple) or len(rotate_deg) != 3:
        return node
    rx, ry, rz = [math.radians(float(value)) for value in rotate_deg]
    cy, sy = math.cos(rx), math.sin(rx)
    y, z = y * cy - z * sy, y * sy + z * cy
    cy, sy = math.cos(ry), math.sin(ry)
    x, z = x * cy + z * sy, -x * sy + z * cy
    cy, sy = math.cos(rz), math.sin(rz)
    x, y = x * cy - y * sy, x * sy + y * cy
    return nid, x, y, z


def apply_centering(nodes: list[Node], center_m: object) -> list[Node]:
    if not isinstance(center_m, list | tuple) or len(center_m) != 3:
        return nodes
    min_x, max_x, min_y, max_y, min_z, max_z = bounds(nodes)
    cx, cy, cz = (0.5 * (min_x + max_x), 0.5 * (min_y + max_y), 0.5 * (min_z + max_z))
    target_x, target_y, target_z = [float(value) for value in center_m]
    dx, dy, dz = target_x - cx, target_y - cy, target_z - cz
    return [(nid, x + dx, y + dy, z + dz) for nid, x, y, z in nodes]


def bounds(nodes: list[Node]) -> tuple[float, float, float, float, float, float]:
    xs = [x for _, x, _, _ in nodes]
    ys = [y for _, _, y, _ in nodes]
    zs = [z for _, _, _, z in nodes]
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


def nodes_for_component_face(nodes: list[Node], face: str) -> list[int]:
    axis_map = {"x": 1, "y": 2, "z": 3}
    axis_name, side = face.split("_", 1)
    axis = axis_map[axis_name]
    values = [node[axis] for node in nodes]
    target = min(values) if side == "min" else max(values)
    span = max(values) - min(values)
    tol = max(abs(span) * 1e-9, 1e-12)
    selected = [nid for nid, x, y, z in nodes if abs((x, y, z)[axis - 1] - target) <= tol]
    if not selected:
        raise ValueError(f"component face {face} selected no nodes")
    return selected


def nodes_for_component_region(nodes: list[Node], template: str, region: str) -> list[int]:
    if template == "circular_plate" and region == "rim":
        radii = [math.hypot(x, y) for _, x, y, _ in nodes]
        target = max(radii)
        tolerance = max(target * 1.0e-9, 1.0e-12)
        selected = [nid for (nid, x, y, _), radius in zip(nodes, radii) if abs(radius - target) <= tolerance]
        if not selected:
            raise ValueError("circular_plate rim selected no nodes")
        return selected
    aliases = {
        "four_edges": ("x_min", "x_max", "y_min", "y_max"),
        "x_min_edge": ("x_min",),
        "x_max_edge": ("x_max",),
        "y_min_edge": ("y_min",),
        "y_max_edge": ("y_max",),
        "rim": ("z_min",),
        "bottom_ring": ("z_min",),
        "top_ring": ("z_max",),
        "bottom_end": ("z_min",),
        "top_end": ("z_max",),
        "start_end": ("x_min",),
        "finish_end": ("x_max",),
    }
    faces = aliases.get(region, (region,))
    selected: set[int] = set()
    for face in faces:
        selected.update(nodes_for_component_face(nodes, face))
    return sorted(selected)


def part_lines(title: str, pid: int, secid: int, mid: int) -> list[str]:
    return [
        "*PART",
        title,
        "$#   pid     secid       mid     eosid      hgid      grav    adpopt      tmid",
        f"{pid},{secid},{mid},0,0,0,0,0",
    ]


def section_lines_for_component(section: JSONDict, secid: int) -> list[str]:
    if section["type"] == "shell":
        thickness = float(section["thickness_m"])
        return [
            "*SECTION_SHELL",
            "$# secid    elform      shrf       nip     propt   qr/irid     icomp     setyp",
            f"{secid},2,0.833000,5,1.0,0,0,0",
            "$#     t1        t2        t3        t4      nloc     marea",
            f"{thickness:.9g},{thickness:.9g},{thickness:.9g},{thickness:.9g},0.0,0.0",
        ]
    return [
        "*SECTION_SOLID",
        "$# secid    elform",
        f"{secid},1",
    ]


def all_segments(shell_elements: list[ShellElement], solid_elements: list[SolidElement]) -> list[Segment]:
    shell_segments = [(n1, n2, n3, n4) for _, _, n1, n2, n3, n4 in shell_elements]
    return shell_segments + solid_segments_from_elements(solid_elements)


def empty_condition_metadata() -> JSONDict:
    return {
        "constraint_count": 0,
        "node_set_count": 0,
        "part_set_count": 0,
        "segment_set_count": 0,
        "load_count": 0,
        "initial_condition_count": 0,
        "curve_count": 0,
    }
