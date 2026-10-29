from __future__ import annotations

import json
import math
import time
import unittest
from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import lsprepost_mcp.refined_building.surfaces as surface_module
from lsprepost_mcp.refined_building import compile_detailed_building_asset
from lsprepost_mcp.refined_building.artifacts import (
    BuildingArtifact,
    MeshFragment,
    Node,
    PartBinding,
    ShellElement,
    SolidElement,
)
from lsprepost_mcp.refined_building.asset_compiler import _compile_asset_definition
from lsprepost_mcp.refined_building.asset_resources import get_detailed_building_asset
from lsprepost_mcp.refined_building.asset_surfaces import (
    build_refined_asset_surface_catalog,
)
from lsprepost_mcp.refined_building.asset_templates import (
    build_detailed_building_template,
    normalize_asset_geometry,
)
from lsprepost_mcp.refined_building.compiler import compile_refined_building
from lsprepost_mcp.refined_building.contracts import default_building_definition
from lsprepost_mcp.refined_building.spatial import compile_spatial_topology
from lsprepost_mcp.refined_building.surfaces import (
    build_fluid_exposed_surface_catalog,
)
from lsprepost_mcp.refined_building.validation import validate_building_artifact


RESOURCE_ID = "commercial_supermarket_detailed_building"
SMALL_GEOMETRY = {
    "length_m": 6.0,
    "width_m": 4.0,
    "height_m": 3.0,
    "wall_thickness_m": 0.20,
    "entrance_width_m": 2.0,
    "entrance_height_m": 2.0,
}


def compile_small_supermarket(**overrides: object):
    arguments: dict[str, object] = {
        "legacy_geometry": SMALL_GEOMETRY,
        "mesh_profile": "coarse",
    }
    arguments.update(overrides)
    return compile_detailed_building_asset(RESOURCE_ID, **arguments)


def outside_envelope_panel() -> MeshFragment:
    return MeshFragment(
        nodes=(
            Node(1, 100.0, 0.0, 0.0),
            Node(2, 101.0, 0.0, 0.0),
            Node(3, 101.0, 0.0, 1.0),
            Node(4, 100.0, 0.0, 1.0),
        ),
        shells=(
            ShellElement(1, (1, 2, 3, 4), "nonstructural_facade"),
        ),
        part_bindings=(
            PartBinding(
                "nonstructural_facade",
                "facade_material",
                "nonstructural_shell_section",
            ),
        ),
    )


def surface_reference_fixture(
    shell_xy: tuple[tuple[float, float], ...],
    solid_faces_xy: tuple[tuple[tuple[float, float], ...], ...],
    *,
    system_id: str = "steel_concrete_hybrid",
    bottom_z: float = 2.0,
) -> tuple[BuildingArtifact, object]:
    definition = default_building_definition(structural_system=system_id)
    topology = compile_spatial_topology(definition)
    nodes: list[Node] = []
    solids: list[SolidElement] = []
    for element_id, face_xy in enumerate(solid_faces_xy, start=1):
        first_node_id = len(nodes) + 1
        nodes.extend(Node(len(nodes) + 1, x, y, bottom_z) for x, y in face_xy)
        nodes.extend(Node(len(nodes) + 1, x, y, 3.0) for x, y in face_xy)
        solids.append(
            SolidElement(
                element_id,
                tuple(range(first_node_id, first_node_id + 8)),
                "concrete",
            )
        )
    shell_node_ids = tuple(range(len(nodes) + 1, len(nodes) + 5))
    nodes.extend(Node(len(nodes) + 1, x, y, 3.0) for x, y in shell_xy)
    artifact = BuildingArtifact(
        asset_id=f"{system_id}-surface-reference",
        system_id=system_id,
        mesh=MeshFragment(
            nodes=tuple(nodes),
            solids=tuple(solids),
            shells=(
                ShellElement(
                    len(solids) + 1,
                    shell_node_ids,
                    "nonstructural_facade",
                ),
            ),
        ),
    )
    return artifact, topology


class Phase18DCommercialSupermarketTests(unittest.TestCase):
    def test_fast_path_uses_canonical_structural_profile_normalization(self) -> None:
        definition = default_building_definition(structural_system="rc_frame")
        parameters = definition["structural_system"]["parameters"]
        parameters.pop("generation_mode", None)
        definition["nonstructural"] = []

        fast = _compile_asset_definition(definition)
        canonical = compile_refined_building(definition)

        self.assertEqual(canonical.normalized_input, fast.normalized_input)
        self.assertEqual(canonical.mesh.fingerprint, fast.mesh.fingerprint)
        self.assertEqual(canonical.fingerprint, fast.fingerprint)

    def test_frozen_artifact_mapping_rejects_inplace_union(self) -> None:
        package = compile_small_supermarket()
        artifact = package.artifacts[0]
        snapshot = artifact.normalized_input
        artifact_fingerprint = artifact.fingerprint
        package_fingerprint = package.package_fingerprint

        with self.assertRaises(TypeError):
            snapshot |= {"asset_id": "tampered"}

        self.assertEqual(RESOURCE_ID, artifact.normalized_input["asset_id"])
        self.assertEqual(artifact_fingerprint, artifact.fingerprint)
        self.assertEqual(package_fingerprint, package.package_fingerprint)

    def test_surface_candidate_prefilter_matches_exhaustive_reference(self) -> None:
        split = 0.9999999999
        fixtures = {
            "hybrid_union": surface_reference_fixture(
                ((0.0, 0.0), (3.0, 0.0), (3.0, 2.0), (0.0, 2.0)),
                (
                    ((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)),
                    ((1.0, 0.0), (3.0, 0.0), (3.0, 2.0), (1.0, 2.0)),
                ),
            ),
            "rc_union": surface_reference_fixture(
                ((0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)),
                (
                    ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
                    ((1.0, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0, 1.0)),
                ),
                system_id="rc_frame",
            ),
            "tolerance_boundary": surface_reference_fixture(
                ((0.0, 0.0), (1.0, 0.0), (1.0, 100.0), (0.0, 100.0)),
                (
                    ((0.0, 0.0), (split, 0.0), (split, 100.0), (0.0, 100.0)),
                    ((split, 0.0), (1.0, 0.0), (1.0, 100.0), (split, 100.0)),
                ),
                bottom_z=-97.0,
            ),
            "non_axis_fallback": surface_reference_fixture(
                ((0.5, 0.5), (3.5, 0.5), (3.5, 3.5), (0.5, 3.5)),
                (((2.0, 0.0), (4.0, 2.0), (2.0, 4.0), (0.0, 2.0)),),
            ),
        }

        exhaustive_by_fixture: dict[str, object] = {}
        for fixture_id, (artifact, topology) in fixtures.items():
            with self.subTest(fixture_id=fixture_id):
                optimized = build_fluid_exposed_surface_catalog(artifact, topology)
                with patch.object(
                    surface_module,
                    "_solid_face_candidates_for_shell",
                    side_effect=lambda _nodes, solid_faces, _index: solid_faces,
                ):
                    exhaustive = build_fluid_exposed_surface_catalog(
                        artifact,
                        topology,
                    )
                self.assertEqual(exhaustive, optimized)
                exhaustive_by_fixture[fixture_id] = exhaustive

        rc_artifact, rc_topology = fixtures["rc_union"]
        with patch.object(
            surface_module,
            "_solid_face_candidates_for_shell",
            return_value=[],
        ):
            broken = build_fluid_exposed_surface_catalog(rc_artifact, rc_topology)
        self.assertNotEqual(exhaustive_by_fixture["rc_union"], broken)

    def test_official_validator_reports_outside_envelope_panel_nodes(self) -> None:
        descriptor = get_detailed_building_asset(RESOURCE_ID)
        geometry = normalize_asset_geometry(descriptor, SMALL_GEOMETRY)
        template = build_detailed_building_template(
            descriptor,
            geometry,
            structural_system="steel_concrete_hybrid",
            fidelity_profile="blast_response",
            mesh_profile="coarse",
            generation_options={
                "reinforcement_mode": "full_reinforced",
                "cover_m": 0.04,
                "bar_diameter_m": 0.016,
                "rebar_spacing_m": 0.30,
            },
        )
        with patch(
            "lsprepost_mcp.refined_building.asset_compiler.compile_nonstructural",
            return_value=outside_envelope_panel(),
        ):
            candidate = _compile_asset_definition(template.definitions[0])

        report = validate_building_artifact(candidate)
        self.assertEqual(
            ["structural_node_outside_envelope"] * 4,
            [row["code"] for row in report["findings"]],
        )

    def test_public_compiler_fails_closed_for_outside_envelope_panel(self) -> None:
        with patch(
            "lsprepost_mcp.refined_building.asset_compiler.compile_nonstructural",
            return_value=outside_envelope_panel(),
        ):
            with self.assertRaisesRegex(
                ValueError,
                "structural_node_outside_envelope",
            ):
                compile_small_supermarket()

    def test_frozen_package_artifact_remains_valid_for_official_validator(self) -> None:
        package = compile_small_supermarket()

        report = validate_building_artifact(package.artifacts[0])

        self.assertTrue(report["valid"], report["findings"])
        self.assertEqual([], report["findings"])
        self.assertEqual(
            report["valid"],
            package.quality_manifest["software_validation_passed"],
        )

    def test_frozen_package_artifact_remains_usable_by_surface_builder(self) -> None:
        package = compile_small_supermarket(structural_system="rc_frame")
        artifact = package.artifacts[0]
        fingerprint_before = artifact.fingerprint

        rebuilt = build_refined_asset_surface_catalog((artifact,))

        self.assertIsInstance(rebuilt["exterior_surfaces"], list)
        self.assertIsInstance(rebuilt["interior_cavity_surfaces"], list)
        self.assertEqual(fingerprint_before, artifact.fingerprint)

    def test_default_hybrid_contains_solid_steel_and_reinforced_concrete(self) -> None:
        package = compile_small_supermarket()
        artifact = package.artifacts[0]

        self.assertEqual("steel_concrete_hybrid", package.structural_system)
        self.assertEqual("steel_concrete_hybrid", artifact.system_id)
        self.assertEqual(25920, len(artifact.mesh.solids))
        beam_roles = {row.part_role for row in artifact.mesh.beams}
        self.assertIn("steel_column", beam_roles)
        self.assertIn("steel_beam", beam_roles)
        self.assertIn("foundation_rebar", beam_roles)
        self.assertIn("slab_rebar", beam_roles)
        self.assertTrue(artifact.connections_by_type("embedded_rebar"))
        self.assertFalse(artifact.validation_findings)
        self.assertFalse(package.solver_ready)
        self.assertTrue(package.requires_project_review)

        bindings = package.material_binding_manifest["bindings"]
        by_semantic_role = {row["semantic_role"]: row for row in bindings}
        self.assertEqual(
            "two_storey_rc_frame_mid5_concrete_kc",
            by_semantic_role["concrete"]["resource_id"],
        )
        self.assertEqual(
            "syntax_unit_reviewed",
            by_semantic_role["concrete"]["effective_validation_status"],
        )
        self.assertEqual(
            "two_storey_rc_frame_mid8_rebar_d8_d18",
            by_semantic_role["reinforcing_steel"]["resource_id"],
        )
        self.assertEqual(
            "mild_steel_mat24_demo",
            by_semantic_role["structural_steel"]["resource_id"],
        )
        self.assertEqual(
            "demo",
            by_semantic_role["structural_steel"]["effective_validation_status"],
        )
        self.assertEqual(
            "piecewise_linear_plasticity",
            by_semantic_role["structural_steel"]["material_type"],
        )
        self.assertRegex(
            by_semantic_role["structural_steel"]["canonical_resource_sha256"],
            r"^[0-9a-f]{64}$",
        )
        expected_binding_keys = {
            (artifact.asset_id, row.part_role) for row in artifact.mesh.part_bindings
        }
        actual_binding_keys = {
            (row["artifact_id"], row["part_role"]) for row in bindings
        }
        self.assertEqual(expected_binding_keys, actual_binding_keys)
        self.assertEqual(len(expected_binding_keys), len(bindings))
        self.assertTrue(
            {"facade", "nonstructural"}
            <= {
                row["semantic_role"]
                for row in bindings
                if row["resolution_status"] == "unresolved"
            }
        )

    def test_four_by_three_grid_rooms_and_openings_preserve_real_voids(self) -> None:
        package = compile_small_supermarket()
        artifact = package.artifacts[0]
        normalized = artifact.normalized_input

        self.assertEqual(5, len(normalized["grid_axes"]["x_m"]))
        self.assertEqual(4, len(normalized["grid_axes"]["y_m"]))
        self.assertEqual(
            {"sales_hall", "stockroom", "service_room"},
            {row["id"] for row in normalized["spaces"]},
        )
        self.assertFalse(artifact.solid_contains_point((3.0, 1.0, 1.5)))
        self.assertFalse(artifact.solid_contains_point((5.0, 1.0, 1.5)))
        self.assertFalse(artifact.solid_contains_point((5.0, 3.2, 1.5)))
        self.assertIn("exterior", artifact.topology_manifest["adjacency"]["sales_hall"])
        self.assertIn("stockroom", artifact.topology_manifest["adjacency"]["sales_hall"])
        self.assertIn("service_room", artifact.topology_manifest["adjacency"]["sales_hall"])
        self.assertIn(
            "front_entrance",
            {row["opening_id"] for row in artifact.surface_catalog["opening_boundaries"]},
        )

        entrance = next(
            row for row in normalized["openings"] if row["id"] == "front_entrance"
        )
        entrance_bounds = entrance["bounds_m"]
        nodes = {node.node_id: node for node in artifact.mesh.nodes}
        for shell in artifact.mesh.shells:
            if not shell.part_role.startswith("nonstructural_facade"):
                continue
            centroid = tuple(
                sum(nodes[node_id].coordinates[axis] for node_id in shell.node_ids) / 4.0
                for axis in range(3)
            )
            inside_entrance = all(
                entrance_bounds[axis] - 1.0e-12
                <= centroid[axis]
                <= entrance_bounds[axis + 3] + 1.0e-12
                for axis in range(3)
            )
            self.assertFalse(inside_entrance)
            self.assertGreaterEqual(centroid[2], SMALL_GEOMETRY["wall_thickness_m"])
            self.assertLessEqual(
                centroid[2],
                SMALL_GEOMETRY["height_m"] - SMALL_GEOMETRY["wall_thickness_m"],
            )

    def test_package_surface_refinement_moves_room_facing_rc_faces_only_in_copy(self) -> None:
        package = compile_small_supermarket(structural_system="rc_frame")
        original = package.artifacts[0].surface_catalog
        refined = package.refined_surface_catalog

        self.assertGreater(len(original["unclassified_boundary_surfaces"]), 0)
        self.assertGreater(
            len(refined["interior_cavity_surfaces"]),
            len(original["interior_cavity_surfaces"]),
        )
        self.assertLess(
            len(refined["unclassified_boundary_surfaces"]),
            len(original["unclassified_boundary_surfaces"]),
        )
        self.assertIsNot(refined, original)
        self.assertGreater(len(original["unclassified_boundary_surfaces"]), 0)

    def test_fidelity_controls_panels_without_removing_structure(self) -> None:
        core = compile_small_supermarket(fidelity_profile="structural_core")
        blast = compile_small_supermarket(fidelity_profile="blast_response")
        research = compile_small_supermarket(fidelity_profile="research_detailed")

        self.assertEqual(len(core.artifacts[0].mesh.solids), len(blast.artifacts[0].mesh.solids))
        self.assertLess(len(core.artifacts[0].mesh.shells), len(blast.artifacts[0].mesh.shells))
        self.assertLessEqual(
            len(blast.artifacts[0].mesh.shells),
            len(research.artifacts[0].mesh.shells),
        )
        blast_panel_ids = {
            row["id"] for row in blast.artifacts[0].normalized_input["nonstructural"]
        }
        self.assertTrue(any(row.startswith("rear_facade_") for row in blast_panel_ids))
        self.assertTrue(any(row.startswith("left_facade_") for row in blast_panel_ids))
        self.assertTrue(any(row.startswith("right_facade_") for row in blast_panel_ids))
        self.assertIn(
            "glazing",
            {
                row["material_role"]
                for row in research.artifacts[0].normalized_input["nonstructural"]
            },
        )

    def test_quantities_separate_declared_air_from_structure_and_never_fabricate_total_mass(self) -> None:
        package = compile_small_supermarket()
        quantities = package.quantity_manifest

        self.assertAlmostEqual(9.6, quantities["solid_volume_m3"], places=9)
        self.assertAlmostEqual(
            quantities["declared_space_volume_m3"],
            quantities["net_air_volume_m3"],
            places=9,
        )
        self.assertAlmostEqual(0.0, quantities["structural_occupied_volume_m3"], places=9)
        self.assertAlmostEqual(0.0, quantities["unexpected_space_fill_volume_m3"], places=9)
        self.assertEqual("evaluable", package.quality_manifest["mass_by_family"]["solid"]["status"])
        self.assertEqual("not_evaluable", package.quality_manifest["mass_by_family"]["beam"]["status"])
        self.assertEqual("not_evaluable", package.quality_manifest["mass_by_family"]["shell"]["status"])
        self.assertEqual("not_evaluable", package.quality_manifest["total_mass"]["status"])
        self.assertNotIn("value_kg", package.quality_manifest["total_mass"])

        rc_package = compile_small_supermarket(structural_system="rc_frame")
        rc_quantities = rc_package.quantity_manifest
        self.assertGreater(rc_quantities["structural_occupied_volume_m3"], 0.0)
        self.assertLess(
            rc_quantities["net_air_volume_m3"],
            rc_quantities["declared_space_volume_m3"],
        )
        self.assertAlmostEqual(0.0, rc_quantities["unexpected_space_fill_volume_m3"], places=9)
        self.assertNotIn("predicted_solid_elements", rc_package.mesh_manifest)
        self.assertGreaterEqual(
            rc_package.mesh_manifest["solid_element_upper_bound"],
            rc_package.mesh_manifest["actual_solid_elements"],
        )

    def test_total_mass_is_evaluable_when_only_closed_solid_family_is_present(self) -> None:
        package = compile_small_supermarket(
            structural_system="rc_frame",
            fidelity_profile="structural_core",
            generation_options={"reinforcement_mode": "concrete_only"},
        )
        families = package.quality_manifest["mass_by_family"]
        total = package.quality_manifest["total_mass"]

        self.assertEqual("evaluable", families["solid"]["status"])
        self.assertEqual("not_present", families["beam"]["status"])
        self.assertEqual("not_present", families["shell"]["status"])
        self.assertEqual("evaluable", total["status"])
        self.assertAlmostEqual(
            families["solid"]["value_kg"],
            total["value_kg"],
            places=9,
        )

    def test_selected_mesh_profile_limits_solid_rebar_steel_and_panel_edges(self) -> None:
        package = compile_small_supermarket()
        artifact = package.artifacts[0]
        nodes = {row.node_id: row.coordinates for row in artifact.mesh.nodes}
        tolerance = 1.0e-12

        for solid in artifact.mesh.solids:
            coordinates = [nodes[node_id] for node_id in solid.node_ids]
            extents = [
                max(point[axis] for point in coordinates)
                - min(point[axis] for point in coordinates)
                for axis in range(3)
            ]
            self.assertLessEqual(max(extents), 0.075 + tolerance)
        for beam in artifact.mesh.beams:
            if beam.part_role not in {
                "steel_column",
                "steel_beam",
                "foundation_rebar",
                "slab_rebar",
            }:
                continue
            self.assertLessEqual(
                math.dist(nodes[beam.node_ids[0]], nodes[beam.node_ids[1]]),
                0.150 + tolerance,
            )
        for shell in artifact.mesh.shells:
            if not shell.part_role.startswith("nonstructural_"):
                continue
            coordinates = [nodes[node_id] for node_id in shell.node_ids]
            edges = [
                math.dist(coordinates[index], coordinates[(index + 1) % 4])
                for index in range(4)
            ]
            self.assertLessEqual(max(edges), 0.150 + tolerance)

    def test_solid_target_honors_slab_wall_and_minimum_thickness_layers(self) -> None:
        geometry = {
            "length_m": 3.6,
            "width_m": 3.0,
            "height_m": 2.4,
            "wall_thickness_m": 0.10,
            "entrance_width_m": 1.0,
            "entrance_height_m": 1.5,
        }
        for system_id in ("steel_concrete_hybrid", "rc_frame"):
            with self.subTest(system_id=system_id):
                package = compile_detailed_building_asset(
                    RESOURCE_ID,
                    legacy_geometry=geometry,
                    structural_system=system_id,
                    fidelity_profile="structural_core",
                    mesh_profile="coarse",
                    generation_options={"reinforcement_mode": "concrete_only"},
                )
                artifact = package.artifacts[0]
                profile = artifact.normalized_input["structural_system"]
                self.assertEqual(0.05, profile["parameters"]["mesh_size_m"])
                nodes = {row.node_id: row.coordinates for row in artifact.mesh.nodes}
                maximum_extent = max(
                    max(
                        max(nodes[node_id][axis] for node_id in solid.node_ids)
                        - min(nodes[node_id][axis] for node_id in solid.node_ids)
                        for axis in range(3)
                    )
                    for solid in artifact.mesh.solids
                )
                self.assertLessEqual(maximum_extent, 0.05 + 1.0e-12)
                thickness_intervals = {
                    (
                        min(nodes[node_id][2] for node_id in solid.node_ids),
                        max(nodes[node_id][2] for node_id in solid.node_ids),
                    )
                    for solid in artifact.mesh.solids
                    if "foundation" in solid.part_role
                }
                self.assertGreaterEqual(len(thickness_intervals), 2)

    def test_package_fingerprint_is_deterministic_and_invalidates_semantic_changes(self) -> None:
        baseline = compile_small_supermarket()
        repeat = compile_small_supermarket()
        self.assertEqual(baseline.package_fingerprint, repeat.package_fingerprint)

        variants = (
            compile_small_supermarket(mesh_profile="standard"),
            compile_small_supermarket(structural_system="rc_frame"),
            compile_small_supermarket(
                generation_options={"reinforcement_mode": "concrete_only"}
            ),
            compile_small_supermarket(
                material_overrides={"structural_steel": "mild_steel"}
            ),
        )
        self.assertEqual(
            len(variants),
            len({row.package_fingerprint for row in variants}),
        )
        self.assertNotIn(
            baseline.package_fingerprint,
            {row.package_fingerprint for row in variants},
        )
        no_rebar = variants[2].artifacts[0]
        self.assertFalse(
            {"foundation_rebar", "slab_rebar"}
            & {row.part_role for row in no_rebar.mesh.beams}
        )
        self.assertFalse(no_rebar.connections_by_type("embedded_rebar"))
        self.assertGreater(len(no_rebar.mesh.solids), 0)

    def test_placement_is_validated_stored_and_does_not_transform_local_mesh(self) -> None:
        baseline = compile_small_supermarket()
        placed = compile_small_supermarket(
            origin_m=(10.0, -2.0, 1.0),
            rotation_deg=(0.0, 0.0, 45.0),
        )

        self.assertEqual(
            {"origin_m": (10.0, -2.0, 1.0), "rotation_deg": (0.0, 0.0, 45.0)},
            placed.placement,
        )
        self.assertEqual(baseline.artifacts[0].fingerprint, placed.artifacts[0].fingerprint)
        self.assertNotEqual(baseline.package_fingerprint, placed.package_fingerprint)
        self.assertEqual(
            baseline.artifacts[0].mesh.bounds_m,
            placed.artifacts[0].mesh.bounds_m,
        )

        for invalid in ((0.0, 0.0), (0.0, math.nan, 0.0), (True, 0.0, 0.0)):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    compile_small_supermarket(origin_m=invalid)

    def test_preflight_rejects_requested_mesh_above_hard_limit_without_coarsening(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            r"commercial_supermarket_detailed_building/coarse predicted 25920 Solid elements .*limit 25919;.*not automatically coarsened",
        ):
            compile_small_supermarket(
                generation_options={"max_solid_elements": 25919}
            )

        accepted = compile_small_supermarket(
            generation_options={"max_solid_elements": 25920}
        )
        self.assertEqual("coarse", accepted.mesh_profile)
        self.assertEqual(25920, len(accepted.artifacts[0].mesh.solids))

    def test_invalid_geometry_system_options_and_material_categories_are_rejected(self) -> None:
        invalid_geometries = (
            {"entrance_width_m": 6.0},
            {"entrance_height_m": 3.0},
            {"wall_thickness_m": 2.1},
            {"unknown_m": 1.0},
        )
        for override in invalid_geometries:
            with self.subTest(override=override):
                with self.assertRaises(ValueError):
                    compile_detailed_building_asset(
                        RESOURCE_ID,
                        legacy_geometry={**SMALL_GEOMETRY, **override},
                        mesh_profile="coarse",
                    )

        with self.assertRaisesRegex(ValueError, "not allowed"):
            compile_small_supermarket(structural_system="rc_box")
        with self.assertRaisesRegex(ValueError, "unsupported generation option"):
            compile_small_supermarket(generation_options={"typo": True})
        with self.assertRaisesRegex(ValueError, "unsupported reinforcement_mode"):
            compile_small_supermarket(generation_options={"reinforcement_mode": []})
        with self.assertRaisesRegex(ValueError, "concrete material"):
            compile_small_supermarket(material_overrides={"concrete": "mild_steel"})
        with self.assertRaisesRegex(ValueError, "unknown material override role"):
            compile_small_supermarket(material_overrides={"typo": "mild_steel"})
        with self.assertRaisesRegex(ValueError, "geometry field names must be strings"):
            compile_detailed_building_asset(
                RESOURCE_ID,
                legacy_geometry={**SMALL_GEOMETRY, 1: 2.0},
                mesh_profile="coarse",
            )
        with self.assertRaisesRegex(ValueError, "material override roles must be strings"):
            compile_small_supermarket(material_overrides={1: "mild_steel"})
        with self.assertRaisesRegex(ValueError, "doors material .*unknown material"):
            compile_small_supermarket(
                fidelity_profile="structural_core",
                material_overrides={"doors": "definitely_missing_material"},
            )
        with self.assertRaisesRegex(ValueError, "material override roles are not used"):
            compile_small_supermarket(
                fidelity_profile="structural_core",
                material_overrides={"doors": "mild_steel"},
            )

    def test_package_is_frozen_and_manifest_is_json_compatible(self) -> None:
        package = compile_small_supermarket()

        with self.assertRaises(FrozenInstanceError):
            package.mesh_profile = "fine"  # type: ignore[misc]
        manifest = package.to_manifest()
        encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
        self.assertIn(package.package_fingerprint, encoded)
        artifact_fingerprint = package.artifacts[0].fingerprint
        manifest["artifacts"][0]["normalized_input"]["asset_id"] = "corrupted_copy"
        manifest["artifacts"][0]["surface_catalog"]["exterior_surfaces"].clear()
        self.assertEqual(RESOURCE_ID, package.artifacts[0].normalized_input["asset_id"])
        self.assertTrue(package.artifacts[0].surface_catalog["exterior_surfaces"])
        self.assertEqual(artifact_fingerprint, package.artifacts[0].fingerprint)
        with self.assertRaises(TypeError):
            package.artifacts[0].normalized_input["asset_id"] = "direct_corruption"
        with self.assertRaises(TypeError):
            package.artifacts[0].normalized_input["spaces"].append({})
        self.assertEqual(
            {
                "nodes": len(package.artifacts[0].mesh.nodes),
                "solids": 25920,
                "shells": len(package.artifacts[0].mesh.shells),
                "beams": len(package.artifacts[0].mesh.beams),
                "connections": len(package.artifacts[0].connections),
            },
            package.mesh_manifest["counts"],
        )

    def test_small_acceptance_asset_compiles_without_shell_solid_quadratic_scan(self) -> None:
        started = time.perf_counter()
        package = compile_small_supermarket()
        elapsed = time.perf_counter() - started

        self.assertEqual(25920, len(package.artifacts[0].mesh.solids))
        self.assertLess(elapsed, 15.0)

    def test_rc_alternative_full_validation_remains_bounded_after_densification(self) -> None:
        started = time.perf_counter()
        package = compile_small_supermarket(structural_system="rc_frame")
        elapsed = time.perf_counter() - started

        self.assertFalse(package.artifacts[0].validation_findings)
        self.assertEqual(137293, len(package.artifacts[0].mesh.solids))
        self.assertLess(elapsed, 60.0)

    def test_final_panel_assembly_has_closed_ids_bindings_connections_bounds_and_fingerprint(self) -> None:
        package = compile_small_supermarket()
        artifact = package.artifacts[0]
        mesh = artifact.mesh
        node_ids = {row.node_id for row in mesh.nodes}
        elements = (*mesh.solids, *mesh.shells, *mesh.beams)
        element_ids = {row.element_id for row in elements}

        self.assertEqual(len(mesh.nodes), len(node_ids))
        self.assertEqual(len(elements), len(element_ids))
        self.assertTrue(all(set(row.node_ids) <= node_ids for row in mesh.shells))
        binding_roles = {row.part_role for row in mesh.part_bindings}
        self.assertTrue({row.part_role for row in elements} <= binding_roles)
        self.assertTrue(
            all(
                set(row.source_element_ids + row.target_element_ids) <= element_ids
                for row in artifact.connections
            )
        )
        mesh_record = package.mesh_manifest["artifacts"][0]
        self.assertEqual(list(mesh.bounds_m), list(mesh_record["bounds_m"]))
        self.assertEqual(mesh.fingerprint, mesh_record["mesh_fingerprint"])
        self.assertEqual(len(elements), mesh_record["element_count"])
        self.assertEqual(
            artifact.fingerprint,
            package.to_manifest()["artifacts"][0]["fingerprint"],
        )

    def test_broken_panel_node_reference_fails_closed_at_mesh_boundary(self) -> None:
        nodes = (
            Node(1, 0.0, 0.0, 0.0),
            Node(2, 1.0, 0.0, 0.0),
            Node(3, 1.0, 0.0, 1.0),
            Node(4, 0.0, 0.0, 1.0),
        )

        with self.assertRaisesRegex(ValueError, "dangling node references"):
            MeshFragment(
                nodes=nodes,
                shells=(ShellElement(1, (1, 2, 3, 5), "nonstructural_facade"),),
            )

    def test_rc_preflight_upper_bound_covers_nonintegral_local_axis_subdivision(self) -> None:
        descriptor = get_detailed_building_asset(RESOURCE_ID)
        geometry = normalize_asset_geometry(
            descriptor,
            {
                "length_m": 11.488,
                "width_m": 7.433,
                "height_m": 2.913,
                "wall_thickness_m": 0.20,
                "entrance_width_m": 2.0,
                "entrance_height_m": 2.0,
            },
        )
        template = build_detailed_building_template(
            descriptor,
            geometry,
            structural_system="rc_frame",
            fidelity_profile="structural_core",
            mesh_profile="coarse",
            generation_options={
                "reinforcement_mode": "full_reinforced",
                "cover_m": 0.04,
                "bar_diameter_m": 0.016,
                "rebar_spacing_m": 0.30,
            },
        )

        self.assertEqual("conservative_upper_bound", template.solid_estimate_kind)
        self.assertGreaterEqual(template.solid_element_estimate, 161016)

    def test_default_hybrid_front_entrance_has_clear_swept_frame_and_load_path(self) -> None:
        package = compile_small_supermarket(
            fidelity_profile="structural_core",
            generation_options={"reinforcement_mode": "concrete_only"},
        )
        artifact = package.artifacts[0]
        profile = artifact.normalized_input["structural_system"]["parameters"][
            "opening_frame_profile"
        ]
        opening = next(
            row
            for row in artifact.normalized_input["openings"]
            if row["id"] == "front_entrance"
        )
        clear_box = tuple(float(value) for value in opening["bounds_m"])
        nodes = {node.node_id: node.coordinates for node in artifact.mesh.nodes}
        frame_roles = {
            "steel_column",
            "steel_beam",
            "steel_opening_jamb",
            "steel_opening_header",
        }
        steel = tuple(row for row in artifact.mesh.beams if row.part_role in frame_roles)
        self.assertTrue(
            {"steel_opening_jamb", "steel_opening_header"}
            <= {row.part_role for row in steel}
        )
        for beam in steel:
            swept = _beam_swept_bounds(nodes, beam, profile)
            self.assertFalse(
                _boxes_have_positive_volume_overlap(swept, clear_box),
                (beam, swept, clear_box),
            )

        frame_connection = artifact.connections_by_type("steel_connection")[0]
        self.assertTrue(
            {row.element_id for row in steel}
            <= set(frame_connection.source_element_ids)
        )
        adjacency = _beam_node_adjacency(steel)
        roof_z = SMALL_GEOMETRY["height_m"]
        jamb_base_nodes = {
            node_id
            for row in steel
            if row.part_role == "steel_opening_jamb"
            for node_id in row.node_ids
            if nodes[node_id][2] == 0.0
        }
        header_nodes = {
            node_id
            for row in steel
            if row.part_role == "steel_opening_header"
            for node_id in row.node_ids
        }
        roof_nodes = {node_id for node_id, point in nodes.items() if point[2] == roof_z}
        self.assertEqual(2, len(jamb_base_nodes))
        self.assertTrue(header_nodes)
        for start in jamb_base_nodes:
            reachable = _reachable_nodes(adjacency, start)
            self.assertTrue(header_nodes & reachable)
            self.assertTrue(roof_nodes & reachable)
        self.assertIn("exterior", artifact.topology_manifest["adjacency"]["sales_hall"])

    def test_rc_alternative_front_entrance_has_clear_solid_frame_and_roof_path(self) -> None:
        package = compile_small_supermarket(
            structural_system="rc_frame",
            fidelity_profile="structural_core",
            generation_options={"reinforcement_mode": "concrete_only"},
        )
        artifact = package.artifacts[0]
        opening = next(
            row
            for row in artifact.normalized_input["openings"]
            if row["id"] == "front_entrance"
        )
        clear_box = tuple(float(value) for value in opening["bounds_m"])
        nodes = {node.node_id: node.coordinates for node in artifact.mesh.nodes}
        structural_roles = {
            "rc_column",
            "rc_beam_x",
            "rc_beam_y",
            "rc_opening_jamb",
            "rc_opening_header",
            "rc_slab",
        }
        solids = tuple(
            row for row in artifact.mesh.solids if row.part_role in structural_roles
        )
        self.assertTrue(
            {"rc_opening_jamb", "rc_opening_header"}
            <= {row.part_role for row in solids}
        )
        for solid in solids:
            bounds = _element_bounds(nodes, solid.node_ids)
            self.assertFalse(
                _boxes_have_positive_volume_overlap(bounds, clear_box),
                (solid, bounds, clear_box),
            )

        by_node: dict[int, list[int]] = {}
        by_id = {row.element_id: row for row in solids}
        for solid in solids:
            for node_id in solid.node_ids:
                by_node.setdefault(node_id, []).append(solid.element_id)
        adjacency: dict[int, set[int]] = {element_id: set() for element_id in by_id}
        for element_ids in by_node.values():
            for element_id in element_ids:
                adjacency[element_id].update(element_ids)
        jamb_ids = {
            row.element_id for row in solids if row.part_role == "rc_opening_jamb"
        }
        header_ids = {
            row.element_id for row in solids if row.part_role == "rc_opening_header"
        }
        roof_ids = {row.element_id for row in solids if row.part_role == "rc_slab"}
        self.assertTrue(jamb_ids and header_ids and roof_ids)
        reachable = _reachable_nodes(adjacency, min(jamb_ids))
        self.assertTrue(header_ids & reachable)
        self.assertTrue(roof_ids & reachable)
        self.assertIn("exterior", artifact.topology_manifest["adjacency"]["sales_hall"])


def _element_bounds(
    nodes: dict[int, tuple[float, float, float]],
    node_ids: tuple[int, ...],
) -> tuple[float, float, float, float, float, float]:
    points = [nodes[node_id] for node_id in node_ids]
    return tuple(
        min(point[axis] for point in points)
        for axis in range(3)
    ) + tuple(
        max(point[axis] for point in points)
        for axis in range(3)
    )


def _beam_swept_bounds(
    nodes: dict[int, tuple[float, float, float]],
    beam: object,
    profile: object,
) -> tuple[float, float, float, float, float, float]:
    assert isinstance(profile, Mapping)
    start = nodes[beam.node_ids[0]]  # type: ignore[attr-defined]
    end = nodes[beam.node_ids[1]]  # type: ignore[attr-defined]
    half_width = float(profile["section_width_m"]) / 2.0
    half_depth = float(profile["section_depth_m"]) / 2.0
    return (
        min(start[0], end[0]) - half_width,
        min(start[1], end[1]) - half_width,
        min(start[2], end[2]) - half_depth,
        max(start[0], end[0]) + half_width,
        max(start[1], end[1]) + half_width,
        max(start[2], end[2]) + half_depth,
    )


def _boxes_have_positive_volume_overlap(
    left: tuple[float, float, float, float, float, float],
    right: tuple[float, float, float, float, float, float],
) -> bool:
    return all(
        min(left[axis + 3], right[axis + 3])
        - max(left[axis], right[axis])
        > 1.0e-12
        for axis in range(3)
    )


def _beam_node_adjacency(beams: tuple[object, ...]) -> dict[int, set[int]]:
    adjacency: dict[int, set[int]] = {}
    for beam in beams:
        start, end = beam.node_ids  # type: ignore[attr-defined]
        adjacency.setdefault(start, set()).add(end)
        adjacency.setdefault(end, set()).add(start)
    return adjacency


def _reachable_nodes(adjacency: dict[int, set[int]], start: int) -> set[int]:
    reached: set[int] = set()
    pending = [start]
    while pending:
        current = pending.pop()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(adjacency.get(current, ()) - reached)
    return reached


if __name__ == "__main__":
    unittest.main()
