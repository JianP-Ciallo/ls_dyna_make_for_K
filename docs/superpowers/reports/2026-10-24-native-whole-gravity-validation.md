# 新运行时单轮整栋自重验证：未通过，已停止

2026-10-24，按用户当次明确确认，使用新独立运行时执行一轮三层整栋自重预平衡；只有父模型达到 100% 自重并通过验收，才进入同进程原 13 单元子域验收。本轮在内部时间预算到达后以 `deadline` 结束，最后接受自重系数为 **0.1837890625（18.37890625%）**，未完成整栋验收。**13 单元子域未运行；没有追加求解、重新建模、修复或测试。** TNT、全量及其他重型案例均未运行。

## 范围与身份

- 630 个结构节点、546 个单元、2976 个自由结构自由度、3780 个质量点。
- 新目录：`artifacts/native-whole-gravity-20261024-01`。原 K、现有修改、历史结果及默认运行时均保留，无提交、合并或清理。
- 使用原审计缓存准备新输入，静态重力采用已修正的 `source_shape_virtual_work@1` 映射。几何节点、单元、支承、柱/板截面及配筋、质量点、模板身份和原 K 文件身份与现有参考逐项完全相同；修正后的重力表合力、力矩守恒检查通过。
- 保持 `g=9.80665 m/s²`、物理相对残差 `≤1e-5`、厚度应力 `|σ33|≤1e-8 Pa`、对角缩放对称物理切线判据门槛 `1e-9`。未降低阈值，未改变强度、Gf、边界或钢筋布置。
- 仅一个独立原生 worker，允许既有算法在核对原生回退后调整载荷步长；自动重启数为 0。

新解释器：`artifacts/native-runtime-20261023-01/resume-01/runtime/python.exe`。

实际使用的材料修复模块为 `runtime/Lib/site-packages/openseespywin/opensees.pyd`，版本 3.8.0，SHA256：

```text
0831c83756d777f4bdf765896193a5e55714037f2cba7ac70a5b71da43f0c81d
```

新请求 SHA256：`c4556104d98c230d5eea4ce7af6f0c7e9f023bbb4a7f2f82543d5c60b566c597`。输入、方法、运行时及授权均另存于本次目录，未改写历史冻结请求。原运行时全部已记录二进制摘要及本次快照中的关键历史文件摘要复核相同。

## 时间和退出

| 项目 | 实测或预算 |
|---|---:|
| 输入准备 | 37.343 s |
| worker 内部预算 | 150 s |
| 父进程截止 | 180 s |
| 重力诊断耗时 | 152.641 s |
| worker 失败记录耗时 | 153.875 s |
| worker 最终状态耗时 | 154.703 s |
| 父进程实际耗时 | 155.437 s |
| 父进程状态 / 返回码 | `failed` / `1` |
| 180 s 强制截止 | 未触发 |

内部预算只能在同步原生调用之间检查；最后原生调用返回、失败诊断写盘和退出耗时使总时间超过 150 s，但没有延长预算或触发 180 s 父进程终止。最终失败原因是 `deadline`，不是 100% 自重验收通过。

## 最后接受状态：仅 18.37890625% 自重

| 检查 | 结果 |
|---|---:|
| 实际物理相对残差 | 1.1848713e-8 |
| 力平衡相对误差 | 2.1659060e-12 |
| 力矩平衡相对误差 | 1.0394747e-12 |
| 当前切线 | 2976 自由度，原 `1e-9` 判据正定 |
| 最大 `|σ33|` | 9.8516466e-9 Pa，35376 个采样点全部通过 |
| 最大位移 | 4.587104 mm，参考零基节点 303 |
| 最大钢筋应力绝对值 | 102.929667 MPa，`e264-ip3-layer18` |
| 最大壳混凝土拉伸损伤 | 0.9999999435，单材料点指标 |
| 最大壳混凝土压缩损伤 | 0 |

厚度应力最差点为 `roof.0` 原生单元 346、积分点 4、混凝土第 16 层。上述量仅描述部分自重已接受状态，不能冒充全自重状态、整栋损坏比例、承载力极限或爆炸响应。最后自重进度及高损伤点也不足以判定真实结构已经失稳或倒塌。

共 11 次内部载荷试步：接受 10%、17.5%、17.8515625%、18.37890625% 四个状态，7 个试步原生返回 `-3`。最后请求系数为 0.19169921875（19.169921875%）；日志包含材料/域更新失败及 Newton 迭代不收敛。现有证据没有定位每次拒收的具体材料点或确定最终物理原因；本轮按用户要求停止，没有追加诊断求解。

所有已记录失败试步的位移、转角、钢筋应力/应变、混凝土损伤和柱纤维可观察回退场误差均为 0；退出时返回场与最后接受场的最大绝对差也均为 0。`restored_to_accepted_state=true`。这证明本轮所记录可观察场一致，不等同于任意元素全部隐藏状态的通用原子回滚保证。

## 证据与易误读字段

- [汇总 JSON](../../../artifacts/native-whole-gravity-20261024-01/reviewed-summary.json)
- [当次授权](../../../artifacts/native-whole-gravity-20261024-01/authorization.json)、[范围核对](../../../artifacts/native-whole-gravity-20261024-01/scope-review.json)、[新冻结请求](../../../artifacts/native-whole-gravity-20261024-01/request.json)
- [父进程结果](../../../artifacts/native-whole-gravity-20261024-01/execution-01/process-outcome.json)
- [完整失败记录](../../../artifacts/native-whole-gravity-20261024-01/execution-01/worker/failure.json)、[重力诊断](../../../artifacts/native-whole-gravity-20261024-01/execution-01/worker/native-gravity-failure.json)
- [最后接受现场](../../../artifacts/native-whole-gravity-20261024-01/execution-01/worker/accepted-state.json)、[最后试态](../../../artifacts/native-whole-gravity-20261024-01/execution-01/worker/trial-state.json)、[原生日志](../../../artifacts/native-whole-gravity-20261024-01/execution-01/logs/stderr.log)

`accepted-state.json` 的 `status=running` 是迭代中的接受快照，最终应以父进程 `failed`、worker `failed` 和 `reason_code=deadline` 为准。没有 `parent-equilibrium.json`、`thirteen-element-result.json` 或成功 `result.json`。

授权中的启动计数 0、`scope-review` 的准备状态及 `preflight` 的未运行字符串也是启动前快照；本次实际启动一次，以 `execution-started.json`、父进程结果和最终汇总为准。报错/schema 中沿用的 `small` 名称不代表本次是 micro。`domain_reuse_allowed=false`，即使记录的回退场一致，也不能继续复用该求解现场。

`plane_stress.tangent_scope` 仍含旧的 `native_finite_difference_matrix...` 描述字符串；本次没有修改该 Python 元数据。实际原生模块由上述 SHA256 标识，是已完成解析切线修复的二进制。厚度应力检查本身不能单独认证切线分支一致性；材料专项证据见此前[小模型验收报告](2026-10-24-native-material-runtime-progress.md)。

限定范围的独立只读复核确认上述进度、预算、最终失败、未运行子域及可观察回退场结论一致，没有追加模型、测试或项目脚本运行。

本次执行范围到此结束。再次整栋尝试、更改求解策略、TNT、全量或其他重型验证均未启动。
