"""Source-pinned nonmesh resources for the reviewed GRAN_R5 reconstruction.

The material model itself is not engineering-validated. Hash checks prove source
fidelity only. No node or element records are published or consumed here.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path

from .config import DEFAULT_UNIT_SYSTEM, ROOT

SOURCE_SHA256 = "49abb80e7528981f8d1b26d902225f674263ca7f49294084a3a5a1931251dfa3"
INDEX_SHA256 = "b2ef1f182081aa0c179799d8699f808e8d583899189345316f396fb70f651ce9"
RESOURCE_TYPE = "source_keyword_bundle"
INDEX_RELATIVE = Path("resources/reviews/source_rebuild/gran_r5/source_index.json")
STRUCTURAL_RELATIVE = Path("resources/model_library/structural/source_rebuild/gran_r5")
MATERIAL_RELATIVE = Path("resources/materials/source_rebuild/gran_r5")


def source_index() -> dict:
    text = (ROOT / INDEX_RELATIVE).read_text(encoding="utf-8")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != INDEX_SHA256:
        raise ValueError("GRAN_R5 source index differs from its reviewed fingerprint")
    return json.loads(text)


def resource_relative_path(record: Mapping) -> Path:
    directory = MATERIAL_RELATIVE if record["resource_kind"] == "materials" else STRUCTURAL_RELATIVE
    return directory / (str(record["id"]) + ".json")


def validate_resource(record: Mapping) -> dict:
    if not isinstance(record, Mapping):
        raise ValueError("source resource must be an object")
    from .impact_1788_resources import SOURCE_SHA256 as SECOND_SOURCE_SHA256, validate_resource as validate_second_source
    provenance = record.get("provenance", {})
    if isinstance(provenance, Mapping) and provenance.get("source_sha256") == SECOND_SOURCE_SHA256:
        return validate_second_source(record)
    from .b120_spg_sale_resources import SOURCE_SHA256 as THIRD_SOURCE_SHA256, validate_resource as validate_third_source
    if isinstance(provenance, Mapping) and provenance.get("source_sha256") == THIRD_SOURCE_SHA256:
        return validate_third_source(record)
    expected = next((r for r in source_index()["resources"] if r["id"] == record.get("id")), None)
    if expected is None:
        raise ValueError("unknown source reconstruction resource identity")
    for key in ("id", "resource_kind", "original_ids", "dependencies"):
        if record.get(key) != expected[key]:
            raise ValueError(f"source resource {key} differs from the reviewed source")
    if record.get("type") != RESOURCE_TYPE or record.get("resource_type") != RESOURCE_TYPE:
        raise ValueError("source resource type must be source_keyword_bundle")
    if record.get("unit_system") != DEFAULT_UNIT_SYSTEM:
        raise ValueError("source resource must preserve confirmed SI units")
    if record.get("validation_status") != "source_reference" or record.get("requires_project_review") is not True:
        raise ValueError("source fidelity must not be promoted to engineering validation")
    provenance = record.get("provenance", {})
    if not isinstance(provenance, Mapping) or provenance.get("source_sha256") != SOURCE_SHA256:
        raise ValueError("resource provenance source hash mismatch")
    if provenance.get("source_unit_system") != DEFAULT_UNIT_SYSTEM:
        raise ValueError("resource provenance unit mismatch")
    cards = record.get("source_cards")
    if not isinstance(cards, list) or len(cards) != len(expected["source_cards"]):
        raise ValueError("source card closure is incomplete")
    for actual, original in zip(cards, expected["source_cards"]):
        if not isinstance(actual, Mapping) or any(actual.get(k) != v for k, v in original.items()):
            raise ValueError("source card identity, span or fingerprint differs")
        payload = actual.get("raw_text")
        if not isinstance(payload, str) or hashlib.sha256(payload.encode("utf-8")).hexdigest() != original["raw_sha256"]:
            raise ValueError("source card payload does not match the pinned original")
    return {"valid": True, "resource_id": record["id"], "resource_type": RESOURCE_TYPE,
            "material_type": RESOURCE_TYPE, "source_sha256": SOURCE_SHA256,
            "effective_validation_status": "source_reference", "requires_project_review": True,
            "validation_scope": "source identity, SI confirmation and byte fidelity; no constitutive validation"}


def validate_bundle(records: list[dict]) -> None:
    expected = source_index()["resources"]
    if len(records) != len(expected) or {r.get("id") for r in records} != {r["id"] for r in expected}:
        raise ValueError("the complete 17-resource source bundle is required")
    for record in records:
        validate_resource(record)
    identities = {r["id"] for r in records}
    if any(dep not in identities for r in records for dep in r["dependencies"]):
        raise ValueError("source resource dependencies are not closed")


def load_bundle(root: Path = ROOT) -> list[dict]:
    records = [json.loads((root / resource_relative_path(row)).read_text(encoding="utf-8"))
               for row in source_index()["resources"]]
    validate_bundle(records)
    return records


def bundle_fingerprint(records: list[dict]) -> str:
    validate_bundle(records)
    cards = sorted((c["source_line_start"], c["raw_sha256"]) for r in records for c in r["source_cards"])
    return hashlib.sha256(json.dumps(cards, separators=(",", ":")).encode()).hexdigest()


def publish_resources(records: list[dict], root: Path = ROOT) -> dict:
    """Publish only validated definitions; identical retry is safe, overwrite is not."""
    validate_bundle(records)
    pending = []
    paths = []
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
            "source_sha256": SOURCE_SHA256, "bundle_fingerprint": bundle_fingerprint(records),
            "validation_status": "source_reference", "external_dependencies_missing": ["MT=41 material implementation"]}


def register_source(path: Path, root: Path = ROOT) -> dict:
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("Source file does not match the approved GRAN_R5 SHA-256")
    lines = raw.decode("utf-8-sig").splitlines(keepends=True)
    records = []
    for row in source_index()["resources"]:
        cards = [{**card, "raw_text": "".join(lines[card["source_line_start"]-1:card["source_line_end"]])}
                 for card in row["source_cards"]]
        name = row["id"].removeprefix("gran_r5_49abb80e7528_")
        records.append({**row, "schema_version": "source_keyword_bundle@1", "source_cards": cards,
            "type": RESOURCE_TYPE, "resource_type": RESOURCE_TYPE,
            "name": name, "display_name": "GRAN_R5 / " + name, "category": row["resource_kind"],
            "unit_system": DEFAULT_UNIT_SYSTEM, "version": "1.0", "validation_status": "source_reference",
            "requires_project_review": True, "source": "Source-faithful GRAN_R5 nonmesh extraction",
            "provenance": {"source_sha256": SOURCE_SHA256, "source_name": source_index()["source_name"],
                "source_unit_system": DEFAULT_UNIT_SYSTEM, "unit_confirmation": "User confirmed SI on 2026-09-23"},
            "unit_conversion": {"applied": False, "factor": 1, "reason": "Source SI preserved; unknown UMAT constants not reinterpreted"},
            "external_dependencies": ["User material MT=41 implementation unavailable"] if name == "concrete_umat41_mid2" else [],
            "notes": "Preserves original fields and blanks. Source reference only; not an engineering or solver validation."})
    return publish_resources(records, root)
