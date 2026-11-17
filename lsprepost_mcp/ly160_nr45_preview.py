"""Export input geometry/material illustrations from a verified L-NR45 project."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ly160_nr45 import ASSUMPTIONS, MODEL_TYPE, flow_stress, radius_at
from .provenance import verify_generated_project
from .web.preview_mesh import parse_keyword_mesh


def export_input_preview(project: Path) -> dict:
    project = project.resolve()
    if not verify_generated_project(project)["ok"]:
        raise ValueError("Preview requires a verified generated project")
    model = json.loads((project/"model.json").read_text(encoding="utf-8"))
    if model["spec"]["model_type"] != MODEL_TYPE:
        raise ValueError("Preview supports only L-NR45")
    output = project/"input_preview.png"
    curve_path = project/"material_curve.json"
    notes_path = project/"model_notes.txt"
    for path in (output, curve_path, notes_path):
        if path.exists():
            raise FileExistsError(f"Preserving existing artifact: {path}")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    import numpy as np

    keyword = (project/"model.k").read_text(encoding="utf-8")
    nodes, shells, _ = parse_keyword_mesh(keyword)
    points = []
    current, curve_id = "", None
    for line in keyword.splitlines():
        if line.startswith("*"):
            current, curve_id = line, None
        elif line.strip() and not line.startswith("$") and current == "*DEFINE_CURVE":
            fields = line.split(",")
            if curve_id is None:
                curve_id = int(fields[0])
            elif curve_id == 1001:
                points.append([float(fields[0]), float(fields[1])])
    if len(points) < 2:
        raise ValueError("MAT_024 curve 1001 not found")
    plt.rcParams.update({"font.family": ["Microsoft YaHei", "DejaVu Sans"],
                         "axes.unicode_minus": False, "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig = plt.figure(figsize=(14, 8.2), facecolor="#f7f9fc", layout="constrained")
    gs = fig.add_gridspec(2, 2, height_ratios=[.85, 1.5])
    shape = fig.add_subplot(gs[0, :])
    mesh_ax = fig.add_subplot(gs[1, 0])
    material = fig.add_subplot(gs[1, 1])
    fig.suptitle("LY160 · L-NR45  |  论文参数重建 · 输入模型（尚未求解）", fontsize=19, weight="bold", color="#16334e")

    axis = np.linspace(-60, 60, 1001)
    radius = np.array([radius_at(float(y)/1000)*1000 for y in axis])
    shape.fill_between(axis, -radius, radius, color="#cbd5e1", label="完整试件轮廓：120 mm（参考）")
    mask = abs(axis) <= 31.25
    shape.fill_between(axis[mask], -radius[mask], radius[mask], color="#168b9e", alpha=.9, label="有限元计算域：中间 62.5 mm")
    for sign in (-1, 1):
        shape.plot(axis, sign*radius, color="#29465a", lw=1)
        shape.axvline(sign*31.25, color="#bd7b20", ls="--", lw=1)
    shape.annotate("", (-31.25, 7.2), (31.25, 7.2), arrowprops={"arrowstyle": "<->", "color": "#bd7b20"})
    shape.text(0, 8, "标距 62.5 mm", ha="center", color="#8a5b1b")
    shape.text(-49, 6, "端部直径 9 mm", ha="center")
    shape.annotate("最小直径 5 mm · R45", xy=(0, -2.5), xytext=(12, -9),
                   arrowprops={"arrowstyle": "->", "color": "#29465a"})
    shape.set(xlim=(-63, 63), ylim=(-12, 12), xlabel="轴向位置（mm）", yticks=[])
    shape.legend(loc="upper right", frameon=False, fontsize=9)

    segments = []
    for rows in shells.values():
        for _, conn in rows:
            for i, n in enumerate(conn):
                p, q = nodes[n], nodes[conn[(i+1)%4]]
                segments.append([[p[1]*1000, p[0]*1000], [q[1]*1000, q[0]*1000]])
    mesh_ax.add_collection(LineCollection(segments, colors="#197c91", linewidths=.42))
    mesh_ax.set(xlim=(-32, 32), ylim=(-.3, 5.8), xlabel="轴向 Y（mm）", ylabel="半径 X（mm）")
    mesh_ax.set_title(f"实际计算网格：{len(nodes):,} 节点 / {sum(len(r) for r in shells.values()):,} 单元", loc="left", pad=14, weight="bold")
    mesh_ax.axhline(0, color="#4b5563", ls="--", lw=.8)
    mesh_ax.annotate("底端轴向固定", xy=(-31.25, 2), xytext=(-27, 5.1), arrowprops={"arrowstyle": "->"})
    mesh_ax.annotate("顶端轴向位移", xy=(31.25, 2), xytext=(12, 5.1), arrowprops={"arrowstyle": "->"})
    mesh_ax.text(.01, -.25, "轴对称实体：ELFORM 15 / NIP 4\n缺口轴向约 0.246 mm；根部径向 0.25 mm\n该图为轴对称截面，无应力或变形计算结果。",
                 transform=mesh_ax.transAxes, va="top", fontsize=9, color="#475569")

    eps = np.linspace(0, 3, 1201)
    material.plot(eps, [flow_stress(float(p))/1e6 for p in eps], color="#1e3a5f", lw=2, label="论文修正 Voce 公式")
    material.plot([p[0] for p in points], [p[1]/1e6 for p in points], "o", ms=2.8, color="#d3912b", label=f"MAT_024 输入：{len(points)} 点")
    material.set(xlim=(0, 3), ylim=(150, 1200), xlabel="等效塑性应变", ylabel="真实流动应力（MPa）")
    material.set_title("材料输入：表 3 · L-NR45", loc="left", pad=14, weight="bold")
    material.grid(alpha=.15)
    material.legend(frameon=False, loc="upper left")
    material.text(.01, -.25, "E = 202.57 GPa；σy0 = 185.69 MPa\nQ∞ = 135.15 MPa；b = 11.24；L = 271.73 MPa\n假设：ν = 0.30；ρ = 7850 kg/m³；未设置损伤或断裂。",
                  transform=material.transAxes, va="top", fontsize=9, color="#475569")
    fig.savefig(output, dpi=160, facecolor=fig.get_facecolor())
    plt.close(fig)
    curve_path.write_text(json.dumps({"source": "model.k curve 1001", "x": "effective_plastic_strain",
                                     "y": "true_flow_stress_pa", "points": points,
                                     "metadata": model["metadata"]["material_curve"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    notes = """LY160 L-NR45 输入模型说明

状态：已生成输入模型；未启动 LS-DYNA；没有力学响应结果。
材料：MAT_024 + LCID 1001 修正 Voce 曲线（表 3 L-NR45）。
应力单位 Pa，长度 m，时间 s，质量 kg。E=202.57e9 Pa，sigy=185.69e6 Pa，Q=135.15e6 Pa，b=11.24，L=271.73e6 Pa。
曲线横坐标为等效塑性应变，不能当成总应变；L 不能直接填入 ETAN。
图 1 原试件长 120 mm；计算域为中间 62.5 mm 标距段。端部直径 9 mm，根部直径 5 mm，圆弧缺口半径 45 mm。
二维轴对称实体：全局 X=半径、Y=轴向、Z=0；ELFORM 15，NIP 4。
实际网格与 Abaqus 的二次 CAX8 不同，尚未验证网格收敛或求解器等效性。

后续读结果：底端轴向合反力取 SPCFORC 对集合 102 节点求和，取拉力方向并乘 2*pi；顶端 BNDOUT 可作平衡核对，不能两端相加。
标距伸长取顶端与底端 Y 位移之差（不乘任何轴对称比例）。
不得将载荷下降到 85% 的名义判据当成单元失效应变；本模型不模拟断裂。

复现命令（在项目仓库根目录）：
python -m lsprepost_mcp.ly160_nr45 generate --project-name LY160_L_NR45_paper_20261101 --if-exists versioned
python -m lsprepost_mcp.ly160_nr45_preview <实际项目目录>
powershell -ExecutionPolicy Bypass -File scripts/verify_generated_k.ps1 -ProjectDir <实际项目目录>

模型仅生成、未求解。后续运行前需确认兼容的双精度 SMP 求解器，并给出运行预算和停止条件。

已记录的假设和边界：
"""
    notes += "\n".join(f"{i+1}. {text}" for i, text in enumerate(ASSUMPTIONS))
    notes += "\n\n参数及网格元数据：\n"+json.dumps(model["metadata"], ensure_ascii=False, indent=2)
    notes_path.write_text(notes+"\n", encoding="utf-8")
    return {"preview": str(output), "curve": str(curve_path), "notes": str(notes_path)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    print(json.dumps(export_input_preview(args.project), ensure_ascii=False, indent=2))
