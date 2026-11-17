"""Run the three-round R12 knowledge evaluation without launching a solver."""
from __future__ import annotations

import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lsprepost_mcp.knowledge import DEFAULT_CATALOG, INDEXES, KnowledgeBase
from lsprepost_mcp.knowledge_vectors import MIN_SEMANTIC_SCORE, MODEL, VectorStore
from lsprepost_mcp.knowledge_workflow import collect_evidence


FIXTURE = DEFAULT_CATALOG.with_name("three_round_evaluation.json")
TOP_K = 3
STAGES = {
    "architect": "I_case", "meshing": "I_model", "input_writer": "I_model",
    "runner": "I_run", "reviewer": "I_run", "visualization": "I_run",
}


def ranked_records(records: list[dict]) -> list[dict]:
    fields = ("id", "index", "score", "semantic_score", "retrieval_method")
    return [{field: record[field] for field in fields if field in record} for record in records]


def hit_counts(rows: list[dict], method: str) -> dict:
    counts = {"queries": len(rows), "hit_at_1": 0, "hit_at_3": 0}
    for row in rows:
        expected = row["expect"]
        expected_ids = {expected} if isinstance(expected, str) else set(expected)
        ranked = [candidate["id"] for candidate in row[method]]
        counts["hit_at_1"] += bool(expected_ids.intersection(ranked[:1]))
        counts["hit_at_3"] += bool(expected_ids.intersection(ranked[:TOP_K]))
    return counts


def round_retrieval(kb: KnowledgeBase, hybrid: KnowledgeBase, checks: list[dict]) -> dict:
    rows = []
    for check in checks:
        options = {"index": check["index"], "case_family": check["family"], "limit": TOP_K}
        rows.append({**check, "lexical": ranked_records(kb.search(check["query"], **options)),
                     "hybrid": ranked_records(hybrid.search(check["query"], **options))})
    return {"summary": {method: {
                **hit_counts(rows, method),
                "by_index": {index: hit_counts([row for row in rows if row["index"] == index], method)
                             for index in INDEXES},
            } for method in ("lexical", "hybrid")}, "results": rows}


def round_routing(kb: KnowledgeBase, vectors: VectorStore, checks: list[dict]) -> dict:
    flat_ids, matrices = [], []
    for name in INDEXES:
        index, ids = vectors._index(name)
        flat_ids.extend(ids)
        matrices.append(index.reconstruct_n(0, index.ntotal))
    flat = vectors.faiss.IndexFlatIP(matrices[0].shape[1])
    flat.add(vectors.np.concatenate(matrices))
    vectors.loaded["flat"] = flat, flat_ids

    rows = []
    for check in checks:
        eligible = {record["id"] for record in kb.records
                    if kb._allowed(record, "R12", check["family"], "general_modeling")}
        vector = vectors.embed([check["query"]], query=True)
        row = {**check, "eligible_flat": len(eligible),
               "eligible_routed": sum(kb.by_id[key]["index"] == check["index"] for key in eligible)}
        for method, index in (("flat", "flat"), ("routed", check["index"])):
            row[method] = [{"id": key, "index": kb.by_id[key]["index"], "score": round(score, 6)}
                           for key, score in vectors.candidates(index, vector, eligible, limit=TOP_K)]
        rows.append(row)

    summary = {}
    for method in ("flat", "routed"):
        off_index = [[candidate["index"] != row["index"] for candidate in row[method]] for row in rows]
        summary[method] = {**hit_counts(rows, method),
                           "off_index_queries": sum(any(flags) for flags in off_index),
                           "off_index_candidates": sum(sum(flags) for flags in off_index),
                           "returned_candidates": sum(map(len, off_index))}
    return {"summary": summary, "results": rows}


def audit_manual_page(kb: KnowledgeBase, previews: list[dict], spec: dict) -> dict:
    key, page = spec["id"], spec["page"]
    metadata = kb.by_id[key]["manual"]
    location = (kb.base / metadata["page_database"]).resolve().as_uri()
    with closing(sqlite3.connect(f"{location}?mode=ro", uri=True)) as db:
        source = db.execute("SELECT text FROM source_pages WHERE source_id = ? AND pdf_page = ?",
                            (metadata["source_id"], page)).fetchone()
    context = kb.context(key, page=page)
    preview = [p["pdf_page"] for item in previews if item["record_id"] == key
               for p in item["payload"]["pages"]]
    return {"id": key, "preview_pages": preview, "requested_page": page,
            "source": context["source"]["locator"],
            "pass": preview == [metadata["pages"][0]["pdf_page"]] and page not in preview
            and source is not None and context["source"]["source_release"] == "R12"
            and context["payload"]["pages"] == [{"pdf_page": page, "text": source[0]}]
            and spec["marker"] in source[0]}


def audit_case(kb: KnowledgeBase, bundle: dict, check: dict) -> dict:
    case_id = check["expect"]
    case = kb.by_id[case_id]
    deck = case["deck"]
    source = kb.base / case["source"]["path"]
    if deck.get("standalone"):
        original = source.read_bytes()
    else:
        with ZipFile(source) as archive:
            original = archive.read(deck["member"])
    lines = original.decode(deck["encoding"]).splitlines(keepends=True)
    stages = {stage["stage"]: stage for stage in bundle["stages"]}
    writer = stages.get("input_writer", {})
    topics = {item["payload"]["topic"]: item for item in writer.get("evidence", []) if "topic" in item["payload"]}
    excerpts = {}
    for topic, card in check["cards"].items():
        item = topics.get(topic, {})
        payload = item.get("payload", {})
        blocks = payload.get("blocks", [])
        spans = []
        for block in blocks:
            start, end = block["start_line"], block["end_line"]
            spans.append({"keyword": block["keyword"], "start_line": start, "end_line": end,
                          "source_match": 1 <= start <= end <= len(lines)
                          and block["text"] == "".join(lines[start - 1:end])})
        excerpts[topic] = {"id": item.get("record_id"), "member": payload.get("member"), "spans": spans,
                           "pass": payload.get("case_id") == case_id and payload.get("member") == deck["member"]
                           and card in {span["keyword"] for span in spans}
                           and all(span["source_match"] for span in spans)
                           and item.get("reference_only") is True and payload.get("r12_execution") == "unverified"}

    def ids(stage: str, field: str = "evidence") -> set[str]:
        return {item["record_id"] for item in stages.get(stage, {}).get(field, [])}

    stage_links = (list(stages) == list(STAGES) and all(
        stages[name]["index"] == index and stages[name]["case_id"] == case_id
        and stages[name]["status"] == "matched" for name, index in STAGES.items()
    ) and "r12.node" in ids("meshing") and {"run.workflow", "run.solver"} <= ids("runner")
        and {"tool.import_keyword", "tool.validate_model"} <= ids("runner", "tools")
        and "run.results" in ids("reviewer") and "run.results" in ids("visualization")
        and excerpts["output"]["id"] in ids("visualization", "output_setup"))
    manual = audit_manual_page(kb, writer.get("manual_definitions", []), check["manual"]) if "manual" in check else None
    archive_ok = sha256(original).hexdigest() == deck["sha256"]
    return {"stage_links": stage_links, "archive_digest_matches": archive_ok,
            "excerpts": excerpts, "manual": manual,
            "pass": stage_links and archive_ok and all(item["pass"] for item in excerpts.values())
            and (manual is None or manual["pass"])}


def round_workflow(kb: KnowledgeBase, checks: list[dict]) -> dict:
    rows = []
    for check in checks:
        bundle = collect_evidence(kb, check["query"], **check["options"])
        selected = bundle["case_id"]
        row = {**check, "selected": selected, "status": bundle["status"],
               "candidates": ranked_records(bundle["stages"][0]["candidates"]),
               "stages": [{key: stage[key] for key in ("stage", "index", "case_id", "status")}
                          for stage in bundle["stages"]]}
        if check["expect"] is None:
            row["pass"] = (selected is None and bundle["status"] == "no_applicable_reference"
                           and len(bundle["stages"]) == 1 and not row["candidates"])
        else:
            row["audit"] = audit_case(kb, bundle, check) if selected == check["expect"] else None
            row["pass"] = row["audit"] is not None and row["audit"]["pass"]
        rows.append(row)
    positives = [row for row in rows if row["expect"] is not None]
    negatives = [row for row in rows if row["expect"] is None]
    audits = [row["audit"] for row in positives if row["audit"] is not None]
    return {"summary": {"positive_queries": len(positives), "correct_cases": len(audits),
                        "verified_workflows": sum(row["pass"] for row in positives),
                        "negative_queries": len(negatives), "rejected": sum(row["pass"] for row in negatives),
                        "audited_excerpts": sum(len(audit["excerpts"]) for audit in audits),
                        "verified_excerpts": sum(item["pass"] for audit in audits
                                                 for item in audit["excerpts"].values())},
            "results": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    frozen = FIXTURE.read_bytes()
    checks = json.loads(frozen)
    kb = KnowledgeBase()
    vectors = VectorStore(kb)
    hybrid = KnowledgeBase(vector_search=vectors.search)
    rounds = {"retrieval": round_retrieval(kb, hybrid, checks["retrieval"]),
              "routing": round_routing(kb, vectors, checks["routing"]),
              "workflow": round_workflow(hybrid, checks["workflow"])}
    report = {"fixture_sha256": sha256(frozen).hexdigest(), "snapshot_sha256": kb.snapshot,
              "model": MODEL, "hybrid_semantic_cutoff": MIN_SEMANTIC_SCORE, "top_k": TOP_K,
              "routing_semantic_cutoff": None, "rounds": rounds}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: result["summary"] for name, result in rounds.items()}, indent=2))


if __name__ == "__main__":
    main()
