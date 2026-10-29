"""Data-only Phase 18E preset descriptors; presets never bypass normalization."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RefinedBlastPresetDescriptor:
    preset_id: str
    version: str
    building_systems: tuple[str, ...]
    provider_ids: tuple[str, ...]
    status: str = "research_candidate"


_PRESETS = (
    RefinedBlastPresetDescriptor("rc-research", "1.0.0", ("rc_frame", "rc_box"), ("explicit_ale_fsi", "lbe_segment", "imported_pressure_history", "solver_complete_ale_fsi")),
    RefinedBlastPresetDescriptor("steel-research", "1.0.0", ("steel_frame",), ("explicit_ale_fsi", "lbe_segment", "imported_pressure_history", "solver_complete_ale_fsi")),
    RefinedBlastPresetDescriptor("masonry-research", "1.0.0", ("masonry",), ("lbe_segment", "imported_pressure_history")),
)


def list_refined_blast_presets() -> tuple[RefinedBlastPresetDescriptor, ...]:
    return _PRESETS


def get_refined_blast_preset(preset_id: str, version: str) -> RefinedBlastPresetDescriptor:
    matches = tuple(row for row in _PRESETS if row.preset_id == preset_id and row.version == version)
    if len(matches) != 1:
        raise ValueError(f"unsupported refined blast preset: {preset_id!r}@{version}")
    return matches[0]


__all__ = ["RefinedBlastPresetDescriptor", "get_refined_blast_preset", "list_refined_blast_presets"]
