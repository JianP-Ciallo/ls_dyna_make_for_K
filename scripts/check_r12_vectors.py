"""Compare flat and stage-selected dense recall on the same frozen corpus."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lsprepost_mcp.knowledge import DEFAULT_CATALOG, EXCLUDED_TERMS, INDEXES, KnowledgeBase, _normalize
from lsprepost_mcp.knowledge_vectors import MIN_SEMANTIC_SCORE, MODEL, VectorStore


def main() -> None:
    kb = KnowledgeBase()
    vectors = VectorStore(kb)
    checks = json.loads(DEFAULT_CATALOG.with_name("semantic_checks.json").read_text(encoding="utf-8"))
    flat_ids, matrices = [], []
    for name in INDEXES:
        index, ids = vectors._index(name)
        flat_ids.extend(ids)
        matrices.append(index.reconstruct_n(0, index.ntotal))
    flat = vectors.faiss.IndexFlatIP(matrices[0].shape[1])
    flat.add(vectors.np.concatenate(matrices))
    vectors.loaded["flat"] = (flat, flat_ids)
    rows = []
    for check in checks:
        query, index, family = (check[k] for k in ("query", "index", "family"))
        options = {"index": index, "case_family": family}
        sparse = [r["id"] for r in kb.search(query, **options)]
        kb.vector_search = vectors.search
        hybrid = [r["id"] for r in kb.search(query, **options)]
        kb.vector_search = None
        normalized = _normalize(query)
        guarded = (any(term in normalized for term in EXCLUDED_TERMS)
                   or any(v != "r12" for v in re.findall(r"(?<![a-z0-9])r\d{2}(?![a-z0-9])", normalized)))
        eligible = {r["id"] for r in kb.records if kb._allowed(r, "R12", family, "general_modeling")}
        dense = {"flat": [], "four_indexes": []}
        if not guarded:
            vector = vectors.embed([query], query=True)
            for method, scope in (("flat", "flat"), ("four_indexes", index)):
                dense[method] = [{"id": key, "score": round(score, 6)} for key, score in
                                 vectors.candidates(scope, vector, eligible)]
        rows.append({**check, "lexical": sparse, "hybrid": hybrid, **dense})
    positives = [row for row in rows if row["expect"]]
    scores = {}
    for method in ("lexical", "flat", "four_indexes", "hybrid"):
        ranked = [[x if isinstance(x, str) else x["id"] for x in row[method]] for row in positives]
        scores[method] = {"top1": sum(bool(ids) and ids[0] == row["expect"] for ids, row in zip(ranked, positives)),
                          "top3": sum(row["expect"] in ids for ids, row in zip(ranked, positives))}
    print(json.dumps({"snapshot_sha256": kb.snapshot, "model": MODEL, "positive_queries": len(positives),
                      "semantic_cutoff": MIN_SEMANTIC_SCORE,
                      "scores": scores, "hybrid_rejected": sum(not r["hybrid"] for r in rows if r["expect"] is None),
                      "negative_queries": len(rows) - len(positives), "results": rows}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
