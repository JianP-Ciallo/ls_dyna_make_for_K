"""Self-contained Chinese HTML assessment report."""

from __future__ import annotations

import html
from collections.abc import Iterable, Mapping


_SEVERITY = {
    None: "不可给出",
    0: "未见明显损伤",
    1: "轻微",
    2: "中等",
    3: "严重",
    4: "极严重",
}


def _escape(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _items(values: object, empty: str = "无") -> str:
    if not isinstance(values, Iterable) or isinstance(values, (str, bytes, Mapping)):
        values = ()
    rendered = "".join(f"<li>{_escape(value)}</li>" for value in values)
    return rendered or f"<li>{_escape(empty)}</li>"


def _metric_items(metrics: object) -> str:
    if not isinstance(metrics, Mapping):
        return _items(())
    return _items(f"{key}={metrics[key]}" for key in sorted(metrics))



def render_html_report(snapshot: Mapping[str, object]) -> str:
    overall = snapshot.get("overall", {})
    building = snapshot.get("building", {})
    ground = snapshot.get("ground", {})
    if not isinstance(overall, Mapping):
        overall = {}
    if not isinstance(building, Mapping):
        building = {}
    if not isinstance(ground, Mapping):
        ground = {}
    components = building.get("components", [])
    component_rows = []
    for item in components if isinstance(components, list) else []:
        if not isinstance(item, Mapping):
            continue
        component_rows.append(
            "<tr>"
            f"<td>{_escape(item.get('component_id'))}</td>"
            f"<td>{_escape(item.get('importance_class'))}</td>"
            f"<td>{_escape(item.get('gate', building.get('gate')))}</td>"
            f"<td>{_escape(_SEVERITY.get(item.get('severity'), item.get('severity')))}</td>"
            f"<td>{_escape(item.get('p99_relative_deformation'))}</td>"
            f"<td><ul>{_metric_items(item.get('response_metrics'))}</ul></td>"
            "</tr>"
        )
    stability = ground.get("stability", {})
    shape_term = stability.get("shape_term") if isinstance(stability, Mapping) else None
    shape_label = "残余形态" if shape_term == "residual_shape" else "瞬时末态"
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>爆炸后建筑与地面损伤评估报告</title>
<style>body{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#18202a}h1,h2{color:#123b5d}.badge{display:inline-block;padding:.2rem .6rem;border:1px solid #557;border-radius:1rem}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccd;padding:.4rem;text-align:left}.notice{background:#fff6d8;padding:.8rem;border-left:4px solid #d59b00}</style></head><body>""" + (
        f"<h1>爆炸后建筑与地面损伤评估报告</h1><p>评估编号：{_escape(snapshot.get('assessment_id'))}</p>"
        f"<h2>总评</h2><p>可评估性门禁：<span class=\"badge\">{_escape(overall.get('gate'))}</span>；损伤等级：{_escape(_SEVERITY.get(overall.get('severity'), overall.get('severity')))}</p>"
        f"<h2>建筑</h2><p>门禁：{_escape(building.get('gate'))}；等级：{_escape(_SEVERITY.get(building.get('severity'), building.get('severity')))}</p>"
        "<table><thead><tr><th>构件</th><th>重要性</th><th>门禁</th><th>等级</th><th>P99 相对变形</th><th>响应指标</th></tr></thead><tbody>"
        + ("".join(component_rows) or "<tr><td colspan=\"6\">无可评估建筑构件</td></tr>")
        + "</tbody></table>"
        f"<h2>地面</h2><p>门禁：{_escape(ground.get('gate'))}；等级：{_escape(_SEVERITY.get(ground.get('severity'), ground.get('severity')))}；形态结论：{shape_label}</p>"
        f"<h3>地面材料响应指标</h3><ul>{_metric_items(ground.get('material_metrics'))}</ul>"
        f"<section class=\"notice\"><h2>局限性</h2><ul>{_items(snapshot.get('limitations'))}</ul>"
        f"<h3>缺失字段</h3><ul>{_items(snapshot.get('missing_fields'))}</ul>"
        f"<h3>推断语义</h3><ul>{_items(snapshot.get('inferences'))}</ul>"
        f"<h3>人工复核</h3><ul>{_items(snapshot.get('review_items'))}</ul></section>"
        "</body></html>"
    )
