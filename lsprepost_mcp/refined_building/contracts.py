"""Normalized input contract for refined structural buildings."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, TypeAlias


JSONValue: TypeAlias = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
JSONDict: TypeAlias = dict[str, JSONValue]

_SCHEMA_VERSION = "1.0.0"
_UNIT_SYSTEM = "SI_m_s_kg_N_Pa"
_FIDELITY_PROFILES = frozenset(
    {"structural_core", "blast_response", "research_detailed"}
)


def default_building_definition(
    asset_id: str = "refined_building",
    structural_system: str = "rc_frame",
) -> JSONDict:
    """Return a safe, editable minimum building definition in SI units."""

    return {
        "schema_version": _SCHEMA_VERSION,
        "asset_id": asset_id,
        "unit_system": _UNIT_SYSTEM,
        "envelope": {
            "origin_m": [0.0, 0.0, 0.0],
            "size_m": [6.0, 6.0, 3.0],
        },
        "levels": [
            {"id": "level_1", "elevation_m": 0.0, "height_m": 3.0},
        ],
        "grid_axes": {
            "x_m": [0.0, 3.0, 6.0],
            "y_m": [0.0, 3.0, 6.0],
        },
        "spaces": [
            {
                "id": "room_1",
                "level_id": "level_1",
                "kind": "room",
                "bounds_m": [0.25, 0.25, 0.25, 5.75, 5.75, 2.75],
            }
        ],
        "openings": [],
        "structural_system": {"type": structural_system, "parameters": {}},
        "nonstructural": [],
        "fidelity_profile": "blast_response",
        "requires_project_review": True,
    }


def normalize_building_definition(value: Mapping[str, object]) -> JSONDict:
    """Validate and deep-copy a Phase 18C building definition.

    Coordinates are absolute metres.  Bounds use
    ``[min_x, min_y, min_z, max_x, max_y, max_z]``.
    """

    if not isinstance(value, Mapping):
        raise TypeError("building definition must be a mapping")
    copied = _clone_json(value, "building definition")
    assert isinstance(copied, dict)

    schema_version = _required_string(copied, "schema_version")
    if schema_version != _SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {_SCHEMA_VERSION!r}")
    asset_id = _required_string(copied, "asset_id")
    unit_system = _required_string(copied, "unit_system")
    if unit_system != _UNIT_SYSTEM:
        raise ValueError(f"unit_system must be {_UNIT_SYSTEM!r}")
    fidelity_profile = _required_string(copied, "fidelity_profile")
    if fidelity_profile not in _FIDELITY_PROFILES:
        raise ValueError(f"unsupported fidelity_profile: {fidelity_profile!r}")
    if copied.get("requires_project_review") is not True:
        raise ValueError("requires_project_review must remain true")

    envelope = _required_mapping(copied, "envelope")
    origin = _number_vector(envelope.get("origin_m"), 3, "envelope.origin_m")
    size = _number_vector(envelope.get("size_m"), 3, "envelope.size_m")
    if any(component <= 0.0 for component in size):
        raise ValueError("envelope.size_m values must be positive")
    envelope_max = tuple(origin[index] + size[index] for index in range(3))

    levels = _required_mapping_list(copied, "levels", allow_empty=False)
    level_ids: set[str] = set()
    levels_by_id: dict[str, tuple[float, float]] = {}
    normalized_levels: list[JSONValue] = []
    for index, level in enumerate(levels):
        level_id = _required_string(level, "id", f"levels[{index}]")
        _claim_unique(level_id, level_ids, "level")
        elevation = _finite_number(level.get("elevation_m"), f"levels[{index}].elevation_m")
        height = _finite_number(level.get("height_m"), f"levels[{index}].height_m")
        if height <= 0.0:
            raise ValueError(f"levels[{index}].height_m must be positive")
        if elevation < origin[2] or elevation + height > envelope_max[2]:
            raise ValueError(f"levels[{index}] must be inside envelope")
        normalized_levels.append({"id": level_id, "elevation_m": elevation, "height_m": height})
        levels_by_id[level_id] = (elevation, elevation + height)

    grid_axes = _required_mapping(copied, "grid_axes")
    normalized_axes: dict[str, JSONValue] = {}
    for key, axis_index in (("x_m", 0), ("y_m", 1)):
        axis = _number_sequence(grid_axes.get(key), f"grid_axes.{key}")
        if len(axis) < 2:
            raise ValueError(f"grid_axes.{key} must contain at least two coordinates")
        if any(right <= left for left, right in zip(axis, axis[1:])):
            raise ValueError(f"grid_axes.{key} must be strictly increasing")
        if axis[0] < origin[axis_index] or axis[-1] > envelope_max[axis_index]:
            raise ValueError(f"grid_axes.{key} must be inside envelope")
        normalized_axes[key] = axis

    spaces = _required_mapping_list(copied, "spaces", allow_empty=False)
    space_ids: set[str] = set()
    spaces_by_id: dict[str, list[float]] = {}
    normalized_spaces: list[JSONValue] = []
    for index, space in enumerate(spaces):
        label = f"spaces[{index}]"
        space_id = _required_string(space, "id", label)
        _claim_unique(space_id, space_ids, "space")
        level_id = _required_string(space, "level_id", label)
        if level_id not in level_ids:
            raise ValueError(f"{label}.level_id references unknown level {level_id!r}")
        kind = _required_string(space, "kind", label)
        bounds = _bounds(space.get("bounds_m"), f"{label}.bounds_m")
        _require_bounds_inside(bounds, origin, envelope_max, f"{label}.bounds_m")
        level_min_z, level_max_z = levels_by_id[level_id]
        if bounds[2] < level_min_z or bounds[5] > level_max_z:
            raise ValueError(f"{label}.bounds_m must be inside its assigned level")
        normalized_spaces.append(
            {"id": space_id, "level_id": level_id, "kind": kind, "bounds_m": bounds}
        )
        spaces_by_id[space_id] = bounds

    space_rows = sorted(spaces_by_id.items())
    for index, (left_id, left_bounds) in enumerate(space_rows):
        for right_id, right_bounds in space_rows[index + 1 :]:
            if _boxes_overlap(left_bounds, right_bounds):
                raise ValueError(f"space regions overlap: {left_id!r} and {right_id!r}")

    openings = _required_mapping_list(copied, "openings", allow_empty=True)
    opening_ids: set[str] = set()
    normalized_openings: list[JSONValue] = []
    for index, opening in enumerate(openings):
        label = f"openings[{index}]"
        opening_id = _required_string(opening, "id", label)
        _claim_unique(opening_id, opening_ids, "opening")
        kind = _required_string(opening, "kind", label)
        bounds = _bounds(opening.get("bounds_m"), f"{label}.bounds_m")
        _require_bounds_inside(bounds, origin, envelope_max, f"{label}.bounds_m")
        connects_raw = opening.get("connects")
        if not _is_sequence(connects_raw) or len(connects_raw) != 2:
            raise ValueError(f"{label}.connects must contain exactly two space ids")
        connects: list[JSONValue] = []
        for endpoint in connects_raw:
            if not isinstance(endpoint, str) or not endpoint.strip():
                raise ValueError(f"{label}.connects must contain non-empty string ids")
            endpoint = endpoint.strip()
            if endpoint not in space_ids and endpoint != "exterior":
                raise ValueError(f"{label}.connects references unknown endpoint {endpoint!r}")
            connects.append(endpoint)
        if connects[0] == connects[1]:
            raise ValueError(f"{label}.connects endpoints must be different")
        for endpoint in connects:
            if endpoint != "exterior" and not _boxes_touch(bounds, spaces_by_id[str(endpoint)]):
                raise ValueError(f"{label} must touch declared space {endpoint!r}")
        if "exterior" in connects and not _opening_touches_envelope(bounds, origin, envelope_max):
            raise ValueError(f"{label} must touch the envelope boundary")
        normalized_openings.append(
            {"id": opening_id, "kind": kind, "bounds_m": bounds, "connects": connects}
        )

    for index, left in enumerate(normalized_openings):
        assert isinstance(left, dict)
        for right in normalized_openings[index + 1 :]:
            assert isinstance(right, dict)
            if _boxes_overlap(left["bounds_m"], right["bounds_m"]):  # type: ignore[arg-type]
                raise ValueError(
                    f"opening regions overlap: {left['id']!r} and {right['id']!r}"
                )

    structural_system = _required_mapping(copied, "structural_system")
    system_type = _required_string(structural_system, "type", "structural_system")
    parameters = structural_system.get("parameters", {})
    if not isinstance(parameters, Mapping):
        raise ValueError("structural_system.parameters must be a mapping")
    normalized_parameters = _clone_json(parameters, "structural_system.parameters")
    assert isinstance(normalized_parameters, dict)

    nonstructural = copied.get("nonstructural")
    if not isinstance(nonstructural, list):
        raise ValueError("nonstructural must be a list")

    return {
        "schema_version": schema_version,
        "asset_id": asset_id,
        "unit_system": unit_system,
        "envelope": {"origin_m": list(origin), "size_m": list(size)},
        "levels": normalized_levels,
        "grid_axes": normalized_axes,
        "spaces": normalized_spaces,
        "openings": normalized_openings,
        "structural_system": {"type": system_type, "parameters": normalized_parameters},
        "nonstructural": _clone_json(nonstructural, "nonstructural"),
        "fidelity_profile": fidelity_profile,
        "requires_project_review": True,
    }


def _clone_json(value: object, path: str) -> JSONValue:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must contain only finite numbers")
        return value
    if isinstance(value, Mapping):
        result: JSONDict = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings")
            result[key] = _clone_json(nested, f"{path}.{key}")
        return result
    if _is_sequence(value):
        return [_clone_json(nested, f"{path}[]") for nested in value]
    raise ValueError(f"{path} must contain only JSON-compatible values")


def _required_mapping(value: Mapping[str, JSONValue], key: str) -> Mapping[str, JSONValue]:
    nested = value.get(key)
    if not isinstance(nested, Mapping):
        raise ValueError(f"{key} must be a mapping")
    return nested


def _required_mapping_list(
    value: Mapping[str, JSONValue], key: str, *, allow_empty: bool
) -> list[Mapping[str, JSONValue]]:
    nested = value.get(key)
    if not isinstance(nested, list) or (not allow_empty and not nested):
        suffix = "a list" if allow_empty else "a non-empty list"
        raise ValueError(f"{key} must be {suffix}")
    if any(not isinstance(row, Mapping) for row in nested):
        raise ValueError(f"{key} entries must be mappings")
    return list(nested)  # type: ignore[return-value]


def _required_string(
    value: Mapping[str, JSONValue], key: str, path: str | None = None
) -> str:
    nested = value.get(key)
    if not isinstance(nested, str) or not nested.strip():
        raise ValueError(f"{path + '.' if path else ''}{key} must be a non-empty string")
    return nested.strip()


def _finite_number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{path} must be finite")
    return number


def _number_sequence(value: object, path: str) -> list[float]:
    if not _is_sequence(value):
        raise ValueError(f"{path} must be a sequence")
    return [_finite_number(component, f"{path}[{index}]") for index, component in enumerate(value)]


def _number_vector(value: object, length: int, path: str) -> tuple[float, ...]:
    result = _number_sequence(value, path)
    if len(result) != length:
        raise ValueError(f"{path} must contain exactly {length} numbers")
    return tuple(result)


def _bounds(value: object, path: str) -> list[float]:
    bounds = list(_number_vector(value, 6, path))
    if any(bounds[index + 3] <= bounds[index] for index in range(3)):
        raise ValueError(f"{path} must have positive extent on every axis")
    return bounds


def _require_bounds_inside(
    bounds: Sequence[float],
    envelope_min: Sequence[float],
    envelope_max: Sequence[float],
    path: str,
) -> None:
    if any(
        bounds[index] < envelope_min[index] or bounds[index + 3] > envelope_max[index]
        for index in range(3)
    ):
        raise ValueError(f"{path} must be inside envelope")


def _boxes_touch(left_bounds: Sequence[float], right_bounds: Sequence[float]) -> bool:
    """Return whether two positive boxes share a face with positive in-plane overlap."""

    tolerance = 1e-12
    for axis in range(3):
        left_faces = (left_bounds[axis], left_bounds[axis + 3])
        right_faces = (right_bounds[axis], right_bounds[axis + 3])
        boundary_contact = any(
            math.isclose(left_face, right_face, abs_tol=tolerance)
            for left_face in left_faces
            for right_face in right_faces
        )
        if not boundary_contact:
            continue
        other_axes = (candidate for candidate in range(3) if candidate != axis)
        if all(
            min(left_bounds[other + 3], right_bounds[other + 3])
            - max(left_bounds[other], right_bounds[other])
            > tolerance
            for other in other_axes
        ):
            return True
    return False


def _boxes_overlap(left_bounds: Sequence[float], right_bounds: Sequence[float]) -> bool:
    return all(
        max(left_bounds[axis], right_bounds[axis])
        < min(left_bounds[axis + 3], right_bounds[axis + 3])
        for axis in range(3)
    )


def _opening_touches_envelope(
    bounds: Sequence[float],
    envelope_min: Sequence[float],
    envelope_max: Sequence[float],
) -> bool:
    tolerance = 1e-12
    return any(
        math.isclose(bounds[axis], envelope_min[axis], abs_tol=tolerance)
        or math.isclose(bounds[axis + 3], envelope_max[axis], abs_tol=tolerance)
        for axis in range(3)
    )


def _claim_unique(identifier: str, seen: set[str], kind: str) -> None:
    if identifier in seen:
        raise ValueError(f"duplicate {kind} id: {identifier!r}")
    seen.add(identifier)


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
