"""Equivalent linear acceleration using native FE matrices and ALL dynamic modes.

No modal truncation: massless rotations are statically condensed, then every
positive-mass degree of freedom is retained. Limited to the flat, B=0, uniform
elastic panel reference. Native layer states independently verify recovered fields.
"""
import numpy as np
from .elastic_sampling import read_panel_elastic_sample
from .loads import pressure_at


class ElasticPanelSystem:
    def __init__(self,ops,model,case,control):
        if case['source']['id']!='rc-panel-v1' or case['materials']['profile']!='elastic_reference' or case['analysis']['damping']!=0:
            raise ValueError('native matrix acceleration is limited to the verified elastic panel')
        self.ops=ops;self.model=model;self.case=case;self.time=0.0
        # No pressure pattern is installed until native assembly/characterization
        # finishes. GimmeMCK(0,0,1) exposes native tangent through printA(-ret).
        ops.constraints('Transformation');ops.numberer('Plain');ops.system('FullGeneral')
        ops.algorithm('Linear');ops.integrator('GimmeMCK',0,0,1);ops.analysis('Transient')
        if ops.analyze(1,0)!=0:raise RuntimeError('native elastic stiffness assembly failed')
        ne=ops.systemSize()
        if not 0<ne<=1000:raise ValueError('native matrix size exceeds the small-reference budget')
        k=np.asarray(ops.printA('-ret'),dtype=float).reshape(ne,ne)
        scale=np.max(np.abs(k))
        if not np.isfinite(k).all() or not np.allclose(k,k.T,rtol=1e-10,atol=scale*1e-12):
            raise RuntimeError('native stiffness is not finite symmetric elastic stiffness')
        self.eq=np.asarray([ops.nodeDOFs(i+1) for i in range(len(model['nodes']))],dtype=int)
        mass=np.zeros(ne);load=np.zeros(ne);fixed_load=np.zeros(6)
        for node,row in enumerate(self.eq):
            for d,e in enumerate(row):
                f=model['load_map']['nodal_vectors_per_pa'][node][d]
                if e>=0:
                    load[e]=f
                    if d<3:mass[e]=model['node_masses_kg'][node]
                else:fixed_load[d]+=f
        active=np.flatnonzero(mass>0);zero=np.flatnonzero(mass==0)
        self.mode_count=len(active)
        if not len(active) or np.any(load[zero]):raise RuntimeError('unsupported massless load or empty mass block')
        control.check()
        rotations=-np.linalg.solve(k[np.ix_(zero,zero)],k[np.ix_(zero,active)])
        condensed=k[np.ix_(active,active)]+k[np.ix_(active,zero)]@rotations
        roots=np.sqrt(mass[active]);normalized=condensed/roots[:,None]/roots[None,:]
        omega2,modes=np.linalg.eigh((normalized+normalized.T)/2)
        if not np.isfinite(omega2).all() or np.any(omega2<=0):raise RuntimeError('nonpositive native bending mode')
        modes/=roots[:,None]
        self.phi=np.zeros((ne,len(active)));self.phi[active]=modes;self.phi[zero]=rotations@modes
        residual=k[np.ix_(zero,range(ne))]@self.phi
        self.condensation_residual=float(np.max(np.abs(residual))/(scale*np.max(np.abs(self.phi))))
        if self.condensation_residual>1e-10:raise RuntimeError('massless condensation residual exceeded tolerance')
        self.omega2=omega2;self.force=self.phi.T@load;self.fixed_load=fixed_load
        self.steel_modes=np.empty((len(model['steel_samples']),len(active)))
        self.reaction_modes=np.zeros((6,len(active)))
        self.node_indices=np.maximum(self.eq,0);self.mask=self.eq>=0
        self.entries=[(node+1,d+1,int(e)) for node,row in enumerate(self.eq) for d,e in enumerate(row) if e>=0]
        # Characterize native section strains for a COMPLETE basis. This is a
        # linear change of coordinates, not a lower-order structural surrogate.
        for mode in range(len(active)):
            control.check();self.set_native(self.phi[:,mode])
            sample=read_panel_elastic_sample(ops,model,0)
            self.steel_modes[:,mode]=sample['steel_stress_pa']
            for node,row in enumerate(self.eq):
                for d,e in enumerate(row):
                    if e<0:self.reaction_modes[d,mode]+=ops.nodeReaction(node+1,d+1)
        self.u=np.zeros(len(active));self.v=self.u.copy();self.acc=self.u.copy()
        self.set_native(np.zeros(ne));ops.reactions('-dynamic')

    def set_native(self,values):
        for tag,dof,e in self.entries:
            # setNodeDisp reads committed values for the OTHER five components;
            # committing each component is necessary to keep the whole vector.
            self.ops.setNodeDisp(tag,dof,float(values[e]),'-commit')

    def sync_native(self):
        self.set_native(self.phi@self.u);self.ops.reactions('-dynamic')

    def advance(self,dt):
        self.time+=dt
        predictor=self.u+dt*self.v+.25*dt*dt*self.acc
        new_acc=(self.force*pressure_at(self.case['loads']['curve_si'],self.time)-self.omega2*predictor)/(1+.25*dt*dt*self.omega2)
        self.u=predictor+.25*dt*dt*new_acc
        self.v+=.5*dt*(self.acc+new_acc);self.acc=new_acc

    def sample(self):
        state=(self.phi@self.u)[self.node_indices]*self.mask
        vel=(self.phi@self.v)[self.node_indices]*self.mask
        accel=(self.phi@self.acc)[self.node_indices]*self.mask
        stress=self.steel_modes@self.u
        reaction=self.reaction_modes@self.u-self.fixed_load*pressure_at(self.case['loads']['curve_si'],self.time)
        return dict(time_s=self.time,displacements_m=state[:,:3].tolist(),rotations_rad=state[:,3:].tolist(),
                    velocities_m_s=vel[:,:3].tolist(),accelerations_m_s2=accel[:,:3].tolist(),
                    steel_stress_pa=stress.tolist(),steel_strain=(stress/self.model['steel_e_pa']).tolist(),
                    support_reaction=reaction.tolist())

    def energy(self):return float(.5*np.sum(self.v*self.v+self.omega2*self.u*self.u))
