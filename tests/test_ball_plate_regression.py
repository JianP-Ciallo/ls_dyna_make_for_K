"""Small, portable reproductions of the 2026-09-29 ball/plate failure."""
import json

import pytest

from lsprepost_mcp.keyword_checks import keyword_quality_checks, parse_keyword_model
from lsprepost_mcp.project_store import parse_keyword_metadata, validate_project_files


def deck(points, elements="1,1,1,2,3,4"):
    nodes = "\n".join(f"{i},{x},{y},{z}" for i, (x, y, z) in enumerate(points, 1))
    return f"""*KEYWORD
*NODE
{nodes}
*ELEMENT_SHELL
{elements}
*PART
plate
1,1,1
*SECTION_SHELL
1,2
0.001,0.001,0.001,0.001
*MAT_ELASTIC
1,7850,2.1e11,0.3
*END
"""


def checks(text):
    return {item["id"]: item for item in keyword_quality_checks(text, {"model_type": "imported_keyword"}, {})}


def test_collapsed_plate_reports_solver_code_and_coordinate_evidence():
    # Source shell 1 uses nodes 18,19,2,1: two pairs of coincident points.
    text = deck([(-131.25, 0, 0), (-131.25, 0, 0), (-150, 0, 0), (-150, 0, 0)])
    result = checks(text)["quality.geometry.shell_zero_normal"]
    assert not result["ok"] and result["severity"] == "error"
    assert result["actual"]["element_ids"] == [1]
    assert result["actual"]["solver_error_code"] == 30099
    sample = result["actual"]["samples"][0]
    assert sample["part_id"] == 1
    assert sample["distinct_coordinate_count"] == 2
    assert sample["coordinates"] == [[-131.25, 0, 0], [-131.25, 0, 0], [-150, 0, 0], [-150, 0, 0]]


def test_crossed_shell_blocks_even_when_unsigned_triangle_areas_are_positive():
    result = checks(deck([(0, 0, 0), (1, 1, 0), (0, 1, 0), (1, 0, 0)]))
    assert result["quality.geometry.shell_area"]["ok"]
    assert not result["quality.geometry.shell_zero_normal"]["ok"]


@pytest.mark.parametrize("points", [
    [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)],
    [(2, 3, 4)] * 4,
])
def test_collinear_and_fully_coincident_shells_are_errors(points):
    result = checks(deck(points))["quality.geometry.shell_zero_normal"]
    assert not result["ok"]


@pytest.mark.parametrize("scale", [1e-6, 1, 1e6])
@pytest.mark.parametrize("nodes", ["1,2,3,4", "4,3,2,1", "1,2,3,3", "1,2,3,0"])
def test_valid_shells_and_triangles_do_not_trigger_zero_normal(scale, nodes):
    text = deck([(0, 0, 0), (scale, 0, 0), (scale, scale, 0), (0, scale, 0)], f"1,1,{nodes}")
    result = checks(text)
    assert result["quality.ref.element_nodes"]["ok"]
    assert result["quality.geometry.shell_zero_normal"]["ok"]
    assert result["quality.geometry.shell_shape_ratio"]["ok"]


def test_shape_ratio_detects_skinny_shell_with_equal_length_edges():
    # Rhombus: edge aspect ratio ~1, but area / longest diagonal squared < 0.1.
    text = deck([(0, 0, 0), (1, 0, 0), (2, 0.1, 0), (1, 0.1, 0)])
    result = checks(text)
    assert result["quality.geometry.shell_aspect_ratio"]["ok"]
    assert result["quality.geometry.shell_zero_normal"]["ok"]
    shape = result["quality.geometry.shell_shape_ratio"]
    assert not shape["ok"] and shape["severity"] == "warning"
    assert shape["actual"]["solver_warning_code"] == 21129
    assert shape["actual"]["min_ratio"] == pytest.approx(0.1 / 4.01)


def test_missing_node_does_not_shift_reported_element_ids():
    result = checks(deck([(0, 0, 0), (20, 0, 0), (20, 1, 1), (0, 1, 0)], "10,1,1,2,3,999\n20,1,1,2,3,4"))
    assert not result["quality.ref.element_nodes"]["ok"]
    assert result["quality.geometry.shell_warpage"]["actual"]["warped_elements"] == [20]
    assert result["quality.geometry.shell_aspect_ratio"]["actual"]["high_aspect_elements"] == [20]


@pytest.mark.parametrize("coordinate", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_coordinates_are_blocking_and_evidence_is_json_safe(coordinate):
    text = deck([(0, 0, 0), (coordinate, 0, 0), (1, 1, 0), (0, 1, 0)])
    result = checks(text)
    finite = result["quality.geometry.shell_finite_coordinates"]
    assert not finite["ok"] and finite["severity"] == "error"
    assert finite["actual"]["element_ids"] == [1]
    json.dumps(list(result.values()), allow_nan=False)


def test_planar_normal_check_accepts_zero_fourth_node_triangle():
    text = deck([(0, 0, 0), (1, 0, 0), (1, 1, 0)], "20,1,1,2,3,0")
    result = {item["id"]: item for item in keyword_quality_checks(text, {"model_type": "shell_plate"}, {})}
    assert result["quality.geometry.shell_normals"]["ok"]


def test_planar_normal_check_preserves_element_ids_after_missing_node():
    text = deck([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], "10,1,1,2,3,999\n20,1,1,2,3,4\n30,1,4,3,2,1")
    result = {item["id"]: item for item in keyword_quality_checks(text, {"model_type": "shell_plate"}, {})}
    assert result["quality.geometry.shell_normals"]["actual"] == [30]


def test_all_256_collapsed_shells_are_reported_without_sampling_loss():
    points = [(-150 + 18.75 * i, 0, 0) for i in range(17) for _ in range(17)]
    elements = []
    for i in range(16):
        for j in range(16):
            n = 17 * i + j + 1
            elements.append(f"{len(elements)+1},1,{n+17},{n+18},{n+1},{n}")
    result = checks(deck(points, "\n".join(elements)))["quality.geometry.shell_zero_normal"]
    assert result["actual"]["element_ids"] == list(range(1, 257))
    assert result["actual"]["count"] == 256
    assert len(result["actual"]["samples"]) <= 10


@pytest.mark.parametrize("material", [
    "*MAT_RIGID_TITLE\nrigid material for ball\n         17.83000E-6     207.0       0.3       0.0       0.0       0.0          \n       0.0         0         0         0       0.0       0.0       0.0",
    "*MAT_ELASTIC_TITLE\n12345\n         17.83000E-6     207.0       0.3",
    "*MAT_ELASTIC_TITLE\n\n         17.83000E-6     207.0       0.3\n0,0,0,0",
    "*MAT_ELASTIC\n1,7.83e-6,207,0.3",
    "*MAT_ELASTIC\n1 7.83e-6 207 0.3",
])
def test_material_header_fixed_columns_title_and_free_format_agree(material):
    text = deck([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)])
    text = text.replace("*MAT_ELASTIC\n1,7850,2.1e11,0.3", material)
    model = parse_keyword_model(text)
    assert model.material_id_list == [1]
    assert model.material_density[1] == pytest.approx(7.83e-6)
    metadata = parse_keyword_metadata(text)
    assert metadata["material_ids"] == [1]
    assert metadata["missing_material_refs"] == []


def test_invalid_material_header_does_not_use_continuation_as_material_zero():
    text = "*KEYWORD\n*MAT_RIGID_TITLE\nball\ninvalid material data\n0,0,0,0\n*END"
    assert parse_keyword_model(text).material_ids == set()
    assert parse_keyword_metadata(text)["material_ids"] == []


@pytest.mark.parametrize("points", [
    [(0, 0, 0), (1, 1, 0), (0, 1, 0), (1, 0, 0)],
    [(0, 0, 0), (1, 0, 0), (2, 0.1, 0), (1, 0.1, 0)],
])
def test_imported_project_readiness_blocks_new_geometry_findings(tmp_path, points):
    text = deck(points)
    (tmp_path / "model.k").write_text(text, encoding="utf-8")
    (tmp_path / "model.json").write_text(json.dumps({
        "spec": {"model_type": "imported_keyword"},
        "metadata": parse_keyword_metadata(text),
    }), encoding="utf-8")
    result = validate_project_files(tmp_path)
    assert not result["readiness"]["ok_for_solver_draft"]
    assert any(not c["ok"] for c in result["checks"] if c["id"] in {
        "quality.geometry.shell_zero_normal", "quality.geometry.shell_shape_ratio",
    })
