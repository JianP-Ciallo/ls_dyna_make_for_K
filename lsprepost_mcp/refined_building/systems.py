"""Structural-system registry for the Phase 18C building kernel."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .contracts import JSONDict


_RC_GENERATION_MODES = ("full_reinforced", "concrete_only", "custom")


@dataclass(frozen=True, slots=True)
class StructuralSystemDescriptor:
    system_id: str
    display_name: str
    backend_key: str
    element_families: tuple[str, ...]
    capabilities: tuple[str, ...]
    ui_sections: tuple[str, ...] = ()
    allowed_generation_modes: tuple[str, ...] = ()


_SYSTEMS = (
    StructuralSystemDescriptor(
        "rc_frame",
        "Reinforced-concrete frame",
        "rc",
        ("solid", "beam"),
        ("solid_concrete", "rebar_beam", "embedded_coupling"),
        ("rebar",),
        _RC_GENERATION_MODES,
    ),
    StructuralSystemDescriptor(
        "rc_frame_shear_wall",
        "Reinforced-concrete frame with shear walls",
        "rc",
        ("solid", "beam"),
        ("solid_concrete", "rebar_beam", "embedded_coupling", "shear_wall"),
        ("rebar",),
        _RC_GENERATION_MODES,
    ),
    StructuralSystemDescriptor(
        "steel_frame",
        "Steel frame",
        "steel",
        ("beam", "shell"),
        ("frame_beam", "shell_plate", "steel_connection"),
        ("steel_connections",),
    ),
    StructuralSystemDescriptor(
        "steel_concrete_hybrid",
        "Steel-concrete hybrid",
        "hybrid",
        ("solid", "beam", "shell"),
        (
            "solid_concrete",
            "frame_beam",
            "shell_plate",
            "steel_connection",
            "composite_interface",
        ),
        ("rebar", "steel_connections"),
    ),
    StructuralSystemDescriptor(
        "rc_box",
        "Reinforced-concrete box",
        "rc_box",
        ("solid", "beam"),
        ("solid_concrete", "rebar_beam", "embedded_coupling", "box_structure"),
        ("rebar",),
        _RC_GENERATION_MODES,
    ),
    StructuralSystemDescriptor(
        "custom_hybrid",
        "Custom zoned hybrid",
        "custom_hybrid",
        ("solid", "beam", "shell"),
        ("zoned_subsystems", "explicit_interfaces"),
        (),
    ),
)
_SYSTEMS_BY_ID = {descriptor.system_id: descriptor for descriptor in _SYSTEMS}


def list_structural_systems() -> tuple[StructuralSystemDescriptor, ...]:
    """Return the immutable first-phase structural-system catalog."""

    return _SYSTEMS


def get_structural_system(system_id: str) -> StructuralSystemDescriptor:
    """Resolve one declared structural system."""

    try:
        return _SYSTEMS_BY_ID[system_id]
    except KeyError as exc:
        available = ", ".join(descriptor.system_id for descriptor in _SYSTEMS)
        raise ValueError(
            f"unknown structural system {system_id!r}; available: {available}"
        ) from exc


def ui_sections_for_structural_system(system_id: str) -> tuple[str, ...]:
    """Return UI section semantics owned by the structural descriptor."""

    return get_structural_system(system_id).ui_sections


def normalize_structural_system_profile(value: Mapping[str, object]) -> JSONDict:
    """Normalize system-specific parameters while enforcing capability scope."""

    if not isinstance(value, Mapping):
        raise TypeError("structural system profile must be a mapping")
    system_id = value.get("type")
    if not isinstance(system_id, str) or not system_id.strip():
        raise ValueError("structural system type must be a non-empty string")
    system_id = system_id.strip()
    descriptor = get_structural_system(system_id)
    parameters_raw = value.get("parameters", {})
    if not isinstance(parameters_raw, Mapping):
        raise ValueError("structural system parameters must be a mapping")
    parameters = copy.deepcopy(dict(parameters_raw))
    _validate_json_compatible(parameters, "structural system parameters")

    generation_mode = parameters.get("generation_mode")
    if descriptor.allowed_generation_modes:
        if generation_mode is None:
            parameters["generation_mode"] = "full_reinforced"
        elif generation_mode not in descriptor.allowed_generation_modes:
            allowed = ", ".join(descriptor.allowed_generation_modes)
            raise ValueError(
                f"generation_mode for {system_id!r} must be one of: {allowed}"
            )
    elif generation_mode is not None:
        raise ValueError(f"generation_mode is not supported by {system_id!r}")

    if system_id == "custom_hybrid":
        _normalize_custom_hybrid(parameters)

    return {"type": system_id, "parameters": parameters}


def _normalize_custom_hybrid(parameters: dict[str, object]) -> None:
    subsystems_raw = parameters.get("subsystems")
    if not _is_sequence(subsystems_raw):
        raise ValueError("custom_hybrid.subsystems must be a list with at least two systems")
    subsystems: list[str] = []
    for value in subsystems_raw:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("custom_hybrid.subsystems entries must be non-empty strings")
        system_id = value.strip()
        if system_id == "custom_hybrid":
            raise ValueError("custom_hybrid cannot contain itself as a subsystem")
        get_structural_system(system_id)
        if system_id in subsystems:
            raise ValueError(f"duplicate custom_hybrid subsystem: {system_id!r}")
        subsystems.append(system_id)
    if len(subsystems) < 2:
        raise ValueError("custom_hybrid requires at least two registered subsystems")

    zones_raw = parameters.get("zones")
    if not _is_sequence(zones_raw) or not zones_raw:
        raise ValueError("custom_hybrid requires explicit non-empty zones")
    zones: list[dict[str, object]] = []
    zone_ids: set[str] = set()
    represented: set[str] = set()
    for index, value in enumerate(zones_raw):
        if not isinstance(value, Mapping):
            raise ValueError(f"custom_hybrid.zones[{index}] must be a mapping")
        zone_id = value.get("id")
        system_id = value.get("system_id")
        if not isinstance(zone_id, str) or not zone_id.strip():
            raise ValueError(f"custom_hybrid.zones[{index}].id must be a non-empty string")
        zone_id = zone_id.strip()
        if zone_id in zone_ids:
            raise ValueError(f"duplicate custom_hybrid zone id: {zone_id!r}")
        zone_ids.add(zone_id)
        if not isinstance(system_id, str) or system_id not in subsystems:
            raise ValueError(
                f"custom_hybrid.zones[{index}].system_id must name a declared subsystem"
            )
        bounds = _normalize_bounds(value.get("bounds_m"), f"custom_hybrid.zones[{index}].bounds_m")
        zones.append({"id": zone_id, "system_id": system_id, "bounds_m": bounds})
        represented.add(system_id)

    if represented != set(subsystems):
        missing = ", ".join(sorted(set(subsystems) - represented))
        raise ValueError(f"custom_hybrid zones do not represent subsystems: {missing}")
    for index, left in enumerate(zones):
        for right in zones[index + 1 :]:
            if _bounds_overlap(left["bounds_m"], right["bounds_m"]):
                raise ValueError(
                    f"custom_hybrid zones overlap: {left['id']!r} and {right['id']!r}"
                )

    parameters["subsystems"] = subsystems
    parameters["zones"] = zones


def _normalize_bounds(value: object, path: str) -> list[float]:
    if not _is_sequence(value) or len(value) != 6:
        raise ValueError(f"{path} must contain exactly six finite numbers")
    bounds: list[float] = []
    for component in value:
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            raise ValueError(f"{path} must contain exactly six finite numbers")
        number = float(component)
        if not math.isfinite(number):
            raise ValueError(f"{path} must contain exactly six finite numbers")
        bounds.append(number)
    if any(bounds[index + 3] <= bounds[index] for index in range(3)):
        raise ValueError(f"{path} must have positive extent on every axis")
    return bounds


def _bounds_overlap(left: object, right: object) -> bool:
    assert isinstance(left, list) and isinstance(right, list)
    return all(max(left[index], right[index]) < min(left[index + 3], right[index + 3]) for index in range(3))


def _validate_json_compatible(value: object, path: str) -> None:
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must contain finite numbers")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_compatible(item, path)
        return
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(f"{path} keys must be strings")
        for item in value.values():
            _validate_json_compatible(item, path)
        return
    raise ValueError(f"{path} must contain only JSON-compatible values")


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
