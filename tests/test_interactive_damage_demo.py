"""Only synthetic small meshes; never launch a solver or read a real d3plot."""
import copy
import hashlib
import importlib
import json

import pytest


def api():
    return importlib.import_module("lsprepost_mcp.web.damage_demo_api")


def payload():
    return {"schema_version": "lsprepost_mcp.synthetic_damage_request@1", "mode": "complete",
            "sources": [{"position_m": [-6, -4, 2], "equivalent_kg": 100}]}


def test_scene_has_three_floors_separate_components_and_ground():
    scene = api().scene_payload()
    assert {c["floor"] for c in scene["components"] if c["role"] != "ground"} == {1, 2, 3}
    assert {c["role"] for c in scene["components"]} >= {"column", "beam", "slab", "wall", "ground"}
    assert len({c["part_id"] for c in scene["components"]}) == len(scene["components"])
    assert all(p["nodes"] and p["faces"] for p in scene["mesh"]["parts"])


def test_real_evaluator_seals_repeatable_synthetic_artifacts():
    first = api().evaluate_demo(payload())
    second = api().evaluate_demo(payload())
    assert first["synthetic_demo"] is True
    assert first["snapshot"] == second["snapshot"]
    assert first["snapshot"]["overall"]["gate"] == "provisional"
    assert first["snapshot"]["building"]["severity"] is not None
    assert first["snapshot"]["ground"]["severity"] is not None
    assert first["snapshot"]["adapter"]["id"] == "synthetic_demo"
    assert len(first["artifacts"]) == 8
    for name, artifact in first["artifacts"].items():
        assert hashlib.sha256(artifact["text"].encode("utf-8")).hexdigest() == artifact["sha256"], name
    assert json.loads(first["artifacts"]["assessment_snapshot.json"]["text"]) == first["snapshot"]
    assert "synthetic-demo" in first["artifacts"]["damage_report.html"]["text"]


@pytest.mark.parametrize("change", ["x", "y", "height", "quantity", "count"])
def test_each_source_control_changes_actual_response_metrics(change):
    original = payload()
    changed = copy.deepcopy(original)
    if change == "count":
        changed["sources"].append({"position_m": [7, 6, 4], "equivalent_kg": 200})
    elif change == "quantity":
        changed["sources"][0]["equivalent_kg"] = 900
    else:
        changed["sources"][0]["position_m"][{"x": 0, "y": 1, "height": 2}[change]] += 5
    before, after = (api().evaluate_demo(p)["snapshot"] for p in (original, changed))
    assert before["assessment_fingerprint"] != after["assessment_fingerprint"]
    assert [c["p99_relative_deformation"] for c in before["building"]["components"]] != [
        c["p99_relative_deformation"] for c in after["building"]["components"]]


def test_partial_and_blocked_modes_use_real_gates_not_zero_grades():
    partial = api().evaluate_demo({**payload(), "mode": "partial"})["snapshot"]
    assert partial["building"]["gate"] == "provisional"
    assert partial["ground"]["gate"] == "blocked"
    assert partial["ground"]["severity"] is None
    blocked = api().evaluate_demo({**payload(), "mode": "blocked"})["snapshot"]
    for key in ("overall", "building", "ground"):
        assert blocked[key]["gate"] == "blocked"
        assert blocked[key]["severity"] is None


def test_complete_demo_exercises_nonzero_ground_geometry_and_stable_tail():
    result = api().evaluate_demo(payload())["snapshot"]
    assert result["ground"]["final"]["crater"]["maximum_depth"] > 0
    assert result["ground"]["final"]["crater"]["affected_cell_count"] > 0
    assert result["ground"]["stability"]["stable"] is True


@pytest.mark.parametrize("bad", [
    {"sources": []}, {"sources": [payload()["sources"][0]] * 6},
    {"mode": "formal"}, {"result_dir": "E:/real-project"},
    {"sources": [{"position_m": [0, 0, -1], "equivalent_kg": 10}]},
    {"sources": [{"position_m": [0, 0, float("nan")], "equivalent_kg": 10}]},
    {"sources": [{"position_m": [0, 0, 1], "equivalent_kg": True}]},
    {"sources": [{"position_m": [0, 0, 1], "equivalent_kg": 0}]},
    {"sources": [{"position_m": [0, 0, 1], "equivalent_kg": 10**400}]},
    {"sources": [{"position_m": [0, 0, 1], "equivalent_kg": 10, "project_id": "real"}]},
])
def test_closed_input_rejects_invalid_or_real_project_data(bad):
    with pytest.raises(ValueError):
        api().evaluate_demo({**payload(), **bad})


def test_demo_http_runs_only_closed_synthetic_request():
    from test_phase18f_api import _web_server, _request, _post
    with _web_server() as address:
        status, body = _request(address, "/api/damage-assessment/demo/scene")
        assert status == 200
        assert body["result"]["synthetic_demo"] is True
        status, body = _post(address, "/api/damage-assessment/demo/evaluate", payload())
        assert status == 200
        assert body["result"]["snapshot"]["identity"]["project_id"] == "synthetic-demo-only"
        assert _post(address, "/api/damage-assessment/demo/evaluate?project_id=real", payload())[0] == 400
        assert _request(address, "/api/damage-assessment/demo/scene?project_id=real")[0] == 400
        assert _post(address, "/api/damage-assessment/demo/evaluate", {**payload(), "project_id": "real"})[0] == 400


def test_demo_http_rejects_cross_origin():
    import http.client
    from test_phase18f_api import _web_server
    with _web_server() as address:
        connection = http.client.HTTPConnection(*address, timeout=10)
        connection.request("POST", "/api/damage-assessment/demo/evaluate", body=json.dumps(payload()),
                           headers={"Content-Type": "application/json", "Origin": "https://untrusted.example"})
        response = connection.getresponse()
        response.read()
        connection.close()
        assert response.status == 403


def test_missing_optional_dependency_is_actionable_and_releases_lock(monkeypatch):
    import sys
    from lsprepost_mcp.web.http_utils import ApiError
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "blast_damage_assessment.api", None)
        with pytest.raises(ApiError) as error:
            api().evaluate_demo(payload())
        assert error.value.status == 503
    assert api().evaluate_demo(payload())["synthetic_demo"] is True
