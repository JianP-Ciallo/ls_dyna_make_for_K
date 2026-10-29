from __future__ import annotations

import unittest

from lsprepost_mcp.dyna_assembly import build_solid_cylinder_component
from lsprepost_mcp.dyna_keyword import build_keyword
from lsprepost_mcp.schema import (
    cube_top_corner_load_spec,
    default_model_spec,
    parse_model_spec,
    plate_pressure_spec,
    rebar_drop_on_helmet_spec,
)


class GenerationTests(unittest.TestCase):
    def test_component_solid_cylinder_uses_round_boundary_mesh(self) -> None:
        component = {
            "id": "rod",
            "template": "solid_cylinder",
            "geometry": {"radius_m": 0.012, "length_m": 1.0},
            "mesh": {"size_m": 0.05},
        }
        nodes, _, elements, metadata = build_solid_cylinder_component(component, 1)
        boundary_nodes = [
            (x, y)
            for _, x, y, z in nodes
            if abs(z) < 1.0e-12 and (abs(x) > 0.0115 or abs(y) > 0.0115)
        ]
        self.assertEqual(metadata["mesh_method"], "mapped_square_to_disk_hexa_cylinder")
        self.assertGreaterEqual(metadata["nxy"], 8)
        self.assertGreater(len(elements), 0)
        self.assertGreater(len(boundary_nodes), 0)
        self.assertTrue(any(abs((x * x + y * y) ** 0.5 - 0.012) < 1.0e-9 for x, y in boundary_nodes))

    def test_mat24_library_material_generates_piecewise_plasticity_card(self) -> None:
        raw = default_model_spec("unit_mat24_library", "shell_plate")
        raw["material"] = {"name": "mild_steel_mat24_demo"}
        keyword, metadata = build_keyword(parse_model_spec(raw))
        self.assertIn("*MAT_PIECEWISE_LINEAR_PLASTICITY", keyword)
        self.assertNotIn("*MAT_ELASTIC\n", keyword)
        self.assertEqual(1, metadata["material_count"])

    def test_cylinder_solid_generates_valid_keyword_shape(self) -> None:
        raw = default_model_spec("unit_cylinder_solid", "cylinder_solid")
        raw["mesh"]["size_m"] = 0.015
        keyword, metadata = build_keyword(parse_model_spec(raw))
        self.assertIn("*ELEMENT_SOLID", keyword)
        self.assertIn("*SECTION_SOLID", keyword)
        self.assertEqual(metadata["model_type"], "cylinder_solid")
        self.assertEqual(metadata["element_family"], "solid")
        self.assertGreater(metadata["node_count"], 0)
        self.assertGreater(metadata["element_count"], 0)
        self.assertEqual(metadata["mesh"]["method"], "voxelized_hexa_cylinder")
        self.assertIn("preflight", metadata)

    def test_assembly_scene_generates_reusable_components_and_surface_contact(self) -> None:
        raw = default_model_spec("unit_assembly_surface_contact", "assembly_scene")
        keyword, metadata = build_keyword(parse_model_spec(raw))
        self.assertIn("*ELEMENT_SOLID", keyword)
        self.assertIn("*ELEMENT_SHELL", keyword)
        self.assertIn("*SET_PART_LIST", keyword)
        self.assertIn("*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE", keyword)
        self.assertIn("*INITIAL_VELOCITY_NODE", keyword)
        self.assertEqual(metadata["model_type"], "assembly_scene")
        self.assertEqual(metadata["element_family"], "mixed")
        self.assertEqual(metadata["part_count"], 2)
        self.assertEqual(metadata["contact_count"], 1)
        self.assertEqual(metadata["controlled_contact_cards"], ["*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE"])
        lines = keyword.splitlines()
        contact_index = lines.index("*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE")
        end_index = lines.index("*END")
        self.assertGreaterEqual(end_index - contact_index, 8)
        self.assertIn("1.0,1.0,0.0,0.0,1.0,1.0,1.0,1.0", lines[contact_index:end_index])

    def test_assembly_scene_generates_nodes_to_surface_contact(self) -> None:
        raw = default_model_spec("unit_assembly_nodes_contact", "assembly_scene")
        raw["contacts"] = [
            {
                "type": "automatic_nodes_to_surface",
                "slave": "rod",
                "master": "plate",
                "slave_face": "z_min",
                "friction": 0.15,
            }
        ]
        keyword, metadata = build_keyword(parse_model_spec(raw))
        self.assertIn("*CONTACT_AUTOMATIC_NODES_TO_SURFACE", keyword)
        self.assertIn("*SET_NODE_LIST", keyword)
        self.assertEqual(metadata["contact_count"], 1)
        self.assertEqual(metadata["controlled_contact_cards"], ["*CONTACT_AUTOMATIC_NODES_TO_SURFACE"])

    def test_assembly_scene_generates_ellipsoid_shell_and_transform(self) -> None:
        raw = default_model_spec("unit_assembly_ellipsoid", "assembly_scene")
        raw["components"][1] = {
            "id": "helmet",
            "template": "ellipsoid_shell",
            "geometry": {"radius_x_m": 0.18, "radius_y_m": 0.14, "height_m": 0.12, "thickness_m": 0.003},
            "mesh": {"size_m": 0.03},
            "transform": {"center_m": [0.0, 0.0, 0.06], "rotate_deg": [0.0, 0.0, 15.0]},
            "fixed_faces": ["z_min"],
        }
        raw["contacts"] = [{"type": "automatic_surface_to_surface", "slave": "rod", "master": "helmet"}]
        keyword, metadata = build_keyword(parse_model_spec(raw))
        self.assertIn("helmet_ellipsoid_shell", keyword)
        self.assertIn("*ELEMENT_SHELL", keyword)
        self.assertIn("*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE", keyword)
        self.assertEqual(metadata["part_count"], 2)
        self.assertEqual(metadata["components"][1]["template"], "ellipsoid_shell")
        shell_lines = []
        in_shell = False
        for line in keyword.splitlines():
            if line == "*ELEMENT_SHELL":
                in_shell = True
                continue
            if in_shell and line.startswith("*"):
                break
            if in_shell and line and not line.startswith("$"):
                shell_lines.append(line)
        self.assertTrue(any(fields[-1] == fields[-2] for fields in (line.split(",") for line in shell_lines)))

    def test_rebar_drop_on_helmet_generates_solver_draft_cards(self) -> None:
        raw = rebar_drop_on_helmet_spec("unit_rebar_drop_on_helmet")
        keyword, metadata = build_keyword(parse_model_spec(raw))
        self.assertIn("rebar_solid_cylinder", keyword)
        self.assertIn("helmet_ellipsoid_shell", keyword)
        self.assertIn("*ELEMENT_SOLID", keyword)
        self.assertIn("*ELEMENT_SHELL", keyword)
        self.assertIn("*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE", keyword)
        self.assertIn("*LOAD_BODY_Z", keyword)
        self.assertIn("*DATABASE_BINARY_D3PLOT", keyword)
        self.assertEqual(metadata["model_type"], "assembly_scene")
        self.assertEqual(metadata["contact_count"], 1)
        self.assertEqual(metadata["load_count"], 1)
        self.assertGreater(metadata["shell_element_count"], 0)
        self.assertGreater(metadata["solid_element_count"], 0)

    def test_quasi_static_scenes_generate_stability_control_cards(self) -> None:
        for raw in [
            cube_top_corner_load_spec("unit_stable_cube_load"),
            plate_pressure_spec("unit_stable_plate_pressure"),
        ]:
            with self.subTest(scene=raw["geometry"]["scene"]):
                keyword, metadata = build_keyword(parse_model_spec(raw))
                self.assertIn("*HOURGLASS_TITLE", keyword)
                self.assertIn("*CONTROL_ENERGY", keyword)
                self.assertIn("*CONTROL_TIMESTEP", keyword)
                self.assertIn("*DEFINE_CURVE", keyword)
                self.assertEqual(metadata["hourglass_count"], 1)

    def test_cube_corner_load_selects_four_geometric_top_corners(self) -> None:
        keyword, _ = build_keyword(parse_model_spec(cube_top_corner_load_spec("unit_cube_geometric_corners")))
        lines = keyword.splitlines()

        node_start = lines.index("*NODE") + 2
        node_coordinates: dict[int, tuple[float, float, float]] = {}
        for line in lines[node_start:]:
            if line.startswith("*"):
                break
            if not line or line.startswith("$"):
                continue
            nid, x, y, z = line.split(",")[:4]
            node_coordinates[int(nid)] = (float(x), float(y), float(z))

        label_index = lines.index("$ node_set top_corner_nodes")
        selected_ids: list[int] = []
        for line in lines[label_index + 1 :]:
            if line.startswith("*"):
                break
            if line and not line.startswith("$"):
                selected_ids.extend(int(value) for value in line.split(",") if value)

        self.assertEqual(len(selected_ids), 4)
        selected_coordinates = {node_coordinates[nid] for nid in selected_ids}
        self.assertEqual(
            selected_coordinates,
            {(0.0, 0.0, 2.0), (2.0, 0.0, 2.0), (0.0, 2.0, 2.0), (2.0, 2.0, 2.0)},
        )

    def test_preflight_rejects_extreme_mesh_size(self) -> None:
        raw = default_model_spec("unit_tiny_mesh_rejected", "solid_block")
        raw["mesh"]["size_m"] = 1.0e-6
        with self.assertRaisesRegex(ValueError, "mesh preflight exceeded"):
            build_keyword(parse_model_spec(raw))

    def test_beam_bar_generates_valid_keyword_shape(self) -> None:
        raw = default_model_spec("unit_beam_bar", "beam_bar")
        raw["mesh"]["size_m"] = 0.02
        keyword, metadata = build_keyword(parse_model_spec(raw))
        self.assertIn("*ELEMENT_SOLID", keyword)
        self.assertIn("*SECTION_SOLID", keyword)
        self.assertIn("_beam_bar", keyword)
        self.assertEqual(metadata["model_type"], "beam_bar")
        self.assertEqual(metadata["element_family"], "solid")
        self.assertGreater(metadata["node_count"], 0)
        self.assertGreater(metadata["element_count"], 0)
        self.assertEqual(metadata["mesh"]["method"], "solid_hexa_bar")

    def test_loads_and_prescribed_displacement_generate_keyword_cards(self) -> None:
        raw = default_model_spec("unit_loads", "shell_plate")
        raw["boundary_conditions"] = [
            {"type": "fixed_edge", "edge": "x_min"},
            {"type": "prescribed_displacement", "edge": "x_max", "dof": "x", "value_m": 0.001},
        ]
        raw["loads"] = [
            {"type": "nodal_force", "edge": "y_max", "dof": "y", "value_n": 100.0},
            {"type": "gravity", "direction": "z", "acceleration_m_per_s2": -9.81},
        ]
        keyword, metadata = build_keyword(parse_model_spec(raw))
        self.assertIn("*BOUNDARY_SPC_SET", keyword)
        self.assertIn("*BOUNDARY_PRESCRIBED_MOTION_SET", keyword)
        self.assertIn("*LOAD_NODE_SET", keyword)
        self.assertIn("*LOAD_BODY_Z", keyword)
        self.assertIn("*DEFINE_CURVE", keyword)
        self.assertEqual(metadata["constraint_count"], 2)
        self.assertEqual(metadata["load_count"], 2)
        self.assertEqual(metadata["curve_count"], 3)
        self.assertEqual(metadata["node_set_count"], 3)

    def test_remaining_phase_four_cards_generate_from_named_sets(self) -> None:
        raw = default_model_spec("unit_phase_four_remaining", "shell_plate")
        raw["sets"] = [
            {"type": "node_set", "name": "left_edge", "selector": {"type": "edge", "edge": "x_min"}},
            {"type": "node_set", "name": "right_edge", "selector": {"type": "edge", "edge": "x_max"}},
            {"type": "segment_set", "name": "plate_surface", "selector": {"type": "face", "face": "z_max"}},
            {"type": "part_set", "name": "main_part", "part_ids": [1]},
        ]
        raw["boundary_conditions"] = [
            {"type": "fixed_edge", "target": {"type": "node_set", "name": "left_edge"}},
            {
                "type": "prescribed_velocity",
                "target": {"type": "node_set", "name": "right_edge"},
                "dof": "x",
                "value_m_per_s": 0.02,
                "curve": {"type": "constant", "value": 0.02, "end_time_s": 0.5},
            },
        ]
        raw["loads"] = [
            {
                "type": "pressure_on_segment_set",
                "target": {"type": "segment_set", "name": "plate_surface"},
                "pressure_pa": 1000.0,
                "curve": {"type": "table", "points": [[0.0, 0.0], [0.2, 1000.0], [0.5, 500.0]]},
            },
            {
                "type": "initial_velocity",
                "target": {"type": "part_set", "name": "main_part"},
                "vector_m_per_s": [1.0, 0.0, 0.0],
            },
        ]
        keyword, metadata = build_keyword(parse_model_spec(raw))
        self.assertIn("*SET_PART_LIST", keyword)
        self.assertIn("*SET_SEGMENT", keyword)
        self.assertIn("*BOUNDARY_PRESCRIBED_MOTION_SET", keyword)
        self.assertIn("*LOAD_SEGMENT_SET", keyword)
        self.assertIn("*INITIAL_VELOCITY_NODE", keyword)
        self.assertIn("0.2,1000", keyword)
        self.assertEqual(metadata["constraint_count"], 2)
        self.assertEqual(metadata["load_count"], 1)
        self.assertEqual(metadata["initial_condition_count"], 1)
        self.assertEqual(metadata["curve_count"], 2)
        self.assertEqual(metadata["node_set_count"], 2)
        self.assertEqual(metadata["segment_set_count"], 1)
        self.assertEqual(metadata["part_set_count"], 1)

    def test_uuc_like_single_element_extensions_generate_keyword_cards(self) -> None:
        raw = default_model_spec("unit_uuc_like", "single_solid_element_test")
        raw["material"] = {
            "name": "confirmed_cscm_concrete",
            "type": "cscm_concrete",
            "id": 2,
            "density_kg_per_m3": 2300,
            "fpc_pa": 50000000,
            "source": "user supplied UUC reference",
            "confirmed_by_user": True,
        }
        raw["curves"] = [{"id": 1, "name": "compression_displacement", "points": [[0.0, 0.0], [0.1, -0.0002]]}]
        raw["hourglass"] = {"id": 3, "title": "Hourglass 3", "ihq": 3, "qm": 0.05, "ibq": 1, "q1": 1.4, "q2": 0.5}
        raw["analysis_control"] = {
            "energy": {"hgen": 2, "rwen": 2, "slnten": 2, "rylen": 2},
            "shell": {"wrpang": 20.0},
            "timestep": {"tssfac": 0.9},
            "termination": {"end_time_s": 0.1},
        }
        raw["database"] = {"format": 0, "d3plot_dt_s": 0.0001, "d3thdt_dt_s": 0.0001, "extent_binary": {}}
        raw["sets"] = [{"type": "node_set", "name": "loaded_nodes", "node_ids": [1, 3, 7, 8]}]
        raw["boundary_conditions"] = [
            {"type": "spc_node_set", "node_ids": [1], "dofs": ["x", "z"]},
            {
                "type": "prescribed_displacement",
                "target": {"type": "node_set", "name": "loaded_nodes"},
                "dof": "y",
                "curve_id": 1,
            },
        ]
        raw["loads"] = [{"type": "pressure_on_segment", "curve_id": 1, "segment": [5, 6, 7, 8]}]
        keyword, metadata = build_keyword(parse_model_spec(raw))
        self.assertIn("*MAT_CSCM_CONCRETE", keyword)
        self.assertIn("*HOURGLASS_TITLE", keyword)
        self.assertIn("*BOUNDARY_SPC_SET", keyword)
        self.assertIn("*LOAD_SEGMENT", keyword)
        self.assertIn("*CONTROL_ENERGY", keyword)
        self.assertIn("*CONTROL_TIMESTEP", keyword)
        self.assertIn("*DATABASE_BINARY_D3THDT", keyword)
        self.assertIn("*DATABASE_EXTENT_BINARY", keyword)
        self.assertIn("1,1,2,0,3,0,0,0", keyword)
        self.assertEqual(metadata["model_type"], "single_solid_element_test")
        self.assertEqual(metadata["element_count"], 1)
        self.assertEqual(metadata["hourglass_count"], 1)
        self.assertEqual(metadata["curve_count"], 1)

    def test_supported_concrete_material_cards_generate(self) -> None:
        material_cases = [
            (
                "johnson_holmquist_concrete",
                {
                    "shear_modulus_pa": 14800000000,
                    "a": 0.79,
                    "b": 1.6,
                    "n": 0.61,
                    "fc_pa": 50000000,
                },
                "*MAT_JOHNSON_HOLMQUIST_CONCRETE",
            ),
            ("rht", {"shear_modulus_pa": 14800000000, "fc_pa": 50000000}, "*MAT_RHT"),
            ("concrete_damage_rel3", {"poisson": 0.2, "ft_pa": 4100000, "a0_pa": -50000000}, "*MAT_CONCRETE_DAMAGE_REL3"),
        ]
        for material_type, params, expected_card in material_cases:
            with self.subTest(material_type=material_type):
                raw = default_model_spec(f"unit_{material_type}", "single_solid_element_test")
                raw["material"] = {
                    "name": f"confirmed_{material_type}",
                    "type": material_type,
                    "density_kg_per_m3": 2300,
                    "source": "unit test confirmed source",
                    "confirmed_by_user": True,
                    **params,
                }
                raw["boundary_conditions"] = [{"type": "spc_node_set", "node_ids": [1], "dofs": ["x", "y", "z"]}]
                keyword, metadata = build_keyword(parse_model_spec(raw))
                self.assertIn(expected_card, keyword)
                self.assertEqual(metadata["element_count"], 1)

    def test_structured_user_defined_material_models_generates_uuc_card(self) -> None:
        raw = default_model_spec("unit_uuc_user_material", "single_solid_element_test")
        raw["material"] = {
            "name": "uuc_user_subroutine_material",
            "type": "user_defined_material_models",
            "id": 2,
            "density_kg_per_m3": 2300,
            "mt": 41,
            "lmc": 44,
            "nhv": 60,
            "iortho": 0,
            "ibulk": 3,
            "ig": 4,
            "ivect": 0,
            "ifail": 0,
            "itherm": 1,
            "ihyper": 0,
            "ieos": 0,
            "lmca": 2,
            "constants": [-50e6, None, 1.7900e10, 1.4060e10, "", 0.5, -1],
            "additional_constants": [123.0, None],
            "source": "E:/Desktop/Single element/UUC/UUC.k",
            "confirmed_by_user": True,
        }
        raw["boundary_conditions"] = [{"type": "spc_node_set", "node_ids": [1], "dofs": ["x", "y", "z"]}]
        keyword, metadata = build_keyword(parse_model_spec(raw))
        self.assertIn("*MAT_USER_DEFINED_MATERIAL_MODELS", keyword)
        self.assertIn("2,2300,41,44,60,0,3,4", keyword)
        self.assertIn("0,0,1,0,0,2,0,0", keyword)
        self.assertIn("-50000000,,1.79e+10,1.406e+10,,0.5,-1", keyword)
        self.assertIn("123,", keyword)
        self.assertIn("1,1,2,0,0,0,0,0", keyword)
        self.assertEqual(metadata["element_count"], 1)

    def test_user_defined_material_models_generates_title_and_orthotropic_cards(self) -> None:
        raw = default_model_spec("unit_uuc_user_material_ortho", "single_solid_element_test")
        raw["material"] = {
            "name": "orthotropic_user_material",
            "title": "orthotropic umat41",
            "type": "user_defined_material_models",
            "id": 2,
            "density_kg_per_m3": 2300,
            "mt": 41,
            "lmc": 8,
            "nhv": 2,
            "iortho": 1,
            "ibulk": 3,
            "ig": 4,
            "ihyper": 1,
            "constants": [1, 2, 3, 4],
            "orthotropic_axes": {"aopt": 2, "a1": 1, "a2": 0, "a3": 0, "d1": 0, "d2": 1, "d3": 0},
            "source": "unit test",
            "confirmed_by_user": True,
        }
        raw["boundary_conditions"] = [{"type": "spc_node_set", "node_ids": [1], "dofs": ["x", "y", "z"]}]
        keyword, _ = build_keyword(parse_model_spec(raw))
        self.assertIn("*MAT_USER_DEFINED_MATERIAL_MODELS_TITLE", keyword)
        self.assertIn("orthotropic umat41", keyword)
        self.assertIn("2,2300,41,8,2,1,3,4", keyword)
        self.assertIn("0,0,0,1,0,0,0,0", keyword)
        self.assertIn("2,1,0,0,0,1,0,0", keyword)


if __name__ == "__main__":
    unittest.main()
