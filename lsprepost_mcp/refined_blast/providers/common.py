"""Immutable public types shared by refined-blast load providers."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, TypeAlias

from lsprepost_mcp.refined_building.artifacts import (
    BuildingArtifact,
    ShellElement,
    SolidElement,
)

from ..contracts import ScenarioKind


FrozenValue: TypeAlias = (
    None | bool | int | float | str | tuple["FrozenValue", ...] | Mapping[str, "FrozenValue"]
)
FrozenMapping: TypeAlias = Mapping[str, FrozenValue]
_SURFACE_FACE_KEYS = frozenset(
    {
        "face_id",
        "element_id",
        "node_ids",
        "part_role",
        "centroid_m",
        "normal",
        "area_m2",
    }
)
_SURFACE_GEOMETRY_TOLERANCE = 1.0e-9
_HEX_ORIENTED_FACES = (
    (0, 1, 2, 3),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (1, 2, 6, 5),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
)


def freeze_value(value: object, path: str = "value") -> FrozenValue:
    """Copy canonical JSON-like data into recursively immutable containers."""

    return _freeze_value(value, path, frozenset())


def _freeze_value(value: object, path: str, ancestors: frozenset[int]) -> FrozenValue:
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must be finite")
        return value
    if isinstance(value, Mapping):
        if id(value) in ancestors:
            raise ValueError(f"{path} must not contain cyclic containers")
        nested_ancestors = ancestors | {id(value)}
        result: dict[str, FrozenValue] = {}
        for key, nested in sorted(value.items()):
            if not isinstance(key, str) or not key:
                raise ValueError(f"{path} keys must be non-empty strings")
            result[key] = _freeze_value(nested, f"{path}.{key}", nested_ancestors)
        return MappingProxyType(result)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if id(value) in ancestors:
            raise ValueError(f"{path} must not contain cyclic containers")
        nested_ancestors = ancestors | {id(value)}
        return tuple(
            _freeze_value(nested, f"{path}[{index}]", nested_ancestors)
            for index, nested in enumerate(value)
        )
    raise ValueError(f"{path} must contain only canonical JSON values")


def thaw_value(value: FrozenValue | object) -> object:
    if isinstance(value, Mapping):
        return {key: thaw_value(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [thaw_value(nested) for nested in value]
    return value


def fingerprint_value(value: object) -> str:
    canonical = json.dumps(
        thaw_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TopologyRegion:
    region_id: str
    bounds_m: tuple[float, float, float, float, float, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "region_id", _safe_string(self.region_id, "region_id"))
        object.__setattr__(self, "bounds_m", _bounds_tuple(self.bounds_m, "region.bounds_m"))


@dataclass(frozen=True, slots=True)
class TopologyOpening:
    opening_id: str
    bounds_m: tuple[float, float, float, float, float, float]
    connects: tuple[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "opening_id", _safe_string(self.opening_id, "opening_id"))
        object.__setattr__(self, "bounds_m", _bounds_tuple(self.bounds_m, "opening.bounds_m"))
        if not _is_sequence(self.connects) or len(self.connects) != 2:
            raise ValueError("opening.connects must contain exactly two endpoint ids")
        connects = tuple(
            _safe_string(value, f"opening.connects[{index}]")
            for index, value in enumerate(self.connects)
        )
        if connects[0] == connects[1]:
            raise ValueError("opening.connects endpoints must be different")
        object.__setattr__(self, "connects", connects)


@dataclass(frozen=True, slots=True)
class ProviderTopology:
    """Minimal immutable public topology view required by load providers."""

    envelope_bounds_m: tuple[float, float, float, float, float, float]
    spaces: tuple[TopologyRegion, ...]
    openings: tuple[TopologyOpening, ...]
    fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "envelope_bounds_m",
            _bounds_tuple(self.envelope_bounds_m, "topology.envelope_bounds_m"),
        )
        object.__setattr__(self, "spaces", tuple(self.spaces))
        object.__setattr__(self, "openings", tuple(self.openings))
        object.__setattr__(self, "fingerprint", _safe_string(self.fingerprint, "topology.fingerprint"))
        space_ids = tuple(row.region_id for row in self.spaces)
        opening_ids = tuple(row.opening_id for row in self.openings)
        if len(space_ids) != len(set(space_ids)):
            raise ValueError("topology contains duplicate space ids")
        if len(opening_ids) != len(set(opening_ids)):
            raise ValueError("topology contains duplicate opening ids")
        allowed_endpoints = set(space_ids) | {"exterior"}
        for opening in self.openings:
            unknown = set(opening.connects) - allowed_endpoints
            if unknown:
                raise ValueError(
                    f"opening {opening.opening_id!r} references unknown endpoint {sorted(unknown)[0]!r}"
                )

    @classmethod
    def from_artifact(cls, artifact: BuildingArtifact) -> "ProviderTopology":
        topology = artifact.topology_manifest
        normalized = artifact.normalized_input
        envelope = _bounds_tuple(topology.get("envelope_bounds_m"), "topology.envelope_bounds_m")
        raw_spaces = topology.get("void_regions")
        if not _is_sequence(raw_spaces):
            raise ValueError("topology.void_regions must be a sequence")
        spaces = tuple(
            sorted(
                (
                    TopologyRegion(
                        _mapping_string(row, "id", f"topology.void_regions[{index}]"),
                        _bounds_tuple(
                            _as_mapping(row, f"topology.void_regions[{index}]").get("bounds_m"),
                            f"topology.void_regions[{index}].bounds_m",
                        ),
                    )
                    for index, row in enumerate(raw_spaces)
                ),
                key=lambda row: row.region_id,
            )
        )
        normalized_openings = normalized.get("openings")
        if not _is_sequence(normalized_openings):
            raise ValueError("artifact.normalized_input.openings must be a sequence")
        openings: list[TopologyOpening] = []
        for index, raw in enumerate(normalized_openings):
            row = _as_mapping(raw, f"artifact.normalized_input.openings[{index}]")
            connects_raw = row.get("connects")
            if not _is_sequence(connects_raw) or len(connects_raw) != 2:
                raise ValueError(f"artifact.normalized_input.openings[{index}].connects is invalid")
            connects = tuple(
                _safe_string(value, f"artifact.normalized_input.openings[{index}].connects")
                for value in connects_raw
            )
            openings.append(
                TopologyOpening(
                    _mapping_string(row, "id", f"artifact.normalized_input.openings[{index}]"),
                    _bounds_tuple(
                        row.get("bounds_m"),
                        f"artifact.normalized_input.openings[{index}].bounds_m",
                    ),
                    connects,  # type: ignore[arg-type]
                )
            )
        raw_fingerprint = topology.get("fingerprint")
        fingerprint = _safe_string(raw_fingerprint, "topology.fingerprint")
        return cls(envelope, spaces, tuple(sorted(openings, key=lambda row: row.opening_id)), fingerprint)


@dataclass(frozen=True, slots=True)
class ProviderContext:
    """Immutable provider context with explicit artifact, surfaces, and topology."""

    artifact: BuildingArtifact
    scenario_kind: ScenarioKind
    available_ids: frozenset[str]
    surface_catalog: FrozenMapping
    topology: ProviderTopology

    def __post_init__(self) -> None:
        if self.scenario_kind not in {"external", "internal", "semi_enclosed"}:
            raise ValueError(f"unsupported scenario_kind: {self.scenario_kind!r}")
        object.__setattr__(self, "available_ids", frozenset(self.available_ids))
        object.__setattr__(self, "surface_catalog", freeze_value(self.surface_catalog, "surface_catalog"))

    @classmethod
    def from_artifact(
        cls,
        artifact: BuildingArtifact,
        *,
        scenario_kind: ScenarioKind,
        available_ids: frozenset[str] | set[str] = frozenset(),
    ) -> "ProviderContext":
        surface_catalog = freeze_value(artifact.surface_catalog, "artifact.surface_catalog")
        assert isinstance(surface_catalog, Mapping)
        topology = ProviderTopology.from_artifact(artifact)
        available = set(available_ids) | {
            f"surface:{row['face_id']}"
            for category in (
                "exterior_surfaces",
                "interior_cavity_surfaces",
                "ground_contact_surfaces",
                "unclassified_boundary_surfaces",
            )
            for row in _surface_rows(surface_catalog, category)
        }
        available.update(
            f"building:element:{row.element_id}"
            for row in (
                *artifact.mesh.solids,
                *artifact.mesh.shells,
                *artifact.mesh.beams,
            )
        )
        available.update(f"building:node:{row.node_id}" for row in artifact.mesh.nodes)
        available.update(f"space:{row.region_id}" for row in topology.spaces)
        available.update(f"opening:{row.opening_id}" for row in topology.openings)
        available.update(
            {
                f"artifact:{artifact.fingerprint}",
                f"topology:{topology.fingerprint}",
            }
        )
        return cls(
            artifact=artifact,
            scenario_kind=scenario_kind,
            available_ids=frozenset(available),
            surface_catalog=surface_catalog,
            topology=topology,
        )


@dataclass(frozen=True, slots=True)
class ProviderEstimate:
    provider_id: str
    axis_point_counts: tuple[int, int, int]
    node_count: int
    element_count: int
    budget_limits: FrozenMapping
    budget_checked_before_allocation: bool = True
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "budget_limits", freeze_value(self.budget_limits, "budget_limits"))
        core = {
            "provider_id": self.provider_id,
            "axis_point_counts": self.axis_point_counts,
            "node_count": self.node_count,
            "element_count": self.element_count,
            "budget_limits": self.budget_limits,
            "budget_checked_before_allocation": self.budget_checked_before_allocation,
        }
        object.__setattr__(self, "fingerprint", fingerprint_value(core))

    def to_manifest(self) -> FrozenMapping:
        value = freeze_value(
            {
                "provider_id": self.provider_id,
                "axis_point_counts": self.axis_point_counts,
                "node_count": self.node_count,
                "element_count": self.element_count,
                "budget_limits": self.budget_limits,
                "budget_checked_before_allocation": self.budget_checked_before_allocation,
                "fingerprint": self.fingerprint,
            }
        )
        assert isinstance(value, Mapping)
        return value


@dataclass(frozen=True, slots=True)
class ProviderEvidence:
    evidence_id: str
    evidence_kind: str
    source_ids: tuple[str, ...]
    claims: FrozenMapping
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_ids", tuple(self.source_ids))
        object.__setattr__(self, "claims", freeze_value(self.claims, "evidence.claims"))
        object.__setattr__(
            self,
            "fingerprint",
            fingerprint_value(
                {
                    "evidence_id": self.evidence_id,
                    "evidence_kind": self.evidence_kind,
                    "source_ids": self.source_ids,
                    "claims": self.claims,
                }
            ),
        )


def classify_source_space(
    position_m: Sequence[float], context: ProviderContext
) -> str:
    """Classify a point as one real room or exterior; reject boundary/solid ambiguity."""

    if not _is_sequence(position_m) or len(position_m) != 3:
        raise ValueError("source position must contain exactly three finite numbers")
    position = tuple(_finite_coordinate(value, "source position") for value in position_m)
    matches = tuple(
        region.region_id
        for region in context.topology.spaces
        if _point_strictly_inside(position, region.bounds_m)
    )
    if len(matches) > 1:
        raise ValueError("source position is ambiguous across multiple topology spaces")
    if matches:
        return matches[0]
    envelope = context.topology.envelope_bounds_m
    if any(
        position[axis] < envelope[axis] or position[axis] > envelope[axis + 3]
        for axis in range(3)
    ):
        return "exterior"
    raise ValueError("source position is on or within ambiguous structural/intersection space")


def validate_source_space(
    source_space_id: str,
    context: ProviderContext,
    *,
    surface_category: str | None = None,
) -> str:
    source_space = _safe_string(source_space_id, "source_space_id")
    room_ids = {row.region_id for row in context.topology.spaces}
    if source_space != "exterior" and source_space not in room_ids:
        raise ValueError(f"source_space_id is not in public topology: {source_space!r}")
    if context.scenario_kind == "external" and source_space != "exterior":
        raise ValueError("source_space_id must be exterior for an external scenario")
    if context.scenario_kind in {"internal", "semi_enclosed"} and source_space not in room_ids:
        raise ValueError(
            f"source_space_id must be a real room for a {context.scenario_kind} scenario"
        )
    if surface_category == "exterior_surfaces" and source_space != "exterior":
        raise ValueError("source_space_id must be exterior for exterior surface mapping")
    if surface_category == "interior_cavity_surfaces" and source_space not in room_ids:
        raise ValueError("source_space_id must be a real room for interior surface mapping")
    return source_space


def surface_geometry_from_artifact(
    artifact: BuildingArtifact,
    row: Mapping[str, object],
    path: str,
) -> tuple[float, tuple[float, float, float], tuple[float, float, float]]:
    """Recompute one closed catalog face from immutable structural mesh nodes."""

    unknown = sorted(set(row) - _SURFACE_FACE_KEYS)
    missing = sorted({"face_id", "element_id", "node_ids"} - set(row))
    if unknown:
        raise ValueError(f"{path} has unknown field: {unknown[0]!r}")
    if missing:
        raise ValueError(f"{path} is missing required field: {missing[0]!r}")
    element_id = row.get("element_id")
    if isinstance(element_id, bool) or not isinstance(element_id, int):
        raise ValueError(f"{path}.element_id must be an integer")
    elements = {
        element.element_id: element
        for element in (*artifact.mesh.solids, *artifact.mesh.shells)
    }
    element = elements.get(element_id)
    if element is None:
        raise ValueError(f"{path}.element_id is not in the structural mesh")
    raw_node_ids = row.get("node_ids")
    if not _is_sequence(raw_node_ids) or len(raw_node_ids) not in {3, 4}:
        raise ValueError(f"{path}.node_ids must contain three or four IDs")
    node_ids: list[int] = []
    for index, value in enumerate(raw_node_ids):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{path}.node_ids[{index}] must be an integer")
        node_ids.append(value)
    if not is_oriented_element_boundary_face(element, tuple(node_ids)):
        raise ValueError(
            f"{path}.node_ids are not one real oriented boundary face"
        )
    node_by_id = {node.node_id: node for node in artifact.mesh.nodes}
    try:
        coordinates = tuple(node_by_id[node_id].coordinates for node_id in node_ids)
    except KeyError as exc:
        raise ValueError(f"{path}.node_ids reference an unknown mesh node") from exc
    origin = coordinates[0]
    area_vector = [0.0, 0.0, 0.0]
    for index in range(1, len(coordinates) - 1):
        first = tuple(coordinates[index][axis] - origin[axis] for axis in range(3))
        second = tuple(coordinates[index + 1][axis] - origin[axis] for axis in range(3))
        cross = (
            first[1] * second[2] - first[2] * second[1],
            first[2] * second[0] - first[0] * second[2],
            first[0] * second[1] - first[1] * second[0],
        )
        for axis in range(3):
            area_vector[axis] += cross[axis]
    magnitude = math.sqrt(sum(value * value for value in area_vector))
    if magnitude <= 2.0e-12:
        raise ValueError(f"{path} must have positive area derived from the mesh")
    area = magnitude / 2.0
    centroid = tuple(
        sum(point[axis] for point in coordinates) / len(coordinates)
        for axis in range(3)
    )
    normal = tuple(value / magnitude for value in area_vector)
    _validate_optional_surface_number(row, "area_m2", area, path)
    _validate_optional_surface_vector(row, "centroid_m", centroid, path)
    _validate_optional_surface_vector(row, "normal", normal, path)
    return area, centroid, normal  # type: ignore[return-value]


def is_oriented_element_boundary_face(
    element: SolidElement | ShellElement, node_ids: Sequence[object]
) -> bool:
    """Return whether IDs exactly follow one supported element boundary cycle."""

    if any(
        isinstance(node_id, bool) or not isinstance(node_id, int)
        for node_id in node_ids
    ):
        return False
    actual = tuple(node_ids)
    if isinstance(element, SolidElement):
        return any(
            actual == tuple(element.node_ids[index] for index in indices)
            for indices in _HEX_ORIENTED_FACES
        )
    return actual == element.node_ids


def _validate_optional_surface_number(
    row: Mapping[str, object], key: str, expected: float, path: str
) -> None:
    if key not in row:
        return
    value = _finite_coordinate(row[key], f"{path}.{key}")
    if abs(value - expected) > _SURFACE_GEOMETRY_TOLERANCE:
        raise ValueError(f"{path}.{key} does not match current mesh")


def _validate_optional_surface_vector(
    row: Mapping[str, object],
    key: str,
    expected: tuple[float, float, float],
    path: str,
) -> None:
    if key not in row:
        return
    raw = row[key]
    if not _is_sequence(raw) or len(raw) != 3:
        raise ValueError(f"{path}.{key} must contain three finite values")
    actual = tuple(
        _finite_coordinate(value, f"{path}.{key}[{index}]")
        for index, value in enumerate(raw)
    )
    if any(
        abs(actual[index] - expected[index]) > _SURFACE_GEOMETRY_TOLERANCE
        for index in range(3)
    ):
        raise ValueError(f"{path}.{key} does not match current mesh")


def source_space_evidence(
    *,
    provider_id: str,
    source_declared_id: str,
    source_space_id: str,
    context: ProviderContext,
    determination: str,
    surface_category: str | None = None,
    external_opening_ids: Sequence[str] = (),
) -> ProviderEvidence:
    """Publish the one closed source-space claim consumed by Task 6."""

    claims = {
        "schema_version": "provider_source_space_evidence@1",
        "provider_id": _safe_string(provider_id, "provider_id"),
        "source_declared_id": _safe_string(source_declared_id, "source_declared_id"),
        "source_space_id": validate_source_space(
            source_space_id, context, surface_category=surface_category
        ),
        "scenario_kind": context.scenario_kind,
        "topology_fingerprint": context.topology.fingerprint,
        "determination": _safe_string(determination, "determination"),
        "surface_category": surface_category,
        "external_opening_ids": tuple(
            _safe_string(value, "external_opening_id") for value in external_opening_ids
        ),
    }
    digest = fingerprint_value(claims)
    return ProviderEvidence(
        evidence_id=f"{provider_id}:evidence:source-space:{digest[:16]}",
        evidence_kind="provider_source_space",
        source_ids=(
            f"artifact:{context.artifact.fingerprint}",
            f"topology:{context.topology.fingerprint}",
            source_declared_id,
        ),
        claims=claims,
    )


@dataclass(frozen=True, slots=True)
class ProviderFragment:
    provider_id: str
    normalized_input: FrozenMapping
    axes_m: tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]
    node_ids: tuple[str, ...]
    element_ids: tuple[str, ...]
    fsi_face_ids: tuple[str, ...]
    required_ids: frozenset[str]
    declared_ids: frozenset[str]
    evidence: tuple[ProviderEvidence, ...]
    manifest: FrozenMapping
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "normalized_input", freeze_value(self.normalized_input, "normalized_input"))
        object.__setattr__(self, "axes_m", tuple(tuple(axis) for axis in self.axes_m))
        object.__setattr__(self, "node_ids", tuple(self.node_ids))
        object.__setattr__(self, "element_ids", tuple(self.element_ids))
        object.__setattr__(self, "fsi_face_ids", tuple(self.fsi_face_ids))
        object.__setattr__(self, "required_ids", frozenset(self.required_ids))
        object.__setattr__(self, "declared_ids", frozenset(self.declared_ids))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "manifest", freeze_value(self.manifest, "manifest"))
        core = {
            "provider_id": self.provider_id,
            "normalized_input": self.normalized_input,
            "axes_m": self.axes_m,
            "node_ids": self.node_ids,
            "element_ids": self.element_ids,
            "fsi_face_ids": self.fsi_face_ids,
            "required_ids": sorted(self.required_ids),
            "declared_ids": sorted(self.declared_ids),
            "evidence": [
                {
                    "evidence_id": row.evidence_id,
                    "fingerprint": row.fingerprint,
                }
                for row in self.evidence
            ],
            "manifest": self.manifest,
        }
        object.__setattr__(self, "fingerprint", fingerprint_value(core))


def _surface_rows(catalog: Mapping[str, object], category: str) -> tuple[Mapping[str, object], ...]:
    raw = catalog.get(category)
    if not _is_sequence(raw):
        raise ValueError(f"surface_catalog.{category} must be a sequence")
    return tuple(_as_mapping(row, f"surface_catalog.{category}") for row in raw)


def _as_mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be a mapping")
    return value


def _mapping_string(value: Mapping[str, object], key: str, path: str) -> str:
    return _safe_string(value.get(key), f"{path}.{key}")


def _safe_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value.strip()


def _finite_coordinate(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be finite")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{path} must be finite")
    return number


def _point_strictly_inside(point: Sequence[float], bounds: Sequence[float]) -> bool:
    return all(bounds[axis] < point[axis] < bounds[axis + 3] for axis in range(3))


def _bounds_tuple(value: object, path: str) -> tuple[float, float, float, float, float, float]:
    if not _is_sequence(value) or len(value) != 6:
        raise ValueError(f"{path} must contain exactly six numbers")
    numbers: list[float] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{path}[{index}] must be a finite number")
        number = float(item)
        if not math.isfinite(number):
            raise ValueError(f"{path}[{index}] must be a finite number")
        numbers.append(number)
    if any(numbers[axis + 3] <= numbers[axis] for axis in range(3)):
        raise ValueError(f"{path} must have positive extent on every axis")
    return tuple(numbers)  # type: ignore[return-value]


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


__all__ = [
    "FrozenMapping",
    "ProviderContext",
    "ProviderEstimate",
    "ProviderEvidence",
    "ProviderFragment",
    "ProviderTopology",
    "TopologyOpening",
    "TopologyRegion",
    "classify_source_space",
    "fingerprint_value",
    "freeze_value",
    "is_oriented_element_boundary_face",
    "source_space_evidence",
    "surface_geometry_from_artifact",
    "thaw_value",
    "validate_source_space",
]
