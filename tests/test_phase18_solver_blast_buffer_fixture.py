from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from lsprepost_mcp.refined_building.solver_blast import (
    materials as solver_blast_materials,
)
from lsprepost_mcp.refined_building.solver_blast import write_solver_blast_deck
from lsprepost_mcp.refined_building.solver_blast.ale_domain import (
    iter_ale_elements,
    iter_ale_nodes,
)
from test_phase18_solver_blast_keyword import _scene


def _keyword_blocks(lines: list[str], keyword: str) -> tuple[tuple[str, ...], ...]:
    blocks = []
    for marker, line in enumerate(lines):
        if line != keyword:
            continue
        cursor = marker + 1
        rows = []
        while cursor < len(lines) and not lines[cursor].startswith("*"):
            if lines[cursor] and not lines[cursor].startswith("$"):
                rows.append(lines[cursor])
            cursor += 1
        blocks.append(tuple(rows))
    return tuple(blocks)


@pytest.fixture(scope="module")
def layered_deck(tmp_path_factory):
    output_directory = tmp_path_factory.mktemp("phase18-layered-ale-buffer")
    scene = _scene()
    evidence = write_solver_blast_deck(scene, output_directory)
    return scene, evidence.model_path


def test_ale_vacuum_material_renderer_matches_r12_fixture_contract() -> None:
    renderer = getattr(solver_blast_materials, "render_ale_vacuum_material", None)

    assert callable(renderer), "Task 3 must expose render_ale_vacuum_material"
    assert renderer(9) == (
        "*MAT_ALE_VACUUM_TITLE",
        "Visible coupling buffer vacuum",
        "9,1.225e-05",
    )


def test_active_air_tnt_and_buffer_render_as_three_distinct_ale_parts(
    layered_deck: tuple[object, Path],
) -> None:
    scene, model_path = layered_deck
    lines = model_path.read_text(encoding="utf-8").splitlines()
    solid_start = lines.index("*ELEMENT_SOLID") + 2
    solid_end = next(
        index
        for index in range(solid_start, len(lines))
        if lines[index].startswith("*")
    )
    solid_rows = [
        line
        for line in lines[solid_start:solid_end]
        if line and not line.startswith("$")
    ]
    ale_rows = [
        row
        for row in solid_rows
        if scene.air.element_id_start
        <= int(row[:8])
        < scene.air.element_id_start + scene.air.element_count
    ]
    pids = [int(row[8:16]) for row in ale_rows]

    assert len(ale_rows) == scene.air.element_count
    assert set(pids) == {9_001, 9_002, 9_003}
    assert pids.count(9_001) == scene.air.active_air_element_count
    assert pids.count(9_002) == scene.air.tnt_element_count
    assert pids.count(9_003) == scene.air.buffer_element_count

    material_marker = lines.index("*MAT_ALE_VACUUM_TITLE")
    assert tuple(lines[material_marker : material_marker + 3]) == (
        "*MAT_ALE_VACUUM_TITLE",
        "Visible coupling buffer vacuum",
        "9,1.225e-05",
    )
    buffer_part_rows = tuple(
        tuple(int(value) for value in block[1].split(","))
        for block in _keyword_blocks(lines, "*PART")
        if len(block) >= 2 and int(block[1].split(",")[0]) == 9_003
    )
    assert len(buffer_part_rows) == 1
    assert buffer_part_rows[0][2:4] == (9, 0)


def test_side_and_top_nonreflecting_sets_are_separate_and_exclude_zmin(
    layered_deck: tuple[object, Path],
) -> None:
    scene, model_path = layered_deck
    lines = model_path.read_text(encoding="utf-8").splitlines()
    nonreflecting_ids = tuple(
        int(block[0].split(",")[0])
        for block in _keyword_blocks(lines, "*BOUNDARY_NON_REFLECTING")
    )

    assert len(nonreflecting_ids) == 2
    assert len(set(nonreflecting_ids)) == 2

    segment_sets = {}
    for block in _keyword_blocks(lines, "*SET_SEGMENT_TITLE"):
        set_id = int(block[1].split(",")[0])
        if set_id not in nonreflecting_ids:
            continue
        segment_sets[set_id] = tuple(
            tuple(int(value) for value in row.split(",")[:4])
            for row in block[2:]
        )
    assert set(nonreflecting_ids) == set(segment_sets)

    node_by_id = {node.node_id: node for node in iter_ale_nodes(scene.air)}
    z_min = scene.air.z_coordinates[0]
    z_max = scene.air.z_coordinates[-1]
    top_ids = tuple(
        set_id
        for set_id, faces in segment_sets.items()
        if faces
        and all(
            all(math.isclose(node_by_id[node_id].z, z_max) for node_id in face)
            for face in faces
        )
    )

    assert len(top_ids) == 1
    top_id = top_ids[0]
    side_id = next(set_id for set_id in nonreflecting_ids if set_id != top_id)
    top_faces = segment_sets[top_id]
    side_faces = segment_sets[side_id]
    nx = len(scene.air.x_coordinates) - 1
    ny = len(scene.air.y_coordinates) - 1
    nz = len(scene.air.z_coordinates) - 1

    assert len(top_faces) == nx * ny
    assert len(side_faces) == 2 * ny * nz + 2 * nx * nz
    assert all(
        not all(math.isclose(node_by_id[node_id].z, z_min) for node_id in face)
        for face in (*side_faces, *top_faces)
    )
    side_planes = (
        ("x", scene.air.x_coordinates[0]),
        ("x", scene.air.x_coordinates[-1]),
        ("y", scene.air.y_coordinates[0]),
        ("y", scene.air.y_coordinates[-1]),
    )
    assert all(
        any(
            all(
                math.isclose(getattr(node_by_id[node_id], axis), coordinate)
                for node_id in face
            )
            for axis, coordinate in side_planes
        )
        for face in side_faces
    )


def test_bottom_boundary_uses_segment_no_flow_normal_without_ale_spc(
    layered_deck: tuple[object, Path],
) -> None:
    scene, model_path = layered_deck
    lines = model_path.read_text(encoding="utf-8").splitlines()
    essential_rows = tuple(
        tuple(int(value) for value in block[0].split(","))
        for block in _keyword_blocks(lines, "*ALE_ESSENTIAL_BOUNDARY")
    )

    assert len(essential_rows) == 1
    bottom_set_id, id_type, boundary_type, excluded_axis = essential_rows[0]
    assert (id_type, boundary_type, excluded_axis) == (2, 2, 0)

    nonreflecting_ids = {
        int(block[0].split(",")[0])
        for block in _keyword_blocks(lines, "*BOUNDARY_NON_REFLECTING")
    }
    assert bottom_set_id not in nonreflecting_ids

    spc_set_ids = {
        int(block[0].split(",")[0])
        for block in _keyword_blocks(lines, "*BOUNDARY_SPC_SET")
    }
    assert bottom_set_id not in spc_set_ids

    bottom_blocks = tuple(
        block
        for block in _keyword_blocks(lines, "*SET_SEGMENT_TITLE")
        if len(block) >= 2 and int(block[1].split(",")[0]) == bottom_set_id
    )
    assert len(bottom_blocks) == 1
    bottom_faces = tuple(
        tuple(int(value) for value in row.split(",")[:4])
        for row in bottom_blocks[0][2:]
    )

    node_by_id = {node.node_id: node for node in iter_ale_nodes(scene.air)}
    z_min = scene.air.z_coordinates[0]
    assert all(
        all(
            node_id in node_by_id
            and math.isclose(node_by_id[node_id].z, z_min)
            for node_id in face
        )
        for face in bottom_faces
    )

    expected_bottom_nodes = {
        node.node_id
        for node in node_by_id.values()
        if math.isclose(node.z, z_min)
    }
    bottom_node_ids = {
        node_id for face in bottom_faces for node_id in face
    }
    nx = len(scene.air.x_coordinates) - 1
    ny = len(scene.air.y_coordinates) - 1

    assert len(bottom_faces) == nx * ny
    assert bottom_node_ids == expected_bottom_nodes
    assert len(expected_bottom_nodes) == (nx + 1) * (ny + 1)


def test_air_probe_set_contains_only_active_air_elements(
    layered_deck: tuple[object, Path],
) -> None:
    scene, model_path = layered_deck
    lines = model_path.read_text(encoding="utf-8").splitlines()
    probe_blocks = tuple(
        block
        for block in _keyword_blocks(lines, "*SET_SOLID_LIST_TITLE")
        if block[0] == "ALE air pressure probes"
    )

    assert len(probe_blocks) == 1
    probe_ids = {
        int(value)
        for row in probe_blocks[0][2:]
        for value in row.split(",")
        if value
    }
    role_by_element = {
        element.element_id: element.part_role
        for element in iter_ale_elements(scene.air)
    }

    assert probe_ids
    assert probe_ids <= set(role_by_element)
    assert {role_by_element[element_id] for element_id in probe_ids} == {
        "ale_active_air_domain"
    }

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "validate_phase18_ale_buffer_fixture.py"
)


def _load_buffer_fixture_script() -> ModuleType:
    assert SCRIPT_PATH.is_file(), "Task 3 fixture script must exist"
    spec = importlib.util.spec_from_file_location(
        "validate_phase18_ale_buffer_fixture",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _doctor_result(path: Path, *, ok: bool = True) -> SimpleNamespace:
    payload = {
        "exe": str(path),
        "exists": True,
        "is_file": True,
        "suffix_ok": True,
        "name_ok": ok,
        "ok": ok,
    }
    return SimpleNamespace(ok=ok, to_json=lambda: payload)


def _model_sha256(project: Path) -> str:
    return hashlib.sha256((project / "model.k").read_bytes()).hexdigest()


def _successful_mcheck_record(project: Path, solver: Path) -> dict[str, object]:
    return {
        "ok": True,
        "operation": "lsdyna_initialization_smoke",
        "status": "completed",
        "smoke_id": "smoke_fixture",
        "project_name": project.name,
        "project_dir": str(project),
        "smoke_dir": str(project / "solver_smokes" / "smoke_fixture"),
        "input": str(project / "solver_smokes" / "smoke_fixture" / "model.k"),
        "input_sha256": _model_sha256(project),
        "solver": {
            "path": str(solver.resolve()),
            "sha256": hashlib.sha256(solver.read_bytes()).hexdigest(),
        },
        "command": [
            str(solver.resolve()),
            "i=model.k",
            "ncpu=1",
            "memory=64m",
            "mcheck=y",
        ],
        "resources": {"ncpu": 1, "memory": "64m", "timeout_s": 120.0},
        "started_at_utc": "2026-08-22T00:00:00+00:00",
        "finished_at_utc": "2026-08-22T00:00:01+00:00",
        "duration_s": 1.0,
        "static_validation": {"ok": True},
        "scope": "mcheck=y: initialization and bounded solver check (at most 10 cycles)",
        "returncode": 0,
        "evidence": {
            "ok": True,
            "sources": ["d3hsp"],
            "maximum_cycle": 10,
            "solver_cycles_completed": True,
            "memory_check_completed": True,
            "terminated_normally": True,
            "termination_marker": "normal",
            "keyword_errors": [],
        },
    }


def _failed_mcheck_record(project: Path, solver: Path) -> dict[str, object]:
    record = _successful_mcheck_record(project, solver)
    record.update({"ok": False, "status": "solver_failed", "returncode": 1})
    record["evidence"] = {
        "ok": False,
        "sources": ["d3hsp"],
        "maximum_cycle": 0,
        "solver_cycles_completed": False,
        "memory_check_completed": True,
        "terminated_normally": False,
        "termination_marker": "missing",
        "keyword_errors": ["*** Error 10131 bad keyword"],
    }
    return record


def _successful_solve_record(
    project: Path,
    solver: Path,
    *,
    final_time_s: float = 5.0e-5,
    matsum_text: str | None = None,
) -> dict[str, object]:
    run_dir = project / "solver_runs" / "run_fixture"
    run_dir.mkdir(parents=True)
    d3hsp = run_dir / "d3hsp"
    glstat = run_dir / "glstat"
    matsum = run_dir / "matsum"
    d3plot = run_dir / "d3plot"
    d3hsp.write_text(
        f"problem time = {final_time_s:.8e}\n"
        "*** termination time reached ***\n",
        encoding="utf-8",
    )
    glstat.write_text(
        "kinetic energy.................   0.00000E+00\n"
        "internal energy................   1.00000E+00\n"
        "hourglass energy ..............   0.00000E+00\n"
        "total energy...................   1.00000E+00\n"
        f"problem time = {final_time_s:.8e}\n",
        encoding="utf-8",
    )
    matsum.write_text(
        matsum_text
        if matsum_text is not None
        else f"time = {final_time_s:.8e}\n1 1.00000E+00 0.00000E+00\n",
        encoding="utf-8",
    )
    d3plot.write_bytes(b"fixture d3plot")
    output_rows = {
        "d3plot": d3plot,
        "d3hsp": d3hsp,
        "glstat": glstat,
        "matsum": matsum,
    }
    outputs = {
        prefix: {
            "ok": prefix in output_rows,
            "files": (
                [
                    {
                        "path": str(output_rows[prefix]),
                        "name": output_rows[prefix].name,
                        "size_bytes": output_rows[prefix].stat().st_size,
                    }
                ]
                if prefix in output_rows
                else []
            ),
            "total_size_bytes": (
                output_rows[prefix].stat().st_size if prefix in output_rows else 0
            ),
        }
        for prefix in (
            "d3plot",
            "blstfor",
            "fsifor",
            "dbfsi",
            "glstat",
            "matsum",
            "spcforc",
            "nodout",
            "elout",
            "d3hsp",
        )
    }
    return {
        "ok": True,
        "operation": "run_lsdyna",
        "status": "completed",
        "run_id": "run_fixture",
        "project_name": project.name,
        "project_dir": str(project),
        "run_dir": str(run_dir),
        "input": str(run_dir / "model.k"),
        "input_sha256": _model_sha256(project),
        "result_mode": "initial_validation",
        "result_variant": "standard",
        "solver": {
            "path": str(solver.resolve()),
            "sha256": hashlib.sha256(solver.read_bytes()).hexdigest(),
            "size_bytes": solver.stat().st_size,
            "modified_at_utc": "2026-08-22T00:00:00+00:00",
        },
        "command": [
            str(solver.resolve()),
            "i=model.k",
            "ncpu=1",
            "memory=64m",
        ],
        "resources": {"ncpu": 1, "memory": "64m", "timeout_s": 300.0},
        "started_at_utc": "2026-08-22T00:00:01+00:00",
        "finished_at_utc": "2026-08-22T00:00:02+00:00",
        "duration_s": 1.0,
        "static_validation": {"ok": True},
        "model_json_sha256": hashlib.sha256(
            (project / "model.json").read_bytes()
        ).hexdigest(),
        "returncode": 0,
        "outputs": outputs,
        "solver_evaluation": {
            "ok": True,
            "mode": "initial_validation",
            "checks": [
                {"id": "normal_termination", "ok": True, "actual": "normal"},
                {"id": "finite_energies", "ok": True, "actual": True},
                {
                    "id": "termination_time_reached",
                    "ok": final_time_s >= 5.0e-5,
                    "actual": final_time_s,
                },
            ],
            "metrics": {
                "hourglass_ratio": 0.0,
                "expected_termination_time_s": 5.0e-5,
                "final_problem_time_s": final_time_s,
            },
            "parsed": {
                "terminated_normally": True,
                "termination_marker": "normal",
                "termination_time_reached": True,
                "final_problem_time_s": final_time_s,
                "finite": True,
            },
        },
        "postprocessing": {
            "status": "requires_lsprepost_verification",
            "stress_cloud_recorded": False,
        },
    }


def _configure_fixture_module(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    solver: Path,
) -> None:
    solver_sha256 = hashlib.sha256(solver.read_bytes()).hexdigest()
    monkeypatch.setattr(module, "EXPECTED_SOLVER_SHA256", solver_sha256)
    monkeypatch.setattr(
        module,
        "doctor_named_exe",
        lambda path, prefixes, require_name: _doctor_result(Path(path)),
    )


def test_fixture_script_runs_static_audit_then_mcheck_then_short_solve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_buffer_fixture_script()
    output_root = tmp_path / "fixture"
    output_root.mkdir()
    solver = tmp_path / "lsdyna_fixture.exe"
    solver.write_bytes(b"trusted fixture solver")
    _configure_fixture_module(module, monkeypatch, solver)
    events: list[str] = []

    def fake_mcheck(project: Path, solver_path: Path, **_kwargs):
        events.append("mcheck")
        assert (project / "model.k").is_file()
        return _successful_mcheck_record(project, solver_path)

    def fake_solve(project: Path, solver_path: Path, **_kwargs):
        events.append("solve")
        return _successful_solve_record(project, solver_path)

    monkeypatch.setattr(module, "execute_lsdyna_initialization_smoke", fake_mcheck)
    monkeypatch.setattr(module, "execute_lsdyna_run", fake_solve)

    result = module.run_fixture(output_root, solver_exe=solver)

    assert events == ["mcheck", "solve"]
    assert result["all_ok"] is True
    assert result["static_audit"] == {
        "ok": True,
        "grid_cells": [4, 4, 6],
        "node_count": 175,
        "active_air_element_count": 64,
        "buffer_element_count": 32,
        "side_nonreflecting_segment_count": 96,
        "top_nonreflecting_segment_count": 16,
        "bottom_nonreflecting_segment_count": 0,
        "bottom_no_flow_segment_count": 16,
        "bottom_closed_node_count": 25,
        "vacuum_density_kg_per_m3": 1.225e-5,
        "vacuum_material_accepted": True,
    }
    assert result["mcheck"]["ok"] is True
    assert result["solve"]["normal_termination"] is True
    assert result["solve"]["termination_time_reached"] is True
    assert result["solve"]["final_problem_time_s"] == pytest.approx(5.0e-5)
    assert result["solve"]["glstat_finite"] is True
    assert result["solve"]["matsum_finite"] is True
    assert result["mcheck"]["input_sha256"] == result["model"]["sha256"]
    assert result["solve"]["input_sha256"] == result["model"]["sha256"]
    assert result["mcheck"]["solver_sha256"] == result["solver_identity"]["actual_sha256"]
    assert result["solve"]["solver_sha256"] == result["solver_identity"]["actual_sha256"]
    deck = (output_root / "model.k").read_text(encoding="utf-8")
    assert (
        "*MAT_ALE_VACUUM_TITLE\n"
        "Visible coupling buffer vacuum\n"
        "9,1.225e-05"
    ) in deck
    assert "*ALE_ESSENTIAL_BOUNDARY\n$# ssid,idtype,ictype,alecomp\n103,2,2,0" in deck
    assert "*BOUNDARY_SPC_SET" not in deck
    assert json.loads(
        (output_root / "fixture_result.json").read_text(encoding="utf-8")
    ) == result


def test_fixture_script_mcheck_failure_never_starts_solve_and_persists_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_buffer_fixture_script()
    output_root = tmp_path / "fixture"
    output_root.mkdir()
    solver = tmp_path / "lsdyna_fixture.exe"
    solver.write_bytes(b"trusted fixture solver")
    _configure_fixture_module(module, monkeypatch, solver)
    monkeypatch.setattr(
        module,
        "execute_lsdyna_initialization_smoke",
        lambda project, solver_path, **_kwargs: _failed_mcheck_record(
            project,
            solver_path,
        ),
    )

    def forbidden_solve(*_args, **_kwargs):
        raise AssertionError("solve must not start after a failed mcheck")

    monkeypatch.setattr(module, "execute_lsdyna_run", forbidden_solve)

    result = module.run_fixture(output_root, solver_exe=solver)

    assert result["all_ok"] is False
    assert result["failure"]["stage"] == "mcheck"
    assert result["mcheck"]["started"] is True
    assert result["mcheck"]["ok"] is False
    assert result["solve"]["started"] is False
    assert result["solve"]["skip_reason"] == "mcheck_failed"
    assert json.loads(
        (output_root / "fixture_result.json").read_text(encoding="utf-8")
    ) == result


def test_fixture_script_rejects_solver_hash_before_mcheck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_buffer_fixture_script()
    output_root = tmp_path / "fixture"
    output_root.mkdir()
    solver = tmp_path / "lsdyna_fixture.exe"
    solver.write_bytes(b"wrong solver binary")
    monkeypatch.setattr(
        module,
        "doctor_named_exe",
        lambda path, prefixes, require_name: _doctor_result(Path(path)),
    )

    def forbidden_mcheck(*_args, **_kwargs):
        raise AssertionError("mcheck must not start with an untrusted solver")

    monkeypatch.setattr(module, "execute_lsdyna_initialization_smoke", forbidden_mcheck)
    monkeypatch.setattr(module, "execute_lsdyna_run", forbidden_mcheck)

    result = module.run_fixture(output_root, solver_exe=solver)

    assert result["all_ok"] is False
    assert result["failure"]["stage"] == "solver_identity"
    assert result["solver_identity"]["doctor"]["ok"] is True
    assert (
        result["solver_identity"]["actual_sha256"]
        != result["solver_identity"]["expected_sha256"]
    )
    assert result["mcheck"]["started"] is False
    assert result["solve"]["started"] is False


@pytest.mark.parametrize(
    ("final_time_s", "matsum_text", "failed_field"),
    [
        (2.5e-5, None, "termination_time_reached"),
        (5.0e-5, "time = 5.00000000E-05\n1 NaN 0.0\n", "matsum_finite"),
    ],
)
def test_fixture_script_rejects_short_or_nonfinite_solve_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    final_time_s: float,
    matsum_text: str | None,
    failed_field: str,
) -> None:
    module = _load_buffer_fixture_script()
    output_root = tmp_path / failed_field
    output_root.mkdir()
    solver = tmp_path / f"lsdyna_{failed_field}.exe"
    solver.write_bytes(b"trusted fixture solver")
    _configure_fixture_module(module, monkeypatch, solver)
    monkeypatch.setattr(
        module,
        "execute_lsdyna_initialization_smoke",
        lambda project, solver_path, **_kwargs: _successful_mcheck_record(
            project,
            solver_path,
        ),
    )
    monkeypatch.setattr(
        module,
        "execute_lsdyna_run",
        lambda project, solver_path, **_kwargs: _successful_solve_record(
            project,
            solver_path,
            final_time_s=final_time_s,
            matsum_text=matsum_text,
        ),
    )

    result = module.run_fixture(output_root, solver_exe=solver)

    assert result["all_ok"] is False
    assert result["failure"]["stage"] == "solve"
    assert result["solve"][failed_field] is False


def test_fixture_script_requires_an_existing_real_empty_output_root(
    tmp_path: Path,
) -> None:
    module = _load_buffer_fixture_script()
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="existing real empty directory"):
        module.run_fixture(missing, solver_exe=tmp_path / "lsdyna.exe")

    nonempty = tmp_path / "nonempty"
    nonempty.mkdir()
    (nonempty / "keep.txt").write_text("owned", encoding="utf-8")
    with pytest.raises(ValueError, match="existing real empty directory"):
        module.run_fixture(nonempty, solver_exe=tmp_path / "lsdyna.exe")


def _audit_mutated_fixture_lines(
    module: ModuleType,
    tmp_path: Path,
    lines: list[str],
) -> dict[str, object]:
    model_path = tmp_path / "mutated_model.k"
    model_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return module.audit_fixture_deck(model_path)


@pytest.mark.parametrize(
    "replacement",
    [
        "2,1,1,0,0,0,0,0",
        "2,1,9,1,0,0,0,0",
    ],
    ids=["wrong_mid", "nonzero_eos"],
)
def test_fixture_audit_rejects_invalid_buffer_part_identity(
    tmp_path: Path,
    replacement: str,
) -> None:
    module = _load_buffer_fixture_script()
    lines = list(module.render_fixture_deck())
    buffer_title = lines.index("Fixture coupling buffer vacuum")
    part_row = buffer_title + 1

    assert lines[part_row] == "2,1,9,0,0,0,0,0"
    lines[part_row] = replacement

    assert _audit_mutated_fixture_lines(module, tmp_path, lines)["ok"] is False


@pytest.mark.parametrize(
    "replacement_rows",
    [
        ("1,1",),
        ("1,1", "2,1", "3,1"),
        ("1,1", "2,1", "2,1"),
        ("1,1", "2,2"),
    ],
    ids=["missing_buffer", "extra_part", "duplicate_buffer", "wrong_idtype"],
)
def test_fixture_audit_rejects_nonclosed_multimaterial_group(
    tmp_path: Path,
    replacement_rows: tuple[str, ...],
) -> None:
    module = _load_buffer_fixture_script()
    lines = list(module.render_fixture_deck())
    marker = lines.index("*ALE_MULTI-MATERIAL_GROUP")
    end = next(
        index
        for index in range(marker + 1, len(lines))
        if lines[index].startswith("*")
    )
    data_start = marker + 2

    assert tuple(lines[data_start:end]) == ("1,1", "2,1")
    lines[data_start:end] = replacement_rows

    assert _audit_mutated_fixture_lines(module, tmp_path, lines)["ok"] is False


def test_fixture_audit_rejects_buffer_cells_outside_bottom_two_layers(
    tmp_path: Path,
) -> None:
    module = _load_buffer_fixture_script()
    lines = list(module.render_fixture_deck())
    marker = lines.index("*ELEMENT_SOLID")
    end = next(
        index
        for index in range(marker + 1, len(lines))
        if lines[index].startswith("*")
    )
    element_rows = [
        index
        for index in range(marker + 1, end)
        if lines[index] and not lines[index].startswith("$")
    ]

    assert len(element_rows) == 96
    bottom_values = lines[element_rows[0]].split(",")
    upper_values = lines[element_rows[32]].split(",")
    assert (bottom_values[1], upper_values[1]) == ("2", "1")
    bottom_values[1], upper_values[1] = upper_values[1], bottom_values[1]
    lines[element_rows[0]] = ",".join(bottom_values)
    lines[element_rows[32]] = ",".join(upper_values)
    assert sum(lines[index].split(",")[1] == "2" for index in element_rows) == 32

    assert _audit_mutated_fixture_lines(module, tmp_path, lines)["ok"] is False


@pytest.mark.parametrize(
    "boundary_title",
    [
        "Fixture lateral non-reflecting boundary",
        "Fixture top non-reflecting boundary",
        "Fixture bottom no-flow-normal boundary",
    ],
    ids=["side", "top", "bottom"],
)
def test_fixture_audit_rejects_inward_boundary_face_winding(
    tmp_path: Path,
    boundary_title: str,
) -> None:
    module = _load_buffer_fixture_script()
    lines = list(module.render_fixture_deck())
    title = lines.index(boundary_title)
    first_face = title + 2
    node_ids = lines[first_face].split(",")

    assert len(node_ids) == 4
    lines[first_face] = ",".join(reversed(node_ids))

    assert _audit_mutated_fixture_lines(module, tmp_path, lines)["ok"] is False


def test_fixture_script_rejects_solve_without_model_json_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_buffer_fixture_script()
    output_root = tmp_path / "fixture"
    output_root.mkdir()
    solver = tmp_path / "lsdyna_fixture.exe"
    solver.write_bytes(b"trusted fixture solver")
    _configure_fixture_module(module, monkeypatch, solver)

    monkeypatch.setattr(
        module,
        "execute_lsdyna_initialization_smoke",
        lambda project, solver_path, **_kwargs: _successful_mcheck_record(
            project,
            solver_path,
        ),
    )

    def solve_without_model_json_identity(
        project: Path,
        solver_path: Path,
        **_kwargs,
    ) -> dict[str, object]:
        record = _successful_solve_record(project, solver_path)
        del record["model_json_sha256"]
        return record

    monkeypatch.setattr(
        module,
        "execute_lsdyna_run",
        solve_without_model_json_identity,
    )

    result = module.run_fixture(output_root, solver_exe=solver)

    assert result["all_ok"] is False
    assert result["failure"]["stage"] == "solve"
    assert result["solve"]["ok"] is False
