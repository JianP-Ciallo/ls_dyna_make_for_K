from __future__ import annotations

from typing import Callable, Protocol
from pathlib import Path

from .artifacts import artifact_path
from .cfile import validate_server_cfile_path, write_server_cfile
from .config import JSONDict
from .io import read_json, write_json
from .locks import ProjectLock
from .lspp import launcher as default_launcher
from .lspp.launcher import require_lsprepost_exe
from .lspp.launcher import validate_d3plot_path
from .paths import find_project_dir
from .project_store import validate_project_files
from .readiness import require_action_readiness
from .tool_helpers import (
    MAX_GUI_TIMEOUT_S,
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


class LSPrePostLauncher(Protocol):
    """External execution dependency; callers may supply an isolated launcher."""

    launch_cfile: Callable[..., JSONDict]
    launch_keyword: Callable[..., JSONDict]
    launch_d3plot: Callable[..., JSONDict]


def tool_open_in_lsprepost(
    args: JSONDict, *, launcher: LSPrePostLauncher = default_launcher
) -> JSONDict:
    name = str(args.get("project_name", "plate_demo"))
    force = bool_arg(args, "force", False)
    timeout_s = float(args.get("timeout_s", 0) or 0)
    if timeout_s < 0 or timeout_s > MAX_GUI_TIMEOUT_S:
        raise ValueError(f"timeout_s must be between 0 and {MAX_GUI_TIMEOUT_S:g} seconds")
    allow_multiple = bool_arg(args, "allow_multiple", False)
    if allow_multiple and str(args.get("manual_ack", "")) != "allow_multiple_lsprepost":
        raise ValueError("allow_multiple requires manual_ack='allow_multiple_lsprepost'")
    with ProjectLock(name):
        path = find_project_dir(name)
        keyword_path = path / "model.k"
        if not path.exists():
            raise FileNotFoundError(f"project not found: {name}")
        checks = validate_project_files(path)
        write_json(path / "checks.json", checks)
        readiness = require_action_readiness("open_in_lsprepost", checks, force=force)
    record = launcher.launch_keyword(path, keyword_path, timeout_s=timeout_s if timeout_s > 0 else None, allow_multiple=allow_multiple)
    return {
        "ok": True,
        **record,
        "readiness": readiness,
    }


def tool_open_result_lsprepost(
    args: JSONDict, *, launcher: LSPrePostLauncher = default_launcher
) -> JSONDict:
    name = str(args.get("project_name", "plate_demo"))
    timeout_s = float(args.get("timeout_s", 0) or 0)
    if timeout_s < 0 or timeout_s > MAX_GUI_TIMEOUT_S:
        raise ValueError(
            f"timeout_s must be between 0 and {MAX_GUI_TIMEOUT_S:g} seconds"
        )
    path = find_project_dir(name)
    if not path.is_dir():
        raise FileNotFoundError(f"project not found: {name}")
    run_id = args.get("run_id")
    d3plot = _resolve_qualified_d3plot(path, run_id)
    record = launcher.launch_d3plot(
        path,
        d3plot,
        timeout_s=timeout_s if timeout_s > 0 else None,
    )
    return {
        "ok": True,
        "project_name": name,
        "project_dir": str(path),
        "run_id": d3plot.parent.name,
        "d3plot_path": str(d3plot),
        "launch_record": record,
    }


def _resolve_qualified_d3plot(project: Path, run_id: object) -> Path:
    runs_dir = project / "solver_runs"
    if not runs_dir.is_dir():
        raise FileNotFoundError("project has no solver_runs directory")
    if run_id is not None:
        if (
            not isinstance(run_id, str)
            or not run_id
            or Path(run_id).name != run_id
            or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for char in run_id)
        ):
            raise ValueError("run_id must be a safe simple identifier")
        candidates = [runs_dir / run_id / "d3plot"]
    else:
        candidates = [
            run_dir / "d3plot"
            for run_dir in sorted(
                (
                    item
                    for item in runs_dir.iterdir()
                    if item.is_dir() and not item.name.startswith(".")
                ),
                key=lambda item: item.name,
                reverse=True,
            )
        ]
    errors: list[str] = []
    for candidate in candidates:
        try:
            return validate_d3plot_path(project, candidate)
        except (FileNotFoundError, ValueError) as exc:
            errors.append(str(exc))
    if run_id is not None:
        raise ValueError(f"run is not qualified for LS-PrePost: {errors}")
    raise FileNotFoundError(
        "no completed qualified d3plot result is available"
        + (f": {errors}" if errors else "")
    )


def tool_export_preview_image(
    args: JSONDict, *, launcher: LSPrePostLauncher = default_launcher
) -> JSONDict:
    name = str(args.get("project_name", "plate_demo"))
    timeout_s = automation_timeout(args, default=45.0)
    output_filename = str(args.get("output_filename", "preview.png"))
    view = preview_view_arg(args)
    display_mode = preview_display_mode_arg(args)
    auto_fit = bool_arg(args, "auto_fit", True)
    if_exists = str(args.get("if_exists", "overwrite"))
    with ProjectLock(name):
        path = find_project_dir(name)
        if not path.exists():
            raise FileNotFoundError(f"project not found: {name}")
        checks = validate_project_files(path)
        write_json(path / "checks.json", checks)
        readiness = require_action_readiness("export_preview_image", checks)
        output = artifact_path(path, output_filename, if_exists=if_exists)
        if output.suffix.lower() != ".png":
            raise ValueError("output_filename must use .png suffix")
        kwdmsg = artifact_path(path, preview_keyword_reader_filename(output), if_exists="overwrite")
        cfile_name = preview_cfile_filename(output)
        cfile, manifest = write_server_cfile(
            path,
            cfile_name,
            "preview_image.cfile",
            {
                "keyword_path": "model.k",
                "output_path": cfile_relative_path(path, output),
                "view_command": PREVIEW_VIEW_COMMANDS[view],
                "display_commands": preview_display_commands(display_mode),
                "fit_command": "ac" if auto_fit else "",
                "kwdmsg_path": cfile_relative_path(path, kwdmsg),
            },
            if_exists="overwrite",
        )
    record: JSONDict = {}
    try:
        record = launcher.launch_cfile(path, cfile, timeout_s=timeout_s)
        verification = verify_png_artifact(output)
        keyword_reader = verify_keyword_reader_messages(kwdmsg)
        result = {
            "ok": verification["ok"],
            "project_name": name,
            "project_dir": str(path),
            "keyword_path": str(path / "model.k"),
            "output_path": str(output),
            "view": view,
            "display_controls": {
                "display_mode": display_mode,
                "auto_fit": auto_fit,
                "mesh_lines": "default_ls_prepost_rendering",
                "part_colors": "default_ls_prepost_part_coloring",
            },
            "cfile_path": str(cfile),
            "cfile_manifest": manifest,
            "readiness": readiness,
            "launch_record": record,
            "verification": verification,
            "keyword_reader": keyword_reader,
        }
        record_lsprepost_verification(path, "export_preview_image", result)
        return result
    except Exception as exc:
        record_lsprepost_verification(
            path,
            "export_preview_image",
            failed_lsprepost_result(
                exc,
                {
                    "project_name": name,
                    "project_dir": str(path),
                    "keyword_path": str(path / "model.k"),
                    "output_path": str(output),
                    "view": view,
                    "cfile_path": str(cfile),
                    "cfile_manifest": manifest,
                    "readiness": readiness,
                    "launch_record": record,
                },
            ),
        )
        raise


def tool_export_preview_images(
    args: JSONDict, *, launcher: LSPrePostLauncher = default_launcher
) -> JSONDict:
    name = str(args.get("project_name", "plate_demo"))
    timeout_s = automation_timeout(args, default=45.0)
    views = preview_views_arg(args)
    output_prefix = preview_output_prefix_arg(args)
    display_mode = preview_display_mode_arg(args)
    auto_fit = bool_arg(args, "auto_fit", True)
    if_exists = str(args.get("if_exists", "overwrite"))
    results = []
    for view in views:
        result = tool_export_preview_image(
            {
                "project_name": name,
                "output_filename": f"{output_prefix}_{view}.png",
                "view": view,
                "display_mode": display_mode,
                "auto_fit": auto_fit,
                "timeout_s": timeout_s,
                "if_exists": if_exists,
            },
            launcher=launcher,
        )
        results.append(result)
    return {
        "ok": all(item.get("ok") and item.get("keyword_reader", {}).get("ok") for item in results),
        "project_name": name,
        "views": views,
        "display_mode": display_mode,
        "auto_fit": auto_fit,
        "count": len(results),
        "results": results,
    }


def tool_export_preview_gif(
    args: JSONDict, *, launcher: LSPrePostLauncher = default_launcher
) -> JSONDict:
    name = str(args.get("project_name", "plate_demo"))
    timeout_s = automation_timeout(args, default=45.0)
    views = preview_views_arg({"views": args.get("views", ["iso", "top", "front"])})
    output_filename = str(args.get("output_filename", "preview_summary.gif"))
    output_prefix = preview_output_prefix_arg(args)
    display_mode = preview_display_mode_arg(args)
    auto_fit = bool_arg(args, "auto_fit", True)
    duration_ms = gif_duration_arg(args)
    if_exists = str(args.get("if_exists", "overwrite"))
    with ProjectLock(name):
        path = find_project_dir(name)
        if not path.exists():
            raise FileNotFoundError(f"project not found: {name}")
        output = artifact_path(path, output_filename, if_exists=if_exists)
        if output.suffix.lower() != ".gif":
            raise ValueError("output_filename must use .gif suffix")
    try:
        preview_images = tool_export_preview_images(
            {
                "project_name": name,
                "views": views,
                "output_prefix": output_prefix,
                "display_mode": display_mode,
                "auto_fit": auto_fit,
                "timeout_s": timeout_s,
                "if_exists": "overwrite",
            },
            launcher=launcher,
        )
        frame_paths = [Path(item["output_path"]) for item in preview_images["results"]]
        write_preview_gif(frame_paths, output, duration_ms=duration_ms)
        verification = verify_gif_artifact(output)
        result = {
            "ok": True,
            "project_name": name,
            "project_dir": str(path),
            "output_path": str(output),
            "views": views,
            "duration_ms": duration_ms,
            "frame_count": len(frame_paths),
            "frames": [
                {
                    "view": item["view"],
                    "path": item["output_path"],
                    "size_bytes": item["verification"]["size_bytes"],
                }
                for item in preview_images["results"]
            ],
            "preview_images": preview_images,
            "verification": verification,
        }
        record_lsprepost_verification(path, "export_preview_gif", result)
        return result
    except Exception as exc:
        record_lsprepost_verification(
            path,
            "export_preview_gif",
            failed_lsprepost_result(
                exc,
                {
                    "project_name": name,
                    "project_dir": str(path),
                    "output_path": str(output),
                    "views": views,
                    "duration_ms": duration_ms,
                },
            ),
        )
        raise


def tool_validate_lsprepost_import(
    args: JSONDict, *, launcher: LSPrePostLauncher = default_launcher
) -> JSONDict:
    name = str(args.get("project_name", "plate_demo"))
    view = preview_view_arg({"view": args.get("view", "iso")})
    timeout_s = automation_timeout(args, default=45.0)
    require_lsprepost_exe()
    output_filename = str(args.get("output_filename", f"import_validation_{view}.png"))
    display_mode = preview_display_mode_arg({"display_mode": args.get("display_mode", "validation")})
    auto_fit = bool_arg(args, "auto_fit", True)
    preview = tool_export_preview_image(
        {
            "project_name": name,
            "output_filename": output_filename,
            "view": view,
            "display_mode": display_mode,
            "auto_fit": auto_fit,
            "timeout_s": timeout_s,
            "if_exists": str(args.get("if_exists", "overwrite")),
        },
        launcher=launcher,
    )
    path = find_project_dir(name)
    checks = read_json(path / "checks.json")
    required_keywords = validate_project_required_keywords(path / "model.k", path / "model.json")
    validation = {
        "static_checks_ok": bool(checks.get("ok")),
        "readiness_ok_for_gui_preview": bool(checks.get("readiness", {}).get("ok_for_gui_preview")),
        "keyword_reader_ok": bool(preview.get("keyword_reader", {}).get("ok")),
        "preview_png_ok": bool(preview.get("verification", {}).get("png_signature_ok")),
        "required_keywords": required_keywords,
    }
    result = {
        "ok": all(
            [
                validation["static_checks_ok"],
                validation["readiness_ok_for_gui_preview"],
                validation["keyword_reader_ok"],
                validation["preview_png_ok"],
                required_keywords["ok"],
            ]
        ),
        "project_name": name,
        "project_dir": str(path),
        "keyword_path": str(path / "model.k"),
        "output_path": preview["output_path"],
        "output_relative_path": str(
            Path(preview["output_path"]).resolve().relative_to(path.resolve())
        ).replace("\\", "/"),
        "view": view,
        "display_controls": preview["display_controls"],
        "validation": validation,
        "model_fingerprint": checks.get("validation_fingerprint", {}),
        "preview_result": preview,
    }
    record_lsprepost_verification(path, "validate_lsprepost_import", result)
    return result


def tool_run_cfile(
    args: JSONDict, *, launcher: LSPrePostLauncher = default_launcher
) -> JSONDict:
    name = str(args.get("project_name", "plate_demo"))
    cfile_filename = str(args.get("cfile_filename", "open_model.cfile"))
    timeout_s = automation_timeout(args, default=45.0)
    allow_multiple = bool_arg(args, "allow_multiple", False)
    if allow_multiple and str(args.get("manual_ack", "")) != "allow_multiple_lsprepost":
        raise ValueError("allow_multiple requires manual_ack='allow_multiple_lsprepost'")
    with ProjectLock(name):
        path = find_project_dir(name)
        if not path.exists():
            raise FileNotFoundError(f"project not found: {name}")
        checks = validate_project_files(path)
        write_json(path / "checks.json", checks)
        readiness = require_action_readiness("run_cfile", checks)
        cfile = resolve_project_cfile(path, cfile_filename)
        validate_server_cfile_path(path, cfile)
    record: JSONDict = {}
    try:
        record = launcher.launch_cfile(path, cfile, timeout_s=timeout_s, allow_multiple=allow_multiple)
        returncode = record.get("returncode")
        if returncode != 0:
            raise RuntimeError(f"LS-PrePost cfile did not complete successfully; returncode={returncode}")
        result = {
            "ok": True,
            "status": "completed",
            "project_name": name,
            "project_dir": str(path),
            "cfile_path": str(cfile),
            "readiness": readiness,
            "launch_record": record,
        }
        record_lsprepost_verification(path, "run_cfile", result)
        return result
    except Exception as exc:
        record_lsprepost_verification(
            path,
            "run_cfile",
            failed_lsprepost_result(
                exc,
                {
                    "project_name": name,
                    "project_dir": str(path),
                    "cfile_path": str(cfile),
                    "readiness": readiness,
                    "launch_record": record,
                },
            ),
        )
        raise
