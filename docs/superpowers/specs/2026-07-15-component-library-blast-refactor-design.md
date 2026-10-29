# 组件库与简化爆炸建模重构路线

## 1. 文档目的

本文确定 `lsprepost-mcp` 在现有四个受控场景之后的优化路线。目标不是扩展为任意有限元前处理器，而是在保持个人可维护、输入受控和结果可追溯的前提下，完成以下能力：

- 将现有 `assembly_scene` 升级为统一的多组件装配内核。
- 让基础模型能够被不同场景重复调用，而不是为每个场景重新实现几何生成。
- 增加明确的 `assemble_components` 公共工具。
- 建立类型化材料库，首先支持弹性材料和 MAT_024 弹塑性材料。
- 建立独立的接触、约束、初速度和简化爆炸动作库。
- 保留现有四个受控场景，作为经过验证的装配预设。
- 生成可由 LS-DYNA 实际求解的简化空爆冲击钢板模型。

首个爆炸场景采用 `*LOAD_BLAST_ENHANCED` 路线。本阶段不建立炸药实体、空气 ALE 域、JWL 状态方程或流固耦合。

## 2. 已确认的产品边界

### 2.1 建模与求解分离

Web 和工具层保持两个明确动作：

1. `assemble_components`：装配、校验并生成项目文件和 K 文件。
2. `run_lsdyna`：在用户确认模型摘要后调用本地 LS-DYNA 求解器。

生成预览、打开 LS-PrePost 和运行 LS-DYNA 互不隐式触发。这样可以避免查看模型时意外启动耗时求解，也便于在求解前检查材料、爆距、网格和输出设置。

### 2.2 “任意组合”的含义

“任意组合”表示：

- 可以从已注册且受控的组件库中选择两个或更多组件。
- 组件数量不固定为两个。
- 每个组件可以独立设置尺寸、网格、材料、位置和方向。
- 场景可以独立添加接触、约束、初速度和爆炸动作。

“任意组合”不表示：

- 接受任意原始 LS-DYNA keyword 文本。
- 自动理解和修复任意 CAD 几何。
- 自动保证任意组合都具有正确的工程物理意义。
- 允许 AI 绕过组件、材料和动作白名单。

初版建议设置每个场景最多 32 个组件，并设置节点、单元数量预检上限。该上限是防止误操作的资源保护，不是装配器的结构限制。

## 3. 目标架构

```text
受控场景预设 / Web 自由装配 / AI IDE
                    |
                    v
           assemble_components
                    |
                    v
     ComponentInstance + PhysicsAction
                    |
                    v
     组件注册表 / 材料注册表 / 动作注册表
                    |
                    v
          统一 ModelSpec 与校验器
                    |
                    v
       LS-DYNA keyword 编译与项目写入
                    |
          +---------+---------+
          |                   |
          v                   v
   LS-PrePost 检查        run_lsdyna
                              |
                              v
                    d3plot / blstfor / 日志
```

现有 `generate_model` 保留为兼容入口。`assemble_components` 不创建第二套生成逻辑，而是构造统一 `ModelSpec`，然后复用同一解析、校验、写入和 provenance 流程。

## 4. 组件库重构

### 4.1 统一组件定义

每个基础模型只保留一个参数化生成器，并实现统一接口：

```text
ComponentDefinition
├── name
├── version
├── geometry_schema
├── mesh_schema
├── element_family
├── material_compatibility
├── build_mesh()
├── named_surfaces
├── named_edges
└── bounds
```

组件实例只保存本次装配参数：

```json
{
  "id": "target_plate",
  "template": "shell_plate",
  "geometry": {
    "length_m": 1.0,
    "width_m": 1.0,
    "thickness_m": 0.01
  },
  "mesh": {"size_m": 0.025},
  "material": {"name": "mild_steel_mat24_demo"},
  "transform": {
    "center_m": [0.0, 0.0, 0.0],
    "rotate_deg": [0.0, 0.0, 0.0]
  }
}
```

节点、单元、Part、Section、Material 和集合 ID 由装配上下文统一分配，组件生成器不持有全局 ID。

### 4.2 第一批基础组件

第一批统一和新增以下组件：

| 组件 | 单元族 | 来源 | 主要用途 |
|---|---|---|---|
| `shell_plate` | shell | 统一现有实现 | 方形钢板、靶板、地板 |
| `circular_plate` | shell | 新增 | 圆形靶板、盖板 |
| `solid_block` | solid | 纳入装配库 | 混凝土块、支撑块、实体靶 |
| `solid_cylinder` | solid | 统一现有实现 | 实心杆、撞击体 |
| `shell_tube` | shell | 由圆柱壳能力统一 | 钢管、空心撞击体 |
| `beam_bar` | beam 或兼容实体细杆 | 纳入装配库 | 简化钢筋、细长杆件 |
| `ellipsoid_shell` | shell | 统一现有实现 | 头盔、椭球罩壳 |
| `shell_box` | shell | 纳入装配库 | 箱体、容器 |
| `sphere_shell` | shell | 新增 | 球壳、压力容器 |

辅助对象：

- `rigid_plane`：表示地面或刚性墙面，由专用 keyword 生成器处理。
- `blast_source_marker`：仅用于 Web 三维视窗标识爆心，不生成炸药实体单元。

圆锥、复杂曲面、通用 CAD 导入和 ALE 空气域不进入第一批。

### 4.3 具名区域

所有组件必须输出语义化区域，动作不得依赖场景代码手工推算节点或单元编号。

示例：

- 钢板：`top_surface`、`bottom_surface`、`four_edges`、`x_min_edge`、`x_max_edge`。
- 圆柱：`outer_surface`、`top_end`、`bottom_end`。
- 钢管：`outer_surface`、`inner_surface`、`top_ring`、`bottom_ring`。
- 头盔：`outer_surface`、`inner_surface`、`rim`。
- 箱体：`top`、`bottom`、`sides`。

组件旋转和平移后，具名区域的拓扑引用必须保持稳定。

## 5. `assemble_components` 工具

### 5.1 输入结构

工具输入由以下部分组成：

```text
project_name
components[]
contacts[]
constraints[]
initial_conditions[]
actions[]
analysis_control
database
if_exists
dry_run
```

其中：

- `components` 至少两个，初版最多 32 个。
- `contacts` 只允许已注册的受控接触类型。
- `constraints` 引用组件具名边界或具名集合。
- `initial_conditions` 包含初速度等初始状态。
- `actions` 包含压力、重力、节点力和爆炸等外部作用。

### 5.2 配套查询能力

为 AI IDE 和 Web 提供同一份注册表元数据：

- `list_component_templates`
- `get_component_template`
- `list_materials`
- `get_material`
- `list_physics_actions`

Web 不维护第二份组件参数表，所有输入控件由后端注册表 schema 驱动。

### 5.3 兼容策略

- `generate_model(model_type="assembly_scene")` 继续可用。
- 四个现有受控场景仍保留原场景 ID 和前端入口。
- 受控场景内部改为调用组件注册表和统一装配服务。
- 旧项目保持只读兼容，不在读取时自动重写。

## 6. 类型化材料库

### 6.1 材料定义

材料条目从“通用弹性字段”升级为按材料族校验：

```text
MaterialDefinition
├── name / display_name / version
├── family
├── keyword
├── unit_system
├── parameters
├── curves
├── compatible_element_families
├── source / source_url / notes
├── validation_status
└── requires_project_review
```

`validation_status` 至少区分：

- `demo`：用于功能和求解闭环，不用于工程定量结论。
- `reviewed`：参数经过项目级人工复核。
- `user_confirmed`：用户提供并明确确认，但不等同于平台认证。

### 6.2 首批材料族

首批只开放：

1. `elastic` -> `*MAT_ELASTIC`
2. `piecewise_linear_plasticity` -> `*MAT_PIECEWISE_LINEAR_PLASTICITY` / MAT_024

首批材料条目：

- 保留现有弹性低碳钢、6061-T6 铝和通用橡胶。
- 新增 `mild_steel_mat24_demo`，供冲击和爆炸闭环使用。
- 可增加 `aluminum_6061_t6_mat24_demo`，但不作为首个爆炸验收依赖。

MAT_024 条目必须校验密度、弹性模量、泊松比、屈服应力、硬化参数或应力应变曲线；失效和应变率参数如果没有可信来源，保持关闭，不由 AI 自动编造。

### 6.3 后续材料路线

后续按场景需要增加，而不是一次开放全部材料卡：

- 金属应变率与失效模型。
- 混凝土损伤材料。
- 刚性材料。
- 完整 ALE 阶段才增加 `*MAT_NULL`、空气 EOS、`*MAT_HIGH_EXPLOSIVE_BURN` 和 `*EOS_JWL`。

## 7. 物理动作库

### 7.1 动作分类

物理定义从场景函数中拆出：

- 接触：点面接触、面面接触。
- 约束：固定边、固定面、固定节点集合。
- 初始条件：组件初速度。
- 常规载荷：压力、节点力、重力。
- 爆炸动作：`blast_enhanced`。

每类动作都必须有独立 schema、版本、校验器和 keyword writer。

### 7.2 简化爆炸动作

受控输入示例：

```json
{
  "id": "blast_1",
  "type": "blast_enhanced",
  "charge_type": "tnt",
  "equivalent_mass_kg": 0.1,
  "position_m": [0.0, 0.0, 0.5],
  "mode": "free_air_burst",
  "targets": ["target_plate.top_surface"]
}
```

编译器负责生成和关联：

- `*LOAD_BLAST_ENHANCED`
- `*LOAD_BLAST_SEGMENT` 或受控的 segment set 形式
- `*DATABASE_BINARY_BLSTFOR`
- 目标表面集合

用户不能通过该动作注入原始 keyword 文本。

### 7.3 爆炸动作校验

至少检查：

- TNT 等效质量为有限正数。
- 爆心坐标为有限数值。
- 目标组件和具名表面存在。
- 爆心不得落在目标表面上。
- 爆距为正，并对异常小或异常大的爆距给出警告。
- 目标表面法向和爆心相对位置合理。
- 终止时间晚于预计载荷到达时间并留有结构响应窗口。
- `d3plot` 和 `blstfor` 输出已启用。

## 8. Web App 调整

### 8.1 页面结构

保留“受控场景”作为默认模式，新增“自由装配”模式：

```text
左侧：组件库与组件参数
中央：交互式三维装配视窗
右侧：物理动作、校验摘要和求解状态
```

### 8.2 自由装配流程

1. 添加组件。
2. 设置尺寸、网格、材料、位置和方向。
3. 添加接触、约束、初速度或爆炸动作。
4. 查看装配确认摘要。
5. 生成并检查模型。
6. 可选打开 LS-PrePost。
7. 用户确认后送入 LS-DYNA。
8. 回读求解状态和结果文件摘要。

三维视窗中的爆心以标记显示，但不会误导为已经建立炸药实体。

### 8.3 防误操作

- 场景或参数变化后，旧预览和旧求解结果立即标记为过期。
- 求解按钮只对当前已生成且校验通过的项目开放。
- 求解前显示组件、材料、爆炸参数、终止时间和输出摘要。
- `demo` 材料显示明确提示。
- Web 不允许编辑后端生成的原始 keyword。

## 9. 首个爆炸验收案例

固定验收参数：

| 参数 | 值 |
|---|---|
| 场景 | TNT 等效自由空爆冲击四边固定钢板 |
| 钢板尺寸 | 1.0 m x 1.0 m x 0.01 m |
| 网格尺寸 | 0.025 m |
| 材料 | `mild_steel_mat24_demo` |
| TNT 等效质量 | 0.1 kg |
| 爆心 | 钢板中心正上方 0.5 m |
| 求解终止时间 | 初始值 0.02 s |
| 输出 | d3plot、blstfor、glstat、matsum、约束反力 |

验收条件：

- `assemble_components` 能生成通过静态校验的 K 文件。
- LS-PrePost 导入无 keyword reader error。
- LS-DYNA 正常结束，不出现 fatal termination。
- `d3plot` 存在且非空。
- `blstfor` 或对应爆炸压力数据库存在且非空。
- 钢板位移和应力不是全零。
- LS-PrePost 能显示钢板位移与应力云图。
- 验证记录保存求解器版本、输入文件 hash、返回码和结果文件清单。

该案例只证明建模和求解闭环成立，不证明材料参数和模型已经适合工程防爆定量分析。

## 10. 分阶段优化路线

当前阶段基线按项目现状记为 Phase 11.9。后续建议按以下顺序推进。

### Phase 12.0：重构安全网

目标：冻结现有行为，避免重构破坏四个受控场景。

交付物：

- 四个现有场景的 spec、K 文件关键字和可视网格快照测试。
- 当前工具注册表和 Web API 契约测试。
- 旧项目读取兼容测试。

完成条件：现有测试通过，四个受控场景输出没有非预期变化。

### Phase 12.1：统一组件内核

目标：消除独立模型和装配模型之间重复的几何生成代码。

交付物：

- `ComponentDefinition`、`ComponentInstance`、`AssemblyContext`。
- 统一 ID 分配器。
- 具名表面、具名边界和 bounds 接口。
- `shell_plate`、`solid_cylinder`、`ellipsoid_shell` 迁移。

完成条件：现有冲击场景改用统一组件后，节点、单元和 Part 关系正确。

### Phase 12.2：扩展基础组件库

目标：将现有基础模型全部纳入装配注册表，并添加少量高复用组件。

交付物：

- 纳入 `solid_block`、`shell_tube`、`beam_bar`、`shell_box`。
- 新增 `circular_plate`、`sphere_shell`。
- 增加 `rigid_plane` 和 Web 爆心标记。

完成条件：每种组件都能独立生成，也能与另一组件组成最小装配模型。

### Phase 12.3：公共装配工具

目标：提供明确且受控的多组件装配入口。

交付物：

- `assemble_components`。
- 组件和动作查询接口。
- 组件数量、资源预算和引用完整性校验。
- `dry_run` 无写入编译校验。

完成条件：AI IDE 能从注册表选择两个以上组件，生成同一项目中的多 Part K 文件。

### Phase 12.4：类型化材料库

目标：支持冲击和爆炸结构响应所需的弹塑性材料。

交付物：

- 按材料族分派的 schema 和 validator。
- MAT_024 keyword writer 与曲线支持。
- `mild_steel_mat24_demo`。
- 材料 provenance、版本和状态提示。

完成条件：MAT_024 单元测试模型可被 LS-DYNA 求解，Web 能区分 demo 与 reviewed 材料。

### Phase 12.5：物理动作库

目标：将接触、约束、初速度和载荷从场景函数中拆出。

交付物：

- 动作注册表和统一引用语法。
- 点面接触、面面接触。
- 固定边界、初速度、压力、节点力和重力动作。
- 四个受控场景迁移为动作组合预设。

完成条件：现有场景不再直接拼接动作 keyword。

### Phase 12.6：Web 自由装配

目标：让用户在前端选择组件并填写参数。

交付物：

- “受控场景 / 自由装配”模式切换。
- 添加、删除、复制和显示隐藏组件。
- 组件尺寸、材料和变换编辑器。
- 动作编辑器和生成前确认摘要。

完成条件：用户不编辑 JSON 即可完成两个以上组件的受控装配。

### Phase 12.7：简化爆炸动作

目标：加入可由 LS-DYNA 求解的 `blast_enhanced` 动作。

交付物：

- 爆炸动作 schema、校验器和 keyword writer。
- 爆心三维标记。
- 爆炸压力输出配置。
- “爆炸冲击钢板”受控预设。

完成条件：生成的 K 文件包含正确关联的爆炸载荷、目标表面和数据库输出卡。

### Phase 12.8：真实 LS-DYNA 爆炸闭环

目标：以固定验收案例完成真实求解和结果回读。

交付物：

- `assemble_components` 到 `run_lsdyna` 的端到端验收测试。
- d3hsp、messag、d3plot、blstfor 等结果检查。
- Web 求解状态和结果摘要。
- LS-PrePost 应力云图人工验证记录。

完成条件：第 9 节全部验收条件通过，Phase 12 才能标记完成。

## 11. Phase 12 之后

### Phase 13：扩大简化爆炸场景

- 爆炸冲击头盔。
- 爆炸冲击圆形板。
- 多个目标组件的受控爆炸场景。
- 参数扫描和结果对比，但每次求解仍需明确确认。
- 增加材料和网格敏感性提示。

### Phase 14：可选的完整 ALE 路线

只有在简化爆炸闭环稳定后再评估：

- ALE 空气域组件。
- 炸药几何和体积分数初始化。
- `*MAT_NULL` 与空气 EOS。
- `*MAT_HIGH_EXPLOSIVE_BURN` 与 `*EOS_JWL`。
- `*CONSTRAINED_LAGRANGE_IN_SOLID` 流固耦合。
- ALE 边界、泄漏控制、能量和网格收敛验证。

Phase 14 属于高难度能力，不作为当前方案 B 的完成条件。

## 12. 测试与发布门禁

每个子阶段至少通过：

- schema 和输入边界单元测试。
- 组件网格拓扑与具名区域测试。
- 材料卡与动作卡 golden/snapshot 测试。
- 四个现有受控场景回归测试。
- `python -m unittest discover -s tests`。
- `python -m compileall -q .\lsprepost_mcp`。
- 纯净压缩包路径和依赖扫描。

涉及 LS-PrePost 或 LS-DYNA 的阶段还必须保留可手动跳过的真实集成测试。没有真实求解记录时，只能标记“代码实现完成”，不能标记“求解闭环完成”。

## 13. 风险控制

- 不根据材料名称自动编造 MAT_024 曲线。
- 不将 `demo` 材料宣传为工程认证材料。
- 不允许动作层注入任意 keyword。
- 不以 LS-PrePost 能打开代替 LS-DYNA 可求解。
- 不以求解器正常退出代替工程结果正确。
- 不在首轮同时开发简化爆炸和完整 ALE。
- 不删除现有四个受控场景或破坏旧项目读取能力。

## 14. 最终完成定义

本轮优化只有同时满足以下条件才算完成：

1. 基础模型通过统一组件注册表复用。
2. `assemble_components` 能装配两个以上受控组件。
3. 每个组件能独立设置材料和空间变换。
4. 接触、约束、初速度和爆炸成为独立动作。
5. MAT_024 弹塑性材料可生成并通过求解 smoke。
6. Web 支持组件添加和受控动作配置。
7. 四个现有场景继续通过回归验证。
8. 固定爆炸钢板案例完成真实 LS-DYNA 求解。
9. LS-PrePost 能读取结果并显示非零位移和应力云图。

