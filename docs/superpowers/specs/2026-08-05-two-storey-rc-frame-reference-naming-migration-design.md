# 双层钢筋混凝土框架爆炸参考模型命名迁移设计

**状态：** 已批准，进入实施  
**日期：** 2026-08-05  
**范围：** 原始来源名 `2.k` 对应的模型、构件、材料、结构关系、审核清单和导入入口

## 1. 规范身份

- 中文显示名：`双层钢筋混凝土框架爆炸参考模型`
- 英文显示名：`Two-Storey Reinforced Concrete Frame Blast Reference Model`
- 规范族标识：`two_storey_rc_frame_blast_reference`
- 原始来源文件名：`2.k`，只保留在 `provenance.source_name`、历史审核文档和兼容别名中。
- 不使用 `benchmark`、`validated` 或其他暗示工程验证完成的名称。

## 2. 规范资源 ID 与兼容别名

### 2.1 模型资源

| 规范 ID | 旧别名 |
| --- | --- |
| `two_storey_rc_frame_blast_reference` | `2k_complete_reference` |
| `two_storey_rc_frame_beam_reference` | `2k_rc_beam_reference` |
| `two_storey_rc_frame_column_reference` | `2k_rc_column_reference` |
| `two_storey_rc_frame_slab_reference` | `2k_rc_slab_reference` |
| `two_storey_rc_frame_foundation_reference` | `2k_rc_base_reference` |

### 2.2 材料资源

| 规范 ID | 旧别名 |
| --- | --- |
| `two_storey_rc_frame_mid2_air_eos2` | `2k_mid2_air_eos2` |
| `two_storey_rc_frame_mid3_tnt_eos1` | `2k_mid3_tnt_eos1` |
| `two_storey_rc_frame_mid5_concrete_kc` | `2k_mid5_concrete_kc` |
| `two_storey_rc_frame_mid8_rebar_d8_d18` | `2k_mid8_rebar_d8_d18` |
| `two_storey_rc_frame_mid12_rebar_d12` | `2k_mid12_rebar_d12` |
| `two_storey_rc_frame_mid14_rebar_d20` | `2k_mid14_rebar_d20` |

### 2.3 结构关系资源

| 规范 ID | 旧别名 |
| --- | --- |
| `two_storey_rc_frame_sections` | `2k_sections_used` |
| `two_storey_rc_frame_kc_rate_curve` | `2k_curve1_kc_rate` |
| `two_storey_rc_frame_part_roles` | `2k_part_role_map` |
| `two_storey_rc_frame_sets` | `2k_sets_used` |
| `two_storey_rc_frame_embedded_couplings` | `2k_embedded_couplings` |

规范资源声明 `aliases`。资源列表只返回规范 ID；获取、校验、导出和材料绑定接受规范 ID 或旧别名。通过旧别名查询时返回同一份规范资源，不复制第二份资源文件，也不产生第二条审核记录。

## 3. 目录与文件

```text
resources/materials/phase18/two_storey_rc_frame_blast_reference/
resources/model_library/references/phase18/two_storey_rc_frame_blast_reference/
resources/model_library/components/phase18/two_storey_rc_frame_blast_reference/
resources/model_library/structural/phase18/two_storey_rc_frame_blast_reference/
resources/reviews/phase18/two_storey_rc_frame_blast_reference_syntax_unit_review.json
```

完整压缩载荷命名为 `two_storey_rc_frame_blast_reference.k.gz`。构件包目录使用规范构件 ID；兼容别名由加载器解析，不保留旧目录副本。

新增规范导入入口 `scripts/import_two_storey_rc_frame_blast_reference.py`。`scripts/import_2k_resources.py` 保留为兼容包装器，调用同一实现。

## 4. 别名安全合同

加载器必须拒绝以下情况：

1. 两个规范资源声明同一别名；
2. 某个别名与另一个规范资源 ID 冲突；
3. 空别名、非字符串别名或资源把自己的规范 ID 再声明为别名；
4. 依赖关系仍指向未登记的旧标识。

旧 ID 兼容只用于解析；新项目、列表、导出建议名、清单、审核记录和依赖绑定全部写规范 ID。

## 5. 审核与工程边界

资源 ID、显示名和别名进入规范哈希，因此迁移后必须重建 11 条审核记录并重新验证。原始 SHA-256、源行、数值、单位、网格和耦合关系不得改变。迁移不提升 `validation_status`，所有来源资源继续保持 `source_reference`、`requires_project_review=true`，有效审核状态最多为 `syntax_unit_reviewed`。

## 6. 验收标准

- 列表中只出现 5 个规范模型 ID、6 个规范材料 ID和5个规范结构关系 ID，不出现旧 `2k_*` ID。
- 每个旧 ID 与对应规范 ID 获取相同的规范资源、载荷哈希和物理计数。
- 旧模型 ID仍可完成校验与导出；旧材料 ID仍可用于材料绑定。
- 规范导入脚本可确定性重建新目录，旧导入脚本得到相同输出。
- 11 条审核记录与规范资源哈希匹配，有效状态保持 `syntax_unit_reviewed`。
- 发布包只包含新目录和新审核清单，不包含旧目录副本或本机绝对路径。
- Phase 18A-1/18B 定向测试、全量 Python 测试、编译和打包边界检查无回归。
