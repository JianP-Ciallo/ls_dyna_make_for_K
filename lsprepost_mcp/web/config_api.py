from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lsprepost_mcp.config import JSONDict, LOCAL_WEB_CONFIG_PATH, configured_lspp_exe, load_local_web_config
from lsprepost_mcp.lspp.launcher import doctor_lsprepost_exe
from lsprepost_mcp.locks import ProjectLock
from lsprepost_mcp.web.http_utils import ApiError
from lsprepost_mcp.web.native_dialogs import (
    NativeDialogUnavailable,
    choose_directory as native_choose_directory,
    choose_file as native_choose_file,
)


@dataclass(frozen=True)
class ExeDoctor:
    exe: str
    exists: bool
    is_file: bool
    suffix_ok: bool
    name_ok: bool
    ok: bool

    def to_json(self) -> JSONDict:
        return {
            "exe": self.exe,
            "exists": self.exists,
            "is_file": self.is_file,
            "suffix_ok": self.suffix_ok,
            "name_ok": self.name_ok,
            "ok": self.ok,
        }


def web_config_status() -> JSONDict:
    path, source, configured = configured_lspp_exe()
    export_dir = configured_export_dir()
    lsrun_path = configured_lsrun_exe()
    lsdyna_path = configured_lsdyna_exe()
    lsrun_doctor = doctor_named_exe(lsrun_path, ("lsrun",), require_name=True) if lsrun_path else None
    lsdyna_doctor = doctor_named_exe(lsdyna_path, ("lsdyna", "ls-dyna", "mppdyna"), require_name=False) if lsdyna_path else None
    return {
        "configured": configured,
        "source": source,
        "lspp_exe": str(path),
        "config_path": str(LOCAL_WEB_CONFIG_PATH),
        "doctor": doctor_lsprepost_exe(path).to_json(),
        "export_dir_configured": export_dir is not None,
        "export_dir": str(export_dir) if export_dir is not None else "",
        "export_dir_exists": export_dir.is_dir() if export_dir is not None else False,
        "lsrun_configured": bool(lsrun_doctor and lsrun_doctor.ok),
        "lsrun_exe": str(lsrun_path) if lsrun_path else "",
        "lsrun_doctor": lsrun_doctor.to_json() if lsrun_doctor else {},
        "lsdyna_configured": bool(lsdyna_doctor and lsdyna_doctor.ok),
        "lsdyna_exe": str(lsdyna_path) if lsdyna_path else "",
        "lsdyna_doctor": lsdyna_doctor.to_json() if lsdyna_doctor else {},
        "solve_command_template": '"$SOLVER" i="$INPUT" ncpu=$NCPU memory=$MEMORY',
        "solve_ncpu": int(load_local_web_config().get("solve_ncpu") or 4),
        "solve_memory": str(load_local_web_config().get("solve_memory") or "20m"),
        "solve_timeout_s": int(load_local_web_config().get("solve_timeout_s") or 600),
    }


def check_lsprepost_payload(payload: JSONDict) -> JSONDict:
    path = payload_lsprepost_path(payload)
    return {
        "lspp_exe": str(path),
        "doctor": doctor_lsprepost_exe(path).to_json(),
    }


def save_lsprepost_payload(payload: JSONDict) -> JSONDict:
    path = payload_lsprepost_path(payload)
    doctor = doctor_lsprepost_exe(path)
    if not doctor.ok:
        raise ApiError(400, "invalid_lsprepost_path", "LS-PrePost path must be an existing lsprepost*.exe file")

    write_web_config_patch({"lspp_exe": str(path)})
    os.environ["LSPP_EXE"] = str(path)
    status = web_config_status()
    status["source"] = "local_config"
    return status


def select_lsprepost_payload(_: JSONDict) -> JSONDict:
    selected = selected_native_path(
        choose_lsprepost_exe,
        "LS-PrePost selection was cancelled",
    )
    return save_lsprepost_payload({"lspp_exe": str(selected)})


def save_export_dir_payload(payload: JSONDict) -> JSONDict:
    path = payload_export_dir(payload)
    write_web_config_patch({"export_dir": str(path)})
    return web_config_status()


def check_lsrun_payload(payload: JSONDict) -> JSONDict:
    path = payload_lsrun_path(payload)
    return {"lsrun_exe": str(path), "doctor": doctor_named_exe(path, ("lsrun",), require_name=True).to_json()}


def save_lsrun_payload(payload: JSONDict) -> JSONDict:
    path = payload_lsrun_path(payload)
    doctor = doctor_named_exe(path, ("lsrun",), require_name=True)
    if not doctor.ok:
        raise ApiError(400, "invalid_lsrun_path", "LS-Run path must be an existing lsrun*.exe file")
    write_web_config_patch({"lsrun_exe": str(path)})
    return web_config_status()


def select_lsrun_payload(_: JSONDict) -> JSONDict:
    selected = selected_native_path(
        choose_lsrun_exe,
        "LS-Run selection was cancelled",
    )
    return save_lsrun_payload({"lsrun_exe": str(selected)})


def check_lsdyna_payload(payload: JSONDict) -> JSONDict:
    path = payload_lsdyna_path(payload)
    return {"lsdyna_exe": str(path), "doctor": doctor_named_exe(path, ("lsdyna", "ls-dyna", "mppdyna"), require_name=False).to_json()}


def save_lsdyna_payload(payload: JSONDict) -> JSONDict:
    path = payload_lsdyna_path(payload)
    doctor = doctor_named_exe(path, ("lsdyna", "ls-dyna", "mppdyna"), require_name=False)
    if not doctor.ok:
        raise ApiError(400, "invalid_lsdyna_path", "LS-DYNA solver path must be an existing .exe file")
    write_web_config_patch({"lsdyna_exe": str(path)})
    return web_config_status()


def select_lsdyna_payload(_: JSONDict) -> JSONDict:
    selected = selected_native_path(
        choose_lsdyna_exe,
        "LS-DYNA solver selection was cancelled",
    )
    return save_lsdyna_payload({"lsdyna_exe": str(selected)})


def select_export_dir_payload(_: JSONDict) -> JSONDict:
    selected = selected_native_path(
        choose_export_dir,
        "export directory selection was cancelled",
    )
    return save_export_dir_payload({"export_dir": str(selected)})


def selected_native_path(chooser, cancelled_message: str) -> Path:
    try:
        selected = chooser()
    except NativeDialogUnavailable as exc:
        raise ApiError(503, "native_dialog_unavailable", str(exc)) from exc
    if selected is None:
        raise ApiError(400, "selection_cancelled", cancelled_message)
    return selected


def configured_export_dir() -> Optional[Path]:
    raw = load_local_web_config().get("export_dir")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(raw.strip())


def configured_lsrun_exe() -> Optional[Path]:
    raw = load_local_web_config().get("lsrun_exe")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(raw.strip())


def configured_lsdyna_exe() -> Optional[Path]:
    raw = load_local_web_config().get("lsdyna_exe")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(raw.strip())


def doctor_named_exe(path: Path, name_prefixes: tuple[str, ...], require_name: bool) -> ExeDoctor:
    exists = path.exists()
    is_file = path.is_file() if exists else False
    suffix_ok = path.suffix.lower() == ".exe"
    lowered = path.name.lower()
    name_ok = any(lowered.startswith(prefix) for prefix in name_prefixes)
    if not require_name:
        name_ok = True
    return ExeDoctor(str(path), exists, is_file, suffix_ok, name_ok, exists and is_file and suffix_ok and name_ok)


def write_web_config_patch(updates: JSONDict) -> None:
    with ProjectLock("web_app_config", namespace="web_config"):
        LOCAL_WEB_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = load_local_web_config()
        data.update(updates)
        data["saved_at_utc"] = datetime.now(timezone.utc).isoformat()
        temp_path = LOCAL_WEB_CONFIG_PATH.with_suffix(".tmp")
        temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(LOCAL_WEB_CONFIG_PATH)


def choose_lsprepost_exe() -> Optional[Path]:
    return native_choose_file(
        title="选择 LS-PrePost 可执行文件",
        filetypes=[
            ("LS-PrePost executable", "lsprepost*.exe"),
            ("Windows executable", "*.exe"),
        ],
    )


def choose_lsrun_exe() -> Optional[Path]:
    return choose_exe_file(
        title="选择 LS-Run 可执行文件",
        filetypes=[
            ("LS-Run executable", "lsrun*.exe"),
            ("Windows executable", "*.exe"),
        ],
    )


def choose_lsdyna_exe() -> Optional[Path]:
    return choose_exe_file(
        title="选择 LS-DYNA 求解器",
        filetypes=[
            ("LS-DYNA solver", "*.exe"),
            ("Windows executable", "*.exe"),
        ],
    )


def choose_exe_file(title: str, filetypes: list[tuple[str, str]]) -> Optional[Path]:
    return native_choose_file(title=title, filetypes=filetypes)


def choose_export_dir() -> Optional[Path]:
    return native_choose_directory("选择模型保存文件夹")


def payload_lsprepost_path(payload: JSONDict) -> Path:
    raw = payload.get("lspp_exe")
    if not isinstance(raw, str) or not raw.strip():
        raise ApiError(400, "invalid_lsprepost_path", "lspp_exe must be a non-empty string")
    return Path(raw.strip())


def payload_export_dir(payload: JSONDict) -> Path:
    raw = payload.get("export_dir")
    if not isinstance(raw, str) or not raw.strip():
        raise ApiError(400, "invalid_export_dir", "export_dir must be a non-empty string")
    path = Path(raw.strip())
    if path.exists() and not path.is_dir():
        raise ApiError(400, "invalid_export_dir", "export_dir must be a directory")
    if not path.exists():
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ApiError(400, "invalid_export_dir", "export_dir could not be created") from exc
    return path


def payload_lsrun_path(payload: JSONDict) -> Path:
    raw = payload.get("lsrun_exe")
    if not isinstance(raw, str) or not raw.strip():
        raise ApiError(400, "invalid_lsrun_path", "lsrun_exe must be a non-empty string")
    return Path(raw.strip())


def payload_lsdyna_path(payload: JSONDict) -> Path:
    raw = payload.get("lsdyna_exe")
    if not isinstance(raw, str) or not raw.strip():
        raise ApiError(400, "invalid_lsdyna_path", "lsdyna_exe must be a non-empty string")
    return Path(raw.strip())
