"""Nonphysical deterministic response fixtures for UI demonstration only.

The source controls index synthetic response patterns. No blast law, pressure
calculation, physical superposition, or engineering calibration is implemented.
"""
from __future__ import annotations

import numpy as np

from blast_damage_assessment.adapters.contracts import (
    AdapterProbe, ArrayField, EntityKind, FieldAvailability, GeometryIndex, SolverQuality, StateChunk,
)
from blast_damage_assessment.contracts import Issue
from lsprepost_mcp.damage_demo_scene import WARNING, box_nodes


class SyntheticDemoAdapter:
    adapter_id = "synthetic_demo"
    adapter_version = "1.0.0"

    def __init__(self, scene, inputs):
        self.inputs = inputs
        coordinates, cells, parts = [], [], []
        self.component_nodes = []
        for component in scene["components"]:
            if component["role"] == "ground":
                continue
            low, high = np.array(component["low"]), np.array(component["high"])
            axis = int(np.argmax(high-low))
            node_map, indexes = {}, []
            for division in range(4):
                left, right = low.copy(), high.copy()
                left[axis] = low[axis] + (high[axis]-low[axis])*division/4
                right[axis] = low[axis] + (high[axis]-low[axis])*(division+1)/4
                cell = []
                for xyz in box_nodes(left, right):
                    key = tuple(xyz)
                    if key not in node_map:
                        node_map[key] = len(coordinates)
                        coordinates.append(xyz)
                        indexes.append(node_map[key])
                    cell.append(node_map[key])
                cells.append(cell)
                parts.append(component["part_id"])
            self.component_nodes.append((component, indexes))
        ground_start = len(coordinates)
        for z in (-.6, 0.):
            for y in np.linspace(-12, 12, 9):
                for x in np.linspace(-12, 12, 9):
                    coordinates.append([x, y, z])
        for y in range(8):
            for x in range(8):
                n = ground_start+y*9+x
                cells.append([n, n+1, n+10, n+9, n+81, n+82, n+91, n+90])
                parts.append(8001+(x >= 4)+2*(y >= 4))
        empty = np.array([], dtype=np.int64)
        ids = np.arange(1, len(cells)+1, dtype=np.int64)
        self.geometry = GeometryIndex(
            np.arange(1, len(coordinates)+1, dtype=np.int64), np.array(coordinates, dtype=float),
            {EntityKind.SOLID: ids, EntityKind.SHELL: empty, EntityKind.BEAM: empty},
            {EntityKind.SOLID: np.array(parts, dtype=np.int64), EntityKind.SHELL: empty, EntityKind.BEAM: empty},
            {EntityKind.SOLID: np.array(cells, dtype=np.int64),
             EntityKind.SHELL: np.empty((0, 4), dtype=np.int64), EntityKind.BEAM: np.empty((0, 2), dtype=np.int64)})
        self.times = np.arange(8, dtype=float)  # Fixture time coordinates, not an event duration.
        self.displacement = np.zeros((8, len(coordinates), 3))
        xyz = self.geometry.initial_coordinates
        for component, indexes in self.component_nodes:
            center = (np.array(component["low"])+np.array(component["high"]))/2
            # Arbitrary UI stimulus pattern; its coefficients have no physical meaning.
            stimulus = self._pattern(center)
            strain = .0008 + .032*stimulus
            delta = xyz[indexes]-center
            self.displacement[1:, indexes, :] = delta * strain
        for index in range(ground_start+81, len(coordinates)):
            # Displacement stencil for the existing ground evaluator, not a crater model.
            self.displacement[1:, index, 2] = -.45*self._pattern(xyz[index], width=3.)
        self.velocity = np.zeros_like(self.displacement)
        self.velocity[1] = self.displacement[1]

    def _pattern(self, point, width=9.):
        values = []
        for source in self.inputs["sources"]:
            center = np.asarray(source["position_m"])
            proximity = float(np.exp(-np.sum(((point-center)/width)**2)))
            knob = .3 + .7*source["equivalent_kg"]/1000
            values.append(proximity*knob)
        return min(1.5, sum(values))

    def probe(self, result_dir):
        present = FieldAvailability(True, None)
        absent = FieldAvailability(False, "synthetic demo omits this field")
        fields = {name: absent for name in (
            "solid_stress", "solid_effective_plastic_strain", "solid_history_variables",
            "shell_stress", "shell_effective_plastic_strain", "shell_history_variables", "shell_strain",
            "shell_is_alive", "beam_axial_force", "beam_shear_force", "beam_is_alive")}
        fields.update(node_displacement=absent if self.inputs["mode"] == "blocked" else present,
                      node_velocity=present, solid_is_alive=present)
        return AdapterProbe(self.adapter_id, self.adapter_version, self.geometry, len(self.times), fields,
                            SolverQuality("normal", 7., 7., 7., 0.,
                                          (Issue("synthetic_demo_only", WARNING, {"synthetic_demo": True}),)))

    def iter_state_chunks(self, result_dir, chunk_size):
        geometry = self.geometry
        for start in range(0, len(self.times), chunk_size):
            stop = min(start+chunk_size, len(self.times))
            indexes = np.arange(start, stop, dtype=np.int64)
            fields = {}
            for name, values, unit, kind, ids in (
                ("node_displacement_m", self.displacement[start:stop], "m", EntityKind.NODE, geometry.node_ids),
                ("node_velocity_m_per_s", self.velocity[start:stop], "m/s", EntityKind.NODE, geometry.node_ids),
                ("solid_is_alive", np.ones((stop-start, len(geometry.element_ids[EntityKind.SOLID])), dtype=bool),
                 "1", EntityKind.SOLID, geometry.element_ids[EntityKind.SOLID]),
            ):
                fields[name] = ArrayField(kind, ids, indexes, values.copy(), unit, values.copy(), unit,
                                          "synthetic_demo.identity@1", "synthetic fixture: "+name, name)
            yield StateChunk(self.times[start:stop].copy(), fields)
