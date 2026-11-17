import io
import json

import pytest

from lsprepost_mcp import knowledge_vectors, paths, planner, r12_plate, server


PLATE = {
    "mode": "create",
    "model_type": "shell_plate",
    "unit_system": "mm_ms_g_N_MPa",
    "length_mm": 100,
    "width_mm": 50,
    "thickness_mm": 2,
    "mesh_size_mm": 10,
    "material_type": "elastic",
    "density_g_per_mm3": 0.00785,
    "youngs_mpa": 210000,
    "poisson": 0.3,
    "geometry": "rectangular_plate",
    "support": "x_min",
    "analysis": "model_only",
    "load": "none",
}


def call_planner(requirements, *, text="规划一个弹性壳板模型", **options):
    reply = server.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "plan_simulation",
            "arguments": {"user_requirement": text, "requirements": requirements, **options},
        },
    })
    assert "error" not in reply, reply.get("error")
    return json.loads(reply["result"]["content"][0]["text"])


def test_new_shell_plate_is_handed_off_to_current_generator(tmp_path, monkeypatch):
    monkeypatch.setattr(r12_plate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(paths, "PROJECTS_DIR", tmp_path)
    plan = call_planner(PLATE)

    assert plan["status"] == "ready"
    assert not list(tmp_path.iterdir())
    assert plan["trace"]["knowledge_snapshot"]
    material_sources = [entry for entry in plan["evidence"] if entry["id"] == "r12.mat_elastic"]
    if material_sources:
        assert material_sources[0]["source"]["locator"] == "Volume II, PDF 190–192"
    else:
        assert "r12.mat_elastic" in plan["trace"]["unavailable_evidence_ids"]
    tasks = plan["tasks"]
    completed = set()
    for task in tasks:
        assert set(task["depends_on"]) <= completed
        completed.add(task["id"])
    meshing = next(task for task in tasks if task.get("tool") == "build_mesh")
    configuration = next(task for task in tasks if task.get("tool") == "configure_model")
    spec = configuration["input"]["spec"]
    assert spec["boundary_conditions"] == [{"type": "fixed_edge", "edge": "x_min"}]
    assert spec["geometry"]["length_mm"] == 100
    assert configuration["input_from"]["mesh_id"] == {"task_id": meshing["id"], "field": "mesh_id"}
    mesh = r12_plate.tool_build_mesh(meshing["input"])
    result = r12_plate.tool_configure_model({**configuration["input"], "mesh_id": mesh["mesh_id"]})
    assert result["checks"]["ok"]
    assert result["checks"]["mesh_binding_check"]["ok"]


def test_planned_generation_does_not_overwrite_existing_project(tmp_path, monkeypatch):
    monkeypatch.setattr(r12_plate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(paths, "PROJECTS_DIR", tmp_path)
    plan = call_planner({**PLATE, "project_name": "occupied"})
    task = next(task for task in plan["tasks"] if task.get("tool") == "configure_model")
    mesh_task = next(task for task in plan["tasks"] if task.get("tool") == "build_mesh")
    mesh = r12_plate.tool_build_mesh(mesh_task["input"])
    project = tmp_path / "occupied"
    project.mkdir()
    target = project / "model.k"
    target.write_text("original", encoding="ascii")
    with pytest.raises(FileExistsError, match="already exists"):
        r12_plate.tool_configure_model({**task["input"], "mesh_id": mesh["mesh_id"]})
    assert target.read_text(encoding="ascii") == "original"


def test_planner_uses_supplied_keyword_mesh_with_its_existing_density(tmp_path):
    source = tmp_path / "mesh.k"
    source.write_text(
        "*NODE\n1,0,0,0\n2,100,0,0\n3,100,50,0\n4,0,50,0\n"
        "*ELEMENT_SHELL\n11,7,1,2,3,4\n*END\n",
        encoding="ascii",
    )
    requirements = {key: value for key, value in PLATE.items() if key != "mesh_size_mm"}
    plan = call_planner(requirements, mesh_source_path=str(source))
    assert plan["status"] == "ready"
    assert plan["requirements"]["mesh_request"] == {
        "method": "auto", "unit_system": "mm_ms_g_N_MPa", "length_mm": 100,
        "width_mm": 50, "source_path": str(source),
    }
    configuration = next(task for task in plan["tasks"] if task.get("tool") == "configure_model")
    assert configuration["input"]["spec"]["mesh"] == {}


def test_missing_units_and_analysis_are_questions():
    plan = call_planner({**PLATE, "unit_system": None, "analysis": None})
    assert plan["status"] == "needs_input"
    assert {"unit_system", "analysis"} <= {item["field"] for item in plan["issues"]}
    assert not plan["tasks"]


def test_four_edge_clamped_solid_case_does_not_select_simply_supported_deck():
    plan = call_planner(
        {**PLATE, "model_type": "solid_plate", "support": "four_edges_clamped",
         "geometry": "square_plate", "analysis": "implicit"},
        text="实体方板四周固定，求固有频率",
    )
    assert plan["trace"]["case_status"] == "no_applicable_reference"
    assert plan["trace"]["case_id"] is None
    assert plan["status"] == "unsupported"
    assert not plan["tasks"]


def test_load_without_magnitude_requires_clarification():
    plan = call_planner({**PLATE, "load": "pressure"}, text="给壳板施加均布压力")
    assert plan["status"] == "needs_input"
    assert "load_magnitude" in {issue["field"] for issue in plan["issues"]}


def test_planner_does_not_ask_generator_to_silently_drop_requested_load():
    plan = call_planner({**PLATE, "load": "pressure", "load_magnitude": 1, "load_unit": "MPa"})
    assert plan["status"] == "unsupported"
    assert not plan["tasks"]


def test_requested_load_filters_case_retrieval():
    plan = call_planner(
        {**PLATE, "geometry": "annular_plate", "support": "simply_supported",
         "analysis": "implicit", "load": "pressure", "load_magnitude": 1, "load_unit": "MPa"},
        text="简支环形薄板加压力，求解隐式算例",
    )
    assert plan["trace"]["case_filters"]["excitation"] == "face_pressure"
    assert plan["trace"]["case_status"] == "no_applicable_reference"


def test_modal_case_evidence_does_not_claim_generator_support():
    plan = call_planner(
        {**PLATE, "width_mm": 100, "geometry": "square_plate", "support": "four_edges_clamped",
         "analysis": "modal"},
        text="薄壳方板四条边都夹紧，求固有频率",
    )
    assert plan["trace"]["case_id"] == "project.square_shell_four_edges_clamped"
    assert plan["status"] == "unsupported"
    assert not plan["tasks"]


def test_stale_lazy_vector_index_falls_back_to_exact(monkeypatch):
    class BrokenIndex(knowledge_vectors.VectorStore):
        def __init__(self, kb):
            pass

        def _index(self, name):
            raise FileNotFoundError("vector index missing")

        def embed(self, *args, **kwargs):
            return None

    planner._knowledge.cache_clear()
    monkeypatch.setattr(knowledge_vectors, "VectorStore", BrokenIndex)
    plan = call_planner(PLATE, semantic=True)
    assert plan["status"] == "ready"
    assert plan["trace"]["retrieval"] == "exact_and_tfidf_fallback"


def test_configured_classifier_accepts_a_text_only_mcp_request(monkeypatch):
    text = (
        "用 R12 建矩形弹性壳板，单位 mm、ms、g、N、MPa。左边固定，只建模不加载。"
        "长 100 mm、宽 50 mm、厚 2 mm，网格 10 mm。密度 0.00785 g/mm³，E 210000 MPa，泊松比 0.3。"
    )
    monkeypatch.setenv("LSDYNA_PLANNER_CLASSIFIER_URL", "http://127.0.0.1:9999/v1/chat/completions")
    monkeypatch.setenv("LSDYNA_PLANNER_CLASSIFIER_MODEL", "fixture")
    monkeypatch.delenv("LSDYNA_PLANNER_CLASSIFIER_API_KEY", raising=False)

    def classify(request, *, timeout):
        payload = json.loads(request.data)
        assert payload["messages"][-1] == {"role": "user", "content": text}
        result = {"choices": [{"message": {"content": json.dumps(PLATE)}}]}
        return io.BytesIO(json.dumps(result).encode())

    monkeypatch.setattr(planner, "urlopen", classify)
    plan = call_planner(None, text=text)
    assert plan["status"] == "ready"
    assert plan["trace"]["classification_source"] == "configured_classifier"


def test_new_plan_refuses_a_project_name_that_corrupts_the_title():
    plan = call_planner({**PLATE, "project_name": "plate\ninvalid title"})
    assert plan["status"] == "needs_input"
    assert any(issue["field"] == "project_name" for issue in plan["issues"])


def test_no_ready_plan_when_dimensions_round_to_zero_in_keyword_output():
    plan = call_planner({**PLATE, "length_mm": 1e-8, "thickness_mm": 1e-8})
    assert plan["status"] == "unsupported"
    assert not plan["tasks"]


EDIT = {"mode": "edit", "field": "youngs_modulus", "value": 205000, "unit": "MPa",
        "unit_system": "mm_ms_g_N_MPa", "part_id": 4}


@pytest.fixture
def shared_material_deck(tmp_path):
    root = tmp_path / "plate.k"
    material = tmp_path / "elastic.k"
    root.write_text(
        "*KEYWORD\n*INCLUDE\nelastic.k\n*PART\nfirst\n4,1,9\n"
        "*PART\nsecond\n5,1,9\n*END\n",
        encoding="ascii",
    )
    material.write_text("*MAT_ELASTIC_TITLE\nSteel\n9,0.00785,210000,0.30\n", encoding="ascii")
    return root, material


def test_edit_part_only_plans_clone_for_shared_material(shared_material_deck):
    root, material = shared_material_deck
    original = {path: path.read_bytes() for path in (root, material)}
    plan = call_planner(EDIT, deck_path=str(root), text="只把部件 4 的弹性模量改为 205000 MPa")

    assert plan["status"] == "ready"
    edit = plan["requirements"]["change"]
    assert edit["old_value"] == 210000
    assert edit["new_value"] == 205000
    assert edit["material"]["path"] == "elastic.k"
    assert edit["material"]["line"] == 3
    assert edit["affected_part_ids"] == [4]
    assert edit["referencing_part_ids"] == [4, 5]
    assert edit["operation"] == "clone_and_rebind"
    assert len(plan["trace"]["source_snapshot"]["files"]) == 2
    assert all(path.read_bytes() == content for path, content in original.items())


def test_shared_material_edit_asks_for_scope(shared_material_deck):
    root, _ = shared_material_deck
    request = {**EDIT, "part_id": None, "material_id": 9}
    plan = call_planner(request, deck_path=str(root))
    assert plan["status"] == "needs_input"
    assert any(issue["field"] == "part_id" for issue in plan["issues"])


def test_edit_rejects_unresolved_include(tmp_path):
    root = tmp_path / "plate.k"
    root.write_text("*KEYWORD\n*INCLUDE\nmissing.k\n*PART\nplate\n4,1,9\n*END\n", encoding="ascii")
    plan = call_planner(EDIT, deck_path=str(root))
    assert plan["status"] == "unsupported"
    assert not plan["tasks"]


def test_edit_reads_all_plain_include_rows(tmp_path):
    root = tmp_path / "plate.k"
    root.write_text("*KEYWORD\n*INCLUDE\nparts.k\nmaterial.k\n*END\n", encoding="ascii")
    (tmp_path / "parts.k").write_text("*PART\nplate\n4,1,9\n", encoding="ascii")
    (tmp_path / "material.k").write_text("*MAT_001\n         9   0.00785210000.000       0.3\n", encoding="ascii")
    plan = call_planner({**EDIT, "value": 205, "unit": "GPa"}, deck_path=str(root))
    assert plan["status"] == "ready", plan["issues"]
    assert plan["requirements"]["change"]["old_value"] == 210000
    assert plan["requirements"]["change"]["new_value"] == 205000
    assert len(plan["trace"]["source_snapshot"]["files"]) == 3


def test_edit_detects_conflicting_unit_marker(shared_material_deck):
    root, _ = shared_material_deck
    content = root.read_bytes().replace(b"*KEYWORD", b"*KEYWORD\r\n$ Unit system: SI_m_s_kg_N_Pa")
    root.write_bytes(content)
    plan = call_planner(EDIT, deck_path=str(root))
    assert plan["status"] == "needs_input"
    assert any(issue["field"] == "unit_system" for issue in plan["issues"])
