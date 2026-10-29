"""Preserve historic evidence and verify its interactive replacement in isolation."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess

import pytest
from node_runtime import node_executable
from test_phase18f_api import _web_server

ROOT = Path(__file__).resolve().parents[1]


def test_demo_local_field_tracks_sources_and_keeps_missing_data_gray():
    result = subprocess.run(
        [str(node_executable()), str(ROOT / "web/tests/damage-demo-field.runtime.cjs")],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_demo_serves_matching_geometry_and_report_without_optional_assessor():
    with _web_server() as address:
        def get(path):
            connection = http.client.HTTPConnection(*address, timeout=15)
            connection.request("GET", path)
            response = connection.getresponse()
            body = response.read()
            connection.close()
            assert response.status == 200, (path, response.status)
            return body

        get("/damage_assessment_demo.html")
        bundle = json.loads(get("/demos/residential-assessment.json"))
        snapshot = bundle["snapshot"]
        assert snapshot["identity"]["case_id"] == "residential"
        assert snapshot["assessment_id"] == "812442014c82b3ceaaaf37a6"
        assert snapshot["building"]["severity"] == 0
        assert snapshot["ground"]["severity"] == 0
        assert snapshot["overall"]["gate"] == "provisional"
        assert bundle["model_sha256"] == next(s["sha256"] for s in snapshot["sources"] if s["relative_path"] == "model.k")
        assert bundle["model_sha256"] == "74418ea174d67bd7d4d781980d45a3c979373d97000158ce4649667cc6c438b9"
        mesh = bundle["mesh"]
        assert any(p["part_id"] == 8001 and p["faces"] for p in mesh["parts"])
        assert any(p["part_id"] == 1011 and p["faces"] for p in mesh["parts"])
        assert not any(p["part_id"] == 9001 for p in mesh["parts"]), "Air must not obscure the building"
        for part in mesh["parts"]:
            assert part["nodes"] and part["faces"]
            assert all(0 <= i < len(part["nodes"]) for face in part["faces"] for i in face)
        report = get("/demos/residential-damage-report.html")
        assert hashlib.sha256(report).hexdigest() == bundle["report_sha256"]
        assert snapshot["assessment_id"] in report.decode("utf-8")


def test_demo_browser_is_isolated_and_restores_project(tmp_path):
    modules = os.environ.get("LSPREPOST_MCP_PLAYWRIGHT_ROOT")
    if not modules:
        pytest.skip("Set LSPREPOST_MCP_PLAYWRIGHT_ROOT to run real Edge/WebGL checks")
    with _web_server() as address:
        result = subprocess.run(
            [str(node_executable()), str(ROOT / "web/tests/damage-assessment-demo.browser.cjs"),
             modules, f"http://{address[0]}:{address[1]}", str(tmp_path)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
    assert result.returncode == 0, result.stdout + result.stderr
