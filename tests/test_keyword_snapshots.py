from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from lsprepost_mcp.dyna_keyword import build_keyword
from lsprepost_mcp.io import read_json
from lsprepost_mcp.schema import (
    cube_top_corner_load_spec,
    default_model_spec,
    parse_model_spec,
    plate_pressure_spec,
    rebar_drop_on_helmet_spec,
    rod_impact_plate_spec,
)


class KeywordSnapshotTests(unittest.TestCase):
    def test_keyword_snapshots_match_manifest(self) -> None:
        manifest = read_json(Path(__file__).parent / "snapshots" / "keyword_hashes.json")
        cases = manifest["cases"]
        for name, expected in cases.items():
            with self.subTest(name=name):
                keyword, metadata = build_keyword(parse_model_spec(snapshot_spec(expected)))
                actual_sha = hashlib.sha256(keyword.encode("utf-8")).hexdigest()
                self.assertEqual(expected["sha256"], actual_sha)
                self.assertEqual(expected["line_count"], len(keyword.splitlines()))
                self.assertEqual(expected["node_count"], metadata.get("node_count"))
                self.assertEqual(expected["element_count"], metadata.get("element_count"))
                if "part_count" in expected:
                    self.assertEqual(expected["part_count"], metadata.get("part_count"))


def snapshot_spec(entry: dict) -> dict:
    scene_builders = {
        "rebar_drop_on_helmet": rebar_drop_on_helmet_spec,
        "rod_impact_plate": rod_impact_plate_spec,
        "cube_top_corner_load": cube_top_corner_load_spec,
        "plate_pressure": plate_pressure_spec,
    }
    scene = entry.get("scene")
    if scene in scene_builders:
        return scene_builders[scene](str(entry["project_name"]))
    return default_model_spec(str(entry["project_name"]), str(entry["model_type"]))


if __name__ == "__main__":
    unittest.main()
