from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LEGACY_PROJECTS_DIR = ROOT / "projects"
WORKSPACE_DIR = ROOT / "workspace"
PROJECTS_DIR = WORKSPACE_DIR / "projects"
ARCHIVE_PROJECTS_DIR = WORKSPACE_DIR / "archived_projects"
MATERIALS_DIR = ROOT / "resources" / "materials"
MODEL_LIBRARY_DIR = ROOT / "resources" / "model_library"
STRUCTURAL_RESOURCES_DIR = MODEL_LIBRARY_DIR / "structural" / "phase18" / "two_storey_rc_frame_blast_reference"
PHASE18_REVIEW_MANIFEST = ROOT / "resources" / "reviews" / "phase18" / "two_storey_rc_frame_blast_reference_syntax_unit_review.json"
MODEL_RESOURCE_EXPORTS_DIR = WORKSPACE_DIR / "model_resource_exports"
DEFAULT_LSPP_EXE = Path("lsprepost4.12.exe")
DEFAULT_UNIT_SYSTEM = "SI_m_s_kg_N_Pa"
LOCAL_WEB_CONFIG_PATH = ROOT / "var" / "generated_configs" / "web_app.local.json"

JSONDict = dict[str, Any]


def load_local_web_config() -> JSONDict:
    if not LOCAL_WEB_CONFIG_PATH.is_file():
        return {}
    try:
        data = json.loads(LOCAL_WEB_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def configured_lspp_exe() -> tuple[Path, str, bool]:
    env_value = os.environ.get("LSPP_EXE")
    if env_value:
        return Path(env_value), "env", True

    local_value = load_local_web_config().get("lspp_exe")
    if isinstance(local_value, str) and local_value.strip():
        return Path(local_value), "local_config", True

    return DEFAULT_LSPP_EXE, "default", False


def lspp_exe() -> Path:
    path, _source, _configured = configured_lspp_exe()
    return path
