from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .config import JSONDict
from .dyna_common import grid_count


@dataclass(frozen=True)
class ComponentDefinition:
    name: str
    element_family: str
    geometry_fields: tuple[str, ...]
    named_surfaces: tuple[str, ...]
    named_edges: tuple[str, ...] = ()
    version: str = "1.0"
    city_category: str = "基础组件"
    city_placeable: bool = False
    city_mobility_profiles: tuple[str, ...] = ()
    city_supports_ale_fsi: bool = False
    city_instance_operations: tuple[str, ...] = ()
    city_response_policy: str = "none"
    city_response_metrics: tuple[str, ...] = ()


@dataclass(frozen=True)
class ComponentInstance:
    component_id: str
    template: str
    raw: JSONDict
    definition: ComponentDefinition

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ComponentInstance":
        raw = dict(value)
        template = str(raw.get("template", ""))
        return cls(
            component_id=str(raw.get("id", "")),
            template=template,
            raw=raw,
            definition=component_definition(template),
        )


@dataclass(frozen=True)
class ComponentIds:
    part_id: int
    section_id: int
    material_id: int


@dataclass
class AssemblyContext:
    next_node_id: int = 1
    next_shell_element_id: int = 1
    next_solid_element_id: int = 1
    next_part_id: int = 1
    next_section_id: int = 1
    next_material_id: int = 1
    next_set_id: int = 1001
    next_contact_id: int = 1

    def allocate_component_ids(self) -> ComponentIds:
        result = ComponentIds(self.next_part_id, self.next_section_id, self.next_material_id)
        self.next_part_id += 1
        self.next_section_id += 1
        self.next_material_id += 1
        return result

    def allocate_node_map(self, node_ids: list[int]) -> dict[int, int]:
        result = {old_id: self.next_node_id + index for index, old_id in enumerate(node_ids)}
        self.next_node_id += len(node_ids)
        return result

    def allocate_shell_element_id(self) -> int:
        result = self.next_shell_element_id
        self.next_shell_element_id += 1
        return result

    def allocate_solid_element_id(self) -> int:
        result = self.next_solid_element_id
        self.next_solid_element_id += 1
        return result

    def allocate_set_id(self) -> int:
        result = self.next_set_id
        self.next_set_id += 1
        return result

    def allocate_contact_id(self) -> int:
        result = self.next_contact_id
        self.next_contact_id += 1
        return result


_COMPONENT_DEFINITIONS = {
    "beam_bar": ComponentDefinition(
        name="beam_bar",
        element_family="solid",
        geometry_fields=("length_m", "width_m", "height_m"),
        named_surfaces=("outer_surface", "start_end", "finish_end"),
    ),
    "circular_plate": ComponentDefinition(
        name="circular_plate",
        element_family="shell",
        geometry_fields=("radius_m", "thickness_m"),
        named_surfaces=("top_surface", "bottom_surface"),
        named_edges=("rim",),
    ),
    "commercial_supermarket": ComponentDefinition(
        name="commercial_supermarket",
        element_family="shell",
        geometry_fields=(
            "length_m",
            "width_m",
            "height_m",
            "wall_thickness_m",
            "entrance_width_m",
            "entrance_height_m",
        ),
        named_surfaces=("facade", "roof", "side_walls", "entrance_canopy"),
        named_edges=("ground_perimeter",),
        city_response_policy="required_individual",
        city_response_metrics=(
            "fsi_pressure",
            "structural_pressure",
            "principal_stress",
            "displacement",
        ),
    ),
    "ellipsoid_shell": ComponentDefinition(
        name="ellipsoid_shell",
        element_family="shell",
        geometry_fields=("radius_x_m", "radius_y_m", "height_m", "thickness_m"),
        named_surfaces=("outer_surface", "inner_surface"),
        named_edges=("rim",),
    ),
    "parking_lot": ComponentDefinition(
        name="parking_lot",
        element_family="shell",
        geometry_fields=("length_m", "width_m", "thickness_m", "parking_rows", "spaces_per_row"),
        named_surfaces=("parking_surface", "curbs"),
        named_edges=("perimeter",),
    ),
    "parked_vehicle": ComponentDefinition(
        name="parked_vehicle",
        element_family="shell",
        geometry_fields=(
            "length_m",
            "width_m",
            "body_height_m",
            "cabin_height_m",
            "shell_thickness_m",
        ),
        named_surfaces=("body", "cabin", "front", "rear", "underbody"),
        named_edges=("body_perimeter",),
        city_category="城市设施",
        city_placeable=True,
        city_mobility_profiles=("surface_dynamic",),
        city_supports_ale_fsi=True,
        city_instance_operations=("add", "duplicate", "delete"),
        city_response_policy="required_individual",
        city_response_metrics=(
            "fsi_pressure",
            "structural_pressure",
            "principal_stress",
            "displacement",
        ),
    ),
    "residential_community": ComponentDefinition(
        name="residential_community",
        element_family="shell",
        geometry_fields=(
            "tower_length_m",
            "tower_width_m",
            "tower_height_m",
            "tower_count",
            "tower_spacing_m",
            "wall_thickness_m",
            "balcony_depth_m",
        ),
        named_surfaces=("tower_facades", "tower_roofs", "balconies", "podium"),
        named_edges=("community_perimeter",),
        city_response_policy="required_individual",
        city_response_metrics=(
            "fsi_pressure",
            "structural_pressure",
            "principal_stress",
            "displacement",
        ),
    ),
    "shell_plate": ComponentDefinition(
        name="shell_plate",
        element_family="shell",
        geometry_fields=("length_m", "width_m", "thickness_m"),
        named_surfaces=("top_surface", "bottom_surface"),
        named_edges=("four_edges", "x_min_edge", "x_max_edge", "y_min_edge", "y_max_edge"),
        city_category="城市结构",
    ),
    "shell_box": ComponentDefinition(
        name="shell_box",
        element_family="shell",
        geometry_fields=("length_m", "width_m", "height_m", "thickness_m"),
        named_surfaces=("outer_surface", "inner_surface", "top", "bottom", "sides"),
        named_edges=("top_edges", "bottom_edges"),
        city_category="城市防护构件",
        city_placeable=True,
        city_mobility_profiles=("grounded",),
        city_supports_ale_fsi=True,
        city_instance_operations=("add", "duplicate", "delete"),
        city_response_policy="required_individual",
        city_response_metrics=(
            "fsi_pressure",
            "structural_pressure",
            "principal_stress",
            "displacement",
        ),
    ),
    "shell_tube": ComponentDefinition(
        name="shell_tube",
        element_family="shell",
        geometry_fields=("radius_m", "length_m", "thickness_m"),
        named_surfaces=("outer_surface", "inner_surface"),
        named_edges=("top_ring", "bottom_ring"),
    ),
    "solid_block": ComponentDefinition(
        name="solid_block",
        element_family="solid",
        geometry_fields=("length_m", "width_m", "height_m"),
        named_surfaces=("x_min", "x_max", "y_min", "y_max", "z_min", "z_max"),
    ),
    "solid_cylinder": ComponentDefinition(
        name="solid_cylinder",
        element_family="solid",
        geometry_fields=("radius_m", "length_m"),
        named_surfaces=("outer_surface", "top_end", "bottom_end"),
    ),
    "sphere_shell": ComponentDefinition(
        name="sphere_shell",
        element_family="shell",
        geometry_fields=("radius_m", "thickness_m"),
        named_surfaces=("outer_surface", "inner_surface"),
    ),
    "subway_entrance": ComponentDefinition(
        name="subway_entrance",
        element_family="shell",
        geometry_fields=(
            "length_m",
            "width_m",
            "platform_height_m",
            "enclosure_height_m",
            "wall_thickness_m",
            "roof_thickness_m",
        ),
        named_surfaces=("platform", "roof", "left_wall", "right_wall", "back_wall", "front_opening"),
        named_edges=("platform_perimeter", "front_opening"),
        city_category="城市设施",
        city_placeable=True,
        city_mobility_profiles=("grounded",),
        city_supports_ale_fsi=True,
        city_instance_operations=("add", "duplicate", "delete"),
        city_response_policy="required_individual",
        city_response_metrics=(
            "fsi_pressure",
            "structural_pressure",
            "principal_stress",
            "displacement",
        ),
    ),
    "traffic_light": ComponentDefinition(
        name="traffic_light",
        element_family="shell",
        geometry_fields=(
            "pole_height_m",
            "pole_radius_m",
            "arm_length_m",
            "head_width_m",
            "head_height_m",
            "thickness_m",
        ),
        named_surfaces=("pole", "mast_arm", "signal_head"),
        named_edges=("pole_base",),
        city_response_policy="required_individual",
        city_response_metrics=(
            "fsi_pressure",
            "structural_pressure",
            "principal_stress",
            "displacement",
        ),
    ),
}


def component_template_names() -> tuple[str, ...]:
    return tuple(sorted(_COMPONENT_DEFINITIONS))


def component_definition(name: str) -> ComponentDefinition:
    try:
        return _COMPONENT_DEFINITIONS[name]
    except KeyError as exc:
        raise ValueError(f"unsupported component template: {name}") from exc


def component_catalog() -> list[JSONDict]:
    return [
        {
            "name": definition.name,
            "version": definition.version,
            "element_family": definition.element_family,
            "geometry_fields": list(definition.geometry_fields),
            "named_surfaces": list(definition.named_surfaces),
            "named_edges": list(definition.named_edges),
            "default_geometry": default_component_geometry(definition.name),
            "default_mesh_size_m": default_component_mesh_size(definition.name),
            "city_editor": {
                "category": definition.city_category,
                "placeable": definition.city_placeable,
                "mobility_profiles": list(definition.city_mobility_profiles),
                "supports_ale_fsi": definition.city_supports_ale_fsi,
                "instance_operations": list(
                    definition.city_instance_operations
                ),
                "response_policy": definition.city_response_policy,
                "response_metrics": list(definition.city_response_metrics),
            },
        }
        for definition in (_COMPONENT_DEFINITIONS[name] for name in component_template_names())
    ]


def default_component_geometry(name: str) -> JSONDict:
    defaults: dict[str, JSONDict] = {
        "beam_bar": {"length_m": 0.5, "width_m": 0.02, "height_m": 0.02},
        "circular_plate": {"radius_m": 0.25, "thickness_m": 0.005},
        "commercial_supermarket": {
            "length_m": 22.0,
            "width_m": 18.0,
            "height_m": 8.0,
            "wall_thickness_m": 0.25,
            "entrance_width_m": 6.0,
            "entrance_height_m": 3.2,
        },
        "ellipsoid_shell": {"radius_x_m": 0.15, "radius_y_m": 0.12, "height_m": 0.10, "thickness_m": 0.002},
        "parking_lot": {
            "length_m": 24.0,
            "width_m": 18.0,
            "thickness_m": 0.15,
            "parking_rows": 2,
            "spaces_per_row": 8,
        },
        "parked_vehicle": {
            "length_m": 4.4,
            "width_m": 1.8,
            "body_height_m": 0.8,
            "cabin_height_m": 0.75,
            "shell_thickness_m": 0.0025,
        },
        "residential_community": {
            "tower_length_m": 8.0,
            "tower_width_m": 10.0,
            "tower_height_m": 18.0,
            "tower_count": 3,
            "tower_spacing_m": 4.0,
            "wall_thickness_m": 0.20,
            "balcony_depth_m": 1.2,
        },
        "shell_box": {"length_m": 0.3, "width_m": 0.2, "height_m": 0.15, "thickness_m": 0.003},
        "shell_plate": {"length_m": 0.5, "width_m": 0.5, "thickness_m": 0.005},
        "shell_tube": {"radius_m": 0.03, "length_m": 0.5, "thickness_m": 0.003},
        "solid_block": {"length_m": 0.2, "width_m": 0.2, "height_m": 0.1},
        "solid_cylinder": {"radius_m": 0.02, "length_m": 0.5},
        "sphere_shell": {"radius_m": 0.1, "thickness_m": 0.002},
        "subway_entrance": {
            "length_m": 6.0,
            "width_m": 4.0,
            "platform_height_m": 0.3,
            "enclosure_height_m": 2.8,
            "wall_thickness_m": 0.2,
            "roof_thickness_m": 0.2,
        },
        "traffic_light": {
            "pole_height_m": 4.5,
            "pole_radius_m": 0.08,
            "arm_length_m": 3.5,
            "head_width_m": 0.3,
            "head_height_m": 0.8,
            "thickness_m": 0.02,
        },
    }
    try:
        return dict(defaults[name])
    except KeyError as exc:
        raise ValueError(f"unsupported component template: {name}") from exc


def default_component_mesh_size(name: str) -> float:
    geometry = default_component_geometry(name)
    characteristic = max(float(value) for key, value in geometry.items() if key != "thickness_m")
    return max(characteristic / 12.0, 0.005)


def estimate_component_mesh(template: str, geometry: Mapping[str, object], mesh_size: float) -> tuple[int, int, JSONDict]:
    if template == "shell_plate":
        nx = grid_count(float(geometry["length_m"]), mesh_size)
        ny = grid_count(float(geometry["width_m"]), mesh_size)
        return (nx + 1) * (ny + 1), nx * ny, {"nx": nx, "ny": ny}
    if template == "commercial_supermarket":
        nx = grid_count(float(geometry["length_m"]), mesh_size)
        ny = grid_count(float(geometry["width_m"]), mesh_size)
        nz = grid_count(float(geometry["height_m"]), mesh_size)
        elements = 2 * (nx * ny + nx * nz + ny * nz)
        return max(elements, 8), elements + 30, {"nx": nx, "ny": ny, "nz": nz, "compound": True}
    if template == "parking_lot":
        nx = grid_count(float(geometry["length_m"]), mesh_size)
        ny = grid_count(float(geometry["width_m"]), mesh_size)
        detail = int(geometry["parking_rows"]) + int(geometry["spaces_per_row"])
        return (nx + 1) * (ny + 1) + 4 * detail, nx * ny + 4 * detail, {
            "nx": nx,
            "ny": ny,
            "compound": True,
        }
    if template == "parked_vehicle":
        nx = grid_count(float(geometry["length_m"]), mesh_size)
        ny = grid_count(float(geometry["width_m"]), mesh_size)
        nz = grid_count(
            float(geometry["body_height_m"]) + float(geometry["cabin_height_m"]),
            mesh_size,
        )
        elements = 2 * (nx * ny + nx * nz + ny * nz)
        return max(elements, 8), elements + 24, {
            "nx": nx,
            "ny": ny,
            "nz": nz,
            "compound": True,
        }
    if template == "residential_community":
        count = int(geometry["tower_count"])
        nx = grid_count(float(geometry["tower_length_m"]), mesh_size)
        ny = grid_count(float(geometry["tower_width_m"]), mesh_size)
        nz = grid_count(float(geometry["tower_height_m"]), mesh_size)
        per_tower = 2 * (nx * ny + nx * nz + ny * nz)
        return max(count * per_tower, 8), count * (per_tower + 30), {
            "tower_count": count,
            "compound": True,
        }
    if template in {"solid_block", "beam_bar"}:
        nx = grid_count(float(geometry["length_m"]), mesh_size)
        ny = grid_count(float(geometry["width_m"]), mesh_size)
        nz = grid_count(float(geometry["height_m"]), mesh_size)
        return (nx + 1) * (ny + 1) * (nz + 1), nx * ny * nz, {"nx": nx, "ny": ny, "nz": nz}
    if template == "solid_cylinder":
        nxy = max(8, 2 * grid_count(float(geometry["radius_m"]), mesh_size))
        nz = grid_count(float(geometry["length_m"]), mesh_size)
        return (nxy + 1) * (nxy + 1) * (nz + 1), nxy * nxy * nz, {"nxy": nxy, "nz": nz}
    if template == "ellipsoid_shell":
        radius = max(float(geometry["radius_x_m"]), float(geometry["radius_y_m"]))
        nt = max(12, round(2.0 * 3.141592653589793 * radius / mesh_size))
        nz = max(3, grid_count(float(geometry["height_m"]), mesh_size))
        return nt * nz + 1, nt * nz, {"nt": nt, "nz": nz}
    if template == "shell_tube":
        nt = max(8, round(2.0 * 3.141592653589793 * float(geometry["radius_m"]) / mesh_size))
        nz = grid_count(float(geometry["length_m"]), mesh_size)
        return nt * (nz + 1), nt * nz, {"nt": nt, "nz": nz}
    if template == "shell_box":
        nx = grid_count(float(geometry["length_m"]), mesh_size)
        ny = grid_count(float(geometry["width_m"]), mesh_size)
        nz = grid_count(float(geometry["height_m"]), mesh_size)
        all_nodes = (nx + 1) * (ny + 1) * (nz + 1)
        interior_nodes = max(nx - 1, 0) * max(ny - 1, 0) * max(nz - 1, 0)
        elements = 2 * (nx * ny + nx * nz + ny * nz)
        return all_nodes - interior_nodes, elements, {"nx": nx, "ny": ny, "nz": nz}
    if template == "circular_plate":
        nr = max(1, grid_count(float(geometry["radius_m"]), mesh_size))
        nt = max(12, round(2.0 * 3.141592653589793 * float(geometry["radius_m"]) / mesh_size))
        return 1 + nr * nt, nr * nt, {"nr": nr, "nt": nt}
    if template == "subway_entrance":
        nx = grid_count(float(geometry["length_m"]), mesh_size)
        ny = grid_count(float(geometry["width_m"]), mesh_size)
        nz = grid_count(float(geometry["enclosure_height_m"]), mesh_size)
        elements = 2 * (nx * ny + nx * nz + ny * nz)
        return max(elements, 8), elements * 3, {"nx": nx, "ny": ny, "nz": nz, "compound": True}
    if template == "traffic_light":
        nz = grid_count(float(geometry["pole_height_m"]), mesh_size)
        nt = max(8, round(2.0 * 3.141592653589793 * float(geometry["pole_radius_m"]) / mesh_size))
        return nt * (nz + 1) + 32, nt * nz + 24, {"nt": nt, "nz": nz, "compound": True}
    if template == "sphere_shell":
        radius = float(geometry["radius_m"])
        nt = max(12, round(2.0 * 3.141592653589793 * radius / mesh_size))
        np = max(4, round(3.141592653589793 * radius / mesh_size))
        return 2 + (np - 1) * nt, np * nt, {"nt": nt, "np": np}
    raise ValueError(f"unsupported component template for preflight: {template}")
