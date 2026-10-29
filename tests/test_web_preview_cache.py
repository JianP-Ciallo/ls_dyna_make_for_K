from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from lsprepost_mcp.web.preview_cache import PreviewMeshCache


class PreviewMeshCacheTests(unittest.TestCase):
    def make_project(self, root: Path, name: str, keyword: str = "*KEYWORD\n*END\n") -> Path:
        project = root / name
        project.mkdir()
        (project / "model.k").write_text(keyword, encoding="utf-8")
        (project / "model.json").write_text('{"schema_version": 1}', encoding="utf-8")
        return project

    def test_reuses_mesh_until_an_input_content_hash_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary), "alpha")
            builder = Mock(side_effect=lambda path: {"project_name": path.name, "call": builder.call_count})
            cache = PreviewMeshCache(max_entries=4, max_serialized_bytes=1024 * 1024)

            first = cache.get_or_build(project, builder)
            second = cache.get_or_build(project, builder)
            (project / "model.k").write_text("*KEYWORD\n$ changed\n*END\n", encoding="utf-8")
            third = cache.get_or_build(project, builder)

        self.assertIs(first, second)
        self.assertIsNot(second, third)
        self.assertEqual(2, builder.call_count)

    def test_evicts_least_recently_used_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            projects = [self.make_project(root, name) for name in ("alpha", "beta", "gamma")]
            builder = Mock(side_effect=lambda path: {"project_name": path.name})
            cache = PreviewMeshCache(max_entries=2, max_serialized_bytes=1024 * 1024)

            cache.get_or_build(projects[0], builder)
            cache.get_or_build(projects[1], builder)
            cache.get_or_build(projects[0], builder)
            cache.get_or_build(projects[2], builder)
            cache.get_or_build(projects[1], builder)

        self.assertEqual(4, builder.call_count)
        self.assertEqual(2, cache.entry_count)

    def test_does_not_cache_single_payload_larger_than_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self.make_project(Path(temporary), "large")
            builder = Mock(return_value={"payload": "x" * 4096})
            cache = PreviewMeshCache(max_entries=4, max_serialized_bytes=128)

            cache.get_or_build(project, builder)
            cache.get_or_build(project, builder)

        self.assertEqual(2, builder.call_count)
        self.assertEqual(0, cache.entry_count)


if __name__ == "__main__":
    unittest.main()
