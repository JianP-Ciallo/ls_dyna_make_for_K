"""Atomic, one-directory publication for assessment artifacts."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from .errors import ContractError
from .source_evidence import SourceEvidence, revalidate_source


class AtomicAssessmentOutput:
    def __init__(self, output_dir: Path, evidence: SourceEvidence):
        requested = output_dir.absolute()
        if requested.exists():
            raise ContractError(f"output directory already exists: {requested}")
        parent = requested.parent.resolve(strict=True)
        resolved = parent / requested.name
        if resolved != evidence.output_dir or parent != evidence.output_parent:
            raise ContractError("output directory does not match inspected source boundary")
        self.output_dir = resolved
        self._parent = parent
        self._parent_identity = parent.resolve(strict=True)
        self._evidence = evidence
        self._staging: Path | None = None
        self._committed = False

    def __enter__(self) -> "AtomicAssessmentOutput":
        if self._staging is not None:
            raise RuntimeError("atomic output context cannot be entered twice")
        staging = tempfile.mkdtemp(prefix=f".{self.output_dir.name}.staging-", dir=self._parent)
        self._staging = Path(staging).resolve(strict=True)
        if self._staging.parent != self._parent_identity:
            self._cleanup()
            raise ContractError("staging directory escaped the approved output parent")
        return self

    def _artifact_path(self, name: str) -> Path:
        if self._staging is None:
            raise RuntimeError("atomic output context has not been entered")
        if not isinstance(name, str) or not name or "\\" in name:
            raise ContractError("artifact name must be a non-empty POSIX relative path")
        relative = PurePosixPath(name)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise ContractError("artifact name traversal or absolute paths are not allowed")
        target = self._staging.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.resolve(strict=False).is_relative_to(self._staging):
            raise ContractError("artifact name escaped the staging directory")
        return target

    def write_bytes(self, name: str, data: bytes) -> Path:
        if not isinstance(data, bytes):
            raise TypeError("artifact data must be bytes")
        target = self._artifact_path(name)
        with target.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return target

    def write_text(self, name: str, text: str, encoding: str = "utf-8") -> Path:
        if not isinstance(text, str):
            raise TypeError("artifact text must be a string")
        return self.write_bytes(name, text.encode(encoding))

    def commit(self) -> Path:
        if self._staging is None:
            raise RuntimeError("atomic output context has not been entered")
        if self._committed:
            raise RuntimeError("atomic output has already been committed")
        if self.output_dir.exists():
            raise ContractError(f"output directory already exists: {self.output_dir}")
        if self._parent.resolve(strict=True) != self._parent_identity:
            raise ContractError("output parent changed before publication")
        try:
            revalidate_source(self._evidence)
            os.rename(self._staging, self.output_dir)
        except Exception:
            self._cleanup()
            raise
        self._committed = True
        self._staging = None
        return self.output_dir

    def _cleanup(self) -> None:
        staging = self._staging
        self._staging = None
        if staging is None or not staging.exists():
            return
        resolved = staging.resolve(strict=True)
        if resolved.parent != self._parent_identity or not resolved.name.startswith(
            f".{self.output_dir.name}.staging-"
        ):
            raise RuntimeError("refusing to remove an unverified staging directory")
        shutil.rmtree(resolved)

    def __exit__(self, exc_type, exc, traceback) -> bool:  # type: ignore[no-untyped-def]
        if not self._committed:
            self._cleanup()
        return False
