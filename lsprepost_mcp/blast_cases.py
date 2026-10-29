from __future__ import annotations

from .config import JSONDict


_PHASE13_CASES = (
    {
        "id": "blast_on_helmet",
        "phase": "13.1",
        "display_name": "简化爆炸冲击固定头盔",
        "description": "TNT 等效自由空爆压力作用于固定椭球头盔外表面。",
        "default_project_name": "phase13_blast_on_helmet",
    },
    {
        "id": "blast_on_circular_plate",
        "phase": "13.1",
        "display_name": "简化爆炸冲击固定圆板",
        "description": "TNT 等效自由空爆压力作用于外圈固定圆形钢板。",
        "default_project_name": "phase13_blast_on_circular_plate",
    },
    {
        "id": "blast_on_multiple_targets",
        "phase": "13.1",
        "display_name": "简化爆炸冲击多个目标",
        "description": "同一爆心同时作用于固定圆板和固定椭球头盔。",
        "default_project_name": "phase13_blast_on_multiple_targets",
    },
)


def blast_case_catalog() -> list[JSONDict]:
    return [dict(item) for item in _PHASE13_CASES]


def blast_case_payload(case_id: str, project_name: str | None = None) -> JSONDict:
    cases = {item["id"]: item for item in _PHASE13_CASES}
    case = cases.get(case_id)
    if case is None:
        raise ValueError(f"unsupported blast case: {case_id}")
    name = project_name or str(case["default_project_name"])
    if case_id == "blast_on_helmet":
        return _helmet_payload(name)
    if case_id == "blast_on_circular_plate":
        return _circular_plate_payload(name)
    return _multiple_target_payload(name)


def blast_plate_demo_payload(project_name: str = "phase12_blast_plate_demo") -> JSONDict:
    plate: JSONDict = {
        "id": "target_plate",
        "template": "shell_plate",
        "geometry": {"length_m": 1.0, "width_m": 1.0, "thickness_m": 0.01},
        "mesh": {"size_m": 0.025},
        "material": {"name": "mild_steel_mat24_demo"},
        "transform": {"translate_m": [-0.5, -0.5, 0.0]},
    }
    supports = [
        _support("support_x_min", [-0.5, -0.475, -0.025], [0.0, 0.0, 0.0]),
        _support("support_x_max", [-0.5, 0.475, -0.025], [0.0, 0.0, 0.0]),
        _support("support_y_min", [-0.475, -0.5, -0.025], [0.0, 0.0, 90.0]),
        _support("support_y_max", [0.475, -0.5, -0.025], [0.0, 0.0, 90.0]),
    ]
    actions: list[JSONDict] = [
        {"type": "fixed_region", "component": "target_plate", "region": "four_edges"},
        {
            "id": "blast_1",
            "type": "blast_enhanced",
            "charge_type": "tnt",
            "equivalent_mass_kg": 0.1,
            "position_m": [0.0, 0.0, 0.5],
            "mode": "free_air_burst",
            "targets": ["target_plate.top_surface"],
            "output_dt_s": 0.001,
        },
    ]
    return {
        "project_name": project_name,
        "components": [plate, *supports],
        "actions": actions,
        "analysis_control": {
            "termination": {"end_time_s": 0.02},
            "energy": {"hgen": 2, "rwen": 2, "slnten": 2, "rylen": 2},
            "timestep": {"tssfac": 0.9},
        },
        "database": {
            # The bundled R12 solver is double precision. IBINARY=1 keeps d3plot
            # in the 32-bit IEEE format expected by common LS-PrePost builds.
            "format": 0,
            "ibinary": 1,
            "d3plot_dt_s": 0.001,
            "extent_binary": {
                "neiph": 0,
                "strflg": 1,
                "sigflg": 1,
                "epsflg": 1,
                "rltflg": 1,
                "engflg": 1,
            },
        },
        "case_status": "demo",
        "engineering_notice": "This case validates the software workflow only; it is not an engineering blast certification.",
    }


def _helmet_payload(project_name: str) -> JSONDict:
    helmet = {
        "id": "target_helmet",
        "template": "ellipsoid_shell",
        "geometry": {
            "radius_x_m": 0.15,
            "radius_y_m": 0.12,
            "height_m": 0.10,
            "thickness_m": 0.003,
        },
        "mesh": {"size_m": 0.0125},
        "material": {"name": "mild_steel_mat24_demo"},
        "transform": {"translate_m": [0.0, 0.0, 0.0]},
    }
    actions = [
        {"type": "fixed_region", "component": "target_helmet", "region": "rim"},
        _blast_action(["target_helmet.outer_surface"], [0.0, 0.0, 0.5]),
    ]
    return _phase13_payload(project_name, "blast_on_helmet", [helmet], actions)


def _circular_plate_payload(project_name: str) -> JSONDict:
    plate = {
        "id": "target_circle",
        "template": "circular_plate",
        "geometry": {"radius_m": 0.30, "thickness_m": 0.008},
        "mesh": {"size_m": 0.02},
        "material": {"name": "mild_steel_mat24_demo"},
        "transform": {"translate_m": [0.0, 0.0, 0.0]},
    }
    actions = [
        {"type": "fixed_region", "component": "target_circle", "region": "rim"},
        _blast_action(["target_circle.top_surface"], [0.0, 0.0, 0.5]),
    ]
    return _phase13_payload(project_name, "blast_on_circular_plate", [plate], actions)


def _multiple_target_payload(project_name: str) -> JSONDict:
    circle = {
        "id": "target_circle",
        "template": "circular_plate",
        "geometry": {"radius_m": 0.25, "thickness_m": 0.008},
        "mesh": {"size_m": 0.025},
        "material": {"name": "mild_steel_mat24_demo"},
        "transform": {"translate_m": [-0.38, 0.0, 0.0]},
    }
    helmet = {
        "id": "target_helmet",
        "template": "ellipsoid_shell",
        "geometry": {
            "radius_x_m": 0.15,
            "radius_y_m": 0.12,
            "height_m": 0.10,
            "thickness_m": 0.003,
        },
        "mesh": {"size_m": 0.015},
        "material": {"name": "mild_steel_mat24_demo"},
        "transform": {"translate_m": [0.38, 0.0, 0.0]},
    }
    actions = [
        {"type": "fixed_region", "component": "target_circle", "region": "rim"},
        {"type": "fixed_region", "component": "target_helmet", "region": "rim"},
        _blast_action(
            ["target_circle.top_surface", "target_helmet.outer_surface"],
            [0.0, 0.0, 0.55],
        ),
    ]
    return _phase13_payload(project_name, "blast_on_multiple_targets", [circle, helmet], actions)


def _phase13_payload(
    project_name: str,
    case_id: str,
    components: list[JSONDict],
    actions: list[JSONDict],
) -> JSONDict:
    return {
        "project_name": project_name,
        "components": components,
        "actions": actions,
        "analysis_control": {
            "termination": {"end_time_s": 0.02},
            "energy": {"hgen": 2, "rwen": 2, "slnten": 2, "rylen": 2},
            "timestep": {"tssfac": 0.9},
        },
        "database": _blast_database(),
        "case_id": case_id,
        "case_status": "demo",
        "engineering_notice": (
            "This simplified blast case validates the software workflow only; "
            "it does not model air-domain shock-wave propagation or certify engineering performance."
        ),
    }


def _blast_action(targets: list[str], position: list[float]) -> JSONDict:
    return {
        "id": "blast_1",
        "type": "blast_enhanced",
        "charge_type": "tnt",
        "equivalent_mass_kg": 0.1,
        "position_m": position,
        "mode": "free_air_burst",
        "targets": targets,
        # A 1 ms BLSTFOR interval missed the sub-millisecond pressure peak in
        # the Phase 13 real run. Keep the controlled preset at 0.1 ms.
        "output_dt_s": 0.0001,
    }


def _blast_database() -> JSONDict:
    return {
        "format": 0,
        "ibinary": 1,
        "d3plot_dt_s": 0.001,
        "nodout_dt_s": 0.001,
        "extent_binary": {
            "neiph": 0,
            "strflg": 1,
            "sigflg": 1,
            "epsflg": 1,
            "rltflg": 1,
            "engflg": 1,
        },
    }


def _support(component_id: str, translate: list[float], rotate: list[float]) -> JSONDict:
    return {
        "id": component_id,
        "template": "beam_bar",
        "geometry": {"length_m": 1.0, "width_m": 0.05, "height_m": 0.05},
        "mesh": {"size_m": 0.05},
        "material": {"name": "mild_steel"},
        "transform": {"translate_m": translate, "rotate_deg": rotate},
        "fixed_faces": ["z_min"],
    }
