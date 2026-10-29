from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from lsprepost_mcp.config import ROOT
from lsprepost_mcp.dyna_keyword import build_keyword
from lsprepost_mcp.io import read_json, write_json
from lsprepost_mcp.project_store import build_model_summary, validate_project_files
from lsprepost_mcp.provenance import verify_generated_project
from lsprepost_mcp.schema import (
    cube_top_corner_load_spec,
    default_model_spec,
    parse_model_spec,
    plate_pressure_spec,
    rebar_drop_on_helmet_spec,
    rod_impact_plate_spec,
)


SNAPSHOT_BUILDERS = {
    "rebar_drop_on_helmet": rebar_drop_on_helmet_spec,
    "rod_impact_plate": rod_impact_plate_spec,
    "cube_top_corner_load": cube_top_corner_load_spec,
    "plate_pressure": plate_pressure_spec,
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refresh_keyword_snapshots() -> None:
    manifest_path = ROOT / "tests" / "snapshots" / "keyword_hashes.json"
    manifest = read_json(manifest_path)
    for entry in manifest["cases"].values():
        scene = entry.get("scene")
        if scene in SNAPSHOT_BUILDERS:
            raw_spec = SNAPSHOT_BUILDERS[scene](str(entry["project_name"]))
        else:
            raw_spec = default_model_spec(str(entry["project_name"]), str(entry["model_type"]))
        keyword, metadata = build_keyword(parse_model_spec(raw_spec))
        entry["sha256"] = hashlib.sha256(keyword.encode("utf-8")).hexdigest()
        entry["line_count"] = len(keyword.splitlines())
        entry["node_count"] = metadata.get("node_count")
        entry["element_count"] = metadata.get("element_count")
        if "part_count" in entry:
            entry["part_count"] = metadata.get("part_count")
    write_json(manifest_path, manifest)


def refresh_complete_solver_examples() -> None:
    root = ROOT / "examples" / "complete_solver_cases"
    for project in sorted(path for path in root.glob("sample_*") if path.is_dir()):
        model_path = project / "model.json"
        model = read_json(model_path)
        spec = parse_model_spec(model["spec"])
        keyword, metadata = build_keyword(spec)
        (project / "model.k").write_text(keyword, encoding="utf-8")
        model["metadata"] = metadata
        write_json(model_path, model)

        checks = validate_project_files(project)
        checks["keyword_path"] = "model.k"
        checks["spec_path"] = "model.json"
        write_json(project / "checks.json", checks)
        summary = build_model_summary(project)
        summary["paths"] = {
            "model_json": "model.json",
            "keyword": "model.k",
            "checks": "checks.json",
            "cfile": "open_model.cfile",
        }
        write_json(project / "summary.json", summary)

        preflight_path = project / "solver_preflight.json"
        preflight = read_json(preflight_path)
        keyword_hash = sha256_file(project / "model.k")
        readiness = checks.get("readiness", {})
        preflight.update(
            {
                "keyword_sha256": keyword_hash,
                "checks_ok": checks.get("ok", False),
                "ok_for_solver_draft": readiness.get("ok_for_solver_draft", False),
                "ok_for_production_review": readiness.get("ok_for_production_review", False),
                "errors": checks.get("errors", []),
                "warnings": checks.get("warnings", []),
            }
        )
        keyword_cards = preflight.get("required_cards_present", {})
        preflight["required_cards_present"] = {
            card: card in keyword for card in keyword_cards
        }
        write_json(preflight_path, preflight)

        provenance = verify_generated_project(project)
        preflight["provenance_ok"] = provenance.get("ok", False)
        preflight["provenance_classification"] = provenance.get("classification", "unknown")
        write_json(preflight_path, preflight)

        sample_manifest_path = project / "sample_manifest.json"
        sample_manifest = read_json(sample_manifest_path)
        sample_manifest["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
        sample_manifest["files"] = {
            name: sha256_file(project / name)
            for name in sample_manifest["files"]
        }
        write_json(sample_manifest_path, sample_manifest)


def main() -> None:
    refresh_keyword_snapshots()
    refresh_complete_solver_examples()
    print("Refreshed keyword snapshots and complete solver examples.")


if __name__ == "__main__":
    main()
