from __future__ import annotations

import unittest
import struct

from lsprepost_mcp.solver_results import (
    evaluate_solver_result,
    parse_ale_material_balance,
    parse_ale_pressure_probes,
    parse_blstfor,
    parse_city_object_responses,
    parse_dbfsi,
    parse_d3hsp,
    parse_fsi_interfaces,
    parse_nodout,
)


def d3hsp_block(
    *,
    kinetic: str = "2.0",
    internal: str = "100.0",
    hourglass: str = "3.0",
    total: str = "105.0",
    ratio: str = "1.0",
    terminated: bool = True,
) -> str:
    termination = "*** termination time reached ***" if terminated else ""
    return f"""
 kinetic energy.................   {kinetic}
 internal energy................   {internal}
 hourglass energy ..............   {hourglass}
 total energy...................   {total}
 total energy / initial energy..   {ratio}
 {termination}
"""


class SolverResultTests(unittest.TestCase):
    def test_parse_dbfsi_integrates_positive_pressure_rise(self) -> None:
        parsed = parse_dbfsi(
            "time=0\n111 0 0 0 0 0\n"
            "time=0.001\n111 1000 0 0 0 0\n"
            "time=0.002\n111 0 0 0 0 0\n"
        )

        self.assertAlmostEqual(
            1.0,
            parsed["surfaces"][0]["positive_pressure_impulse_pa_s"],
        )

    def test_parse_d3hsp_accepts_spaced_normal_termination_marker(self) -> None:
        parsed = parse_d3hsp(
            d3hsp_block(terminated=False)
            + "\n N o r m a l    t e r m i n a t i o n\n"
        )

        self.assertTrue(parsed["terminated_normally"])

    def test_parse_city_object_responses_keeps_objects_separate(self) -> None:
        response_objects = [
            {
                "object_id": "building_a",
                "fsi_surface_id": 111,
                "shell_element_ids": [101],
                "node_ids": [1001],
            },
            {
                "object_id": "building_b",
                "fsi_surface_id": 112,
                "shell_element_ids": [102],
                "node_ids": [1002],
            },
        ]
        dbfsi = """
 time = 0.000
 111 0 0 0 0 0
 112 0 0 0 0 0
 time = 0.001
 111 2000 20 0 0 0
 112 0 0 0 0 0
 time = 0.002
 111 1000 10 0 0 0
 112 800 8 0 0 0
"""
        elout = """
 element stress calculations for time step 1 ( at time 0.000 )
     101-      3
       1- 1 lower 0 0 0 0 0 0 0
     102-      3
       1- 1 lower 0 0 0 0 0 0 0
 element stress calculations for time step 2 ( at time 0.001 )
     101-      3
       1- 1 lower -300 -300 -300 0 0 0 0
     102-      3
       1- 1 lower 0 0 0 0 0 0 0
 element stress calculations for time step 3 ( at time 0.002 )
     101-      3
       1- 1 lower -200 -200 -200 0 0 0 0
     102-      3
       1- 1 lower -120 -120 -120 0 0 0 0
"""
        nodout = """
 nodal print out for time step 1 ( at time 0.000 )
 nodal point  x-disp     y-disp      z-disp      x-vel
 1001 0 0 0 0
 1002 0 0 0 0
 nodal print out for time step 2 ( at time 0.001 )
 nodal point  x-disp     y-disp      z-disp      x-vel
 1001 0.003 0.004 0 0
 1002 0 0 0 0
 nodal print out for time step 3 ( at time 0.002 )
 nodal point  x-disp     y-disp      z-disp      x-vel
 1001 0.002 0 0 0
 1002 0.001 0 0 0
"""

        result = parse_city_object_responses(
            dbfsi,
            elout,
            nodout,
            response_objects,
        )

        self.assertEqual(111, result["building_a"]["fsi_surface_id"])
        self.assertEqual(2000.0, result["building_a"]["peak_fsi_pressure_rise_pa"])
        self.assertEqual(300.0, result["building_a"]["peak_structural_pressure_pa"])
        self.assertEqual(300.0, result["building_a"]["peak_principal_stress_pa"])
        self.assertEqual(0.005, result["building_a"]["peak_displacement_m"])
        self.assertEqual(0.001, result["building_a"]["fsi_arrival_time_s"])
        self.assertEqual(0.002, result["building_b"]["fsi_arrival_time_s"])
        self.assertEqual(0.002, result["building_a"]["last_response_time_s"])

    def test_city_response_uses_later_elout_layer_peak_for_same_element(self) -> None:
        result = parse_city_object_responses(
            """
 time = 0.000
 111 0 0 0 0 0
 time = 0.001
 111 1000 0 0 0 0
""",
            """
 element stress calculations for time step 1 ( at time 0.000 )
     101-      3
       1- 1 lower 0 0 0 0 0 0 0
       1- 2 upper 0 0 0 0 0 0 0
 element stress calculations for time step 2 ( at time 0.001 )
     101-      3
       1- 1 lower -100 -100 -100 0 0 0 0
       1- 2 upper -300 -300 -300 0 0 0 0
""",
            "",
            [
                {
                    "object_id": "building",
                    "fsi_surface_id": 111,
                    "shell_element_ids": [101],
                    "node_ids": [],
                }
            ],
        )["building"]

        self.assertEqual(4, result["structural_sample_count"])
        self.assertEqual(300.0, result["peak_structural_pressure_pa"])
        self.assertEqual(300.0, result["peak_principal_stress_pa"])
        self.assertEqual(300.0, result["post_arrival_peak_structural_pressure_pa"])

    def test_city_response_does_not_treat_single_early_noise_sample_as_arrival(self) -> None:
        result = parse_city_object_responses(
            """
 time = 0.000
 111 0 0 0 0 0
 time = 0.001
 111 0 0 0 0 0
 time = 0.002
 111 1000 0 0 0 0
 time = 0.003
 111 1000 0 0 0 0
""",
            """
 element stress calculations for time step 1 ( at time 0.000 )
     101-      3
       1- 1 lower 0 0 0 0 0 0 0
 element stress calculations for time step 2 ( at time 0.001 )
     101-      3
       1- 1 lower -1 -1 -1 0 0 0 0
 element stress calculations for time step 3 ( at time 0.002 )
     101-      3
       1- 1 lower -500 -500 -500 0 0 0 0
 element stress calculations for time step 4 ( at time 0.003 )
     101-      3
       1- 1 lower -500 -500 -500 0 0 0 0
""",
            """
 nodal print out for time step 1 ( at time 0.000 )
 nodal point  x-disp     y-disp      z-disp      x-vel
 1001 0 0 0 0
""",
            [
                {
                    "object_id": "building",
                    "fsi_surface_id": 111,
                    "shell_element_ids": [101],
                    "node_ids": [1001],
                }
            ],
        )["building"]

        self.assertTrue(result["pre_arrival_quiet"])
        self.assertEqual(0.002, result["structural_arrival_time_s"])
        self.assertEqual(500.0, result["post_arrival_peak_structural_pressure_pa"])

    def test_city_response_flags_material_pre_arrival_response(self) -> None:
        result = parse_city_object_responses(
            """
 time = 0.000
 111 0 0 0 0 0
 time = 0.001
 111 0 0 0 0 0
 time = 0.002
 111 1000 0 0 0 0
 time = 0.003
 111 1000 0 0 0 0
""",
            """
 element stress calculations for time step 1 ( at time 0.000 )
     101-      3
       1- 1 lower 0 0 0 0 0 0 0
 element stress calculations for time step 2 ( at time 0.001 )
     101-      3
       1- 1 lower -1000 -1000 -1000 0 0 0 0
 element stress calculations for time step 3 ( at time 0.002 )
     101-      3
       1- 1 lower -500 -500 -500 0 0 0 0
 element stress calculations for time step 4 ( at time 0.003 )
     101-      3
       1- 1 lower -500 -500 -500 0 0 0 0
""",
            """
 nodal print out for time step 1 ( at time 0.000 )
 nodal point  x-disp     y-disp      z-disp      x-vel
 1001 0 0 0 0
""",
            [
                {
                    "object_id": "building",
                    "fsi_surface_id": 111,
                    "shell_element_ids": [101],
                    "node_ids": [1001],
                }
            ],
        )["building"]

        self.assertFalse(result["pre_arrival_quiet"])
        self.assertIsNone(result["structural_arrival_time_s"])

    def test_parse_fsi_interfaces_distinguishes_zero_positive_and_missing(self) -> None:
        zero = parse_fsi_interfaces(
            """
 FSI Interface ID ...........................         1
 number of slave segments for coupling ......         0
"""
        )
        positive = parse_fsi_interfaces(
            """
 FSI Interface ID ...........................         1
 number of slave segments for coupling ......       193
"""
        )
        missing = parse_fsi_interfaces("*** normal termination ***")

        self.assertEqual(0, zero["total_slave_segment_count"])
        self.assertFalse(zero["all_nonempty"])
        self.assertEqual(193, positive["total_slave_segment_count"])
        self.assertTrue(positive["all_nonempty"])
        self.assertEqual(0, missing["interface_count"])
        self.assertFalse(missing["all_nonempty"])

    def test_parse_fsi_interfaces_accepts_part_based_slave_definition(self) -> None:
        result = parse_fsi_interfaces(
            """
 FSI Interface ID ...........................         1
 number of slave materials ..................         1
 number of slave segments for coupling ......         0
"""
        )

        self.assertEqual(1, result["slave_material_count"])
        self.assertTrue(result["has_slave_definition"])
        self.assertEqual("part_or_material", result["slave_definition_mode"])
        self.assertFalse(result["all_nonempty"])

    def test_parse_fsi_interfaces_rejects_empty_slave_definition(self) -> None:
        result = parse_fsi_interfaces(
            """
 FSI Interface ID ...........................         1
 number of slave materials ..................         0
 number of slave segments for coupling ......         0
"""
        )

        self.assertFalse(result["has_slave_definition"])
        self.assertEqual("missing", result["slave_definition_mode"])

    def test_parse_fsi_interfaces_preserves_incomplete_interface_semantics(self) -> None:
        result = parse_fsi_interfaces(
            """
 FSI Interface ID ...........................         1
 number of slave materials ..................         1
"""
        )

        self.assertEqual(0, result["interface_count"])
        self.assertFalse(result["all_nonempty"])

    def test_parse_ale_material_balance_reports_numeric_drift(self) -> None:
        mass = "time air explosive\n0.0 10.0 1.0\n0.001 9.8 0.99\n0.002 9.5 0.98\n"
        volume = "time air explosive\n0.0 8.0 0.1\n0.001 7.9 0.1\n0.002 7.6 0.098\n"

        result = parse_ale_material_balance(mass, volume)

        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["maximum_absolute_relative_mass_change"], 0.05)
        self.assertAlmostEqual(result["maximum_absolute_relative_volume_change"], 0.05)

    def test_parse_ale_pressure_probes_reports_each_probe_peak(self) -> None:
        text = "time p1 p2\n0.0 0 0\n0.001 100 25\n0.002 50 80\n"

        result = parse_ale_pressure_probes(text, [1.7, 2.25])

        self.assertEqual(result["series_count"], 2)
        self.assertEqual(result["global_peak_pressure_pa"], 100.0)
        self.assertEqual(result["probes"][0]["peak_time_s"], 0.001)
        self.assertEqual(result["probes"][1]["probe_position_m"], 2.25)

    def test_parse_ale_xy_rejects_nonfinite_or_nonincreasing_data(self) -> None:
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            parse_ale_pressure_probes("0.0 1\n0.0 2\n")
        with self.assertRaisesRegex(ValueError, "finite"):
            parse_ale_pressure_probes("0.0 1\n0.1 NaN\n")

    def test_parse_blstfor_extracts_peak_duration_impulse_and_layout(self) -> None:
        words = bytearray(512 * 4)

        def integer(address: int, value: int) -> None:
            struct.pack_into("<i", words, address * 4, value)

        def number(address: int, value: float) -> None:
            struct.pack_into("<f", words, address * 4, value)

        integer(11, 6)
        integer(16, 4)
        integer(18, 0)
        integer(20, 0)
        integer(21, 0)
        integer(31, 1)
        integer(32, 1)
        integer(33, 7)
        integer(39, 0)
        connectivity = 64 + 3 * 4
        for offset, value in enumerate((1, 2, 3, 4, 1)):
            integer(connectivity + offset, value)
        first_state = connectivity + 5
        for state_index, (time_s, pressure_pa) in enumerate(
            ((0.0, 0.0), (0.001, 100.0), (0.002, 50.0), (0.003, -50.0))
        ):
            state = first_state + state_index * 8
            number(state, time_s)
            number(state + 1, pressure_pa)
        number(first_state + 4 * 8, -999999.0)

        result = parse_blstfor(bytes(words))

        self.assertTrue(result["ok"])
        self.assertEqual(4, result["state_count"])
        self.assertEqual(1, result["peak_segment_index"])
        self.assertEqual([1, 2, 3, 4], result["peak_segment_nodes"])
        self.assertEqual(100.0, result["sampled_peak_pressure_pa"])
        self.assertAlmostEqual(0.0025, result["positive_duration_s"])
        self.assertAlmostEqual(0.1375, result["positive_impulse_pa_s"])
        self.assertEqual("limited", result["positive_phase_quality"])

    def test_parse_blstfor_rejects_non_blstfor_binary(self) -> None:
        with self.assertRaisesRegex(ValueError, "could not be identified"):
            parse_blstfor(bytes(512 * 4))

    def test_parse_nodout_extracts_peak_resultant_displacement(self) -> None:
        text = """
 n o d a l   p r i n t   o u t   f o r   t i m e  s t e p       1 ( at time 0.0000000E+00 )
 nodal point  x-disp     y-disp      z-disp      x-vel
       10  0.00000E+00 0.00000E+00 0.00000E+00 0.0
 n o d a l   p r i n t   o u t   f o r   t i m e  s t e p      25 ( at time 1.0000000E-03 )
 nodal point  x-disp     y-disp      z-disp      x-vel
       10  3.00000E-03-4.00000E-03 0.00000E+00 0.0
       11  1.00000E-03 1.00000E-03 1.00000E-03 0.0
 n o d a l   p r i n t   o u t   f o r   t i m e  s t e p      25 ( at time 1.0000000E-03 )
 nodal point  x-rot      y-rot       z-rot
       10  9.00000E+00 9.00000E+00 9.00000E+00
"""

        result = parse_nodout(text)

        self.assertEqual(0.005, result["peak_displacement_m"])
        self.assertEqual(10, result["peak_node_id"])
        self.assertEqual(25, result["peak_time_step"])
        self.assertEqual(0.001, result["peak_time_s"])
        self.assertEqual(2, result["state_count"])
        self.assertEqual(3, result["sample_count"])

    def test_parse_d3hsp_extracts_final_and_max_energy(self) -> None:
        text = d3hsp_block(internal="50.0", hourglass="2.0") + d3hsp_block(internal="100.0", hourglass="7.0")
        parsed = parse_d3hsp(text)
        self.assertTrue(parsed["terminated_normally"])
        self.assertEqual(parsed["final"]["internal_energy"], 100.0)
        self.assertEqual(parsed["max_abs"]["hourglass_energy"], 7.0)
        self.assertTrue(parsed["finite"])

    def test_accepts_valid_impact_result(self) -> None:
        result = evaluate_solver_result(
            d3hsp_block(kinetic="80.0", internal="15.0", hourglass="5.0", total="100.0", ratio="1.01"),
            "impact",
        )
        self.assertTrue(result["ok"])
        self.assertLessEqual(result["metrics"]["hourglass_ratio"], 0.1)

    def test_accepts_valid_blast_result(self) -> None:
        result = evaluate_solver_result(
            d3hsp_block(kinetic="80.0", internal="15.0", hourglass="5.0", total="100.0", ratio="1.01"),
            "blast",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "blast")

    def test_blast_result_extracts_enhanced_blast_peak_from_d3hsp(self) -> None:
        text = (
            " enhanced blast # 1: pmax = 0.40174E+07 at time = 0.28444E-03\n"
            + d3hsp_block(kinetic="80.0", internal="15.0", hourglass="5.0", total="100.0", ratio="1.01")
        )

        result = evaluate_solver_result(text, "blast")

        self.assertEqual(4.0174e6, result["metrics"]["peak_blast_pressure_pa"])
        self.assertEqual(2.8444e-4, result["metrics"]["peak_blast_pressure_time_s"])
        self.assertEqual(1, result["metrics"]["peak_blast_id"])
        self.assertEqual(1, len(result["parsed"]["blast_peaks"]))

    def test_accepts_valid_quasi_static_result(self) -> None:
        result = evaluate_solver_result(d3hsp_block(), "quasi_static")
        self.assertTrue(result["ok"])
        self.assertEqual(result["metrics"]["kinetic_internal_ratio"], 0.02)

    def test_rejects_negative_internal_energy_despite_normal_termination(self) -> None:
        result = evaluate_solver_result(d3hsp_block(internal="-3.15E+08", hourglass="5.0E+07"), "quasi_static")
        self.assertFalse(result["ok"])
        by_id = {check["id"]: check for check in result["checks"]}
        self.assertFalse(by_id["internal_energy_nonnegative"]["ok"])

    def test_rejects_excessive_hourglass_energy(self) -> None:
        result = evaluate_solver_result(d3hsp_block(internal="100", hourglass="30"), "quasi_static")
        self.assertFalse(result["ok"])
        by_id = {check["id"]: check for check in result["checks"]}
        self.assertFalse(by_id["hourglass_energy_ratio"]["ok"])

    def test_rejects_nonfinite_energy_and_missing_termination(self) -> None:
        result = evaluate_solver_result(d3hsp_block(internal="NaN", terminated=False), "impact")
        self.assertFalse(result["ok"])
        by_id = {check["id"]: check for check in result["checks"]}
        self.assertFalse(by_id["normal_termination"]["ok"])
        self.assertFalse(by_id["finite_energies"]["ok"])

    def test_error_termination_configuration_text_is_not_an_error_marker(self) -> None:
        text = "eq.1: yes (error termination if detected)\n" + d3hsp_block()
        self.assertTrue(parse_d3hsp(text)["terminated_normally"])


if __name__ == "__main__":
    unittest.main()
