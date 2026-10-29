from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import artifacts_dir
from .config import ROOT
from .io import read_json, write_json
from .locks import ProjectLock


CFILE_TEMPLATE_DIR = ROOT / "resources" / "templates" / "cfile"
SERVER_CFILE_NAMES = {
    "open_keyword.cfile",
    "open_result_pressure.cfile",
    "open_result_stress.cfile",
    "preview_image.cfile",
    "result_pressure.cfile",
    "result_stress.cfile",
}
CFILE_TEMPLATE_PARAMS = {
    "open_keyword.cfile": {"keyword_path"},
    "preview_image.cfile": {"keyword_path", "output_path", "view_command", "display_commands", "fit_command", "kwdmsg_path"},
    "result_stress.cfile": {
        "d3plot_path",
        "output_path",
        "view_command",
        "state_number",
        "display_commands",
    },
    "result_pressure.cfile": {
        "d3plot_path",
        "output_path",
        "view_command",
        "state_number",
        "display_commands",
    },
    "open_result_pressure.cfile": {
        "d3plot_path",
        "view_command",
        "state_number",
        "display_commands",
    },
    "open_result_stress.cfile": {
        "d3plot_path",
        "view_command",
        "state_number",
        "display_commands",
    },
}
UNSAFE_CFILE_STRING_CHARS = {'"', "\r", "\n"}
UNSAFE_CFILE_COMMAND_CHARS = {'"', "\r"}
CFILE_MANIFEST_NAME = "cfiles.json"


def cfile_template_path(name: str) -> Path:
    if name not in SERVER_CFILE_NAMES:
        raise ValueError(f"unsupported cfile template: {name}")
    path = (CFILE_TEMPLATE_DIR / name).resolve()
    root = CFILE_TEMPLATE_DIR.resolve()
    if root != path.parent:
        raise ValueError("cfile template path escaped template directory")
    return path


def render_cfile_template(name: str, params: dict[str, object] | None = None) -> str:
    path = cfile_template_path(name)
    params = default_cfile_template_params(name, params or {})
    validate_cfile_template_params(name, params)
    text = path.read_text(encoding="utf-8")
    for key, value in params.items():
        placeholder = "{{" + key + "}}"
        text = text.replace(placeholder, render_cfile_param(key, value))
    if "{{" in text or "}}" in text:
        raise ValueError(f"missing cfile template parameter for {name}")
    return text


def default_cfile_template_params(name: str, params: dict[str, object]) -> dict[str, object]:
    merged = dict(params)
    if name == "preview_image.cfile":
        merged.setdefault("view_command", "")
        merged.setdefault("display_commands", "")
        merged.setdefault("fit_command", "ac")
        merged.setdefault("kwdmsg_path", "keyword_reader_messages.xml")
    if name in {
        "result_stress.cfile",
        "result_pressure.cfile",
        "open_result_pressure.cfile",
        "open_result_stress.cfile",
    }:
        merged.setdefault("display_commands", "")
    return merged


def validate_cfile_template_params(name: str, params: dict[str, object]) -> None:
    allowed = CFILE_TEMPLATE_PARAMS.get(name)
    if allowed is None:
        raise ValueError(f"unsupported cfile template: {name}")
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise ValueError(f"unsupported cfile template parameter(s): {', '.join(unknown)}")


def render_cfile_string(value: object) -> str:
    text = str(value)
    if any(ch in text for ch in UNSAFE_CFILE_STRING_CHARS) or "{{" in text or "}}" in text:
        raise ValueError("cfile template parameter contains unsafe characters")
    return text


def render_cfile_param(key: str, value: object) -> str:
    if key == "display_commands":
        return render_cfile_commands(value)
    if key == "state_number":
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1_000_000:
            raise ValueError("state_number must be an integer between 1 and 1000000")
        return str(value)
    return render_cfile_string(value)


def render_cfile_commands(value: object) -> str:
    text = str(value)
    if any(ch in text for ch in UNSAFE_CFILE_COMMAND_CHARS) or "{{" in text or "}}" in text:
        raise ValueError("cfile command parameter contains unsafe characters")
    lines = text.splitlines()
    for line in lines:
        if line.strip() != line:
            raise ValueError("cfile command lines must not have leading or trailing whitespace")
    return "\n".join(lines)


def validate_server_cfile_path(project_path: Path, cfile_path: Path) -> Path:
    resolved = cfile_path.resolve()
    project = project_path.resolve()
    templates = CFILE_TEMPLATE_DIR.resolve()
    artifacts = (project / "artifacts").resolve()
    if resolved == project / "open_model.cfile" and is_manifested_server_cfile(project, resolved):
        return resolved
    if artifacts == resolved.parent and resolved.suffix.lower() == ".cfile" and is_manifested_server_cfile(project, resolved):
        return resolved
    raise ValueError("cfile path must be a manifest-verified project cfile")


def write_server_cfile(
    project_path: Path,
    filename: str,
    template_name: str,
    params: dict[str, object] | None = None,
    if_exists: str = "error",
) -> tuple[Path, dict[str, object]]:
    with ProjectLock(project_path.name, namespace="cfile_manifest"):
        if filename == "open_model.cfile":
            target = project_path / filename
            if target.exists() and if_exists == "error":
                raise FileExistsError(f"cfile already exists: {target}")
            if if_exists not in {"error", "overwrite"}:
                raise ValueError("root cfile if_exists must be error or overwrite")
        else:
            from .artifacts import artifact_path

            target = artifact_path(project_path, filename, if_exists=if_exists)
        text = render_cfile_template(template_name, params)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{target.name}.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.tmp")
        try:
            temp.write_text(text, encoding="utf-8")
            _validate_server_cfile_content(temp, template_name, params)
            os.replace(temp, target)
            return target, _register_server_cfile_locked(project_path, target, template_name, params)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass


def cfile_manifest_path(project_path: Path) -> Path:
    return artifacts_dir(project_path) / CFILE_MANIFEST_NAME


def read_cfile_manifest(project_path: Path) -> list[dict[str, object]]:
    path = cfile_manifest_path(project_path)
    if not path.exists():
        return []
    data = read_json(path)
    entries = data.get("cfiles", []) if isinstance(data, dict) else []
    return [entry for entry in entries if isinstance(entry, dict)]


def write_cfile_manifest(project_path: Path, entries: list[dict[str, object]]) -> None:
    write_json(cfile_manifest_path(project_path), {"schema_version": "0.1.0", "cfiles": entries})


def register_server_cfile(
    project_path: Path,
    cfile_path: Path,
    template_name: str,
    params: dict[str, object] | None = None,
) -> dict[str, object]:
    if template_name not in SERVER_CFILE_NAMES:
        raise ValueError(f"unsupported cfile template: {template_name}")
    project = project_path.resolve()
    cfile = cfile_path.resolve()
    if project != cfile.parent and project not in cfile.parents:
        raise ValueError("cfile path escaped project directory")
    if cfile.suffix.lower() != ".cfile":
        raise ValueError("server cfile must use .cfile suffix")
    if not cfile.exists():
        raise FileNotFoundError(f"cfile not found: {cfile}")
    with ProjectLock(project.name, namespace="cfile_manifest"):
        return _register_server_cfile_locked(project, cfile, template_name, params)


def _register_server_cfile_locked(
    project_path: Path,
    cfile_path: Path,
    template_name: str,
    params: dict[str, object] | None = None,
) -> dict[str, object]:
    project = project_path.resolve()
    cfile = cfile_path.resolve()
    _validate_server_cfile_content(cfile, template_name, params)
    entry = {
        "relative_path": str(cfile.relative_to(project)),
        "template": template_name,
        "params": params or {},
        "sha256": file_sha256(cfile),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "lsprepost-mcp",
    }
    entries = [
        existing
        for existing in read_cfile_manifest(project)
        if existing.get("relative_path") != entry["relative_path"]
    ]
    entries.append(entry)
    write_cfile_manifest(project, entries)
    return entry


def _validate_server_cfile_content(cfile_path: Path, template_name: str, params: dict[str, object] | None) -> None:
    expected = render_cfile_template(template_name, params)
    actual = cfile_path.read_text(encoding="utf-8")
    if actual != expected:
        raise ValueError("server cfile content does not match rendered template")


def is_manifested_server_cfile(project_path: Path, cfile_path: Path) -> bool:
    project = project_path.resolve()
    cfile = cfile_path.resolve()
    try:
        relative = str(cfile.relative_to(project))
    except ValueError:
        return False
    if not cfile.exists() or not cfile.is_file():
        return False
    digest = file_sha256(cfile)
    for entry in read_cfile_manifest(project):
        if entry.get("relative_path") == relative and entry.get("sha256") == digest and entry.get("generated_by") == "lsprepost-mcp":
            return True
    return False


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
