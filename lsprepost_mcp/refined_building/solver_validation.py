"""Generate bounded LS-DYNA decks for refined-building initialization checks.

These decks intentionally use documented elastic proxy materials.  They prove
keyword, topology and short-duration numerical initialization only; they do
not promote Phase 18D assets to engineering-validated solver models.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .artifacts import BuildingArtifact, PartBinding


_SCHEMA_VERSION = "refined_building.initial_solver_validation@1"
_MODEL_TYPE = "refined_building_initial_validation"
_UNIT_SYSTEM = "SI_m_s_kg_N_Pa"
_BASE_NODE_SET_ID = 800_000_001
_GRAVITY_CURVE_ID = 800_000_002


@dataclass(frozen=True, slots=True)
class _NodeMap:
    offset: int
    count: int
    contiguous: bool
    sparse: Mapping[int, int] | None = None

    def global_id(self, local_id: int) -> int:
        if self.contiguous:
            if not 1 <= local_id <= self.count:
                raise ValueError(f"node id {local_id} is outside the contiguous artifact range")
            return self.offset + local_id
        assert self.sparse is not None
        try:
            return self.sparse[local_id]
        except KeyError as exc:
            raise ValueError(f"node id {local_id} is not declared by its artifact") from exc


@dataclass(frozen=True, slots=True)
class _RoleRecord:
    part_role: str
    material_role: str
    section_role: str
    family: str
    part_id: int
    section_id: int
    material_class: str
    material_id: int


_PROXY_MATERIALS: Mapping[str, tuple[str, float, float, float]] = {
    "concrete": ("diagnostic concrete elastic proxy", 2400.0, 30.0e9, 0.20),
    "reinforcing_steel": ("diagnostic reinforcing steel elastic proxy", 7850.0, 210.0e9, 0.30),
    "steel": ("diagnostic structural steel elastic proxy", 7850.0, 210.0e9, 0.30),
    "glass": ("diagnostic glass elastic proxy", 2500.0, 70.0e9, 0.22),
    "aluminum": ("diagnostic aluminum elastic proxy", 2700.0, 69.0e9, 0.33),
    "rubber": ("diagnostic rubber elastic proxy", 1100.0, 10.0e6, 0.49),
    "generic_nonstructural": ("diagnostic nonstructural elastic proxy", 1200.0, 3.0e9, 0.30),
}


def write_initial_solver_validation_model(
    artifacts: Sequence[BuildingArtifact],
    output_dir: Path,
    *,
    source_identity: Mapping[str, object],
    termination_time_s: float = 0.001,
    gravity_m_per_s2: float = -9.81,
    output_interval_s: float | None = None,
) -> dict[str, object]:
    """Write one dependency-closed, monolithic ``model.k`` and its audit data."""

    rows = tuple(artifacts)
    if not rows or any(not isinstance(row, BuildingArtifact) for row in rows):
        raise ValueError("artifacts must contain at least one BuildingArtifact")
    termination = _finite_positive(termination_time_s, "termination_time_s")
    gravity = _finite_number(gravity_m_per_s2, "gravity_m_per_s2")
    if gravity >= 0.0:
        raise ValueError("gravity_m_per_s2 must be negative for the validation load case")
    interval = (
        min(termination / 10.0, 0.0001)
        if output_interval_s is None
        else _finite_positive(output_interval_s, "output_interval_s")
    )
    if interval > termination:
        raise ValueError("output_interval_s must not exceed termination_time_s")
    if not isinstance(source_identity, Mapping) or not source_identity:
        raise ValueError("source_identity must be a non-empty mapping")
    source = _json_plain(source_identity)
    assert isinstance(source, dict)
    json.dumps(source, ensure_ascii=False, sort_keys=True, allow_nan=False)

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("output_dir must be empty")

    node_maps = _node_maps(rows)
    role_records = _role_records(rows)
    global_min_z = min(node.z for artifact in rows for node in artifact.mesh.nodes)
    tolerance = max(1.0e-10, abs(global_min_z) * 1.0e-12)
    fixed_base_nodes = tuple(
        node_map.global_id(node.node_id)
        for artifact, node_map in zip(rows, node_maps)
        for node in artifact.mesh.nodes
        if abs(node.z - global_min_z) <= tolerance
    )
    if not fixed_base_nodes:
        raise ValueError("validation model has no nodes on its global minimum-z base")

    counts = {
        "artifacts": len(rows),
        "nodes": sum(len(row.mesh.nodes) for row in rows),
        "solid_elements": sum(len(row.mesh.solids) for row in rows),
        "shell_elements": sum(len(row.mesh.shells) for row in rows),
        "beam_elements": sum(len(row.mesh.beams) for row in rows),
        "parts": len(role_records),
        "fixed_base_nodes": len(fixed_base_nodes),
    }
    counts["total_elements"] = (
        counts["solid_elements"] + counts["shell_elements"] + counts["beam_elements"]
    )

    model_path = output / "model.k"
    temporary_model = output / ".model.k.tmp"
    try:
        with temporary_model.open("w", encoding="utf-8", newline="\n") as handle:
            _write_keyword(
                handle,
                rows,
                node_maps,
                role_records,
                fixed_base_nodes,
                termination,
                gravity,
                interval,
            )
        os.replace(temporary_model, model_path)
    finally:
        if temporary_model.exists():
            temporary_model.unlink()

    model_json = {
        "schema_version": _SCHEMA_VERSION,
        "spec": {
            "model_type": _MODEL_TYPE,
            "unit_system": _UNIT_SYSTEM,
            "termination_time_s": termination,
            "gravity_m_per_s2": gravity,
            "output_interval_s": interval,
        },
        "source_identity": source,
        "engineering_validated": False,
        "solver_ready": False,
        "requires_project_review": True,
    }
    _write_json_atomic(output / "model.json", model_json)

    manifest: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "unit_system": _UNIT_SYSTEM,
        "purpose": "bounded 1 ms keyword/topology/numerical initialization validation",
        "source_identity": source,
        "termination_time_s": termination,
        "gravity_m_per_s2": gravity,
        "output_interval_s": interval,
        "counts": counts,
        "part_assignments": [
            {
                "part_role": row.part_role,
                "material_role": row.material_role,
                "section_role": row.section_role,
                "element_family": row.family,
                "part_id": row.part_id,
                "section_id": row.section_id,
                "material_class": row.material_class,
                "material_id": row.material_id,
            }
            for row in role_records
        ],
        "material_policy": {
            "kind": "diagnostic_elastic_proxies",
            "not_for_engineering_response": True,
            "classes": {
                key: {
                    "title": values[0],
                    "density_kg_m3": values[1],
                    "youngs_modulus_pa": values[2],
                    "poisson_ratio": values[3],
                }
                for key, values in sorted(_PROXY_MATERIALS.items())
                if any(row.material_class == key for row in role_records)
            },
        },
        "base_constraint": {
            "node_set_id": _BASE_NODE_SET_ID,
            "selection": "all nodes at global minimum z",
            "all_six_dofs_fixed": True,
        },
        "files": {
            name: _file_record(output / name) for name in ("model.k", "model.json")
        },
        "engineering_validated": False,
        "solver_ready": False,
        "requires_project_review": True,
    }
    _write_json_atomic(output / "validation_manifest.json", manifest)
    return manifest


def inspect_initial_solver_validation_model(model_dir: Path) -> dict[str, object]:
    """Verify persisted identity and the closed keyword-card envelope."""

    root = Path(model_dir)
    findings: list[str] = []
    manifest_path = root / "validation_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "findings": ["validation_manifest.json is unreadable"]}
    if not isinstance(manifest, dict) or manifest.get("schema_version") != _SCHEMA_VERSION:
        return {"ok": False, "findings": ["validation manifest schema is invalid"]}
    files = manifest.get("files")
    if not isinstance(files, dict):
        return {"ok": False, "findings": ["validation manifest files are invalid"]}
    for name in ("model.k", "model.json"):
        row = files.get(name)
        path = root / name
        if not isinstance(row, dict) or not path.is_file():
            findings.append(f"{name} is missing")
            continue
        if row.get("size_bytes") != path.stat().st_size:
            findings.append(f"{name} size mismatch")
        if row.get("sha256") != _sha256(path):
            findings.append(f"{name} sha256 mismatch")
    if findings:
        return {"ok": False, "findings": findings}

    try:
        model_json = json.loads((root / "model.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        findings.append("model.json is unreadable")
    else:
        spec = model_json.get("spec") if isinstance(model_json, dict) else None
        if not isinstance(spec, dict) or spec.get("model_type") != _MODEL_TYPE:
            findings.append("model.json model_type mismatch")
        elif spec.get("termination_time_s") != manifest.get("termination_time_s"):
            findings.append("model.json termination_time_s mismatch")

    cards: set[str] = set()
    termination_value: float | None = None
    expect_termination = False
    with (root / "model.k").open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            stripped = raw.strip()
            if not stripped or stripped.startswith("$"):
                continue
            if stripped.startswith("*"):
                token = stripped.split(",", 1)[0].upper()
                cards.add(token)
                expect_termination = token == "*CONTROL_TERMINATION"
                continue
            if expect_termination:
                try:
                    termination_value = float(stripped.split(",", 1)[0])
                except ValueError:
                    pass
                expect_termination = False
    required = {
        "*KEYWORD",
        "*NODE",
        "*PART_TITLE",
        "*MAT_ELASTIC_TITLE",
        "*SET_NODE_LIST_TITLE",
        "*BOUNDARY_SPC_SET",
        "*DEFINE_CURVE_TITLE",
        "*LOAD_BODY_Z",
        "*CONTROL_TERMINATION",
        "*CONTROL_ENERGY",
        "*CONTROL_TIMESTEP",
        "*DATABASE_BINARY_D3PLOT",
        "*END",
    }
    for card in sorted(required - cards):
        findings.append(f"required card is missing: {card}")
    if termination_value != manifest.get("termination_time_s"):
        findings.append("model.k termination time mismatch")
    counts = manifest.get("counts")
    if not isinstance(counts, dict) or any(
        isinstance(counts.get(key), bool)
        or not isinstance(counts.get(key), int)
        or counts[key] <= 0
        for key in ("nodes", "total_elements", "parts", "fixed_base_nodes")
    ):
        findings.append("manifest counts are invalid")
    return {"ok": not findings, "findings": findings}


def _node_maps(artifacts: tuple[BuildingArtifact, ...]) -> tuple[_NodeMap, ...]:
    result: list[_NodeMap] = []
    offset = 0
    for artifact in artifacts:
        local_ids = tuple(node.node_id for node in artifact.mesh.nodes)
        contiguous = len(local_ids) > 0 and set(local_ids) == set(range(1, len(local_ids) + 1))
        sparse = None if contiguous else {local: offset + index for index, local in enumerate(local_ids, 1)}
        result.append(_NodeMap(offset, len(local_ids), contiguous, sparse))
        offset += len(local_ids)
    return tuple(result)


def _role_records(artifacts: tuple[BuildingArtifact, ...]) -> tuple[_RoleRecord, ...]:
    bindings: dict[str, PartBinding] = {}
    families: dict[str, str] = {}
    for artifact in artifacts:
        for binding in artifact.mesh.part_bindings:
            previous = bindings.get(binding.part_role)
            if previous is not None and previous != binding:
                raise ValueError(f"conflicting part binding for role {binding.part_role!r}")
            bindings[binding.part_role] = binding
        for family, elements in (
            ("solid", artifact.mesh.solids),
            ("shell", artifact.mesh.shells),
            ("beam", artifact.mesh.beams),
        ):
            for element in elements:
                previous_family = families.get(element.part_role)
                if previous_family is not None and previous_family != family:
                    raise ValueError(f"part role {element.part_role!r} spans element families")
                families[element.part_role] = family
    missing = sorted(set(families) - set(bindings))
    if missing:
        raise ValueError(f"missing part binding for role {missing[0]!r}")
    material_classes = sorted(
        {_material_class(role, bindings[role].material_role) for role in families}
    )
    material_ids = {key: 2001 + index for index, key in enumerate(material_classes)}
    records: list[_RoleRecord] = []
    for index, role in enumerate(sorted(families), start=1):
        binding = bindings[role]
        material_class = _material_class(role, binding.material_role)
        records.append(
            _RoleRecord(
                part_role=role,
                material_role=binding.material_role,
                section_role=binding.section_role,
                family=families[role],
                part_id=index,
                section_id=1000 + index,
                material_class=material_class,
                material_id=material_ids[material_class],
            )
        )
    return tuple(records)


def _material_class(part_role: str, material_role: str) -> str:
    text = f"{part_role} {material_role}".lower()
    if "rebar" in text or "reinforc" in text:
        return "reinforcing_steel"
    if "glass" in text or "glazing" in text:
        return "glass"
    if "aluminum" in text:
        return "aluminum"
    if "rubber" in text or "handrail" in text:
        return "rubber"
    if "steel" in text or "metal" in text or "escalator_equipment" in text:
        return "steel"
    if "concrete" in text or part_role.startswith(("rc_", "hybrid_", "fixed_stair")):
        return "concrete"
    return "generic_nonstructural"


def _write_keyword(
    handle: object,
    artifacts: tuple[BuildingArtifact, ...],
    node_maps: tuple[_NodeMap, ...],
    roles: tuple[_RoleRecord, ...],
    fixed_base_nodes: tuple[int, ...],
    termination: float,
    gravity: float,
    interval: float,
) -> None:
    role_by_name = {row.part_role: row for row in roles}

    def emit(*lines: object) -> None:
        for line in lines:
            handle.write(str(line) + "\n")  # type: ignore[attr-defined]

    emit(
        "*KEYWORD",
        "$ Phase 18 refined-building 1 ms initialization-validation deck.",
        "$ Elastic proxy materials are diagnostic only; engineering validation remains false.",
        "*TITLE",
        "Phase 18 refined building initial solver validation",
        "*NODE",
    )
    for artifact, node_map in zip(artifacts, node_maps):
        for node in artifact.mesh.nodes:
            emit(
                f"{node_map.global_id(node.node_id)},{_number(node.x)},"
                f"{_number(node.y)},{_number(node.z)}"
            )

    next_element_id = 1
    for family, keyword in (
        ("solid", "*ELEMENT_SOLID"),
        ("shell", "*ELEMENT_SHELL"),
        ("beam", "*ELEMENT_BEAM"),
    ):
        family_count = sum(len(getattr(artifact.mesh, f"{family}s")) for artifact in artifacts)
        if not family_count:
            continue
        emit(keyword)
        for artifact, node_map in zip(artifacts, node_maps):
            for element in getattr(artifact.mesh, f"{family}s"):
                row = role_by_name[element.part_role]
                node_ids = [node_map.global_id(node_id) for node_id in element.node_ids]
                fields = [next_element_id, row.part_id, *node_ids]
                if family == "beam":
                    fields.extend((0, 0, 0, 0))
                emit(",".join(str(value) for value in fields))
                next_element_id += 1

    for row in roles:
        emit(
            "*PART_TITLE",
            f"{row.part_role} [initial validation proxy]",
            "$#     pid     secid       mid     eosid      hgid      grav    adpopt      tmid",
            f"{row.part_id},{row.section_id},{row.material_id},0,0,0,0,0",
        )
    for row in roles:
        if row.family == "solid":
            emit(
                "*SECTION_SOLID_TITLE",
                f"{row.section_role} [initial validation]",
                "$#   secid    elform       aet",
                f"{row.section_id},1,0",
            )
        elif row.family == "shell":
            thickness = _shell_thickness(row.part_role)
            emit(
                "*SECTION_SHELL_TITLE",
                f"{row.section_role} [initial validation]",
                "$#   secid    elform      shrf       nip     propt   qr/irid     icomp     setyp",
                f"{row.section_id},16,1.0,2,1.0,0,0,1",
                "$#      t1        t2        t3        t4      nloc",
                f"{_number(thickness)},{_number(thickness)},{_number(thickness)},{_number(thickness)},0",
            )
        else:
            diameter = _beam_diameter(row.part_role, row.material_class)
            emit(
                "*SECTION_BEAM_TITLE",
                f"{row.section_role} [initial validation]",
                "$#   secid    elform      shrf        qr       cst     scoor       nsm",
                f"{row.section_id},1,1.0,2,1,0.0,0.0",
                "$#     ts1       ts2       tt1       tt2     nsloc     ntloc",
                f"{_number(diameter)},{_number(diameter)},0.0,0.0,0.0,0.0",
            )

    material_ids = {row.material_class: row.material_id for row in roles}
    for material_class, material_id in sorted(material_ids.items(), key=lambda item: item[1]):
        title, density, modulus, poisson = _PROXY_MATERIALS[material_class]
        emit(
            "*MAT_ELASTIC_TITLE",
            title,
            "$#     mid       rho         e        pr        da        db  not used",
            f"{material_id},{_number(density)},{_number(modulus)},{_number(poisson)},0,0,0",
        )

    emit("*SET_NODE_LIST_TITLE", "Fixed global minimum-z base", str(_BASE_NODE_SET_ID))
    for index in range(0, len(fixed_base_nodes), 8):
        emit(",".join(str(value) for value in fixed_base_nodes[index : index + 8]))
    emit(
        "*BOUNDARY_SPC_SET",
        "$#  nsid       cid      dofx      dofy      dofz     dofrx     dofry     dofrz",
        f"{_BASE_NODE_SET_ID},0,1,1,1,1,1,1",
        "*DEFINE_CURVE_TITLE",
        "Constant gravity for 1 ms initialization validation",
        "$#    lcid      sidr       sfa       sfo      offa      offo    dattyp     lcint",
        f"{_GRAVITY_CURVE_ID},0,1.0,1.0,0.0,0.0,0,0",
        "$#                a1                  o1",
        f"0.0,{_number(gravity)}",
        f"{_number(termination)},{_number(gravity)}",
        "*LOAD_BODY_Z",
        "$#  lcid        sf",
        f"{_GRAVITY_CURVE_ID},1.0",
        "*CONTROL_TERMINATION",
        _number(termination),
        "*CONTROL_ENERGY",
        "$#    hgen      rwen    slnten     rylen",
        "2,2,2,2",
        "*CONTROL_TIMESTEP",
        "0,0.67",
        "*DATABASE_BINARY_D3PLOT",
        _number(interval),
        "*DATABASE_GLSTAT",
        _number(interval),
        "*DATABASE_MATSUM",
        _number(interval),
        "*DATABASE_SPCFORC",
        _number(interval),
        "*END",
    )


def _shell_thickness(part_role: str) -> float:
    text = part_role.lower()
    if "glazing" in text or "glass" in text or "balustrade" in text:
        return 0.01
    if "roof" in text or "facade" in text or "door" in text:
        return 0.02
    return 0.02


def _beam_diameter(part_role: str, material_class: str) -> float:
    if material_class == "reinforcing_steel":
        return 0.02
    if "handrail" in part_role.lower():
        return 0.04
    return 0.10


def _number(value: float) -> str:
    result = format(float(value), ".7g")
    if len(result) > 10:
        raise ValueError(f"numeric value cannot be represented in an R12 10-character field: {value!r}")
    return result


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number")
    return result


def _finite_positive(value: object, field: str) -> float:
    result = _finite_number(value, field)
    if result <= 0.0:
        raise ValueError(f"{field} must be positive")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_record(path: Path) -> dict[str, object]:
    return {"sha256": _sha256(path), "size_bytes": path.stat().st_size}


def _write_json_atomic(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _json_plain(value: object) -> object:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("source_identity mapping keys must be strings")
            result[key] = _json_plain(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_plain(item) for item in value]
    return value


__all__ = [
    "inspect_initial_solver_validation_model",
    "write_initial_solver_validation_model",
]
