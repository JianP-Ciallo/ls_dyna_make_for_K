"""Synthetic matrices and one macro block only; never solve the real building."""
from copy import deepcopy
import json
import time

import numpy as np
import pytest
from scipy import sparse,linalg


def hard_spd(n=256):
    # Analytically SPD: orthogonal Hadamard basis, eigenvalues 1e-7 .. 1.
    # Constant diagonal means the scaled minimum is exactly 1e-7 / mean(e).
    H=linalg.hadamard(n).astype(float)/np.sqrt(n)
    eigenvalues=np.geomspace(1e-7,1.,n)
    return sparse.csr_matrix((H*eigenvalues)@H.T)


def test_known_spd_above_old_96_dof_boundary_gets_a_certificate(tmp_path):
    from lsprepost_mcp.architecture.scene_blast.gravity import stable_tangent
    report=stable_tangent(hard_spd())
    assert report is not None, 'old fixed-200-iteration path cannot confirm this known SPD matrix'
    assert report['status']=='positive_definite'
    assert report['blocks'][0]['method']=='dense_cholesky'
    assert report['minimum_eigenvalue'] is None  # a certificate is not an invented eigenvalue
    assert report['certified_lower_bound']>=1e-9
    json.dumps(report,allow_nan=False)
    (tmp_path/'stability.json').write_text(json.dumps(report,indent=2),encoding='utf8')


@pytest.mark.parametrize('matrix,want',[
    ([[1.,1.-2e-8],[1.-2e-8,1.]],'positive_definite'),
    ([[1.,1.-2e-10],[1.-2e-10,1.]],'non_positive'),
    ([[1.,1.],[1.,1.]],'non_positive'),
    ([[1.,2.],[2.,1.]],'non_positive'),
    ([[0.,0.],[0.,1.]],'non_positive'),
    ([[1.,float('nan')],[float('nan'),1.]],'unresolved'),
])
def test_threshold_negative_and_nonfinite_tangents_are_not_silently_accepted(matrix,want):
    from lsprepost_mcp.architecture.scene_blast.stability import check_stability
    report=check_stability(sparse.csr_matrix(matrix))
    assert report['status']==want
    json.dumps(report,allow_nan=False)


def test_positive_modes_near_zero_cannot_hide_a_far_negative_direction():
    from lsprepost_mcp.architecture.scene_blast.stability import check_stability
    # Eigenvalues: -1.56 and 1 (127 times), with all positive diagonal entries.
    matrix=sparse.csr_matrix(np.eye(128)-.02*np.ones((128,128)))
    report=check_stability(matrix,dense_dof_limit=16)
    assert report['status']=='non_positive'
    assert report['estimated_minimum_eigenvalue']<0
    assert report['blocks'][0]['eigen_residual']<1e-6


def test_disconnected_blocks_share_no_dense_allocation_and_keep_all_couplings():
    from lsprepost_mcp.architecture.scene_blast.stability import check_stability
    matrix=sparse.block_diag([hard_spd(128)]*4,format='csr')
    report=check_stability(matrix,dense_dof_limit=128)
    assert report['status']=='positive_definite'
    assert report['matrix_dofs']==512 and report['block_count']==4
    assert max(b['dofs'] for b in report['blocks'])==128
    assert all(b['method']=='dense_cholesky' for b in report['blocks'])


def test_sparse_fallback_matvec_budget_reports_unknown_not_physical_failure():
    from lsprepost_mcp.architecture.scene_blast.stability import check_stability
    matrix=sparse.diags([-np.ones(127),2*np.ones(128),-np.ones(127)],[-1,0,1],format='csr')
    report=check_stability(matrix,dense_dof_limit=16,sparse_matvec_budget=1)
    assert report['status']=='unresolved'
    assert report['reason_code']=='stability_matvec_budget'
    assert report['blocks'][0]['matvec_count']<=1
    assert report['blocks'][0]['error']


def test_sparse_dominance_certificate_respects_the_memory_limit():
    from lsprepost_mcp.architecture.scene_blast.stability import check_stability
    matrix=sparse.diags([-np.ones(127),4*np.ones(128),-np.ones(127)],[-1,0,1],format='csr')
    report=check_stability(matrix,dense_dof_limit=16,dense_workspace_bytes=1024)
    assert report['status']=='positive_definite'
    assert report['blocks'][0]['method']=='gershgorin'
    assert report['certified_lower_bound']==pytest.approx(.5)


def test_stability_calls_cancellation_guard_without_swallowing_it():
    from lsprepost_mcp.architecture.scene_blast.stability import check_stability
    calls=[]
    def cancelled():
        calls.append(1)
        raise TimeoutError('owned time/cancellation sentinel')
    with pytest.raises(TimeoutError,match='sentinel'):
        check_stability(hard_spd(128),check=cancelled)
    assert len(calls)==1


def test_same_2694_dof_synthetic_matrix_is_within_direct_certificate_budget(tmp_path):
    from lsprepost_mcp.architecture.scene_blast.stability import check_stability
    # Arithmetic-only fixture at the same dimension as the building; no geometry,
    # self-weight, TNT load, model reduction, or real building solver invocation.
    n=2694
    matrix=sparse.diags([-np.ones(n-1),2*np.ones(n),-np.ones(n-1)],[-1,0,1],format='csr')
    start=time.monotonic();report=check_stability(matrix);elapsed=time.monotonic()-start
    assert report['status']=='positive_definite'
    assert report['blocks'][0]['method']=='dense_cholesky'
    assert report['estimated_dense_workspace_bytes']<=report['dense_workspace_budget_bytes']
    (tmp_path/'scale-matrix.json').write_text(json.dumps(dict(fixture='SYNTHETIC_MATRIX_ONLY_NOT_BUILDING',wall_s=elapsed,diagnostic=report),indent=2),encoding='utf8')


def test_unresolved_stability_stops_one_load_attempt_and_keeps_history(tmp_path,monkeypatch):
    from lsprepost_mcp.architecture.scene_blast import gravity
    from lsprepost_mcp.architecture.scene_blast.sources import shell_model
    from lsprepost_mcp.architecture.scene_blast.solver import MacroSystem
    model=shell_model('micro',[(1,0,0,0),(2,1,0,0),(3,1,0,1),(4,0,0,1)],[(1,1,1,2,3,4)],.2)
    system=MacroSystem(model);x=system.x.copy();history=system.history.copy()
    def unknown(matrix,**options):
        d=dict(status='unresolved',minimum_eigenvalue=None,reason_code='stability_matvec_budget',
            matrix_dofs=matrix.shape[0],blocks=[dict(error='mocked diagnostic boundary, no physical model alteration')])
        options['progress'](d);return d
    monkeypatch.setattr(gravity,'stable_tangent',unknown)
    with pytest.raises(gravity.GravityFailure) as caught:system.equilibrate()
    d=caught.value.diagnostics
    assert d['reason_code']=='stability_unresolved'
    assert len(d['attempts'])==1 and d['accepted_load_factor']==0
    assert 'stability_matvec_budget' in str(caught.value)
    assert np.array_equal(system.x,x) and np.array_equal(system.history,history)
    assert d['last_stability']['blocks'][0]['error']
    (tmp_path/'gravity-unresolved.json').write_text(json.dumps(d,indent=2),encoding='utf8')


def test_stability_budget_abort_keeps_current_attempt_diagnostic(monkeypatch):
    from lsprepost_mcp.architecture.scene_blast import gravity
    from lsprepost_mcp.architecture.scene_blast.sources import shell_model
    from lsprepost_mcp.architecture.scene_blast.solver import MacroSystem
    model=shell_model('micro',[(1,0,0,0),(2,1,0,0),(3,1,0,1),(4,0,0,1)],[(1,1,1,2,3,4)],.2)
    system=MacroSystem(model);stability_started=[]
    def cancelled(matrix,**options):
        options['progress'](dict(status='running',matrix_dofs=6,blocks=[dict(method='dense_cholesky',status='running')]))
        stability_started.append(True);options['check']()
    monkeypatch.setattr(gravity,'stable_tangent',cancelled)
    with pytest.raises(gravity.GravityFailure) as caught:
        system.equilibrate(cancel=lambda:bool(stability_started))
    assert caught.value.status=='cancelled'
    assert caught.value.diagnostics['last_stability']['blocks'][0]['method']=='dense_cholesky'
    assert caught.value.diagnostics['accepted_load_factor']==0


def test_small_panel_strip_above_96_free_dofs_uses_new_certificate(tmp_path):
    from lsprepost_mcp.architecture.scene_blast.sources import shell_model
    from lsprepost_mcp.architecture.scene_blast.solver import MacroSystem
    nodes=[]
    for i in range(18):nodes.extend([(2*i+1,i*.5,0.,0.),(2*i+2,i*.5,0.,.5)])
    shells=[(i+1,1,2*i+1,2*i+3,2*i+4,2*i+2) for i in range(17)]
    model=shell_model('MICRO_STRIP_NOT_BUILDING',nodes,shells,.2)
    system=MacroSystem(model)
    assert len(system.free)==102
    assert system.equilibrate()<1e-5
    d=system.gravity_diagnostics
    assert d['last_stability']['status']=='positive_definite'
    assert d['last_stability']['matrix_dofs']==102
    assert all(b['method']=='dense_cholesky' for b in d['last_stability']['blocks'])
    initial=system.x.copy()
    for _ in range(20):system.step(.25*system.dt_stable)
    assert np.max(abs(system.x-initial))<1e-8
    (tmp_path/'strip-gravity.json').write_text(json.dumps(d,indent=2),encoding='utf8')
