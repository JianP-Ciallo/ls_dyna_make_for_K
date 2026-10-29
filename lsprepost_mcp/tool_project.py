from __future__ import annotations

from .config import JSONDict
from .io import read_json, write_json
from .locks import ProjectLock
from .paths import find_project_dir
from .project_store import (
    archive_project,
    build_model_summary,
    import_keyword_project,
    iter_project_records,
    project_checks_are_current,
    validate_project_files,
)
from .tool_helpers import bool_arg


def tool_validate_model(args: JSONDict) -> JSONDict:
    name = str(args.get("project_name", "plate_demo"))
    with ProjectLock(name):
        path = find_project_dir(name)
        if not path.exists():
            raise FileNotFoundError(f"project not found: {args.get('project_name')}")
        checks = validate_project_files(path)
        write_json(path / "checks.json", checks)
        return checks


def tool_model_summary(args: JSONDict) -> JSONDict:
    path = find_project_dir(str(args.get("project_name", "generic_plate_demo")))
    if not path.exists():
        raise FileNotFoundError(f"project not found: {args.get('project_name')}")
    return build_model_summary(path)


def tool_list_projects(args: JSONDict) -> JSONDict:
    include_archived = bool_arg(args, "include_archived", True)
    records = iter_project_records()
    if not include_archived:
        records = [record for record in records if record["source"] != "archive"]
    return {"projects": records, "count": len(records)}


def tool_read_project(args: JSONDict) -> JSONDict:
    name = str(args.get("project_name", "generic_plate_demo"))
    with ProjectLock(name):
        path = find_project_dir(name)
        if not path.exists():
            raise FileNotFoundError(f"project not found: {args.get('project_name')}")
        model_path = path / "model.json"
        checks_path = path / "checks.json"
        if not model_path.exists():
            raise FileNotFoundError(f"model.json not found: {model_path}")
        previous_status = "missing"
        checks: JSONDict | None = None
        if checks_path.exists():
            try:
                candidate = read_json(checks_path)
            except (OSError, ValueError):
                previous_status = "invalid"
            else:
                if project_checks_are_current(path, candidate):
                    checks = candidate
                    previous_status = "current"
                else:
                    previous_status = "stale"
        revalidated = checks is None
        if revalidated:
            checks = validate_project_files(path)
            write_json(checks_path, checks)
        return {
            "project_dir": str(path),
            "model": read_json(model_path),
            "checks": checks,
            "checks_freshness": {
                "status": "current",
                "previous_status": previous_status,
                "revalidated": revalidated,
            },
            "summary": build_model_summary(path),
        }


def tool_archive_project(args: JSONDict) -> JSONDict:
    return archive_project(
        str(args.get("project_name", "")),
        str(args.get("confirm_project_name", "")),
        str(args.get("reason", "")),
    )


def tool_import_keyword(args: JSONDict) -> JSONDict:
    project_name = str(args.get("project_name", "imported_keyword"))
    keyword_path = str(args.get("keyword_path", ""))
    if not keyword_path:
        raise ValueError("keyword_path is required")
    return import_keyword_project(
        project_name,
        keyword_path,
        allow_external=bool_arg(args, "allow_external", False),
        max_bytes=int(args.get("max_bytes", 10 * 1024 * 1024)),
        if_exists=str(args.get("if_exists", "error")),
    )
