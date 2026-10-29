"""Gravity virtual work for interpolated shell/column attachments.

This corrects static gravity loading only. The legacy positive eccentric point
mass approximation is retained for dynamics and needs separate validation.
"""
import numpy as np
from .contracts import fingerprint

POLICY='source_shape_virtual_work@1'


def shape_gravity(nodes,points,masses,tags,weights,group_width):
    """Return N^T mg and only the actual offset from each support surface.

    Adjacent-floor routing has two groups of four shape weights. Normalize
    each group's attachment position separately; never average the two floors.
    """
    nodes=np.asarray(nodes);points=np.asarray(points);masses=np.asarray(masses)
    tags=np.asarray(tags);weights=np.asarray(weights)
    if tags.shape!=weights.shape or tags.shape[0]!=len(points) or tags.shape[1]%group_width:
        raise ValueError('gravity shape map dimensions')
    if not np.isfinite(weights).all() or np.any(weights<0) or not np.allclose(weights.sum(1),1.,atol=1e-12,rtol=0):
        raise ValueError('gravity shape map must partition unity')
    result=np.zeros((len(nodes),6));forces=np.zeros((len(points),3));forces[:,2]=-9.80665*masses
    for begin in range(0,tags.shape[1],group_width):
        ids=tags[:,begin:begin+group_width];w=weights[:,begin:begin+group_width];total=w.sum(1)
        position=np.einsum('pi,pij->pj',w,nodes[ids])/np.where(total>0,total,1.)[:,None]
        offset=points-position
        for j in range(group_width):
            f=w[:,j,None]*forces
            np.add.at(result[:,:3],ids[:,j],f)
            np.add.at(result[:,3:],ids[:,j],np.cross(offset,f))
    return result


def gravity_dependencies(case):
    return fingerprint({k:case[k] for k in ('nodes','elements','mass_points')})


def mapped_gravity(case):
    """Validate an explicit mapping; never use a stale table after model edits."""
    record=case['loads'].get('gravity_mapping')
    if record is None:return None
    if record.get('policy')!=POLICY or record.get('dependencies')!=gravity_dependencies(case):
        raise ValueError('重力映射来源已变更，必须重新按形函数映射，禁止沿用旧表')
    values=np.asarray(record['nodal_wrenches_n_nm'],dtype=float)
    if values.shape!=(len(case['nodes']),6) or not np.isfinite(values).all():raise ValueError('invalid gravity mapping')
    if record.get('gravity_m_s2')!=9.80665:raise ValueError('gravity constant changed')
    return values
