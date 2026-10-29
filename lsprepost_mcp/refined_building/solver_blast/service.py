"""Trusted composition service for one solver-complete Phase 18 blast deck."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ..asset_compiler import DetailedBuildingPackage
from .contracts import SolverBlastConfig, normalize_solver_blast_config
from .keyword import SolverBlastDeckEvidence, write_solver_blast_deck
from .physical_building import (
    PhysicalBuildingModel,
    audit_physical_building,
    build_physical_building,
)
from .scene import build_solver_blast_scene
from .validation import ValidationReport, inspect_solver_blast_deck


@dataclass(frozen=True, slots=True)
class SolverBlastCompilation:
    building: PhysicalBuildingModel
    evidence: SolverBlastDeckEvidence
    validation: ValidationReport


def compile_solver_blast_deck(
    package: DetailedBuildingPackage,
    config: SolverBlastConfig | Mapping[str, object],
    output_dir: Path,
) -> SolverBlastCompilation:
    """Compile and statically reparse one dependency-closed R12 candidate."""

    normalized = (
        config
        if isinstance(config, SolverBlastConfig)
        else normalize_solver_blast_config(config)
    )
    building = build_physical_building(package)
    findings = audit_physical_building(building)
    if findings:
        summary = "; ".join(
            f"{row.finding_id}: {row.message}" for row in findings
        )
        raise ValueError(f"physical building audit failed: {summary}")
    scene = build_solver_blast_scene(building, normalized)
    evidence = write_solver_blast_deck(scene, Path(output_dir))
    validation = inspect_solver_blast_deck(Path(output_dir))
    if not validation.ok:
        summary = "; ".join(
            f"{row.code}: {row.message}" for row in validation.findings
        )
        raise ValueError(f"solver blast deck validation failed: {summary}")
    return SolverBlastCompilation(
        building=building, evidence=evidence, validation=validation
    )


__all__ = ["SolverBlastCompilation", "compile_solver_blast_deck"]
