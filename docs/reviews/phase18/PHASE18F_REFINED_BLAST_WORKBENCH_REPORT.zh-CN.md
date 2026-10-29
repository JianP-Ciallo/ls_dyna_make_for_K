# Phase 18F 精细化建筑爆炸工作台：软件验收报告

## 结论

Phase 18F 的实现代码已完成软件矩阵与独立复审闭环：最终复审的开放代码问题为
`Critical 0 / Important 0 / Minor 0`，代码状态为 **Ready**。工作台的 API、浏览器状态、
九层预览、验证/确认/生成门、不可变工件读取和显式外部动作授权均在本报告所列的软件边界内通过。

2026-08-20 已在当前功能 HEAD `0dd6fb004230bfafb1b5b876615d03e5ace133a5` 上补齐三条
fresh heavy 端到端 JUnit 终态：explicit/commercial、imported/residential 与 LBE/subway 均为
`1 passed / 0 failures / 0 errors / 0 skipped`。因此 Phase 18F 的**软件验收现宣布 PASS**；工程验证与
真实求解就绪边界仍然不变。

| 门禁 | 结论 |
| --- | --- |
| 实现代码与常规软件矩阵 | Ready / 通过 |
| 独立代码与规格复审 | 开放代码问题 0 |
| fresh heavy Task 8 证据 | 三项 fresh JUnit 全部 PASS |
| Phase 18F 软件验收 | PASS |
| 工程验证 / 求解就绪 | 未执行 / 不成立 |

所有精细化输出继续永久声明：

| 标志 | 值 |
| --- | --- |
| `solver_ready` | `false` |
| `requires_project_review` | `true` |
| `external_program_started`（生成操作） | `false` |
| 工程验证 | 无 |

本轮启动 LS-PrePost、LS-DYNA 或其他外部工程程序的次数为 **0**。

## 审核范围与提交

- Base：`63a9c55479973a623baf9de6595b1e67629f96c9`
- 最终实现 HEAD：`3b1f4f4bd047d987254f6f2d2b423a5916ff28de`
- 范围：31 个实现/测试/设计提交，49 个文件，`+11,119 / -76`
- 正式报告在实现复审完成后单独提交，不改变上述已复审实现范围。

提交按功能分组如下：

- Task 1 API/事务/租约：`a8d4ce6`、`fb36e92`、`d45f1b6`、`8ca49d0`、
  `a799664`、`816836f`、`94f1c1e`、`6ae7d0f`、`54b3f59`。
- Task 2 隔离入口：`f57972d`、`c1e3c6e`、`2ac15c7`。
- Task 3 schema 驱动状态：`4629739`、`8e04a1e`、`fdb2fe4`、`2055897`、
  `66be8d5`。
- Task 4 预览：`f768b8a`、`975cc84`、`cc0a92e`、`67deb59`。
- Task 5 验证门：`e69bc0d`。
- Task 6 外部动作设计/实现：`7ed1a5e`、`045960c`。
- Task 7 端到端与生命周期：`081c42d`、`655f944`、`d54e244`、`399ec84`。
- Task 8 验收修复：`de5d096`、`896646c`、`3b1f4f4`。

## 最终实现能力

### API、Store 与生成事务

- 独立命名空间 `/api/refined-building-blast`，闭合 JSON 请求、大小限制、本地主机/同源检查，
  未支持方法（含 TRACE）统一返回稳定 JSON 405；精细化 POST 拒绝任意 query 参数。
- 项目级线程/跨进程租约覆盖读取权威状态至响应快照，支持重入、关闭等待和异常释放。
- create 事务、building recipe、初始项目证据和请求指纹均持久化并相互绑定；save 使用 revision CAS。
- project/scenario/route/Store 共享同一 ASCII safe-ID 语法。
- 生成先发布工件与索引，最后推进项目 revision。索引写失败不会使旧 revision 失效；相同重试可复用
  已暂存工件/索引。
- 索引路径必须精确等于当前 project/scenario/revision/store fingerprint 所推导的唯一文件路径。

### 浏览器工作台

- `/refined-building-blast` 与尾斜杠形式直接启动时不取旧工作台数据；返回旧工作台时只初始化一次旧状态。
- schema 驱动 asset/system/provider/ScenarioDraft，递归裁剪未知字段，保存串行化并隔离 stale、跨 mount
  与延迟恢复响应。
- 生成只接受 issued revision 的精确下一 revision，原子推进浏览器持久 revision，消费旧 validation/
  acknowledgement/gate/preview，再安装生成 identity；并发 Generate 被去重。
- 真实 localhost HTTP + Node 全局 fetch 路径覆盖 legacy entry、create、save、preview、validate、
  acknowledge、generate、artifact read、URL reload、back/unmount、forward/remount 和双项目隔离。

### 预览、验证与外部动作

- 预览有九层、八项计数、确定性全域 LOD、分层上限和 evidence/fingerprint 复算；旧 mount、旧 revision、
  dirty draft、失败保存与冲突均使派生结果失效。
- warning 确认绑定 finding 内容哈希、validation 指纹、project/scenario/revision；generation gate 由服务端
  权威产生。
- Generate、Open LS-PrePost、Launch LS-DYNA 是三个独立动作。外部动作需要短 TTL、一次性、
  action/project/package identity 绑定的 nonce。
- action snapshot 通过 Store 的锚定目录/原子字节写发布，并在 delegate 前逐文件重新打开、计算 SHA-256；
  response 不泄露绝对服务器路径，并返回完整 identity 供浏览器逐字段核对。
- LS-DYNA handoff 将 snapshot 的完整 include closure 复制到真实运行 cwd，不再只复制 `model.k`。

## fresh 常规软件证据

所有下列命令均在实现 HEAD `3b1f4f4` 上以单进程串行执行；未启动外部工程程序。

| 矩阵 | 结果 | pytest 时间 |
| --- | ---: | ---: |
| 全部 `test_phase18f_*.py -m "not heavy_provider_e2e"` | 139 passed，3 deselected | 26.30 s |
| `test_web_*.py` | 128 passed，31 subtests | 29.61 s |
| Phase 17 三文件 | 46 passed，3 subtests | 53.86 s |
| Phase 18A-D compatibility/fingerprint | 277 passed，278,281 subtests | 136.76 s |
| Phase 18E，精确排除批准 subway heavy node | 243 passed，2 skipped，1 deselected | 43.17 s |
| legacy core/Web/city/solver-support | 717 passed，7 skipped，142 subtests | 406.19 s |
| LS-DYNA runner 回归（process 为测试替身） | 38 passed，7 subtests | 0.80 s |
| packaging/distribution safety | 20 passed，13 subtests | 60.96 s |
| JS runtime carrier | 83 passed，3 deselected | 6.72 s |
| 独立复审 focused 回归 | 11 passed，77 deselected | 1.92 s |

附加静态门禁：

- `python -m compileall -q lsprepost_mcp tests scripts`：exit 0，0.163 s。
- bundled Node v24.19.0 `--check`：6 个 production JS 与 7 个 runtime CJS，共 13 个文件均 exit 0。
- `git diff --check`、cached diffcheck 与实现提交后的 `git status --short`：干净。
- packaging 使用 .NET SHA-256 stream，不再依赖 Windows PowerShell 进程能否发现 `Get-FileHash`。

legacy 矩阵所需的三个 `examples/complete_solver_cases` 目录为 Git-ignored 测试前置物。它们从主工作区
只读复制，完整矩阵通过后验证目标仍位于 `examples/complete_solver_cases` 下并移除；工作树最终干净。

Phase 18E 的 2 个 skip 是当前 Windows 账户不能创建普通 symlink 的既有平台跳过；junction/
reparse-point 保护仍实际执行。legacy 矩阵的 7 个 skip 是未授权真实集成环境门；本轮显式清除了
`LSPP_INTEGRATION` 与 `LSDYNA_INTEGRATION`。

## 提供器、资产与指纹证据边界

公开 heavy 参数映射恰为：

| provider | public asset |
| --- | --- |
| `explicit_ale_fsi` | `commercial_supermarket_detailed_building` |
| `lbe_segment` | `subway_entrance_detailed_building` |
| `imported_pressure_history` | `residential_community_detailed_building` |

Phase 18A-D fresh compatibility矩阵保持 5 个 Phase 18C 固定指纹不变。Phase 18E 历史、真实 Phase 18C
`rc_box` 工件证据为：

- building artifact：`3900d59b2a27813c93e71678a9b443e99264460fae67b80e5f951bfb8e1423c1`
- topology：`b246a3c4b173f8bbfd3a3318550c1b2292cfd627db10249994b938a968fc55bc`
- controls fragment：`4cab21dad5c1e6a643067172e1a8e34097fba40d67657adbed9e9496937ff478`
- outputs fragment：`071ec9e9b1d8d93241aee63072d8ce12d3e3b115a5d0ec2d5c47a2c901fae62a`

批准地铁入口的历史真实证据为：

- building / topology：
  `f2c61ce690341c567d3532484351e59b84714634cc6314d3089791645b3c3a79` /
  `9708d81e17acf51611502a5b311f85eef9d7eaa1ca6ef25a018b6f8bd28d0703`
- LBE input / estimate / fragment / preview：
  `7cec4970cd7ef4659b73a3999ebe3e35f697eab7b7dfd04a4386657972c26379` /
  `d1d929464f5c4594111447c95df12ede364648f1f8d5e86299bbc552431beacc` /
  `9e0e2af95195ad24f3baed8c230b0fa1e9353b4add909b9925b1c10a5b989701` /
  `2872ab71c38db7040ea6f22fd45dd5c118395269791c983cb6280f53b26453c3`

这些指纹用于兼容性边界；fresh Task 8 heavy 结果以本报告下一节的三份 JUnit 为准。

## fresh heavy 最终证据

三项均在 2026-08-20、同一代码 HEAD `0dd6fb004230bfafb1b5b876615d03e5ace133a5` 上串行运行；
每项完整覆盖 create → save → preview → validate → acknowledge → generate → artifact-read，生成动作均保持
`external_program_started=false`，未启动 LS-PrePost 或 LS-DYNA。

| provider / asset | JUnit 终态 | pytest 总耗时 | JUnit SHA-256 |
| --- | --- | ---: | --- |
| `explicit_ale_fsi` / `commercial_supermarket_detailed_building` | 1 passed，0 failure/error/skip | 455.94 s | `f14670c66e7dc5ed8d033fb3b617c3978a4dd87fc56ba8cc088f584822db72da` |
| `imported_pressure_history` / `residential_community_detailed_building` | 1 passed，0 failure/error/skip | 250.24 s | `ac858cc43a4cc47fc1f3e7e7b227bdb16a169e7e9cdff4f7855879220a917a32` |
| `lbe_segment` / `subway_entrance_detailed_building` | 1 passed，0 failure/error/skip | 6523.45 s | `277700ba53d10c269ff2dd0e9874895b0457f3c43cff8c74d0fd0254b2afd445` |

证据文件：

- `PHASE18F_HEAVY_E2E_EXPLICIT.xml`
- `PHASE18F_HEAVY_E2E_IMPORTED.xml`
- `PHASE18F_HEAVY_E2E_LBE_SUBWAY.xml`

性能仍是已知关注项：地铁入口完整链路耗时 1:48:43，其中 preview 1750.488 s、validate
1208.413 s、acknowledge 1768.817 s、generate 1665.558 s。该结果满足正确性门禁，但明显需要后续缓存与
重复权威重编译优化；正确性测试继续不使用与需求无关的固定 wall-time 阈值。

## 独立复审

初次全范围独立复审覆盖 Base 至 `896646c` 的完整实现，结果为：Critical 1、Important 8、
Minor 3，Spec FAIL / Ready No。唯一修复波次 `3b1f4f4` 解决了浏览器生成 revision 对账、完整 LS-DYNA
include closure、生成发布顺序、ID 语法、action snapshot 防护、project-bound artifact path、JSON 405、
direct refined 返回旧工作台、POST query、绝对路径泄露与 action response identity。

限定复审只核对原 12 项，结果：

- Critical：0 open；
- Important：0 open code finding；原 fresh heavy 证据 concern 已由 2026-08-20 三份 JUnit 关闭；
- Minor：0 open；
- 12/12 resolved；
- Code readiness：Yes；Phase 18F software acceptance：PASS。

## 工程边界与后续门禁

本阶段没有验证 LS-DYNA keyword 的真实导入成功、单元质量、接触稳定性、材料卡标定、爆炸载荷
适用性、ALE/FSI 收敛、质量/能量平衡、网格独立性、压力时程来源或工程等效性。用户在任何真实
求解前必须逐项目审核几何、构件、钢筋/连接、材料/失效、支承/边界、装药、空气域、耦合、控制、
输出与版本兼容性。

fresh heavy 最终证据门现已满足，因此 Phase 18F 可记为软件验收 PASS。该结论不改变工程边界：
`solver_ready=false`、`requires_project_review=true`，真实 LS-PrePost 导入、LS-DYNA 求解以及工程适用性
仍需独立完成。
