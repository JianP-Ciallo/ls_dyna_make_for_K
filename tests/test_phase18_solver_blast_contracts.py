from __future__ import annotations

import math

import pytest

from lsprepost_mcp.refined_building.solver_blast import (
    PhysicalMemberRecord,
    audit_physical_members,
    normalize_solver_blast_config,
)


def _config(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "phase18.solver_blast.config@1",
        "unit_system": "SI_m_s_kg_N_Pa",
        "tnt_equivalent_mass_kg": 2.0,
        "charge_position_m": [-2.0, 0.0, 1.5],
        "detonation_time_s": 0.0,
        "air_cell_size_m": 0.4,
        "air_margin_m": [3.0, 3.0, 3.0],
        "termination_time_s": 0.001,
    }
    value.update(overrides)
    return value


def _config_v3(**overrides: object) -> dict[str, object]:
    value = _config(
        schema_version="phase18.solver_blast.config@3",
        ground_cell_size_m=0.25,
    )
    value.update(overrides)
    return value


def _config_v4(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "phase18.solver_blast.config@4",
        "unit_system": "SI_m_s_kg_N_Pa",
        "tnt_equivalent_mass_kg": 2.0,
        "charge_position_m": [-2.0, 0.0, 1.5],
        "detonation_time_s": 0.0,
        "air_cell_size_m": 0.25,
        "near_field_cell_size_m": 0.15,
        "ground_cell_size_m": 0.25,
        "air_margins_m": [3.0, 3.0, 3.0, 3.0, 3.0],
        "coupling_buffer_layers": 2,
        "material_profile": "verification_reference",
        "termination_time_s": 0.001,
    }
    value.update(overrides)
    return value


def test_config_normalizes_default_2kg_movable_charge() -> None:
    config = normalize_solver_blast_config(_config())
    assert config.schema_version == "phase18.solver_blast.config@4"
    assert config.unit_system == "SI_m_s_kg_N_Pa"
    assert config.tnt_equivalent_mass_kg == 2.0
    assert config.charge_position_m == (-2.0, 0.0, 1.5)
    assert config.ground_cell_size_m == pytest.approx(0.25)
    assert config.air_margins_m == (3.0, 3.0, 3.0, 3.0, 3.0)
    assert config.near_field_cell_size_m == pytest.approx(0.15)
    assert config.coupling_buffer_layers == 2
    assert config.material_profile == "verification_reference"
    assert config.termination_time_s == 0.001


def test_config_accepts_closed_v2_ground_mesh_size() -> None:
    value = _config()
    value["schema_version"] = "phase18.solver_blast.config@2"
    value["ground_cell_size_m"] = 0.2

    config = normalize_solver_blast_config(value)

    assert config.schema_version == "phase18.solver_blast.config@4"
    assert config.ground_cell_size_m == pytest.approx(0.2)


def test_config_accepts_closed_v3_physical_mesh_ranges() -> None:
    value = _config()
    value["schema_version"] = "phase18.solver_blast.config@3"
    value["ground_cell_size_m"] = 0.2
    value["air_cell_size_m"] = 0.25

    config = normalize_solver_blast_config(value)

    assert config.schema_version == "phase18.solver_blast.config@4"
    assert config.air_cell_size_m == pytest.approx(0.25)
    assert config.air_margins_m == (3.0, 3.0, 3.0, 3.0, 3.0)


def test_config_v4_accepts_asymmetric_air_margins() -> None:
    config = normalize_solver_blast_config(
        _config_v4(air_margins_m=[2.0, 4.0, 3.0, 5.0, 6.0])
    )

    assert config.air_margins_m == (2.0, 4.0, 3.0, 5.0, 6.0)


@pytest.mark.parametrize(
    "margins", ([0.0, 3.0, 3.0, 3.0, 3.0], [-1.0, 3.0, 3.0, 3.0, 3.0])
)
def test_config_v4_rejects_nonpositive_air_margins(margins: list[float]) -> None:
    with pytest.raises(ValueError, match="air_margins_m"):
        normalize_solver_blast_config(_config_v4(air_margins_m=margins))


@pytest.mark.parametrize("profile", ["unknown", 7, True])
def test_config_v4_rejects_unknown_material_profile(profile: object) -> None:
    with pytest.raises(ValueError, match="material_profile"):
        normalize_solver_blast_config(_config_v4(material_profile=profile))


def test_config_v4_rejects_unknown_keys() -> None:
    value = _config_v4()
    value["unexpected"] = 1

    with pytest.raises(ValueError, match="unexpected keys"):
        normalize_solver_blast_config(value)


def test_config_v3_rejects_v4_only_keys() -> None:
    value = _config_v3()
    value["near_field_cell_size_m"] = 0.15

    with pytest.raises(ValueError, match="unexpected keys"):
        normalize_solver_blast_config(value)


@pytest.mark.parametrize("layers", [0, 6, 1.5, True])
def test_config_v4_rejects_invalid_coupling_buffer_layers(layers: object) -> None:
    with pytest.raises(ValueError, match="coupling_buffer_layers"):
        normalize_solver_blast_config(_config_v4(coupling_buffer_layers=layers))


@pytest.mark.parametrize("size", [0.049, 0.251, math.nan, True])
def test_config_v4_rejects_invalid_near_field_size(size: object) -> None:
    with pytest.raises(ValueError, match="near_field_cell_size_m"):
        normalize_solver_blast_config(_config_v4(near_field_cell_size_m=size))


@pytest.mark.parametrize("size", [0.149, 0.501, math.nan, True])
def test_config_rejects_air_mesh_size_outside_closed_range(size: object) -> None:
    value = _config()
    value["schema_version"] = "phase18.solver_blast.config@3"
    value["ground_cell_size_m"] = 0.25
    value["air_cell_size_m"] = size

    with pytest.raises(ValueError, match="air_cell_size_m"):
        normalize_solver_blast_config(value)


@pytest.mark.parametrize("size", [0.099, 0.501, math.nan, True])
def test_config_rejects_ground_mesh_size_outside_closed_range(size: object) -> None:
    value = _config()
    value["schema_version"] = "phase18.solver_blast.config@2"
    value["ground_cell_size_m"] = size

    with pytest.raises(ValueError, match="ground_cell_size_m"):
        normalize_solver_blast_config(value)


@pytest.mark.parametrize("mass", [0.099, 100.001, math.nan, True])
def test_config_rejects_charge_outside_closed_range(mass: object) -> None:
    with pytest.raises(ValueError, match="tnt_equivalent_mass_kg"):
        normalize_solver_blast_config(_config(tnt_equivalent_mass_kg=mass))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"charge_position_m": [0.0, 1.0]}, "charge_position_m"),
        ({"air_cell_size_m": 0.0}, "air_cell_size_m"),
        ({"air_margin_m": [3.0, -1.0, 3.0]}, "air_margin_m"),
        ({"termination_time_s": 0.0}, "termination_time_s"),
        ({"detonation_time_s": -0.1}, "detonation_time_s"),
        (
            {"detonation_time_s": 0.001, "termination_time_s": 0.001},
            "detonation_time_s",
        ),
        ({"unit_system": "mm-ms-kg"}, "unit_system"),
    ],
)
def test_config_rejects_invalid_closed_values(
    mutation: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_solver_blast_config(_config(**mutation))


def test_config_rejects_unknown_keys() -> None:
    value = _config()
    value["charge_radius_m"] = 0.25
    with pytest.raises(ValueError, match="unexpected keys"):
        normalize_solver_blast_config(value)


def test_physical_members_accept_reviewed_solid_shell_and_beam_mix() -> None:
    members = (
        PhysicalMemberRecord(
            role="rc_column",
            element_family="Solid",
            material_role="concrete",
            dimensions_m=(0.5, 0.5, 3.0),
            selection_basis="three-dimensional load-bearing column",
            connection_ids=("column_to_foundation", "column_to_beam"),
            fluid_exposed=True,
        ),
        PhysicalMemberRecord(
            role="roof_sheet",
            element_family="Shell",
            material_role="steel",
            dimensions_m=(6.0, 3.0, 0.02),
            selection_basis="thin roof sheet with physical thickness",
            connection_ids=("roof_to_frame",),
            fluid_exposed=True,
        ),
        PhysicalMemberRecord(
            role="steel_beam",
            element_family="Beam",
            material_role="steel",
            dimensions_m=(6.0, 0.3, 0.2),
            selection_basis="slender steel member with reviewed section",
            connection_ids=("beam_to_columns",),
            fluid_exposed=False,
            orientation_vector=(0.0, 0.0, 1.0),
        ),
    )
    assert audit_physical_members(members) == ()


def test_physical_audit_rejects_opaque_facade_shell() -> None:
    member = PhysicalMemberRecord(
        role="opaque_facade",
        element_family="Shell",
        material_role="masonry",
        dimensions_m=(6.0, 3.0, 0.2),
        selection_basis="visual facade",
        connection_ids=("facade_to_frame",),
        fluid_exposed=True,
    )
    findings = audit_physical_members((member,))
    assert [finding.finding_id for finding in findings] == [
        "opaque_envelope_requires_solid"
    ]


def test_physical_audit_rejects_beam_without_slenderness_or_orientation() -> None:
    member = PhysicalMemberRecord(
        role="steel_column",
        element_family="Beam",
        material_role="steel",
        dimensions_m=(1.0, 0.4, 0.4),
        selection_basis="beam shortcut",
        connection_ids=("column_to_foundation",),
        fluid_exposed=True,
    )
    finding_ids = {row.finding_id for row in audit_physical_members((member,))}
    assert finding_ids == {"beam_requires_orientation", "beam_not_slender"}


def test_physical_member_requires_explicit_connection() -> None:
    with pytest.raises(ValueError, match="connection_ids"):
        PhysicalMemberRecord(
            role="glazing",
            element_family="Shell",
            material_role="glass",
            dimensions_m=(2.0, 1.0, 0.01),
            selection_basis="thin glass pane",
            connection_ids=(),
            fluid_exposed=True,
        )
