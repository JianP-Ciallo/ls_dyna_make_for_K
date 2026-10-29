# Phase 18 分层空气域缓冲层 R12 隔离验证

日期：2026-08-22

结论范围：仅验证 Phase 18 采用的 `*MAT_ALE_VACUUM`、分离的侧面/顶部非反射边界以及底面 no-flow/slip 边界卡可被指定 LS-DYNA R12 接受并完成短时程计算。本报告不是三个大型建筑的最终 PASS，也不构成工程验证。

## 1. 最终结论

- 静态审计：PASS。
- `mcheck=y`：PASS，返回码 0，无 keyword error，完成 1 个检查循环并正常终止。
- 50 微秒短时程：PASS，返回码 0，正常终止，显式终止标志存在。
- 最终问题时间：`5.4851e-4 s`，不小于请求的 `5.0e-5 s`。
- GLSTAT 与 MATSUM：均存在、非空且所有解析数值有限。
- 汇总门槛：`all_ok=true`。

求解器 SHA-256：

```text
7a76b0c358a9d0822b8e37edaab9a46171d0376e45fe4f1f2b527974312ca991
```

隔离模型 SHA-256：

```text
9b8770b915c4219028959afb1f21d1680571ac97b7f2e3da6235ae081aa11c46
```

## 2. 被验证的拓扑与物理卡

- 网格：`4 × 4 × 6`，175 节点、96 个 HEX8 ALE 单元。
- active air：64 个单元、4 层。
- coupling buffer：32 个单元、底部 2 层。
- 缓冲材料：PID 2 → MID 9 → `*MAT_ALE_VACUUM_TITLE`，RHO=`1.225e-5 kg/m³`，EOS=0。
- MMG：仅包含 `(PID 1, IDTYPE 1)` 与 `(PID 2, IDTYPE 1)`。
- 侧面非反射：96 个面。
- 顶部非反射：16 个面。
- 底面非反射：0 个面。
- 底面 no-flow/slip：16 个面、25 个唯一节点，`IDTYPE=2`、`ICTYPE=2`。
- 三组边界均通过完整面集合、无重复和有符号外法向审计。

## 3. 真实求解暴露并修复的问题

首次 mcheck 被 R12 拒绝，报 `Error 10246`、`Error 10450` 与最终 `Error 10133`。根因不是 vacuum 或底面卡，而是共享 `render_control_ale()` 仍输出旧的单行 `0,1,2,-1`；R12 需要 DCT=`-1` 且需要完整的两行 `*CONTROL_ALE` 数据。

修复后输出：

```text
-1,1,2,-1.0,0.0,0.0,0.0,0.0
0.0,1.0e20,1.0,1.0e-6,0,0,101325.0,0
```

修复回归与隔离夹具测试通过后，在全新空目录中重新执行，获得本报告的最终 PASS。

## 4. 原始证据身份

原始证据目录：

```text
var/phase18-ale-buffer-r12-20260822-02
```

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| `fixture_result.json` | 4,630 | `d21391b36cb3de86995a2985a68e834b8d0d0dd4aba6f9b748e25b69ebe3054f` |
| `model.k` | 9,357 | `9b8770b915c4219028959afb1f21d1680571ac97b7f2e3da6235ae081aa11c46` |
| `model.json` | 325 | `722bf47d63e1a6cfa67e510d87afa927f2597d93bc874427aba118b9ce9b806b` |
| `solver_smokes/latest.json` | 2,982 | `ed7ac185f0ed153a8c38d7f56dcbc72bd42354cc8706971b9d59d91a060f5c58` |
| `solver_runs/latest.json` | 7,721 | `8b67a057cd8442e679ae2dd5cc627f79d1ae69d212876c82f2dcc14bf081c3eb` |
| solve `d3hsp` | 204,039 | `edf1d8ab6666dc61ef6c0c2cbe5c3a778e6fa0738fada4ca3196ce960b73505e` |
| solve `glstat` | 1,144 | `7d3ce25946baf98a37a7799b179dcc4c132c00e1a211d8ed0eb5d0e722ec4e73` |
| solve `matsum` | 1,732 | `fc0e8070ad917b82745d6df13f950007b1d3e522069ee470961d1dde8dc52ef3` |
| solve `d3plot` | 16,384 | `9c32a6478d28a44089c7279a989e14c2482b7d1141cb0839b32541f97cebaf8b` |

## 5. 工程边界

本夹具只关闭“R12 能否接受并短时程运行这组 ALE 缓冲与边界卡”的发布门禁。项目继续保持：

- `engineering_validated=false`
- `solver_ready=false`
- `requires_project_review=true`

三个真实大型模型仍必须分别完成生成、LS-PrePost 导入、R12 mcheck、1 ms 串行验证和传播证据验收，才能形成三项齐全的最终 PASS。
