from __future__ import annotations

from .config import JSONDict


ACTION_READINESS_KEY = {
    "open_in_lsprepost": "ok_for_gui_preview",
    "export_preview_image": "ok_for_gui_preview",
    "validate_lsprepost_import": "ok_for_gui_preview",
    "run_cfile": "ok_for_solver_draft",
    "batch_modify": "ok_for_solver_draft",
}
FORCE_ALLOWED_ACTIONS = {"open_in_lsprepost"}


def require_action_readiness(action: str, checks: JSONDict, force: bool = False) -> JSONDict:
    readiness = checks.get("readiness", {}) if isinstance(checks, dict) else {}
    key = ACTION_READINESS_KEY.get(action)
    if not key:
        raise ValueError(f"unknown readiness action: {action}")
    if force and action in FORCE_ALLOWED_ACTIONS:
        return readiness
    if force and action not in FORCE_ALLOWED_ACTIONS:
        raise ValueError(f"force is not allowed for automated action: {action}")
    if not bool(readiness.get(key)):
        if action == "open_in_lsprepost":
            raise ValueError("project is not ready for LS-PrePost GUI preview; required readiness.ok_for_gui_preview=true")
        raise ValueError(f"project is not ready for action {action}; required readiness.{key}=true")
    return readiness
