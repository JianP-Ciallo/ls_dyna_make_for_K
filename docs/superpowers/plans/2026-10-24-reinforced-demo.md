# 三层住宅等效钢筋束实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 保留当前三层住宅，按 K 规则布筋，完整显示并通过简化钢筋束双向参与受力。

**Architecture:** 离线提取小型可审计 K 配筋目录；纯函数映射到当前构件；独立束约束模块连接混凝土节点/刚块，接入现有碎裂接触时间步；独立加筋方法与旧历史隔离。Three.js 显示完整筋线和断口。

**Tech Stack:** Python 标准库提取、原生 ES modules、Three.js、Node/pytest 专项、Edge。

**Spec:** `docs/superpowers/specs/2026-10-24-reinforced-demo.md`，依据当前会话已确认范围。

## Global Constraints

现有房屋几何、材料破坏规则、旧修改和历史保留；只做三层加筋，不恢复复杂自重。不存在的配筋不补造；其他场景保持原方法；不运行全量/原生整栋/13 单元/TNT/小区长测或其他重型。不提交、合并或清理旧目录。

## Review Focus

1. K 网格段不等于物理筋根数，必须保留来源、层位、直径、规则及等效总面积。
2. 视觉分块边界不能变成钢筋断口，洞口和无筋轻质隔墙不能新增钢筋。
3. 拉结必须双向，断裂后不再传力；接触位置更新和休眠不能把受拉碎片冻结。
4. 旧结果不能冒充加筋结果；无筋/其他场景路径保持原行为。
5. 显示完整布筋、塑性/弯曲和断口必须有动态状态依据，零输入不改变形状。

## Tasks

- [x] **1. 来源与映射。** 新增 `scripts/build_demo_rebar_catalog.py`、`blast_rebar_catalog.js`、`blast_rebar_layout.js`；先写来源/连续性/几何不变测试，观察缺模块失败，再实现提取与映射。来源不运行模型生成或求解。
- [x] **2. 受力与耦合。** 新增 `blast_rebar_bundles.js`，最小拉结/弯曲/塑性/断裂/零输入测试先红后绿；修改 `blast_panel_fracture.js` 暴露受力点和增量反馈、`blast_demo_model.js` 接入束时间步和独立方法，保持无筋路径；接触/休眠专项复查。
- [x] **3. 显示与缓存。** 新增 `blast_rebar_view.js`，controller/view/两 HTML 接入三层加筋选择、检查视图与统计；CPU 缓存选正确方法，静态白名单/打包覆盖；先写 API/浏览器接口断言再实现。
- [x] **4. 专项验收与审查。** 相关 Node/pytest；Edge 静态/短程和已保存旧结果回放，限时不追加长测。必要的一次独立只读审查，修正阻塞后复查。
- [x] **5. 交付与保留。** 来源、变化、边界、耗时及真实结果写报告；哈希核验旧证据。仅清理本轮测试临时配置，保留全部结果。
