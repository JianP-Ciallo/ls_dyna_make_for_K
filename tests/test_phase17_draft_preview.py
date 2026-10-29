from __future__ import annotations

import shutil
import unittest
from unittest import mock

from lsprepost_mcp.city_street_blast import default_city_street_blast_spec
from lsprepost_mcp.city_ground_crater import default_ground_response
from lsprepost_mcp.city_editor import apply_city_component_operation
from lsprepost_mcp.paths import project_dir
from lsprepost_mcp.io import read_json
from lsprepost_mcp.web.draft_preview import (
    build_editor_draft_preview,
    generate_editor_project,
    mutate_city_editor_component,
)

from tests.test_web_api import request_json, web_test_server


class Phase17DraftPreviewTests(unittest.TestCase):
    def city_payload(
        self,
        *,
        project_name: str = "unit_phase17_city_preview",
        revision: int = 1,
    ) -> dict[str, object]:
        return {
            "source_kind": "city_street_blast",
            "revision": revision,
            "project_name": project_name,
            "spec": default_city_street_blast_spec(project_name),
            "blast_source": {
                "source_id": "city_tnt",
                "position_m": [5.0, -4.0, 0.9],
            },
            "transforms": {},
        }

    def test_city_preview_exposes_real_source_and_grounded_building(self) -> None:
        preview = build_editor_draft_preview(self.city_payload(revision=8))

        self.assertEqual("lsprepost_mcp_preview_mesh_v2", preview["format"])
        self.assertEqual(8, preview["revision"])
        source = next(
            item
            for item in preview["editable_sources"]
            if item["source_id"] == "city_tnt"
        )
        building = next(
            item
            for item in preview["components"]
            if item["component_id"] == "commercial_supermarket"
        )
        self.assertEqual("blast_source", source["mobility_profile"])
        self.assertEqual(["tx", "ty", "tz"], source["allowed_dofs"])
        self.assertEqual([5.0, -4.0, 0.9], source["position_m"])
        self.assertEqual("grounded", building["mobility_profile"])
        self.assertEqual(["tx", "ty", "rz"], building["allowed_dofs"])
        self.assertTrue(building["supports_ale_fsi"])
        self.assertTrue(preview["validation"]["ok"])
        self.assertEqual("draft_compiled_in_memory", preview["validation"]["status"])
        self.assertEqual(
            "pending_project_generation",
            preview["validation"]["full_static_checks"],
        )
        self.assertEqual([5.0, -4.0, 0.9], preview["ale_mesh"]["refinement_center_m"])
        self.assertEqual(64, len(preview["ale_mesh"]["mesh_fingerprint"]))

    def test_city_preview_exposes_validation_crater_ground_parts(self) -> None:
        payload = self.city_payload(revision=9)
        payload["blast_source"]["position_m"] = [0.0, 0.0, 0.9]
        payload["spec"]["ground_response"] = default_ground_response()

        preview = build_editor_draft_preview(payload)

        self.assertEqual(
            "validation_crater",
            preview["resolved_spec"]["ground_response"]["mode"],
        )
        parts = {int(item["part_id"]): item for item in preview["parts"]}
        self.assertEqual(
            "eroding_crater_zone",
            parts[90]["ground_response_role"],
        )
        self.assertEqual("lower_support", parts[92]["ground_response_role"])

    def test_city_preview_exposes_independent_subway_and_vehicles(self) -> None:
        preview = build_editor_draft_preview(self.city_payload(revision=8))
        components = {
            item["component_id"]: item
            for item in preview["components"]
        }

        subway = components["subway_entrance"]
        self.assertEqual("grounded", subway["mobility_profile"])
        self.assertEqual(["tx", "ty", "rz"], subway["allowed_dofs"])
        self.assertEqual("base_fixed", subway["constraint_mode"])

        for index in range(1, 5):
            vehicle = components[f"parked_vehicle_{index}"]
            self.assertEqual("surface_dynamic", vehicle["mobility_profile"])
            self.assertEqual(["tx", "ty", "rz"], vehicle["allowed_dofs"])
            self.assertEqual("free", vehicle["constraint_mode"])
            self.assertEqual("parking_lot", vehicle["support_object_id"])

    def test_subway_and_vehicle_moves_are_independent(self) -> None:
        baseline = build_editor_draft_preview(self.city_payload())
        baseline_components = {
            item["component_id"]: item
            for item in baseline["components"]
        }
        payload = self.city_payload(revision=2)
        payload["transforms"] = {
            "subway_entrance": {
                "translate_m": [-1.0, 2.0, 0.0],
                "rotate_deg": [0.0, 0.0, 15.0],
            },
            "parked_vehicle_1": {
                "translate_m": [-1.0, 0.0, 0.0],
                "rotate_deg": [0.0, 0.0, 5.0],
            },
        }

        moved = build_editor_draft_preview(payload)
        moved_components = {
            item["component_id"]: item
            for item in moved["components"]
        }

        for object_id, delta in (
            ("subway_entrance", [-1.0, 2.0]),
            ("parked_vehicle_1", [-1.0, 0.0]),
        ):
            before = baseline_components[object_id]
            after = moved_components[object_id]
            self.assertAlmostEqual(
                before["pivot_world_m"][0] + delta[0],
                after["pivot_world_m"][0],
                places=9,
            )
            self.assertAlmostEqual(
                before["pivot_world_m"][1] + delta[1],
                after["pivot_world_m"][1],
                places=9,
            )

        self.assertEqual(
            baseline_components["parked_vehicle_2"]["pivot_world_m"],
            moved_components["parked_vehicle_2"]["pivot_world_m"],
        )
        self.assertEqual(15.0, moved_components["subway_entrance"]["rotate_deg"][2])
        self.assertEqual(5.0, moved_components["parked_vehicle_1"]["rotate_deg"][2])
        self.assertEqual("free", moved_components["parked_vehicle_1"]["constraint_mode"])
        self.assertNotEqual(
            baseline["resolved_spec"]["layout"],
            moved["resolved_spec"]["layout"],
        )

    def test_subway_and_vehicle_reject_lift_and_tilt(self) -> None:
        for object_id in ("subway_entrance", "parked_vehicle_1"):
            with self.subTest(object_id=object_id):
                payload = self.city_payload()
                payload["transforms"] = {
                    object_id: {
                        "translate_m": [0.0, 0.0, 0.1],
                        "rotate_deg": [1.0, 0.0, 0.0],
                    }
                }
                with self.assertRaisesRegex(ValueError, "surface-constrained"):
                    build_editor_draft_preview(payload)

    def test_vehicle_cannot_leave_parking_support(self) -> None:
        payload = self.city_payload()
        payload["transforms"] = {
            "parked_vehicle_1": {
                "translate_m": [-20.0, 0.0, 0.0],
                "rotate_deg": [0.0, 0.0, 0.0],
            }
        }

        with self.assertRaisesRegex(ValueError, "city_object_lost_support"):
            build_editor_draft_preview(payload)

    def test_added_vehicle_is_compiled_as_free_supported_object(self) -> None:
        payload = self.city_payload(revision=3)
        payload["spec"]["layout"]["parked_vehicles"]["instances"].append(
            {
                "origin_m": [27.0, -30.0, 0.10],
                "rotate_z_deg": 0.0,
                "editor_added": True,
                "editor_modified": True,
            }
        )

        preview = build_editor_draft_preview(payload)
        vehicle = next(
            item
            for item in preview["components"]
            if item["component_id"] == "parked_vehicle_5"
        )
        self.assertEqual("free", vehicle["constraint_mode"])
        self.assertEqual("surface_dynamic", vehicle["mobility_profile"])
        self.assertEqual("parking_lot", vehicle["support_object_id"])
        self.assertTrue(vehicle["editable"])

    def test_vehicle_instance_ids_remain_stable_after_delete_and_add(self) -> None:
        spec = default_city_street_blast_spec("unit_phase17_stable_ids")
        deleted = apply_city_component_operation(
            spec,
            {"action": "delete", "component_id": "parked_vehicle_2"},
        )
        added = apply_city_component_operation(
            deleted["spec"],
            {"action": "add", "template": "parked_vehicle"},
        )

        instance_ids = [
            item["instance_id"]
            for item in added["spec"]["layout"]["parked_vehicles"]["instances"]
        ]
        self.assertEqual(
            [
                "parked_vehicle_1",
                "parked_vehicle_3",
                "parked_vehicle_4",
                "parked_vehicle_5",
            ],
            instance_ids,
        )
        self.assertEqual("parked_vehicle_5", added["selected_component_id"])

        payload = self.city_payload(revision=4)
        payload["spec"] = added["spec"]
        preview = build_editor_draft_preview(payload)
        preview_ids = {
            item["component_id"]
            for item in preview["components"]
        }
        self.assertNotIn("parked_vehicle_2", preview_ids)
        self.assertIn("parked_vehicle_5", preview_ids)

    def test_duplicate_vehicle_gets_new_id_and_safe_placement(self) -> None:
        spec = default_city_street_blast_spec("unit_phase17_duplicate_vehicle")
        duplicated = apply_city_component_operation(
            spec,
            {"action": "duplicate", "component_id": "parked_vehicle_1"},
        )
        instances = duplicated["spec"]["layout"]["parked_vehicles"]["instances"]

        self.assertEqual("parked_vehicle_5", duplicated["selected_component_id"])
        self.assertEqual(5, len(instances))
        self.assertEqual(
            [27.0, -30.0, 0.10],
            instances[-1]["origin_m"],
        )
        self.assertEqual(
            instances[0]["rotate_z_deg"],
            instances[-1]["rotate_z_deg"],
        )
        self.assertTrue(instances[-1]["editor_added"])
        self.assertTrue(instances[-1]["editor_modified"])

    def test_component_operation_rejects_fixed_unknown_and_last_vehicle_delete(self) -> None:
        spec = default_city_street_blast_spec("unit_phase17_operation_reject")
        with self.assertRaisesRegex(ValueError, "not removable"):
            apply_city_component_operation(
                spec,
                {"action": "delete", "component_id": "commercial_supermarket"},
            )
        with self.assertRaisesRegex(ValueError, "unsupported component template"):
            apply_city_component_operation(
                spec,
                {"action": "add", "template": "shell_plate"},
            )

        spec["layout"]["parked_vehicles"]["instances"] = [
            spec["layout"]["parked_vehicles"]["instances"][0]
        ]
        with self.assertRaisesRegex(ValueError, "at least one parked vehicle"):
            apply_city_component_operation(
                spec,
                {"action": "delete", "component_id": "parked_vehicle_1"},
            )

    def test_subway_instances_keep_legacy_id_and_support_controlled_operations(self) -> None:
        spec = default_city_street_blast_spec("unit_phase17_subway_instances")
        subway = spec["layout"]["subway_entrance"]
        self.assertEqual("subway_entrance", subway["instances"][0]["instance_id"])

        added = apply_city_component_operation(
            spec,
            {"action": "add", "template": "subway_entrance"},
        )
        instances = added["spec"]["layout"]["subway_entrance"]["instances"]
        self.assertEqual("subway_entrance_2", added["selected_component_id"])
        self.assertEqual(2, len(instances))
        self.assertEqual([20.0, 12.0, 0.0], instances[-1]["origin_m"])
        self.assertTrue(instances[-1]["editor_added"])
        self.assertTrue(instances[-1]["editor_modified"])

        duplicated = apply_city_component_operation(
            added["spec"],
            {"action": "duplicate", "component_id": "subway_entrance_2"},
        )
        self.assertEqual(
            "subway_entrance_3",
            duplicated["selected_component_id"],
        )
        self.assertEqual(
            [28.0, 12.0, 0.0],
            duplicated["spec"]["layout"]["subway_entrance"]["instances"][-1][
                "origin_m"
            ],
        )

        deleted = apply_city_component_operation(
            duplicated["spec"],
            {"action": "delete", "component_id": "subway_entrance_2"},
        )
        remaining_ids = [
            item["instance_id"]
            for item in deleted["spec"]["layout"]["subway_entrance"]["instances"]
        ]
        self.assertEqual(
            ["subway_entrance", "subway_entrance_3"],
            remaining_ids,
        )
        self.assertEqual("subway_entrance", deleted["selected_component_id"])

    def test_subway_component_operation_keeps_at_least_one_instance(self) -> None:
        spec = default_city_street_blast_spec("unit_phase17_subway_minimum")
        with self.assertRaisesRegex(ValueError, "at least one subway entrance"):
            apply_city_component_operation(
                spec,
                {"action": "delete", "component_id": "subway_entrance"},
            )

    def test_existing_library_components_can_be_added_duplicated_and_removed(self) -> None:
        spec = default_city_street_blast_spec("unit_phase17_library_components")
        for template, expected_id, expected_origin in (
            ("shell_box", "shell_box_1", [24.0, 30.0, 0.0]),
        ):
            with self.subTest(template=template):
                added = apply_city_component_operation(
                    spec,
                    {"action": "add", "template": template},
                )
                self.assertEqual(expected_id, added["selected_component_id"])
                container = added["spec"]["layout"]["library_components"][template]
                self.assertEqual(expected_origin, container["instances"][0]["origin_m"])

                duplicated = apply_city_component_operation(
                    added["spec"],
                    {"action": "duplicate", "component_id": expected_id},
                )
                self.assertEqual(
                    f"{template}_2",
                    duplicated["selected_component_id"],
                )
                removed = apply_city_component_operation(
                    duplicated["spec"],
                    {"action": "delete", "component_id": expected_id},
                )
                remaining = removed["spec"]["layout"]["library_components"][template][
                    "instances"
                ]
                self.assertEqual([f"{template}_2"], [item["instance_id"] for item in remaining])

                removed_last = apply_city_component_operation(
                    removed["spec"],
                    {"action": "delete", "component_id": f"{template}_2"},
                )
                self.assertIsNone(removed_last["selected_component_id"])
                self.assertEqual(
                    [],
                    removed_last["spec"]["layout"]["library_components"][template][
                        "instances"
                    ],
                )

    def test_shell_box_addition_migrates_legacy_city_layout(self) -> None:
        spec = default_city_street_blast_spec("unit_phase17_legacy_library")
        spec["layout"].pop("library_components")

        added = apply_city_component_operation(
            spec,
            {"action": "add", "template": "shell_box"},
        )

        self.assertEqual("shell_box_1", added["selected_component_id"])
        self.assertEqual(
            [24.0, 30.0, 0.0],
            added["spec"]["layout"]["library_components"]["shell_box"][
                "instances"
            ][0]["origin_m"],
        )

    def test_solid_component_is_rejected_until_fsi_surfaces_are_supported(self) -> None:
        spec = default_city_street_blast_spec("unit_phase17_solid_gate")
        with self.assertRaisesRegex(
            ValueError,
            "unsupported component template",
        ):
            apply_city_component_operation(
                spec,
                {"action": "add", "template": "solid_block"},
            )

    def test_removing_last_shell_box_records_nullable_selection(self) -> None:
        payload = self.city_payload(revision=9)
        payload["operation"] = {"action": "add", "template": "shell_box"}
        added = mutate_city_editor_component(payload)
        delete_payload = added["draft"]
        delete_payload["revision"] = 10
        delete_payload["operation"] = {
            "action": "delete",
            "component_id": "shell_box_1",
        }

        removed = mutate_city_editor_component(delete_payload)

        self.assertIsNone(removed["selected_component_id"])
        self.assertEqual(
            {
                "revision": 10,
                "action": "delete",
                "template": "shell_box",
                "selected_component_id": None,
                "removed_component_id": "shell_box_1",
            },
            removed["draft"]["component_operations"][-1],
        )
        self.assertEqual(
            [],
            removed["draft"]["spec"]["layout"]["library_components"][
                "shell_box"
            ]["instances"],
        )

    def test_duplicate_instance_ids_and_dangling_transforms_are_rejected(self) -> None:
        duplicate_payload = self.city_payload()
        duplicate_instances = duplicate_payload["spec"]["layout"]["parked_vehicles"][
            "instances"
        ]
        duplicate_instances[1]["instance_id"] = "parked_vehicle_1"
        with self.assertRaisesRegex(ValueError, "duplicate parked vehicle"):
            build_editor_draft_preview(duplicate_payload)

        deleted = apply_city_component_operation(
            self.city_payload()["spec"],
            {"action": "delete", "component_id": "parked_vehicle_2"},
        )
        dangling_payload = self.city_payload()
        dangling_payload["spec"] = deleted["spec"]
        dangling_payload["transforms"] = {
            "parked_vehicle_2": {
                "translate_m": [0.1, 0.0, 0.0],
                "rotate_deg": [0.0, 0.0, 0.0],
            }
        }
        with self.assertRaisesRegex(ValueError, "layout entry"):
            build_editor_draft_preview(dangling_payload)

    def test_mutation_endpoint_canonicalizes_transforms_and_returns_preview(self) -> None:
        payload = self.city_payload(revision=5)
        payload["transforms"] = {
            "parked_vehicle_1": {
                "translate_m": [-1.0, 0.0, 0.0],
                "rotate_deg": [0.0, 0.0, 10.0],
            }
        }
        payload["operation"] = {
            "action": "duplicate",
            "component_id": "parked_vehicle_1",
        }

        result = mutate_city_editor_component(payload)

        self.assertEqual({}, result["draft"]["transforms"])
        self.assertEqual(
            {
                "revision": 5,
                "action": "duplicate",
                "template": "parked_vehicle",
                "selected_component_id": "parked_vehicle_5",
                "removed_component_id": None,
            },
            result["draft"]["component_operations"][-1],
        )
        self.assertEqual(5, result["preview"]["revision"])
        self.assertEqual("parked_vehicle_5", result["selected_component_id"])
        source = next(
            item
            for item in result["preview"]["components"]
            if item["component_id"] == "parked_vehicle_1"
        )
        self.assertAlmostEqual(17.2, source["pivot_world_m"][0], places=9)
        self.assertEqual(10.0, source["rotate_deg"][2])

    def test_component_mutation_route_returns_controlled_draft(self) -> None:
        payload = self.city_payload(revision=6)
        payload["operation"] = {
            "action": "add",
            "template": "parked_vehicle",
        }

        with web_test_server() as address:
            status, response = request_json(
                address,
                "POST",
                "/api/editor/city-component",
                payload,
            )

        self.assertEqual(200, status)
        result = response["result"]
        self.assertEqual("parked_vehicle_5", result["selected_component_id"])
        self.assertEqual(6, result["preview"]["revision"])
        self.assertEqual({}, result["draft"]["transforms"])

    def test_subway_mutation_endpoint_records_strict_operation_history(self) -> None:
        payload = self.city_payload(revision=7)
        payload["operation"] = {
            "action": "add",
            "template": "subway_entrance",
        }

        result = mutate_city_editor_component(payload)

        self.assertEqual("subway_entrance_2", result["selected_component_id"])
        self.assertEqual(
            {
                "revision": 7,
                "action": "add",
                "template": "subway_entrance",
                "selected_component_id": "subway_entrance_2",
                "removed_component_id": None,
            },
            result["draft"]["component_operations"][-1],
        )
        components = {
            item["component_id"]: item
            for item in result["preview"]["components"]
        }
        self.assertEqual(
            "base_fixed",
            components["subway_entrance_2"]["constraint_mode"],
        )
        self.assertTrue(
            components["subway_entrance_2"]["supports_ale_fsi"],
        )
        self.assertEqual(
            ["add", "duplicate", "delete"],
            components["subway_entrance_2"]["instance_operations"],
        )

    def test_source_move_changes_exposed_ale_mesh_fingerprint(self) -> None:
        first = build_editor_draft_preview(self.city_payload(revision=1))
        moved_payload = self.city_payload(revision=2)
        moved_payload["blast_source"] = {
            "source_id": "city_tnt",
            "position_m": [6.0, -4.0, 0.9],
        }
        moved = build_editor_draft_preview(moved_payload)

        self.assertNotEqual(
            first["ale_mesh"]["mesh_fingerprint"],
            moved["ale_mesh"]["mesh_fingerprint"],
        )
        self.assertEqual([6.0, -4.0, 0.9], moved["ale_mesh"]["refinement_center_m"])

    def test_lsprepost_validation_route_uses_controlled_tool(self) -> None:
        expected = {"ok": True, "project_name": "phase17_checked"}
        with (
            mock.patch(
                "lsprepost_mcp.web.app.web_config_status",
                return_value={"configured": True, "doctor": {"ok": True}},
            ),
            mock.patch(
                "lsprepost_mcp.web.app.tool_validate_lsprepost_import",
                return_value=expected,
            ) as validate,
        ):
            with web_test_server() as address:
                status, payload = request_json(
                    address,
                    "POST",
                    "/api/editor/validate-lsprepost",
                    {"project_name": "phase17_checked", "timeout_s": 90},
                )

        self.assertEqual(200, status)
        self.assertEqual(expected, payload["result"])
        validate.assert_called_once_with(
            {"project_name": "phase17_checked", "timeout_s": 90}
        )

    def test_lsprepost_validation_route_fails_fast_when_not_configured(self) -> None:
        with (
            mock.patch(
                "lsprepost_mcp.web.app.web_config_status",
                return_value={
                    "configured": False,
                    "lspp_exe": "lsprepost4.12.exe",
                    "doctor": {"ok": False},
                },
            ),
            mock.patch(
                "lsprepost_mcp.web.app.tool_validate_lsprepost_import",
            ) as validate,
        ):
            with web_test_server() as address:
                status, payload = request_json(
                    address,
                    "POST",
                    "/api/editor/validate-lsprepost",
                    {"project_name": "phase17_checked", "timeout_s": 90},
                )

        self.assertEqual(409, status)
        self.assertEqual("lsprepost_not_configured", payload["error"]["code"])
        validate.assert_not_called()

    def test_preview_route_preserves_revision_and_never_writes_project(self) -> None:
        project_name = "unit_phase17_route_no_write"
        path = project_dir(project_name)
        if path.exists():
            shutil.rmtree(path)
        try:
            with web_test_server() as address:
                status, payload = request_json(
                    address,
                    "POST",
                    "/api/editor/preview",
                    self.city_payload(project_name=project_name, revision=9),
                )

            self.assertEqual(200, status)
            self.assertEqual(9, payload["result"]["revision"])
            self.assertFalse(path.exists())
        finally:
            if path.exists():
                shutil.rmtree(path)

    def test_boolean_revision_is_rejected(self) -> None:
        payload = self.city_payload()
        payload["revision"] = True
        with self.assertRaisesRegex(ValueError, "revision"):
            build_editor_draft_preview(payload)

    def test_component_operation_history_is_strictly_validated(self) -> None:
        payload = self.city_payload()
        payload["component_operations"] = [
            {
                "revision": 1,
                "action": "arbitrary_keyword",
                "template": "shell_plate",
                "selected_component_id": "anything",
                "removed_component_id": None,
            }
        ]
        with self.assertRaisesRegex(ValueError, "action is invalid"):
            build_editor_draft_preview(payload)

    def test_grounded_building_rejects_lift_and_tilt(self) -> None:
        payload = self.city_payload()
        payload["transforms"] = {
            "commercial_supermarket": {
                "translate_m": [0.0, 0.0, 0.2],
                "rotate_deg": [5.0, 0.0, 0.0],
            }
        }
        with self.assertRaisesRegex(ValueError, "grounded"):
            build_editor_draft_preview(payload)

    def test_grounded_building_rotation_uses_preview_center_as_pivot(self) -> None:
        baseline = build_editor_draft_preview(self.city_payload())
        baseline_building = next(
            item
            for item in baseline["components"]
            if item["component_id"] == "commercial_supermarket"
        )
        payload = self.city_payload(revision=2)
        payload["transforms"] = {
            "commercial_supermarket": {
                "translate_m": [1.0, 2.0, 0.0],
                "rotate_deg": [0.0, 0.0, 90.0],
            }
        }

        moved = build_editor_draft_preview(payload)
        moved_building = next(
            item
            for item in moved["components"]
            if item["component_id"] == "commercial_supermarket"
        )

        self.assertAlmostEqual(
            baseline_building["pivot_world_m"][0] + 1.0,
            moved_building["pivot_world_m"][0],
            places=9,
        )
        self.assertAlmostEqual(
            baseline_building["pivot_world_m"][1] + 2.0,
            moved_building["pivot_world_m"][1],
            places=9,
        )
        self.assertEqual(90.0, moved_building["rotate_deg"][2])

    def test_blast_source_cannot_intersect_building(self) -> None:
        payload = self.city_payload()
        payload["blast_source"] = {
            "source_id": "city_tnt",
            "position_m": [-28.0, 18.0, 1.0],
        }
        with self.assertRaisesRegex(
            ValueError,
            "blast_source_intersects_structure",
        ):
            build_editor_draft_preview(payload)

    def test_grounded_building_cannot_leave_ale_domain(self) -> None:
        payload = self.city_payload()
        payload["transforms"] = {
            "commercial_supermarket": {
                "translate_m": [-20.0, 0.0, 0.0],
                "rotate_deg": [0.0, 0.0, 0.0],
            }
        }
        with self.assertRaisesRegex(ValueError, "city_object_outside_ale_domain"):
            build_editor_draft_preview(payload)

    def test_grounded_building_cannot_move_off_designated_foundation(self) -> None:
        payload = self.city_payload()
        payload["transforms"] = {
            "commercial_supermarket": {
                "translate_m": [0.0, -20.0, 0.0],
                "rotate_deg": [0.0, 0.0, 0.0],
            }
        }

        with self.assertRaisesRegex(ValueError, "city_object_lost_support"):
            build_editor_draft_preview(payload)

    def test_generation_is_immutable_and_records_provenance(self) -> None:
        project_name = "unit_phase17_generated_city"
        path = project_dir(project_name)
        if path.exists():
            shutil.rmtree(path)
        try:
            payload = self.city_payload(project_name=project_name, revision=14)
            payload["source_project_name"] = "city_baseline"
            payload["source_model_sha256"] = "a" * 64
            result = generate_editor_project(payload)

            self.assertTrue(result["checks"]["ok"])
            model = read_json(path / "model.json")
            provenance = model["metadata"]["editor_provenance"]
            self.assertEqual(17, provenance["editor_phase"])
            self.assertEqual(14, provenance["draft_revision"])
            self.assertEqual("city_baseline", provenance["source_project_name"])
            self.assertEqual("a" * 64, provenance["source_model_sha256"])
            self.assertEqual(
                model["metadata"]["layout_fingerprint"],
                provenance["layout_fingerprint"],
            )
            self.assertEqual(
                model["metadata"]["ale_domain"]["mesh_fingerprint"],
                provenance["ale_mesh_fingerprint"],
            )
            self.assertEqual(payload["transforms"], provenance["transforms"])
            self.assertEqual(payload["blast_source"], provenance["blast_source"])
            self.assertEqual([], provenance["component_operations"])
            with self.assertRaises(FileExistsError):
                generate_editor_project(payload)
        finally:
            if path.exists():
                shutil.rmtree(path)


if __name__ == "__main__":
    unittest.main()
