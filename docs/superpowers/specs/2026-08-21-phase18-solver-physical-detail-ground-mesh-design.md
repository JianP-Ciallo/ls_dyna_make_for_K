# Phase 18 求解建筑构造与地面网格修正设计

状态：用户已批准，实施中

日期：2026-08-21

## 1. 目标

修正 solver-complete ALE/FSI 路径中的四项物理与可用性问题，同时保持 Phase 18D 默认资产及其指纹不变：

1. 商业超市实体外墙具备横、竖双向钢筋；
2. 商业超市承重柱采用 Solid 混凝土柱，并包含纵向钢筋和闭合箍筋；
3. 地铁入口 RC/不透明承重围护采用 Solid，薄玻璃保留 Shell，细长框架和钢筋保留 Beam；
4. 三类建筑的地面网格尺寸成为独立、可持久化、可审计的用户参数。

## 2. 隔离边界

本次只增强 `refined_building.solver_blast` 和 `solver_complete_ale_fsi` Provider。Phase 18D 资产仍是不可变语义来源，普通精细建筑编译结果、默认指纹和旧工作台路径不因本次修改改变。

不允许通过生成后手改 K 文件实现修复。所有几何、配筋、材料、连接、参数和清单证据必须由同一源代码重新生成。

## 3. 商业超市物理模型

### 3.1 实体承重柱

- 在既有商业柱轴线及入口门架位置生成 `commercial_rc_column` Solid 柱；
- 柱截面、位置、柱高和网格来自已归一化商业几何及既有柱轴；
- 原 `steel_column` 和 `steel_opening_jamb` 不再作为 solver-complete 商业竖向承重构件输出，避免与 RC 柱正体积或承重语义重复；
- 钢屋架、钢梁和薄钢屋面仍按长细比/厚度使用 Beam 或 Shell。

### 3.2 柱配筋

- 每根 Solid 柱内布置四根或更多纵向 `commercial_column_longitudinal_rebar` Beam；
- 沿柱高按受控间距布置闭合 `commercial_column_stirrup` Beam；
- 钢筋坐标必须位于混凝土保护层内，不穿出柱体；
- 通过显式 embedded-rebar 接口把纵筋和箍筋连接到 Solid 柱，接口记录钢筋数、宿主单元和几何闭包证据。

### 3.3 外墙双向配筋

- `opaque_facade` 继续是有限厚度 Solid；
- 在四面实体外墙中布置竖向 `commercial_wall_vertical_rebar` 和横向 `commercial_wall_horizontal_rebar` Beam；
- 两向钢筋均避开门窗洞口，保持保护层和最小边距；
- 两向钢筋通过 embedded-rebar 接口连接实体墙；任一方向为空均为硬错误。

## 4. 地铁入口围护

- 地下 RC 箱体墙、底板和顶板保持 Solid；
- 入口亭的不透明基座、承重围护和不透明屋盖以有限厚度 Solid 输出；
- `pavilion_glazing` 保留带真实厚度的 Shell，因为玻璃厚度远小于面内尺度；
- `pavilion_frame` 和钢筋保留 Beam；
- 原薄 `pavilion_metal_roof` Shell 在 solver-complete 视图中被排除，并由 `pavilion_opaque_solid_roof` Solid 替代；
- 新屋盖必须与亭体框架/基座存在可审计连接，且不得封堵声明的通行开口。

## 5. 可调地面网格

新增 `ground_cell_size_m`：

- 合法范围：`0.10 <= ground_cell_size_m <= 0.50` m；
- 默认值：`0.25` m；
- 与 `air_cell_size_m` 独立；
- 进入 Provider UI schema、默认输入、项目持久化、规范化输入、场景和最终包指纹；
- 地面生成严格使用该值，不再执行 `max(0.5, air_cell_size_m)` 的隐式粗化；
- 生成任何坐标/节点/单元前，继续使用节点数 2,000,000、单元数 1,000,000 的硬预算；过细网格造成超限时明确拒绝，不自动放大网格。

配置升级为 `phase18.solver_blast.config@2`。旧 `@1` 配置只允许其原有精确字段，并确定性迁移为 `@2`，补入默认 `ground_cell_size_m=0.25`；未知字段继续拒绝。

## 6. 审计与失败边界

新增硬门禁：

- 商业 RC 柱必须同时存在 Solid 宿主、纵筋和闭合箍筋；
- 商业实体外墙必须同时存在横向和竖向钢筋；
- 配筋不得穿出宿主实体或进入门洞；
- solver-complete 商业模型不得同时输出旧钢柱和新 RC 柱的重复竖向承重语义；
- 地铁不透明屋盖必须为 Solid，玻璃必须为 Shell；
- 所有新增 Beam 必须具有截面、方向和 embedded 接口；
- 地面实际网格步长不得超过用户值，并满足硬预算；
- 配置迁移、UI schema、保存/重载及指纹必须一致。

## 7. 验证

实施按 RED→GREEN 进行：

1. 配置和 Provider schema/迁移测试；
2. 地面网格尺寸、预算与指纹测试；
3. 商业柱/柱配筋/墙双向配筋及洞口避让测试；
4. 地铁 Solid 不透明屋盖、Shell 玻璃及连接测试；
5. 三类 solver-complete 生成、关键字闭包和 Phase 18D–F 兼容测试；
6. 重新生成三套 K 包并执行 LS-PrePost 导入、R12 mcheck 和 1 ms 验证。

只有新的三套快照分别取得上述终态证据，才能取代此前快照的 solver-complete PASS；工程状态仍保持 `engineering_validated=false` 和 `requires_project_review=true`。
