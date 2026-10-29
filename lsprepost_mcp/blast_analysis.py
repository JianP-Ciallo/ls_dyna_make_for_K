from __future__ import annotations

import math
from collections.abc import Mapping

from .config import JSONDict


def blast_sensitivity_report(raw: Mapping[str, object]) -> JSONDict:
    components = _object_list(raw.get("components"))
    actions = _object_list(raw.get("actions"))
    loads = _object_list(raw.get("loads"))
    blast_items = [item for item in [*actions, *loads] if item.get("type") == "blast_enhanced"]
    component_map = {str(item.get("id")): item for item in components}
    warnings: list[JSONDict] = []
    errors: list[JSONDict] = []
    targets: list[JSONDict] = []

    if not blast_items:
        errors.append({"id": "missing_blast", "message": "no blast_enhanced action or load is present"})

    demo_material_seen = False
    for component in components:
        material = component.get("material")
        name = str(material.get("name", "")) if isinstance(material, Mapping) else ""
        if name.endswith("_demo"):
            demo_material_seen = True
    if demo_material_seen:
        warnings.append(
            {
                "id": "demo_material",
                "severity": "warning",
                "message": "demo material requires project-specific review before engineering use",
            }
        )

    for blast in blast_items:
        position = _vector3(blast.get("position_m"))
        raw_targets = blast.get("targets")
        if not isinstance(raw_targets, list):
            errors.append({"id": "invalid_targets", "message": "blast targets must be an array"})
            continue
        for raw_target in raw_targets:
            reference = _target_reference(raw_target)
            component_id = reference.split(".", 1)[0]
            component = component_map.get(component_id)
            if component is None:
                errors.append({"id": "unknown_target", "message": f"unknown blast target: {reference}"})
                continue
            geometry = component.get("geometry") if isinstance(component.get("geometry"), Mapping) else {}
            mesh = component.get("mesh") if isinstance(component.get("mesh"), Mapping) else {}
            characteristic = _characteristic_size(geometry)
            thickness = _positive_or_none(geometry.get("thickness_m"))
            mesh_size = _positive_or_none(mesh.get("size_m"))
            center = _component_center(component)
            standoff = math.dist(position, center)
            standoff_ratio = standoff / characteristic if characteristic > 0.0 else math.inf
            mesh_thickness_ratio = (
                mesh_size / thickness if mesh_size is not None and thickness is not None else None
            )
            target_record: JSONDict = {
                "target": reference,
                "standoff_m": standoff,
                "characteristic_size_m": characteristic,
                "standoff_ratio": standoff_ratio,
                "mesh_thickness_ratio": mesh_thickness_ratio,
            }
            targets.append(target_record)
            if standoff_ratio < 0.25:
                warnings.append(
                    {
                        "id": "small_standoff_ratio",
                        "severity": "warning",
                        "target": reference,
                        "actual": standoff_ratio,
                        "message": "blast standoff is small relative to target size; review simplified-load applicability",
                    }
                )
            if mesh_thickness_ratio is not None and mesh_thickness_ratio > 20.0:
                warnings.append(
                    {
                        "id": "coarse_shell_mesh",
                        "severity": "warning",
                        "target": reference,
                        "actual": mesh_thickness_ratio,
                        "message": "shell in-plane mesh is coarse relative to thickness",
                    }
                )

    analysis_control = raw.get("analysis_control") if isinstance(raw.get("analysis_control"), Mapping) else {}
    termination = analysis_control.get("termination") if isinstance(analysis_control.get("termination"), Mapping) else {}
    database = raw.get("database") if isinstance(raw.get("database"), Mapping) else {}
    end_time = _positive_or_none(termination.get("end_time_s"))
    d3plot_dt = _positive_or_none(database.get("d3plot_dt_s"))
    maximum_standoff = max((float(item["standoff_m"]) for item in targets), default=0.0)
    if end_time is None:
        errors.append({"id": "missing_termination_time", "message": "a positive termination time is required"})
    elif maximum_standoff > 0.0:
        minimum_window = maximum_standoff / 343.0 + 0.005
        if end_time < minimum_window:
            warnings.append(
                {
                    "id": "short_termination_time",
                    "severity": "warning",
                    "actual": end_time,
                    "suggested_minimum_s": minimum_window,
                    "message": "termination time may end before the main structural response is captured",
                }
            )
    if end_time is not None and d3plot_dt is not None and d3plot_dt > end_time / 10.0:
        warnings.append(
            {
                "id": "sparse_d3plot_output",
                "severity": "warning",
                "actual": d3plot_dt,
                "limit": end_time / 10.0,
                "message": "d3plot output interval may miss a short response peak",
            }
        )
    if end_time is not None:
        blast_output_values = [
            value
            for item in blast_items
            if (value := _positive_or_none(item.get("output_dt_s"))) is not None
        ]
        if not blast_output_values:
            warnings.append(
                {
                    "id": "missing_blast_output_interval",
                    "severity": "warning",
                    "message": "blast output interval is not explicitly defined",
                }
            )
        elif max(blast_output_values) > end_time / 100.0:
            warnings.append(
                {
                    "id": "sparse_blast_output",
                    "severity": "warning",
                    "actual": max(blast_output_values),
                    "limit": end_time / 100.0,
                    "message": "blstfor output interval may miss a short pressure peak",
                }
            )

    return {
        "ok_for_demo": not errors,
        "scope": "simplified_blast_screening",
        "targets": targets,
        "warnings": warnings,
        "errors": errors,
        "notice": "Sensitivity hints are not a convergence study or engineering certification.",
    }


def summarize_blast_run(record: Mapping[str, object]) -> JSONDict:
    evaluation = record.get("solver_evaluation") if isinstance(record.get("solver_evaluation"), Mapping) else {}
    energy = evaluation.get("metrics") if isinstance(evaluation.get("metrics"), Mapping) else {}
    outputs = record.get("outputs") if isinstance(record.get("outputs"), Mapping) else {}
    post = record.get("postprocessing") if isinstance(record.get("postprocessing"), Mapping) else {}
    pressure = post.get("blast_pressure") if isinstance(post.get("blast_pressure"), Mapping) else {}
    binary_pressure = evaluation.get("blstfor") if isinstance(evaluation.get("blstfor"), Mapping) else {}
    pressure_value = pressure.get("peak_pressure_pa")
    pressure_time = pressure.get("peak_time_s")
    pressure_source = "LS-PrePost blstfor history extraction"
    if pressure_value is None:
        pressure_value = energy.get("peak_blast_pressure_pa")
        pressure_time = energy.get("peak_blast_pressure_time_s")
        pressure_source = "d3hsp enhanced blast summary"
    history_source = "LS-PrePost blstfor history extraction"
    impulse_value = pressure.get("positive_impulse_pa_s")
    duration_value = pressure.get("positive_duration_s")
    history_quality = pressure.get("positive_phase_quality")
    history_warnings = pressure.get("quality_warnings")
    if impulse_value is None and binary_pressure.get("positive_phase_status") == "available":
        impulse_value = binary_pressure.get("positive_impulse_pa_s")
        duration_value = binary_pressure.get("positive_duration_s")
        history_quality = binary_pressure.get("positive_phase_quality")
        history_warnings = binary_pressure.get("quality_warnings")
        history_source = "LS-DYNA BLSTFOR binary pressure history"
    displacement_value = post.get("peak_displacement_m")
    displacement_time = post.get("peak_displacement_time_s")
    displacement_state = post.get("peak_displacement_state")
    displacement_node = None
    displacement_time_step = None
    displacement_source = "LS-PrePost verified contour record"
    if displacement_value is None:
        displacement_value = energy.get("peak_displacement_m")
        displacement_time = energy.get("peak_displacement_time_s")
        displacement_node = energy.get("peak_displacement_node_id")
        displacement_time_step = energy.get("peak_displacement_time_step")
        displacement_source = "LS-DYNA nodout resultant displacement"

    metrics = {
        "hourglass_energy_ratio": _metric(
            energy.get("hourglass_ratio"), "ratio", "glstat/d3hsp solver evaluation"
        ),
        "total_initial_energy_ratio": _metric(
            energy.get("total_initial_ratio"), "ratio", "glstat/d3hsp solver evaluation"
        ),
        "peak_von_mises_stress": _metric(
            post.get("maximum_value_pa"),
            "Pa",
            "LS-PrePost verified contour record",
            state=post.get("state_number"),
            time_s=post.get("state_time_s"),
        ),
        "peak_displacement": _metric(
            displacement_value,
            "m",
            displacement_source,
            state=displacement_state,
            node_id=displacement_node,
            time_step=displacement_time_step,
            time_s=displacement_time,
        ),
        "peak_blast_pressure": _metric(
            pressure_value,
            "Pa",
            pressure_source,
            time_s=pressure_time,
        ),
        "peak_coupled_surface_pressure": _metric(
            energy.get("peak_coupled_surface_pressure_pa"),
            "Pa",
            "LS-DYNA DBFSI coupled-surface history",
        ),
        "peak_fsi_force": _metric(
            energy.get("peak_fsi_force_n"),
            "N",
            "LS-DYNA DBFSI coupled-surface history",
        ),
        "fsi_impulse": _metric(
            energy.get("fsi_impulse_n_s"),
            "N*s",
            "LS-DYNA DBFSI coupled-surface history",
        ),
        "positive_phase_impulse": _metric(
            impulse_value,
            "Pa*s",
            history_source,
            quality=history_quality,
            warnings=history_warnings,
        ),
        "positive_phase_duration": _metric(
            duration_value,
            "s",
            history_source,
            quality=history_quality,
            warnings=history_warnings,
        ),
        "d3plot_size": _output_metric(outputs.get("d3plot"), "byte", "solver output inventory"),
        "blstfor_size": _output_metric(outputs.get("blstfor"), "byte", "solver output inventory"),
        "nodout_size": _output_metric(outputs.get("nodout"), "byte", "solver output inventory"),
    }
    return {
        "ok": bool(record.get("ok")),
        "status": record.get("status", "unknown"),
        "project_name": record.get("project_name", ""),
        "run_id": record.get("run_id", ""),
        "metrics": metrics,
    }


def compare_blast_run_records(records: list[Mapping[str, object]]) -> JSONDict:
    if not isinstance(records, list) or len(records) < 2:
        raise ValueError("at least two blast run records are required")
    summaries = [summarize_blast_run(record) for record in records]
    comparisons: JSONDict = {}
    for metric_id in summaries[0]["metrics"]:
        entries = []
        units: set[str] = set()
        for summary in summaries:
            metric = summary["metrics"][metric_id]
            if metric["status"] != "available":
                continue
            units.add(str(metric["unit"]))
            entries.append(
                {
                    "project_name": summary["project_name"],
                    "run_id": summary["run_id"],
                    "value": metric["value"],
                }
            )
        if not entries:
            continue
        if len(units) != 1:
            raise ValueError(f"metric {metric_id} has incompatible units")
        values = [float(entry["value"]) for entry in entries]
        minimum, maximum = min(values), max(values)
        comparisons[metric_id] = {
            "unit": next(iter(units)),
            "values": entries,
            "minimum": minimum,
            "maximum": maximum,
            "range": maximum - minimum,
            "max_min_ratio": maximum / minimum if minimum > 0.0 else None,
        }
    return {
        "ok": True,
        "run_count": len(summaries),
        "runs": summaries,
        "comparisons": comparisons,
        "configuration_comparison": _compare_blast_configurations(records),
    }


def blast_configuration_summary(raw: Mapping[str, object]) -> JSONDict:
    components = _object_list(raw.get("components"))
    loads = _object_list(raw.get("loads"))
    actions = _object_list(raw.get("actions"))
    blasts = [item for item in [*loads, *actions] if item.get("type") == "blast_enhanced"]
    analysis = raw.get("analysis_control") if isinstance(raw.get("analysis_control"), Mapping) else {}
    termination = analysis.get("termination") if isinstance(analysis.get("termination"), Mapping) else {}
    database = raw.get("database") if isinstance(raw.get("database"), Mapping) else {}
    return {
        "unit_system": raw.get("unit_system", ""),
        "equivalent_mass_kg": sorted(
            value for item in blasts if (value := _finite_number(item.get("equivalent_mass_kg"))) is not None
        ),
        "blast_positions_m": sorted(
            tuple(_vector3(item.get("position_m"))) for item in blasts
        ),
        "blast_targets": sorted(
            _target_reference(target)
            for item in blasts
            for target in item.get("targets", [])
            if isinstance(item.get("targets"), list)
        ),
        "mesh_sizes_m": sorted(
            value
            for component in components
            if isinstance(component.get("mesh"), Mapping)
            and (value := _finite_number(component["mesh"].get("size_m"))) is not None
        ),
        "material_names": sorted(
            str(component["material"].get("name", ""))
            for component in components
            if isinstance(component.get("material"), Mapping)
        ),
        "end_time_s": _finite_number(termination.get("end_time_s")),
        "d3plot_dt_s": _finite_number(database.get("d3plot_dt_s")),
        "nodout_dt_s": _finite_number(database.get("nodout_dt_s")),
        "blast_output_dt_s": sorted(
            value for item in blasts if (value := _finite_number(item.get("output_dt_s"))) is not None
        ),
    }


def _compare_blast_configurations(records: list[Mapping[str, object]]) -> JSONDict:
    configurations = [
        record.get("blast_configuration")
        for record in records
        if isinstance(record.get("blast_configuration"), Mapping)
    ]
    if len(configurations) != len(records):
        return {
            "status": "unavailable",
            "changed_critical_variables": [],
            "warning": None,
            "message": "one or more run records do not contain a Phase 13 configuration summary",
        }
    keys = sorted({str(key) for config in configurations for key in config})
    changed = [key for key in keys if len({_stable_value(config.get(key)) for config in configurations}) > 1]
    warning = None
    if len(changed) > 1:
        warning = {
            "id": "multiple_variables_changed",
            "severity": "warning",
            "message": "multiple critical variables changed; the result difference cannot be attributed to one factor",
        }
    return {
        "status": "available",
        "changed_critical_variables": changed,
        "warning": warning,
    }


def _stable_value(value: object) -> str:
    if isinstance(value, Mapping):
        return repr(sorted((str(key), _stable_value(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return repr(tuple(_stable_value(item) for item in value))
    return repr(value)


def _metric(value: object, unit: str, source: str, **extra: object) -> JSONDict:
    available = _finite_number(value)
    result: JSONDict = {
        "status": "available" if available is not None else "unavailable",
        "value": available,
        "unit": unit,
        "source": source,
    }
    result.update({key: value for key, value in extra.items() if value is not None})
    return result


def _output_metric(value: object, unit: str, source: str) -> JSONDict:
    if not isinstance(value, Mapping) or not value.get("ok"):
        return _metric(None, unit, source)
    return _metric(value.get("total_size_bytes"), unit, source)


def _object_list(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _target_reference(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return f"{value.get('component', '')}.{value.get('surface', '')}"
    return ""


def _component_center(component: Mapping[str, object]) -> list[float]:
    geometry = component.get("geometry") if isinstance(component.get("geometry"), Mapping) else {}
    transform = component.get("transform") if isinstance(component.get("transform"), Mapping) else {}
    translate = _vector3(transform.get("translate_m", [0.0, 0.0, 0.0]))
    template = str(component.get("template", ""))
    if template == "shell_plate":
        return [
            translate[0] + float(geometry.get("length_m", 0.0)) / 2.0,
            translate[1] + float(geometry.get("width_m", 0.0)) / 2.0,
            translate[2],
        ]
    if template == "ellipsoid_shell":
        return [translate[0], translate[1], translate[2] + float(geometry.get("height_m", 0.0)) / 2.0]
    return translate


def _characteristic_size(geometry: Mapping[str, object]) -> float:
    values = []
    for key in ("length_m", "width_m", "height_m", "radius_x_m", "radius_y_m", "radius_m"):
        value = _positive_or_none(geometry.get(key))
        if value is not None:
            values.append(value * 2.0 if key.startswith("radius") else value)
    return max(values, default=0.0)


def _vector3(value: object) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return [0.0, 0.0, 0.0]
    return [float(item) for item in value]


def _positive_or_none(value: object) -> float | None:
    number = _finite_number(value)
    return number if number is not None and number > 0.0 else None


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None
