"""Connection artifact factories shared by structural backends."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .artifacts import ConnectionArtifact


def make_connection(
    connection_id: str,
    connection_type: str,
    *,
    source_element_ids: Iterable[int] = (),
    target_element_ids: Iterable[int] = (),
    metadata: Mapping[str, object] | None = None,
) -> ConnectionArtifact:
    if not connection_id.strip() or not connection_type.strip():
        raise ValueError("connection id and type must be non-empty")
    source = tuple(int(value) for value in source_element_ids)
    target = tuple(int(value) for value in target_element_ids)
    if any(value <= 0 for value in (*source, *target)):
        raise ValueError("connection element ids must be positive")
    metadata_items = tuple(
        sorted((str(key), str(value)) for key, value in (metadata or {}).items())
    )
    return ConnectionArtifact(
        connection_id.strip(),
        connection_type.strip(),
        source,
        target,
        metadata_items,
    )
