from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

from lsprepost_mcp.config import JSONDict


PREVIEW_CACHE_SCHEMA = "preview_mesh_cache_v1"


def _file_sha256(path: Path) -> str:
    if not path.is_file():
        return "missing"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PreviewMeshCache:
    def __init__(self, *, max_entries: int = 4, max_serialized_bytes: int = 16 * 1024 * 1024):
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        if max_serialized_bytes < 1:
            raise ValueError("max_serialized_bytes must be positive")
        self.max_entries = max_entries
        self.max_serialized_bytes = max_serialized_bytes
        self._entries: OrderedDict[tuple[str, str, str, str], tuple[JSONDict, int]] = OrderedDict()
        self._serialized_bytes = 0
        self._lock = threading.RLock()

    @property
    def entry_count(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def serialized_bytes(self) -> int:
        with self._lock:
            return self._serialized_bytes

    def _key(self, project_path: Path) -> tuple[str, str, str, str]:
        resolved = project_path.resolve()
        return (
            PREVIEW_CACHE_SCHEMA,
            str(resolved),
            _file_sha256(resolved / "model.k"),
            _file_sha256(resolved / "model.json"),
        )

    def get_or_build(
        self,
        project_path: Path,
        builder: Callable[[Path], JSONDict],
    ) -> JSONDict:
        key = self._key(project_path)
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                return cached[0]

            payload = builder(project_path)
            payload_size = len(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
            if payload_size > self.max_serialized_bytes:
                return payload

            project_identity = key[1]
            for stale_key in [item for item in self._entries if item[1] == project_identity]:
                _, stale_size = self._entries.pop(stale_key)
                self._serialized_bytes -= stale_size

            self._entries[key] = (payload, payload_size)
            self._serialized_bytes += payload_size
            while (
                len(self._entries) > self.max_entries
                or self._serialized_bytes > self.max_serialized_bytes
            ):
                _, (_, removed_size) = self._entries.popitem(last=False)
                self._serialized_bytes -= removed_size
            return payload

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._serialized_bytes = 0


preview_mesh_cache = PreviewMeshCache()


def build_cached_preview_mesh(
    project_path: Path,
    builder: Callable[[Path], JSONDict],
) -> JSONDict:
    return preview_mesh_cache.get_or_build(project_path, builder)
