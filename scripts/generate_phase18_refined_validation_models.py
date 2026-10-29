from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lsprepost_mcp.refined_building import compile_detailed_building_asset
from lsprepost_mcp.refined_building.solver_validation import (
    inspect_initial_solver_validation_model,
    write_initial_solver_validation_model,
)


_MODELS = (
    (
        "01_commercial_supermarket",
        "commercial_supermarket_detailed_building",
    ),
    (
        "02_residential_community",
        "residential_community_detailed_building",
    ),
    (
        "03_subway_entrance",
        "subway_entrance_detailed_building",
    ),
)


def generate_models(output_root: Path) -> dict[str, object]:
    output = output_root.resolve()
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise ValueError("output root must be a new or empty directory")
    else:
        output.mkdir(parents=True)

    summaries: list[dict[str, object]] = []
    for folder_name, resource_id in _MODELS:
        package = compile_detailed_building_asset(
            resource_id,
            mesh_profile="coarse",
            fidelity_profile="blast_response",
        )
        model_dir = output / folder_name
        source_identity = {
            "resource_id": resource_id,
            "resource_version": package.resource_version,
            "package_fingerprint": package.package_fingerprint,
            "structural_system": package.structural_system,
            "fidelity_profile": package.fidelity_profile,
            "mesh_profile": package.mesh_profile,
            "geometry": package.geometry_manifest,
            "generation_options": package.generation_options,
        }
        manifest = write_initial_solver_validation_model(
            package.artifacts,
            model_dir,
            source_identity=source_identity,
            termination_time_s=0.001,
            gravity_m_per_s2=-9.81,
        )
        inspection = inspect_initial_solver_validation_model(model_dir)
        if inspection.get("ok") is not True:
            raise ValueError(
                f"generated model {resource_id!r} failed persisted inspection: "
                f"{inspection.get('findings')}"
            )
        summaries.append(
            {
                "folder": folder_name,
                "resource_id": resource_id,
                "package_fingerprint": package.package_fingerprint,
                "counts": manifest["counts"],
                "model_k": manifest["files"]["model.k"],
                "inspection": inspection,
            }
        )
        del package
        gc.collect()

    summary: dict[str, object] = {
        "schema_version": "phase18.refined_building_1ms_generation@1",
        "configuration": {
            "geometry": "asset default real dimensions",
            "mesh_profile": "coarse",
            "fidelity_profile": "blast_response",
            "termination_time_s": 0.001,
            "gravity_m_per_s2": -9.81,
            "engineering_validated": False,
            "solver_ready": False,
            "requires_project_review": True,
        },
        "models": summaries,
    }
    _write_json_atomic(output / "generation_summary.json", summary)
    return summary


def _write_json_atomic(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the three Phase 18 refined-building 1 ms validation decks."
    )
    parser.add_argument("--output-root", required=True, type=Path)
    arguments = parser.parse_args()
    result = generate_models(arguments.output_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
