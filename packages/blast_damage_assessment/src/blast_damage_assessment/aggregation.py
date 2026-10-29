"""Deterministic aggregation of building and ground assessment subjects."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .contracts import GateState, Severity
from .gates import combine_gate_states


@dataclass(frozen=True)
class SubjectSummary:
    subject_id: str
    gate: GateState
    severity: Severity | None
    governing_rule_hits: tuple[str, ...]


@dataclass(frozen=True)
class AggregateAssessment:
    gate: GateState
    severity: Severity | None
    partial_assessment: bool
    governing_subjects: tuple[str, ...]
    governing_rule_hits: tuple[str, ...]
    subjects: Mapping[str, SubjectSummary]

    def __post_init__(self) -> None:
        object.__setattr__(self, "subjects", MappingProxyType(dict(self.subjects)))


def _deduplicate(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _derived_rule_hits(subject: object, subject_id: str, severity: Severity) -> tuple[str, ...]:
    explicit = getattr(subject, "governing_rule_hits", None)
    if explicit is not None:
        return tuple(sorted(set(str(value) for value in explicit)))
    if subject_id == "building":
        hits: list[str] = []
        for component in getattr(subject, "components", ()):
            consequence = any(
                bool(getattr(component, name, False))
                for name in (
                    "hazardous_debris",
                    "evacuation_blockage",
                    "widespread_failure",
                    "corroborated_primary_damage",
                )
            )
            if getattr(component, "severity", None) == severity and (
                bool(getattr(component, "primary_load_path", False)) or consequence
            ):
                hits.extend(str(value) for value in getattr(component, "rule_hits", ()))
        return tuple(sorted(set(hits)))
    hits = []
    for rating in getattr(subject, "subratings", {}).values():
        if bool(getattr(rating, "available", False)) and getattr(rating, "severity", None) == severity:
            hits.extend(str(value) for value in getattr(rating, "rule_hits", ()))
    return tuple(sorted(set(hits)))


def _summarize(subject: object, subject_id: str) -> SubjectSummary:
    gate = getattr(subject, "gate", None)
    if not isinstance(gate, GateState):
        raise ValueError(f"{subject_id} subject gate must be a GateState")
    raw_severity = getattr(subject, "severity", None)
    if gate is GateState.BLOCKED:
        if raw_severity is not None:
            raise ValueError("blocked subject severity must be null")
        severity = None
        hits: tuple[str, ...] = ()
    else:
        if raw_severity is None:
            raise ValueError("assessable subject severity must not be null")
        severity = Severity(raw_severity)
        hits = _derived_rule_hits(subject, subject_id, severity)
    return SubjectSummary(subject_id, gate, severity, hits)


def aggregate_assessment(building: object, ground: object) -> AggregateAssessment:
    """Apply the approved aggregation truth table without hiding partial results."""

    subjects = {
        "building": _summarize(building, "building"),
        "ground": _summarize(ground, "ground"),
    }
    gate = combine_gate_states(*(subject.gate for subject in subjects.values()))
    partial = any(subject.gate is GateState.BLOCKED for subject in subjects.values())
    if partial:
        return AggregateAssessment(gate, None, True, (), (), subjects)
    severity = max(
        subject.severity for subject in subjects.values() if subject.severity is not None
    )
    governing = tuple(
        subject_id
        for subject_id, subject in subjects.items()
        if subject.severity == severity
    )
    ordered_hits: list[str] = []
    for subject_id in governing:
        ordered_hits.extend(subjects[subject_id].governing_rule_hits)
    return AggregateAssessment(
        gate,
        Severity(severity),
        False,
        governing,
        _deduplicate(tuple(ordered_hits)),
        subjects,
    )
