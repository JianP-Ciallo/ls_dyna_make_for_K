from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from io import BytesIO
import http.client
import threading
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

from lsprepost_mcp.paths import project_dir
from lsprepost_mcp.scene_prompts import (
    CUBE_LOAD_DEFAULTS,
    PLATE_PRESSURE_DEFAULTS,
    REBAR_HELMET_DEFAULTS,
    ROD_PLATE_DEFAULTS,
)
from lsprepost_mcp.web.app import MAX_REQUEST_BODY_BYTES, WebAppHandler, create_server, read_request_body
from lsprepost_mcp.web.http_utils import (
    ApiError,
    encode_json,
    json_error,
    json_ok,
    parse_json_body,
    safe_relative_path,
)
from lsprepost_mcp.web.scenes import web_scene_catalog
from lsprepost_mcp.web.solve_api import compare_lsdyna_payload


class WebApiHelperTests(unittest.TestCase):
    def test_json_ok_wraps_result(self) -> None:
        status, headers, body = json_ok({"name": "demo"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(json.loads(body.decode("utf-8")), {"ok": True, "result": {"name": "demo"}})

    def test_json_error_wraps_code_and_message(self) -> None:
        status, headers, body = json_error(400, "invalid_request", "request body must be a JSON object")
        self.assertEqual(status, 400)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        payload = json.loads(body.decode("utf-8"))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_request")
        self.assertEqual(payload["error"]["message"], "request body must be a JSON object")

    def test_parse_json_body_requires_object(self) -> None:
        self.assertEqual(parse_json_body(b'{"project_name":"demo"}'), {"project_name": "demo"})
        with self.assertRaises(ApiError) as raised:
            parse_json_body(b"[]")
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.code, "invalid_request")
        self.assertEqual(raised.exception.message, "request body must be a JSON object")

    def test_parse_json_body_rejects_nonstandard_numeric_constants(self) -> None:
        for value in (b"NaN", b"Infinity", b"-Infinity"):
            with self.subTest(value=value):
                with self.assertRaises(ApiError) as raised:
                    parse_json_body(b'{"value":' + value + b"}")
                self.assertEqual(raised.exception.status, 400)
                self.assertEqual(raised.exception.code, "invalid_json")

    def test_encode_json_preserves_unicode_and_uses_compact_separators(self) -> None:
        self.assertEqual(encode_json({"name": "演示"}), b'{"name":"\xe6\xbc\x94\xe7\xa4\xba"}')

    def test_safe_relative_path_accepts_simple_relative_paths(self) -> None:
        self.assertEqual(str(safe_relative_path("artifacts/result.png")).replace("\\", "/"), "artifacts/result.png")

    def test_safe_relative_path_rejects_empty_absolute_and_parent_paths(self) -> None:
        for raw in ("", "   ", "/tmp/file.png", "C:/tmp/file.png", "artifacts/../secret.txt"):
            with self.subTest(raw=raw):
                with self.assertRaises(ApiError) as raised:
                    safe_relative_path(raw)
                self.assertEqual(raised.exception.status, 400)
                self.assertEqual(raised.exception.code, "invalid_path")

    def test_safe_relative_path_rejects_drive_relative_paths(self) -> None:
        drive_relative_paths = (f"{'C'}:tmp/file.png", f"{'a'}:b")
        for raw in drive_relative_paths:
            with self.subTest(raw=raw):
                self.assertTrue(PureWindowsPath(raw).drive)
                with self.assertRaises(ApiError) as raised:
                    safe_relative_path(raw)
                self.assertEqual(raised.exception.status, 400)
                self.assertEqual(raised.exception.code, "invalid_path")


class WebSceneCatalogTests(unittest.TestCase):
    EXPECTED_SCENES = {
        "rebar_drop_on_helmet": REBAR_HELMET_DEFAULTS,
        "rod_impact_plate": ROD_PLATE_DEFAULTS,
        "cube_top_corner_load": CUBE_LOAD_DEFAULTS,
        "plate_pressure": PLATE_PRESSURE_DEFAULTS,
    }

    def test_scene_catalog_contains_controlled_scenes(self) -> None:
        catalog = web_scene_catalog()
        ids = {item["id"] for item in catalog["scenes"]}
        self.assertEqual(
            ids,
            {"rebar_drop_on_helmet", "rod_impact_plate", "cube_top_corner_load", "plate_pressure"},
        )

    def test_scene_fields_are_explicit_and_typed(self) -> None:
        catalog = web_scene_catalog()
        rebar = next(item for item in catalog["scenes"] if item["id"] == "rebar_drop_on_helmet")
        field_names = [field["name"] for field in rebar["fields"]]
        self.assertIn("rebar_length_m", field_names)
        self.assertIn("rebar_radius_m", field_names)
        self.assertIn("drop_height_m", field_names)
        self.assertIn("impact_velocity_m_per_s", field_names)
        self.assertIn("material_name", field_names)
        for field in rebar["fields"]:
            self.assertIn(field["kind"], {"number", "text", "select", "boolean"})

    def test_scene_fields_match_scene_prompt_defaults(self) -> None:
        catalog = web_scene_catalog()
        scenes = {item["id"]: item for item in catalog["scenes"]}
        self.assertEqual(set(scenes), set(self.EXPECTED_SCENES))
        for scene_id, defaults in self.EXPECTED_SCENES.items():
            with self.subTest(scene_id=scene_id):
                fields = scenes[scene_id]["fields"]
                fields_by_name = {field["name"]: field for field in fields}
                self.assertEqual(set(fields_by_name), set(defaults))
                for name, default in defaults.items():
                    self.assertEqual(fields_by_name[name]["default"], default)

    def test_scene_field_names_are_unique(self) -> None:
        catalog = web_scene_catalog()
        for scene in catalog["scenes"]:
            with self.subTest(scene_id=scene["id"]):
                field_names = [field["name"] for field in scene["fields"]]
                self.assertEqual(len(field_names), len(set(field_names)))

    def test_material_defaults_are_available_options(self) -> None:
        catalog = web_scene_catalog()
        for scene in catalog["scenes"]:
            with self.subTest(scene_id=scene["id"]):
                material = next(field for field in scene["fields"] if field["name"] == "material_name")
                self.assertEqual(material["kind"], "select")
                self.assertIn(material["default"], material["options"])

    def test_material_options_are_isolated_between_catalog_responses(self) -> None:
        catalog = web_scene_catalog()
        rebar = next(item for item in catalog["scenes"] if item["id"] == "rebar_drop_on_helmet")
        material = next(field for field in rebar["fields"] if field["name"] == "material_name")
        material["options"].append("mutated_material")

        fresh_catalog = web_scene_catalog()
        fresh_rebar = next(item for item in fresh_catalog["scenes"] if item["id"] == "rebar_drop_on_helmet")
        fresh_material = next(field for field in fresh_rebar["fields"] if field["name"] == "material_name")
        self.assertNotIn("mutated_material", fresh_material["options"])


@contextmanager
def web_test_server():
    server = create_server("127.0.0.1", 0, open_browser=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request_json(address, method: str, path: str, payload: dict | None = None):
    conn = http.client.HTTPConnection(address[0], address[1], timeout=10)
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=body, headers=headers)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, json.loads(data.decode("utf-8"))


def request_raw(address, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None):
    conn = http.client.HTTPConnection(address[0], address[1], timeout=10)
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    data = response.read()
    response_headers = dict(response.getheaders())
    conn.close()
    return response.status, response_headers, data


class WebSolveComparisonTests(unittest.TestCase):
    def test_three_phase14_projects_attach_and_persist_mesh_convergence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            projects = {
                name: root / name
                for name in ("coarse", "baseline", "fine")
            }
            for project in projects.values():
                project.mkdir()
            records = {
                name: {
                    "ok": True,
                    "status": "completed",
                    "project_name": name,
                    "run_id": f"run_{name}",
                }
                for name in projects
            }
            report = {
                "status": "converged",
                "convergence_verified": True,
                "checks": [
                    {"id": "all_phase14_plate_scenes", "ok": True}
                ],
                "projects": [
                    {
                        "project_name": "coarse",
                        "mesh_size_m": 0.015,
                        "run_id": "run_coarse",
                    },
                    {
                        "project_name": "baseline",
                        "mesh_size_m": 0.0125,
                        "run_id": "run_baseline",
                    },
                    {
                        "project_name": "fine",
                        "mesh_size_m": 0.010,
                        "run_id": "run_fine",
                    },
                ],
                "metric_comparisons": {},
            }

            with (
                patch(
                    "lsprepost_mcp.web.solve_api.find_project_dir",
                    side_effect=lambda name: projects[name],
                ),
                patch(
                    "lsprepost_mcp.web.solve_api.latest_lsdyna_run",
                    side_effect=lambda project: records[project.name],
                ),
                patch(
                    "lsprepost_mcp.web.solve_api.evaluate_phase14_mesh_convergence",
                    return_value=report,
                ),
            ):
                result = compare_lsdyna_payload(
                    {"project_names": ["coarse", "baseline", "fine"]}
                )

            self.assertEqual(report, result["mmale_mesh_convergence"])
            artifact = (
                projects["fine"]
                / "artifacts"
                / "mmale_mesh_convergence.json"
            )
            self.assertTrue(artifact.is_file())
            self.assertEqual(
                report,
                json.loads(artifact.read_text(encoding="utf-8")),
            )

    def test_two_project_comparison_keeps_existing_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            projects = {name: root / name for name in ("left", "right")}
            for project in projects.values():
                project.mkdir()
            records = {
                name: {
                    "ok": True,
                    "status": "completed",
                    "project_name": name,
                    "run_id": f"run_{name}",
                }
                for name in projects
            }

            with (
                patch(
                    "lsprepost_mcp.web.solve_api.find_project_dir",
                    side_effect=lambda name: projects[name],
                ),
                patch(
                    "lsprepost_mcp.web.solve_api.latest_lsdyna_run",
                    side_effect=lambda project: records[project.name],
                ),
                patch(
                    "lsprepost_mcp.web.solve_api.evaluate_phase14_mesh_convergence"
                ) as evaluate,
            ):
                result = compare_lsdyna_payload(
                    {"project_names": ["left", "right"]}
                )

            self.assertNotIn("mmale_mesh_convergence", result)
            evaluate.assert_not_called()


class WebServerRouteTests(unittest.TestCase):
    def test_server_info_route_returns_tool_result(self) -> None:
        with web_test_server() as address:
            status, payload = request_json(address, "GET", "/api/server-info")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["name"], "lsprepost-mcp")

    def test_create_server_rejects_non_local_host(self) -> None:
        with self.assertRaises(ValueError) as raised:
            create_server("0.0.0.0", 0, open_browser=False)
        self.assertIn("host must be localhost or 127.0.0.1", str(raised.exception))

    def test_scenes_route_returns_catalog(self) -> None:
        with web_test_server() as address:
            status, payload = request_json(address, "GET", "/api/scenes")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(len(payload["result"]["scenes"]), 4)

    def test_unknown_route_returns_json_404(self) -> None:
        with web_test_server() as address:
            status, payload = request_json(address, "GET", "/api/missing")
        self.assertEqual(status, 404)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_scene_resolve_rejects_text_plain(self) -> None:
        with web_test_server() as address:
            status, headers, data = request_raw(
                address,
                "POST",
                "/api/scene/resolve",
                body=b'{"scene_id":"plate_pressure"}',
                headers={"Content-Type": "text/plain"},
            )
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(status, 415)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "unsupported_media_type")

    def test_post_rejection_discards_bounded_body_before_response(self) -> None:
        body = b'{"scene_id":"plate_pressure"}'
        fake_handler = type(
            "FakeHandler",
            (),
            {
                "headers": {
                    "Content-Type": "text/plain",
                    "Content-Length": str(len(body)),
                },
                "rfile": BytesIO(body),
            },
        )()
        with self.assertRaises(ApiError) as raised:
            WebAppHandler.handle_api_post(fake_handler, "/api/scene/resolve")
        self.assertEqual(raised.exception.code, "unsupported_media_type")
        self.assertEqual(fake_handler.rfile.tell(), len(body))

    def test_forbidden_host_discards_bounded_post_body_before_response(self) -> None:
        body = b'{"scene_id":"plate_pressure"}'
        fake_handler = type(
            "FakeHandler",
            (),
            {
                "path": "/api/scene/resolve",
                "headers": {
                    "Host": "evil.example:8765",
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                },
                "rfile": BytesIO(body),
                "wfile": BytesIO(),
                "command": "POST",
                "send_response": lambda self, status: setattr(self, "status", status),
                "send_header": lambda self, key, value: None,
                "end_headers": lambda self: None,
            },
        )()

        WebAppHandler.handle_request(fake_handler, "POST")

        self.assertEqual(fake_handler.status, 403)
        self.assertEqual(fake_handler.rfile.tell(), len(body))

    def test_read_request_body_rejects_oversized_payload_before_reading(self) -> None:
        fake_handler = type(
            "FakeHandler",
            (),
            {
                "headers": {"Content-Length": str(MAX_REQUEST_BODY_BYTES + 1)},
                "rfile": BytesIO(b"{}"),
            },
        )()
        with self.assertRaises(ApiError) as raised:
            read_request_body(fake_handler)
        self.assertEqual(raised.exception.status, 413)
        self.assertEqual(raised.exception.code, "request_too_large")
        self.assertEqual(fake_handler.rfile.tell(), 0)

    def test_scene_resolve_rejects_forbidden_origin(self) -> None:
        with web_test_server() as address:
            status, headers, data = request_raw(
                address,
                "POST",
                "/api/scene/resolve",
                body=b'{"scene_id":"plate_pressure"}',
                headers={"Content-Type": "application/json", "Origin": "http://evil.example"},
            )
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(status, 403)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "forbidden_origin")

    def test_api_rejects_dns_rebinding_host_even_when_origin_matches(self) -> None:
        with web_test_server() as address:
            port = address[1]
            status, _headers, data = request_raw(
                address,
                "POST",
                "/api/scene/resolve",
                body=b'{"scene_id":"plate_pressure"}',
                headers={
                    "Content-Type": "application/json",
                    "Host": f"evil.example:{port}",
                    "Origin": f"http://evil.example:{port}",
                },
            )
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(status, 403)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "forbidden_host")

    def test_get_api_rejects_dns_rebinding_host(self) -> None:
        with web_test_server() as address:
            port = address[1]
            status, _headers, data = request_raw(
                address,
                "GET",
                "/api/server-info",
                headers={"Host": f"evil.example:{port}"},
            )
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(status, 403)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "forbidden_host")

    def test_scene_resolve_rejects_https_origin_for_http_host(self) -> None:
        with web_test_server() as address:
            port = address[1]
            status, _headers, data = request_raw(
                address,
                "POST",
                "/api/scene/resolve",
                body=b'{"scene_id":"plate_pressure"}',
                headers={
                    "Content-Type": "application/json",
                    "Host": f"localhost:{port}",
                    "Origin": f"https://localhost:{port}",
                },
            )
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(status, 403)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "forbidden_origin")

    def test_scene_resolve_rejects_localhost_origin_for_127_host(self) -> None:
        with web_test_server() as address:
            port = address[1]
            status, _headers, data = request_raw(
                address,
                "POST",
                "/api/scene/resolve",
                body=b'{"scene_id":"plate_pressure"}',
                headers={
                    "Content-Type": "application/json",
                    "Host": f"127.0.0.1:{port}",
                    "Origin": f"http://localhost:{port}",
                },
            )
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(status, 403)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "forbidden_origin")

    def test_scene_resolve_allows_same_origin_to_reach_route(self) -> None:
        with web_test_server() as address:
            port = address[1]
            status, _headers, data = request_raw(
                address,
                "POST",
                "/api/scene/resolve",
                body=b'{"scene_id":"plate_pressure"}',
                headers={
                    "Content-Type": "application/json",
                    "Host": f"127.0.0.1:{port}",
                    "Origin": f"http://127.0.0.1:{port}",
                },
            )
        payload = json.loads(data.decode("utf-8"))
        self.assertNotEqual((status, payload.get("error", {}).get("code")), (403, "forbidden_origin"))

    def test_api_without_trailing_slash_returns_json_404(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "index.html").write_text("<!doctype html>", encoding="utf-8")
            with patch("lsprepost_mcp.web.app.static_root", return_value=Path(temp_dir)):
                with web_test_server() as address:
                    status, headers, data = request_raw(address, "GET", "/api")
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(status, 404)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_missing_static_asset_with_suffix_returns_404(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "index.html").write_text("<!doctype html>", encoding="utf-8")
            with patch("lsprepost_mcp.web.app.static_root", return_value=Path(temp_dir)):
                with web_test_server() as address:
                    status, _headers, _data = request_raw(address, "GET", "/missing.js")
        self.assertEqual(status, 404)


class WebArtifactTests(unittest.TestCase):
    def test_artifact_route_serves_project_relative_preview_png(self) -> None:
        project = project_dir("unit_web_artifact")
        if project.exists():
            shutil.rmtree(project)
        try:
            artifact = project / "artifacts" / "preview.png"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"\x89PNG\r\n\x1a\nunit")

            with web_test_server() as address:
                status, headers, body = request_raw(
                    address,
                    "GET",
                    "/api/artifact?project_name=unit_web_artifact&relative_path=artifacts/preview.png",
                )

            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], "image/png")
            self.assertEqual(headers["Content-Length"], str(len(body)))
            self.assertTrue(body.startswith(b"\x89PNG\r\n\x1a\n"))
        finally:
            if project.exists():
                shutil.rmtree(project)

    def test_artifact_route_rejects_path_escape(self) -> None:
        with web_test_server() as address:
            status, payload = request_json(
                address,
                "GET",
                "/api/artifact?project_name=unit_web_artifact&relative_path=../model.k",
            )
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_path")


if __name__ == "__main__":
    unittest.main()
