"""Immutable cross-module validation results for Phase 18E."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from .providers.common import FrozenMapping, fingerprint_value, freeze_value


Severity = Literal["error", "warning", "info"]
_SEVERITIES = frozenset({"error", "warning", "info"})


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    finding_id: str
    severity: Severity
    module: str
    field_path: str
    message: str
    correction: str
    evidence: FrozenMapping = field(default_factory=lambda: MappingProxyType({}))
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("finding_id", "module", "field_path", "message", "correction"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"finding.{name} must be a non-empty string")
            object.__setattr__(self, name, value.strip())
        if self.severity not in _SEVERITIES:
            raise ValueError(f"unsupported finding severity: {self.severity!r}")
        evidence = freeze_value(self.evidence, "finding.evidence")
        if not isinstance(evidence, dict) and not hasattr(evidence, "items"):
            raise ValueError("finding.evidence must be a mapping")
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(
            self,
            "content_hash",
            fingerprint_value(
                {
                    "finding_id": self.finding_id,
                    "severity": self.severity,
                    "module": self.module,
                    "field_path": self.field_path,
                    "message": self.message,
                    "correction": self.correction,
                    "evidence": evidence,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ValidationResult:
    project_id: str
    project_revision: int
    project_fingerprint: str
    findings: tuple[ValidationFinding, ...]
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.project_revision, int) or isinstance(self.project_revision, bool) or self.project_revision < 1:
            raise ValueError("project_revision must be a positive integer")
        rows = tuple(self.findings)
        if any(not isinstance(row, ValidationFinding) for row in rows):
            raise TypeError("findings must contain ValidationFinding values")
        identities = tuple(row.finding_id for row in rows)
        if len(identities) != len(set(identities)):
            raise ValueError("validation contains duplicate finding IDs")
        object.__setattr__(self, "findings", tuple(sorted(rows, key=_finding_key)))
        object.__setattr__(
            self,
            "fingerprint",
            fingerprint_value(
                {
                    "project_id": self.project_id,
                    "project_revision": self.project_revision,
                    "project_fingerprint": self.project_fingerprint,
                    "findings": tuple(row.content_hash for row in sorted(rows, key=_finding_key)),
                }
            ),
        )

    @property
    def errors(self) -> tuple[ValidationFinding, ...]:
        return tuple(row for row in self.findings if row.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationFinding, ...]:
        return tuple(row for row in self.findings if row.severity == "warning")


def validation_result(
    *,
    project_id: str,
    project_revision: int,
    project_fingerprint: str,
    findings: Iterable[ValidationFinding],
) -> ValidationResult:
    return ValidationResult(project_id, project_revision, project_fingerprint, tuple(findings))


def _finding_key(row: ValidationFinding) -> tuple[int, str, str, str]:
    return ({"error": 0, "warning": 1, "info": 2}[row.severity], row.module, row.field_path, row.finding_id)


__all__ = ["Severity", "ValidationFinding", "ValidationResult", "validation_result"]
