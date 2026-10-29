"""Exact saved 13-body cutout. No whole-building preparation or solve."""
import json
from pathlib import Path

import numpy as np
import pytest

from lsprepost_mcp.architecture.scene_blast.gravity import STATE,restore
from lsprepost_mcp.architecture.scene_blast.solver import MacroSystem


def fixture():
    return json.loads((Path(__file__).parent/'fixtures/scene_blast/failure_junction_92df.json').read_text(encoding='utf8'))


@pytest.mark.parametrize('name',['accepted','rejected_trial'])
def test_original_patch_preserves_recorded_poses_histories_and_cut_wrench(name):
    data=fixture();s=MacroSystem(data['model'],data['material']);item=data['states'][name]
    restore(s,{k:np.asarray(item['state'][k],dtype=getattr(s,k).dtype) for k in STATE})
    f,t,*_=s.force_state();wrench=np.c_[f[:-1],t[:-1]]
    cut=np.asarray(item['cut_connection_wrench']);whole=np.asarray(item['full_internal_wrench'])
    assert wrench+cut==pytest.approx(whole,rel=1e-11,abs=1e-6)
    mapping=data['metadata']['body_source_indices']
    interior=[mapping.index(i) for i in data['metadata']['interior_source_indices']]
    assert cut[interior]==pytest.approx(np.zeros((len(interior),6)),abs=1e-8)
    boundary=[mapping.index(i) for i in data['metadata']['boundary_source_indices']]
    assert np.any(abs(s.x[boundary]-s.x0[boundary])>1e-8)
    assert np.any(abs(s.R[boundary]-np.eye(3))>1e-8)
    assert all(s.fixed[i] for i in boundary)
    assert not any(s.fixed[i] for i in interior)
    # Pair wrenches conserve global angular momentum even at recorded finite pose.
    assert f.sum(0)==pytest.approx(np.zeros(3),abs=1e-6)
    assert (t+np.cross(s.x,f)).sum(0)==pytest.approx(np.zeros(3),abs=1e-5)


def test_recorded_boundary_reaction_accounts_for_cut_tractions_and_boundary_weight():
    data=fixture();item=data['states']['accepted'];s=MacroSystem(data['model'],data['material'])
    restore(s,{k:np.asarray(item['state'][k],dtype=getattr(s,k).dtype) for k in STATE})
    f,t,*_=s.force_state();wrench=np.c_[f[:-1],t[:-1]]
    external=np.asarray(item['cut_connection_wrench']).copy()
    external[:,:3]+=item['load_factor']*np.asarray(item['original_gravity_n'])
    residual=wrench+external
    reaction=np.zeros_like(external);fixed=s.fixed[:-1];reaction[fixed]=-residual[fixed]
    remaining=residual[~fixed]
    assert (external+reaction)[:,:3].sum(0)==pytest.approx(remaining[:,:3].sum(0),abs=1e-6)
    moment=lambda w:(w[:,3:]+np.cross(s.x[:-1],w[:,:3])).sum(0)
    expected=np.zeros_like(residual);expected[~fixed]=remaining
    assert moment(external+reaction)==pytest.approx(moment(expected),abs=1e-5)


def test_original_mapping_patch_failure_is_retained_as_negative_control(tmp_path):
    data=fixture();s=MacroSystem(data['model'],data['material']);item=data['states']['accepted']
    restore(s,{k:np.asarray(item['state'][k],dtype=getattr(s,k).dtype) for k in STATE})
    with pytest.raises(ValueError) as caught:s.equilibrate(time_budget_s=5.)
    d=caught.value.diagnostics
    assert d['reason_code']=='line_search_failed' and d['accepted_load_factor']<.3
    assert d['blast_applied'] is False and d['restored_to_accepted_state']
    (tmp_path/'original-patch-negative-control.json').write_text(json.dumps(d,indent=2),encoding='utf8')
