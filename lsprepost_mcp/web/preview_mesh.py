from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from lsprepost_mcp.city_impact import SEMANTIC_GROUPS
from lsprepost_mcp.city_editor import city_editable_objects
from lsprepost_mcp.config import JSONDict
from lsprepost_mcp.io import read_json


NODE_CARD = "*NODE"
SHELL_CARD = "*ELEMENT_SHELL"
SOLID_CARD = "*ELEMENT_SOLID"


def build_preview_mesh(project_path: Path) -> JSONDict:
    keyword_path = project_path / "model.k"
    if not keyword_path.is_file():
        raise FileNotFoundError(f"model.k not found: {keyword_path}")
    blast_sources: list[JSONDict] = []
    component_names: dict[int, str] = {}
    component_details: dict[int, JSONDict] = {}
    default_hidden_part_ids: list[int] = []
    ale_domain_bounds: JSONDict | None = None
    model_path = project_path / "model.json"
    if model_path.is_file():
        model = read_json(model_path)
        metadata = model.get("metadata", {}) if isinstance(model, dict) else {}
        if isinstance(metadata, dict):
            if isinstance(metadata.get("blast_sources"), list):
                blast_sources = [dict(item) for item in metadata["blast_sources"] if isinstance(item, dict)]
            for component in metadata.get("components", []):
                if isinstance(component, dict) and isinstance(component.get("part_id"), int):
                    component_names[int(component["part_id"])] = str(component.get("id") or component.get("template"))
            _add_city_semantic_components(metadata, component_names, component_details)
            _add_ground_response_components(
                metadata,
                component_names,
                component_details,
            )
            explosive = metadata.get("explosive")
            if isinstance(explosive, dict):
                position = explosive.get("center_m")
                if not isinstance(position, list):
                    base = explosive.get("base_center_m")
                    length = explosive.get("length_m")
                    if isinstance(base, list) and len(base) == 3 and isinstance(length, (int, float)):
                        position = [base[0], base[1], float(base[2]) + 0.5 * float(length)]
                blast_sources.append(
                    {
                        "kind": "ale_explosive_volume",
                        "label": "炸药初始化区域",
                        "position_m": position or [0.0, 0.0, 0.0],
                        "radius_m": explosive.get(
                            "radius_m",
                            0.5 * float(explosive.get("diameter_m", 0.0)),
                        ),
                        "mass_kg": explosive.get("mass_kg", 0.0),
                    }
                )
            ale_domain = metadata.get("ale_domain")
            if isinstance(ale_domain, dict) and isinstance(ale_domain.get("part_id"), int):
                default_hidden_part_ids.append(int(ale_domain["part_id"]))
                if isinstance(ale_domain.get("bounds_m"), dict):
                    ale_domain_bounds = dict(ale_domain["bounds_m"])
    nodes, shell_elements, solid_elements = parse_keyword_mesh(
        keyword_path.read_text(encoding="utf-8"),
        skip_solid_part_ids=set(default_hidden_part_ids),
    )
    parts = []
    for pid in sorted(set(shell_elements) | set(solid_elements)):
        shell_faces = [element[1] for element in shell_elements.get(pid, [])]
        solid_faces = boundary_faces([element[1] for element in solid_elements.get(pid, [])])
        faces = shell_faces + solid_faces
        if not faces:
            continue
        parts.append(part_mesh(pid, "mixed" if shell_faces and solid_faces else ("shell" if shell_faces else "solid"), nodes, faces))
    bounds = mesh_bounds(nodes)
    for part_id in default_hidden_part_ids:
        if not any(int(part["part_id"]) == part_id for part in parts):
            domain_bounds = ale_domain_bounds or {"min": bounds["min"], "max": bounds["max"]}
            parts.insert(0, box_part_mesh(part_id, domain_bounds))
    for part in parts:
        part_id = int(part["part_id"])
        if part_id in component_names:
            part["name"] = component_names[part_id]
        if part_id in component_details:
            part.update(component_details[part_id])
    return {
        "format": "lsprepost_mcp_preview_mesh_v1",
        "project_name": project_path.name,
        "parts": parts,
        "bounds": bounds,
        "node_count": len(nodes),
        "face_count": sum(len(part["faces"]) for part in parts),
        "blast_sources": blast_sources,
        "default_hidden_part_ids": default_hidden_part_ids,
        "limitations": [
            "Browser preview is generated from controlled keyword mesh cards and is not a solver result.",
            "Solid elements are displayed by exterior faces only.",
        ],
    }


def build_preview_mesh_from_keyword(
    keyword: str,
    metadata: JSONDict,
    *,
    project_name: str,
    revision: int | None = None,
) -> JSONDict:
    component_names: dict[int, str] = {}
    component_details: dict[int, JSONDict] = {}
    raw_components = metadata.get("components")
    if isinstance(raw_components, list):
        for component in raw_components:
            if isinstance(component, dict) and isinstance(component.get("part_id"), int):
                component_names[int(component["part_id"])] = str(
                    component.get("id") or component.get("template")
                )
    _add_city_semantic_components(metadata, component_names, component_details)
    _add_ground_response_components(
        metadata,
        component_names,
        component_details,
    )

    default_hidden_part_ids: list[int] = []
    ale_domain_bounds: JSONDict | None = None
    ale_domain = metadata.get("ale_domain")
    if isinstance(ale_domain, dict) and isinstance(ale_domain.get("part_id"), int):
        default_hidden_part_ids.append(int(ale_domain["part_id"]))
        if isinstance(ale_domain.get("bounds_m"), dict):
            ale_domain_bounds = dict(ale_domain["bounds_m"])

    nodes, shell_elements, solid_elements = parse_keyword_mesh(
        keyword,
        skip_solid_part_ids=set(default_hidden_part_ids),
    )
    parts: list[JSONDict] = []
    for pid in sorted(set(shell_elements) | set(solid_elements)):
        shell_faces = [element[1] for element in shell_elements.get(pid, [])]
        solid_faces = boundary_faces(
            [element[1] for element in solid_elements.get(pid, [])]
        )
        faces = shell_faces + solid_faces
        if not faces:
            continue
        part = part_mesh(
            pid,
            (
                "mixed"
                if shell_faces and solid_faces
                else ("shell" if shell_faces else "solid")
            ),
            nodes,
            faces,
        )
        if pid in component_names:
            part["name"] = component_names[pid]
        if pid in component_details:
            part.update(component_details[pid])
        parts.append(part)

    bounds = mesh_bounds(nodes)
    for part_id in default_hidden_part_ids:
        if not any(int(part["part_id"]) == part_id for part in parts):
            domain_bounds = ale_domain_bounds or {
                "min": bounds["min"],
                "max": bounds["max"],
            }
            parts.insert(0, box_part_mesh(part_id, domain_bounds))

    result: JSONDict = {
        "format": (
            "lsprepost_mcp_preview_mesh_v2"
            if revision is not None
            else "lsprepost_mcp_preview_mesh_v1"
        ),
        "project_name": project_name,
        "parts": parts,
        "bounds": bounds,
        "node_count": len(nodes),
        "face_count": sum(len(part["faces"]) for part in parts),
        "blast_sources": _preview_blast_sources(metadata),
        "default_hidden_part_ids": default_hidden_part_ids,
        "limitations": [
            "Browser preview is generated from controlled keyword mesh cards and is not a solver result.",
            "Solid elements are displayed by exterior faces only.",
        ],
    }
    if revision is not None:
        result["revision"] = revision
        result["components"] = city_editable_objects(metadata)
        result["editable_sources"] = _editable_sources(metadata)
    return result


def _preview_blast_sources(metadata: JSONDict) -> list[JSONDict]:
    result: list[JSONDict] = []
    raw_sources = metadata.get("blast_sources")
    if isinstance(raw_sources, list):
        result.extend(
            dict(item)
            for item in raw_sources
            if isinstance(item, dict)
        )
    explosive = metadata.get("explosive")
    if isinstance(explosive, dict):
        position = explosive.get("center_m")
        if isinstance(position, list) and len(position) == 3:
            result.append(
                {
                    "source_id": "city_tnt",
                    "kind": "ale_explosive_volume",
                    "label": "TNT explosive initialization volume",
                    "position_m": list(position),
                    "radius_m": 0.5 * float(explosive.get("diameter_m", 0.0)),
                    "mass_kg": explosive.get("mass_kg", 0.0),
                }
            )
    return result


def _editable_sources(metadata: JSONDict) -> list[JSONDict]:
    explosive = metadata.get("explosive")
    if not isinstance(explosive, dict):
        return []
    position = explosive.get("center_m")
    if not isinstance(position, list) or len(position) != 3:
        return []
    return [
        {
            "source_id": "city_tnt",
            "kind": "ale_explosive_volume",
            "position_kind": "geometric_center",
            "position_m": list(position),
            "radius_m": 0.5 * float(explosive.get("diameter_m", 0.0)),
            "length_m": float(explosive.get("length_m", 0.0)),
            "mobility_profile": "blast_source",
            "allowed_dofs": ["tx", "ty", "tz"],
            "editable": True,
        }
    ]


def _add_city_semantic_components(
    metadata: JSONDict,
    component_names: dict[int, str],
    component_details: dict[int, JSONDict],
) -> None:
    explicit = metadata.get("semantic_objects")
    if isinstance(explicit, list) and explicit:
        for item in explicit:
            if not isinstance(item, dict):
                continue
            group_id = str(item.get("group_id", ""))
            definition = SEMANTIC_GROUPS.get(group_id)
            part_ids = item.get("part_ids")
            if not definition or not isinstance(part_ids, list):
                continue
            object_id = str(item.get("object_id") or group_id)
            label = _semantic_label(str(definition["label"]), group_id, object_id)
            for part_id in part_ids:
                if not isinstance(part_id, int) or isinstance(part_id, bool):
                    continue
                component_names[part_id] = label
                component_details[part_id] = {
                    "semantic_object_id": object_id,
                    "semantic_group_id": group_id,
                    "semantic_category": definition["category"],
                }
        return

    urban = metadata.get("urban_components")
    if not isinstance(urban, dict):
        return
    for group_id, definition in SEMANTIC_GROUPS.items():
        row = urban.get(group_id)
        if not isinstance(row, dict) or not isinstance(row.get("part_ids"), list):
            continue
        part_ids = [
            value
            for value in row["part_ids"]
            if isinstance(value, int) and not isinstance(value, bool)
        ]
        for index, part_id in enumerate(part_ids, start=1):
            object_id = (
                f"{group_id[:-1]}_{index}"
                if definition.get("expand_parts")
                else group_id
            )
            label = (
                f"{definition['label']} {index}"
                if definition.get("expand_parts")
                else str(definition["label"])
            )
            component_names[part_id] = label
            component_details[part_id] = {
                "semantic_object_id": object_id,
                "semantic_group_id": group_id,
                "semantic_category": definition["category"],
                }


def _add_ground_response_components(
    metadata: JSONDict,
    component_names: dict[int, str],
    component_details: dict[int, JSONDict],
) -> None:
    ground = metadata.get("ground_response")
    if not isinstance(ground, dict) or ground.get("mode") != "validation_crater":
        return
    eroding_part_id = ground.get("eroding_part_id")
    support_part_id = ground.get("support_part_id")
    if isinstance(eroding_part_id, int) and not isinstance(eroding_part_id, bool):
        component_names[eroding_part_id] = "K&C eroding validation ground"
        component_details[eroding_part_id] = {
            "semantic_category": "ground_response",
            "ground_response_role": "eroding_crater_zone",
            "color": "#b25d3f",
        }
    if isinstance(support_part_id, int) and not isinstance(support_part_id, bool):
        component_names[support_part_id] = "Non-eroding ground support"
        component_details[support_part_id] = {
            "semantic_category": "ground_response",
            "ground_response_role": "lower_support",
            "color": "#68777d",
        }


def _semantic_label(base: str, group_id: str, object_id: str) -> str:
    prefixes = {
        "concrete_roads": "concrete_road_",
        "ground_foundation": "ground_foundation_",
        "parked_vehicles": "parked_vehicle_",
        "traffic_lights": "traffic_light_",
    }
    prefix = prefixes.get(group_id)
    suffix = object_id[len(prefix) :] if prefix and object_id.startswith(prefix) else ""
    return f"{base} {suffix}" if suffix else base


def parse_keyword_mesh(
    text: str,
    skip_solid_part_ids: set[int] | None = None,
) -> tuple[dict[int, list[float]], dict[int, list[tuple[int, list[int]]]], dict[int, list[tuple[int, list[int]]]]]:
    nodes: dict[int, list[float]] = {}
    shell_elements: dict[int, list[tuple[int, list[int]]]] = defaultdict(list)
    solid_elements: dict[int, list[tuple[int, list[int]]]] = defaultdict(list)
    current = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("$"):
            continue
        if line.startswith("*"):
            current = line.split()[0].split(",")[0].upper()
            continue
        fields = split_fields(line)
        if current == NODE_CARD and len(fields) >= 4:
            nid = int(float(fields[0]))
            nodes[nid] = [float(fields[1]), float(fields[2]), float(fields[3])]
        elif current == SHELL_CARD and len(fields) >= 6:
            eid = int(float(fields[0]))
            pid = int(float(fields[1]))
            node_ids = [int(float(value)) for value in fields[2:6]]
            shell_elements[pid].append((eid, normalize_shell_face(node_ids)))
        elif current == SOLID_CARD and len(fields) >= 10:
            eid = int(float(fields[0]))
            pid = int(float(fields[1]))
            if skip_solid_part_ids and pid in skip_solid_part_ids:
                continue
            node_ids = [int(float(value)) for value in fields[2:10]]
            solid_elements[pid].append((eid, node_ids))
    return nodes, dict(shell_elements), dict(solid_elements)


def split_fields(line: str) -> list[str]:
    if "," in line:
        return [field.strip() for field in line.split(",") if field.strip()]
    return line.split()


def normalize_shell_face(node_ids: list[int]) -> list[int]:
    if len(node_ids) == 4 and node_ids[2] == node_ids[3]:
        return node_ids[:3]
    return node_ids


def boundary_faces(elements: list[list[int]]) -> list[list[int]]:
    counts: dict[tuple[int, ...], list[int] | None] = {}
    for n in elements:
        candidates = [
            [n[0], n[1], n[2], n[3]],
            [n[4], n[7], n[6], n[5]],
            [n[0], n[4], n[5], n[1]],
            [n[1], n[5], n[6], n[2]],
            [n[2], n[6], n[7], n[3]],
            [n[3], n[7], n[4], n[0]],
        ]
        for face in candidates:
            key = tuple(sorted(face))
            if key in counts:
                counts[key] = None
            else:
                counts[key] = face
    return [face for face in counts.values() if face is not None]


def part_mesh(pid: int, family: str, all_nodes: dict[int, list[float]], faces_by_node_id: list[list[int]]) -> JSONDict:
    used_node_ids = sorted({nid for face in faces_by_node_id for nid in face})
    local_index = {nid: index for index, nid in enumerate(used_node_ids)}
    nodes = [all_nodes[nid] for nid in used_node_ids if nid in all_nodes]
    faces = [[local_index[nid] for nid in face if nid in local_index] for face in faces_by_node_id]
    faces = [face for face in faces if len(face) >= 3]
    return {
        "part_id": pid,
        "name": f"part_{pid}",
        "element_family": family,
        "color": color_for_part(pid),
        "nodes": nodes,
        "faces": faces,
        "edges": edges_for_faces(faces),
    }


def edges_for_faces(faces: list[list[int]]) -> list[list[int]]:
    edges: set[tuple[int, int]] = set()
    for face in faces:
        for index, start in enumerate(face):
            end = face[(index + 1) % len(face)]
            edges.add(tuple(sorted((start, end))))
    return [list(edge) for edge in sorted(edges)]


def mesh_bounds(nodes: dict[int, list[float]]) -> JSONDict:
    if not nodes:
        return {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0], "center": [0.0, 0.0, 0.0]}
    xs = [point[0] for point in nodes.values()]
    ys = [point[1] for point in nodes.values()]
    zs = [point[2] for point in nodes.values()]
    mn = [min(xs), min(ys), min(zs)]
    mx = [max(xs), max(ys), max(zs)]
    center = [(mn[index] + mx[index]) * 0.5 for index in range(3)]
    return {"min": mn, "max": mx, "center": center}


def color_for_part(pid: int) -> str:
    palette = ["#d94157", "#2f8fcd", "#f0a02f", "#55aa65", "#8b6bd6", "#40a6a6"]
    return palette[(pid - 1) % len(palette)]


def box_part_mesh(part_id: int, bounds: JSONDict) -> JSONDict:
    low = [float(value) for value in bounds["min"]]
    high = [float(value) for value in bounds["max"]]
    nodes = [
        [low[0], low[1], low[2]],
        [high[0], low[1], low[2]],
        [high[0], high[1], low[2]],
        [low[0], high[1], low[2]],
        [low[0], low[1], high[2]],
        [high[0], low[1], high[2]],
        [high[0], high[1], high[2]],
        [low[0], high[1], high[2]],
    ]
    faces = [[0, 1, 2, 3], [4, 7, 6, 5], [0, 4, 5, 1], [1, 5, 6, 2], [2, 6, 7, 3], [3, 7, 4, 0]]
    return {
        "part_id": part_id,
        "name": f"part_{part_id}",
        "element_family": "solid_domain_bounds",
        "color": color_for_part(part_id),
        "nodes": nodes,
        "faces": faces,
        "edges": edges_for_faces(faces),
    }
