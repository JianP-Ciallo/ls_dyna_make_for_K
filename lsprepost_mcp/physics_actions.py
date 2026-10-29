from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Mapping

from .component_library import component_definition
from .config import JSONDict


@dataclass(frozen=True)
class PhysicsActionDefinition:
    type: str
    scope: str
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...] = ()
    description: str = ""


_ACTION_DEFINITIONS = {
    "automatic_nodes_to_surface": PhysicsActionDefinition(
        "automatic_nodes_to_surface",
        "component_pair",
        ("slave", "master"),
        ("slave_region", "friction"),
        "Component node region to component surface contact.",
    ),
    "automatic_surface_to_surface": PhysicsActionDefinition(
        "automatic_surface_to_surface",
        "component_pair",
        ("slave", "master"),
        ("friction",),
        "Automatic surface-to-surface contact between two components.",
    ),
    "blast_enhanced": PhysicsActionDefinition(
        "blast_enhanced",
        "component_surfaces",
        ("charge_type", "equivalent_mass_kg", "position_m", "mode", "targets"),
        ("id", "output_dt_s"),
        "Simplified CONWEP blast load on registered shell component surfaces.",
    ),
    "fixed_region": PhysicsActionDefinition(
        "fixed_region",
        "component",
        ("component", "region"),
        description="Fully constrain a controlled component region.",
    ),
    "gravity": PhysicsActionDefinition(
        "gravity",
        "global",
        ("direction", "acceleration_m_per_s2"),
        ("end_time_s", "curve"),
        "Global body acceleration.",
    ),
    "initial_velocity": PhysicsActionDefinition(
        "initial_velocity",
        "component",
        ("component", "vector_m_per_s"),
        description="Initial translational velocity for all nodes in one component.",
    ),
    "nodal_force": PhysicsActionDefinition(
        "nodal_force",
        "global_edge",
        ("edge", "dof", "value_n"),
        ("end_time_s", "curve"),
        "Nodal force on a controlled global edge selector.",
    ),
    "pressure": PhysicsActionDefinition(
        "pressure",
        "global_face",
        ("face", "pressure_pa"),
        ("end_time_s", "curve"),
        "Pressure on a controlled global face selector.",
    ),
}


_REGION_FACE_ALIASES = {
    "four_edges": ("x_min", "x_max", "y_min", "y_max"),
    "x_min_edge": ("x_min",),
    "x_max_edge": ("x_max",),
    "y_min_edge": ("y_min",),
    "y_max_edge": ("y_max",),
    "rim": ("z_min",),
    "bottom_ring": ("z_min",),
    "top_ring": ("z_max",),
    "bottom_end": ("z_min",),
    "top_end": ("z_max",),
    "start_end": ("x_min",),
    "finish_end": ("x_max",),
}
_DIRECT_FACES = {"x_min", "x_max", "y_min", "y_max", "z_min", "z_max"}
_BLAST_WHOLE_SURFACES = {"top_surface", "bottom_surface", "outer_surface", "inner_surface"}


def physics_action_catalog() -> list[JSONDict]:
    return [
        {
            "type": definition.type,
            "scope": definition.scope,
            "required_fields": list(definition.required_fields),
            "optional_fields": list(definition.optional_fields),
            "description": definition.description,
        }
        for definition in (_ACTION_DEFINITIONS[name] for name in sorted(_ACTION_DEFINITIONS))
    ]


def compile_physics_actions(
    components: list[JSONDict],
    actions: list[JSONDict],
    *,
    contacts: list[JSONDict] | None = None,
    loads: list[JSONDict] | None = None,
) -> JSONDict:
    compiled_components = deepcopy(components)
    compiled_contacts = deepcopy(contacts or [])
    compiled_loads = deepcopy(loads or [])
    if not isinstance(actions, list):
        raise ValueError("actions must be an array")

    component_map: dict[str, JSONDict] = {}
    for index, component in enumerate(compiled_components):
        if not isinstance(component, dict):
            raise ValueError(f"components[{index}] must be an object")
        component_id = _non_empty_string(component.get("id"), f"components[{index}].id")
        component_map[component_id] = component

    summaries: list[JSONDict] = []
    for index, raw_action in enumerate(actions):
        if not isinstance(raw_action, dict):
            raise ValueError(f"actions[{index}] must be an object")
        action_type = _non_empty_string(raw_action.get("type"), f"actions[{index}].type")
        definition = _ACTION_DEFINITIONS.get(action_type)
        if definition is None:
            raise ValueError(f"unsupported physics action type: {action_type}")
        _validate_action_fields(index, raw_action, definition)

        if action_type == "fixed_region":
            component = _component_for_action(component_map, raw_action, index)
            region = _non_empty_string(raw_action.get("region"), f"actions[{index}].region")
            if str(component.get("template")) == "circular_plate" and region == "rim":
                existing_regions = list(component.get("fixed_regions", []))
                component["fixed_regions"] = list(dict.fromkeys([*existing_regions, region]))
            else:
                faces = _fixed_faces_for_region(component, region)
                existing = list(component.get("fixed_faces", []))
                component["fixed_faces"] = list(dict.fromkeys([*existing, *faces]))
            summaries.append({"type": action_type, "component": component["id"], "region": region})
        elif action_type == "initial_velocity":
            component = _component_for_action(component_map, raw_action, index)
            vector = _vector3(raw_action.get("vector_m_per_s"), f"actions[{index}].vector_m_per_s")
            if not any(abs(value) > 0.0 for value in vector):
                raise ValueError(f"actions[{index}].vector_m_per_s must be non-zero")
            component["initial_velocity_m_per_s"] = list(vector)
            summaries.append({"type": action_type, "component": component["id"], "vector_m_per_s": list(vector)})
        elif action_type in {"automatic_surface_to_surface", "automatic_nodes_to_surface"}:
            slave = _known_component_id(component_map, raw_action.get("slave"), f"actions[{index}].slave")
            master = _known_component_id(component_map, raw_action.get("master"), f"actions[{index}].master")
            if slave == master:
                raise ValueError(f"actions[{index}] contact slave and master must differ")
            contact: JSONDict = {"type": action_type, "slave": slave, "master": master}
            if "friction" in raw_action:
                contact["friction"] = _finite_number(raw_action["friction"], f"actions[{index}].friction")
            if action_type == "automatic_nodes_to_surface":
                region = str(raw_action.get("slave_region", "z_min"))
                contact["slave_face"] = _single_face_for_region(component_map[slave], region)
            compiled_contacts.append(contact)
            summaries.append(contact.copy())
        elif action_type == "blast_enhanced":
            if raw_action.get("charge_type") != "tnt":
                raise ValueError(f"actions[{index}].charge_type currently only supports tnt")
            if raw_action.get("mode") != "free_air_burst":
                raise ValueError(f"actions[{index}].mode currently only supports free_air_burst")
            position = _vector3(raw_action.get("position_m"), f"actions[{index}].position_m")
            mass = _positive_number(raw_action.get("equivalent_mass_kg"), f"actions[{index}].equivalent_mass_kg")
            targets = _blast_targets(component_map, raw_action.get("targets"), index)
            output_dt = _positive_number(raw_action.get("output_dt_s", 1.0e-4), f"actions[{index}].output_dt_s")
            load = {
                "type": "blast_enhanced",
                "id": str(raw_action.get("id", f"blast_{index + 1}")),
                "charge_type": "tnt",
                "equivalent_mass_kg": mass,
                "position_m": list(position),
                "mode": "free_air_burst",
                "unit": 2,
                "blast_type": 2,
                "targets": targets,
                "output_dt_s": output_dt,
            }
            compiled_loads.append(load)
            summaries.append(deepcopy(load))
        elif action_type == "gravity":
            direction = _axis(raw_action.get("direction"), f"actions[{index}].direction")
            load: JSONDict = {
                "type": "gravity",
                "direction": direction,
                "acceleration_m_per_s2": _non_zero_number(
                    raw_action.get("acceleration_m_per_s2"), f"actions[{index}].acceleration_m_per_s2"
                ),
            }
            _copy_curve_fields(raw_action, load)
            compiled_loads.append(load)
            summaries.append(load.copy())
        elif action_type == "pressure":
            face = _face(raw_action.get("face"), f"actions[{index}].face")
            load = {
                "type": "pressure_on_segment_set",
                "target": {
                    "type": "segment_set",
                    "name": f"action_pressure_{index + 1}",
                    "selector": {"type": "face", "face": face},
                },
                "pressure_pa": _non_zero_number(raw_action.get("pressure_pa"), f"actions[{index}].pressure_pa"),
            }
            _copy_curve_fields(raw_action, load)
            compiled_loads.append(load)
            summaries.append({"type": action_type, "face": face, "pressure_pa": load["pressure_pa"]})
        elif action_type == "nodal_force":
            edge = _face(raw_action.get("edge"), f"actions[{index}].edge")
            load = {
                "type": "nodal_force",
                "target": {"type": "edge", "edge": edge},
                "dof": _axis(raw_action.get("dof"), f"actions[{index}].dof"),
                "value_n": _non_zero_number(raw_action.get("value_n"), f"actions[{index}].value_n"),
            }
            _copy_curve_fields(raw_action, load)
            compiled_loads.append(load)
            summaries.append({"type": action_type, "edge": edge, "dof": load["dof"], "value_n": load["value_n"]})

    return {
        "components": compiled_components,
        "contacts": compiled_contacts,
        "loads": compiled_loads,
        "actions": summaries,
    }


def _validate_action_fields(index: int, action: Mapping[str, object], definition: PhysicsActionDefinition) -> None:
    allowed = {"type", *definition.required_fields, *definition.optional_fields}
    unknown = sorted(set(action) - allowed)
    if unknown:
        raise ValueError(f"actions[{index}] received unsupported field(s): {', '.join(unknown)}")
    missing = [field for field in definition.required_fields if field not in action]
    if missing:
        raise ValueError(f"actions[{index}] missing required field(s): {', '.join(missing)}")


def _component_for_action(component_map: dict[str, JSONDict], action: Mapping[str, object], index: int) -> JSONDict:
    component_id = _known_component_id(component_map, action.get("component"), f"actions[{index}].component")
    return component_map[component_id]


def _known_component_id(component_map: dict[str, JSONDict], value: object, field: str) -> str:
    component_id = _non_empty_string(value, field)
    if component_id not in component_map:
        raise ValueError(f"{field} references unknown component: {component_id}")
    return component_id


def _fixed_faces_for_region(component: JSONDict, region: str) -> tuple[str, ...]:
    if region in _DIRECT_FACES:
        return (region,)
    definition = component_definition(str(component.get("template", "")))
    if region not in {*definition.named_surfaces, *definition.named_edges}:
        raise ValueError(f"component {component.get('id')} has no named region: {region}")
    faces = _REGION_FACE_ALIASES.get(region)
    if not faces:
        raise ValueError(f"named region {region} cannot be used as a fixed node region")
    return faces


def _single_face_for_region(component: JSONDict, region: str) -> str:
    faces = _fixed_faces_for_region(component, region)
    if len(faces) != 1:
        raise ValueError(f"named region {region} is not a single contact node face")
    return faces[0]


def _copy_curve_fields(source: Mapping[str, object], target: JSONDict) -> None:
    if "end_time_s" in source:
        target["end_time_s"] = _finite_number(source["end_time_s"], "action.end_time_s")
    if "curve" in source:
        target["curve"] = deepcopy(source["curve"])


def _blast_targets(component_map: dict[str, JSONDict], value: object, action_index: int) -> list[JSONDict]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"actions[{action_index}].targets must be a non-empty array")
    targets: list[JSONDict] = []
    seen: set[tuple[str, str]] = set()
    for target_index, raw_target in enumerate(value):
        if not isinstance(raw_target, str) or raw_target.count(".") != 1:
            raise ValueError(f"actions[{action_index}].targets[{target_index}] must be component.surface")
        component_id, surface = [part.strip() for part in raw_target.split(".", 1)]
        component_id = _known_component_id(
            component_map, component_id, f"actions[{action_index}].targets[{target_index}]"
        )
        definition = component_definition(str(component_map[component_id].get("template", "")))
        if definition.element_family != "shell":
            raise ValueError(f"blast target {component_id} must be a shell component")
        if surface not in definition.named_surfaces:
            raise ValueError(f"component {component_id} has no named surface: {surface}")
        if surface not in _BLAST_WHOLE_SURFACES:
            raise ValueError(f"blast target surface {component_id}.{surface} is not available in Phase 12")
        key = (component_id, surface)
        if key in seen:
            raise ValueError(f"duplicate blast target: {component_id}.{surface}")
        seen.add(key)
        targets.append({"component": component_id, "surface": surface})
    return targets


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def _non_zero_number(value: object, field: str) -> float:
    number = _finite_number(value, field)
    if number == 0.0:
        raise ValueError(f"{field} must be non-zero")
    return number


def _positive_number(value: object, field: str) -> float:
    number = _finite_number(value, field)
    if number <= 0.0:
        raise ValueError(f"{field} must be positive")
    return number


def _vector3(value: object, field: str) -> tuple[float, float, float]:
    if not isinstance(value, list | tuple) or len(value) != 3:
        raise ValueError(f"{field} must be [x, y, z]")
    return tuple(_finite_number(item, f"{field}[{index}]") for index, item in enumerate(value))  # type: ignore[return-value]


def _axis(value: object, field: str) -> str:
    axis = _non_empty_string(value, field)
    if axis not in {"x", "y", "z"}:
        raise ValueError(f"{field} must be x, y, or z")
    return axis


def _face(value: object, field: str) -> str:
    face = _non_empty_string(value, field)
    if face not in _DIRECT_FACES:
        raise ValueError(f"{field} must be x_min, x_max, y_min, y_max, z_min, or z_max")
    return face
