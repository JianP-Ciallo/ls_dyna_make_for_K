"""Read-only status and original-page access for the local knowledge dashboard."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from lsprepost_mcp.knowledge import INDEXES, KnowledgeBase
from lsprepost_mcp.knowledge_vectors import LOCAL, MODEL, SCHEMA
from lsprepost_mcp.web.http_utils import ApiError


PREPOST_MANUALS = {
    "prepost-tutorial.pdf": ("supp.prepost_history", "ls-prepost-tutorial.pdf", 161),
    "lspost.pdf": ("supp.lspost_cfile", "lspost.pdf", 156),
}


def _manual_bytes(kb: KnowledgeBase, route: str) -> bytes:
    key, expected_name, _ = PREPOST_MANUALS[route]
    source = kb.by_id.get(key, {}).get("source", {})
    if source.get("filename") != expected_name or Path(source.get("path", "")).name != expected_name:
        raise ApiError(404, "manual_unavailable", "手册未登记")
    try:
        pdf = (kb.base / source["path"]).read_bytes()
    except OSError as exc:
        raise ApiError(404, "manual_unavailable", "找不到登记的本地手册") from exc
    if not pdf.startswith(b"%PDF-") or sha256(pdf).hexdigest() != source["sha256"]:
        raise ApiError(409, "manual_changed", "手册内容与登记的哈希不匹配")
    return pdf


def dashboard_payload() -> dict:
    kb = KnowledgeBase()
    manuals = []
    manuals_by_name = {}
    for route, (_, filename, total_pages) in PREPOST_MANUALS.items():
        try:
            _manual_bytes(kb, route)
            available = True
        except ApiError:
            available = False
        item = {"file": filename, "pages": total_pages, "available": available,
                "count": 0, "indexed_pages": 0, "url": f"/api/knowledge/{route}"}
        manuals_by_name[filename] = item
        manuals.append(item)

    visible = {r["id"] for r in kb.records if r["admitted"] and r.get("domain", "general_modeling") == "general_modeling"}
    files_pages = {filename: set() for filename in manuals_by_name}
    records = []
    for r in kb.records:
        if r["id"] not in visible:
            continue
        source = r["source"]
        filename = source.get("filename") or Path(source["path"]).name
        manual = manuals_by_name.get(filename)
        pages = [page["pdf_page"] for page in r.get("manual", {}).get("pages", [])]
        url = source.get("url", "")
        url = url if urlsplit(url).scheme in {"http", "https"} else None
        pdf_url = None
        if manual:
            files_pages[filename].update(pages)
            manual["count"] += 1
            if manual["available"] and pages:
                pdf_url = f"{manual['url']}#page={pages[0]}"
        elif url and urlsplit(url).path.lower().endswith(".pdf"):
            match = re.search(r"\bPDF (\d+)", source["locator"])
            if match:
                pdf_url = f"{url}#page={match.group(1)}"
        guide = r.get("recipe", r)
        records.append({"id": r["id"], "index": r["index"], "title": r["title"], "aliases": r["aliases"],
                        "summary": r["summary"], "collection": r.get("collection", "primary"),
                        "evidence": r.get("evidence_level"), "execution": r.get("r12_execution"),
                        "source": filename, "release": source.get("source_release"), "locator": source["locator"],
                        "url": url, "pdf_url": pdf_url, "steps": guide.get("steps", []), "checks": guide.get("checks", []),
                        "related": [key for key in r.get("related_ids", []) if key in visible]})
    for manual in manuals:
        manual["indexed_pages"] = len(files_pages[manual["file"]])

    counts = Counter((r["index"], r["collection"]) for r in records)
    vector_root = LOCAL / "vector_indexes" / str(kb.snapshot)
    try:
        manifest = json.loads((vector_root / "manifest.json").read_bytes())
    except (ValueError, OSError):
        manifest = {}
    manifest_matches = (manifest.get("snapshot_sha256"), manifest.get("model"), manifest.get("schema")) == (kb.snapshot, MODEL, SCHEMA)
    indexes = []
    for index in INDEXES:
        primary, supplement = counts[index, "primary"], counts[index, "supplement"]
        vector_file = vector_root / f"{index}.faiss"
        vector_ids = [r["id"] for r in kb.records if r["index"] == index and r["admitted"]]
        vector_meta = manifest.get("indexes", {}).get(index, {})
        ready = (manifest_matches and vector_meta.get("record_ids") == vector_ids and vector_file.is_file()
                 and sha256(vector_file.read_bytes()).hexdigest() == vector_meta.get("sha256"))
        indexes.append({"id": index, "count": primary + supplement, "primary": primary,
                        "supplement": supplement, "vector_ready": ready})
    return {"snapshot": kb.snapshot, "indexes": indexes, "manuals": manuals, "records": records}


def manual_response(route: str) -> tuple[int, dict[str, str], bytes] | None:
    if route not in PREPOST_MANUALS:
        return None
    return 200, {"Content-Type": "application/pdf", "Content-Disposition": f'inline; filename="{route}"',
                 "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}, _manual_bytes(KnowledgeBase(), route)
