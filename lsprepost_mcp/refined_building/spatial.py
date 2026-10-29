"""Spatial topology for refined buildings, including real void regions."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from .contracts import JSONDict, normalize_building_definition


PointClassification = Literal["void", "envelope", "outside"]


@dataclass(frozen=True, slots=True)
class AxisAlignedBox:
    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float

    def __post_init__(self) -> None:
        values = self.as_tuple()
        if any(isinstance(value, bool) or not math.isfinite(float(value)) for value in values):
            raise ValueError("box coordinates must be finite numbers")
        if self.max_x <= self.min_x or self.max_y <= self.min_y or self.max_z <= self.min_z:
            raise ValueError("box must have positive extent on every axis")

    @classmethod
    def from_bounds(cls, bounds: Sequence[object]) -> "AxisAlignedBox":
        if len(bounds) != 6:
            raise ValueError("bounds must contain exactly six coordinates")
        return cls(*(float(value) for value in bounds))

    @property
    def volume_m3(self) -> float:
        return (
            (self.max_x - self.min_x)
            * (self.max_y - self.min_y)
            * (self.max_z - self.min_z)
        )

    def as_tuple(self) -> tuple[float, float, float, float, float, float]:
        return (self.min_x, self.min_y, self.min_z, self.max_x, self.max_y, self.max_z)

    def contains_point(self, point_m: Sequence[object]) -> bool:
        if len(point_m) != 3:
            raise ValueError("point must contain exactly three coordinates")
        point = tuple(float(value) for value in point_m)
        if any(not math.isfinite(value) for value in point):
            raise ValueError("point coordinates must be finite")
        return (
            self.min_x <= point[0] <= self.max_x
            and self.min_y <= point[1] <= self.max_y
            and self.min_z <= point[2] <= self.max_z
        )

    def contains_box(self, other: "AxisAlignedBox") -> bool:
        return (
            self.min_x <= other.min_x
            and self.min_y <= other.min_y
            and self.min_z <= other.min_z
            and self.max_x >= other.max_x
            and self.max_y >= other.max_y
            and self.max_z >= other.max_z
        )

    def intersects(self, other: "AxisAlignedBox") -> bool:
        """Return true only for a positive-volume intersection."""

        return (
            max(self.min_x, other.min_x) < min(self.max_x, other.max_x)
            and max(self.min_y, other.min_y) < min(self.max_y, other.max_y)
            and max(self.min_z, other.min_z) < min(self.max_z, other.max_z)
        )


@dataclass(frozen=True, slots=True)
class SpatialTopology:
    envelope: AxisAlignedBox
    void_regions: tuple[tuple[str, AxisAlignedBox], ...]
    opening_regions: tuple[tuple[str, AxisAlignedBox], ...]
    adjacency: Mapping[str, tuple[str, ...]]
    gross_volume_m3: float
    void_volume_m3: float
    fingerprint: str

    def classify_point(self, point_m: Sequence[object]) -> PointClassification:
        if not self.envelope.contains_point(point_m):
            return "outside"
        if any(box.contains_point(point_m) for _, box in self.void_regions):
            return "void"
        if any(box.contains_point(point_m) for _, box in self.opening_regions):
            return "void"
        return "envelope"

    def to_manifest(self) -> JSONDict:
        return {
            "schema_version": "1.0.0",
            "envelope_bounds_m": list(self.envelope.as_tuple()),
            "void_regions": [
                {"id": region_id, "bounds_m": list(box.as_tuple())}
                for region_id, box in self.void_regions
            ],
            "opening_regions": [
                {"id": region_id, "bounds_m": list(box.as_tuple())}
                for region_id, box in self.opening_regions
            ],
            "adjacency": {key: list(value) for key, value in sorted(self.adjacency.items())},
            "gross_volume_m3": self.gross_volume_m3,
            "void_volume_m3": self.void_volume_m3,
            "fingerprint": self.fingerprint,
        }


def compile_spatial_topology(definition: Mapping[str, object]) -> SpatialTopology:
    """Compile normalized void, opening and adjacency semantics."""

    normalized = normalize_building_definition(definition)
    envelope_data = normalized["envelope"]
    assert isinstance(envelope_data, dict)
    origin = envelope_data["origin_m"]
    size = envelope_data["size_m"]
    assert isinstance(origin, list) and isinstance(size, list)
    envelope = AxisAlignedBox(
        float(origin[0]),
        float(origin[1]),
        float(origin[2]),
        float(origin[0]) + float(size[0]),
        float(origin[1]) + float(size[1]),
        float(origin[2]) + float(size[2]),
    )

    void_rows = normalized["spaces"]
    assert isinstance(void_rows, list)
    void_regions: list[tuple[str, AxisAlignedBox]] = []
    for row in void_rows:
        assert isinstance(row, dict) and isinstance(row["id"], str) and isinstance(row["bounds_m"], list)
        void_regions.append((row["id"], AxisAlignedBox.from_bounds(row["bounds_m"])))
    void_regions.sort(key=lambda item: item[0])
    for index, (left_id, left_box) in enumerate(void_regions):
        for right_id, right_box in void_regions[index + 1 :]:
            if left_box.intersects(right_box):
                raise ValueError(f"space regions overlap: {left_id!r} and {right_id!r}")

    adjacency_work: dict[str, set[str]] = {space_id: set() for space_id, _ in void_regions}
    opening_rows = normalized["openings"]
    assert isinstance(opening_rows, list)
    opening_regions: list[tuple[str, AxisAlignedBox]] = []
    for row in opening_rows:
        assert isinstance(row, dict)
        opening_id = row["id"]
        bounds = row["bounds_m"]
        connects = row["connects"]
        assert isinstance(opening_id, str) and isinstance(bounds, list) and isinstance(connects, list)
        left, right = str(connects[0]), str(connects[1])
        adjacency_work.setdefault(left, set()).add(right)
        adjacency_work.setdefault(right, set()).add(left)
        opening_regions.append((opening_id, AxisAlignedBox.from_bounds(bounds)))
    opening_regions.sort(key=lambda item: item[0])

    adjacency = {
        key: tuple(sorted(neighbours)) for key, neighbours in sorted(adjacency_work.items())
    }
    manifest_core = {
        "schema_version": "1.0.0",
        "envelope_bounds_m": list(envelope.as_tuple()),
        "void_regions": [
            {"id": region_id, "bounds_m": list(box.as_tuple())}
            for region_id, box in void_regions
        ],
        "opening_regions": [
            {"id": region_id, "bounds_m": list(box.as_tuple())}
            for region_id, box in opening_regions
        ],
        "adjacency": {key: list(value) for key, value in adjacency.items()},
        "gross_volume_m3": envelope.volume_m3,
        "void_volume_m3": sum(box.volume_m3 for _, box in void_regions),
    }
    canonical = json.dumps(manifest_core, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return SpatialTopology(
        envelope=envelope,
        void_regions=tuple(void_regions),
        opening_regions=tuple(opening_regions),
        adjacency=MappingProxyType(adjacency),
        gross_volume_m3=envelope.volume_m3,
        void_volume_m3=sum(box.volume_m3 for _, box in void_regions),
        fingerprint=fingerprint,
    )
