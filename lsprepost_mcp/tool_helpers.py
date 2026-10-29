from __future__ import annotations

import hashlib
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from .artifacts import safe_artifact_filename
from .config import JSONDict
from .io import read_json, write_json
from .locks import ProjectLock


MAX_GUI_TIMEOUT_S = 300.0
MAX_AUTOMATION_TIMEOUT_S = 120.0
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
GIF_SIGNATURES = {b"GIF87a", b"GIF89a"}
PREVIEW_VIEW_COMMANDS = {
    "current": "",
    "iso": "quat 0.880476 0.279848 0.364705 0.115917",
    "top": "quat 1 0 0 0",
    "front": "quat 0.70710678 0.70710678 0 0",
    "side": "quat 0.70710678 0 0.70710678 0",
}
PREVIEW_DISPLAY_MODES = {
    "geometry": (),
    "boundary_conditions": (
        "displayentity Boundary Spc on all",
        "displayentity Boundary Prescribed_Motion on all",
    ),
    "loads_constraints": (
        "displayentity Boundary Spc on all",
        "displayentity Boundary Prescribed_Motion on all",
        "displayentity Load Body on all",
        "displayentity Load Node on all",
        "displayentity Load Segment on all",
    ),
    "sets": (
        "displayentity Set Node on all",
        "displayentity Set Part on all",
        "displayentity Set Segment on all",
    ),
    "validation": (
        "displayentity Boundary Spc on all",
        "displayentity Boundary Prescribed_Motion on all",
        "displayentity Load Body on all",
        "displayentity Load Node on all",
        "displayentity Load Segment on all",
        "displayentity Set Node on all",
        "displayentity Set Part on all",
        "displayentity Set Segment on all",
    ),
}
PHASE6_REQUIRED_KEYWORDS = {
    "parts": "*PART",
    "contact": "*CONTACT_",
    "gravity": "*LOAD_BODY_",
    "fixed_constraint": "*BOUNDARY_SPC",
    "d3plot": "*DATABASE_BINARY_D3PLOT",
}


def bool_arg(args: JSONDict, key: str, default: bool = False) -> bool:
    value = args.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def automation_timeout(args: JSONDict, default: float, allow_zero: bool = False) -> float:
    raw = args.get("timeout_s", default)
    if not (isinstance(raw, int) or isinstance(raw, float)) or isinstance(raw, bool) or not math.isfinite(raw):
        raise ValueError("timeout_s must be a finite number")
    value = float(raw)
    minimum = 0.0 if allow_zero else 0.001
    if value < minimum or value > MAX_AUTOMATION_TIMEOUT_S:
        if allow_zero:
            raise ValueError(f"timeout_s must be between 0 and {MAX_AUTOMATION_TIMEOUT_S:g} seconds")
        raise ValueError(f"timeout_s must be greater than 0 and at most {MAX_AUTOMATION_TIMEOUT_S:g} seconds")
    return value


def preview_view_arg(args: JSONDict) -> str:
    value = str(args.get("view", "current"))
    if value not in PREVIEW_VIEW_COMMANDS:
        raise ValueError(f"view must be one of {', '.join(sorted(PREVIEW_VIEW_COMMANDS))}")
    return value


def preview_display_mode_arg(args: JSONDict) -> str:
    value = str(args.get("display_mode", "geometry"))
    if value not in PREVIEW_DISPLAY_MODES:
        raise ValueError(f"display_mode must be one of {', '.join(sorted(PREVIEW_DISPLAY_MODES))}")
    return value


def preview_display_commands(display_mode: str) -> str:
    if display_mode not in PREVIEW_DISPLAY_MODES:
        raise ValueError(f"display_mode must be one of {', '.join(sorted(PREVIEW_DISPLAY_MODES))}")
    return "\n".join(PREVIEW_DISPLAY_MODES[display_mode])


def preview_views_arg(args: JSONDict) -> list[str]:
    raw = args.get("views", ["iso", "top", "front", "side"])
    if not isinstance(raw, list) or not raw:
        raise ValueError("views must be a non-empty array")
    views: list[str] = []
    for index, value in enumerate(raw):
        if not isinstance(value, str):
            raise ValueError(f"views[{index}] must be a string")
        if value not in PREVIEW_VIEW_COMMANDS:
            raise ValueError(f"views[{index}] must be one of {', '.join(sorted(PREVIEW_VIEW_COMMANDS))}")
        if value in views:
            raise ValueError(f"duplicate preview view: {value}")
        views.append(value)
    return views


def preview_output_prefix_arg(args: JSONDict) -> str:
    value = args.get("output_prefix", "preview")
    if not isinstance(value, str):
        raise ValueError("output_prefix must be a string")
    safe_name = safe_artifact_filename(f"{value}.png")
    return Path(safe_name).stem


def gif_duration_arg(args: JSONDict) -> int:
    raw = args.get("duration_ms", 900)
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ValueError("duration_ms must be an integer")
    if raw <= 0 or raw > 10000:
        raise ValueError("duration_ms must be greater than 0 and at most 10000")
    return raw


def preview_cfile_filename(output_path: Path) -> str:
    return safe_artifact_filename(f"preview_{output_path.stem}.cfile")


def preview_keyword_reader_filename(output_path: Path) -> str:
    if output_path.name == "preview.png":
        return "keyword_reader_messages.xml"
    return safe_artifact_filename(f"keyword_reader_messages_{output_path.stem}.xml")


def cfile_relative_path(project_path: Path, path: Path) -> str:
    return path.resolve().relative_to(project_path.resolve()).as_posix()


def resolve_project_cfile(project_path: Path, filename: str) -> Path:
    safe_name = safe_artifact_filename(filename)
    if safe_name == "open_model.cfile":
        return project_path / safe_name
    if not safe_name.lower().endswith(".cfile"):
        raise ValueError("cfile_filename must use .cfile suffix")
    return project_path / "artifacts" / safe_name


def verify_png_artifact(path: Path) -> JSONDict:
    if not path.exists():
        raise FileNotFoundError(f"preview image was not created: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise ValueError(f"preview image is empty: {path}")
    signature = path.read_bytes()[:8]
    if signature != PNG_SIGNATURE:
        raise ValueError(f"preview image is not a PNG file: {path}")
    return {"ok": True, "path": str(path), "size_bytes": size, "png_signature_ok": True}


def write_preview_gif(frame_paths: list[Path], output_path: Path, duration_ms: int) -> None:
    if not frame_paths:
        raise ValueError("at least one frame is required to build a preview GIF")
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required to build preview GIF artifacts") from exc
    frames = []
    for frame_path in frame_paths:
        verify_png_artifact(frame_path)
        with Image.open(frame_path) as image:
            frames.append(image.convert("P", palette=Image.ADAPTIVE))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    first, rest = frames[0], frames[1:]
    first.save(output_path, save_all=True, append_images=rest, duration=duration_ms, loop=0, optimize=False)


def verify_gif_artifact(path: Path) -> JSONDict:
    if not path.exists():
        raise FileNotFoundError(f"preview GIF was not created: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise ValueError(f"preview GIF is empty: {path}")
    signature = path.read_bytes()[:6]
    if signature not in GIF_SIGNATURES:
        raise ValueError(f"preview artifact is not a GIF file: {path}")
    return {"ok": True, "path": str(path), "size_bytes": size, "gif_signature_ok": True}


def verify_keyword_reader_messages(path: Path) -> JSONDict:
    if not path.exists():
        raise FileNotFoundError(f"keyword reader messages were not created: {path}")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"keyword reader messages XML is invalid: {path}") from exc
    warnings_node = root.find("Warnings")
    errors_node = root.find("Errors")
    warning_count = len(list(warnings_node)) if warnings_node is not None else 0
    error_count = len(list(errors_node)) if errors_node is not None else 0
    if warning_count or error_count:
        raise ValueError(f"keyword reader reported warnings/errors: warnings={warning_count}, errors={error_count}")
    return {
        "ok": True,
        "path": str(path),
        "warnings": warning_count,
        "errors": error_count,
    }


def validate_phase6_required_keywords(keyword_path: Path) -> JSONDict:
    text = keyword_path.read_text(encoding="utf-8", errors="replace").upper()
    items = {
        name: {"keyword": keyword, "present": keyword in text}
        for name, keyword in PHASE6_REQUIRED_KEYWORDS.items()
    }
    missing = [name for name, item in items.items() if not item["present"]]
    return {"ok": not missing, "items": items, "missing": missing}


def validate_project_required_keywords(keyword_path: Path, model_path: Path) -> JSONDict:
    model = read_json(model_path) if model_path.is_file() else {}
    spec = model.get("spec", {}) if isinstance(model, dict) else {}
    if isinstance(spec, dict) and spec.get("model_type") == "b120_spg_sale_rebuild":
        from .b120_spg_sale_rebuild import required_keywords
        return required_keywords(keyword_path, spec)
    text = keyword_path.read_text(encoding="utf-8", errors="replace").upper()
    if isinstance(spec, dict) and spec.get("model_type") in {"gran_r5_mmale_rebuild", "impact_1788_mmale_rebuild"}:
        if spec["model_type"] == "impact_1788_mmale_rebuild":
            from .impact_1788_rebuild import validate_spec
            from .impact_1788_resources import source_index
        else:
            from .gran_r5_rebuild import validate_spec
            from .source_rebuild_resources import source_index
        validate_spec(spec)
        required_cards = {c["keyword"] for r in source_index()["resources"] for c in r["source_cards"]}
        required_cards.update({"*KEYWORD", "*END", "*NODE", "*ELEMENT_SHELL"})
        tokens = {line.strip().split()[0] for line in text.splitlines() if line.lstrip().startswith("*")}
        items = {card: {"keyword": card, "present": card in tokens} for card in sorted(required_cards)}
        missing = [card for card, item in items.items() if not item["present"]]
        return {"ok": not missing, "items": items, "missing": missing}
    contacts = spec.get("contacts", []) if isinstance(spec, dict) else []
    loads = spec.get("loads", []) if isinstance(spec, dict) else []
    required = {
        "parts": "*PART",
        "fixed_constraint": "*BOUNDARY_SPC",
        "d3plot": "*DATABASE_BINARY_D3PLOT",
    }
    if isinstance(contacts, list) and any(isinstance(item, dict) for item in contacts):
        required["contact"] = "*CONTACT_"
    load_types = {
        str(item.get("type"))
        for item in loads
        if isinstance(item, dict) and isinstance(item.get("type"), str)
    }
    if "gravity" in load_types:
        required["gravity"] = "*LOAD_BODY_"
    if "blast_enhanced" in load_types:
        required["blast_load"] = "*LOAD_BLAST_ENHANCED"
        required["blast_output"] = "*DATABASE_BINARY_BLSTFOR"
    if "initial_velocity" in load_types:
        required["initial_velocity"] = "*INITIAL_VELOCITY_NODE"
    if {"pressure_on_segment", "pressure_on_segment_set"} & load_types:
        required["pressure"] = "*LOAD_SEGMENT"
    if "nodal_force" in load_types:
        required["nodal_force"] = "*LOAD_NODE_SET"
    items = {
        name: {"keyword": keyword, "present": keyword in text}
        for name, keyword in required.items()
    }
    missing = [name for name, item in items.items() if not item["present"]]
    return {"ok": not missing, "items": items, "missing": missing}


def failed_lsprepost_result(exc: Exception, context: JSONDict) -> JSONDict:
    return {
        "ok": False,
        "status": "failed",
        **context,
        "error": {
            "type": exc.__class__.__name__,
            "message": str(exc),
        },
    }


def record_lsprepost_verification(project_path: Path, action: str, result: JSONDict) -> None:
    with ProjectLock(project_path.name, namespace="lspp_verifications"):
        path = project_path / "artifacts" / "lspp_verifications.json"
        previous: list[JSONDict] = []
        if path.exists():
            data = read_json(path)
            entries = data.get("verifications", []) if isinstance(data, dict) else []
            previous = [item for item in entries if isinstance(item, dict)]
        previous.append(
            {
                **result,
                "action": action,
                "model_fingerprint": {
                    "model_k_sha256": _file_sha256(project_path / "model.k"),
                    "model_json_sha256": _file_sha256(project_path / "model.json"),
                },
            }
        )
        write_json(
            path,
            {"schema_version": "0.1.0", "verifications": previous[-100:]},
        )


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
