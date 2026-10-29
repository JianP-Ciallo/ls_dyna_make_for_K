# 5-1788-2 三材料轴对称重建

本入口针对固定 SHA-256 `ad8b3fa71216379a66714ea2d9fdaf4db2d241bbadded064f00b98346e8829b8` 的 `5-1788-2.k`。源单位为用户确认的 SI；所有非网格定义按原卡保存，不重设材料或初速度。

## 生成入口

从项目根目录执行：

```powershell
python -B -m lsprepost_mcp.impact_1788_rebuild prepare
python -B -m lsprepost_mcp.impact_1788_rebuild generate --project-name impact_5_1788_2_rebuilt --if-exists versioned
```

默认生成 361,221 节点、360,000 个四边形单元，三个 Part 分别为 360 / 300,000 / 59,640 个单元。节点和连接表来自已有 Phase15 规则拓扑函数，随后映射解析坐标及空间材料区域；生成路径不读取原 K。

几何固定：径向分界 `[0, 0.003, 0.25]` m，轴向分界 `[-0.3, 0, 0.03, 0.06]` m。默认 `radial_cells=[6,494]`、`axial_cells=[600,60,60]` 对应统一 0.5 mm 网格。小规模专项使用 `[1,4]` 和 `[3,2,2]`，保持真实区域边界但减少网格数量。

CLI 支持 `--radial-cells N1 N2`、`--axial-cells N1 N2 N3`，或 `--spec-json PATH`。spec JSON 是 `model.json` 的 `spec` 对象本身，例如交付的 `rebuild_parameters.json`。指定 spec 时，其中的项目名与网格参数优先。`if_exists` 仅接受 error/versioned，不支持覆盖已有项目。

MCP 工具：`prepare_impact_1788_rebuild`、`generate_impact_1788_rebuild`，相应字段为 project_name、radial_cells、axial_cells、if_exists。prepare 只返回估计和资源闭合结果。

## 原卡与资源

22 份资源覆盖全部 24 个非网格块（包括含 MEMORY/NCPU 选项的 KEYWORD 头）。3 份材料包位于 `resources/materials/source_rebuild/impact_1788/`；其余按 resource_kind 分类保存到 `resources/model_library/structural/source_rebuild/impact_1788/`；索引在 `resources/reviews/source_rebuild/impact_1788/source_index.json`。

本仓库已注册资源。首次从相同源文件注册到新的项目副本时：

```powershell
python -B -m lsprepost_mcp.impact_1788_rebuild register-resources 'E:/Desktop/参考/2/5-1788-2.k'
```

原文件和各卡片均受固定哈希约束，未知来源或改动后的卡片被拒绝；已有资源冲突时不覆盖。资源维持 source_reference 状态。第二来源的 MT=41 参数不同于 GRAN_R5，两个来源分别保存、分别校验。

## 验证与交付

项目生成后自动校验实际节点、单元覆盖、材料区域、公共界面与正矩形 Jacobian，并将实际 K 与按 spec 重新生成的文本比较。正式来源证明使用 `scripts/verify_generated_k.ps1 -ProjectDir <目录>`。LS-PrePost 读取可用既有 validate_lsprepost_import 工具。

缺少 MT=41 用户材料实现，求解和生产审核准备状态均为 false。全量回归、重型案例及求解继续遵循 AGENTS.md 的当次授权要求。

专项为 `python -m pytest tests/test_impact_1788_rebuild.py -q`；涉及公共适配时同时选择 GRAN_R5、资源库、JSON-RPC 和来源检查的相关专项。

本次交付在 `E:/Desktop/参考/2/2/`，含可执行参数、独立对比及交付脚本、生成来源证明、资源快照与原卡映射、测试证据、预览和完整交付报告。指定目录的 model.k 是项目生成包的逐字节副本，交付后再次核对来源；没有手工拼接或修改 K。
