"""Run the frozen retrieval smoke questions against the current R12 catalog."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lsprepost_mcp.knowledge import DEFAULT_CATALOG, KnowledgeBase


def main() -> int:
    kb = KnowledgeBase()
    checks = json.loads(DEFAULT_CATALOG.with_name("retrieval_checks.json").read_text(encoding="utf-8"))
    results = []
    for check in checks:
        options = {key: check[key] for key in ("case_family", "domain", "analysis", "collection", "source_release", "case_id", "support")
                   if key in check}
        options.setdefault("case_family", "general")
        if "stage" in check:
            candidates = kb.retrieve(check["query"], stage=check["stage"], **options)["candidates"]
        else:
            candidates = kb.search(check["query"], index=check["index"], **options)
        actual = candidates[0]["id"] if candidates else None
        results.append({**check, "actual": actual, "passed": actual == check["expect"],
                        "candidates": [{"id": item["id"], "score": item["score"],
                                        "source": item["source"]["locator"]} for item in candidates]})
    matched = sum(result["passed"] for result in results)
    print(json.dumps({"snapshot_sha256": kb.snapshot, "checks": len(results), "passed": matched,
                      "results": results}, ensure_ascii=False, indent=2))
    return 0 if matched == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
