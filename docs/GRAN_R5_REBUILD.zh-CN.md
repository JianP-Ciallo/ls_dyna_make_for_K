# GRAN_R5 原卡复用与解析网格重建入口

本入口处理 SHA-256 为 `49abb80e7528981f8d1b26d902225f674263ca7f49294084a3a5a1931251dfa3` 的 `GRAN_R5_2D_MMALE_6MM.k`。它是有来源约束的专用重建路径，不是任意 K 文件转换工具。

源模型已由用户确认 SI 单位；MT=41 用户材料实现缺失，要求保留原卡。材料和其他物理设置不能通过此入口重新设计。资源保留 `source_reference` 状态，不因静态检查通过而提升工程审核等级。

## 生成

在项目根目录执行：

```powershell
python -B -m lsprepost_mcp.gran_r5_rebuild prepare --project-name GRAN_R5_2D_MMALE_6MM_rebuilt
python -B -m lsprepost_mcp.gran_r5_rebuild generate --project-name GRAN_R5_2D_MMALE_6MM_rebuilt --core-divisions 20 --charge-layers 20 --concrete-layers 30 --if-exists versioned
```

`prepare` 返回规范化参数、网格数量估计和未解决问题；`generate` 经项目事务写入流程生成 `model.k`、`model.json`、`checks.json` 和 `open_model.cfile`，不启动求解器。同名输出默认报错，也可选择 `versioned`，不支持覆盖。

也可用 `--spec-json PATH` 读取独立 spec JSON，例如实际交付目录下的 `rebuild_parameters.json`。该文件是 spec 本身，不是包含 `spec` 字段的整个 `model.json`；提供它时，其项目名和网格参数优先于其他相应 CLI 参数。

MCP 工具为 `prepare_gran_r5_rebuild` 和 `generate_gran_r5_rebuild`。输入字段为 `project_name`、`core_divisions`、`charge_layers`、`concrete_layers`、`if_exists`。原有材料/结构资源查询能发现本来源资源；通用弹性材料解析器会明确拒绝这些原卡包，应由专用重建编译器装配。

## 资源注册

当前仓库已经注册该来源的 17 份资源。需要从同一原文件在新的项目副本中注册时：

```powershell
python -B -m lsprepost_mcp.gran_r5_rebuild register-resources '<原始K文件路径>'
```

注册先检查固定源哈希和资源索引；只提取非网格卡片，不保存原节点/单元表。材料和 EOS 位于 `resources/materials/source_rebuild/gran_r5/`；截面、关系、初始条件、控制、数据库和标题位于 `resources/model_library/structural/source_rebuild/gran_r5/`，由 `resource_kind` 区分。固定索引位于 `resources/reviews/source_rebuild/gran_r5/source_index.json`。

已有内容完全相同允许重复注册；存在冲突则拒绝，不覆盖已有资源。原始行、ID、依赖和单位说明保留在资源 JSON；所有非网格行原样装配，项目写入时可规范换行符。

## 建模和验证边界

`gran_r5_mesh.py` 使用已有 Phase15 四边形拓扑能力和解析映射建立相容分块网格，仅接受三个整数网格参数。几何固定为已核实的源模型。默认生成 49,501 节点、49,000 单元，所有新网格 ID 从 1,000,001 开始；生成时无需访问原 K 文件。

`gran_r5_rebuild.py` 校验实际 K 的几何、引用、界面和 Jacobian，并按保存的 spec 重新生成文本比较。项目生成来源的正式检查入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify_generated_k.ps1 -ProjectDir '<生成命令返回的项目目录>'
```

LS-PrePost 读取和图片导出使用现有 `validate_lsprepost_import` 工具，推荐 `view=top`。由于 MT=41 实现缺失，求解准备和生产审核状态始终为 false；导入和静态检查通过不能替代求解验收。

专项入口为 `python -m pytest tests/test_gran_r5_rebuild.py -q`。仓库 AGENTS.md 的按需测试约定仍然适用；全量、真实重型案例或求解须另行取得当次明确授权。

## 本次交付

实际目录为 `workspace/projects/GRAN_R5_2D_MMALE_6MM_rebuilt/`；完整说明见其中的 [REBUILD_REPORT.zh-CN.md](../workspace/projects/GRAN_R5_2D_MMALE_6MM_rebuilt/REBUILD_REPORT.zh-CN.md)。源分析及测试证据位于 `workspace/imports/gran_r5_49abb80e7528/`。旧分析报告是生成前的阶段记录，最终状态以本次交付报告及其检查文件为准。
