from __future__ import annotations

from typing import Callable

from .config import JSONDict
from .lspp.launcher import launch_cfile, launch_keyword
from .scene_prompts import SUPPORTED_SCENE_TEMPLATES
from .schema import generate_model_input_schema
from .quarter_two_tnt import quarter_two_tnt_input_schema, tool_generate_quarter_two_tnt
from .gran_r5_rebuild import input_schema as gran_r5_input_schema, tool_prepare as tool_prepare_gran_r5, tool_generate as tool_generate_gran_r5
from .impact_1788_rebuild import input_schema as impact_1788_input_schema, tool_prepare as tool_prepare_impact_1788, tool_generate as tool_generate_impact_1788
from .b120_spg_sale_rebuild import input_schema as b120_input_schema, tool_prepare as tool_prepare_b120, tool_generate as tool_generate_b120
from .tool_generation import (
    ale_blast_demo_input_schema,
    city_street_blast_input_schema,
    phase15_a1_input_schema,
    phase15_a1_generate_input_schema,
    tunnel_blast_demo_input_schema,
    assemble_components_input_schema,
    tool_assemble_components,
    tool_create_plate_demo,
    tool_generate_model,
    tool_generate_ale_blast_demo,
    tool_generate_city_street_blast,
    tool_prepare_phase15_a1,
    tool_generate_phase15_a1,
    tool_generate_tunnel_blast_demo,
    tool_generate_scene_from_prompt,
    tool_get_component_template,
    tool_list_component_templates,
    tool_list_physics_actions,
)
from .tool_materials import tool_get_material, tool_list_materials, tool_validate_material_resource
from .tool_model_resources import (
    tool_export_model_resource,
    tool_get_model_resource,
    tool_list_model_resources,
    tool_validate_model_resource,
)
from .tool_structural_resources import (
    tool_get_structural_resource,
    tool_list_structural_resources,
    tool_validate_phase18_resource_review,
)
from .tool_phase16b import (
    analyze_city_case_uncertainty_input_schema,
    authorize_city_case_batch_input_schema,
    compare_city_case_results_input_schema,
    plan_city_local_refinement_input_schema,
    predict_city_surrogate_input_schema,
    prepare_city_case_matrix_input_schema,
    rank_city_protection_options_input_schema,
    register_city_case_result_input_schema,
    train_city_surrogate_input_schema,
    tool_authorize_city_case_batch,
    tool_analyze_city_case_uncertainty,
    tool_compare_city_case_results,
    tool_plan_city_local_refinement,
    tool_predict_city_surrogate,
    tool_prepare_city_case_matrix,
    tool_rank_city_protection_options,
    tool_register_city_case_result,
    tool_train_city_surrogate,
)
from .tool_lsprepost import (
    tool_export_preview_gif,
    tool_export_preview_image,
    tool_export_preview_images,
    tool_open_in_lsprepost,
    tool_run_cfile,
    tool_validate_lsprepost_import,
)
from .tool_project import (
    tool_archive_project,
    tool_import_keyword,
    tool_list_projects,
    tool_model_summary,
    tool_read_project,
    tool_validate_model,
)
from .tool_server import tool_server_info
from .tool_helpers import (
    GIF_SIGNATURES,
    MAX_AUTOMATION_TIMEOUT_S,
    MAX_GUI_TIMEOUT_S,
    PHASE6_REQUIRED_KEYWORDS,
    PNG_SIGNATURE,
    PREVIEW_DISPLAY_MODES,
    PREVIEW_VIEW_COMMANDS,
    automation_timeout,
    bool_arg,
    cfile_relative_path,
    failed_lsprepost_result,
    gif_duration_arg,
    preview_cfile_filename,
    preview_display_commands,
    preview_display_mode_arg,
    preview_keyword_reader_filename,
    preview_output_prefix_arg,
    preview_view_arg,
    preview_views_arg,
    record_lsprepost_verification,
    resolve_project_cfile,
    validate_phase6_required_keywords,
    validate_project_required_keywords,
    verify_gif_artifact,
    verify_keyword_reader_messages,
    verify_png_artifact,
    write_preview_gif,
)


ToolFn = Callable[[JSONDict], JSONDict]


TOOLS: dict[str, tuple[str, JSONDict, ToolFn]] = {
    "server_info": (
        "Return local LS-PrePost MCP server paths and defaults.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        tool_server_info,
    ),
    "generate_model": (
        "Generate model.json, model.k, open_model.cfile, and checks.json from a structured SI model spec.",
        generate_model_input_schema(),
        tool_generate_model,
    ),
    "prepare_b120_spg_sale_rebuild": (
        "Estimate the source-faithful B120 SPG/S-ALE rebuild and check its pinned resources without generating the full mesh.",
        b120_input_schema(),
        tool_prepare_b120,
    ),
    "generate_b120_spg_sale_rebuild": (
        "Generate an analytic B120 SPG/S-ALE mesh with original physics and spatially rebound sets; never launches a solver.",
        b120_input_schema(),
        tool_generate_b120,
    ),
    "prepare_impact_1788_rebuild": (
        "Inspect the pinned 5-1788-2 three-material reconstruction without generating a mesh or launching a solver.",
        impact_1788_input_schema(),
        tool_prepare_impact_1788,
    ),
    "generate_impact_1788_rebuild": (
        "Regenerate the 5-1788-2 analytic MM-ALE mesh with original nonmesh definitions; no solver launch.",
        impact_1788_input_schema(),
        tool_generate_impact_1788,
    ),
    "prepare_gran_r5_rebuild": (
        "Inspect the source-faithful GRAN_R5 reconstruction parameters and resource closure without generating a mesh or launching a solver.",
        gran_r5_input_schema(),
        tool_prepare_gran_r5,
    ),
    "generate_gran_r5_rebuild": (
        "Regenerate the reviewed GRAN_R5 analytic MM-ALE mesh and assemble its pinned original physical definitions. Never launches a solver.",
        gran_r5_input_schema(),
        tool_generate_gran_r5,
    ),
    "assemble_components": (
        "Assemble one or more registered components into one validated LS-DYNA project.",
        assemble_components_input_schema(),
        tool_assemble_components,
    ),
    "generate_ale_blast_demo": (
        "Generate or validate the controlled SI MM-ALE air/explosive/plate blast reference model. This tool never launches LS-DYNA.",
        ale_blast_demo_input_schema(),
        tool_generate_ale_blast_demo,
    ),    "generate_quarter_two_tnt_ale_spg": (
        "Generate the approved SI quarter-symmetry upper-MM-ALE/lower-SPG two-TNT project with streaming validation. This tool never launches LS-DYNA.",
        quarter_two_tnt_input_schema(),
        tool_generate_quarter_two_tnt,
    ),
    "generate_city_street_blast": (
        "Generate or validate the controlled city street MM-ALE blast scene with a cylindrical entity TNT charge and reusable urban components. This tool never launches LS-DYNA.",
        city_street_blast_input_schema(),
        tool_generate_city_street_blast,
    ),
    "prepare_city_case_matrix": (
        "Create a controlled Phase 16B city-blast case matrix. This tool only writes a manifest and never launches LS-Run or LS-DYNA.",
        prepare_city_case_matrix_input_schema(),
        tool_prepare_city_case_matrix,
    ),
    "authorize_city_case_batch": (
        "Record explicit authorization for listed Phase 16B cases without starting any solver process.",
        authorize_city_case_batch_input_schema(),
        tool_authorize_city_case_batch,
    ),
    "register_city_case_result": (
        "Register a completed city result only after it passes the Phase 16A quality and object-metrics gates.",
        register_city_case_result_input_schema(),
        tool_register_city_case_result,
    ),
    "compare_city_case_results": (
        "Compare one semantic city object across registered Phase 16B cases; mixed meshes are blocked unless explicitly requested.",
        compare_city_case_results_input_schema(),
        tool_compare_city_case_results,
    ),
    "analyze_city_case_uncertainty": (
        "Analyze registered Phase 16B object metrics for sample coverage, screening sensitivity, confidence intervals, and paired mesh-fidelity differences. This tool never launches a solver.",
        analyze_city_case_uncertainty_input_schema(),
        tool_analyze_city_case_uncertainty,
    ),
    "plan_city_local_refinement": (
        "Create an auditable Phase 16B local-refinement plan from object risk, uncertainty, paired mesh differences, semantic bounds, and blast geometry. This planning-only tool never edits a K file or launches a solver.",
        plan_city_local_refinement_input_schema(),
        tool_plan_city_local_refinement,
    ),
    "train_city_surrogate": (
        "Train a local Phase 16B object-response surrogate from registered compatible cases using leave-one-out validation. This tool never launches a solver.",
        train_city_surrogate_input_schema(),
        tool_train_city_surrogate,
    ),
    "predict_city_surrogate": (
        "Estimate an object metric only inside a trained Phase 16B surrogate applicability domain; extrapolation and sparse regions are refused. This tool never launches a solver.",
        predict_city_surrogate_input_schema(),
        tool_predict_city_surrogate,
    ),
    "rank_city_protection_options": (
        "Compare registered Phase 16B protection alternatives against a baseline using explicit objectives, costs, constraints, physical basis, Pareto status, and a transparent weighted score. This tool never launches a solver.",
        rank_city_protection_options_input_schema(),
        tool_rank_city_protection_options,
    ),
    "generate_tunnel_blast_demo": (
        "Generate or validate the controlled 6 x 4 x 4 m open concrete tunnel MM-ALE blast model. This tool never launches LS-DYNA.",
        tunnel_blast_demo_input_schema(),
        tool_generate_tunnel_blast_demo,
    ),
    "prepare_phase15_a1": (
        "Validate the controlled Phase 15 A-1 source inputs, expose TNT consistency choices, and estimate the axisymmetric mesh. This tool never launches an external program.",
        phase15_a1_input_schema(),
        tool_prepare_phase15_a1,
    ),
    "generate_phase15_a1": (
        "Generate the controlled Phase 15 A-1 two-dimensional axisymmetric MM-ALE/K&C keyword project. This tool never launches LS-PrePost, LS-Run, or LS-DYNA.",
        phase15_a1_generate_input_schema(),
        tool_generate_phase15_a1,
    ),
    "list_component_templates": (
        "List registered reusable component templates and their named regions.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        tool_list_component_templates,
    ),
    "get_component_template": (
        "Return one registered component template definition.",
        {
            "type": "object",
            "properties": {"template": {"type": "string"}, "name": {"type": "string"}},
            "additionalProperties": False,
        },
        tool_get_component_template,
    ),
    "list_physics_actions": (
        "List controlled physics actions accepted by assemble_components.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        tool_list_physics_actions,
    ),
    "create_plate_demo": (
        "Compatibility helper that creates a simple SI shell plate demo.",
        {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "default": "plate_demo"},
                "length_m": {"type": "number", "default": 0.12},
                "width_m": {"type": "number", "default": 0.06},
                "thickness_m": {"type": "number", "default": 0.0015},
                "mesh_size_m": {"type": "number", "default": 0.01},
                "material_name": {"type": "string", "default": "mild_steel"},
                "if_exists": {
                    "type": "string",
                    "enum": ["error", "overwrite", "archive_then_write", "versioned"],
                    "default": "error",
                },
            },
            "additionalProperties": False,
        },
        tool_create_plate_demo,
    ),
    "generate_scene_from_prompt": (
        "Resolve a natural-language engineering scene prompt into a supported controlled scene spec, generate model.k, and optionally run LS-PrePost validation/previews.",
        {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "default": "scene_from_prompt"},
                "prompt": {"type": "string"},
                "scene_id": {
                    "type": "string",
                    "enum": SUPPORTED_SCENE_TEMPLATES,
                    "description": "Optional controlled scene template id. When provided, this overrides prompt classification.",
                },
                "parameters": {
                    "type": "object",
                    "properties": {
                        "rebar_length_m": {"type": "number"},
                        "rebar_radius_m": {"type": "number"},
                        "rebar_diameter_m": {"type": "number"},
                        "drop_height_m": {"type": "number"},
                        "rod_length_m": {"type": "number"},
                        "rod_radius_m": {"type": "number"},
                        "rod_diameter_m": {"type": "number"},
                        "impact_velocity_m_per_s": {"type": "number"},
                        "plate_length_m": {"type": "number"},
                        "plate_width_m": {"type": "number"},
                        "plate_thickness_m": {"type": "number"},
                        "cube_length_m": {"type": "number"},
                        "cube_width_m": {"type": "number"},
                        "cube_height_m": {"type": "number"},
                        "cube_size_m": {"type": "number"},
                        "corner_force_n": {"type": "number"},
                        "pressure_pa": {"type": "number"},
                        "material_name": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "allow_defaults": {
                    "type": "boolean",
                    "default": False,
                    "description": "If false, missing key physical parameters return needs_confirmation instead of generating a model.",
                },
                "dry_run": {
                    "type": "boolean",
                    "default": False,
                    "description": "Resolve the prompt and return the controlled scene spec without writing project files.",
                },
                "run_lsprepost_validation": {
                    "type": "boolean",
                    "default": False,
                    "description": "Run validate_lsprepost_import after model generation.",
                },
                "export_previews": {
                    "type": "boolean",
                    "default": False,
                    "description": "Export iso/top/front/side preview images after model generation.",
                },
                "export_preview_gif": {
                    "type": "boolean",
                    "default": False,
                    "description": "Export iso/top/front PNG frames and combine them into preview_summary.gif after model generation.",
                },
                "timeout_s": {
                    "type": "number",
                    "default": 45,
                    "description": "Per LS-PrePost automation timeout when validation or preview export is enabled.",
                },
                "if_exists": {
                    "type": "string",
                    "enum": ["error", "overwrite", "archive_then_write", "versioned"],
                    "default": "error",
                },
            },
            "required": ["prompt"],
            "additionalProperties": False,
        },
        tool_generate_scene_from_prompt,
    ),
    "list_materials": (
        "List built-in SI material library entries.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        tool_list_materials,
    ),
    "get_material": (
        "Return one built-in SI material library entry by material_id.",
        {
            "type": "object",
            "properties": {
                "material_id": {"type": "string"},
                "name": {"type": "string"},
            },
            "additionalProperties": False,
        },
        tool_get_material,
    ),
    "validate_material_resource": (
        "Validate one reviewed Phase 18 material resource without claiming engineering calibration.",
        {
            "type": "object",
            "properties": {"material_id": {"type": "string"}},
            "required": ["material_id"],
            "additionalProperties": False,
        },
        tool_validate_material_resource,
    ),
    "list_structural_resources": (
        "List reviewed Section, Curve, Part, Set, and coupling resources in the model library.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        tool_list_structural_resources,
    ),
    "get_structural_resource": (
        "Return one structural relationship resource by resource_id.",
        {
            "type": "object",
            "properties": {"resource_id": {"type": "string"}},
            "required": ["resource_id"],
            "additionalProperties": False,
        },
        tool_get_structural_resource,
    ),
    "validate_phase18_resource_review": (
        "Validate all hash-bound Phase 18 material and structural review records.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        tool_validate_phase18_resource_review,
    ),
    "list_model_resources": (
        "List registered reusable model resources and their compatibility status.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        tool_list_model_resources,
    ),
    "get_model_resource": (
        "Return one reusable model resource manifest by resource_id.",
        {
            "type": "object",
            "properties": {"resource_id": {"type": "string"}},
            "required": ["resource_id"],
            "additionalProperties": False,
        },
        tool_get_model_resource,
    ),
    "validate_model_resource": (
        "Validate one model resource payload hash, mesh counts, and node-reference closure.",
        {
            "type": "object",
            "properties": {"resource_id": {"type": "string"}},
            "required": ["resource_id"],
            "additionalProperties": False,
        },
        tool_validate_model_resource,
    ),
    "export_model_resource": (
        "Export one registered model resource as an independent plain LS-DYNA .k file. This never launches external software.",
        {
            "type": "object",
            "properties": {
                "resource_id": {"type": "string"},
                "export_name": {"type": "string"},
                "filename": {"type": "string", "default": "component.k"},
            },
            "required": ["resource_id"],
            "additionalProperties": False,
        },
        tool_export_model_resource,
    ),
    "validate_model": (
        "Validate a generated or imported project.",
        {"type": "object", "properties": {"project_name": {"type": "string", "default": "plate_demo"}}, "additionalProperties": False},
        tool_validate_model,
    ),
    "model_summary": (
        "Return a concise natural-language summary and structured summary for a project.",
        {"type": "object", "properties": {"project_name": {"type": "string", "default": "generic_plate_demo"}}, "additionalProperties": False},
        tool_model_summary,
    ),
    "list_projects": (
        "List generated, legacy, and archived model projects.",
        {"type": "object", "properties": {"include_archived": {"type": "boolean", "default": True}}, "additionalProperties": False},
        tool_list_projects,
    ),
    "read_project": (
        "Read model.json, checks.json, paths, and summary for a project.",
        {"type": "object", "properties": {"project_name": {"type": "string", "default": "generic_plate_demo"}}, "additionalProperties": False},
        tool_read_project,
    ),
    "archive_project": (
        "Archive an active workspace project. confirm_project_name must exactly match project_name.",
        {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "confirm_project_name": {"type": "string"},
                "reason": {"type": "string", "default": ""},
            },
            "required": ["project_name", "confirm_project_name"],
            "additionalProperties": False,
        },
        tool_archive_project,
    ),
    "import_keyword": (
        "Import an existing LS-DYNA keyword file into a workspace project and parse basic metadata.",
        {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "default": "imported_keyword"},
                "keyword_path": {"type": "string"},
                "allow_external": {"type": "boolean", "default": False},
                "max_bytes": {"type": "integer", "default": 10485760},
                "if_exists": {
                    "type": "string",
                    "enum": ["error", "overwrite", "archive_then_write", "versioned"],
                    "default": "error",
                },
            },
            "required": ["keyword_path"],
            "additionalProperties": False,
        },
        tool_import_keyword,
    ),
    "open_in_lsprepost": (
        "Open a generated model.k in LS-PrePost after validating GUI-preview readiness.",
        {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "default": "plate_demo"},
                "force": {
                    "type": "boolean",
                    "default": False,
                    "description": "Bypass readiness gate; still requires model.k and LS-PrePost executable.",
                },
                "timeout_s": {
                    "type": "number",
                    "default": 0,
                    "description": "Optional wait timeout; 0 starts LS-PrePost and returns after launch.",
                },
            },
            "additionalProperties": False,
        },
        tool_open_in_lsprepost,
    ),
    "export_preview_image": (
        "Open a generated model.k with a server-approved LS-PrePost cfile and export a PNG preview artifact.",
        {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "default": "plate_demo"},
                "output_filename": {"type": "string", "default": "preview.png"},
                "view": {
                    "type": "string",
                    "enum": ["current", "iso", "top", "front", "side"],
                    "default": "current",
                    "description": "Preview view command. current preserves LS-PrePost default view; other values request a controlled camera orientation.",
                },
                "display_mode": {
                    "type": "string",
                    "enum": ["geometry", "boundary_conditions", "loads_constraints", "sets", "validation"],
                    "default": "geometry",
                    "description": "Controlled LS-PrePost display overlays for preview images.",
                },
                "auto_fit": {
                    "type": "boolean",
                    "default": True,
                    "description": "Run LS-PrePost ac before exporting the PNG.",
                },
                "timeout_s": {
                    "type": "number",
                    "default": 45,
                    "description": "Wait timeout for the LS-PrePost preview export cfile.",
                },
                "if_exists": {
                    "type": "string",
                    "enum": ["error", "overwrite", "versioned"],
                    "default": "overwrite",
                },
            },
            "additionalProperties": False,
        },
        tool_export_preview_image,
    ),
    "export_preview_images": (
        "Export multiple controlled PNG preview views with server-approved LS-PrePost cfiles.",
        {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "default": "plate_demo"},
                "views": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["current", "iso", "top", "front", "side"]},
                    "default": ["iso", "top", "front", "side"],
                    "description": "Controlled preview views to export. Duplicate views are rejected.",
                },
                "output_prefix": {
                    "type": "string",
                    "default": "preview",
                    "description": "Simple artifact filename prefix. Outputs are named <prefix>_<view>.png.",
                },
                "display_mode": {
                    "type": "string",
                    "enum": ["geometry", "boundary_conditions", "loads_constraints", "sets", "validation"],
                    "default": "geometry",
                    "description": "Controlled LS-PrePost display overlays for preview images.",
                },
                "auto_fit": {
                    "type": "boolean",
                    "default": True,
                    "description": "Run LS-PrePost ac before exporting each PNG.",
                },
                "timeout_s": {
                    "type": "number",
                    "default": 45,
                    "description": "Per-view wait timeout for each LS-PrePost preview export cfile.",
                },
                "if_exists": {
                    "type": "string",
                    "enum": ["error", "overwrite", "versioned"],
                    "default": "overwrite",
                },
            },
            "additionalProperties": False,
        },
        tool_export_preview_images,
    ),
    "export_preview_gif": (
        "Export controlled preview PNG frames and combine them into a GIF preview summary.",
        {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "default": "plate_demo"},
                "views": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["current", "iso", "top", "front", "side"]},
                    "default": ["iso", "top", "front"],
                    "description": "Controlled preview views to export and combine as GIF frames.",
                },
                "output_filename": {"type": "string", "default": "preview_summary.gif"},
                "output_prefix": {
                    "type": "string",
                    "default": "preview",
                    "description": "Simple artifact filename prefix for PNG frames. Frames are named <prefix>_<view>.png.",
                },
                "duration_ms": {
                    "type": "integer",
                    "default": 900,
                    "description": "Frame duration in milliseconds; must be greater than 0 and at most 10000.",
                },
                "display_mode": {
                    "type": "string",
                    "enum": ["geometry", "boundary_conditions", "loads_constraints", "sets", "validation"],
                    "default": "geometry",
                    "description": "Controlled LS-PrePost display overlays for preview frames.",
                },
                "auto_fit": {
                    "type": "boolean",
                    "default": True,
                    "description": "Run LS-PrePost ac before exporting each PNG frame.",
                },
                "timeout_s": {
                    "type": "number",
                    "default": 45,
                    "description": "Per-frame wait timeout for each LS-PrePost preview export cfile.",
                },
                "if_exists": {
                    "type": "string",
                    "enum": ["error", "overwrite", "versioned"],
                    "default": "overwrite",
                },
            },
            "additionalProperties": False,
        },
        tool_export_preview_gif,
    ),
    "validate_lsprepost_import": (
        "Open model.k in LS-PrePost with a server-approved cfile, save keyword reader messages, export a PNG, and return import validation status.",
        {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "default": "plate_demo"},
                "output_filename": {"type": "string", "default": "import_validation_iso.png"},
                "view": {
                    "type": "string",
                    "enum": ["current", "iso", "top", "front", "side"],
                    "default": "iso",
                },
                "display_mode": {
                    "type": "string",
                    "enum": ["geometry", "boundary_conditions", "loads_constraints", "sets", "validation"],
                    "default": "validation",
                    "description": "Controlled overlays used for the validation screenshot.",
                },
                "auto_fit": {"type": "boolean", "default": True},
                "timeout_s": {
                    "type": "number",
                    "default": 45,
                    "description": "Wait timeout for the LS-PrePost import validation cfile.",
                },
                "if_exists": {
                    "type": "string",
                    "enum": ["error", "overwrite", "versioned"],
                    "default": "overwrite",
                },
            },
            "additionalProperties": False,
        },
        tool_validate_lsprepost_import,
    ),
    "run_cfile": (
        "Run a manifest-verified server-generated project cfile through LS-PrePost.",
        {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "default": "plate_demo"},
                "cfile_filename": {"type": "string", "default": "open_model.cfile"},
                "timeout_s": {
                    "type": "number",
                    "default": 45,
                    "description": "Wait timeout for the LS-PrePost cfile; timeout_s must be greater than 0 and the tool returns ok only after successful completion.",
                },
                "allow_multiple": {"type": "boolean", "default": False},
                "manual_ack": {"type": "string", "default": ""},
            },
            "additionalProperties": False,
        },
        tool_run_cfile,
    ),
}


def tool_list() -> JSONDict:
    return {
        "tools": [
            {"name": name, "description": description, "inputSchema": schema}
            for name, (description, schema, _) in TOOLS.items()
        ]
    }
