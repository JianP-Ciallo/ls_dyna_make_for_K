from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import uuid
from pathlib import Path
from typing import Any

from lsprepost_mcp.artifacts import artifact_path
from lsprepost_mcp.city_layout_contract import (
    city_editor_state_fingerprint,
    city_layout_fingerprint,
)
from lsprepost_mcp.city_result_source import resolve_city_result_source
from lsprepost_mcp.config import JSONDict
from lsprepost_mcp.io import read_json, write_json
from lsprepost_mcp.locks import ProjectLock
from lsprepost_mcp.solver_results import parse_city_object_responses, parse_dbfsi


CITY_IMPACT_SCHEMA_VERSION = "phase16a.city_impact.v1"
CITY_METRICS_SCHEMA_VERSION = "phase17.city_object_metrics.v2"
LEGACY_CITY_METRICS_SCHEMA_VERSION = "phase16a.city_object_metrics.v1"
MINIMUM_TIME_COVERAGE_RATIO = 0.99
MINIMUM_POST_ARRIVAL_OBSERVATION_S = 0.020
MINIMUM_FSI_PRESSURE_RISE_PA = 100.0
MINIMUM_FSI_POSITIVE_SAMPLE_COUNT = 2

SEMANTIC_GROUPS: dict[str, JSONDict] = {
    "commercial_supermarket": {"label": "商业超市", "category": "commercial_building"},
    "residential_community": {"label": "住宅小区", "category": "residential_building"},
    "subway_entrance": {"label": "地铁入口", "category": "transport_entrance"},
    "parked_vehicles": {"label": "停放车辆", "category": "vehicle", "expand_parts": True},
    "traffic_lights": {"label": "交通灯", "category": "street_equipment", "expand_parts": True},
    "concrete_roads": {"label": "混凝土道路", "category": "road"},
    "ground_foundation": {"label": "城市地基", "category": "foundation"},
    "parking_lot": {"label": "停车场", "category": "parking_area"},
    "protection_boxes": {
        "label": "钢制防护箱",
        "category": "street_equipment",
        "expand_parts": True,
    },
}

METRIC_DEFINITIONS: dict[str, JSONDict] = {
    "peak_pressure_pa": {"label": "峰值压力", "unit": "Pa"},
    "pressure_impulse_pa_s": {"label": "压力冲量", "unit": "Pa·s"},
    "max_displacement_m": {"label": "最大位移", "unit": "m"},
    "equivalent_stress_pa": {"label": "等效应力", "unit": "Pa"},
    "damage_index": {"label": "材料损伤指标", "unit": "1"},
    "peak_fsi_pressure_rise_pa": {"label": "FSI 峰值压力增量", "unit": "Pa"},
    "fsi_positive_pressure_impulse_pa_s": {
        "label": "FSI 正压力冲量",
        "unit": "Pa·s",
    },
    "peak_structural_pressure_pa": {"label": "结构压力峰值", "unit": "Pa"},
    "peak_principal_stress_pa": {"label": "主应力峰值", "unit": "Pa"},
    "peak_displacement_m": {"label": "最大位移", "unit": "m"},
    "fsi_arrival_time_s": {"label": "FSI 到达时间", "unit": "s"},
    "structural_arrival_time_s": {"label": "结构响应到达时间", "unit": "s"},
    "post_arrival_observation_s": {"label": "到达后观察时长", "unit": "s"},
    "structural_signal_to_noise_ratio": {"label": "结构响应信噪比", "unit": "1"},
    "pre_arrival_peak_structural_pressure_pa": {
        "label": "到达前结构压力峰值",
        "unit": "Pa",
    },
    "pre_arrival_peak_principal_stress_pa": {
        "label": "到达前主应力峰值",
        "unit": "Pa",
    },
}

RISK_LABELS = {
    "low": "低",
    "attention": "关注",
    "high": "较高",
    "severe": "严重",
    "unavailable": "无法评估",
}
RISK_ORDER = {"low": 0, "attention": 1, "high": 2, "severe": 3}
TRUSTED_THRESHOLD_STATUSES = {"reviewed", "user_confirmed"}
EVIDENCE_BOUND_LEGACY_METRIC_IDS = {
    "peak_pressure_pa",
    "pressure_impulse_pa_s",
    "max_displacement_m",
    "equivalent_stress_pa",
    "damage_index",
}


def build_city_impact_assessment(project_path: Path) -> JSONDict:
    project = project_path.resolve()
    model_path = project / "model.json"
    keyword_path = project / "model.k"
    if not model_path.is_file() or not keyword_path.is_file():
        raise FileNotFoundError("city impact assessment requires model.json and model.k")

    model = read_json(model_path)
    metadata = model.get("metadata", {})
    if not isinstance(metadata, dict) or metadata.get("model_type") != "city_street_blast_scene":
        raise ValueError("city impact assessment only supports city_street_blast_scene projects")

    model_sha256 = _sha256(keyword_path)
    resolved_spec = metadata.get("resolved_spec", {})
    if not isinstance(resolved_spec, dict):
        resolved_spec = {}
    try:
        layout_fingerprint = city_layout_fingerprint(resolved_spec, metadata)
        editor_state_fingerprint = city_editor_state_fingerprint(
            resolved_spec,
            metadata,
        )
    except ValueError:
        layout_fingerprint = None
        editor_state_fingerprint = None
    semantic_objects = _semantic_objects(metadata)
    required_response_object_ids = _required_response_object_ids(metadata)
    result_source = resolve_city_result_source(project)
    result_dir = _validated_result_dir(result_source)
    result_quality = _result_quality(
        result_dir,
        model,
        result_source.get("validation"),
    )
    diagnostics = (
        _matsum_diagnostics(result_dir / "matsum", semantic_objects)
        if result_dir is not None
        else {}
    )
    metrics_contract = _metrics_contract_for_source(
        project,
        result_dir,
        model_sha256,
        semantic_objects,
        required_response_object_ids,
        result_source,
    )
    revalidated_source = metrics_contract.pop("_revalidated_result_source", None)
    if isinstance(revalidated_source, dict):
        result_source = revalidated_source
    if metrics_contract.pop("_invalid_evidence", False):
        result_quality = _invalidate_result_quality(
            result_quality,
            metrics_contract.get("issues", []),
        )
    threshold_profile = metrics_contract.get("threshold_profile") if metrics_contract else None
    thresholds_ready = _threshold_profile_ready(
        threshold_profile,
        model,
        model_sha256,
    )
    metrics_by_object = metrics_contract.get("objects", {}) if metrics_contract else {}
    response_data = metrics_contract.get("response_data", {}) if metrics_contract else {}
    response_acceptance = _response_acceptance(
        result_quality,
        response_data,
        required_response_object_ids,
    )

    ready_for_risk = bool(
        response_acceptance["status"] == "passed"
        and metrics_contract
        and metrics_contract.get("valid")
        and thresholds_ready
    )
    objects = []
    anomalies: list[JSONDict] = []
    for item in semantic_objects:
        object_id = item["object_id"]
        acceptance = response_acceptance.get("objects", {}).get(object_id)
        assessed_object = _assess_object(
            item,
            metrics_by_object.get(object_id, {}),
            diagnostics.get(object_id, {}),
            threshold_profile,
            ready_for_risk and bool(acceptance and acceptance.get("status") == "passed"),
            response=response_data.get(object_id, {}),
            response_acceptance=acceptance,
        )
        objects.append(assessed_object)
        anomaly = _normalized_displacement_anomaly(item, response_data.get(object_id, {}))
        if anomaly is not None:
            anomalies.append(anomaly)
    assessed = sum(item["risk"]["level"] != "unavailable" for item in objects)

    if response_acceptance["status"] == "failed":
        status = "incomplete_solver_result"
    elif metrics_contract and not metrics_contract.get("valid"):
        status = "invalid_object_metrics"
    elif not thresholds_ready:
        status = "awaiting_threshold_profile"
    else:
        status = "ready"

    return {
        "ok": True,
        "operation": "city_impact_assessment",
        "schema_version": CITY_IMPACT_SCHEMA_VERSION,
        "project_name": project.name,
        "project_dir": str(project),
        "model_sha256": model_sha256,
        "layout_fingerprint": layout_fingerprint,
        "editor_state_fingerprint": editor_state_fingerprint,
        "result_source": _result_source_summary(result_source),
        "response_acceptance": response_acceptance,
        "anomalies": anomalies,
        "status": status,
        "status_label": _status_label(status),
        "ready_for_risk": ready_for_risk,
        "engineering_notice": (
            "风险等级仅在求解质量、对象指标和阈值来源同时通过门禁后生成；"
            "demo_unvalidated 阈值不得解释为工程认证结论。"
        ),
        "quality": result_quality,
        "metrics_contract": {
            "present": metrics_contract is not None,
            "valid": bool(metrics_contract and metrics_contract.get("valid")),
            "schema_version": (
                metrics_contract.get("schema_version")
                if metrics_contract
                else None
            ),
            "result_evidence_digest": (
                metrics_contract.get("result_evidence_digest")
                if metrics_contract
                else None
            ),
            "path": str(project / "artifacts" / "city_impact_metrics.json"),
            "issues": metrics_contract.get("issues", []) if metrics_contract else [
                "缺少可验证的对象级结果；全局 DBFSI 或 MATSUM 数据不能冒充单个建筑指标。"
            ],
        },
        "threshold_profile": threshold_profile or {
            "status": "missing",
            "source": "",
            "notice": "未提供经过说明的风险阈值，风险等级保持无法评估。",
        },
        "global_metrics": result_quality.get("global_metrics", {}),
        "object_count": len(objects),
        "assessed_object_count": assessed,
        "objects": objects,
        "part_risk": {
            str(part_id): item["risk"]["level"]
            for item in objects
            for part_id in item["part_ids"]
        },
    }


def write_city_impact_report(project_path: Path) -> JSONDict:
    assessment = build_city_impact_assessment(project_path)
    project = project_path.resolve()
    json_path = artifact_path(project, "city_impact_assessment.json", if_exists="overwrite")
    html_path = artifact_path(project, "city_impact_report.html", if_exists="overwrite")
    write_json(json_path, assessment)
    html_path.write_text(_render_report(assessment), encoding="utf-8")
    return {
        "ok": True,
        "operation": "write_city_impact_report",
        "project_name": project.name,
        "assessment_status": assessment["status"],
        "ready_for_risk": assessment["ready_for_risk"],
        "json_path": str(json_path),
        "html_path": str(html_path),
        "relative_json_path": str(json_path.relative_to(project)).replace("\\", "/"),
        "relative_html_path": str(html_path.relative_to(project)).replace("\\", "/"),
    }


def _semantic_objects(metadata: JSONDict) -> list[JSONDict]:
    explicit = metadata.get("semantic_objects")
    if isinstance(explicit, list) and explicit:
        rows = []
        for item in explicit:
            if not isinstance(item, dict):
                continue
            group_id = str(item.get("group_id", ""))
            definition = SEMANTIC_GROUPS.get(group_id)
            if not definition:
                continue
            part_ids = _positive_ints(item.get("part_ids"))
            if not part_ids:
                continue
            bounds = _optional_semantic_bounds(
                item.get("bounds_m"),
                str(item.get("object_id") or group_id),
            )
            rows.append(
                {
                    "object_id": str(item.get("object_id") or group_id),
                    "group_id": group_id,
                    "label": str(item.get("label") or definition["label"]),
                    "category": str(item.get("category") or definition["category"]),
                    "part_ids": part_ids,
                    "constraint_mode": str(item.get("constraint_mode", "unknown")),
                    **({"bounds_m": bounds} if bounds is not None else {}),
                }
            )
        if rows:
            return rows

    urban = metadata.get("urban_components")
    if not isinstance(urban, dict):
        raise ValueError("city model metadata is missing urban_components")
    rows: list[JSONDict] = []
    for group_id, definition in SEMANTIC_GROUPS.items():
        value = urban.get(group_id)
        if not isinstance(value, dict):
            continue
        part_ids = _positive_ints(value.get("part_ids"))
        if definition.get("expand_parts"):
            for index, part_id in enumerate(part_ids, start=1):
                object_id = f"{group_id[:-1]}_{index}"
                bounds = _optional_semantic_bounds(value.get("bounds_m"), object_id)
                rows.append(
                    {
                        "object_id": object_id,
                        "group_id": group_id,
                        "label": f"{definition['label']} {index}",
                        "category": definition["category"],
                        "part_ids": [part_id],
                        "constraint_mode": str(value.get("constraint_mode", "unknown")),
                        **({"bounds_m": bounds} if bounds is not None else {}),
                    }
                )
        elif part_ids:
            bounds = _optional_semantic_bounds(value.get("bounds_m"), group_id)
            rows.append(
                {
                    "object_id": group_id,
                    "group_id": group_id,
                    "label": definition["label"],
                    "category": definition["category"],
                    "part_ids": part_ids,
                    "constraint_mode": str(value.get("constraint_mode", "unknown")),
                    **({"bounds_m": bounds} if bounds is not None else {}),
                }
            )
    if not rows:
        raise ValueError("city model metadata has no assessable semantic objects")
    return rows


def _required_response_object_ids(metadata: JSONDict) -> list[str]:
    response_objects = metadata.get("response_objects")
    if not isinstance(response_objects, list) or not response_objects:
        raise ValueError("city model metadata has no response_objects")
    response_ids: list[str] = []
    for index, item in enumerate(response_objects):
        if not isinstance(item, dict):
            raise ValueError(f"response_objects[{index}] must be an object")
        object_id = item.get("object_id")
        if not isinstance(object_id, str) or not object_id.strip():
            raise ValueError(f"response_objects[{index}].object_id must be non-empty")
        if object_id in response_ids:
            raise ValueError(f"duplicate response object id: {object_id}")
        response_ids.append(object_id)

    explicit = metadata.get("required_response_object_ids")
    if explicit is None:
        return response_ids
    if not isinstance(explicit, list) or not explicit:
        raise ValueError("required_response_object_ids must be a non-empty array")
    required: list[str] = []
    for index, object_id in enumerate(explicit):
        if not isinstance(object_id, str) or not object_id.strip():
            raise ValueError(
                f"required_response_object_ids[{index}] must be non-empty"
            )
        if object_id in required:
            raise ValueError(f"duplicate required response object id: {object_id}")
        if object_id not in response_ids:
            raise ValueError(
                f"required response object is not defined in response_objects: {object_id}"
            )
        required.append(object_id)
    return required


def _optional_semantic_bounds(
    raw: object,
    object_id: str,
) -> JSONDict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"semantic object {object_id!r} bounds_m must be an object")
    lower = raw.get("min")
    upper = raw.get("max")
    if not isinstance(lower, list) or not isinstance(upper, list):
        raise ValueError(
            f"semantic object {object_id!r} bounds_m requires min/max arrays"
        )
    if len(lower) != 3 or len(upper) != 3:
        raise ValueError(
            f"semantic object {object_id!r} bounds_m must contain three axes"
        )
    normalized_lower: list[float] = []
    normalized_upper: list[float] = []
    for axis, (raw_lower, raw_upper) in enumerate(
        zip(lower, upper, strict=True)
    ):
        if (
            isinstance(raw_lower, bool)
            or isinstance(raw_upper, bool)
            or not isinstance(raw_lower, (int, float))
            or not isinstance(raw_upper, (int, float))
        ):
            raise ValueError(
                f"semantic object {object_id!r} bounds_m axis {axis} must be numeric"
            )
        low = float(raw_lower)
        high = float(raw_upper)
        if not math.isfinite(low) or not math.isfinite(high) or low > high:
            raise ValueError(
                f"semantic object {object_id!r} bounds_m axis {axis} is invalid"
            )
        normalized_lower.append(low)
        normalized_upper.append(high)
    return {"min": normalized_lower, "max": normalized_upper}


def _validated_result_dir(result_source: JSONDict) -> Path | None:
    validation = result_source.get("validation")
    raw_result_dir = result_source.get("result_dir")
    if (
        not isinstance(validation, dict)
        or validation.get("ok") is not True
        or not isinstance(raw_result_dir, str)
        or not raw_result_dir
    ):
        return None
    result_dir = Path(raw_result_dir).resolve()
    return result_dir if result_dir.is_dir() else None


def _result_source_summary(result_source: JSONDict) -> JSONDict:
    keys = (
        "schema_version",
        "source_kind",
        "result_dir",
        "run_id",
        "model_sha256",
        "model_json_sha256",
        "registered_at",
        "registered_by",
    )
    summary = {
        key: result_source[key]
        for key in keys
        if key in result_source
    }
    validation = result_source.get("validation")
    summary["validation"] = (
        validation
        if isinstance(validation, dict)
        else {"ok": False, "issues": ["result source validation is unavailable"]}
    )
    summary["evidence_digest"] = _result_evidence_digest(result_source)
    return summary


def _result_evidence_digest(result_source: JSONDict) -> str | None:
    evidence = result_source.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        return None
    serialized = json.dumps(
        evidence,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _metrics_contract_for_source(
    project: Path,
    result_dir: Path | None,
    model_sha256: str,
    semantic_objects: list[JSONDict],
    required_response_object_ids: list[str],
    result_source: JSONDict,
) -> JSONDict:
    evidence_digest = _result_evidence_digest(result_source)
    if result_dir is None or evidence_digest is None:
        legacy = _load_metrics_contract(project, model_sha256, semantic_objects)
        if (
            legacy is not None
            and legacy.get("schema_version") == LEGACY_CITY_METRICS_SCHEMA_VERSION
        ):
            return legacy
        validation = result_source.get("validation")
        issues = (
            list(validation.get("issues", []))
            if isinstance(validation, dict)
            else []
        )
        return {
            "schema_version": CITY_METRICS_SCHEMA_VERSION,
            "valid": False,
            "issues": issues or ["city result source evidence is unavailable"],
            "objects": {},
            "response_data": {},
            "result_evidence_digest": evidence_digest,
            "threshold_profile": _existing_threshold_profile(project),
        }

    try:
        result_model = read_json(result_dir / "model.json")
        result_metadata = result_model.get("metadata")
        response_objects = (
            result_metadata.get("response_objects")
            if isinstance(result_metadata, dict)
            else None
        )
        if not isinstance(response_objects, list) or not response_objects:
            raise ValueError("result model has no response_objects")
        required_ids = set(required_response_object_ids)
        selected_response_objects = [
            item
            for item in response_objects
            if isinstance(item, dict) and item.get("object_id") in required_ids
        ]
        responses = parse_city_object_responses(
            (result_dir / "dbfsi").read_text(encoding="utf-8", errors="replace"),
            (result_dir / "elout").read_text(encoding="utf-8", errors="replace"),
            (result_dir / "nodout").read_text(encoding="utf-8", errors="replace"),
            selected_response_objects,
        )
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {
            "schema_version": CITY_METRICS_SCHEMA_VERSION,
            "valid": False,
            "issues": [f"对象级结果解析失败：{exc}"],
            "objects": {},
            "response_data": {},
            "result_evidence_digest": evidence_digest,
            "threshold_profile": _existing_threshold_profile(project),
        }

    parsed_ids = set(responses)
    missing_ids = [
        object_id
        for object_id in required_response_object_ids
        if object_id not in parsed_ids
    ]
    unexpected_ids = sorted(parsed_ids - set(required_response_object_ids))
    complete_responses: dict[str, JSONDict] = {}
    for object_id in required_response_object_ids:
        response = responses.get(object_id)
        complete_responses[object_id] = (
            {
                **response,
                "result_present": True,
                "result_set_exact": not unexpected_ids,
            }
            if isinstance(response, dict)
            else {
                "object_id": object_id,
                "result_present": False,
                "result_set_exact": not unexpected_ids,
                "coverage_issue": "required object is missing from parsed results",
            }
        )

    revalidated_source = resolve_city_result_source(project)
    if not _same_result_source(result_source, revalidated_source):
        return {
            "schema_version": CITY_METRICS_SCHEMA_VERSION,
            "valid": False,
            "issues": [
                "invalid_evidence: city result source changed during assessment"
            ],
            "objects": {},
            "response_data": {
                object_id: {
                    "object_id": object_id,
                    "result_present": False,
                    "coverage_issue": "result source evidence changed before commit",
                }
                for object_id in required_response_object_ids
            },
            "result_evidence_digest": evidence_digest,
            "threshold_profile": _existing_threshold_profile(project),
            "_revalidated_result_source": revalidated_source,
            "_invalid_evidence": True,
        }

    payload: JSONDict = {
        "schema_version": CITY_METRICS_SCHEMA_VERSION,
        "model_sha256": model_sha256,
        "result_evidence_digest": evidence_digest,
        "source": "lsprepost_mcp.parse_city_object_responses",
        "required_response_object_ids": required_response_object_ids,
        "object_coverage": {
            "exact": not missing_ids and not unexpected_ids,
            "missing_object_ids": missing_ids,
            "unexpected_object_ids": unexpected_ids,
        },
        "objects": complete_responses,
    }
    payload = _write_generated_metrics(project, payload)
    return _normalize_metrics_contract(
        payload,
        model_sha256,
        semantic_objects,
        expected_evidence_digest=evidence_digest,
    )


def _same_result_source(first: JSONDict, second: JSONDict) -> bool:
    first_validation = first.get("validation")
    second_validation = second.get("validation")
    if (
        not isinstance(first_validation, dict)
        or first_validation.get("ok") is not True
        or not isinstance(second_validation, dict)
        or second_validation.get("ok") is not True
    ):
        return False
    identity_fields = (
        "schema_version",
        "source_kind",
        "result_dir",
        "run_id",
        "model_sha256",
        "model_json_sha256",
    )
    if any(first.get(field) != second.get(field) for field in identity_fields):
        return False
    first_digest = _result_evidence_digest(first)
    return first_digest is not None and first_digest == _result_evidence_digest(second)


def _invalidate_result_quality(
    result_quality: JSONDict,
    issues: object,
) -> JSONDict:
    issue_rows = (
        [str(item) for item in issues]
        if isinstance(issues, list)
        else [str(issues)]
    )
    checks: list[JSONDict] = []
    for check in result_quality.get("checks", []):
        if not isinstance(check, dict):
            continue
        if check.get("id") == "result_source.valid":
            checks.append(
                {
                    **check,
                    "ok": False,
                    "message": "; ".join(issue_rows),
                }
            )
        else:
            checks.append(dict(check))
    checks.append(
        _quality_check(
            "result_source.invalid_evidence",
            False,
            "; ".join(issue_rows),
        )
    )
    blocking = [
        *[
            str(check_id)
            for check_id in result_quality.get("blocking_check_ids", [])
            if check_id != "result_source.valid"
        ],
        "result_source.valid",
        "result_source.invalid_evidence",
    ]
    return {
        **result_quality,
        "ready_for_object_assessment": False,
        "checks": checks,
        "blocking_check_ids": list(dict.fromkeys(blocking)),
    }


def _write_generated_metrics(project: Path, payload: JSONDict) -> JSONDict:
    path = project / "artifacts" / "city_impact_metrics.json"
    with ProjectLock(project.name, namespace="city_impact_metrics"):
        threshold_profile = _existing_threshold_profile(project)
        preserved_metrics = _evidence_bound_legacy_metrics(path, payload)
        objects = {
            object_id: {
                **values,
                **preserved_metrics.get(object_id, {}),
            }
            for object_id, values in payload.get("objects", {}).items()
            if isinstance(values, dict)
        }
        complete_payload = {
            **payload,
            "objects": objects,
            "threshold_profile": threshold_profile,
        }
        _write_json_atomic(path, complete_payload)
    return complete_payload


def _evidence_bound_legacy_metrics(
    path: Path,
    payload: JSONDict,
) -> dict[str, JSONDict]:
    if not path.is_file():
        return {}
    try:
        existing = read_json(path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if (
        not isinstance(existing, dict)
        or existing.get("schema_version") != CITY_METRICS_SCHEMA_VERSION
        or existing.get("model_sha256") != payload.get("model_sha256")
        or existing.get("result_evidence_digest")
        != payload.get("result_evidence_digest")
    ):
        return {}
    existing_objects = existing.get("objects")
    generated_objects = payload.get("objects")
    if not isinstance(existing_objects, dict) or not isinstance(generated_objects, dict):
        return {}
    preserved: dict[str, JSONDict] = {}
    for object_id in generated_objects:
        values = existing_objects.get(object_id)
        if not isinstance(values, dict):
            continue
        rows = {
            metric_id: value
            for metric_id, value in values.items()
            if metric_id in EVIDENCE_BOUND_LEGACY_METRIC_IDS
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        }
        if rows:
            preserved[object_id] = rows
    return preserved


def _existing_threshold_profile(project: Path) -> JSONDict:
    path = project / "artifacts" / "city_impact_metrics.json"
    if path.is_file():
        try:
            raw = read_json(path)
            profile = raw.get("threshold_profile")
            if isinstance(profile, dict):
                return profile
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    return {
        "status": "missing",
        "source": "",
        "limits": {},
        "notice": "未提供经过说明且适用于当前模型的工程风险阈值。",
    }


def _write_json_atomic(path: Path, payload: JSONDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _result_quality(
    result_dir: Path | None,
    model: JSONDict,
    source_validation: object,
) -> JSONDict:
    source_ok = bool(
        isinstance(source_validation, dict)
        and source_validation.get("ok") is True
        and result_dir is not None
    )
    d3hsp = _scan_d3hsp(result_dir / "d3hsp") if result_dir else _scan_d3hsp(Path())
    requested_end_time = _requested_end_time(model)
    actual_time = float(d3hsp.get("problem_time_s") or 0.0)
    coverage = actual_time / requested_end_time if requested_end_time > 0.0 else 0.0
    dbfsi_result: JSONDict | None = None
    dbfsi_issue = ""
    dbfsi_path = result_dir / "dbfsi" if result_dir else None
    if dbfsi_path is not None and dbfsi_path.is_file() and dbfsi_path.stat().st_size > 0:
        try:
            dbfsi_result = parse_dbfsi(dbfsi_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError, TypeError) as exc:
            dbfsi_issue = str(exc)
    else:
        dbfsi_issue = "dbfsi 不存在或为空"

    energy = _parse_glstat(result_dir / "glstat") if result_dir else {
        "available": False,
        "summary": "glstat 不存在",
    }
    source_issues = (
        source_validation.get("issues", [])
        if isinstance(source_validation, dict)
        else []
    )
    checks = [
        _quality_check(
            "result_source.valid",
            source_ok,
            "结果源证据有效"
            if source_ok
            else f"结果源证据无效：{'; '.join(str(item) for item in source_issues)}",
        ),
        _quality_check(
            "solver.no_input_error",
            bool(d3hsp.get("available") and d3hsp["error_count"] == 0),
            "Keyword/求解器输入无错误",
        ),
        _quality_check("solver.normal_termination", d3hsp["normal_termination"], "求解器正常终止"),
        _quality_check(
            "solver.complete_time_coverage",
            coverage >= MINIMUM_TIME_COVERAGE_RATIO,
            f"结果覆盖 {actual_time:.6g} s / 计划 {requested_end_time:.6g} s",
        ),
        _quality_check(
            "solver.fsi_output",
            bool(dbfsi_result and dbfsi_result.get("state_count", 0) >= 2),
            "FSI 历史可读取" if dbfsi_result else f"FSI 历史不可用：{dbfsi_issue}",
        ),
        _quality_check(
            "solver.energy_sanity",
            bool(energy.get("available") and energy.get("max_energy_ratio_deviation", math.inf) <= 0.1),
            energy.get("summary", "GLSTAT 能量记录不可用"),
        ),
    ]
    blocking = [item["id"] for item in checks if not item["ok"]]
    global_metrics: JSONDict = {
        "problem_time_s": actual_time,
        "planned_end_time_s": requested_end_time,
        "time_coverage_ratio": coverage,
        "problem_cycle": d3hsp.get("problem_cycle", 0),
        "termination": d3hsp.get("termination", "unknown"),
        "energy": energy,
    }
    if dbfsi_result:
        surfaces = dbfsi_result.get("surfaces", [])
        pressure_rises = [
            float(item["peak_pressure_rise_pa"])
            for item in surfaces
            if isinstance(item, dict)
            and isinstance(item.get("peak_pressure_rise_pa"), (int, float))
        ]
        pressure_impulses = [
            float(item["positive_pressure_impulse_pa_s"])
            for item in surfaces
            if isinstance(item, dict)
            and isinstance(item.get("positive_pressure_impulse_pa_s"), (int, float))
        ]
        force_impulses = [
            float(item["fsi_impulse_magnitude_n_s"])
            for item in surfaces
            if isinstance(item, dict)
            and isinstance(item.get("fsi_impulse_magnitude_n_s"), (int, float))
        ]
        global_metrics["fsi"] = {
            "surface_count": dbfsi_result["surface_count"],
            "state_count": dbfsi_result["state_count"],
            "peak_pressure_rise_pa": max(pressure_rises, default=None),
            "positive_pressure_impulse_pa_s": sum(pressure_impulses),
            "summed_surface_force_impulse_magnitude_n_s": sum(force_impulses),
            "notice": "全局值由所有 DBFSI surface 汇总；对象值仍按 response_objects 独立绑定。",
        }
    return {
        "ready_for_object_assessment": not blocking,
        "checks": checks,
        "blocking_check_ids": blocking,
        "warning_count": d3hsp["warning_count"],
        "warning_codes": d3hsp["warning_codes"],
        "global_metrics": global_metrics,
    }


def _load_metrics_contract(
    project: Path,
    model_sha256: str,
    semantic_objects: list[JSONDict],
    *,
    expected_evidence_digest: str | None = None,
) -> JSONDict | None:
    path = project / "artifacts" / "city_impact_metrics.json"
    if not path.is_file():
        return None
    try:
        raw = read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "issues": [f"对象指标文件无法读取：{exc}"], "objects": {}}
    return _normalize_metrics_contract(
        raw,
        model_sha256,
        semantic_objects,
        expected_evidence_digest=expected_evidence_digest,
    )


def _normalize_metrics_contract(
    raw: JSONDict,
    model_sha256: str,
    semantic_objects: list[JSONDict],
    *,
    expected_evidence_digest: str | None = None,
) -> JSONDict:
    issues: list[str] = []
    schema_version = raw.get("schema_version")
    if schema_version not in {
        CITY_METRICS_SCHEMA_VERSION,
        LEGACY_CITY_METRICS_SCHEMA_VERSION,
    }:
        issues.append("对象指标 schema_version 不受支持")
    if raw.get("model_sha256") != model_sha256:
        issues.append("对象指标对应的 model.k 哈希与当前项目不一致")
    if (
        schema_version == CITY_METRICS_SCHEMA_VERSION
        and expected_evidence_digest is not None
        and raw.get("result_evidence_digest") != expected_evidence_digest
    ):
        issues.append("对象指标对应的结果证据摘要与当前结果源不一致")
    raw_objects = raw.get("objects")
    if not isinstance(raw_objects, dict):
        issues.append("对象指标 objects 必须是对象")
        raw_objects = {}
    known_ids = {item["object_id"] for item in semantic_objects}
    unknown = sorted(set(raw_objects) - known_ids)
    if unknown:
        issues.append(f"对象指标包含未知语义对象：{', '.join(unknown)}")
    normalized: dict[str, JSONDict] = {}
    response_data: dict[str, JSONDict] = {}
    for object_id, values in raw_objects.items():
        if object_id not in known_ids or not isinstance(values, dict):
            continue
        normalized[object_id] = {}
        if schema_version == CITY_METRICS_SCHEMA_VERSION:
            response_data[object_id] = dict(values)
        for metric_id, definition in METRIC_DEFINITIONS.items():
            if metric_id not in values:
                continue
            value = values[metric_id]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                issues.append(f"{object_id}.{metric_id} 必须是数值")
                continue
            number = float(value)
            if not math.isfinite(number) or number < 0.0:
                issues.append(f"{object_id}.{metric_id} 必须是有限非负数")
                continue
            normalized[object_id][metric_id] = {
                "value": number,
                "unit": definition["unit"],
                "source": str(raw.get("source", "external_postprocessor")),
            }
        if schema_version == CITY_METRICS_SCHEMA_VERSION:
            _add_legacy_metric_aliases(normalized[object_id])
    return {
        "schema_version": schema_version,
        "valid": not issues,
        "issues": issues,
        "objects": normalized,
        "response_data": response_data,
        "threshold_profile": raw.get("threshold_profile"),
        "source": str(raw.get("source", "")),
        "result_evidence_digest": raw.get("result_evidence_digest"),
    }


def _add_legacy_metric_aliases(metrics: JSONDict) -> None:
    aliases = {
        "peak_pressure_pa": "peak_structural_pressure_pa",
        "pressure_impulse_pa_s": "fsi_positive_pressure_impulse_pa_s",
        "max_displacement_m": "peak_displacement_m",
    }
    for legacy_id, current_id in aliases.items():
        if legacy_id in metrics or current_id not in metrics:
            continue
        metrics[legacy_id] = {
            **metrics[current_id],
            "alias_of": current_id,
        }


def _response_acceptance(
    result_quality: JSONDict,
    response_data: dict[str, JSONDict],
    required_response_object_ids: list[str],
) -> JSONDict:
    objects = {
        object_id: _object_response_acceptance(
            object_id,
            response_data.get(
                object_id,
                {
                    "object_id": object_id,
                    "result_present": False,
                    "coverage_issue": "required object has no parsed result",
                },
            ),
        )
        for object_id in required_response_object_ids
    }
    quality_blocking = list(result_quality.get("blocking_check_ids", []))
    object_blocking = [
        check_id
        for item in objects.values()
        for check_id in item["blocking_check_ids"]
    ]
    passed_count = sum(item["status"] == "passed" for item in objects.values())
    if quality_blocking or not objects or passed_count == 0:
        status = "failed"
    elif passed_count == len(objects):
        status = "passed"
    else:
        status = "partial"
    return {
        "status": status,
        "status_label": {
            "passed": "数值响应验收通过",
            "partial": "数值响应验收部分通过",
            "failed": "数值响应验收未通过",
        }[status],
        "required_object_count": len(objects),
        "passed_object_count": passed_count,
        "blocking_check_ids": [*quality_blocking, *object_blocking],
        "objects": objects,
        "notice": "数值响应验收不等同于工程风险等级或材料失效结论。",
    }


def _object_response_acceptance(object_id: str, response: JSONDict) -> JSONDict:
    fsi_arrival = _optional_finite_number(response.get("fsi_arrival_time_s"))
    structural_arrival = _optional_finite_number(
        response.get("structural_arrival_time_s")
    )
    displacement = _optional_finite_number(response.get("peak_displacement_m"))
    observation = _optional_finite_number(
        response.get("post_arrival_observation_s")
    )
    checks = [
        _quality_check(
            f"{object_id}.result_present",
            response.get("result_present") is True,
            "required object result is present",
        ),
        _quality_check(
            f"{object_id}.result_set_exact",
            response.get("result_set_exact") is True,
            "parsed object IDs exactly match the required response contract",
        ),
        _quality_check(
            f"{object_id}.fsi_surface",
            response.get("fsi_present") is True,
            "对象 FSI surface 已绑定",
        ),
        _quality_check(
            f"{object_id}.fsi_pressure_signal",
            _number_at_least(
                response.get("peak_fsi_pressure_rise_pa"),
                MINIMUM_FSI_PRESSURE_RISE_PA,
            ),
            f"FSI 压力增量不低于 {MINIMUM_FSI_PRESSURE_RISE_PA:g} Pa",
        ),
        _quality_check(
            f"{object_id}.fsi_positive_samples",
            _integer_at_least(
                response.get("fsi_positive_pressure_sample_count"),
                MINIMUM_FSI_POSITIVE_SAMPLE_COUNT,
            ),
            f"至少 {MINIMUM_FSI_POSITIVE_SAMPLE_COUNT} 个有效正压力样本",
        ),
        _quality_check(
            f"{object_id}.fsi_positive_impulse",
            _number_greater_than(
                response.get("fsi_positive_pressure_impulse_pa_s"),
                0.0,
            ),
            "FSI 正压力冲量大于零",
        ),
        _quality_check(
            f"{object_id}.structural_pressure",
            response.get("structural_stress_present") is True
            and _number_greater_than(
                response.get("post_arrival_peak_structural_pressure_pa"),
                MINIMUM_FSI_PRESSURE_RISE_PA,
            ),
            "FSI 到达后结构压力超过数值噪声下限",
        ),
        _quality_check(
            f"{object_id}.principal_stress",
            response.get("structural_stress_present") is True
            and _number_greater_than(
                response.get("post_arrival_peak_principal_stress_pa"),
                MINIMUM_FSI_PRESSURE_RISE_PA,
            ),
            "FSI 到达后主应力超过数值噪声下限",
        ),
        _quality_check(
            f"{object_id}.pre_arrival_quiet",
            response.get("pre_arrival_quiet") is True,
            "FSI 到达前结构响应保持安静",
        ),
        _quality_check(
            f"{object_id}.response_causality",
            fsi_arrival is not None
            and structural_arrival is not None
            and structural_arrival + 1.0e-12 >= fsi_arrival,
            "结构响应不早于 FSI 到达且满足连续状态门禁",
        ),
        _quality_check(
            f"{object_id}.displacement",
            response.get("displacement_present") is True
            and displacement is not None
            and displacement >= 0.0,
            "对象位移为有限非负值",
        ),
        _quality_check(
            f"{object_id}.observation_window",
            observation is not None
            and observation + 1.0e-12 >= MINIMUM_POST_ARRIVAL_OBSERVATION_S,
            (
                f"FSI 到达后观察时长不少于 "
                f"{MINIMUM_POST_ARRIVAL_OBSERVATION_S:.3f} s"
            ),
        ),
    ]
    blocking = [item["id"] for item in checks if not item["ok"]]
    return {
        "status": "passed" if not blocking else "failed",
        "checks": checks,
        "blocking_check_ids": blocking,
    }


def _normalized_displacement_anomaly(
    semantic: JSONDict,
    response: JSONDict,
) -> JSONDict | None:
    bounds = semantic.get("bounds_m")
    displacement = _optional_finite_number(response.get("peak_displacement_m"))
    if not isinstance(bounds, dict) or displacement is None:
        return None
    lower = bounds.get("min")
    upper = bounds.get("max")
    if not isinstance(lower, list) or not isinstance(upper, list):
        return None
    dimensions = [
        float(high) - float(low)
        for low, high in zip(lower, upper, strict=True)
    ]
    characteristic_size = max(dimensions, default=0.0)
    if characteristic_size <= 0.0:
        return None
    ratio = displacement / characteristic_size
    limit = 0.02 if semantic.get("category") == "street_equipment" else 0.05
    if ratio <= limit:
        return None
    return {
        "id": f"{semantic['object_id']}.normalized_displacement",
        "object_id": semantic["object_id"],
        "severity": "warning",
        "blocking": False,
        "normalized_displacement": ratio,
        "limit": limit,
        "peak_displacement_m": displacement,
        "characteristic_size_m": characteristic_size,
        "message": "归一化位移偏大，需要复核约束、截面、材料和网格。",
        "notice": "该项是模型健全性告警，不是材料失效判据。",
    }


def _optional_finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _number_at_least(value: object, minimum: float) -> bool:
    number = _optional_finite_number(value)
    return number is not None and number >= minimum


def _number_greater_than(value: object, minimum: float) -> bool:
    number = _optional_finite_number(value)
    return number is not None and number > minimum


def _integer_at_least(value: object, minimum: int) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= minimum
    )


def _threshold_profile_ready(
    profile: object,
    model: JSONDict,
    model_sha256: str,
) -> bool:
    if not isinstance(profile, dict):
        return False
    if profile.get("status") not in TRUSTED_THRESHOLD_STATUSES:
        return False
    if not isinstance(profile.get("source"), str) or not profile["source"].strip():
        return False
    limits = profile.get("limits")
    if not isinstance(limits, dict) or not limits:
        return False
    binding = profile.get("binding")
    if not isinstance(binding, dict):
        return False
    if binding.get("model_sha256") != model_sha256:
        return False
    material_sha256 = _material_contract_sha256(model)
    if material_sha256 is None or binding.get("material_sha256") != material_sha256:
        return False
    applicability = binding.get("applicability")
    metadata = model.get("metadata")
    if not isinstance(applicability, dict) or not isinstance(metadata, dict):
        return False
    if applicability.get("model_type") != metadata.get("model_type"):
        return False
    categories = applicability.get("categories")
    if (
        not isinstance(categories, list)
        or not categories
        or any(not isinstance(item, str) or not item for item in categories)
        or len(set(categories)) != len(categories)
    ):
        return False
    explicit_limit_categories = set(limits) - {"default"}
    return explicit_limit_categories.issubset(set(categories))


def _material_contract_sha256(model: JSONDict) -> str | None:
    spec = model.get("spec")
    material = spec.get("material") if isinstance(spec, dict) else None
    if not isinstance(material, dict) or not material:
        return None
    serialized = json.dumps(
        material,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _assess_object(
    semantic: JSONDict,
    metrics: JSONDict,
    diagnostics: JSONDict,
    threshold_profile: object,
    ready_for_risk: bool,
    *,
    response: JSONDict | None = None,
    response_acceptance: JSONDict | None = None,
) -> JSONDict:
    metric_rows: dict[str, JSONDict] = {}
    for metric_id, definition in METRIC_DEFINITIONS.items():
        value = metrics.get(metric_id)
        if isinstance(value, dict):
            metric_rows[metric_id] = {
                "available": True,
                "label": definition["label"],
                **value,
            }
        else:
            metric_rows[metric_id] = {
                "available": False,
                "label": definition["label"],
                "unit": definition["unit"],
                "reason": "对象级后处理指标尚未提供",
            }

    risk = {
        "level": "unavailable",
        "label": RISK_LABELS["unavailable"],
        "basis": [],
        "notice": "求解质量、对象指标或阈值来源未通过门禁。",
    }
    if ready_for_risk and isinstance(threshold_profile, dict):
        risk = _classify_risk(semantic["category"], metric_rows, threshold_profile)

    return {
        **semantic,
        "metrics": metric_rows,
        "response": response or {},
        "response_acceptance": response_acceptance or {
            "status": "not_required",
            "checks": [],
            "blocking_check_ids": [],
        },
        "diagnostics": diagnostics,
        "risk": risk,
    }


def _classify_risk(category: str, metrics: JSONDict, profile: JSONDict) -> JSONDict:
    binding = profile.get("binding")
    applicability = binding.get("applicability") if isinstance(binding, dict) else None
    categories = (
        applicability.get("categories")
        if isinstance(applicability, dict)
        else None
    )
    if not isinstance(categories, list) or category not in categories:
        return {
            "level": "unavailable",
            "label": RISK_LABELS["unavailable"],
            "basis": [],
            "notice": f"threshold profile is not bound to object category {category}.",
        }
    limits = profile.get("limits", {})
    category_limits = limits.get(category) or limits.get("default")
    if not isinstance(category_limits, dict):
        return {
            "level": "unavailable",
            "label": RISK_LABELS["unavailable"],
            "basis": [],
            "notice": f"阈值档案不适用于对象类型 {category}。",
        }
    level = "low"
    basis = []
    for metric_id, metric in metrics.items():
        if not metric.get("available"):
            continue
        thresholds = category_limits.get(metric_id)
        if not isinstance(thresholds, dict):
            continue
        values = [thresholds.get(name) for name in ("attention", "high", "severe")]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
            continue
        attention, high, severe = (float(value) for value in values)
        if not (0.0 <= attention < high < severe):
            continue
        number = float(metric["value"])
        metric_level = (
            "severe" if number >= severe
            else "high" if number >= high
            else "attention" if number >= attention
            else "low"
        )
        basis.append({"metric_id": metric_id, "value": number, "level": metric_level})
        if RISK_ORDER[metric_level] > RISK_ORDER[level]:
            level = metric_level
    if not basis:
        return {
            "level": "unavailable",
            "label": RISK_LABELS["unavailable"],
            "basis": [],
            "notice": "没有同时具备结果值和适用阈值的指标。",
        }
    return {
        "level": level,
        "label": RISK_LABELS[level],
        "basis": basis,
        "threshold_status": profile["status"],
        "threshold_source": profile["source"],
        "notice": (
            "演示阈值结果，不构成工程认证。"
            if profile["status"] == "demo_unvalidated"
            else "风险等级应结合阈值适用范围和模型质量复核。"
        ),
    }


def _scan_d3hsp(path: Path) -> JSONDict:
    result: JSONDict = {
        "available": False,
        "error_count": 0,
        "warning_count": 0,
        "warning_codes": [],
        "normal_termination": False,
        "termination": "unknown",
        "problem_time_s": 0.0,
        "problem_cycle": 0,
    }
    if not path.is_file():
        return result
    result["available"] = True
    warning_codes: set[str] = set()
    saw_normal_termination = False
    saw_abnormal_termination = False
    saw_sense_switch = False
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if re.search(r"^\s*\*\*\*\s+Error\s+\d+", line, flags=re.IGNORECASE):
                result["error_count"] += 1
            warning = re.search(r"^\s*\*\*\*\s+Warning\s+(\d+)", line, flags=re.IGNORECASE)
            if warning:
                result["warning_count"] += 1
                warning_codes.add(warning.group(1))
            compact_line = re.sub(r"\s+", "", line).lower()
            if "abnormaltermination" in compact_line:
                saw_abnormal_termination = True
            elif "normaltermination" in compact_line:
                saw_normal_termination = True
            if "terminationduetosenseswitch" in compact_line:
                saw_sense_switch = True
            time_match = re.search(r"Problem time\s*=\s*([+\-0-9.Ee]+)", line)
            if time_match:
                result["problem_time_s"] = _finite_number(time_match.group(1), 0.0)
            cycle_match = re.search(r"Problem cycle\s*=\s*(\d+)", line)
            if cycle_match:
                result["problem_cycle"] = int(cycle_match.group(1))
    if saw_abnormal_termination:
        result["termination"] = "abnormal"
    elif saw_sense_switch:
        result["termination"] = "stopped_by_sense_switch"
    elif saw_normal_termination:
        result["termination"] = "normal"
        result["normal_termination"] = True
    result["warning_codes"] = sorted(warning_codes)
    return result


def _parse_glstat(path: Path) -> JSONDict:
    if not path.is_file():
        return {"available": False, "summary": "glstat 不存在"}
    ratios: list[float] = []
    times: list[float] = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            match = re.search(r"total energy / initial energy\.\.\s*([+\-0-9.Ee]+)", line)
            if match:
                ratios.append(_finite_number(match.group(1), math.nan))
            time_match = re.search(r"^\s*time\.+\s*([+\-0-9.Ee]+)", line)
            if time_match:
                times.append(_finite_number(time_match.group(1), math.nan))
    ratios = [value for value in ratios if math.isfinite(value)]
    times = [value for value in times if math.isfinite(value)]
    if not ratios:
        return {"available": False, "summary": "glstat 缺少有效能量比"}
    deviation = max(abs(value - 1.0) for value in ratios)
    return {
        "available": True,
        "sample_count": len(ratios),
        "final_energy_ratio": ratios[-1],
        "max_energy_ratio_deviation": deviation,
        "last_time_s": times[-1] if times else None,
        "summary": f"最大总能量比偏差 {deviation:.3%}",
    }


def _matsum_diagnostics(path: Path, semantic_objects: list[JSONDict]) -> dict[str, JSONDict]:
    if not path.is_file():
        return {}
    histories: dict[int, list[tuple[float, float, float]]] = {}
    time_s: float | None = None
    pattern = re.compile(
        r"mat\.\#=\s*(\d+)\s+inten=\s*([+\-0-9.Ee]+)\s+kinen=\s*([+\-0-9.Ee]+)",
        flags=re.IGNORECASE,
    )
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            time_match = re.search(r"^\s*time\s*=\s*([+\-0-9.Ee]+)", line)
            if time_match:
                time_s = _finite_number(time_match.group(1), math.nan)
                continue
            match = pattern.search(line)
            if match and time_s is not None and math.isfinite(time_s):
                part_id = int(match.group(1))
                internal = _finite_number(match.group(2), math.nan)
                kinetic = _finite_number(match.group(3), math.nan)
                if math.isfinite(internal) and math.isfinite(kinetic):
                    histories.setdefault(part_id, []).append((time_s, internal, kinetic))

    result: dict[str, JSONDict] = {}
    for item in semantic_objects:
        part_histories = [histories[pid] for pid in item["part_ids"] if pid in histories]
        if not part_histories:
            continue
        initial_internal = sum(rows[0][1] for rows in part_histories)
        result[item["object_id"]] = {
            "source": "matsum",
            "notice": "仅用于确认对象发生数值响应，不直接用于风险分级。",
            "peak_kinetic_energy_j": sum(max(row[2] for row in rows) for rows in part_histories),
            "peak_internal_energy_change_j": sum(
                max(abs(row[1] - rows[0][1]) for row in rows)
                for rows in part_histories
            ),
            "initial_internal_energy_j": initial_internal,
            "last_time_s": min(rows[-1][0] for rows in part_histories),
        }
    return result


def _render_report(assessment: JSONDict) -> str:
    rows = []
    for item in assessment["objects"]:
        available = [
            f"{definition['label']}={metric['value']:.6g} {metric['unit']}"
            for metric_id, definition in METRIC_DEFINITIONS.items()
            if (metric := item["metrics"][metric_id]).get("available")
        ]
        rows.append(
            "<tr>"
            f"<td>{html.escape(item['label'])}</td>"
            f"<td>{html.escape(item['risk']['label'])}</td>"
            f"<td>{html.escape('；'.join(available) or '对象级指标不可用')}</td>"
            f"<td>{html.escape(item['risk']['notice'])}</td>"
            "</tr>"
        )
    blocking = "、".join(assessment["quality"]["blocking_check_ids"]) or "无"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>城市爆炸影响评估 - {html.escape(assessment['project_name'])}</title>
<style>
body {{ font-family: "Microsoft YaHei", sans-serif; margin: 32px; color: #17212b; }}
h1 {{ font-size: 24px; }} .notice {{ border-left: 4px solid #287a68; padding: 10px 14px; background: #eef6f3; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 18px; }}
th, td {{ border: 1px solid #ccd5dc; padding: 8px; text-align: left; vertical-align: top; }}
th {{ background: #edf2f5; }} .meta {{ color: #52616d; }}
</style>
</head>
<body>
<h1>城市爆炸影响评估</h1>
<p class="meta">项目：{html.escape(assessment['project_name'])}</p>
<p class="meta">模型哈希：{html.escape(assessment['model_sha256'])}</p>
<p class="meta">评估状态：{html.escape(assessment['status_label'])}</p>
<div class="notice">{html.escape(assessment['engineering_notice'])}</div>
<p>阻塞门禁：{html.escape(blocking)}</p>
<table>
<thead><tr><th>对象</th><th>风险等级</th><th>可用指标</th><th>说明</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</body>
</html>
"""


def _requested_end_time(model: JSONDict) -> float:
    spec = model.get("spec", {})
    if not isinstance(spec, dict):
        return 0.0
    analysis = spec.get("analysis", {})
    if not isinstance(analysis, dict):
        return 0.0
    return _finite_number(analysis.get("end_time_s"), 0.0)


def _quality_check(check_id: str, ok: bool, message: str) -> JSONDict:
    return {"id": check_id, "ok": bool(ok), "message": message}


def _positive_ints(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    return [int(item) for item in value if isinstance(item, int) and not isinstance(item, bool) and item > 0]


def _finite_number(value: object, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _status_label(status: str) -> str:
    return {
        "incomplete_solver_result": "求解结果不完整",
        "awaiting_object_metrics": "等待对象级后处理指标",
        "invalid_object_metrics": "对象级指标无效",
        "awaiting_threshold_profile": "等待风险阈值档案",
        "ready": "可生成对象级风险评估",
    }.get(status, status)
