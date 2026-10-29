from __future__ import annotations

import ast
from pathlib import Path


def imported_module_tokens(root: Path) -> set[str]:
    tokens: set[str] = set()
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                tokens.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                tokens.add(node.module)
    return tokens


def test_refined_blast_has_no_legacy_imports():
    forbidden = {"city_street_blast", "blast_cases", "dyna_assembly", "web.draft_preview"}
    assert imported_module_tokens(Path("lsprepost_mcp/refined_blast")).isdisjoint(forbidden)
