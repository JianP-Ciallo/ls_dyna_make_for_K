"""Bounded positive-definiteness certificates for the symmetric scaled tangent.

The mechanics and 1e-9 admissibility threshold are unchanged. No shift-invert
positive-near-zero inference: an unresolved eigenproblem never certifies SPD.
"""
import time

import numpy as np
from scipy import linalg,sparse
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import LinearOperator,eigsh,ArpackNoConvergence

DENSE_DOF_LIMIT=3072
DENSE_WORKSPACE_BYTES=256*1024**2
SPARSE_MATVEC_BUDGET=2048
THRESHOLD=1e-9


class _MatvecBudget(RuntimeError):pass


def check_stability(K,*,check=lambda:None,progress=lambda value:None,
                    dense_dof_limit=DENSE_DOF_LIMIT,dense_workspace_bytes=DENSE_WORKSPACE_BYTES,
                    sparse_matvec_budget=SPARSE_MATVEC_BUDGET):
    check();start=time.monotonic();K=sparse.csr_matrix(K,dtype=float)
    if K.shape[0]!=K.shape[1]:raise ValueError('切线矩阵必须为方阵')
    n=K.shape[0]
    report=dict(schema_version='scene-blast-stability@1',status='running',matrix_dofs=n,nnz=int(K.nnz),
        criterion='symmetric diagonal-scaled tangent minus threshold*I must be positive definite',
        threshold=THRESHOLD,minimum_eigenvalue=None,estimated_minimum_eigenvalue=None,certified_lower_bound=None,
        block_count=0,max_block_dofs=0,blocks=[],estimated_dense_workspace_bytes=0,
        dense_dof_limit=dense_dof_limit,dense_workspace_budget_bytes=dense_workspace_bytes,
        sparse_matvec_budget=sparse_matvec_budget,reason_code=None)

    def emit():
        report['wall_s']=float(time.monotonic()-start);progress(report)

    def finish(status,reason):
        report.update(status=status,reason_code=reason);emit();return report

    if not np.isfinite(K.data).all():return finish('unresolved','nonfinite_tangent')
    if not n:
        report['certified_lower_bound']=THRESHOLD
        return finish('positive_definite','no_free_dofs')
    diagonal=K.diagonal()
    if np.any(diagonal<=0):
        report['nonpositive_diagonal_dofs']=np.flatnonzero(diagonal<=0)[:16].tolist()
        return finish('non_positive','nonpositive_diagonal')
    check()
    scale=sparse.diags(1/np.sqrt(diagonal));S=(scale@((K+K.T)*.5)@scale).tocsr();S.eliminate_zeros()
    if not np.isfinite(S.data).all():return finish('unresolved','nonfinite_scaled_tangent')
    count,labels=connected_components(S,directed=False)
    sizes=np.bincount(labels);report.update(block_count=int(count),max_block_dofs=int(sizes.max()))
    report['estimated_dense_workspace_bytes']=int(3*8*int(sizes.max())**2)
    emit();bounds=[];unknown=[]
    for label in np.argsort(-sizes):
        check();ids=np.flatnonzero(labels==label);block=S[ids][:,ids].tocsr();m=len(ids)
        info=dict(block_index=int(label),dofs=m,status='running',method=None,
            dense_workspace_required_bytes=int(3*8*m*m),original_dof_sample=ids[:8].tolist())
        report['blocks'].append(info);emit()
        if m<=dense_dof_limit and info['dense_workspace_required_bytes']<=dense_workspace_bytes:
            info['method']='dense_cholesky';info['certificate']='Cholesky(S_block - threshold*I)'
            dense=block.toarray(order='F');dense[np.diag_indices(m)]-=THRESHOLD
            check()
            try:factor=linalg.cholesky(dense,lower=True,overwrite_a=True,check_finite=False)
            except linalg.LinAlgError as exc:
                info.update(status='non_positive',reason_code='non_positive_tangent',error=str(exc))
                return finish('non_positive','non_positive_tangent')
            check();info.update(status='positive_definite',certified_lower_bound=THRESHOLD,
                minimum_cholesky_diagonal=float(np.diag(factor).min()))
            bounds.append(THRESHOLD);del factor,dense
        else:
            # A global lower bound can certify SPD without a dense allocation.
            lower=float(np.min(block.diagonal()-(np.asarray(abs(block).sum(axis=1)).ravel()-abs(block.diagonal()))))
            info['gershgorin_lower_bound']=lower
            if lower>THRESHOLD:
                info.update(status='positive_definite',method='gershgorin',certified_lower_bound=lower)
                bounds.append(lower);emit();continue
            info.update(method='arpack_sa_diagnostic',matvec_count=0,ncv=min(m,32),maxiter=min(2000,max(200,10*m)))
            emit()
            def matvec(v):
                check()
                if info['matvec_count']>=sparse_matvec_budget:raise _MatvecBudget('sparse tangent matvec budget exhausted')
                info['matvec_count']+=1
                if info['matvec_count']%64==0:emit()
                return block@v
            operator=LinearOperator(block.shape,matvec=matvec,rmatvec=matvec,dtype=float)
            try:
                values,vectors=eigsh(operator,k=1,which='SA',tol=1e-6,maxiter=info['maxiter'],
                    ncv=info['ncv'],v0=np.random.default_rng(20261023).standard_normal(m))
                check();v=vectors[:,0];theta=float(v@(block@v)/(v@v))
                error=float(np.linalg.norm(block@v-theta*v)/np.linalg.norm(v))
                info.update(estimated_minimum_eigenvalue=theta,rayleigh_quotient=theta,eigen_residual=error)
                report['estimated_minimum_eigenvalue']=theta
                if theta<=THRESHOLD:
                    info.update(status='non_positive',reason_code='non_positive_rayleigh_quotient')
                    return finish('non_positive','non_positive_tangent')
                # A positive approximate eigenpair does not give a rigorous lower
                # bound on ALL directions. Beyond direct budget, fail as unknown.
                info.update(status='unresolved',reason_code='positive_eigenpair_without_certificate',
                    error='Positive Ritz value is not a full positive-definiteness certificate; reduce computational size or use a budgeted direct factorization')
            except _MatvecBudget as exc:
                info.update(status='unresolved',reason_code='stability_matvec_budget',error=str(exc))
            except ArpackNoConvergence as exc:
                partial=np.asarray(exc.eigenvalues)
                info.update(status='unresolved',reason_code='stability_eigen_no_convergence',error=str(exc)[:2000],
                    partial_eigenvalues=[float(x) if np.isfinite(x) else None for x in partial[:8]])
            unknown.append(info['reason_code'])
        emit()
    if unknown:return finish('unresolved',unknown[0])
    report['certified_lower_bound']=min(bounds,default=THRESHOLD)
    return finish('positive_definite','positive_certificate')
