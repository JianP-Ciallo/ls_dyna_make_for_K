"""Build the same static workbench that the Python server serves."""
import subprocess
from pathlib import Path

from node_runtime import node_executable

ROOT = Path(__file__).resolve().parents[1]


def test_build_contains_workbench_and_its_unbundled_modules(tmp_path):
    output = tmp_path / "workbench build"
    result = subprocess.run(
        [str(node_executable()), str(ROOT / "web/scripts/build-workbench.mjs"), str(output)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    index = (output / "index.html").read_text(encoding="utf-8")
    assert 'id="refinedBlastWorkbenchRoot"' in index
    assert 'id="legacyWorkbenchRoot"' in index
    assert 'src="/app.js"' in index
    for asset in (
        "app.js", "styles.css", "phase17_editor.js",
        "refined_blast_workbench.js", "refined_blast_state.js",
        "refined_blast_persistence.js", "refined_blast_viewer.js",
        "vendor/three/three.module.min.js", "damage_assessment_demo.html",
        "blast_demo.html", "blast_demo_model.js", "blast_demo_worker.js",
        "blast_buildings.html", "blast_buildings.js", "blast_buildings.css",
        "blast_original_scenes.js", "blast_demo_presentation.js",
        "cpu_blast.html", "cpu_blast.css", "cpu_blast.js", "blast_demo_cache.js", "cpu_blast_catalog.css",
        "blast_panel_fracture.js", "blast_fracture_view.js",
        "blast_rebar_catalog.js", "blast_rebar_layout.js", "blast_rebar_bundles.js", "blast_rebar_coupling.js", "blast_rebar_view.js",
        "blast_local_rebar.js", "blast_local_rebar_view.js", "blast_damage_fields.js",
        "blast_powder.js", "blast_powder_view.js",
    ):
        assert (output / asset).is_file(), asset
    assert "React/Vite build entry" not in index
