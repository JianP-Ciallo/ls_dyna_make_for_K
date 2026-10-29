from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "var" / "generated_configs"
DEFAULT_LSPP_EXE = os.environ.get("LSPP_EXE", "<LS_PREPOST_INSTALL_DIR>\\lsprepost4.12.exe")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stdio_server(lspp_exe: str) -> dict[str, Any]:
    return {
        "command": "cmd",
        "args": ["/c", str(ROOT / "scripts" / "start_mcp_server.cmd")],
        "env": {"LSPP_EXE": lspp_exe},
    }


def vscode_server(lspp_exe: str) -> dict[str, Any]:
    server = stdio_server(lspp_exe)
    return {"type": "stdio", **server}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate MCP client config snippets for lsprepost-mcp."
    )
    parser.add_argument("--lspp-exe", default=DEFAULT_LSPP_EXE, help="Path to lsprepost*.exe")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output directory")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    lspp_exe = str(Path(args.lspp_exe))

    mcp_servers = {"mcpServers": {"lsprepost": stdio_server(lspp_exe)}}
    servers = {"servers": {"lsprepost": vscode_server(lspp_exe)}}

    write_json(out / "cursor.mcp.json", mcp_servers)
    write_json(out / "claude_desktop_config.fragment.json", mcp_servers)
    write_json(out / "codex.mcp.json", mcp_servers)
    write_json(out / "windsurf.mcp.json", mcp_servers)
    write_json(out / "vscode.mcp.json", servers)
    write_json(out / "visualstudio.mcp.json", servers)

    print(f"Generated MCP configs in: {out}")
    print(f"LS-PrePost executable: {lspp_exe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
