"""Descriptor-only registry for Phase 18E load providers.

Descriptors are available before provider implementations exist.  Binding an
implementation is an explicit later action; lookup never fabricates one.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from threading import RLock
from types import MappingProxyType

from .contracts import BlastLoadProvider, ScenarioKind


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    supported_scenario_kinds: tuple[ScenarioKind, ...]
    schema_version: str
    implementation_bound: bool = False


_DESCRIPTORS: tuple[ProviderDescriptor, ...] = (
    ProviderDescriptor(
        provider_id="explicit_ale_fsi",
        supported_scenario_kinds=("external", "internal", "semi_enclosed"),
        schema_version="refined_building_blast@1",
    ),
    ProviderDescriptor(
        provider_id="lbe_segment",
        supported_scenario_kinds=("external", "internal", "semi_enclosed"),
        schema_version="refined_building_blast@1",
    ),
    ProviderDescriptor(
        provider_id="imported_pressure_history",
        supported_scenario_kinds=("external", "internal", "semi_enclosed"),
        schema_version="refined_building_blast@1",
    ),
    ProviderDescriptor(
        provider_id="solver_complete_ale_fsi",
        supported_scenario_kinds=("external",),
        schema_version="refined_building_blast@1",
    ),
)
_DESCRIPTORS_BY_ID = MappingProxyType(
    {descriptor.provider_id: descriptor for descriptor in _DESCRIPTORS}
)
_BOUND_PROVIDERS: dict[str, BlastLoadProvider] = {}
_LAZY_PROVIDER_TARGETS = MappingProxyType(
    {
        "explicit_ale_fsi": (
            "lsprepost_mcp.refined_blast.providers.explicit_ale_fsi",
            "ExplicitAleFsiProvider",
        ),
        "lbe_segment": (
            "lsprepost_mcp.refined_blast.providers.lbe_segment",
            "LbeSegmentProvider",
        ),
        "imported_pressure_history": (
            "lsprepost_mcp.refined_blast.providers.imported_pressure_history",
            "ImportedPressureHistoryProvider",
        ),
        "solver_complete_ale_fsi": (
            "lsprepost_mcp.refined_blast.providers.solver_complete_ale_fsi",
            "SolverCompleteAleFsiProvider",
        ),
    }
)
_BIND_LOCK = RLock()


def list_load_providers() -> tuple[ProviderDescriptor, ...]:
    """List all declared provider capabilities without importing implementations."""

    return tuple(
        ProviderDescriptor(
            provider_id=descriptor.provider_id,
            supported_scenario_kinds=descriptor.supported_scenario_kinds,
            schema_version=descriptor.schema_version,
            implementation_bound=descriptor.provider_id in _BOUND_PROVIDERS,
        )
        for descriptor in _DESCRIPTORS
    )


def bind_load_provider(provider_id: str, provider: BlastLoadProvider) -> None:
    """Explicitly bind a later provider implementation to a declared descriptor."""

    _require_declared_provider(provider_id)
    if getattr(provider, "provider_id", None) != provider_id:
        raise ValueError("provider_id does not match the declared provider")
    with _BIND_LOCK:
        _BOUND_PROVIDERS[provider_id] = provider


def get_load_provider(provider_id: str) -> BlastLoadProvider:
    """Return a bound provider or fail closed; descriptors are not providers."""

    _require_declared_provider(provider_id)
    provider = _BOUND_PROVIDERS.get(provider_id)
    if provider is None:
        provider = _load_provider(provider_id)
    if provider is None:
        raise ValueError(f"load provider is declared but not bound: {provider_id!r}")
    return provider


def _load_provider(provider_id: str) -> BlastLoadProvider | None:
    target = _LAZY_PROVIDER_TARGETS.get(provider_id)
    if target is None:
        return None
    with _BIND_LOCK:
        existing = _BOUND_PROVIDERS.get(provider_id)
        if existing is not None:
            return existing
        module_name, factory_name = target
        module = importlib.import_module(module_name)
        factory = getattr(module, factory_name)
        provider = factory()
        bind_load_provider(provider_id, provider)
        return _BOUND_PROVIDERS[provider_id]


def _require_declared_provider(provider_id: str) -> ProviderDescriptor:
    if not isinstance(provider_id, str) or provider_id not in _DESCRIPTORS_BY_ID:
        raise ValueError(f"unsupported provider: {provider_id!r}")
    return _DESCRIPTORS_BY_ID[provider_id]
