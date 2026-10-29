"""Bounded, streaming parsers for LS-DYNA text evidence."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from ...contracts import Issue


_NUMBER = r"[^\s]+"
_LABEL_VALUE_RE = re.compile(rf"^\s*(?P<label>[A-Za-z /]+?)\.*\s+(?P<value>{_NUMBER})\s*$")
_TIME_RE = re.compile(rf"^\s*time\s*=*\.*\s*(?P<value>{_NUMBER})\s*$", re.IGNORECASE)
_PROBLEM_TIME_RE = re.compile(rf"\bproblem\s+time\s*=\s*(?P<value>{_NUMBER})", re.IGNORECASE)
_TERMINATION_TIME_RE = re.compile(
    rf"^\s*termination\s+time\s*[.=]+\s*(?P<value>{_NUMBER})\s*$", re.IGNORECASE
)
_MATSUM_RE = re.compile(
    rf"^\s*mat\.\#\s*=\s*(?P<material>[0-9]+).*?"
    rf"inten\s*=\s*(?P<internal>{_NUMBER}).*?"
    rf"kinen\s*=\s*(?P<kinetic>{_NUMBER}).*?"
    rf"eroded_ie\s*=\s*(?P<eroded_internal>{_NUMBER}).*?"
    rf"eroded_ke\s*=\s*(?P<eroded_kinetic>{_NUMBER})",
    re.IGNORECASE,
)
_DBFSI_ROW_RE = re.compile(rf"^\s*(?P<surface>[0-9]+)\s+(?P<pressure>{_NUMBER})(?:\s+.*)?$")


@dataclass(frozen=True)
class D3hspSummary:
    termination: str
    problem_time: float | None
    termination_time: float | None
    issues: tuple[Issue, ...]


@dataclass(frozen=True)
class EnergyRecord:
    time: float
    kinetic_energy: float | None
    internal_energy: float | None
    hourglass_energy: float
    eroded_kinetic_energy: float
    eroded_internal_energy: float
    total_energy: float
    total_to_initial_ratio: float | None

    @property
    def eroded_energy(self) -> float:
        return self.eroded_kinetic_energy + self.eroded_internal_energy


@dataclass(frozen=True)
class GlstatSummary:
    records: tuple[EnergyRecord, ...]
    final_time: float | None
    max_hourglass_ratio: float | None
    issues: tuple[Issue, ...]


@dataclass(frozen=True)
class MaterialEnergyRecord:
    time: float
    material_id: int
    internal_energy: float
    kinetic_energy: float
    eroded_internal_energy: float
    eroded_kinetic_energy: float

    @property
    def eroded_energy(self) -> float:
        return self.eroded_internal_energy + self.eroded_kinetic_energy


@dataclass(frozen=True)
class MatsumSummary:
    records: tuple[MaterialEnergyRecord, ...]
    issues: tuple[Issue, ...]


@dataclass(frozen=True)
class FsiPressureRecord:
    time: float
    surface_id: int
    pressure: float


@dataclass(frozen=True)
class DbfsiSummary:
    records: tuple[FsiPressureRecord, ...]
    issues: tuple[Issue, ...]


def _append_issue(issues: list[Issue], issue: Issue, max_findings: int) -> None:
    if len(issues) < max_findings:
        issues.append(issue)


def _lines(
    path: Path,
    issues: list[Issue],
    *,
    max_line_bytes: int,
    max_findings: int,
) -> Iterator[tuple[int, str]]:
    with path.open("rb") as stream:
        for line_number, raw in enumerate(stream, 1):
            if len(raw) > max_line_bytes:
                _append_issue(
                    issues,
                    Issue("text.line_too_long", "Text evidence line exceeded the parser limit", {"line": line_number}),
                    max_findings,
                )
                continue
            try:
                line = raw.decode("utf-8")
            except UnicodeDecodeError:
                line = raw.decode("utf-8", errors="replace")
                _append_issue(
                    issues,
                    Issue("text.decode_replacement", "Invalid UTF-8 bytes were replaced", {"line": line_number}),
                    max_findings,
                )
            yield line_number, line.rstrip("\r\n")


def _number(token: str, issues: list[Issue], line_number: int, max_findings: int) -> float | None:
    try:
        value = float(token.replace("D", "E").replace("d", "e"))
    except ValueError:
        _append_issue(
            issues,
            Issue("text.invalid_number", "A numeric text record could not be parsed", {"line": line_number, "token": token}),
            max_findings,
        )
        return None
    if not math.isfinite(value):
        _append_issue(
            issues,
            Issue("text.nonfinite", "A non-finite numeric text record was ignored", {"line": line_number, "token": token}),
            max_findings,
        )
        return None
    return value


def parse_d3hsp(path: Path, *, max_line_bytes: int = 1024 * 1024, max_findings: int = 1000) -> D3hspSummary:
    issues: list[Issue] = []
    normal = False
    abnormal = False
    sense_switch = False
    problem_time: float | None = None
    termination_time: float | None = None
    for line_number, line in _lines(path, issues, max_line_bytes=max_line_bytes, max_findings=max_findings):
        letters = re.sub(r"[^a-z]+", "", line.lower())
        if letters.startswith("normaltermination"):
            normal = True
        if letters.startswith(("abnormaltermination", "errortermination")):
            abnormal = True
        if letters.startswith("termination") and "senseswitch" in letters:
            sense_switch = True
        match = _PROBLEM_TIME_RE.search(line)
        if match:
            value = _number(match.group("value"), issues, line_number, max_findings)
            if value is not None:
                problem_time = value
        match = _TERMINATION_TIME_RE.match(line)
        if match:
            value = _number(match.group("value"), issues, line_number, max_findings)
            if value is not None:
                termination_time = value
    termination = "sense_switch" if sense_switch else "abnormal" if abnormal else "normal" if normal else "unknown"
    return D3hspSummary(termination, problem_time, termination_time, tuple(issues))


def parse_glstat(path: Path, *, max_line_bytes: int = 1024 * 1024, max_findings: int = 1000) -> GlstatSummary:
    issues: list[Issue] = []
    records: list[EnergyRecord] = []
    current: dict[str, float] = {}

    def finish() -> None:
        if not current:
            return
        required = {"time", "hourglass energy", "total energy"}
        if not required.issubset(current):
            _append_issue(
                issues,
                Issue("glstat.incomplete_state", "Incomplete GLSTAT energy state was ignored"),
                max_findings,
            )
            current.clear()
            return
        records.append(
            EnergyRecord(
                time=current["time"],
                kinetic_energy=current.get("kinetic energy"),
                internal_energy=current.get("internal energy"),
                hourglass_energy=current["hourglass energy"],
                eroded_kinetic_energy=current.get("eroded kinetic energy", 0.0),
                eroded_internal_energy=current.get("eroded internal energy", 0.0),
                total_energy=current["total energy"],
                total_to_initial_ratio=current.get("total energy / initial energy"),
            )
        )
        current.clear()

    wanted = {
        "kinetic energy",
        "internal energy",
        "hourglass energy",
        "eroded kinetic energy",
        "eroded internal energy",
        "total energy",
        "total energy / initial energy",
    }
    for line_number, line in _lines(path, issues, max_line_bytes=max_line_bytes, max_findings=max_findings):
        time_match = _TIME_RE.match(line)
        if time_match:
            finish()
            value = _number(time_match.group("value"), issues, line_number, max_findings)
            if value is not None:
                current["time"] = value
            continue
        match = _LABEL_VALUE_RE.match(line)
        if not match:
            continue
        label = " ".join(match.group("label").lower().split())
        if label not in wanted:
            continue
        value = _number(match.group("value"), issues, line_number, max_findings)
        if value is not None:
            current[label] = value
    finish()
    ratios = [
        abs(record.hourglass_energy) / abs(record.total_energy)
        for record in records
        if record.total_energy != 0.0
    ]
    return GlstatSummary(
        tuple(records),
        records[-1].time if records else None,
        max(ratios) if ratios else None,
        tuple(issues),
    )


def parse_matsum(path: Path, *, max_line_bytes: int = 1024 * 1024, max_findings: int = 1000) -> MatsumSummary:
    issues: list[Issue] = []
    records: list[MaterialEnergyRecord] = []
    current_time: float | None = None
    for line_number, line in _lines(path, issues, max_line_bytes=max_line_bytes, max_findings=max_findings):
        time_match = _TIME_RE.match(line)
        if time_match:
            current_time = _number(time_match.group("value"), issues, line_number, max_findings)
            continue
        match = _MATSUM_RE.match(line)
        if not match:
            continue
        values = {
            name: _number(match.group(name), issues, line_number, max_findings)
            for name in ("internal", "kinetic", "eroded_internal", "eroded_kinetic")
        }
        if current_time is None or any(value is None for value in values.values()):
            _append_issue(
                issues,
                Issue("matsum.incomplete_record", "Incomplete MATSUM record was ignored", {"line": line_number}),
                max_findings,
            )
            continue
        records.append(
            MaterialEnergyRecord(
                current_time,
                int(match.group("material")),
                values["internal"],  # type: ignore[arg-type]
                values["kinetic"],  # type: ignore[arg-type]
                values["eroded_internal"],  # type: ignore[arg-type]
                values["eroded_kinetic"],  # type: ignore[arg-type]
            )
        )
    return MatsumSummary(tuple(records), tuple(issues))


def parse_dbfsi(path: Path, *, max_line_bytes: int = 1024 * 1024, max_findings: int = 1000) -> DbfsiSummary:
    issues: list[Issue] = []
    records: list[FsiPressureRecord] = []
    current_time: float | None = None
    for line_number, line in _lines(path, issues, max_line_bytes=max_line_bytes, max_findings=max_findings):
        time_match = _TIME_RE.match(line)
        if time_match:
            current_time = _number(time_match.group("value"), issues, line_number, max_findings)
            continue
        match = _DBFSI_ROW_RE.match(line)
        if match is None or current_time is None:
            continue
        pressure = _number(match.group("pressure"), issues, line_number, max_findings)
        if pressure is not None:
            records.append(FsiPressureRecord(current_time, int(match.group("surface")), pressure))
    return DbfsiSummary(tuple(records), tuple(issues))
