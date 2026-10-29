"""Immutable public contracts used by every assessment stage."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum, EnumMeta, IntEnum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .canonical import canonical_json_bytes


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHORT_HASH_RE = re.compile(r"^[0-9a-f]{24}$")


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _sha256(value: object, field_name: str = "sha256") -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be 64 lowercase hexadecimal characters")
    return value


def _finite_number(value: object, field_name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number")
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be a finite number")
    return value


class _StrictIntEnumMeta(EnumMeta):
    def __call__(cls, value, *args, **kwargs):  # type: ignore[no-untyped-def]
        if isinstance(value, bool):
            raise ValueError(f"{value!r} is not a valid {cls.__qualname__}")
        return super().__call__(value, *args, **kwargs)


class GateState(str, Enum):
    FORMAL = "formal"
    PROVISIONAL = "provisional"
    BLOCKED = "blocked"


class Severity(IntEnum, metaclass=_StrictIntEnumMeta):
    NO_OBVIOUS = 0
    MINOR = 1
    MODERATE = 2
    SEVERE = 3
    EXTREME = 4


@dataclass(frozen=True)
class FileReference:
    path: Path
    sha256: str
    schema_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or not str(self.path):
            raise ValueError("path must be a non-empty Path")
        _sha256(self.sha256)
        if self.schema_version is not None:
            _required_text(self.schema_version, "schema_version")


@dataclass(frozen=True)
class AssessmentRequest:
    schema_version: str
    project_id: str
    case_id: str
    result_dir: Path
    semantic_manifest: FileReference
    building_rule_pack: str
    ground_rule_pack: str
    output_dir: Path
    state_chunk_size: int = 4

    def __post_init__(self) -> None:
        _required_text(self.schema_version, "schema_version")
        _required_text(self.project_id, "project_id")
        _required_text(self.case_id, "case_id")
        _required_text(self.building_rule_pack, "building_rule_pack")
        _required_text(self.ground_rule_pack, "ground_rule_pack")
        if not isinstance(self.result_dir, Path) or not str(self.result_dir):
            raise ValueError("result_dir must be a non-empty Path")
        if not isinstance(self.output_dir, Path) or not str(self.output_dir):
            raise ValueError("output_dir must be a non-empty Path")
        if not isinstance(self.semantic_manifest, FileReference):
            raise ValueError("semantic_manifest must be a FileReference")
        if isinstance(self.state_chunk_size, bool) or not isinstance(self.state_chunk_size, int):
            raise ValueError("state_chunk_size must be a positive integer")
        if self.state_chunk_size <= 0:
            raise ValueError("state_chunk_size must be a positive integer")


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _required_text(self.code, "code")
        _required_text(self.message, "message")
        if not isinstance(self.details, Mapping):
            raise ValueError("details must be a mapping")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


@dataclass(frozen=True)
class MetricValue:
    raw_value: int | float | None
    raw_unit: str | None
    standard_value: int | float | None
    standard_unit: str | None
    conversion_id: str | None
    available: bool = True
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.available, bool):
            raise ValueError("available must be boolean")
        if self.available:
            _finite_number(self.raw_value, "raw_value")
            _finite_number(self.standard_value, "standard_value")
            _required_text(self.raw_unit, "raw_unit")
            _required_text(self.standard_unit, "standard_unit")
            _required_text(self.conversion_id, "conversion_id")
            if self.unavailable_reason is not None:
                raise ValueError("available metric cannot have unavailable_reason")
        else:
            _required_text(self.unavailable_reason, "unavailable_reason")
            if any(
                value is not None
                for value in (
                    self.raw_value,
                    self.raw_unit,
                    self.standard_value,
                    self.standard_unit,
                    self.conversion_id,
                )
            ):
                raise ValueError("unavailable metric values and units must be null")

    @classmethod
    def unavailable(cls, reason: str) -> "MetricValue":
        return cls(None, None, None, None, None, available=False, unavailable_reason=reason)


@dataclass(frozen=True)
class ArtifactReference:
    path: Path
    sha256: str
    media_type: str
    size_bytes: int
    schema_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or not str(self.path):
            raise ValueError("path must be a non-empty Path")
        _sha256(self.sha256)
        _required_text(self.media_type, "media_type")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
            raise ValueError("size_bytes must be a non-negative integer")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be a non-negative integer")
        if self.schema_version is not None:
            _required_text(self.schema_version, "schema_version")


@dataclass(frozen=True)
class AssessmentResult:
    schema_version: str
    assessment_id: str
    execution_status: str
    gate: GateState
    severity: int | None
    assessment_fingerprint: str | None
    artifacts: Mapping[str, ArtifactReference]
    warnings: tuple[Issue, ...] = ()
    blockers: tuple[Issue, ...] = ()
    review_items: tuple[Issue, ...] = ()
    state_chunk_size: int = 4

    def __post_init__(self) -> None:
        _required_text(self.schema_version, "schema_version")
        if not isinstance(self.assessment_id, str) or _SHORT_HASH_RE.fullmatch(self.assessment_id) is None:
            raise ValueError("assessment_id must be 24 lowercase hexadecimal characters")
        if self.execution_status not in {"completed", "failed"}:
            raise ValueError("execution_status must be completed or failed")
        if not isinstance(self.gate, GateState):
            raise ValueError("gate must be a GateState")
        if self.severity is not None:
            Severity(self.severity)
        if self.gate is GateState.BLOCKED and self.severity is not None:
            raise ValueError("blocked assessment severity must be null")
        if self.assessment_fingerprint is not None:
            _sha256(self.assessment_fingerprint, "assessment_fingerprint")
        if not isinstance(self.artifacts, Mapping):
            raise ValueError("artifacts must be a mapping")
        object.__setattr__(self, "artifacts", MappingProxyType(dict(self.artifacts)))
        for name in ("warnings", "blockers", "review_items"):
            value = tuple(getattr(self, name))
            if not all(isinstance(issue, Issue) for issue in value):
                raise ValueError(f"{name} must contain Issue values")
            object.__setattr__(self, name, value)
        if isinstance(self.state_chunk_size, bool) or not isinstance(self.state_chunk_size, int):
            raise ValueError("state_chunk_size must be a positive integer")
        if self.state_chunk_size <= 0:
            raise ValueError("state_chunk_size must be a positive integer")

    def to_dict(self) -> dict[str, object]:
        """Return the complete, JSON-safe public result representation."""

        def artifact_record(reference: ArtifactReference) -> dict[str, object]:
            return {
                "path": reference.path.as_posix(),
                "sha256": reference.sha256,
                "media_type": reference.media_type,
                "size_bytes": reference.size_bytes,
                "schema_version": reference.schema_version,
            }

        def issue_record(issue: Issue) -> dict[str, object]:
            return {
                "code": issue.code,
                "message": issue.message,
                "details": json.loads(canonical_json_bytes(issue.details)),
            }

        return {
            "schema_version": self.schema_version,
            "assessment_id": self.assessment_id,
            "execution_status": self.execution_status,
            "gate": self.gate.value,
            "severity": self.severity,
            "assessment_fingerprint": self.assessment_fingerprint,
            "artifacts": {
                name: artifact_record(reference)
                for name, reference in sorted(self.artifacts.items())
            },
            "warnings": [issue_record(issue) for issue in self.warnings],
            "blockers": [issue_record(issue) for issue in self.blockers],
            "review_items": [issue_record(issue) for issue in self.review_items],
            "state_chunk_size": self.state_chunk_size,
        }
