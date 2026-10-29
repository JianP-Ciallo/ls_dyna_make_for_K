from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from test_phase18e_assembler import _artifact, _explicit_input, _lbe_input, _project

from lsprepost_mcp.refined_blast.assembler import RefinedBlastPackage
from lsprepost_mcp.refined_blast.service import (
    RefinedBlastService,
    validate_public_package,
)
from lsprepost_mcp.refined_blast.store import RefinedBlastStore


def _validate_package(package, artifact, store):
    stored = store.load_project("project-1")
    return validate_public_package(
        package,
        store,
        stored.project_id,
        artifact,
        expected_revision=stored.revision,
    )


def _two_scenario_project():
    artifact = _artifact()
    first_project = _project(artifact)
    first = first_project.scenario_set[0]
    second_input = _lbe_input(peak_pressure_pa=350_000.0)
    second = replace(
        first,
        scenario_id="scenario-2",
        load_provider={"provider_id": "lbe_segment", "provider_input": second_input},
    )
    return artifact, replace(first_project, scenario_set=(first, second))


def test_scenario_set_has_independent_deterministic_packages_and_result_ids(tmp_path):
    artifact, project = _two_scenario_project()
    with RefinedBlastStore(tmp_path) as store:
        stored = store.create(project)
        service = RefinedBlastService(store, stored.project_id, artifact)
        validation = service.validate(expected_revision=1)
        for warning in validation.warnings:
            service.acknowledge(validation, warning.finding_id)

        first = service.compile_scenario_set(expected_revision=1)
        second = service.compile_scenario_set(expected_revision=1)

    assert len(first.packages) == 2
    assert len({row.package_fingerprint for row in first.packages}) == 2
    assert len({row.result_id for row in first.packages}) == 2
    assert tuple(row.package_fingerprint for row in first.packages) == tuple(
        row.package_fingerprint for row in second.packages
    )
    assert tuple(row.result_id for row in first.packages) == tuple(
        row.result_id for row in second.packages
    )
    assert first.packages[0].package is not first.packages[1].package


def test_scenario_set_rejects_semantic_duplicates_even_with_different_ids(tmp_path):
    artifact = _artifact()
    project = _project(artifact)
    first = project.scenario_set[0]
    duplicate = replace(first, scenario_id="scenario-duplicate")
    duplicated = replace(project, scenario_set=(first, duplicate))

    with RefinedBlastStore(tmp_path) as store:
        stored = store.create(duplicated)
        service = RefinedBlastService(store, stored.project_id, artifact)
        with pytest.raises(ValueError, match="duplicate scenario"):
            service.compile_scenario_set(expected_revision=1)


def test_public_package_manifest_evidence_is_recomputed_not_trusted(tmp_path):
    artifact, store, valid = _generated_package(tmp_path)

    forged_manifest = dict(valid.manifest)
    forged_files = [dict(row) for row in forged_manifest["files"]]
    forged_files[0]["sha256"] = hashlib.sha256(b"forged").hexdigest()
    forged_manifest["files"] = forged_files
    forged = RefinedBlastPackage(
        files=valid.files,
        manifest=forged_manifest,
        symbol_to_numeric_id=valid.symbol_to_numeric_id,
        building_artifact_fingerprint=valid.building_artifact_fingerprint,
    )

    with pytest.raises(ValueError, match="manifest evidence"):
        _validate_package(forged, artifact, store)

    forged_counts_manifest = dict(valid.manifest)
    forged_counts = dict(forged_counts_manifest["rendered_counts"])
    forged_counts["building_nodes"] += 1
    forged_counts_manifest["rendered_counts"] = forged_counts
    forged_counts_package = RefinedBlastPackage(
        files=valid.files,
        manifest=forged_counts_manifest,
        symbol_to_numeric_id=valid.symbol_to_numeric_id,
        building_artifact_fingerprint=valid.building_artifact_fingerprint,
    )
    try:
        with pytest.raises(ValueError, match="rendered count"):
            _validate_package(forged_counts_package, artifact, store)
    finally:
        store.close()


def _repackage(package, *, files=None, manifest=None):
    files = dict(package.files if files is None else files)
    manifest = dict(package.manifest if manifest is None else manifest)
    manifest["files"] = tuple(
        {
            "path": path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "byte_count": len(content),
            "line_count": len(content.decode("utf-8").splitlines()),
        }
        for path, content in files.items()
    )
    return RefinedBlastPackage(
        files=files,
        manifest=manifest,
        symbol_to_numeric_id=package.symbol_to_numeric_id,
        building_artifact_fingerprint=package.building_artifact_fingerprint,
    )


def _generated_package(tmp_path, *, provider_id="lbe_segment", provider_input=None):
    artifact = _artifact()
    project = _project(
        artifact,
        provider_id=provider_id,
        provider_input=provider_input,
    )
    store = RefinedBlastStore(tmp_path)
    stored = store.create(project)
    service = RefinedBlastService(store, stored.project_id, artifact)
    validation = service.validate(expected_revision=1)
    for warning in validation.warnings:
        service.acknowledge(validation, warning.finding_id)
    return artifact, store, service.generate(expected_revision=1)


def test_public_package_parses_main_include_closure_and_building_bytes(tmp_path):
    artifact, store, package = _generated_package(tmp_path)
    try:
        files = dict(package.files)
        files["main.k"] = files["main.k"].replace(b"01_building.k", b"02_provider.k", 1)
        with pytest.raises(ValueError, match="INCLUDE"):
            _validate_package(_repackage(package, files=files), artifact, store)

        files = dict(package.files)
        files["01_building.k"] = files["01_building.k"].replace(b"1,0,0,0", b"999,0,0,0", 1)
        with pytest.raises(ValueError, match="building.*node"):
            _validate_package(_repackage(package, files=files), artifact, store)

        files = dict(package.files)
        files["01_building.k"] = files["01_building.k"].replace(
            b"1,0,0,0", b"999999999999999999999,0,0,0", 1
        )
        with pytest.raises(ValueError, match="bounded.*ID"):
            _validate_package(_repackage(package, files=files), artifact, store)
    finally:
        store.close()


def test_public_package_recomputes_explicit_provider_mesh_structure(tmp_path):
    artifact, store, package = _generated_package(
        tmp_path,
        provider_id="explicit_ale_fsi",
        provider_input=_explicit_input(),
    )
    try:
        files = dict(package.files)
        provider = files["02_provider.k"]
        node_marker = next(
            line for line in provider.splitlines() if line.startswith(b"10100007,")
        )
        changed = node_marker.replace(b",-3,", b",-2.5,", 1)
        files["02_provider.k"] = provider.replace(node_marker, changed, 1)
        with pytest.raises(ValueError, match="provider.*mesh"):
            _validate_package(_repackage(package, files=files), artifact, store)

        files = dict(package.files)
        provider = files["02_provider.k"]
        element_marker = next(
            line for line in provider.splitlines() if line.startswith(b"10100071,")
        )
        fields = element_marker.split(b",")
        fields[-1], fields[-2] = fields[-2], fields[-1]
        files["02_provider.k"] = provider.replace(
            element_marker, b",".join(fields), 1
        )
        with pytest.raises(ValueError, match="provider.*mesh"):
            _validate_package(_repackage(package, files=files), artifact, store)
    finally:
        store.close()


def test_rendered_count_schema_is_closed_and_preview_compares_every_metric(tmp_path):
    artifact, store, package = _generated_package(tmp_path)
    try:
        for mutation in ("unknown", "missing", "fsi"):
            manifest = dict(package.manifest)
            counts = dict(manifest["rendered_counts"])
            if mutation == "unknown":
                counts["mystery"] = 0
            elif mutation == "missing":
                counts.pop("provider_fsi_faces")
            else:
                counts["provider_fsi_faces"] += 1
            manifest["rendered_counts"] = counts
            with pytest.raises(ValueError, match="rendered count"):
                _validate_package(
                    _repackage(package, manifest=manifest), artifact, store
                )
    finally:
        store.close()


def test_public_package_rejects_forged_provider_fingerprint_against_store(tmp_path):
    artifact, store, package = _generated_package(tmp_path)
    try:
        manifest = dict(package.manifest)
        manifest["provider_fingerprint"] = "0" * 64
        with pytest.raises(ValueError, match="canonical"):
            _validate_package(
                _repackage(package, manifest=manifest), artifact, store
            )
    finally:
        store.close()


def test_public_package_rejects_unknown_keyword_card_even_when_rehashed(tmp_path):
    artifact, store, package = _generated_package(tmp_path)
    try:
        files = dict(package.files)
        files["01_building.k"] += b"*PART\n1\n"
        with pytest.raises(ValueError, match="keyword|canonical"):
            _validate_package(_repackage(package, files=files), artifact, store)
    finally:
        store.close()


def test_public_package_rejects_deleted_control_include_even_when_reclosed(tmp_path):
    artifact, store, package = _generated_package(tmp_path)
    try:
        files = dict(package.files)
        files["main.k"] = files["main.k"].replace(
            b"*INCLUDE\n80_controls.k\n", b"", 1
        )
        files.pop("80_controls.k")
        manifest = dict(package.manifest)
        manifest["include_order"] = tuple(
            path for path in manifest["include_order"] if path != "80_controls.k"
        )
        with pytest.raises(ValueError, match="control|canonical"):
            _validate_package(
                _repackage(package, files=files, manifest=manifest),
                artifact,
                store,
            )
    finally:
        store.close()
