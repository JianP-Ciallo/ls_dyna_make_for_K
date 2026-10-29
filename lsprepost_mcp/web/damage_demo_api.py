"""Closed synthetic-only facade; never imports project stores or solver tools."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import threading

from lsprepost_mcp.damage_demo_scene import WARNING, scene_payload, validate_demo_input
from lsprepost_mcp.web.http_utils import ApiError

_RUN_LOCK = threading.Lock()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _evaluate(inputs):
    try:
        from blast_damage_assessment.api import assess
        from lsprepost_mcp.damage_demo_adapter import SyntheticDemoAdapter
    except ImportError as exc:
        raise ApiError(503, "assessment_unavailable", "评估依赖未安装，请运行 setup_damage_assessment.ps1 并重启服务。") from exc
    scene = scene_payload()
    components = [{"id": c["component_id"], "role": c["role"], "part_ids": [c["part_id"]],
                   "material_ids": [1], "importance_class": "nonstructural" if c["role"] == "wall" else "primary",
                   "primary_load_path": c["role"] != "wall", "zone_id": f"floor-{c['floor']}"}
                  for c in scene["components"] if c["role"] != "ground"]
    semantics = {
        "schema_version": "blast_damage.model_semantics@1", "unit_system": "SI_m_s_kg_N_Pa",
        "axes": {"vertical": "z", "horizontal": ["x", "y"]},
        "blast_center_m": inputs["sources"][0]["position_m"],
        "engineering_validated": False, "requires_project_review": True,
        "building": {"zones": [{"id": f"floor-{i}"} for i in (1, 2, 3)], "components": components},
        "materials": [{"material_id": 1, "model": "elastic", "engineering_validated": False}],
    }
    # Keep a valid request, but make ground identity unverifiable in partial mode.
    semantics["ground"] = {"part_ids": [99999] if inputs["mode"] == "partial" else [8001, 8002, 8003, 8004],
                           "material_ids": [1], "surface": {"axis": "z", "direction": "max"}}
    # Owned, ephemeral synthetic fixture only: no usable solver deck/database or completed run record.
    with tempfile.TemporaryDirectory(prefix="synthetic-damage-demo-") as directory:
        root = Path(directory)
        source = root / "synthetic-source"
        source.mkdir()
        manifest = source / "assessment_semantics.json"
        manifest.write_text(_json(semantics), encoding="utf-8")
        for name, content in {
            "model.k": "SYNTHETIC DEMO ONLY: presentation geometry, not a solver deck.",
            "model.json": _json({"synthetic_demo": True, "warning": WARNING, "input": inputs, "components": scene["components"]}),
            "run.json": _json({"status": "synthetic_demo", "solver_executed": False, "warning": WARNING}),
            "d3hsp": "SYNTHETIC DEMO ONLY: no solver log or physical termination.",
            "d3plot": "SYNTHETIC DEMO ONLY: arrays provided by synthetic_demo adapter; not a d3plot database.",
        }.items():
            (source / name).write_text(content, encoding="utf-8")
        output = root / "synthetic-output"
        result = assess({
            "schema_version": "blast_damage.assessment_request@1",
            "project_id": "synthetic-demo-only", "case_id": "synthetic-demo-three-storey",
            "result_dir": str(source), "semantic_manifest": {
                "path": str(manifest), "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "schema_version": "blast_damage.model_semantics@1"},
            "building_rule_pack": "building_research_reference@1",
            "ground_rule_pack": "ground_research_reference@1", "output_dir": str(output), "state_chunk_size": 3,
        }, adapter=SyntheticDemoAdapter(scene, inputs))
        artifacts = {}
        for name, reference in result.artifacts.items():
            data = (output / name).read_bytes()
            artifacts[name] = {"text": data.decode("utf-8"), "sha256": hashlib.sha256(data).hexdigest(),
                               "media_type": reference.media_type}
        snapshot = json.loads(artifacts["assessment_snapshot.json"]["text"])
    return {"schema_version": "lsprepost_mcp.synthetic_damage_result@1", "synthetic_demo": True,
            "warning": WARNING, "input": inputs, "snapshot": snapshot, "artifacts": artifacts}


def evaluate_demo(payload):
    inputs = validate_demo_input(payload)
    if not _RUN_LOCK.acquire(blocking=False):
        raise ApiError(429, "demo_busy", "另一个演示正在评估，请稍后重试。")
    try:
        return _evaluate(inputs)
    finally:
        _RUN_LOCK.release()
