"""Bounded elastic transient response. Imported only by explicit CPU workers."""
from dataclasses import dataclass, field
import math
import os
import platform
import sys
import threading
import time
from .contracts import normalize_case, fingerprint, adapter_identity
from .loads import pressure_at


class BudgetExceeded(RuntimeError):pass
class CaseCancelled(RuntimeError):pass


@dataclass
class RunControl:
    deadline: float = field(default_factory=lambda:time.monotonic()+30)
    cancel: threading.Event | None = None
    max_steps: int = 10000

    def check(self,steps=0):
        if self.cancel is not None and self.cancel.is_set():raise CaseCancelled('CPU run cancelled')
        if time.monotonic()>=self.deadline or steps>self.max_steps:raise BudgetExceeded('CPU budget exceeded')


def solve_case(case: dict, control: RunControl | None = None,*,reuse_tangent=True,panel_recovery=True,quarter_panel=None,linear_matrix=None) -> dict:
    case=normalize_case(case)
    control=control or RunControl(deadline=time.monotonic()+case['budget']['wall_s'],max_steps=case['budget']['max_steps'])
    control.check()
    start=time.perf_counter();cpu_start=time.process_time()
    import openseespy.opensees as ops
    imported=time.perf_counter()
    from .column import build_column,read_column_sample,run_static
    from .panel import build_panel,read_panel_sample
    is_column=case['geometry']['kind']=='column'
    use_quarter=not is_column and (case['mesh']['n']>=16 if quarter_panel is None else quarter_panel)
    use_matrix=not is_column and case['analysis']['kind']=='dynamic' and (case['mesh']['n']>=16 if linear_matrix is None else linear_matrix)
    model=build_column(ops,case) if is_column else build_panel(ops,case,quarter=use_quarter,bending_only=use_matrix)
    symmetry=None;display_model=model
    if use_quarter:
        from .symmetry import PanelSymmetry
        symmetry=PanelSymmetry(model,case);display_model=symmetry.mesh
    read=(read_column_sample if is_column else read_panel_sample)
    if not is_column and panel_recovery:
        from .elastic_sampling import read_panel_elastic_sample,check_native_steel
        read=read_panel_elastic_sample
    matrix=None
    if use_matrix:
        from .elastic_system import ElasticPanelSystem
        matrix=ElasticPanelSystem(ops,model,case,control)
    built=time.perf_counter();solve_s=read_s=0.0;steps=iterations=0
    frames=[];curves=[];native_checks=0;tangent_rebuilds=0;peak_frames={}
    peaks=dict(displacement_m=0.0,displacement_time_s=0.0,steel_abs_pa=0.0,
               steel_signed_pa=0.0,steel_time_s=0.0,steel_sample_id=None)
    end=case['analysis']['duration_s'];dt=case['analysis']['dt_s']
    estimated=math.ceil(end/dt)
    # Bound scalar output as well as frame count. Peaks always use every internal step.
    frame_count=min(case['budget']['frames'],max(4,300000//max(1,6*len(display_model['nodes'])+2*len(display_model['steel_samples']))))
    stride=max(1,math.ceil(estimated/max(1,frame_count-1)))

    def capture(t,force_frame=False):
        nonlocal read_s,native_checks
        tick=time.perf_counter()
        sample=matrix.sample() if matrix else read(ops,model,t)
        disps=sample['displacements_m'];stress=sample['steel_stress_pa']
        save_frame=force_frame or steps%stride==0
        new_steel_index=None
        displacement=max(math.sqrt(sum(v*v for v in u)) for u in disps)
        new_displacement=displacement>peaks['displacement_m']
        if displacement>peaks['displacement_m']:
            peaks.update(displacement_m=displacement,displacement_time_s=t)
        if stress:
            i=max(range(len(stress)),key=lambda i:abs(stress[i]))
            if abs(stress[i])>peaks['steel_abs_pa']:
                new_steel_index=i
                peaks.update(steel_abs_pa=abs(stress[i]),steel_signed_pa=stress[i],steel_time_s=t,
                             steel_sample_id=symmetry.sample_id(i) if symmetry else model['steel_samples'][i]['id'])
        retain_peak=new_displacement or new_steel_index is not None
        if not is_column and (panel_recovery or matrix):
            from .elastic_sampling import check_native_steel
            indices=range(len(stress)) if save_frame or retain_peak else ()
            if matrix and (save_frame or retain_peak):matrix.sync_native()
            native_checks+=check_native_steel(ops,model,sample,indices)
        kinetic=sum(m*sum(v*v for v in vel)/2 for m,vel in zip(model['node_masses_kg'],sample['velocities_m_s']))
        strain_energy=0.0
        if matrix:kinetic=matrix.energy()
        else:
            for eid,element in enumerate(model['elements'],1):
                f=ops.eleForce(eid)
                u=[value for node in element for value in (disps[node]+sample['rotations_rad'][node])]
                strain_energy+=sum(a*b for a,b in zip(f,u))/2
        monitor=model['monitor_node']
        multiplier=4 if symmetry else 1
        reaction=sample['support_reaction'] if not symmetry else [0,0,4*sample['support_reaction'][2],0,0,0]
        pressure=(case['loads']['static_pressure_pa'] if t>0 else 0) if case['analysis']['kind']=='static' else pressure_at(case['loads']['curve_si'],t)
        curves.append(dict(time_s=t,pressure_pa=pressure,
                           monitor_displacement_m=disps[monitor],
                           monitor_velocity_m_s=sample['velocities_m_s'][monitor],
                           monitor_acceleration_m_s2=sample['accelerations_m_s2'][monitor],
                           steel_max_pa=max(stress,default=0),steel_min_pa=min(stress,default=0),
                           energy_j=multiplier*(kinetic+strain_energy),support_reaction=reaction))
        if save_frame or retain_peak:
            frame=symmetry.frame(sample) if symmetry else {k:sample[k] for k in ('time_s','displacements_m','rotations_rad','steel_stress_pa','steel_strain')}
            if save_frame:frames.append(frame)
            if new_displacement:peak_frames['displacement']=frame
            if new_steel_index is not None:peak_frames['steel']=frame
        read_s+=time.perf_counter()-tick

    try:
        capture(0,True)
        if case['analysis']['kind']=='static':
            tick=time.perf_counter();run_static(ops,model,case['loads']['static_pressure_pa']);solve_s+=time.perf_counter()-tick
            steps=1;capture(1,True)
        else:
            curve=case['loads']['curve_si']
            ops.timeSeries('Path',1,'-time',*[v[0] for v in curve],'-values',*[v[1] for v in curve])
            ops.pattern('Plain',1,1)
            for i,v in enumerate(model['load_map']['nodal_vectors_per_pa']):ops.load(i+1,*v)
            if not matrix:
                ops.constraints('Transformation');ops.numberer('RCM');ops.system('UmfPack')
            # Fixed elastic K/M: reuse a factorization only while ACTUAL dt agrees.
            # Replacing Linear at a short step AND the following nominal step
            # invalidates its cache without wiping model/integrator state.
            if not matrix:
                ops.test('NormDispIncr',1e-11,30);ops.algorithm('Linear')
                ops.integrator('Newmark',0.5,0.25);ops.analysis('Transient')
            previous_dt=None
            clock=lambda:matrix.time if matrix else ops.getTime()
            while clock()<end-1e-12:
                control.check(steps+1)
                now=clock()
                next_knot=next((t for t,_ in curve if t>now+1e-12),end)
                step=min(dt,end-now,next_knot-now)
                if math.isclose(step,dt,rel_tol=0,abs_tol=1e-12):step=dt
                if not matrix and (not reuse_tangent or step!=previous_dt):
                    ops.algorithm('Linear',*(['-factorOnce'] if reuse_tangent else []))
                    tangent_rebuilds+=1;previous_dt=step
                tick=time.perf_counter()
                if matrix:matrix.advance(step);code=0
                else:code=ops.analyze(1,step)
                solve_s+=time.perf_counter()-tick
                if code!=0:raise RuntimeError('elastic native integration did not converge; no result published')
                steps+=1;iterations+=0 if matrix else ops.testIter()
                capture(clock(),clock()>=end-1e-12)
        control.check(steps)
        finished=time.perf_counter()
        by_time={f['time_s']:f for f in frames+list(peak_frames.values())}
        times=sorted(by_time);mandatory={times[0],times[-1],*[f['time_s'] for f in peak_frames.values()]}
        if len(times)>frame_count:
            remaining=[t for t in times if t not in mandatory];slots=frame_count-len(mandatory)
            times=sorted(mandatory|{remaining[int((i+.5)*len(remaining)/slots)] for i in range(slots)})
        frames=[by_time[t] for t in times]
        # Preserve pressure knots and endpoints; curve thinning does not affect raw peaks.
        if len(curves)>case['budget']['samples']:
            mandatory={0,len(curves)-1}
            knots=[t for t,_ in case['loads']['curve_si']]
            mandatory.update(i for i,r in enumerate(curves) if any(abs(r['time_s']-t)<1e-12 for t in knots))
            remaining=[i for i in range(len(curves)) if i not in mandatory]
            slots=case['budget']['samples']-len(mandatory)
            selected=mandatory|{remaining[int((i+0.5)*len(remaining)/slots)] for i in range(slots)}
            curves=[curves[i] for i in sorted(selected)]
        result=dict(schema_version='cpu-response.result@1',source=case['source'],input_fingerprint=fingerprint(case),
                    mesh={k:v for k,v in display_model.items() if k not in ('load_map',)},frames=frames,curves=curves,peaks=peaks,
                    diagnostics=dict(accepted_steps=steps,iterations=iterations,retries=0,dt_requested_s=dt,
                                     tangent_rebuilds=tangent_rebuilds,native_steel_checks=native_checks,
                                     dynamic_modes=matrix.mode_count if matrix else None,all_dynamic_modes_retained=bool(matrix),
                                     condensation_residual=matrix.condensation_residual if matrix else None,
                                     native_element_count=len(model['elements']),mass_kg=display_model['mass_kg'],frame_stride=stride,
                                     timings=dict(import_s=imported-start,build_s=built-imported,solve_s=solve_s,
                                                  stress_read_s=read_s,worker_wall_s=finished-start,
                                                  worker_cpu_s=time.process_time()-cpu_start)),
                    provenance=dict(adapter_identity=adapter_identity(),solver='OpenSees '+ops.version(),python=sys.version,platform=platform.platform(),
                                    numerics=dict(reuse_tangent=reuse_tangent,panel_recovery=panel_recovery,quarter_panel=use_quarter,linear_matrix=use_matrix),
                                    integration_method='native_FE_full_basis_Newmark' if matrix else 'native_Newmark',
                                    steel_response_method='native_fiber' if is_column or not (panel_recovery or matrix) else 'elastic_section_recovery_native_checked',
                                    cpu=platform.processor(),cpu_count=os.cpu_count(),
                                    threads={k:os.environ.get(k) for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')},
                                    assumptions=case['assumptions'],materials=case['materials'],case=case,
                                    response_scope='elastic_small_displacement_reference',pressure_scope='prescribed_surface_load'))
        return result
    finally:
        ops.wipe()
