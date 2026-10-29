from __future__ import annotations

from dataclasses import dataclass
import math

from .component_library import component_definition, component_template_names
from .component_model_resources import component_resource_spec
from .config import DEFAULT_UNIT_SYSTEM, JSONDict
from .materials import resolve_material
from .paths import safe_project_name


SUPPORTED_MODEL_TYPES = {
    "shell_plate",
    "solid_block",
    "shell_box",
    "cylinder_shell",
    "cylinder_solid",
    "beam_bar",
    "assembly_scene",
    "ale_blast_scene",
    "single_solid_element_test",
    "imported_keyword",
}

SUPPORTED_MATERIAL_TYPES = {
    "elastic",
    "piecewise_linear_plasticity",
    "cscm_concrete",
    "johnson_holmquist_concrete",
    "rht",
    "concrete_damage_rel3",
    "user_defined_material_models",
    "user_defined_material",
}


@dataclass(frozen=True)
class ModelSpec:
    project_name: str
    model_type: str
    unit_system: str
    geometry: JSONDict
    mesh: JSONDict
    material: JSONDict
    curves: list[JSONDict]
    hourglass: JSONDict
    analysis_control: JSONDict
    database: JSONDict
    components: list[JSONDict]
    model_resources: list[JSONDict]
    contacts: list[JSONDict]
    sets: list[JSONDict]
    boundary_conditions: list[JSONDict]
    loads: list[JSONDict]
    warnings: list[JSONDict]


def default_model_spec(project_name: str = "plate_demo", model_type: str = "shell_plate") -> JSONDict:
    if model_type == "ale_blast_scene":
        from .ale_blast import default_ale_blast_spec

        return default_ale_blast_spec(project_name)
    geometry_by_type: dict[str, JSONDict] = {
        "shell_plate": {"length_m": 0.12, "width_m": 0.06, "thickness_m": 0.0015},
        "solid_block": {"length_m": 0.12, "width_m": 0.06, "height_m": 0.02},
        "shell_box": {
            "length_m": 0.12,
            "width_m": 0.06,
            "height_m": 0.04,
            "thickness_m": 0.0015,
        },
        "cylinder_shell": {"radius_m": 0.03, "length_m": 0.12, "thickness_m": 0.0015},
        "cylinder_solid": {"radius_m": 0.03, "length_m": 0.12},
        "beam_bar": {"length_m": 0.12, "width_m": 0.01, "height_m": 0.01},
        "assembly_scene": {},
        "single_solid_element_test": {"length_m": 0.01, "width_m": 0.01, "height_m": 0.01},
    }
    if model_type not in geometry_by_type:
        model_type = "shell_plate"
    return {
        "project_name": project_name,
        "model_type": model_type,
        "unit_system": DEFAULT_UNIT_SYSTEM,
        "geometry": geometry_by_type[model_type],
        "mesh": {"size_m": 0.01},
        "material": {
            "name": "mild_steel",
            "type": "elastic",
            "density_kg_per_m3": 7850.0,
            "youngs_pa": 210000000000.0,
            "poisson": 0.3,
        },
        "curves": [],
        "hourglass": {},
        "analysis_control": {},
        "database": {},
        "components": default_assembly_components() if model_type == "assembly_scene" else [],
        "model_resources": [],
        "contacts": default_assembly_contacts() if model_type == "assembly_scene" else [],
        "sets": [],
        "boundary_conditions": [] if model_type == "assembly_scene" else [{"type": "fixed_edge", "edge": "x_min"}],
        "loads": [],
    }


def rebar_drop_on_helmet_spec(project_name: str = "rebar_drop_on_helmet") -> JSONDict:
    spec = default_model_spec(project_name, "assembly_scene")
    spec["geometry"] = {"scene": "rebar_drop_on_helmet"}
    spec["analysis_control"] = {
        "termination": {"end_time_s": 1.8},
        "energy": {"hgen": 2, "rwen": 2, "slnten": 2, "rylen": 2},
        "timestep": {"tssfac": 0.9},
    }
    spec["database"] = {
        "format": 0,
        "d3plot_dt_s": 0.01,
        "d3thdt_dt_s": 0.01,
        "extent_binary": {"strflg": 1, "sigflg": 1, "epsflg": 1, "rltflg": 1, "engflg": 1},
    }
    spec["components"] = [
        {
            "id": "rebar",
            "template": "solid_cylinder",
            "geometry": {"radius_m": 0.012, "length_m": 1.0},
            "mesh": {"size_m": 0.01},
            "material": {"name": "mild_steel"},
            "transform": {"translate_m": [0.0, 0.0, 0.62]},
            "initial_velocity_m_per_s": [0.0, 0.0, -10.0],
        },
        {
            "id": "helmet",
            "template": "ellipsoid_shell",
            "geometry": {
                "radius_x_m": 0.18,
                "radius_y_m": 0.14,
                "height_m": 0.12,
                "thickness_m": 0.003,
            },
            "mesh": {"size_m": 0.025},
            "material": {"name": "mild_steel"},
            "transform": {"translate_m": [0.0, 0.0, 0.0]},
            "fixed_faces": ["z_min"],
        },
    ]
    spec["contacts"] = [
        {
            "type": "automatic_surface_to_surface",
            "slave": "rebar",
            "master": "helmet",
            "friction": 0.2,
        }
    ]
    spec["loads"] = [{"type": "gravity", "direction": "z", "acceleration_m_per_s2": -9.81}]
    spec["geometry"]["drop_height_m"] = 0.5
    spec["geometry"]["impact_velocity_m_per_s"] = 10.0
    return spec


def rod_impact_plate_spec(project_name: str = "rod_impact_plate") -> JSONDict:
    spec = default_model_spec(project_name, "assembly_scene")
    spec["geometry"] = {"scene": "rod_impact_plate"}
    spec["analysis_control"] = {
        "termination": {"end_time_s": 0.1},
        "energy": {"hgen": 2, "rwen": 2, "slnten": 2, "rylen": 2},
        "timestep": {"tssfac": 0.9},
    }
    spec["database"] = {"format": 0, "d3plot_dt_s": 0.001, "d3thdt_dt_s": 0.001}
    spec["components"] = [
        {
            "id": "rod",
            "template": "solid_cylinder",
            "geometry": {"radius_m": 0.02, "length_m": 0.5},
            "mesh": {"size_m": 0.02},
            "material": {"name": "mild_steel"},
            "transform": {"translate_m": [0.0, 0.0, 0.05]},
            "initial_velocity_m_per_s": [0.0, 0.0, -10.0],
        },
        {
            "id": "plate",
            "template": "shell_plate",
            "geometry": {"length_m": 0.8, "width_m": 0.6, "thickness_m": 0.004},
            "mesh": {"size_m": 0.05},
            "material": {"name": "mild_steel"},
            "transform": {"translate_m": [-0.4, -0.3, 0.0]},
            "fixed_faces": ["x_min", "x_max", "y_min", "y_max"],
        },
    ]
    spec["contacts"] = [
        {
            "type": "automatic_surface_to_surface",
            "slave": "rod",
            "master": "plate",
            "friction": 0.2,
        }
    ]
    spec["loads"] = []
    return spec


def cube_top_corner_load_spec(project_name: str = "cube_top_corner_load") -> JSONDict:
    spec = default_model_spec(project_name, "solid_block")
    spec["geometry"] = {"length_m": 2.0, "width_m": 2.0, "height_m": 2.0, "scene": "cube_top_corner_load"}
    spec["mesh"] = {"size_m": 0.5}
    spec["material"] = {"name": "mild_steel"}
    spec["hourglass"] = {
        "id": 1,
        "title": "Cube solid hourglass control",
        "ihq": 3,
        "qm": 0.05,
        "ibq": 1,
        "q1": 1.4,
        "q2": 0.5,
    }
    spec["sets"] = [
        {
            "type": "node_set",
            "name": "top_corner_nodes",
            "selector": {"type": "face_corners", "face": "z_max"},
        }
    ]
    spec["boundary_conditions"] = [{"type": "fixed_edge", "edge": "z_min"}]
    spec["loads"] = [
        {
            "type": "nodal_force",
            "target": {"type": "node_set", "name": "top_corner_nodes"},
            "dof": "z",
            "value_n": -1000.0,
            "curve": {"type": "ramp", "start_value": 0.0, "end_value": -1000.0, "end_time_s": 1.0},
        }
    ]
    spec["analysis_control"] = {
        "termination": {"end_time_s": 1.0},
        "energy": {"hgen": 2, "rwen": 2, "slnten": 2, "rylen": 2},
        "timestep": {"tssfac": 0.9},
    }
    spec["database"] = {"format": 0, "d3plot_dt_s": 0.01}
    return spec


def plate_pressure_spec(project_name: str = "plate_pressure") -> JSONDict:
    spec = default_model_spec(project_name, "shell_plate")
    spec["geometry"] = {"length_m": 1.0, "width_m": 0.5, "thickness_m": 0.003, "scene": "plate_pressure"}
    spec["mesh"] = {"size_m": 0.05}
    spec["material"] = {"name": "mild_steel"}
    spec["hourglass"] = {
        "id": 1,
        "title": "Plate shell hourglass control",
        "ihq": 3,
        "qm": 0.05,
        "ibq": 1,
        "q1": 1.4,
        "q2": 0.5,
    }
    spec["sets"] = [{"type": "segment_set", "name": "plate_surface", "selector": {"type": "all_shell"}}]
    spec["boundary_conditions"] = [{"type": "fixed_edge", "edge": "x_min"}]
    spec["loads"] = [
        {
            "type": "pressure_on_segment_set",
            "target": {"type": "segment_set", "name": "plate_surface"},
            "pressure_pa": 20000.0,
            "curve": {"type": "ramp", "start_value": 0.0, "end_value": 20000.0, "end_time_s": 1.0},
        }
    ]
    spec["analysis_control"] = {
        "termination": {"end_time_s": 1.0},
        "energy": {"hgen": 2, "rwen": 2, "slnten": 2, "rylen": 2},
        "shell": {"wrpang": 20.0},
        "timestep": {"tssfac": 0.9},
    }
    spec["database"] = {"format": 0, "d3plot_dt_s": 0.01}
    return spec


def default_assembly_components() -> list[JSONDict]:
    return [
        {
            "id": "rod",
            "template": "solid_cylinder",
            "geometry": {"radius_m": 0.01, "length_m": 0.2},
            "mesh": {"size_m": 0.02},
            "transform": {"translate_m": [0.0, 0.0, 0.08]},
            "initial_velocity_m_per_s": [0.0, 0.0, -5.0],
        },
        {
            "id": "plate",
            "template": "shell_plate",
            "geometry": {"length_m": 0.4, "width_m": 0.4, "thickness_m": 0.004},
            "mesh": {"size_m": 0.04},
            "transform": {"translate_m": [-0.2, -0.2, 0.0]},
            "fixed_faces": ["x_min", "x_max", "y_min", "y_max"],
        },
    ]


def default_assembly_contacts() -> list[JSONDict]:
    return [
        {
            "type": "automatic_surface_to_surface",
            "slave": "rod",
            "master": "plate",
            "friction": 0.2,
        }
    ]


def generate_model_input_schema() -> JSONDict:
    return {
        "type": "object",
        "properties": {
            "if_exists": {
                "type": "string",
                "enum": ["error", "overwrite", "archive_then_write", "versioned"],
                "default": "error",
                "description": "Project collision policy. Default refuses to overwrite existing projects.",
            },
            "spec": {
                "type": "object",
                "description": "Structured SI model spec. Supported model types include controlled structural models, assembly_scene, and ale_blast_scene.",
                "properties": {
                    "project_name": {"type": "string", "default": "plate_demo"},
                    "model_type": {
                        "type": "string",
                        "enum": [
                            "shell_plate",
                            "solid_block",
                            "shell_box",
                            "cylinder_shell",
                            "cylinder_solid",
                            "beam_bar",
                            "assembly_scene",
                            "ale_blast_scene",
                            "single_solid_element_test",
                        ],
                        "default": "shell_plate",
                    },
                    "unit_system": {"type": "string", "default": DEFAULT_UNIT_SYSTEM},
                    "geometry": {"type": "object", "additionalProperties": True},
                    "mesh": {"type": "object", "additionalProperties": True},
                    "material": {"type": "object", "additionalProperties": True},
                    "curves": {
                        "type": "array",
                        "items": {"type": "object", "additionalProperties": True},
                    },
                    "hourglass": {"type": "object", "additionalProperties": True},
                    "analysis_control": {"type": "object", "additionalProperties": True},
                    "database": {"type": "object", "additionalProperties": True},
                    "components": {
                        "type": "array",
                        "items": {"type": "object", "additionalProperties": True},
                    },
                    "model_resources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "model_resource_id": {"type": "string"},
                                "transform": {
                                    "type": "object",
                                    "properties": {
                                        "translation_m": {
                                            "type": "array", "items": {"type": "number"},
                                            "minItems": 3, "maxItems": 3,
                                        },
                                        "rotation_deg": {
                                            "type": "array", "items": {"type": "number"},
                                            "minItems": 3, "maxItems": 3,
                                        },
                                    },
                                    "additionalProperties": False,
                                },
                                "material_binding": {"type": "string", "enum": ["source_reference"]},
                            },
                            "required": ["id", "model_resource_id"],
                            "additionalProperties": False,
                        },
                    },
                    "contacts": {
                        "type": "array",
                        "items": {"type": "object", "additionalProperties": True},
                    },
                    "sets": {
                        "type": "array",
                        "items": {"type": "object", "additionalProperties": True},
                    },
                    "boundary_conditions": {
                        "type": "array",
                        "items": {"type": "object", "additionalProperties": True},
                    },
                    "loads": {
                        "type": "array",
                        "items": {"type": "object", "additionalProperties": True},
                    },
                },
                "additionalProperties": False,
            }
        },
        "additionalProperties": False,
    }


def normalize_model_resources(rows: list[object]) -> list[JSONDict]:
    """Validate the additive component-resource instance contract."""
    normalized: list[JSONDict] = []
    seen_ids: set[str] = set()
    allowed = {"id", "model_resource_id", "transform", "material_binding"}
    transform_allowed = {"translation_m", "rotation_deg"}

    def vector(value: object, path: str) -> list[float]:
        if value is None:
            return [0.0, 0.0, 0.0]
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ValueError(f"{path} must contain three numbers")
        try:
            result = [float(item) for item in value]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path} must contain three numbers") from exc
        if not all(math.isfinite(item) for item in result):
            raise ValueError(f"{path} values must be finite")
        return result

    for index, row in enumerate(rows):
        path = f"spec.model_resources[{index}]"
        if not isinstance(row, dict):
            raise ValueError(f"{path} must be an object")
        unknown = sorted(set(row) - allowed)
        if unknown:
            raise ValueError(f"{path} has unsupported field(s): {', '.join(unknown)}")

        raw_id = str(row.get("id", ""))
        instance_id = safe_project_name(raw_id)
        if instance_id != raw_id:
            raise ValueError(f"{path}.id contains unsupported characters")
        if instance_id in seen_ids:
            raise ValueError(f"duplicate model resource instance id '{instance_id}'")
        seen_ids.add(instance_id)

        resource_id = str(row.get("model_resource_id", "")).strip()
        component_resource_spec(resource_id)
        material_binding = str(row.get("material_binding", "source_reference"))
        if material_binding != "source_reference":
            raise ValueError(f"{path}.material_binding must be source_reference")

        transform = row.get("transform") or {}
        if not isinstance(transform, dict):
            raise ValueError(f"{path}.transform must be an object")
        transform_unknown = sorted(set(transform) - transform_allowed)
        if transform_unknown:
            raise ValueError(
                f"{path}.transform has unsupported field(s): {', '.join(transform_unknown)}"
            )
        normalized.append(
            {
                "id": instance_id,
                "model_resource_id": resource_id,
                "transform": {
                    "translation_m": vector(transform.get("translation_m"), f"{path}.transform.translation_m"),
                    "rotation_deg": vector(transform.get("rotation_deg"), f"{path}.transform.rotation_deg"),
                },
                "material_binding": material_binding,
            }
        )
    return normalized


def parse_model_spec(raw: JSONDict) -> ModelSpec:
    raw_project_name = str(raw.get("project_name", "plate_demo"))
    project_name = safe_project_name(raw_project_name)
    if project_name != raw_project_name:
        raise ValueError("project_name contains unsupported characters; use letters, numbers, '_' or '-'")
    model_type = str(raw.get("model_type", "shell_plate"))
    if model_type not in SUPPORTED_MODEL_TYPES or model_type == "imported_keyword":
        raise ValueError(
            "model_type must be one of shell_plate, solid_block, shell_box, cylinder_shell, cylinder_solid, beam_bar, assembly_scene, ale_blast_scene, single_solid_element_test"
        )
    unit_system = str(raw.get("unit_system", DEFAULT_UNIT_SYSTEM))
    if unit_system != DEFAULT_UNIT_SYSTEM:
        raise ValueError(f"only unit_system='{DEFAULT_UNIT_SYSTEM}' is supported")

    geometry = raw.get("geometry") or {}
    mesh = raw.get("mesh") or {}
    material = raw.get("material") or {}
    curves = raw.get("curves", [])
    hourglass = raw.get("hourglass") or {}
    analysis_control = raw.get("analysis_control") or {}
    database = raw.get("database") or {}
    components = raw.get("components", [])
    model_resources = raw.get("model_resources", [])
    contacts = raw.get("contacts", [])
    sets = raw.get("sets", [])
    boundary_conditions = raw.get("boundary_conditions", [])
    loads = raw.get("loads", [])
    if not isinstance(geometry, dict):
        raise ValueError("spec.geometry must be an object")
    if not isinstance(mesh, dict):
        raise ValueError("spec.mesh must be an object")
    if not isinstance(material, dict):
        raise ValueError("spec.material must be an object")
    if not isinstance(curves, list):
        raise ValueError("spec.curves must be a list")
    if not isinstance(hourglass, dict):
        raise ValueError("spec.hourglass must be an object")
    if not isinstance(analysis_control, dict):
        raise ValueError("spec.analysis_control must be an object")
    if not isinstance(database, dict):
        raise ValueError("spec.database must be an object")
    if not isinstance(components, list):
        raise ValueError("spec.components must be a list")
    if not isinstance(model_resources, list):
        raise ValueError("spec.model_resources must be a list")
    if not isinstance(contacts, list):
        raise ValueError("spec.contacts must be a list")
    if not isinstance(sets, list):
        raise ValueError("spec.sets must be a list")
    if not isinstance(boundary_conditions, list):
        raise ValueError("spec.boundary_conditions must be a list")
    if not isinstance(loads, list):
        raise ValueError("spec.loads must be a list")

    model_resources = normalize_model_resources(model_resources)
    validate_curves(curves)
    validate_hourglass(hourglass)
    validate_analysis_control(analysis_control)
    validate_database(database)
    if model_type == "assembly_scene":
        if geometry.get("scene") == "rebar_drop_on_helmet" and not components:
            scene = rebar_drop_on_helmet_spec(project_name)
            components = scene["components"]
            contacts = contacts or scene["contacts"]
            loads = loads or scene["loads"]
            analysis_control = analysis_control or scene["analysis_control"]
            database = database or scene["database"]
        components = normalize_components(components, material)
        validate_components(components)
        validate_contacts(contacts, {str(component["id"]) for component in components})
        if boundary_conditions:
            validate_named_sets(sets)
            validate_boundary_conditions(boundary_conditions, sets)
        elif not any(component.get("fixed_faces") or component.get("fixed_regions") for component in components):
            raise ValueError(
                "assembly_scene must include at least one component fixed_faces/fixed_regions entry or boundary condition"
            )
    elif model_type == "ale_blast_scene":
        if components:
            raise ValueError("ale_blast_scene does not accept assembly components")
        if contacts:
            raise ValueError("ale_blast_scene uses controlled ALE-Lagrange coupling, not contact cards")
        if sets or boundary_conditions or loads:
            raise ValueError(
                "ale_blast_scene creates its controlled sets, boundaries, and initialization internally"
            )
    else:
        validate_named_sets(sets)
        validate_boundary_conditions(boundary_conditions, sets)
        if components:
            raise ValueError("spec.components is only supported for assembly_scene")
        if contacts:
            raise ValueError("spec.contacts is only supported for assembly_scene")
    validate_loads(loads, sets, components)
    validate_curve_references(curves, boundary_conditions, loads)
    warnings = collect_unknown_field_warnings(
        raw,
        model_type,
        geometry,
        mesh,
        material,
        curves,
        hourglass,
        analysis_control,
        database,
        components,
        contacts,
        sets,
        boundary_conditions,
        loads,
    )

    normalized = ModelSpec(
        project_name=project_name,
        model_type=model_type,
        unit_system=unit_system,
        geometry=normalize_geometry(model_type, geometry),
        mesh=normalize_mesh(mesh),
        material=normalize_material(material),
        curves=curves,
        hourglass=hourglass,
        analysis_control=analysis_control,
        database=database,
        components=components,
        model_resources=model_resources,
        contacts=contacts,
        sets=sets,
        boundary_conditions=boundary_conditions,
        loads=loads,
        warnings=warnings,
    )
    validate_model_spec(normalized)
    return normalized


def collect_unknown_field_warnings(
    raw: JSONDict,
    model_type: str,
    geometry: JSONDict,
    mesh: JSONDict,
    material: JSONDict,
    curves: list[JSONDict],
    hourglass: JSONDict,
    analysis_control: JSONDict,
    database: JSONDict,
    components: list[JSONDict],
    contacts: list[JSONDict],
    sets: list[JSONDict],
    boundary_conditions: list[JSONDict],
    loads: list[JSONDict],
) -> list[JSONDict]:
    warnings: list[JSONDict] = []

    def warn(path: str, key: str) -> None:
        warnings.append(
            {
                "id": "schema.unknown_field",
                "path": path,
                "field": key,
                "message": f"{path}.{key} is not used by the current compiler",
            }
        )

    def check_object(path: str, value: JSONDict, allowed: set[str]) -> None:
        for key in value:
            if key not in allowed:
                warn(path, str(key))

    check_object(
        "spec",
        raw,
        {
            "project_name",
            "model_type",
            "unit_system",
            "geometry",
            "mesh",
            "material",
            "curves",
            "hourglass",
            "analysis_control",
            "database",
            "components",
            "model_resources",
            "contacts",
            "sets",
            "boundary_conditions",
            "loads",
        },
    )
    geometry_keys = {
        "shell_plate": {"length_m", "width_m", "thickness_m"},
        "solid_block": {"length_m", "width_m", "height_m"},
        "shell_box": {"length_m", "width_m", "height_m", "thickness_m"},
        "cylinder_shell": {"radius_m", "length_m", "thickness_m"},
        "cylinder_solid": {"radius_m", "length_m"},
        "beam_bar": {"length_m", "width_m", "height_m"},
        "assembly_scene": {"scene"},
        "ale_blast_scene": {
            "domain_min_m",
            "domain_max_m",
            "explosive_center_m",
            "explosive_mass_kg",
            "explosive_material",
            "plate_length_m",
            "plate_width_m",
            "plate_thickness_m",
            "plate_z_m",
            "scene_variant",
            "tunnel_length_m",
            "tunnel_width_m",
            "tunnel_height_m",
            "tunnel_wall_thickness_m",
            "tunnel_material_name",
            "plate_center_m",
        },
        "single_solid_element_test": {"length_m", "width_m", "height_m"},
    }.get(model_type, set())
    check_object(
        "spec.geometry",
        geometry,
        geometry_keys | {"length_mm", "width_mm", "height_mm", "thickness_mm", "radius_mm"},
    )
    check_object(
        "spec.mesh",
        mesh,
        {
            "size_m",
            "size_mm",
            "elform",
            "mode",
            "charge_size_m",
            "wave_path_size_m",
            "wall_size_m",
            "plate_size_m",
        },
    )
    check_object(
        "spec.material",
        material,
        {
            "id",
            "mid",
            "name",
            "title",
            "type",
            "density_kg_per_m3",
            "density_g_per_mm3",
            "youngs_pa",
            "youngs_mpa",
            "poisson",
            "source",
            "source_type",
            "version",
            "unit_system",
            "confirmed_by_user",
            "requires_project_review",
            "fpc_pa",
            "dagg_m",
            "units",
            "nplot",
            "incre",
            "irate",
            "erode",
            "recov",
            "itretrc",
            "pred",
            "shear_modulus_pa",
            "a",
            "b",
            "c",
            "n",
            "fc_pa",
            "t_pa",
            "eps0",
            "efmin",
            "sfmax",
            "pc_pa",
            "uc",
            "pl_pa",
            "ul",
            "d1",
            "d2",
            "k1_pa",
            "k2_pa",
            "k3_pa",
            "fs",
            "one_mpa_pa",
            "epsf",
            "b0",
            "b1",
            "t1_pa",
            "fs_star",
            "ft_star",
            "q0",
            "t2_pa",
            "ft_pa",
            "a0_pa",
            "a1",
            "a2",
            "omega",
            "a1f",
            "mt",
            "lmc",
            "nhv",
            "iortho",
            "ibulk",
            "ig",
            "ivect",
            "ifail",
            "itherm",
            "ihyper",
            "ieos",
            "lmca",
            "constants",
            "additional_constants",
            "orthotropic_axes",
            "card_lines",
        },
    )
    check_object("spec.hourglass", hourglass, {"id", "title", "ihq", "ibq", "qm", "q1", "q2", "qb", "qw"})
    check_object("spec.analysis_control", analysis_control, {"termination", "energy", "shell", "timestep"})
    for key in ["termination", "energy", "shell", "timestep"]:
        if isinstance(analysis_control.get(key), dict):
            allowed = {
                "termination": {"end_time_s", "end_cycle", "dtmin", "endeng", "endmas"},
                "energy": {"hgen", "rwen", "slnten", "rylen"},
                "shell": {"wrpang", "esort", "irnxx", "istupd", "theory", "bwc", "miter"},
                "timestep": {"dtinit_s", "tssfac", "isdo", "tslimt", "dt2ms", "lctm"},
            }[key]
            check_object(f"spec.analysis_control.{key}", analysis_control[key], allowed)
    check_object(
        "spec.database",
        database,
        {
            "format",
            "ibinary",
            "d3plot_dt_s",
            "d3thdt_dt_s",
            "nodout_dt_s",
            "fsi_dt_s",
            "glstat_dt_s",
            "matsum_dt_s",
            "ale_mat_dt_s",
            "ale_probe_dt_s",
            "d3plot_schedule",
            "d3plot_lcdt_curve_id",
            "extent_binary",
        },
    )
    if isinstance(database.get("extent_binary"), dict):
        check_object(
            "spec.database.extent_binary",
            database["extent_binary"],
            {"neiph", "neips", "maxint", "strflg", "sigflg", "epsflg", "rltflg", "engflg", "cmpflg", "ieverp", "beamip", "dcomp", "shge", "stssz", "n3thdt", "ialemat", "nintsld", "pkp_sen", "sclp", "msscl", "therm"},
        )
    for index, curve in enumerate(curves):
        check_object(f"spec.curves[{index}]", curve, {"id", "name", "points"})
    for index, component in enumerate(components):
        component_type = str(component.get("template", ""))
        allowed = {
            "id",
            "template",
            "geometry",
            "mesh",
            "material",
            "transform",
            "fixed_faces",
            "fixed_regions",
            "initial_velocity_m_per_s",
        }
        check_object(f"spec.components[{index}]", component, allowed)
        if isinstance(component.get("geometry"), dict):
            geometry_allowed = set(COMPONENT_GEOMETRY_KEYS.get(component_type, []))
            check_object(f"spec.components[{index}].geometry", component["geometry"], geometry_allowed)
        if isinstance(component.get("mesh"), dict):
            check_object(f"spec.components[{index}].mesh", component["mesh"], {"size_m"})
        if isinstance(component.get("transform"), dict):
            check_object(
                f"spec.components[{index}].transform",
                component["transform"],
                {"translate_m", "center_m", "rotate_deg", "orientation"},
            )
    for index, contact in enumerate(contacts):
        check_object(f"spec.contacts[{index}]", contact, {"type", "slave", "master", "slave_face", "friction"})
    for index, item in enumerate(sets):
        item_type = str(item.get("type", ""))
        allowed = {"type", "name"}
        if item_type == "node_set":
            allowed |= {"selector", "edge", "node_ids"}
        elif item_type == "part_set":
            allowed |= {"part_ids"}
        elif item_type == "segment_set":
            allowed |= {"selector", "face"}
        check_object(f"spec.sets[{index}]", item, allowed)
    for index, item in enumerate(boundary_conditions):
        item_type = str(item.get("type", ""))
        allowed = {"type", "target", "edge", "name"}
        if item_type == "spc_node_set":
            allowed |= {"node_ids", "dofs"}
        elif item_type == "prescribed_displacement":
            allowed |= {"dof", "value_m", "end_time_s", "curve", "curve_id"}
        elif item_type == "prescribed_velocity":
            allowed |= {"dof", "value_m_per_s", "end_time_s", "curve", "curve_id"}
        check_object(f"spec.boundary_conditions[{index}]", item, allowed)
    for index, item in enumerate(loads):
        item_type = str(item.get("type", ""))
        allowed = {"type", "target", "edge", "name", "curve", "curve_id", "end_time_s"}
        if item_type == "nodal_force":
            allowed |= {"dof", "value_n"}
        elif item_type == "gravity":
            allowed |= {"direction", "acceleration_m_per_s2"}
        elif item_type == "pressure_on_segment_set":
            allowed |= {"pressure_pa", "face", "selector"}
        elif item_type == "pressure_on_segment":
            allowed |= {"pressure_pa", "segment", "scale_factor", "arrival_time_s"}
        elif item_type == "initial_velocity":
            allowed |= {"vector_m_per_s", "vx_m_per_s", "vy_m_per_s", "vz_m_per_s"}
        elif item_type == "blast_enhanced":
            allowed |= {
                "id", "charge_type", "equivalent_mass_kg", "position_m", "mode",
                "unit", "blast_type", "targets", "output_dt_s",
            }
        check_object(f"spec.loads[{index}]", item, allowed)
    return warnings


def normalize_geometry(model_type: str, geometry: JSONDict) -> JSONDict:
    # Backward-compatible field conversion. New docs use SI names only.
    converted = dict(geometry)
    for old, new in {
        "length_mm": "length_m",
        "width_mm": "width_m",
        "height_mm": "height_m",
        "thickness_mm": "thickness_m",
        "radius_mm": "radius_m",
    }.items():
        if new not in converted and old in converted:
            converted[new] = numeric(converted[old], f"geometry.{old}") / 1000.0

    if model_type == "ale_blast_scene" and converted.get("scene_variant") == "open_concrete_tunnel":
        return converted
    defaults = default_model_spec("tmp", model_type)["geometry"]
    for key, value in defaults.items():
        converted.setdefault(key, value)
    return converted


def normalize_mesh(mesh: JSONDict) -> JSONDict:
    converted = dict(mesh)
    if "size_m" not in converted and "size_mm" in converted:
        converted["size_m"] = numeric(converted["size_mm"], "mesh.size_mm") / 1000.0
    converted.setdefault("size_m", 0.01)
    return converted


def normalize_material(material: JSONDict) -> JSONDict:
    converted = dict(material)
    if "density_kg_per_m3" not in converted and "density_g_per_mm3" in converted:
        converted["density_kg_per_m3"] = numeric(converted["density_g_per_mm3"], "material.density_g_per_mm3") * 1_000_000.0
    if "youngs_pa" not in converted and "youngs_mpa" in converted:
        converted["youngs_pa"] = numeric(converted["youngs_mpa"], "material.youngs_mpa") * 1_000_000.0
    converted.setdefault("name", "mild_steel")
    converted.setdefault("type", "elastic")
    material_type = str(converted.get("type", "elastic"))
    if material_type in {"elastic", "piecewise_linear_plasticity"}:
        return resolve_material(converted)
    validate_advanced_material(converted)
    converted.setdefault("unit_system", DEFAULT_UNIT_SYSTEM)
    converted.setdefault("version", "user-confirmed")
    converted.setdefault("source_type", "user_confirmed_custom")
    converted["requires_project_review"] = True
    return converted


def validate_model_spec(spec: ModelSpec) -> None:
    positive_geometry_keys = {
        "shell_plate": ["length_m", "width_m", "thickness_m"],
        "solid_block": ["length_m", "width_m", "height_m"],
        "shell_box": ["length_m", "width_m", "height_m", "thickness_m"],
        "cylinder_shell": ["radius_m", "length_m", "thickness_m"],
        "cylinder_solid": ["radius_m", "length_m"],
        "beam_bar": ["length_m", "width_m", "height_m"],
        "assembly_scene": [],
        "ale_blast_scene": [],
        "single_solid_element_test": ["length_m", "width_m", "height_m"],
    }[spec.model_type]
    for key in positive_geometry_keys:
        if positive_numeric(spec.geometry.get(key, 0), f"geometry.{key}") <= 0:
            raise ValueError(f"geometry.{key} must be positive")
    if spec.model_type == "ale_blast_scene":
        from .ale_blast import explosive_radius_m, validate_ale_blast_geometry

        validate_ale_blast_geometry(spec.geometry, numeric(spec.mesh.get("size_m"), "mesh.size_m"))
        if spec.geometry.get("scene_variant") == "open_concrete_tunnel":
            for key in ["wall_size_m", "plate_size_m"]:
                if positive_numeric(spec.mesh.get(key, 0), f"mesh.{key}") <= 0.0:
                    raise ValueError(f"mesh.{key} must be positive for open_concrete_tunnel")
            if spec.mesh.get("mode") != "uniform_air_mesh":
                raise ValueError("open_concrete_tunnel mesh.mode must be uniform_air_mesh")
    if positive_numeric(spec.mesh.get("size_m", 0), "mesh.size_m") <= 0:
        raise ValueError("mesh.size_m must be positive")
    if positive_numeric(spec.material.get("density_kg_per_m3", 0), "material.density_kg_per_m3") <= 0:
        raise ValueError("material.density_kg_per_m3 must be positive")
    if spec.material.get("type", "elastic") == "elastic":
        if positive_numeric(spec.material.get("youngs_pa", 0), "material.youngs_pa") <= 0:
            raise ValueError("material.youngs_pa must be positive")
        poisson = numeric(spec.material.get("poisson", 0), "material.poisson")
        if not 0.0 < poisson < 0.5:
            raise ValueError("material.poisson must be between 0 and 0.5")
    curve_ids = {int(curve["id"]) for curve in spec.curves}
    if (
        spec.material.get("type") == "concrete_damage_rel3"
        and spec.material.get("parameter_mode") == "automatic"
    ):
        lcrate = int(spec.material.get("lcrate", -1))
        if lcrate > 0 and lcrate not in curve_ids:
            raise ValueError(
                f"concrete_damage_rel3.lcrate {lcrate} references no top-level curve"
            )
    if spec.database.get("d3plot_schedule"):
        d3plot_curve_id = int(spec.database.get("d3plot_lcdt_curve_id", 990001))
        if d3plot_curve_id in curve_ids:
            raise ValueError(
                f"database.d3plot_lcdt_curve_id {d3plot_curve_id} collides with a top-level curve"
            )


SUPPORTED_EDGES = {"x_min", "x_max", "y_min", "y_max", "z_min", "z_max"}
SUPPORTED_DOFS = {"x": 1, "y": 2, "z": 3}
SUPPORTED_SPC_DOFS = {"x", "y", "z", "rx", "ry", "rz"}
SUPPORTED_CURVES = {"constant", "ramp", "table"}
SUPPORTED_SET_TYPES = {"node_set", "part_set", "segment_set"}


def validate_boundary_conditions(boundary_conditions: list[JSONDict], sets: list[JSONDict]) -> None:
    fixed_edges = [
        item.get("edge")
        for item in boundary_conditions
        if isinstance(item, dict) and item.get("type") == "fixed_edge"
    ]
    spc_sets = [
        item
        for item in boundary_conditions
        if isinstance(item, dict) and item.get("type") == "spc_node_set"
    ]
    if not fixed_edges and not spc_sets:
        raise ValueError("boundary_conditions must include at least one fixed_edge or spc_node_set")
    for item in boundary_conditions:
        if not isinstance(item, dict):
            raise ValueError("each boundary condition must be an object")
        item_type = item.get("type")
        if item_type == "fixed_edge":
            validate_node_target(item, sets, "boundary_conditions[]")
        elif item_type == "spc_node_set":
            validate_spc_node_set(item, sets)
        elif item_type == "prescribed_displacement":
            validate_node_target(item, sets, "boundary_conditions[]")
            validate_dof(item.get("dof"), "boundary_conditions[].dof")
            validate_curve_or_value(item, "value_m", "prescribed_displacement.value_m")
        elif item_type == "prescribed_velocity":
            validate_node_target(item, sets, "boundary_conditions[]")
            validate_dof(item.get("dof"), "boundary_conditions[].dof")
            validate_curve_or_value(item, "value_m_per_s", "prescribed_velocity.value_m_per_s")
        else:
            raise ValueError(f"unsupported boundary condition type: {item_type}")


def validate_loads(loads: list[JSONDict], sets: list[JSONDict], components: list[JSONDict] | None = None) -> None:
    for item in loads:
        if not isinstance(item, dict):
            raise ValueError("each load must be an object")
        item_type = item.get("type")
        if item_type == "nodal_force":
            validate_node_target(item, sets, "loads[]")
            validate_dof(item.get("dof"), "loads[].dof")
            validate_curve_or_value(item, "value_n", "nodal_force.value_n")
        elif item_type == "gravity":
            validate_dof(item.get("direction"), "loads[].direction")
            validate_curve_or_value(item, "acceleration_m_per_s2", "gravity.acceleration_m_per_s2")
        elif item_type == "pressure_on_segment_set":
            validate_segment_target(item, sets, "loads[]")
            validate_curve_or_value(item, "pressure_pa", "pressure_on_segment_set.pressure_pa")
        elif item_type == "pressure_on_segment":
            validate_direct_segment_load(item)
        elif item_type == "initial_velocity":
            validate_initial_velocity(item, sets)
        elif item_type == "blast_enhanced":
            validate_blast_enhanced(item, components or [])
        else:
            raise ValueError(f"unsupported load type: {item_type}")


def validate_blast_enhanced(item: JSONDict, components: list[JSONDict]) -> None:
    if item.get("charge_type") != "tnt":
        raise ValueError("blast_enhanced.charge_type currently only supports tnt")
    if item.get("mode") != "free_air_burst":
        raise ValueError("blast_enhanced.mode currently only supports free_air_burst")
    if positive_numeric(item.get("equivalent_mass_kg", 0), "blast_enhanced.equivalent_mass_kg") <= 0.0:
        raise ValueError("blast_enhanced.equivalent_mass_kg must be positive")
    validate_vector3(item.get("position_m"), "blast_enhanced.position_m")
    if int(item.get("unit", 0)) != 2:
        raise ValueError("blast_enhanced.unit must be 2 for SI kg-m-s-Pa")
    if int(item.get("blast_type", 0)) != 2:
        raise ValueError("blast_enhanced.blast_type must be 2 for free-air burst")
    if positive_numeric(item.get("output_dt_s", 0), "blast_enhanced.output_dt_s") <= 0.0:
        raise ValueError("blast_enhanced.output_dt_s must be positive")
    targets = item.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError("blast_enhanced.targets must be a non-empty list")
    component_map = {str(component.get("id")): component for component in components}
    seen: set[tuple[str, str]] = set()
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("blast_enhanced.targets[] must be an object")
        component_id = str(target.get("component", ""))
        surface = str(target.get("surface", ""))
        component = component_map.get(component_id)
        if component is None:
            raise ValueError(f"blast target references unknown component: {component_id}")
        definition = component_definition(str(component.get("template", "")))
        if definition.element_family != "shell":
            raise ValueError(f"blast target {component_id} must be a shell component")
        if surface not in definition.named_surfaces:
            raise ValueError(f"component {component_id} has no named surface: {surface}")
        key = (component_id, surface)
        if key in seen:
            raise ValueError(f"duplicate blast target: {component_id}.{surface}")
        seen.add(key)


def validate_named_sets(sets: list[JSONDict]) -> None:
    names: set[tuple[str, str]] = set()
    for item in sets:
        if not isinstance(item, dict):
            raise ValueError("each set definition must be an object")
        set_type = str(item.get("type", ""))
        if set_type not in SUPPORTED_SET_TYPES:
            raise ValueError(f"unsupported set type: {set_type}")
        name = validate_set_name(item.get("name"), "sets[].name")
        key = (set_type, name)
        if key in names:
            raise ValueError(f"duplicate set definition: {set_type}:{name}")
        names.add(key)
        if set_type == "node_set":
            validate_node_selector(item, "sets[]")
        elif set_type == "segment_set":
            validate_segment_selector(item, "sets[].selector")
        elif set_type == "part_set":
            validate_part_ids(item.get("part_ids"))


def validate_node_target(item: JSONDict, sets: list[JSONDict], field: str, allow_part_set: bool = False) -> None:
    target = item.get("target")
    if target is None:
        validate_edge(item.get("edge"), f"{field}.edge")
        return
    if not isinstance(target, dict):
        raise ValueError(f"{field}.target must be an object")
    target_type = str(target.get("type", ""))
    if target_type == "edge":
        validate_edge(target.get("edge"), f"{field}.target.edge")
    elif target_type == "node_set":
        name = validate_set_name(target.get("name"), f"{field}.target.name")
        if has_inline_node_selector(target):
            validate_node_selector(target, f"{field}.target")
        elif not has_named_set(sets, "node_set", name):
            raise ValueError(f"{field}.target references unknown node_set: {name}")
    elif target_type == "part_set":
        if not allow_part_set:
            raise ValueError(f"{field}.target.type part_set is only supported for initial_velocity")
        name = validate_set_name(target.get("name"), f"{field}.target.name")
        if not has_named_set(sets, "part_set", name):
            raise ValueError(f"{field}.target references unknown part_set: {name}")
    else:
        raise ValueError(f"{field}.target.type must be edge, node_set, or part_set")


def validate_spc_node_set(item: JSONDict, sets: list[JSONDict]) -> None:
    if "node_ids" in item:
        validate_node_ids(item.get("node_ids"), "boundary_conditions[].node_ids")
    else:
        validate_node_target(item, sets, "boundary_conditions[]")
    dofs = item.get("dofs")
    if not isinstance(dofs, list) or not dofs:
        raise ValueError("spc_node_set.dofs must be a non-empty list")
    for dof in dofs:
        if dof not in SUPPORTED_SPC_DOFS:
            raise ValueError("spc_node_set.dofs may only contain x, y, z, rx, ry, rz")


def validate_segment_target(item: JSONDict, sets: list[JSONDict], field: str) -> None:
    target = item.get("target")
    if target is None:
        validate_segment_selector(item, field)
        return
    if not isinstance(target, dict):
        raise ValueError(f"{field}.target must be an object")
    if target.get("type") != "segment_set":
        raise ValueError(f"{field}.target.type must be segment_set")
    name = validate_set_name(target.get("name"), f"{field}.target.name")
    if has_inline_segment_selector(target):
        validate_segment_selector(target, f"{field}.target.selector")
    elif not has_named_set(sets, "segment_set", name):
        raise ValueError(f"{field}.target references unknown segment_set: {name}")


def validate_initial_velocity(item: JSONDict, sets: list[JSONDict]) -> None:
    validate_node_target(item, sets, "loads[]", allow_part_set=True)
    vector = velocity_vector(item)
    if not any(abs(value) > 0.0 for value in vector):
        raise ValueError("initial_velocity must define at least one non-zero velocity component")


def validate_direct_segment_load(item: JSONDict) -> None:
    segment = item.get("segment")
    if not isinstance(segment, list | tuple) or len(segment) != 4:
        raise ValueError("pressure_on_segment.segment must contain four node ids")
    validate_node_ids(segment, "pressure_on_segment.segment")
    validate_curve_or_value(item, "pressure_pa", "pressure_on_segment.pressure_pa")


def validate_curve_or_value(item: JSONDict, value_field: str, label: str) -> None:
    if "curve_id" in item:
        if int(item["curve_id"]) <= 0:
            raise ValueError("curve_id must be positive")
        return
    curve = item.get("curve")
    if curve is None:
        value = numeric(item.get(value_field, 0.0), label)
        if value == 0.0:
            raise ValueError(f"{label} must be non-zero")
        if "end_time_s" in item and numeric(item["end_time_s"], "end_time_s") <= 0.0:
            raise ValueError("end_time_s must be positive")
        return
    if not isinstance(curve, dict):
        raise ValueError("curve must be an object")
    curve_type = str(curve.get("type", ""))
    if curve_type not in SUPPORTED_CURVES:
        raise ValueError(f"curve.type must be one of {', '.join(sorted(SUPPORTED_CURVES))}")
    if curve_type == "constant":
        value = numeric(curve.get("value", item.get(value_field, 0.0)), "curve.value")
        if value == 0.0:
            raise ValueError("curve.value must be non-zero")
        if numeric(curve.get("end_time_s", item.get("end_time_s", 1.0)), "curve.end_time_s") <= 0.0:
            raise ValueError("curve.end_time_s must be positive")
    elif curve_type == "ramp":
        start_time = numeric(curve.get("start_time_s", 0.0), "curve.start_time_s")
        end_time = numeric(curve.get("end_time_s", item.get("end_time_s", 1.0)), "curve.end_time_s")
        start_value = numeric(curve.get("start_value", 0.0), "curve.start_value")
        end_value = numeric(curve.get("end_value", item.get(value_field, 0.0)), "curve.end_value")
        if end_time <= start_time:
            raise ValueError("curve.end_time_s must be greater than curve.start_time_s")
        if start_value == 0.0 and end_value == 0.0:
            raise ValueError("curve ramp must include a non-zero value")
    elif curve_type == "table":
        points = curve.get("points")
        if not isinstance(points, list) or len(points) < 2:
            raise ValueError("curve.points must contain at least two points")
        previous_time: float | None = None
        nonzero = False
        for point in points:
            if not isinstance(point, list | tuple) or len(point) != 2:
                raise ValueError("each curve point must be [time_s, value]")
            time = numeric(point[0], "curve point time")
            value = numeric(point[1], "curve point value")
            if previous_time is not None and time <= previous_time:
                raise ValueError("curve point times must be strictly increasing")
            previous_time = time
            nonzero = nonzero or value != 0.0
        if not nonzero:
            raise ValueError("curve table must include at least one non-zero value")


def validate_edge(value: object, field: str) -> None:
    if value not in SUPPORTED_EDGES:
        raise ValueError(f"{field} must be one of {', '.join(sorted(SUPPORTED_EDGES))}")


def validate_dof(value: object, field: str) -> None:
    if value not in SUPPORTED_DOFS:
        raise ValueError(f"{field} must be one of x, y, z")


def validate_set_name(value: object, field: str) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError(f"{field} must be a non-empty string")
    if not all(char.isalnum() or char in {"_", "-"} for char in name):
        raise ValueError(f"{field} may only contain letters, numbers, '_' and '-'")
    return name


def validate_node_selector(item: JSONDict, field: str) -> None:
    if "node_ids" in item:
        validate_node_ids(item.get("node_ids"), f"{field}.node_ids")
        return
    nested_selector = item.get("selector")
    selector = nested_selector if isinstance(nested_selector, dict) else item
    selector_type = str(selector.get("type", "edge")) if isinstance(nested_selector, dict) else "edge"
    if selector_type == "edge":
        validate_edge(selector.get("edge"), f"{field}.selector.edge")
        return
    if selector_type == "face_corners":
        validate_edge(selector.get("face"), f"{field}.selector.face")
        return
    raise ValueError(f"{field}.selector.type must be edge or face_corners")


def validate_node_ids(value: object, field: str) -> None:
    if not isinstance(value, list | tuple) or not value:
        raise ValueError(f"{field} must be a non-empty list")
    seen: set[int] = set()
    for node_id_value in value:
        node_id_int = int(node_id_value)
        if node_id_int <= 0:
            raise ValueError(f"{field} values must be positive node ids")
        if node_id_int in seen:
            raise ValueError(f"{field} must not contain duplicate node ids")
        seen.add(node_id_int)


def validate_segment_selector(item: JSONDict, field: str) -> None:
    selector = item.get("selector") if isinstance(item.get("selector"), dict) else item
    selector_type = selector.get("type", "face") if isinstance(selector, dict) else "face"
    if selector_type == "all_shell":
        return
    if selector_type != "face":
        raise ValueError(f"{field}.type must be face or all_shell")
    face = selector.get("face") if isinstance(selector, dict) else item.get("face")
    validate_edge(face, f"{field}.face")


def validate_part_ids(value: object) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError("part_set.part_ids must be a non-empty list")
    for part_id in value:
        if int(part_id) != 1:
            raise ValueError("part_set.part_ids currently only supports generated part id 1")


SUPPORTED_COMPONENT_TEMPLATES = set(component_template_names())
COMPONENT_GEOMETRY_KEYS = {
    name: list(component_definition(name).geometry_fields) for name in component_template_names()
}


def normalize_components(components: list[JSONDict], default_material: JSONDict) -> list[JSONDict]:
    normalized: list[JSONDict] = []
    for component in components:
        if not isinstance(component, dict):
            raise ValueError("each component must be an object")
        item = dict(component)
        item["geometry"] = dict(item.get("geometry") or {})
        item["mesh"] = dict(item.get("mesh") or {})
        item["transform"] = dict(item.get("transform") or {})
        item.setdefault("material", default_material)
        if not isinstance(item["material"], dict):
            raise ValueError("component.material must be an object")
        item["material"] = normalize_material(item["material"])
        normalized.append(item)
    return normalized


def validate_components(components: list[JSONDict]) -> None:
    if len(components) < 1:
        raise ValueError("assembly_scene requires at least one component")
    ids: set[str] = set()
    for component in components:
        component_id = validate_set_name(component.get("id"), "components[].id")
        if component_id in ids:
            raise ValueError(f"duplicate component id: {component_id}")
        ids.add(component_id)
        template = str(component.get("template", ""))
        if template not in SUPPORTED_COMPONENT_TEMPLATES:
            raise ValueError(f"unsupported component template: {template}")
        geometry = component.get("geometry")
        if not isinstance(geometry, dict):
            raise ValueError("component.geometry must be an object")
        for key in COMPONENT_GEOMETRY_KEYS[template]:
            if positive_numeric(geometry.get(key, 0), f"component {component_id} geometry.{key}") <= 0:
                raise ValueError(f"component {component_id} geometry.{key} must be positive")
        mesh = component.get("mesh")
        if not isinstance(mesh, dict):
            raise ValueError("component.mesh must be an object")
        if positive_numeric(mesh.get("size_m", 0), f"component {component_id} mesh.size_m") <= 0:
            raise ValueError(f"component {component_id} mesh.size_m must be positive")
        transform = component.get("transform")
        if not isinstance(transform, dict):
            raise ValueError("component.transform must be an object")
        validate_vector3(transform.get("translate_m", [0.0, 0.0, 0.0]), f"component {component_id} transform.translate_m")
        if "center_m" in transform:
            validate_vector3(transform["center_m"], f"component {component_id} transform.center_m")
        if "rotate_deg" in transform:
            validate_vector3(transform["rotate_deg"], f"component {component_id} transform.rotate_deg")
        if "orientation" in transform and transform["orientation"] not in {"vertical_z", "vertical_x", "vertical_y"}:
            raise ValueError("component.transform.orientation must be vertical_z, vertical_x, or vertical_y")
        fixed_faces = component.get("fixed_faces", [])
        if fixed_faces:
            if not isinstance(fixed_faces, list):
                raise ValueError("component.fixed_faces must be a list")
            for face in fixed_faces:
                validate_edge(face, "component.fixed_faces[]")
        fixed_regions = component.get("fixed_regions", [])
        if fixed_regions:
            if not isinstance(fixed_regions, list):
                raise ValueError("component.fixed_regions must be a list")
            definition = component_definition(str(component["template"]))
            allowed_regions = {
                *definition.named_edges,
                *definition.named_surfaces,
                "x_min",
                "x_max",
                "y_min",
                "y_max",
                "z_min",
                "z_max",
            }
            for region in fixed_regions:
                if region not in allowed_regions:
                    raise ValueError(f"component.fixed_regions[] unsupported region: {region}")
        if "initial_velocity_m_per_s" in component:
            vector = validate_vector3(component["initial_velocity_m_per_s"], f"component {component_id} initial_velocity_m_per_s")
            if not any(abs(value) > 0.0 for value in vector):
                raise ValueError(f"component {component_id} initial_velocity_m_per_s must be non-zero")


def validate_contacts(contacts: list[JSONDict], component_ids: set[str]) -> None:
    for contact in contacts:
        if not isinstance(contact, dict):
            raise ValueError("each contact must be an object")
        contact_type = str(contact.get("type", ""))
        if contact_type not in {"automatic_surface_to_surface", "automatic_nodes_to_surface"}:
            raise ValueError("contacts[].type currently only supports automatic_surface_to_surface or automatic_nodes_to_surface")
        slave = str(contact.get("slave", "")).strip()
        master = str(contact.get("master", "")).strip()
        if slave not in component_ids:
            raise ValueError(f"contact slave references unknown component: {slave}")
        if master not in component_ids:
            raise ValueError(f"contact master references unknown component: {master}")
        if slave == master:
            raise ValueError("contact slave and master must be different components")
        if "slave_face" in contact:
            validate_edge(contact["slave_face"], "contact.slave_face")
        friction = numeric(contact.get("friction", 0.0), "contact.friction")
        if not 0.0 <= friction <= 2.0:
            raise ValueError("contact.friction must be between 0 and 2")


def validate_vector3(value: object, field: str) -> tuple[float, float, float]:
    if not isinstance(value, list | tuple) or len(value) != 3:
        raise ValueError(f"{field} must be [x, y, z]")
    return (numeric(value[0], f"{field}[0]"), numeric(value[1], f"{field}[1]"), numeric(value[2], f"{field}[2]"))


def has_named_set(sets: list[JSONDict], set_type: str, name: str) -> bool:
    return any(isinstance(item, dict) and item.get("type") == set_type and item.get("name") == name for item in sets)


def has_inline_node_selector(target: JSONDict) -> bool:
    return "edge" in target or "node_ids" in target or isinstance(target.get("selector"), dict)


def has_inline_segment_selector(target: JSONDict) -> bool:
    return "face" in target or isinstance(target.get("selector"), dict)


def edge_from_selector(item: JSONDict) -> object:
    selector = item.get("selector")
    if isinstance(selector, dict):
        return selector.get("edge")
    return item.get("edge")


def velocity_vector(item: JSONDict) -> tuple[float, float, float]:
    if "vector_m_per_s" in item:
        vector = item["vector_m_per_s"]
        if not isinstance(vector, list | tuple) or len(vector) != 3:
            raise ValueError("initial_velocity.vector_m_per_s must be [vx, vy, vz]")
        return (
            numeric(vector[0], "initial_velocity.vector_m_per_s[0]"),
            numeric(vector[1], "initial_velocity.vector_m_per_s[1]"),
            numeric(vector[2], "initial_velocity.vector_m_per_s[2]"),
        )
    return (
        numeric(item.get("vx_m_per_s", 0.0), "initial_velocity.vx_m_per_s"),
        numeric(item.get("vy_m_per_s", 0.0), "initial_velocity.vy_m_per_s"),
        numeric(item.get("vz_m_per_s", 0.0), "initial_velocity.vz_m_per_s"),
    )


def validate_curves(curves: list[JSONDict]) -> None:
    ids: set[int] = set()
    for curve in curves:
        if not isinstance(curve, dict):
            raise ValueError("each curve definition must be an object")
        curve_id = int(curve.get("id", 0))
        if curve_id <= 0:
            raise ValueError("curves[].id must be positive")
        if curve_id in ids:
            raise ValueError(f"duplicate curve id: {curve_id}")
        ids.add(curve_id)
        points = curve.get("points")
        if not isinstance(points, list) or len(points) < 2:
            raise ValueError("curves[].points must contain at least two points")
        previous_time: float | None = None
        for point in points:
            if not isinstance(point, list | tuple) or len(point) != 2:
                raise ValueError("each curves[].points item must be [x, y]")
            time = numeric(point[0], "curves point x")
            numeric(point[1], "curves point y")
            if previous_time is not None and time <= previous_time:
                raise ValueError("curve point x values must be strictly increasing")
            previous_time = time


def validate_curve_references(
    curves: list[JSONDict],
    boundary_conditions: list[JSONDict],
    loads: list[JSONDict],
) -> None:
    defined_ids = {int(curve["id"]) for curve in curves}
    for item in [*boundary_conditions, *loads]:
        if isinstance(item, dict) and "curve_id" in item and int(item["curve_id"]) not in defined_ids:
            raise ValueError(f"curve_id {int(item['curve_id'])} references no top-level curve")


def validate_hourglass(hourglass: JSONDict) -> None:
    if not hourglass:
        return
    if int(hourglass.get("id", 0)) <= 0:
        raise ValueError("hourglass.id must be positive")
    for key in ["ihq", "ibq"]:
        if key in hourglass and int(hourglass[key]) < 0:
            raise ValueError(f"hourglass.{key} must be non-negative")
    for key in ["qm", "q1", "q2", "qb", "qw"]:
        if key in hourglass:
            numeric(hourglass[key], f"hourglass.{key}")


def validate_analysis_control(control: JSONDict) -> None:
    termination = control.get("termination", {})
    if termination and not isinstance(termination, dict):
        raise ValueError("analysis_control.termination must be an object")
    if isinstance(termination, dict) and "end_time_s" in termination:
        if numeric(termination["end_time_s"], "analysis_control.termination.end_time_s") <= 0.0:
            raise ValueError("analysis_control.termination.end_time_s must be positive")
    for key in ["energy", "shell", "timestep"]:
        if key in control and not isinstance(control[key], dict):
            raise ValueError(f"analysis_control.{key} must be an object")


def validate_database(database: JSONDict) -> None:
    if "format" in database:
        format_value = int(database["format"])
        if format_value != 0:
            raise ValueError("database.format currently supports only LS-DYNA IFORM=0")
    if "ibinary" in database:
        ibinary = int(database["ibinary"])
        if ibinary not in {0, 1}:
            raise ValueError("database.ibinary must be 0 or 1")
    for key in [
        "d3plot_dt_s",
        "d3thdt_dt_s",
        "nodout_dt_s",
        "fsi_dt_s",
        "glstat_dt_s",
        "matsum_dt_s",
        "ale_mat_dt_s",
        "ale_probe_dt_s",
    ]:
        if key in database and numeric(database[key], f"database.{key}") <= 0.0:
            raise ValueError(f"database.{key} must be positive")
    if "extent_binary" in database and not isinstance(database["extent_binary"], dict):
        raise ValueError("database.extent_binary must be an object")
    schedule = database.get("d3plot_schedule")
    if schedule is not None:
        if not isinstance(schedule, list) or not schedule:
            raise ValueError("database.d3plot_schedule must be a non-empty list")
        previous_end = 0.0
        for index, stage in enumerate(schedule):
            if not isinstance(stage, dict) or set(stage) != {"until_time_s", "dt_s"}:
                raise ValueError(
                    f"database.d3plot_schedule[{index}] must contain only until_time_s and dt_s"
                )
            end_time = numeric(stage["until_time_s"], f"database.d3plot_schedule[{index}].until_time_s")
            dt = numeric(stage["dt_s"], f"database.d3plot_schedule[{index}].dt_s")
            if end_time <= previous_end or dt <= 0.0:
                raise ValueError("database.d3plot_schedule stages must have increasing positive times and dt_s")
            previous_end = end_time
    if "d3plot_lcdt_curve_id" in database and int(database["d3plot_lcdt_curve_id"]) <= 0:
        raise ValueError("database.d3plot_lcdt_curve_id must be positive")


def validate_advanced_material(material: JSONDict) -> None:
    material_type = str(material.get("type", ""))
    if material_type not in SUPPORTED_MATERIAL_TYPES:
        raise ValueError(f"unsupported material.type: {material_type}")
    if material.get("unit_system", DEFAULT_UNIT_SYSTEM) != DEFAULT_UNIT_SYSTEM:
        raise ValueError(f"material.unit_system must be '{DEFAULT_UNIT_SYSTEM}'")
    if material.get("confirmed_by_user") is not True:
        raise ValueError("advanced concrete/user material cards require confirmed_by_user=true")
    if not str(material.get("source", "")).strip():
        raise ValueError("advanced concrete/user material cards require material.source")
    if positive_numeric(material.get("density_kg_per_m3", 0), "material.density_kg_per_m3") <= 0:
        raise ValueError("material.density_kg_per_m3 must be positive")
    if material_type == "cscm_concrete":
        if positive_numeric(material.get("fpc_pa", 0), "cscm_concrete.fpc_pa") <= 0:
            raise ValueError("cscm_concrete.fpc_pa must be positive")
    elif material_type == "johnson_holmquist_concrete":
        for key in ["shear_modulus_pa", "a", "b", "n", "fc_pa"]:
            if positive_numeric(material.get(key, 0), f"johnson_holmquist_concrete.{key}") <= 0:
                raise ValueError(f"johnson_holmquist_concrete.{key} must be positive")
    elif material_type == "rht":
        for key in ["shear_modulus_pa", "fc_pa"]:
            if positive_numeric(material.get(key, 0), f"rht.{key}") <= 0:
                raise ValueError(f"rht.{key} must be positive")
    elif material_type == "concrete_damage_rel3":
        poisson = numeric(material.get("poisson", 0), "concrete_damage_rel3.poisson")
        if not 0.0 < poisson < 0.5:
            raise ValueError("concrete_damage_rel3.poisson must be between 0 and 0.5")
        parameter_mode = str(material.get("parameter_mode", "explicit"))
        if parameter_mode not in {"automatic", "explicit"}:
            raise ValueError("concrete_damage_rel3.parameter_mode must be automatic or explicit")
        if parameter_mode == "automatic":
            if positive_numeric(material.get("fpc_pa", 0), "concrete_damage_rel3.fpc_pa") <= 0:
                raise ValueError("concrete_damage_rel3.fpc_pa must be positive")
            manual_fields = {"ft_pa", "a0_pa", "a1", "a2", "b1", "omega", "a1f"}
            if manual_fields.intersection(material):
                raise ValueError("concrete_damage_rel3 automatic mode cannot mix manual strength-surface parameters")
            for key, default in (
                ("rsize_in_per_user_length", 39.37),
                ("ucf_psi_per_user_stress", 1.4503773773e-4),
            ):
                if positive_numeric(material.get(key, default), f"concrete_damage_rel3.{key}") <= 0:
                    raise ValueError(f"concrete_damage_rel3.{key} must be positive")
            lcrate = int(material.get("lcrate", -1))
            if lcrate == 0 or lcrate < -1:
                raise ValueError("concrete_damage_rel3.lcrate must be -1 or a positive curve id")
    elif material_type == "user_defined_material_models":
        title = str(material.get("title", "")).strip()
        if title and (title.startswith("*") or len(title) > 80):
            raise ValueError("user_defined_material_models.title must not be a keyword card and must be <= 80 characters")
        if int(material.get("mt", 0)) == 0:
            raise ValueError("user_defined_material_models.mt must be non-zero")
        for key in ["lmc", "nhv"]:
            if int(material.get(key, 0)) < 0:
                raise ValueError(f"user_defined_material_models.{key} must be non-negative")
        if int(material.get("nhv", 0)) > 200:
            raise ValueError("user_defined_material_models.nhv must be <= 200")
        iortho = int(material.get("iortho", 0))
        if iortho not in {0, 1, 2, 3}:
            raise ValueError("user_defined_material_models.iortho must be 0, 1, 2, or 3")
        lmc_limit = 40 if iortho in {1, 3} else 48
        if int(material.get("lmc", 0)) > lmc_limit:
            raise ValueError(f"user_defined_material_models.lmc must be <= {lmc_limit}; use lmca/additional_constants for more parameters")
        for key in ["ibulk", "ig", "ivect", "itherm", "ieos", "lmca"]:
            if key in material and int(material[key]) < 0:
                raise ValueError(f"user_defined_material_models.{key} must be non-negative")
        if "ifail" in material:
            int(material["ifail"])
        if "ihyper" in material and int(material["ihyper"]) not in {-1, 0, 1, 3}:
            raise ValueError("user_defined_material_models.ihyper must be -1, 0, 1, or 3")
        constants = material.get("constants", [])
        if constants is None:
            constants = []
            material["constants"] = constants
        if not isinstance(constants, list):
            raise ValueError("user_defined_material_models.constants must be a list")
        if len(constants) > int(material.get("lmc", 0)):
            raise ValueError("user_defined_material_models.constants length must not exceed lmc")
        for index, value in enumerate(constants):
            if value is None or value == "":
                continue
            numeric(value, f"user_defined_material_models.constants[{index}]")
        additional_constants = material.get("additional_constants", [])
        if additional_constants is None:
            additional_constants = []
            material["additional_constants"] = additional_constants
        if not isinstance(additional_constants, list):
            raise ValueError("user_defined_material_models.additional_constants must be a list")
        if int(material.get("lmca", len(additional_constants))) < len(additional_constants):
            raise ValueError("user_defined_material_models.additional_constants length must not exceed lmca")
        material.setdefault("lmca", len(additional_constants))
        for index, value in enumerate(additional_constants):
            if value is None or value == "":
                continue
            numeric(value, f"user_defined_material_models.additional_constants[{index}]")
        axes = material.get("orthotropic_axes", {})
        if axes is None:
            axes = {}
            material["orthotropic_axes"] = axes
        if axes and not isinstance(axes, dict):
            raise ValueError("user_defined_material_models.orthotropic_axes must be an object")
        if iortho in {1, 3}:
            validate_user_material_orthotropic_axes(axes)
    elif material_type == "user_defined_material":
        lines = material.get("card_lines")
        if not isinstance(lines, list) or not lines:
            raise ValueError("user_defined_material.card_lines must be a non-empty list")
        validate_user_material_card_lines(lines)


FORBIDDEN_USER_MATERIAL_CARD_PREFIXES = {
    "*KEYWORD",
    "*END",
    "*INCLUDE",
    "*CONTACT_",
    "*NODE",
    "*ELEMENT_",
    "*PART",
    "*SECTION_",
    "*SET_",
    "*LOAD_",
    "*BOUNDARY_",
    "*INITIAL_",
    "*CONTROL_",
    "*DATABASE_",
}


def validate_user_material_card_lines(lines: list[object]) -> None:
    saw_material_card = False
    for index, value in enumerate(lines):
        line = str(value).strip()
        if not line:
            continue
        if len(line) > 240:
            raise ValueError(f"user_defined_material.card_lines[{index}] is too long")
        if not line.startswith("*"):
            continue
        upper = line.upper().split(",", 1)[0].split()[0]
        if any(upper.startswith(prefix) for prefix in FORBIDDEN_USER_MATERIAL_CARD_PREFIXES):
            raise ValueError(f"user_defined_material.card_lines[{index}] contains forbidden keyword card: {upper}")
        if not upper.startswith("*MAT_") and not upper.startswith("*DEFINE_CURVE"):
            raise ValueError(f"user_defined_material.card_lines[{index}] must be a material card or material curve only")
        saw_material_card = saw_material_card or upper.startswith("*MAT_")
    if not saw_material_card:
        raise ValueError("user_defined_material.card_lines must include a *MAT_ card")


def validate_user_material_orthotropic_axes(axes: JSONDict) -> None:
    if not isinstance(axes, dict):
        raise ValueError("user_defined_material_models.orthotropic_axes must be an object")
    allowed = {"aopt", "macf", "xp", "yp", "zp", "a1", "a2", "a3", "v1", "v2", "v3", "d1", "d2", "d3", "beta", "ievts"}
    for key in axes:
        if key not in allowed:
            raise ValueError(f"user_defined_material_models.orthotropic_axes.{key} is not supported")
    for key in ["aopt", "xp", "yp", "zp", "a1", "a2", "a3", "v1", "v2", "v3", "d1", "d2", "d3", "beta"]:
        if key in axes:
            numeric(axes[key], f"user_defined_material_models.orthotropic_axes.{key}")
    for key in ["macf", "ievts"]:
        if key in axes and int(axes[key]) < 0:
            raise ValueError(f"user_defined_material_models.orthotropic_axes.{key} must be non-negative")


def numeric(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def positive_numeric(value: object, field: str) -> float:
    number = numeric(value, field)
    if number <= 0.0:
        raise ValueError(f"{field} must be positive")
    return number
