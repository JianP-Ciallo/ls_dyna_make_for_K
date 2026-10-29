from __future__ import annotations

import unittest
import tempfile

from lsprepost_mcp.dyna_keyword import build_keyword
from lsprepost_mcp.keyword_checks import keyword_quality_checks, parse_keyword_model
from lsprepost_mcp.schema import default_model_spec, parse_model_spec, rod_impact_plate_spec


class KeywordQualityTests(unittest.TestCase):
    def test_generated_shell_plate_has_quality_estimates(self) -> None:
        raw = default_model_spec("quality_plate", "shell_plate")
        keyword, metadata = build_keyword(parse_model_spec(raw))
        checks = keyword_quality_checks(keyword, raw, metadata)
        by_id = {item["id"]: item for item in checks}
        self.assertTrue(by_id["quality.geometry.shell_area"]["ok"])
        self.assertTrue(by_id["quality.geometry.shell_normals"]["ok"])
        self.assertTrue(by_id["quality.topology.orphan_nodes"]["ok"])
        self.assertTrue(by_id["quality.estimate.mass"]["ok"])
        self.assertTrue(by_id["quality.estimate.stable_timestep"]["ok"])
        self.assertGreater(by_id["quality.estimate.mass"]["actual"]["mass_kg"], 0.0)
        self.assertGreater(by_id["quality.estimate.stable_timestep"]["actual"]["stable_dt_s"], 0.0)

    def test_assembly_shell_thickness_ratio_uses_component_mesh(self) -> None:
        spec = parse_model_spec(rod_impact_plate_spec("quality_rod_plate_ratio"))
        keyword, metadata = build_keyword(spec)
        checks = keyword_quality_checks(keyword, spec.__dict__, metadata)
        by_id = {item["id"]: item for item in checks}
        ratio = by_id["quality.shell.component.plate.thickness_mesh_ratio"]
        self.assertTrue(ratio["ok"])
        self.assertAlmostEqual(ratio["actual"], 0.08)

    def test_assembly_check_rejects_fully_fixed_shell_component(self) -> None:
        raw = rod_impact_plate_spec("quality_fully_fixed_plate")
        plate = next(component for component in raw["components"] if component["id"] == "plate")
        plate["fixed_faces"] = ["z_min"]
        spec = parse_model_spec(raw)
        keyword, metadata = build_keyword(spec)
        checks = keyword_quality_checks(keyword, spec.__dict__, metadata)
        by_id = {item["id"]: item for item in checks}
        result = by_id["quality.assembly.component.plate.deformable_nodes"]
        self.assertFalse(result["ok"])
        self.assertEqual(result["actual"]["fixed_node_count"], result["actual"]["node_count"])

    def test_detects_missing_node_reference_and_duplicate_node_id(self) -> None:
        keyword = """*KEYWORD
*NODE
1,0,0,0
1,1,0,0
2,1,1,0
3,0,1,0
*ELEMENT_SHELL
1,1,1,2,3,99
*PART
part
1,1,1,0,0,0,0,0
*SECTION_SHELL
1,2
0.001,0.001,0.001,0.001
*MAT_ELASTIC
1,7850,2.1e11,0.3
*END
"""
        checks = keyword_quality_checks(keyword, {"model_type": "shell_plate", "mesh": {"size_m": 0.01}}, {})
        by_id = {item["id"]: item for item in checks}
        self.assertFalse(by_id["quality.id.nodes_unique"]["ok"])
        self.assertFalse(by_id["quality.ref.element_nodes"]["ok"])

    def test_mat_add_erosion_is_not_a_second_material_definition(self) -> None:
        keyword = """*KEYWORD
*MAT_ELASTIC
90,2400,3.0e10,0.2
*MAT_ADD_EROSION
$#     mid      excl    mxpres      mneps
90,0,0,0.05
*END
"""
        model = parse_keyword_model(keyword)
        checks = keyword_quality_checks(keyword, {"model_type": "imported_keyword"}, {})
        by_id = {item["id"]: item for item in checks}

        self.assertEqual([90], model.material_id_list)
        self.assertEqual(2400.0, model.material_density[90])
        self.assertTrue(by_id["quality.id.materials_unique"]["ok"])
        self.assertTrue(by_id["quality.material.90.density_range"]["ok"])

    def test_detects_duplicate_set_ids_before_parser_overwrite(self) -> None:
        keyword = """*KEYWORD
*NODE
1,0,0,0
2,1,0,0
3,1,1,0
4,0,1,0
*SET_NODE_LIST
1301
1
*SET_NODE_LIST
1301
2
*SET_SEGMENT
1401
1,2,3,4
*SET_SEGMENT
1401
1,2,3,4
*END
"""
        checks = keyword_quality_checks(keyword, {"model_type": "imported_keyword"}, {})
        by_id = {item["id"]: item for item in checks}

        self.assertFalse(by_id["quality.id.node_sets_unique"]["ok"])
        self.assertEqual([1301], by_id["quality.id.node_sets_unique"]["actual"])
        self.assertFalse(by_id["quality.id.segment_sets_unique"]["ok"])
        self.assertEqual([1401], by_id["quality.id.segment_sets_unique"]["actual"])

    def test_detects_duplicate_curve_ids(self) -> None:
        keyword = """*KEYWORD
*DEFINE_CURVE
42,0,1,1,0,0,0,0
0,0
1,1
*DEFINE_CURVE_TITLE
duplicate
42,0,1,1,0,0,0,0
0,0
1,1
*END
"""

        checks = keyword_quality_checks(keyword, {"model_type": "imported_keyword"}, {})
        by_id = {item["id"]: item for item in checks}

        self.assertFalse(by_id["quality.id.curves_unique"]["ok"])
        self.assertEqual([42], by_id["quality.id.curves_unique"]["actual"])

    def test_detects_database_output_reference_to_missing_curve(self) -> None:
        keyword = """*KEYWORD
*DEFINE_CURVE
41,0,1,1,0,0,0,0
0,0
1,1
*DATABASE_BINARY_D3PLOT
0,42
*END
"""

        checks = keyword_quality_checks(keyword, {"model_type": "imported_keyword"}, {})
        by_id = {item["id"]: item for item in checks}

        self.assertFalse(by_id["quality.ref.database_output_curves"]["ok"])
        self.assertEqual([42], by_id["quality.ref.database_output_curves"]["actual"])

    def test_detects_incomplete_tied_node_contact_cards(self) -> None:
        keyword = """*KEYWORD
*NODE
1,0,0,0
2,1,0,0
3,1,1,0
4,0,1,0
*SET_NODE_LIST
1301
1
*SET_SEGMENT
1401
1,2,3,4
*CONTACT_TIED_NODES_TO_SURFACE
1301,1401,4,0,0,0,0,0
*END
"""
        checks = keyword_quality_checks(keyword, {"model_type": "imported_keyword"}, {})
        by_id = {item["id"]: item for item in checks}

        self.assertFalse(by_id["quality.keyword.tied_node_contact_card_arity"]["ok"])
        self.assertEqual(
            [{"line": 13, "data_line_count": 1}],
            by_id["quality.keyword.tied_node_contact_card_arity"]["actual"],
        )

    def test_detects_missing_tied_node_contact_set_references(self) -> None:
        keyword = """*KEYWORD
*CONTACT_TIED_NODES_TO_SURFACE
1301,1401,4,0,0,0,0,0
0,0,0,0,0,0,0,0
0,0,0,0,0,0,0,0
*END
"""
        checks = keyword_quality_checks(keyword, {"model_type": "imported_keyword"}, {})
        by_id = {item["id"]: item for item in checks}

        self.assertFalse(by_id["quality.ref.tied_contact_node_sets"]["ok"])
        self.assertEqual([1301], by_id["quality.ref.tied_contact_node_sets"]["actual"])
        self.assertFalse(by_id["quality.ref.tied_contact_segment_sets"]["ok"])
        self.assertEqual([1401], by_id["quality.ref.tied_contact_segment_sets"]["actual"])

    def test_rejects_embedded_end_before_final_end(self) -> None:
        keyword = """*KEYWORD
*NODE
1,0,0,0
*END
*MAT_ELASTIC
1,7850,2.1e11,0.3
*END
"""
        checks = keyword_quality_checks(keyword, {"model_type": "imported_keyword"}, {})
        by_id = {item["id"]: item for item in checks}
        self.assertFalse(by_id["quality.keyword.boundary"]["ok"])

    def test_rejects_fake_keyword_and_end_cards(self) -> None:
        keyword = """*KEYWORD_NOT_REAL
*NODE
1,0,0,0
*END_NOT_REAL
"""
        checks = keyword_quality_checks(keyword, {"model_type": "imported_keyword"}, {})
        by_id = {item["id"]: item for item in checks}
        self.assertFalse(by_id["quality.keyword.boundary"]["ok"])

    def test_detects_database_fsi_reference_to_missing_part(self) -> None:
        keyword = """*KEYWORD
*DATABASE_FSI
1.0e-5
1,3,1
*PART
existing
10,10,10
*SECTION_SHELL
10,2
0.01,0.01,0.01,0.01
*MAT_ELASTIC
10,7850,2.1e11,0.3
*END
"""
        checks = keyword_quality_checks(
            keyword,
            {"model_type": "imported_keyword"},
            {},
        )
        by_id = {item["id"]: item for item in checks}
        self.assertFalse(by_id["quality.ref.database_fsi_parts"]["ok"])
        self.assertEqual([3], by_id["quality.ref.database_fsi_parts"]["actual"])

    def test_detects_missing_and_empty_fsi_segment_set_references(self) -> None:
        keyword = """*KEYWORD
*SET_PART_LIST_TITLE
ALE material parts
100
1
*SET_SEGMENT_TITLE
Empty exposed interface
200
*CONSTRAINED_LAGRANGE_IN_SOLID
200,100,2,0,4,4,2,0
0,0,0.1,0,0.3,0,0,0.1
0,0,0,2,0.1,0,0,0
*DATABASE_FSI
1.0e-5
1,201,2
*PART
ALE air
1,1,1
*SECTION_SOLID
1,1
*MAT_NULL
1,1.225
*END
"""
        checks = keyword_quality_checks(keyword, {"model_type": "imported_keyword"}, {})
        by_id = {item["id"]: item for item in checks}
        self.assertFalse(by_id["quality.ref.database_fsi_segment_sets"]["ok"])
        self.assertEqual([201], by_id["quality.ref.database_fsi_segment_sets"]["actual"])
        self.assertFalse(by_id["quality.ref.fsi_slave_segment_sets_nonempty"]["ok"])
        self.assertEqual([200], by_id["quality.ref.fsi_slave_segment_sets_nonempty"]["actual"])

    def test_detects_missing_contact_boundary_and_blast_references(self) -> None:
        keyword = """*KEYWORD
*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE
501,502,2,2,0,0,0,0
0.2,0.2,0,0,0,0,0,0
*BOUNDARY_SPC_SET
601,0,1,1,1,1,1,1
*BOUNDARY_NON_REFLECTING
602,0,0
*INITIAL_DETONATION
99,0,0,0,0
*INITIAL_VOLUME_FRACTION_GEOMETRY
98,1,1,0
4,0,2
0,0,0,1,1,1,0,0
0,0,0,0,0,0,0,0
*PART
existing
1,1,1
*SECTION_SOLID
1,1
*MAT_NULL
1,1.225
*END
"""
        checks = keyword_quality_checks(keyword, {"model_type": "imported_keyword"}, {})
        by_id = {item["id"]: item for item in checks}
        self.assertFalse(by_id["quality.ref.contact_part_sets"]["ok"])
        self.assertEqual([501, 502], by_id["quality.ref.contact_part_sets"]["actual"])
        self.assertFalse(by_id["quality.ref.boundary_spc_node_sets"]["ok"])
        self.assertEqual([601], by_id["quality.ref.boundary_spc_node_sets"]["actual"])
        self.assertFalse(by_id["quality.ref.nonreflecting_segment_sets"]["ok"])
        self.assertEqual([602], by_id["quality.ref.nonreflecting_segment_sets"]["actual"])
        self.assertFalse(by_id["quality.ref.initial_detonation_parts"]["ok"])
        self.assertEqual([99], by_id["quality.ref.initial_detonation_parts"]["actual"])
        self.assertFalse(by_id["quality.ref.ivfg_parts"]["ok"])
        self.assertEqual([98], by_id["quality.ref.ivfg_parts"]["actual"])

    def test_detects_invalid_set_members_and_database_ale_set(self) -> None:
        keyword = """*KEYWORD
*SET_PART_LIST_TITLE
Broken part set
701
1,2
*SET_SOLID_LIST_TITLE
Broken solid set
702
10,11
*DATABASE_ALE
1.0e-5,703
11,12,13
*DATABASE_HISTORY_SOLID_SET
704
*PART
existing
1,1,1
*SECTION_SOLID
1,1
*MAT_NULL
1,1.225
*END
"""
        checks = keyword_quality_checks(keyword, {"model_type": "imported_keyword"}, {})
        by_id = {item["id"]: item for item in checks}
        self.assertFalse(by_id["quality.ref.part_sets"]["ok"])
        self.assertEqual([701], by_id["quality.ref.part_sets"]["actual"])
        self.assertFalse(by_id["quality.ref.solid_sets"]["ok"])
        self.assertEqual([702], by_id["quality.ref.solid_sets"]["actual"])
        self.assertFalse(by_id["quality.ref.database_ale_solid_sets"]["ok"])
        self.assertEqual([703], by_id["quality.ref.database_ale_solid_sets"]["actual"])
        self.assertFalse(by_id["quality.ref.database_history_solid_sets"]["ok"])
        self.assertEqual(
            [704],
            by_id["quality.ref.database_history_solid_sets"]["actual"],
        )

    def test_detects_direct_load_segment_that_is_not_an_element_face(self) -> None:
        keyword = """*KEYWORD
*NODE
1,0,0,0
2,1,0,0
3,1,1,0
4,0,1,0
5,0,0,1
6,1,0,1
7,1,1,1
8,0,1,1
*ELEMENT_SOLID
1,1,1,2,3,4,5,6,7,8
*PART
part
1,1,1,0,0,0,0,0
*SECTION_SOLID
1,1
*MAT_ELASTIC
1,7850,2.1e11,0.3
*LOAD_SEGMENT
1,1.0,0.0,1,2,3,5
*END
"""
        checks = keyword_quality_checks(keyword, {"model_type": "solid_block"}, {})
        by_id = {item["id"]: item for item in checks}
        self.assertFalse(by_id["quality.topology.load_segments_on_faces"]["ok"])

    def test_detects_inverted_solid_center_jacobian(self) -> None:
        keyword = """*KEYWORD
*NODE
1,0,0,0
2,1,0,0
3,1,1,0
4,0,1,0
5,0,0,1
6,1,0,1
7,1,1,1
8,0,1,1
*ELEMENT_SOLID
1,1,1,4,3,2,5,8,7,6
*PART
part
1,1,1,0,0,0,0,0
*SECTION_SOLID
1,1
*MAT_ELASTIC
1,7850,2.1e11,0.3
*END
"""
        checks = keyword_quality_checks(keyword, {"model_type": "solid_block"}, {})
        by_id = {item["id"]: item for item in checks}
        self.assertFalse(by_id["quality.geometry.solid_volume"]["ok"])

    def test_detects_high_solid_aspect_ratio(self) -> None:
        keyword = """*KEYWORD
*NODE
1,0,0,0
2,20,0,0
3,20,1,0
4,0,1,0
5,0,0,1
6,20,0,1
7,20,1,1
8,0,1,1
*ELEMENT_SOLID
1,1,1,2,3,4,5,6,7,8
*PART
part
1,1,1,0,0,0,0,0
*SECTION_SOLID
1,1
*MAT_ELASTIC
1,7850,2.1e11,0.3
*END
"""
        checks = keyword_quality_checks(keyword, {"model_type": "solid_block"}, {})
        by_id = {item["id"]: item for item in checks}
        self.assertTrue(by_id["quality.geometry.solid_volume"]["ok"])
        self.assertFalse(by_id["quality.geometry.solid_aspect_ratio"]["ok"])

    def test_detects_shell_warpage_and_aspect_ratio(self) -> None:
        keyword = """*KEYWORD
*NODE
1,0,0,0
2,20,0,0
3,20,1,1
4,0,1,0
*ELEMENT_SHELL
1,1,1,2,3,4
*PART
part
1,1,1,0,0,0,0,0
*SECTION_SHELL
1,2
0.001,0.001,0.001,0.001
*MAT_ELASTIC
1,7850,2.1e11,0.3
*END
"""
        checks = keyword_quality_checks(keyword, {"model_type": "shell_plate", "mesh": {"size_m": 1.0}}, {})
        by_id = {item["id"]: item for item in checks}
        self.assertFalse(by_id["quality.geometry.shell_warpage"]["ok"])
        self.assertFalse(by_id["quality.geometry.shell_aspect_ratio"]["ok"])

    def test_estimates_timestep_from_advanced_material_wave_speed(self) -> None:
        raw = default_model_spec("quality_concrete", "single_solid_element_test")
        raw["material"] = {
            "name": "confirmed_concrete",
            "type": "cscm_concrete",
            "density_kg_per_m3": 2300.0,
            "fpc_pa": 50000000.0,
            "wave_speed_m_per_s": 4200.0,
            "source": "unit test",
            "confirmed_by_user": True,
        }
        raw["boundary_conditions"] = [{"type": "spc_node_set", "node_ids": [1], "dofs": ["x", "y", "z"]}]
        spec = parse_model_spec(raw)
        keyword, metadata = build_keyword(spec)
        checks = keyword_quality_checks(keyword, spec.__dict__, metadata)
        by_id = {item["id"]: item for item in checks}
        self.assertTrue(by_id["quality.estimate.stable_timestep"]["ok"])
        self.assertGreater(by_id["quality.estimate.stable_timestep"]["actual"]["stable_dt_s"], 0.0)

    def test_detects_missing_include_parameter_and_contact_cards(self) -> None:
        keyword = """*KEYWORD
*INCLUDE
missing_mesh.k
*PARAMETER
R defined_value 1.0
*NODE
1,0,0,&missing_value
2,1,0,0
3,1,1,0
4,0,1,0
*ELEMENT_SHELL
1,1,1,2,3,4
*PART
part
1,1,1,0,0,0,0,0
*SECTION_SHELL
1,2
0.001,0.001,0.001,0.001
*MAT_ELASTIC
1,7850,2.1e11,0.3
*CONTACT_AUTOMATIC_SINGLE_SURFACE
*END
"""
        with tempfile.TemporaryDirectory() as tmp:
            checks = keyword_quality_checks(keyword, {"model_type": "imported_keyword"}, {"_project_dir": tmp})
        by_id = {item["id"]: item for item in checks}
        self.assertFalse(by_id["quality.keyword.include_paths"]["ok"])
        self.assertFalse(by_id["quality.keyword.parameters"]["ok"])
        self.assertFalse(by_id["quality.unsupported.contact_cards"]["ok"])

    def test_allows_generator_controlled_contact_cards(self) -> None:
        keyword = """*KEYWORD
*NODE
1,0,0,0
2,1,0,0
3,1,1,0
4,0,1,0
*ELEMENT_SHELL
1,1,1,2,3,4
*PART
plate
1,1,1,0,0,0,0,0
*SECTION_SHELL
1,2,0.833,5,1,0,0,0
0.001,0.001,0.001,0.001,0,0
*MAT_ELASTIC
1,7850,2.1e11,0.3
*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE
1001,1002,2,2,0,0,0,0
0.2,0.2,0,0,0,0,0,0
*END
"""
        checks = keyword_quality_checks(
            keyword,
            {"model_type": "assembly_scene", "mesh": {"size_m": 0.01}},
            {"controlled_contact_cards": ["*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE"]},
        )
        by_id = {item["id"]: item for item in checks}
        self.assertTrue(by_id["quality.unsupported.contact_cards"]["ok"])


if __name__ == "__main__":
    unittest.main()
