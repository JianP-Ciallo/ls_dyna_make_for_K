"""Public provider selecting the trusted solver-complete ALE/FSI compiler."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from lsprepost_mcp.refined_building.solver_blast import (
    SHORT_SOLVE_DEFAULT_TERMINATION_TIME_S,
    SolverBlastConfig,
    normalize_solver_blast_config,
    tnt_radius_m,
    tnt_side_length_m,
)

from ..contracts import Finding
from .common import (
    FrozenMapping,
    ProviderContext,
    ProviderEstimate,
    ProviderFragment,
    classify_source_space,
    fingerprint_value,
    freeze_value,
    source_space_evidence,
)


_PROVIDER_ID = "solver_complete_ale_fsi"
_SCHEMA_VERSION = "phase18.solver_blast.config@4"
_ACCEPTED_MIGRATIONS = (
    "phase18.solver_blast.config@1",
    "phase18.solver_blast.config@2",
    "phase18.solver_blast.config@3",
)
_UNIT_SYSTEM = "SI_m_s_kg_N_Pa"
_SUBWAY_ASSET_PREFIX = "subway_entrance_"


def _input_ui_schema() -> dict[str, object]:
    number = {"type": "number"}
    vector3 = {"type": "array", "items": number, "minItems": 3, "maxItems": 3}
    positive = {"type": "number", "exclusiveMinimum": 0.0}
    vector5 = {"type": "array", "items": positive, "minItems": 5, "maxItems": 5}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "unit_system",
            "tnt_equivalent_mass_kg",
            "charge_position_m",
            "detonation_time_s",
            "air_cell_size_m",
            "near_field_cell_size_m",
            "ground_cell_size_m",
            "air_margins_m",
            "coupling_buffer_layers",
            "material_profile",
            "termination_time_s",
        ],
        "properties": {
            "schema_version": {"type": "string", "const": _SCHEMA_VERSION},
            "unit_system": {"type": "string", "const": _UNIT_SYSTEM},
            "tnt_equivalent_mass_kg": {
                "type": "number",
                "minimum": 0.1,
                "maximum": 100.0,
                "title": "TNT 当量 (kg)",
            },
            "charge_position_m": {
                **vector3,
                "title": "爆源位置 X / Y / Z (m)",
            },
            "detonation_time_s": {
                "type": "number",
                "minimum": 0.0,
                "title": "起爆时间 (s)",
            },
            "air_cell_size_m": {
                "type": "number",
                "minimum": 0.15,
                "maximum": 0.5,
                "title": "空气单元尺寸 (m)",
            },
            "near_field_cell_size_m": {
                "type": "number",
                "minimum": 0.05,
                "maximum": 0.5,
                "title": "爆源近场单元尺寸 (m)",
            },
            "ground_cell_size_m": {
                "type": "number",
                "minimum": 0.1,
                "maximum": 0.5,
                "title": "地面单元尺寸 (m)",
            },
            "air_margins_m": {
                **vector5,
                "title": "空气域 X-/X+/Y-/Y+/顶部余量 (m)",
            },
            "coupling_buffer_layers": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "title": "地坪下耦合缓冲层数",
            },
            "material_profile": {
                "type": "string",
                "enum": ["verification_reference", "project_calibrated"],
                "title": "材料档案",
            },
            "termination_time_s": {
                "type": "number",
                "exclusiveMinimum": 0.0,
                "title": "终止时间 (s)",
            },
        },
    }


def _normalized_mapping(config: SolverBlastConfig) -> FrozenMapping:
    result = freeze_value(
        {
            "schema_version": config.schema_version,
            "unit_system": config.unit_system,
            "tnt_equivalent_mass_kg": config.tnt_equivalent_mass_kg,
            "charge_position_m": config.charge_position_m,
            "detonation_time_s": config.detonation_time_s,
            "air_cell_size_m": config.air_cell_size_m,
            "near_field_cell_size_m": config.near_field_cell_size_m,
            "ground_cell_size_m": config.ground_cell_size_m,
            "air_margins_m": config.air_margins_m,
            "coupling_buffer_layers": config.coupling_buffer_layers,
            "material_profile": config.material_profile,
            "termination_time_s": config.termination_time_s,
        },
        _PROVIDER_ID,
    )
    assert isinstance(result, Mapping)
    return result


class SolverCompleteAleFsiProvider:
    provider_id = _PROVIDER_ID

    def default_input(self) -> Mapping[str, object]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "unit_system": _UNIT_SYSTEM,
            "tnt_equivalent_mass_kg": 2.0,
            "charge_position_m": [-2.0, 1.5, 4.0],
            "detonation_time_s": 0.0,
            "air_cell_size_m": 0.225,
            "near_field_cell_size_m": 0.15,
            "ground_cell_size_m": 0.25,
            "air_margins_m": [3.0, 3.0, 3.0, 3.0, 3.0],
            "coupling_buffer_layers": 2,
            "material_profile": "verification_reference",
            "termination_time_s": SHORT_SOLVE_DEFAULT_TERMINATION_TIME_S,
        }

    def schema(self) -> Mapping[str, object]:
        result = freeze_value(
            {
                "schema_version": _SCHEMA_VERSION,
                "unit_system": _UNIT_SYSTEM,
                "exact_root_keys": tuple(self.default_input()),
                "accepted_migrations": _ACCEPTED_MIGRATIONS,
                "input_schema": _input_ui_schema(),
            },
            "schema",
        )
        assert isinstance(result, Mapping)
        return result

    def capabilities(self) -> Mapping[str, object]:
        result = freeze_value(
            {
                "provider_id": self.provider_id,
                "scenario_kinds": ("external",),
                "solver_complete": True,
                "software_candidate_only": False,
                "visible_air_domain": True,
                "movable_tnt": True,
                "real_ale_fsi_energy_path": True,
                "solver_ready": False,
                "requires_project_review": True,
                "engineering_validated": False,
                "launches_external_programs": False,
            },
            "capabilities",
        )
        assert isinstance(result, Mapping)
        return result

    def normalize(self, value: Mapping[str, object]) -> FrozenMapping:
        return _normalized_mapping(normalize_solver_blast_config(value))

    def validate(
        self, value: Mapping[str, object], context: ProviderContext
    ) -> tuple[Finding, ...]:
        try:
            self._validated(value, context)
        except (TypeError, ValueError) as exc:
            return (
                Finding(
                    finding_id=f"{self.provider_id}:{fingerprint_value(str(exc))[:16]}",
                    severity="error",
                    message=str(exc),
                ),
            )
        return ()

    def estimate(
        self, value: Mapping[str, object], context: ProviderContext
    ) -> ProviderEstimate:
        self._validated(value, context)
        return ProviderEstimate(
            provider_id=self.provider_id,
            axis_point_counts=(0, 0, 0),
            node_count=0,
            element_count=0,
            budget_limits={},
            budget_checked_before_allocation=True,
        )

    def compile(
        self, value: Mapping[str, object], context: ProviderContext
    ) -> ProviderFragment:
        normalized = self._validated(value, context)
        estimate = self.estimate(normalized, context)
        source_declared_id = "solver_complete_ale_fsi:charge"
        source_space_id = classify_source_space(
            normalized["charge_position_m"], context
        )
        evidence = source_space_evidence(
            provider_id=self.provider_id,
            source_declared_id=source_declared_id,
            source_space_id=source_space_id,
            context=context,
            determination="mesh_topology_classification",
        )
        required_ids = frozenset(
            {
                f"artifact:{context.artifact.fingerprint}",
                f"topology:{context.topology.fingerprint}",
            }
        )
        return ProviderFragment(
            provider_id=self.provider_id,
            normalized_input=normalized,
            axes_m=((), (), ()),
            node_ids=(),
            element_ids=(),
            fsi_face_ids=(),
            required_ids=required_ids,
            declared_ids=frozenset({source_declared_id, evidence.evidence_id}),
            evidence=(evidence,),
            manifest={
                "schema_version": "phase18.solver_blast.provider_fragment@1",
                "provider_id": self.provider_id,
                "scenario_kind": context.scenario_kind,
                "building_artifact_fingerprint": context.artifact.fingerprint,
                "topology_fingerprint": context.topology.fingerprint,
                "input_fingerprint": fingerprint_value(normalized),
                "allocation": {
                    "estimate": estimate.to_manifest(),
                    "actual_node_count": 0,
                    "actual_element_count": 0,
                },
                "fsi_face_ids": (),
                "evidence_fingerprints": (evidence.fingerprint,),
                "id_closure": {
                    "required_ids": tuple(sorted(required_ids)),
                    "declared_ids": tuple(sorted({source_declared_id, evidence.evidence_id})),
                    "evidence_ids": (evidence.evidence_id,),
                    "closed": True,
                },
                "solver_complete": True,
                "solver_ready": False,
                "requires_project_review": True,
                "engineering_validated": False,
                "external_program_started": False,
            },
        )

    def preview(
        self, value: Mapping[str, object], context: ProviderContext
    ) -> FrozenMapping:
        normalized = self._validated(value, context)
        envelope = context.topology.envelope_bounds_m
        margins = tuple(float(value) for value in normalized["air_margins_m"])
        grade_elevation_m = _grade_elevation_m(context)
        active_air_bounds = (
            envelope[0] - margins[0],
            envelope[1] - margins[2],
            grade_elevation_m,
            envelope[3] + margins[1],
            envelope[4] + margins[3],
            envelope[5] + margins[4],
        )
        buffer_depth_m = (
            int(normalized["coupling_buffer_layers"])
            * float(normalized["air_cell_size_m"])
        )
        coupling_buffer_bounds = (
            active_air_bounds[0],
            active_air_bounds[1],
            grade_elevation_m - buffer_depth_m,
            active_air_bounds[3],
            active_air_bounds[4],
            grade_elevation_m,
        )
        tnt_mass = float(normalized["tnt_equivalent_mass_kg"])
        tnt_side = tnt_side_length_m(tnt_mass)
        half_side = 0.5 * tnt_side
        tnt_position = tuple(float(value) for value in normalized["charge_position_m"])
        tnt_bounds = (
            tnt_position[0] - half_side,
            tnt_position[1] - half_side,
            tnt_position[2] - half_side,
            tnt_position[0] + half_side,
            tnt_position[1] + half_side,
            tnt_position[2] + half_side,
        )
        result = freeze_value(
            {
                "provider_id": self.provider_id,
                "scenario_kind": context.scenario_kind,
                "detonation_position_m": normalized["charge_position_m"],
                "tnt_equivalent_mass_kg": tnt_mass,
                "tnt_realized_mass_kg": tnt_mass,
                "tnt_radius_m": tnt_radius_m(tnt_mass),
                "tnt_geometry_kind": "mass_conserving_cuboid",
                "tnt_side_length_m": tnt_side,
                "tnt_bounds_m": tnt_bounds,
                "tnt_minimum_solid_element_count": 27,
                "domain_bounds_m": active_air_bounds,
                "active_air_bounds_m": active_air_bounds,
                "coupling_buffer_bounds_m": coupling_buffer_bounds,
                "coupling_buffer_layers": normalized["coupling_buffer_layers"],
                "ground_bounds_m": (
                    active_air_bounds[0],
                    active_air_bounds[1],
                    grade_elevation_m
                    - max(
                        0.5,
                        buffer_depth_m + float(normalized["ground_cell_size_m"]),
                    ),
                    active_air_bounds[3],
                    active_air_bounds[4],
                    grade_elevation_m,
                ),
                "visible_air_domain": True,
                "real_fsi_on_generation": True,
                "solver_complete": True,
                "solver_ready": False,
                "requires_project_review": True,
            },
            "solver_complete.preview",
        )
        assert isinstance(result, Mapping)
        return result

    def _validated(
        self, value: Mapping[str, object], context: ProviderContext
    ) -> FrozenMapping:
        if context.scenario_kind != "external":
            raise ValueError("solver_complete_ale_fsi currently requires an external scenario")
        normalized = self.normalize(value)
        position = normalized["charge_position_m"]
        assert isinstance(position, Sequence)
        margins = normalized["air_margins_m"]
        assert isinstance(margins, Sequence)
        envelope = context.topology.envelope_bounds_m
        grade_elevation_m = _grade_elevation_m(context)
        preview_bounds = (
            envelope[0] - float(margins[0]),
            envelope[1] - float(margins[2]),
            grade_elevation_m,
            envelope[3] + float(margins[1]),
            envelope[4] + float(margins[3]),
            envelope[5] + float(margins[4]),
        )
        if any(
            not preview_bounds[axis] < float(position[axis]) < preview_bounds[axis + 3]
            for axis in range(3)
        ):
            raise ValueError("charge_position_m must be strictly inside the generated air domain")
        return normalized


def _grade_elevation_m(context: ProviderContext) -> float:
    """Recover the public grade marker without changing Phase 18D fingerprints."""

    artifact = context.artifact
    if not artifact.asset_id.startswith(_SUBWAY_ASSET_PREFIX):
        return 0.0
    spaces = artifact.normalized_input.get("spaces")
    if not isinstance(spaces, Sequence) or isinstance(spaces, (str, bytes, bytearray)):
        raise ValueError("subway artifact spaces are unavailable for grade recovery")
    passage_tops: list[float] = []
    for row in spaces:
        if not isinstance(row, Mapping) or row.get("kind") != "passage":
            continue
        bounds = row.get("bounds_m")
        if (
            not isinstance(bounds, Sequence)
            or isinstance(bounds, (str, bytes, bytearray))
            or len(bounds) != 6
        ):
            raise ValueError("subway passage bounds are invalid for grade recovery")
        top = float(bounds[5])
        if not math.isfinite(top):
            raise ValueError("subway passage grade must be finite")
        passage_tops.append(top)
    if not passage_tops:
        raise ValueError("subway artifact does not expose a passage grade")
    return max(passage_tops)


__all__ = ["SolverCompleteAleFsiProvider"]
