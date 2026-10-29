from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import JSONDict
from .io import read_json
from .run_evidence import (
    validate_phase14_run_evidence,
    validate_run_record_identity,
)


CITY_RESULT_SOURCE_SCHEMA_VERSION = "phase17.city_result_source.v1"
REQUIRED_TEXT_OUTPUTS = ("d3hsp", "dbfsi", "glstat", "elout", "nodout")
_RECORD_NAME = "city_result_source.json"
_RUN_ID_PATTERN = re.compile(r"run_[A-Za-z0-9_]+")
_D3PLOT_PATTERN = re.compile(r"d3plot(?P<index>\d*)$")
_TERMINAL_RUN_STATUSES = {"completed", "solver_failed", "timed_out"}
_URBAN_COMPONENT_GROUPS = (
    "commercial_supermarket",
    "residential_community",
    "subway_entrance",
    "parked_vehicles",
    "traffic_lights",
    "concrete_roads",
    "ground_foundation",
    "parking_lot",
    "protection_boxes",
)
_EXPANDED_URBAN_COMPONENT_GROUPS = {
    "parked_vehicles",
    "traffic_lights",
    "protection_boxes",
}


def register_city_result_source(project: Path, result_dir: Path) -> JSONDict:
    project = project.resolve()
    result = result_dir.resolve()
    _require_city_model(project)
    _require_city_model(result)
    _require_matching_model_contract(project, result)
    evidence = _build_result_evidence(result)
    record: JSONDict = {
        "schema_version": CITY_RESULT_SOURCE_SCHEMA_VERSION,
        "source_kind": "registered_external",
        "project_name": project.name,
        "result_dir": str(result),
        "model_sha256": _sha256(result / "model.k"),
        "model_json_sha256": _sha256(result / "model.json"),
        "evidence": evidence,
        "registered_at": _utc_now(),
        "registered_by": "lsprepost_mcp.web",
    }
    _atomic_write_record(project, record)
    return {**record, "validation": {"ok": True, "issues": []}}


def resolve_city_result_source(project: Path) -> JSONDict:
    project = project.resolve()
    internal = _resolve_internal_solver_run(project)
    if internal is not None:
        return internal

    record_path = _record_path(project)
    if record_path.is_file():
        try:
            record = read_json(record_path)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return _unavailable_source(project, "registered city result record is unreadable")
        if isinstance(record, dict):
            return {**record, "validation": validate_city_result_source(project, record)}
    legacy = _resolve_legacy_project_root(project)
    if legacy is not None:
        return legacy
    return _unavailable_source(project, "no completed internal run or registered external result")


def validate_city_result_source(project: Path, record: JSONDict) -> JSONDict:
    project = project.resolve()
    validation: JSONDict = {
        "ok": False,
        "issues": [],
        "missing_files": [],
        "changed_files": [],
        "unexpected_files": [],
    }
    if not isinstance(record, dict):
        validation["issues"].append("registered city result record must be an object")
        return validation
    if record.get("schema_version") != CITY_RESULT_SOURCE_SCHEMA_VERSION:
        validation["issues"].append("registered city result record has an unsupported schema version")
    if record.get("source_kind") != "registered_external":
        validation["issues"].append("registered city result record has an invalid source kind")
    if record.get("project_name") != project.name:
        validation["issues"].append("registered city result record belongs to a different project")

    raw_result_dir = record.get("result_dir")
    if not isinstance(raw_result_dir, str) or not raw_result_dir:
        validation["issues"].append("registered city result record has no result directory")
        return validation
    result = Path(raw_result_dir).resolve()
    try:
        _require_city_model(project)
        _require_city_model(result)
        _require_matching_model_contract(project, result)
    except (OSError, ValueError) as exc:
        validation["issues"].append(str(exc))
    _validate_recorded_model_hashes(result, record, validation)

    expected_evidence = record.get("evidence")
    if not isinstance(expected_evidence, dict):
        validation["issues"].append("registered city result record has invalid evidence")
        return validation
    try:
        current_evidence = _build_result_evidence(result)
    except (OSError, ValueError) as exc:
        validation["issues"].append(str(exc))
        return validation

    expected_names = set(expected_evidence)
    current_names = set(current_evidence)
    validation["missing_files"] = sorted(expected_names - current_names)
    validation["unexpected_files"] = sorted(current_names - expected_names)
    changed_files: list[str] = list(validation["changed_files"])
    for name in sorted(expected_names & current_names):
        expected = expected_evidence[name]
        current = current_evidence[name]
        if (
            not isinstance(expected, dict)
            or expected.get("size_bytes") != current["size_bytes"]
            or expected.get("sha256") != current["sha256"]
        ):
            changed_files.append(name)
    validation["changed_files"] = sorted(set(changed_files))
    if validation["missing_files"]:
        validation["issues"].append("registered evidence files are missing")
    if validation["unexpected_files"]:
        validation["issues"].append("registered evidence files changed")
    if validation["changed_files"]:
        validation["issues"].append("registered evidence file contents changed")
    validation["ok"] = not validation["issues"]
    return validation


def _resolve_internal_solver_run(project: Path) -> JSONDict | None:
    latest_path = project / "solver_runs" / "latest.json"
    if not latest_path.is_file():
        return None
    try:
        latest = read_json(latest_path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(latest, dict) or not _is_terminal_city_run(latest):
        return None

    run_id = latest.get("run_id")
    if not isinstance(run_id, str) or not _RUN_ID_PATTERN.fullmatch(run_id):
        return None
    run_dir = (project / "solver_runs" / run_id).resolve()
    if run_dir.parent != (project / "solver_runs").resolve() or not run_dir.is_dir():
        return None
    try:
        run_record = read_json(run_dir / "run.json")
        if not isinstance(run_record, dict) or run_record.get("run_id") != run_id:
            return None
        if not _is_terminal_city_run(run_record):
            return None
        if not validate_run_record_identity(latest, run_record).get("ok"):
            return None
        if not validate_phase14_run_evidence(
            run_dir,
            run_record.get("evidence_manifest"),
        ).get("ok"):
            return None
        _require_city_model(project)
        _require_city_model(run_dir)
        _require_matching_model_contract(project, run_dir)
        evidence = _build_result_evidence(run_dir)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None
    return {
        "schema_version": CITY_RESULT_SOURCE_SCHEMA_VERSION,
        "source_kind": "solver_run",
        "project_name": project.name,
        "result_dir": str(run_dir),
        "run_id": run_id,
        "model_sha256": _sha256(run_dir / "model.k"),
        "model_json_sha256": _sha256(run_dir / "model.json"),
        "evidence": evidence,
        "validation": {"ok": True, "issues": []},
    }


def _resolve_legacy_project_root(project: Path) -> JSONDict | None:
    try:
        _require_city_model(project)
        evidence = _build_result_evidence(project)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None
    return {
        "schema_version": CITY_RESULT_SOURCE_SCHEMA_VERSION,
        "source_kind": "legacy_project_root",
        "project_name": project.name,
        "result_dir": str(project),
        "model_sha256": _sha256(project / "model.k"),
        "model_json_sha256": _sha256(project / "model.json"),
        "evidence": evidence,
        "validation": {"ok": True, "issues": []},
    }


def _is_terminal_city_run(record: JSONDict) -> bool:
    return (
        record.get("status") in _TERMINAL_RUN_STATUSES
        and record.get("result_variant") == "city_street_blast"
    )


def _require_city_model(directory: Path) -> JSONDict:
    model_k = directory / "model.k"
    model_json = directory / "model.json"
    if not model_k.is_file():
        raise ValueError(f"model.k is missing: {model_k}")
    if not model_json.is_file():
        raise ValueError(f"model.json is missing: {model_json}")
    try:
        model = read_json(model_json)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"model.json is unreadable: {model_json}") from exc
    metadata = model.get("metadata") if isinstance(model, dict) else None
    if not isinstance(metadata, dict) or metadata.get("model_type") != "city_street_blast_scene":
        raise ValueError("model.json is not a city_street_blast_scene model")
    semantic_objects = metadata.get("semantic_objects")
    urban_components = metadata.get("urban_components")
    if not (
        isinstance(semantic_objects, list)
        and semantic_objects
        or isinstance(urban_components, dict)
        and urban_components
    ):
        raise ValueError("model.json has no city semantic objects")
    semantic_object_ids = _semantic_object_ids(metadata, semantic_objects)
    _require_response_objects(metadata.get("response_objects"), semantic_object_ids)
    return model


def _semantic_object_ids(metadata: JSONDict, semantic_objects: object) -> set[str]:
    explicit_ids: set[str] = set()
    if isinstance(semantic_objects, list):
        explicit_ids = {
            item["object_id"]
            for item in semantic_objects
            if isinstance(item, dict)
            and isinstance(item.get("object_id"), str)
            and item["object_id"].strip()
        }
    if explicit_ids:
        return explicit_ids

    urban_components = metadata.get("urban_components")
    if not isinstance(urban_components, dict):
        return set()
    object_ids: set[str] = set()
    for group_id in _URBAN_COMPONENT_GROUPS:
        component = urban_components.get(group_id)
        part_ids = component.get("part_ids") if isinstance(component, dict) else None
        positive_part_ids: list[int] = []
        if isinstance(part_ids, list):
            positive_part_ids = [
                part_id
                for part_id in part_ids
                if isinstance(part_id, int)
                and not isinstance(part_id, bool)
                and part_id > 0
            ]
        if group_id in _EXPANDED_URBAN_COMPONENT_GROUPS:
            object_ids.update(
                f"{group_id[:-1]}_{index}"
                for index, _part_id in enumerate(positive_part_ids, start=1)
            )
        elif positive_part_ids:
            object_ids.add(group_id)
    return object_ids


def _require_response_objects(
    response_objects: object,
    semantic_object_ids: set[str],
) -> None:
    if not isinstance(response_objects, list) or not response_objects:
        raise ValueError("model.json response_objects must be a non-empty list")
    seen_object_ids: set[str] = set()
    seen_surface_ids: set[int] = set()
    for item in response_objects:
        if not isinstance(item, dict):
            raise ValueError("response_objects entries must be objects")
        object_id = item.get("object_id")
        if not isinstance(object_id, str) or not object_id.strip():
            raise ValueError("response object_id must be a non-empty string")
        if object_id in seen_object_ids:
            raise ValueError(f"duplicate response object_id: {object_id}")
        if object_id not in semantic_object_ids:
            raise ValueError(f"unbound response object_id: {object_id}")
        seen_object_ids.add(object_id)

        surface_id = item.get("fsi_surface_id")
        if isinstance(surface_id, bool) or not isinstance(surface_id, int) or surface_id <= 0:
            raise ValueError(f"response object {object_id} fsi_surface_id must be a positive integer")
        if surface_id in seen_surface_ids:
            raise ValueError(f"duplicate response fsi_surface_id: {surface_id}")
        seen_surface_ids.add(surface_id)
        _require_positive_response_ids(item.get("shell_element_ids"), "shell_element_ids", object_id)
        _require_positive_response_ids(item.get("node_ids"), "node_ids", object_id)


def _require_positive_response_ids(value: object, field: str, object_id: str) -> None:
    if (
        not isinstance(value, list)
        or not value
        or any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in value)
    ):
        raise ValueError(f"response object {object_id} {field} must contain positive integers")


def _require_matching_model_contract(project: Path, result: Path) -> None:
    if _sha256(project / "model.k") != _sha256(result / "model.k"):
        raise ValueError("project and result model.k hash differ")
    if _sha256(project / "model.json") != _sha256(result / "model.json"):
        raise ValueError("project and result model.json hash differ")


def _validate_recorded_model_hashes(
    result: Path,
    record: JSONDict,
    validation: JSONDict,
) -> None:
    for filename, field in (("model.k", "model_sha256"), ("model.json", "model_json_sha256")):
        expected = record.get(field)
        path = result / filename
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            validation["issues"].append(f"registered city result record has invalid {field}")
            continue
        try:
            actual = _sha256(path)
        except OSError:
            validation["issues"].append(f"registered city result {filename} is unavailable")
            continue
        if actual != expected:
            validation["changed_files"].append(filename)
            validation["issues"].append(f"registered city result {filename} hash changed")


def _build_result_evidence(result: Path) -> JSONDict:
    if not result.is_dir():
        raise ValueError(f"result directory is unavailable: {result}")
    evidence_paths: dict[str, Path] = {}
    for name in REQUIRED_TEXT_OUTPUTS:
        path = result / name
        if not path.is_file() or path.stat().st_size <= 0:
            raise ValueError(f"required solver output is missing or empty: {name}")
        evidence_paths[name] = path

    d3plots = _continuous_d3plot_series(result)
    evidence_paths.update({path.name: path for path in d3plots})
    return {
        name: {"size_bytes": path.stat().st_size, "sha256": _sha256(path)}
        for name, path in evidence_paths.items()
    }


def _continuous_d3plot_series(result: Path) -> list[Path]:
    candidates = [path for path in result.iterdir() if path.is_file() and path.name.lower().startswith("d3plot")]
    indexed: list[tuple[int, Path]] = []
    for path in candidates:
        match = _D3PLOT_PATTERN.fullmatch(path.name.lower())
        if match is None:
            raise ValueError(f"invalid d3plot evidence filename: {path.name}")
        suffix = match.group("index")
        index = 0 if not suffix else int(suffix)
        expected_name = "d3plot" if index == 0 else f"d3plot{index:02d}"
        if path.name.lower() != expected_name or path.stat().st_size <= 0:
            raise ValueError(f"invalid d3plot evidence file: {path.name}")
        indexed.append((index, path))
    indexed.sort(key=lambda item: item[0])
    if not indexed or indexed[0][0] != 0:
        raise ValueError("d3plot evidence must begin with d3plot")
    if [index for index, _path in indexed] != list(range(len(indexed))):
        raise ValueError("d3plot evidence sequence is not continuous")
    return [path for _index, path in indexed]


def _atomic_write_record(project: Path, record: JSONDict) -> None:
    path = _record_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _record_path(project: Path) -> Path:
    return project / "artifacts" / _RECORD_NAME


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unavailable_source(project: Path, issue: str) -> JSONDict:
    return {
        "schema_version": CITY_RESULT_SOURCE_SCHEMA_VERSION,
        "source_kind": "none",
        "project_name": project.name,
        "validation": {"ok": False, "issues": [issue]},
    }
