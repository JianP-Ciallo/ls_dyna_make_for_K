"""Small facade that compiles a refined building without scene dependencies."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from .artifacts import BuildingArtifact
from .backends.hybrid import compile_steel_concrete_hybrid
from .backends.rc import compile_rc_structure
from .backends.rc_box import compile_rc_box
from .backends.steel import compile_steel_frame
from .contracts import normalize_building_definition
from .meshing import merge_fragments
from .nonstructural import compile_nonstructural
from .spatial import compile_spatial_topology
from .surfaces import build_fluid_exposed_surface_catalog
from .systems import get_structural_system, normalize_structural_system_profile
from .validation import validate_building_artifact


def compile_refined_building(definition: Mapping[str, object]) -> BuildingArtifact:
    """Compile one deterministic building artifact from a normalized contract."""

    normalized = normalize_building_definition(definition)
    profile_raw = normalized["structural_system"]
    assert isinstance(profile_raw, dict)
    profile = normalize_structural_system_profile(profile_raw)
    normalized["structural_system"] = profile
    system_id = profile["type"]
    assert isinstance(system_id, str)
    descriptor = get_structural_system(system_id)
    topology = compile_spatial_topology(normalized)

    if descriptor.backend_key == "rc":
        artifact = compile_rc_structure(normalized, topology, descriptor)
    elif descriptor.backend_key == "steel":
        artifact = compile_steel_frame(normalized, topology, descriptor)
    elif descriptor.backend_key == "hybrid":
        artifact = compile_steel_concrete_hybrid(normalized, topology, descriptor)
    elif descriptor.backend_key == "rc_box":
        artifact = compile_rc_box(normalized, topology, descriptor)
    elif descriptor.backend_key == "custom_hybrid":
        raise ValueError("custom_hybrid backend is not yet available in Phase 18C-1")
    else:
        raise ValueError(f"no backend registered for {system_id!r}")

    nonstructural_rows = normalized["nonstructural"]
    assert isinstance(nonstructural_rows, list)
    if nonstructural_rows:
        nonstructural = compile_nonstructural(normalized, artifact)
        artifact = replace(artifact, mesh=merge_fragments((artifact.mesh, nonstructural)))

    surface_catalog = build_fluid_exposed_surface_catalog(artifact, topology)
    artifact = replace(artifact, normalized_input=normalized, surface_catalog=surface_catalog)
    report = validate_building_artifact(artifact)
    findings = report["findings"]
    assert isinstance(findings, list)
    finding_codes = tuple(
        str(row.get("code", "unknown")) for row in findings if isinstance(row, dict)
    )
    return replace(artifact, validation_findings=finding_codes)
