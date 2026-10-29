# Phase 18 八步 Schema 与分层物理模型兼容实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先交付可保存、可预览、可验证的 Schema 驱动八步工作台，再恢复并集成 Phase 18 `config@4` 分层空气域与三类建筑物理细化，最终以短时真实求解查错替代 1 ms 传播门槛。

**Architecture:** 后端发布版本化 `workbench_schema`，浏览器按稳定路径渲染 building recipe 与 scenario draft；新增原子 definition save 保证建筑与工况同修订持久化且不触发编译。Phase 18 `config@4` 作为后端能力扩展接入同一八步 Schema，不再替换导航结构。

**Tech Stack:** Python 3.12/3.13、pytest、JSON Schema、JavaScript ES modules、Node runtime fixtures、WebGL 轻量预览、LS-PrePost 4.12、LS-DYNA R12。

**Spec:** `docs/superpowers/specs/2026-08-31-refined-blast-eight-step-layered-compatibility-design.md`

## Global Constraints

- 单位制固定为 `SI_m_s_kg_N_Pa`。
- 所有生产改动遵守 RED → GREEN → REFACTOR；每项提交前运行受影响测试。
- 保存和轻量预览不得调用详细建筑编译器。
- 八步导航是稳定兼容合同，Phase 18 后续能力只能扩展字段。
- 保留旧 `config@1–3` 和 draft-only save 的读取/调用能力。
- 旧 Phase 18 工作树和未提交文件不得覆盖、删除或静默改写。
- 外部程序只在所有软件门禁通过后串行启动。
- 取消 1 ms 传播门槛，最终仅做导入、mcheck 和短时真实求解查错。

---

### Task 1: 发布闭合的八步工作台 Schema

**Files:**
- Create: `lsprepost_mcp/web/refined_blast_workbench_schema.py`
- Modify: `lsprepost_mcp/web/refined_blast_api.py`
- Modify: `lsprepost_mcp/refined_building/asset_compiler.py`
- Test: `tests/test_phase18f_workbench_schema.py`
- Modify: `tests/test_phase18f_state_contract.py`

**Interfaces:**
- Consumes: asset descriptor、building recipe schema、generation-options schema、scenario draft schema、provider input schema。
- Produces: `refined_blast.workbench_schema@1`，包含 8 个 section 和唯一字段路径。

- [ ] 写失败测试：断言 capability 返回八个稳定 section；02–06 均有实际字段或显式 applicability；所有 building/provider 可编辑字段恰好映射一次。
- [ ] 运行 `python -m pytest -q --basetemp .pytest_tmp_task1_red tests/test_phase18f_workbench_schema.py tests/test_phase18f_state_contract.py`，确认因缺少 `workbench_schema` 失败。
- [ ] 实现 section/field dataclass、中文标签/单位/顺序/适用条件和 JSON 序列化；拒绝重复、孤儿或未知路径。
- [ ] 运行同一测试到 GREEN，并运行 `python -m compileall -q lsprepost_mcp`。
- [ ] 提交 `feat: publish eight-step refined blast schema`。

### Task 2: 原子保存 building definition 与 scenario draft

**Files:**
- Create: `lsprepost_mcp/refined_blast/definition.py`
- Modify: `lsprepost_mcp/refined_blast/store.py`
- Modify: `lsprepost_mcp/web/refined_blast_api.py`
- Modify: `lsprepost_mcp/web/static/refined_blast_state.js`
- Test: `tests/test_phase18f_definition_save.py`
- Modify: `tests/test_phase18f_api.py`

**Interfaces:**
- Consumes: `refined_blast.definition_save@1 {expected_revision, building, draft}`。
- Produces: 单一新 revision、building recipe fingerprint、scenario fingerprint 和失效后的生成门禁。

- [ ] 写失败测试：创建后修改 mesh/material/geometry 与 TNT，definition save 后重载值完全一致；详细建筑编译器调用次数仍为 0。
- [ ] 写故障注入测试：recipe、metadata 或 project 任一步写失败均不暴露部分新修订。
- [ ] 运行 RED 测试并确认失败原因是 definition save 缺失。
- [ ] 实现闭合合同、项目锁内原子写入/恢复和旧 draft-only save 兼容；建筑变化清除 artifact/preview/validation/generation/action identity。
- [ ] 运行 Task 2 测试和现有 API/并发/持久化聚合到 GREEN。
- [ ] 提交 `feat: save refined blast definitions atomically`。

### Task 3: 浏览器按 Schema 编辑 building 与 draft

**Files:**
- Modify: `lsprepost_mcp/web/static/refined_blast_state.js`
- Create: `lsprepost_mcp/web/static/refined_blast_fields.js`
- Modify: `lsprepost_mcp/web/static/refined_blast_workbench.js`
- Modify: `lsprepost_mcp/web/static/refined_blast_workbench.css`
- Create: `web/tests/refined-blast-eight-step.runtime.cjs`
- Modify: `tests/test_phase18f_web_contract.py`

**Interfaces:**
- Consumes: `workbench_schema.sections[].fields[]` 和统一 `building.* / draft.*` 路径。
- Produces: 8 个可编辑步骤、字段级错误、definition-save payload。

- [ ] 写 Node/browser contract 失败测试：逐步切换后 02–06 出现真实控件，修改值写入正确根对象，返回后恢复。
- [ ] 运行 Node fixture 和 Python Web contract，确认当前占位实现失败。
- [ ] 抽出通用字段渲染/解析器；支持 number、integer、boolean、enum、vector3、string-array 和只读 derived 字段。
- [ ] 用 Schema 替换 `step === 1 / step === 7 / else placeholder` 分支；高级字段折叠但可编辑。
- [ ] 将显式保存改为 definition save，未创建项目继续使用 session draft，已创建项目恢复自动保存。
- [ ] 运行 Node/Python 聚合到 GREEN，提交 `feat: render all refined blast steps from schema`。

### Task 4: 准确的步骤状态与验证定位

**Files:**
- Modify: `lsprepost_mcp/web/static/refined_blast_state.js`
- Modify: `lsprepost_mcp/web/static/refined_blast_workbench.js`
- Modify: `lsprepost_mcp/refined_blast/validation.py`
- Test: `tests/test_phase18f_step_status.py`
- Modify: `web/tests/refined-blast-eight-step.runtime.cjs`

**Interfaces:**
- Produces: `not_applicable / pending / defaulted / configured / warning / error` 和 finding → section 映射。

- [ ] 写失败测试覆盖三资产和四 provider 的每步状态、默认值、显式覆盖、旧验证失效与错误定位。
- [ ] 运行 RED；确认现实现只标记 01、07、08。
- [ ] 实现后端路径归属与前端确定性状态计算；第 08 步只接受当前保存修订的验证。
- [ ] 运行状态、验证、持久化测试到 GREEN，提交 `fix: derive refined blast step status from schema`。

### Task 5: 地面、空气、TNT 与网格轻量预览

**Files:**
- Modify: `lsprepost_mcp/refined_blast/preview.py`
- Modify: `lsprepost_mcp/web/refined_blast_preview.py`
- Modify: `lsprepost_mcp/web/static/refined_blast_viewer.js`
- Modify: `lsprepost_mcp/web/static/refined_blast_workbench.css`
- Modify: `tests/test_phase18f_preview.py`
- Create: `web/tests/refined-blast-ground-mesh-preview.runtime.cjs`

**Interfaces:**
- Produces: building slab/foundation、support ground、active air、TNT 和代表性 grid-hint 图层；不产生真实详细网格。

- [ ] 写失败测试：ground 与 building 可区分；mesh profile、air size、ground size 改动改变预览指纹/图例；TNT 移动更新位置。
- [ ] 运行 RED，确认当前 generic ground proxy 和无网格提示不满足。
- [ ] 实现分层代理、代表性网格线、颜色/透明度/图例和 provider 不适用提示。
- [ ] 验证保存/预览仍不调用详细编译器，运行 preview/runtime 测试到 GREEN。
- [ ] 提交 `feat: preview refined blast ground and mesh controls`。

### Task 6: 三场景浏览器验收与八步兼容基线

**Files:**
- Create: `tools/capture_refined_blast_eight_step.mjs`
- Create: `tests/test_phase18f_eight_step_e2e_contract.py`
- Modify: `tests/test_phase18f_persistence_contract.py`

**Interfaces:**
- Produces: 商业超市、住宅、地铁入口逐步截图与机器可读 acceptance JSON。

- [ ] 写失败 contract：脚本必须遍历 8 步、保存、刷新预览、验证、返回/恢复，且不点击生成 K 包。
- [ ] 实现可重复浏览器脚本并运行三场景；检查重叠、截断、状态、单位和恢复值。
- [ ] 运行 Phase18F 165 项基线及新增测试，记录测试数和截图目录。
- [ ] 提交 `test: freeze eight-step refined blast compatibility`。

### Task 7: 恢复并集成中断的 Phase 18 `config@4` 工作

**Files:**
- Integrate commits: `ae04727`、`72e4c33`、`4e1d94d`、`494020a`
- Preserve/review worktree: `.worktrees/phase18-layered-air-physical-fidelity`
- Modify only files identified by merge conflicts and RED tests。

**Interfaces:**
- Consumes: 已冻结八步 workbench schema。
- Produces: `config@4`、active air、1–5 layer buffer、拓扑和边界能力，并保持八步 UI。

- [ ] 在旧工作树运行其已提交 Task 1–4 测试，记录真实基线；不清理未提交文件。
- [ ] 审查未提交 surface-topology/material/mesh-quality diff，分别完成 RED/GREEN 后提交。
- [ ] 将旧分支提交合入当前集成分支；解决冲突时以八步 Schema 和 definition save 为 UI 生命周期权威。
- [ ] 添加兼容测试：`@1–3` 唯一迁移，`@4` 字段进入 06/07，八步数量保持 8。
- [ ] 运行 solver-blast core、Phase18F 和 Phase17/18 兼容聚合，提交 `feat: integrate layered phase18 config with eight-step workbench`。

### Task 8: 完成三类建筑物理细化与审查资源

**Files:**
- Modify: `lsprepost_mcp/refined_building/solver_blast/physical_building.py`
- Modify/Create under: `lsprepost_mcp/refined_building/solver_blast/buildings/`
- Modify: `lsprepost_mcp/refined_building/solver_blast/ground.py`
- Modify: `lsprepost_mcp/refined_building/solver_blast/fsi.py`
- Modify: `lsprepost_mcp/refined_building/solver_blast/validation.py`
- Test: `tests/test_phase18_solver_blast_buildings.py`
- Test: `tests/test_phase18_solver_blast_surface_topology.py`
- Test: `tests/test_phase18_solver_blast_quality.py`

**Interfaces:**
- Produces: 三类建筑真实荷载路径、构件/连接/配筋证据、土体开挖闭合和暴露面 FSI。

- [ ] 商业超市先写 RED：Solid RC 柱+纵筋+闭合箍筋、双向墙筋、屋盖到基础连续路径；实现并提交。
- [ ] 住宅先写 RED：无虚假空层、竖向构件对齐、剪力墙/核心筒/楼梯支承、基础闭合；实现并提交。
- [ ] 地铁先写 RED：Solid 地下箱体/地上不透明围护、开挖土体无重叠、入口为内部空气唯一外连路径；实现并提交。
- [ ] 为 Solid/Shell/Beam 物理依据、截面、宿主和连接增加审查；运行三资产聚合到 GREEN。

### Task 9: 将 Phase 18 物理参数投影回八步 Schema

**Files:**
- Modify: `lsprepost_mcp/web/refined_blast_workbench_schema.py`
- Modify: `lsprepost_mcp/refined_blast/providers/solver_complete_ale_fsi.py`
- Modify: `lsprepost_mcp/refined_blast/preview.py`
- Modify: `lsprepost_mcp/web/static/refined_blast_viewer.js`
- Test: `tests/test_phase18f_workbench_schema.py`
- Test: `tests/test_phase18_solver_blast_provider.py`

**Interfaces:**
- Produces: buffer/material/boundary/topology/probe 字段与预览图层，分别归属 05、06、07、08。

- [ ] 写失败测试断言所有 `config@4` 可编辑字段唯一映射且旧项目显示迁移来源。
- [ ] 实现 Schema 扩展、预览层和 validation finding 路由，不增加或减少导航步骤。
- [ ] 浏览器重新执行三场景八步验收，确认 `config@4` 保存/恢复/生成身份一致。
- [ ] 提交 `feat: expose layered phase18 controls in eight-step schema`。

### Task 10: 全量回归、生成和短时真实求解查错

**Files:**
- Modify: `scripts/run_phase18_solver_blast_validation.py`
- Create: `docs/reviews/phase18/PHASE18_EIGHT_STEP_LAYERED_SHORT_SOLVE_REPORT.zh-CN.md`
- Modify: `tests/test_phase18_solver_blast_script.py`
- External output: a new immutable folder under `E:\K文件模型\`。

**Interfaces:**
- Produces: 三个新 K 包、LS-PrePost import、R12 mcheck、short-solve 记录和最终兼容报告。

- [ ] 写失败测试：stage 只允许 `mcheck` 和 `short_solve`；报告不得要求 `final_problem_time_s >= 0.001` 或声称 propagation PASS。
- [ ] 实现短时 stage，记录请求/实际终止时间、return code、fatal/error/negative-volume/NaN findings 和精确 K/solver SHA-256。
- [ ] 运行全部 Python/Node/packaging/Phase17/18/Web 兼容测试；任何失败先写最小回归测试再修复。
- [ ] 生成三个新模型，串行运行 LS-PrePost 导入和 R12 mcheck。
- [ ] 串行运行短时实际求解；若出现错误，追溯生成链并以 RED/GREEN 修复后重新生成新不可变快照。
- [ ] 写报告，明确“短时无报错 ≠ 1 ms 传播 PASS ≠ 工程验证”；提交报告。

## Plan Self-Review

- Spec coverage：Task 1–6 完成方案 A；Task 7–9 恢复并兼容 Phase 18 物理细化；Task 10 替代旧 1 ms 门槛。
- 冲突消解：旧计划 Task 9 的四步 UI 被八步 Schema 取代；旧计划 Task 12 的 propagation 1 ms 不再执行。
- 类型一致性：所有 UI 路径只使用 `building.*` 或 `draft.*`；`config@4` 归属 provider input，不产生第三份真值。
- 安全：旧工作树未提交成果原样保留；外部程序在软件门禁后串行执行；历史证据不改写。
- 无占位项：每个任务指定文件、接口、RED/GREEN 命令或验收动作。

