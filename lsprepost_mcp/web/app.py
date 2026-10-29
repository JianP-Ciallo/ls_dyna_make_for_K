from __future__ import annotations

import argparse
import mimetypes
import os
import socket
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from lsprepost_mcp.config import JSONDict, ROOT
from lsprepost_mcp.blast_cases import blast_case_catalog, blast_case_payload, blast_plate_demo_payload
from lsprepost_mcp.paths import find_project_dir
from lsprepost_mcp.tool_generation import (
    tool_assemble_components,
    tool_generate_ale_blast_demo,
    tool_generate_tunnel_blast_demo,
    tool_prepare_phase15_a1,
    tool_generate_phase15_a1,
    tool_generate_model,
    tool_generate_scene_from_prompt,
    tool_list_component_templates,
    tool_list_physics_actions,
)
from lsprepost_mcp.tool_lsprepost import (
    tool_export_preview_gif,
    tool_open_in_lsprepost,
    tool_open_result_lsprepost,
    tool_validate_lsprepost_import,
)
from lsprepost_mcp.tool_project import tool_list_projects, tool_read_project, tool_validate_model
from lsprepost_mcp.tool_server import tool_server_info
from lsprepost_mcp.web.config_api import (
    check_lsdyna_payload,
    check_lsprepost_payload,
    check_lsrun_payload,
    configured_export_dir,
    save_lsdyna_payload,
    save_lsprepost_payload,
    save_lsrun_payload,
    save_export_dir_payload,
    select_export_dir_payload,
    select_lsdyna_payload,
    select_lsprepost_payload,
    select_lsrun_payload,
    web_config_status,
)
from lsprepost_mcp.web.city_impact_api import (
    city_impact_payload,
    write_city_impact_report_payload,
)
from lsprepost_mcp.web.damage_assessment_api import (
    assessment_capabilities_payload,
)
from lsprepost_mcp.web.http_utils import ApiError, json_error, json_ok, parse_json_body, safe_relative_path
from lsprepost_mcp.web.refined_blast_api import (
    REFINED_BLAST_API_PREFIX,
    handle_refined_blast_artifact_get,
    handle_refined_blast_get,
    handle_refined_blast_post,
    is_refined_blast_payload,
)
from lsprepost_mcp.web.draft_preview import (
    build_editor_draft_preview,
    city_editor_template,
    generate_editor_project,
    mutate_city_editor_component,
)
from lsprepost_mcp.web.preview_mesh import build_preview_mesh
from lsprepost_mcp.web.preview_cache import build_cached_preview_mesh
from lsprepost_mcp.web.phase16b_api import (
    analyze_city_case_uncertainty_payload,
    authorize_city_case_batch_payload,
    compare_city_case_results_payload,
    plan_city_local_refinement_payload,
    predict_city_surrogate_payload,
    prepare_city_case_matrix_payload,
    rank_city_protection_options_payload,
    register_city_case_result_payload,
    train_city_surrogate_payload,
)
from lsprepost_mcp.web.project_export import export_project_copy
from lsprepost_mcp.web.project_import import import_project_package_payload, select_import_project_package_payload
from lsprepost_mcp.web.scenes import web_scene_catalog
from lsprepost_mcp.web.solve_api import (
    compare_lsdyna_payload,
    latest_lsdyna_payload,
    open_lsrun_payload,
    recover_lsrun_payload,
    run_lsdyna_payload,
)


LOCAL_HOSTS = {"127.0.0.1", "localhost"}
MAX_REQUEST_BODY_BYTES = 1024 * 1024


from lsprepost_mcp.web.fixed_building_workspace import FixedBuildingWorkspace, PREFIX as FIXED_BUILDING_PREFIX, SCENE_CPU_PREFIX


class WebAppServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self.fixed_building = FixedBuildingWorkspace(ROOT / "var" / "fixed-building-pressure")
        super().__init__(*args, **kwargs)

    def server_close(self):
        super().server_close()
        self.fixed_building.close()

    def server_bind(self) -> None:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_EXCLUSIVEADDRUSE,
                1,
            )
        super().server_bind()


def static_root() -> Path:
    # The packaged workbench is the production source of truth. A local build
    # must not silently replace it with stale or experimental UI assets.
    return Path(__file__).resolve().parent / "static"


def read_request_body(handler: BaseHTTPRequestHandler) -> bytes:
    raw_length = handler.headers.get("Content-Length", "0") or "0"
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise ApiError(400, "invalid_request", "Content-Length must be an integer") from exc
    if length < 0:
        raise ApiError(400, "invalid_request", "Content-Length must not be negative")
    if length > MAX_REQUEST_BODY_BYTES:
        raise ApiError(
            413,
            "request_too_large",
            f"request body must not exceed {MAX_REQUEST_BODY_BYTES} bytes",
        )
    return handler.rfile.read(length) if length > 0 else b"{}"


def send_tuple(handler: BaseHTTPRequestHandler, response: tuple[int, dict[str, str], bytes]) -> None:
    status, headers, body = response
    handler.send_response(status)
    for key, value in headers.items():
        handler.send_header(key, value)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(body)


def query_value(query: dict[str, list[str]], name: str) -> str:
    values = query.get(name) or []
    return values[0] if values else ""


def require_json_content_type(handler: BaseHTTPRequestHandler) -> None:
    media_type = (handler.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise ApiError(415, "unsupported_media_type", "Content-Type must be application/json")


def parsed_host_port(raw: str) -> tuple[str, int]:
    parsed = urlparse(f"//{raw}")
    if not parsed.hostname:
        raise ValueError("host is required")
    return parsed.hostname.lower(), parsed.port or 80


def parsed_url_origin(raw: str) -> tuple[str, str, int | None]:
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError("absolute URL is required")
    scheme = parsed.scheme.lower()
    return scheme, parsed.hostname.lower(), parsed.port or (80 if scheme == "http" else None)


def require_local_host(handler: BaseHTTPRequestHandler) -> None:
    try:
        request_host, _request_port = parsed_host_port(handler.headers.get("Host") or "")
    except ValueError as exc:
        raise ApiError(403, "forbidden_host", "request Host is not allowed") from exc
    if request_host not in LOCAL_HOSTS:
        raise ApiError(403, "forbidden_host", "request Host is not allowed")


def require_same_local_origin(handler: BaseHTTPRequestHandler) -> None:
    source = handler.headers.get("Origin")
    if not source:
        source = handler.headers.get("Referer")
    if not source:
        return

    try:
        request_host, request_port = parsed_host_port(handler.headers.get("Host") or "")
        source_scheme, source_host, source_port = parsed_url_origin(source)
    except ValueError as exc:
        raise ApiError(403, "forbidden_origin", "browser request origin is not allowed") from exc
    if source_scheme != "http" or source_host != request_host or source_port != request_port:
        raise ApiError(403, "forbidden_origin", "browser request origin is not allowed")


def attach_user_export(result: JSONDict) -> JSONDict:
    if os.environ.get("LSPP_WEB_DISABLE_USER_EXPORT") == "1":
        return result
    export_dir = configured_export_dir()
    if export_dir is None:
        return result

    raw_project_dir = (
        result.get("project_dir")
        or (result.get("write_result") if isinstance(result.get("write_result"), dict) else {}).get("project_dir")
    )
    if not isinstance(raw_project_dir, str) or not raw_project_dir.strip():
        return result

    project_path = Path(raw_project_dir)
    result["user_export"] = export_project_copy(project_path, export_dir)
    return result


class WebAppHandler(BaseHTTPRequestHandler):
    server_version = "lsprepost-mcp-web/0.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_error(
        self, code: int, message: str | None = None, explain: str | None = None
    ) -> None:
        if code == 501 and urlparse(self.path).path.startswith(
            REFINED_BLAST_API_PREFIX + "/"
        ):
            self.handle_request(self.command)
            return
        super().send_error(code, message, explain)

    def do_GET(self) -> None:
        self.handle_request("GET")

    def do_HEAD(self) -> None:
        self.handle_request("HEAD")

    def do_POST(self) -> None:
        self.handle_request("POST")

    def do_PUT(self) -> None:
        self._handle_refined_unsupported_method("PUT")

    def do_PATCH(self) -> None:
        self._handle_refined_unsupported_method("PATCH")

    def do_DELETE(self) -> None:
        self._handle_refined_unsupported_method("DELETE")

    def do_OPTIONS(self) -> None:
        self._handle_refined_unsupported_method("OPTIONS")

    def _handle_refined_unsupported_method(self, method: str) -> None:
        if urlparse(self.path).path.startswith(REFINED_BLAST_API_PREFIX + "/"):
            self.handle_request(method)
            return
        self.send_error(501, f"Unsupported method ({self.command!r})")

    def handle_request(self, method: str) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        response: tuple[int, dict[str, str], bytes] | None
        try:
            if parsed.path == "/api" or parsed.path.startswith("/api/"):
                try:
                    require_local_host(self)
                except ApiError:
                    if method not in {"GET", "HEAD"}:
                        try:
                            read_request_body(self)
                        except ApiError:
                            pass
                    raise
                if (
                    method not in {"GET", "HEAD", "POST"}
                    and parsed.path.startswith(REFINED_BLAST_API_PREFIX + "/")
                ):
                    require_same_local_origin(self)
                    read_request_body(self)
                response = self.handle_api(method, parsed.path, query)
            elif method in {"GET", "HEAD"}:
                response = self.handle_static(parsed.path)
            else:
                raise ApiError(405, "method_not_allowed", "method is not allowed")
        except ApiError as exc:
            response = json_error(exc.status, exc.code, exc.message)
        except FileNotFoundError as exc:
            response = json_error(404, "not_found", str(exc))
        except ValueError as exc:
            response = json_error(400, "invalid_request", str(exc))
        except Exception as exc:
            response = json_error(500, "internal_error", str(exc))
        if response is not None:
            send_tuple(self, response)

    def handle_api(
        self,
        method: str,
        path: str,
        query: dict[str, list[str]],
    ) -> tuple[int, dict[str, str], bytes] | None:
        if path.startswith((FIXED_BUILDING_PREFIX, '/api/architecture/tnt/', SCENE_CPU_PREFIX)):
            if query:
                raise ApiError(400, "invalid_request", "fixed building API does not accept query parameters")
            if method == "POST":
                try:
                    require_json_content_type(self)
                    require_same_local_origin(self)
                except ApiError:
                    read_request_body(self)
                    raise
                payload = parse_json_body(read_request_body(self))
            else:
                require_same_local_origin(self)
                payload = None
            return self.server.fixed_building.request(method, path, payload)
        if method in {"GET", "HEAD"}:
            return self.handle_api_get(path, query)
        if method == "POST":
            return self.handle_api_post(path, query)
        raise ApiError(405, "method_not_allowed", "method is not allowed")

    def handle_api_get(self, path: str, query: dict[str, list[str]]) -> tuple[int, dict[str, str], bytes] | None:
        if path == "/api/damage-assessment/demo/scene":
            if query:
                raise ApiError(400, "unknown_query", "Demo does not accept query parameters")
            from lsprepost_mcp.web.damage_demo_api import scene_payload
            return json_ok(scene_payload())
        if path == "/api/damage-assessment/capabilities":
            if query:
                raise ApiError(
                    400,
                    "unknown_query",
                    "damage assessment capabilities do not accept query parameters",
                )
            return json_ok(assessment_capabilities_payload())
        if path.startswith(REFINED_BLAST_API_PREFIX + "/"):
            relative = path[len(REFINED_BLAST_API_PREFIX):]
            artifact = handle_refined_blast_artifact_get(relative, query)
            if artifact is not None:
                return artifact
            return json_ok(handle_refined_blast_get(relative, query))
        if path == "/api/server-info":
            return json_ok(tool_server_info({}))
        if path == "/api/config":
            return json_ok(web_config_status())
        if path == "/api/scenes":
            return json_ok(web_scene_catalog())
        if path == "/api/components":
            return json_ok(tool_list_component_templates({}))
        if path == "/api/physics-actions":
            return json_ok(tool_list_physics_actions({}))
        if path == "/api/blast-demo":
            return json_ok({"ok": True, "payload": blast_plate_demo_payload()})
        if path == "/api/ale-blast-demo":
            return json_ok(
                tool_generate_ale_blast_demo(
                    {"project_name": "web_phase14_mmale_blast", "dry_run": True}
                )
            )
        if path == "/api/tunnel-blast-demo":
            return json_ok(
                tool_generate_tunnel_blast_demo(
                    {"project_name": "web_phase14_open_tunnel_blast", "dry_run": True}
                )
            )
        if path == "/api/blast-cases":
            cases = blast_case_catalog()
            return json_ok({"ok": True, "count": len(cases), "cases": cases})
        if path == "/api/blast-case":
            case_id = query_value(query, "case_id")
            project_name = query_value(query, "project_name") or None
            return json_ok({"ok": True, "payload": blast_case_payload(case_id, project_name)})
        if path == "/api/projects":
            return json_ok(tool_list_projects({"include_archived": True}))
        if path == "/api/project":
            return json_ok(tool_read_project({"project_name": query_value(query, "project_name")}))
        if path == "/api/project/preview-mesh":
            project = find_project_dir(query_value(query, "project_name"))
            return json_ok(build_cached_preview_mesh(project, build_preview_mesh))
        if path == "/api/project/city-impact":
            return json_ok(city_impact_payload(query_value(query, "project_name")))
        if path == "/api/editor/city-template":
            return json_ok(
                city_editor_template(
                    query_value(query, "project_name")
                    or "web_phase17_city_street_blast"
                )
            )
        if path == "/api/solve/status":
            return json_ok(latest_lsdyna_payload(query_value(query, "project_name")))
        if path == "/api/artifact":
            self.serve_artifact(query)
            return None
        raise ApiError(404, "not_found", f"route not found: {path}")

    def handle_api_post(
        self, path: str, query: dict[str, list[str]] | None = None
    ) -> tuple[int, dict[str, str], bytes]:
        try:
            require_json_content_type(self)
            require_same_local_origin(self)
        except ApiError:
            read_request_body(self)
            raise
        body = read_request_body(self)
        payload = parse_json_body(body)
        if path == "/api/damage-assessment/demo/evaluate":
            if query:
                raise ApiError(400, "unknown_query", "Demo does not accept query parameters")
            from lsprepost_mcp.web.damage_demo_api import evaluate_demo
            return json_ok(evaluate_demo(payload))
        if path.startswith(REFINED_BLAST_API_PREFIX + "/"):
            if query:
                raise ApiError(400, "unknown_query", "POST routes do not accept query parameters")
            return json_ok(handle_refined_blast_post(path[len(REFINED_BLAST_API_PREFIX):], payload))
        if path.startswith("/api/editor/") and is_refined_blast_payload(payload):
            raise ApiError(
                400,
                "project_type_mismatch",
                "refined building blast projects must use the isolated refined blast API",
            )
        if path == "/api/scene/resolve":
            args: JSONDict = {**payload, "dry_run": True}
            return json_ok(tool_generate_scene_from_prompt(args))
        if path == "/api/scene/generate":
            return json_ok(attach_user_export(tool_generate_scene_from_prompt(payload)))
        if path == "/api/model/generate":
            return json_ok(attach_user_export(tool_generate_model(payload)))
        if path == "/api/assembly/validate":
            return json_ok(tool_assemble_components({**payload, "dry_run": True}))
        if path == "/api/assembly/generate":
            return json_ok(attach_user_export(tool_assemble_components(payload)))
        if path == "/api/editor/preview":
            return json_ok(build_editor_draft_preview(payload))
        if path == "/api/editor/city-component":
            return json_ok(mutate_city_editor_component(payload))
        if path == "/api/editor/generate":
            return json_ok(attach_user_export(generate_editor_project(payload)))
        if path == "/api/editor/validate-lsprepost":
            config = web_config_status()
            doctor = config.get("doctor")
            if not isinstance(doctor, dict) or not doctor.get("ok"):
                raise ApiError(
                    409,
                    "lsprepost_not_configured",
                    "请先在工作区导入有效的 lsprepost*.exe，再执行 LS-PrePost 导入检查",
                )
            return json_ok(tool_validate_lsprepost_import(payload))
        if path == "/api/ale-blast/validate":
            return json_ok(tool_generate_ale_blast_demo({**payload, "dry_run": True}))
        if path == "/api/ale-blast/generate":
            return json_ok(attach_user_export(tool_generate_ale_blast_demo(payload)))
        if path == "/api/tunnel-blast/validate":
            return json_ok(tool_generate_tunnel_blast_demo({**payload, "dry_run": True}))
        if path == "/api/tunnel-blast/generate":
            return json_ok(attach_user_export(tool_generate_tunnel_blast_demo(payload)))
        if path == "/api/phase15/prepare":
            return json_ok(tool_prepare_phase15_a1(payload))
        if path == "/api/phase15/generate":
            return json_ok(attach_user_export(tool_generate_phase15_a1(payload)))
        if path == "/api/phase16b/case-matrix":
            return json_ok(prepare_city_case_matrix_payload(payload))
        if path == "/api/phase16b/authorize":
            return json_ok(authorize_city_case_batch_payload(payload))
        if path == "/api/phase16b/register-result":
            return json_ok(register_city_case_result_payload(payload))
        if path == "/api/phase16b/compare":
            return json_ok(compare_city_case_results_payload(payload))
        if path == "/api/phase16b/analyze-uncertainty":
            return json_ok(analyze_city_case_uncertainty_payload(payload))
        if path == "/api/phase16b/plan-refinement":
            return json_ok(plan_city_local_refinement_payload(payload))
        if path == "/api/phase16b/train-surrogate":
            return json_ok(train_city_surrogate_payload(payload))
        if path == "/api/phase16b/predict-surrogate":
            return json_ok(predict_city_surrogate_payload(payload))
        if path == "/api/phase16b/rank-protection":
            return json_ok(rank_city_protection_options_payload(payload))
        if path == "/api/project/validate":
            return json_ok(tool_validate_model(payload))
        if path == "/api/project/preview-gif":
            return json_ok(tool_export_preview_gif(payload))
        if path == "/api/project/open-lsprepost":
            return json_ok(tool_open_in_lsprepost(payload))
        if path == "/api/project/open-result-lsprepost":
            return json_ok(tool_open_result_lsprepost(payload))
        if path == "/api/project/city-impact-report":
            return json_ok(write_city_impact_report_payload(payload))
        if path == "/api/project/import-package":
            return json_ok(import_project_package_payload(payload))
        if path == "/api/project/select-import-package":
            return json_ok(select_import_project_package_payload(payload))
        if path == "/api/config/select-lsprepost":
            return json_ok(select_lsprepost_payload(payload))
        if path == "/api/config/check-lsprepost":
            return json_ok(check_lsprepost_payload(payload))
        if path == "/api/config/lsprepost":
            return json_ok(save_lsprepost_payload(payload))
        if path == "/api/config/check-lsrun":
            return json_ok(check_lsrun_payload(payload))
        if path == "/api/config/select-lsrun":
            return json_ok(select_lsrun_payload(payload))
        if path == "/api/config/lsrun":
            return json_ok(save_lsrun_payload(payload))
        if path == "/api/config/check-lsdyna":
            return json_ok(check_lsdyna_payload(payload))
        if path == "/api/config/select-lsdyna":
            return json_ok(select_lsdyna_payload(payload))
        if path == "/api/config/lsdyna":
            return json_ok(save_lsdyna_payload(payload))
        if path == "/api/config/select-export-dir":
            return json_ok(select_export_dir_payload(payload))
        if path == "/api/config/export-dir":
            return json_ok(save_export_dir_payload(payload))
        if path == "/api/solve/open-lsrun":
            return json_ok(open_lsrun_payload(payload))
        if path == "/api/solve/recover-lsrun":
            return json_ok(recover_lsrun_payload(payload))
        if path == "/api/solve/run-lsdyna":
            return json_ok(run_lsdyna_payload(payload))
        if path == "/api/solve/compare":
            return json_ok(compare_lsdyna_payload(payload))
        raise ApiError(404, "not_found", f"route not found: {path}")

    def serve_artifact(self, query: dict[str, list[str]]) -> None:
        project_name = query_value(query, "project_name")
        relative = safe_relative_path(query_value(query, "relative_path"))
        if relative.suffix.lower() not in {".png", ".gif", ".json", ".txt", ".xml"}:
            raise ApiError(400, "invalid_path", "artifact suffix is not allowed")

        project = find_project_dir(project_name)
        root = project.resolve()
        target = (project / relative).resolve()
        if root != target and root not in target.parents:
            raise ApiError(400, "invalid_path", "artifact path escaped project")
        if not target.is_file():
            raise ApiError(404, "not_found", "artifact not found")

        data = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def handle_static(self, raw_path: str) -> tuple[int, dict[str, str], bytes]:
        fixed = self.server.fixed_building.static_response(raw_path, legacy=parse_qs(urlparse(self.path).query).get('legacy') == ['1'])
        if fixed is not None:
            return fixed
        root = static_root().resolve()
        if raw_path in {"", "/"}:
            relative = Path("index.html")
        else:
            decoded = unquote(raw_path).replace("\\", "/").lstrip("/")
            relative = Path(decoded)
        if relative.is_absolute() or ".." in relative.parts:
            raise ApiError(404, "not_found", "static file not found")
        path = (root / relative).resolve()
        if root != path and root not in path.parents:
            raise ApiError(404, "not_found", "static file not found")
        if not path.is_file():
            if relative.suffix:
                raise ApiError(404, "not_found", "static file not found")
            path = root / "index.html"
        if not path.is_file():
            raise ApiError(404, "not_found", "static file not found")
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        return 200, {"Content-Type": content_type}, path.read_bytes()


def create_server(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> WebAppServer:
    if host.lower() not in LOCAL_HOSTS:
        raise ValueError("host must be localhost or 127.0.0.1")
    server = WebAppServer((host, port), WebAppHandler)
    url = f"http://{server.server_address[0]}:{server.server_address[1]}"
    if open_browser:
        webbrowser.open(url)
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the lsprepost-mcp local Web App.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=8765, help="TCP port to bind.")
    parser.add_argument("--lspp-exe", default="", help="Optional LS-PrePost executable path.")
    parser.add_argument("--open-browser", action="store_true", help="Open the Web App URL in a browser.")
    args = parser.parse_args(argv)

    if args.lspp_exe:
        os.environ["LSPP_EXE"] = args.lspp_exe

    server = create_server(args.host, args.port, open_browser=args.open_browser)
    url = f"http://{server.server_address[0]}:{server.server_address[1]}"
    print(f"lsprepost-mcp web app: {url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
