# Phase 15 Parameterized Conforming Air-Gap Workflow Design

## Status

This design supersedes the direct-contact conforming geometry in
`2026-07-23-phase15-conforming-interface-design.md` for new work. The existing
`conforming_shared_nodes` implementation remains readable as historical,
experimental evidence, but it is not exposed as a qualified Web workflow.

## Goal

Add a general Phase 15 axisymmetric blast mode with this physical path:

```text
TNT detonation
  -> pressure wave through ALE air
  -> zero-overlap conforming air/concrete interface
  -> K&C concrete pressure, stress, displacement, and damage
```

The user configures the model in the existing Web application, generates and
validates `model.k`, hands an isolated run snapshot to LS-Run, and opens the
completed `d3plot` in LS-PrePost. The workflow must never report successful
wave transfer from static validation or normal solver termination alone.

## Supported Coupling Modes

Phase 15 keeps three internal coupling modes:

- `immersed_clis`: qualified reference workflow with controlled ALE/concrete
  computational overlap and `*CONSTRAINED_LAGRANGE_IN_SOLID`.
- `conforming_air_gap`: new parameterized zero-overlap workflow.
- `conforming_shared_nodes`: historical direct TNT/concrete shared-node
  experiment; retained for compatibility and marked `experimental_unqualified`.

`immersed_clis` remains the production default until `conforming_air_gap`
passes the real solver and postprocessing gates in this design. The Web
application exposes `immersed_clis` and `conforming_air_gap`; it does not expose
the unqualified direct-contact experiment.

## Public Parameter Contract

The new mode adds these inputs:

```json
{
  "coupling_mode": "conforming_air_gap",
  "borehole_radius_m": 0.073,
  "bottom_air_gap_m": 0.024
}
```

Existing Phase 15 inputs continue to control:

- TNT mass, radius or diameter, length, density, and consistency decision;
- TNT bottom depth;
- concrete radius and height;
- top air height;
- mesh size;
- K&C and steel material settings;
- end time and output intervals.

The default borehole radius is the resolved TNT radius plus four requested mesh
sizes. The default bottom air gap is four requested mesh sizes. Defaults are
resolved explicitly and recorded in `model.json`; they are not recomputed when
an existing project is reopened.

The generator enforces these non-bypassable invariants:

1. `borehole_radius_m > resolved_tnt_radius_m`.
2. `bottom_air_gap_m > 0`.
3. Side and bottom air gaps each contain at least three actual ALE cells.
4. The borehole bottom remains inside the concrete target.
5. TNT cells do not share a node or edge with concrete cells.
6. ALE/concrete volume overlap and geometric gap are both zero within a
   mesh-scaled tolerance.
7. Every active borehole side and bottom interface edge has exactly one ALE
   element and one concrete element.
8. The model stays within the existing node, element, and keyword-size
   preflight limits.

Invalid combinations fail without silently changing user values. The error
reports the actual gap, actual cell count, and minimum recommended dimension.

## Geometry and Mesh

Let:

```text
charge_radius = resolved TNT radius
charge_bottom = resolved TNT bottom z coordinate
borehole_radius = user borehole radius
borehole_bottom = charge_bottom - bottom_air_gap
```

The concrete cavity is:

```text
0 <= r < borehole_radius
borehole_bottom < z <= target_top
```

The ALE domain fills the complete cavity and the open air column above it.
TNT occupies only:

```text
0 <= r <= charge_radius
charge_bottom <= z <= charge_top
```

Air fills the side annulus, bottom gap, space above the charge, and the open
column above the target. TNT and air use the existing multi-material ALE
formulation. The initial volume-fraction geometry must not classify any TNT
material in a concrete cell.

The active conforming interface contains only:

- `borehole_bottom` at `z = borehole_bottom`;
- `borehole_side` at `r = borehole_radius`.

The target top outside the borehole is a concrete free surface. The air column
opening and its outer/top boundaries use the existing controlled
non-reflecting treatment. The conforming mode emits no CLIS card and no DBFSI
slave-surface claim.

ALE and concrete use common node IDs on the active interface. Shared interface
nodes move as Lagrangian boundary nodes; interior ALE nodes use
`*CONTROL_ALE` and targeted ALE smoothing constraints. Mesh construction must
reject duplicate coincident interface nodes, zero-area cells, reversed
elements, and incomplete edge adjacency before writing a project.

## Model Metadata

`model.json` records the resolved geometry rather than inferred labels:

```json
{
  "interfaces": {
    "coupling_mode": "conforming_air_gap",
    "transfer_mechanism": "shared_node_ale_lagrange_interface",
    "active_surfaces": ["borehole_bottom", "borehole_side"],
    "shared_node_count": 0,
    "shared_edge_count": 0,
    "geometric_gap_max_m": 0.0,
    "ale_concrete_overlap_area_m2": 0.0,
    "tnt_concrete_shared_node_count": 0
  },
  "phase15": {
    "side_air_gap_m": 0.024,
    "side_air_gap_cells": 4,
    "bottom_air_gap_m": 0.024,
    "bottom_air_gap_cells": 4
  }
}
```

The ALE-domain metadata uses actual generated radial and axial extents. Legacy
`fsi_surfaces` fields remain only for `immersed_clis`; conforming reports use
`interface_surfaces` and `transfer_evidence`.

## K-File Generation

The generated keyword must include:

- one coherent axisymmetric ALE air/TNT mesh;
- K&C concrete and the existing steel confinement;
- explicit shared nodes on borehole side and bottom;
- non-reflecting air boundaries;
- ALE smoothing controls;
- ALE pressure history probes;
- concrete interface and depth probes;
- K&C history variables required for pressure, principal stress, and scaled
  damage;
- output intervals sufficient to resolve traversal of the smallest allowed air
  gap.

The K-file validator adds mode-specific checks:

- no `*CONSTRAINED_LAGRANGE_IN_SOLID` in `conforming_air_gap`;
- no TNT/concrete node or edge sharing;
- non-empty side and bottom air regions;
- complete conforming interface;
- no ALE/concrete overlap;
- expected probe sets and database cards present.

## LS-Run Handoff and Result Recovery

LS-Run is the user-visible job submission and monitoring application. It is not
the postprocessor.

Before opening LS-Run, the server creates an isolated run directory:

```text
workspace/projects/<project>/solver_runs/<run_id>/
```

It atomically copies `model.k` and `model.json`, records their hashes, records
the selected LS-Run and LS-DYNA identities, and writes a pending run record.
LS-Run starts with this run directory as its working directory and the snapshot
`model.k` as the intended input. The Web UI shows the exact input path, solver,
CPU count, memory, and run ID before launch.

The local LS-Run version is capability-checked before attempting input
prefill. If this LS-Run build cannot accept the input file through its launch
arguments, the workflow opens LS-Run in the prepared run directory and
prominently exposes the exact snapshot path for the INPUT field. It must not
pretend that a job was submitted merely because the LS-Run process opened.

After LS-Run finishes the LS-DYNA job, the Web application can refresh/import
the run. Recovery requires `d3hsp`, `d3plot`, and the configured history files,
binds their hashes to the original input snapshot, and evaluates the same
solver and propagation gates as direct controlled runs. A changed input or
output produces `invalid_evidence`.

## Propagation Acceptance

The conforming mode is qualified only when all of the following pass:

1. LS-DYNA terminates normally and the evidence manifest matches.
2. No negative-volume, zero-area, ALE leakage, or non-finite-energy failure is
   present.
3. A pressure response appears at a TNT-near ALE probe.
4. A pressure response appears later at a mid-gap air probe.
5. A pressure response appears later at an interface-adjacent ALE probe.
6. Concrete interface pressure or principal stress responds no earlier than
   the interface-adjacent ALE pressure, within one history-output interval.
7. Deeper concrete probes respond in geometric order with finite apparent wave
   speeds.
8. Concrete hydrostatic pressure and principal stress exceed their
   baseline-plus-noise gates for a non-zero duration.
9. K&C scaled damage is readable and finite. Positive damage is reported but
   is not required for every low-load parameter combination.
10. Concrete displacement is finite and occurs after the corresponding local
    load. Pre-arrival displacement above the noise gate fails acceptance.

Each signal uses a pre-arrival baseline, a finite-value check, a
baseline-relative signal-to-noise gate, an absolute engineering noise floor,
and a minimum duration. A single numerical spike does not qualify as
propagation.

The result is reported as one of:

- `qualified`: all geometry, solver, transfer, and postprocessing gates pass;
- `solver_complete_unqualified`: solver completed but transfer evidence failed;
- `invalid_evidence`: run files do not match their recorded identities;
- `failed`: solver or geometry failure.

## LS-PrePost Postprocessing

LS-PrePost opens the immutable run snapshot `d3plot`, not a mutable project-root
result. A server-generated cfile produces at least:

- ALE pressure progression at source, mid-gap, and interface times;
- concrete pressure contour after interface arrival;
- concrete principal-stress contour;
- K&C scaled-damage contour when the selected LS-PrePost version exposes it;
- true-scale (`1.0`) deformation view and a separately labeled amplified view
  when needed for visibility.

Generated PNG/GIF artifacts include the run ID, state time, component, display
scale, input hash, result hash, and cfile hash. Visual output supplements the
numeric gates; it cannot override a failed numeric acceptance.

## Web Application

The existing built-in Web UI gains:

- a coupling-mode selector with `侵入式 CLIS` and `共形空气间隙`;
- borehole radius and bottom air-gap controls shown only for the conforming
  mode;
- a live side/bottom gap summary in millimetres and actual mesh-cell counts;
- overlap-layer controls shown only for `immersed_clis`;
- an explicit warning when a conforming combination is below the three-cell
  minimum;
- resolved geometry and estimated mesh size in the prepare response;
- a `生成 K 文件` action;
- a `提交至 LS-Run` action that displays and records the run snapshot;
- a `刷新求解结果` action;
- an `在 LS-PrePost 中查看` action enabled only when a usable `d3plot` exists;
- separate badges for static validity, solver completion, wave-transfer
  qualification, and K&C calibration status.

The UI does not present normal termination as successful wave transfer. It
does not hide the distinction between an uncalibrated material demonstration
and a calibrated engineering prediction.

## Error Handling

- Invalid geometry returns field-specific `400` responses with minimum values.
- A locked project or existing active run returns `409`.
- Missing or invalid LS-Run, LS-DYNA, or LS-PrePost configuration returns a
  named configuration error before process launch.
- LS-Run opening without a submitted job remains `handoff_opened`, never
  `running` or `completed`.
- Solver timeout or abnormal termination preserves outputs for diagnosis.
- Postprocessing failure does not erase a valid solver run; it reports
  `postprocessing_failed`.
- Evidence mismatch is fail-closed and cannot be overridden from the Web UI.

## Compatibility

- Existing `immersed_clis` projects and solver evidence remain readable.
- Existing `conforming_shared_nodes` projects remain readable but retain
  `experimental_unqualified`.
- Calls omitting `coupling_mode` continue to generate `immersed_clis`.
- Convergence comparisons reject mixed coupling modes and mismatched resolved
  gap geometry.
- No existing project directory is converted automatically.

## Existing-Project Immutability and Tool Reuse

Implementation and qualification must not modify any project directory that
existed before this work started. This includes old `model.k`, `model.json`,
checks, artifacts, solver runs, latest-run pointers, manifests, and archives.
Historical projects are read-only references.

The new workflow requires a new, valid project name and always uses
`if_exists=error`. It must not expose overwrite or archive-and-replace behavior
for conforming qualification. LS-Run snapshots, recovered outputs, and
LS-PrePost artifacts are written only below the newly created project.

Implementation reuses the existing libraries and their safety boundaries:

- Phase 15 geometry, material, keyword, and acceptance modules;
- project store, project locks, artifact paths, and provenance manifests;
- LS-DYNA run records, evidence hashing, and result parsers;
- LS-Run and LS-PrePost configuration doctors;
- server-generated cfiles and controlled process launchers;
- existing Web request, error, and static-UI conventions.

A new helper or module is permitted only when the existing library has no
coherent owner for the required behavior. New code must call existing
validators and launchers rather than duplicating path handling, process
management, evidence hashing, or JSON parsing.

## Testing

Unit and contract tests cover:

- default and explicit coupling-mode behavior;
- geometry derivation and three-cell gap gates;
- absence of TNT/concrete adjacency;
- zero overlap and complete shared-edge topology;
- legacy immersed keyword stability;
- conforming keyword cards and probe sets;
- Web payload and conditional controls;
- isolated LS-Run snapshot creation;
- LS-Run-opened versus job-submitted state;
- result evidence hash recovery;
- ordered propagation, pre-arrival displacement, noise, duration, and damage
  gates;
- mode-specific result reporting.

Integration checks proceed in this order:

1. Generate a small conforming model and run static validators.
2. Import `model.k` in LS-PrePost and require zero keyword-reader errors.
3. Run a short LS-DYNA initialization check.
4. Run the full controlled case through the prepared LS-Run directory.
5. Recover and hash result evidence.
6. Evaluate propagation acceptance.
7. Generate and visually inspect LS-PrePost pressure, stress, damage, and
   deformation artifacts.
8. Verify the Web workflow at desktop and narrow viewport sizes.

## Qualification Boundary

Passing this workflow proves that the modeled pressure wave travels through
the ALE air gap and transfers into the K&C concrete without ALE/concrete volume
overlap. It does not prove that the uncalibrated K&C parameters predict a
specific physical specimen. Quantitative engineering claims still require
material calibration and mesh-convergence evidence.
