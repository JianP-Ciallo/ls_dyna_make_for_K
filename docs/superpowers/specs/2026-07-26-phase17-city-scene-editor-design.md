# Phase 17 城市三维场景编辑器设计

**状态：** 已批准设计，尚未实施

**日期：** 2026-07-26

## 1. 目标

Phase 17 将现有 Web 三维建模预览升级为组件级场景编辑器。最终目标是在 `city_street_blast_scene` 中选择并移动真实爆源及被授权编辑的建筑物，再由后端重新生成 ALE/TNT、结构、FSI、测点和语义结果映射。

最终受控验收场景为城市街道爆炸：

- 用户能够选择真实 TNT/JWL 爆源并在有效 ALE 空气域内进行 X/Y/Z 平移；
- 用户能够选择带 `grounded` 移动策略的建筑物，在地面内进行 X/Y 平移和绕 Z 轴旋转；
- 建筑物始终贴合其支承地面，不能悬空或倾斜；
- 未来空中物体通过独立 `airborne` 策略扩展，不放宽建筑物约束；
- 视窗、数值输入和场景草案保持一致；
- 移动后重新计算 TNT 初始体积分数、起爆点、ALE/结构耦合、压力测点和语义对象映射；
- 只有空间和物理门禁通过后才能生成新的 LS-DYNA 项目；
- 旧项目、旧 K 文件和旧求解结果不被修改。

`rebar_drop_on_helmet` 保留为通用组件变换的早期回归案例，但不再作为 Phase 17 最终完成验收。

Phase 17 建设的是受控有限元场景编辑器，不是通用 CAD 或完整 Blender 替代品。

## 2. 已冻结范围

### 2.1 首版支持

- 完整语义组件的单选；
- 世界坐标系下的 X/Y/Z 平移；
- 世界坐标系下的 X/Y/Z 旋转；
- 三轴、平面和平移中心操纵；
- 三轴旋转环；
- 数值输入与操纵器双向同步；
- 撤销、重做、复位和取消当前拖动；
- 自由装配模式；
- 基于统一装配组件的受控场景；
- `city_street_blast_scene` 城市布局编辑；
- 真实 TNT/JWL 爆源位置编辑；
- 授权建筑物的贴地移动和绕 Z 轴旋转；
- `rebar_drop_on_helmet` 组件变换回归；
- 无落盘草案预览；
- 生成新的项目或版本；
- 求解结果只读展示。

### 2.2 首版不支持

- 几何缩放；
- 节点、单元、面或边编辑；
- 材料、截面或厚度的视窗内编辑；
- 同时选择和变换多个组件；
- 改变城市 ALE 空气域外形或网格拓扑策略；
- 让 `grounded` 建筑物悬空、下沉或绕 X/Y 倾斜；
- 在 Phase 17 首版直接实现 `airborne` 物体编辑；
- 父子层级、骨骼、动画关键帧；
- 任意导入 CAD 的直接编辑；
- 对已经生成的 `model.k` 原地修改；
- 对求解结果网格进行变换并回写。

## 3. 现状与设计判断

现有 Web 视窗由 `lsprepost_mcp/web/static/app.js` 内的 HTML Canvas 二维投影代码实现。它已经支持：

- 相机旋转、缩放和平移；
- 根据投影面点击选择 Part；
- 显示或隐藏 Part；
- 从 `/api/project/preview-mesh` 读取已生成项目的网格。

现有组件装配协议已经支持：

```json
{
  "transform": {
    "translate_m": [0.0, 0.0, 0.0],
    "rotate_deg": [0.0, 0.0, 0.0]
  }
}
```

但当前视窗仍有三个关键缺口：

1. 选择对象是有限元 Part，不一定等于用户理解的完整组件。
2. 预览来源是已经生成的 `model.k`，不能承担无落盘草案编辑。
3. 自研 Canvas 不具备可靠的三维射线拾取、轴向拖动和旋转操纵器。

因此 Phase 17 不在现有 Canvas 上继续堆叠三维编辑逻辑，而是使用 Three.js 建立独立的建模预览层，同时保留当前结果查看行为。

## 4. 总体架构

```text
城市街道爆炸 / 受控场景 / 自由装配
        |
        v
EditableSceneDraft
        |
        +---- POST /api/editor/preview
        |             |
        |             v
        |      内存编译与静态检查
        |             |
        |             v
        |      PreviewMesh v2
        |             |
        v             v
Three.js 组件视窗 <-> 组件列表和数值输入
        |
        v
POST /api/assembly/validate
        |
        +---- 失败：阻止生成并定位组件/动作
        |
        v
POST /api/assembly/generate
        |
        v
新的不可变项目版本
        |
        +---- LS-PrePost
        +---- LS-DYNA
        +---- 只读结果视图
```

### 4.1 双视窗策略

- `建模预览` 使用 Three.js/WebGL。
- `求解结果` 保持只读，不获得变换操纵器。
- 现有 Canvas 结果绘制在迁移完成前保留为独立 legacy canvas。
- 两个 canvas 不共享 WebGL/2D context，避免上下文冲突。
- 模式切换时必须释放不再使用的事件监听、几何和材质资源。

### 4.2 本地依赖

- Three.js 固定为 `three@0.180.0`。
- 浏览器运行时只加载分发包内的本地模块，不访问 CDN。
- `OrbitControls` 和 `TransformControls` 与同一 Three.js 版本一起分发。
- Playwright 仅作为开发和验收依赖，不进入运行时 Python 包。
- 第三方许可证和版本哈希进入分发清单。

## 5. 编辑草案模型

前端新增单一可信状态 `EditableSceneDraft`：

```javascript
{
  revision: 12,
  source: {
    kind: "controlled_scene",
    scene: "rebar_drop_on_helmet",
    project_name: null
  },
  components: [],
  actions: [],
  contacts: [],
  loads: [],
  analysis_control: null,
  database: null,
  selected_component_id: "rebar",
  dirty: true,
  validation: null
}
```

约束：

- `revision` 每次已提交编辑递增。
- 预览响应必须回显请求的 `revision`。
- 前端丢弃旧 revision 的迟到响应。
- Three.js 对象不是模型状态，不允许将场景图直接序列化为工程输入。
- 所有工程变换最终写入 `components[*].transform`。
- 生成请求只从 `EditableSceneDraft` 构造，不从渲染网格反向推断。

## 6. 变换语义

### 6.1 单位和顺序

- 平移单位固定为 m。
- 旋转单位固定为 degree。
- 旋转顺序与现有编译器一致：先 X，后 Y，最后 Z。
- 组件模板的 `orientation` 先应用，再应用 `rotate_deg`。
- `center_m` 定位在旋转后应用。
- `translate_m` 最后应用。

该顺序不得由 Three.js 默认矩阵顺序隐式替代。预览接口返回后端计算的组件 pivot 和变换矩阵，视窗必须用测试证明与 K 文件节点坐标一致。

### 6.2 操纵器模式

- 默认模式为平移。
- 平移支持 X、Y、Z 单轴和 XY、YZ、XZ 平面。
- 旋转支持 X、Y、Z 世界轴。
- 首版不开放 local/world 切换，统一使用世界坐标，避免用户误判。
- 拖动期间显示临时变换；结束拖动后提交一次历史记录和一次后端预览。
- 数值输入失焦或确认后提交，不对每个键盘字符生成历史记录。

### 6.3 精度

- 模型状态保存未经格式化的有限浮点数。
- UI 平移默认显示 6 位小数，旋转默认显示 3 位小数。
- 禁止 NaN、Infinity 和字符串数字。
- 前端检查不能替代后端 `parse_model_spec()` 和装配校验。

### 6.4 对象移动策略

每个可编辑对象必须由后端显式声明 `mobility_profile`，前端不得根据对象名称自行推断：

| 策略 | 首版状态 | 允许自由度 | 典型对象 |
|---|---|---|---|
| `fixed` | 实施 | 无 | 道路、地基、ALE 外边界、未授权建筑 |
| `grounded` | 实施 | X/Y 平移、绕 Z 轴旋转 | 被授权编辑的建筑物 |
| `blast_source` | 实施 | X/Y/Z 平移 | 城市 TNT/JWL 爆源 |
| `free_component` | 实施 | X/Y/Z 平移、绕 X/Y/Z 旋转 | 钢筋、钢盔等普通装配组件 |
| `airborne` | 仅冻结协议 | X/Y/Z 平移、绕 X/Y/Z 旋转 | 后续无人机、飞行物或悬挂物 |

`grounded` 对象的 Z 坐标由支承面求解，不接受用户直接输入。对象移动后必须重新投影到支承地面，并证明底面节点在地面容差内。支承地面存在坡度时，首版只允许绕世界 Z 轴旋转，不自动倾斜建筑物。

`blast_source` 表示真实 ALE 炸药体，不是显示标记。编辑其位置必须同步改变炸药几何、ALE 多材料初始体积分数和 `*INITIAL_DETONATION` 位置。

城市爆源位置确认后，后端必须以新的炸药几何中心重新生成分级 ALE
坐标轴。ALE 外边界、材料定义和总体分级策略保持不变；近场细网格窗口在
X/Y/Z 三个方向随爆源移动，外围过渡区重新离散。这里的“随动”发生在
K 文件重新生成阶段，不表示求解过程中 Eulerian 网格跟随炸药运动。

`blast_source.position_m` 固定表示炸药体的几何中心。城市圆柱 TNT 的后端输入仍使用 `base_center_m`，由后端按当前长度计算：

```text
base_center_m = position_m - [0, 0, 0.5 * length_m]
```

前端不得把圆柱底面中心误当成操纵器 pivot。

`airborne` 协议在首版进入数据契约和测试夹具，但 UI 保持禁用，直到单独阶段完成碰撞、初始条件和支承关系验收。

## 7. PreviewMesh v2

新增 `lsprepost_mcp_preview_mesh_v2`，同时保留 v1 项目预览兼容性。

最小响应：

```json
{
  "format": "lsprepost_mcp_preview_mesh_v2",
  "revision": 12,
  "parts": [],
  "components": [
    {
      "component_id": "rebar",
      "part_ids": [1],
      "pivot_world_m": [0.0, 0.0, 0.62],
      "translate_m": [0.0, 0.0, 0.62],
      "rotate_deg": [0.0, 0.0, 0.0],
      "mobility_profile": "free_component",
      "allowed_dofs": ["tx", "ty", "tz", "rx", "ry", "rz"],
      "editable": true
    }
  ],
  "editable_sources": [
    {
      "source_id": "city_tnt",
      "kind": "ale_explosive_volume",
      "position_kind": "geometric_center",
      "position_m": [0.0, 0.0, 0.51],
      "mobility_profile": "blast_source",
      "allowed_dofs": ["tx", "ty", "tz"]
    }
  ],
  "bounds": {},
  "validation": {},
  "limitations": []
}
```

要求：

- 每个可编辑 Part 必须映射到恰好一个 `component_id`。
- 一个组件可以拥有多个 Part，选择任一 Part 必须选择整个组件。
- 没有组件映射的辅助 Part 只读。
- 城市语义对象通过稳定 `object_id` 映射到一个或多个 Part。
- 爆源通过 `source_id` 映射到真实炸药体参数，不能只映射到绘图标记。
- 服务端预览通过内存中的 keyword 和 metadata 构建，不写入项目目录。
- 预览接口不得启动 LS-PrePost、LS-Run 或 LS-DYNA。
- 响应大小继续受网格 preflight 门禁限制。

## 8. 选择和交互

### 8.1 选择

- 点击可见网格，通过 Three.js raycaster 得到 Part。
- Part 经 `part_id -> component_id` 映射为组件。
- 组件列表选择与视窗选择双向同步。
- 选中组件的所有 Part 使用轮廓或高对比材质高亮。
- 选中爆源时高亮其真实体积边界，并显示仅含 X/Y/Z 的平移操纵器。
- `grounded` 对象隐藏 Z 平移和 X/Y 旋转手柄。
- `fixed` 对象可以查看，但不能附加操纵器。
- 点击空白取消选择。
- 隐藏组件时取消其选择并移除操纵器。

### 8.2 相机与操纵器冲突

- 未命中操纵器时，左键旋转相机。
- 命中操纵器时，禁用 OrbitControls，结束拖动后恢复。
- 右键平移和滚轮缩放保留。
- 相机按钮继续支持适配、等轴、顶、前和全屏。
- 操纵器屏幕尺寸保持稳定，不因模型尺度改变而不可操作。

### 8.3 响应式布局

- 桌面端显示视窗操纵器和完整数值面板。
- 窄屏端不允许控件覆盖 canvas；组件属性移动到可展开区域。
- 触摸设备允许选择和数值编辑；操纵器触摸拖动必须通过 Playwright 触摸验收后才能标记支持。
- 不支持的输入方式必须明确降级，不能显示可操作但无响应的控件。

## 9. 工程安全门禁

### 9.1 通用门禁

每次正式生成前必须重新执行：

- 组件 ID 唯一性；
- 有限三维平移和旋转；
- 组件网格规模；
- 组件 AABB/OBB 有效性；
- 非法初始穿透；
- 接触动作引用对象存在；
- 固定区域和固定面仍可解析到节点；
- 初速度和载荷引用对象存在；
- 变换后命名面、命名区域和 Part 映射有效；
- 所有静态 keyword 检查。

警告只能用于不会导致错误物理关系的问题。初始穿透、丢失接触对象、固定区域为空和受控碰撞路径失效必须阻止生成。

### 9.2 城市场景通用空间门禁

`city_street_blast_scene` 中每次编辑后必须满足：

- 爆源和所有可编辑建筑物的包围体完全位于 ALE 域水平范围内；
- 爆源真实炸药体完全位于有效空气材料单元中；
- 爆源与建筑、道路实体、地基及其他 Lagrange 结构不存在体积相交；
- 爆源到 ALE 外边界至少保留受控最小单元层数；
- 建筑底面投影到指定支承地面，支承节点集合非空；
- 建筑不与其他建筑、地铁入口、车辆或固定结构发生非法初始穿透；
- 移动建筑后重新生成 FSI 从属面/段集合，且集合非空；
- 城市语义 `object_id` 保持稳定，Part ID 变化不得改变对象身份；
- 与旧几何绑定的城市影响结果立即标记过期；
- 空气压力测点和路径根据新爆源与目标位置重新派生，不能沿用旧坐标；
- 网格规模和输出体积继续通过 preflight。

### 9.3 城市爆源专用门禁

城市爆源移动后必须重新计算并验证：

- TNT 圆柱的 `base_center_m`、顶面和几何中心；
- TNT 质量、密度、直径和长度一致性；
- 受 TNT 占据的 ALE 单元及每个单元体积分数；
- 所有体积分数有限，处于 `[0, 1]`，且单元内材料体积分数和满足求解器要求；
- TNT 实际离散体积和目标体积误差在受控容差内；
- `*INITIAL_DETONATION` 位于 TNT 体内；
- 至少有受控数量的 TNT 单元，不能因拖动到粗网格或边界处退化为空；
- TNT 必须完全位于爆源随动近场窗口内，并保留至少一层近场单元余量；
- `diameter_cells` 和 `length_cells` 必须由爆源当前位置的实际轴间距计算，
  不能只用配置的 `near_size_m` 推算；
- 生成后的网格元数据必须记录爆源中心、近场窗口边界、局部 X/Y/Z
  单元尺寸、网格指纹和重划分原因；
- 任一爆源位置变化必须改变 `editor_state_fingerprint` 和网格指纹，并使
  旧求解结果、旧 LS-PrePost 导入证据和旧网格相关验收失效；
- 预览显示位置、metadata 位置、初始化卡位置和 K 文件离散位置一致。

只改变 `blast_sources[*].position_m` 绘图字段而不改变 ALE 初始化必须视为阻断错误 `blast_marker_only_move`。

### 9.4 贴地建筑专用门禁

`grounded` 建筑编辑后必须：

- 只接受 X/Y 平移和绕 Z 轴旋转；
- 由后端根据支承面计算 Z，不信任前端提交的 Z；
- 底面节点与支承面距离不超过 `max(1.0e-9 m, 1.0e-4 * local_mesh_size_m)`；
- 固定区域、接触面和 FSI 面随完整组件重新生成；
- 语义对象关联的 Part、Set、测点和结果输出映射全部更新；
- 超出允许布局区域或进入排除区域时阻止生成。

### 9.5 钢筋撞击钢盔回归门禁

`rebar_drop_on_helmet` 还必须满足：

- `rebar` 和 `helmet` 组件存在且映射唯一；
- 钢筋与钢盔初始状态不存在超过容差的体积穿透；
- 钢筋初速度为有限非零向量；
- 沿初速度方向构造的钢筋有限时间扫掠体与钢盔目标壳相交；
- 钢筋和钢盔仍被同一有效接触动作引用；
- 钢盔固定区域仍能解析到非空节点集合；
- 旋转后的钢筋网格 Jacobian/体积检查通过；
- 若钢筋移出碰撞路径，生成被阻止并返回 `impact_path_misses_target`。

视窗移动钢筋只改变几何变换。初速度是世界坐标向量，不随组件旋转静默改变。用户要改变撞击方向时必须显式编辑速度参数。

## 10. 撤销、重做与状态失效

- 历史记录保存结构化草案快照，不保存 Three.js 对象。
- 连续一次拖动只形成一条历史记录。
- 历史上限固定为 100 条。
- 新编辑发生后清空 redo 栈。
- 场景参数、组件变换、组件增删和物理动作变化都使旧预览验证失效。
- 任一编辑立即将旧求解结果标记为与当前草案不匹配。
- 离开页面前若草案未生成，浏览器显示标准未保存更改确认。

## 11. Phase 16A/16B 兼容契约

Phase 17 是 Phase 16 城市语义和结果链路的输入编辑层，不得建立第二套对象身份、结果单位、风险等级、研究仓库或代理模型协议。

### 11.1 Phase 16A 语义和结果兼容

- 复用已有 `city_semantic_schema_version` 和稳定 `object_id`。
- 建筑移动只更新位置、姿态、`bounds_m`、Part/Set 映射和空间关系，不改变对象身份。
- 同一对象在新旧布局中保持相同 `object_id`；Part ID 必须由稳定编译顺序确定，不能因拖动顺序随机变化。
- 继续使用 `phase16a.city_impact.v1` 指标名称、单位、阈值来源和风险状态。
- Phase 17 不修改 Phase 16A 的压力、冲量、位移、应力和损伤含义。
- 每次草案变脏，Web 必须立即清空旧 `part_risk` 着色和对象指标，显示“布局已修改，尚未求解”。
- 新项目不得复制旧 `city_impact_metrics.json`、评估报告、风险等级、`d3plot`、`matsum` 或求解记录。
- Phase 16A 现有 `model_sha256` 门禁继续作为结果绑定的最终依据。

Phase 17 可向 Phase 16A 评估响应增加可选 `layout_fingerprint`，但不得破坏历史 `phase16a.city_impact.v1` 项目的读取。历史项目缺少布局指纹时仍可查看自身结果，但不能参与 Phase 17 跨布局工作流。

### 11.2 规范化布局契约

新增 `phase17.city_layout.v1`，规范化内容至少包括：

```json
{
  "schema_version": "phase17.city_layout.v1",
  "semantic_schema_version": "existing-phase16-value",
  "objects": [
    {
      "object_id": "commercial_supermarket",
      "mobility_profile": "grounded",
      "translate_m": [0.0, 0.0, 0.0],
      "rotate_z_deg": 0.0,
      "bounds_m": {"min": [], "max": []},
      "support_object_id": "ground_foundation"
    }
  ]
}
```

`layout_fingerprint` 是该规范化结构的 SHA-256。规范化规则固定为：

- 对象按 `object_id` 排序；
- 数组轴顺序固定为 X/Y/Z；
- 只接受有限数值；
- `-0.0` 归一化为 `0.0`；
- 不包含项目名、时间戳、Part ID、网格尺寸、材料或求解结果；
- 包含城市对象空间变换、边界和支承关系；
- 不包含爆源中心；爆源位置是 Phase 16B 已有的受控 case 参数；
- 同一物理布局在重新生成后得到相同指纹。

Part ID 继续进入 Phase 16B 既有语义指纹以发现生成差异，但不进入 `layout_fingerprint`，避免把纯编号变化误判为布局变化。

另建 `phase17.city_editor_state.v1`：

```json
{
  "schema_version": "phase17.city_editor_state.v1",
  "layout_fingerprint": "64-character-sha256",
  "blast_center_m": [0.0, 0.0, 0.5]
}
```

其 SHA-256 记为 `editor_state_fingerprint`，用于绑定某一次具体编辑状态。建筑移动会同时改变布局指纹和编辑状态指纹；只移动爆源时布局指纹保持不变，但编辑状态指纹和模型哈希改变。

### 11.3 Phase 16B 工况矩阵兼容

- Phase 17 爆源位置直接映射已有 `blast_center_x_m`、`blast_center_y_m` 和 `blast_center_z_m`，不得增加同义字段。
- Phase 17 生成的项目同时记录 `layout_fingerprint` 和 `editor_state_fingerprint`。
- Phase 16B 新矩阵记录 `reference_layout_fingerprint`。
- 建筑移动后的项目必须创建新的 reference project 和新的 study/matrix。
- 只移动爆源时仍属于同一布局，可以作为同布局矩阵中的受控 case；若该爆心组合不在既有矩阵中，必须生成新矩阵版本，不能临时改写已有 matrix。
- 新布局不得注册到旧矩阵，即使语义对象 ID 相同。
- 旧布局矩阵授权不得继承到新布局。
- 爆源移动不得继承另一 case 的授权；每个精确 case ID 仍需单独进入批次授权。
- 任何矩阵、结果索引或授权记录缺少/不匹配布局指纹时，Phase 17 操作必须 fail closed。

Phase 16B 现有由 `reference_model_sha256` 提供的隔离继续保留；`layout_fingerprint` 是面向布局语义的第二道门禁，不替代模型哈希。

### 11.4 结果比较和不确定性分析

- 同布局、同语义、同材料和同生成契约的结果继续按 Phase 16B 现有规则比较。
- 不同布局默认返回 `layout_fingerprint_mismatch`。
- 不得通过 `allow_mixed_mesh` 绕过布局差异。
- 跨布局比较只能进入明确标记的 Phase 16B.6 独立布局验证流程。
- 跨布局报告必须同时列出两个布局指纹和变化对象，不得只显示数值差异。
- 未经独立高保真求解验证，不得把布局差异归因于单一建筑移动。

### 11.5 代理模型适用域

- Phase 16B 代理模型产物绑定训练时的 `layout_fingerprint`。
- 预测请求必须携带当前布局指纹。
- 布局指纹不匹配时返回 `layout_out_of_surrogate_domain`，不得进行最近邻计算。
- 当前代理模型的特征继续使用 Phase 16B 已有受控参数；Phase 17 首版不把建筑坐标自动加入训练特征。
- 新布局只有建立独立矩阵、登记合格样本并重新训练后，才能获得自己的代理模型。
- Phase 16B.6 留出布局不得混入训练数据。

### 11.6 局部精化和防护排序

- 精化计划绑定 `layout_fingerprint`、矩阵 ID 和参考模型哈希。
- 建筑移动后，旧精化计划因布局指纹变化立即标记过期。
- 只移动爆源时，旧精化计划因 case 参数/模型哈希变化过期，但布局指纹保持一致。
- 新精化计划从当前爆源中心、当前语义对象 `bounds_m` 和当前传播走廊重新计算。
- 防护方案排序默认要求布局指纹一致。
- 允许语义变体的显式比较也必须保留 `layout_variant=true` 和独立验证声明，不能解除材料、生成器或结果质量门禁。

### 11.7 实施时序

- Three.js 渲染、选择、操纵器和草案历史可以独立实施。
- 爆源编辑复用已存在的 Phase 16B 爆心参数，可以先接入。
- 建筑编辑接入前必须冻结 `phase17.city_layout.v1` 和 Phase 16A 对象边界输出。
- Phase 17 城市验收应向 Phase 16B.6 提供一个未参与训练的新布局，但两个阶段分别记录完成状态。

## 12. 项目不可变与 provenance

- 草案预览不写入 `workspace/projects/`。
- 生成默认使用 `if_exists="error"`。
- 从已有项目进入编辑时，操作名称为“创建可编辑副本”。
- 生成的项目必须使用新项目名；不允许通过视窗原地覆盖旧项目。
- `model.json` 记录：
  - `editor_phase: 17`
  - `source_project_name`
- `source_model_sha256`
- `source_layout_fingerprint`
- `layout_fingerprint`
- `editor_state_fingerprint`
- `draft_revision`
  - 每个组件的最终 `translate_m` 和 `rotate_deg`
- 求解记录继续绑定生成后的不可变 `model.k` 和 `model.json` 哈希。

## 13. 错误处理

预览接口采用结构化错误：

```json
{
  "ok": false,
  "error": {
    "code": "impact_path_misses_target",
    "message": "钢筋当前轨迹不会与钢盔相交。",
    "component_ids": ["rebar", "helmet"],
    "field": "components.rebar.transform.translate_m"
  },
  "revision": 12
}
```

要求：

- 错误必须关联组件、动作或字段。
- 旧请求失败不能覆盖新 revision 的成功状态。
- WebGL 初始化失败时回退为只读预览和数值编辑，不允许伪装为三维编辑可用。
- 浏览器丢失 WebGL context 时释放操纵器并允许恢复。

## 14. 验收标准

Phase 17 只有同时满足以下条件才能标记完成：

1. Three.js 和控制器完全本地分发，无 CDN 请求。
2. 自由装配和城市街道爆炸都可以无落盘预览。
3. 点击任一 Part 能选择其完整语义对象，选择爆源能绑定真实 TNT 体。
4. 平移和旋转操纵器与数值输入双向一致。
5. 预览坐标与最终生成 K 文件节点坐标在容差内一致。
6. 结果视图不可编辑。
7. 旧项目和旧求解结果不会被修改。
8. 城市真实爆源可以在有效 ALE 空气域内 X/Y/Z 移动，并重新生成 TNT 体积分数和起爆点。
9. 至少一栋授权建筑可以贴地 X/Y 移动和绕 Z 轴旋转，禁止悬空和倾斜。
10. 移动后的建筑具有非空且正确重建的 FSI 集合、固定区域和语义结果映射。
11. 爆源或建筑越界、相交、失去支承或只移动绘图标记时阻止生成。
12. 钢筋撞击钢盔继续通过组件变换回归。
13. 撤销、重做、复位和迟到响应处理通过自动化测试。
14. 桌面和移动视口不存在控件遮挡或文字溢出。
15. Playwright 截图和 canvas 像素检查证明视窗非空、模型正确取景。
16. Python 全量测试、前端单元测试、Playwright 测试、打包和本机路径扫描全部通过。
17. Phase 16A 对象 ID、指标单位和风险契约保持兼容。
18. 新布局不能注册到旧 Phase 16B 矩阵，也不能继承旧批次授权。
19. 布局变化后旧风险、精化计划和代理预测全部失效。
20. 代理模型对不匹配布局返回 `layout_out_of_surrogate_domain`。
21. Phase 16B.6 使用的独立布局不进入代理模型训练样本。
22. 只移动爆源时 `layout_fingerprint` 保持不变，但 case 参数、`editor_state_fingerprint` 和模型哈希改变。
23. 爆源移动不能继承另一 case 的求解授权。

## 15. 阶段边界

Phase 17 完成代表三维装配输入闭环可靠，不代表：

- 任意 CAD 编辑能力完成；
- 所有受控场景都适合自由移动；
- 变换后的模型必然具有工程合理性；
- 静态检查可以替代 LS-DYNA 求解；
- 未经材料标定的结果可以作为最终工程预测。

涉及外部求解器的真实验收仍需要单独授权。Phase 17 的默认自动化测试只生成和检查模型，不自动启动 LS-Run 或 LS-DYNA。
