"""Controlled quarter-symmetry two-TNT MM-ALE/SPG project generator.

The scenario is intentionally narrow.  It records the user-approved SI geometry
and material calibration and never launches LS-DYNA.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Mapping

from .config import DEFAULT_UNIT_SYSTEM, JSONDict


MODEL_TYPE = "quarter_two_tnt_ale_spg"
GENERATOR_ID = "quarter_two_tnt_ale_spg.v1"
_APPROVED: dict[str, float] = {
    "mesh_size_m": 0.004,
    "charge_edge_m": 0.08,
    "gap_m": 0.02,
    "end_time_s": 0.0002,
    "d3plot_dt_s": 0.000002,
}
_ALLOWED_FIELDS = {
    "project_name",
    "model_type",
    "unit_system",
    "domain_min_m",
    "domain_max_m",
    "mesh_size_m",
    "charge_edge_m",
    "gap_m",
    "end_time_s",
    "d3plot_dt_s",
    "detonation_point_m",
    "tnt_density_kg_per_m3",
    "ls_dyna_version",
}


@dataclass(frozen=True)
class QuarterTwoTntSpec:
    project_name: str
    model_type: str
    unit_system: str
    domain_min_m: tuple[float, float, float]
    domain_max_m: tuple[float, float, float]
    mesh_size_m: float
    charge_edge_m: float
    gap_m: float
    end_time_s: float
    d3plot_dt_s: float
    detonation_point_m: tuple[float, float, float]
    tnt_density_kg_per_m3: float
    ls_dyna_version: str
    ale_cells: tuple[int, int, int]
    spg_cells: tuple[int, int, int]
    ale_node_count: int
    ale_element_count: int
    spg_node_count: int
    spg_element_count: int
    upper_ale_element_count: int
    lower_vacuum_element_count: int
    air_element_count: int
    quarter_tnt_mass_kg: float
    full_tnt_mass_kg: float

    def to_json(self) -> JSONDict:
        return {
            "project_name": self.project_name,
            "model_type": self.model_type,
            "unit_system": self.unit_system,
            "domain_min_m": list(self.domain_min_m),
            "domain_max_m": list(self.domain_max_m),
            "mesh_size_m": self.mesh_size_m,
            "charge_edge_m": self.charge_edge_m,
            "gap_m": self.gap_m,
            "end_time_s": self.end_time_s,
            "d3plot_dt_s": self.d3plot_dt_s,
            "detonation_point_m": list(self.detonation_point_m),
            "tnt_density_kg_per_m3": self.tnt_density_kg_per_m3,
            "ls_dyna_version": self.ls_dyna_version,
        }


def default_quarter_two_tnt_spec(
    project_name: str = "quarter_two_tnt_ale_spg",
) -> JSONDict:
    return {
        "project_name": project_name,
        "model_type": MODEL_TYPE,
        "unit_system": DEFAULT_UNIT_SYSTEM,
        "domain_min_m": [0.0, -0.4, 0.0],
        "domain_max_m": [0.4, 0.4, 0.4],
        "mesh_size_m": 0.004,
        "charge_edge_m": 0.08,
        "gap_m": 0.02,
        "end_time_s": 0.0002,
        "d3plot_dt_s": 0.000002,
        "detonation_point_m": [0.0, 0.06, 0.0],
        "tnt_density_kg_per_m3": 1630.0,
        "ls_dyna_version": "R12",
    }


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def _vector3(value: object, field: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{field} must contain exactly three finite numbers")
    return tuple(_finite(item, f"{field}[{index}]") for index, item in enumerate(value))  # type: ignore[return-value]


def _require_exact(raw: Mapping[str, object], field: str) -> float:
    value = _finite(raw.get(field), field)
    expected = _APPROVED[field]
    if not math.isclose(value, expected, rel_tol=0.0, abs_tol=1.0e-12):
        raise ValueError(f"{field} must equal the approved value {expected:.12g}")
    return value


def _grid_count(length: float, step: float, field: str) -> int:
    count = int(round(length / step))
    if count <= 0 or not math.isclose(count * step, length, rel_tol=0.0, abs_tol=1.0e-12):
        raise ValueError(f"{field} must be exactly divisible by mesh_size_m")
    return count


def validate_quarter_two_tnt_spec(raw: Mapping[str, object]) -> QuarterTwoTntSpec:
    if not isinstance(raw, Mapping):
        raise ValueError("spec must be an object")
    unknown = sorted(set(raw) - _ALLOWED_FIELDS)
    if unknown:
        raise ValueError(f"spec contains unknown fields: {', '.join(unknown)}")

    project_name = str(raw.get("project_name", "")).strip()
    if not project_name:
        raise ValueError("project_name must be a non-empty string")
    if raw.get("model_type") != MODEL_TYPE:
        raise ValueError(f"model_type must equal {MODEL_TYPE}")
    if raw.get("unit_system") != DEFAULT_UNIT_SYSTEM:
        raise ValueError(f"unit_system must equal {DEFAULT_UNIT_SYSTEM}")
    if raw.get("ls_dyna_version") != "R12":
        raise ValueError("ls_dyna_version must equal R12")

    domain_min = _vector3(raw.get("domain_min_m"), "domain_min_m")
    domain_max = _vector3(raw.get("domain_max_m"), "domain_max_m")
    if domain_min != (0.0, -0.4, 0.0) or domain_max != (0.4, 0.4, 0.4):
        raise ValueError("domain bounds must equal the approved quarter-domain bounds")

    mesh_size = _require_exact(raw, "mesh_size_m")
    charge_edge = _require_exact(raw, "charge_edge_m")
    gap = _require_exact(raw, "gap_m")
    end_time = _require_exact(raw, "end_time_s")
    d3plot_dt = _require_exact(raw, "d3plot_dt_s")
    detonation = _vector3(raw.get("detonation_point_m"), "detonation_point_m")
    if detonation != (0.0, 0.06, 0.0):
        raise ValueError("detonation_point_m must equal (0, 0.06, 0)")
    density = _finite(raw.get("tnt_density_kg_per_m3"), "tnt_density_kg_per_m3")
    if not math.isclose(density, 1630.0, rel_tol=0.0, abs_tol=1.0e-12):
        raise ValueError("tnt_density_kg_per_m3 must equal 1630")

    ale_cells = tuple(
        _grid_count(high - low, mesh_size, f"domain_{axis}")
        for axis, low, high in zip("xyz", domain_min, domain_max, strict=True)
    )
    half_edge_cells = _grid_count(charge_edge * 0.5, mesh_size, "quarter charge width")
    vertical_charge_cells = _grid_count(charge_edge, mesh_size, "charge height")
    spg_cells = (half_edge_cells, vertical_charge_cells, half_edge_cells)
    ale_element_count = math.prod(ale_cells)
    ale_node_count = math.prod(count + 1 for count in ale_cells)
    spg_element_count = math.prod(spg_cells)
    spg_node_count = math.prod(count + 1 for count in spg_cells)
    full_mass = density * charge_edge**3
    quarter_mass = full_mass / 4.0

    return QuarterTwoTntSpec(
        project_name=project_name,
        model_type=MODEL_TYPE,
        unit_system=DEFAULT_UNIT_SYSTEM,
        domain_min_m=domain_min,
        domain_max_m=domain_max,
        mesh_size_m=mesh_size,
        charge_edge_m=charge_edge,
        gap_m=gap,
        end_time_s=end_time,
        d3plot_dt_s=d3plot_dt,
        detonation_point_m=detonation,
        tnt_density_kg_per_m3=density,
        ls_dyna_version="R12",
        ale_cells=ale_cells,
        spg_cells=spg_cells,
        ale_node_count=ale_node_count,
        ale_element_count=ale_element_count,
        spg_node_count=spg_node_count,
        spg_element_count=spg_element_count,
        upper_ale_element_count=spg_element_count,
        lower_vacuum_element_count=spg_element_count,
        air_element_count=ale_element_count - 2 * spg_element_count,
        quarter_tnt_mass_kg=quarter_mass,
        full_tnt_mass_kg=full_mass,
    )
AIR_PART_ID = 1
UPPER_TNT_PART_ID = 2
VACUUM_PART_ID = 3
LOWER_SPG_PART_ID = 4
ALE_SECTION_ID = 1
SPG_SECTION_ID = 2
AIR_MATERIAL_ID = 1
UPPER_TNT_MATERIAL_ID = 2
VACUUM_MATERIAL_ID = 3
LOWER_TNT_MATERIAL_ID = 4
AIR_EOS_ID = 1
UPPER_TNT_EOS_ID = 2
LOWER_TNT_EOS_ID = 3
ALE_PART_SET_ID = 1001
OUTER_SEGMENT_SET_ID = 1101
X_SYMMETRY_SEGMENT_SET_ID = 1102
Z_SYMMETRY_SEGMENT_SET_ID = 1103
SPG_X_SYMMETRY_NODE_SET_ID = 1201
SPG_Z_SYMMETRY_NODE_SET_ID = 1202
ALE_PROBE_SOLID_SET_ID = 1301
SPG_PROBE_SOLID_SET_ID = 1302


def _fmt(value: float | int) -> str:
    if isinstance(value, int):
        return str(value)
    return format(float(value), ".10g")


def _lines(*values: str):
    for value in values:
        yield value + "\n"


def ale_node_id(spec: QuarterTwoTntSpec, ix: int, iy: int, iz: int) -> int:
    nx, ny, nz = spec.ale_cells
    if not (0 <= ix <= nx and 0 <= iy <= ny and 0 <= iz <= nz):
        raise ValueError("ALE node index is outside the structured domain")
    return iz * (ny + 1) * (nx + 1) + iy * (nx + 1) + ix + 1


def ale_element_id(spec: QuarterTwoTntSpec, ix: int, iy: int, iz: int) -> int:
    nx, ny, nz = spec.ale_cells
    if not (0 <= ix < nx and 0 <= iy < ny and 0 <= iz < nz):
        raise ValueError("ALE element index is outside the structured domain")
    return iz * ny * nx + iy * nx + ix + 1


def ale_element_nodes(spec: QuarterTwoTntSpec, ix: int, iy: int, iz: int) -> tuple[int, ...]:
    return (
        ale_node_id(spec, ix, iy, iz),
        ale_node_id(spec, ix + 1, iy, iz),
        ale_node_id(spec, ix + 1, iy + 1, iz),
        ale_node_id(spec, ix, iy + 1, iz),
        ale_node_id(spec, ix, iy, iz + 1),
        ale_node_id(spec, ix + 1, iy, iz + 1),
        ale_node_id(spec, ix + 1, iy + 1, iz + 1),
        ale_node_id(spec, ix, iy + 1, iz + 1),
    )


def spg_node_id(spec: QuarterTwoTntSpec, ix: int, iy: int, iz: int) -> int:
    nx, ny, nz = spec.spg_cells
    if not (0 <= ix <= nx and 0 <= iy <= ny and 0 <= iz <= nz):
        raise ValueError("SPG node index is outside the structured charge")
    local = iz * (ny + 1) * (nx + 1) + iy * (nx + 1) + ix + 1
    return spec.ale_node_count + local


def spg_element_id(spec: QuarterTwoTntSpec, ix: int, iy: int, iz: int) -> int:
    nx, ny, nz = spec.spg_cells
    if not (0 <= ix < nx and 0 <= iy < ny and 0 <= iz < nz):
        raise ValueError("SPG element index is outside the structured charge")
    local = iz * ny * nx + iy * nx + ix + 1
    return spec.ale_element_count + local


def spg_element_nodes(spec: QuarterTwoTntSpec, ix: int, iy: int, iz: int) -> tuple[int, ...]:
    return (
        spg_node_id(spec, ix, iy, iz),
        spg_node_id(spec, ix + 1, iy, iz),
        spg_node_id(spec, ix + 1, iy + 1, iz),
        spg_node_id(spec, ix, iy + 1, iz),
        spg_node_id(spec, ix, iy, iz + 1),
        spg_node_id(spec, ix + 1, iy, iz + 1),
        spg_node_id(spec, ix + 1, iy + 1, iz + 1),
        spg_node_id(spec, ix, iy + 1, iz + 1),
    )


def iter_x_symmetry_segments(spec: QuarterTwoTntSpec):
    _, ny, nz = spec.ale_cells
    for iz in range(nz):
        for iy in range(ny):
            yield (
                ale_node_id(spec, 0, iy, iz),
                ale_node_id(spec, 0, iy, iz + 1),
                ale_node_id(spec, 0, iy + 1, iz + 1),
                ale_node_id(spec, 0, iy + 1, iz),
            )


def iter_z_symmetry_segments(spec: QuarterTwoTntSpec):
    nx, ny, _ = spec.ale_cells
    for iy in range(ny):
        for ix in range(nx):
            yield (
                ale_node_id(spec, ix, iy, 0),
                ale_node_id(spec, ix, iy + 1, 0),
                ale_node_id(spec, ix + 1, iy + 1, 0),
                ale_node_id(spec, ix + 1, iy, 0),
            )


def iter_outer_boundary_segments(spec: QuarterTwoTntSpec):
    nx, ny, nz = spec.ale_cells
    for iz in range(nz):
        for iy in range(ny):
            yield (
                ale_node_id(spec, nx, iy, iz),
                ale_node_id(spec, nx, iy + 1, iz),
                ale_node_id(spec, nx, iy + 1, iz + 1),
                ale_node_id(spec, nx, iy, iz + 1),
            )
    for iz in range(nz):
        for ix in range(nx):
            yield (
                ale_node_id(spec, ix, 0, iz),
                ale_node_id(spec, ix + 1, 0, iz),
                ale_node_id(spec, ix + 1, 0, iz + 1),
                ale_node_id(spec, ix, 0, iz + 1),
            )
            yield (
                ale_node_id(spec, ix, ny, iz),
                ale_node_id(spec, ix, ny, iz + 1),
                ale_node_id(spec, ix + 1, ny, iz + 1),
                ale_node_id(spec, ix + 1, ny, iz),
            )
    for iy in range(ny):
        for ix in range(nx):
            yield (
                ale_node_id(spec, ix, iy, nz),
                ale_node_id(spec, ix + 1, iy, nz),
                ale_node_id(spec, ix + 1, iy + 1, nz),
                ale_node_id(spec, ix, iy + 1, nz),
            )


def iter_keyword_preamble(spec: QuarterTwoTntSpec):
    yield from _lines(
        "*KEYWORD",
        "*TITLE",
        f"lsprepost-mcp {MODEL_TYPE}: {spec.project_name}",
        "$",
        "$ Unit system: SI_m_s_kg_N_Pa (m, s, kg, N, Pa)",
        "$ LS-DYNA target: R12",
        "$ Generated by lsprepost_mcp",
        f"$ Generator: {GENERATOR_ID}",
        "$",
        "*CONTROL_TERMINATION",
        "$#    endtim    endcyc     dtmin    endeng    endmas",
        f"{_fmt(spec.end_time_s)},0,0,0,0",
        "*CONTROL_TIMESTEP",
        "$#    dtinit    tssfac      isdo     tslimt     dt2ms      lctm",
        "0,0.67,0,0,0,0",
        "*CONTROL_ENERGY",
        "$#      hgen      rwen    slnten     rylen",
        "2,2,2,2",
        "*CONTROL_ALE",
        "$#       dct      nadv      meth      afac      bfac      cfac      dfac      efac",
        "-1,1,2,-1,0,0,0,0",
        "$#     start       end     aafac     vfact    vlimit       ebc      pref   nsidebc",
        "0,1e+20,1,1e-06,0,0,101325,0",
        "*DATABASE_FORMAT",
        "0,1",
        "*DATABASE_BINARY_D3PLOT",
        "$#      dt",
        _fmt(spec.d3plot_dt_s),
        "*DATABASE_GLSTAT",
        _fmt(spec.d3plot_dt_s),
        "*DATABASE_MATSUM",
        _fmt(spec.d3plot_dt_s),
        "*DATABASE_ELOUT",
        _fmt(spec.d3plot_dt_s),
        "*DATABASE_ALE_MAT",
        f"{_fmt(spec.d3plot_dt_s)},0",
        "*DATABASE_EXTENT_BINARY",
        "12,3,4,1,1,1,1,1",
        "0,0,0,0,0,0,2,1",
        "1,0,1,0,0",
        "*DATABASE_HISTORY_SOLID_SET",
        str(ALE_PROBE_SOLID_SET_ID),
        "*DATABASE_HISTORY_SOLID_SET",
        str(SPG_PROBE_SOLID_SET_ID),
    )


def _iter_id_rows(values, width: int = 8):
    row: list[str] = []
    for value in values:
        row.append(str(value))
        if len(row) == width:
            yield ",".join(row) + "\n"
            row.clear()
    if row:
        yield ",".join(row) + "\n"


def _iter_segment_set(set_id: int, title: str, segments):
    yield from _lines("*SET_SEGMENT_TITLE", title, f"{set_id},0,0,0,0")
    for segment in segments:
        yield ",".join(str(node_id) for node_id in segment) + "\n"


def iter_keyword_tail(spec: QuarterTwoTntSpec):
    yield from _lines(
        "*PART",
        "ALE host air",
        "1,1,1,1,0,0,0,0",
        "*PART",
        "Upper TNT MM-ALE material group",
        "2,1,2,2,0,0,0,0",
        "*PART",
        "Lower-charge ALE vacuum fill",
        "3,1,3,0,0,0,0,0",
        "*PART",
        "Lower TNT SPG acceptor",
        "4,2,4,3,0,0,0,0",
        "*SECTION_SOLID",
        "$#     secid    elform       aet    unused    unused    unused    cohoff    unused",
        "1,11,0,0,0,0,0,0",
        "*SECTION_SOLID_SPG",
        "$#     secid    elform       aet    unused    unused    unused    cohoff   gaskeit",
        "2,47,0,0,0,0,0,0",
        "$#        dx        dy        dz   ispline    kernel    unused    smstep       msc",
        "1.5,1.5,1.5,0,1,0,15,0",
        "$#      idam        fs   stretch       itb     msfac       isc     boxid     pdamp",
        "1,0.3,1.015,1,0,0,0,-0.001",
        "*MAT_NULL_TITLE",
        "Air at 298 K",
        "1,1.225,0,0,0,0,0,0",
        "*EOS_LINEAR_POLYNOMIAL_TITLE",
        "Air ideal-gas linear polynomial form",
        "1,0,0,0,0,0.4,0.4,0",
        "253312.5,1",
        "*MAT_HIGH_EXPLOSIVE_BURN_TITLE",
        "Upper TNT supplied MM-ALE calibration",
        "2,1630,6930,2.1e+10,0,0,0,0",
        "*EOS_JWL_TITLE",
        "Upper TNT supplied JWL calibration",
        "2,3.7377e+11,3.7471e+09,4.15,0.9,0.35,6e+09,1",
        "*MAT_ALE_VACUUM_TITLE",
        "Vacuum occupying the lower SPG charge volume",
        "3,1.225e-05",
        "*MAT_ELASTIC_PLASTIC_HYDRO_TITLE",
        "Lower TNT for Ignition and Growth",
        "4,1630,3.54e+09,2e+08,0,0,0,0",
        "0,0,0,0,0,0,0,0",
        "0,0,0,0,0,0,0,0",
        "*EOS_IGNITION_AND_GROWTH_OF_REACTION_IN_HE",
        "3,3.712e+11,3.231e+09,4.15,0.95,0.667,300,1.798e+12",
        "-9.31e+10,1874.46,6.2,3.1,0.015,8e+08,0.000112,1",
        "0.667,0.667,1000,2100,6,0.065,7000000,298",
        "8.2e-25,0.333,0.333,3,1,0",
        "*ALE_MULTI-MATERIAL_GROUP",
        "1,1",
        "2,1",
        "3,1",
        "*INITIAL_VOLUME_FRACTION_GEOMETRY",
        "$#     fmsid   fmidtyp     bammg    ntrace",
        "1,1,1,0",
        "$#   conttyp   fillopt     fammg",
        "5,0,2",
        "$#        x0        y0        z0        x1        y1        z1     lcsid",
        "0,0.02,0,0.04,0.1,0.04,0",
        "5,0,3",
        "0,-0.08,0,0.04,0,0.04,0",
        "*INITIAL_DETONATION",
        "$#       pid        x0        y0        z0        lt",
        "1,0,0.06,0,0",
        "*CONSTRAINED_LAGRANGE_IN_SOLID_TITLE",
        "         1LOWER SPG TNT TO MM-ALE",
        "$#     slave    master     sstyp     mstyp     nquad     ctype     direc     mcoup",
        "4,1,1,1,3,5,3,0",
        "$#     start       end      pfac      fric    frcmin      norm   normtyp      damp",
        "0,100,0.5,0,0.5,0,0,0",
        "$#        cq      hmin      hmax     ileak     pleak   lcidpor     nvent  blockage",
        "0,0,0,0,0.2,0,0,0",
        "$#    iboxid   ipenchk   intforc   ialesof    lagmul    pfacmm      thkf",
        "0,0,0,0,0,0,0",
        "*SET_PART_LIST_TITLE",
        "MM-ALE material parts",
        str(ALE_PART_SET_ID),
        "1,2,3",
        "*SET_SOLID_LIST_TITLE",
        "ALE pressure probes across gap and upper charge",
        str(ALE_PROBE_SOLID_SET_ID),
    )
    nx, _, _ = spec.ale_cells
    ale_probe_ids = (
        ale_element_id(spec, 0, 104, 0),
        ale_element_id(spec, 0, 105, 0),
        ale_element_id(spec, 0, 114, 0),
        ale_element_id(spec, 0, 115, 0),
        ale_element_id(spec, 0, 125, 0),
    )
    yield from _iter_id_rows(ale_probe_ids)
    yield from _lines(
        "*SET_SOLID_LIST_TITLE",
        "Lower SPG burn-fraction and pressure probes",
        str(SPG_PROBE_SOLID_SET_ID),
    )
    yield from _iter_id_rows(
        (
            spg_element_id(spec, 0, 0, 0),
            spg_element_id(spec, 0, 9, 0),
            spg_element_id(spec, 0, 19, 0),
        )
    )
    yield from _iter_segment_set(
        X_SYMMETRY_SEGMENT_SET_ID,
        "X=0 quarter-symmetry ALE face",
        iter_x_symmetry_segments(spec),
    )
    yield from _iter_segment_set(
        Z_SYMMETRY_SEGMENT_SET_ID,
        "Z=0 quarter-symmetry ALE face",
        iter_z_symmetry_segments(spec),
    )
    yield from _iter_segment_set(
        OUTER_SEGMENT_SET_ID,
        "Five physical MM-ALE outer non-reflecting faces",
        iter_outer_boundary_segments(spec),
    )
    yield from _lines(
        "*ALE_ESSENTIAL_BOUNDARY",
        "$#        id    idtype    ictype     iexcl",
        f"{X_SYMMETRY_SEGMENT_SET_ID},2,2,0",
        "*ALE_ESSENTIAL_BOUNDARY",
        f"{Z_SYMMETRY_SEGMENT_SET_ID},2,2,0",
        "*BOUNDARY_NON_REFLECTING",
        "$#      ssid        ad        as",
        f"{OUTER_SEGMENT_SET_ID},0,0",
        "*SET_NODE_LIST_TITLE",
        "Lower SPG X=0 symmetry nodes",
        str(SPG_X_SYMMETRY_NODE_SET_ID),
    )
    sx, sy, sz = spec.spg_cells
    yield from _iter_id_rows(spg_node_id(spec, 0, iy, iz) for iz in range(sz + 1) for iy in range(sy + 1))
    yield from _lines(
        "*BOUNDARY_SPC_SET",
        f"{SPG_X_SYMMETRY_NODE_SET_ID},0,1,0,0,0,0,0",
        "*SET_NODE_LIST_TITLE",
        "Lower SPG Z=0 symmetry nodes",
        str(SPG_Z_SYMMETRY_NODE_SET_ID),
    )
    yield from _iter_id_rows(spg_node_id(spec, ix, iy, 0) for iy in range(sy + 1) for ix in range(sx + 1))
    yield from _lines(
        "*BOUNDARY_SPC_SET",
        f"{SPG_Z_SYMMETRY_NODE_SET_ID},0,0,0,1,0,0,0",
        "*END",
    )


def iter_quarter_two_tnt_keyword(spec: QuarterTwoTntSpec):
    yield from iter_keyword_preamble(spec)
    yield from _lines("*NODE", "$#       nid                 x                 y                 z")
    nx, ny, nz = spec.ale_cells
    dx = spec.mesh_size_m
    for iz in range(nz + 1):
        z = spec.domain_min_m[2] + iz * dx
        for iy in range(ny + 1):
            y = spec.domain_min_m[1] + iy * dx
            for ix in range(nx + 1):
                x = spec.domain_min_m[0] + ix * dx
                yield f"{ale_node_id(spec, ix, iy, iz)},{_fmt(x)},{_fmt(y)},{_fmt(z)}\n"
    sx, sy, sz = spec.spg_cells
    for iz in range(sz + 1):
        z = iz * dx
        for iy in range(sy + 1):
            y = -spec.charge_edge_m + iy * dx
            for ix in range(sx + 1):
                x = ix * dx
                yield f"{spg_node_id(spec, ix, iy, iz)},{_fmt(x)},{_fmt(y)},{_fmt(z)}\n"
    yield from _lines("*ELEMENT_SOLID", "$#       eid       pid        n1        n2        n3        n4        n5        n6        n7        n8")
    for iz in range(nz):
        for iy in range(ny):
            for ix in range(nx):
                nodes = ale_element_nodes(spec, ix, iy, iz)
                yield f"{ale_element_id(spec, ix, iy, iz)},1," + ",".join(str(value) for value in nodes) + "\n"
    for iz in range(sz):
        for iy in range(sy):
            for ix in range(sx):
                nodes = spg_element_nodes(spec, ix, iy, iz)
                yield f"{spg_element_id(spec, ix, iy, iz)},4," + ",".join(str(value) for value in nodes) + "\n"
    yield from iter_keyword_tail(spec)


def keyword_sha256(spec: QuarterTwoTntSpec) -> str:
    digest = hashlib.sha256()
    for line in iter_quarter_two_tnt_keyword(spec):
        digest.update(line.encode("utf-8"))
    return digest.hexdigest()

def validate_quarter_two_tnt_keyword_file(
    keyword_path,
    spec: QuarterTwoTntSpec,
    *,
    expected_sha256: str | None = None,
) -> JSONDict:
    """Validate the large deck in one bounded-memory pass."""

    from collections import Counter
    from pathlib import Path

    path = Path(keyword_path)
    errors: list[str] = []
    warnings: list[str] = []
    items: list[JSONDict] = []

    def add(
        check_id: str,
        ok: bool,
        message: str,
        *,
        expected: object | None = None,
        actual: object | None = None,
    ) -> None:
        item: JSONDict = {
            "id": check_id,
            "ok": bool(ok),
            "severity": "info" if ok else "error",
            "message": message,
        }
        if expected is not None:
            item["expected"] = expected
        if actual is not None:
            item["actual"] = actual
        items.append(item)
        if not ok:
            errors.append(message)

    if not path.is_file():
        add("file.model_k", False, f"model.k is missing: {path}")
        return {
            "ok": False,
            "errors": errors,
            "warnings": warnings,
            "items": items,
            "keyword_path": str(path),
            "summary": {},
        }

    keyword_counts: Counter[str] = Counter()
    element_counts: Counter[int] = Counter()
    static_rows: dict[str, list[str]] = {}
    retained_cards = {
        "*CONTROL_TERMINATION",
        "*DATABASE_BINARY_D3PLOT",
        "*SECTION_SOLID_SPG",
        "*MAT_HIGH_EXPLOSIVE_BURN_TITLE",
        "*EOS_JWL_TITLE",
        "*MAT_ELASTIC_PLASTIC_HYDRO_TITLE",
        "*EOS_IGNITION_AND_GROWTH_OF_REACTION_IN_HE",
        "*ALE_MULTI-MATERIAL_GROUP",
        "*INITIAL_VOLUME_FRACTION_GEOMETRY",
        "*INITIAL_DETONATION",
        "*CONSTRAINED_LAGRANGE_IN_SOLID_TITLE",
        "*ALE_ESSENTIAL_BOUNDARY",
        "*BOUNDARY_NON_REFLECTING",
        "*BOUNDARY_SPC_SET",
    }
    digest = hashlib.sha256()
    active = ""
    node_count = 0
    element_count = 0
    first_node_id: int | None = None
    last_node_id: int | None = None
    first_element_id: int | None = None
    last_element_id: int | None = None
    detonation_rows: list[list[str]] = []
    signature_found = False
    parse_errors: list[str] = []

    with path.open("rb") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            digest.update(raw_line)
            try:
                line = raw_line.decode("utf-8")
            except UnicodeDecodeError as exc:
                parse_errors.append(f"line {line_number}: invalid UTF-8 ({exc})")
                continue
            stripped = line.strip()
            if GENERATOR_ID in stripped and "Generated by lsprepost_mcp" in stripped:
                signature_found = True
            elif stripped == "$ Generated by lsprepost_mcp":
                signature_found = True
            if not stripped or stripped.startswith("$"):
                continue
            if stripped.startswith("*"):
                active = stripped.upper()
                keyword_counts[active] += 1
                continue

            if active == "*NODE":
                try:
                    node_id = int(stripped.split(",", 1)[0].strip())
                except ValueError:
                    if len(parse_errors) < 20:
                        parse_errors.append(f"line {line_number}: invalid node row")
                    continue
                node_count += 1
                first_node_id = node_id if first_node_id is None else first_node_id
                last_node_id = node_id
            elif active == "*ELEMENT_SOLID":
                fields = [field.strip() for field in stripped.split(",")]
                try:
                    element_id = int(fields[0])
                    part_id = int(fields[1])
                except (IndexError, ValueError):
                    if len(parse_errors) < 20:
                        parse_errors.append(f"line {line_number}: invalid solid element row")
                    continue
                element_count += 1
                element_counts[part_id] += 1
                first_element_id = element_id if first_element_id is None else first_element_id
                last_element_id = element_id
            elif active == "*INITIAL_DETONATION":
                fields = [field.strip() for field in stripped.split(",")]
                detonation_rows.append(fields)

            if active in retained_cards:
                rows = static_rows.setdefault(active, [])
                if len(rows) < 32:
                    rows.append(stripped)

    actual_sha256 = digest.hexdigest()
    required_cards = {
        "*KEYWORD",
        "*NODE",
        "*ELEMENT_SOLID",
        "*PART",
        "*SECTION_SOLID",
        "*SECTION_SOLID_SPG",
        "*MAT_NULL_TITLE",
        "*EOS_LINEAR_POLYNOMIAL_TITLE",
        "*MAT_HIGH_EXPLOSIVE_BURN_TITLE",
        "*EOS_JWL_TITLE",
        "*MAT_ALE_VACUUM_TITLE",
        "*MAT_ELASTIC_PLASTIC_HYDRO_TITLE",
        "*EOS_IGNITION_AND_GROWTH_OF_REACTION_IN_HE",
        "*ALE_MULTI-MATERIAL_GROUP",
        "*INITIAL_VOLUME_FRACTION_GEOMETRY",
        "*INITIAL_DETONATION",
        "*CONSTRAINED_LAGRANGE_IN_SOLID_TITLE",
        "*ALE_ESSENTIAL_BOUNDARY",
        "*BOUNDARY_NON_REFLECTING",
        "*BOUNDARY_SPC_SET",
        "*END",
    }
    missing = sorted(card for card in required_cards if keyword_counts[card] == 0)
    add(
        "keyword.required_cards",
        not missing,
        "all required MM-ALE/SPG cards are present" if not missing else f"missing required cards: {', '.join(missing)}",
        expected=sorted(required_cards),
        actual=sorted(card for card in required_cards if keyword_counts[card]),
    )
    add(
        "keyword.generator_signature",
        signature_found,
        "generator signature is present" if signature_found else "generator signature is missing",
        expected="$ Generated by lsprepost_mcp",
        actual=signature_found,
    )
    add(
        "keyword.parse",
        not parse_errors,
        "node and element rows parsed successfully" if not parse_errors else "; ".join(parse_errors),
        actual=parse_errors,
    )

    expected_nodes = spec.ale_node_count + spec.spg_node_count
    expected_elements = spec.ale_element_count + spec.spg_element_count
    add("count.nodes", node_count == expected_nodes, "node count matches the approved topology", expected=expected_nodes, actual=node_count)
    add("count.elements", element_count == expected_elements, "solid element count matches the approved topology", expected=expected_elements, actual=element_count)
    add("count.ale_elements", element_counts[AIR_PART_ID] == spec.ale_element_count, "all ALE host elements use the air host part", expected=spec.ale_element_count, actual=element_counts[AIR_PART_ID])
    add("count.spg_elements", element_counts[LOWER_SPG_PART_ID] == spec.spg_element_count, "all lower TNT elements use the SPG part", expected=spec.spg_element_count, actual=element_counts[LOWER_SPG_PART_ID])
    unexpected_parts = {pid: count for pid, count in element_counts.items() if pid not in {AIR_PART_ID, LOWER_SPG_PART_ID}}
    add("element.parts", not unexpected_parts, "no unexpected element part IDs are present", expected={}, actual=unexpected_parts)
    add("node.id_range", first_node_id == 1 and last_node_id == expected_nodes, "node IDs span the deterministic range", expected=[1, expected_nodes], actual=[first_node_id, last_node_id])
    add("element.id_range", first_element_id == 1 and last_element_id == expected_elements, "element IDs span the deterministic range", expected=[1, expected_elements], actual=[first_element_id, last_element_id])

    detonation_ok = False
    if len(detonation_rows) == 1 and len(detonation_rows[0]) >= 5:
        row = detonation_rows[0]
        try:
            detonation_ok = (
                int(row[0]) == AIR_PART_ID
                and math.isclose(float(row[1]), spec.detonation_point_m[0], abs_tol=1.0e-12)
                and math.isclose(float(row[2]), spec.detonation_point_m[1], abs_tol=1.0e-12)
                and math.isclose(float(row[3]), spec.detonation_point_m[2], abs_tol=1.0e-12)
                and math.isclose(float(row[4]), 0.0, abs_tol=1.0e-12)
            )
        except ValueError:
            detonation_ok = False
    add(
        "detonation.upper_only",
        detonation_ok,
        "exactly one upper-charge detonation is defined" if detonation_ok else "detonation must target only the upper MM-ALE charge at (0, 0.06, 0), t=0",
        expected=[AIR_PART_ID, 0.0, 0.06, 0.0, 0.0],
        actual=detonation_rows,
    )

    joined_static = "\n".join(row for rows in static_rows.values() for row in rows)
    required_records = [
        "2,1630,6930,2.1e+10,0,0,0,0",
        "2,3.7377e+11,3.7471e+09,4.15,0.9,0.35,6e+09,1",
        "4,1630,3.54e+09,2e+08,0,0,0,0",
        "3,3.712e+11,3.231e+09,4.15,0.95,0.667,300,1.798e+12",
        "-9.31e+10,1874.46,6.2,3.1,0.015,8e+08,0.000112,1",
        "0.667,0.667,1000,2100,6,0.065,7000000,298",
        "8.2e-25,0.333,0.333,3,1,0",
        "1.5,1.5,1.5,0,1,0,15,0",
        "1,0.3,1.015,1,0,0,0,-0.001",
        "0,0.02,0,0.04,0.1,0.04,0",
        "0,-0.08,0,0.04,0,0.04,0",
        "4,1,1,1,3,5,3,0",
        "0,100,0.5,0,0.5,0,0,0",
        "0,0,0,0,0.2,0,0,0",
    ]
    missing_records = [record for record in required_records if record not in joined_static]
    add(
        "parameters.approved_records",
        not missing_records,
        "approved material, SPG, fill, and coupling records are present" if not missing_records else f"approved records missing: {missing_records}",
        expected=required_records,
        actual=missing_records,
    )
    add(
        "boundary.symmetry",
        keyword_counts["*ALE_ESSENTIAL_BOUNDARY"] == 2 and keyword_counts["*BOUNDARY_SPC_SET"] == 2,
        "quarter-symmetry constraints are present for ALE and SPG",
        expected={"ale": 2, "spg": 2},
        actual={"ale": keyword_counts["*ALE_ESSENTIAL_BOUNDARY"], "spg": keyword_counts["*BOUNDARY_SPC_SET"]},
    )
    add(
        "boundary.non_reflecting",
        keyword_counts["*BOUNDARY_NON_REFLECTING"] == 1,
        "one non-reflecting outer boundary definition is present",
        expected=1,
        actual=keyword_counts["*BOUNDARY_NON_REFLECTING"],
    )
    if expected_sha256 is not None:
        add(
            "keyword.sha256",
            actual_sha256 == expected_sha256,
            "keyword SHA-256 matches the generated stream" if actual_sha256 == expected_sha256 else "keyword SHA-256 differs from the generated stream",
            expected=expected_sha256,
            actual=actual_sha256,
        )

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "items": items,
        "keyword_path": str(path),
        "summary": {
            "project_name": spec.project_name,
            "model_type": spec.model_type,
            "node_count": node_count,
            "element_count": element_count,
            "ale_node_count": spec.ale_node_count,
            "spg_node_count": spec.spg_node_count,
            "ale_element_count": element_counts[AIR_PART_ID],
            "spg_element_count": element_counts[LOWER_SPG_PART_ID],
            "detonation_count": len(detonation_rows),
            "keyword_sha256": actual_sha256,
            "keyword_counts": dict(sorted(keyword_counts.items())),
        },
        "readiness": {
            "ok_for_gui_preview": not errors,
            "ok_for_solver_draft": not errors,
            "ok_for_production_review": False,
            "note": "Static checks only; engineering review and solver verification remain required.",
        },
        "validation_scope": {
            "ok_meaning": "streaming static checks passed; this is not an LS-DYNA solution certificate",
        },
    }


def _derived_summary(spec: QuarterTwoTntSpec) -> JSONDict:
    return {
        "ale_cells": list(spec.ale_cells),
        "ale_node_count": spec.ale_node_count,
        "ale_element_count": spec.ale_element_count,
        "spg_cells": list(spec.spg_cells),
        "spg_node_count": spec.spg_node_count,
        "spg_element_count": spec.spg_element_count,
        "air_element_count": spec.air_element_count,
        "upper_volume_cell_count": spec.upper_ale_element_count,
        "lower_vacuum_cell_count": spec.lower_vacuum_element_count,
        "quarter_tnt_mass_kg": spec.quarter_tnt_mass_kg,
        "full_tnt_mass_kg": spec.full_tnt_mass_kg,
    }


def quarter_two_tnt_input_schema() -> JSONDict:
    return {
        "type": "object",
        "properties": {
            "project_name": {
                "type": "string",
                "default": "quarter_two_tnt_ale_spg",
            },
            "unit_system": {"const": DEFAULT_UNIT_SYSTEM, "default": DEFAULT_UNIT_SYSTEM},
            "domain_min_m": {
                "const": [0.0, -0.4, 0.0],
                "default": [0.0, -0.4, 0.0],
            },
            "domain_max_m": {
                "const": [0.4, 0.4, 0.4],
                "default": [0.4, 0.4, 0.4],
            },
            "mesh_size_m": {"const": 0.004, "default": 0.004},
            "charge_edge_m": {"const": 0.08, "default": 0.08},
            "gap_m": {"const": 0.02, "default": 0.02},
            "end_time_s": {"const": 0.0002, "default": 0.0002},
            "d3plot_dt_s": {"const": 0.000002, "default": 0.000002},
            "detonation_point_m": {
                "const": [0.0, 0.06, 0.0],
                "default": [0.0, 0.06, 0.0],
            },
            "tnt_density_kg_per_m3": {"const": 1630.0, "default": 1630.0},
            "ls_dyna_version": {"const": "R12", "default": "R12"},
            "dry_run": {"type": "boolean", "default": False},
            "if_exists": {
                "type": "string",
                "enum": ["error", "overwrite", "archive_then_write", "versioned"],
                "default": "error",
            },
        },
        "additionalProperties": False,
    }


def _project_metadata(spec: QuarterTwoTntSpec, keyword_digest: str) -> JSONDict:
    return {
        "model_type": spec.model_type,
        "generator_id": GENERATOR_ID,
        "keyword_sha256": keyword_digest,
        "unit_system": spec.unit_system,
        "ls_dyna_version": spec.ls_dyna_version,
        "element_family": "solid",
        "node_count": spec.ale_node_count + spec.spg_node_count,
        "element_count": spec.ale_element_count + spec.spg_element_count,
        "part_count": 4,
        "material_count": 4,
        "section_count": 2,
        "constraint_count": 4,
        "node_set_count": 2,
        "part_set_count": 1,
        "segment_set_count": 3,
        "initial_condition_count": 3,
        "derived": _derived_summary(spec),
        "approved_parameters": {
            "upper_tnt": {
                "rho": 1630.0,
                "d": 6930.0,
                "pcj": 2.1e10,
                "jwl": [3.7377e11, 3.7471e9, 4.15, 0.9, 0.35, 6.0e9, 1.0],
            },
            "lower_tnt": {
                "rho": 1630.0,
                "shear_modulus_pa": 3.54e9,
                "yield_stress_pa": 2.0e8,
                "ignition_and_growth": [
                    [3.712e11, 3.231e9, 4.15, 0.95, 0.667, 300.0, 1.798e12],
                    [-9.31e10, 1874.46, 6.2, 3.1, 0.015, 8.0e8, 1.12e-4, 1.0],
                    [0.667, 0.667, 1000.0, 2100.0, 6.0, 0.065, 7.0e6, 298.0],
                    [8.2e-25, 0.333, 0.333, 3.0, 1.0, 0.0],
                ],
            },
        },
        "limitations": [
            "Static generation and import checks do not replace engineering review.",
            "No LS-DYNA solver run is started by this tool.",
        ],
    }


def validate_quarter_two_tnt_project(path) -> JSONDict:
    from pathlib import Path

    from .io import read_json

    project_path = Path(path)
    model_path = project_path / "model.json"
    keyword_path = project_path / "model.k"
    cfile_path = project_path / "open_model.cfile"
    if not model_path.is_file():
        return {
            "ok": False,
            "errors": [f"model.json is missing: {model_path}"],
            "warnings": [],
            "items": [
                {
                    "id": "file.model_json",
                    "ok": False,
                    "severity": "error",
                    "message": f"model.json is missing: {model_path}",
                }
            ],
            "project_name": project_path.name,
            "keyword_path": str(keyword_path),
            "spec_path": str(model_path),
            "summary": {},
        }
    try:
        model = read_json(model_path)
        raw_spec = model.get("spec", {})
        metadata = model.get("metadata", {})
        spec = validate_quarter_two_tnt_spec(raw_spec)
    except Exception as exc:
        return {
            "ok": False,
            "errors": [f"model.json does not contain a valid quarter-two-TNT spec: {exc}"],
            "warnings": [],
            "items": [
                {
                    "id": "file.model_json",
                    "ok": False,
                    "severity": "error",
                    "message": f"model.json does not contain a valid quarter-two-TNT spec: {exc}",
                }
            ],
            "project_name": project_path.name,
            "keyword_path": str(keyword_path),
            "spec_path": str(model_path),
            "summary": {},
        }

    expected_hash = str(metadata.get("keyword_sha256", "")) if isinstance(metadata, dict) else ""
    checks = validate_quarter_two_tnt_keyword_file(
        keyword_path,
        spec,
        expected_sha256=expected_hash or None,
    )
    file_items = [
        {
            "id": "file.model_json",
            "ok": True,
            "severity": "info",
            "message": "model.json exists and contains the approved scenario spec",
        },
        {
            "id": "file.open_model_cfile",
            "ok": cfile_path.is_file(),
            "severity": "info" if cfile_path.is_file() else "error",
            "message": "open_model.cfile exists" if cfile_path.is_file() else "open_model.cfile is missing",
        },
    ]
    checks["items"] = file_items + list(checks.get("items", []))
    if not cfile_path.is_file():
        checks["ok"] = False
        checks.setdefault("errors", []).append("open_model.cfile is missing")
    checks["project_name"] = spec.project_name
    checks["keyword_path"] = str(keyword_path)
    checks["spec_path"] = str(model_path)
    summary = dict(checks.get("summary", {}))
    summary["project_name"] = spec.project_name
    summary["derived"] = _derived_summary(spec)
    checks["summary"] = summary
    return checks


def generate_quarter_two_tnt_project(args: Mapping[str, object]) -> JSONDict:
    """Generate the fixed approved project transactionally without running a solver."""

    import os
    import shutil
    from dataclasses import replace

    from .cfile import write_server_cfile
    from .io import write_json
    from .locks import ProjectLock
    from .paths import project_dir, safe_project_name
    from .project_store import (
        ALLOWED_IF_EXISTS,
        commit_project_dir,
        ensure_no_active_runtime,
        mark_runtime_artifact,
        next_versioned_project_dir,
        rebase_committed_checks,
        remove_runtime_artifact,
        temp_project_dir,
    )

    allowed = set(_ALLOWED_FIELDS) | {"dry_run", "if_exists"}
    unknown = sorted(set(args) - allowed)
    if unknown:
        raise ValueError(f"unsupported argument(s): {', '.join(unknown)}")
    project_name = str(args.get("project_name", "quarter_two_tnt_ale_spg"))
    if safe_project_name(project_name) != project_name:
        raise ValueError("project_name contains unsupported characters")
    raw = default_quarter_two_tnt_spec(project_name)
    for key in _ALLOWED_FIELDS:
        if key in args:
            raw[key] = args[key]
    spec = validate_quarter_two_tnt_spec(raw)
    if_exists = str(args.get("if_exists", "error"))
    if if_exists not in ALLOWED_IF_EXISTS:
        raise ValueError(f"if_exists must be one of {', '.join(sorted(ALLOWED_IF_EXISTS))}")
    path = project_dir(spec.project_name)
    if bool(args.get("dry_run", False)):
        return {
            "project": spec.project_name,
            "project_dir": str(path),
            "dry_run": True,
            "if_exists": if_exists,
            "spec": spec.to_json(),
            "derived": _derived_summary(spec),
            "solver_started": False,
        }

    with ProjectLock(spec.project_name):
        final_name = spec.project_name
        if path.exists():
            if if_exists == "error":
                raise FileExistsError(
                    f"project already exists: {path}; use if_exists=overwrite, archive_then_write, or versioned"
                )
            if if_exists == "versioned":
                path = next_versioned_project_dir(spec.project_name)
                final_name = path.name
                spec = replace(spec, project_name=final_name)
            else:
                ensure_no_active_runtime(path, False)

        tmp_path = temp_project_dir(path)
        if tmp_path.exists():
            raise FileExistsError(f"temporary project path already exists: {tmp_path}")
        tmp_path.mkdir(parents=True)
        mark_runtime_artifact(tmp_path)
        try:
            keyword_path = tmp_path / "model.k"
            digest = hashlib.sha256()
            with keyword_path.open("w", encoding="utf-8", newline="\n") as handle:
                for line in iter_quarter_two_tnt_keyword(spec):
                    handle.write(line)
                    digest.update(line.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            keyword_digest = digest.hexdigest()
            metadata = _project_metadata(spec, keyword_digest)
            write_json(
                tmp_path / "model.json",
                {
                    "schema_version": "0.2.0",
                    "spec": spec.to_json(),
                    "metadata": metadata,
                },
            )
            write_server_cfile(
                tmp_path,
                "open_model.cfile",
                "open_keyword.cfile",
                {"keyword_path": "model.k"},
                if_exists="overwrite",
            )
            checks = validate_quarter_two_tnt_project(tmp_path)
            write_json(tmp_path / "checks.json", checks)
            if not checks.get("ok"):
                raise ValueError(f"generated quarter-two-TNT project failed validation: {checks.get('errors', [])}")

            commit_project_dir(tmp_path, path, if_exists)
            remove_runtime_artifact(path)
            checks = rebase_committed_checks(
                checks,
                project_name=final_name,
                project_path=path,
            )
            write_json(path / "checks.json", checks)
            return {
                "project": final_name,
                "project_dir": str(path),
                "keyword_path": str(path / "model.k"),
                "cfile_path": str(path / "open_model.cfile"),
                "spec_path": str(path / "model.json"),
                "checks_path": str(path / "checks.json"),
                "metadata": metadata,
                "derived": _derived_summary(spec),
                "checks": checks,
                "if_exists": if_exists,
                "dry_run": False,
                "solver_started": False,
            }
        except Exception:
            if tmp_path.exists():
                shutil.rmtree(tmp_path)
            raise


def tool_generate_quarter_two_tnt(args: JSONDict) -> JSONDict:
    return generate_quarter_two_tnt_project(args)