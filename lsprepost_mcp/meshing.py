"""Route, validate and publish a mesh handoff, adapted from Foam-Agent's meshing node."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

from .knowledge import KnowledgeBase
from .mesh_geometry import CheckedMesh, MAX_DIMENSION_MM, UNITS, inspect_plate_mesh, structured_plate
from .mesh_import import read_gmsh_mesh, read_keyword_mesh


GENERATED_METHODS = ("structured", "triangular")
METHODS = ("auto", *GENERATED_METHODS, "keyword", "gmsh_ascii")
BUILD_MESH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["unit_system"],
    "properties": {
        "unit_system": {"type": "string", "enum": [UNITS]},
        "method": {"type": "string", "enum": list(METHODS), "default": "auto"},
        "source_path": {"type": "string", "description": "User-selected K or Gmsh mesh file."},
        "source_length_unit": {"type": "string", "enum": ["mm", "m"],
                               "description": "Length unit of the imported geometry. K unit comments are checked."},
        "length_mm": {"type": "number"},
        "width_mm": {"type": "number"},
        "size_mm": {"type": "number", "description": "Target grid spacing, or maximum imported edge length if supplied."},
    },
}
STAGE_EVIDENCE = {
    "meshing": [
        ("I_model", "primary", "r12.node"), ("I_model", "primary", "r12.element_shell"),
        ("I_tool", "supplement", "book.ansys_prepost_plate_mesh"),
        ("I_tool", "supplement", "prepost.element_quality"), ("I_tool", "supplement", "prepost.check_normals"),
    ],
    "input_writer": [
        ("I_model", "primary", "r12.part"), ("I_model", "primary", "r12.section_shell"),
        ("I_model", "primary", "r12.mat_elastic"), ("I_model", "primary", "r12.set_node_list"),
        ("I_model", "primary", "r12.boundary_spc_set"), ("I_model", "primary", "r12.database_binary_d3plot"),
        ("I_tool", "supplement", "book.ansys_prepost_constraints"),
    ],
}


def stage_evidence(stage: str) -> dict:
    kb = KnowledgeBase()
    sources = STAGE_EVIDENCE[stage]
    evidence, unavailable, checked = [], [], set()
    for index, collection, key in sources:
        try:
            record = kb.checked_reference(key, index=index, collection=collection,
                                          case_family="shell_plate", checked=checked)
        except (KeyError, ValueError, OSError):
            unavailable.append(key)
            continue
        evidence.append({field: record[field] for field in ("id", "index", "summary", "source")})
    return {"knowledge_snapshot": kb.snapshot, "knowledge_ids": [key for _, _, key in sources],
            "evidence": evidence, "unavailable_evidence_ids": unavailable}


def _serialize(artifact: dict) -> bytes:
    return json.dumps(artifact, separators=(",", ":"), sort_keys=True, allow_nan=False).encode("utf-8")


def _artifact_path(root: Path, mesh_id: str) -> Path:
    if not isinstance(mesh_id, str) or re.fullmatch(r"[0-9a-f]{64}", mesh_id) is None:
        raise ValueError("mesh_id 必须是网格工件的 SHA-256。")
    return root / f"{mesh_id}.json"


def _publish(root: Path, artifact: dict) -> tuple[str, Path]:
    raw = _serialize(artifact)
    mesh_id = hashlib.sha256(raw).hexdigest()
    path = _artifact_path(root, mesh_id)
    root.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes() == raw:
        return mesh_id, path
    temporary = None
    try:
        with NamedTemporaryFile(dir=root, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return mesh_id, path


def _positive_size(value, name: str) -> float:
    if type(value) not in (int, float) or not 0 < value <= MAX_DIMENSION_MM:
        raise ValueError(f"{name} 须为有效的正数，单位 mm。")
    return float(value)


def _check_geometry(mesh: CheckedMesh, *, length=None, width=None) -> None:
    (x0, y0), _, (x1, y1), _ = mesh.outline
    for key, actual, expected in (("length_mm", x1 - x0, length), ("width_mm", y1 - y0, width)):
        if expected is not None and not math.isclose(actual, expected, rel_tol=0, abs_tol=1e-6):
            raise ValueError(f"网格轮廓的 {key} 与规划要求不符。")


def build_mesh(request: dict, root: Path) -> dict:
    """Select the backend, inspect its mesh, then publish a validated handoff."""
    if not isinstance(request, dict) or set(request) - BUILD_MESH_SCHEMA["properties"].keys():
        raise ValueError("网格请求字段不受支持。")
    if request.get("unit_system") != UNITS:
        raise ValueError(f"请确认网格坐标单位制 {UNITS}。")
    method = request.get("method", "auto")
    if method not in METHODS:
        raise ValueError(f"网格路径须为 {', '.join(METHODS)}。")
    source = request.get("source_path")
    if source is not None and (not isinstance(source, str) or not source.strip()):
        raise ValueError("请给出有效的源网格文件路径。")
    path = Path(source).resolve() if source else None
    if method == "auto":
        method = ("gmsh_ascii" if path.suffix.lower() == ".msh" else "keyword") if path else "structured"
    sizes = {key: _positive_size(request[key], key) for key in ("length_mm", "width_mm", "size_mm")
             if key in request}
    grid = {}
    sources = []
    source_unit = request.get("source_length_unit")
    if source_unit is not None and (source_unit not in ("mm", "m") or path is None):
        raise ValueError("源长度单位仅用于导入，支持 mm 或 m。")
    if method in GENERATED_METHODS:
        if path or set(sizes) != {"length_mm", "width_mm", "size_mm"}:
            raise ValueError("结构化网格需要长、宽和目标尺寸。请选择导入路径使用源文件。")
        nodes, elements, grid = structured_plate(
            sizes["length_mm"], sizes["width_mm"], sizes["size_mm"], triangular=method == "triangular"
        )
    else:
        if path is None:
            raise ValueError("导入路径需要源网格文件。")
        if method == "keyword":
            nodes, elements, sources, declared_unit = read_keyword_mesh(path)
            if source_unit and declared_unit and source_unit != declared_unit:
                raise ValueError("已确认的源长度单位与 K 文件标记不一致。")
            source_unit = source_unit or declared_unit
        else:
            nodes, elements, sources = read_gmsh_mesh(path)
        source_unit = source_unit or "mm"
        if source_unit == "m":
            nodes = [(nid, x * 1000, y * 1000, z * 1000) for nid, x, y, z in nodes]
    mesh = inspect_plate_mesh(nodes, elements)
    _check_geometry(mesh, length=sizes.get("length_mm"), width=sizes.get("width_mm"))
    if method not in GENERATED_METHODS and "size_mm" in sizes and mesh.quality["max_edge_mm"] > sizes["size_mm"] + 1e-6:
        raise ValueError("导入网格的最大单元边长超过要求。")
    artifact = {"schema_version": 1, "method": method, "unit_system": UNITS, "grid": grid,
                "size_mm": sizes.get("size_mm"), "source_files": sources,
                "source_length_unit": source_unit, "nodes": mesh.nodes,
                "elements": mesh.elements, "regions": mesh.regions, "outline_mm": mesh.outline}
    knowledge = stage_evidence("meshing")
    mesh_id, artifact_path = _publish(root, artifact)
    return {"mesh_id": mesh_id, "method": method, "artifact_path": str(artifact_path),
            "outline_mm": mesh.outline, "quality": mesh.quality, "source_files": sources,
            "source_length_unit": source_unit,
            "regions": {key: {"count": len(ids), "entity": "part" if key == "plate.part" else "node"}
                        for key, ids in mesh.regions.items()},
            **knowledge}


def load_for_configuration(root: Path, mesh_id: str, *, length: float, width: float,
                           size: float | None) -> tuple[CheckedMesh, dict]:
    path = _artifact_path(root, mesh_id)
    if not path.is_file():
        raise ValueError("网格工件不存在，请先运行 build_mesh。")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != mesh_id:
        raise ValueError("网格工件指纹不匹配，请重新划分或导入。")
    data = json.loads(raw)
    if (data.get("schema_version"), data.get("unit_system")) != (1, UNITS):
        raise ValueError("网格工件版本或单位制不受支持。")
    mesh = inspect_plate_mesh(data["nodes"], data["elements"])
    _check_geometry(mesh, length=length, width=width)
    recorded_size = data["size_mm"]
    if size is not None and recorded_size != size:
        raise ValueError("网格尺寸要求与工件版本不一致，请重新划分或导入。")
    if data["outline_mm"] != mesh.outline or data["regions"].keys() != mesh.regions.keys():
        raise ValueError("网格工件的轮廓或语义区域不一致。")
    for region, ids in mesh.regions.items():
        if data["regions"][region] != ids:
            raise ValueError(f"网格工件的 {region} 与实际拓扑不一致。")
    method = data["method"]
    if method in GENERATED_METHODS:
        nodes, elements, grid = structured_plate(
            length, width, _positive_size(recorded_size, "size_mm"), triangular=method == "triangular"
        )
        coordinates = [(nid, round(x, 6), round(y, 6), round(z, 6)) for nid, x, y, z in nodes]
        if mesh.nodes != coordinates or mesh.elements != elements or data["grid"] != grid:
            raise ValueError("实际结构化网格与声明的网格尺寸或连接规则不一致。")
    elif method in ("keyword", "gmsh_ascii"):
        grid = {}
        if recorded_size is not None and mesh.quality["max_edge_mm"] > _positive_size(recorded_size, "size_mm") + 1e-6:
            raise ValueError("导入工件的实际网格尺寸超过声明上限。")
    else:
        raise ValueError("网格工件的生成路径未知。")
    return mesh, grid
