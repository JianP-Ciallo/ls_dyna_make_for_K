from __future__ import annotations

import json
import pathlib
import tempfile
import tracemalloc
import unittest

from lsprepost_mcp.keyword_decomposition import (
    _numbers,
    classify_resources,
    decompose_keyword_deck,
    normalize_2k_resource,
)


FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "phase18" / "2k_minimal_reference.k"


class KeywordDecompositionTests(unittest.TestCase):
    def test_normalize_2k_resource_converts_only_declared_quantity_units(self) -> None:
        # Break caught: a wrong conversion factor, target unit, or implicit conversion.
        cases = [
            ("density", 7.85e-9, "tonne/mm^3", 7850.0, "kg/m^3", 1e12),
            ("stress", 210000.0, "MPa", 210e9, "Pa", 1e6),
            ("velocity", 8193000.0, "mm/s", 8193.0, "m/s", 1e-3),
            ("energy_density", 640000.0, "MPa", 640e9, "J/m^3", 1e6),
            ("solver_sentinel", 0.0, "solver_semantic", 0.0, "solver_semantic", 1.0),
        ]

        for quantity, original, source_unit, expected, target_unit, factor in cases:
            with self.subTest(quantity=quantity):
                result = normalize_2k_resource(
                    {
                        "resource_kind": "material",
                        "fields": [{
                            "name": "value",
                            "value": original,
                            "quantity": quantity,
                            "source_unit": source_unit,
                        }],
                    }
                )

                self.assertEqual(
                    {
                        "original_value": original,
                        "original_unit": source_unit,
                        "factor": factor,
                        "value": expected,
                        "unit": target_unit,
                        "conversion_kind": (
                            "solver_semantic_passthrough"
                            if quantity == "solver_sentinel"
                            else "explicit_unit_conversion"
                        ),
                    },
                    result["normalized_fields"]["value"],
                )

        with self.assertRaises(ValueError):
            normalize_2k_resource(
                {"fields": [{"name": "bad", "value": 1.0, "quantity": "length", "source_unit": "cm"}]}
            )

    def test_classify_resources_builds_source_specific_inventory(self) -> None:
        # Break caught: treating Set IDs as globally unique, or publishing an unproven resource.
        source_path = pathlib.Path("E:/Desktop/2.k")
        if source_path.exists():
            report = decompose_keyword_deck(source_path, "tonne_mm_s_N_MPa")
        else:
            sha256 = "c1c02a9e832852854b47cd3720bc9348cf48989484d25e1a54036836d0697a22"
            starts = iter(range(10, 2000, 10))

            def records(ids, keyword, identity="id"):
                result = []
                for source_id in ids:
                    start = next(starts)
                    result.append({identity: source_id, "keyword": keyword, "source_line_start": start, "source_line_end": start + 2})
                return result

            parts = records([201, 202, 203, 301, 302, 303, 401, 402, 501, 502, 1001, 1002], "*PART", "pid")
            sections = records(range(1, 9), "*SECTION_SOLID_TITLE")
            materials = records([2, 3, 5, 8, 9, 10, 11, 12, 13, 14], "*MAT_SOURCE_TITLE")
            eos = records([1, 2], "*EOS_SOURCE_TITLE")
            curves = records([1, 2], "*DEFINE_CURVE_TITLE")
            sets = records([1], "*SET_NODE_LIST_TITLE") + records(range(1, 9), "*SET_PART_LIST_TITLE") + records([1], "*SET_SEGMENT")
            coupling_starts = [next(starts) for _ in range(5)]
            constrained = [{"ssid": index, "msid": index + 100, "sstyp": 0, "mstyp": 1} for index in range(5)]
            all_records = parts + sections + materials + eos + curves + sets
            raw_blocks = [
                {"normalized_keyword": row["keyword"], "keyword": row["keyword"], "source_line_start": row["source_line_start"], "source_line_end": row["source_line_end"], "raw_lines": []}
                for row in all_records
            ] + [
                {"normalized_keyword": "*CONSTRAINED_LAGRANGE_IN_SOLID", "keyword": "*CONSTRAINED_LAGRANGE_IN_SOLID", "source_line_start": start, "source_line_end": start + 2, "raw_lines": []}
                for start in coupling_starts
            ]
            for keyword in ("*MAT_ADD_EROSION", "*INITIAL_DETONATION", "*LOAD_BODY_PARTS", "*LOAD_BODY_Z", "*BOUNDARY_SPC_SET", "*BOUNDARY_NON_REFLECTING"):
                start = next(starts)
                raw_blocks.append({"normalized_keyword": keyword, "keyword": keyword, "source_line_start": start, "source_line_end": start, "raw_lines": []})
            start = next(starts)
            raw_blocks.append({
                "normalized_keyword": "*ALE_MULTI-MATERIAL_GROUP", "keyword": "*ALE_MULTI-MATERIAL_GROUP",
                "source_line_start": start, "source_line_end": start + 1,
                "raw_lines": [f"{1001:10d}{1:10d}", f"{1002:10d}{1:10d}"],
            })
            report = {
                "source": {"sha256": sha256}, "parts": parts, "sections": sections, "materials": materials,
                "eos": eos, "curves": curves, "sets": sets, "constrained_couplings": constrained,
                "unsupported_used_cards": [], "raw_keyword_blocks": raw_blocks,
            }

        inventory = classify_resources(report)

        self.assertEqual({"used", "dependency", "unused", "unsupported", "blockers"}, set(inventory))
        expected_used = {
            "part": {201, 202, 203, 301, 302, 303, 401, 402, 501, 502, 1001, 1002},
            "section": {1, 2, 3, 4, 5, 6},
            "material": {2, 3, 5, 8, 12, 14},
            "eos": {1, 2},
            "curve": {1, 2},
        }
        for resource_kind, expected_ids in expected_used.items():
            self.assertEqual(
                expected_ids,
                {row["source_id"] for row in inventory["used"] if row["resource_kind"] == resource_kind},
            )
        self.assertEqual(report["constrained_couplings"], [row["coupling"] for row in inventory["used"] if row["resource_kind"] == "coupling"])
        self.assertEqual(
            {
                ("*MAT_ADD_EROSION", 5), ("*INITIAL_DETONATION", 1002), ("*LOAD_BODY_PARTS", 4),
                ("*LOAD_BODY_Z", 2), ("*ALE_MULTI-MATERIAL_GROUP", 1001), ("*ALE_MULTI-MATERIAL_GROUP", 1002),
                ("*BOUNDARY_SPC_SET", 1), ("*BOUNDARY_NON_REFLECTING", 1),
            },
            {(row["keyword"], row["source_id"]) for row in inventory["dependency"]},
        )
        self.assertEqual(
            {("*SET_PART_LIST_TITLE", 5), ("*SET_PART_LIST_TITLE", 7), ("*SET_PART_LIST_TITLE", 8)},
            {(row["keyword"], row["source_id"]) for row in inventory["unused"] if row["resource_kind"] == "set"},
        )
        self.assertFalse(any(row["resource_kind"] == "set" and row["source_id"] == 1 for row in inventory["unused"]))
        self.assertEqual(
            {7, 8},
            {row["source_id"] for row in inventory["unused"] if row["resource_kind"] == "section"},
        )
        self.assertEqual(
            {9, 10, 11, 13},
            {row["source_id"] for row in inventory["unused"] if row["resource_kind"] == "material"},
        )
        self.assertTrue({"KC_RATE_CURVE_REQUIRES_REVIEW", "MID8_SHARED_ACROSS_D8_D18", "OVERLAPPING_EMBEDDED_COUPLINGS", "SOLVER_SENTINELS_REQUIRE_FIELD_AWARE_HANDLING", "NO_SOLVER_OR_EXPERIMENTAL_VALIDATION"}.issubset({row["code"] for row in inventory["blockers"]}))

        sample = inventory["used"][0]
        for key in ("resource_kind", "source_id", "keyword", "source_line_start", "source_line_end", "usage", "validation_status", "requires_project_review", "source_sha256", "raw_block"):
            self.assertIn(key, sample)
        self.assertEqual("source_reference", sample["validation_status"])
        self.assertTrue(sample["requires_project_review"])
        self.assertEqual(report["source"]["sha256"], sample["source_sha256"])
        self.assertIsNotNone(sample["raw_block"])
        self.assertIsInstance(sample["source_line_start"], int)

        rejected = dict(report)
        rejected["source"] = dict(report["source"], sha256="0" * 64)
        with self.assertRaises(ValueError):
            classify_resources(rejected)

    def test_streams_reference_deck_into_mesh_and_dependency_report(self) -> None:
        report = decompose_keyword_deck(FIXTURE, "tonne_mm_s_N_MPa")

        self.assertEqual("tonne_mm_s_N_MPa", report["source"]["units"])
        self.assertEqual(2575, report["source"]["byte_size"])
        self.assertEqual("f3282857f1bf3c01f1d4d47d3eef13bfbfb9d094f120d814cd047bf40aa18690", report["source"]["sha256"])
        self.assertEqual(67, report["source"]["line_count"])
        self.assertEqual(
            {
                "*KEYWORD": 1, "*NODE": 1, "*ELEMENT_SOLID": 1, "*ELEMENT_BEAM": 1,
                "*PART": 2, "*SECTION_SOLID_TITLE": 1, "*SECTION_BEAM_TITLE": 1,
                "*MAT_CONCRETE_DAMAGE_REL3_TITLE": 1, "*MAT_ADD_EROSION": 1,
                "*DEFINE_CURVE": 1, "*MAT_PLASTIC_KINEMATIC_TITLE": 1,
                "*CONSTRAINED_LAGRANGE_IN_SOLID_TITLE": 1, "*END": 1,
                "*SET_NODE_LIST_TITLE": 1, "*SET_PART_LIST_TITLE": 1, "*SET_SEGMENT_TITLE": 1,
            },
            report["keyword_counts"],
        )
        self.assertEqual(14, report["mesh"]["node_record_count"])
        self.assertEqual(14, report["mesh"]["unique_node_id_count"])
        self.assertEqual([], report["mesh"]["duplicate_node_ids"])
        self.assertEqual({"solid": 1, "beam": 2}, report["mesh"]["element_count_by_type"])
        self.assertEqual({"201": 1, "202": 2}, report["mesh"]["element_count_by_pid"])
        self.assertEqual(3, report["mesh"]["unique_element_id_count"])
        self.assertEqual([], report["mesh"]["duplicate_element_ids"])
        self.assertEqual(
            [{"node_ids": [12, 13], "classification": "beam_orientation_only", "node_roles": [{"node_id": 12, "roles": ["beam_orientation"]}, {"node_id": 13, "roles": ["beam_orientation"]}]}],
            report["mesh"]["exact_coordinate_duplicate_groups"],
        )
        self.assertEqual([99], report["mesh"]["orphan_node_ids"])
        self.assertEqual(
            [
                {"title": "Concrete solid", "pid": 201, "secid": 4, "mid": 5, "eosid": 0},
                {"title": "Rebar beam", "pid": 202, "secid": 3, "mid": 14, "eosid": 0},
            ],
            report["parts"],
        )
        self.assertEqual(
            [{"id": 4, "source_line_start": 30, "source_line_end": 32}, {"id": 3, "source_line_start": 33, "source_line_end": 35}],
            [{"id": row["id"], "source_line_start": row["source_line_start"], "source_line_end": row["source_line_end"]} for row in report["sections"]],
        )
        self.assertEqual(
            [{"id": 5, "source_line_start": 36, "source_line_end": 40}, {"id": 14, "source_line_start": 47, "source_line_end": 49}],
            [{"id": row["id"], "source_line_start": row["source_line_start"], "source_line_end": row["source_line_end"]} for row in report["materials"]],
        )
        self.assertEqual(
            [{"id": 1, "source_line_start": 43, "source_line_end": 46}],
            [{"id": row["id"], "source_line_start": row["source_line_start"], "source_line_end": row["source_line_end"]} for row in report["curves"]],
        )
        self.assertEqual([], report["eos"])
        self.assertEqual(
            {"mid": 5, "curve_ids": [1], "add_erosion": True},
            report["material_dependencies"]["5"],
        )
        self.assertEqual(
            [{"ssid": 202, "msid": 201, "sstyp": 1, "mstyp": 1}],
            report["constrained_couplings"],
        )
        self.assertEqual(
            [
                {
                    "keyword": "*SET_NODE_LIST_TITLE", "id": 501,
                    "source_line_start": 53, "source_line_end": 57,
                    "member_record_count": 2,
                    "member_rows": [[1, 2, 3, 4, 5, 6, 7, 8], [9, 10, 11]],
                },
                {
                    "keyword": "*SET_PART_LIST_TITLE", "id": 601,
                    "source_line_start": 58, "source_line_end": 61,
                    "member_record_count": 1,
                    "member_rows": [[201, 202]],
                },
                {
                    "keyword": "*SET_SEGMENT_TITLE", "id": 701,
                    "source_line_start": 62, "source_line_end": 66,
                    "member_record_count": 2,
                    "member_rows": [[1, 2, 3, 4], [5, 6, 7, 8]],
                },
            ],
            report["sets"],
        )
        self.assertEqual([], report["parse_warnings"])
        self.assertEqual([], report["unsupported_used_cards"])
        self.assertEqual(
            {"normalized_keyword": "*KEYWORD", "keyword": "*KEYWORD", "raw_keyword_line": "*KEYWORD", "source_line_start": 1, "source_line_end": 2, "raw_lines": ["$ Compact fixed-width Phase 18 reference deck"]},
            report["raw_keyword_blocks"][0],
        )
        json.dumps(report)

    def test_parses_concatenated_fixed_width_ten_node_solid_connectivity(self) -> None:
        node_fields = [10000001, 10000002, 10000003, 10000004, 10000005, 10000006, 10000007, 10000008, 0, 0]
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "solid-connectivity.k"
            deck.write_text(
                "*KEYWORD\n*ELEMENT_SOLID\n      42       7\n"
                + "".join(f"{node:8d}" for node in node_fields)
                + "\n*END\n",
                encoding="utf-8",
            )
            report = decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")

        self.assertEqual(
            [10000001, 10000002, 10000003, 10000004, 10000005, 10000006, 10000007, 10000008],
            report["mesh"]["missing_node_references"],
        )

    def test_parses_partially_concatenated_fixed_width_solid_connectivity(self) -> None:
        node_fields = [1, 2, 7264690, 12468341, 12480166, 3, 4, 5, 0, 0]
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "partial-solid-connectivity.k"
            deck.write_text(
                "*KEYWORD\n*ELEMENT_SOLID\n      42       7\n"
                + "".join(f"{node:8d}" for node in node_fields)
                + "\n*END\n",
                encoding="utf-8",
            )
            report = decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")

        self.assertEqual(
            [1, 2, 3, 4, 5, 7264690, 12468341, 12480166],
            report["mesh"]["missing_node_references"],
        )

    def test_parses_partially_concatenated_fixed_width_beam_connectivity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "partial-beam-connectivity.k"
            deck.write_text(
                "*KEYWORD\n*ELEMENT_BEAM\n"
                + "".join(f"{field:8d}" for field in [544496, 502, 7264690, 12468341, 12480166])
                + "\n*END\n",
                encoding="utf-8",
            )
            report = decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")

        self.assertEqual([7264690, 12468341, 12480166], report["mesh"]["missing_node_references"])

    def test_title_cards_skip_numeric_title_lines_before_identity_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "numeric-titles.k"
            deck.write_text(
                "*KEYWORD\n*SECTION_SOLID_TITLE\n8\n4,1\n"
                "*EOS_LINEAR_POLYNOMIAL_TITLE\n12\n9,1,0,0\n"
                "*DEFINE_CURVE_TITLE\n16\n1,0,1,1,0,0,0,0\n"
                "*MAT_PLASTIC_KINEMATIC_TITLE\n20\n14,7.85000E-9,0,0\n*END\n",
                encoding="utf-8",
            )
            report = decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")

        self.assertEqual([4], [section["id"] for section in report["sections"]])
        self.assertEqual([9], [equation["id"] for equation in report["eos"]])
        self.assertEqual([1], [curve["id"] for curve in report["curves"]])
        self.assertEqual([14], [material["id"] for material in report["materials"]])

    def test_part_title_skips_hyperworks_comments_and_keeps_untitled_comma_part(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "annotated-parts.k"
            deck.write_text(
                "*KEYWORD\n*PART\n$HWCOLOR COMP 17\n$NAME rebar_group\n$# title metadata\nRebar cage\n"
                "201,4,5,0,0,0,0,0\n*PART\n202,3,14,0,0,0,0,0\n*END\n",
                encoding="utf-8",
            )
            report = decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")

        self.assertEqual(
            [
                {"title": "Rebar cage", "pid": 201, "secid": 4, "mid": 5, "eosid": 0},
                {"title": "", "pid": 202, "secid": 3, "mid": 14, "eosid": 0},
            ],
            report["parts"],
        )

    def test_nonmesh_cards_keep_comma_positions_and_parse_fixed_width_columns(self) -> None:
        row10 = lambda values: "".join(f"{value:10d}" for value in values)
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "nonmesh-columns.k"
            deck.write_text(
                "*KEYWORD\n*PART\n"
                + row10([201, 4, 5, 0, 0, 0, 0, 0])
                + "\n*SECTION_SOLID\n"
                + row10([4, 1, 0, 0, 0, 0, 0, 0])
                + "\n*DEFINE_CURVE\n"
                + row10([1, 0, 1, 1, 0, 0, 0, 0])
                + "\n*SET_NODE_LIST\n"
                + row10([501])
                + "\n"
                + row10([1, 2, 3, 4, 5, 6, 7, 8])
                + "\n*CONSTRAINED_LAGRANGE_IN_SOLID\n"
                + row10([202, 201, 1, 1, 0, 0, 0, 0])
                + "\n*MAT_CONCRETE_DAMAGE_REL3\n5,2.4E-9,0,0,0,0,0,0\n0,0,0,0,0,0,0,0\n0,0,,,,1,0,0\n"
                + "*DEFINE_CURVE\n1,0,1,1,0,0,0,0\n*END\n",
                encoding="utf-8",
            )
            report = decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")

        self.assertEqual(201, report["parts"][0]["pid"])
        self.assertEqual(4, report["sections"][0]["id"])
        self.assertEqual([1, 1], [curve["id"] for curve in report["curves"]])
        self.assertEqual(1, report["sets"][0]["member_record_count"])
        self.assertEqual(202, report["constrained_couplings"][0]["ssid"])
        self.assertEqual([1], report["material_dependencies"]["5"]["curve_ids"])

    def test_part_parses_fully_occupied_ten_column_fields_with_trailing_padding(self) -> None:
        fields = [1234567890, 1234567891, 1234567892, 1234567893, 1234567894, 1234567895, 1234567896, 1234567897]
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "padded-ten-column-part.k"
            deck.write_text(
                "*KEYWORD\n*PART\n" + "".join(str(value) for value in fields) + "    \n*END\n",
                encoding="utf-8",
            )
            report = decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")

        self.assertEqual(
            {"title": "", "pid": 1234567890, "secid": 1234567891, "mid": 1234567892, "eosid": 1234567893},
            report["parts"][0],
        )

    def test_fixed_width_fields_keep_declared_blank_tail_separate_from_padding(self) -> None:
        occupied = ["12345678", "12345679", "12345680", "12345681"]
        row = "".join(occupied) + " " * (4 * 8) + " " * 4

        self.assertEqual(occupied + ["", "", "", ""], _numbers(row, layout=(8,) * 8))

    def test_signed_zero_coordinates_form_one_beam_orientation_duplicate_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "signed-zero-n3.k"
            deck.write_text(
                "*KEYWORD\n*NODE\n1,1,0,0\n2,2,0,0\n3,0.0,0.0,0.0\n4,-0.0,0.0,-0.0\n"
                "*ELEMENT_BEAM\n10,2,1,2,3\n11,2,1,2,4\n*END\n",
                encoding="utf-8",
            )
            report = decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")

        self.assertEqual(
            [{"node_ids": [3, 4], "classification": "beam_orientation_only", "node_roles": [{"node_id": 3, "roles": ["beam_orientation"]}, {"node_id": 4, "roles": ["beam_orientation"]}]}],
            report["mesh"]["exact_coordinate_duplicate_groups"],
        )

    def test_solid_preserves_nonzero_nine_and_ten_as_topology_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "solid-ten-topology.k"
            deck.write_text(
                "*KEYWORD\n*ELEMENT_SOLID\n      42       7\n"
                + "".join(f"{node:8d}" for node in range(1, 11))
                + "\n*END\n",
                encoding="utf-8",
            )
            report = decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")

        self.assertEqual(list(range(1, 11)), report["mesh"]["missing_node_references"])

    def test_coordinate_duplicates_keep_beam_orientation_roles_in_mixed_groups(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "mixed-duplicate-roles.k"
            deck.write_text(
                "*KEYWORD\n*NODE\n1,0,0,0\n2,1,0,0\n3,0,0,0\n4,0,0,0\n"
                "*ELEMENT_BEAM\n10,2,1,2,3\n*ELEMENT_SOLID\n20,2\n4,1,2,1,2,1,2,1,0,0\n*END\n",
                encoding="utf-8",
            )
            report = decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")

        group = report["mesh"]["exact_coordinate_duplicate_groups"][0]
        self.assertEqual("mixed_beam_orientation_and_topology", group["classification"])
        self.assertEqual(
            [
                {"node_id": 1, "roles": ["topology"]},
                {"node_id": 3, "roles": ["beam_orientation"]},
                {"node_id": 4, "roles": ["topology"]},
            ],
            group["node_roles"],
        )

    def test_reports_unimplemented_cards_even_when_they_share_a_known_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "unsupported-shell.k"
            deck.write_text("*KEYWORD\n*ELEMENT_SHELL\n1,1,1,2,3,4\n*MAT_ELASTIC\n1,1,1,0.3\n*END\n", encoding="utf-8")
            report = decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")

        self.assertEqual(
            [
                {"keyword": "*ELEMENT_SHELL", "source_line_start": 2},
                {"keyword": "*MAT_ELASTIC", "source_line_start": 4},
            ],
            report["unsupported_used_cards"],
        )

    def test_raw_nonmesh_block_keeps_original_keyword_line_and_normalized_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "raw-keyword.k"
            deck.write_text("*mat_plastic_kinematic_title (format)  \n20\n14,7.85E-9,0,0\n*END\n", encoding="utf-8")
            report = decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")

        block = report["raw_keyword_blocks"][0]
        self.assertEqual("*mat_plastic_kinematic_title (format)  ", block["raw_keyword_line"])
        self.assertEqual("*MAT_PLASTIC_KINEMATIC_TITLE", block["normalized_keyword"])

    def test_malformed_nonmesh_semantic_fields_become_line_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "malformed-nonmesh.k"
            deck.write_text(
                "*KEYWORD\n*PART\nBroken part\n201,not-a-section,5,0\n"
                "*SET_NODE_LIST\nnot-a-set\n1,2,3\n"
                "*CONSTRAINED_LAGRANGE_IN_SOLID\n202,bad,1,1\n*END\n",
                encoding="utf-8",
            )
            report = decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")

        self.assertEqual([], report["parts"])
        self.assertEqual([], report["sets"])
        self.assertEqual([], report["constrained_couplings"])
        self.assertEqual([4, 6, 9], [warning["line"] for warning in report["parse_warnings"]])

    def test_synthetic_streaming_mesh_stays_within_memory_budget(self) -> None:
        node_count = 40000
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "streaming-budget.k"
            with deck.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write("*KEYWORD\n*NODE\n")
                for node_id in range(1, node_count + 1):
                    handle.write(f"{node_id},0,0,{node_id}\n")
                handle.write("*ELEMENT_BEAM\n")
                for element_id in range(1, node_count - 1, 2):
                    handle.write(f"{element_id},{1},{element_id},{element_id + 1},{element_id + 2}\n")
                handle.write("*END\n")
            tracemalloc.start()
            decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

        self.assertLess(peak, 24 * 1024 * 1024)

    def test_parses_concatenated_ten_column_material_identity_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "fixed-width-materials.k"
            deck.write_text(
                "*KEYWORD\n*MAT_CONCRETE_DAMAGE_REL3_TITLE\nConcrete\n"
                "         52.40000E-9         0         0         0         0         0         0         0\n"
                "*MAT_PLASTIC_KINEMATIC_TITLE\nRebar\n"
                "        147.85000E-9         0         0         0         0         0         0         0\n*END\n",
                encoding="utf-8",
            )
            report = decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")

        self.assertEqual([5, 14], [material["id"] for material in report["materials"]])

    def test_concrete_material_reads_lcrate_from_third_ten_column_card(self) -> None:
        first_card = f"{5:10d}{'2.40000E-9':>10}" + "".join(f"{0:10d}" for _ in range(8))
        third_card = "".join(f"{value:10d}" for value in [0, 0, 0, 0, 0, 1, 0, 0, 0, 0])
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "concrete-lcrate.k"
            deck.write_text(
                "*KEYWORD\n*MAT_CONCRETE_DAMAGE_REL3_TITLE\nConcrete\n"
                + first_card
                + "\n"
                + "".join(f"{0:10d}" for _ in range(10))
                + "\n"
                + third_card
                + "\n*DEFINE_CURVE\n1,0,1,1,0,0,0,0\n*DEFINE_CURVE\n2,0,1,1,0,0,0,0\n*END\n",
                encoding="utf-8",
            )
            report = decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")

        self.assertEqual([1], report["material_dependencies"]["5"]["curve_ids"])

    def test_constrained_lagrange_keeps_main_row_before_control_continuations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "constrained-continuations.k"
            deck.write_text(
                "*KEYWORD\n*CONSTRAINED_LAGRANGE_IN_SOLID_TITLE\nEmbedded rebar\n"
                "202,201,1,1,0,0,0,0\n"
                "0.0,1.0,0.0,0.0,0.0,0.0,0.0,0.0\n"
                "0,0,0,0,0,0,0,0\n"
                "0,0,0,0,0,0,0,0\n*END\n",
                encoding="utf-8",
            )
            report = decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")

        self.assertEqual(
            [{"ssid": 202, "msid": 201, "sstyp": 1, "mstyp": 1}],
            report["constrained_couplings"],
        )

    def test_reports_missing_element_node_references_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "missing-node.k"
            deck.write_text("*KEYWORD\n*NODE\n1,0,0,0\n*ELEMENT_BEAM\n10,2,1,99,1\n*END\n", encoding="utf-8")
            report = decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")

        self.assertEqual([99], report["mesh"]["missing_node_references"])
        self.assertEqual(
            [{"message": "element references missing node", "node_id": 99}],
            report["parse_warnings"],
        )

    def test_lists_used_cards_outside_the_supported_decomposition_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "unsupported.k"
            deck.write_text("*KEYWORD\n*DATABASE_BINARY_D3PLOT\n1.0\n*END\n", encoding="utf-8")
            report = decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")

        self.assertEqual(
            [{"keyword": "*DATABASE_BINARY_D3PLOT", "source_line_start": 2}],
            report["unsupported_used_cards"],
        )

    def test_concrete_material_dependency_uses_its_declared_lcrate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            deck = pathlib.Path(directory) / "two-curves.k"
            deck.write_text(
                "*KEYWORD\n*MAT_CONCRETE_DAMAGE_REL3\n5,2400,0,0,0,0,0,0\n"
                "0,0,0,0,0,0,0,0\n0,0,0,0,0,1,0,0\n"
                "*DEFINE_CURVE\n1,0,1,1,0,0,0,0\n*DEFINE_CURVE\n2,0,1,1,0,0,0,0\n*END\n",
                encoding="utf-8",
            )
            report = decompose_keyword_deck(deck, "tonne_mm_s_N_MPa")

        self.assertEqual([1], report["material_dependencies"]["5"]["curve_ids"])


if __name__ == "__main__":
    unittest.main()
