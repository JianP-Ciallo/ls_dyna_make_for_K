import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from packages.blast_damage_assessment.scripts.run_reference_acceptance import (
    AcceptanceFailure,
    ProcessOutcome,
    aggregate_process_tree_rss,
    _validate_case_snapshot,
    _validate_report_consistency,
    descendant_process_ids,
    cleanup_owned_output_root,
    compare_source_hashes,
    process_tree_termination_order,
    ensure_nonformal,
    run_monitored,
    prepare_output_parent,
    run_negative_checks,
    validate_artifact_references,
    validate_process_outcome,
    validate_solver_times,
)


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class FakeProcess:
    def __init__(self, returncode=None):
        self.pid = 42
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode

    def communicate(self):
        return b'{"ok":true}', b""



class ProcessMonitorTests(unittest.TestCase):
    def test_process_tree_termination_is_deepest_child_first(self):
        parents = {10: 1, 20: 10, 30: 20, 40: 10, 50: 999}
        self.assertEqual(
            process_tree_termination_order(10, parents),
            (30, 20, 40),
        )

    def test_process_tree_rss_includes_recursive_children(self):
        parents = {10: 1, 20: 10, 30: 20, 40: 999}
        self.assertEqual(descendant_process_ids(10, parents), {10, 20, 30})
        rss = aggregate_process_tree_rss(
            10,
            parents,
            lambda pid: {10: 4, 20: 11, 30: 100, 40: 1000}[pid],
        )
        self.assertEqual(rss, 115)



    def test_timeout_terminates_child_and_fails_acceptance(self):
        process = FakeProcess()
        clock = FakeClock()
        outcome = run_monitored(
            ["fake"],
            timeout_s=0.1,
            max_rss_bytes=100,
            popen_factory=lambda *args, **kwargs: process,
            rss_reader=lambda pid: 1,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            poll_interval=0.2,
        )
        self.assertTrue(outcome.timed_out)
        self.assertTrue(process.terminated)
        with self.assertRaisesRegex(AcceptanceFailure, "timeout"):
            validate_process_outcome(outcome)

    def test_peak_rss_limit_terminates_child(self):
        process = FakeProcess()
        clock = FakeClock()
        outcome = run_monitored(
            ["fake"],
            timeout_s=10.0,
            max_rss_bytes=100,
            popen_factory=lambda *args, **kwargs: process,
            rss_reader=lambda pid: 101,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
        self.assertTrue(outcome.memory_exceeded)
        self.assertEqual(outcome.peak_rss_bytes, 101)
        with self.assertRaisesRegex(AcceptanceFailure, "RSS"):
            validate_process_outcome(outcome)

    def test_nonzero_exit_fails_acceptance(self):
        with self.assertRaisesRegex(AcceptanceFailure, "exit code 7"):
            validate_process_outcome(ProcessOutcome(7, b"", b"bad", 1.0, 10, False, False))


class AcceptanceValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
    def test_prepares_parent_without_precreating_atomic_output_target(self):
        output = self.root / "commercial" / "chunk-1"
        prepare_output_parent(output)
        self.assertTrue(output.parent.is_dir())
        self.assertFalse(output.exists())


    def test_any_formal_subject_is_an_automatic_stop(self):
        for location in ("overall", "building", "ground"):
            snapshot = {
                "overall": {"gate": "provisional"},
                "building": {"gate": "provisional"},
                "ground": {"gate": "provisional"},
            }
            snapshot[location]["gate"] = "formal"
            with self.subTest(location=location), self.assertRaisesRegex(AcceptanceFailure, "formal"):
                ensure_nonformal(snapshot)

    def test_solver_time_comparison_allows_d3hsp_display_rounding_only(self):
        validate_solver_times(0.00100181319706243, 0.0010018, 0.001)
        with self.assertRaisesRegex(AcceptanceFailure, "differs"):
            validate_solver_times(0.0011, 0.0010018, 0.001)
        with self.assertRaisesRegex(AcceptanceFailure, "termination target"):
            validate_solver_times(0.00100181319706243, 0.0010018, 0.002)

    def test_part_validation_allows_only_declared_implicit_tnt_part_without_elements(self):
        snapshot = {
            "adapter": {
                "geometry": {
                    "node_count": 10,
                    "element_count": 20,
                    "part_count": 2,
                    "part_ids": [1001, 9001],
                },
                "solver_quality": {"final_state_time": 5.0, "problem_time": 5.0},
                "fields": {},
            },
            "missing_fields": [],
        }
        manifest = {
            "total_node_count": 10,
            "total_element_count": 20,
            "part_ids": [
                ["building", 1001],
                ["ale_air_tnt_domain", 9001],
                ["tnt_high_explosive", 9002],
            ],
        }
        run = {"static_validation": {"termination_time_s": 5.0}}

        _validate_case_snapshot(snapshot, manifest, run)
        snapshot["adapter"]["geometry"]["part_ids"].append(9999)
        snapshot["adapter"]["geometry"]["part_count"] = 3
        with self.assertRaisesRegex(AcceptanceFailure, "Part"):
            _validate_case_snapshot(snapshot, manifest, run)


    def test_source_hash_change_fails(self):
        with self.assertRaisesRegex(AcceptanceFailure, "source hash"):
            compare_source_hashes({"d3plot": "a" * 64}, {"d3plot": "b" * 64})

    def test_artifact_hash_inconsistency_fails(self):
        output = self.root / "output"
        output.mkdir()
        (output / "payload.json").write_bytes(b"actual")
        envelope = {
            "artifacts": {
                "payload.json": {
                    "sha256": hashlib.sha256(b"different").hexdigest(),
                    "size_bytes": len(b"actual"),
                }
            }
        }
        (output / "assessment_result.json").write_text(json.dumps(envelope), encoding="utf-8")
        with self.assertRaisesRegex(AcceptanceFailure, "artifact hash"):
            validate_artifact_references(output)

    def test_report_consistency_rejects_same_row_count_with_wrong_severity(self):
        output = self.root / "report"
        output.mkdir()
        snapshot = {
            "overall": {"gate": "provisional"},
            "building": {
                "gate": "provisional",
                "components": [{
                    "component_id": "column-1", "zone_id": None, "importance_class": "primary",
                    "gate": "provisional", "severity": 1, "p99_relative_deformation": 0.1,
                    "affected_fraction": 0.2, "rule_hits": ["building-rule"],
                }],
            },
            "ground": {
                "gate": "provisional", "stability": {"stable": True},
                "subratings": {"crater": {
                    "available": True, "severity": 2, "reason": None, "metric_name": "depth",
                    "actual_value": 1.5, "rule_hits": ["ground-rule"],
                }},
            },
        }
        (output / "building_components.csv").write_text(
            "component_id,zone_id,importance_class,gate,severity,p99_relative_deformation,affected_fraction,rule_hits\n"
            "column-1,,primary,provisional,0,0.1,0.2,building-rule\n", encoding="utf-8",
        )
        (output / "ground_regions.csv").write_text(
            "region_or_subrating,gate,available,severity,reason,metric_name,actual_value,rule_hits\n"
            "crater,provisional,True,2,,depth,1.5,ground-rule\n", encoding="utf-8",
        )
        (output / "damage_report.html").write_text("provisional", encoding="utf-8")
        with self.assertRaisesRegex(AcceptanceFailure, "severity"):
            _validate_report_consistency(output, snapshot)

    def test_cleanup_is_limited_to_owned_output_root(self):
        parent = self.root / "parent"
        parent.mkdir()
        owned = parent / "owned"
        owned.mkdir()
        (owned / ".blast-damage-acceptance-owned").write_text("owned", encoding="utf-8")
        sibling = parent / "keep.txt"
        sibling.write_text("keep", encoding="utf-8")
        cleanup_owned_output_root(owned, parent)
        self.assertFalse(owned.exists())
        self.assertEqual(sibling.read_text(encoding="utf-8"), "keep")
        with self.assertRaisesRegex(AcceptanceFailure, "ownership marker"):
            cleanup_owned_output_root(parent, self.root)

    def test_generated_negative_checks_cover_all_required_cases(self):
        results = run_negative_checks(self.root / "acceptance")
        self.assertEqual(
            set(results),
            {
                "d3plot_gap",
                "changed_hash",
                "abnormal_termination",
                "insufficient_final_time",
                "missing_units",
                "missing_building_identity",
                "missing_ground_identity",
                "unsupported_request_major",
                "missing_velocity",
                "non_stabilized_surface",
            },
        )
        self.assertTrue(all(item["passed"] for item in results.values()))


if __name__ == "__main__":
    unittest.main()
