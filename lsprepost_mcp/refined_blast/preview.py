"""Deterministic layered previews built only from immutable public artifacts."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import chain
from typing import Literal

from lsprepost_mcp.refined_building.artifacts import BuildingArtifact
from lsprepost_mcp.refined_building.asset_resources import (
    get_detailed_building_asset,
)
from lsprepost_mcp.refined_building.solver_blast.charge import tnt_side_length_m

from .assembler import RefinedBlastPackage
from .contracts import RefinedBlastProject
from .providers.common import FrozenMapping, fingerprint_value, freeze_value, thaw_value


CountSemantics = Literal["exact", "upper_bound"]
PREVIEW_LAYER_IDS = (
    "cavities_openings",
    "structure",
    "reinforcement_connections",
    "nonstructural",
    "exposed_surfaces",
    "blast_source",
    "fluid_domain",
    "boundaries",
    "support_ground",
)
PREVIEW_COUNT_METRICS = (
    "building_nodes",
    "building_elements",
    "provider_nodes",
    "provider_elements",
    "provider_fsi_faces",
    "module_new_nodes",
    "module_new_elements",
    "symbolic_ids",
)
_MAX_PREVIEW_COUNT = 100_000_000
_MAX_PREVIEW_SOURCE_ELEMENTS = 1_000_000
_MAX_NEUTRAL_SOURCE_ITEMS_PER_LAYER = 512
_MAX_NEUTRAL_PRIMITIVES_PER_LAYER = 4
_MAX_NEUTRAL_PRIMITIVE_BYTES_PER_LAYER = 2_000_000


@dataclass(frozen=True, slots=True)
class _NeutralPrimitiveBuild:
    primitives: tuple[Mapping[str, object], ...]
    source_item_count: int
    rendered_item_count: int


@dataclass(frozen=True, slots=True)
class PreviewLayer:
    layer_id: str
    payload: FrozenMapping
    source_fingerprints: tuple[str, ...]
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.layer_id not in PREVIEW_LAYER_IDS:
            raise ValueError(f"unsupported preview layer: {self.layer_id!r}")
        payload = freeze_value(self.payload, f"preview.{self.layer_id}")
        if not isinstance(payload, Mapping):
            raise ValueError("preview layer payload must be a mapping")
        fingerprints = tuple(self.source_fingerprints)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "source_fingerprints", fingerprints)
        object.__setattr__(self, "fingerprint", fingerprint_value({"layer_id": self.layer_id, "payload": payload, "source_fingerprints": fingerprints}))


@dataclass(frozen=True, slots=True)
class PreviewCount:
    metric: str
    value: int
    semantics: CountSemantics

    def __post_init__(self) -> None:
        if not isinstance(self.value, int) or isinstance(self.value, bool) or self.value < 0:
            raise ValueError("preview count must be a non-negative bounded integer")
        if self.value > _MAX_PREVIEW_COUNT:
            raise ValueError("preview count exceeds orchestration safety limit")
        if self.semantics not in {"exact", "upper_bound"}:
            raise ValueError("unsupported preview count semantics")


@dataclass(frozen=True, slots=True)
class RefinedBlastPreview:
    project_id: str
    scenario_id: str
    project_revision: int
    cache_key: str
    layers: tuple[PreviewLayer, ...]
    counts: tuple[PreviewCount, ...]
    is_final: bool
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        layers = tuple(self.layers)
        if tuple(row.layer_id for row in layers) != PREVIEW_LAYER_IDS:
            raise ValueError("preview layers must exactly cover the Phase 18E layer contract")
        counts = tuple(self.counts)
        if tuple(row.metric for row in counts) != PREVIEW_COUNT_METRICS:
            raise ValueError("preview counts must exactly cover the closed metric family")
        object.__setattr__(self, "layers", layers)
        object.__setattr__(self, "counts", counts)
        object.__setattr__(self, "fingerprint", fingerprint_value({"project_id": self.project_id, "scenario_id": self.scenario_id, "project_revision": self.project_revision, "cache_key": self.cache_key, "layers": tuple(row.fingerprint for row in layers), "counts": tuple((row.metric, row.value, row.semantics) for row in counts), "is_final": self.is_final}))

    def compare_generated(self, package: RefinedBlastPackage) -> tuple[str, ...]:
        rendered = package.manifest.get("rendered_counts")
        if not isinstance(rendered, Mapping):
            return ("generated package has no rendered_counts evidence",)
        mismatches: list[str] = []
        unknown = sorted(set(rendered) - set(PREVIEW_COUNT_METRICS))
        if unknown:
            mismatches.append(f"unknown generated count: {unknown[0]}")
        for row in self.counts:
            actual = rendered.get(row.metric)
            if (
                not isinstance(actual, int)
                or isinstance(actual, bool)
                or actual < 0
                or actual > _MAX_PREVIEW_COUNT
            ):
                mismatches.append(f"{row.metric}: invalid generated count")
            elif row.semantics == "exact" and actual != row.value:
                mismatches.append(f"{row.metric}: expected exactly {row.value}, found {actual}")
            elif row.semantics == "upper_bound" and actual > row.value:
                mismatches.append(f"{row.metric}: upper bound {row.value} exceeded by {actual}")
        return tuple(mismatches)


def build_refined_blast_preview(
    project: RefinedBlastProject,
    artifact: BuildingArtifact,
    package: RefinedBlastPackage,
    *,
    provider_preview: Mapping[str, object],
    module_payloads: Mapping[str, Mapping[str, object]],
    revision: int,
    cache_key: str,
    is_final: bool,
) -> RefinedBlastPreview:
    if len(project.scenario_set) != 1:
        raise ValueError("one preview represents exactly one scenario")
    _enforce_preview_source_budget(artifact, module_payloads)
    scenario = project.scenario_set[0]
    roles = {
        row.element_id: row.part_role
        for row in (*artifact.mesh.solids, *artifact.mesh.shells, *artifact.mesh.beams)
    }
    reinforcement_ids = tuple(sorted(element_id for element_id, role in roles.items() if _is_reinforcement(role)))
    nonstructural_ids = tuple(sorted(element_id for element_id, role in roles.items() if "nonstructural" in role))
    structure_ids = tuple(sorted(set(roles) - set(reinforcement_ids) - set(nonstructural_ids)))
    connections_payload = tuple(
        {
            "id": row.connection_id,
            "type": row.connection_type,
            "source_element_ids": row.source_element_ids,
            "target_element_ids": row.target_element_ids,
            "metadata": dict(row.metadata),
        }
        for row in artifact.connections
    )
    fragment_fingerprints = dict(package.manifest.get("fragment_fingerprints", ()))
    cavities_payload = {
        "void_regions": artifact.topology_manifest.get("void_regions", ()),
        "openings": artifact.normalized_input.get("openings", ()),
    }
    exposed_payload = {"catalog": artifact.surface_catalog}
    blast_payload = {
        "provider_id": scenario.load_provider["provider_id"],
        "input_fingerprint": fingerprint_value(scenario.load_provider["provider_input"]),
        "provider_preview": provider_preview,
    }
    fluid_payload = module_payloads.get("fluid_domain", {})
    fluid_from_provider = False
    if not fluid_payload and provider_preview.get("domain_bounds_m") is not None:
        fluid_payload = {
            "bounds_m": provider_preview["domain_bounds_m"],
            "active_air_bounds_m": provider_preview.get(
                "active_air_bounds_m", provider_preview["domain_bounds_m"]
            ),
            "coupling_buffer_bounds_m": provider_preview.get(
                "coupling_buffer_bounds_m"
            ),
            "coupling_buffer_layers": provider_preview.get(
                "coupling_buffer_layers"
            ),
            "representation": "visible_solver_complete_air_domain",
        }
        fluid_from_provider = True
    boundaries_payload = module_payloads.get("boundaries", {})
    support_payload = module_payloads.get("support_ground", {})
    support_from_provider = False
    if not support_payload and provider_preview.get("ground_bounds_m") is not None:
        support_payload = {
            "bounds_m": provider_preview["ground_bounds_m"],
            "representation": "visible_solver_complete_ground",
        }
        support_from_provider = True
    layers = (
        PreviewLayer("cavities_openings", _with_primitives(cavities_payload, _bounds_primitives(cavities_payload, "cavity")), (artifact.fingerprint, str(artifact.topology_manifest.get("fingerprint", "")))),
        PreviewLayer("structure", _with_primitives({"element_ids": structure_ids}, _artifact_mesh_primitives(artifact, structure_ids, "structure")), (artifact.mesh.fingerprint,)),
        PreviewLayer("reinforcement_connections", _with_primitives({"reinforcement_element_ids": reinforcement_ids, "connections": connections_payload}, _artifact_mesh_primitives(artifact, reinforcement_ids, "reinforcement")), (artifact.fingerprint,)),
        PreviewLayer("nonstructural", _with_primitives({"element_ids": nonstructural_ids}, _artifact_mesh_primitives(artifact, nonstructural_ids, "nonstructural")), (artifact.fingerprint,)),
        PreviewLayer("exposed_surfaces", _with_primitives(exposed_payload, _catalog_surface_primitives(artifact, artifact.surface_catalog, "exposed")), (artifact.fingerprint,)),
        PreviewLayer("blast_source", _with_primitives(blast_payload, _blast_source_primitives(scenario.load_provider, provider_preview)), (str(package.manifest["provider_fingerprint"]),)),
        PreviewLayer(
            "fluid_domain",
            _with_primitives(
                fluid_payload,
                _combine_primitive_builds(
                    _single_primitive_build(
                        _box_primitive(
                            "active-air-proxy",
                            fluid_payload["active_air_bounds_m"],
                        )
                    ),
                    *(
                        (
                            _single_primitive_build(
                                _box_primitive(
                                    "coupling-buffer-proxy",
                                    fluid_payload["coupling_buffer_bounds_m"],
                                )
                            ),
                        )
                        if fluid_payload.get("coupling_buffer_bounds_m") is not None
                        else ()
                    ),
                )
                if fluid_from_provider
                else _bounds_primitives(fluid_payload, "fluid"),
            ),
            tuple(filter(None, (fragment_fingerprints.get("fluid_domain", ""),))),
        ),
        PreviewLayer("boundaries", _with_primitives(boundaries_payload, _catalog_surface_primitives(artifact, boundaries_payload.get("surfaces", ()), "boundary")), tuple(filter(None, (fragment_fingerprints.get("boundaries", ""),)))),
        PreviewLayer("support_ground", _with_primitives(support_payload, _bounds_primitives(support_payload, "support") if support_from_provider else _module_mesh_primitives(support_payload, "support")), tuple(filter(None, (fragment_fingerprints.get("support_ground", ""), str(package.manifest["provider_fingerprint"]) if support_from_provider else "")))),
    )
    rendered = package.manifest["rendered_counts"]
    assert isinstance(rendered, Mapping)
    counts = tuple(
        PreviewCount(metric, int(rendered[metric]), semantics)
        for metric, semantics in (
            ("building_nodes", "exact"),
            ("building_elements", "exact"),
            ("provider_nodes", "upper_bound"),
            ("provider_elements", "upper_bound"),
            ("provider_fsi_faces", "upper_bound"),
            ("module_new_nodes", "upper_bound"),
            ("module_new_elements", "upper_bound"),
            ("symbolic_ids", "exact"),
        )
    )
    return RefinedBlastPreview(project.project_id, scenario.scenario_id, revision, cache_key, layers, counts, is_final)


def build_lightweight_refined_blast_preview(
    project: RefinedBlastProject,
    building_recipe: Mapping[str, object],
    *,
    revision: int,
) -> RefinedBlastPreview:
    """Build a configuration proxy without compiling any detailed mesh."""

    if len(project.scenario_set) != 1:
        raise ValueError("one lightweight preview represents exactly one scenario")
    descriptor = get_detailed_building_asset(
        str(building_recipe.get("asset_id", ""))
    )
    geometry = dict(descriptor.default_geometry)
    overrides = building_recipe.get("legacy_geometry")
    if isinstance(overrides, Mapping):
        geometry.update(overrides)
    origin = _preview_vector(building_recipe.get("origin_m"), (0.0, 0.0, 0.0))
    building_bounds = _lightweight_building_bounds(
        descriptor.resource_id, geometry, origin
    )
    union = _bounds_union(building_bounds)
    scenario = project.scenario_set[0]
    provider_input = scenario.load_provider.get("provider_input")
    if not isinstance(provider_input, Mapping):
        provider_input = {}
    mesh_profile = str(
        building_recipe.get("mesh_profile", descriptor.default_mesh_profile)
    )
    if mesh_profile not in descriptor.mesh_profile_rows:
        mesh_profile = descriptor.default_mesh_profile
    mesh_row = descriptor.mesh_profile_rows[mesh_profile]
    building_cell_size = float(mesh_row["slab_wall_target_m"])
    air_cell_size = _lightweight_cell_size(
        provider_input.get("air_cell_size_m"),
        _nested_preview_value(provider_input, "domain", "target_cell_size_m"),
        default=0.25,
    )
    ground_cell_size = _lightweight_cell_size(
        provider_input.get("ground_cell_size_m"), default=0.25
    )
    raw_margins = provider_input.get("air_margins_m")
    if isinstance(raw_margins, Sequence) and not isinstance(
        raw_margins, (str, bytes, bytearray)
    ):
        margins = _preview_vector5(raw_margins, (3.0, 3.0, 3.0, 3.0, 3.0))
    else:
        legacy_margin = _preview_vector(
            provider_input.get("air_margin_m"), (3.0, 3.0, 3.0)
        )
        margins = (
            legacy_margin[0], legacy_margin[0], legacy_margin[1],
            legacy_margin[1], legacy_margin[2],
        )
    grade_elevation = union[2]
    air_bounds = (
        union[0] - max(0.0, margins[0]),
        union[1] - max(0.0, margins[2]),
        grade_elevation,
        union[3] + max(0.0, margins[1]),
        union[4] + max(0.0, margins[3]),
        union[5] + max(0.0, margins[4]),
    )
    raw_buffer_layers = provider_input.get("coupling_buffer_layers", 2)
    buffer_layers = (
        int(raw_buffer_layers)
        if isinstance(raw_buffer_layers, int)
        and not isinstance(raw_buffer_layers, bool)
        and 1 <= raw_buffer_layers <= 5
        else 2
    )
    buffer_bounds = (
        air_bounds[0], air_bounds[1],
        grade_elevation - buffer_layers * air_cell_size,
        air_bounds[3], air_bounds[4], grade_elevation,
    )
    near_field_cell_size = _lightweight_cell_size(
        provider_input.get("near_field_cell_size_m"), default=air_cell_size
    )
    foundation_depth = max(
        0.20, min(0.75, 3.0 * float(mesh_row["member_foundation_target_m"]))
    )
    ground_depth = max(0.50, foundation_depth + 2.0 * ground_cell_size)
    foundation_bounds = (
        union[0],
        union[1],
        union[2] - foundation_depth,
        union[3],
        union[4],
        union[2],
    )
    ground_bounds = (
        union[0],
        union[1],
        union[2] - ground_depth,
        union[3],
        union[4],
        union[2] - foundation_depth,
    )
    definition_fingerprint = fingerprint_value(
        {
            "schema_version": "phase18f_lightweight_definition@1",
            "building_recipe": building_recipe,
        }
    )
    scenario_fingerprint = fingerprint_value(
        {
            "scenario_id": scenario.scenario_id,
            "load_provider": scenario.load_provider,
        }
    )
    regions = tuple(
        {"region_id": f"building-proxy-{index}", "bounds_m": bounds}
        for index, bounds in enumerate(building_bounds, start=1)
    )
    structure_payload = {
        "representation": "configuration_building_proxy",
        "asset_id": descriptor.resource_id,
        "mesh_profile": mesh_profile,
        "representative_cell_size_m": building_cell_size,
        "regions": regions,
    }
    fluid_payload = {
        "representation": "configuration_visible_air_domain",
        "air_cell_size_m": air_cell_size,
        "near_field_cell_size_m": near_field_cell_size,
        "air_margins_m": margins,
        "coupling_buffer_layers": buffer_layers,
        "building_envelope_bounds_m": union,
        "active_air_bounds_m": air_bounds,
        "coupling_buffer_bounds_m": buffer_bounds,
        "bounds_m": air_bounds,
    }
    support_payload = {
        "representation": "configuration_foundation_and_ground_proxy",
        "foundation_bounds_m": foundation_bounds,
        "ground_bounds_m": ground_bounds,
        "ground_cell_size_m": ground_cell_size,
        "foundation_depth_m": foundation_depth,
    }
    boundary_payload = {
        "representation": "configuration_flow_boundary_proxy",
        "boundary_semantics": "external_air_boundary_candidate",
        "bounds_m": air_bounds,
    }
    position = _lightweight_blast_position(provider_input)
    provider_preview: dict[str, object] = {}
    if position is not None:
        provider_preview["detonation_position_m"] = position
        mass = provider_input.get("tnt_equivalent_mass_kg")
        if isinstance(mass, (int, float)) and not isinstance(mass, bool) and mass > 0:
            side = tnt_side_length_m(float(mass))
            half = 0.5 * side
            provider_preview["tnt_bounds_m"] = (
                position[0] - half,
                position[1] - half,
                position[2] - half,
                position[0] + half,
                position[1] + half,
                position[2] + half,
            )
    blast_payload = {
        "provider_id": scenario.load_provider.get("provider_id"),
        "input_fingerprint": fingerprint_value(provider_input),
        "provider_preview": provider_preview,
    }
    empty = _with_primitives({}, _NeutralPrimitiveBuild((), 0, 0))
    layers = (
        PreviewLayer("cavities_openings", empty, (definition_fingerprint,)),
        PreviewLayer(
            "structure",
            _with_primitives(
                structure_payload,
                _combine_primitive_builds(
                    _bounds_primitives(structure_payload, "structure-proxy"),
                    _single_primitive_build(
                        _representative_grid_primitive(
                            "building-mesh-grid",
                            union,
                            building_cell_size,
                            elevation_m=union[5] + 1.0e-4,
                        )
                    ),
                ),
            ),
            (definition_fingerprint,),
        ),
        PreviewLayer("reinforcement_connections", empty, (definition_fingerprint,)),
        PreviewLayer("nonstructural", empty, (definition_fingerprint,)),
        PreviewLayer("exposed_surfaces", empty, (definition_fingerprint,)),
        PreviewLayer(
            "blast_source",
            _with_primitives(
                blast_payload,
                _blast_source_primitives(scenario.load_provider, provider_preview),
            ),
            (scenario_fingerprint,),
        ),
        PreviewLayer(
            "fluid_domain",
            _with_primitives(
                fluid_payload,
                _combine_primitive_builds(
                    _single_primitive_build(
                        _box_primitive("active-air-proxy", air_bounds)
                    ),
                    _single_primitive_build(
                        _box_primitive("coupling-buffer-proxy", buffer_bounds)
                    ),
                    _single_primitive_build(
                        _representative_grid_primitive(
                            "air-mesh-grid",
                            air_bounds,
                            air_cell_size,
                            elevation_m=air_bounds[5] + 1.0e-4,
                        )
                    ),
                ),
            ),
            (scenario_fingerprint,),
        ),
        PreviewLayer(
            "boundaries",
            _with_primitives(
                boundary_payload,
                _single_primitive_build(
                    _wireframe_box_primitive(
                        "active-air-flow-boundary", air_bounds
                    )
                ),
            ),
            (scenario_fingerprint,),
        ),
        PreviewLayer(
            "support_ground",
            _with_primitives(
                support_payload,
                _combine_primitive_builds(
                    _single_primitive_build(
                        _box_primitive(
                            "building-foundation-proxy", foundation_bounds
                        )
                    ),
                    _single_primitive_build(
                        _box_primitive("support-ground-proxy", ground_bounds)
                    ),
                    _single_primitive_build(
                        _representative_grid_primitive(
                            "ground-mesh-grid",
                            ground_bounds,
                            ground_cell_size,
                            elevation_m=ground_bounds[5] + 1.0e-4,
                        )
                    ),
                ),
            ),
            (definition_fingerprint,),
        ),
    )
    counts = tuple(
        PreviewCount(metric, _MAX_PREVIEW_COUNT, "upper_bound")
        for metric in PREVIEW_COUNT_METRICS
    )
    cache_key = fingerprint_value(
        {
            "schema_version": "phase18f_lightweight_preview@1",
            "project_id": project.project_id,
            "revision": revision,
            "definition_fingerprint": definition_fingerprint,
            "scenario_fingerprint": scenario_fingerprint,
        }
    )
    return RefinedBlastPreview(
        project.project_id,
        scenario.scenario_id,
        revision,
        cache_key,
        layers,
        counts,
        False,
    )


def _preview_vector(
    value: object, default: tuple[float, float, float]
) -> tuple[float, float, float]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or len(value) != 3
    ):
        return default
    try:
        result = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return default
    if not all(math.isfinite(item) for item in result):
        return default
    return result  # type: ignore[return-value]


def _preview_vector5(
    value: object,
    default: tuple[float, float, float, float, float],
) -> tuple[float, float, float, float, float]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ) or len(value) != 5:
        return default
    try:
        result = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return default
    if not all(math.isfinite(item) for item in result):
        return default
    return result  # type: ignore[return-value]


def _nested_preview_value(
    value: Mapping[str, object], parent: str, child: str
) -> object:
    nested = value.get(parent)
    return nested.get(child) if isinstance(nested, Mapping) else None


def _lightweight_cell_size(*values: object, default: float) -> float:
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        number = float(value)
        if math.isfinite(number) and number > 0.0:
            return number
    return default


def _lightweight_building_bounds(
    asset_id: str,
    geometry: Mapping[str, object],
    origin: tuple[float, float, float],
) -> tuple[tuple[float, float, float, float, float, float], ...]:
    def positive(name: str, default: float) -> float:
        value = geometry.get(name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        number = float(value)
        return number if math.isfinite(number) and number > 0 else default

    ox, oy, oz = origin
    if asset_id == "residential_community_detailed_building":
        count_value = geometry.get("tower_count", 1)
        count = max(1, int(count_value)) if isinstance(count_value, (int, float)) else 1
        length = positive("tower_length_m", 8.0)
        width = positive("tower_width_m", 10.0)
        height = positive("tower_height_m", 18.0)
        spacing = positive("tower_spacing_m", 4.0)
        return tuple(
            (
                ox + index * (length + spacing),
                oy,
                oz,
                ox + index * (length + spacing) + length,
                oy + width,
                oz + height,
            )
            for index in range(count)
        )
    length = positive("length_m", 10.0)
    width = positive("width_m", 8.0)
    height = positive(
        "height_m",
        positive("platform_height_m", 0.3)
        + positive("enclosure_height_m", 2.8),
    )
    return ((ox, oy, oz, ox + length, oy + width, oz + height),)


def _bounds_union(
    rows: Sequence[Sequence[float]],
) -> tuple[float, float, float, float, float, float]:
    return (
        min(row[0] for row in rows),
        min(row[1] for row in rows),
        min(row[2] for row in rows),
        max(row[3] for row in rows),
        max(row[4] for row in rows),
        max(row[5] for row in rows),
    )


def _lightweight_blast_position(
    provider_input: Mapping[str, object],
) -> tuple[float, float, float] | None:
    direct = provider_input.get("charge_position_m")
    if isinstance(direct, Sequence) and not isinstance(
        direct, (str, bytes, bytearray)
    ):
        position = _preview_vector(direct, (math.nan, math.nan, math.nan))
        if all(math.isfinite(value) for value in position):
            return position
    for key in ("charge", "source"):
        nested = provider_input.get(key)
        if isinstance(nested, Mapping):
            raw = nested.get("position_m")
            if isinstance(raw, Sequence) and not isinstance(
                raw, (str, bytes, bytearray)
            ):
                position = _preview_vector(raw, (math.nan, math.nan, math.nan))
                if all(math.isfinite(value) for value in position):
                    return position
    return None


def _is_reinforcement(role: str) -> bool:
    return any(token in role for token in ("rebar", "reinforcement", "longitudinal", "stirrup"))


def _with_primitives(
    payload: Mapping[str, object], build: _NeutralPrimitiveBuild,
) -> dict[str, object]:
    primitives = build.primitives
    if len(primitives) > _MAX_NEUTRAL_PRIMITIVES_PER_LAYER:
        raise ValueError("neutral primitive count exceeds per-layer safety limit")
    canonical = json.dumps(
        thaw_value(primitives), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    if len(canonical) > _MAX_NEUTRAL_PRIMITIVE_BYTES_PER_LAYER:
        raise ValueError("neutral primitive payload exceeds per-layer byte safety limit")
    source_count = build.source_item_count
    rendered_count = build.rendered_item_count
    representation = "deterministic_lod" if rendered_count < source_count else "full_geometry"
    result = dict(payload)
    result["neutral_primitives"] = tuple(primitives)
    result["neutral_representation"] = {
        "schema_version": "refined_blast.neutral_primitives@1",
        "representation": representation,
        "source_item_count": source_count,
        "rendered_item_count": rendered_count,
        "coverage": 1.0 if source_count == 0 else rendered_count / source_count,
        "primitive_count": len(primitives),
        "payload_byte_count": len(canonical),
        "fingerprint": fingerprint_value(primitives),
    }
    return result


def _enforce_preview_source_budget(
    artifact: BuildingArtifact,
    module_payloads: Mapping[str, Mapping[str, object]],
) -> None:
    source_elements = 0

    def include(count: int) -> None:
        nonlocal source_elements
        source_elements += count
        if source_elements > _MAX_PREVIEW_SOURCE_ELEMENTS:
            raise ValueError("preview source element budget exceeded before neutral primitive materialization")

    include(len(artifact.mesh.nodes))
    include(len(artifact.mesh.solids))
    include(len(artifact.mesh.shells))
    include(len(artifact.mesh.beams))
    include(len(artifact.connections))
    for rows in artifact.surface_catalog.values():
        if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray)):
            include(len(rows))
    cavity_sources = (
        artifact.normalized_input.get("openings", ()),
        artifact.topology_manifest.get("void_regions", ()),
    )
    include(max(
        sum(_source_family_size(value) for value in cavity_sources),
        sum(1 for value in cavity_sources for _row in _iter_bounds(value)),
    ))
    for payload in module_payloads.values():
        for key in ("elements", "nodes", "surfaces"):
            rows = payload.get(key)
            if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray)):
                include(len(rows))
        bounded_sources = (payload.get("regions", ()), payload.get("openings", ()))
        include(max(
            sum(_source_family_size(value) for value in bounded_sources),
            sum(1 for _row in _iter_bounds(payload)),
        ))


def _lod_rows(rows: Sequence[object]) -> tuple[object, ...]:
    if len(rows) <= _MAX_NEUTRAL_SOURCE_ITEMS_PER_LAYER:
        return tuple(rows)
    limit = _MAX_NEUTRAL_SOURCE_ITEMS_PER_LAYER
    return tuple(rows[(index * len(rows)) // limit] for index in range(limit))


def _lod_positions(source_count: int) -> frozenset[int]:
    rendered_count = min(source_count, _MAX_NEUTRAL_SOURCE_ITEMS_PER_LAYER)
    if rendered_count == source_count:
        return frozenset(range(source_count))
    return frozenset(
        (index * source_count) // rendered_count for index in range(rendered_count)
    )


def _source_family_size(value: object) -> int:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return len(value)
    if isinstance(value, Mapping):
        return 1
    return 0


def _primitive(
    primitive_id: str,
    nodes: Sequence[Sequence[float]],
    faces: Sequence[Sequence[int]],
    edges: Sequence[Sequence[int]],
) -> dict[str, object]:
    return {
        "primitive_id": primitive_id,
        "kind": "mesh",
        "nodes": tuple(tuple(float(value) for value in point) for point in nodes),
        "faces": tuple(tuple(int(value) for value in face) for face in faces),
        "edges": tuple(tuple(int(value) for value in edge) for edge in edges),
    }


def _artifact_mesh_primitives(
    artifact: BuildingArtifact, element_ids: Sequence[int], primitive_id: str,
) -> _NeutralPrimitiveBuild:
    selected = set(element_ids)
    if not selected:
        return _NeutralPrimitiveBuild((), 0, 0)
    source_count = sum(
        1
        for element in chain(
            artifact.mesh.solids, artifact.mesh.shells, artifact.mesh.beams,
        )
        if element.element_id in selected
    )
    positions = _lod_positions(source_count)
    rendered: list[object] = []
    eligible_index = 0
    for element in chain(
        artifact.mesh.solids, artifact.mesh.shells, artifact.mesh.beams,
    ):
        if element.element_id in selected:
            if eligible_index in positions:
                rendered.append(element)
            eligible_index += 1
    required_node_ids = {
        node_id for element in rendered for node_id in element.node_ids
    }
    node_by_id = {
        row.node_id: row.coordinates
        for row in artifact.mesh.nodes
        if row.node_id in required_node_ids
    }
    nodes: list[tuple[float, float, float]] = []
    node_indexes: dict[int, int] = {}
    faces: list[tuple[int, ...]] = []
    seen_faces: set[tuple[int, ...]] = set()
    edges: list[tuple[int, int]] = []
    seen_edges: set[tuple[int, int]] = set()

    def node_index(node_id: int) -> int:
        if node_id not in node_indexes:
            node_indexes[node_id] = len(nodes)
            nodes.append(node_by_id[node_id])
        return node_indexes[node_id]

    def add_face(node_ids: Sequence[int]) -> None:
        face = tuple(node_index(node_id) for node_id in node_ids)
        identity = tuple(sorted(face))
        if identity not in seen_faces:
            seen_faces.add(identity)
            faces.append(face)

    def add_edge(first_id: int, second_id: int) -> None:
        edge = tuple(sorted((node_index(first_id), node_index(second_id))))
        if edge not in seen_edges:
            seen_edges.add(edge)
            edges.append(edge)

    for row in rendered:
        element = row
        if len(element.node_ids) == 8:
            local_faces = ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
            for face in local_faces:
                add_face(tuple(element.node_ids[value] for value in face))
            local_edges = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))
            for first, second in local_edges:
                add_edge(element.node_ids[first], element.node_ids[second])
        elif len(element.node_ids) == 4:
            add_face(element.node_ids)
            for first, second in ((0, 1), (1, 2), (2, 3), (3, 0)):
                add_edge(element.node_ids[first], element.node_ids[second])
        else:
            add_edge(element.node_ids[0], element.node_ids[1])
    if not nodes:
        return _NeutralPrimitiveBuild((), source_count, len(rendered))
    return _NeutralPrimitiveBuild(
        (_primitive(primitive_id, nodes, faces, edges),), source_count, len(rendered),
    )


def _catalog_surface_primitives(
    artifact: BuildingArtifact, catalog: object, primitive_id: str,
) -> _NeutralPrimitiveBuild:
    source_count = sum(1 for _row in _iter_catalog_rows(catalog))
    positions = _lod_positions(source_count)
    rendered = tuple(
        row for index, row in enumerate(_iter_catalog_rows(catalog)) if index in positions
    )
    required_node_ids = {
        node_id
        for row in rendered
        for node_id in _node_id_sequence(row.get("node_ids"))
    }
    node_by_id = {
        row.node_id: row.coordinates
        for row in artifact.mesh.nodes
        if row.node_id in required_node_ids
    }
    nodes: list[tuple[float, float, float]] = []
    node_indexes: dict[object, int] = {}
    faces: list[tuple[int, ...]] = []
    seen_faces: set[tuple[int, ...]] = set()
    edges: list[tuple[int, int]] = []
    seen_edges: set[tuple[int, int]] = set()
    for candidate in rendered:
        row = candidate
        if not isinstance(row, Mapping):
            continue
        ids = row.get("node_ids")
        if not isinstance(ids, Sequence) or isinstance(ids, (str, bytes, bytearray)):
            continue
        coordinates = [node_by_id.get(node_id) for node_id in ids]
        if len(coordinates) < 3 or any(point is None for point in coordinates):
            continue
        face_indexes: list[int] = []
        for node_id, point in zip(ids, coordinates, strict=True):
            if node_id not in node_indexes:
                node_indexes[node_id] = len(nodes)
                assert point is not None
                nodes.append(point)
            face_indexes.append(node_indexes[node_id])
        face = tuple(face_indexes)
        identity = tuple(sorted(face))
        if identity not in seen_faces:
            seen_faces.add(identity)
            faces.append(face)
        for index in range(len(face)):
            edge = tuple(sorted((face[index], face[(index + 1) % len(face)])))
            if edge not in seen_edges:
                seen_edges.add(edge)
                edges.append(edge)
    primitives = (_primitive(primitive_id, nodes, faces, edges),) if nodes else ()
    return _NeutralPrimitiveBuild(primitives, source_count, len(rendered))


def _iter_catalog_rows(catalog: object):
    values: object
    if isinstance(catalog, Mapping):
        values = catalog.values()
    elif isinstance(catalog, Sequence) and not isinstance(catalog, (str, bytes, bytearray)):
        values = catalog
    else:
        values = ()
    for value in values:
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for row in value:
                if isinstance(row, Mapping):
                    yield row
        elif isinstance(value, Mapping):
            yield value


def _node_id_sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _bounds_primitives(value: object, prefix: str) -> _NeutralPrimitiveBuild:
    source_count = sum(1 for _row in _iter_bounds(value))
    positions = _lod_positions(source_count)
    found = [
        bounds for index, bounds in enumerate(_iter_bounds(value)) if index in positions
    ]
    if not found:
        return _NeutralPrimitiveBuild((), source_count, 0)
    nodes: list[tuple[float, float, float]] = []
    node_indexes: dict[tuple[float, float, float], int] = {}
    faces: list[tuple[int, ...]] = []
    seen_faces: set[tuple[int, ...]] = set()
    edges: list[tuple[int, int]] = []
    seen_edges: set[tuple[int, int]] = set()
    for bounds in found:
        primitive = _box_primitive(prefix, bounds)
        local_to_global: dict[int, int] = {}
        for index, point in enumerate(primitive["nodes"]):  # type: ignore[union-attr]
            normalized = tuple(point)
            if normalized not in node_indexes:
                node_indexes[normalized] = len(nodes)
                nodes.append(normalized)  # type: ignore[arg-type]
            local_to_global[index] = node_indexes[normalized]
        for local_face in primitive["faces"]:  # type: ignore[union-attr]
            face = tuple(local_to_global[index] for index in local_face)
            identity = tuple(sorted(face))
            if identity not in seen_faces:
                seen_faces.add(identity)
                faces.append(face)
        for local_edge in primitive["edges"]:  # type: ignore[union-attr]
            edge = tuple(sorted(local_to_global[index] for index in local_edge))
            if edge not in seen_edges:
                seen_edges.add(edge)
                edges.append(edge)
    return _NeutralPrimitiveBuild(
        (_primitive(prefix, nodes, faces, edges),), source_count, len(found),
    )


def _iter_bounds(value: object):
    if isinstance(value, Mapping):
        bounds = value.get("bounds_m")
        if (
            isinstance(bounds, Sequence)
            and not isinstance(bounds, (str, bytes, bytearray))
            and len(bounds) == 6
        ):
            try:
                yield tuple(float(item) for item in bounds)
            except (TypeError, ValueError):
                pass
        for child in value.values():
            yield from _iter_bounds(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            yield from _iter_bounds(child)


def _box_primitive(
    primitive_id: str, bounds: Sequence[float],
) -> dict[str, object]:
    x0, y0, z0, x1, y1, z1 = bounds
    nodes = ((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))
    faces = ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
    edges = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))
    return _primitive(primitive_id, nodes, faces, edges)


def _wireframe_box_primitive(
    primitive_id: str, bounds: Sequence[float]
) -> dict[str, object]:
    primitive = _box_primitive(primitive_id, bounds)
    primitive["faces"] = ()
    return primitive


def _representative_grid_primitive(
    primitive_id: str,
    bounds: Sequence[float],
    target_spacing_m: float,
    *,
    elevation_m: float,
) -> dict[str, object]:
    """Return a bounded XY grid patch that communicates the selected spacing."""

    x0, y0, _z0, x1, y1, _z1 = (float(value) for value in bounds)
    spacing = float(target_spacing_m)
    if not math.isfinite(spacing) or spacing <= 0.0:
        raise ValueError("representative grid spacing must be positive and finite")
    x_cells = max(1, min(10, int(math.floor((x1 - x0) / spacing))))
    y_cells = max(1, min(10, int(math.floor((y1 - y0) / spacing))))
    patch_width = min(x1 - x0, x_cells * spacing)
    patch_height = min(y1 - y0, y_cells * spacing)
    patch_x0 = x0 + 0.5 * ((x1 - x0) - patch_width)
    patch_y0 = y0 + 0.5 * ((y1 - y0) - patch_height)
    patch_x1 = patch_x0 + patch_width
    patch_y1 = patch_y0 + patch_height
    nodes: list[tuple[float, float, float]] = []
    edges: list[tuple[int, int]] = []

    def line(start: tuple[float, float, float], end: tuple[float, float, float]) -> None:
        index = len(nodes)
        nodes.extend((start, end))
        edges.append((index, index + 1))

    for index in range(x_cells + 1):
        x = patch_x0 + min(index * spacing, patch_width)
        line((x, patch_y0, elevation_m), (x, patch_y1, elevation_m))
    for index in range(y_cells + 1):
        y = patch_y0 + min(index * spacing, patch_height)
        line((patch_x0, y, elevation_m), (patch_x1, y, elevation_m))
    return _primitive(primitive_id, nodes, (), edges)


def _single_primitive_build(primitive: Mapping[str, object]) -> _NeutralPrimitiveBuild:
    return _NeutralPrimitiveBuild((primitive,), 1, 1)


def _combine_primitive_builds(
    *builds: _NeutralPrimitiveBuild,
) -> _NeutralPrimitiveBuild:
    return _NeutralPrimitiveBuild(
        tuple(chain.from_iterable(build.primitives for build in builds)),
        sum(build.source_item_count for build in builds),
        sum(build.rendered_item_count for build in builds),
    )


def _blast_source_primitives(
    load_provider: Mapping[str, object],
    provider_preview: Mapping[str, object],
) -> _NeutralPrimitiveBuild:
    position: object = provider_preview.get("detonation_position_m")
    provider_input = load_provider.get("provider_input")
    if position is None and isinstance(provider_input, Mapping):
        for key in ("charge", "source"):
            nested = provider_input.get(key)
            if isinstance(nested, Mapping) and nested.get("position_m") is not None:
                position = nested.get("position_m")
                break
    if not isinstance(position, Sequence) or isinstance(position, (str, bytes, bytearray)) or len(position) != 3:
        return _NeutralPrimitiveBuild((), 0, 0)
    try:
        center = tuple(float(value) for value in position)
    except (TypeError, ValueError):
        return _NeutralPrimitiveBuild((), 0, 0)
    marker = {
        "primitive_id": "blast-source",
        "kind": "blast_source",
        "position_m": center,
    }
    raw_bounds = provider_preview.get("tnt_bounds_m")
    if (
        isinstance(raw_bounds, Sequence)
        and not isinstance(raw_bounds, (str, bytes, bytearray))
        and len(raw_bounds) == 6
    ):
        try:
            bounds = tuple(float(value) for value in raw_bounds)
        except (TypeError, ValueError):
            return _NeutralPrimitiveBuild((marker,), 1, 1)
        if all(math.isfinite(value) for value in bounds) and all(
            bounds[index] < bounds[index + 3] for index in range(3)
        ):
            return _NeutralPrimitiveBuild(
                (_box_primitive("tnt-solid", bounds), marker), 2, 2
            )
    return _NeutralPrimitiveBuild((marker,), 1, 1)


def _module_mesh_primitives(
    payload: Mapping[str, object], primitive_id: str,
) -> _NeutralPrimitiveBuild:
    raw_nodes = payload.get("nodes")
    raw_elements = payload.get("elements")
    if not isinstance(raw_nodes, Sequence) or isinstance(raw_nodes, (str, bytes, bytearray)):
        return _NeutralPrimitiveBuild((), 0, 0)
    if not isinstance(raw_elements, Sequence) or isinstance(raw_elements, (str, bytes, bytearray)):
        return _NeutralPrimitiveBuild((), 0, 0)
    rendered = _lod_rows(raw_elements)
    required_node_ids = {
        node_id
        for row in rendered
        if isinstance(row, Mapping)
        for node_id in _node_id_sequence(row.get("node_ids"))
    }
    node_by_id: dict[object, tuple[float, float, float]] = {}
    for row in raw_nodes:
        if not isinstance(row, Mapping):
            continue
        if row.get("node_id") not in required_node_ids:
            continue
        coordinates = row.get("coordinates_m")
        if isinstance(coordinates, Sequence) and not isinstance(coordinates, (str, bytes, bytearray)) and len(coordinates) == 3:
            try:
                node_by_id[row.get("node_id")] = tuple(float(value) for value in coordinates)  # type: ignore[assignment]
            except (TypeError, ValueError):
                continue
    nodes: list[tuple[float, float, float]] = []
    node_indexes: dict[object, int] = {}
    faces: list[tuple[int, ...]] = []
    seen_faces: set[tuple[int, ...]] = set()
    edges: list[tuple[int, int]] = []
    seen_edges: set[tuple[int, int]] = set()
    for candidate in rendered:
        row = candidate
        if not isinstance(row, Mapping):
            continue
        node_ids = row.get("node_ids")
        if not isinstance(node_ids, Sequence) or isinstance(node_ids, (str, bytes, bytearray)):
            continue
        coordinates = [node_by_id.get(node_id) for node_id in node_ids]
        if len(coordinates) < 2 or any(point is None for point in coordinates):
            continue
        indexes: list[int] = []
        for node_id, point in zip(node_ids, coordinates, strict=True):
            if node_id not in node_indexes:
                node_indexes[node_id] = len(nodes)
                assert point is not None
                nodes.append(point)
            indexes.append(node_indexes[node_id])

        def add_face(local: Sequence[int]) -> None:
            face = tuple(indexes[value] for value in local)
            identity = tuple(sorted(face))
            if identity not in seen_faces:
                seen_faces.add(identity)
                faces.append(face)

        def add_edge(first: int, second: int) -> None:
            edge = tuple(sorted((indexes[first], indexes[second])))
            if edge not in seen_edges:
                seen_edges.add(edge)
                edges.append(edge)
        if len(coordinates) == 8:
            local_faces = ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
            for face in local_faces:
                add_face(face)
            local_edges = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))
            for first, second in local_edges:
                add_edge(first, second)
        elif len(coordinates) >= 3:
            add_face(tuple(range(len(indexes))))
            for index in range(len(indexes)):
                add_edge(index, (index + 1) % len(indexes))
        else:
            add_edge(0, 1)
    primitives = (_primitive(primitive_id, nodes, faces, edges),) if nodes else ()
    return _NeutralPrimitiveBuild(primitives, len(raw_elements), len(rendered))


__all__ = [
    "PREVIEW_COUNT_METRICS",
    "PREVIEW_LAYER_IDS",
    "PreviewCount",
    "PreviewLayer",
    "RefinedBlastPreview",
    "build_refined_blast_preview",
]
