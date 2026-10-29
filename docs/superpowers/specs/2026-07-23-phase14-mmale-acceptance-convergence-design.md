# Phase 14 MM-ALE 求解验收与网格收敛设计

## 目标

修复 Phase 14 MM-ALE 求解记录可能仅凭输出文件存在而返回成功的问题，并把现有网格敏感性计划升级为可执行、可持久化、失败关闭的真实网格收敛验收。

## 适用范围

- 只作用于 `result_variant == "ale_blast"`、且 `geometry.scene_variant` 不是
  `open_concrete_tunnel` 的 Phase 14 三维 MM-ALE 钢板爆炸。
- 不修改通道爆炸、Phase 15 二维轴对称爆炸或普通增强爆炸的验收规则。
- 不修改当前已经通过真实求解的 `*CONSTRAINED_LAGRANGE_IN_SOLID` 部件型耦合卡。
- 不把本次数值收敛结果表述为材料标定或工程试验验证。

## 根因

### 求解误报

`execute_lsdyna_run()` 和终态刷新当前只要求 `d3plot` 及非空 `fsifor/dbfsi` 文件。虽然 `_evaluate_d3hsp()` 已解析 `dbfsi` 和 `nodout`，顶层 `record["ok"]` 没有使用这些解析结果，也没有检查耦合载荷和钢板响应。

### FSI segment 语义

现有模型使用 `SSTYP=1` 的部件型 slave 定义。真实求解的 `d3hsp` 同时报告：

- 一个 FSI interface；
- 一个 slave material；
- `number of slave segments for coupling = 0`；
- 非零 `dbfsi` 压力、合力、冲量；
- 非零钢板位移。

该 segment 字段表示显式 segment 定义数量，不能单独用于否定部件型耦合。验收必须区分“显式 segment set”与“由部件表面生成的 slave surface”。

### 网格收敛缺口

`phase14_mesh_sensitivity_report()` 只生成资源计划，没有读取真实求解结果、验证配置一致性或计算相邻网格误差。

## 组件设计

### `phase14_acceptance.py`

新增独立模块，避免继续扩大 `lsdyna_runner.py`。

### `solver_results.py`

扩展 `parse_fsi_interfaces()`，在保留现有字段和 `all_nonempty` 语义的前提下新增：

- `slave_material_count`
- `has_slave_definition`
- `slave_definition_mode`

`has_slave_definition` 在显式 slave segment 数量大于零，或
slave material/part 数量大于零时为真。现有 Phase 15 调用方继续使用原字段，
避免本次变更扩大到其他场景。

#### `evaluate_phase14_wave_transfer(project: Path, run_dir: Path) -> JSONDict`

读取：

- `model.json`
- `d3hsp`
- `dbfsi`
- `nodout`

输出 `wave_transfer_verified`、结构化 checks 和解析指标。

必须全部满足：

1. `model.json` 声明 `model_type == "ale_blast_scene"`，且不是
   `geometry.scene_variant == "open_concrete_tunnel"`。
2. 元数据声明至少一个 coupling、至少一个 Lagrangian shell element 和非空目标板响应节点。
3. `d3hsp` 正常终止并识别至少一个 FSI interface。
4. slave 定义有效：
   - 显式 segment 总数大于零；或
   - slave material/part 数量大于零。
5. `dbfsi` 可解析，状态数至少为 2。
6. 峰值耦合压力为正有限值。
7. 峰值 FSI 合力为正有限值。
8. FSI 冲量为正有限值。
9. `nodout` 可解析，状态数至少为 2。
10. `nodout` 峰值位移节点属于 `target_plate.response_node_ids`。
11. 峰值钢板位移为正有限值。
12. 钢板峰值位移时间不早于峰值耦合压力时间。

这些门禁证明“求解器识别耦合并产生可观测结构响应”，不设置工程量级阈值。
实际 coupling、shell element 和目标响应节点从运行目录的 `model.k` 快照解析；
不信任可在求解后修改的项目根目录元数据。新运行同时快照 `model.json` 并记录
其 SHA-256；历史运行只有在当前 deck 与运行快照物理摘要一致时才允许使用当前
`model.json`。

#### `evaluate_phase14_mesh_convergence(projects: list[Path], tolerance: float = 0.10) -> JSONDict`

要求：

- 至少三个项目，最多八个项目。
- 项目名不得重复。
- 全部为 `ale_blast_scene`，且都不是
  `geometry.scene_variant == "open_concrete_tunnel"`。
- 除 `project_name` 和 `mesh.size_m` 外，规范化后的 model spec 必须完全一致。
- 网格尺寸必须为正、有限、互不相同。
- 每个项目必须有完整终态求解记录。
- 运行记录 `input_sha256` 必须匹配求解目录中的 `model.k` 快照。
- 当前 `model.k` 与求解快照的非输出物理卡摘要必须一致。摘要忽略
  `*DATABASE_*` 卡，以及 `model.json` 明确声明为 ALE 压力探针输出的
  solid set。探针 set 只有在当前 deck 与求解快照中仅单侧存在时才可忽略；
  两侧都存在时，其成员仍参与摘要。控制、材料、几何、边界和耦合卡始终
  必须一致。
- 三档求解快照的非网格控制摘要必须一致。该摘要排除节点、单元和集合成员，
  但保留控制、材料、EOS、部件、耦合、边界和集合身份。
- 固定字段数据行保留原始列位置参与摘要，不折叠内部空格。
- 每个记录必须通过 `wave_transfer_verified`。

按网格从粗到细排序，对以下指标计算相邻误差：

- `peak_coupled_surface_pressure_pa`
- `fsi_impulse_n_s`
- `peak_displacement_m`

误差公式：

```text
relative_difference = abs(finer - coarser) / abs(finer)
```

每个指标必须满足：

- 所有数值均为正有限值。
- 最细两档的 `relative_difference <= 0.10`。
- 最细两档误差不大于前一档误差。

全部指标满足时：

```json
{
  "status": "converged",
  "convergence_verified": true,
  "tolerance": 0.1
}
```

否则返回 `status: "not_converged"` 或 `status: "invalid_evidence"`，不抛弃具体失败 checks。

## 求解记录集成

`lsdyna_runner.py` 在首次求解完成和终态刷新时调用同一验收函数：

- 写入 `record["wave_transfer_acceptance"]`。
- 写入运行目录 `wave_transfer_acceptance.json`。
- `record["ok"]` 必须包含 `wave_transfer_verified`。
- `postprocessing` 继续表示云图人工/LS-PrePost 核验状态，不替代数值门禁。

旧运行记录在 `latest_lsdyna_run()` 刷新时重新计算验收，避免历史 `ok=true` 绕过新规则。

## 收敛接口

在现有 `/api/solve/compare` 中：

- 当传入至少三个项目且全部为 Phase 14 `ale_blast` 时，附加 `mmale_mesh_convergence`。
- 普通两个项目比较保持原行为。
- 收敛报告写入最细网格项目：

```text
artifacts/mmale_mesh_convergence.json
```

报告包含参与项目、运行 ID、模型摘要哈希、各指标误差、结论和生成时间。
持久化时获取最细网格项目的
`ProjectLock(..., namespace="mmale_convergence")`，并使用临时文件加
`os.replace()` 原子提交，避免并发比较互相覆盖或产生半写文件。

## 现有三档基线

参与项目：

- `phase14_mmale_blast_plate_acceptance_v2_mesh_coarse`：`0.015 m`
- `phase14_mmale_blast_plate_acceptance_v2_mesh_baseline`：`0.0125 m`
- `phase14_mmale_blast_plate_acceptance_v2_mesh_fine`：`0.010 m`

已确认除网格尺寸和项目名外配置完全一致。

基准到细网格、相对于细网格值的误差：

- 耦合压力：`0.0996314819689392`
- FSI 冲量：`0.011073983414944883`
- 钢板位移：`0.04942625232574372`

三项均不超过 `0.10`，且相较粗网格到基准网格的误差下降。代码实现后必须重新读取原始运行文件计算，不得把这些结论硬编码。

## 错误处理

- 缺失、空或无法解析的 `d3hsp/dbfsi/nodout` 均失败关闭。
- NaN、Infinity、零值或负值响应均失败关闭。
- 配置不一致、重复网格或少于三档时不产生收敛结论。
- 报告写入使用临时文件加 `os.replace()`。
- 现有求解输出只读，不移动、不覆盖。

## 测试

### 单元测试

- 部件型 slave：显式 segment 为零但 slave material 非零，可以进入后续响应门禁。
- 显式 segment 和 slave material 均为零，必须失败。
- 非空但无法解析的 `dbfsi`，必须失败。
- 零压力、零冲量或零位移，必须失败。
- 位移峰值早于压力峰值，必须失败。
- 位移峰值节点不属于目标钢板响应节点，必须失败。
- 当前 deck 的物理卡在求解后变化，必须拒绝旧运行证据。
- 仅增加或调整数据库输出卡时，允许复用物理内容相同的旧运行证据。
- 三档同构记录满足误差规则时收敛。
- 任一指标超过容差时不收敛。
- 配置不一致、重复网格、缺失运行记录时失败。

### Runner 回归

- Phase 14 未通过波传递验收时 `record["ok"] == false`。
- Phase 14 通过时写入并持久化验收报告。
- 终态刷新使用同一门禁。
- Phase 15 和其他爆炸结果不受影响。

### 真实结果回归

- 对现有 coarse/baseline/fine 三档重新评估。
- 三档必须分别通过波传递门禁。
- 收敛报告必须为 `convergence_verified == true`。
- 不需要补跑 refined；只有真实计算结果不满足规格时才生成并求解 `0.009375 m` 项目。

## 非目标

- 不宣称 Composition B、钢板材料或边界条件已经过试验标定。
- 不用三档数值收敛替代真实实验验证。
- 不自动启动新的 LS-DYNA 求解，除非现有三档未通过收敛规格。
