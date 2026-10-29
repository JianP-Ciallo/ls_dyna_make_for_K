from __future__ import annotations

from copy import deepcopy
import math

from .component_library import component_definition
from .config import JSONDict
from .dyna_assembly import build_component_geometry


CITY_MOBILITY: dict[str, JSONDict] = {
    "commercial_supermarket": {
        "mobility_profile": "grounded",
        "support_object_id": "ground_foundation",
        "allowed_dofs": ["tx", "ty", "rz"],
    },
    "residential_community": {
        "mobility_profile": "grounded",
        "support_object_id": "ground_foundation",
        "allowed_dofs": ["tx", "ty", "rz"],
    },
    "subway_entrance": {
        "mobility_profile": "grounded",
        "support_object_id": "ground_foundation",
        "allowed_dofs": ["tx", "ty", "rz"],
    },
}
CITY_EDITABLE_TEMPLATES = {
    "commercial_supermarket": ("commercial_supermarket", 2.0),
    "residential_community": ("residential_community", 1.5),
    "subway_entrance": ("subway_entrance", 0.5),
}
CITY_VEHICLE_SAFE_PLACEMENTS: tuple[tuple[float, float, float], ...] = (
    (16.0, -30.0, 0.10),
    (21.5, -30.0, 0.10),
    (27.0, -30.0, 0.10),
    (16.0, -25.5, 0.10),
    (21.5, -25.5, 0.10),
    (27.0, -25.5, 0.10),
    (16.0, -21.0, 0.10),
    (21.5, -21.0, 0.10),
    (27.0, -21.0, 0.10),
)
CITY_SUBWAY_SAFE_PLACEMENTS: tuple[tuple[float, float, float], ...] = (
    (12.0, 12.0, 0.0),
    (20.0, 12.0, 0.0),
    (28.0, 12.0, 0.0),
    (12.0, 20.0, 0.0),
    (20.0, 20.0, 0.0),
    (28.0, 20.0, 0.0),
)
CITY_SHELL_BOX_SAFE_PLACEMENTS: tuple[tuple[float, float, float], ...] = (
    (24.0, 30.0, 0.0),
    (28.0, 30.0, 0.0),
    (32.0, 30.0, 0.0),
    (24.0, 25.0, 0.0),
    (28.0, 25.0, 0.0),
    (32.0, 25.0, 0.0),
)


def apply_city_component_operation(
    raw_spec: JSONDict,
    raw_operation: object,
) -> JSONDict:
    if not isinstance(raw_spec, dict):
        raise ValueError("city component operation requires a city spec")
    if not isinstance(raw_operation, dict):
        raise ValueError("city component operation must be an object")
    action = raw_operation.get("action")
    if action not in {"add", "duplicate", "delete"}:
        raise ValueError("city component action must be add, duplicate, or delete")

    allowed_fields = (
        {"action", "template"}
        if action == "add"
        else {"action", "component_id"}
    )
    unknown = sorted(set(raw_operation) - allowed_fields)
    if unknown:
        raise ValueError(
            "city component operation has unsupported fields: "
            + ", ".join(unknown)
        )

    spec = deepcopy(raw_spec)
    layout = spec.get("layout")
    if not isinstance(layout, dict):
        raise ValueError("city layout is missing")
    if action == "add":
        template = raw_operation.get("template")
        if template not in {
            "parked_vehicle",
            "subway_entrance",
            "shell_box",
        }:
            raise ValueError(
                f"unsupported component template for city placement: {template}"
            )
        source = None
        component_id = None
    else:
        component_id = raw_operation.get("component_id")
        if not isinstance(component_id, str) or not component_id:
            raise ValueError("city component_id must be a non-empty string")
        template = _city_instance_template(component_id)
        if template is None:
            raise ValueError(f"city component {component_id!r} is not removable")
        instances = _city_instance_rows(layout, template)
        source = _find_city_instance(instances, component_id, template)
        if source is None:
            raise ValueError(f"city component {component_id!r} is not removable")

    instances = _city_instance_rows(layout, str(template))
    if action == "delete":
        if (
            template in {"parked_vehicle", "subway_entrance"}
            and len(instances) <= 1
        ):
            label = (
                "parked vehicle"
                if template == "parked_vehicle"
                else "subway entrance"
            )
            raise ValueError(f"city scene must keep at least one {label}")
        instances.remove(source)
        remaining_ids = [
            city_instance_id(item, index, str(template))
            for index, item in enumerate(instances)
        ]
        return {
            "action": action,
            "template": template,
            "spec": spec,
            "selected_component_id": remaining_ids[0] if remaining_ids else None,
            "removed_component_id": component_id,
        }

    maximum = 12 if template == "parked_vehicle" else 6
    if len(instances) >= maximum:
        raise ValueError(
            f"city scene supports at most {maximum} {template} instances"
        )
    origin = _next_city_safe_placement(instances, str(template))
    if origin is None:
        placement = (
            "parking lot"
            if template == "parked_vehicle"
            else "registered ground area"
        )
        raise ValueError(
            f"{placement} has no remaining registered safe placement"
        )
    component_id = _next_city_instance_id(instances, str(template))
    instance = {
        "instance_id": component_id,
        "origin_m": origin,
        "rotate_z_deg": (
            float(source.get("rotate_z_deg", 0.0))
            if isinstance(source, dict)
            else 0.0
        ),
        "editor_added": True,
        "editor_modified": True,
    }
    instances.append(instance)
    return {
        "action": action,
        "template": template,
        "spec": spec,
        "selected_component_id": component_id,
        "added_instance": deepcopy(instance),
    }


def parked_vehicle_instance_id(instance: object, index: int) -> str:
    if not isinstance(instance, dict):
        raise ValueError(f"parked vehicle instance {index + 1} must be an object")
    value = instance.get("instance_id")
    if value is None:
        return f"parked_vehicle_{index + 1}"
    if (
        not isinstance(value, str)
        or _parked_vehicle_index(value) is None
    ):
        raise ValueError(
            f"parked vehicle instance_id {value!r} must match parked_vehicle_N"
        )
    return value


def subway_entrance_instance_id(instance: object, index: int) -> str:
    if not isinstance(instance, dict):
        raise ValueError(f"subway entrance instance {index + 1} must be an object")
    value = instance.get("instance_id")
    if value is None:
        return "subway_entrance" if index == 0 else f"subway_entrance_{index + 1}"
    if not isinstance(value, str) or _subway_entrance_index(value) is None:
        raise ValueError(
            "subway entrance instance_id "
            f"{value!r} must be subway_entrance or subway_entrance_N"
        )
    return value


def ensure_subway_entrance_instances(raw: JSONDict) -> list[object]:
    instances = raw.get("instances")
    if instances is None:
        origin = raw.pop("origin_m", None)
        if origin is None:
            raise ValueError("city subway entrance origin is missing")
        instance: JSONDict = {
            "instance_id": "subway_entrance",
            "origin_m": origin,
            "rotate_z_deg": raw.pop("rotate_z_deg", 0.0),
        }
        if "editor_modified" in raw:
            instance["editor_modified"] = raw.pop("editor_modified")
        instances = [instance]
        raw["instances"] = instances
    if not isinstance(instances, list):
        raise ValueError("city subway entrance instances are missing")
    _assign_city_instance_ids(instances, "subway_entrance")
    return instances


def city_mobility_for(object_id: str) -> JSONDict | None:
    mobility = CITY_MOBILITY.get(object_id)
    if mobility is not None:
        return mobility
    if _parked_vehicle_index(object_id) is not None:
        return {
            "mobility_profile": "surface_dynamic",
            "support_object_id": "parking_lot",
            "support_clearance_m": 0.08,
            "allowed_dofs": ["tx", "ty", "rz"],
        }
    if _subway_entrance_index(object_id) is not None:
        return CITY_MOBILITY["subway_entrance"]
    if _indexed_city_instance(object_id, "shell_box") is not None:
        return {
            "mobility_profile": "grounded",
            "support_object_id": "ground_foundation",
            "allowed_dofs": ["tx", "ty", "rz"],
        }
    return None


def city_editable_objects(metadata: JSONDict) -> list[JSONDict]:
    result: list[JSONDict] = []
    semantic_objects = metadata.get("semantic_objects")
    if not isinstance(semantic_objects, list):
        return result
    for raw in semantic_objects:
        if not isinstance(raw, dict):
            continue
        object_id = str(raw.get("object_id", ""))
        mobility = city_mobility_for(object_id)
        profile = str(
            raw.get("mobility_profile")
            or (mobility or {}).get("mobility_profile")
            or "fixed"
        )
        template = str(raw.get("template") or "")
        try:
            definition = component_definition(template)
        except ValueError:
            definition = None
        bounds = raw.get("bounds_m")
        raw_pivot = raw.get("pivot_world_m")
        if isinstance(raw_pivot, list):
            pivot = _vector3(raw_pivot, f"{object_id}.pivot_world_m")
        else:
            pivot = (
                _bounds_center(bounds)
                if isinstance(bounds, dict)
                else [0.0, 0.0, 0.0]
            )
        result.append(
            {
                "component_id": object_id,
                "template": template,
                "role": str(raw.get("role") or ""),
                "part_ids": list(raw.get("part_ids") or []),
                "pivot_world_m": pivot,
                "translate_m": list(raw.get("translate_m") or [0.0, 0.0, 0.0]),
                "rotate_deg": list(raw.get("rotate_deg") or [0.0, 0.0, 0.0]),
                "mobility_profile": profile,
                "allowed_dofs": list(
                    raw.get("allowed_dofs")
                    or (mobility or {}).get("allowed_dofs")
                    or []
                ),
                "support_object_id": raw.get("support_object_id")
                or (mobility or {}).get("support_object_id"),
                "support_clearance_m": float(
                    raw.get("support_clearance_m")
                    or (mobility or {}).get("support_clearance_m")
                    or 0.0
                ),
                "constraint_mode": str(raw.get("constraint_mode") or "fixed"),
                "supports_ale_fsi": bool(
                    raw.get("supports_ale_fsi")
                    if "supports_ale_fsi" in raw
                    else definition and definition.city_supports_ale_fsi
                ),
                "instance_operations": list(
                    definition.city_instance_operations
                    if definition is not None
                    else ()
                ),
                "editable": profile != "fixed",
            }
        )
    return result


def apply_city_editor_transforms(
    raw_spec: JSONDict,
    transforms: object,
) -> JSONDict:
    if not isinstance(transforms, dict):
        raise ValueError("transforms must be an object")
    spec = deepcopy(raw_spec)
    layout = spec.get("layout")
    if not isinstance(layout, dict):
        raise ValueError("city layout is missing")
    for object_id, raw_transform in transforms.items():
        mobility = city_mobility_for(str(object_id))
        if mobility is None:
            raise ValueError(f"city object {object_id!r} is fixed or unknown")
        if not isinstance(raw_transform, dict):
            raise ValueError(f"transform for {object_id!r} must be an object")
        unknown = sorted(set(raw_transform) - {"translate_m", "rotate_deg"})
        if unknown:
            raise ValueError(
                f"transform for {object_id!r} has unsupported fields: {', '.join(unknown)}"
            )
        translation = _vector3(
            raw_transform.get("translate_m", [0.0, 0.0, 0.0]),
            f"transforms.{object_id}.translate_m",
        )
        rotation = _vector3(
            raw_transform.get("rotate_deg", [0.0, 0.0, 0.0]),
            f"transforms.{object_id}.rotate_deg",
        )
        if abs(translation[2]) > 1.0e-12 or abs(rotation[0]) > 1.0e-12 or abs(rotation[1]) > 1.0e-12:
            raise ValueError(
                f"grounded or surface-constrained city object {object_id!r} only permits "
                "X/Y translation and Z rotation"
            )
        target, template, mesh_size, geometry = _layout_target(layout, str(object_id))
        origin = _vector3(target.get("origin_m"), f"layout.{object_id}.origin_m")
        base_angle = _finite(
            target.get("rotate_z_deg", 0.0),
            f"layout.{object_id}.rotate_z_deg",
        )
        new_angle = base_angle + rotation[2]
        local_center = _layout_local_center(
            geometry,
            str(object_id),
            template,
            mesh_size,
        )
        base_center_offset = _rotate_xy(local_center, base_angle)
        new_center_offset = _rotate_xy(local_center, new_angle)
        target["origin_m"] = [
            origin[0]
            + base_center_offset[0]
            + translation[0]
            - new_center_offset[0],
            origin[1]
            + base_center_offset[1]
            + translation[1]
            - new_center_offset[1],
            origin[2],
        ]
        target["rotate_z_deg"] = new_angle
        target["editor_modified"] = True
    return spec


def apply_city_blast_source(raw_spec: JSONDict, raw_source: object) -> JSONDict:
    if not isinstance(raw_source, dict):
        raise ValueError("blast_source must be an object")
    if raw_source.get("source_id") != "city_tnt":
        raise ValueError("blast_source.source_id must be city_tnt")
    unknown = sorted(set(raw_source) - {"source_id", "position_m"})
    if unknown:
        raise ValueError(
            f"blast_source has unsupported fields: {', '.join(unknown)}"
        )
    position = _vector3(raw_source.get("position_m"), "blast_source.position_m")
    spec = deepcopy(raw_spec)
    explosive = spec.get("explosive")
    if not isinstance(explosive, dict):
        raise ValueError("city explosive definition is missing")
    length = _finite(explosive.get("length_m"), "explosive.length_m")
    explosive["base_center_m"] = [
        position[0],
        position[1],
        position[2] - 0.5 * length,
    ]
    return spec


def _bounds_center(bounds: JSONDict) -> list[float]:
    lower = _vector3(bounds.get("min"), "bounds.min")
    upper = _vector3(bounds.get("max"), "bounds.max")
    return [(lower[index] + upper[index]) * 0.5 for index in range(3)]


def _layout_local_center(
    raw_geometry: JSONDict,
    object_id: str,
    template: str,
    mesh_size: float,
) -> list[float]:
    geometry = {
        key: deepcopy(value)
        for key, value in raw_geometry.items()
        if key
        not in {
            "origin_m",
            "enclosure",
            "open_side",
            "rotate_z_deg",
            "editor_modified",
        }
    }
    component = {
        "template": template,
        "geometry": geometry,
        "mesh": {"size_m": mesh_size},
    }
    if template in {
        "commercial_supermarket",
        "residential_community",
        "subway_entrance",
        "traffic_light",
    }:
        component["structural_response_mode"] = "supported_shell_details"
    nodes, _shells, _solids, _section = build_component_geometry(component, 1)
    if not nodes:
        raise ValueError(f"layout geometry for {object_id!r} produced no nodes")
    return [
        0.5
        * (
            min(float(node[axis]) for node in nodes)
            + max(float(node[axis]) for node in nodes)
        )
        for axis in (1, 2)
    ]


def _layout_target(
    layout: JSONDict,
    object_id: str,
) -> tuple[JSONDict, str, float, JSONDict]:
    layout_key = {
        "commercial_supermarket": "supermarket",
        "residential_community": "residential_community",
    }.get(object_id)
    if layout_key is not None:
        target = layout.get(layout_key)
        if not isinstance(target, dict):
            raise ValueError(f"layout entry for {object_id!r} is missing")
        template, mesh_size = CITY_EDITABLE_TEMPLATES[object_id]
        return target, template, mesh_size, target

    template = _city_instance_template(object_id)
    if template is None:
        raise ValueError(f"layout entry for {object_id!r} is missing")
    if template == "parked_vehicle":
        container = layout.get("parked_vehicles")
    elif template == "subway_entrance":
        container = layout.get("subway_entrance")
    else:
        container = _ensure_library_component_container(layout, template)
    if not isinstance(container, dict):
        raise ValueError(f"layout entry for {object_id!r} is missing")
    instances = _city_instance_rows(layout, template)
    target = _find_city_instance(instances, object_id, template)
    if target is None:
        raise ValueError(f"layout entry for {object_id!r} is missing")
    geometry = {
        key: value
        for key, value in container.items()
        if key != "instances"
    }
    mesh_size = {
        "parked_vehicle": 0.35,
        "subway_entrance": 0.5,
        "shell_box": 0.25,
    }[template]
    return target, template, mesh_size, geometry


def _assign_legacy_vehicle_instance_ids(instances: list[object]) -> None:
    _assign_city_instance_ids(instances, "parked_vehicle")


def _assign_city_instance_ids(
    instances: list[object],
    template: str,
) -> None:
    used: set[str] = set()
    for index, instance in enumerate(instances):
        component_id = city_instance_id(instance, index, template)
        if component_id in used:
            raise ValueError(
                f"duplicate {template} instance_id: {component_id}"
            )
        used.add(component_id)
        if isinstance(instance, dict):
            instance["instance_id"] = component_id


def city_instance_id(instance: object, index: int, template: str) -> str:
    if template == "parked_vehicle":
        return parked_vehicle_instance_id(instance, index)
    if template == "subway_entrance":
        return subway_entrance_instance_id(instance, index)
    if template == "shell_box":
        if not isinstance(instance, dict):
            raise ValueError(
                f"{template} instance {index + 1} must be an object"
            )
        value = instance.get("instance_id")
        if value is None:
            return f"{template}_{index + 1}"
        if (
            not isinstance(value, str)
            or _indexed_city_instance(value, template) is None
        ):
            raise ValueError(
                f"{template} instance_id {value!r} must match {template}_N"
            )
        return value
    raise ValueError(f"unsupported city instance template: {template}")


def _find_city_instance(
    instances: list[object],
    component_id: str,
    template: str,
) -> JSONDict | None:
    for index, instance in enumerate(instances):
        if (
            isinstance(instance, dict)
            and city_instance_id(instance, index, template) == component_id
        ):
            return instance
    return None


def _next_city_instance_id(instances: list[object], template: str) -> str:
    if template in {"parked_vehicle", "shell_box"}:
        prefix = f"{template}_"
        suffixes = [
            int(city_instance_id(item, index, template).removeprefix(prefix))
            for index, item in enumerate(instances)
        ]
        return f"{prefix}{max(suffixes, default=0) + 1}"
    suffixes = []
    for index, item in enumerate(instances):
        component_id = city_instance_id(item, index, template)
        suffixes.append(
            1
            if component_id == "subway_entrance"
            else int(component_id.removeprefix("subway_entrance_"))
        )
    return f"subway_entrance_{max(suffixes, default=1) + 1}"


def _next_city_safe_placement(
    instances: list[object],
    template: str,
) -> list[float] | None:
    occupied: list[list[float]] = []
    for index, instance in enumerate(instances):
        if not isinstance(instance, dict):
            raise ValueError(f"{template} instance {index + 1} must be an object")
        occupied.append(
            _vector3(
                instance.get("origin_m"),
                f"{template}.instances[{index}].origin_m",
            )
        )
    placements = {
        "parked_vehicle": CITY_VEHICLE_SAFE_PLACEMENTS,
        "subway_entrance": CITY_SUBWAY_SAFE_PLACEMENTS,
        "shell_box": CITY_SHELL_BOX_SAFE_PLACEMENTS,
    }[template]
    clearance_x, clearance_y = {
        "parked_vehicle": (4.8, 2.2),
        "subway_entrance": (6.5, 4.5),
        "shell_box": (2.5, 1.8),
    }[template]
    for candidate in placements:
        if not any(
            abs(origin[0] - candidate[0]) < clearance_x
            and abs(origin[1] - candidate[1]) < clearance_y
            for origin in occupied
        ):
            return list(candidate)
    return None


def _city_instance_rows(layout: JSONDict, template: str) -> list[object]:
    if template == "parked_vehicle":
        container = layout.get("parked_vehicles")
    elif template == "subway_entrance":
        container = layout.get("subway_entrance")
    else:
        container = _ensure_library_component_container(layout, template)
    if not isinstance(container, dict):
        raise ValueError(f"city {template} layout is missing")
    if template == "subway_entrance":
        return ensure_subway_entrance_instances(container)
    instances = container.get("instances")
    if not isinstance(instances, list):
        raise ValueError(f"city {template} instances are missing")
    _assign_city_instance_ids(instances, template)
    return instances


def _city_instance_template(component_id: str) -> str | None:
    if _parked_vehicle_index(component_id) is not None:
        return "parked_vehicle"
    if _subway_entrance_index(component_id) is not None:
        return "subway_entrance"
    if _indexed_city_instance(component_id, "shell_box") is not None:
        return "shell_box"
    return None


def _ensure_library_component_container(
    layout: JSONDict,
    template: str,
) -> JSONDict | None:
    if template != "shell_box":
        return None
    library = layout.get("library_components")
    if library is None:
        library = {}
        layout["library_components"] = library
    if not isinstance(library, dict):
        return None
    container = library.get(template)
    if container is None:
        container = {
            "length_m": 2.0,
            "width_m": 1.2,
            "height_m": 1.4,
            "thickness_m": 0.01,
            "instances": [],
        }
        library[template] = container
    return container if isinstance(container, dict) else None


def _parked_vehicle_index(object_id: str) -> int | None:
    prefix = "parked_vehicle_"
    if not object_id.startswith(prefix):
        return None
    suffix = object_id.removeprefix(prefix)
    if not suffix.isdigit():
        return None
    index = int(suffix) - 1
    return index if index >= 0 else None


def _subway_entrance_index(object_id: str) -> int | None:
    if object_id == "subway_entrance":
        return 0
    prefix = "subway_entrance_"
    if not object_id.startswith(prefix):
        return None
    suffix = object_id.removeprefix(prefix)
    if not suffix.isdigit() or int(suffix) < 2:
        return None
    return int(suffix) - 1


def _indexed_city_instance(object_id: str, template: str) -> int | None:
    prefix = f"{template}_"
    if not object_id.startswith(prefix):
        return None
    suffix = object_id.removeprefix(prefix)
    if not suffix.isdigit():
        return None
    index = int(suffix) - 1
    return index if index >= 0 else None


def _rotate_xy(point: list[float], angle_deg: float) -> list[float]:
    angle = math.radians(angle_deg)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return [
        point[0] * cosine - point[1] * sine,
        point[0] * sine + point[1] * cosine,
    ]


def _vector3(value: object, path: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{path} must contain exactly three finite numbers")
    return [_finite(item, f"{path}[{index}]") for index, item in enumerate(value)]


def _finite(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{path} must be a finite number")
    return result
