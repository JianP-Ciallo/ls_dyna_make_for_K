# 三个完整求解输入样例

本目录包含除“钢筋冲击头盔”外的三个受控场景样例。所有 `model.k` 都由当前版本 `lsprepost-mcp` 生成，不是手工拼写的 keyword 文件。

三个样例均已通过本项目静态校验，并满足 `ok_for_solver_draft=true`。这表示求解输入草稿所需的基本模型、控制卡和输出卡已经生成，不表示已经通过真实 LS-DYNA 求解或工程认证。

## 1. 圆柱杆冲击固定钢板

目录：`sample_rod_impact_plate`

- 实体圆柱杆：长 0.5 m，半径 0.02 m。
- 杆件初速度：沿 Z 轴向下 10 m/s。
- 壳钢板：0.8 x 0.6 x 0.004 m。
- 钢板四周固定。
- 杆与钢板采用 `*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE`。
- 终止时间：0.1 s。
- d3plot 输出间隔：0.001 s。
- 材料：内置名义低碳钢弹性材料。

主要检查卡：

```text
*INITIAL_VELOCITY_NODE
*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE
*BOUNDARY_SPC_SET
*CONTROL_TERMINATION
*DATABASE_BINARY_D3PLOT
```

## 2. 立方体顶面四角受载

目录：`sample_cube_top_corner_load`

- 实体立方体：2 x 2 x 2 m。
- 网格尺寸：0.5 m。
- 底面固定。
- 顶面四角节点沿 Z 轴向下各加载 1000 N。
- 载荷在 1 s 内从 0 线性增加到 -1000 N。
- 终止时间：1 s。
- d3plot 输出间隔：0.01 s。
- 材料：内置名义低碳钢弹性材料。

主要检查卡：

```text
*HOURGLASS_TITLE
*DEFINE_CURVE
*LOAD_NODE_SET
*BOUNDARY_SPC_SET
*CONTROL_TERMINATION
*DATABASE_BINARY_D3PLOT
```

## 3. 壳板均布压力

目录：`sample_plate_pressure`

- 壳钢板：1.0 x 0.5 x 0.003 m。
- 网格尺寸：0.05 m。
- `x_min` 边固定。
- 板面压力在 1 s 内从 0 线性增加到 20000 Pa。
- 终止时间：1 s。
- d3plot 输出间隔：0.01 s。
- 材料：内置名义低碳钢弹性材料。

主要检查卡：

```text
*SET_SEGMENT
*DEFINE_CURVE
*LOAD_SEGMENT_SET
*BOUNDARY_SPC_SET
*CONTROL_SHELL
*CONTROL_TERMINATION
*DATABASE_BINARY_D3PLOT
```

## 每个目录的文件

```text
model.k                 LS-DYNA 求解输入
model.json              受控模型源数据
checks.json             静态校验结果
open_model.cfile        LS-PrePost 打开模型的受控命令文件
artifacts/cfiles.json   cfile 来源和哈希记录
export_manifest.json    项目导出记录
summary.json            尺寸、网格、载荷和模型摘要
solver_preflight.json   求解卡、来源和 readiness 检查
sample_manifest.json    样例文件 SHA256 清单
```

## 使用步骤

1. 先在 LS-PrePost 中打开样例目录内的 `model.k`，检查几何、网格、材料、约束、载荷、接触和控制卡。
2. 在 Web App 中也可以使用“导入完整模型文件夹”导入该目录，再查看三维模型或打开 LS-PrePost。
3. 在右侧导入本机 `lsrun.exe` 和 LS-DYNA 求解器后，点击“送入 LS-Run”；也可以直接在 LS-Run 中选择该目录的 `model.k`。
4. 在 LS-Run 中人工核对输入文件、求解器、工作目录、CPU 和内存，然后启动求解。
5. 求解完成后，在 LS-PrePost 中打开 `d3plot`，查看位移、应力、应变、接触和能量结果。

## 必须人工复核

- `checks.ok=true` 和 `ok_for_solver_draft=true` 仅代表本项目静态检查通过。
- 三个样例尚未在本轮实际运行 LS-DYNA，`solver_preflight.json` 中明确记录 `real_lsdyna_run_completed=false`。
- 内置低碳钢使用名义弹性参数。若研究屈服、塑性、破坏或贯穿，必须更换并验证适用的材料模型。
- 网格、时间步、接触参数和边界条件应根据实际分析目的重新做收敛性与合理性检查。
