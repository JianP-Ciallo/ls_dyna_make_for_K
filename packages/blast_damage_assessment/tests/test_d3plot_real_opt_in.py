import os
import unittest
from pathlib import Path

import numpy as np

from blast_damage_assessment.adapters.lsdyna.d3plot_reader import LassoD3plotReader
from blast_damage_assessment.adapters.lsdyna.text_results import parse_d3hsp


@unittest.skipUnless(os.environ.get("BLAST_DAMAGE_REAL_CASE"), "set BLAST_DAMAGE_REAL_CASE to opt in")
class RealD3plotSmokeTests(unittest.TestCase):
    def test_real_case_geometry_time_and_public_records(self):
        result_dir = Path(os.environ["BLAST_DAMAGE_REAL_CASE"])
        reader = LassoD3plotReader(result_dir / "d3plot")
        probe = reader.probe()
        self.assertGreater(probe.geometry.node_ids.size, 0)
        self.assertGreater(sum(ids.size for ids in probe.geometry.element_ids.values()), 0)
        expected = parse_d3hsp(result_dir / "d3hsp").problem_time
        self.assertIsNotNone(expected)
        exact_expected = os.environ.get("BLAST_DAMAGE_EXPECTED_END_TIME")
        expected = float(exact_expected) if exact_expected else expected
        tolerance = max(1e-9, 1e-6 * expected) if exact_expected else max(5e-8, 1e-6 * expected)
        self.assertAlmostEqual(probe.timesteps[-1], expected, delta=tolerance)
        first = next(reader.iter_state_chunks("node_kinematics", 1))
        self.assertLessEqual(float(np.max(np.abs(first.values["node_displacement_m"]))), 1e-9)
        for value in (probe, first, probe.geometry):
            self.assertFalse(type(value).__module__.startswith("lasso"))


if __name__ == "__main__":
    unittest.main()
