# README 阶段与功能状态核对

核对日期：2026-10-30。范围为根目录两份 README 及其直接导航说明，依据当前源码和已保存文档/结果；本次不重新执行历史求解、不做全量回归或真实重型案例。文档中的历史通过仅对应原报告列明的输入、版本、方法和验证范围。

## 阶段口径

| 阶段 | 当前可确认的实现/证据 | 保留的验证边界 |
| --- | --- | --- |
| Phase 1–10 | 基础生成、校验、材料/资源、项目、预览、诊断和分发工具链已实现；见 `schema.py`、`tools.py`、`scripts/` 及对应专项。 | 不把阶段实现完成等同于每个材料和工况已做工程标定。 |
| Phase 11–13 | Web 入口、组件装配、物理动作、受控爆炸预设和结果摘要已实现；服务包含组件目录和爆炸案例接口。 | 基础自然语言仍是四类场景；专用工作流不自动变成自然语言或 MCP 工具。 |
| Phase 14 | MM-ALE 生成、结果封存、证据身份、传播与网格比较门禁已有实现。 | [现有验收说明](phase14/PHASE14_MM_ALE_ACCEPTANCE.zh-CN.md)已将旧三档收敛报告降级为无效历史证据，不能引用旧 `converged=true` 为当前工程结论。 |
| Phase 15 | 当前实现基线完成，存在历史受控案例波传递通过记录。 | 共形方案仍实验性；详见[专项状态核对](phase15/PHASE15_STATUS.zh-CN.md)。 |
| Phase 16 | 城市对象级指标、多保真任务规划/比较与不确定性接口已实现；另有[真实结果评估桥接验收](blast-damage-assessment/MAIN_PROJECT_BRIDGE_ACCEPTANCE.zh-CN.md)。 | 多保真接口存在不代表所有策略已校准；建筑/地面规则为研究参考，`formal_eligible=false`。 |
| Phase 17 | 城市编辑、草稿预览、项目生成和对象交互已实现，见 `web/draft_preview.py`、编辑器与相关 API。 | 城市场景的[原验收范围](city-street/CITY_STREET_BLAST_SCENE.zh-CN.md)不能因后续其他建筑通过而自动升级为城市真实求解通过。 |
| Phase 18A–18F | 资产、内核、独立爆炸引擎和工作台已有软件验收；[18F 报告](phase18/PHASE18F_REFINED_BLAST_WORKBENCH_REPORT.zh-CN.md)记录指定版本的软件 PASS。 | 软件通过与外部工程验证分开；后续独立求解路径的证据不能反向赋予所有旧提供器相同资格。 |

基础实现来源包括 [`tools.py`](../../lsprepost_mcp/tools.py)、[`schema.py`](../../lsprepost_mcp/schema.py)、[Web 服务](../../lsprepost_mcp/web/app.py)、[城市编辑适配](../../lsprepost_mcp/web/draft_preview.py)及[多保真接口](../../lsprepost_mcp/web/phase16b_api.py)。早期[路线图](../ROADMAP.zh-CN.md)保留为规划快照，其中未完成项不能直接作为当前实现状态。

## Phase 18 后续求解记录不能合并为一个结论

- [2026-08-21 独立 ALE/FSI 报告](phase18/PHASE18_SOLVER_COMPLETE_ALE_FSI_REPORT.zh-CN.md)：记录商业超市、住宅和地铁入口的实际导入、R12 初始化及指定 1 ms 初始传播验证。
- [2026-09-01 config@4 报告](phase18/PHASE18_CONFIG4_LAYERED_SHORT_SOLVE_ACCEPTANCE_20260901.zh-CN.md)：记录三个最终配置经同一 K/同一求解器完成 `5.0e-5 s` 短求解；验收模式为 `configured_short_solve_no_error`，明确不是 1 ms 传播验收。
- 两份报告对应不同模型/配置和时长。后一记录不能借用前一记录把自身标为 1 ms，通过也不代表完整爆炸事件、材料标定或工程安全评估完成。报告继续保留 `solver_ready=false`、`requires_project_review=true` 等边界。

## 当前功能入口与旧说明的修正

| 旧说明 | 本次对照结果与修正 |
| --- | --- |
| 损伤演示只读取历史住宅报告，不执行评估、不需要评估依赖。 | 默认已是交互式合成演示，专用 POST 调用公开评估模块处理合成时序，需可选依赖；旧静态报告为历史资料。见[演示说明](blast-damage-assessment/FRONTEND_DEMO.zh-CN.md)和[当前实现](../../lsprepost_mcp/web/damage_demo_api.py)。 |
| 没有 Node.js 才使用原生“兜底页面”。 | 正式服务固定读取 `lsprepost_mcp/web/static/`；`web/dist` 不覆盖它，旧 React 文件不是正式构建输入。见[前端说明](../../web/README.md)。 |
| 固定建筑只有给定压力及 K 包页面。 | 默认 `/structural-pressure` 是室外 TNT 工作流，旧压力页面由 `?legacy=1` 保留；显式确认生成 K 包，不提供原生求解端点。既有 binout 压力曲线读取另需 `lasso-python`。见[TNT 集成记录](2026-10-23-fixed-building-tnt-integration.md)。 |
| CPU 页面只包含单柱/单板，整栋相关页面一律未开放。 | `/cpu-blast` 默认是五类轻量 Worker 演示；`?legacy=1` 保留原生场景记录与诊断；`/fixed-building-pressure/response` 为弹性参考及历史首试报告/静态图表的只读查看与下载。整栋三维回放未启用，不能混用三条路径的能力和证据。 |
| 基础通用类型/三种材料就是项目全部能力。 | 四种基础自然语言与通用生成 Schema 仍有限；专用建筑/爆炸和固定来源重建采用独立编译器/入口。来源卡片依赖和工程资格不因重建成功而消失。 |
| 普通打包等同于内置 Python 的便携包。 | 普通 `pack.ps1` 生成源码包；便携包需额外传入已校验运行时。源码 ZIP 不包含本机环境。 |

页面映射来源为 [`fixed_building_workspace.py`](../../lsprepost_mcp/web/fixed_building_workspace.py)；当前默认演示见 [2026-10-24 CPU 接入报告](../superpowers/reports/2026-10-24-cpu-demo-workbench-integration.md)及[简化响应改进记录](../superpowers/reports/2026-10-24-scene-physics.md)。这些是演示/软件检查，不是原生工程求解资格。

## CPU 参考算例历史记录

本次只读了以下已有小型 Markdown 报告；大体积运行结果及完整验收数据仍保留在本机，不随 GitHub 源码上传。

| 本地历史来源 | 可引用的历史结论 |
| --- | --- |
| `artifacts/cpu-response-acceptance-20261022-07/validation/acceptance.md` | 两个弹性参考算例在 150 ms 时窗下记录 16→32 空间细化及步长减半检查通过。柱/板钢筋峰值空间变化分别为 0.0676% / 0.8288%，最细单板耗时 7.864 s。 |
| `artifacts/cpu-response-building-preflight-20261022-04/preflight.md` | 独立三层柱板参考：630 个结构节点、402 个柔性壳、144 个纤维梁柱单元；原配筋及质量映射的核验，不等同于整栋求解通过。 |
| `artifacts/cpu-response-building-trial-20261022-01/analysis/report.md` | 2026-10-22 单墙面 10 kPa 给定压力的线弹性首试完成 150 ms / 1500 步；父进程 97.947 s，位移幅值峰值 0.080701 mm，钢筋轴向应力绝对值峰值 1.508288 MPa。未验收整栋收敛或真实爆炸精度。 |

历史首试通过 CLI 执行。当前[保存结果适配器](../../lsprepost_mcp/architecture/cpu_response/saved_building.py)和 [CPU API](../../lsprepost_mcp/architecture/cpu_response/api.py)支持本机已有产物的只读状态/下载；[服务能力](../../lsprepost_mcp/architecture/cpu_response/service.py)仍声明 `building_enabled=false`，不能据此声称页面已开放新的整栋参考求解。

## 原生非线性整栋的未通过项

后续[精度运行时复验](../superpowers/reports/2026-10-24-native-whole-gravity-precision-revalidation.md)与[局部保护运行时复验](../superpowers/reports/2026-10-24-native-whole-gravity-guard-revalidation.md)均记录：10% 自重步接受，目标 25% 步原生失败并立即停止。

这些记录与前面的给定压力线弹性首试、浏览器轻量演示属于不同方法和工况，不能互相替代。不能声称原生候选满自重、后续 TNT、完整时程或工程精度已经通过；本次也没有重新运行它们。
