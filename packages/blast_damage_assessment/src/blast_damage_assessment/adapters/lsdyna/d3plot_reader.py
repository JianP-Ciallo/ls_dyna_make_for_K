"""State-filtered LASSO reader that returns only package-owned NumPy records."""

from __future__ import annotations

import gc
import math
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Iterator, Mapping

import numpy as np

from ...errors import ContractError
from ..contracts import ArrayField, EntityKind, FieldAvailability, GeometryIndex, StateChunk


FIELD_GROUPS = {
    "node_kinematics": ("node_displacement", "node_velocity", "node_acceleration"),
    "solid_response": (
        "element_solid_stress",
        "element_solid_effective_plastic_strain",
        "element_solid_history_variables",
        "element_solid_is_alive",
    ),
    "shell_response": (
        "element_shell_stress",
        "element_shell_effective_plastic_strain",
        "element_shell_history_vars",
        "element_shell_is_alive",
        "element_shell_strain",
    ),
    "beam_response": (
        "element_beam_axial_force",
        "element_beam_shear_force",
        "element_beam_is_alive",
    ),
}

FIELD_ALIASES = {
    "node_displacement": ("node_displacement",),
    "node_velocity": ("node_velocity",),
    "node_acceleration": ("node_acceleration",),
    "solid_stress": ("element_solid_stress",),
    "solid_effective_plastic_strain": ("element_solid_effective_plastic_strain",),
    "solid_history_variables": ("element_solid_history_variables",),
    "solid_is_alive": ("element_solid_is_alive",),
    "shell_stress": ("element_shell_stress",),
    "shell_effective_plastic_strain": ("element_shell_effective_plastic_strain",),
    "shell_history_variables": ("element_shell_history_vars", "element_shell_history_variables"),
    "shell_is_alive": ("element_shell_is_alive",),
    "shell_strain": ("element_shell_strain",),
    "beam_axial_force": ("element_beam_axial_force",),
    "beam_shear_force": ("element_beam_shear_force",),
    "beam_is_alive": ("element_beam_is_alive",),
}

_SOURCE_TO_SEMANTIC = {
    source: semantic for semantic, aliases in FIELD_ALIASES.items() for source in aliases
}
_GEOMETRY_KEYS = {
    EntityKind.SOLID: (
        "element_solid_ids",
        "element_solid_node_indexes",
        "element_solid_part_indexes",
    ),
    EntityKind.SHELL: (
        "element_shell_ids",
        "element_shell_node_indexes",
        "element_shell_part_indexes",
    ),
    EntityKind.BEAM: (
        "element_beam_ids",
        "element_beam_node_indexes",
        "element_beam_part_indexes",
    ),
}
_OUTPUT_METADATA = {
    "node_displacement": (EntityKind.NODE, "node_displacement_m", "model_length", "m", "node current position minus initial coordinates"),
    "node_velocity": (EntityKind.NODE, "node_velocity_m_per_s", "model_length/model_time", "m/s", "nodal velocity"),
    "node_acceleration": (EntityKind.NODE, "node_acceleration_m_per_s2", "model_length/model_time^2", "m/s^2", "nodal acceleration"),
    "solid_stress": (EntityKind.SOLID, "solid_stress_pa", "model_stress", "Pa", "solid stress tensor"),
    "solid_effective_plastic_strain": (EntityKind.SOLID, "solid_effective_plastic_strain", "1", "1", "solid effective plastic strain"),
    "solid_history_variables": (EntityKind.SOLID, "solid_history_variables", "material_defined", "material_defined", "solid material history variables"),
    "solid_is_alive": (EntityKind.SOLID, "solid_is_alive", "1", "1", "solid numerical alive state"),
    "shell_stress": (EntityKind.SHELL, "shell_stress_pa", "model_stress", "Pa", "shell stress tensor"),
    "shell_effective_plastic_strain": (EntityKind.SHELL, "shell_effective_plastic_strain", "1", "1", "shell effective plastic strain"),
    "shell_history_variables": (EntityKind.SHELL, "shell_history_variables", "material_defined", "material_defined", "shell material history variables"),
    "shell_is_alive": (EntityKind.SHELL, "shell_is_alive", "1", "1", "shell numerical alive state"),
    "shell_strain": (EntityKind.SHELL, "shell_strain", "1", "1", "shell strain tensor"),
    "beam_axial_force": (EntityKind.BEAM, "beam_axial_force_n", "model_force", "N", "beam axial force"),
    "beam_shear_force": (EntityKind.BEAM, "beam_shear_force_n", "model_force", "N", "beam shear force"),
    "beam_is_alive": (EntityKind.BEAM, "beam_is_alive", "1", "1", "beam numerical alive state"),
}


@dataclass(frozen=True)
class D3plotProbe:
    geometry: GeometryIndex
    timesteps: np.ndarray
    state_count: int
    fields: Mapping[str, FieldAvailability]
    aliases: Mapping[str, str]

    def __post_init__(self) -> None:
        self.timesteps.setflags(write=False)
        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))
        object.__setattr__(self, "aliases", MappingProxyType(dict(self.aliases)))


class LassoD3plotReader:
    def __init__(
        self,
        d3plot_path: Path,
        *,
        d3plot_factory: Callable[..., object] | None = None,
        length_to_m: float = 1.0,
        time_to_s: float = 1.0,
        stress_to_pa: float = 1.0,
        force_to_n: float = 1.0,
    ):
        self.d3plot_path = Path(d3plot_path)
        if d3plot_factory is None:
            from lasso.dyna import D3plot

            d3plot_factory = D3plot
        self._factory = d3plot_factory
        self._scales = {
            "length": self._positive_scale(length_to_m, "length_to_m"),
            "time": self._positive_scale(time_to_s, "time_to_s"),
            "stress": self._positive_scale(stress_to_pa, "stress_to_pa"),
            "force": self._positive_scale(force_to_n, "force_to_n"),
        }
        self._geometry: GeometryIndex | None = None
        self._timesteps: np.ndarray | None = None
        self._probe: D3plotProbe | None = None

    @staticmethod
    def _positive_scale(value: float, name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ContractError(f"{name} must be a positive finite number")
        return float(value)

    def _open(self, *, state_filter=None, state_array_filter=None):
        return self._factory(
            str(self.d3plot_path),
            state_filter=state_filter,
            state_array_filter=list(state_array_filter or ()),
            buffered_reading=True,
        )

    def _first_pass(self) -> tuple[GeometryIndex, np.ndarray]:
        if self._geometry is not None and self._timesteps is not None:
            return self._geometry, self._timesteps
        database = self._open(state_array_filter=("timesteps",))
        try:
            arrays = database.arrays
            timesteps = np.array(arrays.get("timesteps", ()), dtype=float, copy=True)
            if timesteps.ndim != 1 or timesteps.size == 0 or not np.all(np.isfinite(timesteps)):
                raise ContractError("d3plot timesteps are missing or invalid")
            if np.any(np.diff(timesteps) < 0.0):
                raise ContractError("d3plot time decreases")
            timesteps *= self._scales["time"]
            node_ids = np.array(arrays.get("node_ids", ()), dtype=np.int64, copy=True)
            coordinates = np.array(arrays.get("node_coordinates", ()), dtype=float, copy=True)
            if node_ids.ndim != 1 or node_ids.size == 0:
                raise ContractError("d3plot node IDs are missing")
            if np.unique(node_ids).size != node_ids.size:
                raise ContractError("d3plot contains duplicate node IDs")
            if coordinates.shape != (node_ids.size, 3) or not np.all(np.isfinite(coordinates)):
                raise ContractError("d3plot node coordinates are invalid")
            coordinates *= self._scales["length"]
            all_part_ids = np.array(arrays.get("part_ids", ()), dtype=np.int64, copy=True)
            element_ids: dict[EntityKind, np.ndarray] = {}
            part_ids: dict[EntityKind, np.ndarray] = {}
            connectivity: dict[EntityKind, np.ndarray] = {}
            for kind, (ids_key, nodes_key, parts_key) in _GEOMETRY_KEYS.items():
                ids = np.array(arrays.get(ids_key, ()), dtype=np.int64, copy=True)
                nodes = np.array(arrays.get(nodes_key, np.empty((0, 0))), dtype=np.int64, copy=True)
                part_indexes = np.array(arrays.get(parts_key, ()), dtype=np.int64, copy=True)
                if nodes.ndim != 2:
                    raise ContractError(f"{kind.value} connectivity must be two-dimensional")
                if ids.size != nodes.shape[0]:
                    raise ContractError(f"{kind.value} element/connectivity size mismatch")
                if ids.size != part_indexes.size:
                    raise ContractError(f"{kind.value} element/Part mapping size mismatch")
                primary_nodes = nodes[:, :2] if kind is EntityKind.BEAM else nodes
                if primary_nodes.size and (np.min(primary_nodes) < 0 or np.max(primary_nodes) >= node_ids.size):
                    raise ContractError(f"{kind.value} connectivity references an unknown node")
                if part_indexes.size and (
                    all_part_ids.size == 0
                    or np.min(part_indexes) < 0
                    or np.max(part_indexes) >= all_part_ids.size
                ):
                    raise ContractError(f"{kind.value} Part mapping references an unknown Part")
                element_ids[kind] = ids
                connectivity[kind] = primary_nodes.copy()
                part_ids[kind] = all_part_ids[part_indexes].copy() if part_indexes.size else np.array([], dtype=np.int64)
            geometry = GeometryIndex(node_ids, coordinates, element_ids, part_ids, connectivity)
        finally:
            del database
            gc.collect()
        self._geometry = geometry
        self._timesteps = timesteps
        return geometry, timesteps

    def read_geometry(self) -> GeometryIndex:
        return self._first_pass()[0]

    def probe(self) -> D3plotProbe:
        if self._probe is not None:
            return self._probe
        geometry, timesteps = self._first_pass()
        fields: dict[str, FieldAvailability] = {}
        aliases: dict[str, str] = {}
        for group_sources in FIELD_GROUPS.values():
            database = self._open(state_filter={0}, state_array_filter=("timesteps", *group_sources))
            try:
                arrays = database.arrays
                for source in group_sources:
                    semantic = _SOURCE_TO_SEMANTIC[source]
                    if semantic in fields and fields[semantic].available:
                        continue
                    selected = next((alias for alias in FIELD_ALIASES[semantic] if alias in arrays), None)
                    if selected is None:
                        fields[semantic] = FieldAvailability(False, "d3plot field is absent")
                    else:
                        fields[semantic] = FieldAvailability(True, None)
                        aliases[semantic] = selected
            finally:
                del database
                gc.collect()
        if fields["node_displacement"].available:
            database = self._open(
                state_filter={0},
                state_array_filter=("timesteps", aliases["node_displacement"]),
            )
            try:
                positions = np.asarray(database.arrays[aliases["node_displacement"]], dtype=float)
                displacement = positions[0] * self._scales["length"] - geometry.initial_coordinates
                extent = float(np.linalg.norm(np.ptp(geometry.initial_coordinates, axis=0)))
                tolerance = max(1e-9, 1e-7 * extent)
                if displacement.size and float(np.max(np.abs(displacement))) > tolerance:
                    raise ContractError("physical initial displacement exceeds the model tolerance")
            finally:
                del database
                gc.collect()
        self._probe = D3plotProbe(geometry, timesteps.copy(), timesteps.size, fields, aliases)
        return self._probe

    def _standard_values(self, semantic: str, raw: np.ndarray, geometry: GeometryIndex) -> tuple[np.ndarray, str]:
        if semantic == "node_displacement":
            return raw * self._scales["length"] - geometry.initial_coordinates[None, :, :], "lasso.current_position_to_displacement@1"
        if semantic == "node_velocity":
            return raw * self._scales["length"] / self._scales["time"], "units.velocity_to_si@1"
        if semantic == "node_acceleration":
            return raw * self._scales["length"] / self._scales["time"] ** 2, "units.acceleration_to_si@1"
        if semantic.endswith("stress"):
            return raw * self._scales["stress"], "units.stress_to_pa@1"
        if semantic.endswith("force"):
            return raw * self._scales["force"], "units.force_to_n@1"
        return raw.copy(), "units.identity@1"

    def iter_state_chunks(self, field_group: str, chunk_size: int) -> Iterator[StateChunk]:
        if field_group not in FIELD_GROUPS:
            raise ContractError(f"unknown d3plot field group: {field_group}")
        if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
            raise ContractError("chunk_size must be a positive integer")
        probe = self.probe()
        requested_semantics = tuple(_SOURCE_TO_SEMANTIC[source] for source in FIELD_GROUPS[field_group])
        selected_sources = tuple(
            probe.aliases[semantic]
            for semantic in requested_semantics
            if probe.fields[semantic].available
        )
        for start in range(0, probe.state_count, chunk_size):
            stop = min(start + chunk_size, probe.state_count)
            indexes = set(range(start, stop))
            database = self._open(
                state_filter=indexes,
                state_array_filter=("timesteps", *selected_sources),
            )
            try:
                fields: dict[str, ArrayField] = {}
                for semantic in requested_semantics:
                    availability = probe.fields[semantic]
                    if not availability.available:
                        continue
                    source = probe.aliases[semantic]
                    raw = np.array(database.arrays[source], copy=True)
                    if not np.all(np.isfinite(raw)):
                        raise ContractError(f"d3plot field {source} contains non-finite values")
                    kind, output_name, raw_unit, standard_unit, physical_meaning = _OUTPUT_METADATA[semantic]
                    standard, conversion = self._standard_values(semantic, raw, probe.geometry)
                    ids = (
                        probe.geometry.node_ids
                        if kind is EntityKind.NODE
                        else probe.geometry.element_ids[kind]
                    )
                    fields[output_name] = ArrayField(
                        entity_kind=kind,
                        entity_ids=ids.copy(),
                        time_indices=np.arange(start, stop, dtype=np.int64),
                        raw_values=raw,
                        raw_unit=raw_unit,
                        standard_values=standard,
                        standard_unit=standard_unit,
                        conversion_id=conversion,
                        physical_meaning=physical_meaning,
                        source_field_name=source,
                        availability=availability,
                    )
                yield StateChunk(
                    times=probe.timesteps[start:stop].copy(),
                    fields=fields,
                    availability=FieldAvailability(True, None),
                )
            finally:
                del database
                gc.collect()


def iter_state_chunks(result_dir: Path, chunk_size: int) -> Iterator[StateChunk]:
    reader = LassoD3plotReader(Path(result_dir) / "d3plot")
    for group in FIELD_GROUPS:
        yield from reader.iter_state_chunks(group, chunk_size)
