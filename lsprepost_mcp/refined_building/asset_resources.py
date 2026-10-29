"""Registry for Phase 18D parameterized detailed-building assets.

The fixed-K model-library scanner intentionally ignores these ``asset.json``
rows.  They are semantic inputs for the refined-building compiler rather than
ready-to-export keyword payloads.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from ..config import MODEL_LIBRARY_DIR
from .systems import list_structural_systems


_ASSET_ROOT = MODEL_LIBRARY_DIR / "detailed_buildings" / "phase18d"
_SCHEMA_VERSION = "0.1.0"
_ASSET_RESOURCE_KEYS = frozenset(
    {
        "schema_version",
        "id",
        "version",
        "legacy_asset_id",
        "source_type",
        "generator",
        "capability",
        "unit_system",
        "validation_status",
        "solver_ready",
        "requires_project_review",
        "geometry_fields",
        "default_geometry",
        "default_structural_system",
        "allowed_structural_systems",
        "allowed_fidelity_profiles",
        "default_fidelity_profile",
        "allowed_mesh_profiles",
        "default_mesh_profile",
        "mesh_profiles",
        "material_candidates",
        "unresolved_material_roles",
        "source_reference_lineage",
    }
)
_FIDELITY_PROFILES = ("structural_core", "blast_response", "research_detailed")
_MESH_PROFILES = ("coarse", "standard", "fine")
_MESH_ROW_KEYS = (
    "member_foundation_target_m",
    "slab_wall_target_m",
    "rebar_target_length_m",
    "steel_member_target_length_m",
    "panel_target_m",
    "minimum_thickness_layers",
)
_MESH_PROFILE_ROWS: dict[str, dict[str, float | int]] = {
    "coarse": {
        "member_foundation_target_m": 0.150,
        "slab_wall_target_m": 0.0750,
        "rebar_target_length_m": 0.150,
        "steel_member_target_length_m": 0.150,
        "panel_target_m": 0.150,
        "minimum_thickness_layers": 2,
    },
    "standard": {
        "member_foundation_target_m": 0.100,
        "slab_wall_target_m": 0.0500,
        "rebar_target_length_m": 0.100,
        "steel_member_target_length_m": 0.100,
        "panel_target_m": 0.100,
        "minimum_thickness_layers": 3,
    },
    "fine": {
        "member_foundation_target_m": 0.075,
        "slab_wall_target_m": 0.0375,
        "rebar_target_length_m": 0.075,
        "steel_member_target_length_m": 0.075,
        "panel_target_m": 0.075,
        "minimum_thickness_layers": 4,
    },
}
_MATERIAL_CANDIDATES = {
    "concrete": "two_storey_rc_frame_mid5_concrete_kc",
    "reinforcing_steel": "two_storey_rc_frame_mid8_rebar_d8_d18",
    "structural_steel": "mild_steel_mat24_demo",
}
_UNRESOLVED_MATERIAL_ROLES = ("facade", "glazing", "doors", "nonstructural")
_ALLOWED_UNRESOLVED_MATERIAL_ROLES = _UNRESOLVED_MATERIAL_ROLES + (
    "metal_roof",
    "signage",
    "escalator_equipment",
    "escalator_balustrade",
    "escalator_handrail",
)


@dataclass(frozen=True, slots=True)
class DetailedBuildingAssetDescriptor:
    """Immutable public view of one Phase 18D asset family."""

    resource_id: str
    version: str
    legacy_asset_id: str
    capability: str
    default_geometry: Mapping[str, object]
    geometry_fields: tuple[str, ...]
    default_structural_system: str
    allowed_structural_systems: tuple[str, ...]
    fidelity_profiles: tuple[str, ...]
    default_fidelity_profile: str
    mesh_profiles: tuple[str, ...]
    default_mesh_profile: str
    mesh_profile_rows: Mapping[str, Mapping[str, float | int]]
    material_candidates: Mapping[str, str]
    unresolved_material_roles: tuple[str, ...]
    source_reference_lineage: Mapping[str, object]
    solver_ready: bool
    requires_project_review: bool

    @property
    def material_override_roles(self) -> tuple[str, ...]:
        """Return every public material-override input accepted for this asset."""

        return tuple(self.material_candidates) + self.unresolved_material_roles


def load_detailed_building_asset_rows(
    root: Path | None = None,
) -> dict[str, dict[str, object]]:
    """Load validated Phase 18D ``asset.json`` rows keyed by stable ID."""

    asset_root = Path(root) if root is not None else _ASSET_ROOT
    rows: dict[str, dict[str, object]] = {}
    if not asset_root.exists():
        return rows
    for path in sorted(asset_root.rglob("asset.json"), key=lambda item: str(item).lower()):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid detailed building asset JSON in '{path}'") from exc
        if not isinstance(raw, Mapping):
            raise ValueError(f"detailed building asset '{path}' must be a JSON object")
        row = validate_detailed_building_asset_resource(raw)
        resource_id = str(row["id"])
        if resource_id in rows:
            raise ValueError(
                f"duplicate detailed building asset id '{resource_id}' in "
                f"'{path}'"
            )
        rows[resource_id] = row
    return rows


def list_detailed_building_assets() -> tuple[DetailedBuildingAssetDescriptor, ...]:
    """Return all parameterized detailed-building descriptors in stable order."""

    rows = load_detailed_building_asset_rows()
    return tuple(_descriptor_from_row(rows[resource_id]) for resource_id in sorted(rows))


def get_detailed_building_asset(resource_id: str) -> DetailedBuildingAssetDescriptor:
    """Resolve one parameterized detailed-building asset by its stable ID."""

    key = str(resource_id).strip()
    if not key:
        raise ValueError("resource_id is required")
    rows = load_detailed_building_asset_rows()
    try:
        return _descriptor_from_row(rows[key])
    except KeyError as exc:
        raise ValueError(f"unknown detailed building asset {key!r}") from exc


def validate_detailed_building_asset_resource(
    resource: Mapping[str, object],
) -> dict[str, object]:
    """Validate and copy a standalone Phase 18D asset resource row."""

    if not isinstance(resource, Mapping):
        raise TypeError("detailed building asset resource must be a mapping")
    if "payload" in resource:
        raise ValueError("parametric detailed building assets must not declare a fixed payload")

    row = copy.deepcopy(dict(resource))
    unknown_fields = sorted(set(row) - _ASSET_RESOURCE_KEYS)
    if unknown_fields:
        raise ValueError(f"unknown top-level field: {unknown_fields}")
    missing_fields = sorted(_ASSET_RESOURCE_KEYS - set(row))
    if missing_fields:
        raise ValueError(f"missing required top-level field: {missing_fields}")
    if row.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {_SCHEMA_VERSION!r}")
    resource_id = _required_string(row, "id")
    _required_string(row, "version")
    _required_string(row, "legacy_asset_id")
    if row.get("source_type") != "parametric_detailed_building":
        raise ValueError("source_type must be 'parametric_detailed_building'")
    if row.get("generator") != "refined_building.asset_compiler@1":
        raise ValueError("generator must be 'refined_building.asset_compiler@1'")
    if row.get("capability") != "detailed_building":
        raise ValueError("capability must be 'detailed_building'")
    if row.get("unit_system") != "SI_m_s_kg_N_Pa":
        raise ValueError("unit_system must be 'SI_m_s_kg_N_Pa'")
    if row.get("validation_status") != "research_candidate":
        raise ValueError("validation_status must be 'research_candidate'")
    if row.get("solver_ready") is not False:
        raise ValueError("solver_ready must be false for Phase 18D assets")
    if row.get("requires_project_review") is not True:
        raise ValueError("requires_project_review must be true for Phase 18D assets")

    geometry_fields = _string_tuple(row.get("geometry_fields"), "geometry_fields")
    if not geometry_fields:
        raise ValueError("geometry_fields must not be empty")
    if len(set(geometry_fields)) != len(geometry_fields):
        raise ValueError("duplicate geometry field")
    default_geometry = row.get("default_geometry")
    if not isinstance(default_geometry, Mapping):
        raise ValueError("default_geometry must be a mapping")
    if set(default_geometry) != set(geometry_fields):
        raise ValueError("default_geometry keys must exactly match geometry fields")
    for name, value in default_geometry.items():
        _finite_positive(value, f"default_geometry.{name}")

    allowed_systems = _string_tuple(
        row.get("allowed_structural_systems"), "allowed_structural_systems"
    )
    if not allowed_systems or len(set(allowed_systems)) != len(allowed_systems):
        raise ValueError("allowed structural systems must be unique and non-empty")
    registered_systems = {system.system_id for system in list_structural_systems()}
    unknown_systems = set(allowed_systems) - registered_systems
    if unknown_systems:
        raise ValueError(
            f"unknown structural system: {', '.join(sorted(unknown_systems))}"
        )
    default_system = _required_string(row, "default_structural_system")
    if default_system not in allowed_systems:
        raise ValueError("default structural system must be in allowed structural systems")

    fidelity_profiles = _string_tuple(
        row.get("allowed_fidelity_profiles"), "allowed_fidelity_profiles"
    )
    if fidelity_profiles != _FIDELITY_PROFILES:
        raise ValueError("fidelity profiles must exactly match the Phase 18D profile set")
    default_fidelity = _required_string(row, "default_fidelity_profile")
    if default_fidelity not in fidelity_profiles:
        raise ValueError("default fidelity profile must be in allowed fidelity profiles")

    mesh_profiles = _string_tuple(row.get("allowed_mesh_profiles"), "allowed_mesh_profiles")
    if mesh_profiles != _MESH_PROFILES:
        raise ValueError("mesh profiles must exactly match the Phase 18D profile set")
    default_mesh = _required_string(row, "default_mesh_profile")
    if default_mesh not in mesh_profiles:
        raise ValueError("default mesh profile must be in allowed mesh profiles")
    _validate_mesh_profiles(row.get("mesh_profiles"))

    material_candidates = row.get("material_candidates")
    if material_candidates != _MATERIAL_CANDIDATES:
        raise ValueError("material_candidates must match the Phase 18D candidate registry")
    unresolved = _string_tuple(row.get("unresolved_material_roles"), "unresolved_material_roles")
    unknown_unresolved = sorted(
        set(unresolved) - set(_ALLOWED_UNRESOLVED_MATERIAL_ROLES)
    )
    if unknown_unresolved:
        raise ValueError(
            f"unknown unresolved material role: {unknown_unresolved}"
        )
    if (
        unresolved[: len(_UNRESOLVED_MATERIAL_ROLES)] != _UNRESOLVED_MATERIAL_ROLES
        or len(set(unresolved)) != len(unresolved)
    ):
        raise ValueError(
            "nonstructural material roles must remain unresolved and unique"
        )
    _validate_lineage(row.get("source_reference_lineage"), resource_id)
    return row


def _descriptor_from_row(row: Mapping[str, object]) -> DetailedBuildingAssetDescriptor:
    return DetailedBuildingAssetDescriptor(
        resource_id=str(row["id"]),
        version=str(row["version"]),
        legacy_asset_id=str(row["legacy_asset_id"]),
        capability=str(row["capability"]),
        default_geometry=_freeze_mapping(_mapping(row["default_geometry"], "default_geometry")),
        geometry_fields=_string_tuple(row["geometry_fields"], "geometry_fields"),
        default_structural_system=str(row["default_structural_system"]),
        allowed_structural_systems=_string_tuple(
            row["allowed_structural_systems"], "allowed_structural_systems"
        ),
        fidelity_profiles=_string_tuple(
            row["allowed_fidelity_profiles"], "allowed_fidelity_profiles"
        ),
        default_fidelity_profile=str(row["default_fidelity_profile"]),
        mesh_profiles=_string_tuple(row["allowed_mesh_profiles"], "allowed_mesh_profiles"),
        default_mesh_profile=str(row["default_mesh_profile"]),
        mesh_profile_rows=_freeze_mapping(_mapping(row["mesh_profiles"], "mesh_profiles")),
        material_candidates=_freeze_mapping(_mapping(row["material_candidates"], "material_candidates")),
        unresolved_material_roles=_string_tuple(
            row["unresolved_material_roles"], "unresolved_material_roles"
        ),
        source_reference_lineage=_freeze_mapping(
            _mapping(row["source_reference_lineage"], "source_reference_lineage")
        ),
        solver_ready=False,
        requires_project_review=True,
    )


def _validate_mesh_profiles(value: object) -> None:
    rows = _mapping(value, "mesh_profiles")
    if set(rows) != set(_MESH_PROFILES):
        raise ValueError("mesh profiles must exactly match the Phase 18D profile set")
    for profile, expected in _MESH_PROFILE_ROWS.items():
        actual = _mapping(rows.get(profile), f"mesh_profiles.{profile}")
        if set(actual) != set(_MESH_ROW_KEYS):
            raise ValueError(f"mesh_profiles.{profile} must declare the exact mesh fields")
        for key in _MESH_ROW_KEYS:
            value = actual[key]
            if key == "minimum_thickness_layers":
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise ValueError(f"mesh_profiles.{profile}.{key} must be a positive integer")
            else:
                _finite_positive(value, f"mesh_profiles.{profile}.{key}")
        if dict(actual) != expected:
            raise ValueError(f"mesh_profiles.{profile} must use the approved Phase 18D values")


def _validate_lineage(value: object, resource_id: str) -> None:
    lineage = _mapping(value, "source_reference_lineage")
    if lineage.get("resource_id") != "two_storey_rc_frame_blast_reference":
        raise ValueError("source_reference_lineage must identify the Phase 18 reference")
    if lineage.get("relation") != "reference_only" or lineage.get("scaled_input") is not False:
        raise ValueError("source_reference_lineage must be reference-only, not a scaled input")
    if lineage.get("asset_resource_id") != resource_id:
        raise ValueError("source_reference_lineage asset_resource_id must match id")


def _required_string(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{name} must be a list of non-empty strings")
    values = tuple(value)
    if not all(isinstance(item, str) and item.strip() for item in values):
        raise ValueError(f"{name} must be a list of non-empty strings")
    return values  # type: ignore[return-value]


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be a mapping with string keys")
    return value


def _finite_positive(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite positive number")
    if not math.isfinite(float(value)) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    frozen: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            frozen[key] = _freeze_mapping(item)
        elif isinstance(item, list):
            frozen[key] = tuple(item)
        else:
            frozen[key] = item
    return MappingProxyType(frozen)
