"""Solver-complete Phase 18 refined-building blast generation."""

from .ale_domain import AleDomainEstimate, iter_ale_elements, iter_ale_nodes
from .air_topology import (
    AirCellPlan,
    AirRegionModel,
    AirTopologyEvidence,
    audit_air_topology,
    classify_ale_cell,
)
from .charge import (
    ChargeModel,
    TNT_DENSITY_KG_PER_M3,
    tnt_radius_m,
    tnt_side_length_m,
)
from .contracts import (
    AuditFinding,
    PhysicalInterfaceRecord,
    PhysicalMemberRecord,
    SHORT_SOLVE_DEFAULT_TERMINATION_TIME_S,
    SolverBlastConfig,
    normalize_solver_blast_config,
)
from .fsi import FsiInterface, FsiSegment, extract_fsi_segments
from .ground import GroundModel, build_ground
from .keyword import SolverBlastDeckEvidence, write_solver_blast_deck
from .physical_audit import audit_physical_connections, audit_physical_members
from .physical_building import (
    PhysicalBuildingModel,
    SUPPORTED_RESOURCE_IDS,
    audit_physical_building,
    build_physical_building,
)
from .results import SolverBlastRunReport, evaluate_solver_blast_run
from .scene import SolverBlastScene, build_solver_blast_scene
from .service import SolverBlastCompilation, compile_solver_blast_deck
from .surface_topology import (
    ClassifiedSurface,
    SurfaceClass,
    SurfaceTopology,
    classify_surface_topology,
)
from .validation import ValidationFinding, ValidationReport, inspect_solver_blast_deck

__all__ = [
    "AleDomainEstimate",
    "AirCellPlan",
    "AirRegionModel",
    "AirTopologyEvidence",
    "AuditFinding",
    "ChargeModel",
    "ClassifiedSurface",
    "FsiInterface",
    "FsiSegment",
    "GroundModel",
    "PhysicalInterfaceRecord",
    "PhysicalMemberRecord",
    "PhysicalBuildingModel",
    "SHORT_SOLVE_DEFAULT_TERMINATION_TIME_S",
    "SUPPORTED_RESOURCE_IDS",
    "SolverBlastScene",
    "SolverBlastConfig",
    "SolverBlastCompilation",
    "SolverBlastDeckEvidence",
    "SolverBlastRunReport",
    "SurfaceClass",
    "SurfaceTopology",
    "TNT_DENSITY_KG_PER_M3",
    "ValidationFinding",
    "ValidationReport",
    "audit_air_topology",
    "audit_physical_building",
    "audit_physical_connections",
    "audit_physical_members",
    "build_ground",
    "build_physical_building",
    "build_solver_blast_scene",
    "compile_solver_blast_deck",
    "classify_ale_cell",
    "classify_surface_topology",
    "extract_fsi_segments",
    "evaluate_solver_blast_run",
    "inspect_solver_blast_deck",
    "iter_ale_elements",
    "iter_ale_nodes",
    "normalize_solver_blast_config",
    "tnt_radius_m",
    "tnt_side_length_m",
    "write_solver_blast_deck",
]
