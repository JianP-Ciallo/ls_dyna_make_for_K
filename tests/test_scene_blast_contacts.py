"""Small local junctions only; never run a building or a TNT case."""
from copy import deepcopy
import json
import time

import numpy as np
import pytest

from lsprepost_mcp.architecture.scene_blast.contracts import MATERIAL
from lsprepost_mcp.architecture.scene_blast.mechanics import rotation
from lsprepost_mcp.architecture.scene_blast.solver import MacroSystem, overlap_pairs
from lsprepost_mcp.architecture.scene_blast.sources import (
    add_interface, body_from_quad, connect_quad_edges, corners,
)


def four_plates():
    model = dict(bodies=[], springs=[])
    for x, y in [(0, 0), (1, 0), (0, 1), (1, 1)]:
        p = [[x, y, 1], [x+1, y, 1], [x+1, y+1, 1], [x, y+1, 1]]
        model['bodies'].append(body_from_quad(f'floor:{len(model["bodies"])}', p, .18))
    connect_quad_edges(model)
    return model


def bend_at_common_node(s):
    # Compatible small curvature about both axes, with finite thickness proxies.
    for i in range(4):
        x, y, _ = s.x0[i]
        s.x[i, 2] -= 1e-4*(x*x+y*y)
        s.R[i] = rotation(np.array([-2e-4*y, 2e-4*x, 0.]))


def column_plate_junction():
    model = four_plates()
    col = dict(id='column:0', component_id='column', role='column', fixed=False,
        center_m=[0, 0, .5], vertices_m=corners([-.15, -.15, 0], [.15, .15, 1]).tolist(),
        mass_kg=216., inertia_kg_m2=np.diag([18.405, 18.405, 3.24]).tolist())
    model['bodies'].append(col)
    add_interface(model, 4, 0, [0, 0, 1], [0, 0, 1.], [1., 0, 0], .3, .3, .5)
    add_interface(model, 4, -1, [0, 0, 0], [0, 0, -1.], [1., 0, 0], .3, .3, .5)
    return model


def test_diagonal_plates_use_local_common_node_without_new_contact_force():
    s = MacroSystem(four_plates()); bend_at_common_node(s)
    before = s.force_state()[0].copy()
    assert overlap_pairs(s) == set()
    report = s.contact_diagnostics
    diagonal = next(r for r in report['records'] if r['body_indices'] == [0, 3])
    assert diagonal['classification'] == 'connected_junction'
    assert len(diagonal['path']) == 2 and diagonal['penetration_m'] > 1e-6
    assert np.array_equal(before, s.force_state()[0])


def test_column_slab_side_node_uses_local_slab_path():
    model = column_plate_junction()
    # Split the first slab at x=.15: the column attaches to the narrow tile,
    # while the adjoining wide slab has no direct column spring (saved failure).
    model['bodies'][0] = body_from_quad('floor:narrow', [[0,0,1],[.15,0,1],[.15,1,1],[0,1,1]], .18)
    model['bodies'][1] = body_from_quad('floor:wide', [[.15,0,1],[1,0,1],[1,1,1],[.15,1,1]], .18)
    model['bodies'] = [model['bodies'][0], model['bodies'][1], model['bodies'][4]]
    model['springs'] = []; connect_quad_edges(model, [0, 1])
    add_interface(model, 2, 0, [0,0,1], [0,0,1.], [1.,0,0], .3,.3,.5)
    s = MacroSystem(model); s.x[:2, 0] -= 2e-5
    assert overlap_pairs(s) == set()
    contact = next(r for r in s.contact_diagnostics['records'] if r['body_indices'] == [1,2])
    assert contact['classification'] == 'connected_junction' and len(contact['path']) == 2


def test_column_foot_and_fixed_slab_share_only_local_foundation_support():
    model = column_plate_junction(); col = model['bodies'][4]
    floor = body_from_quad('base:0', [[-1,-1,-.09],[1,-1,-.09],[1,1,-.09],[-1,1,-.09]], .18)
    floor['fixed'] = True
    model = dict(bodies=[floor, col], springs=[])
    add_interface(model, 1,-1,[0,0,0],[0,0,-1.],[1.,0,0],.3,.3,.5)
    s = MacroSystem(model); s.x[1,2] -= 1e-5
    assert overlap_pairs(s) == set()
    record = s.contact_diagnostics['records'][0]
    assert record['classification'] == 'connected_junction'
    assert any(edge['kind'] == 'fixed_support' for edge in record['path'])


def test_balcony_corner_finds_path_at_shared_edge_not_only_contact_centroid():
    # The saved balcony contacts have a centroid outside the interior slab,
    # but a real three-facet path at the end of the shared column/slab edge.
    quads = [([[0,0,1],[.15,0,1],[.15,1,1],[0,1,1]], 'narrow'),
        ([[.15,0,1],[1,0,1],[1,1,1],[.15,1,1]], 'inside'),
        ([[.15,-1,1],[1,-1,1],[1,0,1],[.15,0,1]], 'balcony')]
    model = dict(bodies=[body_from_quad(name,p,.18) for p,name in quads],springs=[])
    model['bodies'].append(column_plate_junction()['bodies'][4])
    connect_quad_edges(model,[0,1,2])
    add_interface(model,3,0,[0,0,1],[0,0,1.],[1.,0,0],.3,.3,.5)
    s = MacroSystem(model); s.x[2,0] -= 2e-5
    assert overlap_pairs(s) == set()
    record = next(r for r in s.contact_diagnostics['records'] if r['body_indices']==[2,3])
    assert len(record['path']) == 3 and record['junction_point_m'][1] == pytest.approx(0.)


@pytest.mark.parametrize('broken', [False, True])
def test_same_name_or_fully_broken_local_path_does_not_whitelist_collision(broken):
    model = four_plates()
    if not broken: model['springs'] = []
    s = MacroSystem(model); bend_at_common_node(s)
    if broken: s.damage[:] = 1.; s.broken[:] = True
    assert (0, 3) in overlap_pairs(s)
    record = next(r for r in s.contact_diagnostics['records'] if r['body_indices'] == [0,3])
    assert record['classification'] == 'unsupported_collision'
    assert record['penetration_m'] > 1e-6


def test_remote_graph_path_cannot_excuse_a_collision_at_the_other_end():
    model = four_plates()
    # Two bodies touch at (1,1), but their spring is artificially far away.
    model['bodies'] = [model['bodies'][0], model['bodies'][3]]; model['springs'] = []
    add_interface(model,0,1,[10,10,1],[1.,0,0],[0,1.,0],.2,.18,1.)
    s = MacroSystem(model); s.x[1,:2] -= 2e-5
    assert overlap_pairs(s) == {(0,1)}


def test_intact_direct_bond_cannot_hide_large_interpenetration_or_folding():
    for mode in ['translation', 'rotation']:
        model = four_plates(); model['bodies'] = model['bodies'][:2]
        model['springs'] = []; connect_quad_edges(model)
        s = MacroSystem(model)
        if mode == 'translation': s.x[1,0] -= .1
        else:
            s.R[1] = rotation(np.array([0., 1., 0.]))
            # Rotate about the shared edge: its midpoint remains continuous.
            p = np.array([1., .5, 1.]); s.x[1] = p+s.R[1]@(s.x0[1]-p)
        assert overlap_pairs(s) == {(0,1)}, mode
        assert s.contact_diagnostics['records'][0]['reason_code'] == 'joint_kinematics_exceeded'


@pytest.mark.parametrize('offset,facet_width,point_y', [(0.,.2,0.),(.95,.2,.1),(0.,1.,.5)])
def test_corner_bond_cannot_whitelist_initial_overlap_outside_its_support(offset,facet_width,point_y):
    # Review regression: a single valid corner point cannot grandfather a whole
    # duplicate slab; even a shallow overlap must fit the physical junction patch.
    a = body_from_quad('a',[[0,0,1],[1,0,1],[1,1,1],[0,1,1]],.18)
    b = deepcopy(a); b['id']='b'
    b['vertices_m'] = (np.array(b['vertices_m'])+[offset,0,0]).tolist(); b['center_m'][0] += offset
    model = dict(bodies=[a,b],springs=[])
    add_interface(model,0,1,[1 if offset else 0,point_y,1],[1.,0,0],[0,1.,0],facet_width,.18,1.)
    s = MacroSystem(model)
    assert overlap_pairs(s) == {(0,1)}
    record = s.contact_diagnostics['records'][0]
    assert record['reason_code'] == 'reference_overlap_outside_junction'


def test_initial_unconnected_overlap_is_rejected_with_poses_before_gravity():
    from lsprepost_mcp.architecture.scene_blast.gravity import GravityFailure
    model = four_plates(); model['bodies'] = model['bodies'][:2]; model['springs'] = []
    for b in model['bodies']: b['fixed'] = True
    model['bodies'][1]['vertices_m'] = (np.array(model['bodies'][1]['vertices_m'])-[.01,0,0]).tolist()
    model['bodies'][1]['center_m'][0] -= .01
    s = MacroSystem(model)
    with pytest.raises(GravityFailure) as caught: s.equilibrate()
    d = caught.value.diagnostics
    assert d['reason_code'] == 'unsupported_gravity_contact' and not d['blast_applied']
    record = d['contact_diagnostics']['records'][0]
    assert record['penetration_m'] == pytest.approx(.01)
    assert np.linalg.norm(record['normal']) == pytest.approx(1.)
    assert len(record['poses']) == 2 and d['restored_to_accepted_state']
    json.dumps(d, allow_nan=False)


def test_common_rigid_motion_does_not_change_joint_classification():
    s = MacroSystem(four_plates()); bend_at_common_node(s)
    assert overlap_pairs(s) == set()
    Q = rotation(np.array([.1,-.2,.3])); shift = np.array([4.,-3.,2.])
    s.x[:s.count] = s.x[:s.count]@Q.T+shift; s.R[:s.count] = Q@s.R[:s.count]
    assert overlap_pairs(s) == set()


def test_four_plate_cantilever_balances_true_gravity_and_holds_without_new_support(tmp_path):
    model = four_plates()
    for i in [0,2]:
        add_interface(model,i,-1,[0, .5+(i//2),1],[-1.,0,0],[0,1.,0],1.,.18,.5)
    saved = deepcopy(model); s = MacroSystem(model); initial_mass = s.mass.copy(); started = time.perf_counter()
    assert s.equilibrate() < 1e-5
    gravity_wall_s = time.perf_counter()-started
    d = s.gravity_diagnostics
    assert d['accepted_load_factor'] == 1.
    assert d['final']['support_reaction_n'][2] == pytest.approx(16945.8912, rel=1e-5)
    assert d['contact_diagnostics']['unsupported_pairs'] == 0
    assert d['contact_diagnostics']['connected_junction_pairs'] > 0
    equilibrium = s.x.copy()
    for _ in range(50):
        s.step(min(s.dt_stable*.25, .0001))
        assert overlap_pairs(s) == set()
    assert np.max(abs(s.x-equilibrium)) < 1e-8
    assert np.array_equal(initial_mass, s.mass) and model == saved and s.mat == MATERIAL
    (tmp_path/'four-plate-gravity.json').write_text(json.dumps(d,indent=2),encoding='utf8')
    (tmp_path/'four-plate-summary.json').write_text(json.dumps(dict(fixture='FOUR_PLATE_CANTILEVER_ONLY',
        gravity_wall_s=gravity_wall_s,force_residual_n=d['final']['force_residual_n'],
        relative_residual=d['final']['scaled_relative_residual'],reaction_n=d['final']['support_reaction_n'],
        max_translation_mm=float(np.max(np.linalg.norm(s.x[:4]-s.x0[:4],axis=1))*1000),
        steel_mpa=float(np.max(abs(s.stress[s.steel]))/1e6),max_damage=float(s.damage.max()),
        hold_steps=50,hold_drift_m=float(np.max(abs(s.x-equilibrium))),material=s.mat),indent=2),encoding='utf8')


def test_symmetric_column_slab_and_foot_balance_gravity_without_contact_support(tmp_path):
    model = four_plates()
    for b in model['bodies']:
        b['vertices_m'] = (np.array(b['vertices_m'])-[1,1,0]).tolist()
        b['quad_m'] = (np.array(b['quad_m'])-[1,1,0]).tolist()
        b['center_m'] = (np.array(b['center_m'])-[1,1,0]).tolist()
    col = column_plate_junction()['bodies'][4]
    base = body_from_quad('base:0',[[-1,-1,-.09],[1,-1,-.09],[1,1,-.09],[-1,1,-.09]],.18)
    base['fixed'] = True; model['bodies'] += [col,base]
    model['springs']=[]; connect_quad_edges(model,[0,1,2,3])
    for i in range(4):
        start = len(model['springs'])
        add_interface(model,4,i,[0,0,1],[0,0,1.],[1.,0,0],.3,.3,.5)
        for spring in model['springs'][start:]: spring['area_m2'] /= 4
    add_interface(model,4,-1,[0,0,0],[0,0,-1.],[1.,0,0],.3,.3,.5)
    s = MacroSystem(model); saved = deepcopy(model); mass = s.mass.copy(); started = time.perf_counter()
    assert s.equilibrate() < 1e-5
    gravity_wall_s = time.perf_counter()-started
    d = s.gravity_diagnostics
    assert d['final']['support_reaction_n'][2] == pytest.approx(19064.1276, rel=1e-5)
    assert d['contact_diagnostics']['unsupported_pairs'] == 0
    assert any(r['body_indices']==[4,5] and r['classification']=='connected_junction'
        for r in d['contact_diagnostics']['records'])
    x = s.x.copy()
    for _ in range(50):
        s.step(min(s.dt_stable*.25,.0001))
        assert overlap_pairs(s) == set()
    assert np.max(abs(s.x-x)) < 1e-8
    assert np.array_equal(s.mass,mass) and model == saved and s.mat == MATERIAL
    (tmp_path/'column-slab-gravity.json').write_text(json.dumps(d,indent=2),encoding='utf8')
    (tmp_path/'column-slab-summary.json').write_text(json.dumps(dict(fixture='FOUR_PLATES_ONE_COLUMN_ONE_FIXED_BASE_ONLY',
        gravity_wall_s=gravity_wall_s,force_residual_n=d['final']['force_residual_n'],
        relative_residual=d['final']['scaled_relative_residual'],reaction_n=d['final']['support_reaction_n'],
        max_translation_mm=float(np.max(np.linalg.norm(s.x[:6]-s.x0[:6],axis=1))*1000),
        steel_mpa=float(np.max(abs(s.stress[s.steel]))/1e6),max_damage=float(s.damage.max()),
        hold_steps=50,hold_drift_m=float(np.max(abs(s.x-x))),material=s.mat),indent=2),encoding='utf8')


def test_dynamic_collision_keeps_contact_depth_and_pose_in_partial_result(tmp_path):
    from lsprepost_mcp.architecture.scene_blast.contracts import normalize_input,snapshot
    from lsprepost_mcp.architecture.scene_blast.solver import solve
    from lsprepost_mcp.architecture.scene_blast.sources import shell_model,finish
    m = shell_model('MICRO_WALL_ONLY',[(1,0,0,0),(2,1,0,0),(3,1,0,1),(4,0,0,1)],[(1,1,1,2,3,4)],.2)
    obstacle = deepcopy(m['bodies'][0]); obstacle.update(id='fixed_obstacle',fixed=True)
    obstacle['center_m'][1] += .200003
    obstacle['vertices_m'] = (np.array(obstacle['vertices_m'])+[0,.200003,0]).tolist()
    m['bodies'].append(obstacle); finish(m)
    m.update(source=dict(kind='commercial_supermarket',fixture='TWO_BLOCK_DYNAMIC_COLLISION_ONLY'),assumptions=[])
    c = normalize_input(dict(source=dict(kind='commercial_supermarket'),tnt=dict(position_m=[0,-1,0],mass_kg=.01),analysis=dict(duration_s=.05)))
    r = solve(snapshot(c,m))
    assert r['status'] == 'partial' and r['metrics']['completed_steps'] > 0
    d = r['metrics']['block_contacts']
    assert d['unsupported_pairs'] == 1 and d['records'][0]['penetration_m'] > 1e-6
    assert len(d['records'][0]['poses']) == 2
    assert r['frames'][-1]['time_s'] < .05
    (tmp_path/'micro-partial-result.json').write_text(json.dumps(r,indent=2),encoding='utf8')


def test_worker_preserves_new_contact_poses_and_sealed_diagnostics(tmp_path):
    import time
    from lsprepost_mcp.architecture.scene_blast.contracts import normalize_input
    from lsprepost_mcp.architecture.scene_blast.service import SceneBlastService
    from lsprepost_mcp.architecture.scene_blast.sources import finish
    def prepare(config):
        m = four_plates(); m['bodies'] = m['bodies'][:2]; m['springs']=[]
        # Keep the left body free but bonded to ground; the right fixed body
        # overlaps it by 10 mm, with no local joint or artificial support.
        m['bodies'][1]['fixed'] = True
        m['bodies'][1]['vertices_m'] = (np.array(m['bodies'][1]['vertices_m'])-[.01,0,0]).tolist()
        m['bodies'][1]['center_m'][0] -= .01
        add_interface(m,0,-1,[0,.5,1],[-1.,0,0],[0,1.,0],1.,.18,.5)
        m.update(source=dict(config['source'],fixture='TWO_BLOCK_CONTACT_DIAG_ONLY'),assumptions=[],
            envelopes=[dict(min_m=[0,0,.91],max_m=[2,1,1.09])],
            surfaces=[dict(point_m=[.5,0,1],normal=[0.,-1.,0.],area_m2=.18,weights=[[0,1.]])])
        return finish(m)
    service = SceneBlastService(tmp_path,prepare=prepare)
    try:
        c = normalize_input(dict(source=dict(kind='commercial_supermarket'),tnt=dict(position_m=[0,-5,0],mass_kg=.01)))
        p = service.prepare(c)
        j = service.submit(dict(input=c,model_fingerprint=p['model_fingerprint'],request_id='8'*32))
        deadline = time.monotonic()+10
        while time.monotonic()<deadline:
            j = service.job(j['run_id'])
            if j['status'] not in {'queued','running'}: break
            time.sleep(.02)
        assert j['status'] == 'failed'
        d = service.gravity(j['run_id'])
        assert d['reason_code'] == 'unsupported_gravity_contact' and not d['blast_applied']
        assert d['accepted_load_factor'] == 0. and d['restored_to_accepted_state']
        record = d['contact_diagnostics']['records'][0]
        assert record['classification'] == 'unsupported_collision'
        assert record['penetration_m'] == pytest.approx(.01) and len(record['poses']) == 2
        assert j['gravity_sha256'] and not (tmp_path/'runs'/j['run_id']/'result.json').exists()
    finally: service.close()
