# City Ground Crater Validation Design

**Date:** 2026-08-01
**Status:** Approved design
**Target capability:** `city_ground_crater_v1`

## 1. Purpose

Add an opt-in ground-response mode to the Phase 17 city street blast scene. The
mode must demonstrate a complete numerical path from TNT detonation through the
ALE air domain and FSI into a solid ground model, followed by readable ground
pressure, stress, K&C damage, downward displacement, element erosion, and a
finite measurable crater.

This is a validation workflow. It proves that the model, solver outputs, and
acceptance chain work together. It must not claim calibrated crater dimensions
or engineering prediction accuracy for a real road or soil site.

## 2. Scope

### In scope

- Preserve the existing `city_street_blast` behavior as the legacy mode.
- Add a versioned `city_ground_crater_v1` mode.
- Replace road and ground shells with connected hexahedral solid ground when the
  new mode is selected.
- Extend the ALE grid below the initial ground surface using a controlled depth.
- Use separate eroding and non-eroding FSI interfaces.
- Reuse the controlled Phase 15 K&C material and erosion rendering path.
- Preserve independent object-level FSI and response evidence for buildings,
  vehicles, subway entrances, and traffic lights.
- Produce ground-specific result images, metrics, and acceptance evidence.
- Expose the capability in the Web city editor without silently changing old
  projects or API calls.

### Out of scope

- Calibrated prediction of real crater depth or diameter.
- Calibrated soil, pavement, moisture, reinforcement, fragmentation, or debris
  behavior.
- Erosion beneath or through a building foundation.
- Automatic weakening of material parameters until a visually attractive crater
  appears.
- Treating normal solver termination or a non-empty d3plot as proof of success.

## 3. Compatibility Contract

- A city specification without `ground_response` retains the current fixed-shell
  ground behavior.
- The new behavior requires `ground_response.mode = "validation_crater"`.
- Existing generated projects and solver result directories are never rewritten.
- New generation uses a new project name and the existing `if_exists` policy.
- Existing building, vehicle, facility, city-impact, evidence-hash, and Phase 17
  editor identities remain stable.
- Phase 16 city assessment receives one additional semantic object for the ground
  crater. Global DBFSI values may not be substituted for this object.

## 4. Resolved Specification

The new mode adds the following normalized specification block:

```json
{
  "ground_response": {
    "mode": "validation_crater",
    "anticipated_crater_depth_m": 0.6,
    "ale_overlap_layers": 5,
    "erosion_mode": "standard_observation",
    "material_preset": "kc_a1_automatic_reference",
    "capability_version": "city_ground_crater_v1"
  }
}
```

Allowed local ground mesh sizes are `0.20`, `0.15`, and `0.10 m`. Allowed ALE
overlap layer selections are `5` and `7`. Custom erosion thresholds remain an
advanced path and require strict `confirmed_by_user is True` validation.

The default derived dimensions are:

```text
h = local central ground/ALE mesh size

actual_ale_overlap_layers = max(
    ale_overlap_layers,
    ceil(anticipated_crater_depth/h) + 2,
    4
)
ale_overlap_depth = actual_ale_overlap_layers*h

raw_eroding_zone_half_width = max(
    3.0 m,
    2*anticipated_crater_depth + 4*h
)
eroding_zone_half_width = ceil(raw_eroding_zone_half_width/h)*h

eroding_ground_depth = ale_overlap_depth + 2*h
support_depth = max(0.4 m, 2*h)
total_ground_depth = eroding_ground_depth + support_depth
```

For the initial `h = 0.20 m`, five-layer configuration, the ALE overlap depth is
`1.0 m`, the eroding-zone half-width is `3.0 m`, and the solid ground retains at
least two intact layers below the ALE overlap. Selecting seven layers changes
the overlap depth to `1.4 m` and regenerates the ground depth accordingly.

These values are numerical design bounds, not predictions of a 250 kg TNT
surface-burst crater.

## 5. Geometry and Mesh Architecture

The initial ground surface remains at `z = 0`. The ALE lower bound moves from
`z = 0` to `z = -ale_overlap_depth`. The TNT remains initialized exclusively by
ALE volume fraction and is not converted into a Lagrangian explosive part.

When crater mode is active:

1. Road and urban ground regions are remeshed as connected hexahedral solids.
2. A source-centered, axis-aligned square zone is assigned to the eroding ground
   part. Its half-width is `eroding_zone_half_width`; its boundaries snap outward
   to the next local ground-grid line so no cut cells are created.
3. The surrounding ground is assigned to non-eroding solid parts.
4. A lower non-eroding solid support region completes the ground depth.
5. Adjacent ground regions use matching interface nodes. Duplicate coincident
   faces are forbidden.
6. Building and fixed-facility base-node sets are connected to the generated
   ground top surface by dedicated `*CONTACT_TIED_NODES_TO_SURFACE` cards. Those
   base nodes are not independently fixed to global space in crater mode. Every
   base node must be present in exactly one such tied contact.
7. Vehicles remain free and use the existing road/parking contact path.
8. Ground faces covered by building foundations are excluded from exposed-air
   FSI.

The central eroding zone must not intersect a building or fixed-facility support
footprint. Generation fails before writing a project if the source movement would
violate this rule. This first version intentionally does not model a crater
propagating through a building foundation.

Moving the blast source in Phase 17 regenerates the TNT fill, ALE refinement
window, central eroding zone, ground probes, and all derived depth/clearance
checks. The mesh is never translated as a stale block from a previous source
position.

## 6. Material and Erosion Contract

### Central eroding ground

- Reuse the Phase 15 controlled `*MAT_CONCRETE_DAMAGE_REL3` renderer.
- Use preset `kc_a1_automatic_reference` with `NOUT=2`.
- Reuse `*MAT_ADD_EROSION` preset `standard_observation`.
- The preset maximum principal strain deletion threshold is `0.05`.
- Metadata must state `numerical_element_deletion_only` and
  `automatic_reference_not_site_calibrated`.

### Peripheral ground and lower support

- Use the existing city reference elastic concrete card for both regions:
  `*MAT_ELASTIC`, density `2400 kg/m^3`, Young's modulus `3.0e10 Pa`, and
  Poisson ratio `0.20`.
- These parts must output pressure, stress, and displacement but must not be
  deleted by the central erosion criterion.
- The first release uses an elastic support material instead of inventing an
  uncalibrated soil pressure-volumetric-strain curve.
- Metadata must label both regions `validation_only_uncalibrated_ground` and
  must not identify them as a calibrated soil or pavement model.

The material model may only be upgraded to a soil model after a named, unit-
checked preset and its single-element compression/unloading test are added. Such
an upgrade is outside `city_ground_crater_v1`.

## 7. FSI Architecture

Use separate coupling cards for eroding and non-eroding structures:

- Central eroding ground: `*CONSTRAINED_LAGRANGE_IN_SOLID` with `CTYPE=5` and
  an eroding-ground part set so newly exposed solid faces can enter coupling.
- Peripheral exposed ground: `CTYPE=4` with explicit exposed top segments.
- Buildings, vehicles, subway entrances, and traffic lights: retain independent
  object-level `CTYPE=4` interfaces and DBFSI identities.
- Covered ground faces, ground internal interfaces, side faces, and bottom faces
  must not be present in exposed-ground FSI sets.
- No slave face or part may be assigned to both eroding and non-eroding coupling
  cards.
- No fully translation-constrained segment may remain in a response FSI set.

Ground coupling metadata must identify the exact coupling card, slave entity,
master ALE part set, coupling type, initial exposed segment count, overlap depth,
and overlap layer count.

## 8. Boundary Conditions

- The ALE side and top boundaries retain the existing non-reflecting treatment.
- The former ALE ground reflection SPC is removed in crater mode because the ALE
  mesh now extends below `z = 0`.
- Ground lateral and lower support segment sets use `*BOUNDARY_NON_REFLECTING`.
  They exclude the exposed top surface and all FSI slave faces.
- Rigid-body modes are removed with three support-layer anchor nodes, all outside
  the eroding and observation zones: one node constrains `X/Y/Z`, a second
  non-collinear node constrains `Y/Z`, and a third non-collinear node constrains
  `Z`. No other ground translation SPC is permitted in crater mode.
- Static checks reject an entirely fixed eroding ground part.
- The real-solver regression uses three ordered guard probes on each center-to-
  boundary path. A boundary-to-center peak ordering after the primary outgoing
  wave is classified as a reflected wave. If its central-zone amplitude exceeds
  both five pre-arrival standard deviations and five percent of the primary
  central-zone peak before the crater measurement window ends, acceptance fails
  with `boundary_reflection_contaminated`.

## 9. Solver Outputs

The deck must request all of the following data to reconstruct and verify the
ground response:

- d3plot with solid pressure, stress, displacement, and K&C history variables.
- DBFSI/FSIFOR data separated by ground and city response interfaces.
- ELOUT for fixed K&C probe elements on the source axis at the initial surface,
  mid-overlap depth, and first protected layer below the overlap.
- NODOUT for surviving source-axis surface nodes, crater-edge surface nodes, and
  the ordered lateral/lower boundary-reflection guard probes.
- GLSTAT and MATSUM for global and part-level energy checks.
- Initial eroding-zone element identity and boundary-element identity.

Postprocessing produces:

- `ground_pressure.png`
- `ground_principal_stress.png`
- `ground_kc_damage.png`
- `ground_z_displacement.png`
- `ground_crater_metrics.json`
- `ground_crater_acceptance.json`

The metrics file binds to the run evidence manifest and records initial element
count, deleted element count and ratio, maximum and residual negative-Z
displacement, crater depth, crater diameter, damage range, pressure arrival,
pressure impulse, and whether deleted elements touch a protected boundary.

## 10. Acceptance Gates

### Static generation gates

- ALE lower bound and actual overlap-layer count match normalized metadata.
- TNT and the central refinement window remain inside the ALE domain.
- All ground solid elements have positive initial volume.
- Ground interfaces contain no gaps, duplicate elements, or duplicate FSI faces.
- The central eroding part appears in exactly one `CTYPE=5` card.
- Peripheral ground and every required city response object have their required
  `CTYPE=4` interfaces.
- Building-covered ground faces are absent from exposed-ground FSI.
- The eroding-zone guard distance is at least two local cells.
- Preflight node, element, keyword-size, and estimated-output limits pass.

### Real solver propagation gates

- LS-DYNA terminates normally and d3plot covers at least 99% of target time.
- The ground DBFSI interface has finite pressure rise, positive-pressure impulse,
  force, and more than one positive sample above its pre-arrival baseline.
- Ground structural pressure and principal stress appear no earlier than the FSI
  arrival time and exceed the baseline signal-to-noise gate.
- K&C damage is readable and has a finite positive increment.
- Existing object-level city response gates remain mandatory.

### Crater gates

- At least one central ground element is deleted.
- All deleted elements form one source-localized, face-connected region.
- No deleted element touches the eroding-zone side or bottom boundary.
- At least two intact solid layers remain below the accepted crater.
- Crater depth is at least `0.25*h`.
- Crater diameter spans at least two surface cells.
- Maximum and residual ground displacement contain a finite negative-Z response.
- The crater is not still growing rapidly at the final output states; otherwise
  the run is marked `observation_window_too_short`.

Crater depth is measured from initial `z = 0` to the deepest newly exposed face
of an intact element adjacent to the deleted cluster. Crater diameter is the
larger of the X and Y spans of the deleted top-surface cell footprint. Maximum
and residual negative-Z displacement are evaluated only on surviving nodes that
belonged to the initial exposed ground surface. These definitions are stored in
the metrics file and may not be replaced by a visual estimate from a screenshot.

### Numerical quality gates

- No fatal error, negative-volume termination, NaN, or infinite result.
- Existing total-energy and hourglass-energy gates pass.
- Erosion-related energy changes are reported separately.
- The immutable evidence manifest binds `model.k`, `model.json`, d3plot, d3hsp,
  DBFSI/FSIFOR, ELOUT, NODOUT, GLSTAT, MATSUM, and generated crater metrics.

Normal termination without all propagation, damage, crater, and evidence gates
is not acceptance.

## 11. Sensitivity Requirement

A development run may use one mesh and one overlap depth, but its status remains
`provisional`. Final `validation_crater_passed` requires:

- central mesh sizes `0.20`, `0.15`, and `0.10 m`;
- ALE overlap depths using `5` and `7` local layers;
- no protected-boundary contact in any accepted run;
- consistent response classification across the mesh series; and
- no material drift in TNT, K&C, erosion, ground dimensions, or source position.

The convergence evaluator must classify monotonic, oscillatory, and divergent
sequences. A simple adjacent percentage difference is not sufficient evidence.

## 12. Web and API Design

The Web city editor adds a compact ground-response section with:

- a mode selector: `Fixed ground (legacy)` or `Validation crater`;
- central mesh selector: `0.20`, `0.15`, or `0.10 m`;
- anticipated validation depth input, default `0.6 m`;
- ALE overlap selector: `5` or `7` layers;
- controlled erosion preset selector;
- existing end-time control, default `0.05 s`.

The preview displays the eroding-zone footprint and ALE lower plane as modeling
guides. They are not physical response parts and do not enter result statistics.

Before generation, the UI displays derived overlap depth, eroding-zone
half-width, estimated ground element count, and source-to-foundation clearance.
Invalid configurations disable generation and report the violated bound.

The MCP generation schema exposes the same closed parameter set and rejects
unknown properties, non-finite numbers, unsupported modes, and custom erosion
without strict confirmation.

## 13. Failure States

Use explicit non-success states:

- `invalid_ground_geometry`
- `crater_zone_intersects_foundation`
- `ale_overlap_insufficient`
- `ground_fsi_invalid`
- `solver_failed`
- `ground_propagation_not_proven`
- `damage_not_readable`
- `no_element_erosion`
- `erosion_reached_protected_boundary`
- `boundary_reflection_contaminated`
- `observation_window_too_short`
- `sensitivity_not_completed`
- `invalid_evidence`

No failure state may be converted to success by the presence of a d3plot alone.

## 14. Test Strategy

### Unit tests

- Specification defaults, bounds, strict booleans, and unknown-property rejection.
- Derived overlap depth, zone half-width, and source-movement regeneration.
- Solid mesh counts, positive volumes, shared interfaces, and footprint exclusion.
- Separate CTYPE 4/5 cards and duplicate-coupling rejection.
- K&C/erosion rendering reuse and required output cards.
- Metadata and semantic-object binding.
- Crater metric extraction using synthetic result histories.
- Every failure state and boundary-touch mutation.

### Integration tests

- LS-PrePost import with zero keyword reader errors and a non-empty preview.
- Optional real LS-DYNA smoke producing the complete evidence set.
- A bounded short propagation run before a complete 50 ms run.
- Three-mesh and two-overlap sensitivity aggregation.
- Web generation, invalid-clearance feedback, and legacy-project compatibility.

Real GUI and solver tests remain opt-in through environment variables, but the
capability cannot be marked accepted until their evidence is recorded.

## 15. Implementation Boundaries

The implementation must reuse focused pieces of the Phase 15/K&C workflow:

- material normalization and rendering;
- `NOUT=2` K&C damage output contract;
- controlled erosion presets;
- FSI propagation and arrival checks;
- run snapshot and evidence hashing; and
- sensitivity result classification.

It must not reuse Phase 15 axisymmetric geometry assumptions, borehole surface
sets, or two-dimensional coupling topology. City ground meshing and three-
dimensional object-level FSI remain owned by the city scene modules.
