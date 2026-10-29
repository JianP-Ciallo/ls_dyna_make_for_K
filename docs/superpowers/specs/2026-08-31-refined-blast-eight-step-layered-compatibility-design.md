# Phase 18 八步 Schema 工作台与分层物理模型兼容设计

状态：用户已确认，进入实施

日期：2026-08-31

单位制：`SI_m_s_kg_N_Pa`

## 1. 目标与实施顺序

本设计合并两个连续目标，执行顺序不可颠倒：

1. 先完成 Schema 驱动的完整八步精细化爆炸工作台；
2. 冻结八步 Schema、保存和轻量预览兼容基线；
3. 再恢复 Phase 18 三类建筑分层空气域与物理细化；
4. 将 `config@4`、1–5 层耦合缓冲、土体、实体 TNT、暴露面 FSI 和建筑细节接入同一八步 Schema；
5. 最终只执行 LS-PrePost 导入、R12 `mcheck` 和短时实际求解查错，不再把 1 ms 传播验证作为本轮通过条件。

## 2. 单一真值与组件边界

后端 capability API 是工作台字段的唯一真值。它发布版本化的 `workbench_schema`，每个字段声明：

- `path`：以 `building.` 或 `draft.` 开头的稳定路径；
- `section_id`：八步中的唯一归属；
- `label_zh`、`description_zh`、`unit`、`order`；
- JSON 类型、范围、枚举、默认值和是否高级；
- 适用资产、结构体系和载荷提供器；
- 状态与验证归属。

浏览器只负责按 Schema 渲染、编辑和展示状态，不维护第二份生成参数表。生成器和验证器继续拥有物理范围、闭合合同和 K 文件语义。

组件拆分：

- `refined_blast_workbench_schema.py`：组合建筑资源、场景合同和 provider Schema，生成八步 UI Schema；
- `refined_blast_definition.py`：规范化可原子保存的建筑定义与场景草稿；
- `refined_blast_state.js`：按路径更新 `building` 或 `draft`，计算可见字段和值来源；
- `refined_blast_workbench.js`：渲染八步、保存、状态和错误定位；
- `refined_blast_viewer.js`：显示地面、空气、TNT、结构和网格提示；
- Phase 18 `config@4` 模块：只扩展后端 Schema 和物理生成，不改变八步导航合同。

## 3. 八步语义

| 步骤 | section_id | 配置内容 |
|---|---|---|
| 01 建筑 | `building_space` | 资产、工况、位置、旋转、楼层、空间尺寸和洞口 |
| 02 结构 | `structural_system` | 结构体系、保真度、承重柱梁墙板、基础和地下箱体 |
| 03 连接 | `connections` | 配筋模式、钢筋直径/间距/保护层、钢构和组合连接 |
| 04 构件 | `nonstructural` | 幕墙、门窗、隔墙、楼梯、扶梯和附属设施 |
| 05 材料 | `materials` | 材料角色绑定、截面、失效模型和审查状态 |
| 06 网格 | `mesh_ground` | 建筑网格、空气网格、地面网格、局部加密、地面和耦合缓冲 |
| 07 爆源 | `blast_load` | provider、TNT 当量/位置/起爆、空气余量、边界与求解时间 |
| 08 检查 | `validation` | 当前修订的几何、材料、网格、FSI、预算和生成门禁 |

无适用字段的步骤显示“本工况不适用”，不得显示“待配置”。

## 4. 状态模型

步骤状态是后端 Schema、当前值和当前修订验证结果的确定性函数：

- `not_applicable`：当前资产/结构/provider 没有适用字段；
- `pending`：存在缺失或无效必填字段；
- `defaulted`：字段有效且全部来自权威默认值；
- `configured`：字段有效且至少一个值是显式覆盖；
- `warning`：当前修订在该步骤有未确认警告；
- `error`：当前修订在该步骤有阻断错误；
- 第 08 步只有当前保存修订验证完成后才可为 `configured`。

旧验证、旧预览和旧生成包在任一字段变化后立即失效。

## 5. 保存与生命周期

保存草稿不得编译详细建筑、生成网格或写 K 文件。新增版本化原子保存合同，同时保存：

- 闭合的 building recipe；
- 单一 scenario draft；
- 期望修订号；
- Schema 版本和输入指纹。

服务端在同一项目锁内校验、写入 recipe/metadata/project，并只在全部写入成功后推进修订。失败或进程中断后，旧修订仍是唯一可见权威状态。

兼容规则：旧的 draft-only save 接口继续可用；新工作台使用 definition save。建筑定义变化使已编译 artifact、preview、validation、generation 和外部操作确认全部失效。完整建筑编译只发生在“生成 K 包”。

## 6. 地面与网格

工作台明确区分：

1. 建筑混凝土基础/地坪板；
2. 支承土体或场景地面；
3. ALE active air；
4. 地坪附近 1–5 层 coupling buffer；
5. 实体 TNT。

现有 `config@3` 的公开范围继续有效：空气单元 `0.15–0.50 m`，地面单元 `0.10–0.50 m`。建筑网格提供 `coarse / standard / fine` 三档并显示各构件目标尺寸。`config@4` 增加近场网格、五向空气余量、1–5 层缓冲、材料档案和边界参数；旧 `@1–3` 通过唯一迁移补入默认值，未知字段仍拒绝。

轻量预览不生成真实全量网格，但必须显示：建筑包络、混凝土基础/地坪、支承地面、active air、buffer、TNT、边界和代表性网格线；同时给出估算值和“生成时统计”的明确语义。

## 7. Phase 18 物理细化兼容

保留此前 `codex/phase18-layered-air-physical-fidelity` 工作树的已提交 `config@4`、active-air/buffer、空气拓扑和边界成果，以及未提交的表面拓扑、材料审查和网格质量成果。集成时逐提交审查，禁止用新分支覆盖该工作树。

三类建筑继续遵守已确认的物理要求：

- 商业超市具有 Solid RC 柱、纵筋、闭合箍筋、双向墙筋和连续屋盖—柱—基础—土体荷载路径；
- 住宅关闭无设计依据的空层，形成连续框架—剪力墙—核心筒—基础体系；
- 地铁入口地下底板、侧墙、顶板和地上不透明围护为 Solid，玻璃可为 Shell，钢筋/细长框架可为 Beam；
- Solid、Shell、Beam 可以有物理依据地共存，每个非 Solid 单元必须有截面、宿主/连接和审查证据；
- 外部空气不得形成通向埋置底面或地下外墙的自由传播通道；FSI 只使用真实空气暴露面。

## 8. 验证与最终判据

软件门禁：

- Schema 中每个可编辑生成输入恰好归属一个步骤；
- 三场景保存/返回恢复后字段、单位和值不漂移；
- 保存和轻量预览不编译详细建筑；
- 生成后的 normalized input、manifest 和 K 文件参数与 UI 当前修订一致；
- Phase 17、Phase 18A–F、Web、打包和旧项目读取回归通过。

外部程序门禁：

1. 三个新快照分别通过 LS-PrePost 导入，关键字读取无未审查 error；
2. 三个快照分别通过 R12 `mcheck`；
3. 三个快照分别执行短时实际求解，检查初始化和若干有效时间步；
4. 无 fatal/error、异常退出、NaN、未接受负体积或关键字问题；
5. 记录实际终止时间和所有日志，但不要求达到 `0.001 s`，也不要求形成 1 ms 传播 PASS。

短时无报错只证明该快照可初始化并开始求解，不证明爆炸传播、峰值压力、破坏或工程安全结论成立。最终仍保持 `engineering_validated=false`、`solver_ready=false`、`requires_project_review=true`。

## 9. 非目标

- 不为达到 45–70 MiB 制造无物理意义网格；
- 不删除或改写历史 1 ms/失败诊断证据；
- 不把短时无报错描述成三项最终传播 PASS；
- 不在保存、预览或验证时隐式启动 LS-PrePost/LS-DYNA；
- 不把旧项目静默升级成 `config@4` 新能力。

