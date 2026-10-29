import tempfile
import unittest
from pathlib import Path

from blast_damage_assessment.adapters.contracts import FieldAvailability, StateChunk
from blast_damage_assessment.adapters.lsdyna.text_results import (
    parse_d3hsp,
    parse_dbfsi,
    parse_glstat,
    parse_matsum,
)


class TextResultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_d3hsp_parses_spaced_normal_termination_and_problem_time(self):
        result = parse_d3hsp(
            self.write(
                "d3hsp",
                "termination time........................ 1.0000E-03\n"
                "Problem time = 1.0018E-03\n"
                "N o r m a l    t e r m i n a t i o n\n",
            )
        )
        self.assertEqual(result.termination, "normal")
        self.assertAlmostEqual(result.problem_time, 1.0018e-3)
        self.assertAlmostEqual(result.termination_time, 1.0e-3)

    def test_adverse_or_sense_switch_termination_wins_over_normal_text(self):
        abnormal = parse_d3hsp(
            self.write("d3hsp", "normal termination\nABNORMAL TERMINATION\n")
        )
        self.assertEqual(abnormal.termination, "abnormal")
        sense = parse_d3hsp(
            self.write("d3hsp", "normal termination\ntermination due to sense switch\n")
        )
        self.assertEqual(sense.termination, "sense_switch")

    def test_configuration_description_does_not_fake_adverse_termination(self):
        result = parse_d3hsp(
            self.write("d3hsp", "eq.1: yes (error termination if detected)\nnormal termination\n")
        )
        self.assertEqual(result.termination, "normal")

    def test_glstat_parses_finite_energy_states_and_ratios(self):
        result = parse_glstat(
            self.write(
                "glstat",
                "time........................... 0.00000E+00\n"
                "kinetic energy................. 2.00000E+00\n"
                "internal energy................ 8.00000E+00\n"
                "hourglass energy .............. 5.00000E-01\n"
                "eroded kinetic energy.......... 1.00000E-01\n"
                "eroded internal energy......... 2.00000E-01\n"
                "total energy................... 1.00000E+01\n"
                "total energy / initial energy.. 1.00000E+00\n"
                "time........................... 1.00000E-03\n"
                "hourglass energy .............. 1.00000E+00\n"
                "total energy................... 2.00000E+01\n",
            )
        )
        self.assertEqual(len(result.records), 2)
        self.assertAlmostEqual(result.records[0].eroded_energy, 0.3)
        self.assertAlmostEqual(result.max_hourglass_ratio, 0.05)
        self.assertEqual(result.final_time, 1.0e-3)

    def test_matsum_parses_material_and_eroded_energy(self):
        result = parse_matsum(
            self.write(
                "matsum",
                "time = 1.0000E-03\n"
                "mat.#= 8001 inten= 1.0E+01 kinen= 2.0E+00 "
                "eroded_ie= 3.0E-01 eroded_ke= 2.0E-01\n",
            )
        )
        self.assertEqual(len(result.records), 1)
        record = result.records[0]
        self.assertEqual(record.material_id, 8001)
        self.assertEqual(record.eroded_energy, 0.5)

    def test_dbfsi_parses_surface_pressure_history(self):
        result = parse_dbfsi(
            self.write(
                "dbfsi",
                "time= 0.00000E+00\n"
                "1 0.0000E+00 0 0 0 0\n"
                "time= 0.50000E-03\n"
                "1 1.2500E+02 0 0 0 0\n",
            )
        )
        self.assertEqual([(r.time, r.surface_id, r.pressure) for r in result.records], [
            (0.0, 1, 0.0),
            (0.0005, 1, 125.0),
        ])

    def test_truncated_and_nonfinite_records_become_issues_not_values(self):
        result = parse_glstat(
            self.write(
                "glstat",
                "time........................... 0.0\n"
                "total energy................... NaN\n"
                "hourglass energy .............. 1.0\n",
            )
        )
        self.assertEqual(result.records, ())
        self.assertTrue(any(issue.code == "text.nonfinite" for issue in result.issues))
        self.assertTrue(any(issue.code == "glstat.incomplete_state" for issue in result.issues))

    def test_invalid_utf8_and_overlong_lines_are_reported(self):
        path = self.root / "d3hsp"
        path.write_bytes(b"\xffnormal termination\n" + b"x" * 80 + b"\n")
        result = parse_d3hsp(path, max_line_bytes=32)
        codes = {issue.code for issue in result.issues}
        self.assertIn("text.decode_replacement", codes)
        self.assertIn("text.line_too_long", codes)

    def test_package_records_reject_third_party_or_non_numpy_arrays(self):
        availability = FieldAvailability(True, None)
        with self.assertRaisesRegex(ValueError, "NumPy"):
            StateChunk(times=[0.0], fields={}, availability=availability)


if __name__ == "__main__":
    unittest.main()
