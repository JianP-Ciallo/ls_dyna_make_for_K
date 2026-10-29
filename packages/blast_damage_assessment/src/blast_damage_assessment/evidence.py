"""Closed, typed provenance graph for every reported damage conclusion."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Iterable, Mapping

from .contracts import Severity


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DEPENDENCY_KINDS = {
    "source": (),
    "field": ("source",),
    "observation": ("field",),
    "metric": ("observation",),
    "rule_hit": ("metric",),
    "local_severity": ("rule_hit",),
    "aggregate_severity": ("local_severity",),
}


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _finite(value: object, name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


@dataclass(frozen=True)
class EvidenceNode:
    node_id: str
    kind: str
    dependencies: tuple[str, ...]
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        _text(self.node_id, "node_id")
        if self.kind not in _DEPENDENCY_KINDS:
            raise ValueError(f"unsupported evidence kind: {self.kind}")
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    def with_dependencies(self, dependencies: Iterable[str]) -> "EvidenceNode":
        return replace(self, dependencies=tuple(dependencies))

    def with_payload(self, payload: Mapping[str, object]) -> "EvidenceNode":
        return replace(self, payload=payload)


class EvidenceGraph:
    schema_version = "blast-evidence-graph@1"

    def __init__(self) -> None:
        self._nodes: dict[str, EvidenceNode] = {}

    @property
    def nodes(self) -> Mapping[str, EvidenceNode]:
        return MappingProxyType(self._nodes)

    def _add(
        self,
        node_id: str,
        kind: str,
        dependencies: Iterable[str],
        payload: Mapping[str, object],
    ) -> EvidenceNode:
        if node_id in self._nodes:
            raise ValueError(f"duplicate evidence node ID: {node_id}")
        node = EvidenceNode(node_id, kind, tuple(dependencies), payload)
        self._nodes[node_id] = node
        return node

    def add_source(self, node_id: str, *, path: str, sha256: str) -> EvidenceNode:
        return self._add(node_id, "source", (), {"path": _text(path, "path"), "sha256": sha256})

    def add_field(self, node_id: str, *, source_id: str, field_name: str) -> EvidenceNode:
        return self._add(node_id, "field", (source_id,), {"field_name": _text(field_name, "field_name")})

    def add_observation(
        self,
        node_id: str,
        *,
        field_id: str,
        entity_type: str,
        entity_id: int | str,
        state_index: int,
        time: float,
    ) -> EvidenceNode:
        if isinstance(state_index, bool) or not isinstance(state_index, int) or state_index < 0:
            raise ValueError("state_index must be a non-negative integer")
        return self._add(
            node_id,
            "observation",
            (field_id,),
            {
                "entity_type": _text(entity_type, "entity_type"),
                "entity_id": entity_id,
                "state_index": state_index,
                "time": _finite(time, "time"),
            },
        )

    def add_metric(
        self,
        node_id: str,
        *,
        observation_ids: Iterable[str],
        metric_name: str,
        raw_value: float,
        raw_unit: str,
        standard_value: float,
        standard_unit: str,
        conversion_id: str,
    ) -> EvidenceNode:
        return self._add(
            node_id,
            "metric",
            tuple(observation_ids),
            {
                "metric_name": _text(metric_name, "metric_name"),
                "raw_value": _finite(raw_value, "raw_value"),
                "raw_unit": raw_unit,
                "standard_value": _finite(standard_value, "standard_value"),
                "standard_unit": standard_unit,
                "conversion_id": conversion_id,
            },
        )

    def add_rule_hit(
        self,
        node_id: str,
        *,
        metric_id: str,
        rule_id: str,
        actual_value: float,
        limit_value: float,
        operator: str,
        severity: Severity,
    ) -> EvidenceNode:
        return self._add(
            node_id,
            "rule_hit",
            (metric_id,),
            {
                "rule_id": _text(rule_id, "rule_id"),
                "actual_value": _finite(actual_value, "actual_value"),
                "limit_value": _finite(limit_value, "limit_value"),
                "operator": _text(operator, "operator"),
                "severity": int(Severity(severity)),
            },
        )

    def add_local_severity(
        self,
        node_id: str,
        *,
        rule_hit_ids: Iterable[str],
        subject_id: str,
        severity: Severity,
    ) -> EvidenceNode:
        return self._add(
            node_id,
            "local_severity",
            tuple(rule_hit_ids),
            {"subject_id": _text(subject_id, "subject_id"), "severity": int(Severity(severity))},
        )

    def add_aggregate_severity(
        self,
        node_id: str,
        *,
        local_severity_ids: Iterable[str],
        severity: Severity,
    ) -> EvidenceNode:
        return self._add(
            node_id,
            "aggregate_severity",
            tuple(local_severity_ids),
            {"severity": int(Severity(severity))},
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "nodes": [
                {
                    "id": node.node_id,
                    "kind": node.kind,
                    "dependencies": list(node.dependencies),
                    **dict(node.payload),
                }
                for node in sorted(self._nodes.values(), key=lambda value: value.node_id)
            ],
        }


def _validate_acyclic(nodes: Mapping[str, EvidenceNode]) -> None:
    state: dict[str, int] = {}

    def visit(node_id: str) -> None:
        marker = state.get(node_id, 0)
        if marker == 1:
            raise ValueError(f"cyclic evidence derivation at {node_id}")
        if marker == 2:
            return
        state[node_id] = 1
        for dependency in nodes[node_id].dependencies:
            visit(dependency)
        state[node_id] = 2

    for node_id in sorted(nodes):
        visit(node_id)


def validate_evidence_graph(graph: EvidenceGraph) -> None:
    if not isinstance(graph, EvidenceGraph):
        raise TypeError("graph must be an EvidenceGraph")
    nodes = graph._nodes
    for node in nodes.values():
        for dependency in node.dependencies:
            if dependency not in nodes:
                raise ValueError(f"dangling evidence dependency: {dependency}")
    _validate_acyclic(nodes)
    for node in nodes.values():
        expected = _DEPENDENCY_KINDS[node.kind]
        if node.kind == "source":
            if node.dependencies:
                raise ValueError("source nodes cannot derive from other evidence")
            sha256 = node.payload.get("sha256")
            if not isinstance(sha256, str) or _SHA256_RE.fullmatch(sha256) is None:
                raise ValueError("source sha256 must be 64 lowercase hexadecimal characters")
        else:
            if not node.dependencies:
                if node.kind == "local_severity":
                    raise ValueError("local severity conclusion requires a rule hit")
                raise ValueError(f"{node.kind} evidence requires dependencies")
            actual_kinds = {nodes[dependency].kind for dependency in node.dependencies}
            if actual_kinds != set(expected):
                raise ValueError(
                    f"{node.kind} must derive only from {', '.join(expected)} evidence"
                )
        if node.kind == "metric":
            for name in ("raw_unit", "standard_unit", "conversion_id"):
                if not isinstance(node.payload.get(name), str) or not str(node.payload[name]).strip():
                    raise ValueError("metric requires a complete unit conversion")
            _finite(node.payload.get("raw_value"), "raw_value")
            _finite(node.payload.get("standard_value"), "standard_value")
        elif node.kind == "rule_hit":
            actual = _finite(node.payload.get("actual_value"), "rule actual_value")
            limit = _finite(node.payload.get("limit_value"), "rule limit_value")
            operator = node.payload.get("operator")
            comparisons = {
                "<": lambda: actual < limit,
                "<=": lambda: actual <= limit,
                ">": lambda: actual > limit,
                ">=": lambda: actual >= limit,
                "==": lambda: actual == limit,
            }
            if operator not in comparisons:
                raise ValueError("rule operator is unsupported")
            if not comparisons[operator]():
                raise ValueError("rule actual/limit comparison is false")
            Severity(node.payload.get("severity"))
        elif node.kind in {"local_severity", "aggregate_severity"}:
            Severity(node.payload.get("severity"))
