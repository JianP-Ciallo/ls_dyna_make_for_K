from __future__ import annotations

import hashlib
import json
import math

from .config import JSONDict


CITY_LAYOUT_SCHEMA_VERSION = "phase17.city_layout.v1"
CITY_EDITOR_STATE_SCHEMA_VERSION = "phase17.city_editor_state.v1"


def build_city_layout_contract(
    resolved_spec: JSONDict,
    metadata: JSONDict,
) -> JSONDict:
    del resolved_spec
    raw_objects = metadata.get("semantic_objects")
    if not isinstance(raw_objects, list) or not raw_objects:
        raise ValueError("city semantic objects are required for layout fingerprinting")
    objects: list[JSONDict] = []
    for raw in raw_objects:
        if not isinstance(raw, dict):
            raise ValueError("city semantic object entries must be objects")
        object_id = raw.get("object_id")
        if not isinstance(object_id, str) or not object_id:
            raise ValueError("city semantic object_id must be a non-empty string")
        if raw.get("role") == "non_structural_visual_guide":
            continue
        objects.append(
            {
                "object_id": object_id,
                "group_id": str(raw.get("group_id", "")),
                "role": str(raw.get("role", "")),
                "mobility_profile": str(raw.get("mobility_profile", "fixed")),
                "translate_m": _vector3(
                    raw.get("translate_m", [0.0, 0.0, 0.0]),
                    f"{object_id}.translate_m",
                ),
                "rotate_deg": _vector3(
                    raw.get("rotate_deg", [0.0, 0.0, 0.0]),
                    f"{object_id}.rotate_deg",
                ),
                "bounds_m": (
                    _bounds(raw.get("bounds_m"), object_id)
                    if raw.get("bounds_m") is not None
                    else None
                ),
                "support_object_id": raw.get("support_object_id"),
            }
        )
    objects.sort(key=lambda item: item["object_id"])
    return {
        "schema_version": CITY_LAYOUT_SCHEMA_VERSION,
        "semantic_schema_version": str(
            metadata.get("city_semantic_schema_version", "")
        ),
        "objects": objects,
    }


def city_layout_fingerprint(
    resolved_spec: JSONDict,
    metadata: JSONDict,
) -> str:
    return _digest(build_city_layout_contract(resolved_spec, metadata))


def city_editor_state_fingerprint(
    resolved_spec: JSONDict,
    metadata: JSONDict,
) -> str:
    explosive = metadata.get("explosive")
    ale_domain = metadata.get("ale_domain")
    if not isinstance(explosive, dict):
        explosive = resolved_spec.get("explosive")
    if not isinstance(explosive, dict):
        raise ValueError("city explosive metadata is required")
    raw_center = explosive.get("center_m")
    if raw_center is None:
        base = _vector3(explosive.get("base_center_m"), "explosive.base_center_m")
        length = _canonical_number(
            explosive.get("length_m"),
            "explosive.length_m",
        )
        raw_center = [base[0], base[1], base[2] + 0.5 * length]
    center = _vector3(raw_center, "explosive.center_m")
    mesh_fingerprint = (
        ale_domain.get("mesh_fingerprint")
        if isinstance(ale_domain, dict)
        else None
    )
    if not isinstance(mesh_fingerprint, str) or len(mesh_fingerprint) != 64:
        mesh_fingerprint = _digest(resolved_spec.get("mesh", {}))
    return _digest(
        {
            "schema_version": CITY_EDITOR_STATE_SCHEMA_VERSION,
            "layout_fingerprint": city_layout_fingerprint(
                resolved_spec,
                metadata,
            ),
            "blast_center_m": center,
            "ale_mesh_fingerprint": mesh_fingerprint,
        }
    )


def _bounds(value: object, object_id: str) -> JSONDict:
    if not isinstance(value, dict):
        raise ValueError(f"{object_id}.bounds_m must be an object")
    lower = _vector3(value.get("min"), f"{object_id}.bounds_m.min")
    upper = _vector3(value.get("max"), f"{object_id}.bounds_m.max")
    if any(low > high for low, high in zip(lower, upper, strict=True)):
        raise ValueError(f"{object_id}.bounds_m is invalid")
    return {"min": lower, "max": upper}


def _vector3(value: object, path: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{path} must contain three finite numbers")
    return [
        _canonical_number(item, f"{path}[{index}]")
        for index, item in enumerate(value)
    ]


def _canonical_number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{path} must be a finite number")
    return 0.0 if result == 0.0 else result


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()
