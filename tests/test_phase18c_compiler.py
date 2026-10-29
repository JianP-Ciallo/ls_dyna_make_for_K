from __future__ import annotations

from dataclasses import replace
import unittest

from lsprepost_mcp.refined_building.compiler import compile_refined_building
from lsprepost_mcp.refined_building.artifacts import (
    BeamElement,
    BuildingArtifact,
    MeshFragment,
    Node,
    PartBinding,
    ShellElement,
)
from lsprepost_mcp.refined_building.contracts import default_building_definition
from lsprepost_mcp.refined_building.meshing import merge_fragments, mesh_axis_aligned_block
from lsprepost_mcp.refined_building.spatial import AxisAlignedBox
from lsprepost_mcp.refined_building.validation import validate_building_artifact


class Phase18CCompilerTests(unittest.TestCase):
    def test_validation_rejects_each_structural_node_kind_outside_envelope(self) -> None:
        shell_artifact = BuildingArtifact(
            asset_id="outside_shell",
            system_id="steel_frame",
            mesh=MeshFragment(
                nodes=(
                    Node(1, 0.0, 0.0, 0.0),
                    Node(2, 1.0, 0.0, 0.0),
                    Node(3, 1.0, 1.0, 0.0),
                    Node(4, 0.0, 1.0, 0.0),
                ),
                shells=(ShellElement(1, (1, 2, 3, 4), "steel_shell"),),
                part_bindings=(PartBinding("steel_shell", "structural_steel", "shell"),),
            ),
            normalized_input=default_building_definition(structural_system="steel_frame"),
        )
        beam_artifact = BuildingArtifact(
            asset_id="outside_beam",
            system_id="steel_frame",
            mesh=MeshFragment(
                nodes=(Node(1, 0.0, 0.0, 0.0), Node(2, 1.0, 0.0, 0.0)),
                beams=(BeamElement(1, (1, 2), "steel_beam"),),
                part_bindings=(PartBinding("steel_beam", "structural_steel", "beam"),),
            ),
            normalized_input=default_building_definition(structural_system="steel_frame"),
        )
        cases = (
            (
                "solid",
                compile_refined_building(default_building_definition(structural_system="rc_frame")),
                "solids",
            ),
            ("shell", shell_artifact, "shells"),
            ("beam", beam_artifact, "beams"),
        )
        for label, artifact, collection_name in cases:
            with self.subTest(kind=label):
                collection = getattr(artifact.mesh, collection_name)
                moved_node_id = collection[0].node_ids[0]
                moved_nodes = tuple(
                    replace(node, x=-0.1) if node.node_id == moved_node_id else node
                    for node in artifact.mesh.nodes
                )
                moved_artifact = replace(
                    artifact,
                    mesh=replace(artifact.mesh, nodes=moved_nodes),
                )

                report = validate_building_artifact(moved_artifact)
                outside_findings = [
                    row
                    for row in report["findings"]
                    if row["code"] == "structural_node_outside_envelope"
                ]

                self.assertFalse(report["valid"])
                self.assertEqual(1, len(outside_findings))

    def test_room_space_is_not_treated_as_structural_intrusion(self) -> None:
        artifact = compile_refined_building(default_building_definition())

        codes = {row["code"] for row in validate_building_artifact(artifact)["findings"]}

        self.assertNotIn("solid_centroid_in_void", codes)
        self.assertNotIn("reinforcement_crosses_void", codes)

    def test_validation_ignores_an_outside_orphan_node(self) -> None:
        artifact = BuildingArtifact(
            asset_id="outside_orphan",
            system_id="steel_frame",
            mesh=MeshFragment(
                nodes=(
                    Node(1, 0.0, 0.0, 0.0),
                    Node(2, 1.0, 0.0, 0.0),
                    Node(3, -0.1, 0.0, 0.0),
                ),
                beams=(BeamElement(1, (1, 2), "steel_beam"),),
                part_bindings=(PartBinding("steel_beam", "structural_steel", "beam"),),
            ),
            normalized_input=default_building_definition(structural_system="steel_frame"),
        )

        report = validate_building_artifact(artifact)

        self.assertTrue(report["valid"], report["findings"])
        self.assertNotIn(
            "structural_node_outside_envelope",
            {row["code"] for row in report["findings"]},
        )

    def test_validation_reports_reinforcement_crossing_an_opening(self) -> None:
        value = default_building_definition(structural_system="rc_box")
        value["spaces"][0]["bounds_m"] = [0.2, 0.2, 0.2, 5.8, 5.8, 2.8]
        value["openings"] = [
            {
                "id": "entry",
                "kind": "door",
                "bounds_m": [0.0, 0.7, 0.2, 0.2, 1.2, 2.2],
                "connects": ["room_1", "exterior"],
            }
        ]
        artifact = BuildingArtifact(
            asset_id="crossing_rebar",
            system_id="rc_box",
            mesh=MeshFragment(
                nodes=(Node(1, 0.1, 0.5, 1.0), Node(2, 0.1, 1.5, 1.0)),
                beams=(BeamElement(1, (1, 2), "wall_rebar"),),
                part_bindings=(PartBinding("wall_rebar", "reinforcing_steel", "beam"),),
            ),
            normalized_input=value,
        )

        codes = {row["code"] for row in validate_building_artifact(artifact)["findings"]}

        self.assertIn("reinforcement_crosses_void", codes)

    def test_validation_rejects_duplicate_structural_coordinates(self) -> None:
        first = mesh_axis_aligned_block(AxisAlignedBox(0, 0, 0, 0.2, 0.2, 0.2), 0.2, "a")
        second = mesh_axis_aligned_block(AxisAlignedBox(0, 0, 0, 0.2, 0.2, 0.2), 0.2, "b")
        artifact = BuildingArtifact(
            asset_id="duplicate_coordinates",
            system_id="rc_frame",
            mesh=merge_fragments((first, second)),
            normalized_input=default_building_definition(),
        )

        codes = {row["code"] for row in validate_building_artifact(artifact)["findings"]}

        self.assertIn("duplicate_structural_coordinate", codes)

    def test_validation_rejects_disconnected_rc_concrete(self) -> None:
        first = mesh_axis_aligned_block(AxisAlignedBox(0, 0, 0, 0.2, 0.2, 0.2), 0.2, "a")
        second = mesh_axis_aligned_block(
            AxisAlignedBox(5.8, 5.8, 0, 6.0, 6.0, 0.2), 0.2, "b"
        )
        artifact = BuildingArtifact(
            asset_id="disconnected_concrete",
            system_id="rc_frame",
            mesh=merge_fragments((first, second)),
            normalized_input=default_building_definition(),
        )

        codes = {row["code"] for row in validate_building_artifact(artifact)["findings"]}

        self.assertIn("disconnected_concrete", codes)

    def test_every_standard_system_compiles_a_valid_minimum_building(self) -> None:
        for system_id in (
            "rc_frame",
            "rc_frame_shear_wall",
            "steel_frame",
            "steel_concrete_hybrid",
            "rc_box",
        ):
            with self.subTest(system_id=system_id):
                artifact = compile_refined_building(
                    default_building_definition(structural_system=system_id)
                )
                report = validate_building_artifact(artifact)
                self.assertTrue(report["valid"], report["findings"])
                self.assertGreater(report["element_count"], 0)
                self.assertTrue(artifact.requires_project_review)
                self.assertEqual(artifact.fingerprint, artifact.to_manifest()["fingerprint"])

    def test_reordered_input_maps_produce_same_fingerprint(self) -> None:
        value = default_building_definition(structural_system="rc_frame")
        reordered = {key: value[key] for key in reversed(list(value))}

        self.assertEqual(
            compile_refined_building(value).fingerprint,
            compile_refined_building(reordered).fingerprint,
        )

    def test_nonstructural_components_are_merged_but_not_structurally_connected(self) -> None:
        value = default_building_definition(structural_system="rc_frame")
        value["structural_system"]["parameters"] = {"generation_mode": "concrete_only"}
        value["nonstructural"] = [
            {
                "id": "partition_1",
                "kind": "partition",
                "bounds_m": [2.95, 0.25, 0.25, 3.05, 5.75, 2.75],
                "material_role": "gypsum_partition",
            }
        ]

        artifact = compile_refined_building(value)

        self.assertIn("nonstructural_partition", {row.part_role for row in artifact.mesh.shells})
        self.assertFalse(artifact.connections_by_type("structural_common_node"))
        self.assertTrue(validate_building_artifact(artifact)["valid"])

    def test_custom_hybrid_requires_explicit_backend_support(self) -> None:
        value = default_building_definition(structural_system="custom_hybrid")
        value["structural_system"]["parameters"] = {
            "subsystems": ["steel_frame", "rc_frame"],
            "zones": [
                {
                    "id": "west",
                    "system_id": "steel_frame",
                    "bounds_m": [0.0, 0.0, 0.0, 3.0, 6.0, 3.0],
                },
                {
                    "id": "east",
                    "system_id": "rc_frame",
                    "bounds_m": [3.0, 0.0, 0.0, 6.0, 6.0, 3.0],
                },
            ],
        }

        with self.assertRaisesRegex(ValueError, "custom_hybrid.*not yet"):
            compile_refined_building(value)


if __name__ == "__main__":
    unittest.main()
