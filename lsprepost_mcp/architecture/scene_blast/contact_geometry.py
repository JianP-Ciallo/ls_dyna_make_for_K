"""Vertices of the convex intersection of two oriented rectangular boxes.

Only geometric clipping; no optimization solver or contact force. Intersection
vertices are endpoints of either box's edges clipped against the other box.
Containment is handled because wholly internal edges retain their endpoints.
"""
import numpy as np

EDGES=np.array([(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)])


def _clipped_edges(edges_box,clip_box):
    basis=clip_box[[1,3,4]]-clip_box[0]
    lengths=np.linalg.norm(basis,axis=1);basis/=lengths[:,None]
    start=edges_box[EDGES[:,0]];delta=edges_box[EDGES[:,1]]-start
    p=(start-clip_box.mean(0))@basis.T;d=delta@basis.T;half=lengths/2
    parallel=abs(d)<1e-12
    inverse=np.divide(1.,d,out=np.zeros_like(d),where=~parallel)
    t1=(-half-p)*inverse;t2=(half-p)*inverse
    lo=np.where(parallel,-np.inf,np.minimum(t1,t2))
    hi=np.where(parallel,np.inf,np.maximum(t1,t2))
    enter=np.maximum(0.,lo.max(1));leave=np.minimum(1.,hi.min(1))
    valid=(enter<=leave)&~np.any(parallel&(abs(p)>half+1e-10),axis=1)
    return np.concatenate([start[valid]+enter[valid,None]*delta[valid],
        start[valid]+leave[valid,None]*delta[valid]])


def intersection_vertices(a,b):
    """Return all extremal points (possibly duplicated), or an empty (0,3) array."""
    a=np.asarray(a,dtype=float);b=np.asarray(b,dtype=float)
    return np.concatenate([_clipped_edges(a,b),_clipped_edges(b,a)])
