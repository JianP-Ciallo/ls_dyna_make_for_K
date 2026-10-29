# 固定建筑 CPU 响应：单柱、单板验证与后续扩展实施计划

> **方向修订（2026-10-22）：** 此计划继续保留原实施与计算证据；用户目前的产品目标已改为五类建筑来源的场景式 CPU 爆炸模拟，并要求损伤/失效或局部倒塌及数十秒目标。详见[新设计](../specs/2026-10-22-scene-cpu-blast-simulator-design.md)。不得再把本计划的小算例界面当作产品交付终点；新技术路线尚待验证，旧真实收敛矩阵仍暂停，不能自动运行。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 按用户约定由主会话执行，仅在必要的独立审查中少量使用子智能体。

**Goal:** 先交付有真实数值结果的单柱、单板小算例，测量 CPU 耗时并回放变形与钢筋应力，达到门槛后再扩展到现有三层建筑。

**Architecture:** 复用 OpenSeesPy 的梁柱纤维截面和分层配筋壳，放在独立 CPU 工作进程中；主工作台负责输入、快照、任务和结果展示。S0—S2 小算例通过后，用户继续授权柱板体系的 S3c 连接验证与 S4 三层映射；真实整栋验证仍按项目测试约定执行。

**Tech Stack:** Python、候选 Python 3.12 x64 / OpenSeesPy 3.8.0.0、NumPy、psutil；现有 HTTP 服务、Three.js 和原生 JavaScript。实际依赖组合通过任务 1 后锁定，主工作台不强制导入求解内核。

**Spec:** [修订设计 v2](../specs/2026-10-22-fixed-building-cpu-response-design.md)。执行时同时阅读根目录 AGENTS.md。

**Status:** 2026-10-22：小算例完整时窗门槛通过；三层原生连接、配筋与质量映射已核验，用户选择的规整柱板参考输入已封存。经当次明确同意，真实整栋首例完成150ms/1500步，父进程97.947s，结果和实际云图已保存。整栋收敛、工程准确性及网页整栋功能尚未验收。原清单及历史失败保留，最新状态见“真实整栋首试结果”。

整栋网格/时间步长验证已列入[五例离线收敛计划](2026-10-22-building-cpu-convergence.md)，但用户随后明确暂不运行，转为先统一各工作台风格与颜色。当前五例均未运行，不沿用上一例授权；后续恢复验证仍需当次确认，全部通过才开放整栋求解界面。

## Global Constraints

- 初轮交付 S0—S2；用户继续授权后推进柱板小装配与三层映射。完整建筑计算仍须完成对应数值与几何核验。
- 先弹性验证；未通过材料及构件验证的非线性能力保持关闭，不能把弹性外推应力称为屈服或损伤结果。
- 首轮资源上限：每个真实小算例墙钟 30 s，单条验证/性能命令总预算 180 s；最多 1 个计算工作进程，最大 10,000 个实际积分步、500 个动画帧、5,000 个曲线样本。
- 全量回归、真实重型和慢速模型生成检查必须先说明具体范围与预计耗时，取得用户当次明确同意；技术预算不替代授权。
- 默认 smoke 不新增真实求解和性能矩阵；不运行 LS-DYNA、原有三个重型案例或三层建筑来验收小算例。
- 保留用户已有脏改动、暂存内容、工作树和测试证据；不清理工作区。原文档回合不实施；用户后续已明确授权 S0—S2 开发。本次未提交或合并。
- 原 K 页面、严格 pressure config 和导出语义继续有效；CPU 参数独立保存，打开页面不触发计算。
- 生产前端放在 `lsprepost_mcp/web/static/`；不修改归档 React 原型或复制老师网站源码、品牌和模型。

## Review Focus

1. 本机解释器能安装包但不能加载二进制内核：能力显示 unavailable，旧页面可用；任务 1、7 验证。
2. 钢筋方向、层位置、质量或记录器量混淆：单柱/单板旋转、截面和层质量检查后才标为钢筋轴向应力；任务 2—5 验证。
3. 应力峰值落在两帧之间：内部步计算峰值，回放抽稀不改变摘要；任务 5、8 验证。
4. 取消、重启、超时或不收敛留下部分文件：不得成为 completed，保留诊断及准确状态；任务 5—7 验证。
5. 改工况、改参数或切页后旧响应返回：结果绑定不可变快照和来源，前端忽略过期响应；任务 7、8 验证。

## 文件与接口总图

以下路径均相对仓库根目录，列示本计划的实现范围；实际可用能力和阶段缺口见执行记录。显式原生探针另实现于 `.../native_probes.py`，安装入口为 `scripts/setup_cpu_response.py`。

| 文件 | 职责 |
| --- | --- |
| `lsprepost_mcp/architecture/cpu_response/__init__.py`、`contracts.py` | 延迟加载入口、输入/输出与预算合同、校验和规范化指纹 |
| `.../runtime.py`、`worker.py`、`requirements-win-py312.txt` | 环境探针、受控子进程入口、实际验证后的依赖锁 |
| `.../benchmarks.py`、`loads.py` | 独立小算例定义、压力方向和一致节点载荷 |
| `.../column.py`、`panel.py` | 梁柱纤维、分层配筋壳建模与采样映射 |
| `.../backend_opensees.py`、`results.py` | 积分与内核适配、原始钢筋结果提取、峰值和产物 |
| `.../benchmarking.py`、`scripts/benchmark_cpu_response.py` | 性能采样、预算及报告 CLI |
| `.../service.py`、`jobs.py`、`api.py` | 不可变配置和快照、单工作进程调度、路径式 HTTP API |
| `lsprepost_mcp/web/static/fixed_building_response.html/.css/.js` | 小算例 CPU 页及状态交互 |
| `lsprepost_mcp/web/static/fixed_building_response_view.js`、`fixed_building_response_charts.js` | 梁/壳回放和应力字段、曲线与共用游标 |
| `lsprepost_mcp/web/fixed_building_workspace.py` | CPU 路由/静态资源接入、正确 MIME 与关闭任务 |
| `tests/fixtures/cpu_response/` | 来源明确的输入、解析参考、独立配筋板参考和保存回放结果 |
| `tests/test_cpu_response_*.py`、`tests/browser/fixed_building_response.cjs` | 下述专项；不依赖真实整栋模型 |

`.../` 均指 `lsprepost_mcp/architecture/cpu_response/`。

合同在任务 2 定义并由后续任务复用：

- `CaseSource`：`kind` 为 `benchmark` 或 `pressure_scene`，加 `id/revision/fingerprint`；近期只开放 benchmark。该指纹绑定不可变的来源定义；网格、静/动力及 CPU 参数修改属于 profile，另产生 input_fingerprint，不能与来源指纹混淆。
- `CaseSpec`：来源、几何、材料、配筋、荷载、分析、预算和假设；内部一律 SI。
- `ModelMap`：求解节点/单元、局部轴、受载面、截面/纤维/配筋层采样标识、显示映射与质量账目。
- `StepSample`：时间、节点位移/速度/加速度、反力、带采样标识的钢筋轴向应力/应变；没有字段用不支持标志，不填零。
- `CaseResult`：`schema_version/source/input_fingerprint/mesh/frames/curves/peaks/diagnostics/provenance`，字段与单位显式列出。
- `RunControl`：取消标志、单调时钟截止时间、实际步数上限；仅在进程内部使用，不从 HTTP 接收可执行对象。

`RuntimeInfo/CapabilityReport` 在 runtime.py 定义，`LoadMap` 在 contracts.py 定义，`ArtifactIndex` 在 results.py 定义，`BenchmarkReport` 在 benchmarking.py 定义。任务 3、4 先完成静力构件与采样；任务 5 统一加入动力积分和动态收敛，避免前置任务依赖尚未实现的内核。

## 近期实施任务：S0—S2

### Task 1：验证隔离运行环境与钢筋结果读取（S0）

**Files:** 新增 `runtime.py`、`worker.py`、`requirements-win-py312.txt`、`tests/test_cpu_response_runtime.py`、`tests/cpu_response_probes.py`。

**Interfaces:** `inspect_runtime(python_executable: str) -> RuntimeInfo`；`probe_backend() -> CapabilityReport`。能力包括 `column_fiber_stress`、`panel_rebar_stress`、`sparse_solver`，并返回具体版本和未支持原因。

- [ ] 写失败测试：模拟依赖缺失、导入异常、工作进程非零退出；断言主进程仍可导入模块，能力为 unavailable，错误不被包装成成功。
- [ ] 写父进程看护测试：受控假 worker 不响应协作取消或模拟阻塞，父进程仍按墙钟截止终止并回收本次子进程；不匹配 PID/句柄不得终止。Windows 无可见控制台启动，不影响无关 Python 或主服务。
- [ ] 运行 `python -m pytest tests/test_cpu_response_runtime.py -q`，确认测试因新接口缺失失败；该测试只用受控假进程，不启动真实求解。
- [ ] 实现延迟导入与服务端受控入口；在项目内隔离环境检查 Python 3.12 x64 / OpenSeesPy 3.8.0.0 候选组合。实际解释器与 wheel 版本/哈希写入锁文件，原工作台 Python 不改动。
- [ ] 显式运行两个极小探针：梁截面一个非零应变状态；板壳一个已知曲率/膜应变状态。检查 ShellMITC4/LayeredShell/PlateRebar 材料复制、0°/90° 方向及记录器的真实输出，保存命令与响应。稀疏求解器以 UmfPack 为首选，实际能力不支持时报告失败，不默默切成稠密整栋求解。
- [ ] 重跑专项并保存环境探针 JSON，含解释器/内核/依赖身份，供 capabilities 只读使用；无匹配记录为未验证，GET 不启动探针。无法取得正确配筋层轴向应力时停止对应能力开发，不以合力、等效应力或空数组代替。此时没有资格宣称单板钢筋应力已支持。

### Task 2：冻结小算例合同、参数与载荷（S1）

**Files:** 新增 `contracts.py`、`benchmarks.py`、`loads.py`、`tests/fixtures/cpu_response/column-v1.json`、`panel-v1.json`、`tests/test_cpu_response_contracts.py`、`tests/test_cpu_response_loads.py`。

**Interfaces:** `normalize_case(payload: dict) -> CaseSpec`；`make_benchmark(case_id: str, refinement: str = 'base') -> CaseSpec`；`map_pressure(model: ModelMap, load: dict) -> LoadMap`。`LoadMap` 含 SI 压力、时间插值和一致节点荷载，不只是节点力总和。

- [ ] 写失败测试：未知字段、NaN/Inf、非法单位、保护层越界、负/重复时间、旧曲线不支持的负压、相同来源 ID/revision 对应不同原始定义、超过预算均拒绝；同一规范化输入指纹稳定，合法 profile 修改只改变 input_fingerprint。
- [ ] 写守恒测试：1 kPa=1000 Pa、1 ms=0.001 s；柱/板网格细化不改变合力、力矩和冲量；翻转受载法线改变力向；不能把柱面均布荷载全部压到柱顶。
- [ ] 运行 `python -m pytest tests/test_cpu_response_contracts.py tests/test_cpu_response_loads.py -q`，确认失败后按设计第 4.3—4.5 节实现。冻结 3 m/0.30 m 柱、4Φ16、40 mm 保护层；2 m/0.15 m 板、上下双向 Φ10@200、25 mm 保护层；材料为明确标识的纯数值参数，不伪称 C30 实际材料。
- [ ] 将动态折线 `[0,0],[1,10],[10,0],[150,0]`（ms/kPa）、0.1 ms 基准时间步、0.05 ms 对照和 150 ms 时长写入夹具。静力、动力分别定义，不用静力解析式直接校验动态峰值。源输入不适用时生成新版本，不覆盖已冻结算例。
- [ ] 重跑两文件专项；记录钢筋中心坐标、面积、配筋层顺序及质量算法。组合截面扣除钢筋占用的混凝土；板层总厚度和实际配筋位置必须同时成立。按设计显式集总节点平移质量，原生质量关闭；独立核对柱 μ、板 mA、约束前总质量及固定/自由份额，避免全局质量比例错误仍数值收敛。

### Task 3：单柱弹性计算、钢筋应力与数值对照（S1）

**Files:** 新增 `column.py`、`tests/test_cpu_response_column.py`、`tests/fixtures/cpu_response/column-reference.json`；扩展 `backend_opensees.py` 的柱模型入口。

**Interfaces:** `build_column(ops: object, case: CaseSpec) -> ModelMap`；`read_column_sample(ops: object, model: ModelMap, time_s: float) -> StepSample`。内核对象只在工作进程传入，避免模块导入就建立 OpenSees 全局模型。

- [ ] 写弹性对照测试：组合截面 EI 下的悬臂均布荷载，顶位移 `qL⁴/(8EI)`、底反力和底弯矩；纵筋应力与同位置截面曲率的弹性恢复对照，非零量误差 ≤2%。零位移容差固定为 1e-10 m，零应力为 1 Pa，零合力为 1e-6 N；不得用放大零量相对误差替代。
- [ ] 写钢筋采样与方向测试：四根纵筋有唯一 ID、截面局部坐标和积分点位置；反向弯曲拉压互换，旋转模型与荷载后物理结果等价；不把每根纵筋都赋为同一个最大应力。
- [ ] 在受支持内核解释器下运行 `python -m pytest tests/test_cpu_response_column.py -q`，确认新功能失败，然后实现 4 段纤维梁柱弹性基线、底部固定和一致节点加载。截面积分默认每段 3 点，混凝土纤维初始 10×10，细化时保留钢筋真实位置。
- [ ] 显式做 4/8/16 段、10×10/20×20 纤维的静力检查；0.1/0.05 ms 动态对照在任务 5 统一积分完成后执行。从积分点外推到底部的值必须标明为恢复量，不能把离底部有距离的积分点应力直接当底部精确值。
- [ ] 以独立计算的组合截面 EI 与线质量 μ，检查第一弯曲频率 `ω1=1.87510407²√(EI/(μL⁴))`；空间细化后误差目标 ≤2%，识别对应弯曲模态，不能把轴向/扭转模态误当对照。
- [ ] 保存输入、原始曲线、钢筋应力/应变、反力、误差与诊断。Concrete02/Steel02 的非线性材料/轴弯构件验证单列后续任务；本次结果明确为弹性，不据此输出屈服或破坏。

### Task 4：单板分层配筋、挠度和钢筋层应力（S1）

**Files:** 新增 `panel.py`、`tests/test_cpu_response_panel.py`、`tests/fixtures/cpu_response/panel-reference.json`、`panel-layer-reference.json`；扩展内核的板模型入口。

**Interfaces:** `build_panel(ops: object, case: CaseSpec) -> ModelMap`；`read_panel_sample(ops: object, model: ModelMap, time_s: float) -> StepSample`。钢筋字段必须包含 element/积分点、上/下、局部方向、层深度、轴向应力和应变。

- [ ] 写边界与弹性基线测试：四边法向简支、最少面内约束；裸弹性方板按同一边界 Navier 参考检查中心挠度，细化目标 ≤5%。先验证参考级数自身收敛，并注明厚跨比与剪切差异。
- [ ] 写配筋层测试：等曲率状态下各层应变方向/符号/深度正确，钢筋轴向应力与 `Es·εs` 一致；0°/90° 及整体旋转等价；PlateRebar 返回的多分量应力先投影到该层轴向，不能固定取一个全局分量。
- [ ] 写质量/刚度测试：四层钢筋的等效厚度、实际中心位置、混凝土替代体积和总质量守恒；配筋板用独立积分的 D11/D22/D12/D66、B=0 及正交层合板 Navier 级数作为静力参考，中心挠度目标差异 ≤5%，禁止直接套用裸板系数。参考数据记录算法、版本、单位、级数截断误差及剪切差异，不由被测求解代码自行生成“标准答案”。
- [ ] 检查裸简支板的一阶频率 `ω11=π²√(D/mA)(1/a²+1/b²)`，细化目标误差 ≤5%；板面质量与总质量单独核对，并说明壳剪切及忽略厚度旋转惯性的差异。
- [ ] 在受支持解释器下运行 `python -m pytest tests/test_cpu_response_panel.py -q` 确认失败后，实现已通过任务 1 的分层壳组合；首轮混凝土和钢筋为弹性。先运行 4×4、8×8、16×16 静力网格对照；时间步对照在任务 5 执行，每组遵守 180 s 总预算，不自动扩大。
- [ ] 保存中心挠度、双向上下层应力、反力及原始积分点位置。结果说明为配筋层代表应力，不宣称每根钢筋的局部弯曲、滑移或断裂已经求出。

### Task 5：统一积分、结果合同、峰值与失败语义（S1）

**Files:** 新增/扩展 `backend_opensees.py`、`results.py`、`tests/test_cpu_response_solver.py`、`tests/test_cpu_response_results.py`。

**Interfaces:** `solve_case(case: CaseSpec, control: RunControl) -> CaseResult`；`write_artifacts(result: CaseResult, result_dir: Path) -> ArtifactIndex`。Path 由服务端或本地受控 CLI 产生，HTTP 不提供该参数。

- [ ] 写零荷载、无阻尼自由振动、压力拐点、结果单位、采样位置与稀疏时间轴测试；自由振动采用非零初始状态或加载后卸载的非零状态，同时检验绝对周期和能量，不能零响应空通过。完整步上出现的峰值在抽成 500 帧后仍保留原值和发生时间。输出应力采用 Pa 存储，展示再转 MPa。
- [ ] 写失败测试：迭代不收敛、取消、步数超限、进程退出、结果非有限数、时间不递增、文件缺失或哈希错误；部分结果不得形成 completed。
- [ ] 运行 `python -m pytest tests/test_cpu_response_solver.py tests/test_cpu_response_results.py -q`，确认失败后，实现 Newmark γ=1/2、β=1/4 适配。压力拐点强制落步；每步最多 30 次迭代，失败最多减半 4 次，先恢复最后已提交状态，实际接受步/重试均计入时间与预算。
- [ ] 将收敛准则、绝对/相对尺度、实际步长与每次回退写入诊断；不可用自动改粗步长掩盖超时。解算、内部峰值、曲线与帧采样分开，显示倍率不进入应力或峰值计算。
- [ ] 重跑两文件专项和对应柱/板动态小样本，分别完成 0.1/0.05 ms 时间步与空间细化检查，按设计的峰值/周期门槛报告收敛。产出 JSON 摘要、CSV 曲线、网格与采样场、产物清单和哈希。无阻尼弹性检查能量；未来有塑性时改查外功与耗散账目。

### Task 6：CPU 性能记录与小样本报告（S2）

**Files:** 新增 `benchmarking.py`、`scripts/benchmark_cpu_response.py`、`tests/test_cpu_response_benchmarking.py`；运行产物写入新的 `artifacts/cpu-response-small-cases-<run-id>/`，不清理旧目录。

**Interfaces:** `measure_case(case: CaseSpec, repeats: int, control: RunControl) -> BenchmarkReport`；CLI 固定选项 `--case column|panel`、`--matrix baseline|convergence`、`--wall-budget-s 180`、`--case-timeout-s 30`、`--output-dir`，不接受任意 Python 代码或远程输入。

- [ ] 写假时钟/假进程测试：排队、构建、内核推进、应力读取、写盘分别计时，区间不重叠；CPU 时间和墙钟时间分别报告。一次冷启动包含启动/导入，三次预热实验在同一 worker 内逐次清空模型后重新建模求解，不复用上一次状态；中位数/范围正确，未完成次数不能补零，worker 复用方式入报告。
- [ ] 写预算测试：单例 30 s、整条命令 180 s、10,000 步上限生效；180 s 覆盖启动/导入、预热、三次重复、提取和写盘，超限后无后续矩阵。父进程看护可打断阻塞的原生调用，预留进程回收余量且终止/回收时间单列；Windows 工作进程退出后本次 RSS 峰值仍保留，原生内存采用 psutil 采样并标明采样周期。
- [ ] 运行 `python -m pytest tests/test_cpu_response_benchmarking.py -q`，确认失败后实现报告。为本次 worker 固定并记录线程配置，不修改全局环境；报告计算规模、内核版本及模型假设。
- [ ] 在范围已说明的轻量阶段显式运行两个独立命令：`python scripts/benchmark_cpu_response.py --case column --matrix baseline --wall-budget-s 180 --case-timeout-s 30 --output-dir artifacts/cpu-response-small-cases-<run-id>/column`，以及同选项的 panel 命令。报告 180 s 是上限，不是预计实际用时；超时后先分析瓶颈，再决定范围，不自动追加整栋测试。
- [ ] 输出 `report.json`、`report.md`、保存回放结果及输入哈希。报告列明成功/失败/超时/未运行、参考误差、求解与渲染分别耗时；不得据此承诺三层楼的速度。网格/步长收敛矩阵另用 `--matrix convergence` 显式分组执行，不加入默认 smoke。

### Task 7：最小任务、快照与 HTTP 接口（S2）

**Files:** 新增 `service.py`、`jobs.py`、`api.py`、`tests/test_cpu_response_service.py`、`tests/test_cpu_response_api.py`；小范围修改 `lsprepost_mcp/web/fixed_building_workspace.py`。

**Interfaces:** `CpuResponseService.create_profile(payload: dict) -> dict`；`preflight(source: CaseSource, profile_id: str) -> dict`；`start_run(source: CaseSource, profile_id: str, input_fingerprint: str, client_request_id: str) -> dict`；`cancel(run_id: str) -> dict`；`handle_cpu_response_request(service, method: str, path: str, payload: dict | None) -> tuple`。

- [ ] 写失败测试：同 ID/revision 的内容冲突、输入指纹过期、来源和 run 不匹配、重复提交、旧 source 被覆盖后快照仍可重放、路径穿越、未知字段和越预算拒绝；近期 pressure_scene 返回明确的阶段未开放错误。
- [ ] 写状态测试：queued/running/completed/failed/cancelled/interrupted；取消后晚到的结果不能发布，重启不能把 running 改成 completed；模板或内核不可用时 capabilities 只读且不触发模型生成。
- [ ] 将任务 1 的父进程看护用于服务 worker；取消/超时不依赖 analyze() 主动返回。验证阻塞 worker 被回收，任务正确结束，后续队列可执行且没有成功产物发布。
- [ ] 运行 `python -m pytest tests/test_cpu_response_service.py tests/test_cpu_response_api.py -q`，确认失败后按设计第 7 节接入路径式 API。profiles 不可变，runs 原子冻结全部规范化输入、来源与环境身份，单工作进程执行；任务 1 的工作进程探针和正常 API GET 分离。
- [ ] 将 CPU 路由分发置于原 pressure API 的具体匹配前；保持原前缀、本地来源与无 API 查询参数规则。对 JSON/CSV/PNG/ZIP 明确 MIME 和下载名；HEAD 不返回实体，不能沿用全部 bytes 都是 ZIP 的逻辑。
- [ ] 重跑新增专项和相关既有压力/工作区 API 小样本。测试使用临时目录、小夹具和假 worker；真实内核的端到端调用另列一个单柱、一个单板轻量 node id，不把真实求解塞进全部 API 测试。

### Task 8：单柱、单板最小回放页与首次交付（S2）

**Files:** 新增 `fixed_building_response.html/.css/.js`、`fixed_building_response_view.js`、`fixed_building_response_charts.js`、`tests/browser/fixed_building_response.cjs`、`tests/test_cpu_response_web.py`；修改 `fixed_building_workspace.py` 的路由/静态白名单及两个旧页面的导航。

**Interfaces:** `ResponseView.setResult(result)`、`setFrame(index)`、`setField(fieldId)`、`setScale(factor)`；`ResponseCharts.setResult(result)`、`setCursor(timeS)`。前端统一用 `source + input_fingerprint + run_id` 丢弃旧异步返回。

- [ ] 写保存结果回放测试：单柱形函数与板壳节点产生不同的实际变形；钢筋按纤维或上/下、X/Y 配筋层切换；单位、符号、色标、原始积分点与未平滑峰值可查询，倍率不改数值。
- [ ] 写交互测试：空/排队/运行/失败/取消/完成状态、显式开始与停止、历史结果、时间轴和曲线同步；请求被延迟后切换来源、字段或 run，旧响应不能覆盖新选择。三层入口暂不可计算，不能伪造建筑结果。
- [ ] 运行 `python -m pytest tests/test_cpu_response_web.py -q` 确认失败后实现页面。S2 页内默认单柱/单板，三层显示完成映射后开放；压力、位移、钢筋应力三种字段各自标明来源，支持范围来自 capabilities。
- [ ] 浏览器专项以保存结果夹具为主，测试脚本参数固定为 `node tests/browser/fixed_building_response.cjs <base-url> <artifact-dir>`；真实“点击计算”仅对单柱、单板各一次并保留 API 任务与结果证据。浏览器脚本总预算与求解预算分别报告；本轮编计划时不启动这些命令。
- [ ] 做必要独立审查，修复阻塞后交付：小算例输入、解析/收敛证据、实测耗时、位移与钢筋应力截图/回放、局限说明。没有已验证非线性结果时页面明确标为弹性。

## 近期专项命令与证据边界

实施开始先运行 `powershell -NoProfile -File scripts/run_test_matrix.ps1 -List`，只查看范围。各任务按其列出的文件或 node id 执行，真实内核专项使用任务 1 验证的解释器；命令中的 `python` 是该解释器占位，不得假定主 Python 已具备求解依赖。

新增纯合同/载荷/结果/API 与保存回放专项可由主工作台环境执行。真实内核的 column、panel、solver 专项必须单独报告所用解释器和实际运行数；依赖缺失产生的 skip 不构成数值验证通过。

受影响的既有专项为 `tests/test_architecture_pressure.py`、`tests/test_fixed_building_workspace.py`、`tests/test_fixed_building_web_integration.py` 以及 `tests/browser/fixed_building_workspace.cjs`；执行前逐项检查范围，选择轻量夹具，不通过默认 smoke 推断旧 K 链路已验收。

原计划回合只做文档检查；用户后续授权后的实际执行记录如下。

## 执行记录

### 已实现及验证的范围

| 任务 | 实际状态与证据 |
| --- | --- |
| 1 环境 | 独立 Python 3.12.10 x64、OpenSeesPy 包 3.8.0.0（原生版本 3.8.0）；柱纤维与板 0°/90° 配筋层极小探针通过。安装脚本固定官方 Python SHA256 和 PyPI wheel 哈希，`--verify-only` 已执行；未另建一个干净环境重复完整安装。GET 不启动探针，环境文件变化后能力失效。 |
| 2 合同与载荷 | SI、闭合字段、不可变来源与输入指纹、压力插值/冲量和一致节点载荷专项通过。 |
| 3 单柱 | 4/8/16 段、纤维密度 10/20 的静力对照通过；组合 EI、质量、第一频率、非零自由振动周期、正反弯曲及正交端弯矩应力检查通过。 |
| 4 单板 | 4×4/8×8/16×16 静力对照；独立连续厚度 D/B/质量、Navier 截断、已知双向曲率层应变、上下层符号和裸板频率通过。固定参考几何的方向检查已覆盖，任意旋转几何入口未实现。 |
| 5 内核与结果 | Newmark 平均加速度法；原生纤维或经原生核对的弹性层恢复；峰值与能量、独立曲线/帧抽样、JSON/CSV/清单及哈希。续轮完整时窗的空间及时间收敛门槛通过；取消、超时和异常结果不发布成功，非线性保持关闭。 |
| 6 测量 | 两例各一次首次运行和三次同 worker 清空重建的预热运行；另存静力、动力细化及超时证据。父进程观察首次结束含启动耗时（20 ms 采样误差），RSS 同样按 20 ms 采样。 |
| 7 服务 | 单工作进程队列、不可变 profile/input 快照、代码和环境身份、幂等提交、取消、重启中断恢复、来源绑定、产物校验及专用 MIME。 |
| 8 页面 | 三个页签互通，单柱/单板真实变形与钢筋应力回放、曲线共用时间轴、压力输入着色、截图/下载/历史地址、未保存工况提示。浏览器专项通过；三层计算保持关闭。 |

弹性步进不做未验证的非线性回退：任何原生非零返回立即失败。非零 SP 位移探针及静力使用 Newton。续轮的已知均匀线弹性瞬态仅在实际 dt 相同时复用切线，压力拐点缩步及恢复常规步均重建；细板完整动态基底加速另见续轮记录。非线性验证与重试仍归 S3。

### 初轮数值对照和失败证据（保留）

独立参考算法在 `tests/test_cpu_response_references.py`，冻结数值在 `tests/fixtures/cpu_response/column-reference.json`、`panel-reference.json`、`panel-layer-reference.json`。参考不读取生产层构造或求解器刚度。配筋板连续积分的四层中心为 ±0.045 m（X）、±0.035 m（Y）；混凝土扣除相同配筋等效体积，B=0。Navier 采用奇数项 1—99，并与 1—49 截断对照；壳包含剪切，薄板参考不包含剪切。

| 对照 | 测得结果 |
| --- | --- |
| 单柱静力，16 段、纤维密度 20 | 顶位移 1.404532 mm；独立组合截面参考 1.401549 mm，差异 0.213% |
| 配筋板静力，16×16 | 中心挠度 0.075217 mm；独立 Navier 参考 0.073569 mm，差异 2.239%（含薄板/壳剪切差异） |
| 柱时间步 0.1→0.05 ms，8 段、150 ms | 位移峰值变化约 0.003%，钢筋绝对峰值约 0.964%，通过 2% 变化门槛 |
| 板时间步 0.1→0.05 ms，8×8、15 ms | 位移峰值变化约 0.070%，钢筋峰值约 0.337%；峰时差不超过一个较粗步长 |
| 柱空间 8→16，150 ms | 位移峰值约 0.50%，钢筋峰值约 2.53%，钢筋项未通过 2% 门槛；全局位移峰时受多周期近等峰影响，不宣称该峰时收敛 |
| 板空间 8×8→16×16，15 ms | 位移峰值约 1.08%，钢筋峰值约 4.17%，钢筋项未通过 2% 门槛 |
| 板 16×16，完整 150 ms | 30 s 超时，随后变体未运行；没有写成通过 |

初轮 15 ms 是明确新增的**早期荷载及峰值观察窗口**，不是完整 150 ms 动态收敛验收的替代。彼时细网格后期峰值未验证，页面提示收敛待完善。续轮另完成完整时窗验收，数据见下；两轮证据均保留，小算例通过仍不等于整栋数值验收。

### CPU 与页面实测

最新一次正式四轮报告为 `artifacts/cpu-response-small-cases-20261022-03/{column,panel}`。预热指同一 worker 内清空并重建，耗时包含提取和写盘，不能当作每次新进程的端到端耗时。

| 测量 | 单柱 4 段 | 单板 4×4 |
| --- | --- | --- |
| 首次含进程启动至下一轮开始，父进程观测 | 1.105 s | 3.964 s |
| 三次预热总耗时中位数 | 0.355 s | 6.683 s |
| 三次预热总耗时范围 | 0.353—0.366 s | 6.574—6.934 s |
| 内核推进中位数 | 0.076 s | 3.022 s |
| 四轮进程 RSS 采样峰值 | 约 41.2 MiB | 约 49.9 MiB |
| 最后一次浏览器任务的工作进程总耗时，含启动 | 0.646 s | 3.617 s |

前一组独立测量 `...small-cases-20261022-02` 的单板预热中位数为 2.983 s，和最新一组存在明显波动；两组原始数据均保留，未择优替换。跨进程/运行状态的耗时稳定性仍需完善，不把这些数字作为三层建筑性能承诺。浏览器加载与首帧显示另测，不能混入求解推进时间。

### 专项验证和证据目录

- 主环境相关合同、载荷、看护、产物、服务/API、页面接入、原压力与工作区专项：62 passed。
- 独立求解环境柱/板/瞬态专项：14 passed，无 skip。
- 原固定建筑本地 HTTP/两立方体 K 包专项：3 passed。
- Node 延迟请求专项：2 项通过，覆盖旧轮询覆盖当前取消目标、初始历史加载覆盖新来源。
- Chrome/CDP 最终专项：14 项通过，`artifacts/cpu-response-browser-20261022-06/checks.json`，含两次真实小求解、回放、CSV MIME、历史 URL、移动布局、干净/未保存 K 工况导航；对应位移/钢筋截图同目录。
- 静力九组原始结果：`artifacts/cpu-response-static-20261022-01/`。
- 柱完整时窗细化及板超时：`artifacts/cpu-response-convergence-20261022-01/`；板 15 ms 四组对照：`...convergence-20261022-02/panel/`。
- 独立实施审查已完成一次，提出的旧请求覆盖、冷跑报告空值、独立层参考、环境身份、曲线样本预算和历史 URL 问题已处理并有相应专项证据。

所有记录保留，包括早期浏览器失败/板超时。未运行全量、重型、三层建筑或 LS-DYNA；原 Playwright 全预览脚本未运行，已执行本轮 CDP 导航与小夹具 HTTP/K 专项。没有清理、提交或合并用户已有工作。

复现基础性能：`python scripts/benchmark_cpu_response.py --case column --matrix baseline --wall-budget-s 180 --case-timeout-s 30 --output-dir <新空目录>`；panel 同理。早期窗口须显式加 `--matrix convergence --duration-ms 15`；默认仍为完整 150 ms。两类命令都只选小算例，不包含默认 smoke；无需、也不得为此追加整栋或重型案例。

## 后续路线图：S3—S5

### 2026-10-22 继续授权：柱板体系的小装配与映射

用户在小算例收敛通过后明确选择：柱与楼板承重，填充墙传递压力并计入质量。继续沿现有 S3c/S4 路线实施，先增加以下可独立核验的内容；不启动真实整栋测试。

- [x] `building.py`：读取并校验封存语义 JSON，按角色与材料分类柱、混凝土板/屋面和填充构件；保留原始顶点、原生包围范围及差异，输出未核验连接/配筋/基础等缺项，不把包围盒当原生实体。
- [x] `assembly.py`：四根纤维柱、可弯曲分层配筋板，柱顶至板中面的真实厚度偏心采用局部刚臂；只在连接处约束，不设置整层刚性楼板。复用已验证截面构造。
- [x] 填充墙先采用沿高度简支条带的均布荷载传力：上下两边各分一半的力与质量，沿各支承边分段形函数分配到全部边节点；保持合力、力矩与柔性边虚功。墙净高止于板底，偏心传力与附加质量使用一致局部刚臂，无 MP 约束链。此模式不计算墙局部挠曲、破坏或其承重刚度，实际建筑映射须另核验支承边；本轮小装配只做静力和模态检查。
- [x] 专项先 RED 后 GREEN：微型语义夹具的分类与篡改拒绝；墙力矩/质量守恒；单跨静力反力平衡、柱板偏心运动一致、局部板挠曲保留、正的低阶固有频率。真实小装配每条命令仍受 30 s 看护。
- [x] 实际三层模板只做只读清点并保存带指纹的映射清单；原 K 页面及来源合同不改，整栋计算入口仍以连接、配筋与规模核验为门槛。

这些阶段的范围和接口在本计划保留，具体经验数据集、非线性板材料及本建筑结构体系需在进入对应阶段时冻结并细化任务；近期交付不依赖猜定它们。

| 阶段 | 主要文件与验证 | 进入条件与交付 |
| --- | --- | --- |
| S3a 材料能力扩展 | 新增材料方案文件、`tests/test_cpu_response_materials.py`；单柱 Concrete02/Steel02 材料路径与轴弯构件；单板兼容平面应力材料、配筋层与构件参考 | 弹性基线已过；冻结有来源的完整参数与参考结果后，按已验证能力开放非线性、动力增强及相应状态，不能直接套地震示例宣称爆炸验证 |
| S3b 经验荷载 | 新增 `empirical_loads.py`、参考表/实现清单和 `tests/test_cpu_response_empirical_loads.py`，复用 `loads.py` 守恒接口 | 冻结可使用的 Kingery–Bulmash/CONWEP 类实现或参考表、版本、适用域及测点数据；比较峰压/冲量/到达时间，通过后开放表面压力场 |
| S3c 单跨柱板 | 新增 `assembly.py`、`tests/test_cpu_response_assembly.py`；连接、边界、刚体/机构、载荷和反力检查 | 小算例已过，梁柱—板壳偏心与连接方式明确；装配不增加虚构刚度，不能把板壳局部挠曲用整层刚性约束消掉 |
| S4 三层映射与计算 | 新增 `building.py`、映射清单和 `tests/test_cpu_response_building.py`；扩展 service 来源为 pressure_scene，初期测试仅用三层微型夹具 | 核验 36 柱、板墙/井筒及缺失梁角色，明确承重体系、质量/刚度和配筋、真实连接与模板指纹；先估规模与耗时，再按用户规则决定整栋验证范围 |
| S5 三页互通与 K | 修改原导航、压力页和 response 页，扩展 API/浏览器/K 导出专项，更新 README.zh-CN.md | 同一 scene/revision 往返、未保存输入处理、CPU 独立参数、旧 K 输出内容与行为验证；CPU 的新经验配置不自动写进旧 pressure config |

S4 不把显示包围盒直接当求解实体，不把填充墙静默当剪力墙，不凭参考配筋推断原建筑真实抗爆能力。小算例结果不能直接外推为整栋耗时或真实爆炸误差。

## 计划自检与交接

- 设计第 1—4 节由任务 1—5落实近期范围；经验荷载、非线性与建筑信息的后续决策归 S3—S4，不在近期实现中隐式补齐。
- 第 5 节由任务 5、6、8覆盖；第 6—7 节的近期页面/来源/任务由任务 7—8覆盖，整栋与 K 联动专项归 S5。
- 第 8 节的柱、板、收敛、守恒、结果真实性由任务 2—5覆盖，性能由任务 6覆盖；物理精度与真实爆炸误差不混淆。
- Review Focus 五项分别落实到指定任务的测试，不依赖默认 smoke。资源预算、专项/重型授权及已有修改保护贯穿所有任务。
- 实施由主会话完成，必要独立数值审查只读进行。小算例空间/时间/性能门槛通过，S3c/S4映射和单次整栋CLI首试已完成；整栋收敛、网页整栋与经验爆炸/非线性能力仍未开放。

## 续轮验收与柱板扩展

### 新一轮 S4：原生核验到首个试算准备

用户继续授权完成三层连接、配筋和质量映射。沿用本设计的柱板体系，不重新要求一般开发确认；实际整栋试算的范围/预计耗时说明和当次授权仍独立保留。

- [x] `building_source.py` + 微型 K 夹具：逐个核对封存文件哈希，读取真实 Hex8 及钢筋梁；由原生体积、材料密度、钢筋直径/长度建立质量账目，保留真实纵筋坐标与板筋层位/方向，不套用小算例配筋。非轴对齐实体积分真实 Jacobian，不以包围盒替换。
- [x] `building_mapping.py` + 微型三层夹具：建立层间连续柱、柔性板片共边、实际筋位和填充传力映射；用户明确选择恢复设计柱截面的独立参考，扣除原所有者体积，保留原 K；检查连通性与主从约束无链。
- [x] 原生微型三层专项：正的低阶频率、质量与载荷/反力平衡、真实钢筋响应、短时及完整150 ms动力回放和看护；不采用单板四分域或面内零块。
- [x] 封存可审查的真实模板参考映射、质量/配筋报告和试算输入。ready只表示进入首试，未宣称真实整栋原生组装/动力验收通过。
- [x] 显式单次 CLI 入口已准备，默认 prepared_only；专项、独立只读审查及代码检查已完成。首试范围、预计耗时及预算见下。
- [x] 按根 AGENTS.md 说明范围和预计60—150s、180s截止，用户回答“同意，运行这一例”；仅执行case04一次，父进程97.947s完成，原始结果、实际云图/曲线及报告保存。不运行全量或原有重型组。

### 完整时窗验收（2026-10-22，最终代码身份）

正式证据为 [acceptance-07](../../../artifacts/cpu-response-acceptance-20261022-07/validation/acceptance.md)，逐项指标、非零能量漂移、周期、峰时、钢筋采样位置及身份见同目录 `acceptance.json`。六个独立受控任务均完成 150 ms，组合为 16 / 0.1 ms、32 / 0.1 ms、32 / 0.05 ms；分别 1500、1500、3000 步。六例代码身份一致且与最终适配器一致。

| 算例 | 空间位移变化 | 空间钢筋峰值变化 | 步长位移变化 | 步长钢筋峰值变化 | 32 / 0.05 ms 进程总耗时 |
| --- | --- | --- | --- | --- | --- |
| 柱 | 0.1186% | 0.0676% | 0.0121% | 0.5654% | 5.451 s |
| 板 | 0.2311% | 0.8288% | 0.0435% | 0.0003% | 7.864 s |

所有非零峰值及周期变化 ≤2%，峰时变化满足 2% 或一个粗步长，卸载后的非零能量漂移 ≤0.5%，每例 <30 s。32 / 0.1 ms 板位移绝对峰值 0.127400 mm、钢筋绝对峰值 2.760256 MPa；32 / 0.05 ms 为 0.127345 mm 和 2.760248 MPa。原始 8→16 未通过记录并未更改；本轮采用更细网格证明收敛，未放宽阈值或缩短时窗。

复现：分别执行 `python scripts/benchmark_cpu_response.py --case column --matrix acceptance --output-dir <新根目录>/column` 及相同选项的 panel；然后 `python scripts/validate_cpu_response_acceptance.py --root <新根目录> --output-dir <新验证目录>`。默认单例 30 s、命令 180 s 上限不变，acceptance 拒绝 15 ms 短窗口。验证脚本只读已保存清单与结果哈希，不启动求解；还强制相同物理模型/代码身份、恢复法的原生钢筋核对及完整动态基底。

### 超时根因及等价加速的边界

原细板每步重新分解相同弹性切线，并逐个钢筋样本调用原生记录器。修正分为三层：

1. 只在实际 dt 相同的弹性步复用分解；拐点短步及恢复常规 dt 都重建。非整除 0.3 ms 对照已覆盖全部曲线。
2. 批量读原生壳截面应变，以弹性 `Es·(ε0−zκ)` 恢复 0°/90° 配筋层；先刷新当前节点状态，避免 ShellMITC4 缓存滞后一拍。保存帧和刷新峰值均用原生纤维核对，偏差超限直接失败。4×4 / 150 步的每个样本与原生读取逐一比对。
3. 仅对冻结的均布横向荷载、平坦、对称 B=0 配筋板，使用精确四分之一对称域；由原生 K/M 消去无质量转角，保留该域全部有质量自由度，完整基底中推进 Newmark。16、32 网格分别保留 64、256 个动态自由度，无模态截断。显示与质量账目恢复完整物理模型。未受载的面内块保持零状态。这些对称与解耦条件不用于三层建筑。

保留原生全域/原始读取/不缓存路径做独立对照：4、8 网格的曲线、速度/加速度、反力、能量、共同帧全部节点位移/转角和钢筋场在声明容差内一致。真实积分峰值帧与首末帧必保留，其他动画帧按数据体积抽稀；钢筋均值着色与原始积分点峰值分别标明。

原生命令和缓存行为参考 [Linear.cpp](https://raw.githubusercontent.com/OpenSees/OpenSees/master/SRC/analysis/algorithm/equiSolnAlgo/Linear.cpp)、[ShellMITC4.cpp](https://raw.githubusercontent.com/OpenSees/OpenSees/master/SRC/element/shell/ShellMITC4.cpp)、[setNodeDisp](https://openseespydoc.readthedocs.io/en/latest/src/setNodeDisp.html)；实际版本的正确性由本机原生对照检查，不只依据文档。结果仍仅限弹性数值参考，不是实际爆炸误差声明。

### 已执行的柱板扩展

用户明确选择柱板承重，填充墙传力并计质量。已增加 `assembly.py` / `building.py`，并提取复用已验证的柱、板截面定义，原数值参考不变。

- 单跨为 2×2 m、3 m 高的数值参考：4 根纤维柱（8 单元）与 4×4 分层配筋板，40 节点。只在柱板及墙支承点使用板厚偏心刚臂，无整层刚性楼板、无 MP 约束链。
- 1 kPa 竖向板荷载合力 4000 N，基础反力 4000 N；板中挠度 −0.021366 mm，角点 −0.001005 mm，局部弯曲仍存在。连接位移差约 5.5e−21 m，最低六个特征频率均正，第一项 11.106 Hz。数值及原生钢筋读数见 [single-bay.json](../../../artifacts/cpu-response-building-mapping-20261022-01/single-bay/single-bay.json)。该报告仅为静力与模态，不冒充爆炸动力验收。
- 墙采用物理净高 2.85 m，面积 5.7 m²、质量 2052 kg。上下支承边分配各半载荷/质量，上沿全部五个边节点按分段形函数受载；墙板中面偏心同时用于传力与质量。水平受载另核对基础总力、总矩，墙无承重刚度。独立审查发现的“只集中在角点”问题已修正，有失败复现和通过记录，并经只读复核确认。
- 真实模板只读清单在 [inventory.md](../../../artifacts/cpu-response-building-mapping-20261022-01/inventory.md) / `inventory.json`：36 柱、33 混凝土板/屋面、277 填充构件、485 其他构件，共 831；10 个语义范围与原生范围有差异。没有 beam 角色，plaster 井筒不当核心筒；电梯超高顶盖、楼梯、基础和其他附属构件须单独解释传力及质量。

上一轮 `scripts/inspect_cpu_response_building.py` 只做语义清点，`ready_to_solve=False`；彼时原生连接、配筋及质量未核验，未运行实际整栋。新一轮已完成独立规整参考映射及首个全域工况，见下面 S4 结果。旧清单继续保留；不得把单板对称加速用于建筑。

### 最终专项与界面证据

- 主环境运行相关合同、载荷、看护、产物、服务/API、页面、验收及微型映射，加原压力/工作区：70 passed / 4.53 s。
- 原生柱/板/瞬态/优化 21 项通过；单跨最后净高/边线分配修正后专项 1 passed / 0.60 s。无 skip。非整除 dt、全域/四分域、完整基底/原生、原生钢筋读数和峰值帧检查均覆盖。
- 原本地 HTTP / 两立方体 K 导出专项 3 passed / 5.02 s；Node 延迟响应 2 项通过，三个页面模块语法检查通过。
- [浏览器最终 14 项](../../../artifacts/cpu-response-browser-20261022-07/checks.json)通过，无 JS 异常；默认 32 网格的真实柱/板任务、原始积分点说明、双向上下层选择、历史/下载、移动布局和原 K 页面干净/未保存导航均覆盖。截图同目录，单板峰值云图已人工查看；实时任务 ID 为 `ff352a234e55486eb826d6764df26af0`、`9bd5066a7ddb45038badcff1928090d4`。

上述小算例/界面验收阶段未运行全量、三个重型案例、真实三层求解与 LS-DYNA。随后获当次同意才运行下面的一个整栋首试。未清理、提交或合并用户工作；不宣称非线性、经验爆炸压力或实际建筑已验收。

## 本轮 S4 核验结果

### 已封存输入

[预备报告](../../../artifacts/cpu-response-building-preflight-20261022-04/preflight.md)、同目录 `preflight.json`、`reference-case.json`、`native-audit.json`、`sealed-template.json` 及 `reference-preview.png`。当前输入指纹为 `24de7a83aa909d5380af4f6ef5a369a67ffbebd420cba69c27b7b7ade0e640eb`。

- 原生读取445866个结构节点/310836个Hex8、509096个筋节点/248284个筋梁段；六个原始K文件SHA256均匹配。5862个非轴对齐梯步/栏杆单元按2×2×2正Jacobian积分体积与矩，不跳过、不用包围盒补量。旧preflight-02在非轴体积未补齐时保存，属于中间证据，以03/04完整审计为准。
- 用户看到柱部件范围与钢筋宿主分配问题后，明确选择独立规整参考：恢复36根300×300mm设计柱，对原所有者扣除相应体积，原K不改。恢复10.044m³、同时扣除10.044m³；原指定密度均为2400kg/m³，因此这项重新归属不改变总质量。它会改变柱板参考的承重刚度分配，不能声称原K等价。
- 170个语义标签与原K混凝土指定不一致的构件已列明。前期“纵筋落入填充材料”的表述依据语义plaster，后续实际材料卡核验已向用户更正：落入墙部件，该K中墙材料实际为9002混凝土。CPU按用户选择不计其承重刚度，保留原卡质量。
- 630个结构节点、402个分层壳、144个纤维梁柱，134个固定节点；3780个正偏心附加质量点，固定主节点的质量只列账、不生成约束链。板片共边合并、洞口保留、柱链连通固定基础，未设置整层刚性楼板。
- 36柱的4Φ16坐标不强制对称，形成7套纤维截面；原始板筋为四层Φ16，并不等于单板参考的Φ10@200。保留实际层位、等体积配筋层和非零B；Ec30GPa为明确的数值参考，Es210GPa来自原卡。箍筋/锚固/搭接计质量，不伪称已模拟约束增强或破坏。
- 总质量1431225.546kg，固定部分564816.007kg，动态部分866409.539kg。总质量、一阶矩、二阶矩相对误差约8.13e−16、2.11e−14、2.66e−15。另核对板/板筋只归本层、柱筋归柱链及本层独立平动动能，避免只过整体守恒。

### 独立审查及针对性修正

主会话实施，一名现有审查员只读审查，未代理执行测试或求解。两个Important均有RED→GREEN并只读复核确认已解决：

1. 墙荷载原先按楼层顶面分力并用跨高力偶补整体矩，整体守恒掩盖局部错误。现按实际净跨0—2.92m分简支反力，再施加支承面到板中面0.09m的偏心；真实case上下各4.5333N/Pa，端矩分别−0.407997/+0.407997N·m/Pa。专项分别检查上下力/矩及独立转动虚功。
2. 板质量原先沿层高插值而把约2.9%分给下层。现板体积和板筋质量强制归自身壳面；密度微扰测试证明异层质量增量为零、本层独立平动动能正确。柱筋质量也回自身柱链。

质量点是声明的偏心集总参考，不求墙、楼梯与附属件自身局部振型；整体惯性相符不能代替实际建筑动态精度。质量约束采用 [rigidLink](https://openseespydoc.readthedocs.io/en/latest/src/rigidLink.html)，并按 [Transformation](https://openseespydoc.readthedocs.io/en/latest/src/TransformationMethod.html) 的约束限制保证主节点不为从节点，固定质量不生成MP链。

### 首试前已执行专项与预计范围

- 主环境相关CPU、原压力/工作区及新增原生审计/映射/CLI专项：86 passed / 5.38s。
- 隔离原生环境原柱/板/瞬态/优化、单跨、微型三层及真实worker路径：26 passed / 12.57s，无skip；父进程墙钟13.20s，30s看护。无真实整栋。
- 完整微型三层另存 `artifacts/cpu-response-building-micro-20261022-01/full-window`：52结构节点、16板/24梁柱，150ms、0.1ms、1500步，含启动/写盘6.0589s，内核1.4768s、提取3.7740s；峰位移0.44163mm、峰筋应力3.23295MPa。只属于微型夹具，不是实际三层建筑结果。
- `run_cpu_response_building.py --case ...` 实际只读执行成功，返回prepared_only；未加--run，未偷偷启动真实建筑。新Python语法及原相关diff检查通过。前端本轮未改，未重复浏览器/HTTP或全量测试。

当次请求并获同意的首试：**仅case04一例**，原生全域线弹性纤维柱/分层壳，无模态截断或四分域。压力施加于`F0.west.front.0`的south面，规整后9.0666m²；1ms达10kPa、10ms卸载、总时窗150ms，步长0.1ms、1500步，最多一个受控worker。运行前基于微型全时窗及模型规模，预计60—150s；父进程硬上限180s，内存按20ms采样。只产出位移、原生柱/经原生核对的板筋轴向应力、曲线和诊断，不作损伤结论。

用户回答“同意，运行这一例”后执行：`python scripts/run_cpu_response_building.py --case artifacts/cpu-response-building-preflight-20261022-04/reference-case.json --run --output-dir artifacts/cpu-response-building-trial-20261022-01`。仅执行一次，未重跑或追加实际工况。超时/不收敛/身份或产物校验失败均不算通过。原K、旧页面和benchmark API保留，网页整栋按钮仍关闭。

### 真实整栋首试结果（2026-10-22）

[完整报告](../../../artifacts/cpu-response-building-trial-20261022-01/analysis/report.md)、[变形/钢筋云图](../../../artifacts/cpu-response-building-trial-20261022-01/analysis/deformation-and-steel.png)、[响应曲线](../../../artifacts/cpu-response-building-trial-20261022-01/analysis/response-curves.png)及[结构化摘要](../../../artifacts/cpu-response-building-trial-20261022-01/analysis/summary.json)。原始输入、结果、CSV、manifest和父进程测量位于上一层目录。

| 核验项 | 实际结果 |
| --- | --- |
| 进程结果 / 父进程墙钟 | completed、exit0 / 97.9468s，低于180s |
| 建模 / 数值积分 / 场量读取与核对 | 0.0537 / 35.9026 / 60.5898s |
| RSS采样峰值（20ms间隔） | 118.61MiB |
| 完整时窗 / 步数 / 曲线 / 帧 | 150ms / 1500 / 1501 / 29 |
| 原生节点 / 结构节点 / 附加质量链接 | 3606 / 630 / 2976，无模态截断或四分域 |
| 位移幅值峰值 | 0.0807014mm，58.9ms；节点零基索引269，参考位置(0.15, −1.6, 3.01)m |
| 钢筋轴向应力绝对值峰值 | 1.508288MPa，25.6ms，为拉应力；`e150-ip4-bottom-X`，`F1.floor.0`底层X向板筋积分点 |
| 原生板筋应力/应变核对 | 3,421,824次；每帧8160个钢筋样本 |
| 11—150ms卸载后机械能 | 约0.51181443J，相对范围4.36e−14，无阻尼 |

读取已保存manifest验证原始结果与CSV的SHA256，校对输入/适配器身份、来源、全时窗有限值、真实峰值帧及所有帧极值上界。报告和Matplotlib图只读保存结果生成，没有再启动求解。变形显示放大3000倍；位移面颜色为节点均值，峰值仍取原始节点；钢筋图取单元内原始钢筋采样点绝对值最大值，不平滑。屋面监测点曲线与全楼空间位移峰值分开说明。出图时Matplotlib对混合长度线段自动缩放的错误已改为显式范围，随后生成成功并人工检查。

本例通过**一次参考模型的稳定运行、结果完整性与180s预算**检查。整栋空间/时间收敛未执行，线弹性原始板筋采样值不能解释为实际开裂/屈服后的单根钢筋结果；给定单墙压力也不是求得的空气爆炸压力场。没有运行第二个实际工况、原重型组、全量回归或LS-DYNA。进一步整栋工况/收敛矩阵按根AGENTS另说明范围和耗时并取得当次同意；页面接入属于后续S5，不因本例自动开放。
