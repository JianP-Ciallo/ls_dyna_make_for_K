from __future__ import annotations

from pathlib import Path

SAFE_FILENAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
ALLOWED_ARTIFACT_IF_EXISTS = {"error", "overwrite", "versioned"}


def artifacts_dir(project_path: Path) -> Path:
    path = project_path / "artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_artifact_filename(name: str) -> str:
    if not name:
        raise ValueError("artifact filename must not be empty")
    candidate = name.strip()
    if candidate != name or candidate in {".", ".."}:
        raise ValueError("artifact filename is not allowed")
    if Path(candidate).is_absolute() or "/" in candidate or "\\" in candidate or ".." in Path(candidate).parts:
        raise ValueError("artifact filename must be a simple relative filename")
    if any(ch not in SAFE_FILENAME_CHARS for ch in candidate):
        raise ValueError("artifact filename contains unsupported characters")
    return candidate


def artifact_path(project_path: Path, filename: str, if_exists: str = "error") -> Path:
    if if_exists not in ALLOWED_ARTIFACT_IF_EXISTS:
        raise ValueError(f"if_exists must be one of {', '.join(sorted(ALLOWED_ARTIFACT_IF_EXISTS))}")
    base = artifacts_dir(project_path).resolve()
    safe_name = safe_artifact_filename(filename)
    target = (base / safe_name).resolve()
    if base != target.parent:
        raise ValueError("artifact path escaped project artifacts directory")
    if not target.exists() or if_exists == "overwrite":
        return target
    if if_exists == "error":
        raise FileExistsError(f"artifact already exists: {target}")
    if if_exists != "versioned":
        raise ValueError(f"unsupported artifact if_exists policy: {if_exists}")
    stem = target.stem
    suffix = target.suffix
    for index in range(2, 10_000):
        candidate = base / f"{stem}_v{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not allocate versioned artifact name for {safe_name}")
