from __future__ import annotations

import unittest
from unittest.mock import patch

import lsprepost_mcp.refined_building.asset_compiler as compiler_module
import lsprepost_mcp.refined_building.asset_templates as template_module
import lsprepost_mcp.refined_building.nonstructural as nonstructural_module
import lsprepost_mcp.refined_building.reinforcement as reinforcement_module
from lsprepost_mcp.refined_building import compile_detailed_building_asset


COMMERCIAL_ID = "commercial_supermarket_detailed_building"
RESIDENTIAL_ID = "residential_community_detailed_building"
SUBWAY_ID = "subway_entrance_detailed_building"
SMALL_COMMERCIAL = {
    "length_m": 6.0,
    "width_m": 4.0,
    "height_m": 3.0,
    "wall_thickness_m": 0.20,
    "entrance_width_m": 2.0,
    "entrance_height_m": 2.0,
}
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


class Phase18DGenerationBudgetTests(unittest.TestCase):
    def test_solid_limit_rejects_ten_million_axis_probe_before_coordinates(self) -> None:
        geometry = {
            **SMALL_COMMERCIAL,
            "length_m": 10.0,
            "wall_thickness_m": 0.000004,
        }
        with patch.object(
            template_module,
            "_axis_coordinates_for_upper_bound",
            side_effect=AssertionError("axis coordinates were materialized"),
        ):
            with self.assertRaisesRegex(
                ValueError,
                r"Solid elements .* limit 1",
            ):
                compile_detailed_building_asset(
                    COMMERCIAL_ID,
                    legacy_geometry=geometry,
                    structural_system="rc_frame",
                    fidelity_profile="structural_core",
                    mesh_profile="coarse",
                    generation_options={
                        "max_solid_elements": 1,
                        "reinforcement_mode": "concrete_only",
                    },
                )

    def test_tiny_rebar_spacing_rejects_before_position_or_beam_generation(self) -> None:
        with patch.object(
            reinforcement_module,
            "_positions",
            side_effect=AssertionError("rebar positions were materialized"),
        ):
            with self.assertRaisesRegex(ValueError, r"Beam elements .* limit 1"):
                compile_detailed_building_asset(
                    COMMERCIAL_ID,
                    legacy_geometry=SMALL_COMMERCIAL,
                    mesh_profile="coarse",
                    generation_options={
                        "max_beam_elements": 1,
                        "rebar_spacing_m": 1.0e-9,
                    },
                )

    def test_shell_limit_rejects_before_panel_axes_are_materialized(self) -> None:
        with patch.object(
            nonstructural_module,
            "_axis_coordinates",
            side_effect=AssertionError("panel axes were materialized"),
        ):
            with self.assertRaisesRegex(ValueError, r"Shell elements .* limit 1"):
                compile_detailed_building_asset(
                    COMMERCIAL_ID,
                    legacy_geometry=SMALL_COMMERCIAL,
                    mesh_profile="coarse",
                    generation_options={
                        "max_shell_elements": 1,
                        "reinforcement_mode": "concrete_only",
                    },
                )

    def test_node_and_total_limits_reject_before_artifact_compilation(self) -> None:
        cases = (
            ("max_node_count", "Node count"),
            ("max_total_elements", "Total elements"),
        )
        for option, family_label in cases:
            with self.subTest(option=option):
                with patch.object(
                    compiler_module,
                    "_compile_asset_definition",
                    side_effect=AssertionError("artifact compilation started"),
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        rf"{family_label} .* limit 1",
                    ):
                        compile_detailed_building_asset(
                            COMMERCIAL_ID,
                            legacy_geometry=SMALL_COMMERCIAL,
                            fidelity_profile="structural_core",
                            mesh_profile="coarse",
                            generation_options={
                                option: 1,
                                "reinforcement_mode": "concrete_only",
                            },
                        )

    def test_huge_storey_count_rejects_before_residential_rows_are_built(self) -> None:
        with patch.object(
            template_module,
            "_residential_spatial_rows",
            side_effect=AssertionError("residential rows were allocated"),
        ):
            with self.assertRaisesRegex(ValueError, r"Total elements .* limit 1"):
                compile_detailed_building_asset(
                    RESIDENTIAL_ID,
                    legacy_geometry=SMALL_RESIDENTIAL,
                    mesh_profile="coarse",
                    generation_options={
                        "storey_count": 10_000_000,
                        "max_total_elements": 1,
                        "reinforcement_mode": "concrete_only",
                    },
                )

    def test_residential_family_limits_reject_before_storey_rows_are_built(self) -> None:
        geometry = {
            **SMALL_RESIDENTIAL,
            "tower_height_m": 3_000.0,
        }
        cases = (
            ("max_solid_elements", "Solid elements"),
            ("max_beam_elements", "Beam elements"),
            ("max_shell_elements", "Shell elements"),
            ("max_node_count", "Node count"),
        )
        for option, family_label in cases:
            with self.subTest(option=option):
                with patch.object(
                    template_module,
                    "_residential_spatial_rows",
                    side_effect=AssertionError("residential rows were allocated"),
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        rf"{family_label} .* limit 1",
                    ):
                        compile_detailed_building_asset(
                            RESIDENTIAL_ID,
                            legacy_geometry=geometry,
                            mesh_profile="coarse",
                            generation_options={
                                "storey_count": 1_000,
                                option: 1,
                            },
                        )

    def test_residential_lower_bound_ignores_roles_inapplicable_to_system(self) -> None:
        package = compile_detailed_building_asset(
            RESIDENTIAL_ID,
            legacy_geometry=SMALL_RESIDENTIAL,
            structural_system="rc_frame",
            mesh_profile="coarse",
            generation_options={
                "reinforcement_mode": "custom",
                "include_reinforcement_roles": ["wall_rebar"],
                "max_beam_elements": 1,
            },
        )

        self.assertEqual(0, package.mesh_manifest["counts"]["beams"])

    def test_huge_subway_bay_count_rejects_before_component_rows_are_built(self) -> None:
        with patch.object(
            template_module,
            "_subway_pavilion_and_equipment_components",
            side_effect=AssertionError("subway component rows were allocated"),
        ):
            with self.assertRaisesRegex(ValueError, r"Shell elements .* limit 1"):
                compile_detailed_building_asset(
                    SUBWAY_ID,
                    legacy_geometry=SMALL_SUBWAY,
                    mesh_profile="coarse",
                    generation_options={
                        "glazing_bay_count": 10_000_000,
                        "max_shell_elements": 1,
                    },
                )

    def test_subway_family_limits_reject_before_bay_axes_are_built(self) -> None:
        cases = (
            ("max_solid_elements", "Solid elements"),
            ("max_beam_elements", "Beam elements"),
            ("max_node_count", "Node count"),
            ("max_total_elements", "Total elements"),
        )
        for option, family_label in cases:
            with self.subTest(option=option):
                with patch.object(
                    template_module,
                    "_subway_route_walkable_elevation",
                    side_effect=AssertionError("subway bay axes were allocated"),
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        rf"{family_label} .* limit 1",
                    ):
                        compile_detailed_building_asset(
                            SUBWAY_ID,
                            legacy_geometry=SMALL_SUBWAY,
                            mesh_profile="coarse",
                            generation_options={
                                "glazing_bay_count": 100_000,
                                option: 1,
                            },
                        )

    def test_public_limits_cannot_raise_hard_caps_or_expose_axis_cap(self) -> None:
        for option in (
            "max_solid_elements",
            "max_beam_elements",
            "max_shell_elements",
            "max_node_count",
            "max_total_elements",
        ):
            with self.subTest(option=option):
                with self.assertRaisesRegex(ValueError, rf"{option} .* hard cap"):
                    compile_detailed_building_asset(
                        COMMERCIAL_ID,
                        legacy_geometry=SMALL_COMMERCIAL,
                        mesh_profile="coarse",
                        generation_options={option: 10**12},
                    )
        with self.assertRaisesRegex(ValueError, "unsupported generation option"):
            compile_detailed_building_asset(
                COMMERCIAL_ID,
                legacy_geometry=SMALL_COMMERCIAL,
                mesh_profile="coarse",
                generation_options={"max_axis_coordinate_count": 1},
            )

    def test_small_asset_manifest_reports_safe_family_preflight(self) -> None:
        package = compile_detailed_building_asset(
            COMMERCIAL_ID,
            legacy_geometry=SMALL_COMMERCIAL,
            mesh_profile="coarse",
        )
        preflight = package.mesh_manifest["preflight"]
        actual = package.mesh_manifest["counts"]
        expected_families = {
            "solid_elements": actual["solids"],
            "beam_elements": actual["beams"],
            "shell_elements": actual["shells"],
            "node_count": actual["nodes"],
            "total_elements": actual["solids"] + actual["beams"] + actual["shells"],
        }
        self.assertEqual(set(expected_families), set(preflight))
        for family, actual_count in expected_families.items():
            with self.subTest(family=family):
                row = preflight[family]
                self.assertIn(row["estimation_kind"], {"exact", "proved_upper_bound"})
                self.assertGreaterEqual(row["estimated_count"], actual_count)
                self.assertLessEqual(row["estimated_count"], row["limit"])

    def test_explicit_budget_changes_request_fingerprint_not_artifact_mesh(self) -> None:
        arguments = {
            "legacy_geometry": SMALL_COMMERCIAL,
            "mesh_profile": "coarse",
            "fidelity_profile": "structural_core",
            "generation_options": {"reinforcement_mode": "concrete_only"},
        }
        baseline = compile_detailed_building_asset(COMMERCIAL_ID, **arguments)
        repeat = compile_detailed_building_asset(COMMERCIAL_ID, **arguments)
        limited = compile_detailed_building_asset(
            COMMERCIAL_ID,
            **{
                **arguments,
                "generation_options": {
                    "reinforcement_mode": "concrete_only",
                    "max_beam_elements": 100_000,
                },
            },
        )
        self.assertEqual(baseline.package_fingerprint, repeat.package_fingerprint)
        self.assertNotIn("max_beam_elements", baseline.generation_options)
        self.assertEqual(100_000, limited.generation_options["max_beam_elements"])
        self.assertNotEqual(baseline.package_fingerprint, limited.package_fingerprint)
        self.assertEqual(
            baseline.artifacts[0].mesh.fingerprint,
            limited.artifacts[0].mesh.fingerprint,
        )


if __name__ == "__main__":
    unittest.main()
