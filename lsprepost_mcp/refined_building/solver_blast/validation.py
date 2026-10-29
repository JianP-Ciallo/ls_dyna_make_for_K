"""Fail-closed persisted-deck inspection for Phase 18 solver blast packages."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from .charge import TNT_DENSITY_KG_PER_M3


_MAX_MODEL_BYTES = 256 * 1024 * 1024
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_AIR_PART_ID = 9_001
_TNT_PART_ID = 9_002
_ALE_BUFFER_PART_ID = 9_003
_ALE_PART_SET_ID = 91_001
_FSI_SEGMENT_SET_ID = 92_001
_ALE_SIDE_SEGMENT_SET_ID = 92_002
_ALE_TOP_SEGMENT_SET_ID = 92_003
_ALE_BOTTOM_SEGMENT_SET_ID = 92_004
_EXPECTED_ALE_PART_IDS = (_AIR_PART_ID, _TNT_PART_ID, _ALE_BUFFER_PART_ID)
_SURFACE_CLASSES = (
    "external_air_exposed",
    "internal_air_exposed",
    "soil_contact",
    "sealed_internal",
    "structural_connection",
)
_SURFACE_TOPOLOGY_SCHEMA_VERSION = "phase18.solver_blast.surface_topology@1"
_SURFACE_TOPOLOGY_MODEL_ANCHOR_PREFIX = "$P18ST="
_MESH_QUALITY_SCHEMA_VERSION = "phase18.solver_blast.mesh_quality@1"
_MESH_QUALITY_MODEL_ANCHOR_PREFIX = "$P18MQ="
_ALLOWED_KEYWORDS = {
    "*ALE_ESSENTIAL_BOUNDARY",
    "*ALE_MULTI-MATERIAL_GROUP",
    "*BOUNDARY_NON_REFLECTING",
    "*BOUNDARY_SPC_SET",
    "*CONSTRAINED_BEAM_IN_SOLID",
    "*CONSTRAINED_INTERPOLATION",
    "*CONSTRAINED_LAGRANGE_IN_SOLID",
    "*CONTROL_ALE",
    "*CONTROL_ENERGY",
    "*CONTROL_TERMINATION",
    "*CONTROL_TIMESTEP",
    "*DATABASE_ALE",
    "*DATABASE_ALE_MAT",
    "*DATABASE_BINARY_D3PLOT",
    "*DATABASE_FSI",
    "*DATABASE_GLSTAT",
    "*DATABASE_HISTORY_NODE_SET",
    "*DATABASE_HISTORY_SOLID_SET",
    "*DATABASE_MATSUM",
    "*DEFINE_CURVE_TITLE",
    "*ELEMENT_BEAM",
    "*ELEMENT_SHELL",
    "*ELEMENT_SOLID",
    "*END",
    "*EOS_JWL",
    "*EOS_LINEAR_POLYNOMIAL",
    "*INITIAL_DETONATION",
    "*KEYWORD",
    "*MAT_CONCRETE_DAMAGE_REL3",
    "*MAT_ADD_EROSION",
    "*MAT_ALE_VACUUM_TITLE",
    "*MAT_ELASTIC_TITLE",
    "*MAT_HIGH_EXPLOSIVE_BURN",
    "*MAT_NULL",
    "*MAT_PLASTIC_KINEMATIC",
    "*NODE",
    "*PART",
    "*SECTION_BEAM",
    "*SECTION_SHELL",
    "*SECTION_SOLID",
    "*SET_NODE_LIST_TITLE",
    "*SET_PART_LIST_TITLE",
    "*SET_SEGMENT_TITLE",
    "*SET_SOLID_LIST_TITLE",
    "*TITLE",
}


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    ok: bool
    findings: tuple[ValidationFinding, ...]
    model_sha256: str | None
    node_count: int
    element_count: int
    ale_node_count: int
    ale_element_count: int
    air_element_count: int
    tnt_element_count: int
    tnt_realized_mass_kg: float | None
    tnt_bounds_m: tuple[float, float, float, float, float, float] | None
    fsi_segment_count: int
    charge_position_m: tuple[float, float, float] | None
    charge_radius_m: float | None
    detonation_time_s: float | None
    termination_time_s: float | None


@dataclass(frozen=True, slots=True)
class _Element:
    family: str
    element_id: int
    part_id: int
    node_ids: tuple[int, ...]


def inspect_solver_blast_deck(path: Path) -> ValidationReport:
    directory = Path(path)
    try:
        return _inspect_solver_blast_deck(directory)
    except (
        OSError,
        TypeError,
        ValueError,
        KeyError,
        IndexError,
        OverflowError,
        json.JSONDecodeError,
    ) as exc:
        return ValidationReport(
            ok=False,
            findings=(ValidationFinding("deck_parse_error", str(exc)),),
            model_sha256=None,
            node_count=0,
            element_count=0,
            ale_node_count=0,
            ale_element_count=0,
            air_element_count=0,
            tnt_element_count=0,
            tnt_realized_mass_kg=None,
            tnt_bounds_m=None,
            fsi_segment_count=0,
            charge_position_m=None,
            charge_radius_m=None,
            detonation_time_s=None,
            termination_time_s=None,
        )


def _inspect_solver_blast_deck(directory: Path) -> ValidationReport:
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("solver blast model path must be a real directory")
    model_path = directory / "model.k"
    manifest_path = directory / "manifest.json"
    for candidate, limit, label in (
        (model_path, _MAX_MODEL_BYTES, "model.k"),
        (manifest_path, _MAX_MANIFEST_BYTES, "manifest.json"),
    ):
        if not candidate.is_file() or candidate.is_symlink():
            raise ValueError(f"{label} must be a real regular file")
        if candidate.stat().st_size > limit:
            raise ValueError(f"{label} exceeds the inspection byte limit")

    payload = model_path.read_bytes()
    model_sha256 = hashlib.sha256(payload).hexdigest()
    text = payload.decode("utf-8", errors="strict")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _validate_manifest_shape(manifest)
    _validate_surface_topology_model_anchor(
        text,
        manifest["surface_topology"]["fingerprint"],
    )
    _validate_mesh_quality_model_anchor(
        text,
        manifest["mesh_quality"]["fingerprint"],
    )
    sections = _keyword_sections(text)
    findings: list[ValidationFinding] = []

    expected_model = manifest["model"]
    _check(
        findings,
        expected_model["path"] == "model.k",
        "model_path",
        "manifest model path must be exactly model.k",
    )
    _check(
        findings,
        expected_model["sha256"] == model_sha256,
        "model_sha256",
        "model.k SHA-256 does not match the manifest",
    )
    _check(
        findings,
        expected_model["byte_count"] == len(payload),
        "model_byte_count",
        "model.k byte count does not match the manifest",
    )

    section_names = [name for name, _ in sections]
    unexpected_keywords = sorted(set(section_names) - _ALLOWED_KEYWORDS)
    _check(
        findings,
        not unexpected_keywords,
        "keyword_vocabulary",
        f"model contains unsupported keyword cards: {unexpected_keywords}",
    )
    _check(findings, section_names.count("*KEYWORD") == 1, "keyword_root", "model must contain one *KEYWORD")
    _check(findings, section_names.count("*END") == 1, "keyword_end", "model must contain one *END")
    for required in (
        "*MAT_NULL",
        "*EOS_LINEAR_POLYNOMIAL",
        "*MAT_HIGH_EXPLOSIVE_BURN",
        "*EOS_JWL",
        "*MAT_ALE_VACUUM_TITLE",
        "*ALE_MULTI-MATERIAL_GROUP",
        "*ALE_ESSENTIAL_BOUNDARY",
        "*INITIAL_DETONATION",
        "*CONSTRAINED_LAGRANGE_IN_SOLID",
    ):
        _check(
            findings,
            required in section_names,
            f"required_card:{required}",
            f"required solver card is missing: {required}",
        )

    nodes = _parse_nodes(sections)
    elements = _parse_elements(sections)
    part_records = _parse_parts(sections)
    material_ids = _parse_identity_cards(
        tuple(row for row in sections if row[0] != "*MAT_ADD_EROSION"),
        "*MAT_",
    )
    eos_ids = _parse_identity_cards(sections, "*EOS_")
    vacuum_rows = _single_section(sections, "*MAT_ALE_VACUUM_TITLE")
    if len(vacuum_rows) != 2:
        raise ValueError("*MAT_ALE_VACUUM_TITLE must use the reviewed title/data layout")
    vacuum_identity = _csv_numbers(vacuum_rows[1])
    if (
        len(vacuum_identity) != 2
        or _exact_int(vacuum_identity[0], "ALE vacuum material id") != 9
        or not math.isclose(
            float(vacuum_identity[1]), 1.225e-5, rel_tol=0.0, abs_tol=1.0e-12
        )
    ):
        raise ValueError("*MAT_ALE_VACUUM_TITLE does not match the reviewed R12 candidate")
    if _parse_part_set(sections, _ALE_PART_SET_ID) != _EXPECTED_ALE_PART_IDS:
        raise ValueError("ALE master part set does not contain the reviewed material parts")
    if _parse_ale_multimaterial_group(sections) != tuple(
        (part_id, 1) for part_id in _EXPECTED_ALE_PART_IDS
    ):
        raise ValueError("*ALE_MULTI-MATERIAL_GROUP does not match the reviewed material parts")
    if _parse_ale_essential_boundary(sections) != (
        _ALE_BOTTOM_SEGMENT_SET_ID,
        2,
        2,
        0,
    ):
        raise ValueError("*ALE_ESSENTIAL_BOUNDARY must close the bottom in no-flow slip mode")
    if _parse_nonreflecting_boundaries(sections) != (
        (_ALE_SIDE_SEGMENT_SET_ID, 0, 0),
        (_ALE_TOP_SEGMENT_SET_ID, 0, 0),
    ):
        raise ValueError("ALE non-reflecting boundaries must target only the side and top sets")
    if _parse_control_ale(sections) != (
        (-1.0, 1.0, 2.0, -1.0, 0.0, 0.0, 0.0, 0.0),
        (0.0, 1.0e20, 1.0, 1.0e-6, 0.0, 0.0, 101325.0, 0.0),
    ):
        raise ValueError("*CONTROL_ALE does not match the reviewed R12 two-row preset")
    erosion_rows = _single_section(sections, "*MAT_ADD_EROSION")
    if len(erosion_rows) != 2:
        raise ValueError("*MAT_ADD_EROSION must use the reviewed two-row layout")
    erosion_identity = _csv_numbers(erosion_rows[0])
    erosion_criteria = _csv_numbers(erosion_rows[1])
    if (
        len(erosion_identity) != 8
        or len(erosion_criteria) != 8
        or _exact_int(erosion_identity[0], "erosion material id") != 3
        or _exact_int(erosion_identity[6], "erosion integration point count") != 1
        or _exact_int(erosion_identity[7], "erosion criterion count") != 1
        or not math.isclose(
            float(erosion_criteria[3]),
            0.05,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        )
    ):
        raise ValueError("*MAT_ADD_EROSION does not match the reviewed concrete preset")
    declared_part_ids = set(part_records)
    defined_node_ids = set(nodes)
    referenced_node_ids = {node_id for element in elements for node_id in element.node_ids}
    referenced_part_ids = {element.part_id for element in elements}
    _check(
        findings,
        referenced_node_ids <= defined_node_ids,
        "element_node_closure",
        "one or more elements reference an undefined node",
    )
    _check(
        findings,
        referenced_part_ids <= declared_part_ids,
        "element_part_closure",
        "one or more elements reference an undefined part",
    )
    for element in (row for row in elements if row.family == "Beam"):
        if not set(element.node_ids) <= defined_node_ids:
            continue
        first, second, orientation = (nodes[node_id] for node_id in element.node_ids)
        axis = tuple(second[index] - first[index] for index in range(3))
        reference = tuple(orientation[index] - first[index] for index in range(3))
        cross = (
            axis[1] * reference[2] - axis[2] * reference[1],
            axis[2] * reference[0] - axis[0] * reference[2],
            axis[0] * reference[1] - axis[1] * reference[0],
        )
        _check(
            findings,
            math.sqrt(math.fsum(value * value for value in cross)) > 1.0e-10,
            f"beam_orientation:{element.element_id}",
            f"beam {element.element_id} orientation node is collinear with its axis",
        )
    for part_id, (_role, _section_id, material_id, eos_id) in part_records.items():
        _check(
            findings,
            material_id in material_ids,
            f"part_material:{part_id}",
            f"part {part_id} references an undefined material",
        )
        if eos_id:
            _check(
                findings,
                eos_id in eos_ids,
                f"part_eos:{part_id}",
                f"part {part_id} references an undefined EOS",
            )
    for part_id, expected_material, expected_eos, label in (
        (_AIR_PART_ID, 1, 1, "air"),
        (_TNT_PART_ID, 2, 2, "TNT"),
        (_ALE_BUFFER_PART_ID, 9, 0, "ALE coupling buffer"),
    ):
        record = part_records.get(part_id)
        _check(findings, record is not None, f"{label}_part", f"{label} part is missing")
        if record is not None:
            _check(
                findings,
                record[2:] == (expected_material, expected_eos),
                f"{label}_material_eos",
                f"{label} part material/EOS relationship is invalid",
            )

    manifest_parts = {str(role): int(part_id) for role, part_id in manifest["part_ids"]}
    manifest_roles_by_id = {part_id: role for role, part_id in manifest_parts.items()}
    _check(
        findings,
        set(manifest_roles_by_id) == set(part_records),
        "part_manifest_closure",
        "part ID closure does not match the manifest",
    )
    for part_id, (title, *_rest) in part_records.items():
        if part_id in {8_001, _AIR_PART_ID, _TNT_PART_ID}:
            continue
        _check(
            findings,
            manifest_roles_by_id.get(part_id) == title,
            f"part_role:{part_id}",
            f"building part {part_id} title does not match its manifest role",
        )
    _check(
        findings,
        sorted(material_ids) == manifest["materials"]["material_ids"],
        "material_manifest_closure",
        "material identities do not match the manifest",
    )
    _check(
        findings,
        sorted(eos_ids) == manifest["materials"]["eos_ids"],
        "eos_manifest_closure",
        "EOS identities do not match the manifest",
    )

    fsi_segments = _parse_segment_set(sections, _FSI_SEGMENT_SET_ID)
    for segment in fsi_segments:
        _check(
            findings,
            set(segment) <= defined_node_ids,
            "fsi_node_closure",
            "FSI segment references an undefined node",
        )
    _check(
        findings,
        len(fsi_segments) == manifest["total_fsi_segment_count"],
        "fsi_segment_count",
        "FSI segment count does not match the manifest",
    )
    _check(
        findings,
        len(fsi_segments) > 0,
        "fsi_nonempty",
        "FSI segment set must be nonempty",
    )
    ale_boundary_segments: dict[int, tuple[tuple[int, int, int, int], ...]] = {}
    for set_id, label in (
        (_ALE_SIDE_SEGMENT_SET_ID, "ALE side"),
        (_ALE_TOP_SEGMENT_SET_ID, "ALE top"),
        (_ALE_BOTTOM_SEGMENT_SET_ID, "ALE bottom"),
    ):
        boundary_segments = _parse_segment_set(sections, set_id)
        ale_boundary_segments[set_id] = boundary_segments
        _check(
            findings,
            bool(boundary_segments),
            f"ale_boundary_nonempty:{set_id}",
            f"{label} segment set must be nonempty",
        )
        _check(
            findings,
            all(set(segment) <= defined_node_ids for segment in boundary_segments),
            f"ale_boundary_node_closure:{set_id}",
            f"{label} segment set references an undefined node",
        )

    air_elements = tuple(row for row in elements if row.part_id == _AIR_PART_ID)
    tnt_elements = tuple(row for row in elements if row.part_id == _TNT_PART_ID)
    buffer_elements = tuple(
        row for row in elements if row.part_id == _ALE_BUFFER_PART_ID
    )
    ale_elements = air_elements + buffer_elements + tnt_elements
    ale_node_ids = {node_id for row in ale_elements for node_id in row.node_ids}
    _check(
        findings,
        len(nodes) == manifest["total_node_count"],
        "node_count",
        "node count does not match the manifest",
    )
    _check(
        findings,
        len(elements) == manifest["total_element_count"],
        "element_count",
        "element count does not match the manifest",
    )
    _check(
        findings,
        len(ale_elements) == manifest["ale_element_count"],
        "ale_element_count",
        "ALE element count does not match the manifest",
    )
    _check(
        findings,
        len(air_elements) == manifest["ale_air_element_count"],
        "ale_air_element_count",
        "ALE air element count does not match the manifest",
    )
    _check(
        findings,
        len(tnt_elements) == manifest["tnt_element_count"],
        "tnt_element_count",
        "TNT Solid element count does not match the manifest",
    )
    _check(
        findings,
        bool(tnt_elements),
        "tnt_solid_nonempty",
        "TNT Part must own explicit Solid elements",
    )
    _check(
        findings,
        bool(buffer_elements),
        "ale_buffer_solid_nonempty",
        "ALE coupling-buffer Part must own explicit Solid elements",
    )
    _check(
        findings,
        len(ale_node_ids) == manifest["ale_node_count"],
        "ale_node_count",
        "ALE node count does not match the manifest",
    )
    ale_hex8_ok = bool(ale_elements) and all(
        row.family == "Solid" and _is_positive_axis_aligned_hex8(row, nodes)
        for row in ale_elements
    )
    _check(
        findings,
        ale_hex8_ok,
        "ale_hex_orientation",
        "all ALE material elements must be positively oriented axis-aligned HEX8 cells",
    )
    if ale_hex8_ok:
        expected_boundaries = _expected_ale_boundary_faces(ale_elements, nodes)
        for set_id, label, kind in (
            (_ALE_SIDE_SEGMENT_SET_ID, "ALE side", "side"),
            (_ALE_TOP_SEGMENT_SET_ID, "ALE top", "top"),
            (_ALE_BOTTOM_SEGMENT_SET_ID, "ALE bottom", "bottom"),
        ):
            complete, outward = _boundary_face_closure(
                ale_boundary_segments[set_id],
                expected_boundaries[kind],
            )
            _check(
                findings,
                complete,
                f"ale_boundary_geometry:{set_id}",
                (
                    f"{label} segment set must exactly cover the structured ALE "
                    "outer faces without omissions or duplicates"
                ),
            )
            _check(
                findings,
                outward,
                f"ale_boundary_winding:{set_id}",
                f"{label} segment faces must use outward signed winding",
            )

    charge_position, detonation_time, detonation_part_id = _parse_charge(sections)
    manifest_charge = manifest["charge"]
    charge_radius = float(manifest_charge["radius_m"])
    _check(
        findings,
        detonation_part_id == _TNT_PART_ID,
        "detonation_tnt_part",
        "detonation must reference the explicit TNT Part",
    )
    _check(
        findings,
        all(
            math.isclose(
                float(manifest_charge["position_m"][index]),
                charge_position[index],
                rel_tol=5.0e-8,
                abs_tol=1.0e-9,
            )
            for index in range(3)
        ),
        "charge_position",
        "charge position does not match the manifest",
    )
    _check(
        findings,
        math.isclose(float(manifest_charge["detonation_time_s"]), detonation_time, rel_tol=0.0, abs_tol=1.0e-12),
        "detonation_time",
        "detonation time does not match the manifest",
    )
    tnt_element_bounds = tuple(
        _bounds(nodes[node_id] for node_id in row.node_ids)
        for row in tnt_elements
        if set(row.node_ids) <= defined_node_ids
    )
    _check(
        findings,
        all(_is_positive_axis_aligned_hex8(row, nodes) for row in tnt_elements),
        "tnt_hex_orientation",
        "TNT Solid elements must be positively oriented axis-aligned HEX8 cells",
    )
    _check(
        findings,
        not any(
            _boxes_overlap_positive(left, right)
            for index, left in enumerate(tnt_element_bounds)
            for right in tnt_element_bounds[index + 1:]
        ),
        "tnt_solid_overlap",
        "TNT Solid elements must not overlap one another",
    )
    tnt_bounds = _bounds(
        nodes[node_id]
        for row in tnt_elements
        for node_id in row.node_ids
        if node_id in nodes
    )
    tnt_volume = math.fsum(_box_volume(bounds) for bounds in tnt_element_bounds)
    tnt_dimensions = tuple(tnt_bounds[axis + 3] - tnt_bounds[axis] for axis in range(3))
    tnt_center = tuple(0.5 * (tnt_bounds[axis] + tnt_bounds[axis + 3]) for axis in range(3))
    rendered_mass = tnt_volume * TNT_DENSITY_KG_PER_M3
    _check(
        findings,
        manifest_charge["geometry_kind"] == "mass_conserving_cuboid",
        "charge_geometry_kind",
        "manifest charge geometry must be the reviewed mass-conserving cuboid",
    )
    _check(
        findings,
        all(
            math.isclose(value, float(manifest_charge["side_length_m"]), rel_tol=2.0e-7, abs_tol=5.0e-8)
            for value in tnt_dimensions
        ),
        "charge_side_length",
        "explicit TNT Solid bounds do not match the manifest side length",
    )
    _check(
        findings,
        all(
            math.isclose(tnt_bounds[index], float(manifest_charge["bounds_m"][index]), rel_tol=5.0e-8, abs_tol=1.0e-9)
            for index in range(6)
        ),
        "charge_bounds",
        "explicit TNT Solid bounds do not match the manifest",
    )
    _check(
        findings,
        all(math.isclose(tnt_center[index], charge_position[index], rel_tol=5.0e-8, abs_tol=1.0e-9) for index in range(3)),
        "charge_center",
        "detonation position is not the center of the explicit TNT Solid",
    )
    _check(
        findings,
        math.isclose(tnt_volume, math.prod(tnt_dimensions), rel_tol=2.0e-7, abs_tol=1.0e-12),
        "charge_solid_closure",
        "explicit TNT Solid elements do not close the declared cuboid volume",
    )
    _check(
        findings,
        math.isclose(float(manifest_charge["volume_m3"]), tnt_volume, rel_tol=2.0e-7, abs_tol=1.0e-12),
        "charge_volume",
        "manifest TNT volume does not match the explicit Solid elements",
    )
    _check(
        findings,
        int(manifest_charge["solid_element_count"]) == len(tnt_elements),
        "charge_solid_count",
        "manifest TNT Solid count does not match the model",
    )
    _check(
        findings,
        math.isclose(
            float(manifest_charge["mass_kg"]),
            rendered_mass,
            rel_tol=2.0e-7,
            abs_tol=1.0e-9,
        ),
        "charge_mass_volume",
        "manifest TNT mass does not match the rendered Solid volume",
    )
    _check(
        findings,
        math.isclose(float(manifest_charge["realized_mass_kg"]), rendered_mass, rel_tol=2.0e-7, abs_tol=1.0e-9),
        "charge_realized_mass",
        "manifest realized TNT mass does not match the rendered Solid volume",
    )
    if ale_node_ids:
        air_bounds = _bounds(nodes[node_id] for node_id in ale_node_ids)
        _check(
            findings,
            all(
                air_bounds[axis] < tnt_bounds[axis]
                and tnt_bounds[axis + 3] < air_bounds[axis + 3]
                for axis in range(3)
            ),
            "charge_air_bounds",
            "explicit TNT Solid is not strictly inside the ALE bounds",
        )
    occupied = tuple(
        row for row in elements
        if row.part_id not in {_AIR_PART_ID, _TNT_PART_ID, _ALE_BUFFER_PART_ID}
    )
    intersects_occupied = any(
        _boxes_overlap_positive(tnt_bounds, _bounds(nodes[node_id] for node_id in row.node_ids))
        for row in occupied
        if set(row.node_ids) <= defined_node_ids
    )
    _check(
        findings,
        not intersects_occupied,
        "charge_occupied_volume",
        "explicit TNT Solid intersects building or soil geometry",
    )

    termination_time = _single_float_card(sections, "*CONTROL_TERMINATION")
    _check(
        findings,
        math.isfinite(termination_time) and termination_time > 0.0,
        "termination_time",
        "termination time must be finite and positive",
    )
    return ValidationReport(
        ok=not findings,
        findings=tuple(findings),
        model_sha256=model_sha256,
        node_count=len(nodes),
        element_count=len(elements),
        ale_node_count=len(ale_node_ids),
        ale_element_count=len(ale_elements),
        air_element_count=len(air_elements),
        tnt_element_count=len(tnt_elements),
        tnt_realized_mass_kg=tnt_volume * TNT_DENSITY_KG_PER_M3,
        tnt_bounds_m=tnt_bounds,
        fsi_segment_count=len(fsi_segments),
        charge_position_m=charge_position,
        charge_radius_m=charge_radius,
        detonation_time_s=detonation_time,
        termination_time_s=termination_time,
    )


def _validate_manifest_shape(manifest: object) -> None:
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    required = {
        "schema_version",
        "unit_system",
        "model",
        "scene_fingerprint",
        "building_mesh_fingerprint",
        "fsi_fingerprint",
        "surface_topology",
        "mesh_quality",
        "fsi_slave_segment_count",
        "ground_fsi_segment_count",
        "total_fsi_segment_count",
        "building_ground_contact_segment_count",
        "ground_contact_segment_count",
        "structural_constraint_count",
        "ale_node_count",
        "ale_element_count",
        "ale_air_element_count",
        "tnt_element_count",
        "total_node_count",
        "total_element_count",
        "part_ids",
        "materials",
        "charge",
        "engineering_validated",
        "requires_project_review",
    }
    if set(manifest) != required:
        raise ValueError("manifest root schema is not closed")
    if manifest["schema_version"] != "phase18.solver_blast.deck_manifest@4":
        raise ValueError("unsupported solver blast manifest version")
    if manifest["unit_system"] != "SI_m_s_kg_N_Pa":
        raise ValueError("solver blast manifest unit system must be SI_m_s_kg_N_Pa")
    if manifest["engineering_validated"] is not False:
        raise ValueError("solver blast manifest cannot claim engineering validation")
    if manifest["requires_project_review"] is not True:
        raise ValueError("solver blast manifest must require project review")
    if not isinstance(manifest["model"], dict) or set(manifest["model"]) != {
        "path",
        "sha256",
        "byte_count",
    }:
        raise ValueError("manifest model schema is not closed")
    model = manifest["model"]
    if (
        model["path"] != "model.k"
        or not isinstance(model["sha256"], str)
        or len(model["sha256"]) != 64
        or isinstance(model["byte_count"], bool)
        or not isinstance(model["byte_count"], int)
        or model["byte_count"] <= 0
        or model["byte_count"] > _MAX_MODEL_BYTES
    ):
        raise ValueError("manifest model identity is invalid")
    if not isinstance(manifest["charge"], dict) or set(manifest["charge"]) != {
        "geometry_kind",
        "mass_kg",
        "position_m",
        "radius_m",
        "volume_m3",
        "side_length_m",
        "bounds_m",
        "solid_element_count",
        "realized_mass_kg",
        "detonation_time_s",
    }:
        raise ValueError("manifest charge schema is not closed")
    charge = manifest["charge"]
    position = charge["position_m"]
    numeric = (
        charge["mass_kg"], charge["radius_m"], charge["volume_m3"],
        charge["side_length_m"], charge["realized_mass_kg"], charge["detonation_time_s"],
    )
    if (
        any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in numeric)
        or not all(math.isfinite(float(value)) for value in numeric)
        or not 0.1 <= float(charge["mass_kg"]) <= 100.0
        or float(charge["radius_m"]) <= 0.0
        or float(charge["volume_m3"]) <= 0.0
        or float(charge["side_length_m"]) <= 0.0
        or float(charge["realized_mass_kg"]) <= 0.0
        or float(charge["detonation_time_s"]) < 0.0
        or charge["geometry_kind"] != "mass_conserving_cuboid"
        or isinstance(charge["solid_element_count"], bool)
        or not isinstance(charge["solid_element_count"], int)
        or charge["solid_element_count"] <= 0
        or not isinstance(position, list)
        or len(position) != 3
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in position
        )
    ):
        raise ValueError("manifest charge identity is invalid")
    bounds = charge["bounds_m"]
    if (
        not isinstance(bounds, list)
        or len(bounds) != 6
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in bounds
        )
        or any(float(bounds[index]) >= float(bounds[index + 3]) for index in range(3))
    ):
        raise ValueError("manifest charge bounds are invalid")
    if not isinstance(manifest["materials"], dict) or set(manifest["materials"]) != {
        "eos_ids",
        "erosion_maximum_principal_strain",
        "erosion_mode",
        "material_ids",
        "role_to_material_id",
        "validation_status",
    }:
        raise ValueError("manifest material schema is not closed")
    materials = manifest["materials"]
    if materials["validation_status"] != (
        "review_required_preliminary_si_presets_with_standard_concrete_erosion_and_elastic_rc"
    ):
        raise ValueError("manifest material status cannot claim engineering validation")
    if materials["erosion_mode"] != "standard_observation":
        raise ValueError("manifest material erosion mode is invalid")
    erosion_strain = materials["erosion_maximum_principal_strain"]
    if (
        isinstance(erosion_strain, bool)
        or not isinstance(erosion_strain, (int, float))
        or not math.isfinite(float(erosion_strain))
        or not math.isclose(float(erosion_strain), 0.05, rel_tol=0.0, abs_tol=1.0e-12)
    ):
        raise ValueError("manifest material erosion strain is invalid")
    for identity_key in ("eos_ids", "material_ids"):
        identities = materials[identity_key]
        if (
            not isinstance(identities, list)
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                for value in identities
            )
            or identities != sorted(set(identities))
        ):
            raise ValueError(f"manifest material identities are invalid: {identity_key}")
    role_rows = materials["role_to_material_id"]
    if (
        not isinstance(role_rows, list)
        or any(
            not isinstance(row, list)
            or len(row) != 2
            or not isinstance(row[0], str)
            or not row[0].strip()
            or isinstance(row[1], bool)
            or not isinstance(row[1], int)
            or row[1] not in materials["material_ids"]
            for row in role_rows
        )
        or len({row[0] for row in role_rows}) != len(role_rows)
    ):
        raise ValueError("manifest material role identities are invalid")
    for count_key in (
        "fsi_slave_segment_count",
        "ground_fsi_segment_count",
        "total_fsi_segment_count",
        "building_ground_contact_segment_count",
        "ground_contact_segment_count",
        "structural_constraint_count",
        "ale_node_count",
        "ale_element_count",
        "ale_air_element_count",
        "tnt_element_count",
        "total_node_count",
        "total_element_count",
    ):
        value = manifest[count_key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"manifest count must be a non-negative integer: {count_key}")
    if (
        manifest["fsi_slave_segment_count"]
        + manifest["ground_fsi_segment_count"]
        != manifest["total_fsi_segment_count"]
    ):
        raise ValueError("manifest FSI segment counts do not close")
    _validate_surface_topology_manifest(
        manifest["surface_topology"],
        fsi_slave_segment_count=manifest["fsi_slave_segment_count"],
    )
    _validate_mesh_quality_manifest(manifest["mesh_quality"])
    part_ids = manifest["part_ids"]
    if not isinstance(part_ids, list) or any(
        not isinstance(row, list)
        or len(row) != 2
        or not isinstance(row[0], str)
        or not row[0].strip()
        or isinstance(row[1], bool)
        or not isinstance(row[1], int)
        or row[1] <= 0
        for row in part_ids
    ) or len({row[0] for row in part_ids}) != len(part_ids) or len(
        {row[1] for row in part_ids}
    ) != len(part_ids):
        raise ValueError("manifest part identities are invalid")


def _validate_surface_topology_manifest(
    value: object,
    *,
    fsi_slave_segment_count: int,
) -> None:
    required = {
        "schema_version",
        "fingerprint",
        "counts",
        "boundary_face_count",
        "unclassified_count",
        "multiply_classified_count",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("manifest surface topology schema is not closed")
    if value["schema_version"] != _SURFACE_TOPOLOGY_SCHEMA_VERSION:
        raise ValueError("unsupported surface topology manifest version")
    _validate_sha256_identity(
        value["fingerprint"],
        "manifest surface topology fingerprint",
    )
    counts = value["counts"]
    if not isinstance(counts, list) or len(counts) != len(_SURFACE_CLASSES):
        raise ValueError("manifest surface topology counts are not closed")
    for index, surface_class in enumerate(_SURFACE_CLASSES):
        row = counts[index]
        if (
            not isinstance(row, list)
            or len(row) != 2
            or row[0] != surface_class
            or isinstance(row[1], bool)
            or not isinstance(row[1], int)
            or row[1] < 0
        ):
            raise ValueError("manifest surface topology counts are invalid")
    for count_key in (
        "boundary_face_count",
        "unclassified_count",
        "multiply_classified_count",
    ):
        count = value[count_key]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(
                f"manifest surface topology count is invalid: {count_key}"
            )
    count_by_class = {row[0]: row[1] for row in counts}
    if sum(count_by_class.values()) != value["boundary_face_count"]:
        raise ValueError("manifest surface topology boundary count does not close")
    if value["unclassified_count"] != 0:
        raise ValueError("manifest surface topology contains unclassified faces")
    if value["multiply_classified_count"] != 0:
        raise ValueError("manifest surface topology contains multiply classified faces")
    if (
        count_by_class["external_air_exposed"]
        + count_by_class["internal_air_exposed"]
        != fsi_slave_segment_count
    ):
        raise ValueError(
            "manifest active-air-exposed surface count does not close against FSI"
        )


def _validate_surface_topology_model_anchor(
    text: str,
    expected_fingerprint: str,
) -> None:
    anchors = tuple(
        line.strip()[len(_SURFACE_TOPOLOGY_MODEL_ANCHOR_PREFIX) :]
        for line in text.splitlines()
        if line.strip().startswith(_SURFACE_TOPOLOGY_MODEL_ANCHOR_PREFIX)
    )
    if len(anchors) != 1:
        raise ValueError("model must contain one surface topology fingerprint anchor")
    _validate_sha256_identity(anchors[0], "model surface topology fingerprint")
    if anchors[0] != expected_fingerprint:
        raise ValueError(
            "model surface topology fingerprint does not match the manifest"
        )


def _validate_mesh_quality_manifest(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "fingerprint",
        "solid_count",
        "shell_count",
        "beam_count",
        "minimum_corner_jacobian_m3",
        "maximum_aspect_ratio",
        "orphan_node_count",
        "duplicate_element_count",
        "solid_overlap_pair_count",
        "unresolved_overlap_candidate_count",
        "finding_count",
    }:
        raise ValueError("manifest mesh_quality schema is not closed")
    if value["schema_version"] != _MESH_QUALITY_SCHEMA_VERSION:
        raise ValueError("unsupported manifest mesh_quality version")
    _validate_sha256_identity(value["fingerprint"], "manifest mesh_quality fingerprint")
    for key in (
        "solid_count",
        "shell_count",
        "beam_count",
        "orphan_node_count",
        "duplicate_element_count",
        "solid_overlap_pair_count",
        "unresolved_overlap_candidate_count",
        "finding_count",
    ):
        count = value[key]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"manifest mesh_quality count is invalid: {key}")
    if value["solid_count"] <= 0:
        raise ValueError("manifest mesh_quality must contain structural solids")
    for key in ("minimum_corner_jacobian_m3", "maximum_aspect_ratio"):
        number = value[key]
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(float(number))
        ):
            raise ValueError(f"manifest mesh_quality metric is invalid: {key}")
    if float(value["minimum_corner_jacobian_m3"]) <= 0.0:
        raise ValueError("manifest mesh_quality Jacobian must be positive")
    if float(value["maximum_aspect_ratio"]) < 1.0:
        raise ValueError("manifest mesh_quality aspect ratio must be at least one")
    for key in (
        "orphan_node_count",
        "duplicate_element_count",
        "solid_overlap_pair_count",
        "unresolved_overlap_candidate_count",
        "finding_count",
    ):
        if value[key] != 0:
            raise ValueError(f"manifest mesh_quality is not clean: {key}")


def _validate_mesh_quality_model_anchor(
    text: str,
    expected_fingerprint: str,
) -> None:
    anchors = tuple(
        line.strip()[len(_MESH_QUALITY_MODEL_ANCHOR_PREFIX) :]
        for line in text.splitlines()
        if line.strip().startswith(_MESH_QUALITY_MODEL_ANCHOR_PREFIX)
    )
    if len(anchors) != 1:
        raise ValueError("model must contain one mesh quality fingerprint anchor")
    _validate_sha256_identity(anchors[0], "model mesh quality fingerprint")
    if anchors[0] != expected_fingerprint:
        raise ValueError(
            "model mesh quality fingerprint does not match the manifest"
        )


def _validate_sha256_identity(value: object, path: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{path} must be a lowercase SHA-256 identity")


def _keyword_sections(text: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    sections: list[tuple[str, list[str]]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("$"):
            continue
        if line.startswith("*"):
            sections.append((line.upper(), []))
        elif not sections:
            raise ValueError("keyword data appears before the first card")
        else:
            sections[-1][1].append(raw)
    if not sections:
        raise ValueError("model.k contains no keyword cards")
    return tuple((name, tuple(rows)) for name, rows in sections)


def _parse_nodes(sections: tuple[tuple[str, tuple[str, ...]], ...]) -> dict[int, tuple[float, float, float]]:
    nodes: dict[int, tuple[float, float, float]] = {}
    for name, rows in sections:
        if name != "*NODE":
            continue
        for row in rows:
            values = _csv_numbers(row)
            if len(values) < 4:
                raise ValueError("*NODE row must contain id and three coordinates")
            node_id = _exact_int(values[0], "node id")
            coordinates = tuple(float(value) for value in values[1:4])
            if node_id <= 0 or node_id in nodes or not all(math.isfinite(value) for value in coordinates):
                raise ValueError("node identities and coordinates must be unique, positive and finite")
            nodes[node_id] = coordinates  # type: ignore[assignment]
    if not nodes:
        raise ValueError("model contains no nodes")
    return nodes


def _parse_elements(sections: tuple[tuple[str, tuple[str, ...]], ...]) -> tuple[_Element, ...]:
    result: list[_Element] = []
    seen: set[int] = set()
    layouts = {
        "*ELEMENT_SOLID": ("Solid", 10),
        "*ELEMENT_SHELL": ("Shell", 6),
        "*ELEMENT_BEAM": ("Beam", 5),
    }
    for name, rows in sections:
        layout = layouts.get(name)
        if layout is None:
            continue
        family, field_count = layout
        for row in rows:
            if len(row) != field_count * 8:
                raise ValueError(f"{name} row must use the reviewed R12 fixed-column layout")
            values = tuple(int(row[index : index + 8]) for index in range(0, len(row), 8))
            element_id, part_id, *node_ids = values
            if element_id <= 0 or element_id in seen or part_id <= 0 or any(value <= 0 for value in node_ids):
                raise ValueError("element identities and references must be unique and positive")
            seen.add(element_id)
            result.append(_Element(family, element_id, part_id, tuple(node_ids)))
    if not result:
        raise ValueError("model contains no elements")
    return tuple(result)


def _parse_parts(sections: tuple[tuple[str, tuple[str, ...]], ...]) -> dict[int, tuple[str, int, int, int]]:
    result: dict[int, tuple[str, int, int, int]] = {}
    for name, rows in sections:
        if name != "*PART":
            continue
        if len(rows) != 2:
            raise ValueError("*PART must contain one title and one identity row")
        values = _csv_numbers(rows[1])
        if len(values) < 4:
            raise ValueError("*PART identity row is incomplete")
        part_id, section_id, material_id, eos_id = (_exact_int(value, "part field") for value in values[:4])
        if part_id <= 0 or part_id in result or not rows[0].strip():
            raise ValueError("part identity/title must be unique and positive")
        result[part_id] = (rows[0].strip(), section_id, material_id, eos_id)
    return result


def _parse_identity_cards(
    sections: tuple[tuple[str, tuple[str, ...]], ...],
    prefix: str,
) -> set[int]:
    result: set[int] = set()
    for name, rows in sections:
        if not name.startswith(prefix) or not rows:
            continue
        identity_row = rows[1] if name.endswith("_TITLE") and len(rows) >= 2 else rows[0]
        values = _csv_numbers(identity_row)
        if not values:
            continue
        identifier = _exact_int(values[0], f"{prefix} identity")
        if identifier <= 0 or identifier in result:
            raise ValueError(f"{prefix} identities must be unique and positive")
        result.add(identifier)
    return result


def _parse_part_set(
    sections: tuple[tuple[str, tuple[str, ...]], ...],
    set_id: int,
) -> tuple[int, ...]:
    matches: list[tuple[int, ...]] = []
    for name, rows in sections:
        if name != "*SET_PART_LIST_TITLE":
            continue
        if len(rows) < 2 or not rows[0].strip():
            raise ValueError("*SET_PART_LIST_TITLE must contain a title and identity row")
        identity_values = _csv_numbers(rows[1])
        if len(identity_values) != 1:
            raise ValueError("*SET_PART_LIST_TITLE identity row must contain exactly one set id")
        identity = _exact_int(identity_values[0], "part set id")
        if identity != set_id:
            continue
        members: list[int] = []
        for row in rows[2:]:
            values = _csv_numbers(row)
            if not values:
                raise ValueError("ALE master part set contains an empty member row")
            members.extend(_exact_int(value, "part set member") for value in values)
        if any(member <= 0 for member in members) or len(set(members)) != len(members):
            raise ValueError("ALE master part set members must be unique and positive")
        matches.append(tuple(members))
    if len(matches) != 1:
        raise ValueError(f"model must contain exactly one part set {set_id}")
    return matches[0]


def _parse_ale_multimaterial_group(
    sections: tuple[tuple[str, tuple[str, ...]], ...]
) -> tuple[tuple[int, int], ...]:
    rows = _single_section(sections, "*ALE_MULTI-MATERIAL_GROUP")
    if not rows:
        raise ValueError("*ALE_MULTI-MATERIAL_GROUP must contain material part rows")
    parsed: list[tuple[int, int]] = []
    for row in rows:
        values = _csv_numbers(row)
        if len(values) != 2:
            raise ValueError("*ALE_MULTI-MATERIAL_GROUP rows must contain SID and IDTYPE")
        parsed.append(
            (
                _exact_int(values[0], "ALE multi-material part id"),
                _exact_int(values[1], "ALE multi-material id type"),
            )
        )
    if len({part_id for part_id, _id_type in parsed}) != len(parsed):
        raise ValueError("*ALE_MULTI-MATERIAL_GROUP part ids must be unique")
    return tuple(parsed)


def _parse_ale_essential_boundary(
    sections: tuple[tuple[str, tuple[str, ...]], ...]
) -> tuple[int, int, int, int]:
    rows = _single_section(sections, "*ALE_ESSENTIAL_BOUNDARY")
    if len(rows) != 1:
        raise ValueError("*ALE_ESSENTIAL_BOUNDARY must contain exactly one data row")
    values = _csv_numbers(rows[0])
    if len(values) != 4:
        raise ValueError("*ALE_ESSENTIAL_BOUNDARY row must contain four fields")
    return tuple(
        _exact_int(value, "ALE essential boundary field") for value in values
    )  # type: ignore[return-value]


def _parse_nonreflecting_boundaries(
    sections: tuple[tuple[str, tuple[str, ...]], ...]
) -> tuple[tuple[int, int, int], ...]:
    parsed: list[tuple[int, int, int]] = []
    for name, rows in sections:
        if name != "*BOUNDARY_NON_REFLECTING":
            continue
        if len(rows) != 1:
            raise ValueError("*BOUNDARY_NON_REFLECTING must contain exactly one data row")
        values = _csv_numbers(rows[0])
        if len(values) != 3:
            raise ValueError("*BOUNDARY_NON_REFLECTING row must contain three fields")
        parsed.append(
            tuple(
                _exact_int(value, "non-reflecting boundary field") for value in values
            )
        )
    return tuple(parsed)


def _parse_control_ale(
    sections: tuple[tuple[str, tuple[str, ...]], ...]
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    rows = _single_section(sections, "*CONTROL_ALE")
    if len(rows) != 2:
        raise ValueError("*CONTROL_ALE must contain the reviewed two-row layout")
    parsed = tuple(_csv_numbers(row) for row in rows)
    if any(len(row) != 8 for row in parsed):
        raise ValueError("*CONTROL_ALE rows must contain exactly eight fields")
    return parsed  # type: ignore[return-value]


def _parse_segment_set(
    sections: tuple[tuple[str, tuple[str, ...]], ...],
    set_id: int,
) -> tuple[tuple[int, int, int, int], ...]:
    matches: list[tuple[tuple[int, int, int, int], ...]] = []
    for name, rows in sections:
        if name != "*SET_SEGMENT_TITLE" or len(rows) < 2:
            continue
        identity = _exact_int(_csv_numbers(rows[1])[0], "segment set id")
        if identity != set_id:
            continue
        result = []
        for row in rows[2:]:
            values = _csv_numbers(row)
            if len(values) != 4:
                raise ValueError("segment-set rows must contain exactly four node ids")
            result.append(tuple(_exact_int(value, "FSI node id") for value in values[:4]))
        matches.append(tuple(result))  # type: ignore[arg-type]
    if len(matches) != 1:
        raise ValueError(f"required segment set {set_id} must occur exactly once")
    return matches[0]


def _parse_charge(
    sections: tuple[tuple[str, tuple[str, ...]], ...]
) -> tuple[tuple[float, float, float], float, int]:
    detonation_rows = _single_section(sections, "*INITIAL_DETONATION")
    if len(detonation_rows) != 1:
        raise ValueError("charge initialization cards have an unsupported layout")
    detonation = _csv_numbers(detonation_rows[0])
    if len(detonation) < 5:
        raise ValueError("charge initialization values are incomplete")
    part_id = _exact_int(detonation[0], "detonation part id")
    position = tuple(float(value) for value in detonation[1:4])
    detonation_time = float(detonation[4])
    if not all(math.isfinite(value) for value in (*position, detonation_time)):
        raise ValueError("charge identity must be finite")
    return position, detonation_time, part_id  # type: ignore[return-value]


def _single_section(
    sections: tuple[tuple[str, tuple[str, ...]], ...], name: str
) -> tuple[str, ...]:
    matches = tuple(rows for keyword, rows in sections if keyword == name)
    if len(matches) != 1:
        raise ValueError(f"model must contain exactly one {name}")
    return matches[0]


def _single_float_card(
    sections: tuple[tuple[str, tuple[str, ...]], ...], name: str
) -> float:
    rows = _single_section(sections, name)
    if not rows:
        raise ValueError(f"{name} has no values")
    values = _csv_numbers(rows[0])
    if not values:
        raise ValueError(f"{name} has no numeric value")
    return float(values[0])


def _csv_numbers(row: str) -> tuple[float, ...]:
    try:
        values = tuple(float(value.strip().replace("D", "E").replace("d", "e")) for value in row.split(",") if value.strip())
    except ValueError as exc:
        raise ValueError(f"keyword row contains a nonnumeric value: {row!r}") from exc
    if not all(math.isfinite(value) for value in values):
        raise ValueError("keyword numeric values must be finite")
    return values


def _exact_int(value: float, label: str) -> int:
    if not math.isfinite(value) or value != int(value):
        raise ValueError(f"{label} must be an exact integer")
    return int(value)


def _bounds(points) -> tuple[float, float, float, float, float, float]:
    rows = tuple(points)
    if not rows:
        raise ValueError("cannot compute bounds of an empty point set")
    return (
        min(row[0] for row in rows),
        min(row[1] for row in rows),
        min(row[2] for row in rows),
        max(row[0] for row in rows),
        max(row[1] for row in rows),
        max(row[2] for row in rows),
    )


def _box_volume(bounds: tuple[float, float, float, float, float, float]) -> float:
    return math.prod(bounds[index + 3] - bounds[index] for index in range(3))


def _is_positive_axis_aligned_hex8(
    element: _Element,
    nodes: dict[int, tuple[float, float, float]],
) -> bool:
    if len(element.node_ids) != 8 or any(node_id not in nodes for node_id in element.node_ids):
        return False
    coordinates = tuple(nodes[node_id] for node_id in element.node_ids)
    bounds = _bounds(coordinates)
    x0, y0, z0, x1, y1, z1 = bounds
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
    return all(
        all(math.isclose(actual[axis], target[axis], rel_tol=0.0, abs_tol=1.0e-12) for axis in range(3))
        for actual, target in zip(coordinates, expected)
    )


def _expected_ale_boundary_faces(
    elements: tuple[_Element, ...],
    nodes: dict[int, tuple[float, float, float]],
) -> dict[str, dict[frozenset[int], tuple[int, int, int, int]]]:
    ale_node_ids = {node_id for element in elements for node_id in element.node_ids}
    if not ale_node_ids or any(node_id not in nodes for node_id in ale_node_ids):
        raise ValueError("ALE boundary topology references undefined nodes")
    x_values = {nodes[node_id][0] for node_id in ale_node_ids}
    y_values = {nodes[node_id][1] for node_id in ale_node_ids}
    z_values = {nodes[node_id][2] for node_id in ale_node_ids}
    if min(len(x_values), len(y_values), len(z_values)) < 2:
        raise ValueError("ALE boundary topology must span three dimensions")
    x_min, y_min, z_min, x_max, y_max, z_max = _bounds(
        nodes[node_id] for node_id in ale_node_ids
    )
    result: dict[str, dict[frozenset[int], tuple[int, int, int, int]]] = {
        "side": {},
        "top": {},
        "bottom": {},
    }

    def on_plane(node_id: int, axis: int, value: float) -> bool:
        return math.isclose(
            nodes[node_id][axis], value, rel_tol=0.0, abs_tol=1.0e-12
        )

    def add(kind: str, face: tuple[int, int, int, int]) -> None:
        canonical = frozenset(face)
        if len(canonical) != 4 or canonical in result[kind]:
            raise ValueError("ALE boundary topology contains a duplicate or degenerate face")
        result[kind][canonical] = face

    for element in elements:
        n1, n2, n3, n4, n5, n6, n7, n8 = element.node_ids
        if on_plane(n1, 0, x_min):
            add("side", (n1, n5, n8, n4))
        if on_plane(n2, 0, x_max):
            add("side", (n2, n3, n7, n6))
        if on_plane(n1, 1, y_min):
            add("side", (n1, n2, n6, n5))
        if on_plane(n4, 1, y_max):
            add("side", (n4, n8, n7, n3))
        if on_plane(n5, 2, z_max):
            add("top", (n5, n6, n7, n8))
        if on_plane(n1, 2, z_min):
            add("bottom", (n1, n4, n3, n2))

    nx = len(x_values) - 1
    ny = len(y_values) - 1
    nz = len(z_values) - 1
    expected_counts = {
        "side": 2 * nz * (nx + ny),
        "top": nx * ny,
        "bottom": nx * ny,
    }
    if any(len(result[kind]) != expected_counts[kind] for kind in result):
        raise ValueError("ALE outer boundary is not a complete structured box")
    return result


def _boundary_face_closure(
    actual: tuple[tuple[int, int, int, int], ...],
    expected: dict[frozenset[int], tuple[int, int, int, int]],
) -> tuple[bool, bool]:
    canonical_rows: list[frozenset[int]] = []
    for face in actual:
        canonical = frozenset(face)
        if len(canonical) != 4:
            return False, False
        canonical_rows.append(canonical)
    complete = bool(
        len(actual) == len(expected)
        and len(set(canonical_rows)) == len(canonical_rows)
        and set(canonical_rows) == set(expected)
    )
    if not complete:
        return False, False
    outward = all(
        _same_cyclic_winding(face, expected[frozenset(face)]) for face in actual
    )
    return True, outward


def _same_cyclic_winding(
    actual: tuple[int, int, int, int],
    expected: tuple[int, int, int, int],
) -> bool:
    return any(
        actual == expected[offset:] + expected[:offset]
        for offset in range(len(expected))
    )


def _boxes_overlap_positive(
    left: tuple[float, float, float, float, float, float],
    right: tuple[float, float, float, float, float, float],
) -> bool:
    return all(
        min(left[index + 3], right[index + 3])
        - max(left[index], right[index])
        > 1.0e-10
        for index in range(3)
    )


def _check(
    findings: list[ValidationFinding],
    condition: bool,
    code: str,
    message: str,
) -> None:
    if not condition:
        findings.append(ValidationFinding(code, message))
