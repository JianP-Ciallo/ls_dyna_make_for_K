"""Small source-fidelity cases; the million-cell user model is not a test fixture."""
from collections import Counter
from copy import deepcopy
import hashlib
import importlib
import importlib.util
import math
from pathlib import Path

import pytest


def api(name):
    module = 'lsprepost_mcp.b120_spg_sale_' + name
    assert importlib.util.find_spec(module) is not None, 'Third-model reconstruction adapter is missing'
    return importlib.import_module(module)


def small_mesh():
    return {'core_divisions': 2, 'core_radial_layers': 1, 'bore_transition_layers': 1,
            'outer_extension_cells': 2, 'outer_radial_layers': 2, 'axial_step_m': .2}


def small_spec():
    return api('rebuild').default_spec('b120_small', mesh=small_mesh())


def test_regions_hole_rings_and_interfaces_are_rebuilt_without_source_tables():
    recipe = api('mesh').build_recipe(small_mesh())
    nodes = {int(n[0]): tuple(n[1:]) for n in recipe.iter_nodes()}
    elements = list(recipe.iter_elements())
    assert len(nodes) == 2740
    assert Counter(e[1] for e in elements) == {2: 840, 4: 300, 5: 300, 6: 408}
    assert min(nodes) == 2000001
    members = {p: {n for e in elements if e[1] == p for n in e[2:]} for p in (2, 4, 5, 6)}
    assert len(members[4] & members[5]) == 113
    assert all(nodes[n][2] == -1.04 for n in members[4] & members[5])
    assert not members[2] & members[4]
    assert not members[6] & (members[2] | members[4] | members[5])
    concrete_plane = {nodes[n] for n in members[2] if nodes[n][2] == -.54}
    c5_plane = {nodes[n] for n in members[4] if nodes[n][2] == -.54}
    assert concrete_plane == c5_plane and len(c5_plane) == 113
    for nid in members[2]:
        x, y, z = nodes[nid]
        assert -.54 <= z <= .86 and math.hypot(x, y) <= 1.05 + 1e-10
        if z > 0: assert math.hypot(x, y) >= .049 - 1e-10
    for e in elements:
        if e[1] != 6: continue
        p = [nodes[n] for n in e[2:]]
        if max(math.hypot(x, y) for x, y, _ in p) > 1.067:
            zs = [v[2] for v in p]
            assert (-.42 <= min(zs) < max(zs) <= -.26) or (.7 <= min(zs) < max(zs) <= .86)
    assert set(nodes) == set.union(*members.values())


def test_actual_small_hex_jacobians_and_volumes_agree_with_geometry():
    from lsprepost_mcp.keyword_checks import hexa_gauss_jacobians
    recipe = api('mesh').build_recipe(small_mesh())
    nodes = {n[0]: tuple(n[1:]) for n in recipe.iter_nodes()}
    volumes = Counter()
    for e in recipe.iter_elements():
        dets = hexa_gauss_jacobians(nodes, tuple(e[2:]))
        assert min(dets) > 0, e
        volumes[e[1]] += sum(dets)
    disk = 24 * 1.05**2 * math.sin(2*math.pi/24)/2
    bore = 8 * .049**2 * math.sin(2*math.pi/8)/2
    assert volumes[2] == pytest.approx(disk*1.4-bore*.86, rel=1e-9)
    assert volumes[4] == pytest.approx(disk*.5, rel=1e-9)
    assert volumes[5] == pytest.approx(disk*.5, rel=1e-9)
    steel = 24/2*math.sin(2*math.pi/24)*((1.066**2-1.05**2)*2.4+(1.086**2-1.066**2)*.32)
    assert volumes[6] == pytest.approx(steel, rel=1e-9)


def test_bottom_bindings_select_all_and_only_correct_nodes_and_faces():
    recipe = api('mesh').build_recipe(small_mesh())
    nodes = {n[0]: tuple(n[1:]) for n in recipe.iter_nodes()}
    fixed = list(recipe.iter_bottom_nodes())
    faces = list(recipe.iter_bottom_segments())
    assert len(fixed) == 161 and len(faces) == 124
    assert set(fixed) == {n for n, p in nodes.items() if p[2] == -1.54}
    assert set(fixed) == {n for f in faces for n in f}
    for f in faces:
        assert all(nodes[n][2] == -1.54 for n in f)
        a, b, c = [nodes[n] for n in f[:3]]
        assert (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]) < 0


@pytest.mark.parametrize('change', [{'core_divisions': True}, {'core_divisions': 3},
    {'axial_step_m': 0}, {'axial_step_m': float('nan')}, {'core_divisions': 64, 'outer_extension_cells': 64,
    'outer_radial_layers': 64, 'axial_step_m': .001}, {'source_nodes': []}])
def test_mesh_rejects_invalid_or_unbounded_parameters(change):
    raw = small_mesh(); raw.update(change)
    with pytest.raises(ValueError): api('mesh').build_recipe(raw)


def test_all_physics_cards_survive_and_mesh_references_are_regenerated():
    text = ''.join(api('rebuild').iter_keyword(small_spec()))
    records = api('resources').load_bundle()
    assert len(records) == 47
    exact = [c for r in records if r['reuse_policy'] == 'exact_original_card_payload' for c in r['source_cards']]
    assert len(exact) == 46
    for c in exact: assert c['raw_text'].replace('\r\n', '\n') in text
    assert '*SECTION_SOLID_SPG' in text and '*ALE_COUPLING_NODAL_PENALTY_ID' in text
    assert 'SALEFAC' in text and '9000001' in text
    assert text.count('*NODE\n') == 1 and text.count('*ELEMENT_SOLID\n') == 1
    assert api('rebuild').default_spec()['geometry']['steel_bands_z'] == [[-.42, -.26], [.7, .86]]


@pytest.mark.parametrize('field', ['material', 'selector', 'dependencies', 'unit'])
def test_resource_pin_rejects_changes_even_if_payload_hash_is_forged(field):
    module = api('resources'); records = deepcopy(module.load_bundle())
    if field == 'material':
        r = next(r for r in records if r['original_ids'].get('mid') == 2 and r['resource_kind'] == 'materials')
        c = r['source_cards'][0]; c['raw_text'] = c['raw_text'].replace('2500.0', '2400.0')
        assert '2400.0' in c['raw_text']
        c['raw_sha256'] = hashlib.sha256(c['raw_text'].encode()).hexdigest()
    elif field == 'selector':
        r = next(r for r in records if r['id'].endswith('node_set1_bottom'))
        r['binding_recipe']['selector'] = 'all nodes'
    elif field == 'dependencies':
        r = next(r for r in records if r['id'].endswith('coupling1')); r['dependencies'] = []
    else:
        r = records[0]; r['unit_system'] = 'mm-ms-tonne'
    with pytest.raises(ValueError): module.validate_resource(r)


def test_resources_are_queryable_and_conflicts_never_overwrite(tmp_path):
    module = api('resources'); records = module.load_bundle()
    from lsprepost_mcp.materials import get_material, validate_material_resource
    from lsprepost_mcp.structural_resources import get_structural_resource, validate_structural_resource
    for r in records:
        if r['resource_kind'] == 'materials': assert validate_material_resource(get_material(r['id']))['valid']
        else:
            assert get_structural_resource(r['id'])['id'] == r['id']
            assert validate_structural_resource(r['id'])['valid']
    assert module.publish_resources(records, tmp_path)['created'] == 47
    p = tmp_path / module.resource_relative_path(records[0]); p.write_text('{"user":true}')
    before = p.read_bytes()
    with pytest.raises(FileExistsError): module.publish_resources(records, tmp_path)
    assert p.read_bytes() == before


def test_project_generation_provenance_required_cards_and_tampering(tmp_path, monkeypatch):
    from lsprepost_mcp import project_store, paths
    from lsprepost_mcp.provenance import verify_generated_project
    from lsprepost_mcp.tool_helpers import validate_project_required_keywords
    monkeypatch.setattr(project_store, 'PROJECTS_DIR', tmp_path)
    monkeypatch.setattr(paths, 'PROJECTS_DIR', tmp_path)
    module = api('rebuild'); result = module.generate_project(small_spec())
    p = Path(result['project_dir'])
    assert result['checks']['ok'], result['checks']
    assert not result['checks']['readiness']['ok_for_solver_draft']
    assert verify_generated_project(p)['ok']
    assert validate_project_required_keywords(p/'model.k', p/'model.json')['ok']
    with pytest.raises(FileExistsError): module.generate_project(small_spec())
    original = (p/'model.k').read_text(encoding='utf-8')
    (p/'model.k').write_text(original.replace('SALEFAC', 'BADFACE'), encoding='utf-8')
    assert not project_store.validate_project_files(p)['ok']
    assert not verify_generated_project(p)['ok']
    (p/'model.k').write_text(original.replace('*SECTION_SOLID_SPG', '*SECTION_SOLID'), encoding='utf-8')
    assert not validate_project_required_keywords(p/'model.k', p/'model.json')['ok']


@pytest.mark.parametrize('field,value', [('unit_system','mm-ms-tonne'), ('source_sha256','unknown'),
    ('geometry',{'body_radius': 1.2}), ('source_nodes',[])])
def test_spec_rejects_changed_physics_or_original_mesh_input(field, value):
    spec = small_spec(); spec[field] = value
    with pytest.raises(ValueError): list(api('rebuild').iter_keyword(spec))


def test_mcp_prepare_estimates_the_approved_model_without_full_generation():
    api('rebuild')
    from lsprepost_mcp.tools import TOOLS
    report = TOOLS['prepare_b120_spg_sale_rebuild'][2]({})
    assert report['mesh_estimate']['elements'] == 947200
    assert report['mesh_estimate']['nodes'] == 1000415
    assert report['model_generated'] is False
    with pytest.raises(ValueError): TOOLS['prepare_b120_spg_sale_rebuild'][2]({'old_mesh': []})
