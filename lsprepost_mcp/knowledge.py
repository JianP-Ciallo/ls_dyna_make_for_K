"""Read-only, source-checked R12 retrieval. No tool or solver execution.

This baseline uses exact identifiers and sparse TF-IDF cosine retrieval.
All retrieved text is reference data, never an instruction to execute.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from copy import deepcopy
import hashlib
import json
from math import log, sqrt
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata
from zipfile import ZipFile


INDEXES = ("I_case", "I_model", "I_run", "I_tool")
DEFAULT_CATALOG = Path(__file__).resolve().parents[1] / "resources/knowledge/r12/catalog.json"
ALLOWED_CASES = frozenset({"shell_plate", "beam_bar", "solid_plate", "thick_shell_plate", "component_contact", "explicit_impact", "spring_mass"})
EXCLUDED_TERMS = ("大型建筑", "整栋", "三层住宅", "large_building", "fixed_building", "city_street")
STAGE_INDEX = {
    "architect": "I_case", "meshing": "I_model", "input_writer": "I_model",
    "runner": "I_run", "reviewer": "I_run", "visualization": "I_run",
}
DOMAINS = ("general_modeling", "blast")
ANALYSIS_TYPES = ("explicit", "implicit", "implicit_transient")
COLLECTIONS = ("primary", "supplement")
SUPPORT_TYPES = ("four_edges_clamped", "four_edges_simply_supported", "one_edge_clamped",
                 "one_end_clamped", "simply_supported", "pinned_ends", "mixed_constraints",
                 "contact_boundary", "rigid_wall", "one_node_fixed")

_SUPPORT_PHRASES = re.compile(
    r"(?P<four_edges_clamped>(?:四边|四周|周边|四条边)(?:都|均|完全|全部|全)?(?:固支|固定|夹紧)|"
    r"\b(?:all (?:four )?edges|four edges) (?:are )?(?:fully )?(?:clamped|fixed)\b|\bfully clamped\b)"
    r"|(?P<four_edges_simply_supported>(?:四边|四周|四条边)(?:都|均|全部)?简支|"
    r"\bsimply supported (?:on )?all (?:four )?edges\b|\ball (?:four )?edges (?:are )?simply supported\b)"
    r"|(?P<one_edge_clamped>(?:单边|一边|一条边)(?:完全)?(?:固支|固定|夹紧)|\bone edge (?:is )?clamped\b)"
    r"|(?P<simply_supported>简支|\bsimply supported\b)"
)
_ELEMENT_PHRASES = re.compile(
    r"(?P<solid>实体(?:单元|方板|网格)|\bsolid (?:elements?|mesh|plate)\b)"
    r"|(?P<thick_shell>厚壳|\bthick[- ]shell\b)|(?P<shell>薄壳|\bthin[- ]shell\b)"
)
_GEOMETRY_PHRASES = re.compile(
    r"(?P<annular_plate>环形(?:薄|厚)?板|环板|\bannular plate\b)"
    r"|(?P<square_plate>方板|方形板|\bsquare (?:shell |solid )?plate\b)"
)


def _positive_matches(pattern: re.Pattern, query: str) -> set[str]:
    return {match.lastgroup for match in pattern.finditer(query)
            if not re.search(r"(?:而非|不是|不要|并非|非|not)\s*(?:采用|使用|a\s+)?$", query[:match.start()])}


def _requested_support(query: str, support: str | None) -> set[str]:
    if support is not None:
        if support not in SUPPORT_TYPES:
            raise ValueError(f"support must be one of {SUPPORT_TYPES}")
    requested = _positive_matches(_SUPPORT_PHRASES, query)
    if support is not None:
        requested.add(support)
    return requested


def _matches_applicability(record: dict, requested: set[str], elements: set[str], geometries: set[str]) -> bool:
    applicability = record.get("applicability", {})
    support = applicability.get("support")
    available = {support}
    if support == "four_edges_simply_supported":
        available.add("simply_supported")
    return (requested <= available and elements <= {applicability.get("element")}
            and geometries <= {applicability.get("geometry")})


def _query_in_scope(query: str, solver: str, collection: str) -> bool:
    versions = {v.upper() for v in re.findall(r"(?<![a-z0-9])r\d{2}(?![a-z0-9])", query)}
    return (bool(query) and not any(term in query for term in EXCLUDED_TERMS)
            and (collection != "primary" or versions <= {solver}))


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip().casefold()


def _terms(text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9_]+", text))
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        words.update(run[i:i + 2] for i in range(len(run) - 1))
    return words


def _cosine(query: set[str], document: set[str], weights: dict[str, float]) -> float:
    shared = query & document
    if not shared:
        return 0.0
    query_size = sum(weights.get(term, 1.0) ** 2 for term in query)
    doc_size = sum(weights[term] ** 2 for term in document)
    return sum(weights[term] ** 2 for term in shared) / sqrt(query_size * doc_size)


class KnowledgeBase:
    def __init__(self, catalog: str | Path = DEFAULT_CATALOG, *, vector_search=None):
        self.path = Path(catalog).resolve()
        document = json.loads(self.path.read_text(encoding="utf-8"))
        self.base = (self.path.parent / document.get("path_base", ".")).resolve()
        self.snapshot = document.get("snapshot_sha256")
        self.vector_search = vector_search
        self.records = document.get("records", [])
        # Separate category files are loaded only as data, never imported.
        snapshot = hashlib.sha256()
        for index_file in document.get("index_files", []):
            data = (self.path.parent / index_file).read_bytes()
            snapshot.update(data)
            self.records.extend(json.loads(data)["records"])
        if self.snapshot and snapshot.hexdigest() != self.snapshot:
            raise ValueError("knowledge index snapshot changed; rebuild the catalog")
        self.by_id = {}
        for record in self.records:
            for field in ("id", "index", "solver", "case_families", "title", "aliases", "summary", "admitted", "source"):
                if field not in record:
                    raise ValueError(f"missing record field: {field}")
            if record["id"] in self.by_id or record["index"] not in INDEXES:
                raise ValueError("duplicate record id or invalid index")
            if not isinstance(record["admitted"], bool) or not isinstance(record["case_families"], list):
                raise ValueError("invalid admission or case families")
            self.by_id[record["id"]] = record

    def _verify_file(self, reference: dict, checked: set[tuple[str, str]]) -> Path:
        path = (self.base / reference["path"]).resolve()
        identity = (str(path), reference["sha256"])
        if identity not in checked:
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != reference["sha256"]:
                raise ValueError(f"source changed or missing: {path}")
            checked.add(identity)
        return path

    def _verify(self, record: dict, checked: set[tuple[str, str]]) -> None:
        for reference in [record["source"], *record.get("supporting_sources", [])]:
            self._verify_file(reference, checked)
        if record.get("content"):
            self._verify_file(record["content"], checked)

    @staticmethod
    def _allowed(record: dict, solver: str, case_family: str, domain: str, collection: str = "primary") -> bool:
        families = set(record["case_families"])
        return (record.get("collection", "primary") == collection
                and (record["solver"] == solver == "R12" if collection == "primary"
                     else record.get("runtime_admitted") is False)
                and bool(families) and families <= ALLOWED_CASES and record["admitted"] is True
                and (case_family == "general" or case_family in families)
                and record.get("domain", "general_modeling") == domain
                and not any(term in _normalize(record["title"] + " " + record["id"])
                            for term in EXCLUDED_TERMS))

    def search(self, query: str, *, index: str, solver: str = "R12",
               case_family: str | None = None, limit: int = 3,
               domain: str = "general_modeling", analysis: str | None = None,
               collection: str = "primary", source_release: str | None = None,
               case_id: str | None = None, support: str | None = None,
               case_applicability: dict[str, str] | None = None,
               on_unavailable=None) -> list[dict]:
        if index not in INDEXES:
            raise ValueError(f"index must be one of {INDEXES}")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ValueError("limit must be an integer between 1 and 20")
        if domain not in DOMAINS:
            raise ValueError(f"domain must be one of {DOMAINS}")
        if analysis is not None and analysis not in (*ANALYSIS_TYPES, "model_only"):
            raise ValueError(f"analysis must be one of {ANALYSIS_TYPES}")
        if collection not in COLLECTIONS:
            raise ValueError(f"collection must be one of {COLLECTIONS}")
        if source_release is not None and collection != "supplement":
            raise ValueError("source_release applies to the supplement collection")
        if collection == "supplement" and solver != "R12":
            raise ValueError("use source_release to select a supplemental source version")
        if case_family is None:
            case_family = "general" if case_id is not None else "shell_plate"
        query = _normalize(query)
        requested_support = (_requested_support(query, support) if support is not None
                             or (index == "I_case" and collection == "primary") else set())
        elements = _positive_matches(_ELEMENT_PHRASES, query) if requested_support else set()
        geometries = _positive_matches(_GEOMETRY_PHRASES, query) if requested_support else set()
        if requested_support and index != "I_case" and case_id is None:
            raise ValueError("support filtering requires a case index or case_id")
        if not _query_in_scope(query, solver, collection):
            return []
        versions = {v.upper() for v in re.findall(r"(?<![a-z0-9])r\d{2}(?![a-z0-9])", query)} if collection == "supplement" else set()
        scoped_ids = None
        if case_id is not None:
            case = self.by_id.get(case_id)
            if (case is None or case["index"] != "I_case"
                    or not self._allowed(case, solver, case_family, domain, collection)
                    or not _matches_applicability(case, requested_support, elements, geometries)
                    or (analysis is not None and case.get("analysis") != analysis)):
                return []
            scoped_ids = {case_id, *case.get("related_ids", [])}
        keywords = set(re.findall(r"\*[a-z][a-z0-9_]*", query))
        explicit_id = next((key for key in self.by_id if _normalize(key) == query), None)
        query_terms = _terms(query)
        eligible = [r for r in self.records
                    if r["index"] == index and self._allowed(r, solver, case_family, domain, collection)
                    and (index != "I_case" or _matches_applicability(r, requested_support, elements, geometries))
                    and (index != "I_case" or all(
                        r.get("applicability", {}).get(key) == value
                        for key, value in (case_applicability or {}).items()))
                    and (explicit_id is None or r["id"] == explicit_id)
                    and (scoped_ids is None or r["id"] in scoped_ids)
                    and (collection == "primary" or not versions or r["solver"] in versions)
                    and (source_release is None or source_release.casefold() in {
                        (r["solver"] or "").casefold(), r["source"].get("source_release", "").casefold()})
                    and (analysis is None or (index != "I_case" and not r.get("recipe"))
                         or r.get("analysis") == (None if analysis == "model_only" else analysis))]
        documents = [_terms(_normalize(" ".join([r["title"], *r["aliases"], r["summary"]]))) for r in eligible]
        frequency = Counter(term for document in documents for term in document)
        weights = {term: 1.0 + log((len(documents) + 1) / (count + 1)) for term, count in frequency.items()}
        # Explicit card names keep the identifier-based path. Dense candidates
        # are scored only after applying the same metadata constraints.
        dense = (self.vector_search(index, query, {r["id"] for r in eligible})
                 if self.vector_search is not None and eligible and not keywords and explicit_id is None else {})
        ranked = []
        for record, document in zip(eligible, documents):
            labels = [_normalize(record["id"]), _normalize(record["title"]), *map(_normalize, record["aliases"])]
            if case_id is not None and record.get("recipe"):
                labels.extend(map(_normalize, record["recipe"]["query_aliases"]))
            # A full keyword is an identifier: never satisfy an unknown keyword by prefix overlap.
            if keywords and not keywords.intersection(labels):
                continue
            exact = max(2 if query == label else 1 if label and label in query else 0 for label in labels)
            overlap = query_terms & document
            vector_score = dense.get(record["id"])
            if exact or vector_score is not None or (len(overlap) >= 2 and len(overlap) / len(query_terms) >= 0.35):
                similarity = _cosine(query_terms, document, weights)
                score = similarity if vector_score is None else 0.7 * vector_score + 0.3 * similarity
                ranked.append((exact, score, record, vector_score))
        ranked.sort(key=lambda item: (-item[0], -item[1], item[2]["id"]))
        results, checked = [], set()
        for exact, similarity, record, vector_score in ranked:
            try:
                self._verify(record, checked)
            except (OSError, ValueError):
                if on_unavailable is None:
                    raise
                on_unavailable(record["id"])
                continue
            result = deepcopy(record)
            result.update(exact_match=exact, score=round(similarity, 6), retrieval_method="exact_and_tfidf_cosine_v1",
                          reference_only=True)
            if vector_score is not None:
                result.update(semantic_score=round(vector_score, 6), retrieval_method="exact_tfidf_e5_v1")
            results.append(result)
            if len(results) == limit:
                break
        return results

    def retrieve(self, query: str, *, stage: str, solver: str = "R12", case_family: str = "general",
                 domain: str = "general_modeling", analysis: str | None = None, limit: int = 3,
                 collection: str = "primary", source_release: str | None = None,
                 case_id: str | None = None, support: str | None = None,
                 case_applicability: dict[str, str] | None = None, on_unavailable=None) -> dict:
        if stage not in STAGE_INDEX:
            raise ValueError(f"unknown stage: {stage}")
        index = STAGE_INDEX[stage]
        candidates = self.search(query, index=index, solver=solver, case_family=case_family,
                                 domain=domain, analysis=analysis, limit=limit, collection=collection,
                                 source_release=source_release, case_id=case_id, support=support,
                                 case_applicability=case_applicability, on_unavailable=on_unavailable)
        normalized = _normalize(query)
        requested_support = (_requested_support(normalized, support) if support is not None
                             or (index == "I_case" and collection == "primary") else set())
        selected = candidates[0] if candidates else None
        related = self.references(selected["id"]) if selected else []
        support_reference = None
        if (selected is None and index == "I_case" and requested_support and collection == "primary"
                and solver == "R12" and domain == "general_modeling" and _query_in_scope(normalized, solver, collection)
                and (case_family == "general" or case_family in ALLOWED_CASES)):
            definitions = self.search("*BOUNDARY_SPC_SET", index="I_model", case_family=case_family,
                                      limit=1, on_unavailable=on_unavailable)
            if definitions:
                support_reference = {key: definitions[0][key] for key in ("id", "title", "source", "reference_only")}
        return {"stage": stage, "index": index, "query": query, "domain": domain, "snapshot_sha256": self.snapshot,
                "solver": solver, "case_family": case_family, "analysis": analysis, "candidates": candidates,
                "collection": collection, "source_release": source_release, "case_id": case_id,
                "requested_support": sorted(requested_support),
                "requested_elements": sorted(_positive_matches(_ELEMENT_PHRASES, normalized)) if requested_support else [],
                "support_reference": support_reference,
                "status": "matched" if selected else "no_applicable_reference",
                "selected": selected, "related": related}

    def references(self, record_id: str) -> list[dict]:
        record = self.by_id[record_id]
        domain = record.get("domain", "general_modeling")
        if not self._allowed(record, "R12", "general", domain, record.get("collection", "primary")):
            raise ValueError("record is not admitted")
        related = []
        for key in record.get("related_ids", []):
            item = self.by_id[key]
            if not self._allowed(item, "R12", "general", domain) or not set(item["case_families"]).intersection(record["case_families"]):
                raise ValueError(f"incompatible related record: {key}")
            related.append({"id": key, "index": item["index"], "title": item["title"]})
        return related

    def checked_reference(self, record_id: str, *, index: str, collection: str,
                          case_family: str, checked: set[tuple[str, str]]) -> dict:
        """Read one stage-selected record and verify its source once per batch."""
        record = self.by_id[record_id]
        if record["index"] != index or not self._allowed(
            record, "R12", case_family, "general_modeling", collection
        ):
            raise ValueError("record is outside the requested knowledge scope")
        self._verify(record, checked)
        return record

    def _deck_text(self, record: dict, checked: set[tuple[str, str]]) -> str:
        source = record["source"]
        deck = record["deck"]
        path = self._verify_file(source, checked)
        if deck.get("standalone"):
            raw = path.read_bytes()
        else:
            with ZipFile(path) as archive:
                raw = archive.read(deck["member"])
        if hashlib.sha256(raw).hexdigest() != deck["sha256"]:
            raise ValueError(f"archive member changed: {deck['member']}")
        return raw.decode(deck["encoding"])

    def _deck(self, record: dict, checked: set[tuple[str, str]], keyword: str | None) -> dict:
        original = self._deck_text(record, checked)
        deck = record["deck"]
        if keyword is None:
            return {"member": deck["member"], "text": original}
        lines = original.splitlines(keepends=True)
        blocks = [{**block, "text": "".join(lines[block["start_line"] - 1:block["end_line"]])}
                  for block in deck["blocks"] if block["keyword"] == keyword.upper()]
        if not blocks:
            raise ValueError(f"keyword not found in case: {keyword}")
        return {"member": deck["member"], "blocks": blocks}

    def _recipe(self, record: dict, checked: set[tuple[str, str]]) -> dict:
        recipe = record["recipe"]
        case = self.by_id[recipe["case_id"]]
        related = self.references(record["id"])
        if not case.get("deck") or case["id"] not in {item["id"] for item in related}:
            raise ValueError("invalid recipe parent case")
        lines = self._deck_text(case, checked).splitlines(keepends=True)
        blocks = []
        for block in recipe["source_blocks"]:
            start, end = block["start_line"], block["end_line"]
            if not any(b["keyword"] == block["keyword"] and b["start_line"] <= start <= end <= b["end_line"]
                       for b in case["deck"]["blocks"]):
                raise ValueError(f"recipe source block is outside its case: {block}")
            blocks.append({**block, "text": "".join(lines[start - 1:end])})
        return {**deepcopy(recipe), "member": case["deck"]["member"], "blocks": blocks,
                "related": related, "r12_execution": case["r12_execution"]}

    def _manual(self, record: dict, page: int | None) -> dict:
        selection = record["manual"]
        pages = [p for p in selection["pages"] if page is None or p["pdf_page"] == page]
        if not pages:
            raise ValueError("page is outside this record")
        path = (self.base / selection["page_database"]).resolve()
        if not path.is_file():
            raise ValueError(f"source page database missing: {path}")
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
            result = []
            for entry in pages:
                number = entry["pdf_page"]
                row = db.execute("SELECT text FROM source_pages WHERE source_id = ? AND pdf_page = ?",
                                 (selection["source_id"], number)).fetchone()
                if row is None or hashlib.sha256(row[0].encode("utf-8")).hexdigest() != entry["sha256"]:
                    raise ValueError(f"source page changed or missing: {selection['source_id']} PDF {number}")
                result.append({"pdf_page": number, "text": row[0]})
        return {"pages": result}

    def context(self, record_id: str, *, page: int | None = None, keyword: str | None = None) -> dict:
        """Fetch original material by stable record ID, PDF page or deck keyword."""
        record = self.by_id[record_id]
        collection = record.get("collection", "primary")
        if not self._allowed(record, "R12", "general", record.get("domain", "general_modeling"), collection):
            raise ValueError("record is not admitted")
        checked: set[tuple[str, str]] = set()
        self._verify(record, checked)
        if record.get("deck") and page is None:
            payload = self._deck(record, checked, keyword)
        elif record.get("recipe") and page is None and keyword is None:
            payload = self._recipe(record, checked)
        elif record.get("manual") and keyword is None:
            payload = self._manual(record, page)
        elif record.get("text_excerpt") and page is None and keyword is None:
            payload = {**self._text_excerpt(record),
                       **{key: deepcopy(record[key]) for key in ("steps", "checks") if key in record}}
        elif record.get("content") and keyword is None:
            path = self._verify_file(record["content"], checked)
            payload = json.loads(path.read_text(encoding="utf-8"))
            if page is not None:
                pages = [p for p in payload.get("pages", []) if p["pdf_page"] == page]
                if not pages:
                    raise ValueError("page is outside this record")
                payload = {**payload, "pages": pages}
        elif page is None and keyword is None:
            payload = deepcopy(record)
        else:
            raise ValueError("requested selector does not apply to this record")
        return {"record_id": record_id, "reference_only": True, "collection": collection,
                "summary": record["summary"],
                "source": deepcopy(record["source"]), "payload": payload}

    def _text_excerpt(self, record: dict) -> dict:
        excerpt = record["text_excerpt"]
        source = (self.base / record["source"]["path"]).resolve()
        lines = source.read_bytes().decode(excerpt["encoding"]).splitlines(keepends=True)
        start, end = excerpt["start_line"], excerpt["end_line"]
        if not 1 <= start <= end <= len(lines):
            raise ValueError("text excerpt is outside the source")
        return {"start_line": start, "end_line": end, "text": "".join(lines[start - 1:end])}

    def verify_all(self) -> dict:
        checked: set[tuple[str, str]] = set()
        counts = dict.fromkeys(INDEXES, 0)
        collections = {name: dict.fromkeys(INDEXES, 0) for name in COLLECTIONS}
        for record in self.records:
            self._verify(record, checked)
            if record.get("deck"):
                self._deck(record, checked, None)
            if record.get("recipe"):
                self._recipe(record, checked)
            if record.get("manual"):
                self._manual(record, None)
            if record.get("text_excerpt"):
                self._text_excerpt(record)
            if record["admitted"] and record.get("related_ids"):
                self.references(record["id"])
            counts[record["index"]] += 1
            collections[record.get("collection", "primary")][record["index"]] += 1
        return {"records": len(self.records), "files_verified": len(checked), "indexes": counts,
                "collections": collections, "snapshot_sha256": self.snapshot}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--semantic", action="store_true", help="Use local FAISS and E5 for natural-language queries")
    commands = parser.add_subparsers(dest="command", required=True)
    search = commands.add_parser("search")
    search.add_argument("query")
    route = search.add_mutually_exclusive_group(required=True)
    route.add_argument("--index", choices=INDEXES)
    route.add_argument("--stage", choices=STAGE_INDEX)
    search.add_argument("--solver", default="R12")
    search.add_argument("--case-family", default="general")
    search.add_argument("--case-id", help="Limit to an existing case and its linked records")
    search.add_argument("--domain", choices=DOMAINS, default="general_modeling")
    search.add_argument("--collection", choices=COLLECTIONS, default="primary")
    search.add_argument("--source-release", help="Filter supplemental documents by original release, such as R11 or R13")
    search.add_argument("--analysis", choices=ANALYSIS_TYPES)
    search.add_argument("--support", choices=SUPPORT_TYPES)
    search.add_argument("--limit", type=int, default=3)
    context = commands.add_parser("context")
    context.add_argument("record_id")
    selector = context.add_mutually_exclusive_group()
    selector.add_argument("--page", type=int)
    selector.add_argument("--keyword")
    commands.add_parser("verify")
    commands.add_parser("build-vectors")
    workflow = commands.add_parser("workflow", help="Retrieve evidence for the six stages of one case")
    workflow.add_argument("query")
    workflow.add_argument("--solver", default="R12")
    workflow.add_argument("--case-family", default="general")
    workflow.add_argument("--domain", choices=DOMAINS, default="general_modeling")
    workflow.add_argument("--analysis", choices=ANALYSIS_TYPES)
    workflow.add_argument("--support", choices=SUPPORT_TYPES)
    args = parser.parse_args(argv)
    try:
        kb = KnowledgeBase(args.catalog)
        if args.semantic or args.command == "build-vectors":
            from .knowledge_vectors import VectorStore

            vectors = VectorStore(kb)
            if args.semantic and args.command != "build-vectors":
                kb.vector_search = vectors.search
        if args.command == "search":
            filters = {"solver": args.solver, "case_family": args.case_family, "limit": args.limit,
                       "domain": args.domain, "analysis": args.analysis, "collection": args.collection,
                       "source_release": args.source_release, "case_id": args.case_id, "support": args.support}
            result = (kb.retrieve(args.query, stage=args.stage, **filters) if args.stage else
                      kb.search(args.query, index=args.index, **filters))
        elif args.command == "context":
            result = kb.context(args.record_id, page=args.page, keyword=args.keyword)
        elif args.command == "build-vectors":
            result = vectors.build()
        elif args.command == "workflow":
            from .knowledge_workflow import collect_evidence

            result = collect_evidence(kb, args.query, solver=args.solver, case_family=args.case_family,
                                      domain=args.domain, analysis=args.analysis, support=args.support)
        else:
            result = kb.verify_all()
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, ImportError, RuntimeError) as exc:
        print(f"knowledge error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
