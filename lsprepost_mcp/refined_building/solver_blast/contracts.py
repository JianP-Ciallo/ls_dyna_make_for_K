"""Closed contracts for solver-complete Phase 18 blast scenes."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


_CONFIG_V1_KEYS = frozenset(
    {
        "schema_version",
        "unit_system",
        "tnt_equivalent_mass_kg",
        "charge_position_m",
        "detonation_time_s",
        "air_cell_size_m",
        "air_margin_m",
        "termination_time_s",
    }
)
_CONFIG_V2_KEYS = _CONFIG_V1_KEYS | {"ground_cell_size_m"}
_CONFIG_V3_KEYS = _CONFIG_V2_KEYS
_CONFIG_V4_KEYS = frozenset(
    {
        "schema_version",
        "unit_system",
        "tnt_equivalent_mass_kg",
        "charge_position_m",
        "detonation_time_s",
        "air_cell_size_m",
        "near_field_cell_size_m",
        "ground_cell_size_m",
        "air_margins_m",
        "coupling_buffer_layers",
        "material_profile",
        "termination_time_s",
    }
)
_SCHEMA_VERSION_V1 = "phase18.solver_blast.config@1"
_SCHEMA_VERSION_V2 = "phase18.solver_blast.config@2"
_SCHEMA_VERSION_V3 = "phase18.solver_blast.config@3"
_SCHEMA_VERSION = "phase18.solver_blast.config@4"
_UNIT_SYSTEM = "SI_m_s_kg_N_Pa"
SHORT_SOLVE_DEFAULT_TERMINATION_TIME_S = 5.0e-5
_MATERIAL_PROFILES = frozenset({"verification_reference", "project_calibrated"})
_ELEMENT_FAMILIES = frozenset({"Solid", "Shell", "Beam"})


@dataclass(frozen=True, slots=True)
class SolverBlastConfig:
    schema_version: str
    unit_system: str
    tnt_equivalent_mass_kg: float
    charge_position_m: tuple[float, float, float]
    detonation_time_s: float
    air_cell_size_m: float
    near_field_cell_size_m: float
    ground_cell_size_m: float
    air_margins_m: tuple[float, float, float, float, float]
    coupling_buffer_layers: int
    material_profile: str
    termination_time_s: float

    @property
    def air_margin_m(self) -> tuple[float, float, float]:
        """Conservative bridge for pre-layered internal consumers."""

        return (
            max(self.air_margins_m[0], self.air_margins_m[1]),
            max(self.air_margins_m[2], self.air_margins_m[3]),
            self.air_margins_m[4],
        )


@dataclass(frozen=True, slots=True)
class PhysicalMemberRecord:
    role: str
    element_family: str
    material_role: str
    dimensions_m: tuple[float, float, float]
    selection_basis: str
    connection_ids: tuple[str, ...]
    fluid_exposed: bool
    orientation_vector: tuple[float, float, float] | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.role, "role"),
            (self.material_role, "material_role"),
            (self.selection_basis, "selection_basis"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must be a non-empty string")
        if self.element_family not in _ELEMENT_FAMILIES:
            raise ValueError("element_family must be Solid, Shell, or Beam")
        if (
            not isinstance(self.dimensions_m, tuple)
            or len(self.dimensions_m) != 3
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0.0
                for value in self.dimensions_m
            )
        ):
            raise ValueError("dimensions_m must contain three positive finite numbers")
        if (
            not isinstance(self.connection_ids, tuple)
            or not self.connection_ids
            or any(not isinstance(value, str) or not value.strip() for value in self.connection_ids)
        ):
            raise ValueError("connection_ids must contain non-empty connection identifiers")
        if len(self.connection_ids) != len(set(self.connection_ids)):
            raise ValueError("connection_ids must be unique")
        if not isinstance(self.fluid_exposed, bool):
            raise ValueError("fluid_exposed must be a boolean")
        if self.orientation_vector is not None:
            if (
                not isinstance(self.orientation_vector, tuple)
                or len(self.orientation_vector) != 3
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    for value in self.orientation_vector
                )
                or math.sqrt(sum(float(value) ** 2 for value in self.orientation_vector)) <= 0.0
            ):
                raise ValueError("orientation_vector must contain a non-zero finite vector")


@dataclass(frozen=True, slots=True)
class PhysicalInterfaceRecord:
    interface_id: str
    connection_type: str
    source_roles: tuple[str, ...]
    target_roles: tuple[str, ...]
    evidence_kind: str
    shared_node_count: int
    positive_contact_area_m2: float
    positive_contact_length_m: float
    maximum_gap_m: float
    connection_tolerance_m: float
    source_element_count: int
    target_element_count: int

    def __post_init__(self) -> None:
        for value, label in (
            (self.interface_id, "interface_id"),
            (self.connection_type, "connection_type"),
            (self.evidence_kind, "evidence_kind"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must be a non-empty string")
        for value, label in (
            (self.source_roles, "source_roles"),
            (self.target_roles, "target_roles"),
        ):
            if (
                not isinstance(value, tuple)
                or not value
                or len(value) != len(set(value))
                or any(not isinstance(role, str) or not role.strip() for role in value)
            ):
                raise ValueError(f"{label} must contain unique non-empty roles")
        if set(self.source_roles) & set(self.target_roles):
            raise ValueError("source_roles and target_roles must be disjoint")
        for value, label in (
            (self.shared_node_count, "shared_node_count"),
            (self.source_element_count, "source_element_count"),
            (self.target_element_count, "target_element_count"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{label} must be a nonnegative integer")
        if self.source_element_count == 0 or self.target_element_count == 0:
            raise ValueError("interface element counts must be positive")
        if (
            isinstance(self.positive_contact_area_m2, bool)
            or not isinstance(self.positive_contact_area_m2, (int, float))
            or not math.isfinite(float(self.positive_contact_area_m2))
            or float(self.positive_contact_area_m2) < 0.0
        ):
            raise ValueError("positive_contact_area_m2 must be finite and nonnegative")
        for value, label in (
            (self.positive_contact_length_m, "positive_contact_length_m"),
            (self.maximum_gap_m, "maximum_gap_m"),
            (self.connection_tolerance_m, "connection_tolerance_m"),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0.0
            ):
                raise ValueError(f"{label} must be finite and nonnegative")
        if self.maximum_gap_m > self.connection_tolerance_m:
            raise ValueError("maximum_gap_m exceeds connection_tolerance_m")


@dataclass(frozen=True, slots=True)
class AuditFinding:
    finding_id: str
    member_role: str
    message: str


def normalize_solver_blast_config(value: Mapping[str, object]) -> SolverBlastConfig:
    """Normalize every published input version to the exact public v4 contract."""

    if not isinstance(value, Mapping):
        raise TypeError("solver blast config must be a mapping")
    requested_schema = value.get("schema_version")
    if requested_schema == _SCHEMA_VERSION_V1:
        expected_keys = _CONFIG_V1_KEYS
    elif requested_schema == _SCHEMA_VERSION_V2:
        expected_keys = _CONFIG_V2_KEYS
    elif requested_schema == _SCHEMA_VERSION_V3:
        expected_keys = _CONFIG_V3_KEYS
    elif requested_schema == _SCHEMA_VERSION:
        expected_keys = _CONFIG_V4_KEYS
    else:
        raise ValueError(
            "schema_version must be "
            f"{_SCHEMA_VERSION!r}, {_SCHEMA_VERSION_V3!r}, "
            f"{_SCHEMA_VERSION_V2!r}, or {_SCHEMA_VERSION_V1!r}"
        )
    keys = set(value)
    missing = expected_keys - keys
    extra = keys - expected_keys
    if missing:
        raise ValueError(f"missing keys: {sorted(missing)}")
    if extra:
        raise ValueError(f"unexpected keys: {sorted(extra)}")

    unit_system = _literal(value["unit_system"], _UNIT_SYSTEM, "unit_system")
    mass = _finite(value["tnt_equivalent_mass_kg"], "tnt_equivalent_mass_kg")
    if not 0.1 <= mass <= 100.0:
        raise ValueError("tnt_equivalent_mass_kg must be between 0.1 and 100 kg")
    position = _vector3(value["charge_position_m"], "charge_position_m")
    detonation = _finite(value["detonation_time_s"], "detonation_time_s")
    if detonation < 0.0:
        raise ValueError("detonation_time_s must be nonnegative")
    cell_size = _finite(value["air_cell_size_m"], "air_cell_size_m")
    if not 0.15 <= cell_size <= 0.50:
        raise ValueError("air_cell_size_m must be between 0.15 and 0.50 m")
    if requested_schema == _SCHEMA_VERSION_V1:
        ground_cell_size = 0.25
    else:
        ground_cell_size = _finite(
            value["ground_cell_size_m"], "ground_cell_size_m"
        )
        if not 0.10 <= ground_cell_size <= 0.50:
            raise ValueError("ground_cell_size_m must be between 0.10 and 0.50 m")
    if requested_schema == _SCHEMA_VERSION:
        near_field_cell_size = _finite(
            value["near_field_cell_size_m"], "near_field_cell_size_m"
        )
        if not 0.05 <= near_field_cell_size <= cell_size:
            raise ValueError(
                "near_field_cell_size_m must be between 0.05 m and air_cell_size_m"
            )
        margins = _vector5(value["air_margins_m"], "air_margins_m")
        if any(component <= 0.0 for component in margins):
            raise ValueError("air_margins_m values must be positive")
        layers = value["coupling_buffer_layers"]
        if (
            isinstance(layers, bool)
            or not isinstance(layers, int)
            or not 1 <= layers <= 5
        ):
            raise ValueError(
                "coupling_buffer_layers must be an integer between 1 and 5"
            )
        material_profile = value["material_profile"]
        if (
            not isinstance(material_profile, str)
            or material_profile not in _MATERIAL_PROFILES
        ):
            raise ValueError(
                "material_profile must be 'verification_reference' or "
                "'project_calibrated'"
            )
    else:
        legacy_margins = _vector3(value["air_margin_m"], "air_margin_m")
        if any(component <= 0.0 for component in legacy_margins):
            raise ValueError("air_margin_m values must be positive")
        margins = (
            legacy_margins[0],
            legacy_margins[0],
            legacy_margins[1],
            legacy_margins[1],
            legacy_margins[2],
        )
        near_field_cell_size = min(0.15, cell_size)
        layers = 2
        material_profile = "verification_reference"
    termination = _finite(value["termination_time_s"], "termination_time_s")
    if termination <= 0.0:
        raise ValueError("termination_time_s must be positive")
    if detonation >= termination:
        raise ValueError("detonation_time_s must be less than termination_time_s")
    return SolverBlastConfig(
        schema_version=_SCHEMA_VERSION,
        unit_system=unit_system,
        tnt_equivalent_mass_kg=mass,
        charge_position_m=position,
        detonation_time_s=detonation,
        air_cell_size_m=cell_size,
        near_field_cell_size_m=near_field_cell_size,
        ground_cell_size_m=ground_cell_size,
        air_margins_m=margins,
        coupling_buffer_layers=layers,
        material_profile=material_profile,
        termination_time_s=termination,
    )


def _literal(value: object, expected: str, path: str) -> str:
    if value != expected:
        raise ValueError(f"{path} must be {expected!r}")
    return expected


def _finite(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{path} must be finite")
    return result


def _vector3(value: object, path: str) -> tuple[float, float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{path} must contain exactly three finite numbers")
    rows = tuple(_finite(component, f"{path}[{index}]") for index, component in enumerate(value))
    if len(rows) != 3:
        raise ValueError(f"{path} must contain exactly three finite numbers")
    return (rows[0], rows[1], rows[2])


def _vector5(
    value: object, path: str
) -> tuple[float, float, float, float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{path} must contain exactly five finite numbers")
    rows = tuple(
        _finite(component, f"{path}[{index}]")
        for index, component in enumerate(value)
    )
    if len(rows) != 5:
        raise ValueError(f"{path} must contain exactly five finite numbers")
    return (rows[0], rows[1], rows[2], rows[3], rows[4])
