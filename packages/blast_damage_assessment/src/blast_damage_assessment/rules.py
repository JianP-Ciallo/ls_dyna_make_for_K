"""Versioned, immutable damage-assessment rule packs."""

from __future__ import annotations

import importlib.resources
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .canonical import canonical_json_bytes, sha256_json
from .errors import ContractError, UnsupportedSchemaError


RULE_PACK_SCHEMA = "blast_damage.rule_pack@1"
_BUILTIN_FILES = {
    "building_research_reference@1": "building_research_reference_v1.json",
    "ground_research_reference@1": "ground_research_reference_v1.json",
}
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise ContractError(f"unsupported rule-pack value: {type(value).__name__}")


@dataclass(frozen=True)
class RulePack:
    pack_id: str
    subject: str
    formal_eligible: bool
    payload: Mapping[str, object]
    rules: tuple[Mapping[str, object], ...]

    def rule(self, rule_id: str) -> Mapping[str, object]:
        for rule in self.rules:
            if rule["id"] == rule_id:
                return rule
        raise KeyError(rule_id)


@dataclass(frozen=True)
class RuleSnapshot:
    schema_version: str
    pack_id: str
    sha256: str
    payload: Mapping[str, object]


@dataclass(frozen=True)
class ApplicabilityResult:
    applicable: bool
    missing: tuple[str, ...]
    mismatches: tuple[str, ...]


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a non-empty string")
    return value


def _load_json(source: str | Path) -> Mapping[str, object]:
    if isinstance(source, Path) or (isinstance(source, str) and source not in _BUILTIN_FILES):
        path = Path(source)
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise ContractError(f"rule pack is unavailable: {path}: {exc}") from exc
    else:
        name = _BUILTIN_FILES[source]
        payload = (
            importlib.resources.files("blast_damage_assessment")
            .joinpath("rule_packs", name)
            .read_bytes()
        )
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid rule-pack JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError("rule-pack root must be an object")
    return value


def _validate_bands(value: object, rule_id: str) -> None:
    if not isinstance(value, list) or len(value) != 4:
        raise ContractError(f"rule {rule_id} bands must contain four thresholds")
    numbers: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
            raise ContractError(f"rule {rule_id} bands must be finite numbers")
        numbers.append(float(item))
    if any(left >= right for left, right in zip(numbers, numbers[1:])):
        raise ContractError(f"rule {rule_id} bands must be strictly monotonic")


def _validate_formal(raw: Mapping[str, object]) -> None:
    bindings = raw.get("bindings")
    review = raw.get("review_record")
    if not isinstance(bindings, dict) or not isinstance(review, dict):
        raise ContractError("formal-eligible rule pack requires bindings and a review record")
    for key in (
        "unit_system",
        "material_ids",
        "subject_family",
        "geometry_assumptions",
        "applicability_predicates",
    ):
        if key not in bindings:
            raise ContractError(f"formal rule bindings are missing {key}")
    _required_text(bindings["unit_system"], "bindings.unit_system")
    _required_text(bindings["subject_family"], "bindings.subject_family")
    material_ids = bindings["material_ids"]
    if not isinstance(material_ids, list) or not material_ids or any(
        isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in material_ids
    ):
        raise ContractError("bindings.material_ids must contain positive integers")
    assumptions = bindings["geometry_assumptions"]
    if not isinstance(assumptions, dict) or not assumptions:
        raise ContractError("bindings.geometry_assumptions must be non-empty")
    predicates = bindings["applicability_predicates"]
    if not isinstance(predicates, list) or not predicates or any(
        not isinstance(item, str) or not item.strip() for item in predicates
    ):
        raise ContractError("bindings.applicability_predicates must be non-empty")
    for key in ("reviewer", "review_date", "source", "reviewed_binding_sha256"):
        _required_text(review.get(key), f"review_record.{key}")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(review["review_date"])) is None:
        raise ContractError("review_record.review_date must use YYYY-MM-DD")
    expected = review["reviewed_binding_sha256"]
    if _HASH_RE.fullmatch(str(expected)) is None or expected != sha256_json(bindings):
        raise ContractError("review record hash does not match the bound formal parameters")


def load_rule_pack(pack_id: str | Path) -> RulePack:
    raw = _load_json(pack_id)
    schema = _required_text(raw.get("schema_version"), "schema_version")
    if schema != RULE_PACK_SCHEMA:
        raise UnsupportedSchemaError(f"unsupported rule-pack schema {schema}; expected {RULE_PACK_SCHEMA}")
    declared_id = _required_text(raw.get("pack_id"), "pack_id")
    if isinstance(pack_id, str) and pack_id in _BUILTIN_FILES and declared_id != pack_id:
        raise ContractError("built-in rule-pack ID does not match its file")
    subject = _required_text(raw.get("subject"), "subject")
    if subject not in {"building", "ground"}:
        raise ContractError("rule-pack subject must be building or ground")
    formal = raw.get("formal_eligible")
    if not isinstance(formal, bool):
        raise ContractError("formal_eligible must be boolean")
    _required_text(raw.get("label"), "label")
    citations = raw.get("citations")
    if not isinstance(citations, list) or not citations:
        raise ContractError("rule pack must contain at least one citation")
    citation_ids: set[str] = set()
    for citation in citations:
        if not isinstance(citation, dict):
            raise ContractError("citation must be an object")
        citation_id = _required_text(citation.get("id"), "citation.id")
        if citation_id in citation_ids:
            raise ContractError(f"duplicate citation ID: {citation_id}")
        citation_ids.add(citation_id)
        for key in ("title", "edition", "section", "url"):
            _required_text(citation.get(key), f"citation.{key}")
    rules = raw.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ContractError("rule pack must contain rules")
    rule_ids: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise ContractError("rule must be an object")
        rule_id = _required_text(rule.get("id"), "rule.id")
        if rule_id in rule_ids:
            raise ContractError(f"duplicate rule ID: {rule_id}")
        rule_ids.add(rule_id)
        _required_text(rule.get("kind"), f"rule {rule_id} kind")
        applicability = rule.get("applicability")
        if not isinstance(applicability, list) or not applicability or any(
            not isinstance(item, str) or not item.strip() for item in applicability
        ):
            raise ContractError(f"rule {rule_id} applicability must be non-empty")
        rule_citations = rule.get("citations")
        if not isinstance(rule_citations, list) or not rule_citations:
            raise ContractError(f"rule {rule_id} citation list must be non-empty")
        if any(item not in citation_ids for item in rule_citations):
            raise ContractError(f"rule {rule_id} references an unknown citation")
        if "bands" in rule:
            _validate_bands(rule["bands"], rule_id)
    if formal:
        _validate_formal(raw)
    frozen = _freeze(raw)
    assert isinstance(frozen, Mapping)
    frozen_rules = frozen["rules"]
    assert isinstance(frozen_rules, tuple)
    return RulePack(declared_id, subject, formal, frozen, frozen_rules)  # type: ignore[arg-type]


def snapshot_rule_pack(pack: RulePack) -> RuleSnapshot:
    digest = sha256_json(pack.payload)
    return RuleSnapshot(RULE_PACK_SCHEMA, pack.pack_id, digest, pack.payload)


def check_rule_applicability(
    pack: RulePack,
    subject: Mapping[str, object],
    *,
    rule_id: str | None = None,
) -> ApplicabilityResult:
    if rule_id is None:
        selected = pack.rules
    else:
        selected = (pack.rule(rule_id),)
    required: set[str] = set()
    for rule in selected:
        required.update(rule["applicability"])  # type: ignore[arg-type]
    bindings = pack.payload.get("bindings")
    if isinstance(bindings, Mapping):
        required.update(bindings["applicability_predicates"])  # type: ignore[arg-type]
    missing = sorted(name for name in required if not subject.get(name))
    mismatches: list[str] = []
    if isinstance(bindings, Mapping):
        for key in ("unit_system", "subject_family", "geometry_assumptions"):
            if subject.get(key) != bindings.get(key):
                mismatches.append(key)
        actual_materials = subject.get("material_ids")
        expected_materials = bindings.get("material_ids")
        if not isinstance(actual_materials, (list, tuple, set)) or set(actual_materials) != set(expected_materials):  # type: ignore[arg-type]
            mismatches.append("material_ids")
    return ApplicabilityResult(not missing and not mismatches, tuple(missing), tuple(sorted(mismatches)))
