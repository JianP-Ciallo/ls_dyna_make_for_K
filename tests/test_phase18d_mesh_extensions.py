from __future__ import annotations

import unittest
import math
from unittest.mock import patch

from lsprepost_mcp.refined_building.compiler import compile_refined_building
from lsprepost_mcp.refined_building.contracts import (
    default_building_definition,
    normalize_building_definition,
)
from lsprepost_mcp.refined_building.meshing import mesh_axis_aligned_union
from lsprepost_mcp.refined_building.reinforcement import (
    REINFORCEMENT_ROLES,
    generate_reinforcement,
)
from lsprepost_mcp.refined_building.spatial import AxisAlignedBox


class Phase18DContractAndSparseUnionTests(unittest.TestCase):
    def test_fidelity_profiles_accept_exact_catalog_and_reject_unknown_values(self) -> None:
        for profile in ("structural_core", "blast_response", "research_detailed"):
            with self.subTest(profile=profile):
                value = default_building_definition()
                value["fidelity_profile"] = profile
                self.assertEqual(
                    profile,
                    normalize_building_definition(value)["fidelity_profile"],
                )

        value = default_building_definition()
        value["fidelity_profile"] = "ultra"
        with self.assertRaisesRegex(ValueError, "unsupported fidelity_profile"):
            normalize_building_definition(value)

    def test_sparse_union_keeps_literal_mesh_order_and_fingerprint(self) -> None:
        members = (
            ("base", AxisAlignedBox(0.0, 0.0, 0.0, 1.0, 0.5, 0.25)),
            ("wall", AxisAlignedBox(0.75, 0.0, 0.0, 1.0, 0.5, 1.0)),
        )

        fragment = mesh_axis_aligned_union(members, 0.25, role_priority={"wall": 1})

        self.assertEqual(48, len(fragment.nodes))
        self.assertEqual(14, len(fragment.solids))
        self.assertEqual((1, 2, 3, 4, 5, 6, 7, 8), fragment.solids[0].node_ids)
        self.assertEqual("base", fragment.solids[0].part_role)
        self.assertEqual("wall", fragment.solids[-1].part_role)
        self.assertEqual(
            "f4555b1d1c3dcfb6e8a4a965e7f94c9e134e66e1e1e7f4bc54cbe643a4423916",
            fragment.fingerprint,
        )

    def test_sparse_union_indexes_members_without_cell_contains_scans(self) -> None:
        members = (
            ("left", AxisAlignedBox(0.0, 0.0, 0.0, 1.0, 1.0, 1.0)),
            ("right", AxisAlignedBox(2.0, 0.0, 0.0, 3.0, 1.0, 1.0)),
        )

        with patch.object(
            AxisAlignedBox,
            "contains_point",
            side_effect=AssertionError("dense occupancy scan"),
        ):
            fragment = mesh_axis_aligned_union(members, 0.25)

        self.assertEqual(250, len(fragment.nodes))
        self.assertEqual(128, len(fragment.solids))

    def test_sparse_union_preserves_exclusion_boundary_literal_rows(self) -> None:
        fragment = mesh_axis_aligned_union(
            (("block", AxisAlignedBox(0.0, 0.0, 0.0, 1.0, 1.0, 1.0)),),
            0.5,
            (AxisAlignedBox(0.5, 0.0, 0.0, 1.0, 0.5, 0.5),),
        )

        self.assertEqual(26, len(fragment.nodes))
        self.assertEqual(
            (
                (1, (1, 2, 3, 4, 5, 6, 7, 8), "block"),
                (2, (4, 3, 9, 10, 8, 7, 11, 12), "block"),
                (3, (3, 13, 14, 9, 7, 15, 16, 11), "block"),
                (4, (5, 6, 7, 8, 17, 18, 19, 20), "block"),
                (5, (6, 21, 15, 7, 18, 22, 23, 19), "block"),
                (6, (8, 7, 11, 12, 20, 19, 24, 25), "block"),
                (7, (7, 15, 16, 11, 19, 23, 26, 24), "block"),
            ),
            tuple(
                (solid.element_id, solid.node_ids, solid.part_role)
                for solid in fragment.solids
            ),
        )

    def test_sparse_union_preserves_role_priority_overlap_literal_rows(self) -> None:
        fragment = mesh_axis_aligned_union(
            (
                ("base", AxisAlignedBox(0.0, 0.0, 0.0, 1.0, 1.0, 1.0)),
                ("cap", AxisAlignedBox(0.5, 0.0, 0.0, 1.0, 1.0, 1.0)),
            ),
            0.5,
            role_priority={"cap": 1},
        )

        self.assertEqual(27, len(fragment.nodes))
        self.assertEqual(
            (
                (1, (1, 2, 3, 4, 5, 6, 7, 8), "base"),
                (2, (2, 9, 10, 3, 6, 11, 12, 7), "cap"),
                (3, (4, 3, 13, 14, 8, 7, 15, 16), "base"),
                (4, (3, 10, 17, 13, 7, 12, 18, 15), "cap"),
                (5, (5, 6, 7, 8, 19, 20, 21, 22), "base"),
                (6, (6, 11, 12, 7, 20, 23, 24, 21), "cap"),
                (7, (8, 7, 15, 16, 22, 21, 25, 26), "base"),
                (8, (7, 12, 18, 15, 21, 24, 27, 25), "cap"),
            ),
            tuple(
                (solid.element_id, solid.node_ids, solid.part_role)
                for solid in fragment.solids
            ),
        )


class Phase18DBeamSubdivisionTests(unittest.TestCase):
    def test_rebar_target_length_subdivides_every_reinforcement_role(self) -> None:
        members = (
            ("rc_column", AxisAlignedBox(0.0, 0.0, 0.0, 0.4, 0.4, 1.4)),
            ("rc_beam_x", AxisAlignedBox(2.0, 0.0, 0.0, 3.4, 0.4, 0.4)),
            ("rc_slab", AxisAlignedBox(4.0, 0.0, 0.0, 5.4, 1.4, 0.2)),
            ("rc_shear_wall", AxisAlignedBox(6.0, 0.0, 0.0, 6.2, 1.4, 1.4)),
            ("rc_foundation", AxisAlignedBox(8.0, 0.0, 0.0, 9.4, 1.4, 0.2)),
        )
        parameters = {
            "cover_m": 0.05,
            "bar_diameter_m": 0.02,
            "rebar_spacing_m": 0.5,
            "rebar_target_length_m": 0.3,
        }

        fragment = generate_reinforcement(members, parameters, REINFORCEMENT_ROLES)

        self.assertIsNotNone(fragment)
        assert fragment is not None
        self.assertEqual(REINFORCEMENT_ROLES, {beam.part_role for beam in fragment.beams})
        self.assertLessEqual(_maximum_beam_length(fragment), 0.3 + 1e-12)
        self.assertEqual((0.05, 0.05, 0.05), fragment.nodes[0].coordinates)
        self.assertTrue(
            any(
                math.dist(node.coordinates, (0.05, 0.05, 1.35)) <= 1e-12
                for node in fragment.nodes
            )
        )

    def test_rebar_target_absent_preserves_one_segment_per_straight_grid_line(self) -> None:
        member = (("rc_foundation", AxisAlignedBox(0.0, 0.0, 0.0, 1.0, 1.0, 0.2)),)

        coarse = generate_reinforcement(
            member,
            {"cover_m": 0.04, "bar_diameter_m": 0.016, "rebar_spacing_m": 10.0},
            frozenset({"foundation_rebar"}),
        )
        refined = generate_reinforcement(
            member,
            {
                "cover_m": 0.04,
                "bar_diameter_m": 0.016,
                "rebar_spacing_m": 10.0,
                "rebar_target_length_m": 0.3,
            },
            frozenset({"foundation_rebar"}),
        )

        assert coarse is not None and refined is not None
        self.assertEqual(4, len(coarse.beams))
        self.assertEqual(16, len(refined.beams))
        self.assertEqual(coarse.bounds_m, refined.bounds_m)

    def test_rebar_subdivision_preserves_original_endpoints_exactly(self) -> None:
        member = (
            (
                "rc_column",
                AxisAlignedBox(0.0, 0.0, -1.04, 0.42, 0.42, -0.62),
            ),
        )
        parameters = {
            "cover_m": 0.04,
            "bar_diameter_m": 0.016,
            "rebar_spacing_m": 10.0,
        }

        coarse = generate_reinforcement(
            member, parameters, frozenset({"column_longitudinal"})
        )
        refined = generate_reinforcement(
            member,
            {**parameters, "rebar_target_length_m": 0.12},
            frozenset({"column_longitudinal"}),
        )

        assert coarse is not None and refined is not None
        self.assertTrue(
            {node.coordinates for node in coarse.nodes}
            <= {node.coordinates for node in refined.nodes}
        )

    def test_rebar_exclusions_filter_original_lines_before_subdivision(self) -> None:
        member = (("rc_foundation", AxisAlignedBox(0.0, 0.0, 0.0, 1.0, 1.0, 0.2)),)
        exclusion = (AxisAlignedBox(0.4, 0.0, 0.0, 0.6, 1.0, 0.2),)
        parameters = {
            "cover_m": 0.04,
            "bar_diameter_m": 0.016,
            "rebar_spacing_m": 10.0,
        }

        coarse = generate_reinforcement(
            member,
            parameters,
            frozenset({"foundation_rebar"}),
            exclusion,
        )
        refined = generate_reinforcement(
            member,
            {**parameters, "rebar_target_length_m": 0.2},
            frozenset({"foundation_rebar"}),
            exclusion,
        )

        assert coarse is not None and refined is not None
        self.assertEqual(2, len(coarse.beams))
        self.assertEqual(10, len(refined.beams))
        self.assertEqual(
            {0.04, 0.96},
            {node.x for node in refined.nodes},
        )

    def test_rebar_target_length_rejects_invalid_values(self) -> None:
        member = (("rc_foundation", AxisAlignedBox(0.0, 0.0, 0.0, 1.0, 1.0, 0.2)),)
        for invalid in (True, 0.0, -0.1, math.nan, math.inf):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(
                    ValueError, "rebar_target_length_m must be a positive finite number"
                ):
                    generate_reinforcement(
                        member,
                        {"rebar_target_length_m": invalid},
                        frozenset({"foundation_rebar"}),
                    )

    def test_steel_member_target_subdivides_members_and_reuses_joint_endpoints(self) -> None:
        coarse_value = default_building_definition(structural_system="steel_frame")
        refined_value = default_building_definition(structural_system="steel_frame")
        refined_value["structural_system"]["parameters"] = {
            "member_target_length_m": 1.0
        }

        coarse = compile_refined_building(coarse_value)
        refined = compile_refined_building(refined_value)

        self.assertEqual((18, 21, 4), (
            len(coarse.mesh.nodes),
            len(coarse.mesh.beams),
            len(coarse.mesh.shells),
        ))
        self.assertEqual((60, 63, 4), (
            len(refined.mesh.nodes),
            len(refined.mesh.beams),
            len(refined.mesh.shells),
        ))
        self.assertLessEqual(_maximum_beam_length(refined.mesh), 1.0 + 1e-12)
        joint_ids = {
            node.node_id
            for node in refined.mesh.nodes
            if node.x in (0.0, 3.0, 6.0)
            and node.y in (0.0, 3.0, 6.0)
            and node.z in (0.0, 3.0)
        }
        self.assertEqual(18, len(joint_ids))
        self.assertTrue(
            all(set(shell.node_ids) <= joint_ids for shell in refined.mesh.shells)
        )

    def test_steel_member_target_rejects_invalid_values(self) -> None:
        for invalid in (True, 0.0, -0.1, math.nan, math.inf):
            with self.subTest(invalid=invalid):
                value = default_building_definition(structural_system="steel_frame")
                value["structural_system"]["parameters"] = {
                    "member_target_length_m": invalid
                }
                with self.assertRaises(ValueError):
                    compile_refined_building(value)


class Phase18DHybridAndRCBoxTests(unittest.TestCase):
    def test_hybrid_full_reinforced_adds_foundation_slab_and_separate_connection(self) -> None:
        value = default_building_definition(structural_system="steel_concrete_hybrid")
        value["structural_system"]["parameters"] = {
            "concrete_reinforcement": {
                "mode": "full_reinforced",
                "include_roles": ["foundation_rebar", "slab_rebar"],
                "cover_m": 0.04,
                "bar_diameter_m": 0.016,
                "rebar_spacing_m": 0.30,
                "rebar_target_length_m": 0.50,
            }
        }

        artifact = compile_refined_building(value)

        self.assertEqual(
            {"foundation_rebar", "slab_rebar"},
            {
                beam.part_role
                for beam in artifact.mesh.beams
                if beam.part_role.endswith("_rebar")
            },
        )
        self.assertEqual(
            {"steel_connection", "composite_interface", "embedded_rebar"},
            {connection.connection_type for connection in artifact.connections},
        )
        self.assertEqual(
            (
                "hybrid_steel_joints",
                "hybrid_composite_interface",
                "hybrid_embedded_rebar",
            ),
            tuple(connection.connection_id for connection in artifact.connections),
        )
        steel_element_ids = {
            beam.element_id
            for beam in artifact.mesh.beams
            if beam.part_role in {"steel_column", "steel_beam"}
        }
        self.assertEqual(
            steel_element_ids,
            set(artifact.connections_by_type("steel_connection")[0].source_element_ids),
        )
        self.assertEqual(
            steel_element_ids,
            set(artifact.connections_by_type("composite_interface")[0].source_element_ids),
        )
        rebar_beams = tuple(
            beam for beam in artifact.mesh.beams if beam.part_role.endswith("_rebar")
        )
        self.assertLessEqual(
            _maximum_beam_length_for_rows(artifact.mesh, rebar_beams),
            0.50 + 1e-12,
        )
        embedded = artifact.connections_by_type("embedded_rebar")
        self.assertEqual(1, len(embedded))
        self.assertEqual(
            {beam.element_id for beam in artifact.mesh.beams if beam.part_role.endswith("_rebar")},
            set(embedded[0].source_element_ids),
        )

    def test_hybrid_concrete_only_and_absent_mapping_omit_rc_rebar(self) -> None:
        absent_value = default_building_definition(
            structural_system="steel_concrete_hybrid"
        )
        concrete_only_value = default_building_definition(
            structural_system="steel_concrete_hybrid"
        )
        concrete_only_value["structural_system"]["parameters"] = {
            "concrete_reinforcement": {"mode": "concrete_only"}
        }

        absent = compile_refined_building(absent_value)
        concrete_only = compile_refined_building(concrete_only_value)

        for artifact in (absent, concrete_only):
            self.assertFalse(
                {"foundation_rebar", "slab_rebar"}
                & {beam.part_role for beam in artifact.mesh.beams}
            )
            self.assertFalse(artifact.connections_by_type("embedded_rebar"))

    def test_hybrid_custom_reinforcement_selects_only_declared_subset(self) -> None:
        value = default_building_definition(structural_system="steel_concrete_hybrid")
        value["structural_system"]["parameters"] = {
            "concrete_reinforcement": {
                "mode": "custom",
                "include_roles": ["foundation_rebar"],
            }
        }

        artifact = compile_refined_building(value)

        self.assertIn("foundation_rebar", {beam.part_role for beam in artifact.mesh.beams})
        self.assertNotIn("slab_rebar", {beam.part_role for beam in artifact.mesh.beams})

    def test_hybrid_reinforcement_contract_rejects_invalid_modes_and_roles(self) -> None:
        invalid_rows = (
            ([], "must be a mapping"),
            ({"mode": "other"}, "unsupported concrete_reinforcement mode"),
            ({"mode": "custom"}, "include_roles must be a list"),
            ({"mode": "custom", "include_roles": "foundation_rebar"}, "include_roles must be a list"),
            ({"mode": "custom", "include_roles": ["wall_rebar"]}, "unknown concrete reinforcement roles"),
        )
        for mapping, message in invalid_rows:
            with self.subTest(mapping=mapping):
                value = default_building_definition(
                    structural_system="steel_concrete_hybrid"
                )
                value["structural_system"]["parameters"] = {
                    "concrete_reinforcement": mapping
                }
                with self.assertRaisesRegex(ValueError, message):
                    compile_refined_building(value)

    def test_hybrid_no_role_modes_reject_every_explicit_invalid_rebar_number(self) -> None:
        mode_rows = (
            {"mode": "concrete_only"},
            {"mode": "custom", "include_roles": []},
        )
        for mode_row in mode_rows:
            for key in ("cover_m", "bar_diameter_m", "rebar_spacing_m"):
                for invalid in (True, 0.0, -0.1, math.nan, math.inf):
                    with self.subTest(mode=mode_row["mode"], key=key, invalid=invalid):
                        value = default_building_definition(
                            structural_system="steel_concrete_hybrid"
                        )
                        value["structural_system"]["parameters"] = {
                            "concrete_reinforcement": {**mode_row, key: invalid}
                        }
                        with self.assertRaises(ValueError):
                            compile_refined_building(value)

    def test_hybrid_passes_member_target_to_internal_steel_frame(self) -> None:
        value = default_building_definition(structural_system="steel_concrete_hybrid")
        value["structural_system"]["parameters"] = {
            "member_target_length_m": 1.0
        }

        artifact = compile_refined_building(value)
        steel_beams = tuple(
            beam
            for beam in artifact.mesh.beams
            if beam.part_role in {"steel_column", "steel_beam"}
        )

        self.assertEqual(63, len(steel_beams))
        self.assertLessEqual(
            _maximum_beam_length_for_rows(artifact.mesh, steel_beams),
            1.0 + 1e-12,
        )

    def test_generation_mode_remains_unsupported_for_steel_and_hybrid(self) -> None:
        for system_id in ("steel_frame", "steel_concrete_hybrid"):
            with self.subTest(system_id=system_id):
                value = default_building_definition(structural_system=system_id)
                value["structural_system"]["parameters"] = {
                    "generation_mode": "concrete_only"
                }
                with self.assertRaisesRegex(ValueError, "generation_mode is not supported"):
                    compile_refined_building(value)

    def test_rc_box_uses_distinct_floor_wall_and_roof_thicknesses(self) -> None:
        value = default_building_definition(structural_system="rc_box")
        value["structural_system"]["parameters"] = {
            "generation_mode": "concrete_only",
            "mesh_size_m": 0.5,
            "floor_thickness_m": 0.30,
            "wall_thickness_m": 0.20,
            "roof_thickness_m": 0.15,
        }

        artifact = compile_refined_building(value)

        self.assertEqual(
            (0.0, 0.30),
            _role_axis_extents(artifact.mesh, "rc_box_floor", 2),
        )
        self.assertEqual(
            (0.30, 2.85),
            _role_axis_extents(artifact.mesh, "rc_box_wall", 2),
        )
        self.assertEqual(
            (2.85, 3.0),
            _role_axis_extents(artifact.mesh, "rc_box_roof", 2),
        )
        wall_coordinates = {
            coordinate
            for axis in (0, 1)
            for coordinate in _role_axis_coordinates(
                artifact.mesh, "rc_box_wall", axis
            )
        }
        self.assertTrue({0.0, 0.2, 5.8, 6.0} <= wall_coordinates)

    def test_rc_box_thickness_overrides_reject_invalid_values_and_void_collapse(self) -> None:
        for key, invalid in (
            ("floor_thickness_m", True),
            ("floor_thickness_m", 0.0),
            ("wall_thickness_m", -0.1),
            ("roof_thickness_m", math.nan),
            ("roof_thickness_m", math.inf),
        ):
            with self.subTest(key=key, invalid=invalid):
                value = default_building_definition(structural_system="rc_box")
                value["structural_system"]["parameters"] = {key: invalid}
                with self.assertRaises(ValueError):
                    compile_refined_building(value)

        for parameters, message in (
            (
                {"floor_thickness_m": 1.5, "roof_thickness_m": 1.5},
                r"floor_thickness_m \+ roof_thickness_m must be smaller",
            ),
            (
                {"wall_thickness_m": 3.0},
                "wall_thickness_m leaves no x/y internal void",
            ),
        ):
            with self.subTest(parameters=parameters):
                value = default_building_definition(structural_system="rc_box")
                value["structural_system"]["parameters"] = parameters
                with self.assertRaisesRegex(ValueError, message):
                    compile_refined_building(value)


class Phase18DNonstructuralPanelTests(unittest.TestCase):
    def test_panel_mesh_size_builds_literal_shared_grid_and_exterior_min_plane(self) -> None:
        value = _panel_definition(mesh_size_m=0.5, plane_at="min")

        artifact = compile_refined_building(value)
        facade_shells = tuple(
            shell
            for shell in artifact.mesh.shells
            if shell.part_role == "nonstructural_facade"
        )
        facade_node_ids = {
            node_id for shell in facade_shells for node_id in shell.node_ids
        }
        facade_nodes = tuple(
            node for node in artifact.mesh.nodes if node.node_id in facade_node_ids
        )

        self.assertEqual(15, len(facade_nodes))
        self.assertEqual(8, len(facade_shells))
        first_node_id = facade_nodes[0].node_id
        self.assertEqual(
            (first_node_id, first_node_id + 1, first_node_id + 6, first_node_id + 5),
            facade_shells[0].node_ids,
        )
        self.assertEqual(
            (first_node_id + 8, first_node_id + 9, first_node_id + 14, first_node_id + 13),
            facade_shells[-1].node_ids,
        )
        self.assertEqual({0.0}, {node.x for node in facade_nodes})
        self.assertTrue(
            any(
                row["part_role"] == "nonstructural_facade"
                for row in artifact.surface_catalog["exterior_surfaces"]
            )
        )

    def test_panel_plane_at_selects_min_mid_and_max_on_thin_axis(self) -> None:
        for plane_at, expected_x in (("min", 0.0), ("mid", 0.05), ("max", 0.1)):
            with self.subTest(plane_at=plane_at):
                artifact = compile_refined_building(
                    _panel_definition(plane_at=plane_at)
                )
                facade_node_ids = {
                    node_id
                    for shell in artifact.mesh.shells
                    if shell.part_role == "nonstructural_facade"
                    for node_id in shell.node_ids
                }
                self.assertEqual(
                    {expected_x},
                    {
                        node.x
                        for node in artifact.mesh.nodes
                        if node.node_id in facade_node_ids
                    },
                )

    def test_panel_without_options_preserves_single_midpoint_quad(self) -> None:
        artifact = compile_refined_building(_panel_definition())
        facade_shells = tuple(
            shell
            for shell in artifact.mesh.shells
            if shell.part_role == "nonstructural_facade"
        )
        nodes = {node.node_id: node for node in artifact.mesh.nodes}

        self.assertEqual(1, len(facade_shells))
        self.assertEqual(
            (
                (0.05, 1.0, 0.5),
                (0.05, 3.0, 0.5),
                (0.05, 3.0, 1.5),
                (0.05, 1.0, 1.5),
            ),
            tuple(nodes[node_id].coordinates for node_id in facade_shells[0].node_ids),
        )

    def test_panel_options_reject_invalid_mesh_size_and_plane(self) -> None:
        for invalid in (True, 0.0, -0.1, math.nan, math.inf):
            with self.subTest(mesh_size_m=invalid):
                with self.assertRaises(ValueError):
                    compile_refined_building(_panel_definition(mesh_size_m=invalid))
        for invalid in (None, "inside", 1, []):
            with self.subTest(plane_at=invalid):
                with self.assertRaisesRegex(ValueError, "plane_at must be one of"):
                    compile_refined_building(_panel_definition(plane_at=invalid))


class Phase18DCompatibilityTests(unittest.TestCase):
    def test_all_phase18c_default_fingerprints_remain_literal_exact(self) -> None:
        expected = {
            "rc_frame": "48289fc948abd6cd9d6b1df627405a5cee8f91ad35d537321ed22b7a17baa03b",
            "rc_frame_shear_wall": "4f4fd26f4fac7ca607555805f89505b07c79b9752cd0589227067c53bcef6723",
            "steel_frame": "07d1119cdc7bf23848ede68acd644bedaac9594044f682a8fb0c981e5151f150",
            "steel_concrete_hybrid": "8adc42e4beeb973a1515f03e1734a8c782e978d76c322ba4c1b09b90ea3978cf",
            "rc_box": "fa4be2c35728d340da3ea6b97cf259678c018f6cac2f651c76f4ae1ecb6e8262",
        }

        self.assertEqual(
            expected,
            {
                system_id: compile_refined_building(
                    default_building_definition(structural_system=system_id)
                ).fingerprint
                for system_id in expected
            },
        )


def _panel_definition(**options: object) -> dict[str, object]:
    value = default_building_definition(structural_system="rc_frame")
    value["structural_system"]["parameters"] = {"generation_mode": "concrete_only"}
    value["nonstructural"] = [
        {
            "id": "facade_1",
            "kind": "facade",
            "bounds_m": [0.0, 1.0, 0.5, 0.1, 3.0, 1.5],
            "material_role": "facade_panel",
            **options,
        }
    ]
    return value


def _maximum_beam_length(fragment: object) -> float:
    nodes = {node.node_id: node for node in fragment.nodes}  # type: ignore[attr-defined]
    return max(
        math.dist(
            nodes[beam.node_ids[0]].coordinates,
            nodes[beam.node_ids[1]].coordinates,
        )
        for beam in fragment.beams  # type: ignore[attr-defined]
    )


def _maximum_beam_length_for_rows(fragment: object, beams: tuple[object, ...]) -> float:
    nodes = {node.node_id: node for node in fragment.nodes}  # type: ignore[attr-defined]
    return max(
        math.dist(
            nodes[beam.node_ids[0]].coordinates,  # type: ignore[attr-defined]
            nodes[beam.node_ids[1]].coordinates,  # type: ignore[attr-defined]
        )
        for beam in beams
    )


def _role_axis_coordinates(fragment: object, role: str, axis: int) -> set[float]:
    nodes = {node.node_id: node for node in fragment.nodes}  # type: ignore[attr-defined]
    return {
        nodes[node_id].coordinates[axis]
        for solid in fragment.solids  # type: ignore[attr-defined]
        if solid.part_role == role
        for node_id in solid.node_ids
    }


def _role_axis_extents(fragment: object, role: str, axis: int) -> tuple[float, float]:
    coordinates = _role_axis_coordinates(fragment, role, axis)
    return (min(coordinates), max(coordinates))


if __name__ == "__main__":
    unittest.main()
