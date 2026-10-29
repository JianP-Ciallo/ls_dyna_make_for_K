"""Regenerate the source's rectangular r-z regions using existing Phase15 topology."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import math

from .phase15 import compile_axisymmetric_quad_mesh

GEOMETRY = {"radial_breaks_m": [0.0, .003, .25], "axial_breaks_m": [-.3, 0.0, .03, .06]}
DEFAULT_MESH = {"radial_cells": [6, 494], "axial_cells": [600, 60, 60]}


def validate_mesh_parameters(raw: dict) -> dict:
    if not isinstance(raw, dict) or set(raw) != set(DEFAULT_MESH):
        raise ValueError("mesh requires only radial_cells and axial_cells")
    for key, count in (("radial_cells", 2), ("axial_cells", 3)):
        values = raw[key]
        if not isinstance(values, list) or len(values) != count:
            raise ValueError(f"{key} requires {count} subdivision integers")
        if any(type(v) is not int or not 1 <= v <= 1000 for v in values):
            raise ValueError("subdivisions must be integers from 1 to 1000")
    if sum(raw["radial_cells"]) * sum(raw["axial_cells"]) > 500000:
        raise ValueError("requested mesh exceeds the controlled 500000-element budget")
    return deepcopy(raw)


def estimate_mesh(raw: dict) -> dict:
    p = validate_mesh_parameters(raw)
    inner, outer = p["radial_cells"]
    target, steel, top = p["axial_cells"]
    nx, ny = inner + outer, target + steel + top
    return {"nodes": (nx+1)*(ny+1), "elements": nx*ny,
            "elements_by_part": {"1": inner*steel, "2": nx*target, "3": nx*(steel+top)-inner*steel},
            "interfaces": {"1-2": {"edges": inner, "nodes": inner+1},
                           "1-3": {"edges": steel+inner, "nodes": steel+inner+1},
                           "2-3": {"edges": outer, "nodes": outer+1}}}


def _axis(breaks: list[float], counts: list[int]) -> list[float]:
    return [round(lo+(hi-lo)*i/n, 12) for lo, hi, n in zip(breaks, breaks[1:], counts) for i in range(n)] + [breaks[-1]]


def build_mesh(raw: dict) -> dict:
    p = validate_mesh_parameters(raw)
    nx, ny = sum(p["radial_cells"]), sum(p["axial_cells"])
    grid = compile_axisymmetric_quad_mesh(float(nx), float(ny), 1.0,
        node_id_start=1000001, element_id_start=1000001)
    xs = _axis(GEOMETRY["radial_breaks_m"], p["radial_cells"])
    ys = _axis(GEOMETRY["axial_breaks_m"], p["axial_cells"])
    for node in grid["nodes"]:
        node[1], node[2] = xs[int(node[1])], ys[int(node[2])]
    for index, row in enumerate(grid["elements"]):
        i, j = index % nx, index // nx
        row[1] = 2 if j < p["axial_cells"][0] else (1 if i < p["radial_cells"][0] and j < sum(p["axial_cells"][:2]) else 3)
    return {"nodes": grid["nodes"], "elements": grid["elements"], "mesh": p, "estimate": estimate_mesh(p)}


def audit_mesh(nodes: list, elements: list, raw: dict) -> dict:
    """Inspect actual rows. Full rectangular cell coverage proves connectivity.

    Each accepted cell is an axis-aligned positive rectangle; its bilinear
    Jacobian is constant, so dx*dy/4 checks all corners and Gauss points.
    """
    p = validate_mesh_parameters(raw)
    xs = _axis(GEOMETRY["radial_breaks_m"], p["radial_cells"])
    ys = _axis(GEOMETRY["axial_breaks_m"], p["axial_cells"])
    nx, ny = len(xs)-1, len(ys)-1
    xi, yi = {x:i for i,x in enumerate(xs)}, {y:j for j,y in enumerate(ys)}
    errors = set()
    coordinates, lattice = {}, {}
    for node in nodes:
        if len(node) != 4 or type(node[0]) is not int or node[0] <= 0:
            errors.add("invalid node record"); continue
        nid, x, y, z = node
        if nid in coordinates: errors.add("duplicate node ID")
        coordinates[nid] = (x, y, z)
        if x not in xi or y not in yi or z != 0:
            errors.add("node outside prescribed analytic lattice"); continue
        key = (xi[x], yi[y])
        if key in lattice: errors.add("duplicate coordinate")
        lattice[key] = nid
    if len(lattice) != (nx+1)*(ny+1): errors.add("incomplete node lattice")
    cells = bytearray(nx*ny)
    used, element_ids = set(), set()
    parts = defaultdict(lambda: {"elements":0, "area_m2":0.0, "volume_m3":0.0})
    min_jac = math.inf
    for e in elements:
        if len(e) != 6 or len(set(e[2:])) != 4 or any(type(v) is not int for v in e):
            errors.add("invalid quad record"); continue
        eid, pid, n1, n2, n3, n4 = e
        if eid <= 0 or eid in element_ids: errors.add("invalid or duplicate element ID")
        element_ids.add(eid)
        used.update(e[2:])
        if any(n not in coordinates for n in e[2:]):
            errors.add("missing node reference"); continue
        q = [coordinates[n] for n in e[2:]]
        x0,y0,_ = q[0]
        i,j = xi.get(x0, -1), yi.get(y0, -1)
        if not (0 <= i < nx and 0 <= j < ny):
            errors.add("invalid quad origin or winding"); continue
        expected = [(x0,y0,0), (xs[i+1],y0,0), (xs[i+1],ys[j+1],0), (x0,ys[j+1],0)]
        if q != expected:
            errors.add("nonrectangular, crossed, reversed or nonadjacent quad"); continue
        slot = j*nx+i
        if cells[slot]: errors.add("duplicate cell coverage")
        if pid not in (1,2,3):
            errors.add("unknown part"); continue
        cells[slot] = pid
        cx,cy = (x0+xs[i+1])/2, (y0+ys[j+1])/2
        expected_pid = 2 if cy < 0 else (1 if cx < .003 and cy < .03 else 3)
        if pid != expected_pid: errors.add("part differs from physical spatial region")
        dx,dy = xs[i+1]-x0, ys[j+1]-y0
        min_jac = min(min_jac, dx*dy/4)
        parts[str(pid)]["elements"] += 1
        parts[str(pid)]["area_m2"] += dx*dy
        parts[str(pid)]["volume_m3"] += math.pi*(xs[i+1]**2-x0*x0)*dy
    if any(v==0 for v in cells): errors.add("missing cell coverage")
    if set(coordinates) != used: errors.add("unreferenced or unknown nodes")
    if min_jac <= 0 or not math.isfinite(min_jac): errors.add("nonpositive Jacobian")
    edges = defaultdict(int)
    interface_nodes = defaultdict(set)
    for j in range(ny):
        for i in range(nx):
            pid = cells[j*nx+i]
            if i+1 < nx:
                other = cells[j*nx+i+1]
                if pid and other and pid != other:
                    pair = "-".join(map(str,sorted((pid,other))))
                    edges[pair] += 1
                    interface_nodes[pair].update(((i+1,j),(i+1,j+1)))
            if j+1 < ny:
                other = cells[(j+1)*nx+i]
                if pid and other and pid != other:
                    pair = "-".join(map(str,sorted((pid,other))))
                    edges[pair] += 1
                    interface_nodes[pair].update(((i,j+1),(i+1,j+1)))
    interfaces = {key:{"edges":edges[key],"nodes":len(interface_nodes[key])} for key in sorted(edges)}
    if interfaces != estimate_mesh(p)["interfaces"]: errors.add("incorrect material interface")
    if len(elements) != nx*ny: errors.add("incorrect element count")
    return {"ok":not errors,"errors":sorted(errors),"node_count":len(nodes),"element_count":len(elements),
            "parts":dict(parts),"bounds_m":[[0.0,.25],[-.3,.06],[0.0,0.0]] if not errors else None,
            "interfaces":interfaces,"minimum_jacobian":min_jac if math.isfinite(min_jac) else None,
            "jacobian_method":"constant positive rectangular bilinear Jacobian (all corners and Gauss points)",
            "connected_components":1 if not errors else None,"boundary_edges":2*(nx+ny) if not errors else None,
            "complete_cell_coverage":all(cells),"unreferenced_nodes":len(set(coordinates)-used)}
