# Phase 18B 材料库与模型库整理设计

> **命名迁移（2026-08-05）：** 本文中的 `2k_*` ID 和 `/2k/` 目录为旧名称。规范资源族现为 `two_storey_rc_frame_blast_reference`；加载器继续接受旧 ID 作为兼容别名，但列表、目录、审核清单和新导出使用规范名称。原文件名 `2.k` 只保留为来源追溯。

**状态：** 已批准，进入实施

**日期：** 2026-08-05
**范围：** Phase 18B 材料、构件与结构关系资源的审核入库

## 1. 目标

在不修改现有资源 ID、不破坏既有调用接口的前提下，把当前混放的材料资源、`2.k` 完整参考包、构件级 K 文件以及 Section/Curve/Part/Set/耦合关系整理成可查询、可审核、可追溯的两级资源体系。

系统对外保持两个资源入口：

1. 材料库；
2. 模型库。

审核记录独立存放，但不作为第三个可调用资源库。Section、Curve、Part、Set 和耦合关系归入模型库的 `structural` 子库。

## 2. 目录结构

```text
resources/
├─ materials/
│  ├─ builtin/
│  └─ phase18/
│     └─ 2k/
├─ model_library/
│  ├─ references/
│  │  └─ phase18/
│  │     └─ 2k_complete_reference/
│  ├─ components/
│  │  └─ phase18/
│  │     └─ 2k/
│  ├─ structural/
│  │  └─ phase18/
│  │     └─ 2k/
│  └─ buildings/
│     ├─ legacy/
│     └─ detailed_rc/
└─ reviews/
   └─ phase18/
      └─ 2k_syntax_unit_review.json
```

Phase 18B 只创建当前已有资源所需的目录。`buildings/legacy` 与 `buildings/detailed_rc` 是稳定的后续落点，不创建空目录，也不在本阶段生成新建筑模型。

## 3. 材料库

### 3.1 分类

- `materials/builtin/`：现有通用材料与演示材料；
- `materials/phase18/2k/`：从 `2.k` 确定性提取的六份材料资源。

六个稳定资源 ID：

- `2k_mid5_concrete_kc`；
- `2k_mid8_rebar_d8_d18`；
- `2k_mid12_rebar_d12`；
- `2k_mid14_rebar_d20`；
- `2k_mid2_air_eos2`；
- `2k_mid3_tnt_eos1`。

### 3.2 状态模型

- `source_reference`：忠实提取但未获得审核提升；
- `syntax_unit_reviewed`：语法、单位、来源和依赖闭合审核通过；
- `engineering_validated`：工程标定状态，Phase 18B 不授予。

源资源文件始终保存 `validation_status=source_reference`。只有资源规范哈希与审核清单一致时，查询层才叠加 `effective_validation_status=syntax_unit_reviewed`。所有 `2.k` 资源继续保持 `requires_project_review=true`。

## 4. 模型库

### 4.1 完整参考包

`references/phase18/2k_complete_reference` 保存完整压缩 K 文件、清单、库存和审计报告。它是追溯与差异核对基准，不进入普通构件推荐结果。

### 4.2 构件包

`components/phase18/2k` 保存梁、柱、楼板、基础四个独立、自包含构件包。每包由 `manifest.json`、压缩 K 文件和 `audit.json` 组成，并继续支持按稳定资源 ID 查询、校验和导出。

### 4.3 结构资源子库

`structural/phase18/2k` 保存五个结构化资源：

- `2k_sections_used`；
- `2k_curve1_kc_rate`；
- `2k_part_role_map`；
- `2k_sets_used`；
- `2k_embedded_couplings`。

这些 JSON 资源提供独立查询与审核能力，但不替代构件 K 文件中的自包含卡片。未使用的 MID 9/10/11/13、SECID 7/8 和 Part Set 5/7/8 只保留在完整参考审计信息中，不发布为可调用结构资源。

### 4.4 既有程序化模板

现有程序化模板继续由原注册表生成。统一目录查询层使用 `source_type`、`asset_class` 和 `fidelity` 描述程序化模板与文件型资源的差异，不移动生成逻辑，也不改变模板 ID。

## 5. 兼容约束

1. 材料与模型加载器递归发现资源；
2. 资源身份由 `id`/`resource_id` 决定，不由物理路径决定；
3. 发现重复 ID 时失败，不允许后扫描文件静默覆盖；
4. 公共返回结果不暴露 `_path` 或本机绝对路径；
5. 旧物理目录在迁移期仍可扫描，因此现有调用不依赖路径迁移时序；
6. 导入器直接写入规范目录，不再生成新的平面目录资源；
7. 审核清单与资源规范哈希绑定，内容变化立即使有效审核状态失效；
8. 完整参考包、构件包、结构资源和材料资源共享同一个源文件 SHA-256。

## 6. 查询边界

材料库提供列出、获取和材料资源验证。模型库提供模型资源列出、获取、验证、导出，以及结构资源列出、获取和验证。默认列表可返回全部资源，但推荐筛选只接受有效审核状态与允许的资源类型。

JSON 文件与 K 文件仍是事实来源；运行时索引由递归扫描确定性构建，不新增需要人工同步的数据库副本。

## 7. 迁移顺序

1. 用测试固定现有资源 ID、数量和公共调用行为；
2. 升级递归发现与重复 ID 检查；
3. 将材料迁移到 `builtin` 和 `phase18/2k`；
4. 将完整参考包与构件包迁移到规范目录；
5. 生成五个结构资源；
6. 生成并验证哈希绑定审核清单；
7. 接入公共查询与验证工具；
8. 运行定向、兼容、全量和打包边界验证。

## 8. 验收标准

- 现有 11 份材料仍可按原 ID 查询；
- 六份 `2.k` 材料获得可验证的有效审核状态；
- 四个构件包仍可按原 ID 校验和导出；
- 五个结构资源能独立列出、查询和校验；
- 依赖关系闭合，未使用卡片不进入生产资源；
- 不存在重复资源 ID、本机绝对路径或无效审核提升；
- 原有材料、模型和工具调用测试无回归；
- 不声明求解器验证或工程标定完成。
