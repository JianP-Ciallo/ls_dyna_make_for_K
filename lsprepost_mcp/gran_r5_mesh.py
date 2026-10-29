"""Analytic conforming mesh for the reviewed GRAN_R5 r-z domain.

Only scalar mesh parameters enter this module. The source node and element
tables are neither loaded nor accepted. Rectangular topology comes from the
project's existing axisymmetric quad generator.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import math

from .phase15 import compile_axisymmetric_quad_mesh

DEFAULT_MESH = {"core_divisions": 20, "charge_layers": 20, "concrete_layers": 30}
GEOMETRY = {"outer_radius_m": .9, "axial_range_m": [-.9, .9], "charge_radius_m": .04,
            "charge_center_m": [0.0, 0.0, 0.0], "core_half_size_m": .02, "transition_half_size_m": .12}


def validate_mesh_parameters(raw: dict) -> dict:
    if not isinstance(raw, dict) or set(raw) != set(DEFAULT_MESH):
        raise ValueError("mesh requires exactly core_divisions, charge_layers, concrete_layers")
    for key, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 80:
            raise ValueError(f"{key} must be an integer between 1 and 80")
    if raw["core_divisions"] % 2:
        raise ValueError("core_divisions must be even for conforming far-field interfaces")
    n = raw["core_divisions"]
    count = 225*n*n//2 + 4*n*(raw["charge_layers"]+raw["concrete_layers"])
    if count > 200000:
        raise ValueError("requested mesh exceeds the controlled 200000-element budget")
    return dict(raw)


def estimate_mesh(raw: dict) -> dict:
    p = validate_mesh_parameters(raw)
    n = p["core_divisions"]
    charge = 2*n*n + 4*n*p["charge_layers"]
    total = 225*n*n//2 + 4*n*(p["charge_layers"]+p["concrete_layers"])
    boundary_edges = 45*n + 2*(p["charge_layers"]+p["concrete_layers"])
    return {"nodes": total + boundary_edges//2 + 1, "elements": total,
            "elements_by_part": {"1": charge, "2": total-charge},
            "interface_edges": 4*n, "far_field_spacing_m": .12/n}


def build_mesh(raw: dict) -> dict:
    p = validate_mesh_parameters(raw)
    n = p["core_divisions"]
    nodes, elements, registry = [], [], {}

    def add_block(nx, ny, mapping, pid):
        grid = compile_axisymmetric_quad_mesh(float(nx), float(ny), 1.0, part_id=pid)
        ids = {}
        for local, x, y, _ in grid["nodes"]:
            px, py = mapping(x/nx, y/ny)
            key = (round(px, 12), round(py, 12), 0.0)
            if key not in registry:
                registry[key] = 1000001 + len(nodes)
                nodes.append([registry[key], *key])
            ids[local] = registry[key]
        for row in grid["elements"]:
            elements.append([1000001+len(elements), pid, *(ids[j] for j in row[2:6])])

    add_block(n, 2*n, lambda u,v: (.02*u, -.02+.04*v), 1)
    # Half-square perimeter follows top -> right upper/lower -> bottom.
    corners = [(0,1),(1,1),(1,0),(1,-1),(0,-1)]
    def square(sector, u, size):
        a,b = corners[sector:sector+2]
        return (size*((1-u)*a[0]+u*b[0]), size*((1-u)*a[1]+u*b[1]))
    def arc(sector,u):
        angle=math.pi/2-(sector+u)*math.pi/4
        return (.04*math.cos(angle),.04*math.sin(angle))
    for sector in range(4):
        def charge_map(u,v,s=sector):
            a,b=square(s,u,.02),arc(s,u)
            return ((1-v)*a[0]+v*b[0],(1-v)*a[1]+v*b[1])
        def concrete_map(u,v,s=sector):
            a,b=arc(s,u),square(s,u,.12)
            return ((1-v)*a[0]+v*b[0],(1-v)*a[1]+v*b[1])
        add_block(n,p["charge_layers"],charge_map,1)
        add_block(n,p["concrete_layers"],concrete_map,2)
    far = 13*n//2
    width = 15*n//2
    add_block(far,2*n,lambda u,v:(.12+.78*u,-.12+.24*v),2)
    add_block(width,far,lambda u,v:(.9*u,.12+.78*v),2)
    add_block(width,far,lambda u,v:(.9*u,-.9+.78*v),2)
    expected = estimate_mesh(p)
    if len(nodes) != expected["nodes"] or len(elements) != expected["elements"]:
        raise ValueError("analytic block topology did not close as planned")
    return {"nodes":nodes,"elements":elements,"mesh":p,"estimate":expected}


def audit_mesh(nodes: list, elements: list) -> dict:
    """Inspect actual mesh rows, independent of their generating spec."""
    coordinates = {int(n[0]):tuple(float(v) for v in n[1:4]) for n in nodes}
    errors=[]
    if len(coordinates)!=len(nodes): errors.append("duplicate node IDs")
    if len({e[0] for e in elements})!=len(elements): errors.append("duplicate element IDs")
    if len(set(coordinates.values()))!=len(nodes): errors.append("duplicate coordinates")
    if not nodes or not elements: errors.append("empty mesh")
    if any(not all(math.isfinite(v) for v in p) or p[0]<0 or p[2]!=0 for p in coordinates.values()):
        errors.append("invalid r-z coordinates")
    references={nid for e in elements for nid in e[2:6]}
    if references-set(coordinates):
        return {"ok":False,"errors":errors+["missing node references"]}
    if set(coordinates)-references: errors.append("unreferenced nodes")
    edges=defaultdict(list)
    parts=defaultdict(lambda:{"elements":0,"area_m2":0.0,"volume_m3":0.0})
    minimum_jacobian=float("inf")
    negative=0
    parent={nid:nid for nid in coordinates}
    def find(nid):
        while parent[nid]!=nid:
            parent[nid]=parent[parent[nid]]
            nid=parent[nid]
        return nid
    gauss=1/math.sqrt(3)
    sample_points=[(-1,-1),(1,-1),(1,1),(-1,1),(-gauss,-gauss),(gauss,-gauss),(gauss,gauss),(-gauss,gauss)]
    derivatives=[]
    for xi,eta in sample_points:
        derivatives.append(([-(1-eta)/4,(1-eta)/4,(1+eta)/4,-(1+eta)/4],
                            [-(1-xi)/4,-(1+xi)/4,(1+xi)/4,(1-xi)/4]))
    for e in elements:
        if len(e)!=6 or len(set(e[2:]))!=4: errors.append("invalid quad connectivity"); continue
        pid=e[1]; corners=e[2:6]; pts=[coordinates[n] for n in corners]
        area=sum(pts[i][0]*pts[(i+1)%4][1]-pts[(i+1)%4][0]*pts[i][1] for i in range(4))/2
        moment=sum((pts[i][0]+pts[(i+1)%4][0])*(pts[i][0]*pts[(i+1)%4][1]-pts[(i+1)%4][0]*pts[i][1]) for i in range(4))/6
        parts[str(pid)]["elements"]+=1
        parts[str(pid)]["area_m2"]+=area
        parts[str(pid)]["volume_m3"]+=2*math.pi*moment
        negative+=area<=0
        for du,dv in derivatives:
            ux=sum(du[i]*pts[i][0] for i in range(4)); uy=sum(du[i]*pts[i][1] for i in range(4))
            vx=sum(dv[i]*pts[i][0] for i in range(4)); vy=sum(dv[i]*pts[i][1] for i in range(4))
            minimum_jacobian=min(minimum_jacobian,ux*vy-vx*uy)
        for a,b in zip(corners,corners[1:]+corners[:1]):
            edges[tuple(sorted((a,b)))].append(pid)
            parent[find(a)]=find(b)
    if negative: errors.append("nonpositive signed area")
    if minimum_jacobian<=0: errors.append("nonpositive Jacobian")
    if any(len(p)>2 for p in edges.values()): errors.append("nonmanifold edges")
    components=len({find(n) for n in references})
    if components!=1: errors.append("disconnected mesh")
    interface=[edge for edge,pids in edges.items() if len(set(pids))>1]
    interface_nodes={n for edge in interface for n in edge}
    fit=max((abs(math.hypot(*coordinates[n][:2])-.04) for n in interface_nodes),default=float("inf"))
    if fit>1e-10: errors.append("material interface does not fit source charge radius")
    if set(parts)!={"1","2"}: errors.append("incorrect material part coverage")
    area=sum(p["area_m2"] for p in parts.values())
    if not math.isclose(area,1.62,rel_tol=1e-10,abs_tol=1e-10): errors.append("total section area differs from source")
    bounds=[[min(p[i] for p in coordinates.values()),max(p[i] for p in coordinates.values())] for i in range(3)] if nodes else []
    if bounds!=[[0.0,.9],[-.9,.9],[0.0,0.0]]: errors.append("domain bounds differ from source")
    return {"ok":not errors,"errors":sorted(set(errors)),"node_count":len(nodes),"element_count":len(elements),
            "parts":dict(parts),"bounds_m":bounds,"minimum_jacobian":minimum_jacobian,
            "nonpositive_area_elements":negative,"connected_components":components,
            "interface_edges":len(interface),"interface_nodes":len(interface_nodes),"interface_radial_error_m":fit,
            "boundary_edges":sum(len(v)==1 for v in edges.values()),"total_area_m2":area}
