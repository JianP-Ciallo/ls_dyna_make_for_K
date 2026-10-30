# Phase 15 状态核对说明

核对日期：2026-10-30。本次只读取已有源码、路线图和本地验收记录，不运行模型生成、LS-DYNA、全量回归或重型测试。

## 状态口径

| 层面 | 证据与结论 |
| --- | --- |
| 软件实现 | [路线图](../../ROADMAP.zh-CN.md#3-阶段总览)标记“已完成当前实现基线”；现有代码包含二维轴对称网格、材料、FSI 接口和 Web 生成流程。 |
| 历史受控案例 | 2026-07-23 的 `phase15_a1_kc_axisymmetric_fsi_mmgfix` 保存了波传递验收通过的报告。结论仅对应该冻结输入及当时验收条件。 |
| 共形方案 | `phase15.py` 将 `conforming_shared_nodes` 和 `conforming_air_gap` 标为 `experimental_unqualified`，分别保留共享孔壁负体积、尚未完成真实求解资格验证的限制。 |
| 工程精度 | 历史单案例报告不能证明材料标定、网格收敛、所有工况的可靠性或损伤预测能力。 |

因此，“Phase 15 开发中”不能准确概括整个阶段；当前应表述为“实现基线已完成，验证结论按案例和方案分别限定”。

## 已保存案例的证据

案例目录位于本机 `workspace/projects/phase15_a1_kc_axisymmetric_fsi_mmgfix/solver_runs/run_20260723T035250861328Z_ca5bb48b/`。原始计算结果保留在本机，不随源码上传。

读取该目录的 `run.json` 与 `wave_transfer_acceptance.json`，得到：

| 项目 | 保存的结果 |
| --- | --- |
| 运行日期 | 2026-07-23 |
| 运行状态 / 返回码 | `completed` / `0` |
| `wave_transfer_verified` | `true` |
| FSI 从属线段数 | `193`；原始 `d3hsp` 中的数量与报告一致 |
| 混凝土静水压力响应 | `78765.66666666667 Pa` |
| 混凝土主应力响应 | `154063.69180871634 Pa` |
| 沿测点的主应力波传播 | 历史报告记录 `verified: true` |
| K&C scaled damage | 可读且有限，峰值 `0.0`；不能据此声称已出现损伤 |
| 后处理记录 | `requires_lsprepost_verification`，未记录应力云图验证完成 |

冻结 `model.k` 的实际 SHA-256 与 `run.json` 中的输入哈希一致：

```text
817834b15e2b581f7914089bef2ef1ff1bfdf810f6e607e3dec2117d83981129
```

本次读取的原始 `wave_transfer_acceptance.json` SHA-256 为：

```text
ad47ef615129fdd667aff80a2f1c785ce8282b8b2ce68d0fcaa2fe7fcaac332e
```

本次没有用当前版本的验收器重新计算此案例，也不把历史通过扩展为其他输入、共形方案或后处理显示的通过。

## README 旧状态的来源

旧 README 的“开发中”和“Phase 15 当前状态”沿用了早期 `phase15_a1_kc_axisymmetric_acceptance_r12fix3`：该案例的 FSI 从属线段数为 0，是保留的失效基线。后续已有实现和上述验收记录，而首页没有同步区分历史失败、实现完成和各方案资格，本次据此修正文档。
