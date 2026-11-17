"""Carry one selected case through the six read-only knowledge stages."""
from __future__ import annotations

from .knowledge import KnowledgeBase


def collect_evidence(kb: KnowledgeBase, query: str, *, solver: str = "R12",
                     case_family: str = "general", domain: str = "general_modeling",
                     analysis: str | None = None, support: str | None = None) -> dict:
    plan = kb.retrieve(query, stage="architect", solver=solver, case_family=case_family,
                       domain=domain, analysis=analysis, support=support)
    selected = plan["selected"]
    bundle = {"query": query, "snapshot_sha256": kb.snapshot, "case_id": None,
              "status": plan["status"], "stages": [plan]}
    if selected is None:
        return bundle

    case_id = selected["id"]
    bundle["case_id"] = case_id
    plan["case_id"] = case_id
    related = {item["id"]: item for item in plan["related"]}

    def trace(stage: str, index: str, ids: list[str], *, page_only: bool = False) -> dict:
        records = []
        for key in dict.fromkeys(ids):
            manual = kb.by_id[key].get("manual")
            page = manual["pages"][0]["pdf_page"] if page_only and manual else None
            records.append(kb.context(key, page=page))
        return {"stage": stage, "index": index, "case_id": case_id, "retrieval_method": "case_links",
                "status": "matched" if records else "no_applicable_reference", "evidence": records}

    mesh_ids = [key for key in related if key.startswith(("r12.node", "r12.part", "r12.section_", "r12.element_"))]
    recipes = [key for key in related if kb.by_id[key].get("recipe", {}).get("case_id") == case_id]
    if not recipes:
        recipes = [key for key, item in related.items() if item["index"] == "I_model"]
    run_ids = [key for key, item in related.items() if item["index"] == "I_run"]
    run_related = {item["id"]: item for key in run_ids for item in kb.references(key)}
    tool_ids = [key for key, item in {**related, **run_related}.items() if item["index"] == "I_tool"]
    run_ids += [key for key, item in run_related.items() if item["index"] == "I_run"]
    runner_ids = [key for key in run_ids if key in {"run.workflow", "run.solver"}]
    result_ids = [key for key in run_ids if key == "run.results"]
    out_ids = [key for key in recipes if kb.by_id[key].get("recipe", {}).get("topic") == "output"]

    input_stage = trace("input_writer", "I_model", recipes, page_only=True)
    manual_ids = [item["id"] for key in recipes for item in kb.references(key)
                  if item["index"] == "I_model" and kb.by_id[item["id"]].get("manual")]
    input_stage["manual_definitions"] = trace("input_writer", "I_model", manual_ids, page_only=True)["evidence"]
    input_stage["manual_preview"] = "first_pdf_page; use context RECORD_ID for the complete section"
    bundle["stages"] += [trace("meshing", "I_model", mesh_ids, page_only=True), input_stage,
                         {**trace("runner", "I_run", runner_ids),
                          "tools": trace("runner", "I_tool", tool_ids)["evidence"]},
                         trace("reviewer", "I_run", result_ids),
                         {**trace("visualization", "I_run", result_ids),
                          "output_setup": trace("visualization", "I_model", out_ids)["evidence"]}]
    return bundle
