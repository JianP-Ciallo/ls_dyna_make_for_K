"""Package a verified residential reference as read-only browser assets. No solver/API calls."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from lsprepost_mcp.web.preview_mesh import build_preview_mesh_from_keyword


def build_demo(reference: Path, assessment: Path, output: Path) -> dict:
    snapshot = json.loads((assessment / "assessment_snapshot.json").read_text(encoding="utf-8"))
    keyword = (reference / "model.k").read_bytes()
    model_sha = hashlib.sha256(keyword).hexdigest()
    source = next(row for row in snapshot["sources"] if row["relative_path"] == "model.k")
    if source["sha256"] != model_sha or snapshot["identity"]["case_id"] != "residential":
        raise ValueError("Demo model and assessment must be the same residential case")
    manifest_bytes = (reference / "manifest.json").read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != snapshot["identity"]["semantic_manifest_sha256"]:
        raise ValueError("Demo semantic manifest does not match the assessment")
    manifest = json.loads(manifest_bytes)
    report = (assessment / "damage_report.html").read_bytes()
    if snapshot["assessment_id"] not in report.decode("utf-8"):
        raise ValueError("Demo report identity mismatch")
    # The reference deck mixes comma-separated building cells and 8-column soil cells.
    # Normalize only this export input, leaving the original deck and general parser untouched.
    lines = []
    section = ""
    for raw in keyword.decode("utf-8").splitlines():
        if raw.startswith("*"):
            section = raw.strip().upper()
        if section == "*ELEMENT_SOLID" and raw.strip() and not raw.startswith(("*", "$")) and "," not in raw and len(raw.split()) < 10:
            fields = [raw[i:i + 8].strip() for i in range(0, len(raw), 8)]
            if len(fields) != 10 or not all(field.isdigit() for field in fields):
                raise ValueError("Unsupported fixed-width solid record")
            raw = ",".join(fields)
        lines.append(raw)
    mesh = build_preview_mesh_from_keyword("\n".join(lines), {
        "ale_domain": {"part_id": 9001},
        "components": [{"part_id": pid, "id": name} for name, pid in manifest["part_ids"]],
    }, project_name="residential-reference-demo")
    # Preserve original shell/exterior solid geometry; omit the occluding air proxy.
    mesh["parts"] = [part for part in mesh["parts"] if part["part_id"] != 9001]
    if not {8001, 1011}.issubset({part["part_id"] for part in mesh["parts"]}):
        raise ValueError("Demo must contain both the ground and building geometry")
    points = [point for part in mesh["parts"] for point in part["nodes"]]
    mesh["bounds"] = {"min": [min(p[i] for p in points) for i in range(3)],
                      "max": [max(p[i] for p in points) for i in range(3)]}
    mesh["face_count"] = sum(len(part["faces"]) for part in mesh["parts"])
    mesh["blast_sources"] = []
    bundle = {
        "schema_version": "lsprepost_mcp.damage_assessment_demo@1",
        "case_id": "residential", "title": "住宅建筑与地面 · 参考案例",
        "model_representation": "original_shell_and_solid_boundary",
        "model_sha256": model_sha, "report_sha256": hashlib.sha256(report).hexdigest(),
        "geometry_limitations": ["原始模型，非爆炸后变形图", "仅展示壳与实体外表面；不展示钢筋梁单元和空气域", "颜色仅区分构件，不代表损伤等级"],
        "snapshot": snapshot, "mesh": mesh,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "residential-assessment.json").write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (output / "residential-damage-report.html").write_bytes(report)
    return {"model_sha256": model_sha, "assessment_id": snapshot["assessment_id"],
            "display_parts": len(mesh["parts"]), "display_faces": mesh["face_count"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--assessment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_demo(args.reference, args.assessment, args.output)))
