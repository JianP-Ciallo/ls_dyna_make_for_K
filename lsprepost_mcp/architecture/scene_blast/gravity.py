"""Bounded load-control equilibrium with actual trial constitutive response.

No strength changes, force cancellation, or dynamic relaxation. Rejected Newton
and load steps never commit material history. A failed solve cannot start blast.
"""
import math
import time
import warnings

import numpy as np
from scipy.sparse.linalg import MatrixRankWarning, spsolve

from .mechanics import rotation
from .stability import check_stability

STATE=('x','R','history','plastic','accumulated_plastic','compression_plastic',
       'shear_plastic','broken','damage','stress')


class GravityFailure(ValueError):
    def __init__(self,message,diagnostics,status='failed'):
        self.diagnostics=diagnostics;self.status=status
        super().__init__(message)


def capture(s):return {key:getattr(s,key).copy() for key in STATE}


def restore(s,state):
    for key,value in state.items():setattr(s,key,value.copy())


def finite_json(value,paths,path=''):
    """Nonfinite diagnostics are explicit nulls with locations, never fake zeros."""
    if isinstance(value,dict):return {k:finite_json(v,paths,path+'.'+str(k)) for k,v in value.items()}
    if isinstance(value,list):return [finite_json(v,paths,path+'['+str(i)+']') for i,v in enumerate(value)]
    if isinstance(value,(float,np.floating)) and not math.isfinite(value):
        paths.append(path);return None
    return value


def checkpoint(state,factor,info):
    """Preserve committed histories at a trial pose, not fictitious committed damage."""
    values={key:value.tolist() for key,value in state.items()}
    paths=[]
    item=finite_json(dict(load_factor=float(factor),history_status='committed_history_at_trial_pose',
        state=values,residual=info),paths)
    item.update(contains_nonfinite=bool(paths),nonfinite_fields=paths,replayable=not paths)
    return item


def residual(s,factor):
    f,t,trial,details=s.force_state()
    r=np.c_[f+factor*s.gravity,t]
    active=~s.fixed;length=np.r_[np.maximum(s.radius,.05),1.]
    scaled=np.c_[r[:,:3],r[:,3:]/length[:,None]].ravel()[s.free]
    reference=max(1.,np.linalg.norm((factor*s.gravity)[active]))
    relative=float(np.linalg.norm(scaled)/reference)
    ids=np.flatnonzero(active)
    worst=int(ids[np.argmax(np.linalg.norm(r[ids,:3],axis=1)+np.linalg.norm(r[ids,3:],axis=1)/length[ids])]) if len(ids) else None
    cracked=(~s.steel)&(trial['damage']>1e-8)
    stats=dict(cracked_concrete=int(cracked.sum()),
        compression_plastic=int(np.sum((~s.steel)&(abs(trial['compression_plastic'])>1e-12))),
        shear_plastic=int(np.sum((~s.steel)&(np.linalg.norm(trial['shear_plastic'],axis=1)>1e-12))),
        steel_plastic=int(np.sum(s.steel&(trial['accumulated_plastic']>1e-12))),
        ruptured_steel=int(np.sum(s.steel&trial['broken'])),max_damage=float(np.max(trial['damage'],initial=0)),
        max_steel_stress_mpa=float(np.max(abs(trial['stress'][s.steel]),initial=0)/1e6))
    connection=None
    if len(s.pairs):
        strength=np.where(s.steel,s.mat['steel_fy_pa'],np.where(trial['stress']<0,s.mat['fc_pa'],s.mat['ft_pa']))
        utilization=abs(trial['stress'])/strength+details['shear_pa']/s.mat['ft_pa']
        k=int(np.argmax(utilization));a,b=s.pairs[k]
        connection=dict(spring_index=k,a_body_id=s.model['bodies'][a]['id'],
            b_body_id=s.model['bodies'][b]['id'] if b<s.count else 'foundation',
            kind='steel' if s.steel[k] else 'concrete',point_m=s.model['springs'][k]['point_m'],
            opening_m=float(details['opening_m'][k]),normal_stress_mpa=float(trial['stress'][k]/1e6),
            shear_stress_mpa=float(details['shear_pa'][k]/1e6),damage=float(trial['damage'][k]),
            plastic_strain=float(trial['plastic'][k]),compression_plastic_m=float(trial['compression_plastic'][k]),
            shear_plastic_m=trial['shear_plastic'][k].tolist(),utilization=float(utilization[k]))
    summary=dict(load_factor=float(factor),scaled_relative_residual=relative,
        force_residual_n=float(np.linalg.norm(r[active,:3])),moment_residual_nm=float(np.linalg.norm(r[active,3:])),
        applied_weight_n=float(-factor*s.gravity[:,2].sum()),support_reaction_n=(-f[s.fixed].sum(axis=0)).tolist(),
        worst_body=None if worst is None else dict(body_id=s.model['bodies'][worst]['id'],
            force_residual_n=r[worst,:3].tolist(),moment_residual_nm=r[worst,3:].tolist()),
        connections=stats,worst_connection=connection)
    return r.ravel()[s.free],summary


def stable_tangent(K,**options):
    return check_stability(K,**options)


def equilibrate(s,*,tolerance=1e-5,max_iterations=25,cancel=lambda:False,
                time_budget_s=90.,clock=time.monotonic,diagnostics=lambda value:None,validate_state=lambda:[]):
    start=clock();accepted=capture(s);factor=0.;increment=.1;last_trial=None;target=0.;rejected_checkpoint=None
    d=dict(schema_version='scene-blast-gravity@1',algorithm='load-control-newton-branch-tangent-v2',
        status='running',blast_applied=False,accepted_load_factor=0.,tolerance=tolerance,
        residual_scaling='free-body forces and moments/characteristic radius; relative to current applied weight L2',
        attempts=[],iterations=[],reason_code=None,restored_to_accepted_state=False)
    s.gravity_diagnostics=d

    def publish():
        d['wall_s']=float(clock()-start)
        diagnostics(d)

    def fail(code,message,status='failed'):
        # Capture BEFORE restoring. During a rejected load-step the last trial
        # was already saved; cancellation may instead interrupt a current trial.
        trial_info=residual(s,target)[1]
        trial_checkpoint=checkpoint(capture(s),target,trial_info)
        if rejected_checkpoint is not None and code not in {'cancelled','timed_out'}:
            trial_checkpoint=rejected_checkpoint
        restore(s,accepted)
        d.update(status=status,reason_code=code,reason=message,accepted_load_factor=factor,
            restored_to_accepted_state=True,last_trial=trial_checkpoint['residual'],final=residual(s,1.)[1],
            failure_interpretation='equilibrium_not_established_not_a_capacity_certificate',
            state_checkpoints=dict(accepted=checkpoint(accepted,factor,residual(s,factor)[1]),
                rejected_trial=trial_checkpoint))
        paths=[];clean=finite_json(d,paths);d.clear();d.update(clean)
        if paths:d['nonfinite_fields']=paths
        publish()
        raise GravityFailure(message+'；未施加爆炸荷载',d,status)

    def check():
        if cancel():fail('cancelled','自重平衡已取消','cancelled')
        if clock()-start>=time_budget_s:fail('timed_out','自重平衡达到求解时间预算','timed_out')

    def check_contacts():
        contacts=validate_state()
        d['contact_diagnostics']=getattr(s,'contact_diagnostics',None)
        if contacts:
            d['contact_pairs']=contacts
            if d['attempts']:d['attempts'][-1].update(status='rejected',reason_code='unsupported_gravity_contact')
            fail('unsupported_gravity_contact','自重状态存在未支持的构件碰撞，不能作为爆炸初始状态')

    check()
    check_contacts();check()
    while factor<1.-1e-12:
        check();target=min(1.,factor+increment);restore(s,accepted);rejected_checkpoint=None
        attempt=dict(from_load_factor=factor,target_load_factor=target,increment=target-factor,status='iterating')
        d['attempts'].append(attempt);reason='iteration_limit';success=False
        for iteration in range(max_iterations):
            check();r,info=residual(s,target);last_trial=info
            if not np.isfinite(r).all() or not np.isfinite(info['scaled_relative_residual']):
                fail('nonfinite_response','自重迭代出现非有限恢复力')
            d['iterations'].append(dict(attempt=len(d['attempts']),iteration=iteration,
                load_factor=target,relative_residual=info['scaled_relative_residual'],
                force_residual_n=info['force_residual_n'],moment_residual_nm=info['moment_residual_nm'],
                worst_body_id=info['worst_body']['body_id'] if info['worst_body'] else None))
            d['last_trial']=info;publish()
            K=s.current_stiffness(check)[s.free][:,s.free]
            if info['scaled_relative_residual']<=tolerance:
                def record_stability(value):
                    attempt['stability']=value;d['last_stability']=value;publish()
                stability=stable_tangent(K,check=check,progress=record_stability);check()
                attempt['minimum_scaled_symmetric_tangent_eigenvalue']=stability['minimum_eigenvalue']
                if stability['status']=='unresolved':
                    attempt.update(status='rejected',reason_code='stability_unresolved')
                    fail('stability_unresolved','切线稳定性数值判定未完成（'+stability['reason_code']+'），不能据此判定建筑失稳')
                if stability['status']!='positive_definite':
                    reason='non_positive_tangent';break
                s.forces();post=residual(s,target)[1]
                if post['scaled_relative_residual']>tolerance:
                    reason='post_commit_imbalance';break
                check_contacts();check()
                factor=target;accepted=capture(s);d['accepted_load_factor']=factor
                attempt.update(status='converged',iterations=iteration+1,final=post)
                success=True;publish();break
            with warnings.catch_warnings():
                warnings.simplefilter('error',MatrixRankWarning)
                try:step=spsolve(K,r)
                except (MatrixRankWarning,RuntimeError):fail('singular_tangent','连接切线刚度奇异，存在未约束机构或承载路径丧失')
            check()
            if not np.isfinite(step).all():fail('singular_tangent','连接切线产生非有限平衡增量')
            delta=np.zeros(6*len(s.x));delta[s.free]=step;delta=delta.reshape(-1,6)
            extent=np.r_[np.maximum(s.radius,.05),1.]
            ratio=max(float(np.max(np.linalg.norm(delta[:,:3],axis=1)/(.1*extent))),
                float(np.max(np.linalg.norm(delta[:,3:],axis=1)/.1)),1.)
            alpha=1/ratio;x=s.x.copy();R=s.R.copy();improved=False
            # Use actual projected unbalanced work along the branch-consistent
            # Newton direction. This is a search merit, never an acceptance
            # substitute for force equilibrium or positive physical tangent.
            work=float(step@r)
            search=[];d['iterations'][-1]['line_search']=search
            d['iterations'][-1]['linear_relative_residual']=float(np.linalg.norm(K@step-r)/max(np.linalg.norm(r),1.))
            for _ in range(16):
                check();s.x=x+alpha*delta[:,:3];s.R=rotation(alpha*delta[:,3:])@R
                candidate_r,candidate=residual(s,target)
                candidate_work=float(step@candidate_r)
                if not np.isfinite(candidate_r).all() or not np.isfinite(candidate_work):
                    search.append(dict(alpha=float(alpha),projected_work_nm=candidate_work,
                        relative_residual=candidate['scaled_relative_residual'],accepted=False))
                    fail('nonfinite_response','自重线搜索出现非有限恢复力')
                improved=bool(abs(candidate_work)<abs(work)*(1-1e-4*alpha) or
                    candidate['scaled_relative_residual']<=tolerance)
                search.append(dict(alpha=float(alpha),projected_work_nm=candidate_work,
                    relative_residual=candidate['scaled_relative_residual'],accepted=improved))
                if improved:break
                alpha*=.5
            d['iterations'][-1]['line_search_alpha']=search[-1]['alpha']
            d['iterations'][-1]['projected_residual_work_nm']=work
            if not improved:reason='line_search_failed';last_trial=candidate;break
        if not success:
            last_trial=residual(s,target)[1]
            rejected_checkpoint=checkpoint(capture(s),target,last_trial)
            attempt.update(status='rejected',reason_code=reason,last_trial=last_trial)
            restore(s,accepted);increment*=.5;publish()
            if increment<1/4096 or len(d['attempts'])>=128:
                fail(reason,'非线性自重平衡未收敛或当前路径失稳，已回滚到上个收敛荷载级')
        else:increment=min(.2,increment*1.5)
    final=residual(s,1.)[1]
    if final['scaled_relative_residual']>tolerance:fail('final_imbalance','提交后的完整自重残差未达到容差')
    d.update(status='converged',accepted_load_factor=1.,final=final,reason_code=None)
    publish()
    return final['scaled_relative_residual']
