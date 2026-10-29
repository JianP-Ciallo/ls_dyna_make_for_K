"""Read-only discovery and sealing of solver-result evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .contracts import AssessmentRequest
from .errors import AssessmentError, ContractError


_D3PLOT_RE = re.compile(r"^d3plot(?P<index>[0-9]+)?$")
_REQUIRED_FILES = {
    "model.k": "solver_input",
    "model.json": "model_metadata",
    "run.json": "run_metadata",
    "d3hsp": "solver_log",
}
_OPTIONAL_FILES = ("glstat", "matsum", "dbfsi")


class SourceChangedError(AssessmentError):
    """Raised when sealed source evidence changes before publication."""


@dataclass(frozen=True)
class EvidenceFile:
    path: Path
    relative_path: str
    size_bytes: int
    sha256: str
    role: str
    root_role: str = "result_dir"


@dataclass(frozen=True)
class SourceEvidence:
    result_dir: Path
    output_dir: Path
    output_parent: Path
    manifest_path: Path
    files: tuple[EvidenceFile, ...]


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _has_reparse_component(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if not current.exists():
            break
        if current.is_symlink():
            return True
        is_junction = getattr(current, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
    return False


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_nonempty_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise ContractError(f"required evidence {label} is missing")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ContractError(f"required evidence {label} is unreadable: {exc}") from exc
    if size <= 0:
        raise ContractError(f"required evidence {label} is empty")


def continuous_d3plot_series(result_dir: Path) -> tuple[Path, ...]:
    root = result_dir.resolve(strict=True)
    base = root / "d3plot"
    if not base.is_file():
        raise ContractError("d3plot base file is missing")

    indexed: dict[int, Path] = {}
    for child in root.iterdir():
        match = _D3PLOT_RE.fullmatch(child.name)
        if match is None or match.group("index") is None:
            continue
        index = int(match.group("index"))
        if index in indexed:
            raise ContractError(f"duplicate d3plot sequence index {index}")
        indexed[index] = child

    if indexed:
        expected = set(range(1, max(indexed) + 1))
        missing = sorted(expected - set(indexed))
        if missing:
            raise ContractError(f"d3plot sequence has a numbering gap at {missing[0]}")
    series = (base, *(indexed[index] for index in sorted(indexed)))
    for path in series:
        _require_nonempty_file(path, path.name)
    return tuple(series)


def _manifest_path(request: AssessmentRequest, result_dir: Path) -> Path:
    declared = request.semantic_manifest.path
    if declared.is_absolute():
        return declared.resolve(strict=True)
    if ".." in declared.parts:
        raise ContractError("semantic manifest path traversal is not allowed")
    return (result_dir / declared).resolve(strict=True)


def _validate_output_boundary(request: AssessmentRequest, result_dir: Path) -> tuple[Path, Path]:
    output = request.output_dir.absolute()
    if output.exists():
        raise ContractError(f"output directory already exists: {output}")
    if _has_reparse_component(output.parent):
        raise ContractError("output parent contains a symlink or reparse point")
    parent = output.parent.resolve(strict=True)
    final = parent / output.name
    if _is_relative_to(final, result_dir) or _is_relative_to(result_dir, final):
        raise ContractError("output and result directories overlap")
    return final, parent


def _record(path: Path, relative_path: str, role: str, root_role: str = "result_dir") -> EvidenceFile:
    _require_nonempty_file(path, relative_path)
    stat = path.stat()
    return EvidenceFile(
        path=path,
        relative_path=relative_path,
        size_bytes=stat.st_size,
        sha256=_hash_file(path),
        role=role,
        root_role=root_role,
    )


def inspect_source(request: AssessmentRequest) -> SourceEvidence:
    if not isinstance(request, AssessmentRequest):
        raise ContractError("request must be an AssessmentRequest")
    result_dir = request.result_dir.resolve(strict=True)
    if not result_dir.is_dir():
        raise ContractError("result_dir must be a directory")
    if _has_reparse_component(result_dir):
        raise ContractError("result_dir contains a symlink or reparse point")
    output_dir, output_parent = _validate_output_boundary(request, result_dir)
    manifest_path = _manifest_path(request, result_dir)

    files: list[EvidenceFile] = []
    for name, role in _REQUIRED_FILES.items():
        path = result_dir / name
        files.append(_record(path, name, role))
    try:
        run_value = json.loads((result_dir / "run.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"run.json is unreadable or invalid JSON: {exc}") from exc
    if not isinstance(run_value, dict):
        raise ContractError("run.json root must be an object")

    for path in continuous_d3plot_series(result_dir):
        files.append(_record(path, path.name, "state_database"))
    for name in _OPTIONAL_FILES:
        path = result_dir / name
        if path.exists():
            files.append(_record(path, name, "solver_quality_optional"))

    actual_manifest_hash = _hash_file(manifest_path)
    if actual_manifest_hash != request.semantic_manifest.sha256:
        raise ContractError(
            "semantic manifest hash mismatch: "
            f"expected {request.semantic_manifest.sha256}, got {actual_manifest_hash}"
        )
    if _is_relative_to(manifest_path, result_dir):
        manifest_relative = manifest_path.relative_to(result_dir).as_posix()
        manifest_root = "result_dir"
    else:
        manifest_relative = manifest_path.name
        manifest_root = "semantic_manifest_parent"
    files.append(_record(manifest_path, manifest_relative, "semantic_manifest", manifest_root))
    files.sort(key=lambda item: (item.root_role, item.relative_path, item.role))
    return SourceEvidence(
        result_dir=result_dir,
        output_dir=output_dir,
        output_parent=output_parent,
        manifest_path=manifest_path,
        files=tuple(files),
    )


def revalidate_source(evidence: SourceEvidence) -> None:
    for item in evidence.files:
        try:
            stat = item.path.stat()
            digest = _hash_file(item.path)
        except OSError as exc:
            raise SourceChangedError(f"source evidence changed: {item.relative_path}: {exc}") from exc
        if stat.st_size != item.size_bytes or digest != item.sha256:
            raise SourceChangedError(f"source evidence changed: {item.relative_path}")
