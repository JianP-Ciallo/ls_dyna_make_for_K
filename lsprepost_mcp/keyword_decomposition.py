"""Streaming LS-DYNA keyword-deck decomposition primitives."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any

from .phase18_reference_naming import (
    LEGACY_SOURCE_FILENAME,
    MATERIAL_DISPLAY_NAMES,
    MATERIAL_RESOURCE_ALIASES,
    MODEL_DISPLAY_NAMES,
    MODEL_RESOURCE_ALIASES,
    REFERENCE_DISPLAY_NAME_EN,
    REFERENCE_FAMILY_ID,
    STRUCTURAL_DISPLAY_NAMES,
    STRUCTURAL_RESOURCE_ALIASES,
    aliases_for,
)


_MESH_CARDS = {"*NODE", "*ELEMENT_SOLID", "*ELEMENT_BEAM"}
_SUPPORTED_KEYWORDS = {
    "*KEYWORD", "*END", "*NODE", "*ELEMENT_SOLID", "*ELEMENT_BEAM", "*PART",
    "*SECTION_SOLID", "*SECTION_SOLID_TITLE", "*SECTION_BEAM", "*SECTION_BEAM_TITLE",
    "*MAT_CONCRETE_DAMAGE_REL3", "*MAT_CONCRETE_DAMAGE_REL3_TITLE", "*MAT_ADD_EROSION",
    "*MAT_PLASTIC_KINEMATIC", "*MAT_PLASTIC_KINEMATIC_TITLE",
    "*EOS_LINEAR_POLYNOMIAL", "*EOS_LINEAR_POLYNOMIAL_TITLE",
    "*DEFINE_CURVE", "*DEFINE_CURVE_TITLE",
    "*CONSTRAINED_LAGRANGE_IN_SOLID", "*CONSTRAINED_LAGRANGE_IN_SOLID_TITLE",
    "*SET_NODE_LIST", "*SET_NODE_LIST_TITLE", "*SET_PART_LIST", "*SET_PART_LIST_TITLE",
    "*SET_SEGMENT", "*SET_SEGMENT_TITLE",
}


_2K_SOURCE_SHA256 = "c1c02a9e832852854b47cd3720bc9348cf48989484d25e1a54036836d0697a22"
_2K_CONVERSIONS = {
    ("density", "tonne/mm^3"): ("kg/m^3", 1e12),
    ("stress", "MPa"): ("Pa", 1e6),
    ("energy_density", "MPa"): ("J/m^3", 1e6),
    ("velocity", "mm/s"): ("m/s", 1e-3),
    ("length", "mm"): ("m", 1e-3),
    ("acceleration", "mm/s^2"): ("m/s^2", 1e-3),
    ("time", "s"): ("s", 1.0),
    ("rate", "1/s"): ("1/s", 1.0),
    ("dimensionless", "1"): ("1", 1.0),
    ("solver_sentinel", "solver_semantic"): ("solver_semantic", 1.0),
}
_2K_PART_SPANS = {
    201: (2366, 2373), 202: (2402, 2409), 203: (2425, 2432), 301: (2448, 2455),
    302: (2456, 2463), 303: (2479, 2486), 401: (2487, 2494), 402: (2495, 2502),
    501: (2503, 2510), 502: (2511, 2518), 1001: (2527, 2534), 1002: (2553, 2560),
}


def _keyword_token(line: str) -> str:
    return re.sub(r"\s*\([^)]*\)", "", line.strip().upper()).split()[0]


def _numbers(line: str, layout: tuple[int, ...] | None = None) -> list[str]:
    """Return position-preserving comma fields or declared fixed-column fields."""
    stripped = line.strip()
    if not stripped or stripped.startswith("$"):
        return []
    if "," in stripped:
        return [item.strip() for item in stripped.split(",")]
    if not layout:
        return stripped.split()
    if len(line) < layout[0]:
        return stripped.split()
    fields = []
    offset = 0
    for width in layout:
        fields.append(line[offset: offset + width].strip())
        offset += width
    return fields or stripped.split()


def _integer(value: str) -> int:
    return int(float(value.replace("D", "E").replace("d", "e")))


def _float(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "e"))


def _is_numeric_row(fields: list[str]) -> bool:
    if not fields:
        return False
    try:
        _integer(fields[0])
    except ValueError:
        return False
    return True


def _semantic_rows(block: dict[str, Any], layout: tuple[int, ...]) -> list[tuple[int, list[str]]]:
    rows = []
    title_pending = block["keyword"].endswith("_TITLE")
    for line_number, text in block["data"]:
        if title_pending and text.strip() and not text.lstrip().startswith("$"):
            title_pending = False
            continue
        if text.strip() and not text.lstrip().startswith("$"):
            rows.append((line_number, _numbers(text, layout)))
    return rows


def _warn(warnings: list[dict[str, Any]], line: int, message: str) -> None:
    warnings.append({"line": line, "message": message})


def _safe_integer(value: str | None, line: int, context: str, warnings: list[dict[str, Any]]) -> int | None:
    try:
        if value is None or value == "":
            raise ValueError
        return _integer(value)
    except ValueError:
        _warn(warnings, line, f"invalid {context}")
        return None


def _required_integers(
    fields: list[str], count: int, line: int, context: str, warnings: list[dict[str, Any]]
) -> list[int] | None:
    if len(fields) < count:
        _warn(warnings, line, f"incomplete {context}")
        return None
    values = [_safe_integer(fields[index], line, context, warnings) for index in range(count)]
    return values if all(value is not None for value in values) else None


def _coordinate_key(coordinates: tuple[float, float, float]) -> bytes:
    return struct.pack("<ddd", *(0.0 if value == 0.0 else value for value in coordinates))


def normalize_2k_resource(candidate: dict[str, object]) -> dict[str, object]:
    """Return a source-faithful 2.k candidate with explicit SI conversions.

    This intentionally accepts only the audited quantity/unit pairs.  Solver
    sentinels retain their solver semantics instead of being treated as values
    in a physical dimension.
    """
    normalized = dict(candidate)
    normalized_fields: dict[str, dict[str, object]] = {}
    fields = candidate.get("fields", [])
    if not isinstance(fields, list):
        raise ValueError("2.k resource fields must be a list")
    for field in fields:
        if not isinstance(field, dict):
            raise ValueError("2.k resource field must be a mapping")
        try:
            name = field["name"]
            value = field["value"]
            quantity = field["quantity"]
            source_unit = field["source_unit"]
        except KeyError as exc:
            raise ValueError(f"2.k resource field is missing {exc.args[0]}") from exc
        if not isinstance(name, str) or not isinstance(quantity, str) or not isinstance(source_unit, str):
            raise ValueError("2.k resource fields need string name, quantity, and source_unit")
        try:
            target_unit, factor = _2K_CONVERSIONS[(quantity, source_unit)]
        except KeyError as exc:
            raise ValueError(f"unsupported 2.k quantity/unit pair: {quantity} / {source_unit}") from exc
        if not isinstance(value, (int, float)):
            raise ValueError(f"2.k resource field {name} must have a numeric value")
        normalized_fields[name] = {
            "original_value": value,
            "original_unit": source_unit,
            "factor": factor,
            "value": float(Decimal(str(value)) * Decimal(str(factor))),
            "unit": target_unit,
            "conversion_kind": (
                "solver_semantic_passthrough"
                if quantity == "solver_sentinel"
                else "explicit_unit_conversion"
            ),
        }
    normalized["normalized_fields"] = normalized_fields
    return normalized


def _2k_raw_block_index(report: dict[str, object]) -> dict[tuple[str, int], dict[str, object]]:
    blocks = report.get("raw_keyword_blocks", [])
    if not isinstance(blocks, list):
        return {}
    return {
        (str(block.get("normalized_keyword", block.get("keyword", ""))), int(block["source_line_start"])): block
        for block in blocks
        if isinstance(block, dict) and isinstance(block.get("source_line_start"), int)
    }


def _2k_resource_record(
    source_sha256: str,
    resource_kind: str,
    source_id: int | None,
    keyword: str | None,
    source_line_start: int | None,
    source_line_end: int | None,
    usage: str,
    raw_block: dict[str, object] | None,
    **extra: object,
) -> dict[str, object]:
    return {
        "resource_kind": resource_kind,
        "source_id": source_id,
        "keyword": keyword,
        "source_line_start": source_line_start,
        "source_line_end": source_line_end,
        "usage": usage,
        "validation_status": "source_reference",
        "requires_project_review": True,
        "source_sha256": source_sha256,
        "raw_block": raw_block,
        **extra,
    }


def classify_resources(report: dict[str, object]) -> dict[str, list[dict[str, object]]]:
    """Classify only the independently audited 2.k source report."""
    source = report.get("source")
    if not isinstance(source, dict) or source.get("sha256") != _2K_SOURCE_SHA256:
        raise ValueError("resource classification is restricted to the audited 2.k source SHA-256")
    source_sha256 = _2K_SOURCE_SHA256
    raw_index = _2k_raw_block_index(report)

    def raw_for(record: dict[str, object]) -> dict[str, object] | None:
        keyword = record.get("keyword")
        start = record.get("source_line_start")
        if not isinstance(keyword, str) or not isinstance(start, int):
            return None
        return raw_index.get((keyword, start))

    inventory: dict[str, list[dict[str, object]]] = {
        "used": [], "dependency": [], "unused": [], "unsupported": [], "blockers": [],
    }
    used_ids = {
        "parts": {201, 202, 203, 301, 302, 303, 401, 402, 501, 502, 1001, 1002},
        "sections": {1, 2, 3, 4, 5, 6},
        "materials": {2, 3, 5, 8, 12, 14},
        "eos": {1, 2},
        "curves": {1, 2},
    }
    unused_ids = {
        "sections": {7, 8},
        "materials": {9, 10, 11, 13},
    }
    kind_names = {"parts": "part", "sections": "section", "materials": "material", "eos": "eos", "curves": "curve"}
    for report_key, resource_kind in kind_names.items():
        records = report.get(report_key, [])
        if not isinstance(records, list):
            continue
        for record in records:
            identity_key = "pid" if report_key == "parts" else "id"
            if not isinstance(record, dict) or not isinstance(record.get(identity_key), int):
                continue
            source_id = record[identity_key]
            if source_id not in used_ids.get(report_key, set()) and source_id not in unused_ids.get(report_key, set()):
                continue
            usage = "used" if source_id in used_ids.get(report_key, set()) else "unused"
            if report_key == "parts":
                source_keyword = "*PART"
                source_start, source_end = _2K_PART_SPANS[source_id]
                source_raw = raw_index.get((source_keyword, source_start))
            else:
                source_keyword = str(record.get("keyword", ""))
                source_start = record.get("source_line_start") if isinstance(record.get("source_line_start"), int) else None
                source_end = record.get("source_line_end") if isinstance(record.get("source_line_end"), int) else None
                source_raw = raw_for(record)
            inventory[usage].append(_2k_resource_record(
                source_sha256, resource_kind, source_id, source_keyword, source_start, source_end, usage, source_raw,
            ))

    sets = report.get("sets", [])
    if isinstance(sets, list):
        for record in sets:
            if not isinstance(record, dict) or not isinstance(record.get("id"), int):
                continue
            keyword = str(record.get("keyword", ""))
            source_id = record["id"]
            usage = "unused" if keyword.startswith("*SET_PART") and source_id in {5, 7, 8} else "used"
            inventory[usage].append(_2k_resource_record(
                source_sha256, "set", source_id, keyword,
                record.get("source_line_start") if isinstance(record.get("source_line_start"), int) else None,
                record.get("source_line_end") if isinstance(record.get("source_line_end"), int) else None,
                usage, raw_for(record),
            ))

    coupling_blocks = [
        block for (keyword, _), block in raw_index.items()
        if keyword.startswith("*CONSTRAINED_LAGRANGE_IN_SOLID")
    ]
    coupling_blocks.sort(key=lambda block: int(block["source_line_start"]))
    couplings = report.get("constrained_couplings", [])
    if isinstance(couplings, list):
        for index, coupling in enumerate(couplings):
            if not isinstance(coupling, dict):
                continue
            raw_block = coupling_blocks[index] if index < len(coupling_blocks) else None
            inventory["used"].append(_2k_resource_record(
                source_sha256, "coupling", None,
                str(raw_block.get("normalized_keyword")) if raw_block else "*CONSTRAINED_LAGRANGE_IN_SOLID",
                raw_block.get("source_line_start") if raw_block else None,
                raw_block.get("source_line_end") if raw_block else None,
                "used", raw_block, coupling=coupling,
            ))

    dependency_keywords = {
        "*MAT_ADD_EROSION", "*INITIAL_DETONATION", "*LOAD_BODY_PARTS", "*LOAD_BODY_Z",
        "*ALE_MULTI-MATERIAL_GROUP", "*BOUNDARY_SPC_SET", "*BOUNDARY_NON_REFLECTING",
    }
    dependency_ids = {
        "*MAT_ADD_EROSION": 5, "*INITIAL_DETONATION": 1002, "*LOAD_BODY_PARTS": 4,
        "*LOAD_BODY_Z": 2, "*BOUNDARY_SPC_SET": 1, "*BOUNDARY_NON_REFLECTING": 1,
    }
    for (keyword, _), raw_block in sorted(raw_index.items(), key=lambda item: item[0][1]):
        if keyword not in dependency_keywords:
            continue
        start = raw_block.get("source_line_start") if isinstance(raw_block.get("source_line_start"), int) else None
        end = raw_block.get("source_line_end") if isinstance(raw_block.get("source_line_end"), int) else None
        if keyword == "*ALE_MULTI-MATERIAL_GROUP":
            for offset, line in enumerate(raw_block.get("raw_lines", []), start=1):
                if not isinstance(line, str):
                    continue
                fields = _numbers(line, (10,) * 8)
                try:
                    source_id = _integer(fields[0])
                except (IndexError, ValueError):
                    continue
                if source_id in {1001, 1002}:
                    inventory["dependency"].append(_2k_resource_record(
                        source_sha256, "ale_group", source_id, keyword,
                        start + offset if start is not None else None, start + offset if start is not None else None,
                        "dependency", raw_block,
                    ))
            continue
        inventory["dependency"].append(_2k_resource_record(
            source_sha256, "dependency", dependency_ids[keyword], keyword, start, end, "dependency", raw_block,
        ))

    unsupported = report.get("unsupported_used_cards", [])
    if isinstance(unsupported, list):
        for record in unsupported:
            if not isinstance(record, dict):
                continue
            keyword = record.get("keyword")
            start = record.get("source_line_start")
            if not isinstance(keyword, str) or not isinstance(start, int):
                continue
            raw_block = raw_index.get((keyword, start))
            inventory["unsupported"].append(_2k_resource_record(
                source_sha256, "unsupported", None, keyword, start,
                raw_block.get("source_line_end") if raw_block else None,
                "unsupported", raw_block,
            ))

    for code in (
        "KC_RATE_CURVE_REQUIRES_REVIEW",
        "MID8_SHARED_ACROSS_D8_D18",
        "OVERLAPPING_EMBEDDED_COUPLINGS",
        "SOLVER_SENTINELS_REQUIRE_FIELD_AWARE_HANDLING",
        "NO_SOLVER_OR_EXPERIMENTAL_VALIDATION",
    ):
        inventory["blockers"].append(_2k_resource_record(
            source_sha256, "blocker", None, None, None, None, "blocker", None, code=code,
        ))
    return inventory


def decompose_keyword_deck(path: Path, source_units: str) -> dict[str, object]:
    """Stream a keyword deck into a JSON-serializable decomposition report."""
    digest = hashlib.sha256()
    byte_size = line_count = 0
    keyword_counts: Counter[str] = Counter()
    node_record_count = 0
    node_ids: set[int] = set()
    duplicate_node_ids: set[int] = set()
    coordinate_groups: dict[bytes, int | list[int]] = {}
    element_counts: Counter[str] = Counter()
    element_counts_by_pid: Counter[int] = Counter()
    element_ids: set[int] = set()
    duplicate_element_ids: set[int] = set()
    topology_references: set[int] = set()
    orientation_references: set[int] = set()
    blocks: list[dict[str, Any]] = []
    raw_blocks: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
    pending_solid: tuple[int, int, int] | None = None

    def add_element(element_id: int, pid: int, element_type: str) -> None:
        if element_id in element_ids:
            duplicate_element_ids.add(element_id)
        element_ids.add(element_id)
        element_counts[element_type] += 1
        element_counts_by_pid[pid] += 1

    def finish_active(end_line: int) -> None:
        nonlocal active, pending_solid
        if active is None:
            return
        active["source_line_end"] = end_line
        if active["keyword"] not in _MESH_CARDS:
            blocks.append(active)
            raw_blocks.append({
                "normalized_keyword": active["keyword"],
                "keyword": active["keyword"],
                "raw_keyword_line": active["raw_keyword_line"],
                "source_line_start": active["source_line_start"],
                "source_line_end": end_line,
                "raw_lines": [text for _, text in active["data"]],
            })
        if pending_solid is not None:
            _warn(warnings, pending_solid[2], "incomplete solid connectivity")
            pending_solid = None
        active = None

    with path.open("rb") as handle:
        for line_number, byte_line in enumerate(handle, start=1):
            digest.update(byte_line)
            byte_size += len(byte_line)
            line_count = line_number
            line = byte_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if line.lstrip().startswith("*"):
                finish_active(line_number - 1)
                keyword = _keyword_token(line)
                keyword_counts[keyword] += 1
                active = {"keyword": keyword, "raw_keyword_line": line, "source_line_start": line_number, "data": []}
                continue
            if active is None:
                continue
            keyword = active["keyword"]
            if not line.strip() or line.lstrip().startswith("$"):
                if keyword not in _MESH_CARDS:
                    active["data"].append((line_number, line))
                continue
            if keyword == "*NODE":
                fields = _numbers(line, (8, 16, 16, 16))
                if len(fields) < 4:
                    _warn(warnings, line_number, "invalid node record")
                    continue
                try:
                    node_id = _integer(fields[0])
                    coordinates = (_float(fields[1]), _float(fields[2]), _float(fields[3]))
                except ValueError:
                    _warn(warnings, line_number, "invalid node record")
                    continue
                node_record_count += 1
                if node_id in node_ids:
                    duplicate_node_ids.add(node_id)
                node_ids.add(node_id)
                key = _coordinate_key(coordinates)
                existing = coordinate_groups.get(key)
                if existing is None:
                    coordinate_groups[key] = node_id
                elif isinstance(existing, list):
                    existing.append(node_id)
                else:
                    coordinate_groups[key] = [existing, node_id]
            elif keyword == "*ELEMENT_SOLID":
                if pending_solid is None:
                    fields = _numbers(line, (8, 8))
                    values = _required_integers(fields, 2, line_number, "solid element header", warnings)
                    if values is not None:
                        pending_solid = (values[0], values[1], line_number)
                else:
                    fields = _numbers(line, (8,) * 10)
                    values = _required_integers(fields, 10, line_number, "solid connectivity", warnings)
                    if values is not None:
                        nonzero = [value for value in values if value != 0]
                        if len(nonzero) < 8:
                            _warn(warnings, line_number, "solid element has fewer than eight topology nodes")
                        add_element(pending_solid[0], pending_solid[1], "solid")
                        topology_references.update(nonzero)
                    pending_solid = None
            elif keyword == "*ELEMENT_BEAM":
                fields = _numbers(line, (8,) * 5)
                values = _required_integers(fields, 5, line_number, "beam element", warnings)
                if values is not None:
                    add_element(values[0], values[1], "beam")
                    topology_references.update(values[2:4])
                    if values[4] != 0:
                        orientation_references.add(values[4])
            else:
                active["data"].append((line_number, line))
        finish_active(line_count)

    parts: list[dict[str, object]] = []
    sections: list[dict[str, object]] = []
    materials: list[dict[str, object]] = []
    eos: list[dict[str, object]] = []
    curves: list[dict[str, object]] = []
    sets: list[dict[str, object]] = []
    erosion_mids: set[int] = set()
    concrete_lcrates: dict[int, list[int]] = {}
    constrained: list[dict[str, int]] = []
    for block in blocks:
        keyword = block["keyword"]
        span = {"source_line_start": block["source_line_start"], "source_line_end": block["source_line_end"]}
        if keyword == "*PART":
            layout = (10,) * 8
            rows = _semantic_rows(block, layout)
            title = next(
                (text.strip() for _, text in block["data"] if text.strip() and not text.lstrip().startswith("$") and not _is_numeric_row(_numbers(text, layout))),
                "",
            )
            numeric_rows = [(line, fields) for line, fields in rows if _is_numeric_row(fields)]
            if not numeric_rows:
                continue
            line, fields = numeric_rows[0]
            values = _required_integers(fields, 3, line, "part fields", warnings)
            if values is not None:
                eosid = _safe_integer(fields[3], line, "part eosid", warnings) if len(fields) > 3 and fields[3] else 0
                if eosid is not None:
                    parts.append({"title": title, "pid": values[0], "secid": values[1], "mid": values[2], "eosid": eosid})
        elif keyword.startswith("*SECTION_"):
            rows = _semantic_rows(block, (10,) * 8)
            if rows:
                line, fields = rows[0]
                card_id = _safe_integer(fields[0] if fields else None, line, "section id", warnings)
                if card_id is not None:
                    sections.append({"id": card_id, "keyword": keyword, **span})
        elif keyword.startswith("*MAT_") and keyword != "*MAT_ADD_EROSION":
            rows = _semantic_rows(block, (10,) * 10)
            if rows:
                line, fields = rows[0]
                card_id = _safe_integer(fields[0] if fields else None, line, "material id", warnings)
                if card_id is not None:
                    materials.append({"id": card_id, "keyword": keyword, **span})
                    if keyword.startswith("*MAT_CONCRETE_DAMAGE_REL3") and len(rows) >= 3:
                        lcrate_line, lcrate_fields = rows[2]
                        if len(lcrate_fields) < 6:
                            _warn(warnings, lcrate_line, "incomplete concrete lcrate")
                        else:
                            lcrate = _safe_integer(lcrate_fields[5], lcrate_line, "concrete lcrate", warnings)
                            if lcrate is not None:
                                concrete_lcrates[card_id] = [] if lcrate == 0 else [lcrate]
        elif keyword == "*MAT_ADD_EROSION":
            rows = _semantic_rows(block, (10,) * 8)
            if rows:
                line, fields = rows[0]
                mid = _safe_integer(fields[0] if fields else None, line, "erosion material id", warnings)
                if mid is not None:
                    erosion_mids.add(mid)
        elif keyword.startswith("*EOS_"):
            rows = _semantic_rows(block, (10,) * 8)
            if rows:
                line, fields = rows[0]
                card_id = _safe_integer(fields[0] if fields else None, line, "eos id", warnings)
                if card_id is not None:
                    eos.append({"id": card_id, "keyword": keyword, **span})
        elif keyword.startswith("*DEFINE_CURVE"):
            rows = _semantic_rows(block, (10,) * 8)
            if rows:
                line, fields = rows[0]
                card_id = _safe_integer(fields[0] if fields else None, line, "curve id", warnings)
                if card_id is not None:
                    points: list[list[float]] = []
                    for _point_line, text in block["data"]:
                        point_fields = _numbers(text)
                        if len(point_fields) != 2:
                            continue
                        try:
                            points.append([_float(point_fields[0]), _float(point_fields[1])])
                        except ValueError:
                            continue
                    curves.append({"id": card_id, "keyword": keyword, **span, "points": points})
        elif keyword.startswith("*SET_"):
            rows = _semantic_rows(block, (10,) * 8)
            if rows:
                line, fields = rows[0]
                card_id = _safe_integer(fields[0] if fields else None, line, "set id", warnings)
                if card_id is not None:
                    member_rows = [
                        [_integer(value) for value in member_fields if value]
                        for _, member_fields in rows[1:]
                        if _is_numeric_row(member_fields)
                    ]
                    sets.append({
                        "id": card_id,
                        "keyword": keyword,
                        **span,
                        "member_record_count": len(member_rows),
                        "member_rows": member_rows,
                    })
        elif keyword.startswith("*CONSTRAINED_LAGRANGE_IN_SOLID"):
            rows = _semantic_rows(block, (10,) * 8)
            if rows:
                line, fields = rows[0]
                values = _required_integers(fields, 4, line, "constrained lagrange main row", warnings)
                if values is not None:
                    constrained.append({"ssid": values[0], "msid": values[1], "sstyp": values[2], "mstyp": values[3]})

    missing = sorted((topology_references | orientation_references) - node_ids)
    for node_id in missing:
        warnings.append({"message": "element references missing node", "node_id": node_id})
    duplicate_groups = []
    for group in coordinate_groups.values():
        if not isinstance(group, list):
            continue
        roles = []
        has_orientation = False
        has_topology = False
        has_orphan = False
        for node_id in sorted(group):
            node_roles = []
            if node_id in topology_references:
                node_roles.append("topology")
                has_topology = True
            if node_id in orientation_references:
                node_roles.append("beam_orientation")
                has_orientation = True
            if not node_roles:
                node_roles.append("orphan")
                has_orphan = True
            roles.append({"node_id": node_id, "roles": node_roles})
        if has_orientation and not has_topology and not has_orphan:
            classification = "beam_orientation_only"
        elif has_orientation and has_topology:
            classification = "mixed_beam_orientation_and_topology"
        elif has_orientation:
            classification = "mixed_beam_orientation_and_orphan"
        elif has_topology:
            classification = "topology_duplicate"
        else:
            classification = "orphan_coordinate_duplicate"
        duplicate_groups.append({"node_ids": sorted(group), "classification": classification, "node_roles": roles})

    dependencies = {
        str(material["id"]): {
            "mid": material["id"],
            "curve_ids": concrete_lcrates.get(material["id"], []),
            "add_erosion": material["id"] in erosion_mids,
        }
        for material in materials
    }
    unsupported = [
        {"keyword": block["keyword"], "source_line_start": block["source_line_start"]}
        for block in blocks if block["keyword"] not in _SUPPORTED_KEYWORDS
    ]
    return {
        "source": {"path": str(path), "units": source_units, "sha256": digest.hexdigest(), "byte_size": byte_size, "line_count": line_count},
        "keyword_counts": dict(sorted(keyword_counts.items())),
        "mesh": {
            "node_record_count": node_record_count,
            "unique_node_id_count": len(node_ids),
            "duplicate_node_ids": sorted(duplicate_node_ids),
            "element_count_by_type": dict(sorted(element_counts.items())),
            "element_count_by_pid": {str(key): value for key, value in sorted(element_counts_by_pid.items())},
            "unique_element_id_count": len(element_ids),
            "duplicate_element_ids": sorted(duplicate_element_ids),
            "exact_coordinate_duplicate_groups": sorted(duplicate_groups, key=lambda item: item["node_ids"]),
            "orphan_node_ids": sorted(node_ids - topology_references - orientation_references),
            "missing_node_references": missing,
        },
        "parts": parts, "sections": sections, "materials": materials, "eos": eos, "curves": curves, "sets": sets,
        "material_dependencies": dependencies, "constrained_couplings": constrained, "parse_warnings": warnings,
        "unsupported_used_cards": unsupported, "raw_keyword_blocks": raw_blocks,
    }


def _2k_material_assets() -> list[dict[str, object]]:
    common = {
        "schema_version": "0.2.0",
        "unit_system": "SI_m_s_kg_N_Pa",
        "validation_status": "source_reference",
        "requires_project_review": True,
        "version": "2026.08.03",
        "source": "Audited extraction from the Two-Storey Reinforced Concrete Frame Blast Reference Model; values are source-faithful references, not solver or experimental validation.",
        "provenance": {
            "source_name": LEGACY_SOURCE_FILENAME,
            "source_display_name": REFERENCE_DISPLAY_NAME_EN,
            "source_sha256": _2K_SOURCE_SHA256,
            "source_unit_system": "tonne_mm_s_N_MPa",
        },
    }

    def asset(**values: object) -> dict[str, object]:
        return {**common, **values}

    steel = {
        "category": "rebar_steel",
        "type": "plastic_kinematic",
        "density_kg_per_m3": 7850.0,
        "youngs_pa": 210000000000.0,
        "poisson": 0.3,
        "tangent_modulus_pa": 2100000000.0,
        "parameters_si": {"beta": 0.0, "src_per_s": 6844.0, "srp": 3.91, "vp": 0.0},
    }
    return [
        asset(
            id=MATERIAL_RESOURCE_ALIASES["2k_mid5_concrete_kc"], name=MATERIAL_RESOURCE_ALIASES["2k_mid5_concrete_kc"],
            aliases=["2k_mid5_concrete_kc"], display_name=MATERIAL_DISPLAY_NAMES[MATERIAL_RESOURCE_ALIASES["2k_mid5_concrete_kc"]],
            category="concrete", type="concrete_damage_rel3", density_kg_per_m3=2400.0, poisson=0.2,
            parameters_si={"a0_pa": -30400000.0, "a1": 0.0, "a2": 0.0, "b1": 2.0, "b2": 1.5, "omega": 0.0},
            solver_semantics={
                "ft": {
                    "source_value": 0.0,
                    "source_unit": "MPa",
                    "meaning": "K&C automatic/default sentinel retained from source; it is not a physical zero tensile strength.",
                }
            },
            solver_unit_conversion={
                "rsize_in_per_user_length_unit": 0.03937,
                "ucf_psi_per_user_stress_unit": 145.0,
                "semantics": "K&C solver conversion factors retained from the source unit system; these are not SI material properties.",
            },
            dependencies={"rate_curve": {"lcid": 1, "point_count": 23}, "mat_add_erosion": {"mid": 5, "mxeps": 0.15}},
            source_cards=[
                {"keyword": "*MAT_CONCRETE_DAMAGE_REL3_TITLE", "source_id": 5, "line_start": 2379, "line_end": 2401},
                {"keyword": "*MAT_ADD_EROSION", "source_id": 5, "line_start": 2587, "line_end": 2597},
                {"keyword": "*DEFINE_CURVE", "source_id": 1, "line_start": 2642, "line_end": 2673},
            ],
        ),
        asset(**{
            **steel, "id": MATERIAL_RESOURCE_ALIASES["2k_mid8_rebar_d8_d18"], "name": MATERIAL_RESOURCE_ALIASES["2k_mid8_rebar_d8_d18"],
            "aliases": ["2k_mid8_rebar_d8_d18"], "display_name": MATERIAL_DISPLAY_NAMES[MATERIAL_RESOURCE_ALIASES["2k_mid8_rebar_d8_d18"]],
            "yield_strength_pa": 455000000.0, "section_diameters_mm": [8.0, 18.0],
            "parameters_si": {**steel["parameters_si"], "failure_strain": 0.15},
            "source_cards": [
                {"keyword": "*MAT_PLASTIC_KINEMATIC_TITLE", "source_id": 8, "line_start": 2441, "line_end": 2447},
                {"keyword": "*SECTION_BEAM_TITLE", "source_id": 1, "line_start": 2433, "line_end": 2440},
                {"keyword": "*SECTION_BEAM_TITLE", "source_id": 6, "line_start": 2519, "line_end": 2526},
            ],
        }),
        asset(**{
            **steel, "id": MATERIAL_RESOURCE_ALIASES["2k_mid12_rebar_d12"], "name": MATERIAL_RESOURCE_ALIASES["2k_mid12_rebar_d12"],
            "aliases": ["2k_mid12_rebar_d12"], "display_name": MATERIAL_DISPLAY_NAMES[MATERIAL_RESOURCE_ALIASES["2k_mid12_rebar_d12"]],
            "yield_strength_pa": 460000000.0, "section_diameters_mm": [12.0],
            "parameters_si": {**steel["parameters_si"], "failure_strain": 0.14},
            "source_cards": [
                {"keyword": "*MAT_PLASTIC_KINEMATIC_TITLE", "source_id": 12, "line_start": 2472, "line_end": 2478},
                {"keyword": "*SECTION_BEAM_TITLE", "source_id": 2, "line_start": 2464, "line_end": 2471},
            ],
        }),
        asset(**{
            **steel, "id": MATERIAL_RESOURCE_ALIASES["2k_mid14_rebar_d20"], "name": MATERIAL_RESOURCE_ALIASES["2k_mid14_rebar_d20"],
            "aliases": ["2k_mid14_rebar_d20"], "display_name": MATERIAL_DISPLAY_NAMES[MATERIAL_RESOURCE_ALIASES["2k_mid14_rebar_d20"]],
            "yield_strength_pa": 445000000.0, "section_diameters_mm": [20.0],
            "parameters_si": {**steel["parameters_si"], "failure_strain": 0.14},
            "source_cards": [
                {"keyword": "*MAT_PLASTIC_KINEMATIC_TITLE", "source_id": 14, "line_start": 2418, "line_end": 2424},
                {"keyword": "*SECTION_BEAM_TITLE", "source_id": 3, "line_start": 2410, "line_end": 2417},
            ],
        }),
        asset(
            id=MATERIAL_RESOURCE_ALIASES["2k_mid2_air_eos2"], name=MATERIAL_RESOURCE_ALIASES["2k_mid2_air_eos2"],
            aliases=["2k_mid2_air_eos2"], display_name=MATERIAL_DISPLAY_NAMES[MATERIAL_RESOURCE_ALIASES["2k_mid2_air_eos2"]],
            category="gas", type="mat_null_eos_linear_polynomial", density_kg_per_m3=1.22,
            parameters_si={"pressure_cutoff_pa": 0.0, "dynamic_viscosity_pa_s": 0.0},
            eos_si={"eos_id": 2, "c0_pa": 0.0, "c1_pa": 0.0, "c2_pa": 0.0, "c3_pa": 0.0, "c4": 0.4, "c5": 0.4, "c6": 0.0, "e0_j_per_m3": 250000.0, "v0_solver_semantic": 0.0},
            source_cards=[
                {"keyword": "*MAT_NULL_TITLE", "source_id": 2, "line_start": 2540, "line_end": 2544},
                {"keyword": "*EOS_LINEAR_POLYNOMIAL_TITLE", "source_id": 2, "line_start": 2545, "line_end": 2552},
            ],
        ),
        asset(
            id=MATERIAL_RESOURCE_ALIASES["2k_mid3_tnt_eos1"], name=MATERIAL_RESOURCE_ALIASES["2k_mid3_tnt_eos1"],
            aliases=["2k_mid3_tnt_eos1"], display_name=MATERIAL_DISPLAY_NAMES[MATERIAL_RESOURCE_ALIASES["2k_mid3_tnt_eos1"]],
            category="high_explosive", type="high_explosive_burn_eos_jwl", density_kg_per_m3=1550.0,
            parameters_si={"detonation_velocity_m_per_s": 8193.0, "cj_pressure_pa": 28000000000.0, "beta": 0.0},
            eos_si={"eos_id": 1, "a_pa": 640000000000.0, "b_pa": 13900000000.0, "r1": 4.5, "r2": 1.4, "omega": 0.25, "e0_j_per_m3": 8700000000.0, "v0": 1.0},
            dependencies={"initial_detonation": {"pid": 1002, "xyz_m": [3.314, 3.295, -0.2674], "time_s": 0.0}},
            source_cards=[
                {"keyword": "*MAT_HIGH_EXPLOSIVE_BURN_TITLE", "source_id": 3, "line_start": 2561, "line_end": 2565},
                {"keyword": "*EOS_JWL_TITLE", "source_id": 1, "line_start": 2566, "line_end": 2570},
                {"keyword": "*INITIAL_DETONATION", "source_id": 1002, "line_start": 2636, "line_end": 2641},
            ],
        ),
    ]


_MID_TO_RESOURCE = {
    2: MATERIAL_RESOURCE_ALIASES["2k_mid2_air_eos2"],
    3: MATERIAL_RESOURCE_ALIASES["2k_mid3_tnt_eos1"],
    5: MATERIAL_RESOURCE_ALIASES["2k_mid5_concrete_kc"],
    8: MATERIAL_RESOURCE_ALIASES["2k_mid8_rebar_d8_d18"],
    12: MATERIAL_RESOURCE_ALIASES["2k_mid12_rebar_d12"],
    14: MATERIAL_RESOURCE_ALIASES["2k_mid14_rebar_d20"],
}


def _2k_structural_assets(report: dict[str, object]) -> list[dict[str, object]]:
    source = report.get("source")
    if not isinstance(source, dict) or source.get("sha256") != _2K_SOURCE_SHA256:
        raise ValueError("structural extraction is restricted to the audited 2.k source SHA-256")

    common = {
        "schema_version": "0.1.0",
        "unit_system": "SI_m_s_kg_N_Pa",
        "validation_status": "source_reference",
        "requires_project_review": True,
        "version": "2026.08.05",
        "source": "Audited structural relationship extraction from the Two-Storey Reinforced Concrete Frame Blast Reference Model; not solver or engineering validation.",
        "provenance": {
            "source_name": LEGACY_SOURCE_FILENAME,
            "source_display_name": REFERENCE_DISPLAY_NAME_EN,
            "source_sha256": _2K_SOURCE_SHA256,
            "source_unit_system": "tonne_mm_s_N_MPa",
        },
    }

    section_records = {
        int(record["id"]): record
        for record in report.get("sections", [])
        if isinstance(record, dict) and int(record.get("id", -1)) in {1, 2, 3, 4, 5, 6}
    }
    section_properties: dict[int, dict[str, object]] = {
        1: {"source_diameter_mm": 8.0, "diameter_m": 0.008},
        2: {"source_diameter_mm": 12.0, "diameter_m": 0.012},
        3: {"source_diameter_mm": 20.0, "diameter_m": 0.020},
        4: {"elform": 1},
        5: {"elform": 11},
        6: {"source_diameter_mm": 18.0, "diameter_m": 0.018},
    }
    sections = []
    for secid in sorted(section_properties):
        record = section_records[secid]
        sections.append({
            "secid": secid,
            "keyword": record["keyword"],
            "source_line_start": record["source_line_start"],
            "source_line_end": record["source_line_end"],
            **section_properties[secid],
        })

    curve_record = next(
        record for record in report.get("curves", [])
        if isinstance(record, dict) and record.get("id") == 1
    )
    curve_points = [list(point) for point in curve_record.get("points", [])]

    element_counts = report.get("mesh", {}).get("element_count_by_pid", {})
    solid_pids = {201, 301, 401, 501, 1001, 1002}
    roles = {
        201: "beam_concrete", 202: "beam_longitudinal_rebar", 203: "beam_stirrup",
        301: "column_concrete", 302: "column_longitudinal_rebar", 303: "column_stirrup",
        401: "slab_concrete", 402: "slab_rebar",
        501: "base_concrete", 502: "base_rebar",
        1001: "air_domain", 1002: "explosive_charge",
    }
    parts = []
    for record in sorted(report.get("parts", []), key=lambda item: int(item["pid"])):
        pid = int(record["pid"])
        if pid not in roles:
            continue
        mid = int(record["mid"])
        start, end = _2K_PART_SPANS[pid]
        parts.append({
            **record,
            "role": roles[pid],
            "element_family": "solid" if pid in solid_pids else "beam",
            "element_count": int(element_counts[str(pid)]),
            "material_resource_id": _MID_TO_RESOURCE[mid],
            "source_line_start": start,
            "source_line_end": end,
        })

    sets = []
    for record in report.get("sets", []):
        if not isinstance(record, dict):
            continue
        keyword = str(record.get("keyword", ""))
        source_id = int(record.get("id", -1))
        if keyword.startswith("*SET_PART") and source_id in {5, 7, 8}:
            continue
        if keyword.startswith("*SET_NODE"):
            set_type = "node"
        elif keyword.startswith("*SET_PART"):
            set_type = "part"
        elif keyword.startswith("*SET_SEGMENT"):
            set_type = "segment"
        else:
            continue
        sets.append({
            "set_type": set_type,
            "source_id": source_id,
            "keyword": keyword,
            "source_line_start": record["source_line_start"],
            "source_line_end": record["source_line_end"],
            "member_record_count": int(record.get("member_record_count", 0)),
            "member_rows": record.get("member_rows", []),
        })
    sets.sort(key=lambda item: (str(item["set_type"]), int(item["source_id"])))

    coupling_blocks = [
        block for block in report.get("raw_keyword_blocks", [])
        if isinstance(block, dict) and str(block.get("normalized_keyword", "")).startswith("*CONSTRAINED_LAGRANGE_IN_SOLID")
    ]
    coupling_blocks.sort(key=lambda block: int(block["source_line_start"]))
    couplings = []
    for index, record in enumerate(report.get("constrained_couplings", []), start=1):
        block = coupling_blocks[index - 1]
        couplings.append({
            "coupling_index": index,
            **record,
            "slave_kind": "set" if int(record["sstyp"]) == 0 else "part",
            "master_kind": "set" if int(record["mstyp"]) == 0 else "part",
            "source_line_start": block["source_line_start"],
            "source_line_end": block["source_line_end"],
        })

    return [
        {
            **common,
            "id": STRUCTURAL_RESOURCE_ALIASES["2k_sections_used"],
            "name": STRUCTURAL_RESOURCE_ALIASES["2k_sections_used"],
            "aliases": ["2k_sections_used"],
            "display_name": STRUCTURAL_DISPLAY_NAMES[STRUCTURAL_RESOURCE_ALIASES["2k_sections_used"]],
            "resource_type": "sections",
            "items": sections,
        },
        {
            **common,
            "id": STRUCTURAL_RESOURCE_ALIASES["2k_curve1_kc_rate"],
            "name": STRUCTURAL_RESOURCE_ALIASES["2k_curve1_kc_rate"],
            "aliases": ["2k_curve1_kc_rate"],
            "display_name": STRUCTURAL_DISPLAY_NAMES[STRUCTURAL_RESOURCE_ALIASES["2k_curve1_kc_rate"]],
            "resource_type": "curve",
            "curve_id": 1,
            "abscissa_unit": "1/s",
            "ordinate_unit": "dimensionless",
            "source_line_start": curve_record["source_line_start"],
            "source_line_end": curve_record["source_line_end"],
            "points": curve_points,
        },
        {
            **common,
            "id": STRUCTURAL_RESOURCE_ALIASES["2k_part_role_map"],
            "name": STRUCTURAL_RESOURCE_ALIASES["2k_part_role_map"],
            "aliases": ["2k_part_role_map"],
            "display_name": STRUCTURAL_DISPLAY_NAMES[STRUCTURAL_RESOURCE_ALIASES["2k_part_role_map"]],
            "resource_type": "part_role_map",
            "items": parts,
        },
        {
            **common,
            "id": STRUCTURAL_RESOURCE_ALIASES["2k_sets_used"],
            "name": STRUCTURAL_RESOURCE_ALIASES["2k_sets_used"],
            "aliases": ["2k_sets_used"],
            "display_name": STRUCTURAL_DISPLAY_NAMES[STRUCTURAL_RESOURCE_ALIASES["2k_sets_used"]],
            "resource_type": "sets",
            "items": sets,
        },
        {
            **common,
            "id": STRUCTURAL_RESOURCE_ALIASES["2k_embedded_couplings"],
            "name": STRUCTURAL_RESOURCE_ALIASES["2k_embedded_couplings"],
            "aliases": ["2k_embedded_couplings"],
            "display_name": STRUCTURAL_DISPLAY_NAMES[STRUCTURAL_RESOURCE_ALIASES["2k_embedded_couplings"]],
            "resource_type": "embedded_couplings",
            "items": couplings,
        },
    ]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_2k_payload(report: dict[str, object], source_path: Path, payload_path: Path) -> dict[str, object]:
    inventory = classify_resources(report)
    selected: dict[tuple[str, int], dict[str, object]] = {}
    for group in ("used", "dependency"):
        for record in inventory[group]:
            raw = record.get("raw_block")
            if not isinstance(raw, dict):
                continue
            keyword = str(raw.get("normalized_keyword", ""))
            start = raw.get("source_line_start")
            if keyword in _MESH_CARDS or not isinstance(start, int):
                continue
            selected[(keyword, start)] = raw

    priority = {
        "*PART": 0, "*SECTION_SOLID_TITLE": 1, "*SECTION_BEAM_TITLE": 1,
        "*MAT_CONCRETE_DAMAGE_REL3_TITLE": 2, "*MAT_PLASTIC_KINEMATIC_TITLE": 2,
        "*MAT_NULL_TITLE": 2, "*MAT_HIGH_EXPLOSIVE_BURN_TITLE": 2, "*MAT_ADD_EROSION": 2,
        "*EOS_LINEAR_POLYNOMIAL_TITLE": 3, "*EOS_JWL_TITLE": 3, "*DEFINE_CURVE": 4,
    }
    ordered = sorted(selected.values(), key=lambda block: (priority.get(str(block.get("normalized_keyword")), 5), int(block["source_line_start"])))
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    with payload_path.open("wb") as raw_output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_output, mtime=0) as zipped:
            def emit(text: str) -> None:
                zipped.write((text + "\n").encode("utf-8"))

            emit("*KEYWORD")
            emit("$ Source-faithful reusable resource: Two-Storey RC Frame Blast Reference")
            emit("$ Original source filename retained in provenance: 2.k")
            emit("$ Control/output cards and audit-only unused cards are intentionally excluded")
            for block in ordered:
                emit(str(block.get("raw_keyword_line") or block["normalized_keyword"]))
                for line in block.get("raw_lines", []):
                    emit(str(line))

            copy_mesh = False
            source_digest = hashlib.sha256()
            with source_path.open("rb") as source:
                for byte_line in source:
                    source_digest.update(byte_line)
                    line = byte_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if line.lstrip().startswith("*"):
                        copy_mesh = _keyword_token(line) in _MESH_CARDS
                    if copy_mesh:
                        emit(line)
            emit("*END")

    if source_digest.hexdigest() != _2K_SOURCE_SHA256:
        payload_path.unlink(missing_ok=True)
        raise ValueError("source SHA-256 changed while writing the model payload")

    digest = hashlib.sha256()
    with payload_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": payload_path.name, "format": "ls_dyna_keyword_gzip", "sha256": digest.hexdigest(), "byte_size": payload_path.stat().st_size}


def write_decomposition_package(
    report: dict[str, object],
    output_dir: Path,
    materials_dir: Path | None = None,
    structural_dir: Path | None = None,
) -> dict[str, str]:
    """Write the audited 2.k materials, model payload, manifest, and audit package."""
    source = report.get("source")
    if not isinstance(source, dict) or source.get("sha256") != _2K_SOURCE_SHA256:
        raise ValueError("package writing is restricted to the audited 2.k source SHA-256")
    source_path = Path(str(source.get("path", "")))
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if _file_sha256(source_path) != _2K_SOURCE_SHA256:
        raise ValueError("source SHA-256 does not match the audited 2.k file")

    output_dir.mkdir(parents=True, exist_ok=True)
    target_materials = materials_dir or output_dir / "materials"
    material_assets = _2k_material_assets()
    for material in material_assets:
        _write_json(target_materials / f"{material['id']}.json", material)
    target_structural = structural_dir or output_dir / "structural"
    structural_assets = _2k_structural_assets(report)
    for resource in structural_assets:
        _write_json(target_structural / f"{resource['id']}.json", resource)

    inventory = classify_resources(report)
    audit = {
        "schema_version": "0.1.0",
        "source_sha256": _2K_SOURCE_SHA256,
        "unused_section_ids": [7, 8],
        "unused_material_ids": [9, 10, 11, 13],
        "unused_part_set_ids": [5, 7, 8],
        "excluded_from_payload": True,
        "blockers": [record["code"] for record in inventory["blockers"]],
        "unused_resources": inventory["unused"],
        "unsupported_cards": inventory["unsupported"],
    }
    payload = _write_2k_payload(report, source_path, output_dir / f"{REFERENCE_FAMILY_ID}.k.gz")
    solid_pids = {201, 301, 401, 501, 1001, 1002}
    parts = []
    element_counts = report["mesh"]["element_count_by_pid"]
    for part in report["parts"]:
        pid = int(part["pid"])
        parts.append({
            **part,
            "element_family": "solid" if pid in solid_pids else "beam",
            "element_count": int(element_counts[str(pid)]),
        })
    sections = [
        {"secid": 1, "keyword": "*SECTION_BEAM_TITLE", "diameter_mm": 8.0},
        {"secid": 2, "keyword": "*SECTION_BEAM_TITLE", "diameter_mm": 12.0},
        {"secid": 3, "keyword": "*SECTION_BEAM_TITLE", "diameter_mm": 20.0},
        {"secid": 4, "keyword": "*SECTION_SOLID_TITLE", "elform": 1},
        {"secid": 5, "keyword": "*SECTION_SOLID_TITLE", "elform": 11},
        {"secid": 6, "keyword": "*SECTION_BEAM_TITLE", "diameter_mm": 18.0},
    ]
    manifest = {
        "schema_version": "0.1.0",
        "id": REFERENCE_FAMILY_ID,
        "name": REFERENCE_FAMILY_ID,
        "aliases": aliases_for(REFERENCE_FAMILY_ID, MODEL_RESOURCE_ALIASES),
        "display_name": MODEL_DISPLAY_NAMES[REFERENCE_FAMILY_ID],
        "version": "2026.08.03",
        "unit_system": "tonne_mm_s_N_MPa",
        "normalized_resource_unit_system": "SI_m_s_kg_N_Pa",
        "validation_status": "source_reference",
        "requires_project_review": True,
        "solver_ready": False,
        "provenance": {"source_name": LEGACY_SOURCE_FILENAME, "source_display_name": REFERENCE_DISPLAY_NAME_EN, "source_sha256": _2K_SOURCE_SHA256, "source_byte_size": source["byte_size"], "source_line_count": source["line_count"]},
        "payload": payload,
        "mesh_statistics": {
            "nodes": report["mesh"]["node_record_count"],
            "solid_elements": report["mesh"]["element_count_by_type"]["solid"],
            "beam_elements": report["mesh"]["element_count_by_type"]["beam"],
            "orphan_nodes": len(report["mesh"]["orphan_node_ids"]),
            "exact_coordinate_duplicate_groups": len(report["mesh"]["exact_coordinate_duplicate_groups"]),
        },
        "parts": parts,
        "sections": sections,
        "sets": [record for record in report["sets"] if not (record["keyword"].startswith("*SET_PART") and record["id"] in {5, 7, 8})],
        "couplings": report["constrained_couplings"],
        "material_resource_ids": [material["id"] for material in material_assets],
        "audit": audit,
        "notes": "Reusable source model package. It intentionally excludes unrelated control/output cards and all audit-only unused cards; therefore it is not a standalone solver deck.",
    }
    _write_json(output_dir / "manifest.json", manifest)
    _write_json(output_dir / "audit.json", audit)
    _write_json(output_dir / "inventory.json", inventory)
    return {
        "manifest": str(output_dir / "manifest.json"),
        "payload": str(output_dir / payload["path"]),
        "audit": str(output_dir / "audit.json"),
        "inventory": str(output_dir / "inventory.json"),
        "materials_dir": str(target_materials),
        "structural_dir": str(target_structural),
    }
