# 原生材料修复与独立运行时：小模型验收通过

2026-10-24 完成用户授权的两个原生材料修复、独立运行时构建及三项 micro 验收。三项原失败小模型全部通过；受影响五文件专项和默认轻量 smoke 通过。本结论限于下列材料与小模型证据，真实整栋的自重与爆炸响应尚未验收。整栋、TNT、全量回归和重型案例均未运行。

## 保留与隔离

沿用现有 `codex/neibao` checkout，保留已有修改、历史输入及结果，未清理、提交或合并。旧运行时 `.venv/cpu-response` 保留。新增工作目录为 `artifacts/native-runtime-20261023-01/resume-01`；其中 `runtime` 是独立 Python 副本，未替换默认后端。已逐项复核 `original-runtime-manifest.json` 中的原运行时二进制 SHA256，全部相同。

## 本次已观察到的失败

| 范围 | 运行时 | 结果 | 耗时 | 证据 |
|---|---|---|---:|---|
| 原三项指定 micro node id | 原 Python 3.12.10 | 3 失败，`native_plane_stress_unbalanced` | 4.96 s | `resume-01/pytest-stock.txt` |
| 新冻结单材料回归 | 原 Python 3.12.10 | 4 失败、4 通过；失败点 D3333≈0.158 GPa，应约29.2 GPa | 1.06 s | `resume-01/materials-stock.txt` |

冻结输入已复制至 `tests/fixtures/scene_blast/native-material-history.json`，含原诊断报告摘要、十个提交状态和四个试态。回归使用单材料，不重建或求解真实建筑。

## 修复方向与边界

`ASDConcrete3DMaterial` 将固定前向数值扰动切线替换为正负谱分解的 Fréchet 导数，加上 Lubliner 度量、加载/卸载、硬化插值、塑性与损伤的链式导数。切线使用原应力计算实际选中的硬化点及加载标志，不再向材料施加固定扰动，不改变强度、断裂能或应力法则。冻结历史四点的 D3333 从旧运行时约 0.158 GPa 恢复至约 29.2 GPa，并通过独立双侧差分验证。

光滑分支上验收真实局部方向导数。连续拐点采用明确选定的单侧/广义导数，不能称为唯一经典导数；活动硬化输入恰落在容差平移造成的跳跃开关时拒绝，严格卸载时冻结的历史值仍作为常量。活动非线性度量的重复最大主应力须识别。原 Jacobi 求解器约 `1e-8 Pa` 的极小数值死区仍需作为可验证扰动尺度的限制记录，不能承诺任意小尺度机器函数微分完全一致。

`PlateFiberMaterial` 在保留提交历史的副本上执行局部 Newton 和有界括区搜索；仅最终原对象重算满足 `|σ33|≤1e-8 Pa` 才成功，厚度缓存必须与真实材料输入一致。不以步长、括区宽度或迭代上限代替应力残差。不替换原内部材料对象，保留已有 recorder Response 指针的有效性。最终检查完整三维响应和实际凝聚切线的有限性；括区同时检查种子至两端，避免非单调双根时遗漏。

同时修复 ASD 名义应力和切线回滚、Plate 五维应变复制/回滚、Parallel3D 复制缓存，以及 ShellMITC4／Domain 失败码传递。Domain 在提交节点之前预检试态并传播更新/提交失败；ASD 序列化恢复后重算 `fcft_ratio`，Plate 传输独立的 trial 与 committed 缓存。直接 C++ 回归已通过，包括冻结材料/凝聚方向导数、复制/回滚、非有限输入、有限但无根、对称端点漏括区、凝聚溢出、壳失败拒收及 MemoryChannel 序列化往返。补充回归没有分别观察旧源码 RED，不把它们报告为逐项红绿实验。

凝聚切线差分额外使用独立 Eigen 谱解从冻结提交状态重建有效应力，检查主应力符号、加载标志、硬化分段及 floor 分支。四个步长共 80 个差分模板的两侧分支均相同；`h=1e-7、1e-8` 的最大相对差约 0.0361%，正式断言同时要求两档、双侧误差小于 0.2%。更小步长下差分应力接近本构/求根的绝对数值误差，误差增大，保留于 `root-scan-02.txt`。这项独立重建证据适用于当前 `cdf=eta=0、nct=ncc=0` 冻结材料，不能外推任意参数。

同进程回归曾因局部壳 Domain 销毁后遗留的全局 active-element 指针崩溃；GDB 栈记录于 `native-all-crash-backtrace-01.txt`。仅修正测试夹具的上下文恢复，之后全部模式同进程通过。旧失败/诊断日志均保留，最终依据是 `native-materials-all-03.txt`，不能把早期 `native-materials-01/summary.json` 的 root 失败改写为通过。

## 工具链状态

源码固定于官方 OpenSees v3.8.0 提交 `6e55293513192aa05c7e1205e66a5a1a1ed088c4`。使用已有 MinGW GCC/Fortran 15.2.0 和项目内 CMake/Ninja，不安装系统级工具。

便携依赖已下载并记录 URL/SHA256：Python 3.12.10 官方头文件、MSYS2 Tcl/Zlib/Eigen 和官方 HDF5 1.14.6 源码。HDF5 已构建；禁用 MinGW 缺少宏支持的非标准 Float16，启用 MPCO recorder 所需 HL。头less Python 构建仅要求 Tcl，不要求 Tk。CMake 的两套 Python 查找均已约束为独立 Python 3.12.10，避免误选已有 conda 3.13。

源码构建与链接完成，最终增量构建显示 `ninja: no work to do`。额外兼容修复包括 TetGen 的 Windows 64 位指针转换，以及 GNU Fortran 与 Windows C++ 入口的 35 项经实际归档符号核对的链接别名；没有使用截断指针的 `-fpermissive` 或替换数学实现。

独立解释器为 `artifacts/native-runtime-20261023-01/resume-01/runtime/python.exe`，实际导入 `runtime/Lib/site-packages/openseespywin/opensees.pyd`，版本 3.8.0，SHA256：

```text
0831c83756d777f4bdf765896193a5e55714037f2cba7ac70a5b71da43f0c81d
```

`runtime-manifest.json` 记录原运行时不变、源码提交、三组补丁、构建输入、原生回归程序及依赖二进制摘要，并核对已导入模块与本次构建 DLL 一致。`patches`、`licenses`、下载/符号映射清单和构建脚本均保留在新增目录中。复现入口见 [REPRODUCE.md](../../../artifacts/native-runtime-20261023-01/resume-01/REPRODUCE.md)。

## 本次验收证据

| 范围 | 新运行时结果 | 耗时 | `resume-01` 内证据 |
|---|---|---:|---|
| 冻结单材料与一般加载/卸载方向导数 | 8 通过 | 1.54 s | `materials-new-01.txt` |
| 直接 C++ 七组专项，同进程 | 全部通过，退出码 0 | — | `native-materials-all-03.txt` |
| 原三项指定 micro node id | 3 通过 | 4.86 s | `pytest-three-new-01.txt` |
| 受影响五文件专项 | 45 通过 | 8.92 s | `pytest-five-new-01.txt` |
| 根目录默认轻量 smoke | 20 通过 | 4.29 s | `pytest-smoke-new-01.txt` |

45 项专项来自 `test_scene_blast_gravity_mapping.py`、`test_cpu_response_building_mapping.py`、`test_scene_blast_native_reference.py`、`test_scene_blast_native_subdomain.py`、`test_scene_blast_native_prebalance.py`，包含拒收、回滚、保持及未来材料路径验证；它包含三项指定 micro，不能把两次运行相加声称是独立测试总数。所有 pytest 运行使用新增独立输出目录。

三项指定小模型的实测量：

| 小模型 | 自重载荷因子 | 物理相对残差 | 力/力矩平衡相对误差 | 当前切线 |
|---|---:|---:|---|---|
| 原生父模型 | 1.0 | 5.322e-11 | 1.956e-11 / 2.946e-12 | 正定，原门槛 1e-9 |
| 13 单元子域 | 1.0 | 6.380e-11 | 2.807e-11 / 3.042e-12 | 正定，原门槛 1e-9 |
| 独立 worker 同进程父模型→子域 | 1.0 | 父 5.322e-11，子 6.380e-11 | 与上述量级一致 | 父/子均正定；自动重启 0 |

子域接口相对残差约 1.030e-11。保留 `g=9.80665`、`|σ33|≤1e-8 Pa`、物理残差 `≤1e-5` 及切线门槛 `1e-9`，未降低验收阈值或修改材料强度、Gf。详细输出位于 `pytest-three-new-01` 子目录。

最终限定范围的独立只读复核未发现阻塞问题，确认 Domain 拒收、ASD 参数往返和 Plate 两套缓存传输问题已闭合。Domain 预检覆盖材料试态拒收，不承诺任意其他元素在后续 `commitState()` 内部失败时具有全域原子回滚。本次可以交付小模型已验收的独立运行时；真实整栋、TNT、全量及重型测试仍等待用户另行明确授权。

## 演示备选（未实施）

若当前非线性材料路线不能满足演示所需的稳定性或耗时，可另行采用简化爆压时程、构件级等效单自由度/降阶动力响应、失效后的刚体运动，串联冲击、变形、失效和倒塌画面。构件动力响应可参考 [UFC 3-340-02](https://www.wbdg.org/ffc/army-coe/ufc/ufc-3-340-02)；整体倒塌顺序、裂缝纹理和碎屑动画需要单独界定，不能因画面连续就称为完整高保真爆炸求解。本次尚未切换路线或运行爆炸工况。
