from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict
from pathlib import Path

import pytest

from lsprepost_mcp.refined_building.solver_blast import (
    build_solver_blast_scene,
    inspect_solver_blast_deck,
    evaluate_solver_blast_run,
    write_solver_blast_deck,
)
from test_phase18_solver_blast_scene import COMMERCIAL, _config, _model


SURFACE_CLASS_ORDER = (
    "external_air_exposed",
    "internal_air_exposed",
    "soil_contact",
    "sealed_internal",
    "structural_connection",
)
SURFACE_TOPOLOGY_MANIFEST_KEYS = {
    "schema_version",
    "fingerprint",
    "counts",
    "boundary_face_count",
    "unclassified_count",
    "multiply_classified_count",
}
MESH_QUALITY_MANIFEST_KEYS = {
    "schema_version",
    "fingerprint",
    "solid_count",
    "shell_count",
    "beam_count",
    "minimum_corner_jacobian_m3",
    "maximum_aspect_ratio",
    "orphan_node_count",
    "duplicate_element_count",
    "solid_overlap_pair_count",
    "unresolved_overlap_candidate_count",
    "finding_count",
}


@pytest.fixture(scope="module")
def generated_model(tmp_path_factory) -> Path:
    directory = tmp_path_factory.mktemp("phase18-solver-blast-validation")
    scene = build_solver_blast_scene(_model(COMMERCIAL), _config())
    write_solver_blast_deck(scene, directory)
    return directory


def _copy_model(source: Path, target: Path) -> Path:
    shutil.copytree(source, target)
    return target


def _read_surface_topology_manifest(directory: Path) -> tuple[dict, dict]:
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "phase18.solver_blast.deck_manifest@4"
    surface_topology = manifest.get("surface_topology")
    assert isinstance(surface_topology, dict), (
        "deck_manifest@4 must contain the closed surface_topology evidence"
    )
    assert set(surface_topology) == SURFACE_TOPOLOGY_MANIFEST_KEYS
    return manifest, surface_topology


def _write_manifest(directory: Path, manifest: dict) -> None:
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )


def _rewrite_model(directory: Path, lines: list[str], *, update_manifest: bool) -> None:
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    (directory / "model.k").write_bytes(payload)
    if update_manifest:
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["model"]["sha256"] = hashlib.sha256(payload).hexdigest()
        manifest["model"]["byte_count"] = len(payload)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )


def _segment_set_member_bounds(lines: list[str], set_id: int) -> tuple[int, int]:
    for marker, row in enumerate(lines):
        if row != "*SET_SEGMENT_TITLE" or marker + 2 >= len(lines):
            continue
        identity = lines[marker + 2].split(",", 1)[0].strip()
        if identity != str(set_id):
            continue
        start = marker + 3
        end = start
        while end < len(lines) and not lines[end].startswith("*"):
            end += 1
        assert start < end, f"generated segment set {set_id} must be nonempty"
        return start, end
    raise AssertionError(f"generated deck is missing segment set {set_id}")


def _mutate_model(directory: Path, mutation: str) -> None:
    model_path = directory / "model.k"
    lines = model_path.read_text(encoding="utf-8").splitlines()
    update_manifest = True
    if mutation == "missing_air_eos":
        lines[lines.index("*EOS_LINEAR_POLYNOMIAL")] = "*EOS_LINEAR_POLYNOMIAL_REMOVED"
    elif mutation == "missing_tnt_jwl":
        lines[lines.index("*EOS_JWL")] = "*EOS_JWL_REMOVED"
    elif mutation == "missing_vacuum_material":
        marker = "*MAT_ALE_VACUUM_TITLE"
        assert marker in lines, "generated deck must publish the vacuum material"
        start = lines.index(marker)
        end = start + 1
        while end < len(lines) and not lines[end].startswith("*"):
            end += 1
        del lines[start:end]
    elif mutation == "buffer_retyped_as_air":
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        part_by_role = {
            str(role): int(part_id) for role, part_id in manifest["part_ids"]
        }
        assert "ale_coupling_buffer" in part_by_role
        assert "ale_active_air_domain" in part_by_role
        buffer_part_id = part_by_role["ale_coupling_buffer"]
        air_part_id = part_by_role["ale_active_air_domain"]
        marker = lines.index("*ELEMENT_SOLID")
        end = marker + 1
        while end < len(lines) and not lines[end].startswith("*"):
            end += 1
        retyped = 0
        for index in range(marker + 1, end):
            row = lines[index]
            if (
                len(row) >= 16
                and row[:8].strip().isdigit()
                and row[8:16].strip() == str(buffer_part_id)
            ):
                lines[index] = row[:8] + f"{air_part_id:>8}" + row[16:]
                retyped += 1
        assert retyped > 0
        manifest["ale_air_element_count"] += retyped
        manifest_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
    elif mutation == "empty_fsi_set":
        title = lines.index("Physical building and exposed ground ALE FSI")
        first_segment = title + 2
        end = first_segment
        while end < len(lines) and not lines[end].startswith("*"):
            end += 1
        del lines[first_segment:end]
    elif mutation == "moved_charge_into_soil":
        detonation = lines.index("*INITIAL_DETONATION")
        values = lines[detonation + 2].split(",")
        values[1:4] = ["0", "0", "-0.5"]
        lines[detonation + 2] = ",".join(values)
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["charge"]["position_m"] = [0.0, 0.0, -0.5]
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
    elif mutation == "dangling_part":
        marker = lines.index("*ELEMENT_SOLID")
        element_row = next(
            index
            for index in range(marker + 1, len(lines))
            if lines[index].strip() and not lines[index].lstrip().startswith("$")
        )
        row = lines[element_row]
        lines[element_row] = row[:8] + f"{9_999_999:>8}" + row[16:]
    elif mutation == "inverted_tnt_hex":
        element_row = next(
            index
            for index, row in enumerate(lines)
            if len(row) >= 32
            and row[:8].strip().isdigit()
            and row[8:16].strip() == "9002"
        )
        fields = [lines[element_row][index:index + 8] for index in range(0, 80, 8)]
        fields[2], fields[3] = fields[3], fields[2]
        lines[element_row] = "".join(fields)
    elif mutation == "wrong_ale_essential_boundary_modes":
        marker = lines.index("*ALE_ESSENTIAL_BOUNDARY")
        boundary_row = marker + 2
        assert lines[boundary_row] == "92004,2,2,0"
        lines[boundary_row] = "92004,1,1,0"
    elif mutation == "ale_master_set_missing_buffer":
        title = lines.index("ALE active air, TNT, and coupling-buffer material parts")
        member_row = title + 2
        assert lines[member_row] == "9001,9002,9003"
        lines[member_row] = "9001,9002"
    elif mutation == "ale_multi_material_group_missing_buffer":
        marker = lines.index("*ALE_MULTI-MATERIAL_GROUP")
        end = marker + 1
        while end < len(lines) and not lines[end].startswith("*"):
            end += 1
        buffer_rows = [
            index for index in range(marker + 1, end) if lines[index] == "9003,1"
        ]
        assert len(buffer_rows) == 1
        del lines[buffer_rows[0]]
    elif mutation == "ale_side_boundary_inward_winding":
        start, _end = _segment_set_member_bounds(lines, 92_002)
        face = lines[start].split(",")
        assert len(face) == 4 and len(set(face)) == 4
        lines[start] = ",".join((face[0], face[3], face[2], face[1]))
    elif mutation == "ale_top_boundary_missing_face":
        start, end = _segment_set_member_bounds(lines, 92_003)
        assert end - start > 1
        del lines[start]
    elif mutation == "ale_bottom_boundary_duplicate_replaces_face":
        start, end = _segment_set_member_bounds(lines, 92_004)
        assert end - start > 1 and lines[start] != lines[end - 1]
        lines[end - 1] = lines[start]
    elif mutation == "legacy_single_row_control_ale":
        marker = lines.index("*CONTROL_ALE")
        end = marker + 1
        while end < len(lines) and not lines[end].startswith("*"):
            end += 1
        assert lines[marker + 2] == "-1,1,2,-1.0,0.0,0.0,0.0,0.0"
        assert lines[marker + 4] == "0.0,1.0e20,1.0,1.0e-6,0,0,101325.0,0"
        lines[marker + 1:end] = [
            "$#     dct      nadv      meth      afac",
            "0,1,2,-1",
        ]
    elif mutation == "duplicate_ale_bottom_segment_set":
        start, end = _segment_set_member_bounds(lines, 92_004)
        block_start = start - 3
        assert lines[block_start] == "*SET_SEGMENT_TITLE"
        assert lines[block_start + 2].split(",", 1)[0] == "92004"
        end_card = lines.index("*END")
        assert end <= end_card
        lines[end_card:end_card] = lines[block_start:end]
    elif mutation == "changed_model_hash":
        lines.insert(1, "$ tampered without manifest update")
        update_manifest = False
    else:
        raise AssertionError(f"unknown mutation: {mutation}")
    _rewrite_model(directory, lines, update_manifest=update_manifest)


def test_untampered_solver_deck_passes_persisted_closure(generated_model: Path) -> None:
    report = inspect_solver_blast_deck(generated_model)

    assert report.ok is True
    assert report.findings == ()
    assert report.fsi_segment_count > 0
    assert report.ale_element_count > 0


def test_persisted_mesh_quality_is_closed_clean_and_model_anchored(
    generated_model: Path,
) -> None:
    manifest = json.loads(
        (generated_model / "manifest.json").read_text(encoding="utf-8")
    )
    quality = manifest["mesh_quality"]
    model_lines = (generated_model / "model.k").read_text(
        encoding="utf-8"
    ).splitlines()

    assert set(quality) == MESH_QUALITY_MANIFEST_KEYS
    assert quality["schema_version"] == "phase18.solver_blast.mesh_quality@1"
    assert quality["finding_count"] == 0
    assert quality["orphan_node_count"] == 0
    assert quality["duplicate_element_count"] == 0
    assert quality["solid_overlap_pair_count"] == 0
    assert quality["unresolved_overlap_candidate_count"] == 0
    assert quality["minimum_corner_jacobian_m3"] > 0.0
    assert quality["maximum_aspect_ratio"] >= 1.0
    assert "$P18MQ=" + quality["fingerprint"] in model_lines


@pytest.mark.parametrize(
    "mutation",
    ["missing_key", "extra_key", "forged_fingerprint", "nonzero_finding"],
)
def test_persisted_mesh_quality_tampering_fails_closed(
    generated_model: Path,
    tmp_path: Path,
    mutation: str,
) -> None:
    directory = _copy_model(generated_model, tmp_path / f"mesh-quality-{mutation}")
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    quality = manifest["mesh_quality"]
    if mutation == "missing_key":
        del quality["minimum_corner_jacobian_m3"]
    elif mutation == "extra_key":
        quality["unexpected"] = 0
    elif mutation == "forged_fingerprint":
        quality["fingerprint"] = "0" * 64
    elif mutation == "nonzero_finding":
        quality["finding_count"] = 1
    else:
        raise AssertionError(mutation)
    _write_manifest(directory, manifest)

    report = inspect_solver_blast_deck(directory)

    assert report.ok is False
    assert report.findings


def test_manifest_charge_position_accepts_only_r12_rendering_roundoff(
    generated_model: Path,
    tmp_path: Path,
) -> None:
    directory = _copy_model(generated_model, tmp_path / "rounded-position")
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["charge"]["position_m"][2] += 2.0e-15
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )

    report = inspect_solver_blast_deck(directory)

    assert report.ok is True
    assert report.findings == ()


def test_manifest_nested_schema_fails_closed_without_leaking_key_error(
    generated_model: Path,
    tmp_path: Path,
) -> None:
    directory = _copy_model(generated_model, tmp_path / "broken-manifest")
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["model"]["sha256"]
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    report = inspect_solver_blast_deck(directory)

    assert report.ok is False
    assert report.findings


def test_unexpected_keyword_is_rejected_even_when_manifest_hash_is_updated(
    generated_model: Path,
    tmp_path: Path,
) -> None:
    directory = _copy_model(generated_model, tmp_path / "unknown-card")
    lines = (directory / "model.k").read_text(encoding="utf-8").splitlines()
    lines[-1:-1] = ["*CONTROL_SPH", "0,0,0,0,0,0,0,0"]
    _rewrite_model(directory, lines, update_manifest=True)

    report = inspect_solver_blast_deck(directory)

    assert report.ok is False
    assert any(row.code == "keyword_vocabulary" for row in report.findings)


def test_manifest_tnt_mass_must_match_rendered_charge_solids(
    generated_model: Path,
    tmp_path: Path,
) -> None:
    directory = _copy_model(generated_model, tmp_path / "wrong-mass")
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["charge"]["mass_kg"] = 99.0
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    report = inspect_solver_blast_deck(directory)

    assert report.ok is False
    assert any(row.code == "charge_mass_volume" for row in report.findings)


def test_manifest_material_review_status_cannot_be_forged(
    generated_model: Path,
    tmp_path: Path,
) -> None:
    directory = _copy_model(generated_model, tmp_path / "forged-material-status")
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["materials"]["validation_status"] = "engineering_validated"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    report = inspect_solver_blast_deck(directory)

    assert report.ok is False
    assert report.findings


def test_manifest_part_identity_rows_must_be_unique(
    generated_model: Path,
    tmp_path: Path,
) -> None:
    directory = _copy_model(generated_model, tmp_path / "duplicate-part-row")
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["part_ids"].append(manifest["part_ids"][0])
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    report = inspect_solver_blast_deck(directory)

    assert report.ok is False
    assert report.findings


def test_persisted_surface_topology_counts_close_against_fsi_and_boundary_faces(
    generated_model: Path,
) -> None:
    manifest, surface_topology = _read_surface_topology_manifest(generated_model)
    counts = surface_topology["counts"]

    assert [row[0] for row in counts] == list(SURFACE_CLASS_ORDER)
    assert all(
        len(row) == 2
        and isinstance(row[1], int)
        and not isinstance(row[1], bool)
        and row[1] >= 0
        for row in counts
    )
    count_by_class = {surface_class: count for surface_class, count in counts}
    assert sum(count_by_class.values()) == surface_topology["boundary_face_count"]
    assert surface_topology["unclassified_count"] == 0
    assert surface_topology["multiply_classified_count"] == 0
    assert manifest["fsi_slave_segment_count"] == (
        count_by_class["external_air_exposed"]
        + count_by_class["internal_air_exposed"]
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_nested_key",
        "extra_nested_key",
        "wrong_nested_schema",
        "unknown_surface_class",
        "boolean_surface_count",
        "negative_surface_count",
        "surface_count_not_closed",
        "exposed_count_not_closed_against_fsi",
        "forged_well_formed_fingerprint",
    ],
)
def test_persisted_surface_topology_manifest_tampering_fails_closed(
    generated_model: Path,
    tmp_path: Path,
    mutation: str,
) -> None:
    directory = _copy_model(generated_model, tmp_path / mutation)
    manifest, surface_topology = _read_surface_topology_manifest(directory)
    counts = surface_topology["counts"]

    if mutation == "missing_nested_key":
        del surface_topology["boundary_face_count"]
    elif mutation == "extra_nested_key":
        surface_topology["unexpected"] = 0
    elif mutation == "wrong_nested_schema":
        surface_topology["schema_version"] = "phase18.solver_blast.surface_topology@2"
    elif mutation == "unknown_surface_class":
        counts[0][0] = "unknown_air_exposed"
    elif mutation == "boolean_surface_count":
        counts[0][1] = True
    elif mutation == "negative_surface_count":
        counts[0][1] = -1
    elif mutation == "surface_count_not_closed":
        surface_topology["boundary_face_count"] += 1
    elif mutation == "exposed_count_not_closed_against_fsi":
        counts[0][1] += 1
        counts[2][1] -= 1
        assert counts[2][1] >= 0
    elif mutation == "forged_well_formed_fingerprint":
        forged = "0" * 64
        if forged == surface_topology["fingerprint"]:
            forged = "f" * 64
        surface_topology["fingerprint"] = forged
    else:
        raise AssertionError(f"unknown mutation: {mutation}")
    _write_manifest(directory, manifest)

    report = inspect_solver_blast_deck(directory)

    assert report.ok is False
    assert report.findings


def test_persisted_inspector_rejects_legacy_surface_topology_manifest_version(
    generated_model: Path,
    tmp_path: Path,
) -> None:
    directory = _copy_model(generated_model, tmp_path / "legacy-manifest-version")
    manifest, _surface_topology = _read_surface_topology_manifest(directory)
    manifest["schema_version"] = "phase18.solver_blast.deck_manifest@2"
    _write_manifest(directory, manifest)

    report = inspect_solver_blast_deck(directory)

    assert report.ok is False
    assert report.findings


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_air_eos",
        "missing_tnt_jwl",
        "missing_vacuum_material",
        "buffer_retyped_as_air",
        "empty_fsi_set",
        "moved_charge_into_soil",
        "dangling_part",
        "inverted_tnt_hex",
        "wrong_ale_essential_boundary_modes",
        "ale_master_set_missing_buffer",
        "ale_multi_material_group_missing_buffer",
        "ale_side_boundary_inward_winding",
        "ale_top_boundary_missing_face",
        "ale_bottom_boundary_duplicate_replaces_face",
        "legacy_single_row_control_ale",
        "duplicate_ale_bottom_segment_set",
        "changed_model_hash",
    ],
)
def test_persisted_deck_tampering_fails_closed(
    generated_model: Path,
    tmp_path: Path,
    mutation: str,
) -> None:
    directory = _copy_model(generated_model, tmp_path / mutation)
    _mutate_model(directory, mutation)

    report = inspect_solver_blast_deck(directory)

    assert report.ok is False
    assert report.findings


def _write_successful_run(directory: Path) -> None:
    directory.mkdir()
    (directory / "d3hsp").write_text(
        """
 FSI Interface ID .............. 1
 number of slave segments for coupling ........ 12
 kinetic energy................. 1.00000E+00
 internal energy................ 2.00000E+00
 hourglass energy .............. 1.00000E-03
 total energy................... 3.00100E+00
 total energy / initial energy.. 1.00000E+00
 Problem time       =    1.0000E-03
 N o r m a l    t e r m i n a t i o n
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (directory / "messag").write_text(
        "Problem time = 1.0000E-03\nN o r m a l    t e r m i n a t i o n\n",
        encoding="utf-8",
    )
    (directory / "glstat").write_text(
        """
 time........................... 0.00000E+00
 kinetic energy................. 0.00000E+00
 internal energy................ 1.00000E+00
 hourglass energy .............. 0.00000E+00
 total energy................... 1.00000E+00
 total energy / initial energy.. 1.00000E+00
 time........................... 1.00000E-03
 kinetic energy................. 1.00000E+00
 internal energy................ 2.00000E+00
 hourglass energy .............. 1.00000E-03
 total energy................... 3.00100E+00
 total energy / initial energy.. 1.00000E+00
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (directory / "dbfsi").write_text(
        """
 Fluid-structure interaction output
 Number of surfaces: 1
 time= 0.00000E+00
 1 1.01325E+05 0.0 0.0 0.0 0.0
   0.0 0.0 0.0 0.0 0.0 0.0
 time= 2.00000E-04
 1 2.01325E+05 0.0 0.0 0.0 0.0
   0.0 0.0 0.0 0.0 0.0 0.0
 time= 4.00000E-04
 1 3.01325E+05 1.0E+04 0.0 0.0 0.0
   0.0 0.0 0.0 0.0 0.0 0.0
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (directory / "matsum").write_text(
        "time = 0.00000E+00\ninternal energy = 1.00000E+00\n"
        "time = 1.00000E-03\ninternal energy = 2.00000E+00\n",
        encoding="utf-8",
    )
    (directory / "alevfrc").write_text(
        "time = 0.00000E+00 air_fraction = 1.00000E+00\n"
        "time = 1.00000E-03 air_fraction = 9.00000E-01\n",
        encoding="utf-8",
    )


def test_run_requires_real_tnt_air_structure_causality(
    generated_model: Path,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_successful_run(run_dir)

    report = evaluate_solver_blast_run(generated_model, run_dir)

    assert report.ok is True
    assert report.acceptance_mode == "configured_short_solve_no_error"
    assert report.propagation_observed is True
    assert report.normal_termination is True
    assert report.final_problem_time_s >= inspect_solver_blast_deck(
        generated_model
    ).termination_time_s
    assert report.fsi_slave_segment_count > 0
    assert report.air_peak_pressure_pa > 0.0
    assert report.building_peak_response > report.response_noise_floor
    assert (
        report.source_time_s
        <= report.air_arrival_time_s
        <= report.building_arrival_time_s
    )


def test_run_rejects_invalid_coupled_response_path(
    generated_model: Path,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_successful_run(run_dir)
    (run_dir / "dbfsi").unlink()
    (run_dir / "dbfsi").mkdir()

    report = evaluate_solver_blast_run(generated_model, run_dir)

    assert report.ok is False
    assert any(row.code == "invalid:dbfsi" for row in report.findings)
    json.dumps(asdict(report), allow_nan=False)


def test_run_uses_dbfsi_pressure_without_treating_ale_initialization_as_output(
    generated_model: Path,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_successful_run(run_dir)
    (run_dir / "alevfrc").unlink()

    report = evaluate_solver_blast_run(generated_model, run_dir)

    assert report.ok is True
    assert report.air_peak_pressure_pa > 0.0


def test_run_accepts_real_r12_timing_labels_and_glstat_energy_authority(
    generated_model: Path,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_successful_run(run_dir)
    d3hsp = run_dir / "d3hsp"
    d3hsp.write_text(
        """
 FSI Interface ID .............. 1
 number of slave segments for coupling ........ 12
 flag to check for NaN in force/moment arrays...       0
 eq.1: yes (error termination if detected)
 Problem time       =    1.0002E-03
 CPU time per zone cycle = 2699.234 nanoseconds
 N o r m a l    t e r m i n a t i o n
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = evaluate_solver_blast_run(generated_model, run_dir)

    assert report.ok is True
    assert not any(row.code == "fatal_output" for row in report.findings)
    assert not any(row.code == "finite_energy" for row in report.findings)


def test_run_rejects_numeric_nonfinite_energy_value(
    generated_model: Path,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_successful_run(run_dir)
    glstat = run_dir / "glstat"
    glstat.write_text(
        glstat.read_text(encoding="utf-8").replace(
            "kinetic energy................. 1.00000E+00",
            "kinetic energy................. NaN",
        ),
        encoding="utf-8",
    )

    report = evaluate_solver_blast_run(generated_model, run_dir)

    assert report.ok is False
    assert any(row.code in {"fatal_output", "finite_energy"} for row in report.findings)


def test_run_accepts_short_no_error_without_requiring_propagation_response(
    generated_model: Path,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_successful_run(run_dir)
    (run_dir / "dbfsi").unlink()

    report = evaluate_solver_blast_run(generated_model, run_dir)

    assert report.ok is True
    assert report.propagation_observed is False
    assert report.air_arrival_time_s is None
    assert report.building_arrival_time_s is None


def test_run_rejects_numbered_r12_error_marker(
    generated_model: Path,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_successful_run(run_dir)
    with (run_dir / "messag").open("a", encoding="utf-8") as stream:
        stream.write("*** Error 10131 invalid keyword data\n")

    report = evaluate_solver_blast_run(generated_model, run_dir)

    assert report.ok is False
    assert any(row.code == "fatal_output" for row in report.findings)


def test_run_rejects_normal_solve_that_does_not_reach_configured_time(
    generated_model: Path,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_successful_run(run_dir)
    d3hsp = run_dir / "d3hsp"
    d3hsp.write_text(
        d3hsp.read_text(encoding="utf-8").replace(
            "Problem time       =    1.0000E-03",
            "Problem time       =    1.0000E-05",
        ),
        encoding="utf-8",
    )

    report = evaluate_solver_blast_run(generated_model, run_dir)

    assert report.ok is False
    assert any(row.code == "final_problem_time" for row in report.findings)
