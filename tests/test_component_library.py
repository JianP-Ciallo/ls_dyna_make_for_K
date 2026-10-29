from __future__ import annotations

import math
import unittest
import shutil

from lsprepost_mcp.component_library import (
    AssemblyContext,
    ComponentInstance,
    component_definition,
    component_template_names,
)
from lsprepost_mcp.config import PROJECTS_DIR
from lsprepost_mcp.dyna_keyword import build_keyword
from lsprepost_mcp.dyna_assembly import build_component_geometry
from lsprepost_mcp.schema import default_model_spec, parse_model_spec
from lsprepost_mcp.tool_generation import (
    tool_assemble_components,
    tool_get_component_template,
    tool_list_component_templates,
)


class ComponentLibraryTests(unittest.TestCase):
    def test_traffic_light_is_one_connected_fine_shell_topology(self) -> None:
        nodes, shells, solids, _metadata = build_component_geometry(
            {
                "id": "traffic_light_probe",
                "template": "traffic_light",
                "geometry": {
                    "pole_height_m": 4.5,
                    "pole_radius_m": 0.08,
                    "arm_length_m": 3.5,
                    "head_width_m": 0.3,
                    "head_height_m": 0.8,
                    "thickness_m": 0.02,
                },
                "mesh": {"size_m": 0.5},
                "material": {"name": "mild_steel"},
            },
            33,
        )
        self.assertFalse(solids)
        node_to_elements: dict[int, set[int]] = {}
        for element_index, element in enumerate(shells):
            for node_id in element[2:6]:
                node_to_elements.setdefault(node_id, set()).add(element_index)
        adjacency = [set() for _element in shells]
        for element_ids in node_to_elements.values():
            for element_id in element_ids:
                adjacency[element_id].update(element_ids - {element_id})
        remaining = set(range(len(shells)))
        component_count = 0
        while remaining:
            component_count += 1
            pending = [remaining.pop()]
            while pending:
                current = pending.pop()
                neighbors = adjacency[current] & remaining
                remaining.difference_update(neighbors)
                pending.extend(neighbors)

        coordinates = {
            node_id: (float(x), float(y), float(z))
            for node_id, x, y, z in nodes
        }
        maximum_edge = max(
            math.dist(coordinates[first], coordinates[second])
            for _eid, _pid, n1, n2, n3, n4 in shells
            for first, second in ((n1, n2), (n2, n3), (n3, n4), (n4, n1))
        )
        self.assertEqual(1, component_count)
        self.assertLessEqual(maximum_edge, 0.101)

    def test_initial_registry_describes_existing_assembly_templates(self) -> None:
        self.assertEqual(
            (
                "beam_bar",
                "circular_plate",
                "commercial_supermarket",
                "ellipsoid_shell",
                "parked_vehicle",
                "parking_lot",
                "residential_community",
                "shell_box",
                "shell_plate",
                "shell_tube",
                "solid_block",
                "solid_cylinder",
                "sphere_shell",
                "subway_entrance",
                "traffic_light",
            ),
            component_template_names(),
        )
        plate = component_definition("shell_plate")
        self.assertEqual("shell", plate.element_family)
        self.assertEqual(("length_m", "width_m", "thickness_m"), plate.geometry_fields)
        self.assertIn("top_surface", plate.named_surfaces)
        self.assertIn("four_edges", plate.named_edges)

    def test_component_instance_resolves_definition_without_mutating_input(self) -> None:
        raw = default_model_spec("component_instance_probe", "assembly_scene")["components"][0]
        instance = ComponentInstance.from_mapping(raw)
        self.assertEqual("rod", instance.component_id)
        self.assertEqual("solid_cylinder", instance.template)
        self.assertEqual("solid", instance.definition.element_family)
        self.assertIsNot(instance.raw, raw)

    def test_assembly_context_allocates_legacy_compatible_ids(self) -> None:
        context = AssemblyContext()
        first = context.allocate_component_ids()
        second = context.allocate_component_ids()
        self.assertEqual((1, 1, 1), (first.part_id, first.section_id, first.material_id))
        self.assertEqual((2, 2, 2), (second.part_id, second.section_id, second.material_id))
        self.assertEqual(1001, context.allocate_set_id())
        self.assertEqual(1, context.allocate_contact_id())

    def test_assembly_metadata_exposes_registered_named_regions(self) -> None:
        keyword, metadata = build_keyword(parse_model_spec(default_model_spec("named_regions_probe", "assembly_scene")))
        self.assertIn("*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE", keyword)
        rod, plate = metadata["components"]
        self.assertIn("outer_surface", rod["named_surfaces"])
        self.assertIn("bottom_end", rod["named_surfaces"])
        self.assertIn("top_surface", plate["named_surfaces"])
        self.assertIn("four_edges", plate["named_edges"])

    def test_every_registered_mesh_component_can_join_an_assembly(self) -> None:
        geometries = {
            "beam_bar": {"length_m": 0.2, "width_m": 0.02, "height_m": 0.02},
            "circular_plate": {"radius_m": 0.1, "thickness_m": 0.003},
            "commercial_supermarket": {
                "length_m": 16.0,
                "width_m": 12.0,
                "height_m": 6.0,
                "wall_thickness_m": 0.2,
                "entrance_width_m": 4.0,
                "entrance_height_m": 3.0,
            },
            "ellipsoid_shell": {"radius_x_m": 0.1, "radius_y_m": 0.08, "height_m": 0.06, "thickness_m": 0.003},
            "parking_lot": {
                "length_m": 12.0,
                "width_m": 10.0,
                "thickness_m": 0.15,
                "parking_rows": 2,
                "spaces_per_row": 4,
            },
            "parked_vehicle": {
                "length_m": 4.4,
                "width_m": 1.8,
                "body_height_m": 0.8,
                "cabin_height_m": 0.75,
                "shell_thickness_m": 0.0025,
            },
            "residential_community": {
                "tower_length_m": 6.0,
                "tower_width_m": 8.0,
                "tower_height_m": 12.0,
                "tower_count": 2,
                "tower_spacing_m": 3.0,
                "wall_thickness_m": 0.2,
                "balcony_depth_m": 1.0,
            },
            "shell_box": {"length_m": 0.2, "width_m": 0.15, "height_m": 0.1, "thickness_m": 0.003},
            "shell_plate": {"length_m": 0.2, "width_m": 0.15, "thickness_m": 0.003},
            "shell_tube": {"radius_m": 0.03, "length_m": 0.2, "thickness_m": 0.002},
            "solid_block": {"length_m": 0.2, "width_m": 0.15, "height_m": 0.1},
            "solid_cylinder": {"radius_m": 0.03, "length_m": 0.2},
            "sphere_shell": {"radius_m": 0.08, "thickness_m": 0.002},
            "subway_entrance": {
                "length_m": 6.0,
                "width_m": 4.0,
                "platform_height_m": 0.3,
                "enclosure_height_m": 2.8,
                "wall_thickness_m": 0.2,
                "roof_thickness_m": 0.2,
            },
            "traffic_light": {
                "pole_height_m": 4.5,
                "pole_radius_m": 0.08,
                "arm_length_m": 3.5,
                "head_width_m": 0.3,
                "head_height_m": 0.8,
                "thickness_m": 0.02,
            },
        }
        for template, geometry in geometries.items():
            with self.subTest(template=template):
                mesh_size = 2.0 if template in {
                    "commercial_supermarket",
                    "parking_lot",
                    "parked_vehicle",
                    "residential_community",
                    "subway_entrance",
                    "traffic_light",
                } else 0.04
                raw = default_model_spec(f"component_{template}_probe", "assembly_scene")
                raw["components"][0] = {
                    "id": "probe",
                    "template": template,
                    "geometry": geometry,
                    "mesh": {"size_m": mesh_size},
                    "material": {"name": "mild_steel"},
                    "transform": {"translate_m": [0.0, 0.0, 0.2]},
                }
                raw["contacts"] = []
                keyword, metadata = build_keyword(parse_model_spec(raw))
                self.assertEqual(2, metadata["part_count"])
                self.assertGreater(metadata["components"][0]["node_count"], 0)
                self.assertIn(f"probe_{template}", keyword)

    def test_component_catalog_tools_expose_registry_metadata(self) -> None:
        catalog = tool_list_component_templates({})
        self.assertEqual(15, catalog["count"])
        plate = tool_get_component_template({"template": "shell_plate"})["component"]
        self.assertEqual("shell", plate["element_family"])
        self.assertIn("top_surface", plate["named_surfaces"])
        self.assertEqual(0.5, plate["default_geometry"]["length_m"])
        self.assertGreater(plate["default_mesh_size_m"], 0.0)
        self.assertFalse(plate["city_editor"]["placeable"])
        self.assertEqual("城市结构", plate["city_editor"]["category"])
        self.assertEqual([], plate["city_editor"]["mobility_profiles"])
        vehicle = tool_get_component_template(
            {"template": "parked_vehicle"}
        )["component"]
        self.assertTrue(vehicle["city_editor"]["placeable"])
        self.assertEqual("城市设施", vehicle["city_editor"]["category"])
        self.assertEqual(
            ["surface_dynamic"],
            vehicle["city_editor"]["mobility_profiles"],
        )
        self.assertEqual(
            ["add", "duplicate", "delete"],
            vehicle["city_editor"]["instance_operations"],
        )
        self.assertTrue(vehicle["city_editor"]["supports_ale_fsi"])
        self.assertEqual(
            "required_individual",
            vehicle["city_editor"]["response_policy"],
        )
        self.assertEqual(
            [
                "fsi_pressure",
                "structural_pressure",
                "principal_stress",
                "displacement",
            ],
            vehicle["city_editor"]["response_metrics"],
        )
        subway = tool_get_component_template(
            {"template": "subway_entrance"}
        )["component"]
        self.assertTrue(subway["city_editor"]["placeable"])
        self.assertEqual(
            ["add", "duplicate", "delete"],
            subway["city_editor"]["instance_operations"],
        )
        self.assertEqual(
            ["grounded"],
            subway["city_editor"]["mobility_profiles"],
        )
        self.assertTrue(subway["city_editor"]["supports_ale_fsi"])
        cylinder = tool_get_component_template(
            {"template": "solid_cylinder"}
        )["component"]
        self.assertFalse(cylinder["city_editor"]["placeable"])
        solid_block = tool_get_component_template(
            {"template": "solid_block"}
        )["component"]
        self.assertFalse(solid_block["city_editor"]["placeable"])
        shell_box = tool_get_component_template(
            {"template": "shell_box"}
        )["component"]
        self.assertTrue(shell_box["city_editor"]["placeable"])
        self.assertEqual(
            ["grounded"],
            shell_box["city_editor"]["mobility_profiles"],
        )
        self.assertEqual(
            ["add", "duplicate", "delete"],
            shell_box["city_editor"]["instance_operations"],
        )
        self.assertTrue(shell_box["city_editor"]["supports_ale_fsi"])

    def test_assemble_components_dry_run_builds_without_writing(self) -> None:
        project_name = "unit_assemble_components_dry_run"
        project_path = PROJECTS_DIR / project_name
        if project_path.exists():
            shutil.rmtree(project_path)
        raw = default_model_spec(project_name, "assembly_scene")
        result = tool_assemble_components(
            {
                "project_name": project_name,
                "components": raw["components"],
                "contacts": raw["contacts"],
                "dry_run": True,
            }
        )
        self.assertTrue(result["ok"])
        self.assertEqual("validated_only", result["status"])
        self.assertEqual(2, result["metadata"]["part_count"])
        self.assertFalse(project_path.exists())

    def test_assemble_components_rejects_unknown_geometry_fields(self) -> None:
        raw = default_model_spec("unit_assemble_unknown_geometry", "assembly_scene")
        raw["components"][0]["geometry"]["invented_radius"] = 1.0
        with self.assertRaisesRegex(ValueError, "unsupported geometry field"):
            tool_assemble_components(
                {
                    "project_name": "unit_assemble_unknown_geometry",
                    "components": raw["components"],
                    "contacts": raw["contacts"],
                    "dry_run": True,
                }
            )


if __name__ == "__main__":
    unittest.main()
