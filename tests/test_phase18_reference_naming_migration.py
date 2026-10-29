from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from lsprepost_mcp.materials import get_material, list_materials
from lsprepost_mcp.component_model_resources import COMPONENT_RESOURCE_SPECS
from lsprepost_mcp.keyword_decomposition import _2k_material_assets
from lsprepost_mcp.model_library import (
    export_model_resource,
    get_model_resource,
    list_model_resources,
    load_model_resources,
)
from lsprepost_mcp.structural_resources import (
    get_structural_resource,
    list_structural_resources,
)


MODEL_ALIASES = {
    "2k_complete_reference": "two_storey_rc_frame_blast_reference",
    "2k_rc_beam_reference": "two_storey_rc_frame_beam_reference",
    "2k_rc_column_reference": "two_storey_rc_frame_column_reference",
    "2k_rc_slab_reference": "two_storey_rc_frame_slab_reference",
    "2k_rc_base_reference": "two_storey_rc_frame_foundation_reference",
}

MATERIAL_ALIASES = {
    "2k_mid2_air_eos2": "two_storey_rc_frame_mid2_air_eos2",
    "2k_mid3_tnt_eos1": "two_storey_rc_frame_mid3_tnt_eos1",
    "2k_mid5_concrete_kc": "two_storey_rc_frame_mid5_concrete_kc",
    "2k_mid8_rebar_d8_d18": "two_storey_rc_frame_mid8_rebar_d8_d18",
    "2k_mid12_rebar_d12": "two_storey_rc_frame_mid12_rebar_d12",
    "2k_mid14_rebar_d20": "two_storey_rc_frame_mid14_rebar_d20",
}

STRUCTURAL_ALIASES = {
    "2k_sections_used": "two_storey_rc_frame_sections",
    "2k_curve1_kc_rate": "two_storey_rc_frame_kc_rate_curve",
    "2k_part_role_map": "two_storey_rc_frame_part_roles",
    "2k_sets_used": "two_storey_rc_frame_sets",
    "2k_embedded_couplings": "two_storey_rc_frame_embedded_couplings",
}


class CanonicalReferenceNamingTests(unittest.TestCase):
    def test_public_lists_use_only_descriptive_canonical_ids(self) -> None:
        model_ids = {row["id"] for row in list_model_resources()}
        material_ids = {row["id"] for row in list_materials()}
        structural_ids = {row["id"] for row in list_structural_resources()}

        self.assertTrue(set(MODEL_ALIASES.values()).issubset(model_ids))
        self.assertTrue(set(MATERIAL_ALIASES.values()).issubset(material_ids))
        self.assertTrue(set(STRUCTURAL_ALIASES.values()).issubset(structural_ids))
        self.assertFalse(set(MODEL_ALIASES) & model_ids)
        self.assertFalse(set(MATERIAL_ALIASES) & material_ids)
        self.assertFalse(set(STRUCTURAL_ALIASES) & structural_ids)

    def test_old_model_ids_resolve_to_one_canonical_resource(self) -> None:
        for legacy_id, canonical_id in MODEL_ALIASES.items():
            with self.subTest(legacy_id=legacy_id):
                legacy = get_model_resource(legacy_id)
                self.assertEqual(canonical_id, legacy["id"])
                self.assertIn(legacy_id, legacy["aliases"])

    def test_old_material_and_structural_ids_resolve_to_canonical_resources(self) -> None:
        for legacy_id, canonical_id in MATERIAL_ALIASES.items():
            with self.subTest(kind="material", legacy_id=legacy_id):
                legacy = get_material(legacy_id)
                self.assertEqual(canonical_id, legacy["id"])
                self.assertIn(legacy_id, legacy["aliases"])

        for legacy_id, canonical_id in STRUCTURAL_ALIASES.items():
            with self.subTest(kind="structural", legacy_id=legacy_id):
                legacy = get_structural_resource(legacy_id)
                self.assertEqual(canonical_id, legacy["id"])
                self.assertIn(legacy_id, legacy["aliases"])

    def test_old_and_canonical_model_exports_are_byte_identical(self) -> None:
        canonical_ids = {row["id"] for row in list_model_resources()}
        self.assertIn("two_storey_rc_frame_beam_reference", canonical_ids)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = export_model_resource("2k_rc_beam_reference", root / "legacy.k")
            canonical = export_model_resource(
                "two_storey_rc_frame_beam_reference",
                root / "canonical.k",
            )

            self.assertEqual(legacy.read_bytes(), canonical.read_bytes())

    def test_canonical_review_records_promote_canonical_and_alias_queries(self) -> None:
        for legacy_id, canonical_id in MATERIAL_ALIASES.items():
            with self.subTest(kind="material", canonical_id=canonical_id):
                canonical = get_material(canonical_id)
                legacy = get_material(legacy_id)
                self.assertEqual("syntax_unit_reviewed", canonical["effective_validation_status"])
                self.assertEqual(canonical_id, canonical["review"]["id"])
                self.assertEqual(canonical["review"], legacy["review"])

        for legacy_id, canonical_id in STRUCTURAL_ALIASES.items():
            with self.subTest(kind="structural", canonical_id=canonical_id):
                canonical = get_structural_resource(canonical_id)
                legacy = get_structural_resource(legacy_id)
                self.assertEqual("syntax_unit_reviewed", canonical["effective_validation_status"])
                self.assertEqual(canonical_id, canonical["review"]["id"])
                self.assertEqual(canonical["review"], legacy["review"])


class AliasCollisionTests(unittest.TestCase):
    @staticmethod
    def _write_manifest(root: Path, folder: str, resource: dict[str, object]) -> None:
        target = root / folder
        target.mkdir(parents=True)
        (target / "manifest.json").write_text(
            json.dumps(resource, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_duplicate_alias_is_rejected_during_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_manifest(root, "one", {"id": "canonical_one", "aliases": ["legacy"]})
            self._write_manifest(root, "two", {"id": "canonical_two", "aliases": ["legacy"]})

            with self.assertRaisesRegex(ValueError, "duplicate model resource alias 'legacy'"):
                load_model_resources(root)

    def test_alias_that_collides_with_canonical_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_manifest(root, "one", {"id": "canonical_one", "aliases": ["canonical_two"]})
            self._write_manifest(root, "two", {"id": "canonical_two"})

            with self.assertRaisesRegex(ValueError, "model resource alias 'canonical_two' collides"):
                load_model_resources(root)


class CanonicalGeneratorNamingTests(unittest.TestCase):
    def test_material_generator_writes_canonical_ids_with_legacy_aliases(self) -> None:
        assets = {row["id"]: row for row in _2k_material_assets()}

        self.assertEqual(set(MATERIAL_ALIASES.values()), set(assets))
        for legacy_id, canonical_id in MATERIAL_ALIASES.items():
            with self.subTest(legacy_id=legacy_id):
                self.assertEqual([legacy_id], assets[canonical_id]["aliases"])
                self.assertNotIn("2.k", assets[canonical_id]["display_name"])

    def test_component_generator_specs_use_canonical_ids(self) -> None:
        self.assertEqual(
            {
                "two_storey_rc_frame_beam_reference",
                "two_storey_rc_frame_column_reference",
                "two_storey_rc_frame_slab_reference",
                "two_storey_rc_frame_foundation_reference",
            },
            set(COMPONENT_RESOURCE_SPECS),
        )


class CanonicalImportEntrypointTests(unittest.TestCase):
    def test_canonical_and_legacy_import_entrypoints_expose_descriptive_identity(self) -> None:
        root = Path(__file__).resolve().parents[1]
        canonical_script = root / "scripts" / "import_two_storey_rc_frame_blast_reference.py"
        self.assertTrue(canonical_script.is_file())

        for script in (canonical_script, root / "scripts" / "import_2k_resources.py"):
            with self.subTest(script=script.name):
                completed = subprocess.run(
                    [sys.executable, str(script), "--help"],
                    cwd=root,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, completed.returncode, completed.stderr)
                self.assertIn("Two-Storey Reinforced Concrete Frame Blast Reference Model", completed.stdout)
                self.assertIn("two_storey_rc_frame_blast_reference", completed.stdout)

if __name__ == "__main__":
    unittest.main()
