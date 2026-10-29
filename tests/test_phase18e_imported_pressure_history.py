from __future__ import annotations

import copy
import math
import sys
from dataclasses import FrozenInstanceError

import pytest

from lsprepost_mcp.refined_blast.providers import ProviderContext
from lsprepost_mcp.refined_building.compiler import compile_refined_building
from lsprepost_mcp.refined_building.contracts import default_building_definition


@pytest.fixture(scope="module")
def detailed_artifact():
    value = default_building_definition(structural_system="rc_box")
    value["spaces"] = [
        {
            "id": "room_1",
            "level_id": "level_1",
            "kind": "room",
            "bounds_m": [0.25, 0.25, 0.25, 5.75, 5.75, 2.75],
        }
    ]
    value["openings"] = [
        {
            "id": "door_external",
            "kind": "door",
            "bounds_m": [0.0, 2.5, 0.25, 0.25, 3.5, 2.25],
            "connects": ["room_1", "exterior"],
        }
    ]
    value["structural_system"]["parameters"] = {
        "generation_mode": "concrete_only",
        "box_thickness_m": 0.25,
        "mesh_size_m": 0.5,
    }
    return compile_refined_building(value)


def pressure_context(artifact, *, kind: str = "external") -> ProviderContext:
    return ProviderContext.from_artifact(artifact, scenario_kind=kind)


def valid_history_input(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "imported_pressure_history@1",
        "unit_system": "SI_m_s_kg_N_Pa",
        "source": {
            "schema_version": "imported_pressure_history.source@1",
            "source_id": "history-1",
            "source_name": "test-history",
            "form": "structured_rows",
            "rows": [[0.0, 0.0], [100.0, 2.0]],
        },
        "units": {
            "schema_version": "imported_pressure_history.units@1",
            "time_unit": "ms",
            "pressure_unit": "kPa",
        },
        "curve": {
            "schema_version": "imported_pressure_history.curve@1",
            "interpolation": "linear",
            "scale": 1.0,
        },
        "mapping": {
            "schema_version": "imported_pressure_history.mapping@1",
            "surface_category": "exterior_surfaces",
            "target_face_ids": [],
        },
        "budgets": {
            "schema_version": "imported_pressure_history.budgets@1",
            "max_input_bytes": 4096,
            "max_row_count": 100,
            "max_target_surface_count": 1000,
        },
    }
    value.update(overrides)
    return value


def test_imported_rows_compile_to_normalized_si_and_record_auditable_hashes(detailed_artifact):
    from lsprepost_mcp.refined_blast.providers.imported_pressure_history import (
        ImportedPressureHistoryProvider,
    )

    context = pressure_context(detailed_artifact)
    fragment = ImportedPressureHistoryProvider().compile(valid_history_input(), context)

    assert fragment.provider_id == "imported_pressure_history"
    assert fragment.manifest["normalized_curve_si"] == ((0.0, 0.0), (0.1, 2000.0))
    evidence = fragment.evidence[0].claims
    assert len(evidence["source_sha256"]) == 64
    assert len(evidence["normalized_curve_sha256"]) == 64
    assert fragment.fsi_face_ids == tuple(
        sorted(row["face_id"] for row in detailed_artifact.surface_catalog["exterior_surfaces"])
    )
    assert fragment.required_ids <= context.available_ids | fragment.declared_ids
    assert fragment.manifest["solver_ready"] is False
    assert fragment.manifest["requires_project_review"] is True
    assert fragment.manifest["engineering_validated"] is False


def test_imported_pressure_declares_closed_source_space_and_legacy_external_migrates(
    detailed_artifact,
):
    from lsprepost_mcp.refined_blast.providers.imported_pressure_history import (
        ImportedPressureHistoryProvider,
    )

    provider = ImportedPressureHistoryProvider()
    legacy = provider.normalize(valid_history_input())
    assert legacy["schema_version"] == "imported_pressure_history@2"
    assert legacy["source"]["source_space_id"] == "exterior"

    current = valid_history_input()
    current["schema_version"] = "imported_pressure_history@2"
    current["source"]["schema_version"] = "imported_pressure_history.source@2"
    current["source"]["source_space_id"] = "exterior"
    fragment = provider.compile(current, pressure_context(detailed_artifact))
    source_space = next(
        row for row in fragment.evidence if row.evidence_kind == "provider_source_space"
    )
    assert source_space.claims["source_space_id"] == "exterior"
    assert source_space.claims["source_declared_id"] == (
        "imported_pressure_history:source:history-1"
    )

    mismatch = copy.deepcopy(current)
    mismatch["source"]["source_space_id"] = "room_1"
    with pytest.raises(ValueError, match="source_space_id.*external"):
        provider.compile(mismatch, pressure_context(detailed_artifact))


def test_imported_utf8_csv_bytes_are_decoded_without_path_access(detailed_artifact):
    from lsprepost_mcp.refined_blast.providers.imported_pressure_history import (
        ImportedPressureHistoryProvider,
    )

    raw = valid_history_input()
    raw["source"] = {
        "schema_version": "imported_pressure_history.source@1",
        "source_id": "history-2",
        "source_name": "observed.csv",
        "form": "utf8_csv_bytes",
        "bytes": b"0,0\n0.1,2500\n",
    }
    raw["units"]["time_unit"] = "s"
    raw["units"]["pressure_unit"] = "Pa"
    fragment = ImportedPressureHistoryProvider().compile(raw, pressure_context(detailed_artifact))

    assert fragment.manifest["normalized_curve_si"] == ((0.0, 0.0), (0.1, 2500.0))
    assert fragment.manifest["source"]["form"] == "utf8_csv_bytes"


def test_structured_source_hash_preserves_declared_original_rows(detailed_artifact):
    from lsprepost_mcp.refined_blast.providers.imported_pressure_history import (
        ImportedPressureHistoryProvider,
    )

    provider = ImportedPressureHistoryProvider()
    first = valid_history_input()
    second = valid_history_input()
    second["source"]["rows"] = [[0, 0], [100, 2]]
    first_fragment = provider.compile(first, pressure_context(detailed_artifact))
    second_fragment = provider.compile(second, pressure_context(detailed_artifact))

    assert first_fragment.manifest["normalized_curve_si"] == second_fragment.manifest[
        "normalized_curve_si"
    ]
    assert first_fragment.evidence[0].claims["source_sha256"] != second_fragment.evidence[0].claims[
        "source_sha256"
    ]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([], "must not be empty"),
        ([[0.0, 0.0], [0.1, math.nan]], "finite number"),
        ([[0.0, 0.0], [0.1, math.inf]], "finite number"),
        ([[0.0, 0.0], [0.1, 1.0], [0.1, 2.0]], "strictly increasing"),
    ],
)
def test_curve_rows_fail_closed_on_invalid_values(rows, message, detailed_artifact):
    from lsprepost_mcp.refined_blast.providers.imported_pressure_history import (
        ImportedPressureHistoryProvider,
    )

    raw = valid_history_input()
    raw["source"]["rows"] = rows
    with pytest.raises(ValueError, match=message):
        ImportedPressureHistoryProvider().compile(raw, pressure_context(detailed_artifact))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw["curve"].update(scale=-0.01), "scale"),
        (lambda raw: raw["units"].update(time_unit="fortnight"), "time_unit"),
        (lambda raw: raw["source"].update(source_id="../history"), "safe identifier"),
        (lambda raw: raw["source"].update(source_name="history/one.csv"), "safe identifier"),
        (lambda raw: raw["curve"].update(scale=True), "finite number"),
        (lambda raw: raw["source"].update(path="C:/unsafe.csv"), "unknown field"),
    ],
)
def test_closed_schema_units_and_source_tokens_fail_closed(mutate, message, detailed_artifact):
    from lsprepost_mcp.refined_blast.providers.imported_pressure_history import (
        ImportedPressureHistoryProvider,
    )

    raw = valid_history_input()
    mutate(raw)
    with pytest.raises(ValueError, match=message):
        ImportedPressureHistoryProvider().compile(raw, pressure_context(detailed_artifact))


def test_budgets_and_surface_mapping_are_checked_before_fragment_allocation(detailed_artifact):
    from lsprepost_mcp.refined_blast.providers.imported_pressure_history import (
        ImportedPressureHistoryProvider,
    )

    provider = ImportedPressureHistoryProvider()
    context = pressure_context(detailed_artifact)
    raw = valid_history_input()
    raw["budgets"]["max_row_count"] = 1
    with pytest.raises(ValueError, match="row count budget"):
        provider.compile(raw, context)

    raw = valid_history_input()
    raw["budgets"]["max_input_bytes"] = 1
    with pytest.raises(ValueError, match="input byte budget"):
        provider.compile(raw, context)

    raw = valid_history_input()
    raw["mapping"]["target_face_ids"] = [
        detailed_artifact.surface_catalog["interior_cavity_surfaces"][0]["face_id"]
    ]
    with pytest.raises(ValueError, match="surface category"):
        provider.compile(raw, context)

    raw = valid_history_input()
    face_id = detailed_artifact.surface_catalog["exterior_surfaces"][0]["face_id"]
    raw["mapping"]["target_face_ids"] = [face_id, face_id]
    with pytest.raises(ValueError, match="duplicate"):
        provider.compile(raw, context)


def test_fragment_is_deterministic_deeply_immutable_and_registry_bound(detailed_artifact):
    from lsprepost_mcp.refined_blast import get_load_provider
    from lsprepost_mcp.refined_blast.providers.imported_pressure_history import (
        ImportedPressureHistoryProvider,
    )

    provider = ImportedPressureHistoryProvider()
    context = pressure_context(detailed_artifact)
    first = provider.compile(valid_history_input(), context)
    second = provider.compile(valid_history_input(), context)
    assert first.fingerprint == second.fingerprint
    assert isinstance(get_load_provider("imported_pressure_history"), ImportedPressureHistoryProvider)
    with pytest.raises(TypeError):
        first.manifest["solver_ready"] = True
    with pytest.raises(TypeError):
        first.evidence[0].claims["source_sha256"] = "changed"
    with pytest.raises(FrozenInstanceError):
        first.provider_id = "changed"


def test_context_catalog_tampering_is_rejected_against_current_mesh(detailed_artifact):
    from lsprepost_mcp.refined_blast.providers.imported_pressure_history import (
        ImportedPressureHistoryProvider,
    )

    context = pressure_context(detailed_artifact)
    catalog = {
        category: [dict(row) for row in rows] if isinstance(rows, tuple) else rows
        for category, rows in context.surface_catalog.items()
    }
    catalog["exterior_surfaces"][0]["centroid_m"] = [999.0, 999.0, 999.0]
    forged = type(context)(
        artifact=context.artifact,
        scenario_kind=context.scenario_kind,
        available_ids=context.available_ids,
        surface_catalog=catalog,
        topology=context.topology,
    )
    with pytest.raises(ValueError, match="does not match artifact|centroid"):
        ImportedPressureHistoryProvider().compile(valid_history_input(), forged)


def test_target_surface_must_reference_its_real_structural_element_and_oriented_face(
    detailed_artifact,
):
    from dataclasses import replace

    from lsprepost_mcp.refined_blast.providers.imported_pressure_history import (
        ImportedPressureHistoryProvider,
    )

    catalog = copy.deepcopy(detailed_artifact.surface_catalog)
    row = catalog["exterior_surfaces"][0]
    row["element_id"] = 999_999
    nonexistent_element_artifact = replace(detailed_artifact, surface_catalog=catalog)
    with pytest.raises(ValueError, match="element_id.*does not exist"):
        ImportedPressureHistoryProvider().compile(
            valid_history_input(), pressure_context(nonexistent_element_artifact)
        )

    catalog = copy.deepcopy(detailed_artifact.surface_catalog)
    row = catalog["exterior_surfaces"][0]
    row["node_ids"] = list(reversed(row["node_ids"]))
    row["normal"] = [-value for value in row["normal"]]
    reversed_face_artifact = replace(detailed_artifact, surface_catalog=catalog)
    with pytest.raises(ValueError, match="oriented boundary face"):
        ImportedPressureHistoryProvider().compile(
            valid_history_input(), pressure_context(reversed_face_artifact)
        )


def test_validate_converts_huge_integers_and_deep_rows_to_blocking_findings(detailed_artifact):
    from lsprepost_mcp.refined_blast.providers.imported_pressure_history import (
        ImportedPressureHistoryProvider,
    )

    provider = ImportedPressureHistoryProvider()
    context = pressure_context(detailed_artifact)
    huge_scale = valid_history_input()
    huge_scale["curve"]["scale"] = 10**100_000
    findings = provider.validate(huge_scale, context)
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert "finite number" in findings[0].message
    with pytest.raises(ValueError, match="finite number"):
        provider.compile(huge_scale, context)

    nested: object = 0.0
    for _ in range(200):
        nested = [nested]
    deep_rows = valid_history_input()
    deep_rows["source"]["rows"] = [[nested, 1.0]]
    findings = provider.validate(deep_rows, context)
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert "finite number" in findings[0].message


def test_input_and_automatic_catalog_budgets_fail_before_large_result_materialization(
    detailed_artifact,
):
    from lsprepost_mcp.refined_blast.providers.imported_pressure_history import (
        ImportedPressureHistoryProvider,
    )

    provider = ImportedPressureHistoryProvider()
    context = pressure_context(detailed_artifact)
    csv_over_budget = valid_history_input()
    csv_over_budget["source"] = {
        "schema_version": "imported_pressure_history.source@1",
        "source_id": "history-3",
        "source_name": "too-many.csv",
        "form": "utf8_csv_bytes",
        "bytes": b"0,0\n0.1,1\n",
    }
    csv_over_budget["units"]["time_unit"] = "s"
    csv_over_budget["units"]["pressure_unit"] = "Pa"
    csv_over_budget["budgets"]["max_row_count"] = 1
    with pytest.raises(ValueError, match="row count budget"):
        provider.compile(csv_over_budget, context)

    automatic_targets = valid_history_input()
    automatic_targets["budgets"]["max_target_surface_count"] = 1
    with pytest.raises(ValueError, match="target surface count budget"):
        provider.compile(automatic_targets, context)


def test_single_huge_structured_integer_fails_before_json_encoder_materializes_it(
    detailed_artifact, monkeypatch
):
    """Keep this independent of Python's optional decimal-int safety cap."""

    from lsprepost_mcp.refined_blast.providers import imported_pressure_history as module

    provider = module.ImportedPressureHistoryProvider()
    raw = valid_history_input()
    raw["source"]["rows"] = [[10**100_000, 1.0]]
    context = pressure_context(detailed_artifact)
    previous_limit = sys.get_int_max_str_digits()
    try:
        sys.set_int_max_str_digits(0)
        monkeypatch.setattr(
            module.json.JSONEncoder,
            "iterencode",
            lambda *_args, **_kwargs: pytest.fail("JSON encoder must not see oversized integer"),
        )
        with pytest.raises(ValueError, match="integer decimal width"):
            provider.compile(raw, context)
    finally:
        sys.set_int_max_str_digits(previous_limit)


def test_integer_subclass_cannot_bypass_preencoding_width_guard(detailed_artifact, monkeypatch):
    from lsprepost_mcp.refined_blast.providers import imported_pressure_history as module

    class MisleadingInt(int):
        def bit_length(self) -> int:
            return 1

    provider = module.ImportedPressureHistoryProvider()
    raw = valid_history_input()
    raw["source"]["rows"] = [[MisleadingInt(10**100_000), 1.0]]
    context = pressure_context(detailed_artifact)
    previous_limit = sys.get_int_max_str_digits()
    try:
        sys.set_int_max_str_digits(0)
        monkeypatch.setattr(
            module.json.JSONEncoder,
            "iterencode",
            lambda *_args, **_kwargs: pytest.fail("JSON encoder must not see oversized integer subclass"),
        )
        with pytest.raises(ValueError, match="integer decimal width"):
            provider.compile(raw, context)
    finally:
        sys.set_int_max_str_digits(previous_limit)
