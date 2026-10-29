from __future__ import annotations

import gzip
import hashlib
import math
import os
import re
from pathlib import Path

from .config import JSONDict, MODEL_LIBRARY_DIR
from .io import read_json
from .phase18_reference_naming import MODEL_RESOURCE_ALIASES
from .resource_aliases import build_alias_index, normalize_resource_identity, resolve_resource_id


def _manifest_files(root: Path = MODEL_LIBRARY_DIR) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob("manifest.json"), key=lambda item: str(item).lower())


def load_model_resources(root: Path = MODEL_LIBRARY_DIR) -> dict[str, JSONDict]:
    resources: dict[str, JSONDict] = {}
    for path in _manifest_files(root):
        data = read_json(path)
        raw_id = str(data.get("id") or path.parent.name)
        normalized = normalize_resource_identity(data, raw_id, MODEL_RESOURCE_ALIASES, "model")
        resource_id = str(normalized["id"])
        if resource_id in resources:
            previous = resources[resource_id]["_manifest_path"]
            raise ValueError(
                f"duplicate model resource id '{resource_id}' in '{previous}' and '{path}'"
            )
        normalized.setdefault("name", resource_id)
        relative = path.relative_to(root)
        normalized.setdefault("library_section", relative.parts[0] if len(relative.parts) > 1 else "legacy_flat")
        normalized.setdefault("source_type", "packaged_k")
        normalized["_manifest_path"] = str(path)
        normalized["_resource_dir"] = str(path.parent)
        resources[resource_id] = normalized
    build_alias_index(resources, "model")
    return resources


def list_model_resources() -> list[JSONDict]:
    rows: list[JSONDict] = []
    for resource in load_model_resources().values():
        rows.append(
            {
                "id": resource["id"],
                "name": resource.get("name", resource["id"]),
                "display_name": resource.get("display_name", resource["id"]),
                "unit_system": resource.get("unit_system", "unknown"),
                "validation_status": resource.get("validation_status", "source_reference"),
                "requires_project_review": bool(resource.get("requires_project_review", True)),
                "solver_ready": bool(resource.get("solver_ready", False)),
                "version": resource.get("version", "unknown"),
                "library_section": resource.get("library_section", "legacy_flat"),
                "source_type": resource.get("source_type", "packaged_k"),
            }
        )
    return rows


def get_model_resource(resource_id: str) -> JSONDict:
    key = str(resource_id).strip()
    if not key:
        raise ValueError("resource_id is required")
    resources = load_model_resources()
    _, resource = resolve_resource_id(key, resources, "model")
    return dict(resource)


def _payload_path(resource: JSONDict) -> Path:
    payload = resource.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("path"), str):
        raise ValueError(f"model resource '{resource.get('id')}' has no payload path")
    resource_dir = Path(str(resource.get("_resource_dir", "")))
    path = (resource_dir / payload["path"]).resolve()
    try:
        path.relative_to(resource_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"model resource '{resource.get('id')}' payload escaped its resource directory") from exc
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _numeric_fields(
    line: str,
    widths: tuple[int, ...],
    *,
    expected_count: int | None = None,
    minimum_count: int | None = None,
) -> list[str]:
    raw = line.rstrip("\r\n")
    stripped = line.strip()
    if "," in stripped:
        return [field.strip() for field in stripped.split(",")]

    whitespace_fields = stripped.split()
    total_width = sum(widths)
    if len(raw) < total_width:
        return whitespace_fields

    required_count = expected_count if expected_count is not None else minimum_count
    if required_count is None:
        raise ValueError("numeric field parser requires an expected or minimum count")
    valid_whitespace_count = (
        len(whitespace_fields) == expected_count
        if expected_count is not None
        else required_count <= len(whitespace_fields) <= len(widths)
    )

    fixed_segments: list[str] = []
    offset = 0
    for width in widths:
        fixed_segments.append(raw[offset : offset + width])
        offset += width
    fixed_fields = [segment.strip() for segment in fixed_segments]
    segment_token_counts = [len(segment.split()) for segment in fixed_segments]
    crossing_index = next(
        (index for index, count in enumerate(segment_token_counts[:required_count]) if count > 1),
        None,
    )
    empty_required_indices = {
        index for index, field in enumerate(fixed_fields[:required_count]) if not field
    }
    clear_whitespace = (
        valid_whitespace_count
        and bool(whitespace_fields)
        and len(whitespace_fields[0]) <= widths[0]
        and not raw[:1].isspace()
        and crossing_index is not None
        and not any(index < crossing_index for index in empty_required_indices)
    )
    if clear_whitespace:
        return whitespace_fields
    if len(raw) != total_width:
        return []
    if (
        valid_whitespace_count
        and not raw[:1].isspace()
        and whitespace_fields != [field for field in fixed_fields if field]
    ):
        return []
    return fixed_fields


def _manifest_mesh_count(
    resource: JSONDict,
    flat_key: str,
    nested_key: str,
    label: str,
) -> int:
    missing = object()
    flat_value = resource.get(flat_key, missing)
    statistics = resource.get("mesh_statistics", missing)
    if statistics is not missing and not isinstance(statistics, dict):
        raise ValueError(f"model resource '{resource.get('id')}' has invalid mesh_statistics")
    nested_value = (
        statistics.get(nested_key, missing) if isinstance(statistics, dict) else missing
    )

    def normalized(value: object, location: str) -> int | None:
        if value is missing:
            return None
        if isinstance(value, bool):
            raise ValueError(
                f"model resource '{resource.get('id')}' has invalid {label} count in {location}"
            )
        if isinstance(value, int):
            count = value
        elif isinstance(value, float):
            if not math.isfinite(value) or not value.is_integer():
                raise ValueError(
                    f"model resource '{resource.get('id')}' has invalid {label} count in {location}"
                )
            try:
                count = int(value)
            except OverflowError as exc:
                raise ValueError(
                    f"model resource '{resource.get('id')}' has invalid {label} count in {location}"
                ) from exc
        elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
            count = int(value)
        else:
            raise ValueError(
                f"model resource '{resource.get('id')}' has invalid {label} count in {location}"
            )
        if count < 0:
            raise ValueError(
                f"model resource '{resource.get('id')}' has invalid {label} count in {location}"
            )
        return count

    flat_count = normalized(flat_value, flat_key)
    nested_count = normalized(nested_value, f"mesh_statistics.{nested_key}")
    if flat_count is not None and nested_count is not None and flat_count != nested_count:
        raise ValueError(
            f"model resource '{resource.get('id')}' has conflicting {label} count metadata"
        )
    expected = flat_count if flat_count is not None else nested_count
    if expected is None:
        raise ValueError(f"model resource '{resource.get('id')}' has no {label} count metadata")
    return expected


def validate_model_resource(resource_id: str) -> JSONDict:
    resource = get_model_resource(resource_id)
    payload = resource.get("payload")
    if not isinstance(payload, dict):
        raise ValueError(f"model resource '{resource_id}' has invalid payload metadata")
    path = _payload_path(resource)
    actual_hash = _sha256(path)
    if actual_hash != payload.get("sha256"):
        raise ValueError(f"model resource '{resource_id}' payload SHA-256 mismatch")

    expected_node_count = _manifest_mesh_count(resource, "node_count", "nodes", "node")
    expected_solid_count = _manifest_mesh_count(
        resource, "solid_count", "solid_elements", "solid"
    )
    expected_beam_count = _manifest_mesh_count(
        resource, "beam_count", "beam_elements", "beam"
    )

    active = ""
    keyword_order: list[str] = []
    node_ids: set[int] = set()
    element_ids: set[int] = set()
    references: set[int] = set()
    solid_count = beam_count = 0
    pending_ten_node_solid = False
    ten_node_keyword_seen = False
    errors: list[str] = []
    with gzip.open(path, "rt", encoding="utf-8", errors="strict") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped.startswith("*"):
                if active == "*ELEMENT_SOLID" and pending_ten_node_solid:
                    errors.append("incomplete ten-node solid record")
                active = stripped.split()[0].upper()
                keyword_order.append(active)
                pending_ten_node_solid = False
                if active == "*ELEMENT_SOLID":
                    ten_node_keyword_seen = stripped.upper() == "*ELEMENT_SOLID (TEN NODES FORMAT)"
                    if not ten_node_keyword_seen:
                        errors.append("ten-node solids require *ELEMENT_SOLID (ten nodes format)")
                continue
            if not stripped or stripped.startswith("$"):
                continue
            if active == "*NODE":
                fields = _numeric_fields(
                    line,
                    (8, 16, 16, 16, 8, 8),
                    minimum_count=4,
                )
                if not 4 <= len(fields) <= 6:
                    raise ValueError(f"model resource '{resource_id}' has invalid node record")
                try:
                    node_id = int(fields[0])
                    coordinates = tuple(float(value) for value in fields[1:4])
                    tuple(int(value) for value in fields[4:] if value)
                    if not all(math.isfinite(value) for value in coordinates):
                        raise ValueError("non-finite node coordinate")
                except (OverflowError, ValueError) as exc:
                    raise ValueError(
                        f"model resource '{resource_id}' has invalid node record"
                    ) from exc
                if node_id <= 0:
                    raise ValueError(
                        f"model resource '{resource_id}' node ID must be positive: {node_id}"
                    )
                if node_id in node_ids:
                    raise ValueError(
                        f"model resource '{resource_id}' has duplicate node ID: {node_id}"
                    )
                node_ids.add(node_id)
            elif active == "*ELEMENT_SOLID":
                if not pending_ten_node_solid:
                    fields = _numeric_fields(line, (8, 8), expected_count=2)
                    if len(fields) != 2:
                        raise ValueError(
                            f"model resource '{resource_id}' has invalid solid identity record"
                        )
                    try:
                        element_id, _ = (int(value) for value in fields)
                    except (OverflowError, ValueError) as exc:
                        raise ValueError(
                            f"model resource '{resource_id}' has invalid solid identity record"
                        ) from exc
                    if element_id <= 0:
                        raise ValueError(
                            f"model resource '{resource_id}' element ID must be positive: {element_id}"
                        )
                    if element_id in element_ids:
                        raise ValueError(
                            f"model resource '{resource_id}' has duplicate element ID: {element_id}"
                        )
                    element_ids.add(element_id)
                    solid_count += 1
                    pending_ten_node_solid = True
                else:
                    fields = _numeric_fields(line, (8,) * 10, expected_count=10)
                    if len(fields) != 10:
                        raise ValueError(
                            f"model resource '{resource_id}' has invalid solid connectivity record"
                        )
                    try:
                        connectivity = tuple(int(value) for value in fields)
                    except (OverflowError, ValueError) as exc:
                        raise ValueError(
                            f"model resource '{resource_id}' has invalid solid connectivity record"
                        ) from exc
                    references.update(value for value in connectivity if value != 0)
                    pending_ten_node_solid = False
            elif active == "*ELEMENT_BEAM":
                fields = _numeric_fields(line, (8,) * 10, minimum_count=5)
                if not 5 <= len(fields) <= 10:
                    raise ValueError(f"model resource '{resource_id}' has invalid beam record")
                try:
                    beam_fields = tuple(int(value) for value in fields[:5])
                    tuple(int(value) for value in fields[5:] if value)
                except (OverflowError, ValueError) as exc:
                    raise ValueError(
                        f"model resource '{resource_id}' has invalid beam record"
                    ) from exc
                element_id = beam_fields[0]
                if element_id <= 0:
                    raise ValueError(
                        f"model resource '{resource_id}' element ID must be positive: {element_id}"
                    )
                if element_id in element_ids:
                    raise ValueError(
                        f"model resource '{resource_id}' has duplicate element ID: {element_id}"
                    )
                element_ids.add(element_id)
                beam_count += 1
                references.update(beam_fields[2:5])

    if pending_ten_node_solid:
        errors.append("incomplete ten-node solid record")
    if not keyword_order or keyword_order[0] != "*KEYWORD" or keyword_order[-1] != "*END":
        errors.append("payload must start with *KEYWORD and end with *END")
    if solid_count != expected_solid_count:
        errors.append(f"solid count mismatch: {solid_count}")
    if beam_count != expected_beam_count:
        errors.append(f"beam count mismatch: {beam_count}")
    if len(node_ids) != expected_node_count:
        errors.append(f"node count mismatch: {len(node_ids)}")
    if solid_count and not ten_node_keyword_seen:
        errors.append("ten-node solid keyword was not found")
    missing = sorted(references - node_ids)
    if missing:
        errors.append(f"missing node references: {len(missing)}")
    if errors:
        raise ValueError(f"model resource '{resource_id}' validation failed: {'; '.join(errors)}")
    provenance = resource.get("provenance") if isinstance(resource.get("provenance"), dict) else {}
    return {
        "valid": True,
        "resource_id": resource_id,
        "payload_sha256": actual_hash,
        "unit_system": resource.get("unit_system"),
        "source_sha256": provenance.get("source_sha256"),
        "node_count": len(node_ids),
        "solid_count": solid_count,
        "ten_node_solid_count": solid_count,
        "beam_count": beam_count,
        "missing_node_reference_count": 0,
        "validation_status": resource.get("validation_status"),
        "requires_project_review": bool(resource.get("requires_project_review", True)),
    }


def export_model_resource(resource_id: str, output_path: Path) -> Path:
    validate_model_resource(resource_id)
    resource = get_model_resource(resource_id)
    source = _payload_path(resource)
    target = Path(output_path)
    if target.exists():
        raise FileExistsError(f"output file already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        with gzip.open(source, "rb") as compressed, temporary.open("wb") as output:
            for chunk in iter(lambda: compressed.read(1024 * 1024), b""):
                output.write(chunk)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
