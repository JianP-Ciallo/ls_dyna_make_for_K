from __future__ import annotations

from .config import JSONDict
from .schema import ModelSpec
from .dyna_common import EDGE_AXES, Segment, format_id_lines

def edge_for_model(spec: ModelSpec, edge: str) -> str:
    # Backward compatibility: previous cylinder models used x_min to mean the z_min end cap.
    if spec.model_type in {"cylinder_shell", "cylinder_solid"} and edge == "x_min":
        return "z_min"
    if spec.model_type in {"cylinder_shell", "cylinder_solid"} and edge == "x_max":
        return "z_max"
    return edge


def nodes_for_edge(spec: ModelSpec, nodes: list[tuple[int, float, float, float]], edge: str) -> list[int]:
    effective_edge = edge_for_model(spec, edge)
    axis, side = EDGE_AXES[effective_edge]
    values = [item[axis + 1] for item in nodes]
    target = min(values) if side == "min" else max(values)
    span = max(values) - min(values)
    tol = max(abs(span) * 1e-9, 1e-12)
    selected = [nid for nid, x, y, z in nodes if abs((x, y, z)[axis] - target) <= tol]
    if not selected:
        raise ValueError(f"edge {edge} selected no nodes")
    return selected


def nodes_for_face_corners(
    spec: ModelSpec,
    nodes: list[tuple[int, float, float, float]],
    face: str,
) -> list[int]:
    effective_face = edge_for_model(spec, face)
    normal_axis, side = EDGE_AXES[effective_face]
    coordinate_rows = [(nid, (x, y, z)) for nid, x, y, z in nodes]
    minima = [min(coords[axis] for _, coords in coordinate_rows) for axis in range(3)]
    maxima = [max(coords[axis] for _, coords in coordinate_rows) for axis in range(3)]
    tolerances = [max(abs(maxima[axis] - minima[axis]) * 1e-9, 1e-12) for axis in range(3)]
    normal_target = minima[normal_axis] if side == "min" else maxima[normal_axis]
    tangent_axes = [axis for axis in range(3) if axis != normal_axis]

    selected: list[int] = []
    for nid, coords in coordinate_rows:
        if abs(coords[normal_axis] - normal_target) > tolerances[normal_axis]:
            continue
        if all(
            abs(coords[axis] - minima[axis]) <= tolerances[axis]
            or abs(coords[axis] - maxima[axis]) <= tolerances[axis]
            for axis in tangent_axes
        ):
            selected.append(nid)
    if len(selected) != 4:
        raise ValueError(f"face_corners selector {face} selected {len(selected)} nodes; expected 4")
    return sorted(selected)


def nodes_from_selector(
    spec: ModelSpec,
    nodes: list[tuple[int, float, float, float]],
    item: JSONDict,
) -> list[int]:
    if "node_ids" in item:
        return [int(value) for value in item["node_ids"]]
    nested_selector = item.get("selector")
    selector = nested_selector if isinstance(nested_selector, dict) else item
    selector_type = str(selector.get("type", "edge")) if isinstance(nested_selector, dict) else str(item.get("type", "edge"))
    if selector_type not in {"edge", "face_corners"} and "edge" in item:
        selector_type = "edge"
    if selector_type == "face_corners":
        return nodes_for_face_corners(spec, nodes, str(selector.get("face")))
    if selector_type == "edge":
        return nodes_for_edge(spec, nodes, str(selector.get("edge")))
    raise ValueError(f"unsupported node selector type: {selector_type}")


def edge_from_selector(item: JSONDict) -> str:
    selector = item.get("selector")
    if isinstance(selector, dict):
        return str(selector.get("edge"))
    return str(item.get("edge"))


def segment_selector(item: JSONDict) -> JSONDict:
    selector = item.get("selector")
    if isinstance(selector, dict):
        return selector
    if item.get("type") == "all_shell":
        return {"type": "all_shell"}
    if "face" in item:
        return {"type": "face", "face": item["face"]}
    return {"type": "all_shell"}


def segments_for_selector(
    spec: ModelSpec,
    nodes: list[tuple[int, float, float, float]],
    segments: list[Segment],
    selector: JSONDict,
) -> list[Segment]:
    if not segments:
        raise ValueError("segment target selected no segments")
    if selector.get("type") == "all_shell":
        return segments
    face = edge_for_model(spec, str(selector.get("face")))
    axis, side = EDGE_AXES[face]
    node_map = {nid: (x, y, z) for nid, x, y, z in nodes}
    values = [coords[axis] for coords in node_map.values()]
    target = min(values) if side == "min" else max(values)
    span = max(values) - min(values)
    tol = max(abs(span) * 1e-9, 1e-12)
    selected = [
        segment
        for segment in segments
        if all(abs(node_map[nid][axis] - target) <= tol for nid in segment)
    ]
    if not selected:
        raise ValueError(f"segment selector {selector} selected no segments")
    return selected


def velocity_vector(item: JSONDict) -> tuple[float, float, float]:
    if "vector_m_per_s" in item:
        vx, vy, vz = item["vector_m_per_s"]
        return float(vx), float(vy), float(vz)
    return (
        float(item.get("vx_m_per_s", 0.0)),
        float(item.get("vy_m_per_s", 0.0)),
        float(item.get("vz_m_per_s", 0.0)),
    )


def shell_segments_from_elements(elements: list[tuple[int, int, int, int, int, int]]) -> list[Segment]:
    return [(n1, n2, n3, n4) for _, _, n1, n2, n3, n4 in elements]


def solid_segments_from_elements(elements: list[tuple[int, int, int, int, int, int, int, int, int, int]]) -> list[Segment]:
    segments: list[Segment] = []
    for _, _, n1, n2, n3, n4, n5, n6, n7, n8 in elements:
        segments.extend(
            [
                (n1, n4, n3, n2),
                (n5, n6, n7, n8),
                (n2, n3, n7, n6),
                (n1, n2, n6, n5),
                (n3, n4, n8, n7),
                (n4, n1, n5, n8),
            ]
        )
    return segments


def node_set_lines(sid: int, label: str, node_ids: list[int]) -> list[str]:
    lines = [
        "*SET_NODE_LIST",
        "$#   sid       da1       da2       da3       da4",
        f"{sid},0,0,0,0",
        f"$ {label}",
    ]
    lines.extend(format_id_lines(node_ids))
    return lines


def part_set_lines(sid: int, label: str, part_ids: list[int]) -> list[str]:
    lines = [
        "*SET_PART_LIST",
        "$#   sid       da1       da2       da3       da4",
        f"{sid},0,0,0,0",
        f"$ {label}",
    ]
    lines.extend(format_id_lines(part_ids))
    return lines


def segment_set_lines(sid: int, label: str, segments: list[Segment]) -> list[str]:
    lines = [
        "*SET_SEGMENT",
        "$#   sid       da1       da2       da3       da4",
        f"{sid},0,0,0,0",
        f"$ {label}",
        "$#    n1      n2      n3      n4",
    ]
    lines.extend(",".join(str(value) for value in segment) for segment in segments)
    return lines


def curve_lines_from_points(lcid: int, points: list[tuple[float, float]], label: str) -> list[str]:
    lines = [
        "*DEFINE_CURVE",
        f"$ {label}",
        "$#   lcid      sidr       sfa       sfo      offa      offo    dattyp     lcint",
        f"{lcid},0,1.0,1.0,0.0,0.0,0,0",
        "$#                a1                  o1",
    ]
    lines.extend(f"{time:.9g},{value:.9g}" for time, value in points)
    return lines


def top_level_curve_lines(spec: ModelSpec) -> list[str]:
    lines: list[str] = []
    for curve in spec.curves:
        points = [(float(point[0]), float(point[1])) for point in curve["points"]]
        lines.extend(curve_lines_from_points(int(curve["id"]), points, str(curve.get("name", "curve"))))
    return lines


def curve_points(item: JSONDict, value_field: str) -> list[tuple[float, float]]:
    curve = item.get("curve")
    if not isinstance(curve, dict):
        return [(0.0, 0.0), (float(item.get("end_time_s", 1.0)), float(item[value_field]))]
    curve_type = str(curve.get("type", "ramp"))
    if curve_type == "constant":
        value = float(curve.get("value", item.get(value_field, 0.0)))
        end_time = float(curve.get("end_time_s", item.get("end_time_s", 1.0)))
        return [(0.0, value), (end_time, value)]
    if curve_type == "ramp":
        start_time = float(curve.get("start_time_s", 0.0))
        end_time = float(curve.get("end_time_s", item.get("end_time_s", 1.0)))
        start_value = float(curve.get("start_value", 0.0))
        end_value = float(curve.get("end_value", item.get(value_field, 0.0)))
        return [(start_time, start_value), (end_time, end_value)]
    return [(float(time), float(value)) for time, value in curve["points"]]


def curve_lines(lcid: int, item: JSONDict, value_field: str, label: str) -> list[str]:
    return curve_lines_from_points(lcid, curve_points(item, value_field), label)


def legacy_curve_lines(lcid: int, value: float, label: str, end_time: float = 1.0) -> list[str]:
    return [
        "*DEFINE_CURVE",
        f"$ {label}",
        "$#   lcid      sidr       sfa       sfo      offa      offo    dattyp     lcint",
        f"{lcid},0,1.0,1.0,0.0,0.0,0,0",
        "$#                a1                  o1",
        f"0.0,0.0",
        f"{end_time:.9g},{value:.9g}",
    ]


