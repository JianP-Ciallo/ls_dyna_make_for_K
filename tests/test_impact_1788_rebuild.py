"""Bounded tests: preserve three material regions and source definitions."""
from collections import Counter
from copy import deepcopy
import hashlib
import importlib
import importlib.util
import math
from pathlib import Path

import pytest


def api(name):
    module = "lsprepost_mcp." + name
    assert importlib.util.find_spec(module) is not None, "Missing second-source reconstruction implementation"
    return importlib.import_module(module)


def small_spec(name="impact_small"):
    return api("impact_1788_rebuild").default_spec(name, radial_cells=[1, 4], axial_cells=[3, 2, 2])


def test_small_mesh_keeps_all_regions_and_shared_interfaces():
    module = api("impact_1788_mesh")
    mesh = module.build_mesh(small_spec()["mesh"])
    assert len(mesh["nodes"]) == 48
    assert Counter(e[1] for e in mesh["elements"]) == {1: 2, 2: 15, 3: 18}
    report = module.audit_mesh(mesh["nodes"], mesh["elements"], small_spec()["mesh"])
    assert report["ok"], report
    assert report["interfaces"] == {"1-2": {"edges": 1, "nodes": 2}, "1-3": {"edges": 3, "nodes": 4}, "2-3": {"edges": 4, "nodes": 5}}
    assert report["connected_components"] == 1
    assert report["minimum_jacobian"] > 0
    assert report["parts"]["1"]["volume_m3"] == pytest.approx(math.pi * .003**2 * .03)
    assert report["parts"]["2"]["volume_m3"] == pytest.approx(math.pi * .25**2 * .3)
    assert min(n[0] for n in mesh["nodes"]) == 1000001


@pytest.mark.parametrize("change", [{"radial_cells": [True, 4]}, {"axial_cells": [3, 0, 2]}, {"radial_cells": [1000, 1000], "axial_cells": [1000, 1000, 1000]}, {"source_nodes": []}])
def test_invalid_mesh_cannot_silently_lose_interfaces_or_exceed_budget(change):
    spec = small_spec()
    spec["mesh"].update(change)
    with pytest.raises(ValueError):
        api("impact_1788_rebuild").build_keyword(spec)


def test_audit_detects_wrong_part_missing_cell_and_reversed_quad():
    module = api("impact_1788_mesh")
    spec = small_spec()
    mesh = module.build_mesh(spec["mesh"])
    for kind in ("part", "missing", "winding"):
        rows = deepcopy(mesh["elements"])
        if kind == "part": rows[0][1] = 1
        elif kind == "missing": rows.pop()
        else: rows[0][2:] = rows[0][2:][::-1]
        assert not module.audit_mesh(mesh["nodes"], rows, spec["mesh"])["ok"], kind


def test_keyword_options_materials_velocity_and_blank_fields_survive():
    module = api("impact_1788_rebuild")
    resources = api("impact_1788_resources")
    text, metadata = module.build_keyword(small_spec())
    assert text.startswith("*KEYWORD MEMORY=144000000 NCPU=1\n")
    cards = [c for r in resources.load_bundle() for c in r["source_cards"]]
    assert len(cards) == 24
    for card in cards:
        assert card["raw_text"].replace("\r\n", "\n") in text
    assert "*INITIAL_VELOCITY_GENERATION" in text and "-1788.0" in text
    assert "*BOUNDARY" not in text and "*CONTACT" not in text
    assert "2250.0" in text and "*MAT_JOHNSON_COOK_TITLE" in text
    assert metadata["source_mesh_used_for_generation"] is False


def test_source_hash_pin_rejects_changed_material_even_with_forged_card_hash():
    resources = api("impact_1788_resources")
    record = next(deepcopy(r) for r in resources.load_bundle() if r["original_ids"].get("mid") == 2)
    card = record["source_cards"][0]
    card["raw_text"] = card["raw_text"].replace("2250.0", "2180.0")
    card["raw_sha256"] = hashlib.sha256(card["raw_text"].encode()).hexdigest()
    from lsprepost_mcp.source_rebuild_resources import validate_resource
    with pytest.raises(ValueError): validate_resource(record)


def test_resource_publication_refuses_conflict_without_overwriting(tmp_path):
    resources = api("impact_1788_resources")
    records = resources.load_bundle()
    assert resources.publish_resources(records, tmp_path)["created"] == 22
    path = tmp_path / resources.resource_relative_path(records[0])
    path.write_text('{"user":true}', encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(FileExistsError): resources.publish_resources(records, tmp_path)
    assert path.read_bytes() == before


def test_library_queries_keep_second_source_separate_from_gran_materials():
    resources = api("impact_1788_resources")
    from lsprepost_mcp.materials import get_material, validate_material_resource, resolve_material
    from lsprepost_mcp.structural_resources import get_structural_resource, validate_structural_resource
    for record in resources.load_bundle():
        if record["resource_kind"] == "materials":
            found = get_material(record["id"])
            assert validate_material_resource(found)["valid"]
            with pytest.raises(ValueError, match="reconstruction"): resolve_material({"name": record["id"]})
        else:
            found = get_structural_resource(record["id"])
            assert validate_structural_resource(record["id"])["valid"]
        assert found["validation_status"] == "source_reference"
        assert found["provenance"]["source_sha256"] == "ad8b3fa71216379a66714ea2d9fdaf4db2d241bbadded064f00b98346e8829b8"


def test_real_project_provenance_preview_and_tamper_detection(tmp_path, monkeypatch):
    module = api("impact_1788_rebuild")
    from lsprepost_mcp import project_store, paths
    from lsprepost_mcp.provenance import verify_generated_project
    from lsprepost_mcp.tool_helpers import validate_project_required_keywords
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(paths, "PROJECTS_DIR", tmp_path)
    result = module.generate_project(small_spec())
    path = Path(result["project_dir"])
    assert result["checks"]["ok"], result["checks"]
    assert result["checks"]["readiness"]["ok_for_gui_preview"]
    assert not result["checks"]["readiness"]["ok_for_solver_draft"]
    assert verify_generated_project(path)["ok"]
    assert validate_project_required_keywords(path/"model.k", path/"model.json")["ok"]
    with pytest.raises(FileExistsError): module.generate_project(small_spec())
    original = (path/"model.k").read_text(encoding="utf-8")
    (path/"model.k").write_text(original.replace("-1788.0", "-1787.0"), encoding="utf-8")
    assert not project_store.validate_project_files(path)["ok"]
    assert not verify_generated_project(path)["ok"]
    (path/"model.k").write_text(original.replace("*SECTION_ALE2D_TITLE", "*SECTION_SHELL_TITLE"), encoding="utf-8")
    assert not validate_project_required_keywords(path/"model.k", path/"model.json")["ok"]


@pytest.mark.parametrize("field,value", [("geometry", {"steel_radius_m": .005}), ("unit_system", "mm-ms-tonne"), ("source_sha256", "unknown")])
def test_reconstruction_rejects_changed_physical_contract(field, value):
    spec = small_spec()
    spec[field] = value
    with pytest.raises(ValueError): api("impact_1788_rebuild").build_keyword(spec)


def test_mcp_prepare_estimates_full_mesh_without_generating_it():
    api("impact_1788_rebuild")
    from lsprepost_mcp.tools import TOOLS
    report = TOOLS["prepare_impact_1788_rebuild"][2]({})
    assert report["mesh_estimate"]["elements"] == 360000
    assert report["mesh_estimate"]["nodes"] == 361221
    assert report["model_generated"] is False
    with pytest.raises(ValueError): TOOLS["prepare_impact_1788_rebuild"][2]({"source_nodes": []})
