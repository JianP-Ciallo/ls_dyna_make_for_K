from __future__ import annotations

from .config import JSONDict
from .paths import find_project_dir
from .phase16b import (
    MAX_PROTECTION_OBJECTIVES,
    MAX_PROTECTION_OPTIONS,
    MAX_VALUES_PER_PARAMETER,
    analyze_case_uncertainty,
    authorize_case_batch,
    compare_case_results,
    create_controlled_case_matrix,
    plan_local_refinement,
    predict_surrogate_response,
    rank_protection_options,
    register_case_result,
    train_surrogate_model,
)


def prepare_city_case_matrix_input_schema() -> JSONDict:
    numeric_array = {
        "type": "array",
        "items": {"type": "number"},
        "minItems": 1,
        "maxItems": MAX_VALUES_PER_PARAMETER,
    }
    return {
        "type": "object",
        "properties": {
            "project_name": {"type": "string"},
            "study_id": {"type": "string"},
            "dimensions": {
                "type": "object",
                "properties": {
                    "tnt_mass_kg": {
                        **numeric_array,
                        "items": {
                            "type": "number",
                            "minimum": 10.0,
                            "maximum": 1000.0,
                        },
                    },
                    "tnt_diameter_m": {
                        **numeric_array,
                        "items": {
                            "type": "number",
                            "minimum": 0.3,
                            "maximum": 1.5,
                        },
                    },
                    "blast_center_x_m": numeric_array,
                    "blast_center_y_m": numeric_array,
                    "blast_center_z_m": numeric_array,
                    "near_mesh_size_m": {
                        **numeric_array,
                        "items": {
                            "type": "number",
                            "enum": [0.05, 0.075, 0.1, 0.15, 0.2],
                        },
                    },
                    "end_time_s": {
                        **numeric_array,
                        "items": {
                            "type": "number",
                            "minimum": 0.005,
                            "maximum": 0.1,
                        },
                    },
                },
                "additionalProperties": False,
            },
        },
        "required": ["project_name", "study_id", "dimensions"],
        "additionalProperties": False,
    }


def authorize_city_case_batch_input_schema() -> JSONDict:
    return {
        "type": "object",
        "properties": {
            "project_name": {"type": "string"},
            "study_id": {"type": "string"},
            "case_ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 64,
            },
            "approval_text": {"type": "string"},
        },
        "required": ["project_name", "study_id", "case_ids", "approval_text"],
        "additionalProperties": False,
    }


def register_city_case_result_input_schema() -> JSONDict:
    return {
        "type": "object",
        "properties": {
            "project_name": {"type": "string"},
            "study_id": {"type": "string"},
            "case_id": {"type": "string"},
            "result_project_name": {"type": "string"},
            "replace": {"type": "boolean", "default": False},
        },
        "required": [
            "project_name",
            "study_id",
            "case_id",
            "result_project_name",
        ],
        "additionalProperties": False,
    }


def compare_city_case_results_input_schema() -> JSONDict:
    return {
        "type": "object",
        "properties": {
            "project_name": {"type": "string"},
            "study_id": {"type": "string"},
            "object_id": {"type": "string"},
            "case_ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 64,
            },
            "allow_mixed_mesh": {"type": "boolean", "default": False},
        },
        "required": ["project_name", "study_id", "object_id"],
        "additionalProperties": False,
    }


def analyze_city_case_uncertainty_input_schema() -> JSONDict:
    return {
        "type": "object",
        "properties": {
            "project_name": {"type": "string"},
            "study_id": {"type": "string"},
            "object_id": {"type": "string"},
            "metric_id": {
                "type": "string",
                "enum": [
                    "peak_pressure_pa",
                    "pressure_impulse_pa_s",
                    "max_displacement_m",
                    "equivalent_stress_pa",
                    "damage_index",
                ],
            },
            "case_ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 64,
            },
            "confidence_level": {
                "type": "number",
                "enum": [0.9, 0.95, 0.99],
                "default": 0.95,
            },
        },
        "required": ["project_name", "study_id", "object_id", "metric_id"],
        "additionalProperties": False,
    }


def plan_city_local_refinement_input_schema() -> JSONDict:
    return {
        "type": "object",
        "properties": {
            "project_name": {"type": "string"},
            "study_id": {"type": "string"},
            "object_id": {"type": "string"},
            "metric_id": {
                "type": "string",
                "enum": [
                    "peak_pressure_pa",
                    "pressure_impulse_pa_s",
                    "max_displacement_m",
                    "equivalent_stress_pa",
                    "damage_index",
                ],
            },
            "case_ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 64,
            },
            "confidence_level": {
                "type": "number",
                "enum": [0.9, 0.95, 0.99],
                "default": 0.95,
            },
            "refinement_factor": {
                "type": "number",
                "enum": [0.5, 0.67, 0.75],
                "default": 0.5,
            },
            "padding_cells": {
                "type": "integer",
                "minimum": 2,
                "maximum": 12,
                "default": 4,
            },
        },
        "required": ["project_name", "study_id", "object_id", "metric_id"],
        "additionalProperties": False,
    }


def train_city_surrogate_input_schema() -> JSONDict:
    return {
        "type": "object",
        "properties": {
            "project_name": {"type": "string"},
            "study_id": {"type": "string"},
            "object_id": {"type": "string"},
            "metric_id": {
                "type": "string",
                "enum": [
                    "peak_pressure_pa",
                    "pressure_impulse_pa_s",
                    "max_displacement_m",
                    "equivalent_stress_pa",
                    "damage_index",
                ],
            },
            "case_ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 64,
            },
            "confidence_level": {
                "type": "number",
                "enum": [0.9, 0.95, 0.99],
                "default": 0.95,
            },
            "neighbor_count": {
                "type": "integer",
                "enum": [1, 2, 3],
                "default": 1,
            },
            "max_normalized_rmse": {
                "type": "number",
                "enum": [0.15, 0.25, 0.35, 0.5],
                "default": 0.25,
            },
        },
        "required": ["project_name", "study_id", "object_id", "metric_id"],
        "additionalProperties": False,
    }


def predict_city_surrogate_input_schema() -> JSONDict:
    return {
        "type": "object",
        "properties": {
            "project_name": {"type": "string"},
            "study_id": {"type": "string"},
            "object_id": {"type": "string"},
            "metric_id": {
                "type": "string",
                "enum": [
                    "peak_pressure_pa",
                    "pressure_impulse_pa_s",
                    "max_displacement_m",
                    "equivalent_stress_pa",
                    "damage_index",
                ],
            },
            "parameters": {
                "type": "object",
                "properties": {
                    "tnt_mass_kg": {"type": "number"},
                    "tnt_diameter_m": {"type": "number"},
                    "blast_center_x_m": {"type": "number"},
                    "blast_center_y_m": {"type": "number"},
                    "blast_center_z_m": {"type": "number"},
                    "near_mesh_size_m": {"type": "number"},
                    "end_time_s": {"type": "number"},
                },
                "additionalProperties": False,
            },
        },
        "required": [
            "project_name",
            "study_id",
            "object_id",
            "metric_id",
            "parameters",
        ],
        "additionalProperties": False,
    }


def rank_city_protection_options_input_schema() -> JSONDict:
    metric_enum = [
        "peak_pressure_pa",
        "pressure_impulse_pa_s",
        "max_displacement_m",
        "equivalent_stress_pa",
        "damage_index",
    ]
    objective = {
        "type": "object",
        "properties": {
            "object_id": {"type": "string"},
            "metric_id": {"type": "string", "enum": metric_enum},
            "weight": {"type": "number", "exclusiveMinimum": 0.0},
        },
        "required": ["object_id", "metric_id", "weight"],
        "additionalProperties": False,
    }
    metric_limit = {
        "type": "object",
        "properties": {
            "object_id": {"type": "string"},
            "metric_id": {"type": "string", "enum": metric_enum},
            "maximum_value": {"type": "number"},
        },
        "required": ["object_id", "metric_id", "maximum_value"],
        "additionalProperties": False,
    }
    option = {
        "type": "object",
        "properties": {
            "option_id": {"type": "string"},
            "label": {"type": "string"},
            "case_id": {"type": "string"},
            "measure_type": {
                "type": "string",
                "enum": [
                    "increase_standoff",
                    "blast_barrier",
                    "entrance_reorientation",
                    "vehicle_evacuation",
                    "combined",
                    "other_validated",
                ],
            },
            "incremental_cost": {
                "type": "object",
                "properties": {
                    "value": {"type": "number", "minimum": 0.0},
                    "unit": {"type": "string"},
                },
                "required": ["value", "unit"],
                "additionalProperties": False,
            },
            "physical_basis": {"type": "string"},
            "constraints": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 16,
            },
        },
        "required": [
            "option_id",
            "label",
            "case_id",
            "measure_type",
            "incremental_cost",
            "physical_basis",
            "constraints",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "project_name": {"type": "string"},
            "study_id": {"type": "string"},
            "baseline_case_id": {"type": "string"},
            "objectives": {
                "type": "array",
                "items": objective,
                "minItems": 1,
                "maxItems": MAX_PROTECTION_OBJECTIVES,
            },
            "options": {
                "type": "array",
                "items": option,
                "minItems": 1,
                "maxItems": MAX_PROTECTION_OPTIONS,
            },
            "effectiveness_weight": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.7,
            },
            "cost_weight": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.3,
            },
            "budget_limit": {"type": "number", "minimum": 0.0},
            "metric_limits": {
                "type": "array",
                "items": metric_limit,
                "maxItems": 16,
            },
            "minimum_benefit_fraction": {
                "type": "number",
                "minimum": -1.0,
                "maximum": 1.0,
                "default": 0.0,
            },
            "allow_mixed_mesh": {"type": "boolean", "default": False},
            "allow_semantic_variants": {
                "type": "boolean",
                "default": False,
            },
        },
        "required": [
            "project_name",
            "study_id",
            "baseline_case_id",
            "objectives",
            "options",
        ],
        "additionalProperties": False,
    }


def tool_prepare_city_case_matrix(args: JSONDict) -> JSONDict:
    return create_controlled_case_matrix(
        find_project_dir(str(args["project_name"])),
        str(args["study_id"]),
        args["dimensions"],
    )


def tool_authorize_city_case_batch(args: JSONDict) -> JSONDict:
    return authorize_case_batch(
        find_project_dir(str(args["project_name"])),
        str(args["study_id"]),
        args["case_ids"],
        str(args["approval_text"]),
    )


def tool_register_city_case_result(args: JSONDict) -> JSONDict:
    return register_case_result(
        find_project_dir(str(args["project_name"])),
        str(args["study_id"]),
        str(args["case_id"]),
        find_project_dir(str(args["result_project_name"])),
        replace=args.get("replace") is True,
    )


def tool_compare_city_case_results(args: JSONDict) -> JSONDict:
    return compare_case_results(
        find_project_dir(str(args["project_name"])),
        str(args["study_id"]),
        str(args["object_id"]),
        case_ids=args.get("case_ids"),
        allow_mixed_mesh=args.get("allow_mixed_mesh") is True,
    )


def tool_analyze_city_case_uncertainty(args: JSONDict) -> JSONDict:
    return analyze_case_uncertainty(
        find_project_dir(str(args["project_name"])),
        str(args["study_id"]),
        str(args["object_id"]),
        str(args["metric_id"]),
        case_ids=args.get("case_ids"),
        confidence_level=float(args.get("confidence_level", 0.95)),
    )


def tool_plan_city_local_refinement(args: JSONDict) -> JSONDict:
    return plan_local_refinement(
        find_project_dir(str(args["project_name"])),
        str(args["study_id"]),
        str(args["object_id"]),
        str(args["metric_id"]),
        case_ids=args.get("case_ids"),
        confidence_level=float(args.get("confidence_level", 0.95)),
        refinement_factor=float(args.get("refinement_factor", 0.5)),
        padding_cells=int(args.get("padding_cells", 4)),
    )


def tool_train_city_surrogate(args: JSONDict) -> JSONDict:
    return train_surrogate_model(
        find_project_dir(str(args["project_name"])),
        str(args["study_id"]),
        str(args["object_id"]),
        str(args["metric_id"]),
        case_ids=args.get("case_ids"),
        confidence_level=float(args.get("confidence_level", 0.95)),
        neighbor_count=int(args.get("neighbor_count", 1)),
        max_normalized_rmse=float(args.get("max_normalized_rmse", 0.25)),
    )


def tool_predict_city_surrogate(args: JSONDict) -> JSONDict:
    return predict_surrogate_response(
        find_project_dir(str(args["project_name"])),
        str(args["study_id"]),
        str(args["object_id"]),
        str(args["metric_id"]),
        args["parameters"],
    )


def tool_rank_city_protection_options(args: JSONDict) -> JSONDict:
    return rank_protection_options(
        find_project_dir(str(args["project_name"])),
        str(args["study_id"]),
        str(args["baseline_case_id"]),
        args["objectives"],
        args["options"],
        effectiveness_weight=float(args.get("effectiveness_weight", 0.7)),
        cost_weight=float(args.get("cost_weight", 0.3)),
        budget_limit=(
            float(args["budget_limit"])
            if "budget_limit" in args
            else None
        ),
        metric_limits=args.get("metric_limits"),
        minimum_benefit_fraction=float(
            args.get("minimum_benefit_fraction", 0.0)
        ),
        allow_mixed_mesh=args.get("allow_mixed_mesh") is True,
        allow_semantic_variants=(
            args.get("allow_semantic_variants") is True
        ),
    )
