"""Component-level model resources derived from the audited 2.k deck."""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, TextIO

from .keyword_decomposition import _float, _integer, _keyword_token, _numbers
from .phase18_reference_naming import (
    LEGACY_SOURCE_FILENAME,
    MATERIAL_RESOURCE_ALIASES,
    MODEL_DISPLAY_NAMES,
    MODEL_RESOURCE_ALIASES,
    REFERENCE_DISPLAY_NAME_EN,
    aliases_for,
)


SOURCE_2K_SHA256 = "c1c02a9e832852854b47cd3720bc9348cf48989484d25e1a54036836d0697a22"


@dataclass(frozen=True)
class ComponentResourceSpec:
    resource_id: str
    component_kind: str
    part_ids: tuple[int, ...]
    solid_count: int
    beam_count: int
    section_ids: tuple[int, ...]
    material_ids: tuple[int, ...]
    set_ids: tuple[int, ...]
    coupling: tuple[int, int, int, int]


COMPONENT_RESOURCE_SPECS = {
    "two_storey_rc_frame_beam_reference": ComponentResourceSpec(
        "two_storey_rc_frame_beam_reference", "reinforced_concrete_beam",
        (201, 202, 203), 6600, 11540, (4, 3, 1), (5, 14, 8), (1,), (1, 201, 0, 1),
    ),
    "two_storey_rc_frame_column_reference": ComponentResourceSpec(
        "two_storey_rc_frame_column_reference", "reinforced_concrete_column",
        (301, 302, 303), 6000, 12546, (4, 2, 1), (5, 12, 8), (2,), (2, 301, 0, 1),
    ),
    "two_storey_rc_frame_slab_reference": ComponentResourceSpec(
        "two_storey_rc_frame_slab_reference", "reinforced_concrete_slab",
        (401, 402), 91245, 25725, (4, 2), (5, 12), (), (402, 401, 1, 1),
    ),
    "two_storey_rc_frame_foundation_reference": ComponentResourceSpec(
        "two_storey_rc_frame_foundation_reference", "reinforced_concrete_base",
        (501, 502), 22445, 12150, (4, 6), (5, 8), (6,), (6, 501, 0, 1),
    ),
}


def component_resource_spec(resource_id: str) -> ComponentResourceSpec:
    key = str(resource_id).strip()
    key = MODEL_RESOURCE_ALIASES.get(key, key)
    try:
        return COMPONENT_RESOURCE_SPECS[key]
    except KeyError as exc:
        known = ", ".join([*COMPONENT_RESOURCE_SPECS, *MODEL_RESOURCE_ALIASES])
        raise ValueError(f"unknown component model resource '{key}'. Known resources: {known}") from exc


_PID_TO_RESOURCE = {
    pid: resource_id
    for resource_id, spec in COMPONENT_RESOURCE_SPECS.items()
    for pid in spec.part_ids
}

_PART_TITLES = {
    201: "beam concrete", 202: "beam longitudinal rebar", 203: "beam stirrup",
    301: "column concrete", 302: "column longitudinal rebar", 303: "column stirrup",
    401: "slab concrete", 402: "slab rebar", 501: "base concrete", 502: "base rebar",
}
_PART_BINDINGS = {
    201: (4, 5), 202: (3, 14), 203: (1, 8), 301: (4, 5), 302: (2, 12),
    303: (1, 8), 401: (4, 5), 402: (2, 12), 501: (4, 5), 502: (6, 8),
}
_BEAM_DIAMETER_M = {1: 0.008, 2: 0.012, 3: 0.020, 6: 0.018}
_STEEL = {
    8: (455000000.0, 0.15),
    12: (460000000.0, 0.14),
    14: (445000000.0, 0.14),
}
_CURVE_1 = (
    (-30000.0, 9.7), (-300.0, 9.7), (-100.0, 6.72), (-30.0, 4.5),
    (-10.0, 3.12), (-3.0, 2.09), (-1.0, 1.45), (-0.1, 1.36),
    (-0.01, 1.28), (-0.001, 1.2), (-9.9999997474e-05, 1.13),
    (-9.9999997474e-06, 1.06), (0.0, 1.0), (9.9999997474e-06, 1.03),
    (0.001, 1.08), (0.01, 1.14), (0.1, 1.2), (1.0, 1.26),
    (3.0, 1.29), (10.0, 1.33), (30.0, 2.04), (300.0, 2.94), (30000.0, 2.94),
)
_COUPLING_CONTROLS = {
    "two_storey_rc_frame_beam_reference": (1, 2, 2),
    "two_storey_rc_frame_column_reference": (1, 2, 2),
    "two_storey_rc_frame_slab_reference": (1, 1, 2),
    "two_storey_rc_frame_foundation_reference": (2, 1, 0),
}
_FILTERED_SET_MEMBERS = {
    "two_storey_rc_frame_beam_reference": (202, 203),
    "two_storey_rc_frame_column_reference": (302, 303),
    "two_storey_rc_frame_foundation_reference": (502,),
}
_SOURCE_SET_EXCLUSIONS = {
    "two_storey_rc_frame_beam_reference": (402,),
    "two_storey_rc_frame_column_reference": (202,),
    "two_storey_rc_frame_foundation_reference": (302,),
}


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _atomic_json(path: Path, value: object) -> None:
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_ints(line: str, layout: tuple[int, ...]) -> list[int]:
    return [_integer(field) for field in _numbers(line, layout) if field]


def _metadata_lines(spec: ComponentResourceSpec) -> list[str]:
    lines = [
        "*KEYWORD",
        "$ Phase 18A-1 component resource: Two-Storey RC Frame Blast Reference",
        "$ Original source filename retained in provenance: 2.k",
        "$ Units: SI_m_s_kg_N_Pa; status: source_reference; project review required",
    ]
    for pid in spec.part_ids:
        secid, mid = _PART_BINDINGS[pid]
        lines.extend([
            "*PART",
            _PART_TITLES[pid],
            "$#     pid     secid       mid     eosid      hgid      grav    adpopt      tmid",
            f"{pid},{secid},{mid},0,0,0,0,0",
        ])
    for secid in spec.section_ids:
        if secid == 4:
            lines.extend([
                "*SECTION_SOLID_TITLE", "concrete solid", "$#   secid    elform       aet", "4,1,0",
            ])
        else:
            diameter = _BEAM_DIAMETER_M[secid]
            lines.extend([
                "*SECTION_BEAM_TITLE", f"rebar diameter {diameter:.6g} m",
                "$#   secid    elform      shrf        qr       cst     scoor       nsm",
                f"{secid},1,1.0,2,1,0.0,0.0",
                "$#     ts1       ts2       tt1       tt2     nsloc     ntloc",
                f"{diameter:.12g},{diameter:.12g},0.0,0.0,0.0,0.0",
            ])
    if 5 in spec.material_ids:
        lines.extend([
            "*MAT_CONCRETE_DAMAGE_REL3_TITLE", "Two-Storey RC Frame concrete MID 5 normalized SI",
            "$#     mid       rho        pr", "5,2400.0,0.2",
            "$#      ft        a0        a1        a2        b1     omega       a1f",
            "0.0,-30400000.0,0.0,0.0,2.0,0.0,0.0",
            "$# slambda      nout     edrop     rsize       ucf    lcrate   locwid      npts",
            "0.0,0,0.0,39.37,0.000145,1,0.0,0",
            "0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0",
            "0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0",
            "0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0",
            "0.0,0.0,0.0,0.0,0.0,1.5,0.0,0.0",
        ])
    for mid in spec.material_ids:
        if mid == 5:
            continue
        yield_strength, failure_strain = _STEEL[mid]
        lines.extend([
            "*MAT_PLASTIC_KINEMATIC_TITLE", f"Two-Storey RC Frame rebar MID {mid} normalized SI",
            "$#     mid       rho         e        pr      sigy      etan      beta",
            f"{mid},7850.0,210000000000.0,0.3,{yield_strength:.12g},2100000000.0,0.0",
            "$#     src       srp        fs        vp",
            f"6844.0,3.91,{failure_strain:.12g},0.0",
        ])
    lines.extend([
        "*MAT_ADD_EROSION", "$#     mid      excl    mxpres     mneps    effeps    voleps    numfip       ncs",
        "5,0.0,0.0,0.0,0.0,0.0,1.0,1.0",
        "0.0,0.0,0.0,0.15,0.0,0.0,0.0,0.0",
        "0,0.0,0,0.0,1.0,0.0,0.0,0",
        "0,10,0.0,0.0,0.0",
        "*DEFINE_CURVE", "$#    lcid      sidr       sfa       sfo      offa      offo    dattyp     lcint",
        "1,0,1.0,1.0,0.0,0.0,0,0",
    ])
    lines.extend(f"{x:.12g},{y:.12g}" for x, y in _CURVE_1)
    if spec.set_ids:
        set_id = spec.set_ids[0]
        members = _FILTERED_SET_MEMBERS[spec.resource_id]
        lines.extend([
            "*SET_PART_LIST_TITLE", f"{spec.component_kind} embedded rebar parts",
            "$#     sid       da1       da2       da3       da4    solver",
            f"{set_id},0.0,0.0,0.0,0.0,MECH",
            "$#    pid1      pid2      pid3      pid4      pid5      pid6      pid7      pid8",
            ",".join(str(value) for value in (*members, *(0 for _ in range(8 - len(members))))),
        ])
    ssid, msid, sstyp, mstyp = spec.coupling
    ctype, direc, ileak = _COUPLING_CONTROLS[spec.resource_id]
    lines.extend([
        "*CONSTRAINED_LAGRANGE_IN_SOLID_TITLE", f"{spec.component_kind} embedded coupling",
        "$#   slave    master     sstyp     mstyp     nquad     ctype     direc     mcoup",
        f"{ssid},{msid},{sstyp},{mstyp},0,{ctype},{direc},0",
        "$#   start       end      pfac      fric    frcmin      norm   normtyp      damp",
        "0.0,1.0e10,0.1,0.0,0.5,0,0,0.0",
        "$#      cq      hmin      hmax     ileak     pleak   lcidpor     nvent  blockage",
        f"0.0,0.0,0.0,{ileak},0.1,0,0,0",
        "0,0,0,0,0.0,0,0.0",
    ])
    return lines


def _open_fragment_files(directory: Path, suffix: str) -> dict[str, TextIO]:
    return {
        resource_id: (directory / f"{resource_id}.{suffix}").open("w", encoding="utf-8", newline="\n")
        for resource_id in COMPONENT_RESOURCE_SPECS
    }


def write_component_resource_packages(
    report: dict[str, object],
    output_root: Path,
) -> dict[str, dict[str, str]]:
    """Split the audited structural PIDs into four dependency-closed SI bundles."""
    source = report.get("source")
    if not isinstance(source, dict) or source.get("sha256") != SOURCE_2K_SHA256:
        raise ValueError("component package writing requires the audited 2.k source SHA-256")
    source_path = Path(str(source.get("path", "")))
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    output_root.mkdir(parents=True, exist_ok=True)

    node_ids = {resource_id: set() for resource_id in COMPONENT_RESOURCE_SPECS}
    element_ids = {resource_id: set() for resource_id in COMPONENT_RESOURCE_SPECS}
    solid_counts = {resource_id: 0 for resource_id in COMPONENT_RESOURCE_SPECS}
    beam_counts = {resource_id: 0 for resource_id in COMPONENT_RESOURCE_SPECS}
    element_hashes = {resource_id: hashlib.sha256() for resource_id in COMPONENT_RESOURCE_SPECS}

    with tempfile.TemporaryDirectory(prefix="phase18a1_", dir=output_root) as temporary_name:
        temporary = Path(temporary_name)
        solid_files = _open_fragment_files(temporary, "solid")
        beam_files = _open_fragment_files(temporary, "beam")
        source_digest = hashlib.sha256()
        active = ""
        pending_solid: tuple[int, int] | None = None
        try:
            with source_path.open("rb") as source_handle:
                for byte_line in source_handle:
                    source_digest.update(byte_line)
                    line = byte_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if line.lstrip().startswith("*"):
                        active = _keyword_token(line)
                        pending_solid = None
                        continue
                    if not line.strip() or line.lstrip().startswith("$"):
                        continue
                    if active == "*ELEMENT_SOLID":
                        if pending_solid is None:
                            values = _parse_ints(line, (8, 8))
                            if len(values) >= 2:
                                pending_solid = (values[0], values[1])
                            continue
                        connectivity = _parse_ints(line, (8,) * 10)
                        eid, pid = pending_solid
                        pending_solid = None
                        resource_id = _PID_TO_RESOURCE.get(pid)
                        if resource_id is None:
                            continue
                        row = [eid, pid, *connectivity]
                        solid_files[resource_id].write(",".join(str(value) for value in row) + "\n")
                        node_ids[resource_id].update(value for value in connectivity if value != 0)
                        element_ids[resource_id].add(eid)
                        solid_counts[resource_id] += 1
                        element_hashes[resource_id].update((",".join(str(value) for value in row) + "\n").encode())
                    elif active == "*ELEMENT_BEAM":
                        values = _parse_ints(line, (8,) * 5)
                        if len(values) < 5:
                            continue
                        eid, pid, n1, n2, n3 = values[:5]
                        resource_id = _PID_TO_RESOURCE.get(pid)
                        if resource_id is None:
                            continue
                        row = [eid, pid, n1, n2, n3]
                        beam_files[resource_id].write(",".join(str(value) for value in row) + "\n")
                        node_ids[resource_id].update((n1, n2, n3))
                        element_ids[resource_id].add(eid)
                        beam_counts[resource_id] += 1
                        element_hashes[resource_id].update((",".join(str(value) for value in row) + "\n").encode())
        finally:
            for handle in (*solid_files.values(), *beam_files.values()):
                handle.close()
        if source_digest.hexdigest() != SOURCE_2K_SHA256:
            raise ValueError("source SHA-256 changed while extracting component elements")

        for resource_id, spec in COMPONENT_RESOURCE_SPECS.items():
            if solid_counts[resource_id] != spec.solid_count or beam_counts[resource_id] != spec.beam_count:
                raise ValueError(
                    f"{resource_id} element count mismatch: solid={solid_counts[resource_id]}, beam={beam_counts[resource_id]}"
                )

        node_files = _open_fragment_files(temporary, "node")
        node_counts = {resource_id: 0 for resource_id in COMPONENT_RESOURCE_SPECS}
        bounds: dict[str, list[list[float]]] = {
            resource_id: [[float("inf")] * 3, [float("-inf")] * 3]
            for resource_id in COMPONENT_RESOURCE_SPECS
        }
        active = ""
        try:
            with source_path.open("rb") as source_handle:
                for byte_line in source_handle:
                    line = byte_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if line.lstrip().startswith("*"):
                        active = _keyword_token(line)
                        continue
                    if active != "*NODE" or not line.strip() or line.lstrip().startswith("$"):
                        continue
                    fields = _numbers(line, (8, 16, 16, 16))
                    if len(fields) < 4:
                        continue
                    nid = _integer(fields[0])
                    matching = [resource_id for resource_id, selected in node_ids.items() if nid in selected]
                    if not matching:
                        continue
                    coordinates = [_float(fields[index]) * 0.001 for index in range(1, 4)]
                    row = f"{nid},{coordinates[0]:.12g},{coordinates[1]:.12g},{coordinates[2]:.12g}\n"
                    for resource_id in matching:
                        node_files[resource_id].write(row)
                        node_counts[resource_id] += 1
                        for axis, value in enumerate(coordinates):
                            bounds[resource_id][0][axis] = min(bounds[resource_id][0][axis], value)
                            bounds[resource_id][1][axis] = max(bounds[resource_id][1][axis], value)
        finally:
            for handle in node_files.values():
                handle.close()

        written: dict[str, dict[str, str]] = {}
        for resource_id, spec in COMPONENT_RESOURCE_SPECS.items():
            if node_counts[resource_id] != len(node_ids[resource_id]):
                raise ValueError(f"{resource_id} has missing source node records")
            package = output_root / resource_id
            package.mkdir(parents=True, exist_ok=True)
            payload_temp = package / ".component.k.gz.tmp"
            with payload_temp.open("wb") as raw_output:
                with gzip.GzipFile(filename="", mode="wb", fileobj=raw_output, mtime=0) as zipped:
                    def emit(text: str) -> None:
                        zipped.write((text + "\n").encode("utf-8"))

                    for text in _metadata_lines(spec):
                        emit(text)
                    emit("*ELEMENT_SOLID (ten nodes format)")
                    emit("$# eid,pid")
                    emit("$# n1,n2,n3,n4,n5,n6,n7,n8,n9,n10")
                    with (temporary / f"{resource_id}.solid").open("r", encoding="utf-8") as handle:
                        for line in handle:
                            fields = line.rstrip("\n").split(",")
                            if len(fields) != 12:
                                raise ValueError(f"{resource_id} has an invalid ten-node solid row")
                            emit(",".join(fields[:2]))
                            emit(",".join(fields[2:]))
                    emit("*ELEMENT_BEAM")
                    emit("$# eid,pid,n1,n2,n3")
                    with (temporary / f"{resource_id}.beam").open("r", encoding="utf-8") as handle:
                        for line in handle:
                            emit(line.rstrip("\n"))
                    emit("*NODE")
                    emit("$# nid,x,y,z")
                    with (temporary / f"{resource_id}.node").open("r", encoding="utf-8") as handle:
                        for line in handle:
                            emit(line.rstrip("\n"))
                    emit("*END")
            payload_path = package / "component.k.gz"
            os.replace(payload_temp, payload_path)

            shared = sorted(
                nid for nid in node_ids[resource_id]
                if any(nid in other for other_id, other in node_ids.items() if other_id != resource_id)
            )
            audit = {
                "schema_version": "0.1.0",
                "resource_id": resource_id,
                "source_sha256": SOURCE_2K_SHA256,
                "source_part_ids": list(spec.part_ids),
                "source_element_ids_hash": element_hashes[resource_id].hexdigest(),
                "source_and_local_ids_are_identical_in_payload": True,
                "shared_source_node_ids": shared,
                "filtered_source_set_members": list(_SOURCE_SET_EXCLUSIONS.get(resource_id, ())),
                "excluded_part_ids": sorted(set(_PID_TO_RESOURCE) - set(spec.part_ids)),
                "warnings": [
                    "Original cross-component embedded part-set memberships were filtered to make this component dependency-closed.",
                    "Material cards are source references normalized to SI and require project review.",
                ],
            }
            manifest = {
                "schema_version": "0.1.0",
                "id": resource_id,
                "name": resource_id,
                "aliases": aliases_for(resource_id, MODEL_RESOURCE_ALIASES),
                "display_name": MODEL_DISPLAY_NAMES[resource_id],
                "component_kind": spec.component_kind,
                "version": "2026.08.04",
                "unit_system": "SI_m_s_kg_N_Pa",
                "validation_status": "source_reference",
                "requires_project_review": True,
                "solver_ready": False,
                "provenance": {
                    "source_name": LEGACY_SOURCE_FILENAME,
                    "source_display_name": REFERENCE_DISPLAY_NAME_EN,
                    "source_sha256": SOURCE_2K_SHA256,
                    "source_unit_system": "tonne_mm_s_N_MPa",
                },
                "payload": {
                    "path": "component.k.gz",
                    "format": "ls_dyna_keyword_gzip",
                    "sha256": _hash_file(payload_path),
                    "byte_size": payload_path.stat().st_size,
                },
                "source_part_ids": list(spec.part_ids),
                "source_section_ids": list(spec.section_ids),
                "source_material_ids": list(spec.material_ids),
                "source_set_ids": list(spec.set_ids),
                "coupling": {"ssid": spec.coupling[0], "msid": spec.coupling[1], "sstyp": spec.coupling[2], "mstyp": spec.coupling[3]},
                "node_count": node_counts[resource_id],
                "solid_count": spec.solid_count,
                "beam_count": spec.beam_count,
                "coordinate_frame": {"kind": "source_global_normalized_si", "bounding_box_m": bounds[resource_id]},
                "capabilities": ["solid", "beam", "beam_orientation_node", "embedded_coupling", "rigid_transform", "id_remap", "material_binding"],
                "material_resource_ids": [
                    {5: MATERIAL_RESOURCE_ALIASES["2k_mid5_concrete_kc"], 8: MATERIAL_RESOURCE_ALIASES["2k_mid8_rebar_d8_d18"], 12: MATERIAL_RESOURCE_ALIASES["2k_mid12_rebar_d12"], 14: MATERIAL_RESOURCE_ALIASES["2k_mid14_rebar_d20"]}[mid]
                    for mid in spec.material_ids
                ],
                "interfaces": {"connection_policy": "explicit_only", "shared_source_node_count": len(shared)},
                "audit": {"path": "audit.json"},
            }
            _atomic_json(package / "audit.json", audit)
            _atomic_json(package / "manifest.json", manifest)
            written[resource_id] = {
                "manifest": str(package / "manifest.json"),
                "payload": str(payload_path),
                "audit": str(package / "audit.json"),
            }
        return written
