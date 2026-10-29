# Phase 18B 材料与模型资源审核报告

**审核日期：** 2026-08-05

**结论：** Phase 18B 的软件侧语法、单位、来源、依赖闭合和确定性入库检查通过。所有来源资源仍要求项目复核，本报告不构成求解器验证或工程标定证明。

## 1. 来源基线

- 规范模型名：双层钢筋混凝土框架爆炸参考模型（`two_storey_rc_frame_blast_reference`）
- 来源文件：`2.k`
- 来源 SHA-256：`c1c02a9e832852854b47cd3720bc9348cf48989484d25e1a54036836d0697a22`
- 来源单位制：`tonne_mm_s_N_MPa`
- 规范资源单位制：`SI_m_s_kg_N_Pa`
- 审核清单：`resources/reviews/phase18/two_storey_rc_frame_blast_reference_syntax_unit_review.json`
- 审核记录数量：11

审核清单保存每份资源的规范内容哈希。路径、运行时分类和有效审核状态不参与规范哈希；任何物理字段、来源卡片或依赖字段变化都会导致审核失效。

## 2. 材料库

材料库按递归目录组织：

- `resources/materials/builtin/`：5 份原有通用或演示材料；
- `resources/materials/phase18/two_storey_rc_frame_blast_reference/`：6 份来源模型类型化材料。

正式审核资源：

| 资源 ID | 类型 | 来源关系 |
|---|---|---|
| `two_storey_rc_frame_mid5_concrete_kc` | `concrete_damage_rel3` | MID 5、Curve 1、MID 5 侵蚀卡 |
| `two_storey_rc_frame_mid8_rebar_d8_d18` | `plastic_kinematic` | MID 8、D8/D18 截面 |
| `two_storey_rc_frame_mid12_rebar_d12` | `plastic_kinematic` | MID 12、D12 截面 |
| `two_storey_rc_frame_mid14_rebar_d20` | `plastic_kinematic` | MID 14、D20 截面 |
| `two_storey_rc_frame_mid2_air_eos2` | `mat_null_eos_linear_polynomial` | MID 2、EOS 2 |
| `two_storey_rc_frame_mid3_tnt_eos1` | `high_explosive_burn_eos_jwl` | MID 3、EOS 1、初始起爆定义 |

源 JSON 始终保存 `validation_status=source_reference`。只有审核清单哈希匹配时，查询接口才返回 `effective_validation_status=syntax_unit_reviewed`。六份资源均保持 `requires_project_review=true`。

## 3. 模型库

模型库规范目录：

- `resources/model_library/references/phase18/two_storey_rc_frame_blast_reference/`：完整参考包；
- `resources/model_library/components/phase18/two_storey_rc_frame_blast_reference/`：梁、柱、楼板、基础四个独立构件包；
- `resources/model_library/structural/phase18/two_storey_rc_frame_blast_reference/`：五类结构关系资源。

结构关系审核结果：

| 资源 ID | 审核数量 |
|---|---:|
| `two_storey_rc_frame_sections` | 6 个已使用 Section |
| `two_storey_rc_frame_kc_rate_curve` | Curve 1，共 23 个点 |
| `two_storey_rc_frame_part_roles` | 12 个 Part 角色和材料/截面绑定 |
| `two_storey_rc_frame_sets` | 7 个发布 Set |
| `two_storey_rc_frame_embedded_couplings` | 5 条耦合关系 |

四个构件包以规范资源 ID 查询和导出；旧 `2k_*` ID 作为兼容别名解析到同一规范资源，不依赖旧物理目录。构件包继续保存混凝土 Solid、钢筋 Beam、必要 Part/Section/Material/Set/Curve/耦合卡片以及来源审计信息。

## 4. 排除资源

以下来源卡片只保留在完整参考审计信息中，没有发布为生产资源：

- MID 9、10、11、13；
- SECID 7、8；
- Part Set 5、7、8。

## 5. 公共接口

新增并验证：

- `validate_material_resource`
- `list_structural_resources`
- `get_structural_resource`
- `validate_phase18_resource_review`

材料和模型加载器均采用递归发现，资源身份由稳定 ID 决定。重复材料 ID、模型资源 ID或结构资源 ID会明确报错，不允许静默覆盖。

## 6. 验证证据

执行结果：

- 审核清单验证：11 条匹配，6 份材料，5 份结构资源；
- Phase 18A-1/18B 联合矩阵：170 项通过，0 失败；
- Python 编译检查：`python -m compileall -q lsprepost_mcp scripts`，退出码 0；
- 命名迁移后全量 Python 测试：819 项运行，0 失败，7 项环境跳过；
- 命名迁移专项测试：10 项通过，覆盖规范 ID 列表、旧别名解析、别名冲突拒绝以及新旧 ID 导出字节一致性；
- 双次资源重生成：相对文件集合及文件字节完全一致；
- 纯包和开发包检查：规范材料、结构资源和审核清单均被包含；
- 路径检查：发布 JSON 不含本机绝对来源路径、`_path` 或 `_resource_dir`；
- 诊断脚本：递归识别分层材料库，在带空格和 Unicode 的工作目录测试中通过。

环境跳过项依赖未启用的外部 GUI 或求解器集成，不包含 Phase 18B 的材料、结构资源、构件包、审核清单或公共接口测试。

## 7. 审核边界

本次审核只证明：

- 来源身份一致；
- 卡片结构可解析；
- 显式单位换算与规范字段一致；
- Part、Section、Material、EOS、Curve、Set 和耦合依赖闭合；
- 入库资源可以确定性重生成和查询。

本次没有启动 LS-PrePost 或 LS-DYNA，没有进行材料试验相关、网格收敛、爆炸损伤预测精度或工程适用范围标定。因此没有资源获得 `engineering_validated` 状态。
