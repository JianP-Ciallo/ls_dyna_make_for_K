import hashlib
import json
from pathlib import Path

import pytest

from lsprepost_mcp import paths, r12_plate, server
from lsprepost_mcp.planner import PlanResult
from lsprepost_mcp.provenance import verify_generated_project


UNITS = "mm_ms_g_N_MPa"
SPEC = {
    "project_name": "meshing_test",
    "model_type": "shell_plate",
    "unit_system": UNITS,
    "geometry": {"length_mm": 100, "width_mm": 50, "thickness_mm": 2},
    "mesh": {"size_mm": 5},
    "material": {"type": "elastic", "density_g_per_mm3": 0.00785, "youngs_mpa": 210000, "poisson": .3},
    "boundary_conditions": [{"type": "fixed_edge", "edge": "x_min"}],
}
IMPORT_SPEC = {key: value for key, value in SPEC.items() if key != "mesh"}


def mcp(tool, args):
    response = server.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    })
    if "error" in response:
        raise ValueError(response["error"]["message"])
    return json.loads(response["result"]["content"][0]["text"])


def mesh_request(size=5):
    return {"unit_system": UNITS, "length_mm": 100, "width_mm": 50, "size_mm": size}


@pytest.fixture(autouse=True)
def projects(tmp_path, monkeypatch):
    path = tmp_path / "projects"
    monkeypatch.setattr(r12_plate, "PROJECTS_DIR", path)
    monkeypatch.setattr(paths, "PROJECTS_DIR", path)
    return path


def test_remesh_rebinds_left_edge_before_writing_keyword():
    coarse = mcp("build_mesh", mesh_request(10))
    fine = mcp("build_mesh", mesh_request(5))
    assert coarse["method"] == fine["method"] == "structured"
    assert coarse["mesh_id"] != fine["mesh_id"]
    assert coarse["regions"]["plate.left_edge"]["count"] == 6
    assert fine["regions"]["plate.left_edge"]["count"] == 11
    assert fine["outline_mm"] == [[0, 0], [100, 0], [100, 50], [0, 50]]
    request = {"spec": SPEC, "mesh_id": fine["mesh_id"]}
    result = mcp("configure_model", request)
    assert result["checks"]["ok"]
    assert result["bindings"]["plate.left_edge"]["node_count"] == 11
    assert result["bindings"]["plate.left_edge"]["set_id"] == 1001
    assert result["mesh_id"] == fine["mesh_id"]
    assert verify_generated_project(result["project_dir"])["ok"]
    assert not ({e["id"] for e in fine["evidence"]} & {e["id"] for e in result["evidence"]})
    assert "r12.node" in fine["knowledge_ids"]
    assert "r12.boundary_spc_set" in result["knowledge_ids"]


def test_configuration_rejects_a_previous_mesh_for_a_new_size(projects):
    coarse = mcp("build_mesh", mesh_request(10))
    with pytest.raises(ValueError, match="网格尺寸"):
        mcp("configure_model", {"spec": SPEC, "mesh_id": coarse["mesh_id"]})
    assert not (projects / "meshing_test").exists()


def test_native_triangular_route_generates_and_writes_positive_shells():
    artifact = mcp("build_mesh", {**mesh_request(), "method": "triangular"})
    assert artifact["quality"]["triangle_count"] == 400
    assert artifact["quality"]["quad_count"] == 0
    assert artifact["quality"]["area_mm2"] == 5000
    result = mcp("configure_model", {"spec": SPEC, "mesh_id": artifact["mesh_id"]})
    assert result["checks"]["ok"]
    assert "*SECTION_SHELL" in Path(result["keyword_path"]).read_text(encoding="utf-8")


def test_configured_material_uses_r12_field_width():
    artifact = mcp("build_mesh", mesh_request())
    result = mcp("configure_model", {"spec": SPEC, "mesh_id": artifact["mesh_id"]})
    rows = Path(result["keyword_path"]).read_text(encoding="utf-8").split("*MAT_ELASTIC\n")[1].splitlines()
    fields = next(row for row in rows if row and not row.startswith("$")).split(",")
    assert all(len(value) <= 10 for value in fields)
    assert float(fields[2]) == 210_000


def test_mixed_shell_mesh_uses_r12_explicit_triangle_sorting(tmp_path):
    deck = tmp_path / "mixed.k"
    deck.write_text(
        "*NODE\n1,0,0,0\n2,50,0,0\n3,100,0,0\n4,0,50,0\n5,50,50,0\n6,100,50,0\n"
        "*ELEMENT_SHELL\n10,1,1,2,5,4\n11,1,2,3,6,6\n12,1,2,6,5,5\n*END\n",
        encoding="ascii",
    )
    artifact = mcp("build_mesh", {"source_path": str(deck), "unit_system": UNITS})
    result = mcp("configure_model", {"spec": IMPORT_SPEC, "mesh_id": artifact["mesh_id"]})
    rendered = Path(result["keyword_path"]).read_text(encoding="utf-8")
    assert "*CONTROL_SHELL\n20,1,-1,0,2,2,1,0\n" in rendered
    assert "*SECTION_SHELL\n" in rendered and "\n1,2,0.833000" in rendered


def test_reviewer_detects_an_edited_deck_with_wrong_set_reference():
    mesh = mcp("build_mesh", mesh_request())
    result = mcp("configure_model", {"spec": SPEC, "mesh_id": mesh["mesh_id"]})
    deck = Path(result["keyword_path"])
    deck.write_text(
        deck.read_text(encoding="utf-8").replace("1001,0,1,1,1,1,1,1\n", "1002,0,1,1,1,1,1,1\n"),
        encoding="utf-8",
    )
    checks = mcp("validate_model", {"project_name": SPEC["project_name"]})
    assert not checks["ok"]
    assert any("约束集合" in error for error in checks["errors"])


@pytest.mark.parametrize("change", ["end_moved", "extra_constraint"])
def test_reviewer_rejects_keyword_layout_that_changes_the_planned_deck(change):
    mesh = mcp("build_mesh", mesh_request())
    result = mcp("configure_model", {"spec": SPEC, "mesh_id": mesh["mesh_id"]})
    deck = Path(result["keyword_path"])
    text = deck.read_text(encoding="utf-8")
    if change == "end_moved":
        edited = text.replace("*KEYWORD\n", "*KEYWORD\n*END\n").removesuffix("*END\n")
    else:
        edited = text.replace("*END", "*BOUNDARY_SPC_NODE\n1,0,1,1,1,1,1,1\n*END")
    deck.write_text(edited, encoding="utf-8")
    checks = mcp("validate_model", {"project_name": SPEC["project_name"]})
    assert not checks["ok"]
    assert not checks["mesh_binding_check"]["ok"]


def test_plan_rejects_binding_to_an_undeclared_mesh_artifact():
    mesh = {"id": "build_mesh", "depends_on": [], "input": {}, "outputs": ["mesh_id"]}
    configure = {
        "id": "configure", "depends_on": ["build_mesh"], "input": {},
        "input_from": {"mesh_id": {"task_id": "build_mesh", "field": "filename"}},
        "outputs": ["model.k"],
    }
    with pytest.raises(ValueError, match="task input"):
        PlanResult("plate").ready([mesh, configure])


def test_configuration_does_not_trust_a_right_edge_labeled_left(projects):
    artifact = mcp("build_mesh", mesh_request())
    original = Path(artifact["artifact_path"])
    content = json.loads(original.read_bytes())
    content["regions"]["plate.left_edge"] = content["regions"]["plate.right_edge"]
    payload = json.dumps(content, separators=(",", ":"), sort_keys=True, allow_nan=False).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    original.with_name(f"{digest}.json").write_bytes(payload)
    with pytest.raises(ValueError, match="plate.left_edge"):
        mcp("configure_model", {"spec": SPEC, "mesh_id": digest})
    assert not (projects / "meshing_test").exists()


def test_configuration_rejects_a_rehashed_artifact_with_false_mesh_size(projects):
    coarse = mcp("build_mesh", mesh_request(10))
    path = Path(coarse["artifact_path"])
    content = json.loads(path.read_bytes())
    content["size_mm"] = 5
    raw = json.dumps(content, separators=(",", ":"), sort_keys=True, allow_nan=False).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    path.with_name(f"{digest}.json").write_bytes(raw)
    with pytest.raises(ValueError, match="网格尺寸"):
        mcp("configure_model", {"spec": SPEC, "mesh_id": digest})
    assert not (projects / "meshing_test").exists()


def test_keyword_import_preserves_ids_and_uses_real_outline(tmp_path):
    deck = tmp_path / "plate.k"
    deck.write_text("*KEYWORD\n*INCLUDE\nmesh.inc\n*END\n", encoding="ascii")
    (tmp_path / "mesh.inc").write_text(
        "*NODE\n11,10,20,0\n22,110,20,0\n33,110,70,0\n44,10,70,0\n"
        "*ELEMENT_SHELL\n70,9,11,22,33,44\n",
        encoding="ascii",
    )
    artifact = mcp("build_mesh", {"source_path": str(deck), "unit_system": UNITS})
    mesh = json.loads(Path(artifact["artifact_path"]).read_bytes())
    assert artifact["method"] == "keyword"
    assert artifact["outline_mm"] == [[10, 20], [110, 20], [110, 70], [10, 70]]
    assert mesh["regions"]["plate.left_edge"] == [11, 44]
    assert mesh["elements"] == [[70, 9, 11, 22, 33, 44]]
    assert len(mesh["source_files"]) == 2
    result = mcp("configure_model", {"spec": IMPORT_SPEC, "mesh_id": artifact["mesh_id"]})
    rendered = Path(result["keyword_path"]).read_text(encoding="utf-8")
    assert "70,9,11,22,33,44" in rendered
    assert "9,1,1,0,0,0,0,0" in rendered


def test_keyword_import_respects_a_declared_si_length_unit(tmp_path):
    deck = tmp_path / "plate_si.k"
    deck.write_text(
        "$ SI: m, s, kg, N, Pa.\n*NODE\n1,0,0,0\n2,0.1,0,0\n3,0.1,0.05,0\n4,0,0.05,0\n"
        "*ELEMENT_SHELL\n1,1,1,2,3,4\n*END\n",
        encoding="ascii",
    )
    payload = {"source_path": str(deck), "unit_system": UNITS}
    artifact = mcp("build_mesh", payload)
    assert artifact["outline_mm"] == [[0, 0], [100, 0], [100, 50], [0, 50]]
    assert artifact["source_length_unit"] == "m"
    with pytest.raises(ValueError, match="单位"):
        mcp("build_mesh", {**payload, "source_length_unit": "mm"})


def test_gmsh_ascii_mesh_can_be_configured(tmp_path):
    source = tmp_path / "plate.msh"
    source.write_text(
        "$MeshFormat\n2.2 0 8\n$EndMeshFormat\n$Nodes\n4\n"
        "1 0 0 0\n2 100 0 0\n3 100 50 0\n4 0 50 0\n$EndNodes\n"
        "$Elements\n3\n20 1 2 1 1 1 2\n21 2 2 2 1 1 2 3\n22 2 2 2 1 1 3 4\n$EndElements\n",
        encoding="ascii",
    )
    artifact = mcp("build_mesh", {"source_path": str(source), "unit_system": UNITS})
    assert artifact["method"] == "gmsh_ascii"
    assert artifact["quality"]["triangle_count"] == 2
    result = mcp("configure_model", {"spec": IMPORT_SPEC, "mesh_id": artifact["mesh_id"]})
    rendered = Path(result["keyword_path"]).read_text(encoding="utf-8")
    assert "21,2,1,2,3,3" in rendered
    assert "1,4," in rendered


def test_import_rejects_open_interior_boundary(tmp_path):
    deck = tmp_path / "missing_corner.k"
    deck.write_text(
        "*NODE\n1,0,0,0\n2,100,0,0\n3,100,50,0\n4,0,50,0\n"
        "*ELEMENT_SHELL\n1,1,1,2,3,3\n*END\n",
        encoding="ascii",
    )
    with pytest.raises(ValueError, match="矩形|边界|孤立"):
        mcp("build_mesh", {"source_path": str(deck), "unit_system": UNITS})
