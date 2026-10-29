# Interactive Assessment Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 按用户偏好，本任务顺序实施，仅最终独立审查少量使用子智能体。

**Goal:** 用可修改爆源并运行现有规则的合成演示替代固定住宅案例。

**Architecture:** 固定小网格、合成 ResultAdapter、临时目录内真实 assess 管线、独立本地接口、原 iframe URL 下的交互页面。真实项目存储和求解器不参与。

**Tech Stack:** Python、NumPy、blast_damage_assessment 公开 API；原 Three.js viewer；pytest、Edge/Playwright。

**Spec:** docs/superpowers/specs/2026-09-10-interactive-assessment-demo-design.md

## Global Constraints

- 禁止求解、全量/重型测试、真实项目修改和 DeepSeek。
- 合成数据显式标注；完整结果仍非正式鉴定；缺失/过期不能显示等级零。
- 数量 1—5；X/Y -15—15；Z 0—15；当量 1—1000；模式 complete/partial/blocked。
- 保留用户修改和历史住宅证据。

### Task 1: 合成输入与实际评估

创建 lsprepost_mcp/damage_demo_scene.py、damage_demo_adapter.py、web/damage_demo_api.py、tests/test_interactive_damage_demo.py。

接口：scene_payload() 返回 mesh/components/defaults；validate_demo_input(payload) 返回规范化输入；evaluate_demo(payload) 返回 synthetic_demo/input/snapshot/artifacts。

- [x] 先写重复性、参数变化、缺失门禁、坏输入和工件哈希的行为测试，运行指定文件观察失败。
- [x] 建立三层构件 box 网格及地面格网、原生语义、有限时序数组；通过公开适配器接入 assess，不调用真实文件解析器。

      result = evaluate_demo(payload)
      assert result["synthetic_demo"] is True
      assert result["snapshot"]["overall"]["gate"] == "provisional"

- [x] TemporaryDirectory 只持有本次合成输入和产物；非阻塞锁拒绝并发评估，异常释放锁。返回八项工件文本及 SHA256。
- [x] 运行 python -m pytest tests/test_interactive_damage_demo.py -q，检查代表性快照。

### Task 2: HTTP 隔离入口

修改 lsprepost_mcp/web/app.py；扩展 tests/test_interactive_damage_demo.py。

- [x] 先用真实 HTTP 测试场景读取、演示评估、未知字段/查询、跨源拒绝。
- [x] 在现有本地 Origin/JSON 校验之后增加独立演示分发：

      if path == "/api/damage-assessment/demo/evaluate":
          if query:
              raise ApiError(400, "unknown_query", "Demo does not accept query parameters")
          return json_ok(evaluate_demo(payload))

- [x] 可选包延迟导入，缺失返回可理解 503；接口不接收任意路径或真实项目身份。
- [x] 仅运行新增 HTTP 测试和已有评估 API 专项。

### Task 3: 替换交互页面

替换 static/damage_assessment_demo.html/.css/.js；创建 static/damage_demo_view.js；更新 tests/test_damage_assessment_demo.py、web/tests/damage-assessment-demo.browser.cjs。

- [x] 先写浏览器行为测试：编辑失效、增删源、三状态、着色/选择、外墙隐藏、导出、退出不污染项目。
- [x] 页面职责拆分为视图（viewer/颜色/选择）与控制器（输入/请求/状态/导出）；新增输入时立即清空旧快照与下载链接。
- [x] 复用 createModelViewer({canvas,onPartSelected})，以快照 component_id 映射 Part 等级；输入修改前后的响应身份必须一致才显示。
- [x] 运行期间禁用输入；失败撤销旧结果；HTML/CSV 加演示标记，完整证据包保留原文本/哈希。
- [x] 桌面/移动真实浏览器检查，截图检查，无物理生成或真实项目写请求。

### Task 4: 审查与整合

更新 docs/reviews/blast-damage-assessment/FRONTEND_DEMO.zh-CN.md。

- [x] 独立审查本次差异并修复阻塞项；记录功能覆盖及两项已批准排除。
- [x] 记录主工作区相关文件与无关文件哈希，最小增量应用，尤其保护 app.py 与工作台的其他未提交修改。
- [x] 复验合成演示、原评估入口/API 相关测试，记录实际数目，不跑全量。
- [x] 核对现有服务进程与活跃任务后更新服务；从原演示入口进行只读页面确认。
- [x] 报告交付结果、测试证据、研究限制和原历史资料保留情况。
