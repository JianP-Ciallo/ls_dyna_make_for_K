from __future__ import annotations

import copy
import json
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request_json(base_url: str, path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        base_url + path,
        data=data,
        method="GET" if payload is None else "POST",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code} {path}: {detail}") from error


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8767"
    provider_id = sys.argv[2] if len(sys.argv) > 2 else "lbe_segment"
    capabilities = request_json(base_url, "/api/refined-building-blast/capabilities")["result"]
    assets = request_json(base_url, "/api/refined-building-blast/assets")["result"]["assets"]
    asset_id = {
        "explicit_ale_fsi": "commercial_supermarket_detailed_building",
        "lbe_segment": "subway_entrance_detailed_building",
        "imported_pressure_history": "residential_community_detailed_building",
    }[provider_id]
    asset = next(row for row in assets if row["asset_id"] == asset_id)
    provider = next(row for row in capabilities["providers"] if row["provider_id"] == provider_id)

    project_id = f"soft-copyright-preview-{int(time.time())}"
    draft = copy.deepcopy(capabilities["default_scenario_draft"])
    draft["scenario_id"] = f"{project_id}-scenario"
    provider_input = copy.deepcopy(provider["default_input"])
    if provider_id == "explicit_ale_fsi":
        provider_input["budgets"].update({
            "max_axis_points": 40,
            "max_node_count": 20_000,
            "max_element_count": 20_000,
        })
    elif provider_id == "lbe_segment":
        provider_input["source"]["position_m"] = [-2.0, 1.5, 1.5]
        provider_input["budgets"].update({
            "max_surface_count": 100_000,
            "max_total_area_m2": 1_000_000.0,
        })
    draft["load_provider"] = {
        "provider_id": provider["provider_id"],
        "provider_input": provider_input,
    }
    legacy_geometry = {
        "length_m": 6.0,
        "width_m": 6.0,
        "height_m": 3.0,
        "wall_thickness_m": 0.25,
        "entrance_width_m": 2.0,
        "entrance_height_m": 2.0,
    } if provider_id == "explicit_ale_fsi" else {}
    payload = {
        "schema_version": "refined_blast_create@1",
        "building": {
            "asset_id": asset["asset_id"],
            "legacy_geometry": legacy_geometry,
            "structural_system": asset["default_structural_system"],
            "fidelity_profile": "structural_core",
            "mesh_profile": "coarse",
            "generation_options": {},
            "material_overrides": {},
        },
        "project": {
            "schema_version": "refined_building_blast@1",
            "project_id": project_id,
            "preset_reference": "soft_copyright_preview",
            "preset_version": "1",
            "project_overrides": {},
            "expert_extensions": {},
            "scenario_set": [draft],
            "confirmation_records": [],
            "provenance": {"purpose": "software_copyright_runtime_screenshot"},
            "created_at": "2026-08-28T00:00:00Z",
            "updated_at": "2026-08-28T00:00:00Z",
        },
    }
    created = request_json(base_url, "/api/refined-building-blast/projects", payload)["result"]["project"]
    revision = created["revision"]
    preview = request_json(
        base_url,
        f"/api/refined-building-blast/projects/{project_id}/preview",
        {"expected_revision": revision},
    )["result"]["preview"]
    print(json.dumps({
        "project_id": project_id,
        "revision": revision,
        "preview_project_id": preview.get("project_id"),
        "preview_revision": preview.get("project_revision"),
        "preview_keys": sorted(preview),
        "layer_count": len(preview.get("layers", [])),
        "object_count": len(preview.get("objects", [])),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
