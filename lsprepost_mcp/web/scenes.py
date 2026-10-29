from __future__ import annotations

from lsprepost_mcp.config import JSONDict
from lsprepost_mcp.scene_prompts import (
    CUBE_LOAD_DEFAULTS,
    PLATE_PRESSURE_DEFAULTS,
    REBAR_HELMET_DEFAULTS,
    ROD_PLATE_DEFAULTS,
)


MATERIAL_OPTIONS = ("mild_steel", "aluminum_6061_t6", "rubber_generic")


def number_field(name: str, label: str, unit: str, default: float) -> JSONDict:
    return {"name": name, "label": label, "kind": "number", "unit": unit, "default": default}


def material_field(default: str = "mild_steel") -> JSONDict:
    return {
        "name": "material_name",
        "label": "Material",
        "kind": "select",
        "default": default,
        "options": list(MATERIAL_OPTIONS),
    }


def web_scene_catalog() -> JSONDict:
    return {
        "scenes": [
            {
                "id": "rebar_drop_on_helmet",
                "title": "Rebar impact on helmet",
                "summary": "A vertical solid rebar starts 0.5 m above a fixed ellipsoid helmet shell and impacts with an initial velocity.",
                "fields": [
                    number_field("rebar_length_m", "Rebar length", "m", REBAR_HELMET_DEFAULTS["rebar_length_m"]),
                    number_field("rebar_radius_m", "Rebar radius", "m", REBAR_HELMET_DEFAULTS["rebar_radius_m"]),
                    number_field("drop_height_m", "Drop height", "m", REBAR_HELMET_DEFAULTS["drop_height_m"]),
                    number_field(
                        "impact_velocity_m_per_s",
                        "Impact velocity",
                        "m/s",
                        REBAR_HELMET_DEFAULTS["impact_velocity_m_per_s"],
                    ),
                    material_field(REBAR_HELMET_DEFAULTS["material_name"]),
                ],
            },
            {
                "id": "rod_impact_plate",
                "title": "Rod impact on plate",
                "summary": "A solid cylinder rod impacts a fixed steel plate.",
                "fields": [
                    number_field("rod_length_m", "Rod length", "m", ROD_PLATE_DEFAULTS["rod_length_m"]),
                    number_field("rod_radius_m", "Rod radius", "m", ROD_PLATE_DEFAULTS["rod_radius_m"]),
                    number_field(
                        "impact_velocity_m_per_s",
                        "Impact velocity",
                        "m/s",
                        ROD_PLATE_DEFAULTS["impact_velocity_m_per_s"],
                    ),
                    number_field("plate_length_m", "Plate length", "m", ROD_PLATE_DEFAULTS["plate_length_m"]),
                    number_field("plate_width_m", "Plate width", "m", ROD_PLATE_DEFAULTS["plate_width_m"]),
                    number_field(
                        "plate_thickness_m",
                        "Plate thickness",
                        "m",
                        ROD_PLATE_DEFAULTS["plate_thickness_m"],
                    ),
                    material_field(ROD_PLATE_DEFAULTS["material_name"]),
                ],
            },
            {
                "id": "cube_top_corner_load",
                "title": "Cube with top corner loads",
                "summary": "A fixed cube receives downward nodal loads at four top corners.",
                "fields": [
                    number_field("cube_length_m", "Cube length", "m", CUBE_LOAD_DEFAULTS["cube_length_m"]),
                    number_field("cube_width_m", "Cube width", "m", CUBE_LOAD_DEFAULTS["cube_width_m"]),
                    number_field("cube_height_m", "Cube height", "m", CUBE_LOAD_DEFAULTS["cube_height_m"]),
                    number_field("corner_force_n", "Corner force", "N", CUBE_LOAD_DEFAULTS["corner_force_n"]),
                    material_field(CUBE_LOAD_DEFAULTS["material_name"]),
                ],
            },
            {
                "id": "plate_pressure",
                "title": "Plate under pressure",
                "summary": "A shell plate with fixed boundary receives uniform pressure.",
                "fields": [
                    number_field("plate_length_m", "Plate length", "m", PLATE_PRESSURE_DEFAULTS["plate_length_m"]),
                    number_field("plate_width_m", "Plate width", "m", PLATE_PRESSURE_DEFAULTS["plate_width_m"]),
                    number_field(
                        "plate_thickness_m",
                        "Plate thickness",
                        "m",
                        PLATE_PRESSURE_DEFAULTS["plate_thickness_m"],
                    ),
                    number_field("pressure_pa", "Pressure", "Pa", PLATE_PRESSURE_DEFAULTS["pressure_pa"]),
                    material_field(PLATE_PRESSURE_DEFAULTS["material_name"]),
                ],
            },
        ]
    }
