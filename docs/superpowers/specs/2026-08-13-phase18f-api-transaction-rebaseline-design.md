# Phase 18F API Transaction Rebaseline Design

## Context

Phase 18F Task 1 passed its existing API tests, but final review found two load-bearing contract defects:

1. `RefinedBlastApi` verifies the create transaction, project, metadata, and building artifact while holding the Store project lock, then releases the lock before save, validate, preview, acknowledge, generate, or artifact retrieval performs its actual work. A second process can mutate the project between verification and use.
2. project and scenario creation accept Store-safe identifiers containing `.`, while `_path_segments()` rejects `.`, so a persisted identifier such as `project.v1` cannot be addressed through the Web API.

These are API transaction and routing defects. They do not change Phase 18D building geometry, Phase 18E provider semantics, solver readiness, or external-program authorization.

## Goals

- Make every project-scoped Web request linearizable across threads and processes.
- Keep the same project lock held from authority verification through the final state-dependent read or write and response snapshot construction.
- Preserve concurrency between different project IDs.
- Make route identifiers use the exact same safe grammar as Store identifiers.
- Preserve the dedicated `/api/refined-building-blast/` namespace and all existing host, origin, media-type, body-size, legacy-isolation, and no-external-launch gates.

## Non-goals

- Do not add Phase 18F UI features in this repair; those remain Tasks 2-8 of the existing Phase 18F plan.
- Do not change Phase 18E numerical, provider, package, or engineering-readiness contracts.
- Do not make generation optimistic or backgrounded. Performance improvements are separate from correctness.
- Do not introduce a global Web lock that serializes unrelated projects.

## Considered Approaches

### A. Project operation lease — selected

Expose a Store project transaction context and hold it for the complete API operation. Nested Store and service calls for the same root/project/thread reuse the existing lock ownership instead of opening and locking the same OS lock file again.

This provides a single linearization boundary, protects reads and writes, works across processes, and leaves different projects independent.

### B. Verify again after the operation — rejected

A post-check can detect some races, but a save, generated package, acknowledgement, or index write may already have caused side effects. Detection after mutation is not atomicity.

### C. One process-wide Web lock — rejected

It unnecessarily blocks unrelated projects and does not coordinate separate server processes.

## Architecture

### Store project transaction

`RefinedBlastStore.project_transaction(project_id)` is the public project-scoped context manager. It validates the identifier and delegates to the existing hardened local plus OS lock chain.

The internal lock becomes re-entrant for the same thread, Store root identity, and project ID. The outermost acquisition owns the local lock and OS file lock; nested `save_draft()`, `commit_generated_package()`, and other Store calls increment a thread-local depth and reuse that ownership. The outermost exit alone releases the OS lock. Exception paths must always restore the depth map and release resources.

No lock ownership is shared across threads. A different thread or process must wait. A different project ID uses a different lock and remains concurrent.

### API project operation

Every project-scoped GET or POST route enters one API project-operation context:

1. Acquire `store.project_transaction(project_id)`.
2. Read and validate the creation transaction.
3. Load the authoritative project and immutable creation metadata.
4. Recompile and verify the building artifact.
5. Create or select the service bound to that verified artifact.
6. Perform the requested read or mutation.
7. Re-read any state needed by the response and construct the complete JSON payload.
8. Release the lease only after the response no longer depends on mutable project files.

For artifact retrieval, generated-index lookup, stale checks, package decoding, integrity reconstruction, and response construction all occur inside the lease. For generation, provider compilation, generated package commit, generated-index update, and returned revision/fingerprints occur inside one lease.

The linearization rule is: whichever same-project operation acquires the lease first completes against that coherent state; the next operation observes its result. The API must never verify revision N and then perform a state-dependent action after another operation has committed revision N+1.

### Identifier grammar

Store exposes one side-effect-free identifier validator using the existing grammar:

- first character: ASCII letter or digit;
- remaining characters: ASCII letters, digits, `_`, `-`, or `.`;
- `.` and `..` are rejected;
- whitespace, slashes, backslashes, colons, percent-decoded separators, empty strings, and non-strings are rejected.

Creation persistence and dynamic Web route segments consume this same validator. Static route words are still matched explicitly, so accepting `.` in a safe dynamic segment cannot create new routes.

## Error Handling

- Invalid or unsafe route segments remain `404 not_found` without exposing filesystem paths.
- Revision races remain stable `409` conflicts through the existing API error mapping.
- Transaction, metadata, project, artifact, and generated-package integrity failures retain their current closed error codes.
- A failed operation releases its lease and cannot leave a re-entrancy depth entry behind.

## Test Design

Tests must be written and observed RED before production changes:

1. Create `project.v1` with `scenario.v1`; verify load, save, validate, preview, acknowledgement, generate, and artifact routes can address it.
2. Reject `.`, `..`, separator, whitespace, colon, and empty route identifiers while Store and Web acceptance remain identical.
3. Pause a request after authority verification and prove a second same-project API instance cannot save until the first response snapshot is complete.
4. Pause artifact retrieval after project verification and prove a concurrent save cannot make the response return an artifact checked against a different revision.
5. Use separate processes sharing one Store root to prove the same-project lease serializes while different project IDs do not share the lease.
6. Inject exceptions inside nested Store operations and prove subsequent requests can acquire the lock.
7. Re-run Phase 18F API/Web/Phase 17 and Phase 18E Store/service regressions, then request an independent concurrency-focused review.

## Compatibility Boundary

The repair may change only locking and identifier reachability. Existing response schemas, artifact/package fingerprints, Phase 18E generated bytes, Phase 18D fingerprints, legacy editor behavior, external launch policy, and `solver_ready=false` / `requires_project_review=true` remain unchanged.
