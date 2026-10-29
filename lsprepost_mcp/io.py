from __future__ import annotations

import json
from pathlib import Path

from .config import JSONDict


def write_json(path: Path, data: JSONDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> JSONDict:
    return json.loads(path.read_text(encoding="utf-8"))
