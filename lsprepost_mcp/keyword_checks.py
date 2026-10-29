from __future__ import annotations

import math
import hashlib
import json
from dataclasses import dataclass
from typing import Callable

from .city_ground_crater import GROUND_PROBE_SOLID_SET_ID
from .config import JSONDict
from .validation_profiles import validation_capabilities

Segment = tuple[int, ...]


@dataclass(frozen=True)
class KeywordModel:
    nodes: dict[int, tuple[float, float, float]]
    node_ids: list[int]
    shell_elements: list[tuple[int, int, int, int, int, int]]
    solid_elements: list[tuple[int, int, int, int, int, int, int, int, int, int]]
    parts: list[tuple[int, int | None, int | None]]
    section_id_list: list[int]
    material_id_list: list[int]
    material_density: dict[int, float]
    elastic_materials: dict[int, tuple[float, float, float]]
    section_ids: set[int]
    material_ids: set[int]
    shell_section_thickness: dict[int, float]
    node_sets: dict[int, list[int]]
    node_set_id_list: list[int]
    part_sets: dict[int, list[int]]
    part_set_id_list: list[int]
    shell_sets: dict[int, list[int]]
    shell_set_id_list: list[int]
    solid_sets: dict[int, list[int]]
    solid_set_id_list: list[int]
    segment_sets: dict[int, list[Segment]]
    segment_set_id_list: list[int]
    segment_set_add_refs: dict[int, list[int]]
    segment_loads: list[Segment]
    load_segment_set_ids: list[int]
    database_fsi_refs: list[tuple[int, int, int]]
    database_ale_solid_set_ids: list[int]
    database_history_node_set_ids: list[int]
    database_history_shell_set_ids: list[int]
    database_history_solid_set_ids: list[int]
    boundary_spc_node_set_ids: list[int]
    boundary_spc_constraints: list[tuple[int, int, int, int, int, int, int]]
    boundary_nonreflecting_segment_set_ids: list[int]
    boundary_nonreflecting_2d_node_set_ids: list[int]
    contact_refs: list[tuple[int, int, int, int]]
    tied_node_contact_refs: list[tuple[int, int, int, int]]
    coupling_refs: list[tuple[int, int, int, int]]
    initial_detonation_part_ids: list[int]
    ale_multi_material_part_ids: list[int]
    ivfg_part_ids: list[int]


def keyword_quality_checks(keyword: str, spec: JSONDict, metadata: JSONDict) -> list[JSONDict]:
    model = parse_keyword_model(keyword)
    checks: list[JSONDict] = []

    def add(check_id: str, ok: bool, message: str, severity: str = "error", actual: object | None = None) -> None:
        item: JSONDict = {"id": check_id, "ok": ok, "severity": "info" if ok else severity, "message": message}
        if actual is not None:
            item["actual"] = actual
        checks.append(item)

    check_keyword_structure(keyword, metadata, model, add)
    check_duplicate_ids(model, add)
    check_curve_contract(keyword, add)
    check_references(model, add)
    quality = check_element_quality(model, spec, add)
    check_orphans(model, add)
    check_shell_thickness_ratio(spec, model, metadata, add)
    check_assembly_component_constraints(metadata, add)
    check_material_ranges(model, add)
    check_r12_ale_compatibility(keyword, spec, metadata, add)
    check_r12_kc_compatibility(keyword, spec, metadata, add)
    check_phase17_city_contract(keyword, spec, metadata, model, add)
    check_city_ground_crater_contract(keyword, spec, metadata, model, add)
    estimate_mass_and_timestep(model, spec, quality, add)
    return checks


def check_phase17_city_contract(
    keyword: str,
    spec: JSONDict,
    metadata: JSONDict,
    model: KeywordModel,
    add: Callable[..., None],
) -> None:
    if spec.get("model_type") != "city_street_blast_scene":
        return
    ale_domain = metadata.get("ale_domain")
    explosive = metadata.get("explosive")
    if not isinstance(ale_domain, dict) or not isinstance(explosive, dict):
        add(
            "quality.phase17.source_refinement_binding",
            False,
            "Phase 17 city metadata contains ALE and explosive contracts",
        )
        return

    expected_mesh = ale_domain.get("mesh_fingerprint")
    actual_mesh = _actual_ale_mesh_fingerprint(
        model,
        int(ale_domain.get("part_id", 0)),
    )
    add(
        "quality.phase17.ale_mesh_fingerprint",
        isinstance(expected_mesh, str) and expected_mesh == actual_mesh,
        "serialized ALE axes match the recorded Phase 17 mesh fingerprint",
        actual={"expected": expected_mesh, "actual": actual_mesh},
    )

    center = explosive.get("center_m")
    refinement_center = ale_domain.get("refinement_center_m")
    diameter_cells = explosive.get("diameter_cells_actual")
    length_cells = explosive.get("length_cells_actual")
    source_binding_ok = (
        _finite_vector3(center)
        and _finite_vector3(refinement_center)
        and _vectors_close(center, refinement_center)
        and _finite_at_least(diameter_cells, 3.0)
        and _finite_at_least(length_cells, 3.0)
    )
    add(
        "quality.phase17.source_refinement_binding",
        source_binding_ok,
        "real TNT source, refinement center, and actual local-cell coverage agree",
        actual={
            "source_center_m": center,
            "refinement_center_m": refinement_center,
            "diameter_cells_actual": diameter_cells,
            "length_cells_actual": length_cells,
        },
    )


    detonation_fields = _first_card_data_fields(keyword, "*INITIAL_DETONATION")
    detonation_position = (
        detonation_fields[1:4]
        if len(detonation_fields) >= 4
        else []
    )
    add(
        "quality.phase17.initial_detonation_binding",
        _finite_vector3(center)
        and _vectors_close(center, detonation_position),
        "*INITIAL_DETONATION matches the real TNT geometric center",
        actual={
            "source_center_m": center,
            "detonation_position_m": detonation_position,
        },
    )

    fingerprints_ok = all(
        isinstance(metadata.get(field), str)
        and len(metadata[field]) == 64
        and all(character in "0123456789abcdef" for character in metadata[field])
        for field in ("layout_fingerprint", "editor_state_fingerprint")
    )
    add(
        "quality.phase17.editor_fingerprints",
        fingerprints_ok,
        "Phase 17 layout and editor-state fingerprints are present",
    )

    translation_fixed_nodes: set[int] = set()
    for node_set_id, dofx, dofy, dofz, _dofrx, _dofry, _dofrz in (
        model.boundary_spc_constraints
    ):
        if dofx and dofy and dofz:
            translation_fixed_nodes.update(model.node_sets.get(node_set_id, []))

    fsi_segments: list[Segment] = []
    for slave, _master, slave_type, _master_type in model.coupling_refs:
        if slave_type == 2:
            fsi_segments.extend(_resolved_segment_set(model, slave))
    fully_constrained_segments = [
        segment
        for segment in fsi_segments
        if segment and set(segment).issubset(translation_fixed_nodes)
    ]
    reported_fsi = metadata.get("fsi")
    reported_count = (
        reported_fsi.get("fully_constrained_slave_segment_count")
        if isinstance(reported_fsi, dict)
        else None
    )
    add(
        "quality.phase17.fsi_fully_constrained_segments",
        not fully_constrained_segments and reported_count == 0,
        "Phase 17 FSI slave segments retain at least one translation-free node",
        actual={
            "segment_count": len(fully_constrained_segments),
            "sample": [
                list(segment)
                for segment in fully_constrained_segments[:10]
            ],
            "reported_count": reported_count,
        },
    )


def check_city_ground_crater_contract(
    keyword: str,
    spec: JSONDict,
    metadata: JSONDict,
    model: KeywordModel,
    add: Callable[..., None],
) -> None:
    if "city_ground_crater_v1" not in resolved_validation_capabilities(
        spec,
        metadata,
    ):
        return
    ground = metadata.get("ground_response")
    if not isinstance(ground, dict):
        add(
            "quality.city_ground_crater.metadata",
            False,
            "city crater metadata is present",
        )
        return

    card_tokens = [keyword_card_token(line) for line in keyword.splitlines()]
    required_cards = {
        "*MAT_CONCRETE_DAMAGE_REL3",
        "*MAT_ADD_EROSION",
        "*DATABASE_EXTENT_BINARY",
        "*DATABASE_HISTORY_SOLID_SET",
    }
    missing_cards = sorted(required_cards - set(card_tokens))
    add(
        "quality.city_ground_crater.required_cards",
        not missing_cards,
        "K&C damage, erosion, binary state, and solid history cards are present",
        actual=missing_cards or "ok",
    )

    eroding_pid = int(ground.get("eroding_part_id", 0))
    support_pid = int(ground.get("support_part_id", 0))
    solid_counts = {
        pid: sum(1 for element in model.solid_elements if element[1] == pid)
        for pid in (eroding_pid, support_pid)
    }
    add(
        "quality.city_ground_crater.solid_ground_parts",
        eroding_pid > 0
        and support_pid > 0
        and all(count > 0 for count in solid_counts.values()),
        "eroding and lower-support ground parts both contain solid elements",
        actual=solid_counts,
    )

    expected_eroding_ids = {
        element[0]
        for element in model.solid_elements
        if element[1] == eroding_pid
    }
    recorded_eroding_ids = set(
        model.solid_sets.get(GROUND_PROBE_SOLID_SET_ID, [])
    )
    missing_history_ids = sorted(expected_eroding_ids - recorded_eroding_ids)
    extra_history_ids = sorted(recorded_eroding_ids - expected_eroding_ids)
    add(
        "quality.city_ground_crater.deletion_history_coverage",
        bool(expected_eroding_ids)
        and GROUND_PROBE_SOLID_SET_ID
        in model.database_history_solid_set_ids
        and not missing_history_ids
        and not extra_history_ids,
        "the eroding-ground history set covers every eroding solid exactly",
        actual={
            "set_id": GROUND_PROBE_SOLID_SET_ID,
            "expected_count": len(expected_eroding_ids),
            "actual_count": len(recorded_eroding_ids),
            "database_history_reference": (
                GROUND_PROBE_SOLID_SET_ID
                in model.database_history_solid_set_ids
            ),
            "missing_sample": missing_history_ids[:10],
            "extra_sample": extra_history_ids[:10],
        },
    )

    expected_fsi = {
        (
            int(ground["eroding_fsi"]["surface_id"]),
            int(ground["eroding_fsi"]["initial_segment_set_id"]),
        ),
        (
            int(ground["peripheral_fsi"]["surface_id"]),
            int(ground["peripheral_fsi"]["segment_set_id"]),
        ),
    }
    actual_fsi = {
        (surface, segment_set)
        for surface, segment_set, _ in model.database_fsi_refs
    }
    add(
        "quality.city_ground_crater.database_fsi",
        expected_fsi.issubset(actual_fsi),
        "both ground FSI surfaces are recorded by *DATABASE_FSI",
        actual={"expected": sorted(expected_fsi), "actual": sorted(actual_fsi)},
    )

    coupling_rows = _constrained_lagrange_rows(keyword)
    expected_couplings = {
        (
            int(ground["eroding_fsi"]["part_set_id"]),
            0,
            5,
        ),
        (
            int(ground["peripheral_fsi"]["segment_set_id"]),
            2,
            4,
        ),
    }
    actual_couplings = {
        (row[0], row[2], row[5])
        for row in coupling_rows
        if len(row) >= 6
    }
    add(
        "quality.city_ground_crater.split_fsi",
        expected_couplings.issubset(actual_couplings),
        "eroding CTYPE=5 and peripheral CTYPE=4 ground interfaces are distinct",
        actual={
            "expected": sorted(expected_couplings),
            "actual": sorted(actual_couplings),
        },
    )

    tie_ids = ground.get("foundation_tied_object_ids")
    expected_ties = len(tie_ids) if isinstance(tie_ids, list) else 0
    actual_ties = card_tokens.count("*CONTACT_TIED_NODES_TO_SURFACE")
    add(
        "quality.city_ground_crater.foundation_ties",
        expected_ties > 0 and actual_ties == expected_ties,
        "every recorded fixed facility foundation is tied to solid ground",
        actual={"expected": expected_ties, "actual": actual_ties},
    )

    add(
        "quality.city_ground_crater.no_ale_ground_reflection",
        "ALE ground reflection nodes" not in keyword,
        "crater mode does not constrain the ALE-ground overlap plane",
    )


def _constrained_lagrange_rows(keyword: str) -> list[list[int]]:
    rows: list[list[int]] = []
    active = False
    for raw in keyword.splitlines():
        token = keyword_card_token(raw)
        if token:
            active = token == "*CONSTRAINED_LAGRANGE_IN_SOLID"
            continue
        item = raw.strip()
        if not active or not item or item.startswith("$"):
            continue
        try:
            rows.append([int(float(field.strip())) for field in item.split(",")])
        except ValueError:
            pass
        active = False
    return rows


def _resolved_segment_set(
    model: KeywordModel,
    segment_set_id: int,
    visited: set[int] | None = None,
) -> list[Segment]:
    visited = set() if visited is None else set(visited)
    if segment_set_id in visited:
        return []
    visited.add(segment_set_id)
    segments = list(model.segment_sets.get(segment_set_id, []))
    for child_id in model.segment_set_add_refs.get(segment_set_id, []):
        segments.extend(_resolved_segment_set(model, child_id, visited))
    return segments


def _actual_ale_mesh_fingerprint(
    model: KeywordModel,
    part_id: int,
) -> str:
    node_ids: set[int] = set()
    for element in model.solid_elements:
        if element[1] == part_id:
            node_ids.update(element[2:10])
    axes = [set(), set(), set()]
    for node_id in node_ids:
        point = model.nodes.get(node_id)
        if point is None:
            continue
        for axis in range(3):
            axes[axis].add(round(float(point[axis]), 12))
    payload = json.dumps(
        {
            "x": sorted(axes[0]),
            "y": sorted(axes[1]),
            "z": sorted(axes[2]),
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _first_card_data_fields(keyword: str, card: str) -> list[float]:
    active = False
    for raw in keyword.splitlines():
        token = keyword_card_token(raw)
        if token:
            if active:
                break
            active = token == card
            continue
        line = raw.strip()
        if active and line and not line.startswith("$"):
            return numeric_fields(line)
    return []


def _finite_vector3(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 3
        and all(
            not isinstance(item, bool)
            and isinstance(item, (int, float))
            and math.isfinite(float(item))
            for item in value
        )
    )


def _vectors_close(left: object, right: object) -> bool:
    return (
        _finite_vector3(left)
        and _finite_vector3(right)
        and all(
            math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1.0e-8)
            for a, b in zip(left, right, strict=True)
        )
    )


def _finite_at_least(value: object, minimum: float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) >= minimum
    )


def check_keyword_structure(keyword: str, metadata: JSONDict, model: KeywordModel, add: Callable[..., None]) -> None:
    raw_lines = keyword.splitlines()
    stripped_nonempty = [line.strip() for line in raw_lines if line.strip()]
    card_tokens = [keyword_card_token(line) for line in stripped_nonempty]
    keyword_cards = [token for token in card_tokens if token in {"*KEYWORD"} or token.startswith("*KEYWORD_")]
    unsupported_keyword_cards = [token for token in keyword_cards if token not in {"*KEYWORD", "*KEYWORD_ID"}]
    end_indices = [index for index, token in enumerate(card_tokens) if token == "*END"]
    indented_cards = [
        index + 1
        for index, line in enumerate(raw_lines)
        if line.lstrip().startswith("*") and not line.startswith("*")
    ]
    add(
        "quality.keyword.boundary",
        len(keyword_cards) == 1
        and not unsupported_keyword_cards
        and len(end_indices) == 1
        and end_indices[0] == len(stripped_nonempty) - 1,
        "keyword deck has exactly one *KEYWORD card and exactly one final *END",
        actual={
            "keyword_cards": keyword_cards,
            "unsupported_keyword_cards": unsupported_keyword_cards,
            "end_positions": end_indices[-3:],
        },
    )
    tied_contact_cards = _card_data_line_counts(
        raw_lines,
        "*CONTACT_TIED_NODES_TO_SURFACE",
    )
    incomplete_tied_contacts = [
        {"line": line_number, "data_line_count": data_line_count}
        for line_number, data_line_count in tied_contact_cards
        if data_line_count < 3
    ]
    add(
        "quality.keyword.tied_node_contact_card_arity",
        not incomplete_tied_contacts,
        "each tied-node contact contains all three required data cards",
        actual=incomplete_tied_contacts or len(tied_contact_cards),
    )
    add(
        "quality.keyword.card_alignment",
        not indented_cards,
        "keyword cards are left-aligned",
        actual=indented_cards or "ok",
    )
    long_format = any("LONG" in line.upper() and "YES" in line.upper() for line in stripped_nonempty if keyword_card_token(line) in keyword_cards)
    ids = [
        *model.node_ids,
        *[element[0] for element in model.shell_elements],
        *[element[0] for element in model.solid_elements],
        *[part[0] for part in model.parts],
        *model.material_id_list,
        *model.section_id_list,
    ]
    max_id = max(ids) if ids else 0
    add(
        "quality.keyword.long_format_id_range",
        long_format or max_id <= 9_999_999,
        "standard ID range fits fixed keyword fields" if max_id <= 9_999_999 else "large IDs should use *KEYWORD long=yes",
        severity="warning",
        actual={"max_id": max_id, "long_format": long_format},
    )
    check_include_paths(raw_lines, metadata, add)
    check_parameters(keyword, add)
    contact_cards = sorted({line.strip().split()[0].split(",")[0] for line in raw_lines if line.strip().upper().startswith("*CONTACT_")})
    controlled_contact_cards = {str(card).upper() for card in metadata.get("controlled_contact_cards", []) if str(card).strip()}
    unsupported_contact_cards = [card for card in contact_cards if card.upper() not in controlled_contact_cards]
    add(
        "quality.unsupported.contact_cards",
        not unsupported_contact_cards,
        "no contact cards found"
        if not contact_cards
        else "all contact cards are controlled by this generator"
        if not unsupported_contact_cards
        else "contact cards are not yet controlled by this generator",
        severity="warning",
        actual={"contact_cards": contact_cards, "unsupported": unsupported_contact_cards} if contact_cards else "ok",
    )


def keyword_card_token(line: str) -> str:
    item = line.strip()
    if not item.startswith("*"):
        return ""
    return item.replace(",", " ", 1).split()[0].upper()


def _card_data_line_counts(
    raw_lines: list[str],
    card: str,
) -> list[tuple[int, int]]:
    counts: list[tuple[int, int]] = []
    active_line: int | None = None
    data_line_count = 0
    for line_number, raw in enumerate(raw_lines, start=1):
        token = keyword_card_token(raw)
        if token:
            if active_line is not None:
                counts.append((active_line, data_line_count))
            active_line = line_number if token == card else None
            data_line_count = 0
            continue
        stripped = raw.strip()
        if active_line is not None and stripped and not stripped.startswith("$"):
            data_line_count += 1
    if active_line is not None:
        counts.append((active_line, data_line_count))
    return counts


def r12_ale_compatibility_issues(keyword: str) -> list[JSONDict]:
    """Return known LS-DYNA R12 MM-ALE keyword incompatibilities."""

    blocks: list[tuple[str, int, list[tuple[int, str]]]] = []
    current_card = ""
    current_line = 0
    current_data: list[tuple[int, str]] = []
    for line_number, raw in enumerate(keyword.splitlines(), 1):
        line = raw.strip()
        if line.startswith("*"):
            if current_card:
                blocks.append((current_card, current_line, current_data))
            current_card = keyword_card_token(line)
            current_line = line_number
            current_data = []
        elif current_card and line and not line.startswith("$"):
            current_data.append((line_number, line))
    if current_card:
        blocks.append((current_card, current_line, current_data))

    issues: list[JSONDict] = []
    for card, card_line, data in blocks:
        if card == "*DATABASE_BINARY_FSIFOR":
            issues.append(
                {
                    "id": "database_binary_fsifor",
                    "line": card_line,
                    "actual": card,
                }
            )
        elif card.startswith("*CONSTRAINED_LAGRANGE_IN_SOLID") and len(data) > 3:
            issues.append(
                {
                    "id": "constrained_lagrange_extended_data",
                    "line": data[3][0],
                    "actual": data[3][1],
                }
            )
        elif card == "*DATABASE_ALE_MAT" and data:
            fields = [field.strip() for field in data[0][1].split(",")]
            if len(fields) > 2:
                issues.append(
                    {
                        "id": "database_ale_mat_field_count",
                        "line": data[0][0],
                        "actual": len(fields),
                    }
                )
        elif card == "*INITIAL_VOLUME_FRACTION_GEOMETRY" and len(data) >= 3:
            fields = [field.strip() for field in data[2][1].split(",")]
            if any(len(field) > 10 for field in fields):
                issues.append(
                    {
                        "id": "initial_volume_fraction_field_width",
                        "line": data[2][0],
                        "actual": [field for field in fields if len(field) > 10],
                    }
                )
    return issues


def _defined_curve_id_list(lines: list[str]) -> list[int]:
    curve_ids: list[int] = []
    for index, raw in enumerate(lines):
        token = keyword_card_token(raw)
        if token not in {"*DEFINE_CURVE", "*DEFINE_CURVE_TITLE"}:
            continue
        data: list[str] = []
        for candidate in lines[index + 1 :]:
            item = candidate.strip()
            if item.startswith("*"):
                break
            if item and not item.startswith("$"):
                data.append(item)
        data_index = 1 if token == "*DEFINE_CURVE_TITLE" else 0
        if len(data) <= data_index:
            continue
        try:
            curve_ids.append(int(data[data_index].split(",", 1)[0].strip()))
        except ValueError:
            continue
    return curve_ids


def _defined_curve_ids(lines: list[str]) -> set[int]:
    return set(_defined_curve_id_list(lines))


def _database_output_curve_ids(lines: list[str]) -> list[int]:
    references: list[int] = []
    for index, raw in enumerate(lines):
        if keyword_card_token(raw) not in {
            "*DATABASE_BINARY_D3PLOT",
            "*DATABASE_BINARY_D3THDT",
        }:
            continue
        for candidate in lines[index + 1 :]:
            item = candidate.strip()
            if item.startswith("*"):
                break
            if not item or item.startswith("$"):
                continue
            fields = item.replace(",", " ").split()
            if len(fields) >= 2:
                try:
                    curve_id = int(float(fields[1]))
                except ValueError:
                    curve_id = 0
                if curve_id > 0:
                    references.append(curve_id)
            break
    return references


def check_curve_contract(keyword: str, add: Callable[..., None]) -> None:
    lines = keyword.splitlines()
    curve_id_list = _defined_curve_id_list(lines)
    duplicates = duplicate_ids(curve_id_list)
    add(
        "quality.id.curves_unique",
        not duplicates,
        "curve IDs are unique",
        actual=duplicates or len(curve_id_list),
    )
    missing = sorted(
        set(_database_output_curve_ids(lines)) - set(curve_id_list)
    )
    add(
        "quality.ref.database_output_curves",
        not missing,
        "database output curve references are defined",
        actual=missing or "ok",
    )


def r12_kc_automatic_issues(keyword: str) -> list[JSONDict]:
    """Check the R12 simple-input contract for K&C automatic generation."""

    lines = keyword.splitlines()
    for index, raw in enumerate(lines):
        if keyword_card_token(raw) != "*MAT_CONCRETE_DAMAGE_REL3":
            continue
        data: list[tuple[int, str]] = []
        for line_number, candidate in enumerate(lines[index + 1 :], index + 2):
            item = candidate.strip()
            if item.startswith("*"):
                break
            if item and not item.startswith("$"):
                data.append((line_number, item))
        if len(data) < 2:
            return [{"id": "kc_automatic_card_count", "line": index + 1, "actual": len(data)}]
        card2 = [field.strip() for field in data[1][1].split(",")]
        try:
            a0 = float(card2[1])
        except (IndexError, ValueError):
            return []
        manual_values = [value for field_index, value in enumerate(card2) if field_index != 1 and value]
        if a0 >= 0.0 or manual_values:
            return []
        if len(data) != 7:
            return [{"id": "kc_automatic_card_count", "line": index + 1, "actual": len(data)}]
        card3 = [field.strip() for field in data[2][1].split(",")]
        if len(card3) != 8:
            return [{"id": "kc_automatic_conversion_fields", "line": data[2][0], "actual": len(card3)}]
        try:
            rsize = float(card3[3])
            ucf = float(card3[4])
            lcrate = int(card3[5])
        except (ValueError, IndexError):
            return [{"id": "kc_automatic_conversion_values", "line": data[2][0], "actual": card3}]
        if rsize <= 0.0 or ucf <= 0.0 or lcrate == 0 or lcrate < -1:
            return [{"id": "kc_automatic_conversion_values", "line": data[2][0], "actual": card3}]
        curve_ids = _defined_curve_ids(lines)
        if lcrate == -1 and not curve_ids:
            return [
                {
                    "id": "kc_automatic_curve_table_missing",
                    "line": data[2][0],
                    "actual": "LCRATE=-1 with no *DEFINE_CURVE card",
                }
            ]
        if lcrate > 0 and lcrate not in curve_ids:
            return [
                {
                    "id": "kc_rate_curve_missing",
                    "line": data[2][0],
                    "actual": {"lcrate": lcrate, "defined_curve_ids": sorted(curve_ids)},
                }
            ]
        return []
    return []


def check_r12_ale_compatibility(
    keyword: str,
    spec: JSONDict,
    metadata: JSONDict,
    add: Callable[..., None],
) -> None:
    if "mm_ale" not in resolved_validation_capabilities(spec, metadata):
        return
    issues = r12_ale_compatibility_issues(keyword)
    messages = {
        "database_binary_fsifor": "R12 deck does not request binary FSIFOR without supported INTFORC fields",
        "constrained_lagrange_extended_data": "R12 coupling cards use only the supported three data lines",
        "database_ale_mat_field_count": "R12 DATABASE_ALE_MAT uses no more than two fields",
        "initial_volume_fraction_field_width": "R12 initial volume fraction fields fit within 10 characters",
    }
    for issue_id, message in messages.items():
        matching = [issue for issue in issues if issue["id"] == issue_id]
        add(
            f"quality.r12_ale.{issue_id}",
            not matching,
            message,
            actual=matching or "ok",
        )


def check_r12_kc_compatibility(
    keyword: str,
    spec: JSONDict,
    metadata: JSONDict,
    add: Callable[..., None],
) -> None:
    if "kc_concrete" not in resolved_validation_capabilities(spec, metadata):
        return
    issues = r12_kc_automatic_issues(keyword)
    add(
        "quality.r12_kc.automatic_card",
        not issues,
        "R12 K&C automatic material card follows the seven-line contract and has a curve table",
        actual=issues or "ok",
    )


def resolved_validation_capabilities(spec: JSONDict, metadata: JSONDict) -> set[str]:
    try:
        return set(validation_capabilities(spec, metadata))
    except ValueError:
        return set()


def check_include_paths(raw_lines: list[str], metadata: JSONDict, add: Callable[..., None]) -> None:
    include_paths: list[str] = []
    for index, line in enumerate(raw_lines):
        upper = line.strip().upper()
        if not upper.startswith("*INCLUDE"):
            continue
        for next_line in raw_lines[index + 1 :]:
            item = next_line.strip()
            if not item or item.startswith("$"):
                continue
            if item.startswith("*"):
                break
            include_paths.append(item.split(",")[0].strip())
            break
    if not include_paths:
        add("quality.keyword.include_paths", True, "no include paths found", actual="none")
        return
    base = str(metadata.get("keyword_dir", "") or metadata.get("_project_dir", "") or "").strip()
    if not base:
        add(
            "quality.keyword.include_paths",
            False,
            "include paths found but no base directory is available for static path checks",
            severity="warning",
            actual=include_paths,
        )
        return
    from pathlib import Path

    base_path = Path(base)
    missing = []
    for include_path in include_paths:
        path = Path(include_path)
        resolved = path if path.is_absolute() else base_path / path
        if not resolved.exists():
            missing.append(include_path)
    add(
        "quality.keyword.include_paths",
        not missing,
        "all include paths exist",
        actual=missing or include_paths,
    )


def check_parameters(keyword: str, add: Callable[..., None]) -> None:
    tokens = keyword.replace(",", " ").replace("=", " ").split()
    defined: set[str] = set()
    used: set[str] = set()
    lines = [line.strip() for line in keyword.splitlines()]
    in_parameter = False
    for line in lines:
        upper = line.upper()
        if upper.startswith("*"):
            in_parameter = upper.startswith("*PARAMETER")
            continue
        if not in_parameter or not line or line.startswith("$"):
            continue
        fields = [field.strip() for field in line.replace(",", " ").split() if field.strip()]
        if len(fields) >= 2:
            defined.add(fields[1].lstrip("&"))
    for token in tokens:
        if token.startswith("&") and len(token) > 1:
            used.add(token[1:].strip())
    missing = sorted(used - defined)
    add(
        "quality.keyword.parameters",
        not missing,
        "all parameter references are defined",
        actual={"defined": sorted(defined), "missing": missing} if defined or missing else "none",
    )


def parse_keyword_model(keyword: str) -> KeywordModel:
    raw_lines = keyword.splitlines()
    lines = [line.strip() for line in raw_lines]
    nodes: dict[int, tuple[float, float, float]] = {}
    node_ids: list[int] = []
    node_sets: dict[int, list[int]] = {}
    node_set_id_list: list[int] = []
    part_sets: dict[int, list[int]] = {}
    part_set_id_list: list[int] = []
    shell_sets: dict[int, list[int]] = {}
    shell_set_id_list: list[int] = []
    solid_sets: dict[int, list[int]] = {}
    solid_set_id_list: list[int] = []
    segment_set_id_list: list[int] = []
    shell_elements: list[tuple[int, int, int, int, int, int]] = []
    solid_elements: list[tuple[int, int, int, int, int, int, int, int, int, int]] = []
    parts: list[tuple[int, int | None, int | None]] = []
    material_density: dict[int, float] = {}
    elastic_materials: dict[int, tuple[float, float, float]] = {}
    section_ids: set[int] = set()
    section_id_list: list[int] = []
    material_ids: set[int] = set()
    material_id_list: list[int] = []
    shell_section_thickness: dict[int, float] = {}
    segment_sets: dict[int, list[Segment]] = {}
    segment_set_add_refs: dict[int, list[int]] = {}
    segment_loads: list[Segment] = []
    load_segment_set_ids: list[int] = []
    database_fsi_refs: list[tuple[int, int, int]] = []
    database_ale_solid_set_ids: list[int] = []
    database_history_node_set_ids: list[int] = []
    database_history_shell_set_ids: list[int] = []
    database_history_solid_set_ids: list[int] = []
    boundary_spc_node_set_ids: list[int] = []
    boundary_spc_constraints: list[
        tuple[int, int, int, int, int, int, int]
    ] = []
    boundary_nonreflecting_segment_set_ids: list[int] = []
    boundary_nonreflecting_2d_node_set_ids: list[int] = []
    contact_refs: list[tuple[int, int, int, int]] = []
    tied_node_contact_refs: list[tuple[int, int, int, int]] = []
    coupling_refs: list[tuple[int, int, int, int]] = []
    initial_detonation_part_ids: list[int] = []
    ale_multi_material_part_ids: list[int] = []
    ivfg_part_ids: list[int] = []

    index = 0
    while index < len(lines):
        line = lines[index]
        upper = line.upper()
        if not upper.startswith("*"):
            index += 1
            continue
        if upper == "*NODE":
            index += 1
            while index < len(lines) and not lines[index].startswith("*"):
                fields = numeric_fields(lines[index])
                if len(fields) >= 4:
                    nid = int(fields[0])
                    node_ids.append(nid)
                    nodes[nid] = (float(fields[1]), float(fields[2]), float(fields[3]))
                index += 1
            continue
        if upper.startswith("*ELEMENT_SHELL"):
            index += 1
            while index < len(lines) and not lines[index].startswith("*"):
                fields = int_fields(lines[index])
                if len(fields) >= 6:
                    shell_elements.append((fields[0], fields[1], fields[2], fields[3], fields[4], fields[5]))
                index += 1
            continue
        if upper.startswith("*ELEMENT_SOLID"):
            index += 1
            while index < len(lines) and not lines[index].startswith("*"):
                fields = int_fields(lines[index])
                if len(fields) >= 10:
                    solid_elements.append((fields[0], fields[1], *fields[2:10]))
                index += 1
            continue
        if upper.startswith("*SET_NODE"):
            sid, ids, index = parse_node_set(lines, index)
            if sid is not None:
                node_set_id_list.append(sid)
                node_sets[sid] = ids
            continue
        if upper.startswith("*SET_PART"):
            sid, ids, index = parse_id_set(lines, index)
            if sid is not None:
                part_set_id_list.append(sid)
                part_sets[sid] = ids
            continue
        if upper.startswith("*SET_SHELL"):
            sid, ids, index = parse_id_set(lines, index)
            if sid is not None:
                shell_set_id_list.append(sid)
                shell_sets[sid] = ids
            continue
        if upper.startswith("*SET_SOLID"):
            sid, ids, index = parse_id_set(lines, index)
            if sid is not None:
                solid_set_id_list.append(sid)
                solid_sets[sid] = ids
            continue
        if upper.startswith("*SET_SEGMENT_ADD"):
            sid, ids, index = parse_id_set(lines, index)
            if sid is not None:
                segment_set_id_list.append(sid)
                segment_sets[sid] = []
                segment_set_add_refs[sid] = ids
            continue
        if upper.startswith("*SET_SEGMENT"):
            sid, segments, index = parse_segment_set(lines, index)
            if sid is not None:
                segment_set_id_list.append(sid)
                segment_sets[sid] = segments
            continue
        if upper.startswith("*LOAD_SEGMENT_SET"):
            index += 1
            while index < len(lines) and not lines[index].startswith("*"):
                fields = int_fields(lines[index])
                if fields:
                    load_segment_set_ids.append(fields[0])
                index += 1
            continue
        if upper.startswith("*LOAD_SEGMENT") and not upper.startswith("*LOAD_SEGMENT_SET"):
            index += 1
            while index < len(lines) and not lines[index].startswith("*"):
                fields = int_fields(lines[index])
                if len(fields) >= 7:
                    segment_loads.append((fields[3], fields[4], fields[5], fields[6]))
                index += 1
            continue
        if upper == "*DATABASE_FSI":
            index += 1
            saw_interval = False
            while index < len(lines) and not lines[index].startswith("*"):
                fields = int_fields(lines[index])
                if fields:
                    if not saw_interval:
                        saw_interval = True
                    elif len(fields) >= 3:
                        database_fsi_refs.append((fields[0], fields[1], fields[2]))
                index += 1
            continue
        if upper == "*DATABASE_ALE":
            fields, next_index = next_numeric_fields(lines, index)
            if len(fields) >= 2:
                database_ale_solid_set_ids.append(int(fields[1]))
            index = max(next_index, index + 1)
            continue
        if upper.startswith("*DATABASE_HISTORY_NODE_SET"):
            fields, next_index = next_numeric_fields(lines, index)
            if fields:
                database_history_node_set_ids.append(int(fields[0]))
            index = max(next_index, index + 1)
            continue
        if upper.startswith("*DATABASE_HISTORY_SHELL_SET"):
            fields, next_index = next_numeric_fields(lines, index)
            if fields:
                database_history_shell_set_ids.append(int(fields[0]))
            index = max(next_index, index + 1)
            continue
        if upper.startswith("*DATABASE_HISTORY_SOLID_SET"):
            fields, next_index = next_numeric_fields(lines, index)
            if fields:
                database_history_solid_set_ids.append(int(fields[0]))
            index = max(next_index, index + 1)
            continue
        if upper.startswith("*BOUNDARY_SPC_SET"):
            fields, next_index = next_numeric_fields(lines, index)
            if fields:
                node_set_id = int(fields[0])
                boundary_spc_node_set_ids.append(node_set_id)
                if len(fields) >= 8:
                    boundary_spc_constraints.append(
                        (
                            node_set_id,
                            int(fields[2]),
                            int(fields[3]),
                            int(fields[4]),
                            int(fields[5]),
                            int(fields[6]),
                            int(fields[7]),
                        )
                    )
            index = max(next_index, index + 1)
            continue
        if upper == "*BOUNDARY_NON_REFLECTING":
            fields, next_index = next_numeric_fields(lines, index)
            if fields:
                boundary_nonreflecting_segment_set_ids.append(int(fields[0]))
            index = max(next_index, index + 1)
            continue
        if upper == "*BOUNDARY_NON_REFLECTING_2D":
            fields, next_index = next_numeric_fields(lines, index)
            if fields:
                boundary_nonreflecting_2d_node_set_ids.append(int(fields[0]))
            index = max(next_index, index + 1)
            continue
        if upper.startswith("*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE"):
            fields, next_index = next_numeric_fields(lines, index)
            if len(fields) >= 4:
                contact_refs.append(
                    (int(fields[0]), int(fields[1]), int(fields[2]), int(fields[3]))
                )
            index = max(next_index, index + 1)
            continue
        if upper.startswith("*CONTACT_TIED_NODES_TO_SURFACE"):
            fields, next_index = next_numeric_fields(lines, index)
            if len(fields) >= 4:
                tied_node_contact_refs.append(
                    (int(fields[0]), int(fields[1]), int(fields[2]), int(fields[3]))
                )
            index = max(next_index, index + 1)
            continue
        if upper.startswith("*CONSTRAINED_LAGRANGE_IN_SOLID"):
            fields, next_index = next_numeric_fields(lines, index)
            if len(fields) >= 4:
                coupling_refs.append(
                    (int(fields[0]), int(fields[1]), int(fields[2]), int(fields[3]))
                )
            index = max(next_index, index + 1)
            continue
        if upper == "*INITIAL_DETONATION":
            fields, next_index = next_numeric_fields(lines, index)
            if fields:
                initial_detonation_part_ids.append(int(fields[0]))
            index = max(next_index, index + 1)
            continue
        if upper == "*ALE_MULTI-MATERIAL_GROUP":
            index += 1
            while index < len(lines) and not lines[index].startswith("*"):
                fields = int_fields(lines[index])
                if fields:
                    ale_multi_material_part_ids.append(fields[0])
                index += 1
            continue
        if upper == "*INITIAL_VOLUME_FRACTION_GEOMETRY":
            fields, next_index = next_numeric_fields(lines, index)
            if len(fields) >= 2 and int(fields[1]) == 1:
                ivfg_part_ids.append(int(fields[0]))
            index = max(next_index, index + 1)
            continue
        if upper.startswith("*PART"):
            fields, next_index = next_numeric_fields(lines, index)
            if fields:
                pid = int(fields[0])
                secid = int(fields[1]) if len(fields) > 1 else None
                mid = int(fields[2]) if len(fields) > 2 else None
                parts.append((pid, secid, mid))
            index = max(next_index, index + 1)
            continue
        if upper.startswith("*SECTION_SHELL"):
            section_id, thickness, next_index = parse_shell_section(lines, index)
            if section_id is not None:
                section_ids.add(section_id)
                section_id_list.append(section_id)
                if thickness is not None:
                    shell_section_thickness[section_id] = thickness
            index = next_index
            continue
        if upper.startswith("*SECTION_"):
            fields, next_index = next_numeric_fields(lines, index)
            if fields:
                section_id = int(fields[0])
                section_ids.add(section_id)
                section_id_list.append(section_id)
            index = max(next_index, index + 1)
            continue
        if upper.startswith("*MAT_ADD_"):
            _, next_index = next_numeric_fields(lines, index)
            index = max(next_index, index + 1)
            continue
        if upper.startswith("*MAT_"):
            fields, next_index = material_header_fields(raw_lines, index)
            if fields:
                mid = int(fields[0])
                material_ids.add(mid)
                material_id_list.append(mid)
                if len(fields) >= 2:
                    material_density[mid] = float(fields[1])
                if upper.startswith("*MAT_ELASTIC") and len(fields) >= 4:
                    elastic_materials[mid] = (float(fields[1]), float(fields[2]), float(fields[3]))
            index = max(next_index, index + 1)
            continue
        index += 1

    return KeywordModel(
        nodes=nodes,
        node_ids=node_ids,
        shell_elements=shell_elements,
        solid_elements=solid_elements,
        parts=parts,
        section_id_list=section_id_list,
        material_id_list=material_id_list,
        material_density=material_density,
        elastic_materials=elastic_materials,
        section_ids=section_ids,
        material_ids=material_ids,
        shell_section_thickness=shell_section_thickness,
        node_sets=node_sets,
        node_set_id_list=node_set_id_list,
        part_sets=part_sets,
        part_set_id_list=part_set_id_list,
        shell_sets=shell_sets,
        shell_set_id_list=shell_set_id_list,
        solid_sets=solid_sets,
        solid_set_id_list=solid_set_id_list,
        segment_sets=segment_sets,
        segment_set_id_list=segment_set_id_list,
        segment_set_add_refs=segment_set_add_refs,
        segment_loads=segment_loads,
        load_segment_set_ids=load_segment_set_ids,
        database_fsi_refs=database_fsi_refs,
        database_ale_solid_set_ids=database_ale_solid_set_ids,
        database_history_node_set_ids=database_history_node_set_ids,
        database_history_shell_set_ids=database_history_shell_set_ids,
        database_history_solid_set_ids=database_history_solid_set_ids,
        boundary_spc_node_set_ids=boundary_spc_node_set_ids,
        boundary_spc_constraints=boundary_spc_constraints,
        boundary_nonreflecting_segment_set_ids=boundary_nonreflecting_segment_set_ids,
        boundary_nonreflecting_2d_node_set_ids=boundary_nonreflecting_2d_node_set_ids,
        contact_refs=contact_refs,
        tied_node_contact_refs=tied_node_contact_refs,
        coupling_refs=coupling_refs,
        initial_detonation_part_ids=initial_detonation_part_ids,
        ale_multi_material_part_ids=ale_multi_material_part_ids,
        ivfg_part_ids=ivfg_part_ids,
    )


def parse_node_set(lines: list[str], start: int) -> tuple[int | None, list[int], int]:
    return parse_id_set(lines, start)


def parse_id_set(lines: list[str], start: int) -> tuple[int | None, list[int], int]:
    sid: int | None = None
    ids: list[int] = []
    index = start + 1
    while index < len(lines) and not lines[index].startswith("*"):
        fields = int_fields(lines[index])
        if fields:
            if sid is None:
                sid = fields[0]
            else:
                ids.extend(fields)
        index += 1
    return sid, ids, index


def parse_segment_set(lines: list[str], start: int) -> tuple[int | None, list[Segment], int]:
    sid: int | None = None
    segments: list[Segment] = []
    index = start + 1
    while index < len(lines) and not lines[index].startswith("*"):
        fields = int_fields(lines[index])
        if fields:
            if sid is None:
                sid = fields[0]
            elif len(fields) >= 4:
                segments.append(tuple(fields[:4]))
            elif len(fields) >= 2:
                segments.append(tuple(fields[:2]))
        index += 1
    return sid, segments, index


def parse_shell_section(lines: list[str], start: int) -> tuple[int | None, float | None, int]:
    fields, first_index = next_numeric_fields(lines, start)
    if not fields:
        return None, None, max(first_index, start + 1)
    section_id = int(fields[0])
    thickness: float | None = None
    index = first_index + 1
    while index < len(lines) and not lines[index].startswith("*"):
        t_fields = numeric_fields(lines[index])
        if len(t_fields) >= 4:
            thickness = sum(float(value) for value in t_fields[:4]) / 4.0
            return section_id, thickness, index + 1
        index += 1
    return section_id, thickness, index


def next_numeric_fields(lines: list[str], start: int) -> tuple[list[float], int]:
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("*"):
            return [], index
        fields = numeric_fields(lines[index])
        if fields:
            return fields, index
    return [], len(lines)


def numeric_fields(line: str) -> list[float]:
    if not line or line.startswith("$"):
        return []
    chunks = line.split(",") if "," in line else line.split()
    values: list[float] = []
    for chunk in chunks:
        token = chunk.strip()
        if not token:
            continue
        try:
            values.append(float(token))
        except ValueError:
            return []
    return values


def material_header_fields(lines: list[str], start: int) -> tuple[list[float], int]:
    """Read the first material data card, keeping standard 10-column fields.

    Only MID, density, E and nu are consumed by these static checks. Do not
    scan later cards after a malformed header: their first field is not MID.
    """
    title_pending = keyword_card_token(lines[start]).endswith("_TITLE")
    for index in range(start + 1, len(lines)):
        raw = lines[index]
        line = raw.strip()
        if line.startswith("*"):
            return [], index
        if line.startswith("$"):
            continue
        if title_pending:
            title_pending = False
            continue
        if not line:
            continue
        if "," not in raw and len(raw) >= 20:
            try:
                # A fixed-width MID must occupy its own integer field.
                mid = int(raw[:10].strip())
                values = [float(mid)]
                for offset in range(10, min(len(raw), 40), 10):
                    token = raw[offset:offset + 10].strip()
                    values.append(float(token.replace("D", "E").replace("d", "e")) if token else 0.0)
                return values, index
            except ValueError:
                pass
        if "," in line:
            try:
                values = [float(token.strip().replace("D", "E").replace("d", "e")) if token.strip() else 0.0 for token in line.split(",")[:4]]
            except ValueError:
                values = []
        else:
            values = numeric_fields(line)
        return values, index
    return [], len(lines)


def int_fields(line: str) -> list[int]:
    return [int(value) for value in numeric_fields(line)]


def check_duplicate_ids(model: KeywordModel, add: Callable[..., None]) -> None:
    duplicate_checks = {
        "quality.id.nodes_unique": model.node_ids,
        "quality.id.shell_elements_unique": [element[0] for element in model.shell_elements],
        "quality.id.solid_elements_unique": [element[0] for element in model.solid_elements],
        "quality.id.parts_unique": [part[0] for part in model.parts],
        "quality.id.materials_unique": model.material_id_list,
        "quality.id.sections_unique": model.section_id_list,
        "quality.id.node_sets_unique": model.node_set_id_list,
        "quality.id.part_sets_unique": model.part_set_id_list,
        "quality.id.shell_sets_unique": model.shell_set_id_list,
        "quality.id.solid_sets_unique": model.solid_set_id_list,
        "quality.id.segment_sets_unique": model.segment_set_id_list,
    }
    for check_id, ids in duplicate_checks.items():
        duplicates = duplicate_ids(ids)
        add(check_id, not duplicates, "IDs are unique" if not duplicates else f"duplicate IDs found: {duplicates}", actual=duplicates or len(ids))


def duplicate_ids(ids: list[int]) -> list[int]:
    seen: set[int] = set()
    duplicates: set[int] = set()
    for value in ids:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def check_references(model: KeywordModel, add: Callable[..., None]) -> None:
    node_ids = set(model.nodes)
    part_ids = {part[0] for part in model.parts}
    shell_element_ids = {element[0] for element in model.shell_elements}
    solid_element_ids = {element[0] for element in model.solid_elements}
    missing_element_nodes = sorted(
        [element[0] for element in model.shell_elements if not set(shell_node_ids(element[2:6])).issubset(node_ids)]
        + [element[0] for element in model.solid_elements if not set(element[2:10]).issubset(node_ids)]
    )
    missing_element_parts = sorted(element[0] for element in all_elements(model) if element[1] not in part_ids)
    missing_part_sections = sorted(pid for pid, secid, _ in model.parts if secid is None or secid not in model.section_ids)
    missing_part_materials = sorted(pid for pid, _, mid in model.parts if mid is None or mid not in model.material_ids)
    missing_set_nodes = sorted(sid for sid, ids in model.node_sets.items() if not set(ids).issubset(node_ids))
    missing_part_set_members = sorted(
        sid for sid, ids in model.part_sets.items() if not set(ids).issubset(part_ids)
    )
    missing_shell_set_members = sorted(
        sid
        for sid, ids in model.shell_sets.items()
        if not set(ids).issubset(shell_element_ids)
    )
    missing_solid_set_members = sorted(
        sid
        for sid, ids in model.solid_sets.items()
        if not set(ids).issubset(solid_element_ids)
    )
    missing_segment_set_nodes = sorted(
        sid
        for sid, segments in model.segment_sets.items()
        if any(not set(segment).issubset(node_ids) for segment in segments)
    )
    missing_segment_set_add_members = sorted(
        sid
        for sid, member_ids in model.segment_set_add_refs.items()
        if not set(member_ids).issubset(model.segment_sets)
    )
    missing_segment_nodes = sorted(index + 1 for index, segment in enumerate(model.segment_loads) if not set(segment).issubset(node_ids))
    missing_load_segment_sets = sorted(set(model.load_segment_set_ids) - set(model.segment_sets))
    missing_database_fsi_parts = sorted(
        sid
        for _dbfsi_id, sid, stype in model.database_fsi_refs
        if stype == 1 and sid not in part_ids
    )
    missing_database_fsi_segment_sets = sorted(
        sid
        for _dbfsi_id, sid, stype in model.database_fsi_refs
        if stype == 2 and sid not in model.segment_sets
    )
    missing_boundary_spc_node_sets = sorted(
        set(model.boundary_spc_node_set_ids) - set(model.node_sets)
    )
    missing_nonreflecting_segment_sets = sorted(
        set(model.boundary_nonreflecting_segment_set_ids) - set(model.segment_sets)
    )
    missing_nonreflecting_2d_node_sets = sorted(
        set(model.boundary_nonreflecting_2d_node_set_ids) - set(model.node_sets)
    )
    missing_contact_parts = sorted(
        {
            reference
            for slave, master, slave_type, master_type in model.contact_refs
            for reference, reference_type in (
                (slave, slave_type),
                (master, master_type),
            )
            if reference_type == 1 and reference not in part_ids
        }
    )
    missing_contact_part_sets = sorted(
        {
            reference
            for slave, master, slave_type, master_type in model.contact_refs
            for reference, reference_type in (
                (slave, slave_type),
                (master, master_type),
            )
            if reference_type == 2 and reference not in model.part_sets
        }
    )
    missing_tied_contact_node_sets = sorted(
        {
            slave
            for slave, _master, slave_type, _master_type in model.tied_node_contact_refs
            if slave_type == 4
            and (slave not in model.node_sets or not model.node_sets[slave])
        }
    )
    missing_tied_contact_segment_sets = sorted(
        {
            master
            for _slave, master, _slave_type, master_type in model.tied_node_contact_refs
            if master_type == 0
            and (master not in model.segment_sets or not model.segment_sets[master])
        }
    )
    missing_fsi_slave_parts = sorted(
        slave
        for slave, _master, slave_type, _master_type in model.coupling_refs
        if slave_type == 1 and slave not in part_ids
    )
    missing_fsi_slave_segment_sets = sorted(
        slave
        for slave, _master, slave_type, _master_type in model.coupling_refs
        if slave_type == 2 and slave not in model.segment_sets
    )
    missing_fsi_master_part_sets = sorted(
        master
        for _slave, master, _slave_type, master_type in model.coupling_refs
        if master_type == 0 and master not in model.part_sets
    )
    empty_fsi_slave_segment_sets = sorted(
        {
            slave
            for slave, _master, slave_type, _master_type in model.coupling_refs
            if slave_type == 2
            and slave in model.segment_sets
            and not segment_set_has_members(model, slave)
        }
        | {
            sid
            for _dbfsi_id, sid, stype in model.database_fsi_refs
            if stype == 2
            and sid in model.segment_sets
            and not segment_set_has_members(model, sid)
        }
    )
    empty_fsi_master_part_sets = sorted(
        master
        for _slave, master, _slave_type, master_type in model.coupling_refs
        if master_type == 0
        and master in model.part_sets
        and not model.part_sets[master]
    )
    missing_initial_detonation_parts = sorted(
        set(model.initial_detonation_part_ids) - part_ids
    )
    missing_ale_material_group_parts = sorted(
        set(model.ale_multi_material_part_ids) - part_ids
    )
    missing_ivfg_parts = sorted(set(model.ivfg_part_ids) - part_ids)
    missing_database_ale_solid_sets = sorted(
        set(model.database_ale_solid_set_ids) - set(model.solid_sets)
    )
    missing_history_node_sets = sorted(
        set(model.database_history_node_set_ids) - set(model.node_sets)
    )
    missing_history_shell_sets = sorted(
        set(model.database_history_shell_set_ids) - set(model.shell_sets)
    )
    missing_history_solid_sets = sorted(
        set(model.database_history_solid_set_ids) - set(model.solid_sets)
    )
    add("quality.ref.element_nodes", not missing_element_nodes, "all elements reference existing nodes", actual=missing_element_nodes or "ok")
    add("quality.ref.element_parts", not missing_element_parts, "all elements reference existing parts", actual=missing_element_parts or "ok")
    add("quality.ref.part_sections", not missing_part_sections, "all parts reference existing sections", actual=missing_part_sections or "ok")
    add("quality.ref.part_materials", not missing_part_materials, "all parts reference existing materials", actual=missing_part_materials or "ok")
    add("quality.ref.node_sets", not missing_set_nodes, "all node sets reference existing nodes", actual=missing_set_nodes or "ok")
    add(
        "quality.ref.part_sets",
        not missing_part_set_members,
        "all part sets reference existing parts",
        actual=missing_part_set_members or "ok",
    )
    add(
        "quality.ref.shell_sets",
        not missing_shell_set_members,
        "all shell sets reference existing shell elements",
        actual=missing_shell_set_members or "ok",
    )
    add(
        "quality.ref.solid_sets",
        not missing_solid_set_members,
        "all solid sets reference existing solid elements",
        actual=missing_solid_set_members or "ok",
    )
    add("quality.ref.segment_sets", not missing_segment_set_nodes, "all segment sets reference existing nodes", actual=missing_segment_set_nodes or "ok")
    add(
        "quality.ref.segment_set_add_members",
        not missing_segment_set_add_members,
        "all composite segment sets reference existing segment sets",
        actual=missing_segment_set_add_members or "ok",
    )
    add("quality.ref.load_segments", not missing_segment_nodes, "all direct load segments reference existing nodes", actual=missing_segment_nodes or "ok")
    add(
        "quality.ref.load_segment_sets",
        not missing_load_segment_sets,
        "all segment-set pressure loads reference existing segment sets",
        actual=missing_load_segment_sets or "ok",
    )
    add(
        "quality.ref.database_fsi_parts",
        not missing_database_fsi_parts,
        "all *DATABASE_FSI part references exist",
        actual=missing_database_fsi_parts or "ok",
    )
    add(
        "quality.ref.database_fsi_segment_sets",
        not missing_database_fsi_segment_sets,
        "all *DATABASE_FSI segment-set references exist",
        actual=missing_database_fsi_segment_sets or "ok",
    )
    add(
        "quality.ref.boundary_spc_node_sets",
        not missing_boundary_spc_node_sets,
        "all SPC boundaries reference existing node sets",
        actual=missing_boundary_spc_node_sets or "ok",
    )
    add(
        "quality.ref.nonreflecting_segment_sets",
        not missing_nonreflecting_segment_sets,
        "all 3D non-reflecting boundaries reference existing segment sets",
        actual=missing_nonreflecting_segment_sets or "ok",
    )
    add(
        "quality.ref.nonreflecting_2d_node_sets",
        not missing_nonreflecting_2d_node_sets,
        "all 2D non-reflecting boundaries reference existing node sets",
        actual=missing_nonreflecting_2d_node_sets or "ok",
    )
    add(
        "quality.ref.contact_parts",
        not missing_contact_parts,
        "all direct contact part references exist",
        actual=missing_contact_parts or "ok",
    )
    add(
        "quality.ref.contact_part_sets",
        not missing_contact_part_sets,
        "all contact part-set references exist",
        actual=missing_contact_part_sets or "ok",
    )
    add(
        "quality.ref.tied_contact_node_sets",
        not missing_tied_contact_node_sets,
        "all tied-node contacts reference existing non-empty node sets",
        actual=missing_tied_contact_node_sets or "ok",
    )
    add(
        "quality.ref.tied_contact_segment_sets",
        not missing_tied_contact_segment_sets,
        "all tied-node contacts reference existing non-empty segment sets",
        actual=missing_tied_contact_segment_sets or "ok",
    )
    add(
        "quality.ref.fsi_slave_parts",
        not missing_fsi_slave_parts,
        "all FSI slave part references exist",
        actual=missing_fsi_slave_parts or "ok",
    )
    add(
        "quality.ref.fsi_slave_segment_sets",
        not missing_fsi_slave_segment_sets,
        "all FSI slave segment-set references exist",
        actual=missing_fsi_slave_segment_sets or "ok",
    )
    add(
        "quality.ref.fsi_master_part_sets",
        not missing_fsi_master_part_sets,
        "all FSI master part-set references exist",
        actual=missing_fsi_master_part_sets or "ok",
    )
    add(
        "quality.ref.fsi_slave_segment_sets_nonempty",
        not empty_fsi_slave_segment_sets,
        "all referenced FSI slave segment sets contain segments",
        actual=empty_fsi_slave_segment_sets or "ok",
    )
    add(
        "quality.ref.fsi_master_part_sets_nonempty",
        not empty_fsi_master_part_sets,
        "all referenced FSI master part sets contain parts",
        actual=empty_fsi_master_part_sets or "ok",
    )
    add(
        "quality.ref.initial_detonation_parts",
        not missing_initial_detonation_parts,
        "all detonation references target existing ALE parts",
        actual=missing_initial_detonation_parts or "ok",
    )
    add(
        "quality.ref.ale_material_group_parts",
        not missing_ale_material_group_parts,
        "all ALE multi-material groups reference existing parts",
        actual=missing_ale_material_group_parts or "ok",
    )
    add(
        "quality.ref.ivfg_parts",
        not missing_ivfg_parts,
        "all initial-volume geometry part references exist",
        actual=missing_ivfg_parts or "ok",
    )
    add(
        "quality.ref.database_ale_solid_sets",
        not missing_database_ale_solid_sets,
        "all DATABASE_ALE outputs reference existing solid sets",
        actual=missing_database_ale_solid_sets or "ok",
    )
    add(
        "quality.ref.database_history_node_sets",
        not missing_history_node_sets,
        "all node-history outputs reference existing node sets",
        actual=missing_history_node_sets or "ok",
    )
    add(
        "quality.ref.database_history_shell_sets",
        not missing_history_shell_sets,
        "all shell-history outputs reference existing shell sets",
        actual=missing_history_shell_sets or "ok",
    )
    add(
        "quality.ref.database_history_solid_sets",
        not missing_history_solid_sets,
        "all solid-history outputs reference existing solid sets",
        actual=missing_history_solid_sets or "ok",
    )


def segment_set_has_members(
    model: KeywordModel,
    segment_set_id: int,
    visited: set[int] | None = None,
) -> bool:
    if model.segment_sets.get(segment_set_id):
        return True
    visited = set() if visited is None else set(visited)
    if segment_set_id in visited:
        return False
    visited.add(segment_set_id)
    return any(
        segment_set_has_members(model, member_id, visited)
        for member_id in model.segment_set_add_refs.get(segment_set_id, [])
        if member_id in model.segment_sets
    )


def check_element_quality(model: KeywordModel, spec: JSONDict, add: Callable[..., None]) -> JSONDict:
    shell_areas: list[float] = []
    zero_shells: list[int] = []
    shell_warp_angles: list[float] = []
    shell_aspect_ratios: list[float] = []
    checked_shell_ids: list[int] = []
    zero_normal_shells: list[int] = []
    zero_normal_samples: list[JSONDict] = []
    poor_shape_shells: list[int] = []
    shell_shape_ratios: list[float] = []
    nonfinite_shells: list[int] = []
    for element in model.shell_elements:
        required_nodes = shell_node_ids(element[2:6])
        if not all(nid in model.nodes for nid in required_nodes):
            continue
        coords = [model.nodes[nid] for nid in required_nodes]
        if not all(math.isfinite(value) for point in coords for value in point):
            nonfinite_shells.append(element[0])
            continue
        checked_shell_ids.append(element[0])
        area = quad_area(model.nodes, element[2:6])
        shell_areas.append(area)
        shell_warp_angles.append(quad_warpage_degrees(model.nodes, element[2:6]))
        shell_aspect_ratios.append(quad_aspect_ratio(model.nodes, element[2:6]))
        if area <= 1.0e-18:
            zero_shells.append(element[0])
        normal_size = norm(quad_normal(model.nodes, element[2:6]))
        span_squared = max(dot(sub(a, b), sub(a, b)) for a in coords for b in coords)
        if normal_size <= 1.0e-12 * span_squared:
            zero_normal_shells.append(element[0])
            if len(zero_normal_samples) < 10:
                zero_normal_samples.append({
                    "element_id": element[0], "part_id": element[1],
                    "node_ids": list(required_nodes),
                    "coordinates": [list(point) for point in coords],
                    "distinct_coordinate_count": len(set(coords)),
                })
        diagonal_squared = span_squared if len(coords) == 3 else max(
            dot(sub(coords[2], coords[0]), sub(coords[2], coords[0])),
            dot(sub(coords[3], coords[1]), sub(coords[3], coords[1])),
        )
        ratio = 0.5 * normal_size / diagonal_squared if diagonal_squared > 0 else 0.0
        shell_shape_ratios.append(ratio)
        if ratio < 0.1:
            poor_shape_shells.append(element[0])
    solid_volumes: list[float] = []
    inverted_solids: list[int] = []
    poor_jacobian_solids: list[int] = []
    solid_aspect_ratios: list[float] = []
    for element in model.solid_elements:
        if not all(nid in model.nodes for nid in element[2:10]):
            continue
        regular = axis_aligned_hexa_metrics(model.nodes, element[2:10])
        if regular is None:
            jacobians = hexa_gauss_jacobians(model.nodes, element[2:10])
            signed_volume = sum(jacobians)
            min_jacobian = min(jacobians) if jacobians else 0.0
            max_jacobian = max(jacobians) if jacobians else 0.0
            aspect_ratio = hexa_aspect_ratio(model.nodes, element[2:10])
        else:
            signed_volume, min_jacobian, max_jacobian, aspect_ratio = regular
        if min_jacobian <= 1.0e-24 or signed_volume <= 1.0e-24:
            inverted_solids.append(element[0])
        elif min_jacobian / max_jacobian < 0.2:
            poor_jacobian_solids.append(element[0])
        solid_volumes.append(max(signed_volume, 0.0))
        solid_aspect_ratios.append(aspect_ratio)
    if model.shell_elements:
        add(
            "quality.geometry.shell_finite_coordinates",
            not nonfinite_shells,
            "shell node coordinates are finite" if not nonfinite_shells else
            f"{len(nonfinite_shells)} shell elements contain NaN or infinite node coordinates",
            actual={"element_ids": nonfinite_shells},
        )
        add("quality.geometry.shell_area", not zero_shells, "shell element areas are positive", actual={"zero_area_elements": zero_shells, "min_area_m2": min(shell_areas) if shell_areas else 0.0})
        add(
            "quality.geometry.shell_zero_normal",
            not zero_normal_shells,
            "shell normals are nonzero" if not zero_normal_shells else
            f"{len(zero_normal_shells)} shell elements have zero or near-zero normals (LS-DYNA 30099); inspect coincident/collinear coordinates and crossed connectivity",
            actual={"element_ids": zero_normal_shells, "count": len(zero_normal_shells),
                    "solver_error_code": 30099, "relative_tolerance": 1.0e-12,
                    "samples": zero_normal_samples},
        )
        add(
            "quality.geometry.shell_shape_ratio",
            not poor_shape_shells,
            "shell projected area / longest diagonal squared is at least 0.1" if not poor_shape_shells else
            f"{len(poor_shape_shells)} shell elements have projected area / longest diagonal squared below 0.1 (LS-DYNA 21129 heuristic)",
            severity="warning",
            actual={"element_ids": poor_shape_shells, "count": len(poor_shape_shells),
                    "min_ratio": min(shell_shape_ratios) if shell_shape_ratios else None,
                    "threshold": 0.1, "solver_warning_code": 21129},
        )
        warped_shells = [
            checked_shell_ids[index]
            for index, angle in enumerate(shell_warp_angles)
            if angle > 15.0
        ]
        high_aspect_shells = [
            checked_shell_ids[index]
            for index, ratio in enumerate(shell_aspect_ratios)
            if ratio > 10.0
        ]
        add(
            "quality.geometry.shell_warpage",
            not warped_shells,
            "shell element warpage is within conservative limit",
            severity="warning",
            actual={"warped_elements": warped_shells, "max_warpage_deg": max(shell_warp_angles) if shell_warp_angles else 0.0},
        )
        add(
            "quality.geometry.shell_aspect_ratio",
            not high_aspect_shells,
            "shell element aspect ratios are within conservative limit",
            severity="warning",
            actual={"high_aspect_elements": high_aspect_shells, "max_aspect_ratio": max(shell_aspect_ratios) if shell_aspect_ratios else 0.0},
        )
        check_shell_normals(model, spec, add)
    if model.solid_elements:
        add(
            "quality.geometry.solid_volume",
            not inverted_solids,
            "solid element Gauss-point Jacobians and integrated volumes are positive",
            actual={"non_positive_volume_elements": inverted_solids, "min_volume_m3": min(solid_volumes) if solid_volumes else 0.0},
        )
        add(
            "quality.geometry.solid_jacobian_ratio",
            not poor_jacobian_solids,
            "solid element Jacobian ratios are within conservative limit",
            severity="warning",
            actual={"poor_jacobian_elements": poor_jacobian_solids},
        )
        high_aspect_solids = [
            model.solid_elements[index][0]
            for index, ratio in enumerate(solid_aspect_ratios)
            if ratio > 10.0
        ]
        add(
            "quality.geometry.solid_aspect_ratio",
            not high_aspect_solids,
            "solid element aspect ratios are within conservative limit",
            severity="warning",
            actual={"high_aspect_elements": high_aspect_solids, "max_aspect_ratio": max(solid_aspect_ratios) if solid_aspect_ratios else 0.0},
        )
    check_segment_topology(model, add)
    return {"shell_areas": shell_areas, "solid_volumes": solid_volumes}


def check_segment_topology(model: KeywordModel, add: Callable[..., None]) -> None:
    if not model.segment_loads and not model.segment_sets:
        return
    requested_segments = [
        *model.segment_loads,
        *[
            segment
            for segments in model.segment_sets.values()
            for segment in segments
        ],
    ]
    surface_faces = surface_face_map(model, requested_segments)
    shell_edges = shell_edge_keys(model)
    invalid_direct = [
        index + 1
        for index, segment in enumerate(model.segment_loads)
        if all(node_id in model.nodes for node_id in segment)
        and not segment_matches_element_topology(segment, surface_faces, shell_edges)
    ]
    invalid_sets: dict[int, list[int]] = {}
    for sid, segments in model.segment_sets.items():
        bad_indices = [
            index + 1
            for index, segment in enumerate(segments)
            if all(node_id in model.nodes for node_id in segment)
            and not segment_matches_element_topology(segment, surface_faces, shell_edges)
        ]
        if bad_indices:
            invalid_sets[sid] = bad_indices
    add(
        "quality.topology.load_segments_on_faces",
        not invalid_direct,
        "direct load segments match existing shell faces or element edges",
        actual=invalid_direct or "ok",
    )
    add(
        "quality.topology.segment_sets_on_faces",
        not invalid_sets,
        "segment-set entries match existing shell faces, solid faces, or 2D shell edges",
        actual=invalid_sets or "ok",
    )
    check_loaded_segment_orientation(model, surface_faces, add)


def check_loaded_segment_orientation(
    model: KeywordModel,
    surface_faces: dict[tuple[int, int, int, int], Segment],
    add: Callable[..., None],
) -> None:
    reversed_direct = [
        index + 1
        for index, segment in enumerate(model.segment_loads)
        if segment_orientation_dot(model, segment, surface_faces) < 0.0
    ]
    reversed_sets: dict[int, list[int]] = {}
    for sid in model.load_segment_set_ids:
        bad_indices = [
            index + 1
            for index, segment in enumerate(model.segment_sets.get(sid, []))
            if segment_orientation_dot(model, segment, surface_faces) < 0.0
        ]
        if bad_indices:
            reversed_sets[sid] = bad_indices
    add(
        "quality.geometry.load_segment_orientation",
        not reversed_direct and not reversed_sets,
        "loaded segment orientations match their source element faces",
        severity="warning",
        actual={"direct": reversed_direct, "sets": reversed_sets} if reversed_direct or reversed_sets else "ok",
    )


def check_shell_normals(model: KeywordModel, spec: JSONDict, add: Callable[..., None]) -> None:
    if spec.get("model_type") != "shell_plate":
        add("quality.geometry.shell_normals", True, "global shell normal consistency check skipped for non-planar shell model", actual=spec.get("model_type"))
        return
    normals = [
        (element[0], quad_normal(model.nodes, element[2:6]))
        for element in model.shell_elements
        if all(nid in model.nodes for nid in shell_node_ids(element[2:6]))
        and all(math.isfinite(value) for nid in shell_node_ids(element[2:6]) for value in model.nodes[nid])
    ]
    reference = next((normal for _, normal in normals if norm(normal) > 0.0), None)
    if reference is None:
        add("quality.geometry.shell_normals", False, "no valid shell normal could be computed")
        return
    inverted = [element_id for element_id, normal in normals if dot(reference, normal) < 0.0]
    add("quality.geometry.shell_normals", not inverted, "shell normals are consistently oriented", actual=inverted or "ok", severity="warning")


def check_orphans(model: KeywordModel, add: Callable[..., None]) -> None:
    referenced_nodes: set[int] = set()
    for element in all_elements(model):
        referenced_nodes.update(element[2:])
    orphan_nodes = sorted(set(model.nodes) - referenced_nodes)
    orphan_elements = sorted(element[0] for element in all_elements(model) if element[1] not in {part[0] for part in model.parts})
    add("quality.topology.orphan_nodes", not orphan_nodes, "no orphan nodes found", severity="warning", actual=orphan_nodes or "ok")
    add("quality.topology.orphan_elements", not orphan_elements, "no orphan elements found", actual=orphan_elements or "ok")


def check_shell_thickness_ratio(
    spec: JSONDict,
    model: KeywordModel,
    metadata: JSONDict,
    add: Callable[..., None],
) -> None:
    if not model.shell_elements:
        return
    component_ratios: list[float] = []
    for component in metadata.get("components", []):
        if not isinstance(component, dict) or component.get("element_family") != "shell":
            continue
        component_id = str(component.get("id", "unknown"))
        mesh_size = float(component.get("mesh_size_m", 0.0))
        thickness = float(component.get("shell_thickness_m", 0.0))
        if mesh_size <= 0.0 or thickness <= 0.0:
            add(
                f"quality.shell.component.{component_id}.thickness_mesh_ratio",
                True,
                "component shell thickness/mesh ratio check skipped; mesh size or thickness unavailable",
                actual="skipped",
            )
            continue
        ratio = thickness / mesh_size
        component_ratios.append(ratio)
        add(
            f"quality.shell.component.{component_id}.thickness_mesh_ratio",
            ratio <= 0.25,
            "component shell thickness is within a conservative mesh-size ratio"
            if ratio <= 0.25
            else "component shell thickness is large relative to mesh size",
            severity="warning",
            actual=ratio,
        )
    if component_ratios:
        ratio = max(component_ratios)
        add(
            "quality.shell.thickness_mesh_ratio",
            ratio <= 0.25,
            "shell thickness is within a conservative mesh-size ratio" if ratio <= 0.25 else "shell thickness is large relative to mesh size",
            severity="warning",
            actual=ratio,
        )
        return
    mesh_size = float((spec.get("mesh") or {}).get("size_m", 0.0))
    thicknesses = list(model.shell_section_thickness.values())
    if mesh_size <= 0.0 or not thicknesses:
        add("quality.shell.thickness_mesh_ratio", True, "shell thickness/mesh ratio check skipped; mesh size or thickness unavailable", actual="skipped")
        return
    ratio = max(thicknesses) / mesh_size
    add(
        "quality.shell.thickness_mesh_ratio",
        ratio <= 0.25,
        "shell thickness is within a conservative mesh-size ratio" if ratio <= 0.25 else "shell thickness is large relative to mesh size",
        severity="warning",
        actual=ratio,
    )


def check_assembly_component_constraints(metadata: JSONDict, add: Callable[..., None]) -> None:
    for component in metadata.get("components", []):
        if not isinstance(component, dict) or component.get("element_family") != "shell":
            continue
        component_id = str(component.get("id", "unknown"))
        node_ids = {int(value) for value in component.get("node_ids", [])}
        fixed_node_ids = {int(value) for value in component.get("fixed_node_ids", [])}
        fully_fixed = bool(node_ids) and node_ids.issubset(fixed_node_ids)
        add(
            f"quality.assembly.component.{component_id}.deformable_nodes",
            not fully_fixed,
            "shell component retains deformable nodes" if not fully_fixed else "shell component has every node fixed",
            actual={
                "node_count": len(node_ids),
                "fixed_node_count": len(node_ids & fixed_node_ids),
                "free_node_count": len(node_ids - fixed_node_ids),
            },
        )


def check_material_ranges(model: KeywordModel, add: Callable[..., None]) -> None:
    for mid, density in model.material_density.items():
        add(
            f"quality.material.{mid}.density_range",
            1.0 <= density <= 30000.0,
            "material density is within broad engineering range",
            severity="warning",
            actual=density,
        )
    for mid, (density, youngs, poisson) in model.elastic_materials.items():
        add(
            f"quality.material.{mid}.youngs_range",
            1.0e5 <= youngs <= 1.0e13,
            "elastic modulus is within broad engineering range",
            severity="warning",
            actual=youngs,
        )
        add(
            f"quality.material.{mid}.poisson_range",
            0.0 < poisson < 0.5,
            "Poisson ratio is within valid isotropic elastic range",
            severity="warning",
            actual=poisson,
        )
        add(
            f"quality.material.{mid}.wave_speed",
            density > 0.0 and youngs > 0.0,
            "elastic wave speed inputs are available",
            severity="warning",
            actual={"density_kg_per_m3": density, "youngs_pa": youngs},
        )


def estimate_mass_and_timestep(model: KeywordModel, spec: JSONDict, quality: JSONDict, add: Callable[..., None]) -> None:
    part_material = {pid: mid for pid, _, mid in model.parts if mid is not None}
    mass = 0.0
    for element in model.solid_elements:
        mid = part_material.get(element[1])
        density = model.material_density.get(mid or -1)
        if density is not None and all(nid in model.nodes for nid in element[2:10]):
            mass += density * max(sum(hexa_gauss_jacobians(model.nodes, element[2:10])), 0.0)
    for element in model.shell_elements:
        mid = part_material.get(element[1])
        density = model.material_density.get(mid or -1)
        thickness = first_shell_thickness(model, element[1])
        if density is not None and thickness is not None and all(nid in model.nodes for nid in shell_node_ids(element[2:6])):
            mass += density * quad_area(model.nodes, element[2:6]) * thickness
    finite_mass = math.isfinite(mass)
    add("quality.estimate.mass", finite_mass and mass > 0.0,
        "model mass estimate is available" if finite_mass else "model mass estimate unavailable due to nonfinite input geometry or properties",
        severity="warning", actual={"mass_kg": mass if finite_mass else None})

    stable_dt = estimate_stable_timestep(model, spec, quality)
    if stable_dt is None:
        add("quality.estimate.stable_timestep", False, "stable time step estimate skipped; wave speed unavailable", severity="warning", actual="skipped")
    else:
        add("quality.estimate.stable_timestep", True, "estimated explicit stable time step", actual={"stable_dt_s": stable_dt})


def estimate_stable_timestep(model: KeywordModel, spec: JSONDict, quality: JSONDict) -> float | None:
    wave_speeds = material_wave_speeds(model, spec)
    if not wave_speeds:
        return None
    lengths: list[float] = []
    lengths.extend(math.sqrt(area) for area in quality.get("shell_areas", []) if area > 0.0)
    lengths.extend(volume ** (1.0 / 3.0) for volume in quality.get("solid_volumes", []) if volume > 0.0)
    if not lengths:
        return None
    return min(lengths) / max(wave_speeds)


def material_wave_speeds(model: KeywordModel, spec: JSONDict) -> list[float]:
    speeds = [math.sqrt(youngs / density) for density, youngs, _ in model.elastic_materials.values() if density > 0.0 and youngs > 0.0]
    material = spec.get("material", {}) if isinstance(spec, dict) else {}
    density = float(material.get("density_kg_per_m3", 0.0) or 0.0)
    explicit_speed = float(material.get("wave_speed_m_per_s", 0.0) or 0.0)
    if explicit_speed > 0.0:
        speeds.append(explicit_speed)
    if density > 0.0:
        bulk = float(material.get("bulk_modulus_pa", 0.0) or 0.0)
        shear = float(material.get("shear_modulus_pa", 0.0) or 0.0)
        youngs = float(material.get("youngs_pa", 0.0) or 0.0)
        if bulk > 0.0 and shear > 0.0:
            speeds.append(math.sqrt((bulk + 4.0 * shear / 3.0) / density))
        elif shear > 0.0:
            speeds.append(math.sqrt(shear / density))
        elif youngs > 0.0:
            speeds.append(math.sqrt(youngs / density))
    return [speed for speed in speeds if math.isfinite(speed) and speed > 0.0]


def first_shell_thickness(model: KeywordModel, part_id: int) -> float | None:
    section_by_part = {pid: secid for pid, secid, _ in model.parts}
    section_id = section_by_part.get(part_id)
    if section_id is None:
        return None
    return model.shell_section_thickness.get(section_id)


def all_elements(model: KeywordModel) -> list[tuple[int, ...]]:
    return [*model.shell_elements, *model.solid_elements]


def quad_area(nodes: dict[int, tuple[float, float, float]], node_ids: tuple[int, int, int, int]) -> float:
    if is_triangle_shell(node_ids):
        p1, p2, p3 = [nodes[nid] for nid in triangle_node_ids(node_ids)]
        return 0.5 * norm(cross(sub(p2, p1), sub(p3, p1)))
    p1, p2, p3, p4 = [nodes[nid] for nid in node_ids]
    return 0.5 * norm(cross(sub(p2, p1), sub(p3, p1))) + 0.5 * norm(cross(sub(p3, p1), sub(p4, p1)))


def quad_normal(nodes: dict[int, tuple[float, float, float]], node_ids: tuple[int, int, int, int]) -> tuple[float, float, float]:
    if is_triangle_shell(node_ids):
        p1, p2, p3 = [nodes[nid] for nid in triangle_node_ids(node_ids)]
        return cross(sub(p2, p1), sub(p3, p1))
    p1, p2, p3, p4 = [nodes[nid] for nid in node_ids]
    n1 = cross(sub(p2, p1), sub(p3, p1))
    n2 = cross(sub(p3, p1), sub(p4, p1))
    return (n1[0] + n2[0], n1[1] + n2[1], n1[2] + n2[2])


def quad_warpage_degrees(nodes: dict[int, tuple[float, float, float]], node_ids: tuple[int, int, int, int]) -> float:
    if is_triangle_shell(node_ids):
        return 0.0
    p1, p2, p3, p4 = [nodes[nid] for nid in node_ids]
    normal_123 = cross(sub(p2, p1), sub(p3, p1))
    normal_134 = cross(sub(p3, p1), sub(p4, p1))
    n1 = norm(normal_123)
    n2 = norm(normal_134)
    if n1 <= 0.0 or n2 <= 0.0:
        return 180.0
    cosine = max(-1.0, min(1.0, dot(normal_123, normal_134) / (n1 * n2)))
    return math.degrees(math.acos(cosine))


def quad_aspect_ratio(nodes: dict[int, tuple[float, float, float]], node_ids: tuple[int, int, int, int]) -> float:
    if is_triangle_shell(node_ids):
        p1, p2, p3 = [nodes[nid] for nid in triangle_node_ids(node_ids)]
        lengths = [distance(p1, p2), distance(p2, p3), distance(p3, p1)]
        positive = [value for value in lengths if value > 0.0]
        if not positive:
            return math.inf
        return max(positive) / min(positive)
    p1, p2, p3, p4 = [nodes[nid] for nid in node_ids]
    lengths = [distance(p1, p2), distance(p2, p3), distance(p3, p4), distance(p4, p1)]
    positive = [value for value in lengths if value > 0.0]
    if not positive:
        return math.inf
    return max(positive) / min(positive)


def is_triangle_shell(node_ids: tuple[int, int, int, int]) -> bool:
    return node_ids[2] == node_ids[3] or node_ids[3] == 0


def triangle_node_ids(node_ids: tuple[int, int, int, int]) -> tuple[int, int, int]:
    return node_ids[0], node_ids[1], node_ids[2]


def shell_node_ids(node_ids: tuple[int, int, int, int]) -> tuple[int, ...]:
    return triangle_node_ids(node_ids) if is_triangle_shell(node_ids) else node_ids


def hexa_aspect_ratio(nodes: dict[int, tuple[float, float, float]], node_ids: tuple[int, ...]) -> float:
    coords = [nodes[nid] for nid in node_ids]
    edge_pairs = [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    ]
    lengths = [distance(coords[i], coords[j]) for i, j in edge_pairs]
    positive = [value for value in lengths if value > 0.0]
    if not positive:
        return math.inf
    return max(positive) / min(positive)


def axis_aligned_hexa_metrics(
    nodes: dict[int, tuple[float, float, float]],
    node_ids: tuple[int, ...],
) -> tuple[float, float, float, float] | None:
    coordinates = [nodes[nid] for nid in node_ids]
    x0, y0, z0 = coordinates[0]
    x1 = coordinates[1][0]
    y1 = coordinates[2][1]
    z1 = coordinates[4][2]
    expected = (
        (x0, y0, z0),
        (x1, y0, z0),
        (x1, y1, z0),
        (x0, y1, z0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    )
    if tuple(coordinates) != expected:
        return None
    dx = x1 - x0
    dy = y1 - y0
    dz = z1 - z0
    lengths = (dx, dy, dz)
    positive = [value for value in lengths if value > 0.0]
    if len(positive) != 3:
        return (dx * dy * dz, 0.0, 0.0, math.inf)
    volume = dx * dy * dz
    jacobian = volume / 8.0
    aspect_ratio = max(positive) / min(positive)
    return volume, jacobian, jacobian, aspect_ratio


def distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return norm(sub(a, b))


def hexa_gauss_jacobians(nodes: dict[int, tuple[float, float, float]], node_ids: tuple[int, ...]) -> list[float]:
    gauss = 1.0 / math.sqrt(3.0)
    return [
        hexa_jacobian_determinant(nodes, node_ids, xi, eta, zeta)
        for xi in (-gauss, gauss)
        for eta in (-gauss, gauss)
        for zeta in (-gauss, gauss)
    ]


def hexa_jacobian_determinant(
    nodes: dict[int, tuple[float, float, float]],
    node_ids: tuple[int, ...],
    xi: float,
    eta: float,
    zeta: float,
) -> float:
    coords = [nodes[nid] for nid in node_ids]
    signs = [
        (-1.0, -1.0, -1.0),
        (1.0, -1.0, -1.0),
        (1.0, 1.0, -1.0),
        (-1.0, 1.0, -1.0),
        (-1.0, -1.0, 1.0),
        (1.0, -1.0, 1.0),
        (1.0, 1.0, 1.0),
        (-1.0, 1.0, 1.0),
    ]
    dxi = [0.125 * sx * (1.0 + sy * eta) * (1.0 + sz * zeta) for sx, sy, sz in signs]
    deta = [0.125 * sy * (1.0 + sx * xi) * (1.0 + sz * zeta) for sx, sy, sz in signs]
    dzeta = [0.125 * sz * (1.0 + sx * xi) * (1.0 + sy * eta) for sx, sy, sz in signs]
    j1 = tuple(sum(coords[i][axis] * dxi[i] for i in range(8)) for axis in range(3))
    j2 = tuple(sum(coords[i][axis] * deta[i] for i in range(8)) for axis in range(3))
    j3 = tuple(sum(coords[i][axis] * dzeta[i] for i in range(8)) for axis in range(3))
    return dot(j1, cross(j2, j3))


def hexa_center_signed_volume(nodes: dict[int, tuple[float, float, float]], node_ids: tuple[int, ...]) -> float:
    return 8.0 * hexa_jacobian_determinant(nodes, node_ids, 0.0, 0.0, 0.0)


def surface_face_map(
    model: KeywordModel,
    requested_segments: list[Segment] | None = None,
) -> dict[tuple[int, ...], Segment]:
    requested_keys = (
        {canonical_segment(segment) for segment in requested_segments}
        if requested_segments is not None
        else None
    )
    faces: dict[tuple[int, ...], Segment] = {}
    solid_counts: dict[tuple[int, ...], int] = {}
    solid_refs: dict[tuple[int, ...], Segment] = {}
    for element in model.shell_elements:
        segment = (element[2], element[3], element[4], element[5])
        key = canonical_segment(segment)
        if requested_keys is None or key in requested_keys:
            faces[key] = segment
    for element in model.solid_elements:
        for segment in solid_face_segments(element):
            key = canonical_segment(segment)
            if requested_keys is not None and key not in requested_keys:
                continue
            solid_counts[key] = solid_counts.get(key, 0) + 1
            solid_refs[key] = segment
    for key, count in solid_counts.items():
        if count == 1:
            faces[key] = solid_refs[key]
    return faces


def shell_edge_keys(model: KeywordModel) -> set[tuple[int, ...]]:
    edges: set[tuple[int, ...]] = set()
    for element in model.shell_elements:
        n1, n2, n3, n4 = element[2:6]
        edges.update(
            {
                canonical_segment((n1, n2)),
                canonical_segment((n2, n3)),
                canonical_segment((n3, n4)),
                canonical_segment((n4, n1)),
            }
        )
    return edges


def segment_matches_element_topology(
    segment: Segment,
    surface_faces: dict[tuple[int, ...], Segment],
    shell_edges: set[tuple[int, ...]],
) -> bool:
    key = canonical_segment(segment)
    return key in shell_edges if len(segment) == 2 else key in surface_faces


def solid_face_segments(element: tuple[int, int, int, int, int, int, int, int, int, int]) -> list[Segment]:
    _, _, n1, n2, n3, n4, n5, n6, n7, n8 = element
    return [
        (n1, n4, n3, n2),
        (n5, n6, n7, n8),
        (n1, n2, n6, n5),
        (n2, n3, n7, n6),
        (n3, n4, n8, n7),
        (n4, n1, n5, n8),
    ]


def canonical_segment(segment: Segment) -> tuple[int, ...]:
    return tuple(sorted(segment))


def segment_orientation_dot(
    model: KeywordModel,
    segment: Segment,
    surface_faces: dict[tuple[int, ...], Segment],
) -> float:
    if len(segment) != 4:
        return 0.0
    key = canonical_segment(segment)
    reference = surface_faces.get(key)
    if reference is None:
        return 0.0
    if not all(node_id in model.nodes for node_id in segment) or not all(
        node_id in model.nodes for node_id in reference
    ):
        return 0.0
    return dot(quad_normal(model.nodes, segment), quad_normal(model.nodes, reference))


def sub(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def norm(a: tuple[float, float, float]) -> float:
    return math.sqrt(dot(a, a))
