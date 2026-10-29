"""Pinned nonmesh definitions for 5-1788-2; no original mesh is registered."""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path

from .config import DEFAULT_UNIT_SYSTEM, ROOT

SOURCE_SHA256 = "ad8b3fa71216379a66714ea2d9fdaf4db2d241bbadded064f00b98346e8829b8"
INDEX_SHA256 = "67c15ded3cd8ff3a828b0edcdc017c278df8ef11c2d15c4a6016b1ab246fea46"
INDEX_RELATIVE = Path("resources/reviews/source_rebuild/impact_1788/source_index.json")
MATERIAL_RELATIVE = Path("resources/materials/source_rebuild/impact_1788")
STRUCTURAL_RELATIVE = Path("resources/model_library/structural/source_rebuild/impact_1788")
RESOURCE_TYPE = "source_keyword_bundle"


def source_index() -> dict:
    text = (ROOT / INDEX_RELATIVE).read_text(encoding="utf-8")
    if hashlib.sha256(text.encode()).hexdigest() != INDEX_SHA256:
        raise ValueError("Second-source index differs from its approved fingerprint")
    return json.loads(text)


def resource_relative_path(record: Mapping) -> Path:
    directory = MATERIAL_RELATIVE if record["resource_kind"] == "materials" else STRUCTURAL_RELATIVE
    return directory / (record["id"] + ".json")


def validate_resource(record: Mapping) -> dict:
    if not isinstance(record, Mapping):
        raise ValueError("source resource must be an object")
    expected = next((r for r in source_index()["resources"] if r["id"] == record.get("id")), None)
    if expected is None:
        raise ValueError("unknown second-source resource identity")
    for key in ("id", "resource_kind", "original_ids", "dependencies"):
        if record.get(key) != expected[key]:
            raise ValueError(f"source resource {key} differs from the pinned source")
    if record.get("type") != RESOURCE_TYPE or record.get("resource_type") != RESOURCE_TYPE:
        raise ValueError("source resource type must be source_keyword_bundle")
    if record.get("unit_system") != DEFAULT_UNIT_SYSTEM:
        raise ValueError("confirmed SI source units must be preserved")
    if record.get("validation_status") != "source_reference" or record.get("requires_project_review") is not True:
        raise ValueError("source fidelity must not be promoted to engineering validation")
    provenance = record.get("provenance", {})
    if not isinstance(provenance, Mapping) or provenance.get("source_sha256") != SOURCE_SHA256:
        raise ValueError("second-source provenance mismatch")
    if provenance.get("source_unit_system") != DEFAULT_UNIT_SYSTEM:
        raise ValueError("source unit declaration mismatch")
    cards = record.get("source_cards")
    if not isinstance(cards, list) or len(cards) != len(expected["source_cards"]):
        raise ValueError("source card closure is incomplete")
    for actual, original in zip(cards, expected["source_cards"]):
        if not isinstance(actual, Mapping) or any(actual.get(k) != v for k, v in original.items()):
            raise ValueError("source card identity, span or fingerprint differs")
        text = actual.get("raw_text")
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != original["raw_sha256"]:
            raise ValueError("source card payload differs from its original fingerprint")
    return {"valid": True, "resource_id": record["id"], "resource_type": RESOURCE_TYPE,
            "material_type": RESOURCE_TYPE, "source_sha256": SOURCE_SHA256,
            "effective_validation_status": "source_reference", "requires_project_review": True,
            "validation_scope": "source identity, SI and exact raw-card fidelity only"}


def validate_bundle(records: list[dict]) -> None:
    expected = source_index()["resources"]
    if len(records) != len(expected) or {r.get("id") for r in records} != {r["id"] for r in expected}:
        raise ValueError("the complete 22-resource second-source bundle is required")
    for r in records:
        validate_resource(r)
    ids = {r["id"] for r in records}
    if any(d not in ids for r in records for d in r["dependencies"]):
        raise ValueError("resource dependencies are not closed")


def load_bundle(root: Path = ROOT) -> list[dict]:
    records = [json.loads((root / resource_relative_path(r)).read_text(encoding="utf-8"))
               for r in source_index()["resources"]]
    validate_bundle(records)
    return records


def bundle_fingerprint() -> str:
    cards = sorted((c["source_line_start"], c["raw_sha256"])
                   for r in source_index()["resources"] for c in r["source_cards"])
    return hashlib.sha256(json.dumps(cards, separators=(",", ":")).encode()).hexdigest()


def publish_resources(records: list[dict], root: Path = ROOT) -> dict:
    validate_bundle(records)
    pending, paths = [], []
    for record in records:
        path = root / resource_relative_path(record)
        paths.append(str(path))
        if path.exists():
            if json.loads(path.read_text(encoding="utf-8")) != record:
                raise FileExistsError(f"Refusing to overwrite existing resource: {path}")
        else:
            pending.append((path, record))
    for path, record in pending:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    return {"resource_count": len(records), "created": len(pending), "resource_paths": paths,
            "source_sha256": SOURCE_SHA256, "bundle_fingerprint": bundle_fingerprint(),
            "validation_status": "source_reference", "external_dependencies_missing": ["MT=41 implementation"]}


def register_source(path: Path, root: Path = ROOT) -> dict:
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("Source file differs from the approved 5-1788-2 fingerprint")
    lines = raw.decode("utf-8-sig").splitlines(keepends=True)
    records = []
    for row in source_index()["resources"]:
        cards = [{**c, "raw_text": "".join(lines[c["source_line_start"]-1:c["source_line_end"]])}
                 for c in row["source_cards"]]
        name = row["id"].removeprefix("impact_1788_ad8b3fa71216_")
        records.append({**row, "source_cards": cards, "schema_version": "source_keyword_bundle@1",
            "type": RESOURCE_TYPE, "resource_type": RESOURCE_TYPE, "name": name,
            "display_name": "5-1788-2 / " + name, "category": row["resource_kind"],
            "unit_system": DEFAULT_UNIT_SYSTEM, "version": "1.0", "validation_status": "source_reference",
            "requires_project_review": True, "source": "Source-faithful 5-1788-2 nonmesh extraction",
            "provenance": {"source_sha256": SOURCE_SHA256, "source_name": "5-1788-2.k",
                "source_unit_system": DEFAULT_UNIT_SYSTEM, "unit_confirmation": "User confirmed SI on 2026-09-26"},
            "unit_conversion": {"applied": False, "factor": 1, "reason": "Confirmed SI preserved; UMAT constants not reinterpreted"},
            "external_dependencies": ["MT=41 material implementation not provided"] if row["original_ids"].get("mt") == 41 else [],
            "notes": "Exact source fields and blanks; no solver or constitutive validation."})
    return publish_resources(records, root)
