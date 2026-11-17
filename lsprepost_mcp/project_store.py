from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .config import (
    ARCHIVE_PROJECTS_DIR,
    DEFAULT_UNIT_SYSTEM,
    JSONDict,
    LEGACY_PROJECTS_DIR,
    PROJECTS_DIR,
    ROOT,
    WORKSPACE_DIR,
)
from .io import read_json, write_json
from .keyword_checks import keyword_card_token, keyword_quality_checks, material_header_fields
from .cfile import write_server_cfile
from .dyna_keyword import build_keyword
from .locks import ProjectLock
from .lspp.launcher import running_project_processes, terminate_process_tree
from .paths import archive_project_dir, checked_child, find_project_dir, iso_mtime, project_dir, safe_project_name
from .schema import ModelSpec
from .validation_profiles import (
    required_card_groups_for_capabilities,
    required_cards_for_capabilities,
    validation_capabilities,
)


ALLOWED_IF_EXISTS = {"error", "overwrite", "archive_then_write", "versioned"}
MAX_IMPORT_BYTES = 10 * 1024 * 1024
IMPORTS_DIR = WORKSPACE_DIR / "imports"
RUNTIME_ARTIFACT_MARKER = ".lsprepost_mcp_runtime_artifact"
RUNTIME_ARTIFACT_RE = re.compile(r"^\.[A-Za-z0-9_-]+\.(tmp|bak)_\d{8}T\d{6}\d*Z$")
CHECKER_VERSION = "phase17.r12_solver_compatibility.v6"


def write_model_project(spec: ModelSpec, if_exists: str = "error", force_close_runtime: bool = False) -> JSONDict:
    with ProjectLock(spec.project_name):
        return _write_model_project_locked(spec, if_exists, force_close_runtime)


def write_compiled_keyword_project(
    project_name: str,
    keyword: str,
    spec: JSONDict,
    metadata: JSONDict,
    *,
    if_exists: str = "error",
    force_close_runtime: bool = False,
    require_valid: bool = False,
) -> JSONDict:
    """Persist a trusted compiler result through the normal project transaction."""

    name = safe_project_name(project_name)
    if name != project_name:
        raise ValueError("project_name contains unsupported characters")
    if not keyword.startswith("*KEYWORD") or not keyword.rstrip().endswith("*END"):
        raise ValueError("compiled keyword must contain one complete *KEYWORD ... *END deck")
    with ProjectLock(name):
        if if_exists not in ALLOWED_IF_EXISTS:
            raise ValueError(f"if_exists must be one of {', '.join(sorted(ALLOWED_IF_EXISTS))}")
        path = project_dir(name)
        final_name = name
        if path.exists():
            if if_exists == "error":
                raise FileExistsError(
                    f"project already exists: {path}; use if_exists=overwrite, archive_then_write, or versioned"
                )
            if if_exists == "versioned":
                path = next_versioned_project_dir(name)
                final_name = path.name
            else:
                ensure_no_active_runtime(path, force_close_runtime)
        normalized_spec = dict(spec)
        normalized_spec["project_name"] = final_name
        tmp_path = temp_project_dir(path)
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True)
        mark_runtime_artifact(tmp_path)
        (tmp_path / "model.k").write_text(keyword, encoding="utf-8")
        write_json(
            tmp_path / "model.json",
            {
                "schema_version": "0.2.0",
                "spec": normalized_spec,
                "metadata": metadata,
            },
        )
        write_server_cfile(
            tmp_path,
            "open_model.cfile",
            "open_keyword.cfile",
            {"keyword_path": "model.k"},
            if_exists="overwrite",
        )
        try:
            checks = validate_project_files(tmp_path)
            if require_valid and not checks["ok"]:
                raise ValueError("；".join(checks["errors"]))
        except Exception:
            if require_valid:
                shutil.rmtree(tmp_path)
            raise
        write_json(tmp_path / "checks.json", checks)
        commit_project_dir(tmp_path, path, if_exists)
        remove_runtime_artifact(path)
        checks = rebase_committed_checks(
            checks,
            project_name=final_name,
            project_path=path,
        )
        write_json(path / "checks.json", checks)
        return {
            "project": final_name,
            "project_dir": str(path),
            "keyword_path": str(path / "model.k"),
            "cfile_path": str(path / "open_model.cfile"),
            "spec_path": str(path / "model.json"),
            "checks_path": str(path / "checks.json"),
            "metadata": metadata,
            "checks": checks,
            "if_exists": if_exists,
        }


def rebase_committed_checks(
    checks: JSONDict,
    *,
    project_name: str,
    project_path: Path,
) -> JSONDict:
    rebased = dict(checks)
    rebased["project_name"] = project_name
    rebased["keyword_path"] = str(project_path / "model.k")
    rebased["spec_path"] = str(project_path / "model.json")
    summary = rebased.get("summary")
    if isinstance(summary, dict):
        rebased["summary"] = {
            **summary,
            "project_name": project_name,
        }
    return rebased


def _write_model_project_locked(spec: ModelSpec, if_exists: str = "error", force_close_runtime: bool = False) -> JSONDict:
    if if_exists not in ALLOWED_IF_EXISTS:
        raise ValueError(f"if_exists must be one of {', '.join(sorted(ALLOWED_IF_EXISTS))}")
    path = project_dir(spec.project_name)
    if path.exists():
        if if_exists == "error":
            raise FileExistsError(f"project already exists: {path}; use if_exists=overwrite, archive_then_write, or versioned")
        if if_exists == "versioned":
            path = next_versioned_project_dir(spec.project_name)
            spec = replace(spec, project_name=path.name)
        else:
            ensure_no_active_runtime(path, force_close_runtime)
    keyword, metadata = build_keyword(spec)
    tmp_path = temp_project_dir(path)
    if tmp_path.exists():
        shutil.rmtree(tmp_path)
    tmp_path.mkdir(parents=True)
    mark_runtime_artifact(tmp_path)
    keyword_path = tmp_path / "model.k"
    spec_path = tmp_path / "model.json"
    checks_path = tmp_path / "checks.json"
    keyword_path.write_text(keyword, encoding="utf-8")
    write_server_cfile(tmp_path, "open_model.cfile", "open_keyword.cfile", {"keyword_path": "model.k"}, if_exists="overwrite")
    write_json(
        spec_path,
        {
            "schema_version": "0.2.0",
            "spec": {
                "project_name": spec.project_name,
                "model_type": spec.model_type,
                "unit_system": spec.unit_system,
                "geometry": spec.geometry,
                "mesh": spec.mesh,
                "material": spec.material,
                "curves": spec.curves,
                "hourglass": spec.hourglass,
                "analysis_control": spec.analysis_control,
                "database": spec.database,
                "components": spec.components,
                "model_resources": spec.model_resources,
                "contacts": spec.contacts,
                "sets": spec.sets,
                "boundary_conditions": spec.boundary_conditions,
                "loads": spec.loads,
                "warnings": spec.warnings,
            },
            "metadata": metadata,
        },
    )
    checks = validate_project_files(tmp_path)
    write_json(checks_path, checks)
    commit_project_dir(tmp_path, path, if_exists)
    remove_runtime_artifact(path)
    checks = validate_project_files(path)
    write_json(path / "checks.json", checks)
    return {
        "project": spec.project_name,
        "project_dir": str(path),
        "keyword_path": str(path / "model.k"),
        "cfile_path": str(path / "open_model.cfile"),
        "spec_path": str(path / "model.json"),
        "checks_path": str(path / "checks.json"),
        "metadata": metadata,
        "checks": checks,
        "if_exists": if_exists,
    }


def temp_project_dir(path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return checked_child(PROJECTS_DIR, f".{path.name}.tmp_{timestamp}")


def mark_runtime_artifact(path: Path) -> None:
    (path / RUNTIME_ARTIFACT_MARKER).write_text(
        f"lsprepost-mcp runtime artifact\ncreated_at={datetime.now(timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )


def remove_runtime_artifact(path: Path) -> None:
    try:
        (path / RUNTIME_ARTIFACT_MARKER).unlink()
    except FileNotFoundError:
        pass


def next_versioned_project_dir(project_name: str) -> Path:
    base = safe_project_name(project_name)
    for index in range(2, 10_000):
        candidate = project_dir(f"{base}_v{index}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not allocate versioned project name for {base}")


def commit_project_dir(tmp_path: Path, path: Path, if_exists: str) -> None:
    if not path.exists():
        shutil.move(str(tmp_path), str(path))
        return
    if if_exists == "archive_then_write":
        dest = archive_project_dir(path.name)
        if dest.exists():
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            dest = archive_project_dir(f"{path.name}_{timestamp}")
        ARCHIVE_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))
        shutil.move(str(tmp_path), str(path))
        return
    if if_exists != "overwrite":
        raise FileExistsError(f"project already exists: {path}")
    backup = checked_child(PROJECTS_DIR, f".{path.name}.bak_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}")
    shutil.move(str(path), str(backup))
    mark_runtime_artifact(backup)
    try:
        shutil.move(str(tmp_path), str(path))
    except Exception:
        if path.exists():
            shutil.rmtree(path)
        shutil.move(str(backup), str(path))
        remove_runtime_artifact(path)
        raise
    shutil.rmtree(backup)


def ensure_no_active_runtime(project_path: Path, force_close_runtime: bool = False) -> None:
    running = running_project_processes(project_path, fail_closed=True)
    if not running:
        return
    if not force_close_runtime:
        raise RuntimeError(
            f"project has active LS-PrePost runtime process(es); close them before modifying the project: {running}"
        )
    failed: list[JSONDict] = []
    for record in running:
        pid = int(record.get("pid", 0) or 0)
        if pid <= 0 or not terminate_process_tree(pid):
            failed.append(record)
    remaining = running_project_processes(project_path, fail_closed=True)
    if failed or remaining:
        raise RuntimeError(
            f"could not close active LS-PrePost runtime process(es): failed={failed}, remaining={remaining}"
        )


def validate_project_files(path: Path) -> JSONDict:
    custom_model_path = path / "model.json"
    if custom_model_path.is_file():
        try:
            custom_model = read_json(custom_model_path)
        except (OSError, ValueError):
            custom_model = {}
        custom_metadata = custom_model.get("metadata", {}) if isinstance(custom_model, dict) else {}
        if isinstance(custom_metadata, dict) and custom_metadata.get("compiler") == "lsprepost.r12_shell_plate@1":
            from .r12_plate import validate_project_files as validate_r12_plate

            return validate_r12_plate(path)
        custom_spec = custom_model.get("spec", {}) if isinstance(custom_model, dict) else {}
        if isinstance(custom_spec, dict) and custom_spec.get("model_type") == "ly160_paper_tension":
            from .ly160_tension import validate_project as validate_paper_tension

            return validate_paper_tension(path)
        if isinstance(custom_spec, dict) and custom_spec.get("model_type") in {"ly160_nr45_tension", "ly160_nr45_diagnostic"}:
            from .ly160_nr45 import validate_project as validate_nr45_project

            return validate_nr45_project(path)
        if isinstance(custom_spec, dict) and custom_spec.get("model_type") == "quarter_two_tnt_ale_spg":
            from .quarter_two_tnt import validate_quarter_two_tnt_project

            return validate_quarter_two_tnt_project(path)
        if isinstance(custom_spec, dict) and custom_spec.get("model_type") == "b120_spg_sale_rebuild":
            from .b120_spg_sale_rebuild import validate_project as validate_b120_project

            return validate_b120_project(path)
        if isinstance(custom_spec, dict) and custom_spec.get("model_type") == "impact_1788_mmale_rebuild":
            from .impact_1788_rebuild import validate_project as validate_impact_project

            return validate_impact_project(path)
        if isinstance(custom_spec, dict) and custom_spec.get("model_type") == "gran_r5_mmale_rebuild":
            from .gran_r5_rebuild import validate_project

            return validate_project(path)

    keyword_path = path / "model.k"
    spec_path = path / "model.json"
    errors: list[str] = []
    warnings: list[str] = []
    check_items: list[JSONDict] = []
    keyword = keyword_path.read_text(encoding="utf-8") if keyword_path.exists() else ""
    model = read_json(spec_path) if spec_path.exists() else {}
    spec = model.get("spec", {}) if isinstance(model, dict) else {}
    metadata = model.get("metadata", {}) if isinstance(model, dict) else {}
    if isinstance(metadata, dict):
        metadata = dict(metadata)
        metadata["_project_dir"] = str(path)
    model_type = spec.get("model_type", metadata.get("model_type", "unknown")) if isinstance(spec, dict) else "unknown"

    def add_check(
        check_id: str,
        ok: bool,
        message: str,
        severity: str = "error",
        expected: object | None = None,
        actual: object | None = None,
    ) -> None:
        item: JSONDict = {"id": check_id, "ok": ok, "severity": "info" if ok else severity, "message": message}
        if expected is not None:
            item["expected"] = expected
        if actual is not None:
            item["actual"] = actual
        check_items.append(item)
        if ok:
            return
        if severity == "warning":
            warnings.append(message)
        else:
            errors.append(message)

    add_check("file.model_k", keyword_path.exists(), "model.k exists" if keyword_path.exists() else "model.k is missing")
    add_check("file.model_json", spec_path.exists(), "model.json exists" if spec_path.exists() else "model.json is missing")

    required_cards = ["*KEYWORD", "*NODE", "*PART", "*END"]
    required_card_groups: list[tuple[str, ...]] = []
    element_family = metadata.get("element_family", "imported")
    if element_family == "shell":
        required_cards.extend(["*ELEMENT_SHELL", "*SECTION_SHELL"])
    elif element_family == "solid":
        required_cards.extend(["*ELEMENT_SOLID", "*SECTION_SOLID"])
    elif element_family == "mixed":
        required_cards.extend(["*ELEMENT_SHELL", "*SECTION_SHELL", "*ELEMENT_SOLID", "*SECTION_SOLID"])
    if model_type != "imported_keyword":
        required_cards.extend(material_cards_for_spec(spec))
        required_cards.extend(["*SET_NODE_LIST", "*BOUNDARY_SPC_SET"])
        try:
            capabilities = validation_capabilities(spec, metadata)
            required_cards.extend(required_cards_for_capabilities(capabilities))
            required_card_groups.extend(
                required_card_groups_for_capabilities(capabilities)
            )
            add_check(
                "validation.capability_profile",
                True,
                "validation capabilities resolved",
                actual=list(capabilities),
            )
        except ValueError as exc:
            add_check(
                "validation.capability_profile",
                False,
                str(exc),
                actual=metadata.get("validation_capabilities"),
            )
        if int(metadata.get("curve_count", 0)) > 0:
            required_cards.append("*DEFINE_CURVE")
        if has_condition_type(spec, "spc_node_set"):
            required_cards.append("*BOUNDARY_SPC_SET")
        if has_condition_type(spec, "prescribed_displacement"):
            required_cards.append("*BOUNDARY_PRESCRIBED_MOTION_SET")
        if has_condition_type(spec, "prescribed_velocity"):
            required_cards.append("*BOUNDARY_PRESCRIBED_MOTION_SET")
        if has_load_type(spec, "nodal_force"):
            required_cards.append("*LOAD_NODE_SET")
        if has_load_type(spec, "gravity"):
            required_cards.append("*LOAD_BODY_")
        if has_load_type(spec, "pressure_on_segment_set"):
            required_cards.extend(["*SET_SEGMENT", "*LOAD_SEGMENT_SET"])
        if has_load_type(spec, "pressure_on_segment"):
            required_cards.append("*LOAD_SEGMENT")
        if has_load_type(spec, "initial_velocity"):
            required_cards.append("*INITIAL_VELOCITY_NODE")
        if has_load_type(spec, "blast_enhanced"):
            required_cards.extend(
                [
                    "*LOAD_BLAST_ENHANCED",
                    "*LOAD_BLAST_SEGMENT_SET",
                    "*DATABASE_BINARY_BLSTFOR",
                ]
            )
        if isinstance(spec.get("hourglass"), dict) and spec.get("hourglass"):
            required_cards.append("*HOURGLASS_TITLE")
        if isinstance(spec.get("analysis_control"), dict):
            if isinstance(spec["analysis_control"].get("energy"), dict):
                required_cards.append("*CONTROL_ENERGY")
            if isinstance(spec["analysis_control"].get("shell"), dict):
                required_cards.append("*CONTROL_SHELL")
            if isinstance(spec["analysis_control"].get("timestep"), dict):
                required_cards.append("*CONTROL_TIMESTEP")
        if isinstance(spec.get("database"), dict):
            if "format" in spec["database"]:
                required_cards.append("*DATABASE_FORMAT")
            if "d3thdt_dt_s" in spec["database"]:
                required_cards.append("*DATABASE_BINARY_D3THDT")
            if "nodout_dt_s" in spec["database"]:
                required_cards.append("*DATABASE_NODOUT")
                required_cards.append("*DATABASE_HISTORY_NODE_SET")
            if isinstance(spec["database"].get("extent_binary"), dict):
                required_cards.append("*DATABASE_EXTENT_BINARY")

    card_tokens = {
        keyword_card_token(line)
        for line in keyword.splitlines()
        if keyword_card_token(line)
    }
    for card in sorted(set(required_cards)):
        present = required_keyword_card_present(card_tokens, card)
        add_check(
            f"card.{card.strip('*').lower()}",
            present,
            f"{card} card is present" if present else f"{card} card is missing",
            expected=True,
            actual=present,
        )
    for alternatives in sorted(set(required_card_groups)):
        present_cards = [
            card
            for card in alternatives
            if required_keyword_card_present(card_tokens, card)
        ]
        check_name = "_or_".join(
            card.strip("*").lower() for card in alternatives
        )
        add_check(
            f"card_group.{check_name}",
            bool(present_cards),
            "one accepted capability card is present"
            if present_cards
            else f"one of {', '.join(alternatives)} is required",
            expected=list(alternatives),
            actual=present_cards,
        )

    add_check(
        "unit_system.marker",
        DEFAULT_UNIT_SYSTEM in keyword or model_type == "imported_keyword",
        f"unit system marker {DEFAULT_UNIT_SYSTEM} is present"
        if DEFAULT_UNIT_SYSTEM in keyword or model_type == "imported_keyword"
        else f"unit system marker {DEFAULT_UNIT_SYSTEM} is missing",
        expected=DEFAULT_UNIT_SYSTEM,
        actual="present" if DEFAULT_UNIT_SYSTEM in keyword else "missing",
    )

    counts = normalize_counts(metadata)
    for key in ["nodes", "elements", "parts", "materials", "sections"]:
        add_check(
            f"count.{key}",
            counts[key] > 0,
            f"{key} count is positive" if counts[key] > 0 else f"{key} count must be positive",
            expected="> 0",
            actual=counts[key],
        )
    for index, limitation in enumerate(metadata.get("limitations", []), start=1):
        add_check(f"model.limitation.{index}", False, str(limitation), severity="warning")
    if model_type != "imported_keyword":
        for index, warning in enumerate(spec.get("warnings", []), start=1):
            add_check(
                f"schema.unknown_field.{index}",
                False,
                str(warning.get("message", warning)),
                severity="warning",
                actual={"path": warning.get("path"), "field": warning.get("field")},
            )
        add_check(
            "count.constraints",
            counts["constraints"] >= 1,
            "at least one constraint card is present"
            if counts["constraints"] >= 1
            else "at least one constraint card is required",
            expected=">= 1",
            actual=counts["constraints"],
        )
        check_physical_values(spec, add_check)
        check_load_and_boundary_values(spec, add_check, metadata)
        add_keyword_quality_checks(keyword, spec, metadata, add_check)
    else:
        add_keyword_quality_checks(keyword, spec, metadata, add_check)
        for index, warning in enumerate(metadata.get("semantic_warnings", []), start=1):
            add_check(f"import.semantic_warning.{index}", False, warning, severity="warning")

    readiness = derive_readiness(errors, warnings, check_items)
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "readiness": readiness,
        "validation_scope": {
            "ok_meaning": "static checks passed; this is not a full LS-DYNA solver semantic validation",
            "ok_for_gui_preview": "keyword deck is suitable for LS-PrePost preview attempts",
            "ok_for_solver_draft": "static blockers for solver draft were not detected; still requires engineering review",
            "ok_for_production_review": "all current static warnings cleared; still not a production certification",
        },
        "counts": counts,
        "checks": check_items,
        "summary": {
            "project_name": path.name,
            "model_type": model_type,
            "unit_system": metadata.get("unit_system", "unknown"),
            "modified_at": iso_mtime(path),
        },
        "keyword_path": str(keyword_path),
        "spec_path": str(spec_path),
        "validation_fingerprint": project_validation_fingerprint(path),
    }


def project_validation_fingerprint(path: Path) -> JSONDict:
    return {
        "checker_version": CHECKER_VERSION,
        "model_k_sha256": _file_sha256(path / "model.k"),
        "model_json_sha256": _file_sha256(path / "model.json"),
    }


def project_checks_are_current(path: Path, checks: object) -> bool:
    if not isinstance(checks, dict):
        return False
    if "mesh_binding_check" in checks:
        # The mesh is a separate content-addressed file. Recheck it when opening the project.
        return False
    fingerprint = checks.get("validation_fingerprint")
    return (
        isinstance(fingerprint, dict)
        and fingerprint == project_validation_fingerprint(path)
    )


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_physical_values(spec: JSONDict, add_check) -> None:
    geometry = spec.get("geometry", {}) if isinstance(spec, dict) else {}
    mesh = spec.get("mesh", {}) if isinstance(spec, dict) else {}
    material = spec.get("material", {}) if isinstance(spec, dict) else {}
    keys = ["length_m", "width_m", "height_m", "thickness_m", "radius_m"]
    for key in keys:
        if key not in geometry:
            continue
        add_check(
            f"physical.{key}",
            float(geometry.get(key, 0)) > 0,
            f"{key} is positive" if float(geometry.get(key, 0)) > 0 else f"{key} must be positive",
            expected="> 0",
            actual=geometry.get(key),
        )
    add_check(
        "mesh.size_m",
        float(mesh.get("size_m", 0)) > 0,
        "mesh.size_m is positive" if float(mesh.get("size_m", 0)) > 0 else "mesh.size_m must be positive",
        expected="> 0",
        actual=mesh.get("size_m", 0),
    )
    add_check(
        "material.density",
        float(material.get("density_kg_per_m3", 0)) > 0,
        "density_kg_per_m3 is positive"
        if float(material.get("density_kg_per_m3", 0)) > 0
        else "density_kg_per_m3 must be positive",
        expected="> 0",
        actual=material.get("density_kg_per_m3", 0),
    )
    if material.get("type", "elastic") == "elastic":
        add_check(
            "material.youngs_modulus",
            float(material.get("youngs_pa", 0)) > 0,
            "youngs_pa is positive" if float(material.get("youngs_pa", 0)) > 0 else "youngs_pa must be positive",
            expected="> 0",
            actual=material.get("youngs_pa", 0),
        )
    else:
        add_check("material.advanced_type", True, f"advanced material card {material.get('type')} is selected", actual=material.get("type"))
    add_check(
        "material.unit_system",
        material.get("unit_system") == DEFAULT_UNIT_SYSTEM,
        f"material unit system is {DEFAULT_UNIT_SYSTEM}"
        if material.get("unit_system") == DEFAULT_UNIT_SYSTEM
        else "material.unit_system must match model unit system",
        expected=DEFAULT_UNIT_SYSTEM,
        actual=material.get("unit_system", "missing"),
    )
    add_check(
        "material.source",
        bool(str(material.get("source", "")).strip()),
        "material source is recorded" if str(material.get("source", "")).strip() else "material.source is missing",
        severity="warning",
    )
    add_check(
        "material.version",
        bool(str(material.get("version", "")).strip()),
        "material version is recorded" if str(material.get("version", "")).strip() else "material.version is missing",
        severity="warning",
    )
    source_type = str(material.get("source_type", ""))
    add_check(
        "material.source_type",
        source_type in {"material_library", "user_confirmed_custom"},
        "material source_type is controlled"
        if source_type in {"material_library", "user_confirmed_custom"}
        else "material.source_type should be material_library or user_confirmed_custom",
        severity="warning",
        actual=source_type or "missing",
    )
    if material.get("requires_project_review"):
        add_check("material.review_required", False, "material values require project review before production analysis", severity="warning")


def add_keyword_quality_checks(keyword: str, spec: JSONDict, metadata: JSONDict, add_check) -> None:
    for item in keyword_quality_checks(keyword, spec, metadata):
        add_check(
            str(item["id"]),
            bool(item["ok"]),
            str(item["message"]),
            severity=str(item.get("severity", "error")),
            actual=item.get("actual"),
        )


def derive_readiness(errors: list[str], warnings: list[str], check_items: list[JSONDict]) -> JSONDict:
    failed_warning_ids = [
        str(item.get("id"))
        for item in check_items
        if not bool(item.get("ok")) and str(item.get("severity")) == "warning"
    ]
    solver_warning_blockers = [
        check_id
        for check_id in failed_warning_ids
        if check_id
        in {
            "quality.estimate.stable_timestep",
            "quality.geometry.load_segment_orientation",
            "quality.geometry.shell_normals",
            "quality.geometry.shell_warpage",
            "quality.geometry.shell_aspect_ratio",
            "quality.geometry.shell_shape_ratio",
            "quality.geometry.solid_jacobian_ratio",
            "quality.geometry.solid_aspect_ratio",
            "quality.unsupported.contact_cards",
        }
    ]
    return {
        "ok_for_gui_preview": not errors,
        "ok_for_solver_draft": not errors and not solver_warning_blockers,
        "ok_for_production_review": not errors and not warnings,
        "solver_warning_blockers": solver_warning_blockers,
        "production_warning_count": len(warnings),
        "note": "Readiness is based on local static checks, not full LS-DYNA/LS-PrePost semantic validation.",
    }


def material_card_for_spec(spec: JSONDict) -> str:
    material = spec.get("material", {}) if isinstance(spec, dict) else {}
    material_type = str(material.get("type", "elastic"))
    return {
        "elastic": "*MAT_ELASTIC",
        "piecewise_linear_plasticity": "*MAT_PIECEWISE_LINEAR_PLASTICITY",
        "cscm_concrete": "*MAT_CSCM_CONCRETE",
        "johnson_holmquist_concrete": "*MAT_JOHNSON_HOLMQUIST_CONCRETE",
        "rht": "*MAT_RHT",
        "concrete_damage_rel3": "*MAT_CONCRETE_DAMAGE_REL3",
        "user_defined_material_models": "*MAT_USER_DEFINED_MATERIAL_MODELS",
        "user_defined_material": "*MAT_USER_DEFINED_MATERIAL_MODELS",
    }.get(material_type, "*MAT_")


def material_cards_for_spec(spec: JSONDict) -> list[str]:
    if not isinstance(spec, dict):
        return ["*MAT_"]
    components = spec.get("components")
    if spec.get("model_type") == "assembly_scene" and isinstance(components, list):
        cards = {
            material_card_for_spec({"material": component.get("material", {})})
            for component in components
            if isinstance(component, dict)
        }
        return sorted(cards) or ["*MAT_"]
    return [material_card_for_spec(spec)]


def has_condition_type(spec: JSONDict, condition_type: str) -> bool:
    if not isinstance(spec, dict):
        return False
    return any(
        isinstance(item, dict) and item.get("type") == condition_type
        for item in spec.get("boundary_conditions", [])
    )


def has_load_type(spec: JSONDict, load_type: str) -> bool:
    if not isinstance(spec, dict):
        return False
    return any(isinstance(item, dict) and item.get("type") == load_type for item in spec.get("loads", []))


def required_keyword_card_present(card_tokens: set[str], required: str) -> bool:
    required = required.upper()
    if required == "*KEYWORD":
        return bool(card_tokens & {"*KEYWORD", "*KEYWORD_ID"})
    if required.endswith("_"):
        return any(token.startswith(required) for token in card_tokens)
    return required in card_tokens or f"{required}_TITLE" in card_tokens


def check_load_and_boundary_values(
    spec: JSONDict,
    add_check,
    metadata: JSONDict | None = None,
) -> None:
    boundary_conditions = spec.get("boundary_conditions", []) if isinstance(spec, dict) else []
    loads = spec.get("loads", []) if isinstance(spec, dict) else []
    components = spec.get("components", []) if isinstance(spec, dict) else []
    fixed_count = sum(1 for item in boundary_conditions if isinstance(item, dict) and item.get("type") == "fixed_edge")
    component_fixed_count = sum(
        len(item.get("fixed_faces", [])) + len(item.get("fixed_regions", []))
        for item in components
        if isinstance(item, dict)
        and isinstance(item.get("fixed_faces", []), list)
        and isinstance(item.get("fixed_regions", []), list)
    )
    prescribed_count = sum(1 for item in boundary_conditions if isinstance(item, dict) and item.get("type") == "prescribed_displacement")
    prescribed_velocity_count = sum(1 for item in boundary_conditions if isinstance(item, dict) and item.get("type") == "prescribed_velocity")
    spc_node_set_count = sum(1 for item in boundary_conditions if isinstance(item, dict) and item.get("type") == "spc_node_set")
    nodal_force_count = sum(1 for item in loads if isinstance(item, dict) and item.get("type") == "nodal_force")
    gravity_count = sum(1 for item in loads if isinstance(item, dict) and item.get("type") == "gravity")
    pressure_count = sum(1 for item in loads if isinstance(item, dict) and item.get("type") == "pressure_on_segment_set")
    direct_pressure_count = sum(1 for item in loads if isinstance(item, dict) and item.get("type") == "pressure_on_segment")
    initial_velocity_count = sum(1 for item in loads if isinstance(item, dict) and item.get("type") == "initial_velocity")
    component_initial_velocity_count = sum(1 for item in components if isinstance(item, dict) and "initial_velocity_m_per_s" in item)
    generated_anchor_count = int((metadata or {}).get("generated_constraint_anchor_count", 0))
    anchor_count = fixed_count + spc_node_set_count + component_fixed_count + generated_anchor_count
    add_check(
        "boundary.constraint_anchor_count",
        anchor_count >= 1,
        "at least one fixed edge or node-level SPC is defined"
        if anchor_count >= 1
        else "at least one fixed edge or node-level SPC is required",
        expected=">= 1",
        actual=anchor_count,
    )
    if prescribed_count:
        add_check(
            "boundary.prescribed_displacement_count",
            True,
            f"{prescribed_count} prescribed displacement boundary condition(s) defined",
            actual=prescribed_count,
        )
    if prescribed_velocity_count:
        add_check(
            "boundary.prescribed_velocity_count",
            True,
            f"{prescribed_velocity_count} prescribed velocity boundary condition(s) defined",
            actual=prescribed_velocity_count,
        )
    if spc_node_set_count:
        add_check("boundary.spc_node_set_count", True, f"{spc_node_set_count} node-level SPC definition(s) defined", actual=spc_node_set_count)
    if component_fixed_count:
        add_check("boundary.component_fixed_face_count", True, f"{component_fixed_count} component fixed face definition(s) defined", actual=component_fixed_count)
    if generated_anchor_count:
        add_check(
            "boundary.generated_constraint_anchor_count",
            True,
            f"{generated_anchor_count} controlled generated constraint anchor(s) defined",
            actual=generated_anchor_count,
        )
    if nodal_force_count:
        add_check("load.nodal_force_count", True, f"{nodal_force_count} nodal force load(s) defined", actual=nodal_force_count)
    if gravity_count:
        add_check("load.gravity_count", True, f"{gravity_count} gravity load(s) defined", actual=gravity_count)
    if pressure_count:
        add_check("load.pressure_count", True, f"{pressure_count} pressure load(s) defined", actual=pressure_count)
    if direct_pressure_count:
        add_check("load.direct_pressure_count", True, f"{direct_pressure_count} direct segment pressure load(s) defined", actual=direct_pressure_count)
    if initial_velocity_count or component_initial_velocity_count:
        add_check(
            "initial_velocity.count",
            True,
            f"{initial_velocity_count + component_initial_velocity_count} initial velocity definition(s) defined",
            actual=initial_velocity_count + component_initial_velocity_count,
        )


def normalize_counts(metadata: JSONDict) -> JSONDict:
    if "nodes" in metadata:
        return metadata
    return {
        "nodes": int(metadata.get("node_count", 0)),
        "elements": int(metadata.get("element_count", 0)),
        "parts": int(metadata.get("part_count", 0)),
        "materials": int(metadata.get("material_count", 0)),
        "sections": int(metadata.get("section_count", 0)),
        "constraints": int(metadata.get("constraint_count", 0)),
        "node_sets": int(metadata.get("node_set_count", 0)),
        "part_sets": int(metadata.get("part_set_count", 0)),
        "segment_sets": int(metadata.get("segment_set_count", 0)),
        "loads": int(metadata.get("load_count", 0)),
        "initial_conditions": int(metadata.get("initial_condition_count", 0)),
        "curves": int(metadata.get("curve_count", 0)),
        "hourglass": int(metadata.get("hourglass_count", 0)),
        "controls": int(metadata.get("control_count", 0)),
        "databases": int(metadata.get("database_count", 0)),
    }


def project_record(path: Path, source: str) -> JSONDict:
    model_path = path / "model.json"
    checks_path = path / "checks.json"
    model: JSONDict = {}
    checks: JSONDict = {}
    if model_path.exists():
        try:
            model = read_json(model_path)
        except json.JSONDecodeError:
            model = {}
    if checks_path.exists():
        try:
            checks = read_json(checks_path)
        except json.JSONDecodeError:
            checks = {}
    spec = model.get("spec", {}) if isinstance(model, dict) else {}
    metadata = model.get("metadata", {}) if isinstance(model, dict) else {}
    return {
        "project_name": path.name,
        "source": source,
        "project_dir": str(path),
        "model_type": spec.get("model_type", "unknown") if isinstance(spec, dict) else "unknown",
        "unit_system": metadata.get("unit_system", "unknown"),
        "ok": checks.get("ok") if isinstance(checks, dict) else None,
        "readiness": checks.get("readiness", {}) if isinstance(checks, dict) else {},
        "counts": normalize_counts(checks.get("counts", metadata) if isinstance(checks, dict) else metadata),
        "modified_at": iso_mtime(path),
        "paths": {
            "model_json": str(model_path),
            "keyword": str(path / "model.k"),
            "checks": str(checks_path),
            "cfile": str(path / "open_model.cfile"),
        },
    }


def iter_project_records() -> list[JSONDict]:
    cleanup_stale_project_artifacts()
    records: list[JSONDict] = []
    for base, source in [
        (PROJECTS_DIR, "workspace"),
        (LEGACY_PROJECTS_DIR, "legacy"),
        (ARCHIVE_PROJECTS_DIR, "archive"),
    ]:
        if not base.exists():
            continue
        for path in sorted(base.iterdir(), key=lambda item: item.name.lower()):
            if path.name.startswith("."):
                continue
            if path.is_dir() and ((path / "model.json").exists() or (path / "model.k").exists()):
                records.append(project_record(path, source))
    return records


def cleanup_stale_project_artifacts(max_age_seconds: int = 24 * 60 * 60) -> JSONDict:
    now = datetime.now(timezone.utc).timestamp()
    removed: list[str] = []
    errors: list[JSONDict] = []
    for base in [PROJECTS_DIR, ARCHIVE_PROJECTS_DIR]:
        if not base.exists():
            continue
        try:
            candidates = list(base.iterdir())
        except OSError as exc:
            errors.append({"path": str(base), "error": str(exc)})
            continue
        for path in candidates:
            try:
                if not path.is_dir():
                    continue
                if not RUNTIME_ARTIFACT_RE.match(path.name):
                    continue
                if not (path / RUNTIME_ARTIFACT_MARKER).exists():
                    continue
                age_seconds = now - path.stat().st_mtime
                if age_seconds < max_age_seconds:
                    continue
                shutil.rmtree(path)
                removed.append(str(path))
            except OSError as exc:
                errors.append({"path": str(path), "error": str(exc)})
    return {"removed": removed, "removed_count": len(removed), "errors": errors, "error_count": len(errors)}


def build_model_summary(path: Path) -> JSONDict:
    model_path = path / "model.json"
    if not model_path.exists():
        raise FileNotFoundError(f"model.json not found: {model_path}")
    model = read_json(model_path)
    checks_path = path / "checks.json"
    checks = read_json(checks_path) if checks_path.exists() else validate_project_files(path)
    spec = model.get("spec", {})
    metadata = model.get("metadata", {})
    geometry = spec.get("geometry", {}) if isinstance(spec, dict) else {}
    mesh = spec.get("mesh", {}) if isinstance(spec, dict) else {}
    material = spec.get("material", {}) if isinstance(spec, dict) else {}
    summary_text = (
        f"项目 {path.name} 是 {spec.get('model_type', 'unknown')} 模型；"
        f"单位制为 {metadata.get('unit_system', 'unknown')}；"
        f"材料为 {material.get('name', 'unknown')}；"
        f"节点数 {metadata.get('node_count', 'unknown')}，"
        f"单元数 {metadata.get('element_count', 'unknown')}；"
        f"校验状态为 {'通过' if checks.get('ok') else '未通过'}。"
    )
    return {
        "project_name": path.name,
        "summary_text": summary_text,
        "model": {
            "model_type": spec.get("model_type", "unknown") if isinstance(spec, dict) else "unknown",
            "unit_system": metadata.get("unit_system", "unknown"),
            "geometry": geometry,
            "mesh": mesh,
            "material": material,
            "metadata": metadata,
        },
        "checks": {
            "ok": checks.get("ok"),
            "errors": checks.get("errors", []),
            "warnings": checks.get("warnings", []),
            "readiness": checks.get("readiness", {}),
            "counts": checks.get("counts", {}),
        },
        "paths": project_record(path, "resolved")["paths"],
    }


def archive_project(name: str, confirm: str, reason: str = "", force_close_runtime: bool = False) -> JSONDict:
    project_name = safe_project_name(name)
    with ProjectLock(project_name):
        if confirm != project_name:
            raise ValueError("confirm_project_name must exactly match project_name")
        src = project_dir(project_name)
        if not src.exists():
            raise FileNotFoundError(
                f"active workspace project not found: {project_name}; only workspace/projects can be archived"
            )
        ensure_no_active_runtime(src, force_close_runtime)
        ARCHIVE_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        dest = archive_project_dir(project_name)
        if dest.exists():
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            dest = archive_project_dir(f"{project_name}_{timestamp}")
        shutil.move(str(src), str(dest))
        metadata = {
            "project_name": project_name,
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "source_dir": str(src),
            "archive_dir": str(dest),
        }
        write_json(dest / "archive.json", metadata)
        return {"ok": True, **metadata}


def import_keyword_project(
    project_name: str,
    keyword_path: str,
    allow_external: bool = False,
    max_bytes: int = MAX_IMPORT_BYTES,
    if_exists: str = "error",
    force_close_runtime: bool = False,
) -> JSONDict:
    with ProjectLock(project_name):
        return _import_keyword_project_locked(project_name, keyword_path, allow_external, max_bytes, if_exists, force_close_runtime)


def _import_keyword_project_locked(
    project_name: str,
    keyword_path: str,
    allow_external: bool,
    max_bytes: int,
    if_exists: str,
    force_close_runtime: bool = False,
) -> JSONDict:
    if if_exists not in ALLOWED_IF_EXISTS:
        raise ValueError(f"if_exists must be one of {', '.join(sorted(ALLOWED_IF_EXISTS))}")
    if max_bytes <= 0 or max_bytes > MAX_IMPORT_BYTES:
        raise ValueError(f"max_bytes must be between 1 and {MAX_IMPORT_BYTES}")
    src = Path(keyword_path).resolve()
    if not src.exists():
        raise FileNotFoundError(f"keyword file not found: {src}")
    validate_import_source(src, allow_external, max_bytes)
    path = project_dir(project_name)
    final_project_name = safe_project_name(project_name)
    if path.exists():
        if if_exists == "error":
            raise FileExistsError(f"project already exists: {path}; use if_exists=overwrite, archive_then_write, or versioned")
        if if_exists == "versioned":
            path = next_versioned_project_dir(project_name)
            final_project_name = path.name
        else:
            ensure_no_active_runtime(path, force_close_runtime)
    raw = src.read_bytes()
    text = raw.decode("utf-8")
    tmp_path = temp_project_dir(path)
    if tmp_path.exists():
        shutil.rmtree(tmp_path)
    tmp_path.mkdir(parents=True)
    mark_runtime_artifact(tmp_path)
    keyword_out = tmp_path / "model.k"
    keyword_out.write_text(text, encoding="utf-8")
    metadata = parse_keyword_metadata(text)
    metadata["model_type"] = "imported_keyword"
    metadata["unit_system"] = "unknown"
    metadata["source_keyword"] = str(src)
    metadata["source_size_bytes"] = len(raw)
    metadata["source_is_external"] = not is_allowed_import_path(src)
    metadata["allow_external"] = allow_external
    metadata["imported_at"] = datetime.now(timezone.utc).isoformat()
    write_json(
        tmp_path / "model.json",
        {
            "schema_version": "0.2.0",
            "spec": {"project_name": final_project_name, "model_type": "imported_keyword", "source_keyword": str(src)},
            "metadata": metadata,
        },
    )
    write_server_cfile(tmp_path, "open_model.cfile", "open_keyword.cfile", {"keyword_path": "model.k"}, if_exists="overwrite")
    checks = validate_project_files(tmp_path)
    write_json(tmp_path / "checks.json", checks)
    commit_project_dir(tmp_path, path, if_exists)
    remove_runtime_artifact(path)
    checks = validate_project_files(path)
    write_json(path / "checks.json", checks)
    return {
        "project": final_project_name,
        "project_dir": str(path),
        "keyword_path": str(path / "model.k"),
        "source_keyword": str(src),
        "metadata": metadata,
        "checks": checks,
        "if_exists": if_exists,
    }


def validate_import_source(src: Path, allow_external: bool, max_bytes: int) -> None:
    if src.suffix.lower() not in {".k", ".key", ".dyn"}:
        raise ValueError("keyword_path must use .k, .key, or .dyn extension for a complete keyword deck")
    if not is_allowed_import_path(src) and not allow_external:
        raise ValueError("keyword_path is outside the project root; pass allow_external=true to import external files")
    size = src.stat().st_size
    if size <= 0:
        raise ValueError("keyword file is empty")
    if size > max_bytes:
        raise ValueError(f"keyword file is too large: {size} bytes exceeds {max_bytes}")
    raw = src.read_bytes()
    if b"\x00" in raw:
        raise ValueError("keyword file appears to be binary")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("keyword file must be valid UTF-8 text") from exc
    first_card = next((keyword_card_token(line) for line in text.splitlines() if line.strip() and not line.strip().startswith("$")), "")
    if first_card not in {"*KEYWORD", "*KEYWORD_ID"}:
        raise ValueError("keyword file must start with *KEYWORD as the first non-comment card")


def is_allowed_import_path(src: Path) -> bool:
    root = ROOT.resolve()
    imports = IMPORTS_DIR.resolve()
    return root == src or root in src.parents or imports == src or imports in src.parents

def parse_keyword_metadata(text: str) -> JSONDict:
    lines = [line.strip() for line in text.splitlines()]
    tokens = [keyword_card_token(line) for line in lines]
    card_counts = {
        "node_count": 0,
        "element_count": 0,
        "part_count": sum(1 for token in tokens if token == "*PART"),
        "material_count": sum(1 for token in tokens if token.startswith("*MAT_")),
        "section_count": sum(1 for token in tokens if token.startswith("*SECTION_")),
        "constraint_count": sum(1 for token in tokens if token.startswith("*BOUNDARY_")),
        "node_set_count": sum(1 for token in tokens if token.startswith("*SET_NODE")),
    }
    current = None
    for line in lines:
        token = keyword_card_token(line)
        if token:
            current = token
            continue
        if not line or line.startswith("$"):
            continue
        if current == "*NODE":
            card_counts["node_count"] += 1
        elif current in {"*ELEMENT_SHELL", "*ELEMENT_SOLID"}:
            card_counts["element_count"] += 1
    element_family = "solid" if "*ELEMENT_SOLID" in tokens else "shell" if "*ELEMENT_SHELL" in tokens else "imported"
    card_counts["element_family"] = element_family
    card_counts.update(parse_keyword_references(text.splitlines()))
    return card_counts


def parse_keyword_references(lines: list[str]) -> JSONDict:
    material_ids: set[int] = set()
    section_ids: set[int] = set()
    part_references: list[JSONDict] = []

    def numeric_fields(line: str) -> list[int]:
        if not line or line.startswith("$"):
            return []
        chunks = line.split(",") if "," in line else line.split()
        values: list[int] = []
        for chunk in chunks:
            token = chunk.strip()
            if not token:
                continue
            try:
                values.append(int(float(token)))
            except ValueError:
                return []
        return values

    def next_numeric_fields(start: int) -> list[int]:
        for item in lines[start + 1 :]:
            if keyword_card_token(item):
                return []
            fields = numeric_fields(item)
            if fields:
                return fields
        return []

    for index, line in enumerate(lines):
        token = keyword_card_token(line)
        if token.startswith("*MAT_") and not token.startswith("*MAT_ADD_"):
            fields, _ = material_header_fields(lines, index)
            if fields:
                material_ids.add(int(fields[0]))
        elif token.startswith("*SECTION_"):
            fields = next_numeric_fields(index)
            if fields:
                section_ids.add(fields[0])
        elif token == "*PART":
            fields = next_numeric_fields(index)
            if len(fields) >= 3:
                part_references.append({"pid": fields[0], "section_id": fields[1], "material_id": fields[2]})
            elif fields:
                part_references.append({"pid": fields[0], "section_id": None, "material_id": None})

    referenced_materials = {int(item["material_id"]) for item in part_references if item.get("material_id")}
    referenced_sections = {int(item["section_id"]) for item in part_references if item.get("section_id")}
    missing_material_refs = sorted(referenced_materials - material_ids)
    missing_section_refs = sorted(referenced_sections - section_ids)
    semantic_warnings: list[str] = []
    if part_references and missing_material_refs:
        semantic_warnings.append(f"parts reference missing material ids: {missing_material_refs}")
    if part_references and missing_section_refs:
        semantic_warnings.append(f"parts reference missing section ids: {missing_section_refs}")
    if not part_references and any(keyword_card_token(line) == "*PART" for line in lines):
        semantic_warnings.append("part cards were found, but pid/section/material references could not be parsed")

    return {
        "material_ids": sorted(material_ids),
        "section_ids": sorted(section_ids),
        "part_references": part_references,
        "missing_material_refs": missing_material_refs,
        "missing_section_refs": missing_section_refs,
        "semantic_warnings": semantic_warnings,
    }
