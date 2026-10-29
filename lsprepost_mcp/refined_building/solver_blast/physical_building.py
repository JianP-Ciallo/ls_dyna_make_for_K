"""Build physically reviewed solver views of the three Phase 18D assets."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from ...keyword_checks import hexa_gauss_jacobians
from ..artifacts import (
    BeamElement,
    BuildingArtifact,
    MeshFragment,
    Node,
    PartBinding,
    SolidElement,
)
from ..asset_compiler import DetailedBuildingPackage
from ..meshing import merge_fragments_welded, mesh_axis_aligned_block_excluding
from ..spatial import AxisAlignedBox
from .contracts import AuditFinding, PhysicalInterfaceRecord, PhysicalMemberRecord
from .physical_audit import audit_physical_connections


COMMERCIAL_ID = "commercial_supermarket_detailed_building"
RESIDENTIAL_ID = "residential_community_detailed_building"
SUBWAY_ID = "subway_entrance_detailed_building"
SUPPORTED_RESOURCE_IDS = (COMMERCIAL_ID, RESIDENTIAL_ID, SUBWAY_ID)
_INTERNAL_NON_FLUID_ROLES = frozenset(
    {
        "fixed_stair_A",
        "lower_landing_8",
        "upper_landing",
        "pavilion_rc_plinth",
        "escalator_1_step_band",
        "escalator_1_truss_guides",
        "escalator_2_step_band",
        "escalator_2_truss_guides",
    }
)


@dataclass(frozen=True, slots=True)
class LoadPathEvidence:
    foundation_roles: tuple[str, ...]
    vertical_roles: tuple[str, ...]
    floor_or_roof_roles: tuple[str, ...]
    continuous: bool


@dataclass(frozen=True, slots=True)
class PhysicalBuildingModel:
    resource_id: str
    package_fingerprint: str
    artifacts: tuple[BuildingArtifact, ...]
    supplement_fragments: tuple[MeshFragment, ...]
    excluded_base_part_roles: tuple[str, ...]
    interfaces: tuple[PhysicalInterfaceRecord, ...]
    members: tuple[PhysicalMemberRecord, ...]
    load_path: LoadPathEvidence
    bounds_m: tuple[float, float, float, float, float, float]
    grade_elevation_m: float
    declared_opening_count: int
    unplanned_exterior_gap_intervals_m: tuple[tuple[float, float], ...]
    fingerprint: str

    def family_for_role(self, role: str) -> str:
        families = {row.element_family for row in self.members if row.role == role}
        if len(families) != 1:
            raise ValueError(f"role {role!r} does not have one physical element family")
        return next(iter(families))


def audit_physical_building(model: PhysicalBuildingModel) -> tuple[AuditFinding, ...]:
    if not isinstance(model, PhysicalBuildingModel):
        raise TypeError("model must be a PhysicalBuildingModel")
    return (
        *audit_physical_connections(model.members, model.interfaces),
        *_required_physics_findings(model.resource_id, model.members, model.interfaces),
        *_geometric_physics_findings(
            model.resource_id,
            model.artifacts,
            model.supplement_fragments,
            model.members,
            model.interfaces,
        ),
    )


def build_physical_building(package: DetailedBuildingPackage) -> PhysicalBuildingModel:
    """Create a solver-only physical view without mutating the Phase 18D package."""

    if not isinstance(package, DetailedBuildingPackage):
        raise TypeError("package must be a DetailedBuildingPackage")
    resource_id = package.resource_id
    if resource_id not in SUPPORTED_RESOURCE_IDS:
        raise ValueError(f"unsupported solver blast building resource: {resource_id!r}")

    if resource_id == COMMERCIAL_ID:
        column_boxes = _commercial_column_boxes(package)
        column_solid = _mesh_solid_boxes(column_boxes, "commercial_rc_column", "concrete")
        column_longitudinal, column_stirrups = _commercial_column_reinforcement(
            package, column_boxes
        )
        facade = _commercial_opaque_facade(package, column_boxes)
        wall_vertical, wall_horizontal = _commercial_wall_reinforcement(
            package, column_boxes
        )
        supplements = (
            facade,
            column_solid,
            column_longitudinal,
            column_stirrups,
            wall_vertical,
            wall_horizontal,
        )
        excluded = (
            "nonstructural_facade",
            "steel_column",
            "steel_opening_jamb",
            "steel_opening_header",
        )
        grade = 0.0
        gaps: tuple[tuple[float, float], ...] = ()
        load_path = _load_path(
            package,
            ("hybrid_foundation",),
            ("commercial_rc_column",),
            ("hybrid_slab", "steel_beam", "steel_roof_deck"),
            supplements,
        )
    elif resource_id == RESIDENTIAL_ID:
        supplements = tuple(
            _residential_opaque_facade(
                package,
                artifact,
                _residential_frame_exclusions(artifact),
            )
            for artifact in package.artifacts
        )
        excluded = ("nonstructural_facade", "nonstructural_balcony_slab")
        grade = 0.0
        gaps = ()
        load_path = _load_path(
            package,
            ("rc_foundation",),
            ("rc_column", "rc_shear_wall"),
            ("rc_slab", "rc_beam_x", "rc_beam_y"),
        )
    else:
        supplements = (_subway_opaque_solid_roof(package),)
        excluded = (
            "generic_signage",
            "nonstructural_architectural_finish",
            "pavilion_metal_roof",
        )
        circulation = _mapping(package.geometry_manifest["subway_circulation"], "subway_circulation")
        walkable = _mapping(
            circulation["walkable_surface_elevations_m"],
            "subway_circulation.walkable_surface_elevations_m",
        )
        grade = _finite(walkable["upper_landing"], "upper_landing grade")
        gaps = ()
        load_path = _load_path(
            package,
            ("rc_box_floor",),
            ("rc_box_wall", "pavilion_frame"),
            ("rc_box_roof", "upper_landing", "pavilion_opaque_solid_roof"),
            supplements,
        )

    interfaces = _physical_interface_records(package, supplements, frozenset(excluded))
    members = _physical_member_records(
        package,
        supplements,
        frozenset(excluded),
        interfaces,
    )
    findings = (
        *audit_physical_connections(members, interfaces),
        *_required_physics_findings(resource_id, members, interfaces),
        *_geometric_physics_findings(
            resource_id,
            package.artifacts,
            supplements,
            members,
            interfaces,
        ),
    )
    if findings:
        raise ValueError(
            "physical building audit failed: "
            + ", ".join(f"{row.member_role}:{row.finding_id}" for row in findings)
        )
    bounds = _combined_bounds((*package.artifacts, *supplements))
    opening_count = sum(
        len(_sequence(artifact.normalized_input.get("openings", ()), "openings"))
        for artifact in package.artifacts
    )
    identity = {
        "schema_version": "phase18.solver_blast.physical_building@1",
        "resource_id": resource_id,
        "package_fingerprint": package.package_fingerprint,
        "supplement_fingerprints": [row.fingerprint for row in supplements],
        "excluded_base_part_roles": list(excluded),
        "interfaces": [
            {
                "interface_id": row.interface_id,
                "connection_type": row.connection_type,
                "source_roles": list(row.source_roles),
                "target_roles": list(row.target_roles),
                "evidence_kind": row.evidence_kind,
                "shared_node_count": row.shared_node_count,
                "positive_contact_area_m2": row.positive_contact_area_m2,
                "positive_contact_length_m": row.positive_contact_length_m,
                "maximum_gap_m": row.maximum_gap_m,
                "connection_tolerance_m": row.connection_tolerance_m,
                "source_element_count": row.source_element_count,
                "target_element_count": row.target_element_count,
            }
            for row in interfaces
        ],
        "members": [
            {
                "role": row.role,
                "family": row.element_family,
                "material_role": row.material_role,
                "dimensions_m": list(row.dimensions_m),
                "selection_basis": row.selection_basis,
                "connection_ids": list(row.connection_ids),
                "fluid_exposed": row.fluid_exposed,
                "orientation_vector": (
                    list(row.orientation_vector) if row.orientation_vector is not None else None
                ),
            }
            for row in members
        ],
        "grade_elevation_m": grade,
        "bounds_m": list(bounds),
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    ).hexdigest()
    return PhysicalBuildingModel(
        resource_id=resource_id,
        package_fingerprint=package.package_fingerprint,
        artifacts=tuple(package.artifacts),
        supplement_fragments=supplements,
        excluded_base_part_roles=excluded,
        interfaces=interfaces,
        members=members,
        load_path=load_path,
        bounds_m=bounds,
        grade_elevation_m=grade,
        declared_opening_count=opening_count,
        unplanned_exterior_gap_intervals_m=gaps,
        fingerprint=fingerprint,
    )


def _required_physics_findings(
    resource_id: str,
    members: Sequence[PhysicalMemberRecord],
    interfaces: Sequence[PhysicalInterfaceRecord],
) -> tuple[AuditFinding, ...]:
    families = {row.role: row.element_family for row in members}
    embedded = {
        (row.source_roles, row.target_roles)
        for row in interfaces
        if row.connection_type == "embedded_beam_in_solid"
    }
    findings: list[AuditFinding] = []
    if resource_id == COMMERCIAL_ID:
        required = {
            "commercial_rc_column": "Solid",
            "commercial_column_longitudinal_rebar": "Beam",
            "commercial_column_stirrup": "Beam",
            "opaque_facade": "Solid",
            "commercial_wall_vertical_rebar": "Beam",
            "commercial_wall_horizontal_rebar": "Beam",
        }
        for role, family in required.items():
            if families.get(role) != family:
                findings.append(
                    AuditFinding(
                        "commercial_required_physics_missing",
                        role,
                        f"commercial solver view requires {role} as {family}",
                    )
                )
        for source, target in (
            ("commercial_column_longitudinal_rebar", "commercial_rc_column"),
            ("commercial_column_stirrup", "commercial_rc_column"),
            ("commercial_wall_vertical_rebar", "opaque_facade"),
            ("commercial_wall_horizontal_rebar", "opaque_facade"),
        ):
            if ((source,), (target,)) not in embedded:
                findings.append(
                    AuditFinding(
                        "commercial_embedded_rebar_missing",
                        source,
                        f"{source} must be embedded in {target}",
                    )
                )
        for role in ("steel_column", "steel_opening_jamb", "steel_opening_header"):
            if role in families:
                findings.append(
                    AuditFinding(
                        "commercial_duplicate_vertical_system",
                        role,
                        "legacy steel vertical member duplicates the solver RC column system",
                    )
                )
    if resource_id == SUBWAY_ID:
        for role, family in (
            ("rc_box_wall", "Solid"),
            ("pavilion_opaque_solid_roof", "Solid"),
            ("pavilion_glazing", "Shell"),
            ("pavilion_frame", "Beam"),
        ):
            if families.get(role) != family:
                findings.append(
                    AuditFinding(
                        "subway_required_physics_missing",
                        role,
                        f"subway solver view requires {role} as {family}",
                    )
                )
        if "pavilion_metal_roof" in families:
            findings.append(
                AuditFinding(
                    "subway_duplicate_roof_family",
                    "pavilion_metal_roof",
                    "thin roof shell must be replaced by the solver solid opaque roof",
                )
            )
        if not any(
            row.connection_type == "tied_solid_nodes_to_frame"
            and row.source_roles == ("pavilion_opaque_solid_roof",)
            and row.target_roles == ("pavilion_frame",)
            for row in interfaces
        ):
            findings.append(
                AuditFinding(
                    "subway_roof_frame_connection_missing",
                    "pavilion_opaque_solid_roof",
                    "solid pavilion roof must be tied to the pavilion frame",
                )
            )
    return tuple(findings)


def _geometric_physics_findings(
    resource_id: str,
    artifacts: Sequence[BuildingArtifact],
    supplements: Sequence[MeshFragment],
    members: Sequence[PhysicalMemberRecord],
    interfaces: Sequence[PhysicalInterfaceRecord],
) -> tuple[AuditFinding, ...]:
    findings: list[AuditFinding] = []
    if resource_id == COMMERCIAL_ID:
        for source, target in (
            ("commercial_column_longitudinal_rebar", "commercial_rc_column"),
            ("commercial_column_stirrup", "commercial_rc_column"),
            ("commercial_wall_vertical_rebar", "opaque_facade"),
            ("commercial_wall_horizontal_rebar", "opaque_facade"),
        ):
            boxes = _solid_element_boxes(supplements, target)
            segments = _beam_element_segments(supplements, source)
            if not boxes or not segments or any(
                not _segment_contained_in_boxes(start, end, boxes)
                for start, end in segments
            ):
                findings.append(
                    AuditFinding(
                        "commercial_rebar_not_contained",
                        source,
                        f"{source} must remain wholly inside {target}",
                    )
                )
        openings = tuple(
            box for artifact in artifacts for box in _external_opening_boxes(artifact)
        )
        if any(
            _boxes_overlap_with_volume(column, opening)
            for column in _solid_element_boxes(supplements, "commercial_rc_column")
            for opening in openings
        ):
            findings.append(
                AuditFinding(
                    "commercial_column_intrudes_opening",
                    "commercial_rc_column",
                    "commercial RC column volume must remain outside declared openings",
                )
            )
        if not _closed_stirrup_topology(supplements):
            findings.append(
                AuditFinding(
                    "commercial_column_stirrup_not_closed",
                    "commercial_column_stirrup",
                    "every commercial column stirrup must form one closed four-edge loop",
                )
            )
    if resource_id == SUBWAY_ID:
        roof = next(
            (
                fragment
                for fragment in supplements
                if any(
                    element.part_role == "pavilion_opaque_solid_roof"
                    for element in fragment.solids
                )
            ),
            None,
        )
        if roof is None:
            findings.append(
                AuditFinding(
                    "subway_solid_roof_missing",
                    "pavilion_opaque_solid_roof",
                    "subway pavilion requires a Solid opaque roof",
                )
            )
        else:
            node_coordinates = {node.node_id: node.coordinates for node in roof.nodes}
            if any(
                min(hexa_gauss_jacobians(node_coordinates, element.node_ids)) <= 0.0
                for element in roof.solids
            ):
                findings.append(
                    AuditFinding(
                        "subway_solid_roof_invalid_jacobian",
                        "pavilion_opaque_solid_roof",
                        "subway Solid roof must have positive Gauss-point Jacobians",
                    )
                )
            roof_tie = next(
                (
                    row
                    for row in interfaces
                    if row.connection_type == "tied_solid_nodes_to_frame"
                    and row.source_roles == ("pavilion_opaque_solid_roof",)
                    and row.target_roles == ("pavilion_frame",)
                ),
                None,
            )
            frame_section = next(
                (
                    max(member.dimensions_m[1:])
                    for member in members
                    if member.role == "pavilion_frame"
                ),
                0.0,
            )
            if roof_tie is None or not _roof_frame_interface_matches_geometry(
                artifacts,
                roof,
                roof_tie,
                frame_section,
            ):
                findings.append(
                    AuditFinding(
                        "subway_roof_frame_geometry_not_closed",
                        "pavilion_opaque_solid_roof",
                        "solid roof-to-frame interface must match actual node-to-beam geometry",
                    )
                )
    return tuple(findings)


def _closed_stirrup_topology(fragments: Sequence[MeshFragment]) -> bool:
    segments = _beam_element_segments(fragments, "commercial_column_stirrup")
    if not segments:
        return False
    adjacency: dict[tuple[float, float, float], set[tuple[float, float, float]]] = {}
    for start, end in segments:
        left = tuple(round(value, 10) for value in start)
        right = tuple(round(value, 10) for value in end)
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)
    if any(len(neighbours) != 2 for neighbours in adjacency.values()):
        return False
    remaining = set(adjacency)
    while remaining:
        seed = next(iter(remaining))
        component = {seed}
        frontier = [seed]
        while frontier:
            current = frontier.pop()
            for neighbour in adjacency[current]:
                if neighbour not in component:
                    component.add(neighbour)
                    frontier.append(neighbour)
        if len(component) != 4:
            return False
        edge_count = sum(len(adjacency[node]) for node in component) // 2
        if edge_count != 4:
            return False
        remaining.difference_update(component)
    return True


def _roof_frame_interface_matches_geometry(
    artifacts: Sequence[BuildingArtifact],
    roof: MeshFragment,
    interface: PhysicalInterfaceRecord,
    frame_section: float,
) -> bool:
    roof_nodes = {node.node_id: node.coordinates for node in roof.nodes}
    roof_node_ids = {
        node_id
        for element in roof.solids
        if element.part_role == "pavilion_opaque_solid_roof"
        for node_id in element.node_ids
    }
    thickness_rows = tuple(
        math.dist(roof_nodes[element.node_ids[index]], roof_nodes[element.node_ids[index + 4]])
        for element in roof.solids
        if element.part_role == "pavilion_opaque_solid_roof"
        for index in range(4)
    )
    if not roof_node_ids or not thickness_rows or frame_section <= 0.0:
        return False
    frame_segments: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    for artifact in artifacts:
        nodes = {node.node_id: node.coordinates for node in artifact.mesh.nodes}
        frame_segments.extend(
            (nodes[element.node_ids[0]], nodes[element.node_ids[1]])
            for element in artifact.mesh.beams
            if element.part_role == "pavilion_frame"
        )
    if not frame_segments:
        return False
    tolerance = (max(thickness_rows) + frame_section) / 2.0 + 1.0e-9
    coordinates = tuple(roof_nodes[node_id] for node_id in sorted(roof_node_ids))
    matched = {
        index
        for index, segment in enumerate(frame_segments)
        if any(_point_segment_distance(point, *segment) <= tolerance for point in coordinates)
    }
    eligible_gaps = tuple(
        gap
        for point in coordinates
        for gap in (
            min(_point_segment_distance(point, *segment) for segment in frame_segments),
        )
        if gap <= tolerance
    )
    if not matched or not eligible_gaps:
        return False
    actual_length = math.fsum(math.dist(*frame_segments[index]) for index in matched)
    actual_gap = max(eligible_gaps)
    return (
        math.isclose(
            interface.connection_tolerance_m,
            tolerance,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        )
        and math.isclose(
            interface.positive_contact_length_m,
            actual_length,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        )
        and math.isclose(
            interface.maximum_gap_m,
            actual_gap,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        )
    )


def _commercial_opaque_facade(
    package: DetailedBuildingPackage,
    column_boxes: Sequence[AxisAlignedBox] = (),
) -> MeshFragment:
    geometry = _legacy_geometry(package)
    length = _positive(geometry["length_m"], "length_m")
    width = _positive(geometry["width_m"], "width_m")
    height = _positive(geometry["height_m"], "height_m")
    wall = _positive(geometry["wall_thickness_m"], "wall_thickness_m")
    if not package.artifacts:
        raise ValueError("commercial package has no artifact")
    artifact = package.artifacts[0]
    openings = (*_external_opening_boxes(artifact), *column_boxes)
    target = wall / 2.0
    fragments = (
        mesh_axis_aligned_block_excluding(
            _rounded_box((0.0, 0.0, wall, length, wall, height - wall)),
            target,
            "opaque_facade",
            openings,
        ),
        mesh_axis_aligned_block_excluding(
            _rounded_box((0.0, width - wall, wall, length, width, height - wall)),
            target,
            "opaque_facade",
            openings,
        ),
        mesh_axis_aligned_block_excluding(
            _rounded_box((0.0, wall, wall, wall, width - wall, height - wall)),
            target,
            "opaque_facade",
            openings,
        ),
        mesh_axis_aligned_block_excluding(
            _rounded_box((length - wall, wall, wall, length, width - wall, height - wall)),
            target,
            "opaque_facade",
            openings,
        ),
    )
    return merge_fragments_welded(fragments)


def _commercial_column_boxes(
    package: DetailedBuildingPackage,
) -> tuple[AxisAlignedBox, ...]:
    artifact = package.artifacts[0]
    nodes = {node.node_id: node for node in artifact.mesh.nodes}
    axes: set[tuple[str, float, float]] = set()
    for element in artifact.mesh.beams:
        if element.part_role not in {"steel_column", "steel_opening_jamb"}:
            continue
        left, right = (nodes[node_id] for node_id in element.node_ids)
        if (
            abs(left.x - right.x) <= 1.0e-12
            and abs(left.y - right.y) <= 1.0e-12
            and abs(left.z - right.z) > 1.0e-12
        ):
            axes.add((element.part_role, left.x, left.y))
    if not axes:
        raise ValueError("commercial structural column axes are missing")
    foundation_nodes = _role_nodes(artifact, "hybrid_foundation")
    slab_nodes = _role_nodes(artifact, "hybrid_slab")
    geometry = _legacy_geometry(package)
    length = _positive(geometry["length_m"], "length_m")
    width = _positive(geometry["width_m"], "width_m")
    section = _beam_section_size(package, "steel_column")
    openings = _external_opening_boxes(artifact)
    z_min = max(node.z for node in foundation_nodes)
    z_max = min(node.z for node in slab_nodes)
    if z_max <= z_min:
        raise ValueError("commercial column clear height is not positive")
    boxes: list[AxisAlignedBox] = []
    for source_role, x, y in sorted(axes):
        if source_role == "steel_column" and any(
            opening.min_x + 1.0e-10 < x < opening.max_x - 1.0e-10
            and opening.min_y - 1.0e-10 <= y <= opening.max_y + 1.0e-10
            for opening in openings
        ):
            continue
        x_min, x_max = _structural_interval(x, section, 0.0, length, 0, y, openings)
        y_min, y_max = _structural_interval(y, section, 0.0, width, 1, x, openings)
        box = AxisAlignedBox(x_min, y_min, z_min, x_max, y_max, z_max)
        if any(_boxes_overlap_with_volume(box, opening) for opening in openings):
            raise ValueError("commercial RC column intrudes into a declared exterior opening")
        boxes.append(box)
    return tuple(boxes)


def _structural_interval(
    target: float,
    size: float,
    lower: float,
    upper: float,
    axis: int,
    other_coordinate: float,
    openings: Sequence[AxisAlignedBox],
) -> tuple[float, float]:
    tolerance = 1.0e-10
    if target <= lower + tolerance:
        return (lower, lower + size)
    if target >= upper - tolerance:
        return (upper - size, upper)
    for opening in openings:
        bounds = opening.as_tuple()
        other_axis = 1 - axis
        if not (
            bounds[other_axis] - tolerance
            <= other_coordinate
            <= bounds[other_axis + 3] + tolerance
        ):
            continue
        if abs(target - bounds[axis]) <= tolerance:
            return (target - size, target)
        if abs(target - bounds[axis + 3]) <= tolerance:
            return (target, target + size)
    return (target - size / 2.0, target + size / 2.0)


def _boxes_overlap_with_volume(left: AxisAlignedBox, right: AxisAlignedBox) -> bool:
    left_bounds = left.as_tuple()
    right_bounds = right.as_tuple()
    return all(
        min(left_bounds[axis + 3], right_bounds[axis + 3])
        - max(left_bounds[axis], right_bounds[axis])
        > 1.0e-10
        for axis in range(3)
    )


def _role_nodes(artifact: BuildingArtifact, role: str) -> tuple[Node, ...]:
    node_map = {node.node_id: node for node in artifact.mesh.nodes}
    node_ids = {
        node_id
        for element in (*artifact.mesh.solids, *artifact.mesh.shells, *artifact.mesh.beams)
        if element.part_role == role
        for node_id in element.node_ids
    }
    if not node_ids:
        raise ValueError(f"required physical role {role!r} has no nodes")
    return tuple(node_map[node_id] for node_id in sorted(node_ids))


def _mesh_solid_boxes(
    boxes: Sequence[AxisAlignedBox],
    role: str,
    material_role: str,
) -> MeshFragment:
    fragments = tuple(
        mesh_axis_aligned_block_excluding(
            box,
            min(box.max_x - box.min_x, box.max_y - box.min_y) / 2.0,
            role,
            (),
        )
        for box in boxes
    )
    merged = merge_fragments_welded(fragments)
    return MeshFragment(
        nodes=merged.nodes,
        solids=merged.solids,
        part_bindings=(PartBinding(role, material_role, f"{role}_solid_section"),),
    )


def _commercial_column_reinforcement(
    package: DetailedBuildingPackage,
    boxes: Sequence[AxisAlignedBox],
) -> tuple[MeshFragment, MeshFragment]:
    cover = _positive(package.generation_options.get("cover_m", 0.04), "cover_m")
    spacing = _positive(
        package.generation_options.get("rebar_spacing_m", 0.5),
        "rebar_spacing_m",
    )
    longitudinal: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    stirrups: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    for box in boxes:
        if min(box.max_x - box.min_x, box.max_y - box.min_y) <= 2.0 * cover:
            raise ValueError("commercial column has no reinforcement space after cover")
        for x in (box.min_x + cover, box.max_x - cover):
            for y in (box.min_y + cover, box.max_y - cover):
                longitudinal.append(
                    ((x, y, box.min_z + cover), (x, y, box.max_z - cover))
                )
        for z in _positions(box.min_z + cover, box.max_z - cover, spacing):
            loop = (
                (box.min_x + cover, box.min_y + cover, z),
                (box.max_x - cover, box.min_y + cover, z),
                (box.max_x - cover, box.max_y - cover, z),
                (box.min_x + cover, box.max_y - cover, z),
            )
            stirrups.extend((loop[index], loop[(index + 1) % 4]) for index in range(4))
    return (
        _beam_segments(longitudinal, "commercial_column_longitudinal_rebar"),
        _beam_segments(stirrups, "commercial_column_stirrup"),
    )


def _commercial_wall_reinforcement(
    package: DetailedBuildingPackage,
    column_boxes: Sequence[AxisAlignedBox],
) -> tuple[MeshFragment, MeshFragment]:
    geometry = _legacy_geometry(package)
    length = _positive(geometry["length_m"], "length_m")
    width = _positive(geometry["width_m"], "width_m")
    height = _positive(geometry["height_m"], "height_m")
    wall = _positive(geometry["wall_thickness_m"], "wall_thickness_m")
    cover = _positive(package.generation_options.get("cover_m", 0.04), "cover_m")
    spacing = _positive(
        package.generation_options.get("rebar_spacing_m", 0.5),
        "rebar_spacing_m",
    )
    exclusions = (*_external_opening_boxes(package.artifacts[0]), *column_boxes)
    vertical: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    horizontal: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    z_start, z_end = wall + cover, height - wall - cover
    for plane_y in (wall / 2.0, width - wall / 2.0):
        for x in _positions(cover, length - cover, spacing):
            for start, end in _subtract_intervals(
                z_start,
                z_end,
                tuple((box.min_z, box.max_z) for box in exclusions if _inside(x, box.min_x, box.max_x) and _inside(plane_y, box.min_y, box.max_y)),
            ):
                vertical.append(((x, plane_y, start), (x, plane_y, end)))
        for z in _positions(z_start, z_end, spacing):
            for start, end in _subtract_intervals(
                cover,
                length - cover,
                tuple((box.min_x, box.max_x) for box in exclusions if _inside(z, box.min_z, box.max_z) and _inside(plane_y, box.min_y, box.max_y)),
            ):
                horizontal.append(((start, plane_y, z), (end, plane_y, z)))
    for plane_x in (wall / 2.0, length - wall / 2.0):
        for y in _positions(wall + cover, width - wall - cover, spacing):
            for start, end in _subtract_intervals(
                z_start,
                z_end,
                tuple((box.min_z, box.max_z) for box in exclusions if _inside(y, box.min_y, box.max_y) and _inside(plane_x, box.min_x, box.max_x)),
            ):
                vertical.append(((plane_x, y, start), (plane_x, y, end)))
        for z in _positions(z_start, z_end, spacing):
            for start, end in _subtract_intervals(
                wall + cover,
                width - wall - cover,
                tuple((box.min_y, box.max_y) for box in exclusions if _inside(z, box.min_z, box.max_z) and _inside(plane_x, box.min_x, box.max_x)),
            ):
                horizontal.append(((plane_x, start, z), (plane_x, end, z)))
    if not vertical or not horizontal:
        raise ValueError("commercial facade must contain both reinforcement directions")
    return (
        _beam_segments(vertical, "commercial_wall_vertical_rebar"),
        _beam_segments(horizontal, "commercial_wall_horizontal_rebar"),
    )


def _inside(value: float, lower: float, upper: float) -> bool:
    return lower - 1.0e-12 <= value <= upper + 1.0e-12


def _subtract_intervals(
    start: float,
    end: float,
    exclusions: Sequence[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    retained = [(start, end)]
    for raw_left, raw_right in sorted(exclusions):
        left, right = max(start, raw_left), min(end, raw_right)
        if right <= left:
            continue
        next_rows: list[tuple[float, float]] = []
        for row_start, row_end in retained:
            if right <= row_start or left >= row_end:
                next_rows.append((row_start, row_end))
                continue
            if left > row_start + 1.0e-12:
                next_rows.append((row_start, left))
            if right < row_end - 1.0e-12:
                next_rows.append((right, row_end))
        retained = next_rows
    return tuple(row for row in retained if row[1] - row[0] > 1.0e-9)


def _positions(start: float, end: float, spacing: float) -> tuple[float, ...]:
    if end <= start:
        raise ValueError("reinforcement interval must be positive")
    count = max(1, math.ceil((end - start) / spacing))
    if count > 100_000:
        raise ValueError("reinforcement position hard cap exceeded")
    step = (end - start) / count
    return tuple(start + index * step for index in range(count + 1))


def _beam_segments(
    segments: Sequence[tuple[tuple[float, float, float], tuple[float, float, float]]],
    role: str,
) -> MeshFragment:
    if not segments:
        raise ValueError(f"{role} has no physical segments")
    nodes: list[Node] = []
    beams: list[BeamElement] = []
    for index, (left, right) in enumerate(segments):
        if math.dist(left, right) <= 1.0e-12:
            raise ValueError(f"{role} contains a zero-length segment")
        left_id = 2 * index + 1
        right_id = left_id + 1
        nodes.extend((Node(left_id, *left), Node(right_id, *right)))
        beams.append(BeamElement(index + 1, (left_id, right_id), role))
    return MeshFragment(
        nodes=tuple(nodes),
        beams=tuple(beams),
        part_bindings=(PartBinding(role, "reinforcing_steel", f"{role}_beam_section"),),
    )


def _subway_opaque_solid_roof(package: DetailedBuildingPackage) -> MeshFragment:
    artifact = package.artifacts[0]
    roof_shells = tuple(
        element for element in artifact.mesh.shells if element.part_role == "pavilion_metal_roof"
    )
    if not roof_shells:
        raise ValueError("subway pavilion metal roof shell is missing")
    source_nodes = {node.node_id: node for node in artifact.mesh.nodes}
    used_ids = tuple(sorted({node_id for element in roof_shells for node_id in element.node_ids}))
    thickness = _positive(
        package.generation_options.get("pavilion_roof_thickness_m", 0.05),
        "pavilion_roof_thickness_m",
    )
    face_normals: dict[int, list[tuple[float, float, float]]] = {
        source_id: [] for source_id in used_ids
    }
    oriented_loops: list[tuple[int, int, int, int]] = []
    for shell in roof_shells:
        loop = shell.node_ids
        points = tuple(source_nodes[node_id].coordinates for node_id in loop)
        normal = _unit_cross(points[0], points[1], points[2])
        if normal[2] < 0.0:
            loop = (loop[0], loop[3], loop[2], loop[1])
            points = tuple(source_nodes[node_id].coordinates for node_id in loop)
            normal = _unit_cross(points[0], points[1], points[2])
        oriented_loops.append(loop)
        for node_id in loop:
            face_normals[node_id].append(normal)
    vertex_normals = {
        node_id: _unit_vector(
            tuple(math.fsum(row[axis] for row in rows) for axis in range(3))
        )
        for node_id, rows in face_normals.items()
    }
    support_node_ids = {
        node_id
        for element in artifact.mesh.solids
        if element.part_role == "rc_box_roof"
        for node_id in element.node_ids
    }
    if not support_node_ids:
        raise ValueError("subway RC box roof support is missing")
    support_top_z = max(source_nodes[node_id].z for node_id in support_node_ids)
    source_min_z = min(source_nodes[node_id].z for node_id in used_ids)
    support_clearance_z = max(0.0, support_top_z - source_min_z)
    bottom_ids = {source_id: index + 1 for index, source_id in enumerate(used_ids)}
    top_ids = {source_id: len(used_ids) + index + 1 for index, source_id in enumerate(used_ids)}
    nodes = tuple(
        Node(
            bottom_ids[source_id],
            *(
                source_nodes[source_id].coordinates[axis]
                + (support_clearance_z if axis == 2 else 0.0)
                for axis in range(3)
            ),
        )
        for source_id in used_ids
    ) + tuple(
        Node(
            top_ids[source_id],
            *(
                source_nodes[source_id].coordinates[axis]
                + (support_clearance_z if axis == 2 else 0.0)
                + thickness * vertex_normals[source_id][axis]
                for axis in range(3)
            ),
        )
        for source_id in used_ids
    )
    solids: list[SolidElement] = []
    for index, loop in enumerate(oriented_loops):
        solids.append(
            SolidElement(
                index + 1,
                tuple(bottom_ids[node_id] for node_id in loop)
                + tuple(top_ids[node_id] for node_id in loop),
                "pavilion_opaque_solid_roof",
            )
        )
    return MeshFragment(
        nodes=nodes,
        solids=tuple(solids),
        part_bindings=(
            PartBinding(
                "pavilion_opaque_solid_roof",
                "metal_roof",
                "pavilion_opaque_solid_roof_solid_section",
            ),
        ),
    )


def _unit_cross(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    third: tuple[float, float, float],
) -> tuple[float, float, float]:
    left = tuple(second[index] - first[index] for index in range(3))
    right = tuple(third[index] - first[index] for index in range(3))
    return _unit_vector(
        (
            left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0],
        )
    )


def _unit_vector(value: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(math.fsum(component * component for component in value))
    if length <= 1.0e-12:
        raise ValueError("roof surface contains a degenerate normal")
    return tuple(component / length for component in value)  # type: ignore[return-value]


def _residential_opaque_facade(
    package: DetailedBuildingPackage,
    artifact: BuildingArtifact,
    frame_exclusions: Sequence[AxisAlignedBox] = (),
) -> MeshFragment:
    geometry = _legacy_geometry(package)
    wall = _positive(geometry["wall_thickness_m"], "wall_thickness_m")
    envelope = _mapping(artifact.normalized_input["envelope"], "envelope")
    origin = _vector3(envelope["origin_m"], "envelope.origin_m")
    size = _vector3(envelope["size_m"], "envelope.size_m")
    x0, y0, z0 = origin
    length, width, _ = size
    levels = _sequence(artifact.normalized_input["levels"], "levels")
    openings = _external_opening_boxes(artifact)
    target = wall / 2.0
    fragments: list[MeshFragment] = []
    for level_index, raw_level in enumerate(levels):
        level = _mapping(raw_level, f"levels[{level_index}]")
        base = _finite(level["elevation_m"], "level.elevation_m")
        top = base + _positive(level["height_m"], "level.height_m")
        wall_min_z = base + wall if level_index == 0 else base
        wall_max_z = top - wall
        if wall_max_z <= wall_min_z:
            raise ValueError("residential level leaves no physical facade height")
        level_openings = tuple(
            box
            for box in openings
            if box.max_z > wall_min_z and box.min_z < wall_max_z
        )
        level_frame = tuple(
            box
            for box in frame_exclusions
            if box.max_z > wall_min_z and box.min_z < wall_max_z
        )
        exclusions = (*level_openings, *level_frame)
        fragments.extend(
            (
                mesh_axis_aligned_block_excluding(
                    _rounded_box((x0, y0, wall_min_z, x0 + length, y0 + wall, wall_max_z)),
                    target,
                    "opaque_facade",
                    exclusions,
                ),
                mesh_axis_aligned_block_excluding(
                    _rounded_box((
                        x0,
                        y0 + width - wall,
                        wall_min_z,
                        x0 + length,
                        y0 + width,
                        wall_max_z,
                    )),
                    target,
                    "opaque_facade",
                    level_frame,
                ),
                mesh_axis_aligned_block_excluding(
                    _rounded_box((
                        x0,
                        y0 + wall,
                        wall_min_z,
                        x0 + wall,
                        y0 + width - wall,
                        wall_max_z,
                    )),
                    target,
                    "opaque_facade",
                    level_frame,
                ),
                mesh_axis_aligned_block_excluding(
                    _rounded_box((
                        x0 + length - wall,
                        y0 + wall,
                        wall_min_z,
                        x0 + length,
                        y0 + width - wall,
                        wall_max_z,
                    )),
                    target,
                    "opaque_facade",
                    level_frame,
                ),
            )
        )
    return merge_fragments_welded(fragments)


def _residential_frame_exclusions(
    artifact: BuildingArtifact,
) -> tuple[AxisAlignedBox, ...]:
    coalesced = tuple(
        box
        for role, axis in (
            ("rc_beam_x", 0),
            ("rc_beam_y", 1),
            ("rc_column", 2),
        )
        for box in _coalesced_solid_role_boxes(artifact, role, axis)
    )
    shear_walls = _solid_element_boxes((artifact.mesh,), "rc_shear_wall")
    return tuple(sorted((*coalesced, *shear_walls), key=lambda row: row.as_tuple()))


def _coalesced_solid_role_boxes(
    artifact: BuildingArtifact,
    role: str,
    merge_axis: int,
) -> tuple[AxisAlignedBox, ...]:
    nodes = {node.node_id: node for node in artifact.mesh.nodes}
    transverse_axes = tuple(axis for axis in range(3) if axis != merge_axis)
    grouped: dict[
        tuple[float, float, float, float],
        list[tuple[float, float]],
    ] = {}
    for element in artifact.mesh.solids:
        if element.part_role != role:
            continue
        points = tuple(nodes[node_id] for node_id in element.node_ids)
        bounds = (
            min(node.x for node in points),
            min(node.y for node in points),
            min(node.z for node in points),
            max(node.x for node in points),
            max(node.y for node in points),
            max(node.z for node in points),
        )
        key = tuple(
            round(bounds[axis + offset], 12)
            for axis in transverse_axes
            for offset in (0, 3)
        )
        grouped.setdefault(key, []).append(
            (
                round(bounds[merge_axis], 12),
                round(bounds[merge_axis + 3], 12),
            )
        )
    result: list[AxisAlignedBox] = []
    for key, intervals in grouped.items():
        merged: list[list[float]] = []
        for lower, upper in sorted(intervals):
            if not merged or lower > merged[-1][1] + 1.0e-12:
                merged.append([lower, upper])
            else:
                merged[-1][1] = max(merged[-1][1], upper)
        transverse_bounds = {
            transverse_axes[0]: (key[0], key[1]),
            transverse_axes[1]: (key[2], key[3]),
        }
        for lower, upper in merged:
            bounds = [0.0] * 6
            bounds[merge_axis] = lower
            bounds[merge_axis + 3] = upper
            for axis, (axis_lower, axis_upper) in transverse_bounds.items():
                bounds[axis] = axis_lower
                bounds[axis + 3] = axis_upper
            result.append(AxisAlignedBox.from_bounds(tuple(bounds)))
    return tuple(sorted(result, key=lambda row: row.as_tuple()))


def _external_opening_boxes(artifact: BuildingArtifact) -> tuple[AxisAlignedBox, ...]:
    rows = _sequence(artifact.normalized_input.get("openings", ()), "openings")
    result: list[AxisAlignedBox] = []
    for index, raw in enumerate(rows):
        row = _mapping(raw, f"openings[{index}]")
        connects = _sequence(row.get("connects", ()), f"openings[{index}].connects")
        if "exterior" not in connects:
            continue
        bounds = tuple(round(value, 12) for value in _vector6(row["bounds_m"], "opening.bounds_m"))
        result.append(AxisAlignedBox.from_bounds(bounds))
    return tuple(result)


def _physical_interface_records(
    package: DetailedBuildingPackage,
    supplements: Sequence[MeshFragment],
    excluded: frozenset[str],
) -> tuple[PhysicalInterfaceRecord, ...]:
    records: list[PhysicalInterfaceRecord] = []
    base_role_coordinates: list[dict[str, set[tuple[float, float, float]]]] = []
    base_role_node_ids: list[dict[str, set[int]]] = []
    base_role_counts: list[dict[str, int]] = []
    base_element_roles: list[dict[int, str]] = []

    for artifact_index, artifact in enumerate(package.artifacts):
        nodes = {node.node_id: node for node in artifact.mesh.nodes}
        role_coordinates: dict[str, set[tuple[float, float, float]]] = {}
        role_node_ids: dict[str, set[int]] = {}
        role_counts: dict[str, int] = {}
        element_roles: dict[int, str] = {}
        for element in (*artifact.mesh.solids, *artifact.mesh.shells, *artifact.mesh.beams):
            role = element.part_role
            if role in excluded:
                continue
            role_counts[role] = role_counts.get(role, 0) + 1
            element_roles[element.element_id] = role
            role_node_ids.setdefault(role, set()).update(element.node_ids)
            role_coordinates.setdefault(role, set()).update(
                _coordinate_key(nodes[node_id]) for node_id in element.node_ids
            )
        base_role_coordinates.append(role_coordinates)
        base_role_node_ids.append(role_node_ids)
        base_role_counts.append(role_counts)
        base_element_roles.append(element_roles)

        roles = sorted(role_coordinates)
        for left_index, left_role in enumerate(roles):
            for right_role in roles[left_index + 1 :]:
                shared_coordinates = role_coordinates[left_role] & role_coordinates[right_role]
                if not shared_coordinates:
                    continue
                shared_ids = role_node_ids[left_role] & role_node_ids[right_role]
                records.append(
                    PhysicalInterfaceRecord(
                        interface_id=(
                            f"artifact_{artifact_index}:topology:{left_role}_to_{right_role}"
                        ),
                        connection_type=(
                            "shared_nodes" if shared_ids else "shared_node_weld_on_assembly"
                        ),
                        source_roles=(left_role,),
                        target_roles=(right_role,),
                        evidence_kind=(
                            "actual_shared_node_ids"
                            if shared_ids
                            else "actual_coincident_mesh_coordinates"
                        ),
                        shared_node_count=len(shared_ids or shared_coordinates),
                        positive_contact_area_m2=0.0,
                        positive_contact_length_m=0.0,
                        maximum_gap_m=0.0,
                        connection_tolerance_m=0.0,
                        source_element_count=role_counts[left_role],
                        target_element_count=role_counts[right_role],
                    )
                )

        for connection_index, connection in enumerate(artifact.connections):
            source_roles = tuple(
                sorted(
                    {
                        element_roles[element_id]
                        for element_id in connection.source_element_ids
                        if element_id in element_roles
                    }
                )
            )
            target_roles = tuple(
                sorted(
                    {
                        element_roles[element_id]
                        for element_id in connection.target_element_ids
                        if element_id in element_roles
                    }
                    - set(source_roles)
                )
            )
            if not source_roles or not target_roles:
                continue
            records.append(
                PhysicalInterfaceRecord(
                    interface_id=(
                        f"artifact_{artifact_index}:constraint_{connection_index}:"
                        f"{connection.connection_id}"
                    ),
                    connection_type="artifact_constraint",
                    source_roles=source_roles,
                    target_roles=target_roles,
                    evidence_kind=f"artifact_connection:{connection.connection_type}",
                    shared_node_count=0,
                    positive_contact_area_m2=0.0,
                    positive_contact_length_m=0.0,
                    maximum_gap_m=0.0,
                    connection_tolerance_m=0.0,
                    source_element_count=len(connection.source_element_ids),
                    target_element_count=len(connection.target_element_ids),
                )
            )

        glazing_tie = _pavilion_glazing_frame_interface(
            artifact,
            artifact_index,
            _beam_section_size(package, "pavilion_frame") / 2.0,
        )
        if glazing_tie is not None:
            records.append(glazing_tie)

    for supplement_index, supplement in enumerate(supplements):
        supplement_nodes = {node.node_id: node for node in supplement.nodes}
        supplement_coordinates: dict[str, set[tuple[float, float, float]]] = {}
        supplement_counts: dict[str, int] = {}
        for element in (*supplement.solids, *supplement.shells, *supplement.beams):
            role = element.part_role
            supplement_counts[role] = supplement_counts.get(role, 0) + 1
            supplement_coordinates.setdefault(role, set()).update(
                _coordinate_key(supplement_nodes[node_id]) for node_id in element.node_ids
            )
        for artifact_index, role_coordinates in enumerate(base_role_coordinates):
            for source_role in sorted(supplement_coordinates):
                for target_role in sorted(role_coordinates):
                    shared = supplement_coordinates[source_role] & role_coordinates[target_role]
                    if not shared:
                        continue
                    records.append(
                        PhysicalInterfaceRecord(
                            interface_id=(
                                f"supplement_{supplement_index}:artifact_{artifact_index}:"
                                f"{source_role}_to_{target_role}"
                            ),
                            connection_type="shared_node_weld_on_assembly",
                            source_roles=(source_role,),
                            target_roles=(target_role,),
                            evidence_kind="actual_coincident_mesh_coordinates",
                            shared_node_count=len(shared),
                            positive_contact_area_m2=0.0,
                            positive_contact_length_m=0.0,
                            maximum_gap_m=0.0,
                            connection_tolerance_m=0.0,
                            source_element_count=supplement_counts[source_role],
                            target_element_count=base_role_counts[artifact_index][target_role],
                        )
                    )

    records.extend(_supplement_embedded_interfaces(supplements))
    if package.resource_id == COMMERCIAL_ID:
        records.extend(_commercial_column_support_interfaces(package, supplements))
    if package.resource_id == SUBWAY_ID:
        records.append(_pavilion_solid_roof_frame_interface(package, supplements))
    return tuple(sorted(records, key=lambda row: row.interface_id))


def _supplement_embedded_interfaces(
    supplements: Sequence[MeshFragment],
) -> tuple[PhysicalInterfaceRecord, ...]:
    counts: dict[str, int] = {}
    families: dict[str, str] = {}
    for fragment in supplements:
        for family, elements in (
            ("Solid", fragment.solids),
            ("Shell", fragment.shells),
            ("Beam", fragment.beams),
        ):
            for element in elements:
                previous = families.setdefault(element.part_role, family)
                if previous != family:
                    raise ValueError(f"supplement role {element.part_role!r} mixes families")
                counts[element.part_role] = counts.get(element.part_role, 0) + 1
    bindings = (
        ("commercial_column_longitudinal_rebar", "commercial_rc_column"),
        ("commercial_column_stirrup", "commercial_rc_column"),
        ("commercial_wall_vertical_rebar", "opaque_facade"),
        ("commercial_wall_horizontal_rebar", "opaque_facade"),
    )
    rows: list[PhysicalInterfaceRecord] = []
    for source, target in bindings:
        if source not in counts:
            continue
        if families.get(source) != "Beam" or families.get(target) != "Solid":
            raise ValueError(f"embedded supplement {source!r} must bind Beam to Solid {target!r}")
        target_boxes = _solid_element_boxes(supplements, target)
        segments = _beam_element_segments(supplements, source)
        if not target_boxes or not segments:
            raise ValueError(f"embedded supplement {source!r} lacks source or host geometry")
        for start, end in segments:
            if not _segment_contained_in_boxes(start, end, target_boxes):
                raise ValueError(
                    f"embedded supplement {source!r} leaves Solid host {target!r}"
                )
        rows.append(
            PhysicalInterfaceRecord(
                interface_id=f"supplement:embedded:{source}_to_{target}",
                connection_type="embedded_beam_in_solid",
                source_roles=(source,),
                target_roles=(target,),
                evidence_kind="actual_segment_containment_in_solid_mesh",
                shared_node_count=0,
                positive_contact_area_m2=0.0,
                positive_contact_length_m=math.fsum(
                    math.dist(start, end) for start, end in segments
                ),
                maximum_gap_m=0.0,
                connection_tolerance_m=0.0,
                source_element_count=counts[source],
                target_element_count=counts[target],
            )
        )
    return tuple(rows)


def _solid_element_boxes(
    fragments: Sequence[MeshFragment],
    role: str,
) -> tuple[AxisAlignedBox, ...]:
    rows: list[AxisAlignedBox] = []
    for fragment in fragments:
        nodes = {node.node_id: node for node in fragment.nodes}
        for element in fragment.solids:
            if element.part_role != role:
                continue
            points = tuple(nodes[node_id] for node_id in element.node_ids)
            rows.append(
                AxisAlignedBox(
                    min(node.x for node in points),
                    min(node.y for node in points),
                    min(node.z for node in points),
                    max(node.x for node in points),
                    max(node.y for node in points),
                    max(node.z for node in points),
                )
            )
    return tuple(rows)


def _beam_element_segments(
    fragments: Sequence[MeshFragment],
    role: str,
) -> tuple[tuple[tuple[float, float, float], tuple[float, float, float]], ...]:
    rows = []
    for fragment in fragments:
        nodes = {node.node_id: node for node in fragment.nodes}
        rows.extend(
            (nodes[element.node_ids[0]].coordinates, nodes[element.node_ids[1]].coordinates)
            for element in fragment.beams
            if element.part_role == role
        )
    return tuple(rows)


def _segment_contained_in_boxes(
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    boxes: Sequence[AxisAlignedBox],
) -> bool:
    varying = tuple(
        axis for axis in range(3) if abs(end[axis] - start[axis]) > 1.0e-12
    )
    if len(varying) != 1:
        return False
    axis = varying[0]
    fixed_axes = tuple(index for index in range(3) if index != axis)
    segment_min, segment_max = sorted((start[axis], end[axis]))
    intervals: list[tuple[float, float]] = []
    for box in boxes:
        bounds = box.as_tuple()
        if not all(
            bounds[index] - 1.0e-10
            <= start[index]
            <= bounds[index + 3] + 1.0e-10
            for index in fixed_axes
        ):
            continue
        left = max(segment_min, bounds[axis])
        right = min(segment_max, bounds[axis + 3])
        if right >= left - 1.0e-10:
            intervals.append((left, right))
    if not intervals:
        return False
    merged_end = segment_min
    for left, right in sorted(intervals):
        if left > merged_end + 1.0e-10:
            return False
        merged_end = max(merged_end, right)
        if merged_end >= segment_max - 1.0e-10:
            return True
    return False


def _commercial_column_support_interfaces(
    package: DetailedBuildingPackage,
    supplements: Sequence[MeshFragment],
) -> tuple[PhysicalInterfaceRecord, ...]:
    columns = _solid_element_boxes(supplements, "commercial_rc_column")
    if not columns:
        raise ValueError("commercial RC columns are missing support geometry")
    column_area = math.fsum(
        (box.max_x - box.min_x) * (box.max_y - box.min_y)
        for box in _commercial_column_boxes(package)
    )
    target_counts = {
        role: sum(
            element.part_role == role
            for artifact in package.artifacts
            for element in artifact.mesh.solids
        )
        for role in ("hybrid_foundation", "hybrid_slab")
    }
    source_count = sum(
        element.part_role == "commercial_rc_column"
        for fragment in supplements
        for element in fragment.solids
    )
    return tuple(
        PhysicalInterfaceRecord(
            interface_id=f"supplement:tied:commercial_rc_column_to_{role}",
            connection_type="tied_solid_face_to_solid_surface",
            source_roles=("commercial_rc_column",),
            target_roles=(role,),
            evidence_kind="actual_column_end_face_on_support_surface",
            shared_node_count=0,
            positive_contact_area_m2=column_area,
            positive_contact_length_m=0.0,
            maximum_gap_m=0.0,
            connection_tolerance_m=1.0e-9,
            source_element_count=source_count,
            target_element_count=target_counts[role],
        )
        for role in ("hybrid_foundation", "hybrid_slab")
    )


def _pavilion_solid_roof_frame_interface(
    package: DetailedBuildingPackage,
    supplements: Sequence[MeshFragment],
) -> PhysicalInterfaceRecord:
    roof_nodes = {
        node_id
        for fragment in supplements
        for element in fragment.solids
        if element.part_role == "pavilion_opaque_solid_roof"
        for node_id in element.node_ids
    }
    roof_coordinates = tuple(
        node.coordinates
        for fragment in supplements
        for node in fragment.nodes
        if node.node_id in roof_nodes
    )
    frame_segments: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    frame_count = 0
    for artifact in package.artifacts:
        nodes = {node.node_id: node for node in artifact.mesh.nodes}
        for element in artifact.mesh.beams:
            if element.part_role != "pavilion_frame":
                continue
            frame_count += 1
            frame_segments.append(
                (nodes[element.node_ids[0]].coordinates, nodes[element.node_ids[1]].coordinates)
            )
    if not roof_coordinates or not frame_segments:
        raise ValueError("subway solid roof and pavilion frame must both exist")
    tolerance = (
        _positive(
            package.generation_options.get("pavilion_roof_thickness_m", 0.05),
            "pavilion_roof_thickness_m",
        )
        + _beam_section_size(package, "pavilion_frame")
    ) / 2.0 + 1.0e-9
    matched = {
        index
        for index, segment in enumerate(frame_segments)
        if any(_point_segment_distance(point, *segment) <= tolerance for point in roof_coordinates)
    }
    if not matched:
        raise ValueError("subway solid roof has no frame segment within connection tolerance")
    return PhysicalInterfaceRecord(
        interface_id="supplement:tied:pavilion_opaque_solid_roof_to_pavilion_frame",
        connection_type="tied_solid_nodes_to_frame",
        source_roles=("pavilion_opaque_solid_roof",),
        target_roles=("pavilion_frame",),
        evidence_kind="actual_solid_boundary_node_to_beam_segment_distance",
        shared_node_count=0,
        positive_contact_area_m2=0.0,
        positive_contact_length_m=math.fsum(
            math.dist(*frame_segments[index]) for index in matched
        ),
        maximum_gap_m=max(
            min(_point_segment_distance(point, *segment) for segment in frame_segments)
            for point in roof_coordinates
            if min(_point_segment_distance(point, *segment) for segment in frame_segments)
            <= tolerance
        ),
        connection_tolerance_m=tolerance,
        source_element_count=sum(
            element.part_role == "pavilion_opaque_solid_roof"
            for fragment in supplements
            for element in fragment.solids
        ),
        target_element_count=frame_count,
    )


def _pavilion_glazing_frame_interface(
    artifact: BuildingArtifact,
    artifact_index: int,
    tolerance_m: float,
) -> PhysicalInterfaceRecord | None:
    glazing = tuple(
        element
        for element in artifact.mesh.shells
        if element.part_role == "pavilion_glazing"
    )
    frame = tuple(
        element
        for element in artifact.mesh.beams
        if element.part_role == "pavilion_frame"
    )
    if not glazing and not frame:
        return None
    if not glazing or not frame:
        raise ValueError("pavilion glazing and frame must both exist for physical connection")
    nodes = {node.node_id: node for node in artifact.mesh.nodes}
    edge_counts: dict[tuple[int, int], int] = {}
    for shell in glazing:
        loop = shell.node_ids
        for start, end in zip(loop, (*loop[1:], loop[0])):
            edge = tuple(sorted((start, end)))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1
    frame_segments = tuple(
        (nodes[element.node_ids[0]].coordinates, nodes[element.node_ids[1]].coordinates)
        for element in frame
    )
    connected_length = 0.0
    maximum_gap = 0.0
    for edge, count in edge_counts.items():
        if count != 1:
            continue
        start = nodes[edge[0]].coordinates
        end = nodes[edge[1]].coordinates
        start_gap = min(_point_segment_distance(start, *segment) for segment in frame_segments)
        end_gap = min(_point_segment_distance(end, *segment) for segment in frame_segments)
        edge_gap = max(start_gap, end_gap)
        if edge_gap <= tolerance_m + 1.0e-12:
            connected_length += math.dist(start, end)
            maximum_gap = max(maximum_gap, edge_gap)
    if connected_length <= 0.0:
        raise ValueError("pavilion glazing has no frame edge within connection tolerance")
    return PhysicalInterfaceRecord(
        interface_id=f"artifact_{artifact_index}:tied:pavilion_glazing_to_frame",
        connection_type="tied_shell_edge_to_frame",
        source_roles=("pavilion_glazing",),
        target_roles=("pavilion_frame",),
        evidence_kind="actual_boundary_edge_to_beam_segment_distance",
        shared_node_count=0,
        positive_contact_area_m2=0.0,
        positive_contact_length_m=connected_length,
        maximum_gap_m=maximum_gap,
        connection_tolerance_m=tolerance_m,
        source_element_count=len(glazing),
        target_element_count=len(frame),
    )


def _point_segment_distance(
    point: tuple[float, float, float],
    start: tuple[float, float, float],
    end: tuple[float, float, float],
) -> float:
    direction = tuple(end[index] - start[index] for index in range(3))
    length_squared = sum(value * value for value in direction)
    if length_squared <= 0.0:
        raise ValueError("physical frame contains a zero-length beam")
    projection = sum(
        (point[index] - start[index]) * direction[index] for index in range(3)
    ) / length_squared
    clamped = max(0.0, min(1.0, projection))
    nearest = tuple(start[index] + clamped * direction[index] for index in range(3))
    return math.dist(point, nearest)


def _physical_member_records(
    package: DetailedBuildingPackage,
    supplements: Sequence[MeshFragment],
    excluded: frozenset[str],
    interfaces: Sequence[PhysicalInterfaceRecord],
) -> tuple[PhysicalMemberRecord, ...]:
    roles: dict[str, tuple[str, list[Node], float]] = {}
    for artifact in package.artifacts:
        nodes = {node.node_id: node for node in artifact.mesh.nodes}
        for family, elements in (
            ("Solid", artifact.mesh.solids),
            ("Shell", artifact.mesh.shells),
            ("Beam", artifact.mesh.beams),
        ):
            for element in elements:
                if element.part_role in excluded:
                    continue
                record = roles.setdefault(element.part_role, (family, [], 0.0))
                if record[0] != family:
                    raise ValueError(f"part role {element.part_role!r} mixes element families")
                role_nodes = record[1]
                role_nodes.extend(nodes[node_id] for node_id in element.node_ids)
                length = record[2]
                if family == "Beam":
                    left, right = (nodes[node_id] for node_id in element.node_ids)
                    length = max(length, math.dist(left.coordinates, right.coordinates))
                    roles[element.part_role] = (family, role_nodes, length)
    for fragment in supplements:
        nodes = {node.node_id: node for node in fragment.nodes}
        for family, elements in (
            ("Solid", fragment.solids),
            ("Shell", fragment.shells),
            ("Beam", fragment.beams),
        ):
            for element in elements:
                record = roles.setdefault(element.part_role, (family, [], 0.0))
                if record[0] != family:
                    raise ValueError(f"part role {element.part_role!r} mixes element families")
                role_nodes = record[1]
                role_nodes.extend(nodes[node_id] for node_id in element.node_ids)
                if family == "Beam":
                    left, right = (nodes[node_id] for node_id in element.node_ids)
                    roles[element.part_role] = (
                        family,
                        role_nodes,
                        max(record[2], math.dist(left.coordinates, right.coordinates)),
                    )

    records: list[PhysicalMemberRecord] = []
    for role in sorted(roles):
        family, nodes, beam_segment_length = roles[role]
        bounds = _node_bounds(nodes)
        spans = sorted(
            (bounds[index + 3] - bounds[index] for index in range(3)),
            reverse=True,
        )
        material = _material_role(package.artifacts, role)
        if role == "opaque_facade":
            wall = _positive(_legacy_geometry(package)["wall_thickness_m"], "wall_thickness_m")
            dimensions = (max(spans[0], wall), max(spans[1], wall), wall)
            basis = "solid opaque masonry/precast envelope with explicit openings"
            exposed = True
            orientation = None
        elif role == "commercial_rc_column":
            dimensions = tuple(max(value, 1.0e-9) for value in spans)
            basis = (
                "solid RC load-bearing columns with reviewed 0.30 m sections; "
                "source vertical lines on the exterior building boundary are "
                "facade datum/outer-face lines shifted inward by one section, "
                "while interior and opening-jamb lines preserve their centerline"
            )
            exposed = _solid_role_is_exposed(role)
            orientation = None
        elif family == "Solid":
            dimensions = tuple(max(value, 1.0e-9) for value in spans)
            basis = "three-dimensional structural or circulation volume"
            exposed = _solid_role_is_exposed(role)
            orientation = None
        elif family == "Shell":
            thickness = _shell_thickness(package, role)
            dimensions = (max(spans[0], thickness), max(spans[1], thickness), thickness)
            basis = "thin physical component with reviewed shell thickness"
            exposed = role not in {"nonstructural_partition"}
            orientation = None
        else:
            section = _beam_section_size(package, role)
            length = max(spans[0], beam_segment_length, section * 2.0)
            dimensions = (length, section, section)
            basis = "slender physical member with reviewed section and orientation"
            if length / section < 10.0:
                basis += "; reviewed non-slender beam exception"
            exposed = role in {
                "steel_column",
                "steel_beam",
                "steel_opening_jamb",
                "steel_opening_header",
                "pavilion_frame",
            }
            orientation = (1.0, 1.0, 1.0)
        if role in _INTERNAL_NON_FLUID_ROLES:
            exposed = False
        connection_ids = tuple(
            row.interface_id
            for row in interfaces
            if role in (*row.source_roles, *row.target_roles)
        )
        if not connection_ids:
            raise ValueError(f"physical role {role!r} has no measured connection interface")
        records.append(
            PhysicalMemberRecord(
                role=role,
                element_family=family,
                material_role=material,
                dimensions_m=(float(dimensions[0]), float(dimensions[1]), float(dimensions[2])),
                selection_basis=basis,
                connection_ids=connection_ids,
                fluid_exposed=exposed,
                orientation_vector=orientation,
            )
        )
    return tuple(records)


def _load_path(
    package: DetailedBuildingPackage,
    foundation_candidates: Sequence[str],
    vertical_candidates: Sequence[str],
    floor_candidates: Sequence[str],
    supplements: Sequence[MeshFragment] = (),
) -> LoadPathEvidence:
    roles = {
        element.part_role
        for artifact in package.artifacts
        for element in (*artifact.mesh.solids, *artifact.mesh.shells, *artifact.mesh.beams)
    }
    roles.update(
        element.part_role
        for fragment in supplements
        for element in (*fragment.solids, *fragment.shells, *fragment.beams)
    )
    foundation = tuple(role for role in foundation_candidates if role in roles)
    vertical = tuple(role for role in vertical_candidates if role in roles)
    floor = tuple(role for role in floor_candidates if role in roles)
    return LoadPathEvidence(
        foundation_roles=foundation,
        vertical_roles=vertical,
        floor_or_roof_roles=floor,
        continuous=bool(foundation and vertical and floor),
    )


def _combined_bounds(
    rows: Iterable[BuildingArtifact | MeshFragment],
) -> tuple[float, float, float, float, float, float]:
    bounds = [row.mesh.bounds_m if isinstance(row, BuildingArtifact) else row.bounds_m for row in rows]
    return (
        min(row[0] for row in bounds),
        min(row[1] for row in bounds),
        min(row[2] for row in bounds),
        max(row[3] for row in bounds),
        max(row[4] for row in bounds),
        max(row[5] for row in bounds),
    )


def _node_bounds(nodes: Sequence[Node]) -> tuple[float, float, float, float, float, float]:
    if not nodes:
        raise ValueError("physical role has no nodes")
    return (
        min(row.x for row in nodes),
        min(row.y for row in nodes),
        min(row.z for row in nodes),
        max(row.x for row in nodes),
        max(row.y for row in nodes),
        max(row.z for row in nodes),
    )


def _coordinate_key(node: Node) -> tuple[float, float, float]:
    return tuple(round(value, 12) for value in node.coordinates)  # type: ignore[return-value]


def _material_role(artifacts: Sequence[BuildingArtifact], role: str) -> str:
    values = {
        binding.material_role
        for artifact in artifacts
        for binding in artifact.mesh.part_bindings
        if binding.part_role == role
    }
    if role == "opaque_facade":
        return "facade_masonry"
    if role == "commercial_rc_column":
        return "concrete"
    if role in {
        "commercial_column_longitudinal_rebar",
        "commercial_column_stirrup",
        "commercial_wall_vertical_rebar",
        "commercial_wall_horizontal_rebar",
    }:
        return "reinforcing_steel"
    if role == "pavilion_opaque_solid_roof":
        return "metal_roof"
    if len(values) != 1:
        raise ValueError(f"role {role!r} does not have one material binding")
    return next(iter(values))


def _shell_thickness(package: DetailedBuildingPackage, role: str) -> float:
    options = package.generation_options
    explicit = {
        "pavilion_glazing": options.get("pavilion_glazing_thickness_m", 0.02),
        "pavilion_metal_roof": options.get("pavilion_roof_thickness_m", 0.05),
        "steel_roof_deck": 0.02,
        "nonstructural_partition": 0.10,
        "nonstructural_balcony_barrier": 0.02,
        "generic_signage": 0.02,
        "nonstructural_architectural_finish": 0.01,
    }
    return _positive(explicit.get(role, 0.02), f"{role}.shell_thickness")


def _beam_section_size(package: DetailedBuildingPackage, role: str) -> float:
    options = package.generation_options
    if "rebar" in role or "stirrup" in role:
        return _positive(options.get("bar_diameter_m", 0.016), f"{role}.diameter")
    if role == "pavilion_frame":
        return _positive(options.get("pavilion_frame_size_m", 0.1), "pavilion_frame_size_m")
    if "handrail" in role:
        return 0.04
    if "truss_guides" in role:
        return 0.05
    return 0.30


def _solid_role_is_exposed(role: str) -> bool:
    return role not in {
        "hybrid_foundation",
        "rc_foundation",
        "foundation_rebar",
    } | _INTERNAL_NON_FLUID_ROLES


def _legacy_geometry(package: DetailedBuildingPackage) -> Mapping[str, object]:
    return _mapping(
        package.geometry_manifest["normalized_legacy_geometry"],
        "normalized_legacy_geometry",
    )


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be a mapping")
    return value


def _sequence(value: object, path: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{path} must be a sequence")
    return value


def _finite(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{path} must be finite")
    return result


def _positive(value: object, path: str) -> float:
    result = _finite(value, path)
    if result <= 0.0:
        raise ValueError(f"{path} must be positive")
    return result


def _vector3(value: object, path: str) -> tuple[float, float, float]:
    rows = _sequence(value, path)
    if len(rows) != 3:
        raise ValueError(f"{path} must contain three numbers")
    return (_finite(rows[0], path), _finite(rows[1], path), _finite(rows[2], path))


def _vector6(value: object, path: str) -> tuple[float, float, float, float, float, float]:
    rows = _sequence(value, path)
    if len(rows) != 6:
        raise ValueError(f"{path} must contain six numbers")
    result = tuple(_finite(row, path) for row in rows)
    return (result[0], result[1], result[2], result[3], result[4], result[5])


def _rounded_box(
    bounds: tuple[float, float, float, float, float, float],
) -> AxisAlignedBox:
    return AxisAlignedBox.from_bounds(tuple(round(value, 12) for value in bounds))
