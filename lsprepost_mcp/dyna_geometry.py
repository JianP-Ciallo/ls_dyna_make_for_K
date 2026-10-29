from __future__ import annotations

import math

from .config import JSONDict
from .schema import ModelSpec
from .dyna_cards import (
    base_metadata,
    common_header,
    hourglass_lines,
    material_lines,
    part_header_lines,
)
from .dyna_common import grid_count, node_id
from .dyna_conditions import boundary_and_load_lines
from .dyna_selectors import shell_segments_from_elements, solid_segments_from_elements, top_level_curve_lines

def build_shell_plate(spec: ModelSpec) -> tuple[str, JSONDict]:
    length = float(spec.geometry["length_m"])
    width = float(spec.geometry["width_m"])
    thickness = float(spec.geometry["thickness_m"])
    mesh_size = float(spec.mesh["size_m"])
    nx = grid_count(length, mesh_size)
    ny = grid_count(width, mesh_size)
    dx = length / nx
    dy = width / ny

    nodes: list[tuple[int, float, float, float]] = []
    for iy in range(ny + 1):
        for ix in range(nx + 1):
            nodes.append((node_id(ix, iy, nx), ix * dx, iy * dy, 0.0))

    elements: list[tuple[int, int, int, int, int, int]] = []
    eid = 1
    for iy in range(ny):
        for ix in range(nx):
            elements.append(
                (
                    eid,
                    1,
                    node_id(ix, iy, nx),
                    node_id(ix + 1, iy, nx),
                    node_id(ix + 1, iy + 1, nx),
                    node_id(ix, iy + 1, nx),
                )
            )
            eid += 1

    lines = common_header(spec)
    lines.extend(["*NODE", "$#   nid               x               y               z"])
    lines.extend(f"{nid},{x:.9g},{y:.9g},{z:.9g}" for nid, x, y, z in nodes)
    lines.extend(["*ELEMENT_SHELL", "$#   eid     pid      n1      n2      n3      n4"])
    lines.extend(",".join(str(value) for value in element) for element in elements)
    lines.extend(
        part_header_lines(spec, f"{spec.material.get('name', 'material')}_shell_plate")
        + [
            "*SECTION_SHELL",
            "$# secid    elform      shrf       nip     propt   qr/irid     icomp     setyp",
            "1,2,0.833000,5,1.0,0,0,0",
            "$#     t1        t2        t3        t4      nloc     marea",
            f"{thickness:.9g},{thickness:.9g},{thickness:.9g},{thickness:.9g},0.0,0.0",
        ]
    )
    lines.extend(hourglass_lines(spec))
    lines.extend(top_level_curve_lines(spec))
    lines.extend(material_lines(spec))
    condition_lines, condition_metadata = boundary_and_load_lines(spec, nodes, shell_segments_from_elements(elements))
    lines.extend(condition_lines)
    lines.append("*END")
    metadata = base_metadata(spec, len(nodes), len(elements), "shell")
    metadata["mesh"] = {"nx": nx, "ny": ny, "dx_m": dx, "dy_m": dy}
    metadata.update(condition_metadata)
    return "\n".join(lines) + "\n", metadata


def build_solid_block(spec: ModelSpec) -> tuple[str, JSONDict]:
    length = float(spec.geometry["length_m"])
    width = float(spec.geometry["width_m"])
    height = float(spec.geometry["height_m"])
    mesh_size = float(spec.mesh["size_m"])
    nx = grid_count(length, mesh_size)
    ny = grid_count(width, mesh_size)
    nz = grid_count(height, mesh_size)
    dx, dy, dz = length / nx, width / ny, height / nz

    def nid(ix: int, iy: int, iz: int) -> int:
        return iz * (ny + 1) * (nx + 1) + iy * (nx + 1) + ix + 1

    nodes = [
        (nid(ix, iy, iz), ix * dx, iy * dy, iz * dz)
        for iz in range(nz + 1)
        for iy in range(ny + 1)
        for ix in range(nx + 1)
    ]
    elements = []
    eid = 1
    for iz in range(nz):
        for iy in range(ny):
            for ix in range(nx):
                elements.append(
                    (
                        eid,
                        1,
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
                eid += 1
    lines = common_header(spec)
    lines.extend(["*NODE", "$#   nid               x               y               z"])
    lines.extend(f"{nid0},{x:.9g},{y:.9g},{z:.9g}" for nid0, x, y, z in nodes)
    lines.extend(["*ELEMENT_SOLID", "$#   eid     pid      n1      n2      n3      n4      n5      n6      n7      n8"])
    lines.extend(",".join(str(value) for value in element) for element in elements)
    lines.extend(
        part_header_lines(spec, f"{spec.material.get('name', 'material')}_solid_block")
        + [
            "*SECTION_SOLID",
            "$# secid    elform",
            "1,1",
        ]
    )
    lines.extend(hourglass_lines(spec))
    lines.extend(top_level_curve_lines(spec))
    lines.extend(material_lines(spec))
    condition_lines, condition_metadata = boundary_and_load_lines(spec, nodes, solid_segments_from_elements(elements))
    lines.extend(condition_lines)
    lines.append("*END")
    metadata = base_metadata(spec, len(nodes), len(elements), "solid")
    metadata["mesh"] = {"nx": nx, "ny": ny, "nz": nz, "dx_m": dx, "dy_m": dy, "dz_m": dz}
    metadata["limitations"] = ["Regular hexahedral block mesh only; complex topology is not supported."]
    metadata.update(condition_metadata)
    return "\n".join(lines) + "\n", metadata


def build_shell_box(spec: ModelSpec) -> tuple[str, JSONDict]:
    length = float(spec.geometry["length_m"])
    width = float(spec.geometry["width_m"])
    height = float(spec.geometry["height_m"])
    thickness = float(spec.geometry["thickness_m"])
    mesh_size = float(spec.mesh["size_m"])
    nx = grid_count(length, mesh_size)
    ny = grid_count(width, mesh_size)
    nz = grid_count(height, mesh_size)
    dx, dy, dz = length / nx, width / ny, height / nz

    node_lookup: dict[tuple[int, int, int], int] = {}
    nodes: list[tuple[int, float, float, float]] = []

    def get_node(ix: int, iy: int, iz: int) -> int:
        key = (ix, iy, iz)
        if key in node_lookup:
            return node_lookup[key]
        nid0 = len(nodes) + 1
        node_lookup[key] = nid0
        nodes.append((nid0, ix * dx, iy * dy, iz * dz))
        return nid0

    elements: list[tuple[int, int, int, int, int, int]] = []

    def add_shell(n1: int, n2: int, n3: int, n4: int) -> None:
        elements.append((len(elements) + 1, 1, n1, n2, n3, n4))

    for iz in [0, nz]:
        for iy in range(ny):
            for ix in range(nx):
                add_shell(get_node(ix, iy, iz), get_node(ix + 1, iy, iz), get_node(ix + 1, iy + 1, iz), get_node(ix, iy + 1, iz))
    for iy in [0, ny]:
        for iz in range(nz):
            for ix in range(nx):
                add_shell(get_node(ix, iy, iz), get_node(ix + 1, iy, iz), get_node(ix + 1, iy, iz + 1), get_node(ix, iy, iz + 1))
    for ix in [0, nx]:
        for iz in range(nz):
            for iy in range(ny):
                add_shell(get_node(ix, iy, iz), get_node(ix, iy + 1, iz), get_node(ix, iy + 1, iz + 1), get_node(ix, iy, iz + 1))

    lines = common_header(spec)
    lines.extend(["*NODE", "$#   nid               x               y               z"])
    lines.extend(f"{nid0},{x:.9g},{y:.9g},{z:.9g}" for nid0, x, y, z in nodes)
    lines.extend(["*ELEMENT_SHELL", "$#   eid     pid      n1      n2      n3      n4"])
    lines.extend(",".join(str(value) for value in element) for element in elements)
    lines.extend(
        part_header_lines(spec, f"{spec.material.get('name', 'material')}_shell_box")
        + [
            "*SECTION_SHELL",
            "$# secid    elform      shrf       nip     propt   qr/irid     icomp     setyp",
            "1,2,0.833000,5,1.0,0,0,0",
            "$#     t1        t2        t3        t4      nloc     marea",
            f"{thickness:.9g},{thickness:.9g},{thickness:.9g},{thickness:.9g},0.0,0.0",
        ]
    )
    lines.extend(hourglass_lines(spec))
    lines.extend(top_level_curve_lines(spec))
    lines.extend(material_lines(spec))
    condition_lines, condition_metadata = boundary_and_load_lines(spec, nodes, shell_segments_from_elements(elements))
    lines.extend(condition_lines)
    lines.append("*END")
    metadata = base_metadata(spec, len(nodes), len(elements), "shell")
    metadata["mesh"] = {"nx": nx, "ny": ny, "nz": nz, "dx_m": dx, "dy_m": dy, "dz_m": dz}
    metadata.update(condition_metadata)
    return "\n".join(lines) + "\n", metadata


def build_cylinder_shell(spec: ModelSpec) -> tuple[str, JSONDict]:
    radius = float(spec.geometry["radius_m"])
    length = float(spec.geometry["length_m"])
    thickness = float(spec.geometry["thickness_m"])
    mesh_size = float(spec.mesh["size_m"])
    nt = max(8, round(2 * math.pi * radius / mesh_size))
    nz = grid_count(length, mesh_size)
    dz = length / nz

    def nid(it: int, iz: int) -> int:
        return iz * nt + (it % nt) + 1

    nodes = []
    for iz in range(nz + 1):
        for it in range(nt):
            angle = 2 * math.pi * it / nt
            nodes.append((nid(it, iz), radius * math.cos(angle), radius * math.sin(angle), iz * dz))

    elements = []
    eid = 1
    for iz in range(nz):
        for it in range(nt):
            elements.append((eid, 1, nid(it, iz), nid(it + 1, iz), nid(it + 1, iz + 1), nid(it, iz + 1)))
            eid += 1
    lines = common_header(spec)
    lines.extend(["*NODE", "$#   nid               x               y               z"])
    lines.extend(f"{nid0},{x:.9g},{y:.9g},{z:.9g}" for nid0, x, y, z in nodes)
    lines.extend(["*ELEMENT_SHELL", "$#   eid     pid      n1      n2      n3      n4"])
    lines.extend(",".join(str(value) for value in element) for element in elements)
    lines.extend(
        part_header_lines(spec, f"{spec.material.get('name', 'material')}_cylinder_shell")
        + [
            "*SECTION_SHELL",
            "$# secid    elform      shrf       nip     propt   qr/irid     icomp     setyp",
            "1,2,0.833000,5,1.0,0,0,0",
            "$#     t1        t2        t3        t4      nloc     marea",
            f"{thickness:.9g},{thickness:.9g},{thickness:.9g},{thickness:.9g},0.0,0.0",
        ]
    )
    lines.extend(hourglass_lines(spec))
    lines.extend(top_level_curve_lines(spec))
    lines.extend(material_lines(spec))
    condition_lines, condition_metadata = boundary_and_load_lines(spec, nodes, shell_segments_from_elements(elements))
    lines.extend(condition_lines)
    lines.append("*END")
    metadata = base_metadata(spec, len(nodes), len(elements), "shell")
    metadata["mesh"] = {"nt": nt, "nz": nz, "dz_m": dz}
    metadata.update(condition_metadata)
    return "\n".join(lines) + "\n", metadata


def build_cylinder_solid(spec: ModelSpec) -> tuple[str, JSONDict]:
    radius = float(spec.geometry["radius_m"])
    length = float(spec.geometry["length_m"])
    mesh_size = float(spec.mesh["size_m"])
    nxy = max(4, 2 * grid_count(radius, mesh_size))
    nz = grid_count(length, mesh_size)
    dx = 2.0 * radius / nxy
    dy = dx
    dz = length / nz

    included_cells: list[tuple[int, int, int]] = []
    for iz in range(nz):
        for iy in range(nxy):
            y = -radius + (iy + 0.5) * dy
            for ix in range(nxy):
                x = -radius + (ix + 0.5) * dx
                if x * x + y * y <= radius * radius:
                    included_cells.append((ix, iy, iz))

    node_lookup: dict[tuple[int, int, int], int] = {}
    nodes: list[tuple[int, float, float, float]] = []

    def get_node(ix: int, iy: int, iz: int) -> int:
        key = (ix, iy, iz)
        if key in node_lookup:
            return node_lookup[key]
        nid0 = len(nodes) + 1
        node_lookup[key] = nid0
        nodes.append((nid0, -radius + ix * dx, -radius + iy * dy, iz * dz))
        return nid0

    elements = []
    for ix, iy, iz in included_cells:
        elements.append(
            (
                len(elements) + 1,
                1,
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

    lines = common_header(spec)
    lines.extend(["*NODE", "$#   nid               x               y               z"])
    lines.extend(f"{nid0},{x:.9g},{y:.9g},{z:.9g}" for nid0, x, y, z in nodes)
    lines.extend(["*ELEMENT_SOLID", "$#   eid     pid      n1      n2      n3      n4      n5      n6      n7      n8"])
    lines.extend(",".join(str(value) for value in element) for element in elements)
    lines.extend(
        part_header_lines(spec, f"{spec.material.get('name', 'material')}_cylinder_solid")
        + [
            "*SECTION_SOLID",
            "$# secid    elform",
            "1,1",
        ]
    )
    lines.extend(hourglass_lines(spec))
    lines.extend(top_level_curve_lines(spec))
    lines.extend(material_lines(spec))
    condition_lines, condition_metadata = boundary_and_load_lines(spec, nodes, solid_segments_from_elements(elements))
    lines.extend(condition_lines)
    lines.append("*END")
    metadata = base_metadata(spec, len(nodes), len(elements), "solid")
    metadata["mesh"] = {
        "nxy": nxy,
        "nz": nz,
        "dx_m": dx,
        "dy_m": dy,
        "dz_m": dz,
        "method": "voxelized_hexa_cylinder",
    }
    metadata["limitations"] = ["Voxelized hexahedral approximation; perimeter is faceted by mesh size."]
    metadata.update(condition_metadata)
    return "\n".join(lines) + "\n", metadata


def build_beam_bar(spec: ModelSpec) -> tuple[str, JSONDict]:
    length = float(spec.geometry["length_m"])
    width = float(spec.geometry["width_m"])
    height = float(spec.geometry["height_m"])
    mesh_size = float(spec.mesh["size_m"])
    nx = grid_count(length, mesh_size)
    ny = max(1, grid_count(width, mesh_size))
    nz = max(1, grid_count(height, mesh_size))
    dx, dy, dz = length / nx, width / ny, height / nz

    def nid(ix: int, iy: int, iz: int) -> int:
        return iz * (ny + 1) * (nx + 1) + iy * (nx + 1) + ix + 1

    y0 = -0.5 * width
    z0 = -0.5 * height
    nodes = [
        (nid(ix, iy, iz), ix * dx, y0 + iy * dy, z0 + iz * dz)
        for iz in range(nz + 1)
        for iy in range(ny + 1)
        for ix in range(nx + 1)
    ]
    elements = []
    for iz in range(nz):
        for iy in range(ny):
            for ix in range(nx):
                elements.append(
                    (
                        len(elements) + 1,
                        1,
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

    lines = common_header(spec)
    lines.extend(["*NODE", "$#   nid               x               y               z"])
    lines.extend(f"{nid0},{x:.9g},{y:.9g},{z:.9g}" for nid0, x, y, z in nodes)
    lines.extend(["*ELEMENT_SOLID", "$#   eid     pid      n1      n2      n3      n4      n5      n6      n7      n8"])
    lines.extend(",".join(str(value) for value in element) for element in elements)
    lines.extend(
        part_header_lines(spec, f"{spec.material.get('name', 'material')}_beam_bar")
        + [
            "*SECTION_SOLID",
            "$# secid    elform",
            "1,1",
        ]
    )
    lines.extend(hourglass_lines(spec))
    lines.extend(top_level_curve_lines(spec))
    lines.extend(material_lines(spec))
    condition_lines, condition_metadata = boundary_and_load_lines(spec, nodes, solid_segments_from_elements(elements))
    lines.extend(condition_lines)
    lines.append("*END")
    metadata = base_metadata(spec, len(nodes), len(elements), "solid")
    metadata["mesh"] = {
        "nx": nx,
        "ny": ny,
        "nz": nz,
        "dx_m": dx,
        "dy_m": dy,
        "dz_m": dz,
        "method": "solid_hexa_bar",
    }
    metadata["limitations"] = ["Solid hexahedral bar approximation; no LS-DYNA beam element formulation yet."]
    metadata.update(condition_metadata)
    return "\n".join(lines) + "\n", metadata


def build_single_solid_element_test(spec: ModelSpec) -> tuple[str, JSONDict]:
    length = float(spec.geometry["length_m"])
    width = float(spec.geometry["width_m"])
    height = float(spec.geometry["height_m"])
    nodes = [
        (1, 0.0, width, 0.0),
        (2, 0.0, 0.0, 0.0),
        (3, length, width, 0.0),
        (4, length, 0.0, 0.0),
        (5, 0.0, 0.0, height),
        (6, length, 0.0, height),
        (7, length, width, height),
        (8, 0.0, width, height),
    ]
    elements = [(1, 1, 2, 4, 3, 1, 5, 6, 7, 8)]

    lines = common_header(spec)
    lines.extend(["*NODE", "$#   nid               x               y               z"])
    lines.extend(f"{nid},{x:.9g},{y:.9g},{z:.9g}" for nid, x, y, z in nodes)
    lines.extend(
        [
            "*SECTION_SOLID",
            "$# secid    elform",
            f"1,{int(spec.mesh.get('elform', 1))}",
        ]
    )
    lines.extend(top_level_curve_lines(spec))
    lines.extend(material_lines(spec))
    lines.extend(part_header_lines(spec, f"{spec.material.get('name', 'material')}_single_solid_element"))
    lines.extend(hourglass_lines(spec))
    lines.extend(["*ELEMENT_SOLID", "$#   eid     pid      n1      n2      n3      n4      n5      n6      n7      n8"])
    lines.extend(",".join(str(value) for value in element) for element in elements)
    condition_lines, condition_metadata = boundary_and_load_lines(spec, nodes, solid_segments_from_elements(elements))
    lines.extend(condition_lines)
    lines.append("*END")
    metadata = base_metadata(spec, len(nodes), len(elements), "solid")
    metadata["mesh"] = {"nx": 1, "ny": 1, "nz": 1, "method": "single_hexa_solid_element"}
    metadata["limitations"] = [
        "Single-element test model only; not intended as a production structural mesh.",
        "Concrete material cards require user-supplied, project-reviewed parameters.",
    ]
    metadata.update(condition_metadata)
    return "\n".join(lines) + "\n", metadata


