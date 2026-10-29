from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest import SkipTest


def node_executable() -> Path:
    """Locate Node without binding the test suite to one developer machine."""
    configured = os.environ.get("LSPREPOST_MCP_NODE")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return candidate

    on_path = shutil.which("node")
    if on_path:
        return Path(on_path)

    runtime_root = Path.home() / ".cache" / "codex-runtimes"
    for candidate in sorted(runtime_root.glob("*/dependencies/node/bin/node.exe")):
        if candidate.is_file():
            return candidate

    raise SkipTest(
        "Node runtime unavailable; set LSPREPOST_MCP_NODE or install node on PATH"
    )
