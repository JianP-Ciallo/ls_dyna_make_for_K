"""Architectural contracts that keep transport and persistence independent."""
import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("module", ["record_contract", "project_metadata", "project_repository", "generated_records"])
def test_persistence_modules_do_not_import_web_adapters(module):
    tree = ast.parse((ROOT / "lsprepost_mcp/refined_blast" / f"{module}.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets = [item.name for item in node.names]
        elif isinstance(node, ast.ImportFrom):
            target = "." * node.level + (node.module or "")
            targets = [resolve_name(target, "lsprepost_mcp.refined_blast") if node.level else target]
        else:
            continue
        assert not any(target == "lsprepost_mcp.web" or target.startswith("lsprepost_mcp.web.") for target in targets)


def test_http_adapter_does_not_access_store_private_members():
    tree = ast.parse((ROOT / "lsprepost_mcp/web/refined_blast_api.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute) and node.value.attr == "_store":
            assert not node.attr.startswith("_"), f"private store access at line {node.lineno}"
        if isinstance(node, ast.ImportFrom) and node.module == "lsprepost_mcp.refined_blast.store":
            assert all(not item.name.startswith("_") for item in node.names)


def test_launcher_tools_do_not_reach_back_into_the_tool_registry():
    tree = ast.parse((ROOT / "lsprepost_mcp/tool_lsprepost.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            assert (node.value.id, node.attr) != ("sys", "modules")
        if isinstance(node, ast.ImportFrom):
            assert node.module not in ("tools", "lsprepost_mcp.tools")
