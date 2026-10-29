from __future__ import annotations

from lsprepost_mcp.config import JSONDict
from lsprepost_mcp.tool_phase16b import (
    tool_analyze_city_case_uncertainty,
    tool_authorize_city_case_batch,
    tool_compare_city_case_results,
    tool_plan_city_local_refinement,
    tool_predict_city_surrogate,
    tool_prepare_city_case_matrix,
    tool_rank_city_protection_options,
    tool_register_city_case_result,
    tool_train_city_surrogate,
)


def prepare_city_case_matrix_payload(payload: JSONDict) -> JSONDict:
    return tool_prepare_city_case_matrix(payload)


def authorize_city_case_batch_payload(payload: JSONDict) -> JSONDict:
    return tool_authorize_city_case_batch(payload)


def register_city_case_result_payload(payload: JSONDict) -> JSONDict:
    return tool_register_city_case_result(payload)


def compare_city_case_results_payload(payload: JSONDict) -> JSONDict:
    return tool_compare_city_case_results(payload)


def analyze_city_case_uncertainty_payload(payload: JSONDict) -> JSONDict:
    return tool_analyze_city_case_uncertainty(payload)


def plan_city_local_refinement_payload(payload: JSONDict) -> JSONDict:
    return tool_plan_city_local_refinement(payload)


def train_city_surrogate_payload(payload: JSONDict) -> JSONDict:
    return tool_train_city_surrogate(payload)


def predict_city_surrogate_payload(payload: JSONDict) -> JSONDict:
    return tool_predict_city_surrogate(payload)


def rank_city_protection_options_payload(payload: JSONDict) -> JSONDict:
    return tool_rank_city_protection_options(payload)
