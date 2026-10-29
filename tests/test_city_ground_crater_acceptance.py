from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from lsprepost_mcp.city_ground_crater_acceptance import (
    _parse_eroding_element_history,
    evaluate_city_ground_crater,
)


class CityGroundCraterAcceptanceTests(unittest.TestCase):
    def metadata(self) -> dict:
        return {
            "mode": "validation_crater",
            "local_mesh_size_m": 0.20,
            "eroding_part_id": 90,
            "part_element_counts": {"90": 2},
            "probe_solid_ids": [101, 102],
            "history_node_ids": [201, 202],
            "eroding_fsi": {
                "surface_id": 91,
                "initial_exposed_segment_count": 12,
            },
            "peripheral_fsi": {
                "surface_id": 92,
                "exposed_segment_count": 20,
            },
        }

    def dbfsi_text(self) -> str:
        return """
 Fluid-structure interaction output
 time= 0.000000E+00
 91 0.000000E+00 0.000000E+00 0 0 0
 92 0.000000E+00 0.000000E+00 0 0 0
 time= 1.000000E-03
 91 2.000000E+06 2.000000E+05 0 0 0
 92 1.000000E+06 1.000000E+05 0 0 0
 time= 2.000000E-03
 91 1.000000E+06 1.000000E+05 0 0 0
 92 5.000000E+05 5.000000E+04 0 0 0
"""

    def elout_text(self, *, delete_one: bool = True) -> str:
        final_second = "" if delete_one else """
   102-     90
 1- 15 plastic -2.0E+06 -2.0E+06 -2.0E+06 0 0 0 3.0E-02
"""
        return f"""
 e l e m e n t   s t r e s s   c a l c u l a t i o n s   f o r   t i m e  s t e p 1 ( at time 0.000000E+00 )
   101-     90
 1- 15 elastic 0 0 0 0 0 0 0
   102-     90
 1- 15 elastic 0 0 0 0 0 0 0
 e l e m e n t   s t r e s s   c a l c u l a t i o n s   f o r   t i m e  s t e p 2 ( at time 1.000000E-03 )
   101-     90
 1- 15 plastic -3.0E+06 -2.0E+06 -1.0E+06 0 0 0 2.0E-02
   102-     90
 1- 15 plastic -2.0E+06 -2.0E+06 -2.0E+06 0 0 0 3.0E-02
 e l e m e n t   s t r e s s   c a l c u l a t i o n s   f o r   t i m e  s t e p 3 ( at time 2.000000E-03 )
   101-     90
 1- 15 plastic -4.0E+06 -3.0E+06 -2.0E+06 0 0 0 5.0E-02
{final_second}
"""

    def nodout_text(self) -> str:
        return """
 n o d a l   p r i n t   o u t   f o r   t i m e  s t e p 1 ( at time 0.000000E+00 )
 nodal point x-disp y-disp z-disp x-vel
 201 0 0 0 0
 202 0 0 0 0
 n o d a l   p r i n t   o u t   f o r   t i m e  s t e p 2 ( at time 1.000000E-03 )
 nodal point x-disp y-disp z-disp x-vel
 201 0 0 -3.000000E-03 0
 202 0 0 -1.000000E-03 0
"""

    def write_outputs(self, directory: Path, *, delete_one: bool = True) -> None:
        (directory / "dbfsi").write_text(self.dbfsi_text(), encoding="utf-8")
        (directory / "elout").write_text(
            self.elout_text(delete_one=delete_one),
            encoding="utf-8",
        )
        (directory / "nodout").write_text(self.nodout_text(), encoding="utf-8")

    def test_accepts_only_with_split_fsi_kc_response_downward_motion_and_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            self.write_outputs(run_dir)

            result = evaluate_city_ground_crater(run_dir, self.metadata())

        self.assertTrue(result["verified"])
        self.assertEqual(1, result["element_deletion"]["deleted_element_count"])
        self.assertGreater(result["ground_motion"]["maximum_downward_displacement_m"], 0.002)
        self.assertGreater(result["kc_response"]["peak_kc_scaled_damage"], 0.0)

    def test_rejects_when_elements_do_not_delete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            self.write_outputs(run_dir, delete_one=False)

            result = evaluate_city_ground_crater(run_dir, self.metadata())

        self.assertFalse(result["verified"])
        self.assertIn("city_ground_element_deletion", result["blocking_check_ids"])

    def test_rejects_metadata_that_does_not_bind_initial_element_count(self) -> None:
        metadata = deepcopy(self.metadata())
        metadata["part_element_counts"]["90"] = 3
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            self.write_outputs(run_dir)

            result = evaluate_city_ground_crater(run_dir, metadata)

        self.assertFalse(result["verified"])
        self.assertIn("city_ground_initial_element_evidence", result["blocking_check_ids"])

    def test_element_deletion_parser_accepts_a_fully_eroded_final_state(self) -> None:
        result = _parse_eroding_element_history(
            """
 e l e m e n t   s t r e s s   c a l c u l a t i o n s   f o r   t i m e  s t e p 1 ( at time 0.000000E+00 )
   101-     90
 1- 15 elastic 0 0 0 0 0 0 0
   102-     90
 1- 15 elastic 0 0 0 0 0 0 0
 e l e m e n t   s t r e s s   c a l c u l a t i o n s   f o r   t i m e  s t e p 2 ( at time 1.000000E-03 )
""",
            90,
        )

        self.assertEqual(2, result["deleted_element_count"])
        self.assertEqual(0, result["final_element_count"])

    def test_rejects_deletion_evidence_with_unexpected_element_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            self.write_outputs(run_dir)
            with (run_dir / "elout").open("a", encoding="utf-8") as handle:
                handle.write(
                    "   103-     90\n"
                    " 1- 15 plastic -4.0E+06 -3.0E+06 -2.0E+06 0 0 0 5.0E-02\n"
                )

            result = evaluate_city_ground_crater(run_dir, self.metadata())

        self.assertFalse(result["verified"])
        self.assertIn("city_ground_element_deletion", result["blocking_check_ids"])
        self.assertEqual(
            [103],
            result["element_deletion"]["unexpected_added_element_ids"],
        )


if __name__ == "__main__":
    unittest.main()
