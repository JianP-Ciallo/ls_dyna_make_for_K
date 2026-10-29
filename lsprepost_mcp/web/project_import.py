from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lsprepost_mcp.config import JSONDict
from lsprepost_mcp.io import read_json, write_json
from lsprepost_mcp.locks import ProjectLock
from lsprepost_mcp.paths import project_dir, safe_project_name
from lsprepost_mcp.project_store import (
    commit_project_dir,
    ensure_no_active_runtime,
    mark_runtime_artifact,
    next_versioned_project_dir,
    remove_runtime_artifact,
    temp_project_dir,
    validate_project_files,
)
from lsprepost_mcp.web.http_utils import ApiError, reject_json_constant
from lsprepost_mcp.web.native_dialogs import NativeDialogUnavailable, choose_directory


REQUIRED_IMPORT_FILES = ("model.k", "model.json", "checks.json")
OPTIONAL_IMPORT_FILES = ("export_manifest.json",)
JSON_IMPORT_FILES = ("model.json", "checks.json")
ALLOWED_IF_EXISTS = {"error", "overwrite", "versioned"}
MAX_IMPORT_PACKAGE_BYTES = 100 * 1024 * 1024


def inspect_project_package(source_dir: Path) -> JSONDict:
    source = source_dir.resolve()
    if not source.is_dir():
        raise ApiError(400, "invalid_import_package", "请选择一个模型文件夹")

    missing = [name for name in REQUIRED_IMPORT_FILES if not (source / name).is_file()]
    if missing:
        raise ApiError(
            400,
            "invalid_import_package",
            "模型文件夹不完整，缺少：" + "、".join(missing),
        )

    present_files = list(REQUIRED_IMPORT_FILES)
    present_files.extend(name for name in OPTIONAL_IMPORT_FILES if (source / name).is_file())

    total_size = 0
    for name in present_files:
        candidate = source / name
        if candidate.is_symlink():
            raise ApiError(400, "invalid_import_package", f"{name} must not be a symbolic link")
        total_size += candidate.stat().st_size
        if total_size > MAX_IMPORT_PACKAGE_BYTES:
            raise ApiError(
                413,
                "import_package_too_large",
                f"model package must not exceed {MAX_IMPORT_PACKAGE_BYTES} bytes",
            )

    try:
        keyword = (source / "model.k").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ApiError(400, "invalid_import_package", "model.k must be a UTF-8 text file") from exc
    if "\x00" in keyword:
        raise ApiError(400, "invalid_import_package", "model.k must not contain NUL bytes")

    decoded: JSONDict = {}
    json_files = list(JSON_IMPORT_FILES)
    json_files.extend(name for name in OPTIONAL_IMPORT_FILES if (source / name).is_file())
    for name in json_files:
        try:
            value = json.loads(
                (source / name).read_text(encoding="utf-8"),
                parse_constant=reject_json_constant,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ApiError(400, "invalid_import_package", f"{name} 不是有效的模型信息文件") from exc
        if not isinstance(value, dict):
            raise ApiError(400, "invalid_import_package", f"{name} must contain a JSON object")
        decoded[name] = value

    return {
        "source_dir": str(source),
        "required_files": list(REQUIRED_IMPORT_FILES),
        "present_files": present_files,
        "manifest_present": "export_manifest.json" in present_files,
        "checks_ok": bool(decoded.get("checks.json", {}).get("ok")) if isinstance(decoded.get("checks.json"), dict) else False,
        "size_bytes": total_size,
    }


def import_project_package(source_dir: Path, project_name: str = "", if_exists: str = "versioned") -> JSONDict:
    package = inspect_project_package(source_dir)
    if if_exists not in ALLOWED_IF_EXISTS:
        raise ApiError(400, "invalid_import_package", "if_exists must be error, overwrite, or versioned")

    source = Path(package["source_dir"])
    base_name = safe_project_name(project_name.strip() if project_name.strip() else source.name)
    with ProjectLock(base_name):
        target = project_dir(base_name)
        if target.exists():
            if if_exists == "error":
                raise ApiError(409, "project_exists", "项目已存在，请换一个项目名称")
            if if_exists == "versioned":
                target = next_versioned_project_dir(base_name)
            else:
                ensure_no_active_runtime(target)
        temp = temp_project_dir(target)
        copied: list[str] = []
        generated: list[str] = []
        try:
            temp.mkdir(parents=True)
            mark_runtime_artifact(temp)
            for name in package["present_files"]:
                shutil.copy2(source / name, temp / name)
                copied.append(name)

            inspect_project_package(temp)
            model = read_json(temp / "model.json")
            spec = model.get("spec")
            if not isinstance(spec, dict):
                raise ApiError(400, "invalid_import_package", "model.json spec must be a JSON object")
            spec["project_name"] = target.name
            write_json(temp / "model.json", model)

            checks = validate_project_files(temp)
            write_json(temp / "checks.json", checks)
            if not package["manifest_present"]:
                write_json(
                    temp / "export_manifest.json",
                    {
                        "schema_version": "0.2.0",
                        "source_project_name": source.name,
                        "imported_project_name": target.name,
                        "files": list(REQUIRED_IMPORT_FILES),
                        "saved_at_utc": datetime.now(timezone.utc).isoformat(),
                        "provenance": {
                            "kind": "reconstructed_on_import",
                            "original_manifest_present": False,
                        },
                    },
                )
                generated.append("export_manifest.json")
            commit_project_dir(temp, target, "overwrite" if target.exists() else "error")
            remove_runtime_artifact(target)
        finally:
            if temp.exists():
                shutil.rmtree(temp)

    return {
        "operation": "import_project_package",
        "project_name": target.name,
        "project_dir": str(target),
        "source_dir": str(source),
        "copied_files": copied,
        "generated_files": generated,
        "manifest_reconstructed": bool(generated),
        "checks_ok": bool(checks.get("ok")),
        "size_bytes": package["size_bytes"],
    }


def import_project_package_payload(payload: JSONDict) -> JSONDict:
    raw_source = payload.get("source_dir")
    if not isinstance(raw_source, str) or not raw_source.strip():
        raise ApiError(400, "invalid_import_package", "source_dir must be a non-empty string")
    project_name = str(payload.get("project_name", "") or "")
    if_exists = str(payload.get("if_exists", "versioned") or "versioned")
    return import_project_package(Path(raw_source.strip()), project_name, if_exists=if_exists)


def select_import_project_package_payload(payload: JSONDict) -> JSONDict:
    try:
        selected = choose_import_package_dir()
    except NativeDialogUnavailable as exc:
        raise ApiError(503, "native_dialog_unavailable", str(exc)) from exc
    if selected is None:
        raise ApiError(400, "selection_cancelled", "模型文件夹选择已取消")
    project_name = str(payload.get("project_name", "") or "")
    if_exists = str(payload.get("if_exists", "versioned") or "versioned")
    return import_project_package(selected, project_name, if_exists=if_exists)


def choose_import_package_dir() -> Optional[Path]:
    return choose_directory("选择完整模型文件夹")
