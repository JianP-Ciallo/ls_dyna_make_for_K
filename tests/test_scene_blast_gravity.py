"""One/two-block fixtures only. Never solve the actual three-storey building."""
from copy import deepcopy
import json

import numpy as np
import pytest

from lsprepost_mcp.architecture.scene_blast.contracts import MATERIAL
from lsprepost_mcp.architecture.scene_blast.mechanics import rotation
from lsprepost_mcp.architecture.scene_blast.solver import MacroSystem
from lsprepost_mcp.architecture.scene_blast.sources import add_interface, corners


def hanging_block(mass=10000., steel_ratio=.005):
    # A 0.04 m2 hanger section, 0.05 m gauge length; lumped supported payload.
    # Constitutive parameters are the production defaults, not strengthened.
    model = {'bodies': [dict(id='payload', component_id='hanger', center_m=[0., 0., 1.],
        vertices_m=corners([-.1, -.1, .95], [.1, .1, 1.05]).tolist(),
        mass_kg=mass, inertia_kg_m2=np.diag([mass*.0125/12, mass*.0125/12, mass*.02/12]).tolist(),
        fixed=False)], 'springs': []}
    add_interface(model, 0, -1, [0., 0., 1.05], [0., 0., 1.], [1., 0., 0.], .2, .2, .05, steel_ratio=steel_ratio)
    return model


def test_gravity_cracks_hanger_and_balances_weight_with_unchanged_material(tmp_path):
    # Rejecting nonlinear states or balancing with elastic forces breaks this test.
    model = hanging_block(); original = deepcopy(model); s = MacroSystem(model)
    assert s.equilibrate() < 1e-5
    # Independent piecewise section force: cracked concrete + elastic steel.
    # Defaults: E=30GPa, ft=2MPa, Gf=200N/m, Es=200GPa, rho=0.005.
    expected_opening = (10000*9.80665/.04 - .995*2e6*.0002/(.0002-2e6/(30e9/.05))) / (
        .005*200e9/.05 - .995*2e6/(.0002-2e6/(30e9/.05)))
    assert 1.-s.x[0, 2] == pytest.approx(expected_opening, rel=2e-5)
    f, torque = s.forces(commit=False)
    assert f[0, 2] == pytest.approx(98066.5, rel=1e-5)
    assert np.linalg.norm(torque[0]) < 1e-5
    assert np.any(s.damage > .5) and np.max(abs(s.stress[s.steel])) > 100e6
    assert s.mat == MATERIAL and model == original
    initial = s.x.copy()
    for _ in range(30):
        s.step(.25*s.dt_stable)
    assert np.max(np.abs(s.x-initial)) < 1e-8
    d = s.gravity_diagnostics
    assert d['status'] == 'converged' and d['accepted_load_factor'] == 1.
    assert d['final']['force_residual_n'] < 1.
    assert d['final']['connections']['cracked_concrete'] > 0
    assert d['final']['support_reaction_n'][2] == pytest.approx(98066.5, rel=1e-5)
    assert d['final']['worst_body']['body_id'] == 'payload'
    json.dumps(d, allow_nan=False)
    (tmp_path/'gravity.json').write_text(json.dumps(d,indent=2),encoding='utf8')
    (tmp_path/'summary.json').write_text(json.dumps(dict(kind='ONE_BLOCK_HANGER_ONLY',
        opening_m=float(1-s.x[0,2]),analytic_opening_m=expected_opening,
        steel_stress_mpa=float(np.max(abs(s.stress[s.steel]))/1e6),damage=float(s.damage.max()),
        material=s.mat,weight_n=98066.5,initial_hold_max_drift_m=float(np.max(abs(s.x-initial))))),encoding='utf8')


def test_current_tangent_matches_force_difference_without_history_pollution():
    # An elastic/frozen tangent, wrong rotation sign, or committed trial history breaks this.
    s = MacroSystem(hanging_block())
    s.x[0] += [2e-5, -1e-5, -4e-5]
    s.R[0] = rotation(np.array([1e-4, -2e-4, 1e-4]))
    saved = {key: getattr(s, key).copy() for key in ('history','plastic','accumulated_plastic','compression_plastic','shear_plastic','broken','damage','stress')}
    tangent = s.current_stiffness()
    x, R = s.x.copy(), s.R.copy()
    direction = np.array([[.1, -.2, .3, -.4, .5, -.6], [0,0,0,0,0,0]])
    eps=1e-8
    s.x=x+eps*direction[:,:3];s.R=rotation(eps*direction[:,3:])@R
    fp,tp=s.forces(commit=False)
    s.x=x-eps*direction[:,:3];s.R=rotation(-eps*direction[:,3:])@R
    fm,tm=s.forces(commit=False)
    derivative=np.c_[fp-fm,tp-tm].ravel()/(2*eps)
    assert tangent@direction.ravel() == pytest.approx(-derivative, rel=2e-4, abs=2.)
    for key, value in saved.items():
        assert np.array_equal(getattr(s,key), value), key


def test_unreinforced_hanger_over_capacity_fails_with_traceable_rollback():
    # No equilibrium exists above ft*A; accepting a small increment is a false pass.
    s=MacroSystem(hanging_block(10000., steel_ratio=0))
    with pytest.raises(ValueError) as caught:
        s.equilibrate()
    diagnostic=caught.value.diagnostics
    assert diagnostic['status']=='failed' and diagnostic['accepted_load_factor']<1
    assert diagnostic['blast_applied'] is False
    assert diagnostic['attempts'] and diagnostic['final']['scaled_relative_residual']>1e-5
    assert diagnostic['final']['worst_connection']['a_body_id']=='payload'
    assert diagnostic['restored_to_accepted_state'] is True
    assert np.max(s.damage)<1e-6  # rejected excursions past capacity must not create cracks
    json.dumps(diagnostic,allow_nan=False)


def test_failed_gravity_saves_distinct_replayable_trial_and_accepted_states(tmp_path):
    from lsprepost_mcp.architecture.scene_blast.gravity import STATE,residual,restore
    s=MacroSystem(hanging_block(10000.,steel_ratio=0))
    with pytest.raises(ValueError) as caught:s.equilibrate()
    d=caught.value.diagnostics
    checkpoints=d['state_checkpoints']
    assert set(checkpoints)=={'accepted','rejected_trial'}
    for name,expected in [('accepted',d['accepted_load_factor']),('rejected_trial',d['last_trial']['load_factor'])]:
        item=checkpoints[name]
        assert item['load_factor']==expected
        assert item['history_status']=='committed_history_at_trial_pose'
        state={key:np.asarray(item['state'][key],dtype=getattr(s,key).dtype) for key in STATE}
        clone=MacroSystem(hanging_block(10000.,steel_ratio=0));restore(clone,state)
        info=residual(clone,expected)[1]
        assert info['scaled_relative_residual']==pytest.approx(item['residual']['scaled_relative_residual'],abs=1e-12)
        for key in STATE:
            if name=='accepted':assert np.array_equal(getattr(s,key),state[key]),key
    assert checkpoints['accepted']['state']['x']!=checkpoints['rejected_trial']['state']['x']
    assert d['failure_interpretation']=='equilibrium_not_established_not_a_capacity_certificate'
    searched=[i for i in d['iterations'] if i.get('line_search')]
    assert searched
    for record in searched:
        trials=record['line_search']
        assert 1<=len(trials)<=16
        assert all('relative_residual' in t and 'projected_work_nm' in t for t in trials)
        # On failure report the alpha actually evaluated, not the next halved alpha.
        assert record['line_search_alpha']==trials[-1]['alpha']
    (tmp_path/'replayable-failure.json').write_text(json.dumps(d,indent=2,allow_nan=False),encoding='utf8')


def test_nonfinite_trial_can_be_saved_without_losing_accepted_state():
    # Reproduce arithmetic failure in a small trial, without poisoning its inputs
    # or replacing constitutive force with a stub.
    s=MacroSystem(hanging_block());initial=s.x.copy();injected=[]
    def overflow_trial(d):
        if d['iterations'] and not injected:s.x[0,2]=np.nan;injected.append(True)
    with np.errstate(invalid='ignore'),pytest.raises(ValueError) as caught:
        s.equilibrate(diagnostics=overflow_trial)
    d=caught.value.diagnostics
    assert d['reason_code'] in {'nonfinite_response','singular_tangent'}
    assert np.array_equal(s.x,initial)
    json.dumps(d,allow_nan=False)
    assert d['state_checkpoints']['rejected_trial']['state']['x'][0][2] is None
    assert d['state_checkpoints']['rejected_trial']['contains_nonfinite'] is True


def test_small_slab_bending_balances_full_weight_and_holds_equilibrium(tmp_path):
    mass=1000.
    model={'bodies':[dict(id='strip',component_id='micro-slab',center_m=[.35,0,1.],
        vertices_m=corners([0,-.1,.91],[.7,.1,1.09]).tolist(),mass_kg=mass,
        inertia_kg_m2=(np.diag([.2**2+.18**2,.7**2+.18**2,.7**2+.2**2])*mass/12).tolist(),fixed=False)],'springs':[]}
    add_interface(model,0,-1,[0,0,1],[-1,0,0],[0,1,0],.2,.18,.7)
    original=deepcopy(model);s=MacroSystem(model)
    assert s.equilibrate()<1e-5
    assert s.mat==MATERIAL and model==original
    assert np.max(s.damage)==0 and np.max(abs(s.stress[s.steel]))<400e6
    f,t=s.forces(commit=False)
    assert f[0]==pytest.approx([0,0,mass*9.80665],abs=.05)
    assert t[0]==pytest.approx([0,0,0],abs=.05)
    # Independent global moment balance about the foundation anchor [0,0,1].
    assert t[-1]+np.cross(s.x[-1]-[0,0,1],f[-1])==pytest.approx(
        np.cross(s.x[0]-[0,0,1],[0,0,-mass*9.80665]),abs=.05)
    initial=s.x.copy()
    for _ in range(50):s.step(.25*s.dt_stable)
    assert np.max(abs(s.x-initial))<1e-8
    (tmp_path/'slab-bending.json').write_text(json.dumps(s.gravity_diagnostics,indent=2),encoding='utf8')


def test_gravity_singularity_is_not_a_balanced_initial_state():
    s=MacroSystem(dict(hanging_block(), springs=[]))
    with pytest.raises(ValueError) as caught:s.equilibrate()
    assert caught.value.diagnostics['status']=='failed'
    assert caught.value.diagnostics['reason_code']=='singular_tangent'
    assert caught.value.diagnostics['blast_applied'] is False


def test_gravity_cancellation_and_budget_are_checked_before_iterations():
    from lsprepost_mcp.architecture.scene_blast.gravity import GravityFailure
    for cancel, budget, reason in [(lambda:True, 30., 'cancelled'), (lambda:False, 0., 'timed_out')]:
        s=MacroSystem(hanging_block());initial=s.x.copy()
        with pytest.raises(GravityFailure) as caught:
            s.equilibrate(cancel=cancel, time_budget_s=budget)
        assert caught.value.status==reason
        assert caught.value.diagnostics['reason_code']==reason
        assert np.array_equal(initial,s.x)


def test_failed_newton_attempts_do_not_commit_plastic_history():
    s=MacroSystem(hanging_block(10000.));initial=s.x.copy()
    with pytest.raises(ValueError) as caught:s.equilibrate(max_iterations=1)
    assert caught.value.diagnostics['status']=='failed'
    assert np.array_equal(s.x,initial)
    assert np.max(s.history)==0 and np.max(s.accumulated_plastic)==0
    assert np.max(s.compression_plastic)==0 and np.max(s.shear_plastic)==0


def test_two_blocks_transfer_full_weight_through_cracked_upper_hanger(tmp_path):
    model=hanging_block(7000.)
    lower=deepcopy(model['bodies'][0]);lower.update(id='lower-payload',center_m=[0.,0.,.9],mass_kg=3000.)
    lower['vertices_m']=(np.array(lower['vertices_m'])-[0,0,.1]).tolist()
    model['bodies'].append(lower)
    add_interface(model,1,0,[0.,0.,.95],[0.,0.,1.],[1.,0.,0.],.2,.2,.1)
    s=MacroSystem(model)
    assert s.equilibrate()<1e-5
    f,_=s.forces(commit=False)
    assert f[0,2]==pytest.approx(7000*9.80665,rel=1e-5)
    assert f[1,2]==pytest.approx(3000*9.80665,rel=1e-5)
    assert -f[-1,2]==pytest.approx(10000*9.80665,rel=1e-5)
    assert np.any(s.damage>0)
    (tmp_path/'gravity.json').write_text(json.dumps(s.gravity_diagnostics,indent=2),encoding='utf8')


def test_compression_plastic_gravity_is_committed_and_remains_balanced(tmp_path):
    model=hanging_block(128000.)
    for spring in model['springs']:
        spring['point_m'][2]=.95;spring['normal']=[0.,0.,-1.]
    s=MacroSystem(model)
    assert s.equilibrate()<1e-5
    # Concrete is at 30 MPa compression; elastic bars take the remaining force.
    expected=(128000*9.80665-.04*.995*30e6)/(.04*.005*200e9/.05)
    assert 1-s.x[0,2]==pytest.approx(expected,rel=2e-5)
    assert np.max(abs(s.compression_plastic))>0
    assert np.max(s.damage)<1e-8
    assert np.max(abs(s.stress[s.steel]))<400e6
    f,_=s.forces(commit=False)
    assert f[0,2]==pytest.approx(128000*9.80665,rel=1e-5)
    initial=s.x.copy()
    for _ in range(30):s.step(.25*s.dt_stable)
    assert np.max(abs(s.x-initial))<1e-8
    (tmp_path/'gravity.json').write_text(json.dumps(s.gravity_diagnostics,indent=2),encoding='utf8')


def fixture_scene(config,mass=10000.,steel_ratio=.005):
    model=hanging_block(mass,steel_ratio)
    model.update(source=dict(config['source'],fixture='ONE_HANGER_NOT_A_BUILDING'),
        checks={'supported':True},assumptions=['one-block constitutive fixture only'],
        envelopes=[{'min_m':[-.1,-.1,.95],'max_m':[.1,.1,1.05]}],
        surfaces=[{'point_m':[0.,-.1,1.], 'normal':[0.,-1.,0.], 'area_m2':.02,'weights':[[0,1.]]}])
    return model


def test_preblast_damage_is_retained_as_initial_state_not_a_blast_event():
    from lsprepost_mcp.architecture.scene_blast.contracts import normalize_input,snapshot
    from lsprepost_mcp.architecture.scene_blast.solver import solve
    c=normalize_input({'source':{'kind':'commercial_supermarket'},'tnt':{'position_m':[0,-5,0],'mass_kg':.01},'analysis':{'duration_s':.05}})
    samples=[];r=solve(snapshot(c,fixture_scene(c)),gravity_diagnostics=lambda value:samples.append(deepcopy(value)))
    assert r['initial_state']['damage'][0]>.5
    assert r['initial_state']['steel_mpa'][0]>100
    assert r['frames'][0]['displacement_mm']==[0.]
    assert r['frames'][0]['damage'][0]>.5
    assert not any(e['time_s']==0 and e['kind']=='cracking' for e in r['events'])
    assert r['metrics']['gravity']['status']=='converged'
    assert samples[-1]['status']=='converged'


def test_native_worker_persists_gravity_failure_and_exposes_sealed_diagnostics(tmp_path):
    import time
    from lsprepost_mcp.architecture.scene_blast.contracts import normalize_input
    from lsprepost_mcp.architecture.scene_blast.service import SceneBlastService,read_json
    from lsprepost_mcp.architecture.scene_blast.api import handle_request,PREFIX
    service=SceneBlastService(tmp_path,prepare=lambda c:fixture_scene(c,steel_ratio=0))
    try:
        c=normalize_input({'source':{'kind':'commercial_supermarket'},'tnt':{'position_m':[0,-5,0],'mass_kg':.01},'analysis':{'duration_s':.05}})
        p=service.prepare(c);j=service.submit({'input':c,'model_fingerprint':p['model_fingerprint'],'request_id':'9'*32})
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            j=service.job(j['run_id'])
            if j['status'] not in {'queued','running'}:break
            time.sleep(.02)
        assert j['status']=='failed',j
        assert j['gravity_summary']['blast_applied'] is False
        directory=tmp_path/'runs'/j['run_id']
        failure=read_json(directory/'failure.json')
        assert failure['stage']=='gravity' and failure['diagnostics']['attempts']
        assert not (directory/'result.json').exists()
        code,_,raw=handle_request(service,'GET',PREFIX+'runs/'+j['run_id']+'/gravity')
        assert code==200
        diagnostic=json.loads(raw)
        assert diagnostic['input_fingerprint']==j['input_fingerprint']
        assert diagnostic['final']['worst_body']['body_id']=='payload'
        (directory/'gravity.json').write_text('{}',encoding='utf8')
        code,_,_=handle_request(service,'GET',PREFIX+'runs/'+j['run_id']+'/gravity')
        assert code==400  # replaced diagnosis must not be displayed as authentic evidence
    finally:service.close()


def test_cancellation_before_gravity_still_emits_identity_bound_diagnosis():
    from lsprepost_mcp.architecture.scene_blast.contracts import normalize_input,snapshot
    from lsprepost_mcp.architecture.scene_blast.solver import solve
    from lsprepost_mcp.architecture.scene_blast.gravity import GravityFailure
    c=normalize_input({'source':{'kind':'commercial_supermarket'},'tnt':{'position_m':[0,-5,0],'mass_kg':.01}})
    frozen=snapshot(c,fixture_scene(c));samples=[]
    with pytest.raises(GravityFailure) as caught:
        solve(frozen,cancel=lambda:True,gravity_diagnostics=lambda d:samples.append(deepcopy(d)))
    assert caught.value.status=='cancelled'
    assert samples[-1]['status']=='cancelled'
    assert samples[-1]['input_fingerprint']==frozen['input_fingerprint']


def test_terminal_job_is_not_visible_until_diagnostics_are_sealed(tmp_path,monkeypatch):
    import threading
    import time
    from lsprepost_mcp.architecture.scene_blast import service as module
    from lsprepost_mcp.architecture.scene_blast.contracts import normalize_input
    entered=threading.Event();release=threading.Event();original=module.read_json
    def reader(path):
        if path.name=='gravity.json':entered.set();release.wait(3)
        return original(path)
    monkeypatch.setattr(module,'read_json',reader)
    def runner(frozen,directory,cancel):
        module.write_json(directory/'gravity.json',dict(schema_version='scene-blast-gravity@1',status='failed',
            input_fingerprint=frozen['input_fingerprint'],model_fingerprint=frozen['model_fingerprint'],method=frozen['method'],blast_applied=False))
        raise module.WorkerFailure({'error':'fixture gravity failure','status':'failed'})
    service=module.SceneBlastService(tmp_path,prepare=fixture_scene,runner=runner)
    try:
        c=normalize_input({'source':{'kind':'commercial_supermarket'},'tnt':{'position_m':[0,-5,0],'mass_kg':.01}})
        p=service.prepare(c);j=service.submit({'input':c,'model_fingerprint':p['model_fingerprint'],'request_id':'8'*32})
        assert entered.wait(2)
        # Read the actual in-memory record; job() is intentionally protected by
        # the finalization lock and would wait until the diagnostic file is sealed.
        assert service.records[j['run_id']]['status']=='running'
        release.set()
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            j=service.job(j['run_id'])
            if j['status']=='failed':break
            time.sleep(.01)
        assert j['gravity_sha256'] and j['finished_at']
    finally:release.set();service.close()


def test_new_block_contact_during_gravity_cannot_be_hidden_as_initial_overlap():
    # A fixed obstacle only 10 um below the payload. The balanced cracked opening
    # is about 43 um, so that initial state is inadmissible without contact support.
    model=hanging_block();obstacle=deepcopy(model['bodies'][0])
    obstacle.update(id='obstacle',center_m=[0,0,.89999],fixed=True)
    obstacle['vertices_m']=(np.array(obstacle['vertices_m'])-[0,0,.10001]).tolist()
    model['bodies'].append(obstacle)
    s=MacroSystem(model)
    with pytest.raises(ValueError) as caught:s.equilibrate()
    assert caught.value.diagnostics['reason_code']=='unsupported_gravity_contact'
    assert caught.value.diagnostics['contact_pairs']==[['payload','obstacle']]
    assert caught.value.diagnostics['blast_applied'] is False


def test_external_worker_deadline_seals_terminal_diagnosis_without_claiming_rollback(tmp_path):
    import time
    import hashlib
    from lsprepost_mcp.architecture.scene_blast import service as module
    from lsprepost_mcp.architecture.scene_blast.contracts import normalize_input
    raw_digest=[]
    def runner(frozen,directory,cancel):
        module.write_json(directory/'gravity.json',dict(schema_version='scene-blast-gravity@1',status='running',
            input_fingerprint=frozen['input_fingerprint'],model_fingerprint=frozen['model_fingerprint'],method=frozen['method'],
            accepted_load_factor=.25,blast_applied=False,iterations=[{'relative_residual':.03}],
            last_trial={'scaled_relative_residual':.03},restored_to_accepted_state=False))
        raw_digest.append(hashlib.sha256((directory/'gravity.json').read_bytes()).hexdigest())
        raise module.ProcessStopped('timed_out','owned worker deadline fixture')
    service=module.SceneBlastService(tmp_path,prepare=fixture_scene,runner=runner)
    try:
        c=normalize_input({'source':{'kind':'commercial_supermarket'},'tnt':{'position_m':[0,-5,0],'mass_kg':.01}})
        p=service.prepare(c);j=service.submit({'input':c,'model_fingerprint':p['model_fingerprint'],'request_id':'7'*32})
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            j=service.job(j['run_id'])
            if j['status'] not in {'queued','running'}:break
            time.sleep(.01)
        assert j['status']=='timed_out'
        d=service.gravity(j['run_id'])
        assert d['status']=='timed_out' and d['reason_code']=='worker_timed_out'
        assert d['restored_to_accepted_state'] is False
        assert d['terminal_observation']['worker_status']=='timed_out'
        assert d['last_trial']['scaled_relative_residual']==.03
        assert d['raw_progress_sha256']==raw_digest[0]
        assert hashlib.sha256((tmp_path/'runs'/j['run_id']/'gravity.json').read_bytes()).hexdigest()==raw_digest[0]
    finally:service.close()
