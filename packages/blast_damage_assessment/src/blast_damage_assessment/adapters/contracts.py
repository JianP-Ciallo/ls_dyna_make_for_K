"""Records crossing the solver-adapter boundary contain package and NumPy types only."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Iterator, Mapping, Protocol

import numpy as np

from ..contracts import Issue


class EntityKind(str, Enum):
    NODE = "node"
    SHELL = "shell"
    SOLID = "solid"
    BEAM = "beam"


@dataclass(frozen=True)
class FieldAvailability:
    available: bool
    reason: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.available, bool):
            raise ValueError("available must be boolean")
        if self.available and self.reason is not None:
            raise ValueError("available field cannot have a reason")
        if not self.available and (not isinstance(self.reason, str) or not self.reason.strip()):
            raise ValueError("unavailable field must have a reason")


@dataclass(frozen=True)
class ArrayField:
    entity_kind: EntityKind
    entity_ids: np.ndarray
    time_indices: np.ndarray
    raw_values: np.ndarray
    raw_unit: str
    standard_values: np.ndarray
    standard_unit: str
    conversion_id: str
    physical_meaning: str
    source_field_name: str
    availability: FieldAvailability = field(default_factory=lambda: FieldAvailability(True, None))

    def __post_init__(self) -> None:
        for name in ("entity_ids", "time_indices", "raw_values", "standard_values"):
            value = getattr(self, name)
            if not isinstance(value, np.ndarray):
                raise ValueError(f"{name} must be a NumPy array")
            value.setflags(write=False)
        for name in (
            "raw_unit",
            "standard_unit",
            "conversion_id",
            "physical_meaning",
            "source_field_name",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True)
class StateChunk:
    times: np.ndarray
    fields: Mapping[str, ArrayField]
    availability: FieldAvailability = field(default_factory=lambda: FieldAvailability(True, None))

    def __post_init__(self) -> None:
        if not isinstance(self.times, np.ndarray):
            raise ValueError("times must be a NumPy array")
        self.times.setflags(write=False)
        if not isinstance(self.fields, Mapping):
            raise ValueError("fields must be a mapping")
        if not all(isinstance(name, str) and isinstance(value, ArrayField) for name, value in self.fields.items()):
            raise ValueError("fields must map strings to ArrayField values")
        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))

    @property
    def values(self) -> Mapping[str, np.ndarray]:
        return MappingProxyType(
            {name: field.standard_values for name, field in self.fields.items()}
        )


@dataclass(frozen=True)
class GeometryIndex:
    node_ids: np.ndarray
    initial_coordinates: np.ndarray
    element_ids: Mapping[EntityKind, np.ndarray]
    part_ids: Mapping[EntityKind, np.ndarray]
    connectivity: Mapping[EntityKind, np.ndarray]

    def __post_init__(self) -> None:
        if not isinstance(self.node_ids, np.ndarray) or not isinstance(self.initial_coordinates, np.ndarray):
            raise ValueError("geometry coordinates and IDs must be NumPy arrays")
        self.node_ids.setflags(write=False)
        self.initial_coordinates.setflags(write=False)
        object.__setattr__(self, "element_ids", MappingProxyType(dict(self.element_ids)))
        object.__setattr__(self, "part_ids", MappingProxyType(dict(self.part_ids)))
        object.__setattr__(self, "connectivity", MappingProxyType(dict(self.connectivity)))


@dataclass(frozen=True)
class SolverQuality:
    termination: str
    problem_time: float | None
    termination_time: float | None
    final_state_time: float | None
    max_hourglass_ratio: float | None
    issues: tuple[Issue, ...] = ()


@dataclass(frozen=True)
class AdapterProbe:
    adapter_id: str
    adapter_version: str
    geometry: GeometryIndex | None
    state_count: int
    fields: Mapping[str, FieldAvailability]
    solver_quality: SolverQuality

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))


class ResultAdapter(Protocol):
    def probe(self, result_dir: Path) -> AdapterProbe: ...

    def iter_state_chunks(self, result_dir: Path, chunk_size: int) -> Iterator[StateChunk]: ...
