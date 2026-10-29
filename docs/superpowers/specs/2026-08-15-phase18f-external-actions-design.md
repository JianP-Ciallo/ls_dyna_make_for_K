# Phase 18F External Actions Design

## Purpose and boundary

Generation, opening in LS-PrePost, and launching LS-DYNA are independent
actions.  Generation remains a pure refined-blast package write and always
returns `external_program_started=false`.  Open and launch are opt-in,
per-invocation actions; no browser startup, save, preview, validation,
acknowledgement, refresh, or artifact read may start an external process.

This design deliberately does not make the generated model engineering-ready.
Every generated package and every immutable action snapshot reports
`solver_ready=false`, `requires_project_review=true`, and research status.

## Selected architecture: immutable refined action snapshots

The server accepts only the current generated package identity:

- `project_id`, `scenario_id`, `generated_revision`;
- `artifact_fingerprint` and `package_fingerprint`;
- an action-specific, fresh confirmation nonce.

Under the existing Store project transaction, it re-reads the authoritative
project, scenario, generated index, stored artifact bytes and package.  It
rejects missing, stale, corrupt, cross-project, cross-scenario, unknown-key,
or fingerprint-mismatched input before materializing anything.  It also checks
the relevant configured executable with the reviewed doctor service while the
lease is held.

For a permitted action, the server atomically creates a new immutable
directory below the refined project’s `generated/` directory.  The snapshot is
not copied into the legacy workspace or `projects/` tree.  It contains the
complete generated package closure, its evidence/index data, a generated
action manifest, and stable include files.  `main.k` is the only handoff input
and maps to the package `model.k`; all include paths are relative and are
closed before the directory becomes visible.  The manifest pins project,
scenario, revision, both fingerprints, action kind, and package closure.

The action adapter only passes this trusted snapshot path to path-oriented
neutral delegates.  It never accepts an executable, arbitrary model path,
working directory, `force`, `allow_multiple`, processor count, memory, or
timeout from the browser.  It neither calls an executable itself nor calls a
legacy name-based project API.  The LS-PrePost delegate receives only a
snapshot model path; the LS-DYNA delegate receives only a snapshot directory
and `main.k` path.  Tests mock these delegates; no test launches LS-PrePost or
LS-DYNA.

## Confirmation and replay resistance

The browser first requests a confirmation descriptor for a single action and
then displays its own explicit confirmation dialog.  Cancellation performs no
fetch.  A confirm request includes only the issued nonce plus the immutable
identity above.  The server stores a hash of action, project, scenario,
revision, artifact fingerprint, and package fingerprint with a random nonce.
It consumes the nonce atomically inside the project transaction immediately
before snapshot creation.  A nonce is single-use, short-lived, and fails
closed for a wrong action, different project/scenario/revision/package, stale
identity, or replay.  Because real actions cannot safely be replayed,
retry-on-failure is prohibited.

The browser invalidates action descriptors and disables old buttons whenever
the draft, persisted project revision, selected project/scenario, generation
response, or generated identity changes.  Open and solve are disabled by
default and become available only after an explicit confirmation is issued for
that exact action.

## Failure handling

All external-action routes use exact closed payload schemas.  Unknown keys and
any browser-controlled path/executable/working-directory/force/multiplicity
option are rejected.  Missing configuration, failing doctor checks, stale or
incomplete index/package evidence, invalid resources/includes, snapshot write
failure, and delegate failure fail closed.  No confirmation is retained for a
future call.  Responses truthfully set `external_program_started` only from
the delegate’s confirmed result; failure/unconfigured responses never claim a
start.

## Test plan

Tests first prove: generation does not delegate; external actions reject
unconfigured doctor state, stale/corrupt/mismatched identity, wrong/reused
nonce, unknown keys and client process options; cancel makes no request; each
success creates a closed snapshot and makes exactly one mocked path delegate
call; failed delegates report `external_program_started=false`; and draft
changes disable stale browser action controls.  Regression coverage includes
configuration, handoff, API, Web/static/startup, Phase 18E, Phase 17, Node
syntax, compileall, and diff checks.
