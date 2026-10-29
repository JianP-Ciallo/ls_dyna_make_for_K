# Phase 18 config@4 分层空气域与配置时长短求解验收

日期：2026-09-01

## 1. 验收结论

最终不可变模型快照：

`<MODEL_OUTPUT_ROOT>\Phase18_config4_layered_shortsolve_20260901_03`

三类模型均满足本轮约定的验收条件：

1. 静态关键字验证通过；
2. LS-PrePost 2025 R1（4.12）实际导入通过，0 error、0 warning；
3. LS-DYNA R12 独立 `mcheck=y` 通过；
4. 使用同一 K 文件和同一求解器完成配置时长 `5.0e-5 s` 的实际短时求解；
5. 求解器正常终止、返回码为 0，验收 findings 为空。

本轮已取消 1 ms 验证。验收模式为
`configured_short_solve_no_error`，不是 1 ms 传播验收。

## 2. 最终配置

- Schema：`phase18.solver_blast.config@4`
- 单位制：`SI_m_s_kg_N_Pa`
- TNT 当量：2.0 kg
- TNT 中心：`[-2.0, 1.5, 4.0] m`
- 实体 TNT 单元数：商业 36、住宅 36、地铁 48
- 实现 TNT 质量：约 2.000000266 kg
- 空气域网格：0.225 m
- 近场网格：0.15 m
- 地面网格：0.25 m
- 空气域五向边距：`[3, 3, 3, 3, 3] m`
- 耦合缓冲层：2（Schema 支持 1–5）
- 材料配置：`verification_reference`
- 求解终止时间：`5.0e-5 s`

## 3. 三模型证据

| 场景 | K 大小 | K SHA-256 | 总节点/单元 | 空气/TNT 单元 | FSI 面段 | mcheck | 短求解 | 最终问题时间 |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| 商业超市 | 24.222 MiB | `e0b207d5bc1a6e5fc07ee388b47a1ffa9d1083dadbb63d6bab7190218ab1f1b3` | 214167 / 181198 | 118152 / 36 | 30076 | 15.782 s，PASS | 185.863 s，PASS | `5.0078e-5 s` |
| 住宅社区 | 27.514 MiB | `654a34935fbc73a52572f8d623361654d92580ee35b527c270dc152249ef41f5` | 271899 / 233270 | 125012 / 36 | 30656 | 18.241 s，PASS | 195.820 s，PASS | `5.0068e-5 s` |
| 地铁入口 | 22.444 MiB | `0a248774f2a8259ae5d261a21dc26183706810c852a9cd082ad5f9e65968bcf9` | 188084 / 163760 | 98892 / 48 | 4642 | 13.194 s，PASS | 81.158 s，PASS | `5.0151e-5 s` |

三个 mcheck 记录均满足：

- `status=completed`
- `returncode=0`
- `same_input_as_short_solve=true`
- `same_solver_as_short_solve=true`

R12 求解器 SHA-256：

`7a76b0c358a9d0822b8e37edaab9a46171d0376e45fe4f1f2b527974312ca991`

LS-PrePost 可执行文件 SHA-256：

`730b82b39eb81199eca2c91a3da0be0ab87630685651ef20b8a86eff52058879`

## 4. 关键修复

- 保存草稿只保存配置；轻量预览与完整 K 生成解耦；
- 八步工作台由 Schema 驱动，支持三场景恢复与 config@1–3 到 config@4 迁移；
- 土体、分层空气域、1–5 层耦合缓冲、实体 TNT、可移动爆源和 FSI 接入最终 K 链路；
- 修复住宅梁柱节点重复箍筋，并在 Phase 18 求解装配层处理，保持 Phase 18C 默认指纹不变；
- 修复非承重隔墙壳面朝向一致性；
- 修复地铁入口实体屋盖与 RC 支承的重叠，并保持正 Jacobian；
- 验收脚本升级为 `r12_acceptance@3`：强制 mcheck 先行并校验同一 K、同一求解器哈希。

## 5. 兼容性证据

合并后的主项目回归：

- 378 passed
- 3 deselected（`heavy_provider_e2e`）
- 175 subtests passed
- 0 failed

合并提交：

`4f280de merge: refined blast eight-step layered workflow`

主项目原有未提交文件在合并前后保持未提交状态，未被覆盖或纳入本次提交。

## 6. 证据位置

- 生成汇总：`<MODEL_OUTPUT_ROOT>\Phase18_config4_layered_shortsolve_20260901_03\solver_blast_summary.json`
- LS-PrePost 汇总：`<MODEL_OUTPUT_ROOT>\Phase18_config4_layered_shortsolve_20260901_03\lsprepost_import_summary.json`
- R12 汇总：`<MODEL_OUTPUT_ROOT>\Phase18_config4_layered_shortsolve_20260901_03\solver_blast_r12_summary.json`
- 每个模型的导入截图：`<模型目录>\lsprepost_import\preview_iso.png`
- 每个模型的 mcheck：`<模型目录>\solver_smokes\latest.json`
- 每个模型的短求解：`<模型目录>\solver_runs\latest.json`
- 每个模型的验收记录：`<运行目录>\solver_blast_acceptance.json`

`_01` 为住宅重复箍筋问题的失败快照；`_02` 为恢复 Phase 18C
兼容指纹前的已验收但已替代快照；`_03` 是与最终合并代码对应的最终快照。

## 7. 验收边界

45–70 MiB 是软指标。最终模型未达到该体积区间，但没有为追求文件大小增加无物理意义网格。

虽然短求解结果中可记录空气与建筑响应信号，本轮 PASS 只代表“配置时长内求解无 error
且正常终止”，不能替代完整爆炸传播收敛研究、材料标定、网格敏感性研究或工程复核。因此最终记录必须保持：

- `engineering_validated=false`
- `solver_ready=false`
- `requires_project_review=true`
