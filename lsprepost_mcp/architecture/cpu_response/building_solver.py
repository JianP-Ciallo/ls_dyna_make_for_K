"""Full-domain elastic reference assembly. Explicit worker only; no GET launch."""
import math
import json
import time
import numpy as np
from .backend_opensees import RunControl
from .contracts import fingerprint,adapter_identity,closed
from .loads import pressure_at


def validate_reference(case):
    closed(case,('schema_version','source','template_fingerprint','native_files','nodes','elements','fixed_nodes','mass_points',
                 'column_sections','panel_sections','nodal_load_per_pa','checks','mass_ledger','loads','analysis','budget','assumptions'),'building reference')
    json.dumps(case,allow_nan=False)
    if case['schema_version']!='cpu-response.building-case@1' or case['source']['kind']!='regularized_building_reference' or not case['checks'].get('ready_for_trial'):raise ValueError('unverified building reference')
    nodes=np.asarray(case['nodes'],dtype=float);n=len(nodes)
    if nodes.shape!=(n,3) or not 1<n<=5000 or not np.isfinite(nodes).all() or np.abs(nodes).max()>10000:raise ValueError('building node budget/coordinates')
    if not 1<=len(case['elements'])<=6000 or not 1<=len(case['mass_points'])<=30000:raise ValueError('building element/mass budget')
    def valid_node(i):return type(i) is int and 0<=i<n
    if not case['fixed_nodes'] or any(not valid_node(i) for i in case['fixed_nodes']):raise ValueError('building fixed nodes')
    for e in case['elements']:
        if e['kind'] not in ('column','panel') or len(e['nodes'])!=(2 if e['kind']=='column' else 4) or any(not valid_node(i) for i in e['nodes']):raise ValueError('building element connectivity')
        count=len(case['column_sections'] if e['kind']=='column' else case['panel_sections'])
        if type(e['section']) is not int or not 0<=e['section']<count:raise ValueError('building section identity')
    for p in case['mass_points']:
        if not valid_node(p['master']) or not 0<p['mass_kg']<1e9 or len(p['position_m'])!=3:raise ValueError('building mass point')
    load=np.asarray(case['nodal_load_per_pa'],dtype=float)
    if load.shape!=(n,6) or not np.isfinite(load).all():raise ValueError('building load shape')
    if not 4<=case['budget']['frames']<=500 or not 1<=case['budget']['samples']<=5000:raise ValueError('building output budget')
    from .gravity_mapping import mapped_gravity
    mapped_gravity(case)
    return case


def define_column(ops,profile,tag,mat):
    g=profile['geometry'];r=profile['reinforcement'];m=profile['materials'];b=g['width_m'];h=g['depth_m']
    area=math.pi*r['diameter_m']**2/4;side=math.sqrt(area);bars=profile['original_bar_positions_m']
    ops.uniaxialMaterial('Elastic',mat,m['concrete_e_pa']);ops.uniaxialMaterial('Elastic',mat+1,m['steel_e_pa'])
    ops.section('Fiber',tag,'-GJ',m['concrete_e_pa']/(2*(1+m['concrete_nu']))*.1406*b*h**3)
    ys=sorted({-b/2,b/2,*[y+s*side/2 for y,z in bars for s in (-1,1)]})
    zs=sorted({-h/2,h/2,*[z+s*side/2 for y,z in bars for s in (-1,1)]})
    for ya,yb in zip(ys,ys[1:]):
        for za,zb in zip(zs,zs[1:]):
            if any(abs((ya+yb)/2-y)<side/2-1e-12 and abs((za+zb)/2-z)<side/2-1e-12 for y,z in bars):continue
            ny=max(1,math.ceil((yb-ya)/b*profile['mesh']['fibers']));nz=max(1,math.ceil((zb-za)/h*profile['mesh']['fibers']))
            for i in range(ny):
                for j in range(nz):ops.fiber(ya+(i+.5)*(yb-ya)/ny,za+(j+.5)*(zb-za)/nz,(yb-ya)*(zb-za)/(ny*nz),mat)
    for y,z in bars:ops.fiber(y,z,area,mat+1)


def build_reference(ops,case):
    validate_reference(case)
    if case.get('schema_version')!='cpu-response.building-case@1' or not case['checks']['ready_for_trial']:raise ValueError('reference mapping has not passed preflight')
    ops.wipe();ops.model('basic','-ndm',3,'-ndf',6)
    for i,p in enumerate(case['nodes'],1):ops.node(i,*p)
    for i in case['fixed_nodes']:ops.fix(i+1,1,1,1,1,1,1)
    for i,p in enumerate(case['column_sections']):
        define_column(ops,p,1+i,1+i*2);ops.beamIntegration('Lobatto',1+i,1+i,3)
    ops.geomTransf('Linear',1,0,1,0)
    # All shell layers share the same verified elastic material family; each
    # component retains its own thickness and actual asymmetric steel layers.
    p=case['panel_sections'][0];ops.nDMaterial('ElasticIsotropic',1001,p['concrete_e_pa'],p['concrete_nu'],0)
    ops.uniaxialMaterial('Elastic',1002,p['steel_e_pa']);ops.nDMaterial('PlateRebar',1002,1002,0);ops.nDMaterial('PlateRebar',1003,1002,90)
    for i,p in enumerate(case['panel_sections']):
        args=[]
        for s in p['layers']:args.extend([1001 if s['kind']=='concrete' else 1002 if s['axis']=='X' else 1003,s['t']])
        ops.section('LayeredShell',1000+i,len(p['layers']),*args)
    samples=[];columns=[];panels=[];xyz=np.array(case['nodes']);gauss=1/math.sqrt(3)
    for i,e in enumerate(case['elements'],1):
        tags=[n+1 for n in e['nodes']];si=e['section']
        if e['kind']=='column':
            ops.element('dispBeamColumn',i,*tags,1,si+1);columns.append((i,si));p=case['column_sections'][si]
            for ip,t in enumerate((0,.5,1),1):
                axis=xyz[e['nodes'][0]]*(1-t)+xyz[e['nodes'][1]]*t
                for bar,(y,z) in enumerate(p['original_bar_positions_m']):
                    samples.append(dict(id=f'e{i}-ip{ip}-bar{bar+1}',element=i,ip=ip,bar_id=f'bar-{bar+1}',y=y,z=z,material=si*2+2,
                        position_m=(axis+[y,z,0]).tolist(),local_axis=[0,0,1],scope='longitudinal_fiber',component_id=e['component_id']))
        else:
            ops.element('ShellMITC4',i,*tags,1000+si);panels.append((i,si));p=case['panel_sections'][si]
            a,b=xyz[e['nodes'][0]],xyz[e['nodes'][2]]
            for ip,(xi,eta) in enumerate(((-gauss,-gauss),(gauss,-gauss),(gauss,gauss),(-gauss,gauss)),1):
                for li,s in enumerate(p['layers'],1):
                    if s['kind']!='steel':continue
                    samples.append(dict(id=f'e{i}-ip{ip}-{s["side"]}-{s["axis"]}',element=i,ip=ip,layer=li,side=s['side'],axis=s['axis'],
                        position_m=[a[0]+(xi+1)*(b[0]-a[0])/2,a[1]+(eta+1)*(b[1]-a[1])/2,a[2]+s['z']],
                        local_axis=[1,0,0] if s['axis']=='X' else [0,1,0],scope='smeared_rebar_layer',component_id=e['component_id']))
    # Point masses carry physical eccentric inertia. Fixed-base mass is recorded
    # separately and requires no extra slave nodes. Masters are structural nodes,
    # never slaves; no constraint chains or global rigid floor.
    links=[];next_tag=len(case['nodes'])+1;fixed=set(case['fixed_nodes'])
    for p in case['mass_points']:
        master=p['master']+1
        if p['master'] in fixed:continue
        ops.node(next_tag,*p['position_m']);ops.mass(next_tag,p['mass_kg'],p['mass_kg'],p['mass_kg'],0,0,0)
        ops.rigidLink('beam',master,next_tag);links.append((master,next_tag));next_tag+=1
    top=xyz[:,2].max();center=xyz.mean(axis=0);candidates=np.flatnonzero(np.abs(xyz[:,2]-top)<1e-7)
    monitor=int(candidates[np.argmin(np.sum((xyz[candidates,:2]-center[:2])**2,axis=1))])
    return dict(case=case,nodes=case['nodes'],elements=case['elements'],steel_samples=samples,columns=columns,panels=panels,
        mass_links=links,monitor_node=monitor,native_node_count=next_tag-1,
        mass_masters=np.array([p['master'] for p in case['mass_points']]),mass_values=np.array([p['mass_kg'] for p in case['mass_points']]),
        mass_offsets=np.array([p['position_m'] for p in case['mass_points']])-xyz[[p['master'] for p in case['mass_points']]])


def read_reference_sample(ops,model,time_s,*,native_check=False):
    ops.reactions('-dynamic');case=model['case'];n=len(model['nodes'])
    dofs=np.array([ops.nodeDisp(i+1) for i in range(n)]);vel=np.array([ops.nodeVel(i+1) for i in range(n)]);acc=np.array([ops.nodeAccel(i+1) for i in range(n)])
    strains={};stress=[];strain=[];checked=0
    for e,si in model['panels']:
        values=np.array(ops.eleResponse(e,'strains'))
        if values.shape!=(32,) or not np.isfinite(values).all():raise RuntimeError('missing native building shell strains')
        strains[e]=values.reshape(4,8)
    for s in model['steel_samples']:
        if s['scope']=='longitudinal_fiber':
            v=ops.eleResponse(s['element'],'section',s['ip'],'fiber',s['y'],s['z'],s['material'],'stressStrain')
            if len(v)!=2:raise RuntimeError('missing native building column steel')
            stress.append(v[0]);strain.append(v[1])
        else:
            i=s['element']-1;section=case['panel_sections'][case['elements'][i]['section']];z=section['layers'][s['layer']-1]['z'];d=0 if s['axis']=='X' else 1
            eps=strains[s['element']][s['ip']-1,d]-z*strains[s['element']][s['ip']-1,d+3];sigma=section['steel_e_pa']*eps
            if native_check:
                args=(s['element'],'material',s['ip'],'fiber',s['layer']);sv=ops.eleResponse(*args,'stress');ev=ops.eleResponse(*args,'strain')
                if len(sv)!=5 or len(ev)!=5 or not math.isclose(sv[d],sigma,rel_tol=1e-9,abs_tol=.02) or not math.isclose(ev[d],eps,rel_tol=1e-9,abs_tol=1e-12):raise RuntimeError('native building layer verification failed: '+s['id'])
                checked+=1
            stress.append(float(sigma));strain.append(float(eps))
    internal=0.
    for i,e in enumerate(case['elements'],1):internal+=float(np.dot(ops.eleForce(i),dofs[e['nodes']].ravel()))/2
    mv=vel[model['mass_masters']];speed=mv[:,:3]+np.cross(mv[:,3:],model['mass_offsets'])
    kinetic=float(np.sum(model['mass_values']*np.sum(speed**2,axis=1)))/2
    return dict(time_s=time_s,displacements_m=dofs[:,:3].tolist(),rotations_rad=dofs[:,3:].tolist(),velocities_m_s=vel[:,:3].tolist(),
                accelerations_m_s2=acc[:,:3].tolist(),steel_stress_pa=stress,steel_strain=strain,native_layer_checks=checked,
                support_reaction=[sum(ops.nodeReaction(i+1,d+1) for i in case['fixed_nodes']) for d in range(6)],energy_j=kinetic+internal)


def solve_building_reference(case,control=None):
    budget=case['budget'];analysis=case['analysis'];dt=analysis['dt_s'];end=analysis['duration_s']
    if not 0<budget['wall_s']<=180 or not 0<dt<=.001 or not 0<end<=.15 or math.ceil(end/dt)>10000:raise ValueError('building trial budget')
    control=control or RunControl(deadline=time.monotonic()+budget['wall_s'],max_steps=10000);control.check()
    from .loads import validate_curve
    curve=case['loads']['curve_si'];validate_curve(curve)
    if not math.isclose(curve[-1][0],end,abs_tol=1e-12):raise ValueError('pressure curve/analysis window mismatch')
    import openseespy.opensees as ops
    start=time.perf_counter();model=build_reference(ops,case);built=time.perf_counter()
    try:
        ops.timeSeries('Path',1,'-time',*[p[0] for p in curve],'-values',*[p[1] for p in curve]);ops.pattern('Plain',1,1)
        for i,f in enumerate(case['nodal_load_per_pa'],1):ops.load(i,*f)
        ops.constraints('Transformation');ops.numberer('RCM');ops.system('UmfPack');ops.test('NormDispIncr',1e-11,30)
        ops.algorithm('Linear');ops.integrator('Newmark',.5,.25);ops.analysis('Transient')
        scalar=6*len(model['nodes'])+2*len(model['steel_samples']);limit=min(budget['frames'],max(4,600000//max(1,scalar)))
        stride=max(1,math.ceil(math.ceil(end/dt)/max(1,limit-1)));frames=[];curves=[];peak_frames={};steps=0;previous=None;rebuilds=0;checks=0;solve_s=read_s=0.
        peaks=dict(displacement_m=0.,displacement_time_s=0.,steel_abs_pa=0.,steel_signed_pa=0.,steel_time_s=0.,steel_sample_id=None)
        def capture(t,force=False):
            nonlocal checks,read_s
            tick=time.perf_counter();sample=read_reference_sample(ops,model,t);stress=sample['steel_stress_pa']
            disp=max(math.sqrt(sum(v*v for v in u)) for u in sample['displacements_m']);i=max(range(len(stress)),key=lambda j:abs(stress[j]))
            nd=disp>peaks['displacement_m'];ns=abs(stress[i])>peaks['steel_abs_pa'];save=force or steps%stride==0
            if save or nd or ns:
                # Independent native material response at every saved field/new peak.
                verified=read_reference_sample(ops,model,t,native_check=True);checks+=verified['native_layer_checks']
            if nd:peaks.update(displacement_m=disp,displacement_time_s=t)
            if ns:peaks.update(steel_abs_pa=abs(stress[i]),steel_signed_pa=stress[i],steel_time_s=t,steel_sample_id=model['steel_samples'][i]['id'])
            if save or nd or ns:
                frame={k:sample[k] for k in ('time_s','displacements_m','rotations_rad','steel_stress_pa','steel_strain')}
                if save:frames.append(frame)
                if nd:peak_frames['displacement']=frame
                if ns:peak_frames['steel']=frame
            m=model['monitor_node'];curves.append(dict(time_s=t,pressure_pa=pressure_at(curve,t),monitor_displacement_m=sample['displacements_m'][m],
                monitor_velocity_m_s=sample['velocities_m_s'][m],monitor_acceleration_m_s2=sample['accelerations_m_s2'][m],
                steel_max_pa=max(stress),steel_min_pa=min(stress),support_reaction=sample['support_reaction'],energy_j=sample['energy_j']))
            read_s+=time.perf_counter()-tick
        capture(0,True)
        while ops.getTime()<end-1e-12:
            control.check(steps+1);now=ops.getTime();knot=next((t for t,p in curve if t>now+1e-12),end);step=min(dt,end-now,knot-now)
            if math.isclose(step,dt,abs_tol=1e-12,rel_tol=0):step=dt
            if step!=previous:ops.algorithm('Linear','-factorOnce');previous=step;rebuilds+=1
            tick=time.perf_counter();code=ops.analyze(1,step);solve_s+=time.perf_counter()-tick
            if code:raise RuntimeError('native reference building elastic solve failed')
            steps+=1;capture(ops.getTime(),ops.getTime()>=end-1e-12)
        control.check(steps)
        saved={f['time_s']:f for f in frames+list(peak_frames.values())};times=sorted(saved);mandatory={times[0],times[-1],*[p['time_s'] for p in peak_frames.values()]}
        if len(times)>limit:
            other=[t for t in times if t not in mandatory];slots=limit-len(mandatory);times=sorted(mandatory|{other[int((i+.5)*len(other)/slots)] for i in range(slots)})
        mesh=dict(kind='building_reference',nodes=case['nodes'],elements=[e['nodes'] for e in case['elements']],element_kinds=[e['kind'] for e in case['elements']],
                  element_components=[e['component_id'] for e in case['elements']],steel_samples=model['steel_samples'],monitor_node=model['monitor_node'])
        return dict(schema_version='cpu-response.result@1',source=case['source'],input_fingerprint=fingerprint(case),mesh=mesh,frames=[saved[t] for t in times],curves=curves,peaks=peaks,
            diagnostics=dict(accepted_steps=steps,tangent_rebuilds=rebuilds,native_layer_checks=checks,quarter_domain=False,mass_kg=case['mass_ledger']['total_kg'],
                native_nodes=model['native_node_count'],independent_structural_nodes=len(case['nodes']),mass_links=len(model['mass_links']),
                timings=dict(build_s=built-start,solve_s=solve_s,stress_read_s=read_s,worker_wall_s=time.perf_counter()-start)),
            provenance=dict(adapter_identity=adapter_identity(),solver='OpenSees '+ops.version(),case=case,response_scope='elastic_regularized_reference_trial',
                steel_response_method='native_column_fibers_and_native_checked_elastic_shell_layers',integration_method='native_full_domain_Newmark_no_modal_reduction',
                assumptions=case['assumptions'],whole_building_convergence_verified=False))
    finally:ops.wipe()
