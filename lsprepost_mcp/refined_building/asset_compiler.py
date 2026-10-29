"""Compiler for discoverable Phase 18D detailed-building asset packages."""

from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

from ..materials import get_material, get_reviewed_material_resource
from ..phase18_resource_review import canonical_resource_sha256
from .artifacts import (
    BeamElement,
    BuildingArtifact,
    MeshFragment,
    Node,
    PartBinding,
    ShellElement,
)
from .asset_resources import (
    DetailedBuildingAssetDescriptor,
    get_detailed_building_asset,
)
from .asset_surfaces import build_refined_asset_surface_catalog
from .asset_templates import (
    build_detailed_building_template,
    normalize_asset_geometry,
)
from .backends.hybrid import compile_steel_concrete_hybrid
from .backends.rc import compile_rc_structure
from .backends.rc_box import compile_rc_box
from .budgeting import estimate_template_families
from .connections import make_connection
from .contracts import normalize_building_definition
from .meshing import merge_fragments, merge_fragments_welded, mesh_axis_aligned_union
from .nonstructural import compile_nonstructural
from .reinforcement import (
    REINFORCEMENT_ROLES,
    generate_reinforcement,
    selected_reinforcement_roles,
)
from .spatial import AxisAlignedBox, compile_spatial_topology
from .surfaces import build_fluid_exposed_surface_catalog
from .systems import get_structural_system, normalize_structural_system_profile
from .validation import validate_building_artifact


_UNIT_SYSTEM = "SI_m_s_kg_N_Pa"
_DEFAULT_MAX_SOLIDS = 5_000_000
_GENERATION_HARD_CAPS = {
    "max_solid_elements": _DEFAULT_MAX_SOLIDS,
    "max_beam_elements": 1_000_000,
    "max_shell_elements": 1_000_000,
    "max_node_count": 8_000_000,
    "max_total_elements": 6_000_000,
}
_PREFLIGHT_LIMIT_KEYS = {
    "solid_elements": "max_solid_elements",
    "beam_elements": "max_beam_elements",
    "shell_elements": "max_shell_elements",
    "node_count": "max_node_count",
    "total_elements": "max_total_elements",
}
_GENERATION_KEYS = frozenset(
    {
        "max_solid_elements",
        "max_beam_elements",
        "max_shell_elements",
        "max_node_count",
        "max_total_elements",
        "reinforcement_mode",
        "include_reinforcement_roles",
        "cover_m",
        "bar_diameter_m",
        "rebar_spacing_m",
        "storey_count",
        "stair_width_m",
        "stair_tread_m",
        "stair_rise_m",
        "fixed_stair_slope_deg",
        "upper_landing_clear_width_m",
        "lower_landing_clear_width_m",
        "fixed_stair_longitudinal_spacing_m",
        "fixed_stair_distribution_spacing_m",
        "fixed_stair_local_densification_factor",
        "connection_simplification_level",
        "escalator_width_m",
        "escalator_rise_m",
        "escalator_angle_deg",
        "escalator_equipment_envelope_m",
        "lane_gap_m",
        "upper_landing_length_m",
        "lower_landing_length_m",
        "passage_length_m",
        "passage_clear_width_m",
        "passage_clear_height_m",
        "passage_floor_thickness_m",
        "passage_wall_thickness_m",
        "passage_roof_thickness_m",
        "pavilion_length_m",
        "pavilion_width_m",
        "pavilion_clear_height_m",
        "pavilion_roof_arc_rise_m",
        "pavilion_overhang_m",
        "pavilion_frame_size_m",
        "pavilion_glazing_thickness_m",
        "pavilion_roof_thickness_m",
        "glazing_bay_count",
        "passage_turn_deg",
        "additional_stair_count",
        "additional_escalator_count",
    }
)
_SUBWAY_GENERATION_KEYS = frozenset(
    key
    for key in _GENERATION_KEYS
    if key
    not in {
        "max_solid_elements",
        "max_beam_elements",
        "max_shell_elements",
        "max_node_count",
        "max_total_elements",
        "reinforcement_mode",
        "include_reinforcement_roles",
        "cover_m",
        "bar_diameter_m",
        "rebar_spacing_m",
        "storey_count",
    }
)


def generation_options_ui_schema(
    resource_id: str, structural_system: str | None = None
) -> dict[str, object]:
    """Public closed UI shape derived from the compiler's normalizer keys.

    Scalars intentionally leave numeric range checks to the normalizer.  This
    schema's contract is the exact allowed-property closure and applicability.
    """
    descriptor = get_detailed_building_asset(resource_id)
    system_id = structural_system or descriptor.default_structural_system
    if system_id not in descriptor.allowed_structural_systems:
        raise ValueError(f"structural system {system_id!r} is not allowed for {resource_id!r}")
    allowed = set(_GENERATION_KEYS)
    if resource_id != "subway_entrance_detailed_building":
        allowed -= _SUBWAY_GENERATION_KEYS
    if resource_id != "residential_community_detailed_building":
        allowed.discard("storey_count")
    properties: dict[str, object] = {key: {} for key in sorted(allowed)}
    properties["reinforcement_mode"] = {"type": "string", "enum": ["full_reinforced", "concrete_only", "custom"]}
    if "include_reinforcement_roles" in properties:
        roles = _HYBRID_REBAR_ROLES if system_id == "steel_concrete_hybrid" else REINFORCEMENT_ROLES
        properties["include_reinforcement_roles"] = {"type": "array", "items": {"type": "string", "enum": sorted(roles)}}
    return {"type": "object", "additionalProperties": False, "properties": properties, "ui_validation": "backend_normalizer"}
_HYBRID_REBAR_ROLES = frozenset({"foundation_rebar", "slab_rebar"})
_REBAR_PART_ROLES = REINFORCEMENT_ROLES
_NONSTRUCTURAL_OVERRIDE_CATEGORIES = {
    "facade": frozenset({"aluminum", "concrete", "rubber", "steel"}),
    "glazing": frozenset({"glass"}),
    "doors": frozenset({"aluminum", "steel"}),
    "nonstructural": frozenset({"aluminum", "concrete", "rubber", "steel"}),
    "metal_roof": frozenset({"aluminum", "steel"}),
    "signage": frozenset({"aluminum", "steel"}),
    "escalator_equipment": frozenset({"aluminum", "steel"}),
    "escalator_balustrade": frozenset({"aluminum", "glass", "steel"}),
    "escalator_handrail": frozenset({"rubber", "steel"}),
}


@dataclass(frozen=True, slots=True)
class DetailedBuildingPackage:
    """Frozen package view; :meth:`to_manifest` returns plain JSON values."""

    resource_id: str
    resource_version: str
    legacy_asset_id: str
    capability: str
    structural_system: str
    fidelity_profile: str
    mesh_profile: str
    artifacts: tuple[BuildingArtifact, ...]
    material_binding_manifest: Mapping[str, object]
    geometry_manifest: Mapping[str, object]
    mesh_manifest: Mapping[str, object]
    quantity_manifest: Mapping[str, object]
    quality_manifest: Mapping[str, object]
    refined_surface_catalog: Mapping[str, object]
    unmodeled_scope: tuple[str, ...]
    lineage_manifest: Mapping[str, object]
    placement: Mapping[str, object]
    generation_options: Mapping[str, object]
    package_fingerprint: str
    solver_ready: bool = False
    requires_project_review: bool = True

    @property
    def fingerprint(self) -> str:
        return self.package_fingerprint

    def to_manifest(self) -> dict[str, object]:
        return {
            "schema_version": "0.1.0",
            "resource_id": self.resource_id,
            "resource_version": self.resource_version,
            "legacy_asset_id": self.legacy_asset_id,
            "capability": self.capability,
            "selection": {
                "structural_system": self.structural_system,
                "fidelity_profile": self.fidelity_profile,
                "mesh_profile": self.mesh_profile,
            },
            "artifacts": [_thaw(artifact.to_manifest()) for artifact in self.artifacts],
            "material_binding_manifest": _thaw(self.material_binding_manifest),
            "geometry_manifest": _thaw(self.geometry_manifest),
            "mesh_manifest": _thaw(self.mesh_manifest),
            "quantity_manifest": _thaw(self.quantity_manifest),
            "quality_manifest": _thaw(self.quality_manifest),
            "refined_surface_catalog": _thaw(self.refined_surface_catalog),
            "unmodeled_scope": list(self.unmodeled_scope),
            "lineage_manifest": _thaw(self.lineage_manifest),
            "placement": _thaw(self.placement),
            "generation_options": _thaw(self.generation_options),
            "solver_ready": self.solver_ready,
            "requires_project_review": self.requires_project_review,
            "package_fingerprint": self.package_fingerprint,
        }


def compile_detailed_building_asset(
    resource_id: str,
    *,
    legacy_geometry: Mapping[str, object] | None = None,
    origin_m: Sequence[object] = (0.0, 0.0, 0.0),
    rotation_deg: Sequence[object] = (0.0, 0.0, 0.0),
    structural_system: str | None = None,
    fidelity_profile: str = "blast_response",
    mesh_profile: str = "standard",
    generation_options: Mapping[str, object] | None = None,
    material_overrides: Mapping[str, object] | None = None,
) -> DetailedBuildingPackage:
    """Compile one parameterized asset without applying global placement."""

    descriptor = get_detailed_building_asset(resource_id)
    system_id = (
        descriptor.default_structural_system
        if structural_system is None
        else _nonempty_string(structural_system, "structural_system")
    )
    if system_id not in descriptor.allowed_structural_systems:
        raise ValueError(
            f"structural system {system_id!r} is not allowed for {descriptor.resource_id!r}"
        )
    fidelity = _nonempty_string(fidelity_profile, "fidelity_profile")
    if fidelity not in descriptor.fidelity_profiles:
        raise ValueError(f"unsupported fidelity profile {fidelity!r}")
    mesh = _nonempty_string(mesh_profile, "mesh_profile")
    if mesh not in descriptor.mesh_profiles:
        raise ValueError(f"unsupported mesh profile {mesh!r}")
    placement = {
        "origin_m": _finite_vector(origin_m, "origin_m"),
        "rotation_deg": _finite_vector(rotation_deg, "rotation_deg"),
    }
    geometry = normalize_asset_geometry(descriptor, legacy_geometry)
    options = _normalize_generation_options(
        generation_options,
        system_id,
        descriptor.resource_id,
        geometry,
    )
    overrides = _normalize_material_overrides(material_overrides, descriptor)
    for semantic_role, material_id in sorted(overrides.items()):
        _material_record(semantic_role, material_id)
    template = build_detailed_building_template(
        descriptor,
        geometry,
        structural_system=system_id,
        fidelity_profile=fidelity,
        mesh_profile=mesh,
        generation_options=options,
    )
    limit = int(options["max_solid_elements"])
    if template.solid_element_estimate > limit:
        estimate_label = (
            "predicted"
            if template.solid_estimate_kind == "exact"
            else "conservative upper bound"
        )
        raise ValueError(
            f"{descriptor.resource_id}/{mesh} {estimate_label} "
            f"{template.solid_element_estimate} Solid elements exceeds limit {limit}; "
            "the selected mesh profile was not automatically coarsened"
        )

    preflight = estimate_template_families(
        template.definitions,
        solid_count=template.solid_element_estimate,
        solid_estimation_kind=template.solid_estimate_kind,
    )
    limits = _effective_generation_limits(options)
    _enforce_generation_preflight(
        preflight,
        limits,
        resource_id=descriptor.resource_id,
        mesh_profile=mesh,
    )

    compiled_artifacts = tuple(
        _compile_asset_definition(value) for value in template.definitions
    )
    actual_solid_count = sum(
        len(artifact.mesh.solids) for artifact in compiled_artifacts
    )
    if (
        template.solid_estimate_kind == "exact"
        and actual_solid_count != template.solid_element_estimate
    ):
        raise ValueError(
            "exact Solid preflight estimate does not match the generated artifact"
        )
    if actual_solid_count > template.solid_element_estimate:
        raise ValueError("Solid preflight upper bound was exceeded by generated artifact")
    actual_counts = {
        "solid_elements": actual_solid_count,
        "beam_elements": sum(len(artifact.mesh.beams) for artifact in compiled_artifacts),
        "shell_elements": sum(len(artifact.mesh.shells) for artifact in compiled_artifacts),
        "node_count": sum(len(artifact.mesh.nodes) for artifact in compiled_artifacts),
    }
    actual_counts["total_elements"] = (
        actual_counts["solid_elements"]
        + actual_counts["beam_elements"]
        + actual_counts["shell_elements"]
    )
    _verify_generation_preflight(preflight, actual_counts)

    artifacts = tuple(_freeze_artifact(artifact) for artifact in compiled_artifacts)
    if [artifact.fingerprint for artifact in artifacts] != [
        artifact.fingerprint for artifact in compiled_artifacts
    ]:
        raise ValueError("artifact freeze changed the canonical fingerprint")
    for artifact in artifacts:
        report = validate_building_artifact(artifact)
        if not report["valid"]:
            raise ValueError(
                f"frozen artifact {artifact.asset_id!r} failed validation: "
                f"{report['findings']}"
            )
        if not artifact.requires_project_review:
            raise ValueError("Phase 18D child artifacts must require project review")

    material_manifest = _resolve_material_bindings(descriptor, artifacts, overrides)
    quantities = _quantity_manifest(artifacts)
    mesh_manifest = _mesh_manifest(
        descriptor,
        artifacts,
        mesh,
        template.solid_element_estimate,
        template.solid_estimate_kind,
        preflight,
        limits,
    )
    quality = _quality_manifest(artifacts, material_manifest, quantities)
    refined_surfaces = build_refined_asset_surface_catalog(artifacts)
    lineage = {
        "asset_resource": {
            "id": descriptor.resource_id,
            "version": descriptor.version,
            "legacy_asset_id": descriptor.legacy_asset_id,
        },
        "source_reference_lineage": _thaw(descriptor.source_reference_lineage),
        "fixed_phase18_part_section_data_applied": False,
    }
    fingerprint_core = {
        "schema_version": "0.1.0",
        "resource_id": descriptor.resource_id,
        "resource_version": descriptor.version,
        "selection": {
            "structural_system": system_id,
            "fidelity_profile": fidelity,
            "mesh_profile": mesh,
        },
        "artifact_fingerprints": [artifact.fingerprint for artifact in artifacts],
        "material_binding_manifest": material_manifest,
        "geometry_manifest": template.geometry_manifest,
        "mesh_manifest": {
            key: value for key, value in mesh_manifest.items() if key != "preflight"
        },
        "quantity_manifest": quantities,
        "quality_manifest": quality,
        "refined_surface_catalog": refined_surfaces,
        "unmodeled_scope": list(template.unmodeled_scope),
        "lineage_manifest": lineage,
        "placement": placement,
        "generation_options": options,
        "solver_ready": False,
        "requires_project_review": True,
    }
    fingerprint = _fingerprint(fingerprint_core)
    return DetailedBuildingPackage(
        resource_id=descriptor.resource_id,
        resource_version=descriptor.version,
        legacy_asset_id=descriptor.legacy_asset_id,
        capability=descriptor.capability,
        structural_system=system_id,
        fidelity_profile=fidelity,
        mesh_profile=mesh,
        artifacts=artifacts,
        material_binding_manifest=_freeze_json(material_manifest),  # type: ignore[arg-type]
        geometry_manifest=_freeze_json(template.geometry_manifest),  # type: ignore[arg-type]
        mesh_manifest=_freeze_json(mesh_manifest),  # type: ignore[arg-type]
        quantity_manifest=_freeze_json(quantities),  # type: ignore[arg-type]
        quality_manifest=_freeze_json(quality),  # type: ignore[arg-type]
        refined_surface_catalog=_freeze_json(refined_surfaces),  # type: ignore[arg-type]
        unmodeled_scope=template.unmodeled_scope,
        lineage_manifest=_freeze_json(lineage),  # type: ignore[arg-type]
        placement=_freeze_json(placement),  # type: ignore[arg-type]
        generation_options=_freeze_json(options),  # type: ignore[arg-type]
        package_fingerprint=fingerprint,
        solver_ready=False,
        requires_project_review=True,
    )


def _compile_asset_definition(definition: Mapping[str, object]) -> BuildingArtifact:
    """Compile structure and panels into one complete 18C-semantics artifact."""

    normalized = normalize_building_definition(definition)
    rows = normalized["nonstructural"]
    assert isinstance(rows, list)
    profile_raw = normalized["structural_system"]
    assert isinstance(profile_raw, dict)
    profile = normalize_structural_system_profile(profile_raw)
    normalized["structural_system"] = profile
    system_id = profile["type"]
    assert isinstance(system_id, str)
    descriptor = get_structural_system(system_id)
    topology = compile_spatial_topology(normalized)
    parameters = profile["parameters"]
    assert isinstance(parameters, dict)
    if "task4_subway_solid_members" in parameters:
        structural = _compile_task4_subway_structure(
            normalized, topology, system_id, parameters
        )
    elif descriptor.backend_key == "rc":
        structural = compile_rc_structure(normalized, topology, descriptor)
    elif descriptor.backend_key == "rc_box":
        structural = compile_rc_box(normalized, topology, descriptor)
    elif descriptor.backend_key == "hybrid":
        structural = compile_steel_concrete_hybrid(normalized, topology, descriptor)
    else:
        raise ValueError(
            f"detailed building backend {descriptor.backend_key!r} is unsupported"
        )
    fragments = [structural.mesh]
    supplemental = _compile_task4_subway_mesh(parameters)
    if supplemental is not None:
        fragments.append(supplemental)
    if rows:
        fragments.append(compile_nonstructural(normalized, structural))
    merged_mesh = (
        merge_fragments_welded(fragments)
        if supplemental is not None
        else merge_fragments(fragments)
    )
    connections = structural.connections
    if supplemental is not None:
        connections = (*connections, *_task4_pavilion_connections(merged_mesh))
    candidate = replace(
        structural,
        mesh=merged_mesh,
        connections=connections,
        normalized_input=normalized,
        topology_manifest=topology.to_manifest(),
        surface_catalog={},
    )
    candidate = replace(
        candidate,
        surface_catalog=build_fluid_exposed_surface_catalog(candidate, topology),
    )
    return replace(candidate, validation_findings=())


def _task4_pavilion_connections(
    mesh: MeshFragment,
) -> tuple[object, ...]:
    roof = [row for row in mesh.shells if row.part_role == "pavilion_metal_roof"]
    frame = [row for row in mesh.beams if row.part_role == "pavilion_frame"]
    plinth = [row for row in mesh.solids if row.part_role == "pavilion_rc_plinth"]
    roof_sources: set[int] = set()
    roof_targets: set[int] = set()
    for shell in roof:
        shell_nodes = set(shell.node_ids)
        for beam in frame:
            if len(shell_nodes & set(beam.node_ids)) >= 2:
                roof_sources.add(shell.element_id)
                roof_targets.add(beam.element_id)
    base_sources: set[int] = set()
    base_targets: set[int] = set()
    for beam in frame:
        beam_nodes = set(beam.node_ids)
        for solid in plinth:
            if beam_nodes & set(solid.node_ids):
                base_sources.add(beam.element_id)
                base_targets.add(solid.element_id)
    if not roof_sources or not roof_targets:
        raise ValueError("Task 4 pavilion roof has no real frame support interface")
    if not base_sources or not base_targets:
        raise ValueError("Task 4 pavilion frame has no real plinth support interface")
    return (
        make_connection(
            "task4_pavilion_roof_to_frame",
            "roof_to_frame",
            source_element_ids=sorted(roof_sources),
            target_element_ids=sorted(roof_targets),
            metadata={"method": "shared_roof_edge"},
        ),
        make_connection(
            "task4_pavilion_frame_to_plinth",
            "frame_to_plinth",
            source_element_ids=sorted(base_sources),
            target_element_ids=sorted(base_targets),
            metadata={"method": "shared_column_base_node"},
        ),
    )


def _compile_task4_subway_structure(
    normalized: Mapping[str, object],
    topology: object,
    system_id: str,
    parameters: Mapping[str, object],
) -> BuildingArtifact:
    from .spatial import SpatialTopology

    if not isinstance(topology, SpatialTopology):
        raise TypeError("Task 4 subway topology is invalid")
    raw_members = parameters.get("task4_subway_solid_members")
    if not isinstance(raw_members, list) or not raw_members:
        raise ValueError("task4_subway_solid_members must be a non-empty list")
    members: list[tuple[str, AxisAlignedBox]] = []
    for index, row in enumerate(raw_members):
        if not isinstance(row, Mapping):
            raise ValueError(f"task4_subway_solid_members[{index}] must be a mapping")
        role = row.get("part_role")
        bounds = row.get("bounds_m")
        if not isinstance(role, str) or not role.strip() or not isinstance(bounds, list):
            raise ValueError(f"task4_subway_solid_members[{index}] is invalid")
        members.append((role, AxisAlignedBox.from_bounds(bounds)))
    target = _positive_number(
        parameters.get("task4_subway_solid_target_m", 0.1),
        "task4_subway_solid_target_m",
    )
    exclusions = tuple(box for _, box in topology.opening_regions)
    priorities = {
        "rc_box_floor": 0,
        "rc_box_wall": 1,
        "rc_box_roof": 2,
        "rc_frame_column": 3,
        "rc_frame_roof_beam": 3,
        "pavilion_rc_plinth": 3,
        "lower_landing_8": 4,
        "upper_landing": 4,
        "fixed_stair_A": 5,
    }
    base_members = tuple(
        (role, box) for role, box in members if role.startswith("rc_")
    )
    circulation_members = tuple(
        (role, box) for role, box in members if not role.startswith("rc_")
    )
    if not base_members or not circulation_members:
        raise ValueError(
            "Task 4 subway needs both RC enclosure and circulation members"
        )
    circulation_boxes = tuple(box for _, box in circulation_members)
    base_exclusions = (*exclusions, *circulation_boxes)
    raw_plinth_interfaces = parameters.get(
        "task4_pavilion_plinth_interface_coordinates_m"
    )
    if not isinstance(raw_plinth_interfaces, list) or not raw_plinth_interfaces:
        raise ValueError(
            "task4_pavilion_plinth_interface_coordinates_m must be a non-empty list"
        )
    plinth_interfaces: list[tuple[float, float, float]] = []
    for index, point in enumerate(raw_plinth_interfaces):
        if (
            not isinstance(point, list)
            or len(point) != 3
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in point
            )
        ):
            raise ValueError(
                "task4_pavilion_plinth_interface_coordinates_m"
                f"[{index}] must be a finite x/y/z triple"
            )
        plinth_interfaces.append(tuple(float(value) for value in point))  # type: ignore[arg-type]
    fragments = [
        mesh_axis_aligned_union(
            base_members,
            target,
            base_exclusions,
            priorities,
        ),
        mesh_axis_aligned_union(
            circulation_members,
            target,
            exclusions,
            priorities,
            plinth_interfaces,
        ),
    ]
    selected = selected_reinforcement_roles(parameters)
    base_rebar = generate_reinforcement(
        base_members,
        parameters,
        selected,
        base_exclusions,
    )
    if base_rebar is not None:
        fragments.append(base_rebar)
    if "slab_rebar" in selected:
        stair_boxes = [box for role, box in members if role == "fixed_stair_A"]
        landing_boxes = [box for role, box in members if role in {"upper_landing", "lower_landing_8"}]
        plinth_boxes = [box for role, box in members if role == "pavilion_rc_plinth"]
        stair_rebar = _task4_stair_rebar_fragment(stair_boxes, parameters)
        if stair_rebar is not None:
            fragments.append(stair_rebar)
        for boxes, role in (
            (landing_boxes, "landing_rebar"),
            (plinth_boxes, "plinth_rebar"),
        ):
            generated = generate_reinforcement(
                (("rc_slab", box) for box in boxes),
                parameters,
                frozenset({"slab_rebar"}),
                exclusions,
            )
            if generated is not None:
                fragments.append(_retag_beam_fragment(generated, role))
    mesh = merge_fragments_welded(fragments)
    rebar_roles = set(REINFORCEMENT_ROLES) | {
        "fixed_stair_rebar",
        "fixed_stair_distribution_rebar",
        "fixed_stair_local_rebar",
        "landing_rebar",
        "plinth_rebar",
    }
    rebar_beams = tuple(row.element_id for row in mesh.beams if row.part_role in rebar_roles)
    connections = []
    if rebar_beams:
        connections.append(
            make_connection(
                "task4_subway_embedded_rebar",
                "embedded_rebar",
                source_element_ids=rebar_beams,
                target_element_ids=(row.element_id for row in mesh.solids),
                metadata={"method": "constrained_lagrange_in_solid"},
            )
        )
    interface_groups = _task4_structural_interface_groups(mesh)
    connection_level = parameters.get(
        "connection_simplification_level", "aggregate"
    )
    if connection_level == "aggregate":
        circulation_solids = tuple(
            sorted(
                {
                    element_id
                    for source_ids, _ in interface_groups.values()
                    for element_id in source_ids
                }
            )
        )
        enclosure_solids = tuple(
            sorted(
                {
                    element_id
                    for _, target_ids in interface_groups.values()
                    for element_id in target_ids
                }
            )
        )
        connections.append(
            make_connection(
                "task4_subway_circulation_to_enclosure",
                "tied_structural_interface",
                source_element_ids=circulation_solids,
                target_element_ids=enclosure_solids,
                metadata={
                    "coverage": "complete",
                    "interface": "approved_circulation_to_rc_enclosure",
                    "method": "actual_face_adjacency",
                    "simplification_level": "aggregate",
                },
            )
        )
    elif connection_level == "role_resolved":
        for role, (source_ids, target_ids) in interface_groups.items():
            connections.append(
                make_connection(
                    f"task4_subway_{role}_to_enclosure",
                    "tied_structural_interface",
                    source_element_ids=source_ids,
                    target_element_ids=target_ids,
                    metadata={
                        "coverage": "complete",
                        "interface": f"{role}_to_rc_enclosure",
                        "method": "actual_face_adjacency",
                        "simplification_level": "role_resolved",
                    },
                )
            )
    else:
        raise ValueError(
            "connection_simplification_level must be aggregate or role_resolved"
        )
    if system_id == "rc_frame_shear_wall":
        role_interfaces = (
            (
                "frame_to_shear_wall",
                {"rc_frame_column"},
                {"rc_box_wall"},
            ),
            (
                "column_to_floor",
                {"rc_frame_column"},
                {"rc_box_floor"},
            ),
            (
                "roof_beam_to_roof",
                {"rc_frame_roof_beam"},
                {"rc_box_roof"},
            ),
        )
        for connection_type, source_roles, target_roles in role_interfaces:
            source_ids, target_ids = _task4_shared_face_role_interface_ids(
                mesh,
                source_roles=source_roles,
                target_roles=target_roles,
            )
            if not source_ids or not target_ids:
                raise ValueError(
                    "Task 4 RC frame/shear-wall system has no real shared-face "
                    f"{connection_type} interface"
                )
            connections.append(
                make_connection(
                    f"task4_subway_{connection_type}",
                    connection_type,
                    source_element_ids=source_ids,
                    target_element_ids=target_ids,
                    metadata={"method": "shared_conforming_solid_face"},
                )
            )
    asset_id = normalized["asset_id"]
    assert isinstance(asset_id, str)
    return BuildingArtifact(
        asset_id=asset_id,
        system_id=system_id,
        mesh=mesh,
        connections=tuple(connections),
        normalized_input=dict(normalized),
        topology_manifest=topology.to_manifest(),
        dependency_manifest=(
            {
                "module": "refined_building.asset_compiler.task4_subway_union",
                "version": "1.0.0",
                "material_roles": ["concrete", "reinforcing_steel"] if rebar_beams else ["concrete"],
            },
        ),
        requires_project_review=True,
    )


def _task4_stair_rebar_fragment(
    boxes: Sequence[AxisAlignedBox],
    parameters: Mapping[str, object],
) -> MeshFragment | None:
    if not boxes:
        return None
    cover = _positive_number(parameters.get("cover_m", 0.04), "cover_m")
    diameter = _positive_number(
        parameters.get("bar_diameter_m", 0.016), "bar_diameter_m"
    )
    longitudinal_spacing = _positive_number(
        parameters.get("fixed_stair_longitudinal_spacing_m"),
        "fixed_stair_longitudinal_spacing_m",
    )
    distribution_spacing = _positive_number(
        parameters.get("fixed_stair_distribution_spacing_m"),
        "fixed_stair_distribution_spacing_m",
    )
    densification = _positive_number(
        parameters.get("fixed_stair_local_densification_factor"),
        "fixed_stair_local_densification_factor",
    )
    if not 1.0 <= densification <= 4.0:
        raise ValueError(
            "fixed_stair_local_densification_factor must be from 1 to 4"
        )
    nodes: list[Node] = []
    beams: list[BeamElement] = []
    coordinate_to_id: dict[tuple[float, float, float], int] = {}

    def node_id(point: tuple[float, float, float]) -> int:
        key = tuple(round(value, 12) for value in point)
        existing = coordinate_to_id.get(key)
        if existing is not None:
            return existing
        result = len(nodes) + 1
        coordinate_to_id[key] = result
        nodes.append(Node(result, *point))
        return result

    def positions(lower: float, upper: float, spacing: float) -> tuple[float, ...]:
        if lower >= upper:
            raise ValueError("fixed stair cover leaves no reinforcement span")
        values = [lower]
        candidate = lower + spacing
        while candidate < upper - 1.0e-12:
            values.append(candidate)
            candidate += spacing
        values.append(upper)
        return tuple(values)

    def add_beam(
        start: tuple[float, float, float],
        end: tuple[float, float, float],
        role: str,
    ) -> None:
        beams.append(
            BeamElement(
                len(beams) + 1,
                (node_id(start), node_id(end)),
                role,
            )
        )

    for box_index, box in enumerate(boxes):
        if 2.0 * cover + diameter >= min(
            box.max_x - box.min_x,
            box.max_y - box.min_y,
            box.max_z - box.min_z,
        ):
            raise ValueError("cover/bar combination does not fit fixed stair_A")
        x0 = box.min_x + cover
        x1 = box.max_x - cover
        y0 = box.min_y + cover
        y1 = box.max_y - cover
        z = box.max_z - cover
        for y in positions(y0, y1, longitudinal_spacing):
            add_beam((x0, y, z), (x1, y, z), "fixed_stair_rebar")
        for x in positions(x0, x1, distribution_spacing):
            add_beam(
                (x, y0, z),
                (x, y1, z),
                "fixed_stair_distribution_rebar",
            )
        if box_index in {0, len(boxes) - 1}:
            for x in positions(x0, x1, distribution_spacing / densification):
                add_beam(
                    (x, y0, z - diameter),
                    (x, y1, z - diameter),
                    "fixed_stair_local_rebar",
                )
    roles = (
        "fixed_stair_distribution_rebar",
        "fixed_stair_local_rebar",
        "fixed_stair_rebar",
    )
    return MeshFragment(
        nodes=tuple(nodes),
        beams=tuple(beams),
        part_bindings=tuple(
            PartBinding(role, "reinforcing_steel", f"{role}_beam_section")
            for role in roles
        ),
    )


def _task4_shared_face_role_interface_ids(
    mesh: MeshFragment,
    *,
    source_roles: set[str],
    target_roles: set[str],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    face_indices = (
        (0, 1, 2, 3),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    )
    target_by_face: dict[frozenset[int], list[int]] = {}
    for solid in mesh.solids:
        if solid.part_role in target_roles:
            for indices in face_indices:
                face = frozenset(solid.node_ids[index] for index in indices)
                target_by_face.setdefault(face, []).append(solid.element_id)
    sources: set[int] = set()
    targets: set[int] = set()
    for solid in mesh.solids:
        if solid.part_role not in source_roles:
            continue
        for indices in face_indices:
            face = frozenset(solid.node_ids[index] for index in indices)
            neighbors = target_by_face.get(face, ())
            if neighbors:
                sources.add(solid.element_id)
                targets.update(neighbors)
    return tuple(sorted(sources)), tuple(sorted(targets))


def _task4_structural_interface_ids(
    mesh: MeshFragment,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    groups = _task4_structural_interface_groups(mesh)
    return (
        tuple(
            sorted(
                {
                    element_id
                    for source_ids, _ in groups.values()
                    for element_id in source_ids
                }
            )
        ),
        tuple(
            sorted(
                {
                    element_id
                    for _, target_ids in groups.values()
                    for element_id in target_ids
                }
            )
        ),
    )


def _task4_structural_interface_groups(
    mesh: MeshFragment,
) -> dict[str, tuple[tuple[int, ...], tuple[int, ...]]]:
    groups, _ = _task4_structural_interface_groups_with_stats(mesh)
    return groups


def _task4_structural_interface_groups_with_stats(
    mesh: MeshFragment,
) -> tuple[dict[str, tuple[tuple[int, ...], tuple[int, ...]]], int]:
    nodes = {row.node_id: row.coordinates for row in mesh.nodes}
    bounds_by_id: dict[int, tuple[float, ...]] = {}
    circulation_roles: dict[int, str] = {}
    enclosure_ids: list[int] = []
    for solid in mesh.solids:
        points = [nodes[node_id] for node_id in solid.node_ids]
        bounds_by_id[solid.element_id] = (
            tuple(min(point[axis] for point in points) for axis in range(3))
            + tuple(max(point[axis] for point in points) for axis in range(3))
        )
        if solid.part_role.startswith("rc_"):
            enclosure_ids.append(solid.element_id)
        else:
            circulation_roles[solid.element_id] = solid.part_role

    target_faces: dict[
        tuple[int, float, int], list[tuple[int, float, float, float, float]]
    ] = {}
    for element_id in enclosure_ids:
        bounds = bounds_by_id[element_id]
        for axis in range(3):
            other_axes = tuple(index for index in range(3) if index != axis)
            rectangle = (
                element_id,
                bounds[other_axes[0]],
                bounds[other_axes[0] + 3],
                bounds[other_axes[1]],
                bounds[other_axes[1] + 3],
            )
            target_faces.setdefault(
                (axis, round(bounds[axis], 9), -1), []
            ).append(rectangle)
            target_faces.setdefault(
                (axis, round(bounds[axis + 3], 9), 1), []
            ).append(rectangle)

    source_faces: dict[
        tuple[int, float, int],
        list[tuple[int, str, float, float, float, float]],
    ] = {}
    for source_id, role in circulation_roles.items():
        bounds = bounds_by_id[source_id]
        for axis in range(3):
            other_axes = tuple(index for index in range(3) if index != axis)
            rectangle = (
                source_id,
                role,
                bounds[other_axes[0]],
                bounds[other_axes[0] + 3],
                bounds[other_axes[1]],
                bounds[other_axes[1] + 3],
            )
            source_faces.setdefault(
                (axis, round(bounds[axis], 9), 1), []
            ).append(rectangle)
            source_faces.setdefault(
                (axis, round(bounds[axis + 3], 9), -1), []
            ).append(rectangle)

    grouped: dict[str, tuple[set[int], set[int]]] = {}
    tolerance = 1.0e-9
    candidate_checks = 0
    for plane_key, sources in source_faces.items():
        targets = target_faces.get(plane_key)
        if not targets:
            continue
        u_values = sorted(
            {value for _, u0, u1, _, _ in targets for value in (u0, u1)}
        )
        v_values = sorted(
            {value for _, _, _, v0, v1 in targets for value in (v0, v1)}
        )
        u_indices = {value: index for index, value in enumerate(u_values)}
        v_indices = {value: index for index, value in enumerate(v_values)}
        cells: dict[tuple[int, int], list[int]] = {}
        target_rectangles: dict[int, tuple[float, float, float, float]] = {}
        for target_id, u0, u1, v0, v1 in targets:
            target_rectangles[target_id] = (u0, u1, v0, v1)
            for u_index in range(u_indices[u0], u_indices[u1]):
                for v_index in range(v_indices[v0], v_indices[v1]):
                    cells.setdefault((u_index, v_index), []).append(target_id)

        for source_id, role, u0, u1, v0, v1 in sources:
            if (
                u1 <= u_values[0]
                or u0 >= u_values[-1]
                or v1 <= v_values[0]
                or v0 >= v_values[-1]
            ):
                continue
            u_start = max(0, bisect_right(u_values, u0) - 1)
            u_stop = min(len(u_values) - 1, bisect_left(u_values, u1))
            v_start = max(0, bisect_right(v_values, v0) - 1)
            v_stop = min(len(v_values) - 1, bisect_left(v_values, v1))
            candidates = {
                target_id
                for u_index in range(u_start, u_stop)
                for v_index in range(v_start, v_stop)
                for target_id in cells.get((u_index, v_index), ())
            }
            for target_id in candidates:
                candidate_checks += 1
                target_u0, target_u1, target_v0, target_v1 = (
                    target_rectangles[target_id]
                )
                if (
                    min(u1, target_u1) - max(u0, target_u0) > tolerance
                    and min(v1, target_v1) - max(v0, target_v0) > tolerance
                ):
                    source_ids, target_ids = grouped.setdefault(
                        role, (set(), set())
                    )
                    source_ids.add(source_id)
                    target_ids.add(target_id)
    if not grouped:
        raise ValueError("Task 4 subway has no structural face interface")
    return (
        {
            role: (tuple(sorted(source_ids)), tuple(sorted(target_ids)))
            for role, (source_ids, target_ids) in sorted(grouped.items())
        },
        candidate_checks,
    )


def _retag_beam_fragment(fragment: MeshFragment, role: str) -> MeshFragment:
    return MeshFragment(
        nodes=fragment.nodes,
        beams=tuple(BeamElement(row.element_id, row.node_ids, role) for row in fragment.beams),
        part_bindings=(PartBinding(role, "reinforcing_steel", f"{role}_beam_section"),),
    )


def _compile_task4_subway_mesh(parameters: object) -> MeshFragment | None:
    if not isinstance(parameters, Mapping):
        return None
    component_rows = parameters.get("task4_subway_components")
    if component_rows is None:
        return None
    if not isinstance(component_rows, list):
        raise ValueError("Task 4 subway mesh declarations must be lists")

    fragments: list[MeshFragment] = []
    if component_rows:
        coordinate_to_id: dict[tuple[float, float, float], int] = {}
        nodes: list[Node] = []
        shells: list[ShellElement] = []
        beams: list[BeamElement] = []
        bindings: dict[str, PartBinding] = {}

        def node_id(raw: object, path: str) -> int:
            if not isinstance(raw, list) or len(raw) != 3:
                raise ValueError(f"{path} must contain three coordinates")
            coordinate = tuple(_finite_number(value, path) for value in raw)
            existing = coordinate_to_id.get(coordinate)
            if existing is not None:
                return existing
            result = len(nodes) + 1
            coordinate_to_id[coordinate] = result
            nodes.append(Node(result, *coordinate))
            return result

        for index, row in enumerate(component_rows):
            if not isinstance(row, Mapping):
                raise ValueError(f"task4_subway_components[{index}] must be a mapping")
            role = row.get("part_role")
            material = row.get("material_role")
            kind = row.get("kind")
            points = row.get("points_m")
            if not isinstance(role, str) or not role.strip():
                raise ValueError(f"task4_subway_components[{index}].part_role is required")
            if not isinstance(material, str) or not material.strip():
                raise ValueError(f"task4_subway_components[{index}].material_role is required")
            if kind not in {"beam", "shell"} or not isinstance(points, list):
                raise ValueError(f"task4_subway_components[{index}] has invalid geometry")
            expected = 2 if kind == "beam" else 4
            if len(points) != expected:
                raise ValueError(f"task4_subway_components[{index}].points_m needs {expected} points")
            ids = tuple(node_id(point, f"task4_subway_components[{index}].points_m") for point in points)
            element_id = len(shells) + len(beams) + 1
            if kind == "beam":
                beams.append(BeamElement(element_id, ids, role))  # type: ignore[arg-type]
                section = f"{role}_beam_section"
            else:
                shells.append(ShellElement(element_id, ids, role))  # type: ignore[arg-type]
                section = f"{role}_shell_section"
            binding = PartBinding(role, material, section)
            previous = bindings.get(role)
            if previous is not None and previous != binding:
                raise ValueError(f"conflicting Task 4 component role {role!r}")
            bindings[role] = binding
        fragments.append(
            MeshFragment(
                nodes=tuple(nodes),
                shells=tuple(shells),
                beams=tuple(beams),
                part_bindings=tuple(bindings[key] for key in sorted(bindings)),
            )
        )
    return merge_fragments_welded(fragments)


def _normalize_generation_options(
    value: Mapping[str, object] | None,
    system_id: str,
    resource_id: str,
    geometry: Mapping[str, float],
) -> dict[str, object]:
    if value is None:
        raw: dict[str, object] = {}
    elif isinstance(value, Mapping):
        raw = dict(value)
    else:
        raise TypeError("generation_options must be a mapping")
    if any(not isinstance(key, str) for key in raw):
        raise ValueError("generation option names must be strings")
    unknown = set(raw) - _GENERATION_KEYS
    if unknown:
        raise ValueError(f"unsupported generation option: {sorted(unknown)}")
    subway_keys = set(raw) & set(_SUBWAY_GENERATION_KEYS)
    if (
        resource_id != "subway_entrance_detailed_building"
        and subway_keys
    ):
        raise ValueError(
            f"subway generation options are not supported by {resource_id!r}: "
            f"{sorted(subway_keys)}"
        )
    max_solids = _normalize_budget_limit(
        raw.get("max_solid_elements", _DEFAULT_MAX_SOLIDS),
        "max_solid_elements",
    )
    mode = raw.get("reinforcement_mode", "full_reinforced")
    if not isinstance(mode, str) or mode not in {
        "full_reinforced",
        "concrete_only",
        "custom",
    }:
        raise ValueError(f"unsupported reinforcement_mode: {mode!r}")
    include_raw = raw.get("include_reinforcement_roles")
    if mode == "custom":
        if not isinstance(include_raw, Sequence) or isinstance(
            include_raw, (str, bytes, bytearray)
        ):
            raise ValueError("include_reinforcement_roles must be a list for custom mode")
        include = tuple(include_raw)
        if any(not isinstance(role, str) or not role.strip() for role in include):
            raise ValueError("include_reinforcement_roles must contain role ids")
        if len(set(include)) != len(include):
            raise ValueError("include_reinforcement_roles must not contain duplicates")
        allowed = _HYBRID_REBAR_ROLES if system_id == "steel_concrete_hybrid" else REINFORCEMENT_ROLES
        unknown_roles = set(include) - set(allowed)
        if unknown_roles:
            raise ValueError(f"unknown reinforcement roles: {sorted(unknown_roles)}")
    elif include_raw is not None:
        raise ValueError("include_reinforcement_roles is valid only for custom mode")
    else:
        include = ()
    result: dict[str, object] = {
        "max_solid_elements": max_solids,
        "reinforcement_mode": mode,
        "cover_m": _positive_number(raw.get("cover_m", 0.04), "cover_m"),
        "bar_diameter_m": _positive_number(
            raw.get("bar_diameter_m", 0.016), "bar_diameter_m"
        ),
        "rebar_spacing_m": _positive_number(
            raw.get("rebar_spacing_m", 0.30), "rebar_spacing_m"
        ),
    }
    for key in (
        "max_beam_elements",
        "max_shell_elements",
        "max_node_count",
        "max_total_elements",
    ):
        if key in raw:
            result[key] = _normalize_budget_limit(raw[key], key)
    storey_raw = raw.get("storey_count")
    if resource_id == "residential_community_detailed_building":
        if storey_raw is None:
            tower_height = float(geometry["tower_height_m"])
            storey_count = max(1, math.floor(tower_height / 3.0 + 0.5))
        elif (
            isinstance(storey_raw, bool)
            or not isinstance(storey_raw, int)
            or storey_raw <= 0
        ):
            raise ValueError("storey_count must be a positive integer")
        else:
            storey_count = storey_raw
        result["storey_count"] = storey_count
    elif storey_raw is not None:
        raise ValueError(
            "storey_count is supported only by residential_community_detailed_building"
        )
    if resource_id == "subway_entrance_detailed_building":
        result.update(_normalize_subway_generation_options(raw, geometry))
    if mode == "custom":
        result["include_reinforcement_roles"] = list(include)
    return result


def _normalize_subway_generation_options(
    raw: Mapping[str, object], geometry: Mapping[str, float]
) -> dict[str, object]:
    length = float(geometry["length_m"])
    width = float(geometry["width_m"])
    floor = float(geometry["platform_height_m"])
    clear_height = float(geometry["enclosure_height_m"])
    wall = float(geometry["wall_thickness_m"])
    roof = float(geometry["roof_thickness_m"])
    inner_width = width - 2.0 * wall
    if inner_width <= 0.0:
        raise ValueError("wall_thickness_m leaves no valid subway circulation connection")

    positive_defaults = {
        "stair_width_m": inner_width * 0.34,
        "stair_tread_m": 0.25,
        "stair_rise_m": 0.15,
        "escalator_width_m": inner_width * 0.22,
        "escalator_rise_m": clear_height,
        "escalator_equipment_envelope_m": min(0.12, inner_width * 0.03),
        "lane_gap_m": min(0.10, inner_width * 0.03),
        "upper_landing_length_m": max(0.30, length * 0.075),
        "lower_landing_length_m": max(0.30, length * 0.075),
        "passage_length_m": max(0.80, length * 0.25),
        "passage_clear_width_m": inner_width,
        "passage_clear_height_m": clear_height,
        "passage_floor_thickness_m": floor,
        "passage_wall_thickness_m": wall,
        "passage_roof_thickness_m": roof,
        "pavilion_width_m": width,
        "pavilion_clear_height_m": clear_height,
        "pavilion_roof_arc_rise_m": min(0.30, clear_height * 0.10),
        "pavilion_overhang_m": min(0.60, length * 0.10),
        "pavilion_frame_size_m": min(0.12, wall * 0.50),
        "pavilion_glazing_thickness_m": min(0.03, wall * 0.10),
        "pavilion_roof_thickness_m": min(0.06, roof * 0.25),
        "upper_landing_clear_width_m": inner_width,
        "lower_landing_clear_width_m": inner_width,
    }
    result = {
        key: _positive_number(raw.get(key, default), key)
        for key, default in positive_defaults.items()
    }
    required_pavilion_clear_height = float(result["passage_clear_height_m"])
    if (
        float(result["pavilion_clear_height_m"]) + 1.0e-12
        < required_pavilion_clear_height
    ):
        raise ValueError(
            "pavilion_clear_height_m must be at least "
            f"{required_pavilion_clear_height:.6g} m to cover "
            "passage_clear_height_m beneath the physical roof shell"
        )
    upper = float(result["upper_landing_length_m"])
    lower = float(result["lower_landing_length_m"])
    angle = _positive_number(
        raw.get(
            "escalator_angle_deg",
            math.degrees(math.atan2(float(result["escalator_rise_m"]), length)),
        ),
        "escalator_angle_deg",
    )
    if not 10.0 <= angle <= 45.0:
        raise ValueError("escalator_angle_deg must be from 10 to 45 degrees")
    result["escalator_angle_deg"] = angle
    descent_length = float(result["escalator_rise_m"]) / math.tan(
        math.radians(angle)
    )
    stair_slope = _positive_number(
        raw.get("fixed_stair_slope_deg", angle), "fixed_stair_slope_deg"
    )
    if not 10.0 <= stair_slope <= 45.0:
        raise ValueError("fixed_stair_slope_deg must be from 10 to 45 degrees")
    stair_descent_length = float(result["escalator_rise_m"]) / math.tan(
        math.radians(stair_slope)
    )
    if stair_descent_length > upper + descent_length + 1.0e-12:
        raise ValueError(
            "fixed_stair_slope_deg cannot connect the approved upper and lower landings"
        )
    result["fixed_stair_slope_deg"] = stair_slope
    default_longitudinal_spacing = min(
        float(raw.get("rebar_spacing_m", 0.30)),
        float(result["stair_width_m"]) / 3.0,
    )
    default_distribution_spacing = min(
        float(raw.get("rebar_spacing_m", 0.30)),
        float(result["stair_tread_m"]) / 2.0,
    )
    result["fixed_stair_longitudinal_spacing_m"] = _positive_number(
        raw.get(
            "fixed_stair_longitudinal_spacing_m",
            default_longitudinal_spacing,
        ),
        "fixed_stair_longitudinal_spacing_m",
    )
    result["fixed_stair_distribution_spacing_m"] = _positive_number(
        raw.get(
            "fixed_stair_distribution_spacing_m",
            default_distribution_spacing,
        ),
        "fixed_stair_distribution_spacing_m",
    )
    densification = _finite_number(
        raw.get("fixed_stair_local_densification_factor", 2.0),
        "fixed_stair_local_densification_factor",
    )
    if not 1.0 <= densification <= 4.0:
        raise ValueError(
            "fixed_stair_local_densification_factor must be from 1 to 4"
        )
    result["fixed_stair_local_densification_factor"] = densification
    connection_level = raw.get("connection_simplification_level", "aggregate")
    if not isinstance(connection_level, str) or connection_level not in {
        "aggregate",
        "role_resolved",
    }:
        raise ValueError(
            "connection_simplification_level must be aggregate or role_resolved"
        )
    result["connection_simplification_level"] = connection_level
    result["pavilion_length_m"] = _positive_number(
        raw.get("pavilion_length_m", upper + descent_length + lower),
        "pavilion_length_m",
    )
    glazing_bay_count = _positive_integer_option(
        raw.get("glazing_bay_count", 6), "glazing_bay_count"
    )
    bay_boundary_count = glazing_bay_count + 1
    family_lower_bounds = {
        "max_solid_elements": 2 * bay_boundary_count,
        "max_beam_elements": 2 * bay_boundary_count,
        "max_shell_elements": glazing_bay_count,
        "max_node_count": 2 * bay_boundary_count,
        "max_total_elements": 4 * bay_boundary_count + glazing_bay_count,
    }
    family_labels = {
        "max_solid_elements": "Solid elements",
        "max_beam_elements": "Beam elements",
        "max_shell_elements": "Shell elements",
        "max_node_count": "Node count",
        "max_total_elements": "Total elements",
    }
    for key in sorted(family_lower_bounds, key=lambda value: value not in raw):
        lower_bound = family_lower_bounds[key]
        limit = int(raw.get(key, _GENERATION_HARD_CAPS[key]))
        if lower_bound > limit:
            raise ValueError(
                f"{family_labels[key]} proved lower bound {lower_bound} exceeds limit {limit}"
            )
    if glazing_bay_count > 100_000:
        raise ValueError("glazing_bay_count exceeds internal template hard cap 100000")
    result["glazing_bay_count"] = glazing_bay_count

    turn = _finite_number(raw.get("passage_turn_deg", 0.0), "passage_turn_deg")
    if abs(turn) > 1.0e-12:
        raise ValueError("approved subway route does not permit a turn")
    result["passage_turn_deg"] = 0.0
    for key in ("additional_stair_count", "additional_escalator_count"):
        count = _nonnegative_integer_option(raw.get(key, 0), key)
        if count:
            raise ValueError("approved subway route does not permit additional circulation lanes")
        result[key] = 0

    connection_width = (
        float(result["stair_width_m"])
        + 2.0
        * (
            float(result["escalator_width_m"])
            + 2.0 * float(result["escalator_equipment_envelope_m"])
        )
        + 2.0 * float(result["lane_gap_m"])
    )
    if connection_width > inner_width + 1.0e-12:
        raise ValueError("stair and escalator lane envelopes overlap the RC side walls")
    if float(result["passage_clear_width_m"]) + 1.0e-12 < connection_width:
        raise ValueError("passage_clear_width_m is narrower than the circulation connection")
    if float(result["passage_clear_width_m"]) > inner_width + 1.0e-12:
        raise ValueError("passage_clear_width_m exceeds the RC enclosure clear width")
    for landing_key in (
        "upper_landing_clear_width_m",
        "lower_landing_clear_width_m",
    ):
        landing_width = float(result[landing_key])
        if landing_width + 1.0e-12 < connection_width:
            raise ValueError(f"{landing_key} is narrower than the circulation connection")
        if landing_width > inner_width + 1.0e-12:
            raise ValueError(f"{landing_key} exceeds the RC enclosure clear width")
    if float(result["pavilion_width_m"]) + 1.0e-12 < connection_width:
        raise ValueError("pavilion_width_m is narrower than the circulation connection")
    if float(result["pavilion_width_m"]) > width + 1.0e-12:
        raise ValueError("pavilion_width_m exceeds the subway entrance width")
    full_route_width = max(
        connection_width,
        float(result["passage_clear_width_m"]),
        float(result["upper_landing_clear_width_m"]),
        float(result["lower_landing_clear_width_m"]),
    )
    minimum_pavilion_width = (
        full_route_width + 2.0 * float(result["pavilion_frame_size_m"])
    )
    if float(result["pavilion_width_m"]) + 1.0e-12 < minimum_pavilion_width:
        raise ValueError(
            "pavilion_width_m must keep the frame/plinth footprint outside the "
            f"full-width A/B/C route (minimum {minimum_pavilion_width:.6g} m)"
        )
    if float(result["pavilion_length_m"]) + 1.0e-12 < upper + descent_length + lower:
        raise ValueError("pavilion_length_m must cover the complete descent")
    if float(result["pavilion_overhang_m"]) >= float(result["pavilion_length_m"]):
        raise ValueError("pavilion_overhang_m must be shorter than pavilion_length_m")
    total_route_length = (
        upper
        + descent_length
        + lower
        + float(result["passage_length_m"])
    )
    if (
        float(result["pavilion_length_m"])
        + float(result["pavilion_overhang_m"])
        > total_route_length + 1.0e-12
    ):
        raise ValueError(
            "pavilion_length_m plus pavilion_overhang_m exceeds the entrance route"
        )
    if 2.0 * float(result["pavilion_frame_size_m"]) >= float(result["pavilion_width_m"]):
        raise ValueError("pavilion_frame_size_m leaves no pavilion clear width")
    if 2.0 * float(result["pavilion_glazing_thickness_m"]) >= float(result["pavilion_width_m"]):
        raise ValueError("pavilion_glazing_thickness_m leaves no pavilion clear width")
    return result


def _normalize_budget_limit(value: object, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{key} must be a positive integer")
    hard_cap = _GENERATION_HARD_CAPS[key]
    if value > hard_cap:
        raise ValueError(f"{key} exceeds hard cap {hard_cap}")
    return value


def _effective_generation_limits(options: Mapping[str, object]) -> dict[str, int]:
    return {
        key: int(options.get(key, hard_cap))
        for key, hard_cap in _GENERATION_HARD_CAPS.items()
    }


def _enforce_generation_preflight(
    preflight: Mapping[str, Mapping[str, object]],
    limits: Mapping[str, int],
    *,
    resource_id: str,
    mesh_profile: str,
) -> None:
    labels = {
        "beam_elements": "Beam elements",
        "shell_elements": "Shell elements",
        "node_count": "Node count",
        "total_elements": "Total elements",
    }
    for family, label in labels.items():
        row = preflight[family]
        estimate = int(row["estimated_count"])
        limit = limits[_PREFLIGHT_LIMIT_KEYS[family]]
        if estimate > limit:
            kind = str(row["estimation_kind"]).replace("_", " ")
            raise ValueError(
                f"{resource_id}/{mesh_profile} {label} {kind} {estimate} "
                f"exceeds limit {limit}; the selected generation was not automatically coarsened"
            )


def _verify_generation_preflight(
    preflight: Mapping[str, Mapping[str, object]],
    actual: Mapping[str, int],
) -> None:
    for family, actual_count in actual.items():
        row = preflight[family]
        estimate = int(row["estimated_count"])
        kind = str(row["estimation_kind"])
        if actual_count > estimate:
            raise ValueError(f"{family} preflight upper bound was exceeded by generated artifact")
        if kind == "exact" and actual_count != estimate:
            raise ValueError(f"exact {family} preflight estimate does not match generated artifact")


def _positive_integer_option(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _nonnegative_integer_option(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _normalize_material_overrides(
    value: Mapping[str, object] | None,
    descriptor: DetailedBuildingAssetDescriptor,
) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("material_overrides must be a mapping")
    if any(not isinstance(role, str) for role in value):
        raise ValueError("material override roles must be strings")
    unknown = set(value) - set(descriptor.material_override_roles)
    if unknown:
        raise ValueError(f"unknown material override role: {sorted(unknown)}")
    result: dict[str, str] = {}
    for role, material_id in value.items():
        if not isinstance(material_id, str) or not material_id.strip():
            raise ValueError(f"material override {role!r} must name an existing resource")
        result[role] = material_id.strip()
    return result


def _resolve_material_bindings(
    descriptor: DetailedBuildingAssetDescriptor,
    artifacts: Sequence[BuildingArtifact],
    overrides: Mapping[str, str],
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for artifact in artifacts:
        solid_roles = {row.part_role for row in artifact.mesh.solids}
        for binding in artifact.mesh.part_bindings:
            semantic = _semantic_material_role(binding, solid_roles)
            resource_id = overrides.get(semantic)
            if resource_id is None:
                candidate = descriptor.material_candidates.get(semantic)
                resource_id = str(candidate) if candidate is not None else None
            material = _material_record(semantic, resource_id)
            rows.append(
                {
                    "artifact_id": artifact.asset_id,
                    "part_role": binding.part_role,
                    "source_material_role": binding.material_role,
                    "section_role": binding.section_role,
                    "semantic_role": semantic,
                    **material,
                }
            )
    rows.sort(
        key=lambda row: (
            str(row["artifact_id"]),
            str(row["part_role"]),
            str(row["semantic_role"]),
        )
    )
    used_semantic_roles = {str(row["semantic_role"]) for row in rows}
    unused_overrides = sorted(set(overrides) - used_semantic_roles)
    if unused_overrides:
        raise ValueError(f"material override roles are not used by this asset: {unused_overrides}")
    return {
        "schema_version": "0.1.0",
        "bindings": rows,
        "resolved_count": sum(row["resolution_status"] == "resolved" for row in rows),
        "unresolved_count": sum(row["resolution_status"] == "unresolved" for row in rows),
        "requires_project_review": True,
    }


def _semantic_material_role(binding: PartBinding, solid_roles: set[str]) -> str:
    if binding.part_role in _REBAR_PART_ROLES or binding.material_role == "reinforcing_steel":
        return "reinforcing_steel"
    if binding.material_role == "structural_steel" or binding.part_role.startswith("steel_"):
        return "structural_steel"
    if binding.part_role in solid_roles or binding.material_role == "concrete":
        return "concrete"
    if binding.material_role in {"facade", "glazing", "doors", "nonstructural"}:
        return binding.material_role
    return binding.material_role


def _material_record(semantic_role: str, resource_id: str | None) -> dict[str, object]:
    if resource_id is None:
        return {
            "resolution_status": "unresolved",
            "resource_id": None,
            "version": None,
            "unit_system": None,
            "category": None,
            "material_type": None,
            "effective_validation_status": "unresolved",
            "canonical_resource_sha256": None,
            "density_kg_per_m3": None,
            "requires_project_review": True,
        }
    try:
        if semantic_role == "concrete":
            resource = get_reviewed_material_resource(
                resource_id, {"concrete_damage_rel3"}
            )
            if resource.get("category") != "concrete":
                raise ValueError("category must be concrete")
        elif semantic_role == "reinforcing_steel":
            resource = get_reviewed_material_resource(
                resource_id, {"plastic_kinematic"}
            )
            if resource.get("category") != "rebar_steel":
                raise ValueError("category must be rebar_steel")
        else:
            resource = get_material(resource_id)
            if semantic_role == "structural_steel":
                if resource.get("category") != "steel":
                    raise ValueError("category must be steel")
                if resource.get("type") not in {
                    "elastic",
                    "piecewise_linear_plasticity",
                }:
                    raise ValueError("type must be elastic or piecewise_linear_plasticity")
            elif semantic_role in _NONSTRUCTURAL_OVERRIDE_CATEGORIES:
                allowed_categories = _NONSTRUCTURAL_OVERRIDE_CATEGORIES[semantic_role]
                if resource.get("category") not in allowed_categories:
                    raise ValueError(
                        f"category must be one of: {sorted(allowed_categories)}"
                    )
    except ValueError as exc:
        label = semantic_role.replace("_", " ")
        raise ValueError(f"{label} material {resource_id!r} is incompatible: {exc}") from exc
    if resource.get("unit_system") != _UNIT_SYSTEM:
        raise ValueError(
            f"{semantic_role.replace('_', ' ')} material {resource_id!r} must use {_UNIT_SYSTEM}"
        )
    density_raw = resource.get("density_kg_per_m3")
    density = (
        float(density_raw)
        if isinstance(density_raw, (int, float)) and not isinstance(density_raw, bool)
        else None
    )
    return {
        "resolution_status": "resolved",
        "resource_id": str(resource["id"]),
        "version": str(resource.get("version", "unknown")),
        "unit_system": str(resource["unit_system"]),
        "category": str(resource.get("category", "unknown")),
        "material_type": str(resource.get("type", "unknown")),
        "effective_validation_status": str(
            resource.get("effective_validation_status", resource.get("validation_status", "demo"))
        ),
        "canonical_resource_sha256": canonical_resource_sha256(resource),
        "density_kg_per_m3": density,
        "requires_project_review": bool(resource.get("requires_project_review", True)),
    }


def _mesh_manifest(
    descriptor: DetailedBuildingAssetDescriptor,
    artifacts: Sequence[BuildingArtifact],
    mesh_profile: str,
    solid_estimate: int,
    estimate_kind: str,
    preflight: Mapping[str, Mapping[str, object]],
    limits: Mapping[str, int],
) -> dict[str, object]:
    counts = {
        "nodes": sum(len(row.mesh.nodes) for row in artifacts),
        "solids": sum(len(row.mesh.solids) for row in artifacts),
        "shells": sum(len(row.mesh.shells) for row in artifacts),
        "beams": sum(len(row.mesh.beams) for row in artifacts),
        "connections": sum(len(row.connections) for row in artifacts),
    }
    artifact_rows = [
        {
            "asset_id": artifact.asset_id,
            "bounds_m": list(artifact.mesh.bounds_m),
            "mesh_fingerprint": artifact.mesh.fingerprint,
            "element_count": (
                len(artifact.mesh.solids)
                + len(artifact.mesh.shells)
                + len(artifact.mesh.beams)
            ),
            "nodes": len(artifact.mesh.nodes),
            "solids": len(artifact.mesh.solids),
            "shells": len(artifact.mesh.shells),
            "beams": len(artifact.mesh.beams),
            "connections": len(artifact.connections),
        }
        for artifact in artifacts
    ]
    estimate_row = (
        {"predicted_solid_elements": solid_estimate}
        if estimate_kind == "exact"
        else {"solid_element_upper_bound": solid_estimate}
    )
    return {
        "schema_version": "0.1.0",
        "mesh_profile": mesh_profile,
        "profile_parameters": _thaw(descriptor.mesh_profile_rows[mesh_profile]),
        "solid_estimate_kind": estimate_kind,
        **estimate_row,
        "actual_solid_elements": counts["solids"],
        "preflight": {
            family: {
                **dict(row),
                "limit": limits[_PREFLIGHT_LIMIT_KEYS[family]],
            }
            for family, row in preflight.items()
        },
        "counts": counts,
        "artifacts": artifact_rows,
        "aggregate_mesh_fingerprint": _fingerprint(artifact_rows),
    }


def _quantity_manifest(artifacts: Sequence[BuildingArtifact]) -> dict[str, object]:
    solid_volume = 0.0
    by_role: dict[str, float] = {}
    occupied_by_role: dict[str, float] = {}
    declared_space_volume = 0.0
    gross_envelope_volume = 0.0
    for artifact in artifacts:
        nodes = {node.node_id: node.coordinates for node in artifact.mesh.nodes}
        spaces = _normalized_boxes(artifact.normalized_input.get("spaces"), "spaces")
        envelopes = _normalized_envelope(artifact)
        gross_envelope_volume += _box_volume(envelopes)
        declared_space_volume += sum(_box_volume(box) for box in spaces)
        for solid in artifact.mesh.solids:
            box = _element_box(solid.node_ids, nodes)
            volume = _box_volume(box)
            solid_volume += volume
            by_role[solid.part_role] = by_role.get(solid.part_role, 0.0) + volume
            occupied = sum(_intersection_volume(box, space) for space in spaces)
            if occupied > 0.0:
                occupied_by_role[solid.part_role] = (
                    occupied_by_role.get(solid.part_role, 0.0) + occupied
                )
    occupied_total = sum(occupied_by_role.values())
    unexpected_by_role = {
        role: volume
        for role, volume in occupied_by_role.items()
        if "foundation" in role or "slab" in role or role in {"rc_box_floor", "rc_box_roof"}
    }
    net_air = declared_space_volume - occupied_total
    if net_air < -1.0e-9:
        raise ValueError("structural occupied volume exceeds declared space volume")
    return {
        "schema_version": "0.1.0",
        "gross_envelope_volume_m3": gross_envelope_volume,
        "solid_volume_m3": solid_volume,
        "solid_volume_by_role_m3": dict(sorted(by_role.items())),
        "declared_space_volume_m3": declared_space_volume,
        "structural_occupied_volume_m3": occupied_total,
        "structural_occupied_volume_by_role_m3": dict(sorted(occupied_by_role.items())),
        "unexpected_space_fill_volume_m3": sum(unexpected_by_role.values()),
        "unexpected_space_fill_by_role_m3": dict(sorted(unexpected_by_role.items())),
        "net_air_volume_m3": max(0.0, net_air),
    }


def _quality_manifest(
    artifacts: Sequence[BuildingArtifact],
    material_manifest: Mapping[str, object],
    quantities: Mapping[str, object],
) -> dict[str, object]:
    raw_bindings = material_manifest["bindings"]
    assert isinstance(raw_bindings, list)
    density_by_part: dict[tuple[str, str], float] = {}
    for row in raw_bindings:
        assert isinstance(row, dict)
        density = row.get("density_kg_per_m3")
        if isinstance(density, (int, float)) and not isinstance(density, bool):
            density_by_part[(str(row["artifact_id"]), str(row["part_role"]))] = float(density)
    solid_mass = 0.0
    solid_closure = True
    for artifact in artifacts:
        nodes = {node.node_id: node.coordinates for node in artifact.mesh.nodes}
        for solid in artifact.mesh.solids:
            density = density_by_part.get((artifact.asset_id, solid.part_role))
            if density is None:
                solid_closure = False
                continue
            solid_mass += _box_volume(_element_box(solid.node_ids, nodes)) * density
    beam_count = sum(len(artifact.mesh.beams) for artifact in artifacts)
    shell_count = sum(len(artifact.mesh.shells) for artifact in artifacts)
    mass_by_family: dict[str, object] = {
        "solid": (
            {"status": "evaluable", "value_kg": solid_mass}
            if solid_closure
            else {"status": "not_evaluable", "reason": "unresolved Solid density"}
        ),
        "beam": (
            {
                "status": "not_evaluable",
                "reason": "Beam section areas and role-specific section closure are not assigned",
            }
            if beam_count
            else {"status": "not_present"}
        ),
        "shell": (
            {
                "status": "not_evaluable",
                "reason": "Shell thickness and role-specific section closure are not assigned",
            }
            if shell_count
            else {"status": "not_present"}
        ),
    }
    unresolved_roles = sorted(
        {
            str(row["semantic_role"])
            for row in raw_bindings
            if isinstance(row, dict) and row.get("resolution_status") == "unresolved"
        }
    )
    present_families = tuple(
        row
        for row in mass_by_family.values()
        if isinstance(row, dict) and row.get("status") != "not_present"
    )
    if not present_families:
        total_mass: dict[str, object] = {"status": "not_present"}
    elif all(row.get("status") == "evaluable" for row in present_families):
        total_mass = {
            "status": "evaluable",
            "value_kg": sum(float(row["value_kg"]) for row in present_families),
        }
    else:
        total_mass = {
            "status": "not_evaluable",
            "reason": "at least one present element family lacks geometric mass closure",
            "unresolved_material_roles": unresolved_roles,
        }
    return {
        "schema_version": "0.1.0",
        "artifact_validation_findings": {
            artifact.asset_id: list(artifact.validation_findings) for artifact in artifacts
        },
        "mass_by_family": mass_by_family,
        "total_mass": total_mass,
        "unexpected_space_fill_volume_m3": quantities["unexpected_space_fill_volume_m3"],
        "software_validation_passed": not any(
            artifact.validation_findings for artifact in artifacts
        ),
        "engineering_validation_completed": False,
        "requires_project_review": True,
    }


def _normalized_boxes(value: object, name: str) -> tuple[tuple[float, ...], ...]:
    if not isinstance(value, list):
        raise ValueError(f"normalized {name} must be a list")
    result: list[tuple[float, ...]] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise ValueError(f"normalized {name} rows must be mappings")
        bounds = row.get("bounds_m")
        if not isinstance(bounds, list) or len(bounds) != 6:
            raise ValueError(f"normalized {name} bounds must contain six values")
        result.append(tuple(float(component) for component in bounds))
    return tuple(result)


def _normalized_envelope(artifact: BuildingArtifact) -> tuple[float, ...]:
    raw = artifact.normalized_input.get("envelope")
    if not isinstance(raw, Mapping):
        raise ValueError("normalized envelope must be a mapping")
    origin = raw.get("origin_m")
    size = raw.get("size_m")
    if not isinstance(origin, list) or not isinstance(size, list):
        raise ValueError("normalized envelope must contain origin_m and size_m")
    return tuple(float(origin[index]) for index in range(3)) + tuple(
        float(origin[index]) + float(size[index]) for index in range(3)
    )


def _element_box(
    node_ids: Sequence[int],
    nodes: Mapping[int, Sequence[float]],
) -> tuple[float, ...]:
    coordinates = [nodes[node_id] for node_id in node_ids]
    return tuple(min(point[axis] for point in coordinates) for axis in range(3)) + tuple(
        max(point[axis] for point in coordinates) for axis in range(3)
    )


def _box_volume(bounds: Sequence[float]) -> float:
    return math.prod(bounds[index + 3] - bounds[index] for index in range(3))


def _intersection_volume(left: Sequence[float], right: Sequence[float]) -> float:
    extents = tuple(
        max(0.0, min(left[axis + 3], right[axis + 3]) - max(left[axis], right[axis]))
        for axis in range(3)
    )
    return math.prod(extents)


def _finite_vector(value: Sequence[object], name: str) -> tuple[float, float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{name} must contain exactly three finite numbers")
    if len(value) != 3:
        raise ValueError(f"{name} must contain exactly three finite numbers")
    result: list[float] = []
    for component in value:
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            raise ValueError(f"{name} must contain exactly three finite numbers")
        number = float(component)
        if not math.isfinite(number):
            raise ValueError(f"{name} must contain exactly three finite numbers")
        result.append(number)
    return (result[0], result[1], result[2])


def _nonempty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _positive_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive finite number")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be a positive finite number")
    return result


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _fingerprint(value: object) -> str:
    canonical = json.dumps(
        _thaw(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


class _FrozenDict(dict[str, Any]):
    """JSON-serializable dict snapshot that rejects all mutation."""

    __slots__ = ()

    def _immutable(self, *args: object, **kwargs: object) -> None:
        raise TypeError("frozen artifact mapping cannot be mutated")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __ior__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable

    def __copy__(self) -> "_FrozenDict":
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> dict[str, Any]:
        return _thaw(self)


class _FrozenList(list[Any]):
    """List-compatible JSON snapshot that rejects all mutation."""

    __slots__ = ()

    def _immutable(self, *args: object, **kwargs: object) -> None:
        raise TypeError("frozen artifact list cannot be mutated")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable

    def __copy__(self) -> "_FrozenList":
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> list[Any]:
        return _thaw(self)


def _freeze_artifact(artifact: BuildingArtifact) -> BuildingArtifact:
    return replace(
        artifact,
        normalized_input=_freeze_artifact_json(artifact.normalized_input),
        topology_manifest=_freeze_artifact_json(artifact.topology_manifest),
        surface_catalog=_freeze_artifact_json(artifact.surface_catalog),
        dependency_manifest=tuple(
            _freeze_artifact_json(row) for row in artifact.dependency_manifest
        ),
    )


def _freeze_artifact_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenDict(
            {str(key): _freeze_artifact_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return _FrozenList(_freeze_artifact_json(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value
