"""Fixed presentation geometry. This is not a solver model or an engineering mesh."""
from __future__ import annotations

import math

REQUEST_SCHEMA = "lsprepost_mcp.synthetic_damage_request@1"
WARNING = "合成数据演示，非真实求解预测；不能用于实际爆源设计、毁伤预测或建筑安全鉴定。"
BOX_FACES = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4],
             [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]


def box_nodes(low, high):
    x, y, z = low
    a, b, c = high
    return [[x, y, z], [a, y, z], [a, b, z], [x, b, z],
            [x, y, c], [a, y, c], [a, b, c], [x, b, c]]


def validate_demo_input(value):
    if not isinstance(value, dict) or set(value) != {"schema_version", "mode", "sources"}:
        raise ValueError("演示请求仅允许 schema_version、mode、sources，不接受项目或文件路径。")
    if value["schema_version"] != REQUEST_SCHEMA or value["mode"] not in ("complete", "partial", "blocked"):
        raise ValueError("不支持的演示版本或数据状态。")
    sources = value["sources"]
    if not isinstance(sources, list) or not 1 <= len(sources) <= 5:
        raise ValueError("演示支持 1—5 个爆源。")
    normalized = []
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"position_m", "equivalent_kg"}:
            raise ValueError("爆源仅允许 position_m 和 equivalent_kg。")
        position = source["position_m"]
        if not isinstance(position, list) or len(position) != 3:
            raise ValueError("爆源位置必须包含 X、Y、Z。")
        values = [*position, source["equivalent_kg"]]
        limits = [(-15, 15), (-15, 15), (0, 15), (1, 1000)]
        for number, (low, high) in zip(values, limits):
            if (isinstance(number, bool) or not isinstance(number, (int, float))
                    or not low <= number <= high or not math.isfinite(number)):
                raise ValueError("演示参数必须为有限数值：X/Y -15—15，Z 0—15，当量 1—1000。")
        normalized.append({"position_m": [float(v) for v in position], "equivalent_kg": float(source["equivalent_kg"])})
    return {"schema_version": REQUEST_SCHEMA, "mode": value["mode"], "sources": normalized}


def scene_payload():
    components = []

    def add(role, floor, low, high, label, part_id=None):
        part_id = part_id or 1001 + len(components)
        components.append({"component_id": f"synthetic-demo-{part_id}", "part_id": part_id,
                           "label": label, "role": role, "floor": floor, "low": low, "high": high})

    for floor in (1, 2, 3):
        bottom, top = (floor - 1) * 3.0, floor * 3.0
        for x in (-4, 0, 4):
            for y in (-3, 0, 3):
                add("column", floor, [x-.22, y-.22, bottom], [x+.22, y+.22, top], f"{floor}层柱 ({x},{y})")
        for x in (-4, 0):
            for y in (-3, 0, 3):
                add("beam", floor, [x, y-.18, top-.4], [x+4, y+.18, top], f"{floor}层 X 向梁 ({x},{y})")
        for x in (-4, 0, 4):
            for y in (-3, 0):
                add("beam", floor, [x-.18, y, top-.4], [x+.18, y+3, top], f"{floor}层 Y 向梁 ({x},{y})")
        add("slab", floor, [-4.2, -3.2, top], [4.2, 3.2, top+.16], f"{floor}层楼板")
        for y, label in ((-3.1, "南"), (3.1, "北")):
            add("wall", floor, [-4, y-.08, bottom+.25], [4, y+.08, top-.5], f"{floor}层{label}外墙")
        for x, label in ((-4.1, "西"), (4.1, "东")):
            add("wall", floor, [x-.08, -3, bottom+.25], [x+.08, 3, top-.5], f"{floor}层{label}外墙")
    for index, (x, y) in enumerate(((-12, -12), (0, -12), (-12, 0), (0, 0))):
        add("ground", 0, [x, y, -.6], [x+12, y+12, 0], f"地面区域 {index+1}", 8001+index)
    parts = [{"part_id": c["part_id"], "name": c["label"], "nodes": box_nodes(c["low"], c["high"]),
              "faces": BOX_FACES, "edges": [], "color": "#9aa8b2",
              "opacity": 1} for c in components]
    return {"schema_version": "lsprepost_mcp.synthetic_damage_scene@1", "synthetic_demo": True,
            "warning": WARNING, "components": components,
            "mesh": {"parts": parts, "bounds": {"min": [-15, -15, -1], "max": [15, 15, 16]}, "blast_sources": []},
            "defaults": {"schema_version": REQUEST_SCHEMA, "mode": "complete",
                         "sources": [{"position_m": [-6, -4, 2], "equivalent_kg": 100}]}}
