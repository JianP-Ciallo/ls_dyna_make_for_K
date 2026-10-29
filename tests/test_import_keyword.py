from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lsprepost_mcp.io import write_json
from lsprepost_mcp.project_store import parse_keyword_metadata, validate_project_files


class ImportKeywordTests(unittest.TestCase):
    def test_parses_part_material_section_references(self) -> None:
        keyword = """*KEYWORD
*NODE
1,0,0,0
2,1,0,0
3,1,1,0
4,0,1,0
*ELEMENT_SHELL
1,1,1,2,3,4
*PART
part one
$ pid secid mid
1,10,20,0,0,0,0,0
*SECTION_SHELL
10,2
*MAT_ELASTIC
20,7850,2.1e11,0.3
*END
"""
        metadata = parse_keyword_metadata(keyword)
        self.assertEqual(metadata["node_count"], 4)
        self.assertEqual(metadata["element_count"], 1)
        self.assertEqual(metadata["material_ids"], [20])
        self.assertEqual(metadata["section_ids"], [10])
        self.assertEqual(metadata["part_references"], [{"pid": 1, "section_id": 10, "material_id": 20}])
        self.assertEqual(metadata["semantic_warnings"], [])

    def test_reports_missing_references(self) -> None:
        keyword = """*KEYWORD
*PART
bad part
1,10,20
*END
"""
        metadata = parse_keyword_metadata(keyword)
        self.assertEqual(metadata["missing_material_refs"], [20])
        self.assertEqual(metadata["missing_section_refs"], [10])
        self.assertEqual(len(metadata["semantic_warnings"]), 2)

    def test_metadata_ignores_fake_prefixed_cards(self) -> None:
        keyword = """*KEYWORD
*NODE_NOT_REAL
1,0,0,0
*ELEMENT_SHELL_NOT_REAL
1,1,1,2,3,4
*PART_NOT_REAL
fake part
1,10,20
*SECTION_SHELL
10,2
*MAT_ELASTIC
20,7850,2.1e11,0.3
*END
"""
        metadata = parse_keyword_metadata(keyword)
        self.assertEqual(metadata["node_count"], 0)
        self.assertEqual(metadata["element_count"], 0)
        self.assertEqual(metadata["part_count"], 0)
        self.assertEqual(metadata["part_references"], [])
        self.assertEqual(metadata["missing_material_refs"], [])
        self.assertEqual(metadata["missing_section_refs"], [])

    def test_imported_keyword_runs_quality_checks(self) -> None:
        keyword = """*KEYWORD
*NODE
1,0,0,0
1,1,0,0
2,1,1,0
3,0,1,0
*ELEMENT_SHELL
1,1,1,2,3,99
*PART
bad
1,1,1
*SECTION_SHELL
1,2
0.001,0.001,0.001,0.001
*MAT_ELASTIC
1,7850,2.1e11,0.3
*END
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "model.k").write_text(keyword, encoding="utf-8")
            write_json(
                path / "model.json",
                {
                    "schema_version": "0.2.0",
                    "spec": {"project_name": "imported_bad", "model_type": "imported_keyword"},
                    "metadata": parse_keyword_metadata(keyword) | {"model_type": "imported_keyword", "unit_system": "unknown"},
                },
            )
            checks = validate_project_files(path)
        by_id = {item["id"]: item for item in checks["checks"]}
        self.assertFalse(checks["ok"])
        self.assertFalse(by_id["quality.id.nodes_unique"]["ok"])
        self.assertFalse(by_id["quality.ref.element_nodes"]["ok"])

    def test_readiness_blocks_solver_draft_for_contact_card(self) -> None:
        keyword = """*KEYWORD
*NODE
1,0,0,0
2,1,0,0
3,1,1,0
4,0,1,0
*ELEMENT_SHELL
1,1,1,2,3,4
*PART
part
1,1,1
*SECTION_SHELL
1,2
0.001,0.001,0.001,0.001
*MAT_ELASTIC
1,7850,2.1e11,0.3
*CONTACT_AUTOMATIC_SINGLE_SURFACE
*END
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "model.k").write_text(keyword, encoding="utf-8")
            write_json(
                path / "model.json",
                {
                    "schema_version": "0.2.0",
                    "spec": {"project_name": "imported_contact", "model_type": "imported_keyword"},
                    "metadata": parse_keyword_metadata(keyword) | {"model_type": "imported_keyword", "unit_system": "unknown"},
                },
            )
            checks = validate_project_files(path)
        self.assertTrue(checks["ok"])
        self.assertFalse(checks["readiness"]["ok_for_solver_draft"])
        self.assertIn("quality.unsupported.contact_cards", checks["readiness"]["solver_warning_blockers"])


if __name__ == "__main__":
    unittest.main()
