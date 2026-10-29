# Quarter Two-TNT MM-ALE/SPG Design

## Objective

Generate a solver-oriented LS-DYNA R12 keyword project named
`quarter_two_tnt_ale_spg` through the repository's controlled tooling.  The
model represents two 80 mm TNT cubes separated by a 20 mm vertical air gap.
Only the upper cube is initially detonated.  The upper charge is represented
inside a three-dimensional MM-ALE domain and the lower acceptor charge uses
the Lagrangian Smoothed Particle Galerkin formulation so that sympathetic
initiation is governed by an Ignition-and-Growth reactive EOS.

The generated project must contain `model.k`, `model.json`, and `checks.json`.
`model.k` must carry the repository generator signature and must pass the
repository provenance verifier.  The generator must not start LS-DYNA.

## Approved coordinate system and geometry

All values use `SI_m_s_kg_N_Pa`.

- Global `Y` is vertical.  Global `X` and `Z` are the two horizontal axes.
- Full air-domain dimensions: 0.8 m × 0.8 m × 0.8 m.
- Quarter-model bounds: `X=[0,0.4]`, `Y=[-0.4,0.4]`, `Z=[0,0.4]` m.
- Both complete TNT charges: 0.08 m × 0.08 m × 0.08 m.
- Lower SPG TNT quarter: `X=[0,0.04]`, `Y=[-0.08,0]`, `Z=[0,0.04]` m.
- Physical air gap: `Y=[0,0.02]` m.
- Upper MM-ALE TNT quarter: `X=[0,0.04]`, `Y=[0.02,0.10]`, `Z=[0,0.04]` m.
- Upper initiation point: `(0,0.06,0)` m at `t=0`.
- No initial-detonation card targets the lower TNT.

The uniform ALE cell size and the initial SPG solid mesh size are both exactly
0.004 m.  This gives 100 × 200 × 100 = 2,000,000 ALE cells, 2,050,401 ALE
nodes, 10 × 20 × 10 = 2,000 initial SPG hexahedra, and 2,541 SPG nodes.

At 1,630 kg/m³, each full TNT cube has mass 0.83456 kg and each represented
quarter has mass 0.20864 kg.  These are geometry-derived masses and are
checked rather than independently imposed.

## Numerical formulation

The air and upper explosive use ELFORM 11 and participate in one ALE
multi-material group.  Because all charge faces align exactly with the 4 mm
grid, upper explosive cells may be assigned directly to the explosive ALE
part without cut-cell approximations.  ALE cells geometrically occupied by
the lower Lagrangian/SPG charge use the repository's reviewed low-density ALE
vacuum material, avoiding duplicate physical air mass inside the acceptor.

The lower charge starts from a conforming 4 mm hexahedral discretization and
uses `*SECTION_SOLID_SPG` with ELFORM 47.  `DX=DY=DZ=1.5` are SPG kernel
dilation factors, not particle spacings.  Its remaining approved settings are
`ISPLINE=0`, `KERNEL=1`, `SMSTEP=15`, `MSC=0`, `IDAM=1`, `FS=0.3`,
`STRETCH=1.015`, `ITB=1`, `MSFAC=0`, `ISC=0`, `BOXID=0`, and
`PDAMP=-0.001`.

The lower SPG part is coupled to the ALE host through the supplied
`*CONSTRAINED_LAGRANGE_IN_SOLID_TITLE` layout: `SSTYP=1`, `MSTYP=1`,
`NQUAD=3`, `CTYPE=5`, `DIREC=3`, `MCOUP=0`, `PFAC=0.5`, and
`FRCMIN=0.5`.  The exact target IDs are allocated by the generator and checked
against the emitted part definitions.

The `X=0` and `Z=0` faces are symmetry planes for both the ALE grid and SPG
charge.  The five physical outer faces (`X=0.4`, `Z=0.4`, and both `Y` ends,
with the non-symmetry portions) use non-reflecting ALE boundary treatment.

## Materials

### Upper MM-ALE TNT

Use the user-supplied values without substituting the repository's default TNT:

- `*MAT_HIGH_EXPLOSIVE_BURN_TITLE`: density 1630 kg/m³, detonation velocity
  6930 m/s, `PCJ=2.1E10 Pa`, remaining optional fields zero.
- `*EOS_JWL_TITLE`: `A=3.73770E11 Pa`, `B=3.747100E9 Pa`, `R1=4.15`,
  `R2=0.9`, `OMEGA=0.35`, `E0=6.0E9 J/m³`, `V0=1`.

### Lower SPG TNT

Use the user-supplied mechanical card:

- `*MAT_ELASTIC_PLASTIC_HYDRO_TITLE`: density 1630 kg/m³,
  `G=3.54E9 Pa`, `SIGY=2.0E8 Pa`, and the remaining supplied optional fields
  zero.

The published pressed-TNT Ignition-and-Growth data are mapped to LS-DYNA R12
fields and converted from cm-g-µs-Mbar to SI.  The intended card values are:

| R12 field | SI value |
|---|---:|
| `A`, `B`, `XP1`, `XP2` | `3.712E11`, `3.231E9`, `4.15`, `0.95` |
| `FRER`, `G` | `0.667`, `300` |
| `R1`, `R2`, `R3`, `R5`, `R6` | `1.798E12`, `-9.31E10`, `1874.46`, `6.2`, `3.1` |
| `FMXIG`, `FREQ`, `GROW1`, `EM` | `0.015`, `8.0E8`, `1.12E-4`, `1` |
| `AR1`, `ES1`, `CVP`, `CVR` | `0.667`, `0.667`, `1000`, `2100` |
| `EETAL`, `CCRIT`, `ENQ`, `TMP0` | `6`, `0.065`, `7.0E6`, `298` |
| `GROW2`, `AR2`, `ES2`, `EN` | `8.2E-25`, `0.333`, `0.333`, `3` |
| `FMXGR`, `FMNGR` | `1`, `0` |

Reference parameter table:
<https://maxwellsci.com/print/rjaset/v4-3783-3786.pdf>.  Field placement is
checked against the LS-DYNA R12 keyword definition:
<https://www.dynasupport.com/manuals/ls-dyna-manuals/ls-dyna_manual_volume_ii_r12.pdf>.

## Controls and outputs

- Termination time: `2.0E-4 s` (0.2 ms).
- `d3plot` interval: `2.0E-6 s` (2 µs).
- `GLSTAT`, `MATSUM`, and `ELOUT`: `2.0E-6 s`.
- ALE material output and selected ALE pressure-history solids are included.
- Selected lower-charge solid histories span the interface, center, and
  bottom locations.
- `*DATABASE_EXTENT_BINARY` requests enough solid history variables for the
  I&G burn fraction to be available in binary results.
- The tool generates only; solver execution remains outside the generator.

## Generation and validation architecture

The existing generic `ale_blast_scene` compiler is not suitable: it only
supports a spherical charge and steel plate and constructs all nodes/elements
in memory.  A dedicated MCP tool named
`generate_quarter_two_tnt_ale_spg` will validate the fixed scenario and stream
the approximately two-million-cell deck to disk through a project transaction.
This keeps memory bounded and prevents partially committed projects.

The dedicated validator performs streaming checks for generator signature,
required cards, exact node/element/part counts, unique and bounded IDs,
coordinate bounds, TNT cell/SPG counts and mass, symmetry/non-reflecting sets,
single upper detonation, absence of lower detonation, coupling IDs, approved
material values, and termination/output intervals.  Provenance verification
regenerates a deterministic SHA-256 stream from `model.json` and compares it
with `model.k` without loading the whole deck into memory.

## Acceptance criteria

1. Project environment diagnostics pass with the recorded LS-PrePost 4.12
   executable.
2. The dedicated project tool returns paths to `model.k`, `model.json`, and
   `checks.json`.
3. `checks.json` has `ok: true` and records all geometry, topology, material,
   initiation, coupling, boundary, and output checks.
4. `scripts/verify_generated_k.ps1` returns `ok: true` and
   `classification: generated_by_lsprepost_mcp`.
5. LS-PrePost keyword import validation is attempted.  A preview-export
   failure alone is not treated as model-generation failure; keyword-reader
   errors are treated as failures.
6. No LS-DYNA solver process is started.
