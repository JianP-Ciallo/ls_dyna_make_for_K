"""Read ordinary keyword geometry and Gmsh MSH 2.2 ASCII shell meshes."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from .mesh_geometry import MAX_ELEMENTS, MAX_NODES, UNITS
from .planner_deck import MAX_DECK_BYTES, MAX_INCLUDE_DEPTH, UNIT_MARKER, resolve_local_include


_SI_COMMENT = re.compile(r"^\s*\$\s*SI\s*:\s*m\s*,\s*s\s*,\s*kg\s*,\s*N\s*,\s*Pa\b", re.I)
_LENGTH_BY_SYSTEM = {UNITS.casefold(): "mm", "si_m_s_kg_n_pa": "m"}


def _number(value: str) -> float:
    value = value.lower().replace("d", "e")
    if "e" not in value:
        value = re.sub(r"(?<=\d)([+-]\d+)$", r"e\1", value)
    return float(value)


def _key_fields(line: str, widths: tuple[int, ...]) -> list[str]:
    if "," in line:
        return [value.strip() for value in line.split(",")]
    fields = []
    offset = 0
    for width in widths:
        fields.append(line[offset:offset + width].strip())
        offset += width
    if line[offset:].strip():
        fields.append(line[offset:].strip())
    return fields


def _read_file(path: Path, limit: int) -> bytes:
    if not path.is_file():
        raise ValueError(f"网格文件不可读：{path.name}")
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit or b"\0" in content:
        raise ValueError("仅支持限制大小内的文本网格。")
    return content


def read_keyword_mesh(entry: Path) -> tuple[list, list, list, str | None]:
    base = entry.parent
    nodes, elements = [], []
    fingerprints = {}
    length_units = set()
    bytes_left = MAX_DECK_BYTES

    def visit(path: Path, depth: int) -> None:
        nonlocal bytes_left
        relative = path.relative_to(base).as_posix()
        if depth > MAX_INCLUDE_DEPTH or relative in fingerprints:
            raise ValueError(f"重复、循环或过深的 INCLUDE：{relative}")
        data = _read_file(path, bytes_left)
        bytes_left -= len(data)
        fingerprints[relative] = hashlib.sha256(data).hexdigest()
        keyword = None
        include_has_file = False
        for number, raw in enumerate(data.decode("utf-8-sig", errors="surrogateescape").splitlines(), 1):
            if marker := UNIT_MARKER.match(raw):
                unit = _LENGTH_BY_SYSTEM.get(marker[1].casefold())
                if unit is None:
                    raise ValueError(f"网格来源 {relative} 的单位标记不受支持。")
                length_units.add(unit)
            if _SI_COMMENT.match(raw):
                length_units.add("m")
            line = raw.split("$", 1)[0].rstrip()
            if not line.strip():
                continue
            if line.lstrip().startswith("*"):
                if keyword == "*INCLUDE" and not include_has_file:
                    raise ValueError(f"{relative}:{number} 前的 INCLUDE 缺少文件名。")
                keyword = line.strip().split()[0].upper()
                include_has_file = False
                if keyword == "*END":
                    break
                if (
                    keyword.startswith(("*NODE", "*ELEMENT", "*INCLUDE"))
                    and keyword not in ("*NODE", "*ELEMENT_SHELL", "*INCLUDE")
                    or keyword == "*KEYWORD" and re.search(r"\bLONG\s*=\s*[YS]", line, re.I)
                ):
                    raise ValueError(f"{relative}:{number} 的网格关键字或格式不受支持：{keyword}")
                continue
            if keyword == "*INCLUDE":
                visit(resolve_local_include(base, line.strip(), relative), depth + 1)
                include_has_file = True
                continue
            try:
                if keyword == "*NODE":
                    nid, x, y, z, *_ = _key_fields(line, (8, 16, 16, 16, 8, 8))
                    nodes.append((int(nid), _number(x), _number(y), _number(z)))
                elif keyword == "*ELEMENT_SHELL":
                    eid, pid, n1, n2, n3, *tail = _key_fields(line, (8,) * 10)
                    n4 = tail[0] if tail else ""
                    if any(value and value != "0" for value in tail[1:]):
                        raise ValueError("高阶壳单元不在范围内")
                    elements.append(tuple(map(int, (eid, pid, n1, n2, n3, n4 or "0"))))
            except (ValueError, TypeError):
                raise ValueError(f"{relative}:{number} 的 {keyword} 数据格式不受支持。") from None
            if len(nodes) > MAX_NODES or len(elements) > MAX_ELEMENTS:
                raise ValueError("导入网格的节点或单元数超出限制。")
        if keyword == "*INCLUDE" and not include_has_file:
            raise ValueError(f"{relative} 的 INCLUDE 缺少文件名。")

    visit(entry, 0)
    if len(length_units) > 1:
        raise ValueError("主 K 文件及 INCLUDE 的源长度单位标记不一致。")
    sources = [{"path": path, "sha256": sha} for path, sha in sorted(fingerprints.items())]
    return nodes, elements, sources, next(iter(length_units), None)


def read_gmsh_mesh(path: Path) -> tuple[list, list, list]:
    raw = _read_file(path, MAX_DECK_BYTES)
    lines = [line.strip() for line in raw.decode("utf-8-sig").splitlines() if line.strip()]

    def section(name: str) -> list[str]:
        header, end = "$" + name, "$End" + name
        if lines.count(header) != 1 or lines.count(end) != 1:
            raise ValueError(f"Gmsh 网格缺少或重复 {name} 段。")
        rows = lines[lines.index(header) + 1:lines.index(end)]
        if not rows:
            raise ValueError(f"Gmsh 网格的 {name} 段为空。")
        return rows

    header = section("MeshFormat")
    if len(header) != 1 or header[0].split() != ["2.2", "0", "8"]:
        raise ValueError("请将 Gmsh 网格导出为 MSH 2.2 ASCII。")
    node_count, *node_rows = section("Nodes")
    element_count, *element_rows = section("Elements")
    if int(node_count) != len(node_rows) or int(element_count) != len(element_rows):
        raise ValueError("Gmsh 声明的节点或单元数量与文件不一致。")
    if len(node_rows) > MAX_NODES or len(element_rows) > MAX_NODES + MAX_ELEMENTS:
        raise ValueError("Gmsh 网格的节点或单元数超出限制。")
    nodes, elements = [], []
    group_keys, seen = set(), set()
    for row in node_rows:
        nid, x, y, z = row.split()
        nodes.append((int(nid), float(x), float(y), float(z)))
    node_ids = {row[0] for row in nodes}
    for row in element_rows:
        eid, kind, tag_count, *fields = map(int, row.split())
        expected_count = {1: 2, 2: 3, 3: 4, 15: 1}.get(kind)
        if (expected_count is None or tag_count < 0 or len(fields) != expected_count + tag_count
                or eid <= 0 or eid in seen or not node_ids.issuperset(fields[tag_count:])):
            raise ValueError("Gmsh 仅支持一阶点/边/三角形/四边形，且单元记录与编号须有效。")
        seen.add(eid)
        if kind in (1, 15):
            continue
        tags, face = fields[:tag_count], fields[tag_count:]
        physical_id = tags[0] if tags else 0
        entity = tags[1] if len(tags) > 1 else 0
        group_keys.add(("physical", physical_id) if physical_id else ("entity", entity))
        if kind == 2:
            face.append(face[-1])
        elements.append((eid, physical_id or 1, *face))
    if len(group_keys) != 1:
        raise ValueError("Gmsh 网格须包含一个壳部件对应的面组。")
    return nodes, elements, [{"path": path.name, "sha256": hashlib.sha256(raw).hexdigest()}]
