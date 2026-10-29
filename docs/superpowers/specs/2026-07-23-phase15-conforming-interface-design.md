# Phase 15 Conforming ALE/Concrete Interface Design

## Goal

Add a second Phase 15 coupling mode in which the ALE air/TNT domain ends exactly
at the K&C concrete boundary. The interface has no geometric gap and no ALE
elements inside the concrete region. Pressure transfer uses a conforming,
shared-node ALE/Lagrange boundary.

Preserve the existing immersed `*CONSTRAINED_LAGRANGE_IN_SOLID` model as a
legacy compatibility mode.

## Coupling Modes

Phase 15 accepts a controlled `coupling_mode`:

- `conforming_shared_nodes`: new default for newly generated Phase 15 projects.
- `immersed_clis`: existing two-layer ALE overlap and
  `*CONSTRAINED_LAGRANGE_IN_SOLID` behavior.

Existing projects keep their recorded mode. A project without an explicit mode
is interpreted as `immersed_clis` so old model records remain reproducible.

## Conforming Geometry

The conforming mode builds the ALE air/TNT mesh only in the physical fluid
region:

- inside the borehole above and around the charge;
- above the exposed concrete top surface;
- never behind the borehole wall, charge bottom, or concrete top.

The following three interfaces remain explicit and named:

- `charge_bottom`;
- `borehole_wall`;
- `concrete_top`.

At each interface:

- ALE and concrete boundary coordinates must match within a mesh-scaled
  tolerance;
- the merged solver model must use the same node IDs on both sides;
- every interface edge must have exactly one adjacent ALE element and one
  adjacent concrete element;
- no ALE element centroid may lie in the concrete material region;
- no positive gap or area overlap is allowed.

The new mode must not emit the Phase 15
`*CONSTRAINED_LAGRANGE_IN_SOLID` card or its two-sided-overlap requirement.

## Mesh Motion

Shared interface nodes are Lagrangian boundary nodes for the ALE mesh. Interior
ALE nodes use the existing ALE smoothing/control path. Static generation must
reject:

- inverted or zero-area ALE elements;
- incompatible interface subdivisions;
- duplicate coincident nodes that were not merged;
- an interface movement configuration without ALE smoothing support.

The solver-quality report must continue to check negative volume, ALE leakage,
mass change, and abnormal termination. Large interface deformation remains a
known limitation of the conforming mode.

## Keyword and Model Contract

The project model records:

```json
{
  "interfaces": {
    "coupling_mode": "conforming_shared_nodes",
    "interface_surfaces": {},
    "shared_node_count": 0,
    "geometric_gap_max_m": 0.0,
    "ale_concrete_overlap_area_m2": 0.0
  }
}
```

For `immersed_clis`, retain the existing FSI segment sets, overlap metadata, and
CLIS keyword cards unchanged.

For `conforming_shared_nodes`, retain the named interface topology for
diagnostics and response correlation, but do not describe it as a CLIS slave
surface.

## Acceptance Gates

Static acceptance for the conforming mode requires:

1. All three named interface portions are non-empty and connected.
2. ALE and concrete interface coordinates match.
3. Interface node IDs are shared after model assembly.
4. Every interface edge has one fluid-side and one concrete-side element.
5. Maximum geometric gap is within tolerance.
6. ALE/concrete overlap area is zero within tolerance.
7. No ALE element centroid is classified inside concrete.
8. No CLIS card is emitted.

Real LS-DYNA acceptance requires:

1. Normal solver termination with valid run evidence.
2. A non-zero pressure wave in ALE probes before the interface response.
3. Non-zero interface resultant force or equivalent shared-node transfer
   evidence.
4. Concrete hydrostatic pressure and principal-stress responses above the
   configured noise floor.
5. Arrival times ordered from ALE source to interface to concrete probes.
6. K&C scaled damage is readable and finite.
7. Energy, mass, negative-volume, and leakage diagnostics pass.

The old CLIS-only gate `FSI slave segment count > 0` applies only to
`immersed_clis`. It must not be applied to `conforming_shared_nodes`, because
that mode intentionally has no CLIS slave segments.

## Compatibility

- Existing Phase 15 project files and solver runs remain readable.
- Existing public tool calls that omit `coupling_mode` preserve legacy behavior
  when re-reading or regenerating an old project.
- New project creation defaults to `conforming_shared_nodes`.
- The UI and reports show the selected coupling mode and must not combine
  evidence from different modes.
- Runtime outputs and convergence series may compare only runs with the same
  coupling mode.

## Testing

Unit tests cover:

- both mode values and rejection of unknown values;
- legacy keyword stability;
- conforming zero-overlap geometry;
- shared-node topology and edge adjacency;
- omission of CLIS cards in conforming mode;
- mode-specific acceptance gates;
- rejection of mixed-mode convergence evidence.

Integration validation generates separate legacy and conforming projects. The
conforming project must pass an initialization run before a full solve is
allowed. Final acceptance requires a real LS-DYNA run showing ordered pressure
transfer from ALE to the K&C concrete response.

## Non-Goals

- No automatic conversion of existing project directories.
- No claim that uncalibrated K&C parameters predict a specific experiment.
- No removal of the legacy immersed CLIS implementation.
- No acceptance based only on static validation or normal solver termination.
