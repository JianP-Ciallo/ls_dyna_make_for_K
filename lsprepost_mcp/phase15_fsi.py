from __future__ import annotations

from collections import Counter, defaultdict
import math
from pathlib import Path
import re
import statistics

from .config import JSONDict
from .solver_results import (
    NUMBER_PATTERN,
    parse_d3hsp,
    parse_dbfsi,
    parse_fsi_interfaces,
    parse_nodout,
)


FSI_SURFACE_NAMES = ("charge_bottom", "borehole_wall", "concrete_top")
FSI_EXPECTED_NORMALS = {
    "charge_bottom": (0.0, 1.0),
    "borehole_wall": (-1.0, 0.0),
    "concrete_top": (0.0, 1.0),
}
PHASE15_STRESS_RESPONSE_FLOOR_PA = 1.0e6
PHASE15_COUPLING_PRESSURE_FLOOR_PA = 1.0e6
PHASE15_DISPLACEMENT_FLOOR_M = 1.0e-9
PHASE15_DURABLE_RESPONSE_SAMPLES = 2
ELOUT_STATE_PATTERN = re.compile(
    rf"t\s*i\s*m\s*e\s+s\s*t\s*e\s*p\s+(\d+).*?"
    rf"a\s*t\s+t\s*i\s*m\s*e\s+({NUMBER_PATTERN})",
    flags=re.IGNORECASE,
)
ELOUT_ELEMENT_PATTERN = re.compile(r"^\s*(\d+)-\s+(\d+)\s*$")
ELOUT_STRESS_PATTERN = re.compile(r"^\s*\d+-\s+\d+\s+\S+\s+(.*)$")


def build_phase15_fsi_surfaces(
    concrete_elements: list[list[int]],
    node_coordinates: dict[int, tuple[float, float, float]],
    geometry: JSONDict,
    *,
    mesh_size_m: float,
) -> JSONDict:
    tolerance = _tolerance(mesh_size_m)
    exterior_edges = {
        edge
        for edge, count in _concrete_edge_counts(concrete_elements).items()
        if count == 1
    }
    surfaces: dict[str, list[list[int]]] = {name: [] for name in FSI_SURFACE_NAMES}
    for first, second in sorted(exterior_edges):
        if first not in node_coordinates or second not in node_coordinates:
            continue
        name = _classify_surface(
            node_coordinates[first],
            node_coordinates[second],
            geometry,
            tolerance,
        )
        if name is None:
            continue
        surfaces[name].append(
            list(
                _orient_segment(
                    first,
                    second,
                    node_coordinates,
                    FSI_EXPECTED_NORMALS[name],
                )
            )
        )

    for name in FSI_SURFACE_NAMES:
        surfaces[name].sort(
            key=lambda segment: _segment_midpoint(segment, node_coordinates)
        )
    all_segments = [
        list(segment)
        for name in FSI_SURFACE_NAMES
        for segment in surfaces[name]
    ]
    return {
        **surfaces,
        "all_segments": all_segments,
        "counts": {name: len(surfaces[name]) for name in FSI_SURFACE_NAMES},
        "total_count": len(all_segments),
        "expected_normals_rz": {
            name: list(FSI_EXPECTED_NORMALS[name]) for name in FSI_SURFACE_NAMES
        },
        "coordinate_ranges_m": {
            name: _coordinate_range(surfaces[name], node_coordinates)
            for name in FSI_SURFACE_NAMES
        },
    }


def validate_phase15_fsi_surfaces(
    surfaces: JSONDict,
    concrete_elements: list[list[int]],
    node_coordinates: dict[int, tuple[float, float, float]],
    geometry: JSONDict,
    *,
    mesh_size_m: float,
) -> list[JSONDict]:
    issues: list[JSONDict] = []
    tolerance = _tolerance(mesh_size_m)
    edge_counts = _concrete_edge_counts(concrete_elements)
    seen: set[tuple[int, int]] = set()

    for name in FSI_SURFACE_NAMES:
        raw_segments = surfaces.get(name)
        if not isinstance(raw_segments, list) or not raw_segments:
            issues.append({"id": "fsi_surface_missing", "surface": name})
            continue

        valid_for_connectivity: list[tuple[int, int]] = []
        for index, raw_segment in enumerate(raw_segments):
            if (
                not isinstance(raw_segment, (list, tuple))
                or len(raw_segment) != 2
                or any(isinstance(value, bool) or not isinstance(value, int) for value in raw_segment)
            ):
                issues.append(
                    {
                        "id": "fsi_segment_invalid_node",
                        "surface": name,
                        "segment_index": index,
                    }
                )
                continue
            first, second = int(raw_segment[0]), int(raw_segment[1])
            if first == second or first not in node_coordinates or second not in node_coordinates:
                issues.append(
                    {
                        "id": "fsi_segment_invalid_node",
                        "surface": name,
                        "segment_index": index,
                    }
                )
                continue

            edge = tuple(sorted((first, second)))
            if edge in seen:
                issues.append(
                    {
                        "id": "fsi_segment_duplicate",
                        "surface": name,
                        "segment": [first, second],
                    }
                )
            else:
                seen.add(edge)
            if edge_counts.get(edge) != 1:
                issues.append(
                    {
                        "id": "fsi_segment_not_exterior",
                        "surface": name,
                        "segment": [first, second],
                    }
                )
                continue
            if (
                _classify_surface(
                    node_coordinates[first],
                    node_coordinates[second],
                    geometry,
                    tolerance,
                )
                != name
            ):
                issues.append(
                    {
                        "id": "fsi_surface_geometry_mismatch",
                        "surface": name,
                        "segment": [first, second],
                    }
                )
            if not _normal_matches(
                first,
                second,
                node_coordinates,
                FSI_EXPECTED_NORMALS[name],
            ):
                issues.append(
                    {
                        "id": "fsi_surface_normal_mismatch",
                        "surface": name,
                        "segment": [first, second],
                    }
                )
            valid_for_connectivity.append((first, second))

        if valid_for_connectivity and not _is_connected_chain(valid_for_connectivity):
            issues.append({"id": "fsi_surface_disconnected", "surface": name})

    expected_all = [
        tuple(segment)
        for name in FSI_SURFACE_NAMES
        for segment in surfaces.get(name, [])
        if isinstance(segment, (list, tuple)) and len(segment) == 2
    ]
    raw_all = surfaces.get("all_segments")
    if not isinstance(raw_all, list) or Counter(map(tuple, raw_all)) != Counter(expected_all):
        issues.append({"id": "fsi_all_segments_inconsistent"})
    return issues


def evaluate_phase15_fsi_ale_overlap(
    surfaces: JSONDict,
    ale_elements: list[list[int]],
    node_coordinates: dict[int, tuple[float, float, float]],
    *,
    mesh_size_m: float,
    overlap_layers: int,
) -> JSONDict:
    mesh_size = _finite_number(mesh_size_m, "mesh_size_m")
    if mesh_size <= 0.0:
        raise ValueError("mesh_size_m must be positive")
    if (
        isinstance(overlap_layers, bool)
        or not isinstance(overlap_layers, int)
        or not 1 <= overlap_layers <= 3
    ):
        raise ValueError("overlap_layers must be an integer from 1 to 3")

    bounds: list[tuple[float, float, float, float]] = []
    for element in ale_elements:
        if len(element) < 6:
            continue
        try:
            points = [node_coordinates[int(value)] for value in element[2:6]]
        except KeyError:
            continue
        radii = [float(point[0]) for point in points]
        axial = [float(point[1]) for point in points]
        bounds.append((min(radii), max(radii), min(axial), max(axial)))

    tolerance = max(1.0e-12, mesh_size * 1.0e-8)

    def covered(radius: float, axial: float) -> bool:
        return any(
            minimum_r - tolerance <= radius <= maximum_r + tolerance
            and minimum_z - tolerance <= axial <= maximum_z + tolerance
            for minimum_r, maximum_r, minimum_z, maximum_z in bounds
        )

    surface_results: dict[str, JSONDict] = {}
    for name in FSI_SURFACE_NAMES:
        expected_normal = FSI_EXPECTED_NORMALS[name]
        segments = surfaces.get(name, [])
        two_sided_count = 0
        for raw_segment in segments:
            if not isinstance(raw_segment, (list, tuple)) or len(raw_segment) != 2:
                continue
            try:
                first = node_coordinates[int(raw_segment[0])]
                second = node_coordinates[int(raw_segment[1])]
            except KeyError:
                continue
            midpoint_r = 0.5 * (float(first[0]) + float(second[0]))
            midpoint_z = 0.5 * (float(first[1]) + float(second[1]))
            fluid_covered = covered(
                midpoint_r + 0.5 * mesh_size * expected_normal[0],
                midpoint_z + 0.5 * mesh_size * expected_normal[1],
            )
            structure_layers_covered = all(
                covered(
                    midpoint_r
                    - (layer - 0.5) * mesh_size * expected_normal[0],
                    midpoint_z
                    - (layer - 0.5) * mesh_size * expected_normal[1],
                )
                for layer in range(1, overlap_layers + 1)
            )
            if fluid_covered and structure_layers_covered:
                two_sided_count += 1
        segment_count = len(segments) if isinstance(segments, list) else 0
        surface_results[name] = {
            "segment_count": segment_count,
            "two_sided_segment_count": two_sided_count,
            "all_two_sided": segment_count > 0 and two_sided_count == segment_count,
        }

    return {
        "overlap_layers": overlap_layers,
        "mesh_size_m": mesh_size,
        "overlap_depth_m": overlap_layers * mesh_size,
        "surfaces": surface_results,
        "all_two_sided": all(
            bool(surface["all_two_sided"]) for surface in surface_results.values()
        ),
    }


def parse_phase15_elout(
    path: Path,
    concrete_element_ids: set[int],
    *,
    material_id: int = 3,
) -> JSONDict:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Phase 15 elout not found: {source}")
    if not concrete_element_ids:
        raise ValueError("concrete_element_ids must not be empty")
    if isinstance(material_id, bool) or not isinstance(material_id, int) or material_id <= 0:
        raise ValueError("material_id must be a positive integer")
    material_id_filter = material_id

    current_state: int | None = None
    current_time: float | None = None
    current_element: int | None = None
    state_keys: set[tuple[int, float]] = set()
    baselines: dict[int, tuple[float, ...]] = {}
    sample_count = 0
    peak_pressure: JSONDict | None = None
    peak_principal: JSONDict | None = None
    peak_damage: JSONDict | None = None
    probe_responses: dict[int, JSONDict] = {}

    with source.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            state_match = ELOUT_STATE_PATTERN.search(line)
            if state_match:
                current_state = int(state_match.group(1))
                current_time = _finite_number(state_match.group(2), "elout state time")
                if current_time < 0.0:
                    raise ValueError("elout state time must be non-negative")
                current_element = None
                continue

            element_match = ELOUT_ELEMENT_PATTERN.match(line)
            if element_match:
                element_id = int(element_match.group(1))
                element_material_id = int(element_match.group(2))
                current_element = (
                    element_id
                    if element_material_id == material_id_filter
                    and element_id in concrete_element_ids
                    else None
                )
                continue

            if current_element is None or current_state is None or current_time is None:
                continue
            stress_match = ELOUT_STRESS_PATTERN.match(line)
            if not stress_match:
                continue
            raw_values = stress_match.group(1).split()
            if len(raw_values) < 7:
                raise ValueError(
                    f"elout scaled damage is missing at line {line_number}"
                )
            values = [
                _finite_number(value, f"elout value at line {line_number}")
                for value in raw_values[:7]
            ]
            stress = tuple(values[:6])
            scaled_damage = values[6]
            baseline = baselines.setdefault(current_element, stress)
            response = tuple(value - initial for value, initial in zip(stress, baseline))
            pressure = -(response[0] + response[1] + response[2]) / 3.0
            principal = _axisymmetric_principal_stresses(response)
            principal_peak = max(principal, key=abs)
            sample_count += 1
            state_keys.add((current_state, current_time))
            probe_response = probe_responses.setdefault(
                current_element,
                {
                    "element_id": current_element,
                    "sample_count": 0,
                    "peak_hydrostatic_pressure_response_pa": 0.0,
                    "peak_principal_stress_response_pa": 0.0,
                    "first_principal_stress_arrival": None,
                    "principal_response_series": [],
                },
            )
            probe_response["sample_count"] = int(probe_response["sample_count"]) + 1
            probe_response["peak_hydrostatic_pressure_response_pa"] = max(
                float(probe_response["peak_hydrostatic_pressure_response_pa"]),
                abs(pressure),
            )
            probe_response["peak_principal_stress_response_pa"] = max(
                float(probe_response["peak_principal_stress_response_pa"]),
                abs(principal_peak),
            )
            probe_response["principal_response_series"].append(
                {
                    "time_s": current_time,
                    "time_step": current_state,
                    "value_pa": principal_peak,
                    "absolute_value_pa": abs(principal_peak),
                }
            )
            if (
                probe_response["first_principal_stress_arrival"] is None
                and abs(principal_peak) > PHASE15_STRESS_RESPONSE_FLOOR_PA
            ):
                probe_response["first_principal_stress_arrival"] = {
                    "time_s": current_time,
                    "time_step": current_state,
                    "value_pa": principal_peak,
                    "absolute_value_pa": abs(principal_peak),
                }

            pressure_candidate = {
                "value_pa": pressure,
                "absolute_value_pa": abs(pressure),
                "element_id": current_element,
                "time_step": current_state,
                "time_s": current_time,
            }
            if (
                peak_pressure is None
                or float(pressure_candidate["absolute_value_pa"])
                > float(peak_pressure["absolute_value_pa"])
            ):
                peak_pressure = pressure_candidate

            principal_candidate = {
                "value_pa": principal_peak,
                "absolute_value_pa": abs(principal_peak),
                "principal_stresses_pa": list(principal),
                "element_id": current_element,
                "time_step": current_state,
                "time_s": current_time,
            }
            if (
                peak_principal is None
                or float(principal_candidate["absolute_value_pa"])
                > float(peak_principal["absolute_value_pa"])
            ):
                peak_principal = principal_candidate

            damage_candidate = {
                "value": scaled_damage,
                "element_id": current_element,
                "time_step": current_state,
                "time_s": current_time,
            }
            if peak_damage is None or scaled_damage > float(peak_damage["value"]):
                peak_damage = damage_candidate
            current_element = None

    if sample_count == 0 or peak_pressure is None or peak_principal is None:
        raise ValueError("elout contains no requested concrete probe states")
    if peak_damage is None:
        raise ValueError("elout scaled damage is missing")
    for probe_response in probe_responses.values():
        durable = _durable_response(
            probe_response["principal_response_series"],
            value_key="value_pa",
            floor=PHASE15_STRESS_RESPONSE_FLOOR_PA,
        )
        probe_response["durable_principal_stress_arrival"] = durable["arrival"]
        probe_response["response_threshold_pa"] = durable["threshold"]
        probe_response["consecutive_response_samples"] = durable[
            "consecutive_response_samples"
        ]
    return {
        "ok": True,
        "source": str(source),
        "state_count": len(state_keys),
        "sample_count": sample_count,
        "probe_element_count": len(baselines),
        "peak_hydrostatic_pressure_response_pa": float(
            peak_pressure["absolute_value_pa"]
        ),
        "peak_hydrostatic_pressure": peak_pressure,
        "peak_principal_stress_response_pa": float(
            peak_principal["absolute_value_pa"]
        ),
        "peak_principal_stress": peak_principal,
        "kc_scaled_damage_readable": True,
        "peak_kc_scaled_damage": float(peak_damage["value"]),
        "peak_kc_scaled_damage_state": peak_damage,
        "probe_responses": [
            probe_responses[element_id]
            for element_id in sorted(probe_responses)
        ],
    }


def parse_phase15_ale_elout(
    path: Path,
    probe_metadata: list[JSONDict],
) -> JSONDict:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Phase 15 elout not found: {source}")
    expected_ids = ("TNT_NEAR", "AIR_MID_GAP", "AIR_INTERFACE")
    metadata_by_id = {
        str(probe.get("id")): probe
        for probe in probe_metadata
        if isinstance(probe, dict)
    }
    missing_ids = [probe_id for probe_id in expected_ids if probe_id not in metadata_by_id]
    if missing_ids:
        raise ValueError(
            "Phase 15 conforming air-gap ALE probes are missing: "
            + ", ".join(missing_ids)
        )
    element_to_probe: dict[int, str] = {}
    for probe_id in expected_ids:
        element_id = metadata_by_id[probe_id].get("element_id")
        if (
            not isinstance(element_id, int)
            or isinstance(element_id, bool)
            or element_id <= 0
        ):
            raise ValueError(f"{probe_id} ALE probe element_id must be positive")
        if element_id in element_to_probe:
            raise ValueError("Phase 15 ALE probes must use distinct elements")
        element_to_probe[element_id] = probe_id

    current_state: int | None = None
    current_time: float | None = None
    current_probe: str | None = None
    samples: dict[str, list[JSONDict]] = {
        probe_id: [] for probe_id in expected_ids
    }
    with source.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            state_match = ELOUT_STATE_PATTERN.search(line)
            if state_match:
                current_state = int(state_match.group(1))
                current_time = _finite_number(
                    state_match.group(2),
                    "elout ALE state time",
                )
                if current_time < 0.0:
                    raise ValueError("elout ALE state time must be non-negative")
                current_probe = None
                continue
            element_match = ELOUT_ELEMENT_PATTERN.match(line)
            if element_match:
                element_id = int(element_match.group(1))
                material_id = int(element_match.group(2))
                current_probe = (
                    element_to_probe.get(element_id)
                    if material_id == 1
                    else None
                )
                continue
            if current_probe is None or current_state is None or current_time is None:
                continue
            stress_match = ELOUT_STRESS_PATTERN.match(line)
            if not stress_match:
                continue
            raw_values = stress_match.group(1).split()
            if len(raw_values) < 6:
                raise ValueError(
                    f"elout ALE stress values are missing at line {line_number}"
                )
            stress = [
                _finite_number(value, f"elout ALE value at line {line_number}")
                for value in raw_values[:6]
            ]
            pressure = -(stress[0] + stress[1] + stress[2]) / 3.0
            samples[current_probe].append(
                {
                    "time_s": current_time,
                    "time_step": current_state,
                    "value_pa": pressure,
                }
            )
            current_probe = None

    probe_responses: list[JSONDict] = []
    for probe_id in expected_ids:
        series = samples[probe_id]
        if len(series) < PHASE15_DURABLE_RESPONSE_SAMPLES:
            raise ValueError(
                f"elout contains insufficient ALE states for probe {probe_id}"
            )
        durable = _durable_response(
            series,
            value_key="value_pa",
            floor=PHASE15_COUPLING_PRESSURE_FLOOR_PA,
        )
        arrival = durable["arrival"]
        peak = max(
            (
                {
                    **sample,
                    "response_pa": abs(
                        float(sample["value_pa"]) - float(durable["baseline"])
                    ),
                }
                for sample in series
            ),
            key=lambda sample: float(sample["response_pa"]),
        )
        probe_responses.append(
            {
                "probe_id": probe_id,
                "element_id": int(metadata_by_id[probe_id]["element_id"]),
                "sample_count": len(series),
                "baseline_pressure_pa": durable["baseline"],
                "noise_pa": durable["noise"],
                "response_threshold_pa": durable["threshold"],
                "peak_pressure_response_pa": peak["response_pa"],
                "peak_time_s": peak["time_s"],
                "durable_arrival_time_s": (
                    arrival["time_s"] if isinstance(arrival, dict) else None
                ),
                "durable_arrival_time_step": (
                    arrival["time_step"] if isinstance(arrival, dict) else None
                ),
                "consecutive_response_samples": durable[
                    "consecutive_response_samples"
                ],
            }
        )

    arrival_times = [
        response["durable_arrival_time_s"] for response in probe_responses
    ]
    all_arrived = all(_is_finite_number(value) for value in arrival_times)
    ordered = bool(
        all_arrived
        and all(
            float(second) >= float(first)
            for first, second in zip(arrival_times, arrival_times[1:])
        )
        and float(arrival_times[-1]) > float(arrival_times[0])
    )
    if not all_arrived:
        reason = "durable_pressure_response_did_not_reach_every_ale_probe"
    elif not ordered:
        reason = "ale_pressure_arrivals_are_not_ordered"
    else:
        reason = None
    return {
        "verified": ordered,
        "source": str(source),
        "probe_responses": probe_responses,
        "reason": reason,
    }


def evaluate_phase15_wave_transfer(
    run_dir: Path,
    concrete_element_ids: set[int],
    *,
    probe_metadata: list[JSONDict] | None = None,
    ale_probe_metadata: list[JSONDict] | None = None,
    history_output_dt_s: float | None = None,
    coupling_mode: str = "immersed_clis",
) -> JSONDict:
    if coupling_mode not in {
        "immersed_clis",
        "conforming_shared_nodes",
        "conforming_air_gap",
    }:
        raise ValueError(f"Unsupported Phase 15 coupling mode: {coupling_mode}")
    directory = Path(run_dir)
    checks: list[JSONDict] = []
    d3hsp_path = _first_output(directory, "d3hsp")
    elout_path = _first_output(directory, "elout")
    dbfsi_path = _first_output(directory, "dbfsi")

    d3hsp_text = ""
    termination = {"terminated_normally": False}
    fsi = {
        "interface_count": 0,
        "interfaces": [],
        "total_slave_segment_count": 0,
        "all_nonempty": False,
    }
    if d3hsp_path is not None:
        d3hsp_text = d3hsp_path.read_text(encoding="utf-8", errors="replace")
        termination = parse_d3hsp(d3hsp_text)
        fsi = parse_fsi_interfaces(d3hsp_text)
    checks.append(
        {
            "id": "normal_termination",
            "ok": bool(termination.get("terminated_normally")),
            "actual": termination.get("termination_marker", "missing"),
        }
    )
    if coupling_mode == "conforming_air_gap":
        finite_energy = bool(termination.get("finite"))
        negative_volume_found = bool(
            re.search(r"negative\s+(?:volume|jacobian)", d3hsp_text, re.IGNORECASE)
        )
        checks.extend(
            [
                {
                    "id": "solver_energies_finite",
                    "ok": finite_energy,
                    "actual": finite_energy,
                },
                {
                    "id": "negative_volume_absent",
                    "ok": not negative_volume_found,
                    "actual": negative_volume_found,
                },
            ]
        )
    if coupling_mode == "immersed_clis":
        checks.extend(
            [
            {
                "id": "fsi_interfaces_present",
                "ok": int(fsi["interface_count"]) > 0,
                "actual": int(fsi["interface_count"]),
            },
            {
                "id": "fsi_slave_segments_nonzero",
                "ok": bool(fsi["all_nonempty"])
                and int(fsi["total_slave_segment_count"]) > 0,
                "actual": int(fsi["total_slave_segment_count"]),
            },
            ]
        )

    coupling: JSONDict = {
        "ok": False,
        "peak_coupled_surface_pressure_pa": None,
        "error": (
            "dbfsi output is missing"
            if coupling_mode == "immersed_clis"
            else "not_applicable_for_conforming_shared_nodes"
        ),
    }
    if coupling_mode == "immersed_clis" and dbfsi_path is not None:
        try:
            coupling = parse_dbfsi(
                dbfsi_path.read_text(encoding="utf-8", errors="replace")
            )
            coupling["ok"] = True
            coupling["error"] = None
        except (OSError, TypeError, ValueError) as exc:
            coupling["error"] = str(exc)
    if coupling_mode == "immersed_clis":
        coupling_pressure = coupling.get("peak_coupled_surface_pressure_pa")
        coupling_pressure_finite = _is_finite_number(coupling_pressure)
        checks.append(
            {
                "id": "fsi_coupling_pressure_response",
                "ok": coupling_pressure_finite
                and float(coupling_pressure) > PHASE15_COUPLING_PRESSURE_FLOOR_PA,
                "actual_pa": coupling_pressure,
                "minimum_exclusive_pa": PHASE15_COUPLING_PRESSURE_FLOOR_PA,
                "error": coupling.get("error"),
            }
        )

    response: JSONDict = {
        "ok": False,
        "peak_hydrostatic_pressure_response_pa": None,
        "peak_principal_stress_response_pa": None,
        "kc_scaled_damage_readable": False,
        "peak_kc_scaled_damage": None,
    }
    response_error: str | None = None
    if elout_path is not None:
        try:
            response = parse_phase15_elout(elout_path, concrete_element_ids)
        except (OSError, ValueError) as exc:
            response_error = str(exc)
    else:
        response_error = "elout output is missing"

    pressure_peak = response.get("peak_hydrostatic_pressure_response_pa")
    principal_peak = response.get("peak_principal_stress_response_pa")
    damage_peak = response.get("peak_kc_scaled_damage")
    pressure_finite = _is_finite_number(pressure_peak)
    principal_finite = _is_finite_number(principal_peak)
    damage_finite = _is_finite_number(damage_peak)
    checks.extend(
        [
            {
                "id": "concrete_probe_states_present",
                "ok": int(response.get("sample_count", 0)) > 0,
                "actual": int(response.get("sample_count", 0)),
                "error": response_error,
            },
            {
                "id": "concrete_stress_values_finite",
                "ok": pressure_finite and principal_finite,
            },
            {
                "id": "concrete_hydrostatic_pressure_response",
                "ok": pressure_finite
                and float(pressure_peak) > PHASE15_STRESS_RESPONSE_FLOOR_PA,
                "actual_pa": pressure_peak,
                "minimum_exclusive_pa": PHASE15_STRESS_RESPONSE_FLOOR_PA,
            },
            {
                "id": "concrete_principal_stress_response",
                "ok": principal_finite
                and float(principal_peak) > PHASE15_STRESS_RESPONSE_FLOOR_PA,
                "actual_pa": principal_peak,
                "minimum_exclusive_pa": PHASE15_STRESS_RESPONSE_FLOOR_PA,
            },
            {
                "id": "kc_scaled_damage_readable",
                "ok": bool(response.get("kc_scaled_damage_readable")),
            },
            {
                "id": "kc_scaled_damage_finite",
                "ok": damage_finite,
                "actual": damage_peak,
            },
        ]
    )
    propagation: JSONDict = {
        "verified": False,
        "threshold_pa": PHASE15_STRESS_RESPONSE_FLOOR_PA,
        "arrivals": [],
        "apparent_velocities_m_per_s": [],
        "reason": "probe_metadata_not_provided",
    }
    if probe_metadata is not None:
        propagation = _evaluate_principal_wave_propagation(
            response,
            probe_metadata,
            require_durable=coupling_mode == "conforming_air_gap",
        )
        checks.append(
            {
                "id": "concrete_principal_wave_propagation",
                "ok": bool(propagation["verified"]),
                "actual": propagation,
            }
        )
    ale_response: JSONDict = {
        "verified": False,
        "probe_responses": [],
        "reason": "not_applicable",
    }
    transfer_evidence: JSONDict = {
        "verified": False,
        "arrivals": [],
        "reason": "not_applicable",
    }
    nodout: JSONDict = {"ok": False}
    if coupling_mode == "conforming_air_gap":
        ale_error: str | None = None
        if ale_probe_metadata is None:
            ale_error = "Phase 15 ALE probe metadata is missing"
        elif elout_path is None:
            ale_error = "elout output is missing"
        else:
            try:
                ale_response = parse_phase15_ale_elout(
                    elout_path,
                    ale_probe_metadata,
                )
            except (OSError, ValueError) as exc:
                ale_error = str(exc)
        checks.extend(
            [
                {
                    "id": "ale_air_gap_probe_states_present",
                    "ok": bool(ale_response.get("probe_responses")),
                    "actual": len(ale_response.get("probe_responses", [])),
                    "error": ale_error,
                },
                {
                    "id": "ale_air_gap_pressure_progression",
                    "ok": bool(ale_response.get("verified")),
                    "actual": ale_response,
                },
            ]
        )
        transfer_evidence = _evaluate_air_gap_transfer(
            ale_response,
            response,
            probe_metadata or [],
            history_output_dt_s,
        )
        checks.append(
            {
                "id": "conforming_interface_transfer",
                "ok": bool(transfer_evidence["verified"]),
                "actual": transfer_evidence,
            }
        )

        nodout_path = _first_output(directory, "nodout")
        nodout_error: str | None = None
        if nodout_path is None:
            nodout_error = "nodout output is missing"
        else:
            try:
                nodout = parse_nodout(
                    nodout_path.read_text(encoding="utf-8", errors="replace")
                )
            except (OSError, ValueError) as exc:
                nodout_error = str(exc)
        interface_arrival = transfer_evidence.get("concrete_interface_arrival_time_s")
        peak_time = nodout.get("peak_time_s")
        effective_displacement = nodout.get("effective_peak_displacement_m")
        output_dt_valid = (
            _is_finite_number(history_output_dt_s)
            and float(history_output_dt_s) > 0.0
        )
        displacement_after_load = bool(
            nodout.get("ok")
            and int(nodout.get("state_count", 0)) >= 2
            and _is_finite_number(effective_displacement)
            and float(effective_displacement) > PHASE15_DISPLACEMENT_FLOOR_M
            and _is_finite_number(peak_time)
            and _is_finite_number(interface_arrival)
            and output_dt_valid
            and float(peak_time)
            >= float(interface_arrival) - float(history_output_dt_s)
        )
        checks.append(
            {
                "id": "concrete_displacement_after_interface_load",
                "ok": displacement_after_load,
                "actual": {
                    "effective_peak_displacement_m": effective_displacement,
                    "peak_time_s": peak_time,
                    "concrete_interface_arrival_time_s": interface_arrival,
                    "history_output_dt_s": history_output_dt_s,
                },
                "minimum_displacement_exclusive_m": PHASE15_DISPLACEMENT_FLOOR_M,
                "error": nodout_error,
            }
        )
    required_ok = all(bool(check["ok"]) for check in checks)
    return {
        "wave_transfer_verified": required_ok,
        "coupling_mode": coupling_mode,
        "checks": checks,
        "fsi": fsi,
        "fsi_coupling": coupling,
        "concrete_response": response,
        "concrete_wave_propagation": propagation,
        "ale_air_gap_response": ale_response,
        "transfer_evidence": transfer_evidence,
        "nodout": nodout,
        "kc_scaled_damage": {
            "readable": bool(response.get("kc_scaled_damage_readable")),
            "finite": damage_finite,
            "peak": damage_peak,
            "positive": damage_finite and float(damage_peak) > 0.0,
        },
        "evidence_files": {
            "d3hsp": str(d3hsp_path) if d3hsp_path is not None else None,
            "elout": str(elout_path) if elout_path is not None else None,
            "dbfsi": str(dbfsi_path) if dbfsi_path is not None else None,
        },
    }


def _evaluate_principal_wave_propagation(
    response: JSONDict,
    probe_metadata: list[JSONDict],
    *,
    require_durable: bool = False,
) -> JSONDict:
    response_by_element = {
        int(item["element_id"]): item
        for item in response.get("probe_responses", [])
        if isinstance(item, dict)
        and isinstance(item.get("element_id"), int)
        and not isinstance(item.get("element_id"), bool)
    }
    path_probes: list[tuple[int, float, int]] = []
    for probe in probe_metadata:
        if not isinstance(probe, dict):
            continue
        match = re.fullmatch(r"P(\d+)", str(probe.get("id", "")))
        element_id = probe.get("element_id")
        depth = probe.get("depth_from_top_m")
        if (
            match is None
            or not isinstance(element_id, int)
            or isinstance(element_id, bool)
            or not _is_finite_number(depth)
        ):
            continue
        path_probes.append((int(match.group(1)), float(depth), element_id))
    path_probes.sort(key=lambda item: (item[1], item[0]))

    arrivals: list[JSONDict] = []
    for index, depth, element_id in path_probes:
        probe_response = response_by_element.get(element_id, {})
        arrival = probe_response.get(
            "durable_principal_stress_arrival"
            if require_durable
            else "first_principal_stress_arrival"
        )
        arrivals.append(
            {
                "probe_id": f"P{index}",
                "element_id": element_id,
                "depth_from_top_m": depth,
                "first_arrival_time_s": (
                    float(arrival["time_s"])
                    if isinstance(arrival, dict)
                    and _is_finite_number(arrival.get("time_s"))
                    else None
                ),
                "first_arrival_response_pa": (
                    float(arrival["absolute_value_pa"])
                    if isinstance(arrival, dict)
                    and _is_finite_number(arrival.get("absolute_value_pa"))
                    else None
                ),
                "peak_principal_stress_response_pa": probe_response.get(
                    "peak_principal_stress_response_pa"
                ),
            }
        )

    times = [arrival["first_arrival_time_s"] for arrival in arrivals]
    all_arrived = len(arrivals) >= 3 and all(
        _is_finite_number(value) for value in times
    )
    ordered = all_arrived and all(
        float(second) > float(first)
        for first, second in zip(times, times[1:])
    )
    velocities: list[float] = []
    if ordered:
        for first, second in zip(arrivals, arrivals[1:]):
            distance = float(second["depth_from_top_m"]) - float(
                first["depth_from_top_m"]
            )
            elapsed = float(second["first_arrival_time_s"]) - float(
                first["first_arrival_time_s"]
            )
            if distance <= 0.0 or elapsed <= 0.0:
                ordered = False
                velocities = []
                break
            velocities.append(distance / elapsed)

    if len(arrivals) < 3:
        reason = "at_least_three_ordered_path_probes_required"
    elif not all_arrived:
        reason = "principal_stress_did_not_reach_every_path_probe"
    elif not ordered:
        reason = "principal_stress_arrival_times_are_not_strictly_increasing"
    else:
        reason = None
    return {
        "verified": bool(ordered),
        "threshold_pa": PHASE15_STRESS_RESPONSE_FLOOR_PA,
        "arrivals": arrivals,
        "apparent_velocities_m_per_s": velocities,
        "reason": reason,
    }


def _evaluate_air_gap_transfer(
    ale_response: JSONDict,
    concrete_response: JSONDict,
    concrete_probe_metadata: list[JSONDict],
    history_output_dt_s: float | None,
) -> JSONDict:
    ale_by_id = {
        str(item.get("probe_id")): item
        for item in ale_response.get("probe_responses", [])
        if isinstance(item, dict)
    }
    concrete_by_element = {
        int(item["element_id"]): item
        for item in concrete_response.get("probe_responses", [])
        if isinstance(item, dict)
        and isinstance(item.get("element_id"), int)
        and not isinstance(item.get("element_id"), bool)
    }
    interface_candidates: list[tuple[str, JSONDict]] = []
    for probe in concrete_probe_metadata:
        if not isinstance(probe, dict):
            continue
        probe_id = str(probe.get("id", ""))
        element_id = probe.get("element_id")
        if (
            probe_id not in {"INTERFACE_BOTTOM", "INTERFACE_WALL"}
            or not isinstance(element_id, int)
            or isinstance(element_id, bool)
        ):
            continue
        response = concrete_by_element.get(element_id)
        arrival = (
            response.get("durable_principal_stress_arrival")
            if isinstance(response, dict)
            else None
        )
        if isinstance(arrival, dict) and _is_finite_number(arrival.get("time_s")):
            interface_candidates.append((probe_id, arrival))
    interface_probe_id: str | None = None
    concrete_arrival: JSONDict | None = None
    if interface_candidates:
        interface_probe_id, concrete_arrival = min(
            interface_candidates,
            key=lambda item: float(item[1]["time_s"]),
        )

    arrivals: list[JSONDict] = []
    for probe_id in ("TNT_NEAR", "AIR_MID_GAP", "AIR_INTERFACE"):
        probe = ale_by_id.get(probe_id, {})
        arrivals.append(
            {
                "probe_id": probe_id,
                "time_s": probe.get("durable_arrival_time_s"),
                "element_id": probe.get("element_id"),
            }
        )
    arrivals.append(
        {
            "probe_id": "CONCRETE_INTERFACE",
            "source_probe_id": interface_probe_id,
            "time_s": (
                concrete_arrival.get("time_s")
                if isinstance(concrete_arrival, dict)
                else None
            ),
        }
    )

    times = [arrival["time_s"] for arrival in arrivals]
    output_dt_valid = (
        _is_finite_number(history_output_dt_s)
        and float(history_output_dt_s) > 0.0
    )
    all_arrived = all(_is_finite_number(value) for value in times)
    air_ordered = bool(
        all_arrived
        and float(times[1]) >= float(times[0])
        and float(times[2]) >= float(times[1])
        and float(times[2]) > float(times[0])
    )
    interface_ordered = bool(
        all_arrived
        and output_dt_valid
        and float(times[3])
        >= float(times[2]) - float(history_output_dt_s)
    )
    verified = bool(
        ale_response.get("verified")
        and air_ordered
        and interface_ordered
    )
    if not all_arrived:
        reason = "durable_transfer_arrival_is_missing"
    elif not output_dt_valid:
        reason = "history_output_dt_s_is_missing_or_invalid"
    elif not air_ordered:
        reason = "ale_air_gap_arrivals_are_not_ordered"
    elif not interface_ordered:
        reason = "concrete_response_precedes_ale_interface_load"
    elif not ale_response.get("verified"):
        reason = "ale_air_gap_pressure_progression_not_verified"
    else:
        reason = None
    return {
        "verified": verified,
        "arrivals": arrivals,
        "concrete_interface_arrival_time_s": times[3],
        "ordering_tolerance_s": (
            float(history_output_dt_s) if output_dt_valid else None
        ),
        "reason": reason,
    }


def _durable_response(
    series: list[JSONDict],
    *,
    value_key: str,
    floor: float,
) -> JSONDict:
    if not series:
        return {
            "arrival": None,
            "baseline": 0.0,
            "noise": 0.0,
            "threshold": float(floor),
            "consecutive_response_samples": 0,
        }
    baseline_samples = [
        _finite_number(sample[value_key], f"{value_key} baseline")
        for sample in series[:2]
    ]
    baseline = statistics.fmean(baseline_samples)
    noise = max(abs(value - baseline) for value in baseline_samples)
    threshold = max(float(floor), 10.0 * noise)
    responses = [
        abs(_finite_number(sample[value_key], value_key) - baseline)
        for sample in series
    ]
    arrival: JSONDict | None = None
    consecutive = 0
    for index, response_value in enumerate(responses):
        if response_value > threshold:
            run_length = 1
            while (
                index + run_length < len(responses)
                and responses[index + run_length] > threshold
            ):
                run_length += 1
            if run_length >= PHASE15_DURABLE_RESPONSE_SAMPLES:
                sample = series[index]
                arrival = {
                    "time_s": float(sample["time_s"]),
                    "time_step": int(sample["time_step"]),
                    "value_pa": float(sample[value_key]),
                    "absolute_response_pa": response_value,
                }
                consecutive = run_length
                break
    return {
        "arrival": arrival,
        "baseline": baseline,
        "noise": noise,
        "threshold": threshold,
        "consecutive_response_samples": consecutive,
    }


def _concrete_edge_counts(
    concrete_elements: list[list[int]],
) -> Counter[tuple[int, int]]:
    counts: Counter[tuple[int, int]] = Counter()
    for element in concrete_elements:
        if len(element) < 6:
            continue
        nodes = [int(value) for value in element[2:6]]
        for first, second in zip(nodes, nodes[1:] + nodes[:1]):
            counts[tuple(sorted((first, second)))] += 1
    return counts


def _classify_surface(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    geometry: JSONDict,
    tolerance: float,
) -> str | None:
    first_r, first_z = float(first[0]), float(first[1])
    second_r, second_z = float(second[0]), float(second[1])
    charge_radius = float(geometry["charge_radius_m"])
    charge_bottom = float(geometry["charge_bottom_z_m"])
    target_top = float(geometry["target_top_z_m"])
    target_radius = float(geometry["target_radius_m"])

    if (
        _close(first_z, charge_bottom, tolerance)
        and _close(second_z, charge_bottom, tolerance)
        and min(first_r, second_r) >= -tolerance
        and max(first_r, second_r) <= charge_radius + tolerance
    ):
        return "charge_bottom"
    if (
        _close(first_r, charge_radius, tolerance)
        and _close(second_r, charge_radius, tolerance)
        and min(first_z, second_z) >= charge_bottom - tolerance
        and max(first_z, second_z) <= target_top + tolerance
    ):
        return "borehole_wall"
    if (
        _close(first_z, target_top, tolerance)
        and _close(second_z, target_top, tolerance)
        and min(first_r, second_r) >= charge_radius - tolerance
        and max(first_r, second_r) <= target_radius + tolerance
    ):
        return "concrete_top"
    return None


def _orient_segment(
    first: int,
    second: int,
    node_coordinates: dict[int, tuple[float, float, float]],
    expected_normal: tuple[float, float],
) -> tuple[int, int]:
    if _normal_matches(first, second, node_coordinates, expected_normal):
        return first, second
    return second, first


def _normal_matches(
    first: int,
    second: int,
    node_coordinates: dict[int, tuple[float, float, float]],
    expected_normal: tuple[float, float],
) -> bool:
    first_r, first_z = node_coordinates[first][0:2]
    second_r, second_z = node_coordinates[second][0:2]
    delta_r = float(second_r) - float(first_r)
    delta_z = float(second_z) - float(first_z)
    normal = (delta_z, -delta_r)
    return normal[0] * expected_normal[0] + normal[1] * expected_normal[1] > 0.0


def _is_connected_chain(segments: list[tuple[int, int]]) -> bool:
    adjacency: dict[int, set[int]] = defaultdict(set)
    for first, second in segments:
        adjacency[first].add(second)
        adjacency[second].add(first)
    if any(len(neighbors) > 2 for neighbors in adjacency.values()):
        return False
    endpoints = sum(len(neighbors) == 1 for neighbors in adjacency.values())
    if endpoints != 2:
        return False
    pending = [next(iter(adjacency))]
    visited: set[int] = set()
    while pending:
        node = pending.pop()
        if node in visited:
            continue
        visited.add(node)
        pending.extend(adjacency[node] - visited)
    return len(visited) == len(adjacency)


def _segment_midpoint(
    segment: list[int],
    node_coordinates: dict[int, tuple[float, float, float]],
) -> tuple[float, float]:
    first = node_coordinates[int(segment[0])]
    second = node_coordinates[int(segment[1])]
    return (
        0.5 * (float(first[0]) + float(second[0])),
        0.5 * (float(first[1]) + float(second[1])),
    )


def _coordinate_range(
    segments: list[list[int]],
    node_coordinates: dict[int, tuple[float, float, float]],
) -> JSONDict:
    node_ids = {int(value) for segment in segments for value in segment}
    if not node_ids:
        return {"r": None, "z": None}
    radii = [float(node_coordinates[node_id][0]) for node_id in node_ids]
    axial = [float(node_coordinates[node_id][1]) for node_id in node_ids]
    return {"r": [min(radii), max(radii)], "z": [min(axial), max(axial)]}


def _tolerance(mesh_size_m: float) -> float:
    value = float(mesh_size_m)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError("mesh_size_m must be positive and finite")
    return max(1.0e-10, value * 1.0e-6)


def _close(first: float, second: float, tolerance: float) -> bool:
    return math.isclose(float(first), float(second), rel_tol=0.0, abs_tol=tolerance)


def _axisymmetric_principal_stresses(
    stress: tuple[float, ...],
) -> tuple[float, float, float]:
    if len(stress) != 6:
        raise ValueError("axisymmetric stress must contain six components")
    radial, axial, hoop, radial_axial, _, _ = stress
    mean = 0.5 * (radial + axial)
    radius = math.hypot(0.5 * (radial - axial), radial_axial)
    return tuple(sorted((mean + radius, mean - radius, hoop), reverse=True))


def _finite_number(value: object, field: str) -> float:
    try:
        parsed = float(str(value).replace("D", "E").replace("d", "e"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{field} must be finite")
    return parsed


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _first_output(directory: Path, prefix: str) -> Path | None:
    if not directory.is_dir():
        return None
    candidates = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.name.lower().startswith(prefix.lower())
    )
    return candidates[0] if candidates else None
