"""Branch-consistent Jacobian of the existing finite-rotation trial wrench.

No constitutive/history update is performed here. At a committed tensile maximum
the loading derivative is used, including softening, rather than averaging it
with unloading. Stability therefore cannot be certified by a fictitious slope.
"""
import numpy as np

from .mechanics import skew


def connection_tangent(s,check=lambda:None):
    check()
    xa,xb=s.x[s.a],s.x[s.b];Ra,Rb=s.R[s.a],s.R[s.b]
    wrench,trial,details=s.connection_response(xa,Ra,xb,Rb)
    count=len(s.pairs);eye=np.eye(3);n=s.n
    normal_projector=n[:,:,None]*n[:,None,:];P=eye-normal_projector
    dn=details['opening_m'];effective=dn-s.compression_plastic
    h=trial['history'];D=trial['damage'];stress=trial['stress']
    onset=s.mat['ft_pa']/s.kn;end=2*s.mat['gf_n_m']/s.mat['ft_pa']
    loading=(effective>=s.history)&(effective>=0)
    soft=loading&(h>onset)&(h<end)&~s.steel
    # A committed return lies on its yield surface up to roundoff. Select the
    # continuing-loading derivative there; strict unloading remains elastic.
    roundoff=32*np.finfo(float).eps
    normal_slope=(1-D)*s.kn
    normal_slope=np.where(effective<0,
        np.where(s.kn*effective>-s.mat['fc_pa']*(1-roundoff),s.kn,0.),normal_slope)
    normal_slope[soft]=-s.mat['ft_pa']/(end-onset[soft])
    steel_trial=s.mat['steel_e_pa']*(dn/s.length-s.plastic)
    normal_slope[s.steel]=np.where(
        (abs(steel_trial[s.steel])<s.mat['steel_fy_pa']*(1-roundoff))&~trial['broken'][s.steel],s.kn[s.steel],0.)
    damage_slope=np.zeros(count)
    damage_slope[soft]=s.mat['ft_pa']*end/(s.kn[soft]*(end-onset[soft])*h[soft]**2)

    pb=xb+np.einsum('nij,nj->ni',Rb,s.rb)
    pa=xa+np.einsum('nij,nj->ni',Ra,s.ra)
    local_gap=np.einsum('nji,nj->ni',Ra,pb-pa)
    shear=local_gap-dn[:,None]*n
    z=s.ks[:,None]*(shear-s.shear_plastic);norm=np.linalg.norm(z,axis=1)
    cap=(1-D)*s.mat['ft_pa']+.5*np.maximum(0.,-stress);cap[s.steel]=0.
    cap_slope=-s.mat['ft_pa']*damage_slope-.5*np.where(stress<0,normal_slope,0.)
    cap_slope[s.steel]=0.
    slip=norm>=cap*(1-roundoff)
    shear_slope=s.ks[:,None,None]*P
    v=z/np.maximum(norm[:,None],1e-30)
    shear_slope[slip]=(cap[slip]*s.ks[slip]/np.maximum(norm[slip],1e-30))[:,None,None]*(
        P[slip]-v[slip,:,None]*v[slip,None,:])+(
        cap_slope[slip,None,None]*v[slip,:,None]*n[slip,None,:])
    material=normal_slope[:,None,None]*normal_projector+shear_slope
    check()
    # dg/dq in A's material frame, for left-multiplied world rotations.
    Rt=Ra.transpose(0,2,1);arm_a=pb-xa;arm_b=pb-xb
    B=np.zeros((count,3,12))
    B[:,:,:3]=-Rt;B[:,:,3:6]=Rt@skew(arm_a)
    B[:,:,6:9]=Rt;B[:,:,9:12]=-Rt@skew(arm_b)
    force=wrench[:,:3]
    df=s.area[:,None,None]*(Ra@material@B)
    df[:,:,3:6]-=skew(force)  # rotation of the traction basis
    da=np.zeros_like(B);db=np.zeros_like(B)
    da[:,:,:3]=-eye;da[:,:,6:9]=eye;da[:,:,9:12]=-skew(arm_b)
    db[:,:,9:12]=-skew(arm_b)
    ta=-skew(force)@da+skew(arm_a)@df
    tb=skew(force)@db-skew(arm_b)@df
    return -np.concatenate((df,ta,-df,tb),axis=1)
