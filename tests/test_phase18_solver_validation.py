from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from types import MappingProxyType

from lsprepost_mcp.refined_building import compile_detailed_building_asset
from lsprepost_mcp.refined_building.artifacts import (
    BeamElement,
    BuildingArtifact,
    MeshFragment,
    Node,
    PartBinding,
    ShellElement,
    SolidElement,
)
from lsprepost_mcp.refined_building.solver_validation import (
    inspect_initial_solver_validation_model,
    write_initial_solver_validation_model,
)
from lsprepost_mcp.lsdyna_runner import _evaluate_d3hsp, _result_mode
from lsprepost_mcp.solver_results import evaluate_solver_result


def _shell_shape_quality(
    points: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ],
) -> float:
    def subtract(
        left: tuple[float, float, float], right: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        return (
            left[0] - right[0],
            left[1] - right[1],
            left[2] - right[2],
        )

    def norm(vector: tuple[float, float, float]) -> float:
        return math.sqrt(sum(value * value for value in vector))

    def cross(
        left: tuple[float, float, float], right: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        return (
            left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0],
        )

    area = 0.5 * norm(
        cross(subtract(points[1], points[0]), subtract(points[2], points[0]))
    )
    area += 0.5 * norm(
        cross(subtract(points[2], points[0]), subtract(points[3], points[0]))
    )
    longest_diagonal = max(
        norm(subtract(points[2], points[0])),
        norm(subtract(points[3], points[1])),
    )
    return area / (longest_diagonal * longest_diagonal)


def _solid_artifact() -> BuildingArtifact:
    nodes = (
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 1.0, 0.0, 0.0),
        Node(3, 1.0, 1.0, 0.0),
        Node(4, 0.0, 1.0, 0.0),
        Node(5, 0.0, 0.0, 1.0),
        Node(6, 1.0, 0.0, 1.0),
        Node(7, 1.0, 1.0, 1.0),
        Node(8, 0.0, 1.0, 1.0),
        Node(9, 0.1, 0.1, 0.1),
        Node(10, 0.9, 0.1, 0.1),
    )
    return BuildingArtifact(
        asset_id="solid-child",
        system_id="rc_frame",
        mesh=MeshFragment(
            nodes=nodes,
            solids=(SolidElement(1, (1, 2, 3, 4, 5, 6, 7, 8), "rc_column"),),
            beams=(BeamElement(2, (9, 10), "column_rebar"),),
            part_bindings=(
                PartBinding("rc_column", "concrete", "rc_column_solid_section"),
                PartBinding("column_rebar", "reinforcing_steel", "column_rebar_beam_section"),
            ),
        ),
    )


def _shell_artifact_with_reused_local_ids() -> BuildingArtifact:
    return BuildingArtifact(
        asset_id="shell-child",
        system_id="rc_frame",
        mesh=MeshFragment(
            nodes=(
                Node(1, 2.0, 0.0, 0.0),
                Node(2, 3.0, 0.0, 0.0),
                Node(3, 3.0, 0.0, 1.0),
                Node(4, 2.0, 0.0, 1.0),
            ),
            shells=(ShellElement(1, (1, 2, 3, 4), "nonstructural_facade"),),
            part_bindings=(
                PartBinding(
                    "nonstructural_facade",
                    "facade_material",
                    "nonstructural_facade_shell_section",
                ),
            ),
        ),
    )


def test_default_subway_shells_meet_r12_shape_heuristic() -> None:
    package = compile_detailed_building_asset(
        "subway_entrance_detailed_building",
        mesh_profile="coarse",
        fidelity_profile="blast_response",
    )

    bad: list[tuple[str, int, float]] = []
    glazing_vertical_edges: Counter[tuple[float, float, tuple[int, int]]] = Counter()
    glazing_x_by_side: dict[float, set[float]] = defaultdict(set)
    for artifact in package.artifacts:
        nodes = {node.node_id: node.coordinates for node in artifact.mesh.nodes}
        for element in artifact.mesh.shells:
            quality = _shell_shape_quality(
                tuple(nodes[node_id] for node_id in element.node_ids)  # type: ignore[arg-type]
            )
            if quality < 0.1:
                bad.append((element.part_role, element.element_id, quality))
            if element.part_role == "pavilion_glazing":
                for left, right in ((0, 3), (1, 2)):
                    left_id = element.node_ids[left]
                    right_id = element.node_ids[right]
                    x, y, _ = nodes[left_id]
                    assert nodes[right_id][0] == x
                    assert nodes[right_id][1] == y
                    side = round(y, 12)
                    boundary = round(x, 12)
                    glazing_x_by_side[side].add(boundary)
                    glazing_vertical_edges[
                        (side, boundary, tuple(sorted((left_id, right_id))))
                    ] += 1

    assert bad == []
    internal_edges = 0
    for (side, boundary, _), use_count in glazing_vertical_edges.items():
        side_boundaries = glazing_x_by_side[side]
        if min(side_boundaries) < boundary < max(side_boundaries):
            internal_edges += 1
            assert use_count == 2
    assert internal_edges > 0


def test_initial_solver_validation_model_is_dependency_closed_and_renumbered(
    tmp_path: Path,
) -> None:
    manifest = write_initial_solver_validation_model(
        (_solid_artifact(), _shell_artifact_with_reused_local_ids()),
        tmp_path,
        source_identity=MappingProxyType(
            {
                "resource_id": "test-building",
                "package_fingerprint": "a" * 64,
                "selection": MappingProxyType({"mesh_profile": "coarse"}),
            }
        ),
        termination_time_s=0.001,
    )

    keyword = (tmp_path / "model.k").read_text(encoding="utf-8")
    model_json = json.loads((tmp_path / "model.json").read_text(encoding="utf-8"))
    persisted_manifest = json.loads(
        (tmp_path / "validation_manifest.json").read_text(encoding="utf-8")
    )

    assert manifest == persisted_manifest
    assert manifest["source_identity"]["selection"] == {"mesh_profile": "coarse"}
    assert model_json["spec"]["model_type"] == "refined_building_initial_validation"
    assert model_json["spec"]["termination_time_s"] == 0.001
    assert "*CONTROL_TERMINATION\n0.001" in keyword
    assert "*CONTROL_ENERGY" in keyword
    assert "2,2,2,2" in keyword
    assert "*LOAD_BODY_Z" in keyword
    assert "*BOUNDARY_SPC_SET" in keyword
    assert keyword.count("*PART_TITLE") == 3
    assert "*SECTION_SOLID_TITLE" in keyword
    assert "*SECTION_SHELL_TITLE" in keyword
    assert "*SECTION_BEAM_TITLE" in keyword
    assert keyword.count("*MAT_ELASTIC_TITLE") == 3
    for line in keyword.splitlines():
        if not line or line.startswith(("*", "$")) or "," not in line:
            continue
        assert all(len(field.strip()) <= 10 for field in line.split(",")), line
    assert manifest["counts"] == {
        "artifacts": 2,
        "nodes": 14,
        "solid_elements": 1,
        "shell_elements": 1,
        "beam_elements": 1,
        "total_elements": 3,
        "parts": 3,
        "fixed_base_nodes": 6,
    }
    assert manifest["engineering_validated"] is False
    assert manifest["solver_ready"] is False

    inspection = inspect_initial_solver_validation_model(tmp_path)
    assert inspection["ok"] is True
    assert inspection["findings"] == []


def test_initial_solver_validation_inspection_rejects_file_tampering(tmp_path: Path) -> None:
    write_initial_solver_validation_model(
        (_solid_artifact(),),
        tmp_path,
        source_identity={"resource_id": "test-building", "package_fingerprint": "b" * 64},
    )
    with (tmp_path / "model.k").open("ab") as handle:
        handle.write(b"$ tampered\n")

    inspection = inspect_initial_solver_validation_model(tmp_path)
    assert inspection["ok"] is False
    assert inspection["findings"] == [
        "model.k size mismatch",
        "model.k sha256 mismatch",
    ]


def test_initial_validation_solver_mode_does_not_require_impact_energy_ratio() -> None:
    text = """
 kinetic energy ........ 1.0e-6
 internal energy ....... 1.0e-3
 hourglass energy ...... 1.0e-6
 total energy .......... 1.002e-3
 Problem time = 1.0002e-3
 termination time reached
 normal termination
 """

    initial = evaluate_solver_result(
        text,
        "initial_validation",
        expected_termination_time_s=0.001,
    )
    impact = evaluate_solver_result(text, "impact")

    assert initial["ok"] is True
    assert {row["id"] for row in initial["checks"]} == {
        "normal_termination",
        "finite_energies",
        "internal_energy_nonnegative",
        "hourglass_energy_ratio",
        "termination_time_reached",
    }
    assert impact["ok"] is False


def test_initial_validation_rejects_missing_hourglass_energy() -> None:
    text = """
 kinetic energy ........ 1.0e-6
 internal energy ....... 1.0e-3
 total energy .......... 1.001e-3
 Problem time = 1.0e-3
 termination time reached
 """

    result = evaluate_solver_result(
        text,
        "initial_validation",
        expected_termination_time_s=0.001,
    )

    assert result["ok"] is False
    hourglass = next(
        row for row in result["checks"] if row["id"] == "hourglass_energy_ratio"
    )
    assert hourglass["actual"] is None
    assert hourglass["ok"] is False


def test_initial_validation_rejects_normal_termination_before_target_time() -> None:
    text = """
 kinetic energy ........ 1.0e-6
 internal energy ....... 1.0e-3
 hourglass energy ...... 0.0
 total energy .......... 1.001e-3
 Problem time = 5.0e-4
 normal termination
 """

    result = evaluate_solver_result(
        text,
        "initial_validation",
        expected_termination_time_s=0.001,
    )

    assert result["ok"] is False
    reached = next(
        row for row in result["checks"] if row["id"] == "termination_time_reached"
    )
    assert reached["actual"] == 0.0005
    assert reached["ok"] is False


def test_runner_selects_initial_validation_mode_from_model_json(tmp_path: Path) -> None:
    (tmp_path / "model.json").write_text(
        json.dumps({"spec": {"model_type": "refined_building_initial_validation"}}),
        encoding="utf-8",
    )

    assert _result_mode(tmp_path) == "initial_validation"


def test_runner_binds_initial_validation_to_persisted_termination_time(
    tmp_path: Path,
) -> None:
    (tmp_path / "model.json").write_text(
        json.dumps(
            {
                "spec": {
                    "model_type": "refined_building_initial_validation",
                    "termination_time_s": 0.001,
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "d3hsp").write_text(
        "termination time reached\nProblem time = 1.0002e-3\n",
        encoding="utf-8",
    )
    (tmp_path / "glstat").write_text(
        "kinetic energy........ 1.0e-6\n"
        "internal energy....... 1.0e-3\n"
        "hourglass energy...... 0.0\n"
        "total energy.......... 1.001e-3\n",
        encoding="utf-8",
    )

    result = _evaluate_d3hsp(tmp_path, "initial_validation")

    assert result["ok"] is True
    reached = next(
        row for row in result["checks"] if row["id"] == "termination_time_reached"
    )
    assert reached["actual"] == 0.0010002
