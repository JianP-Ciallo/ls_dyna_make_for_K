from __future__ import annotations

import unittest

from lsprepost_mcp.blast_cases import blast_plate_demo_payload
from lsprepost_mcp.tool_generation import tool_assemble_components


class BlastPlateDemoTests(unittest.TestCase):
    def test_fixed_demo_matches_phase12_acceptance_parameters(self) -> None:
        payload = blast_plate_demo_payload()
        plate = payload["components"][0]
        blast = payload["actions"][1]
        self.assertEqual({"length_m": 1.0, "width_m": 1.0, "thickness_m": 0.01}, plate["geometry"])
        self.assertEqual(0.025, plate["mesh"]["size_m"])
        self.assertEqual("mild_steel_mat24_demo", plate["material"]["name"])
        self.assertEqual(0.1, blast["equivalent_mass_kg"])
        self.assertEqual([0.0, 0.0, 0.5], blast["position_m"])
        self.assertEqual(0.02, payload["analysis_control"]["termination"]["end_time_s"])
        self.assertEqual(0.001, blast["output_dt_s"])
        self.assertEqual(0, payload["database"]["format"])
        self.assertEqual(1, payload["database"]["ibinary"])
        self.assertEqual(0.001, payload["database"]["d3plot_dt_s"])
        self.assertEqual(0, payload["database"]["extent_binary"]["neiph"])
        self.assertNotIn("d3thdt_dt_s", payload["database"])

    def test_fixed_demo_compiles_through_public_assembly_tool(self) -> None:
        payload = blast_plate_demo_payload("phase12_blast_demo_dry_run")
        result = tool_assemble_components({**payload, "dry_run": True})
        self.assertTrue(result["ok"])
        self.assertEqual(5, result["metadata"]["part_count"])
        self.assertEqual(1, result["metadata"]["blast_count"])


if __name__ == "__main__":
    unittest.main()
