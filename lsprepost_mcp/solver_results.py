from __future__ import annotations

import math
import re
import struct

from .config import JSONDict


NUMBER_PATTERN = r"[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?|NaN|Inf(?:inity)?)"
ENERGY_PATTERNS = {
    "kinetic_energy": rf"^\s*kinetic\s+energy\s*\.*\s*({NUMBER_PATTERN})\s*$",
    "internal_energy": rf"^\s*internal\s+energy\s*\.*\s*({NUMBER_PATTERN})\s*$",
    "hourglass_energy": rf"^\s*hourglass\s+energy\s*\.*\s*({NUMBER_PATTERN})\s*$",
    "total_energy": rf"^\s*total\s+energy\s*\.*\s*({NUMBER_PATTERN})\s*$",
    "total_initial_ratio": rf"^\s*total\s+energy\s*/\s*initial\s+energy\s*\.*\s*({NUMBER_PATTERN})\s*$",
}
PROBLEM_TIME_PATTERNS = (
    rf"^\s*problem\s+time\s*=\s*({NUMBER_PATTERN})\s*$",
    rf"^\s*time\s*\.+\s*({NUMBER_PATTERN})\s*$",
)
BLAST_PEAK_PATTERN = re.compile(
    rf"enhanced\s+blast\s*#\s*(\d+)\s*:\s*pmax\s*=\s*({NUMBER_PATTERN})"
    rf"\s+at\s+time\s*=\s*({NUMBER_PATTERN})",
    flags=re.IGNORECASE,
)
NODOUT_STATE_PATTERN = re.compile(
    rf"t\s*i\s*m\s*e\s+s\s*t\s*e\s*p\s+(\d+).*?"
    rf"at\s+time\s+({NUMBER_PATTERN})",
    flags=re.IGNORECASE,
)
NODOUT_NUMBER_PATTERN = re.compile(NUMBER_PATTERN, flags=re.IGNORECASE)
ELOUT_STATE_PATTERN = re.compile(
    rf"t\s*i\s*m\s*e\s+s\s*t\s*e\s*p\s+(\d+).*?"
    rf"a\s*t\s+t\s*i\s*m\s*e\s+({NUMBER_PATTERN})",
    flags=re.IGNORECASE,
)
ELOUT_ELEMENT_PATTERN = re.compile(r"^\s*(\d+)-\s+(\d+)\s*$")
ELOUT_STRESS_PATTERN = re.compile(r"^\s*\d+-\s+\d+\s+\S+\s+(.*)$")


def parse_d3hsp(text: str) -> JSONDict:
    if not isinstance(text, str):
        raise TypeError("d3hsp text must be a string")
    lower_text = text.lower()
    normal_marker = (
        "termination time reached" in lower_text
        or "normal termination" in lower_text
        or bool(
            re.search(
                r"n\s*o\s*r\s*m\s*a\s*l\s+"
                r"t\s*e\s*r\s*m\s*i\s*n\s*a\s*t\s*i\s*o\s*n",
                text,
                flags=re.IGNORECASE,
            )
        )
    )
    error_marker = bool(
        re.search(
            r"(?im)^\s*(?:\*+\s*)?(?:error|e\s+r\s+r\s+o\s+r)\s+"
            r"(?:termination|t\s+e\s+r\s+m\s+i\s+n\s+a\s+t\s+i\s+o\s+n)\b",
            text,
        )
    )

    series: JSONDict = {}
    for name, pattern in ENERGY_PATTERNS.items():
        series[name] = [
            _parse_number(match.group(1))
            for match in re.finditer(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        ]

    all_values = [value for values in series.values() for value in values]
    finite = bool(all_values) and all(math.isfinite(value) for value in all_values)
    final = {name: values[-1] for name, values in series.items() if values}
    max_abs = {
        name: max((abs(value) for value in values if math.isfinite(value)), default=0.0)
        for name, values in series.items()
    }
    blast_peaks = [
        {
            "blast_id": int(match.group(1)),
            "peak_pressure_pa": _parse_number(match.group(2)),
            "peak_time_s": _parse_number(match.group(3)),
        }
        for match in BLAST_PEAK_PATTERN.finditer(text)
    ]
    problem_times_s = [
        _parse_number(match.group(1))
        for pattern in PROBLEM_TIME_PATTERNS
        for match in re.finditer(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    ]
    return {
        "terminated_normally": normal_marker and not error_marker,
        "termination_marker": "error" if error_marker else "normal" if normal_marker else "missing",
        "termination_time_reached": "termination time reached" in lower_text,
        "problem_times_s": problem_times_s,
        "final_problem_time_s": max(problem_times_s, default=None),
        "finite": finite,
        "series": series,
        "final": final,
        "max_abs": max_abs,
        "blast_peaks": blast_peaks,
    }


def parse_fsi_interfaces(text: str) -> JSONDict:
    if not isinstance(text, str):
        raise TypeError("d3hsp text must be a string")
    current: JSONDict | None = None
    interfaces: list[JSONDict] = []
    interface_pattern = re.compile(
        r"FSI\s+Interface\s+ID\s*\.*\s*(\d+)",
        flags=re.IGNORECASE,
    )
    segment_count_pattern = re.compile(
        r"number\s+of\s+slave\s+segments\s+for\s+coupling\s*\.*\s*(\d+)",
        flags=re.IGNORECASE,
    )
    material_count_pattern = re.compile(
        r"number\s+of\s+slave\s+(?:materials|parts)\s*\.*\s*(\d+)",
        flags=re.IGNORECASE,
    )
    for line in text.splitlines():
        interface_match = interface_pattern.search(line)
        if interface_match:
            if current is not None and current["slave_segment_count"] is not None:
                interfaces.append(current)
            current = {
                "interface_id": int(interface_match.group(1)),
                "slave_segment_count": None,
                "slave_material_count": 0,
            }
            continue
        if current is None:
            continue
        material_count_match = material_count_pattern.search(line)
        if material_count_match:
            current["slave_material_count"] = max(
                int(current["slave_material_count"]),
                int(material_count_match.group(1)),
            )
            continue
        segment_count_match = segment_count_pattern.search(line)
        if segment_count_match:
            current["slave_segment_count"] = int(segment_count_match.group(1))
    if current is not None and current["slave_segment_count"] is not None:
        interfaces.append(current)

    total = sum(int(item["slave_segment_count"]) for item in interfaces)
    slave_material_count = sum(int(item["slave_material_count"]) for item in interfaces)
    has_segments = total > 0
    has_materials = slave_material_count > 0
    slave_definition_mode = (
        "segments_and_part_or_material"
        if has_segments and has_materials
        else "explicit_segments"
        if has_segments
        else "part_or_material"
        if has_materials
        else "missing"
    )
    return {
        "interface_count": len(interfaces),
        "interfaces": interfaces,
        "total_slave_segment_count": total,
        "slave_material_count": slave_material_count,
        "has_slave_definition": has_segments or has_materials,
        "slave_definition_mode": slave_definition_mode,
        "all_nonempty": bool(interfaces)
        and all(int(item["slave_segment_count"]) > 0 for item in interfaces),
    }


def parse_nodout(text: str) -> JSONDict:
    if not isinstance(text, str):
        raise TypeError("nodout text must be a string")
    current_step: int | None = None
    current_time: float | None = None
    translation_block = False
    states: set[tuple[int, float]] = set()
    sample_count = 0
    peak: JSONDict | None = None
    first_state_time: float | None = None
    initial_peak_displacement = 0.0

    for line in text.splitlines():
        state_match = NODOUT_STATE_PATTERN.search(line)
        if state_match:
            current_step = int(state_match.group(1))
            current_time = _parse_number(state_match.group(2))
            if not math.isfinite(current_time) or current_time < 0.0:
                raise ValueError("nodout state time must be finite and non-negative")
            states.add((current_step, current_time))
            if first_state_time is None:
                first_state_time = current_time
            translation_block = False
            continue

        lower = line.lower()
        if "nodal point" in lower and "x-disp" in lower:
            translation_block = True
            continue
        if "nodal point" in lower and "x-rot" in lower:
            translation_block = False
            continue
        if not translation_block or current_step is None or current_time is None:
            continue

        values = NODOUT_NUMBER_PATTERN.findall(line)
        if len(values) < 4:
            continue
        node_id = int(values[0])
        x, y, z = (_parse_number(value) for value in values[1:4])
        if not all(math.isfinite(value) for value in (x, y, z)):
            raise ValueError("nodout displacement values must be finite")
        displacement = math.sqrt(x * x + y * y + z * z)
        if current_time == first_state_time:
            initial_peak_displacement = max(initial_peak_displacement, displacement)
        sample_count += 1
        if peak is None or displacement > float(peak["peak_displacement_m"]):
            peak = {
                "peak_displacement_m": displacement,
                "peak_node_id": node_id,
                "peak_time_step": current_step,
                "peak_time_s": current_time,
                "peak_components_m": {"x": x, "y": y, "z": z},
            }

    result: JSONDict = {
        "ok": peak is not None,
        "state_count": len(states),
        "sample_count": sample_count,
    }
    if peak is not None:
        result.update(peak)
        result["initial_peak_displacement_m"] = initial_peak_displacement
        result["effective_peak_displacement_m"] = max(
            0.0,
            float(peak["peak_displacement_m"]) - initial_peak_displacement,
        )
        result["displacement_signal_duration_s"] = max(
            0.0,
            float(peak["peak_time_s"]) - float(first_state_time or 0.0),
        )
    return result


def parse_city_object_responses(
    dbfsi_text: str,
    elout_text: str,
    nodout_text: str,
    response_objects: list[JSONDict],
) -> dict[str, JSONDict]:
    if not response_objects:
        raise ValueError("response_objects must not be empty")
    by_object: dict[str, JSONDict] = {}
    surface_to_object: dict[int, str] = {}
    for item in response_objects:
        object_id = str(item["object_id"])
        surface_id = int(item["fsi_surface_id"])
        if object_id in by_object:
            raise ValueError(f"duplicate response object id: {object_id}")
        if surface_id in surface_to_object:
            raise ValueError(f"duplicate response FSI surface id: {surface_id}")
        by_object[object_id] = {
            "object_id": object_id,
            "fsi_surface_id": surface_id,
        }
        surface_to_object[surface_id] = object_id

    dbfsi = parse_dbfsi(dbfsi_text)
    surfaces = {
        int(item["surface_id"]): item
        for item in dbfsi["surfaces"]
    }
    for object_id, result in by_object.items():
        surface = surfaces.get(int(result["fsi_surface_id"]))
        if surface is None:
            result["fsi_present"] = False
            continue
        result.update(
            {
                "fsi_present": True,
                "peak_fsi_pressure_rise_pa": float(
                    surface["peak_pressure_rise_pa"]
                ),
                "peak_fsi_pressure_time_s": float(
                    surface["peak_pressure_rise_time_s"]
                ),
                "fsi_arrival_time_s": surface["pressure_arrival_time_s"],
                "fsi_positive_pressure_sample_count": int(
                    surface["positive_pressure_sample_count"]
                ),
                "fsi_positive_pressure_duration_s": float(
                    surface["positive_pressure_duration_s"]
                ),
                "fsi_positive_pressure_impulse_pa_s": float(
                    surface["positive_pressure_impulse_pa_s"]
                ),
                "peak_fsi_force_rise_n": float(
                    surface["peak_force_rise_n"]
                ),
                "fsi_impulse_magnitude_n_s": float(
                    surface["fsi_impulse_magnitude_n_s"]
                ),
            }
        )

    structural = _parse_city_elout(
        elout_text,
        response_objects,
        {
            object_id: result.get("fsi_arrival_time_s")
            for object_id, result in by_object.items()
        },
    )
    displacement = _parse_city_nodout(nodout_text, response_objects)
    for object_id, result in by_object.items():
        result.update(structural[object_id])
        result.update(displacement[object_id])
        response_times = [
            value
            for value in (
                result.get("last_structural_time_s"),
                result.get("last_displacement_time_s"),
            )
            if isinstance(value, (int, float)) and math.isfinite(float(value))
        ]
        result["last_response_time_s"] = (
            max(float(value) for value in response_times)
            if response_times
            else None
        )
    return by_object


def _parse_city_elout(
    text: str,
    response_objects: list[JSONDict],
    fsi_arrival_times: dict[str, object],
) -> dict[str, JSONDict]:
    element_to_object: dict[int, str] = {}
    for item in response_objects:
        object_id = str(item["object_id"])
        for element_id in item.get("shell_element_ids", []):
            element_id = int(element_id)
            previous = element_to_object.setdefault(element_id, object_id)
            if previous != object_id:
                raise ValueError(
                    f"shell element {element_id} belongs to multiple response objects"
                )
    baselines: dict[int, tuple[float, ...]] = {}
    samples: dict[str, list[JSONDict]] = {
        str(item["object_id"]): []
        for item in response_objects
    }
    current_step: int | None = None
    current_time: float | None = None
    current_element: int | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        state_match = ELOUT_STATE_PATTERN.search(line)
        if state_match:
            current_step = int(state_match.group(1))
            current_time = _parse_number(state_match.group(2))
            if not math.isfinite(current_time) or current_time < 0.0:
                raise ValueError("elout state time must be finite and non-negative")
            current_element = None
            continue
        element_match = ELOUT_ELEMENT_PATTERN.match(line)
        if element_match:
            element_id = int(element_match.group(1))
            current_element = (
                element_id
                if element_id in element_to_object
                else None
            )
            continue
        if current_element is None or current_time is None or current_step is None:
            continue
        stress_match = ELOUT_STRESS_PATTERN.match(line)
        if stress_match is None:
            continue
        values = stress_match.group(1).split()
        if len(values) < 6:
            raise ValueError(
                f"elout stress values are missing at line {line_number}"
            )
        stress = tuple(_parse_number(value) for value in values[:6])
        if not all(math.isfinite(value) for value in stress):
            raise ValueError("elout stress values must be finite")
        baseline = baselines.setdefault(current_element, stress)
        response = tuple(
            value - initial
            for value, initial in zip(stress, baseline, strict=True)
        )
        pressure = -(response[0] + response[1] + response[2]) / 3.0
        principal_peak = max(
            _principal_stresses(response),
            key=abs,
        )
        samples[element_to_object[current_element]].append(
            {
                "time_step": current_step,
                "time_s": current_time,
                "element_id": current_element,
                "pressure_pa": pressure,
                "principal_stress_pa": principal_peak,
            }
        )

    results: dict[str, JSONDict] = {}
    for object_id, object_samples in samples.items():
        if not object_samples:
            results[object_id] = {
                "structural_stress_present": False,
                "structural_sample_count": 0,
                **_city_structural_causality_metrics(
                    [],
                    fsi_arrival_times.get(object_id),
                ),
            }
            continue
        states: list[JSONDict] = []
        samples_by_time: dict[float, list[JSONDict]] = {}
        for sample in object_samples:
            samples_by_time.setdefault(float(sample["time_s"]), []).append(sample)
        for time_s, state_samples in sorted(samples_by_time.items()):
            pressure_peak = max(
                state_samples,
                key=lambda item: abs(float(item["pressure_pa"])),
            )
            principal_peak = max(
                state_samples,
                key=lambda item: abs(float(item["principal_stress_pa"])),
            )
            states.append(
                {
                    "time_s": time_s,
                    "peak_structural_pressure_pa": abs(
                        float(pressure_peak["pressure_pa"])
                    ),
                    "peak_structural_pressure_element_id": int(
                        pressure_peak["element_id"]
                    ),
                    "peak_principal_stress_pa": abs(
                        float(principal_peak["principal_stress_pa"])
                    ),
                }
            )
        pressure_peak = max(
            states,
            key=lambda item: float(item["peak_structural_pressure_pa"]),
        )
        principal_peak = max(
            states,
            key=lambda item: float(item["peak_principal_stress_pa"]),
        )
        result: JSONDict = {
            "structural_stress_present": True,
            "structural_sample_count": len(object_samples),
            "structural_state_count": len(states),
            "peak_structural_pressure_pa": float(
                pressure_peak["peak_structural_pressure_pa"]
            ),
            "peak_structural_pressure_time_s": float(pressure_peak["time_s"]),
            "peak_structural_pressure_element_id": int(
                pressure_peak["peak_structural_pressure_element_id"]
            ),
            "peak_principal_stress_pa": float(
                principal_peak["peak_principal_stress_pa"]
            ),
            "peak_principal_stress_time_s": float(principal_peak["time_s"]),
            "last_structural_time_s": float(states[-1]["time_s"]),
        }
        result.update(
            _city_structural_causality_metrics(
                states,
                fsi_arrival_times.get(object_id),
            )
        )
        results[object_id] = result
    return results


def _city_structural_causality_metrics(
    states: list[JSONDict],
    fsi_arrival_time_s: object,
) -> JSONDict:
    if not isinstance(fsi_arrival_time_s, (int, float)) or not math.isfinite(
        float(fsi_arrival_time_s)
    ):
        return {
            "pre_arrival_peak_structural_pressure_pa": None,
            "pre_arrival_peak_principal_stress_pa": None,
            "post_arrival_peak_structural_pressure_pa": None,
            "post_arrival_peak_principal_stress_pa": None,
            "pre_arrival_pressure_quiet_limit_pa": None,
            "pre_arrival_principal_stress_quiet_limit_pa": None,
            "structural_pressure_signal_to_noise_ratio": None,
            "principal_stress_signal_to_noise_ratio": None,
            "structural_signal_to_noise_ratio": None,
            "pre_arrival_quiet": None,
            "post_arrival_consecutive_signal_state_count": 0,
            "structural_arrival_time_s": None,
            "post_arrival_observation_s": None,
        }

    arrival_time_s = float(fsi_arrival_time_s)
    pre_arrival_states = [
        state for state in states if float(state["time_s"]) < arrival_time_s
    ]
    post_arrival_states = [
        state for state in states if float(state["time_s"]) >= arrival_time_s
    ]

    def peak(states_to_measure: list[JSONDict], key: str) -> float:
        return max(
            (float(state[key]) for state in states_to_measure),
            default=0.0,
        )

    pre_pressure = peak(pre_arrival_states, "peak_structural_pressure_pa")
    pre_principal = peak(pre_arrival_states, "peak_principal_stress_pa")
    post_pressure = peak(post_arrival_states, "peak_structural_pressure_pa")
    post_principal = peak(post_arrival_states, "peak_principal_stress_pa")
    pressure_quiet_limit = max(100.0, 0.05 * post_pressure)
    principal_quiet_limit = max(100.0, 0.05 * post_principal)
    pre_arrival_quiet = (
        pre_pressure <= pressure_quiet_limit
        and pre_principal <= principal_quiet_limit
    )
    consecutive_signal_count = 0
    largest_consecutive_signal_count = 0
    structural_arrival_time_s: float | None = None
    for state_index, state in enumerate(post_arrival_states):
        state_has_signal = max(
            float(state["peak_structural_pressure_pa"]),
            float(state["peak_principal_stress_pa"]),
        ) > 100.0
        consecutive_signal_count = (
            consecutive_signal_count + 1
            if state_has_signal
            else 0
        )
        largest_consecutive_signal_count = max(
            largest_consecutive_signal_count,
            consecutive_signal_count,
        )
        if (
            structural_arrival_time_s is None
            and pre_arrival_quiet
            and consecutive_signal_count >= 2
        ):
            structural_arrival_time_s = float(
                post_arrival_states[state_index - 1]["time_s"]
            )
    return {
        "pre_arrival_peak_structural_pressure_pa": pre_pressure,
        "pre_arrival_peak_principal_stress_pa": pre_principal,
        "post_arrival_peak_structural_pressure_pa": post_pressure,
        "post_arrival_peak_principal_stress_pa": post_principal,
        "pre_arrival_pressure_quiet_limit_pa": pressure_quiet_limit,
        "pre_arrival_principal_stress_quiet_limit_pa": principal_quiet_limit,
        "structural_pressure_signal_to_noise_ratio": _safe_ratio(
            post_pressure,
            max(pre_pressure, 100.0),
        ),
        "principal_stress_signal_to_noise_ratio": _safe_ratio(
            post_principal,
            max(pre_principal, 100.0),
        ),
        "structural_signal_to_noise_ratio": _safe_ratio(
            max(post_pressure, post_principal),
            max(pre_pressure, pre_principal, 100.0),
        ),
        "pre_arrival_quiet": pre_arrival_quiet,
        "post_arrival_consecutive_signal_state_count": largest_consecutive_signal_count,
        "structural_arrival_time_s": structural_arrival_time_s,
        "post_arrival_observation_s": (
            float(post_arrival_states[-1]["time_s"]) - arrival_time_s
            if post_arrival_states
            else None
        ),
    }


def _parse_city_nodout(
    text: str,
    response_objects: list[JSONDict],
) -> dict[str, JSONDict]:
    node_to_object: dict[int, str] = {}
    for item in response_objects:
        object_id = str(item["object_id"])
        for node_id in item.get("node_ids", []):
            node_id = int(node_id)
            previous = node_to_object.setdefault(node_id, object_id)
            if previous != object_id:
                raise ValueError(
                    f"node {node_id} belongs to multiple response objects"
                )
    baselines: dict[int, tuple[float, float, float]] = {}
    peaks: dict[str, JSONDict | None] = {
        str(item["object_id"]): None
        for item in response_objects
    }
    sample_counts = {object_id: 0 for object_id in peaks}
    last_times: dict[str, float | None] = {
        object_id: None
        for object_id in peaks
    }
    current_step: int | None = None
    current_time: float | None = None
    translation_block = False
    for line in text.splitlines():
        state_match = NODOUT_STATE_PATTERN.search(line)
        if state_match:
            current_step = int(state_match.group(1))
            current_time = _parse_number(state_match.group(2))
            if not math.isfinite(current_time) or current_time < 0.0:
                raise ValueError("nodout state time must be finite and non-negative")
            translation_block = False
            continue
        lower = line.lower()
        if "nodal point" in lower and "x-disp" in lower:
            translation_block = True
            continue
        if "nodal point" in lower and "x-rot" in lower:
            translation_block = False
            continue
        if not translation_block or current_step is None or current_time is None:
            continue
        values = NODOUT_NUMBER_PATTERN.findall(line)
        if len(values) < 4:
            continue
        node_id = int(values[0])
        object_id = node_to_object.get(node_id)
        if object_id is None:
            continue
        vector = tuple(_parse_number(value) for value in values[1:4])
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("nodout displacement values must be finite")
        baseline = baselines.setdefault(node_id, vector)
        delta = tuple(
            value - initial
            for value, initial in zip(vector, baseline, strict=True)
        )
        magnitude = math.sqrt(sum(value * value for value in delta))
        sample_counts[object_id] += 1
        last_times[object_id] = current_time
        candidate = {
            "peak_displacement_m": magnitude,
            "peak_displacement_time_s": current_time,
            "peak_displacement_time_step": current_step,
            "peak_displacement_node_id": node_id,
            "peak_displacement_components_m": {
                "x": delta[0],
                "y": delta[1],
                "z": delta[2],
            },
        }
        peak = peaks[object_id]
        if peak is None or magnitude > float(peak["peak_displacement_m"]):
            peaks[object_id] = candidate
    results: dict[str, JSONDict] = {}
    for object_id, peak in peaks.items():
        results[object_id] = {
            "displacement_present": peak is not None,
            "displacement_sample_count": sample_counts[object_id],
            "last_displacement_time_s": last_times[object_id],
        }
        if peak is not None:
            results[object_id].update(peak)
    return results


def _principal_stresses(stress: tuple[float, ...]) -> tuple[float, float, float]:
    if len(stress) != 6:
        raise ValueError("stress must contain six components")
    xx, yy, zz, xy, yz, zx = stress
    mean = (xx + yy + zz) / 3.0
    p_squared = (
        (xx - mean) ** 2
        + (yy - mean) ** 2
        + (zz - mean) ** 2
        + 2.0 * (xy * xy + yz * yz + zx * zx)
    ) / 6.0
    if p_squared <= 1.0e-30:
        return (mean, mean, mean)
    p = math.sqrt(p_squared)
    bxx = (xx - mean) / p
    byy = (yy - mean) / p
    bzz = (zz - mean) / p
    bxy = xy / p
    byz = yz / p
    bzx = zx / p
    determinant = (
        bxx * byy * bzz
        + 2.0 * bxy * byz * bzx
        - bxx * byz * byz
        - byy * bzx * bzx
        - bzz * bxy * bxy
    )
    angle = math.acos(max(-1.0, min(1.0, determinant / 2.0))) / 3.0
    first = mean + 2.0 * p * math.cos(angle)
    third = mean + 2.0 * p * math.cos(angle + 2.0 * math.pi / 3.0)
    second = 3.0 * mean - first - third
    return tuple(sorted((first, second, third), reverse=True))


def parse_dbfsi(text: str) -> JSONDict:
    """Read ASCII DBFSI histories without collapsing multiple surfaces."""
    if not isinstance(text, str):
        raise TypeError("dbfsi text must be a string")
    lines = text.splitlines()
    time_indices: list[tuple[int, float]] = []
    for index, line in enumerate(lines):
        match = re.search(rf"time\s*=\s*({NUMBER_PATTERN})", line, flags=re.IGNORECASE)
        if match:
            time_indices.append((index, _parse_number(match.group(1))))
    if len(time_indices) < 2:
        raise ValueError("dbfsi must contain at least two states")

    surface_states: dict[int, list[tuple[float, float, float, float, float]]] = {}
    expected_surface_ids: set[int] | None = None
    previous_time: float | None = None
    for state_index, (line_index, time_s) in enumerate(time_indices):
        if not math.isfinite(time_s) or time_s < 0.0:
            raise ValueError("dbfsi state time must be finite and non-negative")
        if previous_time is not None and time_s <= previous_time:
            raise ValueError("dbfsi state times must be strictly increasing")
        previous_time = time_s
        next_index = (
            time_indices[state_index + 1][0]
            if state_index + 1 < len(time_indices)
            else len(lines)
        )
        rows: dict[int, tuple[float, float, float, float]] = {}
        for data_line in lines[line_index + 1 : next_index]:
            row_match = re.match(r"^\s*([1-9][0-9]*)\s+(.*)$", data_line)
            if row_match is None:
                continue
            values = [
                _parse_number(value)
                for value in re.findall(NUMBER_PATTERN, row_match.group(2))
            ]
            if len(values) < 5:
                continue
            surface_id = int(row_match.group(1))
            pressure, fx, fy, fz = values[0], values[1], values[2], values[3]
            if not all(math.isfinite(value) for value in (pressure, fx, fy, fz)):
                raise ValueError("dbfsi values must be finite")
            if surface_id in rows:
                raise ValueError("dbfsi state contains a duplicate surface id")
            rows[surface_id] = (pressure, fx, fy, fz)
        if not rows:
            raise ValueError("dbfsi state is missing its surface data")
        surface_ids = set(rows)
        if expected_surface_ids is None:
            expected_surface_ids = surface_ids
        elif surface_ids != expected_surface_ids:
            raise ValueError("dbfsi surface ids must be consistent across states")
        for surface_id, values in rows.items():
            surface_states.setdefault(surface_id, []).append((time_s, *values))

    surfaces = [
        _dbfsi_surface_metrics(surface_id, states)
        for surface_id, states in sorted(surface_states.items())
    ]
    result: JSONDict = {
        "ok": True,
        "state_count": len(time_indices),
        "surface_count": len(surfaces),
        "surface_ids": [item["surface_id"] for item in surfaces],
        "surfaces": surfaces,
        "source_units": {
            "time": "s",
            "pressure": "Pa",
            "force": "N",
            "impulse": "N*s",
        },
    }
    if len(surfaces) == 1:
        result.update(
            {
                key: value
                for key, value in surfaces[0].items()
                if key != "surface_id"
            }
        )
    return result


def _dbfsi_surface_metrics(
    surface_id: int,
    states: list[tuple[float, float, float, float, float]],
) -> JSONDict:
    peak_pressure_state = max(states, key=lambda item: item[1])
    peak_force_state = max(states, key=lambda item: math.sqrt(item[2] ** 2 + item[3] ** 2 + item[4] ** 2))
    baseline = states[0]
    pressure_rises = [
        (state[0], state[1] - baseline[1])
        for state in states
    ]
    positive_pressure_history = [
        (time_s, max(pressure_rise, 0.0))
        for time_s, pressure_rise in pressure_rises
    ]
    force_deltas = [
        (
            state[0],
            state[2] - baseline[2],
            state[3] - baseline[3],
            state[4] - baseline[4],
        )
        for state in states
    ]
    peak_pressure_rise_state = max(pressure_rises, key=lambda item: item[1])
    peak_force_delta_state = max(
        force_deltas,
        key=lambda item: math.sqrt(item[1] ** 2 + item[2] ** 2 + item[3] ** 2),
    )
    impulse = [
        sum(
            (right[0] - left[0]) * (left[component] + right[component]) * 0.5
            for left, right in zip(force_deltas, force_deltas[1:])
        )
        for component in (1, 2, 3)
    ]
    positive_pressure_impulse = sum(
        0.5 * (left_rise + right_rise) * (right_time - left_time)
        for (left_time, left_rise), (right_time, right_rise) in zip(
            positive_pressure_history,
            positive_pressure_history[1:],
        )
    )
    pressure_threshold = max(float(peak_pressure_rise_state[1]) * 0.01, 0.0)
    positive_pressure_times = [
        time_s
        for time_s, pressure_rise in pressure_rises
        if pressure_rise > pressure_threshold
    ]
    pressure_duration = (
        max(positive_pressure_times) - min(positive_pressure_times)
        if len(positive_pressure_times) >= 2
        else 0.0
    )
    return {
        "surface_id": surface_id,
        "peak_coupled_surface_pressure_pa": peak_pressure_state[1],
        "peak_pressure_time_s": peak_pressure_state[0],
        "baseline_pressure_pa": baseline[1],
        "peak_pressure_rise_pa": peak_pressure_rise_state[1],
        "peak_pressure_rise_time_s": peak_pressure_rise_state[0],
        "positive_pressure_impulse_pa_s": positive_pressure_impulse,
        "positive_pressure_sample_count": len(positive_pressure_times),
        "positive_pressure_duration_s": pressure_duration,
        "pressure_arrival_time_s": (
            min(positive_pressure_times)
            if positive_pressure_times
            else None
        ),
        "peak_resultant_force_n": math.sqrt(
            peak_force_state[2] ** 2 + peak_force_state[3] ** 2 + peak_force_state[4] ** 2
        ),
        "peak_force_time_s": peak_force_state[0],
        "baseline_resultant_force_n": math.sqrt(
            baseline[2] ** 2 + baseline[3] ** 2 + baseline[4] ** 2
        ),
        "peak_force_rise_n": math.sqrt(
            peak_force_delta_state[1] ** 2
            + peak_force_delta_state[2] ** 2
            + peak_force_delta_state[3] ** 2
        ),
        "fsi_impulse_vector_n_s": {"x": impulse[0], "y": impulse[1], "z": impulse[2]},
        "fsi_impulse_magnitude_n_s": math.sqrt(sum(value * value for value in impulse)),
    }


def parse_ale_xy_table(text: str, quantity: str) -> JSONDict:
    """Parse a finite, increasing-time LS-DYNA ALE .xy table."""

    if not isinstance(text, str):
        raise TypeError("ALE xy text must be a string")
    rows: list[list[float]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(("#", "$", "*")):
            continue
        tokens = [item for item in re.split(r"[,;\s]+", line) if item]
        try:
            values = [_parse_number(token) for token in tokens]
        except ValueError:
            if not rows:
                continue
            raise ValueError(f"ALE xy line {line_number} contains non-numeric data") from None
        if len(values) < 2:
            if not rows:
                continue
            raise ValueError(f"ALE xy line {line_number} must contain time and at least one value")
        if not all(math.isfinite(value) for value in values):
            raise ValueError("ALE xy values must be finite")
        if rows and len(values) != len(rows[0]):
            raise ValueError("ALE xy rows must have a consistent column count")
        if rows and values[0] <= rows[-1][0]:
            raise ValueError("ALE xy time must be strictly increasing")
        rows.append(values)
    if len(rows) < 2:
        raise ValueError("ALE xy table must contain at least two numeric rows")
    series = []
    for column in range(1, len(rows[0])):
        values = [row[column] for row in rows]
        peak_index = max(range(len(values)), key=lambda index: abs(values[index]))
        initial = values[0]
        final = values[-1]
        series.append(
            {
                "series_index": column,
                "initial": initial,
                "final": final,
                "relative_change": None if initial == 0.0 else (final - initial) / abs(initial),
                "peak_absolute": abs(values[peak_index]),
                "peak_signed": values[peak_index],
                "peak_time_s": rows[peak_index][0],
            }
        )
    return {
        "ok": True,
        "quantity": quantity,
        "sample_count": len(rows),
        "series_count": len(series),
        "time_range_s": [rows[0][0], rows[-1][0]],
        "series": series,
    }


def parse_ale_material_balance(mass_text: str, volume_text: str) -> JSONDict:
    mass = parse_ale_xy_table(mass_text, "mass_kg")
    volume = parse_ale_xy_table(volume_text, "volume_m3")
    if mass["time_range_s"] != volume["time_range_s"]:
        raise ValueError("ALE mass and volume histories must cover the same time range")
    mass_changes = [abs(float(item["relative_change"])) for item in mass["series"] if item["relative_change"] is not None]
    volume_changes = [abs(float(item["relative_change"])) for item in volume["series"] if item["relative_change"] is not None]
    return {
        "ok": True,
        "mass": mass,
        "volume": volume,
        "maximum_absolute_relative_mass_change": max(mass_changes, default=None),
        "maximum_absolute_relative_volume_change": max(volume_changes, default=None),
        "interpretation": "Open boundaries may transport mass out of the finite ALE domain; review trends against analysis time and boundary flux.",
    }


def parse_ale_pressure_probes(text: str, probe_positions_m: list[float] | None = None) -> JSONDict:
    table = parse_ale_xy_table(text, "pressure_pa")
    if probe_positions_m is not None and len(probe_positions_m) != int(table["series_count"]):
        raise ValueError("probe_positions_m must match the pressure series count")
    probes: list[JSONDict] = []
    for index, series in enumerate(table["series"]):
        peak = float(series["peak_absolute"])
        probes.append(
            {
                **series,
                "probe_position_m": probe_positions_m[index] if probe_positions_m is not None else None,
                "arrival_threshold_pa": max(1.0, peak * 0.01),
            }
        )
    return {
        **table,
        "probes": probes,
        "global_peak_pressure_pa": max(float(item["peak_absolute"]) for item in probes),
        "arrival_definition": "first sample at or above 1% of each probe peak; compute from exported history when available",
    }


def parse_blstfor(data: bytes) -> JSONDict:
    """Read effective-pressure history from an LS-DYNA BLSTFOR database."""
    if not isinstance(data, bytes):
        raise TypeError("blstfor data must be bytes")
    endian, word_size, integer_code, float_code = _detect_blstfor_layout(data)
    integer_format = f"{endian}{integer_code}"
    float_format = f"{endian}{float_code}"

    def integer(word: int) -> int:
        return int(struct.unpack_from(integer_format, data, word * word_size)[0])

    def number(word: int) -> float:
        return float(struct.unpack_from(float_format, data, word * word_size)[0])

    file_type = integer(11)
    num_nodes = integer(16)
    global_value_count = integer(18)
    current_geometry_flag = integer(20)
    velocity_flag = integer(21)
    segment_count = integer(31)
    values_per_segment = integer(33)
    arbitrary_numbering_words = integer(39)
    if file_type != 6:
        raise ValueError("binary database is not a BLSTFOR file")
    if not 0 < num_nodes <= 100_000_000:
        raise ValueError("BLSTFOR node count is invalid")
    if not 0 < segment_count <= 100_000_000:
        raise ValueError("BLSTFOR segment count is invalid")
    if not 0 <= global_value_count <= 10_000:
        raise ValueError("BLSTFOR global variable count is invalid")
    if current_geometry_flag not in {0, 1} or velocity_flag not in {0, 1}:
        raise ValueError("BLSTFOR nodal data flags are unsupported")
    if values_per_segment not in {7, 16}:
        raise ValueError("BLSTFOR must contain 7 or 16 values per segment")
    if arbitrary_numbering_words < 0:
        raise ValueError("BLSTFOR arbitrary numbering length is invalid")

    geometry_words = 3 * num_nodes + 5 * segment_count
    first_state_word = 64 + geometry_words + arbitrary_numbering_words
    node_state_words = 3 * num_nodes * (current_geometry_flag + velocity_flag)
    state_words = 1 + global_value_count + node_state_words + segment_count * values_per_segment
    total_words = len(data) // word_size
    if first_state_word >= total_words or first_state_word + state_words > total_words:
        raise ValueError("BLSTFOR is truncated before its first state")

    states: list[tuple[float, list[float]]] = []
    state_word = first_state_word
    previous_time: float | None = None
    while state_word + state_words <= total_words:
        time_s = number(state_word)
        if math.isclose(time_s, -999999.0, rel_tol=0.0, abs_tol=0.5):
            break
        if not math.isfinite(time_s) or time_s < 0.0:
            raise ValueError("BLSTFOR state time must be finite and non-negative")
        if previous_time is not None and time_s <= previous_time:
            raise ValueError("BLSTFOR state times must be strictly increasing")
        pressure_word = state_word + 1 + global_value_count + node_state_words
        pressures = [number(pressure_word + index * values_per_segment) for index in range(segment_count)]
        if not all(math.isfinite(value) for value in pressures):
            raise ValueError("BLSTFOR pressure values must be finite")
        states.append((time_s, pressures))
        previous_time = time_s
        state_word += state_words

    if not states:
        raise ValueError("BLSTFOR contains no readable states")
    peak_state_index, peak_segment_index = max(
        (
            (state_index, segment_index)
            for state_index, (_, pressures) in enumerate(states)
            for segment_index in range(segment_count)
        ),
        key=lambda item: states[item[0]][1][item[1]],
    )
    history = [(time_s, pressures[peak_segment_index]) for time_s, pressures in states]
    positive_phase = _positive_phase_metrics(history)
    connectivity_word = 64 + 3 * num_nodes + peak_segment_index * 5
    segment_nodes = [integer(connectivity_word + offset) for offset in range(4)]
    peak_time_s, peak_pressure_pa = history[peak_state_index]
    return {
        "ok": True,
        "file_type": file_type,
        "word_size_bytes": word_size,
        "byte_order": "little" if endian == "<" else "big",
        "state_count": len(states),
        "node_count": num_nodes,
        "segment_count": segment_count,
        "values_per_segment": values_per_segment,
        "peak_segment_index": peak_segment_index + 1,
        "peak_segment_nodes": segment_nodes,
        "sampled_peak_pressure_pa": peak_pressure_pa,
        "sampled_peak_time_s": peak_time_s,
        "history_aggregation": "pressure history at the segment containing the sampled global peak",
        **positive_phase,
    }


def _detect_blstfor_layout(data: bytes) -> tuple[str, int, str, str]:
    for word_size, integer_code, float_code in ((4, "i", "f"), (8, "q", "d")):
        if len(data) < 64 * word_size or len(data) % word_size:
            continue
        for endian in ("<", ">"):
            file_type = struct.unpack_from(f"{endian}{integer_code}", data, 11 * word_size)[0]
            if file_type == 6:
                return endian, word_size, integer_code, float_code
    raise ValueError("BLSTFOR word size or byte order could not be identified")


def _positive_phase_metrics(history: list[tuple[float, float]]) -> JSONDict:
    positive = [index for index, (_, pressure) in enumerate(history) if pressure > 0.0]
    if not positive:
        return {
            "positive_phase_status": "unavailable",
            "positive_phase_quality": "unavailable",
            "positive_sample_count": 0,
            "quality_warnings": ["no positive effective-pressure sample was recorded"],
        }
    peak_index = max(positive, key=lambda index: history[index][1])
    start = peak_index
    while start > 0 and history[start - 1][1] > 0.0:
        start -= 1
    finish = peak_index
    while finish + 1 < len(history) and history[finish + 1][1] > 0.0:
        finish += 1
    warnings: list[str] = []
    if start == 0 or finish + 1 >= len(history):
        return {
            "positive_phase_status": "unavailable",
            "positive_phase_quality": "unavailable",
            "positive_sample_count": finish - start + 1,
            "quality_warnings": ["positive phase is not bracketed by non-positive samples"],
        }

    left = history[start - 1]
    first = history[start]
    last = history[finish]
    right = history[finish + 1]
    start_time = _zero_crossing_time(left, first)
    finish_time = _zero_crossing_time(last, right)
    points = [(start_time, 0.0), *history[start : finish + 1], (finish_time, 0.0)]
    impulse = sum(
        (right_point[0] - left_point[0]) * (left_point[1] + right_point[1]) * 0.5
        for left_point, right_point in zip(points, points[1:])
    )
    positive_count = finish - start + 1
    quality = "adequate" if positive_count >= 5 else "limited" if positive_count >= 2 else "coarse"
    if positive_count < 3:
        warnings.append("fewer than three positive samples; duration and impulse are coarse interpolated estimates")
    intervals = [right_item[0] - left_item[0] for left_item, right_item in zip(history, history[1:])]
    return {
        "positive_phase_status": "available",
        "positive_phase_quality": quality,
        "positive_duration_s": finish_time - start_time,
        "positive_impulse_pa_s": impulse,
        "positive_sample_count": positive_count,
        "minimum_state_interval_s": min(intervals) if intervals else None,
        "maximum_state_interval_s": max(intervals) if intervals else None,
        "quality_warnings": warnings,
    }


def _zero_crossing_time(left: tuple[float, float], right: tuple[float, float]) -> float:
    left_time, left_pressure = left
    right_time, right_pressure = right
    pressure_delta = right_pressure - left_pressure
    if pressure_delta == 0.0:
        return left_time
    fraction = -left_pressure / pressure_delta
    return left_time + max(0.0, min(1.0, fraction)) * (right_time - left_time)


def evaluate_solver_result(
    text: str,
    mode: str,
    *,
    expected_termination_time_s: float | None = None,
) -> JSONDict:
    if mode not in {"impact", "blast", "quasi_static", "initial_validation"}:
        raise ValueError("mode must be impact, blast, quasi_static, or initial_validation")
    parsed = parse_d3hsp(text)
    checks: list[JSONDict] = []

    def add(check_id: str, ok: bool, actual: object, limit: object | None = None) -> None:
        check: JSONDict = {"id": check_id, "ok": bool(ok), "actual": actual}
        if limit is not None:
            check["limit"] = limit
        checks.append(check)

    add("normal_termination", bool(parsed["terminated_normally"]), parsed["termination_marker"])
    add("finite_energies", bool(parsed["finite"]), parsed["finite"])

    internal_values = parsed["series"]["internal_energy"]
    finite_internal = [value for value in internal_values if math.isfinite(value)]
    internal_scale = max((abs(value) for value in finite_internal), default=0.0)
    negative_tolerance = max(1.0e-12, internal_scale * 1.0e-9)
    internal_nonnegative = bool(finite_internal) and len(finite_internal) == len(internal_values) and min(finite_internal) >= -negative_tolerance
    add(
        "internal_energy_nonnegative",
        internal_nonnegative,
        min(finite_internal) if finite_internal else None,
        {"minimum": -negative_tolerance},
    )

    hourglass_values = parsed["series"]["hourglass_energy"]
    max_hourglass = float(parsed["max_abs"].get("hourglass_energy", 0.0))
    if mode in {"impact", "blast", "initial_validation"}:
        energy_scale = float(parsed["max_abs"].get("total_energy", 0.0))
        if energy_scale <= 0.0:
            energy_scale = float(parsed["max_abs"].get("kinetic_energy", 0.0)) + internal_scale
    else:
        energy_scale = internal_scale
    if mode == "initial_validation" and not hourglass_values:
        hourglass_ratio: float | None = None
        add("hourglass_energy_ratio", False, None, {"maximum": 0.1})
    else:
        hourglass_ratio = _safe_ratio(max_hourglass, energy_scale)
        add(
            "hourglass_energy_ratio",
            math.isfinite(hourglass_ratio) and hourglass_ratio <= 0.1,
            hourglass_ratio,
            {"maximum": 0.1},
        )

    metrics: JSONDict = {"hourglass_ratio": hourglass_ratio}
    if mode in {"impact", "blast"}:
        final_ratio = parsed["final"].get("total_initial_ratio")
        ratio_ok = isinstance(final_ratio, float) and math.isfinite(final_ratio) and 0.9 <= final_ratio <= 1.1
        add(f"{mode}_total_energy_ratio", ratio_ok, final_ratio, {"minimum": 0.9, "maximum": 1.1})
        metrics["total_initial_ratio"] = final_ratio
        if mode == "blast" and parsed["blast_peaks"]:
            peak = max(parsed["blast_peaks"], key=lambda item: float(item["peak_pressure_pa"]))
            metrics.update(
                {
                    "peak_blast_pressure_pa": peak["peak_pressure_pa"],
                    "peak_blast_pressure_time_s": peak["peak_time_s"],
                    "peak_blast_id": peak["blast_id"],
                }
            )
    elif mode == "quasi_static":
        final_kinetic = parsed["final"].get("kinetic_energy")
        final_internal = parsed["final"].get("internal_energy")
        kinetic_internal_ratio = (
            _safe_ratio(abs(float(final_kinetic)), abs(float(final_internal)))
            if isinstance(final_kinetic, float) and isinstance(final_internal, float)
            else math.inf
        )
        add(
            "quasi_static_kinetic_internal_ratio",
            math.isfinite(kinetic_internal_ratio) and kinetic_internal_ratio <= 0.1,
            kinetic_internal_ratio,
            {"maximum": 0.1},
        )
        metrics["kinetic_internal_ratio"] = kinetic_internal_ratio
    elif mode == "initial_validation":
        expected = (
            float(expected_termination_time_s)
            if isinstance(expected_termination_time_s, (int, float))
            and not isinstance(expected_termination_time_s, bool)
            and math.isfinite(float(expected_termination_time_s))
            and float(expected_termination_time_s) > 0.0
            else None
        )
        actual = parsed.get("final_problem_time_s")
        tolerance = max(1.0e-12, expected * 1.0e-6) if expected is not None else 0.0
        reached = bool(
            expected is not None
            and isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and math.isfinite(float(actual))
            and float(actual) >= expected - tolerance
            and parsed.get("termination_time_reached") is True
        )
        add(
            "termination_time_reached",
            reached,
            actual,
            {
                "target": expected,
                "minimum": expected - tolerance if expected is not None else None,
                "explicit_marker_required": True,
            },
        )
        metrics["expected_termination_time_s"] = expected
        metrics["final_problem_time_s"] = actual

    return {
        "ok": all(check["ok"] for check in checks),
        "mode": mode,
        "checks": checks,
        "metrics": metrics,
        "parsed": parsed,
    }


def _parse_number(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "e"))


def _safe_ratio(numerator: float, denominator: float) -> float:
    if not math.isfinite(numerator) or not math.isfinite(denominator):
        return math.inf
    if denominator <= 1.0e-30:
        return 0.0 if numerator <= 1.0e-30 else math.inf
    return numerator / denominator
