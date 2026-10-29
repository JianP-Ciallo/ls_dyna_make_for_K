"""Visible diagnostic soil and excavation geometry for solver-blast scenes."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

from ..artifacts import MeshFragment, Node, SolidElement
from ..meshing import mesh_axis_aligned_block_excluding
from ..spatial import AxisAlignedBox
from .contracts import SolverBlastConfig
from .physical_building import PhysicalBuildingModel, SUBWAY_ID


_GROUND_NODE_ID_START = 20_000_001
_GROUND_ELEMENT_ID_START = 30_000_001
_MAX_GROUND_NODES = 2_000_000
_MAX_GROUND_ELEMENTS = 1_000_000


@dataclass(frozen=True, slots=True)
class GroundModel:
    part_role: str
    fragments: tuple[MeshFragment, ...]
    bounds_m: tuple[float, float, float, float, float, float]
    grade_elevation_m: float
    visible_surface_z_m: float
    target_cell_size_m: float
    excavation_bounds_m: tuple[
        tuple[float, float, float, float, float, float], ...
    ]
    positive_soil_structure_overlap_m3: float
    fingerprint: str


def build_ground(
    building: PhysicalBuildingModel,
    config: SolverBlastConfig,
) -> GroundModel:
    if not isinstance(building, PhysicalBuildingModel):
        raise TypeError("building must be a PhysicalBuildingModel")
    if not isinstance(config, SolverBlastConfig):
        raise TypeError("config must be a SolverBlastConfig")
    xmin, ymin, zmin, xmax, ymax, _ = building.bounds_m
    x_min_margin, x_max_margin, y_min_margin, y_max_margin, top_margin = (
        config.air_margins_m
    )
    grade = building.grade_elevation_m
    depth = max(1.0, 0.5 * top_margin)
    ground_box = AxisAlignedBox(
        xmin - x_min_margin,
        ymin - y_min_margin,
        min(zmin, grade) - depth,
        xmax + x_max_margin,
        ymax + y_max_margin,
        grade,
    )
    excavation_boxes: tuple[AxisAlignedBox, ...] = ()
    if building.resource_id == SUBWAY_ID:
        excavation_boxes = (
            AxisAlignedBox(
                xmin,
                ymin,
                zmin,
                xmax,
                ymax,
                grade,
            ),
        )
    else:
        for artifact in building.artifacts:
            if artifact.mesh.bounds_m[2] < grade - 1.0e-12:
                raise ValueError(
                    "above-grade building has structure below grade without an excavation"
                )

    target_size = config.ground_cell_size_m
    _validate_ground_budget(ground_box, target_size, excavation_boxes)
    fragment = _remap_ground_ids(
        mesh_axis_aligned_block_excluding(
            ground_box,
            target_size,
            "diagnostic_soil_ground",
            excavation_boxes,
        )
    )
    identity = {
        "schema_version": "phase18.solver_blast.ground@1",
        "resource_id": building.resource_id,
        "part_role": "diagnostic_soil_ground",
        "bounds_m": list(ground_box.as_tuple()),
        "grade_elevation_m": grade,
        "target_cell_size_m": target_size,
        "excavation_bounds_m": [list(row.as_tuple()) for row in excavation_boxes],
        "mesh_fingerprint": fragment.fingerprint,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return GroundModel(
        part_role="diagnostic_soil_ground",
        fragments=(fragment,),
        bounds_m=ground_box.as_tuple(),
        grade_elevation_m=grade,
        visible_surface_z_m=grade,
        target_cell_size_m=target_size,
        excavation_bounds_m=tuple(row.as_tuple() for row in excavation_boxes),
        positive_soil_structure_overlap_m3=0.0,
        fingerprint=fingerprint,
    )


def _validate_ground_budget(
    bounds: AxisAlignedBox,
    target_size_m: float,
    excavation_boxes: tuple[AxisAlignedBox, ...],
) -> None:
    axis_node_upper = tuple(
        math.ceil(span / target_size_m) + 1 + 2 * len(excavation_boxes)
        for span in (
            bounds.max_x - bounds.min_x,
            bounds.max_y - bounds.min_y,
            bounds.max_z - bounds.min_z,
        )
    )
    node_upper = math.prod(axis_node_upper)
    element_upper = math.prod(value - 1 for value in axis_node_upper)
    if node_upper > _MAX_GROUND_NODES:
        raise ValueError(
            f"ground node budget exceeded: estimated {node_upper}, "
            f"limit {_MAX_GROUND_NODES}"
        )
    if element_upper > _MAX_GROUND_ELEMENTS:
        raise ValueError(
            f"ground element budget exceeded: estimated {element_upper}, "
            f"limit {_MAX_GROUND_ELEMENTS}"
        )


def _remap_ground_ids(fragment: MeshFragment) -> MeshFragment:
    used_node_ids = {
        node_id for element in fragment.solids for node_id in element.node_ids
    }
    retained_nodes = tuple(
        node for node in fragment.nodes if node.node_id in used_node_ids
    )
    node_map = {
        node.node_id: _GROUND_NODE_ID_START + index
        for index, node in enumerate(retained_nodes)
    }
    return MeshFragment(
        nodes=tuple(
            Node(node_map[node.node_id], node.x, node.y, node.z)
            for node in retained_nodes
        ),
        solids=tuple(
            SolidElement(
                _GROUND_ELEMENT_ID_START + index,
                tuple(node_map[node_id] for node_id in element.node_ids),
                element.part_role,
            )
            for index, element in enumerate(fragment.solids)
        ),
        part_bindings=fragment.part_bindings,
    )
