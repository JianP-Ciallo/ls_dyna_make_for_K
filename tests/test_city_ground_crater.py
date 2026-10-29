from __future__ import annotations

from copy import deepcopy
import unittest

from lsprepost_mcp.city_ground_crater import default_ground_response
from lsprepost_mcp.city_street_blast import (
    build_city_street_blast_keyword,
    default_city_street_blast_spec,
    validate_city_street_blast_spec,
)
from lsprepost_mcp.keyword_checks import (
    keyword_quality_checks,
    r12_kc_automatic_issues,
)


def crater_spec(project_name: str) -> dict[str, object]:
    spec = default_city_street_blast_spec(project_name)
    spec["ground_response"] = default_ground_response()
    return spec


class CityGroundCraterTests(unittest.TestCase):
    def test_crater_defaults_resolve_mesh_aligned_depths(self) -> None:
        resolved = validate_city_street_blast_spec(
            crater_spec("unit_crater_defaults")
        )
        ground = resolved["ground_response"]

        self.assertEqual("city_ground_crater_v1", ground["capability_version"])
        self.assertEqual(5, ground["actual_ale_overlap_layers"])
        self.assertEqual(1.0, ground["ale_overlap_depth_m"])
        self.assertEqual(3.0, ground["eroding_zone_half_width_m"])
        self.assertEqual(1.4, ground["eroding_ground_depth_m"])
        self.assertEqual(0.4, ground["support_depth_m"])
        self.assertAlmostEqual(1.8, ground["total_ground_depth_m"])
        self.assertEqual(-1.0, resolved["domain"]["min_m"][2])

    def test_crater_depth_can_raise_actual_overlap_layers(self) -> None:
        spec = crater_spec("unit_crater_deeper_overlap")
        spec["ground_response"]["anticipated_crater_depth_m"] = 1.05

        ground = validate_city_street_blast_spec(spec)["ground_response"]

        self.assertEqual(8, ground["actual_ale_overlap_layers"])
        self.assertEqual(1.6, ground["ale_overlap_depth_m"])
        self.assertEqual(3.0, ground["eroding_zone_half_width_m"])

    def test_legacy_spec_keeps_ground_elevation_and_no_crater_block(self) -> None:
        spec = default_city_street_blast_spec("unit_crater_legacy")

        resolved = validate_city_street_blast_spec(spec)

        self.assertNotIn("ground_response", resolved)
        self.assertEqual(0.0, resolved["domain"]["min_m"][2])

    def test_crater_rejects_foundation_intersection(self) -> None:
        spec = crater_spec("unit_crater_foundation")
        spec["explosive"]["base_center_m"] = [-30.0, 16.0, 0.01]

        with self.assertRaisesRegex(
            ValueError,
            "crater_zone_intersects_foundation",
        ):
            validate_city_street_blast_spec(spec)

    def test_crater_rejects_unknown_and_nonfinite_fields(self) -> None:
        unknown = crater_spec("unit_crater_unknown")
        unknown["ground_response"]["raw_keyword"] = "*END"
        with self.assertRaisesRegex(ValueError, "unknown properties"):
            validate_city_street_blast_spec(unknown)

        nonfinite = crater_spec("unit_crater_nonfinite")
        nonfinite["ground_response"]["anticipated_crater_depth_m"] = "NaN"
        with self.assertRaisesRegex(ValueError, "finite number"):
            validate_city_street_blast_spec(nonfinite)

    def test_crater_rejects_unsupported_mesh_and_preset(self) -> None:
        mesh = crater_spec("unit_crater_mesh")
        mesh["mesh"]["near_size_m"] = 0.18
        with self.assertRaisesRegex(ValueError, "ground mesh size"):
            validate_city_street_blast_spec(mesh)

        erosion = crater_spec("unit_crater_erosion")
        erosion["ground_response"]["erosion_mode"] = "early_sensitivity"
        with self.assertRaisesRegex(ValueError, "standard_observation"):
            validate_city_street_blast_spec(erosion)

    def test_custom_erosion_requires_strict_confirmation(self) -> None:
        spec = crater_spec("unit_crater_custom_erosion")
        ground = spec["ground_response"]
        ground["erosion_mode"] = "custom"
        ground["maximum_principal_strain"] = 0.04
        ground["confirmed_by_user"] = "true"

        with self.assertRaisesRegex(ValueError, "confirmed_by_user=true"):
            validate_city_street_blast_spec(spec)

        confirmed = deepcopy(spec)
        confirmed["ground_response"]["confirmed_by_user"] = True
        resolved = validate_city_street_blast_spec(confirmed)
        self.assertEqual(
            0.04,
            resolved["ground_response"]["maximum_principal_strain"],
        )

    def test_crater_keyword_contains_solid_ground_and_split_fsi(self) -> None:
        keyword, metadata = build_city_street_blast_keyword(
            crater_spec("unit_crater_keyword")
        )
        ground = metadata["ground_response"]

        self.assertGreater(ground["solid_element_count"], 0)
        self.assertGreater(ground["minimum_initial_solid_volume_m3"], 0.0)
        self.assertEqual(5, ground["eroding_fsi"]["ctype"])
        self.assertEqual(
            [ground["eroding_part_id"]],
            ground["eroding_fsi"]["slave_part_ids"],
        )
        self.assertGreater(
            ground["eroding_fsi"]["initial_exposed_segment_count"],
            0,
        )
        self.assertEqual(4, ground["peripheral_fsi"]["ctype"])
        self.assertGreater(
            ground["peripheral_fsi"]["exposed_segment_count"],
            0,
        )
        self.assertEqual(0, ground["duplicate_fsi_face_count"])
        self.assertGreater(ground["foundation_tie_count"], 0)
        self.assertIn("*MAT_CONCRETE_DAMAGE_REL3", keyword)
        self.assertIn("*MAT_ADD_EROSION", keyword)
        self.assertIn("*DATABASE_EXTENT_BINARY", keyword)
        self.assertIn("*DATABASE_HISTORY_SOLID_SET", keyword)
        self.assertIn("*CONTACT_TIED_NODES_TO_SURFACE", keyword)
        self.assertIn("$ ground crater eroding FSI CTYPE=5", keyword)
        self.assertNotIn("ALE ground reflection nodes", keyword)

    def test_crater_elout_history_covers_every_eroding_ground_element(self) -> None:
        keyword, metadata = build_city_street_blast_keyword(
            crater_spec("unit_crater_complete_deletion_history")
        )
        lines = keyword.splitlines()
        title_index = lines.index("K&C crater response and deletion history")
        self.assertEqual("1204", lines[title_index + 1])
        history_ids: list[int] = []
        for line in lines[title_index + 2 :]:
            if line.startswith("*"):
                break
            history_ids.extend(
                int(value) for value in line.split(",") if value.strip()
            )

        ground = metadata["ground_response"]
        self.assertEqual(
            ground["part_element_counts"]["90"],
            len(history_ids),
        )
        self.assertTrue(set(ground["probe_solid_ids"]).issubset(history_ids))

    def test_crater_keyword_allocates_r12_curve_table_for_kc_auto_rate(self) -> None:
        keyword, _metadata = build_city_street_blast_keyword(
            crater_spec("unit_crater_r12_kc_curve_table")
        )

        self.assertIn("*DEFINE_CURVE_TITLE", keyword)
        self.assertEqual([], r12_kc_automatic_issues(keyword))

        curve_start = keyword.index("*DEFINE_CURVE_TITLE")
        curve_end = keyword.index("*DATABASE_BINARY_D3PLOT", curve_start)
        without_curve = keyword[:curve_start] + keyword[curve_end:]
        issue_ids = {
            item["id"] for item in r12_kc_automatic_issues(without_curve)
        }
        self.assertIn("kc_automatic_curve_table_missing", issue_ids)

    def test_crater_mode_preserves_individual_city_response_interfaces(
        self,
    ) -> None:
        _keyword, metadata = build_city_street_blast_keyword(
            crater_spec("unit_crater_city_objects")
        )
        response_ids = {
            item["object_id"] for item in metadata["response_objects"]
        }

        self.assertIn("commercial_supermarket", response_ids)
        self.assertIn("residential_community", response_ids)
        self.assertIn("subway_entrance", response_ids)
        self.assertTrue(
            {f"parked_vehicle_{index}" for index in range(1, 5)}
            <= response_ids
        )
        self.assertTrue(
            {f"traffic_light_{index}" for index in range(1, 5)}
            <= response_ids
        )

    def test_crater_source_move_regenerates_ground_mesh_fingerprint(self) -> None:
        baseline = crater_spec("unit_crater_source_baseline")
        _keyword, before = build_city_street_blast_keyword(baseline)
        moved = deepcopy(baseline)
        moved["project_name"] = "unit_crater_source_moved"
        moved["explosive"]["base_center_m"] = [4.0, -4.0, 0.01]

        _keyword, after = build_city_street_blast_keyword(moved)

        self.assertNotEqual(
            before["ground_response"]["mesh_fingerprint"],
            after["ground_response"]["mesh_fingerprint"],
        )
        self.assertEqual(
            after["explosive"]["center_m"][:2],
            after["ground_response"]["source_center_m"][:2],
        )

    def test_resolved_crater_spec_can_be_regenerated_without_manual_field_stripping(self) -> None:
        _keyword, first = build_city_street_blast_keyword(
            crater_spec("unit_crater_round_trip_source")
        )
        resolved = deepcopy(first["resolved_spec"])
        resolved["project_name"] = "unit_crater_round_trip_target"

        _rebuilt_keyword, rebuilt = build_city_street_blast_keyword(resolved)

        self.assertEqual(
            first["ground_response"],
            rebuilt["ground_response"],
        )

    def test_resolved_crater_spec_rejects_tampered_derived_ground_fields(self) -> None:
        _keyword, first = build_city_street_blast_keyword(
            crater_spec("unit_crater_round_trip_tampered")
        )
        resolved = deepcopy(first["resolved_spec"])
        resolved["ground_response"]["actual_ale_overlap_layers"] += 1

        with self.assertRaisesRegex(ValueError, "derived ground_response"):
            build_city_street_blast_keyword(resolved)

    def test_crater_keyword_quality_gates_are_fail_closed(self) -> None:
        spec = crater_spec("unit_crater_quality")
        keyword, metadata = build_city_street_blast_keyword(spec)
        checks = keyword_quality_checks(keyword, spec, metadata)
        crater_checks = {
            item["id"]: item
            for item in checks
            if item["id"].startswith("quality.city_ground_crater.")
        }

        self.assertEqual(7, len(crater_checks))
        self.assertTrue(all(item["ok"] for item in crater_checks.values()))

        tampered = keyword.replace("*MAT_ADD_EROSION", "*MAT_ELASTIC", 1)
        failed = {
            item["id"]: item
            for item in keyword_quality_checks(tampered, spec, metadata)
        }
        self.assertFalse(
            failed["quality.city_ground_crater.required_cards"]["ok"]
        )

        lines = keyword.splitlines()
        title_index = lines.index("K&C crater response and deletion history")
        end_index = next(
            index
            for index in range(title_index + 2, len(lines))
            if lines[index].startswith("*")
        )
        incomplete = "\n".join(
            lines[: title_index + 2]
            + [str(metadata["ground_response"]["probe_solid_ids"][0])]
            + lines[end_index:]
        )
        incomplete_checks = {
            item["id"]: item
            for item in keyword_quality_checks(incomplete, spec, metadata)
        }
        self.assertFalse(
            incomplete_checks[
                "quality.city_ground_crater.deletion_history_coverage"
            ]["ok"]
        )


if __name__ == "__main__":
    unittest.main()
