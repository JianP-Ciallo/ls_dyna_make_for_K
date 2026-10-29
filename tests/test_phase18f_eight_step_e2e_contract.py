from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "tools" / "capture_refined_blast_eight_step.mjs"


def test_capture_script_covers_three_assets_and_all_eight_steps_without_generation() -> None:
    source = CAPTURE.read_text(encoding="utf-8")

    for asset_id in (
        "commercial_supermarket_detailed_building",
        "residential_community_detailed_building",
        "subway_entrance_detailed_building",
    ):
        assert asset_id in source
    assert "for (let step = 1; step <= 8; step += 1)" in source
    assert 'data-refined-section="${step}"' in source
    assert "page.screenshot" in source
    assert "visualAudit" in source
    assert "horizontalOverflow" in source
    assert 'page.locator("[data-refined-save]").click()' in source
    assert 'page.locator("[data-refined-preview]").click()' in source
    assert 'page.locator("[data-refined-validate]").last().click()' in source
    assert 'page.locator("[data-refined-generate]").click()' not in source


def test_capture_script_checks_mesh_ground_tnt_and_return_restore() -> None:
    source = CAPTURE.read_text(encoding="utf-8")

    assert "building.mesh_profile" in source
    assert "draft.load_provider.provider_input.air_cell_size_m" in source
    assert "draft.load_provider.provider_input.ground_cell_size_m" in source
    assert "draft.load_provider.provider_input.charge_position_m" in source
    assert "restoredAsset" in source
    assert "restoredProvider" in source
    assert "acceptance.json" in source


def test_capture_script_keeps_subway_tnt_above_the_real_grade() -> None:
    source = CAPTURE.read_text(encoding="utf-8")

    subway = source.split('assetId: "subway_entrance_detailed_building"', 1)[1]
    subway = subway.split("},", 1)[0]
    assert 'tntPosition: ["-1.0", "1.0", "4.0"]' in subway
