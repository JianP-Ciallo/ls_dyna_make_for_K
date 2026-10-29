from __future__ import annotations

from collections.abc import Mapping


def normalize_resource_identity(
    resource: Mapping[str, object],
    raw_id: str,
    legacy_aliases: Mapping[str, str],
    kind: str,
) -> dict[str, object]:
    canonical_id = legacy_aliases.get(raw_id, raw_id)
    declared = resource.get("aliases", [])
    if not isinstance(declared, list):
        raise ValueError(f"{kind} resource '{raw_id}' aliases must be a list")

    aliases: list[str] = []
    for value in declared:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{kind} resource '{raw_id}' aliases must contain non-empty strings")
        alias = value.strip()
        if alias not in aliases:
            aliases.append(alias)
    for legacy_id, target_id in legacy_aliases.items():
        if target_id == canonical_id and legacy_id not in aliases:
            aliases.append(legacy_id)

    normalized = dict(resource)
    normalized["id"] = canonical_id
    if not str(normalized.get("name", "")).strip() or normalized.get("name") == raw_id:
        normalized["name"] = canonical_id
    normalized["aliases"] = sorted(aliases)
    return normalized


def build_alias_index(
    resources: Mapping[str, Mapping[str, object]],
    kind: str,
) -> dict[str, str]:
    canonical_ids = set(resources)
    aliases: dict[str, str] = {}
    for canonical_id, resource in resources.items():
        declared = resource.get("aliases", [])
        if not isinstance(declared, list):
            raise ValueError(f"{kind} resource '{canonical_id}' aliases must be a list")
        for value in declared:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{kind} resource '{canonical_id}' aliases must contain non-empty strings")
            alias = value.strip()
            if alias == canonical_id:
                raise ValueError(f"{kind} resource '{canonical_id}' cannot alias itself")
            if alias in canonical_ids:
                raise ValueError(f"{kind} resource alias '{alias}' collides with a canonical id")
            previous = aliases.get(alias)
            if previous is not None and previous != canonical_id:
                raise ValueError(
                    f"duplicate {kind} resource alias '{alias}' for '{previous}' and '{canonical_id}'"
                )
            aliases[alias] = canonical_id
    return aliases


def resolve_resource_id(
    requested_id: str,
    resources: Mapping[str, Mapping[str, object]],
    kind: str,
) -> tuple[str, Mapping[str, object]]:
    if requested_id in resources:
        return requested_id, resources[requested_id]
    aliases = build_alias_index(resources, kind)
    canonical_id = aliases.get(requested_id)
    if canonical_id is None:
        known = sorted([*resources, *aliases])
        raise ValueError(
            f"unknown {kind} resource '{requested_id}'. Known resources: {', '.join(known) or '<none>'}"
        )
    return canonical_id, resources[canonical_id]
