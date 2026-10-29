"""Package-layer surface refinement for Phase 18D detailed buildings."""

from __future__ import annotations

import copy
import math
from collections.abc import Iterable, Mapping, Sequence

from .artifacts import BuildingArtifact
from .contracts import JSONDict


_SURFACE_KEYS = (
    "exterior_surfaces",
    "interior_cavity_surfaces",
    "opening_boundaries",
    "ground_contact_surfaces",
    "unclassified_boundary_surfaces",
)


def build_refined_asset_surface_catalog(
    artifacts: Iterable[BuildingArtifact],
) -> JSONDict:
    """Deep-copy and refine 18C catalogs without mutating child artifacts."""

    source = tuple(artifacts)
    if not source:
        raise ValueError("at least one building artifact is required")
    combined: dict[str, list[JSONDict]] = {key: [] for key in _SURFACE_KEYS}
    artifact_rows: list[JSONDict] = []
    for artifact in source:
        refined = _refine_one(artifact)
        artifact_rows.append(
            {
                "asset_id": artifact.asset_id,
                "source_artifact_fingerprint": artifact.fingerprint,
                "moved_to_interior_count": refined.pop("moved_to_interior_count"),
            }
        )
        for key in _SURFACE_KEYS:
            rows = refined[key]
            assert isinstance(rows, list)
            for row in rows:
                assert isinstance(row, dict)
                tagged = copy.deepcopy(row)
                tagged.setdefault("artifact_id", artifact.asset_id)
                combined[key].append(tagged)
    for key in _SURFACE_KEYS:
        combined[key].sort(
            key=lambda row: (str(row.get("artifact_id", "")), str(row.get("face_id", "")))
        )
    user_selectable = sorted(
        (copy.deepcopy(row) for key in _SURFACE_KEYS for row in combined[key]),
        key=lambda row: (str(row.get("artifact_id", "")), str(row.get("face_id", ""))),
    )
    return {
        "schema_version": "1.0.0",
        **combined,
        "user_selectable_surfaces": user_selectable,
        "artifact_refinement": artifact_rows,
    }


def _refine_one(artifact: BuildingArtifact) -> JSONDict:
    catalog = copy.deepcopy(artifact.surface_catalog)
    for key in _SURFACE_KEYS:
        if not isinstance(catalog.get(key), list):
            raise ValueError(f"artifact surface catalog {key!r} must be a list")
    spaces = _space_bounds(artifact)
    probe_epsilon = _probe_epsilon(artifact, spaces)
    unclassified = catalog["unclassified_boundary_surfaces"]
    interior = catalog["interior_cavity_surfaces"]
    assert isinstance(unclassified, list) and isinstance(interior, list)
    retained: list[JSONDict] = []
    moved: list[JSONDict] = []
    for raw in unclassified:
        if not isinstance(raw, Mapping):
            raise ValueError("unclassified surface rows must be mappings")
        row = copy.deepcopy(dict(raw))
        if _face_probes_enter_declared_space(row, spaces, probe_epsilon):
            moved.append(row)
        else:
            retained.append(row)
    interior.extend(moved)
    interior.sort(key=lambda row: str(row["face_id"]))
    retained.sort(key=lambda row: str(row["face_id"]))
    catalog["unclassified_boundary_surfaces"] = retained
    catalog["moved_to_interior_count"] = len(moved)
    catalog["user_selectable_surfaces"] = sorted(
        (
            copy.deepcopy(row)
            for key in _SURFACE_KEYS
            for row in catalog[key]  # type: ignore[union-attr]
        ),
        key=lambda row: str(row["face_id"]),
    )
    return catalog


def _space_bounds(artifact: BuildingArtifact) -> tuple[tuple[float, ...], ...]:
    raw_spaces = artifact.normalized_input.get("spaces")
    if not isinstance(raw_spaces, list):
        raise ValueError("artifact normalized spaces must be a list")
    result: list[tuple[float, ...]] = []
    for row in raw_spaces:
        if not isinstance(row, Mapping):
            raise ValueError("artifact normalized space rows must be mappings")
        bounds = row.get("bounds_m")
        if not isinstance(bounds, list) or len(bounds) != 6:
            raise ValueError("artifact normalized space bounds must contain six values")
        result.append(tuple(float(value) for value in bounds))
    return tuple(result)


def _face_probes_enter_declared_space(
    row: Mapping[str, object],
    spaces: Sequence[Sequence[float]],
    epsilon: float,
) -> bool:
    centroid = row.get("centroid_m")
    normal = row.get("normal")
    if not _three_finite_numbers(centroid) or not _three_finite_numbers(normal):
        return False
    centroid_values = tuple(float(value) for value in centroid)  # type: ignore[arg-type]
    normal_values = tuple(float(value) for value in normal)  # type: ignore[arg-type]
    magnitude = math.sqrt(sum(value * value for value in normal_values))
    if magnitude <= 1.0e-12:
        return False
    unit = tuple(value / magnitude for value in normal_values)
    probes = (
        tuple(centroid_values[index] + epsilon * unit[index] for index in range(3)),
        tuple(centroid_values[index] - epsilon * unit[index] for index in range(3)),
    )
    return any(_strictly_inside_box(probe, bounds) for probe in probes for bounds in spaces)


def _probe_epsilon(
    artifact: BuildingArtifact,
    spaces: Sequence[Sequence[float]],
) -> float:
    minimum_space_extent = min(
        bounds[axis + 3] - bounds[axis]
        for bounds in spaces
        for axis in range(3)
    )
    mesh_target = minimum_space_extent
    profile = artifact.normalized_input.get("structural_system")
    if isinstance(profile, Mapping):
        parameters = profile.get("parameters")
        if isinstance(parameters, Mapping):
            raw_target = parameters.get("mesh_size_m")
            if (
                not isinstance(raw_target, bool)
                and isinstance(raw_target, (int, float))
                and math.isfinite(float(raw_target))
                and float(raw_target) > 0.0
            ):
                mesh_target = float(raw_target)
    return max(1.0e-12, min(minimum_space_extent, mesh_target) * 1.0e-6)


def _strictly_inside_box(point: Sequence[float], bounds: Sequence[float]) -> bool:
    tolerance = 1.0e-10
    return all(
        bounds[axis] + tolerance < point[axis] < bounds[axis + 3] - tolerance
        for axis in range(3)
    )


def _three_finite_numbers(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 3
        and all(
            not isinstance(item, bool)
            and isinstance(item, (int, float))
            and math.isfinite(float(item))
            for item in value
        )
    )
