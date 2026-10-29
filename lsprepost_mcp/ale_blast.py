"""Controlled Phase 14 MM-ALE blast scene compiler.

The bundled scene is a software-validation reference model, not an engineering
blast certification model. It uses SI units throughout and keeps solver launch
outside this module.
"""

from __future__ import annotations

from dataclasses import replace
from bisect import bisect_right
import math
from typing import TYPE_CHECKING, Any

from .ale import default_ale_air_definition, render_ale_air_cards
from .config import DEFAULT_UNIT_SYSTEM, JSONDict
from .dyna_cards import common_header, material_lines
from .materials import resolve_material
from .preflight import grid_count

if TYPE_CHECKING:
    from .schema import ModelSpec


AIR_PART_ID = 1
AIR_SECTION_ID = 1
AIR_MATERIAL_ID = 1
AIR_EOS_ID = 1
EXPLOSIVE_PART_ID = 2
EXPLOSIVE_SECTION_ID = 2
EXPLOSIVE_MATERIAL_ID = 2
EXPLOSIVE_EOS_ID = 2
PLATE_PART_ID = 3
PLATE_SECTION_ID = 3
PLATE_MATERIAL_ID = 3
OUTER_SEGMENT_SET_ID = 100
PLATE_FIXED_NODE_SET_ID = 200
PLATE_RESPONSE_NODE_SET_ID = 201
ALE_MATERIAL_PART_SET_ID = 1
ALE_PRESSURE_PROBE_SOLID_SET_ID = 300
TUNNEL_PART_ID = 4
TUNNEL_SECTION_ID = 4
TUNNEL_MATERIAL_ID = 4
TUNNEL_FIXED_NODE_SET_ID = 202

TUNNEL_AIR_MESH_OPTIONS_M = (0.075, 0.1, 0.125, 0.15)
TUNNEL_PLATE_MATERIAL_NAMES = (
    "mild_steel_mat24_demo",
    "mild_steel",
    "aluminum_6061_t6",
)
TUNNEL_DIMENSION_LIMITS_M = {
    "length": (4.0, 12.0),
    "width": (2.0, 8.0),
    "height": (2.0, 8.0),
    "wall_thickness": (0.1, 0.6),
}

COMPOSITION_B_REFERENCE: JSONDict = {
    "id": "composition_b_reference",
    "display_name": "Composition B reference demo",
    "unit_system": DEFAULT_UNIT_SYSTEM,
    "density_kg_per_m3": 1700.0,
    "detonation_velocity_m_per_s": 8000.0,
    "chapman_jouget_pressure_pa": 3.0e10,
    "beta": 2.0,
    "jwl": {
        "a_pa": 5.24e11,
        "b_pa": 7.68e9,
        "r1": 4.2,
        "r2": 1.1,
        "omega": 0.5,
        "initial_internal_energy_density_j_per_m3": 8.5e9,
        "initial_relative_volume": 1.0,
    },
    "validation_status": "published_reference_demo",
    "source": (
        "15th International LS-DYNA Users Conference, blast-wave mesh "
        "sensitivity / published Composition B SI parameters"
    ),
    "requires_project_review": True,
}


def _r12_field(value: float) -> str:
    """Format a numeric value within LS-DYNA R12's 10-character field limit."""

    for precision in range(9, 0, -1):
        candidate = f"{float(value):.{precision}g}"
        if len(candidate) <= 10:
            return candidate
    raise ValueError(f"cannot format LS-DYNA R12 numeric field: {value!r}")


def default_ale_blast_spec(project_name: str = "phase14_mmale_blast_plate") -> JSONDict:
    """Return the controlled Phase 14 MM-ALE plate-blast reference spec."""

    return {
        "project_name": project_name,
        "model_type": "ale_blast_scene",
        "unit_system": DEFAULT_UNIT_SYSTEM,
        "geometry": {
            "domain_min_m": [-0.3, -0.3, -0.05],
            "domain_max_m": [0.3, 0.3, 0.35],
            "explosive_center_m": [0.0, 0.0, 0.2],
            "explosive_mass_kg": 0.1,
            "explosive_material": "composition_b_reference",
            "plate_length_m": 0.4,
            "plate_width_m": 0.4,
            "plate_thickness_m": 0.006,
            "plate_z_m": 0.0,
        },
        "mesh": {"size_m": 0.0125},
        "material": {"name": "mild_steel_mat24_demo"},
        "curves": [],
        "hourglass": {},
        "analysis_control": {
            "termination": {"end_time_s": 0.002},
            "energy": {"hgen": 2, "rwen": 2, "slnten": 2, "rylen": 2},
            "shell": {"wrpang": 20.0, "esort": 1, "irnxx": -1, "istupd": 1},
            "timestep": {"tssfac": 0.8},
        },
        "database": {
            "format": 0,
            "ibinary": 1,
            "d3plot_dt_s": 0.00005,
            "d3plot_lcdt_curve_id": 990001,
            "d3plot_schedule": [
                {"until_time_s": 0.0003, "dt_s": 0.00001},
                {"until_time_s": 0.002, "dt_s": 0.00005},
            ],
            "nodout_dt_s": 0.00005,
            "fsi_dt_s": 0.00001,
            "ale_mat_dt_s": 0.00001,
            "ale_probe_dt_s": 0.00001,
            "glstat_dt_s": 0.00005,
            "matsum_dt_s": 0.00005,
            "extent_binary": {
                "neiph": 0,
                "strflg": 1,
                "sigflg": 1,
                "epsflg": 1,
                "rltflg": 1,
                "engflg": 1,
                "ialemat": 1,
            },
        },
        "components": [],
        "contacts": [],
        "sets": [],
        "boundary_conditions": [],
        "loads": [],
    }


def default_tunnel_blast_spec(project_name: str = "phase14_open_tunnel_blast") -> JSONDict:
    """Return the controlled parametric open concrete tunnel blast scene."""

    spec = default_ale_blast_spec(project_name)
    spec["geometry"] = {
        "scene_variant": "open_concrete_tunnel",
        "domain_min_m": [0.0, -2.0, -2.0],
        "domain_max_m": [6.0, 2.0, 2.0],
        "tunnel_length_m": 6.0,
        "tunnel_width_m": 4.0,
        "tunnel_height_m": 4.0,
        "tunnel_wall_thickness_m": 0.25,
        "tunnel_material_name": "concrete_linear_elastic_demo",
        "explosive_center_m": [1.5, 0.0, 0.0],
        "explosive_mass_kg": 1.0,
        "explosive_material": "composition_b_reference",
        "plate_length_m": 1.2,
        "plate_width_m": 1.2,
        "plate_thickness_m": 0.02,
        "plate_center_m": [4.5, 0.0, 0.0],
    }
    spec["mesh"] = {
        "size_m": 0.1,
        "mode": "uniform_air_mesh",
        "wall_size_m": 0.1,
        "plate_size_m": 0.05,
    }
    spec["analysis_control"]["termination"]["end_time_s"] = 0.012
    spec["database"].update(
        {
            "d3plot_dt_s": 0.0001,
            "d3plot_schedule": [
                {"until_time_s": 0.004, "dt_s": 0.00002},
                {"until_time_s": 0.012, "dt_s": 0.0001},
            ],
            "nodout_dt_s": 0.0001,
            "fsi_dt_s": 0.00002,
            "ale_mat_dt_s": 0.00002,
            "ale_probe_dt_s": 0.00002,
            "glstat_dt_s": 0.0001,
            "matsum_dt_s": 0.0001,
        }
    )
    return spec


def explosive_radius_m(mass_kg: float) -> float:
    density = float(COMPOSITION_B_REFERENCE["density_kg_per_m3"])
    return (3.0 * mass_kg / (4.0 * math.pi * density)) ** (1.0 / 3.0)


def _finite(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{path} must be a finite number")
    return number


def _vector3(value: object, path: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{path} must contain exactly three finite numbers")
    return [_finite(item, f"{path}[{index}]") for index, item in enumerate(value)]


def validate_ale_blast_geometry(geometry: JSONDict, mesh_size_m: float) -> JSONDict:
    """Validate and normalize the controlled air-domain/charge/plate geometry."""

    if geometry.get("scene_variant") == "open_concrete_tunnel":
        return _validate_tunnel_blast_geometry(geometry, mesh_size_m)

    allowed = {
        "domain_min_m",
        "domain_max_m",
        "explosive_center_m",
        "explosive_mass_kg",
        "explosive_material",
        "plate_length_m",
        "plate_width_m",
        "plate_thickness_m",
        "plate_z_m",
    }
    unknown = sorted(set(geometry) - allowed)
    if unknown:
        raise ValueError(f"ale_blast_scene.geometry contains unknown fields: {', '.join(unknown)}")
    mesh_size = _finite(mesh_size_m, "mesh.size_m")
    if mesh_size <= 0.0:
        raise ValueError("mesh.size_m must be positive")

    domain_min = _vector3(geometry.get("domain_min_m"), "geometry.domain_min_m")
    domain_max = _vector3(geometry.get("domain_max_m"), "geometry.domain_max_m")
    for axis, low, high in zip("xyz", domain_min, domain_max):
        if high <= low:
            raise ValueError(f"geometry domain {axis}-maximum must exceed its minimum")
    center = _vector3(geometry.get("explosive_center_m"), "geometry.explosive_center_m")
    mass = _finite(geometry.get("explosive_mass_kg"), "geometry.explosive_mass_kg")
    if not 0.001 <= mass <= 5.0:
        raise ValueError("geometry.explosive_mass_kg must be between 0.001 and 5.0 kg")
    if geometry.get("explosive_material") != "composition_b_reference":
        raise ValueError("geometry.explosive_material currently supports composition_b_reference only")
    radius = explosive_radius_m(mass)
    if 2.0 * radius / mesh_size < 3.0:
        raise ValueError("explosive diameter must span at least 3 cells; reduce mesh.size_m")
    margin = mesh_size
    if any(
        center[index] - radius - margin <= domain_min[index]
        or center[index] + radius + margin >= domain_max[index]
        for index in range(3)
    ):
        raise ValueError("explosive sphere must be inside the ALE domain with one-cell clearance")

    plate_length = _finite(geometry.get("plate_length_m"), "geometry.plate_length_m")
    plate_width = _finite(geometry.get("plate_width_m"), "geometry.plate_width_m")
    plate_thickness = _finite(geometry.get("plate_thickness_m"), "geometry.plate_thickness_m")
    plate_z = _finite(geometry.get("plate_z_m"), "geometry.plate_z_m")
    if min(plate_length, plate_width, plate_thickness) <= 0.0:
        raise ValueError("plate dimensions must be positive")
    if plate_length * 0.5 >= min(abs(domain_min[0]), abs(domain_max[0])):
        raise ValueError("plate length must fit inside the ALE domain")
    if plate_width * 0.5 >= min(abs(domain_min[1]), abs(domain_max[1])):
        raise ValueError("plate width must fit inside the ALE domain")
    if not domain_min[2] < plate_z < domain_max[2]:
        raise ValueError("plate_z_m must lie inside the ALE domain")
    if center[2] - radius - plate_z < 2.0 * mesh_size:
        raise ValueError("explosive must have at least two cells of stand-off above the plate")

    return {
        **geometry,
        "domain_min_m": domain_min,
        "domain_max_m": domain_max,
        "explosive_center_m": center,
        "explosive_mass_kg": mass,
        "explosive_radius_m": radius,
        "plate_length_m": plate_length,
        "plate_width_m": plate_width,
        "plate_thickness_m": plate_thickness,
        "plate_z_m": plate_z,
    }


def _validate_tunnel_blast_geometry(geometry: JSONDict, mesh_size_m: float) -> JSONDict:
    allowed = {
        "scene_variant",
        "domain_min_m",
        "domain_max_m",
        "tunnel_length_m",
        "tunnel_width_m",
        "tunnel_height_m",
        "tunnel_wall_thickness_m",
        "tunnel_material_name",
        "explosive_center_m",
        "explosive_mass_kg",
        "explosive_material",
        "plate_length_m",
        "plate_width_m",
        "plate_thickness_m",
        "plate_center_m",
    }
    unknown = sorted(set(geometry) - allowed)
    if unknown:
        raise ValueError(f"open_concrete_tunnel geometry contains unknown fields: {', '.join(unknown)}")
    mesh_size = _finite(mesh_size_m, "mesh.size_m")
    if not any(abs(mesh_size - option) <= 1.0e-12 for option in TUNNEL_AIR_MESH_OPTIONS_M):
        choices = ", ".join(f"{value:.3f}" for value in TUNNEL_AIR_MESH_OPTIONS_M)
        raise ValueError(f"tunnel air mesh size must be one of {choices} m")
    domain_min = _vector3(geometry.get("domain_min_m"), "geometry.domain_min_m")
    domain_max = _vector3(geometry.get("domain_max_m"), "geometry.domain_max_m")
    tunnel_length = _finite(geometry.get("tunnel_length_m"), "geometry.tunnel_length_m")
    tunnel_width = _finite(geometry.get("tunnel_width_m"), "geometry.tunnel_width_m")
    tunnel_height = _finite(geometry.get("tunnel_height_m"), "geometry.tunnel_height_m")
    wall_thickness = _finite(
        geometry.get("tunnel_wall_thickness_m"), "geometry.tunnel_wall_thickness_m"
    )
    dimension_values = {
        "length": tunnel_length,
        "width": tunnel_width,
        "height": tunnel_height,
        "wall_thickness": wall_thickness,
    }
    for name, value in dimension_values.items():
        low, high = TUNNEL_DIMENSION_LIMITS_M[name]
        if not low <= value <= high:
            raise ValueError(f"tunnel {name} must be between {low:g} and {high:g} m")
    expected_min = [0.0, -0.5 * tunnel_width, -0.5 * tunnel_height]
    expected_max = [tunnel_length, 0.5 * tunnel_width, 0.5 * tunnel_height]
    if any(abs(domain_min[index] - expected_min[index]) > 1.0e-9 for index in range(3)) or any(
        abs(domain_max[index] - expected_max[index]) > 1.0e-9 for index in range(3)
    ):
        raise ValueError("tunnel ALE domain must match the configured internal open passage")
    center = _vector3(geometry.get("explosive_center_m"), "geometry.explosive_center_m")
    mass = _finite(geometry.get("explosive_mass_kg"), "geometry.explosive_mass_kg")
    if not 0.001 <= mass <= 5.0:
        raise ValueError("geometry.explosive_mass_kg must be between 0.001 and 5.0 kg")
    if geometry.get("explosive_material") != "composition_b_reference":
        raise ValueError("geometry.explosive_material currently supports composition_b_reference only")
    radius = explosive_radius_m(mass)
    if any(center[index] - radius <= domain_min[index] or center[index] + radius >= domain_max[index] for index in range(3)):
        raise ValueError("explosive sphere must remain inside the tunnel air domain")
    plate_length = _finite(geometry.get("plate_length_m"), "geometry.plate_length_m")
    plate_width = _finite(geometry.get("plate_width_m"), "geometry.plate_width_m")
    plate_thickness = _finite(geometry.get("plate_thickness_m"), "geometry.plate_thickness_m")
    plate_center = _vector3(geometry.get("plate_center_m"), "geometry.plate_center_m")
    if min(plate_length, plate_width, plate_thickness) <= 0.0:
        raise ValueError("plate dimensions must be positive")
    if not 0.0 < plate_center[0] < tunnel_length:
        raise ValueError("plate center X must remain inside the open tunnel")
    if abs(plate_center[1]) + 0.5 * plate_length >= 0.5 * tunnel_width or abs(
        plate_center[2]
    ) + 0.5 * plate_width >= 0.5 * tunnel_height:
        raise ValueError("plate must fit inside the tunnel cross-section at its selected Y/Z position")
    closest = [
        max(abs(center[0] - plate_center[0]) - 0.5 * plate_thickness, 0.0),
        max(abs(center[1] - plate_center[1]) - 0.5 * plate_length, 0.0),
        max(abs(center[2] - plate_center[2]) - 0.5 * plate_width, 0.0),
    ]
    if math.sqrt(sum(value * value for value in closest)) <= radius:
        raise ValueError("explosive sphere must not overlap the target plate")
    tunnel_material_name = str(geometry.get("tunnel_material_name", "")).strip()
    if not tunnel_material_name:
        raise ValueError("geometry.tunnel_material_name is required")
    resolve_material({"name": tunnel_material_name})
    return {
        **geometry,
        "domain_min_m": domain_min,
        "domain_max_m": domain_max,
        "explosive_center_m": center,
        "explosive_mass_kg": mass,
        "explosive_radius_m": radius,
        "plate_length_m": plate_length,
        "plate_width_m": plate_width,
        "plate_thickness_m": plate_thickness,
        "plate_center_m": plate_center,
        "tunnel_length_m": tunnel_length,
        "tunnel_width_m": tunnel_width,
        "tunnel_height_m": tunnel_height,
        "tunnel_wall_thickness_m": wall_thickness,
        "tunnel_material_name": tunnel_material_name,
    }


def render_composition_b_cards(*, material_id: int, eos_id: int) -> list[str]:
    material = COMPOSITION_B_REFERENCE
    jwl = material["jwl"]
    return [
        "*MAT_HIGH_EXPLOSIVE_BURN",
        "$#   mid        ro         d       pcj      beta",
        (
            f"{material_id},{float(material['density_kg_per_m3']):.10g},"
            f"{float(material['detonation_velocity_m_per_s']):.10g},"
            f"{float(material['chapman_jouget_pressure_pa']):.10g},"
            f"{float(material['beta']):.10g}"
        ),
        "*EOS_JWL",
        "$# eosid         a         b        r1        r2     omega        e0        v0",
        (
            f"{eos_id},{float(jwl['a_pa']):.10g},{float(jwl['b_pa']):.10g},"
            f"{float(jwl['r1']):.10g},{float(jwl['r2']):.10g},"
            f"{float(jwl['omega']):.10g},"
            f"{float(jwl['initial_internal_energy_density_j_per_m3']):.10g},"
            f"{float(jwl['initial_relative_volume']):.10g}"
        ),
    ]


def phase14_mesh_sensitivity_report(spec: "ModelSpec") -> JSONDict:
    """Return a no-solve mesh plan for the controlled MM-ALE reference scene."""

    baseline = float(spec.mesh["size_m"])
    geometry = validate_ale_blast_geometry(spec.geometry, baseline)
    levels: list[JSONDict] = []
    for name, factor in (("coarse", 1.2), ("baseline", 1.0), ("fine", 0.8), ("refined", 0.75)):
        size = baseline * factor
        normalized = validate_ale_blast_geometry(spec.geometry, size)
        domain_min = normalized["domain_min_m"]
        domain_max = normalized["domain_max_m"]
        nx = grid_count(domain_max[0] - domain_min[0], size)
        ny = grid_count(domain_max[1] - domain_min[1], size)
        nz = grid_count(domain_max[2] - domain_min[2], size)
        plate_nx = grid_count(float(normalized["plate_length_m"]), size)
        plate_ny = grid_count(float(normalized["plate_width_m"]), size)
        nodes = (nx + 1) * (ny + 1) * (nz + 1) + (plate_nx + 1) * (plate_ny + 1)
        elements = nx * ny * nz + plate_nx * plate_ny
        levels.append(
            {
                "name": name,
                "mesh_size_m": size,
                "domain_cells": [nx, ny, nz],
                "charge_diameter_cells": 2.0 * float(normalized["explosive_radius_m"]) / size,
                "estimated_node_count": nodes,
                "estimated_element_count": elements,
                "within_generation_limits": nodes <= 250_000 and elements <= 200_000,
            }
        )
    return {
        "status": "planned_not_solved",
        "levels": levels,
        "comparison_metrics": [
            "peak_plate_displacement_m",
            "peak_plate_effective_stress_pa",
            "peak_ale_pressure_pa",
            "fsi_impulse_n_s",
            "global_energy_balance",
        ],
        "acceptance_rule": (
            "Compare baseline and fine runs after explicit approval; target <=10% change "
            "in the selected response metrics and review energy/mass balance."
        ),
        "solver_permission": "explicit_user_approval_required",
        "convergence_claimed": False,
    }


def build_ale_blast_scene(spec: "ModelSpec") -> tuple[str, JSONDict]:
    if spec.geometry.get("scene_variant") == "open_concrete_tunnel":
        return _build_open_concrete_tunnel_scene(spec)
    geometry = validate_ale_blast_geometry(spec.geometry, float(spec.mesh["size_m"]))
    mesh_size = float(spec.mesh["size_m"])
    domain_min = geometry["domain_min_m"]
    domain_max = geometry["domain_max_m"]
    lengths = [domain_max[index] - domain_min[index] for index in range(3)]
    nx, ny, nz = [grid_count(length, mesh_size) for length in lengths]
    dx, dy, dz = lengths[0] / nx, lengths[1] / ny, lengths[2] / nz

    def domain_nid(ix: int, iy: int, iz: int) -> int:
        return iz * (ny + 1) * (nx + 1) + iy * (nx + 1) + ix + 1

    nodes: list[tuple[int, float, float, float]] = [
        (
            domain_nid(ix, iy, iz),
            domain_min[0] + ix * dx,
            domain_min[1] + iy * dy,
            domain_min[2] + iz * dz,
        )
        for iz in range(nz + 1)
        for iy in range(ny + 1)
        for ix in range(nx + 1)
    ]
    solids: list[tuple[int, int, int, int, int, int, int, int, int, int]] = []
    for iz in range(nz):
        for iy in range(ny):
            for ix in range(nx):
                solids.append(
                    (
                        len(solids) + 1,
                        AIR_PART_ID,
                        domain_nid(ix, iy, iz),
                        domain_nid(ix + 1, iy, iz),
                        domain_nid(ix + 1, iy + 1, iz),
                        domain_nid(ix, iy + 1, iz),
                        domain_nid(ix, iy, iz + 1),
                        domain_nid(ix + 1, iy, iz + 1),
                        domain_nid(ix + 1, iy + 1, iz + 1),
                        domain_nid(ix, iy + 1, iz + 1),
                    )
                )

    plate_nx = grid_count(float(geometry["plate_length_m"]), mesh_size)
    plate_ny = grid_count(float(geometry["plate_width_m"]), mesh_size)
    plate_dx = float(geometry["plate_length_m"]) / plate_nx
    plate_dy = float(geometry["plate_width_m"]) / plate_ny
    first_plate_node = len(nodes) + 1

    def plate_nid(ix: int, iy: int) -> int:
        return first_plate_node + iy * (plate_nx + 1) + ix

    plate_x0 = -0.5 * float(geometry["plate_length_m"])
    plate_y0 = -0.5 * float(geometry["plate_width_m"])
    plate_z = float(geometry["plate_z_m"])
    nodes.extend(
        (plate_nid(ix, iy), plate_x0 + ix * plate_dx, plate_y0 + iy * plate_dy, plate_z)
        for iy in range(plate_ny + 1)
        for ix in range(plate_nx + 1)
    )
    shells: list[tuple[int, int, int, int, int, int]] = []
    first_shell_eid = len(solids) + 1
    for iy in range(plate_ny):
        for ix in range(plate_nx):
            shells.append(
                (
                    first_shell_eid + len(shells),
                    PLATE_PART_ID,
                    plate_nid(ix, iy),
                    plate_nid(ix + 1, iy),
                    plate_nid(ix + 1, iy + 1),
                    plate_nid(ix, iy + 1),
                )
            )

    outer_segments = _outer_domain_segments(domain_nid, nx, ny, nz)
    fixed_plate_nodes = sorted(
        {
            plate_nid(ix, iy)
            for iy in range(plate_ny + 1)
            for ix in range(plate_nx + 1)
            if ix in {0, plate_nx} or iy in {0, plate_ny}
        }
    )
    response_plate_nodes = sorted(
        plate_nid(ix, iy)
        for iy in range(1, plate_ny)
        for ix in range(1, plate_nx)
    )
    probe_solid_ids = _probe_solid_ids(
        domain_min,
        [dx, dy, dz],
        [nx, ny, nz],
        [
            geometry["explosive_center_m"],
            [
                geometry["explosive_center_m"][0],
                geometry["explosive_center_m"][1],
                0.5 * (geometry["explosive_center_m"][2] + plate_z),
            ],
        ],
    )

    lines = common_header(spec)
    lines.extend(
        [
            "$ Phase 14 controlled MM-ALE reference scene",
            "$ Solver execution requires explicit user approval outside this deck generator.",
            "*CONTROL_ALE",
            "$#     dct      nadv      meth      afac      bfac      cfac      dfac      efac",
            "-1,1,2,-1.0,0.0,0.0,0.0,0.0",
            "$#   start       end     aafac     vfact    vlimit       ebc      pref   nsidebc",
            "0.0,1.0e20,1.0,1.0e-6,0,0,101325.0,0",
            "*DATABASE_GLSTAT",
            f"{float(spec.database.get('glstat_dt_s', 0.00005)):.10g}",
            "*DATABASE_MATSUM",
            f"{float(spec.database.get('matsum_dt_s', 0.00005)):.10g}",
            "*DATABASE_FSI",
            f"{float(spec.database.get('fsi_dt_s', 0.00001)):.10g}",
            "1,3,1",
            "*DATABASE_ALE_MAT",
            "$#   dtout     npltc",
            f"{float(spec.database.get('ale_mat_dt_s', 0.00001)):.10g},0",
            "*DATABASE_ALE",
            "$#   dtout     setid",
            f"{float(spec.database.get('ale_probe_dt_s', 0.00001)):.10g},{ALE_PRESSURE_PROBE_SOLID_SET_ID}",
            "$# variables: pressure, mass, volume, density, impulse",
            "11,12,13,14,17",
            "*NODE",
            "$#   nid               x               y               z",
        ]
    )
    lines.extend(f"{nid},{x:.10g},{y:.10g},{z:.10g}" for nid, x, y, z in nodes)
    lines.extend(
        [
            "*ELEMENT_SOLID",
            "$#   eid     pid      n1      n2      n3      n4      n5      n6      n7      n8",
        ]
    )
    lines.extend(",".join(str(value) for value in element) for element in solids)
    lines.extend(["*ELEMENT_SHELL", "$#   eid     pid      n1      n2      n3      n4"])
    lines.extend(",".join(str(value) for value in element) for element in shells)
    lines.extend(_part_lines("ALE air domain", 1, 1, 1, 1))
    lines.extend(_part_lines("Composition B material group", 2, 2, 2, 2))
    lines.extend(_part_lines("Coupled steel target plate", 3, 3, 3, 0))
    lines.extend(
        [
            "*SECTION_SOLID",
            "$# secid    elform",
            "1,11",
            "*SECTION_SOLID",
            "$# secid    elform",
            "2,11",
            "*SECTION_SHELL",
            "$# secid    elform      shrf       nip     propt",
            "3,2,0.833,5,1.0",
            "$#     t1        t2        t3        t4      nloc",
            (
                f"{float(geometry['plate_thickness_m']):.10g},"
                f"{float(geometry['plate_thickness_m']):.10g},"
                f"{float(geometry['plate_thickness_m']):.10g},"
                f"{float(geometry['plate_thickness_m']):.10g},0.0"
            ),
            "*ALE_MULTI-MATERIAL_GROUP",
            "$#     sid    idtype",
            "1,1",
            "2,1",
        ]
    )
    lines.extend(render_ale_air_cards(default_ale_air_definition(), material_id=1, eos_id=1))
    lines.extend(render_composition_b_cards(material_id=2, eos_id=2))
    plate_spec = replace(spec, material={**spec.material, "id": PLATE_MATERIAL_ID})
    lines.extend(material_lines(plate_spec))
    lines.extend(
        [
            "*INITIAL_VOLUME_FRACTION_GEOMETRY",
            "$#   fmsid   fmidtyp    bammg    ntrace",
            "1,1,1,0",
            "$# conttyp   fillopt    fammg",
            "6,0,2",
            "$#      x0        y0        z0        r0",
            (
                f"{geometry['explosive_center_m'][0]:.10g},"
                f"{geometry['explosive_center_m'][1]:.10g},"
                f"{geometry['explosive_center_m'][2]:.10g},"
                f"{_r12_field(geometry['explosive_radius_m'])}"
            ),
            "*INITIAL_DETONATION",
            "$#     pid        x0        y0        z0        lt",
            (
                f"{AIR_PART_ID},{geometry['explosive_center_m'][0]:.10g},"
                f"{geometry['explosive_center_m'][1]:.10g},"
                f"{geometry['explosive_center_m'][2]:.10g},0.0"
            ),
            "*SET_PART_LIST_TITLE",
            "ALE air and explosive material parts",
            str(ALE_MATERIAL_PART_SET_ID),
            f"{AIR_PART_ID},{EXPLOSIVE_PART_ID}",
            "*SET_SOLID_LIST_TITLE",
            "ALE pressure-path probe elements",
            str(ALE_PRESSURE_PROBE_SOLID_SET_ID),
            ",".join(str(value) for value in probe_solid_ids),
            "*CONSTRAINED_LAGRANGE_IN_SOLID",
            "$#   slave    master     sstyp     mstyp     nquad     ctype     direc     mcoup",
            f"{PLATE_PART_ID},{ALE_MATERIAL_PART_SET_ID},1,0,4,4,2,0",
            "$#   start       end      pfac      fric    frcmin      norm   normtyp      damp",
            "0.0,0.0,0.1,0.0,0.3,0,0,0.1",
            "$#       k      hmin      hmax     ileak     pleak   lcidpor     nvent    iblock",
            "0.0,0.0,0.0,2,0.1,0,0,0",
            "*SET_SEGMENT",
            "$#   sid       da1       da2       da3       da4",
            f"{OUTER_SEGMENT_SET_ID},0,0,0,0",
            "$ ALE outer non-reflecting boundary",
            "$#    n1      n2      n3      n4",
        ]
    )
    lines.extend(",".join(str(node_id) for node_id in segment) for segment in outer_segments)
    lines.extend(
        [
            "*BOUNDARY_NON_REFLECTING",
            "$#   ssid        ad        as",
            f"{OUTER_SEGMENT_SET_ID},0.0,0.0",
            "*SET_NODE_LIST_TITLE",
            "Fixed target plate perimeter",
            str(PLATE_FIXED_NODE_SET_ID),
        ]
    )
    for index in range(0, len(fixed_plate_nodes), 8):
        lines.append(",".join(str(value) for value in fixed_plate_nodes[index : index + 8]))
    lines.extend(
        [
            "*BOUNDARY_SPC_SET",
            "$#  nsid       cid      dofx      dofy      dofz     dofrx     dofry     dofrz",
            f"{PLATE_FIXED_NODE_SET_ID},0,1,1,1,1,1,1",
            "*SET_NODE_LIST_TITLE",
            "Free target plate response nodes",
            str(PLATE_RESPONSE_NODE_SET_ID),
        ]
    )
    for index in range(0, len(response_plate_nodes), 8):
        lines.append(",".join(str(value) for value in response_plate_nodes[index : index + 8]))
    lines.extend(
        [
            "*DATABASE_HISTORY_NODE_SET",
            "$#   nsid",
            str(PLATE_RESPONSE_NODE_SET_ID),
            "*END",
        ]
    )

    metadata: JSONDict = {
        "unit_system": spec.unit_system,
        "model_type": spec.model_type,
        "element_family": "mixed",
        "analysis_method": "MM-ALE",
        "validation_profile": "mm_ale_blast_v1",
        "validation_capabilities": [
            "mm_ale",
            "mm_ale_3d",
            "high_explosive_jwl",
            "lagrangian_shell_structure",
            "ale_fsi",
            "ale_nonreflecting_3d",
            "ale_pressure_outputs",
            "steel_plasticity",
        ],
        "node_count": len(nodes),
        "element_count": len(solids) + len(shells),
        "solid_element_count": len(solids),
        "shell_element_count": len(shells),
        "ale_solid_element_count": len(solids),
        "lagrangian_shell_element_count": len(shells),
        "part_count": 3,
        "material_count": 3,
        "section_count": 3,
        "ale_material_groups": 2,
        "constraint_count": 1,
        "generated_constraint_anchor_count": 1,
        "node_set_count": 2,
        "part_set_count": 1,
        "segment_set_count": 1,
        "contact_count": 0,
        "coupling_count": 1,
        "coupling_controls": {
            "coupled_material_groups": "all",
            "nquad": 4,
            "penalty_factor": 0.1,
            "minimum_volume_fraction": 0.3,
            "damping": 0.1,
            "leakage_control": 2,
            "leakage_penalty": 0.1,
        },
        "load_count": 0,
        "initial_condition_count": 2,
        "database_count": 10,
        "control_count": 5,
        "controlled_contact_cards": [],
        "shock_wave_visible_in_d3plot": True,
        "pressure_result_location": "d3plot ALE solid pressure contour",
        "fsi_result_location": "dbfsi",
        "solver_permission": "explicit_user_approval_required",
        "phase14_static_readiness": {
            "ale_domain": True,
            "air_eos": True,
            "explosive_jwl": True,
            "volume_fraction_initialization": True,
            "detonation": True,
            "ale_lagrange_coupling": True,
            "non_reflecting_boundary": True,
            "pressure_and_fsi_outputs": True,
            "ale_mass_balance_output": True,
            "air_pressure_probe_output": True,
            "real_solver_acceptance": False,
        },
        "d3plot_output": {
            "mode": "staged" if spec.database.get("d3plot_schedule") else "fixed",
            "schedule": spec.database.get("d3plot_schedule", []),
        },
        "ale_quantitative_outputs": {
            "material_balance": ["alematmas.xy", "alematvol.xy", "alematEint.xy", "alematEkin.xy"],
            "pressure_probe_set_id": ALE_PRESSURE_PROBE_SOLID_SET_ID,
            "pressure_probe_solid_ids": probe_solid_ids,
            "variables": ["pressure", "mass", "volume", "density", "impulse"],
        },
        "ale_domain": {
            "part_id": AIR_PART_ID,
            "bounds_m": {"min": domain_min, "max": domain_max},
            "cells": [nx, ny, nz],
            "cell_size_m": [dx, dy, dz],
            "outer_segment_count": len(outer_segments),
        },
        "explosive": {
            "part_id": EXPLOSIVE_PART_ID,
            "material": geometry["explosive_material"],
            "mass_kg": geometry["explosive_mass_kg"],
            "center_m": geometry["explosive_center_m"],
            "radius_m": geometry["explosive_radius_m"],
            "detonation_host_part_id": AIR_PART_ID,
            "source": COMPOSITION_B_REFERENCE["source"],
            "validation_status": COMPOSITION_B_REFERENCE["validation_status"],
        },
        "components": [
            {
                "id": "ale_air_domain",
                "template": "ale_air_box",
                "part_id": 1,
                "element_family": "solid",
                "node_count": (nx + 1) * (ny + 1) * (nz + 1),
            },
            {
                "id": "composition_b_charge",
                "template": "ale_explosive_sphere",
                "part_id": 2,
                "element_family": "volume_fraction",
                "node_count": 0,
            },
            {
                "id": "target_plate",
                "template": "shell_plate",
                "part_id": 3,
                "element_family": "shell",
                "node_count": (plate_nx + 1) * (plate_ny + 1),
                "fixed_node_ids": fixed_plate_nodes,
                "response_node_ids": response_plate_nodes,
            },
        ],
    }
    return "\n".join(lines) + "\n", metadata


def _build_open_concrete_tunnel_scene(spec: "ModelSpec") -> tuple[str, JSONDict]:
    geometry = _validate_tunnel_blast_geometry(spec.geometry, float(spec.mesh["size_m"]))
    plate_material_name = str(spec.material.get("library_id") or spec.material.get("name"))
    if plate_material_name not in TUNNEL_PLATE_MATERIAL_NAMES:
        known = ", ".join(TUNNEL_PLATE_MATERIAL_NAMES)
        raise ValueError(f"tunnel target plate material must be one of: {known}")
    base_size = float(spec.mesh["size_m"])
    wall_size = float(spec.mesh["wall_size_m"])
    plate_size = float(spec.mesh["plate_size_m"])
    center = geometry["explosive_center_m"]
    domain_min = geometry["domain_min_m"]
    domain_max = geometry["domain_max_m"]
    plate_center = geometry["plate_center_m"]
    plate_x = float(plate_center[0])
    x_axis = _uniform_axis(domain_min[0], domain_max[0], base_size)
    y_axis = _uniform_axis(domain_min[1], domain_max[1], base_size)
    z_axis = _uniform_axis(domain_min[2], domain_max[2], base_size)
    nx, ny, nz = len(x_axis) - 1, len(y_axis) - 1, len(z_axis) - 1

    def domain_nid(ix: int, iy: int, iz: int) -> int:
        return iz * (ny + 1) * (nx + 1) + iy * (nx + 1) + ix + 1

    nodes: list[tuple[int, float, float, float]] = [
        (domain_nid(ix, iy, iz), x_axis[ix], y_axis[iy], z_axis[iz])
        for iz in range(nz + 1)
        for iy in range(ny + 1)
        for ix in range(nx + 1)
    ]
    solids: list[tuple[int, int, int, int, int, int, int, int, int, int]] = []
    for iz in range(nz):
        for iy in range(ny):
            for ix in range(nx):
                solids.append(
                    (
                        len(solids) + 1,
                        AIR_PART_ID,
                        domain_nid(ix, iy, iz),
                        domain_nid(ix + 1, iy, iz),
                        domain_nid(ix + 1, iy + 1, iz),
                        domain_nid(ix, iy + 1, iz),
                        domain_nid(ix, iy, iz + 1),
                        domain_nid(ix + 1, iy, iz + 1),
                        domain_nid(ix + 1, iy + 1, iz + 1),
                        domain_nid(ix, iy + 1, iz + 1),
                    )
                )

    shells: list[tuple[int, int, int, int, int, int]] = []

    def append_shell_grid(
        u_axis: list[float],
        v_axis: list[float],
        point: Any,
        part_id: int,
        reverse: bool = False,
    ) -> tuple[list[int], list[int]]:
        first_node = len(nodes) + 1
        nu = len(u_axis) - 1
        nv = len(v_axis) - 1

        def shell_nid(iu: int, iv: int) -> int:
            return first_node + iv * (nu + 1) + iu

        grid_nodes: list[int] = []
        end_nodes: list[int] = []
        for iv, v in enumerate(v_axis):
            for iu, u in enumerate(u_axis):
                nid = shell_nid(iu, iv)
                x, y, z = point(u, v)
                nodes.append((nid, x, y, z))
                grid_nodes.append(nid)
                if iu in {0, nu}:
                    end_nodes.append(nid)
        for iv in range(nv):
            for iu in range(nu):
                corners = [
                    shell_nid(iu, iv),
                    shell_nid(iu + 1, iv),
                    shell_nid(iu + 1, iv + 1),
                    shell_nid(iu, iv + 1),
                ]
                if reverse:
                    corners = [corners[0], corners[3], corners[2], corners[1]]
                shells.append((len(solids) + len(shells) + 1, part_id, *corners))
        return grid_nodes, end_nodes

    wall_x = _uniform_axis(0.0, float(geometry["tunnel_length_m"]), wall_size)
    wall_y = _uniform_axis(-0.5 * float(geometry["tunnel_width_m"]), 0.5 * float(geometry["tunnel_width_m"]), wall_size)
    wall_z = _uniform_axis(-0.5 * float(geometry["tunnel_height_m"]), 0.5 * float(geometry["tunnel_height_m"]), wall_size)
    wall_nodes: list[int] = []
    fixed_wall_nodes: list[int] = []
    for u_axis, v_axis, point, reverse in [
        (wall_x, wall_y, lambda x, y: (x, y, domain_min[2]), False),
        (wall_x, wall_y, lambda x, y: (x, y, domain_max[2]), True),
        (wall_x, wall_z, lambda x, z: (x, domain_min[1], z), True),
        (wall_x, wall_z, lambda x, z: (x, domain_max[1], z), False),
    ]:
        created, fixed = append_shell_grid(u_axis, v_axis, point, TUNNEL_PART_ID, reverse)
        wall_nodes.extend(created)
        fixed_wall_nodes.extend(fixed)

    plate_y = _uniform_axis(
        float(plate_center[1]) - 0.5 * float(geometry["plate_length_m"]),
        float(plate_center[1]) + 0.5 * float(geometry["plate_length_m"]),
        plate_size,
    )
    plate_z = _uniform_axis(
        float(plate_center[2]) - 0.5 * float(geometry["plate_width_m"]),
        float(plate_center[2]) + 0.5 * float(geometry["plate_width_m"]),
        plate_size,
    )
    plate_nodes, _unused = append_shell_grid(
        plate_y,
        plate_z,
        lambda y, z: (plate_x, y, z),
        PLATE_PART_ID,
        True,
    )
    plate_ny, plate_nz = len(plate_y) - 1, len(plate_z) - 1
    first_plate_node = plate_nodes[0]

    def plate_nid(iy: int, iz: int) -> int:
        return first_plate_node + iz * (plate_ny + 1) + iy

    fixed_plate_nodes = sorted(
        plate_nid(iy, iz)
        for iz in range(plate_nz + 1)
        for iy in range(plate_ny + 1)
        if iy in {0, plate_ny} or iz in {0, plate_nz}
    )
    response_plate_nodes = sorted(
        plate_nid(iy, iz)
        for iz in range(1, plate_nz)
        for iy in range(1, plate_ny)
    )
    open_end_segments = _open_end_segments(domain_nid, nx, ny, nz)
    probe_points = [
        [
            center[axis] + fraction * (plate_center[axis] - center[axis])
            for axis in range(3)
        ]
        for fraction in (0.1, 0.25, 0.5, 0.75, 0.9)
    ]
    probe_solid_ids = _probe_solid_ids_on_axes(x_axis, y_axis, z_axis, probe_points)

    lines = common_header(spec)
    lines.extend(
        [
            "$ Phase 14 controlled open concrete tunnel MM-ALE scene",
            "$ Geometry: parametric internal passage; both x ends open.",
            "$ Solver execution requires separate explicit user approval.",
            "*CONTROL_ALE",
            "$#     dct      nadv      meth      afac      bfac      cfac      dfac      efac",
            "-1,1,2,-1.0,0.0,0.0,0.0,0.0",
            "$#   start       end     aafac     vfact    vlimit       ebc      pref   nsidebc",
            "0.0,1.0e20,1.0,1.0e-6,0,0,101325.0,0",
            "*DATABASE_GLSTAT",
            f"{float(spec.database.get('glstat_dt_s', 0.0001)):.10g}",
            "*DATABASE_MATSUM",
            f"{float(spec.database.get('matsum_dt_s', 0.0001)):.10g}",
            "*DATABASE_FSI",
            f"{float(spec.database.get('fsi_dt_s', 0.00002)):.10g}",
            "1,3,1",
            "2,4,1",
            "*DATABASE_ALE_MAT",
            "$#   dtout     npltc",
            f"{float(spec.database.get('ale_mat_dt_s', 0.00002)):.10g},0",
            "*DATABASE_ALE",
            "$#   dtout     setid",
            f"{float(spec.database.get('ale_probe_dt_s', 0.00002)):.10g},{ALE_PRESSURE_PROBE_SOLID_SET_ID}",
            "$# variables: pressure, mass, volume, density, impulse",
            "11,12,13,14,17",
            "*NODE",
            "$#   nid               x               y               z",
        ]
    )
    lines.extend(f"{nid},{x:.10g},{y:.10g},{z:.10g}" for nid, x, y, z in nodes)
    lines.extend(["*ELEMENT_SOLID", "$#   eid     pid      n1      n2      n3      n4      n5      n6      n7      n8"])
    lines.extend(",".join(str(value) for value in element) for element in solids)
    lines.extend(["*ELEMENT_SHELL", "$#   eid     pid      n1      n2      n3      n4"])
    lines.extend(",".join(str(value) for value in element) for element in shells)
    lines.extend(_part_lines("ALE tunnel air domain", AIR_PART_ID, AIR_SECTION_ID, AIR_MATERIAL_ID, AIR_EOS_ID))
    lines.extend(_part_lines("Composition B material group", EXPLOSIVE_PART_ID, EXPLOSIVE_SECTION_ID, EXPLOSIVE_MATERIAL_ID, EXPLOSIVE_EOS_ID))
    lines.extend(_part_lines("Vertical coupled steel target plate", PLATE_PART_ID, PLATE_SECTION_ID, PLATE_MATERIAL_ID, 0))
    lines.extend(_part_lines("Concrete tunnel walls", TUNNEL_PART_ID, TUNNEL_SECTION_ID, TUNNEL_MATERIAL_ID, 0))
    lines.extend(
        [
            "*SECTION_SOLID",
            "1,11",
            "*SECTION_SOLID",
            "2,11",
            "*SECTION_SHELL",
            "3,2,0.833,5,1.0",
            f"{geometry['plate_thickness_m']:.10g},{geometry['plate_thickness_m']:.10g},{geometry['plate_thickness_m']:.10g},{geometry['plate_thickness_m']:.10g},0.0",
            "*SECTION_SHELL",
            "4,2,0.833,5,1.0",
            f"{geometry['tunnel_wall_thickness_m']:.10g},{geometry['tunnel_wall_thickness_m']:.10g},{geometry['tunnel_wall_thickness_m']:.10g},{geometry['tunnel_wall_thickness_m']:.10g},0.0",
            "*ALE_MULTI-MATERIAL_GROUP",
            "1,1",
            "2,1",
        ]
    )
    lines.extend(render_ale_air_cards(default_ale_air_definition(), material_id=AIR_MATERIAL_ID, eos_id=AIR_EOS_ID))
    lines.extend(render_composition_b_cards(material_id=EXPLOSIVE_MATERIAL_ID, eos_id=EXPLOSIVE_EOS_ID))
    lines.extend(material_lines(replace(spec, material={**spec.material, "id": PLATE_MATERIAL_ID})))
    concrete = resolve_material({"name": geometry["tunnel_material_name"]})
    lines.extend(material_lines(replace(spec, material={**concrete, "id": TUNNEL_MATERIAL_ID})))
    lines.extend(
        [
            "*INITIAL_VOLUME_FRACTION_GEOMETRY",
            "1,1,1,0",
            "6,0,2",
            f"{center[0]:.10g},{center[1]:.10g},{center[2]:.10g},{_r12_field(geometry['explosive_radius_m'])}",
            "*INITIAL_DETONATION",
            f"{AIR_PART_ID},{center[0]:.10g},{center[1]:.10g},{center[2]:.10g},0.0",
            "*SET_PART_LIST_TITLE",
            "ALE air and explosive material parts",
            str(ALE_MATERIAL_PART_SET_ID),
            f"{AIR_PART_ID},{EXPLOSIVE_PART_ID}",
            "*SET_SOLID_LIST_TITLE",
            "Tunnel centerline pressure probes",
            str(ALE_PRESSURE_PROBE_SOLID_SET_ID),
            ",".join(str(value) for value in probe_solid_ids),
        ]
    )
    lines.extend(_coupling_lines(PLATE_PART_ID))
    lines.extend(_coupling_lines(TUNNEL_PART_ID))
    lines.extend(
        [
            "*SET_SEGMENT_TITLE",
            "Open tunnel ends only",
            f"{OUTER_SEGMENT_SET_ID},0,0,0,0",
        ]
    )
    lines.extend(",".join(str(value) for value in segment) for segment in open_end_segments)
    lines.extend(["*BOUNDARY_NON_REFLECTING", f"{OUTER_SEGMENT_SET_ID},0.0,0.0"])
    _append_node_set(lines, PLATE_FIXED_NODE_SET_ID, "Fixed target plate perimeter", fixed_plate_nodes)
    lines.extend(["*BOUNDARY_SPC_SET", f"{PLATE_FIXED_NODE_SET_ID},0,1,1,1,1,1,1"])
    _append_node_set(lines, TUNNEL_FIXED_NODE_SET_ID, "Fixed tunnel end rims", sorted(set(fixed_wall_nodes)))
    lines.extend(["*BOUNDARY_SPC_SET", f"{TUNNEL_FIXED_NODE_SET_ID},0,1,1,1,1,1,1"])
    _append_node_set(lines, PLATE_RESPONSE_NODE_SET_ID, "Free target plate response nodes", response_plate_nodes)
    lines.extend(["*DATABASE_HISTORY_NODE_SET", str(PLATE_RESPONSE_NODE_SET_ID), "*END"])

    cell_sizes = {
        "x_min_m": min(b - a for a, b in zip(x_axis, x_axis[1:])),
        "x_max_m": max(b - a for a, b in zip(x_axis, x_axis[1:])),
        "y_min_m": min(b - a for a, b in zip(y_axis, y_axis[1:])),
        "y_max_m": max(b - a for a, b in zip(y_axis, y_axis[1:])),
        "z_min_m": min(b - a for a, b in zip(z_axis, z_axis[1:])),
        "z_max_m": max(b - a for a, b in zip(z_axis, z_axis[1:])),
    }
    metadata: JSONDict = {
        "unit_system": spec.unit_system,
        "model_type": spec.model_type,
        "scene_variant": "open_concrete_tunnel",
        "analysis_method": "MM-ALE",
        "element_family": "mixed",
        "validation_profile": "mm_ale_blast_v1",
        "validation_capabilities": [
            "mm_ale",
            "mm_ale_3d",
            "high_explosive_jwl",
            "lagrangian_shell_structure",
            "ale_fsi",
            "ale_nonreflecting_3d",
            "ale_pressure_outputs",
            "steel_plasticity",
        ],
        "node_count": len(nodes),
        "element_count": len(solids) + len(shells),
        "solid_element_count": len(solids),
        "shell_element_count": len(shells),
        "ale_solid_element_count": len(solids),
        "lagrangian_shell_element_count": len(shells),
        "part_count": 4,
        "material_count": 4,
        "section_count": 4,
        "ale_material_groups": 2,
        "constraint_count": 2,
        "generated_constraint_anchor_count": 2,
        "node_set_count": 3,
        "part_set_count": 1,
        "segment_set_count": 1,
        "contact_count": 0,
        "coupling_count": 2,
        "load_count": 0,
        "initial_condition_count": 2,
        "database_count": 10,
        "control_count": 5,
        "controlled_contact_cards": [],
        "shock_wave_visible_in_d3plot": True,
        "pressure_result_location": "d3plot ALE pressure plus DATABASE_ALE centerline probes",
        "fsi_result_location": "dbfsi for target plate and tunnel walls",
        "solver_permission": "explicit_user_approval_required",
        "mesh": {
            "mode": "uniform_air_mesh",
            "requested_air_size_m": base_size,
            "actual_cell_size_range_m": cell_sizes,
            "charge_diameter_cells": 2.0 * float(geometry["explosive_radius_m"]) / base_size,
            "charge_resolution_warning": 2.0 * float(geometry["explosive_radius_m"]) / base_size < 3.0,
        },
        "d3plot_output": {"mode": "staged", "schedule": spec.database["d3plot_schedule"]},
        "ale_quantitative_outputs": {
            "material_balance": ["alematmas.xy", "alematvol.xy", "alematEint.xy", "alematEkin.xy"],
            "pressure_probe_set_id": ALE_PRESSURE_PROBE_SOLID_SET_ID,
            "pressure_probe_solid_ids": probe_solid_ids,
        },
        "phase14_static_readiness": {
            "ale_domain": True,
            "air_eos": True,
            "explosive_jwl": True,
            "volume_fraction_initialization": True,
            "detonation": True,
            "ale_lagrange_coupling": True,
            "open_end_non_reflecting_boundaries": True,
            "concrete_side_walls_not_non_reflecting": True,
            "ale_mass_balance_output": True,
            "air_pressure_probe_output": True,
            "real_solver_acceptance": False,
        },
        "ale_domain": {
            "part_id": AIR_PART_ID,
            "bounds_m": {"min": domain_min, "max": domain_max},
            "cells": [nx, ny, nz],
            "outer_segment_count": len(open_end_segments),
        },
        "tunnel": {
            "part_id": TUNNEL_PART_ID,
            "inside_dimensions_m": [
                float(geometry["tunnel_length_m"]),
                float(geometry["tunnel_width_m"]),
                float(geometry["tunnel_height_m"]),
            ],
            "wall_thickness_m": float(geometry["tunnel_wall_thickness_m"]),
            "material": geometry["tunnel_material_name"],
            "open_ends": ["x_min", "x_max"],
            "material_limitation": "linear elastic workflow demo; not a concrete damage prediction model",
        },
        "explosive": {
            "part_id": EXPLOSIVE_PART_ID,
            "material": geometry["explosive_material"],
            "mass_kg": geometry["explosive_mass_kg"],
            "center_m": center,
            "radius_m": geometry["explosive_radius_m"],
        },
        "target_plate": {
            "part_id": PLATE_PART_ID,
            "center_m": plate_center,
            "dimensions_m": [geometry["plate_length_m"], geometry["plate_width_m"], geometry["plate_thickness_m"]],
            "standoff_m": math.dist(center, plate_center),
            "axial_standoff_m": abs(plate_x - center[0]),
            "material": plate_material_name,
            "orientation": "normal_to_tunnel_axis",
        },
        "components": [
            {"id": "ale_air_domain", "template": "ale_air_box", "part_id": AIR_PART_ID, "element_family": "solid"},
            {"id": "composition_b_charge", "template": "ale_explosive_sphere", "part_id": EXPLOSIVE_PART_ID, "element_family": "volume_fraction"},
            {"id": "target_plate", "template": "shell_plate", "part_id": PLATE_PART_ID, "element_family": "shell", "response_node_ids": response_plate_nodes},
            {"id": "concrete_tunnel", "template": "open_shell_tunnel", "part_id": TUNNEL_PART_ID, "element_family": "shell"},
        ],
    }
    return "\n".join(lines) + "\n", metadata


def _part_lines(title: str, pid: int, secid: int, mid: int, eosid: int) -> list[str]:
    return [
        "*PART",
        title,
        "$#   pid     secid       mid     eosid      hgid      grav    adpopt      tmid",
        f"{pid},{secid},{mid},{eosid},0,0,0,0",
    ]


def _uniform_axis(low: float, high: float, target_size: float) -> list[float]:
    count = grid_count(high - low, target_size)
    step = (high - low) / count
    return [low + index * step for index in range(count + 1)]


def _open_end_segments(nid: Any, nx: int, ny: int, nz: int) -> list[tuple[int, int, int, int]]:
    segments: list[tuple[int, int, int, int]] = []
    for iz in range(nz):
        for iy in range(ny):
            segments.append((nid(0, iy, iz), nid(0, iy + 1, iz), nid(0, iy + 1, iz + 1), nid(0, iy, iz + 1)))
            segments.append((nid(nx, iy, iz), nid(nx, iy, iz + 1), nid(nx, iy + 1, iz + 1), nid(nx, iy + 1, iz)))
    return segments


def _probe_solid_ids_on_axes(
    x_axis: list[float],
    y_axis: list[float],
    z_axis: list[float],
    points: list[list[float]],
) -> list[int]:
    nx, ny, nz = len(x_axis) - 1, len(y_axis) - 1, len(z_axis) - 1

    def cell_index(axis: list[float], value: float) -> int:
        return min(len(axis) - 2, max(0, bisect_right(axis, value) - 1))

    result = {
        cell_index(z_axis, point[2]) * nx * ny
        + cell_index(y_axis, point[1]) * nx
        + cell_index(x_axis, point[0])
        + 1
        for point in points
    }
    return sorted(result)


def _coupling_lines(slave_part_id: int) -> list[str]:
    return [
        "*CONSTRAINED_LAGRANGE_IN_SOLID",
        "$#   slave    master     sstyp     mstyp     nquad     ctype     direc     mcoup",
        f"{slave_part_id},{ALE_MATERIAL_PART_SET_ID},1,0,4,4,2,0",
        "$#   start       end      pfac      fric    frcmin      norm   normtyp      damp",
        "0.0,0.0,0.1,0.0,0.3,0,0,0.1",
        "$#       k      hmin      hmax     ileak     pleak   lcidpor     nvent    iblock",
        "0.0,0.0,0.0,2,0.1,0,0,0",
    ]


def _append_node_set(lines: list[str], set_id: int, title: str, node_ids: list[int]) -> None:
    lines.extend(["*SET_NODE_LIST_TITLE", title, str(set_id)])
    for index in range(0, len(node_ids), 8):
        lines.append(",".join(str(value) for value in node_ids[index : index + 8]))


def _probe_solid_ids(
    domain_min: list[float],
    cell_size: list[float],
    counts: list[int],
    points: list[list[float]],
) -> list[int]:
    result: set[int] = set()
    nx, ny, nz = counts
    for point in points:
        indices = [
            min(counts[index] - 1, max(0, int((point[index] - domain_min[index]) / cell_size[index])))
            for index in range(3)
        ]
        ix, iy, iz = indices
        result.add(iz * nx * ny + iy * nx + ix + 1)
    return sorted(result)


def _outer_domain_segments(nid: Any, nx: int, ny: int, nz: int) -> list[tuple[int, int, int, int]]:
    segments: list[tuple[int, int, int, int]] = []
    for iz in range(nz):
        for iy in range(ny):
            segments.append((nid(0, iy, iz), nid(0, iy + 1, iz), nid(0, iy + 1, iz + 1), nid(0, iy, iz + 1)))
            segments.append((nid(nx, iy, iz), nid(nx, iy, iz + 1), nid(nx, iy + 1, iz + 1), nid(nx, iy + 1, iz)))
    for iz in range(nz):
        for ix in range(nx):
            segments.append((nid(ix, 0, iz), nid(ix, 0, iz + 1), nid(ix + 1, 0, iz + 1), nid(ix + 1, 0, iz)))
            segments.append((nid(ix, ny, iz), nid(ix + 1, ny, iz), nid(ix + 1, ny, iz + 1), nid(ix, ny, iz + 1)))
    for iy in range(ny):
        for ix in range(nx):
            segments.append((nid(ix, iy, 0), nid(ix + 1, iy, 0), nid(ix + 1, iy + 1, 0), nid(ix, iy + 1, 0)))
            segments.append((nid(ix, iy, nz), nid(ix, iy + 1, nz), nid(ix + 1, iy + 1, nz), nid(ix + 1, iy, nz)))
    return segments
