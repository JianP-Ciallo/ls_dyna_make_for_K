# Phase 18D 精细建筑资产实施与软件验收报告

日期：2026-08-10

基线：`3af728a7e57acdb428f3f8df402bea6132bc5b93`

验收修订：`8b917d3a290e1dc0a8c252cdc48c880258dc662e`

提交范围：`3af728a7e57acdb428f3f8df402bea6132bc5b93..8b917d3a290e1dc0a8c252cdc48c880258dc662e`，20 commits、28 files、`+12422/-153`

结论：Phase 18D 的参数化资产、确定性编译和 Phase 18A–C 兼容性已完成软件级验收；没有完成工程验证，所有产物仍为 `solver_ready=false`、`requires_project_review=true`。

## 1. 已实现的软件能力

Phase 18D 在 `lsprepost_mcp/refined_building/` 内增加独立的精细建筑资源、模板、编译、表面再分类和包级清单层。三个资源 ID 为：

- `commercial_supermarket_detailed_building`；
- `residential_community_detailed_building`；
- `subway_entrance_detailed_building`。

资源发现与旧 fixed-K 模型库隔离；资源只声明参数化生成器 `refined_building.asset_compiler@1`，不携带固定 payload。每个 manifest 自描述 schema/version/identity/capability/unit/review/lineage 和资产专属材料角色闭包；全局未解析材料词汇固定为 `facade`、`glazing`、`doors`、`nonstructural`、`metal_roof`、`signage`、`escalator_equipment`、`escalator_balustrade`、`escalator_handrail` 九类，未知或重复角色 fail-closed。

公共编译接口支持稳定的结构体系、`structural_core` / `blast_response` / `research_detailed` 保真度、`coarse` / `standard` / `fine` 网格档位、位置/方位、生成选项和材料覆盖。编译前对 Solid、Beam、Shell、Node 和 Total 五个族执行 allocation-free 预估、默认上限和不可提升硬上限门禁，不会先物化大坐标/单元数组，也不会静默改变用户选择的网格档位。硬上限为 Solid 5,000,000、Beam 1,000,000、Shell 1,000,000、Node 8,000,000、Total 6,000,000；包的 mesh manifest 发布每族 `estimated_count`、`estimation_kind`、`limit` 和实际计数并校核 exact/upper-bound 关系。

包级清单汇总 child artifact、Node/Solid/Beam/Shell/连接计数、体积与可解析质量、材料解析状态、空间与洞口拓扑、网格与质量状态、精细表面目录、未建模范围、谱系和确定性指纹。18D 的表面探针只产生独立的精细表面目录，不改写 18C artifact 的原始表面目录或指纹。

RC 与混合体系支持 `full_reinforced` 和 `concrete_only`；关闭钢筋时保留混凝土 Solid，同时删除钢筋 Beam 和 `embedded_rebar` 连接。可选钢筋/钢构件目标段长、面板离散、RC 箱体分部厚度和混合结构配筋模式均为显式参数。材料覆盖必须引用现有资源并通过类别、单位和实际使用角色校验。

预算具有明确的指纹语义：用户显式提供的预算值属于请求语义，会进入包级指纹；若预算变化但仍允许相同网格，artifact/mesh 指纹保持不变而 package 指纹改变。省略的 Beam/Shell/Node/Total 默认硬上限是安全门禁和 manifest preflight 证据，不伪装成用户显式输入，并从 package fingerprint 的 mesh core 中排除；既有规范化 `max_solid_elements=5000000` 默认保持兼容。

## 2. 最终审查后的五个 follow-up 修复

独立最终审查覆盖完整 final range，结论为 `Critical 0 / Important 0 / Minor 0 / Ready=yes`。审查期间形成五个 follow-up commits：

1. `b3988d28b56cb3f2a8f86959900992cf9059835d`：fixed-K NODE/SOLID/BEAM ID 必须为正且各族唯一，Solid/Beam element ID 还必须跨族唯一，避免解析成功后出现歧义身份。
2. `2985cf30a7b9a4bac9049fc6ebdf0a1aa4bad444`：严格拒绝未知 schema、未知顶层字段和拼写错误；descriptor 发布并校验完整资产专属材料角色闭包，实际编译角色不得越界。
3. `2784c00c8bd995876306533dc8c8dff0a3651d95`：增加 Solid/Beam/Shell/Node/Total 预分配硬门禁、manifest preflight、不可由公共参数抬高的默认上限，以及住宅层数/地铁玻璃分格的早期下界拒绝；商业混合和 RC 入口增加真实 jamb/header 承重构件，并以 swept-volume 零碰撞检查保证入口净空和屋面传力路径。
4. `c617e5f53d6a92c9966893e63ecbf18f7c90dcf5`：原始资产 manifest 改为自描述材料角色合同，并补齐批准地铁资产的扶梯扶手角色。
5. `8b917d3a290e1dc0a8c252cdc48c880258dc662e`：把未解析材料角色限制到全局九类词汇，未知角色 fail-closed。

## 3. 三类资产的实现范围

### 3.1 商业超市

默认采用 `steel_concrete_hybrid`：钢梁柱与屋面、RC 基础/楼板及可选钢筋分别形成 Beam、Shell、Solid 和独立连接。销售厅、仓储和后勤空间、正门及内部通行洞口、围护和隔墙进入规范化拓扑；入口与房间空腔不被 Solid 误填。混合体系和备选 `rc_frame` 都会在入口两侧及上方生成 jamb/header，保持净空 swept volume 零碰撞并建立到屋面/楼板的承重路径；备选体系会重建结构，而不是只替换材料。

### 3.2 住宅多塔社区

默认采用 `rc_frame_shear_wall`，按 `tower_count` 生成互不连接、ID 独立的塔楼 artifact；塔间空地不生成虚假梁、板或墙。每层包含住宅空间、核心筒、门洞、剪力墙及可选钢筋；阳台深度改变真实阳台板与防护构件网格。`rc_frame` 和 `concrete_only` 分别形成可区分的结构与连接结果。

### 3.3 批准版中国通用地铁入口 A

实现以 `docs/superpowers/specs/2026-08-09-phase18d-subway-entrance-approved-baseline.md` 和批准图为绑定基线。批准图 SHA-256 实测为 `9D372CBF379A141ED0483A58B8BC0E086DFB37F27E97F114B536638F4067CD15`。

拓扑固定为一组楼梯 `A` 与两组独立扶梯 `B/C` 横向并排、纵向同向，从共同上平台下降到共同下平台 `8`；独立、笔直、空腔式通道 `9` 沿同一轴线继续到接口面 `10`。资产不生成转弯、侧通道、额外楼梯/扶梯或站厅。地面长玻璃罩棚覆盖完整下降段，具有浅连续曲面金属屋面、入口挑檐、规则玻璃分格、结构框架和 RC 基座；通用标识为可替换非承重角色。地下 RC 地板/墙/屋面、上下平台、固定楼梯和通道具有显式结构几何与真实空腔；两组扶梯是彼此独立的设备装配，不是 RC 实体。

## 4. 两轮只读确定性验收

两轮命令均只向控制台输出 JSON，没有写项目、K 文件或其他验收产物。第一轮耗时 43.293 s、exit 0；第二轮耗时 43.312 s、exit 0，`cross_run_equal=true`。两轮的 child/总计数、所有 artifact/package 指纹、normalized input SHA、validation findings 和材料状态逐项相同。

| 资源 | child | 结构体系 | 总 Node / Solid / Beam / Shell | package fingerprint | findings | 材料状态 |
| --- | ---: | --- | --- | --- | --- | --- |
| `commercial_supermarket_detailed_building` | 1 | `steel_concrete_hybrid` | 41,970 / 25,920 / 3,071 / 2,766 | `7386c2049924c8fcda23a970a97fa4e119969c4b5b6157ba81f77c50decff014` | `[]` | resolved 9、unresolved 2；`syntax_unit_reviewed` 4、`demo` 5、`unresolved` 2 |
| `residential_community_detailed_building` | 2 | `rc_frame_shear_wall` | 103,234 / 67,054 / 6,144 / 4,796 | `6885fd0aaba82d351cce8a762f3480214e4e33555ac790cde8934a65f4db978f` | `[]` | resolved 30、unresolved 4；`syntax_unit_reviewed` 28、`demo` 2、`unresolved` 4 |
| `subway_entrance_detailed_building` | 1 | `rc_box` | 41,629 / 28,314 / 1,650 / 242 | `047d66bcb96caa5e75596518a512a21c05e8f025864b3bc9fa5629c52f610020` | `[]` | resolved 17、unresolved 10；`syntax_unit_reviewed` 14、`demo` 3、`unresolved` 10 |

逐 child 结果：

| child asset ID | Node | Solid | Beam | Shell | artifact fingerprint | normalized input SHA-256 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| `commercial_supermarket_detailed_building` | 41,970 | 25,920 | 3,071 | 2,766 | `603510590dd1de86468efafcb81f74c849d9a64d6ae250d805f7fdaa868c89ac` | `5df728e884114b5446e4e618435e94bee0d4c7675e6375fa3cc95e5ac19b3e3b` |
| `tower_001` | 51,060 | 33,048 | 3,072 | 2,398 | `e7511ffcd7f859602476d583fac2c5de5635ca1d2bee0f63ef9852675e571b95` | `1ac0b7dcb56df09c66ec588acd19cf01ce1b20a39e0a5e7d410ec3b460ed1bae` |
| `tower_002` | 52,174 | 34,006 | 3,072 | 2,398 | `4aa538c61d4a1c13cc63ef970798acf7f75ec7469d77baf1ec50bba9a0e475d9` | `1aa3e46792dfc09618d2fcfcd1c3a4a20807520f49fd2d50d5700449a5fbc6ef` |
| `subway_entrance_001` | 41,629 | 28,314 | 1,650 | 242 | `f2c61ce690341c567d3532484351e59b84714634cc6314d3089791645b3c3a79` | `d907711a5cd73c04f50a7d605914814522ded638390bc768ffef5d95821d5cde` |

以上四个 child 的 `validation_findings=[]`，三个包均为 `requires_project_review=true`。

商业变化仅来自审查后加入的入口 jamb/header 钢构件及其节点/Beam/材料绑定；住宅和地铁的总计数、child artifact 指纹、package 指纹及 normalized input SHA 与 pre-follow-up 基线完全相同。

## 5. 可复现的完整规范化请求输入

第一轮控制台 JSON 还输出了每个 child 的完整 `normalized_input`；上表给出其规范 JSON SHA-256。下列包级规范化输入完整列出重放所需的资源、几何、选择、位置、材料覆盖和全部生效生成参数。

### 5.1 商业超市

```json
{
  "resource_id": "commercial_supermarket_detailed_building",
  "legacy_geometry": {"length_m": 6.0, "width_m": 4.0, "height_m": 3.0, "wall_thickness_m": 0.2, "entrance_width_m": 2.0, "entrance_height_m": 2.0},
  "origin_m": [0.0, 0.0, 0.0],
  "rotation_deg": [0.0, 0.0, 0.0],
  "structural_system": "steel_concrete_hybrid",
  "fidelity_profile": "blast_response",
  "mesh_profile": "coarse",
  "generation_options": {"bar_diameter_m": 0.016, "cover_m": 0.04, "max_solid_elements": 5000000, "rebar_spacing_m": 0.3, "reinforcement_mode": "full_reinforced"},
  "material_overrides": {}
}
```

### 5.2 住宅多塔

```json
{
  "resource_id": "residential_community_detailed_building",
  "legacy_geometry": {"tower_count": 2, "tower_length_m": 3.6, "tower_width_m": 3.6, "tower_height_m": 3.0, "tower_spacing_m": 0.8, "wall_thickness_m": 0.2, "balcony_depth_m": 0.6},
  "origin_m": [0.0, 0.0, 0.0],
  "rotation_deg": [0.0, 0.0, 0.0],
  "structural_system": "rc_frame_shear_wall",
  "fidelity_profile": "blast_response",
  "mesh_profile": "coarse",
  "generation_options": {"bar_diameter_m": 0.016, "cover_m": 0.04, "max_solid_elements": 5000000, "rebar_spacing_m": 0.5, "reinforcement_mode": "full_reinforced", "storey_count": 1},
  "material_overrides": {}
}
```

### 5.3 地铁入口

```json
{
  "resource_id": "subway_entrance_detailed_building",
  "legacy_geometry": {"length_m": 4.0, "width_m": 3.0, "platform_height_m": 0.3, "enclosure_height_m": 2.4, "wall_thickness_m": 0.2, "roof_thickness_m": 0.2},
  "origin_m": [0.0, 0.0, 0.0],
  "rotation_deg": [0.0, 0.0, 0.0],
  "structural_system": "rc_box",
  "fidelity_profile": "blast_response",
  "mesh_profile": "coarse",
  "generation_options": {
    "additional_escalator_count": 0,
    "additional_stair_count": 0,
    "bar_diameter_m": 0.016,
    "connection_simplification_level": "aggregate",
    "cover_m": 0.04,
    "escalator_angle_deg": 30.96375653207352,
    "escalator_equipment_envelope_m": 0.078,
    "escalator_rise_m": 2.4,
    "escalator_width_m": 0.5720000000000001,
    "fixed_stair_distribution_spacing_m": 0.125,
    "fixed_stair_local_densification_factor": 2.0,
    "fixed_stair_longitudinal_spacing_m": 0.2946666666666667,
    "fixed_stair_slope_deg": 30.96375653207352,
    "glazing_bay_count": 6,
    "lane_gap_m": 0.078,
    "lower_landing_clear_width_m": 2.6,
    "lower_landing_length_m": 0.3,
    "max_solid_elements": 5000000,
    "passage_clear_height_m": 2.4,
    "passage_clear_width_m": 2.6,
    "passage_floor_thickness_m": 0.3,
    "passage_length_m": 1.0,
    "passage_roof_thickness_m": 0.2,
    "passage_turn_deg": 0.0,
    "passage_wall_thickness_m": 0.2,
    "pavilion_clear_height_m": 2.4,
    "pavilion_frame_size_m": 0.1,
    "pavilion_glazing_thickness_m": 0.020000000000000004,
    "pavilion_length_m": 4.6,
    "pavilion_overhang_m": 0.4,
    "pavilion_roof_arc_rise_m": 0.24,
    "pavilion_roof_thickness_m": 0.05,
    "pavilion_width_m": 3.0,
    "rebar_spacing_m": 0.5,
    "reinforcement_mode": "full_reinforced",
    "stair_rise_m": 0.15,
    "stair_tread_m": 0.25,
    "stair_width_m": 0.8840000000000001,
    "upper_landing_clear_width_m": 2.6,
    "upper_landing_length_m": 0.3
  },
  "material_overrides": {}
}
```

## 6. 最终软件验证证据

### 6.1 final Head fresh Phase 18D 测试

所有六个文件均在最终修订 `8b917d3a290e1dc0a8c252cdc48c880258dc662e` 上逐文件 fresh 完整运行并 exit 0：

| 命令 | 结果 | pytest 时长 | 外层实测 |
| --- | --- | ---: | ---: |
| `python -m pytest -q tests/test_phase18d_asset_resources.py` | 15 passed，40 subtests | 39.83 s | 40.242 s |
| `python -m pytest -q tests/test_phase18d_commercial_supermarket.py` | 27 passed，13 subtests | 484.91 s | 485.331 s |
| `python -m pytest -q tests/test_phase18d_mesh_extensions.py` | 26 passed，69 subtests | 1.52 s | 1.925 s |
| `python -m pytest -q tests/test_phase18d_residential_subway.py` | 45 passed，59 subtests | 713.78 s | 714.193 s |
| `python -m pytest -q tests/test_phase18d_phase18abc_compatibility.py` | 23 passed，165 subtests | 17.36 s | 17.760 s |
| `python -m pytest -q tests/test_phase18d_generation_budgets.py` | 12 passed，20 subtests | 39.65 s | 40.061 s |

合计：148 tests、366 subtests、0 失败；pytest 报告时长合计 1,297.05 s，外层实测合计 1,299.512 s。

### 6.2 Phase 18A–C 兼容证据

Task 5 在中间修订 `e0ca45107f06a3ca500e956baf1ac6bc9e11a007` 上运行了 `docs/reviews/phase18/PHASE18A_C_ADVERSARIAL_AUDIT_REPAIR_REPORT.zh-CN.md` 定义的精确 Phase 18A–C 归档矩阵并加入当时的 compatibility 文件，结果为 `287 passed, 278256 subtests passed in 131.78s`，exit 0；该结果是 follow-up 前的历史兼容基线，不冒充 final-Head fresh 结果。

五个 follow-up commits 修改了资源/兼容校验、资产 descriptor、预算和入口结构，因此最终修订重新 fresh 运行 `tests/test_phase18d_phase18abc_compatibility.py`，得到 `23 passed, 165 subtests passed in 17.36s`；再与依赖边界合跑得到 `Ran 24 tests in 17.532s / OK`。该 final-Head 回归覆盖旧 building catalog、五组组件别名 SHA、真实完整 fixed-K 参考包、正且唯一的 NODE/SOLID/BEAM ID、跨族 element ID 唯一性和五个 Phase 18C 字面指纹。

兼容修复在 `lsprepost_mcp/model_library.py` 中使 NODE/BEAM/SOLID 的逗号、空格和定宽记录分派严格、确定且 fail-closed；拒绝空必填定宽字段、额外尾部、定宽/空格歧义、非有限坐标及非法/冲突/显式 null 网格计数。旧 building catalog 快照、五组组件别名 SHA、真实完整参考包计数及五个 Phase 18C 字面指纹保持不变。

### 6.3 静态、发现与依赖边界

| 命令/检查 | 结果 | 时长 | exit |
| --- | --- | ---: | ---: |
| `python -m unittest tests.test_phase18c_dependency_boundaries tests.test_phase18d_phase18abc_compatibility -v` | Ran 24 tests；OK | 17.532 s | 0 |
| scoped Python 发现脚本：导入 5 个 18D 模块，发现/验证 3 个参数化资源，核对 5 个 fixed-K ID 唯一与隔离、无 payload、自描述 manifest、生成器、审核标志及 global-9 角色词汇 | 12 项检查全 true | 0.169 s | 0 |
| `python -m compileall -q lsprepost_mcp` | 无输出错误 | 0.089 s | 0 |
| `git diff --check` | 无 whitespace error；仅现有无关脏文件的换行转换 warning | 0.083 s | 0 |
| `Get-FileHash -Algorithm SHA256 docs/assets/phase18d/subway_entrance_cn_generic_A_approved_2026-08-09.png` | 与批准 hash 一致 | < 1 s | 0 |

依赖边界测试确认 `refined_building` 未导入城市/爆炸工况生成器。三个 Phase 18D 资源和五个核心模块可独立发现；Phase 18A/B fixed-K 发现仍为 5 个唯一 ID。

## 7. 材料、截面与工程角色边界

混凝土和钢筋候选目前解析到 Phase 18B 的 `syntax_unit_reviewed` 资源；结构钢解析到 `mild_steel_mat24_demo`，仍是 demo 状态。超市围护/隔墙、住宅围护/隔墙，以及地铁玻璃、金属屋面、标识、建筑饰面、扶梯踏步带/栏板/扶手等角色保持 `unresolved`。这些角色没有被静默替换为混凝土或结构钢。

当前 `section_role`、连接与耦合角色是软件语义标识，不等于具体项目已审核的截面尺寸、梁/壳截面卡、钢筋直径组合、连接刚度、设备质量/动力属性或施工连接。材料覆盖机制只证明资源身份、类别和单位闭包，不证明本构参数适用于目标项目。

## 8. 为什么这不是 engineering validation

本轮没有真实 LS-PrePost 导入，也没有真实 LS-DYNA 初始化或求解证据；没有材料标定、试验相关、壳偏置/厚度方向复核、接触定义审核、单元质量指标、网格收敛、质量/设备动力等效、钢筋锚固与节点核心区细化，也没有适用规范和持证工程角色审查。软件中的 `validation_findings=[]` 只表示当前合同与几何软件门禁未发现问题，不表示工程适用性、可求解性或结果精度。

因此三类资产及其所有 child artifact 必须继续保持 `solver_ready=false`、`requires_project_review=true`；不得称为 `engineering_validated`，不得作为已通过 LS-PrePost/LS-DYNA 的工程模型。

## 9. 阶段状态与交付边界

Phase 18D 软件验收已完成，但工程验证和 LS-PrePost 门禁未完成，所以不得据此进入 Phase 18E 工程装配。Phase 18E 和 Phase 18F 均未启动。旧 `commercial_supermarket`、`residential_community`、`subway_entrance` 场景/模板 ID、默认几何和旧生成器行为未被 Phase 18D 改写；本阶段也没有修改任何既有爆炸工况生成器。

当前共享工作树的 `docs/ROADMAP.zh-CN.md` 相对 final Head 已含约 `+558/-186` 的用户/前序未提交改动，而 HEAD 版本根本没有当前 Phase 18 章节。Task 6 只在现有工作文件的 Phase 18D 状态段更新最终状态与报告链接，无法把 ROADMAP 安全地做 scoped staging：暂存该路径会把整份既有大范围改写一起带入。因此本报告和 ROADMAP 均未执行 `git add` 或 commit，交由主代理处理最终文档提交策略。
