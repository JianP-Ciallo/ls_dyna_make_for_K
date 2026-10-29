"""Vectorized SI constitutive and finite-rotation arithmetic for the macro model."""
import numpy as np


def skew(v):
    x,y,z=np.asarray(v).T;out=np.zeros((*np.shape(x),3,3))
    out[...,0,1]=-z;out[...,0,2]=y;out[...,1,0]=z;out[...,1,2]=-x;out[...,2,0]=-y;out[...,2,1]=x
    return out


def rotation(vector):
    v=np.asarray(vector);a=np.linalg.norm(v,axis=-1);K=skew(v)
    aa=np.maximum(a,1e-20)
    s=np.where(a<1e-6,1-a*a/6,np.sin(a)/aa)
    c=np.where(a<1e-6,.5-a*a/24,(1-np.cos(a))/(aa*aa))
    return np.eye(3)+s[...,None,None]*K+c[...,None,None]*(K@K)


def cohesive(opening, history, stiffness, ft, gf):
    """Bilinear traction-separation, total area Gf, irreversible tensile damage.

    Compression closes cracks without healing tensile stiffness. Unresolvable
    snapback (elastic onset >= final opening) is rejected, never silently broadened.
    """
    d=np.asarray(opening);k=np.asarray(stiffness);start=ft/k;end=2*gf/ft
    if np.any(start>=end):raise ValueError('宏单元尺寸过大，无法解析指定断裂能；请减小尺寸，不能增加断裂能凑图像')
    h=np.maximum(history,np.maximum(d,0))
    envelope=np.where(h<=start,k*h,ft*np.maximum(0.,(end-h)/(end-start)))
    damage=np.where(h>0,1-envelope/np.maximum(k*h,1e-30),0.)
    return np.where(d<0,k*d,(1-damage)*k*d),h,np.clip(damage,0,1)


def steel_return(strain, plastic, failed, elastic, fy, rupture):
    trial=elastic*(strain-plastic);increment=np.maximum(0.,np.abs(trial)-fy)/elastic
    new=plastic+np.sign(trial)*increment
    broken=failed|(np.abs(new)>=rupture)
    return np.where(broken,0.,np.clip(trial,-fy,fy)),new,broken


def gaps(x,R,pairs,ra,rb,n0):
    a,b=pairs.T
    arm_a=np.einsum('nij,nj->ni',R[a],ra);arm_b=np.einsum('nij,nj->ni',R[b],rb)
    pa=x[a]+arm_a;pb=x[b]+arm_b
    # Rotate normal with body A: objective at arbitrarily large common rotations.
    normal=np.einsum('nij,nj->ni',R[a],n0)
    return pb-pa,normal,pa,pb,arm_a,arm_b


def assemble_wrench(x,pairs,pa,pb,force_on_a):
    a,b=pairs.T;f=np.zeros_like(x);torque=np.zeros_like(x)
    # For U(Ra.T @ (pb-pa)), differentiating the material-frame gap gives
    # tau_a=(pb-xa) cross f and tau_b=-(pb-xb) cross f. Applying the pair at
    # pb preserves both virtual work AND total angular momentum at finite gap.
    p=pb
    np.add.at(f,a,force_on_a);np.add.at(f,b,-force_on_a)
    np.add.at(torque,a,np.cross(p-x[a],force_on_a));np.add.at(torque,b,-np.cross(p-x[b],force_on_a))
    return f,torque


def spring_wrench(x,R,pairs,ra,rb,n0,stiffness):
    gap,n,pa,pb,*_=gaps(x,R,pairs,ra,rb,n0)
    dn=np.sum(gap*n,axis=1)
    force=stiffness[:,0,None]*dn[:,None]*n+stiffness[:,1,None]*(gap-dn[:,None]*n)
    return assemble_wrench(x,pairs,pa,pb,force)


def ground_impulse(v,omega,arm,mass,inverse_inertia,restitution=0.):
    n=np.array([0.,0.,1.]);speed=float(np.dot(v+np.cross(omega,arm),n))
    if speed>=0:return np.zeros(3)
    cross=np.cross(arm,n)
    effective=1/mass+float(cross@inverse_inertia@cross)
    return n*(-(1+restitution)*speed/effective)
