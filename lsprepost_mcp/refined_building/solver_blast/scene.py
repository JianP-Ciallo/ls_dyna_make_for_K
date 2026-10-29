"""Assembly of a physical building, soil, MM-ALE air, and movable TNT."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from . import ale_domain
from .air_topology import AirTopologyEvidence, audit_air_domain
from .ale_domain import AleDomainEstimate
from .charge import ChargeModel, build_charge, collect_occupied_volumes
from .contracts import SolverBlastConfig
from .ground import GroundModel, build_ground
from .physical_building import PhysicalBuildingModel


@dataclass(frozen=True, slots=True)
class SolverBlastScene:
    building: PhysicalBuildingModel
    ground: GroundModel
    air: AleDomainEstimate
    charge: ChargeModel
    air_topology: AirTopologyEvidence
    config: SolverBlastConfig
    fingerprint: str


def build_solver_blast_scene(
    building: PhysicalBuildingModel,
    config: SolverBlastConfig,
) -> SolverBlastScene:
    if not isinstance(building, PhysicalBuildingModel):
        raise TypeError("building must be a PhysicalBuildingModel")
    if not isinstance(config, SolverBlastConfig):
        raise TypeError("config must be a SolverBlastConfig")
    ground = build_ground(building, config)
    charge = build_charge(config, collect_occupied_volumes(building, ground))
    air = ale_domain.estimate_ale_domain(building, ground, charge, config)
    air_topology = audit_air_domain(air, ground)
    if air_topology.external_path_to_soil_contact_count:
        raise ValueError("free active air intersects soil outside an excavation")
    if air_topology.buffer_contains_material_count:
        raise ValueError(
            "declared connected internal air was assigned to the coupling buffer"
        )
    identity = {
        "schema_version": "phase18.solver_blast.scene@3",
        "building_fingerprint": building.fingerprint,
        "ground_fingerprint": ground.fingerprint,
        "air_fingerprint": air.fingerprint,
        "air_topology_fingerprint": air_topology.fingerprint,
        "charge_fingerprint": charge.fingerprint,
        "termination_time_s": config.termination_time_s,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return SolverBlastScene(
        building=building,
        ground=ground,
        air=air,
        charge=charge,
        air_topology=air_topology,
        config=config,
        fingerprint=fingerprint,
    )
