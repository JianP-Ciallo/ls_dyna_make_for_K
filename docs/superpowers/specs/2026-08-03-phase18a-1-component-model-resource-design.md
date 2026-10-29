# Phase 18A-1 构件级独立模型资源与兼容调用设计

> **命名迁移（2026-08-05）：** 本文中的 `2k_rc_*` 为旧兼容别名。规范资源族现为 `two_storey_rc_frame_blast_reference`，梁、柱、楼板、基础规范 ID 分别为 `two_storey_rc_frame_beam_reference`、`two_storey_rc_frame_column_reference`、`two_storey_rc_frame_slab_reference`、`two_storey_rc_frame_foundation_reference`。原文件名 `2.k` 只保留为来源追溯。

日期：2026-08-03
状态：技术方案，待实施
来源基线：`2.k`，SHA-256 `C1C02A9E832852854B47CD3720BC9348CF48989484D25E1A54036836D0697A22`

## 1. 目标

Phase 18A-1 将已经完成 Part 级索引的 `2.k` 结构网格进一步拆成四个可以独立读取、独立校验、独立实例化的组合构件模型：梁、柱、楼板和基础。每个构件必须同时保留混凝土 Solid、对应钢筋 Beam、Beam N3 方向节点、Section、材料引用、Set 和嵌入耦合关系，不能退化成只有几何或只有 Part 清单的资源。

四个资源通过统一的模型资源合同、ID 重映射和场景适配器供多个既有场景按需调用。兼容层采用增量接入，不改变既有场景未选择新资源时的输入、默认值和输出。

## 2. 已确认的拆分方案

评估过三种边界：

1. 每个 Part 独立一个文件：粒度最细，但混凝土、纵筋、箍筋和耦合被拆散，调用者必须重新拼接依赖，错误风险最高。
2. 组合构件级闭合资源：梁、柱、楼板、基础各一个资源，每个资源内部闭合 Solid＋Beam＋材料/截面＋耦合。该方案已由用户确认。
3. 仅保留完整建筑资源：关系最完整，但不能满足构件复用和多场景调用要求。

Phase 18A-1 固定采用方案 2。空气域和 TNT 继续作为共享场景资源，不混入梁、柱、楼板或基础构件包。

## 3. 四个独立构件包

| 资源 ID | 组成 Part | Solid 数 | Beam 数 | 必需 Section | 必需材料 | 耦合闭包 |
| --- | --- | ---: | ---: | --- | --- | --- |
| `2k_rc_beam_reference` | 201、202、203 | 6,600 | 11,540 | 4、3、1 | MID 5、14、8 | SSID 1 → MSID 201 |
| `2k_rc_column_reference` | 301、302、303 | 6,000 | 12,546 | 4、2、1 | MID 5、12、8 | SSID 2 → MSID 301 |
| `2k_rc_slab_reference` | 401、402 | 91,245 | 25,725 | 4、2 | MID 5、12 | Part 402 → Part 401 |
| `2k_rc_base_reference` | 501、502 | 22,445 | 12,150 | 4、6 | MID 5、8 | SSID 6 → MSID 501 |

四个构件的并集必须精确覆盖 126,290 个结构 Solid 和 61,961 个钢筋 Beam，不包含 PID 1001 或 PID 1002。

## 4. 资源目录和文件合同

```text
resources/model_library/phase18/components/
├── 2k_rc_beam_reference/
│   ├── manifest.json
│   ├── component.k.gz
│   └── audit.json
├── 2k_rc_column_reference/
├── 2k_rc_slab_reference/
└── 2k_rc_base_reference/
```

每个 `component.k.gz` 必须是可独立解析的 LS-DYNA keyword 片段，包含 `*KEYWORD` 和 `*END`，并且只包含该构件闭包所需的：

- `*NODE`：全部 Solid 拓扑节点、Beam N1/N2 节点、Beam N3 方向节点和相关 Set 节点。
- `*ELEMENT_SOLID` 与 `*ELEMENT_BEAM`。
- `*PART`、在用 `*SECTION_SOLID/*SECTION_BEAM`。
- 所需 MAT、Curve 1、`*MAT_ADD_EROSION` 等材料依赖。
- 该构件的 Node/Part/Segment Set 和 `*CONSTRAINED_LAGRANGE_IN_SOLID`。
- 来源追溯注释；不包含控制卡、输出卡、空气域、爆源和其他构件数据。

`manifest.json` 至少包含：

```text
schema_version
id / version / component_kind
source_sha256 / source_part_ids / source_element_ids_hash
payload path / sha256 / byte_size
coordinate_frame / source_transform / bounding_box
node_count / solid_count / beam_count
part_section_material_map
material_resource_ids
set_and_coupling_dependencies
interfaces
capabilities
compatibility
validation_status / requires_project_review
```

`audit.json` 保存排除项、共享节点、接口节点、源 ID 映射、未纳入卡片及所有警告。审计文件不作为可实例化模型资源。

## 5. 坐标、共享节点和构件接口

独立拆分不能破坏原结构中构件交界处的共享关系，因此同时保存两套身份：

- `source_node_id/source_element_id`：用于审计和按源位置重组。
- `local_node_id/local_element_id`：用于构件独立实例化和场景内重映射。

每个构件以本地锚点建立局部坐标系，并在清单中保存恢复源位置所需的刚体变换。接口按角色登记，例如梁端面、柱顶/柱底、板边界、基础顶面及支承面。

同一源节点出现在两个构件包时允许在各自包内保留副本，但必须写入 `shared_source_node_ids`。重新装配源结构时按源节点 ID 合并；一般场景放置时不得按坐标自动合并，只能使用显式接口、容差和连接策略。

## 6. 多场景兼容架构

### 6.1 统一资源接口

新增独立于具体场景的 `ComponentModelResource` 合同和以下公共能力：

- `list_model_resources()`：列出资源与能力。
- `get_model_resource(resource_id)`：读取可序列化清单。
- `validate_model_resource(resource_id)`：验证载荷哈希和依赖闭包。
- `instantiate_model_resource(resource_id, transform, id_namespace, material_binding)`：生成可装配的构件片段。

实例化返回统一 `ComponentFragment`，包含节点、Solid、Beam、Part、Section、材料引用、Set、耦合、接口和来源映射。调用者不能直接拼接压缩文件或假设源 ID 在目标场景中仍然可用。

### 6.2 ID 和材料兼容

- 节点、单元、Part、Section、Material、Set、Curve 和约束 ID 全部通过场景的 `AssemblyContext` 分配。
- 所有正向和反向引用必须在同一次重映射中更新。
- 默认 `material_binding=source_reference`，绑定已经入库的 2.k 材料资源。
- 可选 `material_binding=host_override`，但替换材料必须满足构件要求的材料角色和关键字能力，且写入来源记录。
- 不允许通过删掉 Beam、耦合或材料依赖的方式“兼容”能力不足的调用者。

### 6.3 既有场景适配层

在现有程序化组件生成器之外新增资源型适配器，不替换旧实现：

```text
旧场景输入
  -> 现有 schema 与默认值
  -> 可选 model_resource_id
  -> ComponentModelResourceAdapter
  -> ID/坐标/材料/集合重映射
  -> 既有场景装配与检查流程
```

场景通过能力协商判断是否支持 `solid`、`beam`、`embedded_coupling`、`rigid_transform`、`id_remap` 和 `material_binding`。能力不足时生成前明确拒绝并返回缺失能力，不能静默降级为纯实体或纯预览模型。

首轮兼容验收至少覆盖三类既有调用链：通用组件装配、简化爆炸目标装配和 ALE 爆炸目标装配。以后新增场景只能调用公共适配器，不复制一套构件解析逻辑。

### 6.4 向后兼容保证

- 不提供 `model_resource_id` 时，既有模板、输入 JSON、默认参数和输出保持不变。
- 新字段全部为可选增量字段；现有项目文件仍可读取。
- 旧场景输出建立快照基线，接入适配器前后必须逐字节或按规范化语义一致。
- 新资源实例的结果对象 ID、资源版本和网格指纹独立记录，参数变化后旧结果自动失效。
- 资源版本升级遵循 schema 兼容规则，不允许同一稳定 ID 静默更换载荷内容。

## 7. 拆分与实例化流程

```text
验证 2.k SHA-256
  -> 按四组 PID 流式选择单元
  -> 收集 Solid/Beam/N3/Set 节点闭包
  -> 收集 Part/Section/MAT/Curve/Set/Coupling 闭包
  -> 生成局部 ID 与源 ID 映射
  -> 写 component.k.gz、manifest.json、audit.json
  -> 独立解析验证
  -> 四构件源位置重组验证
  -> 既有场景适配验证
  -> 写入模型库索引
```

源文件在拆分前和复制过程中均重新计算 SHA-256；任一阶段哈希不一致必须停止并删除未完成载荷。输出采用临时文件加原子替换，避免中断后留下可被索引的半成品资源。

## 8. 验证门槛

### 8.1 单构件闭包

- 每个载荷可独立解压和解析。
- 0 个重复节点 ID、重复单元 ID和缺失节点引用。
- Beam N3 节点完整，方向向量非零，不参与错误的拓扑合并。
- 所有 Part 都能解析到 Section 和材料；所有耦合引用都存在。
- 实际计数、载荷 SHA-256 与清单完全一致。

### 8.2 四构件并集

- Element ID 并集与源结构 PID 201–502 完全一致，无遗漏、无交叉重复。
- 并集为 126,290 个 Solid 和 61,961 个 Beam。
- 按 `source_node_id` 和源变换重组后，节点坐标、单元连通性、Part 角色和四组嵌入关系与源模型一致。

### 8.3 兼容回归

- 至少三个既有场景通过同一公共适配器成功实例化四类资源。
- 平移、旋转和 ID 重映射后无冲突或悬空引用。
- 不选择新资源时，既有场景模型和检查结果保持基线一致。
- 不支持 Beam 或嵌入耦合的调用链必须返回稳定错误码和缺失能力清单。
- Web/工具层读取的资源清单保持 JSON 可序列化，不暴露本机绝对源路径。

## 9. 状态与边界

- 四个构件均继承 `source_reference` 和 `requires_project_review=true`。
- 构件包可复用不等于材料已标定、连接已工程验证或模型已经过真实求解。
- Phase 18A-1 不进行构件参数化拉伸、截面自动改型或钢筋自动重排；这些属于后续实体建筑内核。
- LS-PrePost 导入和 LS-DYNA 求解仍由用户单独触发并保存证据。

## 10. 实施顺序

1. 定义 `ComponentModelResource`、`ComponentFragment`、能力和版本合同。
2. 以失败测试锁定四组 PID、单元数、依赖闭包和缺失引用规则。
3. 扩展流式拆分器，生成四个原子构件包。
4. 实现坐标变换、全类型 ID 重映射、材料绑定和接口元数据。
5. 接入公共场景适配器，保持旧输入默认行为不变。
6. 完成单构件、并集重组和至少三个既有场景的兼容回归。
7. 输出入库报告，提交用户审核后才把状态提升为可选参考资源。
