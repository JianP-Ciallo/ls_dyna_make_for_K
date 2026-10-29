import hashlib
import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path

import numpy as np

from blast_damage_assessment.adapters.contracts import (
    AdapterProbe,
    ArrayField,
    EntityKind,
    FieldAvailability,
    GeometryIndex,
    SolverQuality,
    StateChunk,
)
from blast_damage_assessment.adapters.lsdyna.adapter import LsdynaResultAdapter
from blast_damage_assessment.canonical import sha256_json
from blast_damage_assessment.contracts import Severity
from blast_damage_assessment.pipeline import _collect_fields, run_pipeline


ARTIFACT_NAMES = {
    "assessment_request.json",
    "assessment_result.json",
    "assessment_snapshot.json",
    "evidence_index.json",
    "rule_snapshot.json",
    "damage_report.html",
    "building_components.csv",
    "ground_regions.csv",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def grid_geometry(size: int = 4) -> GeometryIndex:
    layer = (size + 1) ** 2
    coordinates = []
    for z in (0.0, 1.0):
        for y in range(size + 1):
            for x in range(size + 1):
                coordinates.append((float(x), float(y), z))
    solids = []
    for y in range(size):
        for x in range(size):
            bottom = y * (size + 1) + x
            top = layer + bottom
            solids.append(
                (
                    bottom,
                    bottom + 1,
                    bottom + size + 2,
                    bottom + size + 1,
                    top,
                    top + 1,
                    top + size + 2,
                    top + size + 1,
                )
            )
    beam_start = len(coordinates)
    coordinates.extend((5.0, 0.0, float(index)) for index in range(5))
    beams = np.array([[beam_start + i, beam_start + i + 1] for i in range(4)], dtype=np.int64)
    return GeometryIndex(
        np.arange(1, len(coordinates) + 1, dtype=np.int64),
        np.asarray(coordinates, dtype=float),
        {
            EntityKind.SOLID: np.arange(100, 100 + len(solids), dtype=np.int64),
            EntityKind.SHELL: np.array([], dtype=np.int64),
            EntityKind.BEAM: np.arange(200, 204, dtype=np.int64),
        },
        {
            EntityKind.SOLID: np.full(len(solids), 8001, dtype=np.int64),
            EntityKind.SHELL: np.array([], dtype=np.int64),
            EntityKind.BEAM: np.array([1001, 1001, 1002, 1002], dtype=np.int64),
        },
        {
            EntityKind.SOLID: np.asarray(solids, dtype=np.int64),
            EntityKind.SHELL: np.empty((0, 4), dtype=np.int64),
            EntityKind.BEAM: beams,
        },
    )


def array_field(kind, ids, indexes, values, name, unit="1", conversion="units.identity@1"):
    values = np.asarray(values)
    return ArrayField(
        kind,
        np.asarray(ids, dtype=np.int64),
        np.asarray(indexes, dtype=np.int64),
        values.copy(),
        unit,
        values.copy(),
        unit,
        conversion,
        name,
        name,
    )


class FakePipelineAdapter:
    adapter_id = "fake_lsdyna"
    adapter_version = "1.0-test"

    def __init__(self, *, blocked=False, fail=False, missing_building=False, final_time_none=False, delete_building=False):
        self.geometry = None if blocked else grid_geometry()
        if missing_building and self.geometry is not None:
            self.geometry.part_ids[EntityKind.BEAM][:] = 9999
        self.fail = fail
        self.final_time_none = final_time_none
        self.times = np.arange(6.0)
        if self.geometry is not None:
            node_count = self.geometry.node_ids.size
            self.displacement = np.zeros((6, node_count, 3), dtype=float)
            layer = 25
            crater_nodes = [layer + y * 5 + x for y in range(1, 4) for x in range(1, 4)]
            self.displacement[1:, crater_nodes, 2] = -0.5
            self.displacement[2, -5:, 0] = np.linspace(0.0, 0.12, 5)
            self.velocity = np.zeros_like(self.displacement)
            self.solid_alive = np.ones((6, self.geometry.element_ids[EntityKind.SOLID].size), dtype=bool)
            self.solid_history = np.zeros(
                (6, self.geometry.element_ids[EntityKind.SOLID].size, 1),
                dtype=float,
            )
            self.solid_history[-1, :, 0] = 0.6
            self.beam_alive = np.ones((6, self.geometry.element_ids[EntityKind.BEAM].size), dtype=bool)
            self.beam_axial_force = np.zeros_like(self.beam_alive, dtype=float)
            self.beam_shear_force = np.zeros_like(self.beam_alive, dtype=float)
            self.beam_axial_force[-1] = [10.0, -20.0, 30.0, -40.0]
            self.beam_shear_force[-1] = [4.0, -3.0, 2.0, -1.0]
            if delete_building:
                self.beam_alive[-1] = False

    def probe(self, result_dir):
        if self.fail:
            raise RuntimeError("adapter exploded")
        available = FieldAvailability(True, None)
        missing = FieldAvailability(False, "not emitted")
        return AdapterProbe(
            self.adapter_id,
            self.adapter_version,
            self.geometry,
            0 if self.geometry is None else 6,
            {
                "node_displacement": missing if self.geometry is None else available,
                "node_velocity": missing if self.geometry is None else available,
                "solid_stress": missing,
                "solid_effective_plastic_strain": missing,
                "solid_history_variables": missing if self.geometry is None else available,
                "solid_is_alive": missing if self.geometry is None else available,
                "shell_stress": missing,
                "shell_effective_plastic_strain": missing,
                "shell_history_variables": missing,
                "shell_is_alive": missing,
                "shell_strain": missing,
                "beam_axial_force": missing if self.geometry is None else available,
                "beam_shear_force": missing if self.geometry is None else available,
                "beam_is_alive": missing if self.geometry is None else available,
            },
            SolverQuality("normal", 5.0, 5.0, None if self.final_time_none else 5.0, 0.01),
        )

    def iter_state_chunks(self, result_dir, chunk_size):
        assert self.geometry is not None
        for start in range(0, 6, chunk_size):
            stop = min(start + chunk_size, 6)
            indexes = np.arange(start, stop, dtype=np.int64)
            yield StateChunk(
                self.times[start:stop].copy(),
                {
                    "node_displacement_m": array_field(
                        EntityKind.NODE,
                        self.geometry.node_ids,
                        indexes,
                        self.displacement[start:stop],
                        "node_displacement",
                        "m",
                    ),
                    "node_velocity_m_per_s": array_field(
                        EntityKind.NODE,
                        self.geometry.node_ids,
                        indexes,
                        self.velocity[start:stop],
                        "node_velocity",
                        "m/s",
                    ),
                    "solid_history_variables": array_field(
                        EntityKind.SOLID,
                        self.geometry.element_ids[EntityKind.SOLID],
                        indexes,
                        self.solid_history[start:stop],
                        "element_solid_history_variables",
                        "material_defined",
                    ),
                    "solid_is_alive": array_field(
                        EntityKind.SOLID,
                        self.geometry.element_ids[EntityKind.SOLID],
                        indexes,
                        self.solid_alive[start:stop],
                        "element_solid_is_alive",
                        "1",
                    ),

                    "beam_axial_force_n": array_field(
                        EntityKind.BEAM,
                        self.geometry.element_ids[EntityKind.BEAM],
                        indexes,
                        self.beam_axial_force[start:stop],
                        "element_beam_axial_force",
                        "N",
                    ),
                    "beam_shear_force_n": array_field(
                        EntityKind.BEAM,
                        self.geometry.element_ids[EntityKind.BEAM],
                        indexes,
                        self.beam_shear_force[start:stop],
                        "element_beam_shear_force",
                        "N",
                    ),
                    "beam_is_alive": array_field(
                        EntityKind.BEAM,
                        self.geometry.element_ids[EntityKind.BEAM],
                        indexes,
                        self.beam_alive[start:stop],
                        "element_beam_is_alive",
                        "1",
                    ),
                },
            )


class PipelineCase:
    def make_case(self, output_name="assessment"):
        root = Path(self.temp.name)
        result_dir = root / "solver-run"
        result_dir.mkdir(exist_ok=True)
        fixture = Path(__file__).parent / "fixtures" / "semantics" / "native_semantics_v1.json"
        semantics = json.loads(fixture.read_text(encoding="utf-8"))
        semantics["blast_center_m"] = [2.0, 2.0, 2.0]
        manifest = result_dir / "assessment_semantics.json"
        manifest.write_text(json.dumps(semantics), encoding="utf-8")
        for name, data in {
            "model.k": "*KEYWORD\n*END\n",
            "model.json": "{}",
            "run.json": '{"status":"completed"}',
            "d3hsp": "termination time.... 5.0\nproblem time = 5.0\nnormal termination\n",
            "d3plot": "synthetic states",
        }.items():
            (result_dir / name).write_text(data, encoding="utf-8")
        request = {
            "schema_version": "blast_damage.assessment_request@1",
            "project_id": "pipeline-project",
            "case_id": "synthetic-case",
            "result_dir": str(result_dir),
            "semantic_manifest": {
                "path": str(manifest),
                "sha256": sha256(manifest),
                "schema_version": "blast_damage.model_semantics@1",
            },
            "building_rule_pack": "building_research_reference@1",
            "ground_rule_pack": "ground_research_reference@1",
            "output_dir": str(root / output_name),
            "state_chunk_size": 2,
        }
        return root, result_dir, request


class PipelineTests(PipelineCase, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_collector_retains_only_final_alive_state(self):
        adapter = FakePipelineAdapter(delete_building=True)
        _, fields = _collect_fields(adapter, Path("."), 6, 2)

        self.assertEqual(fields["node_displacement_m"].values.shape[0], 6)
        self.assertEqual(fields["solid_is_alive"].values.ndim, 1)
        self.assertEqual(fields["beam_is_alive"].values.ndim, 1)
        self.assertFalse(np.any(fields["beam_is_alive"].values))

    def test_pipeline_publishes_exact_closed_artifact_set(self):
        root, result_dir, request = self.make_case()
        result = run_pipeline(request, adapter=FakePipelineAdapter())
        output = Path(request["output_dir"])
        public_result = result.to_dict()
        public_result["artifacts"].pop("assessment_result.json")
        self.assertEqual(public_result, json.loads((output / "assessment_result.json").read_text(encoding="utf-8")))
        self.assertEqual({path.name for path in output.iterdir()}, ARTIFACT_NAMES)
        self.assertEqual(set(result.artifacts), ARTIFACT_NAMES)
        for name, reference in result.artifacts.items():
            self.assertEqual(reference.sha256, sha256(output / name))
            self.assertEqual(reference.size_bytes, (output / name).stat().st_size)
        snapshot = json.loads((output / "assessment_snapshot.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot["schema_version"], "blast_damage.assessment_snapshot@1")
        self.assertEqual(snapshot["adapter"]["geometry"]["node_count"], 55)
        self.assertEqual(snapshot["adapter"]["geometry"]["element_count"], 20)
        self.assertEqual(snapshot["adapter"]["geometry"]["part_count"], 3)
        self.assertEqual(snapshot["adapter"]["geometry"]["part_ids"], [1001, 1002, 8001])
        self.assertEqual(snapshot["adapter"]["solver_quality"]["final_state_time"], 5.0)
        self.assertEqual(snapshot["overall"]["gate"], "provisional")
        self.assertIsNotNone(snapshot["building"]["severity"])
        self.assertIsNotNone(snapshot["ground"]["severity"])
        self.assertTrue(snapshot["ground"]["subratings"]["numerical_erosion"]["available"])
        evidence = json.loads((output / "evidence_index.json").read_text(encoding="utf-8"))
        node_ids = {node["id"] for node in evidence["nodes"]}
        component_metrics = snapshot["building"]["components"][0]["response_metrics"]
        self.assertEqual(component_metrics["beam_peak_axial_force_n"], 40.0)
        self.assertEqual(component_metrics["beam_peak_shear_force_n"], 4.0)

        self.assertTrue(node_ids)
        self.assertTrue(all(set(node["dependencies"]) <= node_ids for node in evidence["nodes"]))
        nodes = {node["id"]: node for node in evidence["nodes"]}
        erosion_local = next(
            node for node in nodes.values()
            if node["kind"] == "local_severity" and node.get("subject_id") == "ground:numerical_erosion"
        )
        erosion_hit = nodes[erosion_local["dependencies"][0]]
        erosion_metric = nodes[erosion_hit["dependencies"][0]]
        erosion_observation = nodes[erosion_metric["dependencies"][0]]
        self.assertEqual(erosion_observation["dependencies"], ["field:solid_is_alive"])
        rules = json.loads((output / "rule_snapshot.json").read_text(encoding="utf-8"))
        self.assertEqual({item["subject"] for item in rules["rule_packs"]}, {"building", "ground"})
        request_path = output / "assessment_request.json"
        request_text = request_path.read_text(encoding="utf-8")
        request_snapshot = json.loads(request_text)
        self.assertNotIn(str(root), request_text)
        self.assertEqual(request_snapshot["result_dir"], "source/result_dir")
        self.assertEqual(
            request_snapshot["semantic_manifest"]["path"],
            "source/result_dir/assessment_semantics.json",
        )
        self.assertEqual(
            request_snapshot["output_dir"],
            f"output/{output.name}",
        )
        self.assertEqual({path.name for path in root.iterdir()}, {result_dir.name, output.name})

    def test_chunk_size_is_execution_tuning_not_assessment_identity(self):
        root, _, request = self.make_case("chunk-1")
        request["state_chunk_size"] = 1
        first = run_pipeline(request, adapter=FakePipelineAdapter())
        second_request = {**request, "output_dir": str(root / "chunk-8"), "state_chunk_size": 8}
        second = run_pipeline(second_request, adapter=FakePipelineAdapter())
        self.assertEqual(first.assessment_id, second.assessment_id)
        self.assertEqual(first.assessment_fingerprint, second.assessment_fingerprint)
        first_snapshot = (root / "chunk-1" / "assessment_snapshot.json").read_bytes()
        second_snapshot = (root / "chunk-8" / "assessment_snapshot.json").read_bytes()
        self.assertEqual(first_snapshot, second_snapshot)


    def test_blocked_subjects_still_publish_partial_report_without_severity(self):
        _, _, request = self.make_case()
        result = run_pipeline(request, adapter=FakePipelineAdapter(blocked=True))
        self.assertEqual(result.gate.value, "blocked")
        self.assertIsNone(result.severity)
        snapshot = json.loads(
            (Path(request["output_dir"]) / "assessment_snapshot.json").read_text(encoding="utf-8")
        )
        self.assertTrue(snapshot["overall"]["partial_assessment"])

    def test_runtime_component_geometry_gap_is_an_explicit_blocker(self):
        _, _, request = self.make_case()
        result = run_pipeline(request, adapter=FakePipelineAdapter(missing_building=True))
        self.assertEqual(result.gate.value, "blocked")
        self.assertTrue(result.blockers)
        self.assertTrue(any(issue.code == "building.identity" for issue in result.blockers))

    def test_state_time_backfill_preserves_field_specific_gate_issues(self):
        _, _, request = self.make_case()
        result = run_pipeline(request, adapter=FakePipelineAdapter(final_time_none=True))
        self.assertEqual(result.gate.value, "provisional")
        codes = {issue.code for issue in result.review_items}
        self.assertIn("building.stress_missing", codes)
        self.assertIn("building.strain_missing", codes)
        self.assertIn("ground.material_damage_unavailable", codes)

    def test_building_deletion_conclusion_uses_deletion_evidence_not_deformation(self):
        _, _, request = self.make_case()
        adapter = FakePipelineAdapter(delete_building=True)
        adapter.displacement[:] = 0.0
        result = run_pipeline(request, adapter=adapter)
        self.assertEqual(result.severity, Severity.SEVERE)
        evidence = json.loads(
            (Path(request["output_dir"]) / "evidence_index.json").read_text(encoding="utf-8")
        )
        nodes = {node["id"]: node for node in evidence["nodes"]}
        local = next(
            node for node in nodes.values()
            if node["kind"] == "local_severity"
            and node.get("subject_id") == "building:column-a"
        )
        hits = [nodes[node_id] for node_id in local["dependencies"]]
        self.assertEqual(
            {item["rule_id"] for item in hits},
            {"numerical_deletion_connected"},
        )
        self.assertEqual(hits[0]["actual_value"], 4.0)
        self.assertEqual(hits[0]["limit_value"], 4.0)
        observation = nodes[nodes[hits[0]["dependencies"][0]]["dependencies"][0]]
        self.assertEqual(observation["entity_id"], 200)
        self.assertEqual(observation["state_index"], 5)

    def test_formal_rule_pack_is_capped_when_bound_applicability_is_absent(self):
        root, _, request = self.make_case()
        fixture = (
            Path(__file__).parent
            / "fixtures"
            / "rules"
            / "building_project_calibrated_v1.json"
        )
        pack = json.loads(fixture.read_text(encoding="utf-8"))
        pack["rules"][0]["id"] = "building_relative_deformation_ratio"
        pack["review_record"]["reviewed_binding_sha256"] = sha256_json(pack["bindings"])
        path = root / "formal-building.json"
        path.write_text(json.dumps(pack), encoding="utf-8")
        request["building_rule_pack"] = str(path)

        result = run_pipeline(request, adapter=FakePipelineAdapter())

        self.assertEqual(result.gate.value, "provisional")
        issue = next(
            item for item in result.review_items
            if item.code == "building.rule_applicability"
        )
        self.assertIn("response_type", issue.details["missing"])
        self.assertIn("support_definition", issue.details["missing"])

    def test_ground_material_history_is_streamed_and_exposed_without_an_unbound_rating(self):
        _, _, request = self.make_case()
        manifest = Path(request["semantic_manifest"]["path"])
        semantics = json.loads(manifest.read_text(encoding="utf-8"))
        material = next(
            item for item in semantics["materials"]
            if item["material_id"] == 7
        )
        material.clear()
        material.update(
            {
                "material_id": 7,
                "model": "MAT_072R3",
                "nout": 2,
                "engineering_validated": True,
            }
        )
        manifest.write_text(json.dumps(semantics), encoding="utf-8")
        request["semantic_manifest"]["sha256"] = sha256(manifest)
        run_pipeline(request, adapter=FakePipelineAdapter())
        snapshot = json.loads(
            (Path(request["output_dir"]) / "assessment_snapshot.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            snapshot["ground"]["material_metrics"]["scaled_damage_measure"],
            0.6,
        )
        self.assertFalse(snapshot["ground"]["subratings"]["material_damage"]["available"])



class LsdynaAdapterCompositionTests(unittest.TestCase):
    def test_probe_combines_text_quality_with_lasso_geometry_and_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            result_dir = Path(temporary)
            (result_dir / "d3hsp").write_text(
                "termination time.... 5.0\nproblem time = 5.0\nnormal termination\n",
                encoding="utf-8",
            )
            d3probe = SimpleNamespace(
                geometry=grid_geometry(),
                state_count=6,
                fields={"node_displacement": FieldAvailability(True, None)},
                timesteps=np.arange(6.0),
            )

            class Reader:
                def __init__(self):
                    self.groups = []

                def probe(self):
                    return d3probe

                def iter_state_chunks(self, field_group, chunk_size):
                    self.groups.append((field_group, chunk_size))
                    return iter(())

            reader = Reader()
            adapter = LsdynaResultAdapter(reader_factory=lambda path: reader)
            probe = adapter.probe(result_dir)
            self.assertIs(probe.geometry, d3probe.geometry)
            self.assertEqual(probe.state_count, 6)
            self.assertEqual(probe.solver_quality.final_state_time, 5.0)
            list(adapter.iter_state_chunks(result_dir, 2))
            self.assertEqual([name for name, _ in reader.groups], ["node_kinematics", "solid_response", "shell_response", "beam_response"])

if __name__ == "__main__":
    unittest.main()
