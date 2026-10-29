"""Reference cross-sections for mapping validation and small interface tests.

Each side keeps its own concrete/axial steel geometry and membrane-bending
coupling. Ideal monolithic, fully anchored section continuity is a USER-SELECTED
assumption, not evidence of real reinforcement anchorage. This module does not
replace the scene solver or silently modify its existing spring model.
"""
from copy import deepcopy
import math

import numpy as np

from .contracts import MATERIAL
from .mechanics import cohesive,steel_return

ASSUMPTION='ideal_monolithic_section_fully_anchored_rebar'


def panel_fibers(section,*,width,length,axis,material=None):
    if axis not in ('X','Y') or min(width,length)<=0:raise ValueError('截面方向或尺寸无效')
    material=deepcopy(MATERIAL if material is None else material)
    positions=[];areas=[];steel=[]
    for layer in section['layers']:
        if layer['kind']=='steel' and layer['axis']!=axis:continue
        if layer['t']<=0:raise ValueError('截面层厚度必须为正')
        # Exact integration of each concrete layer's quadratic elastic moment;
        # steel is an axial line layer at its recorded centroid, not shifted.
        zs=[layer['z']] if layer['kind']=='steel' else [
            layer['z']+sign*layer['t']/(2*math.sqrt(3)) for sign in (-1,1)]
        for z in zs:
            for sign in (-1,1):
                positions.append([sign*width/(2*math.sqrt(3)),z])
                areas.append(width*layer['t']/(2*len(zs)))
                steel.append(layer['kind']=='steel')
    positions=np.asarray(positions,dtype=float)
    if not len(positions):raise ValueError('空截面')
    return dict(positions_m=positions,area_m2=np.asarray(areas),steel=np.asarray(steel,bool),
        basis=np.c_[np.ones(len(positions)),positions],length_m=float(length),material=material,
        assumption=ASSUMPTION,axis=axis,width_m=float(width),thickness_m=section['thickness_m'])


def elastic_matrix(section):
    m=section['material'];E=np.where(section['steel'],m['steel_e_pa'],m['e_pa'])
    return np.einsum('n,ni,nj->ij',E*section['area_m2']/section['length_m'],section['basis'],section['basis'])


def series_elastic(left,right):
    """Eliminate a massless INTERFACE SECTION, adding no body mass/support."""
    A,B=elastic_matrix(left),elastic_matrix(right)
    K=B-B@np.linalg.solve(A+B,B)
    return (K+K.T)/2


def new_state(section):
    n=len(section['area_m2'])
    return {k:np.zeros(n,dtype=bool if k=='broken' else float) for k in (
        'history','compression_plastic','plastic','accumulated_plastic','broken','damage','stress')}


def section_trial(section,q,state,*,direction=None):
    """Pure normal trial: [integral(sigma), integral(y*sigma), integral(z*sigma)].

    Fiber gaps are basis @ q. Neither global nor local Newton trial commits a
    material history. A direction selects one-sided derivatives ONLY at a
    loading/unloading corner; it never changes stress or material parameters.
    """
    q=np.asarray(q);basis=section['basis'];dn=basis@q;steel=section['steel'];c=~steel
    m=section['material'];L=section['length_m'];kn=np.where(steel,m['steel_e_pa'],m['e_pa'])/L
    trial={k:v.copy() for k,v in state.items()}
    effective=dn-state['compression_plastic'];stress=np.zeros(len(dn));damage=np.zeros(len(dn))
    stress[c],trial['history'][c],damage[c]=cohesive(effective[c],state['history'][c],kn[c],m['ft_pa'],m['gf_n_m'])
    compression=c&(effective<0);stress[compression]=np.maximum(kn[compression]*effective[compression],-m['fc_pa'])
    trial['compression_plastic'][compression]=dn[compression]-stress[compression]/kn[compression]
    stress[steel],trial['plastic'][steel],trial['broken'][steel]=steel_return(
        dn[steel]/L,state['plastic'][steel],state['broken'][steel],m['steel_e_pa'],m['steel_fy_pa'],m['steel_rupture_strain'])
    trial['accumulated_plastic']=state['accumulated_plastic']+abs(trial['plastic']-state['plastic'])
    trial['broken']|=steel&(trial['accumulated_plastic']>=m['steel_rupture_strain'])
    stress[steel&trial['broken']]=0.;trial['damage']=damage;trial['stress']=stress
    increment=np.zeros(len(dn)) if direction is None else basis@np.asarray(direction)
    eps=32*np.finfo(float).eps
    on_history=abs(effective-state['history'])<=eps
    loading=effective>=state['history']
    if direction is not None:loading=np.where(on_history,increment>=0,loading)
    onset=m['ft_pa']/kn;end=2*m['gf_n_m']/m['ft_pa']
    soft=c&(effective>=0)&loading&(trial['history']>onset)&(trial['history']<end)
    slope=(1-damage)*kn;slope[soft]=-m['ft_pa']/(end-onset[soft])
    compress_loading=kn*effective<=-m['fc_pa']*(1-eps)
    if direction is not None:
        surface=abs(kn*effective+m['fc_pa'])<=eps*m['fc_pa']
        compress_loading=np.where(surface,increment<=0,compress_loading)
    slope[compression]=np.where(compress_loading[compression],0.,kn[compression])
    trial_steel=m['steel_e_pa']*(dn/L-state['plastic'])
    yielding=abs(trial_steel)>=m['steel_fy_pa']*(1-eps)
    if direction is not None:
        surface=abs(abs(trial_steel)-m['steel_fy_pa'])<=eps*m['steel_fy_pa']
        yielding=np.where(surface,np.sign(trial_steel)*increment>=0,yielding)
    slope[steel]=np.where(yielding[steel]|trial['broken'][steel],0.,kn[steel])
    force=basis.T@(section['area_m2']*stress)
    tangent=np.einsum('n,ni,nj->ij',section['area_m2']*slope,basis,basis)
    return force,tangent,trial


class SectionFailure(ValueError):
    """An interface trial failed; caller must reject/rollback, never commit it."""


class SerialSection:
    """Two independent half-sections with an explicitly idealized common joint.

    Only normal extension and the two section bending slopes are represented;
    transverse shear/torsion/contact and the whole macro solver are NOT provided
    by this validation component. No layer positions or steel areas are averaged.
    """
    def __init__(self,left,right):
        if left['axis']!=right['axis']:raise ValueError('两侧截面方向不一致')
        self.left,self.right=left,right
        self.elastic=series_elastic(left,right)

    def initial_state(self):
        return dict(left=new_state(self.left),right=new_state(self.right),
            left_gap=np.zeros(3),right_gap=np.zeros(3),assumption=ASSUMPTION)

    def trial(self,total_gap,state,*,check=lambda:None,max_evaluations=60):
        from scipy.optimize import least_squares
        check();total=np.asarray(total_gap,dtype=float)
        if total.shape!=(3,) or not np.isfinite(total).all():raise SectionFailure('非有限截面位移')
        width=max(self.left['width_m'],self.right['width_m'])
        depth=max(self.left['thickness_m'],self.right['thickness_m'])
        scale=np.array([1.,2/width,2/depth])
        L=self.left['length_m']+self.right['length_m']
        opening=min(L*1e-4,2e-5)
        variable=np.array([opening,opening*2/width,opening*2/depth])
        A,B=elastic_matrix(self.left),elastic_matrix(self.right)
        initial=np.asarray(state['left_gap'])+np.linalg.solve(A+B,B@(
            total-np.asarray(state['left_gap'])-np.asarray(state['right_gap'])))
        # Normalize against physical section force, not a tunable numerical spring.
        reference=max(1.,self.left['material']['ft_pa']*self.left['area_m2'].sum(),
            self.right['material']['ft_pa']*self.right['area_m2'].sum())

        def responses(u):
            check();a=initial+u*variable;b=total-a
            F1,K1,t1=section_trial(self.left,a,state['left'],direction=a-state['left_gap'])
            F2,K2,t2=section_trial(self.right,b,state['right'],direction=b-state['right_gap'])
            return a,b,F1,K1,t1,F2,K2,t2

        def fun(u):
            _,_,F1,_,_,F2,_,_=responses(u)
            return scale*(F1-F2)/reference

        def jac(u):
            _,_,_,K1,_,_,K2,_=responses(u)
            return scale[:,None]*(K1+K2)*variable[None,:]/reference

        result=least_squares(fun,np.zeros(3),jac=jac,method='trf',tr_solver='exact',
            max_nfev=max_evaluations,ftol=1e-13,xtol=1e-13,gtol=1e-13)
        a,b,F1,K1,t1,F2,K2,t2=responses(result.x)
        relative=float(np.linalg.norm(scale*(F1-F2))/reference)
        if relative>1e-8:raise SectionFailure('两侧截面力/矩未平衡，拒绝试算')
        internal=(K1+K2);diagonal=internal.diagonal()
        if np.any(diagonal<=0):raise SectionFailure('截面内部切线失稳，不能凝聚')
        scaled=internal/np.sqrt(diagonal[:,None]*diagonal[None,:])
        if np.linalg.eigvalsh((scaled+scaled.T)/2).min()<=1e-9:
            raise SectionFailure('截面内部切线失稳，不能凝聚')
        condensed=K2-K2@np.linalg.solve(internal,K2)
        trial=dict(left=t1,right=t2,left_gap=a,right_gap=b,left_force=F1,right_force=F2,
            relative_internal_residual=relative,evaluations=result.nfev,assumption=ASSUMPTION)
        return (F1+F2)/2,(condensed+condensed.T)/2,trial
