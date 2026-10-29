from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lsprepost_mcp.damage_assessment_semantics import build_assessment_semantics
from lsprepost_mcp.refined_blast.store import RefinedBlastStore
from lsprepost_mcp.refined_building.solver_blast import build_physical_building
from lsprepost_mcp.web import refined_blast_api as api_module
from test_phase18_solver_blast_buildings import (
    COMMERCIAL,
    RESIDENTIAL,
    SUBWAY,
    _package,
)
from test_phase18e_assembler import _artifact, _project


def _semantic_inputs() -> tuple[SimpleNamespace, SimpleNamespace]:
    artifact = SimpleNamespace(fingerprint="b" * 64)
    detailed = SimpleNamespace(
        package_fingerprint="a" * 64,
        artifacts=(artifact,),
    )
    members = (
        SimpleNamespace(role="commercial_rc_column", material_role="concrete"),
        SimpleNamespace(
            role="commercial_column_longitudinal_rebar",
            material_role="reinforcing_steel",
        ),
        SimpleNamespace(role="hybrid_foundation", material_role="concrete"),
        SimpleNamespace(role="steel_beam", material_role="structural_steel"),
        SimpleNamespace(
            role="nonstructural_partition", material_role="nonstructural"
        ),
    )
    building = SimpleNamespace(
        members=members,
        load_path=SimpleNamespace(
            foundation_roles=("hybrid_foundation",),
            vertical_roles=("commercial_rc_column",),
            floor_or_roof_roles=("steel_beam",),
        ),
        fingerprint="c" * 64,
    )
    evidence = SimpleNamespace(
        part_ids=(
            ("commercial_column_longitudinal_rebar", 1001),
            ("commercial_rc_column", 1002),
            ("hybrid_foundation", 1003),
            ("nonstructural_partition", 1004),
            ("steel_beam", 1005),
            ("diagnostic_soil_ground", 8001),
            ("visible_mm_ale_air_domain", 8002),
            ("tnt_high_explosive", 8003),
            ("ale_coupling_buffer", 8004),
        ),
        scene_fingerprint="d" * 64,
        building_mesh_fingerprint="e" * 64,
    )
    compilation = SimpleNamespace(
        building=building,
        evidence=evidence,
        validation=SimpleNamespace(charge_position_m=(-2.0, 1.5, 4.0)),
    )
    return detailed, compilation


def test_builds_native_semantics_with_explicit_part_role_bindings_and_provenance() -> None:
    detailed, compilation = _semantic_inputs()

    result = build_assessment_semantics(detailed, compilation)

    assert set(result) == {
        "schema_version",
        "unit_system",
        "axes",
        "blast_center_m",
        "engineering_validated",
        "requires_project_review",
        "building",
        "ground",
        "materials",
        "classification",
    }
    assert result["schema_version"] == "blast_damage.model_semantics@1"
    assert result["axes"] == {"vertical": "z", "horizontal": ["x", "y"]}
    assert result["blast_center_m"] == [-2.0, 1.5, 4.0]
    assert result["engineering_validated"] is False
    assert result["requires_project_review"] is True
    components = {row["id"]: row for row in result["building"]["components"]}
    assert components["commercial_columns"]["part_ids"] == [1001, 1002]
    assert components["commercial_columns"]["material_ids"] == [3, 4]
    assert components["commercial_columns"]["importance_class"] == "primary"
    assert components["partitions"]["importance_class"] == "nonstructural"
    assert components["partitions"]["primary_load_path"] is False
    assert result["ground"] == {
        "part_ids": [8001],
        "material_ids": [7],
        "surface": {"axis": "z", "direction": "max"},
    }
    assert {row["material_id"] for row in result["materials"]} == {3, 4, 6, 7}
    classification = result["classification"]
    assert classification["source"] == "inferred_generator_mapping@1"
    assert classification["generator_fingerprints"] == {
        "building_artifact": "b" * 64,
        "detailed_building_package": "a" * 64,
        "physical_building": "c" * 64,
        "solver_building_mesh": "e" * 64,
        "solver_scene": "d" * 64,
    }
    bindings = {row["part_role"]: row for row in classification["part_role_bindings"]}
    assert bindings["commercial_rc_column"] == {
        "part_role": "commercial_rc_column",
        "part_id": 1002,
        "component_id": "commercial_columns",
        "material_id": 3,
    }


def test_unknown_generated_building_role_fails_closed() -> None:
    detailed, compilation = _semantic_inputs()
    compilation.evidence.part_ids = (
        ("unknown_primary_member", 1999),
        ("diagnostic_soil_ground", 8001),
    )
    compilation.building.members = (
        SimpleNamespace(role="unknown_primary_member", material_role="concrete"),
    )

    with pytest.raises(ValueError, match="classification"):
        build_assessment_semantics(detailed, compilation)


@pytest.mark.parametrize("resource_id", [COMMERCIAL, RESIDENTIAL, SUBWAY])
def test_classification_table_covers_every_physical_role(resource_id: str) -> None:
    detailed = _package(resource_id)
    building = build_physical_building(detailed)
    part_rows = tuple(
        (member.role, 1001 + index)
        for index, member in enumerate(sorted(building.members, key=lambda row: row.role))
    ) + (
        ("diagnostic_soil_ground", 8001),
        ("visible_mm_ale_air_domain", 8002),
        ("tnt_high_explosive", 8003),
        ("ale_coupling_buffer", 8004),
    )
    compilation = SimpleNamespace(
        building=building,
        evidence=SimpleNamespace(
            part_ids=part_rows,
            scene_fingerprint="d" * 64,
            building_mesh_fingerprint="e" * 64,
        ),
        validation=SimpleNamespace(charge_position_m=(-2.0, 1.5, 4.0)),
    )

    semantics = build_assessment_semantics(detailed, compilation)

    classified = {
        row["part_role"]
        for row in semantics["classification"]["part_role_bindings"]
    }
    assert classified == {member.role for member in building.members}


@pytest.mark.parametrize(
    "changed_name", ["model.k", "manifest.json", "assessment_semantics.json"]
)
def test_action_snapshot_rehashes_every_assessment_input_before_launch(
    tmp_path: Path, changed_name: str
) -> None:
    store = RefinedBlastStore(tmp_path)
    store.create(_project(_artifact()))
    files = {
        "model.k": b"*KEYWORD\n*END\n",
        "manifest.json": b"{}",
        "assessment_semantics.json": b"{}",
    }
    snapshot = store.materialize_action_snapshot(
        "project-1", f"action-launch-lsdyna-2-{changed_name.split('.')[0]}", files
    )
    digests = {
        name: hashlib.sha256(content).hexdigest() for name, content in files.items()
    }
    (snapshot / changed_name).write_bytes(b"changed")

    with pytest.raises(ValueError, match="fingerprint changed"):
        store.verify_action_snapshot("project-1", snapshot, digests)


def test_solver_complete_web_package_retains_both_manifests_and_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    detailed, compilation = _semantic_inputs()
    detailed.artifacts = (SimpleNamespace(fingerprint="b" * 64),)

    def compile_deck(_detailed, _provider_input, output_dir: Path):
        model = b"*KEYWORD\n*END\n"
        manifest = b'{"schema_version":"phase18.solver_blast.deck_manifest@4"}'
        (output_dir / "model.k").write_bytes(model)
        (output_dir / "manifest.json").write_bytes(manifest)
        compilation.evidence.model_sha256 = hashlib.sha256(model).hexdigest()
        compilation.validation = SimpleNamespace(
            node_count=10,
            element_count=5,
            ale_node_count=4,
            ale_element_count=2,
            fsi_segment_count=1,
            charge_position_m=(-2.0, 1.5, 4.0),
            termination_time_s=5.0e-5,
            ok=True,
        )
        return compilation

    semantics = build_assessment_semantics(*_semantic_inputs())
    monkeypatch.setattr(api_module, "compile_solver_blast_deck", compile_deck)
    monkeypatch.setattr(api_module, "build_assessment_semantics", lambda *_: semantics)
    scenario = SimpleNamespace(
        scenario_id="scenario-1",
        scenario_kind="external",
        load_provider={"provider_input": {"schema_version": "phase18.solver_blast.config@4"}},
    )

    package = api_module._compile_solver_complete_web_package(detailed, scenario)

    assert set(package.files) == {"model.k", "manifest.json", "assessment_semantics.json"}
    assert package.manifest["model_sha256"] == hashlib.sha256(package.files["model.k"]).hexdigest()
    assert package.manifest["manifest_sha256"] == hashlib.sha256(package.files["manifest.json"]).hexdigest()
    assert package.manifest["assessment_semantics_sha256"] == hashlib.sha256(
        package.files["assessment_semantics.json"]
    ).hexdigest()
    assert json.loads(package.files["assessment_semantics.json"])["classification"]["source"] == "inferred_generator_mapping@1"
