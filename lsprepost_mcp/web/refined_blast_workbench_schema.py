"""Authoritative field map for the refined-blast eight-step workbench.

The browser consumes this module's JSON-safe output and must not invent
engineering fields, applicability rules, units, or provider ranges.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from lsprepost_mcp.refined_blast.provider_registry import (
    get_load_provider,
    list_load_providers,
)
from lsprepost_mcp.refined_building.asset_compiler import generation_options_ui_schema
from lsprepost_mcp.refined_building.asset_resources import list_detailed_building_assets


_SCHEMA_VERSION = "refined_blast.workbench_schema@1"
_SECTIONS = (
    ("building_space", "建筑空间与洞口"),
    ("structural_system", "结构体系与承重构件"),
    ("connections", "钢筋、钢构或组合连接"),
    ("nonstructural", "非承重构件"),
    ("materials", "材料、截面和失效模型"),
    ("mesh_ground", "网格、地面与局部加密"),
    ("blast_load", "载荷、爆源、空气域、边界与输出"),
    ("validation", "检查、预算、确认与生成"),
)
_SECTION_ORDER = {
    section_id: index for index, (section_id, _) in enumerate(_SECTIONS, 1)
}
_LABELS_ZH = {
    "asset_id": "建筑工况",
    "origin_m": "建筑原点",
    "rotation_deg": "建筑旋转角",
    "structural_system": "结构体系",
    "fidelity_profile": "建模精细度",
    "mesh_profile": "建筑网格方案",
    "reinforcement_mode": "钢筋建模模式",
    "include_reinforcement_roles": "钢筋构件类别",
    "cover_m": "混凝土保护层厚度",
    "bar_diameter_m": "钢筋直径",
    "rebar_spacing_m": "钢筋间距",
    "connection_simplification_level": "连接简化等级",
    "glazing_bay_count": "玻璃分格数量",
    "scenario_kind": "爆炸工况类型",
    "provider_id": "载荷与传播方法",
    "tnt_equivalent_mass_kg": "TNT 当量",
    "charge_position_m": "爆源位置",
    "detonation_time_s": "起爆时间",
    "air_cell_size_m": "空气单元尺寸",
    "ground_cell_size_m": "地面单元尺寸",
    "air_margin_m": "空气域外扩距离",
    "air_margins_m": "空气域五向余量（X-/X+/Y-/Y+/顶部）",
    "coupling_buffer_layers": "地坪下耦合缓冲层数",
    "material_profile": "空气、TNT 与土体材料档案",
    "termination_time_s": "求解终止时间",
    "target_cell_size_m": "空气域目标单元尺寸",
    "near_field_cell_size_m": "爆源近场单元尺寸",
}


class _Missing:
    pass


_MISSING = _Missing()


def build_refined_blast_workbench_schema() -> dict[str, object]:
    """Build the closed eight-step UI contract from compiler/provider schemas."""

    assets = list_detailed_building_assets()
    providers = list_load_providers()
    fields: dict[str, dict[str, object]] = {}

    asset_ids = [asset.resource_id for asset in assets]
    _add_field(
        fields,
        path="building.asset_id",
        section_id="building_space",
        label_zh=_LABELS_ZH["asset_id"],
        schema={"type": "string", "enum": asset_ids},
        default_by_asset={asset.resource_id: asset.resource_id for asset in assets},
    )

    geometry: dict[str, dict[str, object]] = {}
    for asset in assets:
        for name in asset.geometry_fields:
            entry = geometry.setdefault(
                name, {"asset_ids": [], "defaults": {}, "samples": []}
            )
            entry["asset_ids"].append(asset.resource_id)
            value = asset.default_geometry[name]
            entry["defaults"][asset.resource_id] = _json_value(value)
            entry["samples"].append(value)
    for name, entry in sorted(geometry.items()):
        _add_field(
            fields,
            path=f"building.legacy_geometry.{name}",
            section_id="building_space",
            label_zh=_field_label(name),
            unit=_field_unit(name),
            schema=_scalar_schema(entry["samples"][0]),
            default_by_asset=entry["defaults"],
            applicability={"asset_ids": sorted(entry["asset_ids"])},
        )

    _add_field(
        fields,
        path="building.origin_m",
        section_id="building_space",
        label_zh=_LABELS_ZH["origin_m"],
        unit="m",
        schema=_vector_schema(),
        default=[0.0, 0.0, 0.0],
    )
    _add_field(
        fields,
        path="building.rotation_deg",
        section_id="building_space",
        label_zh=_LABELS_ZH["rotation_deg"],
        unit="deg",
        schema=_vector_schema(),
        default=[0.0, 0.0, 0.0],
    )

    structural_systems = sorted(
        {system for asset in assets for system in asset.allowed_structural_systems}
    )
    _add_field(
        fields,
        path="building.structural_system",
        section_id="structural_system",
        label_zh=_LABELS_ZH["structural_system"],
        schema={"type": "string", "enum": structural_systems},
        default_by_asset={
            asset.resource_id: asset.default_structural_system for asset in assets
        },
        enum_by_asset={
            asset.resource_id: list(asset.allowed_structural_systems)
            for asset in assets
        },
    )
    fidelity_profiles = sorted(
        {value for asset in assets for value in asset.fidelity_profiles}
    )
    _add_field(
        fields,
        path="building.fidelity_profile",
        section_id="structural_system",
        label_zh=_LABELS_ZH["fidelity_profile"],
        schema={"type": "string", "enum": fidelity_profiles},
        default_by_asset={
            asset.resource_id: asset.default_fidelity_profile for asset in assets
        },
        enum_by_asset={
            asset.resource_id: list(asset.fidelity_profiles) for asset in assets
        },
    )

    _add_generation_fields(fields, assets)
    _add_material_fields(fields, assets)

    mesh_profiles = sorted(
        {value for asset in assets for value in asset.mesh_profiles}
    )
    _add_field(
        fields,
        path="building.mesh_profile",
        section_id="mesh_ground",
        label_zh=_LABELS_ZH["mesh_profile"],
        schema={"type": "string", "enum": mesh_profiles},
        default_by_asset={
            asset.resource_id: asset.default_mesh_profile for asset in assets
        },
        enum_by_asset={
            asset.resource_id: list(asset.mesh_profiles) for asset in assets
        },
        profile_rows_by_asset={
            asset.resource_id: _json_value(asset.mesh_profile_rows)
            for asset in assets
        },
    )

    _add_field(
        fields,
        path="draft.scenario_kind",
        section_id="blast_load",
        label_zh=_LABELS_ZH["scenario_kind"],
        schema={
            "type": "string",
            "enum": ["external", "internal", "semi_enclosed"],
        },
        default="external",
    )
    provider_ids = [descriptor.provider_id for descriptor in providers]
    _add_field(
        fields,
        path="draft.load_provider.provider_id",
        section_id="blast_load",
        label_zh=_LABELS_ZH["provider_id"],
        schema={"type": "string", "enum": provider_ids},
        default=provider_ids[0] if provider_ids else None,
    )
    _add_provider_fields(fields, providers)

    ordered_fields = sorted(
        fields.values(),
        key=lambda row: (
            _SECTION_ORDER[str(row["section_id"])],
            str(row["path"]),
        ),
    )
    for order, field in enumerate(ordered_fields, 1):
        field["order"] = order
    return {
        "schema_version": _SCHEMA_VERSION,
        "sections": [
            {"section_id": section_id, "step": step, "label_zh": label}
            for step, (section_id, label) in enumerate(_SECTIONS, 1)
        ],
        "fields": ordered_fields,
    }


def _add_generation_fields(fields: dict[str, dict[str, object]], assets: Sequence[object]) -> None:
    generation_fields: dict[str, dict[str, Any]] = {}
    for asset in assets:
        for system_id in asset.allowed_structural_systems:
            option_schema = generation_options_ui_schema(asset.resource_id, system_id)
            for name, property_schema in option_schema["properties"].items():
                entry = generation_fields.setdefault(
                    name,
                    {"asset_ids": set(), "systems": set(), "schemas": []},
                )
                entry["asset_ids"].add(asset.resource_id)
                entry["systems"].add(system_id)
                entry["schemas"].append(_json_value(property_schema))
    for name, entry in sorted(generation_fields.items()):
        _add_field(
            fields,
            path=f"building.generation_options.{name}",
            section_id=_generation_section(name),
            label_zh=_field_label(name),
            unit=_field_unit(name),
            schema=_merge_schemas(entry["schemas"]),
            applicability={
                "asset_ids": sorted(entry["asset_ids"]),
                "structural_systems": sorted(entry["systems"]),
            },
        )


def _add_material_fields(fields: dict[str, dict[str, object]], assets: Sequence[object]) -> None:
    material_roles: dict[str, set[str]] = {}
    material_defaults: dict[str, dict[str, object]] = {}
    for asset in assets:
        for role in asset.material_override_roles:
            material_roles.setdefault(role, set()).add(asset.resource_id)
            if role in asset.material_candidates:
                material_defaults.setdefault(role, {})[
                    asset.resource_id
                ] = asset.material_candidates[role]
    for role, applicable_assets in sorted(material_roles.items()):
        _add_field(
            fields,
            path=f"building.material_overrides.{role}",
            section_id="materials",
            label_zh=_field_label(role),
            schema={"type": "string", "minLength": 1},
            default_by_asset=material_defaults.get(role, {}),
            applicability={"asset_ids": sorted(applicable_assets)},
        )


def _add_provider_fields(fields: dict[str, dict[str, object]], providers: Sequence[object]) -> None:
    provider_fields: dict[str, dict[str, Any]] = {}
    for descriptor in providers:
        provider = get_load_provider(descriptor.provider_id)
        input_schema = _json_value(provider.schema()["input_schema"])
        defaults = _json_value(provider.default_input())
        for relative_path, property_schema, default_value in _flatten_schema(
            input_schema, defaults
        ):
            leaf = relative_path.rsplit(".", 1)[-1]
            if leaf in {"schema_version", "unit_system"}:
                continue
            entry = provider_fields.setdefault(
                relative_path,
                {"provider_ids": [], "schemas": {}, "defaults": {}},
            )
            entry["provider_ids"].append(descriptor.provider_id)
            entry["schemas"][descriptor.provider_id] = property_schema
            if default_value is not _MISSING:
                entry["defaults"][descriptor.provider_id] = default_value
    for relative_path, entry in sorted(provider_fields.items()):
        leaf = relative_path.rsplit(".", 1)[-1]
        provider_id = sorted(entry["schemas"])[0]
        _add_field(
            fields,
            path=f"draft.load_provider.provider_input.{relative_path}",
            section_id=_provider_section(relative_path),
            label_zh=_field_label(leaf),
            unit=_field_unit(leaf),
            schema=entry["schemas"][provider_id],
            schema_by_provider=entry["schemas"],
            default_by_provider=entry["defaults"],
            applicability={"provider_ids": sorted(entry["provider_ids"])},
        )


def _add_field(
    fields: dict[str, dict[str, object]],
    *,
    path: str,
    section_id: str,
    label_zh: str,
    schema: Mapping[str, object],
    unit: str | None = None,
    default: object = _MISSING,
    **metadata: object,
) -> None:
    if path in fields:
        raise ValueError(f"duplicate refined-blast workbench field path: {path}")
    row: dict[str, object] = {
        "path": path,
        "section_id": section_id,
        "label_zh": label_zh,
        "schema": _json_value(schema),
        "editable": True,
    }
    if unit is not None:
        row["unit"] = unit
    if default is not _MISSING:
        row["default"] = _json_value(default)
    for key, value in metadata.items():
        if value not in ({}, [], (), None):
            row[key] = _json_value(value)
    fields[path] = row


def _flatten_schema(
    schema: Mapping[str, object], defaults: object, prefix: str = ""
):
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return
    default_mapping = defaults if isinstance(defaults, Mapping) else {}
    for name, child in sorted(properties.items()):
        if not isinstance(child, Mapping):
            continue
        path = f"{prefix}.{name}" if prefix else str(name)
        child_default = default_mapping.get(name, _MISSING)
        child_properties = child.get("properties")
        if isinstance(child_properties, Mapping):
            yield from _flatten_schema(child, child_default, path)
        else:
            if child_default is _MISSING:
                yield path, _json_value(child), _MISSING
            else:
                yield path, _json_value(child), _json_value(child_default)


def _generation_section(name: str) -> str:
    if name.startswith("max_"):
        return "validation"
    if name == "storey_count":
        return "structural_system"
    if name in {
        "reinforcement_mode",
        "include_reinforcement_roles",
        "cover_m",
        "bar_diameter_m",
        "rebar_spacing_m",
        "connection_simplification_level",
    }:
        return "connections"
    return "nonstructural"


def _provider_section(path: str) -> str:
    lowered = path.lower()
    leaf = lowered.rsplit(".", 1)[-1]
    if "budget" in lowered or leaf.startswith("max_"):
        return "validation"
    if "resource" in lowered:
        return "materials"
    if leaf == "material_profile":
        return "materials"
    if leaf == "coupling_buffer_layers":
        return "mesh_ground"
    if any(token in leaf for token in ("cell_size", "mesh_size", "refinement")):
        return "mesh_ground"
    return "blast_load"


def _field_label(name: str) -> str:
    return _LABELS_ZH.get(name, name.replace("_", " "))


def _field_unit(name: str) -> str | None:
    if name.endswith("_m") or name.endswith("_bounds_m"):
        return "m"
    if name.endswith("_kg"):
        return "kg"
    if name.endswith("_s"):
        return "s"
    if name.endswith("_pa"):
        return "Pa"
    if name.endswith("_deg"):
        return "deg"
    return None


def _scalar_schema(value: object) -> dict[str, object]:
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    return {"type": "string"}


def _vector_schema() -> dict[str, object]:
    return {
        "type": "array",
        "items": {"type": "number"},
        "minItems": 3,
        "maxItems": 3,
    }


def _merge_schemas(schemas: Sequence[Mapping[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    enum_values: set[object] = set()
    for schema in schemas:
        for key, value in schema.items():
            if key == "enum" and isinstance(value, Sequence) and not isinstance(value, str):
                enum_values.update(value)
            elif key not in result:
                result[key] = _json_value(value)
    if enum_values:
        result["enum"] = sorted(enum_values, key=str)
    return result


def _json_value(value: object) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_json_value(item) for item in value]
    return copy.deepcopy(value)
