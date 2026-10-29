# Phase 11 Local Web App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a portable local Web App entry point that lets users select controlled LS-DYNA scenes, fill parameters, generate projects through the existing backend, view validation/preview results, and open LS-PrePost for troubleshooting.

**Architecture:** Phase 11 uses a lightweight Python Web shell. The Web backend runs on localhost with Python standard library HTTP primitives and calls existing `lsprepost_mcp.tool_*` functions directly. Static UI serving prefers a React/Vite build artifact when present and falls back to built-in plain HTML/CSS/JS when Node.js or build output is unavailable.

**Tech Stack:** Python standard library `http.server`, existing `lsprepost_mcp` tool modules, PowerShell startup scripts, optional React/Vite source scaffolding, built-in fallback HTML/CSS/JS, `unittest`.

---

## File Structure

Create:

- `lsprepost_mcp/web/__init__.py`
  - Package marker for the local Web App.
- `lsprepost_mcp/web/scenes.py`
  - Web-facing scene metadata for supported controlled scenes and form fields.
- `lsprepost_mcp/web/http_utils.py`
  - Small helpers for JSON request/response handling, path normalization, and API error envelopes.
- `lsprepost_mcp/web/app.py`
  - Local HTTP server, API routing, static file routing, and CLI entry point.
- `lsprepost_mcp/web/static/index.html`
  - Built-in fallback Web UI.
- `lsprepost_mcp/web/static/styles.css`
  - Built-in fallback Web UI styles.
- `lsprepost_mcp/web/static/app.js`
  - Built-in fallback Web UI behavior and API calls.
- `web/package.json`
  - Optional React/Vite development metadata.
- `web/index.html`
  - Optional React/Vite app shell.
- `web/src/main.jsx`
  - Optional React/Vite entry.
- `web/src/App.jsx`
  - Optional React/Vite app.
- `scripts/start_web_app.ps1`
  - Portable startup script for users and AI IDEs.
- `tests/test_web_api.py`
  - Backend API tests using an in-process local HTTP server.
- `tests/test_web_static.py`
  - Static/fallback UI and asset safety tests.
- `tests/test_web_startup.py`
  - PowerShell startup and packaging integration tests.

Modify:

- `scripts/doctor.ps1`
  - Add Web App file checks and optional Node.js check.
- `scripts/pack.ps1`
  - Ensure Phase 11 Web App files are included and runtime build artifacts are handled safely.
- `scripts/run_test_matrix.ps1`
  - Add a `web` test group.
- `README.zh-CN.md`
  - Document local Web App usage after implementation.
- `README.md`
  - Add English summary for local Web App usage after implementation.
- `AI_IDE_START_HERE.zh-CN.md`
  - Mention Web App entry as an alternative to MCP/AI IDE usage.

Do not modify:

- Existing keyword generation internals unless a failing Web API test proves a narrow adapter is required.
- Existing LS-PrePost launcher/runtime safety mechanisms.
- Existing MCP tool schema semantics.

## API Contract

All API responses must be JSON.

Successful response envelope:

```json
{
  "ok": true,
  "result": {}
}
```

Error response envelope:

```json
{
  "ok": false,
  "error": {
    "code": "invalid_request",
    "message": "request body must be a JSON object"
  }
}
```

Required endpoints:

- `GET /api/server-info`
  - Calls `tool_server_info({})`.
- `GET /api/scenes`
  - Returns supported scene templates and form field metadata.
- `GET /api/projects`
  - Calls `tool_list_projects({"include_archived": true})`.
- `GET /api/project?project_name=name`
  - Calls `tool_read_project`.
- `POST /api/scene/resolve`
  - Calls `tool_generate_scene_from_prompt` with `dry_run=true`.
- `POST /api/scene/generate`
  - Calls `tool_generate_scene_from_prompt` with controlled preview flags.
- `POST /api/model/generate`
  - Calls `tool_generate_model`.
- `POST /api/project/validate`
  - Calls `tool_validate_model`.
- `POST /api/project/preview-gif`
  - Calls `tool_export_preview_gif`.
- `POST /api/project/open-lsprepost`
  - Calls `tool_open_in_lsprepost`.
- `GET /api/artifact?project_name=name&relative_path=artifacts/file.png`
  - Serves only `.png`, `.gif`, `.json`, `.txt`, and `.xml` files inside the resolved project directory.

Do not add an endpoint that accepts arbitrary cfile text or arbitrary filesystem paths.

## Task 1: Web Package Skeleton And JSON Helpers

**Files:**
- Create: `lsprepost_mcp/web/__init__.py`
- Create: `lsprepost_mcp/web/http_utils.py`
- Create: `tests/test_web_api.py`

- [ ] **Step 1: Write failing tests for JSON helpers**

Add this initial content to `tests/test_web_api.py`:

```python
from __future__ import annotations

import json
import unittest

from lsprepost_mcp.web.http_utils import ApiError, json_error, json_ok, parse_json_body


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
            parse_json_body(b'[]')
        self.assertEqual(raised.exception.code, "invalid_request")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m unittest tests.test_web_api
```

Expected result: import failure for `lsprepost_mcp.web.http_utils`.

- [ ] **Step 3: Add package marker**

Create `lsprepost_mcp/web/__init__.py`:

```python
from __future__ import annotations
```

- [ ] **Step 4: Add JSON helper implementation**

Create `lsprepost_mcp/web/http_utils.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from lsprepost_mcp.config import JSONDict


@dataclass
class ApiError(Exception):
    status: int
    code: str
    message: str


def encode_json(payload: JSONDict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def json_ok(result: JSONDict, status: int = 200) -> tuple[int, dict[str, str], bytes]:
    return status, {"Content-Type": "application/json; charset=utf-8"}, encode_json({"ok": True, "result": result})


def json_error(status: int, code: str, message: str) -> tuple[int, dict[str, str], bytes]:
    return status, {"Content-Type": "application/json; charset=utf-8"}, encode_json(
        {"ok": False, "error": {"code": code, "message": message}}
    )


def parse_json_body(body: bytes) -> JSONDict:
    try:
        payload: Any = json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise ApiError(400, "invalid_json", f"request body is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ApiError(400, "invalid_request", "request body must be a JSON object")
    return payload


def safe_relative_path(raw: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ApiError(400, "invalid_path", "relative_path is required")
    normalized = Path(unquote(raw).replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ApiError(400, "invalid_path", "relative_path must stay inside the project")
    return normalized
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```powershell
python -m unittest tests.test_web_api
```

Expected result: `Ran 3 tests ... OK`.

- [ ] **Step 6: Commit**

```powershell
git add lsprepost_mcp/web/__init__.py lsprepost_mcp/web/http_utils.py tests/test_web_api.py
git commit -m "feat: add web api json helpers"
```

## Task 2: Web Scene Metadata

**Files:**
- Create: `lsprepost_mcp/web/scenes.py`
- Modify: `tests/test_web_api.py`

- [ ] **Step 1: Add failing tests for scene metadata**

Append to `tests/test_web_api.py`:

```python
from lsprepost_mcp.web.scenes import web_scene_catalog


class WebSceneCatalogTests(unittest.TestCase):
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
        self.assertIn("material_name", field_names)
        for field in rebar["fields"]:
            self.assertIn(field["kind"], {"number", "text", "select", "boolean"})
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m unittest tests.test_web_api
```

Expected result: import failure for `lsprepost_mcp.web.scenes`.

- [ ] **Step 3: Implement scene catalog**

Create `lsprepost_mcp/web/scenes.py`:

```python
from __future__ import annotations

from lsprepost_mcp.config import JSONDict
from lsprepost_mcp.scene_prompts import (
    CUBE_LOAD_DEFAULTS,
    PLATE_PRESSURE_DEFAULTS,
    REBAR_HELMET_DEFAULTS,
    ROD_PLATE_DEFAULTS,
)


def number_field(name: str, label: str, unit: str, default: float) -> JSONDict:
    return {"name": name, "label": label, "kind": "number", "unit": unit, "default": default}


def material_field(default: str = "mild_steel") -> JSONDict:
    return {
        "name": "material_name",
        "label": "Material",
        "kind": "select",
        "default": default,
        "options": ["mild_steel", "aluminum_6061_t6", "rubber_generic"],
    }


def web_scene_catalog() -> JSONDict:
    return {
        "scenes": [
            {
                "id": "rebar_drop_on_helmet",
                "title": "Rebar free-fall impact on helmet",
                "summary": "A vertical solid rebar drops onto a fixed ellipsoid helmet shell.",
                "fields": [
                    number_field("rebar_length_m", "Rebar length", "m", REBAR_HELMET_DEFAULTS["rebar_length_m"]),
                    number_field("rebar_radius_m", "Rebar radius", "m", REBAR_HELMET_DEFAULTS["rebar_radius_m"]),
                    number_field("drop_height_m", "Drop height", "m", REBAR_HELMET_DEFAULTS["drop_height_m"]),
                    material_field(REBAR_HELMET_DEFAULTS["material_name"]),
                ],
            },
            {
                "id": "rod_impact_plate",
                "title": "Rod impact on plate",
                "summary": "A solid cylinder rod impacts a fixed steel plate.",
                "fields": [
                    number_field("rod_length_m", "Rod length", "m", ROD_PLATE_DEFAULTS["rod_length_m"]),
                    number_field("rod_radius_m", "Rod radius", "m", ROD_PLATE_DEFAULTS["rod_radius_m"]),
                    number_field(
                        "impact_velocity_m_per_s",
                        "Impact velocity",
                        "m/s",
                        ROD_PLATE_DEFAULTS["impact_velocity_m_per_s"],
                    ),
                    number_field("plate_length_m", "Plate length", "m", ROD_PLATE_DEFAULTS["plate_length_m"]),
                    number_field("plate_width_m", "Plate width", "m", ROD_PLATE_DEFAULTS["plate_width_m"]),
                    number_field(
                        "plate_thickness_m",
                        "Plate thickness",
                        "m",
                        ROD_PLATE_DEFAULTS["plate_thickness_m"],
                    ),
                    material_field(ROD_PLATE_DEFAULTS["material_name"]),
                ],
            },
            {
                "id": "cube_top_corner_load",
                "title": "Cube with top corner loads",
                "summary": "A fixed cube receives downward nodal loads at four top corners.",
                "fields": [
                    number_field("cube_length_m", "Cube length", "m", CUBE_LOAD_DEFAULTS["cube_length_m"]),
                    number_field("cube_width_m", "Cube width", "m", CUBE_LOAD_DEFAULTS["cube_width_m"]),
                    number_field("cube_height_m", "Cube height", "m", CUBE_LOAD_DEFAULTS["cube_height_m"]),
                    number_field("corner_force_n", "Corner force", "N", CUBE_LOAD_DEFAULTS["corner_force_n"]),
                    material_field(CUBE_LOAD_DEFAULTS["material_name"]),
                ],
            },
            {
                "id": "plate_pressure",
                "title": "Plate under pressure",
                "summary": "A shell plate with fixed boundary receives uniform pressure.",
                "fields": [
                    number_field("plate_length_m", "Plate length", "m", PLATE_PRESSURE_DEFAULTS["plate_length_m"]),
                    number_field("plate_width_m", "Plate width", "m", PLATE_PRESSURE_DEFAULTS["plate_width_m"]),
                    number_field(
                        "plate_thickness_m",
                        "Plate thickness",
                        "m",
                        PLATE_PRESSURE_DEFAULTS["plate_thickness_m"],
                    ),
                    number_field("pressure_pa", "Pressure", "Pa", PLATE_PRESSURE_DEFAULTS["pressure_pa"]),
                    material_field(PLATE_PRESSURE_DEFAULTS["material_name"]),
                ],
            },
        ]
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python -m unittest tests.test_web_api
```

Expected result: helper and scene catalog tests pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/web/scenes.py tests/test_web_api.py
git commit -m "feat: add web scene catalog"
```

## Task 3: Local HTTP Server And Core API Routes

**Files:**
- Create: `lsprepost_mcp/web/app.py`
- Modify: `tests/test_web_api.py`

- [ ] **Step 1: Add failing tests for server routes**

Append to `tests/test_web_api.py`:

```python
import http.client
import threading
from contextlib import contextmanager

from lsprepost_mcp.web.app import create_server


@contextmanager
def web_test_server():
    server = create_server("127.0.0.1", 0, open_browser=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
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


class WebServerRouteTests(unittest.TestCase):
    def test_server_info_route_returns_tool_result(self) -> None:
        with web_test_server() as address:
            status, payload = request_json(address, "GET", "/api/server-info")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["name"], "lsprepost-mcp")

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
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m unittest tests.test_web_api
```

Expected result: import failure for `lsprepost_mcp.web.app`.

- [ ] **Step 3: Implement HTTP server skeleton**

Create `lsprepost_mcp/web/app.py`:

```python
from __future__ import annotations

import argparse
import mimetypes
import os
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from lsprepost_mcp.config import JSONDict, ROOT
from lsprepost_mcp.paths import find_project_dir
from lsprepost_mcp.tool_generation import tool_generate_model, tool_generate_scene_from_prompt
from lsprepost_mcp.tool_lsprepost import tool_export_preview_gif, tool_open_in_lsprepost
from lsprepost_mcp.tool_project import tool_list_projects, tool_read_project, tool_validate_model
from lsprepost_mcp.tool_server import tool_server_info
from lsprepost_mcp.web.http_utils import ApiError, json_error, json_ok, parse_json_body, safe_relative_path
from lsprepost_mcp.web.scenes import web_scene_catalog


class WebAppServer(ThreadingHTTPServer):
    allow_reuse_address = True


def static_root() -> Path:
    built = ROOT / "web" / "dist"
    if (built / "index.html").exists():
        return built
    return Path(__file__).resolve().parent / "static"


def read_request_body(handler: BaseHTTPRequestHandler) -> bytes:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    return handler.rfile.read(length) if length > 0 else b"{}"


def send_tuple(handler: BaseHTTPRequestHandler, response: tuple[int, dict[str, str], bytes]) -> None:
    status, headers, body = response
    handler.send_response(status)
    for key, value in headers.items():
        handler.send_header(key, value)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def query_value(query: dict[str, list[str]], name: str) -> str:
    values = query.get(name) or []
    return values[0] if values else ""


class WebAppHandler(BaseHTTPRequestHandler):
    server_version = "lsprepost-mcp-web/0.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        self.handle_request("GET")

    def do_POST(self) -> None:
        self.handle_request("POST")

    def handle_request(self, method: str) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/"):
                result = self.route_api(method, parsed.path, parse_qs(parsed.query))
                if result is not None:
                    send_tuple(self, json_ok(result))
            else:
                self.serve_static(parsed.path)
        except ApiError as exc:
            send_tuple(self, json_error(exc.status, exc.code, exc.message))
        except Exception as exc:
            send_tuple(self, json_error(500, "internal_error", str(exc)))

    def route_api(self, method: str, path: str, query: dict[str, list[str]]) -> JSONDict | None:
        if method == "GET" and path == "/api/server-info":
            return tool_server_info({})
        if method == "GET" and path == "/api/scenes":
            return web_scene_catalog()
        if method == "GET" and path == "/api/projects":
            return tool_list_projects({"include_archived": True})
        if method == "GET" and path == "/api/project":
            return tool_read_project({"project_name": query_value(query, "project_name")})
        if method == "GET" and path == "/api/artifact":
            raise ApiError(501, "not_implemented", "artifact serving is implemented in Task 4")
        if method == "POST":
            body = parse_json_body(read_request_body(self))
            if path == "/api/scene/resolve":
                return tool_generate_scene_from_prompt({**body, "dry_run": True})
            if path == "/api/scene/generate":
                return tool_generate_scene_from_prompt(body)
            if path == "/api/model/generate":
                return tool_generate_model(body)
            if path == "/api/project/validate":
                return tool_validate_model(body)
            if path == "/api/project/preview-gif":
                return tool_export_preview_gif(body)
            if path == "/api/project/open-lsprepost":
                return tool_open_in_lsprepost(body)
        raise ApiError(404, "not_found", f"route not found: {method} {path}")

    def serve_static(self, request_path: str) -> None:
        root = static_root()
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        target = (root / relative).resolve()
        if root.resolve() != target and root.resolve() not in target.parents:
            raise ApiError(404, "not_found", "static file not found")
        if not target.exists() or not target.is_file():
            target = root / "index.html"
        data = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def create_server(host: str, port: int, open_browser: bool = False) -> WebAppServer:
    server = WebAppServer((host, port), WebAppHandler)
    if open_browser:
        webbrowser.open(f"http://{host}:{server.server_address[1]}")
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--lspp-exe", default="")
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args(argv)
    if args.lspp_exe:
        os.environ["LSPP_EXE"] = args.lspp_exe
    server = create_server(args.host, args.port, open_browser=args.open_browser)
    print(f"lsprepost-mcp web app: http://{args.host}:{server.server_address[1]}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m unittest tests.test_web_api
```

Expected result: tests pass except static route tests that are introduced later.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/web/app.py tests/test_web_api.py
git commit -m "feat: add local web api server"
```

## Task 4: Artifact Serving And Project Action Safety

**Files:**
- Modify: `lsprepost_mcp/web/app.py`
- Modify: `tests/test_web_api.py`

- [ ] **Step 1: Add failing artifact safety tests**

Append to `tests/test_web_api.py`:

```python
from pathlib import Path
import shutil

from lsprepost_mcp.paths import project_dir


class WebArtifactTests(unittest.TestCase):
    def test_artifact_route_serves_only_project_relative_files(self) -> None:
        project = project_dir("unit_web_artifact")
        if project.exists():
            shutil.rmtree(project)
        try:
            artifact = project / "artifacts" / "preview.png"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"\x89PNG\r\n\x1a\nunit")
            with web_test_server() as address:
                conn = http.client.HTTPConnection(address[0], address[1], timeout=10)
                conn.request("GET", "/api/artifact?project_name=unit_web_artifact&relative_path=artifacts/preview.png")
                response = conn.getresponse()
                body = response.read()
                conn.close()
            self.assertEqual(response.status, 200)
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
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -m unittest tests.test_web_api
```

Expected result: artifact route returns `not_implemented`.

- [ ] **Step 3: Implement artifact route**

In `lsprepost_mcp/web/app.py`, add this method inside `WebAppHandler`:

```python
    def serve_artifact(self, query: dict[str, list[str]]) -> None:
        project_name = query_value(query, "project_name")
        relative = safe_relative_path(query_value(query, "relative_path"))
        if relative.suffix.lower() not in {".png", ".gif", ".json", ".txt", ".xml"}:
            raise ApiError(400, "invalid_path", "artifact suffix is not allowed")
        project = find_project_dir(project_name)
        target = (project / relative).resolve()
        root = project.resolve()
        if root != target and root not in target.parents:
            raise ApiError(400, "invalid_path", "artifact path escaped project")
        if not target.exists() or not target.is_file():
            raise ApiError(404, "not_found", "artifact not found")
        data = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
```

Then replace the `GET /api/artifact` branch in `route_api` with:

```python
        if method == "GET" and path == "/api/artifact":
            self.serve_artifact(query)
            return None
```

Adjust `handle_request` so `route_api` can return `None` after directly serving binary content:

```python
                result = self.route_api(method, parsed.path, parse_qs(parsed.query))
                if result is not None:
                    send_tuple(self, json_ok(result))
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m unittest tests.test_web_api
```

Expected result: artifact safety tests pass.

- [ ] **Step 5: Commit**

```powershell
git add lsprepost_mcp/web/app.py tests/test_web_api.py
git commit -m "feat: add safe web artifact serving"
```

## Task 5: Built-In Fallback Web UI

**Files:**
- Create: `lsprepost_mcp/web/static/index.html`
- Create: `lsprepost_mcp/web/static/styles.css`
- Create: `lsprepost_mcp/web/static/app.js`
- Create: `tests/test_web_static.py`

- [ ] **Step 1: Write failing static UI tests**

Create `tests/test_web_static.py`:

```python
from __future__ import annotations

import http.client
import threading
import unittest
from contextlib import contextmanager

from lsprepost_mcp.web.app import create_server


@contextmanager
def web_static_test_server():
    server = create_server("127.0.0.1", 0, open_browser=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        thread.join(timeout=5)


class WebStaticTests(unittest.TestCase):
    def test_root_serves_fallback_html(self) -> None:
        with web_static_test_server() as address:
            conn = http.client.HTTPConnection(address[0], address[1], timeout=10)
            conn.request("GET", "/")
            response = conn.getresponse()
            body = response.read().decode("utf-8")
            conn.close()
        self.assertEqual(response.status, 200)
        self.assertIn("lsprepost-mcp Web App", body)
        self.assertIn("app.js", body)

    def test_static_js_serves_browser_logic(self) -> None:
        with web_static_test_server() as address:
            conn = http.client.HTTPConnection(address[0], address[1], timeout=10)
            conn.request("GET", "/app.js")
            response = conn.getresponse()
            body = response.read().decode("utf-8")
            conn.close()
        self.assertEqual(response.status, 200)
        self.assertIn("loadScenes", body)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -m unittest tests.test_web_static
```

Expected result: static files missing.

- [ ] **Step 3: Add fallback HTML**

Create `lsprepost_mcp/web/static/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>lsprepost-mcp Web App</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <header class="topbar">
    <div>
      <h1>lsprepost-mcp Web App</h1>
      <p>Controlled LS-DYNA keyword generation through the local backend.</p>
    </div>
    <button id="refresh">Refresh</button>
  </header>
  <main class="layout">
    <section class="panel">
      <h2>1. Scene</h2>
      <select id="scene"></select>
      <div id="fields" class="fields"></div>
      <label class="field">
        <span>Project name</span>
        <input id="projectName" value="web_scene_demo">
      </label>
      <label class="field">
        <span>Natural language prompt</span>
        <textarea id="prompt" rows="5">Generate a controlled scene with the selected parameters.</textarea>
      </label>
      <div class="actions">
        <button id="resolve">Resolve</button>
        <button id="generate">Generate</button>
        <button id="preview">Preview GIF</button>
        <button id="openLspp">Open LS-PrePost</button>
      </div>
    </section>
    <section class="panel">
      <h2>2. Project</h2>
      <div id="projects"></div>
      <h2>3. Result</h2>
      <pre id="result"></pre>
    </section>
    <section class="panel preview">
      <h2>Preview</h2>
      <div id="previewBox">No preview generated.</div>
    </section>
  </main>
  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Add fallback CSS**

Create `lsprepost_mcp/web/static/styles.css`:

```css
body {
  margin: 0;
  font-family: Arial, "Microsoft YaHei", sans-serif;
  color: #1d232a;
  background: #f3f5f7;
}

.topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  background: #18202a;
  color: white;
}

.topbar h1 {
  margin: 0 0 4px;
  font-size: 20px;
}

.topbar p {
  margin: 0;
  color: #c9d2df;
}

.layout {
  display: grid;
  grid-template-columns: minmax(320px, 420px) minmax(320px, 1fr) minmax(320px, 520px);
  gap: 16px;
  padding: 16px;
}

.panel {
  background: white;
  border: 1px solid #d7dde5;
  border-radius: 6px;
  padding: 16px;
  min-height: 240px;
}

.field {
  display: grid;
  gap: 6px;
  margin: 10px 0;
}

input, select, textarea, button {
  font: inherit;
}

input, select, textarea {
  border: 1px solid #b9c2cf;
  border-radius: 4px;
  padding: 8px;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

button {
  border: 1px solid #1e5c99;
  background: #246ba8;
  color: white;
  border-radius: 4px;
  padding: 8px 10px;
  cursor: pointer;
}

pre {
  white-space: pre-wrap;
  word-break: break-word;
  background: #0f1720;
  color: #d5e7ff;
  padding: 12px;
  border-radius: 4px;
  min-height: 260px;
}

.preview img {
  max-width: 100%;
  border: 1px solid #d7dde5;
}
```

- [ ] **Step 5: Add fallback JavaScript**

Create `lsprepost_mcp/web/static/app.js`:

```javascript
let sceneCatalog = [];
let lastProjectName = "";

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    }
  });
  const payload = await response.json();
  if (!payload.ok) {
    throw new Error(`${payload.error.code}: ${payload.error.message}`);
  }
  return payload.result;
}

function showResult(value) {
  document.getElementById("result").textContent = JSON.stringify(value, null, 2);
}

function selectedScene() {
  const id = document.getElementById("scene").value;
  return sceneCatalog.find((scene) => scene.id === id);
}

function collectParameters() {
  const params = {};
  for (const input of document.querySelectorAll("[data-param]")) {
    if (input.dataset.kind === "number") {
      params[input.dataset.param] = Number(input.value);
    } else {
      params[input.dataset.param] = input.value;
    }
  }
  return params;
}

function renderFields() {
  const scene = selectedScene();
  const fields = document.getElementById("fields");
  fields.innerHTML = "";
  for (const field of scene.fields) {
    const label = document.createElement("label");
    label.className = "field";
    const title = document.createElement("span");
    title.textContent = `${field.label}${field.unit ? ` (${field.unit})` : ""}`;
    label.appendChild(title);
    let input;
    if (field.kind === "select") {
      input = document.createElement("select");
      for (const option of field.options) {
        const item = document.createElement("option");
        item.value = option;
        item.textContent = option;
        input.appendChild(item);
      }
    } else {
      input = document.createElement("input");
      input.type = field.kind === "number" ? "number" : "text";
      if (field.kind === "number") input.step = "any";
    }
    input.value = field.default;
    input.dataset.param = field.name;
    input.dataset.kind = field.kind;
    label.appendChild(input);
    fields.appendChild(label);
  }
}

async function loadScenes() {
  const catalog = await api("/api/scenes");
  sceneCatalog = catalog.scenes;
  const select = document.getElementById("scene");
  select.innerHTML = "";
  for (const scene of sceneCatalog) {
    const option = document.createElement("option");
    option.value = scene.id;
    option.textContent = scene.title;
    select.appendChild(option);
  }
  renderFields();
}

async function loadProjects() {
  const result = await api("/api/projects");
  document.getElementById("projects").textContent = result.projects
    .slice(0, 12)
    .map((project) => `${project.name} (${project.source})`)
    .join("\n");
}

async function resolveScene() {
  const projectName = document.getElementById("projectName").value;
  lastProjectName = projectName;
  const result = await api("/api/scene/resolve", {
    method: "POST",
    body: JSON.stringify({
      project_name: projectName,
      prompt: document.getElementById("prompt").value,
      parameters: collectParameters(),
      allow_defaults: true
    })
  });
  showResult(result);
}

async function generateScene() {
  const projectName = document.getElementById("projectName").value;
  lastProjectName = projectName;
  const result = await api("/api/scene/generate", {
    method: "POST",
    body: JSON.stringify({
      project_name: projectName,
      prompt: document.getElementById("prompt").value,
      parameters: collectParameters(),
      allow_defaults: true,
      if_exists: "versioned"
    })
  });
  showResult(result);
  await loadProjects();
}

async function previewGif() {
  const result = await api("/api/project/preview-gif", {
    method: "POST",
    body: JSON.stringify({
      project_name: lastProjectName || document.getElementById("projectName").value,
      if_exists: "overwrite"
    })
  });
  showResult(result);
  const img = document.createElement("img");
  const relative = result.output_path.slice(result.project_dir.length + 1).replaceAll("\\", "/");
  img.src = `/api/artifact?project_name=${encodeURIComponent(result.project_name)}&relative_path=${encodeURIComponent(relative)}`;
  const box = document.getElementById("previewBox");
  box.innerHTML = "";
  box.appendChild(img);
}

async function openLspp() {
  const result = await api("/api/project/open-lsprepost", {
    method: "POST",
    body: JSON.stringify({
      project_name: lastProjectName || document.getElementById("projectName").value
    })
  });
  showResult(result);
}

async function boot() {
  document.getElementById("scene").addEventListener("change", renderFields);
  document.getElementById("refresh").addEventListener("click", loadProjects);
  document.getElementById("resolve").addEventListener("click", () => resolveScene().catch((err) => showResult({error: err.message})));
  document.getElementById("generate").addEventListener("click", () => generateScene().catch((err) => showResult({error: err.message})));
  document.getElementById("preview").addEventListener("click", () => previewGif().catch((err) => showResult({error: err.message})));
  document.getElementById("openLspp").addEventListener("click", () => openLspp().catch((err) => showResult({error: err.message})));
  await loadScenes();
  await loadProjects();
}

boot().catch((err) => showResult({error: err.message}));
```

- [ ] **Step 6: Run static tests**

Run:

```powershell
python -m unittest tests.test_web_static
```

Expected result: `Ran 2 tests ... OK`.

- [ ] **Step 7: Commit**

```powershell
git add lsprepost_mcp/web/static tests/test_web_static.py
git commit -m "feat: add fallback web ui"
```

## Task 6: Startup Script And CLI Smoke

**Files:**
- Create: `scripts/start_web_app.ps1`
- Create: `tests/test_web_startup.py`

- [ ] **Step 1: Write failing startup script tests**

Create `tests/test_web_startup.py`:

```python
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WebStartupTests(unittest.TestCase):
    def test_web_module_help_runs(self) -> None:
        result = subprocess.run(
            ["python", "-m", "lsprepost_mcp.web.app", "--help"],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--port", result.stdout)
        self.assertIn("--lspp-exe", result.stdout)

    def test_start_web_app_script_exists_and_mentions_module(self) -> None:
        script = ROOT / "scripts" / "start_web_app.ps1"
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")
        self.assertIn("lsprepost_mcp.web.app", text)
        self.assertIn("LsppExe", text)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -m unittest tests.test_web_startup
```

Expected result: script existence test fails.

- [ ] **Step 3: Add startup script**

Create `scripts/start_web_app.ps1`:

```powershell
param(
    [string]$LsppExe = $env:LSPP_EXE,
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8765,
    [switch]$OpenBrowser,
    [switch]$SkipDoctor
)

$ErrorActionPreference = "Stop"
$RootPath = Resolve-Path (Join-Path $PSScriptRoot "..")
$Root = $RootPath.Path

if ($LsppExe) {
    $env:LSPP_EXE = $LsppExe
}

if (-not $SkipDoctor) {
    $doctorArgs = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (Join-Path $Root "scripts\doctor.ps1")
    )
    if ($LsppExe) {
        $doctorArgs += @("-LsppExe", $LsppExe)
    }
    & powershell @doctorArgs
    if ($LASTEXITCODE -ne 0) {
        throw "doctor.ps1 failed; Web App startup aborted."
    }
}

Push-Location $Root
try {
    $args = @(
        "-m",
        "lsprepost_mcp.web.app",
        "--host",
        $HostName,
        "--port",
        [string]$Port
    )
    if ($LsppExe) {
        $args += @("--lspp-exe", $LsppExe)
    }
    if ($OpenBrowser) {
        $args += "--open-browser"
    }
    & python @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
```

- [ ] **Step 4: Run startup tests**

Run:

```powershell
python -m unittest tests.test_web_startup
```

Expected result: tests pass.

- [ ] **Step 5: Run a manual help smoke**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_web_app.ps1 -SkipDoctor -Port 8765
```

Expected result: server prints `lsprepost-mcp web app: http://127.0.0.1:8765` and waits. Stop with `Ctrl+C`.

- [ ] **Step 6: Commit**

```powershell
git add scripts/start_web_app.ps1 tests/test_web_startup.py
git commit -m "feat: add local web app startup script"
```

## Task 7: Optional React/Vite Source And Build Selection

**Files:**
- Create: `web/package.json`
- Create: `web/index.html`
- Create: `web/src/main.jsx`
- Create: `web/src/App.jsx`
- Modify: `tests/test_web_static.py`

- [ ] **Step 1: Add tests for build preference**

Append to `tests/test_web_static.py`:

```python
from lsprepost_mcp.config import ROOT


class WebBuildSelectionTests(unittest.TestCase):
    def test_static_root_prefers_dist_when_built_index_exists(self) -> None:
        from lsprepost_mcp.web.app import static_root

        dist = ROOT / "web" / "dist"
        index = dist / "index.html"
        original = index.read_text(encoding="utf-8") if index.exists() else None
        dist.mkdir(parents=True, exist_ok=True)
        index.write_text("<!doctype html><title>built</title>", encoding="utf-8")
        try:
            self.assertEqual(static_root(), dist)
        finally:
            if original is None:
                index.unlink()
            else:
                index.write_text(original, encoding="utf-8")
```

- [ ] **Step 2: Run static tests**

Run:

```powershell
python -m unittest tests.test_web_static
```

Expected result: tests pass because `static_root()` already supports `web/dist`.

- [ ] **Step 3: Add optional React/Vite package metadata**

Create `web/package.json`:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "vite build"
  },
  "dependencies": {
    "@vitejs/plugin-react": "^5.0.0",
    "vite": "^7.0.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {}
}
```

- [ ] **Step 4: Add optional React HTML shell**

Create `web/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>lsprepost-mcp Web App</title>
</head>
<body>
  <div id="root"></div>
  <script type="module" src="/src/main.jsx"></script>
</body>
</html>
```

- [ ] **Step 5: Add optional React entry**

Create `web/src/main.jsx`:

```jsx
import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.jsx";

createRoot(document.getElementById("root")).render(<App />);
```

- [ ] **Step 6: Add optional React app**

Create `web/src/App.jsx`:

```jsx
import React from "react";

export function App() {
  return (
    <main style={{fontFamily: "Arial, sans-serif", padding: 24}}>
      <h1>lsprepost-mcp Web App</h1>
      <p>
        React/Vite build entry. The runtime server uses this build when web/dist/index.html exists;
        otherwise it serves the built-in fallback UI.
      </p>
    </main>
  );
}
```

- [ ] **Step 7: Run tests**

Run:

```powershell
python -m unittest tests.test_web_static
```

Expected result: static tests pass without Node.js.

- [ ] **Step 8: Optional Node build smoke**

Run only when `node` and `npm` are available:

```powershell
cd web
npm install
npm run build
cd ..
```

Expected result: `web/dist/index.html` exists. If Node.js is unavailable, skip this smoke and keep fallback UI as the runtime path.

- [ ] **Step 9: Commit**

```powershell
git add web tests/test_web_static.py
git commit -m "feat: add optional react web source"
```

## Task 8: Doctor, Test Matrix, Packaging, And Docs

**Files:**
- Modify: `scripts/doctor.ps1`
- Modify: `scripts/run_test_matrix.ps1`
- Modify: `scripts/pack.ps1`
- Modify: `README.zh-CN.md`
- Modify: `README.md`
- Modify: `AI_IDE_START_HERE.zh-CN.md`
- Modify: `tests/test_phase8_distribution.py`
- Modify: `tests/test_phase10_test_matrix.py`
- Modify: `tests/test_packaging_and_integration_boundaries.py`

- [ ] **Step 1: Add failing doctor assertions**

In `tests/test_phase8_distribution.py`, extend `test_doctor_json_reports_core_checks_ok_without_lsprepost_requirement`:

```python
        self.assertIn("web_app_files", check_names)
        self.assertIn("node_optional", check_names)
        node = next(item for item in payload["checks"] if item["name"] == "node_optional")
        self.assertIn(node["status"], {"ok", "warning"})
```

- [ ] **Step 2: Add Web group assertion**

In `tests/test_phase10_test_matrix.py`, add:

```python
    def test_run_test_matrix_executes_web_group(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "run_test_matrix.ps1"
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Group",
                "web",
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Running test matrix group: web", completed.stdout)
```

- [ ] **Step 3: Add packaging assertions**

In `tests/test_packaging_and_integration_boundaries.py`, extend the package content checks so the pure package includes:

```python
        self.assertIn("scripts/start_web_app.ps1", names)
        self.assertIn("lsprepost_mcp/web/app.py", names)
        self.assertIn("lsprepost_mcp/web/static/index.html", names)
```

- [ ] **Step 4: Run targeted tests to verify failure**

Run:

```powershell
python -m unittest tests.test_phase8_distribution tests.test_phase10_test_matrix tests.test_packaging_and_integration_boundaries
```

Expected result: failures for missing doctor checks or missing test matrix group before script updates.

- [ ] **Step 5: Update doctor**

In `scripts/doctor.ps1`, add required Web files to `$requiredFiles`:

```powershell
    "lsprepost_mcp\web\app.py",
    "lsprepost_mcp\web\static\index.html",
    "scripts\start_web_app.ps1"
```

After `required_files`, add a dedicated Web check:

```powershell
$webFiles = @(
    "lsprepost_mcp\web\app.py",
    "lsprepost_mcp\web\static\index.html",
    "lsprepost_mcp\web\static\app.js",
    "scripts\start_web_app.ps1"
)
$missingWebFiles = @()
foreach ($relative in $webFiles) {
    if (-not (Test-Path (Join-Path $Root $relative))) {
        $missingWebFiles += $relative
    }
}
if ($missingWebFiles.Count -eq 0) {
    Add-Check "web_app_files" "ok" "local Web App files are present"
} else {
    Add-Check "web_app_files" "error" "local Web App files are missing" $missingWebFiles
}

if (Test-Command "node") {
    try {
        $nodeVersion = (& node --version 2>&1) -join "`n"
        Add-Check "node_optional" "ok" "Node.js is available for optional React/Vite builds" $nodeVersion.Trim()
    } catch {
        Add-Check "node_optional" "warning" "node exists but failed to run; fallback Web UI remains available" $_.Exception.Message
    }
} else {
    Add-Check "node_optional" "warning" "Node.js not found; fallback Web UI remains available"
}
```

- [ ] **Step 6: Update test matrix**

In `scripts/run_test_matrix.ps1`, add a `web` group that runs:

```powershell
python -m unittest tests.test_web_api tests.test_web_static tests.test_web_startup
```

The output must include:

```text
Running test matrix group: web
```

- [ ] **Step 7: Update docs**

Add this Web App section to `README.zh-CN.md` and a concise English equivalent to `README.md`:

```markdown
## 本地 Web App 入口

第 11 阶段开始，本项目提供本地 Web App 入口。它默认只监听 `127.0.0.1`，用于普通用户选择受控场景、填写参数、生成模型、查看校验和预览。

启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_web_app.ps1 -LsppExe $env:LSPP_EXE -OpenBrowser
```

如果没有 Node.js，Web App 会使用内置原生 HTML/CSS/JS 兜底页面。Node.js 只用于开发或重新构建 React/Vite 前端，不是最终用户运行依赖。
```

In `AI_IDE_START_HERE.zh-CN.md`, add one paragraph:

```markdown
如果用户希望通过图形界面操作，可以启动 `scripts\start_web_app.ps1`。Web App 和 AI IDE 都必须复用本项目后端生成流程，不得直接手写 keyword。
```

- [ ] **Step 8: Run targeted tests**

Run:

```powershell
python -m unittest tests.test_phase8_distribution tests.test_phase10_test_matrix tests.test_packaging_and_integration_boundaries
```

Expected result: targeted tests pass.

- [ ] **Step 9: Commit**

```powershell
git add scripts/doctor.ps1 scripts/run_test_matrix.ps1 scripts/pack.ps1 README.zh-CN.md README.md AI_IDE_START_HERE.zh-CN.md tests/test_phase8_distribution.py tests/test_phase10_test_matrix.py tests/test_packaging_and_integration_boundaries.py
git commit -m "docs: document local web app startup"
```

## Task 9: Full Verification And Package

**Files:**
- No new source files unless verification reveals a defect.

- [ ] **Step 1: Run Web test group**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_test_matrix.ps1 -Group web
```

Expected result: Web group passes.

- [ ] **Step 2: Run full unit suite**

Run:

```powershell
python -m unittest discover -s tests
```

Expected result: all non-integration tests pass; LS-PrePost GUI integration tests may remain skipped unless explicitly enabled.

- [ ] **Step 3: Run compile check**

Run:

```powershell
python -m compileall -q .\lsprepost_mcp
```

Expected result: command exits with code 0.

- [ ] **Step 4: Run full test matrix**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_test_matrix.ps1 -Group all
```

Expected result: all configured groups pass.

- [ ] **Step 5: Create phase package**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\pack.ps1 -BuildLabel phase11-local-web-app -Pure
```

Expected result: a new zip appears in `dist\` and package checks pass.

- [ ] **Step 6: Inspect package contents**

Run:

```powershell
$zip = Get-ChildItem .\dist\lsprepost-mcp_phase11-local-web-app_*.zip | Sort-Object LastWriteTime | Select-Object -Last 1
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($zip.FullName)
try {
    $names = $archive.Entries.FullName
    @(
        "scripts/start_web_app.ps1",
        "lsprepost_mcp/web/app.py",
        "lsprepost_mcp/web/static/index.html",
        "PACKAGE_MANIFEST.txt"
    ) | ForEach-Object {
        if ($names -notcontains $_) { throw "missing package entry: $_" }
    }
    "package_ok=$($zip.FullName)"
} finally {
    $archive.Dispose()
}
```

Expected result: prints `package_ok=...`.

- [ ] **Step 7: Commit verification updates**

If verification required fixes, commit them with a focused message. If no source changes happened after Task 8, skip this commit.

```powershell
git status --short
```

Expected result: only expected package artifacts or no source changes remain.

## Self-Review

Spec coverage:

- Local Web App: Tasks 3, 5, and 6.
- Web App calls existing backend tools directly: Tasks 3 and 4.
- Controlled scene selection and parameters: Tasks 2 and 5.
- Natural-language prompt through existing controlled parser: Task 3 endpoint `/api/scene/resolve` and `/api/scene/generate`.
- Project list/history: Task 3 endpoint `/api/projects`; Task 5 UI.
- Static validation and model summary access: Task 3 endpoints `/api/project` and `/api/project/validate`.
- PNG/GIF preview support: Task 4 artifact serving and Task 5 preview action.
- Open LS-PrePost troubleshooting: Task 3 endpoint `/api/project/open-lsprepost`; Task 5 button.
- Node.js not required at runtime: Task 5 fallback UI and Task 7 build selection.
- Optional React/Vite source: Task 7.
- Startup script: Task 6.
- Packaging and docs: Tasks 8 and 9.
- No direct keyword writing from frontend: API contract and Task 4 safety tests.

No unresolved placeholders are intentionally left in this plan. Implementation must keep API endpoints controlled and must not introduce arbitrary file-write or arbitrary cfile execution routes.
