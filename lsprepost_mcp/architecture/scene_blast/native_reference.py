"""Nonlinear beam/layered-shell validation; default entry remains SMALL ONLY.

Deliberate hard size limits prevent this experimental entry point from running
the real building. Keep the original reference and production macro backend.
"""
from copy import deepcopy
from pathlib import Path
import math
import time
import json
import numpy as np
from .native_materials import ASSUMPTIONS,define_panel,define_column
from .contracts import fingerprint
from ..cpu_response.building_solver import validate_reference
from ..cpu_response.gravity_mapping import mapped_gravity
from .native_plane_stress import plane_stress_diagnostics,plane_stress_passed


class NativeGravityFailure(ValueError):
    def __init__(self,diagnostics):
        self.diagnostics=diagnostics
        super().__init__('原生非线性小例自重失败：'+diagnostics['reason_code'])


def check_small_tangent(K,check):
    check();diagonal=np.diag(K);report=dict(status='non_positive',threshold=1e-9,matrix_dofs=len(K),
        criterion='Cholesky of symmetric diagonal-scaled physical tangent minus 1e-9 I')
    if not np.isfinite(K).all() or np.any(diagonal<=0):return report
    s=np.sqrt(diagonal);scaled=(K+K.T)/2/s[:,None]/s[None,:]
    try:np.linalg.cholesky(scaled-1e-9*np.eye(len(K)))
    except np.linalg.LinAlgError:return report
    check();report['status']='positive_definite';return report


def build_nonlinear_reference(ops,case,*,execution_scope='small',check=lambda:None):
    if execution_scope not in ('small','three_storey_prebalance'):raise ValueError('unknown native execution scope')
    limits=(128,128,768) if execution_scope=='small' else (640,600,4000)
    if any(len(case[k])>limit for k,limit in zip(('nodes','elements','mass_points'),limits)):
        raise ValueError('该入口仅用于小例验证，禁止运行整栋参考模型')
    validate_reference(case);case=deepcopy(case);xyz=np.asarray(case['nodes'],dtype=float)
    graph=[set() for _ in xyz]
    for e in case['elements']:
        for n in e['nodes']:graph[n].update(e['nodes'])
    seen=set(case['fixed_nodes']);pending=list(seen)
    while pending:
        for n in graph[pending.pop()]-seen:seen.add(n);pending.append(n)
    if len(seen)!=len(xyz):raise ValueError('小例存在断开的承载路径')
    ops.wipe();ops.model('basic','-ndm',3,'-ndf',6)
    for i,p in enumerate(xyz,1):check();ops.node(i,*p)
    for i in case['fixed_nodes']:ops.fix(i+1,1,1,1,1,1,1)
    ops.geomTransf('PDelta',1,0,1,0)
    panels=[];columns=[];meta=[];node_lengths=np.full(len(xyz),np.inf)
    for i,e in enumerate(case['elements'],1):
        check()
        tags=[n+1 for n in e['nodes']];p=xyz[e['nodes']];section=10*i
        if e['kind']=='panel':
            edge=p[1]-p[0];side=p[3]-p[0];area=np.linalg.norm(np.cross(edge,side))
            if not np.allclose(edge,[np.linalg.norm(edge),0,0],atol=1e-8) or not np.allclose(side,[0,np.linalg.norm(side),0],atol=1e-8):
                raise ValueError('小例壳局部X/Y方向必须与参考板筋一致')
            profile=case['panel_sections'][e['section']];m=define_panel(ops,profile,section,math.sqrt(area))
            ops.element('ShellMITC4',i,*tags,section);panels.append((i,profile));meta.append(m)
            node_lengths[e['nodes']]=np.minimum(node_lengths[e['nodes']],math.sqrt(area)/2)
        else:
            profile=case['column_sections'][e['section']];length=float(np.linalg.norm(p[1]-p[0]));secs=[];items=[]
            for j,w in enumerate((1/6,2/3,1/6)):
                m=define_column(ops,profile,section+j,length*w);secs.append(section+j);items.append(m)
            ops.beamIntegration('UserDefined',i,3,*secs,0.,.5,1.,1/6,2/3,1/6)
            ops.element('dispBeamColumn',i,*tags,1,i);columns.append((i,profile,items));meta.extend(items)
            node_lengths[e['nodes']]=np.minimum(node_lengths[e['nodes']],length/2)
    # Reference eccentric points remain tied to their original independent FE
    # masters. Gravity is T^T mg on those masters, with the exact offset moment.
    gravity=np.zeros((len(xyz),6));next_tag=len(xyz)+1;fixed=set(case['fixed_nodes']);links=[]
    for p in case['mass_points']:
        check()
        n=p['master'];f=np.array([0.,0.,-9.80665*p['mass_kg']]);offset=np.asarray(p['position_m'])-xyz[n]
        gravity[n,:3]+=f;gravity[n,3:]+=np.cross(offset,f)
        if n in fixed:continue
        ops.node(next_tag,*p['position_m']);ops.mass(next_tag,p['mass_kg'],p['mass_kg'],p['mass_kg'],0.,0.,0.)
        ops.rigidLink('beam',n+1,next_tag);links.append((n+1,next_tag));next_tag+=1
    mapped=mapped_gravity(case)
    if mapped is not None:gravity=mapped.copy()
    assumptions=[s for s in case['assumptions'] if s not in ('fixed_ground_floor_and_column_bases_no_soil_or_gravity','elastic_Ec_30GPa_reference_native_Es_and_rebar_positions')]
    assumptions+=ASSUMPTIONS+['gravity_source_shape_virtual_work_real_attachment_offsets' if mapped is not None else 'legacy_rigid_split_gravity_for_saved_reproduction_not_kinematically_validated',
        'legacy_dynamic_eccentric_mass_not_validated_by_static_gravity_correction',
        'source_mass_weights_inherited_from_audited_reference_no_independent_macroblock_splitting']
    return dict(case=case,panels=panels,columns=columns,material_metadata=meta,mass_links=links,
        native_node_count=next_tag-1,gravity=gravity,nodes=xyz,node_residual_length_m=node_lengths,assumptions=assumptions,execution_scope=execution_scope)


def read_fields(ops,model):
    steel=[];strain=[];tension=[];compression=[];ids=[];fiber_states=[]
    for tag,p in model['panels']:
        for ip in range(1,5):
            for li,layer in enumerate(p['layers'],1):
                args=(tag,'material',ip,'fiber',li)
                if layer['kind']=='concrete':
                    d=ops.eleResponse(*args,'material',1,'damage')
                    if len(d)!=2:raise RuntimeError('missing native shell concrete damage')
                    tension.append(d[0]);compression.append(d[1])
                else:
                    s=ops.eleResponse(*args,'stress');e=ops.eleResponse(*args,'strain');axis=0 if layer['axis']=='X' else 1
                    if len(s)!=5 or len(e)!=5:raise RuntimeError('missing native shell steel state')
                    steel.append(s[axis]);strain.append(e[axis]);ids.append(f'e{tag}-ip{ip}-layer{li}')
    for tag,p,sections in model['columns']:
        for ip,m in enumerate(sections,1):
            fibers=ops.eleResponse(tag,'section',ip,'fiberData')
            if not fibers or len(fibers)%5:raise RuntimeError('missing native column fiber history response')
            fiber_states.extend(fibers)
            for j,(y,z) in enumerate(p['original_bar_positions_m']):
                v=ops.eleResponse(tag,'section',ip,'fiber',y,z,m['steel_tag'],'stressStrain')
                if len(v)!=2:raise RuntimeError('missing native column steel state')
                steel.append(v[0]);strain.append(v[1]);ids.append(f'e{tag}-ip{ip}-bar{j}')
    result=dict(displacements_m=[ops.nodeDisp(i+1)[:3] for i in range(len(model['nodes']))],
        rotations_rad=[ops.nodeDisp(i+1)[3:] for i in range(len(model['nodes']))],steel_stress_pa=steel,
        steel_strain=strain,steel_sample_ids=ids,concrete_tensile_damage=tension,concrete_compressive_damage=compression,
        column_fiber_data=fiber_states,
        damage_scope='native_shell_material_damage_only_column_crushing_not_a_damage_index')
    for key in ('displacements_m','rotations_rad','steel_stress_pa','steel_strain','concrete_tensile_damage','concrete_compressive_damage','column_fiber_data'):
        if not np.isfinite(result[key]).all():raise RuntimeError('nonfinite native field: '+key)
    return result


def pdelta_geometric_moment(ops,model,indices=None):
    """Known initial-coordinate moment from PDelta's N/L leaning-column shear.

    Linear MITC shells balance moments in their initial geometry. For each
    PDelta column the additional initial-coordinate moment is N*n cross (uj-ui).
    Use native BASIC axial force, not a fitted total-force balance correction.
    """
    selected=None if indices is None else set(indices);moment=np.zeros(3)
    for i,e in enumerate(model['case']['elements']):
        if e['kind']!='column' or (selected is not None and i not in selected):continue
        a,b=e['nodes'];axis=model['nodes'][b]-model['nodes'][a];axis=axis/np.linalg.norm(axis)
        force=ops.eleResponse(i+1,'basicForce')
        if len(force)!=6 or not np.isfinite(force).all():raise RuntimeError('missing native PDelta basic axial force')
        du=np.asarray(ops.nodeDisp(b+1)[:3])-ops.nodeDisp(a+1)[:3]
        moment+=force[0]*np.cross(axis,du)
    return moment


def actual_balance(ops,model,factor,*,after_native=lambda:None):
    internal=np.zeros_like(model['gravity'])
    for i,e in enumerate(model['case']['elements'],1):
        f=np.asarray(ops.eleForce(i)).reshape(-1,6)
        after_native()
        np.add.at(internal,e['nodes'],f)
    residual=internal-factor*model['gravity'];fixed=model['case']['fixed_nodes'];free=np.ones(len(residual),dtype=bool);free[fixed]=False
    weight=max(1.,float(np.linalg.norm(factor*model['gravity'][free,:3])))
    radius=max(1.,float(np.ptp(model['nodes'],axis=0).max()))
    lengths=np.asarray(model['node_residual_length_m'])[free]
    force_relative=float(np.linalg.norm(residual[free,:3])/weight)
    moment_relative=float(np.linalg.norm(residual[free,3:]/lengths[:,None])/weight)
    relative=math.hypot(force_relative,moment_relative)
    reaction=np.zeros_like(residual);reaction[fixed]=residual[fixed]
    external=factor*model['gravity']+reaction
    net=external[:,:3].sum(0);moment=(np.cross(model['nodes'],external[:,:3])+external[:,3:]).sum(0)
    total=max(1.,float(np.linalg.norm(factor*model['gravity'][:,:3].sum(0))))
    geometric=pdelta_geometric_moment(ops,model);corrected=moment-geometric
    return dict(actual_relative_residual=relative,force_relative_residual=force_relative,moment_relative_residual=moment_relative,
        residual_definition='sqrt(sum(force^2)+sum((moment/local_node_length)^2))/norm(free_applied_force); local length=half min incident sqrt(shell area) or beam length; new FE DOFs not directly comparable to macrobody residual',
        force_balance_relative_error=float(np.linalg.norm(net)/total),
        moment_balance_relative_error=float(np.linalg.norm(corrected)/(total*radius)),
        raw_initial_moment_relative_error=float(np.linalg.norm(moment)/(total*radius)),pdelta_geometric_moment_nm=geometric.tolist(),
        moment_balance_definition='initial_coordinate_external_moment_minus_sum_N_axis_cross_delta_u_for_PDelta_columns_linear_shell_geometry',
        net_force_n=net.tolist(),net_moment_nm=corrected.tolist(),raw_initial_net_moment_nm=moment.tolist(),
        support_reaction_wrenches=reaction[fixed].tolist(),max_force_residual_n=float(np.abs(residual[free,:3]).max(initial=0.)),
        max_moment_residual_nm=float(np.abs(residual[free,3:]).max(initial=0.)))


def configure_static(ops,increment,absolute_tol,*,system='FullGeneral'):
    ops.wipeAnalysis();ops.constraints('Transformation');ops.numberer('RCM');ops.system(system)
    ops.test('NormUnbalance',absolute_tol,40,0);ops.algorithm('Newton')
    ops.integrator('LoadControl',increment);ops.analysis('Static')


def physical_tangent(ops,model,*,reconfigure=True,after_native=lambda:None):
    if reconfigure:
        # Native initialize numbers the new system AND duplicates the current
        # zero-increment commit. This is not a read-only native operation. Its
        # state/time and subsequent material paths are covered by small tests.
        # No load or displacement increment is applied.
        before=read_fields(ops,model);time_before=ops.getTime()
        configure_static(ops,0.,native_tolerance(model,1.),system='FullGeneral');ops.initialize()
        after_native()
        after=read_fields(ops,model)
        keys=('displacements_m','rotations_rad','steel_stress_pa','steel_strain','concrete_tensile_damage','concrete_compressive_damage','column_fiber_data')
        if ops.getTime()!=time_before or any(not np.array_equal(before[k],after[k]) for k in keys):
            raise ValueError('切线初始化改变原生可观测状态或荷载时间，禁止继续')
    n=ops.systemSize()
    if n>3072:raise ValueError('物理切线直接核验超过3072自由度预算')
    K=np.asarray(ops.printA('-ret')).reshape(n,n)
    after_native()
    return K


def install_gravity(ops,model,load_scale):
    ops.timeSeries('Linear',98001);ops.pattern('Plain',98001,98001)
    for i,f in enumerate(model['gravity'],1):ops.load(i,*(f*load_scale))


def native_tolerance(model,factor):
    free=np.ones(len(model['nodes']),dtype=bool);free[model['case']['fixed_nodes']]=False
    # Native mixed force/moment norm is only the iteration stopping rule. Keep
    # one order of margin to the unchanged independent physical residual 1e-5.
    return max(1e-10,1e-6*np.linalg.norm(model['gravity'][free,:3])*factor)


def safe_fields(ops,model):
    try:return read_fields(ops,model)
    except Exception as exc:return dict(error=str(exc),scope='native_fields_unavailable_no_zero_substitution')


def finite_diagnostics(report):
    """JSON cannot contain NaN/Inf; preserve missing-value paths, never use zero."""
    paths=[]
    def convert(value,path):
        if isinstance(value,float) and not math.isfinite(value):paths.append(path);return None
        if isinstance(value,dict):return {k:convert(v,path+'.'+str(k)) for k,v in value.items()}
        if isinstance(value,(list,tuple)):return [convert(v,path+f'[{i}]') for i,v in enumerate(value)]
        return value
    cleaned=convert(report,'diagnostics');cleaned['nonfinite_value_paths']=paths;return cleaned


def replay_accepted(ops,model,increments,load_scale,check):
    """Rebuild only a bounded small case and replay accepted commits, never trials.

    The installed Windows FileDatastore failed its restore probe; it is not a
    valid state backup. Deterministic accepted-path replay preserves native
    constitutive history and is checked against all recorded accepted fields.
    """
    rebuilt=build_nonlinear_reference(ops,model['case']);install_gravity(ops,rebuilt,load_scale)
    total=0.
    for delta in increments:
        total+=delta
        check();configure_static(ops,delta,native_tolerance(model,total*load_scale))
        if ops.analyze(1)!=0:raise RuntimeError('accepted_path_replay_failed')
        ops.integrator('LoadControl',0.)
        if ops.analyze(1)!=0:raise RuntimeError('accepted_path_refresh_failed')
    if not plane_stress_passed(plane_stress_diagnostics(ops,rebuilt)):raise RuntimeError('accepted_replay_plane_stress_unbalanced')
    return read_fields(ops,rebuilt)


def equilibrate_gravity(ops,model,*,checkpoint_dir,wall_s=10.,load_scale=1.,progress=None,
                        stop_on_first_failure=False,failure_probe=None):
    """Bounded load control with checked accepted-path replay and physical gates.

    The FullGeneral matrix is restricted to small cases. Its Newton tangent is
    refreshed by an additional zero-load-increment equilibrium iteration before
    certification. Replay preserves constitutive state across rejected steps.
    """
    whole=model.get('execution_scope')=='three_storey_prebalance'
    if not 0<wall_s<=(150 if whole else 30) or not 0<load_scale<=10000:raise ValueError('native gravity budget')
    start=time.monotonic();path=Path(checkpoint_dir).resolve();path.mkdir(parents=True,exist_ok=True)
    install_gravity(ops,model,load_scale)
    accepted=0.;increment=.1;attempts=[];reason=None;stability=None;accepted_increments=[]
    report=dict(schema_version='scene-native-gravity-small@1',case_fingerprint=fingerprint(model['case']),status='running',accepted_load_factor=0.,gravity_applied=True,blast_applied=False,
        load_scale=load_scale,assumptions=model['assumptions'],attempts=attempts,restored_to_accepted_state=False,
        rollback_policy='stop_no_restart_preserve_accepted_and_rejected_evidence' if whole else 'checked_rebuild_and_replay_accepted_native_commits_only',automatic_restart=False)
    report['tangent_initialization']='native_zero_increment_duplicate_commit_with_state_guard' if whole else 'existing_FullGeneral_static_integrator'
    report['last_accepted_fields']=read_fields(ops,model)
    if progress is not None:progress('accepted',report)
    reserve=min(1.,wall_s*.2)
    def check():
        if time.monotonic()-start>wall_s-reserve:raise TimeoutError('small_case_deadline')
    def rollback_check():
        if time.monotonic()-start>wall_s:raise TimeoutError('small_case_rollback_deadline')
    def check_event():
        if failure_probe is not None and failure_probe():raise RuntimeError('native_failure_event')
        if stop_on_first_failure:check()
    for attempt in range(128):
        try:check()
        except TimeoutError:reason='deadline';break
        target=min(1.,accepted+increment);delta=target-accepted
        saved_fields=read_fields(ops,model)
        report['restored_to_accepted_state']=False;terminal=False
        step=dict(target=target);attempts.append(step);exception_reason=None
        try:
            configure_static(ops,delta,native_tolerance(model,target*load_scale),system='UmfPack' if whole else 'FullGeneral')
            if progress is not None:progress('attempt',dict(target=target,accepted_load_factor=accepted,stage='before_native_analyze'))
            code=ops.analyze(1);step.update(native_code=code,iterations=ops.testIter(),iteration_norms=list(ops.testNorms()))
            check_event()
            if whole and code!=0 and not stop_on_first_failure:
                # PlateRebar reverts its uniaxial material but caches the last
                # trial strain vector. Refresh at the native-reverted nodal pose
                # before comparing observable states. No displacement is set.
                ops.reactions();step['native_response_refresh']='at_native_reverted_nodes_no_new_step'
            if progress is not None:
                progress('trial',dict(target=target,native_code=code,returned_domain_fields=safe_fields(ops,model),
                    field_scope='native_domain_after_analyze_return_may_be_auto_reverted',accepted_load_factor=accepted))
            if code==0:
                ops.integrator('LoadControl',0.)
                code=ops.analyze(1);step['tangent_refresh_code']=code
                check_event()
            if code==0:
                trial_fields=read_fields(ops,model)
                balance=actual_balance(ops,model,target*load_scale,**(dict(after_native=check_event) if failure_probe is not None else {}));step.update(balance)
                plane=plane_stress_diagnostics(ops,model);step['plane_stress']=plane
                if not plane_stress_passed(plane):
                    terminal=True;ok=False;exception_reason='native_plane_stress_unbalanced'
                    stability=dict(status='unresolved',reason_code=exception_reason);step['stability']=stability
                else:
                    K=physical_tangent(ops,model,reconfigure=whole,**(dict(after_native=check_event) if failure_probe is not None else {}))
                    check_event()
                    stability=check_small_tangent(K,check);step['stability']=stability
                    ok=balance['actual_relative_residual']<=1e-5 and max(balance['force_balance_relative_error'],balance['moment_balance_relative_error'])<=1e-5 and stability['status']=='positive_definite'
                    # initialize/printA can update native material internals.
                    # Check the hidden 3D state after the final native update.
                    plane=plane_stress_diagnostics(ops,model);step['plane_stress']=plane
                    if not plane_stress_passed(plane):
                        terminal=True;ok=False;exception_reason='native_plane_stress_unbalanced'
                        stability=dict(status='unresolved',reason_code=exception_reason);step['stability']=stability
                    if ok:trial_fields=read_fields(ops,model)
            else:ok=False
        except Exception as exc:
            terminal=True;ok=False;code=-999;step['error']=str(exc)
            exception_reason='deadline' if isinstance(exc,TimeoutError) else 'native_exception'
            stability=dict(status='unresolved',reason_code=exception_reason);step['stability']=stability
        if ok:
            accepted=target;accepted_increments.append(delta);report.update(balance,accepted_load_factor=accepted,stability=stability,plane_stress=plane)
            report['last_accepted_fields']=trial_fields
            if progress is not None:progress('accepted',report)
            if accepted==1.:
                ops.loadConst('-time',0.);report.update(status='completed',wall_s=time.monotonic()-start);return report
            increment=min(.2,increment*1.5);continue
        reason=exception_reason or ('native_solve_failed' if code else 'physical_gate_failed')
        report['last_accepted_fields']=saved_fields
        report['last_rejected_fields']=safe_fields(ops,model)
        report['rejected_field_scope']='converged_native_trial_rejected_by_plane_stress_gate' if exception_reason=='native_plane_stress_unbalanced' else 'native_exception_domain_state_rollback_not_assumed' if exception_reason else 'native_domain_after_analyze_return_auto_reverted_if_native_code_nonzero' if code else 'converged_native_trial_rejected_by_independent_physical_gates'
        if stop_on_first_failure:
            report.update(domain_reuse_allowed=False,stop_on_first_failure=True,
                rollback_policy='capture_returned_state_without_refresh_replay_or_backtracking')
            break
        if whole:
            # A failed native load step reverts itself. Backtrack ONLY if all
            # committed observables and load factor match the prior accepted
            # state. No whole model rebuild/restart, no reuse of a new commit
            # rejected by our independent physical gates.
            report['domain_reuse_allowed']=False
            returned=report['last_rejected_fields']
            if step.get('native_code',0)<0 and not exception_reason and 'error' not in returned:
                errors={k:float(np.max(np.abs(np.asarray(returned[k])-np.asarray(saved_fields[k])),initial=0))/max(1.,float(np.max(np.abs(saved_fields[k]),initial=0)))
                    for k in ('displacements_m','rotations_rad','steel_stress_pa','steel_strain','concrete_tensile_damage','concrete_compressive_damage','column_fiber_data')}
                step['native_revert_field_errors']=errors;step['native_revert_load_factor_error']=abs(ops.getTime()-accepted)
                report['restored_to_accepted_state']=max(errors.values())<=1e-10 and step['native_revert_load_factor_error']<=1e-12
                if report['restored_to_accepted_state'] and increment/2>=1/4096:
                    increment*=.5
                    if progress is not None:progress('accepted',report)
                    continue
            break
        try:
            restored=replay_accepted(ops,model,accepted_increments,load_scale,rollback_check)
        except Exception as exc:
            reason='checkpoint_restore_failed';step['restore_error']=str(exc);break
        errors={k:float(np.max(np.abs(np.asarray(restored[k])-np.asarray(saved_fields[k])),initial=0))/max(1.,float(np.max(np.abs(saved_fields[k]),initial=0)))
            for k in ('displacements_m','rotations_rad','steel_stress_pa','steel_strain','concrete_tensile_damage','concrete_compressive_damage','column_fiber_data')}
        step['rollback_relative_field_errors']=errors;report['restored_to_accepted_state']=max(errors.values())<=1e-10
        step['rollback_load_factor_error']=abs(ops.getTime()-accepted)
        report['restored_to_accepted_state'] &= step['rollback_load_factor_error']<=1e-12
        if not report['restored_to_accepted_state']:reason='checkpoint_state_mismatch';break
        if terminal:break
        increment*=.5
        if increment<1/4096:break
    report.update(status='failed',reason_code=reason or 'attempt_limit',accepted_load_factor=accepted,stability=stability,wall_s=time.monotonic()-start)
    report=finite_diagnostics(report)
    (path/'native-gravity-failure.json').write_text(json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf8')
    raise NativeGravityFailure(report)


def hold_gravity(ops,model,*,duration_s=.02,dt_s=.001,wall_s=5.):
    """Unforced small transient from the gravity state; no damping to hide drift."""
    if not 0<duration_s<=.05 or not 0<dt_s<=.001 or math.ceil(duration_s/dt_s)>100 or not 0<wall_s<=10:raise ValueError('small hold budget')
    before=read_fields(ops,model);u0=np.array(before['displacements_m']);peak=0.;start=time.monotonic()
    ops.wipeAnalysis();ops.constraints('Transformation');ops.numberer('RCM');ops.system('UmfPack')
    ops.test('NormUnbalance',native_tolerance(model,1.),40,0);ops.algorithm('Newton');ops.integrator('Newmark',.5,.25);ops.analysis('Transient')
    count=math.ceil(duration_s/dt_s);dt=duration_s/count
    for _ in range(count):
        if time.monotonic()-start>wall_s:raise TimeoutError('small hold deadline')
        if ops.analyze(1,dt)!=0:raise RuntimeError('gravity hold failed')
        if not plane_stress_passed(plane_stress_diagnostics(ops,model)):raise RuntimeError('gravity hold plane stress unbalanced')
        u=np.array([ops.nodeDisp(i+1)[:3] for i in range(len(model['nodes']))]);peak=max(peak,float(np.linalg.norm(u-u0,axis=1).max()))
    after=read_fields(ops,model)
    return dict(scope='SMALL_GRAVITY_HOLD_ONLY',duration_s=duration_s,steps=count,wall_s=time.monotonic()-start,blast_applied=False,
        max_displacement_drift_m=peak,max_steel_stress_drift_pa=float(np.max(np.abs(np.array(after['steel_stress_pa'])-before['steel_stress_pa']),initial=0)),
        assumptions=model['assumptions'])
