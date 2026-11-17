"""Controlled paper-based L-NR45 compiler. Generation never launches a solver."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path

from .config import DEFAULT_UNIT_SYSTEM
from .paths import safe_project_name

MODEL_TYPE = "ly160_nr45_tension"
DIAGNOSTIC_MODEL_TYPE = "ly160_nr45_diagnostic"
DIAGNOSTIC_CASES = ("time_step_10x", "top_radial_fixed", "mat103_direct", "nip1_hg6")
SCHEMA_VERSION = "ly160_nr45.paper@1"
GEOMETRY = {"specimen_length_m": .12, "gauge_length_m": .0625,
            "end_radius_m": .0045, "root_radius_m": .0025, "notch_radius_m": .045}
MATERIAL = {"type": "modified_voce_mat024", "youngs_pa": 202.57e9,
            "yield_strength_pa": 185.69e6, "q_pa": 135.15e6, "b": 11.24,
            "linear_hardening_pa": 271.73e6, "density_kg_per_m3": 7850., "poisson": .3}
ANALYSIS = {"method": "nonlinear_implicit_static", "displacement_m": .00387,
            "assumed_gauge_speed_m_s": 1e-5, "initial_step_s": .1,
            "minimum_step_s": 1e-5, "maximum_step_s": 1., "history_interval_s": .1,
            "plot_interval_s": 1.}
CURVE = {"max_plastic_strain": 3., "absolute_error_pa": 10000., "rediscretization_points": 10001}
ASSUMPTIONS = [
    "Density 7850 kg/m3 and Poisson ratio 0.3 are engineering assumptions, not reported paper values.",
    "The physical specimen is 120 mm long; the analysis domain is the central 62.5 mm virtual gauge.",
    "Figure 1 circular notch dimensions govern; Figure 4 round-bar labels appear interchanged.",
    "Four-node fully integrated axisymmetric ELFORM 15 replaces Abaqus quadratic CAX8; numerical equivalence is unverified.",
    "Ten radial layers give 0.25 mm at the root and 0.45 mm at the ends; exact original mesh is unavailable.",
    "Without DIC history, gauge end displacement is assumed linear at 0.01 mm/s, ending at 3.87 mm (387 s model time).",
    "3.87 mm is the paper's nominal displacement cutoff, not a damage law or element-deletion threshold.",
    "Curve coverage 0..3 plastic strain is a numerical choice, not an experimentally validated strain limit.",
    "Implicit timestep/output settings are numerical choices. No rate dependence, cyclic hardening or damage is calibrated.",
    "For ELFORM 15, multiply summed axial reaction by 2*pi for full-specimen force; displacement is not scaled.",
    "No solve has been performed. Verify SMP double precision solver compatibility and licensing before execution.",
]


def default_spec(project_name: str = "LY160_L_NR45_paper_20261101") -> dict:
    return {"schema_version": SCHEMA_VERSION, "model_type": MODEL_TYPE,
            "project_name": project_name, "unit_system": DEFAULT_UNIT_SYSTEM,
            "geometry": deepcopy(GEOMETRY), "material": deepcopy(MATERIAL),
            "analysis": deepcopy(ANALYSIS), "curve": deepcopy(CURVE),
            "mesh": {"radial_cells": 10, "near_size_m": .00025, "far_size_m": .001}}


def diagnostic_spec(case: str, project_name: str) -> dict:
    """Explicitly labelled single-factor diagnostics, never material refitting."""
    if case not in DIAGNOSTIC_CASES:
        raise ValueError("Unknown L-NR45 diagnostic case")
    spec = default_spec(project_name)
    spec.update(model_type=DIAGNOSTIC_MODEL_TYPE, diagnostic_case=case)
    return spec


def _finite(value, name: str, low: float, high: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be finite and in [{low}, {high}]")
    return float(value)


def validate_spec(raw: dict) -> dict:
    expected = default_spec()
    if isinstance(raw, dict) and raw.get("model_type") == DIAGNOSTIC_MODEL_TYPE:
        expected = diagnostic_spec(raw.get("diagnostic_case"), expected["project_name"])
    if not isinstance(raw, dict) or set(raw) != set(expected):
        raise ValueError("L-NR45 spec contains missing or unknown fields")
    for key in ("schema_version", "model_type", "unit_system", "geometry", "material", "analysis", "curve"):
        if raw[key] != expected[key]:
            raise ValueError(f"{key} must preserve the L-NR45 paper contract and recorded assumptions")
    name = raw["project_name"]
    if not isinstance(name, str) or safe_project_name(name) != name:
        raise ValueError("project_name must be a safe identifier")
    mesh = raw["mesh"]
    if not isinstance(mesh, dict) or set(mesh) != {"radial_cells", "near_size_m", "far_size_m"}:
        raise ValueError("unknown or missing mesh parameters")
    nr = mesh["radial_cells"]
    if type(nr) is not int or not 2 <= nr <= 80:
        raise ValueError("radial_cells must be an integer in [2, 80]")
    near = _finite(mesh["near_size_m"], "near_size_m", 5e-5, .001)
    far = _finite(mesh["far_size_m"], "far_size_m", 1e-4, .002)
    a = notch_half_length()
    count = 2 * (math.ceil(a/near) + math.ceil((.03125-a)/far)) * nr
    if count > 20000:
        raise ValueError("mesh exceeds the 20000-element generation budget")
    return deepcopy(raw)


def notch_half_length() -> float:
    return math.sqrt(.045**2 - (.045-(.0045-.0025))**2)


def radius_at(axial_m: float) -> float:
    y = _finite(axial_m, "axial_m", -.06, .06)
    if abs(y) >= notch_half_length():
        return .0045
    return .0025 + .045 - math.sqrt(.045**2-y*y)


def flow_stress(plastic_strain: float) -> float:
    p = _finite(plastic_strain, "plastic_strain", 0, 3)
    return 185.69e6 - 135.15e6*math.expm1(-11.24*p) + 271.73e6*p


def hardening_curve(spec: dict) -> tuple[list[list[float]], float]:
    validate_spec(spec)
    points = [[0., flow_stress(0.)]]
    bounds = []

    def subdivide(a, b):
        # Linear interpolation error <= max(abs(f'')) * h^2 / 8.
        bound = 135.15e6 * 11.24**2 * math.exp(-11.24*a) * (b-a)**2 / 8
        if bound > CURVE["absolute_error_pa"]/2:
            mid = (a+b)/2
            subdivide(a, mid)
            subdivide(mid, b)
        else:
            bounds.append(bound)
            points.append([b, flow_stress(b)])

    subdivide(0., CURVE["max_plastic_strain"])
    # LS-DYNA uniformly rediscretizes constitutive curves. Interpolating the
    # exact function on that grid adds at most this curvature-based error;
    # interpolating our input ordinates adds no more than their existing bound.
    spacing = CURVE["max_plastic_strain"]/(CURVE["rediscretization_points"]-1)
    rediscretization_bound = 135.15e6*11.24**2*spacing**2/8
    return points, max(bounds)+rediscretization_bound


def build_mesh(spec: dict) -> dict:
    spec = validate_spec(spec)
    mesh = spec["mesh"]
    nr = mesh["radial_cells"]
    a = notch_half_length()
    nn = math.ceil(a/mesh["near_size_m"])
    nf = math.ceil((.03125-a)/mesh["far_size_m"])
    half = [a*i/nn for i in range(nn+1)] + [a+(.03125-a)*i/nf for i in range(1, nf+1)]
    ys = [-y for y in reversed(half[1:])] + half
    nodes = []
    for iy, y in enumerate(ys):
        for ir in range(nr+1):
            nodes.append([iy*(nr+1)+ir+1, radius_at(y)*ir/nr, y, 0.])
    elements = []
    for iy in range(len(ys)-1):
        for ir in range(nr):
            n = iy*(nr+1)+ir+1
            elements.append([len(elements)+1, 1, n, n+1, n+nr+2, n+nr+1])
    sets = {101: [n[0] for n in nodes if n[1] == 0],
            102: [n[0] for n in nodes if n[2] == ys[0]],
            103: [n[0] for n in nodes if n[2] == ys[-1]],
            104: [n[0] for n in nodes],
            105: [n[0] for n in nodes if n[2] in (ys[0], 0., ys[-1])]}
    return {"nodes": nodes, "elements": elements, "sets": sets,
            "near_axial_size_m": a/nn, "far_axial_size_m": (.03125-a)/nf}


def audit_mesh(nodes: list, elements: list) -> dict:
    """Check actual parsed coordinates/connectivity, independent of deck identity."""
    coords = {int(n[0]): n[1:4] for n in nodes}
    errors = []
    minimum = math.inf
    edges = {}
    adjacency = {nid: set() for nid in coords}
    if len(coords) != len(nodes):
        errors.append("duplicate node IDs")
    if len({e[0] for e in elements}) != len(elements):
        errors.append("duplicate element IDs")
    for p in coords.values():
        if not all(math.isfinite(v) for v in p) or p[0] < 0 or abs(p[2]) > 1e-14 or abs(p[1]) > .03125+1e-12:
            errors.append("node outside axisymmetric gauge domain")
        elif p[0] > radius_at(p[1])+1e-12:
            errors.append("node outside the circular profile")
    for e in elements:
        conn = e[2:]
        if len(conn) != 4 or len(set(conn)) != 4 or any(n not in coords for n in conn) or e[1] != 1:
            errors.append("invalid element connectivity or part")
            continue
        p = [coords[n] for n in conn]
        # All corners as well as Gauss points; positive area alone misses inverted quads.
        for xi in (-1., -1/math.sqrt(3), 1/math.sqrt(3), 1.):
            for eta in (-1., -1/math.sqrt(3), 1/math.sqrt(3), 1.):
                dxi = [-(1-eta), 1-eta, 1+eta, -(1+eta)]
                deta = [-(1-xi), -(1+xi), 1+xi, 1-xi]
                xr = sum(dxi[i]*p[i][0] for i in range(4))/4
                yr = sum(dxi[i]*p[i][1] for i in range(4))/4
                xs = sum(deta[i]*p[i][0] for i in range(4))/4
                ys = sum(deta[i]*p[i][1] for i in range(4))/4
                minimum = min(minimum, xr*ys-xs*yr)
        for i, n in enumerate(conn):
            other = conn[(i+1)%4]
            adjacency[n].add(other)
            adjacency[other].add(n)
            edge = tuple(sorted((n, other)))
            edges[edge] = edges.get(edge, 0)+1
    if not math.isfinite(minimum) or minimum <= 0:
        errors.append("nonpositive Jacobian or empty mesh")
    if any(n > 2 for n in edges.values()):
        errors.append("nonmanifold edge")
    visited = set()
    components = 0
    for nid in coords:
        if nid in visited:
            continue
        components += 1
        stack = [nid]
        visited.add(nid)
        while stack:
            for neighbor in adjacency[stack.pop()]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)
    if components != 1:
        errors.append("mesh must have one connected component")
    return {"ok": not errors, "errors": sorted(set(errors)), "node_count": len(nodes),
            "element_count": len(elements), "minimum_jacobian_m2": minimum if math.isfinite(minimum) else None,
            "connected_components": components}


def _numbers(*values) -> str:
    return ",".join(format(v, ".12g") for v in values)


def build_keyword(raw: dict) -> tuple[str, dict]:
    spec = validate_spec(raw)
    mesh = build_mesh(spec)
    curve, bound = hardening_curve(spec)
    diagnostic = spec.get("diagnostic_case")
    step_scale = .1 if diagnostic == "time_step_10x" else 1.
    end_time = ANALYSIS["displacement_m"]/ANALYSIS["assumed_gauge_speed_m_s"]
    # Title deliberately excludes project name so versioned project transactions
    # remain deterministically regenerable after changing spec.project_name.
    # R12 enforces field widths even for comma-delimited input. Preserve the
    # paper constants and mesh coordinates with 20-character long fields.
    lines = ["*KEYWORD LONG=Y", "$ Generated by lsprepost_mcp", "*TITLE",
             "LY160 L-NR45 / paper modified Voce / axisymmetric input model",
             f"$ Units: {DEFAULT_UNIT_SYSTEM}",
             "$ SOURCE: Jiang et al. 2026, Fig.1 / Sec.2.1 / Eq.1 / Table 3, L-NR45.",
             "$ INPUT MODEL ONLY. No solver or engineering equivalence validation.",
             "$ Analysis gauge 62.5 mm; full machined specimen 120 mm.",
             "$ Assumed nu=0.3, rho=7850 kg/m3. No rate dependence or damage.",
             "$ ELFORM15 forces are per radian: total force = 2*pi*sum(axial reaction).",
             "*CONTROL_TERMINATION", _numbers(end_time),
             "*CONTROL_IMPLICIT_GENERAL", "$ imflag,dt0,imform,nsbs,igs,cnstn,form",
             _numbers(1, .1*step_scale, 2, 1, 1, 0, 0),
             "*CONTROL_IMPLICIT_SOLUTION", "$ nsolvr,ilimit,maxref,dctol,ectol,rctol,lstol,abstol",
             "12,11,15,0.001,0.01,0,0.9,1e-20",
             "$ dnorm,diverg,istif,nlprint,nlnorm,d3itctl,cpchk",
             "1,1,1,0,2,0,0", "0,0,0,0,0,0,0,0", "4,2,0,0,0,0",
             "*CONTROL_IMPLICIT_AUTO", "$ iauto,iteopt,itewin,dtmin,dtmax,dtexp (R12)",
             # Keep default text stable for existing project provenance.
             "1,11,5,0.00001,1,0" if step_scale == 1. else "1,11,5,0.00001,0.1,0",
             "*CONTROL_IMPLICIT_DYNAMICS", "0",
             "*CONTROL_ACCURACY", "$ osu,inn,pidosu,iacc", "1,4,0,1",
             "*CONTROL_ENERGY", "2,2,2,2",
             "*DATABASE_BINARY_D3PLOT", "1",
             "*DATABASE_EXTENT_BINARY", "0,0,4,1,1,1,1,1",
             "0,0,0,0,0,0,2,1", "1,0,1,0,0"]
    for card in ("GLSTAT", "MATSUM", "NODOUT", "ELOUT", "SPCFORC", "BNDOUT"):
        lines.extend(["*DATABASE_"+card, "0.1"])
    lines.extend(["*DATABASE_HISTORY_NODE_SET", "105", "*DATABASE_HISTORY_SHELL_SET", "201",
                  "*NODE", "$ nid,x_radial_m,y_axial_m,z"])
    lines.extend(_numbers(*n) for n in mesh["nodes"])
    lines.append("*ELEMENT_SHELL")
    lines.extend(_numbers(*e) for e in mesh["elements"])
    underintegrated = diagnostic == "nip1_hg6"
    lines.extend(["*PART", "LY160 L-NR45 gauge",
                  "1,1,1,0,1,0,0,0" if underintegrated else "1,1,1,0,0,0,0,0",
                  "*SECTION_SHELL", "$ secid,elform,shrf,nip,propt,qr,icomp,setyp",
                  "1,15,0.833333,1,1,0,0,0" if underintegrated else "1,15,0.833333,4,1,0,0,0",
                  "0,0,0,0,0,0,0,0"])
    if underintegrated:
        # HG6 is the assumed-strain formulation supported for 2D solids 13/15.
        # Fix the documented default coefficient; do not calibrate it to force.
        lines.extend(["*HOURGLASS", "$ hgid,ihq,qm,ibq,q1,q2,qb,qw",
                      "1,6,0.1,0,0,0,0,0"])
    if diagnostic == "mat103_direct":
        # R12 Volume II pp. 2-644..650 and the official implicit MAT_103
        # template: FLAG=2 reads the absolute flow curve without fitting.
        # Blank-equivalent cards keep isotropic defaults, no viscosity/failure.
        # SIGY=0 does not erase the curve's initial yield stress of 185.69 MPa.
        lines.extend(["*MAT_ANISOTROPIC_VISCOPLASTIC",
                      "$ mid,ro,e,pr,sigy,flag,lcss,alpha",
                      "1,7850,202570000000,0.3,0,2,1001,1"])
        lines.extend(["0,0,0,0,0,0,0,0"]*5)
    else:
        lines.extend(["*MAT_PIECEWISE_LINEAR_PLASTICITY",
                      "$ mid,ro,e,pr,sigy,etan,fail,tdel",
                      "1,7850,202570000000,0.3,185690000,0,1e20,0",
                      "$ c,p,lcss,lcsr,vp", "0,0,1001,0,0",
                      "0,0,0,0,0,0,0,0", "0,0,0,0,0,0,0,0"])
    lines.extend(["*DEFINE_CURVE", "$ LCSS: effective plastic strain / true flow stress Pa",
                  "1001,0,1,1,0,0,0,10001"])
    lines.extend(_numbers(*p) for p in curve)
    lines.extend(["*DEFINE_CURVE", "$ LCID2001: assumed gauge end displacement, time_s / displacement_m",
                  "2001,0,1,1,0,0,0,0", "0,0", _numbers(end_time, .00387)])
    names = {101: "Symmetry axis X=0", 102: "Gauge bottom Y=-31.25mm", 103: "Gauge top Y=31.25mm",
             104: "All nodes XY plane", 105: "Bottom root and top history nodes"}
    for sid, ids in mesh["sets"].items():
        lines.extend(["*SET_NODE_LIST_TITLE", names[sid], str(sid)])
        lines.extend(_numbers(*ids[i:i+8]) for i in range(0, len(ids), 8))
    lines.extend(["*SET_SHELL_LIST_TITLE", "Root section adjacent elements", "201"])
    nr = spec["mesh"]["radial_cells"]
    middle_row = (len(mesh["nodes"])//(nr+1)-1)//2
    history = [e[0] for e in mesh["elements"] if (e[0]-1)//nr in (middle_row-1, middle_row)]
    lines.extend(_numbers(*history[i:i+8]) for i in range(0, len(history), 8))
    lines.extend(["*BOUNDARY_SPC_SET", "$ nsid,cid,dofx,dofy,dofz,dofrx,dofry,dofrz",
                  "101,0,1,0,0,0,0,0", "102,0,0,1,0,0,0,0", "104,0,0,0,1,0,0,0"])
    if diagnostic == "top_radial_fixed":
        lines.append("103,0,1,0,0,0,0,0")
    lines.extend(["*BOUNDARY_PRESCRIBED_MOTION_SET", "$ nsid,dof,vad,lcid,sf,vid,death,birth",
                  "103,2,2,2001,1,0,1e28,0", "*END"])
    metadata = {"model_type": spec["model_type"], "unit_system": DEFAULT_UNIT_SYSTEM,
                "node_count": len(mesh["nodes"]), "element_count": len(mesh["elements"]),
                "element_family": "shell", "physical_element_type": "axisymmetric_solid",
                "material_curve": {"lcid": 1001, "point_count": len(curve),
                                   "interpolation_error_bound_pa": bound, "max_plastic_strain": 3.,
                                   "lsdyna_rediscretization_points": CURVE["rediscretization_points"],
                                   "error_scope": "input linear interpolation plus uniform rediscretization; not stress integration error"},
                "geometry": deepcopy(GEOMETRY), "near_axial_size_m": mesh["near_axial_size_m"],
                "far_axial_size_m": mesh["far_axial_size_m"], "force_to_full_circumference": 2*math.pi,
                "source": {"title": "LY160软钢大应变本构模型及有限元参数反演研究", "author": "姜涛等",
                           "pdf_pages_including_cover": [3, 4, 6, 7, 9], "material_table": "3, modified Voce, L-NR45"},
                "components": [{"id": "L-NR45", "part_id": 1, "material_id": 1, "section_id": 1}],
                "assumptions": list(ASSUMPTIONS), "solver_launched": False}
    if diagnostic:
        metadata["diagnostic_case"] = diagnostic
        metadata["diagnostic_note"] = "Sensitivity experiment; not asserted to be the paper's original settings."
    if diagnostic == "mat103_direct":
        metadata["constitutive_implementation"] = "MAT_103 FLAG=2 direct isotropic curve"
    if underintegrated:
        metadata["integration_points"] = 1
        metadata["hourglass"] = {"type": 6, "coefficient": .1}
        metadata["assumptions"][3] = (
            "One-point axisymmetric ELFORM 15 with HG6, coefficient 0.1; "
            "integration/stabilization sensitivity only, not CAX8 equivalence.")
    return "\n".join(lines)+"\n", metadata


def validate_project(path: Path) -> dict:
    from .project_store import project_validation_fingerprint
    from .web.preview_mesh import parse_keyword_mesh
    errors, checks = [], []
    quality, spec, metadata = {}, {}, {}

    def check(name, ok, message):
        checks.append({"id": "ly160_nr45."+name, "ok": bool(ok),
                       "severity": "info" if ok else "error", "message": message})
        if not ok:
            errors.append(message)

    try:
        spec = validate_spec(json.loads((path/"model.json").read_text(encoding="utf-8"))["spec"])
        expected, metadata = build_keyword(spec)
        actual = (path/"model.k").read_text(encoding="utf-8")
        check("deterministic_rebuild", actual == expected, "Deck must match the controlled paper-based generator")
        node_map, shells, solids = parse_keyword_mesh(actual)
        nodes = [[nid, *xyz] for nid, xyz in node_map.items()]
        elements = [[eid, pid, *conn] for pid, rows in shells.items() for eid, conn in rows]
        quality = audit_mesh(nodes, elements)
        check("mesh_quality", quality["ok"], "Actual mesh must have valid references, domain, connectivity and positive Jacobians")
        check("element_family", not solids and set(shells) == {1}, "Only the L-NR45 axisymmetric part is permitted")
        check("counts", len(nodes) == metadata["node_count"] and len(elements) == metadata["element_count"], "Node/element counts must match recorded mesh parameters")
        check("material_curve", metadata["material_curve"]["interpolation_error_bound_pa"] <= 10000,
              "Voce tabulation absolute interpolation error bound must be <= 0.01 MPa")
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        check("read_compile", False, f"L-NR45 validation failed: {exc}")
    return {"ok": not errors, "errors": errors, "warnings": metadata.get("assumptions", list(ASSUMPTIONS)), "checks": checks,
            "readiness": {"ok_for_gui_preview": not errors, "ok_for_solver_draft": False,
                          "ok_for_production_review": False,
                          "solver_blockers": ["Model-building deliverable only; solver compatibility and execution scope remain unverified."]},
            "validation_scope": {"ok_meaning": "static paper reconstruction and curve accuracy only; no solve or physical validation",
                                 "profile_version": SCHEMA_VERSION},
            "counts": {"nodes": quality.get("node_count", 0), "elements": quality.get("element_count", 0),
                       "parts": 1, "materials": 1, "sections": 1}, "mesh_quality": quality,
            "summary": {"project_name": spec.get("project_name", path.name), "model_type": spec.get("model_type", MODEL_TYPE),
                        "unit_system": DEFAULT_UNIT_SYSTEM},
            "keyword_path": str(path/"model.k"), "spec_path": str(path/"model.json"),
            "validation_fingerprint": project_validation_fingerprint(path)}


def generate_project(spec: dict, *, if_exists: str = "error") -> dict:
    from .project_store import write_compiled_keyword_project
    if if_exists not in {"error", "versioned"}:
        raise ValueError("Only error or versioned is allowed; preserve existing projects")
    spec = validate_spec(spec)
    keyword, metadata = build_keyword(spec)
    mesh = build_mesh(spec)
    quality = audit_mesh(mesh["nodes"], mesh["elements"])
    if not quality["ok"]:
        raise ValueError(f"Mesh audit failed: {quality['errors']}")
    return write_compiled_keyword_project(spec["project_name"], keyword, spec, metadata, if_exists=if_exists)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "generate"))
    parser.add_argument("--project-name", default="LY160_L_NR45_paper_20261101")
    parser.add_argument("--if-exists", choices=("error", "versioned"), default="error")
    args = parser.parse_args()
    spec = default_spec(args.project_name)
    if args.command == "prepare":
        _, metadata = build_keyword(spec)
        result = {"spec": spec, "metadata": metadata, "solver_launched": False}
    else:
        result = generate_project(spec, if_exists=args.if_exists)
        result = {k: v for k, v in result.items() if k not in {"metadata", "checks"}} | {
            "checks_ok": result["checks"]["ok"], "solver_launched": False}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
