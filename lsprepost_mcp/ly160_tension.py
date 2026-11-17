"""Controlled reconstruction of the paper's NR225, GP and CIR tensile specimens."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path

import numpy as np

from .config import DEFAULT_UNIT_SYSTEM
from .paths import safe_project_name

MODEL_TYPE = "ly160_paper_tension"
PAPER = {
    "L-NR225": {"E_GPa": 201.70, "sigma0_MPa": 203.99, "Q_MPa": 114.00, "b": 5.87,
                "L_MPa": 226.12, "peak_kN": 5.69, "cutoff_kN": 4.84, "extension_mm": 1.42},
    "L-GP": {"E_GPa": 199.42, "sigma0_MPa": 133.75, "Q_MPa": 162.84, "b": 10.66,
             "L_MPa": 246.81, "peak_kN": 51.83, "cutoff_kN": 44.05, "extension_mm": 5.09},
    "L-CIR": {"E_GPa": 200.44, "sigma0_MPa": 138.01, "Q_MPa": 157.16, "b": 13.70,
              "L_MPa": 272.38, "peak_kN": 28.80, "cutoff_kN": 24.48, "extension_mm": 7.10},
}
GEOMETRY = {
    "L-NR225": {"physical_length_m": .12, "gauge_length_m": .0625,
                "end_radius_m": .0045, "root_radius_m": .00225, "notch_radius_m": .00225},
    "L-GP": {"physical_length_m": .1725, "gauge_length_m": .0625, "width_m": .03,
             "thickness_m": .01, "groove_radius_m": .003, "assumed_groove_depth_m": .003},
    "L-CIR": {"physical_length_m": .1725, "gauge_length_m": .0625, "width_m": .05,
              "thickness_m": .01, "hole_radius_m": .02},
}


def default_spec(specimen: str, project_name: str | None = None) -> dict:
    if specimen not in PAPER:
        raise ValueError("Unknown LY160 paper specimen")
    p = PAPER[specimen]
    return {"model_type": MODEL_TYPE, "schema_version": "ly160.paper.tension@1",
            "project_name": project_name or f"LY160_{specimen.replace('-', '_')}_paper_20261106",
            "specimen": specimen, "unit_system": DEFAULT_UNIT_SYSTEM,
            "geometry": deepcopy(GEOMETRY[specimen]),
            "material": {k: p[k] for k in ("E_GPa", "sigma0_MPa", "Q_MPa", "b", "L_MPa")} | {"rho": 7850., "nu": .3},
            "analysis": {"final_extension_m": p["extension_mm"]/1000, "assumed_speed_m_s": 1e-5,
                         "dt0_s": .1, "dtmax_s": 1., "history_interval_s": 1., "plot_interval_s": 5.},
            "mesh": ({"radial_cells": 9, "near_size_m": .00025, "far_size_m": .001}
                     if specimen == "L-NR225" else
                     {"half_width_cells": 15, "half_thickness_cells": 5, "near_size_m": .0005, "far_size_m": .001}
                     if specimen == "L-GP" else
                     {"half_circumference_cells": 110, "radial_cells": 10, "half_thickness_cells": 5})}


def validate_spec(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Paper tensile spec must be an object")
    expected = default_spec(raw.get("specimen"))
    if set(raw) != set(expected):
        raise ValueError("Missing or unknown fields")
    name = raw["project_name"]
    if not isinstance(name, str) or safe_project_name(name) != name:
        raise ValueError("Unsafe project name")
    expected["project_name"] = name
    if raw != expected:
        raise ValueError("Preserve the published parameters and recorded reconstruction settings")
    return deepcopy(raw)


def flow_stress(specimen: str, ep):
    p = PAPER[specimen]
    return (p["sigma0_MPa"]+p["Q_MPa"]*(-np.expm1(-p["b"]*np.asarray(ep)))+p["L_MPa"]*np.asarray(ep))*1e6


def hardening_curve(specimen: str):
    p = PAPER[specimen]
    points = [[0., float(flow_stress(specimen, 0.))]]
    bounds = []

    def split(a, b):
        bound = p["Q_MPa"]*1e6*p["b"]**2*math.exp(-p["b"]*a)*(b-a)**2/8
        if bound > 5000:
            mid = (a+b)/2
            split(a, mid)
            split(mid, b)
        else:
            bounds.append(bound)
            points.append([b, float(flow_stress(specimen, b))])
    split(0., 3.)
    bound = max(bounds)+p["Q_MPa"]*1e6*p["b"]**2*(3/10000)**2/8
    return points, bound


def nr225_radius(y):
    return .0045-math.sqrt(max(0., .00225**2-y*y)) if abs(y) < .00225 else .0045


def gp_half_thickness(y):
    return .005-math.sqrt(max(0., .003**2-y*y)) if abs(y) < .003 else .005


def _symmetric_axis(near_extent, near_size, far_size):
    half = np.r_[np.linspace(0, near_extent, math.ceil(near_extent/near_size)+1),
                 np.linspace(near_extent, .03125, math.ceil((.03125-near_extent)/far_size)+1)[1:]]
    return np.r_[-half[:0:-1], half]


def _plane_mesh(spec):
    name = spec["specimen"]
    if name == "L-NR225":
        # Bound the arc length at the steep semicircle shoulders as well as dy.
        half = np.r_[.00225*np.sin(np.linspace(0, math.pi/2, 16)),
                     np.linspace(.00225, .03125, 30)[1:]]
        ys = np.r_[-half[:0:-1], half]
        nr = 9
        nodes = [[float(nr225_radius(y)*i/nr), float(y)] for y in ys for i in range(nr+1)]
        cells = []
        for iy in range(len(ys)-1):
            for ix in range(nr):
                n = iy*(nr+1)+ix
                cells.append([n, n+1, n+nr+2, n+nr+1])
        return np.array(nodes), cells
    if name == "L-GP":
        base = _symmetric_axis(.008, .0005, .001)
        arc = .003*np.sin(np.linspace(0, math.pi/2, 11))
        ys = np.unique(np.round(np.r_[base, arc, -arc], 14))
        xs = np.linspace(0, .015, 16)
        nodes = [[float(x), float(y)] for y in ys for x in xs]
        cells = []
        for iy in range(len(ys)-1):
            for ix in range(15):
                n = iy*16+ix
                cells.append([n, n+1, n+17, n+16])
        return np.array(nodes), cells
    # Half-plane O grid around the hole, with explicit outer-rectangle corners.
    corner = math.atan2(.03125, .025)
    angles = np.r_[np.linspace(-math.pi/2, -corner, 16),
                   np.linspace(-corner, corner, 81)[1:],
                   np.linspace(corner, math.pi/2, 16)[1:]]
    nodes = []
    for theta in angles:
        cosine, sine = math.cos(theta), math.sin(theta)
        outer = min(.025/max(cosine, 1e-30), .03125/max(abs(sine), 1e-30))
        for fraction in np.linspace(0, 1, 11):
            radius = .02+float(fraction)*(outer-.02)
            x, y = radius*cosine, radius*sine
            if abs(x) < 1e-14:
                x = 0.
            if abs(abs(y)-.03125) < 1e-14:
                y = math.copysign(.03125, y)
            nodes.append([x, y])
    cells = []
    for it in range(len(angles)-1):
        for ir in range(10):
            n = it*11+ir
            cells.append([n, n+1, n+12, n+11])
    return np.array(nodes), cells


def build_mesh(raw: dict) -> dict:
    spec = validate_spec(raw)
    name = spec["specimen"]
    plane, cells = _plane_mesh(spec)
    if name == "L-NR225":
        coords = np.c_[plane, np.zeros(len(plane))]
        connections = np.array(cells)
    else:
        coords = []
        for iz in range(6):
            for x, y in plane:
                thickness = gp_half_thickness(y) if name == "L-GP" else .005
                coords.append([x, y, thickness*iz/5])
        coords = np.array(coords)
        count = len(plane)
        connections = np.array([[n+iz*count for n in cell]+[n+(iz+1)*count for n in cell]
                                for iz in range(5) for cell in cells])
    ids = np.arange(1, len(coords)+1)
    sets = {101: ids[np.abs(coords[:, 0]) < 1e-14].tolist(),
            102: ids[np.abs(coords[:, 1]+.03125) < 1e-14].tolist(),
            103: ids[np.abs(coords[:, 1]-.03125) < 1e-14].tolist(),
            104: ids[np.abs(coords[:, 2]) < 1e-14].tolist()}
    root = ids[np.abs(coords[:, 1]) < 1e-14]
    sets[105] = sorted(set(sets[102]+sets[103]+root.tolist()))
    centers = coords[connections].mean(axis=1)
    order = np.argsort(np.abs(centers[:, 1]))
    history = (order[:min(40, len(order))]+1).tolist()
    return {"nodes": [[int(i), *row.tolist()] for i, row in zip(ids, coords)],
            "elements": [[i+1, 1, *(row+1).tolist()] for i, row in enumerate(connections)],
            "sets": sets, "history_elements": history, "element_family": "shell" if name == "L-NR225" else "solid"}


def audit_mesh(mesh: dict) -> dict:
    coords = np.array([n[1:] for n in mesh["nodes"]])
    ids = [n[0] for n in mesh["nodes"]]
    if ids != list(range(1, len(ids)+1)) or not np.isfinite(coords).all():
        raise ValueError("Invalid mesh nodes")
    conn = np.array([e[2:] for e in mesh["elements"]])-1
    if conn.min() < 0 or conn.max() >= len(coords) or any(len(set(row)) != len(row) for row in conn):
        raise ValueError("Invalid element references")
    points = coords[conn]
    minimum = float("inf")
    if conn.shape[1] == 4:
        for xi in (-1, 0, 1):
            for eta in (-1, 0, 1):
                dx = np.array([-(1-eta), 1-eta, 1+eta, -(1+eta)])/4
                dy = np.array([-(1-xi), -(1+xi), 1+xi, 1-xi])/4
                a, b = np.einsum("eij,i->ej", points, dx), np.einsum("eij,i->ej", points, dy)
                minimum = min(minimum, float((a[:, 0]*b[:, 1]-a[:, 1]*b[:, 0]).min()))
    else:
        signs = np.array([[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],
                          [-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]])
        for xi in (-1, 0, 1):
            for eta in (-1, 0, 1):
                for zeta in (-1, 0, 1):
                    natural = np.array([xi, eta, zeta])
                    derivatives = np.empty((8,3))
                    for j in range(3):
                        other = [k for k in range(3) if k != j]
                        derivatives[:,j] = signs[:,j]*np.prod(1+signs[:,other]*natural[other], axis=1)/8
                    jac = np.einsum("eij,ik->ejk", points, derivatives)
                    minimum = min(minimum, float(np.linalg.det(jac).min()))
    if minimum <= 0 or not math.isfinite(minimum):
        raise ValueError("Nonpositive element Jacobian")
    adjacency = [set() for _ in ids]
    for row in conn:
        for n in row[1:]:
            adjacency[row[0]].add(int(n))
            adjacency[n].add(int(row[0]))
    seen, stack = {0}, [0]
    while stack:
        for n in adjacency[stack.pop()]:
            if n not in seen:
                seen.add(n)
                stack.append(n)
    if len(seen) != len(ids):
        raise ValueError("Disconnected mesh")
    return {"ok": True, "node_count": len(ids), "element_count": len(conn),
            "minimum_jacobian": minimum, "connected_components": 1}


def numbers(*values):
    return ",".join(format(v, ".12g") for v in values)


def build_keyword(raw: dict):
    spec = validate_spec(raw)
    mesh = build_mesh(spec)
    name, mat = spec["specimen"], spec["material"]
    axisymmetric = name == "L-NR225"
    end = spec["analysis"]["final_extension_m"]/1e-5
    curve, bound = hardening_curve(name)
    lines = ["*KEYWORD LONG=Y", "$ Generated by lsprepost_mcp", "*TITLE", f"LY160 {name} paper reconstruction",
             "$ SI m,s,kg,N,Pa; y=axial; gauge=62.5 mm; rate-independent modified Voce",
             "*CONTROL_TERMINATION", numbers(end), "*CONTROL_IMPLICIT_GENERAL", "1,0.1,2,1,1,0,0",
             "*CONTROL_IMPLICIT_SOLUTION", "12,11,15,0.001,0.01,0,0.9,1e-20",
             "1,1,1,0,2,0,0", "0,0,0,0,0,0,0,0", "4,2,0,0,0,0",
             "*CONTROL_IMPLICIT_AUTO", "1,11,5,0.00001,1,0",
             "*CONTROL_IMPLICIT_DYNAMICS", "0", "*CONTROL_ACCURACY", "1,4,0,1",
             "*CONTROL_ENERGY", "2,2,2,2", "*DATABASE_BINARY_D3PLOT", "5",
             "*DATABASE_EXTENT_BINARY", "0,0,4,1,1,1,1,1", "0,0,0,0,0,0,2,1", "1,0,1,0,0"]
    for db in ("GLSTAT", "MATSUM", "NODOUT", "ELOUT", "SPCFORC", "BNDOUT"):
        lines += ["*DATABASE_"+db, "1"]
    lines += ["*DATABASE_HISTORY_NODE_SET", "105",
              "*DATABASE_HISTORY_SHELL_SET" if axisymmetric else "*DATABASE_HISTORY_SOLID_SET", "201", "*NODE"]
    lines += [numbers(*n) for n in mesh["nodes"]]
    lines += ["*ELEMENT_SHELL" if axisymmetric else "*ELEMENT_SOLID"]
    lines += [numbers(*e) for e in mesh["elements"]]
    lines += ["*PART", name+" gauge", "1,1,1,0,0,0,0,0" if axisymmetric else "1,1,1,0,1,0,0,0"]
    if axisymmetric:
        lines += ["*SECTION_SHELL", "1,15,0.833333,4,1,0,0,0", "0,0,0,0,0,0,0,0"]
    else:
        lines += ["*SECTION_SOLID", "1,1,0,0,0,0,0,0", "*HOURGLASS", "1,6,0.1,0,0,0,0,0"]
    lines += ["*MAT_PIECEWISE_LINEAR_PLASTICITY",
              numbers(1, 7850, mat["E_GPa"]*1e9, .3, mat["sigma0_MPa"]*1e6, 0, 1e20, 0),
              "0,0,1001,0,0", "0,0,0,0,0,0,0,0", "0,0,0,0,0,0,0,0",
              "*DEFINE_CURVE", "$ effective plastic strain / true flow stress Pa", "1001,0,1,1,0,0,0,10001"]
    lines += [numbers(*p) for p in curve]
    lines += ["*DEFINE_CURVE", "2001,0,1,1,0,0,0,0", "0,0", numbers(end, spec["analysis"]["final_extension_m"])]
    for sid, nodes in mesh["sets"].items():
        lines += ["*SET_NODE_LIST", str(sid)]
        lines += [numbers(*nodes[i:i+8]) for i in range(0, len(nodes), 8)]
    lines += ["*SET_SHELL_LIST" if axisymmetric else "*SET_SOLID_LIST", "201"]
    history = mesh["history_elements"]
    lines += [numbers(*history[i:i+8]) for i in range(0, len(history), 8)]
    lines += ["*BOUNDARY_SPC_SET", "101,0,1,0,0,0,0,0", "102,0,0,1,0,0,0,0", "104,0,0,0,1,0,0,0",
              "*BOUNDARY_PRESCRIBED_MOTION_SET", "103,2,2,2001,1,0,1e28,0", "*END"]
    assumptions = ["rho=7850 kg/m3 and nu=0.3 assumed, not tabulated in the paper.",
                   "Central 62.5 mm virtual gauge domain, not full machined specimen length.",
                   "Linear gauge motion at 0.01 mm/s is assumed because DIC time histories are unavailable.",
                   "Table1 nominal displacement is the run cutoff; material damage is not calibrated."]
    if axisymmetric:
        assumptions += ["Four-node ELFORM15/NIP4 replaces quadratic CAX8; equivalence remains unverified."]
    else:
        assumptions += ["Quarter 3D model uses width/thickness reflection symmetry, ELFORM1/HG6/QM0.1.",
                        "Uniform axial motion at loaded face; transverse motion free except symmetry planes."]
    if name == "L-GP":
        assumptions += ["User accepted two opposed semicircular R3 grooves, each 3 mm deep, root thickness 4 mm."]
    metadata = {"model_type": MODEL_TYPE, "specimen": name, "unit_system": DEFAULT_UNIT_SYSTEM,
                "node_count": len(mesh["nodes"]), "element_count": len(mesh["elements"]),
                "element_family": mesh["element_family"], "force_to_full_specimen": 2*math.pi if axisymmetric else 4.,
                "material_curve": {"point_count": len(curve), "interpolation_error_bound_pa": bound, "lcint": 10001},
                "assumptions": assumptions, "reference_table1": deepcopy(PAPER[name]),
                "solver_launched": False, "source": "Jiang et al. LY160 paper, Fig1, Sec2.1, Eq1, Table3"}
    return "\n".join(lines)+"\n", metadata


def validate_project(path: Path):
    from .project_store import project_validation_fingerprint
    from .web.preview_mesh import parse_keyword_mesh
    errors, metadata, quality = [], {}, {}
    try:
        spec = json.loads((path/"model.json").read_text(encoding="utf-8"))["spec"]
        expected, metadata = build_keyword(spec)
        actual = (path/"model.k").read_text(encoding="utf-8")
        if actual != expected:
            raise ValueError("Keyword must match the controlled project compiler")
        nodes, shells, solids = parse_keyword_mesh(actual)
        table = shells if spec["specimen"] == "L-NR225" else solids
        parsed = {"nodes": [[n, *p] for n,p in sorted(nodes.items())],
                  "elements": [[eid,pid,*conn] for pid,rows in table.items() for eid,conn in rows]}
        quality = audit_mesh(parsed)
        if len(nodes) != metadata["node_count"] or quality["element_count"] != metadata["element_count"]:
            raise ValueError("Parsed mesh count mismatch")
    except (ValueError, KeyError, TypeError, OSError, IndexError) as exc:
        errors.append(str(exc))
    return {"ok": not errors, "errors": errors, "warnings": metadata.get("assumptions", []), "checks": [],
            "counts": {"nodes": quality.get("node_count",0), "elements": quality.get("element_count",0), "parts": 1},
            "mesh_quality": quality, "validation_scope": {"ok_meaning": "static generated input and mesh audit"},
            "readiness": {"ok_for_gui_preview": not errors, "ok_for_solver_draft": not errors, "ok_for_production_review": False},
            "validation_fingerprint": project_validation_fingerprint(path)}


def generate_project(spec, *, if_exists="error"):
    from .project_store import write_compiled_keyword_project
    if if_exists not in {"error", "versioned"}:
        raise ValueError("Preserve existing projects")
    spec = validate_spec(spec)
    keyword, metadata = build_keyword(spec)
    audit_mesh(build_mesh(spec))
    return write_compiled_keyword_project(spec["project_name"], keyword, spec, metadata, if_exists=if_exists)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("specimen", choices=tuple(PAPER))
    parser.add_argument("--project-name")
    args = parser.parse_args()
    result = generate_project(default_spec(args.specimen, args.project_name))
    print(json.dumps({k:result[k] for k in ("project_dir", "keyword_path")}, indent=2))


if __name__ == "__main__":
    main()
