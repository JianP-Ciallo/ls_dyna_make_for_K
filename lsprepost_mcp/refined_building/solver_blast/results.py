"""R12 run-evidence evaluation for Phase 18 solver blast models."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from ...solver_results import parse_d3hsp, parse_dbfsi, parse_fsi_interfaces
from .validation import ValidationFinding, inspect_solver_blast_deck


_MAX_TEXT_EVIDENCE_BYTES = 256 * 1024 * 1024
_RESPONSE_NOISE_FLOOR_N = 1.0e-6


@dataclass(frozen=True, slots=True)
class SolverBlastRunReport:
    ok: bool
    findings: tuple[ValidationFinding, ...]
    acceptance_mode: str
    propagation_observed: bool
    normal_termination: bool
    final_problem_time_s: float
    fsi_slave_segment_count: int
    air_peak_pressure_pa: float
    building_peak_response: float
    response_noise_floor: float
    source_time_s: float
    air_arrival_time_s: float | None
    building_arrival_time_s: float | None


def evaluate_solver_blast_run(model_dir: Path, run_dir: Path) -> SolverBlastRunReport:
    try:
        return _evaluate_solver_blast_run(Path(model_dir), Path(run_dir))
    except (OSError, TypeError, ValueError) as exc:
        return _failed_report((ValidationFinding("run_parse_error", str(exc)),))


def _evaluate_solver_blast_run(model_dir: Path, run_dir: Path) -> SolverBlastRunReport:
    deck = inspect_solver_blast_deck(model_dir)
    if not deck.ok:
        return _failed_report(
            tuple(
                ValidationFinding(f"deck:{row.code}", row.message)
                for row in deck.findings
            )
        )
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ValueError("solver run path must be a real directory")

    required = ("d3hsp", "messag", "glstat", "matsum")
    texts: dict[str, str] = {}
    for name in required:
        path = run_dir / name
        if not path.is_file() or path.is_symlink():
            return _failed_report((ValidationFinding(f"missing:{name}", f"required R12 evidence is missing: {name}"),))
        size = path.stat().st_size
        if size <= 0 or size > _MAX_TEXT_EVIDENCE_BYTES:
            return _failed_report((ValidationFinding(f"size:{name}", f"R12 evidence has an invalid size: {name}"),))
        texts[name] = path.read_text(encoding="utf-8", errors="replace")
    dbfsi_path = run_dir / "dbfsi"
    if dbfsi_path.exists():
        if not dbfsi_path.is_file() or dbfsi_path.is_symlink():
            return _failed_report(
                (ValidationFinding("invalid:dbfsi", "optional R12 evidence is not a real file: dbfsi"),)
            )
        size = dbfsi_path.stat().st_size
        if size <= 0 or size > _MAX_TEXT_EVIDENCE_BYTES:
            return _failed_report(
                (ValidationFinding("size:dbfsi", "R12 evidence has an invalid size: dbfsi"),)
            )
        texts["dbfsi"] = dbfsi_path.read_text(encoding="utf-8", errors="replace")

    findings: list[ValidationFinding] = []
    d3hsp = parse_d3hsp(texts["d3hsp"])
    glstat = parse_d3hsp(texts["glstat"])
    fsi = parse_fsi_interfaces(texts["d3hsp"])
    dbfsi = parse_dbfsi(texts["dbfsi"]) if "dbfsi" in texts else {"surfaces": []}
    combined = "\n".join(texts.values())
    _check(
        findings,
        not _contains_fatal_output(combined),
        "fatal_output",
        "R12 output contains a fatal, invalid-volume or non-finite marker",
    )
    normal_termination = bool(d3hsp.get("terminated_normally"))
    _check(findings, normal_termination, "normal_termination", "R12 did not terminate normally")
    final_time = float(d3hsp.get("final_problem_time_s") or 0.0)
    required_time = float(deck.termination_time_s or 0.0)
    _check(
        findings,
        math.isfinite(final_time) and final_time + 1.0e-12 >= required_time,
        "final_problem_time",
        "R12 did not reach the requested termination time",
    )
    _check(
        findings,
        bool(glstat.get("finite")),
        "finite_energy",
        "R12 global energy histories are missing or non-finite",
    )
    _check(
        findings,
        not _contains_nonfinite(texts["matsum"]) and _contains_number(texts["matsum"]),
        "matsum_finite",
        "material energy history is missing or non-finite",
    )
    fsi_count = int(fsi.get("total_slave_segment_count") or 0)
    _check(findings, fsi_count > 0, "fsi_slave_segments", "R12 reported no active FSI slave segments")
    surfaces = dbfsi.get("surfaces")
    if isinstance(surfaces, list) and surfaces:
        pressure_surface = max(surfaces, key=lambda row: float(row["peak_pressure_rise_pa"]))
        force_surface = max(surfaces, key=lambda row: float(row["peak_force_rise_n"]))
        air_peak_pressure = float(pressure_surface["peak_pressure_rise_pa"])
        building_peak_response = float(force_surface["peak_force_rise_n"])
        air_arrival_raw = pressure_surface.get("pressure_arrival_time_s")
        air_arrival = float(air_arrival_raw) if air_arrival_raw is not None else None
        building_arrival_raw = force_surface.get("peak_force_time_s")
        building_arrival = (
            float(building_arrival_raw) if building_arrival_raw is not None else None
        )
    else:
        air_peak_pressure = 0.0
        building_peak_response = 0.0
        air_arrival = None
        building_arrival = None
    source_time = float(deck.detonation_time_s or 0.0)
    propagation_observed = bool(
        math.isfinite(air_peak_pressure)
        and air_peak_pressure > 0.0
        and math.isfinite(building_peak_response)
        and building_peak_response > _RESPONSE_NOISE_FLOOR_N
        and air_arrival is not None
        and building_arrival is not None
        and all(math.isfinite(value) for value in (source_time, air_arrival, building_arrival))
        and source_time <= air_arrival <= building_arrival
    )
    return SolverBlastRunReport(
        ok=not findings,
        findings=tuple(findings),
        acceptance_mode="configured_short_solve_no_error",
        propagation_observed=propagation_observed,
        normal_termination=normal_termination,
        final_problem_time_s=final_time,
        fsi_slave_segment_count=fsi_count,
        air_peak_pressure_pa=air_peak_pressure,
        building_peak_response=building_peak_response,
        response_noise_floor=_RESPONSE_NOISE_FLOOR_N,
        source_time_s=source_time,
        air_arrival_time_s=air_arrival,
        building_arrival_time_s=building_arrival,
    )


def _failed_report(findings: tuple[ValidationFinding, ...]) -> SolverBlastRunReport:
    return SolverBlastRunReport(
        ok=False,
        findings=findings,
        acceptance_mode="configured_short_solve_no_error",
        propagation_observed=False,
        normal_termination=False,
        final_problem_time_s=0.0,
        fsi_slave_segment_count=0,
        air_peak_pressure_pa=0.0,
        building_peak_response=0.0,
        response_noise_floor=_RESPONSE_NOISE_FLOOR_N,
        source_time_s=0.0,
        air_arrival_time_s=None,
        building_arrival_time_s=None,
    )


def _contains_nonfinite(text: str) -> bool:
    return _contains_numeric_nonfinite(text)


def _contains_fatal_output(text: str) -> bool:
    if re.search(
        r"(?im)^\s*(?:\*+\s*)?(?:fatal|error|e\s+r\s+r\s+o\s+r)\b"
        r"|negative\s+(?:volume|jacobian)",
        text,
    ):
        return True
    return _contains_numeric_nonfinite(text)


def _contains_numeric_nonfinite(text: str) -> bool:
    marker = re.compile(r"(?<![A-Za-z])[-+]?(?:nan|inf(?:inity)?)(?![A-Za-z])", re.IGNORECASE)
    number = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?")
    for line in text.splitlines():
        match = marker.search(line)
        if match is None:
            continue
        prefix = line[: match.start()]
        if "=" in prefix or re.search(r"\.{2,}\s*$", prefix):
            return True
        if number.search(prefix) or marker.fullmatch(line.strip()):
            return True
    return False


def _contains_number(text: str) -> bool:
    return bool(re.search(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?", text))


def _check(
    findings: list[ValidationFinding],
    condition: bool,
    code: str,
    message: str,
) -> None:
    if not condition:
        findings.append(ValidationFinding(code, message))
