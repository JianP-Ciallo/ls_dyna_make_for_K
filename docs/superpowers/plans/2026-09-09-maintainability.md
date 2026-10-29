# Maintainability implementation plan

User approved the five review targets and explicitly prohibited subagents.
Execute in this task, preserving existing working changes and the test policy in AGENTS.md.

## Design

Keep the built-in workbench as the authoritative production UI. Development and
build commands should use that same source. Extract persistence and HTTP request
handling from the workbench instead of introducing another UI implementation.

Keep project creation and metadata recovery together in a repository object in
`refined_blast/`. The HTTP adapter translates repository failures into API errors.
Retain project locks, identity checks, on-disk schemas and recovery semantics.
Pass LS-PrePost launcher dependencies explicitly; keep legacy imports available.

## Tasks

- [x] Convert remaining Python test matrix groups to pytest; retain smoke defaults
  and full/heavy opt-in. Add a focused refined-workbench group and a frontend
  runtime group. Verify commands through the existing dry-run policy tests.
- [x] Use one production frontend source in server, Vite development and builds.
  Verify a stale placeholder build cannot replace the workbench.
- [x] Reuse the existing persistence module; extract shared JSON request handling.
  Run persistence, state, workbench and startup runtime tests.
- [x] Extract project creation transactions and metadata into a repository with
  explicit dependencies. Move fault-injection tests to that boundary and run
  focused creation, recovery, revision and concurrency tests with small fixtures.
- [x] Replace runtime lookup through sys.modules with explicit launcher
  dependencies. Verify direct calls, MCP dispatch and external-action failures.
- [x] Standardize generated document/screenshot output under var/tmp, preserve
  historical files and input assets, document the paths and add ignore rules.
- [x] Review the diff and run relevant focused regressions. Record exact results;
  do not run full regression or heavy provider cases without fresh approval.

## Acceptance

Default smoke stays small; Python groups collect both pytest and unittest tests.
Production and build output show the full workbench. Creation retries, corrupted
metadata and competing requests retain their current outcomes. Launcher callers
have explicit dependencies. New temporary output uses the documented directory.

## Verification (2026-09-09)

Focused runs only; no full regression, heavy provider cases or subagents.
All reports are retained under `var/tmp/maintainability-tests/`.

| Scope | Result | Report |
| --- | --- | --- |
| Refined API, repository recovery, migration, damage API, external actions, architecture boundaries | 95 passed | backend-final.xml |
| Test execution policy, legacy tool exports, architecture boundaries | 41 passed | policy-final.xml |
| Frontend state, validation, static assets, startup/build, small real-HTTP workflow, preview save/abort cases | 109 passed | frontend-final-v2.xml |
| Launcher calls, explicit dependency forwarding, preview export and generation compatibility | 15 passed | launcher-final.xml |

The scopes overlap in architecture checks; these are per-run counts, not a
unique-test total. The frontend result above is the final rerun after updating
the VM test loader for the extracted modules.

Vite development checks returned HTTP 200 for the complete workbench, workbench
module and three.js viewer module, with its cache kept in web/node_modules/.vite.
The build test copied and checked the same production assets in a temporary
output directory. Local document helpers were syntax-checked and their new
output/legacy input paths inspected; document generation itself was not run.
Historical results and existing unrelated working changes were preserved.
