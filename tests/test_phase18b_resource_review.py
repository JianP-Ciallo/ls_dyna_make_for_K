from __future__ import annotations

import copy
import unittest

from lsprepost_mcp.materials import (
    get_material,
    get_reviewed_material_resource,
    validate_material_resource,
)
from lsprepost_mcp.phase18_resource_review import (
    SOURCE_2K_SHA256,
    apply_effective_review,
    canonical_resource_sha256,
    validate_phase18_review_manifest,
)


def review_manifest_for(
    resource: dict[str, object],
    canonical_sha256: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "source_sha256": SOURCE_2K_SHA256,
        "resources": [
            {
                "id": resource["id"],
                "resource_kind": "material",
                "canonical_sha256": canonical_sha256 or canonical_resource_sha256(resource),
                "validation_status": "syntax_unit_reviewed",
                "reviewed_on": "2026-08-05",
                "review_method": "automated_syntax_unit_dependency_audit",
                "evidence": [
                    "source_identity",
                    "source_spans",
                    "si_conversion",
                    "typed_fields",
                    "dependency_closure",
                ],
            }
        ],
    }


class Phase18ReviewContractTests(unittest.TestCase):
    def test_canonical_hash_excludes_only_review_and_runtime_fields(self) -> None:
        base = {
            "id": "2k_mid12_rebar_d12",
            "density_kg_per_m3": 7850.0,
            "validation_status": "source_reference",
            "requires_project_review": True,
            "_path": "local-only.json",
        }
        changed_metadata = {
            **base,
            "validation_status": "syntax_unit_reviewed",
            "effective_validation_status": "syntax_unit_reviewed",
            "review": {"reviewed_on": "2026-08-05"},
            "_path": "other.json",
        }
        changed_value = {**base, "density_kg_per_m3": 7800.0}

        self.assertEqual(canonical_resource_sha256(base), canonical_resource_sha256(changed_metadata))
        self.assertNotEqual(canonical_resource_sha256(base), canonical_resource_sha256(changed_value))

    def test_hash_mismatch_cannot_promote_source_reference(self) -> None:
        resource = {
            "id": "2k_mid12_rebar_d12",
            "validation_status": "source_reference",
            "requires_project_review": True,
        }
        manifest = review_manifest_for(resource, canonical_sha256="0" * 64)

        with self.assertRaisesRegex(ValueError, "canonical SHA-256"):
            apply_effective_review(resource, manifest)

    def test_missing_review_record_keeps_source_reference_effective_status(self) -> None:
        resource = {
            "id": "2k_mid12_rebar_d12",
            "validation_status": "source_reference",
            "requires_project_review": True,
        }
        manifest = {"schema_version": "0.1.0", "source_sha256": SOURCE_2K_SHA256, "resources": []}

        reviewed = apply_effective_review(resource, manifest)

        self.assertEqual("source_reference", reviewed["effective_validation_status"])
        self.assertNotIn("review", reviewed)

    def test_manifest_rejects_duplicate_resource_records(self) -> None:
        resource = {
            "id": "2k_mid12_rebar_d12",
            "validation_status": "source_reference",
            "requires_project_review": True,
        }
        manifest = review_manifest_for(resource)
        manifest["resources"] = [*manifest["resources"], dict(manifest["resources"][0])]

        with self.assertRaisesRegex(ValueError, "duplicate review resource id"):
            validate_phase18_review_manifest(manifest, {resource["id"]: resource})

    def test_manifest_rejects_whitespace_only_review_evidence(self) -> None:
        resource = {
            "id": "2k_mid12_rebar_d12",
            "validation_status": "source_reference",
            "requires_project_review": True,
        }
        manifest = review_manifest_for(resource)
        manifest["resources"][0]["evidence"] = ["   "]

        with self.assertRaisesRegex(ValueError, "evidence"):
            validate_phase18_review_manifest(manifest, {resource["id"]: resource})

    def test_manifest_rejects_resource_mapping_key_and_object_id_mismatch(self) -> None:
        resource = {
            "id": "material.other",
            "validation_status": "source_reference",
            "requires_project_review": True,
        }
        manifest = review_manifest_for(resource)
        manifest["resources"][0]["id"] = "material.demo"

        with self.assertRaisesRegex(ValueError, "key/object identity mismatch"):
            validate_phase18_review_manifest(manifest, {"material.demo": resource})

    def test_effective_review_rejects_invalid_manifest_header(self) -> None:
        resource = {
            "id": "2k_mid12_rebar_d12",
            "validation_status": "source_reference",
            "requires_project_review": True,
        }
        invalid_headers = (
            ("schema_version", "9.9.9", "schema_version"),
            ("source_sha256", "0" * 64, "source SHA-256"),
        )

        for field, invalid_value, expected_message in invalid_headers:
            with self.subTest(field=field):
                manifest = review_manifest_for(resource)
                manifest[field] = invalid_value
                with self.assertRaisesRegex(ValueError, expected_message):
                    apply_effective_review(resource, manifest, expected_resource_kind="material")

    def test_effective_review_rejects_incomplete_or_wrong_record(self) -> None:
        resource = {
            "id": "2k_mid12_rebar_d12",
            "validation_status": "source_reference",
            "requires_project_review": True,
        }
        invalid_records = (
            ("reviewed_on", None, "reviewed_on"),
            ("review_method", "manual", "review_method"),
            ("evidence", [], "evidence"),
            ("resource_kind", "structural", "resource_kind"),
        )

        for field, invalid_value, expected_message in invalid_records:
            with self.subTest(field=field):
                manifest = review_manifest_for(resource)
                record = manifest["resources"][0]
                if invalid_value is None:
                    del record[field]
                else:
                    record[field] = invalid_value
                with self.assertRaisesRegex(ValueError, expected_message):
                    apply_effective_review(resource, manifest, expected_resource_kind="material")


class Phase18MaterialAuditTests(unittest.TestCase):
    MATERIAL_IDS = (
        "two_storey_rc_frame_mid2_air_eos2",
        "two_storey_rc_frame_mid3_tnt_eos1",
        "two_storey_rc_frame_mid5_concrete_kc",
        "two_storey_rc_frame_mid8_rebar_d8_d18",
        "two_storey_rc_frame_mid12_rebar_d12",
        "two_storey_rc_frame_mid14_rebar_d20",
    )

    def test_six_material_bundles_pass_typed_validation(self) -> None:
        for material_id in self.MATERIAL_IDS:
            with self.subTest(material_id=material_id):
                report = validate_material_resource(get_material(material_id))
                self.assertTrue(report["valid"])
                self.assertEqual(material_id, report["resource_id"])
                self.assertEqual(SOURCE_2K_SHA256, report["source_sha256"])

    def test_concrete_requires_rate_curve_dependency(self) -> None:
        concrete = get_material("2k_mid5_concrete_kc")
        broken = copy.deepcopy(concrete)
        del broken["dependencies"]["rate_curve"]

        with self.assertRaisesRegex(ValueError, "rate_curve"):
            validate_material_resource(broken)

    def test_reviewed_accessor_rejects_unreviewed_resource(self) -> None:
        with self.assertRaisesRegex(ValueError, "syntax_unit_reviewed"):
            get_reviewed_material_resource(
                "2k_mid5_concrete_kc",
                {"concrete_damage_rel3"},
                review_manifest={
                    "schema_version": "0.1.0",
                    "source_sha256": SOURCE_2K_SHA256,
                    "resources": [],
                },
            )

    def test_reviewed_accessor_rejects_wrong_material_role(self) -> None:
        air = get_material("2k_mid2_air_eos2")

        with self.assertRaisesRegex(ValueError, "allowed material type"):
            get_reviewed_material_resource(
                "2k_mid2_air_eos2",
                {"concrete_damage_rel3"},
                review_manifest=review_manifest_for(air),
            )


if __name__ == "__main__":
    unittest.main()
