import unittest

from blast_damage_assessment.reporting.csv_report import render_building_csv, render_ground_csv
from blast_damage_assessment.reporting.html_report import render_html_report


def snapshot():
    return {
        "assessment_id": "a" * 24,
        "overall": {"gate": "provisional", "severity": 3, "partial_assessment": False},
        "building": {
            "gate": "provisional",
            "severity": 3,
            "components": [
                {
                    "component_id": "=2+2<script>alert(1)</script>",
                    "zone_id": "+zone",
                    "importance_class": "primary",
                    "severity": 3,
                    "p99_relative_deformation": 0.012,
                    "affected_fraction": 0.4,
                    "response_metrics": {"beam_peak_axial_force_n": 42.0},
                    "rule_hits": ["building_relative_deformation_ratio"],
                }
            ],
        },
        "ground": {
            "gate": "provisional",
            "severity": 2,
            "material_metrics": {"scaled_damage_measure": 0.6},
            "stability": {"shape_term": "instantaneous_final_shape", "failed_criteria": ["tail_speed"]},
            "subratings": {
                "crater": {"available": True, "severity": 2, "reason": None},
                "@material_damage": {"available": False, "severity": None, "reason": "字段缺失"},
            },
            "peak": {"crater": {"maximum_depth": 0.5, "plan_area": 4.0}},
            "final": {"crater": {"maximum_depth": 0.4, "plan_area": 4.0}},
        },
        "limitations": ["<未校准>"],
        "missing_fields": ["solid_stress"],
        "inferences": ["legacy role"],
        "review_items": ["人工复核构件"],
    }


class ReportingTests(unittest.TestCase):
    def test_html_is_self_contained_escaped_and_labels_limitations(self):
        html = render_html_report(snapshot())
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        for text in ("可评估性门禁", "provisional", "局限性", "缺失字段", "推断语义", "瞬时末态", "人工复核"):
            self.assertIn(text, html)
        self.assertIn("beam_peak_axial_force_n", html)
        self.assertIn("scaled_damage_measure", html)

    def test_csv_is_utf8_bom_and_neutralizes_formula_prefixes(self):
        building = render_building_csv(snapshot())
        ground = render_ground_csv(snapshot())
        self.assertTrue(building.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(ground.startswith(b"\xef\xbb\xbf"))
        text = building.decode("utf-8-sig")
        self.assertIn("'=2+2", text)
        self.assertIn("'+zone", text)
        self.assertNotIn(",=2+2", text)
        self.assertIn("'@material_damage", ground.decode("utf-8-sig"))
        self.assertIn("beam_peak_axial_force_n=42.0", text)

        self.assertIn("scaled_damage_measure=0.6", ground.decode("utf-8-sig"))

if __name__ == "__main__":
    unittest.main()
