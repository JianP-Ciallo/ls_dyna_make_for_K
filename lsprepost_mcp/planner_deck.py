"""Read ordinary LS-DYNA decks for material-edit planning."""
from __future__ import annotations

import hashlib
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath


ELASTIC = {"*MAT_ELASTIC", "*MAT_001", "*MAT_ELASTIC_TITLE", "*MAT_001_TITLE"}
MAX_DECK_BYTES = 64 * 1024 * 1024
MAX_INCLUDE_DEPTH = 32
UNIT_MARKER = re.compile(r"^\s*\$\s*Unit system\s*:\s*(\w+)", re.I)


@dataclass(frozen=True)
class Card:
    keyword: str
    path: str
    line: int
    fields: list[str]

    def location(self) -> dict:
        return {"keyword": self.keyword, "path": self.path, "line": self.line}


def _fields(text: str) -> list[str]:
    if "," in text:
        return [value.strip() for value in text.split(",")]
    return [text[start:start + 10].strip() for start in range(0, len(text), 10)]


def _id(fields: list[str], index: int, card: Card) -> int:
    try:
        number = int(fields[index])
        if number > 0:
            return number
    except (IndexError, ValueError):
        pass
    raise ValueError(f"{card.path}:{card.line} 的 ID 缺失或格式不受支持。")


def _old_modulus(card: Card) -> float:
    try:
        text = card.fields[2].lower().replace("d", "e")
        text = re.sub(r"(?<=\d)([+-]\d+)$", r"e\1", text) if "e" not in text else text
        value = float(text)
        if math.isfinite(value) and value > 0:
            return value
    except (IndexError, ValueError):
        pass
    raise ValueError(f"{card.path}:{card.line} 的弹性模量必须是可读取的正数。")


def resolve_local_include(base: Path, text: str, source: str) -> Path:
    target = text.strip("\"'")
    windows = PureWindowsPath(target)
    if not target or ":" in target or windows.anchor or Path(target).is_absolute() or target.endswith(" +"):
        raise ValueError(f"{source} 中的 INCLUDE 必须使用模型目录内的单行相对路径。")
    candidate = Path(os.path.abspath(base / target.replace("\\", "/")))
    if not candidate.is_relative_to(base) or candidate == base:
        raise ValueError(f"{source} 中的 INCLUDE 越出模型目录或指向目录本身。")
    # Windows may allow reading a file while denying strict realpath.
    for component in (candidate, *candidate.parents):
        if component == base:
            break
        metadata = component.lstat()
        if stat.S_ISLNK(metadata.st_mode) or (
            getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError(f"{source} 中的 INCLUDE 指向链接或重解析点。")
    return candidate


@dataclass
class DeckSnapshot:
    entry: Path
    parts: dict[int, tuple[int, Card]]
    materials: dict[int, Card]
    files: dict[str, str]
    unit_markers: set[str]
    material_addons: bool

    def provenance(self) -> dict:
        files = [{"path": path, "sha256": digest} for path, digest in sorted(self.files.items())]
        digest = hashlib.sha256()
        for item in files:
            digest.update(item["path"].encode("utf-8") + b"\0")
            digest.update(bytes.fromhex(item["sha256"]))
        return {"entry_path": str(self.entry), "sha256": digest.hexdigest(), "files": files}


def inspect_deck(path: Path) -> DeckSnapshot:
    entry = path.resolve()
    base = entry.parent
    snapshot = DeckSnapshot(entry, {}, {}, {}, set(), False)
    bytes_read = 0

    def visit(path: Path, depth: int) -> None:
        nonlocal bytes_read
        if depth > MAX_INCLUDE_DEPTH:
            raise ValueError("INCLUDE 嵌套过深。")
        relative = path.relative_to(base).as_posix()
        if relative in snapshot.files:
            raise ValueError(f"重复或循环引用 INCLUDE 文件 {relative}。")
        if not path.is_file():
            raise ValueError(f"无法读取 K 文件 {relative}。")
        with path.open("rb") as stream:
            data = stream.read(MAX_DECK_BYTES - bytes_read + 1)
        bytes_read += len(data)
        if bytes_read > MAX_DECK_BYTES:
            raise ValueError("K 文件及其 INCLUDE 超过首版的 64 MiB 读取范围。")
        if b"\0" in data:
            raise ValueError(f"{relative} 不是受支持的文本 K 文件。")
        snapshot.files[relative] = hashlib.sha256(data).hexdigest()
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")

        keyword = ""
        rows = []

        def consume() -> None:
            if keyword.startswith("*INCLUDE"):
                if keyword != "*INCLUDE" or not rows:
                    raise ValueError(f"{relative} 包含不受支持的 {keyword} 格式。")
                for _, target in rows:
                    visit(resolve_local_include(base, target.strip(), relative), depth + 1)
            elif keyword == "*PART" or keyword.startswith("*MAT"):
                if keyword.startswith(("*MAT_ADD", "*MAT_THERMAL")):
                    snapshot.material_addons = True
                    return
                offset = 1 if keyword == "*PART" or keyword.endswith("_TITLE") else 0
                if len(rows) <= offset:
                    raise ValueError(f"{relative} 中 {keyword} 缺少数据行。")
                line_number, raw_fields = rows[offset]
                card = Card(keyword, relative, line_number, _fields(raw_fields))
                identifier = _id(card.fields, 0, card)
                if keyword == "*PART":
                    if identifier in snapshot.parts or len(rows) != 2:
                        raise ValueError(f"{relative}:{line_number} 的部件定义重复或格式不受支持。")
                    snapshot.parts[identifier] = (_id(card.fields, 2, card), card)
                else:
                    if identifier in snapshot.materials:
                        raise ValueError(f"{relative}:{line_number} 重复定义材料 {identifier}。")
                    snapshot.materials[identifier] = card

        for number, raw_line in enumerate(text.splitlines(), start=1):
            if marker := UNIT_MARKER.match(raw_line):
                snapshot.unit_markers.add(marker[1].casefold())
            line = raw_line.split("$", 1)[0].rstrip()
            if not line.strip():
                continue
            stripped = line.lstrip()
            if stripped.startswith("*"):
                consume()
                keyword = stripped.split()[0].upper()
                rows = []
                if keyword == "*END":
                    break
                if keyword.startswith("*PART_") or (
                    keyword == "*KEYWORD" and re.search(r"\bLONG\s*=\s*[YS]", stripped, re.I)
                ):
                    raise ValueError(f"{relative}:{number} 的部件或字段格式不受支持。")
            elif keyword == "*PART" or keyword.startswith(("*MAT", "*INCLUDE")):
                rows.append((number, line))
        else:
            consume()

    visit(entry, 0)
    return snapshot


def locate_elastic_change(
    deck: DeckSnapshot, *, part_id: int | None, material_id: int | None, new_value: float,
    all_referencing_parts: bool,
) -> dict:
    if part_id is not None:
        if part_id not in deck.parts:
            raise LookupError("所选部件 ID 不存在，请确认部件 ID。")
        referenced_id, _ = deck.parts[part_id]
        if material_id is not None and material_id != referenced_id:
            raise LookupError("所选部件与材料 ID 不对应，请确认修改对象。")
        material_id = referenced_id
    if material_id not in deck.materials:
        raise LookupError("所选材料 ID 不存在，请确认材料 ID。")
    material = deck.materials[material_id]
    if material.keyword not in ELASTIC:
        raise ValueError("首版只支持普通 *MAT_ELASTIC / *MAT_001 的弹性模量 E。")
    referencing = sorted(pid for pid, (mid, _) in deck.parts.items() if mid == material_id)
    if len(referencing) > 1 and part_id is None and not all_referencing_parts:
        raise LookupError("该材料由多个部件共享，请指定部件，或确认修改所有引用部件。")
    clone = part_id is not None and len(referencing) > 1
    if clone and deck.material_addons:
        raise ValueError("模型包含材料附加卡，首版无法核验复制材料卡会影响哪些定义。")
    affected = [part_id] if part_id is not None else referencing
    return {
        "field": "E",
        "material_id": material_id,
        "material": material.location(),
        "old_value": _old_modulus(material),
        "new_value": new_value,
        "operation": "clone_and_rebind" if clone else "edit_material",
        "referencing_part_ids": referencing,
        "affected_part_ids": affected,
        "part_references": [{"part_id": pid, **deck.parts[pid][1].location()} for pid in affected],
    }
