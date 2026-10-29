# 三层建筑原生自重求解交接文档

交接日期：2026-10-23。项目：`E:/workplace/codex_mcp_k`。当前分支：`codex/neibao`。

**当前已按用户要求暂停工程工作。本次仅整理交接，不恢复编译、测试或求解。** 后续接手者应先等待用户恢复任务，再按本文范围继续。

已确认静态重力映射错误，并完成相应 Python 修正；又复现了原生材料厚度方向平衡和刚度差分两个独立问题。原生修复尚未实现，独立运行时尚未构建完成，三项小模型验收仍失败。不能把 11.875% 自重附近停止解释为建筑实际承载极限，也不能承诺修复这两个问题后整栋必然通过。

## 任务目标与已确认选择

最终产品目标是：在工作台使用现有商超、住宅小区、地铁入口、城市场景、固定三层精细楼五类模型，设置建筑外部、开阔场地中的单个 TNT 位置与当量，通过 CPU 简化模拟展示变形、钢筋应力、开裂、构件失效或局部倒塌。用户期望耗时为几十秒，允许有依据的结构简化。

当前阶段只处理三层建筑的自重与原生材料可靠性。原刚块路线暴露承载和质量映射问题后，用户已选择已有梁／分层壳参考路线。承重体系为柱板，填充墙传递压力并计入质量；恢复设计柱截面、扣除墙柱重叠质量，保留原 K 文件并记录差异。节点采用用户同意的“理想整体节点、钢筋充分锚固”假设，不能写成已核实的实际构造。

暂停前的最近授权是：修复厚度方向平衡和刚度差分，构建独立运行时，重新验证三项失败小例；小例全部通过后，再申请重跑整栋。此次交接请求不代表恢复上述任务。

## 运行边界与禁止绕过的条件

- 恢复任务后可做：原生材料代码修复、独立构建、单材料回归、受影响的小模型及专项测试。
- 真实整栋生成、真实整栋自重、TNT 工况、全量回归和重型案例均需另行说明范围与预计耗时，取得用户当次明确同意。历史授权和一般性的“继续”不能替代这项确认。
- 不跳过重力，不修改材料强度或断裂能，不降低物理验收要求；不得用割线矩阵替代真实导数并宣称切线验收通过。
- 不平均旧边界位移，不随意固定内部节点，不通过忽略接触或修改支承掩盖问题。
- 拒绝试态必须正确回滚，不能污染已提交的开裂、损伤和塑性历史；失败保留完整诊断，不自动追加整栋运行。
- 保留原运行时、原 K、已保存结果和现有未提交文件。当前工作区有大量既有修改及未跟踪文件，不 reset、clean、批量清理、提交或合并。

| 条件 | 保持值 |
|---|---:|
| 重力加速度 | 9.80665 m/s² |
| 实际相对平衡残差 | ≤ 1e-5 |
| 对角缩放对称切线判据门槛 | 1e-9 |
| 材料厚度方向应力绝对值 | ≤ 1e-8 Pa |
| 已复现材料点的混凝土参数 | E=30 GPa，ν=0.2，ft=2 MPa，fc=30 MPa |
| 钢筋屈服强度与断裂能 | fy=400 MPa，Gf=200 N/m |

测试和合并规则见 [AGENTS.md](E:/workplace/codex_mcp_k/AGENTS.md)。仅按改动范围运行专项；默认入口为轻量 smoke。不要枚举全部测试或用其他入口绕过授权。

## 已证实的原因与证据范围

### 静态重力映射产生虚假节点弯矩

旧流程先按形函数 N_i 分配重量，再把每份重量按原物理点到各节点的距离作刚性偏心，形成 `(p−x_i)×N_i mg`。这种映射与当前壳的独立位移和转角插值不相容，板内重量也会产生额外节点弯矩。

已用虚功反例复现并修正：按每个真实支承组的形函数投影计算偏心，上下楼层分别处理，保留真实外伸附件和柱轴外质量的偏心。例如节点 285 的竖向力仍为 −23775.43 N，原人为 My=13353.77 N·m 被消除；节点 284 的真实外墙偏心仍保留。相关回归通过。

这仅修正静态重力。动态偏心集中质量仍待单独核验，不能据此宣称爆炸动力计算已修好。

### PlateFiber 厚度方向局部求根未收敛却返回成功

PlateFiber 需要求厚度应变，使内部三维材料的 σ33 接近零。固定版本源码采用无界 Newton 和有限迭代次数，退出后仍可能返回成功；最后更新的缓存厚度应变与材料实际求值状态还需在修复中保证一致。

在保存的失败试态中，σ33 可达约 −0.20 MPa。保持原材料参数、提交历史和面内应变，用有界二分求厚度应变，四个试态均存在根：40–43 次求值后，残差为 4.55e-9～7.66e-9 Pa，满足原标准。证明这些局部状态有解；这是诊断试验，尚未接入壳单元内部。

### ASDConcrete3D 固定前差分跨越本构分支

当前原生切线使用固定扰动 `(ht.strainTolerance()+hc.strainTolerance())/2`。已复现材料点的扰动为 2.333333333333333e-10。在一个严格厚度平衡根处，原生 D3333 约 0.158 GPa；减小扰动并分别检查左右方向后，结果趋近 29.203 GPa。固定差分跨越分支，不能代表该点所在分支的局部导数。

因此，旧矩阵通过正定性检查只说明候选矩阵满足数值判据，不足以认证这里的真实物理导数。不能只把差分步长改小，也不能仅因 h 和 h/2 两次结果相近就接受；两次可能跨过同一分支。

独立审查已指出需覆盖的分支：主应力正负分解、加载／卸载、硬化曲线分段及容差、应力下限、拉伸度量的阈值。分支一致导数的最终算法尚未实现和验收。

完整诊断见 [自重高损伤定位报告](E:/workplace/codex_mcp_k/docs/superpowers/reports/2026-10-23-native-gravity-damage-localization.md)。

## 真实整栋保存现场

最近一次原生整栋任务只做自重，没有施加 TNT：630 个结构节点、546 个单元、2976 个自由结构自由度。父进程实际耗时约 164.956 s；worker 内部预算 150 s、父进程截止 180 s。原生调用是同步的，内部预算只能在调用间检查，因此超过 150 s 返回，但未触发 180 s 父进程截止。

最后接受的自重系数为 0.11875，实际相对残差约 9.90e-9。未完成 100% 自重，也未完成真实原 13 单元的一致边界验收。此历史接受状态不等于通过后来新增的全部材料验收。

- [冻结输入](E:/workplace/codex_mcp_k/artifacts/consistent-boundary-20261023-01/approved-prebalance-01/frozen-request.json)
- [整栋结果摘要](E:/workplace/codex_mcp_k/artifacts/consistent-boundary-20261023-01/approved-prebalance-01/reviewed-summary.json)
- [完整失败诊断](E:/workplace/codex_mcp_k/artifacts/consistent-boundary-20261023-01/approved-prebalance-01/worker/failure.json)
- [最后接受状态](E:/workplace/codex_mcp_k/artifacts/consistent-boundary-20261023-01/approved-prebalance-01/worker/accepted-state.json)

冻结请求 SHA256：`7e3e479cd2df9a8112351a2929f3ec094719a60b6a529d420cdae7456f7c346a`。

父 case 指纹：`24de7a83aa909d5380af4f6ef5a369a67ffbebd420cba69c27b7b7ade0e640eb`。

最高拉伸损伤在二层 F2.floor.0 原生单元 222，即零基索引 221，积分点 1、混凝土第 26 层，损伤约 0.9795551；该板块约 0.15×1.75 m，板厚 180 mm。它是单个材料点指标，不能解释成整栋损坏 98%。

配筋核对与参考输入一致，但顶筋相对板中面仅约 +5.029 / +21.029 mm，板顶为 +90 mm。该布置来自原输入，未经用户授权不可直接移动。上下柱为 300×300 mm、4Φ16、筋轴线 ±94 mm，连接图未断开；这些核对不等于承载力已获验证。

## 局部模型与诊断文件

已从高损伤位置提取 7 单元局部模型：原零基单元 `[221,222,228,229,333,453,498]`，包含 5 壳、2 柱、13 个结构节点、8 个切口边界节点、30 个内部自由度和 78 个质量点。这里的“13 个节点”与待验收的“13 单元子模型”不是同一概念。

边界取各唯一父节点保存的六自由度，无平均或额外内部固定。用新建材料回放加载历史至原 11.875% 自重，并非原生材料完整检查点恢复。当前版本回放约 0.297 s，位移最大差 7.1434e-9 m，钢筋应力最大差 8.7589 kPa，损伤最大差 3.6713e-4，实际残差 4.3164e-11。

该局部模型中 alpha=1 对应父模型的 11.875%，不是 100%。alpha>1 的边界延伸仅用于局部诊断，不能代替真实父模型后续边界。纠正静态重力后在相同旧边界延伸下仍失败，材料问题不能靠载荷修正消失。

| 文件 | 用途 |
|---|---|
| [saved-seven-element-patch.json](E:/workplace/codex_mcp_k/artifacts/native-gravity-damage-audit-20261023-01/saved-seven-element-patch.json) | 原局部来源、边界、质量和保存场 |
| [source-mapping-audit.json](E:/workplace/codex_mcp_k/artifacts/native-gravity-damage-audit-20261023-01/source-mapping-audit.json) | 截面、质量贡献与重力修正审计 |
| [corrected-seven-element-patch.json](E:/workplace/codex_mcp_k/artifacts/native-gravity-damage-audit-20261023-01/corrected-seven-element-patch.json) | 仅修正静态重力的局部输入 |
| [selected-history.json](E:/workplace/codex_mcp_k/artifacts/native-gravity-damage-audit-20261023-01/review-material-point/selected-history.json) | 单材料的 10 个已接受应变、应力、损伤状态 |
| [material-root-result.json](E:/workplace/codex_mcp_k/artifacts/native-gravity-damage-audit-20261023-01/review-material-point/material-root-result.json) | 四个根、应力回放与方向差分证据 |
| [probe_material_root.py](E:/workplace/codex_mcp_k/artifacts/native-gravity-damage-audit-20261023-01/review-material-point/probe_material_root.py) | 独立材料诊断脚本，不是生产修复 |
| [有效手动试态](E:/workplace/codex_mcp_k/artifacts/native-gravity-damage-audit-20261023-01/probe-Newton-1.0-0.1-instrumented-manual-nodal-assignment.json) | 复现失败材料点的有效节点赋值探针 |

不要使用文件名以 `manual.json` 或 `manual-updatedomain.json` 结束的早期节点赋值探针作力学证据。`capture_selected_history.py` 历史脚本会自行加 Parallel3D 包装，而当前生产代码已含包装；原样重跑会重复包装，必须先适配。已有 `selected-history.json` 可直接作为冻结输入。

原生 NDTest 可测试注册材料，但不能替换壳单元 getCopy 后的积分点材料。材料历史捕获与独立 NDTest 宜隔离进程；此前在同一进程中混用构建、wipe 和材料探针发生过原生退出。不要把 Python 层根搜索当作已修复原生壳材料。

## 已有实现与待接手文件

| 文件 | 当前作用 |
|---|---|
| [gravity_mapping.py](E:/workplace/codex_mcp_k/lsprepost_mcp/architecture/cpu_response/gravity_mapping.py) | `source_shape_virtual_work@1`；显式静态重力和依赖指纹 |
| [building_mapping.py](E:/workplace/codex_mcp_k/lsprepost_mcp/architecture/cpu_response/building_mapping.py) | 来源积分、载荷表、合力和力矩守恒检查 |
| [building_solver.py](E:/workplace/codex_mcp_k/lsprepost_mcp/architecture/cpu_response/building_solver.py) | 拒绝依赖已经变化的旧重力映射 |
| [native_materials.py](E:/workplace/codex_mcp_k/lsprepost_mcp/architecture/scene_blast/native_materials.py) | 单个 ASD 材料外加单位权重 Parallel3D，暴露内部三维应力；不增加刚度 |
| [native_plane_stress.py](E:/workplace/codex_mcp_k/lsprepost_mcp/architecture/scene_blast/native_plane_stress.py) | 检查所有板积分点混凝土层的 σ33 和最差位置 |
| [native_reference.py](E:/workplace/codex_mcp_k/lsprepost_mcp/architecture/scene_blast/native_reference.py) | 新重力载荷；重力、切线更新后、保持和回放的材料验收 |
| [native_subdomain.py](E:/workplace/codex_mcp_k/lsprepost_mcp/architecture/scene_blast/native_subdomain.py) | 要求父域和实时子域材料平衡，提取一致边界与状态 |
| [native_prebalance.py](E:/workplace/codex_mcp_k/lsprepost_mcp/architecture/scene_blast/native_prebalance.py) | 冻结输入、方法与运行时身份，独立 worker 和阶段诊断 |
| [runtime.py](E:/workplace/codex_mcp_k/lsprepost_mcp/architecture/cpu_response/runtime.py) | 子进程限时及运行时文件身份；默认仍是原解释器 |

旧输入缺少新重力载荷表时可走历史诊断路径，这不等于已经采用新映射。准备新运行时和新请求时必须明确所用映射，并重新生成对应指纹；不可改写历史冻结文件来假装未变。

观察包装下，三维应力和损伤响应需沿 `material → 积分点 → fiber → 层 → material → 1` 访问。只读 PlateFiber 输出会遗漏 σ33。

## 最近一次测试结果

| 范围 | 结果 | 历史耗时 |
|---|---|---:|
| 五个指定专项文件 | 42 通过，3 失败 | 10.08 s |
| 后续审查修正专项 | 10 通过 | 0.88 s |
| 根目录默认轻量 smoke | 20 通过，4 子测试通过 | 0.67 s |

原始输出：[专项](E:/workplace/codex_mcp_k/artifacts/native-gravity-damage-audit-20261023-01/targeted-tests.txt)、[审查修正专项](E:/workplace/codex_mcp_k/artifacts/native-gravity-damage-audit-20261023-01/review-followup-tests.txt)、[smoke](E:/workplace/codex_mcp_k/artifacts/native-gravity-damage-audit-20261023-01/smoke-tests.txt)。这些是已有记录，编写本交接时没有重跑。

必须重新通过的三个 node id：

```text
tests/test_scene_blast_native_reference.py::test_native_micro_reference_full_gravity_force_moment_and_current_tangent
tests/test_scene_blast_native_subdomain.py::test_micro_parent_thirteen_elements_unique_boundary_force_moment_state_and_tangent
tests/test_scene_blast_native_prebalance.py::test_micro_worker_completes_gravity_and_thirteen_element_acceptance_in_one_process
```

它们使用合成 micro 模型，不是真实三层整栋。目前最后合格自重系数为 0.45，下一目标 0.65 时，最大 |σ33|≈0.039289986 Pa，超过 1e-8 Pa。最差位置为小模型 e13、楼层 3、积分点 3、混凝土第 1 层。失败诊断保存在 [pytest-final-01](E:/workplace/codex_mcp_k/artifacts/native-gravity-damage-audit-20261023-01/pytest-final-01)。

三个失败不能改成 skip 或 xfail。早期未检查 σ33 的通过记录不能代替当前验收。

## 独立构建的实际进度

原运行时为 [原 Python 解释器](E:/workplace/codex_mcp_k/.venv/cpu-response/python.exe)：嵌入式 Python 3.12.10、OpenSeesPy 3.8.0.0，含 NumPy、pytest、psutil，无 SciPy/pip。原环境不可覆盖。根 Python 为 `E:/python/python.exe`，Python 3.13，用于工具和轻量检查，不含 OpenSees。

已完成：

- 将官方 OpenSees v3.8.0 克隆至 [源码目录](E:/workplace/codex_mcp_k/artifacts/native-runtime-20261023-01/OpenSees)，固定提交 `6e55293513192aa05c7e1205e66a5a1a1ed088c4`。本次交接核对该源码工作树无修改，尚无 C++ 修复补丁。
- 工程目录安装 CMake 3.31.6、Ninja 1.11.1.4、zstandard 0.23.0；未安装系统级工具。
- 已有 `D:/mingw64/bin/g++.exe` 和 `D:/mingw64/bin/gfortran.exe`，版本 15.2.0；有 gendef、dlltool。未发现现成 MSVC；WSL 未安装。
- CMake 路径：`E:/workplace/codex_mcp_k/artifacts/native-runtime-20261023-01/tools/cmake/data/bin/cmake.exe`。
- Ninja 路径：`E:/workplace/codex_mcp_k/artifacts/native-runtime-20261023-01/tools/bin/ninja.exe`，不是 `ninja/data/bin`。
- 查询过官方 MSYS2 包列表，准备考虑便携依赖；查询已结束，相关 Tcl/HDF5/Eigen/Zlib 包尚未下载或安装。

尚未完成：Python 3.12 开发头文件和导入库、Tcl/HDF5/Eigen/Zlib 等构建依赖、MinGW 构建兼容性验证、C++ 修复、编译、独立 Python 环境及完整源码／依赖／二进制 manifest。

OpenSees 内置 BLAS/LAPACK 可作为构建选项，是否适合当前 MinGW 路线尚未验证。不要把“有源码和编译器”写成“已能构建”。zstandard 工具安装在根 Python 3.13 的目标目录，不能直接当作原 Python 3.12 扩展复用。

需要修改的上游源码：

- [PlateFiberMaterial.cpp](E:/workplace/codex_mcp_k/artifacts/native-runtime-20261023-01/OpenSees/SRC/material/nD/PlateFiberMaterial.cpp)：`setTrialStrain`、最终状态一致性、失败返回、复制和回滚。
- [ASDConcrete3DMaterial.cpp](E:/workplace/codex_mcp_k/artifacts/native-runtime-20261023-01/OpenSees/SRC/material/nD/ASDConcrete3DMaterial.cpp)：固定差分在约 1638 行，需保持原应力和历史定义，修复导数。

原解释器下载来源与摘要保存在 [python-source.json](E:/workplace/codex_mcp_k/.venv/cpu-response/python-source.json)；依赖来源见 [wheel-sources.json](E:/workplace/codex_mcp_k/.venv/cpu-response/wheel-sources.json)。

## 恢复任务后的实施顺序

1. **先写材料回归。** 使用冻结的 10 个提交状态和四个失败试态，在原运行时保留失败证据。覆盖平面应力、全三维及凝聚切线、加载卸载、commit/revert/getCopy、非有限值和失败返回。不要为复现材料问题重新跑整栋。
2. **实现有保护的厚度求根。** 从一致的缓存状态起步，结合 Newton 与有界括区；仅最终重算 |σ33|≤1e-8 Pa 才成功。步长小、区间小或达到迭代上限都不能作为成功条件。拒绝状态不提交，求解器必须收到失败。
3. **实现分支一致导数。** 对分支边界和扰动误差作显式处理，保留应力法则、强度、断裂能和已提交历史。差分后恢复基准试态，验证 3D 与壳凝聚后方向导数；不可用另一套材料或增加刚度绕过问题。
4. **构建独立运行时。** 编译兼容性补丁与力学补丁分开，保留来源、许可证、构建命令、依赖和二进制 SHA256。明确打印实际导入的 `.pyd` 路径，防止误用旧模块。原运行时与工作台默认后端暂不替换。
5. **完成小例验收。** 单材料先通过，再跑上述三项；随后跑受影响五文件专项、保持／回滚／错误拒收测试及轻量 smoke。记录真实耗时、运行时身份与完整失败证据。
6. **独立审查后才提整栋申请。** 小例全部通过且无阻塞问题时，准备新的冻结输入、方法与运行时身份，列出唯一真实自重预平衡范围、预计耗时、截止机制与通过后的 13 单元验收，等待当次明确同意。不直接进入 TNT。

计划依据：[原生材料修复与独立运行时计划](E:/workplace/codex_mcp_k/docs/superpowers/plans/2026-10-23-native-material-runtime-repair.md)。

独立环境还需注意：嵌入式 Python 的 `._pth` 必须允许项目导入；worker 会清除继承的 PYTHONPATH，不能只依赖终端临时设置。微型 worker 测试使用 `sys.executable`，因此必须由新解释器启动 pytest，并确认请求记录的新运行时身份。`runtime_identity` 目前记录路径、大小及时间，交付 manifest 还应保存二进制内容摘要。

以下仅为恢复任务并完成构建后的三项复验命令模板。本例假定独立环境放在 `runtime` 子目录；该环境目前不存在。实际位置不同时须改为真实新解释器，不能回退到旧解释器冒充修复验证。

```powershell
Set-Location -LiteralPath 'E:/workplace/codex_mcp_k'
$nativePython = 'E:/workplace/codex_mcp_k/artifacts/native-runtime-20261023-01/runtime/python.exe'
if (-not (Test-Path -LiteralPath $nativePython)) { throw '独立运行时尚未构建' }
$caseTests = @(
  'tests/test_scene_blast_native_reference.py::test_native_micro_reference_full_gravity_force_moment_and_current_tangent'
  'tests/test_scene_blast_native_subdomain.py::test_micro_parent_thirteen_elements_unique_boundary_force_moment_state_and_tangent'
  'tests/test_scene_blast_native_prebalance.py::test_micro_worker_completes_gravity_and_thirteen_element_acceptance_in_one_process'
)
$resultDir = 'artifacts/native-runtime-20261023-01/pytest-three-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
& $nativePython -X utf8 -m pytest @caseTests -q --tb=short "--basetemp=$resultDir"
```

五文件专项范围为 `test_scene_blast_gravity_mapping.py`、`test_cpu_response_building_mapping.py`、`test_scene_blast_native_reference.py`、`test_scene_blast_native_subdomain.py`、`test_scene_blast_native_prebalance.py`，均位于 `E:/workplace/codex_mcp_k/tests`。不得扩展为全量发现。每次用新输出目录，保留既有 pytest 失败现场。

## 接手者首先应知道的状态

**工作暂停；原生补丁未写，独立运行时未构建，三项验收未通过，真实整栋与 TNT 未获新授权。** 已有证据支持优先修复材料局部数值问题，暂不支持通过减少部件数、改材料强度或调整边界解决当前阻塞。后续若材料修复后仍失败，继续分辨映射、承载路径和算法原因，不能预设剩余问题都已排除。
