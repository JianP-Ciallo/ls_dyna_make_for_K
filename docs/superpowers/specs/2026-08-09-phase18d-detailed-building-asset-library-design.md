# Phase 18D 多体系精细建筑资产库实施设计

日期：2026-08-09
状态：依据已批准 Phase 18D 路线形成的可执行设计
范围：18D-1 商业超市、18D-2 住宅建筑、18D-3 地铁入口、18D-4 统一登记与验收

## 1. 设计结论

Phase 18D 在 `refined_building` 内核之上增加独立的 `detailed_building` 资产层，不修改旧轻量建筑的模板 ID、默认几何、网格生成器或调用结果。精细资产从旧资产只读取稳定身份、外包络尺寸、位置和方位；内部空间、承重体系、构件、钢筋、连接和非承重构件均由 Phase 18D 语义模板重新生成。

首批完整覆盖：

- `commercial_supermarket_detailed_building`；
- `residential_community_detailed_building`；
- `subway_entrance_detailed_building`。

三类资产以参数化模型清单进入现有模型资源库，但保持 `solver_ready=false`、`requires_project_review=true`。双层钢筋混凝土参考模型继续保留在 Phase 18A/B 参考与构件资源区，不复制为另一份 Phase 18D 固定网格。

## 2. 资产包与公共接口

新增资产描述符和编译结果包：

```text
DetailedBuildingAssetDescriptor
├─ resource_id / version / legacy_asset_id
├─ default_geometry / geometry_fields
├─ default_structural_system / allowed_structural_systems
├─ fidelity_profiles / mesh_profiles
├─ material_binding_candidates
└─ requires_project_review

DetailedBuildingPackage
├─ descriptor identity
├─ normalized legacy geometry and origin
├─ selected structural/fidelity/mesh profiles
├─ one or more BuildingArtifact
├─ material_binding_manifest
├─ geometry_manifest / mesh_manifest / quality_manifest
├─ refined_surface_catalog（不改写 18C 原目录）
├─ unmodeled_scope
└─ package_fingerprint
```

公共接口固定为：

```python
list_detailed_building_assets()
get_detailed_building_asset(resource_id)
compile_detailed_building_asset(
    resource_id,
    *,
    legacy_geometry=None,
    origin_m=(0.0, 0.0, 0.0),
    rotation_deg=(0.0, 0.0, 0.0),
    structural_system=None,
    fidelity_profile="blast_response",
    mesh_profile="standard",
    generation_options=None,
    material_overrides=None,
)
```

`origin_m` 与 `rotation_deg` 进入包级 `placement` 和指纹；Phase 18D 保持本地轴对齐网格，不在资产编译器内重复实现放置旋转。后续放置编译器消费这一合同。

住宅社区是一个资产包而不是把塔间空地填成单一建筑：按旧资产的 `tower_count` 生成多个独立塔楼 `BuildingArtifact`，包级清单统一汇总。这样既保留旧资产族身份，又不会在塔间距内生成虚假梁、楼板或墙体。

## 3. 三类建筑语义

### 3.1 商业超市

- 默认体系：`steel_concrete_hybrid`，表示钢框架＋RC 基础/楼板；
- 允许体系：`steel_concrete_hybrid`、`rc_frame`；
- 默认空间：销售大厅、仓储区、后勤/设备区；
- 主要洞口：正立面入口以及后勤区之间的通行洞口；
- `blast_response`：增加分片外维护面和内部隔墙，入口区域不被面板封死；
- 混合体系的 RC 基础与楼板可生成钢筋并建立独立嵌入关系；钢梁柱按目标长度离散，而不是每跨只生成一个长 Beam。

### 3.2 住宅社区

- 默认体系：`rc_frame_shear_wall`；
- 允许体系：`rc_frame_shear_wall`、`rc_frame`；
- 每栋塔楼单独生成，默认层高由总高与合理整数层数解析，用户可覆盖层数；
- 每层包含起居空间、交通核心空间和显式门洞；
- 剪力墙范围显式声明并与房间空腔留出结构边界；
- `blast_response` 增加外维护面、核心筒分隔和主要开口面板；`research_detailed` 再增加候选阳台/局部隔墙面板，但不赋予未声明承载连接。

### 3.3 地铁入口

- 默认体系：`rc_box`；
- 允许体系：`rc_box`、`rc_frame_shear_wall`；
- 平台与围护总高来自旧资产尺寸，内部通行空腔不被实体填充；
- 正面为显式对外开口，后墙与侧墙保持实体＋墙筋；
- 默认 RC 模式为 `full_reinforced`，用户可选择 `concrete_only` 或自定义钢筋角色。

## 4. 保真度与网格

保真度固定为：

- `structural_core`：只生成承重结构和主要洞口；
- `blast_response`：默认，增加影响压力传播或飞散物的围护、隔墙和门窗面板；
- `research_detailed`：增加可审核的局部候选构件，并把未建模范围显式写入清单。

网格沿用已批准的 RC 参考档位，并为钢构件和非承重面板增加同名候选离散值：

| 档位 | 梁/柱/基础目标 | 板/墙目标 | 钢筋最大段长 | 钢构 Beam 最大段长 | 面板目标 | 最少厚度层数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `coarse` | 0.150 m | 0.0750 m | 0.150 m | 0.150 m | 0.150 m | 2 |
| `standard` | 0.100 m | 0.0500 m | 0.100 m | 0.100 m | 0.100 m | 3 |
| `fine` | 0.075 m | 0.0375 m | 0.075 m | 0.075 m | 0.075 m | 4 |

首版内核对每个结构体系采用满足最严格构件厚度约束的统一实体目标尺寸，保证板/墙厚度门禁不会被悄悄放宽。钢结构、组合连接和非承重面板的数值仍标记为项目审核候选，不声明为收敛结论。

为使默认住宅等大尺寸资产可生成，`mesh_axis_aligned_union` 的占用判定改为稀疏单元索引：保持相同全局坐标、角色优先级、`(z,y,x)` 输出顺序、节点分配顺序和既有指纹，仅避免对每个全局空格逐构件扫描。资产编译前还必须生成规模估算并执行可配置硬上限；超限时明确拒绝，不允许自动改粗网格。

## 5. 材料与结构资源绑定

资产包按实际 `PartBinding.material_role` 解析资源：

- 混凝土角色默认候选 `two_storey_rc_frame_mid5_concrete_kc`；
- 钢筋角色默认候选 `two_storey_rc_frame_mid8_rebar_d8_d18`；
- 钢结构角色默认候选 `mild_steel_mat24_demo`，必须保留 demo/项目复核标记；
- 围护、玻璃、门窗和其他未有匹配材料卡的角色保持 `unresolved`，不得静默套用混凝土。

每个绑定记录资源 ID、版本、单位制、有效审核状态和规范内容哈希。用户覆盖必须引用现有材料库资源，并经过材料类别和单位检查。Phase 18B 的截面、曲线和耦合资源只在语义匹配时引用；不得把双层参考模型的固定 Part/Section 绑定盲目套用到不同尺寸的钢结构或围护构件。

## 6. 模型库登记与兼容边界

每类精细资产在 `resources/model_library/detailed_buildings/phase18d/<resource_id>/asset.json` 登记为 `source_type=parametric_detailed_building`。该目录属于模型库，但由独立的详细建筑查询接口读取；既有固定 K 资源扫描、验证和导出接口保持不变，避免把八节点参数化资产误判为十节点 gzip K 包。参数化精细资产通过 Phase 18D 编译接口生成。

兼容规则：

1. 旧模板 `commercial_supermarket`、`residential_community`、`subway_entrance` 不增加隐式精细模式；
2. 旧默认几何函数和旧装配函数不由 Phase 18D 改写；
3. 精细资源使用独立 ID、版本、指纹和有限元 ID 空间；
4. 任何详细资产失败不得回退为旧轻量网格；
5. Phase 18D 包不得导入任何工况生成器；
6. Phase 18A/B 的固定构件包、材料/结构审核状态和兼容别名保持不变；
7. Phase 18C 的既有默认输入、结构后端默认参数和既有指纹不因新增可选参数而改变。

## 7. 校验与验收

每个资产包至少验证：

- 资源描述符、几何字段、允许体系和用户覆盖合法；
- 生成的 `BuildingArtifact` 全部软件校验通过；
- 房间/通道中心点没有误填充 Solid，主要洞口连通关系正确；
- 默认需要钢筋的 RC 区域同时存在 Solid、Rebar Beam 和嵌入关系；关闭钢筋后 Solid 仍存在且嵌入关系消失；
- 钢构件和面板最大边长不超过所选档位目标；
- 包级节点、Solid、Shell、Beam、连接计数等于子制品汇总；
- Solid 体积、空间几何体积、扣除合法结构占据后的净空腔体积和可解析质量清单内部一致；不可解析质量必须列出原因；
- 房间内合法柱/构件占据与误填充楼板/墙体分开报告，不能把柱体积重复计为空气体积；
- 18D 使用面两侧空间探针把室内柱、梁等原 `unclassified` 边界归入精细内部暴露面；18C 原始表面目录及其指纹保持不变；
- 同一规范化输入生成稳定包指纹；结构、保真度、网格或材料绑定改变会改变指纹；
- 三类旧资产的 ID、默认几何、目录行和原调用测试保持不变；
- Phase 18A–C 专项矩阵全部回归通过，依赖边界无新增违规。

真实 LS-PrePost 导入、LS-DYNA 求解、材料标定和网格收敛仍作为独立工程证据，不由软件单元测试替代。
