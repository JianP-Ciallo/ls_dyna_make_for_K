"""Small source-faithful reconstruction checks; no original mesh or solver needed."""
from collections import Counter
from copy import deepcopy
import hashlib
import importlib
import importlib.util
import json
import math
from pathlib import Path

import pytest


def api(name):
    module = "lsprepost_mcp." + name
    assert importlib.util.find_spec(module) is not None, "Missing controlled reconstruction implementation"
    return importlib.import_module(module)


def small_spec(name="gran_small"):
    return api("gran_r5_rebuild").default_spec(name, core_divisions=2, charge_layers=2, concrete_layers=3)


def test_small_mesh_preserves_domain_and_shared_material_interface():
    mesh_api = api("gran_r5_mesh")
    mesh = mesh_api.build_mesh(small_spec()["mesh"])
    assert len(mesh["nodes"]) == 541
    assert Counter(e[1] for e in mesh["elements"]) == {1: 24, 2: 466}
    nodes = {n[0]: n[1:4] for n in mesh["nodes"]}
    areas = []
    for e in mesh["elements"]:
        p = [nodes[n] for n in e[2:]]
        areas.append(sum(p[i][0]*p[(i+1)%4][1]-p[(i+1)%4][0]*p[i][1] for i in range(4))/2)
    assert min(areas) > 0
    assert sum(areas) == pytest.approx(1.62)
    assert min(nodes) > 1000000
    audit = mesh_api.audit_mesh(mesh["nodes"], mesh["elements"])
    assert audit["ok"]
    assert audit["connected_components"] == 1
    assert audit["interface_edges"] == 8
    assert audit["interface_nodes"] == 9
    assert audit["minimum_jacobian"] > 0
    assert audit["parts"]["1"]["volume_m3"] == pytest.approx(4*math.pi*.04**3/3, rel=.04)


@pytest.mark.parametrize("changes", [{"core_divisions":3}, {"core_divisions":True}, {"charge_layers":0}, {"core_divisions":10000}, {"source_nodes":[]}])
def test_invalid_mesh_inputs_do_not_silently_change_the_model(changes):
    module=api("gran_r5_rebuild")
    spec=small_spec()
    spec["mesh"].update(changes)
    with pytest.raises(ValueError):
        module.build_keyword(spec)


def test_resource_payload_is_pinned_even_if_declared_hash_is_recomputed():
    resources=api("source_rebuild_resources")
    record=deepcopy(resources.load_bundle()[0])
    card=record["source_cards"][0]
    card["raw_text"]=card["raw_text"].replace("1717.0","1700.0")
    card["raw_sha256"]=hashlib.sha256(card["raw_text"].encode()).hexdigest()
    with pytest.raises(ValueError):
        resources.validate_resource(record)


def test_resource_publication_refuses_to_replace_conflicting_existing_record(tmp_path):
    resources=api("source_rebuild_resources")
    records=resources.load_bundle()
    result=resources.publish_resources(records,tmp_path)
    material_file=next((tmp_path/"resources"/"materials").rglob("*.json"))
    material_file.write_text('{"existing_user_resource": true}',encoding="utf-8")
    before=material_file.read_bytes()
    with pytest.raises(FileExistsError):
        resources.publish_resources(records,tmp_path)
    assert material_file.read_bytes()==before
    assert result["resource_count"]==17


def test_compiler_preserves_every_nonmesh_payload_and_unknown_umat_fields():
    resources=api("source_rebuild_resources")
    keyword,metadata=api("gran_r5_rebuild").build_keyword(small_spec())
    cards=[c for r in resources.load_bundle() for c in r["source_cards"]]
    for card in cards:
        assert card["raw_text"].replace("\r\n","\n") in keyword
    assert "*MAT_USER_DEFINED_MATERIAL_MODELS" in keyword
    assert "*BOUNDARY" not in keyword and "*CONTACT" not in keyword
    assert "*MAT_CONCRETE_DAMAGE_REL3" not in keyword
    assert metadata["node_count"]==541
    assert metadata["element_count"]==490
    assert metadata["source_mesh_used_for_generation"] is False


def test_spec_rejects_unknown_physics_or_geometry_instead_of_ignoring_it():
    module=api("gran_r5_rebuild")
    spec=small_spec()
    spec["geometry"]={"charge_radius_m":.05}
    with pytest.raises(ValueError):
        module.build_keyword(spec)


def test_project_is_regenerable_and_tampered_mesh_is_rejected(tmp_path,monkeypatch):
    module=api("gran_r5_rebuild")
    from lsprepost_mcp import project_store, paths
    from lsprepost_mcp.provenance import verify_generated_project
    monkeypatch.setattr(project_store,"PROJECTS_DIR",tmp_path)
    monkeypatch.setattr(paths,"PROJECTS_DIR",tmp_path)
    result=module.generate_project(small_spec("gran_small_write"))
    project=Path(result["project_dir"])
    checks=project_store.validate_project_files(project)
    assert checks["ok"]
    assert checks["readiness"]["ok_for_gui_preview"] is True
    assert checks["readiness"]["ok_for_solver_draft"] is False
    assert verify_generated_project(project)["ok"]
    original=(project/"model.k").read_text(encoding="utf-8")
    altered=original.replace("1000001,0,", "1000001,0.001,",1)
    assert altered!=original
    (project/"model.k").write_text(altered,encoding="utf-8")
    assert not project_store.validate_project_files(project)["ok"]
    assert not verify_generated_project(project)["ok"]


def test_resource_library_queries_find_and_validate_both_materials_and_section():
    resources=api("source_rebuild_resources")
    from lsprepost_mcp.materials import get_material, validate_material_resource
    from lsprepost_mcp.structural_resources import get_structural_resource, validate_structural_resource
    records=resources.load_bundle()
    for record in records:
        if record["resource_kind"]=="materials":
            found=get_material(record["id"])
            assert validate_material_resource(found)["valid"]
        else:
            found=get_structural_resource(record["id"])
            assert validate_structural_resource(record["id"])["valid"]
        assert found["validation_status"]=="source_reference"
        assert found["unit_system"]=="SI_m_s_kg_N_Pa"


def test_generic_elastic_resolver_rejects_raw_physics_bundles_cleanly():
    from lsprepost_mcp.materials import resolve_material
    for resource_id in ("gran_r5_49abb80e7528_compb_mid1_eos1", "gran_r5_49abb80e7528_concrete_umat41_mid2"):
        with pytest.raises(ValueError, match="reconstruction"):
            resolve_material({"name":resource_id})


def test_gui_keyword_check_preserves_source_physics_and_detects_missing_section(tmp_path,monkeypatch):
    module=api("gran_r5_rebuild")
    from lsprepost_mcp import project_store, paths
    from lsprepost_mcp.tool_helpers import validate_project_required_keywords
    monkeypatch.setattr(project_store,"PROJECTS_DIR",tmp_path)
    monkeypatch.setattr(paths,"PROJECTS_DIR",tmp_path)
    result=module.generate_project(small_spec("gran_preview_check"))
    project=Path(result["project_dir"])
    report=validate_project_required_keywords(project/"model.k",project/"model.json")
    assert report["ok"], report
    keyword=(project/"model.k").read_text(encoding="utf-8")
    (project/"model.k").write_text(keyword.replace("*SECTION_ALE2D","*SECTION_SHELL"),encoding="utf-8")
    assert not validate_project_required_keywords(project/"model.k",project/"model.json")["ok"]
