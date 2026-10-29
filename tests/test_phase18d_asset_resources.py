from __future__ import annotations

import copy
import json
import math
import shutil
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from lsprepost_mcp.config import MODEL_LIBRARY_DIR
from lsprepost_mcp.model_library import list_model_resources
from lsprepost_mcp.refined_building import compile_detailed_building_asset
from lsprepost_mcp.refined_building.asset_resources import (
    get_detailed_building_asset,
    list_detailed_building_assets,
    load_detailed_building_asset_rows,
    validate_detailed_building_asset_resource,
)
from lsprepost_mcp.refined_building.systems import list_structural_systems


EXPECTED_IDS = (
    "commercial_supermarket_detailed_building",
    "residential_community_detailed_building",
    "subway_entrance_detailed_building",
)
EXPECTED_FIDELITY_PROFILES = (
    "structural_core",
    "blast_response",
    "research_detailed",
)
EXPECTED_MESH_PROFILES = ("coarse", "standard", "fine")
GENERIC_UNRESOLVED_MATERIAL_ROLES = (
    "facade",
    "glazing",
    "doors",
    "nonstructural",
)
SUBWAY_ONLY_MATERIAL_ROLES = (
    "metal_roof",
    "signage",
    "escalator_equipment",
    "escalator_balustrade",
    "escalator_handrail",
)
SMALL_COMPILE_ARGUMENTS: dict[str, dict[str, object]] = {
    "commercial_supermarket_detailed_building": {
        "legacy_geometry": {
            "length_m": 6.0,
            "width_m": 4.0,
            "height_m": 3.0,
            "wall_thickness_m": 0.20,
            "entrance_width_m": 2.0,
            "entrance_height_m": 2.0,
        },
        "mesh_profile": "coarse",
    },
    "residential_community_detailed_building": {
        "legacy_geometry": {
            "tower_count": 2,
            "tower_length_m": 3.6,
            "tower_width_m": 3.6,
            "tower_height_m": 3.0,
            "tower_spacing_m": 0.8,
            "wall_thickness_m": 0.20,
            "balcony_depth_m": 0.60,
        },
        "mesh_profile": "coarse",
        "generation_options": {"rebar_spacing_m": 0.50},
    },
    "subway_entrance_detailed_building": {
        "legacy_geometry": {
            "length_m": 4.0,
            "width_m": 3.0,
            "platform_height_m": 0.30,
            "enclosure_height_m": 2.40,
            "wall_thickness_m": 0.20,
            "roof_thickness_m": 0.20,
        },
        "mesh_profile": "coarse",
        "generation_options": {"rebar_spacing_m": 0.50},
    },
}


class Phase18DDetailedBuildingAssetResourceTests(unittest.TestCase):
    def test_listing_is_sorted_and_disjoint_from_fixed_k_resources(self) -> None:
        # Mutation caught: changing discovery to scan asset.json as fixed-K manifests.
        assets = list_detailed_building_assets()

        self.assertEqual(EXPECTED_IDS, tuple(row.resource_id for row in assets))
        self.assertTrue(
            set(EXPECTED_IDS).isdisjoint({row["id"] for row in list_model_resources()})
        )

    def test_default_listing_ignores_valid_sibling_phase_assets(self) -> None:
        # Mutation caught: widening default discovery or deleting sibling-phase resources.
        source = load_detailed_building_asset_rows()[EXPECTED_IDS[0]]
        source["id"] = "phase18e_sibling_probe_detailed_building"
        source["source_reference_lineage"]["asset_resource_id"] = source["id"]
        sibling_phase_root = MODEL_LIBRARY_DIR / "detailed_buildings" / "phase18e"
        sibling_root = (
            sibling_phase_root
            / "phase18d_default_root_probe"
        )
        sentinel = sibling_phase_root / "phase18d_preexisting_sentinel.txt"
        created_sibling_phase_root = not sibling_phase_root.exists()
        self.assertFalse(sibling_root.exists())
        self.assertFalse(sentinel.exists())
        sibling_root.mkdir(parents=True)
        sentinel.write_text("preserve sibling phase resources", encoding="utf-8")

        def remove_test_sentinel() -> None:
            sentinel.unlink(missing_ok=True)
            if (
                created_sibling_phase_root
                and sibling_phase_root.exists()
                and not any(sibling_phase_root.iterdir())
            ):
                sibling_phase_root.rmdir()

        def assert_sentinel_survives_probe_cleanup() -> None:
            self.assertTrue(sentinel.is_file())

        def remove_test_probe() -> None:
            shutil.rmtree(sibling_root)

        self.addCleanup(remove_test_sentinel)
        self.addCleanup(assert_sentinel_survives_probe_cleanup)
        self.addCleanup(remove_test_probe)
        (sibling_root / "asset.json").write_text(
            json.dumps(source, sort_keys=True), encoding="utf-8"
        )

        self.assertEqual(
            EXPECTED_IDS,
            tuple(row.resource_id for row in list_detailed_building_assets()),
        )

    def test_get_rejects_empty_and_unknown_resource_ids(self) -> None:
        # Mutation caught: returning an arbitrary descriptor for invalid lookup keys.
        for resource_id in ("", "   ", "not_a_detailed_building"):
            with self.subTest(resource_id=resource_id):
                with self.assertRaisesRegex(ValueError, "resource_id|unknown"):
                    get_detailed_building_asset(resource_id)

    def test_descriptors_are_frozen_and_deterministic(self) -> None:
        # Mutation caught: exposing mutable resource state or rebuilding rows nondeterministically.
        first = list_detailed_building_assets()
        second = list_detailed_building_assets()

        self.assertEqual(first, second)
        self.assertEqual(first[0], get_detailed_building_asset(first[0].resource_id))
        with self.assertRaises(FrozenInstanceError):
            first[0].resource_id = "changed"  # type: ignore[misc]

    def test_descriptors_expose_exact_profiles_meshes_and_material_candidates(self) -> None:
        # Mutation caught: dropping a declared asset contract while preserving basic discovery.
        for descriptor in list_detailed_building_assets():
            with self.subTest(resource_id=descriptor.resource_id):
                self.assertEqual(EXPECTED_FIDELITY_PROFILES, descriptor.fidelity_profiles)
                self.assertEqual("blast_response", descriptor.default_fidelity_profile)
                self.assertEqual(EXPECTED_MESH_PROFILES, descriptor.mesh_profiles)
                self.assertEqual("standard", descriptor.default_mesh_profile)
                self.assertFalse(descriptor.solver_ready)
                self.assertTrue(descriptor.requires_project_review)
                self.assertEqual(
                    {
                        "concrete": "two_storey_rc_frame_mid5_concrete_kc",
                        "reinforcing_steel": "two_storey_rc_frame_mid8_rebar_d8_d18",
                        "structural_steel": "mild_steel_mat24_demo",
                    },
                    descriptor.material_candidates,
                )
                self.assertEqual(
                    "two_storey_rc_frame_blast_reference",
                    descriptor.source_reference_lineage["resource_id"],
                )
                self.assertEqual("reference_only", descriptor.source_reference_lineage["relation"])
                self.assertTrue(
                    set(GENERIC_UNRESOLVED_MATERIAL_ROLES).issubset(
                        descriptor.unresolved_material_roles
                    )
                )
                self.assertEqual({"coarse", "standard", "fine"}, set(descriptor.mesh_profile_rows))
                self.assertEqual(0.100, descriptor.mesh_profile_rows["standard"]["member_foundation_target_m"])
                self.assertEqual(0.0500, descriptor.mesh_profile_rows["standard"]["slab_wall_target_m"])
                self.assertEqual(3, descriptor.mesh_profile_rows["standard"]["minimum_thickness_layers"])

    def test_descriptors_publish_complete_asset_specific_material_role_closure(self) -> None:
        # Mutation caught: hiding asset-specific compiler roles behind an ID special case.
        for descriptor in list_detailed_building_assets():
            with self.subTest(resource_id=descriptor.resource_id):
                expected_unresolved = GENERIC_UNRESOLVED_MATERIAL_ROLES
                if descriptor.resource_id == "subway_entrance_detailed_building":
                    expected_unresolved += SUBWAY_ONLY_MATERIAL_ROLES
                self.assertEqual(expected_unresolved, descriptor.unresolved_material_roles)
                self.assertEqual(
                    set(descriptor.material_candidates) | set(expected_unresolved),
                    set(descriptor.material_override_roles),
                )
                if descriptor.resource_id != "subway_entrance_detailed_building":
                    self.assertTrue(
                        set(SUBWAY_ONLY_MATERIAL_ROLES).isdisjoint(
                            descriptor.material_override_roles
                        )
                    )

    def test_raw_asset_manifests_are_self_describing_material_role_contracts(self) -> None:
        # Mutation caught: reconstructing asset-specific roles in Python instead of asset.json.
        for resource_id in EXPECTED_IDS:
            with self.subTest(resource_id=resource_id):
                path = (
                    MODEL_LIBRARY_DIR
                    / "detailed_buildings"
                    / "phase18d"
                    / resource_id
                    / "asset.json"
                )
                raw = json.loads(path.read_text(encoding="utf-8"))
                descriptor = get_detailed_building_asset(resource_id)
                raw_unresolved_roles = tuple(raw["unresolved_material_roles"])

                self.assertEqual(
                    raw_unresolved_roles,
                    descriptor.unresolved_material_roles,
                )
                self.assertEqual(
                    set(raw["material_candidates"]) | set(raw_unresolved_roles),
                    set(descriptor.material_override_roles),
                )

    def test_compiled_material_roles_are_within_each_descriptor_closure(self) -> None:
        # Mutation caught: emitting a semantic material role that discovery cannot enumerate.
        for resource_id, arguments in SMALL_COMPILE_ARGUMENTS.items():
            with self.subTest(resource_id=resource_id):
                descriptor = get_detailed_building_asset(resource_id)
                package = compile_detailed_building_asset(resource_id, **arguments)
                bindings = package.material_binding_manifest["bindings"]
                used_roles = {
                    row["semantic_role"]
                    for row in bindings
                }
                resolved_roles = {
                    row["semantic_role"]
                    for row in bindings
                    if row["resolution_status"] == "resolved"
                }
                unresolved_roles = {
                    row["semantic_role"]
                    for row in bindings
                    if row["resolution_status"] == "unresolved"
                }
                self.assertTrue(used_roles)
                self.assertEqual(used_roles, resolved_roles | unresolved_roles)
                self.assertTrue(
                    used_roles.issubset(
                        set(descriptor.material_candidates)
                        | set(descriptor.unresolved_material_roles)
                    )
                )

    def test_default_structural_systems_are_allowed_and_phase18c_registered(self) -> None:
        # Mutation caught: accepting an unsupported structural-system name in an asset manifest.
        registered = {row.system_id for row in list_structural_systems()}
        for descriptor in list_detailed_building_assets():
            with self.subTest(resource_id=descriptor.resource_id):
                self.assertIn(descriptor.default_structural_system, descriptor.allowed_structural_systems)
                self.assertTrue(set(descriptor.allowed_structural_systems).issubset(registered))

    def test_validator_rejects_invalid_parametric_contracts(self) -> None:
        # Mutation caught: weakening validation of a deployable asset row.
        source = load_detailed_building_asset_rows()[EXPECTED_IDS[0]]
        cases: tuple[tuple[str, object, str], ...] = (
            ("payload", {"path": "forbidden.k.gz"}, "must not declare a fixed payload"),
            ("requires_project_review", False, "requires_project_review"),
            ("solver_ready", True, "solver_ready"),
            ("unit_system", "tonne_mm_s_N_MPa", "unit_system"),
            ("allowed_fidelity_profiles", ["blast_response"], "fidelity"),
            ("default_fidelity_profile", "not_declared", "default fidelity"),
            ("allowed_mesh_profiles", ["standard"], "mesh"),
            ("default_mesh_profile", "not_declared", "default mesh"),
            ("allowed_structural_systems", ["unknown_system"], "structural system"),
        )
        for key, value, message in cases:
            with self.subTest(key=key):
                resource = copy.deepcopy(source)
                resource[key] = value
                with self.assertRaisesRegex(ValueError, message):
                    validate_detailed_building_asset_resource(resource)

    def test_validator_rejects_unknown_schema_versions(self) -> None:
        # Mutation caught: silently interpreting a newer or missing schema as 0.1.0.
        source = load_detailed_building_asset_rows()[EXPECTED_IDS[0]]
        for schema_version in (None, "", "0.2.0", "1.0.0"):
            with self.subTest(schema_version=schema_version):
                resource = copy.deepcopy(source)
                resource["schema_version"] = schema_version
                with self.assertRaisesRegex(ValueError, "schema_version"):
                    validate_detailed_building_asset_resource(resource)

    def test_validator_rejects_unknown_top_level_fields_and_typos(self) -> None:
        # Mutation caught: accepting misspelled or extension fields that no consumer reads.
        source = load_detailed_building_asset_rows()[EXPECTED_IDS[0]]
        cases = []

        extra = copy.deepcopy(source)
        extra["unrecognized_extension"] = True
        cases.append(extra)

        typo = copy.deepcopy(source)
        typo["default_mesh_profiel"] = typo.pop("default_mesh_profile")
        cases.append(typo)

        for resource in cases:
            with self.subTest(keys=tuple(sorted(resource))):
                with self.assertRaisesRegex(ValueError, "unknown top-level field"):
                    validate_detailed_building_asset_resource(resource)

    def test_validator_rejects_unknown_unresolved_material_roles(self) -> None:
        # Mutation caught: publishing a misspelled override role through a valid manifest.
        source = load_detailed_building_asset_rows()[
            "subway_entrance_detailed_building"
        ]
        source["unresolved_material_roles"].append("metal_roff")

        with self.assertRaisesRegex(ValueError, "unknown unresolved material role"):
            validate_detailed_building_asset_resource(source)

    def test_validator_rejects_geometry_closure_and_invalid_mesh_values(self) -> None:
        # Mutation caught: compiling an asset whose geometry or mesh controls are ambiguous or unsafe.
        source = load_detailed_building_asset_rows()[EXPECTED_IDS[0]]
        cases: list[tuple[dict[str, object], str]] = []

        duplicate_field = copy.deepcopy(source)
        duplicate_field["geometry_fields"] = [*duplicate_field["geometry_fields"], duplicate_field["geometry_fields"][0]]
        cases.append((duplicate_field, "duplicate geometry field"))

        missing_default = copy.deepcopy(source)
        missing_default["default_geometry"].pop(missing_default["geometry_fields"][0])
        cases.append((missing_default, "geometry fields"))

        extra_default = copy.deepcopy(source)
        extra_default["default_geometry"]["not_a_geometry_field"] = 1.0
        cases.append((extra_default, "geometry fields"))

        for mesh_value in (0.0, -0.1, math.inf, math.nan):
            invalid_mesh = copy.deepcopy(source)
            invalid_mesh["mesh_profiles"]["standard"]["member_foundation_target_m"] = mesh_value
            cases.append((invalid_mesh, "finite positive"))

        for resource, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    validate_detailed_building_asset_resource(resource)

    def test_loader_rejects_duplicate_resource_ids(self) -> None:
        # Mutation caught: silently overwriting the first asset when two packages claim an ID.
        source = load_detailed_building_asset_rows()[EXPECTED_IDS[0]]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("first", "second"):
                target = root / name
                target.mkdir()
                (target / "asset.json").write_text(
                    json.dumps(source, sort_keys=True), encoding="utf-8"
                )
            with self.assertRaisesRegex(ValueError, "duplicate detailed building asset id"):
                load_detailed_building_asset_rows(root)


if __name__ == "__main__":
    unittest.main()
