from __future__ import annotations

import json
import shutil
import unittest

from lsprepost_mcp.paths import project_dir
from lsprepost_mcp.web.preview_mesh import build_preview_mesh

from tests.test_web_api import request_json, web_test_server


class WebPreviewMeshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = project_dir("unit_web_preview_mesh")
        if self.project.exists():
            shutil.rmtree(self.project)
        self.project.mkdir(parents=True)
        (self.project / "model.k").write_text(
            "\n".join(
                [
                    "*KEYWORD",
                    "*NODE",
                    "1,0,0,0",
                    "2,1,0,0",
                    "3,1,1,0",
                    "4,0,1,0",
                    "*ELEMENT_SHELL",
                    "1,7,1,2,3,4",
                    "*END",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        if self.project.exists():
            shutil.rmtree(self.project)

    def test_build_preview_mesh_from_shell_keyword(self) -> None:
        mesh = build_preview_mesh(self.project)

        self.assertEqual(mesh["project_name"], "unit_web_preview_mesh")
        self.assertEqual(mesh["format"], "lsprepost_mcp_preview_mesh_v1")
        self.assertEqual(len(mesh["parts"]), 1)
        part = mesh["parts"][0]
        self.assertEqual(part["part_id"], 7)
        self.assertEqual(part["element_family"], "shell")
        self.assertEqual(len(part["nodes"]), 4)
        self.assertEqual(part["faces"], [[0, 1, 2, 3]])
        self.assertEqual({tuple(edge) for edge in part["edges"]}, {(0, 1), (1, 2), (2, 3), (0, 3)})
        self.assertEqual(mesh["bounds"]["min"], [0.0, 0.0, 0.0])
        self.assertEqual(mesh["bounds"]["max"], [1.0, 1.0, 0.0])

    def test_preview_mesh_route_returns_project_mesh(self) -> None:
        with web_test_server() as address:
            status, payload = request_json(
                address,
                "GET",
                "/api/project/preview-mesh?project_name=unit_web_preview_mesh",
            )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["project_name"], "unit_web_preview_mesh")
        self.assertEqual(payload["result"]["parts"][0]["part_id"], 7)

    def test_city_semantic_identity_is_carried_into_preview_part(self) -> None:
        (self.project / "model.json").write_text(
            json.dumps(
                {
                    "metadata": {
                        "model_type": "city_street_blast_scene",
                        "semantic_objects": [
                            {
                                "object_id": "commercial_supermarket",
                                "group_id": "commercial_supermarket",
                                "part_ids": [7],
                            }
                        ],
                    }
                }
            ),
            encoding="utf-8",
        )

        part = build_preview_mesh(self.project)["parts"][0]

        self.assertEqual("commercial_supermarket", part["semantic_object_id"])
        self.assertEqual("commercial_supermarket", part["semantic_group_id"])
        self.assertEqual("commercial_building", part["semantic_category"])
        self.assertEqual("商业超市", part["name"])


if __name__ == "__main__":
    unittest.main()
