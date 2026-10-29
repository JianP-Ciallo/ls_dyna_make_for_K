from __future__ import annotations

from pathlib import Path

from lsprepost_mcp.web.refined_blast_api import RefinedBlastApi


EXPECTED_SECTIONS = [
    "building_space",
    "structural_system",
    "connections",
    "nonstructural",
    "materials",
    "mesh_ground",
    "blast_load",
    "validation",
]


def _schema(tmp_path: Path) -> dict[str, object]:
    api = RefinedBlastApi(tmp_path)
    try:
        return api.get("/capabilities", {})["workbench_schema"]
    finally:
        api._store.close()


def test_capabilities_publish_eight_ordered_workbench_sections(tmp_path: Path) -> None:
    """Removing or renaming a workflow section must break the public UI contract."""
    schema = _schema(tmp_path)

    assert schema["schema_version"] == "refined_blast.workbench_schema@1"
    assert [row["section_id"] for row in schema["sections"]] == EXPECTED_SECTIONS
    assert [row["step"] for row in schema["sections"]] == list(range(1, 9))
    assert [row["label_zh"] for row in schema["sections"]] == [
        "建筑空间与洞口",
        "结构体系与承重构件",
        "钢筋、钢构或组合连接",
        "非承重构件",
        "材料、截面和失效模型",
        "网格、地面与局部加密",
        "载荷、爆源、空气域、边界与输出",
        "检查、预算、确认与生成",
    ]


def test_workbench_fields_have_unique_paths_and_real_middle_step_controls(
    tmp_path: Path,
) -> None:
    """A generator input must not be absent from, or duplicated across, the eight steps."""
    schema = _schema(tmp_path)
    fields = schema["fields"]
    paths = [row["path"] for row in fields]
    by_path = {row["path"]: row for row in fields}

    assert len(paths) == len(set(paths))
    assert all(path.startswith(("building.", "draft.")) for path in paths)
    assert by_path["building.asset_id"]["section_id"] == "building_space"
    assert by_path["building.structural_system"]["section_id"] == "structural_system"
    assert (
        by_path["building.generation_options.reinforcement_mode"]["section_id"]
        == "connections"
    )
    assert (
        by_path["building.generation_options.glazing_bay_count"]["section_id"]
        == "nonstructural"
    )
    assert by_path["building.material_overrides.concrete"]["section_id"] == "materials"
    assert by_path["building.mesh_profile"]["section_id"] == "mesh_ground"
    assert (
        by_path["draft.load_provider.provider_input.air_cell_size_m"]["section_id"]
        == "mesh_ground"
    )
    assert (
        by_path["draft.load_provider.provider_input.ground_cell_size_m"]["section_id"]
        == "mesh_ground"
    )
    assert (
        by_path["draft.load_provider.provider_input.tnt_equivalent_mass_kg"]["section_id"]
        == "blast_load"
    )
    assert (
        by_path["draft.load_provider.provider_input.charge_position_m"]["section_id"]
        == "blast_load"
    )

    populated = {
        row["section_id"]
        for row in fields
        if row.get("editable") is True
    }
    assert set(EXPECTED_SECTIONS[:-1]) <= populated


def test_workbench_field_metadata_exposes_units_ranges_and_applicability(
    tmp_path: Path,
) -> None:
    """The browser must not invent engineering ranges or field applicability."""
    fields = {row["path"]: row for row in _schema(tmp_path)["fields"]}

    air = fields["draft.load_provider.provider_input.air_cell_size_m"]
    assert air["label_zh"] == "空气单元尺寸"
    assert air["unit"] == "m"
    assert air["schema"]["minimum"] == 0.15
    assert air["schema"]["maximum"] == 0.5
    assert air["applicability"] == {"provider_ids": ["solver_complete_ale_fsi"]}

    ground = fields["draft.load_provider.provider_input.ground_cell_size_m"]
    assert ground["schema"]["minimum"] == 0.1
    assert ground["schema"]["maximum"] == 0.5

    reinforcement = fields["building.generation_options.reinforcement_mode"]
    assert reinforcement["applicability"]["structural_systems"] == [
        "rc_box",
        "rc_frame",
        "rc_frame_shear_wall",
        "steel_concrete_hybrid",
    ]


def test_workbench_maps_every_editable_config4_control_once_to_the_eight_steps(
    tmp_path: Path,
) -> None:
    schema = _schema(tmp_path)
    rows = [
        row
        for row in schema["fields"]
        if row["path"].startswith(
            "draft.load_provider.provider_input."
        )
        and row.get("applicability") == {"provider_ids": ["solver_complete_ale_fsi"]}
    ]
    by_leaf = {row["path"].rsplit(".", 1)[-1]: row for row in rows}

    assert set(by_leaf) == {
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
    assert by_leaf["near_field_cell_size_m"]["section_id"] == "mesh_ground"
    assert by_leaf["coupling_buffer_layers"]["section_id"] == "mesh_ground"
    assert by_leaf["coupling_buffer_layers"]["schema"]["minimum"] == 1
    assert by_leaf["coupling_buffer_layers"]["schema"]["maximum"] == 5
    assert by_leaf["material_profile"]["section_id"] == "materials"
    assert by_leaf["air_margins_m"]["section_id"] == "blast_load"
    assert by_leaf["air_margins_m"]["schema"]["minItems"] == 5
    assert by_leaf["air_margins_m"]["schema"]["maxItems"] == 5
    assert by_leaf["termination_time_s"]["default_by_provider"] == {
        "solver_complete_ale_fsi": 5.0e-5
    }
