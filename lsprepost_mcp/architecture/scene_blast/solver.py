"""Experimental 6-DOF macro dynamics, with finite rotations and plane impact.

This is not a general FE/DEM or progressive-collapse solver. New block/block
contact stops the run and returns partial results. No element or mass deletion.
"""
import math
import time

import numpy as np
from scipy import sparse
from scipy.spatial.transform import Rotation

from .contracts import MATERIAL, LIMITS
from .loads import pulse, pulse_average, surface_parameters
from .mechanics import skew, rotation, gaps, assemble_wrench, cohesive, steel_return, ground_impulse


class MacroSystem:
    def __init__(self,model,material=None):
        self.model=model;self.mat=dict(MATERIAL,**(material or {}));bs=model['bodies'];self.count=len(bs)
        self.x0=np.array([b['center_m'] for b in bs]+[[0.,0.,0.]])
        self.mass=np.array([b['mass_kg'] for b in bs]+[1.])
        self.inertia=np.array([b['inertia_kg_m2'] for b in bs]+[np.eye(3).tolist()]);self.inv_inertia=np.linalg.inv(self.inertia)
        self.fixed=np.array([b['fixed'] for b in bs]+[True]);self.free=np.flatnonzero(np.repeat(~self.fixed,6))
        self.x=self.x0.copy();self.R=np.tile(np.eye(3),(len(self.x),1,1));self.v=np.zeros_like(self.x);self.omega=self.v.copy()
        springs=model['springs'];self.pairs=np.array([[s['a'],s['b'] if s['b']>=0 else self.count] for s in springs],dtype=int).reshape(-1,2)
        self.a,self.b=self.pairs.T;anchors=np.array([s['point_m'] for s in springs]).reshape(-1,3);self.ra=anchors-self.x0[self.a];self.rb=anchors-self.x0[self.b]
        self.n=np.array([s['normal'] for s in springs]).reshape(-1,3);self.area=np.array([s['area_m2'] for s in springs]);self.length=np.array([s['length_m'] for s in springs]);self.steel=np.array([s['kind']=='steel' for s in springs],bool)
        E=np.where(self.steel,self.mat['steel_e_pa'],self.mat['e_pa']);self.kn=E/self.length;self.ks=np.where(self.steel,0.,self.mat['e_pa']/(2*(1+self.mat['nu']))/self.length)
        self.history=np.zeros(len(springs));self.plastic=np.zeros(len(springs));self.accumulated_plastic=np.zeros(len(springs));self.compression_plastic=np.zeros(len(springs));self.shear_plastic=np.zeros((len(springs),3));self.broken=np.zeros(len(springs),bool)
        self.damage=np.zeros(len(springs));self.stress=np.zeros(len(springs));self.dissipated=0.
        self.vertices=[np.array(b['vertices_m'])-self.x0[i] for i,b in enumerate(bs)]
        self.vertex_array=np.array(self.vertices);self.radius=np.linalg.norm(self.vertex_array,axis=2).max(axis=1)
        self.ground_z=np.minimum(0.,np.array([np.min(np.array(b['vertices_m'])[:,2]) for b in bs]))
        self.contact_stats=dict(max_penetration_m=0.,normal_impulse_n_s=0.,projected_upward_m=0.)
        self.K=self.elastic_stiffness()
        self.gravity=np.zeros_like(self.x);self.gravity[:,2]=-9.80665*self.mass;self.gravity[self.fixed]=0
        # Upper bound using the smallest principal inertia is conservative under rotation.
        diagonal=np.stack([self.mass]*3+[np.linalg.eigvalsh(self.inertia).min(axis=1)]*3,axis=1).ravel()
        scale=1/np.sqrt(diagonal[self.free]);bound=np.max(scale*(abs(self.K[self.free][:,self.free])@scale)) if len(self.free) else 1.
        self.dt_stable=.6*2/math.sqrt(max(bound,1e-20))

    def elastic_stiffness(self):
        rows=[];cols=[];values=[]
        for start in range(0,len(self.pairs),1024):
            sl=slice(start,start+1024);pairs=self.pairs[sl];n=self.n[sl];A=self.area[sl]
            count=len(pairs);B=np.zeros((count,3,12));B[:,:,:3]=-np.eye(3);B[:,:,3:6]=skew(self.ra[sl]);B[:,:,6:9]=np.eye(3);B[:,:,9:12]=-skew(self.rb[sl])
            D=self.ks[sl,None,None]*np.eye(3)+(self.kn[sl]-self.ks[sl])[:,None,None]*n[:,:,None]*n[:,None,:]
            local=np.einsum('nki,nkl,nlj->nij',B,D,B)*A[:,None,None]
            dofs=(pairs[:,:,None]*6+np.arange(6)).reshape(count,12)
            rows.append(np.broadcast_to(dofs[:,:,None],local.shape).ravel());cols.append(np.broadcast_to(dofs[:,None,:],local.shape).ravel());values.append(local.ravel())
        size=6*len(self.x)
        if not rows:return sparse.csr_matrix((size,size))
        return sparse.coo_matrix((np.concatenate(values),(np.concatenate(rows),np.concatenate(cols))),shape=(size,size)).tocsr()

    def connection_response(self,xa,Ra,xb,Rb,elastic=False):
        """Pure local trial response; all evaluations use the committed history."""
        pa=xa+np.einsum('nij,nj->ni',Ra,self.ra)
        pb=xb+np.einsum('nij,nj->ni',Rb,self.rb)
        gap=pb-pa;n=np.einsum('nij,nj->ni',Ra,self.n)
        dn=np.sum(gap*n,axis=1);shear=gap-dn[:,None]*n
        if elastic:
            force=(self.kn*dn)[:,None]*n+self.ks[:,None]*shear
            force*=self.area[:,None]
            return np.c_[force,np.cross(pb-xa,force),-force,-np.cross(pb-xb,force)],{},{}
        concrete=~self.steel;stress=np.zeros(len(dn));damage=np.zeros(len(dn));hist=self.history.copy();plastic=self.plastic.copy();broken=self.broken.copy();cp=self.compression_plastic.copy()
        effective=dn-self.compression_plastic
        stress[concrete],hist[concrete],damage[concrete]=cohesive(effective[concrete],self.history[concrete],self.kn[concrete],self.mat['ft_pa'],self.mat['gf_n_m'])
        # Separate compressive perfect-plastic cap. No claim of crushing/erosion.
        trial=self.kn[concrete]*effective[concrete];compress=effective[concrete]<0
        compstress=np.maximum(trial,-self.mat['fc_pa']);cc=np.flatnonzero(concrete)[compress]
        stress[cc]=compstress[compress];cp[cc]=dn[cc]-stress[cc]/self.kn[cc]
        strain=dn[self.steel]/self.length[self.steel]
        stress[self.steel],plastic[self.steel],broken[self.steel]=steel_return(strain,self.plastic[self.steel],self.broken[self.steel],self.mat['steel_e_pa'],self.mat['steel_fy_pa'],self.mat['steel_rupture_strain'])
        accumulated=self.accumulated_plastic+np.abs(plastic-self.plastic);broken|=self.steel&(accumulated>=self.mat['steel_rupture_strain']);stress[self.steel&broken]=0.
        # Shear traction in A's material frame: cohesion degrades with tensile damage;
        # compressive friction remains. Plastic slip prevents elastic energy creation.
        local=np.einsum('nji,nj->ni',Ra,shear)
        sheartrial=self.ks[:,None]*(local-self.shear_plastic);norm=np.linalg.norm(sheartrial,axis=1)
        cap=(1-damage)*self.mat['ft_pa']+.5*np.maximum(0.,-stress);cap[self.steel]=0.
        factor=np.minimum(1.,cap/np.maximum(norm,1e-30));traction_local=sheartrial*factor[:,None]
        sp=local-np.divide(traction_local,self.ks[:,None],out=np.zeros_like(local),where=self.ks[:,None]>0)
        force=(stress[:,None]*n+np.einsum('nij,nj->ni',Ra,traction_local))*self.area[:,None]
        trial=dict(history=hist,plastic=plastic,accumulated_plastic=accumulated,
            compression_plastic=cp,shear_plastic=sp,broken=broken,damage=damage,stress=stress)
        details=dict(opening_m=dn,shear_pa=np.linalg.norm(traction_local,axis=1))
        return np.c_[force,np.cross(pb-xa,force),-force,-np.cross(pb-xb,force)],trial,details

    def force_state(self,elastic=False):
        local,trial,details=self.connection_response(self.x[self.a],self.R[self.a],self.x[self.b],self.R[self.b],elastic)
        f=np.zeros_like(self.x);t=f.copy()
        np.add.at(f,self.a,local[:,:3]);np.add.at(t,self.a,local[:,3:6])
        np.add.at(f,self.b,local[:,6:9]);np.add.at(t,self.b,local[:,9:12])
        return f,t,trial,details

    def forces(self,commit=True,elastic=False):
        f,t,trial,_=self.force_state(elastic)
        if commit:
            for key,value in trial.items():setattr(self,key,value)
        return f,t

    def current_stiffness(self,check=lambda:None):
        """Assemble the branch-consistent trial tangent without history commits."""
        from .tangent import connection_tangent
        count=len(self.pairs);size=6*len(self.x)
        if not count:return sparse.csr_matrix((size,size))
        local=connection_tangent(self,check)
        dofs=(self.pairs[:,:,None]*6+np.arange(6)).reshape(count,12)
        rows=np.broadcast_to(dofs[:,:,None],local.shape).ravel()
        cols=np.broadcast_to(dofs[:,None,:],local.shape).ravel()
        return sparse.coo_matrix((local.ravel(),(rows,cols)),shape=(size,size)).tocsr()

    def equilibrate(self,tolerance=1e-5,max_iterations=25,**options):
        from .gravity import equilibrate
        def validate_state():
            contacts=overlap_pairs(self)
            return [[self.model['bodies'][a]['id'],self.model['bodies'][b]['id']] for a,b in sorted(contacts)]
        return equilibrate(self,tolerance=tolerance,max_iterations=max_iterations,validate_state=validate_state,**options)

    def step(self,dt,load=None):
        f,t=self.forces();f+=self.gravity
        if load is not None:f+=load[0];t+=load[1]
        # Mass-proportional damping is explicit and separate from material damage.
        damping=2*self.mat['damping_ratio']*20.
        f-=damping*self.mass[:,None]*self.v
        worldI=self.R@self.inertia@self.R.transpose(0,2,1)
        invI=self.R@self.inv_inertia@self.R.transpose(0,2,1)
        angular=np.einsum('nij,nj->ni',invI,t-np.cross(self.omega,np.einsum('nij,nj->ni',worldI,self.omega)))
        acceleration=f/self.mass[:,None];acceleration[self.fixed]=0;angular[self.fixed]=0
        # Symplectic Euler; fixed stable dt, never inflated to meet a runtime target.
        self.v+=dt*acceleration;self.omega+=dt*angular
        self.x+=dt*self.v;self.R=rotation(dt*self.omega)@self.R
        return acceleration

    def plane_contact(self):
        """Inelastic sequential impulses at all penetrating vertices, fixed z=ground.

        Building ground slabs may be below zero in the sealed source. Use their
        original minimum as the local fixed support plane; never snap the building.
        """
        alive=(self.steel&~self.broken)|(~self.steel&(self.damage<1-1e-10))
        anchored=np.zeros(self.count,bool);ids=self.a[alive&(self.b==self.count)];anchored[ids]=True
        z=np.einsum('nj,nkj->nk',self.R[:self.count,2,:],self.vertex_array)+self.x[:self.count,2,None]
        candidates=np.flatnonzero((z.min(axis=1)<self.ground_z)&~self.fixed[:self.count]&~anchored)
        for i in candidates:
            local=self.vertices[i];ground=self.ground_z[i];points=local@self.R[i].T+self.x[i];ids=np.flatnonzero(points[:,2]<ground)
            inv=self.R[i]@self.inv_inertia[i]@self.R[i].T
            for k in ids:
                arm=points[k]-self.x[i];j=ground_impulse(self.v[i],self.omega[i],arm,self.mass[i],inv)
                self.v[i]+=j/self.mass[i];self.omega[i]+=inv@np.cross(arm,j)
                self.contact_stats['normal_impulse_n_s']+=float(j[2])
            # Bounded geometric projection is reported; it is not a force history.
            depth=ground-points[:,2].min()
            if depth>.02:raise ValueError('地面接触穿透超过 20 mm；本次步长不满足接触分辨率')
            self.contact_stats['max_penetration_m']=max(self.contact_stats['max_penetration_m'],float(depth));self.contact_stats['projected_upward_m']+=float(depth)
            self.x[i,2]+=depth

    def body_fields(self):
        damage=np.zeros(self.count+1);steel=np.zeros(self.count+1);failed=np.zeros(self.count+1)
        for ids in (self.a,self.b):
            np.maximum.at(damage,ids,self.damage);np.maximum.at(steel,ids,np.where(self.steel,np.abs(self.stress)/1e6,0.));np.maximum.at(failed,ids,self.broken.astype(float))
        return damage[:self.count],steel[:self.count],failed[:self.count]


def boxes_intersect(a,b):
    """Separating axes of both boxes and edge cross-products, not vertex-only."""
    from .contacts import box_contacts, EPS
    return bool(box_contacts(np.asarray(a)[None],np.asarray(b)[None])[0][0]>EPS)


def overlap_pairs(system,*,detailed=True):
    from .contacts import JunctionContacts
    if not hasattr(system,'junction_contacts'):system.junction_contacts=JunctionContacts(system)
    pairs=system.junction_contacts.inspect(detailed=detailed)
    # Normal dynamic steps retain counts; a stopping collision retains all detail.
    if pairs and not detailed:system.junction_contacts.inspect(detailed=True)
    return pairs


def solve(snapshot,progress=lambda value:None,cancel=lambda:False,clock=time.monotonic,gravity_diagnostics=lambda value:None):
    start=clock();model=snapshot['model'];config=snapshot['config'];limit=snapshot['limits'];material=snapshot['material']
    if not model['checks']['supported']:raise ValueError('模型存在未接到基础的构件，尚不能启动求解')
    system=MacroSystem(model,material);progress(dict(stage='gravity',fraction=.02))
    def record_gravity(value):
        gravity_diagnostics(dict(value,input_fingerprint=snapshot['input_fingerprint'],
            model_fingerprint=snapshot['model_fingerprint'],method=snapshot['method']))
        progress(dict(stage='gravity',fraction=.02+.03*value['accepted_load_factor'],
            load_factor=value['accepted_load_factor'],gravity_status=value['status'],
            relative_residual=(value.get('last_trial') or {}).get('scaled_relative_residual')))
    residual=system.equilibrate(cancel=cancel,clock=clock,
        time_budget_s=max(0.,limit['wall_s']-(clock()-start)),diagnostics=record_gravity)
    initial_damage,initial_steel,initial_broken=system.body_fields()
    initial_state=dict(kind='gravity_equilibrium_before_blast',damage=initial_damage.tolist(),
        steel_mpa=initial_steel.tolist(),ruptured=initial_broken.tolist())
    params=surface_parameters(config,model)
    dt=min(system.dt_stable,.0001);duration=config['analysis']['duration_s'];steps=math.ceil(duration/dt);dt=duration/steps
    if steps>limit['max_steps']:raise ValueError(f'稳定步长需要 {steps} 步，超过首版预算；未自动增加步长或质量')
    n=system.count;original=system.x0[:n];equilibrium=system.x[:n].copy();frames=[];curve=[];peaks=dict(displacement_mm=np.zeros(n),steel_mpa=np.zeros(n),damage=np.zeros(n));events=[];status='completed';reason=None
    sample_every=max(1,math.ceil(steps/(limit['max_frames']-1)));prev_damage=initial_damage.copy();prev_broken=initial_broken.copy();last_report=start
    surface_body=[];surface_weight=[];surface_index=[];surface_arm=[]
    for k,s in enumerate(model['surfaces']):
        for j,(i,w) in enumerate(s['weights']):
            point=s.get('application_points_m',[s['point_m']]*len(s['weights']))[j]
            surface_body.append(i);surface_weight.append(w);surface_index.append(k);surface_arm.append(np.array(point)-system.x0[i])
    target=np.array(surface_body,int);weight=np.array(surface_weight);si=np.array(surface_index,int);arm=np.array(surface_arm)
    normals=np.array([s['normal'] for s in model['surfaces']]);areas=np.array([s['area_m2'] for s in model['surfaces']]);arrival=np.array([p['arrival_s'] for p in params]);peak=np.array([p['peak_pa'] for p in params]);impulse=np.array([p['impulse_pa_s'] for p in params])
    load_integral=np.zeros_like(system.x);min_extent=min(np.min(np.linalg.norm(np.array(b['vertices_m'])[[1,3,4]]-b['vertices_m'][0],axis=1)) for b in model['bodies'])
    for step in range(steps+1):
        now=clock()
        if cancel():status='cancelled';reason='用户停止';break
        if now-start>limit['wall_s']:status='timed_out';reason='达到冻结的 CPU 时间预算';break
        t=step*dt;pressure=pulse(t,arrival,peak,impulse);average=pulse_average(t-dt,t,arrival,peak,impulse) if step else pressure
        f=np.zeros_like(system.x);torque=f.copy();force=-normals*areas[:,None]*average[:,None]
        np.add.at(f,target,force[si]*weight[:,None]);worldarm=np.einsum('nij,nj->ni',system.R[target],arm)
        np.add.at(torque,target,np.cross(worldarm,force[si]*weight[:,None]))
        if step:
            corner_speed=np.max(np.linalg.norm(system.v[:n],axis=1)+np.linalg.norm(system.omega[:n],axis=1)*system.radius)
            if corner_speed*dt>min_extent*.2:status='partial';reason='平移/转动速度超过固定步长的穿越分辨率';break
            system.step(dt,(f,torque));system.plane_contact();load_integral+=f*dt
            system.forces()  # Constitutive state, events and extrema all refer to accepted x_(n+1).
            contacts=overlap_pairs(system,detailed=False)
            system.contact_diagnostics.update(stage='blast',time_s=t)
            if contacts:status='partial';reason='检测到未支持的构件间接触；本积分步停止，不继续计算互撞或贯穿'
        damage,steel,broken=system.body_fields();u=np.linalg.norm(system.x[:n]-equilibrium,axis=1)*1000
        for name,v in [('displacement_mm',u),('steel_mpa',steel),('damage',damage)]:peaks[name]=np.maximum(peaks[name],v)
        for kind,values,previous,threshold in [('cracking',damage,prev_damage,1e-8),('steel_rupture',broken,prev_broken,.5)]:
            indices=np.flatnonzero((values>threshold)&(previous<=threshold))
            events.extend(dict(time_s=t,stage='blast',kind=kind,body_id=model['bodies'][int(i)]['id']) for i in indices)
        prev_damage=damage;prev_broken=broken
        if step%sample_every==0 or step==steps or status=='partial':
            bodypressure=np.zeros(n)
            if len(target):np.maximum.at(bodypressure,target,pressure[si]/1000)
            frames.append(dict(time_s=t,translation_m=np.round(system.x[:n]-original,8).tolist(),rotation_xyzw=np.round(Rotation.from_matrix(system.R[:n]).as_quat(),8).tolist(),
                displacement_mm=np.round(u,6).tolist(),damage=np.round(damage,6).tolist(),steel_mpa=np.round(steel,6).tolist(),pressure_kpa=np.round(bodypressure,6).tolist()))
            curve.append(dict(time_s=t,max_displacement_mm=float(u.max()),max_steel_mpa=float(steel.max()),cracked_bodies=int(np.sum(damage>1e-8)),ruptured_bodies=int(np.sum(broken>.5))))
            if status=='partial':break
        if now-last_report>.2:progress(dict(stage='blast',fraction=.05+.9*step/steps,time_s=t,steps=step,total_steps=steps));last_report=now
    if not frames:raise ValueError('任务在第一帧前停止')
    return dict(schema_version='scene-blast-result@1',status=status,termination_reason=reason,input_fingerprint=snapshot['input_fingerprint'],model_fingerprint=snapshot['model_fingerprint'],method=snapshot['method'],
        source=model['source'],config=config,frames=frames,curves=curve,peaks={k:v.tolist() for k,v in peaks.items()},events=events,initial_state=initial_state,
        metrics=dict(wall_s=clock()-start,dt_s=dt,planned_steps=steps,completed_steps=step,gravity_relative_residual=residual,
            gravity=system.gravity_diagnostics,mass_kg=float(system.mass[:n].sum()),applied_impulse_n_s=load_integral[:n].sum(axis=0).tolist(),
            contact=system.contact_stats,block_contacts=system.contact_diagnostics),
        limitations=[*model['assumptions'],'研究原型：整栋准确性与数十秒性能尚未验收','拉伸开裂、压塑性、钢筋理想弹塑性/应变断裂；不含混凝土压碎、冲切或剪切破坏的独立预测',
            '相邻节点仅在局部传力路径与有限变形范围内视为连接；断开、过大滑移/转动或真实互撞时停止',
            '地面接触为无摩擦非弹性冲量；构件互撞仅检测后停止，不支持连续渐进倒塌','构件钢筋应力为宏连接轴向包络，不是逐根钢筋有限元应力','峰值逐积分步记录；回放帧及曲线经过独立降采样'])
