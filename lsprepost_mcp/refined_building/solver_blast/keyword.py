"""Dependency-closed LS-DYNA R12 keyword output for solver-blast scenes."""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, TextIO

from ..artifacts import BeamElement, MeshFragment, Node, ShellElement, SolidElement
from .ale_domain import iter_ale_elements, iter_ale_nodes
from .fsi import FsiInterface, FsiSegment, extract_fsi_segments
from .materials import (
    ALE_VACUUM_MATERIAL_ID,
    AIR_EOS_ID,
    AIR_MATERIAL_ID,
    SOIL_MATERIAL_ID,
    TNT_EOS_ID,
    TNT_MATERIAL_ID,
    material_id_for_role,
    render_solver_blast_material_cards,
)
from .mesh_quality import MeshQualityReport, audit_mesh_quality
from .scene import SolverBlastScene
from .surface_topology import (
    SURFACE_CLASSES,
    SurfaceTopology,
    classify_surface_topology,
)


AIR_PART_ID = 9_001
TNT_PART_ID = 9_002
ALE_BUFFER_PART_ID = 9_003
GROUND_PART_ID = 8_001
ALE_PART_SET_ID = 91_001
EMBEDDED_BEAM_PART_SET_ID = 91_002
EMBEDDED_SOLID_PART_SET_ID = 91_003
BUILDING_FSI_SEGMENT_SET_ID = 92_001
ALE_SIDE_SEGMENT_SET_ID = 92_002
ALE_TOP_SEGMENT_SET_ID = 92_003
ALE_BOTTOM_SEGMENT_SET_ID = 92_004
GROUND_FIXED_NODE_SET_ID = 93_001
AIR_PROBE_SOLID_SET_ID = 93_002
BUILDING_RESPONSE_NODE_SET_ID = 93_003
INTERPOLATION_CONSTRAINT_ID_START = 94_001
GROUND_INTERPOLATION_CONSTRAINT_ID_START = 1_940_001
_SURFACE_TOPOLOGY_SCHEMA_VERSION = "phase18.solver_blast.surface_topology@1"
_SURFACE_TOPOLOGY_MODEL_ANCHOR_PREFIX = "$P18ST="
_MESH_QUALITY_SCHEMA_VERSION = "phase18.solver_blast.mesh_quality@1"
_MESH_QUALITY_MODEL_ANCHOR_PREFIX = "$P18MQ="
_MESH_QUALITY_CACHE: dict[str, MeshQualityReport] = {}
_MESH_QUALITY_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class SolverBlastDeckEvidence:
    model_path: Path
    manifest_path: Path
    model_sha256: str
    model_byte_count: int
    scene_fingerprint: str
    building_mesh_fingerprint: str
    fsi_fingerprint: str
    surface_topology_fingerprint: str
    surface_class_counts: tuple[tuple[str, int], ...]
    surface_boundary_face_count: int
    surface_unclassified_count: int
    surface_multiply_classified_count: int
    mesh_quality_fingerprint: str
    mesh_quality_solid_count: int
    mesh_quality_shell_count: int
    mesh_quality_beam_count: int
    mesh_quality_minimum_corner_jacobian_m3: float
    mesh_quality_maximum_aspect_ratio: float
    mesh_quality_orphan_node_count: int
    mesh_quality_duplicate_element_count: int
    mesh_quality_solid_overlap_pair_count: int
    mesh_quality_unresolved_overlap_candidate_count: int
    mesh_quality_finding_count: int
    fsi_slave_segment_count: int
    ground_fsi_segment_count: int
    total_fsi_segment_count: int
    building_ground_contact_segment_count: int
    ground_contact_segment_count: int
    structural_constraint_count: int
    ale_node_count: int
    ale_element_count: int
    ale_air_element_count: int
    ale_buffer_element_count: int
    tnt_element_count: int
    side_nonreflecting_segment_count: int
    top_nonreflecting_segment_count: int
    bottom_nonreflecting_segment_count: int
    bottom_no_flow_segment_count: int
    bottom_closed_node_count: int
    total_node_count: int
    total_element_count: int
    part_ids: tuple[tuple[str, int], ...]
    engineering_validated: bool
    requires_project_review: bool


@dataclass(frozen=True, slots=True)
class _PartSpec:
    role: str
    part_id: int
    section_id: int
    material_id: int
    eos_id: int
    family: str
    dimensions_m: tuple[float, float, float]


def write_solver_blast_deck(
    scene: SolverBlastScene,
    output_dir: Path,
) -> SolverBlastDeckEvidence:
    if not isinstance(scene, SolverBlastScene):
        raise TypeError("scene must be a SolverBlastScene")
    directory = Path(output_dir)
    if directory.exists():
        if not directory.is_dir():
            raise ValueError("output directory path must be a directory")
        if any(directory.iterdir()):
            raise ValueError("output directory must be empty")
    else:
        directory.mkdir(parents=True)

    surface_topology = classify_surface_topology(scene)
    building_mesh_fingerprint = surface_topology.building_mesh.fingerprint
    mesh_quality = _cached_mesh_quality(
        scene.building.fingerprint,
        building_mesh_fingerprint,
        surface_topology.building_mesh,
        scene.building.members,
    )
    if mesh_quality.findings:
        summary = "; ".join(
            f"{row.finding_id}:{row.member_role}"
            for row in mesh_quality.findings[:8]
        )
        raise ValueError(
            "solver structural mesh failed closed quality audit: " + summary
        )
    fsi = extract_fsi_segments(scene, surface_topology)
    surface_class_counts = tuple(
        (surface_class, surface_topology.counts[surface_class])
        for surface_class in SURFACE_CLASSES
    )
    exposed_surface_count = sum(
        surface_topology.counts[surface_class]
        for surface_class in ("external_air_exposed", "internal_air_exposed")
    )
    if len(fsi.segments) != exposed_surface_count:
        raise ValueError(
            "FSI slave segments do not close against active-air-exposed surfaces"
        )
    beam_orientation_nodes, beam_orientation_ids = _beam_orientation_nodes(
        scene,
        fsi.building_mesh,
    )
    part_specs = _building_part_specs(scene, fsi.building_mesh)
    part_by_role = {row.role: row.part_id for row in part_specs}
    material_roles = tuple(member.material_role for member in scene.building.members)
    material_lines, material_evidence = render_solver_blast_material_cards(
        material_roles
    )
    temporary_path = directory / ".model.k.tmp"
    model_path = directory / "model.k"
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as stream:
            _write_header(stream, scene, surface_topology, mesh_quality)
            _write_nodes(stream, scene, fsi.building_mesh, beam_orientation_nodes)
            _write_elements(
                stream,
                scene,
                fsi.building_mesh,
                part_by_role,
                beam_orientation_ids,
            )
            _write_parts_and_sections(stream, part_specs)
            _write_ale_parts_and_sections(stream)
            _write_lines(stream, material_lines)
            structural_constraint_ids = _write_structural_constraints(
                stream,
                scene,
                fsi.building_mesh,
                part_by_role,
            )
            _write_initialization_and_fsi(stream, scene, fsi)
            _write_boundaries_and_databases(stream, scene, fsi, part_by_role)
            stream.write("*END\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, model_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    model_payload = model_path.read_bytes()
    model_sha256 = hashlib.sha256(model_payload).hexdigest()
    building_element_count = len(
        (*fsi.building_mesh.solids, *fsi.building_mesh.shells, *fsi.building_mesh.beams)
    )
    ground_node_count = sum(len(fragment.nodes) for fragment in scene.ground.fragments)
    ground_element_count = sum(
        len(fragment.solids) for fragment in scene.ground.fragments
    )
    evidence = SolverBlastDeckEvidence(
        model_path=model_path,
        manifest_path=directory / "manifest.json",
        model_sha256=model_sha256,
        model_byte_count=len(model_payload),
        scene_fingerprint=scene.fingerprint,
        building_mesh_fingerprint=building_mesh_fingerprint,
        fsi_fingerprint=fsi.fingerprint,
        surface_topology_fingerprint=surface_topology.fingerprint,
        surface_class_counts=surface_class_counts,
        surface_boundary_face_count=surface_topology.boundary_face_count,
        surface_unclassified_count=surface_topology.unclassified_count,
        surface_multiply_classified_count=surface_topology.multiply_classified_count,
        mesh_quality_fingerprint=mesh_quality.fingerprint,
        mesh_quality_solid_count=mesh_quality.solid_count,
        mesh_quality_shell_count=mesh_quality.shell_count,
        mesh_quality_beam_count=mesh_quality.beam_count,
        mesh_quality_minimum_corner_jacobian_m3=(
            mesh_quality.minimum_corner_jacobian_m3
        ),
        mesh_quality_maximum_aspect_ratio=mesh_quality.maximum_aspect_ratio,
        mesh_quality_orphan_node_count=mesh_quality.orphan_node_count,
        mesh_quality_duplicate_element_count=mesh_quality.duplicate_element_count,
        mesh_quality_solid_overlap_pair_count=mesh_quality.solid_overlap_pair_count,
        mesh_quality_unresolved_overlap_candidate_count=(
            mesh_quality.unresolved_overlap_candidate_count
        ),
        mesh_quality_finding_count=len(mesh_quality.findings),
        fsi_slave_segment_count=len(fsi.segments),
        ground_fsi_segment_count=len(fsi.ground_segments),
        total_fsi_segment_count=len(fsi.segments) + len(fsi.ground_segments),
        building_ground_contact_segment_count=len(
            fsi.building_ground_contact_segments
        ),
        ground_contact_segment_count=len(fsi.ground_contact_segments),
        structural_constraint_count=len(structural_constraint_ids),
        ale_node_count=scene.air.node_count,
        ale_element_count=scene.air.element_count,
        ale_air_element_count=scene.air.air_element_count,
        ale_buffer_element_count=scene.air.buffer_element_count,
        tnt_element_count=scene.air.tnt_element_count,
        side_nonreflecting_segment_count=_ale_side_segment_count(scene),
        top_nonreflecting_segment_count=_ale_top_segment_count(scene),
        bottom_nonreflecting_segment_count=0,
        bottom_no_flow_segment_count=_ale_bottom_segment_count(scene),
        bottom_closed_node_count=_ale_bottom_node_count(scene),
        total_node_count=(
            len(fsi.building_mesh.nodes)
            + len(beam_orientation_nodes)
            + ground_node_count
            + scene.air.node_count
        ),
        total_element_count=(
            building_element_count + ground_element_count + scene.air.element_count
        ),
        part_ids=tuple(
            sorted(
                {
                    **part_by_role,
                    scene.ground.part_role: GROUND_PART_ID,
                    scene.air.part_role: AIR_PART_ID,
                    scene.air.buffer_part_role: ALE_BUFFER_PART_ID,
                    scene.charge.material_role: TNT_PART_ID,
                }.items()
            )
        ),
        engineering_validated=False,
        requires_project_review=True,
    )
    manifest = {
        "schema_version": "phase18.solver_blast.deck_manifest@4",
        "unit_system": "SI_m_s_kg_N_Pa",
        "model": {
            "path": "model.k",
            "sha256": evidence.model_sha256,
            "byte_count": evidence.model_byte_count,
        },
        "scene_fingerprint": evidence.scene_fingerprint,
        "building_mesh_fingerprint": evidence.building_mesh_fingerprint,
        "fsi_fingerprint": evidence.fsi_fingerprint,
        "surface_topology": {
            "schema_version": _SURFACE_TOPOLOGY_SCHEMA_VERSION,
            "fingerprint": evidence.surface_topology_fingerprint,
            "counts": [list(row) for row in evidence.surface_class_counts],
            "boundary_face_count": evidence.surface_boundary_face_count,
            "unclassified_count": evidence.surface_unclassified_count,
            "multiply_classified_count": evidence.surface_multiply_classified_count,
        },
        "mesh_quality": {
            "schema_version": _MESH_QUALITY_SCHEMA_VERSION,
            "fingerprint": evidence.mesh_quality_fingerprint,
            "solid_count": evidence.mesh_quality_solid_count,
            "shell_count": evidence.mesh_quality_shell_count,
            "beam_count": evidence.mesh_quality_beam_count,
            "minimum_corner_jacobian_m3": (
                evidence.mesh_quality_minimum_corner_jacobian_m3
            ),
            "maximum_aspect_ratio": evidence.mesh_quality_maximum_aspect_ratio,
            "orphan_node_count": evidence.mesh_quality_orphan_node_count,
            "duplicate_element_count": evidence.mesh_quality_duplicate_element_count,
            "solid_overlap_pair_count": (
                evidence.mesh_quality_solid_overlap_pair_count
            ),
            "unresolved_overlap_candidate_count": (
                evidence.mesh_quality_unresolved_overlap_candidate_count
            ),
            "finding_count": evidence.mesh_quality_finding_count,
        },
        "fsi_slave_segment_count": evidence.fsi_slave_segment_count,
        "ground_fsi_segment_count": evidence.ground_fsi_segment_count,
        "total_fsi_segment_count": evidence.total_fsi_segment_count,
        "building_ground_contact_segment_count": (
            evidence.building_ground_contact_segment_count
        ),
        "ground_contact_segment_count": evidence.ground_contact_segment_count,
        "structural_constraint_count": evidence.structural_constraint_count,
        "ale_node_count": evidence.ale_node_count,
        "ale_element_count": evidence.ale_element_count,
        "ale_air_element_count": evidence.ale_air_element_count,
        "tnt_element_count": evidence.tnt_element_count,
        "total_node_count": evidence.total_node_count,
        "total_element_count": evidence.total_element_count,
        "part_ids": [list(row) for row in evidence.part_ids],
        "materials": asdict(material_evidence),
        "charge": {
            "geometry_kind": scene.charge.geometry_kind,
            "mass_kg": scene.charge.mass_kg,
            "position_m": list(scene.charge.position_m),
            "radius_m": scene.charge.radius_m,
            "volume_m3": scene.charge.volume_m3,
            "side_length_m": scene.charge.side_length_m,
            "bounds_m": list(scene.charge.bounds_m),
            "solid_element_count": scene.air.tnt_element_count,
            "realized_mass_kg": scene.air.realized_tnt_mass_kg,
            "detonation_time_s": scene.charge.detonation_time_s,
        },
        "engineering_validated": False,
        "requires_project_review": True,
    }
    _atomic_json(evidence.manifest_path, manifest)
    return evidence


def _write_header(
    stream: TextIO,
    scene: SolverBlastScene,
    surface_topology: SurfaceTopology,
    mesh_quality: MeshQualityReport,
) -> None:
    _write_lines(
        stream,
        [
            "*KEYWORD",
            "$ Phase 18 solver-complete candidate: visible MM-ALE air, movable TNT, real FSI",
            "$ SI_m_s_kg_N_Pa; engineering validation and project review remain required",
            (
                _SURFACE_TOPOLOGY_MODEL_ANCHOR_PREFIX + surface_topology.fingerprint
            ),
            _MESH_QUALITY_MODEL_ANCHOR_PREFIX + mesh_quality.fingerprint,
            "*TITLE",
            f"Phase18 {scene.building.resource_id} ALE FSI",
            "*CONTROL_TERMINATION",
            "$#  endtim",
            _number(scene.config.termination_time_s),
            "*CONTROL_TIMESTEP",
            "$#  dtinit    tssfac      isdo    tslimt     dt2ms      lctm     erode     ms1st",
            "0,0.67,0,0,0,0,0,0",
            "*CONTROL_ENERGY",
            "$#    hgen      rwen    slnten     rylen",
            "2,2,2,2",
            "*CONTROL_ALE",
            "$#     dct      nadv      meth      afac      bfac      cfac      dfac      efac",
            "-1,1,2,-1.0,0.0,0.0,0.0,0.0",
            "$#   start       end     aafac     vfact    vlimit       ebc      pref   nsidebc",
            "0.0,1.0e20,1.0,1.0e-6,0,0,101325.0,0",
        ],
    )


def _cached_mesh_quality(
    building_fingerprint: str,
    mesh_fingerprint: str,
    mesh: MeshFragment,
    members: tuple,
) -> MeshQualityReport:
    cache_key = building_fingerprint + ":" + mesh_fingerprint
    with _MESH_QUALITY_CACHE_LOCK:
        cached = _MESH_QUALITY_CACHE.get(cache_key)
    if cached is not None:
        return cached
    report = audit_mesh_quality(mesh, members)
    with _MESH_QUALITY_CACHE_LOCK:
        existing = _MESH_QUALITY_CACHE.setdefault(cache_key, report)
    return existing


def _write_nodes(
    stream: TextIO,
    scene: SolverBlastScene,
    building_mesh: MeshFragment,
    beam_orientation_nodes: tuple[Node, ...],
) -> None:
    stream.write("*NODE\n$#   nid               x               y               z\n")
    for node in building_mesh.nodes:
        stream.write(
            f"{node.node_id},{_number(node.x)},{_number(node.y)},{_number(node.z)}\n"
        )
    for node in beam_orientation_nodes:
        stream.write(
            f"{node.node_id},{_number(node.x)},{_number(node.y)},{_number(node.z)}\n"
        )
    for fragment in scene.ground.fragments:
        for node in fragment.nodes:
            stream.write(
                f"{node.node_id},{_number(node.x)},{_number(node.y)},{_number(node.z)}\n"
            )
    for node in iter_ale_nodes(scene.air):
        stream.write(
            f"{node.node_id},{_number(node.x)},{_number(node.y)},{_number(node.z)}\n"
        )


def _write_elements(
    stream: TextIO,
    scene: SolverBlastScene,
    building_mesh: MeshFragment,
    part_by_role: dict[str, int],
    beam_orientation_ids: dict[int, int],
) -> None:
    stream.write(
        "*ELEMENT_SOLID\n"
        "$#   eid     pid      n1      n2      n3      n4      n5      n6      n7      n8\n"
    )
    for element in building_mesh.solids:
        _write_element(stream, element, part_by_role[element.part_role])
    for fragment in scene.ground.fragments:
        for element in fragment.solids:
            _write_element(stream, element, GROUND_PART_ID)
    ale_part_by_role = {
        scene.air.part_role: AIR_PART_ID,
        scene.air.buffer_part_role: ALE_BUFFER_PART_ID,
        scene.air.tnt_part_role: TNT_PART_ID,
    }
    for element in iter_ale_elements(scene.air):
        try:
            part_id = ale_part_by_role[element.part_role]
        except KeyError as exc:
            raise ValueError(
                f"ALE element references an unknown material role: {element.part_role!r}"
            ) from exc
        _write_element(stream, element, part_id)
    if building_mesh.shells:
        stream.write("*ELEMENT_SHELL\n$#   eid     pid      n1      n2      n3      n4\n")
        for element in building_mesh.shells:
            _write_element(stream, element, part_by_role[element.part_role])
    if building_mesh.beams:
        stream.write("*ELEMENT_BEAM\n$#   eid     pid      n1      n2      n3\n")
        for element in building_mesh.beams:
            values = (
                element.element_id,
                part_by_role[element.part_role],
                *element.node_ids,
                beam_orientation_ids[element.element_id],
            )
            if any(value < 0 or value > 99_999_999 for value in values):
                raise ValueError("LS-DYNA R12 element identifiers must fit an 8-column field")
            stream.write("".join(f"{value:>8d}" for value in values) + "\n")


def _beam_orientation_nodes(
    scene: SolverBlastScene,
    building_mesh: MeshFragment,
) -> tuple[tuple[Node, ...], dict[int, int]]:
    if not building_mesh.beams:
        return (), {}
    node_map = {node.node_id: node for node in building_mesh.nodes}
    member_orientation = {
        member.role: member.orientation_vector
        for member in scene.building.members
        if member.element_family == "Beam"
    }
    next_id = scene.air.node_id_start + scene.air.node_count
    if next_id + len(building_mesh.beams) > 99_999_999:
        raise ValueError("LS-DYNA R12 beam orientation-node identifier budget exceeded")
    nodes: list[Node] = []
    ids: dict[int, int] = {}
    for offset, element in enumerate(building_mesh.beams):
        start = node_map[element.node_ids[0]].coordinates
        end = node_map[element.node_ids[1]].coordinates
        axis = _unit_vector(tuple(end[index] - start[index] for index in range(3)))
        candidates = (
            member_orientation.get(element.part_role),
            (0.0, 0.0, 1.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
        )
        perpendicular = None
        for candidate in candidates:
            if candidate is None:
                continue
            projection = math.fsum(candidate[index] * axis[index] for index in range(3))
            residual = tuple(
                candidate[index] - projection * axis[index] for index in range(3)
            )
            length = math.sqrt(math.fsum(value * value for value in residual))
            if length > 1.0e-8:
                perpendicular = tuple(value / length for value in residual)
                break
        if perpendicular is None:
            raise ValueError(f"beam {element.element_id} has no valid orientation basis")
        node_id = next_id + offset
        ids[element.element_id] = node_id
        nodes.append(
            Node(
                node_id,
                *(start[index] + perpendicular[index] for index in range(3)),
            )
        )
    return tuple(nodes), ids


def _unit_vector(value: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(math.fsum(component * component for component in value))
    if length <= 1.0e-12:
        raise ValueError("beam contains a zero-length axis")
    return tuple(component / length for component in value)  # type: ignore[return-value]


def _write_element(
    stream: TextIO,
    element: SolidElement | ShellElement | BeamElement,
    part_id: int,
) -> None:
    values = (element.element_id, part_id, *element.node_ids)
    if any(value < 0 or value > 99_999_999 for value in values):
        raise ValueError("LS-DYNA R12 element identifiers must fit an 8-column field")
    stream.write("".join(f"{value:>8d}" for value in values) + "\n")


def _building_part_specs(
    scene: SolverBlastScene,
    building_mesh: MeshFragment,
) -> tuple[_PartSpec, ...]:
    members = {row.role: row for row in scene.building.members}
    roles = sorted(
        {
            row.part_role
            for row in (*building_mesh.solids, *building_mesh.shells, *building_mesh.beams)
        }
    )
    missing = set(roles) - set(members)
    if missing:
        raise ValueError(f"building mesh roles lack physical member records: {sorted(missing)}")
    return tuple(
        _PartSpec(
            role=role,
            part_id=1_000 + index,
            section_id=1_000 + index,
            material_id=material_id_for_role(members[role].material_role),
            eos_id=0,
            family=members[role].element_family,
            dimensions_m=members[role].dimensions_m,
        )
        for index, role in enumerate(roles, start=1)
    )


def _write_parts_and_sections(
    stream: TextIO,
    specs: tuple[_PartSpec, ...],
) -> None:
    for spec in specs:
        _write_lines(
            stream,
            [
                "*PART",
                spec.role,
                "$#     pid     secid       mid     eosid      hgid      grav    adpopt      tmid",
                f"{spec.part_id},{spec.section_id},{spec.material_id},{spec.eos_id},0,0,0,0",
            ],
        )
        if spec.family == "Solid":
            _write_lines(
                stream,
                ["*SECTION_SOLID", "$# secid    elform", f"{spec.section_id},1"],
            )
        elif spec.family == "Shell":
            thickness = spec.dimensions_m[2]
            _write_lines(
                stream,
                [
                    "*SECTION_SHELL",
                    "$# secid    elform      shrf       nip     propt",
                    f"{spec.section_id},2,0.833,5,1.0",
                    "$#     t1        t2        t3        t4      nloc",
                    f"{_number(thickness)},{_number(thickness)},{_number(thickness)},{_number(thickness)},0",
                ],
            )
        elif spec.family == "Beam":
            width, height = spec.dimensions_m[1], spec.dimensions_m[2]
            _write_lines(
                stream,
                [
                    "*SECTION_BEAM",
                    "$# secid    elform      shrf        qr       cst     scoor       nsm",
                    f"{spec.section_id},1,1.0,2,1,0,0",
                    "$#     ts1       ts2       tt1       tt2     nsloc     ntloc",
                    f"{_number(width)},{_number(height)},0,0,0,0",
                ],
            )
        else:
            raise ValueError(f"unsupported physical element family: {spec.family!r}")


def _write_ale_parts_and_sections(stream: TextIO) -> None:
    _write_lines(
        stream,
        [
            "*PART",
            "Diagnostic soil ground",
            f"{GROUND_PART_ID},{GROUND_PART_ID},{SOIL_MATERIAL_ID},0,0,0,0,0",
            "*SECTION_SOLID",
            f"{GROUND_PART_ID},1",
            "*PART",
            "Visible MM-ALE air domain",
            f"{AIR_PART_ID},{AIR_PART_ID},{AIR_MATERIAL_ID},{AIR_EOS_ID},0,0,0,0",
            "*PART",
            "Movable TNT material group",
            f"{TNT_PART_ID},{TNT_PART_ID},{TNT_MATERIAL_ID},{TNT_EOS_ID},0,0,0,0",
            "*PART",
            "ale_coupling_buffer",
            f"{ALE_BUFFER_PART_ID},{ALE_BUFFER_PART_ID},{ALE_VACUUM_MATERIAL_ID},0,0,0,0,0",
            "*SECTION_SOLID",
            f"{AIR_PART_ID},11",
            "*SECTION_SOLID",
            f"{TNT_PART_ID},11",
            "*SECTION_SOLID",
            f"{ALE_BUFFER_PART_ID},11",
            "*ALE_MULTI-MATERIAL_GROUP",
            "$#     sid    idtype",
            f"{AIR_PART_ID},1",
            f"{TNT_PART_ID},1",
            f"{ALE_BUFFER_PART_ID},1",
        ],
    )


def _write_initialization_and_fsi(
    stream: TextIO,
    scene: SolverBlastScene,
    fsi: FsiInterface,
) -> None:
    x, y, z = scene.charge.position_m
    _write_lines(
        stream,
        [
            "*INITIAL_DETONATION",
            "$#     pid        x0        y0        z0        lt",
            f"{TNT_PART_ID},{_number(x)},{_number(y)},{_number(z)},{_number(scene.charge.detonation_time_s)}",
            "*SET_PART_LIST_TITLE",
            "ALE active air, TNT, and coupling-buffer material parts",
            str(ALE_PART_SET_ID),
            f"{AIR_PART_ID},{TNT_PART_ID},{ALE_BUFFER_PART_ID}",
            "*SET_SEGMENT_TITLE",
            "Physical building and exposed ground ALE FSI",
            f"{BUILDING_FSI_SEGMENT_SET_ID},0,0,0,0",
        ],
    )
    for segment in fsi.segments:
        stream.write(",".join(str(value) for value in segment.node_ids) + "\n")
    for segment in fsi.ground_segments:
        stream.write(",".join(str(value) for value in segment.node_ids) + "\n")
    _write_lines(
        stream,
        [
            "*CONSTRAINED_LAGRANGE_IN_SOLID",
            "$#   slave    master     sstyp     mstyp     nquad     ctype     direc     mcoup",
            f"{BUILDING_FSI_SEGMENT_SET_ID},{ALE_PART_SET_ID},2,0,1,4,2,0",
            "$#   start       end      pfac      fric    frcmin      norm   normtyp      damp",
            "0,0,0.1,0,0.3,0,0,0.1",
            "$#       k      hmin      hmax     ileak     pleak   lcidpor     nvent    iblock",
            "0,0,0,2,0.1,0,0,0",
            "$#   iboxid   ipenchk   intforc   ialesof    lagmul    pfacmm       thk",
            "0,1,0,0,0,0,0",
        ],
    )
    for index, (dependent, independent_rows) in enumerate(
        _building_ground_interpolations(scene, fsi)
    ):
        _write_lines(
            stream,
            [
                "*CONSTRAINED_INTERPOLATION",
                "$#    icid      dnid      ddof",
                (
                    f"{GROUND_INTERPOLATION_CONSTRAINT_ID_START + index:>10}"
                    f"{dependent:>10}{123:>10}"
                ),
                "$#    inid      idof    twghtx    twghty    twghtz    rwghtx    rwghty    rwghtz",
            ],
        )
        for node_id, weight in independent_rows:
            stream.write(_interpolation_node_card(node_id, weight) + "\n")


def _building_ground_interpolations(
    scene: SolverBlastScene,
    fsi: FsiInterface,
) -> tuple[tuple[int, tuple[tuple[int, float], ...]], ...]:
    building_nodes = {
        node.node_id: node.coordinates for node in fsi.building_mesh.nodes
    }
    ground_nodes = {
        node.node_id: node.coordinates
        for fragment in scene.ground.fragments
        for node in fragment.nodes
    }
    master_groups = _group_contact_segments_by_plane(
        fsi.ground_contact_segments,
        ground_nodes,
        scene.building.bounds_m,
    )
    order = {"x_min": 0, "x_max": 1, "y_min": 2, "y_max": 3, "z_min": 4}
    node_planes: dict[int, set[str]] = {}
    for segment in fsi.building_ground_contact_segments:
        plane = _contact_plane_label(segment, building_nodes, scene.building.bounds_m)
        if plane not in master_groups:
            raise ValueError("building and ground contact planes do not have exact closure")
        for node_id in segment.node_ids:
            node_planes.setdefault(node_id, set()).add(plane)

    result: list[tuple[int, tuple[tuple[int, float], ...]]] = []
    for dependent in sorted(node_planes):
        point = building_nodes[dependent]
        candidates = [
            (order[plane], segment.owner_element_id, segment.node_ids, plane)
            for plane in node_planes[dependent]
            for segment in master_groups[plane]
            if _point_is_on_contact_segment(point, segment, ground_nodes, plane)
        ]
        if not candidates:
            raise ValueError(
                f"building-ground dependent node {dependent} has no containing ground face"
            )
        _, _, node_ids, plane = min(candidates)
        weights = _axis_aligned_quad_weights(point, node_ids, ground_nodes, plane)
        result.append((dependent, weights))
    return tuple(result)


def _point_is_on_contact_segment(
    point: tuple[float, float, float],
    segment: FsiSegment,
    nodes: dict[int, tuple[float, float, float]],
    plane: str,
) -> bool:
    axis, first_axis, second_axis = _contact_plane_axes(plane)
    tolerance = 1.0e-9
    points = tuple(nodes[node_id] for node_id in segment.node_ids)
    return (
        abs(point[axis] - points[0][axis]) <= tolerance
        and min(row[first_axis] for row in points) - tolerance
        <= point[first_axis]
        <= max(row[first_axis] for row in points) + tolerance
        and min(row[second_axis] for row in points) - tolerance
        <= point[second_axis]
        <= max(row[second_axis] for row in points) + tolerance
    )


def _axis_aligned_quad_weights(
    point: tuple[float, float, float],
    node_ids: tuple[int, int, int, int],
    nodes: dict[int, tuple[float, float, float]],
    plane: str,
) -> tuple[tuple[int, float], ...]:
    _, first_axis, second_axis = _contact_plane_axes(plane)
    points = tuple(nodes[node_id] for node_id in node_ids)
    first_min = min(row[first_axis] for row in points)
    first_max = max(row[first_axis] for row in points)
    second_min = min(row[second_axis] for row in points)
    second_max = max(row[second_axis] for row in points)
    if first_max <= first_min or second_max <= second_min:
        raise ValueError("building-ground master face must have positive dimensions")
    first_fraction = max(
        0.0,
        min(1.0, (point[first_axis] - first_min) / (first_max - first_min)),
    )
    second_fraction = max(
        0.0,
        min(1.0, (point[second_axis] - second_min) / (second_max - second_min)),
    )
    weighted_rows = tuple(
        (
            node_id,
            (first_fraction if row[first_axis] > first_min else 1.0 - first_fraction)
            * (
                second_fraction
                if row[second_axis] > second_min
                else 1.0 - second_fraction
            ),
        )
        for node_id, row in zip(node_ids, points)
    )
    rows = tuple((node_id, weight) for node_id, weight in weighted_rows if weight > 1.0e-12)
    if not rows:
        raise ValueError("building-ground interpolation contains no positive weight")
    if not math.isclose(math.fsum(weight for _, weight in rows), 1.0, abs_tol=1.0e-9):
        raise ValueError("building-ground interpolation weights do not close")
    return rows


def _contact_plane_axes(plane: str) -> tuple[int, int, int]:
    if plane in {"x_min", "x_max"}:
        return 0, 1, 2
    if plane in {"y_min", "y_max"}:
        return 1, 0, 2
    if plane == "z_min":
        return 2, 0, 1
    raise ValueError(f"unsupported building-ground contact plane: {plane!r}")


def _group_contact_segments_by_plane(
    segments: tuple[FsiSegment, ...],
    nodes: dict[int, tuple[float, float, float]],
    bounds: tuple[float, float, float, float, float, float],
) -> dict[str, list[FsiSegment]]:
    groups: dict[str, list[FsiSegment]] = {}
    for segment in segments:
        plane = _contact_plane_label(segment, nodes, bounds)
        groups.setdefault(plane, []).append(segment)
    return groups


def _contact_plane_label(
    segment: FsiSegment,
    nodes: dict[int, tuple[float, float, float]],
    bounds: tuple[float, float, float, float, float, float],
) -> str:
    tolerance = 1.0e-9
    points = tuple(nodes[node_id] for node_id in segment.node_ids)
    candidates = (
        ("x_min", 0, bounds[0]),
        ("x_max", 0, bounds[3]),
        ("y_min", 1, bounds[1]),
        ("y_max", 1, bounds[4]),
        ("z_min", 2, bounds[2]),
    )
    for label, axis, value in candidates:
        if all(abs(point[axis] - value) <= tolerance for point in points):
            return label
    raise ValueError("building-ground contact segment is not on a reviewed plane")


def _write_structural_constraints(
    stream: TextIO,
    scene: SolverBlastScene,
    building_mesh: MeshFragment,
    part_by_role: dict[str, int],
) -> tuple[str, ...]:
    role_nodes: dict[str, set[int]] = {}
    for element in (*building_mesh.solids, *building_mesh.shells, *building_mesh.beams):
        role_nodes.setdefault(element.part_role, set()).update(element.node_ids)

    embedded = tuple(
        row
        for row in scene.building.interfaces
        if row.connection_type == "embedded_beam_in_solid"
        or row.evidence_kind == "artifact_connection:embedded_rebar"
    )
    rendered_ids: list[str] = []
    if embedded:
        beam_roles = tuple(sorted({role for row in embedded for role in row.source_roles}))
        solid_roles = tuple(sorted({role for row in embedded for role in row.target_roles}))
        if not beam_roles or not solid_roles:
            raise ValueError("embedded reinforcement interface must bind beam and solid roles")
        _write_lines(
            stream,
            [
                "*SET_PART_LIST_TITLE",
                "Embedded reinforcement beam parts",
                str(EMBEDDED_BEAM_PART_SET_ID),
            ],
        )
        _write_id_rows(stream, (part_by_role[role] for role in beam_roles))
        _write_lines(
            stream,
            [
                "*SET_PART_LIST_TITLE",
                "Reinforced concrete host solid parts",
                str(EMBEDDED_SOLID_PART_SET_ID),
            ],
        )
        _write_id_rows(stream, (part_by_role[role] for role in solid_roles))
        _write_lines(
            stream,
            [
                "*CONSTRAINED_BEAM_IN_SOLID",
                "$#   slave    master     sstyp     mstyp                         ncoup      cdir",
                (
                    f"{EMBEDDED_BEAM_PART_SET_ID:>10}"
                    f"{EMBEDDED_SOLID_PART_SET_ID:>10}"
                    f"{0:>10}{0:>10}{'':>10}{'':>10}{1:>10}{0:>10}"
                ),
                "$#   start       end               axfor",
                f"{0:>10}{0:>10}{'':>10}{0:>10}",
            ],
        )
        rendered_ids.extend(row.interface_id for row in embedded)

    shell_edge_rows = tuple(
        row
        for row in scene.building.interfaces
        if row.connection_type == "tied_shell_edge_to_frame"
    )
    interpolation_index = 0
    for row in shell_edge_rows:
        if len(row.source_roles) != 1 or len(row.target_roles) != 1:
            raise ValueError("shell-edge tie must bind one shell role to one frame role")
        ties = _shell_frame_interpolations(
            building_mesh,
            row.source_roles[0],
            row.target_roles[0],
            row.connection_tolerance_m,
        )
        for dependent, independent_a, independent_b, weight_a, weight_b in ties:
            constraint_id = INTERPOLATION_CONSTRAINT_ID_START + interpolation_index
            interpolation_index += 1
            independent_rows = tuple(
                (node_id, weight)
                for node_id, weight in (
                    (independent_a, weight_a),
                    (independent_b, weight_b),
                )
                if weight > 1.0e-12
            )
            if not independent_rows or not math.isclose(
                math.fsum(weight for _, weight in independent_rows),
                1.0,
                rel_tol=0.0,
                abs_tol=1.0e-9,
            ):
                raise ValueError("shell-frame interpolation weights do not close")
            _write_lines(
                stream,
                [
                    "*CONSTRAINED_INTERPOLATION",
                    "$#    icid      dnid      ddof",
                    f"{constraint_id:>10}{dependent:>10}{123:>10}",
                    "$#    inid      idof    twghtx    twghty    twghtz    rwghtx    rwghty    rwghtz",
                    *(
                        _interpolation_node_card(node_id, weight)
                        for node_id, weight in independent_rows
                    ),
                ],
            )
        rendered_ids.append(row.interface_id)

    solid_frame_rows = tuple(
        row
        for row in scene.building.interfaces
        if row.connection_type == "tied_solid_nodes_to_frame"
    )
    for row in solid_frame_rows:
        if len(row.source_roles) != 1 or len(row.target_roles) != 1:
            raise ValueError("solid-to-frame tie must bind one Solid role to one Beam role")
        ties = _role_frame_interpolations(
            building_mesh,
            row.source_roles[0],
            row.target_roles[0],
            row.connection_tolerance_m,
        )
        for dependent, independent_a, independent_b, weight_a, weight_b in ties:
            constraint_id = INTERPOLATION_CONSTRAINT_ID_START + interpolation_index
            interpolation_index += 1
            independent_rows = tuple(
                (node_id, weight)
                for node_id, weight in (
                    (independent_a, weight_a),
                    (independent_b, weight_b),
                )
                if weight > 1.0e-12
            )
            _write_interpolation(stream, constraint_id, dependent, independent_rows)
        rendered_ids.append(row.interface_id)

    solid_support_rows = tuple(
        row
        for row in scene.building.interfaces
        if row.connection_type == "tied_solid_face_to_solid_surface"
    )
    for row in solid_support_rows:
        if len(row.source_roles) != 1 or len(row.target_roles) != 1:
            raise ValueError("solid support tie must bind one source and one target role")
        ties = _solid_surface_interpolations(
            building_mesh,
            row.source_roles[0],
            row.target_roles[0],
            row.connection_tolerance_m,
        )
        for dependent, independent_rows in ties:
            constraint_id = INTERPOLATION_CONSTRAINT_ID_START + interpolation_index
            interpolation_index += 1
            _write_interpolation(stream, constraint_id, dependent, independent_rows)
        rendered_ids.append(row.interface_id)

    for row in scene.building.interfaces:
        if row.interface_id in rendered_ids:
            continue
        shared = sum(
            len(role_nodes.get(source, set()) & role_nodes.get(target, set()))
            for source in row.source_roles
            for target in row.target_roles
        )
        if shared <= 0:
            raise ValueError(
                f"physical interface {row.interface_id!r} has no rendered constraint "
                "or welded shared nodes"
            )
        rendered_ids.append(row.interface_id)
    return tuple(rendered_ids)


def _write_interpolation(
    stream: TextIO,
    constraint_id: int,
    dependent: int,
    independent_rows: tuple[tuple[int, float], ...],
) -> None:
    if not independent_rows or not math.isclose(
        math.fsum(weight for _, weight in independent_rows),
        1.0,
        rel_tol=0.0,
        abs_tol=1.0e-9,
    ):
        raise ValueError("interpolation weights do not close")
    _write_lines(
        stream,
        [
            "*CONSTRAINED_INTERPOLATION",
            "$#    icid      dnid      ddof",
            f"{constraint_id:>10}{dependent:>10}{123:>10}",
            "$#    inid      idof    twghtx    twghty    twghtz    rwghtx    rwghty    rwghtz",
            *(
                _interpolation_node_card(node_id, weight)
                for node_id, weight in independent_rows
            ),
        ],
    )


def _shell_frame_interpolations(
    mesh: MeshFragment,
    shell_role: str,
    frame_role: str,
    tolerance_m: float,
) -> tuple[tuple[int, int, int, float, float], ...]:
    nodes = {node.node_id: node.coordinates for node in mesh.nodes}
    shells = tuple(row for row in mesh.shells if row.part_role == shell_role)
    frame = tuple(
        sorted(
            (row for row in mesh.beams if row.part_role == frame_role),
            key=lambda row: row.element_id,
        )
    )
    if not shells or not frame:
        raise ValueError("shell-to-frame interpolation requires shell and beam elements")

    edge_counts: dict[tuple[int, int], int] = {}
    for shell in shells:
        loop = shell.node_ids
        for start, end in zip(loop, (*loop[1:], loop[0])):
            edge = tuple(sorted((start, end)))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1

    candidates: dict[int, tuple[float, int, int, float]] = {}
    for edge, count in sorted(edge_counts.items()):
        if count != 1:
            continue
        edge_candidates = tuple(
            _nearest_frame_segment(nodes[node_id], frame, nodes)
            for node_id in edge
        )
        if max(row[0] for row in edge_candidates) > tolerance_m + 1.0e-12:
            continue
        for node_id, candidate in zip(edge, edge_candidates):
            previous = candidates.get(node_id)
            if previous is None or candidate < previous:
                candidates[node_id] = candidate
    if not candidates:
        raise ValueError("shell edge has no frame interpolation within tolerance")

    return tuple(
        (
            node_id,
            candidate[1],
            candidate[2],
            1.0 - candidate[3],
            candidate[3],
        )
        for node_id, candidate in sorted(candidates.items())
    )


def _role_frame_interpolations(
    mesh: MeshFragment,
    source_role: str,
    frame_role: str,
    tolerance_m: float,
) -> tuple[tuple[int, int, int, float, float], ...]:
    nodes = {node.node_id: node.coordinates for node in mesh.nodes}
    source_node_ids = sorted(
        {
            node_id
            for element in mesh.solids
            if element.part_role == source_role
            for node_id in element.node_ids
        }
    )
    frame = tuple(
        sorted(
            (element for element in mesh.beams if element.part_role == frame_role),
            key=lambda element: element.element_id,
        )
    )
    if not source_node_ids or not frame:
        raise ValueError("solid-to-frame interpolation requires Solid and Beam geometry")
    rows = []
    for node_id in source_node_ids:
        distance, start_id, end_id, fraction = _nearest_frame_segment(
            nodes[node_id], frame, nodes
        )
        if distance <= tolerance_m + 1.0e-12:
            rows.append((node_id, start_id, end_id, 1.0 - fraction, fraction))
    if not rows:
        raise ValueError("solid nodes have no frame interpolation within tolerance")
    return tuple(rows)


def _solid_surface_interpolations(
    mesh: MeshFragment,
    source_role: str,
    target_role: str,
    tolerance_m: float,
) -> tuple[tuple[int, tuple[tuple[int, float], ...]], ...]:
    nodes = {node.node_id: node.coordinates for node in mesh.nodes}
    source_nodes = sorted(
        {
            node_id
            for element in mesh.solids
            if element.part_role == source_role
            for node_id in element.node_ids
        }
    )
    if not source_nodes:
        raise ValueError("solid support interpolation has no source nodes")
    source_z = (min(nodes[node_id][2] for node_id in source_nodes), max(nodes[node_id][2] for node_id in source_nodes))
    target_faces: dict[tuple[int, int, int, int], tuple[int, int, int, int]] = {}
    face_offsets = (
        (0, 1, 2, 3),
        (4, 7, 6, 5),
        (0, 4, 5, 1),
        (1, 5, 6, 2),
        (2, 6, 7, 3),
        (3, 7, 4, 0),
    )
    for element in mesh.solids:
        if element.part_role != target_role:
            continue
        for offsets in face_offsets:
            face = tuple(element.node_ids[index] for index in offsets)
            if max(nodes[node_id][2] for node_id in face) - min(
                nodes[node_id][2] for node_id in face
            ) > tolerance_m:
                continue
            target_faces[tuple(sorted(face))] = face
    if not target_faces:
        raise ValueError("solid support interpolation has no target horizontal faces")
    target_node_ids = {node_id for face in target_faces.values() for node_id in face}
    rows: list[tuple[int, tuple[tuple[int, float], ...]]] = []
    for dependent in source_nodes:
        point = nodes[dependent]
        if not any(abs(point[2] - value) <= tolerance_m for value in source_z):
            continue
        if dependent in target_node_ids:
            continue
        candidates = tuple(
            face
            for face in target_faces.values()
            if abs(point[2] - nodes[face[0]][2]) <= tolerance_m
            and min(nodes[node_id][0] for node_id in face) - tolerance_m
            <= point[0]
            <= max(nodes[node_id][0] for node_id in face) + tolerance_m
            and min(nodes[node_id][1] for node_id in face) - tolerance_m
            <= point[1]
            <= max(nodes[node_id][1] for node_id in face) + tolerance_m
        )
        if not candidates:
            continue
        face = min(candidates)
        weights = _horizontal_quad_weights(point, face, nodes)
        rows.append((dependent, weights))
    if not rows and not any(node_id in target_node_ids for node_id in source_nodes):
        raise ValueError("solid support interpolation produced no welded or constrained nodes")
    return tuple(rows)


def _horizontal_quad_weights(
    point: tuple[float, float, float],
    node_ids: tuple[int, int, int, int],
    nodes: dict[int, tuple[float, float, float]],
) -> tuple[tuple[int, float], ...]:
    points = tuple(nodes[node_id] for node_id in node_ids)
    x_min, x_max = min(row[0] for row in points), max(row[0] for row in points)
    y_min, y_max = min(row[1] for row in points), max(row[1] for row in points)
    if x_max <= x_min or y_max <= y_min:
        raise ValueError("support face must have positive in-plane dimensions")
    x_fraction = max(0.0, min(1.0, (point[0] - x_min) / (x_max - x_min)))
    y_fraction = max(0.0, min(1.0, (point[1] - y_min) / (y_max - y_min)))
    weighted = tuple(
        (
            node_id,
            (x_fraction if row[0] > x_min else 1.0 - x_fraction)
            * (y_fraction if row[1] > y_min else 1.0 - y_fraction),
        )
        for node_id, row in zip(node_ids, points)
    )
    return tuple((node_id, weight) for node_id, weight in weighted if weight > 1.0e-12)


def _nearest_frame_segment(
    point: tuple[float, float, float],
    frame: tuple[BeamElement, ...],
    nodes: dict[int, tuple[float, float, float]],
) -> tuple[float, int, int, float]:
    best: tuple[float, int, int, float] | None = None
    for element in frame:
        start_id, end_id = element.node_ids
        start = nodes[start_id]
        end = nodes[end_id]
        direction = tuple(end[index] - start[index] for index in range(3))
        length_squared = sum(value * value for value in direction)
        if length_squared <= 0.0:
            raise ValueError("physical frame contains a zero-length beam")
        projection = sum(
            (point[index] - start[index]) * direction[index] for index in range(3)
        ) / length_squared
        fraction = max(0.0, min(1.0, projection))
        nearest = tuple(
            start[index] + fraction * direction[index] for index in range(3)
        )
        candidate = (math.dist(point, nearest), start_id, end_id, fraction)
        if best is None or candidate < best:
            best = candidate
    if best is None:
        raise ValueError("physical frame contains no beam segments")
    return best


def _interpolation_node_card(node_id: int, weight: float) -> str:
    if not math.isfinite(weight) or not 0.0 < weight <= 1.0:
        raise ValueError("interpolation weight must be finite and in (0, 1]")
    fields = (str(node_id), "123", *(_number(weight) for _ in range(6)))
    return "".join(f"{value:>10}" for value in fields)


def _write_boundaries_and_databases(
    stream: TextIO,
    scene: SolverBlastScene,
    fsi: FsiInterface,
    part_by_role: dict[str, int],
) -> None:
    _write_lines(
        stream,
        [
            "*SET_SEGMENT_TITLE",
            "MM-ALE lateral non-reflecting boundary",
            f"{ALE_SIDE_SEGMENT_SET_ID},0,0,0,0",
        ],
    )
    for face in _ale_side_segments(scene):
        stream.write(",".join(str(value) for value in face) + "\n")
    _write_lines(
        stream,
        [
            "*SET_SEGMENT_TITLE",
            "MM-ALE top non-reflecting boundary",
            f"{ALE_TOP_SEGMENT_SET_ID},0,0,0,0",
        ],
    )
    for face in _ale_top_segments(scene):
        stream.write(",".join(str(value) for value in face) + "\n")
    _write_lines(
        stream,
        [
            "*SET_SEGMENT_TITLE",
            "MM-ALE bottom no-flow-normal boundary",
            f"{ALE_BOTTOM_SEGMENT_SET_ID},0,0,0,0",
        ],
    )
    for face in _ale_bottom_segments(scene):
        stream.write(",".join(str(value) for value in face) + "\n")
    _write_lines(
        stream,
        [
            "*BOUNDARY_NON_REFLECTING",
            "$#   ssid        ad        as",
            f"{ALE_SIDE_SEGMENT_SET_ID},0,0",
            "*BOUNDARY_NON_REFLECTING",
            "$#   ssid        ad        as",
            f"{ALE_TOP_SEGMENT_SET_ID},0,0",
            "*ALE_ESSENTIAL_BOUNDARY",
            "$#      id    idtype    ictype     iexcl",
            f"{ALE_BOTTOM_SEGMENT_SET_ID},2,2,0",
            "*SET_NODE_LIST_TITLE",
            "Fixed far and bottom soil nodes",
            str(GROUND_FIXED_NODE_SET_ID),
        ],
    )
    _write_id_rows(stream, _ground_fixed_nodes(scene))
    _write_lines(
        stream,
        [
            "*BOUNDARY_SPC_SET",
            "$#  nsid       cid      dofx      dofy      dofz     dofrx     dofry     dofrz",
            f"{GROUND_FIXED_NODE_SET_ID},0,1,1,1,0,0,0",
            "*SET_SOLID_LIST_TITLE",
            "ALE air pressure probes",
            str(AIR_PROBE_SOLID_SET_ID),
        ],
    )
    _write_id_rows(stream, _air_probe_elements(scene))
    _write_lines(
        stream,
        [
            "*SET_NODE_LIST_TITLE",
            "Building response nodes",
            str(BUILDING_RESPONSE_NODE_SET_ID),
        ],
    )
    response_nodes = sorted({node for row in fsi.segments for node in row.node_ids})[:32]
    _write_id_rows(stream, response_nodes)
    output_dt = min(1.0e-4, scene.config.termination_time_s / 20.0)
    representative_part_id = part_by_role[fsi.segments[0].owner_part_role]
    _write_lines(
        stream,
        [
            "*DATABASE_BINARY_D3PLOT",
            _number(output_dt),
            "*DATABASE_GLSTAT",
            _number(output_dt),
            "*DATABASE_MATSUM",
            _number(output_dt),
            "*DATABASE_FSI",
            _number(output_dt),
            f"1,{representative_part_id},1",
            "*DATABASE_ALE_MAT",
            f"{_number(output_dt)},0",
            "*DATABASE_HISTORY_SOLID_SET",
            str(AIR_PROBE_SOLID_SET_ID),
            "*DATABASE_HISTORY_NODE_SET",
            str(BUILDING_RESPONSE_NODE_SET_ID),
        ],
    )


def _ale_side_segments(
    scene: SolverBlastScene,
) -> Iterable[tuple[int, int, int, int]]:
    nx = len(scene.air.x_coordinates) - 1
    ny = len(scene.air.y_coordinates) - 1
    nz = len(scene.air.z_coordinates) - 1

    def node_id(ix: int, iy: int, iz: int) -> int:
        return scene.air.node_id_start + iz * (ny + 1) * (nx + 1) + iy * (nx + 1) + ix

    for iz in range(nz):
        for iy in range(ny):
            yield (node_id(0, iy, iz), node_id(0, iy, iz + 1), node_id(0, iy + 1, iz + 1), node_id(0, iy + 1, iz))
            yield (node_id(nx, iy, iz), node_id(nx, iy + 1, iz), node_id(nx, iy + 1, iz + 1), node_id(nx, iy, iz + 1))
    for iz in range(nz):
        for ix in range(nx):
            yield (node_id(ix, 0, iz), node_id(ix + 1, 0, iz), node_id(ix + 1, 0, iz + 1), node_id(ix, 0, iz + 1))
            yield (node_id(ix, ny, iz), node_id(ix, ny, iz + 1), node_id(ix + 1, ny, iz + 1), node_id(ix + 1, ny, iz))


def _ale_top_segments(
    scene: SolverBlastScene,
) -> Iterable[tuple[int, int, int, int]]:
    nx = len(scene.air.x_coordinates) - 1
    ny = len(scene.air.y_coordinates) - 1
    nz = len(scene.air.z_coordinates) - 1

    def node_id(ix: int, iy: int, iz: int) -> int:
        return scene.air.node_id_start + iz * (ny + 1) * (nx + 1) + iy * (nx + 1) + ix

    for iy in range(ny):
        for ix in range(nx):
            yield (node_id(ix, iy, nz), node_id(ix + 1, iy, nz), node_id(ix + 1, iy + 1, nz), node_id(ix, iy + 1, nz))


def _ale_bottom_segments(
    scene: SolverBlastScene,
) -> Iterable[tuple[int, int, int, int]]:
    nx = len(scene.air.x_coordinates) - 1
    ny = len(scene.air.y_coordinates) - 1

    def node_id(ix: int, iy: int) -> int:
        return scene.air.node_id_start + iy * (nx + 1) + ix

    for iy in range(ny):
        for ix in range(nx):
            yield (
                node_id(ix, iy),
                node_id(ix, iy + 1),
                node_id(ix + 1, iy + 1),
                node_id(ix + 1, iy),
            )


def _ale_side_segment_count(scene: SolverBlastScene) -> int:
    nx = len(scene.air.x_coordinates) - 1
    ny = len(scene.air.y_coordinates) - 1
    nz = len(scene.air.z_coordinates) - 1
    return 2 * nz * (nx + ny)


def _ale_top_segment_count(scene: SolverBlastScene) -> int:
    nx = len(scene.air.x_coordinates) - 1
    ny = len(scene.air.y_coordinates) - 1
    return nx * ny


def _ale_bottom_segment_count(scene: SolverBlastScene) -> int:
    nx = len(scene.air.x_coordinates) - 1
    ny = len(scene.air.y_coordinates) - 1
    return nx * ny


def _ale_bottom_node_count(scene: SolverBlastScene) -> int:
    nx = len(scene.air.x_coordinates) - 1
    ny = len(scene.air.y_coordinates) - 1
    return (nx + 1) * (ny + 1)


def _ground_fixed_nodes(scene: SolverBlastScene) -> tuple[int, ...]:
    bounds = scene.ground.bounds_m
    tolerance = 1.0e-10
    result = {
        node.node_id
        for fragment in scene.ground.fragments
        for node in fragment.nodes
        if (
            abs(node.x - bounds[0]) <= tolerance
            or abs(node.x - bounds[3]) <= tolerance
            or abs(node.y - bounds[1]) <= tolerance
            or abs(node.y - bounds[4]) <= tolerance
            or abs(node.z - bounds[2]) <= tolerance
        )
    }
    if not result:
        raise ValueError("ground mesh has no far or bottom fixed nodes")
    return tuple(sorted(result))


def _air_probe_elements(scene: SolverBlastScene) -> tuple[int, ...]:
    active_count = scene.air.active_air_element_count
    targets = {
        0,
        active_count // 2,
        active_count - 1,
    }
    result: list[int] = []
    active_index = 0
    for element in iter_ale_elements(scene.air):
        if element.part_role != scene.air.part_role:
            continue
        if active_index in targets:
            result.append(element.element_id)
        active_index += 1
    if active_index != active_count or len(result) != len(targets):
        raise ValueError("ALE active-air probe selection does not close")
    return tuple(result)


def _write_id_rows(stream: TextIO, identifiers: Iterable[int]) -> None:
    values = tuple(identifiers)
    for index in range(0, len(values), 8):
        stream.write(",".join(str(value) for value in values[index : index + 8]) + "\n")


def _write_lines(stream: TextIO, lines: Iterable[str]) -> None:
    for line in lines:
        stream.write(str(line) + "\n")


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _number(value: float | int) -> str:
    if isinstance(value, int):
        return str(value)
    number = float(value)
    for precision in range(9, 0, -1):
        candidate = f"{number:.{precision}g}"
        if candidate.startswith("0."):
            candidate = candidate[1:]
        elif candidate.startswith("-0."):
            candidate = "-" + candidate[2:]
        if len(candidate) <= 10:
            return candidate
    raise ValueError(f"cannot format LS-DYNA R12 numeric field: {value!r}")
