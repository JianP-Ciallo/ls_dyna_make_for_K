"""Spreadsheet-safe UTF-8 CSV renderers."""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping


def _safe(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _metrics(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    return ";".join(f"{key}={value[key]}" for key in sorted(value))




def _csv_bytes(headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_safe(value) for value in row])
    return stream.getvalue().encode("utf-8-sig")


def render_building_csv(snapshot: Mapping[str, object]) -> bytes:
    building = snapshot.get("building", {})
    components = building.get("components", []) if isinstance(building, Mapping) else []
    rows: list[tuple[object, ...]] = []
    for item in components if isinstance(components, list) else []:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            (
                item.get("component_id"),
                item.get("zone_id"),
                item.get("importance_class"),
                item.get("gate", building.get("gate") if isinstance(building, Mapping) else None),
                item.get("severity"),
                item.get("p99_relative_deformation"),
                item.get("affected_fraction"),
                _metrics(item.get("response_metrics")),
                ";".join(str(value) for value in item.get("rule_hits", [])),
            )
        )
    return _csv_bytes(
        (
            "component_id",
            "zone_id",
            "importance_class",
            "gate",
            "severity",
            "p99_relative_deformation",
            "affected_fraction",
            "response_metrics",
            "rule_hits",
        ),
        rows,
    )


def render_ground_csv(snapshot: Mapping[str, object]) -> bytes:
    ground = snapshot.get("ground", {})
    subratings = ground.get("subratings", {}) if isinstance(ground, Mapping) else {}
    rows: list[tuple[object, ...]] = []
    if isinstance(subratings, Mapping):
        for name in sorted(subratings):
            item = subratings[name]
            if not isinstance(item, Mapping):
                continue
            rows.append(
                (
                    name,
                    ground.get("gate"),
                    item.get("available"),
                    item.get("severity"),
                    item.get("reason"),
                    item.get("metric_name"),
                    item.get("actual_value"),
                    _metrics(ground.get("material_metrics")),
                    ";".join(str(value) for value in item.get("rule_hits", [])),
                )
            )
    return _csv_bytes(
        (
            "region_or_subrating",
            "gate",
            "available",
            "severity",
            "reason",
            "metric_name",
            "actual_value",
            "material_metrics",
            "rule_hits",
        ),
        rows,
    )
