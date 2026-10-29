from __future__ import annotations

import ast
import unittest
from pathlib import Path


class Phase18CDependencyBoundaryTests(unittest.TestCase):
    def test_refined_building_package_has_no_scene_generator_imports(self) -> None:
        package_root = Path(__file__).resolve().parents[1] / "lsprepost_mcp" / "refined_building"
        forbidden = (
            "lsprepost_mcp.city_",
            "lsprepost_mcp.ale_blast",
            "lsprepost_mcp.dyna_assembly",
        )
        violations: list[str] = []

        for path in sorted(package_root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules.append(node.module)
                for module in modules:
                    if module == forbidden[2] or module.startswith(forbidden):
                        violations.append(f"{path.name}:{node.lineno}:{module}")

        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
