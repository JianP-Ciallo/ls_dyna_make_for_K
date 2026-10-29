"""Immutable mesh and building artifacts used by Phase 18C backends."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

from .contracts import JSONDict


@dataclass(frozen=True, slots=True)
class Node:
    node_id: int
    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        if self.node_id <= 0:
            raise ValueError("node_id must be positive")
        if any(not math.isfinite(float(value)) for value in (self.x, self.y, self.z)):
            raise ValueError("node coordinates must be finite")

    @property
    def coordinates(self) -> tuple[float, float, float]:
        return (float(self.x), float(self.y), float(self.z))


@dataclass(frozen=True, slots=True)
class SolidElement:
    element_id: int
    node_ids: tuple[int, int, int, int, int, int, int, int]
    part_role: str


@dataclass(frozen=True, slots=True)
class ShellElement:
    element_id: int
    node_ids: tuple[int, int, int, int]
    part_role: str


@dataclass(frozen=True, slots=True)
class BeamElement:
    element_id: int
    node_ids: tuple[int, int]
    part_role: str


@dataclass(frozen=True, slots=True)
class PartBinding:
    part_role: str
    material_role: str
    section_role: str


@dataclass(frozen=True, slots=True)
class ConnectionArtifact:
    connection_id: str
    connection_type: str
    source_element_ids: tuple[int, ...] = ()
    target_element_ids: tuple[int, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class MeshFragment:
    nodes: tuple[Node, ...]
    solids: tuple[SolidElement, ...] = ()
    shells: tuple[ShellElement, ...] = ()
    beams: tuple[BeamElement, ...] = ()
    part_bindings: tuple[PartBinding, ...] = ()

    def __post_init__(self) -> None:
        if not self.nodes:
            raise ValueError("mesh fragment must contain nodes")
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("mesh fragment contains duplicate node ids")
        valid_nodes = set(node_ids)
        elements: tuple[SolidElement | ShellElement | BeamElement, ...] = (
            *self.solids,
            *self.shells,
            *self.beams,
        )
        element_ids = [element.element_id for element in elements]
        if len(element_ids) != len(set(element_ids)):
            raise ValueError("mesh fragment contains duplicate element ids")
        for element in elements:
            if element.element_id <= 0:
                raise ValueError("element_id must be positive")
            if not element.part_role.strip():
                raise ValueError("element part_role must be non-empty")
            if len(element.node_ids) != len(set(element.node_ids)):
                raise ValueError(f"element {element.element_id} contains duplicate node references")
            dangling = set(element.node_ids) - valid_nodes
            if dangling:
                raise ValueError(
                    f"element {element.element_id} has dangling node references: {sorted(dangling)}"
                )
        binding_roles = [binding.part_role for binding in self.part_bindings]
        if len(binding_roles) != len(set(binding_roles)):
            raise ValueError("mesh fragment contains duplicate part bindings")

    @property
    def bounds_m(self) -> tuple[float, float, float, float, float, float]:
        return (
            min(node.x for node in self.nodes),
            min(node.y for node in self.nodes),
            min(node.z for node in self.nodes),
            max(node.x for node in self.nodes),
            max(node.y for node in self.nodes),
            max(node.z for node in self.nodes),
        )

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.to_manifest())

    def to_manifest(self) -> JSONDict:
        return {
            "nodes": [
                {"id": row.node_id, "xyz_m": [row.x, row.y, row.z]} for row in self.nodes
            ],
            "solids": [
                {"id": row.element_id, "node_ids": list(row.node_ids), "part_role": row.part_role}
                for row in self.solids
            ],
            "shells": [
                {"id": row.element_id, "node_ids": list(row.node_ids), "part_role": row.part_role}
                for row in self.shells
            ],
            "beams": [
                {"id": row.element_id, "node_ids": list(row.node_ids), "part_role": row.part_role}
                for row in self.beams
            ],
            "part_bindings": [
                {
                    "part_role": row.part_role,
                    "material_role": row.material_role,
                    "section_role": row.section_role,
                }
                for row in self.part_bindings
            ],
        }


@dataclass(frozen=True, slots=True)
class BuildingArtifact:
    asset_id: str
    system_id: str
    mesh: MeshFragment
    connections: tuple[ConnectionArtifact, ...] = ()
    normalized_input: JSONDict = field(default_factory=dict)
    topology_manifest: JSONDict = field(default_factory=dict)
    surface_catalog: JSONDict = field(default_factory=dict)
    dependency_manifest: tuple[JSONDict, ...] = ()
    validation_findings: tuple[str, ...] = ()
    requires_project_review: bool = True

    def connections_by_type(self, connection_type: str) -> tuple[ConnectionArtifact, ...]:
        return tuple(
            connection for connection in self.connections if connection.connection_type == connection_type
        )

    def solid_contains_point(self, point_m: tuple[float, float, float]) -> bool:
        nodes = {node.node_id: node for node in self.mesh.nodes}
        for solid in self.mesh.solids:
            coordinates = [nodes[node_id].coordinates for node_id in solid.node_ids]
            if all(
                min(point[index] for point in coordinates)
                <= point_m[index]
                <= max(point[index] for point in coordinates)
                for index in range(3)
            ):
                return True
        return False

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.to_manifest(include_fingerprint=False))

    def to_manifest(self, *, include_fingerprint: bool = True) -> JSONDict:
        result: JSONDict = {
            "schema_version": "1.0.0",
            "asset_id": self.asset_id,
            "system_id": self.system_id,
            "normalized_input": self.normalized_input,
            "mesh": self.mesh.to_manifest(),
            "counts": {
                "nodes": len(self.mesh.nodes),
                "solids": len(self.mesh.solids),
                "shells": len(self.mesh.shells),
                "beams": len(self.mesh.beams),
                "connections": len(self.connections),
            },
            "connections": [
                {
                    "id": row.connection_id,
                    "type": row.connection_type,
                    "source_element_ids": list(row.source_element_ids),
                    "target_element_ids": list(row.target_element_ids),
                    "metadata": dict(row.metadata),
                }
                for row in self.connections
            ],
            "topology": self.topology_manifest,
            "surface_catalog": self.surface_catalog,
            "dependencies": list(self.dependency_manifest),
            "validation_findings": list(self.validation_findings),
            "requires_project_review": self.requires_project_review,
        }
        if include_fingerprint:
            result["fingerprint"] = self.fingerprint
        return result


def _fingerprint(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
