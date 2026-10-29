import unittest
from pathlib import Path

import numpy as np

from blast_damage_assessment.errors import ContractError
from blast_damage_assessment.adapters.lsdyna.d3plot_reader import LassoD3plotReader
from packages.blast_damage_assessment.tests.fakes.fake_lasso import FakeD3plotFactory


def base_arrays():
    coordinates = np.array([[10.0, 0.0, 0.0], [11.0, 0.0, 0.0]])
    return {
        "timesteps": np.array([0.0, 0.5, 1.0]),
        "node_ids": np.array([101, 102]),
        "node_coordinates": coordinates,
        "part_ids": np.array([8001]),
        "element_solid_ids": np.array([201]),
        "element_solid_node_indexes": np.array([[0, 1, 1, 0, 0, 1, 1, 0]]),
        "element_solid_part_indexes": np.array([0]),
        "element_shell_ids": np.array([], dtype=int),
        "element_shell_node_indexes": np.empty((0, 4), dtype=int),
        "element_shell_part_indexes": np.array([], dtype=int),
        "element_beam_ids": np.array([], dtype=int),
        "element_beam_node_indexes": np.empty((0, 5), dtype=int),
        "element_beam_part_indexes": np.array([], dtype=int),
        "node_displacement": np.array(
            [coordinates, coordinates + [0.25, 0.0, 0.0], coordinates + [0.5, 0.0, 0.0]]
        ),
        "node_velocity": np.zeros((3, 2, 3)),
        "element_solid_stress": np.ones((3, 1, 6)),
    }


class D3plotReaderTests(unittest.TestCase):
    def reader(self, changes=None):
        arrays = base_arrays()
        if changes:
            arrays.update(changes)
        factory = FakeD3plotFactory(arrays)
        return LassoD3plotReader(Path("fake/d3plot"), d3plot_factory=factory), factory

    def test_node_displacement_is_interpreted_as_current_position(self):
        reader, _ = self.reader()
        chunk = next(reader.iter_state_chunks("node_kinematics", 2))
        np.testing.assert_allclose(
            chunk.values["node_displacement_m"],
            [[[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]], [[0.25, 0.0, 0.0], [0.25, 0.0, 0.0]]],
        )

    def test_missing_shell_strain_is_unavailable_not_zero(self):
        reader, _ = self.reader()
        probe = reader.probe()
        self.assertFalse(probe.fields["shell_strain"].available)
        self.assertEqual("d3plot field is absent", probe.fields["shell_strain"].reason)

    def test_reads_explicit_state_chunks_and_field_groups(self):
        reader, factory = self.reader()
        chunks = list(reader.iter_state_chunks("solid_response", 2))
        self.assertEqual([chunk.times.tolist() for chunk in chunks], [[0.0, 0.5], [1.0]])
        self.assertEqual(chunks[0].fields["solid_stress_pa"].source_field_name, "element_solid_stress")
        state_calls = [call for call in factory.calls if call["state_filter"] is not None]
        self.assertTrue(all(call["buffered_reading"] for call in factory.calls))
        self.assertIn(frozenset({0, 1}), [call["state_filter"] for call in state_calls])
        self.assertIn(frozenset({2}), [call["state_filter"] for call in state_calls])

    def test_geometry_maps_part_indexes_to_part_ids(self):
        reader, _ = self.reader()
        geometry = reader.read_geometry()
        np.testing.assert_array_equal(geometry.part_ids["solid"], [8001])
        np.testing.assert_array_equal(geometry.connectivity["solid"], [[0, 1, 1, 0, 0, 1, 1, 0]])

    def test_rejects_duplicate_nodes_unknown_connectivity_and_part_mismatch(self):
        cases = (
            ({"node_ids": np.array([101, 101])}, "duplicate node"),
            ({"element_solid_node_indexes": np.array([[0, 2, 1, 0, 0, 1, 1, 0]])}, "unknown node"),
            ({"element_solid_part_indexes": np.array([], dtype=int)}, "Part mapping"),
        )
        for changes, message in cases:
            with self.subTest(message=message):
                reader, _ = self.reader(changes)
                with self.assertRaisesRegex(ContractError, message):
                    reader.read_geometry()

    def test_rejects_decreasing_time_and_nonzero_initial_displacement(self):
        reader, _ = self.reader({"timesteps": np.array([0.0, 1.0, 0.5])})
        with self.assertRaisesRegex(ContractError, "decreases"):
            reader.probe()
        positions = base_arrays()["node_displacement"].copy()
        positions[0, 0, 0] += 0.01
        reader, _ = self.reader({"node_displacement": positions})
        with self.assertRaisesRegex(ContractError, "initial displacement"):
            reader.probe()

    def test_rejects_invalid_group_and_chunk_size(self):
        reader, _ = self.reader()
        with self.assertRaisesRegex(ContractError, "field group"):
            next(reader.iter_state_chunks("unknown", 1))
        with self.assertRaisesRegex(ContractError, "chunk_size"):
            next(reader.iter_state_chunks("node_kinematics", 0))


if __name__ == "__main__":
    unittest.main()
