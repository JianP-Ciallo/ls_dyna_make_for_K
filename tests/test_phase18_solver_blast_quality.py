from __future__ import annotations

import pytest

from lsprepost_mcp.refined_building.artifacts import (
    BeamElement,
    MeshFragment,
    Node,
    ShellElement,
    SolidElement,
)
from lsprepost_mcp.refined_building.solver_blast import mesh_quality as mesh_quality_module
from lsprepost_mcp.refined_building.solver_blast import surface_topology as surface_topology_module
from lsprepost_mcp.refined_building.solver_blast.materials import (
    material_review_record,
)
from lsprepost_mcp.refined_building.solver_blast.mesh_quality import (
    audit_mesh_quality,
)


def _unit_hex(*, twisted: bool = False) -> MeshFragment:
    coordinates = (
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 1.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (1.0, 0.0, 1.0),
        ((-0.35, 0.25, 0.10) if twisted else (1.0, 1.0, 1.0)),
        (0.0, 1.0, 1.0),
    )
    return MeshFragment(
        nodes=tuple(
            Node(index, *point) for index, point in enumerate(coordinates, start=1)
        ),
        solids=(SolidElement(1, tuple(range(1, 9)), "test_solid"),),
    )


def test_hex8_requires_positive_jacobian_at_all_natural_corners() -> None:
    report = audit_mesh_quality(_unit_hex(twisted=True))

    assert "solid_nonpositive_corner_jacobian" in {
        row.finding_id for row in report.findings
    }


def test_valid_unit_hex_reports_all_eight_positive_corner_jacobians() -> None:
    report = audit_mesh_quality(_unit_hex())

    assert report.solid_count == 1
    assert report.minimum_corner_jacobian_m3 == 0.125
    assert report.maximum_aspect_ratio == 1.0
    assert report.findings == ()


def test_duplicate_geometry_and_orphan_nodes_are_hard_findings() -> None:
    first = _unit_hex()
    shifted_nodes = tuple(
        Node(node.node_id + 8, node.x, node.y, node.z) for node in first.nodes
    )
    mesh = MeshFragment(
        nodes=(*first.nodes, *shifted_nodes, Node(17, 2.0, 2.0, 2.0)),
        solids=(
            first.solids[0],
            SolidElement(2, tuple(range(9, 17)), "duplicate_test_solid"),
        ),
    )

    report = audit_mesh_quality(mesh)
    finding_ids = {row.finding_id for row in report.findings}

    assert report.duplicate_element_count == 1
    assert report.orphan_node_count == 1
    assert "duplicate_element_geometry" in finding_ids
    assert "orphan_mesh_node" in finding_ids


def test_positive_volume_solid_overlap_is_not_confused_with_face_contact() -> None:
    def block(
        node_start: int,
        element_id: int,
        x0: float,
        x1: float,
        role: str,
    ) -> tuple[tuple[Node, ...], SolidElement]:
        points = (
            (x0, 0.0, 0.0),
            (x1, 0.0, 0.0),
            (x1, 1.0, 0.0),
            (x0, 1.0, 0.0),
            (x0, 0.0, 1.0),
            (x1, 0.0, 1.0),
            (x1, 1.0, 1.0),
            (x0, 1.0, 1.0),
        )
        nodes = tuple(
            Node(node_start + index, *point) for index, point in enumerate(points)
        )
        return nodes, SolidElement(
            element_id,
            tuple(node.node_id for node in nodes),
            role,
        )

    left_nodes, left = block(1, 1, 0.0, 1.0, "left")
    overlap_nodes, overlap = block(9, 2, 0.5, 1.5, "overlap")
    touch_nodes, touch = block(17, 3, 1.5, 2.5, "face_touch")
    report = audit_mesh_quality(
        MeshFragment(
            nodes=(*left_nodes, *overlap_nodes, *touch_nodes),
            solids=(left, overlap, touch),
        )
    )

    assert report.solid_overlap_pair_count == 1
    assert "solid_positive_volume_overlap" in {
        row.finding_id for row in report.findings
    }


def test_overlap_broad_phase_prunes_solids_separated_on_secondary_axis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    solid_count = 200
    nodes: list[Node] = []
    solids: list[SolidElement] = []
    for index in range(solid_count):
        node_start = 8 * index + 1
        y0 = float(2 * index)
        points = (
            (0.0, y0, 0.0), (1.0, y0, 0.0),
            (1.0, y0 + 1.0, 0.0), (0.0, y0 + 1.0, 0.0),
            (0.0, y0, 1.0), (1.0, y0, 1.0),
            (1.0, y0 + 1.0, 1.0), (0.0, y0 + 1.0, 1.0),
        )
        element_nodes = tuple(
            Node(node_start + offset, *point)
            for offset, point in enumerate(points)
        )
        nodes.extend(element_nodes)
        solids.append(SolidElement(
            index + 1,
            tuple(node.node_id for node in element_nodes),
            "separated_solid",
        ))

    overlap_checks = 0
    real_overlap_check = mesh_quality_module._positive_aabb_overlap

    def counted_overlap_check(left, right):
        nonlocal overlap_checks
        overlap_checks += 1
        return real_overlap_check(left, right)

    monkeypatch.setattr(
        mesh_quality_module,
        "_positive_aabb_overlap",
        counted_overlap_check,
    )

    report = audit_mesh_quality(MeshFragment(nodes=tuple(nodes), solids=tuple(solids)))

    assert report.solid_overlap_pair_count == 0
    assert overlap_checks <= solid_count


def test_conforming_warped_hex_neighbors_are_not_overlap_findings() -> None:
    first_points = (
        (0.4, 0.05695547293232586, 5.106027656501243),
        (0.5435389432535157, 0.05671917259268779, 5.10684345529285),
        (0.5434836558712284, 0.41830798585636353, 5.21161402071003),
        (0.4, 0.4185148710267253, 5.210774957903786),
        (0.4, 0.04304452706767414, 5.154053541033968),
        (0.5564610567464839, 0.04328082740731221, 5.153237742242361),
        (0.5565163441287713, 0.40669201414363654, 5.258467176825182),
        (0.4, 0.40648512897327477, 5.259306239631425),
    )
    diagonal_points = (
        first_points[2],
        (0.7874188904188443, 0.4176997134326647, 5.064072082799013),
        (0.7872649219391445, 0.7785087945168517, 5.13881546866618),
        (0.5433974268166171, 0.7789318285506605, 5.286250963385652),
        first_points[6],
        (0.8125811095811554, 0.40730028656733536, 5.106009114736198),
        (0.8127350780608551, 0.7714912054831485, 5.18126572886903),
        (0.5566025731833826, 0.7710681714493398, 5.333830234149558),
    )
    nodes = tuple(Node(index, *point) for index, point in enumerate(first_points, 1))
    extra = tuple(
        Node(index, *point)
        for index, point in enumerate(diagonal_points[1:4] + diagonal_points[5:], 9)
    )
    diagonal_ids = (3, 9, 10, 11, 7, 12, 13, 14)
    report = audit_mesh_quality(MeshFragment(
        nodes=(*nodes, *extra),
        solids=(
            SolidElement(1, tuple(range(1, 9)), "curved_roof"),
            SolidElement(2, diagonal_ids, "curved_roof"),
        ),
    ))

    assert report.solid_overlap_pair_count == 0
    assert report.unresolved_overlap_candidate_count == 0
    assert not {
        "solid_positive_volume_overlap", "solid_overlap_unresolved",
    } & {row.finding_id for row in report.findings}


def test_shell_winding_is_a_per_physical_part_audit() -> None:
    nodes = (
        Node(1, 0.0, 0.0, 0.0), Node(2, 1.0, 0.0, 0.0),
        Node(3, 1.0, 1.0, 0.0), Node(4, 0.0, 1.0, 0.0),
        Node(5, 1.0, 0.0, 1.0), Node(6, 1.0, 1.0, 1.0),
    )
    distinct_parts = audit_mesh_quality(MeshFragment(
        nodes=nodes,
        shells=(
            ShellElement(1, (1, 2, 3, 4), "step_band"),
            ShellElement(2, (2, 3, 6, 5), "balustrade"),
        ),
    ))
    same_part = audit_mesh_quality(MeshFragment(
        nodes=nodes,
        shells=(
            ShellElement(1, (1, 2, 3, 4), "joined_skin"),
            ShellElement(2, (2, 3, 6, 5), "joined_skin"),
        ),
    ))

    assert "shell_inconsistent_winding" not in {
        row.finding_id for row in distinct_parts.findings
    }
    assert "shell_inconsistent_winding" in {
        row.finding_id for row in same_part.findings
    }


def test_solver_mesh_reconciliation_removes_shared_bar_and_orients_shells() -> None:
    nodes = (
        Node(1, 0.0, 0.0, 0.0), Node(2, 1.0, 0.0, 0.0),
        Node(3, 1.0, 1.0, 0.0), Node(4, 0.0, 1.0, 0.0),
        Node(5, 1.0, 0.0, 1.0), Node(6, 1.0, 1.0, 1.0),
        Node(7, 0.0, 0.0, 2.0), Node(8, 1.0, 0.0, 2.0),
        Node(9, 0.0, 0.0, 2.0), Node(10, 1.0, 0.0, 2.0),
    )
    mesh = MeshFragment(
        nodes=nodes,
        shells=(
            ShellElement(1, (1, 2, 3, 4), "partition"),
            ShellElement(2, (2, 3, 6, 5), "partition"),
        ),
        beams=(
            BeamElement(3, (7, 8), "column_stirrup"),
            BeamElement(4, (10, 9), "beam_stirrup"),
        ),
    )
    before = audit_mesh_quality(mesh)

    reconciled = surface_topology_module._reconcile_solver_mesh(mesh)
    after = audit_mesh_quality(reconciled)

    assert before.duplicate_element_count == 1
    assert "shell_inconsistent_winding" in {
        row.finding_id for row in before.findings
    }
    assert len(reconciled.beams) == 1
    assert reconciled.beams[0].part_role == "column_stirrup"
    assert after.duplicate_element_count == 0
    assert "shell_inconsistent_winding" not in {
        row.finding_id for row in after.findings
    }


def test_zero_area_shell_and_zero_length_beam_are_rejected_by_coordinates() -> None:
    mesh = MeshFragment(
        nodes=(
            Node(1, 0.0, 0.0, 0.0),
            Node(2, 1.0, 0.0, 0.0),
            Node(3, 2.0, 0.0, 0.0),
            Node(4, 3.0, 0.0, 0.0),
            Node(5, 4.0, 0.0, 0.0),
            Node(6, 4.0, 0.0, 0.0),
        ),
        shells=(ShellElement(1, (1, 2, 3, 4), "flat_shell"),),
        beams=(BeamElement(2, (5, 6), "zero_beam"),),
    )

    finding_ids = {row.finding_id for row in audit_mesh_quality(mesh).findings}

    assert "shell_nonpositive_area" in finding_ids
    assert "beam_nonpositive_length" in finding_ids


def test_reference_material_profile_never_claims_engineering_validation() -> None:
    record = material_review_record("verification_reference")

    assert record.engineering_validated is False
    assert record.requires_project_review is True

def test_uncertified_project_profile_also_requires_project_review() -> None:
    record = material_review_record("project_calibrated")

    assert record.engineering_validated is False
    assert record.requires_project_review is True
