from __future__ import annotations

import re
from copy import deepcopy

from .config import JSONDict
from .schema import (
    cube_top_corner_load_spec,
    plate_pressure_spec,
    rebar_drop_on_helmet_spec,
    rod_impact_plate_spec,
)


SCENE_TEMPLATE_REGISTRY = {
    "cube_top_corner_load": cube_top_corner_load_spec,
    "plate_pressure": plate_pressure_spec,
    "rebar_drop_on_helmet": rebar_drop_on_helmet_spec,
    "rod_impact_plate": rod_impact_plate_spec,
}
SUPPORTED_SCENE_TEMPLATES = sorted(SCENE_TEMPLATE_REGISTRY)
REBAR_HELMET_DEFAULTS = {
    "rebar_length_m": 1.0,
    "rebar_radius_m": 0.012,
    "drop_height_m": 0.5,
    "impact_velocity_m_per_s": 10.0,
    "material_name": "mild_steel",
}
REBAR_HELMET_REQUIRED = ["rebar_length_m", "rebar_radius_m", "drop_height_m", "impact_velocity_m_per_s", "material_name"]
ROD_PLATE_DEFAULTS = {
    "rod_length_m": 0.5,
    "rod_radius_m": 0.02,
    "impact_velocity_m_per_s": 10.0,
    "plate_length_m": 0.8,
    "plate_width_m": 0.6,
    "plate_thickness_m": 0.004,
    "material_name": "mild_steel",
}
ROD_PLATE_REQUIRED = [
    "rod_length_m",
    "rod_radius_m",
    "impact_velocity_m_per_s",
    "plate_length_m",
    "plate_width_m",
    "plate_thickness_m",
    "material_name",
]
CUBE_LOAD_DEFAULTS = {
    "cube_length_m": 2.0,
    "cube_width_m": 2.0,
    "cube_height_m": 2.0,
    "corner_force_n": 1000.0,
    "material_name": "mild_steel",
}
CUBE_LOAD_REQUIRED = ["cube_length_m", "cube_width_m", "cube_height_m", "corner_force_n", "material_name"]
PLATE_PRESSURE_DEFAULTS = {
    "plate_length_m": 1.0,
    "plate_width_m": 0.5,
    "plate_thickness_m": 0.003,
    "pressure_pa": 20000.0,
    "material_name": "mild_steel",
}
PLATE_PRESSURE_REQUIRED = ["plate_length_m", "plate_width_m", "plate_thickness_m", "pressure_pa", "material_name"]

TOKEN_REBAR = ["\u94a2\u7b4b", "\u6746", "\u5706\u67f1", "rebar", "rod"]
TOKEN_HELMET = ["\u5934\u76d4", "\u94a2\u76d4", "helmet"]
TOKEN_PLATE = ["\u94a2\u677f", "\u677f", "plate"]
TOKEN_CUBE = ["\u7acb\u65b9\u4f53", "\u65b9\u5757", "cube", "block"]
TOKEN_PRESSURE = ["\u538b\u529b", "\u5747\u5e03\u538b\u529b", "pressure"]
TOKEN_CORNER_LOAD = ["\u56db\u4e2a\u89d2", "\u56db\u89d2", "\u9876\u9762", "\u8f7d\u8377", "corner", "load"]
TOKEN_DROP_IMPACT = [
    "\u81ea\u7531\u843d\u4f53",
    "\u4e0b\u843d",
    "\u843d\u4e0b",
    "\u9ad8\u5904",
    "\u4e0a\u65b9",
    "\u51b2\u51fb",
    "\u649e",
    "impact",
    "drop",
]
TOKEN_LENGTH = ["\u957f\u5ea6", "\u957f"]
TOKEN_RADIUS = ["\u534a\u5f84", "radius"]
TOKEN_DIAMETER = ["\u76f4\u5f84", "diameter"]
TOKEN_DROP_HEIGHT = ["\u4e0a\u65b9", "\u9ad8\u5904", "\u9ad8\u5ea6", "\u4e0b\u843d", "\u81ea\u7531\u843d\u4f53", "drop"]
TOKEN_MILD_STEEL = ["\u4f4e\u78b3\u94a2", "\u94a2\u7b4b", "\u94a2\u76d4", "\u94a2", "mild steel"]
TOKEN_ALUMINUM = ["\u94dd\u5408\u91d1", "\u94dd", "aluminum"]
UNIT_PATTERN = r"(\u6beb\u7c73|mm|\u5398\u7c73|cm|\u7c73|m)"


def resolve_scene_prompt(
    prompt: str,
    project_name: str,
    parameters: JSONDict | None = None,
    allow_defaults: bool = False,
    scene_template: str | None = None,
) -> JSONDict:
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")
    if not isinstance(project_name, str) or not project_name.strip():
        raise ValueError("project_name must be a non-empty string")
    if scene_template is not None:
        if scene_template not in SCENE_TEMPLATE_REGISTRY:
            raise ValueError(f"scene_id must be one of {', '.join(SUPPORTED_SCENE_TEMPLATES)}")
        scene = scene_template
    else:
        scene = classify_scene(prompt)
    parameters = validate_scene_parameters(parameters or {})
    if scene is None:
        return {
            "ok": False,
            "needs_confirmation": False,
            "reason": "unsupported_scene_prompt",
            "supported_scene_templates": SUPPORTED_SCENE_TEMPLATES,
            "message": "Prompt did not match a supported controlled scene template.",
        }

    extracted = extract_scene_parameters(scene, prompt)
    extracted.update(parameters)
    explicit_material = "material_name" in parameters
    if extracted.get("_ambiguous_material") and not explicit_material:
        extracted.pop("_ambiguous_material", None)
        return {
            "ok": False,
            "needs_confirmation": True,
            "reason": "ambiguous_material",
            "scene_template": scene,
            "missing_parameters": ["material_name"],
            "extracted_parameters": extracted,
            "suggested_defaults": {},
            "risk_notes": scene_risk_notes(scene),
            "message": "Prompt contains mixed material cues; provide parameters.material_name explicitly.",
        }
    extracted.pop("_ambiguous_material", None)
    defaults = scene_defaults(scene)
    required = scene_required(scene)
    missing = [key for key in required if key not in extracted]
    if missing and not allow_defaults:
        return {
            "ok": False,
            "needs_confirmation": True,
            "scene_template": scene,
            "missing_parameters": missing,
            "extracted_parameters": extracted,
            "suggested_defaults": {key: defaults[key] for key in missing},
            "risk_notes": scene_risk_notes(scene),
            "message": f"Prompt matched {scene} but is missing required physical parameters.",
        }

    resolved = dict(defaults)
    defaulted = []
    for key, value in extracted.items():
        resolved[key] = value
    for key in defaults:
        if key not in extracted:
            defaulted.append(key)
    spec = build_scene_spec(scene, project_name, resolved)
    return {
        "ok": True,
        "needs_confirmation": False,
        "scene_template": scene,
        "intent": "generate_scene",
        "project_name": project_name,
        "resolved_parameters": resolved,
        "extracted_parameters": extracted,
        "defaulted_parameters": defaulted,
        "risk_notes": scene_risk_notes(scene),
        "resolved_spec": spec,
        "summary": scene_summary(scene, resolved, defaulted),
    }


def validate_scene_parameters(parameters: JSONDict) -> JSONDict:
    allowed = {
        "rebar_length_m",
        "rebar_radius_m",
        "rebar_diameter_m",
        "drop_height_m",
        "rod_length_m",
        "rod_radius_m",
        "rod_diameter_m",
        "impact_velocity_m_per_s",
        "plate_length_m",
        "plate_width_m",
        "plate_thickness_m",
        "cube_length_m",
        "cube_width_m",
        "cube_height_m",
        "cube_size_m",
        "corner_force_n",
        "pressure_pa",
        "material_name",
    }
    unknown = sorted(set(parameters) - allowed)
    if unknown:
        raise ValueError(f"unsupported scene parameter(s): {', '.join(unknown)}")
    result: JSONDict = {}
    for key, value in parameters.items():
        if key == "material_name":
            if not isinstance(value, str) or not value:
                raise ValueError("parameters.material_name must be a non-empty string")
            result[key] = value
            continue
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise ValueError(f"parameters.{key} must be a number")
        number = float(value)
        if number <= 0:
            raise ValueError(f"parameters.{key} must be positive")
        result[key] = number
    if "rebar_diameter_m" in result:
        result["rebar_radius_m"] = float(result.pop("rebar_diameter_m")) / 2.0
    if "rod_diameter_m" in result:
        result["rod_radius_m"] = float(result.pop("rod_diameter_m")) / 2.0
    if "cube_size_m" in result:
        size = float(result.pop("cube_size_m"))
        result.setdefault("cube_length_m", size)
        result.setdefault("cube_width_m", size)
        result.setdefault("cube_height_m", size)
    return result


def classify_scene(prompt: str) -> str | None:
    text = normalize_text(prompt)
    has_rebar = any(token in text for token in TOKEN_REBAR)
    has_helmet = any(token in text for token in TOKEN_HELMET)
    has_plate = any(token in text for token in TOKEN_PLATE)
    has_cube = any(token in text for token in TOKEN_CUBE)
    has_pressure = any(token in text for token in TOKEN_PRESSURE)
    has_corner_load = any(token in text for token in TOKEN_CORNER_LOAD)
    has_drop_or_impact = any(token in text for token in TOKEN_DROP_IMPACT)
    if has_rebar and has_helmet and has_drop_or_impact:
        return "rebar_drop_on_helmet"
    if has_rebar and has_plate and has_drop_or_impact:
        return "rod_impact_plate"
    if has_cube and has_corner_load:
        return "cube_top_corner_load"
    if has_plate and has_pressure:
        return "plate_pressure"
    return None


def extract_scene_parameters(scene: str, prompt: str) -> JSONDict:
    if scene == "rebar_drop_on_helmet":
        return extract_rebar_helmet_parameters(prompt)
    if scene == "rod_impact_plate":
        return extract_rod_plate_parameters(prompt)
    if scene == "cube_top_corner_load":
        return extract_cube_load_parameters(prompt)
    if scene == "plate_pressure":
        return extract_plate_pressure_parameters(prompt)
    return {}


def extract_rebar_helmet_parameters(prompt: str) -> JSONDict:
    text = normalize_text(prompt)
    result: JSONDict = {}
    length = find_measure(text, [], prefer_before_keywords=TOKEN_LENGTH)
    if length is not None:
        result["rebar_length_m"] = length
    radius = find_measure(text, TOKEN_RADIUS)
    if radius is not None:
        result["rebar_radius_m"] = radius
    diameter = find_measure(text, TOKEN_DIAMETER)
    if diameter is not None and "rebar_radius_m" not in result:
        result["rebar_radius_m"] = diameter / 2.0
    drop_height = find_measure(text, TOKEN_DROP_HEIGHT)
    if drop_height is not None:
        result["drop_height_m"] = drop_height
    velocity = find_speed_m_per_s(text)
    if velocity is not None:
        result["impact_velocity_m_per_s"] = velocity
    material = extract_material(text)
    if material:
        result["material_name"] = material
    elif material_is_ambiguous(text):
        result["_ambiguous_material"] = True
    return result


def extract_rod_plate_parameters(prompt: str) -> JSONDict:
    text = normalize_text(prompt)
    result: JSONDict = {}
    length = find_measure(text, TOKEN_LENGTH)
    if length is not None:
        result["rod_length_m"] = length
    radius = find_measure(text, TOKEN_RADIUS)
    if radius is not None:
        result["rod_radius_m"] = radius
    diameter = find_measure(text, TOKEN_DIAMETER)
    if diameter is not None and "rod_radius_m" not in result:
        result["rod_radius_m"] = diameter / 2.0
    velocity = find_speed_m_per_s(text)
    if velocity is not None:
        result["impact_velocity_m_per_s"] = velocity
    plate_length = find_measure(text, ["\u94a2\u677f\u957f", "\u677f\u957f"])
    if plate_length is not None:
        result["plate_length_m"] = plate_length
    plate_width = find_measure(text, ["\u94a2\u677f\u5bbd", "\u677f\u5bbd", "\u5bbd"])
    if plate_width is not None:
        result["plate_width_m"] = plate_width
    plate_thickness = find_measure(text, ["\u94a2\u677f\u539a", "\u677f\u539a", "\u539a\u5ea6", "\u539a"])
    if plate_thickness is not None:
        result["plate_thickness_m"] = plate_thickness
    material = extract_material(text)
    if material:
        result["material_name"] = material
    elif material_is_ambiguous(text):
        result["_ambiguous_material"] = True
    return result


def extract_cube_load_parameters(prompt: str) -> JSONDict:
    text = normalize_text(prompt)
    result: JSONDict = {}
    dimensions = find_box_dimensions(text)
    if dimensions is not None:
        result["cube_length_m"], result["cube_width_m"], result["cube_height_m"] = dimensions
    force = find_force_n(text)
    if force is not None:
        result["corner_force_n"] = force
    material = extract_material(text)
    if material:
        result["material_name"] = material
    elif material_is_ambiguous(text):
        result["_ambiguous_material"] = True
    return result


def extract_plate_pressure_parameters(prompt: str) -> JSONDict:
    text = normalize_text(prompt)
    result: JSONDict = {}
    length = find_measure(text, ["\u957f\u5ea6", "\u957f"])
    if length is not None:
        result["plate_length_m"] = length
    width = find_measure(text, ["\u5bbd\u5ea6", "\u5bbd"])
    if width is not None:
        result["plate_width_m"] = width
    thickness = find_measure(text, ["\u539a\u5ea6", "\u539a"])
    if thickness is not None:
        result["plate_thickness_m"] = thickness
    pressure = find_pressure_pa(text)
    if pressure is not None:
        result["pressure_pa"] = pressure
    material = extract_material(text)
    if material:
        result["material_name"] = material
    elif material_is_ambiguous(text):
        result["_ambiguous_material"] = True
    return result


def find_measure(text: str, keywords: list[str], prefer_before_keywords: list[str] | None = None) -> float | None:
    number = r"([0-9]+(?:\.[0-9]+)?)"
    for keyword in keywords:
        match = re.search(rf"{keyword}[^\d]{{0,8}}{number}\s*{UNIT_PATTERN}", text, flags=re.IGNORECASE)
        if match:
            return to_meters(float(match.group(1)), match.group(2))
    before_keywords = prefer_before_keywords or keywords
    for keyword in before_keywords:
        match = re.search(rf"{number}\s*{UNIT_PATTERN}[^\d]{{0,8}}{keyword}", text, flags=re.IGNORECASE)
        if match:
            return to_meters(float(match.group(1)), match.group(2))
    return None


def find_speed_m_per_s(text: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(m/s|\u7c73/\u79d2|\u7c73\u6bcf\u79d2)", text, flags=re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))


def find_force_n(text: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(n|\u725b\u987f|\u725b)", text, flags=re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))


def find_pressure_pa(text: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(mpa|kpa|pa|\u5e15)", text, flags=re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit == "mpa":
        return value * 1_000_000.0
    if unit == "kpa":
        return value * 1000.0
    return value


def find_box_dimensions(text: str) -> tuple[float, float, float] | None:
    number = r"([0-9]+(?:\.[0-9]+)?)"
    match = re.search(rf"{number}\s*[xX\u00d7]\s*{number}\s*[xX\u00d7]\s*{number}\s*{UNIT_PATTERN}", text)
    if not match:
        return None
    unit = match.group(4)
    return (
        to_meters(float(match.group(1)), unit),
        to_meters(float(match.group(2)), unit),
        to_meters(float(match.group(3)), unit),
    )


def to_meters(value: float, unit: str) -> float:
    normalized = unit.lower()
    if normalized in {"\u6beb\u7c73", "mm"}:
        return value / 1000.0
    if normalized in {"\u5398\u7c73", "cm"}:
        return value / 100.0
    return value


def extract_material(text: str) -> str | None:
    has_aluminum = any(token in text for token in TOKEN_ALUMINUM)
    has_mild_steel = any(token in text for token in TOKEN_MILD_STEEL)
    if has_aluminum and has_mild_steel:
        return None
    if has_aluminum:
        return "aluminum_6061_t6"
    if has_mild_steel:
        return "mild_steel"
    return None


def material_is_ambiguous(text: str) -> bool:
    return any(token in text for token in TOKEN_ALUMINUM) and any(token in text for token in TOKEN_MILD_STEEL)


def build_scene_spec(scene: str, project_name: str, parameters: JSONDict) -> JSONDict:
    if scene == "rebar_drop_on_helmet":
        return apply_rebar_helmet_parameters(rebar_drop_on_helmet_spec(project_name), parameters)
    if scene == "rod_impact_plate":
        return apply_rod_plate_parameters(rod_impact_plate_spec(project_name), parameters)
    if scene == "cube_top_corner_load":
        return apply_cube_load_parameters(cube_top_corner_load_spec(project_name), parameters)
    if scene == "plate_pressure":
        return apply_plate_pressure_parameters(plate_pressure_spec(project_name), parameters)
    raise ValueError(f"unsupported scene template: {scene}")


def apply_rebar_helmet_parameters(spec: JSONDict, parameters: JSONDict) -> JSONDict:
    resolved = deepcopy(spec)
    rebar = next(component for component in resolved["components"] if component["id"] == "rebar")
    helmet = next(component for component in resolved["components"] if component["id"] == "helmet")
    rebar["geometry"]["length_m"] = float(parameters["rebar_length_m"])
    rebar["geometry"]["radius_m"] = float(parameters["rebar_radius_m"])
    material = str(parameters.get("material_name", "mild_steel"))
    rebar["material"]["name"] = material
    helmet["material"]["name"] = material
    helmet_height = float(helmet["geometry"]["height_m"])
    drop_height = float(parameters["drop_height_m"])
    impact_velocity = float(parameters["impact_velocity_m_per_s"])
    rebar["transform"]["translate_m"] = [0.0, 0.0, helmet_height + drop_height]
    rebar["initial_velocity_m_per_s"] = [0.0, 0.0, -impact_velocity]
    resolved["geometry"] = {
        "scene": "rebar_drop_on_helmet",
        "source": "scene_prompt",
        "drop_height_m": drop_height,
        "impact_velocity_m_per_s": impact_velocity,
    }
    return resolved


def apply_rod_plate_parameters(spec: JSONDict, parameters: JSONDict) -> JSONDict:
    resolved = deepcopy(spec)
    rod = next(component for component in resolved["components"] if component["id"] == "rod")
    plate = next(component for component in resolved["components"] if component["id"] == "plate")
    rod["geometry"]["length_m"] = float(parameters["rod_length_m"])
    rod["geometry"]["radius_m"] = float(parameters["rod_radius_m"])
    rod["initial_velocity_m_per_s"] = [0.0, 0.0, -float(parameters["impact_velocity_m_per_s"])]
    plate["geometry"]["length_m"] = float(parameters["plate_length_m"])
    plate["geometry"]["width_m"] = float(parameters["plate_width_m"])
    plate["geometry"]["thickness_m"] = float(parameters["plate_thickness_m"])
    plate["transform"]["translate_m"] = [-0.5 * float(parameters["plate_length_m"]), -0.5 * float(parameters["plate_width_m"]), 0.0]
    material = str(parameters.get("material_name", "mild_steel"))
    rod["material"]["name"] = material
    plate["material"]["name"] = material
    resolved["geometry"] = {
        "scene": "rod_impact_plate",
        "source": "scene_prompt",
        "impact_velocity_m_per_s": float(parameters["impact_velocity_m_per_s"]),
    }
    return resolved


def apply_cube_load_parameters(spec: JSONDict, parameters: JSONDict) -> JSONDict:
    resolved = deepcopy(spec)
    resolved["geometry"] = {
        "length_m": float(parameters["cube_length_m"]),
        "width_m": float(parameters["cube_width_m"]),
        "height_m": float(parameters["cube_height_m"]),
        "scene": "cube_top_corner_load",
    }
    dimensions = [
        float(parameters["cube_length_m"]),
        float(parameters["cube_width_m"]),
        float(parameters["cube_height_m"]),
    ]
    resolved["mesh"] = {"size_m": min(dimensions) / 4.0}
    resolved["material"] = {"name": str(parameters.get("material_name", "mild_steel"))}
    force = -abs(float(parameters["corner_force_n"]))
    resolved["loads"][0]["value_n"] = force
    resolved["loads"][0]["curve"]["end_value"] = force
    return resolved


def apply_plate_pressure_parameters(spec: JSONDict, parameters: JSONDict) -> JSONDict:
    resolved = deepcopy(spec)
    resolved["geometry"] = {
        "length_m": float(parameters["plate_length_m"]),
        "width_m": float(parameters["plate_width_m"]),
        "thickness_m": float(parameters["plate_thickness_m"]),
        "scene": "plate_pressure",
    }
    resolved["material"] = {"name": str(parameters.get("material_name", "mild_steel"))}
    pressure = float(parameters["pressure_pa"])
    resolved["loads"][0]["pressure_pa"] = pressure
    resolved["loads"][0]["curve"]["end_value"] = pressure
    return resolved


def scene_defaults(scene: str) -> JSONDict:
    if scene == "rebar_drop_on_helmet":
        return REBAR_HELMET_DEFAULTS
    if scene == "rod_impact_plate":
        return ROD_PLATE_DEFAULTS
    if scene == "cube_top_corner_load":
        return CUBE_LOAD_DEFAULTS
    if scene == "plate_pressure":
        return PLATE_PRESSURE_DEFAULTS
    return {}


def scene_required(scene: str) -> list[str]:
    if scene == "rebar_drop_on_helmet":
        return REBAR_HELMET_REQUIRED
    if scene == "rod_impact_plate":
        return ROD_PLATE_REQUIRED
    if scene == "cube_top_corner_load":
        return CUBE_LOAD_REQUIRED
    if scene == "plate_pressure":
        return PLATE_PRESSURE_REQUIRED
    return []


def scene_risk_notes(scene: str) -> list[str]:
    if scene in {"rebar_drop_on_helmet", "rod_impact_plate"}:
        return ["impact_contact", "review_contact_pair", "solver_result_required_for_damage_or_penetration"]
    if scene == "plate_pressure":
        return ["pressure_direction_review"]
    if scene == "cube_top_corner_load":
        return ["load_boundary_condition_review"]
    return []


def scene_summary(scene: str, parameters: JSONDict, defaulted: list[str]) -> str:
    if scene == "rebar_drop_on_helmet":
        return (
            "Resolved controlled scene rebar_drop_on_helmet: "
            f"rebar length={parameters['rebar_length_m']} m, "
            f"radius={parameters['rebar_radius_m']} m, "
            f"drop height={parameters['drop_height_m']} m, "
            f"impact velocity={parameters['impact_velocity_m_per_s']} m/s, "
            f"material={parameters.get('material_name', 'mild_steel')}; "
            f"defaulted={defaulted}."
        )
    if scene == "rod_impact_plate":
        return (
            "Resolved controlled scene rod_impact_plate: "
            f"rod length={parameters['rod_length_m']} m, "
            f"radius={parameters['rod_radius_m']} m, "
            f"impact velocity={parameters['impact_velocity_m_per_s']} m/s, "
            f"plate={parameters['plate_length_m']} x {parameters['plate_width_m']} x {parameters['plate_thickness_m']} m; "
            f"defaulted={defaulted}."
        )
    if scene == "cube_top_corner_load":
        return (
            "Resolved controlled scene cube_top_corner_load: "
            f"block={parameters['cube_length_m']} x {parameters['cube_width_m']} x {parameters['cube_height_m']} m, "
            f"top corner force={parameters['corner_force_n']} N downward; "
            f"defaulted={defaulted}."
        )
    if scene == "plate_pressure":
        return (
            "Resolved controlled scene plate_pressure: "
            f"plate={parameters['plate_length_m']} x {parameters['plate_width_m']} x {parameters['plate_thickness_m']} m, "
            f"pressure={parameters['pressure_pa']} Pa; "
            f"defaulted={defaulted}."
        )
    return f"Resolved controlled scene {scene}."


def normalize_text(text: str) -> str:
    return text.strip().lower().replace("\uff0c", ",").replace("\u3002", ".").replace("\u3000", " ")
