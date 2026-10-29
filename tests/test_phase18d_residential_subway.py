from __future__ import annotations

import math
import random
import tracemalloc
import unittest

from lsprepost_mcp.refined_building import compile_detailed_building_asset
from lsprepost_mcp.refined_building.asset_compiler import (
    _compile_asset_definition,
    _normalize_generation_options,
)
from lsprepost_mcp.refined_building.asset_resources import get_detailed_building_asset
from lsprepost_mcp.refined_building.asset_templates import (
    build_detailed_building_template,
    normalize_asset_geometry,
)
from lsprepost_mcp.refined_building.meshing import (
    count_axis_aligned_union_cells,
    mesh_axis_aligned_union,
)
from lsprepost_mcp.refined_building.spatial import AxisAlignedBox


RESIDENTIAL_ID = "residential_community_detailed_building"
SUBWAY_ID = "subway_entrance_detailed_building"
SMALL_RESIDENTIAL = {
    "tower_count": 2,
    "tower_length_m": 3.6,
    "tower_width_m": 3.6,
    "tower_height_m": 3.0,
    "tower_spacing_m": 0.8,
    "wall_thickness_m": 0.20,
    "balcony_depth_m": 0.60,
}
SMALL_SUBWAY = {
    "length_m": 4.0,
    "width_m": 3.0,
    "platform_height_m": 0.30,
    "enclosure_height_m": 2.40,
    "wall_thickness_m": 0.20,
    "roof_thickness_m": 0.20,
}


def compile_small_residential(**overrides: object):
    arguments: dict[str, object] = {
        "legacy_geometry": SMALL_RESIDENTIAL,
        "mesh_profile": "coarse",
        "generation_options": {"rebar_spacing_m": 0.50},
    }
    arguments.update(overrides)
    return compile_detailed_building_asset(RESIDENTIAL_ID, **arguments)


def compile_small_subway(**overrides: object):
    arguments: dict[str, object] = {
        "legacy_geometry": SMALL_SUBWAY,
        "mesh_profile": "coarse",
        "generation_options": {"rebar_spacing_m": 0.50},
    }
    arguments.update(overrides)
    return compile_detailed_building_asset(SUBWAY_ID, **arguments)


def build_small_subway_template(**option_overrides: object):
    descriptor = get_detailed_building_asset(SUBWAY_ID)
    geometry = normalize_asset_geometry(descriptor, SMALL_SUBWAY)
    options = _normalize_generation_options(
        {"rebar_spacing_m": 0.50, **option_overrides},
        "rc_box",
        SUBWAY_ID,
        geometry,
    )
    return build_detailed_building_template(
        descriptor,
        geometry,
        structural_system="rc_box",
        fidelity_profile="blast_response",
        mesh_profile="coarse",
        generation_options=options,
    )


def _beam_roles(artifact: object) -> set[str]:
    return {row.part_role for row in artifact.mesh.beams}  # type: ignore[attr-defined]


def _shell_centroid(artifact: object, shell: object) -> tuple[float, float, float]:
    nodes = {row.node_id: row.coordinates for row in artifact.mesh.nodes}  # type: ignore[attr-defined]
    return tuple(
        sum(nodes[node_id][axis] for node_id in shell.node_ids) / 4.0  # type: ignore[attr-defined]
        for axis in range(3)
    )  # type: ignore[return-value]


def _element_bounds(
    nodes: dict[int, tuple[float, float, float]], element: object
) -> tuple[float, ...]:
    points = [nodes[node_id] for node_id in element.node_ids]  # type: ignore[attr-defined]
    return tuple(min(point[axis] for point in points) for axis in range(3)) + tuple(
        max(point[axis] for point in points) for axis in range(3)
    )


def _physical_element_bounds(
    nodes: dict[int, tuple[float, float, float]],
    element: object,
    *,
    beam_size_m: float = 0.0,
    shell_thickness_m: float = 0.0,
) -> tuple[float, ...]:
    points = [nodes[node_id] for node_id in element.node_ids]  # type: ignore[attr-defined]
    bounds = _element_bounds(nodes, element)
    if beam_size_m > 0.0:
        half_size = beam_size_m / 2.0
        offsets = (half_size, half_size, half_size)
    elif shell_thickness_m > 0.0:
        edge_a = tuple(points[1][axis] - points[0][axis] for axis in range(3))
        edge_b = tuple(points[3][axis] - points[0][axis] for axis in range(3))
        normal = (
            edge_a[1] * edge_b[2] - edge_a[2] * edge_b[1],
            edge_a[2] * edge_b[0] - edge_a[0] * edge_b[2],
            edge_a[0] * edge_b[1] - edge_a[1] * edge_b[0],
        )
        magnitude = math.sqrt(sum(value * value for value in normal))
        if magnitude <= 1.0e-12:
            raise AssertionError("test oracle received a degenerate shell")
        offsets = tuple(
            abs(value) * shell_thickness_m / (2.0 * magnitude)
            for value in normal
        )
    else:
        offsets = (0.0, 0.0, 0.0)
    return tuple(bounds[axis] - offsets[axis] for axis in range(3)) + tuple(
        bounds[axis + 3] + offsets[axis] for axis in range(3)
    )


def _positive_box_overlap(left: tuple[float, ...], right: tuple[float, ...]) -> bool:
    return all(
        min(left[axis + 3], right[axis + 3])
        - max(left[axis], right[axis])
        > 1.0e-9
        for axis in range(3)
    )


_PRISM_FACES = (
    (0, 1, 2, 3),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (1, 2, 6, 5),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
)
_PRISM_EDGES = (
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 0),
    (4, 5),
    (5, 6),
    (6, 7),
    (7, 4),
    (0, 4),
    (1, 5),
    (2, 6),
    (3, 7),
)


def _vector_subtract(
    left: tuple[float, float, float], right: tuple[float, float, float]
) -> tuple[float, float, float]:
    return tuple(left[axis] - right[axis] for axis in range(3))  # type: ignore[return-value]


def _vector_cross(
    left: tuple[float, float, float], right: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _normalized_vector(
    vector: tuple[float, float, float]
) -> tuple[float, float, float] | None:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude <= 1.0e-12:
        return None
    return tuple(value / magnitude for value in vector)  # type: ignore[return-value]


def _prism_face_normals(
    vertices: tuple[tuple[float, float, float], ...]
) -> tuple[tuple[float, float, float], ...]:
    normals = []
    for face in _PRISM_FACES:
        normal = _normalized_vector(
            _vector_cross(
                _vector_subtract(vertices[face[1]], vertices[face[0]]),
                _vector_subtract(vertices[face[3]], vertices[face[0]]),
            )
        )
        if normal is not None:
            normals.append(normal)
    return tuple(normals)


def _prism_edge_directions(
    vertices: tuple[tuple[float, float, float], ...]
) -> tuple[tuple[float, float, float], ...]:
    return tuple(
        direction
        for start, end in _PRISM_EDGES
        if (
            direction := _normalized_vector(
                _vector_subtract(vertices[end], vertices[start])
            )
        )
        is not None
    )


def _positive_prism_overlap(
    left: tuple[tuple[float, float, float], ...],
    right: tuple[tuple[float, float, float], ...],
) -> bool:
    left_edges = _prism_edge_directions(left)
    right_edges = _prism_edge_directions(right)
    axes = [*_prism_face_normals(left), *_prism_face_normals(right)]
    axes.extend(
        axis
        for left_edge in left_edges
        for right_edge in right_edges
        if (axis := _normalized_vector(_vector_cross(left_edge, right_edge)))
        is not None
    )
    for axis in axes:
        left_projection = tuple(
            sum(point[index] * axis[index] for index in range(3))
            for point in left
        )
        right_projection = tuple(
            sum(point[index] * axis[index] for index in range(3))
            for point in right
        )
        if (
            min(max(left_projection), max(right_projection))
            - max(min(left_projection), min(right_projection))
            <= 1.0e-9
        ):
            return False
    return True


def _box_vertices(
    bounds: tuple[float, ...]
) -> tuple[tuple[float, float, float], ...]:
    x0, y0, z0, x1, y1, z1 = bounds
    return (
        (x0, y0, z0),
        (x1, y0, z0),
        (x1, y1, z0),
        (x0, y1, z0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    )


def _linear_sweep_vertices(
    sweep: tuple[float, float, float, float, float, float],
    clear_height: float,
) -> tuple[tuple[float, float, float], ...]:
    x0, x1, y0, y1, upper_z, lower_z = sweep
    lower0 = upper_z
    lower1 = lower_z
    upper0 = upper_z + clear_height
    upper1 = lower_z + clear_height
    return (
        (x0, y0, lower0),
        (x1, y0, lower1),
        (x1, y1, lower1),
        (x0, y1, lower0),
        (x0, y0, upper0),
        (x1, y0, upper1),
        (x1, y1, upper1),
        (x0, y1, upper0),
    )


def _shell_prism_vertices(
    nodes: dict[int, tuple[float, float, float]],
    shell: object,
    thickness: float,
    *,
    z_offset_m: float = 0.0,
) -> tuple[tuple[float, float, float], ...]:
    points = tuple(nodes[node_id] for node_id in shell.node_ids)  # type: ignore[attr-defined]
    normal = _normalized_vector(
        _vector_cross(
            _vector_subtract(points[1], points[0]),
            _vector_subtract(points[3], points[0]),
        )
    )
    if normal is None:
        raise AssertionError("test oracle received a degenerate shell")
    offset = tuple(value * thickness / 2.0 for value in normal)
    return tuple(
        tuple(
            point[axis] - offset[axis] + (z_offset_m if axis == 2 else 0.0)
            for axis in range(3)
        )
        for point in points
    ) + tuple(
        tuple(
            point[axis] + offset[axis] + (z_offset_m if axis == 2 else 0.0)
            for axis in range(3)
        )
        for point in points
    )  # type: ignore[return-value]


def _linear_clearance_sweep_intersects_box(
    sweep: tuple[float, float, float, float, float, float],
    box: tuple[float, ...],
    clear_height: float,
) -> bool:
    x0, x1, y0, y1, upper_z, lower_z = sweep
    overlap_x0 = max(x0, box[0])
    overlap_x1 = min(x1, box[3])
    if overlap_x1 - overlap_x0 <= 1.0e-9:
        return False
    if min(y1, box[4]) - max(y0, box[1]) <= 1.0e-9:
        return False

    def walk_z(x: float) -> float:
        fraction = (x - x0) / (x1 - x0)
        return upper_z + (lower_z - upper_z) * fraction

    surface_values = (walk_z(overlap_x0), walk_z(overlap_x1))
    swept_min = min(surface_values)
    swept_max = max(surface_values) + clear_height
    return min(swept_max, box[5]) - max(swept_min, box[2]) > 1.0e-9


def _full_subway_route_clearance_collisions(
    package: object,
    *,
    roof_z_offset_m: float = 0.0,
) -> list[tuple[str, str, int]]:
    artifact = package.artifacts[0]  # type: ignore[attr-defined]
    circulation = package.geometry_manifest["subway_circulation"]  # type: ignore[attr-defined]
    clear_height = float(package.generation_options["passage_clear_height_m"])  # type: ignore[attr-defined]
    equipment_envelope = float(
        package.generation_options["escalator_equipment_envelope_m"]  # type: ignore[attr-defined]
    )
    frame_size = float(package.generation_options["pavilion_frame_size_m"])  # type: ignore[attr-defined]
    shell_thickness_by_role = {
        "pavilion_glazing": float(
            package.generation_options["pavilion_glazing_thickness_m"]  # type: ignore[attr-defined]
        ),
        "pavilion_metal_roof": float(
            package.generation_options["pavilion_roof_thickness_m"]  # type: ignore[attr-defined]
        ),
    }
    parameters = artifact.normalized_input["structural_system"]["parameters"]
    clearance_boxes: list[tuple[str, tuple[float, ...]]] = []
    for index, row in enumerate(parameters["task4_subway_solid_members"]):
        if row["part_role"] not in {
            "upper_landing",
            "fixed_stair_A",
            "lower_landing_8",
        }:
            continue
        bounds = tuple(float(value) for value in row["bounds_m"])
        clearance_boxes.append(
            (
                f"{row['part_role']}_{index}",
                (
                    bounds[0],
                    bounds[1],
                    bounds[5],
                    bounds[3],
                    bounds[4],
                    bounds[5] + clear_height,
                ),
            )
        )
    passage = tuple(float(value) for value in circulation["passage_9_bounds_m"])
    clearance_boxes.append(
        (
            "passage_9",
            (
                passage[0],
                passage[1],
                passage[2],
                passage[3],
                passage[4],
                passage[2] + clear_height,
            ),
        )
    )
    terminal = next(
        row
        for row in artifact.normalized_input["openings"]
        if row["id"] == "terminal_interface_10"
    )
    terminal_bounds = tuple(float(value) for value in terminal["bounds_m"])
    clearance_boxes.append(
        (
            "terminal_interface_10",
            (
                terminal_bounds[0],
                terminal_bounds[1],
                terminal_bounds[2],
                terminal_bounds[3],
                terminal_bounds[4],
                terminal_bounds[2] + clear_height,
            ),
        )
    )
    sloped_sweeps = []
    for lane_id in ("B", "C"):
        lane = tuple(
            float(value) for value in circulation["lane_envelopes_m"][lane_id]
        )
        sloped_sweeps.append(
            (
                lane_id,
                (
                    lane[0],
                    lane[3],
                    lane[1] + equipment_envelope,
                    lane[4] - equipment_envelope,
                    lane[5],
                    lane[2],
                ),
            )
        )

    nodes = {row.node_id: row.coordinates for row in artifact.mesh.nodes}
    pavilion_obstruction_roles = {
        "pavilion_frame",
        "pavilion_glazing",
        "pavilion_metal_roof",
        "generic_signage",
    }
    obstacle_bounds = [
        (row.part_role, row.element_id, _element_bounds(nodes, row))
        for row in artifact.mesh.solids
    ]
    obstacle_bounds.extend(
        (
            row.part_role,
            row.element_id,
            _physical_element_bounds(
                nodes,
                row,
                beam_size_m=frame_size,
            ),
        )
        for row in artifact.mesh.beams
        if row.part_role == "pavilion_frame"
    )
    shell_obstacles = [
        (
            row.part_role,
            row.element_id,
            row,
            shell_thickness_by_role.get(row.part_role, 0.0),
        )
        for row in artifact.mesh.shells
        if row.part_role in pavilion_obstruction_roles
    ]
    collisions = [
        (label, role, element_id)
        for label, sweep in clearance_boxes
        for role, element_id, bounds in obstacle_bounds
        if _positive_box_overlap(sweep, bounds)
    ]
    collisions.extend(
        (label, role, element_id)
        for label, sweep in clearance_boxes
        for role, element_id, shell, thickness in shell_obstacles
        if thickness > 0.0
        and _positive_prism_overlap(
            _box_vertices(sweep),
            _shell_prism_vertices(
                nodes,
                shell,
                thickness,
                z_offset_m=(
                    roof_z_offset_m
                    if role == "pavilion_metal_roof"
                    else 0.0
                ),
            ),
        )
    )
    collisions.extend(
        (label, role, element_id)
        for label, sweep in sloped_sweeps
        for role, element_id, bounds in obstacle_bounds
        if _linear_clearance_sweep_intersects_box(sweep, bounds, clear_height)
    )
    collisions.extend(
        (label, role, element_id)
        for label, sweep in sloped_sweeps
        for role, element_id, shell, thickness in shell_obstacles
        if thickness > 0.0
        and _positive_prism_overlap(
            _linear_sweep_vertices(sweep, clear_height),
            _shell_prism_vertices(
                nodes,
                shell,
                thickness,
                z_offset_m=(
                    roof_z_offset_m
                    if role == "pavilion_metal_roof"
                    else 0.0
                ),
            ),
        )
    )
    return collisions


def _physical_subway_roof_top(package: object) -> float:
    artifact = package.artifacts[0]  # type: ignore[attr-defined]
    roof_rows = [
        row
        for row in artifact.normalized_input["structural_system"]["parameters"][
            "task4_subway_components"
        ]
        if row["part_role"] == "pavilion_metal_roof"
    ]
    return max(
        max(float(point[2]) for point in row["points_m"])
        + float(row["physical_vertical_half_thickness_m"])
        for row in roof_rows
    )


def _minimum_roof_route_vertical_gap(package: object) -> float:
    artifact = package.artifacts[0]  # type: ignore[attr-defined]
    circulation = package.geometry_manifest["subway_circulation"]  # type: ignore[attr-defined]
    clear_height = float(package.generation_options["passage_clear_height_m"])  # type: ignore[attr-defined]
    equipment_envelope = float(
        package.generation_options["escalator_equipment_envelope_m"]  # type: ignore[attr-defined]
    )
    roof_thickness = float(
        package.generation_options["pavilion_roof_thickness_m"]  # type: ignore[attr-defined]
    )
    parameters = artifact.normalized_input["structural_system"]["parameters"]
    horizontal_clearance_surfaces = []
    for row in parameters["task4_subway_solid_members"]:
        if row["part_role"] not in {
            "upper_landing",
            "fixed_stair_A",
            "lower_landing_8",
        }:
            continue
        bounds = tuple(float(value) for value in row["bounds_m"])
        horizontal_clearance_surfaces.append(
            (bounds[0], bounds[3], bounds[1], bounds[4], 0.0, bounds[5] + clear_height)
        )
    passage = tuple(float(value) for value in circulation["passage_9_bounds_m"])
    horizontal_clearance_surfaces.append(
        (passage[0], passage[3], passage[1], passage[4], 0.0, passage[2] + clear_height)
    )
    terminal = next(
        row
        for row in artifact.normalized_input["openings"]
        if row["id"] == "terminal_interface_10"
    )
    terminal_bounds = tuple(float(value) for value in terminal["bounds_m"])
    horizontal_clearance_surfaces.append(
        (
            terminal_bounds[0],
            terminal_bounds[3],
            terminal_bounds[1],
            terminal_bounds[4],
            0.0,
            terminal_bounds[2] + clear_height,
        )
    )
    route_surfaces = list(horizontal_clearance_surfaces)
    for lane_id in ("B", "C"):
        lane = tuple(
            float(value) for value in circulation["lane_envelopes_m"][lane_id]
        )
        slope = (lane[2] - lane[5]) / (lane[3] - lane[0])
        intercept = lane[5] + clear_height - slope * lane[0]
        route_surfaces.append(
            (
                lane[0],
                lane[3],
                lane[1] + equipment_envelope,
                lane[4] - equipment_envelope,
                slope,
                intercept,
            )
        )

    gaps = []
    for row in parameters["task4_subway_components"]:
        if row["part_role"] != "pavilion_metal_roof":
            continue
        points = tuple(tuple(float(value) for value in point) for point in row["points_m"])
        normal = _normalized_vector(
            _vector_cross(
                _vector_subtract(points[1], points[0]),
                _vector_subtract(points[3], points[0]),
            )
        )
        if normal is None or abs(normal[2]) <= 1.0e-12:
            raise AssertionError("test oracle received a vertical roof facet")
        roof_slope_x = -normal[0] / normal[2]
        roof_slope_y = -normal[1] / normal[2]
        roof_intercept = (
            points[0][2]
            - roof_slope_x * points[0][0]
            - roof_slope_y * points[0][1]
        )
        vertical_half_thickness = roof_thickness * math.sqrt(
            1.0 + roof_slope_x**2 + roof_slope_y**2
        ) / 2.0
        roof_x0 = min(point[0] for point in points)
        roof_x1 = max(point[0] for point in points)
        roof_y0 = min(point[1] for point in points)
        roof_y1 = max(point[1] for point in points)
        for route_x0, route_x1, route_y0, route_y1, route_slope_x, route_intercept in route_surfaces:
            overlap_x0 = max(roof_x0, route_x0)
            overlap_x1 = min(roof_x1, route_x1)
            overlap_y0 = max(roof_y0, route_y0)
            overlap_y1 = min(roof_y1, route_y1)
            if overlap_x1 - overlap_x0 <= 1.0e-12 or overlap_y1 - overlap_y0 <= 1.0e-12:
                continue
            for x in (overlap_x0, overlap_x1):
                for y in (overlap_y0, overlap_y1):
                    roof_lower = (
                        roof_intercept
                        + roof_slope_x * x
                        + roof_slope_y * y
                        - vertical_half_thickness
                    )
                    route_upper = route_intercept + route_slope_x * x
                    gaps.append(roof_lower - route_upper)
    if not gaps:
        raise AssertionError("test oracle found no roof/route overlap")
    return min(gaps)


class AxisAlignedUnionExactCountTests(unittest.TestCase):
    def test_exact_counter_matches_mesher_for_overlap_exclusion_and_role_priority(self) -> None:
        members = (
            ("base", AxisAlignedBox(0.0, 0.0, 0.0, 1.0, 0.8, 0.4)),
            ("wall", AxisAlignedBox(0.6, 0.2, 0.0, 1.2, 0.6, 1.0)),
        )
        exclusions = (AxisAlignedBox(0.7, 0.3, 0.2, 0.9, 0.5, 0.8),)
        priority = {"base": 0, "wall": 2}

        expected = count_axis_aligned_union_cells(
            members, 0.20, exclusions, priority
        )
        fragment = mesh_axis_aligned_union(members, 0.20, exclusions, priority)

        self.assertEqual(expected, len(fragment.solids))
        self.assertIn("base", {row.part_role for row in fragment.solids})
        self.assertIn("wall", {row.part_role for row in fragment.solids})

    def test_exact_counter_matches_mesher_for_seeded_sparse_unions(self) -> None:
        generator = random.Random(1804)
        for sample in range(20):
            members: list[tuple[str, AxisAlignedBox]] = []
            for index in range(generator.randint(1, 4)):
                x = generator.randrange(0, 6) * 0.2
                y = generator.randrange(0, 5) * 0.2
                z = generator.randrange(0, 3) * 0.2
                members.append(
                    (
                        f"role_{index % 2}",
                        AxisAlignedBox(
                            x,
                            y,
                            z,
                            x + generator.randint(1, 4) * 0.2,
                            y + generator.randint(1, 3) * 0.2,
                            z + generator.randint(1, 3) * 0.2,
                        ),
                    )
                )
            exclusions = (
                AxisAlignedBox(0.2, 0.2, 0.0, 0.4, 0.4, 0.2),
            )
            with self.subTest(sample=sample):
                count = count_axis_aligned_union_cells(
                    members, 0.10, exclusions, {"role_1": 2}
                )
                mesh = mesh_axis_aligned_union(
                    members, 0.10, exclusions, {"role_1": 2}
                )
                self.assertEqual(count, len(mesh.solids))

    def test_limited_counter_does_not_materialize_large_union_ownership(self) -> None:
        members = (
            ("large", AxisAlignedBox(0.0, 0.0, 0.0, 200.0, 200.0, 200.0)),
        )
        tracemalloc.start()
        try:
            count = count_axis_aligned_union_cells(
                members,
                0.05,
                max_cells=2_000,
            )
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        self.assertEqual(2_001, count)
        self.assertLess(peak_bytes, 8_000_000)

    def test_subway_template_preflight_stops_at_hard_limit_plus_one(self) -> None:
        template = build_small_subway_template(max_solid_elements=100)

        self.assertEqual(101, template.solid_element_estimate)


class Phase18DResidentialTests(unittest.TestCase):
    def test_one_independent_artifact_per_tower_preserves_exact_gap_and_placement(self) -> None:
        package = compile_small_residential(
            origin_m=(10.0, 20.0, 30.0), rotation_deg=(0.0, 0.0, 15.0)
        )

        self.assertEqual(["tower_001", "tower_002"], [row.asset_id for row in package.artifacts])
        self.assertTrue(
            all(row.system_id == "rc_frame_shear_wall" for row in package.artifacts)
        )
        self.assertAlmostEqual(
            SMALL_RESIDENTIAL["tower_spacing_m"],
            package.artifacts[1].mesh.bounds_m[0] - package.artifacts[0].mesh.bounds_m[3],
            places=12,
        )
        self.assertEqual((10.0, 20.0, 30.0), package.placement["origin_m"])
        self.assertEqual((0.0, 0.0, 15.0), package.placement["rotation_deg"])
        self.assertAlmostEqual(0.0, package.artifacts[0].mesh.bounds_m[0], places=12)
        self.assertAlmostEqual(
            SMALL_RESIDENTIAL["tower_length_m"] + SMALL_RESIDENTIAL["tower_spacing_m"],
            package.artifacts[1].mesh.bounds_m[0],
            places=12,
        )
        for artifact in package.artifacts:
            envelope = artifact.topology_manifest["envelope_bounds_m"]
            nodes = {row.node_id: row.coordinates for row in artifact.mesh.nodes}
            for element in (*artifact.mesh.solids, *artifact.mesh.beams):
                xs = [nodes[node_id][0] for node_id in element.node_ids]
                self.assertGreaterEqual(min(xs), envelope[0] - 1.0e-12)
                self.assertLessEqual(max(xs), envelope[3] + 1.0e-12)

    def test_each_storey_has_four_apartments_core_four_doors_and_first_floor_exit(self) -> None:
        package = compile_small_residential()
        artifact = package.artifacts[0]
        spaces = artifact.normalized_input["spaces"]
        openings = artifact.normalized_input["openings"]

        self.assertEqual(5, len(spaces))
        self.assertEqual(4, sum(row["kind"] == "apartment_door" for row in openings))
        self.assertEqual(2, len(artifact.normalized_input["structural_system"]["parameters"]["wall_bounds_m"]))
        core_id = "tower_001_level_01_core"
        self.assertIn("exterior", artifact.topology_manifest["adjacency"][core_id])
        self.assertEqual(
            4,
            sum(
                row["id"].startswith("tower_001_level_01_apartment_")
                and row["kind"] == "apartment"
                for row in spaces
            ),
        )
        boxes = [row["bounds_m"] for row in spaces]
        for index, left in enumerate(boxes):
            for right in boxes[index + 1 :]:
                self.assertFalse(
                    all(
                        max(left[axis], right[axis])
                        < min(left[axis + 3], right[axis + 3])
                        for axis in range(3)
                    )
                )

    def test_storey_count_derivation_is_normalized_and_validated(self) -> None:
        implicit = compile_small_residential()
        explicit = compile_small_residential(
            generation_options={"storey_count": 1, "rebar_spacing_m": 0.50}
        )
        self.assertEqual(implicit.fingerprint, explicit.fingerprint)
        self.assertEqual(1, implicit.generation_options["storey_count"])

        for invalid in (True, 0, -1, 1.5, "2"):
            with self.subTest(storey_count=invalid):
                with self.assertRaisesRegex(ValueError, "storey_count"):
                    compile_small_residential(
                        generation_options={"storey_count": invalid}
                    )
        for invalid in (0, 7, 1.5):
            geometry = dict(SMALL_RESIDENTIAL, tower_count=invalid)
            with self.subTest(tower_count=invalid):
                with self.assertRaisesRegex(ValueError, "tower_count"):
                    compile_detailed_building_asset(
                        RESIDENTIAL_ID,
                        legacy_geometry=geometry,
                        mesh_profile="coarse",
                    )

    def test_default_reinforcement_alternative_system_and_concrete_only_are_distinct(self) -> None:
        reinforced = compile_small_residential()
        alternative = compile_small_residential(structural_system="rc_frame")
        concrete_only = compile_small_residential(
            generation_options={
                "reinforcement_mode": "concrete_only",
                "rebar_spacing_m": 0.50,
            }
        )

        for artifact in reinforced.artifacts:
            self.assertIn("wall_rebar", _beam_roles(artifact))
            self.assertTrue(artifact.connections_by_type("embedded_rebar"))
        for artifact in alternative.artifacts:
            self.assertNotIn("rc_shear_wall", {row.part_role for row in artifact.mesh.solids})
            self.assertNotIn("wall_rebar", _beam_roles(artifact))
        for artifact in concrete_only.artifacts:
            self.assertGreater(len(artifact.mesh.solids), 0)
            self.assertFalse(artifact.mesh.beams)
            self.assertFalse(artifact.connections_by_type("embedded_rebar"))
        self.assertNotIn("balcony", " ".join(reinforced.unmodeled_scope).lower())

    def test_balcony_depth_changes_real_slab_and_barrier_mesh(self) -> None:
        shallow_geometry = dict(SMALL_RESIDENTIAL, balcony_depth_m=0.40)
        deep_geometry = dict(SMALL_RESIDENTIAL, balcony_depth_m=0.90)
        shallow = compile_detailed_building_asset(
            RESIDENTIAL_ID,
            legacy_geometry=shallow_geometry,
            mesh_profile="coarse",
            generation_options={"rebar_spacing_m": 0.50},
        ).artifacts[0]
        deep = compile_detailed_building_asset(
            RESIDENTIAL_ID,
            legacy_geometry=deep_geometry,
            mesh_profile="coarse",
            generation_options={"rebar_spacing_m": 0.50},
        ).artifacts[0]

        def balcony_y_extent(artifact: object, role: str) -> tuple[float, float]:
            nodes = {row.node_id: row.coordinates for row in artifact.mesh.nodes}  # type: ignore[attr-defined]
            shells = [
                row
                for row in artifact.mesh.shells  # type: ignore[attr-defined]
                if row.part_role == role
            ]
            self.assertTrue(shells)
            values = [nodes[node_id][1] for shell in shells for node_id in shell.node_ids]
            return min(values), max(values)

        slab_role = "nonstructural_balcony_slab"
        barrier_role = "nonstructural_balcony_barrier"
        shallow_extent = balcony_y_extent(shallow, slab_role)
        deep_extent = balcony_y_extent(deep, slab_role)
        balcony_y_extent(shallow, barrier_role)
        balcony_y_extent(deep, barrier_role)
        self.assertAlmostEqual(0.40, shallow_extent[1] - shallow_extent[0])
        self.assertAlmostEqual(0.90, deep_extent[1] - deep_extent[0])
        self.assertNotEqual(shallow.mesh.fingerprint, deep.mesh.fingerprint)
        self.assertNotEqual(shallow.normalized_input, deep.normalized_input)

    def test_package_aggregation_excludes_gap_and_tags_unique_resources(self) -> None:
        package = compile_small_residential()
        expected_gross = (
            SMALL_RESIDENTIAL["tower_count"]
            * SMALL_RESIDENTIAL["tower_length_m"]
            * SMALL_RESIDENTIAL["tower_width_m"]
            * SMALL_RESIDENTIAL["tower_height_m"]
        )
        self.assertAlmostEqual(
            expected_gross,
            package.quantity_manifest["gross_envelope_volume_m3"],
            places=9,
        )
        self.assertEqual(
            sum(len(row.mesh.solids) for row in package.artifacts),
            package.mesh_manifest["counts"]["solids"],
        )
        binding_keys = [
            (row["artifact_id"], row["part_role"])
            for row in package.material_binding_manifest["bindings"]
        ]
        self.assertEqual(len(binding_keys), len(set(binding_keys)))
        surface_keys = [
            (row["artifact_id"], row["face_id"])
            for row in package.refined_surface_catalog["user_selectable_surfaces"]
        ]
        self.assertEqual(len(surface_keys), len(set(surface_keys)))
        self.assertTrue(all(key[0].startswith("tower_") for key in surface_keys))

    def test_exact_preflight_matches_final_solids_and_accepts_literal_boundary(self) -> None:
        package = compile_small_residential()
        count = package.mesh_manifest["actual_solid_elements"]
        self.assertEqual("exact", package.mesh_manifest["solid_estimate_kind"])
        self.assertEqual(count, package.mesh_manifest["predicted_solid_elements"])

        with self.assertRaisesRegex(ValueError, "exceeds limit"):
            compile_small_residential(
                generation_options={
                    "max_solid_elements": count - 1,
                    "rebar_spacing_m": 0.50,
                }
            )
        accepted = compile_small_residential(
            generation_options={
                "max_solid_elements": count,
                "rebar_spacing_m": 0.50,
            }
        )
        self.assertEqual(count, accepted.mesh_manifest["actual_solid_elements"])

    def test_default_template_uses_exact_count_below_hard_limit_without_meshing(self) -> None:
        descriptor = get_detailed_building_asset(RESIDENTIAL_ID)
        geometry = normalize_asset_geometry(descriptor, None)
        template = build_detailed_building_template(
            descriptor,
            geometry,
            structural_system="rc_frame_shear_wall",
            fidelity_profile="blast_response",
            mesh_profile="standard",
            generation_options={
                "max_solid_elements": 5_000_000,
                "reinforcement_mode": "full_reinforced",
                "cover_m": 0.04,
                "bar_diameter_m": 0.016,
                "rebar_spacing_m": 0.30,
                "storey_count": 6,
            },
        )
        self.assertEqual("exact", template.solid_estimate_kind)
        self.assertGreater(template.solid_element_estimate, 0)
        self.assertLessEqual(template.solid_element_estimate, 5_000_000)


class Phase18DSubwayTests(unittest.TestCase):
    def assert_physical_roof_and_rc_close_declared_envelopes(
        self,
        package: object,
    ) -> None:
        artifact = package.artifacts[0]  # type: ignore[attr-defined]
        physical_roof_top = _physical_subway_roof_top(package)
        envelope = artifact.normalized_input["envelope"]
        envelope_top = float(envelope["origin_m"][2]) + float(
            envelope["size_m"][2]
        )
        level_top = max(
            float(level["elevation_m"]) + float(level["height_m"])
            for level in artifact.normalized_input["levels"]
        )
        local_bounds = package.geometry_manifest[  # type: ignore[attr-defined]
            "local_envelope_bounds_m"
        ]
        circulation = package.geometry_manifest[  # type: ignore[attr-defined]
            "subway_circulation"
        ]
        topology_bounds = artifact.topology_manifest["envelope_bounds_m"]
        pavilion = circulation["pavilion"]
        rc_top = float(circulation["below_grade_rc_enclosure_bounds_m"][5])
        overall_top = max(rc_top, physical_roof_top)

        self.assertAlmostEqual(overall_top, envelope_top)
        self.assertAlmostEqual(overall_top, level_top)
        self.assertAlmostEqual(overall_top, float(local_bounds[5]))
        self.assertAlmostEqual(
            overall_top,
            float(circulation["pavilion_validation_bounds_m"][5]),
        )
        self.assertAlmostEqual(overall_top, float(topology_bounds[5]))
        self.assertAlmostEqual(
            physical_roof_top,
            float(pavilion["physical_roof_top_m"]),
        )
        expected_gross = (
            float(envelope["size_m"][0])
            * float(envelope["size_m"][1])
            * float(envelope["size_m"][2])
        )
        self.assertAlmostEqual(
            expected_gross,
            float(artifact.topology_manifest["gross_volume_m3"]),
        )
        self.assertAlmostEqual(
            expected_gross,
            float(package.quantity_manifest["gross_envelope_volume_m3"]),  # type: ignore[attr-defined]
        )
        nodes = {row.node_id: row.coordinates for row in artifact.mesh.nodes}
        roof_thickness = float(
            package.generation_options["pavilion_roof_thickness_m"]  # type: ignore[attr-defined]
        )
        physical_mesh_top = max(
            point[2]
            for shell in artifact.mesh.shells
            if shell.part_role == "pavilion_metal_roof"
            for point in _shell_prism_vertices(nodes, shell, roof_thickness)
        )
        self.assertLessEqual(physical_mesh_top, physical_roof_top + 1.0e-12)
        self.assertEqual(
            package.mesh_manifest["predicted_solid_elements"],  # type: ignore[attr-defined]
            package.mesh_manifest["actual_solid_elements"],  # type: ignore[attr-defined]
        )

    def test_pavilion_clear_height_rejects_below_route_clearance(self) -> None:
        for slope in (None, 40.0):
            options = {
                "rebar_spacing_m": 0.50,
                "pavilion_clear_height_m": 1.0,
            }
            if slope is not None:
                options["fixed_stair_slope_deg"] = slope
            with self.subTest(fixed_stair_slope_deg=slope):
                with self.assertRaisesRegex(
                    ValueError,
                    r"pavilion_clear_height_m.*at least 2\.4",
                ):
                    compile_small_subway(generation_options=options)

    def test_physical_clearance_oracle_expands_sections_and_treats_contact_as_clear(self) -> None:
        class Element:
            def __init__(self, node_ids: tuple[int, ...]) -> None:
                self.node_ids = node_ids

        beam_nodes = {1: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0)}
        self.assertEqual(
            (-0.1, -0.1, -0.1, 1.1, 0.1, 0.1),
            _physical_element_bounds(
                beam_nodes,
                Element((1, 2)),
                beam_size_m=0.2,
            ),
        )
        shell_nodes = {
            1: (0.0, 0.0, 0.0),
            2: (1.0, 0.0, 0.0),
            3: (1.0, 0.0, 1.0),
            4: (0.0, 0.0, 1.0),
        }
        shell_bounds = _physical_element_bounds(
            shell_nodes,
            Element((1, 2, 3, 4)),
            shell_thickness_m=0.2,
        )
        self.assertEqual((0.0, -0.1, 0.0, 1.0, 0.1, 1.0), shell_bounds)
        self.assertFalse(
            _positive_box_overlap(
                shell_bounds,
                (0.0, 0.1, 0.0, 1.0, 0.2, 1.0),
            )
        )
        self.assertTrue(
            _positive_box_overlap(
                shell_bounds,
                (0.0, 0.099, 0.0, 1.0, 0.2, 1.0),
            )
        )
        inclined_nodes = {
            1: (0.0, 0.0, 1.0),
            2: (1.0, 0.0, 2.0),
            3: (1.0, 1.0, 2.0),
            4: (0.0, 1.0, 1.0),
        }
        inclined_shell = Element((1, 2, 3, 4))
        inclined_prism = _shell_prism_vertices(
            inclined_nodes,
            inclined_shell,
            0.2,
        )
        normal = _normalized_vector(
            _vector_cross(
                _vector_subtract(inclined_nodes[2], inclined_nodes[1]),
                _vector_subtract(inclined_nodes[4], inclined_nodes[1]),
            )
        )
        self.assertIsNotNone(normal)
        assert normal is not None
        contacting_clearance_prism = tuple(
            tuple(point[axis] - normal[axis] * 0.2 for axis in range(3))
            for point in inclined_prism
        )
        penetrating_clearance_prism = tuple(
            tuple(point[axis] + normal[axis] * 0.001 for axis in range(3))
            for point in contacting_clearance_prism
        )
        self.assertFalse(
            _positive_prism_overlap(
                inclined_prism,
                contacting_clearance_prism,
            )
        )
        self.assertTrue(
            _positive_prism_overlap(
                inclined_prism,
                penetrating_clearance_prism,
            )
        )

    def test_thick_pavilion_sections_keep_combined_route_physically_clear(self) -> None:
        package = compile_small_subway(
            generation_options={
                "rebar_spacing_m": 0.50,
                "fixed_stair_slope_deg": 40.0,
                "pavilion_frame_size_m": 0.12,
                "pavilion_glazing_thickness_m": 0.10,
                "pavilion_roof_thickness_m": 0.16,
            }
        )
        self.assertEqual([], _full_subway_route_clearance_collisions(package))
        minimum_roof_gap = _minimum_roof_route_vertical_gap(package)
        self.assertGreaterEqual(minimum_roof_gap, -1.0e-9)
        self.assertLess(minimum_roof_gap, 0.25)
        shifted_collisions = _full_subway_route_clearance_collisions(
            package,
            roof_z_offset_m=-(minimum_roof_gap + 0.001),
        )
        self.assertTrue(
            any(role == "pavilion_metal_roof" for _, role, _ in shifted_collisions)
        )
        self.assert_physical_roof_and_rc_close_declared_envelopes(package)
        artifact = package.artifacts[0]
        roof_rows = [
            row
            for row in artifact.normalized_input["structural_system"][
                "parameters"
            ]["task4_subway_components"]
            if row["part_role"] == "pavilion_metal_roof"
        ]
        projection_factors = {
            float(row["physical_normal_projection_factor"])
            for row in roof_rows
        }
        vertical_envelopes = {
            float(row["physical_vertical_half_envelope_m"])
            for row in roof_rows
        }
        self.assertEqual(1, len(projection_factors))
        self.assertEqual(1, len(vertical_envelopes))
        projection_factor = projection_factors.pop()
        vertical_envelope = vertical_envelopes.pop()
        self.assertTrue(math.isfinite(projection_factor))
        self.assertGreaterEqual(projection_factor, 1.0)
        self.assertAlmostEqual(
            vertical_envelope,
            0.16 * projection_factor / 2.0,
        )
        self.assertLess(vertical_envelope - 0.16 / 2.0, 0.16)
        pavilion = package.geometry_manifest["subway_circulation"]["pavilion"]
        self.assertEqual(
            projection_factor,
            pavilion.get("roof_shell_normal_projection_factor"),
        )
        self.assertEqual(
            vertical_envelope,
            pavilion.get("roof_shell_vertical_half_envelope_m"),
        )
        replayed = _compile_asset_definition(artifact.normalized_input)
        self.assertEqual(artifact.fingerprint, replayed.fingerprint)

    def test_pavilion_width_rejects_frame_plinth_footprint_inside_full_route(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "pavilion_width_m.*frame/plinth footprint"
        ):
            compile_small_subway(
                generation_options={
                    "rebar_spacing_m": 0.50,
                    "pavilion_width_m": 2.60,
                }
            )

        minimum_clear = compile_small_subway(
            generation_options={
                "rebar_spacing_m": 0.50,
                "pavilion_width_m": 2.80,
            }
        )
        self.assertEqual([], _full_subway_route_clearance_collisions(minimum_clear))

    def test_custom_stair_slope_clears_complete_pavilion_element_envelopes(self) -> None:
        package = compile_small_subway(
            generation_options={
                "rebar_spacing_m": 0.50,
                "fixed_stair_slope_deg": 40.0,
            }
        )

        self.assertEqual([], _full_subway_route_clearance_collisions(package))
        self.assert_physical_roof_and_rc_close_declared_envelopes(package)

    def test_low_rise_pavilion_below_rc_still_closes_overall_envelope(self) -> None:
        package = compile_small_subway(
            generation_options={
                "rebar_spacing_m": 0.50,
                "escalator_rise_m": 0.10,
                "escalator_angle_deg": 30.0,
                "pavilion_roof_arc_rise_m": 0.01,
                "pavilion_roof_thickness_m": 0.01,
            }
        )
        artifact = package.artifacts[0]
        circulation = package.geometry_manifest["subway_circulation"]
        physical_roof_top = _physical_subway_roof_top(package)
        rc_top = float(circulation["below_grade_rc_enclosure_bounds_m"][5])
        envelope = artifact.normalized_input["envelope"]
        envelope_top = float(envelope["origin_m"][2]) + float(
            envelope["size_m"][2]
        )

        self.assertLess(physical_roof_top, rc_top)
        self.assertAlmostEqual(rc_top, envelope_top)
        self.assertAlmostEqual(
            physical_roof_top,
            float(circulation["pavilion"]["physical_roof_top_m"]),
        )
        self.assertTrue(
            all(
                float(envelope["origin_m"][axis]) - 1.0e-12
                <= node.coordinates[axis]
                <= float(envelope["origin_m"][axis])
                + float(envelope["size_m"][axis])
                + 1.0e-12
                for node in artifact.mesh.nodes
                for axis in range(3)
            )
        )
        replayed = _compile_asset_definition(artifact.normalized_input)
        self.assertEqual(artifact.fingerprint, replayed.fingerprint)
        self.assertEqual(
            package.mesh_manifest["predicted_solid_elements"],
            package.mesh_manifest["actual_solid_elements"],
        )
        self.assert_physical_roof_and_rc_close_declared_envelopes(package)

    def test_complete_approved_route_has_continuous_solid_headroom(self) -> None:
        package = compile_small_subway()
        self.assert_physical_roof_and_rc_close_declared_envelopes(package)
        artifact = package.artifacts[0]
        circulation = package.geometry_manifest["subway_circulation"]
        clear_height = float(package.generation_options["passage_clear_height_m"])
        offsets = (0.05, clear_height / 2.0, clear_height - 0.05)

        sample_surfaces: list[tuple[str, float, float, float]] = []
        upper = circulation["upper_landing_bounds_m"]
        for lane_id, lane in circulation["lane_envelopes_m"].items():
            sample_surfaces.append(
                (
                    f"upper_{lane_id}",
                    (float(upper[0]) + float(upper[3])) / 2.0,
                    (float(lane[1]) + float(lane[4])) / 2.0,
                    float(lane[5]),
                )
            )
        parameters = artifact.normalized_input["structural_system"]["parameters"]
        for index, row in enumerate(parameters["task4_subway_solid_members"]):
            if row["part_role"] != "fixed_stair_A":
                continue
            bounds = row["bounds_m"]
            sample_surfaces.append(
                (
                    f"stair_A_{index}",
                    (float(bounds[0]) + float(bounds[3])) / 2.0,
                    (float(bounds[1]) + float(bounds[4])) / 2.0,
                    float(bounds[5]),
                )
            )
        for lane_id in ("B", "C"):
            lane = tuple(float(value) for value in circulation["lane_envelopes_m"][lane_id])
            for index in range(17):
                fraction = index / 16.0
                sample_surfaces.append(
                    (
                        f"{lane_id}_{index}",
                        lane[0] + (lane[3] - lane[0]) * fraction,
                        (lane[1] + lane[4]) / 2.0,
                        lane[5] + (lane[2] - lane[5]) * fraction,
                    )
                )
        route_start = float(circulation["lower_landing_8_bounds_m"][0])
        route_end = float(circulation["interface_10_plane_m"][0])
        route_y = (
            float(circulation["passage_9_bounds_m"][1])
            + float(circulation["passage_9_bounds_m"][4])
        ) / 2.0
        route_z = float(circulation["walkable_surface_elevations_m"]["passage_9"])
        for index in range(17):
            fraction = index / 16.0
            sample_surfaces.append(
                (
                    f"route_8_9_10_{index}",
                    route_start + (route_end - route_start) * fraction,
                    route_y,
                    route_z,
                )
            )

        blocked = [
            (label, offset)
            for label, x, y, walk_z in sample_surfaces
            for offset in offsets
            if artifact.solid_contains_point((x, y, walk_z + offset))
        ]
        self.assertEqual([], blocked)

    def test_escalator_balustrades_and_handrails_do_not_intersect_rc_roof(self) -> None:
        package = compile_small_subway()
        artifact = package.artifacts[0]
        nodes = {row.node_id: row.coordinates for row in artifact.mesh.nodes}
        roof_boxes = []
        for solid in artifact.mesh.solids:
            if solid.part_role != "rc_box_roof":
                continue
            points = [nodes[node_id] for node_id in solid.node_ids]
            roof_boxes.append(
                tuple(min(point[axis] for point in points) for axis in range(3))
                + tuple(max(point[axis] for point in points) for axis in range(3))
            )

        roof_envelope = (
            tuple(min(bounds[axis] for bounds in roof_boxes) for axis in range(3))
            + tuple(max(bounds[axis] for bounds in roof_boxes) for axis in range(3, 6))
        )

        def strictly_inside_roof(point: tuple[float, float, float]) -> bool:
            tolerance = 1.0e-9
            return (
                roof_envelope[0] - tolerance <= point[0] <= roof_envelope[3] + tolerance
                and roof_envelope[1] - tolerance <= point[1] <= roof_envelope[4] + tolerance
                and roof_envelope[2] + tolerance < point[2] < roof_envelope[5] - tolerance
            )

        collisions: list[tuple[str, tuple[float, float, float]]] = []
        for shell in artifact.mesh.shells:
            if not (
                shell.part_role.endswith("_balustrade")
                and shell.part_role.startswith("escalator_")
            ):
                continue
            corners = [nodes[node_id] for node_id in shell.node_ids]
            for index in range(41):
                fraction = index / 40.0
                for side in ((0, 1), (1, 2), (2, 3), (3, 0)):
                    point = tuple(
                        corners[side[0]][axis]
                        + (corners[side[1]][axis] - corners[side[0]][axis])
                        * fraction
                        for axis in range(3)
                    )
                    if strictly_inside_roof(point):
                        collisions.append((shell.part_role, point))
                midpoint = tuple(
                    sum(corner[axis] for corner in corners) / 4.0
                    for axis in range(3)
                )
                toward_midpoint = tuple(
                    corners[0][axis]
                    + (midpoint[axis] - corners[0][axis]) * fraction
                    for axis in range(3)
                )
                if strictly_inside_roof(toward_midpoint):
                    collisions.append((shell.part_role, toward_midpoint))
        for beam in artifact.mesh.beams:
            if not (
                beam.part_role.endswith("_handrails")
                and beam.part_role.startswith("escalator_")
            ):
                continue
            start, end = (nodes[node_id] for node_id in beam.node_ids)
            for index in range(41):
                fraction = index / 40.0
                point = tuple(
                    start[axis] + (end[axis] - start[axis]) * fraction
                    for axis in range(3)
                )
                if strictly_inside_roof(point):
                    collisions.append((beam.part_role, point))
        self.assertEqual([], collisions)

    def test_default_public_subway_call_compiles_with_review_only_defaults(self) -> None:
        package = compile_detailed_building_asset(SUBWAY_ID)
        self.assertFalse(package.solver_ready)
        self.assertTrue(package.requires_project_review)

    def test_walkable_junctions_are_continuous_and_normalized_input_replays(self) -> None:
        package = compile_small_subway()
        artifact = package.artifacts[0]
        circulation = package.geometry_manifest["subway_circulation"]
        elevations = circulation["walkable_surface_elevations_m"]
        lanes = circulation["lane_envelopes_m"]

        self.assertEqual(elevations["upper_landing"], lanes["A"][5])
        self.assertEqual(elevations["upper_landing"], lanes["B"][5])
        self.assertEqual(elevations["upper_landing"], lanes["C"][5])
        self.assertEqual(elevations["lower_landing_8"], lanes["A"][2])
        self.assertEqual(elevations["lower_landing_8"], elevations["passage_9"])
        self.assertIn("upper_landing", circulation["component_roles"])
        replayed = _compile_asset_definition(artifact.normalized_input)
        self.assertEqual(artifact.fingerprint, replayed.fingerprint)

    def test_stair_and_landings_use_conforming_union_and_mode_specific_rebar(self) -> None:
        reinforced = compile_small_subway()
        concrete_only = compile_small_subway(
            generation_options={"reinforcement_mode": "concrete_only", "rebar_spacing_m": 0.50}
        )
        artifact = reinforced.artifacts[0]
        nodes = {row.node_id: row.coordinates for row in artifact.mesh.nodes}
        roles_by_node: dict[int, set[str]] = {}
        for solid in artifact.mesh.solids:
            for node_id in solid.node_ids:
                roles_by_node.setdefault(node_id, set()).add(solid.part_role)
        floor_z = reinforced.geometry_manifest["subway_circulation"]["walkable_surface_elevations_m"]["lower_landing_8"]
        stair_interface_nodes = {
            node_id
            for solid in artifact.mesh.solids
            if solid.part_role == "fixed_stair_A"
            for node_id in solid.node_ids
            if abs(nodes[node_id][2] - floor_z) <= 1.0e-12
        }
        self.assertTrue(stair_interface_nodes)
        shared_interface_nodes = {
            node_id
            for node_id in stair_interface_nodes
            if roles_by_node[node_id] & {"rc_box_floor", "lower_landing_8"}
        }
        structural_interfaces = artifact.connections_by_type("tied_structural_interface")
        if shared_interface_nodes != stair_interface_nodes:
            stair_interface_solids = {
                solid.element_id
                for solid in artifact.mesh.solids
                if solid.part_role == "fixed_stair_A"
                and any(node_id in stair_interface_nodes for node_id in solid.node_ids)
            }
            tied_sources = {
                element_id
                for connection in structural_interfaces
                for element_id in connection.source_element_ids
            }
            self.assertTrue(stair_interface_solids <= tied_sources)
            self.assertTrue(
                all(connection.target_element_ids for connection in structural_interfaces)
            )
        self.assertIn("fixed_stair_rebar", _beam_roles(artifact))
        self.assertIn("landing_rebar", _beam_roles(artifact))
        embedded_sources = {
            element_id
            for connection in artifact.connections_by_type("embedded_rebar")
            for element_id in connection.source_element_ids
        }
        self.assertTrue(
            any(
                beam.element_id in embedded_sources
                for beam in artifact.mesh.beams
                if beam.part_role in {"fixed_stair_rebar", "landing_rebar"}
            )
        )
        self.assertFalse(
            _beam_roles(concrete_only.artifacts[0])
            & {"fixed_stair_rebar", "landing_rebar"}
        )

    def test_tied_structural_interface_contains_only_real_face_neighbors(self) -> None:
        artifact = compile_small_subway().artifacts[0]
        connection = artifact.connections_by_type("tied_structural_interface")[0]
        circulation = {
            solid.element_id
            for solid in artifact.mesh.solids
            if not solid.part_role.startswith("rc_box_")
        }
        enclosure = {
            solid.element_id
            for solid in artifact.mesh.solids
            if solid.part_role.startswith("rc_box_")
        }
        source_ids = set(connection.source_element_ids)
        target_ids = set(connection.target_element_ids)
        self.assertLess(len(source_ids), len(circulation))
        self.assertLess(len(target_ids), len(enclosure))

        nodes = {row.node_id: row.coordinates for row in artifact.mesh.nodes}
        bounds_by_id = {}
        for solid in artifact.mesh.solids:
            points = [nodes[node_id] for node_id in solid.node_ids]
            bounds_by_id[solid.element_id] = (
                tuple(min(point[axis] for point in points) for axis in range(3))
                + tuple(max(point[axis] for point in points) for axis in range(3))
            )
        target_faces: dict[tuple[int, float, int], list[int]] = {}
        for element_id in enclosure:
            bounds = bounds_by_id[element_id]
            for axis in range(3):
                target_faces.setdefault((axis, round(bounds[axis], 9), -1), []).append(element_id)
                target_faces.setdefault((axis, round(bounds[axis + 3], 9), 1), []).append(element_id)

        adjacent_sources: set[int] = set()
        adjacent_targets: set[int] = set()
        for source_id in circulation:
            source = bounds_by_id[source_id]
            for axis in range(3):
                other_axes = tuple(index for index in range(3) if index != axis)
                for coordinate, source_side, target_side in (
                    (source[axis], -1, 1),
                    (source[axis + 3], 1, -1),
                ):
                    for target_id in target_faces.get(
                        (axis, round(coordinate, 9), target_side), []
                    ):
                        target = bounds_by_id[target_id]
                        if all(
                            min(source[index + 3], target[index + 3])
                            - max(source[index], target[index])
                            > 1.0e-9
                            for index in other_axes
                        ):
                            adjacent_sources.add(source_id)
                            adjacent_targets.add(target_id)

        self.assertTrue(adjacent_sources)
        self.assertEqual(adjacent_sources, source_ids)
        self.assertEqual(adjacent_targets, target_ids)

    def test_structural_interface_query_scales_with_local_candidates(self) -> None:
        from lsprepost_mcp.refined_building.asset_compiler import (
            _task4_structural_interface_groups_with_stats,
        )

        def run(strip_count: int) -> tuple[int, int]:
            members = [
                (
                    "rc_box_wall",
                    AxisAlignedBox(float(index), 0.0, 0.0, float(index + 1), 1.0, 1.0),
                )
                for index in range(strip_count)
            ]
            members.extend(
                (
                    "lower_landing_8",
                    AxisAlignedBox(float(index), 1.0, 0.0, float(index + 1), 2.0, 1.0),
                )
                for index in range(strip_count)
            )
            mesh = mesh_axis_aligned_union(
                members,
                1.0,
                role_priority={"rc_box_wall": 0, "lower_landing_8": 1},
            )
            groups, candidate_checks = (
                _task4_structural_interface_groups_with_stats(mesh)
            )
            source_ids, target_ids = groups["lower_landing_8"]
            self.assertEqual(strip_count, len(source_ids))
            self.assertEqual(strip_count, len(target_ids))
            self.assertLessEqual(candidate_checks, 4 * strip_count)
            return len(source_ids), candidate_checks

        _, small_checks = run(64)
        _, large_checks = run(128)
        self.assertLessEqual(large_checks, 2 * small_checks + 4)

    def test_subway_local_mesh_avoids_global_stair_axis_explosion(self) -> None:
        small = build_small_subway_template()
        descriptor = get_detailed_building_asset(SUBWAY_ID)
        geometry = normalize_asset_geometry(descriptor, None)
        options = _normalize_generation_options(
            None,
            "rc_box",
            SUBWAY_ID,
            geometry,
        )
        default = build_detailed_building_template(
            descriptor,
            geometry,
            structural_system="rc_box",
            fidelity_profile="blast_response",
            mesh_profile="standard",
            generation_options=options,
        )

        self.assertLess(small.solid_element_estimate, 100_000)
        self.assertLess(default.solid_element_estimate, 750_000)
        artifact = compile_small_subway().artifacts[0]
        connections = artifact.connections_by_type("tied_structural_interface")
        self.assertTrue(connections)
        self.assertTrue(
            all(
                dict(connection.metadata).get("coverage") == "complete"
                for connection in connections
            )
        )

    def test_every_retained_subway_parameter_changes_compiled_geometry(self) -> None:
        baseline = build_small_subway_template()
        baseline_definition = baseline.definitions[0]["structural_system"]["parameters"]
        variants = {
            "stair_tread_m": 0.30,
            "escalator_angle_deg": 35.0,
            "escalator_equipment_envelope_m": 0.08,
            "pavilion_overhang_m": 0.30,
            "pavilion_frame_size_m": 0.08,
            "pavilion_glazing_thickness_m": 0.02,
            "pavilion_roof_thickness_m": 0.04,
        }
        baseline_geometry = (
            baseline_definition["task4_subway_solid_members"],
            baseline_definition["task4_subway_components"],
        )
        for key, value in variants.items():
            with self.subTest(parameter=key):
                changed = build_small_subway_template(**{key: value})
                parameters = changed.definitions[0]["structural_system"]["parameters"]
                self.assertNotEqual(
                    baseline_geometry,
                    (
                        parameters["task4_subway_solid_members"],
                        parameters["task4_subway_components"],
                    ),
                )

    def test_subway_specific_material_roles_accept_strict_overrides(self) -> None:
        package = compile_small_subway(
            material_overrides={
                "metal_roof": "mild_steel_mat24_demo",
                "signage": "mild_steel_mat24_demo",
                "escalator_equipment": "mild_steel_mat24_demo",
                "escalator_balustrade": "mild_steel_mat24_demo",
                "escalator_handrail": "rubber_generic",
            }
        )
        rows = package.material_binding_manifest["bindings"]
        for role in (
            "metal_roof",
            "signage",
            "escalator_equipment",
            "escalator_balustrade",
            "escalator_handrail",
        ):
            self.assertTrue(
                any(row["semantic_role"] == role and row["resolution_status"] == "resolved" for row in rows)
            )

    def test_approved_topology_is_one_stair_two_parallel_escalators_then_8_9_10(self) -> None:
        package = compile_small_subway()
        circulation = package.geometry_manifest["subway_circulation"]

        self.assertEqual(1, circulation["fixed_stair_count"])
        self.assertEqual(2, circulation["escalator_count"])
        self.assertEqual(("A", "B", "C"), tuple(circulation["parallel_lane_ids"]))
        self.assertEqual(
            ("upper_landing", "A_B_C", "lower_landing_8", "passage_9", "interface_10"),
            tuple(circulation["longitudinal_route"]),
        )
        self.assertEqual("x", circulation["longitudinal_axis"])
        self.assertFalse(circulation["has_turn"])
        self.assertFalse(circulation["has_station_hall"])

    def test_hollow_passage_and_pavilion_equipment_roles_exist_in_real_mesh(self) -> None:
        package = compile_small_subway()
        artifact = package.artifacts[0]
        circulation = package.geometry_manifest["subway_circulation"]
        roles = circulation["component_roles"]

        self.assertFalse(artifact.solid_contains_point(tuple(circulation["passage_probe_m"])))
        self.assertTrue(artifact.solid_contains_point(tuple(circulation["passage_wall_probe_m"])))
        expected_roles = {
            "fixed_stair_A",
            "pavilion_rc_plinth",
            "lower_landing_8",
            "pavilion_frame",
            "pavilion_glazing",
            "pavilion_metal_roof",
            "generic_signage",
            "escalator_1",
            "escalator_2",
        }
        self.assertTrue(expected_roles.issubset(roles))
        mesh_roles = {
            *(row.part_role for row in artifact.mesh.solids),
            *(row.part_role for row in artifact.mesh.shells),
            *(row.part_role for row in artifact.mesh.beams),
        }
        for semantic_role in expected_roles:
            self.assertTrue(set(roles[semantic_role]["part_ids"]).issubset(mesh_roles))
        self.assertNotEqual(roles["escalator_1"]["part_ids"], roles["escalator_2"]["part_ids"])
        self.assertGreaterEqual(len(roles["escalator_1"]["part_ids"]), 3)
        self.assertGreaterEqual(len(roles["escalator_2"]["part_ids"]), 3)
        self.assertFalse(
            set(roles["escalator_1"]["part_ids"])
            & set(roles["escalator_2"]["part_ids"])
        )
        binding_by_part = {
            row["part_role"]: row
            for row in package.material_binding_manifest["bindings"]
        }
        self.assertEqual("structural_steel", binding_by_part["pavilion_frame"]["semantic_role"])
        self.assertEqual("glazing", binding_by_part["pavilion_glazing"]["semantic_role"])
        self.assertEqual("metal_roof", binding_by_part["pavilion_metal_roof"]["semantic_role"])
        nodes = {row.node_id: row.coordinates for row in artifact.mesh.nodes}
        frame_x = min(
            nodes[node_id][0]
            for beam in artifact.mesh.beams
            if beam.part_role == "pavilion_frame"
            for node_id in beam.node_ids
        )
        roof_x = min(
            nodes[node_id][0]
            for shell in artifact.mesh.shells
            if shell.part_role == "pavilion_metal_roof"
            for node_id in shell.node_ids
        )
        self.assertLess(roof_x, frame_x)
        for equipment_id in ("escalator_1", "escalator_2"):
            self.assertTrue(
                any(
                    part_id.endswith("_handrails")
                    for part_id in roles[equipment_id]["part_ids"]
                )
            )
            self.assertTrue(
                any(
                    part_id.endswith("_balustrade")
                    for part_id in roles[equipment_id]["part_ids"]
                )
            )
            equipment_materials = {
                binding_by_part[part_id]["semantic_role"]
                for part_id in roles[equipment_id]["part_ids"]
            }
            self.assertGreaterEqual(len(equipment_materials), 3)
            self.assertNotIn("concrete", equipment_materials)

    def test_pavilion_glazing_is_above_rc_enclosure_and_passage_has_real_rc_roof(self) -> None:
        package = compile_small_subway()
        artifact = package.artifacts[0]
        circulation = package.geometry_manifest["subway_circulation"]
        rc_bounds = circulation["below_grade_rc_enclosure_bounds_m"]
        pavilion_bounds = circulation["pavilion_validation_bounds_m"]

        self.assertLess(rc_bounds[5], pavilion_bounds[5])
        self.assertFalse(
            artifact.solid_contains_point(tuple(circulation["pavilion_glazing_void_probe_m"]))
        )
        self.assertTrue(
            artifact.solid_contains_point(tuple(circulation["passage_roof_probe_m"]))
        )

    def test_pavilion_roof_frame_and_plinth_form_one_real_load_path(self) -> None:
        artifact = compile_small_subway().artifacts[0]
        roof_ids = {
            row.element_id
            for row in artifact.mesh.shells
            if row.part_role == "pavilion_metal_roof"
        }
        frame_ids = {
            row.element_id
            for row in artifact.mesh.beams
            if row.part_role == "pavilion_frame"
        }
        plinth_ids = {
            row.element_id
            for row in artifact.mesh.solids
            if row.part_role == "pavilion_rc_plinth"
        }
        self.assertTrue(roof_ids and frame_ids and plinth_ids)

        elements = {
            row.element_id: row
            for row in (
                *artifact.mesh.solids,
                *artifact.mesh.shells,
                *artifact.mesh.beams,
            )
            if row.element_id in roof_ids | frame_ids | plinth_ids
        }
        elements_by_node: dict[int, set[int]] = {}
        for element_id, element in elements.items():
            for node_id in element.node_ids:
                elements_by_node.setdefault(node_id, set()).add(element_id)
        adjacency: dict[int, set[int]] = {element_id: set() for element_id in elements}
        for touching in elements_by_node.values():
            for element_id in touching:
                adjacency[element_id].update(touching - {element_id})

        roof_root = min(roof_ids)
        reachable = {roof_root}
        pending = [roof_root]
        while pending:
            current = pending.pop()
            for neighbor in adjacency[current]:
                if neighbor not in reachable:
                    reachable.add(neighbor)
                    pending.append(neighbor)
        self.assertEqual(roof_ids | frame_ids | plinth_ids, reachable)

        nodes = {row.node_id: row.coordinates for row in artifact.mesh.nodes}
        column_frame_ids = {
            beam.element_id
            for beam in artifact.mesh.beams
            if beam.part_role == "pavilion_frame"
            and all(
                abs(nodes[beam.node_ids[0]][axis] - nodes[beam.node_ids[1]][axis])
                <= 1.0e-9
                for axis in (0, 1)
            )
        }
        vertical_frames = [
            beam
            for beam in artifact.mesh.beams
            if beam.part_role == "pavilion_frame"
            and beam.element_id in column_frame_ids
        ]
        frame_rail_ids = frame_ids - column_frame_ids
        for column in vertical_frames:
            top_node = max(column.node_ids, key=lambda node_id: nodes[node_id][2])
            self.assertTrue(
                any(
                    top_node in elements[element_id].node_ids
                    for element_id in frame_rail_ids
                )
            )

        roof_connection = artifact.connections_by_type("roof_to_frame")
        base_connection = artifact.connections_by_type("frame_to_plinth")
        self.assertTrue(roof_connection)
        self.assertTrue(base_connection)
        for connection, minimum_shared_nodes in (
            (roof_connection[0], 2),
            (base_connection[0], 1),
        ):
            sources = [elements[element_id] for element_id in connection.source_element_ids]
            targets = [elements[element_id] for element_id in connection.target_element_ids]
            self.assertTrue(sources and targets)
            self.assertTrue(
                all(
                    any(
                        len(set(source.node_ids) & set(target.node_ids))
                        >= minimum_shared_nodes
                        for target in targets
                    )
                    for source in sources
                )
            )

    def test_plinth_rebar_is_embedded_and_concrete_only_removes_it(self) -> None:
        reinforced = compile_small_subway().artifacts[0]
        concrete_only = compile_small_subway(
            generation_options={
                "reinforcement_mode": "concrete_only",
                "rebar_spacing_m": 0.50,
            }
        ).artifacts[0]
        plinth_rebar = {
            beam.element_id
            for beam in reinforced.mesh.beams
            if beam.part_role == "plinth_rebar"
        }
        embedded = {
            element_id
            for connection in reinforced.connections_by_type("embedded_rebar")
            for element_id in connection.source_element_ids
        }
        self.assertTrue(plinth_rebar)
        self.assertTrue(plinth_rebar <= embedded)
        self.assertNotIn("plinth_rebar", _beam_roles(concrete_only))

    def test_approved_topology_and_roles_are_invariant_across_fidelity_modes(self) -> None:
        packages = [
            compile_small_subway(fidelity_profile=profile)
            for profile in ("structural_core", "blast_response", "research_detailed")
        ]
        reference = packages[0].geometry_manifest["subway_circulation"]
        for package in packages[1:]:
            circulation = package.geometry_manifest["subway_circulation"]
            self.assertEqual(reference["fixed_stair_count"], circulation["fixed_stair_count"])
            self.assertEqual(reference["escalator_count"], circulation["escalator_count"])
            self.assertEqual(reference["longitudinal_route"], circulation["longitudinal_route"])
            self.assertEqual(reference["component_roles"], circulation["component_roles"])
            self.assertEqual(reference["passage_probe_m"], circulation["passage_probe_m"])

    def test_subway_parameters_reject_bad_dimensions_overlap_narrow_passage_and_extra_route(self) -> None:
        invalid_options = (
            ({"stair_width_m": 0.0}, "stair_width_m"),
            ({"escalator_width_m": -1.0}, "escalator_width_m"),
            ({"pavilion_roof_arc_rise_m": float("nan")}, "pavilion_roof_arc_rise_m"),
            (
                {"stair_width_m": 2.0, "escalator_width_m": 1.0, "lane_gap_m": 0.20},
                "lane envelopes",
            ),
            (
                {"passage_clear_width_m": 1.0},
                "passage_clear_width_m",
            ),
            ({"pavilion_length_m": 6.0}, "pavilion_length_m"),
            ({"passage_turn_deg": 90.0}, "turn"),
            ({"additional_stair_count": 1}, "additional"),
            ({"additional_escalator_count": 1}, "additional"),
        )
        for options, message in invalid_options:
            with self.subTest(options=options):
                with self.assertRaisesRegex(ValueError, message):
                    compile_small_subway(
                        generation_options={"rebar_spacing_m": 0.50, **options}
                    )

    def test_rc_box_uses_distinct_platform_wall_roof_thicknesses_and_real_passage(self) -> None:
        package = compile_small_subway()
        artifact = package.artifacts[0]
        parameters = artifact.normalized_input["structural_system"]["parameters"]

        self.assertEqual("rc_box", artifact.system_id)
        self.assertEqual(SMALL_SUBWAY["platform_height_m"], parameters["floor_thickness_m"])
        self.assertEqual(SMALL_SUBWAY["wall_thickness_m"], parameters["wall_thickness_m"])
        self.assertEqual(SMALL_SUBWAY["roof_thickness_m"], parameters["roof_thickness_m"])
        circulation = package.geometry_manifest["subway_circulation"]
        self.assertFalse(artifact.solid_contains_point(tuple(circulation["passage_probe_m"])))
        self.assertTrue(artifact.solid_contains_point(tuple(circulation["passage_wall_probe_m"])))
        self.assertFalse(artifact.solid_contains_point((0.1, 1.5, 1.5)))
        self.assertTrue(artifact.solid_contains_point((2.0, 0.10, 1.5)))
        self.assertIn(
            "exterior", artifact.topology_manifest["adjacency"]["entrance_passage"]
        )

    def test_front_opening_cuts_wall_rebar_but_preserves_side_and_back_wall_rebar(self) -> None:
        package = compile_small_subway()
        artifact = package.artifacts[0]
        self.assertIn("wall_rebar", _beam_roles(artifact))
        nodes = {row.node_id: row.coordinates for row in artifact.mesh.nodes}
        wall_beams = [row for row in artifact.mesh.beams if row.part_role == "wall_rebar"]
        self.assertTrue(
            any(
                all(nodes[node_id][1] < 0.21 for node_id in beam.node_ids)
                for beam in wall_beams
            )
        )
        self.assertTrue(
            any(
                all(nodes[node_id][1] > 2.79 for node_id in beam.node_ids)
                for beam in wall_beams
            )
        )
        self.assertFalse(
            any(
                all(nodes[node_id][0] < 0.21 for node_id in beam.node_ids)
                and all(0.21 < nodes[node_id][1] < 2.79 for node_id in beam.node_ids)
                and any(0.31 < nodes[node_id][2] < 2.69 for node_id in beam.node_ids)
                for beam in wall_beams
            )
        )

    def test_fidelity_panels_never_cover_the_front_opening(self) -> None:
        core = compile_small_subway(fidelity_profile="structural_core")
        blast = compile_small_subway(fidelity_profile="blast_response")
        research = compile_small_subway(fidelity_profile="research_detailed")
        self.assertLess(len(core.artifacts[0].mesh.shells), len(blast.artifacts[0].mesh.shells))
        self.assertLessEqual(
            len(blast.artifacts[0].mesh.shells),
            len(research.artifacts[0].mesh.shells),
        )
        opening = next(
            row
            for row in blast.artifacts[0].normalized_input["openings"]
            if row["id"] == "front_entrance"
        )["bounds_m"]
        for package in (blast, research):
            artifact = package.artifacts[0]
            for shell in artifact.mesh.shells:
                centroid = _shell_centroid(artifact, shell)
                self.assertFalse(
                    all(
                        opening[axis] - 1.0e-12
                        <= centroid[axis]
                        <= opening[axis + 3] + 1.0e-12
                        for axis in range(3)
                    )
                )

    def test_concrete_only_and_alternative_system_compile_through_same_api(self) -> None:
        concrete_only = compile_small_subway(
            generation_options={
                "reinforcement_mode": "concrete_only",
                "rebar_spacing_m": 0.50,
            }
        )
        alternative = compile_small_subway(structural_system="rc_frame_shear_wall")
        artifact = concrete_only.artifacts[0]
        self.assertGreater(len(artifact.mesh.solids), 0)
        self.assertFalse(_beam_roles(artifact) & {"foundation_rebar", "wall_rebar", "slab_rebar"})
        self.assertIn("pavilion_frame", _beam_roles(artifact))
        self.assertFalse(artifact.connections_by_type("embedded_rebar"))
        self.assertEqual("rc_frame_shear_wall", alternative.artifacts[0].system_id)

    def test_rc_box_and_frame_shear_wall_have_distinct_final_structure(self) -> None:
        rc_box = compile_small_subway().artifacts[0]
        frame_wall = compile_small_subway(
            structural_system="rc_frame_shear_wall"
        ).artifacts[0]

        box_roles = {row.part_role for row in rc_box.mesh.solids}
        frame_roles = {row.part_role for row in frame_wall.mesh.solids}
        self.assertIn("rc_frame_column", frame_roles)
        self.assertIn("rc_frame_roof_beam", frame_roles)
        self.assertNotEqual(box_roles, frame_roles)
        self.assertNotEqual(rc_box.mesh.fingerprint, frame_wall.mesh.fingerprint)
        self.assertNotEqual(rc_box.connections, frame_wall.connections)
        frame_connections = frame_wall.connections_by_type("frame_to_shear_wall")
        self.assertTrue(frame_connections)
        elements = {row.element_id: row for row in frame_wall.mesh.solids}
        connection = frame_connections[0]
        self.assertTrue(
            all(
                any(
                    len(
                        set(elements[source_id].node_ids)
                        & set(elements[target_id].node_ids)
                    )
                    >= 4
                    for target_id in connection.target_element_ids
                )
                for source_id in connection.source_element_ids
            )
        )

    def test_frame_connections_use_exact_structural_roles_and_shared_faces(self) -> None:
        artifact = compile_small_subway(
            structural_system="rc_frame_shear_wall"
        ).artifacts[0]
        elements = {row.element_id: row for row in artifact.mesh.solids}
        expected_roles = {
            "frame_to_shear_wall": (
                {"rc_frame_column"},
                {"rc_box_wall"},
            ),
            "column_to_floor": (
                {"rc_frame_column"},
                {"rc_box_floor"},
            ),
            "roof_beam_to_roof": (
                {"rc_frame_roof_beam"},
                {"rc_box_roof"},
            ),
        }
        for connection_type, (source_roles, target_roles) in expected_roles.items():
            with self.subTest(connection_type=connection_type):
                connections = artifact.connections_by_type(connection_type)
                self.assertEqual(1, len(connections))
                connection = connections[0]
                self.assertEqual(
                    source_roles,
                    {
                        elements[element_id].part_role
                        for element_id in connection.source_element_ids
                    },
                )
                self.assertEqual(
                    target_roles,
                    {
                        elements[element_id].part_role
                        for element_id in connection.target_element_ids
                    },
                )
                self.assertTrue(
                    all(
                        any(
                            len(
                                set(elements[source_id].node_ids)
                                & set(elements[target_id].node_ids)
                            )
                            >= 4
                            for target_id in connection.target_element_ids
                        )
                        for source_id in connection.source_element_ids
                    )
                )
                self.assertTrue(
                    all(
                        any(
                            len(
                                set(elements[source_id].node_ids)
                                & set(elements[target_id].node_ids)
                            )
                            >= 4
                            for source_id in connection.source_element_ids
                        )
                        for target_id in connection.target_element_ids
                    )
                )

    def test_independent_stair_slope_and_landing_clear_widths_change_solids(self) -> None:
        baseline = compile_small_subway().artifacts[0]
        custom = compile_small_subway(
            generation_options={
                "rebar_spacing_m": 0.50,
                "fixed_stair_slope_deg": 40.0,
                "upper_landing_clear_width_m": 2.52,
                "lower_landing_clear_width_m": 2.54,
            }
        ).artifacts[0]

        def role_bounds(artifact: object, role: str) -> tuple[float, ...]:
            nodes = {row.node_id: row.coordinates for row in artifact.mesh.nodes}  # type: ignore[attr-defined]
            solids = [
                row
                for row in artifact.mesh.solids  # type: ignore[attr-defined]
                if row.part_role == role
            ]
            self.assertTrue(solids)
            coordinates = [nodes[node_id] for row in solids for node_id in row.node_ids]
            return tuple(
                min(point[axis] for point in coordinates)
                for axis in range(3)
            ) + tuple(
                max(point[axis] for point in coordinates)
                for axis in range(3)
            )

        baseline_stair = role_bounds(baseline, "fixed_stair_A")
        custom_stair = role_bounds(custom, "fixed_stair_A")
        self.assertGreater(custom_stair[0], baseline_stair[0] + 0.50)
        upper = role_bounds(custom, "upper_landing")
        lower = role_bounds(custom, "lower_landing_8")
        self.assertAlmostEqual(2.52, upper[4] - upper[1], places=9)
        self.assertAlmostEqual(2.54, lower[4] - lower[1], places=9)
        self.assertNotEqual(baseline.mesh.fingerprint, custom.mesh.fingerprint)

    def test_stair_rebar_controls_and_connection_level_are_artifact_non_noops(self) -> None:
        baseline = compile_small_subway().artifacts[0]

        def beam_signature(artifact: object, role: str) -> tuple[object, ...]:
            nodes = {row.node_id: row.coordinates for row in artifact.mesh.nodes}  # type: ignore[attr-defined]
            return tuple(
                sorted(
                    tuple(nodes[node_id] for node_id in beam.node_ids)
                    for beam in artifact.mesh.beams  # type: ignore[attr-defined]
                    if beam.part_role == role
                )
            )

        cases = (
            (
                {"fixed_stair_longitudinal_spacing_m": 0.22},
                "fixed_stair_rebar",
            ),
            (
                {"fixed_stair_distribution_spacing_m": 0.08},
                "fixed_stair_distribution_rebar",
            ),
            (
                {"fixed_stair_local_densification_factor": 3.0},
                "fixed_stair_local_rebar",
            ),
        )
        for option, role in cases:
            with self.subTest(option=option):
                changed = compile_small_subway(
                    generation_options={"rebar_spacing_m": 0.50, **option}
                ).artifacts[0]
                self.assertTrue(beam_signature(baseline, role))
                self.assertNotEqual(
                    beam_signature(baseline, role),
                    beam_signature(changed, role),
                )

        role_resolved = compile_small_subway(
            generation_options={
                "rebar_spacing_m": 0.50,
                "connection_simplification_level": "role_resolved",
            }
        ).artifacts[0]
        baseline_ties = baseline.connections_by_type("tied_structural_interface")
        resolved_ties = role_resolved.connections_by_type(
            "tied_structural_interface"
        )
        self.assertGreater(len(resolved_ties), len(baseline_ties))
        self.assertNotEqual(baseline_ties, resolved_ties)

    def test_new_subway_review_controls_fail_closed(self) -> None:
        invalid_cases = (
            ({"fixed_stair_slope_deg": 5.0}, "fixed_stair_slope_deg"),
            ({"upper_landing_clear_width_m": 2.0}, "upper_landing_clear_width_m"),
            ({"lower_landing_clear_width_m": 3.0}, "lower_landing_clear_width_m"),
            ({"fixed_stair_longitudinal_spacing_m": 0.0}, "fixed_stair_longitudinal_spacing_m"),
            ({"fixed_stair_distribution_spacing_m": -0.1}, "fixed_stair_distribution_spacing_m"),
            ({"fixed_stair_local_densification_factor": 0.5}, "fixed_stair_local_densification_factor"),
            ({"connection_simplification_level": "none"}, "connection_simplification_level"),
        )
        for options, message in invalid_cases:
            with self.subTest(options=options):
                with self.assertRaisesRegex(ValueError, message):
                    compile_small_subway(
                        generation_options={"rebar_spacing_m": 0.50, **options}
                    )

    def test_exact_preflight_and_fingerprint_invalidation_cover_subway_parameters(self) -> None:
        package = compile_small_subway()
        count = package.mesh_manifest["actual_solid_elements"]
        self.assertEqual(count, package.mesh_manifest["predicted_solid_elements"])
        self.assertEqual("exact", package.mesh_manifest["solid_estimate_kind"])
        with self.assertRaisesRegex(ValueError, "exceeds limit"):
            compile_small_subway(
                generation_options={
                    "max_solid_elements": count - 1,
                    "rebar_spacing_m": 0.50,
                }
            )
        accepted = compile_small_subway(
            generation_options={
                "max_solid_elements": count,
                "rebar_spacing_m": 0.50,
            }
        )
        changed_geometry = dict(SMALL_SUBWAY, roof_thickness_m=0.25)
        changed = compile_detailed_building_asset(
            SUBWAY_ID,
            legacy_geometry=changed_geometry,
            mesh_profile="coarse",
            generation_options={"rebar_spacing_m": 0.50},
        )
        concrete_only = compile_small_subway(
            generation_options={
                "reinforcement_mode": "concrete_only",
                "rebar_spacing_m": 0.50,
            }
        )
        self.assertEqual(count, accepted.mesh_manifest["actual_solid_elements"])
        self.assertNotEqual(package.fingerprint, changed.fingerprint)
        self.assertNotEqual(package.fingerprint, concrete_only.fingerprint)


if __name__ == "__main__":
    unittest.main()
