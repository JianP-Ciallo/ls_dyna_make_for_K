#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
export PYTHONDONTWRITEBYTECODE=1
exec python3 "$ROOT/lsprepost_mcp/server.py"
