"""Monotone subject-level quality and assessability gates."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .contracts import GateState, Issue


_RANK = {GateState.FORMAL: 0, GateState.PROVISIONAL: 1, GateState.BLOCKED: 2}


@dataclass(frozen=True)
class CommonGateFacts:
    termination: str
    final_time: float | None
    target_time: float | None
    units_known: bool
    evidence_unchanged: bool
    request_schema_supported: bool
    legacy_inference: bool
    preliminary_materials: bool


@dataclass(frozen=True)
class BuildingGateFacts:
    common: CommonGateFacts
    identity_available: bool = True
    deformation_available: bool = True
    stress_available: bool = True
    strain_available: bool = True
    importance_explicit: bool = True


@dataclass(frozen=True)
class GroundGateFacts:
    common: CommonGateFacts
    identity_available: bool = True
    deformation_available: bool = True
    velocity_available: bool = True
    material_damage_available: bool = True


@dataclass(frozen=True)
class GateDecision:
    state: GateState
    issues: tuple[Issue, ...] = ()
    unavailable_metrics: tuple[str, ...] = ()
    residual_wording_allowed: bool = True

    def degrade(
        self,
        state: GateState,
        issue: Issue | None = None,
        *,
        unavailable_metric: str | None = None,
        residual_wording_allowed: bool | None = None,
    ) -> "GateDecision":
        resulting = self.state if _RANK[self.state] >= _RANK[state] else state
        issues = self.issues + ((issue,) if issue is not None else ())
        unavailable = list(self.unavailable_metrics)
        if unavailable_metric is not None and unavailable_metric not in unavailable:
            unavailable.append(unavailable_metric)
        residual = self.residual_wording_allowed
        if residual_wording_allowed is not None:
            residual = residual and residual_wording_allowed
        return replace(
            self,
            state=resulting,
            issues=issues,
            unavailable_metrics=tuple(unavailable),
            residual_wording_allowed=residual,
        )


def combine_gate_states(*states: GateState) -> GateState:
    if not states:
        raise ValueError("at least one gate state is required")
    return max(states, key=_RANK.__getitem__)


def _issue(
    code: str,
    message: str,
    state: GateState,
    subject_id: str,
    sources: tuple[str, ...],
    metrics: tuple[str, ...],
    remediation: str,
) -> Issue:
    return Issue(
        code,
        message,
        {
            "subject_id": subject_id,
            "gate_state": state.value,
            "source_evidence_ids": sources,
            "affected_metrics": metrics,
            "remediation": remediation,
        },
    )


def evaluate_common_gate(facts: CommonGateFacts, *, subject_id: str) -> GateDecision:
    decision = GateDecision(GateState.FORMAL)
    checks = (
        (
            not facts.request_schema_supported,
            "request.schema",
            "Assessment request schema is unsupported",
            ("assessment_request.json",),
            ("all",),
            "Use a supported blast_damage.assessment_request schema.",
        ),
        (
            not facts.evidence_unchanged,
            "evidence.changed",
            "Source evidence changed after preflight",
            ("source_evidence",),
            ("all",),
            "Restart the assessment from an immutable solver result directory.",
        ),
        (
            facts.termination != "normal",
            "solver.termination",
            "Solver termination is not normal",
            ("d3hsp",),
            ("all",),
            "Resolve solver termination errors and rerun the analysis.",
        ),
        (
            facts.target_time is None
            or facts.target_time <= 0
            or facts.final_time is None
            or facts.final_time / facts.target_time < 0.99,
            "solver.coverage",
            "Result states do not cover at least 99% of target time",
            ("d3plot", "model.json"),
            ("peak", "final", "residual"),
            "Rerun until the configured termination time is covered.",
        ),
        (
            not facts.units_known,
            "semantics.units",
            "Model unit system is unknown",
            ("semantic_manifest",),
            ("all",),
            "Declare and verify the model unit system and conversions.",
        ),
    )
    for failed, code, message, sources, metrics, remediation in checks:
        if failed:
            decision = decision.degrade(
                GateState.BLOCKED,
                _issue(code, message, GateState.BLOCKED, subject_id, sources, metrics, remediation),
            )
    if facts.legacy_inference:
        decision = decision.degrade(
            GateState.PROVISIONAL,
            _issue(
                "semantics.legacy_inference",
                "Legacy role or axis semantics were inferred",
                GateState.PROVISIONAL,
                subject_id,
                ("semantic_manifest",),
                ("classification",),
                "Provide a native blast_damage.model_semantics@1 manifest.",
            ),
        )
    if facts.preliminary_materials:
        decision = decision.degrade(
            GateState.PROVISIONAL,
            _issue(
                "materials.preliminary",
                "One or more material definitions lack engineering validation",
                GateState.PROVISIONAL,
                subject_id,
                ("semantic_manifest", "model.k"),
                ("material_damage", "stress_utilization"),
                "Bind reviewed project material calibration records.",
            ),
        )
    return decision


def evaluate_building_gate(facts: BuildingGateFacts, *, subject_id: str = "building") -> GateDecision:
    decision = evaluate_common_gate(facts.common, subject_id=subject_id)
    if not facts.identity_available:
        decision = decision.degrade(
            GateState.BLOCKED,
            _issue(
                "building.identity",
                "Critical building component identity is missing",
                GateState.BLOCKED,
                subject_id,
                ("semantic_manifest",),
                ("building_severity",),
                "Classify every primary load-path Part explicitly.",
            ),
        )
    if not facts.deformation_available:
        decision = decision.degrade(
            GateState.BLOCKED,
            _issue(
                "building.deformation_missing",
                "Building deformation response is unavailable",
                GateState.BLOCKED,
                subject_id,
                ("d3plot",),
                ("relative_deformation",),
                "Enable and verify nodal kinematic output.",
            ),
            unavailable_metric="deformation",
        )
    if not facts.importance_explicit:
        decision = decision.degrade(
            GateState.PROVISIONAL,
            _issue(
                "building.importance_inferred",
                "Building importance class is inferred",
                GateState.PROVISIONAL,
                subject_id,
                ("semantic_manifest",),
                ("class_aggregation",),
                "Declare component importance and primary load-path status.",
            ),
        )
    for available, metric in ((facts.stress_available, "stress"), (facts.strain_available, "strain")):
        if not available:
            decision = decision.degrade(
                GateState.PROVISIONAL,
                _issue(
                    f"building.{metric}_missing",
                    f"Building {metric} field is unavailable; deformation remains assessable",
                    GateState.PROVISIONAL,
                    subject_id,
                    ("d3plot",),
                    (metric,),
                    f"Enable a material-compatible {metric} result field.",
                ),
                unavailable_metric=metric,
            )
    return decision


def evaluate_ground_gate(facts: GroundGateFacts, *, subject_id: str = "ground") -> GateDecision:
    decision = evaluate_common_gate(facts.common, subject_id=subject_id)
    if not facts.identity_available:
        decision = decision.degrade(
            GateState.BLOCKED,
            _issue(
                "ground.identity",
                "Ground Part or surface identity is missing",
                GateState.BLOCKED,
                subject_id,
                ("semantic_manifest",),
                ("ground_severity",),
                "Declare exactly one ground Part set and its surface definition.",
            ),
        )
    if not facts.deformation_available:
        decision = decision.degrade(
            GateState.BLOCKED,
            _issue(
                "ground.deformation_missing",
                "Ground deformation response is unavailable",
                GateState.BLOCKED,
                subject_id,
                ("d3plot",),
                ("crater", "uplift", "settlement"),
                "Enable and verify ground nodal kinematics.",
            ),
            unavailable_metric="deformation",
        )
    if not facts.velocity_available:
        decision = decision.degrade(
            GateState.PROVISIONAL,
            _issue(
                "ground.velocity_missing",
                "Ground velocity is unavailable; residual stability cannot be established",
                GateState.PROVISIONAL,
                subject_id,
                ("d3plot",),
                ("residual_stability",),
                "Enable nodal velocity and extend the tail-state history.",
            ),
            unavailable_metric="velocity",
            residual_wording_allowed=False,
        )
    if not facts.material_damage_available:
        decision = decision.degrade(
            GateState.PROVISIONAL,
            _issue(
                "ground.material_damage_unavailable",
                "Ground material model does not support a damage variable",
                GateState.PROVISIONAL,
                subject_id,
                ("semantic_manifest", "d3plot"),
                ("material_damage",),
                "Use a calibrated inelastic soil model when material damage is required.",
            ),
            unavailable_metric="material_damage",
        )
    return decision
