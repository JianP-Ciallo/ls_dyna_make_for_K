from __future__ import annotations

from .config import JSONDict
from .schema import ModelSpec
from .dyna_common import DOF_NUMBERS, SPC_DOF_MASK, Segment
from .dyna_selectors import (
    curve_lines,
    node_set_lines,
    nodes_from_selector,
    nodes_for_edge,
    part_set_lines,
    segment_selector,
    segment_set_lines,
    segments_for_selector,
    velocity_vector,
)

def boundary_and_load_lines(
    spec: ModelSpec,
    nodes: list[tuple[int, float, float, float]],
    segments: list[Segment] | None = None,
) -> tuple[list[str], JSONDict]:
    lines: list[str] = []
    set_id = 1001
    used_curve_ids = {int(curve["id"]) for curve in spec.curves}
    curve_id = 2001
    node_set_ids: dict[str, int] = {}
    node_set_nodes: dict[str, list[int]] = {}
    part_set_ids: dict[str, int] = {}
    segment_set_ids: dict[str, int] = {}
    segment_candidates = segments or []
    counts = {
        "constraint_count": 0,
        "node_set_count": 0,
        "part_set_count": 0,
        "segment_set_count": 0,
        "load_count": 0,
        "initial_condition_count": 0,
        "curve_count": 0,
    }

    def next_set_id() -> int:
        nonlocal set_id
        current = set_id
        set_id += 1
        return current

    def next_curve_id() -> int:
        nonlocal curve_id
        while curve_id in used_curve_ids:
            curve_id += 1
        current = curve_id
        used_curve_ids.add(current)
        curve_id += 1
        return current

    def node_ids_from_selector(item: JSONDict) -> list[int]:
        return nodes_from_selector(spec, nodes, item)

    def emit_node_set(name: str, selector: JSONDict, label: str) -> int:
        if name in node_set_ids:
            return node_set_ids[name]
        sid = next_set_id()
        ids = node_ids_from_selector(selector)
        lines.extend(node_set_lines(sid, label, ids))
        node_set_ids[name] = sid
        node_set_nodes[name] = ids
        counts["node_set_count"] += 1
        return sid

    def emit_part_set(name: str, part_ids: list[int], label: str) -> int:
        if name in part_set_ids:
            return part_set_ids[name]
        sid = next_set_id()
        lines.extend(part_set_lines(sid, label, part_ids))
        part_set_ids[name] = sid
        counts["part_set_count"] += 1
        return sid

    def emit_segment_set(name: str, selector: JSONDict, label: str) -> int:
        if name in segment_set_ids:
            return segment_set_ids[name]
        sid = next_set_id()
        selected = segments_for_selector(spec, nodes, segment_candidates, selector)
        lines.extend(segment_set_lines(sid, label, selected))
        segment_set_ids[name] = sid
        counts["segment_set_count"] += 1
        return sid

    for item in spec.sets:
        set_type = item.get("type")
        name = str(item["name"])
        if set_type == "node_set":
            emit_node_set(name, item, f"node_set {name}")
        elif set_type == "part_set":
            emit_part_set(name, [int(part_id) for part_id in item["part_ids"]], f"part_set {name}")
        elif set_type == "segment_set":
            emit_segment_set(name, segment_selector(item), f"segment_set {name}")

    def resolve_node_target(item: JSONDict, label: str) -> tuple[int, list[int]]:
        target = item.get("target")
        if isinstance(target, dict):
            target_type = target.get("type")
            if target_type == "edge":
                edge = str(target["edge"])
                name = str(target.get("name", f"inline_{label}_{set_id}"))
                sid = emit_node_set(name, target, f"{label} {name}")
                return sid, nodes_for_edge(spec, nodes, edge)
            if target_type == "node_set":
                name = str(target["name"])
                if name not in node_set_ids:
                    sid = emit_node_set(name, target, f"{label} {name}")
                else:
                    sid = node_set_ids[name]
                return sid, node_set_nodes[name]
            if target_type == "part_set":
                name = str(target["name"])
                if name not in part_set_ids:
                    raise ValueError(f"part_set target {name} is not defined")
                return part_set_ids[name], [nid for nid, _, _, _ in nodes]
        edge = str(item["edge"])
        name = f"inline_{label}_{set_id}"
        sid = emit_node_set(name, item, f"{label} {edge}")
        return sid, nodes_for_edge(spec, nodes, edge)

    def resolve_segment_target(item: JSONDict, label: str) -> int:
        target = item.get("target")
        if isinstance(target, dict):
            name = str(target["name"])
            if name not in segment_set_ids:
                return emit_segment_set(name, segment_selector(target), f"{label} {name}")
            return segment_set_ids[name]
        name = f"inline_{label}_{set_id}"
        return emit_segment_set(name, segment_selector(item), f"{label} {name}")

    for item in spec.boundary_conditions:
        item_type = item.get("type")
        if item_type == "fixed_edge":
            sid, _ = resolve_node_target(item, "fixed")
            lines.extend(
                [
                    "*BOUNDARY_SPC_SET",
                    "$#  nsid       cid      dofx      dofy      dofz     dofrx     dofry     dofrz",
                    f"{sid},0,1,1,1,1,1,1",
                ]
            )
            counts["constraint_count"] += 1
        elif item_type == "spc_node_set":
            if "node_ids" in item:
                name = str(item.get("name", f"inline_spc_{set_id}"))
                sid = emit_node_set(name, item, f"spc {name}")
            else:
                sid, _ = resolve_node_target(item, "spc")
            mask = [0, 0, 0, 0, 0, 0]
            for dof in item["dofs"]:
                mask[SPC_DOF_MASK[str(dof)]] = 1
            lines.extend(
                [
                    "*BOUNDARY_SPC_SET",
                    "$#  nsid       cid      dofx      dofy      dofz     dofrx     dofry     dofrz",
                    f"{sid},0,{mask[0]},{mask[1]},{mask[2]},{mask[3]},{mask[4]},{mask[5]}",
                ]
            )
            counts["constraint_count"] += 1
        elif item_type == "prescribed_displacement":
            dof = str(item["dof"])
            sid, _ = resolve_node_target(item, "prescribed_displacement")
            active_curve_id = int(item["curve_id"]) if "curve_id" in item else next_curve_id()
            if "curve_id" not in item:
                lines.extend(curve_lines(active_curve_id, item, "value_m", f"prescribed displacement {dof}"))
                counts["curve_count"] += 1
            lines.extend(
                [
                    "*BOUNDARY_PRESCRIBED_MOTION_SET",
                    "$#  nsid       dof       vad      lcid        sf       vid     death     birth",
                    f"{sid},{DOF_NUMBERS[dof]},2,{active_curve_id},1.0,0,1.0e28,0.0",
                ]
            )
            counts["constraint_count"] += 1
        elif item_type == "prescribed_velocity":
            dof = str(item["dof"])
            sid, _ = resolve_node_target(item, "prescribed_velocity")
            active_curve_id = int(item["curve_id"]) if "curve_id" in item else next_curve_id()
            if "curve_id" not in item:
                lines.extend(curve_lines(active_curve_id, item, "value_m_per_s", f"prescribed velocity {dof}"))
                counts["curve_count"] += 1
            lines.extend(
                [
                    "*BOUNDARY_PRESCRIBED_MOTION_SET",
                    "$#  nsid       dof       vad      lcid        sf       vid     death     birth",
                    f"{sid},{DOF_NUMBERS[dof]},0,{active_curve_id},1.0,0,1.0e28,0.0",
                ]
            )
            counts["constraint_count"] += 1

    for item in spec.loads:
        item_type = item.get("type")
        if item_type == "nodal_force":
            dof = str(item["dof"])
            sid, _ = resolve_node_target(item, "nodal_force")
            active_curve_id = int(item["curve_id"]) if "curve_id" in item else next_curve_id()
            if "curve_id" not in item:
                lines.extend(curve_lines(active_curve_id, item, "value_n", f"nodal force {dof}"))
                counts["curve_count"] += 1
            lines.extend(
                [
                    "*LOAD_NODE_SET",
                    "$#  nsid       dof      lcid        sf       cid        m1        m2        m3",
                    f"{sid},{DOF_NUMBERS[dof]},{active_curve_id},1.0,0,0,0,0",
                ]
            )
            counts["load_count"] += 1
        elif item_type == "gravity":
            direction = str(item["direction"])
            active_curve_id = int(item["curve_id"]) if "curve_id" in item else next_curve_id()
            if "curve_id" not in item:
                lines.extend(curve_lines(active_curve_id, item, "acceleration_m_per_s2", f"gravity {direction}"))
                counts["curve_count"] += 1
            lines.extend(
                [
                    f"*LOAD_BODY_{direction.upper()}",
                    "$#  lcid        sf",
                    f"{active_curve_id},1.0",
                ]
            )
            counts["load_count"] += 1
        elif item_type == "pressure_on_segment_set":
            sid = resolve_segment_target(item, "pressure")
            active_curve_id = int(item["curve_id"]) if "curve_id" in item else next_curve_id()
            if "curve_id" not in item:
                lines.extend(curve_lines(active_curve_id, item, "pressure_pa", "pressure"))
                counts["curve_count"] += 1
            lines.extend(
                [
                    "*LOAD_SEGMENT_SET",
                    "$#  ssid      lcid        sf       at        n1        n2        n3        n4",
                    f"{sid},{active_curve_id},1.0,0.0,0,0,0,0",
                ]
            )
            counts["load_count"] += 1
        elif item_type == "pressure_on_segment":
            active_curve_id = int(item["curve_id"]) if "curve_id" in item else next_curve_id()
            if "curve_id" not in item:
                lines.extend(curve_lines(active_curve_id, item, "pressure_pa", "pressure segment"))
                counts["curve_count"] += 1
            segment = [int(value) for value in item["segment"]]
            lines.extend(
                [
                    "*LOAD_SEGMENT",
                    "$#  lcid        sf        at        n1        n2        n3        n4",
                    f"{active_curve_id},{float(item.get('scale_factor', 1.0)):.9g},{float(item.get('arrival_time_s', 0.0)):.9g},{segment[0]},{segment[1]},{segment[2]},{segment[3]}",
                ]
            )
            counts["load_count"] += 1
        elif item_type == "initial_velocity":
            _, ids = resolve_node_target(item, "initial_velocity")
            vx, vy, vz = velocity_vector(item)
            lines.extend(
                [
                    "*INITIAL_VELOCITY_NODE",
                    "$#   nid        vx        vy        vz       vxr       vyr       vzr",
                ]
            )
            lines.extend(f"{nid},{vx:.9g},{vy:.9g},{vz:.9g},0.0,0.0,0.0" for nid in ids)
            counts["initial_condition_count"] += 1
    counts["curve_count"] += len(spec.curves)
    counts["hourglass_count"] = 1 if spec.hourglass else 0
    counts["control_count"] = 1 + sum(1 for key in ["energy", "shell", "timestep"] if isinstance(spec.analysis_control.get(key), dict))
    counts["database_count"] = 1 + int("d3thdt_dt_s" in spec.database) + int("nodout_dt_s" in spec.database) + int(isinstance(spec.database.get("extent_binary"), dict)) + int("format" in spec.database)
    return lines, counts


