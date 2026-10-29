from __future__ import annotations

import numpy as np


class FakeD3plotFactory:
    def __init__(self, arrays):
        self.source = {name: np.asarray(value) for name, value in arrays.items()}
        self.calls = []

    def __call__(
        self,
        filepath=None,
        *,
        state_array_filter=None,
        state_filter=None,
        buffered_reading=False,
        **kwargs,
    ):
        self.calls.append(
            {
                "filepath": filepath,
                "state_array_filter": tuple(state_array_filter or ()),
                "state_filter": None if state_filter is None else frozenset(state_filter),
                "buffered_reading": buffered_reading,
                **kwargs,
            }
        )
        geometry_names = {
            "node_ids",
            "node_coordinates",
            "part_ids",
            "element_solid_ids",
            "element_solid_node_indexes",
            "element_solid_part_indexes",
            "element_shell_ids",
            "element_shell_node_indexes",
            "element_shell_part_indexes",
            "element_beam_ids",
            "element_beam_node_indexes",
            "element_beam_part_indexes",
        }
        selected = set(state_array_filter or ()) | geometry_names
        arrays = {}
        for name, value in self.source.items():
            if name not in selected:
                continue
            if state_filter is not None and name not in geometry_names:
                indexes = sorted(state_filter)
                arrays[name] = np.array(value[indexes], copy=True)
            else:
                arrays[name] = np.array(value, copy=True)
        return FakeD3plot(arrays)


class FakeD3plot:
    def __init__(self, arrays):
        self.arrays = arrays
