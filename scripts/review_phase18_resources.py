from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lsprepost_mcp.materials import load_materials, validate_material_resource
from lsprepost_mcp.phase18_reference_naming import MATERIAL_RESOURCE_ALIASES, STRUCTURAL_RESOURCE_ALIASES
from lsprepost_mcp.phase18_resource_review import (
    REVIEW_METHOD,
    REVIEW_SCHEMA_VERSION,
    REVIEWED_STATUS,
    SOURCE_2K_SHA256,
    canonical_resource_sha256,
    validate_phase18_review_manifest,
)
from lsprepost_mcp.structural_resources import (
    load_structural_resources,
    validate_structural_catalog_closure,
)


MATERIAL_IDS = set(MATERIAL_RESOURCE_ALIASES.values())
STRUCTURAL_IDS = set(STRUCTURAL_RESOURCE_ALIASES.values())
EVIDENCE = [
    "source_identity",
    "source_spans",
    "si_conversion",
    "typed_fields",
    "dependency_closure",
]


def _formal_resources() -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    available_materials = load_materials()
    available_structural = load_structural_resources()
    missing_materials = sorted(MATERIAL_IDS - set(available_materials))
    missing_structural = sorted(STRUCTURAL_IDS - set(available_structural))
    if missing_materials or missing_structural:
        raise ValueError(
            f"formal Phase 18 resources are incomplete: materials={missing_materials}, structural={missing_structural}"
        )
    materials = {resource_id: available_materials[resource_id] for resource_id in sorted(MATERIAL_IDS)}
    structural = {resource_id: available_structural[resource_id] for resource_id in sorted(STRUCTURAL_IDS)}
    for resource in materials.values():
        validate_material_resource(resource)
    validate_structural_catalog_closure(list(structural.values()), materials)
    return materials, structural


def candidate_manifest() -> dict[str, object]:
    materials, structural = _formal_resources()
    records = []
    for resource_kind, resources in (("material", materials), ("structural", structural)):
        for resource_id, resource in resources.items():
            records.append({
                "id": resource_id,
                "resource_kind": resource_kind,
                "canonical_sha256": canonical_resource_sha256(resource),
                "validation_status": REVIEWED_STATUS,
                "reviewed_on": "2026-08-05",
                "review_method": REVIEW_METHOD,
                "evidence": EVIDENCE,
            })
    records.sort(key=lambda row: str(row["id"]))
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "source_sha256": SOURCE_2K_SHA256,
        "resources": records,
    }


def verify_manifest(path: Path) -> dict[str, object]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    materials, structural = _formal_resources()
    resources = {**materials, **structural}
    report = validate_phase18_review_manifest(manifest, resources)
    return {
        **report,
        "material_count": len(materials),
        "structural_count": len(structural),
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or verify Phase 18 hash-bound review evidence.")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--candidate-output", type=Path)
    modes.add_argument("--verify", type=Path)
    args = parser.parse_args()

    if args.candidate_output is not None:
        manifest = candidate_manifest()
        _write_json(args.candidate_output, manifest)
        print(json.dumps({"candidate": str(args.candidate_output), "resource_count": 11}, ensure_ascii=False))
        return 0

    report = verify_manifest(args.verify)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
