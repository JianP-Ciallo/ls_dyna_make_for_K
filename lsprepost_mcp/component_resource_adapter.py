"""Transform and collision-safe remapping for component model resources."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import Callable

from .config import JSONDict
from .model_library import get_model_resource, validate_model_resource


@dataclass(frozen=True)
class ResourceIdNamespace:
    node_offset: int = 0
    element_offset: int = 0
    part_offset: int = 0
    section_offset: int = 0
    material_offset: int = 0
    set_offset: int = 0
    curve_offset: int = 0

    @classmethod
    def from_offsets(
        cls,
        *,
        node: int = 0,
        element: int = 0,
        part: int = 0,
        section: int = 0,
        material: int = 0,
        set_id: int = 0,
        curve: int = 0,
    ) -> "ResourceIdNamespace":
        values = (node, element, part, section, material, set_id, curve)
        if any(not isinstance(value, int) or value < 0 for value in values):
            raise ValueError("resource ID offsets must be non-negative integers")
        return cls(node, element, part, section, material, set_id, curve)


@dataclass(frozen=True)
class ComponentFragment:
    keyword_text: str
    metadata: JSONDict
    fingerprint: str


def _triplet(value: object, name: str) -> tuple[float, float, float]:
    if value is None:
        return (0.0, 0.0, 0.0)
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"transform.{name} must contain three numbers")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"transform.{name} values must be finite")
    return result  # type: ignore[return-value]


def _transformer(transform: JSONDict) -> Callable[[float, float, float], tuple[float, float, float]]:
    unknown = sorted(set(transform) - {"translation_m", "rotation_deg"})
    if unknown:
        raise ValueError(f"unsupported transform field(s): {', '.join(unknown)}")
    tx, ty, tz = _triplet(transform.get("translation_m"), "translation_m")
    rx, ry, rz = (math.radians(value) for value in _triplet(transform.get("rotation_deg"), "rotation_deg"))
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)

    def apply(x: float, y: float, z: float) -> tuple[float, float, float]:
        y, z = y * cx - z * sx, y * sx + z * cx
        x, z = x * cy + z * sy, -x * sy + z * cy
        x, y = x * cz - y * sz, x * sz + y * cz
        return (x + tx, y + ty, z + tz)

    return apply


def _integer(value: str) -> int:
    return int(float(value.strip()))


def _shift(value: str, offset: int) -> str:
    identity = _integer(value)
    return str(identity if identity == 0 else identity + offset)


def _numeric_fields(line: str) -> list[str] | None:
    if "," not in line:
        return None
    fields = [field.strip() for field in line.strip().split(",")]
    try:
        float(fields[0])
    except (ValueError, IndexError):
        return None
    return fields


def instantiate_model_resource(
    resource_id: str,
    transform: JSONDict | None,
    id_namespace: ResourceIdNamespace,
    material_binding: str = "source_reference",
) -> ComponentFragment:
    if material_binding != "source_reference":
        raise ValueError("material_binding must be source_reference for Phase 18A-1 resources")
    if not isinstance(id_namespace, ResourceIdNamespace):
        raise ValueError("id_namespace must be a ResourceIdNamespace")
    transform_map = dict(transform or {})
    apply_transform = _transformer(transform_map)
    validation = validate_model_resource(resource_id)
    resource = get_model_resource(resource_id)
    payload = resource.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("path"), str):
        raise ValueError(f"model resource '{resource_id}' has invalid payload metadata")
    payload_path = Path(str(resource["_resource_dir"])) / payload["path"]

    active = ""
    data_index = 0
    pending_ten_node_solid = False
    ten_node_solid = False
    output: list[str] = []
    ids: dict[str, list[int]] = {name: [] for name in ("node", "element", "part", "section", "material", "set", "curve")}
    with gzip.open(payload_path, "rt", encoding="utf-8", errors="strict") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\r\n")
            stripped = line.strip()
            if stripped.startswith("*"):
                if active == "*ELEMENT_SOLID" and pending_ten_node_solid:
                    raise ValueError(f"model resource '{resource_id}' has an incomplete ten-node solid record")
                active = stripped.split()[0].upper()
                data_index = 0
                pending_ten_node_solid = False
                ten_node_solid = stripped.upper() == "*ELEMENT_SOLID (TEN NODES FORMAT)"
                output.append(line)
                continue
            if not stripped or stripped.startswith("$"):
                output.append(line)
                continue
            fields = _numeric_fields(line)
            if fields is None:
                output.append(line)
                continue

            if active == "*NODE":
                source_id = _integer(fields[0])
                target_id = source_id + id_namespace.node_offset
                x, y, z = apply_transform(float(fields[1]), float(fields[2]), float(fields[3]))
                fields = [str(target_id), f"{x:.12g}", f"{y:.12g}", f"{z:.12g}"]
                ids["node"].append(target_id)
            elif active == "*ELEMENT_SOLID" and ten_node_solid:
                if not pending_ten_node_solid:
                    if len(fields) != 2:
                        raise ValueError(f"model resource '{resource_id}' has an invalid ten-node solid identity row")
                    target_eid = _integer(fields[0]) + id_namespace.element_offset
                    target_pid = _integer(fields[1]) + id_namespace.part_offset
                    fields[0] = str(target_eid)
                    fields[1] = str(target_pid)
                    ids["element"].append(target_eid)
                    pending_ten_node_solid = True
                else:
                    if len(fields) != 10:
                        raise ValueError(f"model resource '{resource_id}' has an invalid ten-node connectivity row")
                    for index in range(len(fields)):
                        fields[index] = _shift(fields[index], id_namespace.node_offset)
                    pending_ten_node_solid = False
            elif active in {"*ELEMENT_SOLID", "*ELEMENT_BEAM"}:
                target_eid = _integer(fields[0]) + id_namespace.element_offset
                target_pid = _integer(fields[1]) + id_namespace.part_offset
                fields[0] = str(target_eid)
                fields[1] = str(target_pid)
                for index in range(2, len(fields)):
                    fields[index] = _shift(fields[index], id_namespace.node_offset)
                ids["element"].append(target_eid)
            elif active == "*PART" and data_index == 0:
                target_pid = _integer(fields[0]) + id_namespace.part_offset
                fields[0] = str(target_pid)
                fields[1] = _shift(fields[1], id_namespace.section_offset)
                fields[2] = _shift(fields[2], id_namespace.material_offset)
                ids["part"].append(target_pid)
            elif active.startswith("*SECTION_") and data_index == 0:
                target_id = _integer(fields[0]) + id_namespace.section_offset
                fields[0] = str(target_id)
                ids["section"].append(target_id)
            elif active.startswith("*MAT_") and active != "*MAT_ADD_EROSION" and data_index == 0:
                target_id = _integer(fields[0]) + id_namespace.material_offset
                fields[0] = str(target_id)
                ids["material"].append(target_id)
            elif active == "*MAT_CONCRETE_DAMAGE_REL3_TITLE" and data_index == 2:
                fields[5] = _shift(fields[5], id_namespace.curve_offset)
            elif active == "*MAT_ADD_EROSION" and data_index == 0:
                fields[0] = _shift(fields[0], id_namespace.material_offset)
            elif active == "*DEFINE_CURVE" and data_index == 0:
                target_id = _integer(fields[0]) + id_namespace.curve_offset
                fields[0] = str(target_id)
                ids["curve"].append(target_id)
            elif active == "*SET_PART_LIST_TITLE":
                if data_index == 0:
                    target_id = _integer(fields[0]) + id_namespace.set_offset
                    fields[0] = str(target_id)
                    ids["set"].append(target_id)
                else:
                    for index in range(min(8, len(fields))):
                        fields[index] = _shift(fields[index], id_namespace.part_offset)
            elif active == "*CONSTRAINED_LAGRANGE_IN_SOLID_TITLE" and data_index == 0:
                sstyp = _integer(fields[2])
                mstyp = _integer(fields[3])
                fields[0] = _shift(fields[0], id_namespace.set_offset if sstyp == 0 else id_namespace.part_offset)
                fields[1] = _shift(fields[1], id_namespace.set_offset if mstyp == 0 else id_namespace.part_offset)

            output.append(",".join(fields))
            data_index += 1

    if pending_ten_node_solid:
        raise ValueError(f"model resource '{resource_id}' has an incomplete ten-node solid record")

    keyword_text = "\n".join(output) + "\n"

    def id_range(name: str) -> list[int] | None:
        values = ids[name]
        return [min(values), max(values)] if values else None

    metadata: JSONDict = {
        "resource_id": resource_id,
        "resource_version": resource.get("version"),
        "payload_sha256": validation["payload_sha256"],
        "unit_system": resource.get("unit_system"),
        "node_count": validation["node_count"],
        "solid_count": validation["solid_count"],
        "beam_count": validation["beam_count"],
        "id_namespace": asdict(id_namespace),
        "id_ranges": {name: id_range(name) for name in ids},
        "transform": {
            "translation_m": list(_triplet(transform_map.get("translation_m"), "translation_m")),
            "rotation_deg": list(_triplet(transform_map.get("rotation_deg"), "rotation_deg")),
        },
        "material_binding": material_binding,
        "validation_status": resource.get("validation_status"),
        "requires_project_review": bool(resource.get("requires_project_review", True)),
    }
    fingerprint = hashlib.sha256(
        (keyword_text + json.dumps(metadata, sort_keys=True, separators=(",", ":"))).encode("utf-8")
    ).hexdigest()
    metadata["fingerprint"] = fingerprint
    return ComponentFragment(keyword_text, metadata, fingerprint)


_ID_KINDS = ("node", "element", "part", "section", "material", "set", "curve")


def _scan_id_ranges(lines: Iterable[str]) -> dict[str, list[int] | None]:
    ranges: dict[str, list[int] | None] = {name: None for name in _ID_KINDS}
    active = ""
    data_index = 0
    pending_ten_node_solid = False
    ten_node_solid = False

    def record(kind: str, value: str) -> None:
        try:
            identity = _integer(value)
        except (TypeError, ValueError):
            return
        if identity <= 0:
            return
        current = ranges[kind]
        if current is None:
            ranges[kind] = [identity, identity]
        else:
            current[0] = min(current[0], identity)
            current[1] = max(current[1], identity)

    for raw_line in lines:
        stripped = str(raw_line).strip()
        if stripped.startswith("*"):
            active = stripped.split()[0].upper()
            data_index = 0
            pending_ten_node_solid = False
            ten_node_solid = stripped.upper() == "*ELEMENT_SOLID (TEN NODES FORMAT)"
            continue
        if not stripped or stripped.startswith("$"):
            continue
        fields = _numeric_fields(stripped)
        if fields is None:
            continue
        if active == "*NODE":
            record("node", fields[0])
        elif active == "*ELEMENT_SOLID" and ten_node_solid:
            if not pending_ten_node_solid:
                record("element", fields[0])
                pending_ten_node_solid = True
            else:
                pending_ten_node_solid = False
        elif active in {"*ELEMENT_SOLID", "*ELEMENT_BEAM", "*ELEMENT_SHELL"}:
            record("element", fields[0])
        elif active == "*PART" and data_index == 0:
            record("part", fields[0])
        elif active.startswith("*SECTION_") and data_index == 0:
            record("section", fields[0])
        elif active.startswith("*MAT_") and active != "*MAT_ADD_EROSION" and data_index == 0:
            record("material", fields[0])
        elif active == "*DEFINE_CURVE" and data_index == 0:
            record("curve", fields[0])
        elif active.startswith("*SET_") and data_index == 0:
            record("set", fields[0])
        data_index += 1
    return ranges


def _resource_id_ranges(resource_id: str) -> dict[str, list[int] | None]:
    resource = get_model_resource(resource_id)
    payload = resource.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("path"), str):
        raise ValueError(f"model resource '{resource_id}' has invalid payload metadata")
    payload_path = Path(str(resource["_resource_dir"])) / payload["path"]
    with gzip.open(payload_path, "rt", encoding="utf-8", errors="strict") as handle:
        return _scan_id_ranges(handle)


def _namespace_after(
    occupied: dict[str, list[int] | None],
    source: dict[str, list[int] | None],
) -> ResourceIdNamespace:
    offsets: dict[str, int] = {}
    for kind in _ID_KINDS:
        used = occupied[kind]
        incoming = source[kind]
        offsets[kind] = 0 if used is None or incoming is None else max(0, used[1] + 1 - incoming[0])
    return ResourceIdNamespace.from_offsets(
        node=offsets["node"],
        element=offsets["element"],
        part=offsets["part"],
        section=offsets["section"],
        material=offsets["material"],
        set_id=offsets["set"],
        curve=offsets["curve"],
    )


def _occupy(
    occupied: dict[str, list[int] | None],
    target_ranges: dict[str, list[int] | None],
) -> None:
    for kind, target in target_ranges.items():
        if target is None:
            continue
        current = occupied[kind]
        if current is None:
            occupied[kind] = list(target)
        else:
            current[0] = min(current[0], target[0])
            current[1] = max(current[1], target[1])


def _fragment_body(keyword_text: str) -> list[str]:
    return [
        line
        for line in keyword_text.splitlines()
        if line.strip().upper() not in {"*KEYWORD", "*END"}
    ]


def attach_model_resources(
    keyword_text: str,
    instances: list[JSONDict],
) -> tuple[str, list[JSONDict]]:
    """Append component instances before one final *END using collision-free IDs."""
    if not instances:
        return keyword_text, []

    occupied = _scan_id_ranges(keyword_text.splitlines())
    host_lines = [line for line in keyword_text.splitlines() if line.strip().upper() != "*END"]
    metadata_rows: list[JSONDict] = []
    for instance in instances:
        instance_id = str(instance["id"])
        resource_id = str(instance["model_resource_id"])
        source_ranges = _resource_id_ranges(resource_id)
        namespace = _namespace_after(occupied, source_ranges)
        fragment = instantiate_model_resource(
            resource_id,
            transform=instance.get("transform") if isinstance(instance.get("transform"), dict) else {},
            id_namespace=namespace,
            material_binding=str(instance.get("material_binding", "source_reference")),
        )
        host_lines.append(f"$ MODEL_RESOURCE_INSTANCE {instance_id} {resource_id}")
        host_lines.extend(_fragment_body(fragment.keyword_text))
        row = dict(fragment.metadata)
        row["instance_id"] = instance_id
        metadata_rows.append(row)
        target_ranges = fragment.metadata.get("id_ranges")
        if isinstance(target_ranges, dict):
            _occupy(occupied, target_ranges)  # type: ignore[arg-type]
    host_lines.append("*END")
    return "\n".join(host_lines) + "\n", metadata_rows
