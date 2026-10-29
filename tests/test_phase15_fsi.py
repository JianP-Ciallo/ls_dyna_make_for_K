from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from lsprepost_mcp.phase15 import default_phase15_a1_inputs
from lsprepost_mcp.phase15_fsi import (
    FSI_SURFACE_NAMES,
    build_phase15_fsi_surfaces,
    evaluate_phase15_wave_transfer,
    parse_phase15_ale_elout,
    parse_phase15_elout,
    validate_phase15_fsi_surfaces,
)
from lsprepost_mcp.phase15_keyword import compile_phase15_a1_solver_model


class Phase15FsiTopologyTests(unittest.TestCase):
    def setUp(self) -> None:
        inputs = default_phase15_a1_inputs()
        inputs["consistency_mode"] = "mass_priority_adjust_length"
        self.model = compile_phase15_a1_solver_model(inputs)
        self.concrete_elements = [
            element for element in self.model["elements"] if int(element[1]) == 3
        ]
        self.coordinates = {
            int(node[0]): (float(node[1]), float(node[2]), float(node[3]))
            for node in self.model["nodes"]
        }

    def build_surfaces(self):
        return build_phase15_fsi_surfaces(
            self.concrete_elements,
            self.coordinates,
            self.model["geometry"],
            mesh_size_m=float(self.model["mesh_size_m"]),
        )

    def test_extracts_all_three_nonempty_connected_surfaces(self) -> None:
        surfaces = self.build_surfaces()

        for name in FSI_SURFACE_NAMES:
            self.assertGreater(len(surfaces[name]), 0, name)
        self.assertEqual(
            len(surfaces["all_segments"]),
            sum(len(surfaces[name]) for name in FSI_SURFACE_NAMES),
        )
        self.assertEqual(
            [],
            validate_phase15_fsi_surfaces(
                surfaces,
                self.concrete_elements,
                self.coordinates,
                self.model["geometry"],
                mesh_size_m=float(self.model["mesh_size_m"]),
            ),
        )

    def test_each_segment_is_a_unique_concrete_exterior_edge(self) -> None:
        surfaces = self.build_surfaces()
        edge_counts: dict[tuple[int, int], int] = {}
        for element in self.concrete_elements:
            nodes = [int(value) for value in element[2:6]]
            for first, second in zip(nodes, nodes[1:] + nodes[:1]):
                edge = tuple(sorted((first, second)))
                edge_counts[edge] = edge_counts.get(edge, 0) + 1

        normalized = [tuple(sorted(segment)) for segment in surfaces["all_segments"]]
        self.assertEqual(len(normalized), len(set(normalized)))
        self.assertTrue(all(first != second for first, second in surfaces["all_segments"]))
        self.assertTrue(all(edge_counts[edge] == 1 for edge in normalized))

    def test_rejects_duplicate_and_non_exterior_segments(self) -> None:
        surfaces = self.build_surfaces()
        duplicate = deepcopy(surfaces)
        duplicate["concrete_top"].append(list(duplicate["charge_bottom"][0]))
        duplicate["all_segments"].append(list(duplicate["charge_bottom"][0]))

        duplicate_issues = validate_phase15_fsi_surfaces(
            duplicate,
            self.concrete_elements,
            self.coordinates,
            self.model["geometry"],
            mesh_size_m=float(self.model["mesh_size_m"]),
        )
        self.assertIn("fsi_segment_duplicate", {issue["id"] for issue in duplicate_issues})

        edge_counts: dict[tuple[int, int], int] = {}
        for element in self.concrete_elements:
            nodes = [int(value) for value in element[2:6]]
            for first, second in zip(nodes, nodes[1:] + nodes[:1]):
                edge = tuple(sorted((first, second)))
                edge_counts[edge] = edge_counts.get(edge, 0) + 1
        interior = next(edge for edge, count in edge_counts.items() if count == 2)
        invalid = deepcopy(surfaces)
        invalid["charge_bottom"][0] = list(interior)
        invalid["all_segments"][0] = list(interior)

        invalid_issues = validate_phase15_fsi_surfaces(
            invalid,
            self.concrete_elements,
            self.coordinates,
            self.model["geometry"],
            mesh_size_m=float(self.model["mesh_size_m"]),
        )
        self.assertIn("fsi_segment_not_exterior", {issue["id"] for issue in invalid_issues})

    def test_rejects_disconnected_surface(self) -> None:
        surfaces = self.build_surfaces()
        disconnected = deepcopy(surfaces)
        original = disconnected["borehole_wall"]
        self.assertGreater(len(original), 2)
        disconnected["borehole_wall"] = [original[0], original[-1]]
        disconnected["all_segments"] = [
            *disconnected["charge_bottom"],
            *disconnected["borehole_wall"],
            *disconnected["concrete_top"],
        ]

        issues = validate_phase15_fsi_surfaces(
            disconnected,
            self.concrete_elements,
            self.coordinates,
            self.model["geometry"],
            mesh_size_m=float(self.model["mesh_size_m"]),
        )
        self.assertIn("fsi_surface_disconnected", {issue["id"] for issue in issues})


class Phase15FsiResponseTests(unittest.TestCase):
    AIR_GAP_PROBES = [
        {"id": "TNT_NEAR", "element_id": 11},
        {"id": "AIR_MID_GAP", "element_id": 12},
        {"id": "AIR_INTERFACE", "element_id": 13},
    ]
    AIR_GAP_CONCRETE_PROBES = [
        {
            "id": "INTERFACE_WALL",
            "element_id": 101,
            "surface": "borehole_side",
        },
        {"id": "P1", "element_id": 102, "depth_from_top_m": 0.01},
        {"id": "P2", "element_id": 103, "depth_from_top_m": 0.02},
        {"id": "P3", "element_id": 104, "depth_from_top_m": 0.03},
    ]

    def air_gap_elout_text(
        self,
        *,
        interface_spike_only: bool = False,
        nonfinite_air: bool = False,
    ) -> str:
        states = [
            (1, 0.0, set(), set()),
            (2, 2.0e-6, set(), set()),
            (3, 4.0e-6, {"TNT_NEAR"}, set()),
            (4, 6.0e-6, {"TNT_NEAR", "AIR_MID_GAP"}, set()),
            (
                5,
                8.0e-6,
                {"TNT_NEAR", "AIR_MID_GAP", "AIR_INTERFACE"},
                {"INTERFACE_WALL"},
            ),
            (
                6,
                1.0e-5,
                (
                    {"TNT_NEAR", "AIR_MID_GAP"}
                    if interface_spike_only
                    else {"TNT_NEAR", "AIR_MID_GAP", "AIR_INTERFACE"}
                ),
                {"INTERFACE_WALL", "P1"},
            ),
            (
                7,
                1.2e-5,
                (
                    {"TNT_NEAR", "AIR_MID_GAP"}
                    if interface_spike_only
                    else {"TNT_NEAR", "AIR_MID_GAP", "AIR_INTERFACE"}
                ),
                {"INTERFACE_WALL", "P1", "P2"},
            ),
            (
                8,
                1.4e-5,
                (
                    {"TNT_NEAR", "AIR_MID_GAP"}
                    if interface_spike_only
                    else {"TNT_NEAR", "AIR_MID_GAP", "AIR_INTERFACE"}
                ),
                {"INTERFACE_WALL", "P1", "P2", "P3"},
            ),
            (
                9,
                1.6e-5,
                (
                    {"TNT_NEAR", "AIR_MID_GAP"}
                    if interface_spike_only
                    else {"TNT_NEAR", "AIR_MID_GAP", "AIR_INTERFACE"}
                ),
                {"INTERFACE_WALL", "P1", "P2", "P3"},
            ),
        ]
        air_ids = {probe["id"]: probe["element_id"] for probe in self.AIR_GAP_PROBES}
        concrete_ids = {
            probe["id"]: probe["element_id"]
            for probe in self.AIR_GAP_CONCRETE_PROBES
        }
        lines = []
        for state, time_s, active_air, active_concrete in states:
            lines.append(
                " e l e m e n t   s t r e s s   c a l c u l a t i o n s"
                f"   f o r   t i m e  s t e p {state} ( at time {time_s:.6E} )"
            )
            for probe_id, element_id in air_ids.items():
                value = "3.0E+06" if probe_id in active_air else "0"
                if nonfinite_air and state == 5 and probe_id == "AIR_INTERFACE":
                    value = "NaN"
                lines.extend(
                    [
                        f"   {element_id}-      1",
                        f" 1- 15 elastic  -{value} -{value} -{value} 0 0 0",
                    ]
                )
            for probe_id, element_id in concrete_ids.items():
                value = "3.0E+06" if probe_id in active_concrete else "0"
                lines.extend(
                    [
                        f"   {element_id}-      3",
                        f" 1- 15 elastic  -{value} -{value} -{value} 0 0 0 0",
                    ]
                )
        return "\n".join(lines)

    def air_gap_d3hsp_text(self) -> str:
        return """
 kinetic energy ............... 1.000000E+00
 internal energy .............. 1.000000E+00
 hourglass energy ............. 0.000000E+00
 total energy ................. 2.000000E+00
 total energy / initial energy  1.000000E+00
 *** normal termination ***
"""

    def air_gap_nodout_text(self, peak_time_s: float = 1.2e-5) -> str:
        return f"""
 n o d a l   p r i n t   o u t   f o r   t i m e  s t e p 1 ( at time 0.000000E+00 )
 nodal point  x-disp     y-disp      z-disp      x-vel
       201  0.000000E+00 0.000000E+00 0.000000E+00 0.0
 n o d a l   p r i n t   o u t   f o r   t i m e  s t e p 2 ( at time {peak_time_s:.6E} )
 nodal point  x-disp     y-disp      z-disp      x-vel
       201  2.000000E-06 0.000000E+00 0.000000E+00 0.0
"""

    def dbfsi_text(self, peak_pressure_pa: float = 2.0e6) -> str:
        return f"""
     Fluid-structure interaction output
     Number of surfaces:       1
         time=  0.00000E+00
         1    0.0000E+00    0.0000E+00    0.0000E+00    0.0000E+00    0.0000E+00
         time=  0.20000E-03
         1    {peak_pressure_pa:.6E}    1.0000E+06    0.0000E+00    0.0000E+00    0.0000E+00
"""

    def elout_text(
        self,
        *,
        final_stress: str = "-3.0E+06 -2.0E+06 -1.0E+06 5.0E+05 0 0",
        final_damage: str = "2.0E-02",
    ) -> str:
        return f"""
 e l e m e n t   s t r e s s   c a l c u l a t i o n s   f o r   t i m e  s t e p        1   ( at time 0.00000E+00 )
 element  materl(global)
   11153-      3
 1- 15 elastic   0 0 0 0 0 0 0
 e l e m e n t   s t r e s s   c a l c u l a t i o n s   f o r   t i m e  s t e p       20   ( at time 2.00000E-04 )
 element  materl(global)
   11153-      3
 1- 15 plastic  {final_stress} {final_damage}
"""

    def test_elout_reports_pressure_principal_stress_and_scaled_damage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "elout"
            path.write_text(self.elout_text(), encoding="utf-8")

            result = parse_phase15_elout(path, {11153})

        self.assertEqual(2, result["state_count"])
        self.assertEqual(2, result["sample_count"])
        self.assertAlmostEqual(
            2.0e6,
            result["peak_hydrostatic_pressure_response_pa"],
        )
        self.assertGreater(result["peak_principal_stress_response_pa"], 3.0e6)
        self.assertTrue(result["kc_scaled_damage_readable"])
        self.assertEqual(0.02, result["peak_kc_scaled_damage"])

    def test_elout_accepts_explicit_kc_material_id_and_still_filters_element_ids(self) -> None:
        text = self.elout_text().replace("-      3", "-     90")
        text += """
 e l e m e n t   s t r e s s   c a l c u l a t i o n s   f o r   t i m e  s t e p       21   ( at time 2.10000E-04 )
 element  materl(global)
   99999-     90
 1- 15 plastic  -9.0E+09 -9.0E+09 -9.0E+09 0 0 0 9.0E-01
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "elout"
            path.write_text(text, encoding="utf-8")

            result = parse_phase15_elout(path, {11153}, material_id=90)

        self.assertEqual(2, result["state_count"])
        self.assertEqual(2, result["sample_count"])
        self.assertEqual(0.02, result["peak_kc_scaled_damage"])

    def test_zero_stress_is_not_wave_transfer_but_zero_damage_is_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "d3hsp").write_text(
                """
 FSI Interface ID ...........................         1
 number of slave segments for coupling ......       193
 *** normal termination ***
""",
                encoding="utf-8",
            )
            (run_dir / "elout").write_text(
                self.elout_text(
                    final_stress="0 0 0 0 0 0",
                    final_damage="0",
                ),
                encoding="utf-8",
            )

            result = evaluate_phase15_wave_transfer(run_dir, {11153})

        self.assertFalse(result["wave_transfer_verified"])
        checks = {check["id"]: check for check in result["checks"]}
        self.assertFalse(checks["concrete_hydrostatic_pressure_response"]["ok"])
        self.assertFalse(checks["concrete_principal_stress_response"]["ok"])
        self.assertTrue(checks["kc_scaled_damage_readable"]["ok"])
        self.assertFalse(result["kc_scaled_damage"]["positive"])

    def test_positive_response_verifies_wave_transfer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "d3hsp").write_text(
                """
 FSI Interface ID ...........................         1
 number of slave segments for coupling ......       193
 *** normal termination ***
""",
                encoding="utf-8",
            )
            (run_dir / "elout").write_text(self.elout_text(), encoding="utf-8")
            (run_dir / "dbfsi").write_text(self.dbfsi_text(), encoding="utf-8")

            result = evaluate_phase15_wave_transfer(run_dir, {11153})

        self.assertTrue(result["wave_transfer_verified"])
        self.assertEqual(193, result["fsi"]["total_slave_segment_count"])
        self.assertTrue(result["kc_scaled_damage"]["positive"])

    def test_conforming_response_does_not_require_dbfsi(self) -> None:
        probes = [
            {"id": "P1", "element_id": 101, "depth_from_top_m": 0.01},
            {"id": "P2", "element_id": 102, "depth_from_top_m": 0.02},
            {"id": "P3", "element_id": 103, "depth_from_top_m": 0.03},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "d3hsp").write_text(
                "*** normal termination ***\n",
                encoding="utf-8",
            )
            states = [
                (1, 0.0, {101: "0 0 0 0 0 0", 102: "0 0 0 0 0 0", 103: "0 0 0 0 0 0"}),
                (10, 1.0e-4, {101: "-3e6 -2e6 -1e6 0 0 0", 102: "0 0 0 0 0 0", 103: "0 0 0 0 0 0"}),
                (20, 1.2e-4, {101: "-2e6 -1e6 -1e6 0 0 0", 102: "-3e6 -2e6 -1e6 0 0 0", 103: "0 0 0 0 0 0"}),
                (30, 1.4e-4, {101: "-1e6 -1e6 -1e6 0 0 0", 102: "-2e6 -1e6 -1e6 0 0 0", 103: "-3e6 -2e6 -1e6 0 0 0"}),
            ]
            elout = []
            for state, time_s, stresses in states:
                elout.append(
                    " e l e m e n t   s t r e s s   c a l c u l a t i o n s"
                    f"   f o r   t i m e  s t e p {state} ( at time {time_s:.6E} )"
                )
                for element_id, stress in stresses.items():
                    elout.extend(
                        [
                            f"   {element_id}-      3",
                            f" 1- 15 elastic  {stress} 1.0E-02",
                        ]
                    )
            (run_dir / "elout").write_text("\n".join(elout), encoding="utf-8")

            result = evaluate_phase15_wave_transfer(
                run_dir,
                {101, 102, 103},
                probe_metadata=probes,
                coupling_mode="conforming_shared_nodes",
            )

        self.assertTrue(result["wave_transfer_verified"])
        self.assertEqual("conforming_shared_nodes", result["coupling_mode"])
        check_ids = {check["id"] for check in result["checks"]}
        self.assertNotIn("fsi_interfaces_present", check_ids)
        self.assertNotIn("fsi_slave_segments_nonzero", check_ids)
        self.assertNotIn("fsi_coupling_pressure_response", check_ids)

    def test_low_interface_pressure_rejects_weak_fsi_transfer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "d3hsp").write_text(
                """
 FSI Interface ID ...........................         1
 number of slave segments for coupling ......       193
 *** normal termination ***
""",
                encoding="utf-8",
            )
            (run_dir / "elout").write_text(self.elout_text(), encoding="utf-8")
            (run_dir / "dbfsi").write_text(
                self.dbfsi_text(peak_pressure_pa=1.0e3),
                encoding="utf-8",
            )

            result = evaluate_phase15_wave_transfer(run_dir, {11153})

        self.assertFalse(result["wave_transfer_verified"])
        checks = {check["id"]: check for check in result["checks"]}
        self.assertFalse(checks["fsi_coupling_pressure_response"]["ok"])

    def test_propagation_gate_requires_ordered_principal_stress_arrivals(self) -> None:
        probes = [
            {"id": "P1", "element_id": 101, "depth_from_top_m": 1.26},
            {"id": "P2", "element_id": 102, "depth_from_top_m": 1.31},
            {"id": "P3", "element_id": 103, "depth_from_top_m": 1.36},
        ]
        states = [
            (1, 0.0, {101: "0 0 0 0 0 0", 102: "0 0 0 0 0 0", 103: "0 0 0 0 0 0"}),
            (10, 1.0e-4, {101: "-3e6 -2e6 -1e6 0 0 0", 102: "0 0 0 0 0 0", 103: "0 0 0 0 0 0"}),
            (20, 1.2e-4, {101: "-2e6 -1e6 -1e6 0 0 0", 102: "-3e6 -2e6 -1e6 0 0 0", 103: "0 0 0 0 0 0"}),
            (30, 1.4e-4, {101: "-1e6 -1e6 -1e6 0 0 0", 102: "-2e6 -1e6 -1e6 0 0 0", 103: "-3e6 -2e6 -1e6 0 0 0"}),
        ]
        elout = []
        for state, time_s, stresses in states:
            elout.append(
                " e l e m e n t   s t r e s s   c a l c u l a t i o n s"
                f"   f o r   t i m e  s t e p {state} ( at time {time_s:.6E} )"
            )
            for element_id, stress in stresses.items():
                elout.extend(
                    [
                        f"   {element_id}-      3",
                        f" 1- 15 elastic  {stress} 0",
                    ]
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "d3hsp").write_text(
                """
 FSI Interface ID ...........................         1
 number of slave segments for coupling ......       193
 *** normal termination ***
""",
                encoding="utf-8",
            )
            (run_dir / "elout").write_text("\n".join(elout), encoding="utf-8")
            (run_dir / "dbfsi").write_text(self.dbfsi_text(), encoding="utf-8")

            result = evaluate_phase15_wave_transfer(
                run_dir,
                {101, 102, 103},
                probe_metadata=probes,
            )

        self.assertTrue(result["wave_transfer_verified"])
        propagation = result["concrete_wave_propagation"]
        self.assertTrue(propagation["verified"])
        self.assertEqual(
            [1.0e-4, 1.2e-4, 1.4e-4],
            [arrival["first_arrival_time_s"] for arrival in propagation["arrivals"]],
        )

    def test_propagation_gate_rejects_local_response_only(self) -> None:
        probes = [
            {"id": "P1", "element_id": 101, "depth_from_top_m": 1.26},
            {"id": "P2", "element_id": 102, "depth_from_top_m": 1.31},
            {"id": "P3", "element_id": 103, "depth_from_top_m": 1.36},
        ]
        elout = """
 e l e m e n t   s t r e s s   c a l c u l a t i o n s   f o r   t i m e  s t e p 1 ( at time 0.000000E+00 )
   101-      3
 1- 15 elastic  0 0 0 0 0 0 0
   102-      3
 1- 15 elastic  0 0 0 0 0 0 0
   103-      3
 1- 15 elastic  0 0 0 0 0 0 0
 e l e m e n t   s t r e s s   c a l c u l a t i o n s   f o r   t i m e  s t e p 10 ( at time 1.000000E-04 )
   101-      3
 1- 15 elastic  -3e6 -2e6 -1e6 0 0 0 0
   102-      3
 1- 15 elastic  0 0 0 0 0 0 0
   103-      3
 1- 15 elastic  0 0 0 0 0 0 0
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "d3hsp").write_text(
                """
 FSI Interface ID ...........................         1
 number of slave segments for coupling ......       193
 *** normal termination ***
""",
                encoding="utf-8",
            )
            (run_dir / "elout").write_text(elout, encoding="utf-8")

            result = evaluate_phase15_wave_transfer(
                run_dir,
                {101, 102, 103},
                probe_metadata=probes,
            )

        self.assertFalse(result["wave_transfer_verified"])
        checks = {check["id"]: check for check in result["checks"]}
        self.assertFalse(checks["concrete_principal_wave_propagation"]["ok"])

    def test_nonfinite_or_missing_damage_data_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "elout"
            path.write_text(
                self.elout_text(final_damage="NaN"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "finite"):
                parse_phase15_elout(path, {11153})

            path.write_text(
                self.elout_text().replace(" 2.0E-02", ""),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "scaled damage"):
                parse_phase15_elout(path, {11153})

    def test_air_gap_parser_requires_durable_ordered_pressure_arrivals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "elout"
            path.write_text(self.air_gap_elout_text(), encoding="utf-8")

            result = parse_phase15_ale_elout(path, self.AIR_GAP_PROBES)

        self.assertTrue(result["verified"])
        self.assertEqual(
            [4.0e-6, 6.0e-6, 8.0e-6],
            [
                probe["durable_arrival_time_s"]
                for probe in result["probe_responses"]
            ],
        )
        self.assertTrue(
            all(probe["consecutive_response_samples"] >= 2 for probe in result["probe_responses"])
        )

    def test_conforming_air_gap_verifies_full_transfer_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "d3hsp").write_text(
                self.air_gap_d3hsp_text(),
                encoding="utf-8",
            )
            (run_dir / "elout").write_text(
                self.air_gap_elout_text(),
                encoding="utf-8",
            )
            (run_dir / "nodout").write_text(
                self.air_gap_nodout_text(),
                encoding="utf-8",
            )

            result = evaluate_phase15_wave_transfer(
                run_dir,
                {101, 102, 103, 104},
                probe_metadata=self.AIR_GAP_CONCRETE_PROBES,
                ale_probe_metadata=self.AIR_GAP_PROBES,
                history_output_dt_s=2.0e-6,
                coupling_mode="conforming_air_gap",
            )

        self.assertTrue(result["wave_transfer_verified"])
        self.assertTrue(result["transfer_evidence"]["verified"])
        self.assertEqual(
            [
                "TNT_NEAR",
                "AIR_MID_GAP",
                "AIR_INTERFACE",
                "CONCRETE_INTERFACE",
            ],
            [
                arrival["probe_id"]
                for arrival in result["transfer_evidence"]["arrivals"]
            ],
        )
        self.assertTrue(result["kc_scaled_damage"]["readable"])
        self.assertFalse(result["kc_scaled_damage"]["positive"])

    def test_conforming_air_gap_rejects_one_state_interface_spike(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "d3hsp").write_text(
                self.air_gap_d3hsp_text(),
                encoding="utf-8",
            )
            (run_dir / "elout").write_text(
                self.air_gap_elout_text(interface_spike_only=True),
                encoding="utf-8",
            )
            (run_dir / "nodout").write_text(
                self.air_gap_nodout_text(),
                encoding="utf-8",
            )

            result = evaluate_phase15_wave_transfer(
                run_dir,
                {101, 102, 103, 104},
                probe_metadata=self.AIR_GAP_CONCRETE_PROBES,
                ale_probe_metadata=self.AIR_GAP_PROBES,
                history_output_dt_s=2.0e-6,
                coupling_mode="conforming_air_gap",
            )

        self.assertFalse(result["wave_transfer_verified"])
        checks = {check["id"]: check for check in result["checks"]}
        self.assertFalse(checks["ale_air_gap_pressure_progression"]["ok"])

    def test_conforming_air_gap_rejects_displacement_before_interface_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "d3hsp").write_text(
                self.air_gap_d3hsp_text(),
                encoding="utf-8",
            )
            (run_dir / "elout").write_text(
                self.air_gap_elout_text(),
                encoding="utf-8",
            )
            (run_dir / "nodout").write_text(
                self.air_gap_nodout_text(peak_time_s=2.0e-6),
                encoding="utf-8",
            )

            result = evaluate_phase15_wave_transfer(
                run_dir,
                {101, 102, 103, 104},
                probe_metadata=self.AIR_GAP_CONCRETE_PROBES,
                ale_probe_metadata=self.AIR_GAP_PROBES,
                history_output_dt_s=2.0e-6,
                coupling_mode="conforming_air_gap",
            )

        self.assertFalse(result["wave_transfer_verified"])
        checks = {check["id"]: check for check in result["checks"]}
        self.assertFalse(checks["concrete_displacement_after_interface_load"]["ok"])

    def test_air_gap_parser_rejects_nonfinite_pressure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "elout"
            path.write_text(
                self.air_gap_elout_text(nonfinite_air=True),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "finite"):
                parse_phase15_ale_elout(path, self.AIR_GAP_PROBES)


if __name__ == "__main__":
    unittest.main()
