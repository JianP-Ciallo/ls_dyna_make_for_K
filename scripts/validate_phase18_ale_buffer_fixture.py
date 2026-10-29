from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lsprepost_mcp.ale import (
    render_ale_air_cards,
    render_ale_multimaterial_setup,
    render_control_ale,
)
from lsprepost_mcp.lsdyna_runner import (
    execute_lsdyna_initialization_smoke,
    execute_lsdyna_run,
)
from lsprepost_mcp.refined_building.solver_blast.materials import (
    render_ale_vacuum_material,
)
from lsprepost_mcp.web.config_api import configured_lsdyna_exe, doctor_named_exe


EXPECTED_SOLVER_SHA256 = (
    "7a76b0c358a9d0822b8e37edaab9a461"
    "71d0376e45fe4f1f2b527974312ca991"
)
TERMINATION_TIME_S = 5.0e-5
NCPU = 1
MEMORY = "64m"
MCHECK_TIMEOUT_S = 120.0
SOLVE_TIMEOUT_S = 300.0

NX = 4
NY = 4
NZ = 6
ACTIVE_LAYERS = 4
BUFFER_LAYERS = 2
CELL_SIZE_M = 0.25
GRADE_ELEVATION_M = 0.0

SECTION_ID = 1
AIR_PART_ID = 1
BUFFER_PART_ID = 2
AIR_MATERIAL_ID = 1
AIR_EOS_ID = 1
VACUUM_MATERIAL_ID = 9
VACUUM_DENSITY_KG_PER_M3 = 1.225e-5
SIDE_SEGMENT_SET_ID = 101
TOP_SEGMENT_SET_ID = 102
BOTTOM_SEGMENT_SET_ID = 103
MAX_FIXTURE_DECK_BYTES = 1024 * 1024

_NUMBER_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_.])"
    r"[-+]?(?:nan|inf(?:inity)?|(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?)"
    r"(?![A-Za-z0-9_.])",
    flags=re.IGNORECASE,
)


def _fmt(value: float) -> str:
    return format(value, ".10g")


def _node_id(ix: int, iy: int, iz: int) -> int:
    return 1 + iz * (NY + 1) * (NX + 1) + iy * (NX + 1) + ix


def _coordinates() -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    x_values = tuple(index * CELL_SIZE_M for index in range(NX + 1))
    y_values = tuple(index * CELL_SIZE_M for index in range(NY + 1))
    z_min = GRADE_ELEVATION_M - BUFFER_LAYERS * CELL_SIZE_M
    z_values = tuple(z_min + index * CELL_SIZE_M for index in range(NZ + 1))
    return x_values, y_values, z_values


def _iter_node_rows() -> Iterable[str]:
    x_values, y_values, z_values = _coordinates()
    for iz, z_value in enumerate(z_values):
        for iy, y_value in enumerate(y_values):
            for ix, x_value in enumerate(x_values):
                yield (
                    f"{_node_id(ix, iy, iz)},"
                    f"{_fmt(x_value)},{_fmt(y_value)},{_fmt(z_value)}"
                )


def _element_nodes(ix: int, iy: int, iz: int) -> tuple[int, ...]:
    return (
        _node_id(ix, iy, iz),
        _node_id(ix + 1, iy, iz),
        _node_id(ix + 1, iy + 1, iz),
        _node_id(ix, iy + 1, iz),
        _node_id(ix, iy, iz + 1),
        _node_id(ix + 1, iy, iz + 1),
        _node_id(ix + 1, iy + 1, iz + 1),
        _node_id(ix, iy + 1, iz + 1),
    )


def _iter_element_rows() -> Iterable[str]:
    element_id = 1
    for iz in range(NZ):
        part_id = BUFFER_PART_ID if iz < BUFFER_LAYERS else AIR_PART_ID
        for iy in range(NY):
            for ix in range(NX):
                values = (element_id, part_id, *_element_nodes(ix, iy, iz))
                yield ",".join(str(value) for value in values)
                element_id += 1


def _side_segments() -> tuple[tuple[int, int, int, int], ...]:
    faces: list[tuple[int, int, int, int]] = []
    for iz in range(NZ):
        for iy in range(NY):
            faces.append(
                (
                    _node_id(0, iy, iz),
                    _node_id(0, iy, iz + 1),
                    _node_id(0, iy + 1, iz + 1),
                    _node_id(0, iy + 1, iz),
                )
            )
            faces.append(
                (
                    _node_id(NX, iy, iz),
                    _node_id(NX, iy + 1, iz),
                    _node_id(NX, iy + 1, iz + 1),
                    _node_id(NX, iy, iz + 1),
                )
            )
        for ix in range(NX):
            faces.append(
                (
                    _node_id(ix, 0, iz),
                    _node_id(ix + 1, 0, iz),
                    _node_id(ix + 1, 0, iz + 1),
                    _node_id(ix, 0, iz + 1),
                )
            )
            faces.append(
                (
                    _node_id(ix, NY, iz),
                    _node_id(ix, NY, iz + 1),
                    _node_id(ix + 1, NY, iz + 1),
                    _node_id(ix + 1, NY, iz),
                )
            )
    return tuple(faces)


def _top_segments() -> tuple[tuple[int, int, int, int], ...]:
    return tuple(
        (
            _node_id(ix, iy, NZ),
            _node_id(ix + 1, iy, NZ),
            _node_id(ix + 1, iy + 1, NZ),
            _node_id(ix, iy + 1, NZ),
        )
        for iy in range(NY)
        for ix in range(NX)
    )


def _bottom_segments() -> tuple[tuple[int, int, int, int], ...]:
    return tuple(
        (
            _node_id(ix, iy, 0),
            _node_id(ix, iy + 1, 0),
            _node_id(ix + 1, iy + 1, 0),
            _node_id(ix + 1, iy, 0),
        )
        for iy in range(NY)
        for ix in range(NX)
    )


def render_fixture_deck() -> tuple[str, ...]:
    lines = [
        "*KEYWORD",
        "*TITLE",
        "Phase 18 isolated R12 active-air and ALE-vacuum buffer fixture",
        "*CONTROL_TERMINATION",
        "$#  endtim",
        _fmt(TERMINATION_TIME_S),
        "*CONTROL_TIMESTEP",
        "$#  dtinit    tssfac",
        "0,0.67",
        "*CONTROL_ENERGY",
        "$#    hgen      rwen    slnten     rylen",
        "2,2,2,2",
    ]
    lines.extend(render_control_ale())
    lines.extend(
        [
            "*DATABASE_BINARY_D3PLOT",
            _fmt(TERMINATION_TIME_S / 5.0),
            "*DATABASE_GLSTAT",
            _fmt(TERMINATION_TIME_S / 5.0),
            "*DATABASE_MATSUM",
            _fmt(TERMINATION_TIME_S / 5.0),
        ]
    )
    lines.extend(
        render_ale_multimaterial_setup(
            section_id=SECTION_ID,
            material_part_ids=(AIR_PART_ID, BUFFER_PART_ID),
        )
    )
    lines.extend(
        [
            "*PART",
            "Fixture active air",
            f"{AIR_PART_ID},{SECTION_ID},{AIR_MATERIAL_ID},{AIR_EOS_ID},0,0,0,0",
            "*PART",
            "Fixture coupling buffer vacuum",
            f"{BUFFER_PART_ID},{SECTION_ID},{VACUUM_MATERIAL_ID},0,0,0,0,0",
        ]
    )
    lines.extend(
        render_ale_air_cards(
            material_id=AIR_MATERIAL_ID,
            eos_id=AIR_EOS_ID,
        )
    )
    lines.extend(render_ale_vacuum_material(VACUUM_MATERIAL_ID))
    lines.extend(["*NODE", "$# nid,x,y,z"])
    lines.extend(_iter_node_rows())
    lines.extend(["*ELEMENT_SOLID", "$# eid,pid,n1,n2,n3,n4,n5,n6,n7,n8"])
    lines.extend(_iter_element_rows())
    lines.extend(
        [
            "*SET_SEGMENT_TITLE",
            "Fixture lateral non-reflecting boundary",
            f"{SIDE_SEGMENT_SET_ID},0,0,0,0",
        ]
    )
    lines.extend(",".join(str(value) for value in face) for face in _side_segments())
    lines.extend(
        [
            "*SET_SEGMENT_TITLE",
            "Fixture top non-reflecting boundary",
            f"{TOP_SEGMENT_SET_ID},0,0,0,0",
        ]
    )
    lines.extend(",".join(str(value) for value in face) for face in _top_segments())
    lines.extend(
        [
            "*SET_SEGMENT_TITLE",
            "Fixture bottom no-flow-normal boundary",
            f"{BOTTOM_SEGMENT_SET_ID},0,0,0,0",
        ]
    )
    lines.extend(",".join(str(value) for value in face) for face in _bottom_segments())
    lines.extend(
        [
            "*BOUNDARY_NON_REFLECTING",
            "$# ssid,ad,as",
            f"{SIDE_SEGMENT_SET_ID},0,0",
            "*BOUNDARY_NON_REFLECTING",
            "$# ssid,ad,as",
            f"{TOP_SEGMENT_SET_ID},0,0",
            "*ALE_ESSENTIAL_BOUNDARY",
            "$# ssid,idtype,ictype,alecomp",
            f"{BOTTOM_SEGMENT_SET_ID},2,2,0",
            "*END",
        ]
    )
    return tuple(lines)


def _keyword_blocks(
    lines: tuple[str, ...],
    keyword: str,
) -> tuple[tuple[str, ...], ...]:
    blocks: list[tuple[str, ...]] = []
    for marker, line in enumerate(lines):
        if line != keyword:
            continue
        rows: list[str] = []
        cursor = marker + 1
        while cursor < len(lines) and not lines[cursor].startswith("*"):
            value = lines[cursor].strip()
            if value and not value.startswith("$"):
                rows.append(value)
            cursor += 1
        blocks.append(tuple(rows))
    return tuple(blocks)


def _csv_ints(row: str) -> tuple[int, ...]:
    return tuple(int(value.strip()) for value in row.split(",") if value.strip())


def _strict_csv_ints(row: str, field_count: int) -> tuple[int, ...]:
    fields = tuple(value.strip() for value in row.split(","))
    if len(fields) != field_count or any(not value for value in fields):
        raise ValueError(f"expected exactly {field_count} integer fields")
    return tuple(int(value) for value in fields)


def _oriented_face_key(face: tuple[int, ...]) -> tuple[int, ...]:
    if len(face) != 4 or len(set(face)) != 4:
        raise ValueError("segment face must contain four distinct node ids")
    rotations = tuple(face[index:] + face[:index] for index in range(len(face)))
    return min(rotations)


def _complete_oriented_face_set(
    actual: tuple[tuple[int, ...], ...],
    expected: tuple[tuple[int, int, int, int], ...],
) -> bool:
    try:
        actual_keys = tuple(_oriented_face_key(face) for face in actual)
        expected_keys = tuple(_oriented_face_key(face) for face in expected)
    except ValueError:
        return False
    return bool(
        len(actual_keys) == len(expected_keys)
        and len(set(actual_keys)) == len(actual_keys)
        and set(actual_keys) == set(expected_keys)
    )


def _face_normal(
    face: tuple[int, ...],
    nodes: Mapping[int, tuple[float, float, float]],
) -> tuple[float, float, float] | None:
    if len(face) != 4 or any(node_id not in nodes for node_id in face):
        return None
    first, second, third = (nodes[node_id] for node_id in face[:3])
    edge_1 = tuple(second[index] - first[index] for index in range(3))
    edge_2 = tuple(third[index] - first[index] for index in range(3))
    return (
        edge_1[1] * edge_2[2] - edge_1[2] * edge_2[1],
        edge_1[2] * edge_2[0] - edge_1[0] * edge_2[2],
        edge_1[0] * edge_2[1] - edge_1[1] * edge_2[0],
    )


def _face_has_outward_winding(
    face: tuple[int, ...],
    nodes: Mapping[int, tuple[float, float, float]],
    outward: tuple[float, float, float],
) -> bool:
    normal = _face_normal(face, nodes)
    if normal is None:
        return False
    magnitude = math.sqrt(sum(component * component for component in normal))
    signed_magnitude = sum(
        normal[index] * outward[index] for index in range(3)
    )
    return bool(
        magnitude > 1.0e-15
        and signed_magnitude > magnitude * (1.0 - 1.0e-12)
    )


def _empty_static_audit() -> dict[str, object]:
    return {
        "ok": False,
        "grid_cells": [0, 0, 0],
        "node_count": 0,
        "active_air_element_count": 0,
        "buffer_element_count": 0,
        "side_nonreflecting_segment_count": 0,
        "top_nonreflecting_segment_count": 0,
        "bottom_nonreflecting_segment_count": 0,
        "bottom_no_flow_segment_count": 0,
        "bottom_closed_node_count": 0,
        "vacuum_density_kg_per_m3": None,
        "vacuum_material_accepted": False,
    }


def audit_fixture_deck(model_path: Path) -> dict[str, object]:
    path = Path(model_path)
    try:
        if path.is_symlink() or not path.is_file():
            return _empty_static_audit()
        with path.open("rb") as handle:
            payload = handle.read(MAX_FIXTURE_DECK_BYTES + 1)
    except OSError:
        return _empty_static_audit()
    if not payload or len(payload) > MAX_FIXTURE_DECK_BYTES:
        return _empty_static_audit()
    try:
        text = payload.decode("utf-8")
    except UnicodeError:
        return _empty_static_audit()
    if "\x00" in text:
        return _empty_static_audit()

    lines = tuple(text.splitlines())
    expected_node_count = (NX + 1) * (NY + 1) * (NZ + 1)
    expected_element_count = NX * NY * NZ
    node_blocks = _keyword_blocks(lines, "*NODE")
    element_blocks = _keyword_blocks(lines, "*ELEMENT_SOLID")
    if (
        len(node_blocks) != 1
        or len(node_blocks[0]) != expected_node_count
        or len(element_blocks) != 1
        or len(element_blocks[0]) != expected_element_count
    ):
        return _empty_static_audit()

    nodes: dict[int, tuple[float, float, float]] = {}
    try:
        for row in node_blocks[0]:
            values = tuple(value.strip() for value in row.split(","))
            if len(values) != 4 or any(not value for value in values):
                return _empty_static_audit()
            node_id = int(values[0])
            coordinates = tuple(float(value) for value in values[1:])
            if (
                node_id <= 0
                or node_id in nodes
                or len(coordinates) != 3
                or not all(math.isfinite(value) for value in coordinates)
            ):
                return _empty_static_audit()
            nodes[node_id] = coordinates  # type: ignore[assignment]
        elements = tuple(
            _strict_csv_ints(row, 10) for row in element_blocks[0]
        )
    except (TypeError, ValueError):
        return _empty_static_audit()

    x_coordinates, y_coordinates, z_coordinates = _coordinates()
    expected_nodes = {
        _node_id(ix, iy, iz): (
            x_coordinates[ix],
            y_coordinates[iy],
            z_coordinates[iz],
        )
        for iz in range(NZ + 1)
        for iy in range(NY + 1)
        for ix in range(NX + 1)
    }
    node_geometry_exact = bool(
        set(nodes) == set(expected_nodes)
        and all(
            all(
                math.isclose(
                    nodes[node_id][axis],
                    expected[axis],
                    rel_tol=0.0,
                    abs_tol=1.0e-12,
                )
                for axis in range(3)
            )
            for node_id, expected in expected_nodes.items()
        )
    )

    expected_cell_parts = {
        frozenset(_element_nodes(ix, iy, iz)): (
            BUFFER_PART_ID if iz < BUFFER_LAYERS else AIR_PART_ID
        )
        for iz in range(NZ)
        for iy in range(NY)
        for ix in range(NX)
    }
    element_ids: set[int] = set()
    element_cells: set[frozenset[int]] = set()
    element_topology_exact = True
    for row in elements:
        element_id, part_id, *node_ids = row
        cell = frozenset(node_ids)
        expected_part_id = expected_cell_parts.get(cell)
        if (
            element_id <= 0
            or element_id in element_ids
            or len(cell) != 8
            or any(node_id not in nodes for node_id in node_ids)
            or cell in element_cells
            or expected_part_id is None
            or part_id != expected_part_id
        ):
            element_topology_exact = False
            break
        element_ids.add(element_id)
        element_cells.add(cell)
    element_topology_exact = bool(
        element_topology_exact
        and element_ids == set(range(1, expected_element_count + 1))
        and element_cells == set(expected_cell_parts)
    )

    active_count = sum(row[1] == AIR_PART_ID for row in elements)
    buffer_count = sum(row[1] == BUFFER_PART_ID for row in elements)
    x_values = {value[0] for value in nodes.values()}
    y_values = {value[1] for value in nodes.values()}
    z_values = {value[2] for value in nodes.values()}
    grid_cells = [
        max(0, len(x_values) - 1),
        max(0, len(y_values) - 1),
        max(0, len(z_values) - 1),
    ]
    x_min = min(x_values)
    x_max = max(x_values)
    y_min = min(y_values)
    y_max = max(y_values)
    z_min = min(z_values)
    z_max = max(z_values)

    expected_part_rows = {
        AIR_PART_ID: (
            AIR_PART_ID,
            SECTION_ID,
            AIR_MATERIAL_ID,
            AIR_EOS_ID,
            0,
            0,
            0,
            0,
        ),
        BUFFER_PART_ID: (
            BUFFER_PART_ID,
            SECTION_ID,
            VACUUM_MATERIAL_ID,
            0,
            0,
            0,
            0,
            0,
        ),
    }
    expected_part_titles = {
        AIR_PART_ID: "Fixture active air",
        BUFFER_PART_ID: "Fixture coupling buffer vacuum",
    }
    part_identity_exact = False
    try:
        part_blocks = _keyword_blocks(lines, "*PART")
        parsed_part_rows: dict[int, tuple[int, ...]] = {}
        parsed_part_titles: dict[int, str] = {}
        if len(part_blocks) != len(expected_part_rows):
            raise ValueError("fixture must contain exactly two PART blocks")
        for block in part_blocks:
            if len(block) != 2:
                raise ValueError("fixture PART must contain one title and one row")
            part_row = _strict_csv_ints(block[1], 8)
            part_id = part_row[0]
            if part_id in parsed_part_rows:
                raise ValueError("duplicate fixture PART id")
            parsed_part_rows[part_id] = part_row
            parsed_part_titles[part_id] = block[0]
        part_identity_exact = bool(
            parsed_part_rows == expected_part_rows
            and parsed_part_titles == expected_part_titles
        )
    except (IndexError, ValueError):
        part_identity_exact = False

    multimaterial_group_exact = False
    try:
        multimaterial_blocks = _keyword_blocks(lines, "*ALE_MULTI-MATERIAL_GROUP")
        if len(multimaterial_blocks) == 1:
            multimaterial_rows = tuple(
                _strict_csv_ints(row, 2) for row in multimaterial_blocks[0]
            )
            multimaterial_group_exact = bool(
                len(multimaterial_rows) == 2
                and set(multimaterial_rows)
                == {(AIR_PART_ID, 1), (BUFFER_PART_ID, 1)}
            )
    except ValueError:
        multimaterial_group_exact = False

    segment_sets: dict[int, tuple[tuple[int, ...], ...]] = {}
    segment_sets_exact = False
    expected_segment_titles = {
        SIDE_SEGMENT_SET_ID: "Fixture lateral non-reflecting boundary",
        TOP_SEGMENT_SET_ID: "Fixture top non-reflecting boundary",
        BOTTOM_SEGMENT_SET_ID: "Fixture bottom no-flow-normal boundary",
    }
    try:
        segment_blocks = _keyword_blocks(lines, "*SET_SEGMENT_TITLE")
        segment_titles: dict[int, str] = {}
        if len(segment_blocks) != len(expected_segment_titles):
            raise ValueError("fixture must contain exactly three segment sets")
        for block in segment_blocks:
            if len(block) < 2:
                raise ValueError("segment set is missing its id row")
            header = _strict_csv_ints(block[1], 5)
            set_id = header[0]
            if set_id in segment_sets or header != (set_id, 0, 0, 0, 0):
                raise ValueError("invalid or duplicate segment set header")
            faces = tuple(_strict_csv_ints(row, 4) for row in block[2:])
            segment_sets[set_id] = faces
            segment_titles[set_id] = block[0]
        segment_sets_exact = bool(
            set(segment_sets) == set(expected_segment_titles)
            and segment_titles == expected_segment_titles
        )
    except (IndexError, ValueError):
        segment_sets = {}
        segment_sets_exact = False

    side_faces = segment_sets.get(SIDE_SEGMENT_SET_ID, ())
    top_faces = segment_sets.get(TOP_SEGMENT_SET_ID, ())
    bottom_faces = segment_sets.get(BOTTOM_SEGMENT_SET_ID, ())

    def face_on_coordinate(
        face: tuple[int, ...],
        axis: int,
        coordinate: float,
    ) -> bool:
        return len(face) == 4 and all(
            node_id in nodes
            and math.isclose(
                nodes[node_id][axis],
                coordinate,
                rel_tol=0.0,
                abs_tol=1.0e-12,
            )
            for node_id in face
        )

    def side_face_has_outward_winding(face: tuple[int, ...]) -> bool:
        outward_directions = tuple(
            outward
            for axis, coordinate, outward in (
                (0, x_min, (-1.0, 0.0, 0.0)),
                (0, x_max, (1.0, 0.0, 0.0)),
                (1, y_min, (0.0, -1.0, 0.0)),
                (1, y_max, (0.0, 1.0, 0.0)),
            )
            if face_on_coordinate(face, axis, coordinate)
        )
        return bool(
            len(outward_directions) == 1
            and _face_has_outward_winding(face, nodes, outward_directions[0])
        )

    side_faces_valid = bool(
        segment_sets_exact
        and _complete_oriented_face_set(side_faces, _side_segments())
        and all(side_face_has_outward_winding(face) for face in side_faces)
    )
    top_faces_valid = bool(
        segment_sets_exact
        and _complete_oriented_face_set(top_faces, _top_segments())
        and all(face_on_coordinate(face, 2, z_max) for face in top_faces)
        and all(
            _face_has_outward_winding(face, nodes, (0.0, 0.0, 1.0))
            for face in top_faces
        )
    )
    bottom_faces_valid = bool(
        segment_sets_exact
        and _complete_oriented_face_set(bottom_faces, _bottom_segments())
        and all(face_on_coordinate(face, 2, z_min) for face in bottom_faces)
        and all(
            _face_has_outward_winding(face, nodes, (0.0, 0.0, -1.0))
            for face in bottom_faces
        )
    )

    nonreflecting_ids: tuple[int, ...] = ()
    exact_nonreflecting_sets = False
    try:
        nonreflecting_blocks = _keyword_blocks(lines, "*BOUNDARY_NON_REFLECTING")
        if len(nonreflecting_blocks) == 2 and all(
            len(block) == 1 for block in nonreflecting_blocks
        ):
            nonreflecting_rows = tuple(
                _strict_csv_ints(block[0], 3) for block in nonreflecting_blocks
            )
            nonreflecting_ids = tuple(row[0] for row in nonreflecting_rows)
            exact_nonreflecting_sets = bool(
                len(set(nonreflecting_ids)) == 2
                and set(nonreflecting_rows)
                == {
                    (SIDE_SEGMENT_SET_ID, 0, 0),
                    (TOP_SEGMENT_SET_ID, 0, 0),
                }
            )
    except ValueError:
        nonreflecting_ids = ()
        exact_nonreflecting_sets = False

    bottom_nonreflecting_count = sum(
        face_on_coordinate(face, 2, z_min)
        for set_id in nonreflecting_ids
        for face in segment_sets.get(set_id, ())
    )
    bottom_node_ids = {node_id for face in bottom_faces for node_id in face}
    essential_rows: tuple[tuple[int, ...], ...] = ()
    try:
        essential_blocks = _keyword_blocks(lines, "*ALE_ESSENTIAL_BOUNDARY")
        if len(essential_blocks) == 1 and len(essential_blocks[0]) == 1:
            essential_rows = (
                _strict_csv_ints(essential_blocks[0][0], 4),
            )
    except ValueError:
        essential_rows = ()
    expected_bottom_node_ids = {
        node_id
        for node_id, coordinate in nodes.items()
        if math.isclose(
            coordinate[2],
            z_min,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        )
    }

    vacuum_blocks = _keyword_blocks(lines, "*MAT_ALE_VACUUM_TITLE")
    rendered_vacuum_card = render_ale_vacuum_material(VACUUM_MATERIAL_ID)
    expected_vacuum_card = (
        "*MAT_ALE_VACUUM_TITLE",
        "Visible coupling buffer vacuum",
        f"{VACUUM_MATERIAL_ID},1.225e-05",
    )
    expected_vacuum_rows = expected_vacuum_card[1:]
    vacuum_density: float | None = None
    if len(vacuum_blocks) == 1 and len(vacuum_blocks[0]) == 2:
        try:
            vacuum_density_fields = tuple(
                value.strip() for value in vacuum_blocks[0][1].split(",")
            )
            if len(vacuum_density_fields) == 2 and all(vacuum_density_fields):
                vacuum_density = float(vacuum_density_fields[1])
        except ValueError:
            vacuum_density = None
    vacuum_material_accepted = bool(
        rendered_vacuum_card == expected_vacuum_card
        and len(vacuum_blocks) == 1
        and vacuum_blocks[0] == expected_vacuum_rows
        and vacuum_density is not None
        and math.isclose(
            vacuum_density,
            VACUUM_DENSITY_KG_PER_M3,
            rel_tol=0.0,
            abs_tol=1.0e-15,
        )
    )

    side_count = len(side_faces)
    top_count = len(top_faces)
    bottom_no_flow_count = len(bottom_faces)
    bottom_node_count = len(bottom_node_ids)
    ok = bool(
        grid_cells == [NX, NY, NZ]
        and len(nodes) == expected_node_count
        and node_geometry_exact
        and len(elements) == expected_element_count
        and element_topology_exact
        and active_count == NX * NY * ACTIVE_LAYERS
        and buffer_count == NX * NY * BUFFER_LAYERS
        and active_count + buffer_count == len(elements)
        and part_identity_exact
        and multimaterial_group_exact
        and side_count == 2 * NY * NZ + 2 * NX * NZ
        and top_count == NX * NY
        and bottom_nonreflecting_count == 0
        and bottom_no_flow_count == NX * NY
        and bottom_node_count == (NX + 1) * (NY + 1)
        and bottom_node_ids == expected_bottom_node_ids
        and side_faces_valid
        and top_faces_valid
        and bottom_faces_valid
        and essential_rows == ((BOTTOM_SEGMENT_SET_ID, 2, 2, 0),)
        and not _keyword_blocks(lines, "*BOUNDARY_SPC_SET")
        and exact_nonreflecting_sets
        and vacuum_material_accepted
    )
    return {
        "ok": ok,
        "grid_cells": grid_cells,
        "node_count": len(nodes),
        "active_air_element_count": active_count,
        "buffer_element_count": buffer_count,
        "side_nonreflecting_segment_count": side_count,
        "top_nonreflecting_segment_count": top_count,
        "bottom_nonreflecting_segment_count": bottom_nonreflecting_count,
        "bottom_no_flow_segment_count": bottom_no_flow_count,
        "bottom_closed_node_count": bottom_node_count,
        "vacuum_density_kg_per_m3": vacuum_density,
        "vacuum_material_accepted": vacuum_material_accepted,
    }

def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_text_atomic(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json_atomic(path: Path, value: object) -> None:
    _write_text_atomic(
        path,
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
    )


def _validated_empty_output_root(output_root: Path) -> Path:
    root = Path(output_root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("output root must be an existing real empty directory")
    root = root.resolve()
    try:
        first_entry = next(root.iterdir(), None)
    except OSError as exc:
        raise ValueError(
            "output root must be an existing real empty directory"
        ) from exc
    if first_entry is not None:
        raise ValueError("output root must be an existing real empty directory")
    return root


def _empty_mcheck_result() -> dict[str, object]:
    return {
        "started": False,
        "ok": False,
        "status": "not_started",
        "returncode": None,
        "smoke_id": None,
        "smoke_dir": None,
        "input_sha256": None,
        "solver_sha256": None,
        "command_has_mcheck": False,
        "maximum_cycle": 0,
        "solver_cycles_completed": False,
        "memory_check_completed": False,
        "terminated_normally": False,
        "keyword_errors": [],
        "skip_reason": None,
    }


def _empty_solve_result() -> dict[str, object]:
    return {
        "started": False,
        "ok": False,
        "status": "not_started",
        "returncode": None,
        "run_id": None,
        "run_dir": None,
        "input_sha256": None,
        "solver_sha256": None,
        "normal_termination": False,
        "termination_time_reached": False,
        "final_problem_time_s": None,
        "finite_solver_evaluation": False,
        "glstat_finite": False,
        "matsum_finite": False,
        "glstat_history": {"ok": False, "files": [], "numeric_value_count": 0},
        "matsum_history": {"ok": False, "files": [], "numeric_value_count": 0},
        "required_outputs_present": False,
        "skip_reason": None,
    }


def _new_result(root: Path) -> dict[str, Any]:
    return {
        "schema_version": "phase18.ale_buffer_fixture_result@1",
        "all_ok": False,
        "output_root": str(root),
        "model": {
            "path": str(root / "model.k"),
            "sha256": None,
            "size_bytes": None,
            "model_json_path": str(root / "model.json"),
            "model_json_sha256": None,
            "termination_time_s": TERMINATION_TIME_S,
            "grid_cells": [NX, NY, NZ],
            "active_layers": ACTIVE_LAYERS,
            "buffer_layers": BUFFER_LAYERS,
            "vacuum_renderer": (
                "lsprepost_mcp.refined_building.solver_blast.materials."
                "render_ale_vacuum_material"
            ),
        },
        "static_audit": _empty_static_audit(),
        "solver_identity": {
            "ok": False,
            "source": None,
            "path": None,
            "expected_sha256": EXPECTED_SOLVER_SHA256,
            "actual_sha256": None,
            "doctor": None,
        },
        "mcheck": _empty_mcheck_result(),
        "solve": _empty_solve_result(),
        "failure": None,
        "engineering_validated": False,
        "solver_ready": False,
        "requires_project_review": True,
    }


def _record_failure(
    result: dict[str, Any],
    *,
    stage: str,
    error: Exception | None = None,
    message: str | None = None,
) -> None:
    result["all_ok"] = False
    result["failure"] = {
        "stage": stage,
        "type": type(error).__name__ if error is not None else "FixtureGateError",
        "message": str(error) if error is not None else str(message),
    }
    if result["mcheck"]["started"] is False:
        result["mcheck"]["skip_reason"] = f"{stage}_failed"
    if result["solve"]["started"] is False:
        result["solve"]["skip_reason"] = f"{stage}_failed"


def _doctor_payload(doctor: object) -> dict[str, object]:
    converter = getattr(doctor, "to_json", None)
    if callable(converter):
        payload = converter()
        if isinstance(payload, dict):
            return payload
    return {
        field: getattr(doctor, field, None)
        for field in ("exe", "exists", "is_file", "suffix_ok", "name_ok", "ok")
    }


def _resolve_solver_identity(
    result: dict[str, Any],
    solver_exe: Path | None,
) -> Path | None:
    source = "cli" if solver_exe is not None else "configured"
    candidate = Path(solver_exe) if solver_exe is not None else configured_lsdyna_exe()
    result["solver_identity"]["source"] = source
    if candidate is None:
        _record_failure(
            result,
            stage="solver_identity",
            message="LS-DYNA is not configured and --solver-exe was not provided",
        )
        return None

    doctor = doctor_named_exe(candidate, ("lsdyna",), True)
    result["solver_identity"]["doctor"] = _doctor_payload(doctor)
    result["solver_identity"]["path"] = str(candidate)
    if getattr(doctor, "ok", False) is not True:
        _record_failure(
            result,
            stage="solver_identity",
            message="LS-DYNA executable failed doctor checks",
        )
        return None

    solver = candidate.resolve()
    actual_sha256 = _sha256_file(solver)
    result["solver_identity"].update(
        {
            "path": str(solver),
            "actual_sha256": actual_sha256,
            "ok": actual_sha256 == EXPECTED_SOLVER_SHA256,
        }
    )
    if actual_sha256 != EXPECTED_SOLVER_SHA256:
        _record_failure(
            result,
            stage="solver_identity",
            message=(
                "LS-DYNA executable SHA-256 does not match the reviewed "
                f"R12 identity {EXPECTED_SOLVER_SHA256}"
            ),
        )
        return None
    return solver


def _zero_returncode(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == 0


def _summarize_mcheck(
    record: object,
    *,
    model_sha256: str,
    solver_sha256: str,
) -> dict[str, object]:
    if not isinstance(record, Mapping):
        raise TypeError("mcheck runner result must be a mapping")
    evidence = record.get("evidence")
    if not isinstance(evidence, Mapping):
        evidence = {}
    solver = record.get("solver")
    if not isinstance(solver, Mapping):
        solver = {}
    command = record.get("command")
    command_has_mcheck = bool(
        isinstance(command, list)
        and all(isinstance(value, str) for value in command)
        and "mcheck=y" in command
    )
    keyword_errors = evidence.get("keyword_errors")
    if not isinstance(keyword_errors, list):
        keyword_errors = ["malformed keyword_errors evidence"]
    maximum_cycle = evidence.get("maximum_cycle")
    maximum_cycle_ok = bool(
        isinstance(maximum_cycle, int)
        and not isinstance(maximum_cycle, bool)
        and 1 <= maximum_cycle <= 10
    )
    input_sha256 = record.get("input_sha256")
    stage_solver_sha256 = solver.get("sha256")
    ok = bool(
        record.get("ok") is True
        and record.get("status") == "completed"
        and _zero_returncode(record.get("returncode"))
        and input_sha256 == model_sha256
        and stage_solver_sha256 == solver_sha256
        and command_has_mcheck
        and evidence.get("ok") is True
        and maximum_cycle_ok
        and evidence.get("solver_cycles_completed") is True
        and evidence.get("memory_check_completed") is True
        and evidence.get("terminated_normally") is True
        and not keyword_errors
    )
    return {
        "started": True,
        "ok": ok,
        "status": record.get("status"),
        "returncode": record.get("returncode"),
        "smoke_id": record.get("smoke_id"),
        "smoke_dir": record.get("smoke_dir"),
        "input_sha256": input_sha256,
        "solver_sha256": stage_solver_sha256,
        "command_has_mcheck": command_has_mcheck,
        "maximum_cycle": maximum_cycle if isinstance(maximum_cycle, int) else None,
        "solver_cycles_completed": evidence.get("solver_cycles_completed") is True,
        "memory_check_completed": evidence.get("memory_check_completed") is True,
        "terminated_normally": evidence.get("terminated_normally") is True,
        "keyword_errors": [
            str(value) for value in keyword_errors[:20]
        ],
        "skip_reason": None,
    }


def _finite_history(run_dir: Path, prefix: str) -> dict[str, object]:
    files = tuple(
        sorted(
            (
                path
                for path in run_dir.iterdir()
                if path.is_file()
                and not path.is_symlink()
                and path.name.lower().startswith(prefix)
            ),
            key=lambda path: path.name.lower(),
        )
    )
    numeric_value_count = 0
    finite = bool(files)
    file_rows: list[dict[str, object]] = []
    for path in files:
        size_bytes = path.stat().st_size
        if size_bytes <= 0 or size_bytes > 64 * 1024 * 1024:
            finite = False
            file_rows.append(
                {
                    "path": str(path),
                    "size_bytes": size_bytes,
                    "finite": False,
                }
            )
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        tokens = _NUMBER_TOKEN.findall(text)
        values = [
            float(token.replace("D", "E").replace("d", "e"))
            for token in tokens
        ]
        file_finite = bool(values) and all(math.isfinite(value) for value in values)
        numeric_value_count += len(values)
        finite = finite and file_finite
        file_rows.append(
            {
                "path": str(path),
                "size_bytes": size_bytes,
                "finite": file_finite,
                "numeric_value_count": len(values),
            }
        )
    return {
        "ok": bool(finite and numeric_value_count > 0),
        "files": file_rows,
        "numeric_value_count": numeric_value_count,
    }


def _summarize_solve(
    record: object,
    *,
    root: Path,
    model_sha256: str,
    model_json_sha256: str,
    solver_sha256: str,
) -> dict[str, object]:
    if not isinstance(record, Mapping):
        raise TypeError("solve runner result must be a mapping")
    run_dir_raw = record.get("run_dir")
    if not isinstance(run_dir_raw, str):
        raise ValueError("solve runner result has no run_dir")
    run_dir_path = Path(run_dir_raw)
    if run_dir_path.is_symlink() or not run_dir_path.is_dir():
        raise ValueError("solve runner run_dir must be a real directory")
    run_dir = run_dir_path.resolve()
    if run_dir.parent != (root / "solver_runs").resolve():
        raise ValueError("solve runner escaped the fixture solver_runs directory")

    glstat_history = _finite_history(run_dir, "glstat")
    matsum_history = _finite_history(run_dir, "matsum")
    solver = record.get("solver")
    if not isinstance(solver, Mapping):
        solver = {}
    outputs = record.get("outputs")
    if not isinstance(outputs, Mapping):
        outputs = {}
    evaluation = record.get("solver_evaluation")
    if not isinstance(evaluation, Mapping):
        evaluation = {}
    parsed = evaluation.get("parsed")
    if not isinstance(parsed, Mapping):
        parsed = {}

    raw_final_time = parsed.get("final_problem_time_s")
    final_time = (
        float(raw_final_time)
        if isinstance(raw_final_time, (int, float))
        and not isinstance(raw_final_time, bool)
        and math.isfinite(float(raw_final_time))
        else None
    )
    tolerance = max(1.0e-12, TERMINATION_TIME_S * 1.0e-6)
    termination_time_reached = bool(
        parsed.get("termination_time_reached") is True
        and final_time is not None
        and final_time >= TERMINATION_TIME_S - tolerance
    )
    required_outputs_present = all(
        isinstance(outputs.get(prefix), Mapping)
        and outputs[prefix].get("ok") is True
        for prefix in ("d3hsp", "d3plot", "glstat", "matsum")
    )
    stage_solver_sha256 = solver.get("sha256")
    model_json_identity_ok = record.get("model_json_sha256") == model_json_sha256
    finite_solver_evaluation = bool(
        evaluation.get("ok") is True
        and parsed.get("finite") is True
    )
    normal_termination = parsed.get("terminated_normally") is True
    ok = bool(
        record.get("ok") is True
        and record.get("status") == "completed"
        and _zero_returncode(record.get("returncode"))
        and record.get("result_mode") == "initial_validation"
        and record.get("input_sha256") == model_sha256
        and stage_solver_sha256 == solver_sha256
        and model_json_identity_ok
        and normal_termination
        and termination_time_reached
        and finite_solver_evaluation
        and glstat_history["ok"] is True
        and matsum_history["ok"] is True
        and required_outputs_present
    )
    return {
        "started": True,
        "ok": ok,
        "status": record.get("status"),
        "returncode": record.get("returncode"),
        "run_id": record.get("run_id"),
        "run_dir": str(run_dir),
        "input_sha256": record.get("input_sha256"),
        "solver_sha256": stage_solver_sha256,
        "normal_termination": normal_termination,
        "termination_time_reached": termination_time_reached,
        "final_problem_time_s": final_time,
        "finite_solver_evaluation": finite_solver_evaluation,
        "glstat_finite": glstat_history["ok"] is True,
        "matsum_finite": matsum_history["ok"] is True,
        "glstat_history": glstat_history,
        "matsum_history": matsum_history,
        "required_outputs_present": required_outputs_present,
        "skip_reason": None,
    }


def run_fixture(
    output_root: Path,
    *,
    solver_exe: Path | None = None,
) -> dict[str, Any]:
    root = _validated_empty_output_root(output_root)
    result = _new_result(root)
    result_path = root / "fixture_result.json"
    stage = "static_audit"
    try:
        model_path = root / "model.k"
        model_json_path = root / "model.json"
        deck_lines = render_fixture_deck()
        _write_text_atomic(model_path, "\n".join(deck_lines) + "\n")
        _write_json_atomic(
            model_json_path,
            {
                "schema_version": "phase18.ale_buffer_fixture_model@1",
                "spec": {
                    "model_type": "refined_building_initial_validation",
                    "fixture_kind": "phase18_ale_buffer",
                    "termination_time_s": TERMINATION_TIME_S,
                    "grid_cells": [NX, NY, NZ],
                    "active_layers": ACTIVE_LAYERS,
                    "buffer_layers": BUFFER_LAYERS,
                },
            },
        )
        model_sha256 = _sha256_file(model_path)
        model_json_sha256 = _sha256_file(model_json_path)
        audit = audit_fixture_deck(model_path)
        result["static_audit"] = audit
        result["model"].update(
            {
                "sha256": model_sha256,
                "size_bytes": model_path.stat().st_size,
                "model_json_sha256": model_json_sha256,
            }
        )
        _write_json_atomic(result_path, result)
        if audit["ok"] is not True:
            _record_failure(
                result,
                stage="static_audit",
                message="generated fixture deck failed closed static audit",
            )
            _write_json_atomic(result_path, result)
            return result

        stage = "solver_identity"
        solver = _resolve_solver_identity(result, solver_exe)
        _write_json_atomic(result_path, result)
        if solver is None:
            return result
        solver_sha256 = str(result["solver_identity"]["actual_sha256"])

        stage = "mcheck"
        result["mcheck"]["started"] = True
        result["mcheck"]["status"] = "starting"
        _write_json_atomic(result_path, result)
        mcheck_record = execute_lsdyna_initialization_smoke(
            root,
            solver,
            ncpu=NCPU,
            memory=MEMORY,
            timeout_s=MCHECK_TIMEOUT_S,
            static_validation={"fixture_static_audit": audit},
        )
        result["mcheck"] = _summarize_mcheck(
            mcheck_record,
            model_sha256=model_sha256,
            solver_sha256=solver_sha256,
        )
        _write_json_atomic(result_path, result)
        if result["mcheck"]["ok"] is not True:
            _record_failure(
                result,
                stage="mcheck",
                message="R12 mcheck did not satisfy the closed fixture gate",
            )
            _write_json_atomic(result_path, result)
            return result

        stage = "solve"
        result["solve"]["started"] = True
        result["solve"]["status"] = "starting"
        _write_json_atomic(result_path, result)
        solve_record = execute_lsdyna_run(
            root,
            solver,
            ncpu=NCPU,
            memory=MEMORY,
            timeout_s=SOLVE_TIMEOUT_S,
            static_validation={"fixture_static_audit": audit},
        )
        result["solve"] = _summarize_solve(
            solve_record,
            root=root,
            model_sha256=model_sha256,
            model_json_sha256=model_json_sha256,
            solver_sha256=solver_sha256,
        )
        if result["solve"]["ok"] is not True:
            _record_failure(
                result,
                stage="solve",
                message="50 microsecond R12 solve did not satisfy the closed fixture gate",
            )
            _write_json_atomic(result_path, result)
            return result

        result["all_ok"] = True
        result["failure"] = None
        _write_json_atomic(result_path, result)
        return result
    except Exception as exc:
        _record_failure(result, stage=stage, error=exc)
        _write_json_atomic(result_path, result)
        return result


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description=(
            "Validate the isolated 4x4x6 Phase 18 active-air/ALE-vacuum "
            "buffer fixture with reviewed LS-DYNA R12."
        )
    )
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--solver-exe", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run_fixture(args.output_root, solver_exe=args.solver_exe)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0 if result["all_ok"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
