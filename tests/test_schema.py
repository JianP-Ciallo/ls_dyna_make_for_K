from __future__ import annotations

import unittest

from lsprepost_mcp.config import DEFAULT_UNIT_SYSTEM
from lsprepost_mcp.schema import (
    cube_top_corner_load_spec,
    default_model_spec,
    parse_model_spec,
    plate_pressure_spec,
    rebar_drop_on_helmet_spec,
    rod_impact_plate_spec,
)


class SchemaTests(unittest.TestCase):
    def test_supported_generated_model_types_parse(self) -> None:
        for model_type in [
            "shell_plate",
            "solid_block",
            "shell_box",
            "cylinder_shell",
            "cylinder_solid",
            "beam_bar",
            "assembly_scene",
            "single_solid_element_test",
        ]:
            with self.subTest(model_type=model_type):
                spec = parse_model_spec(default_model_spec(f"{model_type}_test", model_type))
                self.assertEqual(spec.model_type, model_type)
                self.assertEqual(spec.unit_system, DEFAULT_UNIT_SYSTEM)

    def test_accepts_assembly_scene_surface_and_nodes_contact(self) -> None:
        raw = default_model_spec("assembly_schema", "assembly_scene")
        raw["contacts"].append(
            {
                "type": "automatic_nodes_to_surface",
                "slave": "rod",
                "master": "plate",
                "slave_face": "z_min",
                "friction": 0.1,
            }
        )
        spec = parse_model_spec(raw)
        self.assertEqual(spec.model_type, "assembly_scene")
        self.assertEqual(len(spec.components), 2)
        self.assertEqual(len(spec.contacts), 2)

    def test_rejects_assembly_scene_unknown_contact_component(self) -> None:
        raw = default_model_spec("assembly_bad_contact", "assembly_scene")
        raw["contacts"] = [{"type": "automatic_surface_to_surface", "slave": "missing", "master": "plate"}]
        with self.assertRaisesRegex(ValueError, "unknown component"):
            parse_model_spec(raw)

    def test_accepts_ellipsoid_shell_component_and_transform_options(self) -> None:
        raw = default_model_spec("assembly_ellipsoid_schema", "assembly_scene")
        raw["components"][1] = {
            "id": "helmet",
            "template": "ellipsoid_shell",
            "geometry": {"radius_x_m": 0.18, "radius_y_m": 0.14, "height_m": 0.12, "thickness_m": 0.003},
            "mesh": {"size_m": 0.03},
            "transform": {"center_m": [0, 0, 0.06], "rotate_deg": [0, 0, 15], "translate_m": [0, 0, 0]},
            "fixed_faces": ["z_min"],
        }
        raw["contacts"] = [{"type": "automatic_surface_to_surface", "slave": "rod", "master": "helmet"}]
        spec = parse_model_spec(raw)
        self.assertEqual(spec.components[1]["template"], "ellipsoid_shell")
        self.assertEqual(spec.components[1]["transform"]["rotate_deg"], [0, 0, 15])

    def test_accepts_rebar_drop_on_helmet_scene_spec(self) -> None:
        spec = parse_model_spec(rebar_drop_on_helmet_spec("schema_rebar_drop_on_helmet"))
        self.assertEqual(spec.model_type, "assembly_scene")
        self.assertEqual(spec.geometry["scene"], "rebar_drop_on_helmet")
        self.assertEqual([component["id"] for component in spec.components], ["rebar", "helmet"])
        self.assertEqual(spec.geometry["drop_height_m"], 0.5)
        self.assertEqual(spec.geometry["impact_velocity_m_per_s"], 10.0)
        self.assertEqual(spec.components[0]["transform"]["translate_m"][2], 0.62)
        self.assertEqual(spec.components[0]["initial_velocity_m_per_s"], [0.0, 0.0, -10.0])
        self.assertEqual(spec.components[1]["template"], "ellipsoid_shell")
        self.assertEqual(spec.loads[0]["type"], "gravity")
        self.assertEqual(spec.database["d3plot_dt_s"], 0.01)
        self.assertIn("extent_binary", spec.database)

    def test_accepts_phase7_scene_specs(self) -> None:
        rod_plate = parse_model_spec(rod_impact_plate_spec("schema_rod_impact_plate"))
        self.assertEqual(rod_plate.model_type, "assembly_scene")
        self.assertEqual(rod_plate.geometry["scene"], "rod_impact_plate")
        self.assertEqual([component["id"] for component in rod_plate.components], ["rod", "plate"])
        self.assertEqual(rod_plate.contacts[0]["type"], "automatic_surface_to_surface")

        cube = parse_model_spec(cube_top_corner_load_spec("schema_cube_top_corner_load"))
        self.assertEqual(cube.model_type, "solid_block")
        self.assertEqual(cube.geometry["scene"], "cube_top_corner_load")
        self.assertEqual(cube.sets[0]["selector"], {"type": "face_corners", "face": "z_max"})
        self.assertEqual(cube.loads[0]["type"], "nodal_force")

        plate = parse_model_spec(plate_pressure_spec("schema_plate_pressure"))
        self.assertEqual(plate.model_type, "shell_plate")
        self.assertEqual(plate.geometry["scene"], "plate_pressure")
        self.assertEqual(plate.sets[0]["type"], "segment_set")
        self.assertEqual(plate.loads[0]["type"], "pressure_on_segment_set")

    def test_phase7_scene_specs_use_solver_stable_defaults(self) -> None:
        rod_plate = parse_model_spec(rod_impact_plate_spec("stable_rod_impact_plate"))
        plate_component = next(component for component in rod_plate.components if component["id"] == "plate")
        self.assertEqual(plate_component["fixed_faces"], ["x_min", "x_max", "y_min", "y_max"])

        cube = parse_model_spec(cube_top_corner_load_spec("stable_cube_top_corner_load"))
        for dimension in ["length_m", "width_m", "height_m"]:
            self.assertGreaterEqual(cube.geometry[dimension] / cube.mesh["size_m"], 4.0)
        self.assertEqual(cube.loads[0]["curve"]["type"], "ramp")
        self.assertIn("energy", cube.analysis_control)
        self.assertIn("timestep", cube.analysis_control)
        self.assertTrue(cube.hourglass)

        plate = parse_model_spec(plate_pressure_spec("stable_plate_pressure"))
        self.assertEqual(plate.loads[0]["curve"]["type"], "ramp")
        self.assertIn("energy", plate.analysis_control)
        self.assertIn("timestep", plate.analysis_control)
        self.assertTrue(plate.hourglass)

    def test_rejects_legacy_unit_system(self) -> None:
        raw = default_model_spec("bad_units", "shell_plate")
        raw["unit_system"] = "mm_ms_g_N_MPa"
        with self.assertRaisesRegex(ValueError, "only unit_system"):
            parse_model_spec(raw)

    def test_rejects_project_name_that_would_be_silently_cleaned(self) -> None:
        raw = default_model_spec("unsafe/path", "shell_plate")
        with self.assertRaisesRegex(ValueError, "project_name"):
            parse_model_spec(raw)

    def test_rejects_windows_reserved_or_ambiguous_project_names(self) -> None:
        for project_name in ["CON", "nul", "COM1", "LPT9", "trailing_dot.", "trailing_space "]:
            with self.subTest(project_name=project_name):
                raw = default_model_spec(project_name, "shell_plate")
                with self.assertRaisesRegex(ValueError, "project_name"):
                    parse_model_spec(raw)

    def test_rejects_unconfirmed_advanced_material(self) -> None:
        raw = default_model_spec("bad_material", "shell_plate")
        raw["material"] = {
            "name": "lab_concrete",
            "type": "cscm_concrete",
            "density_kg_per_m3": 2300,
            "fpc_pa": 50000000,
            "source": "lab report",
        }
        with self.assertRaisesRegex(ValueError, "confirmed_by_user"):
            parse_model_spec(raw)

    def test_rejects_kc_rate_reference_to_missing_top_level_curve(self) -> None:
        raw = default_model_spec("missing_kc_rate_curve", "single_solid_element_test")
        raw["material"] = {
            "name": "kc_missing_rate_curve",
            "type": "concrete_damage_rel3",
            "parameter_mode": "automatic",
            "density_kg_per_m3": 2480.0,
            "poisson": 0.2,
            "fpc_pa": 133.5e6,
            "lcrate": 42,
            "source": "unit test",
            "confirmed_by_user": True,
        }

        with self.assertRaisesRegex(ValueError, "lcrate 42 references no top-level curve"):
            parse_model_spec(raw)

    def test_accepts_kc_rate_reference_to_defined_top_level_curve(self) -> None:
        raw = default_model_spec("defined_kc_rate_curve", "single_solid_element_test")
        raw["material"] = {
            "name": "kc_defined_rate_curve",
            "type": "concrete_damage_rel3",
            "parameter_mode": "automatic",
            "density_kg_per_m3": 2480.0,
            "poisson": 0.2,
            "fpc_pa": 133.5e6,
            "lcrate": 42,
            "source": "unit test",
            "confirmed_by_user": True,
        }
        raw["curves"] = [{"id": 42, "name": "rate", "points": [[0.0, 1.0], [1.0, 1.0]]}]

        self.assertEqual(42, parse_model_spec(raw).material["lcrate"])

    def test_rejects_d3plot_schedule_curve_id_collision(self) -> None:
        raw = default_model_spec("d3plot_curve_collision", "shell_plate")
        raw["curves"] = [{"id": 990001, "name": "load", "points": [[0.0, 0.0], [1.0, 1.0]]}]
        raw["database"] = {
            "d3plot_schedule": [{"until_time_s": 1.0, "dt_s": 0.1}],
            "d3plot_lcdt_curve_id": 990001,
        }

        with self.assertRaisesRegex(ValueError, "d3plot_lcdt_curve_id 990001 collides"):
            parse_model_spec(raw)

    def test_resolves_known_material_from_library(self) -> None:
        raw = default_model_spec("library_material", "shell_plate")
        raw["material"] = {"name": "aluminum_6061_t6"}
        spec = parse_model_spec(raw)
        self.assertEqual(spec.material["library_id"], "aluminum_6061_t6")
        self.assertEqual(spec.material["source_type"], "material_library")
        self.assertEqual(spec.material["unit_system"], DEFAULT_UNIT_SYSTEM)
        self.assertGreater(spec.material["density_kg_per_m3"], 0)

    def test_rejects_unknown_material_without_user_confirmation(self) -> None:
        raw = default_model_spec("unknown_material", "shell_plate")
        raw["material"] = {
            "name": "invented_steel",
            "type": "elastic",
            "density_kg_per_m3": 7800,
            "youngs_pa": 200000000000,
            "poisson": 0.3,
        }
        with self.assertRaisesRegex(ValueError, "unknown material"):
            parse_model_spec(raw)

    def test_rejects_string_nan_in_geometry(self) -> None:
        raw = default_model_spec("bad_nan_geometry", "shell_plate")
        raw["geometry"]["length_m"] = "NaN"
        with self.assertRaisesRegex(ValueError, "geometry.length_m must be finite"):
            parse_model_spec(raw)

    def test_rejects_string_infinity_in_legacy_mm_conversion(self) -> None:
        raw = default_model_spec("bad_inf_geometry", "shell_plate")
        raw["geometry"].pop("length_m")
        raw["geometry"]["length_mm"] = "Infinity"
        with self.assertRaisesRegex(ValueError, "geometry.length_mm must be finite"):
            parse_model_spec(raw)

    def test_rejects_string_nan_in_advanced_material(self) -> None:
        raw = default_model_spec("bad_nan_advanced_material", "shell_plate")
        raw["material"] = {
            "name": "bad_concrete",
            "type": "cscm_concrete",
            "density_kg_per_m3": "NaN",
            "fpc_pa": 50000000,
            "source": "unit test",
            "confirmed_by_user": True,
        }
        with self.assertRaisesRegex(ValueError, "material.density_kg_per_m3 must be finite"):
            parse_model_spec(raw)

    def test_accepts_confirmed_custom_material_with_source(self) -> None:
        raw = default_model_spec("custom_material", "shell_plate")
        raw["material"] = {
            "name": "lab_coupon_material",
            "type": "elastic",
            "density_kg_per_m3": 7800,
            "youngs_pa": 200000000000,
            "poisson": 0.29,
            "source": "user lab measurement report ABC-001",
            "confirmed_by_user": True,
        }
        spec = parse_model_spec(raw)
        self.assertEqual(spec.material["source_type"], "user_confirmed_custom")
        self.assertEqual(spec.material["source"], "user lab measurement report ABC-001")

    def test_rejects_user_defined_material_keyword_injection(self) -> None:
        raw = default_model_spec("bad_user_material", "shell_plate")
        raw["material"] = {
            "name": "unsafe_user_material",
            "type": "user_defined_material",
            "density_kg_per_m3": 1000,
            "source": "unit test",
            "confirmed_by_user": True,
            "card_lines": ["*MAT_USER_DEFINED_MATERIAL_MODELS", "1,1000", "*END"],
        }
        with self.assertRaisesRegex(ValueError, "forbidden keyword card"):
            parse_model_spec(raw)

    def test_accepts_structured_user_defined_material_models(self) -> None:
        raw = default_model_spec("uuc_user_material_schema", "single_solid_element_test")
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
        spec = parse_model_spec(raw)
        self.assertEqual(spec.material["type"], "user_defined_material_models")
        self.assertEqual(spec.material["mt"], 41)

    def test_accepts_user_defined_material_models_orthotropic_options(self) -> None:
        raw = default_model_spec("uuc_orthotropic_user_material_schema", "single_solid_element_test")
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
        spec = parse_model_spec(raw)
        self.assertEqual(spec.material["iortho"], 1)
        self.assertEqual(spec.material["orthotropic_axes"]["aopt"], 2)

    def test_rejects_user_defined_material_models_lmc_over_manual_limit(self) -> None:
        raw = default_model_spec("uuc_bad_lmc", "single_solid_element_test")
        raw["material"] = {
            "name": "bad_user_material",
            "type": "user_defined_material_models",
            "density_kg_per_m3": 2300,
            "mt": 41,
            "lmc": 49,
            "nhv": 0,
            "source": "unit test",
            "confirmed_by_user": True,
        }
        raw["boundary_conditions"] = [{"type": "spc_node_set", "node_ids": [1], "dofs": ["x", "y", "z"]}]
        with self.assertRaisesRegex(ValueError, "use lmca"):
            parse_model_spec(raw)

    def test_accepts_phase_four_boundary_and_load_types(self) -> None:
        raw = default_model_spec("phase_four_spec", "shell_plate")
        raw["boundary_conditions"] = [
            {"type": "fixed_edge", "edge": "x_min"},
            {"type": "prescribed_displacement", "edge": "x_max", "dof": "x", "value_m": 0.001},
        ]
        raw["loads"] = [
            {"type": "nodal_force", "edge": "y_max", "dof": "y", "value_n": 100.0},
            {"type": "gravity", "direction": "z", "acceleration_m_per_s2": -9.81},
        ]
        spec = parse_model_spec(raw)
        self.assertEqual(len(spec.boundary_conditions), 2)
        self.assertEqual(len(spec.loads), 2)

    def test_rejects_unsupported_load_type(self) -> None:
        raw = default_model_spec("bad_load", "shell_plate")
        raw["loads"] = [{"type": "contact", "edge": "x_max"}]
        with self.assertRaisesRegex(ValueError, "unsupported load type"):
            parse_model_spec(raw)

    def test_unknown_fields_are_reported_as_warnings(self) -> None:
        raw = default_model_spec("unknown_fields", "shell_plate")
        raw["geometry"]["unused_length_hint"] = 123
        raw["loads"] = [{"type": "nodal_force", "edge": "x_max", "dof": "x", "value_n": 100.0, "unused_force_hint": True}]
        spec = parse_model_spec(raw)
        warning_fields = {item["field"] for item in spec.warnings}
        self.assertIn("unused_length_hint", warning_fields)
        self.assertIn("unused_force_hint", warning_fields)

    def test_accepts_named_sets_curves_and_remaining_phase_four_loads(self) -> None:
        raw = default_model_spec("phase_four_remaining", "shell_plate")
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
        spec = parse_model_spec(raw)
        self.assertEqual(len(spec.sets), 4)
        self.assertEqual(len(spec.boundary_conditions), 2)
        self.assertEqual(len(spec.loads), 2)

    def test_rejects_bad_curve_table(self) -> None:
        raw = default_model_spec("bad_curve", "shell_plate")
        raw["loads"] = [
            {
                "type": "nodal_force",
                "edge": "x_max",
                "dof": "x",
                "value_n": 100.0,
                "curve": {"type": "table", "points": [[0.1, 0.0], [0.1, 100.0]]},
            }
        ]
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            parse_model_spec(raw)

    def test_rejects_unsupported_generated_part_id(self) -> None:
        raw = default_model_spec("bad_part_set", "shell_plate")
        raw["sets"] = [{"type": "part_set", "name": "bad_part", "part_ids": [2]}]
        with self.assertRaisesRegex(ValueError, "part id 1"):
            parse_model_spec(raw)

    def test_accepts_uuc_like_single_element_extensions(self) -> None:
        raw = default_model_spec("uuc_like_schema", "single_solid_element_test")
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
        raw["hourglass"] = {"id": 3, "ihq": 3, "qm": 0.05, "ibq": 1}
        raw["analysis_control"] = {
            "energy": {},
            "timestep": {"tssfac": 0.9},
            "termination": {"end_time_s": 0.1},
        }
        raw["database"] = {"format": 0, "d3plot_dt_s": 0.0001, "d3thdt_dt_s": 0.0001, "extent_binary": {}}
        raw["sets"] = [{"type": "node_set", "name": "top_nodes", "node_ids": [1, 3, 7, 8]}]
        raw["boundary_conditions"] = [
            {"type": "spc_node_set", "node_ids": [1], "dofs": ["x", "z"]},
            {
                "type": "prescribed_displacement",
                "target": {"type": "node_set", "name": "top_nodes"},
                "dof": "y",
                "curve_id": 1,
            },
        ]
        raw["loads"] = [{"type": "pressure_on_segment", "curve_id": 1, "segment": [5, 6, 7, 8]}]
        spec = parse_model_spec(raw)
        self.assertEqual(spec.model_type, "single_solid_element_test")
        self.assertEqual(spec.material["type"], "cscm_concrete")
        self.assertEqual(len(spec.curves), 1)


if __name__ == "__main__":
    unittest.main()
