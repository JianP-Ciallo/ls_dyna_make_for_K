"""Geometry and topology checks for the R12 rectangular shell mesh contract."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math


UNITS = "mm_ms_g_N_MPa"
MAX_ELEMENTS = 100_000
MAX_NODES = 2 * MAX_ELEMENTS + 2
MAX_DIMENSION_MM = 1e9


def grid_count(length: float, size: float) -> int:
    return max(1, round(length / size))


def node_id(ix: int, iy: int, nx: int) -> int:
    return iy * (nx + 1) + ix + 1


def structured_plate(length: float, width: float, size: float, *, bounded: bool = True,
                     triangular: bool = False):
    try:
        nx, ny = grid_count(length, size), grid_count(width, size)
    except OverflowError:
        raise ValueError("网格数量超出可处理范围。") from None
    dx, dy = length / nx, width / ny
    if bounded and (nx * ny * (2 if triangular else 1) > MAX_ELEMENTS or min(dx, dy) < 1e-6):
        raise ValueError("结构化网格超出单元数量或坐标分辨率限制。")
    nodes = [
        (node_id(ix, iy, nx), ix * dx, iy * dy, 0.0)
        for iy in range(ny + 1) for ix in range(nx + 1)
    ]
    elements = [
        (iy * nx + ix + 1, 1, node_id(ix, iy, nx), node_id(ix + 1, iy, nx),
         node_id(ix + 1, iy + 1, nx), node_id(ix, iy + 1, nx))
        for iy in range(ny) for ix in range(nx)
    ]
    if triangular:
        triangles = []
        for eid, pid, a, b, c, d in elements:
            if ((eid - 1) // nx + (eid - 1) % nx) % 2 == 0:
                triangles.extend(((2 * eid - 1, pid, a, b, c, c), (2 * eid, pid, a, c, d, d)))
            else:
                triangles.extend(((2 * eid - 1, pid, a, b, d, d), (2 * eid, pid, b, c, d, d)))
        elements = triangles
    return nodes, elements, {"nx": nx, "ny": ny, "dx_mm": dx, "dy_mm": dy}


@dataclass(frozen=True)
class CheckedMesh:
    nodes: list
    elements: list
    regions: dict[str, list[int]]
    outline: list[list[float]]
    quality: dict
    part_id: int


def _positive_id(value) -> bool:
    return type(value) is int and 0 < value <= 99_999_999


def inspect_plate_mesh(nodes: list, elements: list) -> CheckedMesh:
    if not (0 < len(nodes) <= MAX_NODES and 0 < len(elements) <= MAX_ELEMENTS):
        raise ValueError("网格为空或节点、单元数量超出支持范围。")
    coordinates = {}
    for nid, *xyz in nodes:
        if not _positive_id(nid) or nid in coordinates or len(xyz) != 3 or any(
            type(value) not in (int, float) or abs(value) > MAX_DIMENSION_MM or not math.isfinite(value)
            for value in xyz
        ):
            raise ValueError("节点号或节点坐标无效。")
        coordinates[nid] = tuple(round(value, 6) for value in xyz)
    if len(set(coordinates.values())) != len(coordinates):
        raise ValueError("网格在 K 文件输出精度下存在重合节点。")
    xs, ys, zs = zip(*coordinates.values())
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if x1 <= x0 or y1 <= y0 or min(zs) != max(zs):
        raise ValueError("当前支持与 XY 平面平行的矩形壳网格。")

    edges = defaultdict(list)
    element_ids, parts, used = set(), set(), set()
    areas, lengths = [], []
    triangles = 0
    normalized = []
    for eid, pid, n1, n2, n3, n4 in elements:
        if not (_positive_id(eid) and _positive_id(pid)) or eid in element_ids:
            raise ValueError("单元或部件编号无效，或存在重复单元号。")
        if n4 in (0, n3):
            n4 = n3
            face = (n1, n2, n3)
            triangles += 1
        else:
            face = (n1, n2, n3, n4)
        if len(set(face)) != len(face) or any(not _positive_id(n) or n not in coordinates for n in face):
            raise ValueError(f"单元 {eid} 的节点引用无效。")
        points = [coordinates[n] for n in face]
        # Convex faces must turn consistently toward positive Z.
        vectors = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:] + points[:1])]
        turns = [a[0] * b[1] - a[1] * b[0] for a, b in zip(vectors, vectors[1:] + vectors[:1])]
        if min(turns) <= 0:
            raise ValueError(f"单元 {eid} 退化、凹折或法向偏离 +Z。")
        areas.append((turns[0] + (turns[2] if len(face) == 4 else 0)) / 2)
        lengths.extend(math.hypot(*vector) for vector in vectors)
        for a, b in zip(face, face[1:] + face[:1]):
            edges[tuple(sorted((a, b)))].append(a < b)
        element_ids.add(eid)
        parts.add(pid)
        used.update(face)
        normalized.append((eid, pid, n1, n2, n3, n4))
    if len(parts) != 1 or used != coordinates.keys():
        raise ValueError("当前网格应只有一个部件，且节点必须全部参与单元，不得存在孤立节点。")

    boundary = {"plate.left_edge": [], "plate.right_edge": [],
                "plate.bottom_edge": [], "plate.top_edge": []}
    for (a, b), directions in edges.items():
        if len(directions) == 2 and directions[0] != directions[1]:
            continue
        if len(directions) != 1:
            raise ValueError("单元连接存在重叠或非流形边。")
        ax, ay, _ = coordinates[a]
        bx, by, _ = coordinates[b]
        if ax == bx == x0:
            key, interval = "plate.left_edge", (ay, by)
        elif ax == bx == x1:
            key, interval = "plate.right_edge", (ay, by)
        elif ay == by == y0:
            key, interval = "plate.bottom_edge", (ax, bx)
        elif ay == by == y1:
            key, interval = "plate.top_edge", (ax, bx)
        else:
            raise ValueError("发现矩形外轮廓之外的自由边，网格可能缺角、有孔或断裂。")
        boundary[key].append((*sorted(interval), a, b))

    regions = {"plate.part": sorted(parts)}
    for key, segments in boundary.items():
        lower, upper = (y0, y1) if key in ("plate.left_edge", "plate.right_edge") else (x0, x1)
        for start, end, _, _ in sorted(segments):
            if start != lower or start >= end:
                raise ValueError(f"{key} 边界存在间隙或重叠。")
            lower = end
        if lower != upper:
            raise ValueError(f"{key} 未覆盖完整边界。")
        regions[key] = sorted({nid for _, _, a, b in segments for nid in (a, b)})
    area = math.fsum(areas)
    if not math.isclose(area, (x1 - x0) * (y1 - y0), rel_tol=1e-9):
        raise ValueError("单元覆盖面积与矩形轮廓不一致。")
    return CheckedMesh(
        [(nid, *xyz) for nid, xyz in sorted(coordinates.items())],
        sorted(normalized), regions, [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
        {"node_count": len(nodes), "element_count": len(elements), "triangle_count": triangles,
         "quad_count": len(elements) - triangles, "area_mm2": area,
         "min_element_area_mm2": min(areas), "max_edge_mm": max(lengths), "normal": "+Z"},
        next(iter(parts)),
    )


def shell_elform(mesh: CheckedMesh) -> int:
    return 2 if mesh.quality["quad_count"] else 4


def shell_sort_card(mesh: CheckedMesh) -> str | None:
    # R12 ESORT=1 changes degenerate ELFORM 2 shells to triangle ELFORM 4.
    if mesh.quality["triangle_count"] and mesh.quality["quad_count"]:
        return "20,1,-1,0,2,2,1,0"
    return None


def r12_number(value: float, width: int) -> str:
    for precision in range(17, 0, -1):
        text = format(value, f".{precision}g")
        if len(text) <= width and float(text) == value:
            return text
    raise ValueError(f"数值 {value} 无法在 R12 的 {width} 字符字段内保持精度。")


def verify_written_plate(text: str, mesh: CheckedMesh, *, material: tuple, thickness: float) -> dict:
    """Read the writer's comma-formatted cards and check effective bindings."""
    cards = defaultdict(list)
    active = None
    order = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("*"):
            order.append(line)
            active = []
            cards[line].append(active)
        elif line and not line.startswith("$"):
            if active is None:
                raise ValueError("K 文件在 *KEYWORD 之前存在未识别的数据。")
            active.append(line)
    expected = [
        "*KEYWORD", "*TITLE", "*CONTROL_TERMINATION", "*DATABASE_BINARY_D3PLOT", "*NODE",
        "*ELEMENT_SHELL", "*PART", "*SECTION_SHELL", "*MAT_ELASTIC", "*SET_NODE_LIST",
        "*SET_NODE_LIST", "*BOUNDARY_SPC_SET", "*END",
    ]
    if sort_card := shell_sort_card(mesh):
        expected.insert(3, "*CONTROL_SHELL")
    if order != expected or cards["*KEYWORD"] != [[]] or cards["*END"] != [[]]:
        raise ValueError("K 文件关键字顺序或范围与当前配置计划不一致。")

    def rows(keyword: str) -> list[str]:
        blocks = cards[keyword]
        if len(blocks) != 1:
            raise ValueError(f"写出后的 {keyword} 数量不符合配置计划。")
        return blocks[0]

    if sort_card and rows("*CONTROL_SHELL") != [sort_card]:
        raise ValueError("回读的三角形壳单元排序设置与网格类型不一致。")
    field_widths = {
        "*NODE": (8, 16, 16, 16), "*ELEMENT_SHELL": (8,) * 6,
        "*SECTION_SHELL": (10,) * 8, "*MAT_ELASTIC": (10,) * 4,
    }
    for keyword, widths in field_widths.items():
        for row in rows(keyword):
            if len(row) > 80 or any(len(value) > width for value, width in zip(row.split(","), widths)):
                raise ValueError(f"回读的 {keyword} 数值超出 R12 字段宽度。")
    node_rows = [(int(nid), float(x), float(y), float(z))
                 for nid, x, y, z in (row.split(",") for row in rows("*NODE"))]
    element_rows = [tuple(map(int, row.split(","))) for row in rows("*ELEMENT_SHELL")]
    if node_rows != mesh.nodes or element_rows != mesh.elements:
        raise ValueError("回读的节点或单元与已核验网格不同。")
    sets = {}
    for header, *data in cards["*SET_NODE_LIST"]:
        sid = int(header.split(",")[0])
        if sid in sets:
            raise ValueError("回读发现重复节点集合。")
        sets[sid] = [int(nid) for row in data for nid in row.split(",")]
    if sets != {1001: mesh.regions["plate.left_edge"], 1002: mesh.regions["plate.right_edge"]}:
        raise ValueError("回读的节点集合与当前网格边缘映射不一致。")
    if rows("*BOUNDARY_SPC_SET") != ["1001,0,1,1,1,1,1,1"]:
        raise ValueError("回读的约束集合或自由度与配置计划不一致。")
    _, part = rows("*PART")
    if list(map(int, part.split(","))) != [mesh.part_id, 1, 1, 0, 0, 0, 0, 0]:
        raise ValueError("回读的部件与材料、截面引用不一致。")
    section, thickness_row = rows("*SECTION_SHELL")
    if list(map(float, section.split(","))) != [1, shell_elform(mesh), 0.833, 5, 1, 0, 0, 0] or [
        float(item) for item in thickness_row.split(",")
    ] != [thickness] * 4 + [0, 0]:
        raise ValueError("回读的截面或厚度与配置计划不一致。")
    material_rows = rows("*MAT_ELASTIC")
    if len(material_rows) != 1 or tuple(map(float, material_rows[0].split(","))) != (1, *material):
        raise ValueError("回读的弹性材料参数与配置计划不一致。")
    return {"plate.part": {"part_id": mesh.part_id, "material_id": 1, "section_id": 1},
            "plate.left_edge": {"set_id": 1001, "node_count": len(sets[1001]), "dofs": [1] * 6},
            "plate.right_edge": {"set_id": 1002, "node_count": len(sets[1002])}}
