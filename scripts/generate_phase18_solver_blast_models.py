from __future__ import annotations

import argparse
import gc
import json
import math
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lsprepost_mcp.refined_building import compile_detailed_building_asset
from lsprepost_mcp.refined_building.solver_blast import (
    SHORT_SOLVE_DEFAULT_TERMINATION_TIME_S,
    compile_solver_blast_deck,
    normalize_solver_blast_config,
)


SUPPORTED_IDS = (
    "commercial_supermarket_detailed_building",
    "residential_community_detailed_building",
    "subway_entrance_detailed_building",
)

_PHYSICAL_SIZE_TARGET_MIB = (45.0, 70.0)

_MODEL_SPECS: tuple[dict[str, object], ...] = (
    {
        "folder": "01_commercial_supermarket",
        "resource_id": SUPPORTED_IDS[0],
        "legacy_geometry": {
            "length_m": 6.0,
            "width_m": 4.0,
            "height_m": 4.0,
            "wall_thickness_m": 0.2,
            "entrance_width_m": 2.0,
            "entrance_height_m": 2.2,
        },
        "generation_options": {"rebar_spacing_m": 0.5},
    },
    {
        "folder": "02_residential_community",
        "resource_id": SUPPORTED_IDS[1],
        "legacy_geometry": {
            "tower_count": 1,
            "tower_length_m": 4.0,
            "tower_width_m": 4.0,
            "tower_height_m": 6.0,
            "tower_spacing_m": 2.0,
            "wall_thickness_m": 0.2,
            "balcony_depth_m": 0.8,
        },
        "generation_options": {
            "storey_count": 2,
            "rebar_spacing_m": 0.5,
        },
    },
    {
        "folder": "03_subway_entrance",
        "resource_id": SUPPORTED_IDS[2],
        "legacy_geometry": {
            "length_m": 4.0,
            "width_m": 3.0,
            "platform_height_m": 0.3,
            "enclosure_height_m": 2.4,
            "wall_thickness_m": 0.2,
            "roof_thickness_m": 0.2,
        },
        "generation_options": {"rebar_spacing_m": 0.5},
    },
)


def _config(
    *,
    mass_kg: float,
    position_m: tuple[float, float, float],
    detonation_time_s: float,
    air_cell_size_m: float,
    near_field_cell_size_m: float,
    ground_cell_size_m: float,
    air_margins_m: tuple[float, float, float, float, float],
    coupling_buffer_layers: int,
    material_profile: str,
    termination_time_s: float,
) -> object:
    return normalize_solver_blast_config(
        {
            "schema_version": "phase18.solver_blast.config@4",
            "unit_system": "SI_m_s_kg_N_Pa",
            "tnt_equivalent_mass_kg": mass_kg,
            "charge_position_m": list(position_m),
            "detonation_time_s": detonation_time_s,
            "air_cell_size_m": air_cell_size_m,
            "near_field_cell_size_m": near_field_cell_size_m,
            "ground_cell_size_m": ground_cell_size_m,
            "air_margins_m": list(air_margins_m),
            "coupling_buffer_layers": coupling_buffer_layers,
            "material_profile": material_profile,
            "termination_time_s": termination_time_s,
        }
    )


def _config_manifest(config: object) -> dict[str, object]:
    return {
        "schema_version": config.schema_version,
        "unit_system": config.unit_system,
        "tnt_equivalent_mass_kg": config.tnt_equivalent_mass_kg,
        "charge_position_m": list(config.charge_position_m),
        "detonation_time_s": config.detonation_time_s,
        "air_cell_size_m": config.air_cell_size_m,
        "near_field_cell_size_m": config.near_field_cell_size_m,
        "ground_cell_size_m": config.ground_cell_size_m,
        "air_margins_m": list(config.air_margins_m),
        "coupling_buffer_layers": config.coupling_buffer_layers,
        "material_profile": config.material_profile,
        "termination_time_s": config.termination_time_s,
    }


def _planned_rows(config: object) -> list[dict[str, object]]:
    return [
        {
            "folder": str(spec["folder"]),
            "resource_id": str(spec["resource_id"]),
            "charge_mass_kg": config.tnt_equivalent_mass_kg,
            "charge_position_m": list(config.charge_position_m),
            "detonation_time_s": config.detonation_time_s,
            "termination_time_s": config.termination_time_s,
        }
        for spec in _MODEL_SPECS
    ]


def generate_models(output_root: Path, config: object) -> dict[str, object]:
    output = Path(output_root)
    if output.exists():
        if output.is_symlink() or not output.is_dir() or any(output.iterdir()):
            raise ValueError("output root must be empty and must not be a symlink")
        output = output.resolve()
    else:
        output.mkdir(parents=True, exist_ok=False)
        if output.is_symlink() or not output.is_dir():
            raise ValueError("output root must be a real directory")
        output = output.resolve()

    summaries: list[dict[str, object]] = []
    for spec in _MODEL_SPECS:
        resource_id = str(spec["resource_id"])
        folder = str(spec["folder"])
        model_dir = output / folder
        package = compile_detailed_building_asset(
            resource_id,
            legacy_geometry=dict(spec["legacy_geometry"]),
            mesh_profile="coarse",
            fidelity_profile="blast_response",
            generation_options=dict(spec["generation_options"]),
        )
        compilation = compile_solver_blast_deck(package, config, model_dir)
        validation = compilation.validation
        model_byte_count = (model_dir / "model.k").stat().st_size
        model_size_mib = model_byte_count / (1024.0 * 1024.0)
        model_record = {
            "schema_version": "phase18.solver_blast.model_identity@1",
            "resource_id": resource_id,
            "resource_version": package.resource_version,
            "package_fingerprint": package.package_fingerprint,
            "artifact_fingerprints": [row.fingerprint for row in package.artifacts],
            "structural_system": package.structural_system,
            "mesh_profile": package.mesh_profile,
            "fidelity_profile": package.fidelity_profile,
            "legacy_geometry": dict(spec["legacy_geometry"]),
            "generation_options": dict(spec["generation_options"]),
            "solver_config": _config_manifest(config),
            "engineering_validated": False,
            "solver_ready": False,
            "requires_project_review": True,
        }
        validation_record = {
            "schema_version": "phase18.solver_blast.static_validation@1",
            "ok": validation.ok,
            "findings": [
                {"code": row.code, "message": row.message}
                for row in validation.findings
            ],
            "model_sha256": validation.model_sha256,
            "node_count": validation.node_count,
            "element_count": validation.element_count,
            "ale_node_count": validation.ale_node_count,
            "ale_element_count": validation.ale_element_count,
            "air_element_count": validation.air_element_count,
            "tnt_element_count": validation.tnt_element_count,
            "tnt_realized_mass_kg": validation.tnt_realized_mass_kg,
            "tnt_bounds_m": list(validation.tnt_bounds_m or ()),
            "fsi_segment_count": validation.fsi_segment_count,
            "charge_position_m": list(validation.charge_position_m or ()),
            "charge_radius_m": validation.charge_radius_m,
            "detonation_time_s": validation.detonation_time_s,
            "termination_time_s": validation.termination_time_s,
            "engineering_validated": False,
            "requires_project_review": True,
        }
        _write_json_atomic(model_dir / "model.json", model_record)
        _write_json_atomic(model_dir / "validation.json", validation_record)
        summaries.append(
            {
                "folder": folder,
                "resource_id": resource_id,
                "package_fingerprint": package.package_fingerprint,
                "model_sha256": compilation.evidence.model_sha256,
                "node_count": validation.node_count,
                "element_count": validation.element_count,
                "ale_node_count": validation.ale_node_count,
                "ale_element_count": validation.ale_element_count,
                "air_element_count": validation.air_element_count,
                "tnt_element_count": validation.tnt_element_count,
                "tnt_realized_mass_kg": validation.tnt_realized_mass_kg,
                "tnt_bounds_m": list(validation.tnt_bounds_m or ()),
                "fsi_segment_count": validation.fsi_segment_count,
                "model_byte_count": model_byte_count,
                "model_size_mib": model_size_mib,
                "physical_size_target_mib": list(_PHYSICAL_SIZE_TARGET_MIB),
                "physical_size_target_met": (
                    _PHYSICAL_SIZE_TARGET_MIB[0]
                    <= model_size_mib
                    <= _PHYSICAL_SIZE_TARGET_MIB[1]
                ),
                "static_validation_ok": validation.ok,
                "charge_mass_kg": config.tnt_equivalent_mass_kg,
                "charge_position_m": list(config.charge_position_m),
                "termination_time_s": config.termination_time_s,
            }
        )
        del package, compilation
        gc.collect()

    summary: dict[str, object] = {
        "schema_version": "phase18.solver_blast.generation_summary@1",
        "output_root": str(output),
        "solver_config": _config_manifest(config),
        "models": summaries,
        "physical_size_target_mib": list(_PHYSICAL_SIZE_TARGET_MIB),
        "all_physical_size_targets_met": all(
            bool(row["physical_size_target_met"]) for row in summaries
        ),
        "all_static_validation_ok": all(
            bool(row["static_validation_ok"]) for row in summaries
        ),
        "engineering_validated": False,
        "solver_ready": False,
        "requires_project_review": True,
    }
    _write_json_atomic(output / "solver_blast_summary.json", summary)
    return summary


def _write_json_atomic(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _finite(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise argparse.ArgumentTypeError("value must be finite")
    return parsed


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Generate the three Phase 18 solver-complete ALE/FSI models.",
        allow_abbrev=False,
    )
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--mass-kg", type=_finite, default=2.0)
    parser.add_argument(
        "--charge-position",
        type=_finite,
        nargs=3,
        metavar=("X_M", "Y_M", "Z_M"),
        default=(-2.0, 1.5, 4.0),
    )
    parser.add_argument("--detonation-time-s", type=_finite, default=0.0)
    parser.add_argument("--air-cell-size-m", type=_finite, default=0.225)
    parser.add_argument("--near-field-cell-size-m", type=_finite, default=0.15)
    parser.add_argument("--ground-cell-size-m", type=_finite, default=0.25)
    parser.add_argument(
        "--air-margins",
        type=_finite,
        nargs=5,
        metavar=("XMIN_M", "XMAX_M", "YMIN_M", "YMAX_M", "TOP_M"),
        default=(3.0, 3.0, 3.0, 3.0, 3.0),
    )
    parser.add_argument("--coupling-buffer-layers", type=int, default=2)
    parser.add_argument(
        "--material-profile",
        choices=("verification_reference", "project_calibrated"),
        default="verification_reference",
    )
    parser.add_argument(
        "--termination-time-s",
        type=_finite,
        default=SHORT_SOLVE_DEFAULT_TERMINATION_TIME_S,
    )
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()
    try:
        config = _config(
            mass_kg=arguments.mass_kg,
            position_m=tuple(arguments.charge_position),
            detonation_time_s=arguments.detonation_time_s,
            air_cell_size_m=arguments.air_cell_size_m,
            near_field_cell_size_m=arguments.near_field_cell_size_m,
            ground_cell_size_m=arguments.ground_cell_size_m,
            air_margins_m=tuple(arguments.air_margins),
            coupling_buffer_layers=arguments.coupling_buffer_layers,
            material_profile=arguments.material_profile,
            termination_time_s=arguments.termination_time_s,
        )
        if arguments.dry_run:
            result: dict[str, Any] = {
                "schema_version": "phase18.solver_blast.generation_plan@1",
                "dry_run": True,
                "output_root": str(arguments.output_root.resolve()),
                "models": _planned_rows(config),
                "solver_config": _config_manifest(config),
                "physical_size_target_mib": list(_PHYSICAL_SIZE_TARGET_MIB),
                "external_program_started": False,
            }
        else:
            result = generate_models(arguments.output_root, config)
    except (OSError, TypeError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
