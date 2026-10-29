# Native failure diagnostics implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline; keep the existing checkout and all previous evidence.

**Goal:** Locate the first terminal native trial failure without changing mechanics, and validate diagnostics with frozen material history and a minimal shell.

**Spec:** The user's confirmed 2026-10-24 scope and the preceding read-only analysis in this conversation.

**Architecture:** Opt-in JSONL diagnostics from ShellMITC4 → LayeredShellFiberSection → PlateFiber → ASDConcrete3D. Scoped context carries element/IP/layer and nodal/section/material trial inputs. Intermediate failed root probes stay internal; only terminal rejection emits the first event. A cloned material is serialized into an in-memory Channel, preserving a replayable pre-rejection checkpoint without modifying the live material. Logging failures cannot change material return codes.

**Approaches:** Plain text logging cannot replay history; logging all probes confuses recovered searches with rejected updates. Use one bounded structured terminal event with a clone-based checkpoint. This implements the already approved diagnostic approach; no further approval gate is needed for these routine choices.

**Tech stack:** Existing MinGW/CMake cache, OpenSees v3.8.0 repair tree, Python 3.12 and pytest.

## Constraints

- No whole building, TNT, full regression or other heavy tests. No geometry generation or default-backend change.
- No changes to constitutive laws, strengths, Gf, reinforcement, supports, root tolerance 1e-8 Pa, physical residual 1e-5 or tangent criterion 1e-9.
- Preserve validated runtime, old build binaries, fixtures and logs. Build new binaries into a new output directory using the existing compilation cache; stage into a separate diagnostic runtime.
- No worktree, commits, merge, reset or cleanup. One existing read-only reviewer checks model assumptions and final diagnostic correctness.

## Tasks

- [x] Freeze baselines; write black-box diagnostic tests; observe missing-event RED on the previously validated native harness.
- [x] Add opt-in scoped diagnostics and clone/Channel checkpoints. Label nonfinite input, ASD guarded branches, root stages, invalid final response and invalid condensation separately. Preserve all existing decisions and return codes.
- [x] Build diagnostic binaries into a new directory; clone and stage a separate runtime; verify old runtime and build binary hashes unchanged.
- [x] Run frozen material tests, native root/state/serialization checks and new diagnostic tests including replay of a nonzero-history checkpoint, recovered probe silence, first-event bounds and disabled/I/O-failure behavior.
- [x] Run one-element plate checks with the original material law, plus focused shell/reference tests. Never replay an incomplete whole-building snapshot as a full native checkpoint.
- [x] Save independent read-only column-head, hotspot mesh and reinforcement-coordinate audit. Review results and report remaining uncertainty; do not infer the exact old failed material point from newly synthesized small probes.
