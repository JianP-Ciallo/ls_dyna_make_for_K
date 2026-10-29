"""Stable public API for standalone damage assessment."""

from __future__ import annotations

import importlib.metadata

from . import __version__
from .adapters.contracts import ResultAdapter
from .contracts import AssessmentResult
from .pipeline import RESULT_SCHEMA, SNAPSHOT_SCHEMA, run_pipeline
from .rules import load_rule_pack, snapshot_rule_pack
from .schema import REQUEST_SCHEMA_V1


def capabilities() -> dict[str, object]:
    try:
        lasso_version = importlib.metadata.version("lasso-python")
    except importlib.metadata.PackageNotFoundError:
        lasso_version = None
    try:
        numpy_version = importlib.metadata.version("numpy")
    except importlib.metadata.PackageNotFoundError:
        numpy_version = None
    rule_packs = []
    for pack_id in ("building_research_reference@1", "ground_research_reference@1"):
        pack = load_rule_pack(pack_id)
        snapshot = snapshot_rule_pack(pack)
        rule_packs.append(
            {
                "id": pack.pack_id,
                "subject": pack.subject,
                "sha256": snapshot.sha256,
                "formal_eligible": pack.formal_eligible,
            }
        )
    return {
        "package": {"name": "blast-damage-assessment", "version": __version__},
        "schemas": {
            "request": [REQUEST_SCHEMA_V1],
            "result": [RESULT_SCHEMA],
            "snapshot": [SNAPSHOT_SCHEMA],
            "semantics": ["blast_damage.model_semantics@1", "phase18.solver_blast.deck_manifest@1-4"],
        },
        "adapters": [{"id": "lsdyna_d3plot", "version": "1.0.0"}],
        "dependencies": {"lasso_python": lasso_version, "numpy": numpy_version},
        "rule_packs": rule_packs,
        "unit_systems": ["SI_m_s_kg_N_Pa"],
        "available_fields": [
            "node_displacement",
            "node_velocity",
            "solid_stress",
            "solid_effective_plastic_strain",
            "solid_history_variables",
            "solid_is_alive",
            "shell_stress",
            "shell_effective_plastic_strain",
            "shell_history_variables",
            "shell_is_alive",
            "shell_strain",
            "beam_axial_force",
            "beam_shear_force",
            "beam_is_alive",
        ],
    }


def assess(request: object, *, adapter: ResultAdapter | None = None) -> AssessmentResult:
    return run_pipeline(request, adapter=adapter)
