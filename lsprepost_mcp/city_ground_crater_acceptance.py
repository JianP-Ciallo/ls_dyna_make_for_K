from __future__ import annotations

import math
from pathlib import Path

from .config import JSONDict
from .city_ground_crater import (
    ERODING_FSI_SURFACE_ID,
    ERODING_GROUND_MATERIAL_ID,
    GROUND_RESPONSE_MODE,
    PERIPHERAL_FSI_SURFACE_ID,
)
from .phase15_fsi import parse_phase15_elout
from .solver_results import (
    ELOUT_ELEMENT_PATTERN,
    ELOUT_STATE_PATTERN,
    NODOUT_NUMBER_PATTERN,
    NODOUT_STATE_PATTERN,
    parse_dbfsi,
)


MINIMUM_GROUND_PRESSURE_RESPONSE_PA = 100.0
MINIMUM_GROUND_STRESS_RESPONSE_PA = 100.0
MINIMUM_GROUND_PRESSURE_IMPULSE_PA_S = 1.0e-3


def evaluate_city_ground_crater(
    run_dir: Path,
    ground_metadata: JSONDict,
) -> JSONDict:
    directory = Path(run_dir)
    checks: list[JSONDict] = []

    def add(check_id: str, ok: bool, actual: object, limit: object) -> None:
        checks.append(
            {
                "id": check_id,
                "ok": bool(ok),
                "actual": actual,
                "limit": limit,
            }
        )

    mode = ground_metadata.get("mode")
    mesh_size = _finite_value(ground_metadata.get("local_mesh_size_m"))
    eroding_fsi = _object(ground_metadata.get("eroding_fsi"))
    peripheral_fsi = _object(ground_metadata.get("peripheral_fsi"))
    probe_solid_ids = _positive_integer_set(
        ground_metadata.get("probe_solid_ids")
    )
    history_node_ids = _positive_integer_set(
        ground_metadata.get("history_node_ids")
    )
    part_counts = _object(ground_metadata.get("part_element_counts"))
    initial_eroding_count = _positive_integer(
        part_counts.get(str(ERODING_GROUND_MATERIAL_ID))
    )
    metadata_ok = (
        mode == GROUND_RESPONSE_MODE
        and mesh_size is not None
        and mesh_size > 0.0
        and probe_solid_ids
        and history_node_ids
        and initial_eroding_count is not None
        and _positive_integer(eroding_fsi.get("initial_exposed_segment_count"))
        is not None
        and _positive_integer(peripheral_fsi.get("exposed_segment_count"))
        is not None
    )
    add(
        "city_ground_result_contract",
        bool(metadata_ok),
        {
            "mode": mode,
            "mesh_size_m": mesh_size,
            "probe_solid_count": len(probe_solid_ids),
            "history_node_count": len(history_node_ids),
            "initial_eroding_element_count": initial_eroding_count,
            "eroding_segment_count": eroding_fsi.get(
                "initial_exposed_segment_count"
            ),
            "peripheral_segment_count": peripheral_fsi.get(
                "exposed_segment_count"
            ),
        },
        {"ground_response_mode": GROUND_RESPONSE_MODE, "all_counts_positive": True},
    )

    dbfsi: JSONDict = {}
    dbfsi_error: str | None = None
    try:
        dbfsi = parse_dbfsi(
            (directory / "dbfsi").read_text(
                encoding="utf-8",
                errors="replace",
            )
        )
    except (OSError, TypeError, ValueError) as exc:
        dbfsi_error = f"{type(exc).__name__}: {exc}"
    surfaces = {
        int(item["surface_id"]): item
        for item in dbfsi.get("surfaces", [])
        if isinstance(item, dict) and _positive_integer(item.get("surface_id"))
    }
    requested_surfaces = {
        "eroding": (
            _positive_integer(eroding_fsi.get("surface_id"))
            or ERODING_FSI_SURFACE_ID
        ),
        "peripheral": (
            _positive_integer(peripheral_fsi.get("surface_id"))
            or PERIPHERAL_FSI_SURFACE_ID
        ),
    }
    fsi_results: dict[str, JSONDict] = {}
    for name, surface_id in requested_surfaces.items():
        surface = surfaces.get(surface_id, {})
        surface_ok = (
            _finite_above(
                surface.get("peak_pressure_rise_pa"),
                MINIMUM_GROUND_PRESSURE_RESPONSE_PA,
            )
            and _finite_above(
                surface.get("positive_pressure_impulse_pa_s"),
                MINIMUM_GROUND_PRESSURE_IMPULSE_PA_S,
            )
            and _positive_integer(surface.get("positive_pressure_sample_count"))
            is not None
            and int(surface["positive_pressure_sample_count"]) >= 2
            and _finite_above(surface.get("positive_pressure_duration_s"), 0.0)
        )
        fsi_results[name] = {
            "surface_id": surface_id,
            **surface,
            "ok": bool(surface_ok),
        }
        add(
            f"city_ground_{name}_fsi_response",
            bool(surface_ok),
            surface if surface else dbfsi_error or "surface_missing",
            {
                "surface_id": surface_id,
                "minimum_pressure_rise_pa": MINIMUM_GROUND_PRESSURE_RESPONSE_PA,
                "minimum_positive_pressure_samples": 2,
                "minimum_positive_pressure_impulse_pa_s": (
                    MINIMUM_GROUND_PRESSURE_IMPULSE_PA_S
                ),
            },
        )

    kc_response: JSONDict = {}
    kc_error: str | None = None
    if probe_solid_ids:
        try:
            kc_response = parse_phase15_elout(
                directory / "elout",
                probe_solid_ids,
                material_id=ERODING_GROUND_MATERIAL_ID,
            )
        except (OSError, TypeError, ValueError) as exc:
            kc_error = f"{type(exc).__name__}: {exc}"
    kc_pressure_stress_ok = (
        _finite_above(
            kc_response.get("peak_hydrostatic_pressure_response_pa"),
            MINIMUM_GROUND_PRESSURE_RESPONSE_PA,
        )
        and _finite_above(
            kc_response.get("peak_principal_stress_response_pa"),
            MINIMUM_GROUND_STRESS_RESPONSE_PA,
        )
    )
    add(
        "city_ground_kc_pressure_stress",
        bool(kc_pressure_stress_ok),
        kc_response if kc_response else kc_error or "unavailable",
        {
            "minimum_pressure_response_pa": MINIMUM_GROUND_PRESSURE_RESPONSE_PA,
            "minimum_principal_stress_response_pa": MINIMUM_GROUND_STRESS_RESPONSE_PA,
        },
    )
    kc_damage_ok = (
        kc_response.get("kc_scaled_damage_readable") is True
        and _finite_above(kc_response.get("peak_kc_scaled_damage"), 0.0)
    )
    add(
        "city_ground_kc_damage",
        bool(kc_damage_ok),
        {
            "readable": kc_response.get("kc_scaled_damage_readable"),
            "peak_scaled_damage": kc_response.get("peak_kc_scaled_damage"),
            "error": kc_error,
        },
        {"readable": True, "minimum_scaled_damage_exclusive": 0.0},
    )

    ground_motion: JSONDict = {}
    motion_error: str | None = None
    if history_node_ids:
        try:
            ground_motion = _parse_ground_nodout(
                (directory / "nodout").read_text(
                    encoding="utf-8",
                    errors="replace",
                ),
                history_node_ids,
            )
        except (OSError, TypeError, ValueError) as exc:
            motion_error = f"{type(exc).__name__}: {exc}"
    displacement_floor = max(1.0e-4, 0.01 * mesh_size) if mesh_size else None
    motion_ok = (
        displacement_floor is not None
        and ground_motion.get("all_history_nodes_observed") is True
        and _finite_above(
            ground_motion.get("maximum_downward_displacement_m"),
            displacement_floor,
        )
    )
    add(
        "city_ground_downward_displacement",
        bool(motion_ok),
        ground_motion if ground_motion else motion_error or "unavailable",
        {
            "all_history_nodes_observed": True,
            "minimum_downward_displacement_m": displacement_floor,
        },
    )

    element_deletion: JSONDict = {}
    deletion_error: str | None = None
    try:
        element_deletion = _parse_eroding_element_history(
            (directory / "elout").read_text(
                encoding="utf-8",
                errors="replace",
            ),
            ERODING_GROUND_MATERIAL_ID,
        )
    except (OSError, TypeError, ValueError) as exc:
        deletion_error = f"{type(exc).__name__}: {exc}"
    initial_evidence_ok = (
        initial_eroding_count is not None
        and element_deletion.get("initial_element_count") == initial_eroding_count
    )
    add(
        "city_ground_initial_element_evidence",
        bool(initial_evidence_ok),
        element_deletion if element_deletion else deletion_error or "unavailable",
        {"expected_initial_element_count": initial_eroding_count},
    )
    deletion_ok = (
        initial_evidence_ok
        and _positive_integer(element_deletion.get("deleted_element_count"))
        is not None
        and element_deletion.get("unexpected_added_element_ids") == []
    )
    add(
        "city_ground_element_deletion",
        bool(deletion_ok),
        element_deletion if element_deletion else deletion_error or "unavailable",
        {
            "minimum_deleted_element_count": 1,
            "unexpected_added_element_count": 0,
        },
    )

    crater_evidence_ok = bool(
        deletion_ok and motion_ok and kc_pressure_stress_ok and kc_damage_ok
    )
    add(
        "city_ground_actual_crater_evidence",
        crater_evidence_ok,
        {
            "deleted_element_count": element_deletion.get(
                "deleted_element_count"
            ),
            "maximum_downward_displacement_m": ground_motion.get(
                "maximum_downward_displacement_m"
            ),
            "peak_kc_scaled_damage": kc_response.get("peak_kc_scaled_damage"),
        },
        {
            "element_deletion_required": True,
            "downward_displacement_required": True,
            "kc_response_required": True,
        },
    )

    blocking = [item["id"] for item in checks if not item["ok"]]
    return {
        "applicable": True,
        "verified": not blocking,
        "blocking_check_ids": blocking,
        "checks": checks,
        "fsi": fsi_results,
        "kc_response": kc_response,
        "ground_motion": ground_motion,
        "element_deletion": element_deletion,
    }


def _parse_ground_nodout(text: str, node_ids: set[int]) -> JSONDict:
    if not isinstance(text, str):
        raise TypeError("nodout text must be a string")
    if not node_ids:
        raise ValueError("ground history node ids must not be empty")
    current_step: int | None = None
    current_time: float | None = None
    translation_block = False
    baselines: dict[int, tuple[float, float, float]] = {}
    observed: set[int] = set()
    state_keys: set[tuple[int, float]] = set()
    sample_count = 0
    maximum_downward = 0.0
    peak: JSONDict | None = None
    for line in text.splitlines():
        state_match = NODOUT_STATE_PATTERN.search(line)
        if state_match:
            current_step = int(state_match.group(1))
            current_time = _finite_number(state_match.group(2), "nodout time")
            if current_time < 0.0:
                raise ValueError("nodout time must be non-negative")
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
        if node_id not in node_ids:
            continue
        vector = tuple(
            _finite_number(value, "nodout ground displacement")
            for value in values[1:4]
        )
        baseline = baselines.setdefault(node_id, vector)
        downward = max(0.0, baseline[2] - vector[2])
        observed.add(node_id)
        state_keys.add((current_step, current_time))
        sample_count += 1
        if peak is None or downward > maximum_downward:
            maximum_downward = downward
            peak = {
                "node_id": node_id,
                "time_step": current_step,
                "time_s": current_time,
                "downward_displacement_m": downward,
                "components_from_baseline_m": {
                    "x": vector[0] - baseline[0],
                    "y": vector[1] - baseline[1],
                    "z": vector[2] - baseline[2],
                },
            }
    if not observed:
        raise ValueError("nodout contains no requested ground history nodes")
    return {
        "state_count": len(state_keys),
        "sample_count": sample_count,
        "requested_history_node_count": len(node_ids),
        "observed_history_node_ids": sorted(observed),
        "all_history_nodes_observed": observed == node_ids,
        "maximum_downward_displacement_m": maximum_downward,
        "peak": peak,
    }


def _parse_eroding_element_history(text: str, material_id: int) -> JSONDict:
    if not isinstance(text, str):
        raise TypeError("elout text must be a string")
    states: list[tuple[int, float, set[int]]] = []
    current: tuple[int, float, set[int]] | None = None
    for line in text.splitlines():
        state_match = ELOUT_STATE_PATTERN.search(line)
        if state_match:
            current = (
                int(state_match.group(1)),
                _finite_number(state_match.group(2), "elout time"),
                set(),
            )
            states.append(current)
            continue
        if current is None:
            continue
        element_match = ELOUT_ELEMENT_PATTERN.match(line)
        if element_match and int(element_match.group(2)) == material_id:
            current[2].add(int(element_match.group(1)))
    initial_index = next(
        (index for index, state in enumerate(states) if state[2]),
        None,
    )
    if initial_index is None or len(states) - initial_index < 2:
        raise ValueError("elout contains fewer than two eroding-ground states")
    relevant_states = states[initial_index:]
    initial = relevant_states[0]
    final = relevant_states[-1]
    deleted_ids = sorted(initial[2] - final[2])
    added_ids = sorted(final[2] - initial[2])
    return {
        "state_count": len(relevant_states),
        "initial_time_step": initial[0],
        "initial_time_s": initial[1],
        "initial_element_count": len(initial[2]),
        "final_time_step": final[0],
        "final_time_s": final[1],
        "final_element_count": len(final[2]),
        "deleted_element_count": len(deleted_ids),
        "deleted_element_ids": deleted_ids,
        "unexpected_added_element_ids": added_ids,
    }


def _object(value: object) -> JSONDict:
    return value if isinstance(value, dict) else {}


def _positive_integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _positive_integer_set(value: object) -> set[int]:
    if not isinstance(value, list):
        return set()
    result = {_positive_integer(item) for item in value}
    result.discard(None)
    return {int(item) for item in result}


def _finite_value(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _finite_number(value: object, field: str) -> float:
    try:
        result = float(str(value).replace("D", "E").replace("d", "e"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _finite_above(value: object, minimum: float) -> bool:
    result = _finite_value(value)
    return result is not None and result > minimum
