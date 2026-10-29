"""Explicit MM fractions from convex solid intersections and analytic cylinder."""
import math

import numpy as np


def clip_convex_faces(faces,lower,upper):
    """Clip a convex, planar-faced polyhedron against an axis aligned cell."""
    polygons=[np.asarray(f,float) for f in faces]
    for axis in range(3):
        for position,sign in ((lower[axis],-1),(upper[axis],1)):
            kept=[];cap=[]
            for poly in polygons:
                output=[]
                for a,b in zip(poly,np.roll(poly,-1,axis=0)):
                    da=sign*(a[axis]-position);db=sign*(b[axis]-position)
                    ina,inb=da<=1e-12,db<=1e-12
                    if ina: output.append(a)
                    if ina!=inb:
                        point=a+(b-a)*da/(da-db);point[axis]=position
                        output.append(point);cap.append(point)
                if len(output)>=3: kept.append(np.asarray(output))
            if not kept: return []
            if cap:
                points=np.unique(np.round(cap,12),axis=0)
                if len(points)>=3:
                    center=points.mean(axis=0);u=(axis+1)%3;v=(axis+2)%3
                    angles=np.arctan2(points[:,v]-center[v],points[:,u]-center[u])
                    points=points[np.argsort(angles)]
                    if sign<0: points=points[::-1]
                    kept.append(points)
            polygons=kept
    return polygons


def clipped_volume(faces,lower,upper):
    polygons=clip_convex_faces(faces,lower,upper)
    if not polygons:return 0.
    center=np.concatenate(polygons).mean(axis=0)
    volume=0.
    for poly in polygons:
        p=poly-center
        for j in range(1,len(p)-1): volume+=np.dot(p[0],np.cross(p[j],p[j+1]))/6
    if volume<-1e-10: raise ValueError('invalid occupied polyhedron orientation')
    return max(0.,float(volume))


def circle_rectangle_area(x0,y0,x1,y1,radius):
    """Integrate the exact circular cross-section, split at all arc transitions."""
    x0=max(x0,-radius);x1=min(x1,radius)
    if x1<=x0 or y0>=radius or y1<=-radius: return 0.
    cuts=[x0,x1]
    if x0<0<x1: cuts.append(0.)
    for y in (y0,y1):
        if abs(y)<radius:
            t=math.sqrt(max(0,radius*radius-y*y))
            cuts.extend(x for x in (-t,t) if x0<x<x1)
    cuts=sorted(set(cuts))
    def integral_arc(x):
        return .5*(x*math.sqrt(max(0,radius*radius-x*x))+radius*radius*math.asin(max(-1,min(1,x/radius))))
    total=0.
    for a,b in zip(cuts,cuts[1:]):
        h=math.sqrt(max(0,radius*radius-((a+b)/2)**2))
        top=min(y1,h);bottom=max(y0,-h)
        if top<=bottom: continue
        arcs=int(h<y1)+int(-h>y0)
        constant=(y1 if y1<=h else 0)-(y0 if y0>=-h else 0)
        total+=constant*(b-a)+arcs*(integral_arc(b)-integral_arc(a))
    return max(0.,total)


def scene_fractions(plan,xyz,pieces):
    axes=[np.asarray(a,float) for a in plan['axes']]
    nx,ny,nz=[len(a)-1 for a in axes]
    sizes=[np.diff(a) for a in axes]
    volumes=(sizes[2][:,None,None]*sizes[1][None,:,None]*sizes[0][None,None,:]).ravel()
    occupied=np.zeros(nx*ny*nz);tnt=occupied.copy()
    pairs=0
    def intersecting(lo,hi):
        return [range(max(0,int(np.searchsorted(a,l,side='right'))-1),
                      min(len(a)-1,int(np.searchsorted(a,h,side='left'))))
                for a,l,h in zip(axes,lo,hi)]
    for piece in pieces:
        faces=[np.array([xyz[int(n)] for n in f]) for f in piece]
        points=np.concatenate(faces);lo=points.min(axis=0);hi=points.max(axis=0)
        # The below-grade carrier is already pure vacuum.
        lo[2]=max(lo[2],plan['grade_m'])
        if hi[2]<=lo[2]: continue
        orthogonal=np.all((abs(points-points.min(axis=0))<1e-9)|(abs(points-points.max(axis=0))<1e-9))
        xs,ys,zs=intersecting(lo,hi)
        for k in zs:
            for j in ys:
                for i in xs:
                    pairs+=1
                    if pairs>1000000: raise ValueError('occupied intersection budget exceeded')
                    low=np.maximum(lo,[axes[0][i],axes[1][j],axes[2][k]])
                    high=np.minimum(hi,[axes[0][i+1],axes[1][j+1],axes[2][k+1]])
                    if np.any(high<=low): continue
                    value=float(np.prod(high-low)) if orthogonal else clipped_volume(faces,low,high)
                    occupied[(k*ny+j)*nx+i]+=value
    x,y,_=plan['center_m'];r=plan['diameter_m']/2
    lo=np.array(plan['bounds_m'][:3]);hi=np.array(plan['bounds_m'][3:])
    xs,ys,zs=intersecting(lo,hi)
    for j in ys:
        for i in xs:
            area=circle_rectangle_area(axes[0][i]-x,axes[1][j]-y,axes[0][i+1]-x,axes[1][j+1]-y,r)
            for k in zs:
                height=max(0,min(axes[2][k+1],hi[2])-max(axes[2][k],lo[2]))
                tnt[(k*ny+j)*nx+i]=area*height
    below=np.repeat(axes[2][1:]<=plan['grade_m']+1e-12,nx*ny)
    if np.any(occupied[below]>1e-12) or np.any(tnt[below]>1e-12): raise ValueError('solid fill crossed buffer unexpectedly')
    if np.any(occupied+tnt>volumes*(1+1e-7)): raise ValueError('occupied solids overlap or overlap cylinder')
    vf=np.zeros((len(volumes),3));vf[:,1]=tnt/volumes;vf[:,2]=occupied/volumes
    vf[below]=[0,0,1];vf[:,0]=1-vf[:,1]-vf[:,2]
    vf=np.clip(vf,0,1);vf/=vf.sum(axis=1)[:,None]
    return vf,dict(occupied_solid_volume_m3=float(occupied.sum()),tnt_volume_m3=float(tnt.sum()),
                   air_volume_m3=float(np.dot(vf[:,0],volumes)),buffer_volume_m3=float(volumes[below].sum()),
                   solid_cell_intersections=pairs,initialization='explicit_volume_fractions_exact_convex_intersections')
