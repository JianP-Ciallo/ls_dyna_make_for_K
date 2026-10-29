from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from lsprepost_mcp.config import JSONDict
from lsprepost_mcp.locks import ProjectLock


CORE_PROJECT_FILES = ("model.k", "model.json", "checks.json")


def export_project_copy(project_path: Path, export_dir: Path) -> JSONDict:
    project = project_path.resolve()
    if not project.is_dir():
        raise FileNotFoundError(f"project directory not found: {project}")
    export_dir.mkdir(parents=True, exist_ok=True)
    export_root = export_dir.resolve()
    if export_root == project or project in export_root.parents:
        raise ValueError("export directory must stay outside the project directory")
    destination = (export_root / project.name).resolve()
    if destination == project:
        raise ValueError("export destination must stay outside the project directory")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    temp = export_root / f".{project.name}.tmp_{timestamp}"
    backup = export_root / f".{project.name}.bak_{timestamp}"
    copied: list[str] = []
    with ProjectLock(project.name):
        try:
            temp.mkdir(parents=True)
            for name in CORE_PROJECT_FILES:
                source = project / name
                if not source.is_file():
                    raise FileNotFoundError(f"project file not found: {source}")
                shutil.copy2(source, temp / name)
                copied.append(name)

            manifest = {
                "schema_version": "0.1.0",
                "source_project_name": project.name,
                "files": copied,
                "saved_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            (temp / "export_manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            if destination.exists():
                shutil.move(str(destination), str(backup))
            try:
                shutil.move(str(temp), str(destination))
            except Exception:
                if destination.exists():
                    shutil.rmtree(destination)
                if backup.exists():
                    shutil.move(str(backup), str(destination))
                raise
            if backup.exists():
                shutil.rmtree(backup)
        finally:
            if temp.exists():
                shutil.rmtree(temp)
    return {
        "enabled": True,
        "export_dir": str(export_root),
        "project_export_dir": str(destination),
        "files": copied,
    }
