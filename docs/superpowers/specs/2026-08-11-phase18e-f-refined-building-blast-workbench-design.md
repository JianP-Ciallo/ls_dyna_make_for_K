# Phase 18E–F 独立精细建筑爆炸工况与工作台设计

日期：2026-08-11
状态：用户已批准总体架构、独立入口、视觉一致性与软件验收边界

## 1. 目标

Phase 18E 建立独立项目类型 `refined_building_blast@1`，消费 Phase 18D 已通过软件门禁的参数化 `BuildingArtifact`，生成外部、内部、半封闭和参数组合精细建筑爆炸工况。

Phase 18F 在现有 Web 应用中新增“精细化建筑爆炸”入口，进入独立工作台。新工作台延续旧工作台的视觉语言和通用三维操作，但使用独立路由、API、草案、缓存、结果状态和验证闭环。

本轮完成软件生成、预览、验证和兼容性验收。没有真实 LS-PrePost 导入、目标 LS-DYNA 求解、材料标定、网格敏感性或试验对照证据时，所有工况继续保持：

- `solver_ready=false`
- `requires_project_review=true`
- `engineering_validated=false`

## 2. 范围

### 2.1 Phase 18E

- 独立项目契约、存储、版本、缓存和失效规则。
- 三种首发 `BlastLoadProvider`：
  - `explicit_ale_fsi`
  - `lbe_segment`
  - `imported_pressure_history`
- 外部、内部、半封闭和参数组合工况。
- 建筑放置、支承/地面、爆源、流体域、边界、交互/FSI、求解控制和输出模块。
- 确定性 ID 分区、Include 顺序、依赖闭包、规模预算和 K 包 manifest。
- 分层预览适配器和跨模块验证器。
- 审核预设、项目覆盖和受控专家扩展。

### 2.2 Phase 18F

- 现有前端中的“精细化建筑爆炸”入口。
- 独立工作台路由和页面状态。
- schema 驱动的动态字段与适用能力显示。
- 单一草案数据源、自动保存、恢复和版本化。
- 建筑、钢筋/连接、非承重构件、空腔、暴露面、爆源、流体域和边界的分层预览。
- 即时错误、警告、规模预算、版本确认和生成门禁。
- 保存草案、刷新预览、正式生成、打开 LS-PrePost、启动 LS-DYNA 五个独立动作。

### 2.3 明确不在范围内

- 不修改城市项目、城市生成器、城市对象编辑器或粗糙城市建筑。
- 不在旧场景编辑器内增加精细模式。
- 不继承或调用旧爆炸工况生成器。
- 不把 Phase 18E 逻辑继续堆入 `dyna_assembly.py`、通用 `schema.py` 或旧工况模块。
- 不把软件测试结果表述为工程验证。
- 不在未获得用户逐次授权时打开 LS-PrePost 或启动 LS-DYNA。

## 3. 顶层架构

新增顶层领域包：

```text
lsprepost_mcp/
  refined_building/       # Phase 18C–D 建筑语义、网格与 BuildingArtifact
  refined_blast/          # Phase 18E 独立工况领域
    contracts.py
    presets.py
    provider_registry.py
    providers/
      explicit_ale_fsi.py
      lbe_segment.py
      imported_pressure_history.py
    placement.py
    support_ground.py
    blast_source.py
    fluid_domain.py
    boundaries.py
    interactions.py
    controls.py
    outputs.py
    assembler.py
    validation.py
    preview.py
    store.py
    service.py
```

前端新增独立适配层：

```text
lsprepost_mcp/web/
  refined_blast_api.py
  refined_blast_preview.py
  static/
    refined_blast_workbench.js
    refined_blast_workbench.css
```

旧前端只增加入口和路由注册，不把新工作台状态塞入旧场景草案。

## 4. 核心数据契约

### 4.1 RefinedBlastProject

项目根对象固定包含：

- `schema_version="refined_building_blast@1"`
- `project_id`
- `building_reference`
- `building_artifact_fingerprint`
- `preset_reference`
- `preset_version`
- `project_overrides`
- `expert_extensions`
- `scenario_set`
- `confirmation_records`
- `provenance`
- `created_at`、`updated_at`

项目 schema 使用闭合集：未知字段、错误版本、非有限数值、错误单位、空 ID 和重复 ID 均 fail-closed。

### 4.2 ScenarioDraft

每个草案固定包含：

- `scenario_id`
- `scenario_kind`：`external`、`internal` 或 `semi_enclosed`
- `building_placement`
- `support_and_ground`
- `load_provider`
- `blast_source`
- `fluid_domain`
- `boundaries`
- `interactions`
- `solver_controls`
- `output_requests`
- `resource_versions`
- `acknowledged_warning_ids`

同一 `ScenarioSet` 内每个草案独立编译、独立指纹、独立 K 包、独立结果 ID。不得将多个草案静默合并为单个求解模型。

### 4.3 不可变模块片段

每个编译模块输出不可变 `KeywordFragment`：

- `module_id`
- `schema_version`
- `keyword_blocks`
- `declared_ids`
- `required_ids`
- `resource_dependencies`
- `estimated_counts`
- `manifest`
- `fingerprint`

模块不得修改其他模块的输入、片段或状态。只有 `ProjectAssembler` 可以分配最终 ID 区间、排序 Include 和闭合依赖。

## 5. 三种载荷提供器

### 5.1 统一接口

每个提供器实现相同的只读能力接口：

- `provider_id`
- `schema()`
- `capabilities()`
- `normalize(input)`
- `validate(normalized, context)`
- `estimate(normalized, context)`
- `compile(normalized, context)`
- `preview(normalized, context)`
- `evidence_manifest(normalized, context)`

注册表仅依赖提供器描述符，不通过 `if provider_id == ...` 添加隐藏字段或材料角色。

### 5.2 explicit_ale_fsi

输入包括：炸药类型/资源、当量、几何、爆源位置、起爆点、内部能/状态方程资源、空气域网格、域边距、ALE 边界、FSI 选面、耦合参数和控制参数。

验证要求：

- 爆源完全位于允许流体域。
- 爆源与结构 Solid/Shell/Beam 物理包络无非法正体积重叠。
- 内部工况爆源位于有效空腔；半封闭工况同时验证空腔和泄压开口。
- FSI 只使用当前工况真实流体浸润的暴露面。
- 空气域边距、边界、单元预算和资源闭包显式通过。

### 5.3 lbe_segment

输入包括：爆源位置、当量/经验参数、受载方向、距离范围、遮挡策略、表面类别、用户选择集合和时间控制。

验证要求：

- 只能选择与工况类别匹配的内表面或外表面。
- 用户集合必须是自动候选集合的受控子集或显式审核覆盖。
- 不允许把空腔背面、结构内部面或无物理面积面静默加入受载集合。
- 快速提供器不得伪装为 ALE-FSI 等价结果。

### 5.4 imported_pressure_history

输入包括：数据来源、原始 SHA-256、时间/压力单位、列映射、时间序列、插值规则、比例因子、空间映射和目标表面集合。

验证要求：

- 时间严格递增并从非负时刻开始。
- 时间、压力均为有限数；不接受 NaN、Inf 或隐式单位。
- 重复时间、负比例、空曲线和超预算曲线 fail-closed。
- 目标表面集合通过与 LBE 相同的表面类别和空间闭包检查。
- 原始文件哈希、归一化曲线哈希和映射证据进入 manifest。

## 6. 模块化工况编译

编译顺序固定为：

```text
ScenarioDraft / Preset + Overrides
  -> BuildingPlacementCompiler
  -> SupportAndGroundCompiler
  -> BlastSourceCompiler
  -> FluidDomainCompiler
  -> BoundaryCompiler
  -> InteractionAndFSICompiler
  -> SolverControlCompiler
  -> OutputRequestCompiler
  -> ProjectAssembler
  -> CrossModuleValidator
```

### 6.1 BuildingPlacementCompiler

- 验证引用的 Phase 18D artifact 和指纹。
- 只变换放置坐标，不修改建筑局部网格、构件、材料绑定或质量清单。
- 多建筑输入首版明确拒绝，避免把单建筑工况扩成城市工况。

### 6.2 SupportAndGroundCompiler

- 生成地面、支承、约束或用户批准的基础接口片段。
- 验证支承节点/面确实属于建筑基础或指定接口。
- 不用额外 Solid 填充建筑空腔。

### 6.3 BlastSourceCompiler

- 生成提供器需要的爆源、起爆或等效载荷源片段。
- 对爆源和结构/边界的空间关系执行确定性检查。

### 6.4 FluidDomainCompiler

- 外部工况生成外部域。
- 内部工况依据空间、洞口和连通关系生成有效内部域。
- 半封闭工况同时生成内部域、洞口泄压连接和必要外部缓冲域。
- 不可用建筑外包盒代替真实空腔拓扑。

### 6.5 BoundaryCompiler

- 只消费流体域的已分类边界。
- 拒绝重复、冲突、悬空或覆盖结构内部的边界。

### 6.6 InteractionAndFSICompiler

- ALE-FSI、LBE 和压力映射使用不同片段和证据清单。
- 表面选择基于 Phase 18C–D 的内外暴露面目录与当前洞口状态。
- 任一表面不得同时被互斥载荷机制消费。

### 6.7 SolverControlCompiler 与 OutputRequestCompiler

- 控制和输出均由审核预设与项目覆盖生成。
- 研究候选值在 manifest 明示，不标记为工程参数。
- 修改输出请求不使建筑网格缓存失效。

### 6.8 ProjectAssembler

- 按模块保留固定 ID 命名空间。
- 确定性解析跨模块引用。
- 生成稳定 Include 顺序。
- 最终清单记录 Node/Solid/Beam/Shell、集合、曲线、材料、截面和控制卡数量。
- 任一未声明引用、ID 冲突或资源缺失均阻断输出。

## 7. 预设、覆盖和专家扩展

### 7.1 审核预设

首版为三类 Phase 18D 建筑分别提供研究/流程验证预设。预设声明建筑类型、结构体系、载荷提供器、工况类型、网格/域/控制建议值、版本和证据等级。

未完成工程审核的预设状态固定为 `research_candidate`。

### 7.2 项目覆盖

用户可以覆盖建筑选择与放置、洞口状态、支承、装药、爆源、域、边界、交互、控制和输出。每个覆盖记录原值、新值、来源和时间。

### 7.3 专家扩展

专家扩展仅允许：

- 声明式材料/曲线资源引用。
- 受控局部网格区。
- schema 定义的结构化关键字覆盖。
- 项目目录内的受控 Include。

必须通过关键字允许列表、规范化相对路径、项目根目录约束、文件哈希、ID 冲突和依赖闭包检查。禁止绝对路径、目录穿越、未知关键字和修改内核不变量。

## 8. 指纹、缓存和失效

分别计算：

- `building_fingerprint`
- `scenario_input_fingerprint`
- `provider_fingerprint`
- `assembly_fingerprint`
- `preview_fingerprint`
- `output_request_fingerprint`
- `result_fingerprint`

失效规则：

- 改变爆源：建筑 artifact 与建筑预览缓存保持有效，工况及结果失效。
- 改变洞口状态：建筑原始 artifact 保持，暴露面、流体域、交互、预览和结果失效。
- 改变结构体系/网格/材料绑定：建筑及所有下游工况失效。
- 改变输出请求：仅输出片段、装配包和结果失效。
- 资源版本或模块版本改变：依赖该资源/模块的片段与下游产物失效。

同一规范化输入、资源版本和模块版本必须生成相同指纹与清单。

## 9. Phase 18F 工作台

### 9.1 入口与隔离

现有前端项目入口新增“精细化建筑爆炸”按钮，进入独立路由 `/refined-building-blast`。

新工作台共享旧前端的应用外壳、字体、颜色、按钮、输入、弹窗、项目目录和通用 WebGL 相机操作；不读取旧场景对象数组、旧布局草案或旧工况状态。

### 9.2 页面布局

- 左侧：动态配置导航。
- 中央：分层三维预览、图层控制和规模摘要。
- 右侧：当前 schema 字段、即时验证、警告和确认。
- 底部：保存草案、刷新预览、生成 K 包、打开 LS-PrePost、启动 LS-DYNA。

五个动作相互独立。打开 LS-PrePost 与启动 LS-DYNA 默认禁用，只有已生成当前版本 K 包且用户逐次授权时才可执行。

### 9.3 schema 驱动字段

左侧配置固定覆盖八类能力：

1. 建筑空间与洞口。
2. 结构体系与承重构件。
3. 钢筋、钢构或组合连接。
4. 非承重构件。
5. 材料、截面和失效模型。
6. 网格与局部加密。
7. 载荷、爆源、空气域、边界、交互和输出。
8. 错误/警告、规模预算、版本确认和生成。

具体字段由建筑能力描述符和提供器 schema 共同决定。不适用字段不显示，也不保留隐藏旧值。

### 9.4 单一草案真源

- 所有数值输入、选择器和视窗可编辑对象写入同一 `ScenarioDraft`。
- 草案修改递增 revision。
- 预览响应必须携带请求 revision；过期响应不可覆盖新草案。
- 自动保存采用确定性 JSON 快照和原子替换。
- 用户可恢复已保存 revision，但恢复动作创建新 revision，不篡改历史。

### 9.5 分层预览

预览图层包括：

- 空腔和洞口。
- 主体结构。
- 钢筋与连接。
- 非承重构件。
- 内外流体暴露面。
- 爆源和起爆点。
- 空气域和边界。
- 支承/地面。

预览统计使用与正式装配相同的规范化输入和估算器。最终 K 清单必须与预览中标记为 exact 的数量一致；上界估算必须满足实际值不超过估算值。

### 9.6 验证与确认

- `error`：阻断预览后的正式生成，用户不能忽略。
- `warning`：允许用户逐项确认，确认记录包含 finding ID、内容哈希、用户动作、时间和草案 revision。
- `info`：不阻断，只提供来源或预算说明。

结构、工况、资源或 finding 内容变化时，相关旧确认自动失效。

## 10. API 与存储

API 使用独立命名空间 `/api/refined-building-blast/`：

- `GET /capabilities`
- `GET /assets`
- `GET /presets`
- `POST /projects`
- `GET /projects/{project_id}`
- `PUT /projects/{project_id}/draft`
- `POST /projects/{project_id}/validate`
- `POST /projects/{project_id}/preview`
- `POST /projects/{project_id}/generate`
- `GET /projects/{project_id}/artifacts/{artifact_id}`
- `POST /projects/{project_id}/acknowledgements`
- `POST /projects/{project_id}/open-lsprepost`
- `POST /projects/{project_id}/launch-lsdyna`

存储目录与旧项目分离：

```text
workspace/refined_building_blast/<project_id>/
  project.json
  drafts/
  previews/
  generated/
  evidence/
  results/
```

项目 ID、artifact ID 和结果 ID 使用各自命名空间。API 必须拒绝其他项目类型路径和越界 ID。

## 11. 错误处理与安全边界

- 所有公开输入先规范化再进入编译模块。
- bool 不得作为数值；NaN、Inf、负尺寸、重复 ID 和未知枚举均拒绝。
- 所有路径解析后必须仍位于当前项目目录。
- 所有写入使用临时文件加原子替换；失败不得留下半成品正式版本。
- 缓存命中后仍验证 schema、版本和内容哈希。
- 生成失败保留草案和诊断，不覆盖上一个有效 K 包。
- 外部程序调用不属于预览或生成的副作用，必须走独立授权 API。

## 12. 兼容性设计

### 12.1 与 Phase 18A–D

- 18A/18A-1：固定构件 K 包继续只用于对照、回归和刚体实例，不被拉伸伪装成参数化建筑。
- 18B：材料、截面、曲线和耦合资源通过公开审核接口读取；未审核资源进入 manifest 并保持 review 状态。
- 18C：只消费公开 `BuildingDefinition`、`BuildingArtifact`、表面目录、网格和验证接口。
- 18D：只消费公开资产描述符和编译产物，不调用资产模板内部私有函数。
- 五个 Phase 18C 字面指纹和三类 Phase 18D 默认资产指纹必须有回归保护；工况变更不得改变建筑指纹。

### 12.2 与整体项目

- 依赖测试禁止 `refined_blast` 导入城市生成器、旧工况生成器和旧编辑器状态模块。
- 旧模块不得反向导入 `refined_blast`。
- 旧工具名称、API、项目 schema、默认行为和已有测试指纹保持不变。
- 新路由不存在或未启用时，旧前端启动和旧项目加载行为不变。
- 通用材料、关键字写入、路径安全和求解授权接口只能通过稳定公开接口共享。
- 全项目测试至少覆盖项目发现、导入导出、预览、旧爆炸生成、城市场景、Phase 18A–D 和新工作台。

## 13. 验收矩阵

### 13.1 Phase 18E

- 项目契约闭合集、版本和非法输入测试。
- 三种提供器的最小合法夹具、确定性指纹、依赖闭包和失败输入。
- 三类工况的爆源包含、结构不重叠、洞口连通和表面选择。
- 每个编译模块的输入输出闭包与不可变性。
- ProjectAssembler 的 ID、Include、资源和关键字闭包。
- 规模预算在大分配前拒绝；actual 不超过 proved upper，exact 与 actual 相等。
- ScenarioSet 的独立 K 包、结果 ID 和局部失效。

### 13.2 Phase 18F

- 独立路由、API、存储和项目类型。
- 不同建筑体系和三种提供器的动态字段显示。
- 草案保存、恢复、revision、并发过期响应和原子写入。
- 分层预览、图层显隐、统计和正式 K 清单一致。
- error 阻断、warning 确认、确认失效和来源记录。
- 五个独立动作及 LS-PrePost/LS-DYNA 逐次授权。
- 浏览器端单元测试、API 测试和最小端到端工作台流程。

### 13.3 Phase 18 内部兼容性

- 18E/F 与 18A–D 公开资源、指纹和依赖矩阵。
- 商业超市、住宅和批准版地铁入口分别通过三种提供器的最小软件夹具。
- 建筑指纹在仅改变工况时保持不变。
- Phase 18A–D 的既有软件验收矩阵保持通过。

### 13.4 整体项目兼容性

- 旧爆炸工况、城市场景、旧前端、项目导入导出和求解授权回归。
- 依赖边界扫描无跨域导入。
- `compileall`、前端语法/测试、全项目相关测试和 `git diff --check`。
- 独立最终审查区分 Critical、Important、Minor，并在 Critical/Important 清零后才标记软件验收完成。

## 14. 完成定义

Phase 18E 完成：独立项目在没有任何旧工况配置时可保存、预览、验证和生成；三种提供器及三类工况通过模块、空间、预算、依赖和隔离验收。

Phase 18F 完成：用户可以从旧前端入口进入视觉一致但状态独立的新工作台，完成审核预设、项目覆盖、分层预览、检查、预算、确认和生成闭环。

Phase 18 总体软件验收完成：Phase 18A–F 的公开接口、指纹、依赖和兼容性矩阵全部通过，且整体项目旧行为无回归。

工程验证仍单独要求真实 LS-PrePost 导入、LS-DYNA 求解、材料标定、网格敏感性、试验/文献对照和工程人员审核；在这些证据完成前不得设置 `solver_ready=true` 或 `engineering_validated=true`。
