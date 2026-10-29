from __future__ import annotations

from dataclasses import asdict
from copy import deepcopy

from .component_library import component_catalog, component_definition, component_template_names
from .blast_analysis import blast_sensitivity_report
from .city_street_blast import (
    build_city_street_blast_keyword,
    default_city_street_blast_spec,
)
from .ale_blast import (
    TUNNEL_AIR_MESH_OPTIONS_M,
    TUNNEL_PLATE_MATERIAL_NAMES,
    default_ale_blast_spec,
    default_tunnel_blast_spec,
    phase14_mesh_sensitivity_report,
)
from .config import JSONDict
from .dyna_keyword import build_keyword
from .paths import find_project_dir
from .physics_actions import compile_physics_actions, physics_action_catalog
from .phase15 import (
    DEFAULT_PHASE15_COUPLING_MODE,
    PHASE15_COUPLING_MODES,
    TNT_CONSISTENCY_MODES,
    build_axisymmetric_grid,
    compile_phase15_a1_mesh_plan,
    default_phase15_a1_inputs,
    resolve_phase15_coupling_mode,
    resolve_phase15_fsi_overlap_layers,
    resolve_tnt_consistency,
    summarize_phase15_a1_mesh_plan,
)
from .phase15_keyword import (
    build_phase15_a1_keyword,
    default_phase15_output,
    phase15_sensitivity_matrix,
)
from .phase15_materials import default_phase15_materials
from .preflight import preflight_model_spec
from .project_store import write_compiled_keyword_project, write_model_project
from .scene_prompts import resolve_scene_prompt
from .schema import default_model_spec, parse_model_spec
from .tool_helpers import automation_timeout, bool_arg
from .tool_lsprepost import tool_export_preview_gif, tool_export_preview_images, tool_validate_lsprepost_import


MAX_ASSEMBLY_COMPONENTS = 32


def assemble_components_input_schema() -> JSONDict:
    component_schema: JSONDict = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "template": {"type": "string", "enum": list(component_template_names())},
            "geometry": {"type": "object", "additionalProperties": True},
            "mesh": {
                "type": "object",
                "properties": {"size_m": {"type": "number"}},
                "required": ["size_m"],
                "additionalProperties": False,
            },
            "material": {"type": "object", "additionalProperties": True},
            "transform": {
                "type": "object",
                "properties": {
                    "translate_m": {"type": "array", "items": {"type": "number"}},
                    "center_m": {"type": "array", "items": {"type": "number"}},
                    "rotate_deg": {"type": "array", "items": {"type": "number"}},
                    "orientation": {
                        "type": "string",
                        "enum": ["vertical_z", "vertical_x", "vertical_y"],
                    },
                },
                "additionalProperties": False,
            },
            "fixed_faces": {"type": "array", "items": {"type": "string"}},
            "fixed_regions": {"type": "array", "items": {"type": "string"}},
            "initial_velocity_m_per_s": {"type": "array", "items": {"type": "number"}},
        },
        "required": ["id", "template", "geometry", "mesh"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "project_name": {"type": "string", "default": "assembled_model"},
            "components": {"type": "array", "items": component_schema},
            "actions": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "contacts": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "sets": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "boundary_conditions": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "loads": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "curves": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "analysis_control": {"type": "object", "additionalProperties": True},
            "database": {"type": "object", "additionalProperties": True},
            "dry_run": {"type": "boolean", "default": False},
            "if_exists": {
                "type": "string",
                "enum": ["error", "overwrite", "archive_then_write", "versioned"],
                "default": "error",
            },
        },
        "required": ["components"],
        "additionalProperties": False,
    }


def tool_generate_model(args: JSONDict) -> JSONDict:
    raw = args.get("spec") or default_model_spec()
    if not isinstance(raw, dict):
        raise ValueError("spec must be an object")
    return write_model_project(parse_model_spec(raw), if_exists=str(args.get("if_exists", "error")))


def ale_blast_demo_input_schema() -> JSONDict:
    return {
        "type": "object",
        "properties": {
            "project_name": {"type": "string", "default": "phase14_mmale_blast_plate"},
            "mesh_size_m": {"type": "number", "default": 0.0125},
            "domain_min_m": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "default": [-0.3, -0.3, -0.05],
            },
            "domain_max_m": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "default": [0.3, 0.3, 0.35],
            },
            "explosive_center_m": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "default": [0.0, 0.0, 0.2],
            },
            "explosive_mass_kg": {"type": "number", "default": 0.1},
            "plate_length_m": {"type": "number", "default": 0.4},
            "plate_width_m": {"type": "number", "default": 0.4},
            "plate_thickness_m": {"type": "number", "default": 0.006},
            "plate_z_m": {"type": "number", "default": 0.0},
            "plate_material_name": {
                "type": "string",
                "default": "mild_steel_mat24_demo",
            },
            "end_time_s": {"type": "number", "default": 0.002},
            "d3plot_dt_s": {"type": "number", "default": 0.00005},
            "fsi_dt_s": {"type": "number", "default": 0.00001},
            "dry_run": {"type": "boolean", "default": False},
            "if_exists": {
                "type": "string",
                "enum": ["error", "overwrite", "archive_then_write", "versioned"],
                "default": "error",
            },
        },
        "additionalProperties": False,
    }


def city_street_blast_input_schema() -> JSONDict:
    return {
        "type": "object",
        "properties": {
            "project_name": {"type": "string", "default": "city_street_blast"},
            "tnt_mass_kg": {"type": "number", "minimum": 10.0, "maximum": 1000.0, "default": 250.0},
            "tnt_diameter_m": {"type": "number", "minimum": 0.3, "maximum": 1.5, "default": 0.6},
            "near_mesh_size_m": {
                "type": "number",
                "enum": [0.1, 0.15, 0.2],
                "default": 0.2,
                "description": "ALE cell size around the entity TNT cylinder.",
            },
            "end_time_s": {"type": "number", "minimum": 0.005, "maximum": 0.1, "default": 0.04},
            "dry_run": {"type": "boolean", "default": False},
            "if_exists": {
                "type": "string",
                "enum": ["error", "overwrite", "archive_then_write", "versioned"],
                "default": "error",
            },
        },
        "additionalProperties": False,
    }


def phase15_a1_input_schema() -> JSONDict:
    return {
        "type": "object",
        "properties": {
            "tnt_mass_kg": {"type": "number", "minimum": 5.0, "maximum": 8.0, "default": 6.4},
            "tnt_diameter_m": {"type": "number", "minimum": 0.08, "maximum": 0.12, "default": 0.098},
            "tnt_length_m": {"type": "number", "minimum": 0.45, "maximum": 0.65, "default": 0.55},
            "tnt_density_kg_per_m3": {
                "type": "number",
                "minimum": 1550.0,
                "maximum": 1650.0,
                "default": 1630.0,
            },
            "consistency_mode": {
                "type": "string",
                "enum": ["needs_confirmation", *TNT_CONSISTENCY_MODES],
                "default": "needs_confirmation",
                "description": "How to resolve the source conflict between TNT mass, dimensions, and density.",
            },
            "target_radius_m": {"type": "number", "minimum": 0.8, "maximum": 1.3, "default": 1.05},
            "target_height_m": {"type": "number", "minimum": 1.0, "maximum": 1.8, "default": 1.4},
            "mesh_size_m": {
                "type": "number",
                "enum": [0.004, 0.006, 0.008, 0.01],
                "default": 0.006,
            },
            "coupling_mode": {
                "type": "string",
                "enum": list(PHASE15_COUPLING_MODES),
                "default": DEFAULT_PHASE15_COUPLING_MODE,
                "description": (
                    "immersed_clis is the controlled default; "
                    "conforming_air_gap is the zero-overlap air-gap workflow; "
                    "conforming_shared_nodes is experimental and not solver-qualified"
                ),
            },
            "borehole_radius_m": {
                "type": "number",
                "minimum": 0.05,
                "maximum": 0.25,
                "default": 0.073,
            },
            "bottom_air_gap_m": {
                "type": "number",
                "minimum": 0.006,
                "maximum": 0.2,
                "default": 0.024,
            },
            "fsi_overlap_layers": {
                "type": "integer",
                "enum": [1, 2, 3],
                "default": 2,
                "description": (
                    "Number of ALE cells extending across the Lagrange FSI surface. "
                    "This is a computational overlap, not physical air thickness."
                ),
            },
        },
        "additionalProperties": False,
    }


def phase15_a1_generate_input_schema() -> JSONDict:
    schema = deepcopy(phase15_a1_input_schema())
    properties = schema["properties"]
    properties.update(
        {
            "project_name": {"type": "string", "default": "phase15_a1_kc_axisymmetric_blast"},
            "steel_thickness_m": {"type": "number", "minimum": 0.006, "maximum": 0.02, "default": 0.01},
            "concrete_fpc_pa": {"type": "number", "minimum": 1.2e8, "maximum": 1.6e8, "default": 1.335e8},
            "concrete_density_kg_per_m3": {"type": "number", "minimum": 2300, "maximum": 2600, "default": 2480},
            "concrete_poisson": {"type": "number", "minimum": 0.1, "maximum": 0.3, "default": 0.2},
            "steel_density_kg_per_m3": {"type": "number", "minimum": 7750, "maximum": 8050, "default": 7850},
            "steel_youngs_pa": {"type": "number", "minimum": 1.95e11, "maximum": 2.1e11, "default": 2.1e11},
            "steel_poisson": {"type": "number", "minimum": 0.27, "maximum": 0.3, "default": 0.3},
            "steel_yield_strength_pa": {"type": "number", "minimum": 2.0e8, "maximum": 3.55e8, "default": 2.1e8},
            "steel_tangent_modulus_pa": {"type": "number", "minimum": 1.0e8, "maximum": 5.0e9, "default": 1.0e9},
            "tnt_detonation_velocity_m_per_s": {"type": "number", "minimum": 6800, "maximum": 7000, "default": 6930},
            "tnt_cj_pressure_pa": {"type": "number", "minimum": 1.9e10, "maximum": 2.2e10, "default": 2.1e10},
            "tnt_initial_energy_density_j_per_m3": {"type": "number", "minimum": 6.0e9, "maximum": 7.5e9, "default": 7.0e9},
            "erosion_mode": {
                "type": "string",
                "enum": ["off", "delayed", "standard_observation", "early_sensitivity", "custom"],
                "default": "off",
            },
            "erosion_maximum_principal_strain": {"type": "number", "minimum": 0.02, "maximum": 0.15},
            "erosion_confirmed_by_user": {"type": "boolean", "default": False},
            "end_time_s": {"type": "number", "minimum": 0.0002, "maximum": 0.02, "default": 0.0002},
            "early_output_dt_s": {"type": "number", "minimum": 1.0e-6, "maximum": 2.0e-5, "default": 2.0e-6},
            "late_output_dt_s": {"type": "number", "minimum": 2.0e-6, "maximum": 1.0e-4, "default": 5.0e-6},
            "history_output_dt_s": {"type": "number", "minimum": 1.0e-6, "maximum": 2.0e-5, "default": 2.0e-6},
            "if_exists": {
                "type": "string",
                "enum": ["error", "overwrite", "archive_then_write", "versioned"],
                "default": "error",
            },
            "dry_run": {"type": "boolean", "default": False},
        }
    )
    return schema


def tool_prepare_phase15_a1(args: JSONDict) -> JSONDict:
    inputs = default_phase15_a1_inputs()
    scalar_fields = {
        "tnt_mass_kg",
        "tnt_length_m",
        "tnt_density_kg_per_m3",
        "consistency_mode",
        "target_radius_m",
        "target_height_m",
        "mesh_size_m",
        "coupling_mode",
        "fsi_overlap_layers",
        "borehole_radius_m",
        "bottom_air_gap_m",
    }
    for field in scalar_fields:
        if field in args:
            inputs[field] = args[field]
    if "tnt_diameter_m" in args:
        inputs["tnt_radius_m"] = float(args["tnt_diameter_m"]) / 2.0

    coupling_mode = resolve_phase15_coupling_mode(inputs)
    if "fsi_overlap_layers" in args and coupling_mode != "immersed_clis":
        raise ValueError("fsi_overlap_layers is only valid for immersed_clis")
    if coupling_mode == "immersed_clis":
        resolve_phase15_fsi_overlap_layers(inputs)
    consistency = resolve_tnt_consistency(inputs)
    target_grid = build_axisymmetric_grid(
        radius_m=float(inputs["target_radius_m"]),
        height_m=float(inputs["target_height_m"]),
        mesh_size_m=float(inputs["mesh_size_m"]),
    )
    needs_confirmation = bool(consistency["needs_confirmation"])
    region_mesh = None
    if not needs_confirmation:
        region_mesh = summarize_phase15_a1_mesh_plan(
            compile_phase15_a1_mesh_plan(inputs)
        )
    mesh_quality_ok = bool(
        isinstance(region_mesh, dict) and region_mesh.get("quality_issue_count") == 0
    )
    return {
        "ok": not needs_confirmation and mesh_quality_ok,
        "status": "needs_confirmation" if needs_confirmation else "prepared",
        "needs_confirmation": needs_confirmation,
        "generation_available": not needs_confirmation and mesh_quality_ok,
        "ready_for_axisymmetric_compiler": not needs_confirmation and mesh_quality_ok,
        "reason_generation_is_disabled": (
            "Resolve the TNT source conflict before generating"
            if needs_confirmation
            else None
        ),
        "solver_permission": "explicit_user_approval_required",
        "resolved_inputs": inputs,
        "tnt_consistency": consistency,
        "axisymmetric_target_mesh": target_grid,
        "axisymmetric_region_mesh": region_mesh,
        "fsi_coupling": (
            region_mesh.get("fsi_coupling")
            if isinstance(region_mesh, dict)
            else {
                "overlap_layers": inputs["fsi_overlap_layers"],
                "overlap_depth_m": (
                    int(inputs["fsi_overlap_layers"]) * float(inputs["mesh_size_m"])
                ),
                "physical_meaning": "computational_overlap_not_physical_air_thickness",
            }
        ),
        "kc_material": {
            "type": "concrete_damage_rel3",
            "parameter_mode": "automatic",
            "fpc_pa": float(inputs["concrete_fpc_pa"]),
            "validation_status": "demo_unvalidated",
        },
    }


def tool_generate_phase15_a1(args: JSONDict) -> JSONDict:
    inputs = default_phase15_a1_inputs()
    for field in {
        "tnt_mass_kg",
        "tnt_length_m",
        "tnt_density_kg_per_m3",
        "consistency_mode",
        "target_radius_m",
        "target_height_m",
        "mesh_size_m",
        "coupling_mode",
        "fsi_overlap_layers",
        "borehole_radius_m",
        "bottom_air_gap_m",
        "steel_thickness_m",
        "concrete_fpc_pa",
    }:
        if field in args:
            inputs[field] = args[field]
    if "tnt_diameter_m" in args:
        inputs["tnt_radius_m"] = float(args["tnt_diameter_m"]) / 2.0

    coupling_mode = resolve_phase15_coupling_mode(inputs)
    if (
        coupling_mode == "conforming_air_gap"
        and str(args.get("if_exists", "error")) != "error"
    ):
        raise ValueError("conforming_air_gap generation requires if_exists=error")
    if "fsi_overlap_layers" in args and coupling_mode != "immersed_clis":
        raise ValueError("fsi_overlap_layers is only valid for immersed_clis")
    if coupling_mode == "immersed_clis":
        resolve_phase15_fsi_overlap_layers(inputs)

    consistency = resolve_tnt_consistency(inputs)
    if consistency["needs_confirmation"]:
        raise ValueError(f"TNT source conflict requires confirmation: {consistency.get('reason')}")

    materials = default_phase15_materials()
    materials["tnt"]["density_kg_per_m3"] = consistency["effective_density_kg_per_m3"]
    materials["concrete"]["fpc_pa"] = float(inputs["concrete_fpc_pa"])
    material_fields = {
        "concrete_density_kg_per_m3": ("concrete", "density_kg_per_m3"),
        "concrete_poisson": ("concrete", "poisson"),
        "steel_density_kg_per_m3": ("steel_hoop", "density_kg_per_m3"),
        "steel_youngs_pa": ("steel_hoop", "youngs_pa"),
        "steel_poisson": ("steel_hoop", "poisson"),
        "steel_yield_strength_pa": ("steel_hoop", "yield_strength_pa"),
        "steel_tangent_modulus_pa": ("steel_hoop", "tangent_modulus_pa"),
        "tnt_detonation_velocity_m_per_s": ("tnt", "detonation_velocity_m_per_s"),
        "tnt_cj_pressure_pa": ("tnt", "chapman_jouget_pressure_pa"),
    }
    for argument, (group, field) in material_fields.items():
        if argument in args:
            materials[group][field] = args[argument]
    if "tnt_initial_energy_density_j_per_m3" in args:
        materials["tnt"]["jwl"]["initial_internal_energy_density_j_per_m3"] = args[
            "tnt_initial_energy_density_j_per_m3"
        ]
    materials["erosion"]["mode"] = str(args.get("erosion_mode", "off"))
    if materials["erosion"]["mode"] == "custom":
        materials["erosion"]["maximum_principal_strain"] = args.get(
            "erosion_maximum_principal_strain"
        )
        materials["erosion"]["confirmed_by_user"] = args.get("erosion_confirmed_by_user") is True

    output = default_phase15_output()
    for field in {
        "end_time_s",
        "early_output_dt_s",
        "late_output_dt_s",
        "history_output_dt_s",
    }:
        if field in args:
            output[field] = args[field]
    project_name = str(args.get("project_name", "phase15_a1_kc_axisymmetric_blast"))
    keyword, metadata, spec = build_phase15_a1_keyword(
        project_name, inputs, materials=materials, output=output
    )
    common: JSONDict = {
        "ok": True,
        "status": "validated_only" if bool_arg(args, "dry_run", False) else "generated",
        "project_name": project_name,
        "model_type": "phase15_axisymmetric_blast",
        "solver_permission": "explicit_user_approval_required",
        "keyword_size_bytes": len(keyword.encode("utf-8")),
        "metadata": metadata,
        "sensitivity_matrix": phase15_sensitivity_matrix(),
    }
    if bool_arg(args, "dry_run", False):
        return {**common, "resolved_spec": spec}
    result = write_compiled_keyword_project(
        project_name,
        keyword,
        spec,
        metadata,
        if_exists=str(args.get("if_exists", "error")),
    )
    result.update(common)
    result["project_name"] = result["project"]
    result["ok"] = bool(isinstance(result.get("checks"), dict) and result["checks"].get("ok"))
    return result


def tool_generate_ale_blast_demo(args: JSONDict) -> JSONDict:
    project_name = str(args.get("project_name", "phase14_mmale_blast_plate"))
    raw = default_ale_blast_spec(project_name)
    geometry = raw["geometry"]
    field_map = {
        "domain_min_m": "domain_min_m",
        "domain_max_m": "domain_max_m",
        "explosive_center_m": "explosive_center_m",
        "explosive_mass_kg": "explosive_mass_kg",
        "plate_length_m": "plate_length_m",
        "plate_width_m": "plate_width_m",
        "plate_thickness_m": "plate_thickness_m",
        "plate_z_m": "plate_z_m",
    }
    for argument_name, geometry_name in field_map.items():
        if argument_name in args:
            geometry[geometry_name] = deepcopy(args[argument_name])
    if "mesh_size_m" in args:
        raw["mesh"]["size_m"] = args["mesh_size_m"]
    if "plate_material_name" in args:
        raw["material"]["name"] = str(args["plate_material_name"])
    if "end_time_s" in args:
        raw["analysis_control"]["termination"]["end_time_s"] = args["end_time_s"]
    if "d3plot_dt_s" in args:
        raw["database"]["d3plot_dt_s"] = args["d3plot_dt_s"]
    if "fsi_dt_s" in args:
        raw["database"]["fsi_dt_s"] = args["fsi_dt_s"]

    parsed = parse_model_spec(raw)
    keyword, metadata = build_keyword(parsed)
    common = {
        "ok": True,
        "model_type": "ale_blast_scene",
        "project_name": parsed.project_name,
        "solver_permission": "explicit_user_approval_required",
        "metadata": metadata,
        "mesh_sensitivity": phase14_mesh_sensitivity_report(parsed),
    }
    if bool_arg(args, "dry_run", False):
        return {
            **common,
            "status": "validated_only",
            "resolved_spec": asdict(parsed),
            "keyword_size_bytes": len(keyword.encode("utf-8")),
        }
    result = write_model_project(parsed, if_exists=str(args.get("if_exists", "error")))
    result.update(common)
    checks = result.get("checks")
    result["ok"] = bool(isinstance(checks, dict) and checks.get("ok"))
    return result


def tool_generate_city_street_blast(args: JSONDict) -> JSONDict:
    project_name = str(args.get("project_name", "city_street_blast"))
    spec = default_city_street_blast_spec(project_name)
    explosive = spec["explosive"]
    if "tnt_mass_kg" in args:
        explosive["mass_kg"] = args["tnt_mass_kg"]
    if "tnt_diameter_m" in args:
        explosive["diameter_m"] = args["tnt_diameter_m"]
    radius = 0.5 * float(explosive["diameter_m"])
    explosive["length_m"] = float(explosive["mass_kg"]) / (
        float(explosive["density_kg_per_m3"]) * 3.141592653589793 * radius * radius
    )
    if "near_mesh_size_m" in args:
        spec["mesh"]["near_size_m"] = args["near_mesh_size_m"]
    if "end_time_s" in args:
        spec["analysis"]["end_time_s"] = args["end_time_s"]

    keyword, metadata = build_city_street_blast_keyword(spec)
    common = {
        "ok": True,
        "model_type": "city_street_blast_scene",
        "scene_id": "city_street_blast",
        "project_name": project_name,
        "solver_permission": "explicit_user_approval_required",
        "metadata": metadata,
    }
    if bool_arg(args, "dry_run", False):
        return {
            **common,
            "status": "validated_only",
            "resolved_spec": metadata["resolved_spec"],
            "keyword_size_bytes": len(keyword.encode("utf-8")),
        }
    result = write_compiled_keyword_project(
        project_name,
        keyword,
        metadata["resolved_spec"],
        metadata,
        if_exists=str(args.get("if_exists", "error")),
    )
    result.update(common)
    checks = result.get("checks")
    result["ok"] = bool(isinstance(checks, dict) and checks.get("ok"))
    return result


def tunnel_blast_demo_input_schema() -> JSONDict:
    return {
        "type": "object",
        "properties": {
            "project_name": {"type": "string", "default": "phase14_open_tunnel_blast"},
            "tunnel_length_m": {"type": "number", "minimum": 4.0, "maximum": 12.0, "default": 6.0},
            "tunnel_width_m": {"type": "number", "minimum": 2.0, "maximum": 8.0, "default": 4.0},
            "tunnel_height_m": {"type": "number", "minimum": 2.0, "maximum": 8.0, "default": 4.0},
            "tunnel_wall_thickness_m": {
                "type": "number",
                "minimum": 0.1,
                "maximum": 0.6,
                "default": 0.25,
            },
            "air_mesh_size_m": {
                "type": "number",
                "enum": list(TUNNEL_AIR_MESH_OPTIONS_M),
                "default": 0.1,
            },
            "explosive_center_m": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "default": [1.5, 0.0, 0.0],
            },
            "explosive_mass_kg": {"type": "number", "default": 1.0},
            "plate_length_m": {"type": "number", "default": 1.2},
            "plate_width_m": {"type": "number", "default": 1.2},
            "plate_thickness_m": {"type": "number", "default": 0.02},
            "plate_center_m": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "default": [4.5, 0.0, 0.0],
            },
            "plate_material_name": {
                "type": "string",
                "enum": list(TUNNEL_PLATE_MATERIAL_NAMES),
                "default": "mild_steel_mat24_demo",
            },
            "end_time_s": {"type": "number", "default": 0.012},
            "dry_run": {"type": "boolean", "default": False},
            "if_exists": {
                "type": "string",
                "enum": ["error", "overwrite", "archive_then_write", "versioned"],
                "default": "error",
            },
        },
        "additionalProperties": False,
    }


def tool_generate_tunnel_blast_demo(args: JSONDict) -> JSONDict:
    project_name = str(args.get("project_name", "phase14_open_tunnel_blast"))
    raw = default_tunnel_blast_spec(project_name)
    for key in [
        "tunnel_length_m",
        "tunnel_width_m",
        "tunnel_height_m",
        "tunnel_wall_thickness_m",
        "explosive_center_m",
        "explosive_mass_kg",
        "plate_length_m",
        "plate_width_m",
        "plate_thickness_m",
        "plate_center_m",
    ]:
        if key in args:
            raw["geometry"][key] = deepcopy(args[key])
    tunnel_length = raw["geometry"]["tunnel_length_m"]
    tunnel_width = raw["geometry"]["tunnel_width_m"]
    tunnel_height = raw["geometry"]["tunnel_height_m"]
    raw["geometry"]["domain_min_m"] = [0.0, -0.5 * tunnel_width, -0.5 * tunnel_height]
    raw["geometry"]["domain_max_m"] = [tunnel_length, 0.5 * tunnel_width, 0.5 * tunnel_height]
    if "air_mesh_size_m" in args:
        raw["mesh"]["size_m"] = args["air_mesh_size_m"]
        raw["mesh"]["wall_size_m"] = args["air_mesh_size_m"]
    material_name = str(args.get("plate_material_name", raw["material"]["name"]))
    if material_name not in TUNNEL_PLATE_MATERIAL_NAMES:
        known = ", ".join(TUNNEL_PLATE_MATERIAL_NAMES)
        raise ValueError(f"plate_material_name must be one of: {known}")
    raw["material"]["name"] = material_name
    if "end_time_s" in args:
        end_time = args["end_time_s"]
        raw["analysis_control"]["termination"]["end_time_s"] = end_time
        raw["database"]["d3plot_schedule"][-1]["until_time_s"] = end_time

    parsed = parse_model_spec(raw)
    mesh_estimate = preflight_model_spec(parsed)
    keyword, metadata = build_keyword(parsed)
    common = {
        "ok": True,
        "model_type": "ale_blast_scene",
        "scene_variant": "open_concrete_tunnel",
        "project_name": parsed.project_name,
        "solver_permission": "explicit_user_approval_required",
        "metadata": metadata,
        "mesh_estimate": mesh_estimate,
    }
    if bool_arg(args, "dry_run", False):
        return {
            **common,
            "status": "validated_only",
            "resolved_spec": asdict(parsed),
            "keyword_size_bytes": len(keyword.encode("utf-8")),
        }
    result = write_model_project(parsed, if_exists=str(args.get("if_exists", "error")))
    result.update(common)
    checks = result.get("checks")
    result["ok"] = bool(isinstance(checks, dict) and checks.get("ok"))
    return result


def tool_list_component_templates(args: JSONDict) -> JSONDict:
    components = component_catalog()
    return {"ok": True, "count": len(components), "components": components}


def tool_get_component_template(args: JSONDict) -> JSONDict:
    name = args.get("template", args.get("name"))
    if not isinstance(name, str) or not name.strip():
        raise ValueError("template must be a non-empty string")
    definition = component_definition(name.strip())
    component = next(item for item in component_catalog() if item["name"] == definition.name)
    return {"ok": True, "component": component}


def tool_list_physics_actions(args: JSONDict) -> JSONDict:
    actions = physics_action_catalog()
    return {"ok": True, "count": len(actions), "actions": actions}


def tool_assemble_components(args: JSONDict) -> JSONDict:
    components = args.get("components")
    if not isinstance(components, list):
        raise ValueError("components must be an array")
    if not 1 <= len(components) <= MAX_ASSEMBLY_COMPONENTS:
        raise ValueError(f"components must contain between 1 and {MAX_ASSEMBLY_COMPONENTS} items")
    validate_assembly_component_fields(components)

    project_name = str(args.get("project_name", "assembled_model"))
    compiled = compile_physics_actions(
        deepcopy(components),
        deepcopy(args.get("actions", [])),
        contacts=deepcopy(args.get("contacts", [])),
        loads=deepcopy(args.get("loads", [])),
    )
    raw = default_model_spec(project_name, "assembly_scene")
    raw["components"] = compiled["components"]
    raw["contacts"] = compiled["contacts"]
    raw["loads"] = compiled["loads"]
    for field in (
        "sets",
        "boundary_conditions",
        "curves",
        "analysis_control",
        "database",
    ):
        if field in args:
            raw[field] = args[field]
    parsed = parse_model_spec(raw)
    keyword, metadata = build_keyword(parsed)
    sensitivity = blast_sensitivity_report(asdict(parsed)) if metadata.get("blast_count") else None
    if bool_arg(args, "dry_run", False):
        result = {
            "ok": True,
            "status": "validated_only",
            "project_name": parsed.project_name,
            "resolved_spec": asdict(parsed),
            "metadata": metadata,
            "compiled_actions": compiled["actions"],
            "keyword_size_bytes": len(keyword.encode("utf-8")),
        }
        if sensitivity is not None:
            result["sensitivity"] = sensitivity
        return result
    result = write_model_project(parsed, if_exists=str(args.get("if_exists", "error")))
    if sensitivity is not None:
        result["sensitivity"] = sensitivity
    return result


def validate_assembly_component_fields(components: list[object]) -> None:
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
    for index, value in enumerate(components):
        if not isinstance(value, dict):
            raise ValueError(f"components[{index}] must be an object")
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"components[{index}] received unsupported field(s): {', '.join(unknown)}")
        template = str(value.get("template", ""))
        definition = component_definition(template)
        geometry = value.get("geometry")
        if not isinstance(geometry, dict):
            raise ValueError(f"components[{index}].geometry must be an object")
        unknown_geometry = sorted(set(geometry) - set(definition.geometry_fields))
        if unknown_geometry:
            raise ValueError(
                f"components[{index}] received unsupported geometry field(s): {', '.join(unknown_geometry)}"
            )


def tool_create_plate_demo(args: JSONDict) -> JSONDict:
    spec = default_model_spec(str(args.get("project_name", "plate_demo")), "shell_plate")
    geometry = spec["geometry"]
    mesh = spec["mesh"]
    material = spec["material"]
    if "length_m" in args:
        geometry["length_m"] = float(args["length_m"])
    if "width_m" in args:
        geometry["width_m"] = float(args["width_m"])
    if "thickness_m" in args:
        geometry["thickness_m"] = float(args["thickness_m"])
    if "mesh_size_m" in args:
        mesh["size_m"] = float(args["mesh_size_m"])
    if "material_name" in args:
        material["name"] = str(args["material_name"])
    return write_model_project(parse_model_spec(spec), if_exists=str(args.get("if_exists", "error")))


def tool_generate_scene_from_prompt(args: JSONDict) -> JSONDict:
    prompt = args.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")
    project_name = str(args.get("project_name", "scene_from_prompt"))
    parameters = args.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")
    raw_scene_id = args.get("scene_id")
    scene_template = None
    if raw_scene_id is not None:
        if not isinstance(raw_scene_id, str) or not raw_scene_id.strip():
            raise ValueError("scene_id must be a non-empty string")
        scene_template = raw_scene_id.strip()
    allow_defaults = bool_arg(args, "allow_defaults", False)
    dry_run = bool_arg(args, "dry_run", False)
    run_lsprepost_validation = bool_arg(args, "run_lsprepost_validation", False)
    export_previews = bool_arg(args, "export_previews", False)
    export_preview_gif = bool_arg(args, "export_preview_gif", False)
    timeout_s = automation_timeout(args, default=45.0)
    resolved = resolve_scene_prompt(
        prompt,
        project_name,
        parameters=parameters,
        allow_defaults=allow_defaults,
        scene_template=scene_template,
    )
    if not resolved.get("ok"):
        return resolved
    if dry_run:
        parse_model_spec(resolved["resolved_spec"])
        return {
            "ok": True,
            "status": "resolved_only",
            "intent": resolved["intent"],
            "scene_template": resolved["scene_template"],
            "project_name": project_name,
            "resolved_parameters": resolved["resolved_parameters"],
            "defaulted_parameters": resolved["defaulted_parameters"],
            "risk_notes": resolved.get("risk_notes", []),
            "summary": resolved["summary"],
            "resolved_spec": resolved["resolved_spec"],
        }

    write_result = write_model_project(
        parse_model_spec(resolved["resolved_spec"]),
        if_exists=str(args.get("if_exists", "error")),
    )
    path = find_project_dir(write_result["project"])
    result: JSONDict = {
        "ok": True,
        "intent": resolved["intent"],
        "scene_template": resolved["scene_template"],
        "project_name": write_result["project"],
        "project_dir": str(path),
        "keyword_path": str(path / "model.k"),
        "resolved_parameters": resolved["resolved_parameters"],
        "defaulted_parameters": resolved["defaulted_parameters"],
        "risk_notes": resolved.get("risk_notes", []),
        "summary": resolved["summary"],
        "write_result": write_result,
        "checks": write_result["checks"],
    }
    if run_lsprepost_validation:
        result["lsprepost_import"] = tool_validate_lsprepost_import(
            {
                "project_name": write_result["project"],
                "timeout_s": timeout_s,
                "if_exists": "overwrite",
            }
        )
    if export_previews:
        result["preview_images"] = tool_export_preview_images(
            {
                "project_name": write_result["project"],
                "timeout_s": timeout_s,
                "display_mode": "geometry",
                "if_exists": "overwrite",
            }
        )
    if export_preview_gif:
        result["preview_gif"] = tool_export_preview_gif(
            {
                "project_name": write_result["project"],
                "timeout_s": timeout_s,
                "display_mode": "geometry",
                "if_exists": "overwrite",
            }
        )
    return result
