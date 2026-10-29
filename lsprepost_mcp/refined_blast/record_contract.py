"""JSON record validation shared by storage and transport adapters."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any




class RecordError(Exception):
    """A stable record error code without an HTTP dependency."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def require_exact_keys(value: Mapping[str, object], expected: frozenset[str], label: str) -> None:
    actual = set(value)
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unknown:
        raise RecordError("unknown_field", f"{label} has unknown field: {unknown[0]}")
    if missing:
        raise RecordError("missing_field", f"{label} is missing required field: {missing[0]}")


def require_allowed_keys(value: Mapping[str, object], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise RecordError("unknown_field", f"{label} has unknown field: {unknown[0]}")


def require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RecordError("invalid_request", f"{label} must be an object")
    return value


def optional_mapping(value: object, label: str) -> Mapping[str, object] | None:
    if value is None:
        return None
    return require_mapping(value, label)


def optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return nonempty_string(value, label)


def nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecordError("invalid_request", f"{label} must be a non-empty string")
    return value.strip()


def positive_revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RecordError("invalid_request", "expected_revision must be a positive integer")
    return value


def sequence_or_default(value: object, label: str, default: tuple[float, float, float]) -> Sequence[object]:
    if value is None:
        return default
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise RecordError("invalid_request", f"{label} must be an array")
    return value


def json_value(value: object) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [json_value(item) for item in value]
    if isinstance(value, list):
        return [json_value(item) for item in value]
    return value
